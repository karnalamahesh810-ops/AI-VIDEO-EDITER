"""
What slipped past the AI-slop filter and the vision judge in the Hoover Dam video (2026-10-26, its full watch:
docs/vidfix-2026-10-26.md section 3), turned into cheap, deterministic checks - no extra model call except the
focused second look at a mark the free pixel signal finds on a news clip (~$0.0003, capped per video):

* title_flaw         an upload whose title is a hypothetical or a CGI explainer ("What Happens If Hoover Dam
                     Breaks?", "The First 24 Hours After Hoover Dam Fails", "The Untold Story of How It Was Built |
                     Engineering Marvel", "How Water Ate a 45-Foot Hole the Size of a House!") - their pictures are
                     renders the judge called real; turned down before any download unless the line itself asks for
                     a simulation or a what-if.
* description_flaw   the judge's own sentence says what it saw and the verdict ignored it: "An animation of Lake Mead
                     ... with an overlay showing 'Operating Elevations'", "with a graphic overlay", a banner quoting a
                     creator's title; and for a picture: a TV frame with a chyron (a screen grab), a split-screen or
                     before-and-after collage, a hand holding a tablet showing a document (a stock mock-up).
* screen_text_conflict the words of a banner on the clip name another state or region than the line's ("Powerful
                     waves batter Southern California coast" under a Las Vegas flood line): vision.judge reads them
                     into verdict.screen_text, media.title_conflict decides.
* broadcaster        whether a logo on a news clip may stay: the uploader is a TV station / news outlet, or the
                     logo's own text names one (FOX 5, CBS, KOLD); another channel's mark ("LEVEL", "window to the
                     world", "BE", "CH") is turned down (vision.text_check_decision).

Every check returns "" (keep) or a short reason; the gate (src/media.py) counts them in meta.sourcing.slipcheck.
SLIP_CHECKS=0 turns them all off.
"""
from __future__ import annotations

import re
import threading
from typing import Dict, Optional

from . import config

STATS: Dict[str, int] = {"titles": 0, "descriptions": 0, "screenText": 0, "marks": 0}
_LOCK = threading.Lock()


def enabled() -> bool:
    return bool(getattr(config, "SLIP_CHECKS", True))


def reset() -> None:
    with _LOCK:
        for k in STATS:
            STATS[k] = 0


def note(kind: str) -> None:
    with _LOCK:
        STATS[kind] = STATS.get(kind, 0) + 1


def stats() -> Dict[str, int]:
    with _LOCK:
        return dict(STATS)


# --------------------------------------------------------------------------- titles
# Hypotheticals and CGI explainers: their "footage" is a render. Measured on the Hoover Dam video's 70 placed
# uploads: these caught the 3 render clips the judge passed (#48, #95, #150) and 2 more of the same kind (#23, #103),
# and none of the real news, drone, phone or tour footage.
_HYPOTHETICAL = re.compile(
    r"\bwhat (?:happens|would happen|will happen) (?:if|when)\b|\bwhat if\b|\bif .{0,40}\b(?:broke|breaks|failed|fails|"
    r"collapsed|collapses)\b|\bafter .{0,40}\b(?:fails|failed|breaks|collapses|collapsed)\b|\bhour by hour\b|"
    r"\bsimulat\w*|\banimat\w*|\bcgi\b|\b3d (?:model|render|animation|simulation)\b|\brender(?:ed|ing)?\b|"
    r"\bhypothetical\b|\bdoomsday scenario\b|\buntold story\b|\bengineering marvel\b|\bhow .{0,40}\bwas built\b|"
    r"\bthe size of a (?:house|building|car|football)\b|\bai[- ]generated\b|\bvisuali[sz]ation\b", re.I)


def title_flaw(title: str, line: str = "") -> str:
    """Why an upload's title says its pictures are renders ("" = keep). A line that itself asks for a simulation or
    a what-if may take one."""
    if not enabled() or not title:
        return ""
    m = _HYPOTHETICAL.search(str(title))
    if not m or _HYPOTHETICAL.search(str(line or "")):
        return ""
    return f"a hypothetical or CGI explainer upload ('{m.group(0).strip()[:30]}')"


# --------------------------------------------------------------------------- the judge's own words
_RENDER_WORDS = re.compile(
    r"\b(?:an? )?(?:animation|animated|cartoon|3d (?:model|render|rendering|animation|graphic)|cgi|computer[- ]generated|"
    r"rendering|rendered|digital (?:art|illustration|painting|recreation|reconstruction)|simulation|simulated|"
    r"illustration|video game|game footage|virtual model)\b", re.I)
_CREATOR_GRAPHICS = re.compile(
    r"\b(?:graphic(?:al)? overlay|overlay (?:showing|of|reading|with|labell?ed|that)|with an? (?:text |graphic |data )?"
    r"overlay|text overlay|infographic|title card|on-screen (?:graphic|text|title)|(?:banner|caption|title|text) "
    r"(?:reading |saying |that reads )?[\"“']|labels? (?:reading|saying) [\"“']|subscribe|face ?cam|picture[- ]in[- ]picture|"
    r"split[- ]screen)", re.I)
_NEWS_BANNER = re.compile(r"\b(?:news )?(?:chyron|news banner|breaking news|lower[- ]third|news ticker|headline banner|"
                          r"news overlay|news graphic|station (?:logo|bug))\b", re.I)
_COLLAGE = re.compile(r"\b(?:split[- ]screen|side[- ]by[- ]side|collage|before[- ]and[- ]after|two (?:photos|pictures|"
                      r"images|views) (?:side|of)|comparison (?:image|photo|picture|of)|(?:two|three|four) panels?|"
                      r"grid of)\b", re.I)
_MOCKUP = re.compile(r"\b(?:holds?|holding|held) (?:up )?an? (?:tablet|ipad|phone|smartphone|laptop|newspaper)\b|"
                     r"\b(?:tablet|phone|smartphone|laptop|monitor|television|tv|computer) (?:screen )?(?:showing|"
                     r"displaying|with)\b|\bscreen ?(?:shot|grab|capture)\b|\bmock-?up\b", re.I)


def description_flaw(description: str, kind: str = "clip", wants: str = "", subject_type: str = "",
                     news: bool = False) -> str:
    """
    Why the judge's own description turns a kept candidate down ("" = keep). `kind` "clip" or "picture"; `wants` the
    line's kind of picture (a map / chart / document line may take a drawing, a diagram or a screen); `news` a news
    story (a broadcaster's banner over a CLIP is welcome there - never on a picture: a web picture with a chyron is a
    TV frame grabbed by a site).
    """
    if not enabled():
        return ""
    d = " ".join(str(description or "").split())
    if not d:
        return ""
    drawn_ok = wants in ("map", "chart", "document") or subject_type == "document"
    m = _RENDER_WORDS.search(d)
    if m and not drawn_ok:
        return f"an animation or render (the judge: '{m.group(0)[:30]}')"
    # (Another creator's graphics on a clip of a strict or event line: the focused second look decides - it already
    # runs on such words there. A news line never gets that look for them, and a picture never does.)
    m = _CREATOR_GRAPHICS.search(d) if (news or kind == "picture") else None
    if m and not drawn_ok and not (news and kind == "clip" and _NEWS_BANNER.search(d) and
                                   not re.search(r"infographic|title card|subscribe|face ?cam|graphic(?:al)? overlay",
                                                 m.group(0), re.I)):
        return f"another creator's graphics (the judge: '{m.group(0)[:30]}')"
    if kind == "picture":
        m = _NEWS_BANNER.search(d)
        if m:
            return f"a TV frame grabbed by a website (the judge: '{m.group(0)[:30]}')"
        m = _COLLAGE.search(d)
        if m and not drawn_ok:
            return f"a collage (the judge: '{m.group(0)[:30]}')"
        m = _MOCKUP.search(d)
        # a hand holding a tablet or a phone is a stock mock-up on any line; a screenshot may be a document's page
        if m and (not drawn_ok or re.search(r"hold|held", m.group(0), re.I)):
            return f"a screen or a stock mock-up (the judge: '{m.group(0)[:30]}')"
    return ""


# --------------------------------------------------------------------------- banners naming another place
def screen_text_conflict(screen_text: str, context: str) -> str:
    """Why the words of a banner on the clip put it somewhere else than the line ("" = keep): another state, region,
    storm or year than the story's (media.title_conflict, the same rule a title meets)."""
    if not enabled():
        return ""
    t = " ".join(str(screen_text or "").split())
    if len(t) < 6:
        return ""
    from . import media
    why = media.title_conflict(t, context)
    return f"its banner says another place or event ('{t[:40]}': {why})" if why else ""


# --------------------------------------------------------------------------- whose logo
_BROADCASTER = re.compile(
    r"\b(?:news|tv|television|(?:fox|cbs|nbc|abc)\s?\d{0,2}|cnn|pbs|npr|msnbc|bbc|reuters|associated press|ap|afp|univision|"
    r"telemundo|weather channel|accuweather|kare|kusa|ksl|kold|knxv|kvvu|ktnv|klas|kvue|khou|kxan|wfaa|wral|wsb|"
    r"cnbc|cbc|ctv|sky|itv|dw|nhk|rte|ndtv|wion|euronews|france ?24|al jazeera|bloomberg|c-span|cspan|"
    r"channel \d{1,2}|\d{1,2} (?:news|on your side|abc|nbc|cbs|fox)|8newsnow|"
    r"action news|eyewitness news|first alert|storm team|national park service|nps|usgs|noaa|bureau of reclamation|"
    r"usbr|fema|national guard|department of|county|city of|police|sheriff|fire department|government)\b", re.I)


# US call letters as written (K/W and 2-3 more capitals, "KTNV", "WFAA-TV"): case matters.
_CALL_LETTERS = re.compile(r"\b[KW][A-Z]{2,3}(?:-TV|-DT)?\b")


def broadcaster(channel: str = "", logo_text: str = "") -> Optional[bool]:
    """True when the uploader (`channel`) or the logo's own text names a TV station, a news outlet or a public
    agency (or the logo is a bare channel number); False when either is known and neither does; None when nothing
    is known."""
    c = " ".join(str(channel or "").split())
    t = " ".join(str(logo_text or "").split())
    if any(x and (_BROADCASTER.search(x) or _CALL_LETTERS.search(x)) for x in (c, t)):
        return True
    if t and re.fullmatch(r"\d{1,2}", t):
        return True                         # a station's channel number as its bug ("13", "8")
    if c or t:
        return False
    return None
