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
MUSIC_UNDER_VOICE_DB = 21.0     # the user's own track under the narration (the owner's Hoover / Sedona mix)
MUSIC_SPEECH_DUCK_DB = 3.0      # ... and this much lower while a word is spoken
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
CLIP_SOUND_MODES = ("ambient", "off")

# The owner's blocklist (2026-11-02): never this channel's footage, in any storm desk video.
DEFAULT_BLOCKLIST = ("Desert Rat Explorations",)

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


def is_style(inp: Optional[dict] = None, doc: Optional[dict] = None) -> bool:
    from . import styles
    if inp is not None and styles.resolve(inp.get("video_style")) == STYLE:
        return True
    return bool(doc) and str(((doc or {}).get("meta") or {}).get("videoStyle") or "") == STYLE


def options(inp: Optional[dict]) -> dict:
    raw = (inp or {}).get("storm_desk")
    return dict(raw) if isinstance(raw, dict) else {}


def clip_sound_mode(opts: Optional[dict]) -> str:
    """The job's clip sound under the narration: "ambient" (the default) or "off"."""
    v = (opts or {}).get("clip_sound", "ambient")
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


def blocklist(inp: Optional[dict]) -> List[str]:
    """The channels this job never uses: the owner's list for the style, plus the job's own."""
    names = list(DEFAULT_BLOCKLIST) if is_style(inp) else []
    raw = (inp or {}).get("blocked_sources")
    if isinstance(raw, str):
        raw = re.split(r"[,\n;]+", raw)
    for n in raw or []:
        n = str(n or "").strip()
        if n and n.lower() not in {x.lower() for x in names}:
            names.append(n[:80])
    return names


def _norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


def blocked(channel: str, title: str, names: Sequence[str]) -> str:
    """The blocklist entry a candidate matches by its channel (or, failing that, its title), or ''."""
    ch, ti = _norm_name(channel), _norm_name(title)
    for n in names:
        k = _norm_name(n)
        if k and (k == ch or (len(k) >= 8 and (k in ch or k in ti))):
            return n
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
        return [{"at": 0.0, "secs": open_seconds(opts), "sentence": "", "open": True}] + mid
    return mid


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
        cut = min(s["end"] + 0.25, (s["end"] + nxt["start"]) / 2.0)
        prev = sents[k - 1]["text"] if k else ""
        cands.append({"at": round(cut, 3), "score": _drama(s["text"]) + 0.4 * _drama(prev), "sentence": s["text"]})
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
    return {"words": shift_words(words, pauses), "path": audio_path, "url": url,
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


def bake(path: str, boxes: List[List[float]], flip: bool) -> bool:
    """Blur `boxes` (shares of the frame) and mirror the clip, in place (sound kept). True when replaced."""
    if not boxes and not flip:
        return False
    chain, last = [], "0:v"
    for k, (bx, by, bw, bh) in enumerate(boxes):
        chain.append(f"[{last}]split[m{k}][c{k}];[c{k}]crop=iw*{bw}:ih*{bh}:iw*{bx}:ih*{by},boxblur=20:3[b{k}];"
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
    from . import ytdlp
    vid = video[3:] if video.startswith("yt:") else video
    for _ in range(3):
        try:
            path = ytdlp._yt_fetch(vid, work, start, seconds, audio=True)
        except Exception as e:  # noqa: BLE001 - the next try
            print(f"[stormdesk] pause clip {vid}: {type(e).__name__}: {str(e)[:120]}", flush=True)
            path = ""
        if path and os.path.isfile(path):
            return path
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
                classify: Optional[Callable] = None) -> Optional[dict]:
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


def make_pauses(doc: dict, pauses: List[dict], work: str, fetch: Optional[Callable] = None,
                frame_vertical: Optional[Callable[[str], bool]] = None,
                check: Optional[Callable[[str], str]] = None) -> List[dict]:
    """
    Each pause window becomes one scene: a continuous clip with its own sound (scene.natSound), cut from a
    source this block already uses, at a moment no shot shows, never the source of the shot before or after it.
    The shots the plan put in the window are trimmed or removed. A pause no clip could be fetched for keeps the
    plan's shots (silent but for the music) and says so in its row. Returns one row per pause.
    """
    fps = int(doc.get("fps") or 30)
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
            pool = inside + list(reversed([s for s in scenes if p0 - 90 * fps <= _end(s) <= p0])) +                 [s for s in scenes if p1 <= int(s["startFrame"]) <= p1 + 30 * fps]
        tries: List[Tuple[dict, str, float]] = []
        seen: set = set()
        for c in pool:
            mo = moment(c, fps)
            if not mo or mo[0] in seen:
                continue
            seen.add(mo[0])
            key = source_key(c)
            if key and key in (prev_key, next_key):
                continue                        # never two shots in a row from one source
            want = secs + PAUSE_SLACK
            start = pause_start(used.get(mo[0], []), want, video_seconds(mo[0]), gap)
            if start is None:
                continue
            tries.append((c, mo[0], start))
            if len(tries) >= (PAUSE_TRIES + 1 if is_open else PAUSE_TRIES):
                break
        path, src, best, scored = "", None, None, []

        def fetch_one(t: Tuple[dict, str, float]):
            c, vid, start = t
            try:
                got = fetch(vid, start, secs + PAUSE_SLACK)
            except Exception as e:  # noqa: BLE001
                print(f"[stormdesk] pause {k + 1}: {type(e).__name__}: {str(e)[:120]}", flush=True)
                return t, "", None
            if not got or not _audible(got):
                return t, "", None
            title = source_title(c)
            sc = pause_score(got, secs, title=title, relevance=_relevance(c))
            if sc is None or sc.get("reject"):
                print(f"[stormdesk] pause {k + 1}: {vid} @ {start:.0f}s turned down: "
                      f"{(sc or {}).get('reject') or 'unreadable'}", flush=True)
                return t, "", None
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
        if s.get("natSound") or (s.get("media") or {}).get("type") == "animation" or \
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
    return out


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
        loc = {"startFrame": int(LOC_FROM * fps), "durationInFrames": int((LOC_TO - LOC_FROM) * fps),
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
            "bug": {"opacity": 0.9}, "lowerThirds": lts, "location": loc, "subscribe": subs, "credits": True,
            "clipSound": {"mode": clip_sound_mode(opts), "underVoiceDb": UNDER_VOICE_DB, "duckDb": UNDER_DUCK_DB}}


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


def finish(doc: dict, inp: dict, brief: Optional[dict] = None, work: str = "", fetch: Optional[Callable] = None,
           ask: Optional[Callable] = None, frame_vertical: Optional[Callable[[str], bool]] = None,
           upload: Optional[Callable[[str, str], str]] = None, check: Optional[Callable[[str], str]] = None) -> dict:
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
    rep["pauses"] = step("pauses", lambda: make_pauses(doc, pauses, work, fetch, frame_vertical, check)) or []
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
        n_arch += int(arch)
        label = "VIDEO" if m.get("type") == "video" else "PHOTO"
        s["credit"] = {"text": f"{label}: {credit_name(s)}", **({"archive": True} if arch else {})}
    rep["archiveShots"] = n_arch

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
        if not s.get("natSound"):
            # What its own sound is (src/clipaudio.py): only natural sound plays under the narration.
            try:
                from . import clipaudio
                m["clipAudio"] = clipaudio.classify(path, float(m.get("trimStart") or 0.0),
                                                    int(s["durationInFrames"]) / fps, title=source_title(s))
                m["clipAudio"].pop("parts", None)
            except Exception:  # noqa: BLE001 - unknown: silent under the voice
                m["clipAudio"] = {"kind": "unknown"}
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
    rep["blurredClips"], rep["flippedClips"] = marked[0], flipped[0]
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

    # The checks, as the video stands.
    rep["repeats"] = repeats(doc)
    rep["sources"] = shares(doc)[:30]
    over = [r for r in rep["sources"] if r["share"] > SOURCE_CAP_SHARE + 0.005]
    rep["sourcesOverCap"] = over
    longest = max((int(s["durationInFrames"]) / fps for s in doc["scenes"]
                   if not s.get("natSound") and (s.get("media") or {}).get("type") != "animation"), default=0.0)
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
    for s in doc.get("scenes") or []:
        if not s.get("natSound"):
            continue
        url = str((s.get("media") or {}).get("url") or "")
        src = resolve(url) if resolve else url
        t0 = int(s["startFrame"]) / fps
        t1 = t0 + int(s["durationInFrames"]) / fps
        win = next(((p["t0"], p["t1"]) for p in pauses if p["t0"] - 1.2 <= t0 <= p["t1"]), (t0, t1))
        a, b = max(t0, win[0]), min(t1, win[1])
        if b - a < 0.5 or not src:
            continue
        trim = float((s.get("media") or {}).get("trimStart") or 0.0) + (a - t0)
        try:
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
        r = min(m // 2, int(NAT_FADE * sr))
        if r:
            g[:r] = np.linspace(0, 1, r)
            g[-r:] = np.linspace(1, 0, r)
        track[o:o + m] += x[:m] * g[:, None]
        rows.append({"at": round(a, 2), "seconds": round(m / sr, 2), "ok": True})
    return track, rows


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
    below = max(12.0, min(30.0, below))
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
        return float(out)
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
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", out_path, "-i", wav, "-map", "0:v:0", "-map", "1:a:0",
           "-c:v", "copy", "-bsf:v", "filter_units=remove_types=6", "-af", af + f",aresample={sr}",
           "-c:a", "aac", "-b:a", "256k", "-ar", str(sr),
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
            raise RuntimeError("storm desk mix failed: " + (p.stderr or b"")[-300:].decode("utf-8", "replace"))
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
