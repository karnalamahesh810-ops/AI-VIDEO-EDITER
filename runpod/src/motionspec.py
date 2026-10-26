"""
The Smart Editor's design compiler: an edit director's design for one moment -> a motion spec (2026-10-14).

The AI edit director (src/smart_editor.py) does not pick a template. It designs each graphic from a grammar -
what kind of moment it is, the words, where it sits, how the type is set, how each character / word / line
moves (and whether it lands on the narration's own word times), the accents, the depth, what to mark in the
shot, the camera move on the clip, the sound and the exit. This module turns that design into the keyframed
layers the one renderer draws (remotion/src/components/smart/SmartSpec.tsx, specMath.ts), deterministically:
the same design and timing always give the same spec.

The grammar multiplies out to tens of thousands of distinct graphics (12 moves x 3 units x 4 speeds x 8
layouts x 2^11 accent sets x 6 fonts x 9 camera moves x 6 marks), and the validator in smart_editor.py
refuses a repeat of the same text animation or the same design inside a window, so a video never shows the
same graphic twice in a row the way the fixed looks did.

    compile_design(design, timing, ctx) -> spec dict | None
    clean_spec(spec, dur) -> spec dict | None        (the renderer's own clean-up, in Python, for checks)
    signature(design) -> dict                        (what "the same graphic" means for the freshness rule)

House rules baked in (memory: no-yellow-outlined-word-style, graphics-timing-rule): clean white editorial
type with one accent colour, never an outlined poster word; every text graphic gets a scrim on its side so it
reads on any footage; sizes never under the phone-readable minimum; everything inside the title-safe area.
"""
import math
import re
from typing import Dict, List, Optional, Tuple

# ------------------------------------------------------------------ vocabulary
KINDS = ("statement", "number", "date", "label", "spot", "list", "quote", "compare", "place", "card", "waffle",
         "measure", "tiles")
MOVES = ("rise", "drop", "slide-left", "slide-right", "flip-x", "flip-y", "zoom-in", "zoom-out", "blur-in",
         "track-in", "typewriter", "pop", "wipe", "spin-in", "mask-up")
UNITS = ("char", "word", "line")
SPEEDS = {"snappy": (0.32, 0.028, 0.065, 0.16), "smooth": (0.55, 0.04, 0.1, 0.22),
          "slow": (0.85, 0.06, 0.15, 0.3), "punchy": (0.24, 0.02, 0.05, 0.12)}   # dur, char, word, line stagger
LAYOUTS = ("left-third", "right-third", "center", "lower", "upper-left", "lower-center", "upper-right", "corner")
ACCENTS = ("underline-draw", "bar-left", "box-sweep", "glow", "bracket", "divider", "extrude", "kicker-tag",
           "panel-glass", "particles", "rule-top")
FONTS = ("grotesk", "kinetic", "serif", "serif-italic", "mono", "narrow", "inter")
CAMERAS = ("none", "push-in", "push-to-point", "pull-out", "whip-left", "whip-right", "shake", "drift", "dim")
MARKS = ("circle", "arrow", "box", "spotlight", "pin", "underline", "loupe")
EXITS = ("fade", "blur", "drop", "scale", "wipe")
EASES = ("expoOut", "backOut", "spring", "quintOut", "out", "inOut", "elastic")
COLORS = {"gold": "#f2c14e", "red": "#ef4b4b", "cool": "#5ec8f2", "green": "#5fd38d", "white": "#ffffff",
          "amber": "#ffb347", "violet": "#a78bfa"}

# Where each layout puts the text block: (anchor, x, y, align, scrim, max width share).
_LAYOUT = {
    "left-third": ("l", 0.07, 0.44, "left", "left", 0.44),
    "right-third": ("r", 0.93, 0.44, "right", "right", 0.44),
    "center": ("c", 0.5, 0.46, "center", "vignette", 0.72),
    "lower": ("l", 0.07, 0.72, "left", "bottom", 0.62),
    "upper-left": ("l", 0.07, 0.2, "left", "top", 0.5),
    "upper-right": ("r", 0.93, 0.2, "right", "top", 0.5),
    "lower-center": ("c", 0.5, 0.76, "center", "bottom", 0.7),
    "corner": ("l", 0.06, 0.12, "left", None, 0.4),
}
# Font size as a share of the frame height. Scaled down 2026-10-26 (the owner, the Hoover Dam video: "text animations
# bad and number animations too big"): "xl" was 0.13 (a 140 px font, a statement filling half the width) and a figure
# never under 0.095; the documentary references set their figures and statements at about half that (MagnatesMedia's
# year card: capitals ~10 % of the height; our kt-number's were 13-14 %). The same steps, about 0.6-0.75 of before.
_SIZES = {"s": 0.04, "m": 0.05, "l": 0.062, "xl": 0.075}
# A figure's own size (a counter): capitals ~7 % of the height, as the kinetic number (typeScale.json hero).
COUNTER_SIZE = 0.1
COUNTER_SIZE_SMALL = 0.06
# A name, a place or a spot label: a small clean lower third (a name never in a big dark box).
LABEL_SIZE = 0.038
MIN_TEXT = 0.034        # main text, share of the frame height (~37 px at 1080p: readable on a phone)
MIN_SUB = 0.026
SAFE_X = (0.05, 0.95)
SAFE_Y = (0.08, 0.9)


def _f(v, lo, hi, d):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return d
    return d if not math.isfinite(x) else max(lo, min(hi, x))


def _pick(v, allowed, d):
    return v if isinstance(v, str) and v in allowed else d


def _words(text: str) -> List[str]:
    return [w for w in re.split(r"\s+", str(text or "").strip()) if w]


def _norm(w: str) -> str:
    return re.sub(r"[^0-9a-z%$]", "", str(w).lower())


def text_width(text: str, size: float, font: str = "grotesk", aspect: float = 16 / 9, tracking: float = 0.0) -> float:
    """A share-of-frame-width estimate of one line of type (no measuring in Python; ~±10% for the grotesk)."""
    per = {"mono": 0.62, "narrow": 0.44, "serif": 0.5, "serif-italic": 0.48, "kinetic": 0.6}.get(font, 0.56)
    n = len(text)
    return n * size * (per + tracking) / aspect


# ------------------------------------------------------------------ the animator
def animator(move: str, unit: str, speed: str, ease: str, at: Optional[List[float]] = None) -> dict:
    dur, s_char, s_word, s_line = SPEEDS.get(speed, SPEEDS["smooth"])
    stagger = {"char": s_char, "word": s_word, "line": s_line}[unit]
    frm = {
        "rise": {"opacity": 0, "y": 0.75, "blur": 6},
        "drop": {"opacity": 0, "y": -0.75, "blur": 6},
        "slide-left": {"opacity": 0, "x": -0.9, "blur": 10},
        "slide-right": {"opacity": 0, "x": 0.9, "blur": 10},
        "flip-x": {"opacity": 0, "rotX": -95, "y": 0.25},
        "flip-y": {"opacity": 0, "rotY": 85, "x": 0.2},
        "zoom-in": {"opacity": 0, "scale": 1.9, "blur": 16},
        "zoom-out": {"opacity": 0, "scale": 0.35},
        "blur-in": {"opacity": 0, "blur": 26, "tracking": 0.22},
        "track-in": {"opacity": 0, "tracking": 0.55},
        "typewriter": {"opacity": 0},
        "pop": {"opacity": 0, "scale": 0.2},
        "wipe": {},
        "spin-in": {"opacity": 0, "rot": -28, "scale": 0.6, "y": 0.3},
        "mask-up": {"opacity": 0, "y": 1.05},
    }.get(move, {"opacity": 0, "y": 0.75, "blur": 6})
    if move == "typewriter":
        unit, stagger, dur, ease = "char", 0.034, 0.02, "hold"
    if move == "pop" and ease in ("out", "inOut"):
        ease = "backOut"
    if move == "track-in" and unit == "char":
        unit = "word"
    a = {"unit": unit, "stagger": round(stagger, 3), "dur": round(dur, 3), "ease": ease, "from": frm}
    if at and unit == "word":
        a["at"] = [round(max(0.0, t), 3) for t in at]
    return a


def entrance_span(a: dict, n_units: int) -> float:
    """Seconds until the last unit of an animator has landed."""
    if a.get("at"):
        return max(a["at"]) + a["dur"]
    return a["stagger"] * max(0, n_units - 1) + a["dur"]


# ------------------------------------------------------------------ compile
def _palette(ctx: dict, role: str) -> str:
    if ctx.get("kit") and role not in ("alert", "white", "red"):
        from . import brandkits
        return brandkits.get(ctx["kit"])["colors"]["primary"]
    if role == "accent" and re.match(r"^#[0-9a-fA-F]{6}$", str(ctx.get("accent") or "")):
        return ctx["accent"]
    return COLORS.get(role) or COLORS.get(ctx.get("accentRole") or "gold") or COLORS["gold"]


def _camera(kind: str, dur: float, point: Optional[Tuple[float, float]], push: float = 1.14) -> Optional[dict]:
    if kind == "push-in":
        return {"scale": [[0, 1.0], [dur, 1.08, "inOut"]]}
    if kind == "pull-out":
        return {"scale": [[0, 1.12], [dur, 1.02, "out"]]}
    if kind == "push-to-point" and point:
        dx, dy = point[0] - 0.5, point[1] - 0.5
        # The marked point stays where it is on screen while the frame closes in round it (x = (s - 1) * d).
        s = push
        return {"scale": [[0, 1.0], [0.75, s, "expoOut"], [dur, s + 0.02, "linear"]],
                "x": [[0, 0.0], [0.75, round((s - 1) * dx, 4), "expoOut"], [dur, round((s + 0.02 - 1) * dx, 4), "linear"]],
                "y": [[0, 0.0], [0.75, round((s - 1) * dy, 4), "expoOut"], [dur, round((s + 0.02 - 1) * dy, 4), "linear"]]}
    if kind in ("whip-left", "whip-right"):
        sgn = -1 if kind == "whip-left" else 1
        return {"scale": [[0, 1.1], [dur, 1.1]], "x": [[0, 0.045 * sgn], [0.3, 0.0, "expoOut"]],
                "blur": [[0, 18], [0.3, 0, "expoOut"]]}
    if kind == "shake":
        return {"scale": [[0, 1.05], [dur, 1.06]], "shake": [[0, 0.011], [0.5, 0.0, "out"]]}
    if kind == "drift":
        return {"scale": [[0, 1.04], [dur, 1.09, "inOut"]], "x": [[0, 0.0], [dur, 0.015, "inOut"]]}
    if kind == "dim":
        return {"dim": [[0, 0.0], [0.4, 0.38, "out"], [max(0.5, dur - 0.4), 0.38], [dur, 0.0, "in"]],
                "scale": [[0, 1.0], [dur, 1.05, "inOut"]]}
    return None


def compile_design(d: dict, timing: dict, ctx: dict) -> Optional[dict]:
    """
    One design -> a motion spec, or None when there is nothing to draw.

    timing: {"dur": the graphic's seconds, "at": [seconds each main word is spoken, from the graphic's start]
    (word sync; may be shorter than the words), "point": (x, y, r, w, h) the vision anchor of the marked thing
    in frame shares, or None}. ctx: {"accent", "accentRole", "aspect", "captionsBottom"}.
    """
    if d.get("kind") in KIT_KINDS:
        return compile_kit_design(d, timing, ctx)
    spec = _compile_design(d, timing, ctx)
    if spec and ctx.get("kit"):
        ctx = dict(ctx, _accentHex=_palette(ctx, str(d.get("color") or "primary")), _kind=d.get("kind"))
        spec = apply_kit(spec, ctx)
    return spec


def _compile_design(d: dict, timing: dict, ctx: dict) -> Optional[dict]:
    dur = _f(timing.get("dur"), 0.5, 12, 3.0)
    kind = _pick(d.get("kind"), KINDS, "statement")
    text = re.sub(r"\s+", " ", str(d.get("text") or "")).strip()[:90]
    sub = re.sub(r"\s+", " ", str(d.get("sub") or "")).strip()[:90]
    layout = _pick(d.get("layout"), _LAYOUT, "left-third")
    typ = d.get("type") if isinstance(d.get("type"), dict) else {}
    font = _pick(typ.get("font"), FONTS, "grotesk")
    if ctx.get("kit"):
        # Laid out in the face it will be drawn in: the kit's title face (apply_kit keeps two fonts a video).
        from . import brandkits
        kf = (brandkits.get(ctx["kit"]).get("fonts") or {}).get("title")
        font = kf if kf in FONTS else font
    weight = int(_f(typ.get("weight"), 400, 900, 800) // 100 * 100)
    case = _pick(typ.get("case"), ("upper", "title", "lower", "as-is"), "as-is")
    tracking = {"tight": -0.02, "normal": 0.0, "wide": 0.08}.get(str(typ.get("tracking") or ""), 0.0)
    an = d.get("anim") if isinstance(d.get("anim"), dict) else {}
    move = _pick(an.get("move"), MOVES, "rise")
    unit = _pick(an.get("unit"), UNITS, "word")
    speed = _pick(an.get("speed"), SPEEDS, "smooth")
    ease = _pick(an.get("ease"), EASES, "expoOut")
    sync = an.get("sync") == "spoken"
    accents = [a for a in (d.get("accent") or []) if a in ACCENTS][:3] if isinstance(d.get("accent"), list) else []
    depth = d.get("depth") if isinstance(d.get("depth"), dict) else {}
    tilt = _f(depth.get("tilt"), -18, 18, 0.0)
    pitch = _f(depth.get("pitch"), -18, 18, 0.0)
    parallax = _f(depth.get("parallax"), 0, 1, 0.0)
    cam = _pick(d.get("camera"), CAMERAS, "none")
    exit_kind = _pick(d.get("exit"), EXITS, "fade")
    color = _palette(ctx, str(d.get("color") or ctx.get("accentRole") or "gold"))
    hl = d.get("highlight") if isinstance(d.get("highlight"), dict) else None
    point = timing.get("point")
    aspect = float(ctx.get("aspect") or 16 / 9)

    if case == "upper":
        text, sub_c = text.upper(), sub
    elif case == "title":
        text, sub_c = text.title(), sub
    else:
        sub_c = sub
    sub = sub_c

    # A mark on a point: the words sit on the side away from it.
    if point and layout in ("center", "left-third", "right-third"):
        layout = "left-third" if point[0] > 0.5 else "right-third"
    if ctx.get("captionsBottom") and layout in ("lower", "lower-center"):
        layout = "left-third"
    anchor, x, y, align, scrim, max_w = _LAYOUT[layout]
    small = layout == "corner"

    size = _SIZES.get(str(typ.get("size") or ""), 0.055)
    n_chars = len(text)
    if kind in ("label", "spot", "place") or small:
        size = min(size, LABEL_SIZE)
    if kind in ("label", "place"):
        # A clean lower third: white type on a soft shade with a thin accent bar, never a dark glass panel.
        accents = [a for a in accents if a != "panel-glass"]
        if "bar-left" not in accents and anchor != "c":
            accents = (accents + ["bar-left"])[-3:]
    # Long words are set smaller so the block stays in its column (a phone still reads them).
    while size > MIN_TEXT and text_width(max(text.split(" "), key=len, default=""), size, font, aspect, tracking) > max_w:
        size -= 0.004
    lines_est = max(1, math.ceil(text_width(text, size, font, aspect, tracking) / max_w))
    if lines_est > 3:
        size = max(MIN_TEXT, size * 0.8)
        lines_est = max(1, math.ceil(text_width(text, size, font, aspect, tracking) / max_w))
    size = round(max(MIN_TEXT, size), 4)
    block_h = lines_est * size * 1.08

    layers: List[dict] = []
    words = _words(text)
    at = timing.get("at") if sync and unit == "word" else None
    if at:
        at = list(at)[:len(words)]
        if len(at) < len(words):
            last = at[-1] if at else 0.0
            at += [last + 0.12 * (i + 1) for i in range(len(words) - len(at))]
    anim = animator(move, unit, speed, ease, at)
    t_in = 0.0
    land = entrance_span(anim, len(text) if anim["unit"] == "char" else len(words) if anim["unit"] == "word"
                         else lines_est)
    land = min(land, max(0.4, dur * 0.6))
    z_text = round(0.5 * parallax, 3)

    emph_style = "box" if "box-sweep" in accents else "glow" if "glow" in accents else "color"

    def text_layer(txt, yy, sz, wt, fnt, anim_, frm=0.0, col="#ffffff", emph_=None, extra=None):
        L = {"kind": "text", "text": txt, "x": x, "y": round(yy, 4), "anchor": anchor, "align": align, "font": fnt,
             "size": round(sz, 4), "weight": wt, "tracking": tracking, "color": col, "maxW": max_w, "from": round(frm, 3),
             "animator": anim_, "z": z_text, "shadow": "soft"}
        if emph_:
            L.update(emph=emph_, emphColor=color, emphStyle=emph_style)
        if tilt or pitch:
            L["keys"] = {"rotY": [[0, round(tilt * 2.2, 2)], [land + 0.3, round(tilt, 2), "expoOut"]],
                         "rotX": [[0, round(pitch * 2.2, 2)], [land + 0.3, round(pitch, 2), "expoOut"]]}
        if move == "wipe":
            L.setdefault("keys", {})["wipe"] = [[frm, 0.0], [frm + 0.6, 1.0, "expoInOut"]]
        if extra:
            L.update(extra)
        return L

    # Emphasis words (a list, or the model's string).
    raw_emph = d.get("emph")
    if isinstance(raw_emph, str):
        raw_emph = raw_emph.split()
    emph_words = {_norm(w) for w in (raw_emph or []) if isinstance(w, str)} if isinstance(raw_emph, list) else set()
    emph = [i for i, w in enumerate(words) if _norm(w) in emph_words and _norm(w)][:4]

    # One block: kicker above, the words (or figure), underline, sub line below, bar / brackets round it -
    # laid out by the renderer itself (SmartSpec TextBody), so its parts never overlap whatever the font.
    kicker = ""
    if "kicker-tag" in accents and sub and len(sub) <= 28:
        kicker, sub = sub, ""
    deco = {"at": round(land * 0.55, 3)}
    if "underline-draw" in accents or "divider" in accents:
        deco["underline"] = color
    if "bar-left" in accents and anchor != "c":
        deco["bar"] = color
    if "rule-top" in accents:
        deco["rule"] = color
    if "bracket" in accents:
        deco["bracket"] = color
    block: Dict[str, object] = {}
    if kicker:
        block["kicker"] = {"text": kicker.upper(), "size": 0.025, "color": "#0b0c10", "bg": color, "at": 0.0}
    if len(deco) > 1:
        block["deco"] = deco

    def sub_of(txt, at_s, upper=False, size_=None, font_="inter", weight_=600, tr=0.02):
        return {"text": txt, "size": round(max(MIN_SUB, size_ or min(0.036, max(MIN_SUB, size * 0.45))), 4),
                "font": font_, "weight": weight_, "color": "#e9e9ea", "tracking": tr, "upper": upper,
                "at": round(at_s, 3)}

    if kind in ("number", "date", "compare") and _f(d.get("value"), -1e12, 1e12, None) is not None:
        val = _f(d.get("value"), -1e12, 1e12, 0.0)
        is_year = kind == "date" or (1000 <= abs(val) <= 2100 and float(val).is_integer() and not d.get("suffix"))
        dec = int(_f(d.get("decimals"), 0, 3, 0))
        start_val = (val - min(40, abs(val) * 0.02)) if is_year else (0.0 if abs(val) < 1e9 else val * 0.5)
        num_size = round(COUNTER_SIZE if not small else COUNTER_SIZE_SMALL, 4)
        label_txt = text if text and not re.fullmatch(r"[\d,.\s%$]+", text) else ""
        count_for = min(1.3, max(0.5, dur * 0.4))
        L = {"kind": "counter", "x": x, "y": round(y, 4), "anchor": anchor, "align": align,
             "font": font if font not in ("serif-italic", "narrow") else "grotesk",
             "size": num_size, "weight": max(700, weight), "tracking": -0.02, "color": "#ffffff",
             "valueFrom": round(start_val, 3), "valueTo": val, "decimals": dec,
             "prefix": str(d.get("prefix") or "")[:6], "suffix": str(d.get("suffix") or "")[:16],
             "group": not is_year, "z": z_text, "shadow": "soft", "maxW": max_w,
             "keys": {"p": [[0, 0.0], [count_for, 1.0, "expoOut"]], "opacity": [[0, 0.0], [0.18, 1.0, "out"]],
                      "y": [[0, 0.03], [0.5, 0.0, "expoOut"]]}}
        if tilt or pitch:
            L["keys"]["rotY"] = [[0, round(tilt * 2.2, 2)], [0.8, round(tilt, 2), "expoOut"]]
            L["keys"]["rotX"] = [[0, round(pitch * 2.2, 2)], [0.8, round(pitch, 2), "expoOut"]]
        if "extrude" in accents:
            L["extrude"] = 6
        if "glow" in accents:
            L["glow"] = 22
            L["emphColor"] = color
        if "panel-glass" in accents:
            L["panel"] = {"color": "#0c0e12", "opacity": 0.55, "pad": 0.02, "radius": 0.008, "blur": 18}
        line2 = label_txt.upper() if label_txt and case != "lower" else label_txt
        if line2:
            L["sub"] = sub_of(line2 + (f" · {sub}" if sub and len(sub) < 26 else ""), 0.35, True, 0.032, "narrow",
                              700, 0.12)
        elif sub:
            L["sub"] = sub_of(sub, 0.4)
        L.update(block)
        if "deco" in L:
            L["deco"]["at"] = 0.25
        layers.append(L)
    elif kind == "list" or text:
        fnt = font
        txt = text
        anim_ = anim
        if kind == "list":
            raw_items = d.get("items") if isinstance(d.get("items"), list) else []
            items = [str(i).strip()[:40] for i in raw_items if str(i).strip()][:4]
            if items:
                txt = chr(10).join(items)
                anim_ = animator(move if move != "typewriter" else "rise", "line", speed, ease)
                size = round(max(MIN_TEXT, min(size, 0.052)), 4)
                if anchor != "c":
                    block.setdefault("deco", {"at": 0.0})["bar"] = color
        if not txt:
            return None
        if kind == "quote":
            if not ctx.get("kit"):
                fnt = "serif-italic" if font not in ("serif", "serif-italic") else font
            if not txt.startswith("“"):
                txt = f"“{txt}”"
        L = text_layer(txt, y, size, weight, fnt, anim_, 0.0, emph_=emph)
        if "extrude" in accents and size >= 0.07 and weight >= 800:
            L["extrude"] = 6
        if "panel-glass" in accents:
            L["panel"] = {"color": "#0c0e12", "opacity": 0.55, "pad": 0.02, "radius": 0.008, "blur": 18}
        if sub:
            L["sub"] = sub_of(sub, min(land, 0.9))
        L.update(block)
        layers.append(L)
    elif not hl:
        return None

    # Rough block extent (only to aim an arrow from the words to a marked thing).
    w_est = min(max_w, max(text_width(text, size, font, aspect, tracking) / max(1, lines_est), 0.12))
    left = x if anchor == "l" else x - w_est if anchor == "r" else x - w_est / 2
    cx = left + w_est / 2
    main_y = y
    if "particles" in accents:
        layers.insert(0, {"kind": "particles", "count": 36, "color": "#ffe2b0", "size": 0.0032, "opacity": 0.55,
                          "speed": 0.2, "seed": int(abs(hash_text(text)) % 100000)})

    # The mark on the thing the narration names (a vision anchor; none = no mark, never a guess).
    if hl and point:
        px, py, pr, pw, ph = point
        mark = _pick(hl.get("mark"), MARKS, "circle")
        push = 1.12 if cam == "push-to-point" else 1.0
        t_mark = 0.55 if cam == "push-to-point" else 0.15
        k = min(1.0, 16 / 9 / aspect)
        rw = max(0.06, min(0.6, pw * push * 1.35)) if pw else max(0.06, min(0.5, pr * 2 * push / aspect * 1.3))
        rh = max(0.08, min(0.75, ph * push * 1.35)) if ph else max(0.08, min(0.7, pr * 2 * push * 1.3))
        if mark == "circle":
            layers.append({"kind": "ellipse", "x": px, "y": py, "w": round(rw, 4), "h": round(rh, 4), "color": color,
                           "stroke": 0.0055, "keys": {"draw": [[t_mark, 0.0], [t_mark + 0.7, 1.0, "inOut"]]}})
        elif mark == "box":
            layers.append({"kind": "bracket", "x": px, "y": py, "w": round(rw, 4), "h": round(rh, 4), "color": color,
                           "stroke": 0.004, "keys": {"draw": [[t_mark, 0.0], [t_mark + 0.5, 1.0, "expoOut"]],
                                                     "scale": [[t_mark, 1.25], [t_mark + 0.5, 1.0, "expoOut"]]}})
        elif mark == "spotlight":
            layers.insert(0, {"kind": "spot", "x": px, "y": py, "w": round(rw * 1.6, 4), "h": round(rh * 1.6, 4),
                              "fill": "#000000", "keys": {"opacity": [[t_mark, 0.0], [t_mark + 0.6, 1.0, "out"]]}})
            layers.append({"kind": "ellipse", "x": px, "y": py, "w": round(rw, 4), "h": round(rh, 4), "color": "#ffffff",
                           "stroke": 0.0025, "keys": {"draw": [[t_mark + 0.2, 0.0], [t_mark + 0.9, 1.0, "inOut"]]}})
        elif mark == "pin":
            label = str(hl.get("label") or "")[:28]
            layers.append({"kind": "pin", "x": px, "y": py, "color": color, "text": label.upper(), "size": 0.03,
                           "font": "narrow", "keys": {"scale": [[t_mark, 0.0], [t_mark + 0.45, 1.0, "backOut"]]}})
        elif mark == "loupe" and timing.get("src"):
            layers.extend(loupe_layers(timing["src"], point))
        elif mark == "underline":
            layers.append({"kind": "line", "points": [[px - rw / 2, py + rh / 2], [px + rw / 2, py + rh / 2]], "curve": 0.04,
                           "color": color, "stroke": 0.006, "keys": {"draw": [[t_mark, 0.0], [t_mark + 0.5, 1.0, "out"]]}})
        if mark in ("arrow", "circle", "box") and layers and any(L["kind"] in ("text", "counter") for L in layers):
            # An arrow from the words to the edge of the thing.
            tx = (left + w_est + 0.02) if px > cx else (left - 0.02)
            ty = main_y
            ang = math.atan2(py - ty, px - tx)
            ex = px - math.cos(ang) * (rw / 2 + 0.01) if mark != "arrow" else px - math.cos(ang) * rw * 0.25
            ey = py - math.sin(ang) * (rh / 2 + 0.01) if mark != "arrow" else py - math.sin(ang) * rh * 0.25
            if math.hypot(ex - tx, ey - ty) > 0.08:
                layers.append({"kind": "arrow", "points": [[round(tx, 4), round(ty, 4)], [round(ex, 4), round(ey, 4)]],
                               "curve": 0.18 if px > cx else -0.18, "color": "#ffffff", "stroke": 0.0035, "head": 0.022,
                               "keys": {"draw": [[t_mark + 0.35, 0.0], [t_mark + 0.95, 1.0, "out"]]}})
        elif mark == "arrow":
            layers.append({"kind": "arrow", "points": [[px - 0.12, py - 0.16], [px - 0.02, py - 0.03]], "curve": 0.2,
                           "color": color, "stroke": 0.005, "head": 0.025,
                           "keys": {"draw": [[t_mark, 0.0], [t_mark + 0.5, 1.0, "out"]]}})
        _ = k
    elif hl and not point and not text:
        return None

    if not layers:
        return None
    for L in layers:
        _safe(L)
    spec = {"v": 1, "persp": 1100 if (tilt or pitch or move in ("flip-x", "flip-y")) else 1600, "layers": layers,
            "exit": {"kind": exit_kind, "dur": 0.4 if dur > 1.5 else 0.25},
            "drift": {"x": round(0.012 * parallax * (1 if anchor != "r" else -1), 4), "y": 0.0,
                      "rotY": round(4 * parallax * (1 if anchor != "r" else -1), 2)}}
    if scrim and any(L["kind"] in ("text", "counter") for L in layers):
        spec["shade"] = {"kind": scrim, "amount": 0.5 if scrim != "vignette" else 0.42}
    elif hl and point and _pick(hl.get("mark"), MARKS, "circle") != "spotlight":
        spec["shade"] = {"kind": "vignette", "amount": 0.3}
    cam_keys = _camera(cam, dur, (point[0], point[1]) if point else None)
    if cam_keys:
        spec["camera"] = {"keys": cam_keys}
    return spec


def hash_text(s: str) -> int:
    h = 2166136261
    for ch in str(s):
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h


def _safe(L: dict) -> None:
    """Keep a layer's anchor point inside the title-safe area (marks may sit anywhere on the thing they mark)."""
    if L["kind"] in ("text", "counter"):
        L["x"] = round(min(SAFE_X[1], max(SAFE_X[0], L["x"])), 4)
        L["y"] = round(min(SAFE_Y[1], max(SAFE_Y[0], L["y"])), 4)


# ------------------------------------------------------------------ checks (the renderer's clean-up, in Python)
_LAYER_KINDS = {"text", "counter", "rect", "ellipse", "line", "arrow", "bracket", "pin", "spot", "image", "particles",
                "backdrop", "shape", "waffle", "measure", "loupe", "tiles", "pill"}


def clean_spec(spec, dur: float) -> Optional[dict]:
    """The spec as the renderer will draw it (unknown kinds out, numbers in range), or None if nothing is left."""
    if not isinstance(spec, dict) or not dur or dur <= 0:
        return None
    out = []
    for L in (spec.get("layers") or [])[:24]:
        if not isinstance(L, dict) or L.get("kind") not in _LAYER_KINDS:
            continue
        if L["kind"] == "text" and not str(L.get("text") or "").strip():
            continue
        if L["kind"] in ("line", "arrow") and len([p for p in (L.get("points") or []) if isinstance(p, (list, tuple))
                                                    and len(p) >= 2]) < 2:
            continue
        if L["kind"] == "image" and not re.match(r"^(https?://|data:image/)", str(L.get("src") or "")):
            continue
        out.append(L)
    if not out:
        return None
    return dict(spec, layers=out)


def signature(d: dict) -> dict:
    """The parts of a design that make two graphics look 'the same' (the freshness rule)."""
    an = d.get("anim") if isinstance(d.get("anim"), dict) else {}
    typ = d.get("type") if isinstance(d.get("type"), dict) else {}
    hl = d.get("highlight") if isinstance(d.get("highlight"), dict) else {}
    return {
        "anim": f"{an.get('move', 'rise')}/{an.get('unit', 'word')}",
        "layout": str(d.get("layout") or "left-third"),
        "accents": "+".join(sorted(a for a in (d.get("accent") or []) if isinstance(a, str))),
        "font": str(typ.get("font") or "grotesk"),
        "camera": str(d.get("camera") or "none"),
        "mark": str(hl.get("mark") or ""),
        "kind": str(d.get("kind") or "statement"),
    }


# ------------------------------------------------------------------ brand kits
KIT_KINDS = ("card", "waffle", "measure", "tiles")


def _kit_tempo(ctx: dict) -> float:
    from . import brandkits
    return float(brandkits.get(ctx.get("kit") or "").get("tempo", 1.0)) if ctx.get("kit") else 1.0


def apply_kit(spec: Optional[dict], ctx: dict) -> Optional[dict]:
    """Put a compiled spec on the video's brand kit: its tokens for colour, type, easing and tempo."""
    if not spec or not ctx.get("kit"):
        return spec
    from . import brandkits
    kit = brandkits.get(ctx["kit"])
    tempo = float(kit.get("tempo", 1.0))
    spec["kit"] = ctx["kit"]
    accent = ctx.get("_accentHex")
    first_main = True
    # TWO fonts a video (2026-10-18 proof: six families in 100 s read as random, not branded): the kit's title
    # face for the headline (and figures, when the kit's number face is one of the two), its label face for
    # everything else - subs, kickers, pins, second lines. A design's own font choice never adds a third.
    fonts = kit.get("fonts") or {}
    number_font = "$number" if fonts.get("number") in (fonts.get("title"), fonts.get("label")) else "$title"
    for L in spec.get("layers") or []:
        for key in ("color", "fill", "emphColor"):
            v = L.get(key)
            if v == "#ffffff":
                L[key] = "$text"
            elif v == "#e9e9ea":
                L[key] = "$muted"
            elif accent and v == accent:
                L[key] = "$primary"
        if L["kind"] in ("text", "counter"):
            if L["kind"] == "counter":
                L["font"] = number_font
            elif first_main:
                L["font"] = "$title"
                L["weight"] = kit.get("titleWeight", 800)
                L.pop("italic", None)
            else:
                L["font"] = "$label"
            first_main = False
            sub = L.get("sub")
            if isinstance(sub, dict):
                sub["color"] = "$muted" if not sub.get("upper") else "$text"
                sub["font"] = "$label"
        elif "font" in L:
            L["font"] = "$label"            # pins, tags, list rows ...
        for key in ("kicker", "label"):
            if isinstance(L.get(key), dict) and "font" in L[key]:
                L[key]["font"] = "$label"
        if L["kind"] in ("text", "counter"):
            k = L.get("kicker")
            if isinstance(k, dict):
                k.update(color="$pillText", bg="$pillBg")
            deco = L.get("deco")
            if isinstance(deco, dict):
                for dk in ("bar", "underline", "rule", "bracket"):
                    if dk in deco:
                        deco[dk] = "$primary"
            a = L.get("animator")
            if isinstance(a, dict) and a.get("ease") != "hold":
                a["ease"] = "$ease"
                a["dur"] = round(a["dur"] * tempo, 3)
                a["stagger"] = round(a["stagger"] * tempo, 3)
    return spec


def _card_ground(enter: str) -> dict:
    keys = {"opacity": [[0, 0.0], [0.3, 1.0, "$easeSoft"]]} if enter != "wipe" else \
        {"wipe": [[0, 0.0], [0.5, 1.0, "$ease"]]}
    return {"kind": "backdrop", "color": "$bg", "color2": "$bg2", "grid": False, "keys": keys}


def compile_kit_design(d: dict, timing: dict, ctx: dict) -> Optional[dict]:
    """The brand-kit compositions: a full-screen kit card (title, figure, a flat illustration that builds up,
    a measurement beside it), a waffle chart, a measurement on the shot, a row of tiles."""
    dur = _f(timing.get("dur"), 0.5, 12, 3.0)
    kind = d.get("kind")
    text = re.sub(r"\s+", " ", str(d.get("text") or "")).strip()[:60]
    sub = re.sub(r"\s+", " ", str(d.get("sub") or "")).strip()[:60]
    tempo = _kit_tempo(ctx)
    val = _f(d.get("value"), -1e12, 1e12, None)
    suffix = str(d.get("suffix") or "")[:16]
    prefix = str(d.get("prefix") or "")[:6]
    unit = str(d.get("unit") or "").strip()[:20] or suffix.strip()
    layers: List[dict] = []
    point = timing.get("point")
    on_card = kind == "card" or d.get("ground") == "card" or (kind in ("waffle", "tiles") and d.get("ground") != "footage")
    if on_card:
        layers.append(_card_ground("wipe" if hash_text(text) % 2 else "fade"))

    def title(y, size=0.12, col="$primary"):
        return {"kind": "text", "text": text.upper(), "x": 0.5, "y": y, "anchor": "c", "align": "center", "font": "$title",
                "size": size, "weight": 800, "tracking": 0.0, "color": col, "maxW": 0.84, "lineH": 0.95,
                "animator": {"unit": "char", "stagger": round(0.035 * tempo, 3), "dur": round(0.55 * tempo, 3),
                             "ease": "$ease", "from": {"opacity": 0, "y": 0.55}}, "shadow": "soft"}

    def figure(x, y, anchor="c", align="center", size=0.11):
        L = {"kind": "counter", "x": x, "y": y, "anchor": anchor, "align": align, "font": "$number", "size": size,
             "weight": 800, "tracking": -0.02, "color": "$number", "valueFrom": 0 if abs(val) < 1e9 else val * 0.5,
             "valueTo": val, "decimals": int(_f(d.get("decimals"), 0, 3, 0)), "prefix": prefix,
             "suffix": "" if unit and unit == suffix.strip() else suffix, "group": not (1000 <= abs(val) <= 2100),
             "keys": {"p": [[0.2, 0.0], [0.2 + min(1.3, dur * 0.4), 1.0, "$ease"]],
                      "opacity": [[0, 0.0], [0.25, 1.0, "out"]], "y": [[0, 0.025], [0.5, 0.0, "$ease"]]},
             "shadow": "soft", "maxW": 0.5}
        if unit:
            L["sub"] = {"text": unit.upper(), "size": 0.03, "font": "$label", "weight": 800, "color": "$text",
                        "tracking": 0.14, "upper": True, "at": 0.45}
        return L

    if kind == "card":
        ill = d.get("illustration") if isinstance(d.get("illustration"), dict) else {}
        shapes = [s for s in (ill.get("shapes") or []) if isinstance(s, dict)][:30]
        if len(shapes) >= 2:
            # The illustration in the middle, built from the ground up; the title above, the figure beside it.
            # Fit the drawing to its box: the model draws in a square; its own extent fills a 62%-tall box.
            shapes, a = fit_shapes(shapes)
            bh, by = 0.62, 0.6
            bw = min(0.5, max(0.12, bh * a * (1 / float(ctx.get("aspect") or 16 / 9))))
            bx = 0.5 if val is None else 0.5 - bw / 2 - 0.02
            layers.append({"kind": "shape", "x": bx, "y": by, "w": bw, "h": bh, "shapes": shapes,
                           "build": ill.get("build") if ill.get("build") in ("up", "pop", "draw", "left", "fade") else "up",
                           "stagger": round(min(0.12, 1.4 / max(4, len(shapes))) * tempo, 3),
                           "bdur": round(0.45 * tempo, 3), "ease": "$ease", "from": 0.15})
            if text:
                layers.append(title(0.15, 0.115))
            if val is not None:
                layers.append(figure(bx + bw / 2 + 0.09, by, "l", "left"))
                if d.get("measure"):
                    layers.append({"kind": "measure", "points": [[bx + bw / 2 + 0.05, by - bh / 2 + 0.02],
                                                                 [bx + bw / 2 + 0.05, by + bh / 2 - 0.01]],
                                   "color": "$text", "stroke": 0.0028,
                                   "keys": {"draw": [[1.0, 0.0], [1.7, 1.0, "$ease"]]}})
        else:
            if text:
                layers.append(title(0.42 if val is None else 0.3, 0.15 if len(text) < 14 else 0.11))
            if val is not None:
                layers.append(figure(0.5, 0.6 if text else 0.48))
            elif sub and layers and layers[-1]["kind"] == "text":
                layers[-1]["sub"] = {"text": sub, "size": 0.034, "font": "$body", "weight": 600, "color": "$muted",
                                     "tracking": 0.02, "upper": False, "at": 0.6}
        if len(layers) < 2:
            return None
    elif kind == "waffle":
        pct = _f(d.get("value"), 0, 100, None)
        if pct is None:
            return None
        cols, rows = (20, 6) if d.get("shape") == "wide" else (10, 10)
        layers.append({"kind": "waffle", "x": 0.5, "y": 0.6, "w": 0.52 if cols == 20 else 0.34, "h": 0.5,
                       "cols": cols, "rows": rows, "value": int(round(pct / 100 * cols * rows)), "fill": "$primary",
                       "offColor": "rgba(255,255,255,0.16)", "fillFor": min(1.6, dur * 0.45), "from": 0.2})
        top = {"kind": "counter", "x": 0.5, "y": 0.18, "anchor": "c", "align": "center", "font": "$number",
               "size": 0.085, "weight": 800, "color": "$number", "valueFrom": 0, "valueTo": pct, "suffix": "%",
               "decimals": 0 if float(pct).is_integer() else 1,
               "keys": {"p": [[0.4, 0.0], [0.4 + min(1.6, dur * 0.45), 1.0, "$ease"]],
                        "opacity": [[0, 0.0], [0.3, 1.0]]}, "shadow": "soft", "maxW": 0.8}
        if text:
            top["sub"] = {"text": text.upper(), "size": 0.028, "font": "$label", "weight": 800, "color": "$text",
                          "tracking": 0.14, "upper": True, "at": 0.5}
        layers.append(top)
    elif kind == "measure":
        if not point or val is None:
            return None
        px, py, pr, pw, ph = point
        h = ph or pr * 2
        if h < 0.12:
            return None
        mx = min(0.86, px + max(pw, 0.05) / 2 + 0.035)
        layers.append({"kind": "measure", "points": [[mx, max(0.05, py - h / 2)], [mx, min(0.95, py + h / 2)]],
                       "color": "$text", "stroke": 0.003, "keys": {"draw": [[0.1, 0.0], [0.9, 1.0, "$ease"]]}})
        layers.append(figure(min(0.9, mx + 0.03), py, "l", "left", 0.075))
    elif kind == "tiles":
        raw = d.get("items") if isinstance(d.get("items"), list) else []
        items = [str(i).strip()[:22] for i in raw if str(i).strip()][:5]
        if len(items) < 2:
            return None
        layers.append({"kind": "tiles", "x": 0.5, "y": 0.56, "items": items, "size": 0.13, "fill": "$text",
                       "color": "$bg2", "stagger": round(0.2 * tempo, 3), "from": 0.3})
        if text:
            layers.append(title(0.3, 0.075, col="$text"))
    else:
        return None
    spec = {"v": 1, "kit": ctx.get("kit") or "noir", "persp": 1600, "layers": layers,
            "exit": {"kind": "wipe" if on_card else "fade", "dur": 0.35 if dur > 1.5 else 0.2},
            "drift": {"x": 0.0, "y": 0.0, "rotY": 0.0}}
    if not on_card:
        spec["shade"] = {"kind": "vignette", "amount": 0.45}
        cam = d.get("camera")
        if cam in ("push-in", "drift", "push-to-point"):
            ck = _camera(cam, dur, (point[0], point[1]) if point else None)
            if ck:
                spec["camera"] = {"keys": ck}
    return spec


def loupe_layers(src: str, point: tuple) -> List[dict]:
    """A circular loupe magnifying the marked point of a still, linked to it by a fine line."""
    px, py = point[0], point[1]
    lx = 0.76 if px < 0.5 else 0.24
    ly = 0.66 if py < 0.5 else 0.34
    return [
        {"kind": "ellipse", "x": px, "y": py, "w": 0.05, "h": 0.089, "color": "$primary", "stroke": 0.004,
         "keys": {"draw": [[0.1, 0.0], [0.6, 1.0, "$ease"]]}},
        {"kind": "line", "points": [[px, py], [lx, ly]], "color": "$text", "stroke": 0.002,
         "keys": {"draw": [[0.4, 0.0], [0.8, 1.0, "$ease"]]}},
        {"kind": "loupe", "src": src, "x": lx, "y": ly, "w": 0.2, "fx": px, "fy": py, "zoom": 3.0, "color": "$primary",
         "keys": {"scale": [[0.6, 0.0], [1.1, 1.0, "backOut"]]}},
    ]


def fit_shapes(shapes: List[dict]) -> Tuple[List[dict], float]:
    """Shapes re-scaled so their own extent fills 0..1 both ways; returns them and their width / height."""
    xs, ys = [], []
    for q in shapes:
        if q.get("t") in ("poly", "line"):
            for p in q.get("p") or []:
                if isinstance(p, (list, tuple)) and len(p) >= 2:
                    xs.append(_f(p[0], -1, 2, 0)); ys.append(_f(p[1], -1, 2, 0))
        else:
            x, y = _f(q.get("x"), -1, 2, 0), _f(q.get("y"), -1, 2, 0)
            xs += [x, x + _f(q.get("w"), 0, 2, 0)]; ys += [y, y + _f(q.get("h"), 0, 2, 0)]
    if not xs:
        return shapes, 1.0
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    sx, sy = max(1e-3, x1 - x0), max(1e-3, y1 - y0)
    out = []
    for q in shapes:
        q = dict(q)
        if q.get("t") in ("poly", "line"):
            q["p"] = [[round((_f(p[0], -1, 2, 0) - x0) / sx, 4), round((_f(p[1], -1, 2, 0) - y0) / sy, 4)]
                      for p in q.get("p") or [] if isinstance(p, (list, tuple)) and len(p) >= 2]
            if q.get("sw") is not None:
                q["sw"] = _f(q["sw"], 0, 1, 0.01) if _f(q["sw"], 0, 100, 0.01) <= 0.05 else 0.012
        else:
            q["x"] = round((_f(q.get("x"), -1, 2, 0) - x0) / sx, 4)
            q["y"] = round((_f(q.get("y"), -1, 2, 0) - y0) / sy, 4)
            q["w"] = round(_f(q.get("w"), 0, 2, 0) / sx, 4)
            q["h"] = round(_f(q.get("h"), 0, 2, 0) / sy, 4)
        out.append(q)
    return out, sx / sy
