"""
Language versions (the owner, 2026-10-09): "Make a version in another language" of a finished video, for a
creator's second channel in Spanish, Portuguese, German and the rest - cheap because nothing is searched again.

The finished timeline is the plan. Its narration is translated fragment by fragment (one fragment = what is said
while one shot is on screen), voiced by our own voice server (Qwen3-TTS, RunPod endpoint noxv85ue2spsrl) in the
same voice - one of our own voices when the video was made with one, else a clone of the narrator taken from a
clean stretch of the narration itself - and the timeline is re-timed to the new voice:

  * every scene keeps its shot, look, transition and grade; its cut moves to where its own words now start, so
    each scene is stretched or trimmed to its line's new length (_scene_starts);
  * the looks follow the same warp, and a look that shows a number or a name lands on that number or name as it
    is said in the new language (_reanchor);
  * the sound effects, the music sections and the ambience beds follow the warp;
  * the captions are the new words (whisper on the new narration, aligned to the translated text), and the looks'
    on-screen text is translated (translate_screen_text) with the narration's own wording beside it.

Names, numbers and places: one glossary for the whole video fixes how every name is written (make_glossary);
every number of a fragment must come back with the same value (numbers_match) - a fragment that loses one is
asked again, and what still disagrees is reported in meta.languageVersion.numberIssues, never silently changed.

Pure functions up to `prepare`; the handler (do_translate_version) saves and renders. The source project is never
written: the job writes only the new project's row (inp.project_id), and refuses one equal to the source.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
import os
import re
import subprocess
import threading
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import requests

from . import config, costs, events

# --------------------------------------------------------------------------- #
# Languages
# --------------------------------------------------------------------------- #

# What our voice server speaks (tts/handler.py QWEN_LANGS): code -> (English name, its own name).
LANGUAGES: Dict[str, Tuple[str, str]] = {
    "en": ("English", "English"), "es": ("Spanish", "Español"), "pt": ("Portuguese", "Português"),
    "fr": ("French", "Français"), "de": ("German", "Deutsch"), "it": ("Italian", "Italiano"),
    "ru": ("Russian", "Русский"), "zh": ("Chinese", "中文"), "ja": ("Japanese", "日本語"),
    "ko": ("Korean", "한국어"),
}
# Written without spaces between words: a caption token is a character run, a voice part one sentence a line.
UNSPACED = {"zh", "ja"}
# The voice server's length check counts [A-Za-z0-9'] words (tts/textnorm.expected_seconds): in these scripts it
# sees almost none, calls every take "too long" and keeps the SHORTEST of its retries - one take only here.
ONE_TAKE = {"ru", "zh", "ja", "ko"}


class LanguageError(ValueError):
    """A language version that cannot be made. The message is written for the owner."""


def language(code: Any) -> str:
    """The language code, checked against what our voice server speaks."""
    c = str(code or "").strip().lower()[:5]
    if c not in LANGUAGES:
        names = ", ".join(f"{v[0]} ({k})" for k, v in LANGUAGES.items())
        raise LanguageError(f"Our voice speaks {names}; '{code}' is not one of them.")
    return c


def strip_language_suffix(title: Any) -> str:
    """A version's title without its " (Español)" (the app names a version "<title> (<its own name>)")."""
    t = str(title or "").strip()
    for _en, own in LANGUAGES.values():
        for name in {own, _en}:
            if t.endswith(f" ({name})"):
                return t[: -len(name) - 3].rstrip()
    return t


def source_language(doc: dict) -> str:
    """The language a timeline is in: a version's own, else English (every narration until now)."""
    lv = ((doc or {}).get("meta") or {}).get("languageVersion") if isinstance((doc or {}).get("meta"), dict) else None
    code = str((lv or {}).get("language") or "en").lower() if isinstance(lv, dict) else "en"
    return code if code in LANGUAGES else "en"


# --------------------------------------------------------------------------- #
# Fragments: one per scene, grouped into sentences
# --------------------------------------------------------------------------- #

_SENTENCE_END = re.compile(r"[.!?…。！？][\"'”’)\]」』]*$")
_DIGITS = re.compile(r"\d")


@dataclass
class Fragment:
    """What is said while one scene is on screen, before and after translation."""
    scene: int
    text: str
    words: List[dict]
    group: int = -1
    out: str = ""                       # the translation as shown (scene text, captions)
    say: str = ""                       # the translation as read aloud (numbers in words)
    new_words: List[dict] = field(default_factory=list)

    @property
    def spoken(self) -> bool:
        return bool(self.text.strip())

    @property
    def start(self) -> Optional[float]:
        return float(self.words[0]["start"]) if self.words else None

    @property
    def end(self) -> Optional[float]:
        return float(self.words[-1]["end"]) if self.words else None

    @property
    def new_start(self) -> Optional[float]:
        return float(self.new_words[0]["start"]) if self.new_words else None

    @property
    def new_end(self) -> Optional[float]:
        return float(self.new_words[-1]["end"]) if self.new_words else None


def _clean_words(words: Any) -> List[dict]:
    out = []
    for w in words if isinstance(words, list) else []:
        if not isinstance(w, dict):
            continue
        t = str(w.get("text") or "").strip()
        try:
            a, b = float(w.get("start")), float(w.get("end"))
        except (TypeError, ValueError):
            continue
        if t and math.isfinite(a) and math.isfinite(b):
            out.append({"text": t, "start": a, "end": max(a, b)})
    return out


def _tidy(text: str) -> str:
    """A transcript's spacing tidied: "1 ,040" -> "1,040", "15 -story" -> "15-story", no space before a mark."""
    t = re.sub(r"(\d)\s+([,.]\d)", r"\1\2", str(text or ""))
    t = re.sub(r"(\d)\s+-(?=\w)", r"\1-", t)
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def fragments_of(doc: dict) -> List[Fragment]:
    """Every scene's fragment, in order (a scene with no words and no text is a silent one)."""
    out = []
    for i, sc in enumerate(doc.get("scenes") or []):
        if not isinstance(sc, dict):
            continue
        words = _clean_words(sc.get("words"))
        text = str(sc.get("text") or "").strip() or " ".join(w["text"] for w in words)
        if not words:
            text = ""                   # a teaser flash or a silent scene: nothing of it is said
        out.append(Fragment(scene=i, text=_tidy(text), words=words))
    return out


def ends_sentence(text: str) -> bool:
    return bool(_SENTENCE_END.search((text or "").strip()))


def group_fragments(frags: Sequence[Fragment], max_frags: int = 10, max_chars: int = 700) -> List[List[int]]:
    """
    The spoken fragments in runs that end where a sentence ends (a scene often ends inside a sentence and the
    next one finishes it): translated together, so every sentence reads naturally in the new language while each
    shot keeps its own words. A run that never ends a sentence is closed at `max_frags` / `max_chars`.
    """
    groups: List[List[int]] = []
    cur: List[int] = []
    size = 0
    for k, f in enumerate(frags):
        if not f.spoken:
            continue
        cur.append(k)
        size += len(f.text)
        if ends_sentence(f.text) or len(cur) >= max_frags or size >= max_chars:
            groups.append(cur)
            cur, size = [], 0
    if cur:
        groups.append(cur)
    for g, members in enumerate(groups):
        for k in members:
            frags[k].group = g
    return groups


# --------------------------------------------------------------------------- #
# Numbers: what must come back unchanged
# --------------------------------------------------------------------------- #

_NUMBER = re.compile(r"\d+(?:[.,   ]\d+)*")


def _canonical(token: str) -> Optional[str]:
    """A number's value as plain text ("1,040" / "1.040" / "1 040" -> "1040"; "3,5" / "3.5" -> "3.5")."""
    t = token.replace(" ", " ").replace(" ", " ")
    parts = re.split(r"[., ]", t)
    if not parts or not all(p.isdigit() for p in parts):
        return None
    if len(parts) == 1:
        return str(int(parts[0])) if len(parts[0]) < 16 else parts[0]
    if all(len(p) == 3 for p in parts[1:]) and len(parts[0]) <= 3:
        return str(int("".join(parts)))                     # thousands groups
    if len(parts) == 2 and " " not in t:
        whole, frac = parts
        frac = frac.rstrip("0")
        return f"{int(whole)}.{frac}" if frac else str(int(whole))
    return "".join(parts)


def numbers_in(text: str) -> List[str]:
    """The numbers a text states, as values, in order (spacing artefacts of a transcript tidied first)."""
    out = []
    for m in _NUMBER.finditer(_tidy(text)):
        token = m.group(0).strip(" ")
        # "2022, that" is a year and a comma, not 2022.that: a separator must be followed by digits only.
        value = _canonical(token)
        if value is None:
            for piece in re.split(r"[ ]", token):
                v = _canonical(piece)
                if v is not None:
                    out.append(v)
        else:
            out.append(value)
    return out


def numbers_match(source: str, translated: str) -> List[str]:
    """The source's numbers missing from the translation (every value once per time it is stated)."""
    have = numbers_in(translated)
    missing = []
    for v in numbers_in(source):
        if v in have:
            have.remove(v)
        else:
            missing.append(v)
    return missing


# --------------------------------------------------------------------------- #
# The model: one small OpenRouter client (JSON answers, priced by OpenRouter's own usage)
# --------------------------------------------------------------------------- #

def _openrouter_key() -> str:
    for base, key in ((config.OPENROUTER_API_BASE, os.getenv("OPENROUTER_API_KEY", "")),
                      (config.DIRECTOR_API_BASE, config.DIRECTOR_API_KEY),
                      (config.VISION_API_BASE, config.VISION_API_KEY)):
        if key and "openrouter.ai" in (base or ""):
            return key
    return ""


def _reasoning(model: str) -> dict:
    m = model.lower()
    if "gemini-2.5" in m:
        return {"max_tokens": 0}                 # thinking off: a translation needs none
    if "gemini" in m or "/gpt-5" in m:
        return {"effort": "minimal"}
    return {}


def _note_usage(body: Any, kind: str) -> float:
    usage = body.get("usage") if isinstance(body, dict) else None
    if not isinstance(usage, dict):
        return 0.0
    try:
        usd = float(usage.get("cost") or 0.0)
    except (TypeError, ValueError):
        usd = 0.0
    if usd > 0:
        costs.record("llm.usd", usd)
        costs.record(f"llm.{kind}.usd", usd)
    costs.record(f"llm.{kind}.calls")
    for k, n in (("llm.prompt_tokens", usage.get("prompt_tokens")),
                 ("llm.completion_tokens", usage.get("completion_tokens"))):
        try:
            if int(n or 0):
                costs.record(k, int(n))
        except (TypeError, ValueError):
            pass
    return usd


def _json_of(content: Any) -> Any:
    if isinstance(content, list):
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    return json.loads(text)


# What the model calls of this job cost (USD), for the result and a budget check.
SPENT = {"usd": 0.0, "calls": 0}
_SPENT_LOCK = threading.Lock()


def models() -> List[str]:
    out = []
    for m in [config.LANG_TRANSLATE_MODEL] + list(config.LANG_TRANSLATE_FALLBACK_MODELS):
        if m and m not in out:
            out.append(m)
    return out


def chat_json(system: str, payload: dict, kind: str = "translate", timeout: float = 150.0,
              post: Optional[Callable] = None) -> Optional[dict]:
    """
    One JSON answer from the translation models in order (a 429 / 5xx / timeout asked once more on the same
    model after a pause), or None. Every answer's own price goes to the job's ledger (llm.<kind>.usd).
    `post` replaces requests.post (tests).
    """
    key = _openrouter_key()
    if not key:
        raise LanguageError("No OpenRouter key on this worker (OPENROUTER_API_KEY or an OpenRouter DIRECTOR_API_KEY).")
    post = post or requests.post
    if float(config.LANG_TRANSLATE_MAX_USD or 0) > 0 and SPENT["usd"] >= float(config.LANG_TRANSLATE_MAX_USD):
        raise LanguageError(f"The translation passed its ${config.LANG_TRANSLATE_MAX_USD:.2f} cap.")
    for model in models():
        for attempt in (1, 2):
            try:
                r = post(f"{config.OPENROUTER_API_BASE}/chat/completions",
                         headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                         json={"model": model, "temperature": 0.2, "max_tokens": 16000,
                               "messages": [{"role": "system", "content": system},
                                            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                               "response_format": {"type": "json_object"},
                               "usage": {"include": True},
                               **({"reasoning": _reasoning(model)} if _reasoning(model) else {})},
                         timeout=timeout)
            except requests.RequestException as e:
                print(f"[lang] {model} #{attempt}: {type(e).__name__}", flush=True)
                if attempt == 1:
                    time.sleep(3)
                    continue
                break
            try:
                body = r.json()
            except ValueError:
                body = None
            usd = _note_usage(body, kind)
            with _SPENT_LOCK:
                SPENT["usd"] += usd
                SPENT["calls"] += 1
            status = int(getattr(r, "status_code", 200) or 200)
            err = (body or {}).get("error") if isinstance(body, dict) else None
            if status >= 400 or err:
                code = status if status >= 400 else int((err or {}).get("code") or 500) if isinstance(err, dict) else 500
                print(f"[lang] {model} #{attempt}: HTTP {code} {str(err)[:160] if err else ''}", flush=True)
                if code == 402:
                    raise LanguageError("OpenRouter is out of credit: the translation could not be made.")
                if attempt == 1 and (code in (408, 409, 425, 429) or code >= 500):
                    time.sleep(4)
                    continue
                break
            try:
                data = _json_of(body["choices"][0]["message"]["content"])
            except (KeyError, IndexError, TypeError, ValueError):
                print(f"[lang] {model} #{attempt}: no JSON answer", flush=True)
                if attempt == 1:
                    continue
                break
            if isinstance(data, dict):
                return data
            break
    return None


# --------------------------------------------------------------------------- #
# The glossary: how every name is written in the new language, once for the whole video
# --------------------------------------------------------------------------- #

_GLOSSARY_PROMPT = """You prepare the name glossary for translating a documentary video's narration into {lang}.
Input JSON: "terms" (names, places and organisations from the narration) and "story" (what the video is about).
Return JSON {{"glossary": {{"<term>": "<how the term is written in {lang} narration>"}}}} with every term.
Rules:
- The established {lang} name where one exists (countries, regions, famous places, well-known organisations).
- A generic word inside a place name may be translated the way {lang} news writes it; the proper part never is.
- Names of people, brands, companies and official names without a {lang} form stay exactly as written.
- Never invent a name. When unsure, keep the original."""

_STOP_NAMES = {"I", "I'm", "I've", "I'll", "I'd", "The", "A", "An", "And", "But", "So", "Then", "When", "It", "It's",
               "That", "This", "There", "These", "Those", "They", "We", "He", "She", "You", "Is", "In", "On", "At",
               "Lately", "Somewhere", "Nobody", "What", "Why", "How", "If", "Or", "Full", "Not", "No", "Yes", "Now"}
_MONTHS = {"January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}


def glossary_terms(doc: dict, frags: Sequence[Fragment], limit: int = 80) -> List[str]:
    """The story's places and people, then the narration's capitalised runs ("Hoover Dam", "Las Vegas")."""
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    story = meta.get("story") if isinstance(meta.get("story"), dict) else {}
    terms: List[str] = []

    def add(t: Any) -> None:
        t = re.sub(r"\s+", " ", str(t or "")).strip(" ,.;:")
        if 2 <= len(t) <= 60 and t not in terms:
            terms.append(t)
    for key in ("places", "people"):
        for t in story.get(key) or []:
            add(t)
    for c in story.get("cast") or []:
        if isinstance(c, dict):
            add(c.get("name"))
    for t, _n in sorted(_capital_runs(" ".join(f.text for f in frags if f.spoken)).items(), key=lambda kv: -kv[1]):
        add(t)
    return terms[:limit]


_LINKS = {"of", "de", "del", "la", "the"}           # inside one name ("Bureau of Reclamation"); never "and"


def _capital_runs(text: str) -> Dict[str, int]:
    """
    The narration's names: runs of capitalised words ("Hoover Dam", "Bureau of Reclamation"), never across a
    sentence's end or a comma, without a leading "On" / "The" or a month, and a lone word that only ever opens a
    sentence ("Rose of servers...") left out - it is just the first word of a sentence.
    """
    toks = text.split()
    initial = [k == 0 or ends_sentence(toks[k - 1]) for k in range(len(toks))]
    mid_caps = {re.sub(r"[^\w'’-]", "", t) for k, t in enumerate(toks) if not initial[k] and t[:1].isupper()}
    runs: Dict[str, int] = {}
    k = 0
    while k < len(toks):
        if not toks[k][:1].isupper():
            k += 1
            continue
        run, starts_sentence, j = [], initial[k], k
        while j < len(toks):
            word = toks[j]
            bare = re.sub(r"[^\w'’.-]", "", word).strip(".")
            if word[:1].isupper():
                run.append(bare)
            elif bare.lower() in _LINKS and j + 1 < len(toks) and toks[j + 1][:1].isupper() and run:
                run.append(bare)
            else:
                break
            j += 1
            if ends_sentence(word) or word.endswith((",", ";", ":")):
                break
        while run and (run[0] in _STOP_NAMES or run[0] in _MONTHS or run[0].lower() in _LINKS):
            run.pop(0)
            starts_sentence = False
        while run and (run[-1].lower() in _LINKS or run[-1] in _MONTHS):
            run.pop()
        name = " ".join(run)
        lone_opener = len(run) == 1 and starts_sentence and run[0] not in mid_caps
        if name and len(name) >= 3 and not lone_opener:
            runs[name] = runs.get(name, 0) + 1
        k = max(j, k + 1)
    return runs


def make_glossary(doc: dict, frags: Sequence[Fragment], lang: str, chat: Callable = None) -> Dict[str, str]:
    terms = glossary_terms(doc, frags)
    if not terms:
        return {}
    chat = chat or chat_json
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    story = meta.get("story") if isinstance(meta.get("story"), dict) else {}
    data = chat(_GLOSSARY_PROMPT.format(lang=LANGUAGES[lang][0]),
                {"terms": terms, "story": {"summary": str(story.get("summary") or "")[:600]}}, kind="glossary")
    got = (data or {}).get("glossary") if isinstance(data, dict) else None
    if not isinstance(got, dict):
        return {}
    return {str(k): str(v).strip() for k, v in got.items() if str(k) in terms and str(v or "").strip()}


# --------------------------------------------------------------------------- #
# The narration, fragment by fragment
# --------------------------------------------------------------------------- #

_TRANSLATE_PROMPT = """You are a professional translator and dubbing writer. You translate the narration of a finished YouTube documentary into {lang} so it can be voiced again; the video's pictures stay exactly as they are.

Input JSON: "groups" - each a list of numbered fragments ("i", "text") that follow each other in the narration; read in order, a group's fragments form one or more sentences. A fragment is what is said while one shot is on screen. "before" is earlier narration, for context only (never translate it). "glossary" fixes how names are written in {lang}. "story" says what the video is about.

Return JSON {{"fragments": [{{"i": <the same i>, "text": "...", "say": "..."}}]}} with exactly one entry for every input fragment, in order.

Rules:
1. Natural spoken {lang} for a documentary narrator, same register and person (an "I" stays "I"). Read in order, a group's fragments must form natural {lang} sentences; keep each fragment's own meaning in its own fragment as far as {lang} grammar allows, so the words still land on the shot they describe. Never merge, drop or reorder fragments, never leave one empty.
2. About as long as the source when spoken: the concise wording a dubbing writer would choose. No additions, explanations or notes.
3. Names of people, places, organisations, rivers, dams, laws and brands: the glossary's form; otherwise the established {lang} name where one exists, else the original spelling. Never translate a person's name, never invent one.
4. Numbers keep their exact values: no rounding, no unit conversion, no changed years or dates. In "text" write them with digits the way a {lang} script does ({lang} separators); symbols and units as usual.
5. "say" is the same sentence as "text" written exactly as it is read aloud: every number, year, date, time, percentage, money amount, symbol, abbreviation and unit spelled out in {lang} words. Change nothing else.
6. The source is an automatic speech transcript: fix obvious mishearings from context (for example "rose of servers" for "rows of servers", "the number gets red" for "gets read") and spacing slips such as "1 ,040" (one thousand forty), but never change a fact."""


def _batches(groups: Sequence[List[int]], frags: Sequence[Fragment], max_chars: int) -> List[List[int]]:
    """Whole groups packed into requests of about `max_chars` source characters."""
    out, cur, size = [], [], 0
    for g, members in enumerate(groups):
        n = sum(len(frags[k].text) for k in members)
        if cur and size + n > max_chars:
            out.append(cur)
            cur, size = [], 0
        cur.append(g)
        size += n
    if cur:
        out.append(cur)
    return out


def _story(doc: dict) -> dict:
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    story = meta.get("story") if isinstance(meta.get("story"), dict) else {}
    return {"summary": str(story.get("summary") or "")[:600], "kind": str(story.get("kind") or "")}


def _ask_groups(gids: Sequence[int], groups, frags, lang: str, glossary: dict, story: dict, chat: Callable,
                note: str = "") -> Dict[int, dict]:
    """One request for these groups: {fragment index: {"text", "say"}} for the fragments it answered well."""
    first = groups[gids[0]][0] if gids else 0
    before = " ".join(f.text for f in frags[max(0, first - 3):first] if f.spoken)[-500:]
    payload = {"groups": [[{"i": k, "text": frags[k].text} for k in groups[g]] for g in gids],
               "glossary": glossary, "story": story, "before": before}
    if note:
        payload["note"] = note
    data = chat(_TRANSLATE_PROMPT.format(lang=LANGUAGES[lang][0]), payload, kind="translate")
    rows = (data or {}).get("fragments") if isinstance(data, dict) else None
    got: Dict[int, dict] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        try:
            k = int(row.get("i"))
        except (TypeError, ValueError):
            continue
        text = re.sub(r"\s+", " ", str(row.get("text") or "")).strip()
        say = re.sub(r"\s+", " ", str(row.get("say") or "")).strip()
        if text:
            got[k] = {"text": text, "say": say or text}
    return got


def translate(frags: List[Fragment], groups: List[List[int]], lang: str, *, glossary: Optional[dict] = None,
              story: Optional[dict] = None, chat: Callable = None, parallel: int = 4,
              max_chars: Optional[int] = None) -> Dict[str, Any]:
    """
    Every spoken fragment translated (Fragment.out / .say). A group the model answered incompletely, or whose
    numbers came back changed, is asked once more on its own with what was wrong; a group still missing a
    fragment is translated as a whole and split by the source fragments' lengths (_split_like). Returns
    {"groups", "requests", "retried", "split", "numberIssues": [{"scene", "missing", "text"}]}.
    """
    chat = chat or chat_json
    glossary, story = glossary or {}, story or {}
    batches = _batches(groups, frags, int(max_chars or config.LANG_TRANSLATE_BATCH_CHARS))
    answers: Dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(parallel, len(batches) or 1)), thread_name_prefix="lang") as pool:
        for got in pool.map(lambda b: _ask_groups(b, groups, frags, lang, glossary, story, chat), batches):
            answers.update(got)

    def faults(g: int, got: Dict[int, dict]) -> Tuple[int, int, List[str]]:
        """(fragments missing, numbers lost, why) of one answer for group g."""
        missing, lost, why = 0, 0, []
        for k in groups[g]:
            a = got.get(k)
            if not a:
                missing += 1
                why.append(f"fragment {k} is missing")
                continue
            miss = numbers_match(frags[k].text, a["text"])
            if miss:
                lost += len(miss)
                why.append(f"fragment {k} lost the number(s) {', '.join(miss)}")
            # A fragment several times its source's length repeats something (or swallowed its neighbour's
            # words); a long one cut to a stub dropped some: either is voiced as said, so it is asked again.
            ratio = len(a["text"]) / max(1, len(frags[k].text))
            if ratio > (4.0 if lang in UNSPACED else 2.6) or (len(frags[k].text) >= 24 and ratio < (0.12 if lang in UNSPACED else 0.35)):
                lost += 1
                why.append(f"fragment {k} is {ratio:.1f}x its source's length")
        return missing, lost, why
    retried = 0
    for g in range(len(groups)):
        first = {k: answers[k] for k in groups[g] if k in answers}
        m1, l1, why = faults(g, first)
        if not why:
            continue
        retried += 1
        again = _ask_groups([g], groups, frags, lang, glossary, story, chat,
                            note="Your last answer was wrong: " + "; ".join(why)[:400] +
                                 ". Answer every fragment and keep every number's value.")
        again = {k: a for k, a in again.items() if k in groups[g]}
        m2, l2, _ = faults(g, again)
        # A group's fragments come from ONE answer: two answers may cut the same sentence differently, and a
        # mix of them would say a piece twice or not at all.
        if (m2, l2) < (m1, l1):
            for k in groups[g]:
                answers.pop(k, None)
            answers.update(again)
    split = 0
    for g, members in enumerate(groups):
        if all(k in answers for k in members):
            continue
        whole = " ".join(frags[k].text for k in members)
        data = chat(_TRANSLATE_PROMPT.format(lang=LANGUAGES[lang][0]),
                    {"groups": [[{"i": 0, "text": whole}]], "glossary": glossary, "story": story}, kind="translate")
        row = ((data or {}).get("fragments") or [{}])[0] if isinstance(data, dict) else {}
        text = str((row or {}).get("text") or "").strip() if isinstance(row, dict) else ""
        say = str((row or {}).get("say") or "").strip() if isinstance(row, dict) else ""
        if not text:
            raise LanguageError(f"The translation of scene {frags[members[0]].scene + 1} could not be made.")
        pieces = _split_like(text, [frags[k].text for k in members])
        spoken = _split_like(say or text, [frags[k].text for k in members])
        for k, p, s in zip(members, pieces, spoken):
            answers[k] = {"text": p, "say": s or p}
        split += 1
    issues = []
    for k, f in enumerate(frags):
        if not f.spoken:
            continue
        a = answers[k]
        f.out, f.say = a["text"], a["say"]
        miss = numbers_match(f.text, f.out)
        if miss:
            issues.append({"scene": f.scene, "missing": miss, "text": f.out[:160]})
    return {"groups": len(groups), "requests": len(batches) + retried + split, "retried": retried,
            "split": split, "numberIssues": issues}


def _split_like(text: str, sources: Sequence[str]) -> List[str]:
    """`text` cut at word boundaries into len(sources) pieces sized like the sources (none left empty)."""
    n = len(sources)
    if n <= 1:
        return [text]
    words = text.split() or [text]
    if len(words) < n:
        words = list(text) if len(text) >= n else words + [""] * (n - len(words))
        joiner = ""
    else:
        joiner = " "
    weights = [max(1, len(s)) for s in sources]
    total = float(sum(weights))
    out, at, acc = [], 0, 0.0
    for i, w in enumerate(weights):
        acc += w
        end = len(words) if i == n - 1 else max(at + 1, min(len(words) - (n - i - 1), round(len(words) * acc / total)))
        out.append(joiner.join(words[at:end]).strip())
        at = end
    return out


# --------------------------------------------------------------------------- #
# The looks' on-screen text
# --------------------------------------------------------------------------- #

_SCREEN_PROMPT = """You translate the on-screen text of a video's graphics into {lang}. The narration is now in {lang}: an item's "context" is the {lang} narration spoken while its graphic is on screen. A graphic repeats the narration's own words: when the context says the same thing, use exactly the context's words for it (if the context says "nivel máximo" for "FULL", answer "NIVEL MÁXIMO").

Input JSON: "items" ({{"id", "text", "field", "context", "of"?}}) and "glossary" (how names are written in {lang}).
Return JSON {{"items": [{{"id": "...", "text": "..."}}]}} with every id.

Rules:
- The same meaning, as short as the source: graphics have little room (at most the source's length plus a third).
- Keep the source's casing: ALL CAPS stays all caps, Title Case stays title case.
- Numbers, years and dates keep their values; a date in {lang} order with {lang} month names; {lang} number separators.
- Names as in the glossary. A unit or label word in its usual {lang} form or abbreviation; symbols (%, $, °) as they are.
- An item with "of" is the words to highlight inside another item's text: answer words that appear exactly in your translation of that item."""

# Overlay fields whose words are drawn on screen (remotion/src/types.ts Overlay); the rest are names of looks,
# styles, colours, links or numbers.
_TEXT_KEYS = ("text", "subtitle", "label", "suffix", "body", "callout")
_ROW_KEYS = {"items": ("label", "text"), "points": ("label",), "locations": ("label",)}
_DATA_KEYS = ("title", "kicker", "unit", "asOfLabel", "sourceName", "week")
_DATA_ROWS = {"refs": ("label",), "bars": ("label",)}
_DATA_ONE = {"delta": ("text",), "record": ("label", "word"), "latest": ("label",), "compare": ("label",)}


def _wordy(v: Any) -> bool:
    """Text a viewer reads: has letters (a bare "%", "$" or "2022" is the same in every language)."""
    return isinstance(v, str) and bool(v.strip()) and any(ch.isalpha() for ch in v) and len(v) <= 600


def screen_texts(doc: dict) -> List[dict]:
    """
    Every piece of display text in the looks: [{"id", "text", "field", "set": callable(new_text), "at": seconds,
    "of": id of the text a highlight belongs to}]. The looks are the overlays, the full-screen graphic scenes
    (scene.animation) and the brand kit's end card.
    """
    fps = float(doc.get("fps") or 30)
    out: List[dict] = []

    def add(obj: dict, key: str, ident: str, at: float, of: str = "") -> None:
        if _wordy(obj.get(key)):
            out.append({"id": ident, "text": obj[key], "field": key, "at": at, "of": of,
                        "set": (lambda v, o=obj, k=key: o.__setitem__(k, v))})

    def look(ov: dict, tag: str, at: float) -> None:
        for key in _TEXT_KEYS:
            add(ov, key, f"{tag}.{key}", at)
        if _wordy(ov.get("highlight")):
            add(ov, "highlight", f"{tag}.highlight", at, of=f"{tag}.text")
        for key, subkeys in _ROW_KEYS.items():
            for n, row in enumerate(ov.get(key) or [] if isinstance(ov.get(key), list) else []):
                if isinstance(row, dict):
                    for sk in subkeys:
                        add(row, sk, f"{tag}.{key}{n}.{sk}", at)
        data = ov.get("data") if isinstance(ov.get("data"), dict) else None
        if data:
            for key in _DATA_KEYS:
                add(data, key, f"{tag}.data.{key}", at)
            for key, subkeys in _DATA_ROWS.items():
                for n, row in enumerate(data.get(key) or [] if isinstance(data.get(key), list) else []):
                    if isinstance(row, dict):
                        for sk in subkeys:
                            add(row, sk, f"{tag}.data.{key}{n}.{sk}", at)
            for key, subkeys in _DATA_ONE.items():
                if isinstance(data.get(key), dict):
                    for sk in subkeys:
                        add(data[key], sk, f"{tag}.data.{key}.{sk}", at)
        geo = ov.get("geo") if isinstance(ov.get("geo"), dict) else None
        if geo:
            add(geo, "label", f"{tag}.geo.label", at)
            for n, pin in enumerate(geo.get("pins") or [] if isinstance(geo.get("pins"), list) else []):
                if isinstance(pin, dict):
                    add(pin, "label", f"{tag}.geo.pins{n}.label", at)
    for n, ov in enumerate(doc.get("overlays") or []):
        if isinstance(ov, dict):
            look(ov, f"o{n}", float(ov.get("startFrame") or 0) / fps)
    for n, sc in enumerate(doc.get("scenes") or []):
        if isinstance(sc, dict) and isinstance(sc.get("animation"), dict):
            look(sc["animation"], f"s{n}.animation", float(sc.get("startFrame") or 0) / fps)
    outro = ((doc.get("brand") or {}).get("outro") if isinstance(doc.get("brand"), dict) else None)
    if isinstance(outro, dict) and outro.get("kind") == "card":
        for key in ("title", "text", "subtext"):
            add(outro, key, f"brand.outro.{key}", float(doc.get("durationInFrames") or 0) / fps)
    return out


def _context_at(frags: Sequence[Fragment], at: float, before: float = 1.0, after: float = 4.0) -> str:
    """The new narration spoken around a look's start (by the OLD clock: the looks are still on it)."""
    near = [f.out for f in frags if f.spoken and f.out and f.start is not None
            and f.end >= at - before and f.start <= at + after]
    return " ".join(near)[:300]


def translate_screen_text(doc: dict, frags: Sequence[Fragment], lang: str, glossary: Optional[dict] = None,
                          chat: Callable = None, batch: int = 80) -> Dict[str, Any]:
    """
    The looks' display text translated in place, with the narration's own new wording beside each look. A text
    whose numbers would change keeps the source's text; a highlight not found in its translated text is dropped
    (the look then marks nothing rather than a phrase that is not there). Returns the report.
    """
    chat = chat or chat_json
    items = screen_texts(doc)
    if not items:
        return {"items": 0, "kept": 0, "highlightsDropped": 0}
    by_id = {it["id"]: it for it in items}
    answers: Dict[str, str] = {}
    for at in range(0, len(items), batch):
        chunk = items[at:at + batch]
        payload = {"items": [{"id": it["id"], "text": it["text"], "field": it["field"],
                              "context": _context_at(frags, it["at"]), **({"of": it["of"]} if it["of"] else {})}
                             for it in chunk], "glossary": glossary or {}}
        data = chat(_SCREEN_PROMPT.format(lang=LANGUAGES[lang][0]), payload, kind="screen_text")
        for row in (data or {}).get("items") or [] if isinstance(data, dict) else []:
            if isinstance(row, dict) and str(row.get("id")) in by_id and str(row.get("text") or "").strip():
                answers[str(row["id"])] = re.sub(r"\s+", " ", str(row["text"])).strip()
    kept = dropped = 0
    for it in items:
        new = answers.get(it["id"])
        if not new or numbers_match(it["text"], new) or len(new) > max(24, int(len(it["text"]) * 1.8)):
            kept += 1                       # the source's own text: never a changed number or an overflowing look
            continue
        if it["of"]:
            host = answers.get(it["of"]) or (by_id.get(it["of"]) or {}).get("text") or ""
            if new.casefold() not in host.casefold():
                it["set"]("")
                dropped += 1
                continue
        it["set"](new)
    return {"items": len(items), "translated": len(items) - kept, "kept": kept, "highlightsDropped": dropped}


# --------------------------------------------------------------------------- #
# The voice
# --------------------------------------------------------------------------- #

def _flat_words(frags: Sequence[Fragment]) -> List[dict]:
    return [w for f in frags for w in f.words]


def pick_sample(frags: Sequence[Fragment], low: float = 10.0, high: float = 24.0, ideal: float = 17.0,
                gap: float = 0.9) -> Optional[Tuple[float, float, str]]:
    """
    The stretch of the narration the narrator is cloned from: whole sentences, `low`..`high` seconds, no pause
    over `gap`, no figures (the voice server reads a reference's figures by English rules) - the one nearest
    `ideal` seconds. (start, end, its exact words) or None. The voice server keeps 30 s of a reference at most.
    """
    words = _flat_words(frags)
    n = len(words)
    starts = [k for k in range(n) if k == 0 or ends_sentence(words[k - 1]["text"])]
    ends = set(k for k in range(n) if ends_sentence(words[k]["text"]))
    best = None
    for a in starts:
        span_ok = True
        for b in range(a, n):
            if b > a and words[b]["start"] - words[b - 1]["end"] > gap:
                break
            if _DIGITS.search(words[b]["text"]):
                span_ok = False
                break
            length = words[b]["end"] - words[a]["start"]
            if length > high:
                break
            if b in ends and length >= low:
                score = abs(length - ideal)
                if best is None or score < best[0]:
                    best = (score, a, b)
        if not span_ok:
            continue
    if best is None:
        return None
    _s, a, b = best
    text = _tidy(" ".join(words[k]["text"] for k in range(a, b + 1)))
    return float(words[a]["start"]), float(words[b]["end"]), text


def clone_sample(narration: str, frags: Sequence[Fragment], work: str, key: str = "narration") -> Optional[dict]:
    """
    The voice-server reference cut from the source narration: {"b64", "text", "key", "seconds", "from", "to"}
    (FLAC, mono 24 kHz, sent inline: a narrator's voice is never stored anywhere for this), or None.
    """
    pick = pick_sample(frags) or pick_sample(frags, low=6.0, high=26.0, gap=1.2)
    if not pick:
        return None
    a, b, text = pick
    a, b = max(0.0, a - 0.12), b + 0.3
    dest = os.path.join(work, "voice_sample.flac")
    p = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-ss", f"{a:.3f}", "-to", f"{b:.3f}",
                        "-i", narration, "-vn", "-ac", "1", "-ar", "24000", "-c:a", "flac", dest],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    if p.returncode != 0 or not os.path.isfile(dest):
        print(f"[lang] the voice sample could not be cut: {(p.stderr or '')[-200:]}", flush=True)
        return None
    with open(dest, "rb") as fh:
        data = fh.read()
    return {"b64": base64.b64encode(data).decode("ascii"), "text": text, "key": key[:60],
            "seconds": round(b - a, 2), "from": round(a, 2), "to": round(b, 2)}


class VoiceError(RuntimeError):
    """The new narration could not be voiced. The message is written for the owner."""


class VoiceServer:
    """Our own voice endpoint (Qwen3-TTS on RunPod): /run, then /status until done. Never logs its key."""

    def __init__(self, endpoint: str = "", key: str = "", poll: float = 2.0, session=None):
        self.endpoint = endpoint or config.LANG_TTS_ENDPOINT
        self.key = key or config.LANG_TTS_API_KEY
        self.poll = poll
        self.http = session or requests
        self.base = f"https://api.runpod.ai/v2/{self.endpoint}"
        self.jobs: List[dict] = []
        self._lock = threading.Lock()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}

    def health(self, timeout: float = 20) -> dict:
        r = self.http.get(f"{self.base}/health", headers=self._headers(), timeout=timeout)
        if r.status_code in (401, 403):
            return {"ok": False, "error": f"the voice endpoint refused this worker's key (HTTP {r.status_code})"}
        try:
            return {"ok": r.status_code == 200, **(r.json() if r.status_code == 200 else {})}
        except ValueError:
            return {"ok": False, "error": f"HTTP {r.status_code}"}

    def voice(self, body: dict, timeout: float) -> dict:
        """One part voiced: the job's output plus its RunPod timing (delayTime / executionTime, ms)."""
        if not self.key:
            raise VoiceError("No RunPod key for the voice endpoint (LANG_TTS_API_KEY / FANOUT_API_KEY).")
        r = self.http.post(f"{self.base}/run", json={"input": body}, headers=self._headers(), timeout=(20, 120))
        if r.status_code in (401, 403):
            raise VoiceError(f"The voice endpoint refused this worker's key (HTTP {r.status_code}).")
        if r.status_code >= 400:
            raise RuntimeError(f"voice /run HTTP {r.status_code}: {r.text[:160]}")
        job = (r.json() or {}).get("id")
        if not job:
            raise RuntimeError("voice /run answered without a job id")
        deadline = time.time() + timeout
        while True:
            time.sleep(self.poll)
            try:
                s = self.http.get(f"{self.base}/status/{job}", headers=self._headers(), timeout=(20, 60))
                data = s.json() if s.status_code == 200 else {}
            except (requests.RequestException, ValueError):
                data = {}
            state = str(data.get("status") or "").upper()
            if state == "COMPLETED":
                out = data.get("output") if isinstance(data.get("output"), dict) else {}
                row = {"id": job, "delayMs": float(data.get("delayTime") or 0),
                       "executionMs": float(data.get("executionTime") or 0), "seconds": out.get("seconds"),
                       "worker": str(data.get("workerId") or "")}
                with self._lock:
                    self.jobs.append(row)
                if not out.get("ok"):
                    raise RuntimeError(f"voice job: {str(out.get('error') or 'no audio')[:200]}")
                return {**out, "_job": row}
            if state in ("FAILED", "CANCELLED", "TIMED_OUT"):
                with self._lock:
                    self.jobs.append({"id": job, "delayMs": float(data.get("delayTime") or 0),
                                      "executionMs": float(data.get("executionTime") or 0), "failed": state})
                raise RuntimeError(f"voice job {state.lower()}: {str(data.get('error') or '')[:160]}")
            if time.time() >= deadline:
                try:
                    self.http.post(f"{self.base}/cancel/{job}", headers=self._headers(), timeout=(10, 20))
                except requests.RequestException:
                    pass
                raise RuntimeError(f"no audio within {int(timeout)} s")

    def gpu_seconds(self, boot_cap: float = 150.0, idle: float = 60.0) -> float:
        """
        What RunPod bills of these jobs, as near as the jobs tell: every run, each worker's start once (the wait
        of its first job, at most `boot_cap` - a later job's wait is a queue behind a busy worker, not billed) and
        the minute each worker stays up after its last job (the endpoint's idle timeout, billed).
        """
        runs = sum(float(j.get("executionMs") or 0) for j in self.jobs) / 1000.0
        firsts: Dict[str, float] = {}
        for n, j in enumerate(self.jobs):
            worker = str(j.get("worker") or "") or f"job{n}"
            firsts.setdefault(worker, min(boot_cap, float(j.get("delayMs") or 0) / 1000.0))
        if not any(j.get("worker") for j in self.jobs):
            # No worker ids: the first jobs (up to the parts voiced at once) are the workers' starts.
            firsts = {k: v for k, v in list(firsts.items())[:max(1, int(config.LANG_TTS_PARALLEL))]}
        return round(runs + sum(firsts.values()) + idle * len(firsts), 1)


@dataclass
class Part:
    index: int
    frags: List[int]
    text: str
    path: str = ""
    seconds: float = 0.0
    attempts: int = 0


def _sentences(text: str) -> List[str]:
    return [s for s in re.split(r"(?<=[.!?…。！？])\s*", text) if s.strip()]


def _unspaced_lines(text: str, limit: int = 300) -> List[str]:
    """A Chinese / Japanese text one sentence a line, a long one cut at its commas (the voice server cannot split
    a line without spaces: tts/textnorm._split_long would recurse)."""
    out = []
    for s in _sentences(text):
        while len(s) > limit:
            cut = max(s.rfind(ch, 0, limit) for ch in "，、,;；")
            cut = cut + 1 if cut > limit // 3 else limit
            out.append(s[:cut].strip())
            s = s[cut:].strip()
        if s:
            out.append(s)
    return out


def plan_parts(frags: Sequence[Fragment], groups: Sequence[List[int]], lang: str, max_chars: int = 0,
               paragraph_pause: float = 1.0) -> List[Part]:
    """
    The new narration in voice-server parts of about `max_chars`, cut between groups (sentences). Inside a
    part, a group after a pause of `paragraph_pause` seconds or more in the source starts a new paragraph (the
    voice server pauses longer there, as the narrator did); Chinese and Japanese go one sentence a line.
    """
    limit = int(max_chars or config.LANG_TTS_PART_CHARS)
    parts: List[Part] = []
    cur: List[int] = []
    pieces: List[str] = []
    size = 0
    prev_end: Optional[float] = None

    def flush() -> None:
        nonlocal cur, pieces, size
        if cur:
            text = "\n".join(pieces) if lang in UNSPACED else "".join(pieces).strip()
            parts.append(Part(index=len(parts), frags=list(cur), text=text))
        cur, pieces, size = [], [], 0
    for members in groups:
        say = " ".join(frags[k].say or frags[k].out for k in members).strip()
        if not say:
            continue
        start = frags[members[0]].start
        if cur and size + len(say) > limit:
            flush()
        if lang in UNSPACED:
            pieces.extend(_unspaced_lines(say))
        else:
            sep = "" if not pieces else ("\n\n" if prev_end is not None and start is not None
                                         and start - prev_end >= paragraph_pause else " ")
            pieces.append(sep + say)
        cur.extend(members)
        size += len(say)
        prev_end = frags[members[-1]].end
    flush()
    return parts


def voice_body(part: Part, lang: str, voice: dict, seed: int, speed: float = 0.0, pause: float = 0.0) -> dict:
    """One part's request to our voice server (tts/handler.py)."""
    ref = {k: v for k, v in voice.items() if k in ("url", "b64", "key", "text") and v}
    return {"action": "tts", "text": part.text, "language": lang, "voice": ref, "seed": int(seed),
            "speed": round(float(speed or config.LANG_TTS_SPEED), 3),
            "pause": round(float(pause or config.LANG_TTS_PAUSE), 3),
            "format": "mp3", "return": "url", "tail_pause": 0.0, "validate": lang == "en",
            "max_attempts": 1 if lang in ONE_TAKE else 2}


def synthesize(parts: List[Part], lang: str, voice: dict, work: str, server: VoiceServer, *, seed: int,
               report: Optional[Callable] = None, parallel: int = 0, download: Callable = None) -> List[Part]:
    """
    Every part voiced (in parallel, up to the endpoint's workers) and on disk as <work>/voice/part-NNN.mp3. A part
    is asked again (a new seed) after a failure; one that cannot be voiced ends the job (VoiceError) - a narration
    with a part missing is never made. `download(url, dest)` fetches the audio (tests replace it).
    """
    from . import storage
    download = download or (lambda url, dest: storage.download(url, dest, timeout=120))
    folder = os.path.join(work, "voice")
    os.makedirs(folder, exist_ok=True)
    total = len(parts)
    done = [0]
    lock = threading.Lock()
    deadline = time.time() + float(config.LANG_TTS_TOTAL_SECONDS)

    def one(part: Part) -> Part:
        last = ""
        for attempt in range(1, 4):
            left = deadline - time.time()
            if left < 5:
                break
            part.attempts = attempt
            try:
                out = server.voice(voice_body(part, lang, voice, seed + 7919 * (attempt - 1)),
                                   timeout=min(float(config.LANG_TTS_TIMEOUT), left))
                url = str(out.get("audio_url") or "")
                dest = os.path.join(folder, f"part-{part.index:03d}.mp3")
                if url:
                    download(url, dest)
                elif out.get("audio_b64"):
                    with open(dest, "wb") as fh:
                        fh.write(base64.b64decode(out["audio_b64"]))
                else:
                    raise RuntimeError("the voice job finished without audio")
                part.path, part.seconds = dest, float(out.get("seconds") or 0.0)
                with lock:
                    done[0] += 1
                    if report:
                        report(f"Voicing the {LANGUAGES[lang][0]} narration: {done[0]} of {total} parts",
                               15 + int(30 * done[0] / max(1, total)))
                return part
            except VoiceError:
                raise
            except Exception as e:  # noqa: BLE001 - asked again, then the job ends with the reason
                last = f"{type(e).__name__}: {str(e)[:200]}"
                print(f"[lang] part {part.index + 1}/{total} attempt {attempt}: {last}", flush=True)
                time.sleep(min(10.0, 2.0 * attempt))
        raise VoiceError(f"Part {part.index + 1} of {total} of the new narration could not be voiced ({last}).")
    workers = max(1, min(int(parallel or config.LANG_TTS_PARALLEL), total or 1))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="voice") as pool:
        futures = [pool.submit(one, p) for p in parts]
        for fut in as_completed(futures):
            fut.result()
    return parts


def _silence(path: str, seconds: float) -> str:
    subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-t", f"{max(0.01, seconds):.3f}",
                    "-i", "anullsrc=r=44100:cl=mono", "-c:a", "pcm_s16le", path],
                   check=True, capture_output=True, timeout=60)
    return path


def join_narration(parts: Sequence[Part], frags: Sequence[Fragment], work: str, target_lufs: float,
                   lead: float, tail: float, gap: float = 0.0) -> Dict[str, Any]:
    """
    The parts as one narration (src/tts.join: one rate, one steady gain to `target_lufs`, the source narration's
    loudness, so the music and the sounds planned against it stay balanced), with the source's own silence
    before the first word (`lead`) and after the last (`tail`), and `gap` seconds between two parts.
    """
    from . import tts
    folder = os.path.join(work, "voice")
    pieces: List[str] = []
    if lead > 0.02:
        pieces.append(_silence(os.path.join(folder, "lead.wav"), lead))
    for n, p in enumerate(parts):
        pieces.append(p.path)
        if gap > 0.02 and n < len(parts) - 1:
            pieces.append(_silence(os.path.join(folder, f"gap-{n:03d}.wav"), gap))
    if tail > 0.02:
        pieces.append(_silence(os.path.join(folder, "tail.wav"), tail))
    joined = tts.join(pieces, os.path.join(work, "narration_new.mp3"), gap=0.0, target=target_lufs)
    lifted = _lift(joined["path"], target_lufs, joined.get("lufs"))
    if lifted is not None:
        joined["lufs"], joined["liftedDb"] = lifted
    return joined


def _lift(path: str, target: float, have: Optional[float], ceiling: float = 0.89) -> Optional[Tuple[float, float]]:
    """
    The rest of the way to `target` when the join's steady gain stopped short of it at the peaks (src/tts.join
    never lifts a peak over -1 dBTP): at most 6 dB more, the few peaks held by a soft limiter (`ceiling`, linear).
    The Lake Mead proof: a source narration at -14.9 LUFS, the new voice joined at -16.1. Returns (LUFS, dB
    added) or None when nothing was needed or it could not be done (the joined file stays as it was).
    """
    if have is None or target is None or have >= target - 0.6:
        return None
    from . import tts, voicepolish
    tmp = path + ".lift.mp3"
    db, got = round(min(6.0, target - have), 2), None
    for _ in range(2):
        # From the joined file each time (never an encode of an encode); the limiter takes a little of the gain
        # back, so a pass that lands short is made again with what it missed added.
        p = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-i", path, "-af",
                            f"volume={db:.2f}dB,alimiter=limit={ceiling}:attack=5:release=60:level=0",
                            "-ar", str(tts.JOIN_RATE), "-ac", "1", "-c:a", "libmp3lame", "-b:a", "128k", tmp],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
        if p.returncode != 0 or not os.path.isfile(tmp):
            print(f"[lang] narration not lifted: {(p.stderr or '')[-160:]}", flush=True)
            return None
        got = voicepolish.loudness(tmp).get("lufs")
        if got is None or got >= target - 0.3 or db >= 6.0:
            break
        db = round(min(6.0, db + (target - float(got))), 2)
    os.replace(tmp, path)
    return (round(float(got), 1) if got is not None else round(have + db, 1)), db


# --------------------------------------------------------------------------- #
# Alignment: the new words' times
# --------------------------------------------------------------------------- #

def _norm(token: str) -> str:
    """A token as compared: case and accents folded, marks dropped, a number by its value."""
    t = unicodedata.normalize("NFKC", str(token or ""))
    num = _canonical(re.sub(r"[^\d.,   ]", "", t).strip(" .,")) if _DIGITS.search(t) else None
    if num is not None and re.fullmatch(r"[\W\d_]*\d[\d.,   ]*[\W_]*", t):
        return num
    t = "".join(ch for ch in unicodedata.normalize("NFKD", t.casefold()) if not unicodedata.combining(ch))
    return re.sub(r"[^\w]", "", t)


def _tokens(text: str, lang: str) -> List[str]:
    """The words of a text as captions show them (Chinese / Japanese: each character; Latin runs whole)."""
    if lang in UNSPACED:
        out = []
        for run in re.findall(r"[A-Za-z0-9][A-Za-z0-9.,'’%-]*|\S", text):
            if out and not re.search(r"[\w]", run, re.UNICODE):
                out[-1] += run              # a mark rides on the character before it
            else:
                out.append(run)
        return out
    return text.split()


def _heard_units(heard: Sequence[Any], lang: str) -> List[dict]:
    """Whisper's words as {"text", "start", "end"}; Chinese / Japanese words cut into characters, timed evenly."""
    out = []
    for w in heard:
        text = str(getattr(w, "text", None) if not isinstance(w, dict) else w.get("text") or "").strip()
        a = float(getattr(w, "start", 0.0) if not isinstance(w, dict) else w.get("start") or 0.0)
        b = float(getattr(w, "end", 0.0) if not isinstance(w, dict) else w.get("end") or 0.0)
        if not text:
            continue
        if lang in UNSPACED:
            chars = [c for c in _tokens(text, lang)]
            step = (b - a) / max(1, len(chars))
            for n, c in enumerate(chars):
                out.append({"text": c, "start": a + n * step, "end": a + (n + 1) * step})
        else:
            out.append({"text": text, "start": a, "end": max(a, b)})
    return out


def align(frags: List[Fragment], heard: Sequence[Any], lang: str) -> Dict[str, Any]:
    """
    Every spoken fragment's translated words (Fragment.out) timed on the new narration (Fragment.new_words), by
    sequence alignment against what whisper heard: matched words take whisper's times, a run of words whisper
    heard differently (a number said as words, a name spelled another way) is spread over what it heard there,
    and words it missed are placed between their timed neighbours. Returns {"words", "matched", "ratio",
    "byFragment": {index: ratio}}.
    """
    units = _heard_units(heard, lang)
    owners: List[int] = []
    authored: List[str] = []
    for k, f in enumerate(frags):
        if f.spoken and f.out:
            for t in _tokens(f.out, lang):
                owners.append(k)
                authored.append(t)
    a = [_norm(t) for t in authored]
    b = [_norm(u["text"]) for u in units]
    times: List[Optional[Tuple[float, float]]] = [None] * len(authored)
    matched = [False] * len(authored)
    if units:
        sm = SequenceMatcher(None, a, b, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for i, j in zip(range(i1, i2), range(j1, j2)):
                    times[i] = (units[j]["start"], units[j]["end"])
                    matched[i] = True
            elif tag == "replace":
                lo, hi = units[j1]["start"], units[j2 - 1]["end"]
                n = max(1, i2 - i1)
                for m, i in enumerate(range(i1, i2)):
                    times[i] = (lo + (hi - lo) * m / n, lo + (hi - lo) * (m + 1) / n)
    known = [i for i, t in enumerate(times) if t is not None]
    if not known:
        raise LanguageError("The new narration could not be matched to its text (nothing was recognised).")
    for i, t in enumerate(times):
        if t is not None:
            continue
        left = max((k for k in known if k < i), default=None)
        right = min((k for k in known if k > i), default=None)
        if left is None:
            v = times[right][0]
            times[i] = (v, v)
        elif right is None:
            v = times[left][1]
            times[i] = (v, v)
        else:
            lo, hi = times[left][1], times[right][0]
            span = right - left
            times[i] = (lo + (hi - lo) * (i - left - 1) / span, lo + (hi - lo) * (i - left) / span)
    for f in frags:
        f.new_words = []
    for i, (k, t) in enumerate(zip(owners, authored)):
        s, e = times[i]
        frags[k].new_words.append({"text": t, "start": round(float(s), 3), "end": round(float(max(s, e)), 3)})
    by_frag: Dict[int, List[bool]] = {}
    for k, ok in zip(owners, matched):
        by_frag.setdefault(k, []).append(ok)
    ratio = sum(matched) / max(1, len(matched))
    return {"words": len(authored), "matched": sum(matched), "ratio": round(ratio, 3),
            "byFragment": {k: round(sum(v) / max(1, len(v)), 3) for k, v in by_frag.items()}}


def part_ratios(parts: Sequence[Part], by_fragment: Dict[int, float], frags: Sequence[Fragment]) -> Dict[int, float]:
    """How much of each part whisper heard as written (word-weighted)."""
    out = {}
    for p in parts:
        num = den = 0.0
        for k in p.frags:
            n = len(frags[k].new_words) or 1
            num += by_fragment.get(k, 0.0) * n
            den += n
        out[p.index] = round(num / den, 3) if den else 1.0
    return out


# --------------------------------------------------------------------------- #
# Re-timing the timeline
# --------------------------------------------------------------------------- #

LEAD_MAX = 0.75          # a cut that came before its line's first word (in the breath) keeps up to this lead


def _scene_starts(doc: dict, frags: Sequence[Fragment], new_total: float, min_len: float) -> List[float]:
    """
    Each scene's new start (seconds): a spoken scene at its first new word, less the lead its cut had before its
    first word (never before the last word of the scene in front); a silent scene where the old clock puts it
    between its spoken neighbours; then every scene at least `min_len` long, the first at 0.
    """
    fps = float(doc.get("fps") or 30)
    scenes = doc.get("scenes") or []
    n = len(scenes)
    old = [float(sc.get("startFrame") or 0) / fps for sc in scenes]
    old_total = float(doc.get("durationInFrames") or 0) / fps
    new: List[Optional[float]] = [None] * n
    prev_end = 0.0
    for i in range(n):
        f = frags[i] if i < len(frags) else None
        if f is not None and f.spoken and f.new_words and f.words:
            lead = min(LEAD_MAX, max(0.0, f.start - old[i]))
            new[i] = max(prev_end, f.new_start - lead) if i else 0.0
            new[i] = min(new[i], f.new_start) if i else 0.0
            prev_end = f.new_end
    new[0] = 0.0
    # Silent scenes: between the nearest placed neighbours, by the old clock.
    placed = [i for i in range(n) if new[i] is not None]
    for i in range(n):
        if new[i] is not None:
            continue
        left = max((k for k in placed if k < i), default=0)
        right = min((k for k in placed if k > i), default=None)
        a_old, a_new = old[left], new[left]
        b_old, b_new = (old[right], new[right]) if right is not None else (old_total, new_total)
        span = (b_old - a_old) or 1.0
        new[i] = a_new + (b_new - a_new) * (old[i] - a_old) / span
    starts = [float(x) for x in new]
    # Order and room: each scene at least min_len, the last one too.
    for i in range(1, n):
        starts[i] = max(starts[i], starts[i - 1] + min_len)
    over = starts[-1] + min_len - new_total if n else 0.0
    if over > 0:
        for i in range(n - 1, 0, -1):
            starts[i] = min(starts[i], (starts[i + 1] if i + 1 < n else new_total) - min_len)
    return starts


class Warp:
    """Old seconds -> new seconds, linear between anchors (each scene's start, both ends)."""

    def __init__(self, old: Sequence[float], new: Sequence[float]):
        pairs = sorted(zip(old, new))
        xs, ys = [], []
        for x, y in pairs:
            if xs and (x <= xs[-1] or y < ys[-1]):
                continue
            xs.append(float(x))
            ys.append(float(y))
        self.xs, self.ys = xs, ys

    def __call__(self, t: float) -> float:
        xs, ys = self.xs, self.ys
        if not xs:
            return t
        if t <= xs[0]:
            return ys[0] + (t - xs[0]) * (self._slope(0) if len(xs) > 1 else 1.0)
        if t >= xs[-1]:
            return ys[-1] + (t - xs[-1]) * (self._slope(len(xs) - 2) if len(xs) > 1 else 1.0)
        lo, hi = 0, len(xs) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if xs[mid] <= t:
                lo = mid
            else:
                hi = mid
        return ys[lo] + (t - xs[lo]) * (ys[hi] - ys[lo]) / ((xs[hi] - xs[lo]) or 1.0)

    def _slope(self, i: int) -> float:
        return (self.ys[i + 1] - self.ys[i]) / ((self.xs[i + 1] - self.xs[i]) or 1.0)


def _key_tokens(ov: dict) -> List[str]:
    """What a look shows that is said: its numbers first, then its names (from what the narration said)."""
    said = str(ov.get("said") or "")
    shown = " ".join(str(ov.get(k) or "") for k in ("text", "label", "subtitle"))
    if isinstance(ov.get("value"), (int, float)) and not isinstance(ov.get("value"), bool):
        v = ov["value"]
        shown += " " + (str(int(v)) if float(v).is_integer() else str(v))
    nums = numbers_in(said) or numbers_in(shown)
    names = [w for w in re.findall(r"[A-Z][\w'’-]{2,}", said or shown) if w not in _STOP_NAMES and w not in _MONTHS]
    seen, out = set(), []
    for t in nums + [_norm(w) for w in names]:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out[:4]


def _token_stream(words: Sequence[dict]) -> List[Tuple[str, float, float]]:
    """(normalized token, start, end) - a number a transcript split ("1", ",040") joined back into one."""
    out: List[Tuple[str, float, float]] = []
    k = 0
    while k < len(words):
        text, a, b = words[k]["text"], float(words[k]["start"]), float(words[k]["end"])
        while k + 1 < len(words) and re.fullmatch(r"[\d.,]*\d", text.strip(",.")) \
                and re.match(r"^[,.]\d", words[k + 1]["text"]):
            k += 1
            text += words[k]["text"]
            b = float(words[k]["end"])
        out.append((_norm(text), a, b))
        k += 1
    return out


def _reanchor(ov: dict, old_start: float, guess: float, old_stream, new_stream) -> Optional[float]:
    """A look's new start on its number or name as said in the new language, keeping its offset from that word;
    None when the word is not found near where the warp puts the look."""
    for tok in _key_tokens(ov):
        olds = [(a, b) for t, a, b in old_stream if t == tok and old_start - 2.0 <= a <= old_start + 3.0]
        news = [(a, b) for t, a, b in new_stream if t == tok and guess - 3.0 <= a <= guess + 3.5]
        if not olds or not news:
            continue
        oa = min(olds, key=lambda x: abs(x[0] - old_start))[0]
        delta = max(-0.3, min(1.0, old_start - oa))
        na = min(news, key=lambda x: abs(x[0] + delta - guess))[0]
        return max(0.0, na + delta)
    return None


def retime(doc: dict, frags: Sequence[Fragment], new_seconds: float, *, min_scene: float = 0.4) -> Tuple[dict, dict]:
    """
    The document re-timed to the new narration (a deep copy; `doc` is not changed): scenes cut on their new
    lines (their words and text the new language's), looks re-anchored or warped, the sounds, the music and the
    ambience warped, the length the new narration's. Returns (new document, report).
    """
    fps = int(doc.get("fps") or 30)
    out = copy.deepcopy(doc)
    scenes = out.get("scenes") or []
    n = len(scenes)
    total = max(1, int(round(new_seconds * fps)))
    old_total = float(doc.get("durationInFrames") or 0) / fps
    starts = _scene_starts(doc, frags, total / fps, min_scene)
    old_starts = [float(sc.get("startFrame") or 0) / fps for sc in doc.get("scenes") or []]
    warp = Warp(old_starts + [old_total], starts + [total / fps])

    # Scenes: frames from the new starts, tiling 0..total exactly.
    frames = []
    for i, s in enumerate(starts):
        f = 0 if i == 0 else max(frames[-1] + 1, int(round(s * fps)))
        frames.append(f)
    if frames and frames[-1] >= total:
        total = frames[-1] + 1
    slowed = 0
    for i, sc in enumerate(scenes):
        a = frames[i]
        b = frames[i + 1] if i + 1 < n else total
        old_len = int(sc.get("durationInFrames") or 0)
        sc["startFrame"], sc["durationInFrames"] = a, b - a
        f = frags[i] if i < len(frags) else None
        if f is not None and f.spoken and f.out:
            sc["sourceText"] = f.text
            sc["text"] = f.out
            sc["words"] = [dict(w) for w in f.new_words]
        media = sc.get("media") if isinstance(sc.get("media"), dict) else {}
        clip = media.get("clipSeconds")
        if media.get("type") == "video" and isinstance(clip, (int, float)) and clip > 0:
            if (b - a) / fps > float(clip) * 1.02 and old_len / fps <= float(clip) * 1.02:
                slowed += 1             # the renderer slows a clip shorter than its scene (types.ts clipSeconds)

    old_stream = _token_stream(_flat_words(frags))
    new_stream = _token_stream([w for f in frags for w in f.new_words])

    # Looks: re-anchored on their word, else warped; each keeps at least its length when there is room.
    looks = [ov for ov in out.get("overlays") or [] if isinstance(ov, dict)]
    spans = []
    anchored = 0
    for ov in looks:
        a0 = float(ov.get("startFrame") or 0) / fps
        d0 = float(ov.get("durationInFrames") or 1) / fps
        guess = warp(a0)
        a1 = _reanchor(ov, a0, guess, old_stream, new_stream)
        if a1 is not None:
            anchored += 1
        else:
            a1 = guess
        d1 = max(d0, warp(a0 + d0) - guess)
        spans.append([a1, a1 + d1, a0, a0 + d0])
    order = sorted(range(len(looks)), key=lambda k: spans[k][0])
    for x, y in zip(order, order[1:]):
        # Two looks that did not overlap before never do now: the first ends where the next begins.
        if spans[x][3] <= spans[y][2] + 1e-6 and spans[x][1] > spans[y][0]:
            spans[x][1] = max(spans[x][0] + 0.5, spans[y][0])
    for ov, (a1, b1, a0, b0) in zip(looks, spans):
        start = max(0, min(total - 1, int(round(a1 * fps))))
        length = max(1, min(total - start, int(round((b1 - a1) * fps))))
        old_len = max(1, int(ov.get("durationInFrames") or 1))
        ov["startFrame"], ov["durationInFrames"] = start, length
        if isinstance(ov.get("points"), list):
            k = length / old_len
            for p in ov["points"]:
                if isinstance(p, dict) and isinstance(p.get("at"), (int, float)):
                    p["at"] = round(float(p["at"]) * k, 3)

    def frame(t_frames: Any) -> int:
        return max(0, min(total, int(round(warp(float(t_frames) / fps) * fps))))

    for fx in out.get("sfx") or []:
        if isinstance(fx, dict) and isinstance(fx.get("startFrame"), (int, float)):
            fx["startFrame"] = min(total - 1, frame(fx["startFrame"]))
    music = out.get("music") if isinstance(out.get("music"), dict) else None
    if music:
        for sec in music.get("sections") or []:
            if isinstance(sec, dict):
                for key in ("startFrame", "endFrame"):
                    if isinstance(sec.get(key), (int, float)):
                        sec[key] = frame(sec[key])
        for key in ("from", "to"):
            if isinstance(music.get(key), (int, float)):
                music[key] = frame(music[key])
    amb = out.get("ambience") if isinstance(out.get("ambience"), dict) else None
    for bed in (amb or {}).get("beds") or []:
        if not isinstance(bed, dict):
            continue
        a, d = float(bed.get("startFrame") or 0), float(bed.get("durationInFrames") or 0)
        na, nb = frame(a), frame(a + d)
        bed["startFrame"], bed["durationInFrames"] = na, max(1, nb - na)
        holes = []
        for h in bed.get("holes") or []:
            if isinstance(h, list) and len(h) == 2:
                holes.append([frame(a + h[0]) - na, frame(a + h[1]) - na])
        if holes:
            bed["holes"] = holes
    out["durationInFrames"] = total
    lengths = [float(sc["durationInFrames"]) / fps for sc in scenes]
    old_lengths = [float(sc.get("durationInFrames") or 0) / fps for sc in doc.get("scenes") or []]
    ratios = sorted(a / b for a, b in zip(lengths, old_lengths) if b > 0)
    rep = {"seconds": round(total / fps, 2), "sourceSeconds": round(old_total, 2),
           "stretch": round((total / fps) / old_total, 3) if old_total else None,
           "sceneStretch": {"min": round(ratios[0], 2), "median": round(ratios[len(ratios) // 2], 2),
                            "max": round(ratios[-1], 2)} if ratios else {},
           "looks": len(looks), "looksOnTheirWord": anchored, "slowedClips": slowed}
    return out, rep


# --------------------------------------------------------------------------- #
# The whole version (no saving, no render: the handler does both)
# --------------------------------------------------------------------------- #

def _presenter_doc(doc: dict) -> bool:
    if str(((doc.get("meta") or {}) if isinstance(doc.get("meta"), dict) else {}).get("videoStyle") or "") \
            in ("ai_presenter", "presenter"):
        return True
    return any(isinstance(sc, dict) and str((sc.get("media") or {}).get("source") or "") == "ai-presenter"
               for sc in doc.get("scenes") or [])


def check_input(inp: dict, doc: dict) -> str:
    """The language, after the refusals: never the source's own row, never a presenter video, never its own language."""
    project_id = str(inp.get("project_id") or "")
    source = str(inp.get("source_project_id") or "")
    if not project_id:
        raise LanguageError("A language version needs its own project (project_id).")
    if source and project_id == source:
        raise LanguageError("A language version is a new project: it never writes over the video it comes from.")
    lang = language(inp.get("language"))
    if _presenter_doc(doc):
        raise LanguageError("AI presenter videos cannot be made in another language yet: the presenter's lips "
                            "would not match the new voice.")
    if lang == source_language(doc):
        raise LanguageError(f"This video is already in {LANGUAGES[lang][0]}.")
    return lang


def _seed(inp: dict) -> int:
    h = hashlib.sha256(f"{inp.get('source_project_id')}:{inp.get('language')}".encode()).hexdigest()
    return int(h[:8], 16) % 2_000_000_000 + 1


def prepare(inp: dict, doc: dict, work: str, report: Callable, *, server: Optional[VoiceServer] = None,
            transcribe: Optional[Callable] = None, chat: Callable = None,
            download: Optional[Callable] = None) -> Tuple[dict, Dict[str, Any], str]:
    """
    The language version's document and its narration file: (new document, report, narration path). The
    document's audio is still the local file; the caller stores it and sets the link (set_narration).
    `transcribe(path, language)` -> words (whisper), `chat`, `server` and `download` are replaceable (tests).
    """
    started = time.time()
    lang = check_input(inp, doc)
    name = LANGUAGES[lang][0]
    SPENT.update(usd=0.0, calls=0)
    chat = chat or chat_json
    os.makedirs(work, exist_ok=True)
    frags = fragments_of(doc)
    groups = group_fragments(frags)
    if not groups:
        raise LanguageError("This video's timeline has no narration words to translate.")

    events.phase("translate")
    report(f"Translating the narration into {name}", 3)
    glossary = make_glossary(doc, frags, lang, chat=chat)
    tr = translate(frags, groups, lang, glossary=glossary, story=_story(doc), chat=chat,
                   parallel=int(config.LANG_TRANSLATE_PARALLEL))
    report(f"Translating the on-screen text into {name}", 12)
    screen_doc = copy.deepcopy(doc)
    screen = translate_screen_text(screen_doc, frags, lang, glossary=glossary, chat=chat)
    title_tr = ""
    source_title = str(inp.get("source_title") or strip_language_suffix(inp.get("title")) or "").strip()
    if source_title:
        data = chat(_SCREEN_PROMPT.format(lang=name),
                    {"items": [{"id": "title", "text": source_title[:200], "field": "title",
                                "context": ""}], "glossary": glossary}, kind="screen_text")
        rows = (data or {}).get("items") if isinstance(data, dict) else None
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            title_tr = str(rows[0].get("text") or "").strip()[:200]

    # The voice: one of our own voices as it was, else the narrator cloned from the narration.
    events.phase("voice")
    report(f"Voicing the {name} narration", 15)
    voice = inp.get("voice") if isinstance(inp.get("voice"), dict) and (inp["voice"].get("url") or
                                                                       inp["voice"].get("b64")) else None
    voice_kind = "same" if voice else "clone"
    sample = None
    source_audio = str(inp.get("source_audio_url") or inp.get("source_audio_path") or "")
    source_path = ""
    if source_audio:
        from . import storage
        source_path = storage.download(source_audio, os.path.join(work, "source_narration" +
                                                                   (os.path.splitext(source_audio.split("?")[0])[1]
                                                                    or ".mp3")), timeout=180)
    if voice is None:
        if not source_path:
            raise LanguageError("The narration this video was made with could not be read, so its voice "
                                "cannot be cloned.")
        sample = clone_sample(source_path, frags, work, key=f"narration-{str(inp.get('source_project_id'))[:8]}")
        if not sample:
            raise LanguageError("No clean stretch of the narration was found to clone its voice from.")
        voice = {k: sample[k] for k in ("b64", "text", "key")}
    server = server or VoiceServer()
    parts = plan_parts(frags, groups, lang)
    seed = _seed(inp)
    synthesize(parts, lang, voice, work, server, seed=seed, report=report, download=download)

    # The source's own silence around the words, and its loudness: the music and the sounds sit against the new
    # voice exactly as they sat against the old one. Measured on the source file - a timeline's meta.voiceLufs
    # may be an assumption (the Lake Mead narration: -20 "assumed", -14.9 measured); else the timeline's figure.
    words = _flat_words(frags)
    fps = float(doc.get("fps") or 30)
    old_total = float(doc.get("durationInFrames") or 0) / fps
    lead = min(1.0, max(0.1, words[0]["start"])) if words else 0.2
    tail = min(3.0, max(0.4, old_total - words[-1]["end"])) if words else 1.0
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    from . import timeline as _timeline
    source_lufs = _timeline.measure_lufs(source_path) if source_path else None
    target = source_lufs if source_lufs is not None and -40 < source_lufs < -6 else (
        float(meta.get("voiceLufs")) if isinstance(meta.get("voiceLufs"), (int, float))
        and -40 < float(meta.get("voiceLufs")) < -6 else None)
    joined = join_narration(parts, frags, work, target_lufs=target if target is not None else -16.0,
                            lead=lead, tail=tail, gap=float(config.LANG_PART_GAP_SECONDS))

    # The new words' times, and one more take of any part whisper could hardly follow.
    events.phase("align")
    report("Matching the timeline to the new voice", 48)
    transcribe = transcribe or _whisper
    heard = transcribe(joined["path"], lang)
    al = align(frags, heard, lang)
    ratios = part_ratios(parts, al["byFragment"], frags)
    weak = [p for p in parts if ratios.get(p.index, 1.0) < float(config.LANG_MIN_MATCH)]
    redone = 0
    if weak and len(weak) <= max(2, len(parts) // 3):
        print(f"[lang] parts {[p.index + 1 for p in weak]} were hard to follow "
              f"({[ratios[p.index] for p in weak]}): voiced once more", flush=True)
        synthesize(weak, lang, voice, work, server, seed=seed + 104729, report=None, download=download)
        joined = join_narration(parts, frags, work, target_lufs=target if target is not None else -16.0,
                                lead=lead, tail=tail, gap=float(config.LANG_PART_GAP_SECONDS))
        heard = transcribe(joined["path"], lang)
        al = align(frags, heard, lang)
        ratios = part_ratios(parts, al["byFragment"], frags)
        redone = len(weak)
    report("Re-timing the scenes to the new voice", 56)
    new_doc, rt = retime(doc, frags, float(joined["seconds"]))
    # The looks' translated text goes onto the re-timed looks (same order, same objects' places).
    _carry_screen_text(screen_doc, new_doc)
    gpu = server.gpu_seconds()
    if gpu:
        costs.record("lang.tts_gpu_seconds", gpu)
    info = {
        "language": lang, "languageName": name, "from": source_language(doc),
        "sourceProjectId": str(inp.get("source_project_id") or ""),
        "voice": voice_kind, **({"voiceKey": str(voice.get("key") or "")} if voice_kind == "same" else {}),
        **({"sample": {k: sample[k] for k in ("seconds", "from", "to")}} if sample else {}),
        "model": models()[0] if models() else "", "glossary": glossary,
        "fragments": sum(1 for f in frags if f.spoken), "groups": len(groups),
        "requests": tr["requests"], "retried": tr["retried"], "split": tr["split"],
        "numberIssues": tr["numberIssues"], "screenText": screen,
        "parts": len(parts), "partsRedone": redone, "ttsSeconds": round(float(joined["seconds"]), 2),
        "ttsGpuSeconds": gpu, "voiceJobs": len(server.jobs), "align": {k: al[k] for k in ("words", "matched", "ratio")},
        "partMatch": ratios, "retime": rt, "translatedTitle": title_tr,
        "llmUsd": round(SPENT["usd"], 5), "llmCalls": SPENT["calls"],
        "lufs": joined.get("lufs"), "sourceLufs": source_lufs,
        "whisper": config.LANG_WHISPER_MODEL or config.WHISPER_MODEL, "seconds": round(time.time() - started, 1),
    }
    return new_doc, info, joined["path"]


def _carry_screen_text(translated: dict, target: dict) -> None:
    """The translated display text from a copy of the source document onto the re-timed one (same looks, same order)."""
    src = screen_texts(translated)
    dst = screen_texts(target)
    by_id = {it["id"]: it for it in src}
    for it in dst:
        got = by_id.get(it["id"])
        if got is not None and got["text"] != it["text"]:
            it["set"](got["text"])
    # A highlight the translation dropped is empty on the copy, and an empty field is not "display text": drop it.
    for key, ov in _looks(translated):
        if isinstance(ov, dict) and ov.get("highlight") == "":
            other = _look_at(target, key)
            if isinstance(other, dict):
                other["highlight"] = ""


def _looks(doc: dict):
    for n, ov in enumerate(doc.get("overlays") or []):
        yield ("o", n), ov
    for n, sc in enumerate(doc.get("scenes") or []):
        if isinstance(sc, dict) and isinstance(sc.get("animation"), dict):
            yield ("s", n), sc["animation"]


def _look_at(doc: dict, key: Tuple[str, int]):
    kind, n = key
    if kind == "o":
        ovs = doc.get("overlays") or []
        return ovs[n] if n < len(ovs) else None
    scs = doc.get("scenes") or []
    return scs[n].get("animation") if n < len(scs) and isinstance(scs[n], dict) else None


_ALIGN_MODEL: Dict[str, Any] = {}
_ALIGN_LOCK = threading.Lock()


def _whisper(path: str, lang: str):
    """
    What the new narration says, word by word with times. LANG_WHISPER_MODEL ("small"): the worker's own "base"
    hears a clean Spanish narration at 0.89 of its words (the 2026-10-09 proof: "granjas" -> "Grandcas",
    "luego" -> "Lego") where large-v3-turbo heard 0.99 - fewer anchors for the scene cuts and false alarms for
    the part check, worse still in Chinese or Japanese. Its own model, loaded once beside the worker's.
    """
    from . import transcribe
    name = config.LANG_WHISPER_MODEL or config.WHISPER_MODEL
    if name == config.WHISPER_MODEL:
        return transcribe.transcribe_words(path, language=lang)
    with _ALIGN_LOCK:
        model = _ALIGN_MODEL.get(name)
        if model is None:
            from faster_whisper import WhisperModel
            device = config.WHISPER_DEVICE
            if device == "auto":
                try:
                    import torch  # noqa: F401
                    device = "cuda" if torch.cuda.is_available() else "cpu"
                except Exception:  # noqa: BLE001
                    device = "cpu"
            model = WhisperModel(name, device=device, compute_type="float16" if device == "cuda" else "int8")
            _ALIGN_MODEL.clear()
            _ALIGN_MODEL[name] = model
    segments, _info = model.transcribe(path, language=lang, word_timestamps=True, vad_filter=True, beam_size=5)
    return [transcribe.Word(text=(w.word or "").strip(), start=float(w.start), end=float(w.end))
            for seg in segments for w in (seg.words or []) if (w.word or "").strip()]


def finish_doc(doc: dict, info: dict, audio_url: str, *, captions: Optional[bool] = None,
               lufs: Optional[float] = None) -> dict:
    """The version's document made final: its narration link, its captions, its meta (no report of the source's
    render: the version's own render writes its own)."""
    doc["audio"] = {**(doc.get("audio") if isinstance(doc.get("audio"), dict) else {}), "url": audio_url}
    if captions is not None and isinstance(doc.get("captions"), dict):
        doc["captions"]["enabled"] = bool(captions)
    meta = doc.setdefault("meta", {})
    for stale in ("quality", "review", "reportFor", "renderStale", "audioBucket", "publishedMedia", "costs",
                  "events", "aiUsage"):
        meta.pop(stale, None)
    meta["audioSource"] = audio_url
    if isinstance(lufs, (int, float)) and -60 < float(lufs) < 0:
        meta["voiceLufs"] = round(float(lufs), 1)
        meta["voiceLufsSource"] = "measured"
    fps = float(doc.get("fps") or 30)
    seconds = float(doc.get("durationInFrames") or 0) / fps
    meta["sceneCount"] = len(doc.get("scenes") or [])
    meta["overlayCount"] = len(doc.get("overlays") or [])
    meta["cutsPerMinute"] = round(len(doc.get("scenes") or []) / max(seconds / 60.0, 0.01), 1)
    meta["languageVersion"] = info
    if info.get("numberIssues"):
        meta.setdefault("warnings", []).append(
            f"{len(info['numberIssues'])} line(s) of the translation state a number differently: check them "
            "in the editor (meta.languageVersion.numberIssues).")
    return doc


def narration_key(project_id: str, lang: str, given: str = "") -> str:
    """Where the new narration goes on R2: the app's planned key when it is the project's own, else a new one."""
    given = str(given or "").strip()
    if given.startswith(f"projects/{project_id}/") and ".." not in given and given.endswith(".mp3"):
        return given
    return f"projects/{project_id}/narration-{lang}-{uuid.uuid4().hex[:12]}.mp3"


def tts_ready() -> Dict[str, Any]:
    """For the health check: whether this worker may call the voice endpoint (no network call)."""
    return {"endpoint": config.LANG_TTS_ENDPOINT, "key": bool(config.LANG_TTS_API_KEY),
            "openrouter": bool(_openrouter_key()), "model": config.LANG_TRANSLATE_MODEL,
            "languages": sorted(LANGUAGES)}
