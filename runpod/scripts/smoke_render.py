"""
End-to-end smoke test: script + audio in, watchable MP4 out.

Only the three external boundaries are stubbed — whisper (a model download),
media sourcing (the network) and Supabase (credentials). Everything between
them runs for real: clause segmentation, the rule-based director, geocoding
(stubbed to a fixed answer so the run is offline), timeline construction,
validation, the loopback asset server, and an actual Remotion render.

That is deliberately the opposite of a unit test. The failures this catches
are the wiring ones — a document Remotion cannot load, media Chrome cannot
fetch, a scene track that does not tile the audio.

    python scripts/smoke_render.py [--seconds 40] [--width 960]
"""
import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import handler  # noqa: E402
from src import config, geocode, media, transcribe  # noqa: E402
from src.media import MediaAsset  # noqa: E402

SCRIPT = (
    "The reservoir at San Jose del Palmar held four million cubic metres of water. "
    "For eleven years nobody measured it, and nobody needed to. "
    "Then in the spring of 2019 the outer wells began to fail. "
    "By August the level had dropped 74 percent. "
    "So where did all of that water actually go? "
    "The engineers said it would refill after the rains. It did not refill. "
    "Roughly 12,000 people were displaced in the first week alone. "
    "What happened next is the part that nobody reported at the time. "
)


def fake_words(text: str, wps: float = 2.7):
    """Stand-in for whisper: evenly paced words, a beat after each sentence."""
    out, t = [], 0.0
    for token in text.split():
        end = t + 1.0 / wps
        out.append(transcribe.Word(text=token, start=round(t, 3), end=round(end, 3)))
        t = end + (0.32 if token[-1:] in ".!?" else 0.02)
    return out


def make_audio(path: str, seconds: float):
    """A quiet tone standing in for narration, so the mux has a real track."""
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"sine=frequency=220:duration={seconds:.2f}",
         "-af", "volume=0.05", "-c:a", "libmp3lame", path],
        check=True,
    )


def make_local_media(work: str):
    """
    Replace network sourcing with locally generated clips and stills.

    Alternating video and image exercises both render paths — OffthreadVideo
    with range requests, and Img with Ken Burns.
    """
    made = {"n": 0}

    def fake_source(query, seconds, work_dir, *, visual_type="footage", **kw):
        made["n"] += 1
        i = made["n"]
        os.makedirs(work_dir, exist_ok=True)
        if visual_type == "footage" and i % 2 == 1:
            path = os.path.join(work_dir, f"clip{i}.mp4")
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                 "-i", f"testsrc2=size=1280x720:rate=30:duration={max(2, seconds + 2):.2f}",
                 "-pix_fmt", "yuv420p", path], check=True)
            return MediaAsset(kind="video", source="youtube", url="", local_path=path,
                              duration=seconds + 2, license="CC BY (test)", query=query)
        path = os.path.join(work_dir, f"still{i}.png")
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
             "-i", f"gradients=size=1280x720:n=3:seed={i}", "-frames:v", "1", path],
            check=True)
        return MediaAsset(kind="image", source="wikimedia", url="", local_path=path,
                          license="CC BY-SA (test)", query=query)

    return fake_source


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=0.0,
                    help="narration length; default follows the script")
    ap.add_argument("--width", type=int, default=960)
    args = ap.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config.REMOTION_DIR = os.path.join(root, "remotion")
    config.WORK_DIR = os.path.join(root, "out", "smoke")
    work = os.path.join(config.WORK_DIR, "job")
    os.makedirs(work, exist_ok=True)

    words = fake_words(SCRIPT)
    duration = args.seconds or round(words[-1].end + 0.4, 2)
    audio_path = os.path.join(work, "narration.mp3")
    make_audio(audio_path, duration)

    # --- stub the three external boundaries ---------------------------------
    transcribe.transcribe_words = lambda path, language=None: words
    media.source_for_segment = make_local_media(work)
    geocode.resolve_all = lambda names: [
        {"label": "San José del Palmar, Colombia", "lat": 4.8963,
         "lon": -76.2283, "kind": "town"}] if names else []

    width = args.width - (args.width % 2)
    height = int(width * 9 / 16) // 2 * 2
    inp = {
        "audio_path": audio_path,
        "title": "The Vanishing Reservoir",
        "width": width, "height": height, "fps": 30,
        "captions": True,
        "brand": {"accent": "#FFD400", "fontFamily": "Inter"},
        "source_workers": 4,
    }

    steps = []
    report = handler.Reporter("")
    print("--- plan ---", flush=True)
    doc = handler.do_plan(inp, work, report)
    meta = doc["meta"]
    print(f"  scenes           {meta['sceneCount']}")
    print(f"  cuts/min         {meta['cutsPerMinute']}")
    print(f"  overlays         {meta['overlayCount']} "
          f"({sorted({o['type'] for o in doc['overlays']})})")
    print(f"  planner          {meta['planner']}")
    print(f"  source policy    {meta['sourcePolicy']}  sources={meta['sources']}")
    print(f"  needs review     {meta['scenesNeedingReview']}")
    for w in meta["warnings"]:
        print(f"  warning          {w}")
    steps.append(("plan", True))

    print("--- render ---", flush=True)
    out_path = os.path.join(work, "final.mp4")
    import src.render as renderer
    renderer.render(doc, out_path, composition="Main", serve_dir=work)
    steps.append(("render", os.path.exists(out_path)))

    # --- inspect the artefact ----------------------------------------------
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,codec_name,width,height",
         "-of", "default=noprint_wrappers=1", out_path],
        capture_output=True, text=True)
    info = dict(line.split("=", 1) for line in probe.stdout.strip().splitlines()
                if "=" in line)
    has_audio = "audio" in probe.stdout
    actual = float(info.get("duration", 0))

    print(f"  file             {out_path} ({os.path.getsize(out_path) / 1e6:.1f} MB)")
    print(f"  duration         {actual:.2f}s (narration {duration:.2f}s)")
    print(f"  audio track      {'yes' if has_audio else 'NO'}")

    frames_dir = os.path.join(config.WORK_DIR, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    for i, at in enumerate([1.0, actual * 0.35, actual * 0.6, actual * 0.85]):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{at:.2f}",
                        "-i", out_path, "-frames:v", "1",
                        os.path.join(frames_dir, f"smoke-{i}.png")], check=True)
    print(f"  frames           {frames_dir}")

    ok = (has_audio and abs(actual - duration) < 1.0
          and all(passed for _, passed in steps))
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
