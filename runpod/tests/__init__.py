"""Test package.

Set before src.config is imported: the suite asserts how the worker behaves
when a variable is NOT set, so it must not inherit a developer's local .env.
"""
import os

os.environ["SKIP_DOTENV"] = "1"

# Network sources added later are off for the offline suite: an unmocked
# Dailymotion or Archive.org search inside a sourcing test turned a one-minute
# run into seventeen minutes of real downloads.
os.environ.setdefault("ALLOW_DAILYMOTION", "0")
os.environ.setdefault("ALLOW_ARCHIVE_ORG", "0")
# The narration polish downloads a render's narration before drawing it; the
# render tests' documents point at made-up links. tests/test_voice_polish.py
# switches it on around its own local files.
os.environ.setdefault("VOICE_POLISH", "0")
# The grade measures each scene's picture before a render, reading remote
# ones by their link: the suite's documents point at made-up links. No time
# for it here; tests/test_grade.py gives its own measurements a budget.
os.environ.setdefault("GRADE_MEASURE_SECONDS", "0")
# The real-detail checks (src/sharpness.py) would call every synthetic still and
# clip of the suite - 160x90 test patterns - too soft for the frame: off here,
# so the suite also proves that with them off nothing changes. tests/test_sharpness.py
# switches them on around its own pictures and clips.
os.environ.setdefault("PICTURE_SHARPNESS_CHECK", "0")
os.environ.setdefault("CLIP_SHARPNESS_CHECK", "0")
# A clip-first line reads its candidates' YouTube metadata before scouting
# (media._prequalified, CLIP_PREQUALIFY): a full yt-dlp extraction per
# candidate, which an unmocked sourcing test would run against YouTube. Off
# here; tests/test_clips_first.py switches it on around its own stubs.
os.environ.setdefault("CLIP_PREQUALIFY", "0")
# Vision's base when nothing names one is OpenRouter since Kie was turned off (2026-10-07), and an OpenRouter
# base reads the account's balance before it hedges (credit.openrouter_left: a real request). The suite's model
# calls are mocked: a neutral base keeps it offline, as Kie's old default did. Tests about OpenRouter or Kie set
# their own base (and KIE_ENABLED for Kie).
os.environ.setdefault("VISION_API_BASE", "https://vision.invalid/v1")
# A plan or build refuses to start under OPENROUTER_MIN_CREDIT (handler._require_openrouter_credit): a real request
# for the balance. Off here; tests/test_cost_quality_2026_10_07.py sets its own floor around a mocked balance.
os.environ.setdefault("OPENROUTER_MIN_CREDIT", "0")
os.environ.setdefault("OPENROUTER_MIN_CREDIT_SMALL", "0")
