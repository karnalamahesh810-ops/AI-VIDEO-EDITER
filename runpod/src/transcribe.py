"""
Narration alignment.

This is the step that makes clips land on the right words. We transcribe the
narration audio with word-level timestamps, then cut the timeline on natural
clause boundaries around the 7-second GoMotion visual rhythm.

If a script was pasted, we still transcribe (for timing) but snap the recognised
words back onto the *authored* script text, so captions read exactly as written
rather than as whisper heard them.
"""
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import List, Optional
import re

from . import config

_model = None


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Segment:
    """One spoken clause -> one visual on the timeline."""
    text: str
    start: float
    end: float
    words: List[Word] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def _load_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        device = config.WHISPER_DEVICE
        if device == "auto":
            try:
                import torch  # noqa
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:
                device = "cpu"
        compute = "float16" if device == "cuda" else "int8"
        _model = WhisperModel(config.WHISPER_MODEL, device=device, compute_type=compute)
    return _model


def transcribe_words(audio_path: str, language: Optional[str] = None,
                     on_progress=None) -> List[Word]:
    """
    Word-level timestamps for the narration track.

    `on_progress(fraction)` is called as whisper walks the audio. Without it
    this stage is a single silent block - ten minutes on a 21-minute file -
    which is indistinguishable from a hang to anyone watching a progress bar.
    faster-whisper yields segments lazily, so the position is free: it is just
    how far the last decoded segment reached.
    """
    model = _load_model()
    segments, info = model.transcribe(
        audio_path,
        language=language,
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
    )
    total = float(getattr(info, "duration", 0.0) or 0.0)
    words: List[Word] = []
    for seg in segments:
        for w in (seg.words or []):
            t = (w.word or "").strip()
            if t:
                words.append(Word(text=t, start=float(w.start), end=float(w.end)))
        if on_progress and total > 0:
            try:
                on_progress(min(1.0, float(seg.end) / total))
            except Exception:  # noqa: BLE001
                pass
    return words


# Clause boundaries: hard stops first, then soft (comma / connector) so long
# sentences still get cut into ~3s visuals instead of one 12s static shot.
_HARD_END = re.compile(r"[.!?]$")
_SOFT_END = re.compile(r"[,;:—-]$")

# A gap this long between words reads as a breath / beat in delivery.
_PAUSE_SECONDS = 0.08
# How far past target we tolerate while waiting for a natural pause.
_STRETCH_FACTOR = 1.25


def segment_words(words: List[Word]) -> List[Segment]:
    """
    Group words into clause-length segments targeting TARGET_SCENE_SECONDS.

    Rules, in priority order:
      1. Always break on sentence-final punctuation once past MIN_SCENE_SECONDS.
      2. Break on soft punctuation once past TARGET_SCENE_SECONDS.
      3. Force a break at MAX_SCENE_SECONDS so nothing sits still too long.
      4. Never emit a segment shorter than MIN_SCENE_SECONDS - merge it forward.
    """
    if not words:
        return []

    segments: List[Segment] = []
    cur: List[Word] = []
    seg_start = words[0].start

    def flush(end_time: float):
        nonlocal cur, seg_start
        if not cur:
            return
        text = " ".join(w.text for w in cur).strip()
        text = re.sub(r"\s+([,.!?;:])", r"\1", text)
        segments.append(Segment(text=text, start=seg_start, end=end_time, words=list(cur)))
        cur = []

    for i, w in enumerate(words):
        if not cur:
            seg_start = w.start
        cur.append(w)
        elapsed = w.end - seg_start

        # Silence before the *next* word is a natural cut point even when the
        # speaker used no punctuation. Without this, unpunctuated narration only
        # ever breaks at the hard cap and the cut rate drops below the target.
        nxt = words[i + 1] if i + 1 < len(words) else None
        pause = (nxt.start - w.end) if nxt else 0.0

        hard = bool(_HARD_END.search(w.text)) and elapsed >= config.MIN_SCENE_SECONDS
        soft = bool(_SOFT_END.search(w.text)) and elapsed >= config.TARGET_SCENE_SECONDS
        breath = pause >= _PAUSE_SECONDS and elapsed >= config.TARGET_SCENE_SECONDS
        # Unpunctuated narration can run without a usable pause for a long time.
        # Once we are meaningfully past target, cut on the next word boundary
        # rather than drifting out to the hard cap.
        stretch = elapsed >= config.TARGET_SCENE_SECONDS * _STRETCH_FACTOR
        forced = elapsed >= config.MAX_SCENE_SECONDS

        if hard or soft or breath or stretch or forced:
            flush(w.end)

    flush(words[-1].end)

    # Merge any runt segments forward so we don't flash a clip for 0.6s.
    merged: List[Segment] = []
    for seg in segments:
        if merged and seg.duration < config.MIN_SCENE_SECONDS:
            prev = merged[-1]
            prev.text = (prev.text + " " + seg.text).strip()
            prev.end = seg.end
            prev.words.extend(seg.words)
        else:
            merged.append(seg)
    return merged


def align_to_script(segments: List[Segment], script: str) -> List[Segment]:
    """
    Align authored words to recognized words, then retain the actual audio times.

    Proportionally distributing the script across the whole recording drifts
    badly as soon as the narration skips, adds, or paraphrases a sentence. The
    resulting captions and search terms then describe a different moment from
    the voice. Sequence alignment anchors matching words and interpolates only
    between unmatched spans.
    """
    script = (script or "").strip()
    if not script or not segments:
        return segments

    authored = script.split()
    spoken = [w for seg in segments for w in seg.words]
    if not spoken:
        return segments

    def norm(token: str) -> str:
        return re.sub(r"[^\w']", "", token, flags=re.UNICODE).casefold()

    a = [norm(w) for w in authored]
    b = [norm(w.text) for w in spoken]
    aligned: List[Optional[tuple]] = [None] * len(authored)
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for ai, bi in zip(range(i1, i2), range(j1, j2)):
                aligned[ai] = (spoken[bi].start, spoken[bi].end)
        elif tag == "replace" and j2 > j1:
            lo, hi = spoken[j1].start, spoken[j2 - 1].end
            count = max(1, i2 - i1)
            for n, ai in enumerate(range(i1, i2)):
                aligned[ai] = (lo + (hi - lo) * n / count,
                               lo + (hi - lo) * (n + 1) / count)

    # Fill script words absent from the recording between their nearest timed
    # neighbours. If the script and narration are substantially different,
    # fall back to Whisper's words rather than assigning unrelated text.
    matched = sum(x is not None for x in aligned)
    if matched < max(1, min(len(authored), len(spoken)) * 0.2):
        return segments
    known = [i for i, x in enumerate(aligned) if x is not None]
    for i, item in enumerate(aligned):
        if item is not None:
            continue
        left = max((k for k in known if k < i), default=None)
        right = min((k for k in known if k > i), default=None)
        if left is None:
            t = aligned[right][0] if right is not None else spoken[0].start
            aligned[i] = (t, t)
        elif right is None:
            t = aligned[left][1]
            aligned[i] = (t, t)
        else:
            lo, hi = aligned[left][1], aligned[right][0]
            count = right - left
            aligned[i] = (lo + (hi - lo) * (i-left-1) / count,
                          lo + (hi - lo) * (i-left) / count)

    chunks = [[] for _ in segments]
    for token, (start, end) in zip(authored, aligned):
        midpoint = (start + end) / 2
        index = next((i for i, seg in enumerate(segments)
                      if seg.start <= midpoint < seg.end),
                     min(range(len(segments)), key=lambda i: abs(segments[i].start-midpoint)))
        chunks[index].append(token)
    for seg, chunk in zip(segments, chunks):
        if chunk:
            seg.text = " ".join(chunk)
    return segments


def keywords_for(segment: Segment, max_terms: int = 4) -> str:
    """
    Build the stock/clip search query for a segment.

    Keeps proper nouns and content words, drops filler. This is what decides
    whether the visual actually matches what is being narrated.
    """
    stop = {
        "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "at",
        "for", "with", "from", "by", "as", "is", "are", "was", "were", "be", "been",
        "it", "its", "this", "that", "these", "those", "they", "them", "their",
        "he", "she", "his", "her", "you", "your", "we", "our", "i", "my", "me",
        "not", "no", "so", "then", "than", "there", "here", "what", "when", "how",
        "all", "just", "only", "one", "two", "out", "up", "down", "into", "over",
        "about", "after", "before", "while", "would", "could", "should", "will",
        "can", "had", "has", "have", "did", "does", "do", "more", "most", "very",
    }
    words = re.findall(r"[A-Za-z][A-Za-z'-]+", segment.text)
    proper = [w for w in words[1:] if w[0].isupper()]
    content = [w for w in words if w.lower() not in stop and len(w) > 3]

    terms: List[str] = []
    for w in proper + content:
        wl = w.lower()
        if wl not in [t.lower() for t in terms]:
            terms.append(w)
        if len(terms) >= max_terms:
            break
    return " ".join(terms) if terms else segment.text[:60]
