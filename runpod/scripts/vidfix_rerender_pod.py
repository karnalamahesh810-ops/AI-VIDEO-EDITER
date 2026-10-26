"""
Before / after re-render of a few problem scenes of a finished video (docs/vidfix-2026-10-26.md). Runs ON a
throwaway 16-vCPU cpu3c pod started from the LIVE worker image (no template, no keys needed):

  1. BEFORE: the scene windows cut from the saved timeline (DOC_URL, the document as built) and rendered by the
     image's own renderer, exactly as the video was;
  2. the branch's changed files are fetched from GitHub at BRANCH_SHA over the image (BRANCH_FILES, under runpod/);
  3. AFTER: the same windows with the branch's passes re-applied where a re-plan is not needed - src/stillframe.py
     (portrait cards, moves held to real detail), editing v3's still rule (no punch or detail framing past the
     detail), the smart-spec type sizes (motionspec._SIZES / COUNTER_SIZE / LABEL_SIZE mapped onto the compiled
     layers, the label's dark panel dropped) - and rendered by the branch's renderer (the Remotion bundle is keyed
     on remotion/src, so it rebuilds); kinetic numbers get the new typeScale.json in the renderer itself.
  4. A contact sheet (frames every 1.5 s, before | after) and the mp4s are served on :8888 (index.json, log.txt).

Sourcing changes (stills to clips, slop channels, proxies) need a new build of the video, not a re-render.

Env: DOC_URL (the saved timeline JSON: {"top": {...}, "scenes": [...]}, or a timeline itself), BRANCH_SHA,
BRANCH_FILES (comma list), WINDOWS (JSON [[label, first scene, last scene], ...]; scene numbers 0-based).
Local dry run (no render): python vidfix_rerender_pod.py --dry DOC.json
"""
import copy
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

OUT = "/tmp/vidfix"
APP = "/app"
REPO = "https://raw.githubusercontent.com/karnalamahesh810-ops/ai-video-editer"
DEFAULT_WINDOWS = [["jack-schmidt-portrait", 58, 60], ["number-1037", 2, 4], ["still-run-1620", 183, 191],
                   ["reveal-soft-picture", 62, 66], ["statement-nearly-10-to-1", 106, 108]]
# old compiled smart-spec sizes -> the branch's (src/motionspec.py, 2026-10-26)
TEXT_SIZE = {0.048: 0.04, 0.068: 0.05, 0.075: 0.055, 0.095: 0.062, 0.13: 0.075}
LOG_LINES = []


def log(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    LOG_LINES.append(line)
    if os.path.isdir(OUT):
        with open(os.path.join(OUT, "log.txt"), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def load_doc(src: str) -> dict:
    raw = urllib.request.urlopen(src, timeout=120).read() if src.startswith("http") else open(src, "rb").read()
    d = json.loads(raw)
    if "rows" in d:                                   # a saved query result
        d = d["rows"][0]["r"]
    if "scenes" in d and "top" in d:                  # the vidfix extract: top-level fields + scenes
        doc = dict(d["top"])
        doc["scenes"] = d["scenes"]
        doc["meta"] = d.get("meta") or {}
        return doc
    return d


def window(doc: dict, first: int, last: int) -> dict:
    """Scenes first..last re-timed to start at frame 0, the overlays over them shifted, no narration or music."""
    scenes = doc["scenes"][first:last + 1]
    a = int(scenes[0]["startFrame"])
    b = int(scenes[-1]["startFrame"]) + int(scenes[-1]["durationInFrames"])
    out = {k: copy.deepcopy(v) for k, v in doc.items() if k not in ("scenes", "overlays", "captions", "sfx", "meta")}
    out["scenes"] = []
    for s in scenes:
        s = copy.deepcopy(s)
        s["startFrame"] = int(s["startFrame"]) - a
        out["scenes"].append(s)
    out["overlays"] = []
    for o in doc.get("overlays") or []:
        s0 = int(o.get("startFrame") or 0)
        s1 = s0 + int(o.get("durationInFrames") or 0)
        if s1 <= a or s0 >= b:
            continue
        o = copy.deepcopy(o)
        o["startFrame"] = max(0, s0 - a)
        o["durationInFrames"] = min(s1, b) - max(s0, a)
        out["overlays"].append(o)
    out["durationInFrames"] = b - a
    out["audio"] = None
    out["bgm"] = None
    out["music"] = None
    out["sfx"] = []
    out["sfxEnabled"] = False
    out["captions"] = []
    out["meta"] = {"window": [first, last]}
    return out


def fetch_media(doc: dict, work: str) -> None:
    """Every picture and clip of the window to local files (the passes read pixels; the render serves them)."""
    os.makedirs(work, exist_ok=True)
    for s in doc["scenes"]:
        m = s.get("media") or {}
        url = str(m.get("url") or "")
        if not url.startswith("http"):
            continue
        name = os.path.join(work, os.path.basename(url.split("?")[0]))
        if not os.path.exists(name):
            urllib.request.urlretrieve(url, name)
        m["url"] = name


def after(doc: dict) -> dict:
    """The branch's passes that need no re-plan, over a window whose media is local."""
    sys.path.insert(0, APP)
    from src import editing, stillframe  # noqa: E402 - the patched files
    doc = copy.deepcopy(doc)
    report = {"stillFrame": stillframe.place(doc)}
    # editing v3's still rule: a punch or a detail framing past the picture's detail goes
    dropped = 0
    for s in doc["scenes"]:
        if (s.get("media") or {}).get("type") != "image" or not s.get("keyframes"):
            continue
        if editing.still_room(s) < editing.PUNCH_SCALE_HOOK + 0.02:
            s.pop("keyframes", None)
            s.pop("motionBlur", None)
            (s.get("semanticMetadata") or {}).pop("punch", None)
            dropped += 1
    report["punchesDropped"] = dropped
    # the smart spec's type, as the branch compiles it
    resized = 0
    for o in doc.get("overlays") or []:
        kind = str(((o.get("smart") or {}).get("design") or {}).get("kind") or "")
        for L in (o.get("spec") or {}).get("layers") or []:
            sz = L.get("size")
            if not isinstance(sz, (int, float)):
                continue
            if L.get("kind") == "counter":
                L["size"] = 0.1 if sz >= 0.08 else 0.06
            elif kind in ("label", "place", "spot"):
                L["size"] = min(sz, 0.038)
                L.pop("panel", None)
            else:
                L["size"] = TEXT_SIZE.get(round(sz, 3), round(min(sz, 0.075), 4))
            resized += 1
    report["layersResized"] = resized
    # round 2: every date top left, looks end at their cut, AI scenes labelled
    from src import aifill, lookplace  # noqa: E402
    for o in doc.get("overlays") or []:
        if str(o.get("template") or "") in lookplace.KT_SELF_BACKED:
            o["zone"] = "upper-left"
    report["lookEnds"] = editing.end_at_cuts(doc)
    report["aiLabels"] = aifill.label_scenes(doc)
    doc["meta"]["vidfix"] = report
    return doc


def render(doc: dict, out: str) -> str:
    sys.path.insert(0, APP)
    from src import render as r  # noqa: E402
    return r.render(doc, out, muted=True)


def sheet(pairs, out_jpg: str) -> None:
    from PIL import Image, ImageDraw
    rows = []
    for label, a, b in pairs:
        for path in (a, b):
            d = os.path.splitext(path)[0] + "_f"
            os.makedirs(d, exist_ok=True)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, "-vf", "fps=1/1.5,scale=480:-2",
                            os.path.join(d, "f_%03d.jpg")], check=False)
        fa = sorted(os.listdir(os.path.splitext(a)[0] + "_f"))
        fb = sorted(os.listdir(os.path.splitext(b)[0] + "_f"))
        rows.append((label, [os.path.join(os.path.splitext(a)[0] + "_f", f) for f in fa],
                     [os.path.join(os.path.splitext(b)[0] + "_f", f) for f in fb]))
    cols = max(len(x[1]) for x in rows)
    W, H = 480, 270
    img = Image.new("RGB", (W * cols, (H * 2 + 24) * len(rows)), (16, 16, 18))
    d = ImageDraw.Draw(img)
    for k, (label, fa, fb) in enumerate(rows):
        y = k * (H * 2 + 24)
        d.text((6, y + 4), f"{label}: BEFORE (top) / AFTER (bottom)", fill=(255, 230, 80))
        for j, p in enumerate(fa):
            img.paste(Image.open(p).resize((W, H)), (j * W, y + 24))
        for j, p in enumerate(fb):
            img.paste(Image.open(p).resize((W, H)), (j * W, y + 24 + H))
    img.save(out_jpg, quality=80)


def serve() -> None:
    import http.server
    import socketserver
    with socketserver.TCPServer(("", 8888), lambda *a, **k: http.server.SimpleHTTPRequestHandler(
            *a, directory=OUT, **k)) as httpd:
        httpd.serve_forever()


def main() -> None:
    if "--dry" in sys.argv:
        doc = load_doc(sys.argv[sys.argv.index("--dry") + 1])
        for label, a, b in DEFAULT_WINDOWS:
            w = window(doc, a, b)
            print(label, len(w["scenes"]), "scenes", w["durationInFrames"], "frames", len(w["overlays"]), "overlays")
        return
    os.makedirs(OUT, exist_ok=True)
    threading.Thread(target=serve, daemon=True).start()
    index = {"started": time.time(), "windows": []}
    try:
        doc = load_doc(os.environ["DOC_URL"])
        wins = json.loads(os.environ.get("WINDOWS") or "null") or DEFAULT_WINDOWS
        work = os.path.join(OUT, "media")
        cuts = []
        for label, a, b in wins:
            w = window(doc, int(a), int(b))
            fetch_media(w, work)
            cuts.append((label, w))
        # 1. BEFORE with the image's own renderer
        pairs = []
        for label, w in cuts:
            t = time.time()
            pb = render(w, os.path.join(OUT, f"{label}_before.mp4"))
            log("before", label, round(time.time() - t, 1), "s")
            pairs.append([label, pb, None])
        # 2. the branch over the image
        for f in os.environ["BRANCH_FILES"].split(","):
            data = urllib.request.urlopen(f"{REPO}/{os.environ['BRANCH_SHA']}/runpod/{f}", timeout=60).read()
            with open(os.path.join(APP, f), "wb") as fh:
                fh.write(data)
            log("patched", f, len(data))
        for mod in [m for m in list(sys.modules) if m == "src" or m.startswith("src.")]:
            del sys.modules[mod]                    # the patched python, not the image's
        # 3. AFTER
        for k, (label, w) in enumerate(cuts):
            t = time.time()
            aw = after(w)
            pa = render(aw, os.path.join(OUT, f"{label}_after.mp4"))
            log("after", label, round(time.time() - t, 1), "s", json.dumps(aw["meta"].get("vidfix")))
            pairs[k][2] = pa
            index["windows"].append({"label": label, "before": os.path.basename(pairs[k][1]),
                                     "after": os.path.basename(pa), "report": aw["meta"].get("vidfix")})
        sheet(pairs, os.path.join(OUT, "before_after_sheet.jpg"))
        index["sheet"] = "before_after_sheet.jpg"
    except Exception as e:  # noqa: BLE001 - reported on :8888
        import traceback
        index["error"] = f"{type(e).__name__}: {e}"
        log(traceback.format_exc())
    index["done"] = time.time()
    with open(os.path.join(OUT, "index.json"), "w") as fh:
        json.dump(index, fh, indent=1, default=str)
    log("done")
    while True:                                     # keep serving until the pod is deleted
        time.sleep(60)


if __name__ == "__main__":
    main()
