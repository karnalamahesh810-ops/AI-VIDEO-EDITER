"""
Ambience beds and risers: the air a documentary's pictures are in, and a
breath before its biggest moments.

Beds (doc.ambience = {"enabled", "level", "beds": [...]}): every scene is read
for where it is - what its frames show (the vision model's description counts
twice), what it was searched for, what its line says - against a small
lexicon per bed (wind, water, river, rain, storm, city, crowd, fire,
machinery; aerial and satellite shots hear wind, never lapping water). The
scenes become runs of one bed at a time: a lone different or unclear scene
inside a run is bridged, a run under MIN_BED_SECONDS is dropped, and a bed
changes only at a cut, fading out over its last FADE_OUT_SECONDS and the
next one in over its first FADE_IN_SECONDS (never two beds at once). Under a
full-screen graphic (an animation scene, a chapter or title card, a map or a
blurred-backdrop look) the bed goes quiet ("holes", 0.4 s ramps).

Levels: a bed's integrated loudness sits UNDER_VOICE_DB under the narration's
(meta.voiceLufs; the music at the owner's 20% sits about 21 dB under it), a
crowd 3 dB further (voices compete with the voice), and the renderer ducks it
by DUCK while a word is spoken and lets it breathe in the pauses. "level"
(1 = as planned) is its own master, never above each bed's "ceiling"
(CEILING_UNDER_DB under the voice); the editor's sound switch (sfxEnabled
false) mutes it with the other sounds; "enabled" false turns the beds off.

Risers (doc.sfx rows of kind "riser", the soft swell riser-soft.mp3): before
the biggest reveals - a section change of the story, a chapter card, a big
figure the planner marked high - the swell peaks exactly on the reveal: the
figure look's own hit frame, or the first word of the new section. One per
RISER_GAP_SECONDS at most and RISERS_PER_MINUTE overall, best first (a pause
before the reveal, where the swell does not sit on words, counts in its
favour); never where another sound starts inside its swell. Its level is the
sound pass's riser level against the voice, RISER_GAIN_DB softer, under the
document's sfx master like every other row.

Everything here is planning over plain dicts (the document); the renderer
draws it (Main.tsx ambience beds, sfx rows).
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple

from . import config, sfxplan, templates

BEDS = ("wind", "water", "river", "rain", "storm", "city", "crowd", "fire", "machinery")
FILE_PREFIX = "amb-"
RISER = "riser-soft"

UNDER_VOICE_DB = 26.0
EXTRA_UNDER_DB = {"crowd": 3.0, "city": 1.0}
CEILING_UNDER_DB = 18.0
DUCK = 0.7
MIN_BED_SECONDS = 8.0
BRIDGE_SECONDS = 6.0
FADE_IN_SECONDS = 1.0
FADE_OUT_SECONDS = 1.2
HOLE_RAMP_SECONDS = 0.4
MIN_SCORE = 2.0

RISER_GAP_SECONDS = 50.0
RISERS_PER_MINUTE = 0.6
RISER_GAIN_DB = -3.0
RISER_START_SECONDS = 6.0       # none in the opening seconds
RISER_CLEAR_END = 4             # frames before the peak where another sound may land (the reveal's own hit)

# Words that say where a scene is. (pattern, weight); a pattern matches whole words.
_LEXICON: Dict[str, List[Tuple[str, float]]] = {
    "storm": [(r"thunder\w*|lightning|thunderstorms?|hurricanes?|tornado(?:es)?|tropical storms?|nor'?easters?|"
               r"supercells?|storm surge", 2.0), (r"storms?|stormy", 1.0)],
    "rain": [(r"rain|raining|rainfall|rainy|downpours?|drizzle|showers|monsoon|rainstorms?|umbrellas?|puddles?", 1.5),
             (r"wet|soaked", 0.5)],
    "river": [(r"rivers?|streams?|creeks?|rapids|waterfalls?|cascades?|torrent|spillways?|rushing water|"
               r"flowing water|whitewater|floodwaters?|flash floods?", 1.5), (r"current|runoff|flows?", 0.5)],
    "water": [(r"lakes?|reservoirs?|shores?|shoreline|beach(?:es)?|waves?|lapping|boats?|houseboats?|marinas?|docks?|"
               r"piers?|harbou?rs?|bays?|ocean|sea|coast\w*|kayak\w*|swimm\w*|waterfront|lakeshore|boat ramps?", 1.2),
              (r"water", 0.6)],
    "wind": [(r"wind|windy|gusts?|gusty|breeze|blizzard|dust storms?|sandstorms?|dunes?", 1.5),
             (r"desert|deserts|canyons?|mesas?|plateaus?|cliffs?|ridges?|mountains?|peaks?|summits?|snow\w*|"
              r"prairies?|plains|drought|arid|barren|badlands|bluffs?|overlook|valley|rim", 0.8),
             (r"aerial|drone|bird'?s.eye", 0.8)],
    "city": [(r"city|cities|downtown|streets?|traffic|highways?|freeways?|intersections?|urban|skyline|suburbs?|"
              r"neighbou?rhoods?|sidewalks?|avenues?", 1.2), (r"town|cars|buses|trucks|road", 0.5)],
    "crowd": [(r"crowds?|crowded|protest\w*|rall(?:y|ies)|audiences?|spectators|town hall|press conference|"
               r"hearings?|festival|stadium|packed|cheering|marchers|demonstrat\w*", 1.5),
              (r"people gathered|residents gathered|meeting", 1.0)],
    "fire": [(r"fires?|wildfires?|flames?|burning|blaze|blazes|embers|firefighters?|smoke|inferno|burned|burnt", 1.5)],
    "machinery": [(r"turbines?|generators?|power ?plant|powerhouse|factor(?:y|ies)|pumps?|pumping|machinery|"
                   r"machines?|construction|excavators?|bulldozers?|drilling|drill rigs?|cranes?|industrial|"
                   r"hydroelectric|engine room|assembly line", 1.5)],
}
_COMPILED = {k: [(re.compile(rf"\b(?:{p})\b", re.I), w) for p, w in v] for k, v in _LEXICON.items()}
# Shots seen from high above hear the wind, not water at your feet.
_AERIAL = re.compile(r"\b(aerial|drone|bird'?s.eye|from above|overhead view|high above)\b", re.I)
# Pictures that are not a place: no bed of their own.
_NOT_A_PLACE = re.compile(r"\b(satellite (?:image|imagery|view|photo)|map|maps|chart|graph|diagram|infographic|"
                          r"document|notice|letter|newspaper|article|screenshot|website|logo|illustration|"
                          r"text (?:reads|says)|headline|spreadsheet|table of)\b", re.I)
_SOURCES = (("description", 2.0), ("query", 1.0), ("subject", 1.0), ("text", 1.0))
_FULL_SCREEN_TYPES = {"chapter", "title", "map", "article-zoom", "split"}


def _scene_texts(sc: dict) -> Dict[str, str]:
    sm = sc.get("semanticMetadata") if isinstance(sc.get("semanticMetadata"), dict) else {}
    m = sc.get("media") if isinstance(sc.get("media"), dict) else {}
    return {"description": str(sm.get("contentDescription") or m.get("contentDescription") or ""),
            "query": str(sc.get("query") or sm.get("searchQuery") or ""),
            "subject": str(sm.get("subject") or ""), "text": str(sc.get("text") or "")}


def scene_scores(sc: dict) -> Dict[str, float]:
    """How strongly a scene says each bed (0 for every bed when it is no place: a graphic, a map, a document)."""
    m = sc.get("media") if isinstance(sc.get("media"), dict) else {}
    if m.get("type") not in ("video", "image"):
        return {}
    texts = _scene_texts(sc)
    if _NOT_A_PLACE.search(texts["description"]) or (not texts["description"] and _NOT_A_PLACE.search(texts["query"])):
        return {}
    scores: Dict[str, float] = {}
    for bed, pats in _COMPILED.items():
        total = 0.0
        for src, w_src in _SOURCES:
            t = texts[src]
            if not t:
                continue
            for rx, w in pats:
                hits = len(rx.findall(t))
                if hits:
                    total += w * w_src * min(2, hits)
        if total:
            scores[bed] = total
    if _AERIAL.search(texts["description"]) or _AERIAL.search(texts["query"]):
        for bed in ("water", "river", "city", "crowd"):
            if bed in scores:
                scores[bed] *= 0.3
        scores["wind"] = scores.get("wind", 0.0) + 1.5
    return scores


def scene_bed(sc: dict) -> Optional[str]:
    scores = scene_scores(sc)
    if not scores:
        return None
    best = max(BEDS, key=lambda b: (scores.get(b, 0.0), -BEDS.index(b)))
    return best if scores.get(best, 0.0) >= MIN_SCORE else None


def _graphic_spans(doc: dict) -> List[Tuple[int, int]]:
    """Frames covered by a full-screen graphic: animation scenes, chapter/title cards, maps, blurred-backdrop looks."""
    spans = []
    for sc in doc.get("scenes") or []:
        if (sc.get("media") or {}).get("type") == "animation":
            a = int(sc.get("startFrame") or 0)
            spans.append((a, a + int(sc.get("durationInFrames") or 0)))
    for ov in doc.get("overlays") or []:
        if not isinstance(ov, dict):
            continue
        t = templates.get(str(ov.get("template") or "")) or {}
        if (ov.get("backdrop") == "blur" or ov.get("fullFrame") or ov.get("type") in _FULL_SCREEN_TYPES
                or "chapter" in (t.get("cues") or [])):
            a = int(ov.get("startFrame") or 0)
            spans.append((a, a + int(ov.get("durationInFrames") or 0)))
    return sorted(spans)


def _file_lufs(name: str) -> float:
    meta = sfxplan._meta().get(FILE_PREFIX + name) or {}
    v = meta.get("lufsIntegrated", meta.get("lufs"))
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else -24.0


def bed_volume(name: str, voice_lufs=None) -> Tuple[float, float]:
    """(planned volume, ceiling) of a bed against the voice: UNDER_VOICE_DB under it, never over CEILING_UNDER_DB."""
    voice = sfxplan.voice_level(voice_lufs)
    loud = _file_lufs(name)
    under = UNDER_VOICE_DB + EXTRA_UNDER_DB.get(name, 0.0)
    vol = 10 ** ((voice - under - loud) / 20.0)
    ceiling = 10 ** ((voice - CEILING_UNDER_DB - loud) / 20.0)
    return round(min(1.0, vol), 4), round(min(1.0, ceiling), 4)


def plan_beds(doc: dict, voice_lufs=None) -> List[dict]:
    """The beds of a document (see the module notes), in time order, never two at once."""
    scenes = [s for s in doc.get("scenes") or [] if isinstance(s, dict)]
    if not scenes:
        return []
    fps = int(doc.get("fps") or 30)
    total = int(doc.get("durationInFrames") or 0) or sum(int(s.get("durationInFrames") or 0) for s in scenes)
    labels = [scene_bed(s) for s in scenes]
    graphic = [(s.get("media") or {}).get("type") == "animation" for s in scenes]
    lengths = [int(s.get("durationInFrames") or 0) for s in scenes]
    # A short scene that says nothing (or something else) between two of the same bed is bridged.
    for i in range(1, len(scenes) - 1):
        if (labels[i] != labels[i - 1] and labels[i - 1] is not None and labels[i - 1] == labels[i + 1]
                and lengths[i] <= BRIDGE_SECONDS * fps):
            labels[i] = labels[i - 1]
    runs: List[List[int]] = []                    # [label index, first scene, last scene]
    for i, lab in enumerate(labels):
        if runs and labels[runs[-1][1]] == lab:
            runs[-1][2] = i
        else:
            runs.append([i, i, i])
    # Short runs go; then same-bed runs a short unplaced stretch apart join up.
    kept = []
    for _k, a, b in runs:
        lab = labels[a]
        frames = sum(lengths[a:b + 1])
        if lab is None or frames < MIN_BED_SECONDS * fps:
            continue
        if kept and kept[-1][0] == lab:
            gap = sum(lengths[kept[-1][2] + 1:a])
            if gap <= BRIDGE_SECONDS * fps and not any(graphic[kept[-1][2] + 1:a]):
                kept[-1][2] = b
                continue
        kept.append([lab, a, b])
    holes_all = _graphic_spans(doc)
    beds = []
    for lab, a, b in kept:
        start = int(scenes[a].get("startFrame") or 0)
        end = int(scenes[b].get("startFrame") or 0) + lengths[b]
        end = min(end, total) if total else end
        if end - start < MIN_BED_SECONDS * fps:
            continue
        vol, ceiling = bed_volume(lab, voice_lufs)
        holes = [[max(0, h0 - start), min(end, h1) - start] for h0, h1 in holes_all if h0 < end and h1 > start]
        beds.append({"name": FILE_PREFIX + lab, "startFrame": start, "durationInFrames": end - start,
                     "fadeIn": int(round(FADE_IN_SECONDS * fps)), "fadeOut": int(round(FADE_OUT_SECONDS * fps)),
                     "volume": vol, "ceiling": ceiling, **({"holes": holes} if holes else {})})
    return beds


# --------------------------------------------------------------------------- #
# Risers
# --------------------------------------------------------------------------- #

BIG_CUES = {"big-number", "percent", "money", "money-compare", "change", "then-now", "count", "measurement",
            "ratio", "compare-values", "series", "level"}


def _words(doc: dict) -> List[Tuple[float, float]]:
    out = []
    for sc in doc.get("scenes") or []:
        for w in sc.get("words") or []:
            try:
                out.append((float(w["start"]), float(w["end"])))
            except (KeyError, TypeError, ValueError):
                continue
    return sorted(out)


def _pause_before(words: List[Tuple[float, float]], at: float) -> float:
    """Seconds of silence before the word that starts at or just after `at`."""
    prev_end = 0.0
    for s, e in words:
        if s >= at - 0.12:
            return max(0.0, s - prev_end)
        prev_end = max(prev_end, e)
    return 0.0


def _speech_in(words: List[Tuple[float, float]], a: float, b: float) -> float:
    return sum(max(0.0, min(e, b) - max(s, a)) for s, e in words if e > a and s < b)


def reveal_moments(doc: dict) -> List[dict]:
    """Candidate reveals: {frame (the peak), score, why}."""
    fps = int(doc.get("fps") or 30)
    scenes = doc.get("scenes") or []
    out = []
    by_id = {}
    for sc in scenes:
        by_id[sc.get("id")] = sc
    # A big figure the planner marked high: the swell peaks on its look's hit.
    for ov in doc.get("overlays") or []:
        if not isinstance(ov, dict):
            continue
        t = templates.get(str(ov.get("template") or "")) or {}
        cues = set(t.get("cues") or [])
        start = int(ov.get("startFrame") or 0)
        home = next((s for s in scenes if int(s.get("startFrame") or 0) <= start
                     < int(s.get("startFrame") or 0) + int(s.get("durationInFrames") or 0)), {})
        emph = str(ov.get("emphasis") or (home.get("visualTreatment") or {}).get("emphasis") or "")
        hit = int(round(float((t.get("defaults") or {}).get("sfxAt") or sfxplan.DEFAULT_HIT) * fps / 30.0))
        if "chapter" in cues or ov.get("type") == "chapter":
            out.append({"frame": start + hit, "score": 3.0, "why": "chapter card"})
        elif cues & BIG_CUES and emph == "high":
            out.append({"frame": start + hit, "score": 2.0, "why": f"big figure ({sorted(cues & BIG_CUES)[0]})"})
    # A new section of the story: the swell peaks on its first word.
    story = (doc.get("meta") or {}).get("story") if isinstance(doc.get("meta"), dict) else None
    for sec in (story or {}).get("sections") or []:
        i = sec.get("from") if isinstance(sec, dict) else None
        if not isinstance(i, int) or isinstance(i, bool) or i <= 0 or i >= len(scenes):
            continue
        sc = scenes[i]
        first = (sc.get("words") or [{}])[0]
        at = float(first.get("start")) if isinstance(first.get("start"), (int, float)) else None
        frame = int(round(at * fps)) if at is not None else int(sc.get("startFrame") or 0)
        out.append({"frame": frame, "score": 2.5, "why": "new section"})
    return out


def _busy(doc: dict, fps: int) -> List[Tuple[int, int]]:
    """When other sounds start and stop: the rows, the looks' own sounds, the pack transitions."""
    spans = []
    for fx in list(doc.get("sfx") or []):
        if not isinstance(fx, dict) or fx.get("kind") == "riser":
            continue
        a = int(round(float(fx.get("startFrame") or 0)))
        d = fx.get("durationFrames")
        n = int(d) if isinstance(d, (int, float)) and d > 0 else sfxplan.duration_frames(str(fx.get("name") or ""), fps)
        spans.append((a, a + n))
    if doc.get("lookSounds") is not None:
        for fx in sfxplan.builtin_busy(doc.get("overlays") or [], doc.get("scenes") or [], fps):
            a = int(fx["startFrame"])
            spans.append((a, a + int(fx.get("durationFrames") or 1)))
    for sc in doc.get("scenes") or []:
        if str(sc.get("transition") or "").startswith("pack:"):
            a = int(sc.get("startFrame") or 0)
            spans.append((a - int(0.5 * fps), a + int(1.0 * fps)))
    return spans


def plan_risers(doc: dict, voice_lufs=None) -> List[dict]:
    """The riser rows (kind "riser") before the strongest reveals (see the module notes)."""
    fps = int(doc.get("fps") or 30)
    total = int(doc.get("durationInFrames") or 0)
    if not sfxplan.exists(RISER) or total <= 0:
        return []
    peak = sfxplan.peak_frames(RISER, fps)
    length = sfxplan.duration_frames(RISER, fps)
    words = _words(doc)
    busy = _busy(doc, fps)
    graphic = _graphic_spans(doc)
    cands = []
    for c in reveal_moments(doc):
        hit = int(c["frame"])
        start = hit - peak
        if start < RISER_START_SECONDS * fps or hit >= total - fps:
            continue
        # Nothing else may start inside the swell (the reveal's own hit at its peak may).
        if any(start <= a < hit - RISER_CLEAR_END for a, _b in busy) or any(a < start < b for a, b in busy):
            continue
        a_s, h_s = start / fps, hit / fps
        speech = _speech_in(words, a_s, h_s) / max(1e-6, h_s - a_s)
        score = c["score"] + (1.0 if _pause_before(words, h_s) >= 0.3 else 0.0) - 0.8 * speech
        # A swell rising under a full-screen card that is already up adds nothing.
        if any(a <= start and hit <= b for a, b in graphic):
            score -= 1.0
        cands.append({**c, "start": start, "hit": hit, "speech": round(speech, 2), "rank": score})
    cands.sort(key=lambda c: (-c["rank"], c["hit"]))
    most = max(1, int(math.floor(RISERS_PER_MINUTE * total / fps / 60.0)))
    chosen: List[dict] = []
    for c in cands:
        if len(chosen) >= most:
            break
        if any(abs(c["hit"] - o["hit"]) < RISER_GAP_SECONDS * fps for o in chosen):
            continue
        chosen.append(c)
    vol = sfxplan.level(RISER, voice_lufs) * 10 ** (RISER_GAIN_DB / 20.0)
    rows = []
    for c in sorted(chosen, key=lambda c: c["hit"]):
        rows.append({"name": RISER, "startFrame": int(c["start"]), "volume": round(vol, 3), "kind": "riser",
                     "durationFrames": int(length), "why": c["why"]})
    return rows


# --------------------------------------------------------------------------- #
# The document
# --------------------------------------------------------------------------- #

def apply(doc: dict, voice_lufs=None) -> Dict[str, Any]:
    """
    Plan the beds (config.AMBIENCE) into doc["ambience"] and the risers
    (config.RISERS) into doc["sfx"]. Returns counts; never raises (a sound
    plan must never cost the video).
    """
    out = {"beds": 0, "risers": 0}
    try:
        voice = voice_lufs if voice_lufs is not None else (doc.get("meta") or {}).get("voiceLufs")
        if config.AMBIENCE:
            beds = plan_beds(doc, voice)
            doc["ambience"] = {"enabled": True, "level": 1.0, "duck": DUCK, "beds": beds}
            out["beds"] = len(beds)
            out["bedSeconds"] = round(sum(b["durationInFrames"] for b in beds) / max(1, int(doc.get("fps") or 30)), 1)
        if config.RISERS:
            rows = plan_risers(doc, voice)
            if rows:
                doc["sfx"] = sorted(list(doc.get("sfx") or []) + rows, key=lambda s: int(s.get("startFrame", 0)))
            out["risers"] = len(rows)
    except Exception as e:  # noqa: BLE001
        print(f"[ambience] skipped ({type(e).__name__}: {str(e)[:120]})", flush=True)
        out["error"] = type(e).__name__
    return out


def clean(doc: dict) -> int:
    """Drop beds the renderer cannot play (unknown file, bad numbers); returns how many went."""
    amb = doc.get("ambience")
    if not isinstance(amb, dict):
        return 0
    beds = amb.get("beds") if isinstance(amb.get("beds"), list) else []
    total = int(doc.get("durationInFrames") or 0)
    kept = []
    for b in beds:
        try:
            ok = (isinstance(b, dict) and str(b.get("name") or "").startswith(FILE_PREFIX) and sfxplan.exists(b["name"])
                  and 0 <= int(b["startFrame"]) < max(1, total) and int(b["durationInFrames"]) > 0
                  and 0 <= float(b.get("volume", 0)) <= 1.0)
        except (KeyError, TypeError, ValueError):
            ok = False
        if ok:
            kept.append(b)
    amb["beds"] = kept
    return len(beds) - len(kept)
