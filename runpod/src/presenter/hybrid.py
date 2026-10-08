"""
The AI presenter inside ANY footage style ("hybrid"): the normal ThumbGenius
build - real YouTube clips and real web pictures found and judged line by
line - with a made-up presenter who talks to camera now and then, the way the
AI-avatar channels open and punctuate their videos.

A job turns it on with a presenter block (the app's contract,
docs/ai-presenter-contract.md section 10):

    "presenter": {"presenter_id": "hollis",
                  "presenter_kit": {...},                # the kit itself (used first; the app sends it)
                  "share": 0.14,                         # of the running time: 0.08 light, 0.14 medium (default)
                  "level": "medium",                     # the app's label for the share ("light" | "medium")
                  "split_screen": true,                  # about a third of the middle appearances 50/50
                  "max_seconds": 120,                    # the presenter's whole time on screen at most (default
                                                         # 120, however long the video; split screens count)
                  "budget_usd": 9.0}                     # hard cap on the presenter's paid calls (the app sends
                                                         # min(narration s x share, 120) x $0.05 x 1.5; absent: ours)

Without the block nothing here runs and the build is exactly what it was.

What it does (handler.do_plan calls each step at its place):

  1. select()      after the shot plan: which lines the presenter says on
                   camera - the hook's first sentence, chapter openings, a
                   beat whenever the footage has run ~40 s without one, the
                   close - to the share, each appearance 3.5-7.5 s of whole
                   lines (the references: 3.6-7.3 s, median 5 s), never a line
                   the plan gave a graphic, never a named person's line
                   full-screen (that one may be a split: the person stays on
                   screen beside the presenter). Never past max_seconds in
                   all (the presenter is what costs): a plan that would pass
                   it keeps the opening and the close and spreads the beats
                   between them evenly instead, adding none once the next
                   would pass the cap. A plan within the cap is unchanged.
  2. start()       the appearances are made in the background while the
                   footage search runs: one heygen/avatar-iv take per
                   appearance from its narration window (src/presenter/
                   generate.py: kit framing, checks, the other framing as the
                   retry, the job's budget), cut frame-exact into one clip
                   per line so every line keeps its own scene.
  3. search_jobs() full-screen presenter lines are left out of every footage
                   search (the saving); a split line is searched as always -
                   its real clip or picture is the right half.
  4. wait()        after the search: a full-screen line whose take failed is
                   searched now, like any line (fill_jobs() keeps it in the
                   gap fills after that) - never an AI picture, never an AI
                   clip, never the kit's set: hybrid is real footage plus the
                   presenter and nothing else generated.
  5. for_build()   the presenter's clips go on their lines; a split line's
                   real asset becomes its right half (decorate()).
  6. decorate()    after timeline.build: split frames, the presenter's
                   metadata, hard cuts into and out of the presenter, no
                   effect, no film treatment, no move on the presenter.
  7. finish()      at the end of the plan: no look, graphic or sound effect
                   left over a presenter scene (a look that ran into one from
                   the footage before ends at the cut), meta.presenterHybrid
                   (what was planned and made, what fell back, what it cost),
                   the YouTube disclosure line.

The footage passes (the quality gate, the hook check, the AI review, the
hold-overs, the clip library and the ledger, Replace Clip, re-clip, re-cut,
restore) leave a scene whose media.source is "ai-presenter" alone
(src/presenter/__init__.py is_presenter_scene).
"""
from __future__ import annotations

import math
import os
import re
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .. import config
from . import PRESENTER_SOURCE, is_presenter_scene
from .shotplan import CAP_MARGIN

SHARES = {"light": 0.08, "medium": 0.14}
DEFAULT_SHARE = "medium"            # the reference channels' own ~14%
# The presenter's whole time on screen, however long the video (the owner, 2026-10-08: about two minutes at most -
# the presenter is what costs). Split screens count: they are paid the same. A block's max_seconds sets its own.
MAX_SECONDS = float(os.getenv("PRESENTER_HYBRID_MAX_SECONDS", "120") or 120)
PMIN, PMAX = 3.5, 7.5               # one appearance, seconds of whole lines
HOOK_MAX = 9.0                      # the opening sentence on camera (the references open on the presenter 4-13 s)
MAX_GAP = 40.0                      # the presenter comes back at least this often, while the share allows
MIN_APART = 10.0                    # real footage between two appearances, at least
FRONT_SECONDS = 120.0               # trust is built early (15-35% of the first two minutes in the references)
SPLIT_SHARE = 1.0 / 3.0             # of the middle appearances, with split_screen
CLOSE_MIN_VIDEO = 30.0              # a video shorter than this gets the opening only
PART_TAIL = 0.12                    # seconds each line's clip runs past its scene (never slowed by a frame short)
USD_PER_SECOND = 0.05               # heygen/avatar-iv on OpenRouter, 720p and 1080p
# The longest the build waits for the takes once its footage search is done; a take later than that is
# ignored and its lines keep their footage (a take normally lands in 60-120 s, made beside the search).
WAIT_SECONDS = float(os.getenv("PRESENTER_HYBRID_WAIT_SECONDS", "900") or 900)
# A failed take's lines are searched after the main search, in a box of their own: never the main search's
# 10-minute tail for two lines (the laptop test: the video waited on them). Then the usual fills, as any line.
RETRY_BASE_SECONDS = float(os.getenv("PRESENTER_HYBRID_RETRY_SECONDS", "150") or 150)
RETRY_LINE_SECONDS = 30.0


def retry_seconds(lines: int, ceiling: Optional[float] = None) -> float:
    """The search box for a failed take's lines (never past `ceiling`, the main search's own for that many)."""
    want = RETRY_BASE_SECONDS + RETRY_LINE_SECONDS * max(0, int(lines))
    return min(want, float(ceiling)) if ceiling else want
PAD_SECONDS = 0.9                   # billed per appearance on top of its screen time (0.3 s before + 0.6 s after)
CHECK_USD = 0.002                   # one face check (gemini-2.5-flash, three frames + the master)
RETRY_SHARE = 0.10                  # appearances that need their second take (the other framing)
# The footage build without a presenter, per minute of narration (OpenRouter vision + planner + one CPU
# machine): the cost/quality pass's measured ~$1.66 for 15 minutes (vision ~$0.73, planner ~$0.64, machine
# ~$0.29). Overridable (PRESENTER_HYBRID_NORMAL_PER_MIN) as the ledgers move.
NORMAL_PER_MIN = float(os.getenv("PRESENTER_HYBRID_NORMAL_PER_MIN", "0.11") or 0.11)
VISION_PER_LINE = 0.0073            # what a searched line's vision costs (cost/quality pass, arm B)
DISCLOSURE = ("This video shows an AI-generated presenter (a made-up person, lip-synced to the narration) beside real "
              "footage: tick \"Altered or synthetic content\" in YouTube Studio when uploading.")

_SENTENCE_END = re.compile(r"[.!?][\"'”’)\]]*$")
_CHAPTER = re.compile(
    r"^\s*(now|so|okay|ok|alright|but here|here'?s|here is|first(ly)?|second(ly)?|third(ly)?|next|another|finally|"
    r"lastly|the (first|second|third|next|last|real|other|big|biggest) (thing|step|trick|reason|way|secret|mistake|"
    r"rule|part|problem|question)|step (one|two|three|four|five|\d+)|number (one|two|three|four|five|\d+))\b", re.I)
_FIRST = re.compile(r"\b(i|i'?ve|i'?m|i'?d|my|me|we|we'?d|our|us)\b", re.I)
_YOU = re.compile(r"\b(you|your|yours|y'?all|folks)\b", re.I)
_WHY = re.compile(r"\b(why|because|the reason|matters?|important|here'?s the thing|the truth|worr\w*|remember|"
                  r"listen|trust me|never|always|tell me|comments?)\b", re.I)
_NUMBER = re.compile(r"\d|\b(hundred|thousand|million|billion|percent|half|twice|dozen)\b", re.I)


# Hybrid is real footage plus the presenter and nothing else generated: no AI pictures in the search, the gap
# fills or a Replace Clip, and no cold-open flashes over the presenter's opening line (handler.handler merges
# these over the job's own config; the job cannot turn them back on).
FORCED_CONFIG = {"IMAGE_MAX_PER_VIDEO": 0, "PREFER_GENERATED_IMAGES": False, "GENERATED_IMAGES_IN_HOOK": False,
                 "HOOK_TEASER": False}


def force_config(inp: Dict[str, Any]) -> None:
    """The job's config with FORCED_CONFIG over it (in place)."""
    cfg = dict(inp["config"]) if isinstance(inp.get("config"), dict) else {}
    cfg.update(FORCED_CONFIG)
    inp["config"] = cfg


def is_hybrid_doc(doc: Any) -> bool:
    """A timeline built with a presenter block (meta.presenterHybrid)."""
    meta = doc.get("meta") if isinstance(doc, dict) else None
    return isinstance(meta, dict) and isinstance(meta.get("presenterHybrid"), dict)


# ------------------------------------------------------------------ the job's block
def block(inp: Optional[dict]) -> Optional[Dict[str, Any]]:
    """
    The job's presenter block, normalised, or None (no block, switched off, or
    the AI presenter style itself - that style is all presenter, not hybrid).
    """
    inp = inp or {}
    raw = inp.get("presenter")
    if not isinstance(raw, dict) or not raw or raw.get("enabled") is False:
        return None
    from .. import styles
    if styles.resolve(inp.get("video_style")) == "ai_presenter":
        return None
    out = dict(raw)
    # The app sends the share as a number and its level as a label (docs/ai-presenter-contract.md section 10);
    # a level alone, or a share named by its level, reads the same.
    level = str(raw.get("level") or "").strip().lower()
    given = raw.get("share")
    if given in (None, "") and level in SHARES:
        given = level
    out["share_name"], out["share"] = share_of(given)
    if level in SHARES and out["share_name"] == "custom":
        out["share_name"] = level                   # the label as the app shows it; the number is what is used
    out["split_screen"] = raw.get("split_screen", raw.get("split", True)) not in (False, 0, "0", "false", "no", "off")
    out["max_seconds"] = max_seconds_of(raw.get("max_seconds"))
    try:
        out["budget_usd"] = max(0.0, float(raw.get("budget_usd"))) if raw.get("budget_usd") not in (None, "") else None
    except (TypeError, ValueError):
        out["budget_usd"] = None
    return out


def max_seconds_of(value: Any) -> float:
    """The cap on the presenter's whole time on screen (seconds): a positive number, else MAX_SECONDS."""
    if isinstance(value, bool):
        return MAX_SECONDS
    try:
        x = float(value)
    except (TypeError, ValueError):
        return MAX_SECONDS
    return x if math.isfinite(x) and x > 0 else MAX_SECONDS


def share_of(value: Any) -> Tuple[str, float]:
    """("light" | "medium" | "custom", share of the running time): a name, or a number 0.02-0.30 to A/B one job."""
    if isinstance(value, str) and value.strip().lower() in SHARES:
        name = value.strip().lower()
        return name, SHARES[name]
    try:
        x = float(value)
    except (TypeError, ValueError):
        return DEFAULT_SHARE, SHARES[DEFAULT_SHARE]
    if x > 1.0:
        x /= 100.0                                  # "12" = 12%
    x = round(max(0.02, min(0.30, x)), 3)
    named = next((k for k, v in SHARES.items() if abs(v - x) < 1e-9), "custom")
    return named, x


def kit_request(blk: Dict[str, Any], inp: Optional[dict] = None) -> Dict[str, Any]:
    """The block as src/presenter/kits.for_job reads a job (the same kit fields as the AI presenter style)."""
    inp = inp or {}
    req: Dict[str, Any] = {}
    kid = blk.get("presenter_id") or blk.get("id")
    if kid:
        req["presenter_id"] = str(kid)
    if isinstance(blk.get("presenter_kit") or blk.get("kit"), dict):
        req["presenter_kit"] = blk.get("presenter_kit") or blk.get("kit")
    cat = blk.get("presenter_catalogue", blk.get("catalogue"))
    if isinstance(cat, (dict, list)):
        req["presenter_catalogue"] = cat
    elif isinstance(cat, str) and cat.strip().startswith("https://"):
        req["presenter_catalogue_url"] = cat.strip()
    url = blk.get("presenter_catalogue_url") or blk.get("catalogue_url")
    if isinstance(url, str) and url.strip().startswith("https://"):
        req["presenter_catalogue_url"] = url.strip()
    base = blk.get("presenter_base_url") or blk.get("base_url") or inp.get("presenter_base_url")
    if base:
        req["presenter_base_url"] = str(base)
    return req


# ------------------------------------------------------------------ which lines
@dataclass
class Line:
    index: int
    text: str
    start: float                    # on screen from (its scene's first frame / fps)
    end: float                      # to (the next scene's first frame / fps)
    full_ok: bool = True            # may be the presenter full-screen
    split_ok: bool = True           # may be a split (the presenter beside the line's real visual)
    why_not: str = ""
    hint_only: bool = False         # kept off only for the planner's graphic hint (the opening takes it anyway)
    about_presenter: bool = False   # the line is about the presenter (their name was its subject): theirs to say

    @property
    def seconds(self) -> float:
        return self.end - self.start

    @property
    def ends_sentence(self) -> bool:
        return bool(_SENTENCE_END.search((self.text or "").strip()))


@dataclass
class Appearance:
    lines: List[int]
    start: float
    end: float
    role: str                       # hook | chapter | beat | close
    split: bool = False
    framing: str = ""
    id: str = ""
    reason: str = ""
    needs_split: bool = False       # holds a line that must keep its real visual on screen (a named person)

    @property
    def seconds(self) -> float:
        return self.end - self.start

    def as_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "lines": list(self.lines), "start": round(self.start, 3), "end": round(self.end, 3),
                "seconds": round(self.seconds, 3), "role": self.role, "split": self.split, "framing": self.framing,
                "reason": self.reason}


def frame_bounds(segments: Sequence[Any], duration: float, fps: int) -> List[int]:
    """The scenes' frame boundaries exactly as timeline.build will lay them (timeline._scene_bounds)."""
    from .. import timeline
    total = max(1, int(round(float(duration) * fps)))
    return timeline._scene_bounds(list(segments), fps, total)


def _eligibility(line: Line, shot: Dict[str, Any]) -> None:
    """A line keeps its real visual when the plan gave it something only footage can show."""
    shot = shot or {}
    line.about_presenter = bool(shot.get("aboutPresenter"))
    if shot.get("overlay"):
        line.full_ok = line.split_ok = False
        line.why_not = "a graphic is planned on it"
        line.hint_only = str(shot.get("subjectType") or "") not in ("person", "document") and             str(shot.get("visualType") or "") != "animation"
    elif str(shot.get("visualType") or "") == "animation":
        line.full_ok = line.split_ok = False
        line.why_not = "a full-screen graphic is planned"
    elif str(shot.get("subjectType") or "") in ("person", "document"):
        line.full_ok = False                        # the named person / the document stays on screen: split only
        line.why_not = f"shows a {shot.get('subjectType')}"
    if line.seconds < 0.5:
        line.full_ok = line.split_ok = False
        line.why_not = line.why_not or "too short"


def _fit(line: Line, index: int, count: int) -> float:
    """How much a line wants the presenter on camera (the AI presenter style's rules, src/presenter/shotplan)."""
    t = line.text or ""
    fit = 0.15 + 0.35 * bool(_WHY.search(t)) + 0.25 * bool(_FIRST.search(t)) + 0.15 * bool(_YOU.search(t))
    if _CHAPTER.search(t):
        fit += 0.3
    if _NUMBER.search(t):
        fit -= 0.15                                 # its number or date looks belong on footage
    if line.about_presenter:
        fit += 0.35                                 # "My name is ...": the presenter on camera, not a search for them
    return max(0.0, min(1.5, fit))


class Selector:
    """The presenter's appearances on a footage timeline: see the module notes."""

    def __init__(self, lines: List[Line], total: float, *, share: float, split: bool,
                 framings: Sequence[str] = ("master",), chapters: Iterable[int] = (),
                 pmin: float = PMIN, pmax: float = PMAX, hook_max: float = HOOK_MAX, max_gap: float = MAX_GAP,
                 min_apart: float = MIN_APART, max_seconds: Optional[float] = MAX_SECONDS):
        self.lines, self.total = lines, float(total)
        self.share, self.split = float(share), bool(split)
        self.framings = list(framings) or ["master"]
        self.chapters = set(int(c) for c in chapters)
        self.pmin, self.pmax, self.hook_max = pmin, max(pmin, pmax), max(pmax, hook_max)
        self.max_gap, self.min_apart = max_gap, min_apart
        # The presenter's whole time on screen at most, split screens included (None: the share alone decides).
        self.max_seconds = float(max_seconds) if max_seconds and float(max_seconds) > 0 else None
        self.picked: List[Appearance] = []
        self.notes: List[str] = []                  # why a hook or a close was left out; the cap, when it held
        self.capped: Optional[Dict[str, Any]] = None    # the share's plan went past max_seconds: by how much

    # ---- helpers
    def _ok(self, i: int) -> bool:
        ln = self.lines[i]
        return ln.full_ok or (self.split and ln.split_ok)

    def _used(self) -> float:
        return sum(a.seconds for a in self.picked)

    def _clear(self, a: float, b: float) -> bool:
        """[a, b] keeps min_apart of real footage from every appearance."""
        return all(not (a < x.end + self.min_apart - 1e-6 and b > x.start - self.min_apart + 1e-6) for x in self.picked)

    def _taken(self) -> Set[int]:
        return {i for ap in self.picked for i in ap.lines}

    def _make(self, idx: List[int], role: str, reason: str, force: bool = False) -> Optional[Appearance]:
        if not idx:
            return None
        lines = [self.lines[i] for i in idx]
        if not force and any(not self._ok(i) for i in idx):
            return None
        return Appearance(lines=list(idx), start=lines[0].start, end=lines[-1].end, role=role, reason=reason,
                          needs_split=any(not ln.full_ok and not ln.hint_only for ln in lines))

    def _forward(self, i: int, cap: Optional[float] = None) -> List[int]:
        """Whole lines from i: at least pmin, at most cap (pmax), ending on a sentence end when one is in reach."""
        cap = self.pmax if cap is None else cap
        n = len(self.lines)
        if not self._ok(i) or self.lines[i].seconds > cap + 1e-6:
            return []
        idx = [i]
        while True:
            span = self.lines[idx[-1]].end - self.lines[i].start
            done = span >= self.pmin - 1e-6 and self.lines[idx[-1]].ends_sentence
            if done:
                break
            nxt = idx[-1] + 1
            if nxt >= n or not self._ok(nxt) or self.lines[nxt].end - self.lines[i].start > cap + 1e-6:
                break
            idx.append(nxt)
        span = self.lines[idx[-1]].end - self.lines[i].start
        if span < min(self.pmin, 2.0) - 1e-6:
            return []
        # Ran past the sentence end to reach pmin, but a shorter run already ends a sentence above 2.5 s: keep that.
        for k in range(len(idx) - 1):
            j = idx[k]
            if self.lines[j].ends_sentence and self.lines[j].end - self.lines[i].start >= 2.5 and span > self.pmax:
                return idx[:k + 1]
        return idx

    def _hook_lines(self) -> List[int]:
        """The first sentence's whole lines (up to hook_max), each one the presenter may say (a graphic hint too)."""
        ok = lambda k: self.lines[k].full_ok or self.lines[k].hint_only    # noqa: E731
        if not ok(0) or self.lines[0].seconds > self.hook_max + 1e-6:
            return []
        idx = [0]
        while not (self.lines[idx[-1]].ends_sentence and self.lines[idx[-1]].end >= self.pmin - 1e-6):
            nxt = idx[-1] + 1
            if nxt >= len(self.lines) or not ok(nxt) or self.lines[nxt].end - self.lines[0].start > self.hook_max + 1e-6:
                break
            idx.append(nxt)
        return idx if self.lines[idx[-1]].end >= min(self.pmin, 2.0) - 1e-6 else []

    def _backward(self, j: int) -> List[int]:
        """Whole lines ending at j: the last sentence, at least pmin when the line before fits within pmax - the
        sign-off, which (like the opening) the planner's graphic hint gives way to."""
        ok = lambda k: self.lines[k].full_ok or self.lines[k].hint_only    # noqa: E731
        if not ok(j) or self.lines[j].seconds > self.pmax + 1e-6:
            return []
        idx = [j]
        while idx[0] - 1 >= 0:
            prv = idx[0] - 1
            span = self.lines[j].end - self.lines[idx[0]].start
            if self.lines[prv].ends_sentence and span >= self.pmin - 1e-6:
                break
            if not ok(prv) or self.lines[j].end - self.lines[prv].start > self.pmax + 1e-6:
                break
            idx.insert(0, prv)
        if self.lines[j].end - self.lines[idx[0]].start < min(self.pmin, 2.0) - 1e-6:
            return []
        return idx

    def _score(self, i: int) -> float:
        ln = self.lines[i]
        mid = (ln.start + ln.end) / 2
        far = min((abs(mid - (a.start + a.end) / 2) for a in self.picked), default=self.total)
        bonus = 0.4 if i in self.chapters or _CHAPTER.search(ln.text or "") else 0.0
        early = 0.2 if mid < FRONT_SECONDS else 0.0
        spread = min(1.0, far / max(self.max_gap, 1.0)) * 0.4
        full = 0.0 if ln.full_ok else -0.25         # a split-only line comes after the lines the presenter can say alone
        return _fit(ln, i, len(self.lines)) + bonus + early + spread + full

    def _add(self, ap: Optional[Appearance]) -> bool:
        if ap is None or not self._clear(ap.start, ap.end) or set(ap.lines) & self._taken():
            return False
        if ap.needs_split and not self.split:
            return False
        self.picked.append(ap)
        self.picked.sort(key=lambda a: a.start)
        return True

    # ---- the plan
    def plan(self) -> List[Appearance]:
        n = len(self.lines)
        if n == 0 or self.share <= 0 or self.total <= 0:
            return []
        self._anchors()
        anchors = list(self.picked)
        self._to_share()
        self._splits()
        # The presenter is what costs: a plan past max_seconds in all (a long video) keeps its opening and close,
        # and the beats between them are spread evenly to the cap instead. Within the cap the plan is as it was.
        if self.max_seconds is not None and self._used() > self.max_seconds + 1e-6:
            self._cap(anchors)
        for k, ap in enumerate(self.picked):
            ap.framing = self.framings[k % len(self.framings)]
            ap.id = f"h{k:02d}"
        return list(self.picked)

    def _anchors(self) -> None:
        """The opening and the sign-off: the two appearances every plan keeps (when their lines allow)."""
        n = len(self.lines)
        # The hook: the opening sentence, on camera - the planner's graphic hint on it gives way (nothing is laid
        # over the presenter); a line that must show its person, document or full-screen graphic keeps the opening.
        hook = self._hook_lines()
        if hook:
            self._add(self._make(hook, "hook", "the opening sentence", force=True))
        else:
            ln = self.lines[0]
            self.notes.append(f"no opening appearance: the first line {ln.why_not or 'keeps its footage'}")
        # The close: the last sentence - when the video has room for real footage in between.
        if self.total >= CLOSE_MIN_VIDEO and n > 2:
            back = self._backward(n - 1)
            if back:
                self._add(self._make(back, "close", "the sign-off", force=True))
            else:
                ln = self.lines[n - 1]
                why = ln.why_not or ("is longer than one appearance" if ln.seconds > self.pmax else "keeps its footage")
                self.notes.append(f"no closing appearance: the last line {why}")

    def _to_share(self) -> None:
        """Between the opening and the close: chapter openings and lines said to the viewer, then the presenter
        back after every long stretch of footage, to the share."""
        n = len(self.lines)
        target = self.share * self.total
        # Chapter openings and the lines most said to the viewer: best first, spread out, to the share.
        tried: Set[int] = set()
        while self._used() < target - 0.5 * self.pmin:
            order = sorted((i for i in range(n) if i not in tried and i not in self._taken()), key=self._score,
                           reverse=True)
            added = False
            for i in order:
                tried.add(i)
                ln = self.lines[i]
                if not (i in self.chapters or _CHAPTER.search(ln.text or "")) and self._score(i) < 0.75:
                    continue
                if self._add(self._make(self._forward(i), "chapter" if (i in self.chapters or _CHAPTER.search(
                        ln.text or "")) else "beat", "a chapter opening" if (i in self.chapters or _CHAPTER.search(
                            ln.text or "")) else "said to the viewer")):
                    added = True
                    break
            if not added:
                break
        # The presenter comes back whenever the footage has run max_gap without them (while the share allows a
        # little more): the best line in the middle of each long stretch.
        changed = True
        while changed and self._used() < target * 1.3:
            changed = False
            edges = [(0.0, 0.0)] + [(a.start, a.end) for a in self.picked] + [(self.total, self.total)]
            for (_s0, e0), (s1, _e1) in zip(edges, edges[1:]):
                if s1 - e0 <= self.max_gap:
                    continue
                inside = [i for i in range(n) if self.lines[i].start >= e0 + self.min_apart - 1e-6
                          and self.lines[i].end <= s1 - self.min_apart + 1e-6]
                mid = (e0 + s1) / 2
                for i in sorted(inside, key=lambda i: (self._score(i) - abs((self.lines[i].start + self.lines[i].end)
                                                                          / 2 - mid) / max(s1 - e0, 1.0)),
                                reverse=True):
                    chapter = i in self.chapters or bool(_CHAPTER.search(self.lines[i].text or ""))
                    if self._add(self._make(self._forward(i), "chapter" if chapter else "beat",
                                            "a chapter opening, after a long stretch of footage" if chapter
                                            else "comes back after a long stretch of footage")):
                        changed = True
                        break
                if changed:
                    break

    def _cap(self, anchors: List[Appearance]) -> None:
        """
        The share's plan went past max_seconds: keep the opening and the
        close, then one beat near each evenly spaced mark between them (the
        best line there, a chapter opening first) while it fits the cap, then
        one more in the longest stretch of footage while one fits. Split
        screens count (they are paid the same).
        """
        asked = self._used()
        middle = [a.seconds for a in self.picked if a.role not in ("hook", "close")]
        typical = sum(middle) / len(middle) if middle else (self.pmin + self.pmax) / 2.0
        cap = float(self.max_seconds or 0.0)
        self.picked = sorted(anchors, key=lambda a: a.start)
        lo = max((a.end for a in anchors if a.role == "hook"), default=0.0)
        hi = min((a.start for a in anchors if a.role == "close"), default=self.total)
        room = cap - self._used()
        count = int(room / (typical * CAP_MARGIN)) if room > 0 else 0
        if count > 0 and hi > lo:
            step = (hi - lo) / (count + 1)
            for k in range(1, count + 1):
                mark = lo + step * k
                self._near(mark, mark - step / 2.0, mark + step / 2.0, step, cap)
        while self._fill_longest(cap):
            pass
        self._splits()
        self.capped = {"askedSeconds": round(asked, 1), "maxSeconds": cap, "seconds": round(self._used(), 1),
                       "appearances": len(self.picked)}
        self.notes.append(f"the share asked for {asked:.0f} s of presenter, past the cap of {cap:.0f} s: the opening, "
                          f"the close and evenly spaced beats, {self._used():.0f} s in {len(self.picked)} appearance(s)")

    def _near(self, mark: float, lo: float, hi: float, width: float, cap: float) -> bool:
        """One appearance from the best line whose middle is in [lo, hi] (nearest `mark` first, a chapter opening
        ahead of the rest), when it fits under `cap`. True when one was added."""
        taken = self._taken()
        used = self._used()

        def mid(i: int) -> float:
            return (self.lines[i].start + self.lines[i].end) / 2.0
        lines = [i for i in range(len(self.lines)) if i not in taken and self._ok(i) and lo - 1e-6 <= mid(i) <= hi + 1e-6]
        for i in sorted(lines, key=lambda i: self._score(i) - abs(mid(i) - mark) / max(width, 1.0), reverse=True):
            chapter = i in self.chapters or bool(_CHAPTER.search(self.lines[i].text or ""))
            ap = self._make(self._forward(i), "chapter" if chapter else "beat",
                            "a chapter opening" if chapter else "an evenly spaced beat (the presenter's time is capped)")
            if ap is None or used + ap.seconds > cap + 1e-6:
                continue
            if self._add(ap):
                return True
        return False

    def _fill_longest(self, cap: float) -> bool:
        """What the cap still has room for: one more beat in the longest stretch of footage that can take one.
        True when one was added."""
        if self._used() + min(self.pmin, 2.0) > cap + 1e-6:
            return False
        edges = [(0.0, 0.0)] + [(a.start, a.end) for a in self.picked] + [(self.total, self.total)]
        gaps = sorted(((s1 - e0, e0, s1) for (_s0, e0), (s1, _e1) in zip(edges, edges[1:])), reverse=True)
        for length, e0, s1 in gaps:
            if length < 2 * self.min_apart + min(self.pmin, 2.0):
                break
            if self._near((e0 + s1) / 2.0, e0, s1, length, cap):
                return True
        return False

    def _splits(self) -> None:
        """About a third of the middle appearances as a split screen (never the hook or the close): those holding
        a line that must keep its real visual first, then every third one. Without split_screen: none."""
        middle = [a for a in self.picked if a.role not in ("hook", "close")]
        if not self.split or not middle:
            self.picked = [a for a in self.picked if not a.needs_split]
            return
        want = int(math.ceil(SPLIT_SHARE * len(middle) - 1e-9))
        for a in middle:
            if a.needs_split:
                a.split = True
        left = want - sum(1 for a in middle if a.split)
        for k, a in enumerate(middle):
            if left <= 0:
                break
            if not a.split and (k % 3 == 1 or len(middle) - k <= left):
                a.split = True
                left -= 1
        for a in middle:
            if a.split and any(not self.lines[i].split_ok for i in a.lines):
                a.split = False                     # a line no picture may share (a planned graphic): never split
        self.picked = [a for a in self.picked if not (a.needs_split and not a.split)]


def chapter_lines(brief: Optional[dict], count: int) -> Set[int]:
    """The story's own section starts (the planner's brief), as chapter openings."""
    out: Set[int] = set()
    for sec in (brief or {}).get("sections") or []:
        try:
            k = int(sec.get("from"))
        except (TypeError, ValueError, AttributeError):
            continue
        if 0 < k < count:
            out.add(k)
    return out


def plan_lines(segments: Sequence[Any], shots: Sequence[dict], duration: float, fps: int) -> Tuple[List[Line], float]:
    """Every line with its on-screen span (the timeline's own frame bounds) and what it may be; the video's length."""
    segs = list(segments)
    if not segs:
        return [], 0.0
    bounds = frame_bounds(segs, duration, fps)
    lines = []
    for i, s in enumerate(segs):
        ln = Line(index=i, text=str(getattr(s, "text", "") or ""), start=bounds[i] / fps, end=bounds[i + 1] / fps)
        _eligibility(ln, shots[i] if i < len(shots) else {})
        lines.append(ln)
    return lines, bounds[-1] / fps


def select(segments: Sequence[Any], shots: Sequence[dict], duration: float, *, fps: int, share: float,
           split: bool, framings: Sequence[str] = ("master",), brief: Optional[dict] = None,
           max_seconds: Optional[float] = MAX_SECONDS) -> List[Appearance]:
    """The presenter's appearances for a footage plan (whole lines, frame-exact spans): see the module notes."""
    lines, total = plan_lines(segments, shots, duration, fps)
    if not lines:
        return []
    return Selector(lines, total, share=share, split=split, framings=framings,
                    chapters=chapter_lines(brief, len(lines)), max_seconds=max_seconds).plan()


def take_usd(seconds: float, appearances: int = 1) -> float:
    """What takes of this many screen seconds are billed (each 0.9 s over its screen time) plus their face checks."""
    return (float(seconds) + PAD_SECONDS * appearances) * USD_PER_SECOND + CHECK_USD * appearances


def fit_budget(appearances: List[Appearance], cap: Optional[float]) -> Tuple[List[Appearance], List[Appearance]]:
    """
    (kept, dropped): the plan within the job's cap - every take once, plus
    one retry of the dearest (the other framing, when a take fails its
    check) - so a tight cap leaves out the least needed middle appearance
    (the latest first) rather than refusing whichever take comes last, or
    the retry that would have saved the opening (the hybrid laptop test).
    The close goes before the hook.
    """
    keep = list(appearances)
    dropped: List[Appearance] = []
    if cap is None:
        return keep, dropped

    def cost(aps: List[Appearance]) -> float:
        return sum(take_usd(a.seconds) for a in aps) + max((take_usd(a.seconds) for a in aps), default=0.0)
    order = ([a for a in reversed(keep) if a.role not in ("hook", "close")]
             + [a for a in keep if a.role == "close"] + [a for a in keep if a.role == "hook"])
    for a in order:
        if cost(keep) <= float(cap) + 1e-9:
            break
        keep.remove(a)
        dropped.append(a)
    return keep, dropped


# ------------------------------------------------------------------ the estimate
def estimate(minutes: float, share: Any = DEFAULT_SHARE, *, split_screen: bool = True,
             max_seconds: Optional[float] = MAX_SECONDS) -> Dict[str, Any]:
    """
    What a hybrid video costs: the normal footage build + presenter seconds
    (share x length, never past max_seconds) x $0.05 (heygen/avatar-iv; each
    appearance is billed 0.9 s over its screen time for the lip-sync lead-in
    and tail, ~10% need a second take) + a face check per take - less the
    vision of the full-screen presenter lines no one searches.
    """
    name, frac = share_of(share)
    m = max(0.0, float(minutes or 0.0))
    asked = m * 60.0 * frac
    seconds = min(asked, float(max_seconds)) if max_seconds and float(max_seconds) > 0 else asked
    appearances = seconds / 5.0
    billed = (seconds + PAD_SECONDS * appearances) * (1.0 + RETRY_SHARE)
    presenter = billed * USD_PER_SECOND
    checks = appearances * (1.0 + RETRY_SHARE) * CHECK_USD
    normal = NORMAL_PER_MIN * m
    full = seconds * ((1.0 - SPLIT_SHARE * 0.8) if split_screen else 1.0)
    saved = full / 4.0 * VISION_PER_LINE                  # one footage line per ~4 s never searched
    total = normal + presenter + checks - saved
    return {"minutes": m, "share": name, "shareOfTime": frac, "usd": round(total, 2),
            "parts": {"normalBuild": round(normal, 2), "presenter": round(presenter, 2), "checks": round(checks, 3),
                      "searchSaved": round(-saved, 3)},
            "presenterSeconds": round(seconds), "capped": seconds < asked - 1e-9,
            "billedSeconds": round(billed), "appearances": int(math.ceil(appearances)),
            "formula": "normal build + presenter seconds (share x length, at most max_seconds) x $0.05 (+0.9 s a "
                       "take, ~10% retakes) + face checks"}


def estimate_table(minutes: Iterable[float] = (10, 15, 20)) -> Dict[str, Any]:
    """presenter_info's "hybrid": $ per 10/15/20-minute video at light and medium."""
    lengths = [float(x) for x in minutes]
    by = {name: {str(int(x) if x.is_integer() else x): estimate(x, name) for x in lengths} for name in SHARES}
    return {"shares": dict(SHARES), "defaultShare": DEFAULT_SHARE, "usdPerPresenterSecond": USD_PER_SECOND,
            "maxSeconds": MAX_SECONDS, "normalBuildPerMinute": NORMAL_PER_MIN, "byShare": by,
            "note": f"Real footage everywhere else; nothing else generated. The presenter is on screen {MAX_SECONDS:.0f} s "
                    "at most, however long the video (split screens count). The job records what each call really "
                    "cost (meta.costs, meta.presenterHybrid.costs)."}


# ------------------------------------------------------------------ the presenter's shots, beside the search
@dataclass
class Made:
    appearance: Appearance
    asset: Any = None               # the take (src/presenter/generate.Asset) or None
    parts: Dict[int, Any] = field(default_factory=dict)      # line -> MediaAsset (one clip per line)
    why: str = ""


class Hybrid:
    """One job's presenter: the plan, the takes being made, and what goes on the timeline."""

    def __init__(self, *, inp: Dict[str, Any], blk: Dict[str, Any], kit: Optional[dict], appearances: List[Appearance],
                 spans: Dict[int, Tuple[float, float]], duration: float, fps: int, work: str,
                 warnings: Optional[List[str]] = None):
        self.inp, self.blk, self.kit = inp, blk, kit
        self.appearances = appearances
        self.line_spans = dict(spans)               # line -> (start, end) seconds on screen
        self.count, self.duration, self.fps, self.work = len(spans), float(duration), int(fps), work
        self.warnings = list(warnings or [])
        self.made: Dict[str, Made] = {ap.id: Made(ap) for ap in appearances}
        self.budget = None
        self.gen = None
        self.store = None
        self.cache = None
        self.checker = None
        self.est: Dict[str, Any] = {}
        self._thread: Optional[threading.Thread] = None
        self._waited = False
        self._closed = False                        # past the wait: a late take is not used
        self.started = time.time()
        self.seconds = 0.0
        self.searched_after: List[int] = []
        self.halves: Dict[int, Any] = {}
        self.dropped: List[Dict[str, Any]] = []         # planned, left out to fit the cap (their lines keep footage)
        self.capped: Optional[Dict[str, Any]] = None    # the share asked for more than max_seconds (Selector.capped)
        self.log: List[str] = []

    # ---- which lines
    def lines_of(self, *, split: Optional[bool] = None) -> Set[int]:
        return {i for ap in self.appearances if split is None or ap.split == split for i in ap.lines}

    def full_lines(self) -> Set[int]:
        """Full-screen presenter lines as planned (searched by no one)."""
        return self.lines_of(split=False)

    def search_jobs(self, jobs: List[dict]) -> List[dict]:
        """The footage search's lines: every line but the full-screen presenter's."""
        skip = self.full_lines()
        return [j for j in jobs if j["index"] not in skip] if skip else jobs

    def settled(self) -> Set[int]:
        """Lines that have their presenter clip (after wait())."""
        return {i for m in self.made.values() for i in m.parts}

    def failed_full(self) -> List[int]:
        """Full-screen presenter lines whose take failed: they go back to the footage search."""
        return sorted(i for m in self.made.values() if not m.appearance.split and not m.parts
                      for i in m.appearance.lines)

    def fill_jobs(self, jobs: List[dict]) -> List[dict]:
        """The gap fills' lines after wait(): every line but a full-screen line the presenter says."""
        skip = {i for m in self.made.values() if not m.appearance.split for i in m.parts}
        return [j for j in jobs if j["index"] not in skip] if skip else jobs

    # ---- making the takes
    def _note(self, msg: str) -> None:
        print(f"[hybrid] {msg}", flush=True)
        self.log.append(msg[:300])

    def begin(self, narration_path: str, *, provider=None, store=None, cache_dir: str = "") -> None:
        """Start making every appearance in the background (returns at once)."""
        if not self.appearances or self.kit is None:
            return
        from . import providers, tiers
        from .budget import Budget
        from .checks import Checker
        from .generate import Generator
        from .store import Cache, Store
        from . import media_io
        provider = provider or providers.get()
        if not provider.available():
            self.warnings.append("The AI presenter needs the OpenRouter key on this worker: the video was made "
                                 "with real footage only.")
            for m in self.made.values():
                m.why = "no OpenRouter key"
            self.appearances = []
            self.made = {}
            return
        max_s = max_seconds_of(self.blk.get("max_seconds"))
        self.est = estimate(self.duration / 60.0, self.blk.get("share"), split_screen=bool(self.blk.get("split_screen")),
                            max_seconds=max_s)
        cap = self.blk.get("budget_usd")
        if cap is None:
            env = os.getenv("PRESENTER_BUDGET_USD", "").strip()
            try:
                cap = float(env) if env else None
            except ValueError:
                cap = None
        if cap is None:
            planned = sum(ap.seconds for ap in self.appearances)
            # The app's own rule (min(narration seconds x share, max_seconds) x $0.05 x 1.5), never under every
            # planned take once more (the other framing) with its checks.
            asked = min(self.duration * float(self.blk.get("share") or 0.0), max_s)
            cap = max(0.5, round(asked * USD_PER_SECOND * 1.5, 2),
                      round(take_usd(planned, len(self.appearances)) * 1.6, 2))
        self.appearances, over = fit_budget(self.appearances, cap)
        for ap in over:
            self._note(f"{ap.id} ({ap.role}, lines {ap.lines[0]}-{ap.lines[-1]}) left out: the cap ${cap:.2f} "
                       "does not cover it; its lines keep their footage")
        self.dropped = [ap.as_dict() for ap in over]
        self.made = {ap.id: Made(ap) for ap in self.appearances}
        if not self.appearances:
            return
        planned = sum(ap.seconds for ap in self.appearances)
        self.budget = Budget(cap)
        project_id = str(self.inp.get("project_id") or "")
        self.store = store or Store(project_id, str(self.inp.get("_job_id") or ""))
        cache_dir = cache_dir or os.getenv("PRESENTER_CACHE_DIR", "").strip() or os.path.join(self.work, "presenter_cache")
        self.cache = Cache(cache_dir, self.store if project_id else None)
        self.checker = Checker(provider, self.budget, self.work)
        tier = tiers.resolve("budget")
        os.makedirs(self.work, exist_ok=True)
        wav = media_io.to_wav(narration_path, os.path.join(self.work, "presenter_narration_24k.wav"))
        self.gen = Generator(provider=provider, budget=self.budget, tier=tier, kit=self.kit, work=self.work,
                             store=self.store, cache=self.cache, checker=self.checker, narration_wav=wav,
                             total=self.duration, bible={}, still_fallback=False)
        self._note(f"{len(self.appearances)} appearance(s), {planned:.1f} s on camera "
                   f"({planned / max(self.duration, 1e-6):.0%} of {self.duration:.0f} s, at most {max_s:.0f} s), "
                   f"cap ${cap:.2f}: "
                   + ", ".join(f"{ap.id} {ap.role}{' split' if ap.split else ''} lines {ap.lines[0]}-{ap.lines[-1]}"
                               for ap in self.appearances))
        self._thread = threading.Thread(target=self._make_all, name="presenter-hybrid", daemon=True)
        self._thread.start()

    def _make_all(self) -> None:
        from .generate import PRESENTER_PARALLEL
        try:
            with ThreadPoolExecutor(max_workers=max(1, PRESENTER_PARALLEL)) as pool:
                futs = {ap.id: pool.submit(self._make_one, ap) for ap in self.appearances}
                for _aid, f in futs.items():
                    f.result()
        except Exception:  # noqa: BLE001 - a failed take is a line for the footage search, never a failed video
            self._note(f"presenter thread: {traceback.format_exc(limit=3)[-400:]}")
        finally:
            try:
                if self.store is not None:
                    self.store.cleanup()            # the voice windows and framings sent to the provider
            except Exception:  # noqa: BLE001
                pass

    def _make_one(self, ap: Appearance) -> None:
        from .shotplan import Shot
        made = self.made[ap.id]
        shot = Shot(kind="presenter", start=ap.start, end=ap.end, text="", words=[], beats=list(ap.lines),
                    role=ap.role, framing=ap.framing, split=ap.split, id=ap.id, reason=ap.reason)
        try:
            asset = self.gen.presenter(shot)
        except Exception as e:  # noqa: BLE001
            asset = None
            made.why = f"{type(e).__name__}: {str(e)[:160]}"
        if asset is None or getattr(asset, "source", "") != PRESENTER_SOURCE:
            made.why = made.why or "the take failed its tries or the budget"
            self._note(f"{ap.id}: no presenter take ({made.why}); lines {ap.lines} get real footage")
            return
        try:
            parts = self._cut(ap, asset)
        except Exception as e:  # noqa: BLE001
            made.why = f"cutting the take: {type(e).__name__}: {str(e)[:160]}"
            self._note(f"{ap.id}: {made.why}")
            return
        if self._closed:
            made.why = "the take came after the build stopped waiting"
            self._note(f"{ap.id}: {made.why}; its lines keep their footage")
            return
        made.asset, made.parts = asset, parts

    def _cut(self, ap: Appearance, take) -> Dict[int, Any]:
        """The take as one clip per line, frame-exact (each runs PART_TAIL past its scene; the last keeps the
        take's own handle), so every line keeps its scene and the cuts between them are invisible."""
        from ..media import MediaAsset
        from . import media_io
        out: Dict[int, Any] = {}
        bounds = {i: self.line_spans[i] for i in ap.lines}
        have = media_io.duration(take.path)
        folder = os.path.join(self.work, "presenter", "lines")
        os.makedirs(folder, exist_ok=True)
        for k, i in enumerate(ap.lines):
            a, b = bounds[i]
            offset = a - ap.start
            last = k == len(ap.lines) - 1
            want = (b - a) + (max(PART_TAIL, have - (ap.end - ap.start)) if last else PART_TAIL)
            seconds = max(0.05, min(want, have - offset))
            if seconds + 0.04 < b - a:
                raise media_io.MediaError(f"line {i}: {seconds:.2f} s of take for a {b - a:.2f} s scene")
            path = media_io.trim(take.path, os.path.join(folder, f"{ap.id}_line{i:04d}.mp4"), offset, seconds,
                                 mute=True)
            info = media_io.probe(path)
            name = (self.kit or {}).get("name") or "the presenter"
            out[i] = MediaAsset(kind="video", source=PRESENTER_SOURCE, url="", local_path=path,
                                width=int(info["width"]), height=int(info["height"]), duration=float(info["duration"]),
                                attribution=f"AI presenter {name} ({take.model or 'heygen/avatar-iv'})",
                                license="generated", query="", intent=ap.role,
                                moment_key=f"presenter:{(self.kit or {}).get('id')}:{ap.id}:{i}")
        return out

    def wait(self, timeout: Optional[float] = None) -> None:
        """Block until every take is made or failed, at most `timeout` (WAIT_SECONDS); idempotent. A take not in
        by then is never used: its lines are the footage search's."""
        if self._waited:
            return
        if self._thread is not None:
            self._thread.join(WAIT_SECONDS if timeout is None else timeout)
            if self._thread.is_alive():
                self._closed = True
                for m in self.made.values():
                    if not m.parts:
                        m.why = m.why or f"not made within {WAIT_SECONDS if timeout is None else timeout:.0f} s"
                self._note("stopped waiting for the presenter's takes: the lines of those not in keep their footage")
        self._waited = True
        self.seconds = round(time.time() - self.started, 1)
        done = sum(1 for m in self.made.values() if m.parts)
        self._note(f"{done}/{len(self.made)} appearance(s) made in {self.seconds:.0f} s"
                   + (f"; spent ${self.budget.spent:.3f}" if self.budget is not None else ""))

    # ---- on the timeline
    def for_build(self, assets: List[Any]) -> List[Any]:
        """The assets timeline.build gets: each presenter line its own clip; a split line's real asset is kept
        as its right half (decorate). A split whose line found nothing real stays full-screen."""
        out = list(assets)
        for m in self.made.values():
            for i, part in m.parts.items():
                if i >= len(out):
                    continue
                if m.appearance.split and out[i] is not None:
                    self.halves[i] = out[i]
                out[i] = part
        return out

    def _framing(self, framing_id: str) -> dict:
        return next((f for f in (self.kit or {}).get("framings") or [] if f.get("id") == framing_id), {}) or {}

    def decorate(self, doc: Dict[str, Any]) -> None:
        """After timeline.build: split frames, the presenter's metadata, hard cuts, no effect or move on them."""
        scenes = doc.get("scenes") or []
        by_line = {i: m for m in self.made.values() for i in m.parts}
        for i, sc in enumerate(scenes):
            m = by_line.get(i)
            if m is None or not is_presenter_scene(sc):
                continue
            ap, take = m.appearance, m.asset
            sc["effect"] = "none"
            sc["treatment"] = "none"
            sc["motion"] = "none"
            sc["frame"] = "full"
            sc.pop("visualTreatment", None)
            sc["reviewRequired"] = False
            sc["reviewReason"] = ""
            sem = sc.setdefault("semanticMetadata", {})
            for k in ("alternatives", "candidates", "scoreParts", "moment"):
                sem[k] = [] if k == "alternatives" else {}
            for k in ("relevanceScore", "qualityScore", "finalScore", "sourceUrl", "pageUrl", "sourceThumbnail",
                      "cutCheck", "judgedBy"):
                sem.pop(k, None)
            sem["assetId"] = f"presenter:{(self.kit or {}).get('id')}:{ap.id}:{i}"
            sem["provider"] = PRESENTER_SOURCE
            sem["shotKind"] = "presenter"
            sem["role"] = ap.role
            sem["planReason"] = f"presenter: {ap.reason}"
            window = {k: v for k, v in ((take.checks or {}).get("window") or {}).items() if k != "path"}
            sem["presenter"] = {"kit": (self.kit or {}).get("id"), "name": (self.kit or {}).get("name"),
                                "framing": take.framing, "lag": take.lag, "take": ap.id, "lines": list(ap.lines),
                                "window": window, "mode": "hybrid"}
            sem["generated"] = {k: v for k, v in take.report().items() if k != "checks"}
            sem["generated"]["checks"] = {k: v for k, v in (take.checks or {}).items() if k in ("face",)}
            if take.url:
                sem["originalUrl"] = take.url
            half = self.halves.get(i) if ap.split else None
            if half is not None:
                self._split(sc, half)
        # Hard cuts into, between and out of the presenter (the references: always); no transition sound there.
        cuts = set()
        for i, sc in enumerate(scenes):
            prev = scenes[i - 1] if i > 0 else None
            if is_presenter_scene(sc) or (prev is not None and is_presenter_scene(prev)):
                if sc.get("transition") not in (None, "none"):
                    sc["transition"] = "none"
                sc.pop("transitionGain", None)
                cuts.add(int(sc.get("startFrame") or 0))
        if cuts:
            doc["sfx"] = [x for x in doc.get("sfx") or [] if not (
                x.get("kind") == "transition" and any(abs(int(x.get("startFrame") or 0) - c) <= int(self.fps) for c in cuts))]

    def _split(self, sc: Dict[str, Any], half) -> None:
        """The presenter left (cropped on the face), the line's own REAL clip or picture right."""
        framing = self._framing(((sc.get("semanticMetadata") or {}).get("presenter") or {}).get("framing") or "")
        try:
            face_x = float(framing.get("face_x", 0.5))
        except (TypeError, ValueError):
            face_x = 0.5
        media = sc.setdefault("media", {})
        is_video = getattr(half, "kind", "") == "video"
        split = {"type": "video" if is_video else "image", "url": getattr(half, "local_path", "") or half.url,
                 "source": half.source, "motion": "none" if is_video else "zoom-in",
                 # object-position x (%) that centres the face in the left half (cover crop of 16:9)
                 "focusX": round(max(0.0, min(100.0, (2 * face_x - 0.5) * 100)), 1),
                 "attribution": getattr(half, "attribution", "") or "", "license": getattr(half, "license", "") or "",
                 # What makes it this real clip: the repeat checks, the ledger and a restore read these.
                 "assetId": half.identity,
                 **({"sourceUrl": half.url} if str(half.url or "").startswith("http") else {}),
                 **({"pageUrl": half.page_url} if getattr(half, "page_url", "") else {}),
                 **({"moment": dict(half.moment)} if getattr(half, "moment", None) else {})}
        if is_video:
            try:
                from .. import timeline
                secs = timeline._clip_seconds(half)
                if secs:
                    split["clipSeconds"] = round(secs, 2)
            except Exception:  # noqa: BLE001
                pass
        media["split"] = split
        sc["frame"] = "split"
        sc.setdefault("semanticMetadata", {})["split"] = {
            "query": getattr(half, "query", "") or "", "relevanceScore": getattr(half, "relevance_score", None),
            "contentDescription": getattr(half, "content_description", "") or "", "real": True}

    def spans(self, doc: Dict[str, Any]) -> List[Tuple[int, int]]:
        """[start, end) frames of every presenter scene."""
        return [(int(sc["startFrame"]), int(sc["startFrame"]) + int(sc["durationInFrames"]))
                for sc in doc.get("scenes") or [] if is_presenter_scene(sc)]

    def finish(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """The end of the plan: nothing over a presenter scene, the report, the disclosure."""
        swept = clear_over_presenter(doc)
        meta = doc.setdefault("meta", {})
        made = [m for m in self.made.values() if m.parts]
        on_screen = sum((int(sc["durationInFrames"]) for sc in doc.get("scenes") or [] if is_presenter_scene(sc)))
        splits = sum(1 for sc in doc.get("scenes") or [] if is_presenter_scene(sc) and sc.get("frame") == "split")
        rows = self.budget.rows if self.budget is not None else []
        by: Dict[str, float] = {}
        for r in rows:
            by[str(r.get("kind") or "other")] = by.get(str(r.get("kind") or "other"), 0.0) + float(r.get("usd") or 0.0)
        report = {
            "mode": "hybrid", "kit": _public_kit(self.kit), "share": self.blk.get("share_name"),
            "shareOfTime": self.blk.get("share"), "splitScreen": bool(self.blk.get("split_screen")),
            # The cap on the presenter's whole time (split screens count) and, when the share asked for more, how
            # much: {askedSeconds, maxSeconds, seconds, appearances}.
            "maxSeconds": max_seconds_of(self.blk.get("max_seconds")), "capped": self.capped,
            "plannedSeconds": round(sum(ap.seconds for ap in self.appearances), 2),
            "planned": [ap.as_dict() for ap in self.appearances],
            "overBudget": list(self.dropped),
            "made": [m.appearance.id for m in made],
            "fellBack": [{"id": m.appearance.id, "lines": list(m.appearance.lines), "why": m.why}
                         for m in self.made.values() if not m.parts],
            "searchedAfter": list(self.searched_after),
            "screen": {"seconds": round(on_screen / max(1, self.fps), 2),
                       "share": round(on_screen / max(1, int(doc.get("durationInFrames") or 1)), 3),
                       "scenes": sum(1 for sc in doc.get("scenes") or [] if is_presenter_scene(sc)),
                       "splitScenes": splits, "appearances": len(made)},
            "costs": {"presenterUsd": round(by.get("presenter", 0.0), 4), "checksUsd": round(by.get("check", 0.0), 4),
                      "totalUsd": round(sum(by.values()), 4)},
            "budget": self.budget.report() if self.budget is not None else None,
            "estimate": self.est, "swept": swept, "seconds": self.seconds, "log": self.log[-40:]
            + (self.gen.log[-40:] if self.gen is not None else []),
            "disclosure": DISCLOSURE, "warnings": list(self.warnings),
        }
        meta["presenterHybrid"] = report
        if made:
            meta.setdefault("warnings", []).insert(0, DISCLOSURE)
        for w in self.warnings:
            meta.setdefault("warnings", []).append(w)
        return report


def _public_kit(kit: Optional[dict]) -> Optional[Dict[str, Any]]:
    if not kit:
        return None
    from . import kits
    try:
        return kits.public_summary(kit)
    except Exception:  # noqa: BLE001
        return {"id": kit.get("id"), "name": kit.get("name")}


# ------------------------------------------------------------------ nothing over the presenter
def clear_over_presenter(doc: Dict[str, Any], min_seconds: float = 1.2) -> Dict[str, int]:
    """
    No look, graphic or sound effect over a presenter scene: a look that
    starts on the footage before one ends at the cut (when what is left can
    still be read: min_seconds), any other look over one is left out (a look
    lands on its own word - moved, it would be early or late), and a sound
    effect that starts on one goes. Returns {"trimmed", "dropped", "sfx"}.
    """
    spans = [(int(sc["startFrame"]), int(sc["startFrame"]) + int(sc["durationInFrames"]))
             for sc in doc.get("scenes") or [] if is_presenter_scene(sc)]
    out = {"trimmed": 0, "dropped": 0, "sfx": 0}
    if not spans:
        return out
    fps = max(1, int(doc.get("fps") or 30))
    keep = []
    for ov in doc.get("overlays") or []:
        if ov.get("presenter"):
            keep.append(ov)                         # the presenter's own name (a lower third), when one is asked for
            continue
        a = int(ov.get("startFrame") or 0)
        b = a + int(ov.get("durationInFrames") or 0)
        hits = [(x, y) for (x, y) in spans if a < y and b > x]
        if not hits:
            keep.append(ov)
            continue
        first = min(x for x, _y in hits)
        if a < first and first - a >= int(min_seconds * fps):
            ov["durationInFrames"] = first - a
            keep.append(ov)
            out["trimmed"] += 1
        else:
            out["dropped"] += 1
    doc["overlays"] = keep
    sfx = []
    for x in doc.get("sfx") or []:
        at = int(x.get("startFrame") or 0)
        if any(s <= at < e for (s, e) in spans):
            out["sfx"] += 1
            continue
        sfx.append(x)
    doc["sfx"] = sfx
    if isinstance(doc.get("meta"), dict):
        doc["meta"]["overlayCount"] = len(keep)
    return out


# ------------------------------------------------------------------ the presenter is nobody to search for
def _name_pattern(kit: Optional[dict]) -> Optional["re.Pattern[str]"]:
    """The presenter's full name (and their first name when it is not a common word) as one pattern."""
    name = " ".join(str((kit or {}).get("name") or (kit or {}).get("display_name") or "").split())
    if len(name) < 3:
        return None
    parts = [re.escape(name)]
    first = name.split()[0]
    if len(name.split()) > 1 and len(first) >= 4:
        parts.append(re.escape(first))
    return re.compile(r"(?<![\w-])(?:" + "|".join(parts) + r")(?:['’]s)?(?![\w-])", re.I)


def scrub_brief(brief: Optional[dict], kit: Optional[dict]) -> int:
    """
    The presenter out of the story brief's cast and people (the laptop test's
    brief listed "Hollis Reed", alias "my name is Hollis Reed", as the story's
    person): no cut on their name, no person look, no search for their face.
    handler.do_plan calls it right after the brief. Returns how many entries went.
    """
    pat = _name_pattern(kit)
    if pat is None or not isinstance(brief, dict):
        return 0
    gone = 0
    cast = brief.get("cast")
    if isinstance(cast, list):
        keep = [c for c in cast if not (isinstance(c, dict) and pat.fullmatch(str(c.get("name") or "").strip()))]
        gone += len(cast) - len(keep)
        brief["cast"] = keep
    people = brief.get("people")
    if isinstance(people, list):
        keep = [x for x in people if not pat.fullmatch(str(x or "").strip())]
        gone += len(people) - len(keep)
        brief["people"] = keep
    return gone


def scrub_presenter(shots: List[dict], kit: Optional[dict], brief: Optional[dict] = None) -> int:
    """
    The presenter is a made-up person: no footage search may look for them
    (the laptop test's planner wrote "Hollis Reed Texas Panhandle ranch cook
    reading phone comment", and its subject pool found a real Hollis in a
    court case). Their name leaves every shot's query, fallbacks and subject;
    a shot whose subject was the presenter gets the story's own subject and is
    marked aboutPresenter (the presenter says that line on camera first).
    Returns how many shots changed.
    """
    pat = _name_pattern(kit)
    if pat is None:
        return 0
    story = str((brief or {}).get("event") or next(iter((brief or {}).get("places") or []), "") or "").strip()

    def clean(text: str) -> str:
        return " ".join(pat.sub(" ", str(text or "")).split()).strip(" ,;:-")
    changed = 0
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        before = (shot.get("query"), shot.get("subject"), list(shot.get("fallbacks") or []), shot.get("prompt"))
        subject = str(shot.get("subject") or "")
        if subject and pat.search(subject):
            shot["aboutPresenter"] = True
            rest = clean(subject)
            shot["subject"] = rest if len(rest.split()) >= 2 else story
            if shot.get("subjectType") == "person":
                shot["subjectType"] = "place" if shot["subject"] else ""
        query = clean(shot.get("query") or "")
        if len(query.split()) < 2:
            query = " ".join(x for x in (story, query) if x).strip()
        shot["query"] = query or story
        shot["fallbacks"] = [f for f in (clean(f) for f in shot.get("fallbacks") or []) if f]
        if shot.get("prompt"):
            shot["prompt"] = clean(shot["prompt"])
        if (shot.get("query"), shot.get("subject"), list(shot.get("fallbacks") or []), shot.get("prompt")) != before:
            changed += 1
    return changed


# ------------------------------------------------------------------ the whole step, for handler.do_plan
def kit_for(inp: Dict[str, Any], blk: Optional[Dict[str, Any]] = None) -> dict:
    """The block's kit, normalised (kept on the job input: read once). A block naming no usable kit raises
    ValueError - handler.do_plan asks first thing, so such a job fails before anything is paid for."""
    cached = inp.get("_presenter_hybrid_kit")
    if isinstance(cached, dict):
        return cached
    from . import kits
    blk = blk or block(inp) or {}
    try:
        kit = kits.for_job(kit_request(blk, inp))
    except kits.KitError as e:
        raise ValueError(f"The presenter block names no usable presenter: {e}") from None
    inp["_presenter_hybrid_kit"] = kit
    return kit


def start(inp: Dict[str, Any], segments: Sequence[Any], shots: Sequence[dict], *, narration_path: str,
          duration: float, work: str, brief: Optional[dict] = None, provider=None, store=None,
          cache_dir: str = "") -> Optional[Hybrid]:
    """
    The job's presenter, planned and started (the takes made in the
    background), or None without a presenter block. A block naming no usable
    kit fails the job before anything is spent (the app sent a bad block).
    """
    blk = block(inp)
    if blk is None:
        return None
    kit = kit_for(inp, blk)
    scrubbed = scrub_presenter(list(shots), kit, brief)
    fps = int(inp.get("fps") or config.DEFAULT_FPS)
    framings = [f["id"] for f in kit.get("framings") or []][:2] or ["master"]
    lines, total = plan_lines(segments, shots, duration, fps)
    selector = Selector(lines, total, share=float(blk["share"]), split=bool(blk["split_screen"]),
                        framings=framings, chapters=chapter_lines(brief, len(lines)),
                        max_seconds=max_seconds_of(blk.get("max_seconds")))
    appearances = selector.plan() if lines else []
    hy = Hybrid(inp=inp, blk=blk, kit=kit, appearances=appearances,
                spans={ln.index: (ln.start, ln.end) for ln in lines}, duration=duration, fps=fps,
                work=os.path.join(work, "hybrid"))
    hy.capped = selector.capped
    for note in selector.notes:
        hy._note(note)
    if scrubbed:
        hy._note(f"the presenter's name taken out of {scrubbed} line(s)' footage searches (a made-up person)")
    if not appearances:
        hy._note("no line fits the presenter (too short a video, or every line keeps its footage)")
        return hy
    try:
        hy.begin(narration_path, provider=provider, store=store, cache_dir=cache_dir)
    except Exception as e:  # noqa: BLE001 - the presenter never costs the video: real footage on every line
        hy._note(f"the presenter could not start ({type(e).__name__}: {str(e)[:160]}); real footage only")
        hy.warnings.append("The AI presenter could not be made this time: the video has real footage only.")
        hy.appearances, hy.made = [], {}
    return hy
