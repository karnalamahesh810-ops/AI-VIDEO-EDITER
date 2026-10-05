"""
Measure where every look draws, for the subtitles to keep clear of it.

The caption track (remotion/src/components/Captions.tsx, captionPlace.ts)
moves a cue up - or to the top - while a graphic occupies the bottom of the
frame. The renderer cannot see pixels, so each look is drawn once here, alone
on a transparent frame (composition CaptionFootprints, src/FootprintSheet.tsx)
at four moments of its run, and the cells of a 32 x 18 grid it puts anything
in are written to remotion/src/data/caption_footprints.json (one string per
look: a hex mask of 8 digits per row, top row first; bit c = column c). A
picture a look shows is a transparent stand-in: a subtitle may sit over a
photo as it sits over footage, never over the look's own labels and frames.

    cd runpod && SKIP_DOTENV=1 python scripts/build_caption_footprints.py [--only LIB_LT_,CMP_] [--keep DIR]

Run it after adding or changing looks; a look without a footprint is treated
as covering nothing unless it is moved to a bottom position (captionPlace.ts
guessRects) - so is one that drew nothing from its sample words (a chart that
needs its data), which is left out rather than recorded as empty. Maps are not
drawn (they fetch tiles and fill the frame anyway). Local only: no network but
the fonts, no paid calls.
"""
import argparse
import base64
import glob
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

os.environ.setdefault("SKIP_DOTENV", "1")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src import config, render as renderer, templates  # noqa: E402

OUT = os.path.join(ROOT, "remotion", "src", "data", "caption_footprints.json")
GRID = (32, 18)
FPS = 30
SAMPLES = (0.3, 0.5, 0.68, 0.82)       # moments of a look's run (its entrance and exit left out)
SCALE = 0.25                           # drawn at 480 x 270: enough for a 32 x 18 grid
CELL_SHARE = 0.03                      # a cell is covered when 3% of its pixels carry the look
ALPHA = 0.45                           # a pixel carries the look at this opacity (over any scrim)
FULL_FRAME = 0.6                       # a look painting this share of the frame is measured by its detail
EDGE = 0.16                            # ...a pixel whose brightness steps this much to a neighbour (text, rules)

# The words each built-in component is drawn with (the shapes the planner writes).
SAMPLE_BY_COMPONENT = {
    "title": {"text": "MISSING: 1,000s"},
    "chapter": {"text": "The Search Begins", "subtitle": "Chapter Two"},
    "callout": {"text": "12,000 people | displaced"},
    "typewriter": {"text": "So where did the water go?"},
    "stat": {"text": "of the reservoir lost", "value": 74, "suffix": "%"},
    "stat-tag": {"text": "FEET", "value": 930},
    "bar-chart": {"text": "Reported missing", "items": [{"label": "Official count", "value": 112},
                                                        {"label": "Civilian registry", "value": 1340},
                                                        {"label": "Red Cross", "value": 890}]},
    "comparison": {"text": "Water table, 2015 vs 2026", "items": [{"label": "2015", "value": 38, "text": "metres"},
                                                                   {"label": "2026", "value": 9, "text": "metres"}]},
    "quote": {"text": "The river simply stopped arriving.", "subtitle": "Municipal engineer"},
    "timeline": {"text": "How it unfolded", "items": [{"label": "2019", "text": "First wells run dry"},
                                                      {"label": "2023", "text": "Rationing begins"},
                                                      {"label": "2026", "text": "Reservoir closed"}]},
    "highlight": {"text": "Nobody was told for eleven days."},
    "lower-third": {"text": "Daniela Largo", "subtitle": "Her name is", "label": "Hydrologist, Universidad del Valle"},
    "arrow": {"text": "The breach point"},
    "sentence-highlight": {"text": "America saw a reunion. The record reveals a goodbye.", "highlight": "reunion, goodbye"},
    "article-zoom": {"text": "Before Honolulu Knew, the File Named a Family", "subtitle": "Archival Review",
                     "highlight": "a Family", "body": "The immigration file records what officials knew."},
    "date-stamp": {"text": "Boston, July 27, 2004"},
    "name-card": {"text": "Floyd Dominy", "subtitle": "Commissioner, Bureau of Reclamation"},
    "photo-card": {"text": "GLEN CANYON DAM"},
    "kicker": {"text": "concrete"},
    "label-boxes": {"text": "LAKE POWELL | LAKE MEAD"},
    "ring-stat": {"text": "full", "value": 26, "suffix": "%"},
    "bullets": {"text": "What failed", "items": [{"label": "Spillway lining"}, {"label": "Gate seals"},
                                                 {"label": "Forecasts"}]},
    # The data looks draw nothing without their figures (a review on 2026-10-05 found them unmeasured),
    # and the split's label pills sit low in the frame, right where a subtitle goes.
    "split": {"text": "Then and now", "items": [{"label": "SPILLWAY TUNNELS"}, {"label": "CANYON WALL"}]},
    "counter": {"text": "people displaced", "value": 12000},
    "number-roll": {"text": "feet below full", "value": 170},
    "trend": {"text": "LAKE POWELL", "value": 3516, "suffix": " ft", "label": "down"},
    "donut": {"text": "full", "value": 26, "suffix": "%"},
    "line-chart": {"text": "Lake Powell level", "suffix": " ft",
                   "items": [{"label": "2000", "value": 3680}, {"label": "2010", "value": 3640},
                             {"label": "2020", "value": 3600}, {"label": "2026", "value": 3516}]},
    "area-chart": {"text": "Lake Powell level", "suffix": " ft",
                   "items": [{"label": "2000", "value": 3680}, {"label": "2010", "value": 3640},
                             {"label": "2020", "value": 3600}, {"label": "2026", "value": 3516}]},
    "ranking": {"text": "Largest reservoirs", "items": [{"label": "Lake Mead", "value": 26}, {"label": "Lake Powell",
                                                                                              "value": 24},
                                                        {"label": "Lake Sakakawea", "value": 23},
                                                        {"label": "Lake Oahe", "value": 22}]},
    "scale-compare": {"text": "How big", "items": [{"label": "Lake Powell", "value": 24},
                                                   {"label": "Lake Tahoe", "value": 120}]},
    "year-roll": {"text": "", "items": [{"label": "1963"}, {"label": "2026"}]},
    "progress-steps": {"text": "", "items": [{"label": "Drought"}, {"label": "Rationing"}, {"label": "Dead pool"}]},
}
SKIP_COMPONENTS = {"map"}


def stand_in_picture() -> str:
    """
    A fully transparent still (data: URI) for the looks that show a picture:
    a subtitle may sit over a photo as it sits over footage, so only what a
    look draws round and on its pictures (frames, labels, text) is measured.
    """
    from PIL import Image
    im = Image.new("RGBA", (640, 360), (0, 0, 0, 0))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def library_samples() -> dict:
    out = {}
    for path in sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "library_looks*.json"))):
        with open(path, encoding="utf-8") as fh:
            for look in json.load(fh):
                out["LIB_" + look["id"].upper().replace("-", "_")] = dict(look.get("sample") or {})
    return out


def sheet(only: str = "") -> dict:
    lib = library_samples()
    pic = stand_in_picture()
    looks = []
    for t in templates.all_templates():
        if only and not t["id"].startswith(tuple(x.strip() for x in only.split(",") if x.strip())):
            continue
        if t["component"] in SKIP_COMPONENTS or t["category"] == "MAPS":
            continue
        frames = max(30, int(round(float(t["defaults"]["duration"]) * FPS)))
        sample = dict(lib.get(t["id"]) or SAMPLE_BY_COMPONENT.get(t["component"]) or {"text": "Glen Canyon Dam"})
        sample.pop("media", None)
        ov = {"template": t["id"], "type": t["component"], "text": "", **sample,
              "startFrame": 0, "durationInFrames": frames}
        if t["defaults"].get("variant"):
            ov["variant"] = t["defaults"]["variant"]
        if t["component"] == "split":
            ov["media"] = [{"type": "image", "url": pic, "source": "demo"}] * 2
        looks.append({"id": t["id"], "overlay": ov, "at": [int(frames * s) for s in SAMPLES]})
    scene = {"id": "s0", "startFrame": 0, "durationInFrames": 100000, "text": "", "words": [], "motion": "none",
             "transition": "none", "media": {"type": "image", "url": pic, "source": "library", "thumbnail": pic},
             "semanticMetadata": {"subject": "Glen Canyon Dam"}}
    return {"looks": looks, "samples": len(SAMPLES), "scenes": [scene], "accent": "#FFD400"}


def grid_of(png_paths) -> str:
    """
    The covered cells of a look's frames: 8 hex digits per row, top row first
    (bit c = column c). A look that paints most of the frame (a full-screen
    card on its own backdrop) counts only where it has detail - its words,
    labels, figures and edges - not the flat or blurred backdrop: a subtitle
    is drawn over such a card anyway and should only keep off its text.
    """
    import numpy as np
    from PIL import Image
    cols, rows = GRID
    covered = np.zeros((rows, cols), dtype=bool)
    for path in png_paths:
        px = np.asarray(Image.open(path).convert("RGBA"), dtype=np.float32) / 255.0
        a = px[:, :, 3]
        # A uniform scrim over the whole frame is not the look's shape: measure above it.
        floor = float(np.percentile(a, 10))
        on = a >= max(ALPHA, min(0.95, floor + 0.3))
        if on.mean() > FULL_FRAME:
            lum = (px[:, :, 0] * 0.299 + px[:, :, 1] * 0.587 + px[:, :, 2] * 0.114) * a
            edge = np.zeros_like(lum)
            edge[:, 1:] += np.abs(np.diff(lum, axis=1))
            edge[1:, :] += np.abs(np.diff(lum, axis=0))
            on = edge >= EDGE
        h, w = on.shape
        for r in range(rows):
            y0, y1 = r * h // rows, (r + 1) * h // rows
            for c in range(cols):
                x0, x1 = c * w // cols, (c + 1) * w // cols
                cell = on[y0:y1, x0:x1]
                if cell.size and cell.mean() >= CELL_SHARE:
                    covered[r, c] = True
    return "".join(format(sum(1 << c for c in range(cols) if covered[r, c]), "08x") for r in range(rows))


def without_seam(mask: str) -> str:
    """
    A split's footprint without its divider: the thin line between its two
    pictures runs the full height of the frame, so a subtitle (drawn above
    the graphics) crosses it as it would the seam between two shots - only
    the label pills low in each half are kept clear of.
    """
    cols, rows = GRID
    seam = sum(1 << c for c in range(cols // 2 - 1, cols // 2 + 1))
    return "".join(format(int(mask[r * 8:(r + 1) * 8], 16) & ~seam & ((1 << cols) - 1), "08x") for r in range(rows))


def write(data: dict) -> None:
    """The data file, one look per line (diffs stay readable)."""
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write('{"version":1,"grid":[%d,%d],"looks":{\n' % GRID)
        fh.write(",\n".join(f"{json.dumps(key)}:{json.dumps(val)}" for key, val in data["looks"].items()))
        fh.write("\n}}\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="measure only the templates whose id starts with this (several: comma-separated)")
    ap.add_argument("--keep", default="", help="keep the frames in this directory")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--reuse", action="store_true", help="measure the frames already in --keep again (no drawing)")
    args = ap.parse_args()
    config.REMOTION_DIR = os.path.join(ROOT, "remotion")
    work = args.keep or tempfile.mkdtemp(prefix="footprints-")
    os.makedirs(work, exist_ok=True)
    props_path = os.path.join(work, "sheet.props.json")
    frames_dir = os.path.join(work, "frames")
    if args.reuse and args.keep:
        with open(props_path, encoding="utf-8") as fh:
            props = json.load(fh)
        n = len(props["looks"])
    else:
        props = sheet(args.only)
        n = len(props["looks"])
        with open(props_path, "w", encoding="utf-8") as fh:
            json.dump(props, fh)
        shutil.rmtree(frames_dir, ignore_errors=True)
        print(f"drawing {n} looks x {len(SAMPLES)} moments...", flush=True)
        # Only the sampled frames: the composition runs on past them (Root.tsx) so no look is cut short.
        cmd = renderer._renderer_argv() + ["render", "src/index.ts", "CaptionFootprints", frames_dir, "--sequence",
                                           f"--frames=0-{n * len(SAMPLES) - 1}",
                                           "--image-format=png", f"--scale={SCALE}", f"--props={props_path}",
                                           f"--concurrency={args.concurrency}", "--log=error",
                                           "--timeout=60000"]
        subprocess.run(cmd, cwd=config.REMOTION_DIR, check=True)
    pngs = sorted(glob.glob(os.path.join(frames_dir, "*.png")))
    if len(pngs) != n * len(SAMPLES):
        print(f"expected {n * len(SAMPLES)} frames, got {len(pngs)}", flush=True)
        return 1
    data = {"version": 1, "grid": list(GRID), "looks": {}}
    if args.only and os.path.isfile(OUT):
        with open(OUT, encoding="utf-8") as fh:
            data = json.load(fh)
    k = len(SAMPLES)
    for i, look in enumerate(props["looks"]):
        mask = grid_of(pngs[i * k:(i + 1) * k])
        if look["overlay"].get("type") == "split":
            mask = without_seam(mask)
        if mask.strip("0"):
            data["looks"][look["id"]] = mask
        else:
            data["looks"].pop(look["id"], None)       # drew nothing: unmeasured, not "covers nothing"
    data["looks"] = dict(sorted(data["looks"].items()))
    write(data)
    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    print(f"{len(data['looks'])} footprints -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
