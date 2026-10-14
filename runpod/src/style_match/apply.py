"""
Style Match: make a timeline in a Style Kit's style (2026-10-14).

    apply(doc, kit, *, face_at=None, captions_on_narration=None) -> report     (changes doc in place, never raises)

The kit's elements become Smart Editor motion specs (the one renderer, remotion components/smart) placed by the
kit's own TRIGGERS on the narration's word times - deterministically, with no model call:

  speech            captions: phrases of the kit's word count, cut at pauses and at shot changes
  punchline         pops: the last words of an exclaimed / questioned / quoted sentence, as they are said
  date_number       every date and number on its word ("480 BC", "13", "1985")
  first_appearance  a person's name the first time it is said (+ the kit's ring when it has one)
  keyword / place   names and places on their word
  segment_start     the first words after a long pause
  reaction marks    the kit's arrow / pointer on a face (needs face_at; never guessed)

Each element keeps the kit's frequency (per minute, never more than the reference), its measured look (library
font with the measured stretch / slant, cap height, fill, outline, glow band, shadow, box, tilt), entrance (cut,
per-letter pop with its stagger and overshoot, slide, fade, scale), hold growth and exit (a hard cut by default).
Then the rest of the style: scene transitions in the kit's shares, camera pushes, the grade's measured look,
the music level under the voice, SFX on cuts and graphics at the measured rates. The planner's own text looks
are replaced (a style is one design system); maps and real-data graphics stay.
"""
import hashlib
import math
import re
from typing import Callable, Dict, List, Optional

SPEC_VARIANT = "smart-spec"
SPEC_TEMPLATE = "SMART_SPEC"
_KEEP_LOOK = re.compile(r"map|chart|data|photo|card|split|compare|timeline", re.I)
_MONTHS = ("january february march april may june july august september october november december "
           "jan feb mar apr jun jul aug sep sept oct nov dec").split()
_STOP = set("the a an and or but so of to in on at for with from by as is was were be been are it its this that "
            "these those he she they we you i his her their our my your there here then than when what who whom "
            "which while after before during into over under about just also very really one two".split())


def _words(doc: dict) -> List[dict]:
    out = []
    for si, s in enumerate(doc.get("scenes") or []):
        for w in s.get("words") or []:
            try:
                out.append({"t": str(w.get("text") or w.get("word") or "").strip(), "s": float(w["start"]),
                            "e": float(w["end"]), "scene": si, "clip": bool(w.get("clip"))})
            except (KeyError, TypeError, ValueError):
                continue
    return [w for w in sorted(out, key=lambda w: w["s"]) if w["t"]]


def _seed(*parts) -> int:
    return int(hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


# ------------------------------------------------------------------ events from triggers
def _sentences(words: List[dict]) -> List[List[dict]]:
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        gap = words[i + 1]["s"] - w["e"] if i + 1 < len(words) else 9
        if re.search(r"[.!?]['\"]?$", w["t"]) or gap > 0.8:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _clean(t: str) -> str:
    return re.sub(r"^[^\w$]+|[^\w%!?'.]+$", "", t)


def caption_events(words: List[dict], scenes: List[dict], fps: float, wmin: int, wmax: int) -> List[dict]:
    cuts = {int(s.get("startFrame") or 0) / fps for s in scenes[1:]}
    ev, cur = [], []

    def flush():
        if cur:
            ev.append({"t0": cur[0]["s"], "t1": cur[-1]["e"] + 0.12, "text": " ".join(_clean(w["t"]) or w["t"] for w in cur),
                       "kind": "caption"})
    for i, w in enumerate(words):
        if cur and (len(cur) >= wmax or w["s"] - cur[-1]["e"] > 0.35
                    or any(cur[-1]["e"] - 0.05 <= c <= w["s"] + 0.05 for c in cuts) and len(cur) >= wmin):
            flush()
            cur = []
        cur.append(w)
        if len(cur) >= wmin and re.search(r"[.!?,;:]$", w["t"]):
            flush()
            cur = []
    flush()
    # back to back: each caption ends where the next starts (a swap in the same box, never a gap flicker)
    for a, b in zip(ev, ev[1:]):
        if b["t0"] - a["t1"] < 0.25:
            a["t1"] = b["t0"]
    return ev


_NUM = re.compile(r"^\$?\d[\d,.]*%?$|^\d+(st|nd|rd|th)$", re.I)
_NUMWORD = set("hundred thousand million billion trillion percent".split())


def number_events(words: List[dict]) -> List[dict]:
    ev, i = [], 0
    while i < len(words):
        t = _clean(words[i]["t"])
        low = t.lower()
        if _NUM.match(t) or low in _MONTHS:
            j = i
            parts = [t]
            while j + 1 < len(words) and len(parts) < 4:
                nx = _clean(words[j + 1]["t"])
                if _NUM.match(nx) or nx.lower() in _NUMWORD | {"bc", "ad", "b.c.", "a.d."} | set(_MONTHS) \
                        or (nx.lower() in ("percent", "%")):
                    parts.append(nx)
                    j += 1
                else:
                    break
            nxt = _clean(words[j + 1]["t"]) if j + 1 < len(words) else ""
            # "300 Spartans", "120,000 men": the noun right after a bare number belongs on the card
            if len(parts) == 1 and _NUM.match(t) and nxt and nxt.lower() not in _STOP and nxt.isalpha() and len(nxt) > 2:
                parts.append(nxt)
                j += 1
            if not (len(parts) == 1 and low in _MONTHS):
                ev.append({"t0": words[i]["s"], "word_end": words[j]["e"], "text": " ".join(parts).upper(),
                           "kind": "date_number"})
            i = j + 1
        else:
            i += 1
    return ev


def name_events(words: List[dict]) -> List[dict]:
    """Proper names (capitalised runs not at a sentence start), first mention only."""
    ev, seen, i = [], set(), 0
    while i < len(words):
        w = _clean(words[i]["t"])
        prev = words[i - 1]["t"] if i else "."
        if w[:1].isupper() and w.lower() not in _STOP and not re.search(r"[.!?]$", prev) and len(w) > 2:
            j = i
            parts = [re.sub(r"['’]s$", "", w)]
            # a name runs over capitalised words, never past a comma / full stop or a possessive
            while (j + 1 < len(words) and len(parts) < 3 and not re.search(r"[,.;:!?]$|['’]s$", words[j]["t"])
                   and _clean(words[j + 1]["t"])[:1].isupper()):
                parts.append(re.sub(r"['’]s$", "", _clean(words[j + 1]["t"])))
                j += 1
            key = " ".join(parts).lower()
            if key not in seen:
                seen.add(key)
                ev.append({"t0": words[i]["s"], "word_end": words[j]["e"], "text": " ".join(parts).upper(),
                           "kind": "name", "person": len(parts) >= 2})
            i = j + 1
        else:
            i += 1
    return ev


def punch_events(words: List[dict]) -> List[dict]:
    ev = []
    for sen in _sentences(words):
        last = sen[-1]["t"]
        txt = " ".join(w["t"] for w in sen)
        if not (last.endswith("!") or last.endswith("?") or '"' in txt or len(sen) <= 4):
            continue
        tail = sen[-min(3, len(sen)):]
        words_ = [_clean(w["t"]) for w in tail]
        ev.append({"t0": tail[0]["s"], "word_end": tail[-1]["e"], "text": " ".join(words_).upper(),
                   "kind": "punchline", "at": [w["s"] - tail[0]["s"] for w in tail]})
    return ev


def segment_events(words: List[dict]) -> List[dict]:
    ev = []
    for i in range(1, len(words)):
        if words[i]["s"] - words[i - 1]["e"] > 1.2:
            sen = []
            for w in words[i:i + 6]:
                sen.append(_clean(w["t"]))
                if re.search(r"[.!?,]$", w["t"]):
                    break
            ev.append({"t0": words[i]["s"], "word_end": words[min(len(words) - 1, i + len(sen) - 1)]["e"],
                       "text": " ".join(sen).upper(), "kind": "segment"})
    return ev


# ------------------------------------------------------------------ one element -> one motion spec
def _enter_animator(el: dict, n_units: int, at: Optional[List[float]] = None) -> Optional[dict]:
    en = el.get("enter") or {}
    k = en.get("kind") or "cut"
    over = float(en.get("overshoot") or 1.0)
    ease = "backOut" if over > 1.05 else "expoOut"
    secs = max(0.04, float(en.get("seconds") or 0.3))
    if k == "cut":
        return None
    if k == "per-letter":
        st = float(en.get("stagger") or max(0.015, secs / max(1, n_units)))
        return {"unit": "char", "stagger": round(st, 3), "dur": round(float(en.get("unitDur") or min(0.2, 3 * st)), 3),
                "ease": ease, "from": {"opacity": 0, "scale": 0.0}}
    if k == "per-word":
        a = {"unit": "word", "stagger": round(secs / max(1, n_units), 3), "dur": 0.12, "ease": ease,
             "from": {"opacity": 0, "scale": 0.2}}
        if at:
            a["at"] = [round(max(0.0, x), 3) for x in at]
        return a
    if k in ("scale", "pop"):
        return {"unit": "line", "stagger": 0, "dur": round(secs, 3), "ease": ease, "from": {"opacity": 0, "scale": 0.3}}
    if k == "slide":
        d = en.get("dir") or "from-right"
        frm = {"from-right": {"x": 3.0}, "from-left": {"x": -3.0}, "from-below": {"y": 1.5}, "from-above": {"y": -1.5}}[d] \
            if d in ("from-right", "from-left", "from-below", "from-above") else {"x": 3.0}
        return {"unit": "line", "stagger": 0, "dur": round(secs, 3), "ease": "expoOut", "from": dict(frm, opacity=0, blur=8)}
    if k == "wipe":
        return {"unit": "char", "stagger": round(secs / max(1, n_units), 3), "dur": 0.04, "ease": "hold", "from": {"opacity": 0}}
    if k == "typewriter":
        return {"unit": "char", "stagger": 0.034, "dur": 0.02, "ease": "hold", "from": {"opacity": 0}}
    return {"unit": "line", "stagger": 0, "dur": round(secs, 3), "ease": "out", "from": {"opacity": 0}}


def text_spec(el: dict, text: str, dur: float, *, x: Optional[float] = None, y: Optional[float] = None,
              fill: Optional[str] = None, at: Optional[List[float]] = None, seed: int = 0) -> dict:
    t = el["text"]
    f = t.get("font") or {}
    pos = el.get("position") or {}
    tilt = el.get("tilt") or {}
    rot = float(tilt.get("median") or 0)
    if float(tilt.get("range") or 0) > 1.5:      # the reference tilts each one a little, either way
        r = float(tilt["range"])
        rot = ((seed % 1000) / 1000 * 2 - 1) * r
    words = text.split()
    n_units = len(re.sub(r"\s", "", text)) if (el.get("enter") or {}).get("kind") in ("per-letter", "wipe") else len(words)
    from . import fonts as _fonts
    fam, wt = f.get("family") or "Montserrat", int(f.get("weight") or 800)
    em = float(t["size"]) / _fonts.cap_ratio(fam, wt)        # the measured cap height -> the face's em size
    layer = {"id": "t", "kind": "text", "text": text, "font": "lib:" + fam,
             "weight": wt, "size": round(em, 4),
             "color": fill or t["fill"], "upper": t.get("case") == "upper", "align": "center", "anchor": "c",
             "x": round(x if x is not None else float(pos.get("x") or 0.5), 4),
             "y": round(y if y is not None else float(pos.get("y") or 0.85), 4),
             "w": 0.9, "h": 0.2, "maxW": 0.9, "lineH": 1.0, "shadow": "none", "from": 0, "to": round(dur, 3),
             "keys": {}}
    if abs(float(f.get("stretch") or 1) - 1) > 0.02:
        layer["stretch"] = round(float(f["stretch"]), 3)
    if abs(float(f.get("slant") or 0)) > 0.5:
        layer["skew"] = round(float(f["slant"]), 1)
    if t.get("stroke"):
        layer["outline"] = {"w": round(float(t["stroke"]["width"]), 4), "color": t["stroke"]["color"]}
    if t.get("glow"):
        layer["band"] = {"w": round(float(t["glow"]["width"]), 4), "color": t["glow"]["color"], "soft": 0.3}
    if t.get("shadow"):
        layer["shadow"] = "hard" if float(t["shadow"].get("strength") or 0) > 0.4 else "soft"
    if t.get("box"):
        b = t["box"]
        # the box as tall as measured: the line box is one em (lineH 1.0), the rest is padding
        pad_y = (float(b["height"]) - em) / 2 if b.get("height") else float(b.get("padY") or b["padX"] * 0.6)
        layer["panel"] = {"color": b["color"], "opacity": float(b.get("opacity", 1)), "pad": round(float(b["padX"]), 4),
                          "padY": round(max(0.004, pad_y), 4), "radius": round(float(b.get("radius") or 0.012), 4),
                          "blur": 0}
    if abs(rot) > 0.3:
        # the kit's tilt is counter-clockwise positive (measured on the frame); CSS rotate is clockwise
        layer["keys"]["rot"] = [[0, round(-rot, 2)], [dur, round(-rot, 2)]]
    grow = float((el.get("hold") or {}).get("grow") or 1.0)
    if grow > 1.02:
        layer["keys"]["scale"] = [[0, 1.0], [dur, round(grow, 3), "linear"]]
    anim = _enter_animator(el, n_units, at)
    if anim:
        layer["animator"] = anim
    ex = el.get("exit") or {}
    xk = ex.get("kind") or "cut"
    exit_ = {"kind": "fade", "dur": 0.0}
    if xk == "fade":
        exit_ = {"kind": "fade", "dur": round(max(0.05, float(ex.get("seconds") or 0.3)), 3)}
    elif xk == "slide":
        exit_ = {"kind": "drop", "dur": round(max(0.05, float(ex.get("seconds") or 0.2)), 3)}
    elif xk == "scale":
        exit_ = {"kind": "scale", "dur": round(max(0.05, float(ex.get("seconds") or 0.2)), 3)}
    return {"v": 1, "persp": 1600, "layers": [layer], "exit": exit_, "drift": {"x": 0, "y": 0, "rotY": 0},
            "styleMatch": {"element": el.get("id")}}


def mark_spec(m: dict, face: dict, dur: float) -> Optional[dict]:
    """The kit's ring / arrow / pointer placed on a face {x, y, w, h} (shares of the frame)."""
    rel = m.get("relative") or {}
    fx, fy, fh = face["x"] + face["w"] / 2, face["y"] + face["h"] / 2, face["h"]
    en = m.get("enter") or {}
    secs = max(0.1, float(en.get("seconds") or 0.25))
    over = float(en.get("overshoot") or 1.0)
    col = m.get("color") or "#FF0000"
    if m["kind"] == "circle":
        d = max(0.12, float(rel.get("sizeVsFace") or 1.9) * fh)
        layer = {"id": "ring", "kind": "ellipse", "x": round(fx, 4), "y": round(fy, 4), "w": round(d * 9 / 16, 4),
                 "h": round(d, 4), "color": col, "stroke": round(float(m.get("strokeW") or 0.02), 4), "from": 0,
                 "to": round(dur, 3), "keys": {"draw": [[0, 0], [secs, 1, "out"]]}}
        return {"v": 1, "persp": 1600, "layers": [layer], "exit": {"kind": "fade", "dur": 0},
                "drift": {"x": 0, "y": 0, "rotY": 0}, "styleMatch": {"mark": m.get("id")}}
    size = float(m.get("size") or 0.2)
    dark = "#%02X%02X%02X" % tuple(int(int(col[i:i + 2], 16) * 0.6) for i in (1, 3, 5))
    if m["kind"] == "pointer":
        cx, cy = fx, max(0.05, face["y"] - 0.04 - size / 2)
        parts = [{"t": "poly", "p": [[0, 0], [1, 0], [0.5, 1]], "c": col}]
        w, h = size * 9 / 16 * 1.1, size
    else:   # arrow from below pointing up at the chin; its extruded side when the reference has one
        cx, cy = fx + float(rel.get("dx") or 0.1) * fh * 0.3, min(0.95, face["y"] + face["h"] + size / 2)
        body = [[0.5, 0], [1, 0.45], [0.68, 0.45], [0.68, 1], [0.32, 1], [0.32, 0.45], [0, 0.45]]
        parts = ([{"t": "poly", "p": [[px + 0.05, py + 0.01] for px, py in body], "c": dark}] if m.get("extrude") else []) \
            + [{"t": "poly", "p": body, "c": col}]
        w, h = size * 0.62 * 9 / 16, size
    layer = {"id": "mk", "kind": "shape", "x": round(cx, 4), "y": round(cy, 4), "w": round(w, 4), "h": round(h, 4),
             "shapes": parts, "build": "pop", "stagger": 0, "bdur": 0.01, "color": col, "from": 0, "to": round(dur, 3),
             "keys": {"scale": [[0, 0.22], [secs * 0.55, round(max(1.0, over), 3), "out"], [secs, 1.0, "out"]]}}
    return {"v": 1, "persp": 1600, "layers": [layer], "exit": {"kind": "fade", "dur": 0},
            "drift": {"x": 0, "y": 0, "rotY": 0}, "styleMatch": {"mark": m.get("id")}}


# ------------------------------------------------------------------ the whole pass
def _rate_ok(placed: List[dict], t: float, per_min: float, video_s: float) -> bool:
    if per_min <= 0:
        return False
    gap = 60.0 / per_min
    if any(abs(p["t0"] - t) < 0.55 * gap for p in placed):
        return False
    return len(placed) < max(1, int(math.ceil(per_min * video_s / 60 * 1.1)))


def _overlaps(busy: List[tuple], t0: float, t1: float, band: str) -> bool:
    return any(b == band and t0 < e and s < t1 for s, e, b in busy)


def _band(y: float) -> str:
    return "bottom" if y > 0.7 else ("top" if y < 0.3 else "middle")


def apply(doc: dict, kit: dict, *, face_at: Optional[Callable[[float], Optional[dict]]] = None,
          captions_on_narration: Optional[bool] = None, keep_looks: bool = False) -> dict:
    try:
        return _apply(doc, kit, face_at, captions_on_narration, keep_looks)
    except Exception as e:  # noqa: BLE001 - the planner's video is still a video
        return {"error": f"{type(e).__name__}: {str(e)[:200]}"}


def _apply(doc, kit, face_at, captions_on_narration, keep_looks) -> dict:
    from . import kit as kitmod
    kit = kitmod.clean(kit)
    fps = float(doc.get("fps") or 30)
    total = int(doc.get("durationInFrames") or 0)
    video_s = total / fps
    scenes = doc.get("scenes") or []
    words = _words(doc)
    els = [e for e in kit.get("elements") or [] if e.get("enabled", True)]
    marks = [m for m in kit.get("marks") or [] if m.get("enabled", True)]
    rep: Dict[str, object] = {"kit": kit.get("name"), "graphics": {}, "marks": 0}
    new_ovs: List[dict] = []
    busy: List[tuple] = []

    def add(el_or_m, spec, t0, t1, text=""):
        sf = int(round(t0 * fps))
        n = max(1, min(int(round((t1 - t0) * fps)), total - sf))
        if sf >= total or n < 3:
            return False
        new_ovs.append({"type": "motion", "variant": SPEC_VARIANT, "template": SPEC_TEMPLATE, "text": text[:120],
                        "startFrame": sf, "durationInFrames": n, "spec": spec,
                        "styleMatch": {"element": el_or_m.get("id"), "kit": kit.get("name")}})
        return True

    # 1. captions
    cap_el = next((e for e in els if e["role"] in ("caption", "subtitle")), None)
    on = (kit.get("captions") or {}).get("on") or "speech"
    narr = bool(captions_on_narration)
    # whose words: the clips' own speech (words marked "clip") and / or the narration
    cap_words = [w for w in words if w["clip"]] if on == "clip speech" else [w for w in words if not w["clip"] or on == "speech"]
    if on == "clip speech" and narr:
        cap_words = words
    if cap_el and cap_words:
        rng = (cap_el.get("trigger") or {}).get("words") or [2, 5]
        evs = caption_events(cap_words, scenes, fps, max(1, int(rng[0])), max(2, int(rng[1])))
        for ev in evs:
            dur = max(0.3, ev["t1"] - ev["t0"])
            if add(cap_el, text_spec(cap_el, ev["text"], dur), ev["t0"], ev["t0"] + dur, ev["text"]):
                busy.append((ev["t0"], ev["t0"] + dur, _band(cap_el["position"]["y"])))
        rep["graphics"][cap_el["id"]] = len(evs)
        doc.setdefault("captions", {})["enabled"] = False       # ours replace the house captions
    # 2. the other elements on their triggers
    cands = {"date_number": number_events(words), "punchline": punch_events(words), "segment_start": segment_events(words)}
    names = name_events(words)
    cands["first_appearance"] = [n for n in names if n.get("person")] or names
    cands["keyword"] = names
    cands["place"] = names
    cands["name"] = names
    used_t: List[float] = []
    for el in sorted([e for e in els if e is not cap_el], key=lambda e: -e["confidence"].get("overall", 0)):
        trig = (el.get("trigger") or {}).get("kind") or "keyword"
        pool = cands.get(trig) or []
        placed: List[dict] = []
        hold = float((el.get("hold") or {}).get("median") or 1.6)
        for ev in pool:
            t0 = ev["t0"]
            if any(abs(t0 - u) < 0.8 for u in used_t) or not _rate_ok(placed, t0, float(el["frequency"]["perMin"]), video_s):
                continue
            dur = max(hold, (ev.get("word_end", t0) - t0) + 0.6)
            dur = min(dur, max(hold * 1.6, 1.2))
            y = float(el["position"]["y"])
            x = None
            face = face_at(t0) if (face_at and el["position"].get("anchor") == "subject") else None
            if face and el["position"].get("face"):
                fr = el["position"]["face"]
                x = min(0.85, max(0.15, face["x"] + face["w"] / 2 + float(fr["dx"]) * face["h"] * 9 / 16))
                y = min(0.9, max(0.12, face["y"] + face["h"] / 2 + float(fr["dy"]) * face["h"]))
            if _overlaps(busy, t0, t0 + dur, _band(y)):
                continue
            fill = None
            if el.get("variants") and len(placed) % 4 == 3:
                fill = el["variants"][0]["fill"]
            spec = text_spec(el, ev["text"], dur, x=x, y=y, fill=fill, at=ev.get("at"), seed=_seed(ev["text"], t0))
            if add(el, spec, t0, t0 + dur, ev["text"]):
                placed.append(ev)
                used_t.append(t0)
                busy.append((t0, t0 + dur, _band(y)))
                # the ring that comes with a name label
                ring = next((m for m in marks if m["kind"] == "circle"), None)
                if ring and trig == "first_appearance" and face:
                    ms = mark_spec(ring, face, dur)
                    if ms and add(ring, ms, t0, t0 + dur, "ring"):
                        rep["marks"] = int(rep["marks"]) + 1
        rep["graphics"][el["id"]] = len(placed)
    # 3. reaction marks (arrow / pointer) on faces, at the kit's rate, on exclaimed lines
    for m in marks:
        if m["kind"] == "circle" or not face_at:
            continue
        placed = []
        for ev in cands["punchline"]:
            t0 = max(0.0, ev["t0"] - 0.2)
            if not _rate_ok(placed, t0, float(m["frequency"]["perMin"]), video_s):
                continue
            face = face_at(t0)
            if not face:
                continue
            dur = float((m.get("hold") or {}).get("median") or 1.2)
            spec = mark_spec(m, face, dur)
            if spec and add(m, spec, t0, t0 + dur, m["kind"]):
                placed.append({"t0": t0})
                rep["marks"] = int(rep["marks"]) + 1
    # the planner's word looks give way (a style is one design system); maps and data stay
    kept = [o for o in doc.get("overlays") or [] if keep_looks or _KEEP_LOOK.search(str(o.get("template") or "") + str(o.get("variant") or ""))]
    rep["droppedLooks"] = len(doc.get("overlays") or []) - len(kept)
    doc["overlays"] = sorted(kept + new_ovs, key=lambda o: o["startFrame"])
    # 4. transitions in the kit's shares (deterministic: every k-th cut), a flash after the hook when it has one
    shares = (kit.get("transitions") or {}).get("shares") or {}
    names_ = {"flash": "flash", "dip": "dip", "crossfade": "crossfade", "whip": "whip-pan"}
    n_tr = 0
    for i, s in enumerate(scenes):
        if i == 0:
            continue
        cur = str(s.get("transition") or "none")
        if cur.startswith("pack:"):
            continue
        pick = "none"
        for k, v in sorted(shares.items(), key=lambda kv: -kv[1]):
            if k in names_ and v > 0.004 and (_seed(i, k) % 1000) / 1000 < v:
                pick = names_[k]
                break
        s["transition"] = pick
        n_tr += pick != "none"
    hook = (kit.get("structure") or {}).get("hookEnds")
    if hook and shares.get("flash"):
        j = min(range(len(scenes)), key=lambda i: abs(int(scenes[i].get("startFrame") or 0) / fps - float(hook)))
        if j > 0:
            scenes[j]["transition"] = "flash"
            n_tr += 1
    rep["transitions"] = n_tr
    # 5. camera: a slow push on the kit's share of shots, still otherwise (no random drift the reference never had)
    cam = kit.get("camera") or {}
    push = float(cam.get("pushInShare") or 0)
    for i, s in enumerate(scenes):
        if (s.get("media") or {}).get("type") in ("image", "video"):
            s["motion"] = "push-in" if (_seed("cam", i) % 1000) / 1000 < push else (
                s.get("motion") if (s.get("media") or {}).get("type") == "image" and push > 0.05 else "none")
    # 6. grade: the measured look as the renderer's custom look
    g = (kit.get("grade") or {}).get("filter") or {}
    if g:
        warm = float(g.get("warmth") or 0)
        doc["grade"] = dict(doc.get("grade") or {"normalize": True, "strength": 1}, preset="neutral",
                            look={"lift": 0.01 + 0.04 * float(g.get("grain") or 0), "gain": 0.99, "pivot": 0.42,
                                  "contrast": round(float(g.get("contrast") or 1.0) * 1.04, 3),
                                  "sat": round(float(g.get("saturation") or 1.0), 3),
                                  "tint": [round(1 + 0.08 * warm, 4), 1.0, round(1 - 0.08 * warm, 4)]})
    # 7. audio: music under the voice by the measured dB; SFX on the measured share of cuts and graphics
    au = kit.get("audio") or {}
    under = float(au.get("musicUnderVoiceDb") or 18)
    if doc.get("music") and doc.get("bgm"):
        try:
            from .. import timeline
            lv = doc["music"].get("levels") or {}
            voice = float(lv.get("voiceLufs") or -20)
            track = float(lv.get("trackLufs") or timeline.track_lufs_of(doc["bgm"]))
            duck = float(doc["music"].get("duck") or 0.8) or 0.8
            level = min(1.0, 10 ** ((voice - under - track) / 20) / duck) if au.get("music") != "none" else 0.0
            doc["music"] = timeline.music_flat(doc["music"], doc["bgm"], int(fps), total, voice, level)
            rep["musicLevel"] = round(level, 3)
        except Exception as e:  # noqa: BLE001
            rep["musicError"] = type(e).__name__
    sfx = au.get("sfx") or {}
    rows = [r for r in doc.get("sfx") or [] if r.get("kind") not in ("transition", "smart", "look")]
    on_cuts = float(sfx.get("onCuts") or 0)
    lvl = float(sfx.get("levelVsVoiceDb") if sfx.get("levelVsVoiceDb") is not None else -6)
    vol = round(min(0.9, 10 ** ((lvl - 4) / 20)), 3)
    for i, s in enumerate(scenes[1:], 1):
        if on_cuts > 0.04 and (_seed("sfx", i) % 1000) / 1000 < on_cuts:
            rows.append({"name": "whoosh-fast" if i % 2 else "swipe", "startFrame": max(0, int(s.get("startFrame") or 0) - 4),
                         "durationFrames": int(fps), "kind": "transition", "volume": vol})
        if s.get("transition") == "flash":
            rows.append({"name": "camera-flash-pop", "startFrame": int(s.get("startFrame") or 0), "durationFrames": int(fps),
                         "kind": "transition", "volume": vol})
    for el in els:
        if float((el.get("sfx") or {}).get("share") or 0) > 0.15:
            for o in new_ovs:
                if o["styleMatch"]["element"] == el["id"] and (_seed("el", o["startFrame"]) % 100) / 100 < el["sfx"]["share"]:
                    rows.append({"name": "pop", "startFrame": o["startFrame"], "durationFrames": int(fps), "kind": "smart",
                                 "volume": vol})
    doc["sfx"] = sorted(rows, key=lambda r: r.get("startFrame", 0))
    doc.setdefault("meta", {})["styleMatch"] = {"kit": kit.get("name"), "id": kit.get("id"), "report": rep}
    return rep


# ------------------------------------------------------------------ pipeline hooks
def config_overrides(kit: dict) -> dict:
    """The planner settings that give a video the kit's pace (merged under the job's own "config")."""
    p = kit.get("pacing") or {}
    sh = p.get("shot") or {}
    med = float(sh.get("median") or 4.0)
    tgt = max(2.0, min(9.0, med * 1.1))
    out = {"TARGET_SCENE_SECONDS": round(tgt, 2),
           "MIN_SCENE_SECONDS": round(max(1.5, min(tgt - 0.5, float(sh.get("p10") or med * 0.5) * 1.2)), 2),
           "MAX_SCENE_SECONDS": round(max(tgt + 1.0, min(12.0, float(sh.get("p90") or med * 2))), 2)}
    hook, body = float(p.get("hookCutsPerMin") or 0), float(p.get("bodyCutsPerMin") or 0)
    if hook and body:
        out["CUT_HOOK_FACTOR"] = round(max(0.5, min(1.0, body / hook)), 2)
    he = (kit.get("structure") or {}).get("hookEnds")
    if he:
        out["HOOK_SECONDS"] = round(max(6.0, min(40.0, float(he))), 1)
    if float((kit.get("layouts") or {}).get("blurFillShare") or 0) > 0.1:
        out["ALLOW_VERTICAL"] = True
    # the kit draws its own graphics: the planner keeps maps / data, few word looks
    out["GRAPHICS_DENSITY"] = "low"
    return out


def prepare_input(inp: dict) -> Optional[dict]:
    """A job's style kit, cleaned, with its pace folded into inp["config"] (the job's own values win)."""
    k = inp.get("style_kit")
    if not isinstance(k, dict) or not k.get("elements") and not k.get("pacing"):
        return None
    from . import kit as kitmod
    k = kitmod.clean(k)
    cfg = config_overrides(k)
    if isinstance(inp.get("config"), dict):
        cfg.update(inp["config"])
    inp["config"] = cfg
    inp["style_kit"] = k
    return k


def thumb_faces(doc: dict) -> Callable[[float], Optional[dict]]:
    """face_at(t) for a planned document: the largest face in the shot on screen at t (its thumbnail, YuNet)."""
    fps = float(doc.get("fps") or 30)
    scenes = doc.get("scenes") or []
    cache: Dict[int, Optional[dict]] = {}

    def at(t: float) -> Optional[dict]:
        f = int(t * fps)
        i = next((k for k, s in enumerate(scenes) if int(s.get("startFrame") or 0) <= f
                  < int(s.get("startFrame") or 0) + int(s.get("durationInFrames") or 0)), None)
        if i is None:
            return None
        if i not in cache:
            cache[i] = None
            url = str(((scenes[i].get("media") or {}).get("thumbnail")) or "")
            if url.startswith("http"):
                try:
                    import io
                    import numpy as np
                    import requests
                    from PIL import Image
                    from .. import reframe
                    img = np.asarray(Image.open(io.BytesIO(requests.get(url, timeout=20).content)).convert("RGB"))
                    fs = reframe._yunet(img, 640, 0.6)
                    if fs:
                        b = max(fs, key=lambda r: r[2] * r[3])
                        cache[i] = {"x": b[0], "y": b[1], "w": b[2], "h": b[3]}
                except Exception:  # noqa: BLE001 - no face: no mark, never a guess
                    cache[i] = None
        return cache[i]
    return at
