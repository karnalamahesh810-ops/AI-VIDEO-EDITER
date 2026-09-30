"""
Narration alignment.

This is the step that makes clips land on the right words. We transcribe the
narration audio with word-level timestamps, then cut the timeline where a
human editor would (human_cuts): on sentence ends, clause breaks and breaths,
where the line moves to a new place or person, and where a number or danger
word needs its proof shot - each beat as long as what it says asks for, never
longer on screen than MAX_SCENE_SECONDS. HUMAN_CUTS=0 restores the old clause
rhythm around the 7-second GoMotion grid (_rhythm_cuts).

If a script was pasted, we still transcribe (for timing) but snap the recognised
words back onto the *authored* script text, so captions read exactly as written
rather than as whisper heard them.
"""
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import List, Optional, Sequence
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


def segment_words(words: List[Word], origin: Optional[float] = None,
                  until: Optional[float] = None) -> List[Segment]:
    """
    The narration's beats: one visual each, in word order.

    config.HUMAN_CUTS (the default): human_cuts - where an editor would cut,
    each beat's length following its content, MIN/MAX_SCENE_SECONDS bounding
    its time on screen. `origin` is where the visual track starts (0.0 for a
    whole narration: the first shot is up from frame 0) and `until` where it
    ends (the audio's end); left out, the first word's start and the last
    word's end. Off: the old clause rhythm around TARGET_SCENE_SECONDS.
    """
    if not words:
        return []
    if getattr(config, "HUMAN_CUTS", True):
        return human_cuts(words, origin=origin, until=until)
    return _rhythm_cuts(words)


def _rhythm_cuts(words: List[Word]) -> List[Segment]:
    """
    Group words into clause-length segments targeting TARGET_SCENE_SECONDS
    (the cutting before 2026-09-30, kept for A/B: HUMAN_CUTS=0).

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


# --------------------------------------------------------------------------- #
# Human-like cuts (the owner, 2026-09-30)
# --------------------------------------------------------------------------- #
#
# The clause rhythm above cuts as soon as a beat is past TARGET at any comma or
# breath, so nearly every shot lands a little past it: the Texas flood video
# played a ~6-7 s shot after a ~6-7 s shot. An editor cuts where the narration
# turns - a sentence ends, a clause or a breath, a new place or person is
# named, a number or a danger word needs its proof shot - and lets the length
# follow what is said: a burst of action cut short, an establishing line held.
#
# human_cuts() chooses all of a narration's cuts at once (dynamic programming
# over the word boundaries). A candidate beat costs how far its time on screen
# is from the length its own words ask for (_target), how poor a place its
# closing cut is (_cut_quality: 1 at a sentence end, ~0.05 inside a name or
# after "the"), and each extra new name it crams in. Its time ON SCREEN - from
# its first word to the next beat's first word, since the shot stays up through
# the pause - must lie within MIN..MAX_SCENE_SECONDS; the last beat may run
# short. Only a silence longer than MAX can force a longer shot.

_W_LENGTH = 2.0      # (screen length - target) / target, squared: 50% off costs 0.5
_W_CUT = 1.5         # x (1 - cut quality): a mid-clause cut costs ~1.2, a sentence end 0
_W_NAMES = 0.6       # each new name past the first inside one beat
_W_SHORT_LAST = 3.0  # the last beat under MIN (it only runs to the narration's end)
_HARD = 1000.0       # a beat outside MIN..MAX: only when nothing else fits
_LEAD_MAX = 1.5      # silence before the first word / after the last that counts on screen

_ABBREVIATIONS = {"dr", "mr", "mrs", "ms", "gov", "sen", "rep", "lt", "col", "capt", "sgt", "prof", "st",
                  "rev", "gen", "jr", "sr", "adm", "cmdr", "maj", "cpl", "mt", "ft", "vs", "no", "inc", "co"}
_CLOSERS = "\"'”’)]"
# A new clause starts on these: an editor cuts in front of them. The second
# set is also a preposition half the time ("the coastline | since Wednesday").
_CONNECTORS = {"and", "but", "so", "because", "while", "although", "though", "yet", "whereas", "meanwhile",
               "then", "or", "unless"}
_MAYBE_CONNECTORS = {"as", "when", "until", "after", "before", "where", "since", "which", "once"}
# A shot never ends on these: they belong to the words after them.
_GLUE = {"the", "a", "an", "of", "to", "in", "on", "at", "for", "with", "from", "by", "into", "onto", "over",
         "under", "about", "this", "that", "these", "those", "my", "your", "his", "her", "its", "our", "their",
         "some", "any", "no", "every", "each", "very", "more", "most", "less", "than", "is", "are", "was",
         "were", "be", "been", "being", "has", "have", "had", "will", "would", "could", "should", "can",
         "may", "might", "must", "not", "and", "or", "but", "so", "if", "because", "while", "when", "where",
         "which", "who", "whose", "whom", "it's", "there's", "we're", "they're", "i'm", "you're", "he's",
         "she's", "just", "only", "even", "also", "through", "across", "along", "toward", "towards", "near",
         "around", "against", "between", "among", "per", "like", "as", "then", "what", "how", "why", "all",
         "both", "such", "another", "other", "whole", "entire", "several", "many", "few", "much", "own",
         "same", "first", "next", "last", "i", "we", "they", "he", "she", "it", "you", "there", "here",
         "up", "down", "out", "off", "within", "without", "during", "despite", "throughout", "beyond",
         "behind", "below", "above", "beneath", "inside", "outside", "upon", "via", "past", "nearly",
         "almost", "about", "roughly", "approximately", "estimated", "least", "whether", "into", "get",
         "gets", "got", "getting", "become", "became", "becomes", "keep", "keeps", "kept", "let", "let's",
         "going", "gonna", "want", "wanted", "need", "needs", "right", "still", "already", "really",
         "actually", "quite", "too", "extremely", "incredibly", "completely", "totally", "fully", "partly"}
# Words that belong to the word before them: never the first word of a shot.
_BINDS_BACK = {"of", "'s", "than", "to"}
# An article or possessive two words back: the word between is an adjective
# of the same noun phrase ("a powerful | Northeaster").
_DETERMINERS = {"a", "an", "the", "this", "that", "these", "those", "its", "their", "his", "her", "our", "your",
                "my", "every", "each", "another", "some", "no"}
# Words in front of a figure that belong to it: "nearly | 2 feet" is one phrase.
_NUMBER_LEADS = {"nearly", "almost", "about", "around", "roughly", "approximately", "estimated", "over",
                 "under", "up", "some", "another", "least", "than", "just", "only", "more", "less", "all"}
# A comma is a cut when a new clause or phrase follows it, not inside a list
# of adjectives ("a slow moving, | prolonged event").
_CLAUSE_OPENERS = {"it", "it's", "they", "they're", "we", "we're", "he", "she", "you", "i", "i'm", "this",
                   "that", "there", "there's", "these", "those", "the", "a", "an", "its", "their", "our",
                   "in", "at", "on", "from", "with", "by", "for", "after", "before", "during", "since",
                   "which", "who", "where", "when", "while", "if", "but", "so", "and", "or", "as", "then",
                   "now", "here", "here's", "what", "some", "many", "most", "all", "every", "no", "not",
                   "officials", "residents", "crews", "people", "folks"}
# "in Atlantic City": the cut goes in front of the preposition, so the shot of
# the town is up as its name is said.
_PLACE_PREPS = {"in", "at", "near", "across", "from", "into", "through", "over", "along", "outside",
                "inside", "around", "toward", "towards", "to", "off", "on", "up", "down"}
_NOT_NAMES = {"i", "i'm", "i've", "i'll", "i'd", "monday", "tuesday", "wednesday", "thursday", "friday",
              "saturday", "sunday", "january", "february", "march", "april", "may", "june", "july",
              "august", "september", "october", "november", "december", "god", "ok", "okay", "am", "pm",
              "a.m", "p.m", "edt", "est", "cdt", "cst", "pdt", "pst", "mdt", "mst", "utc", "gmt"}
_NUMBER_WORDS = {"two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
                 "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
                 "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred",
                 "hundreds", "thousand", "thousands", "million", "millions", "billion", "billions",
                 "dozen", "dozens", "half"}
# Action and danger: a line full of them is cut short, and a cut lands in
# front of one ("...and then | swept away") for the shot that proves it.
_INTENSE = re.compile(
    r"^(?:flood\w*|surg\w+|swept|sweep\w*|trap\w*|rescu\w*|dead|death\w*|died|dies|dying|kill\w*|deadl\w*|"
    r"destroy\w*|destruct\w*|collaps\w*|evacuat\w*|emergenc\w*|warning\w*|catastroph\w*|devastat\w*|"
    r"record\w*|crash\w*|slam\w*|batter\w*|pound\w*|raging|rage[ds]?|explod\w*|explosion\w*|burst\w*|"
    r"breach\w*|overwhelm\w*|overtop\w*|torrent\w*|violent\w*|fierce\w*|furious\w*|massive|huge|"
    r"enormous|terrif\w*|horrif\w*|chaos|chaotic|panic\w*|scream\w*|fires?|flames?|burn\w*|blaze\w*|"
    r"inferno|tornado\w*|twister\w*|hurricane\w*|gusts?|mph|stranded|submerg\w*|underwater|washed|"
    r"ripp\w*|torn|tore|shatter\w*|smash\w*|sudden\w*|instantly|roar\w*|rush\w*|swell\w*|danger\w*|"
    r"threat\w*|damag\w*|debris|powerless|outages?|blackout\w*|injur\w*|missing|fatal\w*|victims?|"
    r"crush\w*|buried|blizzard\w*|whiteout\w*|lightning|hail\w*|swamp\w*|inundat\w*|toppl\w*|"
    r"uproot\w*|capsiz\w*|sinking|sank|drown\w*)$")
# Setting and description: a line full of these is an establishing shot, held.
_CALM = re.compile(
    r"^(?:quiet\w*|calm\w*|peace\w*|beautiful|scenic|histor\w*|known|famous|home|sits?|lies|located|"
    r"stretch\w*|overlook\w*|town|towns|village\w*|communit\w*|shoreline|coastline|skyline|landscape\w*|"
    r"views?|morning|sunrise|sunset|decades|generations|once|tradition\w*|popular|tourist\w*|resort\w*|"
    r"nestled|surround\w*|miles?|region|normally|usually|typically|summer|seasons?|beach|beaches|"
    r"boardwalk|harbou?r|bay|island|coast|valley|residents?|families|neighbou?rhoods?|streets?)$")


def _norm_word(text: str) -> str:
    t = re.sub(r"[^\w'.\-]", "", (text or "").replace("’", "'")).lower().strip("'.-")
    return t[:-2] if t.endswith("'s") else t


def _ends_sentence(text: str) -> bool:
    t = (text or "").rstrip(_CLOSERS)
    if not t or t[-1] not in ".!?":
        return False
    if t[-1] == "." and (_norm_word(t) in _ABBREVIATIONS or re.fullmatch(r"(?:[A-Za-z]\.)+", t)):
        return False                                       # "Dr.", "U.S."
    return True


def _ends_clause(text: str) -> bool:
    t = (text or "").rstrip(_CLOSERS)
    return bool(t) and (t[-1] in ";:—–" or t.endswith("--") or (t[-1] == "-" and len(t) > 1 and not t[-2].isalnum()))


def _ends_comma(text: str) -> bool:
    return (text or "").rstrip(_CLOSERS).endswith(",")


def _is_number(norm: str) -> bool:
    return bool(re.search(r"\d", norm)) or norm in _NUMBER_WORDS


def _capitalised(text: str) -> bool:
    m = re.search(r"[A-Za-z]", text or "")
    return bool(m) and m.group(0).isupper()


def _cut_features(words: Sequence[Word]) -> dict:
    """Per-word and per-boundary facts the cost reads (lists aligned to the words)."""
    n = len(words)
    norms = [_norm_word(w.text) for w in words]
    sentence_start = [k == 0 or _ends_sentence(words[k - 1].text) for k in range(n)]
    # A name: a capitalised word that does not merely start a sentence.
    proper = [(_capitalised(words[k].text) and not sentence_start[k] and norms[k] not in _NOT_NAMES
               and not _is_number(norms[k])) for k in range(n)]
    # Where a name starts, and whether it is NEW (not said in the last ~25 words).
    new_name = [False] * n
    recent: List[tuple] = []                # (word index, name)
    k = 0
    while k < n:
        if proper[k] and (k == 0 or not proper[k - 1] or _ends_comma(words[k - 1].text)):
            m = k
            while m + 1 < n and proper[m + 1] and not _ends_comma(words[m].text) \
                    and not _ends_sentence(words[m].text):
                m += 1
            name = " ".join(norms[k:m + 1])
            recent = [(at, nm) for at, nm in recent if at >= k - 25]
            new_name[k] = not any(nm == name for _at, nm in recent)
            recent.append((k, name))
            k = m + 1
            continue
        k += 1
    intense = [1.0 if _INTENSE.match(t) else 0.0 for t in norms]
    number = [1.0 if _is_number(t) else 0.0 for t in norms]
    calm = [1.0 if _CALM.match(t) else 0.0 for t in norms]
    exclaim = [1.0 if (w.text or "").rstrip(_CLOSERS).endswith("!") else 0.0 for w in words]

    quality = [0.0] * (n + 1)
    for k in range(1, n):
        prev, nxt = words[k - 1], words[k]
        pn, nn = norms[k - 1], norms[k]
        pause = max(0.0, float(nxt.start) - float(prev.end))
        punct = True
        comma = False
        if _ends_sentence(prev.text):
            q = 1.0
        elif _ends_clause(prev.text):
            q = 0.8
        elif _ends_comma(prev.text):
            comma = True
            if nn in _CLAUSE_OPENERS or nn in _CONNECTORS or nn in _MAYBE_CONNECTORS or proper[k] \
                    or number[k] or nn in _NUMBER_LEADS:
                q = 0.7                                       # a new clause or phrase follows
            else:
                q = 0.45                                      # "a slow moving, | prolonged event"
        else:
            q, punct = 0.2, False
        if pause >= 0.75:
            q = max(q, 0.85)                                  # a breath
        elif pause >= 0.5:
            q = max(q, 0.7)
        elif pause >= 0.35:
            q = max(q, 0.55)
        elif pause >= 0.2:
            q = max(q, 0.3)
        if nn in _CONNECTORS:
            q = max(q, 0.6)                                   # a new clause starts here
        elif nn in _MAYBE_CONNECTORS:
            q = max(q, 0.45)
        # A new name, a figure or a danger word is a fair place to cut, not a
        # strong one: the reference channel's cuts do not chase them (a place
        # name had a cut within a second 17% of the time, chance 14%).
        if new_name[k]:
            q = max(q, 0.35)                                  # a new place, person or thing
        if nn in _PLACE_PREPS and k + 1 < n and new_name[k + 1]:
            q = max(q, 0.45)                                  # "... | in Atlantic City"
        figure = (number[k] and not number[k - 1] and pn not in _NUMBER_LEADS) or \
            (nn in _NUMBER_LEADS and k + 1 < n and number[k + 1])
        if figure or (intense[k] and not pn.endswith("ly") and not proper[k - 1]):
            q = max(q, 0.3)                                   # the proof shot: "... | 90,000 homes"
        # Never inside a phrase, whatever else points at the spot: below zero,
        # so a cut there costs more than a short beat or two elsewhere.
        if not punct:
            if pn in _GLUE or (proper[k - 1] and (proper[k] or number[k])):
                q = min(q, -0.6)                              # "the | storm", "Long | Beach", "Highway | 12"
            elif k >= 2 and norms[k - 2] in _DETERMINERS and not _ends_comma(words[k - 2].text):
                q = min(q, -0.2)                              # "a powerful | Northeaster", "the heavy | rain"
            elif number[k - 1] and not number[k] and nn not in _CONNECTORS and nn.isalpha():
                q = min(q, -0.3)                              # "eleven | feet"
            elif nn in _BINDS_BACK:
                q = min(q, -0.3)                              # "south | of Long Island", "one | of them"
        elif comma and _capitalised(prev.text) and not sentence_start[k - 1] and proper[k]:
            q = min(q, 0.15)                                  # "Duck, | North Carolina": one place
        quality[k] = q
    return {"quality": quality, "new_name": new_name, "intense": intense, "number": number,
            "calm": calm, "exclaim": exclaim}


def _prefix(values: Sequence[float]) -> List[float]:
    out = [0.0]
    for v in values:
        out.append(out[-1] + v)
    return out


def cut_lengths() -> tuple:
    """(min, fast, target, slow, max) seconds on screen, from the config (the style's)."""
    lo = max(0.5, float(config.MIN_SCENE_SECONDS))
    hi = max(lo + 0.5, float(config.MAX_SCENE_SECONDS))
    target = min(hi, max(lo, float(config.TARGET_SCENE_SECONDS)))
    fast = float(getattr(config, "CUT_FAST_SECONDS", 0) or 0) or 0.65 * target
    slow = float(getattr(config, "CUT_SLOW_SECONDS", 0) or 0) or 1.3 * target
    fast = min(target, max(lo, fast))
    slow = max(target, min(hi, slow))
    return lo, fast, target, slow, hi


def human_cuts(words: Sequence[Word], origin: Optional[float] = None,
               until: Optional[float] = None) -> List[Segment]:
    """
    The narration cut the way an editor cuts it (see the section comment):
    the set of cuts with the lowest total cost, every beat's time on screen
    within MIN..MAX_SCENE_SECONDS where the narration allows it.
    """
    words = list(words)
    n = len(words)
    if not n:
        return []
    lo, fast, target, slow, hi = cut_lengths()
    hook_until = float(getattr(config, "HOOK_SECONDS", 0) or 0)
    hook_factor = float(getattr(config, "CUT_HOOK_FACTOR", 1.0) or 1.0)
    first = float(words[0].start)
    last = float(words[-1].end)
    # Where each beat starts on screen: its first word; the first beat from
    # the start of the visual track, the last one to its end (the silence
    # around the narration counts for at most _LEAD_MAX).
    # A beat that opens a sentence goes up CUT_LEAD_SECONDS early (half that
    # after a clause), in the pause; the costs see those real screen times.
    lead = max(0.0, float(getattr(config, "CUT_LEAD_SECONDS", 0.0) or 0.0))
    starts = [first] + [max(float(words[k - 1].end),
                            float(words[k].start) - (lead if _ends_sentence(words[k - 1].text) else lead / 2.0))
                        if lead else float(words[k].start) for k in range(1, n)]
    if origin is not None:
        starts[0] = max(min(first, float(origin)), first - _LEAD_MAX)
    end = last
    if until is not None:
        end = min(max(last, float(until)), last + _LEAD_MAX)
    starts.append(max(end, starts[-1]))
    for k in range(1, n + 1):
        starts[k] = max(starts[k], starts[k - 1])

    f = _cut_features(words)
    quality = f["quality"]
    p_int, p_num, p_calm, p_exc = (_prefix(f["intense"]), _prefix(f["number"]),
                                   _prefix(f["calm"]), _prefix(f["exclaim"]))
    p_name = _prefix([1.0 if x else 0.0 for x in f["new_name"]])

    def target_of(i: int, j: int) -> float:
        # Action and danger words ask for a shorter shot (CUT_FAST_SECONDS);
        # setting, description and figures - gauge readings, counts, times,
        # which the reference channel holds LONGER - for a longer one.
        count = max(4, j - i)
        intense = min(1.0, 2.2 * ((p_int[j] - p_int[i]) + (p_exc[j] - p_exc[i])) / count)
        calm = min(1.0, 3.0 * ((p_calm[j] - p_calm[i]) + 0.5 * (p_num[j] - p_num[i])) / count) * (1.0 - intense)
        t = target - (target - fast) * intense + (slow - target) * calm
        if hook_factor != 1.0 and float(words[i].start) < hook_until:
            t *= hook_factor
        return min(hi, max(lo, t))

    inf = float("inf")
    best = [inf] * (n + 1)
    back = [0] * (n + 1)
    best[0] = 0.0
    for j in range(1, n + 1):
        cut = _W_CUT * (1.0 - quality[j]) if j < n else 0.0
        i = j - 1
        while i >= 0:
            length = starts[j] - starts[i]
            if length > hi and i < j - 1:
                break                              # every earlier start is longer still
            if best[i] < inf:
                t = target_of(i, j)
                cost = best[i] + _W_LENGTH * ((length - t) / t) ** 2 + cut
                extra = (p_name[j] - p_name[i + 1]) - 1.0 if j - i > 1 else 0.0
                if extra > 0:
                    cost += _W_NAMES * extra
                if length > hi:
                    cost += _HARD + 100.0 * (length - hi)
                elif length < lo:
                    if j == n:
                        cost += _W_SHORT_LAST * (lo - length) / lo
                    else:
                        cost += _HARD + 100.0 * (lo - length)
                if cost < best[j]:
                    best[j], back[j] = cost, i
            i -= 1

    bounds = [n]
    while bounds[-1] > 0:
        bounds.append(back[bounds[-1]])
    bounds.reverse()
    out: List[Segment] = []
    for i, j in zip(bounds, bounds[1:]):
        chunk = words[i:j]
        text = re.sub(r"\s+([,.!?;:])", r"\1", " ".join(w.text for w in chunk).strip())
        # The picture changes in the breath before a new sentence (the
        # reference: a median 0.14 s early), never before the last word of
        # the beat in front; the first beat starts on its first word.
        start = starts[i] if i > 0 else float(chunk[0].start)
        out.append(Segment(text=text, start=start, end=float(chunk[-1].end), words=list(chunk)))
    return out


def screen_lengths(segments: Sequence[Segment], origin: Optional[float] = 0.0,
                   until: Optional[float] = None) -> List[float]:
    """Each beat's time on screen (to the next beat's start; the first from `origin`, the last to `until`)."""
    if not segments:
        return []
    starts = [float(s.start) for s in segments]
    if origin is not None:
        starts[0] = min(starts[0], float(origin))
    tail = float(until) if until is not None else float(segments[-1].end)
    return [max(0.0, b - a) for a, b in zip(starts, starts[1:] + [max(tail, starts[-1])])]


def cut_stats(segments: Sequence[Segment], origin: Optional[float] = 0.0,
              until: Optional[float] = None) -> dict:
    """Beats, cuts per minute and the spread of time on screen (for logs, tests and calibration)."""
    lengths = screen_lengths(segments, origin, until)
    if not lengths:
        return {"beats": 0}
    s = sorted(lengths)

    def pct(p: float) -> float:
        k = (len(s) - 1) * p
        a, b = int(k), min(len(s) - 1, int(k) + 1)
        return round(s[a] + (s[b] - s[a]) * (k - a), 2)

    mean = sum(s) / len(s)
    sd = (sum((x - mean) ** 2 for x in s) / len(s)) ** 0.5
    total = sum(lengths)
    return {"beats": len(s), "cpm": round(len(s) / max(total / 60.0, 1e-6), 2), "mean": round(mean, 2),
            "p10": pct(0.10), "p25": pct(0.25), "median": pct(0.5), "p75": pct(0.75), "p90": pct(0.90),
            "min": round(s[0], 2), "max": round(s[-1], 2), "cv": round(sd / mean, 3) if mean else 0.0}


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
