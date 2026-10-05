"""
The "relook" action: new graphics on a timeline that is already made, without
re-building it (the owner, 2026-10-05, on his Las Vegas video: the 27 % with
no ring, dates and numbers said but not shown, looks that end before their
animation, a map path drawn from Australia, overlay pictures that do not load).

Only the graphics change. Every shot, the music, the voice, the captions, the
sounds stay exactly as they are; nothing is sourced, no paid call is made.

  1. maps: every map look's places are resolved again, biased to the story's
     region, with the sanity checks (geocode.resolve_all); a look whose places
     cannot be trusted is left out rather than drawn wrong;
  2. pictures: every picture a look shows is fetched and checked, re-hosted on
     R2 (on an apply), replaced by the next candidate or turned into its
     text-only look (overlayimages.fix);
  3. data looks: the narration's dates, times, years, percentages, multipliers
     and numbers get their KT looks on their words, the retired looks are
     rewritten as their clean equivalents, and every look gets its full
     animation in one lane (datalooks.finish).

A dry run (the default) returns the new timeline and the diff and writes
nothing. An apply (apply: true) needs expect_fingerprint - the fingerprint of
the timeline the caller checked against the database (recut.fingerprint, the
same read-only query scratchpad/recut_project.py prints) - keeps the timeline
as it was on R2 first, then writes the project once (recut.write_project).
"""
from __future__ import annotations

import copy
import datetime
import json
import re
import time
from typing import Any, Callable, Dict, List, Optional

from . import config, datalooks, geocode, lookplace, overlayimages, r2, recut


class RelookError(RuntimeError):
    pass


NEAR_WORDS = 8.0            # the narration this many seconds around a map look is its line
MOVED_KM = 50.0             # a place that moved this far was wrong before


def _is_map(ov: dict) -> bool:
    return isinstance(ov.get("locations"), list) and bool(ov.get("locations")) and (
        ov.get("type") == "map" or str(ov.get("template") or "").startswith("MAP_")
        or str(ov.get("template") or "") == "LIB_PR_MAP_PATH")


def _line_at(words: List[dict], t0: float, t1: float) -> str:
    return " ".join(str(w.get("text") or "") for w in words
                    if t0 - NEAR_WORDS <= float(w.get("start") or 0) <= t1 + NEAR_WORDS)


def fix_maps(doc: dict, *, brief: Optional[dict] = None, resolve: Optional[Callable] = None) -> Dict[str, Any]:
    """Resolve every map look's places again (in place). Returns the rows: kept, fixed, dropped."""
    resolve = resolve or geocode.resolve_all
    fps = int(doc.get("fps") or 30)
    words = datalooks.words_of(doc)
    region = geocode.story_region(" ".join(str(w.get("text") or "") for w in words), brief)
    rows: List[dict] = []
    keep: List[dict] = []
    for ov in doc.get("overlays") or []:
        if not isinstance(ov, dict) or not _is_map(ov):
            keep.append(ov)
            continue
        t0 = int(ov.get("startFrame") or 0) / fps
        t1 = t0 + int(ov.get("durationInFrames") or 0) / fps
        names = [str(l.get("label") or "") for l in ov["locations"] if isinstance(l, dict) and l.get("label")]
        why: List[str] = []
        got = resolve(names, text=_line_at(words, t0, t1), brief=brief, region=region, why=why)
        row = {"template": ov.get("template"), "at": round(t0, 2), "places": names,
               "before": [[l.get("lat"), l.get("lon")] for l in ov["locations"] if isinstance(l, dict)]}
        if not got:
            rows.append({**row, "action": "dropped", "why": (why[0] if why else "a place could not be found")})
            continue
        moved = []
        old = {str(l.get("label") or ""): l for l in ov["locations"] if isinstance(l, dict)}
        for g in got:
            o = old.get(g["label"])
            if o is None or o.get("lat") is None:
                moved.append(g["label"])
                continue
            a = geocode.Place(g["label"], float(o["lat"]), float(o["lon"]))
            b = geocode.Place(g["label"], float(g["lat"]), float(g["lon"]))
            if geocode.hav_km(a, b) > MOVED_KM:
                moved.append(g["label"])
        ov["locations"] = got
        rows.append({**row, "after": [[g["lat"], g["lon"]] for g in got],
                     "action": "fixed" if moved else "kept", **({"moved": moved} if moved else {})})
        keep.append(ov)
    doc["overlays"] = keep
    return {"region": region, "rows": rows, "fixed": sum(1 for r in rows if r["action"] == "fixed"),
            "dropped": sum(1 for r in rows if r["action"] == "dropped"),
            "kept": sum(1 for r in rows if r["action"] == "kept")}


def overlays_fingerprint(doc: dict) -> str:
    """sha256 of the overlays as saved: an editor change to the graphics since the read changes it."""
    import hashlib
    return hashlib.sha256(json.dumps(doc.get("overlays") or [], sort_keys=True, ensure_ascii=False,
                                     default=str).encode("utf-8")).hexdigest()


def replan(doc: dict, *, project_id: str = "", brief: Optional[dict] = None, fetch=None, put=None,
           resolve=None, check_images: bool = True, public_base: str = "") -> Dict[str, Any]:
    """Steps 1-3 on `doc` in place. Returns the diff."""
    fps = int(doc.get("fps") or 30)
    maps = fix_maps(doc, brief=brief, resolve=resolve)
    images = (overlayimages.fix(doc["overlays"], project_id=project_id, scenes=doc.get("scenes") or [], fps=fps,
                                fetch=fetch, put=put, public_base=public_base)
              if check_images else {"skipped": True})
    looks = datalooks.finish(doc)

    def picture(url: str):
        try:
            return (fetch or overlayimages.default_fetch)(url)[0]
        except Exception:  # noqa: BLE001 - an unread picture keeps the look's home place
            return None
    # 4. each KT look on the calm side of its picture, on a soft panel over a busy one (src/lookplace.py)
    places = lookplace.place(doc["overlays"], doc.get("scenes") or [], fetch=picture, measure=check_images)
    return {"maps": maps, "images": images, "looks": looks, "places": places}


def _summary(diff: Dict[str, Any]) -> Dict[str, Any]:
    looks = diff["looks"]
    return {
        "overlaysBefore": looks["overlaysBefore"], "overlaysAfter": looks["overlaysAfter"],
        "byFamilyBefore": looks["byFamilyBefore"], "byFamilyAfter": looks["byFamilyAfter"],
        "addedDataLooks": looks["addedByLook"],
        "addedDates": sum(v for k, v in looks["addedByLook"].items() if k in (datalooks.KT_DATE, datalooks.KT_YEAR,
                                                                              datalooks.KT_TIME)),
        "addedPercents": sum(v for k, v in looks["addedByLook"].items() if k in (datalooks.KT_PERCENT,
                                                                                 datalooks.KT_PROGRESS)),
        "addedNumbers": sum(v for k, v in looks["addedByLook"].items() if k in (datalooks.KT_NUMBER, datalooks.KT_CHIP,
                                                                                datalooks.KT_COMPARE,
                                                                                datalooks.KT_MULTIPLIER)),
        "retiredRemoved": sum(1 for r in looks["removed"] if r["template"] in datalooks.RETIRED_IDS),
        "retiredRewritten": len(looks["remapped"]),
        "replacedFigureLooks": sum(1 for r in looks["removed"] if r["template"] not in datalooks.RETIRED_IDS),
        "droppedNoRoom": len(looks["dropped"]),
        "shortBefore": looks["shortBefore"], "shortAfter": looks["shortAfter"], "overlapAfter": looks["overlapAfter"],
        "mapsFixed": diff["maps"]["fixed"], "mapsDropped": diff["maps"]["dropped"],
        "imagesChecked": diff["images"].get("checked", 0), "imagesRehosted": diff["images"].get("rehosted", 0),
        "imagesWouldRehost": diff["images"].get("wouldRehost", 0), "imagesReplaced": diff["images"].get("replaced", 0),
        "imagesTextOnly": diff["images"].get("textOnly", 0), "imagesDropped": diff["images"].get("dropped", 0),
        "imagesUnchecked": diff["images"].get("unchecked", 0),
        "lookPanels": (diff.get("places") or {}).get("panel", 0),
        "lookFlipped": (diff.get("places") or {}).get("flipped", 0),
        "lookUnmeasured": (diff.get("places") or {}).get("unmeasured", 0),
    }


def read_project(project_id: str) -> dict:
    """The project's saved timeline straight from the database (service key only; read-only)."""
    import requests
    if not (config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY):
        raise RelookError("relook needs the timeline (timeline, timeline_url or timeline_key): this worker "
                          "cannot read the project itself")
    key = config.SUPABASE_SERVICE_KEY
    r = requests.get(f"{config.SUPABASE_URL.rstrip('/')}/rest/v1/video_projects",
                     params={"id": f"eq.{project_id}", "select": "scene_data"},
                     headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=(20, 300))
    r.raise_for_status()
    rows = r.json()
    if not rows or not isinstance(rows[0].get("scene_data"), dict):
        raise RelookError(f"project {project_id} has no timeline")
    return rows[0]["scene_data"]


def run(inp: dict, doc: dict, work: str = "", report: Optional[Callable] = None, *, fetch=None,
        put: Optional[Callable] = None, resolve=None) -> Dict[str, Any]:
    """
    Re-plan the graphics of `doc`. inp: project_id; apply (False = a dry run, the default; `dry_run: false` is
    the same as apply: true); expect_fingerprint (needed for an apply); write_wait; check_images (True).
    Returns {ok, dry_run, fingerprint, summary, diff, timeline, ...}.
    """
    started = time.time()
    say = report or (lambda *a, **k: None)
    apply = bool(inp.get("apply")) or (inp.get("dry_run") is False)
    project_id = str(inp.get("project_id") or "").strip()
    job_id = str(inp.get("_job_id") or "")
    if not isinstance(doc, dict) or not isinstance(doc.get("scenes"), list):
        raise RelookError("relook needs a timeline with scenes")
    fp = recut.fingerprint(doc)
    ofp = overlays_fingerprint(doc)
    expect = str(inp.get("expect_fingerprint") or "").strip().lower()
    if expect and expect != fp:
        raise RelookError(f"the timeline read (fingerprint {fp[:12]}...) is not the one expected ({expect[:12]}...): "
                          "it changed since it was checked against the database - nothing was done")
    expect_ov = str(inp.get("expect_overlays") or "").strip().lower()
    if expect_ov and expect_ov != ofp:
        raise RelookError("the timeline's graphics changed since they were checked - nothing was done")
    if apply:
        if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", project_id):
            raise RelookError("an apply needs the project_id")
        if not expect:
            raise RelookError("an apply needs expect_fingerprint (the read-only query's fingerprint), so a timeline "
                              "edited since it was read is never written over")
        if not r2.enabled():
            raise RelookError("Cloudflare R2 is not configured on this worker: there is nowhere to keep the backup")
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    brief = meta.get("story") if isinstance(meta.get("story"), dict) else None
    say("New graphics: re-planning the looks", 5)
    new_doc = copy.deepcopy(doc)
    if put is None and apply:
        def put(data: bytes, key: str, ctype: str) -> str:
            return r2.upload_bytes(data, r2.tokened(key), content_type=ctype, deadline=time.time() + 120,
                                   cache_control=getattr(r2, "IMMUTABLE", ""))
    diff = replan(new_doc, project_id=project_id, brief=brief, fetch=fetch, put=put if apply else None,
                  resolve=resolve, check_images=inp.get("check_images", True) is not False,
                  public_base=str(getattr(config, "R2_PUBLIC_BASE", "") or ""))
    # only the graphics changed
    for k in doc:
        if k in ("overlays", "meta"):
            continue
        if json.dumps(doc[k], sort_keys=True, default=str) != json.dumps(new_doc.get(k), sort_keys=True, default=str):
            raise RelookError(f"the timeline's {k} changed: nothing was written")
    summary = _summary(diff)
    new_doc.setdefault("meta", {})
    if isinstance(new_doc["meta"], dict):
        new_doc["meta"]["relook"] = {"summary": summary, "job": job_id, "fingerprintBefore": fp,
                                     "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        new_doc["meta"]["overlayCount"] = len(new_doc.get("overlays") or [])
    out: Dict[str, Any] = {"ok": True, "project_id": project_id, "dry_run": not apply, "fingerprint": fp,
                           "overlaysFingerprint": ofp, "summary": summary, "diff": diff, "timeline": new_doc}
    print(f"[relook] {summary['overlaysBefore']} -> {summary['overlaysAfter']} looks; data looks added "
          f"{summary['addedDataLooks']}; retired rewritten {summary['retiredRewritten']}, removed "
          f"{summary['retiredRemoved']}; maps fixed {summary['mapsFixed']}, dropped {summary['mapsDropped']}; "
          f"pictures replaced {summary['imagesReplaced']}, text-only {summary['imagesTextOnly']}; short looks "
          f"{summary['shortBefore']} -> {summary['shortAfter']}", flush=True)
    if not apply:
        out["seconds"] = round(time.time() - started, 1)
        return out
    say("New graphics: keeping the timeline as it was", 80)
    out["backup"] = recut.save_json(project_id, recut.backup_key(project_id, job_id), doc)
    out["relookKey"] = recut.save_json(project_id, recut.backup_key(project_id, job_id, "-relook"), new_doc)
    say("Saving the new graphics", 95)
    wait = inp.get("write_wait")
    written, why = recut.write_project(project_id, new_doc, say,
                                       recut.WRITE_WAIT if wait is None else max(0.0, float(wait)),
                                       step="Graphics re-planned")
    out["written"], out["writeError"] = written, why
    out["seconds"] = round(time.time() - started, 1)
    return out
