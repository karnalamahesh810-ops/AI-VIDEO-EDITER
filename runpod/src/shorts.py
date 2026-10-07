"""
Shorts: 9:16 videos of 30-60 s made from a finished long video's own timeline (the owner, 2026-10-07:
"Shorts maker ... pick the best 3-5 moments, make 9:16 vertical Shorts").

A Short is not a crop of the finished MP4. It is drawn again, from the same document the long video was
rendered from (its clips, pictures, graphics, grade, transitions, sounds and narration):

  * the moment: the narration as sentences, every run of whole sentences 30-60 s long scored as a
    stand-alone Short (a strong first line - a number, a superlative, stakes, a question - that does not
    lean on what came before; an ending that lands; facts, clips and graphics inside; no "subscribe"), the
    best few that do not overlap picked (pick / candidates). Deterministic: no AI, no cost. The app has the
    same picker in TypeScript (src/lib/shorts/pick.ts) for its instant suggestions and re-picks, and sends
    the chosen moments; this one is used when a job names none.
  * the picture: the long video's frames drawn on a 16:9 "stage" (remotion/src/short/Short.tsx renders
    Main inside it), framed per shot (plan_framing): CROP - the stage scaled to fill the 9:16 frame, the
    window on the subject (faces first, else the main object: src/reframe.py's detectors on the shot's own
    file); FIT - the whole stage in a band over a blurred copy of the shot (a graphic on screen, a news
    clip's logo or chyron, burned-in text, a subject wider than the window: nothing is cut off); NATIVE -
    a vertical source drawn straight into the frame. A graphic appearing mid-shot eases the framing out to
    FIT over 0.4 s and back after it.
  * the words: captions of the narration's own word timings, two short lines at a time in clean white
    type with the spoken word brighter (never the big yellow outlined words the owner rejected,
    2026-10-05), and a hook line at the top for the first seconds (a short headline from the moment
    itself, a gold kicker over it).
  * the sound: the narration's slice, the long video's music bed at the owner's level, its transition and
    look sounds; loudness to config.LOUDNESS_TARGET_LUFS like every finished video.

run() is the worker action "shorts" (handler.py). It never writes the project row: its result goes back
in the job's own output and the app's video-shorts edge function stores it (video_shorts table). Files go
to R2 under deterministic keys, projects/<project>/shorts/<short_id>.mp4 / .jpg, so the app can find a
finished Short even after RunPod has forgotten the job.
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------- #
# Settings (the environment can change them; none of them is in config.py)
# --------------------------------------------------------------------------- #

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


SHORT_FPS = int(_env_float("SHORTS_FPS", 30))
SHORT_W, SHORT_H = 1080, 1920
STAGE_W, STAGE_H = 1920, 1080
MIN_SECONDS = _env_float("SHORTS_MIN_SECONDS", 30.0)
MAX_SECONDS = _env_float("SHORTS_MAX_SECONDS", 60.0)
# A moment the app sends may be shorter (a re-pick) but never longer than this.
HARD_MIN_SECONDS, HARD_MAX_SECONDS = 15.0, 62.0
DEFAULT_COUNT = 4
MAX_COUNT = 5
HOOK_SECONDS = _env_float("SHORTS_HOOK_SECONDS", 3.2)
# Breath kept before the first word and after the last one.
LEAD_IN, TAIL_OUT = 0.12, 0.35
# Seconds the whole analysis of one Short's shots may take (downloads excluded).
ANALYSE_SECONDS = _env_float("SHORTS_ANALYSE_SECONDS", 90.0)
ACCENT = "#F2B544"
# The crop window's width as a share of the stage when the 16:9 stage fills the 9:16 frame.
WINDOW = (SHORT_W / SHORT_H) / (STAGE_W / STAGE_H)          # 0.3164
# Frames a mid-shot change of framing takes (a graphic coming in: the picture eases out to show it).
EASE_FRAMES = 12

# --------------------------------------------------------------------------- #
# The narration as words and sentences
# --------------------------------------------------------------------------- #

_ABBREV = {
    "mr.", "mrs.", "ms.", "dr.", "st.", "mt.", "ft.", "jr.", "sr.", "vs.", "etc.", "inc.", "co.", "corp.",
    "ltd.", "u.s.", "u.k.", "e.g.", "i.e.", "a.m.", "p.m.", "no.", "approx.", "dept.", "gov.", "gen.", "sen.",
    "rep.", "jan.", "feb.", "mar.", "apr.", "aug.", "sept.", "sep.", "oct.", "nov.", "dec.", "lt.", "col.",
    "capt.", "sgt.", "prof.", "ave.", "blvd.", "rd.", "mph.", "approx.",
}
_CLOSERS = "\"'”’)]"


def _ends_sentence(text: str, nxt: str = "") -> bool:
    """Does this word end its sentence? (Abbreviations, initials and a lower-case next word say no.)"""
    t = (text or "").strip().rstrip(_CLOSERS)
    if not t or t[-1] not in ".!?":
        return False
    if t.endswith(("!", "?")):
        return True
    low = t.lower()
    if low in _ABBREV or re.fullmatch(r"(?:[a-z]\.){1,3}", low):
        return False
    nxt = (nxt or "").lstrip(_CLOSERS + "“‘(")
    return not (nxt[:1].islower())


def words_of(doc: dict) -> List[dict]:
    """Every spoken word in order: {text, start, end, scene} (seconds of the narration, scene index)."""
    out: List[dict] = []
    scenes = sorted(enumerate(doc.get("scenes") or []), key=lambda p: float(p[1].get("startFrame") or 0))
    for idx, sc in scenes:
        for w in sc.get("words") or []:
            try:
                start, end = float(w.get("start")), float(w.get("end"))
            except (TypeError, ValueError):
                continue
            text = str(w.get("text") or "").strip()
            if not text or end < start:
                continue
            out.append({"text": text, "start": start, "end": end, "scene": idx})
    out.sort(key=lambda w: (w["start"], w["end"]))
    # Whisper splits "10:19" as "10" + ".19", "1,000" as "1" + ",000" and "record-setting" as "record" +
    # "-setting": such a tail goes back on the word before it.
    merged: List[dict] = []
    for w in out:
        prev = merged[-1]["text"] if merged else ""
        if merged and ((re.fullmatch(r"[.:,]\d+[.,!?]?", w["text"]) and re.search(r"\d$", prev))
                       or (re.fullmatch(r"-[A-Za-z][\w'-]*[.,!?]?", w["text"]) and re.search(r"[A-Za-z]$", prev))):
            merged[-1] = {**merged[-1], "text": prev + w["text"], "end": w["end"]}
            continue
        merged.append(dict(w))
    return merged


def sentences_of(doc: dict, words: Optional[List[dict]] = None) -> List[dict]:
    """
    The narration as sentences: {index, start, end, text, w0, w1} (w0..w1 the words, inclusive). A long run
    with no full stop is cut at its longest pause after 40 words, so no "sentence" outgrows a Short.
    """
    words = words if words is not None else words_of(doc)
    out: List[dict] = []
    begin = 0
    for i, w in enumerate(words):
        nxt = words[i + 1]["text"] if i + 1 < len(words) else ""
        long_run = i - begin >= 40 and nxt and (words[i + 1]["start"] - w["end"]) >= 0.45
        if _ends_sentence(w["text"], nxt) or i == len(words) - 1 or long_run:
            run = words[begin:i + 1]
            out.append({"index": len(out), "start": run[0]["start"], "end": run[-1]["end"],
                        "text": " ".join(x["text"] for x in run), "w0": begin, "w1": i})
            begin = i + 1
    return out


# --------------------------------------------------------------------------- #
# What makes a line a hook
# --------------------------------------------------------------------------- #

_NUMBER = re.compile(r"\d|\b(?:hundreds?|thousands?|millions?|billions?|trillions?|percent|per cent|dozens?|"
                     r"twice|triple[ds]?|double[ds]?|half)\b|%", re.I)
_SUPER_STRONG = re.compile(r"\b(?:\w+est|record|records|historic|unprecedented|never|nobody|no one|nothing|"
                           r"first-ever|all-time)\b", re.I)
_SUPER_WEAK = re.compile(r"\b(?:most|every|only|first|last|entire|whole|ever)\b", re.I)
_NOT_SUPER = {"best", "rest", "test", "west", "east", "nest", "chest", "forest", "interest", "honest", "modest",
              "request", "suggest", "protest", "guest", "quest", "harvest", "manifest", "invest", "contest", "pest",
              "arrest", "crest", "vest", "zest", "lest", "digest", "earnest", "latest", "midwest", "northwest",
              "southwest", "northeast", "southeast", "fest", "conquest", "dearest", "behest", "inquest",
              "unrest", "priest"}
_STAKES = re.compile(
    r"\b(?:explod\w*|explosion\w*|erupt\w*|collaps\w*|vanish\w*|destroy\w*|kill\w*|died|dead|death\w*|deadly|"
    r"disappear\w*|warn\w*|danger\w*|crisis|emergency|disaster\w*|catastroph\w*|threat\w*|risk\w*|flood\w*|"
    r"wildfire\w*|fires?|drought\w*|toxic|poison\w*|hidden|secret\w*|myster\w*|shock\w*|discover\w*|"
    r"reveal\w*|buried|sinking|sank|dried|drying|running out|shut down|banned|broke|cracks?|cracking|boiling|"
    r"blast\w*|evacuat\w*|trapped|panic\w*|terrif\w*|massive|huge|giant|enormous|collapse|failing|fail\w*|"
    r"lost|losing|vanishing|suddenly|without warning|nobody knew|no warning|blew|blown|burst|ripped|tore|"
    r"slammed|struck|shattered|splintered|snapped|swallowed|plunged|soared|spiked|surged|skyrocketed|"
    r"crashed|plummeted|wiped out)\b", re.I)
_QUESTION_OPEN = re.compile(r"^(?:why|how|what|who|where|when|which|is|are|can|could|would|should|did|does|do)\b",
                            re.I)
_YOU = re.compile(r"\b(?:you|your|you're|you'd|you'll)\b", re.I)
_DANGLING_CONJ = {"and", "but", "so", "because", "which", "who", "whom", "whose", "also", "then", "meanwhile",
                  "however", "still", "yet", "or", "nor", "plus", "instead", "otherwise", "therefore", "thus",
                  "hence", "besides", "moreover", "furthermore", "anyway", "again", "although", "though",
                  "while", "whereas", "unlike"}
_DANGLING_PRON = {"he", "she", "it", "they", "them", "his", "her", "its", "their", "this", "that", "these",
                  "those", "him", "it's", "that's", "they're", "he's", "she's"}
_BACKREF = re.compile(r"\b(?:that's why|that is why|which is why|as we|as i (?:said|mentioned)|remember\b|earlier|"
                      r"we saw|we've seen|we'll see|later in|in this video|today we|in the next|the second\b|"
                      r"the third\b|another\b|the same\b|but first|in other words|for example|as mentioned|"
                      r"this one|that one|back then|at that point|by then|the next day)", re.I)
_SETUP_END = re.compile(r"(?::\s*$)|\b(?:here's why|here is why|let's|let us|we'll|coming up|but first|stay with|"
                        r"find out|keep watching|in a moment|next,|here's how|here's what)\b", re.I)
_CTA = re.compile(r"\b(?:subscribe\w*|like and|comment\w*|thanks for watching|thank you for watching|"
                  r"link in|description below|sponsor\w*|patreon|notification\w*|bell icon|let me know|"
                  r"see you (?:next|in)|hit the like)\b", re.I)
_SENT_START_SKIP = {"the", "a", "an", "i", "in", "on", "at", "for", "to", "of", "by", "with", "from", "as"}


def _first_word(text: str) -> str:
    m = re.match(r"[\s\"'“‘(]*([A-Za-z][A-Za-z'’]*)", text or "")
    return (m.group(1) if m else "").lower().replace("’", "'")


def _superlatives(text: str) -> Tuple[int, int]:
    strong = [m.group(0).lower() for m in _SUPER_STRONG.finditer(text or "")]
    strong = [s for s in strong if s not in _NOT_SUPER and not (s.endswith("est") and len(s) <= 4)]
    return len(strong), len(_SUPER_WEAK.findall(text or ""))


_RUN_BREAK = {"him", "her", "so", "much", "very", "just", "again", "into", "is", "are", "was", "were", "isn't",
              "aren't", "wasn't", "can't", "won't", "don't", "doesn't", "didn't", "and", "or", "of", "the", "a",
              "an", "to", "for", "with", "at", "in", "on", "by", "from", "about", "after", "before", "why", "how",
              "what", "who", "when", "where", "which", "that", "this", "these", "those", "it", "its", "he", "she",
              "they", "we", "you", "i", "no", "not", "but", "then", "now", "there", "here"}


def _entities(text: str, known: Tuple[str, ...] = ()) -> List[str]:
    """
    Names in a sentence: runs of capitalised words not at its start (a possessive ends a run: "Lake Mead's
    newest" -> "Lake Mead"; a shouted word or a small word never joins one), plus the story's own names.
    """
    found: List[str] = []
    low = (text or "").lower()
    for name in known:
        if name and re.search(r"\b" + re.escape(name.lower()) + r"\b", low):
            found.append(name)
    tokens = re.findall(r"[A-Za-z][A-Za-z'’.\-]*", text or "")
    run: List[str] = []

    def close():
        if run:
            found.append(" ".join(run))
        run.clear()

    for k, tok in enumerate(tokens):
        bare = tok.strip(".'’")
        plain = bare.lower().replace("’", "'")
        possessive = bool(re.search(r"['’]s$", bare))
        if possessive:
            bare = re.sub(r"['’]s$", "", bare)
        shout = bare.isupper() and len(bare) > 4
        cap = (bare[:1].isupper() and not bare.isupper()) or (bare.isupper() and 2 <= len(bare) <= 4)
        contraction = "'" in plain and not possessive
        if cap and not shout and not contraction and k > 0 and plain not in _RUN_BREAK \
                and plain not in _SENT_START_SKIP:
            run.append(bare)
            if possessive:
                close()
        else:
            close()
    close()
    seen, out = set(), []
    for f in found:
        key = f.lower()
        if key not in seen and len(f) > 1:
            seen.add(key)
            out.append(f)
    return out


def line_features(text: str, known: Tuple[str, ...] = ()) -> dict:
    """What a sentence offers as a Short's opening line or ending."""
    first = _first_word(text)
    strong, weak = _superlatives(text)
    n_words = len(re.findall(r"[A-Za-z0-9']+", text or ""))
    return {
        "number": bool(_NUMBER.search(text or "")),
        "superStrong": strong, "superWeak": weak,
        "stakes": len(_STAKES.findall(text or "")),
        "question": (text or "").rstrip(_CLOSERS).endswith("?") or bool(_QUESTION_OPEN.match(text or "")),
        "you": bool(_YOU.search(text or "")),
        "words": n_words,
        "danglingConj": first in _DANGLING_CONJ,
        "danglingPron": first in _DANGLING_PRON,
        "backref": bool(_BACKREF.search(text or "")),
        "setupEnd": bool(_SETUP_END.search(text or "")),
        "cta": bool(_CTA.search(text or "")),
        "entities": len(_entities(text, known)),
    }


def opener_score(f: dict) -> float:
    """0..1: how well a sentence opens a Short on its own."""
    s = 0.3
    s += 0.32 if f["number"] else 0.0
    s += min(0.28, 0.2 * f["superStrong"] + 0.06 * f["superWeak"])
    s += min(0.24, 0.12 * f["stakes"])
    s += 0.15 if f["question"] else 0.0
    s += 0.08 if f["you"] else 0.0
    s += 0.08 if f["entities"] else 0.0
    s += 0.1 if 5 <= f["words"] <= 14 else (-0.15 if f["words"] > 28 else 0.0)
    s -= 0.5 if f["danglingConj"] else 0.0
    s -= 0.32 if f["danglingPron"] else 0.0
    s -= 0.28 if f["backref"] else 0.0
    s -= 0.5 if f["cta"] else 0.0
    return max(0.0, min(1.0, s))


# --------------------------------------------------------------------------- #
# Scoring a run of sentences as a Short
# --------------------------------------------------------------------------- #

class _Ctx:
    """One document, read once for scoring: its sentences, their features, its scenes and graphics."""

    def __init__(self, doc: dict):
        self.doc = doc
        self.fps = float(doc.get("fps") or 30) or 30.0
        self.words = words_of(doc)
        self.sents = sentences_of(doc, self.words)
        story = ((doc.get("meta") or {}).get("story") or {}) if isinstance(doc.get("meta"), dict) else {}
        names = [str(x) for x in (story.get("places") or []) + (story.get("people") or []) if isinstance(x, str)]
        self.known: Tuple[str, ...] = tuple(n for n in names if 2 < len(n) < 40)
        self.feat = [line_features(s["text"], self.known) for s in self.sents]
        self.total = (self.words[-1]["end"] if self.words else 0.0)
        self.scenes = []
        for sc in doc.get("scenes") or []:
            a = float(sc.get("startFrame") or 0) / self.fps
            b = a + float(sc.get("durationInFrames") or 0) / self.fps
            self.scenes.append((a, b, sc))
        self.overlays = []
        for ov in doc.get("overlays") or []:
            a = float(ov.get("startFrame") or 0) / self.fps
            self.overlays.append((a, a + float(ov.get("durationInFrames") or 0) / self.fps, ov))
        self.title = str(doc.get("title") or "")
        self._subject: Optional[str] = None

    def subject(self) -> str:
        """
        What the whole video is about, as a short name: the name its narration and title use most (the
        title's names count three times) - "Yellowstone", "Lake Mead", "Barack Obama"; "" when none stands out.
        """
        if self._subject is None:
            counts: Dict[str, float] = {}
            shown: Dict[str, str] = {}
            for s in self.sents:
                for name in _names_in(s["text"], self.known):
                    if _word_count(name) > 3:
                        continue
                    key = name.lower()
                    counts[key] = counts.get(key, 0.0) + 1.0
                    shown.setdefault(key, name)
            # "Barack Obama" also collects the narration's every "Obama" and "Barack".
            score = dict(counts)
            for key in counts:
                parts = key.split()
                if len(parts) > 1:
                    score[key] += 0.6 * sum(counts.get(p, 0.0) for p in parts)
            title = _title_hook(self.title)
            subject = ""
            # The title says what the video is about: its first name the narration also says is the subject
            # (counted in the narration's own words, at a sentence's start too: "Barack Obama wrote ...").
            text = " ".join(s["text"] for s in self.sents)
            for name in (_names_in("x " + title, self.known) if title else []):
                full = len(re.findall(r"\b" + re.escape(name) + r"\b", text, flags=re.I))
                said = float(full)
                parts = [p for p in name.split() if p.lower() not in _NOT_KICKER and len(p) > 2]
                if len(name.split()) > 1:
                    # "Obama" on its own counts a little too (not the times it is part of "Barack Obama").
                    alone = sum(len(re.findall(r"\b" + re.escape(p) + r"\b", text, flags=re.I)) - full for p in parts)
                    said += 0.6 * max(0, alone)
                if said >= 2:
                    subject = shown.get(name.lower(), name)
                    break
            if not subject and score:
                best = max(score, key=lambda k: (score[k], len(k.split())))
                subject = shown[best] if score[best] >= 3 else ""
            self._subject = subject
        return self._subject

    def window(self, i: int, j: int) -> Tuple[float, float]:
        """The padded start and end (seconds) of sentences i..j."""
        s0, s1 = self.sents[i], self.sents[j]
        prev_end = self.words[s0["w0"] - 1]["end"] if s0["w0"] > 0 else 0.0
        next_start = self.words[s1["w1"] + 1]["start"] if s1["w1"] + 1 < len(self.words) else s1["end"] + 1.0
        start = max(prev_end + 0.03, s0["start"] - LEAD_IN, 0.0)
        end = min(next_start - 0.03, s1["end"] + TAIL_OUT)
        return round(start, 3), round(max(end, s1["end"]), 3)


def _visuals(ctx: _Ctx, t0: float, t1: float) -> dict:
    """What is on screen between t0 and t1: clip share, graphics, empty or AI shots, repeats, quality."""
    span = max(0.1, t1 - t0)
    clip = empty = generated = 0.0
    urls: List[str] = []
    quality: List[float] = []
    n = 0
    for a, b, sc in ctx.scenes:
        o = min(b, t1) - max(a, t0)
        if o <= 0:
            continue
        n += 1
        m = sc.get("media") or {}
        t = m.get("type")
        url = str(m.get("url") or "")
        if not url or t == "color":
            empty += o
        elif t == "video":
            clip += o
        if m.get("generated") or m.get("source") == "generated":
            generated += o
        if url:
            urls.append(url)
        q = m.get("qualityScore")
        if isinstance(q, (int, float)):
            quality.append(float(q))
    graphics = sum(1 for a, b, ov in ctx.overlays if t0 - 0.5 <= a < t1 - 1.0)
    animation = sum(1 for a, b, sc in ctx.scenes
                    if min(b, t1) - max(a, t0) > 0 and (sc.get("media") or {}).get("type") == "animation")
    return {"clipShare": clip / span, "emptyShare": empty / span, "generatedShare": generated / span,
            "graphics": graphics + animation, "scenes": n, "distinct": len(set(urls)),
            "repeats": max(0, len(urls) - len(set(urls))),
            "quality": (sum(quality) / len(quality)) if quality else None}


def score_window(ctx: _Ctx, i: int, j: int) -> Tuple[float, List[str], dict]:
    """(0-100 score, reason chips, parts) of sentences i..j as one Short."""
    t0, t1 = ctx.window(i, j)
    dur = t1 - t0
    f0 = ctx.feat[i]
    hook = opener_score(f0)
    if j > i:
        # A punchy second line lifts a plain first one a little ("It blew open. Nobody was warned.").
        hook = min(1.0, hook + 0.15 * max(0.0, opener_score(ctx.feat[i + 1]) - 0.55))
    fl = ctx.feat[j]
    end = 0.55
    end += 0.12 if fl["number"] else 0.0
    end += 0.1 if (fl["superStrong"] or fl["stakes"]) else 0.0
    end += 0.12 if fl["question"] else 0.0
    end -= 0.42 if fl["setupEnd"] else 0.0
    if j + 1 < len(ctx.sents):
        nxt = ctx.feat[j + 1]
        # The thought goes on in the next sentence: this ending would be cut mid-argument.
        end -= 0.18 if (nxt["danglingConj"] or nxt["backref"]) else 0.0
    end = max(0.0, min(1.0, end))
    minutes = max(0.25, dur / 60.0)
    feats = ctx.feat[i:j + 1]
    numbers = sum(1 for f in feats if f["number"])
    stakes = sum(f["stakes"] for f in feats)
    names = sum(f["entities"] for f in feats)
    density = (0.4 * min(1.0, numbers / (3.0 * minutes)) + 0.3 * min(1.0, stakes / (4.0 * minutes))
               + 0.3 * min(1.0, names / (6.0 * minutes)))
    vis = _visuals(ctx, t0, t1)
    visual = (0.45 * vis["clipShare"] + 0.2 * min(1.0, vis["graphics"] / 2.0)
              + 0.15 * (vis["distinct"] / max(1, vis["scenes"]))
              + 0.2 * (vis["quality"] if vis["quality"] is not None else 0.5)
              - 0.3 * vis["emptyShare"] - 0.15 * vis["generatedShare"])
    visual = max(0.0, min(1.0, visual))
    if dur < 38:
        fit = 0.75 + 0.25 * max(0.0, dur - 30.0) / 8.0
    elif dur <= 55:
        fit = 1.0
    else:
        fit = max(0.6, 1.0 - 0.1 * (dur - 55.0) / 5.0)
    cta = any(f["cta"] for f in feats)
    total = 0.38 * hook + 0.14 * end + 0.2 * density + 0.18 * visual + 0.1 * fit
    total -= 0.35 if cta else 0.0
    # The very end of a video is its outro: thanks, subscribe, the next video.
    if ctx.total and t0 > 0.92 * ctx.total:
        total -= 0.15
    score = round(100.0 * max(0.0, min(1.0, total)), 1)
    reasons: List[str] = []
    if f0["number"]:
        reasons.append("Opens with a number")
    elif f0["question"]:
        reasons.append("Opens with a question")
    elif hook >= 0.6:
        reasons.append("Strong first line")
    if hook >= 0.55 and not (f0["danglingConj"] or f0["danglingPron"] or f0["backref"]):
        reasons.append("Stands on its own")
    clips = sum(1 for a, b, sc in ctx.scenes
                if min(b, t1) - max(a, t0) > 0.5 and (sc.get("media") or {}).get("type") == "video")
    if clips >= 3 and vis["clipShare"] >= 0.5:
        reasons.append(f"{clips} clips")
    if vis["graphics"]:
        reasons.append("Graphics" if vis["graphics"] > 1 else "A graphic")
    if numbers >= 3:
        reasons.append("Packed with facts")
    if fl["question"] and end >= 0.6:
        reasons.append("Ends on a question")
    elif end >= 0.7:
        reasons.append("Ends on a payoff")
    parts = {"hook": round(hook, 3), "end": round(end, 3), "density": round(density, 3),
             "visual": round(visual, 3), "fit": round(fit, 3), "cta": cta, "seconds": round(dur, 2)}
    return score, reasons[:4], parts


def _windows(ctx: _Ctx, min_s: float, max_s: float):
    """Every run of whole sentences whose padded length is within [min_s, max_s]."""
    n = len(ctx.sents)
    for i in range(n):
        for j in range(i, n):
            t0, t1 = ctx.window(i, j)
            d = t1 - t0
            if d > max_s:
                break
            if d >= min_s:
                yield i, j


def _overlaps(a: dict, b: dict) -> bool:
    return a["start"] < b["end"] and b["start"] < a["end"]


def candidates(doc: dict, min_s: float = MIN_SECONDS, max_s: float = MAX_SECONDS, limit: int = 12,
               ctx: Optional[_Ctx] = None) -> List[dict]:
    """Up to `limit` non-overlapping moments, best first (each a full moment: see moment())."""
    ctx = ctx or _Ctx(doc)
    scored = []
    for i, j in _windows(ctx, min_s, max_s):
        score, reasons, parts = score_window(ctx, i, j)
        scored.append((score, i, j, reasons, parts))
    # Equal scores: the earlier, then the shorter one.
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))
    out: List[dict] = []
    for score, i, j, reasons, parts in scored:
        t0, t1 = ctx.window(i, j)
        cand = {"start": t0, "end": t1}
        if any(_overlaps(cand, o) for o in out):
            continue
        out.append(moment(ctx, i, j, score=score, reasons=reasons, parts=parts))
        if len(out) >= limit:
            break
    return out


def pick(doc: dict, count: int = DEFAULT_COUNT, min_s: float = MIN_SECONDS, max_s: float = MAX_SECONDS) -> List[dict]:
    """The best `count` (1-5) non-overlapping moments, best first."""
    count = max(1, min(MAX_COUNT, int(count or DEFAULT_COUNT)))
    return candidates(doc, min_s, max_s, limit=count)


# --------------------------------------------------------------------------- #
# The hook line, the kicker and a title
# --------------------------------------------------------------------------- #

_LEAD_JOIN = re.compile(r"^(?:and|but|so|now|then|and so|but then|still|yet|plus|also)[,\s]+", re.I)
_SHOUT = re.compile(r"\b[A-Z]{3,}\b")


def _clean_line(text: str) -> str:
    """A sentence as a headline: no leading 'And', no trailing full stop, single spaces."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    t = _LEAD_JOIN.sub("", t)
    t = t.rstrip()
    while t.endswith((".", ",", ";", ":")) and not t.endswith("..."):
        t = t[:-1].rstrip()
    t = t.strip("\"“”")
    return (t[:1].upper() + t[1:]) if t else t


def _clauses(text: str) -> List[str]:
    parts = re.split(r"(?<=[,;:—])\s+|\s+[—–-]\s+", text or "")
    return [p.strip(" ,;:—–-") for p in parts if p.strip(" ,;:—–-")]


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9'’%$]+", text or ""))


def _fit_line(text: str, max_words: int = 12, max_chars: int = 70) -> str:
    """The sentence, or its first clause that reads on its own, within the limits; "" when none does."""
    opts = _line_options(text, max_words, max_chars)
    return opts[0] if opts else ""


def _line_options(text: str, max_words: int = 12, max_chars: int = 70) -> List[str]:
    """
    The headlines a sentence offers within the limits: itself, and any clause of it that can stand alone -
    "At 10:19 on a Tuesday morning, the ground at Biscuit Basin blew open" offers "The ground at Biscuit
    Basin blew open" (never a clause that starts on a preposition, a conjunction or a pronoun).
    """
    t = _clean_line(text)
    out: List[str] = []
    if 4 <= _word_count(t) <= max_words and len(t) <= max_chars:
        out.append(t)
    clauses = _clauses(t)
    if len(clauses) > 1:
        for cl in clauses:
            cl = _clean_line(cl)
            w0 = _first_word(cl)
            if not (4 <= _word_count(cl) <= max_words and len(cl) <= max_chars):
                continue
            if w0 in _PREPOSITION_OPEN or w0 in _DANGLING_CONJ or w0 in _DANGLING_PRON:
                continue
            if cl not in out:
                out.append(cl)
    return out


def _title_hook(title: str) -> str:
    """The long video's title as a hook: the part before a dash or a bar, not shouted."""
    t = re.sub(r"[\U0001F000-\U0001FFFF☀-➿]", "", title or "").strip()
    t = re.split(r"\s+[—–|:-]\s+|\s*\|\s*", t)[0].strip()
    t = _SHOUT.sub(lambda m: m.group(0).capitalize() if m.group(0) not in ("USA", "NASA", "NOAA", "USGS", "FBI",
                                                                           "CIA", "UK", "EU", "UN") else m.group(0), t)
    return t[:70].rstrip()


_PREPOSITION_OPEN = {"at", "in", "on", "for", "with", "by", "from", "during", "after", "before", "since", "within",
                     "under", "over", "into", "across", "around", "about", "near", "inside", "outside", "between",
                     "through", "toward", "towards", "until", "of", "to", "as", "like", "if", "when", "once"}


_QUESTION_WORDS = {"why", "how", "what", "who", "where", "when", "which", "is", "are", "can", "could", "would",
                   "should", "did", "does", "do", "there"}


def hook_score(line: str, known: Tuple[str, ...] = (), first: bool = False, clause: bool = False) -> float:
    """How well a short line reads as a Short's headline (opener_score, stricter about how it starts)."""
    f = line_features(line, known)
    s = opener_score(f)
    w0 = _first_word(line)
    if f["danglingPron"] or f["backref"]:
        s -= 0.4
    if w0 in _PREPOSITION_OPEN:
        s -= 0.22                     # an adverbial opener ("At 10:19 on a Tuesday") is not a headline
    if f["number"]:
        s += 0.08
    if f["question"]:
        s += 0.05
    if first:
        s -= 0.03                     # a later line teases what is coming (a little better than a repeat)
    if f["words"] < 4:
        s -= 0.3
    if clause:
        s -= 0.05                     # a whole sentence reads better than a piece of one
    w = re.findall(r"[A-Za-z']+", line.lower())
    if len(w) > 1 and w[1] in ("it", "them", "him", "us", "out", "up", "off") and w0 not in _QUESTION_WORDS:
        s -= 0.3                      # "Blast it out ...": a fragment or an order, not a headline
    return s


def hook_for(ctx: _Ctx, i: int, j: int) -> Tuple[str, str, str]:
    """
    (hook, kicker, title) of sentences i..j. The hook is the moment's own most striking short line - a
    later one preferred (a promise the Short then keeps, never the very words the viewer is hearing),
    a whole sentence that starts on its subject, without a pronoun or "And" leaning on what came before;
    else the long video's title. The kicker names the place or subject the moment is about.
    """
    best, best_score = "", -1.0
    for k in range(i, min(j, i + 8) + 1):
        raw = ctx.sents[k]["text"].strip()
        if not raw[:1].isupper() and not raw[:1].isdigit():
            continue                  # a transcript fragment ("blast it out ...")
        whole = _clean_line(raw)
        for line in _line_options(raw):
            s = hook_score(line, ctx.known, first=(k == i), clause=(line != whole))
            if s > best_score:
                best, best_score = line, s
    if not best or best_score < 0.5:
        best = _title_hook(ctx.title) or best
    hook = best[:70].rstrip()
    kicker = kicker_for(ctx, i, j)
    title = hook if len(hook) >= 20 else (_title_hook(ctx.title) or hook)
    return hook, kicker, title[:95]


# Capitalised words that are not a subject (a sentence's start inside a clause, days, months, units).
_NOT_KICKER = {"he", "she", "it", "they", "we", "you", "i", "no", "not", "but", "and", "so", "the", "this", "that",
               "these", "those", "there", "here", "when", "then", "now", "what", "why", "how", "who", "if", "yes",
               "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "january", "february",
               "march", "april", "may", "june", "july", "august", "september", "october", "november", "december",
               "fahrenheit", "celsius", "mr", "mrs", "dr", "st", "a", "an", "one", "two", "three", "my", "our",
               "his", "her", "its", "their", "at", "in", "on", "for", "with", "by", "from", "of", "to"}


def _names_in(sentence: str, known: Tuple[str, ...]) -> List[str]:
    """The proper names one sentence uses (never its first word on its own), the story's own names first."""
    out = []
    for name in _entities(sentence, known):
        words = name.split()
        while words and words[0].lower().strip("'’") in _NOT_KICKER:
            words = words[1:]
        name = " ".join(words)
        if not name or _word_count(name) > 4 or len(name) > 26 or name.lower() in _NOT_KICKER:
            continue
        out.append(name)
    return out


def kicker_for(ctx: _Ctx, i: int, j: int) -> str:
    """
    The place or subject the moment names most (the story's own places and people count double), upper
    case and short; else the long video's own subject (the first name in its title); else nothing.
    """
    counts: Dict[str, float] = {}
    first_seen: Dict[str, int] = {}
    known_low = {k.lower() for k in ctx.known}
    for k in range(i, j + 1):
        for name in _names_in(ctx.sents[k]["text"], ctx.known):
            key = name.lower()
            counts[key] = counts.get(key, 0.0) + (2.0 if key in known_low else 1.0)
            first_seen.setdefault(key, k)
    # A name inside a longer one ("Basin" in "Biscuit Basin") counts for the longer one.
    for key in list(counts):
        for other in counts:
            if other != key and re.search(r"\b" + re.escape(key) + r"\b", other):
                counts[other] += counts[key] * 0.5
    names = {}
    for k in range(i, j + 1):
        for name in _names_in(ctx.sents[k]["text"], ctx.known):
            names.setdefault(name.lower(), name)
    if counts:
        best = max(counts, key=lambda key: (counts[key], len(key.split()) > 1, -first_seen[key]))
        if counts[best] >= 1.5 or best in known_low:
            # A lone word the story does not list and the moment barely repeats ("Geyser") is more likely
            # a capitalised common noun than a subject: the video's own subject labels it better.
            if len(best.split()) == 1 and best not in known_low and counts[best] < 3 and ctx.subject():
                return ctx.subject().upper()
            return names[best].upper()
    return ctx.subject().upper()


def moment(ctx: _Ctx, i: int, j: int, score: Optional[float] = None, reasons: Optional[List[str]] = None,
           parts: Optional[dict] = None) -> dict:
    """Sentences i..j as a moment: times, hook, kicker, title, score, reasons, first line."""
    if score is None:
        score, reasons, parts = score_window(ctx, i, j)
    t0, t1 = ctx.window(i, j)
    hook, kicker, title = hook_for(ctx, i, j)
    return {"start": t0, "end": t1, "hook": hook, "kicker": kicker, "title": title, "score": score,
            "reasons": list(reasons or []), "firstLine": ctx.sents[i]["text"], "firstSentence": i,
            "lastSentence": j, "parts": parts or {}}


def snap(ctx: _Ctx, start: float, end: float) -> Tuple[float, float]:
    """
    A moment the app sent, on whole words: from just before the first word that starts in it to just after
    the last word that ends in it (never into a neighbouring word). (start, end) as given when no word is in it.
    """
    inside = [k for k, w in enumerate(ctx.words) if w["start"] >= start - 0.25 and w["end"] <= end + 0.25]
    if not inside:
        return float(start), float(end)
    a, b = inside[0], inside[-1]
    prev_end = ctx.words[a - 1]["end"] if a > 0 else 0.0
    next_start = ctx.words[b + 1]["start"] if b + 1 < len(ctx.words) else ctx.words[b]["end"] + 1.0
    s = max(prev_end + 0.03, ctx.words[a]["start"] - LEAD_IN, 0.0)
    e = max(ctx.words[b]["end"], min(next_start - 0.03, ctx.words[b]["end"] + TAIL_OUT))
    return round(s, 3), round(e, 3)


def sentence_range(ctx: _Ctx, start: float, end: float) -> Tuple[int, int]:
    """The first and last sentence (indices) a time range holds; (-1, -1) when it holds none."""
    inside = [s["index"] for s in ctx.sents if s["start"] >= start - 0.3 and s["end"] <= end + 0.3]
    return (inside[0], inside[-1]) if inside else (-1, -1)


# --------------------------------------------------------------------------- #
# The Short's documents: the 16:9 stage and the words
# --------------------------------------------------------------------------- #

def _frames(seconds: float, fps: float) -> int:
    return int(round(float(seconds) * float(fps)))


# Looks that put the narration's own words on screen (a typed statement, a key word, a quote, a headline or
# chapter card): a Short's captions already say them, and each would pull the picture out to the band.
_TEXT_CATEGORIES = {"TEXT", "QUOTES", "HEADLINES", "TRANSITIONS"}
_TEXT_TYPES = {"typewriter", "word-type", "sentence-highlight", "kicker", "chapter", "title", "quote",
               "underline-title", "bar-title", "swoosh-title", "red-strip", "memo-box", "highlight", "callout"}


def says_words(ov: dict) -> bool:
    """Is this overlay a look that only puts words of the narration on screen?"""
    from . import templates
    if str(ov.get("type") or "") in _TEXT_TYPES:
        return True
    tid = str(ov.get("template") or "")
    if not tid and ov.get("type") == "motion" and ov.get("variant"):
        tid = "LIB_" + str(ov["variant"]).upper().replace("-", "_")
    try:
        t = templates.get(tid) if tid else None
    except Exception:  # noqa: BLE001 - an unknown look is kept
        t = None
    return bool(t) and str(t.get("category") or "") in _TEXT_CATEGORIES


def stage_doc(doc: dict, start: float, end: float, fps: int = SHORT_FPS, audio_url: str = "",
              music: bool = True, keep_captions: bool = False, drop_text_looks: bool = False) -> dict:
    """
    The long video's document cut to [start, end) seconds, on the Short's own clock at `fps`: the 16:9
    stage the Short draws (remotion Main renders it), the long video's own look - its scenes, graphics,
    grade, transition and look sounds - with the narration slice `audio_url` playing from frame 0 and the
    music bed at the owner's flat level. Every frame number is scaled the way the editor retimes a
    document (editorHelpers.retimeDocument); scenes tile the Short from frame 0 to its end.
    """
    from . import config, timeline
    src = float(doc.get("fps") or 30) or 30.0
    total = max(1, _frames(end - start, fps))
    f0, f1 = start * src, end * src
    rate = float(fps) / src

    kept = []
    for sc in sorted(doc.get("scenes") or [], key=lambda s: float(s.get("startFrame") or 0)):
        a = float(sc.get("startFrame") or 0)
        b = a + max(1.0, float(sc.get("durationInFrames") or 0))
        if b <= f0 + 0.5 or a >= f1 - 0.5:
            continue
        kept.append((max(a, f0), min(b, f1), sc))
    bounds = [min(total, _frames((a - f0) / src, fps)) for a, _, _ in kept] + [total]
    if bounds:
        bounds[0] = 0
    scenes = []
    for k, (a, b, sc) in enumerate(kept):
        s0, s1 = bounds[k], max(bounds[k], bounds[k + 1])
        if s1 <= s0:
            continue                  # shorter than a frame at this rate: its neighbour covers it
        new = copy.deepcopy(sc)
        new["startFrame"], new["durationInFrames"] = s0, s1 - s0
        new["words"] = [{**w, "start": round(float(w["start"]) - start, 3), "end": round(float(w["end"]) - start, 3)}
                        for w in (sc.get("words") or [])
                        if float(w.get("end") or 0) > start and float(w.get("start") or 0) < end]
        scenes.append(new)
    # A sliver of the shot before (or after) the moment - the window starts a breath before its first word,
    # which can be a few frames into the previous shot - would flash on screen: the neighbour covers it.
    sliver = int(round(0.4 * fps))
    if len(scenes) > 1 and scenes[0]["durationInFrames"] < sliver:
        gone = scenes.pop(0)
        scenes[0]["durationInFrames"] += scenes[0]["startFrame"]
        scenes[0]["startFrame"] = 0
        scenes[0]["words"] = gone["words"] + scenes[0]["words"]
    if len(scenes) > 1 and scenes[-1]["durationInFrames"] < sliver:
        gone = scenes.pop()
        scenes[-1]["words"] = scenes[-1]["words"] + gone["words"]
    if scenes:
        # A Short opens on its first picture, not on a transition into it from nothing.
        scenes[0]["transition"] = "none"
        scenes[-1]["durationInFrames"] = max(1, total - scenes[-1]["startFrame"])

    overlays = []
    for ov in doc.get("overlays") or []:
        if drop_text_looks and says_words(ov):
            continue
        a = float(ov.get("startFrame") or 0)
        d = max(1.0, float(ov.get("durationInFrames") or 0))
        b = a + d
        if b <= f0 or a >= f1:
            continue
        shown = min(b, f1) - max(a, f0)
        if a < f0 and shown < 0.5 * d:
            continue                  # mostly gone before the Short starts
        s0 = _frames((max(a, f0) - f0) / src, fps)
        dur = min(total - s0, _frames(shown / src, fps))
        if dur < int(0.8 * fps):
            continue
        overlays.append({**copy.deepcopy(ov), "startFrame": s0, "durationInFrames": dur})

    def scale(v):
        return int(round(float(v) * rate)) if isinstance(v, (int, float)) else v

    sfx = []
    for fx in doc.get("sfx") or []:
        a = float(fx.get("startFrame") or 0)
        if a < f0 or a >= f1:
            continue
        row = {**fx, "startFrame": _frames((a - f0) / src, fps)}
        for key in ("durationFrames", "trimFrames"):
            if isinstance(fx.get(key), (int, float)):
                row[key] = max(1 if key == "durationFrames" else 0, scale(fx[key]))
        sfx.append(row)

    ambience = None
    amb = doc.get("ambience")
    if isinstance(amb, dict) and isinstance(amb.get("beds"), list):
        beds = []
        for bed in amb["beds"]:
            a = float(bed.get("startFrame") or 0)
            b = a + float(bed.get("durationInFrames") or 0)
            if b <= f0 or a >= f1:
                continue
            nb = {**bed, "startFrame": _frames((max(a, f0) - f0) / src, fps),
                  "durationInFrames": max(1, _frames((min(b, f1) - max(a, f0)) / src, fps))}
            for key in ("fadeIn", "fadeOut"):
                if isinstance(bed.get(key), (int, float)):
                    nb[key] = scale(bed[key])
            if isinstance(bed.get("holes"), list):
                holes = []
                for h in bed["holes"]:
                    if isinstance(h, list) and len(h) == 2:
                        h0, h1 = max(float(h[0]), f0), min(float(h[1]), f1)
                        if h1 > h0:
                            holes.append([_frames((h0 - f0) / src, fps), _frames((h1 - f0) / src, fps)])
                nb["holes"] = holes
            beds.append(nb)
        ambience = {**amb, "beds": beds}

    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    voice_lufs = float(meta.get("voiceLufs") or -20.0)
    bgm = doc.get("bgm") if isinstance(doc.get("bgm"), dict) and (doc.get("bgm") or {}).get("url") else None
    music_doc = None
    if music and bgm:
        old = doc.get("music") if isinstance(doc.get("music"), dict) else {}
        level = (old.get("levels") or {}).get("speech") if isinstance(old.get("levels"), dict) else None
        level = float(level) if isinstance(level, (int, float)) else float(config.MUSIC_LEVEL)
        music_doc = timeline.music_flat(None, bgm, fps, total, voice_lufs, level)
        if isinstance(old.get("duck"), (int, float)):
            music_doc["duck"] = float(old["duck"])
        if isinstance(old.get("gain"), (int, float)):
            music_doc["gain"] = float(old["gain"])
    audio = dict(doc.get("audio") or {})
    audio.pop("boostDb", None)        # already in the slice (_slice_narration)
    audio["url"] = audio_url or ""
    captions = dict(doc.get("captions") or {})
    if not keep_captions:
        captions["enabled"] = False
    out = {
        "fps": fps, "width": STAGE_W, "height": STAGE_H, "durationInFrames": total,
        "schemaVersion": doc.get("schemaVersion"),
        "audio": audio, "bgm": bgm if music_doc else None, "music": music_doc,
        "captions": captions, "scenes": scenes, "overlays": overlays, "sfx": sfx,
        "meta": {"voiceLufs": voice_lufs, "videoStyle": meta.get("videoStyle"), "renderStale": False,
                 "story": meta.get("story")},
    }
    for key in ("grade", "lookSounds", "sfxVolume", "sfxEnabled", "overlaysEnabled", "transitionPack"):
        if key in doc:
            out[key] = copy.deepcopy(doc[key])
    if ambience is not None:
        out["ambience"] = ambience
    return out


def caption_words(ctx: _Ctx, start: float, end: float) -> List[dict]:
    """The Short's words for its captions: {text, start, end} in seconds from the Short's own start."""
    out = []
    for w in ctx.words:
        if w["end"] <= start or w["start"] >= end:
            continue
        out.append({"text": w["text"], "start": round(max(0.0, w["start"] - start), 3),
                    "end": round(min(end - start, w["end"] - start), 3)})
    return out


# --------------------------------------------------------------------------- #
# Framing: crop, fit or native, per shot
# --------------------------------------------------------------------------- #

def scene_framing(scene: dict, focus: Optional[dict]) -> dict:
    """
    How one shot fills the 9:16 frame: {"mode": crop | fit | native, "cx": the crop window's centre (a share
    of the stage's width), "why"}. Fit whenever cropping would cut off what the shot is for: a graphic, a
    framed or inset shot, a news clip (its logo and chyron are never cropped: the owner's rule), lettering
    burned into the picture, a subject wider than the window. Native for a vertical source.
    """
    from . import reframe
    m = scene.get("media") or {}
    t = m.get("type")
    if t == "animation":
        return {"mode": "fit", "cx": 0.5, "why": "graphic"}
    if not m.get("url") or t == "color":
        return {"mode": "crop", "cx": 0.5, "why": "no picture"}
    if scene.get("frame") in ("window", "inset"):
        return {"mode": "fit", "cx": 0.5, "why": "framed shot"}
    if reframe.is_news(m):
        return {"mode": "fit", "cx": 0.5, "why": "news footage"}
    if not focus:
        return {"mode": "crop", "cx": 0.5, "why": "centre"}
    aspect = float(focus.get("aspect") or (16 / 9))
    box = focus.get("box") if isinstance(focus.get("box"), dict) else None
    kind = str(focus.get("kind") or "none")
    conf = float(focus.get("confidence") or 0.0)
    if aspect < 0.9:
        cx = 0.5
        if box and kind in ("face", "object", "action"):
            cx = max(0.0, min(1.0, box["x"] + box["w"] / 2))
        return {"mode": "native", "cx": round(cx, 4), "why": "vertical source"}
    bars = focus.get("bars") if isinstance(focus.get("bars"), dict) else {}
    top, bottom = _stage_bars(bars, aspect)
    if top > 0.015 and bottom > 0.015:
        # A letterboxed picture (black bars baked into the file): cropped, the bars would frame the Short top
        # and bottom; zoomed past them, it would soften. Fitted, with the bars trimmed off the band.
        return {"mode": "fit", "cx": 0.5, "why": "letterboxed", "clip": [round(top, 4), round(bottom, 4)]}
    if focus.get("overlay") or kind == "text":
        return {"mode": "fit", "cx": 0.5, "why": "lettering in the picture"}
    if max([float(v or 0) for k, v in bars.items() if k in ("left", "right")] or [0.0]) > 0.12:
        return {"mode": "crop", "cx": 0.5, "why": "pillarboxed"}
    if box and kind in ("face", "object", "action") and conf >= (0.35 if kind == "face" else 0.4):
        sb = reframe.cover_box(box, aspect, STAGE_W / STAGE_H) or box
        width = float(sb.get("w") or 1.0)
        limit = WINDOW * (1.15 if kind == "face" else 1.35)
        if width <= limit:
            half = WINDOW / 2
            cx = max(half, min(1 - half, float(sb.get("x") or 0) + width / 2))
            # Four decimals, never rounded past the stage's edge.
            cx = math.floor(cx * 1e4) / 1e4 if cx > 0.5 else math.ceil(cx * 1e4) / 1e4
            return {"mode": "crop", "cx": cx, "why": kind}
        return {"mode": "fit", "cx": 0.5, "why": f"wide {kind}"}
    return {"mode": "crop", "cx": 0.5, "why": "centre"}


def _stage_bars(bars: dict, src_aspect: float) -> Tuple[float, float]:
    """A source's top and bottom black bars as shares of the stage once the source is cover-fitted to 16:9."""
    try:
        top, bottom = float(bars.get("top") or 0.0), float(bars.get("bottom") or 0.0)
    except (TypeError, ValueError):
        return 0.0, 0.0
    stage = STAGE_W / STAGE_H
    if src_aspect and src_aspect < stage:
        keep = src_aspect / stage                  # the share of the source's height the stage shows
        off = (1.0 - keep) / 2.0
        top = max(0.0, (top - off) / keep)
        bottom = max(0.0, (bottom - off) / keep)
    return min(top, 0.4), min(bottom, 0.4)


def _graphic_spans(stage: dict) -> List[Tuple[int, int]]:
    """Frames a graphic is on screen (a little before it lands and after it leaves), merged."""
    total = int(stage.get("durationInFrames") or 0)
    fps = int(stage.get("fps") or SHORT_FPS)
    pre, post = int(round(0.15 * fps)), int(round(0.25 * fps))
    spans = []
    for ov in stage.get("overlays") or []:
        a = int(ov.get("startFrame") or 0)
        b = a + int(ov.get("durationInFrames") or 0)
        spans.append((max(0, a - pre), min(total, b + post)))
    spans.sort()
    merged: List[List[int]] = []
    for a, b in spans:
        # Two graphics close together: stay out between them rather than zoom in and out again.
        if merged and a <= merged[-1][1] + int(1.2 * fps):
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged if b > a]


def plan_framing(stage: dict, focus: Dict[str, dict]) -> List[dict]:
    """
    The Short's framing as spans covering every frame: {from, to, mode, cx, ease, scene, why}. Each shot
    takes its own framing (scene_framing) and snaps to it on the cut; while a graphic is on screen the
    framing is FIT, eased over EASE_FRAMES when that happens inside a shot.
    """
    graphics = _graphic_spans(stage)
    out: List[dict] = []
    for idx, sc in enumerate(stage.get("scenes") or []):
        base = scene_framing(sc, focus.get(sc.get("id") or "") or focus.get(str(idx)))
        a = int(sc["startFrame"])
        b = a + int(sc["durationInFrames"])
        cuts = sorted({p for g in graphics for p in g if a < p < b})
        points = [a] + cuts + [b]
        for p0, p1 in zip(points, points[1:]):
            if p1 <= p0:
                continue
            mid = (p0 + p1) / 2.0
            in_graphic = any(g0 <= mid < g1 for g0, g1 in graphics)
            mode = "fit" if in_graphic else base["mode"]
            span = {"from": p0, "to": p1, "mode": mode, "cx": base["cx"] if mode != "fit" else 0.5,
                    "ease": 0 if p0 == a else EASE_FRAMES, "scene": idx,
                    "why": "graphic on screen" if in_graphic and base["mode"] != "fit" else base["why"]}
            # A letterboxed shot's band leaves its bars out - not while a graphic is up (it may sit in them).
            if base.get("clip") and not in_graphic:
                span["clip"] = list(base["clip"])
            prev = out[-1] if out else None
            if prev and prev["mode"] == span["mode"] and abs(prev["cx"] - span["cx"]) < 1e-6 and prev["to"] == p0 \
                    and prev.get("clip") == span.get("clip") and (span["ease"] or prev["scene"] == idx):
                prev["to"] = p1       # nothing changes here: one span
                continue
            out.append(span)
    for s in out:
        s["ease"] = min(int(s["ease"]), max(0, int(s["to"]) - int(s["from"])))
    return out


def native_media(stage: dict, spans: List[dict]) -> None:
    """
    A NATIVE span draws its shot's own file straight into the frame (span.media, which the renderer
    serves like any media); the stage's copy of that scene becomes its still, so the frame never decodes
    the same clip twice (see _backdrop_copies) - the stage shows it only if a graphic pulls the framing out.
    """
    scenes = stage.get("scenes") or []
    for s in spans:
        if s.get("mode") != "native" or not isinstance(s.get("scene"), int) or s["scene"] >= len(scenes):
            continue
        m = scenes[s["scene"]].get("media") or {}
        if not m.get("url"):
            continue
        s["media"] = {k: m.get(k) for k in ("type", "url", "clipSeconds", "thumbnail") if m.get(k) is not None}
        still = m.get("previewUrl") or m.get("thumbnail")
        if m.get("type") == "video" and still:
            scenes[s["scene"]]["media"] = {**m, "type": "image", "url": still, "previewUrl": None}


def framing_counts(spans: List[dict]) -> Dict[str, int]:
    """How many shots took each framing (by frames on screen, rounded to shots for the report)."""
    out: Dict[str, int] = {}
    for s in spans:
        out[s["mode"]] = out.get(s["mode"], 0) + 1
    return out


# --------------------------------------------------------------------------- #
# Files: the shots, the narration slice, the poster
# --------------------------------------------------------------------------- #

_VIDEO_EXT = (".mp4", ".mov", ".webm", ".m4v", ".mkv")


def _ext(url: str, kind: str) -> str:
    path = urllib.parse.urlparse(url).path.lower()
    ext = os.path.splitext(path)[1]
    if ext and len(ext) <= 5:
        return ext
    return ".mp4" if kind == "video" else ".jpg"


def _playable(path: str) -> bool:
    """A real video file (ffprobe finds a picture stream with frames)."""
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                            "-of", "json", path], capture_output=True, text=True, timeout=30)
        streams = json.loads(p.stdout or "{}").get("streams") or []
        return bool(streams and streams[0].get("width"))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def fetch_media(stage: dict, work: str, deadline: float, fetch=None) -> Dict[str, str]:
    """
    Every shot's file on local disk (served to the renderer over loopback, so the render never waits on a
    remote host), {url: local path}. A clip that cannot be had or played becomes its own still (its
    thumbnail) in the stage: a Short never fails on one shot.
    """
    from . import storage
    fetch = fetch or (lambda url, dest: storage.download(url, dest, timeout=60, max_seconds=120))
    folder = os.path.join(work, "shots")
    os.makedirs(folder, exist_ok=True)
    urls = []
    for sc in stage.get("scenes") or []:
        m = sc.get("media") or {}
        url = str(m.get("url") or "")
        if url.startswith(("http://", "https://")) and url not in urls:
            urls.append(url)
    got: Dict[str, str] = {}

    def one(url: str):
        if time.time() > deadline:
            return url, ""
        kind = "video" if any(((s.get("media") or {}).get("url") == url and (s.get("media") or {}).get("type") == "video")
                              for s in stage.get("scenes") or []) else "image"
        dest = os.path.join(folder, uuid.uuid5(uuid.NAMESPACE_URL, url).hex[:16] + _ext(url, kind))
        try:
            path = fetch(url, dest)
        except Exception as e:  # noqa: BLE001 - one shot never stops a Short
            print(f"[shorts] shot not fetched: {type(e).__name__}: {str(e)[:120]}", flush=True)
            return url, ""
        if kind == "video" and not _playable(path):
            return url, ""
        return url, path

    with ThreadPoolExecutor(max_workers=6) as pool:
        for url, path in pool.map(one, urls):
            if path:
                got[url] = path
    for sc in stage.get("scenes") or []:
        m = sc.get("media") or {}
        url = str(m.get("url") or "")
        if not url.startswith(("http://", "https://")):
            continue
        if url in got:
            m["remoteUrl"] = url
            m["url"] = got[url]
        elif m.get("type") == "video" and m.get("thumbnail"):
            # The clip could not be had: its own still holds the shot (SafeImg never stops a render).
            sc["media"] = {**m, "type": "image", "url": m["thumbnail"], "remoteUrl": url, "heldStill": True}
    if NORMALISE_CLIPS:
        _normalise_clips(stage, deadline)
    _backdrop_copies(stage, folder, deadline, fetch)
    return got


# Every clip re-encoded once before the render: constant 30 fps, short GOP, no B-frames, cut to what the
# Short plays. Remotion's frame extraction failed twice on the laptop on ordinary YouTube cuts ("No frame
# found at position", a 30 fps and a 60 fps file, 2026-10-07); a clean file seeks the same on every machine.
NORMALISE_CLIPS = os.getenv("SHORTS_NORMALISE_CLIPS", "1") not in ("0", "false", "no")


def _probe_seconds(path: str) -> float:
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
                           capture_output=True, text=True, timeout=30)
        return float(json.loads(p.stdout or "{}").get("format", {}).get("duration") or 0.0)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0.0


def _normalise_clips(stage: dict, deadline: float, fps: int = 0) -> None:
    fps = int(fps or stage.get("fps") or SHORT_FPS)
    need: Dict[str, float] = {}
    for sc in stage.get("scenes") or []:
        m = sc.get("media") or {}
        path = str(m.get("url") or "")
        if m.get("type") == "video" and os.path.isfile(path):
            secs = float(sc.get("durationInFrames") or 0) / fps
            need[path] = max(need.get(path, 0.0), secs)

    def one(path: str):
        if time.time() > deadline:
            return path, "", 0.0
        have = _probe_seconds(path)
        keep = min(have, need[path] + 0.5) if have > 0 else need[path] + 0.5
        dest = os.path.splitext(path)[0] + "-cfr.mp4"
        p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", path, "-t", f"{keep:.3f}",
                            "-an", "-vf", f"fps={fps},format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
                            "-crf", "17", "-g", str(max(1, fps // 2)), "-bf", "0", "-movflags", "+faststart", dest],
                           capture_output=True, text=True, timeout=240)
        if p.returncode != 0 or not _playable(dest):
            print(f"[shorts] clip kept as it was (re-encode failed): {(p.stderr or '')[-160:]}", flush=True)
            return path, "", 0.0
        return path, dest, _probe_seconds(dest)

    with ThreadPoolExecutor(max_workers=4) as pool:
        done = {src: (dest, secs) for src, dest, secs in pool.map(one, list(need))}
    for sc in stage.get("scenes") or []:
        m = sc.get("media") or {}
        got = done.get(str(m.get("url") or ""))
        if got and got[0]:
            m["url"] = got[0]
            if got[1] > 0:
                m["clipSeconds"] = round(max(0.1, got[1] - 0.04), 3)


def _backdrop_copies(stage: dict, folder: str, deadline: float, fetch=None) -> None:
    """
    Each clip's blurred backdrop (Short.tsx Backdrop) is a STILL of the clip, made here (480 px, from the
    middle of what the scene plays): blurred anyway, and the frame then decodes one video, not two. A
    second video per frame filled Remotion's OffthreadVideo cache on a busy laptop and failed renders with
    "No frame found at position" (2026-10-07; Remotion's docs: frames evicted from a cache that is too
    small). Kept in media.previewUrl: the renderer serves that field and draws nothing else from it. No
    still = the clip's own thumbnail.
    """
    fps = float(stage.get("fps") or SHORT_FPS)
    stills: Dict[str, str] = {}
    for sc in stage.get("scenes") or []:
        m = sc.get("media") or {}
        local = str(m.get("url") or "")
        if m.get("type") != "video":
            continue
        m.pop("previewUrl", None)                # never the editor's preview copy
        if not os.path.isfile(local):
            continue                             # (a remote clip: its backdrop is its thumbnail)
        if local in stills:
            m["previewUrl"] = stills[local]
            continue
        path = os.path.splitext(local)[0] + "-backdrop.jpg"
        if not os.path.isfile(path) and time.time() < deadline:
            mid = max(0.0, min(float(m.get("clipSeconds") or 1.0), float(sc.get("durationInFrames") or 0) / fps) / 2)
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{mid:.2f}", "-i", local,
                            "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "4", path],
                           capture_output=True, text=True, timeout=60)
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            stills[local] = path
            m["previewUrl"] = path


def analyse_shots(stage: dict, deadline: float, detect_clip=None, detect_still=None) -> Dict[str, dict]:
    """
    media.focus for every shot whose file is local, {scene id: focus} (src/reframe.py's detectors: faces,
    the main object, lettering burned in, the source's shape), time-boxed; a shot not reached stays centred.
    """
    from . import reframe
    detect_clip = detect_clip or reframe.detect_clip
    detect_still = detect_still or reframe.detect_still
    jobs = []
    seen: Dict[str, str] = {}
    fps = float(stage.get("fps") or SHORT_FPS)
    for sc in stage.get("scenes") or []:
        m = sc.get("media") or {}
        path = str(m.get("url") or "")
        if m.get("type") not in ("video", "image") or not os.path.isfile(path):
            continue
        if path in seen:
            continue
        seen[path] = sc.get("id") or ""
        jobs.append((sc, path, m.get("type"), max(0.5, float(sc["durationInFrames"]) / fps)))
    found: Dict[str, dict] = {}

    def one(job):
        sc, path, kind, shown = job
        if time.time() > deadline:
            return path, None
        try:
            return path, (detect_clip(path, shown, timeout=25.0) if kind == "video" else detect_still(path))
        except Exception as e:  # noqa: BLE001 - an unread shot is framed on its centre
            print(f"[shorts] shot not analysed: {type(e).__name__}: {str(e)[:120]}", flush=True)
            return path, None

    with ThreadPoolExecutor(max_workers=4) as pool:
        by_path = dict(pool.map(one, jobs))
    for sc in stage.get("scenes") or []:
        path = str((sc.get("media") or {}).get("url") or "")
        if by_path.get(path):
            found[sc.get("id") or ""] = by_path[path]
    return found


def _slice_narration(src: str, start: float, end: float, dest: str, boost_db: float = 0.0) -> str:
    """The narration from `start` to `end` as 48 kHz WAV, faded in and out over a few hundredths of a second."""
    dur = max(0.1, end - start)
    filters = []
    if boost_db and boost_db > 0:
        filters.append(f"volume={min(6.0, float(boost_db)):.2f}dB")
    filters += [f"afade=t=in:st=0:d=0.04", f"afade=t=out:st={max(0.0, dur - 0.22):.3f}:d=0.22"]
    if boost_db and boost_db > 0:
        filters.append("alimiter=limit=0.95")
    p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{max(0.0, start):.3f}",
                        "-t", f"{dur:.3f}", "-i", src, "-af", ",".join(filters), "-ac", "2", "-ar", "48000", dest],
                       capture_output=True, text=True, timeout=300)
    if p.returncode != 0 or not os.path.isfile(dest):
        raise RuntimeError(f"the narration could not be cut: {(p.stderr or '')[-300:]}")
    return dest


def _poster(video: str, dest: str, at: float) -> str:
    """A 540x960 JPEG of the Short at `at` seconds (the hook is on screen by then)."""
    p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{max(0.0, at):.2f}", "-i", video,
                        "-frames:v", "1", "-vf", "scale=540:-2", "-q:v", "3", dest],
                       capture_output=True, text=True, timeout=120)
    return dest if p.returncode == 0 and os.path.isfile(dest) else ""


# --------------------------------------------------------------------------- #
# One Short
# --------------------------------------------------------------------------- #

def short_props(stage: dict, spans: List[dict], words: List[dict], hook: str, kicker: str,
                captions: bool = True, hook_seconds: float = HOOK_SECONDS, accent: str = ACCENT) -> dict:
    """The props of the remotion composition "Short" (remotion/src/short/Short.tsx)."""
    fps = int(stage.get("fps") or SHORT_FPS)
    total = int(stage.get("durationInFrames") or 1)
    return {
        "fps": fps, "width": SHORT_W, "height": SHORT_H, "durationInFrames": total,
        "stage": stage, "framing": spans,
        "captions": {"enabled": bool(captions), "words": words if captions else [], "accent": accent},
        "hook": ({"text": hook.strip(), "kicker": (kicker or "").strip(),
                  "frames": max(1, min(total, int(round(max(1.0, float(hook_seconds)) * fps))))}
                 if hook and hook.strip() else None),
        "accent": accent,
    }


def _clean_hook(text: str, limit: int = 90) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return t[:limit].rstrip()


def make_one(doc: dict, ctx: _Ctx, job: dict, narration: str, work: str, opts: dict, report=None,
             render_fn=None, finalize_fn=None) -> dict:
    """
    Render one Short (or, with aspect "landscape", the long video's own look over the window: the hook
    preview) and save it. Returns its result row (see the module notes); raises on a failure.
    """
    from . import render as renderer
    from . import templates
    render_fn = render_fn or renderer.render
    finalize_fn = finalize_fn or renderer.finalize
    t0 = time.time()
    start, end = float(job["start"]), float(job["end"])
    sid = re.sub(r"[^A-Za-z0-9_-]", "", str(job.get("short_id") or "")) or uuid.uuid4().hex[:12]
    folder = os.path.join(work, f"short-{sid}")
    os.makedirs(folder, exist_ok=True)
    landscape = opts.get("aspect") == "landscape"
    fps = int(opts.get("fps") or SHORT_FPS)
    boost = float(((doc.get("audio") or {}).get("boostDb") or 0) or 0)
    voice = _slice_narration(narration, start, end, os.path.join(folder, "narration.wav"), boost)
    stage = stage_doc(doc, start, end, fps=fps, audio_url=voice, music=opts.get("music", True) is not False,
                      keep_captions=landscape, drop_text_looks=not landscape)
    have = templates.sfx_files()
    stage["sfx"] = [fx for fx in stage.get("sfx") or [] if fx.get("name") in have]
    deadline = time.time() + float(opts.get("analyse_seconds") or ANALYSE_SECONDS)
    if report:
        report("Getting the shots ready", 5)
    fetch_media(stage, folder, deadline + 60, fetch=opts.get("_fetch"))
    words = caption_words(ctx, start, end)
    spans: List[dict] = []
    if landscape:
        props, composition, width, height = stage, "Main", STAGE_W, STAGE_H
    else:
        if report:
            report("Framing every shot for vertical", 15)
        focus = analyse_shots(stage, deadline, detect_clip=opts.get("_detect_clip"),
                              detect_still=opts.get("_detect_still"))
        spans = plan_framing(stage, focus)
        native_media(stage, spans)
        props = short_props(stage, spans, words, job.get("hook") or "", job.get("kicker") or "",
                            captions=opts.get("captions", True) is not False,
                            hook_seconds=float(opts.get("hook_seconds") or HOOK_SECONDS),
                            accent=str(opts.get("accent") or ACCENT))
        composition, width, height = "Short", SHORT_W, SHORT_H
    picture = os.path.join(folder, "picture.mp4")
    sound = os.path.join(folder, "sound.wav")
    last = [0.0]

    def progress(frac):
        if report and time.time() - last[0] > 4:
            last[0] = time.time()
            report("Rendering the Short" if not landscape else "Rendering the preview", int(20 + 72 * frac))

    from . import config
    render_fn(props, picture, composition=composition, serve_dir=folder, on_progress=progress, audio_to=sound,
              concurrency=int(opts.get("concurrency") or config.RENDER_CONCURRENCY))
    final = os.path.join(folder, f"{sid}.mp4")
    loud = finalize_fn(picture, sound, final)
    poster = _poster(final, os.path.join(folder, f"{sid}.jpg"), min(1.2, (end - start) / 2))
    out = {"short_id": sid, "start": round(start, 3), "end": round(end, 3), "duration": round(end - start, 3),
           "hook": job.get("hook") or "", "kicker": job.get("kicker") or "", "title": job.get("title") or "",
           "width": width, "height": height, "fps": fps, "aspect": "landscape" if landscape else "vertical",
           "bytes": os.path.getsize(final) if os.path.isfile(final) else 0,
           "framing": framing_counts(spans) if spans else {}, "loudness": loud,
           "render_seconds": round(time.time() - t0, 1), "local_path": final, "local_poster": poster}
    return out


def _upload(result: dict, project_id: str, title: str, index: int, landscape: bool) -> dict:
    """The Short and its poster to R2 (projects/<project>/shorts/<id>.mp4 / .jpg): their public links."""
    from . import r2
    sid = result["short_id"]
    base = f"projects/{project_id}/shorts/{sid}"
    name = f"{(title or 'video').strip()[:80]} - {'Hook preview' if landscape else f'Short {index + 1}'}"
    out = dict(result)
    out["video_url"] = r2.upload(result["local_path"], base + ".mp4", "video/mp4",
                                 content_disposition=r2.attachment(name))
    if result.get("local_poster"):
        out["poster_url"] = r2.upload(result["local_poster"], base + ".jpg", "image/jpeg")
    return out


# --------------------------------------------------------------------------- #
# The worker action
# --------------------------------------------------------------------------- #

def _load_timeline(inp: dict, work: str) -> dict:
    doc = inp.get("timeline")
    if isinstance(doc, dict) and doc.get("scenes"):
        return doc
    url = str(inp.get("timeline_url") or "")
    if url:
        from . import storage
        path = storage.download(url, os.path.join(work, "timeline.json"), timeout=60)
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        if isinstance(doc, dict) and isinstance(doc.get("timeline"), dict):
            doc = doc["timeline"]
        if isinstance(doc, dict) and doc.get("scenes"):
            return doc
    raise ValueError("shorts needs the video's timeline (timeline or timeline_url)")


def _moments_in(inp: dict) -> List[dict]:
    if isinstance(inp.get("moments"), list):
        return [m for m in inp["moments"] if isinstance(m, dict)]
    if isinstance(inp.get("moment"), dict):
        return [inp["moment"]]
    return []


def run(inp: dict, work: str, report=None) -> dict:
    """
    The worker action "shorts": every moment asked for (or the best `count` the picker finds) rendered as
    a Short and saved. One Short per job is what the app sends (its jobs run side by side); a local run may
    ask for several. Never touches the project row.
    """
    started = time.time()
    report = report or (lambda *a, **k: None)
    doc = _load_timeline(inp, work)
    title = str(inp.get("title") or doc.get("title") or "")
    doc = {**doc, "title": title}
    ctx = _Ctx(doc)
    if not ctx.words:
        return {"ok": False, "error": "This video's timeline has no word timings, so a Short cannot be cut from it."}
    landscape = inp.get("aspect") == "landscape"
    asked = _moments_in(inp)
    picked: List[dict] = []
    if not asked:
        picked = pick(doc, int(inp.get("count") or DEFAULT_COUNT))
        asked = picked
    jobs: List[dict] = []
    ids = inp.get("short_ids") if isinstance(inp.get("short_ids"), list) else []
    for k, m in enumerate(asked[:MAX_COUNT]):
        try:
            s, e = float(m.get("start")), float(m.get("end"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "A moment needs a start and an end (seconds)."}
        if not landscape:
            s, e = snap(ctx, s, e)
        e = min(e, ctx.total + TAIL_OUT) if ctx.total else e
        if not (HARD_MIN_SECONDS <= e - s <= HARD_MAX_SECONDS) and not (landscape and 5 <= e - s <= HARD_MAX_SECONDS):
            return {"ok": False, "error": f"A Short must be {int(HARD_MIN_SECONDS)}-{int(MAX_SECONDS)} seconds long "
                                          f"(this one is {e - s:.0f} s)."}
        hook, kicker, auto_title = (m.get("hook"), m.get("kicker"), m.get("title"))
        if not landscape and (hook is None or kicker is None):
            i, j = sentence_range(ctx, s, e)
            if i >= 0:
                h2, k2, t2 = hook_for(ctx, i, j)
                hook = h2 if hook is None else hook
                kicker = k2 if kicker is None else kicker
                auto_title = auto_title or t2
        sid = (str(inp.get("short_id") or "") if len(asked) == 1 else "") or (str(ids[k]) if k < len(ids) else "")
        jobs.append({"start": s, "end": e, "hook": _clean_hook(hook or "") if not landscape else "",
                     "kicker": _clean_hook(kicker or "", 32).upper() if not landscape else "",
                     "title": _clean_hook(auto_title or hook or "", 100), "short_id": sid or uuid.uuid4().hex[:12]})
    audio = str(inp.get("audio_url") or (doc.get("audio") or {}).get("url") or "")
    if not audio:
        return {"ok": False, "error": "The narration's link is missing."}
    report("Getting the narration", 2)
    from . import storage
    narration = storage.download(audio, os.path.join(work, "narration" + (_ext(audio, "audio") if
                                                                          _ext(audio, "audio") != ".jpg" else ".m4a")),
                                 timeout=120)
    opts = {"aspect": "landscape" if landscape else "vertical", "fps": int(inp.get("fps") or SHORT_FPS),
            "music": inp.get("music", True), "captions": inp.get("captions", True),
            "hook_seconds": inp.get("hook_seconds") or HOOK_SECONDS, "accent": inp.get("accent") or ACCENT,
            "analyse_seconds": inp.get("analyse_seconds") or ANALYSE_SECONDS}
    for key in ("_fetch", "_detect_clip", "_detect_still"):
        if key in inp:
            opts[key] = inp[key]
    upload = inp.get("upload") == "r2"
    if upload:
        from . import r2
        if not r2.enabled():
            return {"ok": False, "error": "This worker cannot save the Short (R2 is not configured)."}
    results: List[dict] = []
    errors: List[str] = []
    project_id = re.sub(r"[^A-Za-z0-9_-]", "", str(inp.get("project_id") or "")) or "local"
    for k, job in enumerate(jobs):
        def sub(step, pct=None, **fields):
            base = int(100 * k / max(1, len(jobs)))
            span = 100.0 / max(1, len(jobs))
            label = step if len(jobs) == 1 else f"{step} ({k + 1} of {len(jobs)})"
            report(label, None if pct is None else int(base + span * pct / 100.0), **fields)
        try:
            res = make_one(doc, ctx, job, narration, work, opts, report=sub,
                           render_fn=inp.get("_render"), finalize_fn=inp.get("_finalize"))
            if upload:
                sub("Saving the Short", 96)
                res = _upload(res, project_id, title, k, landscape)
            res["index"] = k
            results.append(res)
        except Exception as e:  # noqa: BLE001 - one Short failing never loses the others
            import traceback
            traceback.print_exc()
            errors.append(f"Short {k + 1}: {type(e).__name__}: {str(e)[:400]}")
    for r in results:
        if upload:
            r.pop("local_path", None)
            r.pop("local_poster", None)
    out = {"ok": bool(results) and not errors, "shorts": results, "elapsed": round(time.time() - started, 1)}
    if picked:
        out["candidates"] = [{k: v for k, v in m.items() if k != "parts"} for m in picked]
    if errors:
        out["error"] = "; ".join(errors)[:800]
    return out
