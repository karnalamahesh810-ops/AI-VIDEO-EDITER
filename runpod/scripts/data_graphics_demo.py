"""
The real data graphics demo (src/datagraphics.py): a 20-second narration about the Colorado River's water - Lake
Mead's level, Lake Powell's share of capacity, the share of the lower 48 in drought - planned by the real planner
(config.DATA_GRAPHICS on) with today's official numbers, rendered locally by Remotion at 1920x1080, 30 fps.

    python scripts/data_graphics_demo.py --out C:/somewhere/data_graphics_demo.mp4 [--phone] [--stills 40,250,450]

The narration is spoken by the machine's own voice (Windows speech, offline) so its word timings are real and the
charts land on the words as they are said; elsewhere the words are paced evenly over a silent track. The backdrops
are drawn here (no footage is fetched). Three charts in 20 seconds is far denser than a real video allows (one per
DATA_GRAPHICS_GAP, 50 s, none in the first DATA_GRAPHICS_HOOK_SECONDS without a number): the demo lifts those two
rules for itself only. Nothing is uploaded; the only network calls are the free public data sources.
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("SKIP_DOTENV", "1")

from src import config, datagraphics, render as renderer, timeline, treatments  # noqa: E402
from src.assetserver import AssetServer, localise  # noqa: E402
from src.transcribe import Segment, Word  # noqa: E402

FPS = 30
WIDTH, HEIGHT = 1920, 1080
TOTAL = 20.0
# (when the line starts, what is said): one chart each.
LINES = [
    (0.4, "Lake Mead has fallen to about one thousand thirty-eight feet above sea level."),
    (6.9, "Upstream, Lake Powell is just twenty-two percent full."),
    (13.2, "And nearly sixty percent of the lower forty-eight is now in drought."),
]
BRIEF = {"kind": "explainer", "hookBeats": [0], "sections": [], "places": ["Lake Mead", "Lake Powell", "Colorado River"],
         "summary": "The Colorado River's reservoirs and the drought behind them."}

_SAPI = r"""
param([string]$TextFile, [string]$WavPath, [string]$WordsPath)
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
try { $s.SelectVoice("Microsoft David Desktop") } catch { }
$s.Rate = 0
$text = Get-Content -Raw -Encoding UTF8 $TextFile
Register-ObjectEvent -InputObject $s -EventName SpeakProgress -SourceIdentifier "spk" | Out-Null
$s.SetOutputToWaveFile($WavPath)
$s.Speak($text)
$s.SetOutputToNull()
$out = @()
foreach ($ev in (Get-Event -SourceIdentifier "spk")) {
    $a = $ev.SourceEventArgs
    $out += [pscustomobject]@{ text = $a.Text; start = [math]::Round($a.AudioPosition.TotalSeconds, 3); pos = $a.CharacterPosition }
}
Unregister-Event -SourceIdentifier "spk"
$out | ConvertTo-Json -Depth 3 | Out-File -Encoding utf8 $WordsPath
$s.Dispose()
"""


def _duration(path: str) -> float:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    try:
        return float(p.stdout.strip())
    except ValueError:
        return 0.0


def speak(work: str):
    """(narration file, [[Word]] per line): Windows speech with its word timings, else even pacing over silence."""
    lines_words, parts = [], []
    ps = shutil.which("powershell")
    for n, (at, text) in enumerate(LINES):
        words = None
        if ps:
            script = os.path.join(work, "sapi.ps1")
            with open(script, "w", encoding="utf-8") as fh:
                fh.write(_SAPI)
            txt, wav, js = (os.path.join(work, f"line{n}.{e}") for e in ("txt", "wav", "json"))
            with open(txt, "w", encoding="utf-8") as fh:
                fh.write(text)
            subprocess.run([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, "-TextFile", txt,
                            "-WavPath", wav, "-WordsPath", js], capture_output=True, text=True, timeout=120)
            if os.path.isfile(wav) and os.path.isfile(js):
                with open(js, encoding="utf-8-sig") as fh:
                    got = json.load(fh)
                got = sorted(got if isinstance(got, list) else [got], key=lambda w: int(w["pos"]))
                end = _duration(wav)
                words = []
                for i, w in enumerate(got):
                    nxt = float(got[i + 1]["start"]) if i + 1 < len(got) else end - 0.15
                    words.append(Word(text=str(w["text"]), start=round(at + float(w["start"]), 3),
                                      end=round(at + max(float(w["start"]) + 0.12, nxt - 0.03), 3)))
                parts.append((at, wav))
        if words is None:
            t, words = at, []
            for token in text.split():
                words.append(Word(text=token, start=round(t, 3), end=round(t + 0.33, 3)))
                t += 0.38
        lines_words.append(words)
    out = os.path.join(work, "narration.wav")
    if parts:
        inputs, filters = [], []
        for k, (at, wav) in enumerate(parts):
            inputs += ["-i", wav]
            filters.append(f"[{k}:a]aresample=48000,adelay={int(at * 1000)}|{int(at * 1000)}[a{k}]")
        mix = "".join(f"[a{k}]" for k in range(len(parts)))
        filters.append(f"{mix}amix=inputs={len(parts)}:normalize=0,apad=whole_dur={TOTAL},atrim=0:{TOTAL}[out]")
        subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(filters), "-map", "[out]",
                        "-ac", "2", out], check=True)
    else:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo",
                        "-t", str(TOTAL), out], check=True)
    return out, lines_words


def backdrop(path: str, seed: int) -> None:
    """A quiet canyon-and-water picture drawn here (dusk sky, mesas, a reservoir band), 1920x1080."""
    from PIL import Image, ImageDraw, ImageFilter
    w, h = WIDTH, HEIGHT
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    top, mid = [(28, 36, 58), (46, 38, 62), (24, 44, 70)][seed % 3], (196, 128, 84)
    for y in range(h):
        t = min(1.0, y / (h * 0.55))
        d.line([(0, y), (w, y)], fill=tuple(int(top[i] + (mid[i] - top[i]) * t) for i in range(3)))
    rnd = (seed * 7919) % 1000 / 1000.0
    for layer, (base, color) in enumerate(((0.52, (92, 58, 44)), (0.6, (70, 42, 32)), (0.7, (48, 30, 24)))):
        pts = [(0, h)]
        for i in range(0, 41):
            x = w * i / 40
            y = h * base - 60 * math.sin(i * 0.7 + rnd * 6 + layer) - 40 * ((i * 37 + seed * 11 + layer * 5) % 7) / 7
            pts.append((x, y))
        pts.append((w, h))
        d.polygon(pts, fill=color)
    water_top = int(h * 0.78)
    for y in range(water_top, h):
        t = (y - water_top) / max(1, h - water_top)
        d.line([(0, y), (w, y)], fill=(int(40 + 20 * (1 - t)), int(96 + 30 * (1 - t)), int(140 + 30 * (1 - t))))
    d.rectangle([0, water_top - 34, w, water_top - 2], fill=(214, 206, 188))      # the bathtub ring
    img = img.filter(ImageFilter.GaussianBlur(1.2))
    img.save(path)


def build(work: str, captions: bool) -> dict:
    narration, words = speak(work)
    bounds = [0.0] + [LINES[i + 1][0] - 0.2 for i in range(len(LINES) - 1)] + [TOTAL]
    segs = [Segment(text=text, start=bounds[i], end=bounds[i + 1], words=words[i]) for i, (_at, text) in enumerate(LINES)]
    # Today's numbers from the sources.
    store = datagraphics.start([s.text for s in segs], BRIEF, budget=60)
    store.wait(75)
    print("[demo] data:", json.dumps(store.report()), flush=True)
    scenes = []
    for i, s in enumerate(segs):
        still = os.path.join(work, f"backdrop{i}.png")
        backdrop(still, i)
        a, b = int(round(s.start * FPS)), int(round(s.end * FPS))
        scenes.append({"id": f"s{i:04d}", "startFrame": a, "durationInFrames": b - a, "text": s.text,
                       "media": {"type": "image", "url": still, "source": "demo", "thumbnail": still},
                       "motion": "zoom-in", "transition": "none" if i == 0 else "fade", "effect": "none",
                       "words": [{"text": w.text, "start": w.start, "end": w.end} for w in s.words]})
    total = int(round(TOTAL * FPS))
    saved = {k: getattr(config, k) for k in ("DATA_GRAPHICS", "DATA_GRAPHICS_GAP", "DATA_GRAPHICS_HOOK_SECONDS")}
    try:
        config.DATA_GRAPHICS, config.DATA_GRAPHICS_GAP, config.DATA_GRAPHICS_HOOK_SECONDS = True, 4.0, 0.0
        pack = treatments.pack_for(BRIEF, "documentary")
        with datagraphics.use(store):
            plan = treatments.plan(segs, [{"subject": "water"} for _ in segs], scenes, FPS, total, BRIEF, pack,
                                   timeline._OVERLAY_SECONDS)
    finally:
        for k, v in saved.items():
            setattr(config, k, v)
    overlays = [o for o in plan["overlays"] if o.get("data")]
    lufs = timeline.measure_lufs(narration)
    return {
        "schemaVersion": timeline.SCHEMA_VERSION, "fps": FPS, "width": WIDTH, "height": HEIGHT, "durationInFrames": total,
        "audio": {"url": narration, "volume": 1.0}, "bgm": None,
        "captions": {"enabled": captions, "position": "bottom", "accent": "#FFD400", "fontFamily": "Inter",
                     "style": "documentary"},
        "scenes": scenes, "overlays": overlays, "sfx": [], "sfxVolume": 1.0, "sfxEnabled": True,
        "lookSounds": plan.get("lookSounds") or {"intensity": 0.8},
        "meta": {"voiceLufs": round(lufs, 1) if lufs is not None else -20.0, "dataGraphics": plan.get("dataGraphics"),
                 "demo": True},
    }


def stills(doc: dict, work: str, frames, out_dir: str) -> None:
    """PNGs of the document at these frames (remotion still), for a quick look."""
    with AssetServer(work) as assets:
        served = localise(json.loads(json.dumps(doc)), assets)
        props = os.path.join(work, "still.props.json")
        with open(props, "w", encoding="utf-8") as fh:
            json.dump(served, fh)
        entry = renderer.ensure_bundle() or "src/index.ts"
        for fr in frames:
            png = os.path.join(out_dir, f"frame_{int(fr):04d}.png")
            p = subprocess.run(renderer._renderer_argv() + ["still", entry, "Main", png, f"--props={props}",
                                                            f"--frame={int(fr)}", "--log=error"],
                               cwd=config.REMOTION_DIR, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=600)
            print(f"[demo] still {fr}: {'ok' if p.returncode == 0 else p.stderr[-800:]}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="the .mp4 to write")
    ap.add_argument("--captions", action="store_true", help="burn the narration's words in")
    ap.add_argument("--stills", default="", help="comma-separated frames to write as PNGs beside --out (no video)")
    ap.add_argument("--phone", action="store_true", help="also write <out>_phone.mp4 (1280 wide, CRF 26)")
    args = ap.parse_args()
    config.REMOTION_DIR = os.path.join(ROOT, "remotion")
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    work = tempfile.mkdtemp(prefix="dgdemo_", dir=os.path.dirname(out))
    doc = build(work, args.captions)
    with open(os.path.splitext(out)[0] + ".doc.json", "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
    for o in doc["overlays"]:
        d = o["data"]
        print(f"[demo] {o['template']:14s} {o['startFrame'] / FPS:5.2f}s +{o['durationInFrames'] / FPS:.2f}s  "
              f"{d['title']}: {d['latest']['value']} {d['unit']} ({d['source']}, {d['asOfLabel']})", flush=True)
    if args.stills:
        stills(doc, work, [int(x) for x in args.stills.split(",") if x.strip()], os.path.dirname(out))
        return 0
    renderer.render(doc, out, composition="Main", serve_dir=work)
    print(f"[demo] wrote {out} ({os.path.getsize(out) / 1e6:.1f} MB)", flush=True)
    if args.phone:
        # A small copy to watch on a phone: 1280 wide, CRF 26, sound as AAC, playable while it downloads.
        phone = os.path.splitext(out)[0] + "_phone.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", out, "-vf", "scale=1280:-2", "-c:v", "libx264",
                        "-crf", "26", "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                        "-movflags", "+faststart", phone], check=True)
        print(f"[demo] wrote {phone} ({os.path.getsize(phone) / 1e6:.1f} MB)", flush=True)
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
