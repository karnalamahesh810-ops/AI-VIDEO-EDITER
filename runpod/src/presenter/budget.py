"""
A hard spending cap for one AI presenter job, checked before every paid call.

Every call reserves what it could cost (its projected price) before it is
sent; the reservation is settled at the provider's own price (OpenRouter's
usage.cost) when the answer comes back, or released when the call failed
before anything was billed. A call that would take committed money (spent +
still reserved) past the cap is refused with BudgetExceeded, and the caller
falls back to something free (a still with a camera move) - the video still
finishes. Thread-safe; the ledger rows go into the plan's meta.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional


class BudgetExceeded(RuntimeError):
    """A paid call would take the job past its cap."""


class Ticket:
    __slots__ = ("id", "label", "projected", "settled")

    def __init__(self, tid: int, label: str, projected: float):
        self.id, self.label, self.projected, self.settled = tid, label, projected, False


class Budget:
    def __init__(self, cap_usd: float):
        self.cap = max(0.0, float(cap_usd or 0.0))
        self._lock = threading.Lock()
        self._spent = 0.0
        self._reserved: Dict[int, float] = {}
        self._next = 1
        self.rows: List[Dict[str, Any]] = []
        self.refused = 0

    @property
    def spent(self) -> float:
        with self._lock:
            return round(self._spent, 6)

    @property
    def committed(self) -> float:
        with self._lock:
            return round(self._spent + sum(self._reserved.values()), 6)

    def left(self) -> float:
        return max(0.0, self.cap - self.committed)

    def reserve(self, projected: float, label: str = "") -> Ticket:
        """Hold `projected` dollars for one call, or raise BudgetExceeded."""
        projected = max(0.0, float(projected or 0.0))
        with self._lock:
            committed = self._spent + sum(self._reserved.values())
            if committed + projected > self.cap + 1e-9:
                self.refused += 1
                raise BudgetExceeded(f"{label or 'call'}: ${committed:.3f} committed + ${projected:.3f} "
                                     f"> cap ${self.cap:.2f}")
            t = Ticket(self._next, label, projected)
            self._next += 1
            self._reserved[t.id] = projected
            return t

    def settle(self, ticket: Optional[Ticket], actual: Optional[float], **info: Any) -> float:
        """The call came back: count what it really cost (its projected price when the provider did not say)."""
        if ticket is None or ticket.settled:
            return 0.0
        usd = ticket.projected if actual is None else max(0.0, float(actual))
        with self._lock:
            self._reserved.pop(ticket.id, None)
            self._spent += usd
            ticket.settled = True
            self.rows.append({"label": ticket.label, "usd": round(usd, 6), "projected": round(ticket.projected, 6),
                              "at": round(time.time(), 1), **{k: v for k, v in info.items() if v is not None}})
        return usd

    def release(self, ticket: Optional[Ticket], why: str = "") -> None:
        """The call failed before anything was billed: give its reservation back."""
        if ticket is None or ticket.settled:
            return
        with self._lock:
            self._reserved.pop(ticket.id, None)
            ticket.settled = True
            if why:
                self.rows.append({"label": ticket.label, "usd": 0.0, "projected": round(ticket.projected, 6),
                                  "at": round(time.time(), 1), "released": str(why)[:160]})

    def report(self) -> Dict[str, Any]:
        with self._lock:
            return {"capUsd": round(self.cap, 2), "spentUsd": round(self._spent, 4),
                    "reservedUsd": round(sum(self._reserved.values()), 4), "calls": len(self.rows),
                    "refused": self.refused}
