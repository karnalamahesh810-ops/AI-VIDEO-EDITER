"""
The AI presenter style's shot plan: every stretch of the narration is either
the presenter talking to camera, an AI video clip, or a still (with a free
camera move and living-photo parallax), to the tier's shares of screen time.

Where the presenter goes (the research's step 3 and the reference channels):
  * the hook - the video opens on the presenter;
  * the close - the presenter signs off;
  * chapter openings ("Now, the onions...", "Here's what we did");
  * the key "why it matters" lines, first-person lines and lines said
    straight to the viewer;
  * and nowhere else beyond the tier's share, spread so the presenter comes
    back at least every MAX_GAP seconds.
A presenter shot lasts PRESENTER_MIN-PRESENTER_MAX seconds (3-8 s); a longer
passage cuts away to b-roll while the voice runs on (the shot ends on a word
boundary, ideally a sentence or clause end). Between two presenter shots
there is always some b-roll. B-roll shots are BROLL_MIN-BROLL_MAX seconds;
the ones that must move (water, steam, wind, crowds, hands at work - and the
hook on a budget) become AI video until its share is reached. A share of the
b-roll shows the presenter doing the thing (a still made from the kit's
portrait), like the reference channels' "Earl at the stove".

Input: the narration's beats (transcribe.segment_words, the editor's cuts)
and per-beat notes (src/presenter/director.py: the planner model's, or the
rules here). Output: shots in time order that tile the narration exactly
(shot k ends where shot k+1 starts; the first starts at 0, the last ends at
the narration's end), each with its words, the prompts for its still and
motion, and why it got its kind.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

# The owner's six reference videos (docs/ai-avatar-reference-analysis-2026-10-07.md, section 8.2): the
# presenter opens at 0:00 for 4-13 s, then returns for 3.6-7.3 s (median 5 s) every 15-40 s, with 15-35% of
# the first two minutes on the presenter; one visual per ~4 s line (stills 3.5-5.3 s, clips 3.4-5.7 s,
# ~15 cuts a minute); hard cuts, always into and out of the presenter.
PRESENTER_MIN = 3.5
PRESENTER_MAX = 7.5
PRESENTER_FIRST_MAX = 12.0
BROLL_MIN = 2.5
BROLL_MAX = 5.5
BROLL_TARGET = 4.0
AI_MIN = 3.0
MAX_GAP = 40.0
HOOK_SECONDS = 30.0
FRONT_SECONDS = 120.0
EPS = 1e-6


@dataclass
class W:
    """A spoken word (text, start, end) - transcribe.Word without the import."""
    text: str
    start: float
    end: float


@dataclass
class Note:
    """What the planner (model or rules) says about one beat."""
    role: str = "body"              # hook | chapter | why | close | body
    presenter_fit: float = 0.2      # 0-1: how much this line wants the presenter on screen
    needs_motion: float = 0.2       # 0-1: how much its picture must move (water, steam, crowds...)
    in_shot: bool = False           # the b-roll shows the presenter doing it
    still: str = ""                 # what the still shows (one sentence)
    alt: str = ""                   # a second, different picture for the same line
    motion: str = ""                # camera move + what moves (image-to-video)


@dataclass
class Beat:
    index: int
    text: str
    start: float                    # on screen from (the cut before it)
    end: float                      # to (the next beat's cut, or the narration's end)
    words: List[W] = field(default_factory=list)

    @property
    def seconds(self) -> float:
        return self.end - self.start


@dataclass
class Shot:
    kind: str                       # presenter | ai_video | picture
    start: float
    end: float
    text: str
    words: List[W]
    beats: List[int]
    role: str = "body"
    framing: str = ""
    still: str = ""
    motion: str = ""
    in_shot: bool = False
    split: bool = False             # presenter: drawn 50/50 with the line's b-roll (presenter left)
    reason: str = ""
    id: str = ""

    @property
    def seconds(self) -> float:
        return self.end - self.start

    def as_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "start": round(self.start, 3), "end": round(self.end, 3),
                "seconds": round(self.seconds, 3), "text": self.text, "beats": list(self.beats), "role": self.role,
                "framing": self.framing, "still": self.still, "motion": self.motion, "inShot": self.in_shot,
                "split": self.split, "reason": self.reason}


# ------------------------------------------------------------------ rules for a beat (no planner model)
_CHAPTER = re.compile(
    r"^\s*(now|so|okay|ok|alright|here'?s|here is|first(ly)?|second(ly)?|third(ly)?|next|another|finally|lastly|"
    r"the (first|second|third|next|last|real|other|big|biggest) (thing|step|trick|reason|way|secret|mistake|rule)|"
    r"step (one|two|three|four|five|\d+)|number (one|two|three|four|five|\d+))\b", re.I)
_WHY = re.compile(r"\b(why|because|the reason|matters?|important|here'?s the thing|the trick|secret|mistakes?|"
                  r"most (folks|people)|you('ll| need| should| want| have to| gotta)|don'?t|never|always|"
                  r"remember|listen|trust me|the truth)\b", re.I)
_FIRST = re.compile(r"\b(i|i'?ve|i'?m|i'?d|my|me|we|we'?d|our|us)\b", re.I)
_YOU = re.compile(r"\b(you|your|yours|y'?all|folks)\b", re.I)
_MOTION = re.compile(
    r"\b(water|pour(s|ed|ing)?|flow(s|ed|ing)?|river|creek|stream|rain(s|ing)?|storm|wind|breeze|smoke|steam|"
    r"boil(s|ed|ing)?|simmer|fire|flame|wave|cloud|crowd|walk(s|ed|ing)?|drive|driving|stir(s|red|ring)?|"
    r"cook(s|ed|ing)?|fry|sizzl\w*|drip\w*|splash\w*|flood\w*|snow\w*|leaves|sway\w*|blow\w*|swing\w*|"
    r"fly|flying|bird\w*|cattle|herd|tractor|truck|train|machine\w*|hang(s|ing)?|knead\w*|chop\w*|sprout\w*|"
    r"grow(s|ing)?|rot(s|ting)?|melt\w*|dig(s|ging)?)\b", re.I)
_ACTION = re.compile(r"\b(put|lay|laid|drop|hang|tie|brush|store|keep|cut|stir|cook|plant|pick|dig|wrap|fill|set|"
                     r"snip|pour|check|open|carry|stack|sort|spread|mix|knead|slice|peel|wash|dry|feed)\b", re.I)


def rule_note(text: str, index: int, count: int) -> Note:
    """A beat's note from its words alone (the planner model's stand-in)."""
    t = text or ""
    chapter = bool(_CHAPTER.search(t))
    why = bool(_WHY.search(t))
    first = bool(_FIRST.search(t))
    you = bool(_YOU.search(t))
    fit = 0.15 + 0.35 * why + 0.25 * first + 0.15 * you + 0.3 * chapter
    role = "hook" if index == 0 else "close" if index == count - 1 else "chapter" if chapter else \
        "why" if why else "body"
    motion = 0.7 if _MOTION.search(t) else 0.2
    in_shot = bool(first and _ACTION.search(t))
    return Note(role=role, presenter_fit=min(1.0, fit), needs_motion=motion, in_shot=in_shot)


_PRESENTER = re.compile(r"\bthe presenter\b", re.I)


def without_presenter(still: str) -> str:
    """A picture prompt with the presenter taken out: their hands stay (no face), anyone else is seen from behind."""
    t = re.sub(r"\bthe presenter['’]s (hands|hand|fingers|palm)\b", lambda m: f"weathered {m.group(1)}", still,
               flags=re.I)
    t = re.sub(r"\bthe presenter['’]s\b", "a", t, flags=re.I)
    return _PRESENTER.sub("a person seen from behind, face not visible,", t)


# ------------------------------------------------------------------ helpers
def beats_from(segments: Sequence[Any], total: float) -> List[Beat]:
    """Beats with their on-screen spans: each from its cut to the next one's (the first from 0, the last to the end)."""
    segs = list(segments)
    out: List[Beat] = []
    for i, s in enumerate(segs):
        start = 0.0 if i == 0 else float(getattr(s, "start", 0.0))
        end = float(total) if i == len(segs) - 1 else float(getattr(segs[i + 1], "start", 0.0))
        words = [W(str(getattr(w, "text", "")), float(getattr(w, "start", 0.0)), float(getattr(w, "end", 0.0)))
                 for w in getattr(s, "words", None) or []]
        out.append(Beat(index=i, text=str(getattr(s, "text", "") or ""), start=start, end=max(start, end), words=words))
    return out


def _words_in(words: Sequence[W], a: float, b: float) -> List[W]:
    """Words whose start falls in [a, b) (a word belongs to the span its first sound is in)."""
    return [w for w in words if a - EPS <= w.start < b - EPS]


def _text(words: Sequence[W]) -> str:
    return " ".join(w.text for w in words).strip()


def best_cut(words: Sequence[W], lo: float, hi: float, prefer: Optional[float] = None) -> Optional[float]:
    """
    A cut time in [lo, hi] at a word's start: after a sentence end first, then
    a clause end, then the longest pause; ties go to the one nearest `prefer`
    (default: hi). None when no word starts in the range.
    """
    best, best_key = None, None
    target = hi if prefer is None else prefer
    for k in range(1, len(words)):
        t = words[k].start
        if t < lo - EPS or t > hi + EPS:
            continue
        prev = words[k - 1].text.strip()
        rank = 3 if re.search(r"[.!?][\"'”’)]*$", prev) else 2 if re.search(r"[,;:—–-][\"'”’)]*$", prev) else 1
        gap = max(0.0, t - words[k - 1].end)
        key = (rank, round(min(gap, 0.6), 2), -abs(t - target))
        if best_key is None or key > best_key:
            best, best_key = t, key
    return best


# ------------------------------------------------------------------ the plan
class Planner:
    def __init__(self, beats: List[Beat], notes: List[Note], total: float, *, presenter_share: float,
                 ai_video_share: float, presenter_broll: float = 0.0, framings: Sequence[str] = ("master",),
                 presenter_min: float = PRESENTER_MIN, presenter_max: float = PRESENTER_MAX,
                 broll_min: float = BROLL_MIN, broll_max: float = BROLL_MAX, max_gap: float = MAX_GAP,
                 hook_seconds: float = HOOK_SECONDS, first_max: float = PRESENTER_FIRST_MAX,
                 split_share: float = 0.0):
        self.beats, self.total = beats, float(total)
        self.notes = list(notes) + [Note()] * max(0, len(beats) - len(notes))
        self.p_share, self.v_share, self.in_shot_share = presenter_share, ai_video_share, presenter_broll
        self.framings = list(framings) or ["master"]
        self.pmin, self.pmax = presenter_min, max(presenter_min, presenter_max)
        self.first_max = max(self.pmax, first_max)
        self.split_share = max(0.0, min(0.8, split_share))
        self.bmin, self.bmax = broll_min, max(broll_min * 1.5, broll_max)
        self.max_gap, self.hook_seconds = max_gap, hook_seconds
        self.words = [w for b in beats for w in b.words]
        self.runs: List[Tuple[float, float, str]] = []      # presenter spans (start, end, reason)

    # ---- presenter spans
    def _cut_point(self, a: float, lo: float, hi: float) -> float:
        """A cut between a+lo and a+hi: on a word start when one is there, else at a+hi."""
        t = best_cut(self.words, a + lo, a + hi, prefer=a + (lo + hi) / 2)
        return t if t is not None else min(self.total, a + hi)

    def _free(self, a: float, b: float) -> bool:
        """[a, b] keeps at least broll_min clear of every presenter span (the ends of the video excepted)."""
        for (x, y, _r) in self.runs:
            if a < y + self.bmin - EPS and b > x - self.bmin + EPS:
                return False
        return True

    def _grow_forward(self, i: int, pmax: Optional[float] = None) -> Optional[Tuple[float, float]]:
        """A presenter span from beat i's start, pmin-pmax long, ending on a cut."""
        pmax = self.pmax if pmax is None else pmax
        a = self.beats[i].start
        b = self.beats[i].end
        j = i
        while b - a < self.pmin - EPS and j + 1 < len(self.beats):
            nxt = self.beats[j + 1]
            if nxt.end - a <= pmax + EPS:
                j, b = j + 1, nxt.end
            else:
                b = self._cut_point(a, self.pmin, pmax)
                break
        if b - a > pmax + EPS:
            b = self._cut_point(a, self.pmin, pmax)
        b = self._to_sentence_end(a, b, pmax)
        if b - a < min(self.pmin, 2.0) - EPS:
            return None
        return a, b

    def _to_sentence_end(self, a: float, b: float, pmax: float) -> float:
        """A presenter span that stops mid-sentence runs on to the sentence's end when that is within pmax."""
        before = [w for w in self.words if w.start < b - EPS]
        if not before or re.search(r"[.!?][\"'”’)]*$", before[-1].text.strip()):
            return b
        for k, w in enumerate(self.words):
            if w.start < b - EPS or k + 1 >= len(self.words):
                continue
            if self.words[k + 1].start - a > pmax + EPS:
                break
            if re.search(r"[.!?][\"'”’)]*$", w.text.strip()):
                return self.words[k + 1].start
        return b

    def _grow_backward(self, i: int) -> Optional[Tuple[float, float]]:
        """A presenter span that ends at beat i's end, pmin-pmax long, starting on a cut."""
        b = self.beats[i].end
        a = self.beats[i].start
        j = i
        while b - a < self.pmin - EPS and j - 1 >= 0:
            prv = self.beats[j - 1]
            if b - prv.start <= self.pmax + EPS:
                j, a = j - 1, prv.start
            else:
                t = best_cut(self.words, b - self.pmax, b - self.pmin, prefer=b - (self.pmin + self.pmax) / 2)
                a = t if t is not None else max(0.0, b - self.pmax)
                break
        if b - a > self.pmax + EPS:
            t = best_cut(self.words, b - self.pmax, b - self.pmin, prefer=b - (self.pmin + self.pmax) / 2)
            a = t if t is not None else max(0.0, b - self.pmax)
        if b - a < min(self.pmin, 2.0) - EPS:
            return None
        return a, b

    def _score(self, i: int) -> float:
        n = self.notes[i]
        bonus = {"chapter": 0.35, "why": 0.25, "hook": 0.5, "close": 0.5}.get(n.role, 0.0)
        mid = (self.beats[i].start + self.beats[i].end) / 2
        far = min((abs(mid - (x + y) / 2) for (x, y, _r) in self.runs), default=self.total)
        spread = min(1.0, far / max(self.max_gap, 1.0)) * 0.4
        # Trust is built early (the references put 15-35% of the first two minutes on the presenter).
        early = 0.2 if mid < FRONT_SECONDS else 0.0
        return float(n.presenter_fit) + bonus + spread + early

    def _add(self, span: Optional[Tuple[float, float]], reason: str) -> bool:
        if not span:
            return False
        a, b = span
        if not self._free(a, b):
            return False
        self.runs.append((a, b, reason))
        self.runs.sort()
        return True

    def presenter_spans(self) -> List[Tuple[float, float, str]]:
        n = len(self.beats)
        if n == 0 or self.p_share <= 0:
            return []
        target = self.p_share * self.total
        # The hook: the video opens on the presenter.
        self._add(self._grow_forward(0, self.first_max), "hook")
        # The close: the presenter signs off - when the video has room for b-roll in between.
        if self.total >= 2 * self.pmin + self.bmin + 2 and n > 1:
            self._add(self._grow_backward(n - 1), "close")
        used = lambda: sum(y - x for (x, y, _r) in self.runs)   # noqa: E731
        # Chapter openings, key lines, first person: best first, spread out, until the share is reached.
        tried = set()
        while used() < target - 0.5 * self.pmin:
            order = sorted((i for i in range(n) if i not in tried), key=self._score, reverse=True)
            picked = False
            for i in order:
                tried.add(i)
                if self._score(i) < 0.3:
                    break
                if self._add(self._grow_forward(i), self.notes[i].role if self.notes[i].role != "body" else "key line"):
                    picked = True
                    break
            if not picked:
                break
        # The presenter comes back at least every max_gap seconds (while the share allows a little more).
        changed = True
        while changed and used() < target * 1.3:
            changed = False
            edges = [0.0] + [v for (x, y, _r) in self.runs for v in (x, y)] + [self.total]
            gaps = [(edges[k], edges[k + 1]) for k in range(0, len(edges) - 1, 2)]
            for (ga, gb) in gaps:
                if gb - ga <= self.max_gap:
                    continue
                inside = [i for i in range(n) if self.beats[i].start >= ga + self.bmin - EPS
                          and self.beats[i].end <= gb - self.bmin + EPS]
                for i in sorted(inside, key=self._score, reverse=True):
                    if self._add(self._grow_forward(i), "comes back"):
                        changed = True
                        break
                if changed:
                    break
        return list(self.runs)

    # ---- b-roll
    def _broll_pieces(self, a: float, b: float) -> List[Tuple[float, float]]:
        """The stretch [a, b] cut into b-roll shots: on beat cuts, short ones merged, long ones split on words."""
        cuts = [a] + [bt.start for bt in self.beats if a + EPS < bt.start < b - EPS] + [b]
        pieces = [(cuts[k], cuts[k + 1]) for k in range(len(cuts) - 1)]
        # Merge pieces shorter than bmin into a neighbour (the shorter side), within the stretch.
        merged = True
        while merged and len(pieces) > 1:
            merged = False
            for k, (x, y) in enumerate(pieces):
                if y - x >= self.bmin - EPS:
                    continue
                left = pieces[k - 1] if k > 0 else None
                right = pieces[k + 1] if k + 1 < len(pieces) else None
                if left and (not right or (left[1] - left[0]) <= (right[1] - right[0])):
                    pieces[k - 1:k + 1] = [(left[0], y)]
                else:
                    pieces[k:k + 2] = [(x, right[1])]
                merged = True
                break
        out: List[Tuple[float, float]] = []
        for (x, y) in pieces:
            if y - x <= self.bmax + EPS:
                out.append((x, y))
                continue
            parts = max(2, int(round((y - x) / BROLL_TARGET)))
            step = (y - x) / parts
            start = x
            for k in range(1, parts):
                want = x + k * step
                lo = max(start + self.bmin, want - step * 0.35)
                hi = min(y - self.bmin, want + step * 0.35)
                t = best_cut(self.words, lo, hi, prefer=want) if hi > lo else None
                if t is None:
                    t = want if want - start >= self.bmin and y - want >= self.bmin else None
                if t is None:
                    continue
                out.append((start, t))
                start = t
            out.append((start, y))
        return out

    def plan(self) -> List[Shot]:
        runs = self.presenter_spans()
        spans: List[Tuple[float, float, str, str]] = []      # (a, b, kind, reason)
        t = 0.0
        for (x, y, reason) in runs:
            if x > t + EPS:
                spans += [(p, q, "broll", "") for (p, q) in self._broll_pieces(t, x)]
            spans.append((x, y, "presenter", reason))
            t = y
        if t < self.total - EPS:
            spans += [(p, q, "broll", "") for (p, q) in self._broll_pieces(t, self.total)]
        # A sliver of b-roll between two presenter shots (under bmin) joins the shot before it.
        cleaned: List[List[Any]] = []
        for (a, b, kind, reason) in spans:
            if cleaned and kind == "broll" and b - a < 1.0 - EPS and cleaned[-1][2] == "presenter":
                cleaned[-1][1] = b
                continue
            cleaned.append([a, b, kind, reason])
        shots: List[Shot] = []
        for (a, b, kind, reason) in cleaned:
            words = _words_in(self.words, a, b)
            beat_ids = [bt.index for bt in self.beats if bt.start < b - EPS and bt.end > a + EPS] or \
                [min(range(len(self.beats)), key=lambda i: abs(self.beats[i].start - a))]
            first = beat_ids[0]
            note = self.notes[first]
            shots.append(Shot(kind="presenter" if kind == "presenter" else "picture", start=a, end=b,
                              text=_text(words) or self.beats[first].text, words=words, beats=beat_ids,
                              role=reason if kind == "presenter" else note.role if note.role in ("hook", "close")
                              else "body", reason=f"presenter: {reason}" if kind == "presenter" else ""))
        self._label_video(shots)
        self._label_in_shot(shots)
        self._label_split(shots)
        self._prompts(shots)
        self._framings(shots)
        for k, s in enumerate(shots):
            s.id = f"{'p' if s.kind == 'presenter' else 'v' if s.kind == 'ai_video' else 'i'}{k:03d}"
        return shots

    def _label_video(self, shots: List[Shot]) -> None:
        target = self.v_share * self.total
        if target <= 0:
            return
        cands = [k for k, s in enumerate(shots) if s.kind == "picture" and s.seconds >= AI_MIN - EPS]

        def score(k: int) -> float:
            s = shots[k]
            motion = max(self.notes[i].needs_motion for i in s.beats)
            hook = 0.3 if s.start < self.hook_seconds else 0.0
            return motion + hook + 0.2 * min(s.seconds, 6.0) / 6.0

        got = 0.0
        for k in sorted(cands, key=score, reverse=True):
            if got >= target - 1.0:
                break
            near = [shots[j].kind for j in (k - 1, k + 1) if 0 <= j < len(shots)]
            if "ai_video" in near and score(k) < 1.0 and self.v_share < 0.4:
                continue            # spread the clips: two in a row only when both must move
            shots[k].kind = "ai_video"
            shots[k].reason = f"moves ({score(k):.2f})"
            got += shots[k].seconds

    def _label_in_shot(self, shots: List[Shot]) -> None:
        """The presenter in the b-roll, up to the share: the lines the planner marked first, then those whose
        picture it wrote with the presenter in it."""
        broll = [k for k, s in enumerate(shots) if s.kind != "presenter"]
        want = int(round(self.in_shot_share * len(broll)))
        if want <= 0:
            return
        flagged = [k for k in broll if any(self.notes[i].in_shot for i in shots[k].beats)]
        named = [k for k in broll if k not in flagged
                 and any(_PRESENTER.search(self.notes[i].still or "") for i in shots[k].beats)]
        for k in (flagged + named)[:want]:
            shots[k].in_shot = True

    def _label_split(self, shots: List[Shot]) -> None:
        """Every third presenter appearance (never the hook or the close) as a split screen, to split_share."""
        if self.split_share <= 0:
            return
        middle = [s for s in shots if s.kind == "presenter" and s.role not in ("hook", "close")]
        want = int(math.ceil(self.split_share * len(middle) - 1e-9))
        for k, s in enumerate(middle):
            if want <= 0:
                break
            if k % 3 == 1 or len(middle) - k <= want:
                s.split = True
                want -= 1

    def _prompts(self, shots: List[Shot]) -> None:
        """Each shot's still and motion from its first beat's note; a beat's second shot takes the alternative.
        Presenter shots get theirs too: the still a failed presenter shot falls back to, and a split screen's half."""
        used: Dict[int, int] = {}
        for s in shots:
            i = s.beats[0]
            n = self.notes[i]
            k = used.get(i, 0)
            used[i] = k + 1
            still = n.still if k == 0 else (n.alt or n.still)
            if k > 1 and still:
                still = f"{still} (a different angle: a closer detail)"
            still = still or s.text
            if not s.in_shot:
                # Only a picture drawn from the kit's portrait may show the presenter: anyone else would be a
                # stranger with another face (a presenter shot's own still - its split-screen half, its
                # fallback - is drawn without the portrait too).
                still = without_presenter(still)
            s.still = still
            s.motion = n.motion

    def _framings(self, shots: List[Shot]) -> None:
        k = 0
        for s in shots:
            if s.kind == "presenter":
                s.framing = self.framings[k % len(self.framings)]
                k += 1


def plan(segments: Sequence[Any], total: float, notes: Optional[Sequence[Note]] = None, *,
         presenter_share: float, ai_video_share: float, presenter_broll: float = 0.0,
         framings: Sequence[str] = ("master",), **limits: float) -> List[Shot]:
    """The shot list for a narration: see the module notes."""
    beats = beats_from(segments, total)
    if notes is None or len(notes) < len(beats):
        given = list(notes or [])
        notes = given + [rule_note(b.text, b.index, len(beats)) for b in beats[len(given):]]
    return Planner(beats, list(notes), total, presenter_share=presenter_share, ai_video_share=ai_video_share,
                   presenter_broll=presenter_broll, framings=framings, **limits).plan()


def stats(shots: Sequence[Shot], total: float) -> Dict[str, Any]:
    """Screen time by kind and the presenter's shot lengths, for the plan's meta and the tests."""
    by: Dict[str, float] = {"presenter": 0.0, "ai_video": 0.0, "picture": 0.0}
    for s in shots:
        by[s.kind] = by.get(s.kind, 0.0) + s.seconds
    pres = [s.seconds for s in shots if s.kind == "presenter"]
    return {"shots": len(shots), "seconds": {k: round(v, 2) for k, v in by.items()},
            "shares": {k: round(v / max(total, EPS), 3) for k, v in by.items()},
            "presenterShots": len(pres), "presenterLongest": round(max(pres), 2) if pres else 0.0,
            "presenterShortest": round(min(pres), 2) if pres else 0.0,
            "cutsPerMinute": round(len(shots) / max(total / 60.0, EPS), 1)}
