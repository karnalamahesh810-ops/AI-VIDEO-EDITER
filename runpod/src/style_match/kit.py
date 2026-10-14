"""
Style Match: measurements -> the Style Kit (2026-10-14).

A Style Kit is one JSON document that says how a channel edits, in the renderer's own units (shares of the frame
height for sizes, seconds for times, hex colours, dB for levels), with a confidence per element:

    {"v": 1, "name", "summary", "source", "brand" (smart-editor kit tokens), "elements" [text looks with their
     font, colours, stroke / glow / shadow / box, position, entrance / exit, hold, trigger, frequency, sound],
     "marks" [arrows, rings, pointers], "captions" (the caption element's id + chunking rule), "pacing",
     "transitions", "camera", "layouts", "grade", "audio", "structure", "confidence"}

    build(meas)          -> kit                (fonts are matched here)
    clean(kit)           -> kit                (the app's hand edits go through this: clamps, known values only)
    card(kit)            -> markdown           (the human-readable card)
"""
import copy
import math
import re
from collections import Counter
from typing import Dict, List, Optional

from . import fonts

ENTER_KINDS = ("cut", "per-letter", "per-word", "scale", "pop", "slide", "fade", "wipe", "typewriter")
EXIT_KINDS = ("cut", "fade", "slide", "scale")
TRIGGERS = ("speech", "punchline", "keyword", "name", "first_appearance", "date_number", "place", "segment_start",
            "cut", "reaction", "every_beat")
ROLE_TRIGGER = {"caption": "speech", "subtitle": "speech", "pop": "punchline", "quote": "punchline",
                "name_label": "first_appearance", "date": "date_number", "number": "date_number",
                "label": "keyword", "lower_third": "first_appearance", "title": "segment_start",
                "chapter": "segment_start", "other": "keyword"}
NAMES = {"caption": "Captions", "pop": "Punchline pop", "name_label": "Name label", "title": "Title card",
         "label": "Label", "date": "Date label", "number": "Number card", "lower_third": "Lower third",
         "chapter": "Chapter card", "quote": "Quote", "subtitle": "Subtitles", "other": "Text"}


def _med(xs, d=None):
    xs = [x for x in xs if isinstance(x, (int, float)) and math.isfinite(x)]
    if not xs:
        return d
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else 0.5 * (xs[n // 2 - 1] + xs[n // 2])


def _maj(xs, d=None):
    xs = [x for x in xs if x is not None]
    if not xs:
        return d, 0.0
    c = Counter(xs).most_common(1)[0]
    return c[0], c[1] / len(xs)


def _rgb(h: str):
    h = str(h or "#000000").lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if len(h) == 6 else (0, 0, 0)


def _hex_med(hs: List[str]) -> Optional[str]:
    hs = [h for h in hs if isinstance(h, str) and re.match(r"^#[0-9A-Fa-f]{6}$", h)]
    if not hs:
        return None
    cs = [_rgb(h) for h in hs]
    return "#%02X%02X%02X" % tuple(int(_med([c[i] for c in cs])) for i in range(3))


def _cdist(a: str, b: str) -> float:
    return max(abs(x - y) for x, y in zip(_rgb(a), _rgb(b)))


def _near_cut(t: float, cuts: List[float], win: float = 0.17) -> bool:
    import bisect
    i = bisect.bisect_left(cuts, t - win)
    return i < len(cuts) and abs(cuts[i] - t) <= win


def _norm(w: str) -> str:
    return re.sub(r"[^0-9a-z]", "", str(w).lower())


def _spoken(text: str, t0: float, words: List[dict]) -> Optional[float]:
    """Seconds from the first matching spoken word to the text's appearance (+ = after the word), None = unsaid."""
    toks = [_norm(w) for w in re.split(r"\s+", text or "") if _norm(w) and len(_norm(w)) > 1]
    if not toks or not words:
        return None
    near = [w for w in words if t0 - 4.0 <= w["s"] <= t0 + 2.0]
    for tok in toks[:3]:
        for w in near:
            if _norm(w["w"]) == tok or (len(tok) > 3 and _norm(w["w"]).startswith(tok[:4])):
                return round(t0 - w["s"], 2)
    return None


def _role_of(samples: List[dict]) -> tuple:
    roles = [((s.get("vision") or {}).get("role") or None) for s in samples]
    graphic = [((s.get("vision") or {}).get("graphic")) for s in samples]
    specific = [r for r in roles if r and r != "other"]
    role, agree = _maj(specific, None) if specific else _maj(roles, None)
    g, _ = _maj([x for x in graphic if isinstance(x, bool)], None)
    return role, agree, g


def _element(g: dict, meas: dict, idx: int) -> Optional[dict]:
    S = [s for s in g.get("samples") or [] if s.get("fill")]
    if not S:
        return None
    role, role_agree, graphic = _role_of(S)
    if graphic is False or role in ("logo", "source_text", "other"):
        return {"_ignored": True, "role": role, "colour": g["colour"], "count": g["count"],
                "why": "part of the footage" if graphic is False else role}
    said = [((s.get("vision") or {}).get("text") or "").strip() for s in S]
    seen = sum(1 for s in S if s.get("vision"))
    if role is not None and sum(1 for t in said if t) * 2 < max(1, seen):
        return {"_ignored": True, "role": role, "colour": g["colour"], "count": g["count"], "why": "no readable text"}
    # the read text must be the measured line: its width / height has to fit the glyph mask (a model that read
    # a caption beside a red shirt, or a sign, is caught here), and one element type keeps one fill colour
    fits = 0
    for s_, t_ in zip(S, said):
        m_ = s_.get("_mask")
        if t_ and m_ is not None and getattr(m_, "shape", (0, 0))[0] > 3 and fonts.pick_line(t_, m_.shape[1] / m_.shape[0]):
            fits += 1
    if role is not None and fits * 2 < sum(1 for t_ in said if t_):
        return {"_ignored": True, "role": role, "colour": g["colour"], "count": g["count"], "why": "read text is not the measured line"}
    # one element type sits in one place (or by a face) at one size; text in the footage is anywhere, any size
    import statistics as _st
    ins_ = g["instances"]
    if len(ins_) >= 3 and not g["boxed"]:
        ys_ = [(i["y0"] + i["y1"]) / 2 for i in ins_]
        hs_ = [i["h"] for i in ins_]
        near_face = sum(1 for s_ in S if s_.get("face") and abs(s_["face"]["dx"]) < 2.5 and abs(s_["face"]["dy"]) < 2.5)
        if (_st.pstdev(ys_) > 0.14 and near_face * 2 < len(S)) or _st.pstdev(hs_) / max(1e-3, _st.mean(hs_)) > 0.45:
            return {"_ignored": True, "role": role, "colour": g["colour"], "count": g["count"], "why": "no one place or size"}
    fill0 = _hex_med([s_["fill"] for s_ in S])
    if not g["boxed"] and max(_cdist(s_["fill"], fill0) for s_ in S) > 80:
        return {"_ignored": True, "role": role, "colour": g["colour"], "count": g["count"], "why": "no one look"}
    vision_ok = role is not None
    if not vision_ok:
        # pixels only: keep the clear editorial looks (boxed, or outlined and repeated)
        if not (g["boxed"] or (g["outlined"] and g["count"] >= 2)):
            return {"_ignored": True, "role": None, "colour": g["colour"], "count": g["count"], "why": "unconfirmed"}
        role = "caption" if (g["boxed"] and g["band"] == "bottom") else "label"
    insts = g["instances"]
    det = float(meas.get("detailSeconds") or 1)
    cuts = (meas.get("cuts") or {}).get("cuts") or []
    words = meas.get("words") or []
    texts = [((s.get("vision") or {}).get("text") or "") for s in S]
    # ---- type
    fill = _hex_med([s["fill"] for s in S])
    cap = _med([s.get("capH") for s in S], 0.05)
    strokes = [s.get("stroke") or {} for s in S if not s.get("box")]
    sw = _med([st.get("width") for st in strokes if st.get("width") is not None], 0.0) or 0.0
    # a "stroke" as wide as a quarter of the letters is the dark footage behind them, not an outline
    sw = min(sw, 0.16 * cap)
    stroke = {"width": round(sw, 4), "color": _hex_med([st.get("color") for st in strokes]) or "#000000"} if sw > 0 else None
    glows = [s["glow"] for s in S if s.get("glow")]
    glow = {"width": round(_med([x["width"] for x in glows]), 4), "color": _hex_med([x["color"] for x in glows])} \
        if len(glows) * 2 >= len(S) and glows else None
    shadows = [s["shadow"] for s in S if s.get("shadow")]
    shadow = {"offset": round(_med([x["offset"] for x in shadows]), 4), "strength": round(_med([x["strength"] for x in shadows]), 2)} \
        if len(shadows) * 2 >= len(S) and shadows else None
    box = None
    if g["boxed"]:
        boxes = [s for s in S if s.get("box")]
        if boxes:
            bh = _med([s.get("boxH") for s in boxes])
            box = {"color": _hex_med([s["box"] for s in boxes]), "opacity": 1.0,
                   "padX": round(_med([s.get("boxPadX") for s in boxes], 0.03), 4),
                   "padY": round(_med([s.get("boxPadY") for s in boxes], 0.02), 4),
                   "height": round(bh, 4) if bh else None, "radius": round(0.16 * (bh or 0.1), 4)}
    upper = sum(1 for t in texts if t and t == t.upper() and re.search(r"[A-Z]", t)) * 2 >= max(1, sum(1 for t in texts if t))
    # ---- font: every sample with its words, summed per family
    votes: Dict[str, dict] = {}
    for s, t in zip(S, texts):
        clean_t = re.sub(r"[^\w\s'?!.,*-]", "", t).strip()
        if s.get("_mask") is None or len(clean_t) < 2:
            continue
        for r in fonts.match(s["_mask"], clean_t, top=5):
            k = fonts.key(r["family"], r["weight"])
            v = votes.setdefault(k, dict(r, total=0.0, n=0, stretches=[], slants=[]))
            v["total"] += r["score"]
            v["n"] += 1
            v["stretches"].append(r["stretch"])
            v["slants"].append(r["slant"])
    font = None
    if votes:
        best = sorted(votes.values(), key=lambda v: -(v["total"] / max(1, len(S))))
        b = best[0]
        font = {"family": b["family"], "weight": b["weight"], "class": b["class"], "licence": b["licence"],
                "score": round(b["total"] / max(1, b["n"]), 3), "stretch": _med(b["stretches"], 1.0),
                "slant": _med(b["slants"], 0.0),
                "alternatives": [{"family": v["family"], "weight": v["weight"],
                                  "score": round(v["total"] / max(1, v["n"]), 3)} for v in best[1:4]]}
    # ---- position
    xs = [(i["x0"] + i["x1"]) / 2 for i in insts]
    ys = [(i["y0"] + i["y1"]) / 2 for i in insts]
    xspread = (max(xs) - min(xs)) if len(xs) > 2 else 0.0
    faces_ = [s["face"] for s in S if s.get("face")]
    follows = xspread > 0.25 and role in ("pop", "name_label", "quote", "label") and len(faces_) * 2 >= len(S)
    pos = {"x": round(_med(xs, 0.5), 3), "y": round(_med(ys, 0.85), 3),
           "align": "center" if abs(_med(xs, 0.5) - 0.5) < 0.08 else ("left" if _med(xs, 0.5) < 0.5 else "right"),
           "anchor": "subject" if follows else "fixed"}
    if box and S[0].get("boxCenterY"):
        pos["y"] = round(_med([s.get("boxCenterY") for s in S if s.get("boxCenterY")], pos["y"]), 3)
    if follows:
        pos["face"] = {"dx": round(_med([f["dx"] for f in faces_]), 2), "dy": round(_med([f["dy"] for f in faces_]), 2)}
    tilts = [s.get("tilt") for s in S if s.get("tilt") is not None]
    tilt = {"median": round(_med(tilts, 0.0), 1), "range": round(_med([abs(t) for t in tilts], 0.0), 1)}
    # ---- motion
    ins = [s.get("in") or {} for s in S]
    outs = [s.get("out") or {} for s in S]
    ek, e_agree = _maj([x.get("kind") for x in ins], "cut")
    if ek == "per-letter" and role == "caption":
        ek = "cut"
    enter = {"kind": ek, "seconds": round(_med([x.get("seconds") for x in ins if x.get("kind") == ek], 0.0) or 0.0, 3),
             "overshoot": round(_med([x.get("overshoot") for x in ins if x.get("kind") == ek], 1.0) or 1.0, 2)}
    if ek == "slide":
        enter["dir"], _ = _maj([x.get("dir") for x in ins if x.get("kind") == "slide"], "from-right")
    if ek == "per-letter":
        n_chars = _med([len(re.sub(r"\s", "", t)) for t in texts if t], 8)
        enter["stagger"] = round(max(0.01, enter["seconds"] / max(1, n_chars)), 3)
        enter["unitDur"] = round(min(0.2, 3 * enter["stagger"]), 3)
    xk, x_agree = _maj([x.get("kind") for x in outs], "cut")
    exit_ = {"kind": xk, "seconds": round(_med([x.get("seconds") for x in outs if x.get("kind") == xk], 0.0) or 0.0, 3)}
    durs = [i["t1"] - i["t0"] for i in insts]
    on_cut_in = sum(1 for i in insts if _near_cut(i["t0"], cuts)) / len(insts)
    on_cut_out = sum(1 for i in insts if _near_cut(i["t1"], cuts)) / len(insts)
    exit_["onCut"] = round(on_cut_out, 2)
    grow = _med([i.get("growth") for i in insts if i.get("growth")], 1.0)
    hold = {"median": round(_med(durs, 1.5), 2), "p10": round(sorted(durs)[len(durs) // 10], 2),
            "p90": round(sorted(durs)[min(len(durs) - 1, len(durs) * 9 // 10)], 2),
            "grow": round(grow, 3) if grow and 1.04 < grow < 1.4 else 1.0}
    # ---- trigger
    lags = [x for x in (_spoken(t, s["inst"]["t0"], words) for s, t in zip(S, texts)) if x is not None]
    spoken_share = len(lags) / max(1, sum(1 for t in texts if t))
    trig = ROLE_TRIGGER.get(role, "keyword")
    n_words = _med([len(t.split()) for t in texts if t], 3)
    trigger = {"kind": trig, "onCut": round(on_cut_in, 2), "spokenShare": round(spoken_share, 2),
               "lag": round(_med(lags, 0.0), 2) if lags else None,
               "words": [max(1, int(n_words) - 2), int(n_words) + 2] if role in ("caption", "subtitle") else None}
    if role == "caption":
        trigger["note"] = "every phrase of speech, cut at camera changes"
    elif trig == "punchline":
        trigger["note"] = "the punchline / reaction words as they are said"
    elif trig == "first_appearance":
        trigger["note"] = "the first time a person is on screen in a segment"
    elif trig == "date_number":
        trigger["note"] = "every date and number on its spoken word"
    elif trig == "segment_start":
        trigger["note"] = "the start of each segment"
    else:
        trigger["note"] = "names, places and key terms on their spoken word"
    per_min = len(insts) / (det / 60)
    share = sum(durs) / det
    # ---- sound on its entrance (excess rate over the random baseline)
    au = meas.get("audio") or {}
    on = au.get("_onsets") or []
    base = float((au.get("sfx") or {}).get("baseRate") or 0)
    hit = sum(1 for i in insts if any(abs(o - i["t0"]) <= 0.15 for o in on)) / len(insts)
    sfx_share = max(0.0, (hit - base) / max(1e-6, 1 - base))
    # ---- variants (other colours of the same role are merged in later)
    el = {"id": f"{role}-{idx}", "role": role, "name": NAMES.get(role, "Text"),
          "text": {"font": font, "case": "upper" if upper else "as-written", "size": round(cap, 4), "fill": fill,
                   "stroke": stroke, "glow": glow, "shadow": shadow, "box": box},
          "position": pos, "tilt": tilt, "enter": enter, "exit": exit_, "hold": hold, "trigger": trigger,
          "frequency": {"perMin": round(per_min, 2), "screenShare": round(share, 3), "count": len(insts)},
          "sfx": {"share": round(sfx_share, 2)},
          "examples": [{"t": s["inst"]["t0"], "text": t} for s, t in zip(S, texts) if t][:4],
          "variants": [],
          "confidence": {},
          "_spans": [(i["t0"], i["t1"]) for i in insts], "_y": pos["y"],
          "_read": [(s["t"], t) for s, t in zip(S, texts) if t]}
    c = el["confidence"]
    c["font"] = round(min(1.0, (font or {}).get("score", 0) / 0.75), 2) if font else 0.0
    fills = [s["fill"] for s in S]
    c["colors"] = round(max(0.2, 1 - _med([_cdist(f, fill) for f in fills], 0) / 120), 2)
    c["size"] = round(max(0.3, 1 - (max(s.get("capH", cap) for s in S) - min(s.get("capH", cap) for s in S)) / max(1e-3, cap)), 2)
    c["motion"] = round(min(1.0, 0.45 * e_agree + 0.35 * x_agree + 0.2 * min(1, len(S) / 3)), 2)
    c["trigger"] = round(min(1.0, (0.5 if vision_ok else 0.25) + 0.3 * role_agree + (0.2 if lags else 0.0)), 2)
    c["overall"] = round(sum(c.values()) / len(c), 2)
    return el


def _merge_variants(els: List[dict]) -> List[dict]:
    """Same role + same look but another colour (a second speaker's captions): one element with variants."""
    out: List[dict] = []
    for e in sorted(els, key=lambda e: -e["frequency"]["screenShare"]):
        for o in out:
            if o["role"] == e["role"] and bool(o["text"]["box"]) == bool(e["text"]["box"]) \
                    and abs(o["position"]["y"] - e["position"]["y"]) < 0.12 and abs(o["text"]["size"] - e["text"]["size"]) < 0.4 * o["text"]["size"]:
                o["variants"].append({"fill": e["text"]["fill"], "share": e["frequency"]["screenShare"],
                                      "when": "another speaker" if o["role"] in ("caption", "subtitle", "pop") else "alternate"})
                o["frequency"]["count"] += e["frequency"]["count"]
                o["frequency"]["perMin"] = round(o["frequency"]["perMin"] + e["frequency"]["perMin"], 2)
                o["frequency"]["screenShare"] = round(o["frequency"]["screenShare"] + e["frequency"]["screenShare"], 3)
                o["examples"] = (o["examples"] + e["examples"])[:6]
                break
        else:
            out.append(e)
    return out


def _marks(meas: dict) -> List[dict]:
    det = float(meas.get("detailSeconds") or 1)
    groups: Dict[tuple, List[dict]] = {}
    for m in meas.get("marks") or []:
        v = m.get("vision") or {}
        if v.get("mark") == "not_a_mark" or v.get("graphic") is False or not m.get("flat"):
            continue                              # part of the footage (a red shirt, a logo), not an editor's mark
        kind = {"ring": "circle", "triangle": "pointer"}.get(m["shape"], m["shape"])
        if v.get("mark") in ("arrow", "circle", "pointer") and kind != "circle":
            kind = v["mark"]
        groups.setdefault((kind, m["colour"]), []).append(m)
    out = []
    for (kind, col), ms in groups.items():
        # the model must have called at least one of them a drawn arrow / ring / pointer (a flat red or blue
        # shape alone may be a sign or a shirt)
        if not any((m.get("vision") or {}).get("mark") in ("arrow", "circle", "pointer") for m in ms):
            continue
        fr = [m["face"] for m in ms if m.get("face")]
        rel = None
        if fr and len(fr) * 2 >= len(ms):
            rel = {"dx": round(_med([f["dx"] for f in fr]), 2), "dy": round(_med([f["dy"] for f in fr]), 2),
                   "sizeVsFace": round(_med([f["sizeVsFace"] for f in fr]), 2)}
            if kind == "pointer":
                rel["above"] = sum(1 for f in fr if f.get("above")) * 2 >= len(fr)
        ek, ag = _maj([m.get("enter") for m in ms], "scale")
        durs = [m["t1"] - m["t0"] for m in ms]
        out.append({"id": f"{kind}-{col}", "kind": kind, "color": _hex_med([m.get("color") for m in ms]),
                    "size": round(_med([m.get("size") for m in ms], 0.2), 3),
                    "strokeW": round(_med([m.get("strokeW") for m in ms], 0.0) or 0.0, 4) or None,
                    "relative": rel, "extrude": kind == "arrow" and (_med([m.get("darkSide") for m in ms], 0) or 0) > 0.06,
                    "enter": {"kind": ek, "seconds": round(_med([m.get("enterSeconds") for m in ms], 0.2) or 0.2, 3),
                              "overshoot": round(_med([m.get("overshoot") for m in ms], 1.0) or 1.0, 2)},
                    "hold": {"median": round(_med(durs, 1.2), 2)}, "exit": {"kind": "cut"},
                    "trigger": {"kind": "reaction" if kind in ("arrow", "pointer") else "first_appearance",
                                "note": "points at the face of the person reacting / about to speak" if kind in ("arrow", "pointer")
                                else "circles the person being named"},
                    "frequency": {"perMin": round(len(ms) / (det / 60), 2), "count": len(ms)},
                    "confidence": {"overall": round(min(1.0, 0.35 + 0.15 * len(ms) + (0.2 if fr else 0) + 0.2 * ag), 2)}})
    out.sort(key=lambda m: -m["frequency"]["count"])
    return out[:6]


def _grade(g: dict) -> dict:
    if not g:
        return {}
    look = []
    if g.get("saturation", 100) < 25:
        look.append("black and white")
    elif g.get("saturation", 100) < 70:
        look.append("muted")
    elif g.get("saturation", 100) > 125:
        look.append("vivid")
    if g.get("warmth", 0) > 30:
        look.append("warm")
    elif g.get("warmth", 0) < 0:
        look.append("cool")
    if g.get("vignette", 1) < 0.8:
        look.append("vignette")
    if g.get("grain", 0) > 2.6:
        look.append("film grain")
    if g.get("contrast", 55) > 64:
        look.append("punchy contrast")
    elif g.get("contrast", 55) < 44:
        look.append("soft contrast")
    # renderer params against neutral footage (contrast ~55, saturation ~100, warmth ~22)
    return dict(g, look=look or ["natural"], filter={
        "contrast": round(max(0.85, min(1.25, g.get("contrast", 55) / 55)), 2),
        "saturation": round(max(0.0, min(1.35, g.get("saturation", 100) / 100)), 2),
        "warmth": round(max(-0.3, min(0.3, (g.get("warmth", 22) - 22) / 100)), 2),
        "vignette": round(max(0.0, min(0.6, 1 - g.get("vignette", 1))), 2),
        "grain": round(max(0.0, min(1.0, (g.get("grain", 0) - 1.6) / 4)), 2)})


def _brand(elements: List[dict], marks: List[dict], grade: dict) -> dict:
    """The Smart Editor brand-kit tokens (src/brandkits.py shape) from the measured looks."""
    accents = []
    for e in elements:
        for c in [e["text"]["fill"]] + [v["fill"] for v in e["variants"]]:
            if c and max(_rgb(c)) - min(_rgb(c)) > 60:
                accents.append((e["frequency"]["screenShare"], c))
    for m in marks:
        if m.get("color"):
            accents.append((0.01 * m["frequency"]["count"], m["color"]))
    accents.sort(key=lambda a: -a[0])
    primary = accents[0][1] if accents else "#F2C14E"
    secondary = next((c for _, c in accents if _cdist(c, primary) > 90), "#FFFFFF")
    cap = next((e for e in elements if e["role"] == "caption"), None)
    title = next((e for e in elements if e["role"] in ("pop", "title", "label", "name_label")), None) or (elements[0] if elements else None)
    num = next((e for e in elements if e["role"] in ("number", "date")), None) or title
    fam = lambda e, d: ((e or {}).get("text", {}).get("font") or {}).get("family") or d  # noqa: E731
    overs = [e["enter"].get("overshoot", 1) for e in elements]
    eds = [e["enter"].get("seconds", 0.3) for e in elements if e["enter"]["kind"] != "cut"]
    return {"colors": {"bg": (grade or {}).get("shadows") or "#111111", "bg2": "#050505", "primary": primary,
                       "secondary": secondary, "region": primary, "text": "#FFFFFF",
                       "number": (num or {}).get("text", {}).get("fill") or "#FFFFFF", "muted": "#C9CBD1",
                       "pillBg": ((cap or {}).get("text", {}).get("box") or {}).get("color") or "#000000",
                       "pillText": (cap or {}).get("text", {}).get("fill") or "#FFFFFF"},
            "fonts": {"title": fam(title, "Montserrat"), "number": fam(num, "Montserrat"),
                      "label": fam(title, "Montserrat"), "body": fam(cap, "Inter")},
            "titleWeight": ((title or {}).get("text", {}).get("font") or {}).get("weight", 800),
            "ease": "backOut" if (_med(overs, 1) or 1) > 1.05 else "expoOut", "easeSoft": "out",
            "tempo": round(max(0.4, min(2.0, (_med(eds, 0.32) or 0.32) / 0.32)), 2)}


def build(meas: dict, source: Optional[dict] = None) -> dict:
    vis = meas.get("structure") or {}
    raw = []
    ignored = []
    for i, g in enumerate(meas.get("groups") or []):
        e = _element(g, meas, i)
        if not e:
            continue
        (ignored if e.get("_ignored") else raw).append(e)
    # a type whose read texts are another (stronger) type's texts at the same moments read THAT element
    raw.sort(key=lambda e: -(e["confidence"]["overall"] * (1 + e["frequency"]["screenShare"])))
    kept_raw: List[dict] = []
    for e in raw:
        dup = any(_norm(x["text"]) == _norm(y["text"]) and abs(x["t"] - y["t"]) < 1.5
                  for o in kept_raw for x in e["examples"] for y in o["examples"])
        # ... or its readings fall while a caption somewhere else is on screen (the model read the caption)
        caps = [o for o in kept_raw if o["role"] in ("caption", "subtitle") and abs(o["_y"] - e["_y"]) > 0.2]
        if not dup and caps and e["_read"]:
            during = sum(1 for t, _ in e["_read"] if any(a <= t <= b for o in caps for a, b in o["_spans"]))
            dup = e["role"] in ("caption", "subtitle") and during * 2 > len(e["_read"])
        (ignored if dup else kept_raw).append(dict(e, why="read another element's text") if dup else e)
    raw = kept_raw
    elements = _merge_variants(raw)
    for e in elements + ignored:
        for k_ in ("_spans", "_y", "_read"):
            e.pop(k_, None)
    elements = [e for e in elements if e["frequency"]["count"] >= 2 or e["confidence"]["overall"] >= 0.6][:8]
    marks = _marks(meas)
    pace = meas.get("pacing") or {}
    cuts = (meas.get("cuts") or {})
    tr = cuts.get("transitions") or []
    dur = float(meas.get("duration") or 1)
    tcount = Counter(t["kind"] for t in tr)
    n_cuts = max(1, len(cuts.get("cuts") or []))
    au = meas.get("audio") or {}
    cam = meas.get("camera") or {}
    lay = meas.get("layouts") or {}
    grade = _grade(meas.get("grade") or {})
    cap = next((e for e in elements if e["role"] in ("caption", "subtitle")), None)
    hook_end = float(vis.get("hook_end") or 0) or None
    structure = {"coldOpen": {"seconds": float(vis.get("cold_open_end") or 0)},
                 "hookEnds": hook_end, "firstSegment": float(vis.get("first_segment_start") or 0) or None,
                 "hookFormula": vis.get("hook_formula"), "segmentPattern": vis.get("segment_pattern"),
                 "contentMix": vis.get("content_mix") or {}, "devices": vis.get("visual_devices") or [],
                 "narration": vis.get("narration"), "music": vis.get("music"),
                 "chapterBreaks": {"flashes": tcount.get("flash", 0), "dips": tcount.get("dip", 0)}}
    kit = {
        "v": 1, "name": (vis.get("style_name") or "Matched style").strip()[:60], "summary": vis.get("summary") or "",
        "source": dict(source or {}, duration=round(dur, 1), measuredSeconds=meas.get("detailSeconds"),
                       width=(meas.get("probe") or {}).get("width"), height=(meas.get("probe") or {}).get("height"),
                       fps=(meas.get("probe") or {}).get("fps")),
        "brand": _brand(elements, marks, meas.get("grade") or {}),
        "elements": elements, "marks": marks,
        "captions": {"element": cap["id"] if cap else None,
                     "on": (("clip speech" if "clip" in str(vis.get("captions_on") or "") else
                             "narration" if "narration" in str(vis.get("captions_on") or "") else "speech") if cap else None),
                     "words": (cap or {}).get("trigger", {}).get("words")},
        "pacing": {"shot": pace.get("shot"), "hookCutsPerMin": pace.get("first60CutsPerMin"),
                   "bodyCutsPerMin": pace.get("restCutsPerMin") or pace.get("cutsPerMin"),
                   "cutsPerMin": pace.get("cutsPerMin"), "hist": pace.get("hist"), "curve": pace.get("curve"),
                   "beatSeconds": round(1 / max(1e-3, (sum(e["frequency"]["perMin"] for e in elements)
                                                       + sum(m["frequency"]["perMin"] for m in marks)
                                                       + float(cam.get("punchInPerMin") or 0)
                                                       + float(pace.get("cutsPerMin") or 0)) / 60), 2)},
        "transitions": {"shares": {"cut": round(1 - sum(tcount.values()) / n_cuts, 3),
                                   **{k: round(v / n_cuts, 3) for k, v in tcount.items()}},
                        "perMin": {k: round(v / (dur / 60), 2) for k, v in tcount.items()},
                        "flashSeconds": _med([t["dur"] for t in tr if t["kind"] == "flash"], None),
                        "examples": tr[:8]},
        "camera": {"punchInPerMin": cam.get("punchInPerMin"), "punchInScale": (cam.get("punchInScale") or {}).get("median"),
                   "pushInShare": cam.get("pushInShare"), "pushRate": cam.get("pushRate"),
                   "pullOutShare": cam.get("pullOutShare")},
        "layouts": {k: lay.get(k) for k in ("blurFillShare", "pillarboxShare", "splitShare", "pipShare")},
        "grade": grade,
        "audio": {"lufs": au.get("lufs"), "musicUnderVoiceDb": au.get("musicUnderVoiceDb"), "music": au.get("music"),
                  "voiceDb": au.get("voiceDb"),
                  "sfx": {"onCuts": max((au.get("sfx") or {}).get("onCutsShare") or 0, (au.get("sfxOpening") or {}).get("onCutsShare") or 0),
                          "onCutsRaw": (au.get("sfx") or {}).get("onCutsRaw"),
                          "onElements": max((au.get("sfx") or {}).get("onElementsShare") or 0, (au.get("sfxOpening") or {}).get("onElementsShare") or 0),
                          "levelVsVoiceDb": (au.get("sfx") or {}).get("levelVsVoiceDb"),
                          "perMin": (au.get("sfx") or {}).get("onsetsPerMin")}},
        "structure": structure,
        "ignored": [{k: v for k, v in e.items() if not k.startswith("_")} for e in ignored][:12],
    }
    conf = [e["confidence"]["overall"] for e in elements] + [m["confidence"]["overall"] for m in marks]
    kit["confidence"] = {"elements": round(sum(conf) / len(conf), 2) if conf else 0.0,
                         "pacing": 0.9 if (pace.get("cuts") or 0) > 20 else 0.6,
                         "audio": 0.8 if au.get("present") else 0.0,
                         "structure": 0.7 if vis else 0.3,
                         "vision": bool(vis)}
    return clean(kit)


# ------------------------------------------------------------------ hand edits
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _f(v, lo, hi, d):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return d
    return d if not math.isfinite(x) else max(lo, min(hi, x))


def _c(v, d):
    return v.upper() if isinstance(v, str) and _HEX.match(v) else d


def clean(kit: dict) -> dict:
    """Clamp a kit (the app's hand edits come through here): unknown values fall back, never raise."""
    k = copy.deepcopy(kit if isinstance(kit, dict) else {})
    k["v"] = 1
    k["name"] = str(k.get("name") or "Matched style")[:60]
    els = []
    for e in (k.get("elements") or [])[:12]:
        if not isinstance(e, dict):
            continue
        t = e.setdefault("text", {})
        f = t.get("font") or {}
        if f and not fonts.info(f.get("family")):
            f = None
        if f:
            f["stretch"] = _f(f.get("stretch"), 0.6, 1.6, 1.0)
            f["slant"] = _f(f.get("slant"), -15, 15, 0.0)
        t["font"] = f or {"family": fonts.DEFAULT[0], "weight": fonts.DEFAULT[1], "stretch": 1.0, "slant": 0.0}
        t["size"] = _f(t.get("size"), 0.015, 0.3, 0.05)
        t["fill"] = _c(t.get("fill"), "#FFFFFF")
        for key in ("stroke", "glow"):
            s = t.get(key)
            t[key] = {"width": _f(s.get("width"), 0, 0.05, 0.003), "color": _c(s.get("color"), "#000000")} \
                if isinstance(s, dict) and _f(s.get("width"), 0, 0.05, 0) > 0 else None
        b = t.get("box")
        t["box"] = {"color": _c(b.get("color"), "#000000"), "opacity": _f(b.get("opacity"), 0, 1, 1),
                    "padX": _f(b.get("padX"), 0, 0.1, 0.03), "padY": _f(b.get("padY"), 0, 0.1, 0.02),
                    "radius": _f(b.get("radius"), 0, 0.05, 0.015), "height": b.get("height")} if isinstance(b, dict) else None
        p = e.setdefault("position", {})
        p["x"], p["y"] = _f(p.get("x"), 0.04, 0.96, 0.5), _f(p.get("y"), 0.06, 0.96, 0.85)
        p["anchor"] = p.get("anchor") if p.get("anchor") in ("fixed", "subject") else "fixed"
        en = e.setdefault("enter", {})
        en["kind"] = en.get("kind") if en.get("kind") in ENTER_KINDS else "cut"
        en["seconds"] = _f(en.get("seconds"), 0, 2.0, 0.0)
        en["overshoot"] = _f(en.get("overshoot"), 0.9, 1.4, 1.0)
        ex = e.setdefault("exit", {})
        ex["kind"] = ex.get("kind") if ex.get("kind") in EXIT_KINDS else "cut"
        ex["seconds"] = _f(ex.get("seconds"), 0, 1.5, 0.0)
        h = e.setdefault("hold", {})
        h["median"] = _f(h.get("median"), 0.4, 12, 1.5)
        h["grow"] = _f(h.get("grow"), 1.0, 1.3, 1.0)
        tr = e.setdefault("trigger", {})
        tr["kind"] = tr.get("kind") if tr.get("kind") in TRIGGERS else "keyword"
        fq = e.setdefault("frequency", {})
        fq["perMin"] = _f(fq.get("perMin"), 0, 60, 1)
        e["enabled"] = e.get("enabled", True) is not False
        els.append(e)
    k["elements"] = els
    k["marks"] = [m for m in (k.get("marks") or []) if isinstance(m, dict)][:8]
    for m in k["marks"]:
        m["color"] = _c(m.get("color"), "#FF0000")
        m["enabled"] = m.get("enabled", True) is not False
    a = k.setdefault("audio", {})
    a["musicUnderVoiceDb"] = _f(a.get("musicUnderVoiceDb"), 3, 40, 18)
    return k


# ------------------------------------------------------------------ the card
def _pct(x) -> str:
    return f"{100 * float(x):.1f}%" if isinstance(x, (int, float)) else "-"


def card(kit: dict) -> str:
    L = [f"# Style Kit: {kit.get('name')}", "", kit.get("summary") or "", ""]
    src = kit.get("source") or {}
    L.append(f"Source: {src.get('title') or src.get('url') or 'upload'} ({src.get('width')}x{src.get('height')}, "
             f"{src.get('fps')} fps, {src.get('duration')} s; elements measured on the first {src.get('measuredSeconds')} s)")
    b = kit.get("brand") or {}
    L += ["", "## Brand tokens", "", "| token | value |", "|---|---|"]
    for k_, v in (b.get("colors") or {}).items():
        L.append(f"| colour `{k_}` | {v} |")
    for k_, v in (b.get("fonts") or {}).items():
        L.append(f"| font `{k_}` | {v} |")
    L.append(f"| ease / tempo | {b.get('ease')} / {b.get('tempo')} |")
    L += ["", "## Elements", ""]
    for e in kit.get("elements") or []:
        t, en, ex = e["text"], e["enter"], e["exit"]
        f = t.get("font") or {}
        look = [f"fill {t['fill']}"]
        if t.get("stroke"):
            look.append(f"stroke {_pct(t['stroke']['width'])} {t['stroke']['color']}")
        if t.get("glow"):
            look.append(f"glow band {_pct(t['glow']['width'])} {t['glow']['color']}")
        if t.get("shadow"):
            look.append("drop shadow")
        if t.get("box"):
            look.append(f"box {t['box']['color']} pad {_pct(t['box']['padX'])}")
        L += [f"### {e['name']} (`{e['id']}`) - confidence {e['confidence'].get('overall')}", "",
              "| | |", "|---|---|",
              f"| Font | {f.get('family')} {f.get('weight')}" + (f", stretched {round(100 * f.get('stretch', 1))}%" if abs(f.get('stretch', 1) - 1) > 0.05 else "")
              + (f", slant {f.get('slant')}°" if f.get('slant') else "") + f" (match {f.get('score', '-')}) |",
              f"| Size | cap height {_pct(t['size'])} of frame height, {t.get('case')} |",
              f"| Look | {', '.join(look)} |",
              f"| Position | x {e['position']['x']}, y {e['position']['y']} ({e['position']['anchor']}), tilt {e['tilt'].get('median')}° ±{e['tilt'].get('range')} |",
              f"| Enter | {en['kind']} {en.get('seconds')} s" + (f", overshoot {en.get('overshoot')}" if en.get('overshoot', 1) > 1.03 else "") + (f", {en.get('stagger')} s per letter" if en.get('stagger') else "") + " |",
              f"| Hold | median {e['hold']['median']} s (p10 {e['hold'].get('p10')}, p90 {e['hold'].get('p90')})" + (f", grows to {e['hold']['grow']}x" if e['hold'].get('grow', 1) > 1.03 else "") + " |",
              f"| Exit | {ex['kind']} {ex.get('seconds')} s, on a cut {_pct(ex.get('onCut', 0))} |",
              f"| Trigger | {e['trigger'].get('note')} (spoken {_pct(e['trigger'].get('spokenShare', 0))}, on a cut {_pct(e['trigger'].get('onCut', 0))}) |",
              f"| How often | {e['frequency']['perMin']} per min, on screen {_pct(e['frequency'].get('screenShare', 0))} |",
              f"| Sound | {'a hit on ' + _pct(e['sfx']['share']) + ' of entrances' if e.get('sfx', {}).get('share', 0) > 0.1 else 'none'} |"]
        if e.get("variants"):
            L.append(f"| Variants | " + "; ".join(f"{v['fill']} ({v['when']})" for v in e["variants"]) + " |")
        if e.get("examples"):
            L.append(f"| Examples | " + "; ".join(f"{x['t']:.1f}s \"{x['text']}\"" for x in e["examples"][:3]) + " |")
        L.append("")
    if kit.get("marks"):
        L += ["## Marks", ""]
        for m in kit["marks"]:
            rel = m.get("relative") or {}
            L.append(f"- **{m['kind']}** {m.get('color')}, {_pct(m.get('size'))} tall"
                     + (f", {rel.get('sizeVsFace')}x the face, offset ({rel.get('dx')}, {rel.get('dy')}) face heights" if rel else "")
                     + f"; enters {m['enter']['kind']} in {m['enter']['seconds']} s, holds {m['hold']['median']} s; "
                     f"{m['frequency']['perMin']} per min; {m['trigger']['note']} (confidence {m['confidence']['overall']})")
        L.append("")
    p = kit.get("pacing") or {}
    sh = p.get("shot") or {}
    L += ["## Pacing", "", f"- Shot median {sh.get('median')} s (p10 {sh.get('p10')}, p90 {sh.get('p90')}); "
          f"hook {p.get('hookCutsPerMin')} cuts/min, body {p.get('bodyCutsPerMin')} cuts/min; a new beat every {p.get('beatSeconds')} s"]
    tr = kit.get("transitions") or {}
    L.append(f"- Transitions: " + ", ".join(f"{k_} {_pct(v)}" for k_, v in (tr.get("shares") or {}).items()))
    c = kit.get("camera") or {}
    L.append(f"- Camera: punch-ins {c.get('punchInPerMin')}/min at {c.get('punchInScale')}x, slow push on {_pct(c.get('pushInShare') or 0)} of shots")
    lay = kit.get("layouts") or {}
    L.append(f"- Layouts: blur-fill {_pct(lay.get('blurFillShare') or 0)}, split {_pct(lay.get('splitShare') or 0)}, picture-in-picture {_pct(lay.get('pipShare') or 0)}")
    g = kit.get("grade") or {}
    L.append(f"- Grade: {', '.join(g.get('look') or [])} (contrast {g.get('contrast')}, saturation {g.get('saturation')}, warmth {g.get('warmth')}, grain {g.get('grain')})")
    a = kit.get("audio") or {}
    s = a.get("sfx") or {}
    L += ["", "## Audio", "", f"- Loudness {a.get('lufs')} LUFS; music {a.get('music')}, {a.get('musicUnderVoiceDb')} dB under the voice",
          f"- SFX on {_pct(s.get('onCuts') or 0)} of cuts and {_pct(s.get('onElements') or 0)} of graphics, at {s.get('levelVsVoiceDb')} dB against the voice"]
    st = kit.get("structure") or {}
    L += ["", "## Structure", "", f"- Cold open {st.get('coldOpen', {}).get('seconds')} s; hook ends {st.get('hookEnds')} s; first segment {st.get('firstSegment')} s",
          f"- Hook formula: {st.get('hookFormula')}", f"- Segment: {st.get('segmentPattern')}",
          f"- Devices: {', '.join(st.get('devices') or [])}"]
    if kit.get("ignored"):
        L += ["", "Left out (part of the footage or unconfirmed): " + ", ".join(f"{i.get('colour')} {i.get('role') or ''} x{i.get('count')} ({i.get('why')})" for i in kit["ignored"])]
    return "\n".join(L) + "\n"
