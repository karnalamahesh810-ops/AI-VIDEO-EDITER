"""Bake the Style Match font library (Google Fonts, OFL / Apache) into the image: python fetch_style_fonts.py /opt/style_fonts"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["STYLE_FONT_DIR"] = sys.argv[1] if len(sys.argv) > 1 else "/opt/style_fonts"
from src.style_match import fonts  # noqa: E402

n = fonts.prefetch()
print(f"style fonts: {n}/{len(fonts.LIBRARY)} in {fonts.FONT_DIR}")
if n < len(fonts.LIBRARY) - 3:
    sys.exit("too many style fonts missing")
