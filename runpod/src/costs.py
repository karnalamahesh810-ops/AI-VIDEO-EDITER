"""
What one video cost, by category, from counted units and a price table.

Every paid thing a job does is counted as a unit here - a vision judgement,
a storyboard rating, a planning call, a generated image, a SERP call, a
byte through a proxy, a worker-second - and priced at the end from a table
that comes from configuration (PRICES in the environment, or the app's
provider_prices table passed in the job input), never from code. Fan-out
children return their own counts and the parent absorbs them, so a video's
cost includes the work done on other workers.

Kie bills in credits shared across the vision, planning and image models;
when the key is a Kie key the balance is read at the start and the end of
the parent job, so the ledger also carries the measured credits, which is
what the estimate is calibrated against.
"""
import json
import os
import threading
import time
from collections import defaultdict
from typing import Dict, Optional

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
    "llm.director_call": 1.0,            # credits: one planning batch
    "llm.brief_call": 1.0,               # credits: the story brief
    "image.generate": 4.0,               # credits: one generated image
    "runpod.worker_second": 0.576 / 3600,  # USD: serverless cpu3c-16-32 (the endpoint prefers 16 cores since 2026-09-28)
    "proxy.gb": 0.0,                     # USD per GB (ISP proxies are flat monthly)
    "serp.call": 0.0015,                 # USD: one paid SERP request (old documents; no provider uses it now)
    "storage.gb": 0.021,                 # USD per GB-month kept
    "tts.char": 0.0,                     # the app pays for TTS; kept for the total
}
_CREDIT_KEYS = ("vision.judge", "vision.rate_tiles", "vision.pick_tile", "vision.hedge", "vision.anchor",
                "llm.director_call",
                "llm.brief_call", "image.generate")
_CATEGORY = {"vision.judge": "vision", "vision.rate_tiles": "vision", "vision.pick_tile": "vision",
             "vision.hedge": "vision", "vision.anchor": "vision",
             "llm.director_call": "llm", "llm.brief_call": "llm", "image.generate": "image",
             "runpod.worker_second": "runpod", "proxy.bytes": "proxy", "serp.call": "serp",
             "storage.bytes": "storage", "tts.char": "tts"}


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
                    try:
                        self.prices[str(k)] = float(v)
                    except (TypeError, ValueError):
                        pass
            self.child_seconds = 0.0
            self.children = 0
            self.started = time.time()
            self.balance_before: Optional[float] = None
            self.balance_after: Optional[float] = None

    def record(self, key: str, units: float = 1.0) -> None:
        with self.lock:
            self.units[key] += float(units)

    def absorb(self, child: Optional[dict]) -> None:
        """A fan-out child's summary: its units and its worker time join this job's."""
        if not isinstance(child, dict):
            return
        with self.lock:
            for k, v in (child.get("units") or {}).items():
                try:
                    self.units[k] += float(v)
                except (TypeError, ValueError):
                    pass
            self.child_seconds += float(child.get("worker_seconds") or 0.0)
            self.children += 1

    def credits_estimated(self) -> float:
        with self.lock:
            return sum(self.units.get(k, 0.0) * self.prices.get(k, 0.0) for k in _CREDIT_KEYS)

    def summary(self, worker_seconds: Optional[float] = None) -> dict:
        with self.lock:
            own = float(worker_seconds if worker_seconds is not None else time.time() - self.started)
            total_seconds = own + self.child_seconds
            credit = self.prices.get("kie.credit", 0.005)
            by = defaultdict(float)
            # The vision provider's own price per call (OpenRouter's usage.cost,
            # src/vision.py) replaces the Kie-credit estimate when it is there:
            # the estimate priced the Lake Powell job's vision at $2.83.
            measured_vision = float(self.units.get("vision.usd", 0.0) or 0.0)
            for k, n in self.units.items():
                cat = _CATEGORY.get(k, "other")
                if k == "vision.usd" or k.startswith("vision.") and k.endswith("_tokens"):
                    continue
                if k in _CREDIT_KEYS:
                    if cat == "vision" and measured_vision > 0:
                        continue
                    by[cat] += n * self.prices.get(k, 0.0) * credit
                elif k == "proxy.bytes":
                    by[cat] += n / 1e9 * self.prices.get("proxy.gb", 0.0)
                elif k == "storage.bytes":
                    by[cat] += n / 1e9 * self.prices.get("storage.gb", 0.0)
                else:
                    by[cat] += n * self.prices.get(k, 0.0)
            by["runpod"] += total_seconds * self.prices.get("runpod.worker_second", 0.0)
            by["vision"] += measured_vision
            measured = None
            if self.balance_before is not None and self.balance_after is not None:
                measured = round(self.balance_before - self.balance_after, 2)
            out = {c: round(by.get(c, 0.0), 4) for c in
                   ("runpod", "vision", "llm", "image", "proxy", "serp", "storage", "tts", "other")}
            out["total"] = round(sum(out.values()), 4)
            out["credits_estimated"] = round(sum(self.units.get(k, 0.0) * self.prices.get(k, 0.0)
                                                 for k in _CREDIT_KEYS), 2)
            out["credits_measured"] = measured
            if measured is not None:
                out["measured_ai_usd"] = round(measured * credit, 4)
            out["vision_measured"] = measured_vision > 0
            out["worker_seconds"] = round(total_seconds, 1)
            out["own_seconds"] = round(own, 1)
            out["children"] = self.children
            out["units"] = {k: (int(v) if float(v).is_integer() else round(v, 6 if k.endswith(".usd") else 3))
                            for k, v in self.units.items()}
            return out


LEDGER = Ledger()


def reset(prices: Optional[dict] = None) -> None:
    LEDGER.reset(prices)


def record(key: str, units: float = 1.0) -> None:
    LEDGER.record(key, units)


def absorb(child: Optional[dict]) -> None:
    LEDGER.absorb(child)


def summary(worker_seconds: Optional[float] = None) -> dict:
    return LEDGER.summary(worker_seconds)


def kie_balance(timeout: int = 10) -> Optional[float]:
    """The Kie credit balance, when the vision key is a Kie key; else None."""
    key = config.VISION_API_KEY
    if not key or "kie.ai" not in (config.VISION_API_BASE or ""):
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
