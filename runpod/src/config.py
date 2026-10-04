"""Runtime configuration, read from RunPod endpoint environment variables."""
import os


def _load_dotenv() -> None:
    """Fill gaps in the environment from a local .env, for runs off RunPod.

    On RunPod the endpoint supplies every variable and this finds no file. On a
    dev box there is no endpoint, so without this a configured YTDLP_PROXY sits
    in .env doing nothing and sourcing quietly falls back to the bare IP —
    which looks like working code right up until it runs in production.

    Real environment variables always win; this only fills what is unset.
    """
    # The test suite asserts unconfigured behaviour (rule planner, generation
    # off). Filling those from a developer's real .env silently tests the
    # configured path instead, so tests opt out explicitly.
    if os.getenv("SKIP_DOTENV"):
        return
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for path in (os.path.join(here, ".env"),
                 os.path.join(os.path.dirname(here), ".env")):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
        except OSError:
            pass


_load_dotenv()


def _flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, "1" if default else "0").strip().lower() in {"1", "true", "yes", "on"}


# --- sourcing policy ---------------------------------------------------------
# This workflow is deliberately NO-STOCK: footage comes from YouTube via yt-dlp
# (Creative Commons only), images from an image model plus Wikimedia/Openverse
# for real named subjects. Generic stock libraries cannot supply "the Million
# Dollar Highway" or "the 7.4 Colombia quake", which is what documentary
# narration actually asks for.
#
# The stock adapters are still in media.py as an escape hatch. Turning them on
# also requires relaxing timeline.validate(), which rejects stock sources.
ALLOW_STOCK = _flag("ALLOW_STOCK", False)
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "")

# YouTube footage. REQUIRE_CC restricts sourcing to Creative Commons uploads.
# Off by default: CC-licensed YouTube is dominated by gaming streams, phone
# video and tutorials, which is exactly what made early renders look amateur,
# and neither VidRush nor GoMotion filters on licence (their timelines carry
# CNN and Kinolibrary cuts). Unfiltered clips are flagged reviewRequired with an
# "unverified licence" note, so the Content ID exposure stays visible per scene.
# Set REQUIRE_CC=1 for channels that must stay claim-free.
ALLOW_YOUTUBE = _flag("ALLOW_YOUTUBE", True)
REQUIRE_CC = _flag("REQUIRE_CC", False)
# Second real-footage source after YouTube (news-outlet clips, keyless API).
# Same licence posture as unfiltered YouTube: flagged reviewRequired, and
# skipped entirely when REQUIRE_CC is on.
ALLOW_DAILYMOTION = _flag("ALLOW_DAILYMOTION", True)
# Internet Archive public-domain / CC-BY film (see search_archive_org_video).
ALLOW_ARCHIVE_ORG = _flag("ALLOW_ARCHIVE_ORG", True)

# Optional residential/ISP proxy for yt-dlp. Datacenter addresses may be
# challenged by YouTube, but a proxy alone does not guarantee downloads.
# Test metadata extraction AND a short media download on the deployed worker.
#
# Accepts one proxy or a comma-separated list, which is rotated per request so
# a single address does not absorb every download and get flagged.
# Format: http://user:pass@host:port (or socks5://...).
YTDLP_PROXY = os.getenv("YTDLP_PROXY", "").strip()
YTDLP_PROXIES = [p.strip() for p in YTDLP_PROXY.split(",") if p.strip()]
# Routes for picture downloads only (news sites and CDNs refuse datacenter
# addresses). A proxy YouTube bot-blocks is still fine here (the owner,
# 2026-10-02: "use those non-working proxies of YouTube for something"), so
# this list may hold more than YTDLP_PROXY. Empty = the YouTube pool.
IMAGE_PROXY = os.getenv("IMAGE_PROXY", "").strip()
IMAGE_PROXIES = [p.strip() for p in IMAGE_PROXY.split(",") if p.strip()] or YTDLP_PROXIES
# Residential sticky sessions from one login: "{n}" in the template is the
# session number (Webshare: http://USER-us-{n}:PASS@p.webshare.io:80). Each
# session keeps one US home IP for a whole download - YouTube locks a
# video's stream URL to the IP that asked for it, so per-request rotation
# breaks downloads - while different downloads spread over many IPs.
YTDLP_PROXY_TEMPLATE = os.getenv("YTDLP_PROXY_TEMPLATE", "").strip()
YTDLP_PROXY_SESSIONS = int(os.getenv("YTDLP_PROXY_SESSIONS", "100"))
if YTDLP_PROXY_TEMPLATE and "{n}" in YTDLP_PROXY_TEMPLATE:
    YTDLP_PROXIES += [YTDLP_PROXY_TEMPLATE.replace("{n}", str(n))
                      for n in range(1, YTDLP_PROXY_SESSIONS + 1)]

# yt-dlp can also present browser cookies, which helps with the same check.
YTDLP_COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE", "").strip()

# Cap on concurrent yt-dlp subprocesses (search, metadata, download combined).
# Scene-level sourcing (6 workers) x moment-scouting (MOMENT_PARALLEL, 3) can
# ask for up to 18 requests at once; with only a handful of proxy IPs that is
# real oversubscription, not real speed - contended proxies just queue and
# time out, which reads as "sourcing is slow" with nothing to explain why.
# Default tracks the proxy pool (one request per healthy IP), floor of 4 so
# an unproxied dev box still gets some parallelism.
# Capped at 16: with a hundred sticky sessions the old formula allowed 200
# simultaneous yt-dlp processes on one worker.
NETWORK_CONCURRENCY = int(os.getenv("NETWORK_CONCURRENCY", "0")) or max(4, min(16, 2 * len(YTDLP_PROXIES)))

# --- generated images --------------------------------------------------------
# Any OpenAI-compatible /images/generations endpoint (OpenAI gpt-image-1, or a
# compatible gateway). Same env shape as the director below, deliberately.
IMAGE_API_BASE = os.getenv("IMAGE_API_BASE", "https://api.openai.com/v1").rstrip("/")
IMAGE_API_KEY = os.getenv("IMAGE_API_KEY", "")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-1")
IMAGE_SIZE = os.getenv("IMAGE_SIZE", "1536x1024")
IMAGE_STYLE_SUFFIX = os.getenv(
    "IMAGE_STYLE_SUFFIX",
    "photorealistic documentary still, natural lighting, 16:9, no text, no watermark",
)

# Generate stills FIRST instead of only when nothing real is found. This is
# how VidRush looks: consistent, on-topic illustration rather than whatever a
# photo archive happens to hold. The trade-off is real and worth stating — a
# generated photoreal image of an actual event is an illustration of it, not a
# record, so generated frames always carry review_required and their licence
# field says so. For a beat about a real, documented event a real photograph
# is still the better shot, which is why the real sources remain the fallback.
PREFER_GENERATED_IMAGES = _flag("PREFER_GENERATED_IMAGES", False)

# Hard ceiling per video. At roughly $0.02-0.19 an image, a 20-minute script
# of ~400 scenes could run to real money on a single render, and a runaway
# retry loop could do it without anyone watching.
IMAGE_MAX_PER_VIDEO = int(os.getenv("IMAGE_MAX_PER_VIDEO", "80"))

# --- AI director -------------------------------------------------------------
# Optional. Without it the rule-based planner in director.py runs alone.
DIRECTOR_API_BASE = os.getenv("DIRECTOR_API_BASE", "").rstrip("/")
DIRECTOR_API_KEY = os.getenv("DIRECTOR_API_KEY", "")
DIRECTOR_MODEL = os.getenv("DIRECTOR_MODEL", "")
# Tried in order if DIRECTOR_MODEL fails or times out. Empty entries are
# skipped. Measured 2026-09-25 on a real 95s narration, whole-story pass:
#   gemini-3-8-flash-openai  8.9s  0.13 credits
#   gpt-5-2                 18.4s  0.69 credits
#   gemini-3-pro            21.2s  0.55 credits
# All three named the unnamed cast correctly from context. Kie serves the
# Flash models on their own path only; director._chat_url handles that.
DIRECTOR_FALLBACK_MODELS = [m.strip() for m in
                           os.getenv("DIRECTOR_FALLBACK_MODELS", "gpt-5-2,gemini-3-pro").split(",")
                           if m.strip()]
# The routine planning calls - each batch of lines turned into shots and search
# words, the rescue, sequence and assign passes - on a cheaper model; the story
# brief (what the video is about, who and where) stays on DIRECTOR_MODEL, which
# also backs the routine model up when it fails. "" = every call on
# DIRECTOR_MODEL, as before. The owner (2026-10-05): "make this video using
# cost cut method" - ~13 of a video's ~15 planning calls are routine.
DIRECTOR_ROUTINE_MODEL = os.getenv("DIRECTOR_ROUTINE_MODEL", "").strip()

# --- vision verification -----------------------------------------------------
# Every candidate clip/image is shown to a multimodal model, which describes
# what is actually in the frames and scores it against the shot's intent.
# Below VISION_MIN_SCORE it is rejected and the next candidate is tried. 0.70
# is VidRush's own floor: across 325 scored items on one of their timelines the
# minimum was exactly 0.70. Defaults reuse the director's key, so a Kie key
# configured once powers both.
# Backup AI provider (any OpenAI-compatible API), used for planning and vision
# whenever the main one fails - including when the Kie account is out of
# credits. Google Gemini, for example: base
# https://generativelanguage.googleapis.com/v1beta/openai, model gemini-2.5-flash,
# key from Google AI Studio. Empty = no backup.
AI_FALLBACK_API_BASE = os.getenv("AI_FALLBACK_API_BASE", "").rstrip("/")
AI_FALLBACK_API_KEY = os.getenv("AI_FALLBACK_API_KEY", "")
AI_FALLBACK_MODEL = os.getenv("AI_FALLBACK_MODEL", "gemini-2.5-flash")
AI_FALLBACK_VISION_MODEL = os.getenv("AI_FALLBACK_VISION_MODEL", "") or AI_FALLBACK_MODEL

VISION_ENABLED = _flag("VISION_ENABLED", True)
VISION_API_BASE = os.getenv("VISION_API_BASE", "") or DIRECTOR_API_BASE or "https://api.kie.ai/v1"
VISION_API_KEY = (os.getenv("VISION_API_KEY", "") or DIRECTOR_API_KEY
                  or os.getenv("KIE_API_KEY", ""))
# Measured on 8 real candidates, cache cleared per model (2026-09-25):
#   gemini-3-8-flash-openai  7.2s/img  0.080 credits
#   gpt-5-2                 14.5s/img  0.085 credits
#   gemini-3-pro            11.3s/img  0.198 credits
# Flash was also the stricter judge: it saw that an "immigration file" was a
# modern 3D illustration (0.40) where gpt-5-2 passed it (0.82).
VISION_MODEL = os.getenv("VISION_MODEL", "gemini-3-8-flash-openai")
VISION_FALLBACK_MODELS = [m.strip() for m in
                          os.getenv("VISION_FALLBACK_MODELS", "gpt-5-2,gemini-3-pro").split(",")
                          if m.strip()]
VISION_MIN_SCORE = float(os.getenv("VISION_MIN_SCORE", "0.70"))
# Footage quality floor (sharpness, stability, light, framing), judged in the
# same call. Low on purpose: it only removes clips that are plainly unwatchable,
# since rejecting more leaves scenes empty; quality otherwise ranks hook shots.
VISION_MIN_QUALITY = float(os.getenv("VISION_MIN_QUALITY", "0.30"))
# A candidate the judge scored under VISION_MIN_SCORE but at or above this
# is kept as the "best available" when nothing passes, flagged for review:
# a related shot the editor can swap beats an empty beat. Clear rejections
# (a watermark, a talking head) never qualify.
VISION_SOFT_MIN_SCORE = float(os.getenv("VISION_SOFT_MIN_SCORE", "0.55"))
# gpt-5-2 reasons before it answers. Measured on one real clip check: 32.5 s
# at the default effort, 13.5 s at "low", same verdict (0.97 vs 0.98);
# "minimal" is refused (code 500). Sent to gpt-* models only. Empty = default.
VISION_REASONING_EFFORT = os.getenv("VISION_REASONING_EFFORT", "low").strip()
# Google Gemini (VISION_API_BASE = Google's OpenAI-compatible endpoint): thinking
# eats max_tokens, so vision calls ask for none (see vision._extra).
VISION_GEMINI_REASONING = os.getenv("VISION_GEMINI_REASONING", "none").strip()
VISION_FRAMES = int(os.getenv("VISION_FRAMES", "3"))
# Frame widths sent to the judge. Measured on OpenRouter gemini-2.5-flash
# (2026-10-01): a check of 3 clip frames costs 258 image tokens a frame at
# 512 px or 384 px alike, but a lone photo at 512 px is cut into 5 tiles
# (1,290 tokens) and at 384 px is one (258): a photo check 2,946 -> 1,914
# prompt tokens. Clips keep 512 px (free); photos go at 384.
VISION_FRAME_WIDTH = int(os.getenv("VISION_FRAME_WIDTH", "512"))
VISION_STILL_WIDTH = int(os.getenv("VISION_STILL_WIDTH", "384"))
# The judge's long, fixed instructions (~1,500 tokens) as a cached block on
# OpenRouter for Gemini and Claude models: read back at a quarter of the input
# price. Measured: a clip check $0.00110 -> $0.00066-0.00071, same verdicts.
VISION_PROMPT_CACHE = _flag("VISION_PROMPT_CACHE", True)
# Retries per model on a transient failure (timeout, 5xx, 429), before the
# fallback model is tried, and the pause before the first (doubling after).
# Google answered "high demand" (503) in bursts all night on 2026-09-29: one
# quick retry lost 56 of 101 verdicts on the parent alone.
VISION_RETRIES = int(os.getenv("VISION_RETRIES", "2"))
VISION_RETRY_WAIT = float(os.getenv("VISION_RETRY_WAIT", "2"))
# How long a model that failed twice in a row sits out. A provider-wide 503
# burst is over in a minute or two; five minutes benched every model at once.
VISION_MODEL_COOLDOWN_SECONDS = float(os.getenv("VISION_MODEL_COOLDOWN_SECONDS", "90"))
# One request's timeout. gpt-5-2 answers a clip check in ~14 s at "low"; the
# old 90 s wait, retried and then repeated on the fallback, let one verdict
# hold a scene for ~6 minutes when Kie's channels stalled (job 16c80a8b:
# 112 failed vision calls, most of them timeouts).
VISION_TIMEOUT = float(os.getenv("VISION_TIMEOUT", "60"))
# No answer after this many seconds: the next model is asked in parallel and
# the first answer wins (a whole contact sheet gets 1.6x). 0 = one at a time.
VISION_HEDGE_SECONDS = float(os.getenv("VISION_HEDGE_SECONDS", "25"))
# A call gives up after this long in total; the candidate is then handled
# like any unjudged one. Late answers are dropped.
VISION_CALL_BUDGET_SECONDS = float(os.getenv("VISION_CALL_BUDGET_SECONDS", "100"))
# Vision requests in flight per worker. Ten workers each firing 20+ at once
# drew Kie's "You've hit your attachment limit" (Glen Canyon, 2026-09-29).
VISION_CONCURRENCY = int(os.getenv("VISION_CONCURRENCY", "8"))
# Kie's vision channels time out or answer in prose under bursts: with two jobs
# at VISION_CONCURRENCY 20 each, 123 of 130 calls failed (ReadTimeout) and 278
# answers on the owner's 12-min job were unparseable (2026-10-01). Requests to
# Kie are capped at this many in flight per worker whatever the job asks for.
VISION_KIE_MAX_CONCURRENCY = int(os.getenv("VISION_KIE_MAX_CONCURRENCY", "8"))
# News footage the GoMotion way: local-TV reports of the exact event, shown
# with their station logo, headline banner and ticker as they are. Off = the
# old rule (any other channel's text or logo rejects a clip).
NEWS_FOOTAGE = _flag("NEWS_FOOTAGE", True)
# Candidates judged per search before giving up on that query. Each judged
# candidate costs one model call, so this bounds spend per scene.
VISION_MAX_CANDIDATES = int(os.getenv("VISION_MAX_CANDIDATES", "3"))
# Results asked of each YouTube flat search. One request either way (the
# results page), so a longer list only widens the metadata ranking.
YT_SEARCH_RESULTS = int(os.getenv("YT_SEARCH_RESULTS", "20"))
# Best-of-N judging. A scene no longer takes the first clip that clears the
# floor: up to JUDGE_BEST_OF passing clips are judged and the strongest wins,
# the rest ride along as alternatives for Replace Clip. A clip at
# EXCELLENT_SCORE or above ends the search at once. JUDGE_MAX_PER_SCENE caps
# vision calls across all of a scene's expanded searches.
JUDGE_BEST_OF = int(os.getenv("JUDGE_BEST_OF", "2"))
EXCELLENT_SCORE = float(os.getenv("EXCELLENT_SCORE", "0.85"))
# Every model call a scene makes (scouting, the fine pass, judging) across
# all its searches. The old-style search used about 10 per scene.
JUDGE_MAX_PER_SCENE = int(os.getenv("JUDGE_MAX_PER_SCENE", "12"))
# Searches a typed scene intent expands to (src/intent.py), specific first.
INTENT_QUERIES_MAX = int(os.getenv("INTENT_QUERIES_MAX", "10"))
# The candidate pool (src/candidates.py): every search variant plus
# POOL_EXTRA_QUERIES of the intent's own searches are pooled and ranked on
# metadata before the best POOL_SCOUT are scouted and judged. Off restores the
# search-by-search order (kept for A/B benchmarks). Weights are JSON maps.
CANDIDATE_POOL = _flag("CANDIDATE_POOL", True)
POOL_EXTRA_QUERIES = int(os.getenv("POOL_EXTRA_QUERIES", "2"))
# Three, not five: a scout is a model call, and the first benchmark of the
# pool showed scenes spending their budget on scouting before a download.
POOL_SCOUT = int(os.getenv("POOL_SCOUT", "2"))


def _json_env(name: str):
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        import json as _json
        value = _json.loads(raw)
        return value if isinstance(value, dict) else None
    except ValueError:
        return None


# How long a job waits at its end for downloads a time box left running.
DRAIN_SECONDS = float(os.getenv("DRAIN_SECONDS", "15"))
# Replace Clip: how many ranked choices a re-source returns (winner + rest).
REPLACE_ALTERNATIVES = int(os.getenv("REPLACE_ALTERNATIVES", "5"))
# Pick-a-shot (the owner, 2026-10-02): every scene of a build keeps its best
# runner-up clips - already downloaded and judged, so no extra search or AI
# call - published beside the winner so the editor offers "3 other options"
# the moment a clip is clicked. Storage only (~3 x 2 MB a scene on R2).
PICK_A_SHOT = _flag("PICK_A_SHOT", True)
PICK_A_SHOT_CHOICES = int(os.getenv("PICK_A_SHOT_CHOICES", "3"))
META_WEIGHTS = _json_env("META_WEIGHTS")
FINAL_WEIGHTS = _json_env("FINAL_WEIGHTS")

# Moment selection: read the video's storyboard (YouTube's hover-preview
# thumbnails, ~1/sec, a few hundred KB) and let the vision model pick the
# timestamp that shows the intent, instead of cutting at a fixed 35%.
# Wall-clock cap on the second sourcing pass (repeats, rejected and empty
# scenes). Attempts in flight finish; no new ones start after it.
# Speed defaults (2026-09-27): a 3-minute narration must finish in 5-10 min.
# Per-scene judging is capped at 12 model calls, a 0.85 clip ends a search,
# and the repair passes are half as long; animation scenes cover the rest.
REPLACE_BUDGET_SECONDS = int(os.getenv("REPLACE_BUDGET_SECONDS", "120"))
# Wall-clock cap on the AI-rescue pass for scenes still empty after pass 2.
RESCUE_BUDGET_SECONDS = int(os.getenv("RESCUE_BUDGET_SECONDS", "60"))
# Last resort for a scene nothing could fill: reuse a real shot of the same
# subject (or a nearby scene) from elsewhere in the video, never within
# REUSE_MIN_GAP scenes of itself and always flagged for review. Off ("0")
# restores the strict "a clip never appears twice" rule, at the cost of
# empty scenes on long videos about subjects with few real photos.
REUSE_SHOTS_TO_FILL = _flag("REUSE_SHOTS_TO_FILL", True)
# Before a shot is repeated, try another moment of the same on-subject video
# (20-90 s away, a 10 s bucket no scene uses), checked like any clip. The time
# box for all of them together, per sourcing pass.
FRESH_MOMENTS = _flag("FRESH_MOMENTS", True)
FRESH_MOMENT_SECONDS = float(os.getenv("FRESH_MOMENT_SECONDS", "90"))
# Source the video in sequences (runs of lines about one subject and setting,
# each with one pool of shots laid out by an editor call) before the
# line-by-line search. Off ("0") restores line-by-line sourcing only.
SEQUENCE_SOURCING = _flag("SEQUENCE_SOURCING", True)
# When the AI account reports it is out of credits. Off (the default, the
# creator's call): keep going - plan from the story rules, source from every
# free source, and flag the timeline so the gap is visible. On ("1"): stop
# the job with a clear "top up" error before spending on footage.
REQUIRE_AI = _flag("REQUIRE_AI", False)
MOMENT_SELECTION = _flag("MOMENT_SELECTION", True)
MOMENT_TILES = int(os.getenv("MOMENT_TILES", "20"))
# The fine pass (src/moments.refine): a second sheet of the seconds around
# the coarse pick at the storyboard's own rate, rated tile by tile, so the
# clip is cut from the strongest continuous stretch. One more model call per
# downloaded candidate.
MOMENT_FINE_PASS = _flag("MOMENT_FINE_PASS", True)
MOMENT_FINE_TILES = int(os.getenv("MOMENT_FINE_TILES", "20"))
# Every downloaded section is taken with CUT_MARGIN_SECONDS on each side and
# cut from its longest stretch without a shot change (media.tidy_clip).
CLEAN_CUTS = _flag("CLEAN_CUTS", True)
CUT_MARGIN_SECONDS = float(os.getenv("CUT_MARGIN_SECONDS", "2.0"))
SHOT_CUT_THRESHOLD = float(os.getenv("SHOT_CUT_THRESHOLD", "0.4"))
# A softer jump is a shot change too when it stands out from the frames around
# it (filters.shot_changes). The owner's Glen Canyon test (2026-10-05) opened on
# 1.43 s of the shot before its clip: a cut between two grey shots ffmpeg scored
# 0.36, under SHOT_CUT_THRESHOLD, so the cut window never saw it. Such a frame
# counts when its score is at least SHOT_CUT_SOFT_THRESHOLD and SHOT_CUT_RATIO
# times the median of the frames within half a second of it, and the two frames
# either side of it do not show the same picture (a normalised correlation of
# their small grey copies under SHOT_CUT_SAME_PICTURE: an exposure flicker or a
# flash of old film stays one shot - measured 0.87-0.91 there, 0.09-0.33 at real
# cuts). SHOT_CUT_SOFT_THRESHOLD 0 = the fixed threshold only, as before.
SHOT_CUT_SOFT_THRESHOLD = float(os.getenv("SHOT_CUT_SOFT_THRESHOLD", "0.2"))
SHOT_CUT_RATIO = float(os.getenv("SHOT_CUT_RATIO", "4.0"))
SHOT_CUT_SAME_PICTURE = float(os.getenv("SHOT_CUT_SAME_PICTURE", "0.75"))
# Every footage cut starts after a shot change, never on the last second of the
# shot before it: a planned in-point under CUT_GUARD_SECONDS before a shot
# change moves forward past it - CUT_SNAP_PAD past it, so no frame of the shot
# before shows - and the clip keeps its length from later in the section; a
# remainder too short to cover the line is not used (the caller's next
# candidate or the fallback ladder takes the line - a clip is never slowed).
CUT_GUARD_SECONDS = float(os.getenv("CUT_GUARD_SECONDS", "1.0"))
CUT_SNAP_PAD = float(os.getenv("CUT_SNAP_PAD", "0.1"))
# Candidate videos scouted in parallel per search. Each scout is one yt-dlp
# metadata call plus one vision call; the beat then costs about the slowest.
# This is also the ONLY candidates a query ever gets: _plan_grabs slices the
# search results to exactly this many before scouting, so raising it is what
# lets a scene reach past the first few search results when none of them has
# the right moment - a real limiter on match quality, not just a speed knob.
MOMENT_PARALLEL = int(os.getenv("MOMENT_PARALLEL", "5"))

# --- web image search ----------------------------------------------------------
# Real photographs of named people, places and events. Serper (Google Images)
# when SERPER_API_KEY is set; otherwise the keyless DuckDuckGo image search.
ALLOW_WEB_IMAGES = _flag("ALLOW_WEB_IMAGES", True)
# One try of a picture download (src/imagefix.py): how long the host may take
# to accept the connection, and how long the whole transfer may run. A host
# that took no connection used to cost ~20 s on each of the plain, browser and
# Chrome-fingerprint tries plus 25 s through the residential route (~85 s a
# picture, measured 62 s off RunPod 2026-10-04), and a host trickling bytes had
# no limit at all: each 20 s read timeout restarts with every byte.
PICTURE_CONNECT_SECONDS = float(os.getenv("PICTURE_CONNECT_SECONDS", "10"))
PICTURE_FETCH_SECONDS = float(os.getenv("PICTURE_FETCH_SECONDS", "60"))
# Candidate pictures of one search downloaded at once (media._pick_unused): the
# next ones arrive while one is checked and judged, in the same order and with
# the same checks. Downloads were ~70% of a picture search's thread time
# (eight of the Yellowstone re-cut's still pieces, run off RunPod 2026-10-04:
# 55 downloads, 2.9 s each, 32 of them then too soft or too small). At most
# PICTURE_PREFETCH - 1 downloads a search did not need; 0 or 1 = one at a time.
PICTURE_PREFETCH = int(os.getenv("PICTURE_PREFETCH", "3"))
# Non-YouTube videos from Google's video search (TikTok, Facebook, Vimeo,
# news sites), downloaded by yt-dlp. Only when the job is not youtube_only.
ALLOW_WEB_VIDEO = _flag("ALLOW_WEB_VIDEO", True)
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")

# Director calls: when the first model has been silent this long, the next one
# is asked in parallel and the first valid answer wins. A call gives up after
# DIRECTOR_BUDGET_FACTOR x its timeout. The story brief is one long answer
# and gets BRIEF_TIMEOUT per request (a 22-minute story took 9 minutes of
# 120 s timeouts and retries on 2026-09-28).
DIRECTOR_HEDGE_SECONDS = float(os.getenv("DIRECTOR_HEDGE_SECONDS", "75"))
DIRECTOR_BUDGET_FACTOR = float(os.getenv("DIRECTOR_BUDGET_FACTOR", "2.2"))
BRIEF_TIMEOUT = int(os.getenv("BRIEF_TIMEOUT", "240"))

# Story-planning batches (director._ai_pass) run this many at a time. At 4 the
# owner's 111-line job planned in two waves (401 s before the first search);
# at 8 its seven 16-line batches go in one.
PLAN_PARALLEL = int(os.getenv("PLAN_PARALLEL", "8"))

# --- subject pools (src/pools.py) -----------------------------------------------
# GoMotion's method: a few long videos per subject, judged once from their
# storyboard, many different moments cut from them. Lines whose subject pool
# runs dry fall back to per-scene sourcing.
SUBJECT_POOLS = _flag("SUBJECT_POOLS", True)
# With fan-out available, every part runs its own subject pools, so all ten
# workers start at once instead of the parent pooling alone first (a real
# job sat 6 minutes at 22-25% on one worker while nine idled).
POOLS_IN_PARTS = _flag("POOLS_IN_PARTS", True)
POOL_MIN_SCENES = int(os.getenv("POOL_MIN_SCENES", "2"))
POOL_MAX_VIDEOS = int(os.getenv("POOL_MAX_VIDEOS", "8"))
POOL_PARALLEL_SUBJECTS = int(os.getenv("POOL_PARALLEL_SUBJECTS", "4"))
POOL_MIN_GAP_SECONDS = float(os.getenv("POOL_MIN_GAP_SECONDS", "8"))
# A subject's candidate videos rated at once (pools.plan_subject); 1 = one at a time.
POOL_RATE_PARALLEL = int(os.getenv("POOL_RATE_PARALLEL", "3"))
# A pooled line whose moment failed (no download, burned-in text, a still, AI)
# tries this many more of its subject's approved moments before it goes to
# the per-scene search (pools.retry_failed).
POOL_RETRY_MOMENTS = int(os.getenv("POOL_RETRY_MOMENTS", "2"))

# --- supabase storage --------------------------------------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "renders")
# Where sourced clips and finished renders go. Both buckets are private; the
# app re-signs their URLs before it shows or renders them.
MEDIA_BUCKET = os.getenv("MEDIA_BUCKET", "video-media")
RENDER_BUCKET = os.getenv("RENDER_BUCKET", "renders")
# Zero-secret storage. With no service key, uploads go through the app's
# `worker-storage` edge function, which signs one upload at a time and only
# for the project whose running job id matches this job. Nothing in this
# image can then write anywhere else in the app's storage.
STORAGE_BROKER_URL = os.getenv("STORAGE_BROKER_URL", "") or (
    f"{SUPABASE_URL.rstrip('/')}/functions/v1/worker-storage" if SUPABASE_URL else "")

# --- paths -------------------------------------------------------------------
WORK_DIR = os.getenv("WORK_DIR", "/tmp/work")
REMOTION_DIR = os.getenv("REMOTION_DIR", "/app/remotion")
# Left unset, Remotion auto-detects concurrency from the host's real CPU
# count, not what this container is actually allowed to spawn threads for.
# A real render crashed (a Rust panic failing to spawn an OS thread) partway
# through, on a GPU pod, right after the heaviest point of the parallel
# sourcing phase. 4 is conservative; raise it only after confirming a higher
# value survives a real render on this same pod type.
# Sourcing pass 1: a whole-pass budget, and once 90% of scenes are in, a
# short grace for the rest. One stalled download used to hold a job for
# 10+ minutes; unfinished scenes fall through to the recheck and fill steps.
PASS1_BUDGET_SECONDS = float(os.getenv("PASS1_BUDGET_SECONDS", "420"))
# Each scene's own share of pass 1 when there are more scenes than threads:
# the pass's seconds x threads / scenes, kept between these. The owner's Lake
# Powell pod (2026-10-01, 130 scenes on 28 threads, 1800 s) finished 49 scenes:
# no scene had a limit, the ones that found nothing kept trying every fallback
# search and source (~14 minutes a scene on average), and 81 never got their
# turn. With 300 s a scene every one of them starts within the box. 0 = off.
SCENE_SECONDS_MIN = float(os.getenv("SCENE_SECONDS_MIN", "120"))
SCENE_SECONDS_MAX = float(os.getenv("SCENE_SECONDS_MAX", "300"))
# Batch mode (src/batch.py, the handler's action "batch"): several videos queued as one job run one after
# another on the same machine. This is the most a batch may run side by side; a job's "max_parallel" can only
# ask for fewer. 1 = strictly one at a time - and the only value this worker honours today: a build keeps its
# state module-wide (config overrides, the cost ledger, the event log, the storage job id), so two builds in
# one process would write into each other's project.
BATCH_MAX_PARALLEL = int(os.getenv("BATCH_MAX_PARALLEL", "1"))
# The longest a batch may run: RunPod stops a job at its endpoint's execution timeout (3 h on tuxcziwby5plod) and a
# stopped job writes nothing more, so its unfinished projects would sit at "rendering". A batch starts no video that
# would not fit (BATCH_VIDEO_SECONDS, or the longest of the batch so far) and, BATCH_LIMIT_MARGIN_SECONDS before the
# limit, writes the video still being made and every one not started as failed itself. A job's own
# "time_limit_seconds" replaces it (a batch queued with a longer RunPod policy, or on a pod); 0 = no limit.
BATCH_TIME_LIMIT_SECONDS = float(os.getenv("BATCH_TIME_LIMIT_SECONDS", "10800"))
BATCH_VIDEO_SECONDS = float(os.getenv("BATCH_VIDEO_SECONDS", "2700"))
BATCH_LIMIT_MARGIN_SECONDS = float(os.getenv("BATCH_LIMIT_MARGIN_SECONDS", "300"))
# Split one long video's sourcing across workers (src/fanout.py). RunPod
# injects RUNPOD_ENDPOINT_ID into its workers; the API key is set on the
# template (FANOUT_API_KEY) so a worker can queue parts on its own endpoint.
# Total worker slots including the parent worker. The parent handles one part
# locally while up to nine child jobs run on the other endpoint workers.
FANOUT_PARTS = int(os.getenv("FANOUT_PARTS", "10"))
FANOUT_MIN_SCENES = int(os.getenv("FANOUT_MIN_SCENES", "1"))
FANOUT_API_KEY = (os.getenv("FANOUT_API_KEY", "")
                  or os.getenv("RUNPOD_API_KEY", ""))
FANOUT_ENDPOINT_ID = os.getenv("FANOUT_ENDPOINT_ID", "") or os.getenv("RUNPOD_ENDPOINT_ID", "")
FANOUT_TIMEOUT_SECONDS = float(os.getenv("FANOUT_TIMEOUT_SECONDS", "1500"))
# Scenes left empty/doubled after round 1: at least this many go back out
# across the workers; fewer are filled on the parent.
# Leftover scenes after round 1 go back out across the workers from this many
# up; a real job kept 9 for the parent alone ("Filling the last 9 scenes").
FANOUT_REFILL_MIN = int(os.getenv("FANOUT_REFILL_MIN", "3"))
# Getting found clips back to the parent. A part retries its uploads until
# its round deadline plus this; a clip that still cannot be handed over is
# fetched again by the parent from its source (REFETCH_*), in parallel, in
# its own time box past the sourcing deadline. The Glen Canyon job lost 148
# of 167 found scenes here while the app's database was restarting.
PART_UPLOAD_GRACE_SECONDS = float(os.getenv("PART_UPLOAD_GRACE_SECONDS", "30"))
# How long a render_chunk child keeps retrying its upload when the parent did
# not say how long it will wait (deadline_at in the payload).
CHUNK_UPLOAD_GRACE_SECONDS = float(os.getenv("CHUNK_UPLOAD_GRACE_SECONDS", "300"))
REFETCH_SECONDS = float(os.getenv("REFETCH_SECONDS", "300"))
REFETCH_PARALLEL = int(os.getenv("REFETCH_PARALLEL", "12"))
# The last pass over scenes still empty after sourcing, before any shot is
# repeated: another moment of a same-subject video, then the best-titled
# search result nobody uses (no vision call), then a web picture. Time boxed.
RESCUE_SECONDS = float(os.getenv("RESCUE_SECONDS", "300"))
RESCUE_PARALLEL = int(os.getenv("RESCUE_PARALLEL", "12"))
# Fresh footage before repeats: per-scene sourcing leaves a beat empty rather
# than reusing a shot, the job's rescue pass looks for new footage, and only
# then is a shot reused - at most REUSE_MAX_USES times in the whole video.
# That cap is for FOOTAGE. A photo is shown at most IMAGE_MAX_USES times and
# a generated image exactly once: the owner's Texas flood video (2026-09-30)
# showed 15 photos across 28 scenes and 4 generated images across 7.
RESCUE_BEFORE_REUSE = os.getenv("RESCUE_BEFORE_REUSE", "1").strip().lower() not in ("0", "false", "no")
REUSE_MAX_USES = int(os.getenv("REUSE_MAX_USES", "2"))
IMAGE_MAX_USES = int(os.getenv("IMAGE_MAX_USES", "1"))

# --- variety and the hook (the owner's review, 2026-09-30) --------------------
# The Texas flood video (news_compilation, 138 scenes) drew 97 YouTube scenes
# from only 55 videos, and "Drone's eye view of Texas flood damage" played 4
# times in its first minute - different 10 s moments of one video still look
# like the same shot. No source video (a YouTube id, whatever the moment) may
# supply more than MAX_MOMENTS_PER_VIDEO scenes, and two scenes cut from one
# video must start at least SAME_VIDEO_GAP_SECONDS apart on the timeline.
# The pools assign moments under both rules and a final pass after sourcing
# re-sources every scene that still breaks one; a scene nothing else can fill
# may keep its repeat, but never within REUSE_MIN_GAP_SECONDS of its twin.
# 0 turns a rule off.
MAX_MOMENTS_PER_VIDEO = int(os.getenv("MAX_MOMENTS_PER_VIDEO", "2"))
SAME_VIDEO_GAP_SECONDS = float(os.getenv("SAME_VIDEO_GAP_SECONDS", "120"))
REUSE_MIN_GAP_SECONDS = float(os.getenv("REUSE_MIN_GAP_SECONDS", "60"))
# The opening decides whether a viewer stays, and 4 of the same video's first
# 5 scenes were AI-generated illustrations. Every scene that starts within
# HOOK_SECONDS is a footage beat (a document keeps its scan), sourced one by
# one with a wider search and a best-of-HOOK_JUDGE_BEST_OF judgement instead
# of from a subject pool, retried for footage after sourcing if it ended on a
# still, and never given a generated image unless GENERATED_IMAGES_IN_HOOK.
HOOK_SECONDS = float(os.getenv("HOOK_SECONDS", "45"))
GENERATED_IMAGES_IN_HOOK = _flag("GENERATED_IMAGES_IN_HOOK", False)
HOOK_JUDGE_BEST_OF = int(os.getenv("HOOK_JUDGE_BEST_OF", "3"))
HOOK_POOL_SCOUT = int(os.getenv("HOOK_POOL_SCOUT", "4"))
HOOK_JUDGE_MAX_PER_SCENE = int(os.getenv("HOOK_JUDGE_MAX_PER_SCENE", "16"))
# A story about something happening now (a news, weather or disaster story
# about this year) searches the last month's uploads first - "this month" on
# YouTube and Dailymotion - and falls back to this year's and then any upload
# only when nothing recent passes. The owner's reference channel shows this
# week's footage of the town the narration names. Off = this year's first.
RECENT_FOOTAGE_FIRST = _flag("RECENT_FOOTAGE_FIRST", True)
# A named place (a dam, a canyon, a landmark) looks the same in the last few
# years' uploads; only footage of the event itself must be from the story's
# year (2026-10-01: every Lake Powell landmark clip was dropped as "uploaded in
# 2022, before this 2026 story" and 18 lines found nothing).
PLACE_FOOTAGE_YEARS = int(os.getenv("PLACE_FOOTAGE_YEARS", "4"))
# "When a person's name is mentioned, show that person WHILE it is said, not
# before, not after" (the owner, 2026-09-30): a beat is split where it names
# one of the story's people and that beat shows the person (src/mentions.py).
MENTION_CUTS = _flag("MENTION_CUTS", True)
# Red arrow / circle / box on a clip "only when it's worth it" (the owner,
# 2026-09-30): a line that points at something visible ("you can see the
# water line") gets a mark where vision finds that thing, at most MARKS_MAX
# per video, MARKS_GAP_SECONDS apart; photo looks that point get their spot
# the same way (src/marks.py).
MARKS_ENABLED = _flag("MARKS_ENABLED", True)
MARKS_MAX = int(os.getenv("MARKS_MAX", "5"))
MARKS_GAP_SECONDS = float(os.getenv("MARKS_GAP_SECONDS", "60"))
# How still photos move: "" rotates the timeline's camera moves (push, reveal,
# drift...); "none" holds them still (the reference weather channel's ~150
# photos have no zoom or pan; nature_weather sets it).
STILL_MOTION = os.getenv("STILL_MOTION", "").strip().lower()
# One wall-clock budget for all footage finding, across every worker: a
# real 3-minute job spent 107 minutes sourcing. When it runs out, downloads
# and searches stop at once and the beats still without footage become
# animation scenes. Budget = base + per scene, capped. At 2 s per scene the
# owner's 22-minute Glen Canyon video (167 lines) got 514 s and its parts
# delivered 3-6 clips each; at 4 s (~14 min) its parts were still busy at the
# deadline. 6 s per scene gives it ~20 minutes (GoMotion's own screen shows
# 24+ minutes on this step).
SOURCE_BUDGET_BASE_SECONDS = float(os.getenv("SOURCE_BUDGET_BASE_SECONDS", "180"))
SOURCE_BUDGET_PER_SCENE = float(os.getenv("SOURCE_BUDGET_PER_SCENE", "6"))
SOURCE_BUDGET_MAX_SECONDS = float(os.getenv("SOURCE_BUDGET_MAX_SECONDS", "1500"))
# The cap grows with the video (fanout.source_budget): never below
# SOURCE_BUDGET_MAX_PER_SCENE seconds a scene, never past the ceiling. The
# owner's 159-scene Lake Powell video (2026-10-01) hit the pod's flat
# 2400 s cap - the same 40 minutes a 100-scene video gets - and its last 23
# scenes in story order were left empty. 18 s a scene gives it ~48 minutes.
SOURCE_BUDGET_MAX_PER_SCENE = float(os.getenv("SOURCE_BUDGET_MAX_PER_SCENE", "18"))
SOURCE_BUDGET_CEILING_SECONDS = float(os.getenv("SOURCE_BUDGET_CEILING_SECONDS", "5400"))
# --- every scene filled, nothing shown twice (src/gapfill.py) -----------------
# The owner's rules (2026-10-01): never reuse a clip within a video, never
# leave a scene empty, every clip fits its own line. NO_REUSE switches off the
# old "reuse a shot from elsewhere in the story" fill (media.fill_from_story)
# and the render copy's borrowed shots. A fallback never takes a file, asset
# or moment another scene shows; another moment of a source video another
# scene shows only FALLBACK_MOMENT_GAP_SECONDS from its other moments, and
# never on the next scene.
NO_REUSE = _flag("NO_REUSE", True)
FALLBACK_MOMENT_GAP_SECONDS = float(os.getenv("FALLBACK_MOMENT_GAP_SECONDS", "30"))
# Scenes still empty when the sourcing budget is spent get the fast ladder:
# the clip library's unused clips of the line's subject or place, the subject
# pools' unused approved moments, one web/Wikimedia picture search (an AI
# image only when the job allows one), each through the usual gates. Its own
# time box (FALLBACK_SECONDS, plus FALLBACK_SECONDS_PER_SCENE a scene, at
# most FALLBACK_MAX_SECONDS) after the budget, FALLBACK_SCENE_SECONDS a
# scene, FALLBACK_PARALLEL at once. FALLBACK_STILLS=0 drops the picture step.
FALLBACK_FILL = _flag("FALLBACK_FILL", True)
FALLBACK_SECONDS = float(os.getenv("FALLBACK_SECONDS", "180"))
FALLBACK_SECONDS_PER_SCENE = float(os.getenv("FALLBACK_SECONDS_PER_SCENE", "6"))
# 2026-10-02: 600 s and 8 at a time left 97 of the Mount Rainier video's 138 empty scenes without
# a picture; the picture rung needs no proxy, so it can run wider and longer.
FALLBACK_MAX_SECONDS = float(os.getenv("FALLBACK_MAX_SECONDS", "900"))
FALLBACK_SCENE_SECONDS = float(os.getenv("FALLBACK_SCENE_SECONDS", "45"))
FALLBACK_PARALLEL = int(os.getenv("FALLBACK_PARALLEL", "16"))
FALLBACK_STILLS = _flag("FALLBACK_STILLS", True)
# The last resort for a scene nothing filled (never in the hook while
# anything else is possible): the planner's own number/map graphic for the
# line, else the neighbouring shot held over it (the scenes merge) while the
# clip still covers the longer scene at HOLD_MIN_RATE of its speed or more
# (0.6 = the renderer's own slow-down floor).
HOLD_MIN_RATE = float(os.getenv("HOLD_MIN_RATE", "0.85"))
# No shot of footage or still stays on screen longer than this (src/shotcap.py).
# The owner, 2026-10-04: "some of the clips are playing more than seven seconds
# on the timeline, fix that issue" - 132 of his Lake Mead video's 240 shots ran
# past 7 s (the cutter's own ceiling is MAX_SCENE_SECONDS, 9 s) and the 24
# shots held over an empty line averaged 11.3 s, up to 16.8 s. Before the
# shots are planned a longer beat is cut into 2+ shots on word boundaries, each
# sourced and judged like any beat; afterwards a neighbouring shot is held over
# an empty line only within the cap and never slowed to stretch (instead: a
# pick-a-shot runner-up, another moment of the clip beside it, the ladder, then
# the shot beside it held past the cap - real footage beats a text card - up
# to 12 s at real speed, and only then a text card; a cut piece that found
# nothing takes a runner-up of its own sentence before the ladder). Graphics,
# maps and animation scenes keep their own lengths. A video style may set its
# own (src/styles.py); never above 12 s (shotcap.CEILING). 0 = off: every plan
# exactly as before.
SHOT_MAX_SECONDS = float(os.getenv("SHOT_MAX_SECONDS", "7.0"))
# Saving good clips to the library: parallel uploads under one time box.
LIBRARY_SAVE_SECONDS = float(os.getenv("LIBRARY_SAVE_SECONDS", "90"))
# The editor's playback copies of each clip (the render uses the originals).
PREVIEW_WIDTH = int(os.getenv("PREVIEW_WIDTH", "1280"))
PREVIEW_CRF = int(os.getenv("PREVIEW_CRF", "24"))

# Split the render into frame chunks across the workers for longer videos.
FANOUT_RENDER = os.getenv("FANOUT_RENDER", "1") == "1"
FANOUT_RENDER_MIN_SECONDS = float(os.getenv("FANOUT_RENDER_MIN_SECONDS", "0"))
FANOUT_RENDER_CHUNK_SECONDS = float(os.getenv("FANOUT_RENDER_CHUNK_SECONDS", "90"))
# A candidate no vision model could judge is rejected (vision.acceptable).
ACCEPT_UNJUDGED = os.getenv("ACCEPT_UNJUDGED", "0").strip().lower() in ("1", "true", "yes")
# Sound effects on big animation moments (timeline.plan_sfx). SFX_VOLUME
# scales every sound (each already sits under the voice); 0.0 silences them.
# 0.2 = the owner, 2026-10-01, after the final Lake Powell video (master 0.5):
# "the transition SFX and the other SFX are too high ... around 20%". It is the
# one master for every sound: the cut sounds (sfx rows), the sounds built into
# the looks (lookSoundPlan) and the pack transitions' own sound (packLevels).
# 0.4 = the owner, 2026-10-02, after the Mount Rainier video at 0.2: "SFX sounds
# I can barely listen ... try to increase that as well" (with the music up to 50%).
SFX_ENABLED = os.getenv("SFX_ENABLED", "1").strip().lower() not in ("0", "false", "no")
SFX_VOLUME = float(os.getenv("SFX_VOLUME", "0.4"))
# The music bed's level when the job sets none (the editor's Music volume):
# flat under the whole video, x MUSIC_DUCK while a word is spoken - the owner's
# Lake Powell mix, "set to 20% music" (2026-10-01). The voice-relative
# automation (timeline.music_automation) put that bed at 60% under a loud
# narration. 0 = the automation. 0.5 = the owner, 2026-10-02: "the music sound
# is I think 20%. I think put it on fifty percent."
MUSIC_LEVEL = float(os.getenv("MUSIC_LEVEL", "0.5"))
MUSIC_DUCK = float(os.getenv("MUSIC_DUCK", "0.8"))
SFX_MIN_GAP_SECONDS = float(os.getenv("SFX_MIN_GAP_SECONDS", "45"))
# The finished video's loudness (integrated LUFS) and true-peak ceiling. YouTube
# plays at -14; GoMotion's Glen Canyon render measured -14.3 while the raw
# narration (and so our render) sat at -23.8. 0 turns the step off.
LOUDNESS_TARGET_LUFS = float(os.getenv("LOUDNESS_TARGET_LUFS", "-14"))
LOUDNESS_TRUE_PEAK = float(os.getenv("LOUDNESS_TRUE_PEAK", "-1.5"))
# Narration polish before every render (src/voicepolish.py): rumble/hum
# high-pass, denoise, de-ess, peak compression and level drift, each only when
# the narration measures as needing it (a clean recording is never denoised),
# at the original's loudness, length and timing; any failure keeps the
# original. A document's audio.polish false skips it for that video.
VOICE_POLISH = _flag("VOICE_POLISH", True)
# The whole polish (download, analysis, filters, checks) gives up after this.
VOICE_POLISH_SECONDS = float(os.getenv("VOICE_POLISH_SECONDS", "240"))
# One grade for the whole video (src/grade.py, drawn by the renderer's
# gradeMath.ts on every scene picture, never on graphics): each clip pulled
# toward the video's common exposure, saturation and colour cast
# (GRADE_NORMALIZE, from each scene's measured tone), then one gentle look
# (GRADE_PRESET: none, neutral, documentary, warm-doc, cool-news, archival) at
# GRADE_STRENGTH (0-1). GRADE=1 gives a plan or render without one the
# default; a document's own grade (the editor's) always wins.
GRADE = _flag("GRADE", True)
GRADE_PRESET = os.getenv("GRADE_PRESET", "documentary")
GRADE_STRENGTH = float(os.getenv("GRADE_STRENGTH", "1.0"))
GRADE_NORMALIZE = _flag("GRADE_NORMALIZE", True)
# Measuring the scenes' tone: the time box and the parallel reads.
GRADE_MEASURE_SECONDS = float(os.getenv("GRADE_MEASURE_SECONDS", "60"))
GRADE_MEASURE_WORKERS = int(os.getenv("GRADE_MEASURE_WORKERS", "8"))
# Ambience beds under the scenes that are somewhere (src/ambience.py, drawn by
# Main.tsx): wind, water, river, rain, storm, city, crowd, fire or machinery -
# synthesised loops in public/sfx (amb-*.mp3, scripts/build_ambience.py) -
# one at a time, faded at cuts, quiet under full-screen graphics,
# AMBIENCE_UNDER_VOICE_DB under the narration and ducked under its words.
# Planned with a new plan; a document's ambience {enabled, level} is the
# editor's switch and master. Off until the owner has listened: the beds are
# synthesised, and their levels, seams and split renders are measured but not
# yet heard (A/B one job with "config": {"AMBIENCE": 1, "RISERS": 1}).
AMBIENCE = _flag("AMBIENCE", False)
AMBIENCE_UNDER_VOICE_DB = float(os.getenv("AMBIENCE_UNDER_VOICE_DB", "26"))
# A soft swell (riser-soft) into the biggest reveals: section changes, chapter
# cards, big figures marked high - an sfx row of kind "riser" under the sfx master.
RISERS = _flag("RISERS", False)
# Picture quality of h264 renders (x264 CRF). Remotion's own default, 18, made
# ~13 Mbit/s at 1080p: a 22-minute render passed 2 GB and the app's storage
# (Lovable Cloud: 2 GB a file by default) refused it after the whole render.
# 21 was ~8 Mbit/s at 30 fps - but the owner renders at 60 fps, where 21 made
# 6.6 Mbit/s (Lake Powell, 2026-10-04), half of YouTube's 12 Mbit/s for
# 1080p60. Final videos go to Cloudflare R2, which has no per-file cap (the
# app-storage fallback still re-encodes to fit, render.fit_size), so 18 again:
# the owner, 2026-10-04: "we needed to make quality". 0 = Remotion's.
RENDER_CRF = int(os.getenv("RENDER_CRF", "18"))
# The largest file the app's storage takes. A render over it is re-encoded to
# fit before the upload (render.fit_size). 0 turns the check off.
UPLOAD_MAX_MB = float(os.getenv("UPLOAD_MAX_MB", "1900"))
# How long the final video's upload retries through an app outage (the broker
# says "job is not running" whenever the app's database cannot be read).
FINAL_UPLOAD_RETRY_SECONDS = float(os.getenv("FINAL_UPLOAD_RETRY_SECONDS", "900"))
# Pods only: where a copy of the finished video is kept for the owner's laptop
# (src/podfetch.py) - outside the job's work directory, which is deleted.
RENDER_KEEP_DIR = os.getenv("RENDER_KEEP_DIR", "")
# Scenes sourced at once. 8 suited the old 8-vCPU GPU pods; the 32-vCPU CPU
# workers carry 16 (the work is mostly waiting on network and vision calls).
SOURCE_WORKERS = int(os.getenv("SOURCE_WORKERS", "16"))
# Refuse to source a video with an empty AI account (handler._require_ai_credit).
REQUIRE_AI_CREDIT = os.getenv("REQUIRE_AI_CREDIT", "1").strip().lower() not in ("0", "false", "no")
MIN_AI_CREDIT = float(os.getenv("MIN_AI_CREDIT", "5"))
# Refuse to start sourcing when no connection can download from YouTube
# (every search still "works" from a blocked IP; the downloads fail and the
# gaps became paid AI images - two real videos got 0 YouTube clips).
REQUIRE_YOUTUBE = os.getenv("REQUIRE_YOUTUBE", "1").strip().lower() not in ("0", "false", "no")
# Include the worker's own IP in the YouTube route rotation (media._PROXIES).
YTDLP_DIRECT = os.getenv("YTDLP_DIRECT", "0").strip().lower() in ("1", "true", "yes")

# YouTube channels searched first, by story kind (media._story_channels).
# Archive channels hold newsreels and travelogues of every era; the news set
# holds footage of this week's floods and storms.
ARCHIVE_CHANNELS = [c.strip() for c in os.getenv(
    "ARCHIVE_CHANNELS",
    "@BritishPathe,@PeriscopeFilm,@APArchive,@HuntleyFilmArchives,@britishmovietone"
).split(",") if c.strip()]
NEWS_CHANNELS = [c.strip() for c in os.getenv(
    "NEWS_CHANNELS",
    # Wire services and weather networks, plus the agencies that film the
    # water crisis first-hand (Bureau of Reclamation runs Lake Mead) and the
    # Las Vegas station that covers it daily.
    "@Reuters,@AssociatedPress,@weatherchannel,@FOXWeather,@usbr,@8NewsNow,@USGS"
).split(",") if c.strip()]

# --- clip library (src/library.py) ------------------------------------------
# Every approved clip is kept, with its subject and description, and reused
# by later videos about the same subjects: no search, no download from
# YouTube, no vision call. Needs the worker-storage broker's library/ prefix.
CLIP_LIBRARY = _flag("CLIP_LIBRARY", True)
# A two-label contrast ("solid ground" vs "submerged mud") becomes a left/right
# split of two photos, one searched for each side (ProSplit), when both are found.
SPLIT_IMAGES = _flag("SPLIT_IMAGES", True)
SPLIT_IMAGES_SECONDS = float(os.getenv("SPLIT_IMAGES_SECONDS", "60"))
# A beat with no footage becomes a full-screen motion graphic chosen from the
# line (VidRush fills gaps with animations, not repeated clips).
ANIMATION_FILL = _flag("ANIMATION_FILL", True)
# A strong beat (figure, date, mapped place, quote) whose footage scored under
# this becomes an animation scene instead (treatments.wants_animation).
# A data beat that HAS footage keeps its clip and gets the graphic on top of
# it (the owner, 2026-09-28). On = the old rule: weak footage is replaced
# by a full-screen animation scene for the whole beat.
ANIMATION_OVER_FOOTAGE = _flag("ANIMATION_OVER_FOOTAGE", False)
# The owner wants 1080p-looking clips: a modern clip below this many lines is
# replaced (downloads already take the best format up to 1080p). Archive film
# (a title naming a year before 1990, a newsreel, Pathe...) may go down to
# MIN_ARCHIVE_HEIGHT - a 1936 newsreel only exists small. 720 since 2026-10-04
# (the owner: "video clips also we needed to make quality"; it was 480).
MIN_CLIP_HEIGHT = int(os.getenv("MIN_CLIP_HEIGHT", "720"))
# A photo's long side must be at least this (a full-frame still at 1080p; a
# Wikipedia "960px-" thumbnail passes). 0 turns the check off.
MIN_IMAGE_LONG_SIDE = int(os.getenv("MIN_IMAGE_LONG_SIDE", "900"))
MIN_ARCHIVE_HEIGHT = int(os.getenv("MIN_ARCHIVE_HEIGHT", "240"))
# Real detail, not file size (src/sharpness.py; the owner, 2026-10-04: "fix blur
# image issues", "images needed HD to 4K level"). The Lake Powell video showed
# 40 of its 141 pictures blown up past 1.6x though most were stored 1920 px wide:
# thumbnails, pages' upscaled copies and our own upscaler make big files of
# small pictures. PICTURE_SHARPNESS_CHECK: every picture is measured right
# after its download (the round trip: the smallest size it survives within 37 dB
# is its real detail) and is not used full screen when the screen would enlarge
# that detail more than MAX_PICTURE_MAGNIFICATION at the end of its Ken Burns
# move - 1.86 = 1.6 at rest x the planner's typical 1.16 move, about 1200 px of
# real detail across a landscape frame (a portrait picture needs that width:
# it is cropped to fill the frame). Calibrated on 25 Lake Powell pictures seen
# at 1:1: 1.86 flags 6 of the 8 blurry ones and none of the 17 soft-but-fine or
# sharp ones (101 of 141 pass); 1.45 (1.25 at rest) also flagged 7 of the 12
# soft-but-fine ones and left 58 of 141. Sourcing takes the next candidate,
# footage or the fallback ladder instead; searches ask for big pictures first;
# the quality gate replaces such a picture before the render when the ladder
# finds a sharper shot, else the picture stays. Never an inset on a backdrop.
PICTURE_SHARPNESS_CHECK = _flag("PICTURE_SHARPNESS_CHECK", True)
MAX_PICTURE_MAGNIFICATION = float(os.getenv("MAX_PICTURE_MAGNIFICATION", "1.86"))
# CLIP_SHARPNESS_CHECK: up to three frames of every downloaded clip are measured
# the same way, before any vision call; a modern clip whose best frame holds
# under MIN_CLIP_REAL_HEIGHT lines of real detail (an upscaled upload, whatever
# its file says - a 480p upload re-encoded at 1080p reads ~410) is turned down,
# in sourcing, in the ladder (packs, library, spare moments) and by the quality
# gate. Archive film is exempt (MIN_ARCHIVE_HEIGHT).
CLIP_SHARPNESS_CHECK = _flag("CLIP_SHARPNESS_CHECK", True)
MIN_CLIP_REAL_HEIGHT = int(os.getenv("MIN_CLIP_REAL_HEIGHT", "720"))

# --- local vision + upscaling (CPU, no API) -----------------------------------
# CLIP (ONNX, baked into the image under /opt/models) judges every candidate
# before Gemini: slides, text pages, cartoons/games, logos and a portrait on a
# place beat are rejected on the spot, and when every Gemini model is busy the
# local verdict decides instead of the title alone.
LOCAL_VISION_ENABLED = _flag("LOCAL_VISION_ENABLED", True)
LOCAL_VISION_DIR = os.getenv("LOCAL_VISION_DIR", "/opt/models/clip-vit-base-patch16")
LOCAL_VISION_THREADS = int(os.getenv("LOCAL_VISION_THREADS", "4"))
# Cosine similarity (CLIP B/16) of a frame to "a photo of <intent>" below
# which a candidate is off-topic when no remote model can judge it.
LOCAL_VISION_MIN_RELEVANCE = float(os.getenv("LOCAL_VISION_MIN_RELEVANCE", "0.215"))
# Share of the frames' class probability that makes a hard reject.
LOCAL_VISION_REJECT_SHARE = float(os.getenv("LOCAL_VISION_REJECT_SHARE", "0.80"))
# Real-ESRGAN general x4v3 (ONNX): a photo whose long side is under
# UPSCALE_BELOW is upscaled to UPSCALE_TARGET before render; clips under
# UPSCALE_CLIP_BELOW lines get a Lanczos + sharpen pass to 1080p.
UPSCALE_ENABLED = _flag("UPSCALE_ENABLED", True)
UPSCALE_MODEL = os.getenv("UPSCALE_MODEL", "/opt/models/real_esrgan_general_x4v3.onnx")
UPSCALE_BELOW = int(os.getenv("UPSCALE_BELOW", "1600"))
UPSCALE_TARGET = int(os.getenv("UPSCALE_TARGET", "1920"))
UPSCALE_CLIP_BELOW = int(os.getenv("UPSCALE_CLIP_BELOW", "900"))
UPSCALE_SECONDS = float(os.getenv("UPSCALE_SECONDS", "180"))
UPSCALE_PARALLEL = int(os.getenv("UPSCALE_PARALLEL", "4"))
# With the upscaler, a photo this small is still usable (it is upscaled 2-4x
# with real detail instead of blown up blurry).
MIN_IMAGE_LONG_SIDE_UPSCALED = int(os.getenv("MIN_IMAGE_LONG_SIDE_UPSCALED", "640"))
# Smart reframing (src/reframe.py): a slow push toward the subject (faces,
# what stands out, the action) on a locked-off shot, and stills aimed at their
# subject - the owner, 2026-10-01: "it feels hand-edited". Detection is
# CPU-only and time-boxed (REFRAME_SECONDS for the whole video, REFRAME_PARALLEL
# scenes at once); no move above REFRAME_MAX_SCALE, none on a shot shorter than
# REFRAME_MIN_SECONDS, and about REFRAME_SHARE of the shots that could move do.
# Off by default: on the owner-approved Lake Powell video it found no footage
# that may move (80 of 87 clips already move, the rest are news, burned-in
# text, too soft or all subject) and aimed 6 of 65 stills - better on most,
# not yet "clearly better" (scratchpad reframe_eval/evidence). A job turns it
# on with config {"REFRAME_ENABLED": true}.
REFRAME_ENABLED = _flag("REFRAME_ENABLED", False)
# Auto maps (src/automaps.py): a river, lake, reservoir, dam or canal the narration names is drawn on real
# geography (the river along its true course, the reservoir's outline, the dam where it stands), from the
# geodata bundled in src/geodata. Off by default until the owner has seen the stills; a job turns it on with
# config {"AUTO_MAPS": true}.
AUTO_MAPS = _flag("AUTO_MAPS", False)
# Seconds an auto map keeps from any other map before it, so maps never crowd the cut.
AUTO_MAP_GAP = float(os.getenv("AUTO_MAP_GAP", "15"))
# On-screen sources (src/sources.py): a line that states a fact and NAMES where it comes from ("according to the
# Bureau of Reclamation", "USGS data shows", "a 2024 NOAA report found") gets a small citation tag in a low corner
# for about three seconds: "SOURCE: USBR, 2024". Only what the narration itself says (or the brief's own sources
# list) - never a guessed source, never a guessed year; a figure with no named source gets no tag. Off by default
# until the owner has approved the look from its stills; a job turns it on with config {"SOURCE_TAGS": true}.
SOURCE_TAGS = _flag("SOURCE_TAGS", False)
# At most one source tag per SOURCE_TAG_GAP seconds, none in the first SOURCE_TAG_FIRST_SECONDS of the video,
# each on screen about SOURCE_TAG_SECONDS.
SOURCE_TAG_GAP = float(os.getenv("SOURCE_TAG_GAP", "30"))
SOURCE_TAG_FIRST_SECONDS = float(os.getenv("SOURCE_TAG_FIRST_SECONDS", "5"))
SOURCE_TAG_SECONDS = float(os.getenv("SOURCE_TAG_SECONDS", "3"))
# Footage moves and still aiming separately (the news styles keep their
# clips as shot: src/styles.py).
REFRAME_CLIPS = _flag("REFRAME_CLIPS", True)
REFRAME_STILLS = _flag("REFRAME_STILLS", True)
REFRAME_SECONDS = float(os.getenv("REFRAME_SECONDS", "75"))
REFRAME_PARALLEL = int(os.getenv("REFRAME_PARALLEL", "8"))
REFRAME_MAX_SCALE = float(os.getenv("REFRAME_MAX_SCALE", "1.15"))
REFRAME_MIN_SECONDS = float(os.getenv("REFRAME_MIN_SECONDS", "3.0"))
REFRAME_SHARE = float(os.getenv("REFRAME_SHARE", "0.6"))
REFRAME_MIN_CONFIDENCE = float(os.getenv("REFRAME_MIN_CONFIDENCE", "0.45"))
# YuNet face detector (OpenCV Zoo, MIT, 230 KB ONNX) and U2-Net-p salient-object
# maps (Apache-2.0, 4.6 MB ONNX); both baked in by scripts/fetch_models.py.
FACE_MODEL = os.getenv("FACE_MODEL", "/opt/models/face_detection_yunet_2023mar.onnx")
SALIENCY_MODEL = os.getenv("SALIENCY_MODEL", "/opt/models/u2netp.onnx")
# Vertical / square phone video (news-compilation styles, src/styles.py):
# accepted and framed on a blurred copy of itself before render, the way news
# compilation channels show TikTok/X clips. The sharp band keeps the middle
# VERTICAL_BAND_ASPECT (width/height) of the clip, trimming platform
# captions and UI at the top and bottom.
ALLOW_VERTICAL = _flag("ALLOW_VERTICAL", False)
# Official public-domain imagery for stories about today's weather: the live
# NOAA GOES satellite loop of the story's region (src/official.py).
OFFICIAL_IMAGERY = _flag("OFFICIAL_IMAGERY", True)
# Cloudflare R2 for finished videos (src/r2.py): no 2 GB file cap, no
# download fees. All five set = the final video goes to R2 first.
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "").strip()
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "").strip()
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
R2_BUCKET = os.getenv("R2_BUCKET", "").strip()
R2_PUBLIC_BASE = os.getenv("R2_PUBLIC_BASE", "").strip()
# SerpApi (Google Images and Yandex Images) as the backup picture search when
# the free searches come back empty. The plan has a monthly quota (250 on the
# free plan), so each video may spend at most SERPAPI_MAX_PER_JOB searches.
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY", "").strip()
SERPAPI_MAX_PER_JOB = int(os.getenv("SERPAPI_MAX_PER_JOB", "30"))
# Google Videos through SerpApi: a few
# per video so the free plan's 250 searches a month last (2026-10-01).
SERPAPI_VIDEO_MAX_PER_JOB = int(os.getenv("SERPAPI_VIDEO_MAX_PER_JOB", "8"))
# Yandex Images as a picture source after Google/Bing (media.search_yandex_images).
ALLOW_YANDEX_IMAGES = _flag("ALLOW_YANDEX_IMAGES", True)
# The picture sources' order and reach (src/providers.py). Measured 2026-10-04 on
# Yellowstone searches (free sources, the worker's own size, real-detail and AI
# checks): usable - Wikimedia Commons 23 of 30, the web search 24 of 54, Yandex
# 21 of 80, Openverse 0 of 24 (it serves Flickr's 1024 px copies, never sharp
# full screen); Commons answers the short wordings of a line, not its long one.
# COMMONS_BEFORE_YANDEX: Commons is asked before Yandex.
# OPENVERSE_WHEN_SHARP: Openverse is asked while PICTURE_SHARPNESS_CHECK is on.
# STILLS_ALL_WORDINGS_FIRST: a still line asks every wording of its search (its
# own, its intent's, the relaxed ones) for pictures before footage stands in for
# it (YouTube / Dailymotion for stills), and an illustration comes last of all.
# Off: each wording walked pictures, footage and an illustration before the next.
COMMONS_BEFORE_YANDEX = _flag("COMMONS_BEFORE_YANDEX", True)
OPENVERSE_WHEN_SHARP = _flag("OPENVERSE_WHEN_SHARP", False)
STILLS_ALL_WORDINGS_FIRST = _flag("STILLS_ALL_WORDINGS_FIRST", True)
# Set per job by the video style (src/styles.py): how busy the overlay planner
# is ("minimal" | "normal" | "rich") and the transition rhythm
# ("documentary" | "energetic" | "crossfade"). "" = the planner's defaults.
GRAPHICS_DENSITY = os.getenv("GRAPHICS_DENSITY", "").strip().lower()
TRANSITION_STYLE = os.getenv("TRANSITION_STYLE", "").strip().lower()
# The owner's overlay transition pack (remotion/public/transitions, 2026-10-01):
# a few chosen cuts get a screen-blended film burn / leak / flash / glitch with
# its own sound (timeline.plan_pack_transitions; per-style rhythm in
# styles.PACK_TRANSITIONS). Off: the planned cuts stay as they were.
TRANSITION_PACK = _flag("TRANSITION_PACK", True)
VERTICAL_BAND_ASPECT = float(os.getenv("VERTICAL_BAND_ASPECT", "0.8"))
ANIMATION_OVER_FOOTAGE_BELOW = float(os.getenv("ANIMATION_OVER_FOOTAGE_BELOW", "0.6"))
CLIP_LIBRARY_MIN_SCORE = float(os.getenv("CLIP_LIBRARY_MIN_SCORE", "0.8"))
CLIP_LIBRARY_MAX_PER_JOB = int(os.getenv("CLIP_LIBRARY_MAX_PER_JOB", "60"))
STRAGGLER_GRACE_SECONDS = float(os.getenv("STRAGGLER_GRACE_SECONDS", "75"))
SEQUENCE_BUDGET_SECONDS = float(os.getenv("SEQUENCE_BUDGET_SECONDS", "180"))

RENDER_CONCURRENCY = int(os.getenv("RENDER_CONCURRENCY", "4"))
# See render.render: the defaults size these from the host, not the container.
RENDER_FRAME_CACHE_BYTES = int(os.getenv("RENDER_FRAME_CACHE_BYTES", str(1536 * 1024 * 1024)))
RENDER_VIDEO_THREADS = int(os.getenv("RENDER_VIDEO_THREADS", "1"))
# Satellite maps load public tiles (USGS, NASA GIBS) at render time; one slow
# tile past Remotion's 30 s default killed a whole render. Long enough for
# a retried fetch, short enough that a dead tile server still fails the job.
RENDER_DELAY_TIMEOUT_MS = int(os.getenv("RENDER_DELAY_TIMEOUT_MS", "120000"))

# --- how long one render may run (src/render.py render_timeout) ------------------
# A render's time limit follows its frames and this machine. It was a flat 90
# minutes: a 29-minute video (52,000 frames) rendered whole on one 16-vCPU
# worker drew ~7 frames a second and was killed at 55% after 5400 s with
# nothing saved (2026-10-03). The speed is estimated as RENDER_FPS_PER_TAB
# frames a second for every browser tab the render runs (its concurrency, never
# more than the CPUs this container may use; measured 0.58 on that worker, kept
# lower here so a slow machine is not cut short). The limit is the estimate x
# RENDER_TIMEOUT_FACTOR + RENDER_TIMEOUT_BASE_SECONDS, never under ..._MIN and
# never over ..._MAX (the upper bound: no render runs longer than that).
RENDER_FPS_PER_TAB = float(os.getenv("RENDER_FPS_PER_TAB", "0.45"))
RENDER_TIMEOUT_FACTOR = float(os.getenv("RENDER_TIMEOUT_FACTOR", "1.5"))
RENDER_TIMEOUT_BASE_SECONDS = float(os.getenv("RENDER_TIMEOUT_BASE_SECONDS", "600"))
RENDER_TIMEOUT_MIN_SECONDS = float(os.getenv("RENDER_TIMEOUT_MIN_SECONDS", "1800"))
RENDER_TIMEOUT_MAX_SECONDS = float(os.getenv("RENDER_TIMEOUT_MAX_SECONDS", "14400"))
# CPUs this container may use; 0 = read the container's own limit (render.cpus).
RENDER_CPUS = int(os.getenv("RENDER_CPUS", "0"))
# A render that says nothing at all for this long while its frames are being
# drawn is hung: it is stopped with a clear error instead of sitting until its
# time limit. (Not once every frame is drawn: a long video's sound is mixed
# without a line of output.) 0 = off.
RENDER_STALL_SECONDS = float(os.getenv("RENDER_STALL_SECONDS", "900"))

# --- render speed (src/render.py; measured 2026-10-01) ---------------------------
# x264 preset of every h264 render. Remotion's default, medium, encodes beside
# the browser tabs and took ~16% of the machine: veryfast is 2.3x faster at the
# same CRF with the same picture (SSIM 0.9805 vs 0.9814) and a 7% smaller file.
# "" = Remotion's default.
RENDER_X264_PRESET = os.getenv("RENDER_X264_PRESET", "veryfast").strip().lower()
# The sound is rendered as lossless WAV beside a picture-only MP4 and encoded
# to AAC once, loudness included, when the two are joined (render.finalize).
# Remotion's own AAC played 42.7 ms behind the picture. 0 = the old way.
RENDER_SEPARATE_AUDIO = _flag("RENDER_SEPARATE_AUDIO", True)
# Build the Remotion bundle once per machine and code version and render from
# it (render.ensure_bundle) instead of bundling + copying public/ per render.
RENDER_PREBUNDLE = _flag("RENDER_PREBUNDLE", True)
RENDER_BUNDLE_DIR = os.getenv("RENDER_BUNDLE_DIR", "").strip()
RENDER_BUNDLE_TIMEOUT = int(os.getenv("RENDER_BUNDLE_TIMEOUT", "600"))

# --- one pod's render spread over the serverless workers (src/fanout.py render_pod)
# The pod cuts the finished timeline into POD_RENDER_CHUNKS frame ranges at clean
# scene cuts (no crossfade, no cut transition and no sound effect across them),
# renders one itself and queues the rest as "render_chunk" jobs on
# POD_RENDER_ENDPOINT_ID (the serverless endpoint; needs FANOUT_API_KEY and R2).
# Each worker renders its range - picture and that range's slice of the sound
# as WAV - from the scene media's public R2 links and hands both back through
# R2 (POD_RENDER_PREFIX). The pod joins the pictures without re-encoding, the
# sound slices sample-exactly, and encodes the sound once (render.finalize).
# Any chunk that fails, times out or is still queued when the pod is free is
# rendered on the pod; a slow one is raced by a copy on the pod. On by
# default: rendered chunks travel only through Cloudflare R2, never the app's
# Supabase storage (whose broker stalls lost four chunks on 2026-10-04).
# Videos shorter than POD_RENDER_MIN_SECONDS stay whole.
POD_RENDER_FANOUT = _flag("POD_RENDER_FANOUT", True)
POD_RENDER_CHUNKS = int(os.getenv("POD_RENDER_CHUNKS", "12"))
POD_RENDER_MIN_SECONDS = float(os.getenv("POD_RENDER_MIN_SECONDS", "90"))
# No chunk shorter than this many frames (a chunk's start-up costs ~30-45 s).
POD_RENDER_MIN_CHUNK_FRAMES = int(os.getenv("POD_RENDER_MIN_CHUNK_FRAMES", "900"))
POD_RENDER_ENDPOINT_ID = os.getenv("POD_RENDER_ENDPOINT_ID", "").strip() or FANOUT_ENDPOINT_ID
# A chunk no worker has started this long after it was queued is rendered on
# the pod as soon as the pod is free (RunPod wakes stopped workers slowly).
POD_RENDER_QUEUE_GRACE_SECONDS = float(os.getenv("POD_RENDER_QUEUE_GRACE_SECONDS", "45"))
# A worker's chunk is given up (and rendered on the pod) after this long.
POD_RENDER_CHUNK_TIMEOUT_SECONDS = float(os.getenv("POD_RENDER_CHUNK_TIMEOUT_SECONDS", "1800"))
# The whole spread render; past it every unfinished chunk is rendered on the pod.
POD_RENDER_TIMEOUT_SECONDS = float(os.getenv("POD_RENDER_TIMEOUT_SECONDS", "3600"))
# Race a copy of the slowest worker chunk on the pod once it has nothing else to do.
POD_RENDER_SPECULATE = _flag("POD_RENDER_SPECULATE", True)
POD_RENDER_PREFIX = os.getenv("POD_RENDER_PREFIX", "chunks/").strip()
# Keep the chunk files in R2 after the join (debugging); normally deleted.
POD_RENDER_KEEP_CHUNKS = _flag("POD_RENDER_KEEP_CHUNKS", False)
# RunPod job policy on each chunk (executionTimeout/ttl): a pod that dies never
# leaves a chunk running or queued for long. 0 = no policy.
POD_RENDER_JOB_POLICY = _flag("POD_RENDER_JOB_POLICY", True)

# --- whisper -----------------------------------------------------------------
# "base" is the sweet spot for narration alignment on CPU; bump to "small" on GPU.
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto")

# --- render defaults ---------------------------------------------------------
DEFAULT_FPS = int(os.getenv("DEFAULT_FPS", "30"))
DEFAULT_WIDTH = int(os.getenv("DEFAULT_WIDTH", "1920"))
DEFAULT_HEIGHT = int(os.getenv("DEFAULT_HEIGHT", "1080"))

# Scene pacing, measured from a finished GoMotion project (197 clips, 22:59):
# 8.7 cuts/min, median clip 7.00s, and 92% of clips inside a 6.5-7.5s band.
# That is a near-uniform ~7s grid, not one visual per spoken clause.
#
# This replaces the earlier VidRush-derived defaults (2.6s target, 16.8-21.8
# cuts/min). Both were measured from real output; they are simply different
# house styles, and the slower one is the one Mahesh judged good.
#
# Halving the cut rate also halves the clip count for a given runtime — ~191
# instead of ~430 for a 21-minute video — which halves sourcing time, proxy
# bandwidth, and how often a poorly-matched clip appears. Set these back to
# 1.4 / 2.6 / 5.0 for the faster VidRush cutting.
# Base footage grade. Sourced clips come from different cameras, decades and
# upload qualities, so one shared grade is what makes them cut together as a
# single film. Era beats override it (director.pick_treatment). "none" is a
# clean passthrough.
# "none" by default: modern footage is shown as shot, bright and full colour.
# Era beats still get the light vintage/archival grade (director.pick_treatment).
SCENE_TREATMENT = os.getenv("SCENE_TREATMENT", "none").strip().lower()
# Music from the renderer's bundled tracks when a job names none (timeline._bgm_for).
BGM_AUTO = _flag("BGM_AUTO", True)
# A benchmark render returned inline in the job result (handler do_render).
RETURN_VIDEO_MAX_MB = float(os.getenv("RETURN_VIDEO_MAX_MB", "18"))
# The visual treatment planner (src/treatments.py) and the style pack a video
# uses when the job does not name one ("" = chosen from the story's kind).
TREATMENTS = _flag("TREATMENTS", True)
STYLE_PACK = os.getenv("STYLE_PACK", "").strip().lower()
# GoMotion's persistent figure (Glen Canyon, 2026-09-29): the compact ring
# or number riding on a clip stays up across the short cuts that follow it
# ("22% OF CAPACITY REMAINING" rode three consecutive shots) instead of
# leaving with its own sentence. A following scene must be shorter than
# PERSIST_SCENE_MAX seconds, the whole run stays under PERSIST_MAX_SECONDS,
# and the graphic never crosses another overlay, an animation scene or a
# full-screen graphic (treatments._persist_figures).
PERSIST_FIGURES = _flag("PERSIST_FIGURES", True)
PERSIST_SCENE_MAX = float(os.getenv("PERSIST_SCENE_MAX", "4.5"))
# 8 s since 2026-09-30 (was 12): the owner, "don't keep it longer".
PERSIST_MAX_SECONDS = float(os.getenv("PERSIST_MAX_SECONDS", "8"))

# VidRush's pacing, measured on four of their exports (first 8 min each):
# median shot 3.3-3.7 s, middle half 2.3-5.2 s, 13.6-16.5 cuts/min, only
# 2-10% of shots over 8 s. The earlier 5/7/9 (GoMotion's ~7 s) cut half as
# often. Set 5/7/9 again for the slower GoMotion feel.
MIN_SCENE_SECONDS = float(os.getenv("MIN_SCENE_SECONDS", "5.0"))
TARGET_SCENE_SECONDS = float(os.getenv("TARGET_SCENE_SECONDS", "7.0"))
MAX_SCENE_SECONDS = float(os.getenv("MAX_SCENE_SECONDS", "9.0"))

# Contact address used in the User-Agent for Wikimedia/Nominatim, both of which
# require identifying your client in their terms of use.
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "karnalamahesh810@gmail.com")
USER_AGENT = f"ThumbGenius/2.0 (video worker; contact: {CONTACT_EMAIL})"

# --- footage library on Cloudflare R2 (src/libstore.py, src/library.py) -------
# The library's own bucket ("thumbgenius-library") and its public r2.dev or
# custom domain. Both set (with the R2_* keys above) = approved clips and
# photos are kept there instead of the app's storage and read straight from
# the public URL. R2_LIBRARY_PREFIX puts every key under a folder ("library/"
# when the library has to share R2_BUCKET).
R2_LIBRARY_BUCKET = os.getenv("R2_LIBRARY_BUCKET", "").strip()
R2_LIBRARY_PUBLIC_BASE = os.getenv("R2_LIBRARY_PUBLIC_BASE", "").strip()
R2_LIBRARY_PREFIX = os.getenv("R2_LIBRARY_PREFIX", "").strip()
# Each scene's clip, preview and thumbnail go to R2_BUCKET under a public,
# link-only name (no storage reference, so nothing re-signs them) instead of
# the app's video-media bucket. On whenever R2 is configured; 0 = app storage
# (only with R2_ONLY off too: Cloudflare-only keeps them in R2 either way, under
# the same public link - a saved timeline never carries a link that expires).
R2_SCENE_MEDIA = _flag("R2_SCENE_MEDIA", True)
# Every file this worker stores goes to Cloudflare R2 (R2_BUCKET) once R2 is
# configured: scene media, render chunks, parts' clips, the library and the
# final video - the app's Supabase storage is never written, not even as a
# fallback (its broker stalls lost a render on 2026-10-04). Files already in
# Supabase can still be read. Without R2 credentials this has no effect.
R2_ONLY = _flag("R2_ONLY", True)
R2_MEDIA_UPLOAD_SECONDS = float(os.getenv("R2_MEDIA_UPLOAD_SECONDS", "120"))
# --- restore / repair missing media (src/restore.py, action "restore_media") --
# A project whose stored files vanished is put back under the same links,
# without planning again (two R2 project folders were deleted by hand on
# 2026-10-04 and their timelines pointed at nothing). The time box of one
# restore job and how many files it works on at once; a job's own "seconds"
# and "parallel" win. What is not restored in time is restored by the next run.
RESTORE_SECONDS = float(os.getenv("RESTORE_SECONDS", "1500"))
RESTORE_PARALLEL = int(os.getenv("RESTORE_PARALLEL", "8"))
# A part's copy that cannot be checked against the timeline (no tone, no
# ledger hash, no clip length) may be an earlier pick the plan replaced - a
# duplicate or a shot that failed a check. Off: it is not used, the shot is
# fetched again from its source or left to the render's quality check.
RESTORE_UNVERIFIED = _flag("RESTORE_UNVERIFIED", False)
# Approved photos are kept too (never a generated image), when their long
# side is at least LIBRARY_IMAGE_MIN_SIDE.
LIBRARY_IMAGES = _flag("LIBRARY_IMAGES", True)
# Every clip and picture a finished video shows also goes into the app's library
# (library.record_shown), for the owner to see and pick by hand; never auto-reused.
LIBRARY_SHOWN = _flag("LIBRARY_SHOWN", True)
LIBRARY_IMAGE_MIN_SIDE = int(os.getenv("LIBRARY_IMAGE_MIN_SIDE", "1280"))
# The library's quality gate (libstore.check_clip). Not kept (an old row is
# marked removed, reversibly): shorter than LIBRARY_MIN_SECONDS, smaller than
# LIBRARY_MIN_WIDTH x LIBRARY_MIN_HEIGHT, vertical or framed on a blurred copy,
# mostly black, frozen, letter/pillarboxed (bars over LIBRARY_MAX_BARS of the
# frame), a slideshow of stills, burned-in graphics over LIBRARY_MAX_TEXT_SHARE
# of the frame, softer than LIBRARY_MIN_SHARPNESS, CLIP relevance to its own
# subject under LIBRARY_MIN_CLIP_RELEVANCE, or within LIBRARY_DUP_BITS of the
# perceptual hash of a clip the library already keeps.
LIBRARY_MIN_SECONDS = float(os.getenv("LIBRARY_MIN_SECONDS", "3.0"))
LIBRARY_MIN_WIDTH = int(os.getenv("LIBRARY_MIN_WIDTH", "1280"))
LIBRARY_MIN_HEIGHT = int(os.getenv("LIBRARY_MIN_HEIGHT", "720"))
LIBRARY_MAX_BARS = float(os.getenv("LIBRARY_MAX_BARS", "0.2"))
LIBRARY_MAX_TEXT_SHARE = float(os.getenv("LIBRARY_MAX_TEXT_SHARE", "0.25"))
LIBRARY_MIN_SHARPNESS = float(os.getenv("LIBRARY_MIN_SHARPNESS", "12"))
LIBRARY_MIN_CLIP_RELEVANCE = float(os.getenv("LIBRARY_MIN_CLIP_RELEVANCE", str(LOCAL_VISION_MIN_RELEVANCE)))
LIBRARY_DUP_BITS = int(os.getenv("LIBRARY_DUP_BITS", "10"))
# Old rows (clips in the app's storage) are checked and moved to R2 by a
# background pass started with each plan/build job: at most
# LIBRARY_MAINTENANCE_MAX rows within LIBRARY_MAINTENANCE_SECONDS.
LIBRARY_MAINTENANCE = _flag("LIBRARY_MAINTENANCE", True)
LIBRARY_MAINTENANCE_SECONDS = float(os.getenv("LIBRARY_MAINTENANCE_SECONDS", "60"))
LIBRARY_MAINTENANCE_MAX = int(os.getenv("LIBRARY_MAINTENANCE_MAX", "25"))
# A current news story prefers library clips recorded within this many days
# and never takes one dated to another year.
LIBRARY_FRESH_DAYS = int(os.getenv("LIBRARY_FRESH_DAYS", "45"))

# --- human-like cuts (src/transcribe.py) ----------------------------------------
# The owner (2026-09-30): "7 s max, but clips don't all need to be 7 s - cut
# based on the narration like a human editor." On: every beat ends where an
# editor would cut (a sentence end, a clause break or breath, a new named
# place or person, a number or danger word that needs its proof shot), its
# length follows what it says (an intense line near CUT_FAST_SECONDS, an
# establishing one near CUT_SLOW_SECONDS, the rest near TARGET_SCENE_SECONDS),
# MIN_SCENE_SECONDS and MAX_SCENE_SECONDS bound its time ON SCREEN (the pause
# after its last word included), and the opening HOOK_SECONDS cut
# CUT_HOOK_FACTOR faster. 0 = the old clause rhythm around TARGET (kept for A/B).
HUMAN_CUTS = _flag("HUMAN_CUTS", True)
# 0 = derived from TARGET_SCENE_SECONDS (x0.65 and x1.3, inside MIN..MAX).
CUT_FAST_SECONDS = float(os.getenv("CUT_FAST_SECONDS", "0"))
CUT_SLOW_SECONDS = float(os.getenv("CUT_SLOW_SECONDS", "0"))
CUT_HOOK_FACTOR = float(os.getenv("CUT_HOOK_FACTOR", "0.85"))

# --- no reuse across videos (src/ledger.py) ---------------------------------------
# The owner (2026-09-30): "the same clip was literally used in the previous
# video." Every moment, photo and library clip a finished video used is
# recorded in the library bucket (ledger/). For CROSS_VIDEO_REUSE_DAYS no
# video shows a moment of the same source video that overlaps a used one or
# starts within CROSS_VIDEO_GAP_SECONDS of it, nor a photo whose URL or
# perceptual hash (within LEDGER_PHOTO_BITS of 64) matches. 0 days = off.
CROSS_VIDEO_REUSE_DAYS = int(os.getenv("CROSS_VIDEO_REUSE_DAYS", "120"))
CROSS_VIDEO_GAP_SECONDS = float(os.getenv("CROSS_VIDEO_GAP_SECONDS", "30"))
LEDGER_PHOTO_BITS = int(os.getenv("LEDGER_PHOTO_BITS", "6"))
# The ledger is read in the background from the job's start; sourcing waits
# for it at most this long after that (then goes on with what was read).
LEDGER_LOAD_SECONDS = float(os.getenv("LEDGER_LOAD_SECONDS", "8"))
LEDGER_PREFIX = os.getenv("LEDGER_PREFIX", "ledger/").strip()
# A finishing job rewrites ledger/index.json when at least this many job
# files are not in it yet.
LEDGER_COMPACT_EVERY = int(os.getenv("LEDGER_COMPACT_EVERY", "10"))
# With the ledger on, the clip library keeps each job's approved moments that
# the video did NOT use - the runner-up clips judges passed and the subject
# pools' spare moments (at most LIBRARY_SPARES_MAX of those, downloaded for
# it) - instead of the clips the video showed, which the ledger now keeps out
# of later videos anyway. Off = keep the used clips as before.
LIBRARY_SAVE_UNUSED = _flag("LIBRARY_SAVE_UNUSED", True)
LIBRARY_SPARES_MAX = int(os.getenv("LIBRARY_SPARES_MAX", "16"))

# --- the Nature & Weather edit (src/styles.py: nature_weather) -------------------
# Per job through the video style; all off by default.
# EYEWITNESS_SEARCHES: every line's searches name the place it mentions and
# the event, the way eyewitness uploads are titled ("Atlantic City flooding
# video", "Long Beach Island storm surge footage"), and phone, drone,
# storm-chaser and news-helicopter titles rank ahead (a compilation behind).
EYEWITNESS_SEARCHES = _flag("EYEWITNESS_SEARCHES", False)
# COMING_SHOTS: a forward-looking line ("tonight", "the worst is still to
# come", "brace for...") shows what is coming - storm clouds rolling in, a
# shelf cloud, a rain curtain, the radar or the live satellite loop.
COMING_SHOTS = _flag("COMING_SHOTS", False)
# HOOK_INTENSITY: the opening asks for the most dramatic real footage of the
# event (water over roads and seawalls, cars in water, waves, rescues).
HOOK_INTENSITY = _flag("HOOK_INTENSITY", False)
# HOOK_BOOST (src/hookboost.py): the first HOOK_BOOST_SECONDS cut and dressed
# like a top documentary's opening. Before the shots are planned, a beat there
# longer than HOOK_BOOST_SPLIT_OVER is cut into 2-3 shots of HOOK_BOOST_MIN_SHOT
# to HOOK_BOOST_MAX_SHOT seconds on word boundaries, each sourced and judged like
# any beat; the hook's picks lean toward footage that moves and shows scale,
# people and action (HOOK_BOOST_MOTION, HOOK_BOOST_DRAMA - bounded, relevance
# still leads); stills and static clips get a slow push-in; the first
# HOOK_BOOST_SFX_CUTS cuts get a soft whoosh at the owner's sound level; no text
# graphic in the first HOOK_BOOST_QUIET_SECONDS unless it is a date or number the
# planner must show. Off = the video is cut exactly as before.
HOOK_BOOST = _flag("HOOK_BOOST", False)
HOOK_BOOST_SECONDS = float(os.getenv("HOOK_BOOST_SECONDS", "30"))
HOOK_BOOST_SPLIT_OVER = float(os.getenv("HOOK_BOOST_SPLIT_OVER", "3.5"))
HOOK_BOOST_MIN_SHOT = float(os.getenv("HOOK_BOOST_MIN_SHOT", "1.8"))
HOOK_BOOST_MAX_SHOT = float(os.getenv("HOOK_BOOST_MAX_SHOT", "3.0"))
HOOK_BOOST_MOTION = float(os.getenv("HOOK_BOOST_MOTION", "0.04"))
HOOK_BOOST_DRAMA = float(os.getenv("HOOK_BOOST_DRAMA", "0.05"))
HOOK_BOOST_QUIET_SECONDS = float(os.getenv("HOOK_BOOST_QUIET_SECONDS", "5"))
HOOK_BOOST_SFX_CUTS = int(os.getenv("HOOK_BOOST_SFX_CUTS", "3"))
# HOOK_TEASER: a cold open - HOOK_TEASER_SHOTS one-second flashes of the video's
# most striking LATER shots under the first line, only when that line is a hook
# question or statement. A flashed shot shows again at its own line (that is the
# point of a teaser) and nowhere else. Off by default.
HOOK_TEASER = _flag("HOOK_TEASER", False)
HOOK_TEASER_SHOTS = int(os.getenv("HOOK_TEASER_SHOTS", "3"))
HOOK_TEASER_SECONDS = float(os.getenv("HOOK_TEASER_SECONDS", "1.0"))
# MOTION_PREFERENCE: weight of measured on-screen motion (4 frames at 160 px of
# the cut clip) in picking between clips that passed the judge; a frozen
# shot or a slideshow is turned down. Doubled in the hook. 0 = off.
MOTION_PREFERENCE = float(os.getenv("MOTION_PREFERENCE", "0"))
# PHOTO_MAX_PER_10MIN: real photos per 10 minutes of video (the planner's
# photo beats, and footage beats that fall back to a photo); 0 = no cap.
PHOTO_MAX_PER_10MIN = float(os.getenv("PHOTO_MAX_PER_10MIN", "0"))

# REGION_BLOCKS: a line is searched in the region the narration is in (the
# story's first place until "Down in North Carolina" / "Now let's head to
# Delaware" turns it), a line naming its own town keeps the town. The
# reference channel matched regions, not every town name.
REGION_BLOCKS = _flag("REGION_BLOCKS", False)
# CHAIN_SHOTS: a footage beat that carries on the previous beat's sentence
# about the same place plays the next moment of that beat's clip (a long take
# cut forward, at most CHAIN_MAX beats; one source for the variety rules).
CHAIN_SHOTS = _flag("CHAIN_SHOTS", False)
CHAIN_MAX = int(os.getenv("CHAIN_MAX", "3"))
# A beat that starts a new sentence is cut this many seconds before its first
# word, in the breath (the reference: 0.14 s); never before the last word of
# the beat in front of it. 0 = on the word.
CUT_LEAD_SECONDS = float(os.getenv("CUT_LEAD_SECONDS", "0"))

# --- AI slop and not-footage (src/slop.py, the owner's Texas test 2026-09-30) ---
# Every candidate video and photo, in every style: AI-made or painted pictures
# (titles and tags naming an AI generator, the local CLIP model, the judge's
# ai_generated answer), a still or slideshow posing as footage, another
# creator's burned-in captions, a TV studio, presenter, streamer or TV weather
# map. 0 = off (A/B only).
AI_SLOP_FILTER = _flag("AI_SLOP_FILTER", True)

# --- stock-agency and watermarked pictures (src/stockblock.py, the owner 2026-10-04) ---
# "the images it is using are sometimes watermarked images, like Getty ...
# Alamy ... fix that". STOCK_BLOCK: a picture whose address, page, thumbnail
# or title names a stock agency (Alamy, Getty, iStock, Shutterstock,
# Dreamstime, Depositphotos, 123RF, Adobe Stock...) is skipped before any
# download, on every path. STOCK_BLOCK_FILE_NAMES: so is an agency's picture
# re-published elsewhere under its file name ("GettyImages-1325430438.jpg" on
# a news site: licensed to them, not to this channel). STOCK_BLOCK_WORDS: and
# a listing by its title words ("... Stock Photo - Alamy", "Editorial use only").
STOCK_BLOCK = _flag("STOCK_BLOCK", True)
STOCK_BLOCK_FILE_NAMES = _flag("STOCK_BLOCK_FILE_NAMES", True)
STOCK_BLOCK_WORDS = _flag("STOCK_BLOCK_WORDS", True)
# WATERMARK_CHECK: every downloaded picture's own pixels are read before it may
# be placed, judged by the vision model or not: an agency's credit bar along
# the bottom edge (free; no clean picture of 267 measured had one), and, on a
# picture about to be kept, its name stamped on the picture or a tile of it,
# read by the local CLIP model at WATERMARK_CLIP_SHARE or more (0 = the stamp
# check off). Measured 2026-10-04 on 102 stamped agency previews and 267 clean
# pictures (the Lake Mead video's own, Wikimedia, and a held-out set heavy in
# documents and newspapers): bar + stamp at 0.75 turn down 74 of the 102 and 5
# of the 267 (1.9 %); the first prompts at 0.8 turned down 17 (6.4 %). With
# the storm / sea / sky prompts (review, same day): still 74 of the 102, 2 of
# the 267, and 10 of 352 clean weather pictures (29 without them).
WATERMARK_CHECK = _flag("WATERMARK_CHECK", True)
WATERMARK_CLIP_SHARE = float(os.getenv("WATERMARK_CLIP_SHARE", "0.75"))
# STOCK_GATE_REPAIR: the quality gate also replaces a stock-agency picture it
# finds on a timeline built BEFORE this block (a render of an older project).
# On (the owner, 2026-10-04: no Getty / Alamy pictures in his videos - his two
# restored videos were built before the block): replaced like a broken scene,
# through the ladder, never left empty. Off: those renders keep their pictures.
STOCK_GATE_REPAIR = _flag("STOCK_GATE_REPAIR", True)
# A subject pool's moment is rated on storyboard tiles only; on = each pooled
# clip also goes through the vision judge against its own line (the news and
# weather styles: a chyron naming another town is only readable full size).
POOL_JUDGE_CLIPS = _flag("POOL_JUDGE_CLIPS", False)

# --- the quality gate (src/quality.py, the owner's rule 2026-10-01) ------------
# QUALITY_GATE: before every render (build and render actions) every scene,
# picture and sound of the document the renderer will draw is checked - media
# present, the file reachable, a clip long enough to cover its scene, a still
# that decodes and is not tiny, no repeats, every overlay picture loadable -
# and whatever fails is repaired through the fallback ladder (src/gapfill.py).
QUALITY_GATE = _flag("QUALITY_GATE", True)
# QUALITY_SCAN: the finished file is scanned (ffmpeg blackdetect, freezedetect,
# silencedetect); a real defect is repaired and the video drawn once more
# (QUALITY_RERENDER), the better file kept. Never more than one re-render.
QUALITY_SCAN = _flag("QUALITY_SCAN", True)
QUALITY_RERENDER = _flag("QUALITY_RERENDER", True)
# Checks run QUALITY_PARALLEL at a time, each request QUALITY_HTTP_TIMEOUT s,
# all of them inside QUALITY_AUDIT_SECONDS (what is still out then is trusted).
QUALITY_PARALLEL = int(os.getenv("QUALITY_PARALLEL", "16"))
QUALITY_HTTP_TIMEOUT = float(os.getenv("QUALITY_HTTP_TIMEOUT", "12"))
QUALITY_AUDIT_SECONDS = float(os.getenv("QUALITY_AUDIT_SECONDS", "90"))
# The ladder's own time box for the scenes the gate repairs, and per scene.
QUALITY_REPAIR_SECONDS = float(os.getenv("QUALITY_REPAIR_SECONDS", "150"))
QUALITY_REPAIR_SCENE_SECONDS = float(os.getenv("QUALITY_REPAIR_SCENE_SECONDS", "45"))
# A repair may ask the image model for a picture (paid) only when this is on.
QUALITY_REPAIR_GENERATED = _flag("QUALITY_REPAIR_GENERATED", False)
# A still whose long side is under this many pixels is too small to show.
QUALITY_MIN_IMAGE_SIDE = int(os.getenv("QUALITY_MIN_IMAGE_SIDE", "320"))
# The real-detail check of the gate (PICTURE_SHARPNESS_CHECK, CLIP_SHARPNESS_CHECK):
# every full-screen picture and clip of the document is measured within this
# many seconds (QUALITY_PARALLEL at a time; a clip on storage is read by three
# seeks, never downloaded whole). What is not measured in time is trusted. The
# blurry ones are replaced from the ladder within what is left of
# QUALITY_REPAIR_SECONDS after the broken scenes, at least QUALITY_SHARPEN_MIN_SECONDS.
QUALITY_SHARPNESS_SECONDS = float(os.getenv("QUALITY_SHARPNESS_SECONDS", "45"))
QUALITY_SHARPEN_MIN_SECONDS = float(os.getenv("QUALITY_SHARPEN_MIN_SECONDS", "60"))
# When more than this share of the scenes' own clips and pictures cannot be read
# from storage (and at least QUALITY_MISSING_MIN of them), the render stops
# before a frame is drawn with an error that says so - the project's files were
# deleted, or storage is down - instead of "repairing" most of the video into
# text cards (2026-10-04: a project's media was deleted from R2 mid-render).
# 0 = always repair.
QUALITY_MISSING_SHARE = float(os.getenv("QUALITY_MISSING_SHARE", "0.3"))
QUALITY_MISSING_MIN = int(os.getenv("QUALITY_MISSING_MIN", "3"))
# Many files with no clear answer from storage (timeouts, 5xx, rate limits -
# never a plain 404) are asked once more after this pause before anything is
# repaired or the render is stopped: a short outage is waited out. 0 = off.
QUALITY_RETRY_PAUSE_SECONDS = float(os.getenv("QUALITY_RETRY_PAUSE_SECONDS", "15"))
# The scan: black for QUALITY_BLACK_SECONDS or more, a picture frozen for
# QUALITY_FREEZE_SECONDS or more, silence of QUALITY_SILENCE_SECONDS or more.
QUALITY_BLACK_SECONDS = float(os.getenv("QUALITY_BLACK_SECONDS", "0.5"))
QUALITY_FREEZE_SECONDS = float(os.getenv("QUALITY_FREEZE_SECONDS", "0.8"))
QUALITY_SILENCE_SECONDS = float(os.getenv("QUALITY_SILENCE_SECONDS", "4"))
QUALITY_SCAN_TIMEOUT = float(os.getenv("QUALITY_SCAN_TIMEOUT", "900"))

# --- the AI review (src/review.py; the owner, 2026-10-02: "AI review also good
# for me, if you can build that better") -----------------------------------------
# AI_REVIEW: after the render a vision model looks at the FINISHED video scene
# by scene (one frame a scene, a few scenes a call) against the narration and
# catches what the quality gate cannot see: a clip that does not fit its line,
# a stock agency's watermark, a blurry or AI-looking picture, one of our own
# titles over a face, a shot that feels repeated - and the sound is measured
# for music as loud as the voice, dead air and clipping. Off until one real
# video has been reviewed with it and the owner has seen the report.
AI_REVIEW = _flag("AI_REVIEW", False)
# AI_REVIEW_FIX: what it can fix safely it fixes (a scene's own already-judged
# other choice swapped in, a title moved off a face) and the video is drawn
# once more - the quality gate's one second render, never a third. Off = the
# review only lists what it found.
AI_REVIEW_FIX = _flag("AI_REVIEW_FIX", True)
# The sound checks need no model (ffmpeg only); they only ever list.
AI_REVIEW_AUDIO = _flag("AI_REVIEW_AUDIO", True)
# Scenes shown to the model per call (4-6: fewer wastes calls, more and the
# answers get careless), the most calls one video may make and how many run at
# once. AI_REVIEW_SECONDS is the WHOLE review - frames, model calls, sound and
# fixes (the second render it may ask for is not part of it): what is not done
# by then is reported as not checked or not fixed, never a failed render and
# never a finished video held up for long. Measured on the owner's real
# 29-minute Lake Mead video (16 cores, a stand-in model): 280 scenes, frames
# and sound in 34 s. Prices (OpenRouter google/gemini-2.5-flash, list $0.30/M
# in, $2.50/M out): ~2,500 tokens in (258 a frame) and ~110 out for a call of
# 5 scenes = ~$0.001, so a 20-minute video (~200 scenes, 40 calls) ~$0.05.
AI_REVIEW_GROUP = int(os.getenv("AI_REVIEW_GROUP", "5"))
AI_REVIEW_MAX_CALLS = int(os.getenv("AI_REVIEW_MAX_CALLS", "60"))
AI_REVIEW_PARALLEL = int(os.getenv("AI_REVIEW_PARALLEL", "6"))
AI_REVIEW_SECONDS = float(os.getenv("AI_REVIEW_SECONDS", "300"))
# A picture the model scores under this against its line does not fit it
# (the judge's own floor for a new clip is VISION_MIN_SCORE 0.70; the review
# sees the finished frame with our graphics on it, so it is asked for less).
AI_REVIEW_MIN_MATCH = float(os.getenv("AI_REVIEW_MIN_MATCH", "0.45"))
# A review that wants to replace more than this share of the scenes it saw is
# more likely wrong than the video: nothing is swapped, everything is listed.
AI_REVIEW_MAX_FIX_SHARE = float(os.getenv("AI_REVIEW_MAX_FIX_SHARE", "0.3"))


def _job_max_seconds() -> float:
    """JOB_MAX_SECONDS when set; else this machine's own job limit (see below); 0 = none known."""
    try:
        raw = os.getenv("JOB_MAX_SECONDS", "").strip()
        if raw:
            return max(0.0, float(raw))
        if os.getenv("RUNPOD_WEBHOOK_GET_JOB"):             # a serverless worker (handler.Reporter.SERVERLESS)
            return 10800.0
        pod = os.getenv("POD_MAX_SECONDS", "").strip()      # read the way scripts/pod_job.py reads it
        if pod:
            return max(0.0, float(pod))
        return 18000.0 if os.getenv("POD_EXIT") == "terminate" else 0.0
    except ValueError:
        return 0.0                                          # a malformed value: no known limit


# The longest one job may run before it is stopped from outside, with nothing
# saved: the serverless endpoint's executionTimeout (3 h on tuxcziwby5plod,
# README "Endpoint configuration") or, on the app's pods, scripts/pod_job.py's
# own watchdog (POD_MAX_SECONDS, 5 h). 0 = no known limit (a laptop, a test).
# The AI review's second render reads it: it is drawn only when it can still
# finish in what is left - the first render's own time x
# AI_REVIEW_RENDER_FACTOR, plus AI_REVIEW_RENDER_RESERVE_SECONDS for its scan,
# the upload and saving the clips after it. Otherwise the review only lists and
# the first video goes out. (A second render the quality gate draws for its
# own repairs is not held to it; the review's fixes join that one for free.)
JOB_MAX_SECONDS = _job_max_seconds()
AI_REVIEW_RENDER_FACTOR = float(os.getenv("AI_REVIEW_RENDER_FACTOR", "1.25"))
AI_REVIEW_RENDER_RESERVE_SECONDS = float(os.getenv("AI_REVIEW_RENDER_RESERVE_SECONDS", "900"))

# --- niche footage packs (src/packs.py, src/packbuild.py) ----------------------
# A shelf of pre-checked clips per niche (water, weather, fire, earth, nature,
# cities) kept on R2 and read by their public link: the owner's rule "no empty
# scenes, every clip fits its own line" (2026-10-01) answered with footage that
# is already cut, checked and reachable. PACKS_FILL = the fallback ladder's
# first rung (src/gapfill.py): a scene still empty after the footage search
# takes a pack clip whose CLIP picture fits its line. PACKS_FIRST = pack clips
# are tried before any search for the lines they fit best (off: sourcing is
# unchanged). PACKS_NICHES forces the niches ("water,nature"); empty = read
# them off the story and the line. PACKS_PUBLIC_BASE is where packs are read
# from (default: the footage library's public domain); PACKS_DIR reads them
# from a local folder instead (a pack build's --local-dir output).
PACKS_FILL = _flag("PACKS_FILL", True)
PACKS_FIRST = _flag("PACKS_FIRST", False)
PACKS_NICHES = os.getenv("PACKS_NICHES", "").strip()
PACKS_PUBLIC_BASE = os.getenv("PACKS_PUBLIC_BASE", "").strip()
PACKS_PREFIX = os.getenv("PACKS_PREFIX", "packs/").strip()
PACKS_DIR = os.getenv("PACKS_DIR", "").strip()
# A manifest is kept in memory this long (a missing one is not asked again for a minute).
PACKS_CACHE_SECONDS = float(os.getenv("PACKS_CACHE_SECONDS", "600"))
# The least CLIP cosine (B/16: ~0.15 off-topic, ~0.32 exact) between a line and a
# clip for the clip to be used at all. A line that names its own event or place
# (specificity "event"/"location" and not generic_ok) needs PACKS_SPECIFIC_EXTRA
# more: a general clip proves little about an exact place.
PACKS_MIN_SIMILARITY = float(os.getenv("PACKS_MIN_SIMILARITY", "0.25"))
PACKS_FIRST_MIN_SIMILARITY = float(os.getenv("PACKS_FIRST_MIN_SIMILARITY", "0.29"))
PACKS_SPECIFIC_EXTRA = float(os.getenv("PACKS_SPECIFIC_EXTRA", "0.03"))
# Ranking only (never lets a clip under the minimum in): a clip whose topics
# share words with the line gains up to this much.
PACKS_TOPIC_BONUS = float(os.getenv("PACKS_TOPIC_BONUS", "0.02"))
# Licence classes a job may take: pd, cc0, cc-by, cc-by-sa (the author and licence
# go on the clip) and unverified (a clip from the owner's own library, the
# licence posture of every library clip). "pd,cc0" = nothing to credit.
PACKS_LICENSES = os.getenv("PACKS_LICENSES", "pd,cc0,cc-by,cc-by-sa,unverified").strip().lower()
# PACKS_FIRST never takes more than this share of a video's lines, and never the hook.
PACKS_FIRST_MAX_SHARE = float(os.getenv("PACKS_FIRST_MAX_SHARE", "0.35"))
PACKS_FIRST_SECONDS = float(os.getenv("PACKS_FIRST_SECONDS", "90"))
# Building a pack (src/packbuild.py): a source video is skipped over
# PACKS_MAX_SOURCE_MB or PACKS_MAX_SOURCE_SECONDS, cut into segments of
# PACKS_SEGMENT_MIN..PACKS_SEGMENT_MAX seconds (PACKS_MAX_PER_SOURCE at most from
# one source video), a topic keeps at most PACKS_TOPIC_QUOTA clips, and a clip
# whose best topic is under PACKS_TOPIC_MIN_SIMILARITY is not about the niche.
PACKS_MAX_SOURCE_MB = float(os.getenv("PACKS_MAX_SOURCE_MB", "400"))
PACKS_MAX_SOURCE_SECONDS = float(os.getenv("PACKS_MAX_SOURCE_SECONDS", "1200"))
PACKS_SEGMENT_MIN = float(os.getenv("PACKS_SEGMENT_MIN", "4"))
PACKS_SEGMENT_MAX = float(os.getenv("PACKS_SEGMENT_MAX", "10"))
PACKS_MAX_PER_SOURCE = int(os.getenv("PACKS_MAX_PER_SOURCE", "6"))
PACKS_TOPIC_QUOTA = int(os.getenv("PACKS_TOPIC_QUOTA", "40"))
PACKS_TOPIC_MIN_SIMILARITY = float(os.getenv("PACKS_TOPIC_MIN_SIMILARITY", "0.23"))

# --- script -> narration with a free, self-hosted voice (src/tts.py) -----------
# The owner's flow (2026-08-14): "just paste script, select voice over or
# directly upload audio, and make video". A job that carries a script and no
# audio_url has its narration made here, by a voice endpoint of our own
# (runpod/tts_server: Kokoro, Apache-2.0; Chatterbox, MIT, which clones a voice
# from a 10-30 s sample) - no per-character bill, only the GPU seconds it runs.
# Premium voices stay in the app and still arrive as audio_url.
# TTS_API_BASE empty = off: a script-only job is refused with a clear message.
#   an OpenAI-compatible server : https://<host>        (POST /v1/audio/speech)
#   a RunPod queue endpoint     : https://api.runpod.ai/v2/<endpoint id>  (/runsync)
# TTS_API_MODE "auto" tells the two apart by the address; "openai" / "runpod" force one.
TTS_API_BASE = os.getenv("TTS_API_BASE", "").strip().rstrip("/")
TTS_API_KEY = os.getenv("TTS_API_KEY", "").strip()
TTS_API_MODE = os.getenv("TTS_API_MODE", "auto").strip().lower()
# The engine and the voice when the job names none (a job may send tts_model,
# tts_voice, tts_speed, tts_reference_audio). af_heart is Kokoro's best-graded
# voice; am_michael and bm_george are its documentary men.
TTS_MODEL = os.getenv("TTS_MODEL", "kokoro").strip()
TTS_VOICE = os.getenv("TTS_VOICE", "af_heart").strip()
TTS_SPEED = float(os.getenv("TTS_SPEED", "1.0"))
# Voice cloning (Chatterbox): a 10-30 s sample of the voice - a link, or a file
# on this worker. Only ever a voice the owner has the right to use.
TTS_REFERENCE_AUDIO = os.getenv("TTS_REFERENCE_AUDIO", "").strip()
# Another server may call a field something else: TTS_FIELDS renames ours
# ({"reference_audio": "speaker_wav", "input": "text"}) and TTS_EXTRA adds
# fields to every request ({"exaggeration": 0.4, "cfg_weight": 0.5}). Both JSON.
TTS_FIELDS = os.getenv("TTS_FIELDS", "").strip()
TTS_EXTRA = os.getenv("TTS_EXTRA", "").strip()
# What each part comes back as (lossless and small: a 100 s part is ~2.5 MB,
# far under RunPod's 20 MB answer limit) and what the narration is stored as.
TTS_FORMAT = os.getenv("TTS_FORMAT", "flac").strip().lower()
TTS_OUTPUT_FORMAT = os.getenv("TTS_OUTPUT_FORMAT", "mp3").strip().lower()
# A long script is cut at sentence ends into parts of at most this many
# characters (~100 s of speech), TTS_WORKERS of them voiced at once.
TTS_CHUNK_CHARS = int(os.getenv("TTS_CHUNK_CHARS", "1500"))
TTS_WORKERS = int(os.getenv("TTS_WORKERS", "4"))
# One part: seconds before it is given up (a cold GPU worker loads its model
# first) and how many times it is asked again after a failure.
TTS_TIMEOUT = float(os.getenv("TTS_TIMEOUT", "600"))
TTS_RETRIES = int(os.getenv("TTS_RETRIES", "3"))
# The whole narration - every part, retry and cold start - within this many
# seconds (0 = no limit). Kokoro voices a 30-minute script in a few minutes
# even from cold workers; Chatterbox needs ~10-15 minutes on 4 GPUs. Past it
# the job stops with a plain message instead of running into its own time
# limit (3 h on the serverless endpoint, POD_MAX_SECONDS on a pod).
TTS_TOTAL_SECONDS = float(os.getenv("TTS_TOTAL_SECONDS", "1800"))
# The breath between two parts (they always meet at a sentence end).
TTS_GAP_SECONDS = float(os.getenv("TTS_GAP_SECONDS", "0.3"))
# The narration's loudness (integrated LUFS). 0 = where the worker's measured
# narrations sit and its sounds are planned against (sfxplan.VOICE_LUFS_DEFAULT, -20).
TTS_LUFS = float(os.getenv("TTS_LUFS", "0"))
# A script longer than this is refused (about two hours of speech).
TTS_MAX_CHARS = int(os.getenv("TTS_MAX_CHARS", "120000"))
