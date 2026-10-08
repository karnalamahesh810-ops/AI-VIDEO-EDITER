"""
The GPU tools endpoint (gputools/ in this repo; RunPod serverless "thumbgenius-gpu-tools"): three optional
polishes, each off until its flag is on, none of which may fail or stall a video.

* UPSCALE_LOWRES_CLIPS - a clip under UPSCALE_LOWRES_BELOW lines (480p news and archive-era uploads, accepted
  since the owner's 480p decision of 2026-10-08) is sharpened to 1080 lines by FlashVSR v1.1 instead of the CPU
  Lanczos pass (src/upscale.py). Only the used section is sent (the sourced file IS the section); a clip the
  endpoint does not return in time goes through the Lanczos pass as before.
* INTERPOLATE_60FPS - in a 60 fps render, every clip under 50 fps is retimed to 60 fps by RIFE 4.25 before the
  render, so footage moves at 60 like the graphics instead of showing each frame twice (24/25 fps clips judder
  less, too). A clip not back in time keeps its own frame rate (the old doubled frames).
* AI_MUSIC - a music bed made for this video by ACE-Step 1.5: an instrumental from the story's mood at the
  video's length, at the library tracks' loudness, played by the renderer exactly like a library track (flat
  MUSIC_LEVEL, x MUSIC_DUCK under the words). A job asks for it with "ai_music": true (or {"mood", "prompt",
  "seed"}), "bgm_track": "ai" or {"config": {"AI_MUSIC": 1}}; it is started as soon as the story's mood and
  the narration's length are known and picked up when the timeline is built. Not ready in time / failed: the
  library track the job would have had.

The endpoint: GPU_TOOLS_ENDPOINT_ID, GPU_TOOLS_API_KEY (else RUNPOD_API_KEY - it must have run/status rights
on that endpoint), GPU_TOOLS_API_BASE. Clips go to it through R2 (gputools/in/..., the worker's own R2_*) and
come back as R2 links (gputools/out/<job>.mp4) - both only needed for minutes (an R2 lifecycle rule may expire
them); music beds come back under gputools/music/ and are kept (the timeline plays that link on every re-render).
Keys are never printed.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
import zlib
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

from . import config

RUNPOD_API = "https://api.runpod.ai/v2"
_UA = {"User-Agent": "Mozilla/5.0 (ThumbGenius worker)"}
STATS: Dict[str, Any] = {}
_LOCK = threading.Lock()
# Clips this job already retimed to the render's rate on the endpoint (an upscale that carried fps=60).
RETIMED: set = set()


class GpuToolsError(RuntimeError):
    pass


# ------------------------------------------------------------------ the endpoint
class Client:
    def __init__(self, endpoint: str = "", key: str = "", base: str = ""):
        self.endpoint = (endpoint or config.GPU_TOOLS_ENDPOINT_ID or "").strip()
        self._key = (key or config.GPU_TOOLS_API_KEY or os.getenv("RUNPOD_API_KEY", "")).strip()
        self.base = (base or config.GPU_TOOLS_API_BASE or RUNPOD_API).rstrip("/")
        self.session = requests.Session()

    def available(self) -> bool:
        return bool(self.endpoint and self._key)

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}

    def submit(self, payload: Dict[str, Any]) -> str:
        try:
            r = self.session.post(f"{self.base}/{self.endpoint}/run", headers=self._headers(),
                                  json={"input": payload}, timeout=(10, 30))
        except requests.RequestException as e:
            raise GpuToolsError(f"submit: {type(e).__name__}") from e
        if r.status_code >= 300:
            raise GpuToolsError(f"submit: HTTP {r.status_code}")
        jid = str((r.json() or {}).get("id") or "")
        if not jid:
            raise GpuToolsError("submit: no job id")
        return jid

    def status(self, jid: str) -> Dict[str, Any]:
        try:
            r = self.session.get(f"{self.base}/{self.endpoint}/status/{jid}", headers=self._headers(),
                                 timeout=(10, 30))
            return r.json() if r.status_code < 300 else {"status": f"HTTP {r.status_code}"}
        except (requests.RequestException, ValueError):
            return {}

    def cancel(self, jid: str) -> None:
        try:
            self.session.post(f"{self.base}/{self.endpoint}/cancel/{jid}", headers=self._headers(), timeout=15)
        except requests.RequestException:
            pass

    def run(self, payload: Dict[str, Any], deadline: float, poll: float = 2.0) -> Dict[str, Any]:
        """Submit and wait until `deadline` (epoch s); the job's output dict. Past the deadline the job is
        cancelled (no GPU time is paid for an answer nobody waits for)."""
        jid = self.submit(payload)
        while True:
            st = self.status(jid)
            state = str(st.get("status") or "")
            if state == "COMPLETED":
                out = st.get("output") if isinstance(st.get("output"), dict) else {}
                if not out.get("ok"):
                    raise GpuToolsError(str(out.get("error") or "the endpoint answered without a result")[:300])
                out["_execution_ms"] = st.get("executionTime")
                out["_delay_ms"] = st.get("delayTime")
                return out
            if state in ("FAILED", "CANCELLED", "TIMED_OUT"):
                raise GpuToolsError(f"job {state.lower()}: {str(st.get('error') or '')[:200]}")
            if time.time() > deadline:
                self.cancel(jid)
                raise GpuToolsError("not back in time")
            time.sleep(poll)


_CLIENT: Dict[str, Client] = {}


def client() -> Optional[Client]:
    """The configured endpoint, or None (every polish here is then off)."""
    c = _CLIENT.get("c")
    if c is None:
        c = _CLIENT["c"] = Client()
    return c if c.available() else None


def _stat(key: str, n: float = 1) -> None:
    with _LOCK:
        STATS[key] = round(STATS.get(key, 0) + n, 3)


def reset() -> None:
    """A new job: its own stats, retimed set and music bed."""
    with _LOCK:
        STATS.clear()
        RETIMED.clear()
    _MUSIC.clear()


# ------------------------------------------------------------------ files through R2
def _stage(path: str) -> str:
    """A local clip as an https link the endpoint can fetch (R2, gputools/in/<random>/...)."""
    from . import r2
    if not r2.enabled():
        raise GpuToolsError("R2 is not configured on this worker")
    key = f"gputools/in/{uuid.uuid4().hex}/{os.path.basename(path)}"
    return r2.upload(path, key, r2.content_type(path, "video/mp4"))


def _fetch(url: str, dst: str, min_bytes: int = 4000) -> str:
    last = "no link"
    for attempt in range(3):
        try:
            with requests.get(url, headers=_UA, stream=True, timeout=(15, 300)) as r:
                if r.status_code == 200:
                    tmp = dst + ".part"
                    with open(tmp, "wb") as fh:
                        for chunk in r.iter_content(1 << 20):
                            fh.write(chunk)
                    if os.path.getsize(tmp) >= min_bytes:
                        os.replace(tmp, dst)
                        return dst
                    last = "empty file"
                else:
                    last = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last = type(e).__name__
        time.sleep(2 * (attempt + 1))
    raise GpuToolsError(f"download: {last}")


def _probe(path: str) -> Dict[str, float]:
    import json
    import subprocess
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height,avg_frame_rate:format=duration", "-of", "json", path],
                           capture_output=True, text=True, timeout=30)
        d = json.loads(p.stdout or "{}")
        s = (d.get("streams") or [{}])[0]
        num, _, den = str(s.get("avg_frame_rate") or "0/1").partition("/")
        fps = float(num) / float(den or 1) if float(den or 1) else 0.0
        return {"w": int(s.get("width") or 0), "h": int(s.get("height") or 0), "fps": fps,
                "seconds": float((d.get("format") or {}).get("duration") or 0.0)}
    except (ValueError, OSError, subprocess.TimeoutExpired):
        return {"w": 0, "h": 0, "fps": 0.0, "seconds": 0.0}


def _replace_checked(path: str, got: str, want_lines: int = 0, want_fps: float = 0.0) -> bool:
    """`got` replaces `path` only when it is a real clip of the same length (and, when asked, the lines and the
    frame rate it should have now)."""
    a, b = _probe(path), _probe(got)
    ok = (b["w"] > 0 and b["h"] > 0 and b["seconds"] > 0.2 and abs(b["seconds"] - a["seconds"]) <= 0.35
          and (not want_lines or min(b["w"], b["h"]) >= want_lines - 2)
          and (not want_fps or abs(b["fps"] - want_fps) <= 0.6))
    if ok:
        os.replace(got, path)
    else:
        try:
            os.remove(got)
        except OSError:
            pass
    return ok


# ------------------------------------------------------------------ clips
def lowres_candidates(assets: Iterable) -> List[Tuple[Any, str, int]]:
    """(asset, path, lines) of the clips the endpoint should sharpen: landscape video under UPSCALE_LOWRES_BELOW
    lines (and at least 240), at most UPSCALE_LOWRES_MAX_SECONDS long, not archive film (src/archive_restore.py
    restores those its own way)."""
    out, seen = [], set()
    for a in assets:
        path = getattr(a, "local_path", "") or ""
        if (not a or getattr(a, "kind", "") != "video" or getattr(a, "source", "") == "archive_org"
                or not path or path in seen or not os.path.isfile(path)):
            continue
        seen.add(path)
        p = _probe(path)
        if not p["w"] or not p["h"] or p["w"] < p["h"] * 1.2:
            continue                                     # vertical / square: framed on its blurred copy instead
        lines = min(p["w"], p["h"])
        if 240 <= lines < int(config.UPSCALE_LOWRES_BELOW) and 0 < p["seconds"] <= config.UPSCALE_LOWRES_MAX_SECONDS:
            out.append((a, path, lines))
    return out


def upscale_lowres(assets: Iterable, deadline: float, fps: int = 0) -> Dict[str, Any]:
    """
    Sharpen the low-resolution clips of `assets` on the endpoint, in place, all at once (the endpoint scales
    out), until `deadline`. With a 60 fps render and INTERPOLATE_60FPS, the same job retimes the result to 60.
    Returns {"done": [paths], "failed": n, ...}; a clip not done is left exactly as it was.
    """
    from . import upscale as _up
    c = client() if config.UPSCALE_LOWRES_CLIPS else None
    jobs = lowres_candidates(assets) if c else []
    report: Dict[str, Any] = {"queued": len(jobs), "done": [], "failed": 0, "errors": []}
    if not jobs:
        return report
    retime = int(fps or 0) >= 50 and config.INTERPOLATE_60FPS

    def one(job):
        _a, path, lines = job
        t0 = time.time()
        try:
            url = _stage(path)
            payload = {"action": "upscale", "url": url, "lines": 1080}
            if retime and _probe(path)["fps"] < 50:
                payload["fps"] = int(fps)
            out = c.run(payload, deadline)
            got = _fetch(out["url"], path + ".gpu.mp4")
            if not _replace_checked(path, got, want_lines=1080, want_fps=float(payload.get("fps") or 0)):
                raise GpuToolsError("the result did not match the clip")
            with _up._LOCK:
                _up.UPSCALED[os.path.abspath(path)] = lines
            if payload.get("fps"):
                with _LOCK:
                    RETIMED.add(os.path.abspath(path))
            _stat("upscaled")
            _stat("upscale_gpu_ms", float(out.get("_execution_ms") or 0))
            return path
        except Exception as e:  # noqa: BLE001 - the clip keeps the CPU path
            _stat("upscale_failed")
            report["errors"].append(f"{os.path.basename(path)}: {str(e)[:120]}")
            return None
        finally:
            _stat("upscale_wall_s", time.time() - t0)

    with ThreadPoolExecutor(max_workers=max(1, int(config.GPU_TOOLS_PARALLEL)), thread_name_prefix="gpu-up") as pool:
        done = [p for p in pool.map(one, jobs) if p]
    report["done"] = done
    report["failed"] = len(jobs) - len(done)
    report["errors"] = report["errors"][:6]
    print(f"[gputools] {len(done)}/{len(jobs)} low-resolution clip(s) sharpened on the GPU"
          + (f" ({report['failed']} kept the CPU path)" if report["failed"] else ""), flush=True)
    return report


def interpolate_clips(assets: Iterable, fps: int, deadline: float) -> Dict[str, Any]:
    """In a 60 fps render (INTERPOLATE_60FPS), every clip under 50 fps retimed to `fps` on the endpoint, in place,
    until `deadline`. A clip not back in time keeps its own rate (the renderer shows its frames twice)."""
    c = client() if config.INTERPOLATE_60FPS and int(fps or 0) >= 50 else None
    report: Dict[str, Any] = {"queued": 0, "done": 0, "failed": 0, "errors": []}
    if not c:
        return report
    jobs, seen = [], set()
    for a in assets:
        path = getattr(a, "local_path", "") or ""
        if (not a or getattr(a, "kind", "") != "video" or not path or path in seen or not os.path.isfile(path)
                or os.path.abspath(path) in RETIMED):
            continue
        seen.add(path)
        p = _probe(path)
        if 0 < p["fps"] < 50 and 0 < p["seconds"] <= config.INTERPOLATE_MAX_SECONDS:
            jobs.append(path)
    report["queued"] = len(jobs)

    def one(path):
        try:
            url = _stage(path)
            out = c.run({"action": "interpolate", "url": url, "fps": int(fps)}, deadline)
            got = _fetch(out["url"], path + ".gpu60.mp4")
            if not _replace_checked(path, got, want_fps=float(fps)):
                raise GpuToolsError("the result did not match the clip")
            with _LOCK:
                RETIMED.add(os.path.abspath(path))
            _stat("retimed")
            _stat("retime_gpu_ms", float(out.get("_execution_ms") or 0))
            return True
        except Exception as e:  # noqa: BLE001 - the clip keeps its own rate
            _stat("retime_failed")
            report["errors"].append(f"{os.path.basename(path)}: {str(e)[:120]}")
            return False

    with ThreadPoolExecutor(max_workers=max(1, int(config.GPU_TOOLS_PARALLEL)), thread_name_prefix="gpu-fi") as pool:
        report["done"] = sum(1 for ok in pool.map(one, jobs) if ok)
    report["failed"] = report["queued"] - report["done"]
    report["errors"] = report["errors"][:6]
    print(f"[gputools] {report['done']}/{report['queued']} clip(s) retimed to {fps} fps on the GPU", flush=True)
    return report


# ------------------------------------------------------------------ music
# The caption for each mood (the bundled genres of timeline._BGM_BY_KIND, plus "uplifting"): an underscore under
# a narration - no vocals, no lead melody fighting the voice, no drop.
MOODS = {
    "suspense": ("tense documentary underscore, dark cinematic tension, low sustained strings, deep pulsing synth "
                 "bass, sparse ticking percussion, ominous atmosphere, slow build, instrumental, no vocals"),
    "investigative": ("calm investigative documentary underscore, soft piano, warm ambient pads, light pulse, "
                      "curious and thoughtful, steady, instrumental, no vocals"),
    "crime": ("dark true crime underscore, brooding synth bass, sparse piano notes, ticking percussion, mysterious "
              "and suspenseful, instrumental, no vocals"),
    "uplifting": ("uplifting inspirational documentary music, warm strings, gentle piano, soft building percussion, "
                  "hopeful and bright, cinematic, instrumental, no vocals"),
}
_MOOD_WORDS = {"tense": "suspense", "tension": "suspense", "dramatic": "suspense", "news": "suspense",
               "documentary": "investigative", "calm": "investigative", "true-crime": "crime", "mystery": "crime",
               "dark": "crime", "hopeful": "uplifting", "inspiring": "uplifting", "inspirational": "uplifting",
               "positive": "uplifting"}
_MUSIC: Dict[str, Any] = {}


def music_wanted(inp: Dict[str, Any]) -> bool:
    """The job asks for an AI bed: "ai_music" (true / an object), "bgm_track"/"bgm_genre" "ai", or AI_MUSIC on
    (a job's "ai_music": false still says no). Never when the job brings its own track or no music at all."""
    if inp.get("bgm_url") or inp.get("bgm") is False:
        return False
    own = inp.get("ai_music")
    if own is False or str(own).strip().lower() in ("0", "false", "no", "off"):
        return False
    if own or str(inp.get("bgm_track") or "").strip().lower() == "ai" \
            or str(inp.get("bgm_genre") or "").strip().lower() == "ai":
        return True
    return bool(config.AI_MUSIC)


def music_request(inp: Dict[str, Any], mood: str, seconds: float) -> Dict[str, Any]:
    """The endpoint's input for this job: the job's own prompt, else the mood's caption; a stable seed per
    project (a re-plan gets the same bed unless the job sends another seed); the video's length plus a tail."""
    own = inp.get("ai_music") if isinstance(inp.get("ai_music"), dict) else {}
    asked = str(own.get("mood") or "").strip().lower()
    mood = _MOOD_WORDS.get(asked, asked) if asked else mood
    mood = mood if mood in MOODS else "investigative"
    caption = " ".join(str(own.get("prompt") or "").split())[:400] or MOODS[mood]
    seed_src = str(inp.get("project_id") or inp.get("title") or "thumbgenius")
    seed = own.get("seed")
    try:
        seed = int(seed) if seed is not None else zlib.crc32(seed_src.encode("utf-8")) % 2_147_483_647
    except (TypeError, ValueError):
        seed = zlib.crc32(seed_src.encode("utf-8")) % 2_147_483_647
    length = min(float(config.AI_MUSIC_MAX_SECONDS), max(10.0, float(seconds or 0) + config.AI_MUSIC_TAIL_SECONDS))
    return {"action": "music", "caption": caption, "seconds": round(length, 1), "seed": seed,
            "lm": bool(config.AI_MUSIC_LM), "lufs": float(config.AI_MUSIC_LUFS), "_mood": mood}


def _job_key(inp: Dict[str, Any]) -> str:
    """Which video a bed was made for (a worker runs one job at a time, but a later job must never play it)."""
    own = str(inp.get("audio_url") or "") or str(inp.get("script") or "")[:80]
    return f"{inp.get('project_id') or ''}|{inp.get('title') or ''}|{own}"


def start_music(inp: Dict[str, Any], mood: str, seconds: float) -> bool:
    """Start this job's bed on the endpoint in the background (picked up by music_for). False = not started (not
    wanted, or no endpoint)."""
    _MUSIC.clear()
    if not music_wanted(inp):
        return False
    c = client()
    if not c:
        _MUSIC["result"] = {"ok": False, "error": "no GPU tools endpoint configured"}
        return False
    req = music_request(inp, mood, seconds)
    mood = req.pop("_mood")
    done = threading.Event()
    _MUSIC.update({"event": done, "mood": mood, "request": req, "started": time.time(), "key": _job_key(inp)})

    def run():
        try:
            out = c.run(req, time.time() + float(config.AI_MUSIC_SECONDS))
            _MUSIC["result"] = {**out, "mood": mood}
        except Exception as e:  # noqa: BLE001 - the library track plays instead
            _MUSIC["result"] = {"ok": False, "error": str(e)[:200], "mood": mood}
        finally:
            done.set()

    threading.Thread(target=run, name="ai-music", daemon=True).start()
    print(f"[gputools] AI music started: {mood}, {req['seconds']:.0f} s", flush=True)
    return True


def music_for(inp: Dict[str, Any], wait: float = 0.0) -> Optional[Dict[str, Any]]:
    """This job's AI bed as the timeline's bgm (url, volume, genre, trackSeconds, loop, ai), waiting up to
    `wait` s for it; None = play the library track (not asked, not ready, failed - the reason is in STATS)."""
    if not music_wanted(inp):
        return None
    if _MUSIC.get("key", _job_key(inp)) != _job_key(inp):
        return None                      # another job's bed (a flow that did not start one): never borrowed
    ev = _MUSIC.get("event")
    if ev is not None:
        ev.wait(timeout=max(0.0, float(wait)))
    res = _MUSIC.get("result")
    if not res or not res.get("ok") or not str(res.get("url") or "").startswith("https://"):
        with _LOCK:
            STATS["music"] = {"ok": False, "why": (res or {}).get("error") or "not ready in time"}
        return None
    with _LOCK:
        STATS["music"] = {"ok": True, "seconds": res.get("seconds"), "lufs": res.get("lufs"),
                          "gpu_ms": res.get("_execution_ms"), "mood": res.get("mood")}
    return {"url": res["url"], "genre": res.get("mood") or "", "trackSeconds": float(res.get("seconds") or 0),
            "loop": True, "lufs": res.get("lufs"),
            "ai": {"model": "ace-step-1.5", "mood": res.get("mood"), "seed": res.get("seed"),
                   "caption": str(res.get("caption") or "")[:400]}}
