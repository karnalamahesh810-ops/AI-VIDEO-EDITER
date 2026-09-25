"""Invoke the Remotion renderer as a subprocess and return the output path."""
import copy
import json
import os
import re
import shutil
import subprocess

from . import config
from .assetserver import AssetServer, localise


class RenderError(RuntimeError):
    pass


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
           concurrency: int = None, timeout: int = 5400,
           serve_dir: str = None, on_progress=None) -> str:
    """
    Render `props` to `out_path` with Remotion.

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
    props_path = os.path.join(os.path.dirname(out_path), "props.json")

    with AssetServer(work) as assets:
        # Rewrite a copy: the caller keeps the document it passed in, which is
        # what gets stored for the editor. Localhost URLs must not leak there.
        served = localise(copy.deepcopy(props), assets)
        with open(props_path, "w", encoding="utf-8") as f:
            json.dump(served, f)

        cmd = _renderer_argv() + [
            "render", "src/index.ts", composition, out_path,
            f"--props={props_path}",
            # --log=error hides the progress lines, so ask for more only when
            # somebody is listening.
            "--log=info" if on_progress else "--log=error",
        ]
        # A container sees the HOST's memory and cores. Remotion sizes its
        # frame cache at half of "system memory" and the compositor's decoders
        # scale with cores, so on a RunPod worker both overshoot the cgroup
        # until the compositor can no longer start a thread - the render dies
        # with "thread::unix::Thread::new::thread_start" partway through.
        # Fixed caps keep it inside the container.
        cmd += [f"--offthreadvideo-cache-size-in-bytes={config.RENDER_FRAME_CACHE_BYTES}",
                f"--offthreadvideo-video-threads={config.RENDER_VIDEO_THREADS}"]

        def run(argv):
            if on_progress is None:
                return subprocess.run(
                    argv, cwd=config.REMOTION_DIR, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=timeout,
                )
            return _run_streaming(argv, timeout, on_progress)

        p = run(cmd + ([f"--concurrency={concurrency}"] if concurrency else []))
        tail = (p.stderr or p.stdout or "")[-3000:]
        if p.returncode != 0 and ("thread_start" in tail or "Resource temporarily" in tail):
            # Still out of threads: one slower, single-tab retry beats losing
            # a whole job that already spent minutes sourcing.
            print("[render] out of threads - retrying at concurrency 1", flush=True)
            p = run(cmd + ["--concurrency=1"])

    if p.returncode != 0 or not os.path.exists(out_path):
        tail = (p.stderr or p.stdout or "")[-1500:]
        raise RenderError(f"remotion render failed (exit {p.returncode}): {tail}")
    return out_path


class _Completed:
    """Just enough of CompletedProcess for the error path below."""

    def __init__(self, returncode, stdout, stderr):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _run_streaming(cmd, timeout, on_progress) -> "_Completed":
    """Run Remotion, forwarding progress while keeping the output for errors."""
    import time
    proc = subprocess.Popen(
        cmd, cwd=config.REMOTION_DIR, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        bufsize=1,
    )
    lines, deadline = [], time.time() + timeout
    best = [0.0]   # progress only ever moves forward
    try:
        for line in proc.stdout:
            lines.append(line)
            if len(lines) > 400:          # keep the tail, not the whole log
                del lines[:200]
            frac = _render_progress(line)
            if frac is not None and frac > best[0]:
                best[0] = frac
                try:
                    on_progress(frac)
                except Exception:
                    pass
            if time.time() > deadline:
                proc.kill()
                raise subprocess.TimeoutExpired(cmd, timeout)
    finally:
        proc.stdout.close()
        proc.wait()
    return _Completed(proc.returncode, "".join(lines), "")


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
