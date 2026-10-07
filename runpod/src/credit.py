"""
What is left on the OpenRouter account the director and vision calls are billed to, read from its free
/credits endpoint (no model call) and cached, so a job can stop before it runs an account dry
(reclip.Stopper's floor) and a vision call hedges only on a healthy account (vision._hedge_seconds).
2026-10-07: the California re-clip took OpenRouter from $4.87 to $2.73, under the owner's $3 floor, before
anyone could stop it.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

import requests

from . import config

CACHE_SECONDS = 120.0
_LOCK = threading.Lock()
_LAST = {"at": 0.0, "left": None, "key": ""}


def _openrouter_key() -> str:
    for base, key in ((config.VISION_API_BASE, config.VISION_API_KEY), (config.DIRECTOR_API_BASE, config.DIRECTOR_API_KEY)):
        if key and "openrouter.ai" in (base or ""):
            return key
    return ""


def uses_openrouter() -> bool:
    return bool(_openrouter_key())


def openrouter_left(max_age: float = CACHE_SECONDS) -> Optional[float]:
    """USD left on the OpenRouter account (credits bought minus used), or None when it cannot be read."""
    key = _openrouter_key()
    if not key:
        return None
    with _LOCK:
        if _LAST["key"] == key and _LAST["left"] is not None and time.time() - _LAST["at"] < max_age:
            return _LAST["left"]
    try:
        r = requests.get("https://openrouter.ai/api/v1/credits", headers={"Authorization": f"Bearer {key}"},
                         timeout=15)
        data = (r.json() or {}).get("data") or {}
        left = float(data.get("total_credits") or 0.0) - float(data.get("total_usage") or 0.0)
    except Exception:  # noqa: BLE001 - unknown, never a reason to fail a job
        return None
    with _LOCK:
        _LAST.update(at=time.time(), left=left, key=key)
    return left


def reset() -> None:
    with _LOCK:
        _LAST.update(at=0.0, left=None, key="")
