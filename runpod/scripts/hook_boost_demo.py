"""Offline do_plan driver: HOOK_BOOST off vs on on the Lake Mead narration (scratch version)."""
import hashlib
import json
import os
import subprocess
import sys

os.environ["SKIP_DOTENV"] = "1"
ROOT = os.getcwd()
sys.path.insert(0, ROOT)
import handler  # noqa: E402
from src import config, media, transcribe  # noqa: E402
from src.media import MediaAsset  # noqa: E402

with open(os.path.join(ROOT, "tests", "fixtures", "words_lake_mead.json"), encoding="utf-8") as fh:
    FIX = json.load(fh)
WORDS = [transcribe.Word(text=t, start=s, end=e) for t, s, e in FIX["words"]]
OUT = os.path.join(os.environ.get("DEMO_OUT", os.path.join(ROOT, "out", "hook_boost_demo")))
os.makedirs(OUT, exist_ok=True)

DRAMA = ["aerial view of the empty reservoir, a white bathtub ring on the canyon walls",
         "wide shot of boats and people at a dry marina", "close view of cracked mud and a receding shoreline",
         "drone flyover of the dam with water rushing through the spillway", "residents walking along dry gravel"]


def fake_clip(path, seconds, hue):
    if os.path.isfile(path):
        return path
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", f"testsrc2=size=640x360:rate=30:duration={seconds:.2f}",
                    "-vf", f"hue=h={hue}", "-pix_fmt", "yuv420p", path], check=True)
    return path


def fake_source_many(jobs, work_dir, **kw):
    """One distinct local clip per line, scored like a judged one (stand-in for the network)."""
    results = []
    for j in sorted(jobs, key=lambda j: j["index"]):
        key = hashlib.md5(f"{j['index']}:{j['query']}".encode()).hexdigest()
        seconds = max(3.0, float(j.get("seconds") or 4.0) + 1.0)
        path = fake_clip(os.path.join(work_dir, f"clip_{j['index']:03d}.mp4"), seconds, (int(key[:4], 16) % 360))
        rel = 0.72 + (int(key[4:8], 16) % 24) / 100.0
        vid = "".join(c for c in key if c.isalnum())[:11].ljust(11, "x")
        results.append(MediaAsset(
            kind="video", source="youtube", url=f"https://www.youtube.com/watch?v={vid}&t=10", local_path=path,
            duration=seconds, query=j["query"], relevance_score=round(rel, 2), quality=0.7,
            content_description=DRAMA[int(key[8:10], 16) % len(DRAMA)], specificity="event",
            moment={"start": 10.0}, license="CC BY (demo)", attribution="demo clip"))
    return results


def run(flag, teaser=False, tag=""):
    config.HOOK_BOOST = flag
    config.HOOK_TEASER = teaser
    work = os.path.join(OUT, f"job_{tag or ('on' if flag else 'off')}")
    os.makedirs(work, exist_ok=True)
    audio = os.path.join(work, "narration.mp3")
    if not os.path.isfile(audio):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        f"sine=frequency=220:duration={FIX['duration']:.2f}", "-af", "volume=0.05",
                        "-c:a", "libmp3lame", audio], check=True)
    transcribe.transcribe_words = lambda path, language=None, on_progress=None: WORDS
    media.source_many = fake_source_many
    inp = {"audio_path": audio, "title": "Lake Mead is running dry", "width": 960, "height": 540, "fps": 30,
           "maps": False, "allow_youtube": False, "source_workers": 2, "captions": False}
    doc = handler.do_plan(inp, work, handler.Reporter(""))
    return doc, work


def table(doc, seconds=30.0):
    rows = []
    fps = doc["fps"]
    for sc in doc["scenes"]:
        if sc["startFrame"] / fps >= seconds:
            break
        sem = sc.get("semanticMetadata") or {}
        rows.append((sc["id"], round(sc["startFrame"] / fps, 2), round(sc["durationInFrames"] / fps, 2),
                     os.path.basename(sc["media"].get("url") or "") or sc["media"].get("type"),
                     sem.get("relevanceScore"), "T" if sc.get("teaser") else "", sc.get("transition"),
                     "push" if sc.get("reframe") else (sc.get("motion") if sc.get("motion") != "none" else ""),
                     sc.get("text", "")[:48]))
    return rows


if __name__ == "__main__":
    for flag in (False, True):
        doc, work = run(flag)
        print("=== HOOK_BOOST", flag, "scenes", doc["meta"]["sceneCount"], "cuts/min", doc["meta"]["cutsPerMinute"])
        for r in table(doc):
            print("  ", r)
        print("  meta.hookBoost:", json.dumps(doc["meta"].get("hookBoost"), default=str)[:600])
        print("  sfx(transition):", [(fx["name"], fx["startFrame"], fx["volume"]) for fx in doc["sfx"]
                                      if fx.get("kind") == "transition"][:6], "sfxVolume", doc["sfxVolume"])
