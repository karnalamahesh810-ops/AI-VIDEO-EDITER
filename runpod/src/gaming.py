"""
The gaming video essay's planner (src/styles.py: gaming_essay; 2026-10-15).

The owner's reference, "Why GTA 6 Is Making Driving HARD Again!" (docs/style-refs/gta6_driving/catalogue.md), was
catalogued frame by frame: gameplay under everything, cut every ~2.6 s, and on top of it a fixed vocabulary of
graphics, each tied to what the narration says. This module places that vocabulary - the motion library's gaming pack
(remotion components/smart/library.ts GAMING, drawn by SpecGaming.tsx) - on its trigger words:

  ml-gm-kinetic    the stressed word of a line and its lead-in words, standing in the shot (the reference's main
                   punctuation: every line in the 25 s hook, then every 8-15 s)
  ml-gm-boxed      a short punchline clause after a comma ("The physics didn't change, you had.")
  ml-gm-meter      difficulty talk (hard / easy / skill / challenge / punishing / forgiving)
  ml-gm-curve      getting better over time (learning curve, improving, mastering, the 100th hour)
  ml-gm-zone       a place in the game world named (a drawn dark game map with a glowing district)
  ml-gm-wireframe  mechanics of the thing on screen (physics, weight, suspension, hitbox, handling)
  ml-gm-formulas   understanding / figuring a system out
  ml-gm-thumbs     verdicts (loved / hated, some ... others ...)
  ml-gm-versus     two games or versions compared in one line ("GTA 4 ... GTA 6") - the scene becomes a split
  ml-gm-article    a phrase the press or a developer used ("described ... as too big and boat-like")
  ml-gm-summary    a debate summed up ("fans are still fighting over ...")
  ml-gm-neon       a run of questions put to the viewer
  ml-gm-manual     a system to learn with its parts listed
  ml-gm-board      each chapter (about one a minute, on a turn sentence), numbered
  ml-gm-static     one cut back in time ("years ago", "back in 2008")
  ml-gm-endline    the last line

Every graphic starts on its word (never early; the graphics-timing rule) and leaves about 1-2 s after its last word;
one at a time with a breath between. Pure: no network, no paid call. plan(doc) adds the overlays in place.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

KIT = "gaming"
HOOK_SECONDS = 25.0             # the reference's hook: 0:00-0:25, then the first chapter board
BREATH = 0.35                   # clean picture between two graphics
AFTER = {"ml-gm-kinetic": 0.7, "ml-gm-boxed": 1.2, "ml-gm-thumbs": 1.0, "ml-gm-neon": 0.5}   # after the last word (else 1.6)
MAX_LEN = {"ml-gm-kinetic": 3.2, "ml-gm-boxed": 3.0, "ml-gm-board": 3.2, "ml-gm-static": 0.6, "ml-gm-thumbs": 4.0,
           "ml-gm-endline": 4.0, "ml-gm-neon": 4.5, "ml-gm-manual": 6.0, "ml-gm-summary": 7.0}
MIN_LEN = 1.2
# Per look: fewest seconds between two of them, and the most in one video (measured on the reference, 5:50).
EVERY = {"ml-gm-kinetic": 7.0, "ml-gm-boxed": 45.0, "ml-gm-meter": 50.0, "ml-gm-curve": 60.0, "ml-gm-zone": 50.0,
         "ml-gm-wireframe": 40.0, "ml-gm-formulas": 60.0, "ml-gm-thumbs": 30.0, "ml-gm-versus": 35.0,
         "ml-gm-article": 70.0, "ml-gm-summary": 120.0, "ml-gm-neon": 0.0, "ml-gm-manual": 90.0, "ml-gm-board": 45.0,
         "ml-gm-static": 1e9, "ml-gm-endline": 1e9}
CAP = {"ml-gm-meter": 3, "ml-gm-curve": 2, "ml-gm-wireframe": 3, "ml-gm-formulas": 2, "ml-gm-thumbs": 3,
       "ml-gm-article": 2, "ml-gm-summary": 1, "ml-gm-neon": 4, "ml-gm-manual": 1, "ml-gm-board": 8,
       "ml-gm-static": 1, "ml-gm-endline": 1, "ml-gm-boxed": 3, "ml-gm-zone": 3, "ml-gm-versus": 4}
# Which wins when two want the same moment.
# Pairs the reference shows together (different parts of the frame): boxed words beside the wireframe ("you had" +
# PHYSICS at 1:28), kinetic words over the floating formulas.
TOGETHER = {frozenset(("ml-gm-boxed", "ml-gm-wireframe")), frozenset(("ml-gm-kinetic", "ml-gm-formulas")),
            frozenset(("ml-gm-neon",))}          # a run of questions: each box hands over to the next
# The static cut is a 0.6 s transition over the cut into the past: it may cross a word look's tail.
OVER_WORDS = {"ml-gm-static"}
WORD_LOOKS = {"ml-gm-kinetic", "ml-gm-boxed", "ml-gm-thumbs"}
# A difficulty word counts for the meter when it describes something ("made driving hard", "a skill again"), not
# "how hard you could turn".
_METER_CUE = re.compile(r"\b(made|make|makes|making|was|is|be|been|feel|feels|felt|became|become|becomes|got|gets|too|"
                        r"more|less|so|a|stay|stays|keep|kept)\s+(?:\w+\s+){0,2}$", re.I)
PRIORITY = ["ml-gm-board", "ml-gm-endline", "ml-gm-versus", "ml-gm-neon", "ml-gm-meter", "ml-gm-wireframe",
            "ml-gm-zone", "ml-gm-thumbs", "ml-gm-curve", "ml-gm-summary", "ml-gm-manual", "ml-gm-article",
            "ml-gm-boxed", "ml-gm-formulas", "ml-gm-static", "ml-gm-kinetic"]

STOP = set(("a an the to of and or but in on at by for with from that this these those it its is was were be been are "
            "as so if than then you your we our they their he his she her i my me just still even not no do does did "
            "can could would should will have has had there here what which who when where why how very really "
            "much more most some any all one also into over about up out off only because while").split())
_NOT_NAME = STOP | {"before", "after", "since", "during", "without", "unlike", "where", "while", "if"}
_HARD = re.compile(r"\b(hard(?:er|est)?|difficult(?:y)?|challeng\w*|punish\w*|brutal|unforgiving|skill)\b", re.I)
_EASY = re.compile(r"\b(eas(?:y|ier|iest)|forgiving|accessib\w*|casual)\b", re.I)
_CURVE = re.compile(r"\b(learning curve|get(?:ting)? better|got better|improv\w+|master(?:ing|ed|y)?|practi[cs]e\w*|"
                    r"(?:100|hundred)(?:th)? hours?|first hour)\b", re.I)
_WIRE = re.compile(r"\b(physics|weight|suspension|hitbox(?:es)?|collision|handling|momentum|grip|body roll|traction|"
                   r"frame data|i-frames|hit ?boxes)\b", re.I)
_THINK = re.compile(r"\b(understood|understand(?:ing)?|figur(?:e|ed|ing) out|calculat\w+|the math|maths?|system)\b", re.I)
_UP = re.compile(r"\b(lov(?:e|ed|es)|liked|prais\w+|defend\w*|worked)\b", re.I)
_DOWN = re.compile(r"\b(hat(?:e|ed|es)|disliked|frustrat\w+|annoy\w+|complain\w*|criticis\w+|criticiz\w+|failed|broken)\b", re.I)
_DEBATE = re.compile(r"\b(fans|players|people|gamers|critics)\b[^.?!]{0,30}\b(still )?(fighting|arguing|divided|split|debating)\b", re.I)
_QUOTE = re.compile(r"\b(?:described\b[^.?!]{0,40}?\bas|called (?:it|them)|calling (?:it|them)|labell?ed (?:it|them)(?: as)?)\s+"
                    r"([^.,;!?]{3,40})", re.I)
_BACK = re.compile(r"\b(years ago|back in (?:19|20)\d\d|back then|a decade ago|two decades)\b", re.I)
_SYSTEM = re.compile(r"\b(rules|the system|basics|manual|guide|tutorial|how (?:the|it) (?:system )?work\w*)\b", re.I)
_TURN = re.compile(r"^(but|so|and now|now|instead|because|here's|that's why|which is why|in other words)\b", re.I)
_GAME = re.compile(r"\b((?:[A-Z][A-Za-z']+|[A-Z]{2,5})(?:\s(?:[A-Z][A-Za-z']+|[A-Z]{2,5})){0,2})\s(\d{1,2}|[IVX]{1,4})\b")
# Two named games without numbers, compared in one line ("Where Elden Ring let you walk away, Shadow of the Erdtree ...").
_TITLE = re.compile(r"\b([A-Z][A-Za-z']+(?:\s(?:of the|of|the)?\s?[A-Z][A-Za-z']+)+)")
_CUE = re.compile(r"\b(vs\.?|versus|than|compared|unlike|where|while|but)\b", re.I)
_ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII", 9: "IX", 10: "X"}


class Word:
    __slots__ = ("text", "t0", "t1", "bare")

    def __init__(self, text: str, t0: float, t1: float):
        self.text, self.t0, self.t1 = text, t0, max(t0, t1)
        self.bare = re.sub(r"[^a-z0-9']", "", text.lower())


def words_of(doc: dict) -> List[Word]:
    out: List[Word] = []
    for s in doc.get("scenes") or []:
        for w in (s or {}).get("words") or []:
            if not isinstance(w, dict):
                continue
            tok = str(w.get("text") or w.get("word") or "").strip()
            try:
                a, b = float(w.get("start")), float(w.get("end", w.get("start")))
            except (TypeError, ValueError):
                continue
            if tok:
                out.append(Word(tok, a, b))
    out.sort(key=lambda w: w.t0)
    return out


def sentences(words: List[Word]) -> List[List[Word]]:
    out, cur = [], []
    for w in words:
        cur.append(w)
        if re.search(r"[.?!][\"')\]]*$", w.text):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _text(ws: List[Word]) -> str:
    return " ".join(w.text for w in ws)


def _find(sent: List[Word], rx: "re.Pattern") -> Optional[Tuple[int, int]]:
    """(first, last) word index of the regex's first match inside a sentence."""
    text = ""
    starts = []
    for w in sent:
        starts.append(len(text))
        text += w.text + " "
    m = rx.search(text)
    if not m:
        return None
    a = max(i for i, s in enumerate(starts) if s <= m.start())
    b = max(i for i, s in enumerate(starts) if s < m.end())
    return a, b


_PLAIN_VERBS = set(("make makes made making give gives gave giving get gets got getting go goes went going take takes took "
                    "taking spend spent spends spending look looks looked looking want wants wanted say says said keep "
                    "kept come came put seem seems seemed feel feels felt know knew think thought").split())


def stress_index(sent: List[Word]) -> Optional[int]:
    """The word a reader would stress: a content word, late in its clause, longer, not a name at the line's start."""
    best, best_i = -1.0, None
    for i, w in enumerate(sent):
        if w.bare in STOP or len(w.bare) < 4 or w.bare.isdigit() and len(w.bare) < 2 or re.search(r"n't$|'s$|'re$|'ll$", w.bare):
            continue
        score = min(len(w.bare), 9) * 0.3
        if re.search(r"[,.?!;:]$", w.text):
            score += 2.0                    # the end of a clause carries the stress
        if i == 0 and w.text[:1].isupper():
            score -= 1.5
        if _HARD.search(w.text) or _EASY.search(w.text) or re.match(r"^(learn\w*|skill|never|always|everything|gone)", w.bare):
            score += 1.5
        if w.bare in _PLAIN_VERBS:
            score -= 2.0                    # "making", "gave": the stress is on what they act on
        score += i / max(1, len(sent)) * 0.8
        if score > best:
            best, best_i = score, i
    return best_i


def _lead(sent: List[Word], i: int) -> int:
    """Where the kinetic phrase starts: up to two small words before the stressed one."""
    j = i
    while j > 0 and i - j < 2 and sent[j - 1].bare in STOP and not re.search(r"[,.?!;:]$", sent[j - 1].text):
        j -= 1
    return j


def _strip(s: str) -> str:
    return s.strip(" ,.;:!?\"'")


def _short_title(name: str, num: str, other: Tuple[str, str]) -> str:
    """What the versus split shows for a game: the numeral alone when both sides share the series name."""
    if name.lower() == other[0].lower():
        n = int(num) if num.isdigit() else None
        return _ROMAN.get(n, num) if n is not None else num
    t = f"{name} {num}".strip()
    if len(t) <= 12:
        return t.upper() if not num else t
    return num if num else [w for w in name.split() if w[:1].isupper()][-1].upper()


# --------------------------------------------------------------------------- candidates
def candidates(words: List[Word], total: float) -> List[dict]:
    sents = sentences(words)
    out: List[dict] = []

    def add(look: str, ws: List[Word], start: float, last: float, **props):
        out.append({"look": look, "t0": start, "t_last": last, "words": ws, **props})

    q_run: List[List[Word]] = []
    # The first chapter ends the hook (the reference: 0:25) - on a turn sentence when one comes soon after it, else
    # on the first sentence after the hook; the later chapters open on turn sentences.
    first_board = any(HOOK_SECONDS - 1 <= x[0].t0 < HOOK_SECONDS + 25 and _TURN.match(_text(x)) for x in sents if x)
    for si, s in enumerate(sents):
        if not s:
            continue
        txt = _text(s)
        t0 = s[0].t0
        # chapter boards: a turn sentence after the hook, about a minute apart (spacing does the rest)
        if HOOK_SECONDS - 1 <= t0 < total - 20 and len(s) >= 5 and (_TURN.match(txt) or not first_board):
            first_board = True
            title = chapter_title(txt)
            if title:
                add("ml-gm-board", s[:1], t0, t0, text=title)
        # versus: two numbered games in one line
        games = []
        for m in _GAME.finditer(txt):
            name, start = m.group(1), m.start()
            while len(name.split()) > 1 and name.split()[0].lower() in _NOT_NAME:
                first = name.split()[0]
                name, start = name[len(first):].strip(), start + len(first) + 1
            if name.lower() not in _NOT_NAME:
                games.append((name, m.group(2), start))
        uniq = []
        for g in games:
            if all((g[0].lower(), g[1]) != (u[0].lower(), u[1]) for u in uniq):
                uniq.append(g)
        if len(uniq) < 2 and _CUE.search(txt):
            names = []
            for m in _TITLE.finditer(txt):
                name, start = m.group(1), m.start()
                while name.split() and name.split()[0].lower() in _NOT_NAME:
                    first = name.split()[0]
                    name, start = name[len(first):].strip(), start + len(first) + 1
                if len(name.split()) >= 2:
                    names.append((name, "", start))
            if len(names) >= 2 and names[0][0].lower() != names[1][0].lower():
                uniq = names[:2]
        if len(uniq) >= 2:
            (n1, d1, c1), (n2, d2, c2) = uniq[:2]
            i1 = _word_at_char(s, c1)
            i2 = _word_at_char(s, c2)
            add("ml-gm-versus", s, s[i1].t0, s[i2].t1, kicker=_short_title(n1, d1, (n2, d2)),
                sub=_short_title(n2, d2, (n1, d1)), item_at=[s[i1].t0, s[i2].t0])
        # difficulty meter
        hit = _find(s, _HARD) or _find(s, _EASY)
        if hit and not _METER_CUE.search(" ".join(w.text for w in s[max(0, hit[0] - 3):hit[0]]) + " "):
            hit = None
        if hit:
            a, b = hit
            lo, hi = max(0, a - 2), min(len(s), b + 2)
            for k in range(a - 1, lo - 1, -1):          # the caption is one clause: "made driving HARD"
                if re.search(r"[,.;:?!]$", s[k].text):
                    lo = k + 1
                    break
            for k in range(b, hi):
                if re.search(r"[,.;:?!]$", s[k].text):
                    hi = k + 1
                    break
            cap = s[lo:hi]
            value = 88.0 if _find(s, _HARD) else 22.0
            add("ml-gm-meter", cap, cap[0].t0, cap[-1].t1, value=value,
                caption=cap, start_word=cap[0])
        hit = _find(s, _CURVE)
        if hit:
            a, b = hit
            near = txt + " " + (_text(sents[si - 1]) if si else "")
            label = "Learning curve" if re.search(r"\blearn", near, re.I) else _strip(_text(s[a:b + 1]))
            add("ml-gm-curve", s[a:b + 1], s[a].t0, s[b].t1, text=label)
        hit = _find(s, _WIRE)
        if hit:
            a, b = hit
            add("ml-gm-wireframe", s[a:b + 1], s[a].t0, s[b].t1, text=_strip(_text(s[a:b + 1])).upper())
        hit = _find(s, _THINK)
        if hit:
            a, b = hit
            add("ml-gm-formulas", s[a:b + 1], s[a].t0, s[b].t1, text=_strip(_text(s[a:b + 1])))
        # verdicts: this sentence (and the next, for "some ... others ...")
        up, down = _find(s, _UP), _find(s, _DOWN)
        nxt = sents[si + 1] if si + 1 < len(sents) else []
        if up or down:
            first = sorted([x for x in ((up, "up"), (down, "down")) if x[0]], key=lambda x: x[0][0])
            items = [(s[f[0][0]], f[1]) for f in first]
            if len(items) == 1 and nxt and re.match(r"^(but )?others?\b", _text(nxt), re.I):
                other = _find(nxt, _DOWN if items[0][1] == "up" else _UP) or (0, 0)
                items.append((nxt[other[0]] if other != (0, 0) else nxt[0], "down" if items[0][1] == "up" else "up"))
            add("ml-gm-thumbs", [w for w, _ in items], items[0][0].t0, items[-1][0].t1,
                verdicts=[v for _, v in items], item_at=[w.t0 for w, _ in items])
        m = _QUOTE.search(txt)
        if m:
            phrase = _strip(m.group(1))
            pw = phrase.split()
            idx = _word_at_char(s, m.start(1))
            ws = s[idx:idx + len(pw)]
            if ws:
                before = _text(s[max(0, idx - 3):idx])
                add("ml-gm-article", ws, ws[0].t0, ws[-1].t1, text=_strip(_text(ws)), kicker=before)
        if _DEBATE.search(txt) and nxt:
            bullets = [_strip(_text(x)) for x in sents[si + 1:si + 3] if x][:2]
            add("ml-gm-summary", s, t0, (sents[min(si + 2, len(sents) - 1)] or s)[-1].t1, text=_strip(txt), items=bullets)
        hit = _find(s, _BACK)
        if hit:
            add("ml-gm-static", s[hit[0]:hit[0] + 1], max(0.0, s[hit[0]].t0 - 0.3), s[hit[0]].t0)
        # a short punchline clause after a comma: "..., you had."
        parts = re.split(r"(?<=,)\s", txt)
        if len(parts) >= 2 and len(s) <= 10:
            tail = parts[-1].split()
            if 1 < len(tail) <= 3:
                ws = s[-len(tail):]
                add("ml-gm-boxed", ws, ws[0].t0, ws[-1].t1, text=_strip(_text(ws)))
        # a system to learn, with its parts listed in this line or the next
        if _SYSTEM.search(txt):
            for cand in (s, nxt):
                items = [p for p in re.split(r",\s*(?:and\s+)?|\s+and\s+", _strip(_text(cand))) if 0 < len(p.split()) <= 3]
                if len(items) >= 3:
                    add("ml-gm-manual", cand, cand[0].t0, cand[-1].t1, text="The guide", items=items[:4])
                    break
        # questions to the viewer: a run of two or more
        if txt.rstrip().endswith("?") and 4 <= len(s) <= 16:
            q_run.append(s)
        else:
            if len(q_run) >= 2:
                for q in q_run:
                    words_q = _text(q)
                    add("ml-gm-neon", q, q[0].t0, q[-1].t1, text=words_q)
            q_run = []
        # the stressed word of the line - of every clause in the hook (the reference: a word every 2-3 s there)
        clauses = [s]
        if t0 < HOOK_SECONDS:
            clauses, cur = [], []
            for w in s:
                cur.append(w)
                if re.search(r"[,;:]$", w.text) and len(cur) >= 3:
                    clauses.append(cur)
                    cur = []
            if cur:
                clauses.append(cur)
        for cl in clauses:
            i = stress_index(cl)
            if i is not None:
                j = _lead(cl, i)
                add("ml-gm-kinetic", cl[j:i + 1], cl[j].t0, cl[i].t1, text=_text(cl[j:i + 1]))
    if len(q_run) >= 2:
        for q in q_run:
            add("ml-gm-neon", q, q[0].t0, q[-1].t1, text=_text(q))
    if len(sents) >= 3 and len(sents[-1]) >= 3:
        last = sents[-1]
        k = min(2, len(last) - 1)
        add("ml-gm-endline", last, last[0].t0, last[-1].t1, text=_strip(_text(last[-k:])), sub=_strip(_text(last[:-k])))
    # zones: a capitalised place after "in / of / through / across / around" (not a game title: no number after it)
    for si, s in enumerate(sents):
        for k in range(1, len(s) - 1):
            if s[k].bare in ("in", "of", "through", "across", "around") and s[k + 1].text[:1].isupper():
                end = k + 1
                while end + 1 < len(s) and s[end + 1].text[:1].isupper() and end - k < 3:
                    end += 1
                name = _strip(_text(s[k + 1:end + 1]))
                if name and not re.search(r"\d|\b[IVX]{1,4}\b", name) and name.split()[0].lower() not in STOP | {"gta"} \
                        and not (end + 1 < len(s) and re.match(r"^(\d{1,2}|[IVX]{1,4})\W*$", s[end + 1].text)):
                    add("ml-gm-zone", s[k + 1:end + 1], s[k + 1].t0, s[end].t1, text=name)
    return out


def chapter_title(sentence: str) -> str:
    """A board's title from its turn sentence: the first clause without the turn word, at most seven words."""
    t = _TURN.sub("", sentence.strip()).strip(" ,")
    t = re.split(r"[,;:.?!]", t)[0].split()
    ends = STOP - {"it", "them", "you", "him", "her", "us"}
    t = t[:7]
    while t and t[-1].lower() in ends:
        t = t[:-1]
    if len(t) < 3:
        return ""
    out = " ".join(t)
    return out[:1].upper() + out[1:]


def _word_at_char(sent: List[Word], char: int) -> int:
    pos = 0
    for i, w in enumerate(sent):
        if pos + len(w.text) >= char:
            return i
        pos += len(w.text) + 1
    return len(sent) - 1


# --------------------------------------------------------------------------- choosing
def choose(cands: List[dict], total: float) -> List[dict]:
    """One at a time, the look's own spacing and cap, the stronger look on a shared moment, dense in the hook."""
    rank = {k: i for i, k in enumerate(PRIORITY)}
    cands = sorted(cands, key=lambda c: (rank.get(c["look"], 99), c["t0"]))
    taken: List[dict] = []
    last_of: Dict[str, List[float]] = {}
    for c in cands:
        look = c["look"]
        after = AFTER.get(look, 1.6)
        t0 = c["t0"]
        t1 = min(total, max(t0 + MIN_LEN, c["t_last"] + after), t0 + MAX_LEN.get(look, 6.5))
        if look == "ml-gm-board":
            t1 = min(total, t0 + 3.2)
        if t1 - t0 < 0.5:
            continue
        if len(last_of.get(look, [])) >= CAP.get(look, 99):
            continue
        gap = EVERY.get(look, 30.0)
        if look == "ml-gm-kinetic" and t0 < HOOK_SECONDS:
            gap = 2.2
        if any(abs(t0 - x) < gap for x in last_of.get(look, [])):
            continue
        if look == "ml-gm-board" and t0 < HOOK_SECONDS - 1:
            continue
        if any(not (t1 + BREATH <= o["t0"] or t0 >= o["t1"] + BREATH) and frozenset((look, o["look"])) not in TOGETHER
               and not ({look, o["look"]} & OVER_WORDS and {look, o["look"]} & WORD_LOOKS)
               for o in taken):
            continue
        c = dict(c, t1=t1)
        taken.append(c)
        last_of.setdefault(look, []).append(t0)
    taken.sort(key=lambda c: c["t0"])
    for a, b in zip(taken, taken[1:]):
        if a["look"] == b["look"] == "ml-gm-neon":
            a["t1"] = min(a["t1"], b["t0"])
    n = 0
    for c in taken:
        if c["look"] == "ml-gm-board":
            n += 1
            c["number"] = n
    return taken


# --------------------------------------------------------------------------- overlays
def overlay_for(c: dict, fps: int, chapters: List[str]) -> dict:
    look = c["look"]
    sf = int(round(c["t0"] * fps))
    dur = max(int(round((c["t1"] - c["t0"]) * fps)), int(MIN_LEN * fps) if look != "ml-gm-static" else int(0.6 * fps))
    rel = lambda t: round(max(0.0, t - c["t0"]), 3)  # noqa: E731
    ov = {"type": "motion", "variant": look, "template": "ML_" + look[3:].upper().replace("-", "_"),
          "startFrame": sf, "durationInFrames": dur, "kit": KIT, "gaming": True, "seed": sf}
    ws: List[Word] = c.get("words") or []
    if look in ("ml-gm-kinetic", "ml-gm-boxed"):
        ov["text"] = c["text"]
        ov["wordAt"] = [rel(w.t0) for w in ws]
    elif look == "ml-gm-meter":
        cap = c.get("caption") or ws
        words = [w.text.strip(",.;:") for w in cap]
        # the difficulty word in capitals (the reference: "driving a SKILL again")
        words = [w.upper() if (_HARD.search(w) or _EASY.search(w)) else w for w in words]
        ov.update(text=" ".join(words), value=c.get("value", 88.0), wordAt=[rel(w.t0) for w in cap])
    elif look == "ml-gm-versus":
        ov.update(text=f"{c['kicker']} vs {c['sub']}", label=c["kicker"], subtitle=c["sub"], itemAt=[rel(t) for t in c["item_at"]])
    elif look == "ml-gm-thumbs":
        ov.update(text=" ".join(w.text for w in ws), items=[{"label": v} for v in c["verdicts"]], itemAt=[rel(t) for t in c["item_at"]])
    elif look == "ml-gm-board":
        num = c.get("number", 1)
        ov.update(text=c["text"], label=str(num), items=[{"label": t} for t in chapters if t != c["text"]][:2])
    elif look == "ml-gm-zone":
        ov.update(text=c["text"], label="map")
    elif look == "ml-gm-article":
        ov.update(text=c["text"], label=c.get("kicker", ""))
    elif look == "ml-gm-summary":
        ov.update(text=c["text"], items=[{"label": b} for b in c.get("items") or []])
    elif look == "ml-gm-manual":
        ov.update(text=c["text"], items=[{"label": b} for b in c.get("items") or []])
    elif look == "ml-gm-endline":
        ov.update(text=c["text"], subtitle=c.get("sub", ""))
    elif look == "ml-gm-static":
        ov.update(text="")
    else:
        ov["text"] = c.get("text") or " ".join(w.text for w in ws)
    return ov


def _shows_map(doc: dict, frame: int) -> Optional[int]:
    """The end frame of the scene under `frame` when that shot is a map (its vision description says so), else None."""
    for s in doc.get("scenes") or []:
        a = int(s.get("startFrame") or 0)
        if a <= frame < a + int(s.get("durationInFrames") or 0):
            m = s.get("media") or {}
            desc = str(m.get("contentDescription") or (s.get("semanticMetadata") or {}).get("contentDescription") or "")
            return a + int(s.get("durationInFrames") or 0) if re.search(r"\bmaps?\b", desc, re.I) else None
    return None


def split_for_versus(doc: dict, ov: dict, fps: int) -> bool:
    """The reference compares two games side by side: the versus scene shows its neighbour's clip as the right half."""
    scenes = doc.get("scenes") or []
    t = ov["startFrame"]
    for i, s in enumerate(scenes):
        a = int(s.get("startFrame") or 0)
        if a <= t < a + int(s.get("durationInFrames") or 0):
            m = s.get("media") or {}
            other = None
            for j in (i + 1, i - 1, i + 2):
                if 0 <= j < len(scenes):
                    om = (scenes[j] or {}).get("media") or {}
                    if om.get("type") == "video" and om.get("url") and om.get("url") != m.get("url"):
                        other = om
                        break
            if m.get("type") != "video" or not other:
                return False
            s["frame"] = "split"
            m["split"] = {"type": "video", "url": other["url"]}
            s["media"] = m
            return True
    return False


def plan(doc: dict, *, replace: bool = True) -> dict:
    """Adds the gaming pack's overlays to a timeline document (in place). Returns a small report."""
    fps = int(doc.get("fps") or 30)
    words = words_of(doc)
    if not words:
        return {"added": 0, "why": "no timed words"}
    total = max(w.t1 for w in words)
    chosen = choose(candidates(words, total), total)
    chapters = [c["text"] for c in chosen if c["look"] == "ml-gm-board"]
    ovs = [overlay_for(c, fps, chapters) for c in chosen]
    # the planner's word-only looks give way to the pack (facts, maps and pictures stay where they do not clash)
    kept = []
    before = len(doc.get("overlays") or [])
    for o in doc.get("overlays") or []:
        a, b = int(o.get("startFrame") or 0), int(o.get("startFrame") or 0) + int(o.get("durationInFrames") or 0)
        clash = any(not (b <= x["startFrame"] or a >= x["startFrame"] + x["durationInFrames"]) for x in ovs)
        if not (replace and clash):
            kept.append(o)
    splits = sum(1 for o in ovs if o["variant"] == "ml-gm-versus" and split_for_versus(doc, o, fps))
    for o in ovs:
        end = _shows_map(doc, o["startFrame"]) if o["variant"] == "ml-gm-zone" else None
        if end is not None:
            o["label"] = ""                 # the shot is the game's own map: outline it there, do not draw one
            o["durationInFrames"] = max(int(fps), min(o["durationInFrames"], end - o["startFrame"]))
    doc["overlays"] = sorted(kept + ovs, key=lambda o: int(o.get("startFrame") or 0))
    by: Dict[str, int] = {}
    for o in ovs:
        by[o["variant"]] = by.get(o["variant"], 0) + 1
    return {"added": len(ovs), "byLook": by, "splits": splits, "replaced": before - len(kept)}
