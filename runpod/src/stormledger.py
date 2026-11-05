"""
No moment used twice: the used-moments ledger of a customer (the kit's credits/used_moments.json), one JSON per owner and
channel in R2, so nothing in the app's database changes. Every finished video adds its moments; every new plan reads them
and turns those moments down, and the gate reads them again right before the render.
  ledger/v1/<owner>/<channel or "all">.json   {"moments": [[video id, start, end, project], ...]}
A project's own moments never count against it: a re-render of the same video is not a reuse.
"""
from __future__ import annotations

import json
import re
import time
from typing import Dict, List, Optional, Sequence, Tuple

OVERLAP = 0.3             # seconds of the same frames that count as a reuse (tools/reusecheck.py)
CREATOR_SHOTS = 2         # a person's own channel: at most this many shots a video (tools/channels.py) ...
CREATOR_SHOTS_REPEAT = 1  # ... and this many when an earlier video already used it
PERSONALITY = (           # vloggers and presenters who appear in their own videos, and channels the owner named: never a source
    "Fuel For Travel", "The Trek Planner", "Outdoors with Adam Eakle", "Desert Rat Explorations", "Spa and Tell",
    "Wade Jones Sailing", "Northwind to Alaska", "ChloeTheory", "Craig Niesen", "A Sunny Adventure", "Globetrotter Piya",
    "Roaming with the Ramsays", "Out and About Channel", "Travel Your Way to Happiness", "Packs-a-lot", "Upper Summit",
    "Kim Poonthanitkul", "Lost in Nevada again", "Dude Official", "Fast and Fun Travels", "Mighty Travels Aloft",
    "Donald outdoors", "TRAVIS SPARKS", "American Outback", "Mike Irving", "Big Rig Experience by Mohammad",
)
_VLOG = re.compile(r"\b(vlogs?|vlogging|travels?|adventures?|family|lifestyle|with me|our life|my life|rv life|van life)\b", re.I)


def is_personality(channel: str) -> bool:
    """A vlog or personality channel: on the owner's list, or a name that says so."""
    c = re.sub(r"\s+", " ", str(channel or "")).strip().lower()
    if not c:
        return False
    if any(c == p.lower() or c.startswith(p.lower()) for p in PERSONALITY):
        return True
    return bool(_VLOG.search(c))


def bare(video: str) -> str:
    v = str(video or "")
    return v[3:] if v.startswith("yt:") else v


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(s or "")).strip("-")[:80]


def key_for(owner: str, channel: str = "") -> str:
    return f"ledger/v1/{_safe(owner) or 'anon'}/{_safe(channel) or 'all'}.json"


def scope_of(inp: Optional[dict]) -> Tuple[str, str]:
    """(owner, channel) of a job. No owner (a benchmark, a test): no ledger."""
    inp = inp or {}
    sd = inp.get("storm_desk") if isinstance(inp.get("storm_desk"), dict) else {}
    channel = sd.get("ledger_channel") or inp.get("channel_id") or inp.get("yt_channel_id") or ""
    return str(sd.get("ledger_owner") or inp.get("owner_id") or ""), str(channel)


class Ledger:
    def __init__(self, moments: Optional[Sequence[Sequence]] = None, project: str = ""):
        self.project = str(project or "")
        self.moments: List[list] = [list(m) for m in (moments or [])]
        self.by_src: Dict[str, List[Tuple[float, float]]] = {}
        for m in self.moments:
            if len(m) >= 3 and (len(m) < 4 or not self.project or str(m[3]) != self.project):
                self.by_src.setdefault(bare(m[0]), []).append((float(m[1]), float(m[2])))

    def overlap(self, video: str, a: float, b: float) -> float:
        return max([min(b, q) - max(a, p) for p, q in self.by_src.get(bare(video), [])] + [0.0])

    def used(self, video: str, a: float, b: float) -> bool:
        return self.overlap(video, a, b) > OVERLAP

    def ranges(self, video: str) -> List[Tuple[float, float]]:
        return list(self.by_src.get(bare(video), []))

    def add(self, rows: Sequence[Sequence]) -> None:
        """This project's moments, in place of what it said before (a re-render with swapped shots frees the old ones)."""
        self.moments = [m for m in self.moments if not (self.project and len(m) >= 4 and str(m[3]) == self.project)]
        self.moments += [[bare(r[0]), round(float(r[1]), 2), round(float(r[2]), 2), self.project] for r in rows]

    def dumps(self) -> bytes:
        return json.dumps({"moments": self.moments, "updated": int(time.time())}, separators=(",", ":")).encode()


def load(inp: Optional[dict], project: str = "") -> Ledger:
    """This job's ledger; an empty one without an owner or storage (never fails a job, says so in the log)."""
    owner, channel = scope_of(inp)
    project = project or str((inp or {}).get("project_id") or "")
    if not owner:
        return Ledger([], project)
    try:
        from . import r2
        if not r2.enabled():
            return Ledger([], project)
        raw = r2.get_bytes(key_for(owner, channel))
        data = json.loads(raw) if raw else {}
        return Ledger(data.get("moments") or [], project)
    except Exception as e:  # noqa: BLE001
        print(f"[ledger] not read: {type(e).__name__}: {str(e)[:120]}", flush=True)
        return Ledger([], project)


def save(inp: Optional[dict], led: Ledger) -> bool:
    owner, channel = scope_of(inp)
    if not owner:
        return False
    try:
        from . import r2
        if not r2.enabled():
            return False
        r2.upload_bytes(led.dumps(), key_for(owner, channel), deadline=time.time() + 60)
        return True
    except Exception as e:  # noqa: BLE001 - the video is done; the ledger misses it and says so
        print(f"[ledger] not saved: {type(e).__name__}: {str(e)[:120]}", flush=True)
        return False


def doc_moments(doc: dict, moment_of) -> List[Tuple[str, float, float, int]]:
    """(video, start, end, scene index) of every shot with a known moment."""
    fps = int(doc.get("fps") or 30)
    out = []
    for i, s in enumerate(doc.get("scenes") or []):
        mo = moment_of(s, fps)
        if mo:
            out.append((bare(mo[0]), float(mo[1]), float(mo[2]), i))
    return out


def gate(doc: dict, led: Ledger, moment_of) -> dict:
    """{"earlier": [(shot, video, start, seconds)], "same": [(shot, shot, video)]}: shots that reuse an earlier video's moment
    and shots that show the same frames twice in this one (tools/reusecheck.py)."""
    rows = doc_moments(doc, moment_of)
    earlier, same = [], []
    for k, (v, a, b, i) in enumerate(rows):
        ov = led.overlap(v, a, b)
        if ov > OVERLAP:
            earlier.append((i, v, round(a, 1), round(ov, 1)))
        for v2, c, d, j in rows[k + 1:]:
            if v2 == v and min(b, d) - max(a, c) > OVERLAP:
                same.append((i, j, v))
    return {"earlier": earlier, "same": same}
