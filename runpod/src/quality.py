"""
The quality gate (the owner's rule, 2026-10-01): every finished video is
right - no empty or missing scene, no missing picture, no black or frozen
frame, no clip shown twice, no failed render - and when something is wrong
the worker repairs it before anyone sees the video, and says what it did.

What it answers for (each has a test in tests/test_quality.py):
  * the owner's 18-minute Lake Powell video (159 scenes): 23 end scenes empty
    and 47 repeated clips after the build, fixed by hand;
  * an image look (split panels, overlay 46) showing empty slots;
  * a render that fell back to one machine (45 min) when its chunks hit 404s
    on thumbnails that were files on the pod;
  * scenes left without media when their uploads failed during an app
    database outage (the editor's timeline still named files on a dead pod);
  * a render that failed over one missing music file.

  Gate.before_render  every render (handler.do_render: build and render
                      actions), on the document the renderer will draw:
                      - every scene has a picture and none repeats an earlier
                        scene (gapfill.find_repeats);
                      - every file can be read: our R2 objects by an S3 HEAD,
                        any other link by a small range GET, a file by its size
                        on this disk - short timeouts, retries, all in parallel;
                      - a clip covers its scene. SceneClip.tsx slows a short
                        clip to no less than 0.6x and then the clip HOLDS ITS
                        LAST FRAME (measured on Remotion 4.0.511: a 1.5 s clip
                        in a 4 s scene froze for 1.53 s; one with no length in
                        the document plays at 1x and froze for 2 s);
                      - stills decode and are not tiny;
                      - every picture an overlay or a graphic draws can load,
                        and every look that shows pictures has one;
                      - the narration and the music can load.
                      A broken scene goes through the same ladder as an empty
                      one (gapfill.fill_empty: the clip library, the pools'
                      spare moments, one picture), then the last resort
                      (gapfill.hold_or_animate: the line's own graphic, the
                      neighbouring shot held over it), never a repeat; a line
                      that still has no picture becomes a full-screen text
                      graphic (a colour scene would fail the render's own
                      validation, and shows an empty frame).
  Gate.finish         the report: doc.meta.quality, the job's "quality", an
                      events row per finding and repair, and a one-liner for
                      the app ("Quality check: 159/159 scenes OK, 2 clips
                      replaced").
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import threading
import time
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait as _wait
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.request import url2pathname

import requests

from . import config, events, gapfill, r2, templates

# --------------------------------------------------------------------------- #
# What the renderer does (remotion/src), read off the code or measured
# --------------------------------------------------------------------------- #

# A scene plays on under the next scene's "crossfade" for this many frames
# (Main.tsx extends its Sequence), so its clip must cover them too.
CROSSFADE_FRAMES = 15
# The slowest SceneClip.tsx plays a clip to fill its scene; after the clip's
# last frame the picture freezes.
MIN_RATE = 0.6
# A freeze this short at the end of a clip is not seen.
TOLERANCE_FRAMES = 2
# The image looks and how they find their pictures (Main.tsx lookPictures).
PHOTO_CARDS = {"photo-card", "name-card"}
STILL_LOOKS = {"board", "clipping", "doc", "facts", "dossier", "window", "audio", "evidence"}
PERSON_CUES = {"person", "person-full", "profile"}
PICTURE_NEAR = 8
# A line with no picture at all is shown as its own text, full screen, in
# the first of these looks the registry has.
TEXT_LOOKS = ("TEXT_SENTENCE_HIGHLIGHT_V1", "TEXT_UNDERLINE_TITLE_V1", "HEADLINE_TITLE_V1")
# Smaller than this is a stub, not a file (a failed download was 262 bytes);
# a small real picture is caught as tiny once decoded.
MIN_VIDEO_BYTES = 8_000
MIN_IMAGE_BYTES = 100
MAX_IMAGE_BYTES = 40_000_000
# Events rows of findings and repairs per job (the summary row always goes).
EVENT_ROWS = 60

# The job's context for repairs, set by the handler before do_render:
#   ladder: repairs may search (gapfill.fill_empty) - off, only the last resort;
#   plan: this job planned the video, so gapfill.CONTEXT has its lines, the
#     clip library and the flags (build);
#   library / library_loader: the clip library, or how to load it (render);
#   story: the timeline's story, for the vision judge (render);
#   require_cc, allow_generated: the sourcing switches.
CONTEXT: Dict[str, Any] = {}
# The gate of the job running now (its report rides on a failed job too).
LAST: Dict[str, Any] = {}


def set_context(**kw) -> None:
    CONTEXT.clear()
    CONTEXT.update(kw)


def reset() -> None:
    CONTEXT.clear()
    LAST.clear()


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def short(url: str) -> str:
    """A link for the log and the report: host and file name, never a query (signed links carry tokens)."""
    u = str(url or "")
    if u.startswith(("http://", "https://")):
        p = urllib.parse.urlparse(u)
        return f"{p.netloc}/.../{os.path.basename(p.path)}" if p.path.count("/") > 1 else f"{p.netloc}{p.path}"
    return os.path.basename(u) or u[:60]


def local_path(url: str) -> str:
    """The file a document's link names on this disk ("" for a web link)."""
    u = str(url or "")
    if not u or u.startswith(("http://", "https://", "data:", "blob:", "bgm://")):
        return ""
    if u.lower().startswith("file://"):
        return url2pathname(urllib.parse.urlparse(u).path)
    return u


def _clock(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def _n(count: int, one: str, many: str = "") -> str:
    return f"{count} {one if count == 1 else (many or one + 's')}"


def _num(v) -> float:
    try:
        f = float(v)
        return f if math.isfinite(f) else 0.0
    except (TypeError, ValueError):
        return 0.0


def declared_seconds(media: dict) -> float:
    """The clip length the document gives the renderer (clipSeconds), 0 when it has none."""
    v = (media or {}).get("clipSeconds")
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else 0.0


def play_rate(declared: float, need: float) -> float:
    """The speed SceneClip.tsx plays a clip at: slowed to fill its scene, never under MIN_RATE."""
    return max(MIN_RATE, declared / need) if 0 < declared < need else 1.0


def scene_need(scenes: List[dict], i: int, fps: int) -> float:
    """Seconds scene i's picture is on screen (its Sequence, crossfade included)."""
    s = scenes[i]
    nxt = scenes[i + 1] if i + 1 < len(scenes) else {}
    frames = int(s.get("durationInFrames") or 0) + (CROSSFADE_FRAMES if (nxt or {}).get("transition") == "crossfade"
                                                    else 0)
    return frames / max(1, fps)


def sniff(head: bytes) -> str:
    """'video', 'image', 'page' (an HTML or JSON error page) or '' from a file's first bytes."""
    h = bytes(head[:64]) if isinstance(head, (bytes, bytearray)) else b""
    if not h:
        return ""
    if h.startswith((b"\xff\xd8\xff", b"\x89PNG", b"GIF87a", b"GIF89a")) or (h[:4] == b"RIFF" and h[8:12] == b"WEBP"):
        return "image"
    if h[4:8] == b"ftyp":
        return "image" if h[8:12] in (b"avif", b"avis", b"heic", b"heix", b"mif1", b"msf1") else "video"
    if h.startswith(b"\x1aE\xdf\xa3") or h[4:8] in (b"moov", b"mdat", b"wide", b"free", b"skip"):
        return "video"
    low = h.lstrip().lower()
    if low.startswith((b"<!doctype", b"<html", b"<?xml", b"<head", b"<body", b"{", b"[")):
        return "page"
    return ""


# --------------------------------------------------------------------------- #
# Can the renderer load it?
# --------------------------------------------------------------------------- #

@dataclass
class Check:
    ok: bool = True
    why: str = ""
    reached: bool = True        # False: the file could not be read at all
    unverified: bool = False    # the check could not finish: trusted as it is
    tiny: bool = False
    size: int = -1
    seconds: float = 0.0        # a clip's measured length
    width: int = 0
    height: int = 0
    local: str = ""             # a copy on this disk (a still fetched to decode it)


def _verdict(size: int, ctype, head: bytes, want: str) -> Check:
    ctype = ctype.split(";")[0].strip().lower() if isinstance(ctype, str) else ""
    kind = sniff(head)
    if kind == "page" or ctype in ("text/html", "application/json", "text/plain", "text/xml", "application/xml"):
        return Check(ok=False, why="the link returns a web page, not the file", size=size)
    least = MIN_VIDEO_BYTES if want == "video" else MIN_IMAGE_BYTES if want == "image" else 1
    if 0 <= size < least:
        return Check(ok=False, why=f"the file is empty ({size} bytes)", size=size)
    if want == "video" and kind == "image":
        return Check(ok=False, why="the clip is a picture file", size=size)
    return Check(ok=True, size=size)


def _header(r, name: str) -> str:
    try:
        v = r.headers.get(name)
    except Exception:  # noqa: BLE001
        return ""
    return v if isinstance(v, str) else ""


def _first_bytes(r, n: int) -> bytes:
    try:
        for block in r.iter_content(n):
            return block if isinstance(block, (bytes, bytearray)) else b""
    except Exception:  # noqa: BLE001 - a body we cannot read says nothing
        pass
    return b""


def _total_size(r, code: int) -> int:
    m = re.search(r"/(\d+)\s*$", _header(r, "Content-Range"))
    if m:
        return int(m.group(1))
    length = _header(r, "Content-Length")
    return int(length) if code == 200 and length.isdigit() else -1


def _r2_head(loc: Tuple[str, str], want: str, timeout: float) -> Optional[Check]:
    """One of our objects, through the S3 API (not the rate-limited public link). None: ask the public link."""
    bucket, key = loc
    for attempt in range(2):
        try:
            headers = r2._auth_headers("HEAD", key, {}, hashlib.sha256(b"").hexdigest(), bucket=bucket)
            headers["Accept-Encoding"] = "identity"      # else Cloudflare drops Content-Length
            resp = requests.head(r2._object_url(key, bucket), headers=headers, timeout=(5, timeout))
            code = int(resp.status_code)
        except Exception:  # noqa: BLE001 - retried, then the public link decides
            time.sleep(0.5 * (attempt + 1))
            continue
        if code == 404:
            return Check(ok=False, reached=False, why="it is not in storage (R2 answered 404)")
        if code == 200:
            length = _header(resp, "Content-Length")
            return _verdict(int(length) if length.isdigit() else -1, _header(resp, "Content-Type"), b"", want)
        if code in (401, 403):
            return None                                 # these keys cannot read that bucket
        time.sleep(0.5 * (attempt + 1))
    return None


def _range_get(url: str, want: str, timeout: float, tries: int) -> Check:
    last = ""
    for attempt in range(max(1, tries)):
        r = None
        try:
            r = requests.get(url, headers={"Range": "bytes=0-4095", "User-Agent": config.USER_AGENT},
                             timeout=(5, timeout), stream=True)
            code = int(getattr(r, "status_code", 0) or 0)
            if code in (200, 206):
                return _verdict(_total_size(r, code), _header(r, "Content-Type"), _first_bytes(r, 4096), want)
            last = f"HTTP {code}"
            if code in (400, 401, 403, 404, 410):
                return Check(ok=False, reached=False, why=f"the link answers {last}")
        except requests.RequestException as e:
            last = type(e).__name__
        finally:
            if r is not None:
                try:
                    r.close()
                except Exception:  # noqa: BLE001
                    pass
        if attempt + 1 < tries:
            time.sleep(0.4 * (attempt + 1))
    return Check(ok=False, reached=False, why=f"the link cannot be read ({last or 'no answer'})")


def reach(url: str, want: str = "file", timeout: Optional[float] = None, tries: int = 3) -> Check:
    """
    Whether the renderer can load `url`: a file on this disk by its size, our
    R2 objects by an S3 HEAD, any other link by a small range GET (retried on
    a timeout or a 5xx, never on a 4xx). `want` is "video", "image" or "file":
    a stub, an error page or a picture posing as a clip is not a file.
    """
    t = float(timeout or config.QUALITY_HTTP_TIMEOUT)
    url = str(url or "")
    if not url:
        return Check(ok=False, reached=False, why="no link")
    if url.startswith("data:"):
        return Check(ok=True)
    if url.startswith("blob:"):
        return Check(ok=False, reached=False, why="a link only the editor's browser could open")
    path = local_path(url)
    if path:
        if not os.path.isfile(path):
            return Check(ok=False, reached=False, why="the file is not on this machine")
        try:
            size = os.path.getsize(path)
            with open(path, "rb") as fh:
                head = fh.read(64)
        except OSError:
            return Check(ok=False, reached=False, why="the file cannot be read")
        got = _verdict(size, "", head, want)
        got.local = path
        return got
    if not url.startswith(("http://", "https://")):
        return Check(ok=False, reached=False, why="not a link the renderer can load")
    loc = r2.locate(url) if r2._creds() else None
    if loc:
        got = _r2_head(loc, want, t)
        if got is not None:
            return got
    return _range_get(url, want, t, tries)


def _fetch(url: str, dest: str, timeout: float) -> str:
    """Download a still to `dest` (our R2 objects through the S3 API); "" when it cannot be had."""
    loc = r2.locate(url) if r2._creds() else None
    for attempt in range(2):
        data = None
        if loc:
            try:
                data = r2.get_bytes(loc[1], bucket=loc[0], timeout=int(timeout) + 5)
                if data is None:
                    return ""
            except Exception:  # noqa: BLE001 - the public link below
                data = None
        if data is None:
            try:
                resp = requests.get(url, timeout=(5, timeout), headers={"User-Agent": config.USER_AGENT})
                code = int(resp.status_code)
                if code in (400, 401, 403, 404, 410):
                    return ""
                if code == 200:
                    data = resp.content
            except requests.RequestException:
                data = None
        if isinstance(data, (bytes, bytearray)) and data:
            if len(data) > MAX_IMAGE_BYTES:
                return ""
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(data)
            return dest
        time.sleep(0.5 * (attempt + 1))
    return ""


def decode_image(path: str) -> Tuple[bool, int, int, str]:
    """(decodes, width, height, why): Pillow first, ffmpeg for what Pillow cannot read."""
    why = ""
    try:
        from PIL import Image
        with Image.open(path) as im:
            im.load()
            w, h = im.size
        return True, int(w), int(h), ""
    except Exception as e:  # noqa: BLE001 - ffmpeg below decides
        why = type(e).__name__
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", path],
                           capture_output=True, text=True, timeout=30)
        dims = [int(x) for x in (p.stdout or "").strip().split(",")[:2] if x.strip().isdigit()]
        d = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-frames:v", "1", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=60)
        if d.returncode == 0 and len(dims) == 2 and min(dims) > 0:
            return True, dims[0], dims[1], ""
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return False, 0, 0, f"the picture cannot be decoded ({why or 'unreadable'})"


_NETWORK_WORDS = ("resolve", "connection", "timed out", "timeout", "network", "server returned", "http error",
                  "tls", "ssl", "unreachable", "i/o error")


def probe_video(src: str, timeout: float = 30) -> Check:
    """A clip's real length and size by ffprobe (a file on disk or a link). A link that
    could not be read in time is unverified, never broken: the range GET was the test."""
    cmd = ["ffprobe", "-v", "error"]
    remote = src.startswith(("http://", "https://"))
    if remote:
        cmd += ["-rw_timeout", str(int(timeout * 1_000_000))]
    cmd += ["-show_entries", "stream=codec_type,codec_name,width,height,duration:format=duration",
            "-of", "json", src]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout + 5)
    except subprocess.TimeoutExpired:
        return Check(ok=True, unverified=True, why="the clip's length could not be read in time")
    except OSError:
        return Check(ok=True, unverified=True, why="ffprobe is not available")
    err = (p.stderr or "").strip()
    try:
        info = json.loads(p.stdout or "{}") or {}
    except ValueError:
        info = {}
    streams = info.get("streams") or []
    if p.returncode != 0 or not streams:
        low = err.lower()
        if remote and any(w in low for w in _NETWORK_WORDS) and "invalid data" not in low and "moov" not in low:
            return Check(ok=True, unverified=True, why="the clip could not be probed over the network")
        return Check(ok=False, why=f"the clip cannot be decoded ({err[-90:] or 'unreadable'})")
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        return Check(ok=False, why="the file has no picture")
    secs = _num(video.get("duration")) or _num((info.get("format") or {}).get("duration"))
    if secs <= 0:
        return Check(ok=False, why="the clip has no length")
    return Check(ok=True, seconds=secs, width=int(_num(video.get("width"))), height=int(_num(video.get("height"))))


def _probe_source(url: str) -> str:
    """What ffprobe reads: a file, a signed S3 link for our own objects, or the link itself."""
    path = local_path(url)
    if path:
        return path
    loc = r2.locate(url) if r2._creds() else None
    if loc:
        try:
            return r2.presign(loc[1], bucket=loc[0], expires=900)
        except Exception:  # noqa: BLE001 - the public link
            pass
    return url


# --------------------------------------------------------------------------- #
# The image looks' pictures (Main.tsx lookPictures, kept in step)
# --------------------------------------------------------------------------- #

def _still_of(m) -> str:
    if not isinstance(m, dict) or not m.get("url"):
        return ""
    if m.get("type") == "image":
        return str(m["url"])
    th = m.get("thumbnail")
    return th.strip() if isinstance(th, str) else ""


def look_pictures(ov: dict, scenes: List[dict]) -> Optional[List[str]]:
    """The stills an image look will draw, or None for a look that shows none."""
    from . import treatments
    t = templates.get(ov.get("template") or "") or {}
    tags = set(t.get("tags") or [])
    variant = str(ov.get("variant") or (t.get("defaults") or {}).get("variant") or "")
    many = variant == "collage" or "stills" in tags
    kind = ov.get("type")
    if not many and not (kind in PHOTO_CARDS or variant in STILL_LOOKS or "still" in tags):
        return None
    person = kind == "name-card" or bool(set(t.get("cues") or []) & PERSON_CUES)
    out: List[str] = []

    def add(m) -> None:
        s = _still_of(m)
        if s and s not in out:
            out.append(s)
    own = [m for m in (ov.get("media") or []) if isinstance(m, dict)]
    for m in own:
        if m.get("source") != "library":
            add(m)
    by_id = {s.get("id"): s for s in scenes}
    for sid in ov.get("mediaFrom") or []:
        add((by_id.get(sid) or {}).get("media"))
    for m in own:
        if m.get("source") == "library":
            add(m)
    if not out or (many and len(out) < 2):
        start = int(ov.get("startFrame") or 0)
        at = next((k for k, s in enumerate(scenes)
                   if int(s.get("startFrame") or 0) <= start < int(s.get("startFrame") or 0)
                   + int(s.get("durationInFrames") or 0)), -1)
        if at >= 0:
            add(scenes[at].get("media"))
            subject = str((scenes[at].get("semanticMetadata") or {}).get("subject") or "")
            d = 1
            while not person and d <= PICTURE_NEAR and len(out) < (6 if many else 1):
                for j in (at - d, at + d):
                    if 0 <= j < len(scenes) and treatments.same_subject(
                            subject, str((scenes[j].get("semanticMetadata") or {}).get("subject") or "")):
                        add(scenes[j].get("media"))
                d += 1
            if many:
                for k in range(at + 1, len(scenes)):
                    if len(out) >= 6:
                        break
                    add(scenes[k].get("media"))
    return out[: 6 if many else max(1, len(own))]


def _web_photo_look(ov: dict) -> bool:
    t = templates.get(ov.get("template") or "") or {}
    return ov.get("template") == "PHOTO_PIP_V1" or ov.get("variant") == "pip" \
        or ("subject-photo" in (t.get("cues") or []) and "still" in (t.get("tags") or []))


def text_scene(doc: dict, s: dict) -> None:
    """The scene's own line as a full-screen text graphic: what shows when nothing could be found for it."""
    text = " ".join(str(s.get("text") or "").split())[:160]
    tid = next((x for x in TEXT_LOOKS if templates.get(x)), "")
    anim = templates.resolve(tid, props={"text": text}) if tid else {"type": "typewriter"}
    for k in ("seconds", "sfx", "_motion"):
        anim.pop(k, None)
    anim.setdefault("text", text)
    s["media"] = {"type": "animation", "url": "", "source": "template"}
    s["animation"] = anim
    s["visualType"] = "animation"
    s["reviewRequired"] = True
    s["reviewReason"] = ("Nothing usable was found for this line, so it is shown as text - "
                         "use Find footage to give it a clip")
    # The text card the last resort laid over the scene would show the words twice.
    start, length = int(s.get("startFrame") or 0), int(s.get("durationInFrames") or 0)
    overlays = doc.get("overlays")
    if isinstance(overlays, list):
        overlays[:] = [ov for ov in overlays if not (isinstance(ov, dict) and ov.get("type") == "highlight"
                                                     and int(ov.get("startFrame") or -1) == start
                                                     and int(ov.get("durationInFrames") or -1) == length)]


def _how(asset) -> str:
    """How the ladder filled a scene, in words."""
    if getattr(asset, "source", "") == "generated":
        return "an AI picture"
    if getattr(asset, "kind", "") == "image":
        return "a picture"
    if "library" in str(getattr(asset, "review_reason", "") or "").lower():
        return "a library clip"
    return "a spare clip from the footage pools"


def _kind_of(how: str) -> str:
    """The report's bucket for a repair: replaced / held / graphic / text / none."""
    if how.startswith(("a library", "a spare", "a picture", "an AI")):
        return "replaced"
    if how.startswith("held"):
        return "held"
    if how.startswith("a motion graphic"):
        return "graphic"
    if how.startswith("its line"):
        return "text"
    return "none"


# --------------------------------------------------------------------------- #
# The gate
# --------------------------------------------------------------------------- #

class NarrationMissing(RuntimeError):
    """The narration cannot be read: nothing can be drawn over it."""


class Gate:
    """One render's quality gate. handler.do_render drives it; see the module notes."""

    def __init__(self, doc: dict, work: str, report: Callable = None):
        self.doc = doc
        self.work = work or config.WORK_DIR
        self.report_fn = report
        self.fps = max(1, int(doc.get("fps") or 30))
        self.scenes_in = len(doc.get("scenes") or [])
        self.found: Counter = Counter()
        self.fixed: Counter = Counter()
        self.repairs: List[dict] = []
        self.notes: List[str] = []
        self.unresolved: List[dict] = []
        self.seconds: Dict[str, float] = {}
        self.fetched: Dict[str, str] = {}       # a remote still -> the copy fetched to decode it
        self.checked = 0
        self.unverified = 0
        self.audited = False
        self._report: Optional[dict] = None
        self._rows = 0
        self._lock = threading.Lock()
        LAST.clear()
        LAST["gate"] = self

    # ---- talking ------------------------------------------------------------
    def _say(self, step: str, pct: int = None) -> None:
        if callable(self.report_fn):
            try:
                self.report_fn(step, pct)
            except Exception:  # noqa: BLE001 - progress never costs the video
                pass

    def _event(self, event: str, message: str, scene: Optional[int] = None, level: str = "info",
               data: Optional[dict] = None, always: bool = False) -> None:
        if not always:
            with self._lock:
                self._rows += 1
                if self._rows > EVENT_ROWS:
                    return
        events.emit("quality", event, level=level, scene=scene, message=message, data=data)

    # ---- before the render --------------------------------------------------
    def before_render(self) -> int:
        """Check the document and repair it. Returns how many scenes were repaired."""
        if not config.QUALITY_GATE:
            return 0
        t0 = time.time()
        self._say("Checking every scene before the render")
        checks = self._check_all()
        self.seconds["checks"] = round(time.time() - t0, 1)
        self._narration(checks)
        t1 = time.time()
        problems = self._scene_problems(checks)
        self._thumbnails(checks)
        self._overlay_media(checks)
        self._music(checks)
        self._sounds()
        repaired = 0
        if problems:
            self._say(f"Repairing {_n(len(problems), 'scene')} before the render")
            repaired = self._replace(problems, "before the render")
        self._local_stills()
        self._look_sources()
        self.no_empty_scenes()
        from . import timeline
        timeline.drop_invalid_overlays(self.doc)
        self.seconds["repairs"] = round(time.time() - t1, 1)
        self.audited = True
        line = self.summary()
        print(f"[quality] before the render: {line} (checked {self.checked} files in "
              f"{self.seconds['checks']:.1f} s, repairs {self.seconds['repairs']:.1f} s)", flush=True)
        self._event("checked", line, always=True,
                    data={"found": dict(self.found), "fixed": dict(self.fixed), "checked": self.checked,
                          "unverified": self.unverified, "seconds": dict(self.seconds)})
        self._say(line)
        return repaired

    def _check_all(self) -> Dict[str, Check]:
        """Every file the renderer will load, checked once, QUALITY_PARALLEL at a time."""
        doc = self.doc
        want: Dict[str, str] = {}
        probe: set = set()

        def add(url, kind: str) -> None:
            url = str(url or "")
            if not url or url.startswith(("data:", "bgm://")):
                return
            if kind == "file" and want.get(url) in ("video", "image"):
                return
            want[url] = kind
        for s in doc.get("scenes") or []:
            m = s.get("media") or {}
            if m.get("type") in ("video", "image") and m.get("url"):
                add(m["url"], m["type"])
                # A clip whose length the document does not know plays at 1x: measure it. A file
                # on this disk always (it costs nothing); a link only then (it is a request).
                if m["type"] == "video" and (local_path(m["url"]) or not declared_seconds(m)):
                    probe.add(str(m["url"]))
            if isinstance(m.get("thumbnail"), str) and m["thumbnail"]:
                add(m["thumbnail"], "file")
            anim = s.get("animation")
            for x in (anim.get("media") or []) if isinstance(anim, dict) else []:
                if isinstance(x, dict) and x.get("url"):
                    add(x["url"], "image" if (x.get("type") or "image") == "image" else "file")
        for ov in doc.get("overlays") or []:
            for x in (ov.get("media") or []) if isinstance(ov, dict) else []:
                if isinstance(x, dict) and x.get("url"):
                    add(x["url"], "image" if (x.get("type") or "image") == "image" else "file")
        for key in ("audio", "bgm"):
            m = doc.get(key)
            if isinstance(m, dict) and m.get("url"):
                add(m["url"], "file")
        out: Dict[str, Check] = {}
        if not want:
            return out
        deadline = time.time() + config.QUALITY_AUDIT_SECONDS
        pool = ThreadPoolExecutor(max_workers=max(1, min(config.QUALITY_PARALLEL, len(want))))
        futures = {pool.submit(self._check_one, url, kind, url in probe): url for url, kind in want.items()}
        done, late = _wait(futures, timeout=max(1.0, deadline - time.time()))
        pool.shutdown(wait=False, cancel_futures=True)
        for f in done:
            try:
                out[futures[f]] = f.result()
            except Exception as e:  # noqa: BLE001 - a check that broke says nothing
                out[futures[f]] = Check(ok=True, unverified=True, why=f"the check failed ({type(e).__name__})")
        for f in late:
            out[futures[f]] = Check(ok=True, unverified=True, why="not checked in time")
        self.checked = len(out)
        self.unverified = sum(1 for c in out.values() if c.unverified)
        if late:
            self.notes.append(f"{_n(len(late), 'file')} not checked in time - used as they are")
        return out

    def _check_one(self, url: str, kind: str, probe: bool) -> Check:
        got = reach(url, kind)
        if not got.ok:
            return got
        if kind == "image":
            return self._decode(url, got)
        if kind == "video" and probe:
            measured = probe_video(_probe_source(url) if not got.local else got.local)
            measured.size = got.size
            measured.local = got.local
            return measured
        return got

    def _decode(self, url: str, got: Check) -> Check:
        path = got.local
        if not path:
            ext = os.path.splitext(urllib.parse.urlparse(url).path)[1][:6] or ".img"
            dest = os.path.join(self.work, "qa", hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ext)
            path = _fetch(url, dest, config.QUALITY_HTTP_TIMEOUT)
            if not path:
                return Check(ok=False, reached=False, why="the picture could not be downloaded")
            self.fetched[url] = path
        ok, w, h, why = decode_image(path)
        if not ok:
            return Check(ok=False, why=why, local=path)
        if max(w, h) < config.QUALITY_MIN_IMAGE_SIDE or min(w, h) < 64:
            return Check(ok=False, tiny=True, why=f"the picture is tiny ({w}x{h})", width=w, height=h, local=path)
        return Check(ok=True, width=w, height=h, local=path, size=got.size)

    def _narration(self, checks: Dict[str, Check]) -> None:
        url = str((self.doc.get("audio") or {}).get("url") or "")
        got = checks.get(url) if url else None
        if got is None or got.ok or got.unverified:
            return
        self.found["narration"] += 1
        # Only a link that answers "no" is certain; a file path is the job's own
        # business (do_render resolves the narration's link itself).
        definite = url.startswith(("http://", "https://")) and ("answers HTTP 4" in got.why or "404" in got.why)
        self._event("narration", f"the narration cannot be read ({got.why})", level="error" if definite else "warning",
                    always=True)
        if definite:
            raise NarrationMissing(f"The narration cannot be read ({got.why}). Nothing was rendered: upload the "
                                   "voiceover again in the editor and render once more.")
        self.notes.append(f"the narration did not answer the check ({got.why}); the render reads it itself")

    def _scene_problems(self, checks: Dict[str, Check]) -> Dict[int, Tuple[str, str]]:
        scenes = self.doc.get("scenes") or []
        problems: Dict[int, Tuple[str, str]] = {}
        for i, s in enumerate(scenes):
            m = s.get("media") or {}
            kind = m.get("type")
            if kind == "animation":
                continue
            if kind not in ("video", "image") or not m.get("url"):
                problems[i] = ("empty", "the scene has no picture")
                continue
            got = checks.get(str(m["url"]))
            if got is None or got.unverified:
                continue
            if not got.ok:
                problems[i] = ("unreachable" if not got.reached else "tiny" if got.tiny else "broken", got.why)
            elif kind == "video" and got.seconds > 0:
                p = self._cover(i, scenes, got.seconds)
                if p:
                    problems[i] = p
        for i, why in gapfill.find_repeats(self.doc):
            problems.setdefault(i, ("repeat", f"it repeats an earlier scene ({why})"))
        for i, (code, why) in sorted(problems.items()):
            self.found[code] += 1
            self._event("problem", f"scene {i + 1} ({_clock(int(scenes[i].get('startFrame') or 0) / self.fps)}): "
                                   f"{code} - {why}", scene=i, level="warning",
                        data={"problem": code, "media": short((scenes[i].get("media") or {}).get("url"))})
        return problems

    def _cover(self, i: int, scenes: List[dict], real: float) -> Optional[Tuple[str, str]]:
        """None when scene i's clip covers it (its measured length recorded), else the problem."""
        m = scenes[i]["media"]
        need = scene_need(scenes, i, self.fps)
        declared = declared_seconds(m)
        covered = real / play_rate(declared, need)
        tol = TOLERANCE_FRAMES / self.fps
        if covered >= need - tol:
            if abs(declared - real) > 0.05:
                m["clipSeconds"] = round(real, 2)          # the renderer plays it at its true speed
            return None
        if real / MIN_RATE >= need - tol:
            m["clipSeconds"] = round(real, 2)              # slowed just enough to fill its scene
            self.found["timing"] += 1
            self._fixed(i, "timing", f"the clip ({real:.1f} s) would have frozen for {need - covered:.1f} s",
                        "slowed to fill its scene")
            return None
        return ("short", f"the clip is {real:.1f} s long for a {need:.1f} s scene and would freeze for "
                         f"{need - real / MIN_RATE:.1f} s")

    def _fixed(self, i: Optional[int], kind: str, detail: str, how: str, stage: str = "before the render") -> None:
        scenes = self.doc.get("scenes") or []
        s = scenes[i] if i is not None and 0 <= i < len(scenes) else {}
        self.fixed[kind] += 1
        self.repairs.append({"scene": s.get("id", ""), "at": _clock(int(s.get("startFrame") or 0) / self.fps) if s else "",
                             "problem": kind, "detail": detail, "how": how, "stage": stage})
        self._event("repaired", (f"scene {i + 1}: " if s else "") + f"{detail} - {how}", scene=i,
                    data={"problem": kind, "how": how})

    def _thumbnails(self, checks: Dict[str, Check]) -> None:
        """A still the looks and the graphics' backdrops borrow that cannot load is dropped:
        one dead link fails every render chunk that draws it (2026-10-01)."""
        for i, s in enumerate(self.doc.get("scenes") or []):
            m = s.get("media") or {}
            th = m.get("thumbnail")
            got = checks.get(th) if isinstance(th, str) and th else None
            if got is not None and not got.ok and not got.unverified:
                m.pop("thumbnail", None)
                self.found["thumbnail"] += 1
                self._fixed(i, "thumbnail", f"its still ({short(th)}) cannot load: {got.why}",
                            "dropped - the looks borrow another picture")

    def _overlay_media(self, checks: Dict[str, Check]) -> None:
        """Pictures an overlay or a full-screen graphic draws that cannot load are taken out."""
        def bad(m) -> str:
            url = m.get("url") if isinstance(m, dict) else ""
            got = checks.get(str(url)) if url else None
            return got.why if got is not None and not got.ok and not got.unverified else ""
        overlays = self.doc.get("overlays")
        if isinstance(overlays, list):
            keep = []
            for n, ov in enumerate(overlays):
                media = ov.get("media") if isinstance(ov, dict) else None
                if not isinstance(media, list) or not media:
                    keep.append(ov)
                    continue
                good = [m for m in media if not bad(m)]
                if len(good) == len(media):
                    keep.append(ov)
                    continue
                why = next(bad(m) for m in media if bad(m))
                self.found["overlay"] += 1
                ov["media"] = good
                fate = self._after_loss(ov)
                if fate == "dropped":
                    self._fixed(None, "overlay", f"graphic {n + 1} ({ov.get('template') or ov.get('type')}): "
                                                 f"its picture cannot load ({why})", "left out")
                    continue
                self._fixed(None, "overlay", f"graphic {n + 1} ({ov.get('template') or ov.get('type')}): "
                                             f"{_n(len(media) - len(good), 'picture')} cannot load ({why})",
                            "shown as two labels" if fate == "labels" else "the broken picture taken out")
                keep.append(ov)
            overlays[:] = keep
        for i, s in enumerate(self.doc.get("scenes") or []):
            anim = s.get("animation")
            media = anim.get("media") if isinstance(anim, dict) else None
            if isinstance(media, list) and media:
                good = [m for m in media if not bad(m)]
                if len(good) != len(media):
                    anim["media"] = good
                    self.found["overlay"] += 1
                    self._fixed(i, "overlay", "a picture of its graphic cannot load", "taken out")

    @staticmethod
    def _after_loss(ov: dict) -> str:
        """What an overlay that lost pictures becomes: "kept", "labels" (a split back to its label pills) or "dropped"."""
        from . import timeline
        media = ov.get("media") or []
        if ov.get("type") == "split" and len(media) < 2:
            ov["type"] = "label-boxes"
            if templates.get("TEXT_DUAL_LABELS_V1"):
                ov["template"] = "TEXT_DUAL_LABELS_V1"
            ov.pop("variant", None)
            ov.pop("media", None)
            return "labels"
        if not media:
            ov.pop("media", None)
            if _web_photo_look(ov):
                return "dropped"                 # an empty photo window is worse than none
            if ov.get("type") in PHOTO_CARDS and not timeline._borrows_pictures(ov):
                return "dropped"
        return "kept"

    def _music(self, checks: Dict[str, Check]) -> None:
        """The music bed must load: a missing bundled track or a dead link failed a whole render."""
        from . import timeline
        bgm = self.doc.get("bgm")
        if not isinstance(bgm, dict) or not bgm.get("url"):
            return
        url = str(bgm["url"])
        if url.startswith("bgm://"):
            name = timeline.current_bgm_url(url)[len("bgm://"):]
            if _bgm_file(name):
                if url != f"bgm://{name}":
                    bgm["url"] = f"bgm://{name}"
                return
            why = f"the music track '{name}' is not in this renderer"
        else:
            got = checks.get(url)
            if got is None or got.ok or got.unverified:
                return
            why = f"the music file cannot be read ({got.why})"
        self.found["music"] += 1
        new = _bundled_bgm(self.doc, avoid=url)
        if new:
            bgm["url"] = new
            how = f"the bundled '{new[len('bgm://'):]}' bed plays instead"
        else:
            self.doc["bgm"] = None
            how = "the video plays without music"
        self._fixed(None, "music", why, how)

    def _sounds(self) -> None:
        """Sound effects with no file are left out (the renderer would 404 on them)."""
        sfx = self.doc.get("sfx")
        if not isinstance(sfx, list) or not sfx:
            return
        have = templates.sfx_files()
        if not have:
            return
        keep = [fx for fx in sfx if not isinstance(fx, dict) or fx.get("name") in have]
        if len(keep) != len(sfx):
            gone = sorted({str(fx.get("name")) for fx in sfx if isinstance(fx, dict) and fx.get("name") not in have})
            self.doc["sfx"] = keep
            self.found["sound"] += len(sfx) - len(keep)
            self._fixed(None, "sound", f"{_n(len(sfx) - len(keep), 'sound effect')} with no file ({', '.join(gone[:3])})",
                        "left out")

    # ---- the repairs ----------------------------------------------------------
    def _ladder_ok(self) -> bool:
        return bool(CONTEXT.get("ladder") and config.FALLBACK_FILL and self.work)

    def _library(self, plan: dict):
        if plan.get("library") is not None:
            return plan["library"]
        if CONTEXT.get("library") is not None:
            return CONTEXT["library"]
        loader = CONTEXT.get("library_loader")
        if callable(loader):
            CONTEXT["library_loader"] = None              # loaded once per job
            try:
                CONTEXT["library"] = loader()
            except Exception as e:  # noqa: BLE001 - the ladder's other steps still run
                print(f"[quality] clip library not loaded: {type(e).__name__}: {str(e)[:100]}", flush=True)
            return CONTEXT.get("library")
        return None

    def _ladder(self, order: List[int], banned: List[gapfill.Shot],
                problems: Dict[int, Tuple[str, str]]) -> Dict[int, str]:
        """The fallback ladder for the cleared scenes (never a shot another scene shows, never a banned one)."""
        scenes = self.doc["scenes"]
        plan = gapfill.CONTEXT if CONTEXT.get("plan") and gapfill.CONTEXT.get("jobs") else {}
        jobs = [gapfill.job_for(s, k, self.fps, plan.get("jobs")) for k, s in enumerate(scenes)]
        todo = set(order)
        used = gapfill.Used()
        for k, s in enumerate(scenes):
            shot = None if k in todo else gapfill.Shot.of_scene(s, self.fps)
            if shot is not None:
                used.add(k, shot)
        for n, shot in enumerate(banned):
            used.add(-1 - n, shot)                          # what failed is never taken again
        story = CONTEXT.get("story")
        if isinstance(story, dict) and story and not plan:
            try:
                from . import media, vision
                vision.set_story(story)
                media.set_story_kind(str(story.get("kind") or ""))
            except Exception:  # noqa: BLE001
                pass
        allow_generated = bool(CONTEXT.get("allow_generated", config.QUALITY_REPAIR_GENERATED))
        results: Dict[int, Any] = {}
        try:
            gapfill.fill_empty(jobs, results, self.work, library=self._library(plan),
                               require_cc=bool(plan.get("require_cc", CONTEXT.get("require_cc", False))),
                               # fill_empty asks the image model only when this is False
                               youtube_only=bool(plan.get("youtube_only")) or not allow_generated,
                               indices=order, used=used, seconds=config.QUALITY_REPAIR_SECONDS,
                               scene_seconds=config.QUALITY_REPAIR_SCENE_SECONDS, label="quality gate")
        except Exception as e:  # noqa: BLE001 - the last resort below
            print(f"[quality] the ladder failed: {type(e).__name__}: {str(e)[:120]}", flush=True)
            return {}
        out: Dict[int, str] = {}
        for i, asset in results.items():
            if asset is None or not 0 <= i < len(scenes):
                continue
            how = _how(asset)
            gapfill.apply_asset(scenes[i], asset)
            m = scenes[i]["media"]
            if m.get("type") == "video" and declared_seconds(m) and \
                    declared_seconds(m) / MIN_RATE < scene_need(scenes, i, self.fps) - TOLERANCE_FRAMES / self.fps:
                scenes[i]["media"] = {"type": "color", "url": "", "source": "none"}   # too short as well
                for k in ("assetId", "sourceUrl", "moment"):
                    scenes[i].get("semanticMetadata", {}).pop(k, None)
                continue
            scenes[i]["reviewReason"] = (f"The quality check replaced this scene's picture ({problems[i][1]}) "
                                         f"with {how} - check it fits")
            out[i] = how
        return out

    def _replace(self, problems: Dict[int, Tuple[str, str]], stage: str) -> int:
        """
        Every scene in `problems` gets a new picture: the fallback ladder (when
        this job may search), then the last resort (the line's graphic, the
        neighbouring shot held over it), then its line as a text graphic. The
        scene's own failed shot - and every moment of its source - is never
        taken again. Returns how many scenes were repaired.
        """
        scenes = self.doc.get("scenes") or []
        order = sorted(i for i in problems if 0 <= i < len(scenes))
        if not order:
            return 0
        info: Dict[str, dict] = {}
        banned: List[gapfill.Shot] = []
        for i in order:
            s = scenes[i]
            code, why = problems[i]
            sid = str(s.get("id") or f"#{i}")
            s["id"] = s.get("id") or sid
            info[sid] = {"scene": sid, "index": i, "at": _clock(int(s.get("startFrame") or 0) / self.fps),
                         "problem": code, "detail": why, "stage": stage}
            old = gapfill.Shot.of_scene(s, self.fps)
            if old is not None:
                old.start, old.chain = None, False         # every moment of a failed source
                banned.append(old)
            s["media"] = {"type": "color", "url": "", "source": "none"}
            s.pop("animation", None)
            sem = s.setdefault("semanticMetadata", {})
            for k in ("assetId", "sourceUrl", "moment"):
                sem.pop(k, None)
        if self._ladder_ok():
            for i, how in self._ladder(order, banned, problems).items():
                info[str(scenes[i]["id"])]["how"] = how
        empties = [str(s.get("id")) for s in scenes if gapfill._empty(s)]
        gapfill.hold_or_animate(self.doc, label=f"quality gate, {stage}")
        now = {str(s.get("id")): s for s in self.doc.get("scenes") or []}
        for sid in empties:
            s = now.get(sid)
            if sid not in info:
                continue
            if s is None:
                info[sid]["how"] = "held over by its neighbouring shots"
            elif (s.get("media") or {}).get("type") == "animation":
                info[sid]["how"] = "a motion graphic of its line"
        for sid in self.no_empty_scenes():
            if sid in info:
                info[sid].setdefault("how", "its line as a full-screen text graphic")
        for sid, rec in info.items():
            rec.setdefault("how", "not repaired")
            kind = _kind_of(rec["how"])
            if kind == "none":
                self.unresolved.append({"kind": rec["problem"], "scene": sid, "at": rec["at"],
                                        "what": f"scene at {rec['at']}: {rec['detail']}"})
            else:
                self.fixed[kind] += 1
            self.repairs.append({k: v for k, v in rec.items() if k != "index"})
            self._event("repaired", f"scene {rec['index'] + 1} ({rec['at']}): {rec['problem']} - {rec['detail']} "
                                    f"-> {rec['how']}", scene=rec["index"],
                        data={"problem": rec["problem"], "how": rec["how"], "stage": stage})
        return len(info)

    def _local_stills(self, seconds: float = 30.0) -> int:
        """
        A frame of every clip on this disk that has no still. The looks show a
        clip's scene as "a frame of its clip" and a graphic's backdrop is "the
        nearest clip, blurred" - both drawn from the clip's still, which only a
        published scene has. A build that renders before publishing had none:
        those looks drew nothing and the backdrops were flat. Returns how many.
        """
        todo = []
        for s in self.doc.get("scenes") or []:
            m = s.get("media") or {}
            path = local_path(m.get("url")) if m.get("type") == "video" else ""
            if path and os.path.isfile(path) and not m.get("thumbnail"):
                todo.append((s, m, path))
        if not todo:
            return 0
        folder = os.path.join(self.work, "qa")
        os.makedirs(folder, exist_ok=True)

        def grab(item) -> str:
            s, m, path = item
            out = os.path.join(folder, f"still_{s.get('id') or id(s)}_{hashlib.sha1(path.encode()).hexdigest()[:8]}.jpg")
            at = min(max(0.0, declared_seconds(m) / 2), 30.0) if declared_seconds(m) else 0.5
            try:
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.2f}", "-i", path, "-frames:v", "1",
                                "-vf", "scale='min(1280,iw)':-2", "-q:v", "3", out],
                               capture_output=True, timeout=30)
            except (OSError, subprocess.TimeoutExpired):
                return ""
            return out if os.path.isfile(out) and os.path.getsize(out) > 0 else ""
        pool = ThreadPoolExecutor(max_workers=min(8, len(todo)))
        futures = {pool.submit(grab, item): item for item in todo}
        done, _late = _wait(futures, timeout=seconds)
        pool.shutdown(wait=False, cancel_futures=True)
        made = 0
        for f in done:
            try:
                still = f.result()
            except Exception:  # noqa: BLE001 - that clip keeps no still, as before
                still = ""
            if still:
                futures[f][1]["thumbnail"] = still
                made += 1
        return made

    def no_empty_scenes(self) -> List[str]:
        """Every scene still without a picture becomes its line as a full-screen text graphic. Returns their ids."""
        out = []
        for s in self.doc.get("scenes") or []:
            if gapfill._empty(s):
                text_scene(self.doc, s)
                out.append(str(s.get("id")))
        return out

    def _look_sources(self) -> None:
        """
        Every look that shows pictures gets at least one it can load: scenes it
        names that are gone (held over) or have no still are let go, a look
        left with none is bound again from the story's own pictures
        (treatments.bind_look_pictures), else left out - a look without a
        picture draws nothing but still plays its sound.
        """
        doc = self.doc
        scenes = doc.get("scenes") or []
        overlays = doc.get("overlays")
        if not isinstance(overlays, list) or not overlays:
            return
        by_id = {s.get("id"): s for s in scenes}
        keep = []
        for n, ov in enumerate(overlays):
            if not isinstance(ov, dict):
                keep.append(ov)
                continue
            mf = ov.get("mediaFrom")
            if isinstance(mf, list) and mf:
                live = [x for x in mf if _still_of((by_id.get(x) or {}).get("media"))]
                if len(live) != len(mf):
                    if live:
                        ov["mediaFrom"] = live
                    else:
                        ov.pop("mediaFrom", None)
            pics = look_pictures(ov, scenes)
            if pics is None or pics:
                keep.append(ov)
                continue
            self.found["look"] += 1
            name = ov.get("template") or ov.get("type")
            again = [ov]
            try:
                from . import treatments
                treatments.bind_look_pictures(again, scenes, library=self._library({}) if self._ladder_ok() else None,
                                              story=(doc.get("meta") or {}).get("story"))
            except Exception as e:  # noqa: BLE001
                print(f"[quality] look {n + 1} not rebound: {type(e).__name__}", flush=True)
                again = []
            if again and look_pictures(again[0], scenes):
                keep.append(again[0])
                self._fixed(None, "overlay", f"graphic {n + 1} ({name}) had no picture it could show",
                            "given pictures from the story's own scenes")
            else:
                self._fixed(None, "overlay", f"graphic {n + 1} ({name}) had no picture it could show", "left out")
        overlays[:] = keep

    # ---- the report ---------------------------------------------------------
    def summary(self) -> str:
        """The app's one-liner: "Quality check: 159/159 scenes OK, 2 clips replaced"."""
        total = len(self.doc.get("scenes") or [])
        bad = len({u.get("scene") for u in self.unresolved if u.get("scene")}) + \
            sum(1 for u in self.unresolved if not u.get("scene") and u.get("kind") != "silent")
        ok = max(0, total - bad)
        f = self.fixed
        parts = []
        if f["replaced"]:
            parts.append(_n(f["replaced"], "clip") + " replaced")
        if f["held"]:
            parts.append(_n(f["held"], "line") + " held over by the next shot")
        if f["graphic"] + f["text"]:
            parts.append(_n(f["graphic"] + f["text"], "line") + " shown as a graphic")
        if f["timing"]:
            parts.append(_n(f["timing"], "clip") + " slowed to fill its scene")
        if f["thumbnail"]:
            parts.append(_n(f["thumbnail"], "broken still") + " dropped")
        if f["overlay"]:
            parts.append(_n(f["overlay"], "graphic") + " fixed")
        if f["music"]:
            parts.append("music replaced")
        if f["sound"]:
            parts.append(_n(f["sound"], "missing sound") + " left out")
        if self.unresolved:
            parts.append(_n(len(self.unresolved), "problem") + f" left ({self.unresolved[0]['what']})")
        return f"Quality check: {ok}/{total} scenes OK, " + (", ".join(parts) if parts else "nothing to fix")

    def finish(self) -> dict:
        """The report (doc.meta.quality and the job result's "quality"); one summary row in the events."""
        if self._report is not None:
            return self._report
        line = self.summary()
        out = {"summary": line, "scenes": len(self.doc.get("scenes") or []), "scenesBefore": self.scenes_in,
               "found": dict(self.found), "fixed": dict(self.fixed), "repairs": self.repairs[:200],
               "unresolved": self.unresolved[:50], "notes": self.notes[:20],
               "checked": self.checked, "unverified": self.unverified, "seconds": dict(self.seconds),
               "audited": self.audited}
        self._event("summary", line, level="warning" if self.unresolved else "info", always=True,
                    data={"found": dict(self.found), "fixed": dict(self.fixed),
                          "unresolved": len(self.unresolved)})
        extra = getattr(self.report_fn, "extra", None)
        if isinstance(extra, dict):
            extra["quality"] = line                         # rides on every later progress update
        print(f"[quality] {line}", flush=True)
        self._report = out
        return out


def mark_for_review(doc: dict, checked: Optional[dict]) -> int:
    """
    The scenes of a saved timeline that the check replaced in the finished
    video (its render copy), flagged for the editor with what was done - the
    editor shows the timeline, and the owner must see what changed. Retimed
    clips, dropped stills, graphics and sounds are not scene changes. Returns
    how many scenes were flagged.
    """
    by_id = {s.get("id"): s for s in (doc or {}).get("scenes") or []}
    n = 0
    for r in (checked or {}).get("repairs") or []:
        s = by_id.get(r.get("scene"))
        if s is None or r.get("problem") in ("timing", "thumbnail", "overlay", "music", "sound"):
            continue
        s["reviewRequired"] = True
        s["reviewReason"] = (f"The quality check replaced this scene in the finished video ({r.get('detail')}): "
                             f"{r.get('how')} - replace it here to choose its shot")
        n += 1
    return n


def _bgm_dir() -> str:
    for root in (config.REMOTION_DIR, os.path.join(templates.ROOT, "remotion")):
        d = os.path.join(root, "public", "bgm")
        if os.path.isdir(d):
            return d
    return ""


def _bgm_file(name: str) -> bool:
    d = _bgm_dir()
    return bool(d and name and os.path.isfile(os.path.join(d, f"{name}.mp3")))


def _bundled_bgm(doc: dict, avoid: str = "") -> str:
    """A bundled bed of the story's mood that this renderer has ("bgm://<track>"), "" when none."""
    from . import timeline
    meta = doc.get("meta") or {}
    bgm = doc.get("bgm") or {}
    genre = str(bgm.get("genre") or "") or timeline.bgm_mood(meta.get("story") or meta.get("brief") or {})
    fps = max(1, int(doc.get("fps") or 30))
    seconds = int(doc.get("durationInFrames") or 0) / fps
    names = []
    if genre in getattr(timeline, "BGM_TRACKS", {}):
        names.append(timeline._bgm_track(genre, seconds, str(meta.get("audioSource") or "")))
    names += [n for tracks in getattr(timeline, "BGM_TRACKS", {}).values() for n, _len in tracks]
    for name in names:
        if f"bgm://{name}" != avoid and _bgm_file(name):
            return f"bgm://{name}"
    return ""
