"""
Render one sample of every animation template and save a contact sheet.

Type-checking proves the templates compile; it says nothing about whether a
bar chart is readable or a map label collides with its pin. This renders the
whole library to MP4 and pulls a frame out of the middle of each card so the
result can actually be looked at.

    python scripts/preview_overlays.py [--width 1280] [--open]

Writes out/overlay-preview.mp4 and out/frames/NN-<type>.png.
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config, render as renderer  # noqa: E402

SECONDS_EACH = 4.0

# One representative payload per template, using the shapes the director
# actually emits — including the map's gazetteer-resolved coordinates.
SAMPLES = [
    ("title", {"text": "MISSING: 1,000s"}),
    ("chapter", {"text": "The Search Begins", "subtitle": "Chapter Two"}),
    ("callout", {"text": "12,000 people | displaced"}),
    ("typewriter", {"text": "So where did the water go?"}),
    ("stat", {"text": "of the reservoir lost", "value": 74, "suffix": "%"}),
    ("bar-chart", {"text": "Reported missing", "items": [
        {"label": "Official count", "value": 112},
        {"label": "Civilian registry", "value": 1340},
        {"label": "Red Cross", "value": 890},
    ]}),
    ("comparison", {"text": "Water table, 2015 vs 2026", "items": [
        {"label": "2015", "value": 38, "text": "metres"},
        {"label": "2026", "value": 9, "text": "metres"},
    ]}),
    ("map", {"text": "Epicentre", "locations": [
        {"label": "San José del Palmar, Colombia", "lat": 4.8963, "lon": -76.2283},
    ]}),
    ("quote", {"text": "The river simply stopped arriving.",
               "subtitle": "Municipal engineer"}),
    ("timeline", {"text": "How it unfolded", "items": [
        {"label": "2019", "text": "First wells run dry"},
        {"label": "2023", "text": "Rationing begins"},
        {"label": "2026", "text": "Reservoir closed"},
    ]}),
    ("highlight", {"text": "Nobody was told for eleven days."}),
    ("lower-third", {"text": "Daniela Largo", "subtitle": "Her name is",
                     "label": "Hydrologist, Universidad del Valle"}),
    ("arrow", {"text": "The breach point"}),
    # Split needs two real media entries; colour placeholders stand in here.
    ("split", {"text": "", "media": [
        {"type": "color", "url": "", "source": "none"},
        {"type": "color", "url": "", "source": "none"},
    ]}),
]


def build_doc(width: int, height: int, fps: int) -> dict:
    per = int(round(SECONDS_EACH * fps))
    total = per * len(SAMPLES)
    scenes, overlays = [], []
    for i, (kind, payload) in enumerate(SAMPLES):
        start = i * per
        scenes.append({
            "id": f"s{i:04d}", "startFrame": start, "durationInFrames": per,
            "text": f"{kind} template", "media": {"type": "color", "url": "", "source": "none"},
            "motion": "none", "transition": "fade", "words": [],
        })
        overlays.append({"type": kind, "startFrame": start,
                         "durationInFrames": per, **payload})
    return {
        "schemaVersion": 2, "fps": fps, "width": width, "height": height,
        "durationInFrames": total,
        # No narration: this is a design preview, not a video.
        "audio": {"url": "", "volume": 0},
        "bgm": None,
        "captions": {"enabled": False, "position": "bottom",
                     "accent": "#FFD400", "fontFamily": "Inter"},
        "scenes": scenes, "overlays": overlays,
        "meta": {"sceneCount": len(scenes), "preview": True},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--fps", type=int, default=30)
    args = ap.parse_args()
    width = args.width - (args.width % 2)
    height = int(width * 9 / 16) // 2 * 2

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config.REMOTION_DIR = os.path.join(root, "remotion")
    out_dir = os.path.join(root, "out")
    frames_dir = os.path.join(out_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    mp4 = os.path.join(out_dir, "overlay-preview.mp4")

    doc = build_doc(width, height, args.fps)
    print(f"rendering {len(SAMPLES)} templates at {width}x{height}...", flush=True)
    renderer.render(doc, mp4, composition="Main")
    print(f"wrote {mp4} ({os.path.getsize(mp4) / 1e6:.1f} MB)")

    # Grab each card two-thirds of the way in, once it has finished animating.
    for i, (kind, _) in enumerate(SAMPLES):
        at = (i + 0.66) * SECONDS_EACH
        png = os.path.join(frames_dir, f"{i:02d}-{kind}.png")
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{at:.2f}", "-i", mp4,
             "-frames:v", "1", png],
            check=True,
        )
    print(f"wrote {len(SAMPLES)} frames to {frames_dir}")
    print(json.dumps({"mp4": mp4, "frames": frames_dir}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
