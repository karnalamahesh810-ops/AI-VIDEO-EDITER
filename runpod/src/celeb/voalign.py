"""
An uploaded voice-over cut at the clip spots (STYLE.md 2.4).

  1. whisper word timings of the whole upload (transcribe.transcribe_words)
  2. align the heard words to the script's narration blocks (difflib over normalised tokens)
  3. block N ends at its last word + 0.12 s, snapped to the middle of a silence (> 250 ms) within +-0.6 s
  4. each block is cut out and levelled exactly like a generated block (voice.level), so the plan is the same

If the owner read the quotes aloud too, those words match no narration block and fall between the cuts.
"""
import difflib
import os
import re
import subprocess
from typing import List, Optional, Sequence, Tuple

from . import voice
from .quotes import W, norm_tokens


def silences(path: str, noise_db: float = -40.0, min_s: float = 0.25) -> List[Tuple[float, float]]:
    p = subprocess.run(["ffmpeg", "-nostats", "-i", path, "-af", f"silencedetect=n={noise_db}dB:d={min_s}",
                        "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=600)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", p.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", p.stderr)]
    return list(zip(starts, ends))


def align_blocks(words: Sequence[W], blocks: Sequence[str]) -> List[Optional[Tuple[int, int]]]:
    """For each narration block, the (first, last) heard-word index it covers, or None if it was not heard."""
    heard: List[Tuple[str, int]] = [(t, i) for i, w in enumerate(words) for t in norm_tokens(w.text)]
    script: List[Tuple[str, int]] = [(t, b) for b, text in enumerate(blocks) for t in norm_tokens(text)]
    sm = difflib.SequenceMatcher(None, [t for t, _ in script], [t for t, _ in heard], autojunk=False)
    spans: List[List[int]] = [[] for _ in blocks]
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            spans[script[a + k][1]].append(heard[b + k][1])
    out: List[Optional[Tuple[int, int]]] = []
    for b, idx in enumerate(spans):
        need = max(1, len(norm_tokens(blocks[b])))
        out.append((min(idx), max(idx)) if idx and len(idx) >= 0.5 * need else None)
    return out


def cut_points(words: Sequence[W], spans: Sequence[Optional[Tuple[int, int]]], quiet: Sequence[Tuple[float, float]],
               total: float, lead: float = 0.12, snap: float = 0.6) -> List[Tuple[float, float]]:
    """(start, end) seconds of each aligned block in the upload; silence-snapped edges."""
    def snapped(t: float, edge: str) -> float:
        near = [(a, b) for a, b in quiet if a - snap <= t <= b + snap]
        if not near:
            return t
        a, b = min(near, key=lambda q: abs((q[0] + q[1]) / 2 - t))
        mid = (a + b) / 2
        # keep a breath of room on the side of the speech, never cut into a word
        return min(mid, a + 0.2) if edge == "end" else max(mid, b - 0.2)

    out = []
    for sp in spans:
        if sp is None:
            out.append((0.0, 0.0))
            continue
        s = max(0.0, words[sp[0]].start - lead)
        e = min(total, words[sp[1]].end + lead)
        out.append((round(snapped(s, "start"), 3), round(snapped(e, "end"), 3)))
    return out


def split(upload: str, blocks: Sequence[str], work: str, words: Optional[Sequence[W]] = None) -> List[str]:
    """One levelled wav per narration block from the owner's own recording."""
    from .. import transcribe
    from .compose import duration
    os.makedirs(work, exist_ok=True)
    if words is None:
        words = [W(w.text, w.start, w.end) for w in transcribe.transcribe_words(upload, language="en")]
    spans = align_blocks(words, blocks)
    missing = [i + 1 for i, s in enumerate(spans) if s is None]
    if missing:
        raise ValueError(f"narration block(s) {missing} were not found in the uploaded voice-over")
    cuts = cut_points(words, spans, silences(upload), duration(upload))
    out = []
    for i, (a, b) in enumerate(cuts):
        raw = os.path.join(work, f"vo_{i:02d}.wav")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{a:.3f}", "-i", upload, "-t", f"{b - a:.3f}",
                        "-af", "afade=t=in:d=0.03,areverse,afade=t=in:d=0.06,areverse", raw], check=True, timeout=300)
        out.append(voice.level(raw, os.path.join(work, f"narr_{i:02d}.wav")))
    return out
