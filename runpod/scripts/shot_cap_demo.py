"""
Offline before/after for the shot cap (src/shotcap.py, SHOT_MAX_SECONDS): a
synthetic plan built from the benchmark narrations' real whisper timings,
with every n-th line left unsourced the way a real job leaves lines empty.

    cd runpod && SKIP_DOTENV=1 python scripts/shot_cap_demo.py [--empty-every 7] [--repeat 4]

No network, no ffmpeg: the clips are stand-ins with a recorded length. Prints
each setting's shot count, shots over 7 s, longest and average shot, holds and
text cards, the cuts per minute and the share of cuts that close a sentence
or a clause.
"""
import argparse
import json
import os
import sys
from unittest import mock

os.environ.setdefault("SKIP_DOTENV", "1")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import config, gapfill, shotcap, timeline, transcribe  # noqa: E402
from src.media import MediaAsset  # noqa: E402
from src.transcribe import Word  # noqa: E402

FPS = 30


def narration(repeat: int):
    """The two benchmark narrations, one after the other, `repeat` times: a few minutes of real word timings."""
    words, t = [], 0.0
    for _ in range(repeat):
        for name in ("lake_mead", "new_mexico_flash_flood"):
            with open(os.path.join(ROOT, "tests", "fixtures", f"words_{name}.json"), encoding="utf-8") as fh:
                d = json.load(fh)
            words += [Word(w, t + s, t + e) for w, s, e in d["words"]]
            t += float(d["duration"]) + 0.6
    return words, t


def assets_for(segments, empty_every: int):
    """A distinct stand-in picture per beat (a clip as long as its shot plus the usual pad); every n-th line empty."""
    out = []
    for i, seg in enumerate(segments):
        if empty_every and (i + 3) % empty_every == 0:
            out.append(None)
            continue
        if i % 3 == 0:
            out.append(MediaAsset(kind="image", source="wikimedia", url=f"https://x/p{i}.jpg",
                                  local_path=f"/w/p{i}.jpg"))
        else:
            out.append(MediaAsset(kind="video", source="youtube", url=f"https://www.youtube.com/watch?v=V{i:010d}&t=10",
                                  local_path=f"/w/c{i}.mp4", duration=round(float(seg.duration) + 0.5, 2),
                                  moment={"start": 10.0}))
    return out


def run(cap_seconds: float, words, total: float, empty_every: int) -> dict:
    with mock.patch.multiple(config, SHOT_MAX_SECONDS=cap_seconds, TREATMENTS=False, TRANSITION_PACK=False,
                             ANIMATION_FILL=False, HOOK_SECONDS=0.0, MENTION_CUTS=False, HOOK_BOOST=False):
        segs = transcribe.segment_words(words, origin=0.0, until=total)
        segs, _, info = shotcap.prepare(segs, {}, {}, until=total)
        shots = [{"query": f"q{i}", "visualType": "footage", "overlay": None} for i in range(len(segs))]
        assets = assets_for(segs, empty_every)
        doc = timeline.build(segs, shots, assets, audio_url="file:///tmp/vo.mp3", audio_duration=total,
                             inp={"voice_lufs": -20.0, "fps": FPS})
        last = gapfill.hold_or_animate(doc, laddered=True)
        lengths = [s["durationInFrames"] / FPS for s in doc["scenes"] if shotcap.is_shot(s)]
        ends = [s.words[-1].text for s in segs[:-1]]
        good = sum(1 for t in ends if t.rstrip("\"')").endswith((".", "!", "?", ",", ";", ":")))
        return {"cap": cap_seconds, "beats": len(segs), "shots": len(lengths),
                "over7": sum(1 for x in lengths if x > 7.0 + 2 / FPS),
                "longest": round(max(lengths), 2), "average": round(sum(lengths) / len(lengths), 2),
                "cutsPerMinute": round(len(doc["scenes"]) / (total / 60.0), 1),
                "goodCuts": round(good / max(1, len(ends)), 2),
                "empty": sum(1 for a in assets if a is None), "held": last["held"], "cards": last["card"],
                "alternatives": last.get("alternative", 0), "cut": info.get("cut", 0),
                "report": shotcap.report(doc, info) if cap_seconds else None}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--empty-every", type=int, default=7, help="every n-th line is left unsourced (0 = none)")
    ap.add_argument("--repeat", type=int, default=4, help="how many times the two narrations are strung together")
    args = ap.parse_args()
    words, total = narration(args.repeat)
    print(f"narration: {len(words)} words, {total / 60:.1f} min; cutter {config.MIN_SCENE_SECONDS:g}/"
          f"{config.TARGET_SCENE_SECONDS:g}/{config.MAX_SCENE_SECONDS:g} s")
    for cap in (0.0, 7.0):
        r = run(cap, words, total, args.empty_every)
        print(f"SHOT_MAX_SECONDS={cap:g}: {r['beats']} beats -> {r['shots']} shots of footage/stills, "
              f"{r['over7']} over 7 s, longest {r['longest']} s, average {r['average']} s, "
              f"{r['cutsPerMinute']} cuts/min, {int(r['goodCuts'] * 100)}% of cuts close a sentence or clause; "
              f"{r['empty']} empty lines -> {r['held']} held, {r['alternatives']} runner-ups, {r['cards']} text cards")
        if r["report"]:
            print("  meta.shotCap:", json.dumps({k: v for k, v in r["report"].items() if k != "examples"}))
