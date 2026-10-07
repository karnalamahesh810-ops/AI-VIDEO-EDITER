"""
Making the AI presenter video's shots: the presenter talking (lip-synced to
the master voice), the stills, and the AI video clips - every paid call
async (submit, poll, download), in bounded pools, checked, retried once, and
with a free fallback so the video always finishes.

  presenter  the shot's voice window (+0.3 s before, +0.6 s after, silence
             where the narration has none) goes with one of the kit's
             framings to the avatar model (heygen/avatar-iv). The clip comes
             back as long as the window; its own audio is compared with the
             window to find any offset, then it is trimmed to the scene
             (frame-exact, re-encoded) with its sound removed - the master
             voice is the only sound of the video, so the lips stay in sync.
             Checks: length, frozen, black, the face against the master.
             Retry: the other framing. Fallback: a still for the line (the
             b-roll path), then the kit's empty set.
  still      the line's picture from the style bible (or, for the
             presenter-in-action share, a picture of the presenter doing it,
             drawn from the master portrait). Checks: decodes, 16:9, the
             vision check. Retry: the next model. Fallback: the kit's set.
  AI video   the line's still is the start frame; the motion prompt moves
             it. Checks: length, frozen, black, the vision check on three
             frames. Retry: the next model with a new seed. Fallback: the
             still itself, which the renderer moves (camera move + living
             photo).

Every paid call goes through the job's Budget (refused past the cap: the
fallback instead) and the Cache (a request already paid for is not paid
again). What each asset cost, how many tries it took and why it fell back
is kept on it (meta.presenter.shots).
"""
from __future__ import annotations

import os
import threading
import time
import traceback
import zlib
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .. import costs
from . import checks as _checks
from . import kits as _kits
from . import media_io, tiers
from .budget import Budget, BudgetExceeded
from .director import bible_line
from .providers import ImageRequest, Provider, ProviderError, VideoRequest, data_url_for
from .shotplan import Shot
from .store import Cache, Store

PAD_BEFORE = 0.3
PAD_AFTER = 0.6
CLIP_HANDLE = 0.5             # seconds kept past a scene's end (a dissolve, rounding)
PRESENTER_PARALLEL = int(os.getenv("PRESENTER_PARALLEL", "6"))
VIDEO_PARALLEL = int(os.getenv("PRESENTER_VIDEO_PARALLEL", "6"))
IMAGE_PARALLEL = int(os.getenv("PRESENTER_IMAGE_PARALLEL", "6"))
WAIT_SECONDS = float(os.getenv("PRESENTER_WAIT_SECONDS", "900"))
POLL_SECONDS = float(os.getenv("PRESENTER_POLL_SECONDS", "10"))
FRAME_W, FRAME_H = 1920, 1080
SPLIT = ":split"              # the asset key of a split-screen presenter shot's picture half


@dataclass
class Asset:
    shot_id: str
    kind: str                       # "video" | "image"
    path: str                       # the local file the render uses (trimmed clip, 16:9 JPEG)
    source: str                     # ai-presenter | ai-video | ai-image | kit-set
    model: str = ""
    usd: float = 0.0
    url: str = ""                   # the generated original on R2
    width: int = 0
    height: int = 0
    seconds: float = 0.0
    prompt: str = ""
    framing: str = ""
    lag: Optional[float] = None
    attempts: int = 0
    fallback: str = ""
    checks: Dict[str, Any] = field(default_factory=dict)
    cached: str = ""

    def report(self) -> Dict[str, Any]:
        return {"kind": self.kind, "source": self.source, "model": self.model, "usd": round(self.usd, 4),
                "url": self.url, "seconds": round(self.seconds, 3), "framing": self.framing,
                "lag": self.lag, "attempts": self.attempts, "fallback": self.fallback,
                "checks": self.checks, "cached": self.cached}


def still_prompt(what: str, bible: Dict[str, str], kit: dict, in_shot: bool, no_people: bool = False) -> str:
    """A b-roll still's prompt: the line's picture in the video's one look (the references: candid, lived-in,
    photoreal snapshots in natural light - never glossy, never text or brands). `no_people`: the place and the
    things only (a split screen's half, beside the presenter: anyone else there reads as a second person)."""
    lens = bible.get("lens") or "candid camera at eye level, 35-50mm lens"
    palette = bible.get("palette") or "natural colours"
    parts = [f"Photorealistic candid photograph, 16:9: {what.strip().rstrip('.')}.", bible_line(bible),
             f"Taken with a {lens}, natural light, real textures, wear and small imperfections, gentle depth of field, "
             f"{palette}."]
    if in_shot:
        wardrobe = f" ({kit['wardrobe']})" if kit.get("wardrobe") else ""
        parts.append("The person in this picture is the person in the reference photo: exactly the same face, age, "
                     f"hair and clothes{wardrobe}, busy with the task and not looking at the camera.")
    elif no_people:
        parts.append("No people and no hands in the picture: only the place and the things in it.")
    elif "seen from behind" in what and (kit.get("from_behind") or kit.get("wardrobe")):
        # Someone seen from behind looks like the presenter from behind (the kit's silhouette, else their
        # clothes): the viewer reads them as the presenter, never as a stranger.
        who = kit.get("from_behind") or f"dressed in {kit['wardrobe']}"
        parts.append(f"The person seen from behind is {who}.")
    parts.append("No readable text, no signs, no captions, no brand names, logos or patches, no watermark. Hands, if "
                 "visible, natural and relaxed with five fingers. One real photograph - not a collage, not an "
                 "illustration, not a render.")
    return " ".join(p for p in parts if p)


# What a retry asks for after the look check found a giveaway (checks.SEVERE_BROLL and the scores).
_FIXES = {
    "garbled_text": "Every bit of print, label or sign is out of focus, too small to read or turned away: no "
                    "legible letters anywhere.",
    "melted_hands": "Hands are anatomically correct with five fingers each, or kept out of the frame.",
    "extra_fingers": "Hands are anatomically correct with five fingers each, or kept out of the frame.",
    "extra_limbs": "Every person has exactly two arms and two hands.",
    "warped_face": "No faces in close-up: anyone in the picture is seen from behind or far away.",
    "duplicated_person": "At most one person in the frame.",
    "morphing": "Every object keeps its shape: nothing melts, bends or turns into something else.",
    "impossible_physics": "Everything moves slowly, the way it does in real life.",
    "cartoonish": "A real, ordinary photograph - not an illustration, a painting or a render.",
    "watermark": "No watermark, logo or caption anywhere.",
    "collage": "One single photograph - never a collage or a split image.",
    "frozen": "Gentle, continuous natural movement for the whole clip.",
}


def _found(verdict: Dict[str, Any]) -> List[str]:
    """The issues a failed look check found, the low scores among them."""
    issues = [str(i) for i in verdict.get("issues") or []]
    try:
        if float(verdict.get("match", 1.0)) < 0.35:
            issues.append("off_topic")
        if float(verdict.get("real", 1.0)) < 0.45:
            issues.append("cartoonish")
    except (TypeError, ValueError):
        pass
    return issues


def fix_text(issues: List[str], what: str) -> str:
    """The sentences a retry's prompt adds for what the check found."""
    out: List[str] = []
    for i in issues:
        t = f"Show exactly this: {what.strip().rstrip('.')}." if i == "off_topic" else _FIXES.get(i)
        if t and t not in out:
            out.append(t)
    return " ".join(out)


def motion_prompt(motion: str, what: str) -> str:
    move = (motion or "A slow, steady push-in; only small natural movement in the scene").strip().rstrip(".")
    return (f"{move}. The scene: {what.strip().rstrip('.')}. Realistic documentary footage, natural light, steady "
            "camera, smooth natural motion at real speed. Nothing appears or disappears, nothing morphs, no text, "
            "no one walks into the frame.")


class Generator:
    def __init__(self, *, provider: Provider, budget: Budget, tier: Dict[str, Any], kit: dict, work: str,
                 store: Store, cache: Cache, checker: _checks.Checker, narration_wav: str, total: float,
                 bible: Dict[str, str], on_progress: Optional[Callable[[int, int], None]] = None):
        self.provider, self.budget, self.tier, self.kit = provider, budget, tier, kit
        self.work, self.store, self.cache, self.checker = work, store, cache, checker
        self.narration, self.total, self.bible = narration_wav, float(total), bible
        self.on_progress = on_progress
        self.dir = os.path.join(work, "presenter")
        os.makedirs(self.dir, exist_ok=True)
        self._lock = threading.Lock()
        self._done = 0
        self._total = 0
        self._sets_used: set = set()
        self._framing_cache: Dict[str, Tuple[str, str]] = {}
        self._master: Tuple[str, str] = ("", "")
        self.log: List[str] = []
        self.no_https_audio = False
        self.no_expressiveness = False
        self._issues: Dict[str, List[str]] = {}      # what a failed look check found, for the retry's prompt

    # ------------------------------------------------------------------ kit files
    def _framing(self, framing_id: str) -> Tuple[str, str]:
        """(local 16:9 JPEG, link the provider can fetch) for one of the kit's framings."""
        with self._lock:
            if framing_id in self._framing_cache:
                return self._framing_cache[framing_id]
        f = _kits.framing(self.kit, framing_id) or self.kit["framings"][0]
        src = _kits.fetch(self.kit, f["url"], os.path.join(self.work, "kit"))
        local = media_io.to_jpeg(src, os.path.join(self.work, "kit", f"framing_{f['id']}.jpg"),
                                 width=FRAME_W, height=FRAME_H, quality=94)
        # Always this exact 16:9 1920x1080 picture (the avatar's frame is the picture's): a temporary link.
        link = self.store.put(local, f"framing_{f['id']}.jpg", temp=True) or data_url_for(local)
        with self._lock:
            self._framing_cache[framing_id] = (local, link)
        return local, link

    def _master_files(self) -> Tuple[str, str]:
        with self._lock:
            if self._master[0]:
                return self._master
        src = _kits.fetch(self.kit, self.kit["master"], os.path.join(self.work, "kit"))
        local = media_io.to_jpeg(src, os.path.join(self.work, "kit", "master.jpg"), width=1536, quality=92)
        link = _kits.link(self.kit, self.kit["master"])
        if not link:
            link = self.store.put(local, "master.jpg", temp=True) or data_url_for(local)
        with self._lock:
            self._master = (local, link)
        return self._master

    # ------------------------------------------------------------------ progress
    def _tick(self) -> None:
        with self._lock:
            self._done += 1
            done, total = self._done, self._total
        if self.on_progress:
            try:
                self.on_progress(done, total)
            except Exception:  # noqa: BLE001 - progress never costs a shot
                pass

    def _note(self, msg: str) -> None:
        print(f"[presenter] {msg}", flush=True)
        with self._lock:
            self.log.append(msg[:300])

    # ------------------------------------------------------------------ one video call
    def _video_call(self, req: VideoRequest, projected: float, label: str, out_path: str,
                    cache_payload: Dict[str, Any], cache_files: List[str], kind: str) -> Dict[str, Any]:
        """Submit, poll, download one clip (or take it from the cache). Returns {"path", "usd", "cached", "url"}."""
        key = self.cache.key(cache_payload, cache_files)
        hit = self.cache.get(key, out_path)
        if hit:
            self._note(f"{label}: from the cache ({hit.get('cached')})")
            return {"path": out_path, "usd": 0.0, "cached": hit.get("cached", "disk"), "url": hit.get("url", "")}
        ticket = self.budget.reserve(projected, label)
        try:
            job = self.provider.submit_video(req)
        except ProviderError as e:
            self.budget.release(ticket, str(e))
            raise
        self._note(f"{label}: submitted {req.model} ({job.id[-8:]})")
        try:
            res = self.provider.wait_video(job, timeout=WAIT_SECONDS, poll=POLL_SECONDS)
        except ProviderError as e:
            # Still running or lost: what it may cost stays counted (projected), never released.
            self.budget.settle(ticket, None, model=req.model, kind=kind, job=job.id, error=str(e)[:120])
            raise
        if res.status != "completed":
            usd = self.budget.settle(ticket, res.cost or 0.0, model=req.model, kind=kind, job=job.id,
                                     error=res.error[:120] or res.status)
            self._record(kind, usd, 0.0)
            raise ProviderError(f"{req.model} {res.status}: {res.error[:200]}")
        usd = self.budget.settle(ticket, res.cost, model=req.model, kind=kind, job=job.id, seconds=res.seconds)
        self.provider.download_video(job, res, out_path)
        url = self.store.put(out_path, os.path.basename(out_path))
        self.cache.put(key, out_path, {"usd": usd, "model": req.model, "url": url, "job": job.id})
        self._note(f"{label}: done in {res.seconds:.0f} s, ${usd:.3f}")
        return {"path": out_path, "usd": usd, "cached": "", "url": url}

    @staticmethod
    def _record(kind: str, usd: float, seconds: float) -> None:
        cat, sub = ("presenter", "avatar") if kind == "presenter" else ("aivideo", "clip")
        if usd > 0:
            costs.record(f"{cat}.usd", usd)
            costs.record(f"{cat}.{sub}.usd", usd)
        costs.record(f"{cat}.{sub}.calls")
        if seconds > 0:
            costs.record(f"{cat}.seconds", seconds)

    # ------------------------------------------------------------------ presenter shots
    def presenter(self, shot: Shot) -> Optional[Asset]:
        tries: List[str] = [shot.framing or self.kit["framings"][0]["id"]]
        other = _kits.other_framing(self.kit, tries[0])
        tries.append(other["id"] if other else tries[0])
        why = []
        for attempt, framing_id in enumerate(tries):
            try:
                asset = self._presenter_once(shot, framing_id, attempt)
            except BudgetExceeded as e:
                why.append(f"budget: {e}")
                break
            except Exception as e:  # noqa: BLE001 - the next try, then the fallback
                why.append(f"{type(e).__name__}: {str(e)[:160]}")
                self._note(f"{shot.id}: presenter try {attempt + 1} failed: {why[-1]}")
                continue
            if asset is not None:
                asset.attempts = attempt + 1
                if why:
                    asset.checks["earlier"] = why
                return asset
            why.append("checks failed")
        self._note(f"{shot.id}: presenter shot falls back to a still ({'; '.join(why)[:200]})")
        still = self.still(shot, in_shot=False, reason="presenter shot failed")
        if still is not None:
            still.fallback = "presenter -> still: " + "; ".join(why)[:300]
        return still

    def _presenter_once(self, shot: Shot, framing_id: str, attempt: int) -> Optional[Asset]:
        model, res = (list(self.tier.get("presenter_model") or ["heygen/avatar-iv", "1080p"]) + ["1080p"])[:2]
        stem = f"{shot.id}_{framing_id}_{attempt}"
        win = media_io.cut_window(self.narration, shot.start, shot.end, os.path.join(self.dir, f"{stem}.wav"),
                                  pad_before=PAD_BEFORE, pad_after=PAD_AFTER, total=self.total)
        frame_local, frame_link = self._framing(framing_id)
        audio_url = self.store.put(win["path"], f"{stem}.wav", temp=True, content_type="audio/wav")
        avatar = self.kit.get("avatar") or {}
        opts = {"motion_prompt": avatar.get("motion_prompt") or _kits.DEFAULT_MOTION_PROMPT}
        if avatar.get("expressiveness") and not self.no_expressiveness:
            opts["expressiveness"] = avatar["expressiveness"]
        req = VideoRequest(model=model, prompt=avatar.get("prompt") or "", resolution=res, aspect_ratio="16:9",
                           images=[frame_link], audio_url=audio_url, options={"heygen": opts})
        payload = {"kind": "presenter", "model": model, "res": res, "prompt": req.prompt, "opts": opts}
        if not audio_url:
            # OpenRouter takes audio by https link only: without R2 nothing can be sent (a cached clip still can).
            key = self.cache.key(payload, [frame_local, win["path"]])
            if not self.cache.get(key, os.path.join(self.dir, f"{stem}_raw.mp4")):
                self.no_https_audio = True
                raise ProviderError("no https link for the voice window (R2 is not configured)")
        projected = round(win["seconds"] * tiers.usd_per_second(model, res) * 1.05 + 0.01, 4)
        raw = os.path.join(self.dir, f"{stem}_raw.mp4")
        try:
            got = self._video_call(req, projected, f"{shot.id} presenter ({framing_id})", raw, payload,
                                   [frame_local, win["path"]], "presenter")
        except ProviderError as e:
            if "expressiveness" in opts and e.status == 400:
                # A passthrough the provider would not take (untested value): every later call goes without it.
                self.no_expressiveness = True
            raise
        if not got["cached"]:
            self._record("presenter", got["usd"], win["seconds"])
        info = media_io.probe(raw)
        lag = media_io.audio_lag(raw, win["path"]) if info["audio"] else None
        offset = win["lead"] + (lag if lag is not None and abs(lag) <= 0.5 else 0.0)
        scene = shot.seconds
        keep = scene + max(0.0, min(CLIP_HANDLE, info["duration"] - offset - scene))
        if info["duration"] - offset < scene - 0.08:
            raise media_io.MediaError(f"clip {info['duration']:.2f} s too short for its {scene:.2f} s scene")
        clip = media_io.trim(raw, os.path.join(self.dir, f"{stem}.mp4"), offset, keep, mute=True)
        problems = _checks.clip_problems(clip, scene)
        if problems:
            self._note(f"{shot.id}: presenter clip rejected: {', '.join(problems)}")
            return None
        master_local, _ = self._master_files()
        verdict = self.checker.presenter(clip, master_local, stem)
        if not verdict.get("ok"):
            self._note(f"{shot.id}: presenter face check failed: {verdict}")
            return None
        costs.record("presenter.screen_seconds", scene)
        out = media_io.probe(clip)
        return Asset(shot_id=shot.id, kind="video", path=clip, source="ai-presenter", model=model, usd=got["usd"],
                     url=got["url"], width=int(out["width"]), height=int(out["height"]), seconds=out["duration"],
                     prompt=req.prompt, framing=framing_id, lag=lag, checks={"face": verdict, "window": win},
                     cached=got["cached"])

    # ------------------------------------------------------------------ stills
    def still(self, shot: Shot, in_shot: bool, reason: str = "", tag: str = "",
              allow_set: bool = True, no_people: bool = False) -> Optional[Asset]:
        """The line's still: the tier's picture models in turn (one retry), else the kit's set (allow_set)."""
        models = tiers.pairs(self.tier, "presenter_image_models" if in_shot else "image_models")
        if in_shot and not models:
            models = tiers.pairs(self.tier, "image_models")
        what = shot.still or shot.text
        prompt = still_prompt(what, self.bible, self.kit, in_shot, no_people=no_people)
        why = []
        issues: List[str] = []
        for attempt, (model, size) in enumerate(models[:2]):
            try:
                # A retry after a failed look check asks for exactly what the check found wrong.
                asked = f"{prompt} {fix_text(issues, what)}".strip() if issues else prompt
                asset = self._still_once(shot, model, size, asked, in_shot, attempt, tag=tag)
                issues = self._issues.pop(f"{shot.id}{tag}", []) if asset is None else []
            except BudgetExceeded as e:
                why.append(f"budget: {e}")
                break
            except Exception as e:  # noqa: BLE001 - the next model, then the fallback
                why.append(f"{type(e).__name__}: {str(e)[:160]}")
                self._note(f"{shot.id}: still try {attempt + 1} ({model}) failed: {why[-1]}")
                continue
            if asset is not None:
                asset.attempts = attempt + 1
                if why:
                    asset.checks["earlier"] = why
                return asset
            why.append(f"{model}: checks failed")
        if not allow_set:
            return None
        return self._set_fallback(shot, f"{reason + ': ' if reason else ''}" + "; ".join(why))

    def _still_once(self, shot: Shot, model: str, size: str, prompt: str, in_shot: bool,
                    attempt: int, tag: str = "") -> Optional[Asset]:
        stem = f"{shot.id}{tag}_still_{attempt}"
        refs, ref_files = [], []
        if in_shot:
            master_local, master_link = self._master_files()
            refs, ref_files = [master_link], [master_local]
        payload = {"kind": "still", "model": model, "size": size, "prompt": prompt}
        key = self.cache.key(payload, ref_files)
        raw = os.path.join(self.dir, f"{stem}_raw.img")
        hit = self.cache.get(key, raw)
        usd, url, cached = 0.0, "", ""
        if hit:
            usd, url, cached = 0.0, hit.get("url", ""), hit.get("cached", "disk")
        else:
            ticket = self.budget.reserve(round(tiers.image_usd(model, size) * 1.25, 4), f"{shot.id} still")
            try:
                res = self.provider.image(ImageRequest(model=model, prompt=prompt, size=size, aspect_ratio="16:9",
                                                       references=refs))
            except ProviderError as e:
                if e.billed:
                    self.budget.settle(ticket, None, model=model, kind="image", error=str(e)[:120])
                else:
                    self.budget.release(ticket, str(e))
                raise
            usd = self.budget.settle(ticket, res.cost, model=model, kind="image", seconds=res.seconds)
            costs.record("image.usd", usd)
            kind = "presenter_broll" if in_shot else "broll"
            costs.record(f"image.{kind}.usd", usd)
            costs.record(f"image.{kind}.calls")
            with open(raw, "wb") as fh:
                fh.write(res.data)
        path = media_io.to_jpeg(raw, os.path.join(self.dir, f"{stem}.jpg"), width=FRAME_W, height=FRAME_H,
                                quality=93)
        if not hit:
            url = self.store.put(path, f"{shot.id}{tag}.jpg")
            self.cache.put(key, raw, {"usd": usd, "model": model, "url": url})
        problems = _checks.still_problems(path)
        if problems:
            self._note(f"{shot.id}: still rejected: {', '.join(problems)}")
            return None
        verdict = self.checker.broll(path, shot.still or shot.text, f"{stem}", video=False)
        if not verdict.get("ok"):
            self._note(f"{shot.id}: still check failed: {verdict.get('issues')} real={verdict.get('real')} "
                       f"match={verdict.get('match')}")
            with self._lock:
                self._issues[f"{shot.id}{tag}"] = _found(verdict)
            return None
        return Asset(shot_id=shot.id, kind="image", path=path, source="ai-image", model=model, usd=usd, url=url,
                     width=FRAME_W, height=FRAME_H, prompt=prompt, checks={"look": verdict}, cached=cached)

    def _set_fallback(self, shot: Shot, why: str) -> Optional[Asset]:
        """The kit's empty set (each set at most once a video - never a repeated picture), else nothing."""
        with self._lock:
            free = [s for s in self.kit.get("sets") or [] if s["id"] not in self._sets_used]
            pick = free[0] if free else None
            if pick:
                self._sets_used.add(pick["id"])
        if not pick:
            self._note(f"{shot.id}: no picture and no unused set picture ({why[:160]})")
            return None
        try:
            src = _kits.fetch(self.kit, pick["url"], os.path.join(self.work, "kit"))
            path = media_io.to_jpeg(src, os.path.join(self.dir, f"{shot.id}_set_{pick['id']}.jpg"),
                                    width=FRAME_W, height=FRAME_H, quality=93)
        except Exception as e:  # noqa: BLE001
            self._note(f"{shot.id}: set picture unavailable: {type(e).__name__}")
            return None
        return Asset(shot_id=shot.id, kind="image", path=path, source="kit-set", width=FRAME_W, height=FRAME_H,
                     fallback=f"still -> kit set '{pick['id']}': {why[:300]}")

    # ------------------------------------------------------------------ AI video
    def ai_video(self, shot: Shot) -> Optional[Asset]:
        start = self.still(shot, in_shot=shot.in_shot)
        if start is None:
            return None
        if start.source == "kit-set":
            return start
        why = []
        issues: List[str] = []
        for attempt, (model, res) in enumerate(tiers.pairs(self.tier, "video_models")[:2]):
            try:
                asset = self._video_once(shot, start, model, res, attempt,
                                         extra=fix_text(issues, shot.still or shot.text))
                issues = self._issues.pop(f"{shot.id}:clip", []) if asset is None else []
            except BudgetExceeded as e:
                why.append(f"budget: {e}")
                break
            except Exception as e:  # noqa: BLE001 - the next model, then the still
                why.append(f"{type(e).__name__}: {str(e)[:160]}")
                self._note(f"{shot.id}: clip try {attempt + 1} ({model}) failed: {why[-1]}")
                continue
            if asset is not None:
                asset.attempts = attempt + 1
                if why:
                    asset.checks["earlier"] = why
                return asset
            why.append(f"{model}: checks failed")
        start.fallback = "AI video -> its still (camera move + living photo): " + "; ".join(why)[:300]
        self._note(f"{shot.id}: clip falls back to its still")
        return start

    def _video_once(self, shot: Shot, start: Asset, model: str, res: str, attempt: int,
                    extra: str = "") -> Optional[Asset]:
        stem = f"{shot.id}_clip_{attempt}"
        info = tiers.model_info(model)
        seconds = tiers.clip_seconds_for(model, shot.seconds + CLIP_HANDLE)
        link = start.url if start.url.startswith("https://") else ""
        if not link:
            link = self.store.put(start.path, f"{shot.id}_start.jpg", temp=True) or data_url_for(start.path)
        prompt = f"{motion_prompt(shot.motion, shot.still or shot.text)} {extra}".strip()
        seed = zlib.crc32(f"{shot.id}:{attempt}".encode("utf-8")) % 2_000_000_000
        req = VideoRequest(model=model, prompt=prompt, resolution=res, aspect_ratio="16:9", duration=seconds,
                           first_frame=link, generate_audio=False if info.get("audio_flag") else None, seed=seed)
        payload = {"kind": "clip", "model": model, "res": res, "seconds": seconds, "prompt": prompt, "seed": seed}
        projected = round(seconds * tiers.usd_per_second(model, res) * 1.05 + 0.02, 4)
        raw = os.path.join(self.dir, f"{stem}_raw.mp4")
        got = self._video_call(req, projected, f"{shot.id} clip ({model})", raw, payload, [start.path], "aivideo")
        if not got["cached"]:
            self._record("aivideo", got["usd"], float(seconds))
        dur = media_io.duration(raw)
        keep = min(dur, shot.seconds + CLIP_HANDLE)
        clip = media_io.trim(raw, os.path.join(self.dir, f"{stem}.mp4"), 0.0, keep, mute=True)
        problems = _checks.clip_problems(clip, min(shot.seconds, dur))
        if dur + 0.05 < shot.seconds * 0.85:
            problems.append(f"clip {dur:.1f} s for a {shot.seconds:.1f} s scene")
        if problems:
            self._note(f"{shot.id}: clip rejected: {', '.join(problems)}")
            return None
        verdict = self.checker.broll(clip, shot.still or shot.text, stem, video=True)
        if not verdict.get("ok"):
            self._note(f"{shot.id}: clip check failed: {verdict.get('issues')} real={verdict.get('real')} "
                       f"match={verdict.get('match')}")
            with self._lock:
                self._issues[f"{shot.id}:clip"] = _found(verdict)
            return None
        costs.record("aivideo.screen_seconds", min(shot.seconds, keep))
        out = media_io.probe(clip)
        return Asset(shot_id=shot.id, kind="video", path=clip, source="ai-video", model=model, usd=got["usd"],
                     url=got["url"], width=int(out["width"]), height=int(out["height"]), seconds=out["duration"],
                     prompt=prompt, checks={"look": verdict, "still": start.report()}, cached=got["cached"])

    # ------------------------------------------------------------------ the whole set
    def run(self, shots: List[Shot]) -> Dict[str, Optional[Asset]]:
        """Every shot's asset (None: nothing could be made - the assembly holds a neighbour over it)."""
        self._total = len(shots) + sum(1 for s in shots if s.kind == "presenter" and s.split)
        out: Dict[str, Optional[Asset]] = {}
        futures: Dict[str, Future] = {}

        def guarded(fn, shot):
            def go():
                try:
                    return fn(shot)
                except Exception:  # noqa: BLE001 - one shot never takes the video down
                    self._note(f"{shot.id}: {traceback.format_exc(limit=3)[-400:]}")
                    return None
                finally:
                    self._tick()
            return go

        with ThreadPoolExecutor(max_workers=max(1, PRESENTER_PARALLEL)) as pres, \
                ThreadPoolExecutor(max_workers=max(1, IMAGE_PARALLEL)) as imgs, \
                ThreadPoolExecutor(max_workers=max(1, VIDEO_PARALLEL)) as vids:
            for s in shots:
                if s.kind == "presenter":
                    futures[s.id] = pres.submit(guarded(self.presenter, s))
                    if s.split:
                        # The split screen's right half: the line's own picture (never the kit's set).
                        futures[f"{s.id}{SPLIT}"] = imgs.submit(guarded(
                            lambda sh: self.still(sh, in_shot=False, tag="_split", allow_set=False, no_people=True), s))
            for s in shots:
                if s.kind == "ai_video":
                    futures[s.id] = vids.submit(guarded(self.ai_video, s))
                elif s.kind == "picture":
                    futures[s.id] = imgs.submit(guarded(lambda sh: self.still(sh, in_shot=sh.in_shot), s))
            for sid, f in futures.items():
                out[sid] = f.result()
        return out
