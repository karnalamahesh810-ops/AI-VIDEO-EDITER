"""
In-container self test: prove the whole render path works on this worker.

`health` says the process started. That is a low bar — it does not tell you
whether ffmpeg is present, whether headless Chrome can launch on this GPU
image, whether the loopback asset server can reach Chrome, whether any of the
fourteen animation templates throw, or whether faster-whisper can load its
model. Each of those has failed at some point on some machine, and each of
them fails *at render time*, minutes into a paid job.

So this runs the real thing end to end and needs no credentials: synthetic
narration audio and synthetic media from ffmpeg, the real director, the real
timeline and validator, a real Remotion render, and a probe of the output.
Nothing is uploaded, so it works on an endpoint with no Supabase keys set.
"""
import os
import subprocess
import time

from . import config, director, render as renderer, timeline, transcribe
from .media import MediaAsset

SCRIPT = (
    "The reservoir at San Jose del Palmar held four million cubic metres. "
    "By August the level had dropped 74 percent. "
    "So where did all of that water actually go? "
    "Roughly 12,000 people were displaced in the first week alone. "
)

# Every template, so a component that throws is caught here rather than in a
# customer's render. Payloads mirror what the director actually emits.
_TEMPLATE_SAMPLES = [
    ("title", {"text": "MISSING: 1,000s"}),
    ("chapter", {"text": "The Search Begins", "subtitle": "Chapter Two"}),
    ("callout", {"text": "12,000 people | displaced"}),
    ("typewriter", {"text": "So where did the water go?"}),
    ("stat", {"text": "of the reservoir lost", "value": 74, "suffix": "%"}),
    ("bar-chart", {"text": "Reported missing", "items": [
        {"label": "Official", "value": 112}, {"label": "Civilian", "value": 1340}]}),
    ("comparison", {"text": "2015 vs 2026", "items": [
        {"label": "2015", "value": 38, "text": "m"},
        {"label": "2026", "value": 9, "text": "m"}]}),
    ("map", {"text": "Epicentre", "locations": [
        {"label": "San Jose del Palmar, Colombia", "lat": 4.8963, "lon": -76.2283}]}),
    ("quote", {"text": "The river simply stopped arriving.", "subtitle": "Engineer"}),
    ("timeline", {"text": "How it unfolded", "items": [
        {"label": "2019", "text": "Wells fail"}, {"label": "2026", "text": "Closed"}]}),
    ("highlight", {"text": "Nobody was told for eleven days."}),
    ("lower-third", {"text": "Daniela Largo", "subtitle": "Her name is"}),
    ("arrow", {"text": "The breach point"}),
    ("split", {"text": "", "media": [
        {"type": "color", "url": "", "source": "none"},
        {"type": "color", "url": "", "source": "none"}]}),
]


def _run(cmd, timeout=180):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _synth_words(text: str, wps: float = 2.7):
    out, t = [], 0.0
    for token in text.split():
        end = t + 1.0 / wps
        out.append(transcribe.Word(text=token, start=round(t, 3), end=round(end, 3)))
        t = end + (0.32 if token[-1:] in ".!?" else 0.02)
    return out


def _tool_versions() -> dict:
    tools = {}
    for name, cmd in (("ffmpeg", ["ffmpeg", "-version"]),
                      ("yt-dlp", ["yt-dlp", "--version"]),
                      ("node", ["node", "--version"])):
        try:
            p = _run(cmd, timeout=60)
            tools[name] = (p.stdout or p.stderr or "").strip().splitlines()[0][:60]
        except Exception as e:  # noqa: BLE001
            tools[name] = f"MISSING ({type(e).__name__})"
    return tools


def _whisper_status() -> str:
    """Loading the model is the expensive, failure-prone part — check it here."""
    try:
        t = time.time()
        transcribe._load_model()
        return f"ok ({config.WHISPER_MODEL}, loaded in {time.time() - t:.1f}s)"
    except Exception as e:  # noqa: BLE001
        return f"FAILED: {type(e).__name__}: {str(e)[:160]}"


def run(work: str, width: int = 854, seconds_per_template: float = 1.6,
        report=None) -> dict:
    """Render the full template set plus a narration-driven tail. Uploads nothing."""
    started = time.time()
    os.makedirs(work, exist_ok=True)
    result: dict = {"checks": {}}

    def step(msg, pct=None):
        if report:
            report(msg, pct)

    step("Self test: checking tools", 5)
    result["tools"] = _tool_versions()

    width -= width % 2
    height = int(width * 9 / 16) // 2 * 2
    fps = 30

    step("Self test: building test media", 15)
    audio = os.path.join(work, "st_audio.mp3")
    clip = os.path.join(work, "st_clip.mp4")
    still = os.path.join(work, "st_still.png")
    total_seconds = len(_TEMPLATE_SAMPLES) * seconds_per_template
    _run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
          "-i", f"sine=frequency=220:duration={total_seconds:.2f}",
          "-af", "volume=0.05", "-c:a", "libmp3lame", audio])
    _run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
          "-i", f"testsrc2=size=1280x720:rate=30:duration={seconds_per_template + 2:.2f}",
          "-pix_fmt", "yuv420p", clip])
    _run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
          "-i", "gradients=size=1280x720:n=3", "-frames:v", "1", still])
    for path in (audio, clip, still):
        if not os.path.isfile(path):
            raise RuntimeError(f"ffmpeg could not create {os.path.basename(path)} "
                               "— is ffmpeg present in the image?")

    # A beat per template, alternating video and still so both render paths run.
    step("Self test: planning", 25)
    segments, shots, assets = [], [], []
    for i, (kind, payload) in enumerate(_TEMPLATE_SAMPLES):
        start = i * seconds_per_template
        text = f"Template {kind} under test."
        segments.append(transcribe.Segment(
            text=text, start=start, end=start + seconds_per_template,
            words=_synth_words(text)))
        shots.append({"query": kind, "visualType": "footage",
                      "overlay": {"type": kind, **payload}})
        assets.append(
            MediaAsset(kind="video", source="youtube", url="", local_path=clip,
                       duration=seconds_per_template + 2, license="test")
            if i % 2 == 0 else
            MediaAsset(kind="image", source="wikimedia", url="", local_path=still,
                       license="test"))

    doc = timeline.build(
        segments, shots, assets,
        audio_url=audio, audio_duration=total_seconds,
        inp={"width": width, "height": height, "fps": fps, "captions": True},
        planner="selftest", warnings=[],
    )
    timeline.validate(doc, require_media=True)
    result["checks"]["timeline"] = f"ok ({len(doc['scenes'])} scenes, " \
                                   f"{len(doc['overlays'])} overlays)"
    result["templatesExercised"] = sorted({o["type"] for o in doc["overlays"]})
    missing = sorted(director.TEMPLATES - set(result["templatesExercised"]))
    if missing:
        result["checks"]["templates"] = f"WARNING: not exercised: {missing}"
    else:
        result["checks"]["templates"] = f"ok (all {len(director.TEMPLATES)})"

    step("Self test: rendering", 45)
    out_path = os.path.join(work, "selftest.mp4")
    t0 = time.time()
    renderer.render(doc, out_path, composition="Main", serve_dir=work)
    render_seconds = time.time() - t0

    probe = _run(["ffprobe", "-v", "error", "-show_entries",
                  "format=duration:stream=codec_type", "-of",
                  "default=noprint_wrappers=1", out_path])
    info = dict(l.split("=", 1) for l in probe.stdout.strip().splitlines() if "=" in l)
    actual = float(info.get("duration", 0) or 0)
    size = os.path.getsize(out_path)

    result["render"] = {
        "durationSeconds": round(actual, 2),
        "expectedSeconds": round(total_seconds, 2),
        "sizeBytes": size,
        "hasAudio": "audio" in probe.stdout,
        "resolution": f"{width}x{height}",
        "renderSeconds": round(render_seconds, 1),
        "realtimeFactor": round(render_seconds / max(actual, 0.01), 2),
    }
    result["checks"]["render"] = (
        "ok" if size > 10_000 and abs(actual - total_seconds) < 1.5
        else f"SUSPECT (size={size}, duration={actual:.2f})")
    result["checks"]["audio"] = "ok" if result["render"]["hasAudio"] else "FAILED: no audio track"

    step("Self test: checking whisper", 85)
    result["checks"]["whisper"] = _whisper_status()

    result["elapsed"] = round(time.time() - started, 1)
    result["ok"] = all(not str(v).startswith(("FAILED", "SUSPECT"))
                       for v in result["checks"].values())
    return result
