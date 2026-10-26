"""
The proxy manager: which route carries the next request, and what each
route has earned.

Every proxy keeps its latency, success rate, consecutive failures, active
requests and per-domain record, and moves through healthy -> degraded ->
quarantined -> recovering -> healthy. Quarantine grows with repeats (five
minutes, then ten, twenty, thirty at most) and a recovering proxy carries one
trial request before it is trusted again. A failure that is the video's
fault (removed, private, a bad merge) never counts against the route.

Proxies are never printed or exported: only their index in the pool.
"""
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .errors import RETRY, FailureClass

HEALTHY, DEGRADED, QUARANTINED, RECOVERING = "healthy", "degraded", "quarantined", "recovering"
_DEGRADE_AFTER = 2          # consecutive route faults
_QUARANTINE_AFTER = 3
_RESTORE_AFTER = 3          # successes in a row to leave degraded


@dataclass
class ProxyRecord:
    index: int
    url: str
    state: str = HEALTHY
    latency_ms: float = 0.0
    successes: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    active: int = 0
    last_failure_type: str = ""
    last_failure_at: float = 0.0
    quarantined_until: float = 0.0
    quarantines: int = 0
    domains: Dict[str, Dict[str, int]] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        total = self.successes + self.failures
        return round(self.successes / total, 3) if total else 1.0

    def snapshot(self) -> dict:
        return {"proxy_id": f"proxy_{self.index:02d}" if self.url else "direct",
                "healthy": self.state == HEALTHY, "state": self.state,
                "latency_ms": int(self.latency_ms), "success_rate": self.success_rate,
                "successes": self.successes, "failures": self.failures,
                "consecutive_failures": self.consecutive_failures, "active_jobs": self.active,
                "last_failure_type": self.last_failure_type or None,
                "quarantined_for_s": max(0, int(self.quarantined_until - time.time())) if self.state == QUARANTINED else 0,
                "domains": {d: dict(v) for d, v in self.domains.items()}}


def _clean_record(r: ProxyRecord) -> bool:
    """One recent failure in a long run of successes (a refusal is also how
    YouTube answers an age- or region-locked video on the first route that
    tries it). A second refusal in a row still quarantines the route."""
    return r.consecutive_failures <= 1 and r.successes >= 10 and r.success_rate >= 0.9


# A degraded route with a short record that still mostly works (one failure in a row, at least
# _DEGRADED_MIN_RATE of its requests through): kept in the rotation behind the healthy routes.
_DEGRADED_MIN_RATE = 0.6
_DEGRADED_PENALTY = 2


def _usable_record(r: ProxyRecord) -> bool:
    return r.consecutive_failures <= 1 and r.successes >= 2 and r.success_rate >= _DEGRADED_MIN_RATE


class ProxyManager:
    def __init__(self, urls: List[str], direct: bool = False,
                 quarantine_base: float = 300.0, quarantine_max: float = 1800.0):
        self.records: List[ProxyRecord] = []
        if direct:
            self.records.append(ProxyRecord(index=0, url=""))
        for i, u in enumerate(urls):
            if u:
                self.records.append(ProxyRecord(index=i + 1, url=u))
        self.by_url: Dict[str, ProxyRecord] = {r.url: r for r in self.records}
        self.base, self.max = quarantine_base, quarantine_max
        self.lock = threading.Lock()
        self._rr = 0

    # ---------------------------------------------------------------- pick
    def _tick(self, now: float) -> None:
        for r in self.records:
            if r.state == QUARANTINED and r.quarantined_until <= now:
                r.state = RECOVERING

    def _order(self, now: float) -> List[ProxyRecord]:
        self._tick(now)
        rank = {HEALTHY: 0, DEGRADED: 1, RECOVERING: 2, QUARANTINED: 3}
        n = len(self.records)
        self._rr += 1

        def key(r: ProxyRecord):
            # A recovering route carries one trial at a time; when every
            # route is quarantined, the one due back soonest goes first.
            busy = r.active if r.state != RECOVERING else r.active * 100
            state = rank[r.state]
            if r.state == DEGRADED and _clean_record(r):
                # Degraded by one refusal after a long clean run: stay in the
                # rotation, one request behind an equally busy healthy route.
                # Ranked after every healthy route it got no traffic and so
                # could never earn its way back: on the Lake Powell pod
                # (2026-10-01) 11 of 17 proxies sat degraded at 97-99% success
                # (one at 138 of 139) while 4 carried all of YouTube.
                state, busy = rank[HEALTHY], busy + 1
            elif r.state == DEGRADED and _usable_record(r):
                # Degraded by one refusal early in the job, before it could build a long record: it takes
                # traffic once the healthy routes each carry _DEGRADED_PENALTY more requests than it does, and
                # earns its way back with _RESTORE_AFTER successes (a second refusal in a row still quarantines
                # it). The Hoover Dam pod (2026-10-26): 10 of 13 proxies were degraded by one bot check in the
                # first minutes (4-13 requests each, 62-87% success) and never asked again, while 3 carried all
                # 730 sections at ~12 s a request - five yt-dlp processes on each address.
                state, busy = rank[HEALTHY], busy + _DEGRADED_PENALTY
            elif r.state == RECOVERING and r.active == 0:
                # Back from quarantine: its one trial request goes out once the healthy routes each carry
                # _DEGRADED_PENALTY more than it does. Ranked after every healthy route it never got the trial
                # and stayed out for the whole job: on the Hoover Dam pod (2026-10-26) proxies 3, 4, 7, 9 and 10
                # took two bot checks in the job's first 9 seconds, served their 5 minutes and sat "recovering"
                # for the next 40 while 3 routes carried all 730 sections. A trial already out keeps the rest
                # off it (one at a time); a failed trial quarantines it again, longer.
                state, busy = rank[HEALTHY], _DEGRADED_PENALTY
            fair = (r.index - self._rr) % max(1, n)          # round-robin among equals
            due = r.quarantined_until if r.state == QUARANTINED else 0.0
            return (state, due, busy, r.latency_ms, fair)
        return sorted(self.records, key=key)

    def peek(self) -> str:
        """The route the next request would take, without claiming it."""
        with self.lock:
            order = self._order(time.time())
        return order[0].url if order else ""

    def acquire(self, domain: str = "youtube.com", avoid=()) -> str:
        """Claim the best route. `avoid`: routes a retry has already tried for the same
        clip - the best route not among them is taken, the best of all only when every
        usable route was tried (a quarantined route never wins over a tried healthy one)."""
        with self.lock:
            order = self._order(time.time())
            if not order:
                return ""
            r = order[0]
            if avoid:
                fresh = [x for x in order if x.url not in avoid and x.state != QUARANTINED]
                if fresh:
                    r = fresh[0]
            r.active += 1
            return r.url

    # -------------------------------------------------------------- report
    def release(self, url: str, ok: bool, failure: Optional[FailureClass] = None,
                latency_ms: Optional[float] = None, domain: str = "youtube.com") -> None:
        with self.lock:
            r = self.by_url.get(url)
            if r is None:
                return
            r.active = max(0, r.active - 1)
            self._record(r, ok, failure, latency_ms, domain)

    def report(self, url: str, failure: FailureClass, domain: str = "youtube.com") -> None:
        """A failure on a route that was not acquired (the old bench call)."""
        with self.lock:
            r = self.by_url.get(url)
            if r is not None:
                self._record(r, False, failure, None, domain)

    def _record(self, r: ProxyRecord, ok: bool, failure: Optional[FailureClass],
                latency_ms: Optional[float], domain: str) -> None:
        now = time.time()
        d = r.domains.setdefault(domain, {"ok": 0, "fail": 0})
        if latency_ms is not None:
            r.latency_ms = latency_ms if not r.latency_ms else 0.7 * r.latency_ms + 0.3 * latency_ms
        if ok:
            r.successes += 1
            d["ok"] += 1
            r.consecutive_failures = 0
            r.consecutive_successes += 1
            if r.state == RECOVERING or (r.state == DEGRADED and r.consecutive_successes >= _RESTORE_AFTER):
                r.state = HEALTHY
                r.quarantines = 0 if r.state == HEALTHY and r.consecutive_successes >= _RESTORE_AFTER else r.quarantines
            return
        cls = failure or FailureClass.UNKNOWN
        if not RETRY.get(cls, {}).get("proxy_fault", False):
            return                      # the video's fault, not the route's
        r.failures += 1
        d["fail"] += 1
        r.consecutive_successes = 0
        r.consecutive_failures += 1
        r.last_failure_type = cls.value
        r.last_failure_at = now
        # A refusal is the platform flagging the address: the route steps
        # aside at once and is quarantined on the second; a rate limit
        # quarantines immediately. Timeouts and drops take two, then three.
        refused = cls in (FailureClass.ACCESS_DENIED, FailureClass.BOT_CHECK, FailureClass.RATE_LIMITED)
        if r.state == RECOVERING or r.consecutive_failures >= _QUARANTINE_AFTER \
                or cls == FailureClass.RATE_LIMITED \
                or (refused and r.consecutive_failures >= 2):
            r.quarantines += 1
            r.quarantined_until = now + min(self.max, self.base * (2 ** (r.quarantines - 1)))
            r.state = QUARANTINED
        elif r.consecutive_failures >= _DEGRADE_AFTER or refused:
            r.state = DEGRADED

    # ---------------------------------------------------------------- misc
    def index_of(self, url: str) -> int:
        r = self.by_url.get(url)
        return r.index if r else 0

    def snapshot(self) -> List[dict]:
        with self.lock:
            self._tick(time.time())
            return [r.snapshot() for r in self.records]

    def healthy_count(self) -> int:
        with self.lock:
            self._tick(time.time())
            return sum(1 for r in self.records if r.state in (HEALTHY, DEGRADED))

    def reset_stats(self) -> None:
        """New job: keep states and quarantines, restart the counters."""
        with self.lock:
            for r in self.records:
                r.successes = r.failures = 0
                r.active = 0
                r.domains = {}
