"""
Subject pools: source a video the way GoMotion does.

Read off a real 20-minute GoMotion project: 174 clips drawn from only 45
subjects, the top four ("Lake Powell" 58, "Glen Canyon Dam" 27, "Glen Canyon"
19, "Colorado River" 14) covering two thirds of the video. Their method is a
few long, on-subject videos per subject, each judged once, with many
DIFFERENT moments cut from it for the lines about that subject.

Per-scene sourcing (media.source_many) does the opposite - a search, scouts,
downloads and several vision checks for every line - which is slow, spends a
vision call per candidate per scene, sends YouTube thousands of requests
through few proxy IPs, and stitches a section together from dozens of
unrelated uploads.

Here, per subject:
  1. two flat searches ("<subject> aerial drone footage 4k", "<subject>
     documentary footage"), filtered like every other candidate list; for an
     EVENT story (news/weather/disaster, a line carrying an eventWindow, or an
     explainer about a dated event) the news searches GoMotion's clips came
     from join them - "<subject> news <year>", "<subject> <what happened> news
     report" - plus one lookup inside config.NEWS_CHANNELS, never more than
     POOL_SEARCHES_MAX lookups per subject and only with config.NEWS_FOOTAGE;
  2. for the best few videos, one storyboard contact sheet each and ONE
     vision call rating every tile against the subject (vision.rate_tiles);
     in an event story the call is told the shots come from news reports;
  3. the approved moments, at least POOL_MIN_GAP_SECONDS apart, are handed to
     the subject's lines in story order, so consecutive lines about one thing
     play consecutive moments of one video; an event story takes at most
     NEWS_MAX_MOMENTS_PER_VIDEO from one report, so a subject's lines are
     drawn from several reports rather than the first long video;
  4. each moment is downloaded as its own short section.

A moment is identified as video + 10 s bucket (MediaAsset.moment_key): the
same moment never appears twice. Lines with no subject, people (their footage
and photos need the per-scene rules), stills, the opening (hook) lines, which
get the per-scene path's wider best-of search, and subjects whose pool runs
dry are left to the per-scene path.

The owner's review of a news video (2026-09-30) changed step 3: consecutive
lines taking consecutive moments of one video read as one shot repeated
("Drone's eye view of Texas flood damage" 4 times in the first minute). A
video now supplies at most config.MAX_MOMENTS_PER_VIDEO lines of the whole
video, SAME_VIDEO_GAP_SECONDS apart on the timeline (a ledger shared by every
subject, _Slots), and a line that names its own place (job "place", from the
director) is pooled under that place, searched with the event word and, for a
story about now, among the last month's uploads first.
"""
from __future__ import annotations

import datetime
import os
import re
import threading
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional, Set

from . import config, ledger, media, moments, vision, ytdlp

_PUNCT = re.compile(r"[^a-z0-9 ]+")
_ARTICLES = re.compile(r"\b(the|a|an)\b")

# --- event stories: the news report of what happened ------------------------
#
# GoMotion's 215 shots for a 22-minute Colorado River video were mostly local
# TV reports of the exact event (KUTV, ABC15, 8NewsNow, KGUN9, ABC7), several
# moments per report, and drone of the places as they are NOW. The two generic
# searches above never ask YouTube for those; these do.
_EVENT_KINDS = {"news", "weather", "disaster"}
NEWS_SEARCH_RESULTS = 15
# Local-TV reports run 45-120 s; the generic 60 s floor dropped most of them.
NEWS_MIN_SECONDS = 30.0
# Moments one report may supply in an event story (several reports, several
# moments each - GoMotion's pattern), None = unlimited (history/nature pools
# keep drawing many moments from one long documentary).
NEWS_MAX_MOMENTS_PER_VIDEO = 4
# Metadata bonus for a title or channel that reads as a news report, so it can
# WIN against a drone title (media._B_ROLL +3.0, plus +1.0 when the flat row
# carries a wide aspect) once news titles are allowed through at all.
NEWS_TITLE_BONUS = 3.5
# Flat searches plus the in-channel lookup, per subject pool.
POOL_SEARCHES_MAX = 4
_YT_THIS_YEAR = "EgIIBQ%3D%3D"          # same value as ytdlp._YT_THIS_YEAR
# YouTube's "this month" / "this week" upload filters (media._RECENT_SP).
_YT_RECENT = {"month": "EgIIBA%3D%3D", "week": "EgIIAw%3D%3D"}
# Rank bonus for an upload a last-month search returned, in a story about now:
# recent reports of the event are rated first, older ones only when they run
# out (the owner, 2026-09-30: footage of THIS flood, not last year's).
RECENT_BONUS = 2.5
_YEAR = re.compile(r"\b(19[89]\d|20[0-2]\d)\b")

_NEWS_TITLE = re.compile(
    r"\b(news|report(?:s|ing)?|press conference|interview|governor|gov\.|senator|mayor|"
    r"abc\s?\d*|nbc\s?\d*|cbs\s?\d*|fox\s?\d*|pbs|npr|kutv|ksl|kgun\s?\d*|kpnx|"
    r"8 ?news ?now|9 ?news|12 ?news|denver7|azfamily|cbs colorado|kjzz|cpr news|"
    r"reuters|associated press)\b", re.I)
# Station call signs live in the channel field ("KUTV", "KGUN 9"), never
# matched on title words, which would hit "Kutv" in nothing but call signs
# anyway and "West" in everything.
_CALL_SIGN = re.compile(r"^[KW][A-Z]{2,3}(?:-?TV)?\b")


def _news_title(title: str, channel: str = "") -> bool:
    return bool(_NEWS_TITLE.search(f"{title} {channel}") or _CALL_SIGN.match(channel or ""))


def subject_story(sjobs: List[dict]) -> dict:
    """
    {kind, event, year, window, is_event, recency, word} for one subject's lines.

    Read from what already travels with the jobs (event_window and
    scene_intent are copied into every fan-out part) and the story kind
    media.set_story_kind records on every worker, so a part behaves like the
    parent. is_event only ever with config.NEWS_FOOTAGE: off, the pools search
    exactly as before. `recency` is "month" when the lines belong to a story
    about now (the director's job "recency"), `word` the event's own word
    ("flooding", "wildfire") for place + event searches.
    """
    from . import director            # lazy: director never imports pools
    kind = media._STORY_KIND["kind"]
    brief = director.LAST_STORY                  # {} inside a fan-out part
    windows = {j.get("event_window") for j in sjobs if j.get("event_window")}
    si = next((j.get("scene_intent") for j in sjobs if j.get("scene_intent")), None) or {}
    event = str(brief.get("event") or si.get("event_type") or "").replace("/", " ")
    event = " ".join(event.split())
    when = str(si.get("time_context") or "")
    year = brief.get("year") or (int(when) if re.fullmatch(r"20\d\d", when) else None) \
        or (datetime.date.today().year if when == "current" else None)
    window = "year" if "year" in windows else ("event" if windows else "")
    if window == "year" and not year:
        year = datetime.date.today().year
    # A story about now gets news searches too, whatever its kind (the Glen
    # Canyon narration came back "history" and got none).
    current = director.current_story({"kind": kind, "year": year})
    is_event = bool(config.NEWS_FOOTAGE) and (
        kind in _EVENT_KINDS or bool(windows) or (kind == "explainer" and bool(event)) or current)
    recencies = {j.get("recency") for j in sjobs if j.get("recency")}
    recency = next((r for r in ("week", "month") if r in recencies), "") if config.RECENT_FOOTAGE_FIRST else ""
    word = director.event_word(brief) or director.event_word({"event": si.get("event_type") or ""})
    return {"kind": kind, "event": event, "year": year, "window": window, "is_event": is_event,
            "recency": recency, "word": word}


def _event_words(event: str, subject: str) -> str:
    """'2026 Colorado River water cuts' for subject 'Colorado River' -> 'water cuts'."""
    skip = set(subject_key(subject).split())
    return " ".join(w for w in event.split()
                    if subject_key(w) and subject_key(w) not in skip and not _YEAR.fullmatch(w))


def subject_key(subject: str) -> str:
    """"Page, Arizona" and "Page Arizona" are one subject."""
    text = _ARTICLES.sub(" ", _PUNCT.sub(" ", (subject or "").lower()))
    return " ".join(text.split())


_PLACE_WORDS = re.compile(
    r"\b(?:canyon|dam|lake|river|bridge|mountains?|desert|falls|glacier|valley|bay|island|reservoir|arch|"
    r"mesa|butte|creek|national park|monument|gorge|basin|delta|beach|coast|peak|plateau|marina|spring|cave)s?\b",
    re.I)


def place_subject(subject: str, sjobs: List[dict]) -> bool:
    """
    True for a named place that is not the event itself (Cathedral in the
    Desert in a Lake Powell story): its pool may take the last few years'
    uploads (config.PLACE_FOOTAGE_YEARS). The story's own subject ("Lake
    Powell" in "Lake Powell drops to 22%") still needs this year's footage.
    """
    from . import director            # lazy: director never imports pools
    if not subject or not sjobs:
        return False
    placey = (sum(1 for j in sjobs if j.get("subject_type") == "place") * 2 >= len(sjobs)
              or bool(_PLACE_WORDS.search(subject)))
    event = subject_key(" ".join(str(director.LAST_STORY.get(k) or "") for k in ("event", "title")))
    return placey and subject_key(subject) not in event


def _pool_name(job: dict) -> str:
    """What a line's pool is about: the place the line names (director
    linePlace, job "place") before its subject, so a "Dallas and Fort Worth"
    line is pooled - and searched - as Dallas, not with every Texas line."""
    return (job.get("place") or job.get("subject") or "").strip()


def groups(jobs: List[dict]) -> Dict[str, List[dict]]:
    """
    Footage lines grouped by subject, in story order (key -> jobs).

    People stay on the per-scene path: its judge is called with allow_people
    for a person subject (media._vision_gate -> vision.acceptable), whereas
    rate_tiles has no such switch; their interview searches come from
    director.news_queries. Places and things (two thirds of GoMotion's clips)
    are pooled here, from news reports and drone videos. So do the opening
    lines (job "hook"): a pool rates storyboard tiles once per video, while
    the per-scene path judges the downloaded frames best-of-N with a wider
    search for them (the owner, 2026-09-30: the hook gets the strongest clips).
    """
    out: Dict[str, List[dict]] = {}
    for job in sorted(jobs, key=lambda j: j["index"]):
        if job.get("visual_type", "footage") != "footage":
            continue
        if job.get("subject_type") == "person":
            continue
        if job.get("hook"):
            continue
        si = job.get("scene_intent") if isinstance(job.get("scene_intent"), dict) else {}
        if si.get("role") in ("coming", "chain"):
            continue                   # "what's coming" shots have their own searches; a chain continues its clip
        key = subject_key(_pool_name(job))
        if key:
            out.setdefault(key, []).append(job)
    return out


def display_name(jobs: List[dict]) -> str:
    return Counter(_pool_name(j) for j in jobs).most_common(1)[0][0]


def _uses_channels(story: Optional[dict], require_cc: bool) -> bool:
    """Whether the pool also looks inside config.NEWS_CHANNELS (event stories only)."""
    return bool(story and story.get("is_event") and not require_cc and config.NEWS_CHANNELS)


def _searches(subject: str, story: Optional[dict] = None,
              limit: Optional[int] = None) -> List[tuple]:
    """
    (query, variant, recency) per flat search, the two generic searches first
    and unchanged. An event story adds the news searches after them - what
    happened to the subject, in the story's year - up to `limit` searches in
    all (POOL_SEARCHES_MAX, minus one when the channel lookup runs).
    """
    generic = [(f"{subject} aerial drone footage 4k", "drone", ""),
               (f"{subject} documentary footage", "doc", "")]
    if not story or not story.get("is_event"):
        return generic
    year = str(story.get("year") or "")
    word = str(story.get("word") or "").strip()
    now = story.get("recency") or ""
    if now in _YT_RECENT and word:
        # A story about now (the owner's news compilations, 2026-09-30): the
        # place the lines name with the event's own word, among the last
        # month's uploads first, then the same search over any upload for an
        # event YouTube has little recent footage of yet. The generic drone
        # and documentary searches find the skyline, not the flood, and drop
        # out; _rank puts the recent uploads first.
        what = subject if _names_word(subject, word) else f"{subject} {word}"
        first = [(f"{what} {year}".strip(), "event-now", now),
                 (f"{what} news", "news-now", now),
                 (f"{what} {year}".strip(), "event", ""),
                 (f"{what} drone", "drone-now", now)]
        cap = POOL_SEARCHES_MAX if limit is None else max(1, limit)
        if config.EYEWITNESS_SEARCHES:
            # The Nature & Weather edit: the way eyewitness uploads of the
            # event are titled ("Atlantic City flooding video"), among the
            # last month's uploads, right after the event search.
            first.insert(1, (f"{what} video", "eyewitness-now", now))
            cap += 1
        seen, out = set(), []
        for q, v, r in first:
            if (q.lower(), r) not in seen:
                seen.add((q.lower(), r))
                out.append((q, v, r))
        return out[:cap]
    recent = "year" if story.get("window") == "year" else ""
    topic = _event_words(story.get("event") or "", subject)
    news = [(f"{subject} news {year}".strip(), "news", recent)]
    if topic:
        news.append((f"{subject} {topic} news report", "news-event", recent))
    news += [(f"{subject} {year}".strip(), "news-plain", recent),        # local TV titles are short
             (f"{subject} drone {year}".strip(), "drone-year", recent)]  # the place as it is NOW
    seen, out = set(), []
    for q, v, r in generic + news:
        if q.lower() not in seen:
            seen.add(q.lower())
            out.append((q, v, r))
    return out[:max(len(generic), POOL_SEARCHES_MAX if limit is None else limit)]


def _names_word(text: str, word: str) -> bool:
    """Does `text` already carry the event word ("Texas floods" has "flooding")?"""
    stem = (word or "").lower().split()[0][:5] if word else ""
    return bool(stem) and stem in (text or "").lower()


def _target(query: str, require_cc: bool, recency: str) -> str:
    """The yt-dlp target: the CC results page, this year's (month's, week's) uploads, or a flat search."""
    if require_cc:
        return ("https://www.youtube.com/results?search_query="
                + urllib.parse.quote_plus(query) + "&sp=EgIwAQ%3D%3D")
    if recency in _YT_RECENT:
        return ("https://www.youtube.com/results?search_query="
                + urllib.parse.quote_plus(query) + "&sp=" + _YT_RECENT[recency])
    if recency == "year":
        # The only recency signal there is: flat rows carry no upload date.
        return ("https://www.youtube.com/results?search_query="
                + urllib.parse.quote_plus(query) + "&sp=" + _YT_THIS_YEAR)
    return f"ytsearch{NEWS_SEARCH_RESULTS}:{query}"


def _rank(c: dict, words: List[str], story: Optional[dict], via: str) -> Optional[float]:
    """
    A candidate's rank, or None when it is not for this story.

    Outside an event story: the metadata score plus how much of the subject
    the title names; a title naming none of it is not a pool candidate. In an
    event story a news report of the exact event outranks a generic drone
    video (NEWS_TITLE_BONUS, +1.5 for naming the event, +1.5 from a
    NEWS_CHANNELS upload, +1.0/-2.0 on the title's year), while a drone video
    naming the subject and the year still ranks first for place lines.
    """
    title, chan = c.get("title") or "", c.get("channel") or ""
    on_topic = sum(w in title.lower() for w in words) / max(1, len(words))
    # media._score_candidate carries the eyewitness preference too
    # (media.eyewitness_bonus: phone, drone, chaser, helicopter titles; a
    # compilation behind) when the style asks for it.
    score = media._score_candidate(title, c.get("duration") or 0,
                                   c.get("aspect") or 0, 7.0) + 2.0 * on_topic
    if not (story and story.get("is_event")):
        return None if on_topic == 0 else score
    if c.get("_news"):
        score += NEWS_TITLE_BONUS
    if via == "channel":
        score += 1.5
    topic = _event_words(story.get("event") or "", " ".join(words)).lower().split()
    hits = sum(w in title.lower() for w in topic)
    if topic:
        score += 1.5 * min(1.0, hits / len(topic))        # names the EXACT event
    years = _YEAR.findall(title)
    if story.get("year"):
        if str(story["year"]) in years:
            score += 1.0
        elif years:
            score -= 2.0                  # another year's shoreline / another flood
    if on_topic == 0 and hits == 0:
        return None                       # neither the subject nor the event
    # A story about now: the last month's uploads first, the event's own
    # word ("flooding") ahead of a title that names only the place.
    if c.get("_recent"):
        score += RECENT_BONUS
    if story.get("word") and _names_word(title, story["word"]):
        score += 1.0
    return score


def candidates(subject: str, require_cc: bool, skip_ids: Set[str],
               story: Optional[dict] = None) -> List[dict]:
    """
    On-subject videos, best first.

    `story` (subject_story) turns the news searches, the NEWS_CHANNELS lookup,
    the shorter NEWS_MIN_SECONDS floor for news titles and the news ranking
    on; without it the pool is the two generic searches ranked as before.
    Every row records "_news" (title reads as a report) and "_via"
    ("search" or "channel") for the stats and the per-video cap, and "_recent"
    when a last-month search returned it (a story about now ranks those first).
    """
    event = bool(story and story.get("is_event"))
    channels = _uses_channels(story, require_cc)
    limit = POOL_SEARCHES_MAX - (1 if channels else 0)
    words = [w for w in subject_key(subject).split() if len(w) > 2]
    rows: List[tuple] = []
    recent_ids: Set[str] = set()
    for q, variant, recency in _searches(subject, story, limit):
        target = _target(q, require_cc, recency)
        for c in media._yt_candidates_cached(target, require_cc, subject_key(subject),
                                             variant=f"pool:{variant}:{recency}"):
            rows.append((c, "search"))
            if recency in _YT_RECENT and not require_cc:
                recent_ids.add(c.get("id") or "")
    if channels:
        for c in media._channel_candidates(subject, config.NEWS_CHANNELS, subject):
            rows.append((c, "channel"))
    # A video the channel lookup also found is credited as the channel's.
    from_channel = {c.get("id") for c, via in rows if via == "channel"}
    seen, out = set(), []
    for c, via in rows:
        vid = c.get("id") or ""
        if not vid or vid in seen or vid in skip_ids:
            continue
        seen.add(vid)
        title, chan = c.get("title") or "", c.get("channel") or ""
        if not media._usable_title(title, chan, c.get("aspect") or 0.0):
            continue
        if media.title_conflict(title, subject):
            continue                    # another state, storm, kind of weather or year (the Texas test)
        news = event and _news_title(title, chan)
        floor = NEWS_MIN_SECONDS if news else 60
        if c.get("duration") and c["duration"] < floor:
            continue
        c["_news"] = news
        c["_via"] = "channel" if vid in from_channel else via
        c["_recent"] = vid in recent_ids
        rank = _rank(c, words, story, c["_via"])
        if rank is None:
            continue
        c["_rank"] = rank
        out.append(c)
    return sorted(out, key=lambda c: c["_rank"], reverse=True)


def pool_intent(subject: str, story: Optional[dict]) -> str:
    """
    What rate_tiles is told to look for in an event story's videos: the
    field footage, aerials and interviewees OF the news reports, not the
    anchor desk. Empty outside event stories (the subject alone, as before).
    """
    if not (story and story.get("is_event")):
        return ""
    when = f" ({story['year']})" if story.get("year") else ""
    event = story.get("event") or "the event"
    return (f"{subject} in the {event}{when} story, taken FROM NEWS REPORTS of it: field footage, "
            f"aerials and the place as it is now, and the people the report shows speaking about "
            f"{subject} (officials, experts, residents in interviews or press conferences). "
            f"Not the studio anchor desk, a title card or a graphic.")


def rate_video(cand: dict, subject: str, context: str, seconds: float,
               intent: str = "", place: bool = False) -> List[dict]:
    """
    Approved moments of one video: [{"start", "score", "description"}].

    A moment near the end is pulled back so its `seconds` fit inside the
    video: news reports are short, and a tile at 0:52 of a 58 s report made a
    7.5 s cut that ran out of video.
    """
    info, proxy = media._yt_info(cand["id"])
    if not info:
        return []
    # A place subject (a landmark, a dam) may use the last few years' uploads.
    why = (media.upload_conflict(info, older_ok_years=config.PLACE_FOOTAGE_YEARS if place else 0)
           or media.title_conflict(info.get("title") or "", subject))
    if why:
        print(f"[pools] {subject}: skip {cand['id']}: {why}", flush=True)
        return []
    made = moments.contact_sheet(info, seconds, proxy, config.MOMENT_TILES)
    if not made:
        return []
    sheet, times = made
    # A pool's approved moments go to the timeline without the judge unless POOL_JUDGE_CLIPS:
    # only then may the cheaper storyboard model (VISION_TILE_MODEL) rate them.
    rated = vision.rate_tiles(sheet, len(times), subject, context, intent=intent,
                              checked=bool(config.POOL_JUDGE_CLIPS)) or []
    duration = float(info.get("duration") or 0)
    out = []
    for r in rated:
        if r["score"] < config.VISION_MIN_SCORE:
            continue
        start = max(0.0, times[r["tile"] - 1] - 0.5)
        if duration:
            start = min(start, max(0.0, duration - seconds - 0.5))
        out.append({"start": start, "score": r["score"], "description": r["description"]})
    return out


def moment_key(video_id: str, start: float) -> str:
    """
    One key per distinct moment of a video: "yt:<id>@<bucket>", the bucket
    being POOL_MIN_GAP_SECONDS wide - the same spacing `spaced` keeps, so two
    approved moments never share a key and get silently dropped (they did
    when the bucket was 10 s and the spacing 8 s).
    """
    gap = max(1.0, float(config.POOL_MIN_GAP_SECONDS))
    return f"yt:{video_id}@{int(start // gap)}"


def spaced(found: List[dict], gap: float) -> List[dict]:
    """Moments of one video at least `gap` seconds apart, in time order."""
    kept: List[dict] = []
    for m in sorted(found, key=lambda m: m["start"]):
        if not kept or m["start"] - kept[-1]["start"] >= gap:
            kept.append(m)
        elif m["score"] > kept[-1]["score"]:
            kept[-1] = m
    return kept


def _video_of(cand: dict) -> str:
    """A pool candidate's source video as media.video_key names it ("yt:<id>"), library clips included."""
    vid = str(cand.get("id") or "")
    m = re.search(r"yt:([\w-]{11})", vid)
    if m:
        return f"yt:{m.group(1)}"
    return f"yt:{vid}" if re.fullmatch(r"[\w-]{11}", vid) else vid


def _start_of(job: dict) -> Optional[float]:
    at = job.get("start")
    return float(at) if isinstance(at, (int, float)) and not isinstance(at, bool) else None


class _Slots:
    """
    Where each source video already plays on the timeline, shared by every
    subject's pool of one job (they run in parallel): take() admits one more
    line only under the variety rules (media.may_place - MAX_MOMENTS_PER_VIDEO
    lines per video, SAME_VIDEO_GAP_SECONDS apart). The owner's Texas flood
    video (2026-09-30) played four moments of one drone video in a minute.
    """

    def __init__(self, placed: Optional[Dict[str, List[Optional[float]]]] = None):
        self.at: Dict[str, List[Optional[float]]] = {k: list(v) for k, v in (placed or {}).items()}
        self.lock = threading.Lock()

    def take(self, video: str, at: Optional[float]) -> bool:
        with self.lock:
            prev = self.at.setdefault(video, [])
            if not media.may_place(prev, at):
                return False
            prev.append(at)
            return True

    def release(self, video: str, at: Optional[float]) -> None:
        """A line's moment of `video` did not arrive: the video may supply that place again."""
        with self.lock:
            prev = self.at.get(video) or []
            if at in prev:
                prev.remove(at)


def _per_video(story: dict) -> Optional[int]:
    """How many of one video's approved moments a pool keeps (its best, in time order)."""
    cap = config.MAX_MOMENTS_PER_VIDEO
    if cap > 0:
        return min(cap, NEWS_MAX_MOMENTS_PER_VIDEO) if story["is_event"] else cap
    return NEWS_MAX_MOMENTS_PER_VIDEO if story["is_event"] else None


def plan_subject(subject: str, sjobs: List[dict], require_cc: bool, skip_ids: Set[str],
                 claim: Callable[[str], bool], library=None, work: str = "",
                 slots: Optional[_Slots] = None) -> tuple:
    """
    ([(job, candidate, moment)] for the subject's lines, spare (candidate, moment)s).

    Clips the library already holds for the subject come first (no search,
    no download from YouTube, no vision call); YouTube supplies the rest.
    Spares are approved moments no line took; fill_from_reserve hands them to
    lines that ended up empty or repeated.

    Each video keeps its best few moments (_per_video) and each line, in
    story order, takes a moment from the first video in rank order that may
    still supply a line there (`slots`, shared by the job's subjects). Until
    the owner's review (2026-09-30) consecutive lines took consecutive moments
    of one video - on screen, one shot four times in a minute. A line no rated
    video may take is left to per-scene sourcing.
    """
    need = len(sjobs)
    seconds = max(j.get("seconds") or 6.0 for j in sjobs) + media.SEQ_SHOT_PAD
    story = subject_story(sjobs)
    intent = pool_intent(subject, story)
    context = " ".join((j.get("context") or "") for j in sjobs[:6])
    # A named place that is not the event itself (Cathedral in the Desert in a
    # Lake Powell story) may use the last few years' uploads.
    place = place_subject(subject, sjobs)
    # Several reports, a few moments each (GoMotion), rather than every line
    # from the first long video that clears the floor.
    per_video = _per_video(story)
    slots = slots if slots is not None else _Slots()
    open_lines = list(sjobs)
    assigned: Dict[int, tuple] = {}
    available: List[tuple] = []          # claimed moments no line has taken yet

    def assign() -> None:
        for job in list(open_lines):
            for cm in available:
                if slots.take(_video_of(cm[0]), _start_of(job)):
                    assigned[job["index"]] = cm
                    available.remove(cm)
                    open_lines.remove(job)
                    break

    if library is not None and need:
        reused = 0
        for entry in library.find(subject, n=need):
            if not claim(entry["id"]):
                continue
            available.append(({"id": entry["id"], "title": entry.get("attribution", ""), "_library": entry},
                              {"start": 0.0, "score": entry.get("relevance"),
                               "description": entry.get("description", "")}))
            reused += 1
        if reused:
            print(f"[library] {subject}: {reused} clip(s) reused", flush=True)
        assign()
    ranked = candidates(subject, require_cc, skip_ids, story=story)[:config.POOL_MAX_VIDEOS]
    step = max(1, int(config.POOL_RATE_PARALLEL))
    for b in range(0, len(ranked), step):
        if not open_lines or ytdlp.past_deadline():
            break
        # A few videos rated at once (a metadata read, a storyboard and one
        # vision call each): one at a time, a subject that needed its eighth
        # video waited for seven in a row. Moments are still handed out in
        # rank order, video by video, as before.
        batch = ranked[b:b + step]
        if len(batch) == 1:
            rated = [rate_video(batch[0], subject, context, seconds, intent=intent, place=place)]
        else:
            with ThreadPoolExecutor(max_workers=len(batch)) as ex:
                rated = list(ex.map(lambda c: rate_video(c, subject, context, seconds, intent=intent,
                                                         place=place), batch))
        for cand, got in zip(batch, rated):
            found = spaced(got, config.POOL_MIN_GAP_SECONDS)
            # Never a moment an earlier video showed (src/ledger.py); the
            # video's other moments stay.
            found = [m for m in found if not ledger.moment_used(cand["id"], m["start"], m["start"] + seconds)]
            if per_video and len(found) > per_video:
                # The best-scored few of this video, back in time order.
                found = sorted(sorted(found, key=lambda m: -m["score"])[:per_video],
                               key=lambda m: m["start"])
            took = 0
            for m in found:
                if claim(moment_key(cand["id"], m["start"])):
                    available.append((cand, m))
                    took += 1
            if took:
                cand["_used"] = took
            assign()
    plan = [(job, *assigned[job["index"]]) for job in sjobs if job["index"] in assigned]
    return plan, available


# Spare approved moments of this job's pools: (subject key, candidate, moment).
_RESERVE: List[tuple] = []
_RESERVE_LOCK = threading.Lock()
# What each pool was about (subject key -> {"name", "scene_intent", "event_window",
# "seconds"}), so the clip library can keep the spares no line took.
_RESERVE_META: Dict[str, dict] = {}


def spare_moments(limit: int = 0) -> List[dict]:
    """
    The pools' approved moments no line took, best first, for the clip
    library (library.record_from_doc keeps them instead of the clips the
    video showed): [{"key", "name", "cand", "moment", "meta"}]. The reserve
    itself is left as it is.
    """
    with _RESERVE_LOCK:
        spare = list(_RESERVE)
        meta = dict(_RESERVE_META)
    out = [{"key": k, "name": (meta.get(k) or {}).get("name") or k, "cand": c, "moment": m,
            "meta": meta.get(k) or {}} for k, c, m in spare if c.get("_library") is None]
    out.sort(key=lambda s: -float(s["moment"].get("score") or 0.0))
    return out[:limit] if limit else out


def _same_pool(pool_key: str, key: str) -> bool:
    """A spare of pool `pool_key` is about the line's own subject or place (one names the other)."""
    if not key or not pool_key:
        return False
    a, b = set(pool_key.split()), set(key.split())
    return pool_key == key or a <= b or b <= a


def _spare_shot(cand: dict, m: dict, at: Optional[float]):
    """A spare moment as gapfill.Shot (the no-repeat rules)."""
    from . import gapfill
    vid = _video_of(cand)
    if cand.get("_library") is not None:
        e = cand["_library"]
        video = gapfill._video_of(str(e.get("id") or ""), e.get("url") or "")
        return gapfill.Shot(video=video, start=gapfill._start_from(None, e.get("url") or "", ""), at=at,
                            ident="" if video else str(e.get("id") or ""))
    if vid.startswith("yt:"):
        return gapfill.Shot(video=vid, start=float(m.get("start") or 0.0), at=at)
    return gapfill.Shot(ident=vid, at=at)


def fill_from_reserve(jobs: List[dict], indices: List[int], work: str,
                      require_cc: bool = False, assets=None, library=None) -> Dict[int, media.MediaAsset]:
    """
    Real, distinct footage for lines left empty or repeated, from the pools'
    spare moments - the line's own subject first, then any story subject.

    The owner's review (2026-09-30): a spare is only placed where its video
    may still supply a line (media.may_place over `assets`, the lines' current
    assets as a list by index or a dict, the lines being refilled not
    counted), and a line that names its own place (job "place") only takes a
    spare of that place - a Dallas line never gets the Houston pool's shot.
    And never a repeat (the owner, 2026-10-01): not a moment another line
    shows, nor one of its video under FALLBACK_MOMENT_GAP_SECONDS from it, nor
    its video on the next line (gapfill.Used).
    """
    from . import gapfill
    by_index = {j["index"]: j for j in jobs}
    starts = media.scene_starts(jobs)
    slots = _Slots(media.placements(assets, starts, skip=set(indices)) if assets is not None else None)
    keep = {i: a for i, a in (assets.items() if isinstance(assets, dict) else enumerate(assets or []))
            if a is not None and i not in set(indices)}
    used = gapfill.Used.of_results(keep, starts)
    with _RESERVE_LOCK:
        spare = list(_RESERVE)
        _RESERVE.clear()
    out: Dict[int, media.MediaAsset] = {}
    for i in sorted(indices):
        job = by_index.get(i)
        if job is None or not spare or media.is_chain(job):
            continue                    # a chain line continues the clip before it (media.fill_chains)
        key = subject_key(_pool_name(job))
        own = [s for s in spare if _same_pool(s[0], key)]
        others = [] if job.get("place") else [s for s in spare if not _same_pool(s[0], key)]
        pick = next((s for s in own + others
                     if not used.why_not(i, _spare_shot(s[1], s[2], starts.get(i)))
                     and slots.take(_video_of(s[1]), starts.get(i))), None)
        if pick is None:
            continue
        spare.remove(pick)
        asset = _fetch(job, pick[1], pick[2], work, require_cc, _pool_name(job) or pick[0], library=library)
        if asset is not None:
            out[i] = asset
            used.add(i, gapfill.Shot.of_asset(asset, starts.get(i)))
    with _RESERVE_LOCK:
        _RESERVE.extend(spare)
    return out


def take_spare(job: dict, ok: Callable[[dict, dict], bool],
               prefer: Optional[Callable[[dict, dict], bool]] = None) -> Optional[tuple]:
    """
    Take one spare moment for `job` off the reserve: the line's own subject or
    place first, then (a line that names no place of its own) any subject's;
    only one `ok(cand, moment)` accepts, and among those one `prefer` likes
    first. (key, cand, moment), or None. put_back() returns it unused.
    """
    key = subject_key(_pool_name(job))
    with _RESERVE_LOCK:
        own = [s for s in _RESERVE if _same_pool(s[0], key)]
        others = [] if job.get("place") else [s for s in _RESERVE if not _same_pool(s[0], key)]
        fine = [s for s in own + others if ok(s[1], s[2])]
        best = [s for s in fine if prefer is None or prefer(s[1], s[2])]
        pick = (best or fine or [None])[0]
        if pick is not None:
            _RESERVE.remove(pick)
        return pick


def put_back(spare: tuple) -> None:
    with _RESERVE_LOCK:
        _RESERVE.append(spare)


def _fetch(job: dict, cand: dict, m: dict, work: str, require_cc: bool,
           subject: str, library=None) -> Optional[media.MediaAsset]:
    seconds = (job.get("seconds") or 6.0) + media.SEQ_SHOT_PAD
    if cand.get("_library") is not None and library is not None:
        return library.fetch(cand["_library"], work, seconds, job)
    path, clean, cuts = media.fetch_clean_clip(cand["id"], work, m["start"], seconds,
                                               cand.get("title", ""))
    if not path or media.has_burned_captions(path) or media.motion_rejects(path):
        return None
    # An upscaled upload (src/sharpness.py): soft in every moment, whatever its file says.
    soft = media.clip_detail_reason(path, cand.get("title", ""))
    if soft:
        print(f"[pools] {subject}: dropped {cand['id']} @ {m['start']:.0f}s: {soft}", flush=True)
        try:
            os.remove(path)
        except OSError:
            pass
        return None
    # A pooled moment is rated on storyboard tiles only, where a chyron naming
    # another town cannot be read: the AI-slop and not-footage filters look at
    # the real frames (src/slop.py), and with POOL_JUDGE_CLIPS (the news and
    # weather styles) the vision judge checks the clip against the line.
    verdict = None
    if config.POOL_JUDGE_CLIPS:
        keep, verdict = media.judge_clip(path, job, cand.get("title", ""))
        why = "" if keep else "turned down by the judge"
    else:
        why = media.slop_reason(path, cand.get("title", ""))
    if why:
        print(f"[pools] {subject}: dropped {cand['id']} @ {m['start']:.0f}s: {why}", flush=True)
        try:
            os.remove(path)
        except OSError:
            pass
        return None
    return media.MediaAsset(
        kind="video", source="youtube",
        url=f"https://www.youtube.com/watch?v={cand['id']}&t={int(m['start'])}",
        local_path=path, duration=seconds,
        attribution=f"YouTube: {cand.get('title', '')}",
        license=("Creative Commons Attribution (CC BY)" if require_cc
                 else "unverified — you must hold the rights"),
        query=subject, intent=job.get("intent") or subject,
        review_required=not require_cc,
        review_reason="" if require_cc else "Licence unverified — confirm you hold the rights",
        content_description=(verdict or {}).get("description") or m.get("description", ""),
        relevance_score=(verdict or {}).get("score", m.get("score")),
        quality=(verdict or {}).get("quality"),
        moment_key=moment_key(cand["id"], m["start"]),
        moment={"start": round(float(m["start"]), 1), "score": m.get("score"), "fine": False,
                "clean": clean, "cuts": cuts})


def retry_failed(got: List[tuple], plan: List[tuple], spare: List[tuple], slots: "_Slots", work: str,
                 require_cc: bool, subject: str, library=None, stats: Optional[dict] = None,
                 lock: Optional[threading.Lock] = None) -> List[tuple]:
    """
    [(job, asset)] with each line whose pooled moment failed - no download,
    burned-in text, a still, AI-made - given another of its subject's approved
    moments (`spare`, under the same variety rules) at once, up to
    POOL_RETRY_MOMENTS each. Before, such a line fell to the per-scene search
    (a search, scouts, downloads and several vision calls), with this pool's
    other approved moments sitting unused until the reserve pass.
    `spare` loses the moments used; `plan` is [(job, cand, moment)] in `got`'s order.
    """
    tries = max(0, int(config.POOL_RETRY_MOMENTS))
    failed = [(job, cand) for (job, asset), (_j, cand, _m) in zip(got, plan) if asset is None]
    if not failed or not spare or not tries:
        return got
    pick_lock = threading.Lock()
    for job, cand in failed:
        slots.release(_video_of(cand), _start_of(job))       # that moment never arrived

    def one(job: dict) -> Optional[media.MediaAsset]:
        for _ in range(tries):
            if ytdlp.past_deadline():
                return None
            with pick_lock:
                pick = next((cm for cm in spare if slots.take(_video_of(cm[0]), _start_of(job))), None)
                if pick is None:
                    return None
                spare.remove(pick)
            asset = _fetch(job, pick[0], pick[1], work, require_cc, subject, library=library)
            if asset is not None:
                return asset
            slots.release(_video_of(pick[0]), _start_of(job))
        return None
    with ThreadPoolExecutor(max_workers=max(1, min(6, len(failed)))) as ex:
        again = dict(zip((j["index"] for j, _c in failed), ex.map(one, [j for j, _c in failed])))
    filled = sum(1 for a in again.values() if a is not None)
    if stats is not None:
        with (lock or threading.Lock()):
            stats["retried"] = stats.get("retried", 0) + len(failed)
            stats["retry_filled"] = stats.get("retry_filled", 0) + filled
    if filled:
        print(f"[pools] {subject}: {filled}/{len(failed)} failed line(s) took another approved moment",
              flush=True)
    return [(job, asset if asset is not None else again.get(job["index"])) for job, asset in got]


def source_by_subject(jobs: List[dict], work: str, *, require_cc: bool = False,
                      report: Optional[Callable] = None,
                      min_scenes: Optional[int] = None, library=None) -> Dict[int, media.MediaAsset]:
    """{job index: asset} for every line a subject pool covered."""
    need_min = config.POOL_MIN_SCENES if min_scenes is None else min_scenes
    todo = {k: v for k, v in groups(jobs).items() if len(v) >= need_min}
    results: Dict[int, media.MediaAsset] = {}
    if work:
        media._WORK["dir"] = work                # for the passes that run without one (media.fill_chains)
    with _RESERVE_LOCK:
        _RESERVE.clear()
        _RESERVE_META.clear()
    if not todo:
        return results
    lock = threading.Lock()
    claimed: Set[str] = set()
    # One ledger of where each video plays, for every subject: two subjects'
    # searches often return the same report (the owner, 2026-09-30).
    slots = _Slots()
    done = [0]
    stats = {"subjects": len(todo), "lines": sum(len(v) for v in todo.values()), "covered": 0,
             "news_videos": 0}

    def claim(key: str) -> bool:
        with lock:
            if key in claimed:
                return False
            claimed.add(key)
            return True

    def one(key: str) -> None:
        sjobs = todo[key]
        name = display_name(sjobs)
        if ytdlp.past_deadline():
            # Sourcing time is spent: the lines go to what is already found.
            print(f"[pools] {name}: skipped, sourcing time spent", flush=True)
            return
        videos = news = 0
        try:
            plan, spare = plan_subject(name, sjobs, require_cc, set(), claim, library=library, work=work,
                                       slots=slots)
            used = {c["id"]: c for _, c, _ in plan if c.get("id")}
            videos = len(used)
            news = sum(1 for c in used.values() if c.get("_news"))
            with ThreadPoolExecutor(max_workers=6) as ex:
                got = list(ex.map(lambda p: (p[0], _fetch(p[0], p[1], p[2], work, require_cc, name,
                                                          library=library)),
                                  plan))
            got = retry_failed(got, plan, spare, slots, work, require_cc, name, library=library, stats=stats,
                               lock=lock)
            with _RESERVE_LOCK:
                _RESERVE.extend((key, c, m) for c, m in spare)
                first = sjobs[0] if sjobs else {}
                _RESERVE_META[key] = {"name": name, "scene_intent": first.get("scene_intent") or None,
                                      "event_window": first.get("event_window") or "",
                                      "seconds": max(float(j.get("seconds") or 6.0) for j in sjobs)
                                      + media.SEQ_SHOT_PAD if sjobs else 6.5}
        except Exception as e:  # noqa: BLE001 - its lines fall back to per-scene sourcing
            print(f"[pools] {name}: {type(e).__name__}: {e}", flush=True)
            got = []
        with lock:
            for job, asset in got:
                if asset is not None:
                    results[job["index"]] = asset
            done[0] += 1
            covered = sum(1 for _, a in got if a is not None)
            stats["covered"] += covered
            stats["news_videos"] += news
            print(f"[pools] {name}: {covered}/{len(sjobs)} lines from its pool "
                  f"({videos} videos, {news} news reports)", flush=True)
            if report:
                report(f"Finding footage by subject {done[0]}/{len(todo)}", 22 + int(8 * done[0] / len(todo)),
                       done=len(results), total=len(jobs))

    with ThreadPoolExecutor(max_workers=max(1, config.POOL_PARALLEL_SUBJECTS)) as ex:
        list(ex.map(one, sorted(todo, key=lambda k: -len(todo[k]))))
    media.LAST_STATS["pools"] = stats
    return results


def video_ids(assets: Dict[int, media.MediaAsset]) -> Set[str]:
    """"yt:<id>" of every pool video, so per-scene sourcing picks other uploads."""
    out = set()
    for a in assets.values():
        m = re.search(r"[?&]v=([\w-]{11})", a.url or "")
        if m:
            out.add(f"yt:{m.group(1)}")
    return out
