"""
Celeb compilation style ("Celebs Goat", docs/style-refs/celeb-compilation-STYLE.md).

A narrator bridges real interview / talk-show clips that play with their OWN audio:
  script.py  - the owner's script with [CLIP: ...] spots -> ordered narr / clip blocks
  quotes.py  - the quote finder: search -> caption word timings -> fuzzy quote match ->
               sentence-snapped in point, laugh-tail out point -> window download
  voalign.py - an uploaded voice-over cut at the clip spots (whisper words aligned to the script)
  plan.py    - the timeline: cold open, narration, clips, J-cut picture, b-roll, flashes, mix levels
  compose.py - an ffmpeg renderer for the plan (captions, label, push-in, flash, ducked music)
"""
