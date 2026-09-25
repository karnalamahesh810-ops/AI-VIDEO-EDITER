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

# yt-dlp can also present browser cookies, which helps with the same check.
YTDLP_COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE", "").strip()

# Cap on concurrent yt-dlp subprocesses (search, metadata, download combined).
# Scene-level sourcing (6 workers) x moment-scouting (MOMENT_PARALLEL, 3) can
# ask for up to 18 requests at once; with only a handful of proxy IPs that is
# real oversubscription, not real speed - contended proxies just queue and
# time out, which reads as "sourcing is slow" with nothing to explain why.
# Default tracks the proxy pool (one request per healthy IP), floor of 4 so
# an unproxied dev box still gets some parallelism.
NETWORK_CONCURRENCY = int(os.getenv("NETWORK_CONCURRENCY", "0")) or max(4, 2 * len(YTDLP_PROXIES))

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
# Tried in order if DIRECTOR_MODEL fails or times out. Verified working
# through this key: 19s for a text plan call, 7.7s for a vision call, both
# via https://api.kie.ai/v1 with "model" in the body (no per-model path
# needed, unlike vision.py's endpoint). Empty entries are skipped.
DIRECTOR_FALLBACK_MODELS = [m.strip() for m in
                           os.getenv("DIRECTOR_FALLBACK_MODELS", "gemini-3-pro").split(",")
                           if m.strip()]

# --- vision verification -----------------------------------------------------
# Every candidate clip/image is shown to a multimodal model, which describes
# what is actually in the frames and scores it against the shot's intent.
# Below VISION_MIN_SCORE it is rejected and the next candidate is tried. 0.70
# is VidRush's own floor: across 325 scored items on one of their timelines the
# minimum was exactly 0.70. Defaults reuse the director's key, so a Kie key
# configured once powers both.
VISION_ENABLED = _flag("VISION_ENABLED", True)
VISION_API_BASE = os.getenv("VISION_API_BASE", "") or DIRECTOR_API_BASE or "https://api.kie.ai/v1"
VISION_API_KEY = (os.getenv("VISION_API_KEY", "") or DIRECTOR_API_KEY
                  or os.getenv("KIE_API_KEY", ""))
# gpt-5-2 is the model verified to accept images on the Kie account (Gemini
# Flash answers "channel is not supported" there).
VISION_MODEL = os.getenv("VISION_MODEL", "gpt-5-2")
VISION_FALLBACK_MODELS = [m.strip() for m in
                          os.getenv("VISION_FALLBACK_MODELS", "gemini-3-pro").split(",")
                          if m.strip()]
VISION_MIN_SCORE = float(os.getenv("VISION_MIN_SCORE", "0.70"))
# gpt-5-2 reasons before it answers. Measured on one real clip check: 32.5 s
# at the default effort, 13.5 s at "low", same verdict (0.97 vs 0.98);
# "minimal" is refused (code 500). Sent to gpt-* models only. Empty = default.
VISION_REASONING_EFFORT = os.getenv("VISION_REASONING_EFFORT", "low").strip()
VISION_FRAMES = int(os.getenv("VISION_FRAMES", "3"))
# Candidates judged per search before giving up on that query. Each judged
# candidate costs one model call, so this bounds spend per scene.
VISION_MAX_CANDIDATES = int(os.getenv("VISION_MAX_CANDIDATES", "3"))

# Moment selection: read the video's storyboard (YouTube's hover-preview
# thumbnails, ~1/sec, a few hundred KB) and let the vision model pick the
# timestamp that shows the intent, instead of cutting at a fixed 35%.
# Wall-clock cap on the second sourcing pass (repeats, rejected and empty
# scenes). Attempts in flight finish; no new ones start after it.
REPLACE_BUDGET_SECONDS = int(os.getenv("REPLACE_BUDGET_SECONDS", "240"))
# Wall-clock cap on the AI-rescue pass for scenes still empty after pass 2.
RESCUE_BUDGET_SECONDS = int(os.getenv("RESCUE_BUDGET_SECONDS", "180"))
MOMENT_SELECTION = _flag("MOMENT_SELECTION", True)
MOMENT_TILES = int(os.getenv("MOMENT_TILES", "20"))
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
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")

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
RENDER_CONCURRENCY = int(os.getenv("RENDER_CONCURRENCY", "4"))

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
SCENE_TREATMENT = os.getenv("SCENE_TREATMENT", "film").strip().lower()

# VidRush's pacing, measured on four of their exports (first 8 min each):
# median shot 3.3-3.7 s, middle half 2.3-5.2 s, 13.6-16.5 cuts/min, only
# 2-10% of shots over 8 s. The earlier 5/7/9 (GoMotion's ~7 s) cut half as
# often. Set 5/7/9 again for the slower GoMotion feel.
MIN_SCENE_SECONDS = float(os.getenv("MIN_SCENE_SECONDS", "2.0"))
TARGET_SCENE_SECONDS = float(os.getenv("TARGET_SCENE_SECONDS", "3.4"))
MAX_SCENE_SECONDS = float(os.getenv("MAX_SCENE_SECONDS", "6.0"))

# Contact address used in the User-Agent for Wikimedia/Nominatim, both of which
# require identifying your client in their terms of use.
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "karnalamahesh810@gmail.com")
USER_AGENT = f"ThumbGenius/2.0 (video worker; contact: {CONTACT_EMAIL})"
