"""Runtime configuration, read from RunPod endpoint environment variables."""
import os

# --- media source keys (set these as RunPod endpoint env vars) ---------------
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "")

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
