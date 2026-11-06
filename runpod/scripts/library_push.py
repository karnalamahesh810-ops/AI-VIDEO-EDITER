"""
The laptop's footage library -> the private bucket pods search (src/stormlib.py). Run from the laptop:

    python scripts/library_push.py --kit C:/ThumGenius/tools/storm-desk-kit                     # dry run: what would go, nothing sent
    python scripts/library_push.py --kit ... --bucket <private bucket> --upload                 # sends it
    python scripts/library_push.py --kit ... --bucket <private bucket> --upload --text-model    # and the CLIP text model (needs torch)

Dry run by default. Low priority, one source at a time (--workers for more), so the laptop stays usable. Resumable: a source whose
object already has its size is not sent again. Banned sources, personality channels and re-upload channels are skipped. The index and
the catalog go last and name only sources whose file is on the bucket, so a stopped run still leaves a library pods can use.

The bucket must have no public domain: --bucket is refused when it is R2_BUCKET or R2_LIBRARY_BUCKET, and Cloudflare's "Public access"
must stay off for it (the S3 keys this script holds cannot see that setting: check it in the dashboard). Keys come from the environment
(R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY). Nothing here prints a key or a link.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
os.environ.setdefault("SKIP_DOTENV", "1")       # keys from this shell only

from src import stormdesk, stormledger, stormlib  # noqa: E402

BELOW_NORMAL = 0x00004000


def low_priority() -> None:
    try:
        if os.name == "nt":
            import ctypes
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), BELOW_NORMAL)
        else:
            os.nice(10)
    except Exception:  # noqa: BLE001 - only politeness
        pass


def meta_rows(kit: str) -> Dict[str, List[str]]:
    """{id: [id, channel, upload date, WxH, title, seconds]} from the kit's credits/meta*.tsv (tools/common.py)."""
    out: Dict[str, List[str]] = {}
    folder = os.path.join(kit, "credits")
    for f in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if f.startswith("meta") and f.endswith(".tsv"):
            with open(os.path.join(folder, f), encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    q = line.rstrip("\n").split("\t")
                    if len(q) > 4 and q[2][:2] in ("19", "20"):
                        out.setdefault(q[0], q)
    return out


def extra_personality(kit: str) -> set:
    try:
        with open(os.path.join(kit, "credits", "channels.json"), encoding="utf-8") as f:
            return {str(x).lower() for x in json.load(f).get("personality", [])}
    except (OSError, ValueError):
        return set()


def skip_reason(vid: str, row: Optional[List[str]], banned: set, personality: set) -> str:
    """Why a source stays on the laptop ("" = it goes)."""
    if vid in banned:
        return "banned"
    if not row:
        return "no credit row"
    ch = row[1].strip()
    if stormledger.is_personality(ch) or ch.lower() in personality:
        return "personality"
    kind = stormdesk.source_kind(ch, row[4])
    if kind == "reupload":
        return "re-upload"
    if kind == "unknown":
        return "unknown channel"
    return ""


def plan(kit: str) -> Tuple[List[dict], Dict[str, int]]:
    """Every source that may go, with its files, and how many stayed behind by reason."""
    index, src = os.path.join(kit, "engine", "index"), os.path.join(kit, "engine", "src")
    meta = meta_rows(kit)
    banned, personality = stormlib.bad_sources(), extra_personality(kit)
    # (The kit's own list, in case it moved on since the seed was copied.)
    try:
        with open(os.path.join(kit, "credits", "bad_sources.json"), encoding="utf-8") as f:
            banned |= set(json.load(f))
    except (OSError, ValueError):
        pass
    rows: List[dict] = []
    left: Dict[str, int] = {}
    for f in sorted(os.listdir(index)) if os.path.isdir(index) else []:
        if not f.endswith(".npz"):
            continue
        vid = f[:-4]
        path = os.path.join(src, vid + ".mp4")
        if not os.path.isfile(path):
            left["no file"] = left.get("no file", 0) + 1
            continue
        why = skip_reason(vid, meta.get(vid), banned, personality)
        if why:
            left[why] = left.get(why, 0) + 1
            continue
        rows.append({"id": vid, "index": os.path.join(index, f), "faces": os.path.join(index, vid + ".faces.npy"), "path": path,
                     "size": os.path.getsize(path), "meta": meta[vid]})
    return rows, left


def catalog_row(s: dict, dur: float) -> dict:
    row = s["meta"]
    w, _x, h = str(row[3]).partition("x")
    try:
        w_, h_ = int(w), int(h)
    except ValueError:
        w_, h_ = 0, 0
    return {"channel": row[1].strip(), "date": row[2].strip(), "w": w_, "h": h_, "title": row[4].strip(), "dur": round(float(dur), 2),
            "size": int(s["size"]), "key": f"{stormlib.PREFIX}src/{s['id']}.mp4",
            "kind": stormdesk.source_kind(row[1].strip(), row[4].strip())}


def build_pack(sources: List[dict], out: str) -> Tuple[dict, dict]:
    """(catalog, stats): the kit's per-source index files as one compressed file."""
    import numpy as np
    ids, src, emb, a, b, text, top, face, k = [], [], [], [], [], [], [], [], []
    cat: Dict[str, dict] = {}
    no_faces = 0
    for s in sources:
        with np.load(s["index"]) as z:
            n = len(z["a"])
            cat[s["id"]] = catalog_row(s, float(z["dur"]))
            if not n:
                continue
            emb.append(z["emb"].astype(np.float32))
            a.append(z["a"])
            b.append(z["b"])
            text.append(z["text"])
            top.append(z["text_top"])
            k.append(z["k"])
        if os.path.isfile(s["faces"]):
            f = np.load(s["faces"])
            face.append(f if len(f) == n else np.zeros(n, np.float32))
        else:
            no_faces += 1
            face.append(np.zeros(n, np.float32))        # the gate before the render still looks at every placed shot
        src.append(np.full(n, len(ids), np.int32))
        ids.append(s["id"])
    def cat_(xs, dim=None):
        return np.concatenate(xs) if xs else (np.zeros((0, dim), np.float32) if dim else np.zeros(0, np.float32))
    np.savez_compressed(out, ids=np.array(ids), src=cat_(src).astype(np.int32), emb=cat_(emb, 512), a=cat_(a), b=cat_(b), text=cat_(text),
                        text_top=cat_(top), face=cat_(face), k=cat_(k).astype(np.int32))
    return {"version": 1, "updated": int(time.time()), "sources": cat}, {"shots": int(sum(len(x) for x in a)), "sourcesWithoutFaces": no_faces}


def export_text_model(out: str) -> dict:
    """The text half of CLIP ViT-B-32 laion2b_s34b_b79k (what the index was made with) as float32 ONNX, 254 MB, checked against
    torch. Not quantized: dynamic int8 took it to a cosine of 0.57-0.79 with the real model (measured 2026-11-07), a search on
    those numbers would be noise. Needs torch, open_clip, onnx. Takes exactly 77 token ids (padded with 0)."""
    import numpy as np
    import onnxruntime as ort
    import open_clip
    import torch
    model, _, _ = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k")
    model.eval()
    tok = open_clip.get_tokenizer("ViT-B-32")

    class Text(torch.nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, ids):
            return self.m.encode_text(ids)
    dummy = tok(["a flooded street"])
    torch.onnx.export(Text(model), (dummy,), out, input_names=["input_ids"], output_names=["emb"],
                      dynamic_axes={"input_ids": {0: "n"}, "emb": {0: "n"}}, opset_version=17, dynamo=False)
    prompts = ["aerial view of a flooded town", "a boat ramp far above the low water of a lake", "a TV news anchor sitting at a desk"]
    sess = ort.InferenceSession(out, providers=["CPUExecutionProvider"])
    worst = 1.0
    with torch.no_grad():
        for p in prompts:
            ids = tok([p])
            t = model.encode_text(ids)[0].numpy()
            o = sess.run(None, {"input_ids": ids.numpy().astype(np.int64)})[0][0]
            worst = min(worst, float(t @ o / (np.linalg.norm(t) * np.linalg.norm(o))))
    if worst < 0.995:
        raise SystemExit(f"the exported text model differs from torch (cosine {worst:.4f}): not uploaded")
    return {"mb": round(os.path.getsize(out) / 1e6, 1), "cosine": round(worst, 5)}


def public_buckets() -> set:
    from src import config
    return {b for b in (str(getattr(config, "R2_BUCKET", "") or ""), str(getattr(config, "R2_LIBRARY_BUCKET", "") or "")) if b}


def push(kit: str, bucket: str, upload: bool = False, workers: int = 1, limit: int = 0, r2=None, out=print) -> dict:
    """Dry run unless `upload`. Returns its report."""
    sources, left = plan(kit)
    if limit:
        sources = sources[:limit]
    gb = sum(s["size"] for s in sources) / 1e9
    rep = {"sources": len(sources), "gb": round(gb, 1), "left": left, "sent": 0, "skipped": 0, "failed": [], "upload": bool(upload)}
    out(f"{len(sources)} sources, {gb:.1f} GB to go; stayed behind: {left or 'none'}")
    if not upload:
        out("Dry run: nothing sent. Add --bucket <private bucket> --upload to send.")
        return rep
    if not bucket:
        raise SystemExit("--upload needs --bucket")
    if bucket in public_buckets():
        raise SystemExit("that bucket has a public domain: the library goes in a private one only")
    if r2 is None:
        from src import r2 as r2_mod
        r2 = r2_mod
    if not r2._creds():
        raise SystemExit("R2 keys are not in this shell's environment")
    have = {r["key"]: int(r.get("size") or 0) for r in r2.list_keys(stormlib.PREFIX, bucket=bucket, limit=100000)}
    done: List[dict] = []

    def one(s: dict) -> None:
        key = f"{stormlib.PREFIX}src/{s['id']}.mp4"
        if have.get(key) == s["size"]:
            rep["skipped"] += 1
            done.append(s)
            return
        try:
            r2.upload(s["path"], key, content_type="video/mp4", bucket=bucket, base="https://private.invalid",
                      deadline=time.time() + max(1800.0, s["size"] / 2e5))
            r2.upload(s["index"], f"{stormlib.PREFIX}index/{s['id']}.npz", content_type="application/octet-stream", bucket=bucket,
                      base="https://private.invalid", deadline=time.time() + 300)
            rep["sent"] += 1
            done.append(s)
            out(f"{rep['sent'] + rep['skipped']}/{len(sources)} {s['id']} {s['size'] // 2 ** 20} MB")
        except Exception as e:  # noqa: BLE001 - the next run takes it again; the message never carries a link
            rep["failed"].append(s["id"])
            out(f"{s['id']} not sent: {type(e).__name__}")
    with ThreadPoolExecutor(max(1, workers)) as ex:
        list(ex.map(one, sources))
    # Last: only what is on the bucket.
    with tempfile.TemporaryDirectory() as td:
        pack = os.path.join(td, "index_pack.npz")
        ordered = [s for s in sources if s in done]
        cat, stats = build_pack(ordered, pack)
        r2.upload(pack, stormlib.PACK_KEY, content_type="application/octet-stream", bucket=bucket, base="https://private.invalid",
                  deadline=time.time() + 1800)
        r2.upload_bytes(json.dumps(cat, separators=(",", ":")).encode(), stormlib.CATALOG_KEY, bucket=bucket, base="https://private.invalid",
                        deadline=time.time() + 120)
    rep.update(stats)
    out(f"index: {stats['shots']} shots of {len(ordered)} sources. Sent {rep['sent']}, already there {rep['skipped']}, failed {len(rep['failed'])}.")
    return rep


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kit", default=os.path.join(HERE, "..", "tools", "storm-desk-kit"))
    ap.add_argument("--bucket", default=os.environ.get("R2_SDLIB_BUCKET", ""))
    ap.add_argument("--upload", action="store_true", help="send; without it this is a dry run")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0, help="only the first N sources")
    ap.add_argument("--text-model", action="store_true", help="export the CLIP text model (torch, open_clip) and send it")
    a = ap.parse_args(argv)
    low_priority()
    if a.text_model:
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "clip_b32_text.onnx")
            print("text model:", export_text_model(path))
            if a.upload:
                from src import r2
                if not a.bucket or a.bucket in public_buckets():
                    raise SystemExit("--upload needs a private --bucket")
                r2.upload(path, stormlib.TEXT_MODEL_KEY, content_type="application/octet-stream", bucket=a.bucket,
                          base="https://private.invalid", deadline=time.time() + 1800)
                print("text model sent")
    push(os.path.abspath(a.kit), a.bucket, upload=a.upload, workers=a.workers, limit=a.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
