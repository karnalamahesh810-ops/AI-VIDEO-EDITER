"""Invoke the Remotion renderer as a subprocess and return the output path."""
import copy
import hashlib
import json
import math
import os
import queue
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import urllib.parse

from . import config
from . import templates
from .assetserver import AssetServer, localise


class RenderError(RuntimeError):
    pass


class RenderCancelled(RenderError):
    """render(cancel=...) was told to stop (another machine finished the same frames first)."""


class RenderTimeout(RenderError):
    """The render was stopped: it passed its time limit, or it stopped making progress."""


# --------------------------------------------------------------------------- #
# How long a render may take on this machine
# --------------------------------------------------------------------------- #

def _cgroup_cpus() -> float:
    """The container's CPU limit (cgroup v2, then v1), 0 when it has none or cannot be read."""
    try:
        with open("/sys/fs/cgroup/cpu.max", encoding="ascii") as fh:
            quota, period = (fh.read().split() + ["100000"])[:2]
        if quota != "max" and float(period) > 0:
            return float(quota) / float(period)
    except (OSError, ValueError):
        pass
    try:
        with open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us", encoding="ascii") as fh:
            quota = float(fh.read().strip())
        with open("/sys/fs/cgroup/cpu/cpu.cfs_period_us", encoding="ascii") as fh:
            period = float(fh.read().strip())
        if quota > 0 and period > 0:
            return quota / period
    except (OSError, ValueError):
        pass
    return 0.0


def cpus() -> int:
    """
    The CPUs this machine gives a render: RENDER_CPUS when set, else the
    smallest of the container's limit, the cores the scheduler allows and the
    host's count (a container sees the HOST's cores in os.cpu_count()).
    """
    if getattr(config, "RENDER_CPUS", 0) > 0:
        return int(config.RENDER_CPUS)
    found = [os.cpu_count() or 1]
    try:
        found.append(len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        pass
    limit = _cgroup_cpus()
    if limit > 0:
        found.append(int(math.ceil(limit)))
    return max(1, min(found))


def frames_per_second(concurrency: int = None) -> float:
    """The frames a second a picture render is expected to draw here (see RENDER_FPS_PER_TAB)."""
    n = cpus()
    tabs = min(int(concurrency), n) if concurrency else max(1, n // 2)
    return max(0.05, max(1, tabs) * float(config.RENDER_FPS_PER_TAB))


def estimate_seconds(frames: int, concurrency: int = None) -> float:
    """About how long `frames` frames take to render on this machine."""
    return max(0, int(frames)) / frames_per_second(concurrency)


def render_timeout(frames: int, concurrency: int = None) -> int:
    """
    The time limit of a render of `frames` frames on this machine: the
    estimate with room to spare, never under RENDER_TIMEOUT_MIN_SECONDS and
    never over RENDER_TIMEOUT_MAX_SECONDS. A long video on a small machine gets
    the time it needs (it was a flat 5400 s); nothing runs past the upper bound.
    """
    want = estimate_seconds(frames, concurrency) * float(config.RENDER_TIMEOUT_FACTOR) \
        + float(config.RENDER_TIMEOUT_BASE_SECONDS)
    low = float(config.RENDER_TIMEOUT_MIN_SECONDS)
    high = max(low, float(config.RENDER_TIMEOUT_MAX_SECONDS))
    return int(min(high, max(low, want)))


def frame_count(props: dict, frames: tuple = None) -> int:
    """The frames one render draws: its range, else the whole document (brand intro and outro included)."""
    if frames:
        return max(1, int(frames[1]) - int(frames[0]) + 1)
    try:
        from . import brandkit
        return max(1, int(brandkit.total_frames(props)))
    except Exception:  # noqa: BLE001 - an odd document: its own length
        return max(1, int((props or {}).get("durationInFrames") or 1))


def _minutes(seconds: float) -> str:
    m = int(round(float(seconds) / 60.0))
    return f"{m // 60} h {m % 60:02d} min" if m >= 90 else f"{max(1, m)} min"


# --------------------------------------------------------------------------- #
# A failed render in plain words
# --------------------------------------------------------------------------- #

_URL = re.compile(r"https?://[^\s'\"<>()\[\]{},]+")
# Remotion prints a failed download's body between two "---" lines, cut short:
# a page ends at its </html>, else at that closing line, else with the text.
_PAGE_END = r"(?:</html\s*>|\n-{3,}[ \t]*(?=\n|\Z)|\Z)"
_HTML_PAGE = re.compile(r"<!doctype\s+html.*?" + _PAGE_END + r"|<html[\s>].*?" + _PAGE_END, re.I | re.S)
_HTML_REST = re.compile(r"\A.*</(?:html|body)\s*>", re.I | re.S)       # a page whose start was cut off
_HTML_BLOCK = re.compile(r"<(svg|style|script|head)[\s>].*?(?:</\1\s*>|\Z)", re.I | re.S)
_TAG = re.compile(r"<!--.*?-->|</?[A-Za-z][^<>\n]{0,800}>", re.S)
_TITLE = re.compile(r"<title[^>]*>\s*(.{1,120}?)\s*</title>", re.I | re.S)
# An HTTP status in words that say it is one (never a frame number beside a link).
_STATUS = re.compile(r"(?:status(?:\s+code)?(?:\s+of)?|HTTP(?:/\d\.\d)?|answer(?:s|ed)|returned|responded(?:\s+with)?)"
                     r"\D{0,12}(40[0134]|410|429|50[0234])\b", re.I)
# status -> (what happened, what it usually means)
_STATUS_WORDS = {
    "404": ("not found in storage (404)", "deleted from storage?"),
    "410": ("not found in storage (410)", "deleted from storage?"),
    "403": ("refused by storage (403)", "an expired or private link?"),
    "401": ("refused by storage (401)", "an expired or private link?"),
    "400": ("refused by storage (400)", "an expired link?"),
    "429": ("refused for too many requests (429)", "storage is rate limiting"),
}


def _name_of(url: str) -> str:
    """A link for a message: host and file name, never the query (signed links carry tokens)."""
    p = urllib.parse.urlparse(url)
    return f"{p.netloc}/.../{os.path.basename(p.path)}" if p.path.count("/") > 1 else f"{p.netloc}{p.path}"


def _storage_trouble(text: str) -> str:
    """One plain sentence when the output shows files that could not be loaded over HTTP, else ""."""
    by_code: dict = {}
    for line in text.splitlines():
        urls = _URL.findall(line)
        if not urls:
            continue
        m = _STATUS.search(_URL.sub(" ", line))          # a status beside the link, not a number inside it
        if not m:
            continue
        got = by_code.setdefault(m.group(1), [])
        for u in urls:
            u = u.rstrip(".;:")
            if u not in got:
                got.append(u)
    if not by_code:
        return ""
    parts = []
    for code, urls in sorted(by_code.items()):
        what, hint = _STATUS_WORDS.get(code, (f"unreadable (storage answered {code})", ""))
        names = ", ".join(_name_of(u) for u in urls[:3]) + (f" and {len(urls) - 3} more" if len(urls) > 3 else "")
        one = len(urls) == 1
        parts.append(f"{len(urls)} file{'' if one else 's'} the video needs {'was' if one else 'were'} {what}: "
                     f"{names}" + (f" - {hint}" if hint else ""))
    return "; ".join(parts)


def has_markup(text: str) -> bool:
    """The text carries (part of) a web page: an error message must never show it."""
    return bool(re.search(r"<!doctype\s+html|</?(?:html|body|head|svg|path|style|script)[\s>/]", text or "", re.I))


def plain_error(raw: str, limit: int = 2000) -> str:
    """
    What a failed render printed, as an error a person can read: any web page
    in it (a storage 404 or rate-limit page came back as raw HTML and became
    the project's whole error message, 2026-10-04) is taken out, and when the
    output shows files that could not be loaded, that is said first - how
    many, which, and the storage's answer. The links themselves stay in the
    text: the quality check repairs the scenes a render error names.
    """
    raw = raw or ""
    title = _TITLE.search(raw)
    had_page = bool(re.search(r"<!doctype\s+html|<html[\s>]|</html\s*>|</body\s*>", raw, re.I))
    text = _HTML_PAGE.sub(" [a web error page] ", raw)
    if re.search(r"</(?:html|body)\s*>", text, re.I):
        text = _HTML_REST.sub(" [a web error page] ", text)
    text = _HTML_BLOCK.sub(" ", text)
    text = _TAG.sub(" ", text)
    lines = [re.sub(r"[ \t]{2,}", " ", l).rstrip() for l in text.splitlines()]
    text = "\n".join(l for l in lines if l.strip())
    lead = _storage_trouble(text)
    if not lead and had_page:
        page = f' ("{" ".join(title.group(1).split())}")' if title else ""
        lead = f"a storage link answered with an error page{page} instead of the file - is the file still in storage?"
    body = text[-limit:]
    if not lead:
        return body
    return f"{lead}{' ' if lead.endswith('?') else '. '}{body}"


# x264's speed/size trade-offs. Measured on our own 1080p renders (2026-10-01,
# 600 frames at CRF 21): medium 73 fps / SSIM 0.9814, faster 105 fps / 0.9812,
# veryfast 166 fps / 0.9805 (and 7% smaller), superfast 197 fps but 46% bigger.
_X264_PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium",
                 "slow", "slower", "veryslow")
# Audio-only codecs Remotion can render (no picture: no CRF, no x264 preset).
_AUDIO_CODECS = ("aac", "wav", "mp3")


def x264_preset() -> str:
    """config.RENDER_X264_PRESET when it is a real x264 preset, else "" (Remotion's default, medium)."""
    p = str(getattr(config, "RENDER_X264_PRESET", "") or "").strip().lower()
    return p if p in _X264_PRESETS else ""


_FINGERPRINTS: dict = {}
_BUNDLE_LOCK = threading.Lock()
_BUNDLE_FAILED: set = set()


def renderer_fingerprint(remotion_dir: str = None) -> str:
    """
    What draws the frames, as one short hash: every file under remotion/src
    (by content), the public/ file list (names and sizes: the bgm and sfx) and
    the Remotion package versions. Two machines with the same fingerprint
    render identical frames from the same document; it names the pre-built
    bundle and lets a render chunk refuse to join a render made by other code.
    """
    root = os.path.abspath(remotion_dir or config.REMOTION_DIR)
    if root in _FINGERPRINTS:
        return _FINGERPRINTS[root]
    h = hashlib.sha1()
    for sub, by_content in (("src", True), ("public", False)):
        base = os.path.join(root, sub)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames.sort()
            for name in sorted(filenames):
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, root).replace("\\", "/")
                h.update(rel.encode("utf-8") + b"\0")
                if by_content:
                    with open(path, "rb") as fh:
                        h.update(hashlib.sha1(fh.read()).digest())
                else:
                    h.update(str(os.path.getsize(path)).encode("ascii"))
    for pkg in ("remotion", "@remotion/cli", "@remotion/renderer", "@remotion/bundler"):
        try:
            with open(os.path.join(root, "node_modules", *pkg.split("/"), "package.json"),
                      encoding="utf-8") as fh:
                h.update(f"{pkg}@{json.load(fh).get('version')}".encode("utf-8"))
        except (OSError, ValueError):
            pass
    fp = h.hexdigest()[:16]
    _FINGERPRINTS[root] = fp
    return fp


def ensure_bundle() -> str:
    """
    The Remotion project pre-built once per machine and code version
    (RENDER_BUNDLE_DIR/<fingerprint>), or "" to let the CLI bundle it.

    `remotion render src/index.ts` bundles with webpack and copies public/
    (140 MB of music and sound effects) before every render: 3.5 s warm and
    12 s cold on the laptop, longer on a fresh worker. A render chunk, the
    audio track and every retry paid it again. A failed build is not retried
    in this process; the render then bundles from source as before.
    """
    if not getattr(config, "RENDER_PREBUNDLE", False):
        return ""
    if not os.path.isfile(os.path.join(config.REMOTION_DIR, "src", "index.ts")):
        return ""
    try:
        fp = renderer_fingerprint()
    except OSError:
        return ""
    base = config.RENDER_BUNDLE_DIR or os.path.join(tempfile.gettempdir(), "remotion-bundles")
    final = os.path.join(base, fp)
    if os.path.isfile(os.path.join(final, "index.html")):
        return final
    with _BUNDLE_LOCK:
        if os.path.isfile(os.path.join(final, "index.html")):
            return final
        if fp in _BUNDLE_FAILED:
            return ""
        started = time.time()
        tmp = ""
        try:
            os.makedirs(base, exist_ok=True)
            tmp = tempfile.mkdtemp(prefix=f"{fp}-build-", dir=base)
            p = subprocess.run(_renderer_argv() + ["bundle", "src/index.ts", "--out-dir", tmp, "--log=error"],
                               cwd=config.REMOTION_DIR, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=config.RENDER_BUNDLE_TIMEOUT)
            ok = p.returncode == 0 and os.path.isfile(os.path.join(tmp, "index.html"))
            why = (p.stderr or p.stdout or "")[-300:]
        except Exception as e:  # noqa: BLE001 - any failure: bundle per render as before
            ok, why = False, type(e).__name__
        if not ok:
            _BUNDLE_FAILED.add(fp)
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
            print(f"[render] renderer bundle could not be pre-built; bundling per render: {why}", flush=True)
            return ""
        try:
            os.replace(tmp, final)
        except OSError:
            # Another process on this machine finished first: use its copy.
            shutil.rmtree(tmp, ignore_errors=True)
            if not os.path.isfile(os.path.join(final, "index.html")):
                return ""
        # Bundles of older code on a long-lived machine (the name is a fingerprint).
        for name in os.listdir(base):
            if name != fp and re.fullmatch(r"[0-9a-f]{16}", name):
                shutil.rmtree(os.path.join(base, name), ignore_errors=True)
        print(f"[render] renderer bundle ready in {time.time() - started:.1f} s ({fp})", flush=True)
        return final


def _renderer_argv() -> list:
    """
    How to invoke the Remotion CLI, resolved per platform.

    `npx` is a real binary in the Linux image but a .cmd/.ps1 shim on Windows,
    and subprocess without shell=True goes through CreateProcess, which only
    launches real executables - so a plain ["npx", ...] dies with WinError 2 on
    a Windows dev box while working fine in the container. Driving the CLI's own
    JS entry point with `node` skips the shim and behaves identically on both.
    """
    node = shutil.which("node")
    cli = os.path.join(config.REMOTION_DIR, "node_modules", "@remotion",
                       "cli", "remotion-cli.js")
    if node and os.path.exists(cli):
        return [node, cli]
    return [shutil.which("npx") or "npx", "remotion"]


_FRAC = re.compile(r"(\d+)\s*/\s*(\d+)")
_PCT = re.compile(r"(\d{1,3})\s*%")


def _render_progress(line: str):
    """
    0..1 out of a Remotion progress line, or None when it isn't one.

    Remotion reports two passes, "Rendered x/y" (frames) then "Encoded x/y" /
    "Stitched x/y". Read as one bar they made it run to ~80% and drop back to
    0 - the user saw the video's progress "go back". Frames map to 0-0.8,
    encoding to 0.8-1.0.
    """
    low_line = line.lower()
    if "bundling" in low_line or "copying public" in low_line:
        # Webpack's bundling percent is not the render: read as progress it
        # showed "Rendering video 100%" before a single frame was drawn.
        return None
    m = _FRAC.search(line)
    if m:
        done, total = int(m.group(1)), int(m.group(2))
        if total > 0 and done <= total:
            frac = done / total
            low = line.lower()
            if "encod" in low or "stitch" in low or "mux" in low:
                return 0.8 + 0.2 * frac
            return 0.8 * frac
    m = _PCT.search(line)
    if m:
        v = int(m.group(1))
        if v <= 100:
            return v / 100.0
    return None


def render(props: dict, out_path: str, composition: str = "Main",
           concurrency: int = None, timeout: int = None,
           serve_dir: str = None, on_progress=None, frames: tuple = None,
           muted: bool = False, codec: str = None, audio_to: str = None,
           cancel: threading.Event = None) -> str:
    """
    Render `props` to `out_path` with Remotion.

    `timeout` (seconds): left unset, the limit follows the frames this render
    draws and this machine (render_timeout). A render past its limit, or one
    that stops printing progress for RENDER_STALL_SECONDS, is stopped with a
    RenderTimeout that says how far it got.

    `audio_to` (a .wav path): the sound is written there as lossless PCM and
    `out_path` holds the picture only; finalize() then encodes the sound once
    into the finished MP4. Remotion's own AAC left the sound 42.7 ms late.
    With `frames`, the sound is that frame range's slice of the whole mix.
    `cancel`: a threading.Event that kills the render (RenderCancelled).

    Sourced media lives on local disk, and headless Chrome cannot read a
    filesystem path from an http origin, so the job directory is served over
    loopback for the duration of the render and every local reference in the
    document is rewritten to point at it. See assetserver.py.

    Props are written to disk and passed with --props=<file>; passing a large
    JSON document as an inline argument blows the command-line length limit
    once a video has a few hundred scenes.

    `on_progress(fraction)` receives 0..1 as Remotion encodes. Without it the
    render is a silent multi-minute block, which on a 20-minute video is
    indistinguishable from a hang. Streaming costs the plain capture_output
    path, so the output is buffered here to keep the same error tail.
    """
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    work = serve_dir or os.path.dirname(out_path)
    # One props file per output: chunk and audio renders can share a job dir.
    props_path = os.path.splitext(out_path)[0] + ".props.json"

    with AssetServer(work) as assets:
        # Rewrite a copy: the caller keeps the document it passed in, which is
        # what gets stored for the editor. Localhost URLs must not leak there.
        served = localise(copy.deepcopy(props), assets)
        # A sound the renderer does not ship (an editor pick, a renamed file)
        # would 404 and fail the whole render; drop it and say so.
        have = templates.sfx_files()
        kept, dropped = [], []
        for fx in served.get("sfx") or []:
            (kept if fx.get("name") in have else dropped).append(fx)
        if dropped:
            print(f"[render] dropping {len(dropped)} sfx without a file: "
                  f"{sorted({fx.get('name') for fx in dropped})}", flush=True)
            served["sfx"] = kept
        with open(props_path, "w", encoding="utf-8") as f:
            json.dump(served, f)

        # The pre-built bundle (ensure_bundle) skips webpack and the 140 MB
        # public/ copy; without one the CLI bundles from source as before.
        entry = ensure_bundle() or "src/index.ts"
        cmd = _renderer_argv() + [
            "render", entry, composition, out_path,
            f"--props={props_path}",
            # --log=error hides the progress lines, so ask for more only when
            # somebody is listening.
            "--log=info" if on_progress else "--log=error",
        ]
        # A frame chunk of a split render, silent (the audio is rendered once,
        # whole), or the audio track alone (codec "wav" or "aac").
        if frames:
            cmd.append(f"--frames={int(frames[0])}-{int(frames[1])}")
        if muted:
            cmd.append("--muted")
        if codec:
            cmd.append(f"--codec={codec}")
        picture = (codec or "h264") == "h264"
        # Picture quality (the audio-only render has no picture).
        if config.RENDER_CRF and picture:
            cmd.append(f"--crf={config.RENDER_CRF}")
        # x264 runs beside the browser tabs (parallel encoding): its default,
        # medium, took ~16% of the machine for no visible gain (see _X264_PRESETS).
        if picture and x264_preset():
            cmd.append(f"--x264-preset={x264_preset()}")
        if audio_to and picture and not muted:
            audio_to = os.path.abspath(audio_to)
            if os.path.exists(audio_to):
                os.remove(audio_to)             # never mistake an old track for this render's
            # --enforce-audio-track: a document with no sound still yields a
            # (silent) track instead of failing the separate-audio render.
            cmd += [f"--separate-audio-to={audio_to}", "--enforce-audio-track"]
        # A container sees the HOST's memory and cores. Remotion sizes its
        # frame cache at half of "system memory" and the compositor's decoders
        # scale with cores, so on a RunPod worker both overshoot the cgroup
        # until the compositor can no longer start a thread - the render dies
        # with "thread::unix::Thread::new::thread_start" partway through.
        # Fixed caps keep it inside the container.
        cmd += [f"--offthreadvideo-cache-size-in-bytes={config.RENDER_FRAME_CACHE_BYTES}",
                f"--offthreadvideo-video-threads={config.RENDER_VIDEO_THREADS}",
                # Map tiles and remote images are fetched while rendering.
                f"--timeout={config.RENDER_DELAY_TIMEOUT_MS}"]
        # Remotion's canvas/SVG effects otherwise use Chromium's software GL
        # path on headless workers, even when RunPod has attached an NVIDIA
        # device. ANGLE uses the worker's GPU for composition; video decoding
        # remains on OffthreadVideo's bounded FFmpeg workers. CPU-only local
        # runs keep Remotion's default backend. REMOTION_GL can override this
        # for a pod whose driver requires another supported backend.
        gl_backend = os.getenv("REMOTION_GL", "").strip()
        if gl_backend or os.path.exists("/dev/nvidia0"):
            cmd.append(f"--gl={gl_backend or 'angle'}")

        n_frames = frame_count(props, frames)
        limit = int(timeout) if timeout else render_timeout(n_frames, concurrency)
        # Progress lines are printed only when somebody listens (--log=info):
        # silence then means a hung render, not a quiet one.
        stall = float(getattr(config, "RENDER_STALL_SECONDS", 0) or 0) if on_progress is not None else 0.0

        def run(argv):
            started = time.time()
            try:
                if on_progress is None and cancel is None:
                    return subprocess.run(
                        argv, cwd=config.REMOTION_DIR, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=limit,
                    )
                return _run_streaming(argv, limit, on_progress, cancel, stall=stall)
            except subprocess.TimeoutExpired:
                # (Never the command line: it was the whole error of a failed job.)
                raise RenderTimeout(_out_of_time(n_frames, limit, time.time() - started, None)) from None
            except _Stopped as e:
                raise RenderTimeout(_out_of_time(n_frames, limit, time.time() - started, e.frac,
                                                 stalled=e.why == "stall", quiet=stall)) from None

        p = run(cmd + ([f"--concurrency={concurrency}"] if concurrency else []))
        if cancel is not None and cancel.is_set():
            raise RenderCancelled("render cancelled")
        tail = (p.stderr or p.stdout or "")[-3000:]
        if p.returncode != 0 and ("thread_start" in tail or "Resource temporarily" in tail):
            # Still out of threads: one slower, single-tab retry beats losing
            # a whole job that already spent minutes sourcing.
            print("[render] out of threads - retrying at concurrency 1", flush=True)
            p = run(cmd + ["--concurrency=1"])

    if p.returncode != 0 or not os.path.exists(out_path):
        # Drop the progress chatter: 1500 characters of "Rendered 906/2861,
        # time remaining" is all a real failure reported, hiding the error.
        lines = [l for l in (p.stderr or p.stdout or "").splitlines()
                 if l.strip() and not l.lstrip().startswith(("Rendered ", "Encoded ", "Stitched "))
                 and "time remaining" not in l]
        # Never a raw web page: a storage 404 page was a project's whole error.
        said = plain_error("\n".join(lines))
        raise RenderError(f"remotion render failed (exit {p.returncode}): {said}")
    if audio_to and picture and not muted and not os.path.isfile(audio_to):
        raise RenderError("remotion rendered the picture but wrote no sound track")
    return out_path


class _Completed:
    """Just enough of CompletedProcess for the error path below."""

    def __init__(self, returncode, stdout, stderr):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class _Stopped(Exception):
    """_run_streaming stopped the render itself: `why` is "timeout" or "stall", `frac` how far it got."""

    def __init__(self, why: str, frac: float):
        super().__init__(why)
        self.why, self.frac = why, frac


def _out_of_time(frames: int, limit: float, ran: float, frac, stalled: bool = False, quiet: float = 0.0) -> str:
    """The error of a render that was stopped, in plain words (never the command line)."""
    done = f"{int(frac * 100)}% done" if isinstance(frac, (int, float)) else "not finished"
    where = f"{frames} frames on this one machine, {cpus()} CPUs"
    if stalled:
        return (f"The render stopped making progress: nothing was drawn for {_minutes(quiet)}, so it was "
                f"stopped ({done} after {_minutes(ran)}; {where}).")
    return (f"The render ran out of time: {done} after {_minutes(ran)} ({where}; "
            f"the limit was {_minutes(limit)}).")


def _run_streaming(cmd, timeout, on_progress, cancel=None, stall: float = 0.0) -> "_Completed":
    """
    Run Remotion, forwarding progress while keeping the output for errors.
    `cancel` (a threading.Event): once set, the render is killed (a chunk
    another machine finished first). Past `timeout` seconds, or after `stall`
    seconds without a single line of output (0 = not watched), the render is
    stopped and _Stopped raised. The output is read on its own thread and this
    one looks at the clock every second: the limit used to be checked only
    when a line arrived, so a render that hung - and printed nothing - sat
    until the job itself was killed; and a stop never waits on the pipe, which
    a browser the renderer left behind can hold open.
    """
    proc = subprocess.Popen(
        cmd, cwd=config.REMOTION_DIR, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        bufsize=1,
        # Its own process group (Linux): a render that will not stop is killed
        # with the browsers and encoders it started.
        **({"start_new_session": True} if os.name == "posix" else {}),
    )
    out: "queue.Queue" = queue.Queue()

    def pump():
        try:
            for line in proc.stdout:
                out.put(line)
        except (OSError, ValueError):
            pass
        finally:
            out.put(None)
    reader = threading.Thread(target=pump, daemon=True, name="render-output")
    reader.start()
    lines, deadline = [], time.time() + timeout
    best = 0.0     # progress only ever moves forward
    heard = time.time()
    why = ""
    while True:
        try:
            line = out.get(timeout=1.0)
        except queue.Empty:
            line = ""
        if line is None:
            break                         # the renderer closed its output: it is done
        now = time.time()
        if line:
            heard = now
            lines.append(line)
            if len(lines) > 400:          # keep the tail, not the whole log
                del lines[:200]
            frac = _render_progress(line)
            if frac is not None and frac > best:
                best = frac
                if on_progress is not None:
                    try:
                        on_progress(frac)
                    except Exception:
                        pass
        if cancel is not None and cancel.is_set():
            why = "cancel"
        elif now > deadline:
            why = "timeout"
        elif stall and now - heard > stall:
            why = "stall"
        if why:
            break
    if why:
        _stop(proc)
        reader.join(2.0)
    else:
        proc.wait()
    if not reader.is_alive():             # (never closed under a blocked read: that can hang)
        proc.stdout.close()
    if why in ("timeout", "stall"):
        raise _Stopped(why, best)
    code = proc.returncode
    return _Completed(code if code is not None else -9, "".join(lines), "")


def _stop(proc) -> None:
    """
    Stop a render. SIGTERM first: Remotion then closes its browser ("Received
    SIGTERM signal. Killing browser process"); a hard kill would leave Chrome
    running on the machine. One that lingers is killed with everything it
    started. (Its output pipe is left to the reader thread: closing it under a
    blocked read can hang.)
    """
    try:
        proc.terminate()
    except OSError:
        pass
    try:
        proc.wait(timeout=10.0)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=10.0)
    except subprocess.TimeoutExpired:
        pass


def _measure_loudness(path: str, target: float) -> dict:
    """loudnorm's first pass over a file's sound: its measurement dict, or {} when unreadable."""
    tp = config.LOUDNESS_TRUE_PEAK
    probe = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-vn",
         "-af", f"loudnorm=I={target}:TP={tp}:LRA=11:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", probe.stderr or "", re.S)
    if not m:
        return {}
    meas = json.loads(m.group(0))
    float(meas["input_i"])                  # a KeyError/ValueError here means no usable measurement
    return meas


def _loudnorm_filter(meas: dict, target: float) -> str:
    """The second (applying) loudnorm pass: one steady gain wherever the peaks allow it."""
    tp = config.LOUDNESS_TRUE_PEAK
    return (f"loudnorm=I={target}:TP={tp}:LRA=11:measured_I={meas['input_i']}:"
            f"measured_TP={meas['input_tp']}:measured_LRA={meas['input_lra']}:"
            f"measured_thresh={meas['input_thresh']}:offset={meas['target_offset']}:linear=true")


def finalize(video_path: str, audio_path: str, out_path: str, target: float = None) -> dict:
    """
    The finished MP4 from a picture-only render and its lossless sound track
    (render(audio_to=...)): the picture is copied as it is, the sound is set
    to `target` LUFS (config.LOUDNESS_TARGET_LUFS, 0 = as rendered) and
    encoded to AAC once, in one ffmpeg pass.

    Remotion writes its own AAC as ADTS and copies it into the MP4. ADTS has
    no field for the encoder's priming samples, so the 2048 samples libfdk
    puts before the sound played as silence: every render's sound ran
    42.7 ms behind the picture (a 4 s render: audio 4.053 s, video 4.000 s),
    and the old loudness pass kept that offset. ffmpeg's MP4 muxer records
    the priming of its own encoder in an edit list, so here the sound starts
    exactly on frame 0. Returns {"lufsIn", "lufsTarget", "gainApplied"}.
    """
    target = config.LOUDNESS_TARGET_LUFS if target is None else target
    info = {"lufsIn": None, "lufsTarget": target or None, "gainApplied": False}
    af = ""
    if target:
        try:
            meas = _measure_loudness(audio_path, target)
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as e:
            print(f"[render] loudness not measured: {type(e).__name__}", flush=True)
            meas = {}
        if meas:
            measured = float(meas["input_i"])
            info["lufsIn"] = round(measured, 1)
            if measured >= -60 and abs(measured - target) >= 0.7:   # not silent, not already there
                af = _loudnorm_filter(meas, target)
    tmp = out_path + ".part.mp4"

    def mux(filt: str):
        return subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", video_path, "-i", audio_path,
             "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy"] + (["-af", filt] if filt else [])
            + ["-ar", "48000", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", tmp],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600)
    p = mux(af)
    if af and (p.returncode != 0 or not os.path.isfile(tmp)):
        print(f"[render] loudness step skipped: {(p.stderr or '')[-200:]}", flush=True)
        af = ""
        p = mux("")
    if p.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) < 1024:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise RenderError(f"joining the picture and the sound failed: {(p.stderr or '')[-400:]}")
    os.replace(tmp, out_path)
    info["gainApplied"] = bool(af)
    if af:
        print(f"[render] loudness {info['lufsIn']:.1f} -> {target:.1f} LUFS", flush=True)
    return info


def normalize_loudness(path: str, target: float = None) -> bool:
    """
    Set a finished video's sound to `target` LUFS (config.LOUDNESS_TARGET_LUFS),
    true peak config.LOUDNESS_TRUE_PEAK, copying the picture. Two passes: the
    first measures, the second applies loudnorm with the measurement (a steady
    gain wherever the peaks allow it). True when the file was changed; any
    failure leaves the file as it was. (Renders with a separate sound track
    use finalize() instead: one pass, and the sound starts on frame 0.)
    """
    target = config.LOUDNESS_TARGET_LUFS if target is None else target
    if not target or not os.path.isfile(path):
        return False
    try:
        meas = _measure_loudness(path, target)
        if not meas:
            return False
        measured = float(meas["input_i"])
        if measured < -60 or abs(measured - target) < 0.7:
            return False                   # silent, or already there
        tmp = path + ".loud.mp4"
        af = _loudnorm_filter(meas, target)
        p = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", path, "-map", "0:v:0?", "-map", "0:a:0",
             "-c:v", "copy", "-af", af, "-ar", "48000", "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", tmp],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
        if p.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) < 1024:
            if os.path.exists(tmp):
                os.remove(tmp)
            print(f"[render] loudness step skipped: {(p.stderr or '')[-200:]}", flush=True)
            return False
        os.replace(tmp, path)
        print(f"[render] loudness {measured:.1f} -> {target:.1f} LUFS", flush=True)
        return True
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as e:
        print(f"[render] loudness step skipped: {type(e).__name__}", flush=True)
        return False


def fit_size(path: str, max_mb: float = None) -> bool:
    """
    Re-encode a finished video that is over `max_mb` (config.UPLOAD_MAX_MB) at
    a bitrate that fits, copying the sound. The app's storage refuses a file
    over its limit only after the whole upload, so without this a long render
    was lost at the last step. True when the file was changed; any failure
    leaves it as it was.
    """
    max_mb = config.UPLOAD_MAX_MB if max_mb is None else max_mb
    if not max_mb or not os.path.isfile(path):
        return False
    size = os.path.getsize(path)
    cap = max_mb * 1024 * 1024
    if size <= cap:
        return False
    seconds = probe_duration(path)
    if seconds <= 0:
        return False
    # 90% of the cap for the picture, after 192 kbit/s of sound.
    kbps = int(cap * 8 * 0.90 / seconds / 1000) - 192
    if kbps < 300:
        print(f"[render] {size / 1e6:.0f} MB over the {max_mb:.0f} MB upload cap and too long to fit", flush=True)
        return False
    tmp = path + ".fit.mp4"
    try:
        p = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", path, "-map", "0:v:0", "-map", "0:a:0?",
             "-c:v", "libx264", "-preset", "veryfast", "-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.5)}k",
             "-bufsize", f"{kbps * 2}k", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", tmp],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=max(1800, int(seconds * 3)))
        if p.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) < 1024:
            if os.path.exists(tmp):
                os.remove(tmp)
            print(f"[render] size fit skipped: {(p.stderr or '')[-200:]}", flush=True)
            return False
        new = os.path.getsize(tmp)
        os.replace(tmp, path)
        print(f"[render] {size / 1e6:.0f} MB over the {max_mb:.0f} MB upload cap -> {new / 1e6:.0f} MB "
              f"at {kbps} kbit/s", flush=True)
        return True
    except (OSError, subprocess.TimeoutExpired) as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        print(f"[render] size fit skipped: {type(e).__name__}", flush=True)
        return False


def probe_duration(media_path: str) -> float:
    """
    Duration in seconds via ffprobe, 0.0 when it can't be read.

    A missing ffprobe is a broken environment rather than an unreadable file, so
    it is logged loudly: callers silently fall back to the transcript's last
    timestamp, and an unexplained 0.0 otherwise reads as bad narration audio.
    """
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", media_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        return float((p.stdout or "0").strip())
    except FileNotFoundError:
        print("[render] ffprobe not on PATH - install ffmpeg. Durations will "
              "fall back to transcript timings.", flush=True)
        return 0.0
    except Exception:
        return 0.0
