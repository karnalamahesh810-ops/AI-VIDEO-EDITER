"""
Candidates that are not footage of the real world, turned down by their title, channel and YouTube category BEFORE any
download, storyboard pick or vision call (the owner, 2026-10-09: "a random game clip was picked" - "JJ is LEFT
FOREVER in Minecraft! (Maizen)" on a Yellowstone line about ground uplift, a Roblox "Magma Full Showcase | Haze
Seas", the Yellowstone TV show's theme from Paramount Network, "Simon & Garfunkel - Bridge Over Troubled Water
(Audio)", a FIFA highlights reel). General for every niche; each class has its own story exception.

  game     video games and gameplay, mods, game showcases, simulators (Minecraft, Roblox, Fortnite, GTA, BeamNG...)
  kids     kids' animation and toy channels (Maizen, Cocomelon, Peppa Pig...)
  fiction  TV drama, sitcoms and films: a studio's or network's clip channel (Paramount Network, Movieclips...),
           "Official Clip", "Official Trailer", "movie scene" - a show that shares its name with a real place
           or thing ("Bozeman Bar Brawl | Yellowstone | Paramount Network") included
  music    an audio upload or a music video: src/topics.py's rule ("(Audio)", "Official Audio", "Lyrics", "Official
           Music Video", VEVO...) plus an auto-generated "- Topic" channel, "full album", "slowed + reverb"
  sports   a match broadcast's highlights reel or full match
  tutorial a software or gadget tutorial (a screen recording: "Change Satellite Settings", "how to install")

Streams, VODs and reactions are turned down by the talking-head title rule already (media._talking_head).

The exception: the story or the line is about that kind of thing - a video about Minecraft, about the Yellowstone
TV show, a film, a band, a match - read from the story's own words (topics.story_text: the title and the director's
brief) and the line's. A weak sign only (a streaming network's or a talk show's channel, "S2 E11", "Episode 4",
"| Trailer |", "showcase", "animated", YouTube's Entertainment / Film & Animation category) is ambiguous: a cheap text model is asked once per
search for those (OFFTOPIC_AI, OFFTOPIC_MODEL), its answer cached by video; it never decides a clear case, and when
it cannot be asked the candidate stays (the judge still looks at it).

Counted for the job (stats): what was turned down, by class and stage ("search": before the metadata read,
"metadata": after it, before the storyboard, download and judge), and the cheap model's calls.
"""
from __future__ import annotations

import json
import re
import threading
from typing import Dict, Iterable, List, Optional

from . import config

# --------------------------------------------------------------------------- #
# Hard signs: a title or channel that says what the upload is
# --------------------------------------------------------------------------- #

_GAME = re.compile(
    r"\b(?:minecraft|roblox|fortnite|gta ?(?:v|5|6|iv|online|rp)\b|grand theft auto|call of duty|warzone|valorant|"
    r"league of legends|overwatch|apex legends|pubg|free fire|among us|the sims ?\d?\b|cities:? skylines|"
    r"farming simulator|flight simulator|msfs ?20\d\d|euro truck simulator|american truck simulator|"
    r"beamng(?:\.drive)?|teardown (?:game|mod)|red dead redemption|rdr ?2|garry'?s mod|gmod|half-life|skyrim|"
    r"elden ring|legend of zelda|zelda (?:breath|tears|ocarina)|super mario|mario kart|pok[eé]mon|"
    r"sonic the hedgehog|five nights at freddy'?s|fnaf|poppy playtime|skibidi|terraria|subnautica|stormworks|"
    r"kerbal space program|space engineers|hearts of iron|hoi ?4|age of empires|total war|war thunder|"
    r"world of tanks|world of warships|arma ?3|battlefield (?:\d|v|1942|2042|bad company)|doom eternal|"
    r"hogwarts legacy|cyberpunk 2077|starfield|fallout (?:3|4|76|new vegas)|resident evil|counter[- ]strike|"
    r"cs:?go|dota ?2|world of warcraft|genshin impact|honkai|clash of clans|clash royale|brawl stars|"
    r"geometry dash|rocket league|fifa ?\d\d\b|ea sports fc|madden ?\d\d|nba ?2k\d\d|ark:? survival|dayz|tarkov|"
    r"phasmophobia|lethal company|blox fruits?|haze (?:seas|piece)|bedwars|hypixel|brookhaven|adopt me|"
    r"pet simulator|gameplay|game ?play|let'?s play|lets play|playthrough|speedrun|modded|modpack|"
    # "walkthrough" alone is a house's, an RV's or a museum's too: a game's only with a game word beside it
    r"(?:game|gameplay|full|complete|100%) walkthrough|walkthrough (?:part|pt\.?|ep\.?|episode|chapter|#) ?\d|"
    r"simulator\b[^|]{0,60}\bwalkthrough|"
    r"(?:mod|mods|texture pack|shader pack|seed|fruit|skill|ability|weapon|race|class|item|full) showcase|"
    r"in-game|ingame|esports|e-sports|nintendo switch|steam deck|xbox (?:one|series|360)|playstation ?\d|ps[345]\b|"
    r"game trailer|gameplay trailer|launch trailer|unreal engine ?\d|sim racing|simulator 20\d\d)", re.I)
# A story or a line about games, gaming or the industry - and casinos ("gaming" revenue). (Not "steam" or
# "console": a geyser's steam and a control console are no game.)
_GAME_TOPIC = re.compile(
    r"\b(?:video ?games?|gaming|gamers?|esports|e-sports|game (?:studio|studios|developer|developers|industry|"
    r"console|consoles|company|companies)|minecraft|roblox|fortnite|nintendo|playstation|xbox|speedrun\w*|"
    r"twitch streamers?|casinos?|gambling|call of duty|grand theft auto|pok[eé]mon)\b", re.I)

_KIDS = re.compile(
    r"\b(?:maizen|cocomelon|peppa pig|paw patrol|bluey|blippi|little baby bum|super simple songs|pinkfong|"
    r"baby shark|chuchu ?tv|moonbug|nursery rhymes?|kids songs|songs for kids|cartoons? for kids|kids cartoons?|"
    r"animations? for kids|masha and the bear|ryan'?s world|like nastya|vlad and niki|diana and roma|"
    r"kids diana show|gacha (?:life|club|heat)|supermariologan|aphmau|dantdm|popularmmos|unspeakable(?:gaming)?|"
    r"ssundee|jj and mikey|mikey and jj|(?:minecraft|roblox) animation|animation meme|toys? review|"
    r"learn colou?rs|finger family|peekaboo kidz|dr\.? binocs|tomonews|"
    # Kids' explainers (the Yellowstone build's "Volcanoes for Kids | A fun and engaging introduction...", "Blippi
    # Goes Inside a Volcano! Educational Videos for Kids") - not "vaccine for children" on a health line.
    r"(?:educational videos?|videos?|songs?|cartoons?|lessons?|science|learning|stories) for (?:kids|children|toddlers)|"
    r"^\w+(?: \w+)? for kids)\b", re.I)
_KIDS_TOPIC = re.compile(r"\b(?:children'?s (?:tv|television|show|entertainment|cartoon)|cartoons?|kids'? (?:tv|show|"
                         r"channel|content)|youtube kids|animation (?:studio|industry)|toy (?:industry|company))\b", re.I)

# A studio's or network's own clip channel: scripted shows and films only.
_FICTION_CHANNEL = re.compile(
    r"^(?:paramount network|paramount pictures|paramount\+|paramount plus|movieclips(?: trailers| classic trailers)?|"
    r"rotten tomatoes(?: classic)? trailers|filmselect trailer|fandango(?:nowclips)?|universal pictures|"
    r"warner bros\.? (?:pictures|entertainment)|sony pictures entertainment|20th century studios|lionsgate movies|"
    r"marvel entertainment|pixar|dreamworks(?: animation)?|nickelodeon|cartoon network|adult swim|comedy central|"
    r"saturday night live|a24|focus features|searchlight pictures|walt disney studios|"
    r"netflix (?:is a joke|anime)|amc|amc\+|tbs|tnt|showtime|starz|crunchyroll|funimation|dust|omeleto|alter)$", re.I)
_FICTION = re.compile(
    r"\bofficial (?:clip|trailer|teaser|promo)\b|\b(?:teaser|final|new|red band|international|extended) trailer\b|"
    r"\btrailer ?#\d\b|\btrailer \((?:19|20)\d\d\)|\bmovie clips?\b|\bfilm clip\b|\bmovieclips\b|"
    r"\b(?:best|funniest|deleted|ending|opening|fight|death|kiss|chase) scenes?\b|\bmovie scenes?\b|"
    r"\bscene from (?:the )?(?:movie|film|show|series)\b|\bfull movie\b|"
    r"\bnow streaming\b|\b(?:only )?in theaters\b|\bblu-?ray\b|"
    r"\|\s*(?:paramount network|paramount\+|paramount plus|hbo(?: max)?|hulu|prime video|disney\+|apple tv\+?|"
    r"peacock|amc\+?|fx|showtime|starz|movieclips)\s*(?:\||$)", re.I)
_FICTION_TOPIC = re.compile(
    r"\b(?:(?:tv|television|streaming|drama|hit) (?:show|series|drama|network)|sitcom|miniseries|soap opera|"
    r"box office|hollywood|movie (?:star|studio|franchise|director|premiere|theater|theatre)|"
    r"film (?:studio|industry|director|premiere|festival|franchise)|filmmaker|actor|actress|showrunner|screenplay|"
    r"oscars?|emmys?|golden globes?|the cast of|season \d+ of|episode \d+ of|paramount|netflix|hbo|"
    r"movie|movies|blockbuster|sequel|prequel|spin-?off)\b", re.I)

# Music beyond topics.music_title: auto-generated art tracks, albums, edits of songs.
_MUSIC_MORE = re.compile(
    r"\bfull album\b|\bslowed (?:\+|and|&) reverb\b|\bsped up\b|\bnightcore\b|\b8d audio\b|\bkaraoke\b|"
    r"\(instrumental\)|\btheme song\b|\bopening theme\b|\bintros? on repeat\b|\blo-?fi (?:hip hop|beats|mix)\b|\bofficial (?:lyric|music) video\b", re.I)
_TOPIC_CHANNEL = re.compile(r"\s-\sTopic$", re.I)

_SPORTS = re.compile(
    r"\b(?:extended highlights|match highlights|game highlights|full match|full game replay|"
    r"\bvs\.?\b[^|]{1,60}\bhighlights)\b", re.I)
# (Not "team", "match" or "league" alone: "a team of scientists", "Ivy League".)
_SPORTS_TOPIC = re.compile(
    r"\b(?:football|soccer|nfl|nba|mlb|nhl|fifa|world cup|olympics?|olympians?|tournament|championships?|"
    r"super bowl|playoffs?|athletes?|stadium|sports?|(?:basketball|baseball|hockey|cricket|rugby|tennis|golf) "
    r"(?:team|league|club|match|game|season|player|players|star))\b", re.I)

_TUTORIAL = re.compile(
    r"\bstep[- ]by[- ]step (?:guide|tutorial|instructions)\b|\btutorial\b|"
    r"\bhow to (?:install|set ?up|fix|replace|repair|use|change|enable|disable|turn (?:on|off)|connect|download|"
    r"update|reset|configure)\b|\bunboxing\b|\b(?:change|disable|enable|configure) (?:\w+ ){0,2}settings\b|"
    r"\b(?:disable|enable|turn (?:on|off)|hide|unhide|delete) [^|]{0,30}\bon (?:instagram|facebook|tiktok|youtube|"
    r"whatsapp|snapchat|iphone|android|windows ?\d*|mac|pc|chrome)\b", re.I)
_TUTORIAL_TOPIC = re.compile(r"\b(?:how to|tutorial|guide|diy|repair|install(?:ation|ing)?|gadget|software|apps?|"
                             r"social media|instagram|facebook|tiktok|smartphones?|iphone|android)\b", re.I)

# YouTube's own category, when the full metadata was read.
_GAMING_CATEGORY = "gaming"

# --------------------------------------------------------------------------- #
# Weak signs: asked to the cheap model (ambiguous)
# --------------------------------------------------------------------------- #

_WEAK_CHANNEL = re.compile(
    r"^(?:netflix|hbo|hbo max|max|hulu|prime video|amazon prime video|disney\+?|disney plus|apple tv\+?|peacock|"
    r"fx networks|fx|paramount|cbs|nbc|abc|bbc (?:one|three)|channel 4|itv|sky tv|"
    # late-night talk shows: a real guest's interview, or a sketch - the model is asked
    r"the tonight show starring jimmy fallon|jimmy kimmel live|late night with seth meyers|"
    r"the late show with stephen colbert)$", re.I)
_WEAK = re.compile(
    # "S2 E11", "Season 1, Episode 4": a drama's - or a documentary series' or a workshop show's
    r"\bs\d{1,2} ?e\d{1,2}\b|\bepisode \d{1,3}\b|\bseason \d{1,2}\b|\bpart \d{1,2}\b.*\b(?:animation|animated|cartoon|series)\b|"
    r"\bshowcase\b|\banimat(?:ed|ion)\b|\bcartoon\b|\bstop motion\b|\bsketch\b|\bparody\b|\bspoof\b|\bmeme\b|"
    r"\bshort film\b|\bfan ?made\b|\bcosplay\b", re.I)
# A trailer that is a vehicle (or a home), never a film's: never a weak sign.
_TRAILER = re.compile(r"\btrailers?\b", re.I)
_VEHICLE_TRAILER = re.compile(
    r"\b(?:boat|travel|semi|tractor|car|utility|camper|horse|flatbed|park|mobile home|home|house|truck|hitch|rv|"
    r"cargo|dump|enclosed|fifth wheel|gooseneck|teardrop|van|bus|lorry|crash\w*|accident|collision|jackknif\w*)\b",
    re.I)
_WEAK_CATEGORY = ("entertainment", "film & animation", "comedy")

# --------------------------------------------------------------------------- #

_CLASSES = (
    ("game", "a video game", _GAME, _GAME_TOPIC),
    ("kids", "kids' animation", _KIDS, _KIDS_TOPIC),
    ("fiction", "a TV drama, film or trailer", _FICTION, _FICTION_TOPIC),
    ("sports", "a sports broadcast", _SPORTS, _SPORTS_TOPIC),
    ("tutorial", "a tutorial or screen recording", _TUTORIAL, _TUTORIAL_TOPIC),
)


def enabled() -> bool:
    return bool(getattr(config, "OFFTOPIC_FILTER", True))


def _story(story: Optional[str]) -> str:
    if story is not None:
        return str(story)
    from . import topics
    return topics.story_text()


def _allowed(topic, line: str, story: str) -> bool:
    return bool(topic.search(story or "") or topic.search(line or ""))


def reason(title: str = "", channel: str = "", description: str = "", tags: Iterable[str] = (),
           categories: Iterable[str] = (), line: str = "", story: Optional[str] = None) -> str:
    """
    Why an upload is not footage of the real world for this story and line ("" = it may be): "a video game
    (minecraft)", "a TV drama, film or trailer (| paramount network)", "a music upload (- topic)"... The story or the
    line about that kind of thing lifts its class.

    Read from the title, the channel and YouTube's category only. The description and tags are taken but not read:
    on the replayed metadata (2026-10-09) they turned down real footage and nothing else - stuffed tags ("fortnite"
    on a Nairobi road drive) and a visitor guide's "step by step instructions" (a Norris Geyser Basin walk).
    """
    if not enabled():
        return ""
    s = _story(story)
    text = str(title or "")
    chan = str(channel or "").strip()
    cats = [str(c).strip().lower() for c in (categories or []) if c]
    for name, what, sign, topic in _CLASSES:
        m = sign.search(text) or sign.search(chan)
        hit = m.group(0).strip()[:30] if m else ""
        if not hit and name == "fiction" and _FICTION_CHANNEL.match(chan):
            hit = chan[:30]
        if not hit and name == "game" and _GAMING_CATEGORY in cats:
            hit = "YouTube's Gaming category"
        if hit and not _allowed(topic, line, s):
            return f"{what} ({hit.lower()})"
    # Music: topics.py's own rule (a music video, an audio upload, a rap performance), plus art tracks and edits.
    from . import topics
    if not topics.allows_music(line, s):
        why = topics.music_title(title, channel, list(categories or []))
        if why:
            return why
        m = _MUSIC_MORE.search(str(title or ""))
        if m:
            return f"a music upload ({m.group(0).strip().lower()[:30]})"
        if _TOPIC_CHANNEL.search(chan):
            return "a music upload (an auto-generated topic channel)"
    return ""


def ambiguous(title: str = "", channel: str = "", categories: Iterable[str] = ()) -> bool:
    """A weak sign only (a streaming network's channel, "Episode 4", "| Trailer |", "showcase", "animated", YouTube's
    Entertainment / Film & Animation category): the cheap model is asked (screen)."""
    t = str(title or "")
    if _WEAK.search(t) or _WEAK_CHANNEL.match(str(channel or "").strip()):
        return True
    if _TRAILER.search(t) and not _VEHICLE_TRAILER.search(t):
        return True                     # "| Trailer |" - a film's (a boat or travel trailer is no sign at all)
    return any(str(c).strip().lower() in _WEAK_CATEGORY for c in (categories or []))


# --------------------------------------------------------------------------- #
# The cheap model, for the ambiguous ones
# --------------------------------------------------------------------------- #

_SYSTEM = (
    "You sort YouTube search results for a documentary editor who needs REAL footage - filmed in the real world: "
    "news, documentaries, drone and travel films, eyewitness and phone video, nature, archive film, lectures. For "
    "each numbered result (title and channel only), answer whether it is most likely NOT real-world footage: a "
    "scripted TV drama, sitcom, film, film scene or trailer; a video game, gameplay or game mod; a cartoon, "
    "kids' animation or animated meme; a music track or music video; a streamer's VOD or a reaction video. "
    "The STORY says what the video being made is about: a result about the story's own subject in one of those forms "
    "(the story is about that show, game or band) is fine. When unsure, answer false.\n"
    "Reply with JSON only: {\"results\": [{\"n\": int, \"not_real\": bool, \"kind\": str}]}")
_CACHE: Dict[str, Optional[str]] = {}
_LOCK = threading.Lock()
_STATS: Dict[str, Dict[str, int]] = {}


def reset() -> None:
    with _LOCK:
        _CACHE.clear()
        _STATS.clear()
        _SEEN.clear()


def _bump(group: str, key: str, n: int = 1) -> None:
    with _LOCK:
        box = _STATS.setdefault(group, {})
        box[key] = box.get(key, 0) + n


_SEEN: set = set()


def note(why: str, stage: str, key: str = "") -> None:
    """Count one candidate turned down (by class and by stage) - once per `key` (its video, or its title and
    channel) however many lines' searches return it."""
    if not why:
        return
    if key:
        with _LOCK:
            if (stage, key) in _SEEN:
                return
            if len(_SEEN) > 50000:
                _SEEN.clear()
            _SEEN.add((stage, key))
    kind = why.split(" (")[0]
    _bump("byClass", kind)
    _bump("byStage", stage)


def stats() -> dict:
    """{"turnedDown", "byClass", "byStage", "ai": {"calls", "asked", "flagged"}} for the job result."""
    with _LOCK:
        out = {k: dict(v) for k, v in _STATS.items()}
    out["turnedDown"] = sum((out.get("byStage") or {}).values())
    return out


def _ask_model(rows: List[dict], line: str, story: str) -> Optional[Dict[str, str]]:
    """{video id: kind} for the rows the cheap model calls not real-world footage; None when it cannot answer."""
    from . import aiguard, costs, vision
    model = str(getattr(config, "OFFTOPIC_MODEL", "") or "")
    base = str(config.VISION_API_BASE or "").rstrip("/")
    key = config.VISION_API_KEY
    if not model or not key or "openrouter.ai" not in base or aiguard.stopping():
        return None
    listing = "\n".join(f"{n + 1}. {r.get('title', '')[:140]} | channel: {r.get('channel', '')[:60]}"
                        for n, r in enumerate(rows))
    body = {"model": model, "max_tokens": 60 + 30 * len(rows), "stream": False,
            "response_format": {"type": "json_object"}, "usage": {"include": True},
            "messages": [{"role": "system", "content": _SYSTEM},
                         {"role": "user", "content": f"STORY: {story[:400]}\nLINE: {line[:300]}\nRESULTS:\n{listing}"}]}
    if "gemini-2.5" in model:
        body["reasoning"] = {"max_tokens": 0}
    _bump("ai", "calls")
    _bump("ai", "asked", len(rows))
    try:
        import requests
        r = requests.post(f"{base}/chat/completions", json=body, timeout=30,
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        data = r.json()
    except Exception:  # noqa: BLE001 - unknown: the candidates stay, the judge decides
        return None
    usage = data.get("usage") if isinstance(data, dict) else None
    try:
        usd = float((usage or {}).get("cost") or 0.0)
        if usd > 0:
            costs.record("llm.usd", usd)
            costs.record("llm.offtopic.usd", usd)
        costs.record("llm.offtopic.calls")
    except (TypeError, ValueError):
        pass
    err = data.get("error") if isinstance(data, dict) else None
    status = getattr(r, "status_code", 200)
    status = status if isinstance(status, int) and not isinstance(status, bool) else 200
    if err or status >= 400:
        code, msg = status, ""
        if isinstance(err, dict):
            msg = str(err.get("message") or "")
            try:
                code = int(err.get("code") or status)
            except (TypeError, ValueError):
                code = status
        elif err:
            msg = str(err)
        if aiguard.classify(code, msg) == aiguard.CREDIT:
            vision.note_out_of_credits(model, msg)          # the account is dry: the job stops (aiguard)
        return None
    try:
        text = data["choices"][0]["message"]["content"]
        got = vision._loads_lenient(vision._first_object(text if isinstance(text, str) else json.dumps(text)))
        out = {}
        for item in (got or {}).get("results") or []:
            n = int(item.get("n")) - 1
            if 0 <= n < len(rows) and vision._truthy(item.get("not_real")):
                out[str(rows[n].get("id") or "")] = str(item.get("kind") or "not real-world footage")[:40]
        return out
    except Exception:  # noqa: BLE001
        return None


def screen(rows: List[dict], line: str = "", story: Optional[str] = None, limit: int = 12) -> set:
    """
    The ids among `rows` (search results: id, title, channel) the cheap model calls not real-world footage - asked
    only for the ambiguous ones not cached yet (at most `limit` a call, one call per search), answers cached by
    video for the job. OFFTOPIC_AI off, no OpenRouter key, or no answer: nothing is turned down this way.
    """
    if not enabled() or not getattr(config, "OFFTOPIC_AI", True):
        return set()
    s = _story(story)
    out = set()
    todo = []
    with _LOCK:
        for r in rows:
            vid = str(r.get("id") or "")
            if not vid:
                continue
            if vid in _CACHE:
                if _CACHE[vid]:
                    out.add(vid)
                continue
            if ambiguous(r.get("title", ""), r.get("channel", "")):
                todo.append(r)
    todo = todo[:max(1, int(limit))]
    if not todo:
        return out
    got = _ask_model(todo, line, s)
    if got is None:
        return out
    with _LOCK:
        for r in todo:
            vid = str(r.get("id") or "")
            _CACHE[vid] = got.get(vid) or ""
    for vid, kind in got.items():
        out.add(vid)
        _bump("ai", "flagged")
        note(f"{kind or 'not real-world footage'} (the cheap model)", "search", key=vid)
    return out
