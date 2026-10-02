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
                      one (gapfill.fill_empty: a niche pack clip that fits its
                      line (src/packs.py), the clip library, the pools'
                      spare moments, one picture), then the last resort
                      (gapfill.hold_or_animate: the line's own graphic, the
                      neighbouring shot held over it), never a repeat; a line
                      that still has no picture becomes a full-screen text
                      graphic (a colour scene would fail the render's own
                      validation, and shows an empty frame).
  Gate.after_render   one ffmpeg pass over the finished file (blackdetect,
                      freezedetect, silencedetect); every flagged stretch is
                      mapped to its scenes and told apart from what is meant
                      to look that way (the opening fade, a dip or a cut
                      transition, a still with no motion, a graphic holding
                      still, a title card). A real defect: those scenes are
                      repaired the same way and the video is drawn ONCE more;
                      the better file is kept and what is left is reported.
  Gate.recover        a render that failed on a file its error names: those
                      scenes are repaired and the video drawn once more.
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
import traceback
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
# An entrance or cut transition darkens at most this many of a scene's first
# frames (SceneEffects.tsx: 12 + 4; transitions/timing.ts: light-leak 16), and
# a cut transition this many of the outgoing scene's last ones.
ENTRANCE_FRAMES = 16
EXIT_FRAMES = 8
CUT_TRANSITIONS = {"flash", "chromatic-flash", "glitch", "vhs-glitch", "film-burn", "light-leak", "whip-pan",
                   "zoom-punch", "shake-cut", "blur-dissolve", "luma-fade"}
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
# The scan's freeze floor: -70 dB catches the renderer's own freeze (frames
# repeated exactly) and leaves a nearly-still live shot alone (measured: a
# still frame with a small moving patch read as frozen at the default -60 dB).
FREEZE_NOISE = 0.0003
# A clip that never moves in a scene this long reads as a frozen video.
STILL_CLIP_SECONDS = 3.0
STILL_CLIP_SHARE = 0.9
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
    try:
        tid = ""
        if templates.allowed() is not None:
            # A brand kit: a full-screen text look it allows, when it allows one.
            for cue in ("headline", "statement", "fact", "key-phrase"):
                tid = next((t["id"] for t in templates.for_cue(cue) if t.get("kind") == "card"
                            and "text" in (t.get("props") or {})
                            and not ({"still", "stills"} & set(t.get("tags") or []))), "")
                if tid:
                    break
        # (Else the renderer's own text look: a line is never left empty.)
        tid = tid or next((x for x in TEXT_LOOKS if templates.get(x)), "")
        anim = templates.resolve(tid, props={"text": text}) if tid else {}
    except Exception:  # noqa: BLE001 - an unreadable registry: the renderer's own default text look
        anim = {}
    anim = anim or {"type": "typewriter"}
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
    if str(getattr(asset, "moment_key", "") or "").startswith("pack:"):
        return "a niche pack clip"
    if "library" in str(getattr(asset, "review_reason", "") or "").lower():
        return "a library clip"
    return "a spare clip from the footage pools"


def _kind_of(how: str) -> str:
    """The report's bucket for a repair: replaced / held / graphic / text / none."""
    if how.startswith(("a library", "a niche", "a spare", "a picture", "an AI")):
        return "replaced"
    if how.startswith("held"):
        return "held"
    if how.startswith("a motion graphic"):
        return "graphic"
    if how.startswith("its line"):
        return "text"
    return "none"


# --------------------------------------------------------------------------- #
# The scan of the finished file
# --------------------------------------------------------------------------- #

_BLACK = re.compile(r"black_start:\s*(-?[\d.]+)\s+black_end:\s*(-?[\d.]+)")
_FREEZE_START = re.compile(r"freeze_start:\s*(-?[\d.]+)")
_FREEZE_END = re.compile(r"freeze_end:\s*(-?[\d.]+)")
_SILENCE_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*(-?[\d.]+)")


def _streams(path: str) -> dict:
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type:format=duration",
                            "-of", "json", path], capture_output=True, text=True, timeout=60)
        info = json.loads(p.stdout or "{}") or {}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}
    kinds = {s.get("codec_type") for s in info.get("streams") or []}
    return {"video": "video" in kinds, "audio": "audio" in kinds,
            "duration": _num((info.get("format") or {}).get("duration"))}


def _pairs(text: str, start_re, end_re, until: float) -> List[Tuple[float, float]]:
    out, pending = [], None
    for line in text.splitlines():
        m = start_re.search(line)
        if m:
            pending = max(0.0, float(m.group(1)))
            continue
        m = end_re.search(line)
        if m and pending is not None:
            out.append((pending, float(m.group(1))))
            pending = None
    if pending is not None and until > pending:
        out.append((pending, until))            # still running when the file ended
    return out


def scan(path: str, timeout: Optional[float] = None) -> dict:
    """
    One ffmpeg pass over a finished video: black stretches (blackdetect), a
    frozen picture (freezedetect, on a 320 px copy) and silence (silencedetect).
    {"ok", "why", "duration", "black", "frozen", "silent", "audio", "seconds"};
    ok False when the file cannot be scanned (nothing is then judged).
    """
    t0 = time.time()
    out = {"ok": False, "why": "", "duration": 0.0, "black": [], "frozen": [], "silent": [], "audio": True,
           "seconds": 0.0}
    if not path or not os.path.isfile(path) or os.path.getsize(path) < 1024:
        out["why"] = "no finished file to scan"
        return out
    info = _streams(path)
    if not info.get("video") or info.get("duration", 0) <= 0:
        out["why"] = "the finished file could not be read"
        return out
    dur = info["duration"]
    vf = (f"scale=320:-2:flags=neighbor,blackdetect=d={config.QUALITY_BLACK_SECONDS}:pix_th=0.10,"
          f"freezedetect=n={FREEZE_NOISE}:d={config.QUALITY_FREEZE_SECONDS}")
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-map", "0:v:0", "-vf", vf, "-f", "null", "-"]
    if info.get("audio"):
        cmd += ["-map", "0:a:0", "-af", f"silencedetect=n=-50dB:d={config.QUALITY_SILENCE_SECONDS}",
                "-f", "null", "-"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout or config.QUALITY_SCAN_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        out["why"] = f"the scan did not finish ({type(e).__name__})"
        return out
    if p.returncode != 0:
        out["why"] = f"the scan failed ({(p.stderr or '')[-160:].strip()})"
        return out
    text = p.stderr or ""
    out.update(ok=True, duration=round(dur, 3), audio=bool(info.get("audio")),
               black=[(float(a), float(b)) for a, b in _BLACK.findall(text)],
               frozen=_pairs(text, _FREEZE_START, _FREEZE_END, dur),
               silent=_pairs(text, _SILENCE_START, _SILENCE_END, dur),
               seconds=round(time.time() - t0, 1))
    return out


def _covering_cards(doc: dict, f0: int, f1: int) -> bool:
    """A title card, chapter or full-screen graphic is on screen for most of frames f0..f1."""
    span = max(1, f1 - f0)
    for ov in doc.get("overlays") or []:
        if not isinstance(ov, dict):
            continue
        t = templates.get(ov.get("template") or "") or {}
        card = ov.get("backdrop") == "blur" or ov.get("fullFrame") or ov.get("type") in ("title", "chapter") \
            or t.get("category") == "HEADLINES"
        if not card:
            continue
        a = int(ov.get("startFrame") or 0)
        b = a + int(ov.get("durationInFrames") or 0)
        if min(b, f1) - max(a, f0) >= 0.8 * span:
            return True
    return False


def classify(doc: dict, res: dict) -> Tuple[List[dict], List[dict]]:
    """
    (defects, intended) from a scan: every flagged stretch is mapped to the
    scenes it falls on and judged. Meant to look that way: the opening fade and
    the last moments, a dip or cut transition's dark frames, a still with no
    motion, a graphic holding still, a dark graphic or title card. Defects:
    black over a clip or a picture, a clip that ran out and froze on its last
    frame (a frozen stretch reaching its scene's end), a clip that never moves,
    an empty scene, a video with no sound at all.
    """
    fps = max(1, int(doc.get("fps") or 30))
    scenes = doc.get("scenes") or []
    # A brand intro and outro are the customer's own clips around the
    # narration: the scan is read in the narration's own seconds, their
    # stretches left out (brandkit.body_scan).
    from . import brandkit
    res = brandkit.body_scan(doc, res)
    dur = float(res.get("duration") or 0.0) or int(doc.get("durationInFrames") or 0) / fps
    defects: List[dict] = []
    intended: List[dict] = []

    def on(a: float, b: float):
        for k, s in enumerate(scenes):
            s0 = int(s.get("startFrame") or 0) / fps
            s1 = s0 + int(s.get("durationInFrames") or 0) / fps
            if min(b, s1) - max(a, s0) > 0:
                yield k, s, s0, s1

    for a, b in res.get("black") or []:
        what = {"kind": "black", "start": round(a, 2), "end": round(b, 2), "at": _clock(a)}
        if a <= 0.25 and b - a <= 1.5:
            intended.append({**what, "why": "the opening fade"})
            continue
        if b >= dur - 0.25 and b - a <= 2.0:
            intended.append({**what, "why": "the last moments"})
            continue
        if _covering_cards(doc, int(a * fps), int(b * fps)):
            intended.append({**what, "why": "a title card"})
            continue
        parts, graphic = [], False
        for k, s, s0, s1 in on(a, b):
            lo, hi = s0, s1
            if (s.get("transition") or "none") != "none":
                lo = s0 + ENTRANCE_FRAMES / fps              # an entrance darkens its first frames
            nxt = scenes[k + 1] if k + 1 < len(scenes) else {}
            if (nxt or {}).get("transition") in CUT_TRANSITIONS:
                hi = s1 - EXIT_FRAMES / fps                  # and a cut transition the last ones
            part = min(b, hi) - max(a, lo)
            if part <= 0:
                continue
            if (s.get("media") or {}).get("type") == "animation":
                graphic = True                               # a dark graphic is drawn that way
            else:
                parts.append((part, k))
        # Black over clips or pictures, outside every transition's frames, for long
        # enough to see - in one scene or across a cut.
        if sum(p for p, _k in parts) >= config.QUALITY_BLACK_SECONDS:
            bad = [k for p, k in parts if p >= TOLERANCE_FRAMES / fps]
            pictures = all((scenes[k].get("media") or {}).get("type") == "image" for k in bad)
            defects.append({**what, "scenes": bad,
                            "why": f"{b - a:.1f} s of black over {'a picture' if pictures else 'a clip'}"})
        else:
            intended.append({**what, "why": "a dark graphic" if graphic else "a transition"})

    for a, b in res.get("frozen") or []:
        what = {"kind": "frozen", "start": round(a, 2), "end": round(b, 2), "at": _clock(a)}
        bad, whys = [], []
        for k, s, s0, s1 in on(a, b):
            lo, hi = max(a, s0), min(b, s1)
            part = hi - lo
            if part < config.QUALITY_FREEZE_SECONDS:
                continue
            m = s.get("media") or {}
            kind = m.get("type")
            if kind == "image":
                intended.append({**what, "scene": k, "why": "a still picture"})
                continue
            if kind == "animation":
                intended.append({**what, "scene": k, "why": "a graphic holding still"})
                continue
            if kind != "video" or not m.get("url"):
                bad.append(k)
                whys.append("an empty scene")
                continue
            tol = TOLERANCE_FRAMES / fps
            to_end, late = hi >= s1 - tol, lo > s0 + 0.2
            if to_end and late:
                bad.append(k)
                whys.append(f"the clip ran out and froze on its last frame for {part:.1f} s")
            elif a < s0 - tol:
                bad.append(k)                                # two shots cannot be the same frame
                whys.append("the picture did not change at the cut into this clip")
            elif to_end and b > s1 + tol:
                bad.append(k)
                whys.append("the clip never moved and its frame stayed on into the next scene")
            elif part >= STILL_CLIP_SECONDS and part >= STILL_CLIP_SHARE * (s1 - s0):
                bad.append(k)
                whys.append("the clip never moves")
            else:
                intended.append({**what, "scene": k, "why": "a still moment of the clip"})
        if bad:
            defects.append({**what, "scenes": bad, "why": "; ".join(dict.fromkeys(whys))})

    silent = sum(b - a for a, b in res.get("silent") or [])
    if not res.get("audio", True) or (dur > 0 and silent >= 0.9 * dur):
        defects.append({"kind": "silent", "start": 0.0, "end": round(dur, 2), "at": "0:00", "scenes": [],
                        "why": "the video has no sound"})
    else:
        for a, b in res.get("silent") or []:
            intended.append({"kind": "silent", "start": round(a, 2), "end": round(b, 2), "at": _clock(a),
                             "why": "a pause in the narration"})
    return defects, intended


def _score(defects: List[dict]) -> float:
    """How bad a render is: seconds of defect, a silent video worst of all."""
    return sum((1000.0 if d["kind"] == "silent" else 0.0) + max(0.0, d["end"] - d["start"]) for d in defects)


# --------------------------------------------------------------------------- #
# The gate
# --------------------------------------------------------------------------- #

class NarrationMissing(RuntimeError):
    """The narration cannot be read: nothing can be drawn over it."""


class _Floor:
    """A report that never moves the bar backwards (a second render runs 70-90 % again)."""

    def __init__(self, inner: Callable, floor: int, prefix: str = ""):
        self._inner, self._floor, self._prefix = inner, floor, prefix

    def __call__(self, step: str, progress: int = None, **kw):
        pct = None if progress is None else max(int(progress), self._floor)
        return self._inner(f"{self._prefix}{step}", pct, **kw)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def floor(report: Callable, pct: int, prefix: str = "") -> Callable:
    return _Floor(report, pct, prefix) if callable(report) else report


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
        self.render: Dict[str, Any] = {}
        self.seconds: Dict[str, float] = {}
        self.fetched: Dict[str, str] = {}       # a remote still -> the copy fetched to decode it
        self.checked = 0
        self.unverified = 0
        self.audited = False
        self.rerendered = False
        self._first: Optional[Tuple[List[dict], List[dict]]] = None
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

    def _broke(self, what: str, err: BaseException) -> None:
        """A step of the check that broke is logged and skipped: the check must never be what fails a video."""
        traceback.print_exc()
        self.notes.append(f"{what} broke ({type(err).__name__}: {str(err)[:120]}) and was skipped")
        try:
            events.emit("quality", "check_failed", level="error",
                        message=f"{what}: {type(err).__name__}: {str(err)[:200]}")
        except Exception:  # noqa: BLE001
            pass

    # ---- before the render --------------------------------------------------
    def before_render(self) -> int:
        """
        Check the document and repair it. Returns how many scenes were
        repaired. Raises only NarrationMissing; a step that breaks is logged
        and the render goes on as before (no scene left without a picture).
        """
        if not config.QUALITY_GATE:
            return 0
        try:
            return self._before_render()
        except NarrationMissing:
            raise
        except Exception as e:  # noqa: BLE001 - the check must never be what fails a video
            self._broke("the check before the render", e)
            self.no_empty_scenes()          # a scene cleared before the step broke still gets a picture
            return 0

    def _before_render(self) -> int:
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
            if templates.allowed() is not None and templates.banned("TEXT_DUAL_LABELS_V1"):
                ov.pop("template", None)         # the plain label pills: the look is outside the brand kit
            elif templates.get("TEXT_DUAL_LABELS_V1"):
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
            try:
                if gapfill._empty(s):
                    text_scene(self.doc, s)
                    out.append(str(s.get("id")))
            except Exception as e:  # noqa: BLE001 - one odd scene never stops the others
                self._broke(f"scene {s.get('id')} as text", e)
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

    # ---- after the render ---------------------------------------------------
    def after_render(self, path: str) -> bool:
        """
        Scan the finished file. True when scenes were repaired and the video
        should be drawn once more. Never raises: a scan or repair that breaks
        is logged and the first render stands.
        """
        if not config.QUALITY_SCAN:
            return False
        try:
            return self._after_render(path)
        except Exception as e:  # noqa: BLE001 - the check must never be what fails a video
            self._broke("the scan of the finished video", e)
            return False

    def _after_render(self, path: str) -> bool:
        self._say("Checking the finished video", 90)
        res = scan(path)
        self.seconds["scan"] = res.get("seconds", 0.0)
        if not res["ok"]:
            self.render.update(scanned=False, why=res["why"])
            self.notes.append(f"the finished video was not scanned: {res['why']}")
            self._event("scanned", f"not scanned: {res['why']}", level="warning", always=True)
            return False
        defects, intended = classify(self.doc, res)
        self._first = (defects, intended)
        self.render.update(scanned=True, seconds=res["seconds"], black=len(res["black"]),
                           frozen=len(res["frozen"]), silent=len(res["silent"]), intended=len(intended),
                           defects=[_brief(d) for d in defects][:20])
        self.render.setdefault("rerendered", False)
        self._event("scanned", f"{len(defects)} defect(s), {len(intended)} intended (fades, stills, graphics) "
                               f"in {res['seconds']:.0f} s", level="warning" if defects else "info", always=True,
                    data={"black": len(res["black"]), "frozen": len(res["frozen"]), "silent": len(res["silent"]),
                          "defects": len(defects), "intended": len(intended)})
        for d in defects:
            self.found[d["kind"]] += 1
            self._event("defect", f"{d['kind']} at {d['at']}: {d['why']}", level="warning",
                        scene=(d.get("scenes") or [None])[0], data=_brief(d))
        if not defects:
            return False
        scenes = self.doc.get("scenes") or []
        problems = {}
        for d in defects:
            for k in d.get("scenes") or []:
                if 0 <= k < len(scenes):
                    problems.setdefault(k, (d["kind"], d["why"]))
        # Silence has no scene to repair, and drawing the same narration again
        # gives the same sound: it is reported, never re-rendered for.
        if self.rerendered or not config.QUALITY_RERENDER or not problems:
            self._leave(defects)
            return False
        self.rerendered = True
        self._say(f"Repairing {_n(len(problems), 'scene')} the finished video showed wrong", 90)
        self._replace(problems, "after the render")
        self._look_sources()
        self.no_empty_scenes()
        from . import timeline
        timeline.drop_invalid_overlays(self.doc)
        self.render["rerendered"] = True
        self._event("rerender", f"drawing the video once more after repairing {_n(len(problems), 'scene')}",
                    always=True, data={"scenes": sorted(problems)[:40]})
        return True

    def after_rerender(self, path: str, first: str) -> str:
        """
        Scan the second render and keep the better file at `path`. Returns
        "repaired" or "first". A scan that breaks keeps the repaired render.
        """
        try:
            return self._after_rerender(path, first)
        except Exception as e:  # noqa: BLE001 - the check must never be what fails a video
            self._broke("the scan of the second render", e)
            if not os.path.isfile(path) and os.path.isfile(first):
                os.replace(first, path)
                self.render["kept"] = "first"
                return "first"
            _remove(first)
            self.render["kept"] = "repaired"
            return "repaired"

    def _after_rerender(self, path: str, first: str) -> str:
        res = scan(path)
        before = self._first[0] if self._first else []
        if not res["ok"]:
            # Nothing to judge it by: the repaired render stands (its scenes were the ones at fault).
            self.notes.append(f"the second render was not scanned: {res['why']}")
            self.render["kept"] = "repaired"
            self.render["fixed"] = len(before)
            _remove(first)
            return "repaired"
        after, intended = classify(self.doc, res)
        self.seconds["scan"] = round(self.seconds.get("scan", 0.0) + res.get("seconds", 0.0), 1)
        if _score(after) <= _score(before):
            kept, left = "repaired", after
            _remove(first)
        else:
            kept, left = "first", before
            os.replace(first, path)
        self.render.update(kept=kept, fixed=max(0, len(before) - len(left)),
                           defectsAfter=[_brief(d) for d in after][:20])
        if left:
            self._leave(left)
        self._event("rerendered", f"kept the {kept} render: {len(before)} defect(s) before, {len(after)} after",
                    level="warning" if left else "info", always=True)
        return kept

    def rerender_failed(self, err: BaseException) -> None:
        """The second render broke: the first file stands, with its problems reported."""
        self.render["kept"] = "first"
        self.notes.append(f"the second render failed ({type(err).__name__}: {str(err)[:120]}); the first one is kept")
        try:
            self._event("rerender_failed", f"{type(err).__name__}: {str(err)[:200]}", level="error", always=True)
            if self._first:
                self._leave(self._first[0])
        except Exception as e:  # noqa: BLE001 - the check must never be what fails a video
            self._broke("the report of the second render", e)

    def _leave(self, defects: List[dict]) -> None:
        scenes = self.doc.get("scenes") or []
        for d in defects:
            ids = [str(scenes[k].get("id")) for k in d.get("scenes") or [] if 0 <= k < len(scenes)]
            self.unresolved.append({"kind": d["kind"], "scene": ids[0] if ids else "", "at": d["at"],
                                    "what": f"{d['kind']} at {d['at']}: {d['why']}"})
            self._event("unresolved", f"{d['kind']} at {d['at']}: {d['why']}", level="error", always=True,
                        data=_brief(d))

    # ---- a render that failed -----------------------------------------------
    def recover(self, err: BaseException) -> bool:
        """
        A render that failed on files its error names: the scenes showing them
        are repaired, dead stills and pictures taken out, and True says draw it
        once more. False when the error names nothing that can be fixed, the
        one second render is already spent, or the repair itself broke (the
        render's own error then stands).
        """
        if self.rerendered or not config.QUALITY_GATE:
            return False
        try:
            return self._recover(err)
        except Exception as e:  # noqa: BLE001 - the render's own error is the one to report
            self._broke("the repair after a failed render", e)
            return False

    def _recover(self, err: BaseException) -> bool:
        named = set(_URLS.findall(str(err)))
        if not named:
            return False
        hit = _NamedFiles(named, self.work)
        scenes = self.doc.get("scenes") or []
        problems: Dict[int, Tuple[str, str]] = {}
        changed = 0
        for i, s in enumerate(scenes):
            m = s.get("media") or {}
            if m.get("type") in ("video", "image") and hit(m.get("url")):
                problems[i] = ("render", "the renderer could not load it")
            if isinstance(m.get("thumbnail"), str) and hit(m["thumbnail"]):
                m.pop("thumbnail", None)
                changed += 1
            anim = s.get("animation")
            if isinstance(anim, dict) and isinstance(anim.get("media"), list):
                kept = [x for x in anim["media"] if not (isinstance(x, dict) and hit(x.get("url")))]
                changed += len(anim["media"]) - len(kept)
                anim["media"] = kept
        for ov in self.doc.get("overlays") or []:
            if isinstance(ov, dict) and isinstance(ov.get("media"), list):
                kept = [x for x in ov["media"] if not (isinstance(x, dict) and hit(x.get("url")))]
                if len(kept) != len(ov["media"]):
                    changed += len(ov["media"]) - len(kept)
                    ov["media"] = kept
                    self._after_loss(ov)
        bgm = self.doc.get("bgm")
        if isinstance(bgm, dict) and hit(bgm.get("url")):
            new = _bundled_bgm(self.doc, avoid=str(bgm.get("url")))
            if new and new != bgm.get("url"):
                bgm["url"] = new
            else:
                self.doc["bgm"] = None
            changed += 1
        if not problems and not changed:
            return False
        self.rerendered = True
        self.found["render"] += len(problems) + changed
        self._event("render_failed", f"the render failed on {_n(len(problems), 'scene')} and "
                                     f"{_n(changed, 'other picture')}: {str(err)[:160]}", level="warning", always=True)
        if problems:
            self._replace(problems, "after the render failed")
        if changed:
            self.fixed["overlay"] += changed
        self._look_sources()
        self.no_empty_scenes()
        from . import timeline
        timeline.drop_invalid_overlays(self.doc)
        self.render["rerendered"] = True
        self.render["afterFailure"] = True
        return True

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
        if self.render.get("fixed"):
            parts.append(_n(int(self.render["fixed"]), "black or frozen stretch", "black or frozen stretches")
                         + " fixed by a second render")
        if self.unresolved:
            parts.append(_n(len(self.unresolved), "problem") + f" left ({self.unresolved[0]['what']})")
        return f"Quality check: {ok}/{total} scenes OK, " + (", ".join(parts) if parts else "nothing to fix")

    def finish(self) -> dict:
        """The report (doc.meta.quality and the job result's "quality"); one summary row in the events."""
        if self._report is not None:
            return self._report
        try:
            return self._finish()
        except Exception as e:  # noqa: BLE001 - the check must never be what fails a video
            self._broke("the quality report", e)
            self._report = {"summary": "Quality check: the report could not be written", "notes": self.notes[:20],
                            "found": dict(self.found), "fixed": dict(self.fixed)}
            return self._report

    def _finish(self) -> dict:
        line = self.summary()
        out = {"summary": line, "scenes": len(self.doc.get("scenes") or []), "scenesBefore": self.scenes_in,
               "found": dict(self.found), "fixed": dict(self.fixed), "repairs": self.repairs[:200],
               "render": dict(self.render), "unresolved": self.unresolved[:50], "notes": self.notes[:20],
               "checked": self.checked, "unverified": self.unverified, "seconds": dict(self.seconds),
               "audited": self.audited}
        self._event("summary", line, level="warning" if self.unresolved else "info", always=True,
                    data={"found": dict(self.found), "fixed": dict(self.fixed),
                          "unresolved": len(self.unresolved), "rerendered": bool(self.render.get("rerendered"))})
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


def _brief(d: dict) -> dict:
    return {k: d[k] for k in ("kind", "start", "end", "at", "why", "scenes") if k in d}


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


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


_URLS = re.compile(r"https?://[^\s'\"<>()\[\]{},]+")


class _NamedFiles:
    """Whether a document link is one a render error names (directly, or as the copy the renderer served)."""

    def __init__(self, named: set, work: str):
        self.links = set()
        self.paths = set()
        self.names = set()
        root = os.path.abspath(work or ".")
        for u in named:
            u = u.rstrip(".;:")
            p = urllib.parse.urlparse(u)
            if p.hostname in ("127.0.0.1", "localhost"):
                rel = urllib.parse.unquote(p.path).lstrip("/")
                self.paths.add(os.path.normcase(os.path.abspath(os.path.join(root, rel))))
                self.names.add(os.path.basename(rel))
            else:
                self.links.add(u.split("?", 1)[0])

    def __call__(self, url) -> bool:
        url = str(url or "")
        if not url:
            return False
        if url.split("?", 1)[0] in self.links:
            return True
        path = local_path(url)
        if path:
            return os.path.normcase(os.path.abspath(path)) in self.paths or \
                (os.path.basename(path) in self.names and bool(self.names))
        # A link a render chunk downloaded first (fanout._localize: media/<sha1 of the link>.<ext>).
        tag = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        return any(n.startswith(tag) for n in self.names)
