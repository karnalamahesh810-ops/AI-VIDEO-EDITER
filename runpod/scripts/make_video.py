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
import io
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import handler  # noqa: E402
from src import config, render as renderer  # noqa: E402

BAR_W = 34

PREVIEW_HTML = """<!doctype html><meta charset=utf-8>
<title>render progress</title>
<style>
 :root{color-scheme:dark}
 body{font:15px/1.5 system-ui,sans-serif;background:#0d0d10;color:#eee;
      margin:0;display:grid;place-items:center;min-height:100vh}
 .card{width:min(680px,92vw)}
 h1{font-size:17px;font-weight:600;margin:0 0 18px}
 .track{height:26px;border-radius:13px;background:#26262e;overflow:hidden}
 .fill{height:100%;width:0;border-radius:13px;background:#FFD400;
       transition:width .4s ease}
 .row{display:flex;justify-content:space-between;margin-top:10px;
      font-variant-numeric:tabular-nums}
 .step{color:#9a9aa8}
 video{width:100%;margin-top:22px;border-radius:10px;display:none}
</style>
<div class=card>
 <h1>ThumbGenius render</h1>
 <div class=track><div class=fill id=f></div></div>
 <div class=row><span class=step id=s>starting...</span><span id=p>0%</span></div>
 <video id=v controls></video>
</div>
<script>
async function tick(){
 try{
  const r = await fetch('progress.json?t='+Date.now());
  const j = await r.json();
  document.getElementById('f').style.width = j.percent+'%';
  document.getElementById('p').textContent = j.percent+'%';
  document.getElementById('s').textContent = j.step + (j.eta ? ('  -  '+j.eta+' left') : '');
  if(j.done && j.video){
    const v = document.getElementById('v');
    if(!v.src){ v.src = j.video; v.style.display='block'; }
  }
 }catch(e){}
 setTimeout(tick, 1000);
}
tick();
</script>
"""


class BarReporter(handler.Reporter):
    """Reporter that draws a 0-100% bar and feeds preview.html.

    The worker's own Reporter prints one line per step. On a 20-minute video
    sourcing alone is hundreds of scenes over tens of minutes, so without a bar
    there is no way to tell steady progress from a hang. The same numbers are
    written to progress.json, which preview.html polls once a second and then
    swaps for the finished video.
    """

    def __init__(self, work_dir, out_path):
        super().__init__("")
        self.work = work_dir
        self.out = out_path
        self.pct = 0.0
        self.step = "starting"
        self.t0 = time.time()
        # scripts/preview_template.html is the real viewer (progress + a live
        # grid of every clip as it lands). PREVIEW_HTML is the bare fallback.
        tpl = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "preview_template.html")
        try:
            html = io.open(tpl, encoding="utf-8").read()
        except OSError:
            html = PREVIEW_HTML
        with open(os.path.join(work_dir, "preview.html"), "w", encoding="utf-8") as fh:
            fh.write(html)
        self._write()

    def _eta(self):
        if self.pct < 3:
            return ""
        left = (time.time() - self.t0) / self.pct * (100 - self.pct)
        return "%.0fm" % (left / 60) if left > 90 else "%.0fs" % left

    def _write(self, done=False):
        payload = {"percent": round(self.pct), "step": self.step,
                   "eta": self._eta(), "done": done,
                   "elapsed": round(time.time() - self.t0)}
        if done and os.path.exists(self.out):
            payload["video"] = os.path.relpath(self.out, self.work).replace(os.sep, "/")
        tmp = os.path.join(self.work, "progress.json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp, os.path.join(self.work, "progress.json"))

    def draw(self):
        filled = int(BAR_W * self.pct / 100)
        bar = "#" * filled + "." * (BAR_W - filled)
        eta = self._eta()
        tail = (" ETA %4s" % eta) if eta else " " * 9
        sys.stdout.write("\r[%s] %3.0f%%  %-44s%s" % (bar, self.pct, self.step[:44], tail))
        sys.stdout.flush()

    def __call__(self, step, progress=None, **fields):
        if progress is not None:
            self.pct = max(self.pct, float(progress))   # a bar must never go back
        self.step = step
        self._write()
        self.draw()

    def at(self, pct, step=""):
        """Set an exact percentage - used to map Remotion's 0..1 into 70..92."""
        self.pct = max(self.pct, float(pct))
        if step:
            self.step = step
        self._write()
        self.draw()

    def finish(self):
        self.pct, self.step = 100.0, "done"
        self._write(done=True)
        self.draw()
        sys.stdout.write("\n")



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
    ap.add_argument("--any-licence", action="store_true",
                    help="drop the Creative Commons filter — far better footage, "
                         "but the clips are someone else's copyright and can "
                         "attract Content ID claims on a monetised channel")
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
        "require_cc": not args.any_licence,
        "brand": {"accent": "#FFD400", "fontFamily": "Inter"},
    }

    started = time.time()
    report = BarReporter(work, out_path)
    print("progress: open " + os.path.join(work, "preview.html"), flush=True)
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
    # Remotion owns 70..92% of the bar; map its own 0..1 into that band.
    renderer.render(doc, out_path, composition="Main", serve_dir=work,
                    on_progress=lambda f: report.at(70 + 22 * f, "Rendering"))
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
    report.finish()
    print(f"  total           {(time.time() - started) / 60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
