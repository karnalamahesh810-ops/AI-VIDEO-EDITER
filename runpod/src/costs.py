"""
What one video cost, by category, from counted units and a price table.

Every paid thing a job does is counted as a unit here - a vision judgement,
a storyboard rating, a planning call, a generated image, a byte through a
proxy, a worker-second, a second of narration made by the free voice
(src/tts.py) - and priced at the end from a table that comes from
configuration (PRICES in the environment, or the app's provider_prices table
passed in the job input), never from code. Fan-out children and the render
chunks of a spread render return their own counts (and RunPod says how long
each of their jobs ran) and the parent absorbs them, so a video's cost
includes the work done on other workers.

The machine's own seconds are priced at what that machine really costs, which
the worker knows better than any table: a serverless worker at
runpod.worker_second, a pod (scripts/pod_job.py: use_pod) at its own hourly
price, its start-up included. A call whose provider reported its own price
(OpenRouter's usage.cost) is counted at that price; only the calls no
provider priced are estimated from credits.

Kie bills in credits shared across the vision, planning and image models;
when the key is a Kie key the balance is read at the start and the end of
the parent job, so the ledger also carries the measured credits, which is
what the estimate is calibrated against.
"""
import json
import math
import os
import threading
import time
from collections import defaultdict
from typing import Any, Dict, Optional

import requests

from . import config

# Units are counts (calls, bytes, seconds); prices are USD per unit except
# where the key says credits (kie.credit converts).
DEFAULT_PRICES: Dict[str, float] = {
    "kie.credit": 0.005,                 # USD per Kie credit
    "vision.judge": 0.5,                 # credits: one 3-frame verdict
    "vision.rate_tiles": 0.6,            # credits: one 20-tile sheet, every tile rated
    "vision.pick_tile": 0.4,             # credits: one 20-tile sheet, one pick
    "vision.hedge": 0.5,                 # credits: a backup request sent while the first model was slow
    "vision.anchor": 0.3,                # credits: one frame, "where is X" (src/anchors.py)
    "vision.review": 1.0,                # credits: the AI review's call, 4-6 scenes' frames (src/review.py)
    "llm.director_call": 1.0,            # credits: one planning batch
    "llm.brief_call": 1.0,               # credits: the story brief
    "image.generate": 4.0,               # credits: one generated image
    # USD: a serverless worker, cpu3c 16 vCPU ($0.576/h: every serverless hour of the RunPod bill since
    # 2026-09-30 was priced at exactly that; the endpoint prefers 16 cores since 2026-09-28). A pod's own
    # seconds are priced at the pod's price instead (use_pod); its render helpers are serverless workers.
    "runpod.worker_second": 0.576 / 3600,
    "proxy.gb": 0.0,                     # USD per GB (ISP proxies are flat monthly)
    # No provider charges a SERP call now: Bright Data's SERP was removed on 2026-10-04, and SerpApi and
    # Serper are flat monthly plans. Older workers still count them; priced at 0 they add nothing.
    "serp.call": 0.0,
    "storage.gb": 0.021,                 # USD per GB-month kept
    "tts.char": 0.0,                     # the app pays for TTS; kept for the total
    # USD per second of narration made by the free voice (src/tts.py). An
    # ESTIMATE, not a measurement: Kokoro on a 24 GB serverless GPU ($0.69/h,
    # A5000 / L4 / 3090, 2026-10) voices ~50x faster than it is spoken, and up
    # to four cold workers each bill their start - about 3 cents per 20-minute
    # narration. Chatterbox is roughly real time: set this to ~0.0002 with it.
    "tts.seconds": 0.000025,
    # The GPU seconds the voice endpoint itself reported: counted, not priced
    # (they are inside tts.seconds); they are what the estimate is checked against.
    "tts.gpu_seconds": 0.0,
    # A language version's narration on our own voice endpoint (src/langversion.py): what RunPod bills of each
    # part's job - its wait for a worker (a cold start) and its run - on a 16-24 GB GPU worker ($0.00016-0.00019
    # a second, flex, 2026-10). Each worker's idle minute after its last part is not in it.
    "lang.tts_gpu_seconds": 0.00019,
}
_CREDIT_KEYS = ("vision.judge", "vision.rate_tiles", "vision.pick_tile", "vision.hedge", "vision.anchor",
                "vision.review", "llm.director_call",
                "llm.brief_call", "image.generate")
_CATEGORY = {"vision.judge": "vision", "vision.rate_tiles": "vision", "vision.pick_tile": "vision",
             "vision.hedge": "vision", "vision.anchor": "vision", "vision.review": "vision",
             "llm.director_call": "llm", "llm.brief_call": "llm", "image.generate": "image",
             "runpod.worker_second": "runpod", "proxy.bytes": "proxy", "serp.call": "serp",
             "storage.bytes": "storage", "tts.char": "tts", "tts.seconds": "tts", "tts.gpu_seconds": "tts",
             "lang.tts_gpu_seconds": "tts"}
# Categories whose provider reports each call's own price ("<category>.usd"): when it
# did, that call is counted at its price instead of the category's credit estimate
# (OpenRouter's usage.cost - the vision judge since 2026-10-01, the planning calls
# since 2026-10-05). "<category>.measured" counts the answers that came priced, so a
# call that went to a provider that does not say (the Kie fallback) is still estimated.
_MEASURED = ("vision", "llm", "image",       # image.usd: an OpenRouter picture (media._openrouter_generate)
             # The AI presenter style (src/presenter): presenter.usd its lip-synced talking clips (heygen/avatar-iv),
             # aivideo.usd its image-to-video clips - each call at OpenRouter's own usage.cost.
             "presenter", "aivideo")
# Counts kept beside those prices, never priced as units: the seconds generated and the seconds on screen.
_COUNT_ONLY = {"presenter.seconds", "presenter.screen_seconds", "aivideo.seconds", "aivideo.screen_seconds"}

# A pod's price when nothing says what its machine costs (scripts/pod_job.py reads
# POD_COST_PER_HR, then the pod's own RunPod record): a 16-vCPU cpu3c pod, $0.48/h
# (RunPod's price list, 2026-10-05).
DEFAULT_POD_USD_PER_HOUR = 0.48
# Prices the job input's table (the app's provider_prices) cannot change: the worker
# knows them better. The table's runpod.worker_second, 0.000136 ($0.49/h), priced every
# serverless second under the $0.576/h RunPod bills, and one number cannot tell a pod
# from a worker; its serp.call ($0.0015) priced a call no provider charges any more -
# about $1 of a video's "cost" that was never paid. PRICES in the environment still sets them.
_WORKER_OWNED = frozenset({"runpod.worker_second", "serp.call"})


def _counts_only(key: str) -> bool:
    """A measured price, a count of priced answers, a token count or a call count by kind
    (vision.<kind>.calls, llm.<kind>.calls): never priced as a unit of its own."""
    return key.endswith((".usd", ".measured", ".calls")) or key in _COUNT_ONLY or \
        (key.startswith(tuple(f"{c}." for c in _MEASURED)) and key.endswith("_tokens"))


def breakdown(units: dict) -> dict:
    """
    What the measured AI money went on, from a ledger's units: {"vision": {kind: {"usd", "calls"}},
    "llm": {kind: {...}}} - each call kind's own OpenRouter price (vision.<kind>.usd: judge, judge_open,
    judge_still, pick, rate, pool_rate, anchor, review...; llm.<kind>.usd: brief, plan, rescue, sequences,
    assign, replan...) and vision.hedge.usd, what hedges' second requests cost. {} for a ledger from before
    the kinds were kept.
    """
    out: Dict[str, Dict[str, dict]] = {}
    for key, value in (units or {}).items():
        parts = str(key).split(".")
        if len(parts) != 3 or parts[0] not in _MEASURED or parts[2] not in ("usd", "calls"):
            continue
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        row = out.setdefault(parts[0], {}).setdefault(parts[1], {"usd": 0.0, "calls": 0})
        if parts[2] == "usd":
            row["usd"] = round(row["usd"] + v, 6)
        else:
            row["calls"] = int(row["calls"] + v)
    return out


# What this process runs on, for the price of its own seconds: a serverless worker
# (the default) or a pod (use_pod, set by scripts/pod_job.py before its job starts).
# "boot": the pod's start-up not yet charged to a job (charge_machine_start).
_MACHINE: Dict[str, Any] = {"kind": "serverless", "usd_per_hour": None, "source": "", "boot": 0.0}
_MACHINE_LOCK = threading.Lock()


def use_pod(usd_per_hour: Optional[float] = None, boot_seconds: float = 0.0, source: str = "") -> None:
    """
    This process is a RunPod pod's job (scripts/pod_job.py): its own seconds are
    priced at the pod's hourly price (`usd_per_hour`; DEFAULT_POD_USD_PER_HOUR when
    it is not known) instead of a serverless worker's, and `boot_seconds` - the
    pod's start before its job, billed too - are charged to the first job that
    starts here (charge_machine_start). `source` says where the price came from.
    """
    try:
        rate = float(usd_per_hour) if usd_per_hour is not None else None
    except (TypeError, ValueError):
        rate = None
    if rate is not None and not (math.isfinite(rate) and rate > 0):
        rate = None
    try:
        boot = max(0.0, float(boot_seconds or 0.0))
    except (TypeError, ValueError):
        boot = 0.0
    with _MACHINE_LOCK:
        _MACHINE.update(kind="pod", usd_per_hour=rate, source=str(source or ("" if rate else "default")),
                        boot=boot if math.isfinite(boot) else 0.0)


def use_serverless() -> None:
    """This process is a serverless worker (the default): its seconds at runpod.worker_second."""
    with _MACHINE_LOCK:
        _MACHINE.update(kind="serverless", usd_per_hour=None, source="", boot=0.0)


def machine() -> dict:
    """{"kind", "usd_per_hour", "source", "boot"}: what this process runs on (a copy)."""
    with _MACHINE_LOCK:
        return dict(_MACHINE)


def _env_prices() -> Dict[str, float]:
    raw = os.getenv("PRICES", "").strip()
    if not raw:
        return {}
    try:
        table = json.loads(raw)
        return {k: float(v) for k, v in table.items()} if isinstance(table, dict) else {}
    except (ValueError, TypeError):
        return {}


class Ledger:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self, prices: Optional[dict] = None) -> None:
        with self.lock:
            self.units: Dict[str, float] = defaultdict(float)
            self.prices = dict(DEFAULT_PRICES)
            self.prices.update(_env_prices())
            if isinstance(prices, dict):
                for k, v in prices.items():
                    if str(k) in _WORKER_OWNED:
                        continue            # the machine's rate and the retired SERP call: see _WORKER_OWNED
                    try:
                        self.prices[str(k)] = float(v)
                    except (TypeError, ValueError):
                        pass
            self.child_seconds = 0.0
            self.children = 0
            # The pod's start-up, when this is the first job on it (charge_machine_start).
            self.boot_seconds = 0.0
            self.started = time.time()
            self.balance_before: Optional[float] = None
            self.balance_after: Optional[float] = None

    def record(self, key: str, units: float = 1.0) -> None:
        with self.lock:
            self.units[key] += float(units)
            # One answer that came with its provider's own price (vision/director _note_usage):
            # counted, so the calls priced that way are not estimated from credits as well.
            if key.endswith(".usd") and key[:-4] in _MEASURED and float(units) > 0:
                self.units[key[:-4] + ".measured"] += 1

    def absorb(self, child: Optional[dict], billed_seconds: Optional[float] = None) -> None:
        """
        A fan-out child's or a render chunk's summary: its units and its worker
        time join this job's. `billed_seconds`: how long RunPod says the child's
        job ran (its status's executionTime) - a job that failed, was cancelled
        or returned no summary was billed all the same. The larger counts.
        """
        try:
            billed = max(0.0, float(billed_seconds or 0.0))
        except (TypeError, ValueError):
            billed = 0.0
        if not isinstance(child, dict):
            if billed <= 0 or not math.isfinite(billed):
                return
            child = {}
        units = child.get("units") if isinstance(child.get("units"), dict) else {}
        try:
            own = max(0.0, float(child.get("worker_seconds") or 0.0))
        except (TypeError, ValueError):
            own = 0.0
        with self.lock:
            for k, v in units.items():
                try:
                    self.units[k] += float(v)
                except (TypeError, ValueError):
                    pass
            for c in _MEASURED:
                # A summary from a worker that does not count its priced answers (an older
                # image): its calls of that category were priced, as the ledger read them then.
                try:
                    priced = float(units.get(f"{c}.usd") or 0.0) > 0 and f"{c}.measured" not in units
                    if priced:
                        self.units[f"{c}.measured"] += sum(float(units.get(k) or 0.0) for k in _CREDIT_KEYS
                                                           if _CATEGORY.get(k) == c)
                except (TypeError, ValueError):
                    pass
            self.child_seconds += max(own, billed if math.isfinite(billed) else 0.0)
            self.children += 1

    def credits_estimated(self) -> float:
        with self.lock:
            return sum(self.units.get(k, 0.0) * self.prices.get(k, 0.0) for k in _CREDIT_KEYS)

    def _unpriced_share(self, cat: str, calls: float, usd: float) -> float:
        """
        The share of category `cat`'s counted calls that no provider priced, so
        they are estimated from credits: all of them when none came priced; none
        when every one did. Before, one priced call dropped the estimate of the
        whole category - a call that fell back to Kie (no price in its answer)
        then cost nothing in the ledger.
        """
        if usd <= 0 or calls <= 0:
            return 1.0
        priced = float(self.units.get(f"{cat}.measured", 0.0) or 0.0)
        if priced <= 0:
            return 0.0              # priced, but nothing counted the answers: the estimate goes, as it always did
        return max(0.0, calls - priced) / calls

    def summary(self, worker_seconds: Optional[float] = None) -> dict:
        m = machine()
        with self.lock:
            # The job's own seconds (and, on a pod, the pod's start-up when this was its first job).
            own = float(worker_seconds if worker_seconds is not None else time.time() - self.started)
            own += self.boot_seconds
            total_seconds = own + self.child_seconds
            credit = self.prices.get("kie.credit", 0.005)
            by = defaultdict(float)
            estimate = defaultdict(float)         # the credit estimate of each category's calls
            calls = defaultdict(float)            # and how many calls it counts
            # The provider's own price per call (OpenRouter's usage.cost: src/vision.py,
            # src/director.py) stands in for the Kie-credit estimate of the calls it priced:
            # the estimate priced the Lake Powell job's vision at $2.83, and every planning
            # call at $0.005 (openai/gpt-5.2 cost ~$0.04 a call).
            provider_usd = {c: float(self.units.get(f"{c}.usd", 0.0) or 0.0) for c in _MEASURED}
            for k, n in self.units.items():
                cat = _CATEGORY.get(k, "other")
                if _counts_only(k):
                    continue
                if k in _CREDIT_KEYS:
                    estimate[cat] += n * self.prices.get(k, 0.0) * credit
                    calls[cat] += n
                elif k == "proxy.bytes":
                    by[cat] += n / 1e9 * self.prices.get("proxy.gb", 0.0)
                elif k == "storage.bytes":
                    by[cat] += n / 1e9 * self.prices.get("storage.gb", 0.0)
                else:
                    by[cat] += n * self.prices.get(k, 0.0)
            for cat, usd in estimate.items():
                share = self._unpriced_share(cat, calls[cat], provider_usd[cat]) if cat in provider_usd else 1.0
                by[cat] += usd * share
            for c, usd in provider_usd.items():
                by[c] += usd
            # RunPod: this machine's own seconds at its own rate (a pod's price, else a serverless
            # worker's), the children's - fan-out parts, render chunks: always serverless workers -
            # at a worker's.
            worker_rate = self.prices.get("runpod.worker_second", 0.0)
            own_rate = worker_rate
            if m.get("kind") == "pod":
                own_rate = float(m.get("usd_per_hour") or DEFAULT_POD_USD_PER_HOUR) / 3600.0
            by["runpod"] += own * own_rate + self.child_seconds * worker_rate
            measured = None
            if self.balance_before is not None and self.balance_after is not None:
                measured = round(self.balance_before - self.balance_after, 2)
            out = {c: round(by.get(c, 0.0), 4) for c in
                   ("runpod", "vision", "llm", "image", "proxy", "serp", "storage", "tts", "other")}
            # The AI presenter style's generated video (src/presenter): only on a job that made some.
            for c in ("presenter", "aivideo"):
                if by.get(c) or any(k.startswith(f"{c}.") for k in self.units):
                    out[c] = round(by.get(c, 0.0), 4)
            out["total"] = round(sum(out.values()), 4)
            out["credits_estimated"] = round(sum(self.units.get(k, 0.0) * self.prices.get(k, 0.0)
                                                 for k in _CREDIT_KEYS), 2)
            out["credits_measured"] = measured
            if measured is not None:
                out["measured_ai_usd"] = round(measured * credit, 4)
            out["vision_measured"] = provider_usd["vision"] > 0
            out["llm_measured"] = provider_usd["llm"] > 0
            out["worker_seconds"] = round(total_seconds, 1)
            out["own_seconds"] = round(own, 1)
            out["children"] = self.children
            # What the seconds were priced at: this machine and the workers that helped it.
            out["machine"] = str(m.get("kind") or "serverless")
            out["machine_usd_per_hour"] = round(own_rate * 3600.0, 4)
            out["worker_usd_per_hour"] = round(worker_rate * 3600.0, 4)
            if m.get("kind") == "pod":
                out["machine_price_source"] = str(m.get("source") or "default")
            if self.boot_seconds > 0:
                out["boot_seconds"] = round(self.boot_seconds, 1)
            out["units"] = {k: (int(v) if float(v).is_integer() else round(v, 6 if k.endswith(".usd") else 3))
                            for k, v in self.units.items()}
            split = breakdown(out["units"])
            if split:
                out["breakdown"] = split        # the AI money by call kind (vision.<kind>.usd, llm.<kind>.usd)
            return out


LEDGER = Ledger()


def reset(prices: Optional[dict] = None) -> None:
    LEDGER.reset(prices)


def record(key: str, units: float = 1.0) -> None:
    LEDGER.record(key, units)


def absorb(child: Optional[dict], billed_seconds: Optional[float] = None) -> None:
    LEDGER.absorb(child, billed_seconds)


def summary(worker_seconds: Optional[float] = None) -> dict:
    return LEDGER.summary(worker_seconds)


def charge_machine_start() -> float:
    """
    The machine's start-up (a pod's: use_pod) charged to the job starting now -
    once per process, so the first job pays it (a batch's first video) and none
    pays it twice. Call it after reset(). Returns the seconds charged.
    """
    with _MACHINE_LOCK:
        boot = float(_MACHINE.get("boot") or 0.0)
        _MACHINE["boot"] = 0.0
    with LEDGER.lock:
        LEDGER.boot_seconds = boot
    return boot


def kie_balance(timeout: int = 10) -> Optional[float]:
    """The Kie credit balance, when the vision key is a Kie key; else None."""
    key = config.VISION_API_KEY
    if not key or "kie.ai" not in (config.VISION_API_BASE or "") or config.kie_blocked(config.VISION_API_BASE):
        return None
    try:
        r = requests.get("https://api.kie.ai/api/v1/chat/credit",
                         headers={"Authorization": f"Bearer {key}"}, timeout=timeout)
        data = r.json().get("data")
        return float(data) if data is not None else None
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        return None


def measure_start() -> None:
    LEDGER.balance_before = kie_balance()


def measure_end() -> None:
    if LEDGER.balance_before is not None:
        LEDGER.balance_after = kie_balance()
