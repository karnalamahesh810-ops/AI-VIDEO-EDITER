"""Invoke the Remotion renderer as a subprocess and return the output path."""
import json
import os
import subprocess

from . import config


class RenderError(RuntimeError):
    pass


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

    cmd = [
        "npx", "remotion", "render", "src/index.ts", composition, out_path,
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
    """Duration in seconds via ffprobe/ffmpeg, 0.0 when it can't be read."""
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", media_path],
            capture_output=True, text=True, timeout=60,
        )
        return float((p.stdout or "0").strip())
    except Exception:
        return 0.0
