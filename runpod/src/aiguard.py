"""
The AI outage guard (the owner, 2026-10-09): a video is planned and checked by AI, or it is not made.

What it stops. The Yellowstone build of 2026-10-07 (2a2200b3) ran the OpenRouter account dry at 08:29 and kept
going for 40 minutes: 4,158 refused calls ("would exceed your available credits", Kie's "Credits insufficient",
"requires more credits", "Prompt tokens limit exceeded", "call frequency is too high"), lines s0144-s0259 planned by
the rules from the video's TITLE, and clips placed with no verdict - "JJ is LEFT FOREVER in Minecraft! (Maizen)" on a
line about ground uplift. The next build (fd58f969, 2026-10-08) took one 402 at 17:35:35, 22 s into its footage
search, and went on for 40 minutes: 176 of its 181 clips and all 86 pictures reached the timeline unjudged (a Roblox
"Magma Full Showcase", the Yellowstone TV show's theme, a FIFA highlights reel, product tutorials).

Kinds of AI failure (classify):

  credit  the account or the key cannot pay - HTTP 402, "insufficient credits", "requires more credits", "exceed
          your available credits", "key limit", "Prompt tokens limit exceeded": every later call fails the same way.
          The job stops at once (trip): no footage search starts after it, nothing unjudged is placed, the work
          already done is kept for a Retry (src/resume.py) and the job fails with a plain top-up message.
  auth    HTTP 401: the key itself was refused - the same stop, its own message.
  rate    429 / "rate limit" / "call frequency is too high": backed off and asked again (vision._route_call,
          director._chat_route) - never a reason to stop.
  retry   5xx, 408/409/425, a timeout or a dropped connection: asked again.
  other   anything else (a 400, an unusable answer): the next model is asked.

And one more stop, for the outage no single answer names: every call failing for AI_OUTAGE_SECONDS with at least
AI_OUTAGE_MIN_FAILS failures in a row and no answer since (outage) - quality is never traded for a finished video.

The preflight (preflight, estimate_usd) runs before any paid work: the balance OpenRouter will let this key spend
(credit.openrouter_left: the account's credits and the key's own limit, the lower) against what the video needs.

REQUIRE_AI (default on since 2026-10-09) turns the stops on; REQUIRE_AI=0 is the old behaviour (keep going).
Nothing here raises except raise_if_stopped / preflight, and only with AIStopped (a RuntimeError).
"""
from __future__ import annotations

import re
import threading
import time
from typing import Optional

from . import config, events

CREDIT, AUTH, RATE, RETRY, OTHER, OUTAGE = "credit", "auth", "rate", "retry", "other", "outage"

# What the providers say when the account or the key cannot pay (measured on the Yellowstone and California builds,
# 2026-10-06/07, and OpenRouter's own wording): every one of them fails every later call the same way.
_CREDIT_SIGNS = re.compile(
    r"insufficient (?:credits?|balance|funds)|credits? (?:insufficient|exhausted|ran out|depleted)|"
    r"not enough credits?|requires more credits|exceed (?:your )?available credits|out of credits?|"
    r"no credits? (?:left|remaining)|credit limit|key limit|(?:spend|spending) limit|"
    r"prompt tokens limit exceeded|top ?up|balance (?:isn.t|is not) enough|balance (?:is )?too low|"
    r"payment required|exceeded your current quota|add more (?:credits )?using", re.I)
# A rate limit: back off and ask again (Kie's "Your call frequency is too high. Please try again later.").
_RATE_SIGNS = re.compile(
    r"rate[- ]?limit|too many requests|call frequency is too high|requests? per (?:minute|second|day)|"
    r"slow down|retry after|resource[_ ]exhausted", re.I)


class AIStopped(RuntimeError):
    """The job stops for the AI account (credit, key or outage): its message is the one the app shows."""


def classify(status: Optional[int] = None, message: str = "") -> str:
    """credit / auth / rate / retry / other for one failed AI call: its HTTP (or provider) status and message."""
    try:
        code = int(status or 0)
    except (TypeError, ValueError):
        code = 0
    msg = str(message or "")
    if code == 402:
        return CREDIT
    rate_words = bool(_RATE_SIGNS.search(msg))
    if _CREDIT_SIGNS.search(msg) and not (code == 429 and rate_words):
        return CREDIT
    if code == 401:
        return AUTH
    if code == 429 or rate_words:
        return RATE
    if code in (408, 409, 425) or code >= 500:
        return RETRY
    return OTHER


def is_fatal(kind: str) -> bool:
    return kind in (CREDIT, AUTH)


# --------------------------------------------------------------------------- #
# The job's state
# --------------------------------------------------------------------------- #

_LOCK = threading.Lock()
_STATE = {"kind": "", "provider": "", "detail": "", "at": 0.0, "kept": False}
_RUN = {"started": 0.0, "last_ok": 0.0, "streak": 0, "last_error": "", "auth": 0}


def reset() -> None:
    """A new job: nothing tripped, the outage clock starts now."""
    now = time.time()
    with _LOCK:
        _STATE.update(kind="", provider="", detail="", at=0.0, kept=False)
        _RUN.update(started=now, last_ok=0.0, streak=0, last_error="", auth=0)


def enabled() -> bool:
    """The stops are on (REQUIRE_AI)."""
    return bool(getattr(config, "REQUIRE_AI", True))


def tripped() -> str:
    """Why the job's AI stopped ("credit", "auth", "outage"), or ""."""
    with _LOCK:
        return _STATE["kind"]


# Whether a backup provider (another account: AI_FALLBACK_*) can still answer - set by src/vision.py. A main
# account out of credit stops the job only while there is none: the backup carries the job on, as it always did.
_BACKUP = {"check": None}


def set_backup_check(fn) -> None:
    _BACKUP["check"] = fn


def _backup_answers() -> bool:
    fn = _BACKUP["check"]
    try:
        return bool(fn()) if fn else False
    except Exception:  # noqa: BLE001
        return False


def stopping() -> bool:
    """The job must stop spending: the AI account or the AI itself is gone and REQUIRE_AI is on (a main account out
    of credit with a backup provider still answering is not a stop)."""
    kind = tripped()
    if not enabled() or not kind:
        return False
    return not (kind == CREDIT and _backup_answers())


def state() -> dict:
    with _LOCK:
        return {**_STATE, "streak": _RUN["streak"], "lastError": _RUN["last_error"]}


def trip(kind: str, provider: str = "", detail: str = "") -> bool:
    """Record the job's stop (the first one wins). Returns True when this call tripped it."""
    if kind not in (CREDIT, AUTH, OUTAGE):
        return False
    with _LOCK:
        if _STATE["kind"]:
            return False
        _STATE.update(kind=kind, provider=str(provider or "")[:80], detail=" ".join(str(detail or "").split())[:200],
                      at=time.time())
    enforced = stopping()
    print(f"[ai] {'STOP' if enforced else 'main account out'} ({kind}) from {provider or 'the AI'}: "
          f"{str(detail or '')[:160]}", flush=True)
    try:
        events.emit("ai", "stopped" if enforced else "main_out", level="error" if enforced else "warning",
                    provider=str(provider or "")[:60],
                    failure="AI_CREDIT" if kind == CREDIT else ("AI_AUTH" if kind == AUTH else "AI_OUTAGE"),
                    message=str(detail or "")[:200], data={"kind": kind, "enforced": enforced})
    except Exception:  # noqa: BLE001 - the stop never fails on its own report
        pass
    return True


def note_failure(kind: str, provider: str = "", detail: str = "") -> None:
    """One AI call failed after its retries. A credit or key failure trips the stop at once; any other one counts
    toward the outage stop (AI_OUTAGE_SECONDS with no answer and AI_OUTAGE_MIN_FAILS failures in a row)."""
    if is_fatal(kind):
        trip(kind, provider, detail)
        return
    now = time.time()
    with _LOCK:
        _RUN["streak"] += 1
        _RUN["last_error"] = f"{provider}: {detail}"[:160]
        streak = _RUN["streak"]
        quiet_since = max(_RUN["last_ok"], _RUN["started"] or now)
    window = float(getattr(config, "AI_OUTAGE_SECONDS", 600.0) or 0.0)
    need = int(getattr(config, "AI_OUTAGE_MIN_FAILS", 40) or 0)
    if window > 0 and need > 0 and streak >= need and now - quiet_since >= window:
        trip(OUTAGE, provider, f"no AI answer for {int(now - quiet_since)} s ({streak} failed calls in a row; "
                               f"last: {detail})")


def note_ok() -> None:
    """One AI call answered: the outage clock starts again."""
    with _LOCK:
        _RUN["streak"] = 0
        _RUN["auth"] = 0
        _RUN["last_ok"] = time.time()


def note_auth(provider: str = "", detail: str = "") -> None:
    """One request refused for its key (401). One is a model's problem (the next is asked); AI_AUTH_STOP_AFTER in a
    row with no answer between them is the key itself - the job stops (auth)."""
    with _LOCK:
        _RUN["auth"] += 1
        n = _RUN["auth"]
    if n >= max(1, int(getattr(config, "AI_AUTH_STOP_AFTER", 3) or 3)):
        trip(AUTH, provider, detail)


def mark_kept(kept: bool = True) -> None:
    """The work done before the stop was saved for a Retry (src/resume.py): the message says so."""
    with _LOCK:
        _STATE["kept"] = bool(kept)


# --------------------------------------------------------------------------- #
# Messages (the app shows them as they are: no "media", "upload", "not found", "audio"... - its plainFailure rules
# would swap them for a generic line)
# --------------------------------------------------------------------------- #

def _said(detail: str) -> str:
    d = " ".join(str(detail or "").split())
    d = re.sub(r"https?://\S+", "", d).strip(" .:;,")
    return f" (OpenRouter said: {d[:120]})" if d else ""


def message() -> str:
    """The job's stop, as the app shows it."""
    s = state()
    kept = (" The work done so far is kept, so a Retry does not pay for it again." if s.get("kept") else "")
    if s["kind"] == CREDIT:
        return ("Your AI balance ran out while this video was being made" + _said(s["detail"]) + ". It stopped "
                "instead of placing clips nobody checked. Top up OpenRouter, then press Retry." + kept)
    if s["kind"] == AUTH:
        return ("The AI key was refused" + _said(s["detail"]) + ". It stopped instead of placing clips nobody "
                "checked. Check the OpenRouter key set on the worker, then press Retry." + kept)
    if s["kind"] == OUTAGE:
        return ("The AI checks stopped answering" + _said(s["detail"]) + ". It stopped instead of placing clips "
                "nobody checked. Press Retry in a few minutes." + kept)
    return ""


def raise_if_stopped(where: str = "") -> None:
    """Raise AIStopped with the job's message once the job must stop (REQUIRE_AI on)."""
    if stopping():
        if where:
            print(f"[ai] stopping the job at: {where}", flush=True)
        raise AIStopped(message())


def low_balance_message(left: float, need: float, what: str = "this video") -> str:
    have = f"about ${left:.2f} left" if left > 0.004 else f"nothing left (${left:.2f})"
    return (f"Your AI balance is too low for {what}: {have}, it needs about ${need:.2f}. "
            "Top up OpenRouter, then press Retry. Nothing was spent.")


# --------------------------------------------------------------------------- #
# The preflight
# --------------------------------------------------------------------------- #

def minutes_from_script(script: str) -> float:
    """A script's spoken length: AI_EST_WORDS_PER_MIN words a minute (the voices here read ~150)."""
    words = len(str(script or "").split())
    wpm = float(getattr(config, "AI_EST_WORDS_PER_MIN", 150.0) or 150.0)
    return words / wpm if words else 0.0


def estimate_usd(minutes: float, scenes: Optional[int] = None, extra: float = 0.0) -> float:
    """
    What a video of `minutes` (and `scenes` lines, else AI_EST_SCENES_PER_MIN a minute) costs on the AI account,
    with AI_EST_MARGIN on top: the planner's calls (AI_EST_PLAN_USD_PER_MIN; measured 2026-10-08 on fd58f969,
    $0.866 for 20.8 min on openai/gpt-5.2 at low effort) and the clip checks (AI_EST_CHECK_USD_PER_SCENE; $0.0066 a
    line on Lake Mead a197 before the 2026-10-07 cuts, -39% on a line's search since) - plus `extra` (an AI fill
    block's own budget).
    """
    m = max(0.0, float(minutes or 0.0))
    n = float(scenes) if scenes else m * float(getattr(config, "AI_EST_SCENES_PER_MIN", 13.0) or 13.0)
    plan = m * float(getattr(config, "AI_EST_PLAN_USD_PER_MIN", 0.045) or 0.0)
    check = n * float(getattr(config, "AI_EST_CHECK_USD_PER_SCENE", 0.005) or 0.0)
    margin = float(getattr(config, "AI_EST_MARGIN", 1.2) or 1.0)
    return round((plan + check) * margin + max(0.0, float(extra or 0.0)), 2)


def need_for(minutes: float = 0.0, scenes: Optional[int] = None, extra: float = 0.0,
             floor: Optional[float] = None) -> float:
    """What a plan or build must have on the account: the estimate, never under `floor` (OPENROUTER_MIN_CREDIT)."""
    base = float(config.OPENROUTER_MIN_CREDIT if floor is None else floor)
    est = estimate_usd(minutes, scenes, extra) if minutes > 0 else 0.0
    return round(max(base, est), 2) if base > 0 or est > 0 else 0.0


def preflight(need: float, what: str = "this video") -> Optional[float]:
    """
    Refuse to start under `need` dollars on the OpenRouter account this worker's director and vision bill to:
    AIStopped with the plain message, before anything is spent. Returns what is left (None = unknown: no OpenRouter
    key, or the balance could not be read - never a reason to refuse). REQUIRE_AI_CREDIT=0 or need 0: no check.
    """
    if not need or need <= 0 or not getattr(config, "REQUIRE_AI_CREDIT", True):
        return None
    from . import credit
    if not credit.uses_openrouter():
        return None
    left = credit.openrouter_left(max_age=0)
    if left is not None:
        print(f"[ai] OpenRouter: ${left:.2f} left, {what} needs about ${need:.2f}", flush=True)
    if left is not None and left < need:
        raise AIStopped(low_balance_message(left, need, what))
    return left
