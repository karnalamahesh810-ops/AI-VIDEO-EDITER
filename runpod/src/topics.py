"""
Topic-aware content rules (the owner, 2026-10-06): a music video, a rap or music performance, a club or
party, or someone smoking, vaping, taking drugs or drinking has nothing to do with a story about water, a
storm or a politician's family - "we don't want those clips in our videos" - yet a video ABOUT music, a
rapper, nightlife or drugs needs exactly those shots. So the rule is about the story and the line:

  * the story (the director's brief: what the video is about) or the line (its intent and narration)
    names music / musicians / nightlife  -> music videos and performances are allowed (still judged for
    relevance like any clip);
  * the story or the line names smoking / vaping / drugs / drinking               -> those scenes are allowed;
  * otherwise they are off topic: a candidate is turned down at search time by its title, channel or
    YouTube category (off_topic_title), and the vision judge's music_or_vice answer turns a downloaded one
    down (allows_vice) - remembered for the whole job (media.judged_line_free, JUDGE_MEMORY).

The relevance judge stays strict either way: a clip must show what its line is about.
"""
from __future__ import annotations

import re
import threading
from typing import Iterable, Optional

# A story or a line about music, musicians or nightlife.
# ("album", "band", "party" and "bar" are left out: a family photo album, a political party, a sand bar.)
_MUSIC_TOPIC = re.compile(
    r"\b(music\w*|musician\w*|rap(?!\s+sheet)|raps|rapper\w*|rapping|hip[- ]?hop|singer\w*|songs?|songwriter\w*|"
    r"concert\w*|music festival\w*|nightclub\w*|nightlife|clubbing|dj|djs|record label\w*|grammy\w*|"
    r"vevo|lyric\w*|drill music|trap music|r&b|pop star\w*|popstar\w*|rock star\w*|rockstar\w*|"
    r"orchestra\w*|debut album|studio album|mixtape\w*)\b", re.I)
# A story or a line about smoking, vaping, drugs or drinking (or the places for them).
# (Not "smoke" or "drinking water": a wildfire's smoke and a city's drinking water are not a vice.)
_VICE_TOPIC = re.compile(
    r"\b(smoker|smokers|chain[- ]smok\w*|(?:quit(?:ting|s)?|stop(?:ped|ping)?)\s+smoking|smoking\s+(?:habit|addiction)|"
    r"smok(?:e|es|ed|ing)\s+(?:a\s+|his\s+|her\s+|their\s+)?(?:cigarettes?|cigars?|weed|pot|joints?|crack|meth|"
    r"marijuana|pipe)|"
    r"cigarette\w*|cigar|cigars|tobacco|nicotine|vape|vapes|vaping|vaper\w*|weed|marijuana|cannabis|"
    r"drug\s+(?:use|users?|abuse|addiction|deal\w*|cartel\w*|trade|overdose\w*)|drugs|cocaine|heroin|fentanyl|"
    r"opioid\w*|meth|methamphetamine|crack cocaine|alcohol\w*|alcoholic\w*|drunk\w*|drinker\w*|drinking(?![\s-]+water)|"
    r"booze|beer\w*|liquor|whisk(?:e)?y|vodka|addict\w*|overdos\w*|nightclub\w*|nightlife)\b", re.I)
# A music video, a lyric or audio upload, a rap performance - by its title or channel.
_MUSIC_TITLE = re.compile(
    r"[(\[]\s*official\s+(?:music\s+|lyric\s+)?(?:video|audio)\s*[)\]]|"
    r"[-|:]\s*official\s+(?:music\s+)?video\b|\bofficial\s+music\s+video\b|\bmusic\s+video\b|"
    r"\blyrics?\b|\blyric\s+video\b|[(\[]\s*audio\s*[)\]]|\bofficial\s+audio\b|\bvisuali[sz]er\b|"
    r"vevo\b|\bfreestyle\b|\bdiss(?:\s+track)?\b|\brappers?\b|\bremix(?:es)?\b|\bprod\.\s|\bcypher\b", re.I)
# "Song ft. Artist", "(feat. Artist)" - never "24 ft. seas".
_FEAT = re.compile(r"(?<!\d)[\s(\[](?:ft|feat)\.\s*\S", re.I)
# "Freestyle" is a rap word - and a swimming, skiing or BMX one.
_SPORT = re.compile(r"\b(swim\w*|ski|skis|skiing|skier\w*|bmx|motocross|fmx|snowboard\w*|wrestl\w*|relay|"
                    r"olympic\w*|medley|backstroke|butterfly|breaststroke|skat\w*|scooter|football|soccer|"
                    r"chess|kayak\w*|\d+\s*m)\b", re.I)
# A scenery upload filed under YouTube's Music category (a 4K drone film over a lake, set to music): footage,
# not a music video - the judge still looks at its frames.
_SCENERY = re.compile(r"\b(drone|aerial|4k|8k|scenery|scenic|nature|relax\w*|ambient|ambience|sounds? of|"
                      r"waterfalls?|rivers?|ocean|timelapse|time-lapse|landscapes?|footage|walk(?:ing)? tour|"
                      r"national park|cinematic)\b", re.I)

# A described shot of someone smoking, vaping, taking drugs or drinking alcohol - said outright (scene_reason).
# The word "smoking" alone is not it: the Obama video's Huruma (Nairobi) aerial, "a large, smoking garbage dump",
# was taken for a smoking scene and re-clipped away (2026-10-08). Smoke from a fire, a dump, a chimney, a
# volcano, cooking or traffic, "a joint session", "a blunt statement", weeds and drinking water are no vice.
# What is smoked: unmistakable with any verb (a cigarette, a joint) or only after "smoke" / "puff on" (weed,
# crack, a pipe - "holding a pipe" is a plumber; "a smoking pot" is a stove, so pot is never read).
_SMOKED_PLAIN = r"(?:cigarettes?|cigars?|cigarillos?|joints?|blunts?|spliffs?|e-?cigarettes?|vapes?|bongs?|hookahs?)"
_SMOKED_DRUG = r"(?:weed|marijuana|cannabis|hash(?:ish)?|crack|meth|heroin|opium|shisha|tobacco|(?:a|an|his|her|their)\s+pipe)"
_ARTICLE = r"(?:(?:a|an|the|his|her|their|some|another|one)\s+)?"
_VICE_SCENE = re.compile(
    # smoking / puffing on ... a cigarette, weed, a pipe; lighting / rolling / passing a cigarette, a joint
    rf"\b(?:smok(?:e|es|ed|ing)|puff(?:s|ed|ing)?(?:\s+on)?|inhal(?:e|es|ed|ing))\s+{_ARTICLE}"
    rf"(?:{_SMOKED_PLAIN}|{_SMOKED_DRUG})\b"
    rf"|\b(?:light(?:s|ed|ing)?(?:\s+up)?|lit|roll(?:s|ed|ing)?|pass(?:es|ed|ing)?|shar(?:e|es|ed|ing))\s+"
    rf"{_ARTICLE}{_SMOKED_PLAIN}\b"
    # the things themselves (not their litter, their trade or their shape)
    r"|\b(?:cigarettes?|cigars?|cigarillos?)\b(?![-\s]*(?:shaped|butts?|ads?|adverts?\w*|advertis\w*|factor(?:y|ies)|"
    r"compan(?:y|ies)|tax\w*|bans?|smuggl\w*|brands?)\b)"
    r"|\b(?:vaping|vapers?|vape\s+(?:pens?|clouds?)|bongs?|crack\s+pipes?|hookah\s+(?:lounge|bar|pipe)s?|"
    r"snort(?:s|ed|ing)|(?:inject(?:s|ed|ing)|shoot(?:s|ing))\s+(?:up\s+)?(?:drugs|heroin)|"
    r"drug\s+(?:use|users?|addicts?|den)|using\s+drugs|taking\s+drugs)\b"
    # drinking alcohol, drunk
    r"|\b(?:drink(?:s|ing)?|sip(?:s|ping)?|swig(?:s|ging)?|chug(?:s|ging)?|toast(?:s|ing)?\s+with)\s+"
    r"(?:(?:a|an|the|his|her|their|some|another|cans?|bottles?|glass(?:es)?|pints?|shots?|cups?)\s+(?:of\s+)?)*"
    r"(?:beers?|wine|liquor|whisk(?:e)?y|vodka|rum|gin|tequila|alcohol|booze|spirits|champagne|cocktails?|lager|ale)\b"
    r"|\bdrunk(?:en)?\b(?!\s+driv)|\bintoxicated\b|\bbinge[- ]drinking\b", re.I)
# Someone smoking with no object named: "a man smoking on a porch", "youths smoke outside a shop" - never
# what they smoke over a fire ("women smoking fish") nor a thing that smokes ("chimneys smoking").
_SMOKER = re.compile(
    r"\b(?:man|men|woman|women|person|people|someone|somebody|boy|boys|girl|girls|teen\w*|youths?|guy|guys|he|she|"
    r"they|smokers?|workers?|soldiers?|students?|friends|patrons|customers|passers-?by|locals|villagers|residents)\s+"
    r"(?:(?:is|are|was|were|sits?|sitting|stands?|standing|seen|caught|shown)\s+){0,2}"
    r"(?:smoking|smokes|smoked|smoke|vaping|vapes|vape)\b"
    r"(?!\s+(?:fish|meat|pork|beef|chicken|salmon|ham|sausages?|food|ribs|brisket|turkey|cheese|bacon|tea|"
    r"garbage|rubbish|trash|tyres?|tires|wood|charcoal|bees?|hives?|out)\b)", re.I)

_LOCK = threading.Lock()
_STORY = {"text": ""}


def set_story(brief: Optional[dict], title: str = "") -> None:
    """What the video is about, from the director's brief (and its title): the topic the rules read."""
    b = brief if isinstance(brief, dict) else {}
    roles = " ".join(str(c.get("role") or "") for c in (b.get("cast") or [])[:8] if isinstance(c, dict))
    parts = [title, b.get("title"), b.get("summary"), b.get("event"), b.get("kind"), b.get("topic"),
             b.get("subject"), " ".join(str(p) for p in (b.get("people") or [])[:6] if isinstance(p, str)),
             roles]
    with _LOCK:
        _STORY["text"] = " ".join(str(p) for p in parts if p)[:2000]


def story_text() -> str:
    with _LOCK:
        return _STORY["text"]


def _any(rx, texts: Iterable[str]) -> bool:
    return any(rx.search(str(t or "")) for t in texts if t)


def allows_music(line: str = "", story: Optional[str] = None) -> bool:
    """The story or the line is about music, musicians or nightlife."""
    return _any(_MUSIC_TOPIC, (story_text() if story is None else story, line))


def allows_vice(line: str = "", story: Optional[str] = None) -> bool:
    """A music, club, smoking, drugs or drinking scene may stand for this line: the story or the line is about
    music / nightlife or about that vice."""
    s = story_text() if story is None else story
    return _any(_MUSIC_TOPIC, (s, line)) or _any(_VICE_TOPIC, (s, line))


def music_title(title: str = "", channel: str = "", categories=None) -> str:
    """Why a video is a music video / a rap or music performance by its metadata ("" = it does not look like one)."""
    cats = categories if isinstance(categories, (list, tuple)) else ([categories] if categories else [])
    t = f"{title or ''} {channel or ''}"
    hits = {m.group(0).lower() for m in _MUSIC_TITLE.finditer(t)}
    if hits and all("freestyle" in h for h in hits) and _SPORT.search(t):
        hits = set()                        # "Men's 100m freestyle final", "BMX freestyle"
    if hits or _FEAT.search(" " + str(title or "")):
        return "a music video by its title"
    if any(str(c).strip().lower() == "music" for c in cats) and not _SCENERY.search(str(title or "")):
        return "a music video (YouTube's Music category)"
    return ""


def off_topic_title(title: str = "", channel: str = "", categories=None, line: str = "",
                    story: Optional[str] = None) -> str:
    """music_title's reason when neither the story nor the line is about music ("" = usable)."""
    why = music_title(title, channel, categories)
    if not why or allows_music(line, story):
        return ""
    return why


def vice_scene(text: str) -> bool:
    """A described shot says outright that someone smokes or vapes (a cigarette, a joint...), takes drugs or
    drinks alcohol. Smoke from a fire, a dump, a chimney, cooking or traffic is not such a shot."""
    t = str(text or "")
    return bool(_VICE_SCENE.search(t) or _SMOKER.search(t))


def scene_reason(text: str, line: str = "", story: Optional[str] = None) -> str:
    """Why a described shot (a scene's content description or title) is off topic for its line: a music
    performance or video, or a smoking / drugs / drinking / club scene in a story and line not about it."""
    t = str(text or "")
    if not t or allows_vice(line, story):
        return ""
    if music_title(t) or re.search(r"\b(rapper|rapping|music video|singer performing|performs on stage|"
                                   r"concert stage|nightclub|club scene)\b", t, re.I):
        return "a music performance or music video"
    if vice_scene(t):
        return "a smoking, drugs or drinking scene"
    return ""
