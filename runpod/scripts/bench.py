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


def score_timeline(doc: dict, case: dict, elapsed: float = 0.0) -> dict:
    """Metrics for one finished plan. Pure: unit-tested on synthetic timelines."""
    scenes = doc.get("scenes") or []
    meta = doc.get("meta") or {}
    n = len(scenes)
    filled = [s for s in scenes if (s.get("media") or {}).get("url")
              and (s.get("media") or {}).get("type") in ("video", "image")]
    videos = [s for s in filled if s["media"].get("type") == "video"]

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
    ai_usd = float(usage.get("estimatedCredits") or 0) * CREDIT_USD
    fanout = (meta.get("sourcing") or {}).get("fanout") or meta.get("fanout") or {}
    workers = 1 + int(fanout.get("parts") or 0)
    runpod_usd = elapsed * RUNPOD_USD_PER_WORKER_SECOND * max(1, min(workers, 10)) * 0.6
    return {
        "scenes": n,
        "fill_pct": round(100 * len(filled) / n, 1) if n else 0.0,
        "video_pct": round(100 * len(videos) / n, 1) if n else 0.0,
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
        "ai_usd": round(ai_usd, 3),
        "runpod_usd": round(runpod_usd, 3),
        "total_usd": round(ai_usd + runpod_usd, 3),
        "warnings": len(meta.get("warnings") or []),
    }


# ------------------------------------------------------------------ running
def run_case(case: dict, key: str, config: Optional[dict], timeout: int = 3600) -> dict:
    import requests
    H = {"Authorization": f"Bearer {key}"}
    inp = {"action": "plan", "audio_url": f"bench://{case['name']}", "title": case["title"],
           "youtube_only": True, "allow_youtube": True, "publish_media": False,
           "contract_version": 2, "bench": True}
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
            print(f"[bench]   {int(time.time() - t0)}s {line}", flush=True)
            last = line
        if st in ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"):
            break
        if time.time() - t0 > timeout:
            requests.post(f"https://api.runpod.ai/v2/{ENDPOINT}/cancel/{jid}", headers=H, timeout=30)
            return {"ok": False, "error": "benchmark timeout", "elapsed": time.time() - t0}
        time.sleep(10)
    elapsed = time.time() - t0
    if st != "COMPLETED" or not out.get("ok", True):
        return {"ok": False, "error": (s.get("error") or out.get("error") or st)[:300], "elapsed": elapsed}
    return {"ok": True, "timeline": out.get("timeline") or {}, "elapsed": float(out.get("elapsed") or elapsed),
            "job": jid}


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
    cols = ["fill_pct", "entity_acc", "location_acc", "case_entity_coverage", "visual_relevance",
            "timestamp_relevance", "duplicate_rate", "generic_rate", "avg_candidates",
            "avg_winning_score", "generation_s", "total_usd"]
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
    sha = git_sha()
    label = args.label or f"run {time.strftime('%Y-%m-%d %H:%M')}"
    from concurrent.futures import ThreadPoolExecutor

    def one(case):
        res = run_case(case, key, config)
        row = {"label": label, "sha": sha, "case": case["name"], "at": int(time.time()),
               "config": config, "ok": res["ok"]}
        if res["ok"]:
            row["metrics"] = score_timeline(res["timeline"], case, res["elapsed"])
            row["job"] = res.get("job")
        else:
            row["error"] = res.get("error", "")
            row["metrics"] = {"generation_s": round(res.get("elapsed", 0), 1)}
        record(row)
        print(f"[bench] {case['name']}: {json.dumps(row.get('metrics'))}" + ("" if res["ok"] else f" FAILED {row['error']}"),
              flush=True)
        return row

    with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as ex:
        rows = list(ex.map(one, cases))
    ok = [r for r in rows if r["ok"]]
    print(f"[bench] {len(ok)}/{len(rows)} cases completed; results in {RESULTS}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
