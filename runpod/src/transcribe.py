"""
Narration alignment.

This is the step that makes clips land on the right words. We transcribe the
narration audio with word-level timestamps, then cut the timeline on clause
boundaries — which is exactly how the VidRush reference renders behave
(one visual per spoken clause, median ~3s).

If a script was pasted, we still transcribe (for timing) but snap the recognised
words back onto the *authored* script text, so captions read exactly as written
rather than as whisper heard them.
"""
from dataclasses import dataclass, field
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


def transcribe_words(audio_path: str, language: Optional[str] = None) -> List[Word]:
    """Word-level timestamps for the narration track."""
    model = _load_model()
    segments, _info = model.transcribe(
        audio_path,
        language=language,
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
    )
    words: List[Word] = []
    for seg in segments:
        for w in (seg.words or []):
            t = (w.word or "").strip()
            if t:
                words.append(Word(text=t, start=float(w.start), end=float(w.end)))
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
    Replace transcribed text with the authored script text, preserving timing.

    Whisper mishears names and numbers ("Pereira", "7.4"). When the user pasted a
    script we keep whisper's *timing* but show the user's *words*, distributing
    the script across segments proportionally to each segment's word count.
    """
    script = (script or "").strip()
    if not script or not segments:
        return segments

    script_words = script.split()
    total_spoken = sum(len(s.words) for s in segments) or 1
    idx = 0
    for i, seg in enumerate(segments):
        share = len(seg.words) / total_spoken
        take = max(1, round(share * len(script_words)))
        if i == len(segments) - 1:
            take = len(script_words) - idx
        chunk = script_words[idx: idx + take]
        idx += take
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
