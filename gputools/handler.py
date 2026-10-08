"""
ThumbGenius GPU tools - RunPod serverless handler (endpoint "thumbgenius-gpu-tools"; the video worker's client
is runpod/src/gputools.py). Three tools on one GPU image; each is loaded on its first job and kept while the
worker lives (FlashBoot keeps the process between jobs):

  action "health"       -> {"ok", "gpu", "vram_gb", "loaded", "r2", "boot_seconds"}
  action "upscale"      FlashVSR v1.1: url (https; the used section of a clip under 720 lines, <= 20 s), lines
                        (1080), start / seconds (cut first), fps (0, or 60: retime the result with RIFE in the same
                        job), sparse, local_range, seed
                        -> {"ok", "url", "size", "source", "frames", "fps", "seconds", "gpu_seconds", "timings"}
  action "interpolate"  RIFE 4.25: url (https, <= 60 s), fps (60), start / seconds, scene (cut threshold)
                        -> {"ok", "url", "frames_in", "frames_out", "interpolated", "cuts", "gpu_seconds", ...}
  action "music"        ACE-Step 1.5: caption, seconds (10-600), seed, bpm, keyscale, steps, lm, lufs (-27)
                        -> {"ok", "url", "seconds", "lufs", "true_peak", "seed", "gpu_seconds", ...}

Errors come back as {"ok": false, "error"}: the caller keeps its own path (the CPU Lanczos upscale, the doubled
frames, a library track) - nothing here may fail a video.
Outputs go to R2 (clips: gputools/out/<job id>.mp4, short-lived; music beds: gputools/music/<job id>.mp3, kept -
a timeline plays the link), the public link; GPUTOOLS_LOCAL_OUT=<dir> writes them to a folder instead (tests).
"""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
import traceback

import requests

BOOT = time.time()

import plan  # noqa: E402
import r2  # noqa: E402

MAX_INPUT_BYTES = 400 * 1024 * 1024
UA = {"User-Agent": "Mozilla/5.0 (ThumbGenius gpu-tools worker)"}
# GiB free each engine needs on the GPU (to load and then run a job at 1080p) beyond what is already resident;
# measured on an A40, 2026-10-09: FlashVSR tiny peaked at 30.3 GB on an 8 s 16:9 clip (the long pipeline 20.6 GB),
# ACE-Step 12.1 GB (10.6 resident), RIFE 0.6 GB. Before a job, other loaded engines are unloaded (least recently
# used first) until that much is free - three engines share one card.
_TINY = os.environ.get("FLASHVSR_PIPELINE", "tiny").strip().lower() == "tiny"
NEED_GB = {"vsr": float(os.environ.get("NEED_GB_VSR", "31" if _TINY else "21")),
           "music": float(os.environ.get("NEED_GB_MUSIC", "13")),
           "rife": float(os.environ.get("NEED_GB_RIFE", "2"))}
# GiB an engine that is already loaded still needs free to run (its working set).
WORK_GB = {"vsr": float(os.environ.get("WORK_GB_VSR", "27" if _TINY else "17")),
           "music": float(os.environ.get("WORK_GB_MUSIC", "2")),
           "rife": float(os.environ.get("WORK_GB_RIFE", "1"))}
USED: dict = {}
ENGINES: dict = {}
_LOCK = threading.Lock()


def _gpu_free_gb() -> float:
    import torch
    free, _total = torch.cuda.mem_get_info()
    return free / 2 ** 30


def _unload(name: str) -> None:
    import gc

    import torch
    eng = ENGINES.pop(name, None)
    if eng is not None:
        del eng
        gc.collect()
        torch.cuda.empty_cache()
        print(f"[gputools] unloaded {name} to make room", flush=True)


def _make_room(name: str, need: float) -> None:
    """Unload the other engines, least recently used first, until `need` GiB are free."""
    for other in sorted([k for k in ENGINES if k != name], key=lambda k: USED.get(k, 0.0)):
        if _gpu_free_gb() >= need:
            return
        _unload(other)


def engine(name: str):
    """The engine, loaded on first use and kept; others are unloaded first when the GPU would run short."""
    with _LOCK:
        USED[name] = time.time()
        if name in ENGINES:
            _make_room(name, WORK_GB[name])
            return ENGINES[name]
        _make_room(name, NEED_GB[name])
        t0 = time.time()
        if name == "vsr":
            from vsr import FlashVSR
            ENGINES[name] = FlashVSR()
        elif name == "rife":
            from rife import Rife
            ENGINES[name] = Rife()
        elif name == "music":
            from music import Music
            ENGINES[name] = Music()
        else:
            raise plan.InputError(f"no engine {name}")
        print(f"[gputools] loaded {name} in {time.time() - t0:.1f} s", flush=True)
        return ENGINES[name]


def fetch(url: str, path: str, max_bytes: int = MAX_INPUT_BYTES) -> str:
    """Download `url` to `path` (whole or not at all), at most `max_bytes`."""
    with requests.get(url, headers=UA, stream=True, timeout=(15, 120)) as r:
        if r.status_code != 200:
            raise plan.InputError(f"{url.split('?')[0][-60:]} answered HTTP {r.status_code}")
        tmp, size = f"{path}.part", 0
        with open(tmp, "wb") as fh:
            for chunk in r.iter_content(1 << 20):
                size += len(chunk)
                if size > max_bytes:
                    raise plan.InputError(f"{url.split('?')[0][-60:]} is larger than {max_bytes >> 20} MB")
                fh.write(chunk)
    os.replace(tmp, path)
    return path


def publish(path: str, job_id: str, ext: str, content_type: str) -> str:
    local = os.environ.get("GPUTOOLS_LOCAL_OUT", "").strip()
    if local:
        os.makedirs(local, exist_ok=True)
        dst = os.path.join(local, os.path.basename(plan.out_key(job_id, ext)))
        shutil.copyfile(path, dst)
        return "file://" + dst
    if not r2.enabled():
        raise RuntimeError("R2 is not configured on this worker (R2_* environment)")
    return r2.upload_file(path, plan.out_key(job_id, ext), content_type)


def _clip_ext(url: str) -> str:
    ext = os.path.splitext(url.split("?")[0])[1].lower()
    return ext if ext in (".mp4", ".mov", ".webm", ".mkv", ".m4v") else ".mp4"


def do_upscale(job_id: str, inp: dict) -> dict:
    import media
    args = plan.check_upscale(inp)
    work = tempfile.mkdtemp(prefix="up_")
    try:
        src = fetch(args["url"], os.path.join(work, "in" + _clip_ext(args["url"])))
        info = media.probe(src)
        if not info["w"] or not info["h"]:
            raise plan.InputError("the clip has no picture")
        if min(info["w"], info["h"]) > plan.UPSCALE_MAX_SOURCE_LINES or min(info["w"], info["h"]) >= args["lines"]:
            raise plan.InputError(f"the clip already has {min(info['w'], info['h'])} lines")
        t0 = time.time()
        out = os.path.join(work, "out.mp4")
        then = args["fps"] and abs(args["fps"] - float(info["fps"] or 0)) > 0.5
        got = engine("vsr").upscale(src, out if not then else os.path.join(work, "vsr.mp4"), lines=args["lines"],
                                    start=args["start"], seconds=args["seconds"], sparse=args["sparse"],
                                    local_range=args["local_range"], seed=args["seed"], info=info,
                                    keep_frames=bool(then), text_guard=args["text_guard"])
        if then:
            frames, vinfo = got.pop("rgb"), got.pop("info")
            vinfo["audio"] = False
            rt = engine("rife").retime(os.path.join(work, "vsr.mp4"), out, fps_out=args["fps"], info=vinfo,
                                       frames=frames)
            got["retime"] = plan.pick(rt, "frames_out", "interpolated", "cuts", "fps_out", "timings")
            got["fps"] = args["fps"]
            got["frames"] = rt["frames_out"]
            # the sound: the source's section, laid on the retimed picture
            _remux_audio(out, src, args["start"], args["seconds"], info)
        url = publish(out, job_id, "mp4", "video/mp4")
        return {"ok": True, "url": url, **got, "gpu_seconds": round(time.time() - t0, 1),
                "engine": "flashvsr-1.1-tiny"}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _remux_audio(video: str, src: str, start: float, seconds: float, info: dict) -> None:
    """Put the source section's sound on `video` (in place); without sound in the source nothing changes."""
    import subprocess

    import media
    if not info.get("audio"):
        return
    tmp = video + ".a.mp4"
    cmd = [media.FFMPEG, "-v", "error", "-y", "-nostdin", "-i", video]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    if seconds > 0:
        cmd += ["-t", f"{seconds:.3f}"]
    cmd += ["-i", src, "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
            "-af", "apad", "-t", f"{media.duration(video):.3f}", "-movflags", "+faststart", tmp]
    p = subprocess.run(cmd, capture_output=True, timeout=300)
    if p.returncode == 0 and os.path.isfile(tmp):
        os.replace(tmp, video)


def do_interpolate(job_id: str, inp: dict) -> dict:
    import media
    args = plan.check_interpolate(inp)
    work = tempfile.mkdtemp(prefix="fi_")
    try:
        src = fetch(args["url"], os.path.join(work, "in" + _clip_ext(args["url"])))
        info = media.probe(src)
        if not info["w"] or not info["h"]:
            raise plan.InputError("the clip has no picture")
        if info["seconds"] - args["start"] > plan.INTERP_MAX_SECONDS + 0.5 and not args["seconds"]:
            raise plan.InputError(f"the clip is longer than {plan.INTERP_MAX_SECONDS:.0f} s; send the used part")
        t0 = time.time()
        out = os.path.join(work, "out.mp4")
        got = engine("rife").retime(src, out, fps_out=args["fps"], start=args["start"], seconds=args["seconds"],
                                    scene=args["scene"], info=info)
        url = publish(out, job_id, "mp4", "video/mp4")
        return {"ok": True, "url": url, **got, "gpu_seconds": round(time.time() - t0, 1), "engine": "rife-4.25"}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def do_music(job_id: str, inp: dict) -> dict:
    args = plan.check_music(inp)
    work = tempfile.mkdtemp(prefix="mu_")
    try:
        t0 = time.time()
        out = os.path.join(work, "bed.mp3")
        got = engine("music").generate(out, args["caption"], args["seconds"], seed=args["seed"], bpm=args["bpm"],
                                       keyscale=args["keyscale"], steps=args["steps"], use_lm=args["lm"],
                                       lufs=args["lufs"], fade_in=args["fade_in"], fade_out=args["fade_out"],
                                       carve_db=args["carve_db"])
        url = publish(out, job_id, "mp3", "audio/mpeg")
        return {"ok": True, "url": url, **got, "caption": args["caption"], "asked_seconds": args["asked_seconds"],
                "gpu_seconds": round(time.time() - t0, 1), "engine": "ace-step-1.5"}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def health() -> dict:
    import torch
    gpu, vram = None, 0.0
    if torch.cuda.is_available():
        gpu = torch.cuda.get_device_name(0)
        vram = round(torch.cuda.get_device_properties(0).total_memory / 2 ** 30, 1)
    return {"ok": True, "gpu": gpu, "vram_gb": vram, "boot_seconds": round(time.time() - BOOT, 1),
            "loaded": sorted(ENGINES), "r2": r2.enabled() or bool(os.environ.get("GPUTOOLS_LOCAL_OUT"))}


ACTIONS = {"upscale": do_upscale, "interpolate": do_interpolate, "music": do_music}


def handler(job: dict) -> dict:
    inp = job.get("input") or {}
    try:
        act = plan.action_of(inp)
        if act == "health":
            return health()
        return ACTIONS[act](str(job.get("id") or "job"), inp)
    except plan.InputError as e:
        return {"ok": False, "error": f"input: {e}"}
    except Exception as e:  # noqa: BLE001 - the caller keeps its own path
        print(traceback.format_exc()[-2000:], flush=True)
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}


if __name__ == "__main__":
    import runpod
    for name in [n.strip() for n in os.environ.get("GPUTOOLS_PRELOAD", "").split(",") if n.strip()]:
        try:
            engine(name)                       # before the first job (FlashBoot keeps it)
        except Exception as e:  # noqa: BLE001 - the job will try again and report it
            print(f"[gputools] preload {name} failed: {type(e).__name__}: {str(e)[:200]}", flush=True)
    runpod.serverless.start({"handler": handler})
