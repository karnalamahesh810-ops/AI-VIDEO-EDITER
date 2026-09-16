"""Invoke the Remotion renderer as a subprocess and return the output path."""
import json
import os
import shutil
import subprocess

from . import config


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


def render(props: dict, out_path: str, composition: str = "Main",
           concurrency: int = None, timeout: int = 5400) -> str:
    """
    Render `props` to `out_path` with Remotion.

    Props are written to disk and passed with --props=<file>; passing a large
    JSON document as an inline argument blows the command-line length limit
    once a video has a few hundred scenes.
    """
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    props_path = os.path.join(os.path.dirname(out_path), "props.json")
    with open(props_path, "w", encoding="utf-8") as f:
        json.dump(props, f)

    cmd = _renderer_argv() + [
        "render", "src/index.ts", composition, out_path,
        f"--props={props_path}",
        "--log=error",
    ]
    if concurrency:
        cmd.append(f"--concurrency={concurrency}")

    p = subprocess.run(
        cmd, cwd=config.REMOTION_DIR, capture_output=True, text=True,
        timeout=timeout,
    )
    if p.returncode != 0 or not os.path.exists(out_path):
        tail = (p.stderr or p.stdout or "")[-1500:]
        raise RenderError(f"remotion render failed (exit {p.returncode}): {tail}")
    return out_path


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
            capture_output=True, text=True, timeout=60,
        )
        return float((p.stdout or "0").strip())
    except FileNotFoundError:
        print("[render] ffprobe not on PATH - install ffmpeg. Durations will "
              "fall back to transcript timings.", flush=True)
        return 0.0
    except Exception:
        return 0.0
