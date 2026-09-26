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
     documentary footage"), filtered like every other candidate list;
  2. for the best few videos, one storyboard contact sheet each and ONE
     vision call rating every tile against the subject (vision.rate_tiles);
  3. the approved moments, at least POOL_MIN_GAP_SECONDS apart, are handed to
     the subject's lines in story order, so consecutive lines about one thing
     play consecutive moments of one video;
  4. each moment is downloaded as its own short section.

A moment is identified as video + 10 s bucket (MediaAsset.moment_key): the
same video can supply many shots, the same moment never appears twice. Lines
with no subject, people (their footage and photos need the per-scene rules),
stills, and subjects whose pool runs dry are left to the per-scene path.
"""
from __future__ import annotations

import re
import threading
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional, Set

from . import config, media, moments, vision

_PUNCT = re.compile(r"[^a-z0-9 ]+")
_ARTICLES = re.compile(r"\b(the|a|an)\b")


def subject_key(subject: str) -> str:
    """"Page, Arizona" and "Page Arizona" are one subject."""
    text = _ARTICLES.sub(" ", _PUNCT.sub(" ", (subject or "").lower()))
    return " ".join(text.split())


def groups(jobs: List[dict]) -> Dict[str, List[dict]]:
    """Footage lines grouped by subject, in story order (key -> jobs)."""
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


def _searches(subject: str) -> List[str]:
    return [f"{subject} aerial drone footage 4k", f"{subject} documentary footage"]


def candidates(subject: str, require_cc: bool, skip_ids: Set[str]) -> List[dict]:
    """On-subject long videos, best first."""
    seen, out = set(), []
    words = [w for w in subject_key(subject).split() if len(w) > 2]
    for q in _searches(subject):
        target = f"ytsearch15:{q}"
        if require_cc:
            target = ("https://www.youtube.com/results?search_query="
                      + urllib.parse.quote_plus(q) + "&sp=EgIwAQ%3D%3D")
        for c in media._yt_candidates_cached(target, require_cc, "", variant=f"pool:{q}"):
            vid = c.get("id") or ""
            if not vid or vid in seen or vid in skip_ids:
                continue
            seen.add(vid)
            title = c.get("title") or ""
            if media._talking_head(title) or media._stock_seller(title, c.get("channel", "")):
                continue
            if c.get("aspect") and c["aspect"] < 1.2:
                continue
            if c.get("duration") and c["duration"] < 60:
                continue
            on_topic = sum(w in title.lower() for w in words) / max(1, len(words))
            c["_rank"] = media._score_candidate(title, c.get("duration") or 0,
                                                c.get("aspect") or 0, 7.0) + 2.0 * on_topic
            out.append(c)
    return sorted(out, key=lambda c: c["_rank"], reverse=True)


def rate_video(cand: dict, subject: str, context: str, seconds: float) -> List[dict]:
    """Approved moments of one video: [{"start", "score", "description"}]."""
    info, proxy = media._yt_info(cand["id"])
    if not info:
        return []
    made = moments.contact_sheet(info, seconds, proxy, config.MOMENT_TILES)
    if not made:
        return []
    sheet, times = made
    rated = vision.rate_tiles(sheet, len(times), subject, context) or []
    out = []
    for r in rated:
        if r["score"] < config.VISION_MIN_SCORE:
            continue
        out.append({"start": max(0.0, times[r["tile"] - 1] - 0.5),
                    "score": r["score"], "description": r["description"]})
    return out


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
                 claim: Callable[[str], bool]) -> List[tuple]:
    """[(job, candidate, moment)] for as many of the subject's lines as the pool covers."""
    need = len(sjobs)
    seconds = max(j.get("seconds") or 6.0 for j in sjobs) + media.SEQ_SHOT_PAD
    context = " ".join((j.get("context") or "") for j in sjobs[:4])
    pool: List[tuple] = []
    for cand in candidates(subject, require_cc, skip_ids)[:config.POOL_MAX_VIDEOS]:
        found = spaced(rate_video(cand, subject, context, seconds), config.POOL_MIN_GAP_SECONDS)
        for m in found:
            if claim(f"yt:{cand['id']}@{int(m['start'] // 10)}"):
                pool.append((cand, m))
        if len(pool) >= need:
            break
    # Story order: consecutive lines take consecutive moments of one video.
    return [(job, cand, m) for job, (cand, m) in zip(sjobs, pool)]


def _fetch(job: dict, cand: dict, m: dict, work: str, require_cc: bool,
           subject: str) -> Optional[media.MediaAsset]:
    seconds = (job.get("seconds") or 6.0) + media.SEQ_SHOT_PAD
    path = media._yt_fetch_retry(cand["id"], work, m["start"], seconds, cand.get("title", ""))
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
        moment_key=f"yt:{cand['id']}@{int(m['start'] // 10)}")


def source_by_subject(jobs: List[dict], work: str, *, require_cc: bool = False,
                      report: Optional[Callable] = None,
                      min_scenes: Optional[int] = None) -> Dict[int, media.MediaAsset]:
    """{job index: asset} for every line a subject pool covered."""
    need_min = config.POOL_MIN_SCENES if min_scenes is None else min_scenes
    todo = {k: v for k, v in groups(jobs).items() if len(v) >= need_min}
    results: Dict[int, media.MediaAsset] = {}
    if not todo:
        return results
    lock = threading.Lock()
    claimed: Set[str] = set()
    done = [0]
    stats = {"subjects": len(todo), "lines": sum(len(v) for v in todo.values()), "covered": 0}

    def claim(key: str) -> bool:
        with lock:
            if key in claimed:
                return False
            claimed.add(key)
            return True

    def one(key: str) -> None:
        sjobs = todo[key]
        name = display_name(sjobs)
        try:
            plan = plan_subject(name, sjobs, require_cc, set(), claim)
            with ThreadPoolExecutor(max_workers=6) as ex:
                got = list(ex.map(lambda p: (p[0], _fetch(p[0], p[1], p[2], work, require_cc, name)),
                                  plan))
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
            print(f"[pools] {name}: {covered}/{len(sjobs)} lines from its pool", flush=True)
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
