"""
The visual treatment planner: what each beat gets besides its footage.

A professionally edited faceless documentary is not footage, footage,
footage. Every twenty to forty seconds the edit leaves the picture for a
treatment that the line itself asks for: a percentage gets a gauge, a fall
of twelve feet gets a trend figure, a place gets a map, a route a drawn
route, a quote a quote card, a question a typed question, a warning a red
strip, a date a date card, a chapter a chapter title. The planner reads the
narration for those cues (and keeps whatever the AI director already
proposed), picks a template from the registry that the style pack prefers,
fills its props with the line's own words and numbers, and lays it on the
timeline with an entrance, an exit and a sound.

Rhythm is a secondary signal only: treatments are not inserted on a timer,
but two never crowd each other, a family is not repeated within a minute,
and after a long stretch of plain footage a light label is allowed where
the line offers one.
"""
import re
from typing import Any, Dict, List, Optional

from . import config, templates
from .transcribe import Segment

MIN_GAP = 12.0          # seconds between any two treatments
TAG_GAP = 8.0           # a tag riding on the footage may follow sooner
QUIET_MAX = 40.0        # after this long with plain footage a light label is allowed
FAMILY_GAP = 60.0       # the same category is not repeated within this
SFX_GAP = 20.0          # seconds between two sounds
HIGH_GAP = 6.0          # a chapter, a number or a map may follow anything after this

_MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
_PERCENT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:%|percent\b)", re.I)
_NUMBER_UNIT = re.compile(
    r"(\$?\d[\d,]*(?:\.\d+)?)\s*(million|billion|thousand|feet|foot|ft|miles?|meters?|metres?|km|"
    r"acres?|gallons?|acre-feet|people|homes?|structures?|deaths?|hours?|minutes?|days?|"
    r"tons?|degrees|inches|dollars|residents|families|vehicles|square miles)\b", re.I)
_CHANGE = re.compile(
    r"\b(fell|fallen|dropped|declined|decreased|lost|shrank|rose|risen|increased|climbed|gained|"
    r"jumped|surged|grew)\b[^.]{0,60}?(\d[\d,]*(?:\.\d+)?)\s*(percent|%|feet|ft|miles|meters|inches|"
    r"degrees|million|billion|thousand)?", re.I)
_DATE = re.compile(rf"\b(({_MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s*(?:1[89]|20)\d\d|({_MONTHS})\s+(?:1[89]|20)\d\d)\b", re.I)
_YEAR = re.compile(r"\b((?:1[89]|20)\d\d)\b")
_QUOTE = re.compile(r"[“\"]([^”\"]{12,160})[”\"]")
_SAID = re.compile(r"\b(said|says|warned|warns|according to|told|wrote|called it|described it as|put it)\b", re.I)
_WARN = re.compile(r"\b(warning|emergency|critical|danger(?:ous)?|evacuat\w*|dead pool|record (?:low|high|crest)|"
                   r"life-threatening|catastroph\w*|fatal|deadly|collapse)\b", re.I)
_VS = re.compile(r"\b(versus|vs\.?|compared (?:to|with))\b", re.I)
_ROUTE = re.compile(r"\bfrom\s+([A-Z][\w.'-]+(?:\s[A-Z][\w.'-]+){0,3})\s+to\s+([A-Z][\w.'-]+(?:\s[A-Z][\w.'-]+){0,3})")
_TWO_YEARS = re.compile(r"\b((?:19|20)\d\d)\b[^.]{0,40}?(\d[\d,]*(?:\.\d+)?)\s*(percent|%|feet|ft)?[^.]{0,60}?\b((?:19|20)\d\d)\b[^.]{0,40}?(\d[\d,]*(?:\.\d+)?)\s*(percent|%|feet|ft)?", re.I)
_UNIT_SHORT = {"feet": "FT", "foot": "FT", "ft": "FT", "mile": "MI", "miles": "MI", "meter": "M", "meters": "M",
               "metre": "M", "metres": "M", "km": "KM", "percent": "%", "%": "%", "million": "MILLION",
               "billion": "BILLION", "thousand": "THOUSAND", "degrees": "°", "inches": "IN", "dollars": "USD",
               "acre-feet": "ACRE-FT", "acres": "ACRES", "acre": "ACRES", "gallons": "GAL", "gallon": "GAL",
               "square miles": "SQ MI"}

CARD_KINDS = {"card", "map"}


def pack_for(brief: Optional[dict], requested: str = "") -> dict:
    """The style pack: the one asked for, else the one the story's kind suggests."""
    if requested and requested in templates.style_packs():
        return dict(templates.style_pack(requested), id=requested)
    kind = (brief or {}).get("kind") or ""
    name = {"news": "news", "weather": "weather", "disaster": "weather", "history": "history",
            "biography": "history", "science": "tech", "explainer": "documentary"}.get(kind, "documentary")
    return dict(templates.style_pack(name), id=name)


def _num(s: str) -> Optional[float]:
    try:
        return float(str(s).replace(",", "").replace("$", ""))
    except ValueError:
        return None


def _subject_words(shot: dict, seg: Segment, n: int = 4) -> str:
    subject = (shot.get("subject") or "").strip()
    if subject:
        return subject[:60]
    words = [w for w in re.findall(r"[A-Za-z][\w'-]*", seg.text) if w[0].isupper()]
    return " ".join(words[:n])[:60]


def _noun_after(text: str, match_end: int) -> str:
    tail = text[match_end:match_end + 60]
    m = re.match(r"\s*(?:of|in|for|at|to)?\s*(?:the|its|their)?\s*([a-z][\w-]*(?:\s[a-z][\w-]*){0,2})", tail, re.I)
    return (m.group(1) if m else "").strip().upper()[:32]


# --------------------------------------------------------------- cues
def cues_for(seg: Segment, shot: dict, brief: Optional[dict]) -> List[dict]:
    """
    What the line asks for, most specific first: [{cue, props, emphasis}].
    Only the line's own words and numbers ever reach a template.
    """
    text = seg.text or ""
    out: List[dict] = []
    m = _TWO_YEARS.search(text)
    if m and m.group(1) != m.group(4):
        a, b = _num(m.group(2)), _num(m.group(5))
        if a is not None and b is not None:
            unit = _UNIT_SHORT.get((m.group(3) or m.group(6) or "").lower(), "")
            out.append({"cue": "then-now", "emphasis": "high",
                        "props": {"text": _subject_words(shot, seg), "items": [
                            {"label": m.group(1), "value": a, "suffix": unit},
                            {"label": m.group(4), "value": b, "suffix": unit}]}})
    m = _CHANGE.search(text)
    if m and _num(m.group(2)) is not None:
        down = m.group(1).lower() in ("fell", "fallen", "dropped", "declined", "decreased", "lost", "shrank")
        out.append({"cue": "change", "emphasis": "high",
                    "props": {"value": _num(m.group(2)), "suffix": _UNIT_SHORT.get((m.group(3) or "").lower(), ""),
                              "label": "down" if down else "up", "text": _subject_words(shot, seg)}})
    m = _PERCENT.search(text)
    if m and _num(m.group(1)) is not None and not any(c["cue"] in ("then-now", "change") for c in out):
        out.append({"cue": "percent", "emphasis": "high",
                    "props": {"value": _num(m.group(1)), "suffix": "%",
                              "text": _noun_after(text, m.end()) or _subject_words(shot, seg).upper()}})
    m = _NUMBER_UNIT.search(text)
    if m and _num(m.group(1)) is not None and not out:
        unit = m.group(2).lower()
        out.append({"cue": "big-number", "emphasis": "high",
                    "props": {"value": _num(m.group(1)), "suffix": _UNIT_SHORT.get(unit, unit.upper()[:8]),
                              "text": _subject_words(shot, seg).upper()}})
    m = _QUOTE.search(text)
    if m:
        out.append({"cue": "quote", "emphasis": "high",
                    "props": {"text": m.group(1).strip(), "label": _subject_words(shot, seg)}})
    elif _SAID.search(text) and len(text) < 220:
        out.append({"cue": "quote", "emphasis": "medium",
                    "props": {"text": text.strip().rstrip("."), "label": _subject_words(shot, seg)}})
    if text.strip().endswith("?") and len(text) <= 90:
        out.append({"cue": "question", "emphasis": "medium", "props": {"text": text.strip()}})
    m = _WARN.search(text)
    if m:
        phrase = re.sub(r"[^\w\s-]", "", text[max(0, m.start() - 24):m.end() + 24]).strip().upper()
        out.append({"cue": "warning", "emphasis": "medium", "props": {"text": phrase[:40]}})
    m = _ROUTE.search(text)
    locs = shot.get("overlay", {}).get("locations") if isinstance(shot.get("overlay"), dict) else None
    if m and locs and len(locs) >= 2:
        out.append({"cue": "route", "emphasis": "high",
                    "props": {"text": f"{m.group(1)} to {m.group(2)}", "locations": locs[:2]}})
    m = _DATE.search(text)
    if m:
        out.append({"cue": "date", "emphasis": "medium", "props": {"text": m.group(1).upper()}})
    return out


# ------------------------------------------------------------ choosing
class _Rhythm:
    def __init__(self):
        # The opening counts as a visual event: no filler label in the first
        # QUIET_MAX seconds, only treatments the lines ask for.
        self.last_any = 0.0
        self.last_card = -1e9
        self.last_by_cat: Dict[str, float] = {}
        self.last_sfx = -1e9

    def allows(self, at: float, t: dict) -> bool:
        gap = at - self.last_any
        need = TAG_GAP if t["kind"] == "tag" else MIN_GAP
        if t["emphasis"] == "high":
            need = min(need, HIGH_GAP)
        if gap < need and at > 0.0:
            return False
        if at - self.last_by_cat.get(t["category"], -1e9) < FAMILY_GAP and t["emphasis"] != "high":
            return False
        if t["kind"] in CARD_KINDS and at - self.last_card < (HIGH_GAP if t["emphasis"] == "high" else MIN_GAP):
            return False
        return True

    def overlaps(self, at: float) -> bool:
        """A card is still on screen."""
        return at < self.last_card - 0.5

    def note(self, at: float, t: dict, seconds: float) -> None:
        end = at + seconds
        self.last_any = end
        self.last_by_cat[t["category"]] = end
        if t["kind"] in CARD_KINDS:
            self.last_card = end


def _from_hint(overlay: dict, pack: dict, n_locs: int, text: str) -> Optional[str]:
    """The template for an overlay the AI director or the rules proposed."""
    kind = overlay.get("type")
    variant = overlay.get("variant") or ""
    if kind == "map":
        if variant.startswith("route") or variant == "satellite-route":
            return pack["route"]
        if variant.startswith("spread") or n_locs > 1:
            return pack["multi"]
        if variant == "region":
            return pack["region"]
        return pack["map"]
    if kind == "chapter":
        return pack["chapter"]
    if kind == "lower-third":
        return pack["lowerThird"]
    options = templates.for_component(kind, pack.get("id", ""))
    if not options:
        return None
    if variant:
        for t in options:
            if t["defaults"].get("variant") == variant:
                return t["id"]
    for t in options:
        if not t["defaults"].get("variant"):
            return t["id"]
    return options[0]["id"]


def _template_for_cue(cue: str, pack: dict, used_recently: set) -> Optional[str]:
    if cue == "route":
        return pack["route"]
    if cue == "place":
        return pack["map"]
    if cue == "chapter":
        return pack["chapter"]
    options = templates.for_cue(cue, pack.get("id", ""), exclude=used_recently)
    return options[0]["id"] if options else None


def _hint_props(overlay: dict) -> dict:
    keep = {}
    for k in ("text", "subtitle", "label", "suffix", "value", "items", "locations", "highlight", "body",
              "media", "anchor", "labelPosition", "places"):
        if overlay.get(k) is not None:
            keep[k] = overlay[k]
    return keep


def plan(segments: List[Segment], shots: List[dict], scenes: List[dict], fps: int, total: int,
         brief: Optional[dict], pack: dict, seconds_for: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """
    Overlays, transitions, sounds, music sections and per-scene treatments.

    `scenes` are the built scene dicts (start/duration frames, media type);
    `seconds_for` is the renderer's minimum hold per component.
    """
    seconds_for = seconds_for or {}
    rhythm = _Rhythm()
    overlays: List[dict] = []
    treatments: List[dict] = []
    used_recently: Dict[str, float] = {}
    style = pack.get("id", "documentary")
    intensity = float(pack.get("animationIntensity", 1.0))
    hooks = set((brief or {}).get("hookBeats") or [])

    for i, seg in enumerate(segments):
        shot = shots[i] if i < len(shots) else {}
        scene = scenes[i] if i < len(scenes) else {}
        at = seg.start
        start = int(scene.get("startFrame", int(round(at * fps))))
        scene_frames = int(scene.get("durationInFrames", int(round(seg.duration * fps))))
        chosen: Optional[dict] = None
        chosen_id = ""
        props: dict = {}
        emphasis = "medium"

        hint = shot.get("overlay") if isinstance(shot.get("overlay"), dict) else None
        if hint and hint.get("type") and hint["type"] not in ("photo-card", "name-card"):
            tid = _from_hint(hint, pack, len(hint.get("locations") or hint.get("places") or []), seg.text)
            t = templates.get(tid or "")
            # The director already spaced its own proposals (_thin_overlays);
            # only a card still on screen stops one.
            if t and not (t["kind"] in CARD_KINDS and rhythm.overlaps(at)):
                chosen, chosen_id, props = t, t["id"], _hint_props(hint)
                if hint.get("motion"):
                    props["_motion"] = hint["motion"]
                emphasis = t["emphasis"]
        if chosen is None:
            for cue in cues_for(seg, shot, brief):
                recent = {k for k, v in used_recently.items() if at - v < FAMILY_GAP}
                tid = _template_for_cue(cue["cue"], pack, recent)
                t = templates.get(tid or "")
                if not t or not rhythm.allows(at, t):
                    continue
                chosen, chosen_id, props, emphasis = t, t["id"], dict(cue["props"]), cue["emphasis"]
                break
        if chosen is None and at - rhythm.last_any > QUIET_MAX and intensity >= 0.6:
            # A long stretch of plain footage: a light label, if the line names
            # a subject (the planner's, never a guessed capitalised word).
            subject = (shot.get("subject") or "").strip()[:60]
            if subject and len(subject) > 3:
                t = templates.get("TEXT_KICKER_V1")
                if t and rhythm.allows(at, t):
                    chosen, chosen_id, props, emphasis = t, t["id"], {"text": subject.upper()}, "low"

        transition_in = scene.get("transition", "none")
        entry = {
            "primaryType": ("image" if (scene.get("media") or {}).get("type") == "image" else
                            "footage" if (scene.get("media") or {}).get("type") == "video" else "empty"),
            "secondaryType": chosen["category"].lower() if chosen else None,
            "template": chosen_id or None, "variant": None, "entrance": None, "exit": None,
            "duration": None, "emphasis": emphasis if chosen else "low", "animation": None,
            "data": {}, "text": "", "mapData": None, "chartData": None, "overlays": [],
            "transitionIn": transition_in, "transitionOut": "none", "sfx": None, "musicCue": None,
        }
        if chosen:
            motion = props.pop("_motion", "")
            resolved = templates.resolve(chosen_id, style=style, entrance=motion, props=props, pack=pack)
            hold = max(resolved.get("seconds", 3.0), seconds_for.get(resolved["type"], 0.0))
            frames = min(max(scene_frames, int(round(hold * fps))), max(1, total - start))
            sfx = resolved.pop("sfx", {"name": "none", "volume": 0.0})
            overlay = {**resolved, "startFrame": start, "durationInFrames": frames}
            overlay.pop("seconds", None)
            overlays.append(overlay)
            rhythm.note(at, chosen, frames / fps)
            used_recently[chosen_id] = at
            entry.update({
                "variant": overlay.get("variant") or overlay.get("style"), "entrance": overlay.get("motion"),
                "exit": overlay.get("exit"), "duration": round(frames / fps, 2), "animation": overlay.get("motion"),
                "text": str(overlay.get("text") or ""), "overlays": [chosen_id],
                "data": {k: overlay[k] for k in ("value", "suffix", "items") if k in overlay},
                "mapData": {"locations": overlay.get("locations")} if overlay.get("locations") else None,
                "chartData": {"items": overlay.get("items")} if overlay.get("items") and chosen["category"] in ("CHARTS", "COMPARISONS", "TIMELINES") else None,
                "sfx": (sfx if sfx.get("name") not in (None, "none") else None),
            })
            if i in hooks:
                entry["emphasis"] = "high"
        treatments.append(entry)

    sfx = _plan_sfx(overlays, treatments, fps, float(pack.get("sfxIntensity", 1.0)))
    music = _plan_music(segments, brief, fps, total, hooks)
    for i, entry in enumerate(treatments):
        cue = next((s["mood"] for s in music["sections"] if s["startFrame"] <= scenes[i].get("startFrame", 0) < s["endFrame"]), None) if i < len(scenes) else None
        entry["musicCue"] = cue
    return {"overlays": overlays, "treatments": treatments, "sfx": sfx, "music": music,
            "counts": counts(scenes, overlays, sfx, music, treatments)}


def _plan_sfx(overlays: List[dict], treatments: List[dict], fps: int, intensity: float) -> List[dict]:
    """One sound per graphic moment at most every SFX_GAP seconds, the strongest moment winning."""
    rank = {"high": 0, "medium": 1, "low": 2}
    picks: List[dict] = []
    by_start = sorted((ov for ov in overlays), key=lambda o: o["startFrame"])
    emph = {}
    for tr in treatments:
        if tr.get("template"):
            emph.setdefault(tr["template"], tr["emphasis"])
    last = -1e9
    for ov in by_start:
        t = templates.get(ov.get("template") or "")
        if not t:
            continue
        s = t["defaults"].get("sfx") or {}
        if not s.get("name") or s["name"] == "none":
            continue
        at = ov["startFrame"] / fps
        e = emph.get(ov.get("template"), t["emphasis"])
        if at - last < SFX_GAP:
            if picks and rank.get(e, 9) < rank.get(picks[-1]["_e"], 9):
                picks.pop()
            else:
                continue
        picks.append({"name": s["name"], "startFrame": int(ov["startFrame"]),
                      "volume": round(min(1.0, float(s["volume"]) * intensity), 3), "_e": e})
        last = at
    for p in picks:
        p.pop("_e", None)
    return picks


def _plan_music(segments: List[Segment], brief: Optional[dict], fps: int, total: int, hooks: set) -> dict:
    """Sections with a mood and a level; the renderer ramps the music between them and keeps it under the voice."""
    moods = templates.load()["musicMoods"]
    sections = list((brief or {}).get("sections") or [])
    kind = (brief or {}).get("kind") or ""
    tense = kind in ("news", "weather", "disaster")
    out = []
    if not segments:
        return {"sections": [], "duck": 0.55}
    if not sections:
        n = len(segments)
        cuts = [0, max(1, n // 4), max(2, n // 2), max(3, (3 * n) // 4), n]
        sections = [{"from": cuts[k], "to": cuts[k + 1] - 1} for k in range(4) if cuts[k] < cuts[k + 1]]
    for k, sec in enumerate(sections):
        a, b = int(sec.get("from", 0)), int(sec.get("to", len(segments) - 1))
        a, b = max(0, min(a, len(segments) - 1)), max(0, min(b, len(segments) - 1))
        if k == 0:
            mood = "INTRO"
        elif k == len(sections) - 1:
            mood = "OUTRO" if len(sections) > 2 else "RESOLUTION"
        elif tense:
            mood = ("TENSION", "BUILD", "REVELATION")[k % 3]
        else:
            mood = ("EXPLANATION", "BUILD", "EMOTIONAL")[k % 3]
        start = int(round(segments[a].start * fps))
        end = int(round(segments[b].end * fps)) if b < len(segments) else total
        if k == len(sections) - 1:
            end = total
        out.append({"startFrame": start, "endFrame": max(start + 1, end), "mood": mood,
                    "volume": moods.get(mood, 0.12)})
    for i in sorted(hooks):
        if 0 <= i < len(segments):
            for s in out:
                if s["startFrame"] <= int(segments[i].start * fps) < s["endFrame"] and s["mood"] == "INTRO":
                    s["volume"] = max(s["volume"], moods.get("REVELATION", 0.15))
    return {"sections": out, "duck": 0.55}


def counts(scenes: List[dict], overlays: List[dict], sfx: List[dict], music: dict,
           treatments: List[dict]) -> Dict[str, Any]:
    cat = {}
    for ov in overlays:
        t = templates.get(ov.get("template") or "")
        c = t["category"] if t else "OTHER"
        cat[c] = cat.get(c, 0) + 1
    footage = sum(1 for s in scenes if (s.get("media") or {}).get("type") == "video")
    stills = [s for s in scenes if (s.get("media") or {}).get("type") == "image"]
    image_treated = sum(1 for s in stills if (s.get("motion") or "none") != "none" or (s.get("effect") or "none") != "none")
    transitions = sum(1 for s in scenes if (s.get("transition") or "none") != "none")
    text = sum(cat.get(c, 0) for c in ("TEXT", "HEADLINES", "LOWER_THIRDS", "QUOTES", "DOCUMENTS"))
    data = sum(cat.get(c, 0) for c in ("NUMBERS", "CHARTS", "COMPARISONS", "TIMELINES"))
    return {
        "scenes": len(scenes), "footage_scenes": footage, "image_scenes": len(stills),
        "text_treatments": text, "maps": cat.get("MAPS", 0), "data_graphics": data,
        "callouts": cat.get("CALLOUTS", 0), "image_treatments": image_treated,
        "transitions": transitions, "sfx": len(sfx), "music_cues": len(music.get("sections") or []),
        "total_treatments": len(overlays) + image_treated + transitions,
        "by_category": cat,
        "unique_templates": len({ov.get("template") for ov in overlays if ov.get("template")}),
    }
