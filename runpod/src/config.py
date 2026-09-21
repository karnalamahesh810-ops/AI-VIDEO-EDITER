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

# YouTube footage. require_cc keeps sourcing to uploads published under
# Creative Commons Attribution — the only footage you may legally re-cut and
# monetise. Everything else is someone's reserved copyright and Content ID food.
ALLOW_YOUTUBE = _flag("ALLOW_YOUTUBE", True)
REQUIRE_CC = _flag("REQUIRE_CC", True)

# Residential proxy for yt-dlp. NOT optional on RunPod: serverless workers get
# datacenter IPs, and YouTube answers those with "Sign in to confirm you're not
# a bot", so sourcing that works perfectly on a home connection returns nothing
# at all in production. A handful of residential proxies is enough for one
# channel's throughput.
#
# Accepts one proxy or a comma-separated list, which is rotated per request so
# a single address does not absorb every download and get flagged.
# Format: http://user:pass@host:port (or socks5://...).
YTDLP_PROXY = os.getenv("YTDLP_PROXY", "").strip()
YTDLP_PROXIES = [p.strip() for p in YTDLP_PROXY.split(",") if p.strip()]

# yt-dlp can also present browser cookies, which helps with the same check.
YTDLP_COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE", "").strip()

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

# --- supabase storage --------------------------------------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "renders")

# --- paths -------------------------------------------------------------------
WORK_DIR = os.getenv("WORK_DIR", "/tmp/work")
REMOTION_DIR = os.getenv("REMOTION_DIR", "/app/remotion")

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

MIN_SCENE_SECONDS = float(os.getenv("MIN_SCENE_SECONDS", "5.0"))
TARGET_SCENE_SECONDS = float(os.getenv("TARGET_SCENE_SECONDS", "7.0"))
MAX_SCENE_SECONDS = float(os.getenv("MAX_SCENE_SECONDS", "9.0"))

# Contact address used in the User-Agent for Wikimedia/Nominatim, both of which
# require identifying your client in their terms of use.
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "karnalamahesh810@gmail.com")
USER_AGENT = f"ThumbGenius/2.0 (video worker; contact: {CONTACT_EMAIL})"
