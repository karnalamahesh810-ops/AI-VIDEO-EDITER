"""
The seven-script footage benchmark.

Runs the worker's `plan` action on the benchmark narrations baked into the
image (bench/audio, audio_url "bench://<case>") and scores what came back:
scene fill, entity and location accuracy, visual relevance, moment score,
duplicates, generic-footage rate on event scenes, candidates per scene,
winning score, time and cost. Every run is appended to bench/results.jsonl
with a label and the git sha, so runs can be compared across phases.

    python scripts/bench.py --label "A: pool on" --cases all
    python scripts/bench.py --label "A: pool off" --config CANDIDATE_POOL=0
    python scripts/bench.py --report            # table of every recorded run

Needs RUNPOD_API_KEY (from .env) and the endpoint id. Never prints keys.
"""
import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import threading

# Windows consoles default to cp1252; a metrics line with a non-Latin
# character must not kill a benchmark run after the job has finished.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
import time
from typing import Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src import intent as scene_intent  # noqa: E402

CASES_DIR = os.path.join(ROOT, "bench", "cases")
RESULTS = os.path.join(ROOT, "bench", "results.jsonl")
ENDPOINT = os.getenv("RUNPOD_ENDPOINT_ID", "tuxcziwby5plod")
CREDIT_USD = 0.005          # one Kie credit
RUNPOD_USD_PER_WORKER_SECOND = 0.49 / 3600   # cpu5c-32-64 list price


def _env() -> Dict[str, str]:
    out = dict(os.environ)
    for path in (os.path.join(ROOT, "..", ".env"), os.path.join(ROOT, ".env")):
        if os.path.isfile(path):
            for line in open(path, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    out.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return out


def load_cases(names: Optional[List[str]] = None) -> List[dict]:
    cases = []
    for fn in sorted(os.listdir(CASES_DIR)):
        if fn.endswith(".json"):
            with open(os.path.join(CASES_DIR, fn), encoding="utf-8") as fh:
                c = json.load(fh)
            if not names or c["name"] in names:
                cases.append(c)
    return cases


# ------------------------------------------------------------------ scoring
def _hits(text: str, phrases: List[str]) -> bool:
    tw = scene_intent._words(text)
    return any(scene_intent._phrase_hit(p, tw) for p in phrases if p)


def _ai_usd(costs: dict) -> Optional[float]:
    """What the job's model calls cost (OpenRouter's own usage.cost, src/costs.py): vision + planning +
    pictures (+ the presenter's generated video). None for a job that returned no ledger."""
    if not isinstance(costs, dict) or "total" not in costs:
        return None
    return sum(float(costs.get(k) or 0.0) for k in ("vision", "llm", "image", "presenter", "aivideo"))


def score_timeline(doc: dict, case: dict, elapsed: float = 0.0, costs: Optional[dict] = None) -> dict:
    """Metrics for one finished plan. Pure: unit-tested on synthetic timelines.

    `costs`: the job's ledger (the result's "costs", also kept as meta.costs). With it, ai_usd is what the
    job's model calls really cost (OpenRouter prices each call) and runpod_usd the worker's seconds at its
    own rate; without it (an old timeline), the Kie-credit estimate and the wall-time guess as before."""
    scenes = doc.get("scenes") or []
    meta = doc.get("meta") or {}
    n = len(scenes)
    filled = [s for s in scenes if (s.get("media") or {}).get("url")
              and (s.get("media") or {}).get("type") in ("video", "image")]
    videos = [s for s in filled if s["media"].get("type") == "video"]
    images = [s for s in filled if s["media"].get("type") == "image"]

    def frames(group):
        return sum(float(s.get("durationInFrames") or 0) for s in group)

    def sem(s):
        return s.get("semanticMetadata") or {}

    def seen_text(s):
        m = s.get("media") or {}
        return " ".join([sem(s).get("contentDescription") or "", m.get("attribution") or ""])

    ent_scenes = [s for s in filled if (sem(s).get("sceneIntent") or {}).get("entities")]
    ent_ok = [s for s in ent_scenes if _hits(seen_text(s), sem(s)["sceneIntent"]["entities"])]
    loc_scenes = [s for s in filled if (sem(s).get("sceneIntent") or {}).get("locations")]
    loc_ok = [s for s in loc_scenes if _hits(seen_text(s), sem(s)["sceneIntent"]["locations"])]
    case_ok = [s for s in filled if _hits(seen_text(s), case.get("entities") or [])]
    rel = [float(sem(s).get("relevanceScore")) for s in filled if sem(s).get("relevanceScore") is not None]
    fin = [float(sem(s).get("finalScore")) for s in filled if sem(s).get("finalScore") is not None]
    ts = [float((sem(s).get("scoreParts") or {}).get("timestamp"))
          for s in filled if (sem(s).get("scoreParts") or {}).get("timestamp") is not None]
    ids = [sem(s).get("assetId") for s in videos if sem(s).get("assetId")]
    event_scenes = [s for s in filled if (sem(s).get("sceneIntent") or {}).get("specificity") == "event"]
    generic = [s for s in event_scenes if sem(s).get("specificity") == "generic"]
    cands = [float((sem(s).get("candidates") or {}).get("candidates"))
             for s in filled if (sem(s).get("candidates") or {}).get("candidates") is not None]
    usage = meta.get("aiUsage") or {}
    ledger = costs if isinstance(costs, dict) and costs else (meta.get("costs") or {})
    ai_usd = _ai_usd(ledger)
    if ai_usd is None:
        ai_usd = float(usage.get("estimatedCredits") or 0) * CREDIT_USD
    if isinstance(ledger, dict) and ledger.get("runpod") is not None:
        runpod_usd = float(ledger.get("runpod") or 0.0)
    else:
        fanout = (meta.get("sourcing") or {}).get("fanout") or meta.get("fanout") or {}
        workers = 1 + int(fanout.get("parts") or 0)
        runpod_usd = elapsed * RUNPOD_USD_PER_WORKER_SECOND * max(1, min(workers, 10)) * 0.6
    treatments = meta.get("treatments") or {}
    total_frames = frames(scenes)
    judged = [s for s in filled if sem(s).get("relevanceScore") is not None]
    quality = [float(sem(s).get("qualityScore")) for s in filled if sem(s).get("qualityScore") is not None]
    return {
        "scenes": n,
        **({k: treatments.get(k) for k in ("text_treatments", "maps", "data_graphics", "callouts",
                                           "image_treatments", "transitions", "sfx", "music_cues",
                                           "total_treatments", "unique_templates")} if treatments else {}),
        "style_pack": meta.get("stylePack"),
        "fill_pct": round(100 * len(filled) / n, 1) if n else 0.0,
        "video_pct": round(100 * len(videos) / n, 1) if n else 0.0,
        # Clip share by screen time (a short clip line weighs less than a long picture line), the pictures,
        # the share of filled lines a vision verdict judged, and the judge's mean footage quality (0-1).
        "video_time_pct": round(100 * frames(videos) / total_frames, 1) if total_frames else 0.0,
        "image_pct": round(100 * len(images) / n, 1) if n else 0.0,
        "judged_pct": round(100 * len(judged) / len(filled), 1) if filled else None,
        "avg_quality": round(statistics.mean(quality), 3) if quality else None,
        "review_flags": sum(1 for s in scenes if s.get("reviewRequired")),
        "entity_acc": round(100 * len(ent_ok) / len(ent_scenes), 1) if ent_scenes else None,
        "location_acc": round(100 * len(loc_ok) / len(loc_scenes), 1) if loc_scenes else None,
        "case_entity_coverage": round(100 * len(case_ok) / len(filled), 1) if filled else 0.0,
        "visual_relevance": round(statistics.mean(rel), 3) if rel else None,
        "timestamp_relevance": round(statistics.mean(ts), 3) if ts else None,
        "duplicate_rate": round(100 * (1 - len(set(ids)) / len(ids)), 1) if ids else 0.0,
        "generic_rate": round(100 * len(generic) / len(event_scenes), 1) if event_scenes else None,
        "avg_candidates": round(statistics.mean(cands), 1) if cands else None,
        "avg_winning_score": round(statistics.mean(fin), 3) if fin else None,
        "vision_calls": usage.get("visionCalls"),
        "generation_s": round(elapsed, 1),
        "ai_usd": round(ai_usd, 4),
        "runpod_usd": round(runpod_usd, 4),
        "total_usd": round(ai_usd + runpod_usd, 4),
        "cost_source": "ledger" if _ai_usd(ledger) is not None else "estimate",
        "warnings": len(meta.get("warnings") or []),
    }


# ------------------------------------------------------------------ running
OUT_DIR = os.path.join(ROOT, "bench", "out")


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_")[:80] or "run"


def save_run(label: str, case_name: str, payload: dict) -> str:
    """The job's whole answer (timeline, ledger, events, vision stats) under bench/out/runs/<label>/<case>.json,
    so the chosen clips can be looked at later (scripts never print keys; the answer holds none)."""
    folder = os.path.join(OUT_DIR, "runs", _slug(label))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{case_name}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    return path


# What a job asks for: "youtube" - YouTube clips only (the benchmark's original setting: every line a footage
# line, one source, no clips-first ladder); "app" - what the app's video-v2 sends for a real build (YouTube
# allowed, pictures allowed, no stock), so the clips-first ladder and the pictures after it run as in production.
SOURCES = {
    "youtube": {"youtube_only": True, "allow_youtube": True},
    "app": {"youtube_only": False, "allow_youtube": True, "prefer": "youtube", "source_policy": "no_stock"},
}


def run_case(case: dict, key: str, config: Optional[dict], timeout: int = 3600,
             render: bool = False, width: int = 1280, height: int = 720, sources: str = "youtube",
             label: str = "") -> dict:
    import requests
    H = {"Authorization": f"Bearer {key}"}
    inp = {"action": "build" if render else "plan", "audio_url": f"bench://{case['name']}",
           "title": case["title"], **SOURCES[sources], "publish_media": False,
           "contract_version": 2, "bench": True}
    if render:
        # The finished video comes back inline (no project to upload to), so
        # the benchmark renders at 720p to stay under the result cap.
        inp.update({"return_video": True, "width": width, "height": height, "captions": True, "sfx": True})
    if config:
        inp["config"] = config
    r = requests.post(f"https://api.runpod.ai/v2/{ENDPOINT}/run", headers=H,
                      json={"input": inp}, timeout=30).json()
    jid = r["id"]
    print(f"[bench] {case['name']}: job {jid}", flush=True)
    t0 = time.time()
    last = ""
    while True:
        s = requests.get(f"https://api.runpod.ai/v2/{ENDPOINT}/status/{jid}", headers=H, timeout=30).json()
        st = s.get("status")
        out = s.get("output") or {}
        line = f"{st} {out.get('progress', '')}% {out.get('status', '')}"
        if line != last:
            # The case's name on every progress line: several cases run side by side (--parallel), and
            # "Sourced k/n" read with its time is each line's own finish in pass 1.
            print(f"[bench]   {case['name']} {int(time.time() - t0)}s {line}", flush=True)
            last = line
        if st in ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"):
            break
        if time.time() - t0 > timeout:
            requests.post(f"https://api.runpod.ai/v2/{ENDPOINT}/cancel/{jid}", headers=H, timeout=30)
            return {"ok": False, "error": "benchmark timeout", "elapsed": time.time() - t0}
        time.sleep(10)
    elapsed = time.time() - t0
    try:
        kept = {k: v for k, v in out.items() if k != "video_b64"} if isinstance(out, dict) else out
        saved = save_run(label or "run", case["name"], {"job": jid, "status": st, "input": inp, "output": kept,
                                                         "error": s.get("error")})
    except (OSError, TypeError, ValueError) as e:
        saved = ""
        print(f"[bench]   could not save the run: {type(e).__name__}", flush=True)
    if st != "COMPLETED" or not out.get("ok", True):
        # A failed job was paid for all the same: its ledger comes back when the handler got that far.
        return {"ok": False, "error": (s.get("error") or out.get("error") or st)[:300], "elapsed": elapsed,
                "job": jid, "costs": out.get("costs") if isinstance(out, dict) else None, "saved": saved}
    video_path = ""
    if out.get("video_b64"):
        import base64
        os.makedirs(OUT_DIR, exist_ok=True)
        video_path = os.path.join(OUT_DIR, f"{case['name']}.mp4")
        with open(video_path, "wb") as fh:
            fh.write(base64.b64decode(out["video_b64"]))
        print(f"[bench]   saved {video_path} ({os.path.getsize(video_path) / 1e6:.1f} MB)", flush=True)
    ev = out.get("events") or {}
    return {"ok": True, "timeline": out.get("timeline") or {}, "elapsed": float(out.get("elapsed") or elapsed),
            "job": jid, "video": video_path, "costs": out.get("costs"), "saved": saved,
            "events": {k: ev.get(k) for k in ("stage_seconds", "child_stage_seconds", "failures_by_class",
                                             "providers", "errors") if k in ev},
            "sourcing": ((out.get("timeline") or {}).get("meta") or {}).get("sourcing"),
            "proxies": [{k: p.get(k) for k in ("proxy_id", "state", "success_rate", "failures")}
                        for p in ((out.get("timeline") or {}).get("meta") or {}).get("proxies") or []]}


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                       text=True).strip()
    except Exception:  # noqa: BLE001
        return ""


def record(row: dict) -> None:
    with open(RESULTS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def report() -> None:
    if not os.path.isfile(RESULTS):
        print("no results yet")
        return
    rows = [json.loads(l) for l in open(RESULTS, encoding="utf-8") if l.strip()]
    cols = ["fill_pct", "video_pct", "video_time_pct", "entity_acc", "location_acc", "case_entity_coverage",
            "visual_relevance", "avg_quality", "timestamp_relevance", "duplicate_rate", "generic_rate",
            "avg_candidates", "avg_winning_score", "generation_s", "ai_usd", "runpod_usd", "total_usd"]
    print(f"{'label':<22} {'sha':<8} {'case':<24} " + " ".join(f"{c[:10]:>10}" for c in cols))
    for r in rows:
        m = r.get("metrics") or {}
        print(f"{r.get('label', '')[:22]:<22} {r.get('sha', '')[:8]:<8} {r.get('case', '')[:24]:<24} "
              + " ".join(f"{('' if m.get(c) is None else m.get(c)):>10}" for c in cols)
              + ("" if r.get("ok", True) else f"  FAILED: {r.get('error', '')[:60]}"))
    # Per-label means.
    by = {}
    for r in rows:
        if r.get("ok", True):
            by.setdefault(r.get("label", ""), []).append(r["metrics"])
    print("\nmeans by label")
    for label, ms in by.items():
        means = {c: round(statistics.mean([m[c] for m in ms if m.get(c) is not None]), 2)
                 for c in cols if any(m.get(c) is not None for m in ms)}
        print(f"  {label[:22]:<22} n={len(ms)} " + " ".join(f"{c[:10]}={means[c]}" for c in means))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="")
    ap.add_argument("--cases", default="all")
    ap.add_argument("--config", action="append", default=[], help="KEY=VALUE worker config override")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--parallel", type=int, default=1)
    ap.add_argument("--render", action="store_true", help="build (plan + render) and save the video to bench/out")
    ap.add_argument("--sources", choices=sorted(SOURCES), default="youtube",
                    help="youtube: clips only (the original benchmark); app: what a real build asks for")
    ap.add_argument("--sha", default="", help="the worker image's commit, when it is not this checkout's HEAD")
    ap.add_argument("--max-ai-usd", type=float, default=0.0,
                    help="no new case starts once the model calls of this run cost this much (0 = no cap)")
    args = ap.parse_args()
    if args.report:
        report()
        return 0
    env = _env()
    key = env.get("RUNPOD_API_KEY")
    if not key:
        print("RUNPOD_API_KEY missing", file=sys.stderr)
        return 2
    config = {}
    for kv in args.config:
        k, _, v = kv.partition("=")
        config[k.strip()] = v.strip()
    names = None if args.cases == "all" else [n.strip() for n in args.cases.split(",")]
    cases = load_cases(names)
    sha = args.sha or git_sha()
    label = args.label or f"run {time.strftime('%Y-%m-%d %H:%M')}"
    from concurrent.futures import ThreadPoolExecutor
    spent = {"ai": 0.0, "runpod": 0.0}
    spent_lock = threading.Lock()

    def one(case):
        with spent_lock:
            over = args.max_ai_usd > 0 and spent["ai"] >= args.max_ai_usd
        if over:
            print(f"[bench] {case['name']}: skipped - this run's model calls reached ${spent['ai']:.3f}", flush=True)
            return {"label": label, "case": case["name"], "ok": False, "skipped": True}
        res = run_case(case, key, config, render=args.render, sources=args.sources, label=label)
        row = {"label": label, "sha": sha, "case": case["name"], "at": int(time.time()),
               "config": config, "sources": args.sources, "ok": res["ok"], "render": args.render,
               "job": res.get("job"), "saved": res.get("saved", "")}
        if res["ok"]:
            row["metrics"] = score_timeline(res["timeline"], case, res["elapsed"], costs=res.get("costs"))
            if res.get("video"):
                row["video"] = res["video"]
            if res.get("costs"):
                row["metrics"]["measured_credits"] = res["costs"].get("credits_measured")
                row["metrics"]["worker_seconds"] = res["costs"].get("worker_seconds")
                row["metrics"]["ledger_usd"] = res["costs"].get("total")
            for k in ("events", "sourcing", "proxies"):
                if res.get(k):
                    row[k] = res[k]
        else:
            row["error"] = res.get("error", "")
            row["metrics"] = {"generation_s": round(res.get("elapsed", 0), 1)}
            ai = _ai_usd(res.get("costs") or {})
            if ai is not None:
                row["metrics"].update(ai_usd=round(ai, 4), runpod_usd=round(float(res["costs"].get("runpod") or 0), 4))
        with spent_lock:
            spent["ai"] += float(row["metrics"].get("ai_usd") or 0.0)
            spent["runpod"] += float(row["metrics"].get("runpod_usd") or 0.0)
        record(row)
        print(f"[bench] {case['name']}: {json.dumps(row.get('metrics'))}" + ("" if res["ok"] else f" FAILED {row['error']}"),
              flush=True)
        return row

    with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as ex:
        rows = list(ex.map(one, cases))
    ok = [r for r in rows if r["ok"]]
    print(f"[bench] {len(ok)}/{len(rows)} cases completed; model calls ${spent['ai']:.3f}, "
          f"RunPod ${spent['runpod']:.3f}; results in {RESULTS}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
