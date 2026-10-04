"""
Vision verification: look at a sourced clip and decide whether it shows the beat.

Everything upstream of this judges a candidate by its *title*. A title is what
the uploader wanted you to click, not what is in the frames — which is how a
Premiere Pro screen recording titled "Epic TRAILER TEXT Animation" landed in a
documentary. Reading VidRush's own timeline shows how they avoid it: every clip
carries a `contentDescription` written by a vision model after the download, a
`relevanceScore` comparing that description with what the shot was supposed to
show, and nothing on the timeline scores below 0.70. This is that step.

One call per candidate, three frames per call. The model returns what it
actually sees, a 0-1 relevance score against the intent, and a hard flag for
other people's text or watermarks (channel bugs, news tickers, burned-in
subtitles, stock watermarks) — which the pixel heuristics in media.py only
partly catch.

Verdicts are cached by file content, so re-sourcing a scene never pays twice
for the same candidate.
"""
import base64
import hashlib
import json
import os
import re
import subprocess
import threading
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Dict, List, Optional, Tuple

import requests

from . import config, costs, events, intent as scene_intent

_CACHE: Dict[str, dict] = {}
_LOCK = threading.Lock()
_CALLS = {"n": 0}
# Why recent model calls failed. A failed call returns None and the clip is
# kept unjudged, which is invisible in the timeline; the worker reports these
# so a broken key or model shows up in the job result instead of as bad clips.
_ERRORS: deque = deque(maxlen=8)
_FAILS = {"n": 0}
# Candidates no model could judge at all (all attempts failed, or no frames):
# kept unscored, so the job result reports how many reached the timeline that way.
_UNJUDGED = {"n": 0}

_SYSTEM = (
    "You check whether a video clip or photo is usable B-roll for one line of a "
    "documentary narration. You are shown frames from the candidate. Describe "
    "literally what is visible, then score how well it fits the INTENT.\n"
    "First check every NAMED thing in the INTENT - a person, a place, a year or era. "
    "These are hard limits, not preferences:\n"
    "- A named PERSON: above 0.7 only if the frames plausibly show THAT person (a "
    "recognisable public figure, or a period photo consistent with who they are). "
    "A different person, an anonymous stand-in, a stock model, a wedding or family "
    "photo of strangers: at most 0.3.\n"
    "- A named PLACE: footage recognisably from somewhere else (another city, country, "
    "landscape or architecture - Berlin for a line about Honolulu): at most 0.3.\n"
    "- A YEAR or ERA: footage clearly from another era (1940s film for a 1970s line, "
    "modern HD streets, cars or phones for a line about the past): at most 0.4.\n"
    "Then: 0.9-1.0 clearly shows the intended subject; 0.7-0.89 consistent with every "
    "named person, place and era and shows what the line is about; 0.4-0.69 loosely "
    "related; below 0.4 wrong. Never reward mood alone.\n"
    "- AI-GENERATED or fake: an AI image or AI video (over-smooth skin, glossy "
    "uncanny faces, warped hands or text, impossible architecture, a 'historical' "
    "scene rendered like a video game or a painting) shown as a real person, place, "
    "event or era: at most 0.2 - a documentary shows the real thing. A Hollywood "
    "movie scene, a TV show, stock actors posing and music videos: at most 0.3. "
    "But an era-accurate documentary reconstruction of an unfilmed private moment "
    "(a 1970s bedroom, hands typing a 1960s file) is fine when the INTENT asks for "
    "reconstruction footage and no face is presented as the named person.\n"
    "Score 0 and set has_text_or_watermark true for ANY stock-library or channel "
    "watermark or logo bug (ZapataStock, FootageForPro, Pond5, Storyblocks, Getty, a "
    "channel logo in a corner), a lyric video, "
    "glitch art or corrupted/blocky frames, or a screen "
    "recording, software UI, a video game, a news desk or presenter talking to "
    "camera, a thumbnail/title card, burned-in subtitles, a channel logo, a "
    "stock-photo watermark, a product listing or poster for sale, a website "
    "screenshot, or a meme or collage with text. Look closely for a stock agency's "
    "mark even when faint: its name (alamy, gettyimages, iStock, shutterstock, "
    "dreamstime, depositphotos, Adobe Stock, 123RF) or logo stamped once or "
    "repeated across the picture, a translucent box with the agency's name and a "
    "photographer credit, the agency's image ID or web address along an edge "
    "(\"Image ID: 2J7W6N8 www.alamy.com\"), or the agency's credit bar under the "
    "picture - each of these sets has_text_or_watermark true. Not an agency's mark: "
    "a caption, date, catalogue number or library stamp on an archive print, or a "
    "photographer's or newspaper's credit that names no agency. Small incidental "
    "real-world text (a street sign) is fine.\n"
    "STORY is the whole video's subject. A shot that contradicts it (another "
    "person, another event, another era) is wrong even if it fits the line's "
    "words. For an abstract line (a feeling, a decision, a record), era-accurate "
    "footage of the ACTION in the story's setting - hands on a typewriter for a "
    "1960s file, airmail letters for letters, an archive box for a record - is "
    "what a documentary editor uses: 0.7-0.85. Modern generic stock for a "
    "historical story: at most 0.4.\n"
    "Separately rate quality 0-1 as documentary footage, whatever the subject: sharp, "
    "stable, well lit, well composed, filling a 16:9 frame, with motion or visual "
    "interest is high; blurry, blocky compression, shaky, very dark, a vertical phone "
    "video with bars or blur down the sides, or a flat uninteresting frame is low.\n"
    "When the prompt lists ENTITIES or LOCATIONS, say in the description which of "
    "them the frames show, and class the frames: specificity \"event\" when they are "
    "recognisably the named event at the named place, \"location\" when they show the "
    "named place but not that event, \"generic\" otherwise.\n"
    "Answer two more questions, each a hard reject when true:\n"
    "- ai_generated: do the frames look AI-generated or artificial - an AI image or AI "
    "video, CGI or a 3D render, a digital painting, an oil-painting, watercolour or "
    "illustration style, a video game, uncanny waxy faces, warped hands or text, "
    "impossible detail, glossy painterly lighting, or a slideshow of such pictures? "
    "Real photographs and real camera footage are false.\n"
    "- studio: is it NOT real field footage of the subject - a TV studio, a weather "
    "presenter or meteorologist in front of a map or radar wall, a news anchor at a "
    "desk, a YouTuber, streamer or vlogger talking to camera (a face cam, a split screen "
    "with a talking person, a subscribe button or bell icon, a QR code, a chat overlay), "
    "another creator's big word-by-word captions, or a TV weather map or forecast "
    "graphic? A reporter or official interviewed on location, a press conference, and "
    "field video carrying a small news banner are false.\n"
    "Keep the description to one plain sentence of at most 25 words.\n"
    "Reply with one valid JSON object only. Do not wrap it in JSON.stringify(), "
    "JavaScript, markdown, or commentary: {\"description\": str, \"score\": number, \"quality\": number, "
    "\"has_text_or_watermark\": bool, \"is_talking_head\": bool, \"ai_generated\": bool, \"studio\": bool, "
    "\"specificity\": \"event\"|\"location\"|\"generic\"}"
)

# News footage the GoMotion way (config.NEWS_FOOTAGE): the same judge, with the
# text/logo rule swapped for one that welcomes TV-news footage as it is.
_STRICT_TEXT_RULE = (
    "Score 0 and set has_text_or_watermark true for ANY stock-library or channel "
    "watermark or logo bug (ZapataStock, FootageForPro, Pond5, Storyblocks, Getty, a "
    "channel logo in a corner), a lyric video, "
    "glitch art or corrupted/blocky frames, or a screen "
    "recording, software UI, a video game, a news desk or presenter talking to "
    "camera, a thumbnail/title card, burned-in subtitles, a channel logo, a "
    "stock-photo watermark, a product listing or poster for sale, a website "
    "screenshot, or a meme or collage with text. Look closely for a stock agency's "
    "mark even when faint: its name (alamy, gettyimages, iStock, shutterstock, "
    "dreamstime, depositphotos, Adobe Stock, 123RF) or logo stamped once or "
    "repeated across the picture, a translucent box with the agency's name and a "
    "photographer credit, the agency's image ID or web address along an edge "
    "(\"Image ID: 2J7W6N8 www.alamy.com\"), or the agency's credit bar under the "
    "picture - each of these sets has_text_or_watermark true. Not an agency's mark: "
    "a caption, date, catalogue number or library stamp on an archive print, or a "
    "photographer's or newspaper's credit that names no agency. Small incidental "
    "real-world text (a street sign) is fine.\n")
_STAMP_RULE = (
    " A stock agency's mark counts even when faint: its name (alamy, gettyimages, iStock, "
    "shutterstock, dreamstime, depositphotos, Adobe Stock, 123RF) or logo stamped once or "
    "repeated across the picture, a translucent box with the agency's name and a photographer "
    "credit, the agency's image ID or web address along an edge (\"Image ID: 2J7W6N8 "
    "www.alamy.com\"), or the agency's credit bar under the picture. Not an agency's mark: a "
    "caption, date, catalogue number or library stamp on an archive print, or a photographer's "
    "or newspaper's credit that names no agency.")
_NEWS_TEXT_RULE = (
    "TV NEWS FOOTAGE IS WELCOME: field video, aerials, interviews and press "
    "conferences from a news report are exactly what this documentary uses, WITH "
    "their station logo, headline banner, lower-third name, ticker or subtitles - do "
    "not flag those and do not lower the score for them. The studio itself is NOT "
    "welcome: a weather presenter at a map or radar wall, an anchor desk, a TV "
    "forecast graphic, and a YouTuber's or streamer's screen with their big captions "
    "(answer studio true). Score 0 and set "
    "has_text_or_watermark true only for a stock-library watermark (ZapataStock, "
    "FootageForPro, Pond5, Storyblocks, Getty, Shutterstock), a lyric video, glitch "
    "art or corrupted/blocky frames, a screen recording, software UI, a video game, a "
    "news anchor at a studio desk, a thumbnail/title card, an advertisement (a QR "
    "code, a website or phone number to visit, a product offer), a product listing or "
    "poster for sale, a website screenshot, or a meme or collage with text." + _STAMP_RULE + " Small "
    "incidental real-world text (a street sign) is fine.\n")


def _system() -> str:
    if config.NEWS_FOOTAGE:
        return _SYSTEM.replace(_STRICT_TEXT_RULE, _NEWS_TEXT_RULE)
    return _SYSTEM


_NEWS_TILE_RULE = (" A news report's station logo, headline banner or ticker over otherwise "
                   "real footage of the subject is fine - choose it like any other shot.")


# Added for a beat of a news, weather or disaster story. Without it "clearly fits
# the topic ... even if not the exact subject" scored any flooded street 0.7+ for
# a line about one particular flood, which is how random footage passed.
_EVENT_RULE = (
    "\nTHIS LINE IS ABOUT ONE SPECIFIC REAL EVENT at a real place, named in the "
    "INTENT. Footage of the same kind of thing somewhere else is the wrong shot. "
    "Score instead: 0.9-1.0 recognisably that event or place (matching landmarks, "
    "signage, terrain, river, architecture); 0.7-0.89 consistent with that place and "
    "event with nothing contradicting it; below 0.7 generic or stock-looking footage, "
    "or anything from another country, climate, season or era than the one named. "
    "A news outlet's aerial or on-the-ground footage of the event is ideal; the news "
    "desk or a reporter talking to camera is still a talking head.\n"
    "READ EVERY BANNER, CHYRON, CAPTION, TITLE CARD, DATE AND SIGN in the frames. One "
    "that names a DIFFERENT city, county, state or country than the INTENT's and the "
    "STORY's places (\"RUIDOSO, NM\" for a Texas story), another storm's or event's "
    "name, another year, or another kind of weather (snow and ice for a flood) means "
    "the wrong shot: score at most 0.3 and say so in the description."
)


# Kie shares one balance across vision, the director and image generation.
# When it answers "402 Credits insufficient" every later call fails the same
# way: a 362-scene job made 2,631 failed calls after its balance ran out.
_OUT_OF_CREDITS = {"hit": False}


def is_credit_error(code, msg: str = "") -> bool:
    return code == 402 or "credits insufficient" in str(msg or "").lower()


def note_out_of_credits() -> None:
    with _LOCK:
        _OUT_OF_CREDITS["hit"] = True


def out_of_credits() -> bool:
    return _OUT_OF_CREDITS["hit"]


OUT_OF_CREDITS_MESSAGE = (
    "The AI account (Kie) is out of credits, so shots could not be planned or "
    "checked and the video would be random clips. Top up the Kie account whose "
    "key is set on the RunPod endpoint (DIRECTOR_API_KEY), then run it again.")


class OutOfCredits(RuntimeError):
    """The AI account ran dry and REQUIRE_AI is on: stop the job, say why."""


def require_credits() -> None:
    if config.REQUIRE_AI and ai_exhausted():
        raise OutOfCredits(OUT_OF_CREDITS_MESSAGE)


def fallback_configured() -> bool:
    return bool(config.AI_FALLBACK_API_BASE and config.AI_FALLBACK_API_KEY
                and config.AI_FALLBACK_VISION_MODEL)


def ai_exhausted() -> bool:
    """The main AI account is out of credits and there is no backup provider."""
    return _OUT_OF_CREDITS["hit"] and not fallback_configured()


def enabled() -> bool:
    main = bool(config.VISION_API_KEY) and not _OUT_OF_CREDITS["hit"]
    return bool(config.VISION_ENABLED and (main or fallback_configured()))


def calls_made() -> int:
    return _CALLS["n"]


def reset() -> None:
    with _LOCK:
        _MODEL_FAILS.clear()
        _MODEL_DOWN_UNTIL.clear()
        _CACHE.clear()
        _CALLS["n"] = 0
        _FAILS["n"] = 0
        _UNJUDGED["n"] = 0
        _OUT_OF_CREDITS["hit"] = False
        _ERRORS.clear()


def _fail(model: str, why: str) -> None:
    with _LOCK:
        _FAILS["n"] += 1
        _ERRORS.append(f"{model}: {why}"[:240])
    events.emit("vision", "model_failed", level="warning", provider=model or "vision",
                failure="AI_API_FAILURE", message=why)


def stats() -> dict:
    """Calls, failures and the latest failure reasons, for the job result."""
    with _LOCK:
        return {"enabled": enabled(), "model": config.VISION_MODEL,
                "calls": _CALLS["n"], "failures": _FAILS["n"],
                "unjudged": _UNJUDGED["n"],
                "outOfCredits": _OUT_OF_CREDITS["hit"],
                "recentErrors": list(_ERRORS)}


# At most VISION_CONCURRENCY requests in flight per worker (see config), and
# never more than VISION_KIE_MAX_CONCURRENCY against Kie.
_SLOTS = threading.BoundedSemaphore(max(1, min(config.VISION_CONCURRENCY, config.VISION_KIE_MAX_CONCURRENCY)
                                             if "kie.ai" in (config.VISION_API_BASE or "")
                                             else config.VISION_CONCURRENCY))


def _ask_once(model: str, messages: list, max_tokens: int, url: str = "",
              key: str = "", main: bool = True) -> Tuple[Optional[str], bool]:
    """(text, retryable): one call to one model; retryable when the failure was transient."""
    with _SLOTS:
        return _ask_once_slot(model, messages, max_tokens, url, key, main)


def _extra(model: str, url: str, max_tokens: int) -> tuple:
    """
    (max_tokens, extra fields) for one model. Google's Gemini flash models think
    before answering and the thinking comes out of max_tokens: a 400-token
    verdict came back cut off ("finish_reason": "length") until reasoning was
    set to "none" (3 s, complete JSON; measured 2026-09-29). They also get
    double the room as a margin. gpt-* keep VISION_REASONING_EFFORT.
    """
    if model.startswith("gemini-") and "googleapis.com" in url:
        extra = {"reasoning_effort": config.VISION_GEMINI_REASONING} if config.VISION_GEMINI_REASONING else {}
        return max_tokens * 2, extra
    if "openrouter.ai" in url:
        # OpenRouter's own reasoning switch (measured 2026-10-01, 3 frames a check):
        # gemini-2.5-flash with no thinking 2.3 s; gemini-3.x flash cannot turn it
        # off (400 on "none") and thinks ~230 tokens at "minimal", 7 s; gpt-5-mini
        # at "minimal" 3.1 s.
        if "gemini-2.5" in model:
            return max_tokens, {"reasoning": {"max_tokens": 0}}
        if "gemini" in model:
            return max_tokens * 2, {"reasoning": {"effort": "minimal"}}
        if "/gpt-5" in model:
            return max_tokens, {"reasoning": {"effort": "minimal"}}
        return max_tokens, {}
    if config.VISION_REASONING_EFFORT and model.startswith("gpt-"):
        return max_tokens, {"reasoning_effort": config.VISION_REASONING_EFFORT}
    return max_tokens, {}


def _cached(model: str, url: str, messages: list) -> list:
    """
    The fixed system instructions as a cached block, on OpenRouter for the
    models that take a cache breakpoint (Gemini, Claude). Measured on
    gemini-2.5-flash (2026-10-01): 1,502 of a clip check's ~2,400 prompt
    tokens came back from the cache at a quarter of the price, $0.00110 ->
    $0.00066-0.00071 a check. Nothing else changes: the same text, the same
    verdict. Gemini caches only blocks of 1,024+ tokens, so the short tile
    prompts simply go uncached.
    """
    if not config.VISION_PROMPT_CACHE or "openrouter.ai" not in (url or ""):
        return messages
    if not model.startswith(("google/", "anthropic/")):
        return messages
    if not messages or messages[0].get("role") != "system" or not isinstance(messages[0].get("content"), str):
        return messages
    first = dict(messages[0], content=[{"type": "text", "text": messages[0]["content"],
                                        "cache_control": {"type": "ephemeral"}}])
    return [first] + list(messages[1:])


def _note_usage(body) -> None:
    """What a call really cost and used, when the provider says (OpenRouter's usage.cost):
    vision.usd, vision.prompt_tokens, vision.cached_tokens, vision.completion_tokens."""
    usage = body.get("usage") if isinstance(body, dict) else None
    if not isinstance(usage, dict):
        return
    try:
        usd = float(usage.get("cost") or 0.0)
        details = usage.get("prompt_tokens_details") or {}
        counts = {"vision.prompt_tokens": int(usage.get("prompt_tokens") or 0),
                  "vision.cached_tokens": int(details.get("cached_tokens") or 0) if isinstance(details, dict) else 0,
                  "vision.completion_tokens": int(usage.get("completion_tokens") or 0)}
    except (TypeError, ValueError):
        return
    if usd > 0:
        costs.record("vision.usd", usd)
    for k, n in counts.items():
        if n:
            costs.record(k, n)


def _ask_once_slot(model: str, messages: list, max_tokens: int, url: str,
                   key: str, main: bool) -> Tuple[Optional[str], bool]:
    target = url or _endpoint(model)
    budget, extra = _extra(model, target, max_tokens)
    if "openrouter.ai" in target:
        extra = dict(extra, usage={"include": True})     # the call's real price, for the cost ledger
    try:
        r = requests.post(
            target,
            headers={"Authorization": f"Bearer {key or config.VISION_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": model, "messages": _cached(model, target, messages),
                  "max_tokens": budget, "stream": False, **extra},
            timeout=config.VISION_TIMEOUT)
    except requests.RequestException as e:
        _fail(model, f"request failed: {type(e).__name__}")
        return None, True
    try:
        body = r.json()
    except ValueError:
        _fail(model, f"HTTP {r.status_code}, not JSON: {r.text[:120]!r}")
        return None, r.status_code >= 500 or r.status_code == 429
    _note_usage(body)
    # Kie wraps failures in a 200: {"code": 422, "msg": ...}.
    if isinstance(body, dict) and isinstance(body.get("code"), int) and body["code"] >= 400:
        _fail(model, f"code {body['code']}: {str(body.get('msg') or '')[:150]}")
        if is_credit_error(body["code"], body.get("msg")):
            if main:
                note_out_of_credits()
            return None, False
        return None, body["code"] >= 500 or body["code"] == 429
    try:
        text = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        _fail(model, f"HTTP {r.status_code}, no choices: {json.dumps(body)[:150]}")
        return None, r.status_code >= 500
    if isinstance(text, list):
        text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    if not (text or "").strip():
        # Reasoning models can spend max_tokens thinking and return nothing.
        _fail(model, "empty answer")
        return None, False
    low = text.strip().lower()
    if not low.startswith(("{", "[", "```")) and "limit" in low and "try again" in low:
        # Kie's gpt-5-2 under load: "You've hit your attachment limit. Please try
        # again later." A rate limit, not a verdict - the next model is asked.
        _fail(model, f"rate limited: {text.strip()[:80]}")
        return None, True
    return text, False


# Circuit breaker shared with the director. On 2026-09-26 Kie's Gemini
# channels answered every call with "internal error" after ~35 s; each vision
# check waited out two of those before falling back to gpt-5-2, and a 23-scene
# job crawled at one scene a minute. Two consecutive failed calls now take a
# model out of rotation for config.VISION_MODEL_COOLDOWN_SECONDS.
_MODEL_FAILS: Dict[str, int] = {}
_MODEL_DOWN_UNTIL: Dict[str, float] = {}


def model_available(model: str) -> bool:
    import time as _t
    with _LOCK:
        return _MODEL_DOWN_UNTIL.get(model, 0) <= _t.time()


def model_result(model: str, ok: bool) -> None:
    """Record one call; the second failure in a row benches the model."""
    import time as _t
    with _LOCK:
        if ok:
            _MODEL_FAILS[model] = 0
            return
        _MODEL_FAILS[model] = _MODEL_FAILS.get(model, 0) + 1
        if _MODEL_FAILS[model] >= 2:
            cooldown = config.VISION_MODEL_COOLDOWN_SECONDS
            _MODEL_DOWN_UNTIL[model] = _t.time() + cooldown
            _MODEL_FAILS[model] = 0
            print(f"[ai] {model} failing - skipped for {cooldown:.0f} s", flush=True)


def _routes() -> list:
    routes = [(m, "", "", True) for m in [config.VISION_MODEL] + list(config.VISION_FALLBACK_MODELS)
              if m and config.VISION_API_KEY]
    if fallback_configured():
        routes.append((config.AI_FALLBACK_VISION_MODEL,
                       f"{config.AI_FALLBACK_API_BASE}/chat/completions",
                       config.AI_FALLBACK_API_KEY, False))
    return routes


def _route_call(route: tuple, messages: list, max_tokens: int, deadline: float) -> Optional[str]:
    """
    One model, retried with a doubling pause on a transient failure while the
    call's budget lasts. The circuit breaker counts the call once, when every
    try failed: counting each try benched a model on its first 503 burst.
    """
    model, url, key, main = route
    failed = False
    for attempt in range(1 + config.VISION_RETRIES):
        if attempt:
            wait = config.VISION_RETRY_WAIT * (2 ** (attempt - 1))
            if time.time() + wait >= deadline or not model_available(model):
                break
            time.sleep(wait)
        if main and _OUT_OF_CREDITS["hit"]:
            break
        text, retryable = _ask_once(model, messages, max_tokens, url, key, main)
        if text:
            model_result(model, True)
            return text
        failed = retryable
        if not retryable:
            break
    if failed:
        model_result(model, False)
    return None


# Hedged requests run here; abandoned ones finish in the background.
_HEDGE_POOL = ThreadPoolExecutor(max_workers=64, thread_name_prefix="vision")


def _ask(messages: list, max_tokens: int, accept=None) -> Tuple[Optional[str], str]:
    """
    First model that answers: (text, model). (None, "") when none did.

    `accept`: an answer it rejects (a judge verdict that is prose, not JSON)
    counts as that model failing, and the next model is asked - an unusable
    answer used to end the call and leave the clip unjudged.

    A transient failure (timeout, HTTP/Kie 5xx, 429) is retried once on the
    same model. Kie's gpt-5-2 answers "code 500: Server exception, please try
    again later" in bursts - 116 of 609 calls on one real job - and moving
    straight on meant a burst on the fallback too left clips on the timeline
    that no model had ever looked at.

    Hedged: when the first model has not answered after VISION_HEDGE_SECONDS,
    the next one is asked in parallel and the first answer wins; a model that
    fails hands over at once; the call ends after VISION_CALL_BUDGET_SECONDS.
    On the 111-line job 16c80a8b a stalled channel cost the full 90 s timeout
    twice per model before the next was tried, and the worker sat idle.
    """
    queue = [r for r in _routes()
             if not (r[3] and _OUT_OF_CREDITS["hit"]) and model_available(r[0])]
    if not queue:
        return None, ""
    started = time.time()
    deadline = started + max(1.0, config.VISION_CALL_BUDGET_SECONDS)
    hedge = config.VISION_HEDGE_SECONDS * (1.6 if max_tokens > 600 else 1.0)
    if hedge <= 0:
        for route in queue:
            if time.time() >= deadline:
                break
            text = _route_call(route, messages, max_tokens, deadline)
            if text and (accept is None or accept(text)):
                return text, route[0]
            if text:
                _fail(route[0], f"unusable answer: {text[:120]!r}")
        return None, ""
    running: Dict = {}
    nxt = 0

    def launch(backup: bool) -> None:
        nonlocal nxt
        route = queue[nxt]
        nxt += 1
        if backup:
            costs.record("vision.hedge")
        running[_HEDGE_POOL.submit(_route_call, route, messages, max_tokens, deadline)] = route

    launch(False)
    while running:
        left = deadline - time.time()
        if left <= 0:
            break
        # Wait for an answer, but no longer than the next hedge point.
        until_hedge = (started + hedge * nxt) - time.time() if nxt < len(queue) else left
        done, _ = wait(list(running), timeout=max(0.05, min(left, until_hedge)),
                       return_when=FIRST_COMPLETED)
        for fut in done:
            route = running.pop(fut)
            try:
                text = fut.result()
            except Exception:  # noqa: BLE001 - a crashed route is a failed one
                text = None
            if text and (accept is None or accept(text)):
                return text, route[0]
            if text:
                _fail(route[0], f"unusable answer: {text[:120]!r}")
        if nxt < len(queue) and (not running or time.time() >= started + hedge * nxt):
            launch(bool(running))
    return None, ""


def probe() -> dict:
    """One tiny real call, for the health action: is vision reachable here?"""
    if not enabled():
        return {"ok": False, "error": "no VISION_API_KEY / DIRECTOR_API_KEY"}
    try:
        import io as _io
        from PIL import Image
        buf = _io.BytesIO()
        Image.new("RGB", (160, 90), (40, 110, 200)).save(buf, "JPEG")
        img = base64.b64encode(buf.getvalue()).decode()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"could not build test image: {e}"}
    t = time.time()
    text, model = _ask([{"role": "user", "content": [
        {"type": "text", "text": 'What colour is this image? Reply JSON {"colour": str}'},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}}]}], 400)
    out = {"ok": bool(text), "model": model, "seconds": round(time.time() - t, 1),
           "answer": (text or "")[:80]}
    if not text:
        out["recentErrors"] = list(_ERRORS)
    return out


def _fingerprint(path: str) -> str:
    """
    The file's content: its size, first and last 64 KB. Not its modification
    time - a candidate downloaded again (another scene, another search) is the
    same picture and must not pay for a second verdict; the Lake Powell job
    fetched one Dailymotion section at least four times (2026-10-01).
    """
    h = hashlib.sha1()
    try:
        size = os.path.getsize(path)
        h.update(str(size).encode())
        with open(path, "rb") as fh:
            h.update(fh.read(1 << 16))
            if size > 2 << 16:
                fh.seek(size - (1 << 16))
                h.update(fh.read(1 << 16))
    except OSError:
        h.update(path.encode())
    return h.hexdigest()


_STILL_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def judge_width(path: str) -> int:
    """The width the judge sees a candidate at (config.VISION_STILL_WIDTH for a photo)."""
    still = os.path.splitext(path or "")[1].lower() in _STILL_EXT
    return config.VISION_STILL_WIDTH if still else config.VISION_FRAME_WIDTH


# Frames of recent candidates: the local CLIP check and the remote judge look
# at the same frames, and each ffmpeg seek costs ~0.2 s.
_FRAMES_CACHE: dict = {}


def sample_frames(path: str, count: int = 3, width: int = 512) -> List[str]:
    """`count` evenly spaced JPEG frames as base64 strings. [] when unreadable."""
    key = (_fingerprint(path), count, width)
    with _LOCK:
        hit = _FRAMES_CACHE.get(key)
    if hit is not None:
        return list(hit)
    frames = _sample_frames(path, count, width)
    if frames:
        with _LOCK:
            if len(_FRAMES_CACHE) > 96:
                _FRAMES_CACHE.pop(next(iter(_FRAMES_CACHE)))
            _FRAMES_CACHE[key] = list(frames)
    return frames


def _sample_frames(path: str, count: int = 3, width: int = 512) -> List[str]:
    ext = os.path.splitext(path)[1].lower()
    if ext in {".jpg", ".jpeg", ".png", ".webp"}:
        # A still: one downscaled copy is enough.
        cmd = ["ffmpeg", "-v", "error", "-i", path, "-vf", f"scale={width}:-2",
               "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "-"]
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=60)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []
        return [base64.b64encode(p.stdout).decode()] if p.stdout else []

    dur = _duration(path)
    if not dur:
        return []
    frames = []
    for frac in [(i + 1) / (count + 1) for i in range(count)]:
        cmd = ["ffmpeg", "-v", "error", "-ss", f"{dur * frac:.2f}", "-i", path,
               "-frames:v", "1", "-vf", f"scale={width}:-2",
               "-f", "image2pipe", "-vcodec", "mjpeg", "-"]
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=60)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
        if p.stdout:
            frames.append(base64.b64encode(p.stdout).decode())
    return frames


def _duration(path: str) -> float:
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30)
        return float((p.stdout or "0").strip() or 0)
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        return 0.0


def _endpoint(model: str) -> str:
    base = config.VISION_API_BASE.rstrip("/")
    # Kie routes each model on its own path: /{model}/v1/chat/completions.
    if "kie.ai" in base:
        return f"https://api.kie.ai/{model}/v1/chat/completions"
    return f"{base}/chat/completions"


def _parse(text: str) -> Optional[dict]:
    text = re.sub(r"^\s*```(?:json)?|```\s*$", "", text or "").strip()
    # Some OpenAI-compatible gateways occasionally return a JS expression such
    # as JSON.stringify({description: "..."}) despite the JSON-only instruction.
    # Extract the first complete object, then accept its common JS object-literal
    # form without weakening the required fields or score validation.
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    quote = ""
    escaped = False
    end = -1
    for i in range(start, len(text)):
        ch = text[i]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        return None
    raw = text[start:end]
    try:
        data = json.loads(raw)
    except ValueError:
        # Quote unquoted object keys (the usual JSON.stringify({key: value})
        # slip), and remove trailing commas. Restrict the key match to object
        # separators so colons in description strings are left untouched.
        repaired = re.sub(r'([{,]\s*)([A-Za-z_$][\w$]*)(\s*:)', r'\1"\2"\3', raw)
        repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
        try:
            data = json.loads(repaired)
        except ValueError:
            return None
    if not isinstance(data, dict):
        return None
    try:
        score = float(data.get("score", 0))
    except (TypeError, ValueError):
        score = 0.0
    try:
        quality = max(0.0, min(1.0, float(data["quality"])))
    except (KeyError, TypeError, ValueError):
        quality = None      # not rated: unknown, never a reason to reject
    return {
        "description": str(data.get("description") or "")[:600],
        "score": max(0.0, min(1.0, score)),
        "quality": quality,
        "has_text_or_watermark": bool(data.get("has_text_or_watermark")),
        "is_talking_head": bool(data.get("is_talking_head")),
        # The AI-slop and not-footage questions (src/slop.py layer 4): a hard
        # reject each (acceptable). A string "false" is false.
        "ai_generated": _truthy(data.get("ai_generated")),
        "studio": _truthy(data.get("studio")),
        "specificity": (data.get("specificity")
                        if data.get("specificity") in scene_intent.SPECIFICITY else ""),
    }


def _truthy(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1")
    return bool(value)


# One line describing the whole video (who, what, when, where), set once per
# job from the director's story brief and shown with every judgement.
_STORY = {"line": ""}


def set_story(brief: Optional[dict]) -> None:
    """Give the judge the whole-story brief; None or {} clears it."""
    b = brief or {}
    cast = [c.get("name") for c in (b.get("cast") or []) if c.get("name")]
    people = cast or list(b.get("people") or [])
    parts = [b.get("summary") or b.get("event") or "",
             f"people: {', '.join(people[:5])}" if people else "",
             f"places: {', '.join((b.get('places') or [])[:4])}" if b.get("places") else "",
             f"year: {b.get('year')}" if b.get("year") else "",
             f"kind: {b.get('kind')}" if b.get("kind") else ""]
    _STORY["line"] = " | ".join(p for p in parts if p)[:500]


def _scene_lines(scene: Optional[dict]) -> str:
    return scene_intent.SceneIntent.from_dict(scene).vision_lines() if scene else ""


def _wanted_line(wants: str) -> str:
    """The line under INTENT for a line whose wanted shots include a map ("map") or a chart,
    diagram or cross-section ("chart"): a real published one is acceptable - the instructions'
    text, studio and AI rules would read a drawn picture's labels, legend and style as faults.
    Real footage or a photo that fits stays just as good: the INTENT decides."""
    if wants not in ("map", "chart"):
        return ""
    what = "a map" if wants == "map" else "a chart, a diagram or a cross-section"
    return (f"WANTED: the line's wanted shots include {what}. A real published one of what the line is about - a "
            "government agency's, a scientist's or a news report's - is acceptable: its drawn style, its labels and "
            "its legend do not make it ai_generated, studio or has_text_or_watermark. Real footage or a photograph "
            "that fits the INTENT is just as good; score how well the candidate shows what the INTENT describes. "
            "Still hard rejects: a TV weather map or forecast graphic (studio), a presentation slide or a page of "
            "text (has_text_or_watermark), an AI-made or fantasy picture (ai_generated), a stock watermark.\n")


def judge(path: str, intent: str, context: str = "", event: bool = False,
          scene: Optional[dict] = None, wants: str = "") -> Optional[dict]:
    """
    Verdict for one candidate file, or None when no model could be reached.

    None means "unknown", not "bad": the caller keeps its pre-vision behaviour
    rather than rejecting every clip because an API is down. `event`: the beat
    belongs to a news/weather/disaster story, so the footage must be of that
    specific event and place, not the same kind of thing elsewhere. `wants`:
    "map" or "chart" when the line asks for a map or a diagram (_wanted_line).
    """
    if not enabled() or not path or not os.path.exists(path):
        return None
    key = (f"{_fingerprint(path)}|{int(event)}|{intent}|{_STORY['line'][:80]}"
           f"|{_scene_lines(scene)[:160]}|{wants if wants in ('map', 'chart') else ''}")
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]

    frames = sample_frames(path, config.VISION_FRAMES, judge_width(path))
    if not frames:
        _fail("ffmpeg", f"no frames from {os.path.basename(path)}")
        with _LOCK:
            _UNJUDGED["n"] += 1
        return None

    content = [{"type": "text", "text":
                (f"STORY: {_STORY['line']}\n" if _STORY["line"] else "")
                + f"INTENT: {intent}\n" + _scene_lines(scene) + _wanted_line(wants) + f"NARRATION: {context}\n"
                f"These are {len(frames)} frames from the candidate. "
                "Answer with ONLY the JSON object described in your instructions - no prose."}]
    content += [{"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{f}"}} for f in frames]
    messages = [{"role": "system", "content": _system() + (_EVENT_RULE if event else "")},
                {"role": "user", "content": content}]

    text, model = _ask(messages, 400, accept=lambda t: _parse(t) is not None)
    verdict = _parse(text) if text else None
    if verdict:
        verdict["model"] = model
    elif text:
        _fail(model, f"unparseable verdict: {text[:120]!r}")

    with _LOCK:
        _CALLS["n"] += 1
    if text:
        costs.record("vision.judge")
    with _LOCK:
        if verdict:
            _CACHE[key] = verdict
        else:
            _UNJUDGED["n"] += 1
    return verdict


def acceptable(verdict: Optional[dict], allow_people: bool = False) -> bool:
    """
    Pass/fail for a verdict. Unknown (None) passes — see judge().

    allow_people: the line is about a named person, so a portrait or that
    person speaking is the right shot, not a talking-head reject. The score
    still has to clear the floor, which is what checks it is the RIGHT person
    doing the right thing.
    """
    if verdict is None:
        # Unjudged used to pass ("vision can only remove clips"). During a
        # model outage that let an off-topic, watermarked stock dolphin clip
        # open a documentary. With gpt-5-2 first and the circuit breaker,
        # no verdict now means every model failed: reject.
        return bool(config.ACCEPT_UNJUDGED)
    if verdict["has_text_or_watermark"]:
        return False
    # AI slop never passes, whatever the line (the owner, 2026-09-30: "this is
    # AI slop clip"); a studio, presenter, streamer or TV map only for a line
    # about a named person (their own interview or appearance).
    if verdict.get("ai_generated"):
        return False
    if verdict.get("studio") and not allow_people:
        return False
    if verdict["is_talking_head"] and not allow_people:
        return False
    quality = verdict.get("quality")
    if quality is not None and quality < config.VISION_MIN_QUALITY:
        return False
    return verdict["score"] >= config.VISION_MIN_SCORE


def appeal(relevance: Optional[float], quality: Optional[float]) -> float:
    """
    How strongly a clip that already passed would open or carry a beat.

    Relevance leads - the right subject in fair footage beats a gorgeous wrong
    one - and quality breaks near-ties. Unrated quality counts as middling.
    """
    return (relevance or 0.0) + 0.5 * (0.5 if quality is None else quality)


_PICK_SYSTEM = (
    "You pick B-roll for one line of a documentary narration. You are shown a "
    "numbered grid of thumbnails taken across one YouTube video (numbers in the "
    "top-left of each tile). Choose the single tile that best SHOWS the intent. "
    "Never choose a tile showing a presenter talking to camera, a title card, "
    "on-screen text, a graphic, a map or a logo unless the intent asks for it, and "
    "never one that looks AI-generated, painted, illustrated or rendered, or a TV "
    "studio, weather presenter, YouTuber or live-stream screen.\n"
    "Scoring: 0.9-1.0 the tile clearly shows the intended subject; 0.7-0.89 is "
    "consistent with every person, place and era the intent names; below 0.7 nothing "
    "in the grid really fits. A tile from a different named place, person or era "
    "than the intent's is never a match, however well it fits the mood.\n"
    "The tiles are small, low-resolution thumbnails. Only score above 0.7 when you "
    "can actually make out the subject. If a tile is too blurry to identify, do not "
    "guess from the video's topic - score it low. A wrong pick costs a download.\n"
    "Reply with JSON only: {\"tile\": int, \"score\": number, \"description\": str}"
)


_RATE_SYSTEM = (
    "You pick B-roll moments for a documentary, GoMotion-style: one long video about "
    "a subject supplies many shots. You are shown a numbered grid of thumbnails "
    "taken across one YouTube video (numbers top-left). For EVERY tile that is a "
    "usable shot of the SUBJECT - or, when an INTENT is given, of the exact shot the "
    "INTENT describes - give a score and at most 10 words on what it shows.\n"
    "Usable = the subject itself (or its immediate setting) filmed as real footage: "
    "aerials, landscapes, the place, the thing, the event. NOT usable: a presenter or "
    "interviewee talking to camera, title cards, on-screen text or captions, graphics, "
    "maps, logos, black or blurry frames, a different named place or era, anything "
    "that looks AI-generated, painted, illustrated or rendered, a TV studio or weather "
    "presenter, a TV weather map, a YouTuber's or live stream's screen, and a banner or "
    "sign naming another city, state, storm or year.\n"
    "Scoring: 0.9-1.0 clearly the subject, striking footage; 0.7-0.89 clearly the "
    "subject; below 0.7 leave the tile out. Tiles are small thumbnails - never score "
    "above 0.7 what you cannot actually make out.\n"
    "Reply with JSON only: {\"tiles\": [{\"tile\": int, \"score\": number, "
    "\"description\": str}]} listing only tiles scoring 0.7 or more (an empty list "
    "when none fit)."
)


_TILE_ROW = re.compile(r'\{\s*"tile"\s*:\s*(\d+)\s*,\s*"score"\s*:\s*([\d.]+)\s*,\s*"description"\s*:\s*"((?:[^"\\]|\\.)*)"')


def rate_tiles(sheet_b64: str, count: int, subject: str, context: str = "",
               intent: str = "") -> Optional[List[dict]]:
    """
    Every usable tile of one storyboard sheet for a subject, in one call:
    [{"tile": 1-based, "score": 0-1, "description": str}] (None on failure).

    GoMotion cut 174 clips from few long videos about 45 subjects; judging a
    video once and taking many moments from it replaces a search, scout,
    download and vision check per scene.
    """
    if not enabled():
        return None
    messages = [
        {"role": "system", "content": _RATE_SYSTEM + (_NEWS_TILE_RULE if config.NEWS_FOOTAGE else "")},
        {"role": "user", "content": [
            {"type": "text", "text": (f"STORY: {_STORY['line']}\n" if _STORY["line"] else "")
             + (f"INTENT (the exact shot wanted): {intent}\n" if intent else "")
             + (f"SUBJECT: {subject}\n" if subject else "")
             + (f"WHAT THE LINES SAY ABOUT IT: {context[:600]}\n" if context else "")
             + f"There are {count} tiles, numbered 1-{count}."},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{sheet_b64}"}},
        ]},
    ]
    text, model = _ask(messages, 900)
    with _LOCK:
        _CALLS["n"] += 1
    if not text:
        # Every model failed: the local CLIP pass rates the tiles instead, so
        # the video still gets its best moments rather than none.
        from . import localvision
        return localvision.rate_sheet(sheet_b64, count, intent or subject)
    costs.record("vision.rate_tiles")
    m = re.search(r"\{[\s\S]*\}", text)
    try:
        data = json.loads(m.group(0)) if m else {}
        rows = data.get("tiles") or []
        out = []
        for r in rows:
            tile, score = int(r.get("tile")), max(0.0, min(1.0, float(r.get("score", 0))))
            if 1 <= tile <= count:
                out.append({"tile": tile, "score": score,
                            "description": str(r.get("description") or "")[:300]})
    except (ValueError, TypeError, AttributeError):
        # Kie sometimes hands back a reply that starts mid-JSON (seen 17 times
        # in one job with gpt-5-2: '0.88,"description":...},{"tile":5,...').
        # Keep every complete tile object in it rather than losing the sheet.
        out = []
        for m2 in _TILE_ROW.finditer(text):
            try:
                tile, score = int(m2.group(1)), max(0.0, min(1.0, float(m2.group(2))))
            except ValueError:
                continue
            if 1 <= tile <= count:
                out.append({"tile": tile, "score": score, "description": m2.group(3)[:300]})
        if not out:
            _fail(model, f"unparseable tile rating: {text[:120]!r}")
            return None
    return out


def pick_tile(sheet_b64: str, count: int, intent: str, context: str = "") -> Optional[dict]:
    """Best tile number (1-based) on a storyboard contact sheet, or None."""
    if not enabled():
        return None
    messages = [
        {"role": "system", "content": _PICK_SYSTEM + (_NEWS_TILE_RULE if config.NEWS_FOOTAGE else "")},
        {"role": "user", "content": [
            {"type": "text", "text": (f"STORY: {_STORY['line']}\n" if _STORY["line"] else "")
             + f"INTENT: {intent}\nNARRATION: {context}\n"
             f"There are {count} tiles, numbered 1-{count}."},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{sheet_b64}"}},
        ]},
    ]
    text, model = _ask(messages, 400)
    with _LOCK:
        _CALLS["n"] += 1
    if not text:
        # Every model failed: the best tile by the local CLIP pass, if any
        # clears the floor.
        from . import localvision
        rated = localvision.rate_sheet(sheet_b64, count, intent) or []
        best = max(rated, key=lambda r: r["score"], default=None)
        if best and best["score"] >= config.VISION_MIN_SCORE:
            return dict(best, model="local-clip")
        return None
    costs.record("vision.pick_tile")
    m = re.search(r"\{[\s\S]*\}", text)
    try:
        data = json.loads(m.group(0)) if m else {}
        tile = int(data.get("tile"))
        score = max(0.0, min(1.0, float(data.get("score", 0))))
    except (ValueError, TypeError):
        _fail(model, f"unparseable tile pick: {text[:120]!r}")
        return None
    return {"tile": tile, "score": score,
            "description": str(data.get("description") or "")[:400], "model": model}
