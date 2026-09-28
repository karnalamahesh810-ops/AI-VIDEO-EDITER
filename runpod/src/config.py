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
# Retries per model on a transient failure (timeout, 5xx, 429), before the
# fallback model is tried, and the pause before each.
VISION_RETRIES = int(os.getenv("VISION_RETRIES", "1"))
VISION_RETRY_WAIT = float(os.getenv("VISION_RETRY_WAIT", "2"))
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
# Non-YouTube videos from Google's video search (TikTok, Facebook, Vimeo,
# news sites), downloaded by yt-dlp. Only when the job is not youtube_only.
ALLOW_WEB_VIDEO = _flag("ALLOW_WEB_VIDEO", True)
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
# Google Images via Bright Data's SERP API (tried first when set).
BRIGHTDATA_API_KEY = os.getenv("BRIGHTDATA_API_KEY", "")
BRIGHTDATA_SERP_ZONE = os.getenv("BRIGHTDATA_SERP_ZONE", "serp_api1")

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
# scales every sound (each already sits at 20-35%); 0.0 silences them.
SFX_ENABLED = os.getenv("SFX_ENABLED", "1").strip().lower() not in ("0", "false", "no")
SFX_VOLUME = float(os.getenv("SFX_VOLUME", "1.0"))
SFX_MIN_GAP_SECONDS = float(os.getenv("SFX_MIN_GAP_SECONDS", "45"))
# The finished video's loudness (integrated LUFS) and true-peak ceiling. YouTube
# plays at -14; GoMotion's Glen Canyon render measured -14.3 while the raw
# narration (and so our render) sat at -23.8. 0 turns the step off.
LOUDNESS_TARGET_LUFS = float(os.getenv("LOUDNESS_TARGET_LUFS", "-14"))
LOUDNESS_TRUE_PEAK = float(os.getenv("LOUDNESS_TRUE_PEAK", "-1.5"))
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
# MIN_ARCHIVE_HEIGHT - a 1936 newsreel only exists small.
MIN_CLIP_HEIGHT = int(os.getenv("MIN_CLIP_HEIGHT", "480"))
MIN_ARCHIVE_HEIGHT = int(os.getenv("MIN_ARCHIVE_HEIGHT", "240"))
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
PERSIST_MAX_SECONDS = float(os.getenv("PERSIST_MAX_SECONDS", "12"))

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
