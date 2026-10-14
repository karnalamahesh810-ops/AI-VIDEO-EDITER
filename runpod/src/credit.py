"""
What is left on the OpenRouter account the director and vision calls are billed to, read from its free endpoints
(no model call) and cached, so a job can stop before it runs an account dry (reclip.Stopper's floor, aiguard.preflight)
and a vision call hedges only on a healthy account (vision._hedge_seconds).
2026-10-07: the California re-clip took OpenRouter from $4.87 to $2.73, under the owner's $3 floor, before
anyone could stop it.

Two numbers, the lower one counts (2026-10-09): the account's credits (GET /api/v1/credits: total_credits -
total_usage) and the key's own spending limit (GET /api/v1/key: limit_remaining, when the key has a limit). Read on
2026-10-09 the account had $19.02 and the worker's key $9.02 under its $100 limit: a key at its limit is refused
(402) while the account still has money, so the account alone overstated what a job could spend.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

import requests

from . import config

CACHE_SECONDS = 120.0
_LOCK = threading.Lock()
_LAST = {"at": 0.0, "left": None, "key": "", "detail": {}}


def _openrouter_key() -> str:
    for base, key in ((config.VISION_API_BASE, config.VISION_API_KEY), (config.DIRECTOR_API_BASE, config.DIRECTOR_API_KEY)):
        if key and "openrouter.ai" in (base or ""):
            return key
    return ""


def uses_openrouter() -> bool:
    return bool(_openrouter_key())


def _get(path: str, key: str) -> Optional[dict]:
    """One free OpenRouter read: its "data" object, or None (refused, not answering, not JSON)."""
    try:
        r = requests.get(f"https://openrouter.ai/api/v1/{path}", headers={"Authorization": f"Bearer {key}"},
                         timeout=15)
        if getattr(r, "status_code", 200) >= 400:
            return None
        data = (r.json() or {}).get("data")
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001 - unknown, never a reason to fail a job
        return None


def _account_left(data: Optional[dict]) -> Optional[float]:
    if not data or "total_credits" not in data:
        return None                 # refused or not a balance (a bad key, a rate limit): unknown, never $0
    try:
        return float(data.get("total_credits") or 0.0) - float(data.get("total_usage") or 0.0)
    except (TypeError, ValueError):
        return None


def _key_left(data: Optional[dict]) -> Optional[float]:
    """The key's own limit left (limit_remaining), or None when the key has no limit or it cannot be read."""
    if not data or data.get("limit") in (None, "") or data.get("limit_remaining") in (None, ""):
        return None
    try:
        return float(data.get("limit_remaining"))
    except (TypeError, ValueError):
        return None


def openrouter_left(max_age: float = CACHE_SECONDS) -> Optional[float]:
    """USD this key may still spend on OpenRouter - the account's credits left or the key's own limit left,
    whichever is lower - or None when neither can be read."""
    key = _openrouter_key()
    if not key:
        return None
    with _LOCK:
        if _LAST["key"] == key and _LAST["left"] is not None and time.time() - _LAST["at"] < max_age:
            return _LAST["left"]
    account = _account_left(_get("credits", key))
    key_limit = _key_left(_get("key", key))
    known = [v for v in (account, key_limit) if v is not None]
    if not known:
        return None
    left = min(known)
    with _LOCK:
        _LAST.update(at=time.time(), left=left, key=key, detail={"account": account, "key": key_limit})
    return left


def last_detail() -> dict:
    """The two numbers behind the last openrouter_left ({"account": $, "key": $ or None})."""
    with _LOCK:
        return dict(_LAST.get("detail") or {})


def reset() -> None:
    with _LOCK:
        _LAST.update(at=0.0, left=None, key="", detail={})
