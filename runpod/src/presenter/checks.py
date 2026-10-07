"""
The checks every generated presenter shot, AI clip and still passes before it
goes on the timeline (one retry, then the fallback - src/presenter/generate.py):

  every clip    readable, long enough for its scene, not frozen, not black (ffmpeg);
  presenter     the face matches the kit's master portrait and stays natural:
                a vision model compares the master with the clip's first,
                middle and last frames (no face-embedding model ships with
                the worker: OpenCV's YuNet + SFace would need opencv and two
                model files in the image - see face_embedding_available);
  AI clip/still a vision model looks for what gives AI pictures away -
                melted hands, extra fingers, warped faces, garbled text,
                morphing objects, watermarks - and for whether it shows what
                the line needs.

A check that cannot run (no key, the budget spent, the model down) passes the
asset as "unchecked": a check never costs the video its shot. Vision calls
are cheap (google/gemini-2.5-flash: ~$0.0003-0.001 each) and counted as
vision.presenter_check in the ledger.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Sequence

from .. import costs
from . import media_io, tiers
from .budget import Budget, BudgetExceeded
from .providers import Provider, ProviderError, data_url_for

CHECK_USD = 0.004            # the most one check call may cost

SEVERE_PRESENTER = {"different_person", "warped_face", "extra_person", "melted_face"}
SEVERE_BROLL = {"melted_hands", "extra_fingers", "warped_face", "garbled_text", "morphing", "watermark",
                "extra_limbs", "duplicated_person", "collage"}

PRESENTER_PROMPT = """Picture 1 is the reference photo of a TV presenter. Pictures 2 to {n} are frames (start, middle, \
end) of a generated video of that presenter talking to camera. Check like a picture editor before broadcast:
- same_person: 0-1, is it clearly the same person as picture 1 (face shape, age, hair, beard, eyes, clothes)?
- natural: 0-1, does the face look like real camera footage (no warping, melting, doubled or smeared features, \
no odd teeth or eyes)?
- issues: a list from different_person, warped_face, melted_face, bad_mouth, bad_eyes, extra_person, artefacts, \
frozen, other (empty when there is nothing wrong).
Reply with JSON only: {{"same_person": 0.0, "natural": 0.0, "issues": []}}"""

BROLL_PROMPT = """{what_kind} for a documentary video. It should show: {what}
Check it like a picture editor before broadcast:
- real: 0-1, does it look like real camera footage or a real photograph (not a render, cartoon or painting)?
- match: 0-1, does it show what it should?
- issues: a list from melted_hands, extra_fingers, extra_limbs, warped_face, duplicated_person, garbled_text \
(letters that try to read as words but are nonsense - small, blurred or unreadable print is fine), morphing \
(objects melting into each other between frames), impossible_physics, cartoonish, watermark, collage, frozen, other \
(empty when there is nothing wrong).
Reply with JSON only: {{"real": 0.0, "match": 0.0, "issues": []}}"""


def face_embedding_available() -> bool:
    """OpenCV's YuNet + SFace face check: needs cv2 with FaceDetectorYN and the two model files (PRESENTER_FACE_MODELS)."""
    try:
        import cv2  # noqa: F401
    except ImportError:
        return False
    folder = os.getenv("PRESENTER_FACE_MODELS", "/opt/models/face")
    return all(os.path.isfile(os.path.join(folder, f)) for f in
               ("face_detection_yunet_2023mar.onnx", "face_recognition_sface_2021dec.onnx"))


def clip_problems(path: str, need_seconds: float) -> List[str]:
    """What is wrong with a clip as a file: unreadable, shorter than its scene, frozen, black ([] = fine)."""
    info = media_io.probe(path)
    if not info["video"] or info["duration"] <= 0.05:
        return ["unreadable"]
    out = []
    if info["duration"] + 0.06 < need_seconds:
        out.append(f"short: {info['duration']:.2f} s for a {need_seconds:.2f} s scene")
    try:
        fb = media_io.freeze_black(path)
    except media_io.MediaError:
        return out
    if fb["black"] >= 0.5:
        out.append(f"black for {fb['black']:.1f} s")
    if fb["frozen"] >= max(1.2, 0.45 * info["duration"]):
        out.append(f"frozen for {fb['frozen']:.1f} s")
    return out


def still_problems(path: str, min_width: int = 900) -> List[str]:
    try:
        w, h = media_io.still_size(path)
    except media_io.MediaError as e:
        return [str(e)]
    out = []
    if w < min_width:
        out.append(f"small: {w}x{h}")
    if h and not 1.6 <= w / h <= 1.95:
        out.append(f"not 16:9: {w}x{h}")
    return out


def _parse(text: str) -> Optional[dict]:
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    try:
        got = json.loads(t)
    except ValueError:
        m = re.search(r"\{.*\}", t, re.S)
        try:
            got = json.loads(m.group(0)) if m else None
        except ValueError:
            got = None
    return got if isinstance(got, dict) else None


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return default


class Checker:
    def __init__(self, provider: Optional[Provider], budget: Budget, work: str,
                 models: Optional[Sequence[str]] = None):
        self.provider, self.budget, self.work = provider, budget, work
        self.models = list(models or [tiers.CHECK_MODEL] + tiers.CHECK_FALLBACK_MODELS)
        self.calls = 0
        self.unchecked = 0

    def _ask(self, prompt: str, images: List[str], label: str) -> Optional[dict]:
        if self.provider is None or not self.provider.available():
            return None
        content: List[dict] = [{"type": "text", "text": prompt}]
        for p in images:
            content.append({"type": "image_url", "image_url": {"url": data_url_for(p)}})
        for model in self.models:
            try:
                ticket = self.budget.reserve(CHECK_USD, f"check:{label}")
            except BudgetExceeded:
                return None
            try:
                res = self.provider.chat(model, [{"role": "user", "content": content}], json_mode=True,
                                         max_tokens=400, timeout=90)
            except ProviderError as e:
                self.budget.release(ticket, str(e))
                print(f"[presenter] check {label} on {model} failed: {str(e)[:120]}", flush=True)
                continue
            usd = self.budget.settle(ticket, res.cost, model=model, kind="check", label=label)
            self.calls += 1
            costs.record("vision.usd", usd)
            costs.record("vision.presenter_check.usd", usd)
            costs.record("vision.presenter_check.calls")
            got = _parse(res.text)
            if got is not None:
                got["_model"] = model
                return got
        return None

    def _small(self, path: str, stem: str, width: int = 640) -> str:
        out = os.path.join(self.work, "checks", f"{stem}.jpg")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        return media_io.to_jpeg(path, out, width=width, quality=85)

    def presenter(self, clip: str, master: str, stem: str) -> Dict[str, Any]:
        """The presenter shot against the kit's master portrait: same person, natural face."""
        dur = media_io.duration(clip)
        frames = media_io.frames(clip, [0.15, dur / 2, max(0.0, dur - 0.2)], os.path.join(self.work, "checks"), stem)
        if not frames:
            return {"ok": False, "issues": ["no frames"], "checked": True}
        got = self._ask(PRESENTER_PROMPT.format(n=len(frames) + 1), [self._small(master, f"{stem}_ref", 512)] + frames,
                        stem)
        if got is None:
            self.unchecked += 1
            return {"ok": True, "checked": False}
        issues = sorted({str(i).strip().lower() for i in got.get("issues") or [] if str(i).strip()})
        same, natural = _f(got.get("same_person"), 0.5), _f(got.get("natural"), 0.5)
        ok = same >= 0.6 and natural >= 0.5 and not (set(issues) & SEVERE_PRESENTER)
        return {"ok": ok, "checked": True, "samePerson": same, "natural": natural, "issues": issues,
                "model": got.get("_model")}

    def broll(self, path: str, what: str, stem: str, video: bool) -> Dict[str, Any]:
        """An AI clip (3 frames) or a still: real-looking, on the line, nothing that gives AI away."""
        if video:
            dur = media_io.duration(path)
            images = media_io.frames(path, [0.1, dur / 2, max(0.0, dur - 0.15)], os.path.join(self.work, "checks"),
                                     stem)
            kind = "These are frames (start, middle, end) of an AI-generated b-roll clip"
        else:
            images = [self._small(path, stem, 768)]
            kind = "This is an AI-generated b-roll photograph"
        if not images:
            return {"ok": False, "issues": ["no frames"], "checked": True}
        got = self._ask(BROLL_PROMPT.format(what_kind=kind, what=(what or "")[:400]), images, stem)
        if got is None:
            self.unchecked += 1
            return {"ok": True, "checked": False}
        issues = sorted({str(i).strip().lower() for i in got.get("issues") or [] if str(i).strip()})
        real, match = _f(got.get("real"), 0.5), _f(got.get("match"), 0.5)
        if not video:
            issues = [i for i in issues if i != "frozen"]
        ok = real >= 0.45 and match >= 0.35 and not (set(issues) & SEVERE_BROLL)
        return {"ok": ok, "checked": True, "real": real, "match": match, "issues": issues, "model": got.get("_model")}
