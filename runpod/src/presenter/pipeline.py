"""
The AI presenter style end to end, for a plan or build job whose video_style
is "ai_presenter" (handler.do_plan hands the whole plan to plan() here):

  1. the narration: the job's voice (an upload, or our TTS made from the
     script by the handler's narrate step) and its word timings (the job's
     own "words", else whisper as every style);
  2. the beats (the editor's cuts, transcribe.segment_words) and the
     planner's notes on them (director.annotate: roles, prompts, style bible);
  3. the shot plan to the tier's shares (shotplan);
  4. the shots made: presenter, AI clips, stills - checked, retried,
     fallen back, all under the job's budget (generate);
  5. the timeline document (assemble), with meta.presenter: what was
     planned and made, what fell back and why, what every part cost.

Nothing here touches the footage search, the vision judge or Kie.
"""
from __future__ import annotations

import os
import shutil
import time
from typing import Any, Callable, Dict, List, Optional

from .. import config, storage, timeline, transcribe
from .. import render as renderer
from . import assemble, director, estimate, kits, media_io, providers, shotplan, tiers
from .budget import Budget
from .checks import Checker
from .generate import Generator
from .store import Cache, Store

STYLE = "ai_presenter"
DISCLOSURE = ("This video shows a realistic AI-generated person and AI-generated scenes: tick \"Altered or synthetic "
              "content\" in YouTube Studio when uploading. Keep the presenter off medical, financial and legal advice.")


def words_from(raw: Any) -> List[transcribe.Word]:
    """A job's own word timings ([{text|w, start|s, end|e}]) as Words; zero-length words dropped."""
    out: List[transcribe.Word] = []
    for w in raw or []:
        if not isinstance(w, dict):
            continue
        text = str(w.get("text") or w.get("w") or w.get("word") or "").strip()
        try:
            a = float(w.get("start", w.get("s")))
            b = float(w.get("end", w.get("e")))
        except (TypeError, ValueError):
            continue
        if text and b - a > 0.01:
            out.append(transcribe.Word(text=text, start=a, end=b))
    out.sort(key=lambda x: x.start)
    return out


def script_words(spoken: List[transcribe.Word], script: str) -> List[transcribe.Word]:
    """
    The script's own words with the voice's times (the way transcribe.align_to_script lines them up: matching
    words take the recognised word's time, a reworded run shares its span, a missing word sits between its
    neighbours), so the shots, prompts and any captions read as written ("rows", not whisper's "rose") and the
    beats cut on the script's own punctuation. Whisper's words when the two hardly match.
    """
    import re
    from difflib import SequenceMatcher
    authored = (script or "").split()
    if not authored or not spoken:
        return spoken

    def norm(tok: str) -> str:
        return re.sub(r"[^\w']", "", tok, flags=re.UNICODE).casefold()

    a, b = [norm(w) for w in authored], [norm(w.text) for w in spoken]
    times: List[Optional[tuple]] = [None] * len(authored)
    same = 0
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            same += i2 - i1
            for ai, bi in zip(range(i1, i2), range(j1, j2)):
                times[ai] = (spoken[bi].start, spoken[bi].end)
        elif tag == "replace" and j2 > j1:
            lo, hi, n = spoken[j1].start, spoken[j2 - 1].end, max(1, i2 - i1)
            for k, ai in enumerate(range(i1, i2)):
                times[ai] = (lo + (hi - lo) * k / n, lo + (hi - lo) * (k + 1) / n)
    if same < max(1, 0.5 * min(len(authored), len(spoken))):
        return spoken
    known = [i for i, t in enumerate(times) if t is not None]
    for i, t in enumerate(times):
        if t is not None:
            continue
        left = max((k for k in known if k < i), default=None)
        right = min((k for k in known if k > i), default=None)
        lo = times[left][1] if left is not None else (times[right][0] if right is not None else 0.0)
        hi = times[right][0] if right is not None else lo
        times[i] = (lo, max(lo, hi))
    out = [transcribe.Word(text=tok, start=float(t[0]), end=float(t[1])) for tok, t in zip(authored, times)]
    # Times never run backwards (a reworded span can overlap its neighbour by a hair).
    for k in range(1, len(out)):
        if out[k].start < out[k - 1].start:
            out[k].start = out[k - 1].start
        if out[k].end < out[k].start:
            out[k].end = out[k].start
    return out


def budget_cap(inp: Dict[str, Any], est: Dict[str, Any]) -> float:
    """The job's spending cap: its own presenter_budget_usd, else PRESENTER_BUDGET_USD, else 1.5x the estimate."""
    for v in (inp.get("presenter_budget_usd"), os.getenv("PRESENTER_BUDGET_USD", "")):
        try:
            if v not in (None, "") and float(v) > 0:
                return float(v)
        except (TypeError, ValueError):
            continue
    return max(1.0, round(float(est.get("usd") or 0.0) * 1.5, 2))


def _narration(inp: Dict[str, Any], work: str, report, narrate: Optional[Callable]) -> Dict[str, Any]:
    """{"src": the link the timeline keeps, "path": the file here, "made": the TTS report or None, "raw": as sent}."""
    raw = inp.get("audio_url") or inp.get("audio_path")
    made = None
    if not raw and narrate is not None:
        from .. import tts
        if tts.configured() and tts.wanted(inp):
            made = narrate(inp, work, report)
            raw = made["url"]
    if not raw:
        raise ValueError("audio_url is required (upload a voiceover or generate TTS first)")
    if made:
        return {"src": made["url"], "path": made["path"], "made": made, "raw": raw}
    report("Downloading narration", 4)
    local = os.path.join(work, "narration" + (os.path.splitext(str(raw).split("?")[0])[1] or ".mp3"))
    if os.path.isfile(str(raw)):
        shutil.copyfile(str(raw), local)
        return {"src": str(inp.get("audio_url") or raw), "path": local, "made": None, "raw": raw}
    src = storage.resolve_audio(raw, bucket=inp.get("audio_bucket", "video-audio"))
    return {"src": src, "path": storage.download(src, local), "made": None, "raw": raw}


def _costs(budget: Budget) -> Dict[str, Any]:
    by: Dict[str, float] = {}
    n: Dict[str, int] = {}
    for row in budget.rows:
        kind = str(row.get("kind") or "other")
        by[kind] = by.get(kind, 0.0) + float(row.get("usd") or 0.0)
        n[kind] = n.get(kind, 0) + (0 if row.get("released") else 1)
    return {"presenterUsd": round(by.get("presenter", 0.0), 4), "aiVideoUsd": round(by.get("aivideo", 0.0), 4),
            "imagesUsd": round(by.get("image", 0.0), 4), "checksUsd": round(by.get("check", 0.0), 4),
            "plannerUsd": round(by.get("plan", 0.0), 4), "totalUsd": round(sum(by.values()), 4),
            "calls": n}


def plan(inp: Dict[str, Any], work: str, report, narrate: Optional[Callable] = None) -> Dict[str, Any]:
    started = time.time()
    tier = tiers.resolve(inp.get("tier") or inp.get("presenter_tier"), inp.get("presenter_config"))
    kit = kits.for_job(inp)
    provider = providers.get()
    if not provider.available():
        raise RuntimeError("The AI presenter style needs the OpenRouter key on this worker (none is configured).")
    print(f"[presenter] tier {tier['id']} ({tier['presenter_share']:.0%} presenter, {tier['ai_video_share']:.0%} AI "
          f"video), presenter {kit['id']}", flush=True)

    nar = _narration(inp, work, report, narrate)
    duration = float(renderer.probe_duration(nar["path"]) or 0.0)
    if duration <= 1.0:
        raise ValueError("the narration is empty or unreadable")
    report.estimate(duration)
    wav = media_io.to_wav(nar["path"], os.path.join(work, "narration_24k.wav"))

    report("Aligning narration", 8)
    words = words_from(inp.get("words"))
    if not words:
        words = transcribe.transcribe_words(nar["path"], language=inp.get("language"),
                                            on_progress=lambda f: report("Aligning narration", 8 + int(5 * f)))
        words = [w for w in words if w.end - w.start > 0.01]
    if not words:
        raise ValueError("no speech detected in the narration audio")
    if inp.get("script"):
        words = script_words(words, inp["script"])
    segments = transcribe.segment_words(words, origin=0.0, until=duration)

    est = estimate.estimate(duration / 60.0, tier, own_voice=not nar["made"])
    budget = Budget(budget_cap(inp, est))
    title = str(inp.get("title") or inp.get("title_overlay") or "").strip()

    report("Planning the presenter video", 14)
    beats = shotplan.beats_from(segments, duration)
    cache_dir = os.getenv("PRESENTER_CACHE_DIR", "").strip() or os.path.join(work, "presenter_cache")
    notes = director.annotate(beats, title=title, kit=kit, provider=provider, budget=budget, cache=cache_dir)
    limits = {k: float(inp[f"presenter_{k}"]) for k in ("min", "max") if inp.get(f"presenter_{k}")}
    shots = shotplan.Planner(
        beats, notes["notes"], duration, presenter_share=tier["presenter_share"],
        ai_video_share=tier["ai_video_share"], presenter_broll=tier["presenter_broll"],
        # Two cameras at most, like the references (one set, one or two angles): the master and the second.
        framings=[f["id"] for f in kit["framings"]][:2], split_share=tier["split_share"],
        **({"presenter_min": limits["min"]} if "min" in limits else {}),
        **({"presenter_max": limits["max"]} if "max" in limits else {})).plan()
    planned = shotplan.stats(shots, duration)
    print(f"[presenter] plan: {planned}", flush=True)

    project_id = str(inp.get("project_id") or "")
    store = Store(project_id, str(inp.get("_job_id") or ""))
    cache = Cache(cache_dir, store if project_id else None)
    checker = Checker(provider, budget, work)

    def progress(done: int, total: int) -> None:
        report(f"Sourcing the presenter, clips and pictures {done}/{total}", 22 + int(40 * done / max(total, 1)),
               done=done, total=total)

    gen = Generator(provider=provider, budget=budget, tier=tier, kit=kit, work=work, store=store, cache=cache,
                    checker=checker, narration_wav=wav, total=duration, bible=notes["bible"], on_progress=progress)
    progress(0, len(shots))
    try:
        assets = gen.run(shots)
    finally:
        removed = store.cleanup()
    report("Designing the edit", 64)
    warnings: List[str] = []
    if gen.no_https_audio:
        warnings.append("Presenter shots need R2 (the voice goes to the avatar model by an https link): "
                        "they were drawn as pictures instead.")
    if notes["errors"]:
        warnings.append(f"The planner model failed on part of the script: {notes['errors'][0][:160]}")
    doc, items = assemble.build(shots=shots, assets=assets, audio_url=nar["src"], narration_path=nar["path"],
                                duration=duration, inp=dict(inp, title=title), kit=kit,
                                planner=f"presenter:{notes['planner']}", warnings=warnings)

    final = [s for s, _a in items]
    by_source: Dict[str, int] = {}
    for _s, a in items:
        key = a.source if a is not None else "none"
        by_source[key] = by_source.get(key, 0) + 1
    meta = doc.setdefault("meta", {})
    meta["videoStyle"] = STYLE
    meta["audioSource"] = nar["raw"]
    meta["audioBucket"] = inp.get("audio_bucket", "video-audio")
    if nar["made"]:
        meta["narration"] = nar["made"]["report"]
    meta["story"] = {"kind": "other", "summary": title, "title": title, "bible": notes["bible"]}
    meta["presenter"] = {
        "tier": tiers.summary(tier), "kit": kits.public_summary(kit),
        "planner": notes["planner"], "plannerErrors": notes["errors"][:3], "bible": notes["bible"],
        "planned": planned, "final": dict(shotplan.stats(final, duration), bySource=by_source),
        "fallbacks": sum(1 for _s, a in items if a is not None and a.fallback),
        "empty": sum(1 for _s, a in items if a is None),
        "shots": [dict(s.as_dict(), asset=a.report() if a is not None else None) for s, a in items],
        "costs": _costs(budget), "budget": budget.report(), "estimate": est,
        "cache": {"hits": cache.hits, "folder": "PRESENTER_CACHE_DIR" if os.getenv("PRESENTER_CACHE_DIR") else "job"},
        "checks": {"calls": checker.calls, "unchecked": checker.unchecked},
        "storage": {"prefix": store.prefix, "kept": store.kept, "inputsRemoved": removed},
        "disclosure": DISCLOSURE, "seconds": round(time.time() - started, 1), "log": gen.log[-60:],
    }
    meta.setdefault("warnings", []).insert(0, DISCLOSURE)
    timeline.drop_invalid_overlays(doc)
    timeline.validate(doc, require_media=False, allow_stock=inp.get("allow_stock"))
    c = meta["presenter"]["costs"]
    print(f"[presenter] made in {meta['presenter']['seconds']:.0f} s: ${c['totalUsd']:.3f} "
          f"(presenter ${c['presenterUsd']:.3f}, clips ${c['aiVideoUsd']:.3f}, pictures ${c['imagesUsd']:.3f}, "
          f"checks ${c['checksUsd']:.3f}, plan ${c['plannerUsd']:.3f}); {meta['presenter']['fallbacks']} fallback(s)",
          flush=True)
    return doc


def info() -> Dict[str, Any]:
    """What the app shows for the style: tiers, the estimate table, the kits, the script preset."""
    from . import script_preset
    known = []
    for k in kits.catalogue().values():
        try:
            known.append(kits.public_summary(kits.normalize(k)))
        except kits.KitError:
            continue
    return {"style": STYLE, "defaultTier": tiers.DEFAULT_TIER,
            "tiers": {k: tiers.summary(tiers.resolve(k)) for k in tiers.all_tiers()},
            "estimate": estimate.table(), "kits": known, "script": script_preset.PRESET, "disclosure": DISCLOSURE}
