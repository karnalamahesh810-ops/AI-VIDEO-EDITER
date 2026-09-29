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
same video can supply many shots, the same moment never appears twice. Lines
with no subject, people (their footage and photos need the per-scene rules),
stills, and subjects whose pool runs dry are left to the per-scene path.
"""
from __future__ import annotations

import datetime
import re
import threading
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional, Set

from . import config, media, moments, vision, ytdlp

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
    {kind, event, year, window, is_event} for one subject's lines.

    Read from what already travels with the jobs (event_window and
    scene_intent are copied into every fan-out part) and the story kind
    media.set_story_kind records on every worker, so a part behaves like the
    parent. is_event only ever with config.NEWS_FOOTAGE: off, the pools search
    exactly as before.
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
    return {"kind": kind, "event": event, "year": year, "window": window, "is_event": is_event}


def _event_words(event: str, subject: str) -> str:
    """'2026 Colorado River water cuts' for subject 'Colorado River' -> 'water cuts'."""
    skip = set(subject_key(subject).split())
    return " ".join(w for w in event.split()
                    if subject_key(w) and subject_key(w) not in skip and not _YEAR.fullmatch(w))


def subject_key(subject: str) -> str:
    """"Page, Arizona" and "Page Arizona" are one subject."""
    text = _ARTICLES.sub(" ", _PUNCT.sub(" ", (subject or "").lower()))
    return " ".join(text.split())


def groups(jobs: List[dict]) -> Dict[str, List[dict]]:
    """
    Footage lines grouped by subject, in story order (key -> jobs).

    People stay on the per-scene path: its judge is called with allow_people
    for a person subject (media._vision_gate -> vision.acceptable), whereas
    rate_tiles has no such switch; their interview searches come from
    director.news_queries. Places and things (two thirds of GoMotion's clips)
    are pooled here, from news reports and drone videos.
    """
    out: Dict[str, List[dict]] = {}
    for job in sorted(jobs, key=lambda j: j["index"]):
        if job.get("visual_type", "footage") != "footage":
            continue
        if job.get("subject_type") == "person":
            continue
        key = subject_key(job.get("subject") or "")
        if key:
            out.setdefault(key, []).append(job)
    return out


def display_name(jobs: List[dict]) -> str:
    return Counter((j.get("subject") or "").strip() for j in jobs).most_common(1)[0][0]


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


def _target(query: str, require_cc: bool, recency: str) -> str:
    """The yt-dlp target: the CC results page, this year's uploads, or a flat search."""
    if require_cc:
        return ("https://www.youtube.com/results?search_query="
                + urllib.parse.quote_plus(query) + "&sp=EgIwAQ%3D%3D")
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
    return score


def candidates(subject: str, require_cc: bool, skip_ids: Set[str],
               story: Optional[dict] = None) -> List[dict]:
    """
    On-subject videos, best first.

    `story` (subject_story) turns the news searches, the NEWS_CHANNELS lookup,
    the shorter NEWS_MIN_SECONDS floor for news titles and the news ranking
    on; without it the pool is the two generic searches ranked as before.
    Every row records "_news" (title reads as a report) and "_via"
    ("search" or "channel") for the stats and the per-video cap.
    """
    event = bool(story and story.get("is_event"))
    channels = _uses_channels(story, require_cc)
    limit = POOL_SEARCHES_MAX - (1 if channels else 0)
    words = [w for w in subject_key(subject).split() if len(w) > 2]
    rows: List[tuple] = []
    for q, variant, recency in _searches(subject, story, limit):
        target = _target(q, require_cc, recency)
        for c in media._yt_candidates_cached(target, require_cc, subject_key(subject),
                                             variant=f"pool:{variant}:{recency}"):
            rows.append((c, "search"))
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
        news = event and _news_title(title, chan)
        floor = NEWS_MIN_SECONDS if news else 60
        if c.get("duration") and c["duration"] < floor:
            continue
        c["_news"] = news
        c["_via"] = "channel" if vid in from_channel else via
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
               intent: str = "") -> List[dict]:
    """
    Approved moments of one video: [{"start", "score", "description"}].

    A moment near the end is pulled back so its `seconds` fit inside the
    video: news reports are short, and a tile at 0:52 of a 58 s report made a
    7.5 s cut that ran out of video.
    """
    info, proxy = media._yt_info(cand["id"])
    if not info:
        return []
    made = moments.contact_sheet(info, seconds, proxy, config.MOMENT_TILES)
    if not made:
        return []
    sheet, times = made
    rated = vision.rate_tiles(sheet, len(times), subject, context, intent=intent) or []
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


def plan_subject(subject: str, sjobs: List[dict], require_cc: bool, skip_ids: Set[str],
                 claim: Callable[[str], bool], library=None, work: str = "") -> tuple:
    """
    ([(job, candidate, moment)] for the subject's lines, spare (candidate, moment)s).

    Clips the library already holds for the subject come first (no search,
    no download from YouTube, no vision call); YouTube supplies the rest.
    Spares are approved moments beyond what the lines need; fill_from_reserve
    hands them to lines that ended up empty or repeated.
    """
    need = len(sjobs)
    seconds = max(j.get("seconds") or 6.0 for j in sjobs) + media.SEQ_SHOT_PAD
    story = subject_story(sjobs)
    intent = pool_intent(subject, story)
    context = " ".join((j.get("context") or "") for j in sjobs[:6])
    # Several reports, a few moments each (GoMotion), rather than every line
    # from the first long video that clears the floor.
    per_video = NEWS_MAX_MOMENTS_PER_VIDEO if story["is_event"] else None
    pool: List[tuple] = []
    if library is not None and need:
        for entry in library.find(subject, n=need):
            if not claim(entry["id"]):
                continue
            pool.append(({"id": entry["id"], "title": entry.get("attribution", ""), "_library": entry},
                         {"start": 0.0, "score": entry.get("relevance"),
                          "description": entry.get("description", "")}))
        if pool:
            print(f"[library] {subject}: {len(pool)} clip(s) reused", flush=True)
    for cand in candidates(subject, require_cc, skip_ids, story=story)[:config.POOL_MAX_VIDEOS]:
        if len(pool) >= need or ytdlp.past_deadline():
            break
        found = spaced(rate_video(cand, subject, context, seconds, intent=intent),
                       config.POOL_MIN_GAP_SECONDS)
        if per_video and len(found) > per_video:
            # The best-scored few of this report, back in time order.
            found = sorted(sorted(found, key=lambda m: -m["score"])[:per_video],
                           key=lambda m: m["start"])
        took = 0
        for m in found:
            if claim(moment_key(cand["id"], m["start"])):
                pool.append((cand, m))
                took += 1
        if took:
            cand["_used"] = took
        if len(pool) >= need:
            break
    # Story order: consecutive lines take consecutive moments of one video.
    return [(job, cand, m) for job, (cand, m) in zip(sjobs, pool)], pool[need:]


# Spare approved moments of this job's pools: (subject key, candidate, moment).
_RESERVE: List[tuple] = []
_RESERVE_LOCK = threading.Lock()


def fill_from_reserve(jobs: List[dict], indices: List[int], work: str,
                      require_cc: bool = False) -> Dict[int, media.MediaAsset]:
    """
    Real, distinct footage for lines left empty or repeated, from the pools'
    spare moments - the line's own subject first, then any story subject.
    """
    by_index = {j["index"]: j for j in jobs}
    with _RESERVE_LOCK:
        spare = list(_RESERVE)
        _RESERVE.clear()
    out: Dict[int, media.MediaAsset] = {}
    for i in sorted(indices):
        job = by_index.get(i)
        if job is None or not spare:
            continue
        key = subject_key(job.get("subject") or "")
        pick = next((s for s in spare if s[0] == key), None) or spare[0]
        spare.remove(pick)
        asset = _fetch(job, pick[1], pick[2], work, require_cc, job.get("subject") or pick[0])
        if asset is not None:
            out[i] = asset
    with _RESERVE_LOCK:
        _RESERVE.extend(spare)
    return out


def _fetch(job: dict, cand: dict, m: dict, work: str, require_cc: bool,
           subject: str, library=None) -> Optional[media.MediaAsset]:
    seconds = (job.get("seconds") or 6.0) + media.SEQ_SHOT_PAD
    if cand.get("_library") is not None and library is not None:
        return library.fetch(cand["_library"], work, seconds, job)
    path, clean, cuts = media.fetch_clean_clip(cand["id"], work, m["start"], seconds,
                                               cand.get("title", ""))
    if not path or media.has_burned_captions(path):
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
        content_description=m.get("description", ""),
        relevance_score=m.get("score"),
        moment_key=moment_key(cand["id"], m["start"]),
        moment={"start": round(float(m["start"]), 1), "score": m.get("score"), "fine": False,
                "clean": clean, "cuts": cuts})


def source_by_subject(jobs: List[dict], work: str, *, require_cc: bool = False,
                      report: Optional[Callable] = None,
                      min_scenes: Optional[int] = None, library=None) -> Dict[int, media.MediaAsset]:
    """{job index: asset} for every line a subject pool covered."""
    need_min = config.POOL_MIN_SCENES if min_scenes is None else min_scenes
    todo = {k: v for k, v in groups(jobs).items() if len(v) >= need_min}
    results: Dict[int, media.MediaAsset] = {}
    with _RESERVE_LOCK:
        _RESERVE.clear()
    if not todo:
        return results
    lock = threading.Lock()
    claimed: Set[str] = set()
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
            plan, spare = plan_subject(name, sjobs, require_cc, set(), claim, library=library, work=work)
            used = {c["id"]: c for _, c, _ in plan if c.get("id")}
            videos = len(used)
            news = sum(1 for c in used.values() if c.get("_news"))
            with ThreadPoolExecutor(max_workers=6) as ex:
                got = list(ex.map(lambda p: (p[0], _fetch(p[0], p[1], p[2], work, require_cc, name,
                                                          library=library)),
                                  plan))
            with _RESERVE_LOCK:
                _RESERVE.extend((key, c, m) for c, m in spare)
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
