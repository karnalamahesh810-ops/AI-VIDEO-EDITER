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
