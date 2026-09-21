"""
Run the real VidRush workflow on a local audio file and write an MP4.

Identical pipeline to the RunPod worker — real whisper alignment, real
Creative-Commons YouTube sourcing via yt-dlp, real Wikimedia stills, the same
director, the same timeline validation, the same Remotion render. The only
thing skipped is Supabase: the file lands on disk instead of being uploaded,
so this needs no credentials.

    python scripts/make_video.py <audio.mp3> [--title "..."] [--seconds 180]
                                [--width 1920] [--workers 6] [--out out/video.mp4]

--seconds trims the narration to a slice, which is how you check quality and
sourcing hit-rate before committing to a full-length run.
"""
import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import handler  # noqa: E402
from src import config, render as renderer  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--title", default="")
    ap.add_argument("--seconds", type=float, default=0.0,
                    help="trim narration to this many seconds (0 = whole file)")
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default="")
    ap.add_argument("--no-maps", action="store_true")
    args = ap.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config.REMOTION_DIR = os.path.join(root, "remotion")
    work = os.path.join(root, "out", "make")
    os.makedirs(work, exist_ok=True)

    source = os.path.abspath(args.audio)
    if not os.path.isfile(source):
        print(f"no such audio file: {source}")
        return 2

    audio = source
    if args.seconds:
        audio = os.path.join(work, "narration_slice.mp3")
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", source, "-t", f"{args.seconds:.2f}",
             "-c:a", "libmp3lame", "-b:a", "192k", audio], check=True)
        print(f"trimmed to {args.seconds:.0f}s -> {audio}", flush=True)

    width = args.width - (args.width % 2)
    height = int(width * 9 / 16) // 2 * 2
    out_path = os.path.abspath(args.out) if args.out else os.path.join(work, "video.mp4")

    inp = {
        "audio_path": audio,
        "title": args.title,
        "width": width, "height": height, "fps": 30,
        "captions": True,
        "maps": not args.no_maps,
        "source_workers": args.workers,
        "brand": {"accent": "#FFD400", "fontFamily": "Inter"},
    }

    started = time.time()
    report = handler.Reporter("")
    print("=== PLAN ===", flush=True)
    doc = handler.do_plan(inp, work, report)
    meta = doc["meta"]
    plan_seconds = time.time() - started

    print("\n--- storyboard ---")
    print(f"  scenes          {meta['sceneCount']}")
    print(f"  cuts/min        {meta['cutsPerMinute']}  (VidRush reference 16.8-21.8)")
    print(f"  overlays        {meta['overlayCount']} {sorted({o['type'] for o in doc['overlays']})}")
    print(f"  sources         {meta['sources']}")
    print(f"  no media        {meta['scenesWithoutMedia']}")
    print(f"  needs review    {meta['scenesNeedingReview']}")
    print(f"  planner         {meta['planner']}")
    print(f"  plan took       {plan_seconds / 60:.1f} min")
    for w in meta["warnings"]:
        print(f"  ! {w}")

    # How many scenes got real motion footage vs a Ken Burns still — the single
    # most useful number for judging whether CC YouTube covered this script.
    kinds = {}
    for s in doc["scenes"]:
        kinds[s["media"].get("source", "none")] = kinds.get(s["media"].get("source", "none"), 0) + 1
    print(f"  per source      {kinds}")

    with open(os.path.join(work, "timeline.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)

    print("\n=== RENDER ===", flush=True)
    t0 = time.time()
    renderer.render(doc, out_path, composition="Main", serve_dir=work)
    render_seconds = time.time() - t0

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type", "-of", "default=noprint_wrappers=1", out_path],
        capture_output=True, text=True)
    info = dict(l.split("=", 1) for l in probe.stdout.strip().splitlines() if "=" in l)

    print(f"\n  file            {out_path}")
    print(f"  size            {os.path.getsize(out_path) / 1e6:.1f} MB")
    print(f"  duration        {float(info.get('duration', 0)):.1f}s")
    print(f"  audio track     {'yes' if 'audio' in probe.stdout else 'NO'}")
    print(f"  render took     {render_seconds / 60:.1f} min")
    print(f"  total           {(time.time() - started) / 60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
