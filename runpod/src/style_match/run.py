"""
Style Match worker action (2026-10-14): {"action": "style_match", "url" | "video_url", ...} -> a Style Kit.

    input:  url (a YouTube link) or video_url (an uploaded file's signed URL), channel_id / project_id (only
            used in the storage key), detail_seconds (default 300: how much is measured element by element),
            max_seconds (default 600: how much of a YouTube video is fetched), vision (default true)
    output: {"ok", "kit", "card" (markdown), "stills": [{"element", "url"}], "kitUrl", "cardUrl", "usd"}

Cost: the download, ~1-3 CPU minutes and 2-3 vision calls (~$0.003). Nothing is charged to the user here; the
app decides (a style match is free to try).
"""
import json
import os
import re
import shutil
import time
import uuid
from typing import Optional

from . import compare, kit as kitmod, measure, vision


def analyse_file(path: str, workdir: str, source: Optional[dict] = None, *, detail_seconds: float = 300.0,
                 max_seconds: float = 1800.0, use_vision: bool = True, log=print) -> dict:
    """Measure a local video and build its kit. Returns {"kit", "card", "meas", "spend"}."""
    meas = measure.analyse(path, workdir, detail_seconds=detail_seconds, max_seconds=max_seconds, log=log)
    spend = vision.Spend()
    if use_vision:
        try:
            vision.label_elements(meas, spend)
            meas["structure"] = vision.structure(meas, path, spend) or {}
        except Exception as e:  # noqa: BLE001 - the kit is still built from pixels
            log(f"[style-match] vision skipped: {type(e).__name__}: {str(e)[:160]}")
    log(f"[style-match] vision: {spend.calls} call(s), ${spend.usd:.4f}")
    kit = kitmod.build(meas, source)
    kit["source"]["visionUsd"] = round(spend.usd, 4)
    return {"kit": kit, "card": kitmod.card(kit), "meas": meas, "spend": spend}


def _fetch(inp: dict, work: str, max_seconds: float, log) -> tuple:
    url = str(inp.get("url") or "").strip()
    if inp.get("video_url"):
        from .. import storage
        dest = os.path.join(work, "ref.mp4")
        storage.download(str(inp["video_url"]), dest, timeout=900)
        return dest, {"upload": True}
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})", url) or re.fullmatch(r"([A-Za-z0-9_-]{11})", url)
    if not m:
        raise ValueError("a YouTube link or an uploaded video is needed")
    vid = m.group(1)
    from .. import media
    path = media._yt_fetch_retry(vid, work, 0.0, max_seconds, "")
    if not path:
        raise RuntimeError("the video could not be downloaded")
    return path, {"url": f"https://www.youtube.com/watch?v={vid}", "id": vid}


def run(inp: dict, log=print) -> dict:
    started = time.time()
    work = os.path.join(os.getenv("WORK_DIR", "/tmp"), f"style_{uuid.uuid4().hex[:10]}")
    os.makedirs(work, exist_ok=True)
    try:
        max_s = float(inp.get("max_seconds") or 600)
        path, source = _fetch(inp, work, max_s, log)
        if inp.get("title"):
            source["title"] = str(inp["title"])[:160]
        out = analyse_file(path, work, source, detail_seconds=float(inp.get("detail_seconds") or 300),
                           max_seconds=max_s, use_vision=inp.get("vision", True) is not False, log=log)
        kit = out["kit"]
        sid = re.sub(r"[^A-Za-z0-9_-]", "", str(inp.get("style_id") or uuid.uuid4().hex[:12]))[:40]
        owner = re.sub(r"[^A-Za-z0-9_-]", "", str(inp.get("channel_id") or inp.get("project_id") or "anon"))[:60]
        prefix = f"style-kits/{owner}/{sid}"
        stills = compare.stills(path, out["meas"], kit, os.path.join(work, "stills"))
        from .. import r2
        urls = []
        for s in stills:
            urls.append({"element": s["element"], "url": r2.upload(s["path"], f"{prefix}/{os.path.basename(s['path'])}",
                                                                    "image/jpeg"), "confidence": s.get("confidence")})
        kit["stills"] = urls
        kit["id"] = sid
        kit_url = r2.upload_bytes(json.dumps(kit).encode(), f"{prefix}/kit.json")
        card_url = r2.upload_bytes(out["card"].encode(), f"{prefix}/card.md", "text/markdown")
        return {"ok": True, "action": "style_match", "kit": kit, "card": out["card"], "kitUrl": kit_url,
                "cardUrl": card_url, "stills": urls, "usd": round(out["spend"].usd, 4),
                "seconds": round(time.time() - started, 1)}
    finally:
        shutil.rmtree(work, ignore_errors=True)
