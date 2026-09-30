"""
Cut on names: a person is on screen WHILE their name is said.

The owner, 2026-09-30: "when a person's name is mentioned you show a random
clip - you need to show the image or video of that person WHILE the name is
said, not before, not after. Same when something specific is mentioned: show
it at the perfect time."

transcribe.segment_words cuts the narration on clause boundaries around a
~7 s rhythm, and every beat gets one visual chosen for the beat as a whole,
so a name said four seconds into a beat played over whatever the beat was
about. Two steps around the director's shot plan fix that and leave the
rhythm alone everywhere else:

prepare()      before any shot is planned. A beat that names one of the
               story's people (the brief's cast, their aliases, its people
               list, a surname only one of them has) past its opening is
               split at the first word of that mention - its title too:
               "Governor Katie Hobbs" cuts at "Governor" - using the word
               timings, so the name opens a beat of its own. With no person
               to cut at, a beat that names two different places of the
               story is split at the second one. One split per beat at most,
               never a piece shorter than MIN_SCENE_SECONDS / 2 (nor min_head
               before the name, min_tail after it). A person named in the
               last seconds of a beat, too late to split at, opens the next
               beat instead (the name and the next beat are cut again on the
               usual rhythm). The brief's beat numbers (hookBeats, sections)
               move onto the new beats.
apply_focus()  after the shots are planned. Every beat that opens with a
               named person shows that person: subject, subjectType "person",
               a search that starts with the name (their interview on the
               story's topic in a news story), and an intent and scene intent
               the vision judge checks the footage against. A beat cut at a
               second place shows that place.

MENTION_CUTS=0 (in the environment, or a config attribute of that name)
turns both off.
"""
import copy
import dataclasses
import os
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

from . import config

# What the last prepare() / apply_focus() did, for the job log.
LAST_STATS: Dict[str, int] = {}


def enabled() -> bool:
    """On unless MENTION_CUTS is 0/false/no/off (a config attribute first, then the environment)."""
    value = getattr(config, "MENTION_CUTS", None)
    if value is None:
        value = os.getenv("MENTION_CUTS", "1")
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "off")
    return bool(value)


# --------------------------------------------------------------------------- #
# Words
# --------------------------------------------------------------------------- #

# Words in front of a name that belong to the mention: the cut lands on
# "Governor", not on "Katie", in "Governor Katie Hobbs".
_TITLES = {
    "governor", "gov", "senator", "sen", "president", "vice", "secretary", "mayor", "judge",
    "justice", "commissioner", "director", "chairman", "chairwoman", "chair", "chief", "sheriff",
    "representative", "rep", "congressman", "congresswoman", "attorney", "general", "dr", "mr",
    "mrs", "ms", "miss", "sir", "dame", "lord", "lady", "king", "queen", "prince", "princess",
    "pope", "rev", "reverend", "captain", "capt", "colonel", "col", "lieutenant", "lt",
    "sergeant", "sgt", "admiral", "adm", "commander", "cmdr", "major", "maj", "marshal",
    "brigadier", "corporal", "cpl", "ensign",
    "professor", "prof", "officer", "deputy", "speaker", "minister", "premier",
    "chancellor", "ambassador", "councilman", "councilwoman", "councilmember", "superintendent",
    "administrator", "assemblyman", "assemblywoman", "trooper", "detective", "agent", "coach",
    "founder", "ceo", "spokesman", "spokeswoman", "spokesperson", "hydrologist", "scientist",
    "meteorologist", "geologist", "engineer", "farmer", "rancher", "activist", "author",
    "historian", "manager",
}
# Abbreviations whose full stop does not end a clause ("Sen. Mark Kelly", "U.S. Senator").
_ABBREVIATIONS = {"dr", "mr", "mrs", "ms", "gov", "sen", "rep", "lt", "col", "capt", "sgt",
                  "prof", "st", "rev", "gen", "jr", "sr", "us", "adm", "cmdr", "maj", "cpl"}
# Capitalised words in front of a title that are not part of it ("On Monday Governor ...").
_NOT_MODIFIERS = {
    "the", "a", "an", "and", "or", "but", "so", "then", "now", "when", "while", "after", "before",
    "since", "because", "as", "if", "in", "on", "at", "of", "for", "to", "by", "with", "from",
    "that", "this", "these", "those", "there", "here", "today", "yesterday", "tonight", "last",
    "next", "still", "also", "even", "just", "only", "said", "says", "told", "asked", "according",
    "he", "she", "it", "they", "we", "i", "his", "her", "their",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "january",
    "february", "march", "april", "may", "june", "july", "august", "september", "october",
    "november", "december",
}
# An alias made only of these ("he", "his", "the man") names nobody in particular.
_FUNCTION = {
    "the", "a", "an", "this", "that", "these", "those", "of", "and", "or", "to", "in", "on", "at",
    "for", "with", "from", "by", "as", "he", "she", "him", "her", "his", "hers", "they", "them",
    "their", "theirs", "it", "its", "i", "me", "my", "we", "us", "our", "you", "your", "himself",
    "herself", "themselves", "who", "whom", "one", "man", "woman", "person", "people", "guy",
}
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
# "Barack Obama Senior" is "Barack Obama Sr." (and never "Barack Obama").
_SPELLED = {"senior": "sr", "junior": "jr"}
# A "person" in the brief that is really an event, a ship, an organisation
# ("Palisades Fire", "USS Enterprise", "Bureau of Reclamation")...
_NEVER_A_PERSON = {
    "fire", "fires", "hurricane", "tornado", "floods", "drought", "battle", "war",
    "operation", "uss", "hms", "rms", "railroad", "railway", "company", "corporation", "corp",
    "inc", "llc", "university", "college", "department", "agency", "bureau", "commission",
    "administration", "committee", "council", "district", "county", "reservoir", "dam", "canal",
    "airport", "station",
}
# ...and, in the brief's people list - which the rule reading fills from any
# capitalised phrase - a place or company too ("Union Pacific", "Sherman Hill",
# "Las Vegas"). The cast is the model's list of real people, so a cast member
# named Anita Hill stays a person.
_NOT_PERSON_WORDS = _NEVER_A_PERSON | {
    "authority", "school", "service", "office", "board", "court", "congress", "senate", "house",
    "association", "institute", "center", "centre", "foundation", "project", "river", "lake",
    "state", "city", "states", "nation", "nations", "government", "party", "tribe", "news",
    "times", "post", "hill", "hills", "heights", "fleet", "navy", "army", "corps", "club", "team",
    "festival", "conference", "summit", "treaty", "program", "fund", "bank", "market", "network",
    "journal", "magazine", "airlines", "motors", "group", "pacific", "atlantic", "union",
    "national", "federal", "valley", "canyon", "creek", "park", "island", "bay", "harbor",
    "harbour", "mountain", "mountains", "desert", "coast", "springs", "bridge", "street", "avenue",
    "road", "highway",
}
# First words of a place's name ("Los Angeles", "Rio Ruidoso", "Lake Mead"),
# and last words that are almost never a surname ("Punahou School").
_NOT_PERSON_FIRST = {"mount", "mt", "new", "north", "south", "east", "west", "saint", "st", "san",
                     "santa", "los", "las", "el", "rio", "fort", "port", "cape", "gulf", "ocean",
                     "big", "great", "grand", "upper", "lower", "old", "lake", "union", "pacific",
                     "atlantic", "national", "federal", "united"}
_NOT_A_SURNAME = {           # not Temple, Plant, Church, Tower, Law, Street or Flood: people have those
    "school", "academy", "center", "centre", "river", "city", "county", "palisades", "harbor",
    "harbour", "airport", "station", "stadium", "museum", "library", "hospital", "cathedral",
    "college", "university", "institute", "reservoir", "dam", "canyon", "valley", "creek",
    "springs", "falls", "island", "islands", "mountains", "desert", "ocean", "sea", "gulf",
    "coast", "beach", "avenue", "road", "highway", "railroad", "railway", "bridge", "building",
    "company", "group", "review", "times", "journal", "news", "network", "league", "association",
    "society", "foundation", "fund", "project", "program", "plan", "act", "treaty", "basin",
    "aqueduct", "canal", "farm", "ranch", "mine", "base", "fleet", "army", "navy", "force",
    "forces", "corps", "department", "office", "fire",
}
_NAME_JOINERS = {"de", "da", "del", "della", "der", "van", "von", "bin", "al", "la", "le", "du",
                 "of", "the", "y"}
# A name inside a place's name is not a mention of the person ("Lake Powell",
# "Hoover Dam", "Kennedy Center"), nor is "Colorado" in "Colorado River".
_PLACE_BEFORE = {"lake", "mount", "mt", "fort", "ft", "port", "glen", "cape", "point", "camp",
                 "san", "santa", "saint", "st", "new", "north", "south", "east", "west", "upper",
                 "lower", "greater", "little", "big", "grand"}
_PLACE_AFTER = {
    "river", "lake", "dam", "reservoir", "canyon", "valley", "basin", "creek", "springs", "falls",
    "county", "city", "town", "township", "street", "avenue", "ave", "road", "boulevard", "blvd",
    "highway", "park", "center", "centre", "bridge", "tower", "building", "hall", "school",
    "university", "college", "airport", "station", "hospital", "memorial", "museum", "library",
    "island", "islands", "bay", "beach", "harbor", "harbour", "mountain", "mountains", "peak",
    "canal", "aqueduct", "plant", "field", "stadium", "arena", "square", "district", "foundation",
    "institute", "prize", "award",
}
# Surnames that are also everyday words, capitalised at every sentence start
# ("Wells ran dry", "Rivers rose"): never matched on their own - the full name
# and the brief's own aliases still are.
_COMMON_WORDS = {
    "young", "brown", "white", "black", "green", "gray", "grey", "rice", "price", "bush", "king",
    "hill", "long", "little", "rose", "may", "bell", "banks", "rivers", "woods", "wood", "stone",
    "wells", "hunt", "cook", "hope", "grant", "love", "cash", "wise", "sharp", "strong", "hall",
    "lane", "ford", "field", "fields", "park", "west", "north", "south", "east", "day", "case",
    "chase", "church", "mills", "power", "powers", "street", "early", "best", "more", "rich",
    "summers", "winter", "snow", "rain", "storm", "flood", "waters", "lake", "brook", "brooks",
    "ray", "frank", "noble", "major", "bishop", "english", "french", "land", "rock", "rocks",
    "marsh", "fish", "bird", "fox", "wolf", "bear", "lamb", "hand", "will", "mark", "bill",
    "golden", "silver", "gold", "cotton", "wheat", "sand", "sands", "dry", "reed", "pool", "dale",
    "moon", "sun", "star", "sky",
}
# Words two place names can share without being the same area.
_PLACE_GENERIC = {"lake", "river", "mount", "mt", "county", "city", "state", "north", "south",
                  "east", "west", "new", "san", "fort", "dam", "canyon", "valley", "national",
                  "park", "the", "of", "and", "upper", "lower", "great", "grand"}

_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "`": "'", "ʼ": "'"})


def _norm(token: str) -> str:
    """One word as the matcher sees it: "Abbott’s" -> "abbott", "Sr.," -> "sr", "“Hobbs" -> "hobbs"."""
    t = (token or "").translate(_APOSTROPHES).casefold()
    t = re.sub(r"[^\w'.\-]", "", t).strip("'.-")
    if t.endswith("'s"):
        t = t[:-2]
    t = t.replace(".", "").strip("'-")
    return _SPELLED.get(t, t)


def _tokens(phrase: str) -> Tuple[str, ...]:
    return tuple(n for n in (_norm(w) for w in (phrase or "").replace(",", " ").split()) if n)


def _text(value) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _capitalised(token: str) -> bool:
    m = re.search(r"[^\W\d_]", token or "")
    return bool(m) and m.group(0).isupper()


def _abbreviation(token: str) -> bool:
    """"Sen.", "Dr.", "U.S.", "J.D.", "F." - a full stop that ends no sentence."""
    t = (token or "").rstrip("\"'”’)],")
    return t.endswith(".") and (_norm(t) in _ABBREVIATIONS or bool(re.fullmatch(r"(?:[^\W\d_]\.)+", t)))


def _ends_clause(token: str) -> bool:
    """The word closes a clause ("said,", "Monday."), so a mention never reaches back past it."""
    if not re.search(r"[,.;:!?—–][\"'”’)\]]*$", token or ""):
        return False
    return not _abbreviation(token)


def _ends_sentence(token: str) -> bool:
    t = (token or "").rstrip("\"'”’)]")
    return bool(t) and t[-1] in ".!?" and not _abbreviation(t)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# --------------------------------------------------------------------------- #
# Who and what the story names
# --------------------------------------------------------------------------- #

def _person_like(name: str, strict: bool = True) -> bool:
    """
    A real person's name - "Katie Hobbs", "Barack Obama Sr.", "Admiral
    Nimitz" - not an agency, event, ship, company or place the brief listed
    among its people ("Palisades Fire", "Union Pacific", "Apple").
    `strict` also turns down place and company words (see _NOT_PERSON_WORDS).
    """
    if re.search(r"\d", name or ""):
        return False                  # "Big Boy 4014"
    words = re.findall(r"[^\W\d_][\w.'’-]*", name or "")
    norms = [_norm(w) for w in words]
    if not words or any(n in (_NOT_PERSON_WORDS if strict else _NEVER_A_PERSON) for n in norms):
        return False
    if norms[0] in _NOT_PERSON_FIRST or norms[-1] in _NOT_A_SURNAME:
        return False
    if not all(_capitalised(w) for w, n in zip(words, norms) if n not in _NAME_JOINERS):
        return False
    # Two names, or a title and a name; one bare word is a company or a town
    # far more often than a person known by one name.
    named = [n for n in norms if n not in _TITLES and n not in _SUFFIXES and n not in _NAME_JOINERS]
    return len(named) >= 2 or (len(named) == 1 and len(named) < len(norms))


def _surname(name: str) -> str:
    """"Katie Hobbs" -> "hobbs", "Barack Obama Sr." -> "obama"; "" for a one-word name."""
    toks = [t for t in _tokens(name) if t not in _TITLES]
    while toks and toks[-1] in _SUFFIXES:
        toks.pop()
    return toks[-1] if len(toks) >= 2 else ""


def _usable_alias(alias: str) -> bool:
    """"his father", "the governor", "Hobbs" - not "he", "his" or "the man"."""
    return any(t not in _FUNCTION and len(t) >= 3 for t in _tokens(alias))


def _people(brief: dict) -> List[dict]:
    """The story's named people, cast first: [{"name", "role", "aliases", "surname"}]."""
    from .media import same_subject
    out: List[dict] = []

    def known(name: str) -> Optional[dict]:
        return next((p for p in out if same_subject(p["name"], name)), None)

    for c in brief.get("cast") or []:
        if not isinstance(c, dict):
            continue
        name = _text(c.get("name"))
        # Unknown identity ("the pilot" with no name): nobody to show.
        if not name or not _person_like(name, strict=False):
            continue
        aliases = [a for a in (_text(x) for x in (c.get("aliases") or [])) if a]
        have = known(name)
        if have:
            have["aliases"] += aliases
            have["role"] = have["role"] or _text(c.get("role"))
            continue
        out.append({"name": name, "role": _text(c.get("role")), "aliases": aliases, "surname": ""})
    for p in brief.get("people") or []:
        name = _text(p)
        if name and _person_like(name) and not known(name):
            out.append({"name": name, "role": "", "aliases": [], "surname": ""})
    # A surname alone names its person ("Hobbs said...") when nobody else in
    # the story has it, as a surname or a given name.
    surnames = Counter(s for s in (_surname(p["name"]) for p in out) if s)
    for p in out:
        s = _surname(p["name"])
        others = {t for q in out if q is not p for t in _tokens(q["name"])}
        if s and surnames[s] == 1 and s not in others and len(s) >= 3 and s not in _COMMON_WORDS:
            p["surname"] = s
    return out


@dataclasses.dataclass(frozen=True)
class _Pattern:
    tokens: Tuple[str, ...]
    name: str        # who or what a match of it names
    kind: str        # "person" | "place"
    proper: bool     # one capitalised word: the narration must capitalise it too
    rank: int        # 0 a person's name or alias, 1 a place, 2 a surname worked out here


def _lexicon(brief: dict) -> Tuple[List[_Pattern], Dict[str, dict]]:
    """Every way the narration can name one of the story's people or places."""
    if not isinstance(brief, dict):
        return [], {}
    people = _people(brief)
    found: Dict[Tuple[str, ...], List[_Pattern]] = defaultdict(list)

    def add(phrase: str, name: str, kind: str, rank: int, proper: Optional[bool] = None) -> None:
        tokens = _tokens(phrase)
        if not tokens or not any(len(t) >= 2 for t in tokens):
            return
        if proper is None:
            proper = len(tokens) == 1 and _capitalised(phrase)
        found[tokens].append(_Pattern(tokens, name, kind, proper, rank))

    for p in people:
        add(p["name"], p["name"], "person", 0)
        for alias in p["aliases"]:
            if _usable_alias(alias):
                add(alias, p["name"], "person", 0)
        if p["surname"]:
            add(p["surname"], p["name"], "person", 2, proper=True)
    for place in brief.get("places") or []:
        place = _text(place)
        if place:
            bare = re.sub(r"^the\s+", "", place, flags=re.I)      # "the Colorado River"
            add(bare, place, "place", 1)
            add(bare.split(",")[0], place, "place", 1)

    patterns: List[_Pattern] = []
    for tokens, cands in found.items():
        best = min(c.rank for c in cands)
        top = [c for c in cands if c.rank == best]
        if len({(c.name, c.kind) for c in top}) == 1 or all(c.kind == "place" for c in top):
            # Two spellings of one area: the first (the brief's most important) wins.
            patterns.append(top[0])
        # Two different people answer to it ("the governor" of two states): left out.
    return patterns, {p["name"]: p for p in people}


# --------------------------------------------------------------------------- #
# Where in a beat each name is said
# --------------------------------------------------------------------------- #

@dataclasses.dataclass
class _Tok:
    text: str
    char: int            # where it starts in the beat's text
    norm: str
    at: float = 0.0      # when it is said, in seconds
    word: int = -1       # its own whisper word, or -1 when `at` is interpolated


def _timed_tokens(seg) -> List[_Tok]:
    """
    The beat's words as the captions show them, each with the time it is said.

    The text can be the authored script (transcribe.align_to_script) while
    `words` are what whisper heard, so the two are aligned: equal words - and
    same-length stretches heard differently ("Hobs" for "Hobbs") - take their
    word's own start; the rest are placed between their timed neighbours.
    """
    text = getattr(seg, "text", "") or ""
    toks = [_Tok(m.group(0), m.start(), _norm(m.group(0))) for m in re.finditer(r"\S+", text)]
    if not toks:
        return toks
    words = list(getattr(seg, "words", None) or [])
    if words:
        matcher = SequenceMatcher(None, [t.norm for t in toks],
                                  [_norm(getattr(w, "text", "")) for w in words], autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
                for a, b in zip(range(i1, i2), range(j1, j2)):
                    toks[a].at, toks[a].word = float(words[b].start), b
    start = float(seg.start)
    end = max(float(seg.end), start)
    anchors = [(0, start)] + [(t.char, t.at) for t in toks if t.word >= 0] + [(len(text), end)]
    for t in toks:
        if t.word >= 0:
            continue
        left = max((a for a in anchors if a[0] <= t.char), key=lambda a: a[0])
        right = min((a for a in anchors if a[0] > t.char), key=lambda a: a[0], default=(len(text), end))
        span = right[0] - left[0]
        t.at = left[1] + (right[1] - left[1]) * ((t.char - left[0]) / span if span else 0.0)
    return toks


def _find(toks: List[_Tok], lexicon: List[_Pattern]) -> List[Tuple[int, int, _Pattern]]:
    """(first token, token after, pattern) for each name in the beat, longest match first, in order."""
    seq = [k for k, t in enumerate(toks) if t.norm]
    norms = [toks[k].norm for k in seq]
    by_first: Dict[str, List[_Pattern]] = defaultdict(list)
    for p in lexicon:
        by_first[p.tokens[0]].append(p)
    cands = []
    for i, first_norm in enumerate(norms):
        for p in by_first.get(first_norm, ()):
            n = len(p.tokens)
            if tuple(norms[i:i + n]) != p.tokens:
                continue
            first, last = seq[i], seq[i + n - 1]
            if p.proper and not _capitalised(toks[first].text):
                continue
            if any(_ends_sentence(toks[seq[i + k]].text) for k in range(n - 1)):
                continue            # "...in Phoenix. Arizona officials said" is two sentences
            nxt = norms[i + n] if i + n < len(norms) and not _ends_clause(toks[last].text) else ""
            prv = norms[i - 1] if i > 0 and not _ends_clause(toks[seq[i - 1]].text) else ""
            if (p.kind == "person" or n == 1) and nxt in _PLACE_AFTER:
                continue            # "Hoover Dam", "Kennedy Center", "Colorado River"
            if n == 1 and prv in _PLACE_BEFORE:
                continue            # "Lake Powell", "New Mexico"
            if p.kind == "person" and nxt in _SUFFIXES and p.tokens[-1] not in _SUFFIXES:
                continue            # "Barack Obama Sr." is someone else than "Barack Obama"
            cands.append((first, last + 1, p))
    cands.sort(key=lambda c: (-len(c[2].tokens), c[2].rank, c[0]))
    taken: set = set()
    chosen = []
    for first, stop, p in cands:
        if taken.intersection(range(first, stop)):
            continue
        taken.update(range(first, stop))
        chosen.append((first, stop, p))
    chosen.sort(key=lambda c: c[0])
    return chosen


def _title_start(toks: List[_Tok], first: int, floor: int, own: Tuple[str, ...] = ()) -> int:
    """
    Reach back to where the reference to the person starts: the rest of their
    own name in front of a shorter match ("John F. Kennedy" for "Kennedy"),
    then their title and its modifiers ("Arizona Governor Katie Hobbs").
    """
    k = first
    while k - 1 >= floor:
        prev = toks[k - 1]
        if not _capitalised(prev.text) or _ends_clause(prev.text):
            break
        if prev.norm in own or re.fullmatch(r"(?:[^\W\d_]\.)+", prev.text):
            k -= 1
            continue
        break
    titles = 0
    while k - 1 >= floor and titles < 3:
        prev = toks[k - 1]
        if prev.norm not in _TITLES or _ends_clause(prev.text):
            break
        k, titles = k - 1, titles + 1
    modifiers = 0
    while titles and k - 1 >= floor and modifiers < 2:
        prev = toks[k - 1]
        if (not prev.norm or _ends_clause(prev.text) or not _capitalised(prev.text)
                or prev.norm in _NOT_MODIFIERS):
            break
        k, modifiers = k - 1, modifiers + 1
    return k


@dataclasses.dataclass
class Mention:
    name: str        # who or what is named (the cast name, or the brief's place)
    kind: str        # "person" | "place"
    char: int        # where the mention starts in the beat's text (its title included)
    at: float        # when that first word is said, in seconds
    word: int        # index of that word in seg.words, or -1 when its time is interpolated


def _mentions(seg, lexicon: List[_Pattern]) -> List[Mention]:
    toks = _timed_tokens(seg)
    out: List[Mention] = []
    floor, last_first = 0, 0
    for first, stop, p in _find(toks, lexicon):
        start = first
        if p.kind == "person":
            start = _title_start(toks, first, floor, _tokens(p.name))
            # "Arizona Governor Katie Hobbs": a place right in front of the
            # title is part of how the person is named, not a place mention.
            if (out and out[-1].kind == "place" and start == floor and start > 0
                    and not _ends_clause(toks[start - 1].text)
                    and any(toks[k].norm in _TITLES for k in range(start, first))):
                out.pop()
                start = last_first
        out.append(Mention(p.name, p.kind, toks[start].char, toks[start].at, toks[start].word))
        floor, last_first = stop, start
    return out


def find_mentions(seg, brief: dict) -> List[Mention]:
    """The story's people and places a beat names, in the order they are said."""
    return _mentions(seg, _lexicon(brief)[0])


# --------------------------------------------------------------------------- #
# Splitting
# --------------------------------------------------------------------------- #

def _related(a: str, b: str) -> bool:
    """"Davenport, Iowa" and "Iowa" are one area; "Lake Mead" and "Lake Powell" are not."""
    ta = {t for t in _tokens(a) if t not in _PLACE_GENERIC}
    tb = {t for t in _tokens(b) if t not in _PLACE_GENERIC}
    return bool(ta & tb)


def _cut_at(seg, m: Mention, head_min: float, tail_min: float) -> Optional[Tuple[int, float]]:
    """(word index, time) to split the beat at this mention, or None when a piece would be too short."""
    words = list(getattr(seg, "words", None) or [])
    if not words:
        return None       # no word timings: the cut could not land on the name
    j = m.word if m.word >= 0 else min(range(len(words)), key=lambda k: abs(words[k].start - m.at))
    if j <= 0 or j >= len(words):
        return None
    t = float(words[j].start)
    if t - float(seg.start) < head_min - 1e-6 or float(seg.end) - t < tail_min - 1e-6:
        return None
    return j, t


def _choose(seg, found: List[Mention], head_min: float,
            tail_min: float) -> Optional[Tuple[Mention, int, float]]:
    """
    Where to split: the first person newly named far enough from both ends
    (a person the beat already opened with is on screen, no cut needed),
    else the first place that differs from the first one the beat names.
    """
    seen: set = set()
    for m in found:
        if m.kind != "person" or m.name in seen:
            continue
        seen.add(m.name)
        if float(seg.end) - m.at < tail_min:
            break           # every later name is closer still to the end
        got = _cut_at(seg, m, head_min, tail_min)
        if got:
            return (m,) + got
    places: List[Mention] = []
    for m in found:
        if m.kind == "place" and not any(_related(m.name, p.name) for p in places):
            places.append(m)
    for m in places[1:]:
        got = _cut_at(seg, m, head_min, tail_min)
        if got:
            return (m,) + got
    return None


def _piece(seg, text: str, start: float, end: float, words: list):
    """A copy of the beat with its own text, time and words (any other field is kept)."""
    if dataclasses.is_dataclass(seg) and not isinstance(seg, type):
        return dataclasses.replace(seg, text=text, start=start, end=end, words=words)
    piece = copy.copy(seg)
    piece.text, piece.start, piece.end, piece.words = text, start, end, words
    return piece


def _middle_cut(words: list, half: float) -> Optional[int]:
    """Where to cut a run of words in two: the clause end nearest the middle, else the nearest word."""
    if len(words) < 2:
        return None
    start, end = float(words[0].start), float(words[-1].end)
    options = [k for k in range(1, len(words))
               if float(words[k].start) - start >= half and end - float(words[k].start) >= half]
    if not options:
        return None
    ends = [k for k in options if _ends_clause(getattr(words[k - 1], "text", ""))]
    mid = (start + end) / 2
    return min(ends or options, key=lambda k: abs(float(words[k].start) - mid))


def _trailing(seg, found: List[Mention], head_min: float, tail_min: float) -> Optional[Mention]:
    """The first person newly named too close to the beat's end to be cut at there."""
    seen: set = set()
    for m in found:
        if m.kind != "person" or m.name in seen:
            continue
        seen.add(m.name)
        if m.at - float(seg.start) >= head_min and float(seg.end) - m.at < tail_min:
            return m
    return None


def _recut(seg, m: Mention, nxt, head_min: float, half: float):
    """
    (head, pieces): the beat up to the name, and the name plus the next beat
    cut again on the usual rhythm (transcribe.segment_words), so the first
    piece opens on the name. None when either side lacks word timings or a
    piece would be too short.
    """
    from .transcribe import segment_words
    words, later = list(getattr(seg, "words", None) or []), list(getattr(nxt, "words", None) or [])
    if not words or not later:
        return None
    j = m.word if m.word >= 0 else min(range(len(words)), key=lambda k: abs(words[k].start - m.at))
    if j <= 0 or j >= len(words):
        return None
    t = float(words[j].start)
    if t - float(seg.start) < head_min - 1e-6:
        return None
    longest = float(getattr(config, "MAX_SCENE_SECONDS", 9.0)) + 0.6
    shaped = []
    for s in segment_words(words[j:] + later):
        if s.duration <= longest:
            shaped.append(s)
            continue
        # segment_words folds a short remainder back into the beat before it,
        # which can leave one long beat; this stretch is cut once more, at the
        # clause end nearest its middle.
        k = _middle_cut(s.words, half)
        if k is None:
            return None
        shaped += segment_words(s.words[:k]) + segment_words(s.words[k:])
    if not shaped or any(s.duration < half - 1e-6 or s.duration > longest for s in shaped):
        return None
    # The captions keep the beats' own text (the authored script, when there
    # was one): each word of it goes to the piece that is on screen when it is said.
    said = [(t_.text, t_.at) for t_ in _timed_tokens(seg) if t_.char >= m.char] + \
           [(t_.text, t_.at) for t_ in _timed_tokens(nxt)]
    texts: List[List[str]] = [[] for _ in shaped]
    for text, at in said:
        k = max((n for n, s in enumerate(shaped) if float(s.start) <= at + 1e-6), default=0)
        texts[k].append(text)
    head = _piece(seg, (seg.text or "")[:m.char].rstrip(), float(seg.start), t, words[:j])
    pieces = [_piece(nxt, " ".join(texts[k]) or s.text, float(s.start), float(s.end), list(s.words))
              for k, s in enumerate(shaped)]
    return head, pieces


def _opening(found: List[Mention], start: float, window: float) -> Optional[Mention]:
    """The person a beat opens with: the first one it names, said within `window` of its start."""
    for m in found:
        if m.kind == "person":
            return m if m.at - start < window else None
    return None


@dataclasses.dataclass
class _Beat:
    seg: object
    parent: int                        # index of the original beat it came from
    cut: Optional[Mention] = None      # the name (or place) this beat was cut at
    moved: bool = False                # it opens with a name from the end of the beat before


def _split_pass(segments: list, lexicon: List[_Pattern], head_min: float, tail_min: float,
                stats: Counter) -> List[_Beat]:
    """Each beat split once at most, at a person newly named mid-way (else a second place)."""
    beats: List[_Beat] = []
    for idx, seg in enumerate(segments):
        found = _mentions(seg, lexicon)
        cut = _choose(seg, found, head_min, tail_min) if found else None
        if cut is None:
            beats.append(_Beat(seg, idx))
            continue
        m, j, t = cut
        text, words = seg.text or "", list(seg.words or [])
        beats.append(_Beat(_piece(seg, text[:m.char].rstrip(), float(seg.start), t, words[:j]), idx))
        beats.append(_Beat(_piece(seg, text[m.char:].lstrip(), t, float(seg.end), words[j:]), idx, cut=m))
        stats["person_cuts" if m.kind == "person" else "place_cuts"] += 1
    return beats


def _move_pass(beats: List[_Beat], lexicon: List[_Pattern], head_min: float, tail_min: float,
               half: float, stats: Counter) -> List[_Beat]:
    """
    A person named in the last seconds of a beat, where a split would leave
    a flash of a shot, opens the next beat instead: the name and the rest of
    its beat join the next one, and that stretch is cut again on the usual
    rhythm. (The clause segmenter often ends a beat mid-clause: "...and then
    Governor Katie Hobbs ordered a stop | to every new well in the basin.")
    Runs after the splits, so it never takes the room a mid-beat name needed,
    and never moves a name into a beat that already opens on one. A beat that
    takes a name in gives none of its own.
    """
    def opens_on_a_name(beat: _Beat) -> bool:
        return beat.cut is not None or \
            _opening(_mentions(beat.seg, lexicon), float(beat.seg.start), head_min) is not None

    out: List[_Beat] = []
    i = 0
    while i < len(beats):
        beat = beats[i]
        nxt = beats[i + 1] if i + 1 < len(beats) else None
        got = None
        if nxt is not None and not opens_on_a_name(nxt):
            m = _trailing(beat.seg, _mentions(beat.seg, lexicon), head_min, tail_min)
            got = _recut(beat.seg, m, nxt.seg, head_min, half) if m else None
        if not got:
            out.append(beat)
            i += 1
            continue
        head, pieces = got
        out.append(_Beat(head, beat.parent, cut=beat.cut))
        out.extend(_Beat(piece, nxt.parent, moved=k == 0) for k, piece in enumerate(pieces))
        stats["moved_to_next"] += 1
        i += 2
    return out


def _focus(m: Mention, said: float, via: str, people: Dict[str, dict]) -> dict:
    p = people.get(m.name) or {}
    aliases = list(p.get("aliases") or []) + ([p["surname"]] if p.get("surname") else [])
    return {"subject": m.name, "subjectType": m.kind, "role": p.get("role") or "",
            "aliases": aliases, "said": round(max(0.0, said), 2), "via": via}


def plan_mentions(segments: list, brief: dict, min_head: float = 1.2,
                  min_tail: float = 2.0) -> Tuple[list, List[int], Dict[int, dict]]:
    """
    (new segments, parent index of each, focus) - see split_at_mentions.

    focus: {new beat index: {"subject", "subjectType", "role", "aliases",
    "said", "via"}} for every beat that opens with a named person ("opening";
    "cut" when a split made it; "moved" when the name came from the end of the
    beat before) and every beat cut at a second place. The input segments are
    never changed.
    """
    lexicon, people = _lexicon(brief)
    if not lexicon:
        return list(segments), list(range(len(segments))), {}
    half = float(getattr(config, "MIN_SCENE_SECONDS", 5.0) or 0.0) / 2.0
    head_min, tail_min = max(float(min_head), half), max(float(min_tail), half)
    stats: Counter = Counter()
    beats = _split_pass(segments, lexicon, head_min, tail_min, stats)
    beats = _move_pass(beats, lexicon, head_min, tail_min, half, stats)
    focus: Dict[int, dict] = {}
    for k, beat in enumerate(beats):
        if beat.cut is not None:
            focus[k] = _focus(beat.cut, 0.0, "cut", people)
            continue
        m = _opening(_mentions(beat.seg, lexicon), float(beat.seg.start), head_min)
        if m:
            via = "moved" if beat.moved else "opening"
            focus[k] = _focus(m, m.at - float(beat.seg.start), via, people)
            stats[via] += 1
    LAST_STATS.update(stats)
    return [b.seg for b in beats], [b.parent for b in beats], focus


def split_at_mentions(segments: list, brief: dict, min_head: float = 1.2,
                      min_tail: float = 2.0) -> list:
    """
    The beats with each one split where it names one of the story's people.

    For each beat: the first person newly named (the brief's cast names and
    aliases, its people, a surname only one of them has; whole words, any
    case - one capitalised word must be capitalised - possessives included)
    at least min_head seconds after the beat starts and min_tail before it
    ends; else, in a beat naming two different places of the brief, the
    second one. The beat is split at that mention's first word (a title in
    front of the name included), from the word timings, so the name opens its
    own beat. At most one split per beat; no piece under MIN_SCENE_SECONDS/2.
    A person named too near the end for that opens the next beat instead
    (see _move_pass). Beats without word timings are left whole.
    """
    return plan_mentions(segments, brief, min_head, min_tail)[0]


def remap_brief(brief: dict, parents: List[int]) -> None:
    """Move the brief's beat numbers (hookBeats, sections) onto the split beats, in place."""
    if not isinstance(brief, dict) or len(set(parents)) == len(parents):
        return
    children: Dict[int, List[int]] = defaultdict(list)
    for new, old in enumerate(parents):
        children[old].append(new)
    hooks = brief.get("hookBeats")
    if isinstance(hooks, list):
        hooks[:] = sorted({n for h in hooks if _is_int(h) for n in children.get(h, ())})
    for sec in brief.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        lo, hi = sec.get("from"), sec.get("to")
        if _is_int(lo) and lo in children:
            sec["from"] = children[lo][0]
        if _is_int(hi) and hi in children:
            sec["to"] = children[hi][-1]


def prepare(segments: list, brief: dict, min_head: float = 1.2,
            min_tail: float = 2.0) -> Tuple[list, Dict[int, dict]]:
    """
    Before the shots are planned: (segments split at names, focus for apply_focus).

    The brief's beat numbers are moved onto the new beats in place. Never
    raises: anything unexpected leaves the beats as they were.
    """
    LAST_STATS.clear()
    if not segments or not enabled():
        return segments, {}
    try:
        out, parents, focus = plan_mentions(segments, brief, min_head, min_tail)
        remap_brief(brief, parents)
    except Exception as e:  # noqa: BLE001 - better timing, never a failed video
        print(f"[mentions] skipped: {type(e).__name__}: {str(e)[:120]}", flush=True)
        return segments, {}
    print(f"[mentions] {len(segments)} -> {len(out)} beats: {LAST_STATS.get('person_cuts', 0)} cut at a "
          f"named person, {LAST_STATS.get('moved_to_next', 0)} name(s) moved to open the next beat, "
          f"{LAST_STATS.get('place_cuts', 0)} cut at a second place; "
          f"{LAST_STATS.get('opening', 0)} more open with a named person", flush=True)
    return out, focus


# --------------------------------------------------------------------------- #
# After the plan: the beat shows who (or what) it opens with
# --------------------------------------------------------------------------- #

_PERSON_ENTITIES = {"public-figure", "historical-person", "private-person"}
_PLACE_ENTITIES = {"natural-feature", "landmark", "building", "city-region"}


def _is_about(label: str, f: dict) -> bool:
    """Does a subject or caption name the focus person ("Governor Katie Hobbs", "Hobbs")?"""
    from .media import same_subject
    label = (label or "").strip()
    if not label:
        return False
    if same_subject(label, f["subject"]):
        return True
    have = _tokens(label)
    want = _tokens(f["subject"])
    if want and any(have[k:k + len(want)] == want for k in range(len(have) - len(want) + 1)):
        return True
    return any(have == _tokens(a) for a in f.get("aliases") or [])


def _when(brief: dict, index: int) -> str:
    """The year a history or biography beat is about (its section's, else the story's)."""
    if brief.get("kind") not in ("history", "biography"):
        return ""
    for sec in brief.get("sections") or []:
        if isinstance(sec, dict) and _is_int(sec.get("from")) and _is_int(sec.get("to")) \
                and sec["from"] <= index <= sec["to"] and _text(sec.get("when")):
            return _text(sec.get("when"))[:30]
    year = brief.get("year")
    return str(year) if _is_int(year) else ""


def _free_name_tag(shots: List[dict], i: int, f: dict) -> None:
    """
    A lower-third naming someone else must not sit on this person's face; it
    moves to the next beat that shows the one it names, when that beat has
    no graphic of its own.
    """
    from .media import same_subject
    ov = shots[i].get("overlay")
    if not isinstance(ov, dict) or ov.get("type") != "lower-third":
        return
    named = (ov.get("text") or "").strip()
    if not named or _is_about(named, f):
        return
    shots[i]["overlay"] = None
    for later in shots[i + 1:]:
        if later.get("subjectType") == "person" and same_subject(later.get("subject") or "", named):
            if not later.get("overlay"):
                later["overlay"] = dict(ov)
            break


def _show_person(shots: List[dict], i: int, seg, f: dict, brief: dict) -> bool:
    from . import director
    from .intent import SceneIntent
    shot = shots[i]
    name = f["subject"]
    if _is_about(shot.get("subject") or "", f):
        # Already about them. Only the tag may be missing: the gate that never
        # generates a real person's face reads it.
        if shot.get("subjectType") == "person":
            return False
        shot["subjectType"] = "person"
        shot["mention"] = {"name": name, "type": "person", "via": f.get("via", ""),
                           "was": shot.get("subject") or ""}
        return True
    was, old_query = shot.get("subject") or "", (shot.get("query") or "").strip()
    text = getattr(seg, "text", "") or ""
    when = _when(brief, i)
    archival = brief.get("kind") in ("history", "biography")
    who = f"{name} ({f['role']})" if f.get("role") else name
    if shot.get("visualType") == "image":
        query = f"{name} {when} {'archival photo' if archival else 'photo'}"
        intent = f"{who}: a real photograph of them"
    else:
        query = f"{name} {when} {'archival footage' if archival else 'footage'}"
        intent = f"{who} speaking on camera: an interview, a press conference or a public appearance"
    if when:
        intent += f", {when}"
    shot.update({"subject": name, "subjectType": "person", "query": " ".join(query.split())[:240],
                 "intent": intent[:300], "fallbacks": [], "anchor": True})
    if shot.get("entity") not in _PERSON_ENTITIES:
        # What kind of person they are, from a beat the director planned about them.
        shot["entity"] = next((s.get("entity") for s in shots
                               if s is not shot and s.get("entity") in _PERSON_ENTITIES
                               and _is_about(s.get("subject") or "", f)), "")
    # The director's own rule for a person in a news story: their interview
    # on the story's topic first (the plain search becomes a fallback).
    director.prefer_interviews([shot], [seg] if seg is not None else [], brief)
    si = SceneIntent.from_shot(shot, brief)
    if shot.get("visualType") == "image":
        # A portrait is a portrait: it need not be taken at the story's event or place.
        si.specificity, si.generic_ok, si.locations, si.event_type = "generic", True, [], ""
    shot["sceneIntent"] = si.to_dict()
    news = director.news_queries(shot, text, brief)
    context = director.with_subject(name, old_query) if old_query else ""
    query = shot["query"].lower()
    # Every search names them: anything else ("Phoenix 2026 groundwater cuts")
    # finds footage the judge must turn down for this beat.
    key = _surname(name) or (_tokens(name) or ("",))[-1]
    shot["fallbacks"] = [q for q in dict.fromkeys(news + list(shot.get("fallbacks") or [])
                                                  + si.queries(shot["query"])[1:] + [context, name])
                         if q and q.lower() != query and key in _tokens(q)]
    if news:
        shot["newsQueries"] = news
    else:
        shot.pop("newsQueries", None)
    shot["mention"] = {"name": name, "type": "person", "via": f.get("via", ""), "was": was}
    _free_name_tag(shots, i, f)
    return True


def _show_place(shots: List[dict], i: int, seg, f: dict, brief: dict) -> bool:
    from . import director
    from .intent import SceneIntent
    from .media import same_subject
    shot = shots[i]
    place = f["subject"]
    head = place.split(",")[0].strip()
    subject = shot.get("subject") or ""
    if same_subject(subject, place) or (head and head.lower() in subject.lower()):
        return False
    was, old_query = subject, (shot.get("query") or "").strip()
    medium = "photo" if shot.get("visualType") == "image" else "aerial footage"
    query = director.anchor_query(f"{place.replace(',', '')} {medium}", brief,
                                  getattr(seg, "text", "") or "", keep_place=True)
    shot.update({"subject": place, "subjectType": "place", "query": query[:240],
                 "entity": shot.get("entity") if shot.get("entity") in _PLACE_ENTITIES else ""})
    intent = shot.get("intent") or ""
    if head.lower() not in intent.lower():
        shot["intent"] = f"{head}: {intent}".strip(": ")[:300]
    si = SceneIntent.from_shot(shot, brief)
    shot["sceneIntent"] = si.to_dict()
    context = director.with_subject(head, old_query) if old_query else ""
    low = shot["query"].lower()
    shot["fallbacks"] = [q for q in dict.fromkeys(si.queries(shot["query"])[1:] + [context, head])
                         if q and q.lower() != low]
    shot.pop("newsQueries", None)
    shot["mention"] = {"name": place, "type": "place", "via": f.get("via", ""), "was": was}
    return True


def apply_focus(shots: List[dict], segments: list, focus: Dict[int, dict],
                brief: Optional[dict] = None) -> int:
    """
    After the plan: each beat in `focus` shows who or what it opens with.

    A person beat gets subject/subjectType "person", a search that starts
    with the name, and an intent and scene intent about them (so the vision
    judge accepts their portrait or interview and nothing else); a beat that
    already showed that person is left alone. A place beat (a split at a
    second place) gets that place in front of its search. Returns how many
    shots changed; a failure on one beat keeps the director's shot.
    """
    brief = brief if isinstance(brief, dict) else {}
    changed = 0
    for i in sorted(focus or {}):
        if not 0 <= i < len(shots) or not isinstance(shots[i], dict):
            continue
        f = focus[i]
        seg = segments[i] if i < len(segments) else None
        before = copy.deepcopy(shots[i])
        try:
            show = _show_person if f.get("subjectType") == "person" else _show_place
            changed += bool(show(shots, i, seg, f, brief))
        except Exception as e:  # noqa: BLE001 - the director's shot stays, as it was
            shots[i].clear()
            shots[i].update(before)
            print(f"[mentions] beat {i}: kept the planned shot ({type(e).__name__}: {str(e)[:100]})",
                  flush=True)
    LAST_STATS["shots_refocused"] = changed
    if focus:
        print(f"[mentions] {changed}/{len(focus)} beat(s) now show who or what they open with", flush=True)
    return changed
