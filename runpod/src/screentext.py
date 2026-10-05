"""
The words a graphic puts on screen (the owner, 2026-10-05: "sometimes it's saying
some random words - we got the script and the narration - and sometimes the text
is super long").

Measured on two real timelines (Glen Canyon 5 min, Yellowstone 29 min): of 216
text fields on screen, 33 were never said near their graphic and 39 ran past six
words or 32 letters. They came from five places:

  - the photo looks wrote the picture's search subject as their caption
    ("LAKE POWELL LOW WATER EXPOSING PREVIOUSLY SUBMERGED TERRAIN"),
  - the director's one-word "highlight" became a key phrase on its own
    ("biggest", "concrete", "candle", "That's", "isn't", "skip"),
  - fragments cut out of a line ("BLUE WATER THE", "THE DANGER HERE ISNT ALWAYS THE",
    ". The super volcano is real", "AROUND IT. HORSES CAME TO DRINK"),
  - list and split labels the narration never said ("Boat ramps closed" on a line
    about horses at a water hole),
  - typing artefacts ("That�s the part that kills").

The rule, for every text, caption, document and list look the planner lays:

  - the words are the narration's own, copied from the line (or the next lines
    the graphic may wait for): a named entity, a number with its unit, a date,
    or a key phrase of two to six words - with the narration's spelling,
    apostrophes and capitals;
  - never a filler word or a phrase with less than two words that carry meaning
    (one proper name, acronym, number or defined term is enough);
  - never a fragment: no leading "or"/"and", no trailing "the"/"isn't always",
    never across a sentence's end;
  - a headline look holds at most HEAD_WORDS words / HEAD_CHARS letters, a
    sentence look (typed line, statement, quote) SENTENCE_WORDS / SENTENCE_CHARS,
    a document's headline DOC_WORDS / DOC_CHARS; longer text is cut down to the
    key phrase it holds (a name, a figure, a superlative), else the look is left
    out - the planner then tries the next look, or none.

Pure functions, no I/O: the planner (src/treatments.py `_place`, `_photo`) calls
clean_props for each look it is about to lay; audit() is the last pass over a
finished plan.
"""
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

HEAD_WORDS = 6
HEAD_CHARS = 32
SENTENCE_WORDS = 12
SENTENCE_CHARS = 64      # two lines of HEAD_CHARS
DOC_WORDS = 12          # a document's headline runs to two or three lines of serif type
DOC_CHARS = 72
LABEL_WORDS = 6
LABEL_CHARS = 32
# A photo's caption names what is in the picture: a place, a person, a thing.
CAPTION_WORDS = 5
CAPTION_CHARS = 32

# Cues whose looks show a sentence (two short lines at most), not a headline.
SENTENCE_CUES = {"typewriter", "statement", "fact", "question", "quote", "recording", "quote-official",
                 "contrast-line", "figure-context"}
# Cues whose words are a figure's, a date's, a name's or a place's: decided where they are made.
OWN_WORDS_CUES = {"percent", "change", "change-length", "big-number", "money", "measurement", "ratio", "count",
                  "then-now", "series", "shares", "compare-values", "ranking", "money-compare", "sequence", "years",
                  "span", "steps", "time-span", "date", "datetime", "time-of-day", "age", "person", "person-full",
                  "place", "route", "section", "forecast-rain", "forecast-wind", "figure-record", "figure-rate",
                  "figure-share", "lower-third", "chapter"}
TEXT_CATEGORIES = {"TEXT", "HEADLINES", "CALLOUTS", "QUOTES"}

# Words that never carry a graphic on their own.
_STOP = frozenset("""
a an the and or but nor so yet for of to in on at by from with as into onto over under about than then
this that these those it its it's they them their there here he she his her him we us our you your i me my
is are was were be been being am do does did done have has had having will would shall should can could
may might must just really very also even still too quite rather somewhat pretty such
that's it's isn't wasn't aren't weren't don't doesn't didn't can't couldn't won't wouldn't shouldn't
there's here's what's who's he's she's they're we're you're i'm let's
what which who whom whose when where why how whether if because since while though although unless until
up down out off again further once
some any each other another more less most least much many few several lot lots
thing things way ways part kind sort something anything everything nothing someone anyone everyone stuff
one ones get gets got make makes made go goes went come comes came take takes took see sees saw look looks
like say says said tell tells told know knows knew think thinks thought
""".split())
# Glue a phrase may not start with (it is the end of another thought) ...
_LEAD = frozenset("and or but nor so yet because then of to with which that as than for from by into "
                  "while whereas although though since".split())
# ... and words a phrase may not end on (the rest of the thought was cut off).
_DANGLING = _STOP | frozenset("always never ever just still even only almost nearly about around "
                              "not no very more less than like into".split())
# Words that DO carry meaning in a short phrase ("not overdue", "without any warning", "no warning signs").
_MODIFIERS = frozenset("not no never without every all only first last best worst".split())
# A sentence's ordinary first words, capitalised only because they open it.
_OPENERS = frozenset("""after before during today tonight yesterday tomorrow now then still yet once instead meanwhile
however but and so because although though while when where if as since until unless across around between
nearly almost roughly about over under inside outside behind beyond within without imagine picture remember
look listen consider""".split())

_MOJIBAKE = (("â€™", "’"), ("â€˜", "‘"), ("â€œ", "“"),
             ("â€\u009d", "”"), ("â€”", "—"), ("â€“", "–"),
             ("Â ", " "), ("Â ", " "))
_TOKEN = re.compile(r"[A-Za-z0-9À-ɏ]+(?:['’.,\-][A-Za-z0-9À-ɏ]+)*")
_SENTENCE_END = re.compile(r"[.!?;:]+(?:[\"”’)\]]*)\s+|[—–]\s*|\s+-\s+")
_PAREN = re.compile(r"\s*[(\[][^)\]]*[)\]]")
_NUMBERISH = re.compile(r"^\$?\d[\d,.]*%?$|^\d+(?:st|nd|rd|th|s)$", re.I)


def repair(text) -> str:
    """Typing artefacts out: mojibake quotes, a replacement mark inside a word, runs of spaces,
    leading punctuation (". The super volcano is real")."""
    s = str(text or "")
    for bad, good in _MOJIBAKE:
        s = s.replace(bad, good)
    s = re.sub(r"(?<=[A-Za-z])�(?=[A-Za-z])", "’", s)
    s = s.replace("�", "")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^[\s.,;:!\-–—|/]+", "", s)
    return s.strip()


def _norm(tok: str) -> str:
    """A token as the comparison reads it: lower case, apostrophes, commas and dots out ("3,516" = "3516")."""
    t = tok.lower().replace("’", "'")
    t = re.sub(r"[^a-z0-9À-ɏ]", "", t)
    return t


def tokens(text: str) -> List[Tuple[str, str, int, int]]:
    """(raw, normalised, start, end) for every word of `text` (letters and digits, inner ' - . , kept)."""
    out = []
    for m in _TOKEN.finditer(text or ""):
        raw = m.group(0).rstrip(".,")
        n = _norm(raw)
        if n:
            out.append((raw, n, m.start(), m.start() + len(raw)))
    return out


def _sentence_starts(text: str) -> set:
    """Character offsets where a sentence (or a clause after a dash) starts."""
    starts = {0}
    for m in _SENTENCE_END.finditer(text or ""):
        starts.add(m.end())
    return starts


def proper_at(text: str, start: int, raw: str) -> bool:
    """The word at `start` is a name: capitalised where a sentence does not begin, or an acronym."""
    if len(raw) >= 2 and raw.isupper() and any(ch.isalpha() for ch in raw):
        return True
    if not raw[:1].isupper():
        return False
    before = (text or "")[:start].rstrip()
    if not before or before[-1] in ".!?\"“:":
        return False
    return start not in _sentence_starts(text)


def is_number(raw: str) -> bool:
    return bool(_NUMBERISH.match(raw.replace("’", "'")))


def content_count(phrase_toks: Sequence[str]) -> int:
    """How many words of the phrase carry meaning (the negations and "first", "only"... count)."""
    return sum(1 for t in phrase_toks if t not in _STOP or t in _MODIFIERS)


def find(phrase: str, narration: str) -> Optional[Tuple[int, int, int, int]]:
    """
    Where `phrase` stands word for word in `narration`: (first token index, last token index + 1,
    start char, end char), ignoring case, apostrophes and punctuation; None when it is not there.
    """
    want = [n for _r, n, _a, _b in tokens(phrase)]
    if not want:
        return None
    have = tokens(narration)
    hn = [n for _r, n, _a, _b in have]
    k = len(want)
    for i in range(len(hn) - k + 1):
        if hn[i:i + k] == want:
            return i, i + k, have[i][2], have[i + k - 1][3]
    return None


def _crosses_sentence(narration: str, a: int, b: int) -> bool:
    """The span a..b runs over the end of a sentence ("AROUND IT. HORSES CAME TO DRINK")."""
    inner = (narration or "")[a:b]
    return bool(re.search(r"[.!?;]\s+\S", inner))


def _clause_end(narration: str, at: int) -> bool:
    """The narration's thought ends at char `at`: punctuation (or nothing) follows."""
    rest = (narration or "")[at:].lstrip("\"”’')]")
    return not rest.strip() or rest[:1] in ".!?;:,—–" or rest.startswith(" -")


def _trim(narration: str, toks: list, i: int, j: int) -> Tuple[int, int, bool]:
    """
    Drop leading glue and trailing dangling words from tokens i..j; (i, j, anything dropped). A
    phrase that ends where its sentence or clause ends keeps its last word ("When is the next one?").
    """
    cut = False
    while i < j and toks[i][1] in _LEAD:
        i += 1
    if j > i and _clause_end(narration, toks[j - 1][3]):
        return i, j, False
    while j > i and toks[j - 1][1] in _DANGLING and not is_number(toks[j - 1][0]):
        j -= 1
        cut = True
    return i, j, cut


def _caps_like(source: str) -> bool:
    letters = [ch for ch in source if ch.isalpha()]
    return bool(letters) and sum(1 for ch in letters if ch.isupper()) / len(letters) > 0.85


def _cased(slice_: str, like: str) -> str:
    """The narration's words, in capitals when the look asked in capitals, else with a capital first letter."""
    s = slice_.strip()
    if _caps_like(like):
        return s.upper()
    return s[:1].upper() + s[1:] if s else s


def _has_name(narration: str, toks: list, i: int, j: int) -> bool:
    return any(proper_at(narration, toks[k][2], toks[k][0]) or is_number(toks[k][0]) for k in range(i, j))


def meaningful(narration: str, toks: list, i: int, j: int, term: bool = False) -> bool:
    """Two words that carry meaning, or one name, acronym or number (a defined term: one long word)."""
    norm = [toks[k][1] for k in range(i, j)]
    n = content_count(norm)
    if n >= 2:
        return True
    if n == 1:
        k = next(k for k in range(i, j) if toks[k][1] not in _STOP or toks[k][1] in _MODIFIERS)
        raw = toks[k][0]
        if proper_at(narration, toks[k][2], raw) or is_number(raw):
            return True
        if term and len(toks[k][1]) >= 5:
            return True
    return False


# A capitalised word ("Powell", "O'Neill", "U.S", "St.Louis" - a dot only inside a word: a sentence's
# full stop never joins two names, "Yellowstone. Under").
_CAPWORD = r"(?:[A-Z](?:[A-Za-zÀ-ɏ'’-]|\.(?=[A-Za-z]))*|[A-Z]{2,})"
_PROPER_RUN = re.compile(r"\b" + _CAPWORD + r"(?:\s+(?:of|the|de|del|la|du|von|van|and|on)\s+" + _CAPWORD
                         + r"|\s+(?:" + _CAPWORD + r"|\d+))*")
_SUPERLATIVE = re.compile(r"\b((?:the\s+)?(?:largest|biggest|worst|lowest|highest|deepest|driest|hottest|wettest|"
                          r"longest|oldest|fastest|deadliest|costliest|first|last|only|most\s+\w+)"
                          r"(?:\s+[a-z][\w'-]*){1,3})", re.I)
_FIGURE = re.compile(r"\$?\d[\d,]*(?:\.\d+)?(?:\s*(?:%|percent|million|billion|thousand|trillion))?"
                     r"(?:\s+(?:cubic\s+|square\s+)?[a-z][a-z-]*){0,2}", re.I)
# Places and things whose generic word alone names nothing ("Lake" of "Lake Powell").
_GENERIC = frozenset("""lake lakes river rivers dam dams canyon canyons valley mount mountain mountains bay
national state states county city town park forest desert island islands sea ocean gulf basin plain plains creek
falls fall university college bureau department office agency service center centre survey observatory north south
east west northern southern eastern western upper lower old new great little big""".split())


def entities(narration: str, title: bool = False) -> List[str]:
    """
    Named things in the narration, in order: runs of capitalised words that are names, not sentence
    starts. `title`: the text is a label or a picture's subject ("Lake Powell low water"), where a
    capitalised first word is a name too.
    """
    out = []
    for m in _PROPER_RUN.finditer(narration or ""):
        toks = tokens(m.group(0))
        # a run opening a sentence keeps only its names ("Then Lake Powell" -> "Lake Powell")
        base = m.start()
        k = 0
        # (a capitalised word opening a sentence is part of the name when a name follows it -
        # "Lake Powell dropped" - unless it is a sentence's ordinary first word: "Then", "Because")
        multi = len(toks) >= 2
        while k < len(toks) and not ((title or (multi and k + 1 < len(toks))) and toks[k][0][:1].isupper()
                                     and toks[k][1] not in _STOP and toks[k][1] not in _OPENERS) \
                and not proper_at(narration, base + toks[k][2], toks[k][0]) and not is_number(toks[k][0]):
            k += 1
        toks = toks[k:]
        while toks and toks[-1][1] in {"of", "the", "de", "del", "la", "du", "von", "van", "and", "on"}:
            toks = toks[:-1]
        if not toks:
            continue
        a, b = base + toks[0][2], base + toks[-1][3]
        out.append(narration[a:b])
    return out


def _fits(s: str, words: int, chars: int) -> bool:
    return 0 < len(s) <= chars and len(tokens(s)) <= words


def key_phrase(narration: str, words: int = HEAD_WORDS, chars: int = HEAD_CHARS, within: str = "") -> str:
    """
    The phrase a human editor would put on screen for this narration (or for the part of it that
    is `within`): the longest name that fits, else a superlative ("the lowest level on record"),
    else a figure with its unit ("2,450 cubic kilometers"); '' when there is none.
    """
    scope = within or narration
    names = [e for e in entities(scope) if _fits(e, words, chars)]
    # (one capitalised word must still be a name in the whole narration, not a sentence start)
    names = [e for e in names if len(tokens(e)) > 1 or len(e) >= 4]
    if names:
        return max(names, key=lambda e: (len(tokens(e)), len(e)))
    m = _SUPERLATIVE.search(scope)
    if m:
        toks = tokens(m.group(1))
        i, j, _cut = _trim(scope, toks, 0, len(toks))
        if j - i >= 2:
            s = scope[m.start(1) + toks[i][2]:m.start(1) + toks[j - 1][3]]
            s = re.sub(r"^(?:the)\s+", "", s, flags=re.I)
            if _fits(s, words, chars):
                return s
    for m in _FIGURE.finditer(scope):
        toks = tokens(m.group(0))
        i, j, _cut = _trim(scope, toks, 0, len(toks))
        if j > i and is_number(toks[i][0]):
            s = m.group(0)[toks[i][2]:toks[j - 1][3]].strip()
            if _fits(s, words, chars) and (j - i >= 2 or not re.fullmatch(r"(?:19|20)\d\d", s)):
                return s
    return ""


def doc_key(body: str, words: int = 6, chars: int = 40) -> str:
    """
    The words a document's loop circles: the claim it makes - a superlative ("lowest level since it first
    filled"), a figure with its unit, else the name it is about - as said; '' when there is none.
    """
    b = repair(body)
    if not b:
        return ""
    m = _SUPERLATIVE.search(b)
    if m:
        toks = tokens(m.group(1))
        i, j, _cut = _trim(b, toks, 0, len(toks))
        # a superlative's phrase runs to its clause's end when that fits ("lowest level since it first filled")
        start = m.start(1) + toks[i][2] if j > i else m.start(1)
        rest = re.split(r"[,;:.!?]|\s[-–—]\s", b[start:])[0].strip()
        rt = tokens(rest)
        while rt and len(rt) > words:
            rt = rt[:-1]
        while rt and rt[-1][1] in _DANGLING:
            rt = rt[:-1]
        cand = rest[:rt[-1][3]] if rt else ""
        cand = re.sub(r"^(?:the)\s+", "", cand, flags=re.I)
        if len(tokens(cand)) >= 2 and len(cand) <= chars:
            return cand
    k = key_phrase(b, words, chars)
    if len(tokens(k)) >= 2 or (k and not re.fullmatch(r"[\d,.$%\s]+", k)):
        return k
    # else what the document says: the end of its first clause ("the lake could keep falling for years")
    clause = re.split(r"[,;:.!?]|\s[-–—]\s", b)[0]
    ct = tokens(clause)[-words:]
    while ct and (ct[0][1] in _LEAD or ct[0][1] in ("the", "a", "an", "that")):
        ct = ct[1:]
    cand = clause[ct[0][2]:ct[-1][3]] if ct else ""
    return cand if len(ct) >= 3 and len(cand) <= chars else ""


def headline(text: str, narration: str, words: int = HEAD_WORDS, chars: int = HEAD_CHARS,
             term: bool = False) -> str:
    """
    `text` as a headline look shows it: the narration's own words for it, cut of glue and dangling
    ends, at most `words` words and `chars` letters, never filler. Too long, or not said: the key
    phrase it holds (a name, a superlative, a figure) when that is said. '' = show nothing.
    """
    t = _PAREN.sub("", repair(text)).strip()
    if not t or not narration:
        return ""
    hit = find(t, narration)
    if hit is None:
        # the words may run over a sentence's end on screen: the longest sentence part that is said
        parts = [p.strip() for p in re.split(r"[.!?;]\s+|[—–]|\s+-\s+", t) if p.strip()]
        for p in sorted(parts, key=len, reverse=True):
            got = headline(p, narration, words, chars, term) if p != t else ""
            if got:
                return got
        inner = key_phrase(narration, words, chars, within=_said_part(t, narration))
        return _cased(inner, text) if inner else ""
    toks = tokens(narration)
    i, j, a, b = hit
    if _crosses_sentence(narration, a, b):
        return _longest_sentence_part(narration, a, b, text, words, chars, term)
    i, j, cut = _trim(narration, toks, i, j)
    if j <= i:
        return ""
    s = narration[toks[i][2]:toks[j - 1][3]]
    if cut and not _has_name(narration, toks, i, j):
        # the phrase stopped mid-thought ("THE DANGER HERE ISNT ALWAYS THE"): only a name inside it may stand
        inner = key_phrase(narration, words, chars, within=s)
        return _cased(inner, text) if inner and inner != s else ""
    if not _fits(s, words, chars):
        inner = key_phrase(narration, words, chars, within=s)
        return _cased(inner, text) if inner else ""
    if not meaningful(narration, toks, i, j, term=term):
        return ""
    return _cased(s, text)


def _said_part(text: str, narration: str) -> str:
    """The narration's words that `text` also has, as one run (for a key phrase inside a paraphrase)."""
    want = {n for _r, n, _a, _b in tokens(text) if n not in _STOP}
    have = tokens(narration)
    idx = [k for k, (_r, n, _a, _b) in enumerate(have) if n in want]
    if not idx:
        return ""
    return narration[have[idx[0]][2]:have[idx[-1]][3]]


def _longest_sentence_part(narration: str, a: int, b: int, like: str, words: int, chars: int, term: bool) -> str:
    span = narration[a:b]
    parts = [p.strip() for p in re.split(r"[.!?;]\s+", span) if p.strip()]
    for p in sorted(parts, key=lambda p: len(tokens(p)), reverse=True):
        got = headline(p, narration, words, chars, term)
        if got:
            return _cased(got, like)
    return ""


def sentence(text: str, narration: str, words: int = SENTENCE_WORDS, chars: int = SENTENCE_CHARS) -> str:
    """
    A typed line, a statement or a quote: the narration's words, within one sentence, whole
    clauses only. Longer than `words` / `chars`: its first clause that fits and says something,
    else the key phrase it holds, else ''.
    """
    t = repair(text)
    if not t or not narration:
        return ""
    end = t[-1] if t[-1] in "?!" else ""
    hit = find(t, narration)
    if hit is None:
        return _short(headline(t, narration))
    toks = tokens(narration)
    i, j, a, b = hit
    if _crosses_sentence(narration, a, b):
        parts = [p for p in re.split(r"(?<=[.!?;])\s+", narration[a:b]) if p.strip()]
        best = max(parts, key=lambda p: len(tokens(p)))
        return sentence(best.rstrip(".;"), narration, words, chars)
    s = narration[a:b]
    if _fits(s, words, chars) and _clause_end(narration, b):
        # a whole clause: it ends where the narration's thought ends ("...both tend to skip" does not)
        i2, j2, cut = _trim(narration, toks, i, j)
        if j2 > i2 and not cut and (meaningful(narration, toks, i2, j2) or (
                j2 - i2 >= 3 and content_count([toks[k][1] for k in range(i2, j2)]) >= 1)):
            s2 = narration[toks[i2][2]:toks[j2 - 1][3]]
            return _cased(s2, text) + (end if end and not s2.endswith(end) else "")
    # the first clause that fits
    for clause in re.split(r"\s*[,;:]\s+|\s+[—–-]\s+", s):
        clause = clause.strip()
        if clause and _fits(clause, words, chars):
            c_hit = find(clause, narration)
            if c_hit is None:
                continue
            ci, cj, ca, cb = c_hit
            if not _clause_end(narration, cb):
                continue
            ci, cj, cut = _trim(narration, toks, ci, cj)
            if cj > ci and not cut and content_count([toks[k][1] for k in range(ci, cj)]) >= 2 \
                    and len(tokens(clause)) >= 3:
                return _cased(narration[toks[ci][2]:toks[cj - 1][3]], text)
    return _short(headline(t, narration))


def _short(s: str) -> str:
    """A sentence cut down to its key phrase stands only with two words or more (never one name alone)."""
    return s if len(tokens(s)) >= 2 else ""


def photo_caption(subject: str, narration: str) -> str:
    """
    A picture's caption: the name in its subject that the narration says, in the subject's own
    capitals ("Lake Powell low water exposing previously submerged terrain" -> "Lake Powell";
    "Yellowstone Caldera (northwest Wyoming)" said as "Yellowstone" -> "Yellowstone"). '' when the
    line does not name what the picture shows: no caption rather than a guess (a name the line says
    about something else - "the most photographed lakes in America" - is not what the photo shows).
    """
    subj = _PAREN.sub("", repair(subject))
    caps = _caps_like(subj)
    if caps:
        subj = subj.title()
    for name in sorted(entities(subj, title=True), key=lambda e: -len(tokens(e))):
        toks = tokens(name)
        # the longest run of the name that is said (transcripts write names in lower case too)
        for n in range(len(toks), 0, -1):
            for k in range(0, len(toks) - n + 1):
                part = name[toks[k][2]:toks[k + n - 1][3]]
                if toks[k][1] in _STOP or toks[k + n - 1][1] in _STOP or (n == 1 and len(part) < 4) \
                        or (n == 1 and toks[k][1] in _GENERIC):
                    continue
                hit = find(part, narration)
                if not hit or not _fits(part, CAPTION_WORDS, CAPTION_CHARS):
                    continue
                if caps and n == 1:
                    # an all-capitals subject hides which words are names: one word must be one where it is said
                    ntoks = tokens(narration)
                    if not proper_at(narration, ntoks[hit[0]][2], ntoks[hit[0]][0]):
                        continue
                return part
    return ""


def said_share(text: str, narration: str) -> float:
    """The share of the words that carry meaning in `text` that the narration says (numbers count as said
    when the same digits are there)."""
    want = [n for _r, n, _a, _b in tokens(text) if n not in _STOP or n in _MODIFIERS]
    if not want:
        return 0.0
    have = {n for _r, n, _a, _b in tokens(narration)}
    stems = {h[:5] for h in have if len(h) >= 5}
    got = sum(1 for w in want if w in have or (len(w) >= 5 and w[:5] in stems))
    return got / len(want)


def items(rows: list, narration: str, keys: Iterable[str] = ("label", "text"), least: int = 2) -> Optional[list]:
    """
    A list's or a split's rows: each row's words said (at least half of what carries meaning), at most
    LABEL_WORDS / LABEL_CHARS each; numbers and years stand as they are. Rows that fail are taken out;
    None when fewer than `least` rows are left (the look is left out).
    """
    kept = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        ok = True
        out = dict(row)
        for k in keys:
            v = row.get(k)
            if not isinstance(v, str) or not v.strip():
                continue
            v = repair(v)
            if all(is_number(r) for r, _n, _a, _b in tokens(v)):
                out[k] = v
                continue
            if said_share(v, narration) < 0.5:
                ok = False
                break
            if not _fits(v, LABEL_WORDS, LABEL_CHARS):
                short = headline(v, narration, LABEL_WORDS, LABEL_CHARS)
                if not short:
                    ok = False
                    break
                v = short
            out[k] = v
        if ok:
            kept.append(out)
    return kept if len(kept) >= least else None


def _key_for(text: str) -> str:
    """The word that times a graphic showing `text`: its first word that carries meaning."""
    for raw, n, _a, _b in tokens(text):
        if (n not in _STOP or n in _MODIFIERS) and len(n) >= 2:
            return raw
    toks = tokens(text)
    return toks[0][0] if toks else ""


def clean_props(template: dict, cue: str, props: dict, line: str, ahead: str = "") -> Optional[dict]:
    """
    The props a look is laid with, its words checked against what is said (see the module doc).
    `line` is the graphic's line, `ahead` the lines its word may still come in. None: nothing worth
    showing is left - the look is not laid.
    """
    t = template or {}
    out = dict(props or {})
    narration = " ".join(x for x in (line or "", ahead or "") if x).strip()
    category = t.get("category") or ""
    if not narration:
        return out
    for k in ("text", "subtitle", "label", "highlight", "body"):
        if isinstance(out.get(k), str):
            out[k] = repair(out[k])
    if cue in OWN_WORDS_CUES or category in ("NUMBERS", "TIMELINES", "MAPS", "LOWER_THIRDS"):
        return out
    old_text = str(out.get("text") or "")
    if category == "IMAGES":
        if old_text:
            cap = photo_caption(old_text, narration)
            if cap:
                out["text"] = cap.upper() if _caps_like(old_text) else cap
            else:
                out.pop("text", None)
    elif cue == "document" or (category == "DOCUMENTS" and not cue):
        if old_text:
            head = sentence(old_text, narration, DOC_WORDS, DOC_CHARS)
            if not head:
                head = key_phrase(narration, DOC_WORDS, DOC_CHARS)
            if not head:
                return None
            out["text"] = head.upper() if _caps_like(old_text) else head
    elif category in TEXT_CATEGORIES or category == "TRANSITIONS" or cue:
        if old_text:
            if cue in SENTENCE_CUES or (cue == "" and category == "QUOTES"):
                new = sentence(old_text, narration)
            else:
                new = headline(old_text, narration, term=(cue == "term"))
            if not new:
                return None
            out["text"] = new
    # Rows of a list, a split or a card: said, short (a row of digits stands as it is).
    rows_in = out.get("items")
    if isinstance(rows_in, list) and rows_in:
        rows = items(rows_in, narration, least=min(2, len(rows_in)))
        if rows is None:
            return None
        out["items"] = rows
    # The highlighted words are words of the text that carry meaning.
    hl = out.get("highlight")
    if isinstance(hl, str) and hl and category != "DOCUMENTS":
        text_now = str(out.get("text") or "")
        if not find(hl, text_now) or not meaningful(text_now, tokens(text_now), *find(hl, text_now)[:2]):
            inner = key_phrase(narration, 3, 24, within=text_now) if text_now else ""
            if inner:
                out["highlight"] = inner
            else:
                out.pop("highlight", None)
    new_text = str(out.get("text") or "")
    if new_text != old_text and out.get("_key") and not find(str(out["_key"]), new_text):
        key = _key_for(new_text)
        if key:
            out["_key"] = key
        else:
            out.pop("_key", None)
    return out


def audit(overlays: List[dict]) -> int:
    """The last pass over a plan: typing artefacts and leading punctuation out of every text field.
    Returns how many fields changed."""
    changed = 0
    for ov in overlays or []:
        if not isinstance(ov, dict):
            continue
        for k in ("text", "subtitle", "label", "highlight"):
            v = ov.get(k)
            if isinstance(v, str) and v:
                r = repair(v)
                if r != v:
                    ov[k] = r
                    changed += 1
    return changed


def dedupe_cards(overlays: List[dict]) -> int:
    """Two identical text cards on the same frames (a line's card laid twice) become one."""
    seen, kept, dropped = set(), [], 0
    for ov in overlays or []:
        if isinstance(ov, dict) and ov.get("type") == "highlight":
            key = (ov.get("text"), int(ov.get("startFrame") or 0), int(ov.get("durationInFrames") or 0))
            if key in seen:
                dropped += 1
                continue
            seen.add(key)
        kept.append(ov)
    overlays[:] = kept
    return dropped


def stats(overlays: List[dict], words: Sequence[Tuple[float, float, str]], fps: int = 30) -> Dict[str, int]:
    """For the audit: text fields on screen, how many were said near their graphic, how many are long."""
    out = {"fields": 0, "said": 0, "long": 0}
    for ov in overlays or []:
        a = int(ov.get("startFrame") or 0) / float(fps)
        b = a + int(ov.get("durationInFrames") or 0) / float(fps)
        near = " ".join(w for s, e, w in words if e > a - 3 and s < b + 1)
        for k in ("text", "label", "subtitle"):
            v = ov.get(k)
            if isinstance(v, str) and v.strip():
                out["fields"] += 1
                out["said"] += said_share(v, near) >= 0.99
                out["long"] += len(v) > HEAD_CHARS or len(tokens(v)) > HEAD_WORDS
    return out
