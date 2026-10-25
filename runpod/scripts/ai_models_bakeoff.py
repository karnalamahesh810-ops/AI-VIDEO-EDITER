"""
AI fill model bake-off (2026-10-25): the cheapest picture and clip models for documentary b-roll, side by side,
with what each REALLY cost (OpenRouter's own usage.cost on every answer).

  * 3 b-roll prompts from different niches (history, finance, nature/news), written by hand (no paid prompt
    writer), on every candidate picture model;
  * one 5 s image-to-video clip per candidate clip model, all from the same start picture, with NO audio;
  * every file, results.json and a contact sheet (pictures, and the middle frame of each clip) go to
    C:\\ThumGenius\\docs\\ai-models-bakeoff\\ (or --out).

Safety:
  * It runs only when the OpenRouter balance (GET /api/v1/credits) is at least --min-balance ($3), and stops
    before any call whose projected price would take the run past --cap ($1.20). The cheapest calls go first.
  * The key comes from OPENROUTER_API_KEY or --key-file (JSON with "api_key"); it is never printed.
  * --dry-run (or a low balance) prints the plan and the projected cost and calls nothing paid.

    SKIP_DOTENV=1 python scripts/ai_models_bakeoff.py --dry-run
    SKIP_DOTENV=1 python scripts/ai_models_bakeoff.py --key-file <scratchpad>/openrouter_secret.json
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time

os.environ.setdefault("SKIP_DOTENV", "1")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import requests  # noqa: E402

from src.presenter import tiers  # noqa: E402
from src.presenter.providers import ImageRequest, OpenRouter, ProviderError, VideoRequest  # noqa: E402

DEFAULT_OUT = r"C:\ThumGenius\docs\ai-models-bakeoff"

# Written by hand (the owner's rule: test text is Claude's, not a paid model's). Same style rules as AI fill's
# prompts: one real documentary photograph, the story's place/era/light, no text, no logos, no famous faces.
PROMPTS = {
    "history": ("Photorealistic candid documentary photograph, 16:9: a wooden dock on the Erie Canal at dawn in "
                "1830, canal boats tied up with hemp ropes, barrels of flour stacked on the planks, a mule waiting on "
                "the towpath, low mist on the water. Natural early light, 35mm lens at eye level, real textures and "
                "wear. No readable text, no signs, no logos, no watermark. One real photograph, not an illustration."),
    "finance": ("Photorealistic candid documentary photograph, 16:9: a small family-run hardware store in a Midwest "
                "town, an empty checkout counter with an old cash register and a stack of unpaid invoices, late "
                "afternoon light through the front window, dust in the air. 50mm lens, gentle depth of field. No "
                "readable text on any paper or sign, no brand names, no logos, no watermark. One real photograph."),
    "nature": ("Photorealistic documentary news photograph, 16:9: a cracked, dried-up reservoir bed in the American "
               "Southwest, a white mineral 'bathtub ring' on the canyon walls far above the low water, a single "
               "abandoned boat ramp ending in dry mud, harsh midday sun. Wide 24mm lens, real textures. No people, "
               "no readable text, no logos, no watermark. One real photograph, not a render."),
}
CLIP_PROMPT = ("A slow, steady push-in over the scene; only small natural movement: a light breeze, drifting dust. "
               "Realistic documentary footage, natural light, steady camera, smooth natural motion at real speed. "
               "Nothing appears or disappears, nothing morphs, no text, no one walks into the frame.")

# [model, size]: the budget candidates first (cheapest), then today's defaults as the reference.
IMAGE_MODELS = [
    ("openai/gpt-5-image-mini", ""),
    ("google/gemini-3.1-flash-lite-image", "1K"),
    ("google/gemini-nano-banana-2.1", "1K"),
    ("google/gemini-2.5-flash-image", ""),
    ("google/gemini-nano-banana-2.1", "2K"),          # the old default (reference)
]
# [model, resolution]: 5 s each, no audio, from the same start picture.
VIDEO_MODELS = [
    ("bytedance/seedance-1-5-pro", "480p"),
    ("heygen/heygen-video-1", "480p"),
    ("x-ai/grok-imagine-video-1.5-lite", "480p"),
    ("bytedance/seedance-1-5-pro", "720p"),           # the old default (reference)
    ("google/veo-3.1-lite", "720p"),
]
DEAR_VIDEO_MODELS = [                                  # only with --include-dear (past the default cap)
    ("bytedance/seedance-2.0-mini", "480p"),
    ("kwaivgi/kling-v3.0-std", "720p"),
]
CLIP_SECONDS = 5


def projected_image(model: str, size: str) -> float:
    return tiers.image_usd(model, size) if tiers.model_info(model) else 0.08


def projected_clip(model: str, res: str, seconds: int = CLIP_SECONDS) -> float:
    durations = sorted(int(d) for d in (tiers.model_info(model).get("durations") or [seconds]))
    secs = next((d for d in durations if d >= seconds), durations[-1])
    return round(secs * tiers.usd_per_second(model, res), 4)


def load_key(path: str) -> str:
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if key:
        return key
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return str(json.load(fh).get("api_key") or "").strip()
    return ""


def balance(key: str) -> float:
    r = requests.get("https://openrouter.ai/api/v1/credits", headers={"Authorization": f"Bearer {key}"}, timeout=30)
    r.raise_for_status()
    d = r.json().get("data") or {}
    return round(float(d.get("total_credits") or 0) - float(d.get("total_usage") or 0), 4)


def slug(model: str, size: str) -> str:
    return (model.split("/", 1)[-1] + (f"_{size}" if size else "")).replace(".", "-")


def middle_frame(video: str, out: str) -> str:
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video],
                           capture_output=True, text=True, timeout=30)
        mid = max(0.0, float((p.stdout or "0").strip() or 0) / 2)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{mid:.2f}", "-i", video, "-frames:v", "1", out],
                       check=True, timeout=60)
        return out
    except Exception:  # noqa: BLE001
        return ""


def probe_size(video: str) -> str:
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0:s=x", video], capture_output=True, text=True,
                           timeout=30)
        return (p.stdout or "").strip().split("\n")[0]
    except Exception:  # noqa: BLE001
        return ""


def has_audio(video: str) -> bool:
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                            "-of", "csv=p=0", video], capture_output=True, text=True, timeout=30)
        return bool((p.stdout or "").strip())
    except Exception:  # noqa: BLE001
        return False


def contact_sheet(rows: list, out: str) -> str:
    """One labelled grid: a row per model, its pictures (or its clip's middle frame), with the measured cost."""
    from PIL import Image, ImageDraw
    tw, th, label_h, pad = 480, 270, 46, 10
    cols = max([len(r["files"]) for r in rows] + [1])
    sheet = Image.new("RGB", (pad + cols * (tw + pad), pad + len(rows) * (th + label_h + pad)), (18, 18, 18))
    draw = ImageDraw.Draw(sheet)
    for i, r in enumerate(rows):
        y = pad + i * (th + label_h + pad)
        draw.text((pad, y + 4), r["label"], fill=(240, 240, 240))
        draw.text((pad, y + 22), r["note"], fill=(200, 190, 120))
        for j, f in enumerate(r["files"]):
            if not f or not os.path.isfile(f):
                continue
            try:
                with Image.open(f) as im:
                    im = im.convert("RGB")
                    im.thumbnail((tw, th))
                    sheet.paste(im, (pad + j * (tw + pad), y + label_h))
            except Exception:  # noqa: BLE001
                continue
    sheet.save(out, "JPEG", quality=90)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--key-file", default="")
    ap.add_argument("--cap", type=float, default=1.20, help="the most the run may spend (USD)")
    ap.add_argument("--min-balance", type=float, default=3.0, help="run only with at least this balance (USD)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--include-dear", action="store_true", help="also Seedance 2.0 Mini and Kling 3.0 Std")
    args = ap.parse_args()

    videos = VIDEO_MODELS + (DEAR_VIDEO_MODELS if args.include_dear else [])
    plan = [("image", m, s, n) for m, s in sorted(IMAGE_MODELS, key=lambda x: projected_image(*x)) for n in PROMPTS]
    plan += [("clip", m, r, "nature") for m, r in sorted(videos, key=lambda x: projected_clip(*x))]
    projected = sum(projected_image(m, s) if k == "image" else projected_clip(m, s) for k, m, s, _n in plan)
    print(f"plan: {sum(1 for p in plan if p[0] == 'image')} pictures, {sum(1 for p in plan if p[0] == 'clip')} clips, "
          f"projected ${projected:.2f} (cap ${args.cap:.2f}; the start picture is the first picture made)")
    for k, m, s, n in plan:
        usd = projected_image(m, s) if k == "image" else projected_clip(m, s)
        print(f"  {k:5} {m:40} {s or '-':5} {n:8} ~${usd:.3f}")

    key = load_key(args.key_file)
    if not key:
        print("no OpenRouter key (OPENROUTER_API_KEY or --key-file): stopping before any call")
        return 2
    have = balance(key)
    print(f"OpenRouter balance: ${have:.2f} (needs ${args.min_balance:.2f})")
    if args.dry_run or have < args.min_balance:
        print("dry run: nothing paid" if args.dry_run else "balance too low: nothing paid. Top up and run again.")
        return 0 if args.dry_run else 3

    os.makedirs(args.out, exist_ok=True)
    prov = OpenRouter(key=key)
    spent, results, start_frame = 0.0, [], None
    for kind, model, size, niche in plan:
        usd_guess = projected_image(model, size) if kind == "image" else projected_clip(model, size)
        if spent + usd_guess * 1.2 > args.cap:
            results.append({"kind": kind, "model": model, "size": size, "niche": niche, "skipped": "the cap"})
            print(f"skip {model} {size} {niche}: would pass the ${args.cap:.2f} cap (spent ${spent:.3f})")
            continue
        name = f"{kind}_{slug(model, size)}_{niche}"
        row = {"kind": kind, "model": model, "size": size, "niche": niche, "projectedUsd": usd_guess}
        t0 = time.time()
        try:
            if kind == "image":
                res = prov.image(ImageRequest(model=model, prompt=PROMPTS[niche], size=size, aspect_ratio="16:9"))
                path = os.path.join(args.out, name + res.ext)
                with open(path, "wb") as fh:
                    fh.write(res.data)
                row.update(usd=res.cost, file=path)
                # The clips start from the budget default's picture (Nano Banana 2.1 at 1K), else any nature one.
                if niche == "nature" and (start_frame is None or (model, size) == ("google/gemini-nano-banana-2.1",
                                                                                   "1K")):
                    start_frame = path
            else:
                if not start_frame:
                    raise ProviderError("no start picture was made")
                with open(start_frame, "rb") as fh:
                    mime = "image/png" if start_frame.endswith(".png") else "image/jpeg"
                    link = f"data:{mime};base64,{base64.b64encode(fh.read()).decode('ascii')}"
                secs = int(projected_clip(model, size) / max(tiers.usd_per_second(model, size), 1e-9) + 0.5)
                req = VideoRequest(model=model, prompt=CLIP_PROMPT, resolution=size, aspect_ratio="16:9",
                                   duration=secs or CLIP_SECONDS, first_frame=link,
                                   generate_audio=tiers.generate_audio_param(model))
                job = prov.submit_video(req)
                got = prov.wait_video(job, timeout=900, poll=8)
                if got.status != "completed":
                    raise ProviderError(f"{got.status}: {got.error[:160]}")
                path = os.path.join(args.out, name + ".mp4")
                prov.download_video(job, got, path)
                frame = middle_frame(path, os.path.join(args.out, name + "_mid.jpg"))
                row.update(usd=got.cost, file=path, frame=frame, seconds=secs, size_px=probe_size(path),
                           audio=has_audio(path), generateAudio=req.generate_audio)
        except Exception as e:  # noqa: BLE001 - recorded; the run goes on
            row["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        row["wallSeconds"] = round(time.time() - t0, 1)
        if row.get("usd") is None and "file" in row:
            row["usd"] = usd_guess
            row["usdEstimated"] = True
        spent += float(row.get("usd") or 0.0) if "error" not in row else 0.0
        results.append(row)
        print(f"{kind} {model} {size} {niche}: " + (f"${row['usd']:.4f}" if row.get("usd") is not None else
                                                   row.get("error", "")))
        with open(os.path.join(args.out, "results.json"), "w", encoding="utf-8") as fh:
            json.dump({"spentUsd": round(spent, 4), "capUsd": args.cap, "rows": results}, fh, indent=1)

    # The contact sheet: a row per picture model (history, finance, nature), then a row of clip middle frames.
    rows = []
    for model, size in IMAGE_MODELS:
        mine = [r for r in results if r["kind"] == "image" and r["model"] == model and r["size"] == size]
        usd = [r["usd"] for r in mine if r.get("usd") is not None]
        note = (f"avg ${sum(usd) / len(usd):.4f} a picture (measured)" if usd else
                "; ".join(r.get("error") or r.get("skipped") or "" for r in mine)[:90])
        rows.append({"label": f"{model} {size}".strip(), "note": note,
                     "files": [next((r.get("file") for r in mine if r["niche"] == n), "") for n in PROMPTS]})
    clips = [r for r in results if r["kind"] == "clip"]
    rows.append({"label": "clips (middle frame), same start picture, no audio",
                 "note": " | ".join(f"{r['model'].split('/')[-1]} {r['size']}: "
                                    + (f"${r['usd']:.3f}" if r.get("usd") is not None else "-") for r in clips)[:150],
                 "files": [r.get("frame", "") for r in clips]})
    sheet = contact_sheet(rows, os.path.join(args.out, "contact_sheet.jpg"))
    print(f"spent ${spent:.3f} of the ${args.cap:.2f} cap; contact sheet {sheet}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
