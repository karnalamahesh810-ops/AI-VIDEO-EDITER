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

HOLD_SECONDS = 7 * 86400  # a video's moments stay held this long at most (a plan nobody rendered lets them go)
OVERLAP = 0.3             # seconds of the same frames that count as a reuse (tools/reusecheck.py)
CREATOR_SHOTS = 2         # a person's own channel: at most this many shots a video (tools/channels.py) ...
CREATOR_SHOTS_REPEAT = 1  # ... and this many when an earlier video already used it
PERSONALITY = (           # vloggers and presenters who appear in their own videos, and channels the owner named: never a source
    "Fuel For Travel", "The Trek Planner", "Outdoors with Adam Eakle", "Desert Rat Explorations", "Spa and Tell",
    "Wade Jones Sailing", "Northwind to Alaska", "ChloeTheory", "Craig Niesen", "A Sunny Adventure", "Globetrotter Piya",
    "Roaming with the Ramsays", "Out and About Channel", "Travel Your Way to Happiness", "Packs-a-lot", "Upper Summit",
    "Kim Poonthanitkul", "Lost in Nevada again", "Dude Official", "Fast and Fun Travels", "Mighty Travels Aloft",
    "Donald outdoors", "TRAVIS SPARKS", "American Outback", "Mike Irving", "Big Rig Experience by Mohammad",
    "Rick & Deb - RD Air", "Drone Hypnotics", "Swenk Family", "GoPro", "Full Throttle", "Big Rig Experience by Mohamed El-Hewie",
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
    def __init__(self, moments: Optional[Sequence[Sequence]] = None, project: str = "", held: Optional[Sequence[Sequence]] = None):
        self.project = str(project or "")
        self.moments: List[list] = [list(m) for m in (moments or [])]
        self.held: List[list] = [list(m) for m in (held or [])]     # videos in progress elsewhere: blocked, never saved as used
        self.by_src: Dict[str, List[Tuple[float, float]]] = {}
        for m in self.moments + self.held:
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
        return Ledger(data.get("moments") or [], project, held=_read_holds(owner, channel, project))
    except Exception as e:  # noqa: BLE001
        print(f"[ledger] not read: {type(e).__name__}: {str(e)[:120]}", flush=True)
        return Ledger([], project)


def _holds_prefix(owner: str, channel: str) -> str:
    return f"ledger/v1/{_safe(owner) or 'anon'}/{_safe(channel) or 'all'}.holds/"


def _read_holds(owner: str, channel: str, project: str) -> List[list]:
    """Moments other videos of this customer hold right now (tools/reserve.py): [video, start, end, project]. Two pods of one
    batch never pick the same frames. A hold older than HOLD_SECONDS is dropped."""
    from concurrent.futures import ThreadPoolExecutor
    from . import r2
    prefix = _holds_prefix(owner, channel)
    me = _safe(project)
    rows = [r for r in r2.list_keys(prefix) if r["key"][len(prefix):-5] != me]

    def one(r: dict) -> List[list]:
        try:
            raw = r2.get_bytes(r["key"])
            data = json.loads(raw) if raw else {}
            if time.time() - float(data.get("at") or 0.0) > HOLD_SECONDS:
                r2.delete(r["key"])
                return []
            who = str(data.get("project") or "")
            return [[m[0], m[1], m[2], who] for m in data.get("moments") or [] if len(m) >= 3]
        except Exception:  # noqa: BLE001 - one unreadable hold: the gate before the render still looks
            return []
    if not rows:
        return []
    with ThreadPoolExecutor(8) as ex:
        return [m for got in ex.map(one, rows) for m in got]


def hold(inp: Optional[dict], rows: Sequence[Sequence]) -> bool:
    """This video's moments held for the others of this customer while it is being made (and after: a save that lost a race
    stays visible through its hold)."""
    owner, channel = scope_of(inp)
    project = str((inp or {}).get("project_id") or "")
    if not owner or not project:
        return False
    try:
        from . import r2
        if not r2.enabled():
            return False
        body = json.dumps({"moments": [[bare(r[0]), round(float(r[1]), 2), round(float(r[2]), 2)] for r in rows], "project": project,
                           "at": int(time.time())}, separators=(",", ":")).encode()
        r2.upload_bytes(body, f"{_holds_prefix(owner, channel)}{_safe(project)}.json", deadline=time.time() + 60)
        return True
    except Exception as e:  # noqa: BLE001 - the gate before the render still looks
        print(f"[ledger] hold not saved: {type(e).__name__}: {str(e)[:120]}", flush=True)
        return False


def save(inp: Optional[dict], led: Ledger) -> bool:
    """The ledger with this project's moments, on what the file holds NOW (another pod may have saved since this one read it),
    read back to check it stuck: videos of a batch finish at the same time."""
    owner, channel = scope_of(inp)
    if not owner:
        return False
    try:
        from . import r2
        if not r2.enabled():
            return False
        key = key_for(owner, channel)
        mine = [m for m in led.moments if led.project and len(m) >= 4 and str(m[3]) == led.project]
        for attempt in range(3):
            raw = r2.get_bytes(key)
            data = json.loads(raw) if raw else {}
            merged = Ledger(data.get("moments") or [], led.project)
            merged.moments = [m for m in merged.moments if not (led.project and len(m) >= 4 and str(m[3]) == led.project)] + mine \
                if led.project else (led.moments if not merged.moments else merged.moments + [m for m in led.moments if m not in merged.moments])
            r2.upload_bytes(merged.dumps(), key, deadline=time.time() + 60)
            if not mine:
                return True
            back = r2.get_bytes(key)
            if back and mine[0] in (json.loads(back).get("moments") or []):
                return True
            time.sleep(1.0 + attempt)
        return False
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
