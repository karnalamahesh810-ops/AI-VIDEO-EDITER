"""
Restore / repair missing media: a project whose files vanished from storage
is made renderable again WITHOUT planning it again.

Why this exists. On 2026-10-04 (07:06 UTC) the Cloudflare R2 folders of two of
the owner's projects were deleted by hand. Their timelines were untouched and
still pointed at the old links, so the editor showed empty scenes and a render
failed on its first read. Planning again would have paid for the whole footage
search a second time and thrown the owner's edits away - while everything
needed to put the files back was still there:

  1. COPY    the file a fan-out part sourced for the scene:
             projects/<project>/parts/<plan job>/NNNN.ext, NNNN being the
             scene's number (s0NNN in the timeline). In the app's storage for
             plans made before R2_ONLY, in R2 after. A part can be an earlier
             pick the plan later replaced (the rescue pass, the variety
             rules), so a copy is used only when it IS the timeline's shot:
             the tone the plan measured on it (media.tone, src/grade.py),
             else a photo's dHash in the plan's ledger record, else a clip's
             length. A copy that cannot be checked is not used
             (RESTORE_UNVERIFIED).
  2. FETCH   the shot again from where it came from, with the plan's own
             code: the same YouTube moment (semanticMetadata.sourceUrl /
             assetId + moment.start + the clip's length, cut clean like the
             plan cut it), the picture's own address through imagefix.fetch.
             Both are then polished as the plan polishes a chosen file
             (upscale / vertical framing, src/upscale.py).
  3. THUMBS  the editor's thumbnail and light preview copy are made again
             from the file (the handler's _thumbnail / _preview_proxy).
  4. LIST    what cannot be put back is listed (scene, reason) and left to
             the render's quality check (src/quality.py), which repairs a
             scene it cannot read.

A restored file goes to the SAME key the timeline already names
(projects/<project>/media/sNNNN-<12 hex>.ext: the token is random, so the key
is only known from the timeline). So the timeline never changes, and neither
does anything else: the project row is never written, nothing is ever
deleted, an object that exists is never overwritten and nothing is written
outside projects/<project>/. Running it twice restores only what is still
missing; `dry_run` prints the plan and changes nothing.

Measured on the two deleted projects (the read-only study, 2026-10-04):
15eb0bc3 - 81 of 201 scenes copy straight back, 111 are fetched again, 9 have
nothing; 9c467873 - 97 of 187 copy back, 84 are fetched again, 6 have nothing.
Their contrast pictures (split/, overlay/) have no copy and no recorded
source: the render's check shows those looks without them.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import requests

from . import config, events, filters, grade, imagefix, ledger, media, r2, storage, upscale, ytdlp

VIDEO_EXTS = (".mp4", ".webm", ".mov", ".m4v", ".mkv")
# A part clip is the timeline's clip when their lengths agree this closely
# (the timeline's clipSeconds is the measured length, to 2 decimals).
CLIP_TOLERANCE = 0.15
# dHash bits a part photo may differ from the plan's ledger record (upscaling moves a few).
HASH_BITS = 8
# How far a copy's tone may sit from the tone the plan measured on its own
# file: brightness / colourfulness, black and white points, and the two
# colour ratios (relative). Re-encoding and upscaling move these by a few
# thousandths; another shot differs in at least one by far more.
TONE_TOLERANCE = {"l": 0.03, "s": 0.03, "lo": 0.06, "hi": 0.06}
TONE_RATIO_TOLERANCE = 0.06
# A re-fetched clip shorter than this share of the timeline's clip is not stored:
# the render's check would find it short and replace it anyway.
MIN_CLIP_SHARE = 0.6
LIST_LIMIT = 50_000
# Shots with nothing to fetch again, by where they came from.
NO_ORIGIN = {
    "generated": "an AI-made picture cannot be made again the same",
    # AI fill (src/aifill.py): its original stays on R2 under projects/<id>/aifill/ (semanticMetadata.aiFill).
    "ai-generated": "an AI fill picture or clip cannot be made again the same",
    # The AI presenter (src/presenter/hybrid.py): cut to its own words from a take - its original on R2
    # (semanticMetadata.originalUrl) starts before the line, so a copy fetched again would be out of sync.
    "ai-presenter": "the AI presenter's clip is cut to its own words: make the video again to make it again",
    "noaa_goes": "a live satellite loop of that day cannot be fetched again",
    "upload": "the owner's own upload has to be uploaded again",
}
_SCENE_ID = re.compile(r"s(\d{4})$")
_PART_KEY = re.compile(r"(?:^|/)parts/([^/]+)/(\d{4}\.\w+)$")
_DAILYMOTION = re.compile(r"(?:dailymotion\.com/video/|dai\.ly/)([A-Za-z0-9]+)")
_SAFE = re.compile(r"[^A-Za-z0-9_-]+")


class RestoreError(RuntimeError):
    """Why one file could not be put back, in words the owner can read."""


@dataclass
class Link:
    """One stored file the timeline points at, and what is known about its shot."""
    bucket: str
    key: str
    kind: str                           # "video" | "image"
    role: str                           # "scene" | "look" (a graphic's own picture) | "choice"
    label: str                          # "s0012", "graphic 7 (CMP_SPLIT_V1)"
    index: Optional[int] = None         # the scene's place in the timeline, for events
    number: Optional[int] = None        # NNNN of its part file
    asset_id: str = ""
    source_url: str = ""
    page_url: str = ""
    source_thumb: str = ""
    provider: str = ""
    title: str = ""
    start: Optional[float] = None
    clean: bool = False                 # the plan cut it at a clean stretch (moment.clean)
    clip_seconds: float = 0.0
    scene_seconds: float = 0.0
    tone: Optional[dict] = None
    thumb: Optional[Tuple[str, str]] = None
    preview: Optional[Tuple[str, str]] = None
    also: List[str] = field(default_factory=list)   # other scenes showing the same file

    @property
    def ext(self) -> str:
        return os.path.splitext(self.key)[1].lower()

    @property
    def tag(self) -> str:
        """A file-name-safe name for this link's work files."""
        return _SAFE.sub("_", os.path.splitext(os.path.basename(self.key))[0])[:60] or "file"

    @property
    def want(self) -> float:
        """Seconds of clip the timeline expects."""
        if self.clip_seconds > 0:
            return self.clip_seconds
        return self.scene_seconds + 1.5 if self.scene_seconds > 0 else 6.0


# --------------------------------------------------------------------------- #
# The timeline
# --------------------------------------------------------------------------- #

def _find_timeline(data) -> Optional[dict]:
    """The timeline inside what a link returned: itself, or a job payload carrying it."""
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("scenes"), list):
        return data
    for path in (("input", "timeline"), ("timeline",), ("scene_data",)):
        node = data
        for name in path:
            node = node.get(name) if isinstance(node, dict) else None
        if isinstance(node, dict) and isinstance(node.get("scenes"), list):
            return node
    return None


def load_timeline(inp: dict, work: str = "") -> dict:
    """
    The saved document: `timeline` in the input, or read through storage -
    `timeline_key` (an R2 object) or `timeline_url` (a link to the timeline,
    or to the render payload the app keeps under jobs/<project>/, which
    carries it as input.timeline). A long video's timeline is several MB,
    more than a job's input may hold.
    """
    doc = inp.get("timeline") if isinstance(inp.get("timeline"), dict) else None
    if doc is None:
        key, url = str(inp.get("timeline_key") or ""), str(inp.get("timeline_url") or "")
        raw = None
        if key:
            raw = r2.get_bytes(key, timeout=120)
            if raw is None:
                raise ValueError(f"the timeline is not in storage ({key})")
        elif url:
            loc = r2.locate(url) if r2.enabled() else None
            if loc:
                raw = r2.get_bytes(loc[1], bucket=loc[0], timeout=120)
            if raw is None:
                r = requests.get(url, timeout=(20, 300), headers={"User-Agent": config.USER_AGENT})
                if r.status_code != 200:
                    raise ValueError(f"the timeline link answered HTTP {r.status_code}")
                raw = r.content
        else:
            raise ValueError("restore_media needs the saved timeline: timeline, timeline_url or timeline_key")
        try:
            doc = _find_timeline(json.loads(raw.decode("utf-8")))
        except (ValueError, UnicodeDecodeError) as e:
            raise ValueError(f"the timeline could not be read ({type(e).__name__})") from e
    if not isinstance(doc, dict) or not isinstance(doc.get("scenes"), list) or not doc["scenes"]:
        raise ValueError("the timeline has no scenes")
    return doc


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _kind_of(m: dict, key: str) -> str:
    kind = str(m.get("type") or "")
    if kind in ("video", "image"):
        return kind
    return "video" if os.path.splitext(key)[1].lower() in VIDEO_EXTS else "image"


def inventory(doc: dict) -> Tuple[List[Link], dict]:
    """
    Every file of ours the timeline points at, once each: a scene's clip or
    picture (with its thumbnail and preview copy), a graphic's own picture
    (overlay.media, animation.media) and the pick-a-shot choices. Links that
    are not in our R2 buckets (an older project's signed app-storage link, a
    file on the web) are counted, not checked: there is nothing of ours to
    put back for them.
    """
    fps = max(1, int(_num(doc.get("fps")) or 30))
    links: Dict[Tuple[str, str], Link] = {}
    stats = {"scenes": 0, "other_links": 0}

    def add(link: Link) -> None:
        old = links.get((link.bucket, link.key))
        if old is None:
            links[(link.bucket, link.key)] = link
        elif old.role != "scene" and link.role == "scene":
            # A graphic borrowing a scene's picture: the scene knows where it came from.
            link.also = old.also + [old.label]
            links[(link.bucket, link.key)] = link
        elif link.label not in old.also and link.label != old.label:
            old.also.append(link.label)

    def look(m, label: str, index: Optional[int], role: str = "look") -> None:
        if not isinstance(m, dict):
            return
        loc = r2.locate(str(m.get("url") or ""))
        if not loc:
            return
        src = str(m.get("sourceUrl") or "")
        add(Link(bucket=loc[0], key=loc[1], kind=_kind_of(m, loc[1]), role=role, label=label, index=index,
                 source_url=src if src.startswith("http") else "", provider=str(m.get("source") or ""),
                 thumb=r2.locate(str(m.get("thumbnail") or "")) if role == "choice" else None,
                 preview=r2.locate(str(m.get("previewUrl") or "")) if role == "choice" else None))

    for i, s in enumerate(doc.get("scenes") or []):
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id") or f"scene {i + 1}")
        m = s.get("media") if isinstance(s.get("media"), dict) else {}
        sem = s.get("semanticMetadata") if isinstance(s.get("semanticMetadata"), dict) else {}
        if m.get("type") in ("video", "image") and m.get("url"):
            stats["scenes"] += 1
            loc = r2.locate(str(m["url"]))
            if not loc:
                stats["other_links"] += 1
            else:
                moment = sem.get("moment") if isinstance(sem.get("moment"), dict) else {}
                src = str(sem.get("sourceUrl") or "")
                start = _num(moment.get("start"))
                if start is None:
                    start = ledger.url_start(src)
                num = _SCENE_ID.match(sid)
                tone = m.get("tone") if isinstance(m.get("tone"), dict) else None
                add(Link(bucket=loc[0], key=loc[1], kind=str(m["type"]), role="scene", label=sid, index=i,
                         number=int(num.group(1)) if num else None,
                         asset_id=str(sem.get("assetId") or ""), source_url=src if src.startswith("http") else "",
                         page_url=str(sem.get("pageUrl") or ""), source_thumb=str(sem.get("sourceThumbnail") or ""),
                         provider=str(sem.get("provider") or m.get("source") or ""),
                         title=str(m.get("attribution") or "")[:80], start=start,
                         clean="clean" in moment, clip_seconds=_num(m.get("clipSeconds")) or 0.0,
                         scene_seconds=(_num(s.get("durationInFrames")) or 0.0) / fps,
                         tone=tone if tone and tone.get("v") == grade.TONE_VERSION and grade._valid_tone(tone) else None,
                         thumb=r2.locate(str(m.get("thumbnail") or "")),
                         preview=r2.locate(str(m.get("previewUrl") or ""))))
        if isinstance(m.get("split"), dict):
            look(m["split"], f"{sid} split screen", i)        # a presenter split screen's real half
        anim = s.get("animation") if isinstance(s.get("animation"), dict) else {}
        for x in anim.get("media") or []:
            look(x, f"{sid} graphic", i)
        for n, alt in enumerate(sem.get("alternatives") or [], 1):
            if isinstance(alt, dict):
                look(alt.get("media"), f"{sid} choice {n}", i, role="choice")
    for n, ov in enumerate(doc.get("overlays") or []):
        if not isinstance(ov, dict):
            continue
        for x in ov.get("media") or []:
            look(x, f"graphic {n + 1} ({ov.get('template') or ov.get('type') or 'look'})", None)
    return list(links.values()), stats


# --------------------------------------------------------------------------- #
# What storage still has
# --------------------------------------------------------------------------- #

def stored(project_id: str, wanted: List[Tuple[str, str]], parallel: int = 8) -> Tuple[set, set, List[str]]:
    """
    (the wanted (bucket, key)s that exist, the ones that could not be asked
    about, the project's part keys in R2). One listing of projects/<project>/
    answers for the project's own files; anything else (a picture borrowed
    from another project, a library clip) is asked for by HEAD. A file
    storage could not answer for is never treated as missing - it is left
    alone.
    """
    prefix = f"projects/{project_id}/"
    have, unknown, parts = set(), set(), []
    listed = False
    try:
        rows = r2.list_keys(prefix, limit=LIST_LIMIT)
        listed = len(rows) < LIST_LIMIT
        for row in rows:
            have.add((config.R2_BUCKET, row["key"]))
            if _PART_KEY.search(row["key"]):
                parts.append(row["key"])
    except Exception as e:  # noqa: BLE001 - each file is asked for on its own below
        print(f"[restore] could not list {prefix} ({type(e).__name__}: {str(e)[:100]}); "
              "asking for each file instead", flush=True)
    ask = [w for w in dict.fromkeys(wanted)
           if not (listed and w[0] == config.R2_BUCKET and w[1].startswith(prefix))]

    def head(w):
        try:
            return w, r2.head(w[1], bucket=w[0]) is not None
        except Exception:  # noqa: BLE001 - unknown, not missing
            return w, None
    if ask:
        with ThreadPoolExecutor(max_workers=max(1, min(parallel, len(ask)))) as ex:
            for w, ok in ex.map(head, ask):
                if ok is None:
                    unknown.add(w)
                elif ok:
                    have.add(w)
    return {w for w in wanted if w in have}, unknown, sorted(parts)


# --------------------------------------------------------------------------- #
# The copies: what the plan's parts sourced
# --------------------------------------------------------------------------- #

class Parts:
    """
    Where the copies of a project's sourced scene files are.

    * `given`: read links the caller already holds, [{"path": "projects/<p>/
      parts/<plan job>/0012.mp4", "url": "https://..."}] (or {name: url}) -
      scripts/restore_project.py signs them with the app's publishable key;
    * parts still in R2 (plans made with R2_ONLY), found by the listing;
    * the app's storage through the broker (storage.broker_read_url) for the
      plan jobs named in `plan_jobs`. The broker only answers the job that is
      running for the project, so its first refusal ends the asking: a
      200-scene restore must not send 200 refused calls at a small database.
    Never needs a service key.
    """

    def __init__(self, project_id: str, job_id: str = "", bucket: str = "", given=None,
                 plan_jobs: Optional[List[str]] = None, r2_parts: Optional[List[str]] = None):
        self.project_id, self.job_id = project_id, job_id
        self.bucket = bucket or config.MEDIA_BUCKET
        self.by_name: Dict[str, List[dict]] = {}
        self.jobs: List[str] = []
        self.refused = ""
        self._errors = 0
        self._lock = threading.Lock()
        rows = given
        if isinstance(given, dict):
            rows = [{"path": k, "url": v} if isinstance(v, str) else {"path": k, **(v or {})}
                    for k, v in given.items()]
        for row in rows or []:
            if not isinstance(row, dict) or not str(row.get("url") or "").startswith("http"):
                continue
            path = str(row.get("path") or row.get("name") or "")
            m = _PART_KEY.search(path)
            name = m.group(2) if m else os.path.basename(path)
            if not re.fullmatch(r"\d{4}\.\w+", name):
                continue
            job = m.group(1) if m else ""
            self._add(name, {"job": job, "label": f"app storage {path}", "url": str(row["url"])})
        for key in r2_parts or []:
            m = _PART_KEY.search(key)
            if m:
                self._add(m.group(2), {"job": m.group(1), "label": f"R2 {key}", "key": key})
        for job in plan_jobs or []:
            job = str(job or "").strip()
            if job and "/" not in job and job not in self.jobs:
                self.jobs.append(job)

    def _add(self, name: str, ref: dict) -> None:
        self.by_name.setdefault(name.lower(), []).append(ref)

    def plan_jobs(self) -> List[str]:
        """Every plan job a copy is known from (their ledger records hold the photos' hashes)."""
        out = list(self.jobs)
        for refs in self.by_name.values():
            for ref in refs:
                if ref.get("job") and ref["job"] not in out:
                    out.append(ref["job"])
        return out

    def _signed(self, path: str) -> str:
        """A read link to one object of the app's storage, "" when it has none (or will not say)."""
        if self.refused:
            return ""
        try:
            if storage.broker_enabled():
                return storage.broker_read_url(self.bucket, path, self.project_id, self.job_id)
            if config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY:
                return storage.signed_url(path, bucket=self.bucket, expires_in=3600)
            self.refused = "no way to read the app's storage from this worker"
        except Exception as e:  # noqa: BLE001 - no copy there
            text = str(e)
            if "not found" in text.lower():
                return ""                                   # the plain answer: no such part
            denied = "(403)" in text or "(401)" in text or "not running" in text
            with self._lock:
                self._errors += 1
                # Refused outright, or failing again and again (the app's database down):
                # stop asking, the shots are fetched from their sources instead.
                if (denied or self._errors >= 3) and not self.refused:
                    self.refused = text[:160]
                    print(f"[restore] the app's storage is not asked for copies any more: {text[:160]}", flush=True)
        return ""

    def candidates(self, link: Link) -> List[dict]:
        """The copies that could be this link's file: the same scene number and file type."""
        if link.role != "scene" or link.number is None or not link.ext:
            return []
        name = f"{link.number:04d}{link.ext}"
        out = list(self.by_name.get(name, []))
        seen = {ref.get("job") for ref in out}
        for job in self.jobs:
            if job in seen:
                continue
            path = f"projects/{self.project_id}/parts/{job}/{name}"
            url = self._signed(path)
            if url:
                out.append({"job": job, "label": f"app storage {path}", "url": url})
        return out


def _get_object(bucket: str, key: str, dest: str) -> str:
    """One of our own R2 objects to disk, through the S3 API (the public link is rate limited)."""
    from . import fanout
    fanout._r2_get(key, bucket, dest)
    return dest


def fetch_copy(ref: dict, dest: str) -> str:
    if ref.get("key"):
        return _get_object(ref.get("bucket") or config.R2_BUCKET, ref["key"], dest)
    return storage.download(ref["url"], dest, timeout=300)


def plan_hashes(plan_jobs: List[str]) -> Dict[str, int]:
    """
    {asset id or normalised address: dHash} of the photos the plan showed,
    from its ledger records (ledger/jobs/<plan job>.json in the library
    bucket). Empty without the library bucket or the records.
    """
    out: Dict[str, int] = {}
    if not r2.library_enabled():
        return out
    for job in plan_jobs[:8]:
        try:
            rec = ledger._get_json(ledger.job_key(job)) or {}
        except Exception as e:  # noqa: BLE001 - photos are then checked by tone only
            print(f"[restore] the plan's record {job} could not be read ({type(e).__name__})", flush=True)
            continue
        for it in rec.get("items") or []:
            try:
                h = int(str(it.get("h") or ""), 16)
            except (ValueError, AttributeError):
                continue
            for name in (it.get("a"), it.get("u")):
                if name:
                    out.setdefault(str(name), h)
    return out


# --------------------------------------------------------------------------- #
# Is this copy the timeline's shot?
# --------------------------------------------------------------------------- #

def _clip_seconds(path: str) -> float:
    return filters._video_seconds(path)


def _plays(path: str) -> bool:
    return filters.playable_video(path)


def _is_picture(path: str) -> bool:
    return imagefix.sniff(path) in ("jpeg", "png", "webp", "gif", "avif", "heic", "bmp", "tiff")


def _measure_tone(link: Link, path: str) -> Optional[dict]:
    m = {"type": link.kind, "url": path}
    if link.clip_seconds > 0:
        m["clipSeconds"] = link.clip_seconds
    return grade.measure(m)


def same_tone(a: dict, b: dict) -> bool:
    for k, tol in TONE_TOLERANCE.items():
        if abs(float(a[k]) - float(b[k])) > tol:
            return False
    for k in ("rg", "bg"):
        if abs(float(a[k]) - float(b[k])) > TONE_RATIO_TOLERANCE * max(float(a[k]), float(b[k]), 1e-3):
            return False
    return True


def readable(link: Link, path: str) -> str:
    """"" when the copy plays / is a picture and, for a clip, has the timeline's length; else why not."""
    if link.kind == "video":
        if not _plays(path):
            return "the copy does not play"
        if link.clip_seconds > 0:
            real = _clip_seconds(path)
            if abs(real - link.clip_seconds) > CLIP_TOLERANCE:
                return f"another shot ({real:.2f} s long, the timeline's clip is {link.clip_seconds:.2f} s)"
        return ""
    return "" if _is_picture(path) else "the copy is not a picture"


def same_shot(link: Link, path: str, hashes: Dict[str, int]) -> Tuple[Optional[bool], str]:
    """
    (True / False / None when it cannot be checked, why) for a copy that is
    readable() and polished like the plan's file. The tone the plan measured
    on its own file decides when the timeline has one (every plan since the
    grade, src/grade.py); else a photo's dHash against the plan's ledger
    record; else a clip's length, which readable() already matched.
    """
    if link.tone:
        got = _measure_tone(link, path)
        if got and grade._valid_tone(got):
            if same_tone(link.tone, got):
                return True, "the same tone as the plan's file"
            return False, "another shot (its colours are not the ones the plan measured)"
    if link.kind == "image":
        want = hashes.get(link.asset_id[:160]) if link.asset_id else None
        if want is None and link.source_url:
            want = hashes.get(ledger.norm_url(link.source_url))
        got = ledger.photo_hash(path)
        if want is None or got is None:
            return None, "nothing of the plan's picture is recorded to check the copy against"
        bits = bin(got ^ want).count("1")
        return (True, "the plan's picture") if bits <= HASH_BITS else (False, f"another picture ({bits} bits apart)")
    if link.clip_seconds > 0:
        return True, "the timeline's clip length"
    return None, "the timeline does not say how long its clip is"


# --------------------------------------------------------------------------- #
# Fetching a shot again from where it came from
# --------------------------------------------------------------------------- #

def _short(url: str, n: int = 90) -> str:
    return url if len(url) <= n else url[:n - 3] + "..."


def origin(link: Link) -> Tuple[str, str]:
    """(how the shot can be fetched again, in words); ("", why not) when it cannot."""
    if link.provider in NO_ORIGIN:
        return "", NO_ORIGIN[link.provider]
    src = link.source_url
    if link.kind == "image":
        if src:
            return "picture", f"its own address {_short(src)}"
        return "", ("the graphic's picture has no copy and where it came from was not recorded"
                    if link.role != "scene" else "where the picture came from was not recorded")
    vid = ledger.youtube_id(src, link.asset_id)
    if vid:
        if link.start is None:
            return "", f"the moment of YouTube video {vid} was not recorded"
        return "youtube", f"YouTube {vid} from {link.start:.1f} s for {link.want:.1f} s"
    dm = _DAILYMOTION.search(src)
    if dm:
        return "dailymotion", f"Dailymotion {dm.group(1)} from {float(link.start or 0):.1f} s for {link.want:.1f} s"
    if src:
        direct = os.path.splitext(src.split("?", 1)[0])[1].lower() in VIDEO_EXTS or bool(r2.locate(src))
        return ("file", f"its own file {_short(src)}") if direct else ("web", f"its page {_short(src)}")
    return "", "where the clip came from was not recorded"


def agency_of(link: Link) -> str:
    """
    "a stock-agency picture (alamy)" when the picture a link puts back came
    from a stock agency by its recorded address, page, small copy or title,
    else "". A restore puts it back all the same (it is the timeline's own
    shot) and says so in its row; a render with STOCK_GATE_REPAIR replaces it.
    """
    if link.kind != "image" or not link.source_url:
        return ""
    from . import stockblock
    return stockblock.reason(link.source_url, link.page_url, link.source_thumb, title=link.title)


def _download(url: str, dest: str) -> str:
    loc = r2.locate(url) if r2.enabled() else None
    if loc:
        return _get_object(loc[0], loc[1], dest)
    return storage.download(url, dest, timeout=300)


def _fit(path: str, want: float) -> str:
    """The clip cut to the length the timeline plays; RestoreError when it is far too short."""
    real = _clip_seconds(path)
    if real <= 0:
        raise RestoreError("the download does not play")
    if real < want * MIN_CLIP_SHARE:
        raise RestoreError(f"its source only gave {real:.1f} s of the {want:.1f} s clip")
    if real > want + 0.25:
        cut = filters.trim_clip(path, 0.0, want)
        if cut:
            _remove(path)
            return cut
    return path


def refetch(link: Link, how: str, work: str) -> str:
    """
    The shot again from where it came from, as the plan fetched it. A YouTube
    clip the plan cut clean (moment.clean) is taken with the same margin and
    cut at the same clean stretch (media.fetch_clean_clip: the plan asked for
    `need` seconds and kept need + 0.5); any other the plain section.
    """
    if how == "picture":
        dest = os.path.join(work, f"re_{link.tag}{link.ext or '.jpg'}")
        try:
            # The timeline's own picture, even a stock agency's: the block
            # (src/stockblock.py) keeps those out of new choices, and a restore
            # makes no choice - it puts the owner's timeline back as it was.
            return imagefix.fetch(link.source_url, dest, link.page_url, thumbnail=link.source_thumb,
                                  allow_agency=True)
        except storage.StorageError as e:
            raise RestoreError(f"its site no longer gives the picture ({str(e)[:140]})") from e
    start, want = float(link.start or 0.0), link.want
    if how == "youtube":
        vid = ledger.youtube_id(link.source_url, link.asset_id)
        if link.clean:
            path = media.fetch_clean_clip(vid, work, start, max(1.0, want - 0.5), link.title)[0]
        else:
            path = media._yt_fetch_retry(vid, work, start, want, link.title)
        if not path:
            got = ytdlp._LAST_FAILURE.get()
            why = getattr(got[0], "value", str(got[0])) if got else "no answer"
            raise RestoreError(f"YouTube did not give the clip again ({why})")
    elif how == "dailymotion":
        path = media._dm_fetch(_DAILYMOTION.search(link.source_url).group(1), work, start, want)
        if not path:
            raise RestoreError("Dailymotion did not give the clip again")
    elif how == "file":
        dest = os.path.join(work, f"re_{link.tag}{link.ext or '.mp4'}")
        try:
            path = _download(link.source_url, dest)
        except Exception as e:  # noqa: BLE001
            raise RestoreError(f"its file could not be downloaded again ({str(e)[:140]})") from e
    else:
        path = media._web_fetch(link.source_url, work, start, want)
        if not path:
            raise RestoreError("its page did not give the clip again")
    return _fit(path, want)


def polish(link: Link, path: str) -> str:
    """
    What the plan does to a chosen file before it is stored
    (upscale.upscale_assets): a vertical clip framed on its blurred copy when
    the style allows vertical footage, else a soft clip sharpened to 1080
    lines; a small photo upscaled. Archive film keeps its softness and a
    generated picture is left as made. Returns what was done, "" for nothing.
    """
    if link.role != "scene" or not (config.UPSCALE_ENABLED or config.ALLOW_VERTICAL):
        return ""
    if link.kind == "video":
        if link.provider == "archive_org":
            return ""
        if config.ALLOW_VERTICAL and upscale.frame_vertical(path):
            return "framed"
        if config.UPSCALE_ENABLED and upscale.upscale_clip(path, config.MIN_CLIP_HEIGHT):
            return "upscaled"
        return ""
    if link.provider != "generated" and config.UPSCALE_ENABLED and upscale.upscale_image(path):
        return "upscaled"
    return ""


# --------------------------------------------------------------------------- #
# Putting it back
# --------------------------------------------------------------------------- #

def _remove(*paths: str) -> None:
    for p in paths:
        try:
            if p and os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass


def put_if_absent(local: str, bucket: str, key: str) -> bool:
    """
    Upload `local` to `key` unless an object is there now. False when one is
    (another run restored it meanwhile): a restore never overwrites a file.
    """
    if r2.head(key, bucket=bucket) is not None:
        return False
    r2.upload(local, key, content_type=r2.content_type(key),
              deadline=time.time() + config.R2_MEDIA_UPLOAD_SECONDS,
              bucket=bucket, cache_control=r2.IMMUTABLE)
    return True


def _ours(project_id: str, where: Optional[Tuple[str, str]]) -> bool:
    """
    A restore only ever writes under its own project's folder of the videos
    bucket: a plain key there - never one with "." / ".." / empty parts or a
    backslash, which a client could resolve to somewhere else.
    """
    if not (where and project_id and where[0] == config.R2_BUCKET):
        return False
    key = str(where[1] or "")
    head = f"projects/{project_id}/"
    if not key.startswith(head) or "\\" in key:
        return False
    rest = key[len(head):].split("/")
    return bool(rest) and all(p not in ("", ".", "..") for p in rest)


def _row(link: Link, did: str, how: str = "", **more) -> dict:
    row = {"scene": link.label, "type": link.kind, "key": link.key, "did": did}
    if how:
        row["from"] = how[:200]
    if link.also:
        row["also"] = link.also[:6]
    row.update({k: v for k, v in more.items() if v not in (None, "", [], False)})
    return row


def run(inp: dict, doc: dict, work: str, report: Optional[Callable] = None,
        thumbnail: Optional[Callable] = None, preview: Optional[Callable] = None) -> dict:
    """
    Restore the files of `doc` (the saved timeline) that storage no longer has.

    inp: project_id; dry_run; parts / plan_jobs (see Parts); seconds (the time
    box, RESTORE_SECONDS), parallel (RESTORE_PARALLEL); refetch False = copies
    only; allow_unverified = use a copy that cannot be checked
    (RESTORE_UNVERIFIED). `thumbnail(path, work, tag)` and `preview(path,
    work, tag)` are the handler's makers of the editor's small copies.

    Returns the summary: restored_from_copy, refetched, failed (each a count
    of scene files), thumbnails, previews, failures [{scene, reason}], the
    rows of what was done (a dry run: of what would be) and seconds.
    """
    started = time.time()
    project_id = str(inp.get("project_id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", project_id):
        raise ValueError("restore_media needs the project_id")
    if not r2.enabled():
        raise ValueError("Cloudflare R2 is not configured on this worker: there is nowhere to restore to")
    dry = bool(inp.get("dry_run"))
    seconds = float(inp.get("seconds") or config.RESTORE_SECONDS)
    parallel = max(1, int(inp.get("parallel") or config.RESTORE_PARALLEL))
    allow_refetch = inp.get("refetch") is not False
    unverified_ok = bool(inp.get("allow_unverified", config.RESTORE_UNVERIFIED))
    say = report or (lambda *a, **k: None)
    deadline = started + seconds

    say("Restoring media: reading what storage still has", 2)
    links, stats = inventory(doc)
    wanted: List[Tuple[str, str]] = []
    for l in links:
        wanted += [w for w in ((l.bucket, l.key), l.thumb, l.preview) if w]
    have, unknown, r2_parts = stored(project_id, wanted, parallel)

    def there(where) -> bool:
        return where in have or where in unknown

    parts = Parts(project_id, str(inp.get("_job_id") or ""), str(inp.get("media_bucket") or ""),
                  given=inp.get("parts"), plan_jobs=inp.get("plan_jobs"), r2_parts=r2_parts)
    choices_missing = sum(1 for l in links if l.role == "choice" and not there((l.bucket, l.key)))
    todo = [l for l in links if l.role != "choice" and (
        not there((l.bucket, l.key)) or (l.thumb and not there(l.thumb)) or (l.preview and not there(l.preview)))]
    missing = sum(1 for l in todo if not there((l.bucket, l.key)))
    out = {"ok": True, "project_id": project_id, "dry_run": dry,
           "scenes": stats["scenes"], "links": sum(1 for l in links if l.role != "choice"),
           "present": sum(1 for l in links if l.role != "choice" and (l.bucket, l.key) in have),
           "missing": missing, "unchecked": len(unknown), "other_links": stats["other_links"],
           "choices_missing": choices_missing,
           "restored_from_copy": 0, "refetched": 0, "failed": 0, "thumbnails": 0, "previews": 0,
           "agency_pictures": 0, "failures": [], "rows": []}
    print(f"[restore] {project_id}: {out['links']} file(s) in the timeline, {out['present']} in storage, "
          f"{missing} missing; {sum(len(v) for v in parts.by_name.values())} part cop(ies) known, "
          f"{len(parts.jobs)} plan job(s) to ask the app's storage about"
          + (f"; {len(unknown)} could not be asked about and are left alone" if unknown else ""), flush=True)

    if dry:
        would = {"copy": 0, "refetch": 0, "none": 0, "thumbnails": 0, "previews": 0}
        for l in todo:
            would["thumbnails"] += bool(l.thumb and not there(l.thumb))
            would["previews"] += bool(l.preview and not there(l.preview))
            if there((l.bucket, l.key)):
                continue
            if not _ours(project_id, (l.bucket, l.key)):
                would["none"] += 1
                out["rows"].append(_row(l, "none", reason="not this project's own file: a restore does not write it"))
                continue
            cands = parts.candidates(l)
            how, text = origin(l)
            if cands:
                would["copy"] += 1
                out["rows"].append(_row(l, "copy", cands[0]["label"],
                                        note="used if it is the timeline's shot"
                                             + (f", else fetched again from {text}" if how and allow_refetch else ""),
                                        agency=agency_of(l)))
            elif how and allow_refetch:
                would["refetch"] += 1
                out["rows"].append(_row(l, "refetch", text, agency=agency_of(l)))
            else:
                would["none"] += 1
                out["rows"].append(_row(l, "none", reason=text if not how else "re-fetching is switched off"))
        out["would"] = would
        for r in out["rows"]:
            print(f"[restore] WOULD {r['did']:7s} {r['scene']}  {r.get('from') or r.get('reason') or ''}", flush=True)
        out["seconds"] = round(time.time() - started, 1)
        print(f"[restore] dry run: {would['copy']} to copy back, {would['refetch']} to fetch again, "
              f"{would['none']} with nothing; {would['thumbnails']} thumbnail(s) and {would['previews']} "
              f"preview(s) to make again. Nothing was changed.", flush=True)
        events.emit("restore", "dry_run", data={**would, "missing": missing, "present": out["present"]})
        return out

    hashes = plan_hashes(parts.plan_jobs()) if any(l.kind == "image" and not l.tone for l in todo) else {}
    media.reset_cache()                 # a worker is reused: videos an earlier job found unavailable are asked again
    old_deadline = ytdlp.DEADLINE[0]
    ytdlp.set_deadline(deadline)        # a download that hangs ends with the time box

    def find(l: Link, files: List[str], notes: List[str]) -> Tuple[str, str, str]:
        """(the file on this disk, "copy" | "refetch", where from) for a missing file, ("", "", "") for none."""
        unchecked = ""
        for n, ref in enumerate(parts.candidates(l)):                               # (1) the copy
            dest = os.path.join(work, f"copy_{l.tag}_{n}{l.ext}")
            files.append(dest)
            try:
                fetch_copy(ref, dest)
            except Exception as e:  # noqa: BLE001 - the next copy, then its source
                notes.append(f"{ref['label']}: could not be read ({str(e)[:80]})")
                continue
            why = readable(l, dest)
            if not why:
                polish(l, dest)
                same, why = same_shot(l, dest, hashes)
                if same or (same is None and unverified_ok):
                    return dest, "copy", ref["label"] + ("" if same else " (not checked)")
                if same is None:
                    unchecked = ref["label"]
            notes.append(f"{ref['label']}: {why}")
            _remove(dest)
        if allow_refetch:                                                           # (2) its source
            kind, text = origin(l)
            if kind:
                try:
                    path = refetch(l, kind, work)
                    files.append(path)
                    polish(l, path)
                    return path, "refetch", text
                except RestoreError as e:
                    notes.append(str(e))
                except Exception as e:  # noqa: BLE001 - one shot never stops the rest
                    notes.append(f"{type(e).__name__}: {str(e)[:120]}")
            else:
                notes.append(text)
        if unchecked:
            notes.append(f"a copy exists that could not be checked ({unchecked}); allow_unverified uses it")
        return "", "", ""

    def one(l: Link) -> dict:
        main = (l.bucket, l.key)
        local, did, how = "", "present", ""
        notes: List[str] = []
        files: List[str] = []
        made = {"thumbnail": False, "preview": False}
        late = time.time() >= deadline
        try:
            if not there(main):
                if late:
                    return _row(l, "failed", reason="time ran out before its turn - run it again "
                                                    "(what is restored is skipped)")
                if not _ours(project_id, main):
                    return _row(l, "failed", reason="not this project's own file: a restore does not write it")
                try:
                    local, got, where_from = find(l, files, notes)
                    if not local:
                        return _row(l, "failed", reason="; ".join(notes)[:400] or "nothing to restore it from")
                    if put_if_absent(local, l.bucket, l.key):                       # the SAME key
                        did, how = got, where_from
                    else:
                        how = "another run restored it meanwhile"
                except Exception as e:  # noqa: BLE001 - reported for this file, the rest go on
                    return _row(l, "failed", reason=f"{type(e).__name__}: {str(e)[:200]}")
            for name, where, maker in (("thumbnail", l.thumb, thumbnail), ("preview", l.preview, preview)):   # (3)
                if not where or there(where) or maker is None or not _ours(project_id, where):
                    continue
                if late:
                    notes.append(f"time ran out before its {name} was made again")
                    continue
                try:
                    if not local:
                        local = _get_object(l.bucket, l.key, os.path.join(work, f"have_{l.tag}{l.ext}"))
                        files.append(local)
                    small = maker(local, work, f"re_{l.tag}")
                    if not small:
                        notes.append(f"its {name} could not be made again")
                        continue
                    files.append(small)
                    made[name] = put_if_absent(small, where[0], where[1])
                except Exception as e:  # noqa: BLE001 - a small copy never undoes the file itself
                    notes.append(f"its {name} was not stored ({type(e).__name__}: {str(e)[:80]})")
            return _row(l, did, how, thumbnail=made["thumbnail"], preview=made["preview"],
                        note="; ".join(notes)[:300],
                        # said, never dropped: the timeline's own picture goes back as it was
                        agency=agency_of(l) if did in ("copy", "refetch") else "")
        finally:
            _remove(*files)

    total = len(todo)
    say(f"Restoring media 0/{total}", 5, done=0, total=total)
    last_pct = None
    try:
        with ThreadPoolExecutor(max_workers=min(parallel, max(1, total)), thread_name_prefix="restore") as pool:
            futures = {pool.submit(one, l): l for l in todo}
            for n, fut in enumerate(as_completed(futures), 1):
                l = futures[fut]
                try:
                    row = fut.result()
                except Exception as e:  # noqa: BLE001 - one() reports its own; belt and braces
                    row = _row(l, "failed", reason=f"{type(e).__name__}: {str(e)[:200]}")
                out["rows"].append(row)
                if row["did"] == "copy":
                    out["restored_from_copy"] += 1
                elif row["did"] == "refetch":
                    out["refetched"] += 1
                elif row["did"] == "failed":
                    out["failed"] += 1
                    events.emit("restore", "not_restored", level="warning", scene=l.index,
                                message=f"{l.label}: {row.get('reason') or ''}"[:300])
                out["thumbnails"] += bool(row.get("thumbnail"))
                out["previews"] += bool(row.get("preview"))
                out["agency_pictures"] += bool(row.get("agency"))
                pct = 5 + int(93 * n / max(total, 1))
                if pct != last_pct:
                    last_pct = pct
                    say(f"Restoring media {n}/{total}", pct, done=n, total=total)
    finally:
        ytdlp.set_deadline(old_deadline)
    order = {l.key: n for n, l in enumerate(todo)}
    out["rows"].sort(key=lambda r: order.get(r["key"], len(order)))
    # (4) what could not be put back, in timeline order, for the render's quality check to repair.
    out["failures"] = [{"scene": r["scene"], "reason": r.get("reason") or ""}
                       for r in out["rows"] if r["did"] == "failed"]
    out["timed_out"] = time.time() >= deadline
    out["seconds"] = round(time.time() - started, 1)
    summary = {k: out[k] for k in ("restored_from_copy", "refetched", "failed", "thumbnails", "previews",
                                   "missing", "present", "seconds")}
    events.emit("restore", "summary", level="warning" if out["failed"] else "info", data=summary,
                message=f"{out['restored_from_copy']} copied back, {out['refetched']} fetched again, "
                        f"{out['failed']} not restored")
    print(f"[restore] {project_id}: {out['restored_from_copy']} copied back, {out['refetched']} fetched again, "
          f"{out['failed']} not restored; {out['thumbnails']} thumbnail(s) and {out['previews']} preview(s) "
          f"made again in {out['seconds']:.0f} s"
          + (f"; {out['agency_pictures']} stock-agency picture(s) put back as the timeline had them "
             "(STOCK_GATE_REPAIR replaces them at the render)" if out["agency_pictures"] else ""), flush=True)
    say(f"Restored {out['restored_from_copy'] + out['refetched']} of {missing} missing files", 100)
    return out
