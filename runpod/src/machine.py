"""
What this machine can really serve, and how busy it was.

The app sizes a pod build by environment variables (SOURCE_WORKERS 28, NETWORK_CONCURRENCY 16, VISION_CONCURRENCY
20, ...) chosen when pods had 32 cores. Option B (2026-10-19) moved pod builds to 16 cores and nothing re-sized
them: on the Hoover Dam build (82e7cae1, 2026-10-26) the footage search took 42 of 47 minutes. Two things here:

- sizing (cpus, encode_threads, source_workers): the cores the container may use - its cgroup quota, the
  scheduler's affinity and the host's count, the smallest - and the values sourcing derives from them, so an
  environment that asks for more than the cores can serve is clamped instead of thrashing them;
- a sampler (Sampler): the container's own CPU use against that allowance, its memory headroom, CPU throttling
  and how many encoder / yt-dlp processes ran at once, every few seconds of the footage search, for the job
  result (meta.sourcing.machine). Without it "was the pod CPU-bound?" could only be guessed.

Nothing here can fail a job: every read that does not work returns nothing.
"""
from __future__ import annotations

import math
import os
import threading
import time
from typing import Dict, List, Optional

from . import config


def _read(path: str) -> str:
    try:
        with open(path, encoding="ascii", errors="replace") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def cgroup_cpus() -> float:
    """The container's CPU limit (cgroup v2, then v1); 0 when it has none or it cannot be read."""
    parts = _read("/sys/fs/cgroup/cpu.max").split()
    if parts:
        quota, period = parts[0], (parts[1] if len(parts) > 1 else "100000")
        try:
            if quota != "max" and float(period) > 0:
                return float(quota) / float(period)
        except ValueError:
            pass
    try:
        quota = float(_read("/sys/fs/cgroup/cpu/cpu.cfs_quota_us") or "-1")
        period = float(_read("/sys/fs/cgroup/cpu/cpu.cfs_period_us") or "0")
        if quota > 0 and period > 0:
            return quota / period
    except ValueError:
        pass
    return 0.0


def cpus() -> int:
    """The cores this container may use: MACHINE_CPUS when set, else the smallest of the cgroup limit, the
    scheduler's affinity and the host's count (os.cpu_count() alone reports the HOST's cores)."""
    forced = int(getattr(config, "MACHINE_CPUS", 0) or 0)
    if forced > 0:
        return forced
    found = [os.cpu_count() or 1]
    try:
        found.append(len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        pass
    limit = cgroup_cpus()
    if limit > 0:
        found.append(int(math.ceil(limit)))
    return max(1, min(found))


def memory_gb() -> float:
    """The container's memory limit in GB (cgroup v2, v1), else the host's; 0 when unknown."""
    for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        raw = _read(path)
        if raw.isdigit() and int(raw) < 2 ** 50:
            return round(int(raw) / 2 ** 30, 1)
    for line in _read("/proc/meminfo").splitlines()[:1]:
        try:
            return round(int(line.split()[1]) / 2 ** 20, 1)
        except (IndexError, ValueError):
            pass
    return 0.0


def encode_threads() -> int:
    """
    x264 threads for one YouTube section's re-encode (ytdlp._encode_args): DOWNLOAD_THREADS, 0 = x264's own choice.

    Measured on a 16-vCPU cpu3c pod (2026-10-26, 12 s 1080p sections, crf 16 medium, N side by side): x264's own
    threads give the best throughput (16 at once 26.5 s; 2 threads 28.7 s; 1 thread 31.8 s; 8 at once: own 13.4 s,
    2 threads 16.2 s) - it fills the cores when fewer downloads run - but at 16 at once its frame buffers took 16.9 GB
    of the pod's 32 (2 threads: 8.6 GB). So the default stays x264's; a smaller machine can set it.
    """
    return max(0, int(getattr(config, "DOWNLOAD_THREADS", 0) or 0))


def source_workers(asked: int) -> int:
    """
    The sourcing threads a pass may run: `asked`, but never more than SOURCE_WORKERS_PER_CPU a core (0 = no clamp).
    A line's pass-1 time is wall-clock (media.scene_seconds), so a line queued behind too many others for the
    network slots, the vision slots or the cores spends its own time waiting and comes back empty.
    """
    asked = max(1, int(asked or 1))
    per = float(getattr(config, "SOURCE_WORKERS_PER_CPU", 0.0) or 0.0)
    if per <= 0:
        return asked
    return max(1, min(asked, int(round(per * cpus()))))


def describe() -> Dict[str, object]:
    """The machine and the values sourcing derived from it (meta.sourcing.machine)."""
    asked = int(getattr(config, "SOURCE_WORKERS", 16) or 16)
    return {"cpus": cpus(), "cgroupCpus": round(cgroup_cpus(), 2) or None, "hostCpus": os.cpu_count(),
            "memoryGb": memory_gb(), "encodeThreads": encode_threads(),
            "sourceWorkers": {"asked": asked, "used": source_workers(asked)},
            "networkSlots": int(getattr(config, "NETWORK_CONCURRENCY", 0) or 0),
            "visionSlots": int(getattr(config, "VISION_CONCURRENCY", 0) or 0)}


# --------------------------------------------------------------------------- #
# How busy the machine was
# --------------------------------------------------------------------------- #

def _cpu_usage_seconds() -> Optional[float]:
    """CPU seconds this container has used (cgroup v2 cpu.stat, v1 cpuacct); None off Linux / unreadable."""
    for line in _read("/sys/fs/cgroup/cpu.stat").splitlines():
        if line.startswith("usage_usec "):
            try:
                return int(line.split()[1]) / 1e6
            except (IndexError, ValueError):
                return None
    raw = _read("/sys/fs/cgroup/cpuacct/cpuacct.usage")
    if raw.isdigit():
        return int(raw) / 1e9
    return None


def _throttled_seconds() -> Optional[float]:
    for line in _read("/sys/fs/cgroup/cpu.stat").splitlines():
        if line.startswith("throttled_usec "):
            try:
                return int(line.split()[1]) / 1e6
            except (IndexError, ValueError):
                return None
    return None


def _proc_stat() -> Optional[tuple]:
    """(busy, total) jiffies from /proc/stat's first line - the host's, used only with no cgroup counter."""
    first = (_read("/proc/stat").splitlines() or [""])[0].split()
    if len(first) < 5 or first[0] != "cpu":
        return None
    try:
        vals = [int(v) for v in first[1:]]
    except ValueError:
        return None
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
    return sum(vals) - idle, sum(vals)


def _mem_available_gb() -> Optional[float]:
    """Memory still free for this container: its limit minus what it uses (cgroup v2), else MemAvailable."""
    limit, used = _read("/sys/fs/cgroup/memory.max"), _read("/sys/fs/cgroup/memory.current")
    if limit.isdigit() and used.isdigit():
        return round((int(limit) - int(used)) / 2 ** 30, 2)
    for line in _read("/proc/meminfo").splitlines():
        if line.startswith("MemAvailable:"):
            try:
                return round(int(line.split()[1]) / 2 ** 20, 2)
            except (IndexError, ValueError):
                return None
    return None


_WATCH = ("ffmpeg", "yt-dlp", "deno", "node")


def _processes() -> Dict[str, int]:
    """How many ffmpeg / yt-dlp / JS-runtime processes run now (yt-dlp is a Python process: its command line)."""
    out = {k: 0 for k in _WATCH}
    try:
        names = os.listdir("/proc")
    except OSError:
        return {}
    for pid in names:
        if not pid.isdigit():
            continue
        comm = _read(f"/proc/{pid}/comm")
        if comm in out:
            out[comm] += 1
        elif comm.startswith("python") or comm == "yt-dlp":
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as fh:
                    head = fh.read(400)
                if b"yt-dlp" in head or b"yt_dlp" in head:
                    out["yt-dlp"] += 1
            except OSError:
                pass
    return out


def _pct(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


class Sampler:
    """
    Samples the machine every `every` seconds on a daemon thread between start() and stop(); summary() is the
    record for meta.sourcing.machine. A machine with no counters (a dev box) gives an empty summary.
    """

    def __init__(self, every: Optional[float] = None):
        self.every = max(1.0, float(every if every is not None else getattr(config, "MACHINE_SAMPLE_SECONDS", 5.0)))
        self.busy: List[float] = []
        self.mem: List[float] = []
        self.procs: Dict[str, List[int]] = {k: [] for k in _WATCH}
        self.started = 0.0
        self.ended = 0.0
        self._t0_throttle: Optional[float] = None
        self._t1_throttle: Optional[float] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cpus = cpus()

    def start(self) -> "Sampler":
        if self._thread is not None:
            return self
        self.started = time.time()
        self._t0_throttle = _throttled_seconds()
        self._thread = threading.Thread(target=self._run, name="machine-sampler", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> "Sampler":
        if self._thread is None or self._stop.is_set():
            return self
        self._stop.set()
        self._thread.join(timeout=self.every + 2.0)
        self.ended = time.time()
        self._t1_throttle = _throttled_seconds()
        return self

    def _run(self) -> None:
        last_use, last_wall, last_stat = _cpu_usage_seconds(), time.time(), _proc_stat()
        while not self._stop.wait(self.every):
            try:
                now = time.time()
                use = _cpu_usage_seconds()
                if use is not None and last_use is not None and now > last_wall:
                    self.busy.append(min(100.0, 100.0 * (use - last_use) / ((now - last_wall) * self._cpus)))
                elif use is None:
                    stat = _proc_stat()
                    if stat and last_stat and stat[1] > last_stat[1]:
                        self.busy.append(100.0 * (stat[0] - last_stat[0]) / (stat[1] - last_stat[1]))
                    last_stat = stat
                last_use, last_wall = use, now
                free = _mem_available_gb()
                if free is not None:
                    self.mem.append(free)
                for k, v in _processes().items():
                    self.procs[k].append(v)
            except Exception:  # noqa: BLE001 - a sample lost, never the job
                continue

    def summary(self) -> Dict[str, object]:
        if not self.busy and not self.mem:
            return {}
        out: Dict[str, object] = {"samples": len(self.busy), "everySeconds": self.every, "cpus": self._cpus,
                                  "seconds": round((self.ended or time.time()) - self.started, 1)}
        if self.busy:
            out["cpuBusyPct"] = {"mean": round(sum(self.busy) / len(self.busy), 1),
                                 "p50": round(_pct(self.busy, 0.5), 1), "p90": round(_pct(self.busy, 0.9), 1),
                                 "max": round(max(self.busy), 1),
                                 "share90Plus": round(sum(1 for b in self.busy if b >= 90.0) / len(self.busy), 3)}
        if self.mem:
            out["memFreeGb"] = {"min": round(min(self.mem), 2), "p10": round(_pct(self.mem, 0.1), 2),
                                "mean": round(sum(self.mem) / len(self.mem), 2)}
        if self._t0_throttle is not None and self._t1_throttle is not None:
            out["throttledSeconds"] = round(self._t1_throttle - self._t0_throttle, 1)
        procs = {k: {"mean": round(sum(v) / len(v), 1), "max": max(v)} for k, v in self.procs.items() if v and max(v)}
        if procs:
            out["processes"] = procs
        return out
