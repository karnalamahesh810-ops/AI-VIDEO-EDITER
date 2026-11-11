"""
The storm desk style (video_style "storm_desk", src/styles.py): a breaking-news compilation in the measured
Global Storm Desk format (docs/style-refs/global-storm-desk/STYLE.md), in the customer's own brand, under the
owner's rules for it (2026-11-02, the Henderson and Sedona laptop builds, tools/storm-desk/):

  * real footage first; AI shots only when the job turns AI fill on, and never in the first 60 s;
  * every narration shot <= 5 s, hard cuts only;
  * 7-second natural-sound pauses: the narration stops, one continuous clip plays with its own sound;
  * clip sound fully muted under the narration (the renderer always mutes clips; the pauses are mixed in after the
    render, below), an optional music bed of the user's own track ~21 dB under the voice and 3 dB lower while
    a word is spoken, the master at -14 LUFS;
  * never the same footage moment twice, never two shots in a row from one source (channel), a per-source share
    cap (~7% of the runtime, reported; the planner's per-video caps hold it), a look-alike check (CLIP);
  * every clip credited on screen ("VIDEO: <channel>"; older uploads "ARCHIVE"; AI shots "AI ILLUSTRATION"),
    platform logos and source bugs found in a clip's corners blurred, an optional mirror flip per source (never
    on a clip with text or marks, or a named landmark);
  * the graphics of the reference in the customer's colours and logo: the logo bug always on, a two-line lower
    third at every narration block (11 s), the location / date chips at 1-9.5 s, the subscribe pill at 50 s and
    every 120 s (remotion components/brand/StormDesk.tsx reads doc.stormDesk);
  * a clean delivery file (no encoder tags) whose picture is exactly as long as the timeline;
  * a source blocklist (the owner's: Desert Rat Explorations; the job's "blocked_sources" adds to it).

The flow inside the worker:
  plan:    plan_pauses() on the narration's words, before anything else reads them -> pad_narration() (the
           silences go into the narration file itself, so every later step - the planner, the music, the
           editor - sees one consistent timeline) -> the usual plan -> finish() on the finished document.
  render:  after_render() on the drawn file: the pauses' own sound mixed in, -14 LUFS, clean metadata, the
           picture's length checked against the timeline, and the per-video report completed.

Job options (all optional) under inp["storm_desk"]: pauses ("auto" | a count | narration seconds | 0),
pause_seconds (7), open_clip (true: the video opens on a 4-7 s clip with its own sound before the narration),
open_seconds (6), clip_sound ("ambient": clips whose own sound is natural play quietly under the narration,
UNDER_VOICE_DB below the voice and ducked further on every word; "off": silent under the narration),
headlines (one per block, in order), location, date (as shown, "NOV 1, 2026"), event_date (ISO, for the
ARCHIVE label and the upload-date check), tab ("BREAKING NEWS"), subscribe (true), mirror ("off" | "auto"),
blur_marks (true), lookalike (true), channel_name, logo_url (this video's logo; the brand kit's otherwise),
colors {logo, logo2, bar, bar2, tab, tab2, divider, place, date, pill, text}. inp["blocked_sources"]: channel
names never used (adds to the owner's list).

What the editor may change after the plan (the render reads it from the timeline): doc.stormDesk.clipSound
{"mode": "ambient" | "off"}, scene.clipSound (true / false: that clip's own choice, over the mode),
doc.stormDesk.logo {"url", "text"}. Every clip's sound class is kept at scene.media.clipAudio (src/clipaudio.py).
"""
from __future__ import annotations

import datetime
import json
import math
import os
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

STYLE = "storm_desk"

PAUSE_SECONDS = 7.0             # the owner's natural-sound pause (one continuous clip with its own sound)
PAUSE_MIN_GAP = 45.0            # narration seconds between two pauses at least
PAUSE_EVERY = 105.0             # "auto": about one pause this often (the laptop videos: 6 in 12:49)
PAUSE_FIRST_MIN = 15.0          # never before the hook has been said
PAUSE_TAIL = 20.0               # nor in the last seconds of narration
PAUSE_MAX = 12
SHOT_MAX = 5.0                  # every narration shot (the owner)
NO_AI_SECONDS = 60.0            # no AI shot in the first minute (the owner)
SOURCE_CAP_SHARE = 0.07         # one source's share of the runtime (the owner: ~6-7%)
LOOKALIKE = 0.95                # CLIP cosine of two shots' frames that counts as the same picture
LT_LEAD, LT_HOLD = 0.8, 11.0    # lower third: in 0.5-1.5 s after the block starts, ~11 s on screen
BLOCK_MIN, BLOCK_MAX = 20.0, 55.0
LOC_FROM, LOC_TO = 1.0, 9.5     # location / date chips (measured)
SUB_FIRST, SUB_EVERY, SUB_HOLD = 50.0, 120.0, 5.5
HEADLINE_LINE = 26              # characters a lower-third line holds (measured 25-26)
NAT_LUFS = -20.0                # a pause clip's sound before the master (the laptop mix)
NAT_FADE = 0.2
J_LEAD = 0.35                   # a pause's sound starts this much before its picture (a J cut)
L_TAIL = 0.6                    # ... and fades out under the narration's first words after it (an L cut)
BGM_LUFS = -39.0                # the owner's music, integrated, ~10-11% of the voice's level (kit bgm_lufs, 2026-11-06) ...
BGM_ONLY_UNDER_VOICE = True     # ... and only while he speaks: none during a clip's own sound (kit bgm_only_under_voice)
MUSIC_DEFAULT = os.getenv("STORM_MUSIC_DEFAULT", "0").strip().lower() in ("1", "true", "on", "yes")
WATER_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sdkit", "ambience", "rushing_water.mp3")
WATER_SILENT_DB = -60.0         # a first hook clip quieter than this has no sound of its own (kit tools/hookwater.py)
WATER_LEVEL = 0.55
STATION_SKIP_HEAD = 3.0         # a station's source opens on a promo: nothing from its first seconds (a QR code and a CBS eye got through)
NATURAL_PAUSES_MAX = 2          # plain natural-sound pauses a video: the owner cut 3 of them as empty (2026-11-05)
TALKING_FACE_SHARE = 0.015      # a face at least this share of the frame, with speech on the clip: someone talking on camera
HOOK_CLIPS = 3                  # the opening: this many clips (the laptop videos since lp9: HOOKS = [6.0, 7.76, 8.08]) ...
HOOK_SECONDS = 20.0             # ... about this long together, each cut on its own sentence; the last dissolves into the story
HOOK_CLIP_MAX = 9.0             # one hook clip at most (the laptop's: 6.0, 7.76, 8.08)
PAUSE_MAX_SECONDS = 15.0        # a pause with someone talking runs as long as the sentence (the owner: up to ~15 s)
PAUSE_MIN_SECONDS = 3.5
TALK_PAD_BEFORE, TALK_PAD_AFTER = 0.15, 0.25   # a talking clip starts on the first word and ends after the last (word times)
MUSIC_UNDER_VOICE_DB = 15.0     # the user's own track under the narration (the owner's Hoover / Sedona mix)
MUSIC_SPEECH_DUCK_DB = 2.0      # ... and this much lower while a word is spoken
MASTER_LUFS, MASTER_TP = -14.0, -1.5
SYNC_TOLERANCE = 0.25           # seconds the picture may differ from the timeline
OPEN_SECONDS = 6.0              # the opening clip (the owner: 4-7 s of the most dramatic clip, its own sound)
OPEN_MIN, OPEN_MAX = 4.0, 7.0
UNDER_VOICE_DB = 20.0           # a natural-sound clip under the narration: this far below the voice (owner 18-22)
UNDER_DUCK_DB = 6.0             # ... and this much lower again while a word is spoken
UNDER_FADE = 0.12               # its fade at every cut (no click)
UNDER_GAIN_MAX_DB = 12.0        # a very quiet clip is lifted at most this much (no hiss brought up)
MIX_MARGIN_DB = 15.0            # the mix check: the clip sound under a word at least this far below the voice
PAUSE_TRIES = 3                 # candidate clips fetched and scored for a pause (4 for the opening)
PAUSE_SLACK = 4.0               # seconds fetched beyond the pause, to pick its best stretch
TALK_SPEECH_MIN = 0.12          # at least this much speech: the clip is cut on sentences (talk_window)
PAUSE_SPEECH_MAX = 0.6          # a pause clip talking more of the time than this is a report, not a reaction
CLIP_SOUND_MODES = ("ambient", "off")

# The owner's blocklist (2026-11-02): never this channel's footage, in any storm desk video. Since 2026-11-03 also
# the news-compilation / re-upload channels whose own graphics are burned into their footage (the owner's Las Vegas
# run showed their lower thirds and banners): the Global Storm Desk network and its look-alikes.
DEFAULT_BLOCKLIST = ("Desert Rat Explorations",
                     "Global Storm Desk", "The Mercer Report", "Weather Alert Wire", "American Weather System",
                     "Global Weather Network", "Planet Weather", "Storm Global", "Storm Desk USA",
                     "Weather Impact USA", "Disaster Wire")
# The list entry that also turns down channels NAMED like such a compilation desk ("<Global|Planet|US ...> Storm /
# Weather / Disaster <Desk|Wire|Network|Impact|Report ...>"), and the prefix of a name that is always allowed (the
# customer's own channel: "!US Weather Alert").
AGGREGATORS = "@aggregators"
_AGGREGATOR = re.compile(
    r"^(?:the\s+)?(?:global|planet|world|us|usa|u\.s\.|american|america's|national|daily|breaking|live|extreme|"
    r"severe)?\s*(?:storm|weather|disaster|climate|flood|catastrophe|nature'?s?|earth)\s+(?:desk|wire|network|impact|"
    r"report|alert|alerts|tracker|hub|zone|global|central|watch|files|chronicle|news|today|daily|now|usa|us|tv)"
    r"(?:\s+(?:usa|us|news|tv|live|daily|network|report|hd|channel))?$", re.I)

# The reference's colours (STYLE.md 3.1-3.5); the customer's brand kit replaces the navy and blue.
COLORS = {"logo": "#0B2856", "logo2": "#051531", "bar": "#1B4CA0", "bar2": "#08296A", "rim": "#769CE8",
          "divider": "#DE3349", "tab": "#EF3E35", "tab2": "#C71F1A", "place": "#0E3076", "date": "#CC241F",
          "pin": "#CC2321", "pill": "#E4302A", "text": "#FDFDFA"}

_DRAMA = re.compile(
    r"\b(dead|deaths?|died|killed|kill|missing|rescue[sd]?|rescuers?|swept|trapped|stranded|evacuat\w*|record\w*|"
    r"historic|catastroph\w*|destroy\w*|destruction|collaps\w*|submerged|underwater|surge|tornado\w*|wall of water|"
    r"never seen|biggest|worst|deadl\w*|fire|flames|explo\w*|crash\w*|emergency|warning|disaster|chaos|"
    r"terrif\w*|screaming|roaring|exploded|shattered|slammed|swallowed|ripped|tore|burst|overflow\w*|breach\w*|"
    r"flood\w*|hail|lava|erupt\w*|quake|shaking|panic|gone|wiped|stay with us)\b", re.I)
_NUMBER = re.compile(r"\d")
_FILLER = re.compile(r"^(and|so|but|now|then|well|meanwhile|still|also|plus|because|here's|here is|this is|"
                     r"that's|it's|there's|today|tonight)\b[\s,]*", re.I)
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december")
_MONTH_RE = re.compile(r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b", re.I)
_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
    "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY"}
_LANDMARK_TYPES = {"landmark", "building", "monument", "place", "map", "document", "sign"}


JOB_LEDGER = None                # this job's used moments (stormledger.Ledger), set by finish()
JOB_PLACE = None                 # this job's wrong-place pattern (place_regex), set by finish()
JOB_STRICT = False               # the pieces engine's rules are on for this job, set by finish()


def is_style(inp: Optional[dict] = None, doc: Optional[dict] = None) -> bool:
    from . import styles
    if inp is not None and styles.resolve(inp.get("video_style")) == STYLE:
        return True
    return bool(doc) and str(((doc or {}).get("meta") or {}).get("videoStyle") or "") == STYLE


def options(inp: Optional[dict]) -> dict:
    raw = (inp or {}).get("storm_desk")
    return dict(raw) if isinstance(raw, dict) else {}


def clip_sound_mode(opts: Optional[dict]) -> str:
    """The job's clip sound under the narration: "off" (the default since 2026-11-06: clips play their own sound in the pauses
    only, never under the voice) or "ambient" when a job asks for it."""
    v = (opts or {}).get("clip_sound", "off")
    if v is False or str(v).strip().lower() in ("off", "none", "0", "false", "silent"):
        return "off"
    return "ambient"


def open_clip_on(opts: Optional[dict]) -> bool:
    v = (opts or {}).get("open_clip", True)
    return not (v is False or str(v).strip().lower() in ("off", "0", "false", "no"))


def open_seconds(opts: Optional[dict]) -> float:
    try:
        v = float((opts or {}).get("open_seconds") or OPEN_SECONDS)
    except (TypeError, ValueError):
        v = OPEN_SECONDS
    return max(OPEN_MIN, min(OPEN_MAX, v))


def hook_clips(opts: Optional[dict]) -> int:
    """How many clips open the video (input.storm_desk.hook_clips, 1-4)."""
    try:
        return max(1, min(4, int((opts or {}).get("hook_clips") or HOOK_CLIPS)))
    except (TypeError, ValueError):
        return HOOK_CLIPS


def hook_seconds(opts: Optional[dict]) -> float:
    try:
        return max(6.0, min(30.0, float((opts or {}).get("hook_seconds") or HOOK_SECONDS)))
    except (TypeError, ValueError):
        return HOOK_SECONDS


def _originals_only() -> bool:
    try:
        from . import config
        return bool(getattr(config, "ORIGINALS_ONLY", False))
    except Exception:  # noqa: BLE001
        return False


def blocklist(inp: Optional[dict]) -> List[str]:
    """The channels this job never uses: the owner's list for the style (and channels named like a compilation
    desk, but never the customer's own channel), plus the job's own."""
    names = list(DEFAULT_BLOCKLIST) if is_style(inp) else []
    if names:
        from . import stormledger
        names += [n for n in stormledger.PERSONALITY if n not in names]
    if not names and _originals_only():
        # Original sources for every style (config.ORIGINALS_ONLY, 2026-11-03): the owner's never-list, the known
        # re-upload desks and every channel named like a compilation desk.
        names = list(DEFAULT_BLOCKLIST) + [n for n in REUPLOADERS if n not in DEFAULT_BLOCKLIST]
    if names:
        names.append(AGGREGATORS)
        own = options(inp).get("channel_name") or (inp or {}).get("channel_title") or ""
        if isinstance((inp or {}).get("channel_watermark"), str):
            own = own or inp["channel_watermark"]
        if str(own).strip():
            names.append("!" + str(own).strip()[:80])
    raw = (inp or {}).get("blocked_sources")
    if isinstance(raw, str):
        raw = re.split(r"[,\n;]+", raw)
    for n in raw or []:
        n = str(n or "").strip()
        if n and n.lower() not in {x.lower() for x in names}:
            names.append(n[:80])
    return names


# Local stations by the place they serve (the Las Vegas run, 2026-11-03: "WBFF FOX45 Baltimore" and "WUSA9" under a
# Las Vegas story). Cities a channel name may carry, and well-known call signs; anything else falls back to the
# call sign's letter (K west of the Mississippi, W east of it).
_CITY_STATE = {
    "las vegas": "nevada", "henderson": "nevada", "reno": "nevada", "phoenix": "arizona", "tucson": "arizona",
    "flagstaff": "arizona", "sedona": "arizona", "baltimore": "maryland", "washington dc": "dc", "dc": "dc",
    "chicago": "illinois", "houston": "texas", "dallas": "texas", "fort worth": "texas", "austin": "texas",
    "san antonio": "texas", "el paso": "texas", "denver": "colorado", "atlanta": "georgia", "miami": "florida",
    "orlando": "florida", "tampa": "florida", "jacksonville": "florida", "new york": "new york", "nyc": "new york",
    "buffalo": "new york", "albany": "new york", "boston": "massachusetts", "philadelphia": "pennsylvania",
    "pittsburgh": "pennsylvania", "seattle": "washington", "spokane": "washington", "los angeles": "california",
    "san diego": "california", "san francisco": "california", "bay area": "california", "sacramento": "california",
    "fresno": "california", "detroit": "michigan", "minneapolis": "minnesota", "twin cities": "minnesota",
    "st. louis": "missouri", "st louis": "missouri", "kansas city": "missouri", "cleveland": "ohio",
    "columbus": "ohio", "cincinnati": "ohio", "nashville": "tennessee", "memphis": "tennessee",
    "knoxville": "tennessee", "charlotte": "north carolina", "raleigh": "north carolina", "new orleans": "louisiana",
    "baton rouge": "louisiana", "salt lake": "utah", "albuquerque": "new mexico", "oklahoma city": "oklahoma",
    "tulsa": "oklahoma", "omaha": "nebraska", "indianapolis": "indiana", "milwaukee": "wisconsin",
    "louisville": "kentucky", "birmingham": "alabama", "richmond": "virginia", "norfolk": "virginia",
    "hartford": "connecticut", "providence": "rhode island", "honolulu": "hawaii", "anchorage": "alaska",
    "boise": "idaho", "little rock": "arkansas", "des moines": "iowa", "wichita": "kansas", "portland": "oregon",
    "asheville": "north carolina", "chattanooga": "tennessee", "savannah": "georgia", "palm springs": "california"}
_CALL_STATE = {
    "WUSA": "dc", "WJLA": "dc", "WRC": "dc", "WTTG": "dc", "WBFF": "maryland", "WBAL": "maryland", "WJZ": "maryland",
    "WMAR": "maryland", "WABC": "new york", "WNBC": "new york", "WCBS": "new york", "WPIX": "new york",
    "KTLA": "california", "KABC": "california", "KNBC": "california", "KCBS": "california", "KTNV": "nevada",
    "KSNV": "nevada", "KVVU": "nevada", "KLAS": "nevada", "KPNX": "arizona", "KNXV": "arizona", "KSAZ": "arizona",
    "KTVK": "arizona", "KDKA": "pennsylvania", "WFAA": "texas", "WBAP": "texas", "WOAI": "texas", "KHOU": "texas",
    "KPRC": "texas", "KTRK": "texas", "WGN": "illinois", "WLS": "illinois", "WMAQ": "illinois", "KUSA": "colorado",
    "KDVR": "colorado", "KMGH": "colorado", "WSB": "georgia", "WXIA": "georgia", "WPLG": "florida", "WSVN": "florida",
    "WFTV": "florida", "WFLA": "florida", "KING": "washington", "KOMO": "washington", "KIRO": "washington"}
# States west of the Mississippi (call signs start with K there, W east of it - a rule with old exceptions).
_WEST = {"alaska", "arizona", "arkansas", "california", "colorado", "hawaii", "idaho", "iowa", "kansas", "louisiana",
         "minnesota", "missouri", "montana", "nebraska", "nevada", "new mexico", "north dakota", "oklahoma",
         "oregon", "south dakota", "texas", "utah", "washington", "wyoming"}
_STATION = re.compile(r"\d|\bnews\b|\btv\b|\babc\b|\bnbc\b|\bcbs\b|\bfox\b|\bchannel\b|\bcw\b|'s family\b", re.I)
_CALL = re.compile(r"(?<![A-Za-z])([KW][A-Z]{2,3})(?:-?(?:TV|DT|HD|CD|LD))?(?:\s?\d{1,2})?(?![A-Za-z])")


# --------------------------------------------------------------------------- #
# Original sources only (the owner, 2026-11-03: "no footage from competitors at all")
# --------------------------------------------------------------------------- #
#
# The owner's Las Vegas video took ~70% of its shots from re-upload / compilation channels: they can strike the
# video and it hands them the advantage. Original creators are fine: local TV stations, agencies, the person who
# filmed it. source_kind() sorts a channel; "reupload" never plays in a storm desk video.

# Seen re-uploading other people's footage (the owner's list, 2026-11-03) - names that the generic rule below
# would not catch on their own are the point of this list.
REUPLOADERS = (
    "TERRA DOSSIER", "Weather Is Dangerous", "FM Weather", "Storm-HQ", "Real Weather US", "STORM GLOBAL",
    "Disastrrz", "Last Traces", "USA Severe Weather", "USA Wildfire Alert", "Storm Desk USA", "Global Weather Network",
    "GLOBAL WEATHER NEWS", "Weather Disasters", "Disaster Wire", "weather Storm Report", "Global Storm Desk",
    "Beyond The Seen", "IDH Weather News", "StormWatch America", "Hydro-Tech Vision", "Stormfield News",
    "ARTEMIS HOUSE", "USA Climate Reports", "The Why On Earth", "NationalStormReport", "Daily Weather Report",
    "Extreme Weather Report", "Final Remnants", "The Daily Atlas", "Planet Weather", "StormPulse HQ",
    "Weather Impact USA", "Crisis Radar", "GeoVara", "Foreshock", "Dddd Dd", "The Mercer Report",
    "Weather Alert Wire", "American Weather System", "The Earth Desk", "EARTH ALERT NEWS", "Weather Watch USA",
    "SEVERE WEATHER NEWS")
# Original footage by its owner's name: weather networks that shoot and license their own, storm-chaser outfits,
# agencies and services.
_ORIGINAL_NAMES = re.compile(
    r"\b(the weather channel|weathernation|weather nation|accuweather|fox weather|live storms media|"
    r"storm chas\w*|chas(?:er|ers|ing)\b|reed timmer|pecos hank|ryan hall|max velocity|severe studios|"
    r"nws|noaa|national weather service|usgs|fema|nasa|national park service|nps|usfs|forest service|cal ?fire|"
    r"fire (?:department|dept|district|rescue)|police|sheriff|county|city of|state of|department of|dept\.? of|"
    r"bureau of|water authority|emergency management|highway patrol|\bdot\b|national guard|coast guard|red cross|"
    r"associated press|reuters|afp|getty|storyful|viralhog|newsflare|jukin|cbs news|nbc news|abc news|cnn|"
    r"bbc|pbs|npr|univision|telemundo|"
    # Newspapers, agencies and research groups (the kit's tools/channels.py): they film their own.
    r"tribune|herald|gazette|chronicle|sentinel|courier|review-journal|deseret|azfamily|arizona republic|"
    r"usbr|reclamation|blm|geological survey|university|smithsonian|water district|returning rapids|colorado river stories)\b",
    re.I)
# The words re-upload desks are named with; a name made mostly of them, with a weather / disaster word, is one.
_DESK_WORDS = set("""
weather storm storms stormwatch disaster disasters climate crisis severe extreme tornado tornadoes hurricane
flood floods flooding wildfire wildfires earth planet global world usa us america american national daily
breaking news report reports alert alerts desk hq wire radar pulse impact watch tracker hub network dossier
atlas remnants traces chronicle chronicles files insider today now live center centre update updates zone
""".split())
_CORE_WORDS = ("weather", "storm", "disaster", "climate", "crisis", "severe", "extreme", "tornado", "hurricane",
               "flood", "wildfire", "earth", "planet", "catastroph")


def _name_words(name: str) -> List[str]:
    n = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(name or ""))          # NationalStormReport -> National Storm Report
    return [w for w in re.split(r"[^a-z0-9]+", n.lower()) if w and w not in ("the", "a", "of", "and", "on", "in")]


def is_station(channel: str) -> bool:
    """A local TV station by its name: a call sign, a channel number, a network name or "news" + a place."""
    c = str(channel or "")
    if _CALL.search(c) and _STATION.search(c):
        return True
    if re.search(r"\b(abc|nbc|cbs|fox|cw|pbs|univision|telemundo)\s?\d{1,2}\b|\b\d{1,2}\s?(news|abc|nbc|cbs|fox)\b|"
                 r"\bnews\s?\d{1,2}\b|\bchannel\s?\d{1,2}\b|'s family\b", c, re.I):
        return True
    return bool(re.search(r"\bnews\b", c, re.I) and _places_named(c))


def source_kind(channel: str, title: str = "", description: str = "") -> str:
    """
    "station" (a local TV station), "original" (an agency, a weather network or storm-chaser outfit that shoots
    its own), "reupload" (a compilation / re-upload desk: the owner's list, a name made of desk words, or an upload
    whose description says it is someone else's footage), "creator" (anyone else - the person who filmed it), or
    "unknown" (no channel known yet: resolve it before use).
    """
    ch = re.sub(r"\s+", " ", str(channel or "")).strip()
    if not ch or ch.lower() in ("youtube", "unknown", "source"):
        return "unknown"
    key = _norm_name(ch)
    for n in REUPLOADERS:
        k = _norm_name(n)
        if k and (key == k or (len(k) >= 8 and k in key)):
            return "reupload"
    if is_station(ch):
        return "station"
    if _ORIGINAL_NAMES.search(ch):
        return "original"
    words = _name_words(ch)
    if words and any(any(c in w for c in _CORE_WORDS) for w in words):
        desk = sum(1 for w in words if w in _DESK_WORDS or any(c in w for c in _CORE_WORDS))
        if desk / float(len(words)) >= 0.5 and len(words) >= 2 or (len(words) == 1 and len(words[0]) > 12):
            return "reupload"
    if reupload_text(description):
        return "reupload"
    return "creator"


_REUPLOAD_TEXT = re.compile(
    r"copyright disclaimer|section 107|fair use|all rights (?:go |belong )?to (?:their|the) (?:respective )?owners?|"
    r"no copyright infringement intended|credits? to the (?:original|respective)|footage (?:courtesy|credit|from)|"
    r"video credit|(?:source|sources|credits?)\s*:\s*\S+.*(?:news|tv|youtube|tiktok|x\.com|twitter)|"
    r"compilation of|we do not own", re.I)


def reupload_text(description: str) -> bool:
    """An upload's description that says the footage is someone else's (a fair-use notice, a footage credit)."""
    return bool(_REUPLOAD_TEXT.search(str(description or "")[:3000]))


# A montage of other people's videos by its title, in any niche (2026-11-03: original sources for every style):
# "Top 10 ...", "... compilation", "best of ...", "most insane ... ever caught", "25 craziest moments".
_COMPILATION_TITLE = re.compile(
    r"\bcompilations?\b|\btop\s?\d{1,3}\b|\bbest of\b|\bmontage\b|\bmega ?mix\b|"
    r"\bmost (?:shocking|insane|terrifying|dangerous|incredible|unbelievable|crazy|craziest|scary|scariest|"
    r"epic|extreme|bizarre|amazing|satisfying)\b.{0,40}\b(?:ever|caught|recorded|on camera|moments|videos|clips)\b|"
    r"\b\d{1,3}\s+(?:craziest|scariest|insane|incredible|shocking|unbelievable|terrifying|epic|amazing|crazy|"
    r"bizarre|times|moments)\b.{0,30}\b(?:caught|camera|moments|videos|clips|ever)\b", re.I)


def compilation_title(title: str) -> bool:
    """An upload titled as a compilation of other people's footage (never a source of original footage)."""
    return bool(_COMPILATION_TITLE.search(str(title or "")))


def original_share(doc: dict) -> dict:
    """Seconds of the narration shots by source kind and the share from original sources (stations, agencies,
    the people who filmed it), for the report."""
    fps = int(doc.get("fps") or 30)
    secs: Dict[str, float] = {}
    for s in doc.get("scenes") or []:
        if (s.get("media") or {}).get("type") not in ("video", "image") or is_ai(s):
            continue
        k = source_kind(_sm(s).get("channel") or "")
        secs[k] = secs.get(k, 0.0) + int(s["durationInFrames"]) / float(fps)
    total = sum(secs.values()) or 1.0
    orig = sum(v for k, v in secs.items() if k in ("station", "original", "creator"))
    return {"seconds": {k: round(v, 1) for k, v in secs.items()}, "originalShare": round(orig / total, 3)}


def _places_named(text: str) -> set:
    low = f" {str(text or '').lower()} "
    out = set()
    for city, st in _CITY_STATE.items():
        if re.search(r"(?<![a-z])" + re.escape(city) + r"(?![a-z])", low):
            out.add(st)
    for name, code in _STATES.items():
        if re.search(r"(?<![a-z])" + re.escape(name) + r"(?![a-z])", low):
            out.add(name)
    if "washington" in out and re.search(r"washington,?\s*d\.?c\.?", low):
        out.discard("washington")
        out.add("dc")
    return out


def station_conflict(channel: str, title: str, story_places: set) -> str:
    """
    Why a local station's upload cannot show this story's place ("" = fine): the channel names another city or
    state, or its call sign belongs to another place (a known one, else K/W against the story's side of the
    Mississippi) - unless the upload's own title names the story's place.
    """
    story = {str(p).lower() for p in story_places or set() if p}
    if not story or not str(channel or "").strip():
        return ""
    if _places_named(title) & story:
        return ""
    m = _CALL.search(str(channel))
    call = m.group(1) if m else ""
    known = (_CALL_STATE.get(call) or _CALL_STATE.get(call[:3])) if call else ""
    if known:
        return "" if known in story else f"a station from another place ({call}: {known})"
    if not _STATION.search(str(channel)):
        return ""                       # not a local station by its name (a newspaper, an agency, a creator)
    named = _places_named(channel)
    if named and not (named & story):
        return f"a station from another place ({', '.join(sorted(named))[:40]})"
    if not call:
        return ""
    sides = {("west" if p in _WEST else "east") for p in story if p in _WEST or p in set(_STATES) or p == "dc"}
    if len(sides) == 1:
        side = next(iter(sides))
        if (side == "west" and call.startswith("W")) or (side == "east" and call.startswith("K")):
            return f"a station from another part of the country ({call})"
    return ""


def story_places(text: str) -> set:
    """The states (and DC) a story's text names, by state or by city."""
    return _places_named(text)


def _norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


def blocked(channel: str, title: str, names: Sequence[str]) -> str:
    """The blocklist entry a candidate matches by its channel (or, failing that, its title), or ''."""
    ch, ti = _norm_name(channel), _norm_name(title)
    allowed = {_norm_name(n[1:]) for n in names if str(n).startswith("!")}
    if ch and ch in allowed:
        return ""
    for n in names:
        if str(n).startswith(("!", "@")):
            continue
        k = _norm_name(n)
        if k and (k == ch or (len(k) >= 8 and (k in ch or k in ti))):
            return n
    if AGGREGATORS in names and channel and (_AGGREGATOR.match(re.sub(r"\s+", " ", str(channel)).strip())
                                            or source_kind(channel) == "reupload"):
        return "a news-compilation / re-upload channel"
    return ""


# --------------------------------------------------------------------------- #
# Pauses (before the plan)
# --------------------------------------------------------------------------- #

def _text(w) -> str:
    return str(getattr(w, "text", None) if not isinstance(w, dict) else w.get("text") or "")


def _ws(w) -> float:
    return float(getattr(w, "start", 0.0) if not isinstance(w, dict) else w.get("start", 0.0))


def _we(w) -> float:
    return float(getattr(w, "end", 0.0) if not isinstance(w, dict) else w.get("end", 0.0))


def sentences(words: Sequence) -> List[dict]:
    """[{i0, i1, start, end, text}] - the narration cut at . ! ? (and at a gap of 1.2 s or more)."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(i)
        nxt = words[i + 1] if i + 1 < len(words) else None
        end = bool(re.search(r"[.!?][\"')\]]*$", _text(w).strip()))
        gap = (_ws(nxt) - _we(w)) if nxt is not None else 0.0
        if end or gap >= 1.2 or nxt is None:
            out.append({"i0": cur[0], "i1": cur[-1], "start": _ws(words[cur[0]]), "end": _we(words[cur[-1]]),
                        "text": " ".join(_text(words[k]).strip() for k in cur).strip()})
            cur = []
    return out


def _drama(text: str) -> float:
    s = 1.0 * len(_DRAMA.findall(text)) + (0.8 if _NUMBER.search(text) else 0.0)
    if text.rstrip().endswith("!"):
        s += 0.5
    if re.search(r"\bstay with us\b", text, re.I):
        s += 2.0
    return s


def plan_pauses(words: Sequence, duration: float, opts: Optional[dict] = None) -> List[dict]:
    """
    Where the narration stops for a natural-sound pause: [{"at": narration seconds (the cut, inside the silence
    after a sentence), "secs", "sentence"}], in order. "auto": about one every PAUSE_EVERY seconds, each at the
    most dramatic sentence end near its share of the narration (the hook's end, a rescue, a record), never
    before PAUSE_FIRST_MIN or in the last PAUSE_TAIL seconds, never closer than PAUSE_MIN_GAP to another.
    A list of seconds places them by hand (snapped to the nearest sentence end); 0 / "off" = none.
    With open_clip (the default) the first one is the opening clip: at narration second 0, open_seconds long,
    {"open": true} - the video starts on a clip and its own sound, then the narration begins.
    """
    opts = opts or {}
    words = list(words or [])
    if not words or duration <= 0:
        return []
    mid = _mid_pauses(words, opts)
    if open_clip_on(opts):
        n = hook_clips(opts)
        secs = hook_seconds(opts) / n if n > 1 else open_seconds(opts)
        return [{"at": 0.0, "secs": round(secs, 3), "sentence": "", "open": True, "hook": k} for k in range(n)] + mid
    return mid


_CARRIES_ON = re.compile(r"^(and|but|or|because|which|who|that|so that|as|while|though|although|since|if|then|plus|"
                         r"instead|meaning|unless|until|when|where|also|too|it|they|he|she|this|these|those|its|their)\b", re.I)
_NEW_POINT = re.compile(r"^(now|so|here's|here is|meanwhile|next|today|tonight|this week|last week|on (monday|tuesday|wednesday|"
                        r"thursday|friday|saturday|sunday)|the (next|other|bigger|real|question)|what|why|how|where|for|over|in|at|"
                        r"between|back|even|still)\b", re.I)


def natural_stop(sent: dict, nxt: dict) -> float:
    """How clean a stop this sentence end is, 0 to 1. 0 = never pause here: a question waiting for its answer, or a next
    sentence that leans on this one (the owner: never mid-topic, only right after a point is finished). A longer breath
    in the voiceover and a next sentence that opens a new point are what a finished point sounds like."""
    text, after = str(sent.get("text") or "").strip(), str(nxt.get("text") or "").strip()
    if not text or text.endswith((":", ",", ";", "?")):
        return 0.0
    if _CARRIES_ON.match(after):
        return 0.0
    gap = max(0.0, float(nxt.get("start") or 0.0) - float(sent.get("end") or 0.0))
    score = 0.35 + min(0.4, gap / 1.5) + (0.25 if _NEW_POINT.match(after) else 0.0)
    return round(min(1.0, score), 3)


def _mid_pauses(words: list, opts: dict) -> List[dict]:
    """plan_pauses' natural-sound pauses in the narration (not the opening clip)."""
    want = opts.get("pauses", "auto")
    secs = float(opts.get("pause_seconds") or PAUSE_SECONDS)
    secs = max(3.0, min(15.0, secs))
    if want in (0, "0", "off", False, "none"):
        return []
    sents = sentences(words)
    end_of_talk = _we(words[-1])
    cands = []
    for k, s in enumerate(sents[:-1]):
        nxt = sents[k + 1]
        if s["end"] < PAUSE_FIRST_MIN or s["end"] > end_of_talk - PAUSE_TAIL:
            continue
        stop = natural_stop(s, nxt)
        if stop <= 0.0:
            continue                            # mid-topic: the next sentence carries on from this one
        cut = min(s["end"] + 0.25, (s["end"] + nxt["start"]) / 2.0)
        prev = sents[k - 1]["text"] if k else ""
        cands.append({"at": round(cut, 3), "score": stop + _drama(s["text"]) + 0.4 * _drama(prev),
                      "sentence": s["text"]})
    if not cands:
        return []
    picked: List[dict] = []
    if isinstance(want, (list, tuple)):
        for t in want:
            try:
                t = float(t)
            except (TypeError, ValueError):
                continue
            best = min(cands, key=lambda c: abs(c["at"] - t))
            if all(abs(best["at"] - p["at"]) >= 10.0 for p in picked):
                picked.append(best)
    else:
        try:
            n = int(want)
        except (TypeError, ValueError):
            n = int(round(end_of_talk / PAUSE_EVERY))
        n = max(0, min(PAUSE_MAX, n))
        if end_of_talk < 60.0:
            n = min(n, 1)
        span = max(1.0, end_of_talk)
        for j in range(n):
            ideal = span * (j + 1) / (n + 1)
            if j == 0:
                ideal = min(ideal, 40.0)        # the reference breaks right after its ~20 s hook
            window = max(20.0, span / (n + 1) * 0.45)
            ok = [c for c in cands if abs(c["at"] - ideal) <= window
                  and all(abs(c["at"] - p["at"]) >= PAUSE_MIN_GAP for p in picked)]
            if not ok:
                continue
            best = max(ok, key=lambda c: (c["score"] - abs(c["at"] - ideal) / window, -c["at"]))
            picked.append(best)
    picked.sort(key=lambda c: c["at"])
    return [{"at": c["at"], "secs": secs, "sentence": c["sentence"][:200]} for c in picked]


def shift(t: float, pauses: Sequence[dict]) -> float:
    """A narration time on the padded narration (every pause cut before it adds its seconds)."""
    return t + sum(float(p["secs"]) for p in pauses if float(p["at"]) <= t + 1e-9)


def out_pauses(pauses: Sequence[dict]) -> List[dict]:
    """The pauses on the padded timeline: [{"t0", "t1"}] seconds."""
    out, added = [], 0.0
    for p in sorted(pauses, key=lambda x: float(x["at"])):
        t0 = float(p["at"]) + added
        out.append({"t0": round(t0, 3), "t1": round(t0 + float(p["secs"]), 3), "sentence": p.get("sentence", ""),
                    **({"open": True} if p.get("open") else {})})
        added += float(p["secs"])
    return out


def shift_words(words: Sequence, pauses: Sequence[dict]) -> list:
    """The words on the padded narration (same objects' type: Word dataclasses are rebuilt, dicts copied)."""
    out = []
    for w in words:
        d = shift(_ws(w), pauses) - _ws(w)
        if isinstance(w, dict):
            out.append({**w, "start": _ws(w) + d, "end": _we(w) + d})
        else:
            out.append(type(w)(text=_text(w), start=_ws(w) + d, end=_we(w) + d))
    return out


def pad_narration(src: str, pauses: Sequence[dict], out: str, sr: int = 48000) -> str:
    """The narration with a silence of each pause's length at its cut (ffmpeg, one pass). Returns `out`."""
    ps = sorted(pauses, key=lambda x: float(x["at"]))
    if not ps:
        raise ValueError("no pauses")
    parts, labels, prev = [], [], 0.0
    for k, p in enumerate(ps):
        at = float(p["at"])
        if at - prev > 0.001:               # (the opening clip's silence comes before any narration)
            parts.append(f"[0:a]atrim=start={prev:.4f}:end={at:.4f},asetpts=PTS-STARTPTS,"
                         f"aresample={sr},aformat=channel_layouts=stereo[a{k}]")
            labels.append(f"[a{k}]")
        parts.append(f"anullsrc=r={sr}:cl=stereo,atrim=duration={float(p['secs']):.4f}[s{k}]")
        labels.append(f"[s{k}]")
        prev = at
    parts.append(f"[0:a]atrim=start={prev:.4f},asetpts=PTS-STARTPTS,aresample={sr},"
                 f"aformat=channel_layouts=stereo[tail]")
    labels.append("[tail]")
    fc = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(labels)}:v=0:a=1[out]"
    tmp = out + ".part" + os.path.splitext(out)[1]
    codec = ["-c:a", "libmp3lame", "-b:a", "256k"] if out.lower().endswith(".mp3") else ["-c:a", "pcm_s16le"]
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", src, "-filter_complex", fc, "-map", "[out]", "-ar", str(sr),
           *codec, "-map_metadata", "-1", tmp]
    p = subprocess.run(cmd, capture_output=True, timeout=900)
    if p.returncode != 0 or not os.path.isfile(tmp):
        raise RuntimeError("narration padding failed: " + (p.stderr or b"")[-300:].decode("utf-8", "replace"))
    os.replace(tmp, out)
    return out


def prepare_narration(inp: dict, words: list, audio_path: str, duration: float, work: str,
                      store: Optional[Callable[[str], str]] = None) -> Optional[dict]:
    """
    The plan's first storm-desk step (handler.do_plan, right after the words are known): choose the pauses, pad
    the narration file, store it. Returns {"words", "path", "url", "duration", "pauses"} or None (no pause:
    the narration stays as it is). Never raises: a padding that fails leaves the video without pauses.
    """
    pauses = plan_pauses(words, duration, options(inp))
    if not pauses:
        return None
    try:
        padded = os.path.join(work, "narration.padded.mp3")
        pad_narration(audio_path, pauses, padded)
        keep = os.path.join(work, "narration.original" + (os.path.splitext(audio_path)[1] or ".mp3"))
        os.replace(audio_path, keep)
        os.replace(padded, audio_path)
    except Exception as e:  # noqa: BLE001 - no pauses rather than no video
        print(f"[stormdesk] pauses left out: {type(e).__name__}: {str(e)[:200]}", flush=True)
        return None
    url = ""
    if store is not None:
        try:
            url = store(audio_path) or ""
        except Exception as e:  # noqa: BLE001 - a local run keeps the file on its disk
            print(f"[stormdesk] padded narration not stored: {type(e).__name__}: {str(e)[:160]}", flush=True)
    added = sum(float(p["secs"]) for p in pauses)
    where = ", ".join("%.1fs" % float(p["at"]) for p in pauses)
    print(f"[stormdesk] {len(pauses)} natural-sound pause(s) at {where} (+{added:.0f} s)", flush=True)
    return {"words": shift_words(words, pauses), "path": audio_path, "url": url, "original": keep,
            "duration": float(duration) + added, "pauses": pauses}


# --------------------------------------------------------------------------- #
# Scenes: sources, moments, credits
# --------------------------------------------------------------------------- #

def _sm(scene: dict) -> dict:
    sm = scene.get("semanticMetadata")
    return sm if isinstance(sm, dict) else {}


def video_id(scene: dict) -> str:
    """The source video's id ("yt:<id>"), or the media URL for anything else; "" for no media."""
    sm = _sm(scene)
    for raw in (sm.get("sourceUrl"), sm.get("assetId")):
        raw = str(raw or "")
        m = re.search(r"(?:v=|youtu\.be/|^yt:)([A-Za-z0-9_-]{11})", raw)
        if m:
            return "yt:" + m.group(1)
        if raw.startswith(("http", "dm:", "yt:")):
            return raw.split("@")[0]
    return str(((scene.get("media") or {}).get("url")) or "")


def source_key(scene: dict) -> str:
    """Who supplied a shot, for the variety rules: the uploading channel when known, else the video."""
    ch = _norm_name(_sm(scene).get("channel") or "")
    return ("ch:" + ch) if ch else video_id(scene)


def is_ai(scene: dict) -> bool:
    m = scene.get("media") or {}
    sm = _sm(scene)
    blob = " ".join(str(x or "") for x in (m.get("source"), m.get("attribution"), sm.get("provider")))
    return bool(scene.get("aiFill")) or bool(re.search(r"\b(generated|ai[- ]generated|ai fill|aifill|seedance|veo|"
                                                         r"nano.banana|gemini.*image)\b", blob, re.I))


def moment(scene: dict, fps: int) -> Optional[Tuple[str, float, float]]:
    """(video, start, end) seconds of the source video the shot shows, when its in-point is known."""
    vid = video_id(scene)
    if not vid.startswith("yt:"):
        return None
    sm = _sm(scene)
    start = None
    mo = sm.get("moment") if isinstance(sm.get("moment"), dict) else {}
    if isinstance(mo.get("start"), (int, float)):
        start = float(mo["start"])
    else:
        m = re.search(r"[?&]t=(\d+(?:\.\d+)?)", str(sm.get("sourceUrl") or ""))
        if m:
            start = float(m.group(1))
    if start is None:
        return None
    start += float((scene.get("media") or {}).get("trimStart") or 0.0)
    return vid, start, start + int(scene.get("durationInFrames") or 0) / float(fps)


def credit_name(scene: dict) -> str:
    sm = _sm(scene)
    m = scene.get("media") or {}
    ch = str(sm.get("channel") or "").strip()
    if ch:
        return ch[:48]
    att = str(m.get("attribution") or "").strip()
    prov = str(sm.get("provider") or m.get("source") or "").strip().lower()
    if att.lower().startswith(("youtube:", "youtube —", "dailymotion:")) or not att:
        return {"youtube": "YouTube", "dailymotion": "Dailymotion"}.get(prov, prov.title() or "Source")
    return re.split(r"\s+[—-]\s+|:\s+", att)[0][:48] if ":" in att or " — " in att else att[:48]


def event_date(text: str, opts: dict, today: Optional[datetime.date] = None) -> Optional[datetime.date]:
    """The event's day: the job's event_date, else the first "Month day" the narration says (this year, or last
    year when that would be in the future), else None."""
    today = today or datetime.date.today()
    raw = str(opts.get("event_date") or "").strip()
    if raw:
        try:
            return datetime.date.fromisoformat(raw[:10])
        except ValueError:
            pass
    m = _MONTH_RE.search(text or "")
    if not m:
        return None
    month = _MONTHS.index(m.group(1).lower()) + 1
    try:
        d = datetime.date(today.year, month, int(m.group(2)))
    except ValueError:
        return None
    if d > today + datetime.timedelta(days=2):
        d = d.replace(year=today.year - 1)
    return d


EVENT_DAY_RECENT = 45           # a date the narration says counts as the event's day only this recent


def event_day_for(inp: dict, words: Sequence = (), today: Optional[datetime.date] = None) -> Optional[datetime.date]:
    """
    The day the sourcing holds an event line's footage to (media.set_event_day: nothing uploaded before it):
    the job's event_date, else a "Month day" the opening of the narration says when it is within the last
    EVENT_DAY_RECENT days and no other year follows it ("July 4th, 1983" is history, not this event). None =
    the story-year rule only.
    """
    opts = options(inp)
    today = today or datetime.date.today()
    raw = str(opts.get("event_date") or "").strip()
    if raw:
        try:
            return datetime.date.fromisoformat(raw[:10])
        except ValueError:
            pass
    text = " ".join(_text(w).strip() for w in list(words or [])[:220])
    m = _MONTH_RE.search(text)
    if not m:
        return None
    after = text[m.end():m.end() + 12]
    y = re.match(r"\s*,?\s*(\d{4})\b", after)
    if y and int(y.group(1)) not in (today.year, today.year - 1):
        return None
    day = event_date(text, {}, today)
    if day is None or day > today + datetime.timedelta(days=2) or (today - day).days > EVENT_DAY_RECENT:
        return None
    return day


def archive(scene: dict, day: Optional[datetime.date], brief: Optional[dict]) -> bool:
    """Footage uploaded before the event (a day's grace) - an older storm's, labelled ARCHIVE on screen."""
    up = str(_sm(scene).get("uploadDate") or "")
    if not re.fullmatch(r"\d{8}", up):
        return False
    try:
        d = datetime.date(int(up[:4]), int(up[4:6]), int(up[6:8]))
    except ValueError:
        return False
    if day is not None:
        return d < day - datetime.timedelta(days=1)
    year = (brief or {}).get("year")
    return isinstance(year, int) and not isinstance(year, bool) and d.year < year


def place_chip(place: str) -> str:
    """'Henderson, Nevada' -> 'Henderson, NV' (a US state abbreviated); anything else as given, short."""
    place = re.sub(r"\s+", " ", str(place or "")).strip(" ,")
    if not place:
        return ""
    parts = [p.strip() for p in place.split(",") if p.strip()]
    if len(parts) >= 2:
        st = _STATES.get(parts[-1].lower())
        if st:
            return f"{parts[0]}, {st}"[:32]
        return f"{parts[0]}, {parts[-1]}"[:32]
    return parts[0][:32]


def date_chip(day: Optional[datetime.date]) -> str:
    day = day or datetime.date.today()
    return f"{_MONTHS[day.month - 1][:3].upper()} {day.day}, {day.year}"


# --------------------------------------------------------------------------- #
# Headlines
# --------------------------------------------------------------------------- #

_TRAILING = {"AND", "OR", "THE", "A", "AN", "OF", "TO", "IN", "AT", "AS", "FOR", "WITH", "ON", "BY", "FROM",
             "BUT", "THAT", "WHICH", ""}


def wrap2(text: str, width: int = HEADLINE_LINE) -> List[str]:
    """At most two lines of <= width characters, balanced; a longer headline is shortened at a word."""
    words = str(text or "").upper().split()
    if not words:
        return []
    while len(" ".join(words)) > 2 * width + 1 and len(words) > 1:
        words.pop()
    while words and words[-1].strip(",;:-—") in _TRAILING:
        words.pop()
    if not words:
        return []
    words[-1] = words[-1].rstrip(",;:-—")
    one = " ".join(words)
    if len(one) <= width:
        return [one]
    best = None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        score = (max(len(a), len(b)) > width, max(len(a), len(b)), abs(len(a) - len(b)))
        if best is None or score < best[0]:
            best = (score, [a, b])
    return best[1] if best else [one[:width]]


def rule_headline(text: str) -> str:
    """A headline from a block's own words (no model): its most newsworthy sentence, cut to the point."""
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", str(text or "")) if len(s.strip()) > 8]
    if not sents:
        return ""

    def score(s: str) -> float:
        caps = len(re.findall(r"\b[A-Z][a-z]{2,}", s[1:]))
        return _drama(s) + 0.5 * min(caps, 3) - 0.01 * max(0, len(s) - 90)
    best = max(sents[:6], key=score)
    s = re.sub(r"\([^)]*\)", "", best).strip()
    for _ in range(3):
        s = _FILLER.sub("", s).strip()
    s = re.sub(r"[\"“”]", "", s).rstrip(".!?")
    # Keep the clause that carries the number or the drama when the sentence is long.
    if len(s) > 2 * HEADLINE_LINE:
        clauses = [c.strip() for c in re.split(r",|;| — | - |\bbut\b|\bwhile\b|\bas\b(?= the)", s) if c.strip()]
        if clauses:
            def weight(k: int) -> tuple:
                c = clauses[k]
                names = len(re.findall(r"\b[A-Z][a-z]{2,}", c))
                return (_drama(c) + 0.5 * min(names, 2) + (0.25 if len(c.split()) >= 4 else 0.0), -k)
            s = clauses[max(range(len(clauses)), key=weight)]
    return " ".join(wrap2(s))


_HEADLINE_PROMPT = (
    "You write the on-screen lower-third headlines of a breaking-news video, one per narration block. "
    "Each headline restates the block's key fact in ALL CAPS, at most 50 characters, a hard number when the "
    "block says one, the place when it names one, present tense, no clickbait, no emoji, no quotes, nothing the "
    "block does not say. The last block's headline may be the safety line it gives. Also give each block a "
    "short tab label (2-3 words, ALL CAPS): \"BREAKING NEWS\" for the first, else the place or topic. Answer "
    'JSON: {"blocks": [{"i": 0, "headline": "...", "tab": "..."}]}.')


def write_headlines(blocks: List[dict], title: str = "", ask: Optional[Callable] = None) -> str:
    """Fill each block's headline and tab: the job's own, else one model call for all of them, else the rules.
    Returns how they were written ("job", "model", "rules")."""
    how = "rules"
    todo = [b for b in blocks if not b.get("headline")]
    if todo and ask is not None:
        try:
            raw = ask(_HEADLINE_PROMPT, {"title": title, "blocks": [{"i": b["i"], "text": b["text"][:900]}
                                                                    for b in blocks]})
        except Exception as e:  # noqa: BLE001 - the rules below
            print(f"[stormdesk] headline model failed: {type(e).__name__}: {str(e)[:120]}", flush=True)
            raw = None
        got = {}
        for row in ((raw or {}).get("blocks") or []) if isinstance(raw, dict) else []:
            if isinstance(row, dict) and isinstance(row.get("i"), int):
                got[row["i"]] = row
        for b in todo:
            row = got.get(b["i"]) or {}
            head = re.sub(r"\s+", " ", str(row.get("headline") or "")).strip().strip('"')
            if 8 <= len(head) <= 70:
                b["headline"] = head.upper()
                tab = re.sub(r"\s+", " ", str(row.get("tab") or "")).strip().upper()
                if tab and len(tab) <= 22 and not b.get("tab"):
                    b["tab"] = tab
                how = "model"
    for b in blocks:
        if not b.get("headline"):
            b["headline"] = rule_headline(b["text"]) or (title or "BREAKING NEWS").upper()
        b["lines"] = wrap2(b["headline"])
    return how


# --------------------------------------------------------------------------- #
# Frames, marks, look-alikes (local files only; never raises)
# --------------------------------------------------------------------------- #

def _probe(path: str) -> dict:
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "stream=codec_type,width,height:format=duration", "-of", "json", path],
                           capture_output=True, text=True, timeout=60)
        info = json.loads(p.stdout or "{}") or {}
    except Exception:  # noqa: BLE001
        return {}
    out = {"duration": float((info.get("format") or {}).get("duration") or 0.0), "audio": False, "w": 0, "h": 0}
    for s in info.get("streams") or []:
        if s.get("codec_type") == "audio":
            out["audio"] = True
        elif s.get("codec_type") == "video" and not out["w"]:
            out["w"], out["h"] = int(s.get("width") or 0), int(s.get("height") or 0)
    return out


def frames(path: str, start: float, seconds: float, n: int = 6, w: int = 320, h: int = 180):
    """n RGB frames (numpy HxWx3 uint8) spread over [start, start + seconds] of a clip, or []."""
    try:
        import numpy as np
    except ImportError:
        return []
    seconds = max(0.2, float(seconds))
    rate = max(0.2, n / seconds)
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{max(0.0, start):.3f}", "-t", f"{seconds:.3f}", "-i", path,
           "-vf", f"fps={rate:.4f},scale={w}:{h}", "-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    try:
        raw = subprocess.run(cmd, capture_output=True, timeout=120).stdout
    except Exception:  # noqa: BLE001
        return []
    k = len(raw) // (w * h * 3)
    if not k:
        return []
    arr = np.frombuffer(raw[:k * w * h * 3], np.uint8).reshape(k, h, w, 3)
    return [arr[i] for i in range(k)]


def static_marks(fr: list) -> List[List[float]]:
    """
    Logo bugs and platform marks (a TikTok logo, a channel's corner bug) in a moving clip: edges present in
    EVERY frame while the picture around them changes, inside one corner of the frame. Returns boxes as
    [x, y, w, h] shares of the frame (padded), [] for a static shot or a clean clip.
    """
    try:
        import numpy as np
    except ImportError:
        return []
    if len(fr) < 4:
        return []
    g = np.stack([f.astype(np.float32).mean(axis=2) for f in fr])           # n x H x W
    n, H, W = g.shape
    motion = float(np.median(np.abs(np.diff(g, axis=0))))
    if motion < 2.5:
        return []                       # a still or a locked-off shot: every edge looks static
    gx = np.abs(np.diff(g, axis=2))[:, :-1, :]
    gy = np.abs(np.diff(g, axis=1))[:, :, :-1]
    edge = np.maximum(gx, gy)                                               # n x H-1 x W-1
    steady = edge.min(axis=0) > 28.0
    still = g.std(axis=0)[:-1, :-1] < 10.0
    mask = steady & still
    boxes = []
    zw, zh = int(W * 0.32), int(H * 0.24)
    for (x0, y0) in ((0, 0), (W - 1 - zw, 0), (0, H - 1 - zh), (W - 1 - zw, H - 1 - zh)):
        z = mask[y0:y0 + zh, x0:x0 + zw]
        if int(z.sum()) < 12:
            continue
        ys, xs = np.nonzero(z)
        bx0, bx1 = x0 + xs.min(), x0 + xs.max()
        by0, by1 = y0 + ys.min(), y0 + ys.max()
        bw, bh = (bx1 - bx0 + 1) / W, (by1 - by0 + 1) / H
        if bw * bh > 0.08 or bw < 0.015 or bh < 0.015:
            continue
        pad = 0.015
        x, y = max(0.0, bx0 / W - pad), max(0.0, by0 / H - pad)
        boxes.append([round(x, 4), round(y, 4), round(min(1.0 - x, bw + 2 * pad), 4),
                      round(min(1.0 - y, bh + 2 * pad), 4)])
    return boxes


def blurred_sides(fr: list) -> float:
    """
    A vertical clip framed in the centre over its own blur (upscale.frame_vertical): the sharp centre panel's
    share of the width, else 0. Read from the frames: the detail (grey change between neighbouring pixels,
    averaged over the frames and smoothed across columns) in the outer fifths is a small fraction of the centre's.
    """
    try:
        import numpy as np
    except ImportError:
        return 0.0
    if len(fr) < 2:
        return 0.0
    col = np.mean([np.abs(np.diff(f.astype(np.float32).mean(axis=2), axis=1)).mean(axis=0) for f in fr], axis=0)
    w = len(col)
    k = max(3, w // 40)
    col = np.convolve(col, np.ones(k) / k, mode="same")
    mid = float(col[int(w * 0.35):int(w * 0.65)].mean())
    if mid < 0.5:
        return 0.0                                                  # a flat picture says nothing
    side = max(float(col[k:int(w * 0.18)].mean()), float(col[-int(w * 0.18):-k].mean()))
    if side > 0.25 * mid:
        return 0.0
    sharp = np.where(col > 0.4 * mid)[0]
    if not len(sharp):
        return 0.0
    share = (int(sharp.max()) - int(sharp.min()) + 1) / float(w)
    return round(share, 3) if 0.25 <= share <= 0.85 else 0.0


# --------------------------------------------------------------------------- #
# Clean shots (the owner, 2026-11-03): no clip carrying other outlets' text - banners, lower thirds, tickers,
# captions, "NEW VIDEO" cards - and none shot through dirty or rainy glass when a clearer one exists.
# --------------------------------------------------------------------------- #

CROP_KEEP_MIN = 0.72            # a bottom-band crop keeps at least this share of the height
CROP_LINES_MIN = 600            # ... and at least this many of the source's lines (stays sharp at 1080)
CORNER_W, CORNER_H = 0.30, 0.22  # text inside a corner this big is a station bug: fine
TEXT_GROUND_MIN = 0.50          # the share of a text band one flat grey covers (a graphic's box)
SOFT_SHARE = 0.35               # a shot this much softer than the video's median ...
SOFT_FLOOR = 2.2                # ... and under this detail (grey change per pixel at 320 px) is "through glass"


def text_boxes(fr: list) -> List[Tuple[float, float, float, float]]:
    """
    Burned-in text (x0, y0, x1, y1 as shares of the frame): bands of dense vertical edges (src/slop.py's text
    rows) found at the same rows in two frames that either hold still while the picture around them moves (a
    graphic laid over the footage) or sit on a flat box of one colour. A facade, a fence or the horizon in a moving
    shot moves with it; one in a locked-off shot has no flat ground (the hand-used raw clips, 2026-11-03).
    """
    try:
        import numpy as np
        from . import slop
    except ImportError:
        return []
    grays, found = [], []
    for f in fr:
        g = f.astype(np.float32).mean(axis=2)
        grays.append(g)
        h, w = g.shape
        boxes = []
        for a, b in slop._bands(slop._text_rows(g)):
            if (b - a + 1) / h < 0.03:
                continue
            edges = np.abs(np.diff(g[a:b + 1], axis=1)) > 48
            cols = np.where(edges.sum(axis=0) >= 2)[0]
            if len(cols) < 4:
                continue
            x0, x1 = int(cols.min()), int(cols.max()) + 1
            region = (f[a:b + 1, x0:x1].astype(np.int32).mean(axis=2) // 24).astype(np.int64)
            ground = float(np.bincount(region.ravel()).max()) / float(region.size)
            boxes.append((a, b, x0, x1, ground))
        found.append(boxes)
    out: List[Tuple[float, float, float, float]] = []
    for k in range(len(found) - 1):
        g0, g1 = grays[k], grays[k + 1]
        rest = float(np.abs(g0 - g1).mean())
        h, w = g0.shape
        for a, b, x0, x1, ground in found[k]:
            if not any(abs(o[0] - a) <= 2 and abs(o[1] - b) <= 2 for o in found[k + 1]):
                continue
            band = float(np.abs(g0[a:b + 1, x0:x1] - g1[a:b + 1, x0:x1]).mean())
            steady = rest >= 2.0 and band <= 0.35 * rest
            if not (steady or ground >= TEXT_GROUND_MIN):
                continue
            box = (round(x0 / w, 3), round(a / h, 3), round(x1 / w, 3), round((b + 1) / h, 3))
            if all(abs(box[1] - o[1]) > 0.02 or abs(box[0] - o[0]) > 0.05 for o in out):
                out.append(box)
    return out


def _lowest_text_top(fr: list, floor: float) -> float:
    """The highest top (share of the height) of any text-like band below 60% in any frame, else `floor`."""
    try:
        import numpy as np
        from . import slop
    except ImportError:
        return floor
    top = floor
    for f in fr:
        g = f.astype(np.float32).mean(axis=2)
        h = g.shape[0]
        for a, b in slop._bands(slop._text_rows(g)):
            if a / h >= 0.6 and (b - a + 1) / h >= 0.02:
                top = min(top, a / h)
    return top


def text_verdict(fr: list, src_height: int = 1080) -> dict:
    """{"action": "keep" | "crop" | "reject", "why", "keep": height share to keep (crop)} for a shot's frames."""
    def corner(b) -> bool:
        return ((b[2] - b[0]) <= CORNER_W and (b[3] - b[1]) <= CORNER_H
                and (b[1] <= CORNER_H or b[3] >= 1 - CORNER_H) and (b[2] <= 0.4 or b[0] >= 0.6))
    boxes = [b for b in text_boxes(fr) if not corner(b)]
    if not boxes:
        return {"action": "keep"}
    top = min(b[1] for b in boxes)
    if top >= CROP_KEEP_MIN - 0.02:
        top = min(top, _lowest_text_top(fr, top))           # a chyron's other line, changing or not
        keep = max(CROP_KEEP_MIN, round(top - 0.02, 3))
        if keep * src_height >= CROP_LINES_MIN:
            return {"action": "crop", "keep": keep, "why": f"text in the bottom band (from {int(top * 100)}%)"}
        return {"action": "reject", "why": "text in the bottom band, too few lines to crop it out"}
    area = sum((b[2] - b[0]) * (b[3] - b[1]) for b in boxes)
    return {"action": "reject", "why": f"text over the picture ({len(boxes)} band(s), {area * 100:.0f}% of it)"}


def detail(fr: list) -> float:
    """Mean grey change between neighbouring pixels over the frames (320 px wide): low = soft / through glass."""
    try:
        import numpy as np
    except ImportError:
        return 0.0
    if not fr:
        return 0.0
    vals = []
    for f in fr:
        g = f.astype(np.float32).mean(axis=2)
        vals.append(float(np.abs(np.diff(g, axis=1)).mean() + np.abs(np.diff(g, axis=0)).mean()) / 2.0)
    return float(np.median(vals))


def crop_bottom(path: str, keep: float) -> bool:
    """The clip's top `keep` of the height scaled back to its size (the sound kept), in place."""
    k = f"{keep:.3f}"
    # The top-centre (keep x keep) of the frame, scaled back up: the aspect stays, the bottom band goes.
    vf = (f"crop=trunc(iw*{k}/2)*2:trunc(ih*{k}/2)*2:(iw-iw*{k})/2:0,"
          f"scale=trunc(iw/{k}/2)*2:trunc(ih/{k}/2)*2:flags=lanczos,setsar=1")
    tmp = path + ".crop.mp4"
    try:
        p = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, "-vf", vf, "-map", "0:v:0", "-map", "0:a?",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-c:a", "copy",
                            "-movflags", "+faststart", tmp], capture_output=True, timeout=300)
        if p.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) < 5_000:
            raise RuntimeError((p.stderr or b"")[-200:].decode("utf-8", "replace"))
        os.replace(tmp, path)
        return True
    except Exception as e:  # noqa: BLE001 - not cropped: rejected instead by the caller
        print(f"[stormdesk] crop {os.path.basename(path)}: {type(e).__name__}: {str(e)[:120]}", flush=True)
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def clean_check(doc: dict, read: Optional[Callable] = None, crop: Optional[Callable] = None, virtual: bool = False) -> List[dict]:
    """
    Every narration and pause clip read on 3 frames: other outlets' text (text_verdict) cropped out when it
    sits only in the bottom band, else the shot marked for replacement (scene["_reject"]); a shot far softer than
    the rest (filmed through dirty or rainy glass) marked "soft" - replaced only when a clearer clip exists.
    Returns one row per shot acted on (the run report's cleanCheck).
    """
    fps = int(doc.get("fps") or 30)
    read = read or (lambda path, a, secs: frames(path, a, secs, n=3, w=320, h=180))
    crop = crop or crop_bottom
    rows: List[dict] = []
    soft: Dict[int, float] = {}
    cropped: Dict[str, float] = {}
    for i, s in enumerate(doc["scenes"]):
        m = s.get("media") or {}
        path = _local(s)
        if m.get("type") != "video" or not path or is_ai(s):
            continue
        fr = read(path, float(m.get("trimStart") or 0.0), int(s["durationInFrames"]) / float(fps))
        if not fr:
            continue
        if path in cropped:
            s.setdefault("stormDesk", {})["cropped"] = cropped[path]
            if virtual:
                s["stormDesk"]["mode"] = f"news{cropped[path]}@0.0"
            continue
        src_h = int(_probe(path).get("h") or 1080)
        ch = str(_sm(s).get("channel") or "")
        crop_mode = station_crop(ch) if virtual else ""
        if crop_mode:
            # What the viewer sees of a station's frame is its crop: the check reads that, not the banner it drops.
            k0, top0 = _crop_k(crop_mode), _crop_top(crop_mode)
            v = text_verdict(crop_frames(fr, k0, top0), int(src_h * k0))
            if v["action"] != "keep" and k0 > 0.68:
                k0, top0 = 0.68, 0.02           # its corner bug sits further in (KUTV): the tighter crop
                v = text_verdict(crop_frames(fr, k0, top0), int(src_h * k0))
                if v["action"] == "keep":
                    s.setdefault("stormDesk", {})["mode"] = f"news{k0}@{top0}"
                    rows.append({"shot": i, "why": "station text in the crop", "action": "tighter crop"})
        else:
            v = text_verdict(fr, src_h)
        if v["action"] == "crop" and virtual:
            # No file is changed: the pieces engine crops when it draws. The crop must leave no text behind.
            after = text_verdict(crop_frames(fr, float(v["keep"]), 0.0), int(src_h * float(v["keep"])))
            if after["action"] == "keep":
                cropped[path] = round(float(v["keep"]), 3)
                s.setdefault("stormDesk", {}).update({"cropped": cropped[path], "mode": f"news{cropped[path]}@0.0"})
                rows.append({"shot": i, "why": v["why"], "action": f"cropped to {int(v['keep'] * 100)}% height"})
                continue
            v = {"action": "reject", "why": v["why"] + " (still text after the crop)"}
        if v["action"] == "crop":
            if crop(path, v["keep"]) and text_verdict(read(path, float(m.get("trimStart") or 0.0), int(
                    s["durationInFrames"]) / float(fps)))["action"] == "keep":
                cropped[path] = v["keep"]
                s.setdefault("stormDesk", {})["cropped"] = v["keep"]
                rows.append({"shot": i, "why": v["why"], "action": f"cropped to {int(v['keep'] * 100)}% height"})
                continue
            v = {"action": "reject", "why": v["why"] + " (crop failed)"}
        if v["action"] == "reject":
            if s.get("natSound"):
                rows.append({"shot": i, "why": v["why"], "action": "kept (a pause clip)"})
            else:
                s["_reject"] = v["why"]
                rows.append({"shot": i, "why": v["why"], "action": "replace"})
            continue
        soft[i] = detail(fr)
    if len(soft) >= 4:
        import statistics
        med = statistics.median(soft.values())
        for i, d in soft.items():
            if d < SOFT_FLOOR and d < SOFT_SHARE * med and not doc["scenes"][i].get("natSound"):
                doc["scenes"][i]["_soft"] = True
                rows.append({"shot": i, "why": f"soft / through glass (detail {d:.1f} vs {med:.1f})",
                             "action": "replace if a clearer clip exists"})
    return rows


def bake(path: str, boxes: List[List[float]], flip: bool) -> bool:
    """Blur `boxes` (shares of the frame) and mirror the clip, in place (sound kept). True when replaced."""
    if not boxes and not flip:
        return False
    chain, last = [], "0:v"
    for k, (bx, by, bw, bh) in enumerate(boxes):
        # The blur radius fits the box (a small corner box failed "boxblur=20" on real clips: the radius must stay
        # under half the box's smaller side).
        chain.append(f"[{last}]split[m{k}][c{k}];[c{k}]crop=w='max(8,iw*{bw})':h='max(8,ih*{bh})':"
                     f"x='iw*{bx}':y='ih*{by}',"
                     f"boxblur=luma_radius='min(20,min(w,h)/2-1)':luma_power=3:"
                     f"chroma_radius='min(10,min(cw,ch)/2-1)':chroma_power=3[b{k}];"
                     f"[m{k}][b{k}]overlay=main_w*{bx}:main_h*{by}[o{k}]")
        last = f"o{k}"
    chain.append(f"[{last}]{'hflip,' if flip else ''}format=yuv420p,setsar=1[v]")
    tmp = path + ".sd.mp4"
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", path, "-filter_complex", ";".join(chain), "-map", "[v]",
           "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-c:a", "copy",
           "-movflags", "+faststart", tmp]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=300)
        if p.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) < 5_000:
            raise RuntimeError((p.stderr or b"")[-200:].decode("utf-8", "replace"))
        os.replace(tmp, path)
        return True
    except Exception as e:  # noqa: BLE001 - the clip stays as it was
        print(f"[stormdesk] bake {os.path.basename(path)}: {type(e).__name__}: {str(e)[:120]}", flush=True)
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def lookalikes(vectors: Dict[int, Any], threshold: float = LOOKALIKE) -> List[Tuple[int, int, float]]:
    """(i, j, cosine) of shots whose mean frame embeddings are at least `threshold` alike, i < j."""
    try:
        import numpy as np
    except ImportError:
        return []
    keys = sorted(vectors)
    out = []
    for a in range(len(keys)):
        for b in range(a + 1, len(keys)):
            i, j = keys[a], keys[b]
            c = float(np.dot(vectors[i], vectors[j]))
            if c >= threshold:
                out.append((i, j, round(c, 3)))
    return out


# --------------------------------------------------------------------------- #
# The document pass (after the plan)
# --------------------------------------------------------------------------- #

def _end(s: dict) -> int:
    return int(s["startFrame"]) + int(s["durationInFrames"])


def _local(scene: dict) -> str:
    p = str(((scene.get("media") or {}).get("url")) or "")
    return p if p and os.path.isfile(p) else ""


def _clip_room(scene: dict, fps: int) -> float:
    """Seconds of picture the scene's clip file has from its in-point (inf when unknown)."""
    m = scene.get("media") or {}
    if m.get("type") != "video":
        return float("inf")
    cs = m.get("clipSeconds")
    if not isinstance(cs, (int, float)) or cs <= 0:
        return float("inf")
    return float(cs) - float(m.get("trimStart") or 0.0)


def _trim_head(scene: dict, frames_cut: int, fps: int) -> None:
    scene["startFrame"] = int(scene["startFrame"]) + frames_cut
    scene["durationInFrames"] = int(scene["durationInFrames"]) - frames_cut
    m = scene.get("media") or {}
    if m.get("type") == "video":
        m["trimStart"] = round(float(m.get("trimStart") or 0.0) + frames_cut / float(fps), 3)
    scene["words"] = [w for w in scene.get("words") or [] if float(w.get("end", 0)) * fps > scene["startFrame"]]


def _default_fetch(video: str, start: float, seconds: float, work: str) -> str:
    """A section of a YouTube video WITH its sound (the pause clip), three tries on the worker's routes."""
    from . import srcbank, ytdlp
    vid = video[3:] if video.startswith("yt:") else video
    # A source the source bank downloaded whole (src/srcbank.py): cut from its file, sound and all - no download.
    try:
        local = srcbank.local_section(vid, start, seconds, work, audio=True)
    except Exception:  # noqa: BLE001 - the download below
        local = ""
    if local:
        return local
    # A source of the footage library (src/stormlib.py): its file from the private bucket, no YouTube.
    try:
        from . import stormlib
        if stormlib.ensure_source(vid, work):
            local = srcbank.local_section(vid, start, seconds, work, audio=True)
    except Exception:  # noqa: BLE001 - the download below
        local = ""
    if local:
        return local
    for _ in range(3):
        if ytdlp.bot_stopped():
            return ""
        before = ytdlp.bot_report()["botChecks"]
        try:
            path = ytdlp._yt_fetch(vid, work, start, seconds, audio=True)
        except Exception as e:  # noqa: BLE001 - the next try
            print(f"[stormdesk] pause clip {vid}: {type(e).__name__}: {str(e)[:120]}", flush=True)
            path = ""
        if path and os.path.isfile(path):
            return path
        if ytdlp.bot_fast() and ytdlp.bot_report()["botChecks"] > before:
            return ""                   # a bot check: this source is skipped, no second try
    return ""


def _audible(path: str) -> bool:
    """The clip has a sound stream that is not silence (mean volume over -50 dB)."""
    info = _probe(path)
    if not info.get("audio"):
        return False
    try:
        p = subprocess.run(["ffmpeg", "-v", "info", "-i", path, "-vn", "-af", "volumedetect", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=120)
        m = re.search(r"mean_volume:\s*(-?[\d.]+)\s*dB", p.stderr or "")
        return bool(m) and float(m.group(1)) > -50.0
    except Exception:  # noqa: BLE001
        return False


def _moment_gap() -> float:
    """How far apart two moments of one video must start (the repeat check's rule, gapfill.Used)."""
    try:
        from . import config
        return float(config.FALLBACK_MOMENT_GAP_SECONDS)
    except Exception:  # noqa: BLE001
        return 30.0


def video_seconds(video: str) -> float:
    """A YouTube video's length when the search already said (0 = unknown)."""
    try:
        from . import ytdlp
        return float(ytdlp.known_duration(video[3:] if video.startswith("yt:") else video) or 0.0)
    except Exception:  # noqa: BLE001
        return 0.0


def pause_start(used: List[Tuple[float, float]], want: float, length: float, gap: float) -> Optional[float]:
    """
    Where in a source video a pause clip of `want` seconds may start: at least `gap` seconds from the start of
    every moment the video already gives (the repeat check's rule: a moment nearer counts as the same one) and
    overlapping none of them; after the last one first, else before the first. None = the video has no room.
    """
    if not used:
        return 0.5 if not length or length >= want + 0.5 else None
    starts = [a for a, _b in used]
    ends = [b for _a, b in used]
    options_ = [max(max(starts) + gap, max(ends)) + 0.5, min(starts) - max(gap, want) - 0.5]
    for t in options_:
        if t < 0:
            continue
        if length and t + want > length - 0.2:
            continue
        if all(abs(t - a) >= gap and (t + want <= a - 0.3 or t >= b + 0.3) for a, b in used):
            return round(t, 2)
    return None


def _default_check(path: str) -> str:
    """The worker's own local checks on a pause clip (src/slop.py: a studio, presenter or talking head, another
    creator's captions, a still passed off as footage); '' = keep."""
    try:
        from . import slop
        return slop.check_file(path, "video")
    except Exception:  # noqa: BLE001 - a check that cannot run never rejects
        return ""


def source_title(scene: dict) -> str:
    """The upload's title as the search gave it (the YouTube attribution "YouTube: <title>"), or ''."""
    att = str((scene.get("media") or {}).get("attribution") or "")
    return re.sub(r"^(youtube|dailymotion)\s*[:—-]\s*", "", att, flags=re.I)[:200]


def _relevance(scene: dict) -> float:
    """The judge's relevance for the shot's clip, 0..1 (0.5 when unknown)."""
    v = _sm(scene).get("relevanceScore")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return max(0.0, min(1.0, float(v) / 10.0 if v > 1.0 else float(v)))
    return 0.5


def pause_score(path: str, secs: float, title: str = "", relevance: float = 0.5,
                classify: Optional[Callable] = None, talk_ok: bool = False) -> Optional[dict]:
    """
    How good a fetched clip is as a natural-sound pause, and its best `secs`-long stretch: {"score", "offset",
    "audio" (clipaudio.classify), "energy", "motion"} or {"reject": why}. Strong, lively natural sound (its level
    and its swings: rushing water, gusts, crashing, sirens) and motion score; relevance (the judge's) helps;
    music never plays in a pause (the hand-made videos swapped such clips for real water), silence neither; an
    eyewitness talking is allowed, a little lower. None = unreadable.
    """
    try:
        import numpy as np
        from . import clipaudio
    except ImportError:
        return None
    x = clipaudio.read_mono(path)
    info = (classify or clipaudio.classify)(path, title=title, x=x)
    kind = info.get("kind")
    if kind in ("music", "silent", "unknown"):
        return {"reject": f"its sound is {kind}", "audio": info}
    if float(info.get("speech") or 0.0) >= PAUSE_SPEECH_MAX and not talk_ok:
        # Talking all the way through: a reporter or an interview, not an eyewitness reacting (the Las Vegas run's
        # pause on a station's report).
        return {"reject": "talking all the way through", "audio": info}
    sr = clipaudio.SR
    blk = int(0.25 * sr)
    nb = len(x) // blk if x is not None else 0
    if nb < 4:
        return None
    db = 20 * np.log10(np.sqrt(np.mean(x[: nb * blk].reshape(nb, blk) ** 2, axis=1)) + 1e-9)
    total = nb * 0.25
    win = max(1, int(round(min(secs, total) / 0.25)))
    # Motion: grey change between frames 0.5 s apart over the whole fetched clip.
    fr = frames(path, 0.0, total, n=max(4, int(total * 2)), w=160, h=90)
    mot = []
    for i in range(1, len(fr)):
        mot.append(float(np.mean(np.abs(fr[i].astype(np.float32) - fr[i - 1].astype(np.float32)))))
    best = None
    for o in range(0, max(1, nb - win + 1)):
        w = db[o:o + win]
        energy = max(0.0, min(1.0, (float(np.mean(w)) + 45.0) / 30.0))
        swing = max(0.0, min(1.0, float(np.std(w)) / 8.0))
        if mot:
            a = int(o * 0.25 * 2)
            m = mot[a:a + max(1, int(win * 0.25 * 2))] or mot
            motion = max(0.0, min(1.0, float(np.mean(m)) / 12.0))
        else:
            motion = 0.3
        score = 0.40 * energy + 0.15 * swing + 0.30 * motion + 0.15 * relevance - 0.15 * float(info.get("speech") or 0.0)
        if best is None or score > best[0]:
            best = (score, o * 0.25, energy, motion)
    return {"score": round(best[0], 3), "offset": round(best[1], 2), "energy": round(best[2], 3),
            "motion": round(best[3], 3), "audio": info}


def pause_source_ok(channel: str) -> bool:
    """Who may fill a pause or the hook: stations and agencies, never a person's own channel (the owner's creator rule),
    a vlog, a re-uploader or an unknown uploader."""
    from . import stormledger
    return source_kind(channel) in ("station", "original") and not stormledger.is_personality(channel)


_STOP = set("""a an and are as at be but by for from has have he her his in is it its of on or our she so that the their they
this to was we were what when where which who will with would you your""".split())


def fit_to_words(said: str, text: str) -> float:
    """How much of what the clip says or is called was just said: 0 to 1 (the owner: it must fit what was just said)."""
    def keys(t: str) -> set:
        return {w for w in re.findall(r"[a-z0-9']+", str(t or "").lower()) if len(w) > 2 and w not in _STOP}
    a, b = keys(said), keys(text)
    if not a or not b:
        return 0.0
    return round(min(1.0, len(a & b) / float(min(len(a), len(b), 6))), 3)


def talk_window(words: Sequence, clip_seconds: float, said: str = "", most: float = PAUSE_MAX_SECONDS,
                least: float = PAUSE_MIN_SECONDS) -> Optional[dict]:
    """
    Where a talking clip plays: whole sentences only, from the first word of one to the last word of one, padded a little,
    at most `most` s. A sentence the fetch cut (it touches the clip's start or end) never plays. Prefers what fits `said`,
    then a full-length quote. {"start", "seconds", "text", "fit"} or None.
    """
    words = [w for w in (words or []) if _text(w).strip()]
    if not words:
        return None
    sents = sentences(words)
    whole = []
    for k, s in enumerate(sents):
        if k == 0 and s["start"] < 0.2:
            continue                            # the fetch started inside this sentence
        if s["end"] > clip_seconds - 0.4:
            continue                            # ... or ended inside this one
        if not re.search(r"[.!?][\"')\]]*$", str(s["text"]).strip()):
            continue
        whole.append((k, s))
    best = None
    for i in range(len(whole)):
        for j in range(i, len(whole)):
            if whole[j][0] - whole[i][0] != j - i:
                break                           # sentences that follow each other only
            a = max(0.0, whole[i][1]["start"] - TALK_PAD_BEFORE)
            b = min(clip_seconds, whole[j][1]["end"] + TALK_PAD_AFTER)
            if b - a > most:
                break
            if b - a < least:
                continue
            text = " ".join(str(x[1]["text"]) for x in whole[i:j + 1])
            fit = fit_to_words(said, text)
            score = fit + min(1.0, (b - a) / 10.0) * 0.3
            if best is None or score > best[0]:
                best = (score, a, b, text, fit)
    if best is None:
        return None
    return {"start": round(best[1], 3), "seconds": round(best[2] - best[1], 3), "text": best[3][:300], "fit": best[4]}


def make_pauses(doc: dict, pauses: List[dict], work: str, fetch: Optional[Callable] = None,
                frame_vertical: Optional[Callable[[str], bool]] = None,
                check: Optional[Callable[[str], str]] = None,
                spare_pool: Optional[Callable[[dict], List[dict]]] = None,
                spare_take: Optional[Callable[[dict], bool]] = None,
                listen: Optional[Callable[[str], Sequence]] = None) -> List[dict]:
    """
    Each pause window becomes one scene: a continuous clip with its own sound (scene.natSound), cut from a
    source this block already uses, at a moment no shot shows, never the source of the shot before or after it.
    The shots the plan put in the window are trimmed or removed. A pause no clip could be fetched for keeps the
    plan's shots (silent but for the music) and says so in its row. Returns one row per pause.
    """
    fps = int(doc.get("fps") or 30)
    first_words = [w for s in doc["scenes"] for w in (s.get("words") or [])][:40]    # what a hook clip must fit
    fetch = fetch or (lambda v, s, d: _default_fetch(v, s, d, work))
    check = check or _default_check
    gap = _moment_gap()
    rows: List[dict] = []
    scenes: List[dict] = doc["scenes"]
    used: Dict[str, List[Tuple[float, float]]] = {}
    for s in scenes:
        mo = moment(s, fps)
        if mo:
            used.setdefault(mo[0], []).append((mo[1], mo[2]))
    if JOB_LEDGER is not None:
        for v, ranges in JOB_LEDGER.by_src.items():
            used.setdefault("yt:" + v, []).extend(ranges)   # no pause or hook from a moment of an earlier video
    for k, p in enumerate(pauses):
        p0, p1 = int(round(p["t0"] * fps)), int(round(p["t1"] * fps))
        # The shots either side of the pause once the window is cleared (a shot across an edge is trimmed to it).
        before = [s for s in scenes if int(s["startFrame"]) < p0]
        after = [s for s in scenes if _end(s) > p1]
        inside = [s for s in scenes if int(s["startFrame"]) < p1 and _end(s) > p0]
        prev_key = source_key(before[-1]) if before else ""
        next_key = source_key(after[0]) if after else ""
        is_open = bool(p.get("open"))
        secs = float(p["t1"] - p["t0"])
        # Who the pause may come from: the shots in its window first, then the block before it, nearest first,
        # then just after it. The opening clip: any source of the video, the most relevant first.
        if is_open:
            pool = sorted([s for s in scenes if not is_ai(s)], key=lambda s: -_relevance(s))
        else:
            pool = (inside + list(reversed([s for s in scenes if p0 - 90 * fps <= _end(s) <= p0]))
                    + [s for s in scenes if p1 <= int(s["startFrame"]) <= p1 + 30 * fps])
        tries: List[Tuple[dict, str, float]] = []
        seen: set = set()
        for c in pool:
            mo = moment(c, fps)
            if not mo or mo[0] in seen:
                continue
            seen.add(mo[0])
            if not pause_source_ok(_sm(c).get("channel") or ""):
                continue                        # never a re-uploader's, an unknown uploader's or a person's own channel's
            if not place_ok(source_title(c), JOB_PLACE):
                continue                        # the wrong-place guard: a pause too
            key = source_key(c)
            if key and key in (prev_key, next_key):
                continue                        # never two shots in a row from one source
            want = max(secs, PAUSE_MAX_SECONDS) + PAUSE_SLACK
            start = pause_start(used.get(mo[0], []), want, video_seconds(mo[0]), gap)
            if start is None:
                continue
            if JOB_STRICT and is_station(_sm(c).get("channel") or "") and start < STATION_SKIP_HEAD:
                # A station's source opens on a promo. (Clear of what the video shows there, or this source gives no pause.)
                if any(not (STATION_SKIP_HEAD + want <= a - 0.3 or STATION_SKIP_HEAD >= b + 0.3) for a, b in used.get(mo[0], [])):
                    continue
                start = STATION_SKIP_HEAD
            tries.append((c, mo[0], start))
            if len(tries) >= (PAUSE_TRIES + 1 if is_open else PAUSE_TRIES):
                break
        path, src, best, scored = "", None, None, []

        def fetch_one(t: Tuple[dict, str, float]):
            c, vid, start = t
            try:
                got = fetch(vid, start, max(secs, PAUSE_MAX_SECONDS) + PAUSE_SLACK)
            except Exception as e:  # noqa: BLE001
                print(f"[stormdesk] pause {k + 1}: {type(e).__name__}: {str(e)[:120]}", flush=True)
                return t, "", None
            if not got or not _audible(got):
                return t, "", None
            title = source_title(c)
            said = p.get("sentence", "") or " ".join(str(w.get("text") or "") for w in first_words)
            sc = pause_score(got, secs, title=title, relevance=max(_relevance(c), fit_to_words(said, title)),
                             talk_ok=listen is not None)
            if sc is None or sc.get("reject"):
                print(f"[stormdesk] pause {k + 1}: {vid} @ {start:.0f}s turned down: "
                      f"{(sc or {}).get('reject') or 'unreadable'}", flush=True)
                return t, "", None
            if listen is not None and float((sc.get("audio") or {}).get("speech") or 0.0) >= TALK_SPEECH_MIN:
                # Someone talks: the clip plays whole sentences, on the voice's own word times (the owner: never mid-word).
                try:
                    win = talk_window(listen(got), _probe(got).get("duration") or 0.0, said,
                                      most=HOOK_CLIP_MAX if is_open else PAUSE_MAX_SECONDS)
                except Exception as e:  # noqa: BLE001
                    print(f"[stormdesk] pause {k + 1}: words not read: {type(e).__name__}", flush=True)
                    win = None
                if win is None:
                    print(f"[stormdesk] pause {k + 1}: {vid} @ {start:.0f}s turned down: no whole sentence in it", flush=True)
                    return t, "", None
                if win["fit"] <= 0.0:
                    # A person talking about something else breaks the story (the first proof's hook: another dam project).
                    print(f"[stormdesk] pause {k + 1}: {vid} @ {start:.0f}s turned down: what is said does not fit", flush=True)
                    return t, "", None
                sc = {**sc, "offset": win["start"], "fitSecs": win["seconds"], "talk": win["text"],
                      "score": round(float(sc.get("score") or 0.0) + 0.3 * win["fit"], 3)}
            why = check(got)
            if why:
                print(f"[stormdesk] pause {k + 1}: {vid} @ {start:.0f}s turned down: {why}", flush=True)
                return t, "", None
            return t, got, sc
        if tries:
            with ThreadPoolExecutor(min(3, len(tries))) as ex:
                results = list(ex.map(fetch_one, tries))
            for t, got, sc in results:
                if got and sc is not None:
                    scored.append({"video": t[1], "at": round(t[2], 1), "score": sc["score"]})
                    if best is None or sc["score"] > best[2]["score"]:
                        best = (t, got, sc)
        if best is None:
            # Nothing fetched (the routes refused, or every candidate was music / a report / a banner): the job's
            # spare bank - footage it already downloaded with its sound and the judge passed, shown nowhere.
            job = {"index": f"pause{k}", "context": p.get("sentence", ""), "intent": "natural sound of the event",
                   "query": " ".join(str(_sm(c).get("searchQuery") or "") for c in pool[:3])}
            for e in (spare_pool or _spare_pool)(job)[:6]:
                vid = f"yt:{e.get('vid')}" if e.get("vid") else ""
                ep = str(e.get("path") or "")
                if not vid or not ep or not os.path.isfile(ep) or vid in seen:
                    continue
                if e.get("channel") and not pause_source_ok(str(e.get("channel"))):
                    continue
                if any(source_key(x) in (prev_key, next_key) for x in scenes if video_id(x) == vid):
                    continue
                st0 = float(e.get("start") or 0.0)
                if any(abs(st0 - a) < gap for a, _b in used.get(vid, [])):
                    continue
                if (_probe(ep).get("duration") or 0.0) < secs:
                    continue
                if not _audible(ep):
                    continue
                sc = pause_score(ep, secs, title=str(e.get("title") or ""), relevance=0.5)
                if sc is None or sc.get("reject") or check(ep):
                    continue
                if not (spare_take or _spare_take)(e):
                    continue
                donor = {"media": {"source": "youtube", "attribution": f"YouTube: {e.get('title') or ''}"[:300]},
                         "semanticMetadata": {"contentDescription": str(e.get("description") or "")[:300]}}
                best = ((donor, vid, st0), ep, sc)
                scored.append({"video": vid, "at": round(st0, 1), "score": sc["score"], "spare": True})
                break
        if best is not None:
            (c, vid, start), path, sc = best
            if frame_vertical is not None:
                try:
                    frame_vertical(path)
                except Exception:  # noqa: BLE001 - shown as downloaded
                    pass
            src = (c, vid, start, sc)
        row = {"t0": p["t0"], "t1": p["t1"], "sentence": p.get("sentence", "")[:120]}
        if not path:
            for s in inside:
                s["natSoundWanted"] = True
            row["clip"] = None
            row["why"] = "no source clip with sound could be fetched; the plan's shots stay (music only)"
            if is_open:
                row["open"] = True
            rows.append(row)
            continue
        donor, vid, start, sc = src
        offset = float(sc.get("offset") or 0.0)
        info = _probe(path)
        sm = dict(_sm(donor))
        sm.update({"sourceUrl": f"https://www.youtube.com/watch?v={vid[3:]}&t={int(start)}",
                   "moment": {"start": round(start, 2)}, "assetId": f"{vid}@{int(start)}",
                   "intent": "opening clip" if is_open else "natural sound pause", "alternatives": []})
        pause = {
            "id": f"pause{k + 1}", "startFrame": p0, "durationInFrames": p1 - p0, "text": "",
            "visualType": "footage", "motion": "none", "treatment": "none", "transition": "none",
            "effect": "none", "frame": "full", "reframe": "off", "words": [], "natSound": True,
            "media": {"type": "video", "url": path, "source": (donor.get("media") or {}).get("source", "youtube"),
                      "attribution": (donor.get("media") or {}).get("attribution", ""),
                      "license": (donor.get("media") or {}).get("license", ""),
                      "clipSeconds": round(info.get("duration") or (p1 - p0) / fps, 3),
                      "trimStart": round(offset, 3), "clipAudio": sc.get("audio") or {}},
            "semanticMetadata": sm, "reviewRequired": False, "reviewReason": "",
            **({"openClip": True} if is_open else {}),
            **({"_fitSecs": float(sc["fitSecs"])} if sc.get("fitSecs") else {}),
            **({"talk": True, "_talkText": str(sc.get("talk") or "")[:300]} if sc.get("talk") else {}),
        }
        # The window: shots inside go, shots across its edges are trimmed to it.
        keep: List[dict] = []
        for s in scenes:
            a, b = int(s["startFrame"]), _end(s)
            if b <= p0 or a >= p1:
                keep.append(s)
                continue
            if a < p0 and b > p1:                       # one shot across the whole window: its two sides
                tail = json.loads(json.dumps(s))
                tail["id"] = f"{s['id']}b"
                s["durationInFrames"] = p0 - a
                s["words"] = [w for w in s.get("words") or [] if float(w.get("start", 0)) * fps < p0]
                _trim_head(tail, p1 - a, fps)
                keep += [s, tail]
            elif a < p0:
                s["durationInFrames"] = p0 - a
                s["words"] = [w for w in s.get("words") or [] if float(w.get("start", 0)) * fps < p0]
                keep.append(s)
            elif b > p1:
                _trim_head(s, p1 - a, fps)
                keep.append(s)
        keep = [s for s in keep if int(s["durationInFrames"]) > 0]
        # A sliver under 0.6 s beside the pause goes to the pause (its clip has a second spare).
        sl = int(0.6 * fps)
        for s in list(keep):
            if int(s["durationInFrames"]) >= sl:
                continue
            if _end(s) == p0 and pause["startFrame"] == p0:
                pause["startFrame"] -= int(s["durationInFrames"])
                pause["durationInFrames"] += int(s["durationInFrames"])
                keep.remove(s)
            elif int(s["startFrame"]) == p1:
                pause["durationInFrames"] += int(s["durationInFrames"])
                keep.remove(s)
        head = p0 - int(pause["startFrame"])
        if head > 0:                                    # a sliver before it joined: the clip starts that much earlier
            pause["media"]["trimStart"] = round(max(0.0, offset - head / float(fps)), 3)
        keep.append(pause)
        keep.sort(key=lambda s: int(s["startFrame"]))
        scenes[:] = keep
        t_in = start + float(pause["media"]["trimStart"])
        used.setdefault(vid, []).append((t_in, t_in + int(pause["durationInFrames"]) / float(fps)))
        row.update({"clip": path, "source": credit_name(donor), "video": vid, "at": round(t_in, 1),
                    "score": sc.get("score"), "sound": (sc.get("audio") or {}).get("kind"),
                    "candidates": scored, **({"open": True} if is_open else {})})
        rows.append(row)
    return rows


def cap_shots(doc: dict, cap: float = SHOT_MAX) -> int:
    """Every narration shot at most `cap` seconds: a longer one is cut on its own clip (the next moment of it).
    Pauses and full-screen graphics keep their length. Returns the shots cut."""
    fps = int(doc.get("fps") or 30)
    limit = int(round(cap * fps)) + 1
    out, n = [], 0
    for s in doc["scenes"]:
        if s.get("natSound") or s.get("heldOver") or (s.get("media") or {}).get("type") == "animation" or \
                int(s["durationInFrames"]) <= limit:
            out.append(s)
            continue
        parts = math.ceil(int(s["durationInFrames"]) / float(cap * fps))
        size = int(s["durationInFrames"]) // parts
        a = int(s["startFrame"])
        for j in range(parts):
            piece = json.loads(json.dumps(s))
            piece["id"] = s["id"] if j == 0 else f"{s['id']}c{j}"
            piece["startFrame"] = a + j * size
            piece["durationInFrames"] = size if j < parts - 1 else int(s["durationInFrames"]) - size * j
            if j:
                m = piece.get("media") or {}
                if m.get("type") == "video":
                    m["trimStart"] = round(float(m.get("trimStart") or 0.0) + j * size / float(fps), 3)
                piece["splitFrom"] = s["id"]
            lo, hi = piece["startFrame"], piece["startFrame"] + piece["durationInFrames"]
            piece["words"] = [w for w in s.get("words") or [] if lo <= float(w.get("start", 0)) * fps < hi]
            out.append(piece)
        n += 1
    doc["scenes"] = out
    return n


def _swap_ok(scenes: List[dict], i: int, j: int, fps: int) -> bool:
    a, b = scenes[i], scenes[j]
    if a.get("natSound") or b.get("natSound"):
        return False
    da, db = int(a["durationInFrames"]) / fps, int(b["durationInFrames"]) / fps
    if _clip_room(a, fps) < db - 0.05 or _clip_room(b, fps) < da - 0.05:
        return False
    ka, kb = source_key(a), source_key(b)

    def nb(k: int, key: str, skip: int) -> bool:
        for d in (-1, 1):
            m = k + d
            if 0 <= m < len(scenes) and m != skip and source_key(scenes[m]) == key:
                return False
        return True
    return nb(j, ka, i) and nb(i, kb, j)


def _swap(scenes: List[dict], i: int, j: int) -> None:
    for key in ("media", "semanticMetadata", "credit"):
        a, b = scenes[i].get(key), scenes[j].get(key)
        if b is None:
            scenes[i].pop(key, None)
        else:
            scenes[i][key] = b
        if a is None:
            scenes[j].pop(key, None)
        else:
            scenes[j][key] = a


def fix_neighbours(doc: dict, window: int = 6) -> Tuple[int, int]:
    """Two shots in a row from one source: the second trades places with a nearby shot of another source (both
    clips long enough, no new pair made). Returns (fixed, still there)."""
    fps = int(doc.get("fps") or 30)
    sc = doc["scenes"]
    fixed = 0
    for i in range(1, len(sc)):
        k = source_key(sc[i])
        if not k or k != source_key(sc[i - 1]):
            continue
        for d in sorted(range(-window, window + 1), key=abs):
            j = i + d
            if d in (-1, 0, 1) or not (0 <= j < len(sc)) or (sc[j].get("media") or {}).get("type") != "video":
                continue
            if _swap_ok(sc, i, j, fps):
                _swap(sc, i, j)
                fixed += 1
                break
    left = sum(1 for i in range(1, len(sc)) if source_key(sc[i]) and source_key(sc[i]) == source_key(sc[i - 1]))
    return fixed, left


def keep_ai_out_of_opening(doc: dict, seconds: float = NO_AI_SECONDS) -> Tuple[int, int]:
    """An AI shot in the first minute trades places with a real clip later in the video. (moved, still there)"""
    fps = int(doc.get("fps") or 30)
    sc = doc["scenes"]
    moved = 0
    for i, s in enumerate(sc):
        if int(s["startFrame"]) >= seconds * fps:
            break
        if not is_ai(s):
            continue
        for j in range(len(sc) - 1, i, -1):
            if int(sc[j]["startFrame"]) < seconds * fps:
                break
            if not is_ai(sc[j]) and (sc[j].get("media") or {}).get("type") == "video" and _swap_ok(sc, i, j, fps):
                _swap(sc, i, j)
                moved += 1
                break
    left = sum(1 for s in sc if int(s["startFrame"]) < seconds * fps and is_ai(s))
    return moved, left


def repeats(doc: dict) -> List[dict]:
    """Shots showing the same moment of one source video (overlapping by 0.3 s or more)."""
    fps = int(doc.get("fps") or 30)
    seen: Dict[str, List[Tuple[float, float, int]]] = {}
    out = []
    for i, s in enumerate(doc["scenes"]):
        mo = moment(s, fps)
        if not mo:
            continue
        for a, b, j in seen.get(mo[0], []):
            if min(b, mo[2]) - max(a, mo[1]) >= 0.3:
                out.append({"shot": i, "same_as": j, "video": mo[0], "at": round(mo[1], 1)})
        seen.setdefault(mo[0], []).append((mo[1], mo[2], i))
    # The same picture twice (the Las Vegas run showed four photos two times each).
    pics: Dict[str, int] = {}
    for i, s in enumerate(doc["scenes"]):
        k = photo_key(s)
        if not k:
            continue
        if k in pics:
            out.append({"shot": i, "same_as": pics[k], "photo": True})
        else:
            pics[k] = i
    return out


# --------------------------------------------------------------------------- #
# Stills: real clips first (the owner's Las Vegas review, 2026-11-03: ~45 photos of 145 shots, some twice)
# --------------------------------------------------------------------------- #

PHOTO_SHARE_MAX = 0.10          # photos at most this share of the shots, the last resort; never in the opening
HOLD_SLOWEST = 0.6              # a held-over original clip plays no slower than this (else it is not held)


def is_photo(scene: dict) -> bool:
    return (scene.get("media") or {}).get("type") == "image" and not is_ai(scene)


def is_empty(scene: dict) -> bool:
    m = scene.get("media") or {}
    return m.get("type") not in ("video", "image", "animation") or not str(m.get("url") or "").strip()


def photo_key(scene: dict) -> str:
    """One picture, whichever line shows it: its source page / link, else its title."""
    if not is_photo(scene):
        return ""
    sm = _sm(scene)
    m = scene.get("media") or {}
    for raw in (sm.get("assetId"), sm.get("pageUrl"), sm.get("sourceUrl"), m.get("url")):
        raw = str(raw or "").split("?")[0].strip()
        if raw:
            return "u:" + raw
    t = _norm_name(m.get("attribution") or "")
    return ("t:" + t) if len(t) >= 12 else ""


def photo_years(scene: dict) -> List[int]:
    """Years a picture's title or description names ("Flood devastation in 1999")."""
    sm = _sm(scene)
    blob = " ".join(str(x or "") for x in ((scene.get("media") or {}).get("attribution"),
                                           sm.get("contentDescription"), sm.get("sourceTitle")))
    return [int(y) for y in re.findall(r"\b(19\d\d|20\d\d)\b", blob)]


def stills_to_replace(doc: dict, opening: float = NO_AI_SECONDS,
                      share: float = PHOTO_SHARE_MAX) -> List[Tuple[int, str]]:
    """[(scene index, why)]: empty shots, a picture shown again, pictures in the opening, then the pictures past
    `share` of the shots (the latest first: the opening and the hook keep the real clips)."""
    fps = int(doc.get("fps") or 30)
    sc = doc["scenes"]
    out: List[Tuple[int, str]] = []
    seen: set = set()
    for i, s in enumerate(sc):
        if s.get("natSound") or (s.get("media") or {}).get("type") == "animation":
            continue
        if is_empty(s):
            out.append((i, "empty"))
            continue
        k = photo_key(s)
        if not k:
            continue
        if k in seen:
            out.append((i, "the same picture again"))
        elif int(s["startFrame"]) < opening * fps:
            out.append((i, "a picture in the opening"))
        seen.add(k)
    for i, s in enumerate(sc):
        if s.get("natSound") or i in {j for j, _ in out} or (s.get("media") or {}).get("type") != "video" \
                or is_ai(s) or not video_id(s).startswith("yt:"):
            continue
        if s.get("_reject"):
            out.append((i, "text over the picture"))
            continue
        if s.get("_soft"):
            out.append((i, "soft / through glass"))
            continue
        kind = source_kind(_sm(s).get("channel") or "")
        if kind == "reupload":
            out.append((i, "a re-uploader's footage"))
        elif kind == "unknown":
            out.append((i, "an unknown source"))
    taken = {i for i, _ in out}
    photos = [i for i, s in enumerate(sc) if is_photo(s) and i not in taken]
    cap = int(share * max(1, len(sc)))
    for i in reversed(photos[cap:]):
        out.append((i, f"more than {int(share * 100)}% pictures"))
    return out


def _spare_pool(job: dict) -> List[dict]:
    try:
        from . import spares
        return spares.candidates(job, "video", limit=10)
    except Exception:  # noqa: BLE001 - no bank: nothing replaced
        return []


def _spare_take(entry: dict) -> bool:
    try:
        from . import spares
        return spares.take(entry)
    except Exception:  # noqa: BLE001
        return False


def _yt_meta(vid: str) -> dict:
    """A YouTube video's metadata (channel, upload_date, title, description) from the worker's cached reader."""
    try:
        from . import media
        got = media._yt_info(vid[3:] if vid.startswith("yt:") else vid)
        info = got[0] if isinstance(got, tuple) else got
        return info if isinstance(info, dict) else {}
    except Exception:  # noqa: BLE001 - unknown stays unknown
        return {}


_PLACE_GENERIC = set("""lake river creek canyon dam mount mountain valley county city town state national park reservoir basin bay
beach falls island north south east west new upper lower fort saint san santa los las the of""".split())


def place_regex(inp: Optional[dict], brief: Optional[dict] = None) -> Optional[Any]:
    """The wrong-place guard's pattern: storm_desk.place_regex, else the story's places (their first part, and a many-word
    name's own word: "Lake Mead, NV" also matches "Mead"). None when the story names no place: nothing to guard."""
    raw = str(options(inp).get("place_regex") or "").strip()
    if raw:
        try:
            return re.compile(raw, re.I)
        except re.error:
            print("[stormdesk] place_regex is not a valid pattern: the story's places are used", flush=True)
    names: List[str] = []
    for p in (brief or {}).get("places") or []:
        name = str(p or "").split(",")[0].strip().lower()
        if len(name) < 3:
            continue
        names.append(re.escape(name))
        own = [w for w in re.findall(r"[a-z0-9']+", name) if w not in _PLACE_GENERIC and len(w) >= 4]
        names += [re.escape(w) for w in own if len(own) < len(name.split())]
    if not names:
        return None
    return re.compile(r"\b(?:" + "|".join(sorted(set(names), key=len, reverse=True)) + r")\b", re.I)


def place_ok(title: str, rx: Optional[Any]) -> bool:
    """The source's title is about the story's place. A title not known yet is not refused (it is read before any use)."""
    return rx is None or not str(title or "").strip() or bool(rx.search(str(title)))


def station_shots(opts: Optional[dict]) -> int:
    """One station channel's shots a video (storm_desk.station_shots, else STORM_STATION_SHOTS)."""
    from . import config
    try:
        return max(1, int((opts or {}).get("station_shots") or getattr(config, "STORM_STATION_SHOTS", 26)))
    except (TypeError, ValueError):
        return int(getattr(config, "STORM_STATION_SHOTS", 26))


def resolve_channels(doc: dict, info: Optional[Callable[[str], dict]] = None) -> int:
    """Every YouTube shot whose uploader is not known yet ("VIDEO: YouTube" on screen) gets it from the video's
    metadata, with its upload day. Returns how many were resolved."""
    info = info or _yt_meta
    todo: Dict[str, List[dict]] = {}
    for s in doc.get("scenes") or []:
        v = video_id(s)
        if v.startswith("yt:") and not str(_sm(s).get("channel") or "").strip() and not is_ai(s):
            todo.setdefault(v, []).append(s)
    if not todo:
        return 0
    with ThreadPoolExecutor(4) as ex:
        got = dict(zip(todo, ex.map(lambda v: info(v) or {}, list(todo))))
    n = 0
    for v, shots in todo.items():
        meta = got.get(v) or {}
        ch = str(meta.get("channel") or meta.get("uploader") or "").strip()
        if not ch:
            continue
        for s in shots:
            sm = s.setdefault("semanticMetadata", {})
            sm["channel"] = ch[:80]
            up = str(meta.get("upload_date") or "")
            if re.fullmatch(r"\d{8}", up):
                sm["uploadDate"] = up
            if meta.get("description") and reupload_text(str(meta.get("description"))):
                sm["reupload"] = True
            n += 1
    return n


def _reuse_original(doc: dict, i: int, used: Dict[str, List[float]], gap: float, allow_near: bool = False) -> bool:
    """Scene i from an original clip already in the video: the part of its file the video does not show (after
    or before the shot's own stretch, never overlapping it), from a source that is not the shot before's or
    after's. Repeat-safe: a different moment of an original source."""
    fps = int(doc.get("fps") or 30)
    sc = doc["scenes"]
    secs = int(sc[i]["durationInFrames"]) / float(fps)
    near = {source_key(sc[j]) for j in (i - 1, i + 1) if 0 <= j < len(sc)}
    for j, d in enumerate(sc):
        m = d.get("media") or {}
        if j == i or d.get("natSound") or m.get("type") != "video" or is_ai(d) or not _local(d):
            continue
        if source_kind(_sm(d).get("channel") or "") not in ("station", "original", "creator"):
            continue
        if source_key(d) in near and not allow_near:
            continue
        cs = m.get("clipSeconds")
        if not isinstance(cs, (int, float)):
            continue
        t0 = float(m.get("trimStart") or 0.0)
        t1 = t0 + int(d["durationInFrames"]) / float(fps)
        others = [x for x in sc if x is not d and (x.get("media") or {}).get("url") == m.get("url")]
        spans = [(float((x.get("media") or {}).get("trimStart") or 0.0),
                  float((x.get("media") or {}).get("trimStart") or 0.0) + int(x["durationInFrames"]) / float(fps))
                 for x in others] + [(t0, t1)]
        for at in (t1 + 0.3, t0 - 0.3 - secs):
            if at < 0 or at + secs > float(cs) - 0.05:
                continue
            if any(not (at + secs <= a - 0.2 or at >= b + 0.2) for a, b in spans):
                continue
            new = json.loads(json.dumps(m))
            new["trimStart"] = round(at, 3)
            sc[i]["media"] = new
            smd = dict(_sm(d))
            mo = smd.get("moment") if isinstance(smd.get("moment"), dict) else {}
            base = float(mo.get("start") or 0.0) - t0 if isinstance(mo.get("start"), (int, float)) else None
            if base is not None:
                smd["moment"] = {"start": round(base + at, 2)}
            smd["replacedStill"] = "another moment of an original clip"
            sc[i]["semanticMetadata"] = {**_sm(sc[i]), **smd}
            sc[i]["visualType"] = "footage"
            sc[i]["motion"] = "none"
            sc[i].pop("reviewRequired", None)
            return True
    return False


def _hold_previous(doc: dict, i: int) -> bool:
    """The last resort for a shot with nothing to show: the shot before it holds longer over its words (its
    clip has the room). A longer real shot beats a re-upload or an empty frame (the owner)."""
    fps = int(doc.get("fps") or 30)
    sc = doc["scenes"]
    if i == 0:
        return False
    prev, cur = sc[i - 1], sc[i]
    if prev.get("natSound") or (prev.get("media") or {}).get("type") != "video" or \
            source_kind(_sm(prev).get("channel") or "") not in ("station", "original", "creator"):
        return False
    # Its clip may play down to HOLD_SLOWEST of its speed (the renderer slows a clip shorter than its scene).
    if _clip_room(prev, fps) * (1.0 / HOLD_SLOWEST) < (int(prev["durationInFrames"]) + int(cur["durationInFrames"])) \
            / float(fps) - 0.05:
        return False
    prev["durationInFrames"] = int(prev["durationInFrames"]) + int(cur["durationInFrames"])
    prev["words"] = list(prev.get("words") or []) + list(cur.get("words") or [])
    prev["text"] = (str(prev.get("text") or "") + " " + str(cur.get("text") or "")).strip()
    prev["heldOver"] = True
    del sc[i]
    return True


def _hold_next(doc: dict, i: int) -> bool:
    """_hold_previous the other way: the shot after it starts earlier and holds over both (slowed as needed)."""
    fps = int(doc.get("fps") or 30)
    sc = doc["scenes"]
    if i + 1 >= len(sc):
        return False
    cur, nxt = sc[i], sc[i + 1]
    if nxt.get("natSound") or (nxt.get("media") or {}).get("type") != "video" or \
            source_kind(_sm(nxt).get("channel") or "") not in ("station", "original", "creator"):
        return False
    if _clip_room(nxt, fps) * (1.0 / HOLD_SLOWEST) < (int(nxt["durationInFrames"]) + int(cur["durationInFrames"])) \
            / float(fps) - 0.05:
        return False
    nxt["startFrame"] = int(cur["startFrame"])
    nxt["durationInFrames"] = int(nxt["durationInFrames"]) + int(cur["durationInFrames"])
    nxt["words"] = list(cur.get("words") or []) + list(nxt.get("words") or [])
    nxt["text"] = (str(cur.get("text") or "") + " " + str(nxt.get("text") or "")).strip()
    nxt["heldOver"] = True
    del sc[i]
    return True


def replace_stills(doc: dict, pool: Optional[Callable[[dict], List[dict]]] = None,
                   take: Optional[Callable[[dict], bool]] = None,
                   check: Optional[Callable[[str], str]] = None,
                   info: Optional[Callable[[str], dict]] = None, spare: bool = True, reuse: bool = True,
                   hold: bool = True, only_empty: bool = False, near: bool = False) -> dict:
    """
    Real clips for the shots stills_to_replace names, from the job's spare bank (src/spares.py: footage this job
    already downloaded and the judge passed, not shown anywhere): the best word match whose source is not the
    shot before's or after's, whose moment no other shot shows, and long enough. A picture left in the opening
    trades places with a real clip later on. Returns {"replaced", "moved", "left": [(index, why)]}.
    spare / reuse / hold: which rungs run (stormgate.ensure_media walks them one at a time); only_empty: only shots with
    nothing to show; near: another moment even from the source beside the shot.
    """
    fps = int(doc.get("fps") or 30)
    sc = doc["scenes"]
    pool = pool or _spare_pool
    take = take or _spare_take
    gap = _moment_gap()
    used: Dict[str, List[float]] = {}
    for s in sc:
        mo = moment(s, fps)
        if mo:
            used.setdefault(mo[0], []).append(mo[1])
    resolved = resolve_channels(doc, info)
    info = info or _yt_meta
    done, moved, left = 0, 0, []
    wanted = [(i, w) for i, w in stills_to_replace(doc) if not only_empty or w == "empty"]
    for i, why in wanted:
        if not spare:
            left.append((i, why))
            continue
        s = sc[i]
        secs = int(s["durationInFrames"]) / float(fps)
        sm = _sm(s)
        job = {"index": i, "intent": sm.get("intent") or "", "context": s.get("text") or "",
               "query": s.get("query") or sm.get("searchQuery") or "", "subject": sm.get("subject") or "",
               "place": " ".join(str(p) for p in (sm.get("locations") or []) if p)}
        near = {source_key(sc[j]) for j in (i - 1, i + 1) if 0 <= j < len(sc)}
        got = None
        for e in pool(job) or []:
            vid = f"yt:{e.get('vid')}" if e.get("vid") else ""
            path = str(e.get("path") or "")
            if not vid or not path or not os.path.isfile(path):
                continue
            if vid in near or any(abs(float(e.get("start") or 0.0) - t) < gap for t in used.get(vid, [])):
                continue
            room = _probe(path).get("duration") or 0.0
            if room < secs - 0.05:
                continue
            meta = info(vid) or {}
            ch = str(meta.get("channel") or meta.get("uploader") or e.get("channel") or "")
            if source_kind(ch, "", str(meta.get("description") or "")) not in ("station", "original", "creator"):
                continue                                # a spare from a re-uploader or of no known source
            if check is not None and check(path):
                continue
            if not take(e):
                continue
            e = dict(e, channel=ch, upload_date=str(meta.get("upload_date") or ""))
            got = (e, vid, room)
            break
        if got is None:
            left.append((i, why))
            continue
        e, vid, room = got
        start = float(e.get("start") or 0.0)
        s["media"] = {"type": "video", "url": e["path"], "source": "youtube",
                      "attribution": f"YouTube: {e.get('title') or ''}"[:300], "clipSeconds": round(room, 3)}
        s["semanticMetadata"] = {**{k: v for k, v in sm.items()
                                    if k not in ("channel", "uploadDate", "pageUrl", "reupload")},
                                 **({"channel": e["channel"][:80]} if e.get("channel") else {}),
                                 **({"uploadDate": e["upload_date"]} if re.fullmatch(r"\d{8}", e.get("upload_date") or "")
                                    else {}),
                                 "sourceUrl": f"https://www.youtube.com/watch?v={vid[3:]}&t={int(start)}",
                                 "moment": {"start": round(start, 2)}, "assetId": f"{vid}@{int(start)}",
                                 "contentDescription": str(e.get("description") or "")[:300],
                                 "provider": "youtube", "replacedStill": why}
        s["visualType"] = "footage"
        s["motion"] = "none"
        s.pop("reviewRequired", None)
        used.setdefault(vid, []).append(start)
        done += 1
    # Nothing in the bank: another moment of an original clip the video already uses.
    left2 = []
    for i, why in left:
        if reuse and why not in ("a picture in the opening", "soft / through glass") and _reuse_original(doc, i, used, gap, allow_near=near):
            done += 1
        else:
            left2.append((i, why))
    left = left2
    # A picture still in the opening: trades places with a real clip later on.
    still_left = []
    for i, why in left:
        if why == "a picture in the opening":
            swapped = False
            for j in range(len(sc) - 1, i, -1):
                if int(sc[j]["startFrame"]) < NO_AI_SECONDS * fps:
                    break
                if (sc[j].get("media") or {}).get("type") == "video" and not sc[j].get("natSound") \
                        and not is_ai(sc[j]) and _swap_ok(sc, i, j, fps):
                    _swap(sc, i, j)
                    moved += 1
                    swapped = True
                    break
            if not swapped:
                still_left.append((i, why))
            continue
        still_left.append((i, why))
    # Still nothing for an empty shot or a re-upload: the shot before holds longer (from the end, so the indexes
    # still to come stay right). Pictures past the share stay (a real photo beats an empty frame).
    hard_why = ("empty", "a re-uploader's footage", "an unknown source", "text over the picture")
    held = 0
    for _round in range(6 if hold else 0):      # a hold can make the next one possible (its neighbour fixed)
        changed = False
        for i, why in sorted(stills_to_replace(doc), key=lambda t: -t[0]):
            if why not in hard_why or (only_empty and why != "empty"):
                continue
            if _hold_previous(doc, i) or _hold_next(doc, i):
                held += 1
                changed = True
            elif reuse and _reuse_original(doc, i, used, gap, allow_near=True):
                # Never a competitor's footage: another stretch of an original clip, even from the shot beside
                # it (the owner: a repeat-safe reuse of originals beats a re-upload).
                done += 1
                changed = True
        if not changed:
            break
    final_left = [(i, w) for i, w in stills_to_replace(doc)
                  if w in hard_why or w in ("a picture in the opening", "soft / through glass")
                  or w.startswith("more than")]
    return {"replaced": done, "moved": moved, "held": held, "resolved": resolved, "left": sorted(final_left)}


def shares(doc: dict) -> List[dict]:
    """Seconds and share of the runtime per source (credit name), biggest first."""
    fps = int(doc.get("fps") or 30)
    total = max(1, int(doc.get("durationInFrames") or 0) or sum(int(s["durationInFrames"]) for s in doc["scenes"]))
    acc: Dict[str, List] = {}
    for s in doc["scenes"]:
        if (s.get("media") or {}).get("type") not in ("video", "image"):
            continue
        k = source_key(s) or "?"
        row = acc.setdefault(k, [credit_name(s), 0])
        row[1] += int(s["durationInFrames"])
    rows = [{"source": name, "seconds": round(fr / fps, 1), "share": round(fr / total, 4)}
            for name, fr in acc.values()]
    return sorted(rows, key=lambda r: -r["seconds"])


def blocks_of(doc: dict, pauses: List[dict]) -> List[dict]:
    """
    The narration blocks (one lower third each): from the first word, again after every pause, and inside a
    stretch longer than BLOCK_MAX at the sentence start nearest its middle (blocks at least BLOCK_MIN long).
    [{"i", "start" (s), "end", "text"}]
    """
    words = sorted(((float(w.get("start", 0)), float(w.get("end", 0)), str(w.get("text") or ""))
                    for s in doc["scenes"] for w in (s.get("words") or [])), key=lambda x: x[0])
    if not words:
        return []
    starts = [words[0][0]]
    for i in range(1, len(words)):
        if re.search(r"[.!?][\"')\]]*$", words[i - 1][2].strip()) or words[i][0] - words[i - 1][1] >= 1.2:
            starts.append(words[i][0])
    cuts = [words[0][0]]
    for p in pauses:
        nxt = next((t for t in starts if t >= p["t1"] - 0.05), None)
        if nxt is not None and nxt - cuts[-1] >= BLOCK_MIN * 0.5:
            cuts.append(nxt)
    end = words[-1][1]
    bounds = sorted(set(cuts)) + [end]

    def split(a: float, b: float) -> List[float]:
        if b - a <= BLOCK_MAX:
            return [a]
        inner = [t for t in starts if a + BLOCK_MIN <= t <= b - BLOCK_MIN]
        if not inner:
            return [a]
        mid = min(inner, key=lambda t: abs(t - (a + b) / 2))
        return split(a, mid) + split(mid, b)
    final: List[float] = []
    for a, b in zip(bounds, bounds[1:]):
        final += split(a, b)
    out = []
    for k, a in enumerate(final):
        b = final[k + 1] if k + 1 < len(final) else end
        text = " ".join(w[2] for w in words if a - 1e-6 <= w[0] < b - 1e-6)
        out.append({"i": k, "start": round(a, 3), "end": round(b, 3), "text": re.sub(r"\s+", " ", text).strip()})
    return out


def _hex(c: Any, fallback: str) -> str:
    c = str(c or "").strip()
    return c if re.fullmatch(r"#[0-9A-Fa-f]{6}", c) else fallback


def _shade(c: str, k: float) -> str:
    """A colour darkened (k < 1) or lightened (k > 1)."""
    r, g, b = (int(c[i:i + 2], 16) for i in (1, 3, 5))
    if k <= 1:
        r, g, b = (round(v * k) for v in (r, g, b))
    else:
        r, g, b = (round(v + (255 - v) * (k - 1)) for v in (r, g, b))
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, v)) for v in (r, g, b)))


def colors(inp: dict, kit: Optional[dict]) -> dict:
    """The reference's palette in the customer's colours: the brand accent = the bar, its deep shade = the logo
    box; accent2 = the tab and chips' red. The job's own colors win."""
    out = dict(COLORS)
    acc = _hex((kit or {}).get("accent"), "")
    acc2 = _hex((kit or {}).get("accent2"), "")
    if acc:
        out.update(bar=acc, bar2=_shade(acc, 0.42), logo=_shade(acc, 0.45), logo2=_shade(acc, 0.22),
                   place=_shade(acc, 0.55), rim=_shade(acc, 1.45))
    if acc2:
        out.update(tab=acc2, tab2=_shade(acc2, 0.8), divider=acc2, date=_shade(acc2, 0.9), pin=_shade(acc2, 0.9),
                   pill=acc2)
    for k, v in (options(inp).get("colors") or {}).items() if isinstance(options(inp).get("colors"), dict) else []:
        if k in out:
            out[k] = _hex(v, out[k])
    return out


def graphics(doc: dict, inp: dict, blocks: List[dict], brief: Optional[dict], kit: Optional[dict],
             day: Optional[datetime.date]) -> dict:
    """doc.stormDesk: what components/brand/StormDesk.tsx draws."""
    fps = int(doc.get("fps") or 30)
    total = int(doc.get("durationInFrames") or 0)
    opts = options(inp)
    lts = []
    for b in blocks:
        a = int(round((b["start"] + LT_LEAD) * fps))
        nxt = next((int(round((x["start"] + LT_LEAD) * fps)) for x in blocks if x["i"] == b["i"] + 1), total)
        dur = min(int(LT_HOLD * fps), max(0, nxt - a - int(0.6 * fps)), max(0, total - a))
        if dur >= int(3 * fps) and b.get("lines"):
            lts.append({"startFrame": a, "durationInFrames": dur, "lines": b["lines"][:2],
                        "tab": (b.get("tab") or "BREAKING NEWS")[:22]})
    place = str(opts.get("location") or "").strip() or place_chip(((brief or {}).get("places") or [""])[0])
    loc = None
    if place and opts.get("location_tag", True) is not False:
        hook_end = max((int(s["startFrame"]) + int(s["durationInFrames"]) for s in doc.get("scenes") or [] if s.get("openClip")),
                       default=0)
        loc = {"startFrame": hook_end + int(LOC_FROM * fps), "durationInFrames": int((LOC_TO - LOC_FROM) * fps),
               "place": place_chip(place) or place[:32], "date": str(opts.get("date") or "").strip()[:20]
               or date_chip(day)}
    subs = []
    if opts.get("subscribe", True) is not False:
        t = SUB_FIRST
        while (t + SUB_HOLD) * fps < total - fps * 5:
            subs.append({"startFrame": int(t * fps), "durationInFrames": int(SUB_HOLD * fps)})
            t += SUB_EVERY
    wm = ((kit or {}).get("watermark") or {}) if isinstance((kit or {}).get("watermark"), dict) else {}
    logo_url = str(opts.get("logo_url") or wm.get("url") or "")
    name = str(opts.get("channel_name") or inp.get("channel_watermark") or inp.get("channel_title") or
               (kit or {}).get("name") or "").strip()
    if isinstance(inp.get("channel_watermark"), dict):
        name = str(opts.get("channel_name") or inp["channel_watermark"].get("text") or "").strip()
    return {"version": 1, "colors": colors(inp, kit), "logo": {"url": logo_url, "text": name[:24]},
            "bug": {"opacity": 0.9}, "lowerThirds": lts, "location": loc, "subscribe": subs,
            # The owner (2026-11-03): no source names on screen; the sources go in the description (report creditsText).
            "credits": opts.get("credits") is True,
            "clipSound": {"mode": clip_sound_mode(opts), "underVoiceDb": UNDER_VOICE_DB, "duckDb": UNDER_DUCK_DB},
            "sideLogo": opts.get("side_logo", True) is not False}


def music_level(doc: dict) -> Optional[dict]:
    """The user's own track ~21 dB under the voice, 3 dB lower while a word is spoken (a flat bed)."""
    from . import timeline
    bgm = doc.get("bgm")
    if not isinstance(bgm, dict) or not bgm.get("url"):
        return None
    voice = float(((doc.get("meta") or {}).get("voiceLufs")) or -16.0)
    track = timeline.track_lufs_of(bgm)
    track = float(track) if isinstance(track, (int, float)) else -14.0
    level = round(max(0.0, min(1.0, 10 ** ((voice - MUSIC_UNDER_VOICE_DB - track) / 20.0))), 4)
    music = timeline.music_flat(doc.get("music"), bgm, int(doc.get("fps") or 30),
                                int(doc.get("durationInFrames") or 1), voice, level)
    music["duck"] = round(10 ** (-MUSIC_SPEECH_DUCK_DB / 20.0), 3)
    doc["music"] = music
    bgm["volume"] = level
    return {"level": level, "duck": music["duck"], "voiceLufs": voice, "trackLufs": track}


def bgm_options(opts: Optional[dict]) -> dict:
    """doc.stormDesk.bgm: {"lufs", "onlyUnderVoice"}. storm_desk.bgm_lufs is held between -50 and -20."""
    opts = opts or {}
    try:
        lufs = max(-50.0, min(-20.0, float(opts.get("bgm_lufs"))))
    except (TypeError, ValueError):
        lufs = BGM_LUFS
    return {"lufs": lufs, "onlyUnderVoice": opts.get("bgm_only_under_voice", BGM_ONLY_UNDER_VOICE) is not False}


def music_wanted(opts: Optional[dict]) -> bool:
    """storm_desk.music: true plays the job's tracks; anything else (the default since 2026-11-10) is no music."""
    opts = opts or {}
    m = opts.get("music", MUSIC_DEFAULT)
    return m is True or str(m).strip().lower() in ("1", "true", "on", "yes")


def set_amb_beds(doc: dict, opts: Optional[dict]) -> int:
    """storm_desk.amb_bed (a bed's name or link) under every pause clip whose own sound is not nature (and is no talking clip);
    storm_desk.amb_beds {"<pause second>": bed} for one pause (the kit's picks "break_amb"). Returns how many got one."""
    opts = opts or {}
    default = opts.get("amb_bed")
    per = opts.get("amb_beds") if isinstance(opts.get("amb_beds"), dict) else {}
    fps = int(doc.get("fps") or 30)
    n = 0
    for s in doc.get("scenes") or []:
        if not s.get("natSound") or s.get("talk"):
            continue
        t0 = int(s["startFrame"]) / float(fps)
        bed = next((v for k, v in per.items() if _num(k) is not None and abs(float(_num(k)) - t0) <= 1.5), None)
        kind = str(((s.get("media") or {}).get("clipAudio") or {}).get("kind") or "")
        if bed is None and default and kind not in ("nature", ""):
            bed = default
        if bed:
            s.setdefault("stormDesk", {})["ambBed"] = bed
            n += 1
    return n


def _num(x: Any) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def music_plan(tracks: Any, total: float) -> List[dict]:
    """The owner's tracks in turn over the video (the kit's picks "music": inv1, sus1, crime, crossfaded): links or
    {"url", "at", "offset"}; a track with no time gets its even share of the video."""
    rows = [{"url": x} if isinstance(x, str) else dict(x) for x in (tracks or []) if isinstance(x, (str, dict))]
    rows = [r for r in rows if str(r.get("url") or "").startswith(("http://", "https://", "/"))][:6]
    for k, r in enumerate(rows):
        r["at"] = round(float(r["at"]) if isinstance(r.get("at"), (int, float)) else total * k / len(rows), 2)
        r["offset"] = float(r.get("offset") or 0.0)
    return sorted(rows, key=lambda r: r["at"])


def reuse_gate(doc: dict, led: Any = None) -> dict:
    """The gate before the render (tools/reusecheck.py): what still reuses a moment. {"earlier": [...], "same": [...]}"""
    from . import stormledger
    g = stormledger.gate(doc, led or stormledger.Ledger([]), moment)
    return {"earlier": g["earlier"][:60], "same": g["same"][:60]}


def contact_sheet(doc: dict, thumbs: Dict[int, Any], out: str, cols: int = 8) -> str:
    """One frame of every shot on a sheet (index, time, credit; red = an issue), for the owner's check."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return ""
    fps = int(doc.get("fps") or 30)
    sc = doc["scenes"]
    if not sc:
        return ""
    tw, th, lab = 240, 135, 34
    rows = math.ceil(len(sc) / cols)
    sheet = Image.new("RGB", (cols * tw, rows * (th + lab)), (16, 18, 22))
    d = ImageDraw.Draw(sheet)
    for i, s in enumerate(sc):
        x, y = (i % cols) * tw, (i // cols) * (th + lab)
        fr = thumbs.get(i)
        if fr is not None:
            sheet.paste(Image.fromarray(fr).resize((tw - 4, th - 4)), (x + 2, y + 2))
        bad = bool(s.get("reviewRequired")) or bool(s.get("stormDeskIssue"))
        t = int(s["startFrame"]) / fps
        tag = "PAUSE " if s.get("natSound") else ""
        d.text((x + 4, y + th + 2), f"#{i} {int(t // 60)}:{t % 60:04.1f} {tag}{int(s['durationInFrames']) / fps:.1f}s",
               fill=(255, 90, 80) if bad else (230, 230, 230))
        d.text((x + 4, y + th + 17), str((s.get("credit") or {}).get("text") or "")[:34], fill=(160, 170, 185))
    sheet.save(out, quality=82)
    return out


def mark_channels(doc: dict, led: Any = None, earlier_channels: Optional[set] = None, place: Optional[Any] = None,
                  station_cap: int = 0, strict: bool = False) -> List[dict]:
    """
    The owner's creator rule (tools/channels.py + tools/reusecheck.py) and the ledger, on the shots as they stand: a vlog or
    personality channel never; a person's own channel at most 2 shots a video, never in a pause or the hook; a moment of an
    earlier video never; a source whose title is about another place never (`place`, place_regex); one station at most
    `station_cap` shots; `strict` (the pieces engine): a banned source, a shot rejected in any video and a station's first 3 s
    never either. Marks scene["_reject"] so replace_stills swaps them. Returns one row per shot marked.
    """
    from . import stormledger, stormlib
    fps = int(doc.get("fps") or 30)
    rows: List[dict] = []
    per: Dict[str, int] = {}
    per_station: Dict[str, int] = {}
    banned = stormlib.bad_sources() if strict else set()
    shown: Dict[str, List[Tuple[float, float]]] = {}
    for i, s in enumerate(doc.get("scenes") or []):
        if (s.get("media") or {}).get("type") != "video" or is_ai(s) or not video_id(s).startswith("yt:"):
            continue
        ch = str(_sm(s).get("channel") or "")
        why = ""
        if video_id(s)[3:] in banned:
            why = "a banned source"
        elif stormledger.is_personality(ch):
            why = f"a personality channel ({ch[:40]})"
        elif source_kind(ch) == "creator":
            cap = stormledger.CREATOR_SHOTS_REPEAT if ch in (earlier_channels or ()) else stormledger.CREATOR_SHOTS
            per[ch] = per.get(ch, 0) + 1
            if per[ch] > cap:
                why = f"creator {ch[:40]}: over {cap} shots"
        elif station_cap and is_station(ch):
            per_station[ch] = per_station.get(ch, 0) + 1
            if per_station[ch] > station_cap and not s.get("natSound"):
                why = f"station {ch[:40]}: over {station_cap} shots"
        mo = moment(s, fps)
        if not why and not place_ok(source_title(s), place):
            why = "its title is about another place"
        if strict and not why and mo and is_station(ch) and mo[1] < STATION_SKIP_HEAD and not s.get("natSound"):
            why = "a station's first seconds (a promo, a logo)"
        if strict and not why and mo and not s.get("natSound") and stormlib.is_bad(mo[0], mo[1]):
            why = "a shot rejected in an earlier video"
        if not why and led is not None and mo and led.used(mo[0], mo[1], mo[2]):
            why = "a moment an earlier video used"
        if mo:
            if not why and any(min(mo[2], q) - max(mo[1], p) > stormledger.OVERLAP for p, q in shown.get(mo[0], [])):
                why = "the same frames as an earlier shot"
            shown.setdefault(mo[0], []).append((mo[1], mo[2]))
        if why and not s.get("natSound"):
            s["_reject"] = why
            rows.append({"shot": i, "why": why})
    return rows


def drop_plain_pauses(doc: dict, rows: List[dict], most: int = NATURAL_PAUSES_MAX) -> int:
    """No pause unless something worth stopping for happens (the owner, 2026-11-05: natural-sound pauses of plain water felt
    empty). Someone talking always stays; of the rest only the `most` best-scored do. A dropped pause's slot then closes
    (apply_fits). Returns how many went."""
    plain = []
    for r in rows:
        if not r.get("clip") or r.get("open"):
            continue
        s = next((x for x in doc["scenes"] if x.get("natSound") and os.path.basename(_local(x) or str((x.get("media") or {}).get("url") or "")) == os.path.basename(str(r["clip"]))), None)
        if s is not None and not s.get("talk"):
            plain.append((float(r.get("score") or 0.0), id(s), s, r))
    plain.sort(key=lambda x: (-x[0], x[1]))
    for _score, _i, s, r in plain[most:]:
        doc["scenes"].remove(s)
        r["clip"] = None
        r["why"] = "plain natural sound: dropped (at most %d a video)" % most
    return max(0, len(plain) - most)


def is_talking_shot(fr: list, kind: str, faces: Optional[Callable] = None) -> bool:
    """Someone talking on camera (the owner: under the narration it reads as a muted clip): speech on the clip's sound and a
    face of real size in its frames. A reporter's voice over pictures of the flood has no such face and stays."""
    if kind != "speech" or not fr:
        return False
    if faces is None:
        from . import reframe
        if not reframe.faces_available():
            return False
        faces = reframe.find_faces
    hits = 0
    for f in (fr[0], fr[len(fr) // 2], fr[-1]):
        h, w = f.shape[:2]
        if any(_face_share(b, w, h) >= TALKING_FACE_SHARE for b in faces(f) or []):
            hits += 1
    return hits >= 2


def _face_share(b: Any, w: int, h: int) -> float:
    """A face box's share of the frame: reframe's boxes (x, y, w, h first), plain or as an object."""
    try:
        if hasattr(b, "w"):
            bw, bh = float(b.w), float(b.h)
        elif isinstance(b, dict):
            bw, bh = float(b.get("w") or b.get("width")), float(b.get("h") or b.get("height"))
        else:
            bw, bh = float(b[2]), float(b[3])
    except (TypeError, ValueError, IndexError):
        return 0.0
    if bw <= 1.0 and bh <= 1.0:                 # reframe.find_faces gives shares of the frame already
        return bw * bh
    return (bw * bh) / float(max(1, w * h))


def apply_fits(doc: dict, pauses: List[dict], inp: dict, renarrate: Optional[Callable[[List[dict]], str]] = None) -> int:
    """
    A pause's length follows its clip (the owner: "the break length follows the clip"): a talking clip's sentences set it. The
    pause scene changes length, everything after it moves, and the narration is padded again to match. Without a new narration
    file (no `renarrate`, or it failed) nothing moves: the clip plays its slot's length and says so. Returns the pauses changed.
    """
    fps = int(doc.get("fps") or 30)
    plan = inp.get("_storm_pauses") or []
    scenes = sorted(doc.get("scenes") or [], key=lambda s: int(s["startFrame"]))
    want: Dict[int, int] = {}
    gone: List[int] = []
    for k, p in enumerate(pauses):
        s = next((x for x in scenes if x.get("natSound") and int(x["startFrame"]) <= int(round(p["t0"] * fps))
                  < int(x["startFrame"]) + int(x["durationInFrames"])), None)
        if s is None:
            # No clip could fill it: the slot closes instead of the voice stopping over silent shots (the proof's hook).
            gone.append(k)
            want[k] = int(round(float(p["t0"]) * fps)) - int(round(float(p["t1"]) * fps))
            continue
        if not s.get("_fitSecs"):
            continue
        frames_now = int(round(float(p["t1"]) * fps)) - int(round(float(p["t0"]) * fps))
        target = int(round(float(s["_fitSecs"]) * fps))
        if target != frames_now:
            want[k] = target - frames_now
    for s in scenes:
        s.pop("_fitSecs", None)
    if not want:
        return 0
    if renarrate is None or len(plan) != len(pauses):
        return 0
    order = sorted(range(len(plan)), key=lambda i: float(plan[i]["at"]))
    new_plan = [dict(plan[i]) for i in order]
    for k, d in want.items():
        new_plan[k]["secs"] = round(float(new_plan[k]["secs"]) + d / float(fps), 4)
    new_plan = [p for k, p in enumerate(new_plan) if k not in gone]
    url = renarrate(new_plan)
    if not url:
        return 0
    inp["_storm_pauses"] = new_plan
    inp["_storm_narration"] = url
    if isinstance(doc.get("audio"), dict):
        doc["audio"]["url"] = url
    # From the last pause back, so each scene moves by what comes before it only once.
    for k in sorted(want, reverse=True):
        d, p = want[k], pauses[k]
        p0 = int(round(float(p["t0"]) * fps))
        secs = d / float(fps)
        if k in gone:
            p1 = int(round(float(p["t1"]) * fps))
            keep = []
            for s in doc["scenes"]:
                a, b = int(s["startFrame"]), int(s["startFrame"]) + int(s["durationInFrames"])
                if a >= p0 and b <= p1:
                    continue                    # a shot inside the slot goes
                if a < p0 < b <= p1:
                    s["durationInFrames"] = p0 - a
                elif p0 <= a < p1 < b:
                    _trim_head(s, p1 - a, fps)
                    s["startFrame"] = p1
                keep.append(s)
            doc["scenes"][:] = keep
            scenes[:] = sorted(keep, key=lambda s: int(s["startFrame"]))
            cut = p1
        else:
            scene = next(x for x in scenes if x.get("natSound") and int(x["startFrame"]) <= p0 < int(x["startFrame"]) + int(x["durationInFrames"]))
            cut = int(scene["startFrame"]) + int(scene["durationInFrames"])
            scene["durationInFrames"] = int(scene["durationInFrames"]) + d
        for s in scenes:
            if int(s["startFrame"]) >= cut:
                s["startFrame"] = int(s["startFrame"]) + d
                for w in s.get("words") or []:
                    w["start"] = float(w.get("start", 0.0)) + secs
                    w["end"] = float(w.get("end", 0.0)) + secs
        p["t1"] = round(float(p["t1"]) + secs, 3)
        for q in pauses[k + 1:]:
            q["t0"], q["t1"] = round(float(q["t0"]) + secs, 3), round(float(q["t1"]) + secs, 3)
        doc["durationInFrames"] = int(doc.get("durationInFrames") or 0) + d
    for k in sorted(gone, reverse=True):
        del pauses[k]
    return len(want)


_CAPTION_ASK = ("You write one small white caption for each short clip in a news video: what the clip shows, 3 to 8 plain words, "
                "sentence case, no full stop. Use only the words given (what the narrator just said, the clip's title, what is "
                "said in it). Never add a number, a name or a place that is not given. Answer JSON: "
                "{\"captions\":[{\"i\":<clip>,\"text\":\"...\"}]}")


def write_captions(doc: dict, ask: Optional[Callable] = None) -> int:
    """scene.caption for the pause and hook clips (the kit's CAPTIONS). Checked: no digit that was not given. No model: none."""
    rows = []
    clips = [s for s in doc.get("scenes") or [] if s.get("natSound") and not s.get("openClip")]
    if not ask or not clips:
        return 0
    for i, s in enumerate(clips):
        before = [x for x in doc["scenes"] if int(x["startFrame"]) < int(s["startFrame"])]
        said = " ".join(str(x.get("text") or "") for x in before[-2:])[-240:]
        rows.append({"i": i, "said": said, "title": source_title(s)[:120], "spoken": str(s.get("_talkText") or "")[:200]})
    raw = ask(_CAPTION_ASK, {"clips": rows})
    got = raw if isinstance(raw, dict) else json.loads(raw or "{}")
    n = 0
    for x in got.get("captions") or []:
        try:
            i, text = int(x["i"]), re.sub(r"\s+", " ", str(x["text"])).strip().rstrip(".")
            src = " ".join(str(rows[i][k]) for k in ("said", "title", "spoken"))
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        if not text or len(text) > 60 or any(d not in src for d in re.findall(r"\d+", text)):
            continue
        clips[i]["caption"] = text
        n += 1
    for s in clips:
        s.pop("_talkText", None)
    return n


def credits_text(doc: dict) -> str:
    """The description's credits: every source, once (no source names on screen)."""
    seen, out = set(), []
    for s in doc.get("scenes") or []:
        if (s.get("media") or {}).get("type") not in ("video", "image") or is_ai(s):
            continue
        name = credit_name(s)
        url = str(_sm(s).get("sourceUrl") or "").split("&t=")[0]
        if name and (name, url) not in seen:
            seen.add((name, url))
            out.append(f"{name}: {url}" if url else name)
    return "\n".join(out)


def set_modes(doc: dict, marks_by_path: Dict[str, List[List[float]]]) -> None:
    """How the pieces engine frames each shot: a station's crop (its lower third, corner bug and ticker gone) and the small
    marks painted out (fitted tight, from the pixels around them). Nothing is baked into the clip file."""
    for s in doc.get("scenes") or []:
        if (s.get("media") or {}).get("type") != "video" or is_ai(s):
            continue
        sd = s.setdefault("stormDesk", {})
        ch = str(_sm(s).get("channel") or "")
        want = station_crop(ch)
        have = str(sd.get("mode") or "")
        if want and (not have or _crop_k(want) < _crop_k(have)):
            sd["mode"] = want
        from . import stormlib
        vid = video_id(s)[3:] if video_id(s).startswith("yt:") else ""
        tuned = stormlib.station_modes()
        if vid in tuned:                        # tuned by eye on the laptop (credits/station_modes.json); null = the full frame
            if tuned[vid]:
                sd["mode"] = tuned[vid]
            else:
                sd.pop("mode", None)
        path = _local(s) or str((s.get("media") or {}).get("url") or "")
        if not sd.get("mode") and vid not in tuned and stormlib.AUTO_FRAME and path and os.path.isfile(path) \
                and not s.get("natSound") and not s.get("openClip"):
            src_path = _source_file(vid) or path            # the source's shape, not the cut's (same pixels)
            from . import shotcheck
            framed = shotcheck.auto_frame(src_path)
            if framed:
                sd["mode"] = framed
        boxes = marks_by_path.get(path) or []
        if boxes:
            sd["delogo"] = _visible_marks(boxes, str(sd.get("mode") or ""))


def _source_file(vid: str) -> str:
    """The whole source on this disk (library or bank), "" when only the cut is here."""
    from . import srcbank
    for src in srcbank._STATE.get("sources") or []:
        if src.id == vid and src.path and os.path.isfile(src.path):
            return src.path
    return ""


def station_crop(channel: str) -> str:
    """A station's crop, or "" for anyone else. Most stations: 0.76 from the top (lower third + ticker + corner bug gone);
    KUTV's clock bug sits further in (the owner's Lake Mead videos: 0.68)."""
    if not is_station(channel):
        return ""
    for name, mode in STATION_CROPS:
        if name in str(channel).upper():
            return mode
    return "news0.76@0.0"


STATION_CROPS = (("KUTV", "news0.68@0.02"),)


def _crop_k(mode: str) -> float:
    m = re.match(r"news([\d.]+)", str(mode))
    return float(m.group(1)) if m else 1.0


def _crop_top(mode: str) -> float:
    m = re.match(r"news[\d.]+@([\d.]+)", str(mode))
    return float(m.group(1)) if m else 0.03


def crop_frames(fr: list, k: float, top: float = 0.0) -> list:
    """Frames as a newsK@TOP crop shows them: for the text check, without touching the clip."""
    out = []
    for f in fr:
        h, w = f.shape[:2]
        y0, x0 = int(h * top), int(w * (1 - k) / 2)
        out.append(f[y0:y0 + int(h * k), x0:x0 + int(w * k)])
    return out


def _visible_marks(boxes: List[List[float]], mode: str) -> List[List[float]]:
    """Marks a crop already removes need no paint-out."""
    if not mode.startswith("news"):
        return boxes
    k, top = _crop_k(mode), _crop_top(mode)
    x0, x1, y0, y1 = (1 - k) / 2, (1 + k) / 2, top, top + k
    return [b for b in boxes if b[0] < x1 and b[0] + b[2] > x0 and b[1] < y1 and b[1] + b[3] > y0]


def set_hook_tail(doc: dict) -> bool:
    """The last hook clip plays on for 0.6 s under the first narrated shot, so the hook dissolves into the story (the kit's
    tools/hooktail.py). False when that clip has no 0.6 s left."""
    fps = int(doc.get("fps") or 30)
    sc = sorted(doc.get("scenes") or [], key=lambda s: int(s["startFrame"]))
    hooks = [s for s in sc if s.get("openClip")]
    if not hooks:
        return False
    last = hooks[-1]
    after = next((s for s in sc if int(s["startFrame"]) >= int(last["startFrame"]) + int(last["durationInFrames"])), None)
    m = last.get("media") or {}
    if after is None or (after.get("media") or {}).get("type") != "video":
        return False
    ss = float(m.get("trimStart") or 0.0) + int(last["durationInFrames"]) / float(fps)
    if float(m.get("clipSeconds") or 0.0) - ss < 0.6:
        return False
    after["hookTail"] = {"src": str(m.get("url") or ""), "ss": round(ss, 3), "mode": str((last.get("stormDesk") or {}).get("mode") or "full"),
                         "delogo": (last.get("stormDesk") or {}).get("delogo") or []}
    return True


def finish(doc: dict, inp: dict, brief: Optional[dict] = None, work: str = "", fetch: Optional[Callable] = None,
           ask: Optional[Callable] = None, frame_vertical: Optional[Callable[[str], bool]] = None,
           upload: Optional[Callable[[str, str], str]] = None, check: Optional[Callable[[str], str]] = None,
           listen: Optional[Callable[[str], Sequence]] = None,
           renarrate: Optional[Callable[[List[dict]], str]] = None) -> dict:
    """
    The storm desk pass over a planned document (handler.do_plan, before publishing). Returns the report
    (doc.meta.stormDesk). Network only through `fetch` (the pause clips) and `ask` (the headline model);
    never raises: a step that fails is reported and the rest still runs.
    """
    from . import brandkit
    rep: Dict[str, Any] = {"version": 1, "errors": []}
    fps = int(doc.get("fps") or 30)
    opts = options(inp)
    kit = brandkit.from_input(inp)
    work = work or os.path.dirname(next((_local(s) for s in doc.get("scenes") or [] if _local(s)), "")) or "."

    def step(name: str, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - the report says, the video goes on
            rep["errors"].append(f"{name}: {type(e).__name__}: {str(e)[:160]}")
            print(f"[stormdesk] {name} failed: {type(e).__name__}: {str(e)[:200]}", flush=True)
            return None

    # Nothing of the planner's on top: the reference draws only its own four graphics.
    rep["graphicsDropped"] = len(doc.get("overlays") or [])
    doc["overlays"] = []
    doc["sfx"] = []
    doc["ambience"] = None
    doc.setdefault("captions", {})["enabled"] = bool(inp.get("captions") is True)
    if isinstance(doc.get("brand"), dict):
        doc["brand"].pop("watermark", None)            # the bug below is the logo
    for s in doc.get("scenes") or []:
        s["transition"] = "none"                        # hard cuts (measured 97-100%)
        s["effect"] = "none"
        if (s.get("media") or {}).get("type") == "video":
            s["motion"] = "none"
        s.pop("transitionGain", None)

    pauses = out_pauses(inp.get("_storm_pauses") or [])
    # Who uploaded each shot, before anything is picked from them (the pauses take their clips from these sources).
    rep["channelsResolvedFirst"] = step("channels", lambda: resolve_channels(doc)) or 0
    from . import stormledger, stormpieces
    global JOB_LEDGER
    engine = stormpieces.engine_of(None, inp)
    JOB_LEDGER = step("ledger", lambda: stormledger.load(inp)) or stormledger.Ledger([])
    rep["ledgerMoments"] = len(JOB_LEDGER.moments)
    # The laptop's rules on the pieces engine (2026-11-07): a timeline on Remotion stays as it was.
    pieces_on = engine == "pieces"
    from . import stormgate
    global JOB_PLACE, JOB_STRICT
    JOB_PLACE = place_regex(inp, brief) if pieces_on else None
    JOB_STRICT = pieces_on
    cap_station = station_shots(opts) if pieces_on else 0

    def clear_marked() -> int:
        """Shots a rule refused and no spare could replace: nothing to show until the ladder fills them (it may keep them)."""
        n = 0
        for s in doc["scenes"]:
            if s.get("_reject") and not s.get("natSound"):
                stormgate.clear_scene(s, str(s["_reject"]))
                n += 1
        return n
    rep["pauses"] = step("pauses", lambda: make_pauses(doc, pauses, work, fetch, frame_vertical, check, listen=listen)) or []
    rep["naturalPausesDropped"] = step("empty pauses", lambda: drop_plain_pauses(doc, rep["pauses"])) or 0
    rep["pauseFits"] = step("pause lengths", lambda: apply_fits(doc, pauses, inp, renarrate)) or 0
    rep["cleanCheck"] = step("clean check", lambda: clean_check(doc, virtual=engine == "pieces")) or []
    rep["channelRule"] = step("channel rule", lambda: mark_channels(doc, JOB_LEDGER, place=JOB_PLACE, station_cap=cap_station, strict=pieces_on)) or []
    st = step("stills", lambda: replace_stills(doc, check=check, hold=not pieces_on)) or {}
    again = step("channel rule 2", lambda: mark_channels(doc, JOB_LEDGER, place=JOB_PLACE, station_cap=cap_station, strict=pieces_on)) or []
    if again:                                   # a spare from a creator over the cap, or a moment of an earlier video
        rep["channelRule"] += again
        st2 = step("stills 2", lambda: replace_stills(doc, check=check, hold=not pieces_on)) or {}
        for k in ("replaced", "moved", "held"):
            st[k] = int(st.get(k) or 0) + int(st2.get(k) or 0)
        st["left"] = st2.get("left", st.get("left"))
    if pieces_on and step("clear", clear_marked):
        rep["ladderRules"] = step("ladder", lambda: stormgate.ensure_media(doc, inp, work, allow_hold=False))
    for s in doc["scenes"]:
        s.pop("_reject", None)
        s.pop("_soft", None)
    rep["stillsReplaced"], rep["stillsMoved"] = st.get("replaced", 0), st.get("moved", 0)
    rep["stillsLeft"] = [{"shot": i, "why": w} for i, w in (st.get("left") or [])][:40]
    rep["heldOver"], rep["channelsResolved"] = st.get("held", 0), st.get("resolved", 0)
    rep["rejects"] = ([{"shot": r["shot"], "why": r["why"], "action": r["action"]} for r in rep["cleanCheck"]]
                      + [{"shot": x["shot"], "why": x["why"], "action": "left (nothing better found)"}
                         for x in rep["stillsLeft"]])[:200]
    rep["shotsCut"] = step("shot cap", lambda: cap_shots(doc)) or 0
    moved = step("ai opening", lambda: keep_ai_out_of_opening(doc)) or (0, 0)
    rep["aiMovedOutOfOpening"], rep["aiInOpening"] = moved

    # Credits, ARCHIVE labels, AI labels.
    text = " ".join(str(w.get("text") or "") for s in doc["scenes"][:40] for w in s.get("words") or [])
    day = None
    if inp.get("_event_day"):
        try:
            day = datetime.date.fromisoformat(str(inp["_event_day"])[:10])
        except ValueError:
            day = None
    day = day or event_date(text, opts)
    rep["eventDate"] = day.isoformat() if day else None

    def credits_pass() -> int:
        n_arch = 0
        for s in doc["scenes"]:
            m = s.get("media") or {}
            if m.get("type") not in ("video", "image"):
                s.pop("credit", None)
                continue
            if is_ai(s):
                s["credit"] = {"text": "AI ILLUSTRATION", "ai": True}
                continue
            arch = archive(s, day, brief)
            if not arch and is_photo(s):
                # A picture whose title names an earlier year than the event's: an older storm's (the Las Vegas run's
                # "Flood devastation in 1999").
                yr = (brief or {}).get("year")
                ref = day.year if day else (yr if isinstance(yr, int) and not isinstance(yr, bool) else None)
                arch = bool(ref) and any(y < ref for y in photo_years(s))
            n_arch += int(arch)
            label = "VIDEO" if m.get("type") == "video" else "PHOTO"
            s["credit"] = {"text": f"{label}: {credit_name(s)}", **({"archive": True} if arch else {})}
        return n_arch
    rep["archiveShots"] = credits_pass()

    fixed = step("neighbours", lambda: fix_neighbours(doc)) or (0, 0)
    rep["neighboursFixed"], rep["sameSourceInARow"] = fixed

    # Frames of every shot: marks, mirror, look-alikes, the contact sheet.
    vectors: Dict[int, Any] = {}
    thumbs: Dict[int, Any] = {}
    blur_on = opts.get("blur_marks", True) is not False
    mirror = str(opts.get("mirror") or "off").lower() == "auto"
    flips: Dict[str, bool] = {}
    order = []
    for s in doc["scenes"]:
        v = video_id(s)
        if v and v not in order and (s.get("media") or {}).get("type") == "video" and not is_ai(s):
            order.append(v)
    marked, flipped, lock = [0], [0], threading.Lock()
    clip_ok = False
    try:
        from . import localvision
        clip_ok = opts.get("lookalike", True) is not False and localvision.available()
    except Exception:  # noqa: BLE001
        clip_ok = False
    baked: Dict[str, bool] = {}
    marks_by_path: Dict[str, List[List[float]]] = {}

    def look(i: int) -> None:
        s = doc["scenes"][i]
        path = _local(s)
        if not path or (s.get("media") or {}).get("type") != "video":
            return
        m = s["media"]
        fr = frames(path, float(m.get("trimStart") or 0.0), int(s["durationInFrames"]) / fps, n=6)
        if not fr:
            return
        thumbs[i] = fr[1 if len(fr) > 1 else 0]
        # A vertical clip on its blurred fill: where the side-panel logo goes (StormDesk.tsx SideLogos).
        try:
            from . import config as _cfg, upscale
            framed = os.path.abspath(path) in getattr(upscale, "FRAMED", set())
            band = float(getattr(_cfg, "VERTICAL_BAND_ASPECT", 1.051) or 1.051)
        except Exception:  # noqa: BLE001
            framed, band = False, 1.051
        panel = blurred_sides(fr)
        if framed and not panel:
            panel = round(min(0.85, int(doc.get("height") or 1080) * band / float(int(doc.get("width") or 1920))), 3)
        if panel:
            s["blurSides"] = {"panel": panel}
        if not s.get("natSound"):
            # What its own sound is (src/clipaudio.py): only natural sound plays under the narration.
            try:
                from . import clipaudio
                m["clipAudio"] = clipaudio.classify(path, float(m.get("trimStart") or 0.0),
                                                    int(s["durationInFrames"]) / fps, title=source_title(s))
                m["clipAudio"].pop("parts", None)
            except Exception:  # noqa: BLE001 - unknown: silent under the voice
                m["clipAudio"] = {"kind": "unknown"}
            try:
                if is_talking_shot(fr, str((m.get("clipAudio") or {}).get("kind") or "")):
                    s["_talking"] = True
            except Exception:  # noqa: BLE001 - the frame-sheet review still sees it
                pass
        if clip_ok:
            try:
                import numpy as np
                from PIL import Image
                from . import localvision
                emb = localvision.embed_images([Image.fromarray(fr[k]) for k in (0, len(fr) // 2, len(fr) - 1)])
                v = emb.mean(axis=0)
                vectors[i] = v / max(1e-8, float(np.linalg.norm(v)))
            except Exception:  # noqa: BLE001 - no look-alike check for this shot
                pass
        with lock:
            if path in baked:
                return
            baked[path] = True
        boxes = static_marks(fr) if blur_on else []
        if engine == "pieces":
            if boxes:
                with lock:
                    marks_by_path[path] = boxes
                    marked[0] += 1
            return
        sm = _sm(s)
        flip = (mirror and not boxes and flips.get(video_id(s), False)
                and str(sm.get("subjectType") or "").lower() not in _LANDMARK_TYPES)
        if (boxes or flip) and bake(path, boxes, flip):
            with lock:
                marked[0] += int(bool(boxes))
                flipped[0] += int(flip)
            s.setdefault("stormDesk", {}).update({"blurred": boxes, "flipped": bool(flip)})
    for k, v in enumerate(order):
        flips[v] = k % 2 == 1                           # every other source, when the job asks for it
    if any(_local(s) for s in doc["scenes"]):
        with ThreadPoolExecutor(max(1, min(4, (os.cpu_count() or 2)))) as ex:
            list(ex.map(lambda i: step(f"look {i}", lambda: look(i)), range(len(doc["scenes"]))))
    talking = [s for s in doc["scenes"] if s.pop("_talking", None)]
    rep["talkingShotsSwapped"] = len(talking)
    if talking:
        for s in talking:
            s["_reject"] = "someone talking on camera under the narration"
        step("talking shots", lambda: replace_stills(doc, check=check, hold=not pieces_on))
        if pieces_on and step("clear", clear_marked):
            rep["ladderTalking"] = step("ladder", lambda: stormgate.ensure_media(doc, inp, work, allow_hold=False))
        for s in doc["scenes"]:
            s.pop("_reject", None)
            s.pop("_soft", None)
    rep["blurredClips"], rep["flippedClips"] = marked[0], flipped[0]
    if engine == "pieces":
        step("modes", lambda: set_modes(doc, marks_by_path))
        # The hook's pictures (a QR code and a CBS eye got through on the laptop), then the shot gates' loop, the rules once
        # more on whatever the loop placed, and last the ladder with its last rung: a shot held only when nothing else exists.
        if opts.get("gates", True) is not False:

            def refill() -> dict:
                got = stormgate.ensure_media(doc, inp, work, allow_hold=False)
                set_modes(doc, marks_by_path)
                return got
            rep["hookPictures"] = step("hook pictures", lambda: stormgate.hook_pictures(doc)) or []
            rep["shotGates"] = step("shot gates", lambda: stormgate.autofix(doc, inp, work, fill=refill)) or {}
            again = step("channel rule 3", lambda: mark_channels(doc, JOB_LEDGER, place=JOB_PLACE, station_cap=cap_station, strict=pieces_on)) or []
            if again:
                rep["channelRule"] += again
                step("clear", clear_marked)
                rep["ladderRules2"] = step("ladder", refill)
                stormgate.restore_flagged(doc)
                for s in doc["scenes"]:
                    s.pop("_reject", None)
        rep["emptyLadder"] = step("empty shots", lambda: stormgate.ensure_media(doc, inp, work)) or {}
        step("modes", lambda: set_modes(doc, marks_by_path))
        rep["archiveShots"] = step("credits", credits_pass) or 0
        moved2 = step("ai opening", lambda: keep_ai_out_of_opening(doc)) or (0, 0)
        rep["aiMovedOutOfOpening"], rep["aiInOpening"] = rep.get("aiMovedOutOfOpening", 0) + moved2[0], moved2[1]
        fixed2 = step("neighbours", lambda: fix_neighbours(doc)) or (0, 0)
        rep["neighboursFixed"], rep["sameSourceInARow"] = rep.get("neighboursFixed", 0) + fixed2[0], fixed2[1]
    pairs = lookalikes(vectors) if vectors else []
    same = []
    for i, j, c in pairs:
        a, b = doc["scenes"][i], doc["scenes"][j]
        if b.get("splitFrom") in (a.get("id"), a.get("splitFrom")) or (
                video_id(a) == video_id(b) and repeats({"fps": fps, "scenes": [a, b]})):
            continue                    # one shot cut in two by the cap, or a repeat (reported as one)
        same.append({"shot": j, "like": i, "cos": c})
        doc["scenes"][j]["reviewRequired"] = True
        doc["scenes"][j]["reviewReason"] = f"looks like shot #{i} (CLIP {c:.2f}): swap one of them"
        doc["scenes"][j]["stormDeskIssue"] = "lookalike"
    mode = clip_sound_mode(opts)
    kinds: Dict[str, int] = {}
    for s in doc["scenes"]:
        if (s.get("media") or {}).get("type") == "video" and not s.get("natSound"):
            k = str(((s["media"].get("clipAudio") or {}).get("kind")) or "unknown")
            kinds[k] = kinds.get(k, 0) + 1
    try:
        from . import clipaudio
        under = sum(1 for s in doc["scenes"] if clipaudio.plays_under_voice(s, mode))
    except Exception:  # noqa: BLE001
        under = 0
    rep["clipSound"] = {"mode": mode, "kinds": kinds, "underVoice": under}
    rep["lookalikeCheck"] = "clip" if clip_ok else "off"
    rep["lookalikes"] = same[:40]

    # Blocks, headlines, the graphics.
    blocks = step("blocks", lambda: blocks_of(doc, pauses)) or []
    own = [str(h).strip() for h in (opts.get("headlines") or []) if str(h).strip()]
    for b, h in zip(blocks, own):
        b["headline"] = h.upper()
    for b in blocks:
        if b["i"] == 0 and not b.get("tab"):
            b["tab"] = str(opts.get("tab") or "BREAKING NEWS").upper()
    title = str(inp.get("title") or "")
    rep["headlinesBy"] = "job" if own and len(own) >= len(blocks) else step(
        "headlines", lambda: write_headlines(blocks, title, ask)) or "rules"
    for b in blocks:
        if not b.get("tab"):
            b["tab"] = _tab_for(b["text"], brief)
        if not b.get("lines"):
            b["lines"] = wrap2(b.get("headline") or rule_headline(b["text"]))
    doc["stormDesk"] = step("graphics", lambda: graphics(doc, inp, blocks, brief, kit, day)) or {}
    rep["blocks"] = [{"start": b["start"], "headline": " / ".join(b.get("lines") or []), "tab": b.get("tab")}
                     for b in blocks]
    rep["music"] = step("music", lambda: music_level(doc))
    rep["captions"] = step("captions", lambda: write_captions(doc, ask)) or 0
    rep["creditsText"] = step("credits", lambda: credits_text(doc)) or ""
    if engine == "pieces":
        from . import stormlooks
        doc["stormDesk"]["engine"] = "pieces"
        doc["stormDesk"]["statStyle"] = stormlooks.stat_options(opts)
        doc["stormDesk"]["bgm"] = bgm_options(opts)
        doc["stormDesk"]["music"] = music_plan(opts.get("bgm_tracks"), int(doc.get("durationInFrames") or 0) / float(fps))
        # The owner (2026-11-10): no background music at all, and none from the clips. Music only when a job asks for it.
        doc["stormDesk"]["noMusic"] = not music_wanted(opts)
        rep["noMusic"] = doc["stormDesk"]["noMusic"]
        rep["ambBeds"] = step("ambience beds", lambda: set_amb_beds(doc, opts)) or 0
        looks = step("looks", lambda: stormlooks.timeline(doc, blocks, pauses, brief, day, work, ask, opts=opts))
        if looks:
            doc["stormDesk"]["looks"] = looks
            rep["looks"] = stormlooks.summary(looks)
        rep["hookDissolve"] = step("hook tail", lambda: set_hook_tail(doc)) or False
    rep["hookClips"] = sum(1 for s in doc["scenes"] if s.get("openClip"))
    rep["reuseGate"] = step("reuse gate", lambda: reuse_gate(doc, JOB_LEDGER)) or {}

    # The checks, as the video stands.
    rep["repeats"] = repeats(doc)
    rep["sources"] = shares(doc)[:30]
    rep["origin"] = original_share(doc)
    rep["emptyShots"] = sum(1 for s in doc["scenes"] if is_empty(s) and not s.get("natSound"))
    if pieces_on:
        # (A text card counts as empty here: this engine has nothing else to draw on it.)
        rep["emptyList"] = stormgate.empty_rows(doc)[:60]
        rep["emptyShots"] = len(rep["emptyList"])
        step("rejected moments", _flush_library)
        rep["library"] = _library_report()
        rep["youtube"] = _youtube_report()
        rep["holdSaved"] = step("hold", lambda: stormledger.hold(inp, stormledger.doc_moments(doc, moment))) or False
    over = [r for r in rep["sources"] if r["share"] > SOURCE_CAP_SHARE + 0.005]
    rep["sourcesOverCap"] = over
    longest = max((int(s["durationInFrames"]) / fps for s in doc["scenes"]
                   if not s.get("natSound") and not s.get("heldOver")
                   and (s.get("media") or {}).get("type") != "animation"), default=0.0)
    rep["heldShots"] = sum(1 for s in doc["scenes"] if s.get("heldOver"))
    rep["longestShot"] = round(longest, 2)
    rep["shots"] = len(doc["scenes"])
    rep["aiShots"] = sum(1 for s in doc["scenes"] if is_ai(s))
    rep["blocklist"] = blocklist(inp)
    sheet = step("contact sheet", lambda: contact_sheet(doc, thumbs, os.path.join(work, "stormdesk_sheet.jpg")))
    if sheet and upload is not None:
        rep["contactSheet"] = step("sheet upload", lambda: upload(sheet, "stormdesk_sheet.jpg")) or ""
    issues = []
    if rep["sameSourceInARow"]:
        issues.append(f"{rep['sameSourceInARow']} pair(s) of shots in a row from one source")
    if rep["repeats"]:
        issues.append(f"{len(rep['repeats'])} repeated moment(s)")
    if over:
        issues.append(f"{len(over)} source(s) over {int(SOURCE_CAP_SHARE * 100)}% of the runtime")
    if same:
        issues.append(f"{len(same)} look-alike shot(s)")
    if rep["aiInOpening"]:
        issues.append(f"{rep['aiInOpening']} AI shot(s) in the first minute")
    if longest > SHOT_MAX + 0.05:
        issues.append(f"longest shot {longest:.1f} s")
    if rep["origin"]["seconds"].get("reupload"):
        issues.append(f"{rep['origin']['seconds']['reupload']:.0f} s from re-upload channels")
    if rep["emptyShots"]:
        issues.append(f"{rep['emptyShots']} empty shot(s)")
    if (rep.get("reuseGate") or {}).get("earlier"):
        issues.append(f"{len(rep['reuseGate']['earlier'])} shot(s) from a moment of an earlier video")
    if (rep.get("reuseGate") or {}).get("same"):
        issues.append(f"{len(rep['reuseGate']['same'])} pair(s) of shots with the same frames")
    missing = [p for p in rep["pauses"] if not p.get("clip")]
    if missing:
        issues.append(f"{len(missing)} pause(s) without their own clip")
    rep["issues"] = issues
    rep["summary"] = ("Storm desk: " + (", ".join(issues) if issues else "every rule holds") +
                      f" ({rep['shots']} shots, {len(rep['pauses'])} pauses, {len(blocks)} headlines)")
    for p in rep["pauses"]:
        if p.get("clip"):
            p["clip"] = os.path.basename(p["clip"])
    return rep


def _flush_library() -> bool:
    from . import shotcheck, stormlib
    try:
        shotcheck.flush()
    except Exception as e:  # noqa: BLE001 - the video goes on
        print(f"[stormdesk] shared verdicts: {type(e).__name__}", flush=True)
    return stormlib.flush_bad()


def _library_report() -> dict:
    from . import shotcheck, stormlib
    rep = stormlib.report()
    try:
        rep["freeChecks"] = shotcheck.report()
    except Exception:  # noqa: BLE001
        pass
    return rep


def _youtube_report() -> dict:
    from . import ytdlp
    return ytdlp.bot_report()


def _tab_for(text: str, brief: Optional[dict]) -> str:
    """A block's tab: the story place it names most (short), else BREAKING NEWS."""
    best, n = "", 0
    for p in (brief or {}).get("places") or []:
        name = str(p or "").split(",")[0].strip()
        if len(name) < 3:
            continue
        c = len(re.findall(r"\b" + re.escape(name) + r"\b", text, re.I))
        if c > n:
            best, n = name, c
    return best.upper()[:22] if best else "BREAKING NEWS"


# --------------------------------------------------------------------------- #
# After the render
# --------------------------------------------------------------------------- #

class SyncError(RuntimeError):
    """The drawn picture and the timeline disagree: the video must not ship (handler.do_render lets it fail)."""


AMB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sdkit", "ambience")


def amb_bed_file(scene: dict, resolve: Optional[Callable] = None) -> str:
    """A pause clip's own ambience bed (the kit's picks "break_amb" / render3 amb_bed: the clip talks or has music, so a real
    bed plays under its picture instead): scene.stormDesk.ambBed = a bed's name in sdkit/ambience ("rushing_water") or a
    link. True = the default water. "" = the clip's own sound."""
    want = (scene.get("stormDesk") or {}).get("ambBed")
    if not want:
        return ""
    if want is True:
        return WATER_FILE
    want = str(want)
    if want.startswith(("http://", "https://")):
        try:
            return resolve(want) if resolve else ""
        except Exception:  # noqa: BLE001 - its own sound then
            return ""
    for ext in (".mp3", ".wav", ".m4a"):
        p = os.path.join(AMB_DIR, os.path.basename(want).rsplit(".", 1)[0] + ext)
        if os.path.isfile(p):
            return p
    return WATER_FILE


def _read_audio(src: str, start: float, seconds: float, sr: int, af: str = "") -> "Any":
    import numpy as np
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{max(0.0, start):.3f}", "-t", f"{seconds:.3f}", "-i", src, "-vn",
           *(["-af", af] if af else []), "-f", "s16le", "-ac", "2", "-ar", str(sr), "-"]
    raw = subprocess.run(cmd, capture_output=True, timeout=300).stdout
    return np.frombuffer(raw[: len(raw) // 4 * 4], np.int16).reshape(-1, 2).astype(np.float32) / 32768.0


def nat_track(doc: dict, total: float, offset: float, sr: int = 48000, resolve: Optional[Callable] = None):
    """The pauses' own sound on the video's clock: each pause clip at NAT_LUFS, faded in and out over NAT_FADE,
    only inside its pause (the narration's silence). Returns (samples N x 2 float32, rows)."""
    import numpy as np
    fps = int(doc.get("fps") or 30)
    n = int(round(total * sr)) + sr
    track = np.zeros((n, 2), np.float32)
    rows = []
    pauses = (doc.get("meta") or {}).get("stormDesk", {}).get("pauses") or []
    order = sorted(doc.get("scenes") or [], key=lambda x: int(x["startFrame"]))
    water_at = 0.0
    for idx, s in enumerate(order):
        if not s.get("natSound"):
            continue
        url = str((s.get("media") or {}).get("url") or "")
        src = resolve(url) if resolve else url
        t0 = int(s["startFrame"]) / fps
        t1 = t0 + int(s["durationInFrames"]) / fps
        # Its own window: the one it starts inside first (hook clips sit edge to edge, one's end is the next one's start).
        win = next(((p["t0"], p["t1"]) for p in pauses if p["t0"] - 0.05 <= t0 < p["t1"] - 0.05),
                   next(((p["t0"], p["t1"]) for p in pauses if p["t0"] - 1.2 <= t0 <= p["t1"]), (t0, t1)))
        a, b = max(t0, win[0]), min(t1, win[1])
        if b - a < 0.5 or not src:
            continue
        # J / L cuts (the owner's editing rule): the clip's sound comes up a beat before the narration stops
        # (as far as the clip has sound before its picture) and runs on under the first words after the pause.
        # audio_in: the clip keeps its voice while the picture is another stretch of the source (kit render3).
        heard = (s.get("media") or {}).get("audioIn")
        trim0 = float(heard if isinstance(heard, (int, float)) else (s.get("media") or {}).get("trimStart") or 0.0) + (a - t0)
        lead = min(J_LEAD, max(0.0, trim0)) if not s.get("openClip") else 0.0
        tail = L_TAIL
        nxt = order[idx + 1] if idx + 1 < len(order) else None
        if s.get("talk"):
            lead, tail = 0.0, 0.0               # a talking clip starts and ends on its own words (the kit: no J/L for these)
        elif nxt is not None and nxt.get("natSound"):
            tail = 0.0                          # the next clip's own sound starts here
        music = str(((s.get("media") or {}).get("clipAudio") or {}).get("kind") or "") == "music" and not s.get("talk")
        bed = amb_bed_file(s, resolve)
        if music or bed:
            lead, tail = 0.0, 0.0               # never a clip's music in a pause (the kit): real water plays instead
        a, b = a - lead, b + tail
        trim = trim0 - lead
        try:
            if bed:                             # the kit's per-pause amb_bed: this clip's own bed (surf, wind, rumble)
                at = float(((s.get("stormDesk") or {}).get("ambAt")) or 0.0)
                x = _read_audio(bed, at, b - a, sr, f"loudnorm=I={NAT_LUFS}:TP=-3:LRA=11")
            elif music:
                x = _read_audio(WATER_FILE, water_at, b - a, sr, f"loudnorm=I={NAT_LUFS}:TP=-3:LRA=11")
                water_at = (water_at + (b - a)) % 10.0
            else:
                x = _read_audio(src, trim, b - a, sr, f"loudnorm=I={NAT_LUFS}:TP=-3:LRA=11")
        except Exception as e:  # noqa: BLE001 - this pause plays without its sound
            rows.append({"at": round(a, 2), "ok": False, "why": f"{type(e).__name__}"})
            continue
        if not len(x):
            rows.append({"at": round(a, 2), "ok": False, "why": "no sound"})
            continue
        o = int(round((a + offset) * sr))
        m = min(len(x), int(round((b - a) * sr)), n - o)
        if m <= 0:
            continue
        g = np.ones(m, np.float32)
        r_in = min(m // 2, int(max(0.04 if s.get("talk") else NAT_FADE, lead) * sr))
        r_out = min(m // 2, int(max(0.06 if s.get("talk") else NAT_FADE, tail) * sr))
        if r_in:
            g[:r_in] = np.linspace(0, 1, r_in)
        if r_out:
            g[-r_out:] = np.linspace(1, 0, r_out)
        track[o:o + m] += x[:m] * g[:, None]
        rows.append({"at": round(a, 2), "seconds": round(m / sr, 2), "ok": True, "lead": round(lead, 2),
                     "tail": round(tail, 2), **({"water": "its sound is music"} if music and not bed else {}),
                     **({"bed": os.path.basename(bed)} if bed else {})})
    return track, rows


def first_hook_window(doc: dict) -> Optional[Tuple[float, float]]:
    """(start, end) seconds of the video's first hook clip, or the first opening pause no clip was found for."""
    fps = int(doc.get("fps") or 30)
    hooks = sorted((s for s in doc.get("scenes") or [] if s.get("openClip")), key=lambda x: int(x["startFrame"]))
    if hooks:
        a = int(hooks[0]["startFrame"]) / float(fps)
        return a, a + int(hooks[0]["durationInFrames"]) / float(fps)
    for p in ((doc.get("meta") or {}).get("stormDesk") or {}).get("pauses") or []:
        if p.get("open") and float(p.get("t1") or 0.0) > float(p.get("t0") or 0.0):
            return float(p["t0"]), float(p["t1"])
    return None


def hook_water(doc: dict, nat: Any, total: float, offset: float, sr: int = 48000, read: Optional[Callable] = None) -> Optional[dict]:
    """A silent opening never reaches the viewer (kit tools/hookwater.py): real rushing water under the first hook clip when
    it has no sound of its own, fading out into the next clip. Added to `nat` in place. Returns its report, or None."""
    import numpy as np
    win = first_hook_window(doc)
    if not win:
        return None
    a, b = win[0] + offset, win[1] + offset
    i0, i1 = int(a * sr), min(len(nat), int(b * sr))
    if i1 - i0 < int(0.5 * sr):
        return None
    level = float(20 * np.log10(np.sqrt(np.mean(nat[i0:i1] ** 2)) + 1e-9))
    if level > WATER_SILENT_DB:
        return None
    d = b - a
    x = (read or (lambda p, at, secs: _read_audio(p, at, secs, sr)))(WATER_FILE, 0.0, d + 0.25)
    if x is None or not len(x):
        return {"added": False, "why": "no water file"}
    m = min(len(x), len(nat) - i0)
    g = np.full(m, float(WATER_LEVEL), np.float32)
    r = min(m, int(0.08 * sr))
    g[:r] *= np.linspace(0, 1, r)
    # (kit: afade out from d - 0.25 over 0.5 s, the file itself ends at d + 0.25)
    o0 = max(0, int((d - 0.25) * sr))
    if o0 < m:
        g[o0:m] *= np.linspace(1, 0, m - o0)
    nat[i0:i0 + m] += x[:m] * g[:, None]
    return {"added": True, "at": round(a, 2), "seconds": round(m / float(sr), 2), "levelDb": round(level, 1)}


def word_spans(doc: dict) -> List[Tuple[float, float]]:
    """The narration's words on the video's clock (seconds), merged where under 0.25 s apart."""
    spans = sorted((float(w.get("start", 0)), float(w.get("end", 0))) for s in doc.get("scenes") or []
                   for w in s.get("words") or [] if float(w.get("end", 0)) > float(w.get("start", 0)))
    out: List[List[float]] = []
    for a, b in spans:
        if out and a - out[-1][1] < 0.25:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def under_gain(clip_db: float, voice_db: float, below: float = UNDER_VOICE_DB) -> float:
    """The linear gain that puts a clip measured at `clip_db` (gated RMS) `below` dB under a voice at
    `voice_db`, never lifting it more than UNDER_GAIN_MAX_DB."""
    want = float(voice_db) - float(below)
    return float(10 ** (min(UNDER_GAIN_MAX_DB, want - float(clip_db)) / 20.0))


def under_track(doc: dict, total: float, offset: float, voice_db: float, sr: int = 48000,
                resolve: Optional[Callable] = None, read: Optional[Callable] = None):
    """
    The narration shots' own sound under the voice (clip_sound "ambient", the editor's switches:
    clipaudio.plays_under_voice): each clip that plays set UNDER_VOICE_DB under the voice (from its own
    measured level), faded UNDER_FADE at its cut, and UNDER_DUCK_DB lower again while a word is spoken (a
    0.15 s ramp). Returns (samples N x 2 float32, rows, speech mask N float32 0..1).
    """
    import numpy as np
    from . import clipaudio
    fps = int(doc.get("fps") or 30)
    n = int(round(total * sr)) + sr
    track = np.zeros((n, 2), np.float32)
    talk = np.zeros(n, np.float32)
    for a, b in word_spans(doc):
        i0, i1 = max(0, int((a + offset - 0.05) * sr)), min(n, int((b + offset + 0.05) * sr))
        talk[i0:i1] = 1.0
    k = max(1, int(0.15 * sr))
    talk_s = np.convolve(talk, np.ones(k, np.float32) / k, mode="same")
    duck = 1.0 - (1.0 - 10 ** (-UNDER_DUCK_DB / 20.0)) * np.clip(talk_s, 0, 1)
    mode = str((((doc.get("stormDesk") or {}).get("clipSound")) or {}).get("mode") or "off")
    below = float((((doc.get("stormDesk") or {}).get("clipSound")) or {}).get("underVoiceDb") or UNDER_VOICE_DB)
    below = max(12.0, min(30.0, abs(below)))       # dB below the voice (an editor's -20 reads the same)
    todo = [s for s in doc.get("scenes") or [] if (s.get("media") or {}).get("type") == "video"
            and clipaudio.plays_under_voice(s, mode)]
    rows: List[dict] = []
    reader = read or (lambda src, at, secs: _read_audio(src, at, secs, sr))

    def one(s: dict):
        url = str((s.get("media") or {}).get("url") or "")
        src = resolve(url) if resolve else url
        t0 = int(s["startFrame"]) / fps
        secs = int(s["durationInFrames"]) / fps
        if not src or secs < 0.2:
            return s, t0, None
        try:
            return s, t0, reader(src, float((s.get("media") or {}).get("trimStart") or 0.0), secs)
        except Exception:  # noqa: BLE001 - this clip stays silent
            return s, t0, None
    with ThreadPoolExecutor(6) as ex:
        got = list(ex.map(one, todo))
    for s, t0, x in got:
        if x is None or not len(x):
            rows.append({"id": s.get("id"), "at": round(t0, 2), "ok": False})
            continue
        mono = x.mean(axis=1)
        blk = max(1, int(0.05 * sr))
        nb = len(mono) // blk
        if nb >= 4:
            rms = np.sort(np.sqrt(np.mean(mono[: nb * blk].reshape(nb, blk) ** 2, axis=1)))[int(nb * 0.3):]
            db = float(20 * np.log10(np.sqrt(np.mean(rms ** 2)) + 1e-9))
        else:
            db = float(20 * np.log10(np.sqrt(np.mean(mono ** 2)) + 1e-9))
        if db < -60.0:
            rows.append({"id": s.get("id"), "at": round(t0, 2), "ok": False, "why": "silent"})
            continue
        g = under_gain(db, voice_db, below)
        o = int(round((t0 + offset) * sr))
        m = min(len(x), int(round(int(s["durationInFrames"]) / fps * sr)), n - o)
        if m <= 0:
            continue
        env = np.ones(m, np.float32)
        r = min(m // 2, int(UNDER_FADE * sr))
        if r:
            env[:r] = np.linspace(0, 1, r)
            env[-r:] = np.linspace(1, 0, r)
        track[o:o + m] += x[:m] * (env * g * duck[o:o + m])[:, None]
        rows.append({"id": s.get("id"), "at": round(t0, 2), "ok": True, "db": round(db, 1),
                     "gainDb": round(20 * math.log10(max(1e-9, g)), 1)})
    return track, rows, talk


def _voice_level(base, spans: List[Tuple[float, float]], offset: float, sr: int = 48000) -> float:
    """The narration's level (RMS dBFS) in the drawn file while its words are spoken."""
    import numpy as np
    mono = base.mean(axis=1) if getattr(base, "ndim", 1) == 2 else base
    parts = [mono[max(0, int((a + offset) * sr)):int((b + offset) * sr)] for a, b in spans]
    parts = [p for p in parts if len(p)]
    if not parts:
        return -20.0
    x = np.concatenate(parts)
    return float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9))


def classify_missing(doc: dict, resolve: Optional[Callable] = None) -> int:
    """A narration clip with no sound class yet (one swapped in the editor after the plan): read and classed now
    (src/clipaudio.py), so the mix knows whether it may play under the voice. Returns how many."""
    from . import clipaudio
    fps = int(doc.get("fps") or 30)
    mode = str((((doc.get("stormDesk") or {}).get("clipSound")) or {}).get("mode") or "off")
    todo = [s for s in doc.get("scenes") or [] if (s.get("media") or {}).get("type") == "video"
            and not s.get("natSound") and not isinstance((s.get("media") or {}).get("clipAudio"), dict)
            and (mode == "ambient" or s.get("clipSound") is True)]

    def one(s: dict) -> None:
        m = s["media"]
        url = str(m.get("url") or "")
        src = resolve(url) if resolve else url
        got = clipaudio.classify(src, float(m.get("trimStart") or 0.0), int(s["durationInFrames"]) / fps,
                                 title=source_title(s), confirm=False)
        got.pop("parts", None)
        m["clipAudio"] = got
    if todo:
        with ThreadPoolExecutor(6) as ex:
            list(ex.map(one, todo))
    return len(todo)


def mix_check(base, under, talk, sr: int = 48000) -> dict:
    """Level of the clip sound under the narration vs the narration (+ music) itself, while a word is spoken:
    the laptop's mixcheck.py on the worker. ok = the clip sound sits at least MIX_MARGIN_DB under the voice."""
    import numpy as np
    n = min(len(base), len(under), len(talk))
    if n <= 0:
        return {"ok": True, "underVoiceDb": None}
    on = talk[:n] > 0.5

    def db(x):
        return float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9)) if len(x) else -120.0
    if not on.any():
        return {"ok": True, "underVoiceDb": None}
    v = db(base[:n][on])
    c = db(under[:n][on])
    return {"ok": bool(c <= v - MIX_MARGIN_DB), "voiceDb": round(v, 1), "clipDb": round(c, 1),
            "underVoiceDb": round(c - v, 1)}


def _duration(path: str, stream: str) -> float:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", f"{stream}:0", "-show_entries",
                              "stream=duration", "-of", "csv=p=0", path], capture_output=True, text=True,
                             timeout=60).stdout.strip().split("\n")[0]
        # (A stream with side data prints "95.467333," - the old float() of that was 0, which skipped the sync
        # check on every real render: the live run of 2026-11-03.)
        m = re.match(r"\s*([0-9]+(?:\.[0-9]+)?)", out)
        return float(m.group(1)) if m else 0.0
    except (ValueError, subprocess.SubprocessError, OSError):
        return 0.0


def _loudness(path: str) -> dict:
    p = subprocess.run(["ffmpeg", "-v", "info", "-i", path, "-vn", "-af",
                        f"loudnorm=I={MASTER_LUFS}:TP={MASTER_TP}:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=1800)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr or "", re.S)
    return json.loads(m.group(0)) if m else {}


def after_render(doc: dict, out_path: str, work: str, resolve: Optional[Callable[[str], str]] = None,
                 offset_frames: Optional[int] = None, total_frames: Optional[int] = None) -> dict:
    """
    The finished file of a storm desk video (handler.do_render, after the quality checks): the pauses' own sound
    mixed in (the renderer keeps every clip muted), the master at -14 LUFS / -1.5 dBTP, a clean delivery file
    (no encoder or tool tags, the encoder's SEI note stripped), and the picture's length checked against the
    timeline. Replaces out_path; returns the render report. Raises only when the picture and the timeline
    disagree by more than SYNC_TOLERANCE (the laptop build's collapsed join would have shipped otherwise).
    """
    import numpy as np
    import wave
    from . import brandkit
    sr = 48000
    fps = int(doc.get("fps") or 30)
    intro, _body, _outro, total_fr = brandkit.layout(doc)
    if offset_frames is not None:
        intro = offset_frames
    if total_frames is not None:
        total_fr = total_frames
    total = total_fr / float(fps)
    rep: Dict[str, Any] = {"timelineSeconds": round(total, 3)}
    vdur = _duration(out_path, "v")
    rep["pictureSeconds"] = round(vdur, 3)
    rep["pictureOffset"] = round(vdur - total, 3)
    if vdur and abs(vdur - total) > SYNC_TOLERANCE:
        raise SyncError(f"storm desk sync check: the picture runs {vdur:.2f} s, the timeline {total:.2f} s")
    base = _read_audio(out_path, 0.0, total + 1.0, sr)
    nat, rows = nat_track(doc, total, intro / float(fps), sr, resolve)
    rep["pauseSound"] = rows
    try:
        water = hook_water(doc, nat, total, intro / float(fps), sr)
        if water:
            rep["hookWater"] = water
    except Exception as e:  # noqa: BLE001 - the video ships as it is
        rep["hookWater"] = {"added": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}
    n = max(len(base), int(round(total * sr)))
    mix = np.zeros((n, 2), np.float32)
    mix[:len(base)] += base
    m = min(n, len(nat))
    mix[:m] += nat[:m]
    # The clips' own sound under the narration (clip_sound "ambient" and the editor's switches).
    try:
        rep["classifiedAtRender"] = classify_missing(doc, resolve)
        voice_db = _voice_level(base, word_spans(doc), intro / float(fps), sr)
        under, urows, talk = under_track(doc, total, intro / float(fps), voice_db, sr, resolve)
        rep["underVoice"] = {"mode": str(((doc.get("stormDesk") or {}).get("clipSound") or {}).get("mode") or "off"),
                             "clips": sum(1 for r in urows if r.get("ok")), "rows": urows[:200],
                             "voiceDb": round(voice_db, 1)}
        if any(r.get("ok") for r in urows):
            rep["mixCheck"] = mix_check(base.mean(axis=1), under[:len(base)].mean(axis=1), talk[:len(base)], sr)
            if not rep["mixCheck"]["ok"]:
                # Never over the voice: brought down to the margin rather than shipped too loud.
                k = 10 ** ((rep["mixCheck"]["voiceDb"] - MIX_MARGIN_DB - rep["mixCheck"]["clipDb"]) / 20.0)
                under *= np.float32(k)
                rep["mixCheck"]["loweredDb"] = round(20 * math.log10(max(1e-9, k)), 1)
            m = min(n, len(under))
            mix[:m] += under[:m]
    except Exception as e:  # noqa: BLE001 - the video ships with clips silent under the voice
        rep["underVoice"] = {"error": f"{type(e).__name__}: {str(e)[:160]}"}
    mix = mix[: int(round(total * sr))]
    wav = os.path.join(work, "stormdesk_mix.wav")
    with wave.open(wav, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(mix, -1, 1) * 32767).astype(np.int16).tobytes())
    meas = _loudness(wav)
    if meas.get("input_i") not in (None, "-inf"):
        af = (f"loudnorm=I={MASTER_LUFS}:TP={MASTER_TP}:LRA=11:measured_I={meas['input_i']}:"
              f"measured_TP={meas['input_tp']}:measured_LRA={meas['input_lra']}:"
              f"measured_thresh={meas['input_thresh']}:offset={meas.get('target_offset', '0')}:linear=true")
        rep["lufsBefore"] = float(meas["input_i"])
    else:
        af = f"loudnorm=I={MASTER_LUFS}:TP={MASTER_TP}:LRA=11"
    tmp = out_path + ".sd.mp4"
    # The wav's layout is explicit: ffmpeg 5.1 (the worker's) refused "unknown" (2 channels) on the first real pieces render.
    chain = f"aformat=channel_layouts=stereo,{af},aresample={sr},aformat=channel_layouts=stereo"
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", out_path, "-guess_layout_max", "2", "-i", wav, "-map", "0:v:0", "-map", "1:a:0",
           "-c:v", "copy", "-bsf:v", "filter_units=remove_types=6", "-af", chain,
           "-c:a", "aac", "-b:a", "256k", "-ar", str(sr), "-ac", "2",
           "-map_metadata", "-1", "-map_chapters", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
           "-flags:a", "+bitexact", "-metadata:s:v", "handler_name=VideoHandler",
           "-metadata:s:a", "handler_name=SoundHandler", "-metadata:s:v", "encoder=", "-metadata:s:a", "encoder=",
           "-t", f"{total:.3f}", "-movflags", "+faststart", tmp]
    p = subprocess.run(cmd, capture_output=True, timeout=3600)
    if p.returncode != 0 or not os.path.isfile(tmp):
        # The SEI filter is the one step an old ffmpeg may lack: once more without it.
        cmd2 = [c for c in cmd if c not in ("-bsf:v", "filter_units=remove_types=6")]
        p = subprocess.run(cmd2, capture_output=True, timeout=3600)
        if p.returncode != 0 or not os.path.isfile(tmp):
            # Last: the wav to AAC at the master's level in one plain pass, so the pauses keep their sound.
            first_error = (p.stderr or b"")[-300:].decode("utf-8", "replace")
            cmd3 = ["ffmpeg", "-v", "error", "-y", "-i", out_path, "-i", wav, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                    "-af", f"loudnorm=I={MASTER_LUFS}:TP={MASTER_TP}:LRA=11", "-c:a", "aac", "-b:a", "256k", "-ar", str(sr), "-ac", "2",
                    "-map_metadata", "-1", "-t", f"{total:.3f}", "-movflags", "+faststart", tmp]
            p = subprocess.run(cmd3, capture_output=True, timeout=3600)
            if p.returncode != 0 or not os.path.isfile(tmp):
                raise RuntimeError("storm desk mix failed: " + first_error + " | " + (p.stderr or b"")[-200:].decode("utf-8", "replace"))
            rep["mixFallback"] = first_error[:200]
        rep["seiStripped"] = False
    else:
        rep["seiStripped"] = True
    os.replace(tmp, out_path)
    try:
        os.remove(wav)
    except OSError:
        pass
    after = _loudness(out_path)
    if after.get("input_i") not in (None, "-inf"):
        rep["lufs"] = float(after["input_i"])
        rep["truePeak"] = float(after["input_tp"])
    v2, a2 = _duration(out_path, "v"), _duration(out_path, "a")
    rep["final"] = {"picture": round(v2, 3), "sound": round(a2, 3), "offset": round(a2 - v2, 3)}
    if v2 and abs(v2 - total) > SYNC_TOLERANCE:
        raise SyncError(f"storm desk sync check after the mix: picture {v2:.2f} s vs timeline {total:.2f} s")
    rep["cleanMetadata"] = True
    return rep
