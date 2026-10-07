"""
On-screen sources: when a line states a fact and NAMES where it comes from, a
small citation tag shows in a low corner for about three seconds -
"SOURCE: USBR, 2024".

Nothing is invented. A tag is made only from the narration's own words: the
line must name an organisation or a publication inside an attribution
("according to the Bureau of Reclamation", "USGS data shows", "a 2024 NOAA
report found", "researchers at the University of Arizona found", "a study
published in Nature"), and the year is shown only when the line says it of that
source ("a 2024 NOAA report") - or the brief's own sources list gives it for
the source a line names that says no year itself - and never a year still to
come ("2050 projections"). A figure with no named source gets no tag; "experts
say", "studies show" and "according to officials" name nobody; an agency that
is doing something ("the Bureau of Reclamation built the dam") is not being
cited, and a person is introduced by the person looks, not cited here. A
built-in short form is shown only for that body as written ("a geological
survey", "the state Department of Agriculture" and "the Geological Survey of
India" are not the USGS or the USDA).

find() is what treatments.py calls per line (behind config.SOURCE_TAGS): pure
functions, no network, deterministic. settle() runs once the pictures are final
(handler.do_plan, after smart reframing): a tag never sits over a face - it
takes the other low corner, or is left out - and never over a full-screen
graphic.
"""
import re
import time
from typing import Callable, Dict, List, Optional, Tuple

from .presenter import is_presenter_scene

LOOK = "LIB_SRC_TAG"            # the one look (remotion LibSourceTag.tsx, "src-tag"), registered autoPick false
MAX_NAME = 40                   # a name longer than this is not a tag (it would be a sentence in the corner)

_Y = r"(?:19|20)\d{2}"

# --------------------------------------------------------------------------- the names
# (id, what the tag shows, acronyms as written, spelled-out names). An acronym counts only in capitals ("WHO",
# never "who"; "U.S.G.S." too); a spelled-out name in any case, with "U.S." / "United States" before it or not.
# One word ("Reuters") only as written. The tag shows the short form a viewer knows, else the name itself.
_KNOWN: List[Tuple[str, str, List[str], List[str]]] = [
    ("usbr", "USBR", ["USBR"], ["Bureau of Reclamation"]),
    ("usgs", "USGS", ["USGS"], ["Geological Survey"]),
    ("noaa", "NOAA", ["NOAA"], ["National Oceanic and Atmospheric Administration"]),
    ("nws", "NWS", ["NWS"], ["National Weather Service"]),
    ("nhc", "NHC", ["NHC"], ["National Hurricane Center"]),
    ("spc", "STORM PREDICTION CENTER", [], ["Storm Prediction Center"]),
    ("cpc", "CLIMATE PREDICTION CENTER", [], ["Climate Prediction Center"]),
    ("wpc", "WEATHER PREDICTION CENTER", [], ["Weather Prediction Center"]),
    ("nasa", "NASA", ["NASA"], ["National Aeronautics and Space Administration"]),
    ("epa", "EPA", ["EPA"], ["Environmental Protection Agency"]),
    ("usace", "USACE", ["USACE"], ["Army Corps of Engineers"]),
    ("fema", "FEMA", ["FEMA"], ["Federal Emergency Management Agency"]),
    ("cdc", "CDC", ["CDC"], ["Centers for Disease Control and Prevention", "Centers for Disease Control"]),
    ("usda", "USDA", ["USDA"], ["Department of Agriculture"]),
    ("eia", "EIA", ["EIA"], ["Energy Information Administration"]),
    ("census", "U.S. CENSUS BUREAU", [], ["Census Bureau"]),
    ("bls", "BLS", ["BLS"], ["Bureau of Labor Statistics"]),
    ("blm", "BLM", ["BLM"], ["Bureau of Land Management"]),
    ("drought-monitor", "U.S. DROUGHT MONITOR", [], ["Drought Monitor"]),
    ("nps", "NATIONAL PARK SERVICE", [], ["National Park Service"]),
    ("usfs", "U.S. FOREST SERVICE", [], ["Forest Service"]),
    ("usfws", "U.S. FISH & WILDLIFE SERVICE", [], ["Fish and Wildlife Service"]),
    ("nifc", "NIFC", ["NIFC"], ["National Interagency Fire Center"]),
    ("calfire", "CAL FIRE", [], ["Cal Fire", "CalFire"]),
    ("nsidc", "NSIDC", ["NSIDC"], ["National Snow and Ice Data Center"]),
    ("ipcc", "IPCC", ["IPCC"], ["Intergovernmental Panel on Climate Change"]),
    ("who", "WHO", ["WHO"], ["World Health Organization", "World Health Organisation"]),
    ("un", "UNITED NATIONS", ["UN"], ["United Nations"]),
    ("wmo", "WMO", ["WMO"], ["World Meteorological Organization", "World Meteorological Organisation"]),
    ("world-bank", "WORLD BANK", [], ["World Bank"]),
    ("imf", "IMF", ["IMF"], ["International Monetary Fund"]),
    ("iea", "IEA", ["IEA"], ["International Energy Agency"]),
    ("fao", "FAO", ["FAO"], ["Food and Agriculture Organization"]),
    ("gao", "GAO", ["GAO"], ["Government Accountability Office"]),
    ("cbo", "CBO", ["CBO"], ["Congressional Budget Office"]),
    ("fed", "FEDERAL RESERVE", [], ["Federal Reserve"]),
    ("snwa", "SNWA", ["SNWA"], ["Southern Nevada Water Authority"]),
    ("cap", "CENTRAL ARIZONA PROJECT", [], ["Central Arizona Project"]),
    ("srp", "SALT RIVER PROJECT", [], ["Salt River Project"]),
    ("ercot", "ERCOT", ["ERCOT"], ["Electric Reliability Council of Texas"]),
    ("pew", "PEW RESEARCH CENTER", [], ["Pew Research Center", "Pew Research"]),
    ("ap", "AP", ["AP"], ["Associated Press"]),
    ("reuters", "REUTERS", [], ["Reuters"]),
    ("nyt", "THE NEW YORK TIMES", [], ["New York Times"]),
    ("wapo", "THE WASHINGTON POST", [], ["Washington Post"]),
    ("lat", "LOS ANGELES TIMES", [], ["Los Angeles Times", "L.A. Times", "LA Times"]),
    ("wsj", "THE WALL STREET JOURNAL", [], ["Wall Street Journal"]),
    ("bloomberg", "BLOOMBERG", [], ["Bloomberg"]),
    ("guardian", "THE GUARDIAN", [], ["Guardian"]),
    ("propublica", "PROPUBLICA", [], ["ProPublica"]),
    ("bbc", "BBC", ["BBC"], []),
    ("cnn", "CNN", ["CNN"], []),
    ("npr", "NPR", ["NPR"], []),
    ("pnas", "PNAS", ["PNAS"], ["Proceedings of the National Academy of Sciences"]),
    ("nature-climate", "NATURE CLIMATE CHANGE", [], ["Nature Climate Change"]),
    ("nature-comms", "NATURE COMMUNICATIONS", [], ["Nature Communications"]),
    ("science-advances", "SCIENCE ADVANCES", [], ["Science Advances"]),
    ("grl", "GEOPHYSICAL RESEARCH LETTERS", [], ["Geophysical Research Letters"]),
    ("wrr", "WATER RESOURCES RESEARCH", [], ["Water Resources Research"]),
]
# A journal whose name is an everyday word: a source only where the line says it was published there
# ("a study in Nature", "published in Science", "the journal Nature") - never "according to science".
_JOURNALS: List[Tuple[str, str, List[str]]] = [
    ("nature", "NATURE", ["Nature"]),
    ("science", "SCIENCE", ["Science"]),
    ("lancet", "THE LANCET", ["Lancet"]),
]

# A capitalised word that may stand before a name without being part of it ("But NOAA...", "In March the...").
_LEAD = frozenset("""But And Yet So Still Now Today However Meanwhile Then In On At By For As If When While Because
Although Though Even Here There This That These Those It Its Their His Her Our Since After Before Until Once Recent
Later Earlier Also Both Only Just Instead Indeed Worse Again Every Each Some Many Most One Two Three With From Per
Citing The A An According Yesterday Tomorrow Monday Tuesday Wednesday Thursday Friday Saturday Sunday January
February March April May June July August September October November December""".split())
# A word that makes a capitalised name an organisation or a publication ("Pacific Institute", "University of
# Arizona", "Imperial Irrigation District", "Salt Lake Tribune").
_ORG_WORDS = frozenset("""Bureau Department Agency Administration Service Survey Authority Commission Institute
Institution University College Center Centre Board Office Council Association Laboratory Lab Observatory District
Corps Foundation Society Organization Organisation Ministry Academy Committee Group Fund Times Post Journal Tribune
Herald Gazette Chronicle News Magazine Review Union Federation Alliance Coalition Trust Consortium Panel
Conservancy""".split())
_CAP = r"(?:U\.S\.|[A-Z][A-Za-z0-9&'’-]*)"
_PHRASE = re.compile(_CAP + r"(?:\s+(?:(?:of|for|on)\s+(?:the\s+)?|and\s+|&\s+)?" + _CAP + r"){1,7}")
_US = r"(?:(?:(?i:United[\s-]+States)|U\.?\s?S\.?)\s+)?"
_SMALL = frozenset(("of", "and", "for", "the", "on", "in", "&"))
# A lower-case word before a federal or world body's name that makes it some other body: "the state Department of
# Agriculture" is not the USDA, "the county Forest Service" not the U.S. Forest Service.
_LOCAL = frozenset("state state's states' local county city provincial regional tribal municipal territorial".split())


def _spelled(name: str) -> str:
    """
    A spelled-out name as it is written: its capitals kept (or the whole name in capitals), only the small words
    in any case. "Bureau of Reclamation" or "BUREAU OF RECLAMATION" - never "a geological survey" (a survey, not
    the USGS) or "the state forest service" (not the U.S. Forest Service).
    """
    words = name.split()
    if len(words) == 1:
        return re.escape(name)                      # one word: only as written
    return r"[\s-]+".join("(?i:" + re.escape(w) + ")" if w.lower() in _SMALL
                          else "(?:" + re.escape(w) + "|" + re.escape(w.upper()) + ")" for w in words)


def _titled(name: str) -> str:
    """ "bureau of reclamation" -> "Bureau of Reclamation" (a brief's own spelling of a built-in name)."""
    return " ".join(w if w.lower() in _SMALL or w[:1].isupper() else w[:1].upper() + w[1:] for w in name.split())


def _this_year() -> int:
    return time.gmtime().tm_year


def _acronym(a: str) -> str:
    return "(?:" + re.escape(a) + "|" + r"\.".join(re.escape(ch) for ch in a) + r"\.?)"


def _compile(acronyms: List[str], names: List[str], us: bool = True) -> "re.Pattern":
    alts = [(_US if us else "") + _spelled(n) for n in sorted(names, key=lambda s: -len(s))] + [_acronym(a) for a in acronyms]
    return re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(alts) + r")(?![A-Za-z0-9])")


_KNOWN_RX = [(kid, tag, _compile(acr, names)) for kid, tag, acr, names in _KNOWN]
_JOURNAL_RX = [(kid, tag, _compile([], names, us=False)) for kid, tag, names in _JOURNALS]
_NAMED_JOURNAL = re.compile(r"\bthe\s+journal\s+([A-Z][\w&'’-]*(?:\s+(?:(?:of|and|&)\s+)?[A-Z][\w&'’-]*){0,5})")

# --------------------------------------------------------------------------- the attributions
_DOC = (r"(?:data|figures|numbers|records|measurements|readings|estimates|projections|models?|modell?ing|reports?|"
        r"studies|study|research|analysis|analyses|surveys?|forecasts?|outlooks?|statistics|gauges?|sensors?|"
        r"satellites?|maps?|imagery|images|findings|assessments?|audits?|papers?|reviews?|investigations?)")
_PEOPLE = (r"(?:scientists|researchers|experts|hydrologists|engineers|economists|analysts|officials|forecasters|"
           r"meteorologists|climatologists|geologists|biologists|seismologists|investigators|inspectors|regulators)")
_SHOW = (r"(?:shows?|showed|suggests?|suggested|indicates?|indicated|reveals?|revealed|confirms?|confirmed|found|"
         r"finds?|says?|said|warns?|warned|estimates?|estimated|puts?|projects?|projected|predicts?|predicted|"
         r"concluded?|concludes|reported|reports?|calculated?|calculates|recorded|measured|expects?|expected|"
         r"believes?|documented|counted|tracked|notes?|noted|tells?)")
# A verb of saying that is never a noun ...
_SURE = (r"(?:says|said|reported|estimated|found|calculated|calculates|measured|recorded|concluded|concludes|"
         r"projected|predicted|predicts|warned|warns|confirmed|confirms|noted|showed|expects|expected|documented|"
         r"determined|stated|cautioned)")
# ... and one that is also a noun ("Bureau of Reclamation projects supply water"): only before what it says.
_AMBIG = r"(?:reports|estimates|projects|forecasts|counts|measures|notes|puts|records|finds|shows)"
_THEN = (r"(?=(?:that|a|an|the|about|around|roughly|nearly|almost|more|less|fewer|up|over|under|only|just|at|its|"
         r"it|there|some|this|these|those)\b|\d|\$)")
_ADJ = r"(?:new|recent|latest|landmark|major|leaked|internal|federal|joint|separate|earlier|later|key)"
_FILL = (r"(?:the|a|an|one|new|recent|latest|most|its|their|own|official|federal|government|state|preliminary|"
         r"updated|data|figures|numbers|records|estimates|projections|measurements|readings|statistics|reports?|"
         r"study|studies|survey|analysis|research|findings|forecasts?|modell?ing|models|scientists|researchers|"
         r"experts|hydrologists|officials|engineers|economists|analysts|forecasters|meteorologists|from|by|at|with|"
         r"of|published|released|compiled|in|" + _Y + r")")
_POSS = r"(?:'s|’s)?"
# A year said OF a report ("a 2021 study", "the 2024 survey") - never a count that looks like one
# ("more than 2000 measurements from the USGS" has no year).
_DET_YEAR = r"(?:(?:a|an|the|one|that|this|its|their|in|from|new|recent)\s+(?P<y0>" + _Y + r")\s+)?"

# What stands BEFORE the name (anchored on it) ...
_L_ACCORDING = re.compile(r"\b(?:according\s+to|citing)\s+((?:" + _FILL + r"\s+){0,6})$", re.I)
_L_DOC_BY = re.compile(r"\b" + _DET_YEAR + _DOC + r"(?:\s+(?:published|released|compiled|commissioned|"
                       r"conducted|collected|gathered|produced|issued|prepared))?(?:\s+in\s+(?P<y1>" + _Y + r"))?"
                       r"\s+(?:from|by)\s+(?:the\s+)?$", re.I)
_L_VERB_BY = re.compile(r"\b(?:reported|measured|recorded|documented|confirmed|estimated|published|compiled|tracked|"
                        r"collected|calculated|gathered|issued|verified|projected|forecast|predicted)"
                        r"\s+(?:in\s+(?P<y1>" + _Y + r")\s+)?by\s+(?:the\s+)?$", re.I)
_L_PEOPLE = re.compile(r"\b" + _PEOPLE + r"\s+(?:at|from|with|for)\s+(?:the\s+)?$", re.I)
_L_A_DOC = re.compile(r"\b(?:(?:a|an|one)\s+(?:" + _ADJ + r"\s+)?(?:(?P<y0>" + _Y + r")\s+)?|"
                      r"(?:the|this|that|its|their)\s+(?:" + _ADJ + r"\s+)?(?P<y1>" + _Y + r")\s+)$", re.I)
_L_YEAR = re.compile(r"\b(?:the|a|an|in|from|its|their|that|this|by)\s+(" + _Y + r")\s+$", re.I)
_L_JOURNAL = re.compile(r"(?:\b(?:published|appeared|appearing|printed)\s+(?:in\s+(?P<y1>" + _Y + r")\s+)?in\s+"
                        r"(?:the\s+journal\s+)?|\b(?:(?P<y0>" + _Y + r")\s+)?(?:study|paper|article|research|analysis|"
                        r"report|review)\s+in\s+(?:the\s+journal\s+)?|\bthe\s+journal\s+)$", re.I)
# ... and what stands AFTER it. (A report may say what kind it is: "the Bureau's 24-month study", "USGS streamflow data".)
_KIND = (r"(?:\w+-\w+|seasonal|annual|monthly|weekly|daily|streamflow|satellite|radar|gauge|climate|weather|water|"
         r"drought|flood|snowpack|monitoring|historical|preliminary|internal|field|ground)")
_R_DOC_SHOWS = re.compile(r"^" + _POSS + r"\s+(?:own\s+|latest\s+|newest\s+|most\s+recent\s+|new\s+|official\s+)?"
                          r"(?:(?P<y2>" + _Y + r")\s+)?(?:" + _KIND + r"\s+){0,2}"
                          r"(?:" + _DOC + "|" + _PEOPLE + r"|spokes(?:person|man|woman))"
                          r"(?:\s+from\s+(?P<y3>" + _Y + r"))?\s+(?:that\s+)?(?:now\s+|also\s+|clearly\s+|already\s+|"
                          r"have\s+|has\s+|had\s+)?" + _SHOW + r"\b", re.I)
_R_VERB = re.compile(r"^\s+(?:now\s+|also\s+|has\s+|have\s+|had\s+|recently\s+|later\s+|officially\s+|itself\s+|even\s+)?"
                     r"(?:" + _SURE + r"\b|" + _AMBIG + r"\s+" + _THEN + r")", re.I)
_R_SHOW = re.compile(r"^" + _POSS + r"\s+(?:have\s+|has\s+|had\s+|now\s+|also\s+|later\s+)?" + _SHOW + r"\b", re.I)
_R_DOC_NOUN = re.compile(r"^" + _POSS + r"\s+(?:(?P<y2>" + _Y + r")\s+)?(?:report|study|survey|analysis|assessment|"
                         r"audit|paper|review|outlook|estimate|forecast|bulletin|briefing|memo|investigation|"
                         r"projection|dataset|database)\b", re.I)
_R_IN_YEAR = re.compile(r"^\s+in\s+(" + _Y + r")\b", re.I)
# The name is the object of the line, not its speaker: "a lawsuit against the EPA found ...", "the deal with the
# Bureau of Reclamation says ..." (the people who speak for a body are read by _L_PEOPLE first).
_NOT_SUBJECT = re.compile(r"\b(?:against|about|on|over|into|onto|towards?|than|like|unlike|despite|without|under|"
                          r"between|behind|near|beyond|upon|versus|vs\.?|with)\s+(?:the\s+)?$", re.I)
_ENDS_SENTENCE = re.compile(r"[.!?…][\"'”’)\]]*\s*$")
_KEY_SKIP = {"the", "us", "united", "states", "of", "for", "and", "on"}


# --------------------------------------------------------------------------- the brief's own list
def brief_sources(brief: Optional[dict]) -> List[dict]:
    """
    The brief's sources list, when it has one, as [{"name", "tag", "year", "id", "rx"}]: names the narration may
    cite beyond the built-in ones, and the year of a source the line names without saying its year. An entry
    is a name ("Pacific Institute") or {"name" / "publisher" / "org", "short" / "tag", "year" / "date"}.
    Still only shown when the LINE names the source: the list never puts a tag on a line by itself.
    """
    out: List[dict] = []
    raw = (brief or {}).get("sources") if isinstance(brief, dict) else None
    for entry in raw if isinstance(raw, list) else []:
        if isinstance(entry, str):
            name, short, year = entry, "", None
        elif isinstance(entry, dict):
            name = str(entry.get("name") or entry.get("publisher") or entry.get("org") or "")
            short = str(entry.get("short") or entry.get("tag") or "")
            year = entry.get("year") if entry.get("year") is not None else entry.get("date")
        else:
            continue
        m = re.search(r"(?<!\d)(" + _Y + r")(?!\d)", str(year if year is not None else ""))
        if m is None and isinstance(entry, str):
            # "Bureau of Reclamation, 2024": the year written after the name
            m = re.search(r"[,(]\s*(" + _Y + r")\)?\s*$", name)
            if m:
                name = name[:m.start()]
        name = re.sub(r"\s+", " ", name).strip(" ,.;:-")
        name = re.sub(r"^the\s+", "", name, flags=re.I)
        if len(name) < 2 or len(name) > 80:
            continue
        known = next((kid for kid, _tag, rx in _KNOWN_RX if rx.fullmatch(name) or rx.fullmatch(_titled(name))), "")
        tag = next((t for kid, t, _rx in _KNOWN_RX if kid == known), "") or (short or name).upper()
        if len(tag) > MAX_NAME:
            continue
        # (A built-in name keeps its own pattern and tag; the list only adds its year.)
        rx = None if known else re.compile(r"(?<![A-Za-z0-9])" + r"[\s-]+".join(re.escape(w) for w in name.split())
                                           + r"(?![A-Za-z0-9])", re.I)
        out.append({"name": name, "tag": tag, "year": int(m.group(1)) if m else None,
                    "id": known or "brief:" + name.lower(), "rx": rx})
    return out


# --------------------------------------------------------------------------- finding
def _before_is_name(text: str, start: int) -> bool:
    """A capitalised word stands right before the match and belongs to it: "British Geological Survey" is not
    the USGS, "Texas Department of Agriculture" not the USDA."""
    m = re.search(r"([A-Za-z][A-Za-z0-9&'’.-]*)\s+$", text[:start])
    if not m:
        return False
    word = m.group(1)
    return word[:1].isupper() and word.rstrip(".") not in _LEAD and word not in ("U.S.", "US")


def _other_body(text: str, start: int, end: int) -> bool:
    """
    The built-in name at text[start:end] is part of some other body's name, so its tag would name the wrong one:
    a capitalised word before it ("British Geological Survey"), a local word before it ("the state Department of
    Agriculture"), or "of <Name>" after it ("the Geological Survey of India").
    """
    if _before_is_name(text, start):
        return True
    m = re.search(r"([A-Za-z][A-Za-z'’]*)\s+$", text[:start])
    if m and m.group(1).lower().replace("’", "'") in _LOCAL:
        return True
    return re.match(r"\s+of\s+(?:the\s+)?[A-Z]", text[end:]) is not None


def _who_cited(text: str, start: int, end: int) -> bool:
    """ "WHO" is the World Health Organization only as one ("the WHO", "according to WHO", "WHO's report") - never
    the word ("WHO decided this?")."""
    return bool(re.search(r"(?:\bthe|\baccording\s+to|\bciting|\bby|\bfrom)\s+$", text[:start], re.I)
                or text[end:end + 2] in ("'s", "’s"))


def _candidates(text: str, listed: Optional[List[dict]] = None) -> List[dict]:
    """Every name in the text that could be a source, in the order said: {"start", "end", "id", "tag", "kind"}."""
    found: List[dict] = []
    for entry in listed or []:
        if entry.get("rx") is not None:
            for m in entry["rx"].finditer(text):
                found.append({"start": m.start(), "end": m.end(), "id": entry["id"], "tag": entry["tag"], "kind": "org",
                              "listed": True})
    for kid, tag, rx in _KNOWN_RX:
        for m in rx.finditer(text):
            if kid == "who" and m.group(0) == "WHO" and not _who_cited(text, m.start(), m.end()):
                continue
            if not _other_body(text, m.start(), m.end()):
                found.append({"start": m.start(), "end": m.end(), "id": kid, "tag": tag, "kind": "org"})
    for kid, tag, rx in _JOURNAL_RX:
        for m in rx.finditer(text):
            found.append({"start": m.start(), "end": m.end(), "id": kid, "tag": tag, "kind": "journal"})
    for m in _NAMED_JOURNAL.finditer(text):
        name = m.group(1)
        if len(name) <= MAX_NAME:
            found.append({"start": m.start(1), "end": m.end(1), "id": "journal:" + name.lower(), "tag": name.upper(),
                          "kind": "journal"})
    # the longest first, so a known name inside a longer one never splits it
    found.sort(key=lambda c: (-(c["end"] - c["start"]), c["start"]))
    kept: List[dict] = []
    for c in found:
        if not any(c["start"] < k["end"] and k["start"] < c["end"] for k in kept):
            kept.append(c)
    for m in _PHRASE.finditer(text):
        c = _generic(text, m.start(), m.end())
        if c and not any(c["start"] < k["end"] and k["start"] < c["end"] for k in kept):
            kept.append(c)
    kept.sort(key=lambda c: c["start"])
    return kept


def _generic(text: str, start: int, end: int) -> Optional[dict]:
    """A capitalised name that is an organisation by its own words ("Pacific Institute"), as said; else None."""
    words = [(m.group(0), start + m.start(), start + m.end()) for m in re.finditer(r"\S+", text[start:end])]
    while words and (words[0][0] in _LEAD or words[0][0].lower() in ("of", "for", "on", "and", "&", "the")):
        words.pop(0)
    caps = [w for w, _a, _b in words if w[:1].isupper()]
    org = [w for w in caps if re.sub(r"(?:'s|’s)$", "", w) in _ORG_WORDS]
    if len(caps) < 2 or not org:
        return None
    if all(w == "Administration" for w in org) and len(caps) < 3:
        return None                         # "the Biden Administration" is not a publication
    first_org = next(i for i, (w, _a, _b) in enumerate(words) if re.sub(r"(?:'s|’s)$", "", w) in _ORG_WORDS)
    if any(w.lower() in ("of", "for") for w, _a, _b in words[:first_org]):
        # "Brad Udall of Colorado State University": a person and where they work. The person looks introduce
        # people; a source tag never shows a person's name.
        return None
    a, b = words[0][1], words[-1][2]
    name = re.sub(r"(?:'s|’s)$", "", re.sub(r"\s+", " ", text[a:b]))
    if text[a:b].endswith(("'s", "’s")):
        b -= 2
    if len(name) > MAX_NAME:
        return None
    return {"start": a, "end": b, "id": "org:" + name.lower(), "tag": name.upper(), "kind": "org"}


def _year(*values) -> Optional[int]:
    for v in values:
        if v:
            return int(v)
    return None


def _cited(text: str, c: dict) -> Optional[Tuple[str, Optional[int]]]:
    """(how, year) when the name at `c` is being cited, else None. The year only when it is said of the source."""
    left, right = text[max(0, c["start"] - 140):c["start"]], text[c["end"]:c["end"] + 140]
    m = _L_JOURNAL.search(left)
    if m:
        r = _R_IN_YEAR.match(right)                      # "appeared in Science in 2021"
        return "published-in", _year(m.group("y0"), m.group("y1"), r.group(1) if r else None)
    if c["kind"] == "journal":
        return None                         # an everyday word: a source only where something was published in it
    m = _L_ACCORDING.search(left)
    if m:
        r = _R_DOC_NOUN.match(right) or _R_DOC_SHOWS.match(right)
        years = re.findall(_Y, m.group(1) or "")
        return "according-to", _year(years[-1] if years else None, r.groupdict().get("y2") if r else None)
    m = _L_DOC_BY.search(left)
    if m:
        return "data-from", _year(m.group("y1"), m.group("y0"))
    m = _L_VERB_BY.search(left)
    if m:
        return "reported-by", _year(m.group("y1"))
    before = _L_YEAR.search(left)
    r = _R_DOC_SHOWS.match(right)
    if r:
        return "data-shows", _year(r.group("y2"), r.group("y3"), before.group(1) if before else None)
    m = _L_A_DOC.search(left)
    r = _R_DOC_NOUN.match(right)
    if m and r:
        return "a-report", _year(m.group("y0"), m.group("y1"), r.group("y2"))
    if _L_PEOPLE.search(left) and _R_SHOW.match(right):
        return "people-at", None
    if _R_VERB.match(right) and not _NOT_SUBJECT.search(left):
        return "says", None
    return None


def _key(text: str, start: int, end: int) -> Tuple[str, int]:
    """The word the tag lands on - the first of the name that carries it - and where it stands in the line."""
    for m in re.finditer(r"\S+", text[start:end]):
        bare = re.sub(r"[^A-Za-z0-9]", "", m.group(0)).lower()
        if len(bare) >= 2 and bare not in _KEY_SKIP:
            return m.group(0).strip(",;:()\"'”’"), start + m.start()
    return text[start:end].split()[0], start


def find(text: str, after: str = "", listed: Optional[List[dict]] = None) -> Optional[dict]:
    """
    The source this line cites, or None: {"id", "name" (what the tag shows), "year" (or None), "key" (the word
    to land on), "start" (where that word stands in the line), "said" (the name as said), "how", "listed"}.
    `after`: the next line, read on when this one stops mid-sentence ("... the Bureau of Reclamation" /
    "estimates that ..."): the name must still be said in THIS line. `listed`: brief_sources(brief).
    """
    line = str(text or "")
    if not line.strip():
        return None
    whole = line
    if after and not _ENDS_SENTENCE.search(line):
        whole = line.rstrip() + " " + str(after).lstrip()
    limit = len(line.rstrip())
    for c in _candidates(whole, listed):
        if c["start"] >= limit:
            break                           # named in the next line: that line's own tag
        got = _cited(whole, c)
        if got is None:
            continue
        how, year = got
        if year is not None and not 1900 <= year <= _this_year():
            year = None                     # a year to come ("2050 projections") is not when the source said it
        by_list = False
        if year is None and not re.search(r"(?<!\d)" + _Y + r"(?!\d)", line):
            # The brief's year for the source - only on a line that says no year of its own: "in 1983 the Bureau
            # warned ..." is not the Bureau's 2026 report.
            for entry in listed or []:
                if entry["id"] == c["id"] and entry.get("year") and 1900 <= int(entry["year"]) <= _this_year():
                    year, by_list = int(entry["year"]), True
                    break
        key, at = _key(whole, c["start"], min(c["end"], limit))
        return {"id": c["id"], "name": c["tag"], "year": year, "key": key, "start": at,
                "said": re.sub(r"\s+", " ", whole[c["start"]:c["end"]]), "how": how,
                "listed": bool(c.get("listed") or by_list)}
    return None


def label(found: dict) -> str:
    """The tag as it reads on screen: "SOURCE: USBR, 2024"."""
    return "SOURCE: " + found["name"] + (f", {found['year']}" if found.get("year") else "")


# --------------------------------------------------------------------------- never over a face
# Where a tag is drawn (LibSourceTag.tsx), as shares of the frame: from the 96 px side margin, as wide as its
# words in tracked caps (measured on the rendered stills: about 0.0086 of the width a character at 1080p, never
# wider than ROOM), its rule and one line of small caps standing on the 96 px bottom margin - or on the caption
# strip (layout.ts CAPTION_SAFE_ZONE) when captions are on. A face must keep clear of that box plus AIR.
MARGIN_X = 96 / 1920.0
CHAR_SHARE = 0.009
ROOM = 0.42
AIR = 0.03
ROWS = {False: (0.80, 0.98), True: (0.62, 0.80)}     # (y0, y1) with air: captions off / on
FACE_PAD = 0.3                  # a face keeps this much of its own size clear on every side
FACE_SECONDS = 20.0             # looking for faces under the tags never takes longer than this in all


def zone(side: str, line: str = "", captions: bool = False) -> Tuple[float, float, float, float]:
    """The box (x0, y0, x1, y1) a tag reading `line` takes in the `side` low corner, with air round it."""
    width = min(ROOM, max(0.1, len(line) * CHAR_SHARE))
    y0, y1 = ROWS[bool(captions)]
    if side == "right":
        return 1.0 - MARGIN_X - width - AIR, y0, 1.0 - MARGIN_X + AIR, y1
    return MARGIN_X - AIR, y0, MARGIN_X + width + AIR, y1


def _line_of(ov: dict) -> str:
    """The tag's words as drawn: "SOURCE: USBR, 2024"."""
    label = str(ov.get("label") or "Source").strip()
    year = str(ov.get("subtitle") or "").strip()
    return f"{label}: {str(ov.get('text') or '').strip()}" + (f", {year}" if year else "")


def _cover(box: List[float], src_aspect: float, frame_aspect: float) -> Tuple[float, float, float, float]:
    """A box of the source picture (x, y, w, h shares) in the frame once the picture is cover-fitted: x0, y0, x1, y1."""
    x, y, w, h = (float(v) for v in box[:4])
    if src_aspect > 0 and frame_aspect > 0 and abs(src_aspect - frame_aspect) > 1e-3:
        if src_aspect > frame_aspect:            # wider: the sides are cut
            keep = frame_aspect / src_aspect
            x, w = (x - (1 - keep) / 2) / keep, w / keep
        else:                                    # taller: top and bottom are cut
            keep = src_aspect / frame_aspect
            y, h = (y - (1 - keep) / 2) / keep, h / keep
    return x, y, x + w, y + h


def _through(view: dict, b: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
    """Where a frame box lands on screen while the picture is shown through `view` (a reframe viewport)."""
    try:
        vx, vy, vw, vh = float(view["x"]), float(view["y"]), float(view["w"]), float(view["h"])
    except (KeyError, TypeError, ValueError):
        return b
    if vw <= 0 or vh <= 0:
        return b
    return (b[0] - vx) / vw, (b[1] - vy) / vh, (b[2] - vx) / vw, (b[3] - vy) / vh


def _faces_now(scene: dict, fps: float) -> Optional[dict]:
    """The faces in a scene's picture, found now (the files are still local): {"boxes": [[x, y, w, h]], "aspect"}
    in shares of the source; None when it cannot be looked at (no local file, no face model)."""
    try:
        from . import reframe
        m = scene.get("media") or {}
        path = str(m.get("url") or "")
        if reframe.np is None or not reframe._local(path) or not reframe.faces_available():
            return None
        if m.get("type") == "image":
            from PIL import Image
            with Image.open(path) as im:
                im = im.convert("RGB")
                w, h = im.size
                aw = reframe.ANALYSIS_W if w >= h else max(64, int(round(reframe.ANALYSIS_W * w / float(h))))
                frames = [reframe.np.asarray(im.resize((aw, max(64, int(round(aw * h / float(w))))), Image.BILINEAR))]
        elif m.get("type") == "video":
            w, h, dur = reframe._probe(path)
            if not w or not h:
                return None
            shown = reframe.shown_seconds(scene, fps)
            shown = max(0.5, min(shown, dur) if dur > 0 else shown)
            frames = reframe._decode(path, shown, 3.0 / shown, reframe.ANALYSIS_W,
                                     reframe._even(reframe.ANALYSIS_W * h / float(w)), timeout=15.0)
        else:
            return None
        if not frames:
            return None
        return {"boxes": [f[:4] for frame in frames[:4] for f in reframe.find_faces(frame)], "aspect": w / float(h)}
    except Exception as e:  # noqa: BLE001 - a look at the picture never fails a job
        print(f"[sources] face check skipped: {type(e).__name__}: {str(e)[:100]}", flush=True)
        return None


def _faces_on_screen(scene: dict, frame_aspect: float, fps: float, look: Optional[Callable]) -> Optional[list]:
    """The faces of a scene as boxes on screen (x0, y0, x1, y1, padded); [] = none; None = could not be looked at."""
    m = scene.get("media") if isinstance(scene.get("media"), dict) else {}
    if m.get("type") not in ("video", "image"):
        return []
    focus = m.get("focus") if isinstance(m.get("focus"), dict) else None
    if focus is not None and "faces" in focus:
        # Smart reframing looked for faces here (src/reframe.py _focus_of): its count is the answer.
        boxes = focus.get("faceBoxes") if focus.get("kind") == "face" else []
        aspect = float(focus.get("aspect") or frame_aspect)
    else:
        seen = look(scene, fps) if look is not None else None
        if seen is None:
            return None
        boxes, aspect = seen.get("boxes") or [], float(seen.get("aspect") or frame_aspect)
    views = []
    move = m.get("reframe") if isinstance(m.get("reframe"), dict) else {}
    if scene.get("reframe") not in ("off", False):
        views = [v for v in (move.get("from"), move.get("to")) if isinstance(v, dict)]
    out = []
    for b in boxes or []:
        try:
            x, y, w, h = (float(v) for v in b[:4])
        except (TypeError, ValueError):
            continue
        padded = [x - FACE_PAD * w, y - FACE_PAD * h, w * (1 + 2 * FACE_PAD), h * (1 + 2 * FACE_PAD)]
        on = _cover(padded, aspect, frame_aspect)
        out.append(on)
        out.extend(_through(v, on) for v in views)
    return out


def _hits(zone: Tuple[float, float, float, float], boxes: list) -> bool:
    return any(b[0] < zone[2] and zone[0] < b[2] and b[1] < zone[3] and zone[1] < b[3] for b in boxes)


def settle(doc: dict, look: Optional[Callable] = _faces_now, budget: float = FACE_SECONDS) -> Dict[str, object]:
    """
    With the pictures final: every source tag keeps off faces and off full-screen graphics. A tag whose
    corner has a face under it takes the other low corner (never the brand watermark's); with a face there
    too, or over a scene that became a full-screen graphic, it is left out. Faces are read from media.focus
    where smart reframing looked, else found now in the local file (`look`; time-boxed). Never raises.
    Returns the counts for doc.meta.sourceTags ({} when the video has no source tag).
    """
    try:
        return _settle(doc, look, budget)
    except Exception as e:  # noqa: BLE001 - a nicety, never a failure
        print(f"[sources] settle skipped: {type(e).__name__}: {str(e)[:160]}", flush=True)
        return {"error": f"{type(e).__name__}: {str(e)[:160]}"}


def _settle(doc: dict, look: Optional[Callable], budget: float) -> Dict[str, object]:
    overlays = doc.get("overlays") if isinstance(doc.get("overlays"), list) else []
    tags = [i for i, ov in enumerate(overlays) if isinstance(ov, dict) and ov.get("template") == LOOK]
    if not tags:
        return {}
    t0 = time.time()
    fps = float(doc.get("fps") or 30)
    fa = float(doc.get("width") or 1920) / float(doc.get("height") or 1080)
    scenes = [s for s in (doc.get("scenes") or []) if isinstance(s, dict)]
    mark = ((doc.get("brand") or {}).get("watermark") or {}) if isinstance(doc.get("brand"), dict) else {}
    barred = {"bottom-left": "left", "bottom-right": "right"}.get(str(mark.get("position") or ""), "")
    # With burned-in captions the tag stands on the caption strip, higher up (LibSourceTag.tsx).
    captions = bool((doc.get("captions") or {}).get("enabled")) if isinstance(doc.get("captions"), dict) else False
    stats: Dict[str, object] = {"tags": len(tags), "moved": 0, "dropped": 0, "unchecked": 0}
    seen: Dict[int, Optional[list]] = {}
    drop = set()
    for i in tags:
        ov = overlays[i]
        a = int(ov.get("startFrame") or 0)
        b = a + int(ov.get("durationInFrames") or 0)
        under = [n for n, s in enumerate(scenes)
                 if int(s.get("startFrame") or 0) < b and a < int(s.get("startFrame") or 0) + int(s.get("durationInFrames") or 0)]
        if any((scenes[n].get("media") or {}).get("type") == "animation" for n in under):
            drop.add(i)                     # the scene became a full-screen graphic (gapfill): nothing lands on it
            continue
        if any(is_presenter_scene(scenes[n]) for n in under):
            drop.add(i)                     # the presenter talking (src/presenter/hybrid.py): nothing lands on it
            continue
        boxes: list = []
        for n in under:
            if n not in seen:
                timed_out = time.time() - t0 > budget
                seen[n] = _faces_on_screen(scenes[n], fa, fps, None if timed_out else look)
            if seen[n] is None:
                stats["unchecked"] = int(stats["unchecked"]) + 1
            else:
                boxes.extend(seen[n])
        side = "right" if str(ov.get("align") or "left") == "right" else "left"
        line = _line_of(ov)
        if not _hits(zone(side, line, captions), boxes):
            continue
        other = "left" if side == "right" else "right"
        if other != barred and not _hits(zone(other, line, captions), boxes):
            ov["align"] = other
            stats["moved"] = int(stats["moved"]) + 1
        else:
            drop.add(i)
    if drop:
        doc["overlays"] = [ov for i, ov in enumerate(overlays) if i not in drop]
        stats["dropped"] = len(drop)
        if isinstance(doc.get("meta"), dict) and "overlayCount" in doc["meta"]:
            doc["meta"]["overlayCount"] = len(doc["overlays"])
    stats["seconds"] = round(time.time() - t0, 1)
    print(f"[sources] {stats['tags']} source tag(s): {stats['moved']} moved off a face, {stats['dropped']} left out"
          + (f", {stats['unchecked']} scene(s) could not be looked at" if stats["unchecked"] else ""), flush=True)
    return stats
