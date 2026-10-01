"""
The brand kit: what a customer sets once and every video uses.

A kit arrives as the job's `brand_kit` (the app's video-v2 sends it with
plan, build and render). It has two halves:

  identity - one or two accent colours, a font the renderer ships, the
             caption style, the logo as a corner watermark, an intro sting
             and an outro (an end card, or the customer's own outro video);
  picks    - the animation looks, transitions and music the customer allows,
             sound effects on or off, and how busy the graphics are.

Generation uses only the picks, and an empty or odd pick list never breaks a
video. A cue whose looks are all switched off gets the closest allowed look
or no graphic at all; a beat that wanted a full-screen graphic keeps its
footage, or the neighbouring shot is held over it (gapfill's last resort) -
never an empty scene. With no kit the worker behaves exactly as before.

    parse()          whatever arrived -> a clean kit (unknown values dropped,
                     numbers clamped, links checked) or None
    prepare_input()  the kit's defaults folded into the job input before the
                     video style is applied (density, sound, captions, colours)
    scope()          the picks switched on for the planner: templates.banned()
                     answers True for a look the kit leaves out
    doc_brand()      the renderer's `brand` block (Main.tsx draws it)
    enforce()        after planning: any look outside the picks that a side
                     path placed is swapped for the closest allowed one or
                     left out
    prepare_render() before a render: the intro and outro measured, every brand
                     file checked, their frames written for the renderer
    layout()         (intro, body, outro, total) frames - the arithmetic the
                     renderer (brand/brandLayout.ts) and the split render share
"""
import contextlib
import ipaddress
import math
import os
import re
import subprocess
import urllib.parse
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import config, templates

# --------------------------------------------------------------------------- #
# The identity's limits. A contract with remotion/src/components/brand/
# brandLayout.ts (BRAND_LIMITS) and brandFonts.ts; a test keeps them equal.
# --------------------------------------------------------------------------- #
POSITIONS = ("top-left", "top-right", "bottom-left", "bottom-right")
# Top right by default: the planner's compact figures ride in the bottom
# corners and the captions along the bottom (treatments.apply_layout).
DEFAULT_POSITION = "top-right"
LOGO_SIZE_MIN, LOGO_SIZE_MAX, LOGO_SIZE_DEFAULT = 0.04, 0.3, 0.1       # share of the frame's width
LOGO_OPACITY_MIN, LOGO_OPACITY_MAX, LOGO_OPACITY_DEFAULT = 0.1, 1.0, 0.85
INTRO_MAX_SECONDS = 15.0
OUTRO_MAX_SECONDS = 20.0
CARD_MIN_SECONDS, CARD_MAX_SECONDS, CARD_DEFAULT_SECONDS = 3.0, 20.0, 6.0
# The typefaces the renderer loads (remotion/src/components/fonts.ts); the
# brand font is one of them, named as @remotion/google-fonts registers it.
FONTS = ("Inter", "Inter Tight", "Oswald", "Anton", "Bebas Neue", "Barlow Condensed", "Playfair Display",
         "Cinzel", "Courier Prime", "JetBrains Mono", "Caveat", "Permanent Marker")
DEFAULT_FONT = "Inter"
DENSITIES = ("auto", "minimal", "normal", "rich")
TEXT_LIMITS = {"title": 60, "text": 40, "subtext": 80}
OUTRO_KINDS = ("card", "video")
# Brand files are small: a logo, a few seconds of sting. Anything bigger is refused.
LOGO_MAX_BYTES = 15 * 1024 * 1024
CLIP_MAX_BYTES = 300 * 1024 * 1024
# A look family whose graphics take the second colour: the figures and charts.
SECOND_COLOUR_CATEGORIES = frozenset({"NUMBERS", "CHARTS", "COMPARISONS", "TIMELINES"})
# The colour theme an overlay names to draw in the second brand colour
# (remotion/src/overlays.tsx accentFor).
SECOND_THEME = "accent2"
ALL = "all"
NONE = "none"

_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


# --------------------------------------------------------------------------- #
# Parsing: a kit from whatever arrived
# --------------------------------------------------------------------------- #

def _text(value: Any, limit: int) -> str:
    return " ".join(str(value).split())[:limit] if isinstance(value, (str, int, float)) and not isinstance(
        value, bool) else ""


def _colour(value: Any) -> Optional[str]:
    """"#RRGGBB" for a hex colour (3 or 6 digits, with or without #), else None."""
    m = _HEX.match(str(value or "").strip()) if isinstance(value, str) else None
    if not m:
        return None
    h = m.group(1)
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return "#" + h.upper()


def _number(value: Any, lo: float, hi: float, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if isinstance(value, bool) or not math.isfinite(v):
        return default
    return max(lo, min(hi, v))


def _flag(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    if isinstance(value, str) and value.strip():
        return value.strip().lower() in ("1", "true", "yes", "on")
    return default


def font(value: Any) -> Optional[str]:
    """The renderer's own spelling of a font the kit names, or None (case and spacing ignored)."""
    key = re.sub(r"[\s_-]+", "", str(value or "")).lower()
    return next((f for f in FONTS if f.replace(" ", "").lower() == key), None) if key else None


def safe_url(value: Any) -> str:
    """
    An http(s) link the worker may fetch, or "". Never a local path, a file://
    link or a private, loopback or link-local address (a kit is customer data:
    its links must not reach this machine's own network).
    """
    url = str(value or "").strip() if isinstance(value, str) else ""
    if not url or len(url) > 2000:
        return ""
    try:
        p = urllib.parse.urlparse(url)
    except ValueError:
        return ""
    if p.scheme not in ("http", "https") or not p.hostname:
        return ""
    host = p.hostname.lower()
    if host in ("localhost",) or host.endswith((".localhost", ".local", ".internal")):
        return ""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return url
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast \
            or ip.is_unspecified:
        return ""
    return url


def _watermark(raw: Any) -> Optional[dict]:
    if not isinstance(raw, dict) or raw.get("enabled") is False:
        return None
    url = safe_url(raw.get("url"))
    if not url:
        return None
    pos = str(raw.get("position") or "").strip().lower()
    return {"url": url, "position": pos if pos in POSITIONS else DEFAULT_POSITION,
            "size": round(_number(raw.get("size"), LOGO_SIZE_MIN, LOGO_SIZE_MAX, LOGO_SIZE_DEFAULT), 3),
            "opacity": round(_number(raw.get("opacity"), LOGO_OPACITY_MIN, LOGO_OPACITY_MAX,
                                     LOGO_OPACITY_DEFAULT), 3)}


def _clip(raw: Any, most: float) -> Optional[dict]:
    """An intro or outro video: its link and the length the app measured (the render measures it again)."""
    if not isinstance(raw, dict) or raw.get("enabled") is False:
        return None
    url = safe_url(raw.get("url"))
    if not url:
        return None
    out = {"url": url}
    seconds = _number(raw.get("seconds"), 0.0, most, 0.0)
    if seconds > 0:
        out["seconds"] = round(seconds, 3)
    return out


def _outro(raw: Any) -> Optional[dict]:
    if not isinstance(raw, dict) or raw.get("enabled") is False:
        return None
    kind = str(raw.get("kind") or raw.get("type") or "").strip().lower()
    if kind == "video":
        clip = _clip(raw, OUTRO_MAX_SECONDS)
        return {"kind": "video", **clip} if clip else None
    if kind != "card":
        return None
    card = {"kind": "card",
            "seconds": round(_number(raw.get("seconds"), CARD_MIN_SECONDS, CARD_MAX_SECONDS, CARD_DEFAULT_SECONDS), 3)}
    for key, limit in TEXT_LIMITS.items():
        text = _text(raw.get(key), limit)
        if text:
            card[key] = text
    if not any(card.get(k) for k in TEXT_LIMITS):
        card["text"] = "Subscribe for more"          # a card with nothing on it is never drawn blank
    logo = safe_url(raw.get("logo"))
    if logo:
        card["logo"] = logo
    return card


def _known_looks() -> set:
    return {t["id"] for t in templates.all_templates()}


def _list(value: Any) -> Optional[list]:
    """A list of strings from a list (or one comma-separated string); None when it is neither."""
    if isinstance(value, str) and value.strip().lower() not in (ALL, NONE, ""):
        value = [v for v in value.split(",")]
    if not isinstance(value, (list, tuple)):
        return None
    out = []
    for v in value:
        s = str(v).strip() if isinstance(v, (str, int)) and not isinstance(v, bool) else ""
        if s and s not in out:
            out.append(s)
    return out


def _picked(value: Any, known, what: str, warnings: List[str], lower: bool = False):
    """
    "all" (every one), or the known entries of a list in order. A list that
    named entries of which none is known falls back to "all" (a renamed look
    must not leave a video bare); an empty list keeps its meaning: none.
    """
    if value is None or value is True or (isinstance(value, str) and value.strip().lower() in (ALL, "")):
        return ALL
    if value is False or (isinstance(value, str) and value.strip().lower() == NONE):
        return []
    items = _list(value)
    if items is None:
        warnings.append(f"{what}: unreadable pick list, every {what} allowed")
        return ALL
    if lower:
        items = [s.lower() for s in items]
    good = [s for s in items if known(s)]
    if items and not good:
        warnings.append(f"{what}: none of the {len(items)} picks is known here, every {what} allowed")
        return ALL
    if len(good) < len(items):
        warnings.append(f"{what}: {len(items) - len(good)} unknown pick(s) ignored")
    return good


def _transition_known(value: str) -> bool:
    from . import timeline
    if value == "pack":
        return True
    if value.startswith(timeline.PACK_PREFIX):
        return value[len(timeline.PACK_PREFIX):] in timeline.pack_meta()
    return value in timeline.TRANSITIONS and value != "none"


def _music_known(value: str) -> bool:
    from . import timeline
    names = {name for tracks in timeline.BGM_TRACKS.values() for name, _ in tracks}
    return value in timeline.BGM_GENRES or value in names or timeline._BGM_MOODS.get(value) in timeline.BGM_GENRES


def _picks(raw: Any, warnings: List[str]) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    known = _known_looks()
    looks = _picked(raw.get("looks"), lambda s: s in known, "look", warnings)
    transitions = _picked(raw.get("transitions"), _transition_known, "transition", warnings, lower=True)
    music = raw.get("music")
    music = _picked(music, _music_known, "music", warnings, lower=True)
    if isinstance(music, list):
        from . import timeline
        # A mood word ("tense") stands for the genre that plays it.
        music = list(dict.fromkeys(timeline._BGM_MOODS.get(m, m) for m in music))
    density = str(raw.get("density") or ALL).strip().lower()
    density = {"full": "rich", "less": "minimal", "more": "rich", ALL: "auto"}.get(density, density)
    return {"looks": looks, "transitions": transitions, "music": music if music else NONE,
            "sfx": _flag(raw.get("sfx"), True), "density": density if density in DENSITIES else "auto"}


def parse(raw: Any) -> Optional[dict]:
    """
    A clean kit from the job's `brand_kit`, or None when there is none. Never
    raises: a value that cannot be used is left out (and said in "warnings"),
    so an odd kit renders like a smaller one, never a failed job.
    """
    if not isinstance(raw, dict) or not raw:
        return None
    warnings: List[str] = []
    accent = _colour(raw.get("accent"))
    accent2 = _colour(raw.get("accent2"))
    if accent2 and accent2 == accent:
        accent2 = None
    named_font = font(raw.get("font") or raw.get("fontFamily"))
    if (raw.get("font") or raw.get("fontFamily")) and not named_font:
        warnings.append(f"font {str(raw.get('font') or raw.get('fontFamily'))[:40]!r} is not one the renderer has")
    caption = str(raw.get("caption_style") or raw.get("captionStyle") or "").strip().lower()
    if caption and caption not in templates.load().get("captionStyles", {}):
        warnings.append(f"caption style {caption[:30]!r} unknown")
        caption = ""
    kit = {
        "id": _text(raw.get("id"), 64), "name": _text(raw.get("name"), 80) or "Brand kit",
        "accent": accent, "accent2": accent2, "font": named_font, "caption_style": caption or None,
        "watermark": _watermark(raw.get("watermark")),
        "intro": _clip(raw.get("intro"), INTRO_MAX_SECONDS),
        "outro": _outro(raw.get("outro")),
        "picks": _picks(raw.get("picks"), warnings),
    }
    for key in ("watermark", "intro", "outro"):
        if isinstance(raw.get(key), dict) and raw[key].get("url") and raw[key].get("enabled") is not False \
                and not (kit[key] or {}).get("url") and not (key == "outro" and (kit[key] or {}).get("kind") == "card"):
            warnings.append(f"{key}: its link cannot be used")
    kit["warnings"] = warnings
    return kit


def describe(kit: Optional[dict]) -> str:
    """One line for the job's log: what the picks allow."""
    if not kit:
        return "no kit"
    p = kit["picks"]

    def n(v):
        return "all" if v == ALL else ("none" if v in (NONE, []) else str(len(v)))
    return (f"looks {n(p['looks'])}, transitions {n(p['transitions'])}, music {n(p['music'])}, "
            f"sfx {'on' if p['sfx'] else 'off'}, density {p['density']}")


def from_input(inp: Optional[dict]) -> Optional[dict]:
    """The job's kit, parsed once and kept on the input (inp["_brand_kit"])."""
    if not isinstance(inp, dict):
        return None
    if "_brand_kit" not in inp:
        inp["_brand_kit"] = parse(inp.get("brand_kit"))
    return inp["_brand_kit"]


def from_doc(doc: Optional[dict]) -> Optional[dict]:
    """The picks a planned document was made with (doc.meta.brandKit), as a kit with no identity."""
    meta = (doc or {}).get("meta") if isinstance(doc, dict) else None
    saved = meta.get("brandKit") if isinstance(meta, dict) else None
    if not isinstance(saved, dict) or not isinstance(saved.get("picks"), dict):
        return None
    return parse({"id": saved.get("id"), "name": saved.get("name"), "picks": saved["picks"]})


# --------------------------------------------------------------------------- #
# The picks
# --------------------------------------------------------------------------- #

def allowed_looks(kit: Optional[dict]) -> Optional[frozenset]:
    """The looks the kit allows (None: every look)."""
    looks = ((kit or {}).get("picks") or {}).get("looks", ALL)
    return None if looks == ALL or not isinstance(looks, list) else frozenset(looks)


def allowed_transitions(kit: Optional[dict]) -> Optional[frozenset]:
    """The transition values the kit allows (None: every one). A hard cut is always allowed."""
    tr = ((kit or {}).get("picks") or {}).get("transitions", ALL)
    return None if tr == ALL or not isinstance(tr, list) else frozenset(tr)


def pack_clips(kit: Optional[dict]) -> Optional[frozenset]:
    """The overlay-pack clips the kit allows ("mlt5"...; None: every clip, empty: none)."""
    from . import timeline
    allowed = allowed_transitions(kit)
    if allowed is None:
        return None
    if "pack" in allowed:
        return frozenset(timeline.pack_meta())
    return frozenset(v[len(timeline.PACK_PREFIX):] for v in allowed if v.startswith(timeline.PACK_PREFIX))


# The transitions nearest each one, best first: a disallowed transition takes
# the first of these the kit allows, else a hard cut (a jarring stand-in is
# worse than none). Soft changes stay soft, energetic ones energetic.
NEAREST = {
    "fade": ("crossfade", "blur-dissolve", "luma-fade", "dip", "blur", "light-leak", "color-wash"),
    "crossfade": ("fade", "blur-dissolve", "luma-fade", "dip", "blur"),
    "blur-dissolve": ("blur", "fade", "crossfade", "luma-fade", "dip"),
    "blur": ("blur-dissolve", "fade", "crossfade", "zoom", "luma-fade"),
    "luma-fade": ("dip", "fade", "blur-dissolve", "crossfade"),
    "dip": ("luma-fade", "fade", "blur-dissolve", "crossfade"),
    "light-leak": ("film-burn", "color-wash", "flash", "fade", "blur-dissolve"),
    "film-burn": ("light-leak", "flash", "color-wash", "fade"),
    "color-wash": ("light-leak", "fade", "flash", "blur-dissolve"),
    "flash": ("chromatic-flash", "light-leak", "zoom-punch", "punch", "film-burn"),
    "chromatic-flash": ("flash", "glitch", "vhs-glitch", "zoom-punch"),
    "glitch": ("vhs-glitch", "chromatic-flash", "mosaic", "flash"),
    "vhs-glitch": ("glitch", "chromatic-flash", "mosaic"),
    "mosaic": ("glitch", "vhs-glitch", "blur"),
    "whip": ("whip-pan", "slide", "zoom"),
    "whip-pan": ("whip", "slide", "zoom-punch"),
    "slide": ("whip", "whip-pan", "split-wipe", "bar-wipe"),
    "zoom": ("zoom-punch", "punch", "blur"),
    "zoom-punch": ("punch", "zoom", "shake-cut", "flash"),
    "punch": ("zoom-punch", "zoom", "shake-cut"),
    "shake-cut": ("punch", "zoom-punch", "glitch"),
    "split-wipe": ("bar-wipe", "slide", "whip"),
    "bar-wipe": ("split-wipe", "slide", "whip"),
}


def nearest_transition(value: str, allowed: Optional[Iterable[str]]) -> str:
    """`value` when allowed, else the nearest allowed transition, else a hard cut ("none")."""
    if not value or value == "none" or allowed is None:
        return value or "none"
    allowed = set(allowed)
    if value in allowed:
        return value
    return next((alt for alt in NEAREST.get(value, ()) if alt in allowed), "none")


def limit_transitions(entrances: List[str], kit: Optional[dict]) -> List[str]:
    """The planned scene entrances kept to the kit's transitions (pack clips are planned separately)."""
    allowed = allowed_transitions(kit)
    if allowed is None:
        return list(entrances)
    from . import timeline
    return [e if str(e).startswith(timeline.PACK_PREFIX) else nearest_transition(e, allowed) for e in entrances]


# Genres nearest each other: suspense and crime are both tense, the
# investigative bed is the calm one.
NEAREST_GENRE = {"investigative": ("suspense", "crime"), "suspense": ("crime", "investigative"),
                 "crime": ("suspense", "investigative")}


def music_limit(inp: Optional[dict]):
    """
    What the kit allows for this job's music: None (any track), "none" (no
    music) or the set of allowed track names. Only when the job made no music
    choice of its own (prepare_input marks it): the editor's pick wins.
    """
    if not isinstance(inp, dict) or not inp.get("_brand_music"):
        return None
    kit = from_input(inp)
    music = ((kit or {}).get("picks") or {}).get("music", ALL)
    if music == ALL or kit is None:
        return None
    if music == NONE or not music:
        return NONE
    from . import timeline
    tracks = set()
    for m in music:
        if m in timeline.BGM_TRACKS:
            tracks.update(name for name, _ in timeline.BGM_TRACKS[m])
        else:
            tracks.add(m)
    return frozenset(tracks)


def pick_music(genre: str, track: str, seconds: float, allowed: Iterable[str], seed: str = "") -> Tuple[str, str]:
    """
    (genre, track) inside the allowed tracks: the planned track when allowed,
    else an allowed track of the same genre, else of the nearest genre - one
    long enough to run under the whole narration first, varied by `seed`.
    """
    from . import timeline
    import zlib
    allowed = set(allowed or ())
    if track in allowed:
        return genre, track
    order = [genre] + [g for g in NEAREST_GENRE.get(genre, ()) if g != genre] + \
        [g for g in timeline.BGM_GENRES if g != genre and g not in NEAREST_GENRE.get(genre, ())]
    for g in order:
        options = [(name, length) for name, length in timeline.BGM_TRACKS.get(g, ()) if name in allowed]
        if not options:
            continue
        long_enough = [name for name, length in options if length >= seconds] or [name for name, _ in options]
        return g, long_enough[zlib.crc32(seed.encode("utf-8")) % len(long_enough)]
    return genre, track


# --------------------------------------------------------------------------- #
# The job input
# --------------------------------------------------------------------------- #

def prepare_input(inp: dict) -> Optional[dict]:
    """
    Fold the kit's defaults into the job input, in place, before the video
    style is applied (styles.apply): the graphics density, sound effects on or
    off, the caption style and the colours and font. A choice the job made
    itself (the project's own settings) wins over the kit - the kit is the
    customer's default. Music the job did not choose is marked as the kit's
    (music_limit). Returns the kit (None without one).
    """
    kit = from_input(inp)
    if kit is None:
        return None
    picks = kit["picks"]
    if picks["density"] != "auto" and not str(inp.get("graphics_density") or "").strip():
        inp["graphics_density"] = picks["density"]
    if picks["sfx"] is False and not isinstance(inp.get("sfx"), bool):
        inp["sfx"] = False
    if kit.get("caption_style") and not inp.get("caption_style"):
        inp["caption_style"] = kit["caption_style"]
    brand = dict(inp["brand"]) if isinstance(inp.get("brand"), dict) else {}
    if kit.get("accent"):
        brand["accent"] = kit["accent"]
    if kit.get("font"):
        brand["fontFamily"] = kit["font"]
    if brand:
        inp["brand"] = brand
    if not any(inp.get(k) for k in ("bgm_url", "bgm_track", "bgm_genre")) and inp.get("bgm") is not False:
        inp["_brand_music"] = True
    if kit.get("warnings"):
        print(f"[brand] {kit['name']}: {'; '.join(kit['warnings'][:4])}", flush=True)
    return kit


@contextlib.contextmanager
def scope(kit: Optional[dict]):
    """
    The kit's picks in force for the planner (and everything it calls):
    templates.banned() answers True for a look outside them, and the compact
    figures keep out of the watermark's corner. With no kit, nothing changes.
    """
    from . import treatments
    corner = ((kit or {}).get("watermark") or {}).get("position") or ""
    with templates.only(allowed_looks(kit)), treatments.keep_clear(corner):
        yield kit


# --------------------------------------------------------------------------- #
# After planning: only the picks
# --------------------------------------------------------------------------- #

def _needs(ov: dict) -> Tuple[str, ...]:
    """The data an overlay carries that a stand-in look must be able to draw."""
    out = []
    if isinstance(ov.get("locations"), list) and ov["locations"]:
        out.append("locations")
    if isinstance(ov.get("items"), list) and len(ov["items"]) >= 2:
        out.append("items")
    if isinstance(ov.get("value"), (int, float)) and not isinstance(ov.get("value"), bool):
        out.append("value")
    return tuple(out)


def _cue_families() -> List[set]:
    """Cues that draw the same kind of thing: one figure, several values, a date, words, a map, a person, a photo."""
    from . import treatments as vt
    return [set(vt.SINGLE_FIGURE_CUES) | {"count", "age", "big-number"}, set(vt.FULL_DATA_CUES),
            set(vt.DATE_CUES) | {"year", "years", "time-span"}, set(vt.TEXT_CUES),
            {"place", "route", "region", "multi", "map", "location", "forecast-rain", "forecast-wind"},
            {"person", "person-full", "profile", "photo-person"},
            {"photo", "photo-place", "photo-object", "place-photo", "object-photo", "subject-photo", "intro"}]


def closest_look(template_id: str, allowed: Optional[Iterable[str]], *, card: bool = False,
                 needs: Iterable[str] = ()) -> Optional[str]:
    """
    The allowed look nearest `template_id`: one that answers the same cues
    (what the look is about - a percentage, a place, a date), else a cue of
    the same family (a percentage and a count are both one figure), then the
    same component, category, kind and family of looks. It must draw the
    data the overlay carries (`needs`: locations, items, a value) and, for a
    full-screen scene (`card`), fill the frame. None when no allowed look is
    about the same kind of thing.
    """
    if allowed is None:
        return template_id
    allowed = set(allowed)
    if template_id in allowed and not templates.banned_always(template_id):
        return template_id
    t = templates.get(template_id)
    if not t:
        return None
    from . import treatments
    cues = set(templates.cues_of(t))
    kin = set().union(*[f for f in _cue_families() if f & cues]) if cues else set()
    pictures = treatments.look_slots(t)[0] > 0
    best, best_key = None, None
    for n, c in enumerate(templates.all_templates()):
        cid = c["id"]
        if cid not in allowed or templates.banned_always(cid) or not treatments.auto_ok(cid) \
                or not templates.auto_pick(c):
            continue
        if card and c.get("kind") not in treatments.CARD_KINDS:
            continue
        if any(k not in (c.get("props") or {}) for k in needs):
            continue
        theirs = set(templates.cues_of(c))
        shared = cues & theirs
        related = bool(kin & theirs)
        if not shared and not related:
            continue
        score = 3 * len(shared) + (1 if related else 0) + 2 * (c.get("component") == t.get("component")) \
            + 2 * (c.get("category") == t.get("category")) + (c.get("kind") == t.get("kind")) \
            + (templates.family(c) == templates.family(t)) \
            - 2 * (treatments.look_slots(c)[0] > 0 and not pictures)
        key = (-score, n)
        if best_key is None or key < best_key:
            best, best_key = cid, key
    return best


# What an overlay keeps when its look is swapped: what it says and where it is.
_CONTENT = ("text", "subtitle", "label", "suffix", "prefix", "value", "total", "items", "locations", "highlight",
            "body", "media", "mediaFrom", "anchor", "labelPosition", "startFrame", "durationInFrames", "fontScale",
            "theme")
# ... and, when the stand-in is the same kind of look, how it sits.
_PLACEMENT = ("compact", "position", "scale", "backdrop", "align", "textStyle", "opacity")


def _swap(ov: dict, new_id: str) -> bool:
    """Make `ov` an instance of `new_id`, keeping its content (and its placement when the kinds match)."""
    old = templates.get(ov.get("template") or "") or {}
    new = templates.get(new_id) or {}
    resolved = templates.resolve(new_id, props={k: ov[k] for k in ("text", "subtitle", "label") if k in ov})
    if not resolved:
        return False
    resolved.pop("seconds", None)
    resolved.pop("sfx", None)
    keep = {k: ov[k] for k in _CONTENT if k in ov}
    if old.get("kind") == new.get("kind"):
        keep.update({k: ov[k] for k in _PLACEMENT if k in ov})
    ov.clear()
    ov.update(resolved)
    ov.update(keep)
    return True


def enforce(doc: dict, kit: Optional[dict]) -> Dict[str, int]:
    """
    After planning (the planner itself only draws allowed looks; this catches
    the side paths - an archive tag, a photo look made one-picture, the marks,
    a look the director named): every overlay whose look the kit leaves out
    takes the closest allowed look, or goes; every full-screen animation scene
    takes the closest allowed full-screen look, or becomes an empty scene that
    the last resort fills (the line's allowed graphic, the neighbouring shot
    held over it, the line as text) - never an empty frame. Overlays without a
    library look (the job's title card) stay. Returns what it changed.
    """
    out = {"swapped": 0, "dropped": 0, "scenesSwapped": 0, "scenesFilled": 0}
    allowed = allowed_looks(kit)
    if allowed is None or not isinstance(doc, dict):
        return out
    with scope(kit):
        keep, gone = [], []
        for ov in doc.get("overlays") or []:
            tid = ov.get("template") if isinstance(ov, dict) else None
            if not tid or not templates.get(tid) or tid in allowed:
                keep.append(ov)
                continue
            new = closest_look(tid, allowed, needs=_needs(ov))
            if new and _swap(ov, new):
                out["swapped"] += 1
                keep.append(ov)
            else:
                out["dropped"] += 1
                gone.append(ov)
        if gone:
            doc["overlays"] = keep
            # A row that played a dropped look's own sound goes with it.
            starts = {int(o.get("startFrame") or 0) for o in gone}
            doc["sfx"] = [fx for fx in doc.get("sfx") or [] if not (
                isinstance(fx, dict) and fx.get("kind") == "overlay" and int(fx.get("startFrame") or 0) in starts)]
        emptied = 0
        for sc in doc.get("scenes") or []:
            m = sc.get("media") if isinstance(sc, dict) else None
            anim = sc.get("animation") if isinstance(sc, dict) else None
            if not isinstance(m, dict) or m.get("type") != "animation" or not isinstance(anim, dict):
                continue
            tid = anim.get("template")
            if not tid or not templates.get(tid) or tid in allowed:
                continue
            new = closest_look(tid, allowed, card=True, needs=_needs(anim))
            if new and _swap(anim, new):
                anim.pop("startFrame", None)
                anim.pop("durationInFrames", None)
                out["scenesSwapped"] += 1
                continue
            sc["media"] = {"type": "color", "url": "", "source": "none"}
            sc.pop("animation", None)
            sc["visualType"] = "footage"
            emptied += 1
        if emptied:
            from . import gapfill
            filled = gapfill.hold_or_animate(doc, label="brand kit looks")
            out["scenesFilled"] = emptied
            out["fill"] = filled
    if any(v for k, v in out.items() if k != "fill"):
        print(f"[brand] looks outside the kit: {out}", flush=True)
    return out


def second_colour(overlays: Iterable[dict], scenes: Iterable[dict], kit: Optional[dict]) -> int:
    """
    The figures and charts (SECOND_COLOUR_CATEGORIES) draw in the kit's second
    colour: their overlay or animation scene names the theme "accent2"
    (overlays.tsx accentFor). Only looks with no colour of their own chosen.
    Returns how many were set.
    """
    if not (kit or {}).get("accent2"):
        return 0
    n = 0
    targets = [ov for ov in overlays if isinstance(ov, dict)] + [
        sc["animation"] for sc in scenes if isinstance(sc, dict) and isinstance(sc.get("animation"), dict)]
    for ov in targets:
        t = templates.get(ov.get("template") or "") or {}
        if t.get("category") in SECOND_COLOUR_CATEGORIES and not ov.get("theme"):
            ov["theme"] = SECOND_THEME
            n += 1
    return n


# --------------------------------------------------------------------------- #
# The renderer's brand block
# --------------------------------------------------------------------------- #

def doc_brand(kit: Optional[dict]) -> Optional[dict]:
    """
    The document's `brand` block (remotion/src/types.ts BrandBlock): colours,
    font, the watermark, the intro and the outro as the kit set them. The
    intro and outro carry no frames here - the render measures the files and
    writes them (prepare_render), so a saved plan never shifts in the editor.
    """
    if kit is None:
        return None
    out: Dict[str, Any] = {"kit": {"id": kit.get("id") or "", "name": kit.get("name") or ""}}
    for key, field in (("accent", "accent"), ("accent2", "accent2"), ("font", "fontFamily")):
        if kit.get(key):
            out[field] = kit[key]
    for key in ("watermark", "intro", "outro"):
        if kit.get(key):
            out[key] = dict(kit[key])
    return out


def meta(kit: Optional[dict]) -> Optional[dict]:
    """What the document records of the kit (doc.meta.brandKit): its name and the picks it was planned with."""
    if kit is None:
        return None
    return {"id": kit.get("id") or "", "name": kit.get("name") or "", "picks": dict(kit["picks"]),
            **({"warnings": list(kit["warnings"])} if kit.get("warnings") else {})}


def _frames_of(block: Optional[dict], fps: int, most: float) -> int:
    """A brand clip's or card's frames as the renderer reads them (0: not drawn)."""
    if not isinstance(block, dict):
        return 0
    if block.get("kind") != "card" and not safe_url(block.get("url")):
        return 0
    f = block.get("frames")
    if isinstance(f, bool) or not isinstance(f, (int, float)) or not math.isfinite(f) or f <= 0:
        return 0
    return int(min(int(f), int(round(most * fps))))


def layout(doc: dict) -> Tuple[int, int, int, int]:
    """
    (intro, body, outro, total) frames of a document's video: the intro plays
    first, the narration's timeline (doc.durationInFrames) after it, the outro
    last. Without a brand block, (0, body, 0, body). The renderer's twin is
    remotion/src/components/brand/brandLayout.ts brandFrames.
    """
    fps = max(1, int((doc or {}).get("fps") or 30))
    body = max(1, int((doc or {}).get("durationInFrames") or 0))
    brand = (doc or {}).get("brand") if isinstance((doc or {}).get("brand"), dict) else {}
    intro = _frames_of(brand.get("intro"), fps, INTRO_MAX_SECONDS)
    outro = _frames_of(brand.get("outro"), fps, OUTRO_MAX_SECONDS if (brand.get("outro") or {}).get(
        "kind") == "video" else CARD_MAX_SECONDS)
    return intro, body, outro, intro + body + outro


def total_frames(doc: dict) -> int:
    """Every frame the renderer draws for a document: intro, narration, outro."""
    return layout(doc)[3]


# --------------------------------------------------------------------------- #
# Before a render: measured and checked
# --------------------------------------------------------------------------- #

def _probe(path: str) -> dict:
    """{"video": bool, "audio": bool, "duration": s} of a local file (ffprobe); {} when unreadable."""
    import json
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type:format=duration",
                            "-of", "json", path], capture_output=True, text=True, timeout=60)
        info = json.loads(p.stdout or "{}") or {}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}
    kinds = {s.get("codec_type") for s in info.get("streams") or []}
    try:
        dur = float((info.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        dur = 0.0
    return {"video": "video" in kinds, "audio": "audio" in kinds, "duration": dur if math.isfinite(dur) else 0.0}


def _fetch(url: str, path: str, most_bytes: int) -> str:
    """Download a brand file (a size cap, the worker's own downloader); "" when it cannot be had."""
    import requests
    try:
        with requests.get(url, stream=True, timeout=(15, 120), headers={"User-Agent": config.USER_AGENT}) as r:
            if r.status_code != 200 or "text/html" in (r.headers.get("Content-Type") or "").lower():
                return ""
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            got = 0
            with open(path + ".part", "wb") as fh:
                for block in r.iter_content(1 << 20):
                    got += len(block)
                    if got > most_bytes:
                        raise ValueError("too big")
                    fh.write(block)
        os.replace(path + ".part", path)
        return path if got > 0 else ""
    except Exception as e:  # noqa: BLE001 - a brand file that cannot be read is left out, never a failure
        print(f"[brand] could not fetch {url[:100]}: {type(e).__name__}", flush=True)
        try:
            os.remove(path + ".part")
        except OSError:
            pass
        return ""


_IMAGE_MAGIC = (b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"RIFF", b"<svg", b"<?xm")


def _is_image(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            head = fh.read(512)
    except OSError:
        return False
    if head.startswith(b"RIFF") and head[8:12] != b"WEBP":
        return False
    return head.startswith(_IMAGE_MAGIC) or b"<svg" in head.lower()


def _clip_level(lufs: Optional[float], voice_lufs: Optional[float]) -> float:
    """A brand clip's volume: its loudness brought to the narration's, never louder than as recorded."""
    if lufs is None:
        return 0.8
    from . import sfxplan
    voice = sfxplan.voice_level(voice_lufs)
    return round(max(0.05, min(1.0, 10 ** ((voice - float(lufs)) / 20.0))), 3)


def prepare_render(doc: dict, inp: Optional[dict], work: str, fetch=None, probe=None,
                   measure=None) -> Dict[str, Any]:
    """
    Before a render: the brand block from the job's kit (the kit as it is
    now; else the one the plan recorded), every file in it checked - the logo
    is read and must be a picture, the intro and outro must be videos - and
    the intro's and outro's frames and sound levels written for the renderer.
    Anything that fails is left out with a warning: the video renders without
    it, never fails over it. The colours and font follow the kit too. Returns
    what it did (for doc.meta.brand).
    """
    fetch = fetch or _fetch
    probe = probe or _probe
    if measure is None:
        from .timeline import measure_lufs as measure
    kit = from_input(inp) if isinstance(inp, dict) and inp.get("brand_kit") else None
    if kit is not None:
        block = doc_brand(kit)
        caps = doc.setdefault("captions", {}) if isinstance(doc.get("captions"), dict) or "captions" not in doc \
            else None
        if isinstance(caps, dict):
            if kit.get("accent"):
                caps["accent"] = kit["accent"]
            if kit.get("font"):
                caps["fontFamily"] = kit["font"]
    else:
        block = doc.get("brand") if isinstance(doc.get("brand"), dict) else None
        block = doc_brand(parse({**block, "font": block.get("fontFamily")})) if block else None
        if block is not None and isinstance(doc.get("brand"), dict):
            block["kit"] = dict(doc["brand"].get("kit") or {})
    if block is None:
        doc.pop("brand", None)
        return {}
    report: Dict[str, Any] = {"kit": (block.get("kit") or {}).get("name", ""), "dropped": []}
    fps = max(1, int(doc.get("fps") or 30))
    voice = (doc.get("meta") or {}).get("voiceLufs") if isinstance(doc.get("meta"), dict) else None
    folder = os.path.join(work or config.WORK_DIR, "brand")
    wm = block.get("watermark")
    if wm:
        local = fetch(wm["url"], os.path.join(folder, "logo"), LOGO_MAX_BYTES)
        if not local or not _is_image(local):
            report["dropped"].append("watermark: the logo could not be read")
            block.pop("watermark", None)
    for key, most in (("intro", INTRO_MAX_SECONDS), ("outro", OUTRO_MAX_SECONDS)):
        part = block.get(key)
        if not isinstance(part, dict):
            continue
        if part.get("kind") == "card":
            part["frames"] = int(round(_number(part.get("seconds"), CARD_MIN_SECONDS, CARD_MAX_SECONDS,
                                               CARD_DEFAULT_SECONDS) * fps))
            if part.get("logo"):
                local = fetch(part["logo"], os.path.join(folder, "card_logo"), LOGO_MAX_BYTES)
                if not local or not _is_image(local):
                    part.pop("logo")
            report[key] = round(part["frames"] / fps, 2)
            continue
        local = fetch(part["url"], os.path.join(folder, key), CLIP_MAX_BYTES)
        info = probe(local) if local else {}
        seconds = float(info.get("duration") or 0)
        if not local or not info.get("video") or seconds <= 0.1:
            report["dropped"].append(f"{key}: the video could not be read")
            block.pop(key, None)
            continue
        part["frames"] = max(1, int(math.floor(min(seconds, most) * fps)))
        part["volume"] = _clip_level(measure(local) if info.get("audio") else None, voice) if info.get(
            "audio") else 0.0
        part["seconds"] = round(part["frames"] / fps, 3)
        report[key] = part["seconds"]
    report["watermark"] = bool(block.get("watermark"))
    doc["brand"] = block
    if report["dropped"]:
        doc.setdefault("meta", {}).setdefault("warnings", []).append(
            "Brand kit: " + "; ".join(report["dropped"]) + " - the video was made without it.")
        print(f"[brand] {'; '.join(report['dropped'])}", flush=True)
    return report


def body_scan(doc: dict, res: dict) -> dict:
    """
    A scan of a finished video (quality.scan, seconds of the whole file) as
    seconds of the narration's timeline: the intro's length taken off every
    stretch, stretches inside the intro or the outro left out (they are the
    customer's own clips and card), the duration the body's. Unchanged when
    the document has no intro or outro.
    """
    intro, body, outro, _total = layout(doc)
    if not intro and not outro:
        return res
    fps = max(1, int(doc.get("fps") or 30))
    a0, b1 = intro / fps, (intro + body) / fps
    out = dict(res)
    for key in ("black", "frozen", "silent"):
        spans = []
        for a, b in res.get(key) or []:
            lo, hi = max(float(a), a0), min(float(b), b1)
            if hi - lo > 0:
                spans.append((round(lo - a0, 3), round(hi - a0, 3)))
        out[key] = spans
    out["duration"] = round(body / fps, 3)
    return out
