"""
The celeb-style timeline (pure: no files touched, so it is unit-tested).

Measured rules (docs/style-refs/celeb-compilation-STYLE.md):
  * cold open 6-10 s of the strongest clip, own audio, before any narration; a white flash after it
  * narration blocks butt-joined to clips: the clip's own sound starts when the narrator stops (<= 0.25 s)
  * J-cut: the clip's PICTURE starts during the bridge sentence (last 2-3 s, muted), with its label
  * narration b-roll = the same event's footage (the clip's own source around the clip), a new shot every 1.5-3 s
  * music: owner level 0.5, x0.8 under narration, x0.18 inside clips (ramp 0.3 s down, 0.5 s up)
  * a 0.2 s white flash with a shutter between segments (after the cold open, then at most every FLASH_EVERY s)
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

COLD_MIN, COLD_TARGET, COLD_MAX = 6.0, 8.0, 10.0
J_LEAD = 2.5            # seconds of the next clip's picture under the end of its bridge
FLASH = 0.2
FLASH_EVERY = 20.0      # no second flash sooner than this after the last one
SHOTS = (2.2, 1.7, 2.6, 1.9, 2.4, 1.6, 2.8)   # b-roll rhythm, 1.5-3 s
MUSIC_LEVEL, MUSIC_DUCK, MUSIC_IN_CLIP = 0.5, 0.8, 0.18


@dataclass
class Clip:
    """One found moment (quotes.Moment flattened): times on the source clock unless said otherwise."""
    path: str                     # trimmed clip (picture + own audio, 60 ms fades)
    window: str                   # padded download around it
    window_at: float              # window start on the source clock
    start: float
    end: float
    quote_at: Tuple[float, float] = (0.0, 0.0)     # quote inside the clip (clip clock)
    label: str = ""
    cold: bool = False
    words: List[dict] = field(default_factory=list)  # clip clock

    @property
    def length(self) -> float:
        return self.end - self.start

    @property
    def in_window(self) -> float:
        return self.start - self.window_at


@dataclass
class Shot:
    """One video piece: `src` from `src_in` for `dur` seconds, placed at `at` on the output clock."""
    kind: str                     # cold | flash | broll | clip
    at: float
    dur: float
    src: str = ""
    src_in: float = 0.0
    push: bool = False            # the slow 100 -> 104 % push-in
    clip: int = -1                # the clip index this shot shows


@dataclass
class Sound:
    kind: str                     # narr | clip | cold | sfx
    at: float
    path: str
    src_in: float = 0.0
    dur: float = 0.0              # 0 = whole file
    clip: int = -1


@dataclass
class Plan:
    shots: List[Shot] = field(default_factory=list)
    sounds: List[Sound] = field(default_factory=list)
    captions: List[Tuple[float, float, str]] = field(default_factory=list)   # (start, end, text) output clock
    labels: List[Tuple[float, float, str]] = field(default_factory=list)
    flashes: List[float] = field(default_factory=list)
    clip_spans: List[Tuple[float, float]] = field(default_factory=list)     # clip audio on the output clock
    total: float = 0.0


def cold_span(c: Clip) -> Tuple[float, float]:
    """6-10 s of the clip ending 1 s after its quote (clip clock): the punchline with its laugh."""
    q0, q1 = c.quote_at
    end = min(c.length, q1 + 1.0)
    start = max(0.0, min(q0 - 1.5, end - COLD_TARGET))
    start = max(start, end - COLD_MAX)
    if end - start < COLD_MIN:
        end = min(c.length, start + COLD_MIN)
    # never open mid-sentence: the latest sentence start that still leaves 6-10 s
    ws = c.words
    starts = [w["start"] for k, w in enumerate(ws)
              if k == 0 or str(ws[k - 1]["text"]).strip()[-1:] in ".?!" or w["start"] - ws[k - 1]["end"] > 0.45]
    fits = [x for x in starts if end - COLD_MAX <= x <= end - COLD_MIN]
    if fits:
        start = max(0.0, max(fits) - 0.1)
    return round(start, 3), round(end, 3)


def phrases(words: Sequence[dict], offset: float, lo: float = 0.0, hi: float = 1e9,
            max_words: int = 6) -> List[Tuple[float, float, str]]:
    """Caption phrases of 4-7 words from clip words in [lo, hi] (clip clock), shifted by offset."""
    ws = [w for w in words if w["start"] >= lo - 0.05 and w["end"] <= hi + 0.05 and str(w["text"]).strip()]
    out, cur = [], []

    def flush():
        if cur:
            out.append([cur[0]["start"], cur[-1]["end"], " ".join(str(w["text"]).strip() for w in cur)])

    for k, w in enumerate(ws):
        if cur and (w["start"] - cur[-1]["end"] > 0.6 or len(cur) >= max_words):
            flush()
            cur = []
        cur.append(w)
        if str(w["text"]).strip()[-1:] in ".?!" and len(cur) >= 2:
            flush()
            cur = []
    flush()
    for k in range(len(out) - 1):                       # hold a phrase until the next when the gap is short
        if out[k + 1][0] - out[k][1] < 1.0:
            out[k][1] = out[k + 1][0]
    return [(round(a - lo + offset, 3), round(b - lo + offset + (0.25 if k == len(out) - 1 else 0), 3), t.upper())
            for k, (a, b, t) in enumerate(out)]


def broll_ranges(c: Clip, window_len: float, lead: float) -> List[Tuple[float, float]]:
    """Window footage outside the clip and its J-cut lead (window clock): the same event, not the moment."""
    rng = []
    if c.in_window - lead > 1.0:
        rng.append((0.0, c.in_window - lead))
    after = c.in_window + c.length
    if window_len - after > 1.0:
        rng.append((after, window_len))
    return rng


def build(blocks: Sequence, narr_secs: Sequence[float], narr_paths: Sequence[str], clips: Dict[int, Clip],
          window_lens: Dict[str, float]) -> Plan:
    """
    blocks: script blocks (kind narr / clip, in order); narr_secs/paths: per narr block (in order);
    clips: block index -> Clip. Returns the timeline.
    """
    p = Plan()
    t = 0.0
    order = [i for i, b in enumerate(blocks) if b.kind == "clip" and i in clips]
    cold_i = next((i for i in order if clips[i].cold), order[-1] if order else None)
    cursor: Dict[tuple, float] = {}         # per window range: where the next b-roll slice starts
    last_flash = -1e9
    led = set()                             # clips whose picture already started under their bridge

    def flash():
        nonlocal t, last_flash
        p.shots.append(Shot("flash", t, FLASH))
        p.flashes.append(t)
        last_flash = t
        t += FLASH

    if cold_i is not None:
        c = clips[cold_i]
        a, b = cold_span(c)
        p.shots.append(Shot("cold", t, b - a, c.path, a, push=True, clip=cold_i))
        p.sounds.append(Sound("cold", t, c.path, a, b - a, clip=cold_i))
        p.captions += phrases(c.words, t, a, b)
        p.clip_spans.append((t, t + b - a))
        t += b - a
        flash()

    narr_k = 0
    for i, blk in enumerate(blocks):
        if blk.kind == "narr":
            dur = float(narr_secs[narr_k])
            p.sounds.append(Sound("narr", t, narr_paths[narr_k], 0.0, dur))
            narr_k += 1
            nxt = next((j for j in range(i + 1, len(blocks)) if blocks[j].kind == "clip"), None)
            nxt = nxt if nxt in clips and nxt == i + 1 else None
            lead = min(J_LEAD, max(0.0, dur * 0.4), clips[nxt].in_window) if nxt is not None else 0.0
            # b-roll: the next clip's event, else every clip's footage after its moment
            pool = []
            for j in ([nxt] if nxt is not None else order):
                cj = clips[j]
                pool += [(cj.window, a, b, j) for a, b in broll_ranges(cj, window_lens.get(cj.window, 0), J_LEAD)]
            if not pool:
                pool = [(clips[j].window, 0.0, window_lens.get(clips[j].window, 0), j) for j in order]
            left, k, s = dur - lead, 0, 0
            while left > 0.05 and pool:
                d = SHOTS[s % len(SHOTS)]
                d = left if left - d < 1.2 else d                 # never leave a sliver
                win, a, b, j = pool[k % len(pool)]
                at = cursor.get((win, a), a)
                if at < a or at + d > b:
                    at = a
                if at + d > b:                                    # range shorter than the shot: take what fits
                    d2 = max(0.5, b - a)
                    at, d = a, min(d, d2)
                p.shots.append(Shot("broll", t + (dur - lead - left), d, win, at, clip=j))
                cursor[(win, a)] = at + d + 0.4
                left -= d
                k += 1
                s += 1
            if nxt is not None and lead > 0:
                c = clips[nxt]
                p.shots.append(Shot("clip", t + dur - lead, lead + c.length, c.window, c.in_window - lead,
                                    push=True, clip=nxt))
                led.add(nxt)
                if c.label:
                    p.labels.append((round(t + dur - lead, 3), round(t + dur - lead + 2.8, 3), c.label.upper()))
            t += dur
        elif i in clips:
            c = clips[i]
            if i not in led:                                      # no bridge before it: the picture starts here
                p.shots.append(Shot("clip", t, c.length, c.path, 0.0, push=True, clip=i))
                if c.label:
                    p.labels.append((round(t, 3), round(t + 2.8, 3), c.label.upper()))
            p.sounds.append(Sound("clip", t, c.path, 0.0, c.length, clip=i))
            p.captions += phrases(c.words, t, 0.0, c.length)
            p.clip_spans.append((t, t + c.length))
            t += c.length
            follows_narr = i + 1 < len(blocks) and blocks[i + 1].kind == "narr"
            if follows_narr and t - last_flash >= FLASH_EVERY:
                flash()
    p.total = round(t, 3)
    p.shots.sort(key=lambda s: s.at)
    return p


def music_gain_points(p: Plan) -> List[Tuple[float, float]]:
    """(time, gain) breakpoints of the music bed: 0.5 x 0.8 under narration, 0.5 x 0.18 inside clips."""
    hi, lo = MUSIC_LEVEL * MUSIC_DUCK, MUSIC_LEVEL * MUSIC_IN_CLIP
    pts = [(0.0, lo if p.clip_spans and p.clip_spans[0][0] <= 0.01 else hi)]
    for a, b in p.clip_spans:
        pts += [(max(0.0, a - 0.3), hi), (a, lo), (b, lo), (b + 0.5, hi)]
    pts.append((p.total, hi))
    pts.sort()
    clean = []
    for x, g in pts:
        if clean and x <= clean[-1][0]:
            continue
        clean.append((round(x, 3), round(g, 4)))
    if clean and clean[0][0] > 0:
        clean.insert(0, (0.0, clean[0][1]))
    return clean
