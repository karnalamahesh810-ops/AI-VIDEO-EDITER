"""
The quote finder: the real moment behind a [CLIP: who | "quote" | where] spot.

  1. search      YouTube for who + where + quote words (our proxied flat search), official shows first
  2. locate      caption word timings (yt-dlp json3 auto-captions, no video) + fuzzy quote match
  3. download    only a padded window around the match (section download, <= 1080p)
  4. words       faster-whisper on the window: exact word times WITH punctuation (sentence ends)
  5. snap        in point on the setup sentence before the quote, out point on the end of the
                 quote's sentence plus the laugh tail (audio stays loud after the last word, <= 2 s)
  6. trim        the final clip file + its words (the clip's own captions)

When a video has no captions, step 2 falls back to whisper on the first minutes' audio.
Credentials never leave the proxy manager: logs name routes by index only.
"""
import difflib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .. import ytdlp

# Shows and outlets whose uploads are the cleanest source of a talk-show moment.
OFFICIAL = ("jimmy kimmel", "the tonight show", "late night", "graham norton", "the late show", "colbert",
            "ellen", "vanity fair", "wired", "bbc", "buzzfeed", "lad bible", "ladbible", "jimmy fallon",
            "conan", "team coco", "the one show", "james corden", "late late show", "hot ones", "first we feast",
            "seth meyers", "access hollywood", "entertainment tonight", "extra", "mtv", "jake's takes")


@dataclass
class W:
    text: str
    start: float
    end: float


@dataclass
class Moment:
    video_id: str
    title: str = ""
    channel: str = ""
    start: float = 0.0               # in point in the source video (s)
    end: float = 0.0                 # out point in the source video (s)
    score: float = 0.0               # quote match 0..1
    path: str = ""                   # trimmed clip file (video + own audio)
    words: List[W] = field(default_factory=list)   # clip words, times relative to the clip start
    quote_at: Tuple[float, float] = (0.0, 0.0)     # the quote inside the clip (relative s)
    source: str = ""                 # how the match was found: captions | whisper | given
    window: str = ""                 # the padded download around the clip (b-roll comes from it)
    window_at: float = 0.0           # the window's start in the source video (s)
    window_words: List[W] = field(default_factory=list)   # every word of the window, on the window's clock

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


# ------------------------------------------------------------------ text matching
def norm_tokens(text: str) -> List[str]:
    t = (text or "").lower().replace("’", "'")
    t = re.sub(r"\[[^\]]*\]", " ", t)                     # [Laughter] / [Music]
    t = re.sub(r"[^a-z0-9' ]+", " ", t)
    return [w.strip("'") for w in t.split() if w.strip("'")]


def _ratio(a: Sequence[str], b: Sequence[str]) -> float:
    """Order-aware similarity blended with a token-set overlap (tolerates auto-caption slips)."""
    if not a or not b:
        return 0.0
    seq = difflib.SequenceMatcher(None, " ".join(a), " ".join(b), autojunk=False).ratio()
    sa, sb = set(a), set(b)
    overlap = len(sa & sb) / max(1, min(len(sa), len(sb)))
    return 0.6 * seq + 0.4 * overlap


def match_quote(words: Sequence[W], quote: str, slack: int = 3) -> Tuple[float, int, int]:
    """(score, first word index, last word index) of the best window for the quote; score 0 if none."""
    q = norm_tokens(quote)
    toks = [norm_tokens(w.text) for w in words]
    flat: List[Tuple[str, int]] = [(t, i) for i, ts in enumerate(toks) for t in ts]
    if not q or not flat:
        return 0.0, -1, -1
    best = (0.0, -1, -1)
    n = len(q)
    for size in range(max(1, n - slack), n + slack + 1):
        for s in range(0, max(1, len(flat) - size + 1)):
            win = [t for t, _ in flat[s:s + size]]
            if not win or win[0] not in q[:3] and win[-1] not in q[-3:]:
                continue                                       # cheap gate: an end must line up
            r = _ratio(q, win)
            if r > best[0]:
                best = (r, flat[s][1], flat[min(len(flat), s + size) - 1][1])
    return best


# ------------------------------------------------------------------ captions
def parse_json3(data: dict) -> List[W]:
    """Word timings from a YouTube json3 caption track (auto-captions carry per-word offsets)."""
    out: List[W] = []
    for ev in data.get("events") or []:
        segs = ev.get("segs") or []
        t0 = float(ev.get("tStartMs") or 0) / 1000.0
        dur = float(ev.get("dDurationMs") or 0) / 1000.0
        pieces = [(s.get("utf8") or "", float(s.get("tOffsetMs") or 0) / 1000.0) for s in segs]
        pieces = [(t, o) for t, o in pieces if t.strip()]
        for k, (t, o) in enumerate(pieces):
            end = t0 + (pieces[k + 1][1] if k + 1 < len(pieces) else dur)
            parts = t.split()
            step = max(0.05, (end - (t0 + o)) / len(parts))      # manual tracks: one seg per line -> spread
            for n, part in enumerate(parts):
                s0 = t0 + o + n * step
                out.append(W(part, s0, s0 + step))
    out.sort(key=lambda w: w.start)
    for a, b in zip(out, out[1:]):                             # auto-caption events overlap: clip each word
        a.end = min(a.end, max(a.start + 0.05, b.start))
    return out


def fetch_captions(video_id: str, timeout: int = 60, run: Callable = subprocess.run) -> List[W]:
    """English caption words (auto first: they carry word times; manual tracks as a fallback)."""
    with tempfile.TemporaryDirectory() as tmp:
        proxy = ytdlp._acquire_proxy()
        ok = False
        try:
            cmd = ["yt-dlp", f"https://www.youtube.com/watch?v={video_id}", "--skip-download",
                   "--write-auto-subs", "--write-subs", "--sub-langs", "en,en-orig,en-US,en-GB",
                   "--sub-format", "json3", "--no-playlist", "--no-warnings",
                   "-o", os.path.join(tmp, "c.%(ext)s"), *ytdlp._yt_network_args(proxy)]
            p = run(cmd, capture_output=True, text=True, timeout=timeout)
            ok = p.returncode == 0
        except subprocess.TimeoutExpired:
            p = None
        finally:
            ytdlp._release_proxy(proxy, ok)
        files = sorted(f for f in os.listdir(tmp) if f.endswith(".json3"))
        # en-orig (auto) has word offsets; prefer it, then en, then anything English.
        files.sort(key=lambda f: (0 if "orig" in f else 1 if ".en." in f else 2))
        for f in files:
            try:
                with open(os.path.join(tmp, f), encoding="utf-8") as fh:
                    words = parse_json3(json.load(fh))
            except (OSError, ValueError):
                continue
            if words:
                return words
    return []


# ------------------------------------------------------------------ search
def queries(who: Sequence[str], quote: str, where: str) -> List[str]:
    name = " ".join(who[:2])
    qwords = " ".join(norm_tokens(quote)[:8])
    out = [f"{name} {where} {qwords}".strip(), f"{name} {where}".strip(), f"{name} {qwords}".strip()]
    return list(dict.fromkeys(q for q in out if q))


def rank(cands: Sequence[dict], who: Sequence[str], where: str) -> List[dict]:
    """Official show uploads, the person's name in the title, interview-length videos first."""
    names = [n.lower() for n in who]
    wl = (where or "").lower()

    def score(c: dict) -> float:
        title, chan = (c.get("title") or "").lower(), (c.get("channel") or "").lower()
        s = 0.0
        s += 3.0 if any(o in chan for o in OFFICIAL) else 0.0
        s += 2.0 * sum(1 for n in names if n.split()[-1] in title)
        s += 1.5 if wl and any(w in title + " " + chan for w in norm_tokens(wl) if len(w) > 3) else 0.0
        d = float(c.get("duration") or 0)
        s += 1.0 if 60 <= d <= 1200 else (-2.0 if d and d < 30 else 0.0)
        s -= 3.0 if re.search(r"\b(compilation|funniest|best moments|reaction|reacts)\b", title) else 0.0
        return s
    return sorted(cands, key=score, reverse=True)


# ------------------------------------------------------------------ boundaries
SETUP_MIN, SETUP_MAX = 2.0, 9.0      # how far before the quote the setup line may start
SETUP_GROW = 14.0                     # a short clip may take earlier sentences up to this far back
CLIP_MIN = 12.0                       # grow shorter moments by whole sentences towards this
TAIL_MAX = 2.0                        # laugh tail after the last word


def _ends(w: W) -> bool:
    return bool(re.search(r"[.!?][\"')\]]*$", w.text.strip()))


def snap(words: Sequence[W], qi: int, qj: int, *, min_s: float = 0.0, max_s: float = 0.0) -> Tuple[float, float]:
    """
    In/out (seconds, on the words' clock) around words[qi..qj]: in = the start of the sentence before the
    quote's sentence (the setup), never more than SETUP_MAX earlier; out = the end of the quote's sentence.
    Sentence ends come from punctuation (whisper) or, without it, from pauses of 0.6 s or more.
    """
    def boundary_before(i: int) -> bool:
        return i == 0 or _ends(words[i - 1]) or words[i].start - words[i - 1].end >= 0.6

    qstart = words[qi].start
    # start of the quote's own sentence
    i = qi
    while i > 0 and not boundary_before(i) and qstart - words[i - 1].start <= SETUP_MAX:
        i -= 1
    # then one sentence more (the setup) while it fits
    if qstart - words[i].start < SETUP_MIN and i > 0:
        k = i - 1
        while k > 0 and not boundary_before(k) and qstart - words[k - 1].start <= SETUP_MAX:
            k -= 1
        if qstart - words[k].start <= SETUP_MAX:
            i = k
    j = qj
    while j + 1 < len(words) and not _ends(words[j]) and words[j + 1].start - words[j].end < 0.6 \
            and words[j + 1].end - words[qj].end <= 5.0:
        j += 1
    # The references' clip spots run 12-31 s: grow a short moment by whole sentences, setup first.
    # When the speaker runs straight on into the next sentence (< 0.5 s), the thought is not finished:
    # grow forward first; after a beat (a laugh, a reply) the setup before the quote matters more.
    want = max(min_s, CLIP_MIN)

    def grow_back() -> bool:
        nonlocal i
        k = i - 1
        while k > 0 and not boundary_before(k):
            k -= 1
        if i > 0 and qstart - words[k].start <= SETUP_GROW and (not max_s or words[j].end - words[k].start <= max_s):
            i = k
            return True
        return False

    def grow_forward() -> bool:
        nonlocal j
        m = j + 1
        while m + 1 < len(words) and not _ends(words[m]) and words[m + 1].start - words[m].end < 0.6:
            m += 1
        if j + 1 < len(words) and (not max_s or words[m].end - words[i].start <= max_s):
            j = m
            return True
        return False

    forward_first = j + 1 < len(words) and words[j + 1].start - words[j].end < 0.5
    for _ in range(8):
        if words[j].end - words[i].start >= want - 1.0:
            break
        if not ((grow_forward() or grow_back()) if forward_first else (grow_back() or grow_forward())):
            break
    start, end = words[i].start, words[j].end
    if max_s and end - start > max_s:                       # too long: drop setup first, keep the quote
        start = max(start, min(qstart, end - max_s))
    if min_s and end - start < min_s:
        start = max(0.0, end - min_s) if start > 0 else start
    return max(0.0, start - 0.12), end


def laugh_tail(levels: Sequence[float], hop: float, speech_end: float, max_tail: float = TAIL_MAX) -> float:
    """
    Seconds to keep after the last word: while the audio stays within 10 dB of the speech level (laughter,
    applause), up to max_tail. `levels` = dB per hop over the whole window; speech_end on the same clock.
    """
    k = int(speech_end / hop)
    speech = [v for v in levels[max(0, k - int(3 / hop)):k] if v > -70]
    if not speech:
        return 0.3
    ref = sorted(speech)[int(len(speech) * 0.7)]
    t = 0.0
    while t < max_tail and k + int(t / hop) < len(levels) and levels[k + int(t / hop)] > ref - 10:
        t += hop
    return round(max(0.3, min(max_tail, t + 0.25)), 2)


def rms_levels(path: str, hop: float = 0.05) -> List[float]:
    """dB per hop of a file's audio (mono 16 kHz through ffmpeg)."""
    import array
    import math
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                       capture_output=True, timeout=120)
    a = array.array("h", p.stdout)
    n = int(16000 * hop)
    out = []
    for s in range(0, len(a) - n + 1, n):
        chunk = a[s:s + n]
        e = sum(x * x for x in chunk) / n
        out.append(10 * math.log10(e / (32768.0 ** 2)) if e > 0 else -96.0)
    return out


# ------------------------------------------------------------------ the whole finder
_CLIP_MODEL: list = [None]
_MODEL_LOCK = __import__("threading").Lock()


def _whisper(path: str) -> List[W]:
    """
    Clip speech word by word. The clip's captions are read off these words, so they use a stronger model than the
    narration's alignment (CELEB_WHISPER_MODEL, default small.en; the narration model when they are the same).
    """
    from .. import config, transcribe
    name = os.environ.get("CELEB_WHISPER_MODEL", "small.en").strip()
    if not name or name == config.WHISPER_MODEL:
        return [W(w.text, w.start, w.end) for w in transcribe.transcribe_words(path, language="en")]
    with _MODEL_LOCK:
        if _CLIP_MODEL[0] is None:
            from faster_whisper import WhisperModel
            _CLIP_MODEL[0] = WhisperModel(name, device="cpu", compute_type="int8")
    segs, _ = _CLIP_MODEL[0].transcribe(path, language="en", word_timestamps=True, vad_filter=True, beam_size=5)
    out = []
    for s in segs:
        for w in s.words or []:
            if str(w.word).strip():
                out.append(W(str(w.word).strip(), float(w.start), float(w.end)))
    return out


def trim(src: str, dst: str, start: float, end: float, fade: float = 0.06) -> str:
    """Cut [start, end] of a downloaded window, re-encoded (frame-exact), with 60 ms fades on its audio."""
    dur = end - start
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", src, "-t", f"{dur:.3f}",
                    "-af", f"afade=t=in:d={fade},afade=t=out:st={max(0.0, dur - fade):.3f}:d={fade}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k",
                    "-ar", "48000", dst], check=True, timeout=300)
    return dst


def moment_in_window(window: str, offset: float, quote: str, *, min_s: float = 0.0, max_s: float = 0.0,
                     words: Optional[List[W]] = None) -> Optional[dict]:
    """Exact in/out inside a downloaded window (window clock), from whisper words + the audio's laugh tail."""
    words = words if words is not None else _whisper(window)
    if not words:
        return None
    score, qi, qj = match_quote(words, quote) if quote else (1.0, 0, len(words) - 1)
    if qi < 0 or score < 0.6:
        return None
    start, end = snap(words, qi, qj, min_s=min_s, max_s=max(0.0, max_s - 1.0) if max_s else 0.0)
    levels = rms_levels(window)
    tail = laugh_tail(levels, 0.05, end)
    nxt = next((w.start for w in words if w.start > end + 0.02), None)
    if nxt is not None:                       # the laugh, not the first word of the next sentence
        tail = max(0.15, min(tail, nxt - end - 0.08))
    end += tail
    inside = [W(w.text, w.start - start, w.end - start) for w in words if w.start >= start - 0.05 and w.start < end - 0.15]
    return {"start": start, "end": end, "score": score, "words": inside, "all": list(words),
            "quote_at": (words[qi].start - start, words[qj].end - start), "abs": (offset + start, offset + end)}


def find(who: Sequence[str], quote: str, where: str, work: str, *, min_s: float = 0.0, max_s: float = 0.0,
         video_id: str = "", start: Optional[float] = None, end: Optional[float] = None,
         max_candidates: int = 6, log: Callable = print, trim_clip: bool = True) -> Optional[Moment]:
    """The clip for one spot: a given URL (+ in/out), else search -> captions -> window -> whisper -> snap."""
    os.makedirs(work, exist_ok=True)
    pad_before, pad_after = SETUP_GROW + 3.0, 10.0
    tried: List[Tuple[str, dict]] = []
    if video_id:
        tried.append((video_id, {"id": video_id, "title": "", "channel": ""}))
    else:
        seen = set()
        for q in queries(who, quote, where):
            for c in ytdlp._yt_candidates(f"ytsearch10:{q}", require_cc=False, limit=10):
                if c["id"] not in seen:
                    seen.add(c["id"])
                    tried.append((c["id"], c))
            if len(tried) >= max_candidates * 2:
                break
        tried = [(c["id"], c) for c in rank([c for _, c in tried], who, where)][:max_candidates]
    for vid, meta in tried:
        if start is not None and end is not None and video_id:
            at, source = (start, end), "given"
        else:
            caps = fetch_captions(vid)
            if not caps:
                log(f"[celeb] {vid}: no captions")
                continue
            score, qi, qj = match_quote(caps, quote)
            log(f"[celeb] {vid} {meta.get('title', '')[:50]!r}: caption match {score:.2f}")
            if score < 0.72:
                continue
            at, source = (caps[qi].start, caps[qj].end), "captions"
        w0 = max(0.0, at[0] - pad_before)
        seconds = (at[1] + pad_after) - w0
        # A hero clip: the best picture the source has (ytdlp hero tier: AV1/VP9, 1440p downscaled when worth it).
        win = ytdlp._yt_fetch(vid, work, w0, seconds, timeout=600, audio=True, hero=True)
        if not win:
            log(f"[celeb] {vid}: window download failed")
            continue
        w0 = window_start(win, w0)                            # where the section really starts (fitted near an end)
        if source == "given":
            heard = _whisper(win)
            s_rel, e_rel = start - w0, end - w0                # the owner's own in/out win; words for captions
            got = {"start": s_rel, "end": e_rel, "score": 1.0, "abs": (start, end), "quote_at": (0.0, 0.0),
                   "all": heard, "words": [W(w.text, w.start - s_rel, w.end - s_rel) for w in heard
                                           if s_rel - 0.05 <= w.start and w.end <= e_rel + 0.3]}
        else:
            got = moment_in_window(win, w0, quote, min_s=min_s, max_s=max_s)
        if not got:
            log(f"[celeb] {vid}: quote not heard in the window")
            continue
        dst = os.path.join(work, f"clip_{vid}_{int(got['abs'][0] * 1000)}.mp4") if trim_clip else ""
        if dst:                                                # (the reel plays from the window itself)
            trim(win, dst, got["start"], got["end"])
        return Moment(video_id=vid, title=meta.get("title", ""), channel=meta.get("channel", ""),
                      start=round(got["abs"][0], 2), end=round(got["abs"][1], 2), score=round(got["score"], 3),
                      path=dst, words=got["words"], quote_at=got["quote_at"], source=source,
                      window=win, window_at=w0, window_words=list(got.get("all") or []))
    return None


def window_start(path: str, asked: float) -> float:
    """The section's real start in the source video: ytdlp._yt_fetch names its file yt_<id>_<start ms>_<len ms>_..."""
    m = re.search(r"yt_[\w-]{11}_(\d+)_(\d+)_", os.path.basename(path or ""))
    return int(m.group(1)) / 1000.0 if m else asked
