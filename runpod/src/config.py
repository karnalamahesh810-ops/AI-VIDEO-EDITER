"""Runtime configuration, read from RunPod endpoint environment variables."""
import os


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

# Scene pacing. These defaults are measured from the VidRush reference renders
# (4 videos, 240s sample each): 16.8-21.8 cuts/min, median shot 2.56-3.33s,
# ~70% of shots land in the 2-4s band. One visual per spoken clause.
# MIN is deliberately below 2s: ~20-29% of reference shots are sub-2s punches.
MIN_SCENE_SECONDS = float(os.getenv("MIN_SCENE_SECONDS", "1.4"))
TARGET_SCENE_SECONDS = float(os.getenv("TARGET_SCENE_SECONDS", "2.6"))
MAX_SCENE_SECONDS = float(os.getenv("MAX_SCENE_SECONDS", "5.0"))

# Contact address used in the User-Agent for Wikimedia/Nominatim, both of which
# require identifying your client in their terms of use.
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "karnalamahesh810@gmail.com")
USER_AGENT = f"ThumbGenius/2.0 (video worker; contact: {CONTACT_EMAIL})"
