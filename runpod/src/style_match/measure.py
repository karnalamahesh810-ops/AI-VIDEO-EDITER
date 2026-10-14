"""
Style Match: measure a reference video's editing style (2026-10-14).

Everything here is local and deterministic (ffmpeg decoding, numpy / OpenCV pixel work, the YuNet face model the
worker already ships); src/style_match/vision.py adds a handful of cheap vision calls on top (what a text says,
what role it plays, where the cold open ends). The owner's rule (memory: analyze-references-before-building):
catalogue every element's font, size, colours, stroke / glow / shadow, position, entrance and exit motion in
frames, how long it holds, WHEN it is used and the sound with it - plus pacing, intro length and the mix.

    analyse(path, workdir) -> measurements dict (kit.build turns it into the Style Kit)

Passes:
  1. the whole video at 10 fps, 192x108: cuts, flashes, dips, gradual transitions, whips, pace, grade samples
  2. the first `detail_seconds` at 5 fps, 640x360: on-screen text lines and graphic marks (rings, triangles,
     arrows, boxes), picture-in-picture, split screen, blur-fill; each tracked over time into instances
  3. per element type a few instances at full resolution: colours, stroke, glow band, shadow, box, cap height,
     tilt, the glyph mask for the font match; and their entrance / exit frame by frame at the native rate
  4. audio: loudness, voice level, music bed under the voice, SFX transients and where they land
"""
import json
import math
import os
import subprocess
from typing import Dict, Iterator, List, Optional, Tuple

import numpy as np

try:
    import cv2
except Exception:  # noqa: BLE001 - the image installs opencv-python-headless; tests skip without it
    cv2 = None

P1_FPS, P1_W, P1_H = 10, 192, 108
P2_FPS, P2_W, P2_H = 5, 640, 360


# ------------------------------------------------------------------ decoding
def probe(path: str) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration:stream=codec_type,width,height,r_frame_rate", "-of", "json", path],
                         capture_output=True, text=True, timeout=60)
    d = json.loads(out.stdout or "{}")
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
    num, _, den = str(v.get("r_frame_rate") or "30/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 30.0
    return {"duration": float((d.get("format") or {}).get("duration") or 0), "fps": round(fps, 3),
            "width": int(v.get("width") or 0), "height": int(v.get("height") or 0),
            "audio": any(s.get("codec_type") == "audio" for s in d.get("streams", []))}


def frames(path: str, fps: float, w: int, h: int, t0: float = 0.0, dur: Optional[float] = None,
           crop: Optional[str] = None) -> Iterator[Tuple[float, np.ndarray]]:
    """Decoded BGR frames (t, HxWx3 uint8). fps=0 keeps the native rate."""
    vf = []
    if fps:
        vf.append(f"fps={fps}")
    if crop:
        vf.append(crop)
    vf.append(f"scale={w}:{h}:flags=area")
    cmd = ["ffmpeg", "-v", "error", "-nostdin"]
    if t0 > 0:
        cmd += ["-ss", f"{t0:.3f}"]
    cmd += ["-i", path]
    if dur:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-an", "-vf", ",".join(vf), "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=w * h * 3 * 4)
    n, size = 0, w * h * 3
    rate = fps or probe(path)["fps"]
    try:
        while True:
            buf = p.stdout.read(size)
            if len(buf) < size:
                break
            yield t0 + n / rate, np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            n += 1
    finally:
        p.stdout.close()
        p.kill()
        p.wait()


def frame_at(path: str, t: float, w: int = 0, h: int = 0) -> Optional[np.ndarray]:
    """One frame at full (or the given) size."""
    if not w or not h:
        pr = probe(path)
        w, h = pr["width"], pr["height"]
    for _, f in frames(path, 0, w, h, max(0.0, t), 0.2):
        return f.copy()
    return None


def _hsv(bgr):
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)


def _hex(bgr) -> str:
    b, g, r = [int(max(0, min(255, round(float(x))))) for x in bgr[:3]]
    return f"#{r:02X}{g:02X}{b:02X}"


def _q(a, p):
    a = np.asarray(a, float)
    return float(np.percentile(a, p)) if a.size else 0.0


def _stats(a) -> dict:
    a = np.asarray(a, float)
    if not a.size:
        return {"n": 0}
    return {"n": int(a.size), "median": round(float(np.median(a)), 3), "mean": round(float(a.mean()), 3),
            "p10": round(_q(a, 10), 3), "p90": round(_q(a, 90), 3)}


# ------------------------------------------------------------------ pass 1: cuts, transitions, pace, grade
def pass1(path: str, max_seconds: float, keep_gray_until: float) -> dict:
    ts, luma, sat, hists, gxs, gys, grays, thumbs = [], [], [], [], [], [], [], []
    for t, f in frames(path, P1_FPS, P1_W, P1_H, 0.0, max_seconds):
        hsv = _hsv(f)
        h = cv2.calcHist([hsv], [0, 1, 2], None, [8, 4, 4], [0, 180, 0, 256, 0, 256]).ravel()
        hists.append(h / max(1.0, h.sum()))
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        luma.append(float(g.mean()))
        sat.append(float(hsv[..., 1].mean()))
        gf = g.astype(np.float32)
        gxs.append(float(np.abs(np.diff(gf, axis=1)).mean()))
        gys.append(float(np.abs(np.diff(gf, axis=0)).mean()))
        if t < keep_gray_until:
            grays.append(cv2.resize(g, (160, 90), interpolation=cv2.INTER_AREA))
        if len(ts) % (P1_FPS * 2) == 0:
            thumbs.append(f.copy())
        ts.append(t)
    return {"t": np.array(ts), "luma": np.array(luma), "sat": np.array(sat), "hist": np.array(hists),
            "gx": np.array(gxs), "gy": np.array(gys), "gray": grays, "thumbs": thumbs}


def detect_cuts(p1: dict) -> dict:
    """Hard cuts (adaptive histogram jumps), flashes, dips to black, gradual transitions and whip pans."""
    t, H, L = p1["t"], p1["hist"], p1["luma"]
    n = len(t)
    if n < 3:
        return {"cuts": [], "transitions": []}
    d = np.zeros(n)
    d[1:] = 0.5 * np.abs(np.diff(H, axis=0)).sum(axis=1)
    med = np.array([np.median(d[max(0, i - 15):i + 16]) for i in range(n)])
    cut_idx = []
    for i in range(1, n):
        if d[i] > max(0.28, 3.2 * med[i] + 0.06) and d[i] >= d[max(0, i - 1)] and d[i] >= d[min(n - 1, i + 1)]:
            if not cut_idx or i - cut_idx[-1] >= 2:
                cut_idx.append(i)
    # flashes / dips: short runs of near-white / near-black frames
    trans: List[dict] = []
    for kind, mask in (("flash", L > 222), ("dip", L < 14)):
        i = 0
        while i < n:
            if mask[i]:
                j = i
                while j + 1 < n and mask[j + 1]:
                    j += 1
                span = (j - i + 1) / P1_FPS
                if span <= (0.6 if kind == "flash" else 1.6) and i > 0 and j < n - 1:
                    trans.append({"kind": kind, "t": round(float(t[i]), 2), "dur": round(span, 2)})
                i = j + 1
            else:
                i += 1
    # gradual transitions: a big change over ~0.8 s with no hard jump, the middle frame a blend of both ends
    gray = p1["gray"]
    k = 8
    for i in range(k, min(n, len(gray))):
        a, b = i - k, i
        if any(a < c <= b for c in cut_idx):
            continue
        D = 0.5 * np.abs(H[b] - H[a]).sum()
        if D < 0.45 or d[a + 1:b + 1].max() > 0.22:
            continue
        A, B, M = gray[a].astype(np.float32), gray[b].astype(np.float32), gray[(a + b) // 2].astype(np.float32)
        best = min(np.abs(M - (al * A + (1 - al) * B)).mean() for al in (0.25, 0.5, 0.75))
        if best < 0.35 * np.abs(A - B).mean():
            tt = float(t[(a + b) // 2])
            if not trans or abs(trans[-1]["t"] - tt) > 1.0:
                trans.append({"kind": "crossfade", "t": round(tt, 2), "dur": round(k / P1_FPS, 2)})
    cuts = [round(float(t[i]), 2) for i in cut_idx]
    # whips: a cut whose neighbouring frames are smeared sideways (x gradients collapse against y gradients)
    gx, gy = p1["gx"], p1["gy"]
    ratio = gx / np.maximum(gy, 1e-3)
    base = float(np.median(ratio))
    for i in cut_idx:
        r = min(ratio[max(0, i - 1)], ratio[i]) if i > 0 else ratio[i]
        if r < 0.45 * base and gy[i] > 1.5:
            trans.append({"kind": "whip", "t": round(float(t[i]), 2), "dur": 0.2})
    # flashes and dips sitting on a cut are that cut's transition
    trans.sort(key=lambda x: x["t"])
    return {"cuts": cuts, "transitions": trans, "cut_score": [round(float(d[i]), 3) for i in cut_idx]}


def pacing(cuts: List[float], duration: float) -> dict:
    b = [0.0] + [c for c in cuts if 0.15 < c < duration - 0.15] + [duration]
    shots = np.diff(b)
    first = [c for c in cuts if c < 60]
    out = {"cuts": len(cuts), "shot": _stats(shots), "cutsPerMin": round(len(cuts) / max(1e-6, duration / 60), 1),
           "first60CutsPerMin": round(len(first) / (min(60.0, duration) / 60), 1),
           "restCutsPerMin": round((len(cuts) - len(first)) / max(1e-6, (duration - 60) / 60), 1) if duration > 90 else None,
           "hist": {"bins": "0-1,1-2,2-3,3-4,4-6,6-8,8-12,12-20,20+",
                    "counts": np.histogram(shots, [0, 1, 2, 3, 4, 6, 8, 12, 20, 1e9])[0].tolist()},
           "curve": []}
    for w0 in range(0, int(min(duration, 300)), 15):
        n = sum(1 for c in cuts if w0 <= c < w0 + 15)
        out["curve"].append({"t": w0, "cutsPerMin": n * 4})
    return out


# ------------------------------------------------------------------ camera: punch-ins and pushes
def _scale_match(a: np.ndarray, b: np.ndarray, scales=(1.0, 1.1, 1.2, 1.3, 1.45, 1.6, 1.8, 2.0)) -> Tuple[float, float]:
    """Best s so that b ~ a zoomed in by s (b shrunk by 1/s found inside a). Returns (s, ncc)."""
    best = (1.0, -1.0)
    for s in scales:
        w, h = int(round(b.shape[1] / s)), int(round(b.shape[0] / s))
        if w < 24 or h < 14:
            continue
        tpl = cv2.resize(b, (w, h), interpolation=cv2.INTER_AREA)
        r = cv2.matchTemplate(a, tpl, cv2.TM_CCOEFF_NORMED)
        v = float(r.max())
        if v > best[1] + 0.01:
            best = (s, v)
    return best


def camera(p1: dict, cuts: List[float]) -> dict:
    gray, t = p1["gray"], p1["t"]
    n = len(gray)
    punch, pushes, checked = [], [], 0
    cut_frames = [int(round(c * P1_FPS)) for c in cuts]
    for ci in cut_frames:
        if ci < 2 or ci + 1 >= n:
            continue
        checked += 1
        a, b = gray[ci - 2], gray[ci + 1]
        s, v = _scale_match(a, b, (1.15, 1.3, 1.45, 1.6, 1.8, 2.0))
        if v > 0.78 and s >= 1.15:
            punch.append({"t": round(float(t[ci]), 2), "scale": s, "ncc": round(v, 2)})
    bounds = [0] + cut_frames + [n]
    for a0, b0 in zip(bounds[:-1], bounds[1:]):
        if b0 - a0 < 2 * P1_FPS:
            continue
        i, j = a0 + 2, min(b0 - 2, a0 + 2 + 2 * P1_FPS)
        if j >= n:
            continue
        s, v = _scale_match(gray[i], gray[j], (1.0, 1.02, 1.04, 1.07, 1.1, 1.15))
        s_out, v_out = _scale_match(gray[j], gray[i], (1.02, 1.04, 1.07, 1.1, 1.15))
        rate = 0.0
        if v > 0.85 and s > 1.0 and (v >= v_out):
            rate = (s - 1.0) / ((j - i) / P1_FPS)
        elif v_out > 0.85 and v_out > v:
            rate = -(s_out - 1.0) / ((j - i) / P1_FPS)
        pushes.append(rate)
    pushes = np.array(pushes)
    dur = float(t[-1]) if len(t) else 1.0
    return {"punchIns": punch[:60], "punchInPerMin": round(len(punch) / max(1e-6, min(dur, len(gray) / P1_FPS) / 60), 2),
            "punchInScale": _stats([p["scale"] for p in punch]),
            "pushInShare": round(float((pushes > 0.012).mean()), 2) if pushes.size else 0.0,
            "pullOutShare": round(float((pushes < -0.012).mean()), 2) if pushes.size else 0.0,
            "pushRate": round(float(np.median(pushes[pushes > 0.012])), 3) if (pushes > 0.012).any() else 0.0,
            "shotsChecked": int(pushes.size), "cutsChecked": checked}


# ------------------------------------------------------------------ grade
def grade(thumbs: List[np.ndarray]) -> dict:
    if not thumbs:
        return {}
    L, S, warm, tint, sh, hi, p1, p99, vig, con = [], [], [], [], [], [], [], [], [], []
    for f in thumbs:
        fl = f.astype(np.float32)
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32)
        if g.mean() < 8 or g.mean() > 245:
            continue
        hsv = _hsv(f)
        L.append(g.mean())
        con.append(g.std())
        S.append(hsv[..., 1].mean())
        mid = (g > 60) & (g < 190)
        if mid.any():
            warm.append(float((fl[..., 2][mid] - fl[..., 0][mid]).mean()))
            tint.append(float((fl[..., 1][mid] - (fl[..., 2][mid] + fl[..., 0][mid]) / 2).mean()))
        lo, hi_ = np.percentile(g, 10), np.percentile(g, 90)
        sh.append(fl[g <= lo].mean(axis=0))
        hi.append(fl[g >= hi_].mean(axis=0))
        p1.append(np.percentile(g, 1))
        p99.append(np.percentile(g, 99))
        h, w = g.shape
        c = g[h // 4:3 * h // 4, w // 4:3 * w // 4].mean()
        corners = np.concatenate([g[:h // 6, :w // 6].ravel(), g[:h // 6, -w // 6:].ravel(),
                                  g[-h // 6:, :w // 6].ravel(), g[-h // 6:, -w // 6:].ravel()]).mean()
        vig.append(corners / max(1.0, c))
    if not L:
        return {}
    shm, him = np.mean(sh, axis=0), np.mean(hi, axis=0)
    return {"luma": round(float(np.mean(L)), 1), "contrast": round(float(np.mean(con)), 1),
            "saturation": round(float(np.mean(S)), 1), "warmth": round(float(np.mean(warm or [0])), 1),
            "tint": round(float(np.mean(tint or [0])), 1), "shadows": _hex(shm), "highlights": _hex(him),
            "black": round(float(np.median(p1)), 1), "white": round(float(np.median(p99)), 1),
            "vignette": round(float(np.median(vig)), 2), "samples": len(L)}


def grain(frames_full: List[np.ndarray]) -> float:
    """Film grain / noise: the high-pass level in flat areas, 0-255 units at 720p."""
    vals = []
    for f in frames_full:
        g = cv2.cvtColor(cv2.resize(f, (1280, 720)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        hp = g - cv2.GaussianBlur(g, (0, 0), 1.5)
        lo = cv2.GaussianBlur(g, (0, 0), 6)
        flat = np.abs(cv2.Laplacian(lo, cv2.CV_32F)) < 0.6
        if flat.mean() > 0.05:
            vals.append(float(np.abs(hp[flat]).mean()))
    return round(float(np.median(vals)), 2) if vals else 0.0


# ------------------------------------------------------------------ pass 2: text lines + marks + layouts
COLOURS = ("white", "yellow", "red", "green", "cyan", "blue", "magenta", "orange", "black")


def colour_masks(hsv: np.ndarray) -> Dict[str, np.ndarray]:
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    vivid = S >= 120
    return {
        "white": (V >= 215) & (S <= 45),
        "yellow": (H >= 18) & (H <= 40) & vivid & (V >= 170),
        "orange": (H >= 9) & (H < 18) & (S >= 150) & (V >= 170),
        "red": ((H <= 8) | (H >= 172)) & (S >= 150) & (V >= 130),
        "green": (H > 40) & (H <= 85) & vivid & (V >= 130),
        "cyan": (H > 85) & (H <= 105) & vivid & (V >= 150),
        "blue": (H > 105) & (H <= 130) & (S >= 130) & (V >= 110),
        "magenta": (H >= 140) & (H < 172) & vivid & (V >= 150),
    }


def _components(mask: np.ndarray, Hf: int):
    n, lab, st, cen = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    out = []
    for i in range(1, min(n, 1500)):
        x, y, w, h, a = st[i]
        out.append((i, int(x), int(y), int(w), int(h), int(a)))
    return lab, out


def text_lines(bgr: np.ndarray) -> Tuple[List[dict], List[dict]]:
    """On-screen text lines and graphic marks in one 640x360 frame."""
    Hf, Wf = bgr.shape[:2]
    hsv = _hsv(bgr)
    V = hsv[..., 2]
    masks = colour_masks(hsv)
    lines, marks = [], []
    k3 = np.ones((3, 3), np.uint8)
    for cname, m in masks.items():
        if m.mean() > 0.45 or not m.any():
            continue
        lab, comps = _components(m, Hf)
        glyphs = []
        for (i, x, y, w, h, a) in comps:
            if not (0.018 * Hf <= h <= 0.2 * Hf) or w > 12 * h or a < 10:
                if cname != "white" and a >= 0.0008 * Hf * Wf and 0.03 * Hf <= max(w, h) <= 0.65 * Hf:
                    marks.append(("cand", cname, i, x, y, w, h, a))
                continue
            fill = a / float(w * h)
            if not 0.12 <= fill <= 0.9:
                if cname != "white" and a >= 0.0008 * Hf * Wf and 0.03 * Hf <= max(w, h) <= 0.65 * Hf:
                    marks.append(("cand", cname, i, x, y, w, h, a))
                continue
            x0, y0, x1, y1 = max(0, x - 3), max(0, y - 3), min(Wf, x + w + 3), min(Hf, y + h + 3)
            cm = (lab[y0:y1, x0:x1] == i).astype(np.uint8)
            ring = (cv2.dilate(cm, k3, iterations=2) > 0) & (cm == 0)
            # an outline: the ring round the glyph is much darker than the glyph (a black line, or the olive
            # glow band of a yellow pop), not only near-black
            vv = V[y0:y1, x0:x1]
            fv = float(np.median(vv[cm > 0])) if cm.any() else 255.0
            dk = float((vv[ring] < min(140.0, 0.6 * fv)).mean()) if ring.any() else 0.0
            glyphs.append({"i": i, "x": x, "y": y, "w": w, "h": h, "a": a, "dark": dk, "cy": y + h / 2})
        if len(glyphs) < 2:
            # a single vivid component may still be a mark
            continue
        glyphs.sort(key=lambda g: g["x"])
        used = [False] * len(glyphs)
        for gi, g in enumerate(glyphs):
            if used[gi]:
                continue
            row = [g]
            used[gi] = True
            right = g["x"] + g["w"]
            for gj in range(gi + 1, len(glyphs)):
                o = glyphs[gj]
                if used[gj]:
                    continue
                hh = max(o["h"], row[-1]["h"])
                if o["x"] - right > 1.2 * hh:
                    break
                ref = float(np.median([r["cy"] for r in row]))
                if abs(o["cy"] - ref) < 0.4 * hh and max(o["h"], g["h"]) / max(1, min(o["h"], g["h"])) < 2.2:
                    row.append(o)
                    used[gj] = True
                    right = max(right, o["x"] + o["w"])
            hmed = float(np.median([r["h"] for r in row]))
            x0 = min(r["x"] for r in row)
            y0 = min(r["y"] for r in row)
            x1 = max(r["x"] + r["w"] for r in row)
            y1 = max(r["y"] + r["h"] for r in row)
            if len(row) < 2 or (x1 - x0) < 1.4 * hmed:
                continue
            outlined = float(np.median([r["dark"] for r in row]))
            # a box: the area round the glyphs (not the glyphs) is one flat colour
            px, py = int(0.7 * hmed), int(0.55 * hmed)
            bx0, by0, bx1, by1 = max(0, x0 - px), max(0, y0 - py), min(Wf, x1 + px), min(Hf, y1 + py)
            region = bgr[by0:by1, bx0:bx1].reshape(-1, 3).astype(np.float32)
            not_txt = ~m[by0:by1, bx0:bx1].reshape(-1)
            boxed, box_col = False, None
            if not_txt.sum() > 20:
                bg = region[not_txt]
                medc = np.median(bg, axis=0)
                near = (np.abs(bg - medc).max(axis=1) < 28).mean()
                if near > 0.82:
                    boxed, box_col = True, _hex(medc)
            n_ok = len(row) >= (4 if cname == "white" else 3)
            if not (outlined >= 0.45 or boxed or n_ok):
                continue
            lines.append({"colour": cname, "x0": x0 / Wf, "y0": y0 / Hf, "x1": x1 / Wf, "y1": y1 / Hf,
                          "h": hmed / Hf, "n": len(row), "outlined": round(outlined, 2), "boxed": boxed,
                          "box": box_col, "sig": cv2.resize(m[y0:y1, x0:x1].astype(np.uint8) * 255, (48, 12))})
    # marks: vivid components that are not glyphs - rings, triangles, arrows, box outlines
    for (_, cname, i, x, y, w, h, a) in marks[:60]:
        sub = (cv2.connectedComponents(masks[cname][y:y + h, x:x + w].astype(np.uint8), 8)[1] > 0).astype(np.uint8)
        cs, _ = cv2.findContours(sub, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cs:
            continue
        c = max(cs, key=cv2.contourArea)
        ca = cv2.contourArea(c)
        per = cv2.arcLength(c, True)
        if ca < 30 or per < 10:
            continue
        hollow = a / max(1.0, ca)
        circ = 4 * math.pi * ca / (per * per)
        hull = cv2.convexHull(c)
        solidity = ca / max(1.0, cv2.contourArea(hull))
        approx = cv2.approxPolyDP(c, 0.04 * per, True)
        asp = w / max(1.0, h)
        shape = None
        if hollow < 0.45 and circ > 0.55 and 0.55 < asp < 1.8:
            shape = "ring"
        elif hollow < 0.4 and len(approx) == 4:
            shape = "box"
        elif len(approx) == 3 and solidity > 0.85 and hollow > 0.8:
            shape = "triangle"
        elif 5 <= len(approx) <= 9 and 0.5 < solidity < 0.88 and hollow > 0.75 and max(asp, 1 / asp) > 1.3:
            shape = "arrow"
        if shape:
            marks_ = {"shape": shape, "colour": cname, "x0": x / Wf, "y0": y / Hf, "x1": (x + w) / Wf,
                      "y1": (y + h) / Hf, "area": a / float(Wf * Hf)}
            lines.append({"mark": marks_})
    return [l for l in lines if "mark" not in l], [l["mark"] for l in lines if "mark" in l]


def layout_flags(bgr: np.ndarray) -> dict:
    """Blur-fill (a sharp centre band over a blurred copy), pillarbox, split-screen divider, picture-in-picture."""
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    Hf, Wf = g.shape
    lap = np.abs(cv2.Laplacian(g, cv2.CV_32F))
    col = lap.mean(axis=0)
    side = np.r_[col[: Wf // 5], col[-Wf // 5:]].mean()
    centre = col[int(Wf * 0.38):int(Wf * 0.62)].mean()
    side_l = np.r_[g[:, : Wf // 6].ravel(), g[:, -Wf // 6:].ravel()].mean()
    out = {"blurFill": bool(centre > 3.0 * side and side_l > 22), "pillarbox": bool(side_l < 8 and g[:, Wf // 3:2 * Wf // 3].mean() > 25)}
    gxa = np.abs(np.diff(g.astype(np.int16), axis=1))
    strong = (gxa > 45).mean(axis=0)
    mid = strong[int(Wf * 0.3):int(Wf * 0.7)]
    out["split"] = bool(mid.size and mid.max() > 0.85)
    edges = cv2.Canny(g, 60, 160)
    cs, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    pip = None
    for c in cs:
        x, y, w, h = cv2.boundingRect(c)
        a = w * h / float(Wf * Hf)
        if not 0.04 <= a <= 0.4 or x < 0.02 * Wf or y < 0.02 * Hf or x + w > 0.98 * Wf or y + h > 0.98 * Hf:
            continue
        ap = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
        if len(ap) == 4 and cv2.contourArea(ap) > 0.85 * w * h:
            pip = {"x": round((x + w / 2) / Wf, 2), "y": round((y + h / 2) / Hf, 2), "w": round(w / Wf, 2), "h": round(h / Hf, 2)}
            break
    out["pip"] = pip
    return out


def _iou(a: dict, b: dict) -> float:
    iw = max(0.0, min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]))
    ih = max(0.0, min(a["y1"], b["y1"]) - max(a["y0"], b["y0"]))
    inter = iw * ih
    u = (a["x1"] - a["x0"]) * (a["y1"] - a["y0"]) + (b["x1"] - b["x0"]) * (b["y1"] - b["y0"]) - inter
    return inter / u if u > 0 else 0.0


def pass2(path: str, seconds: float) -> dict:
    """Track text lines and marks over the first `seconds` at 5 fps into instances (one per appearance)."""
    open_t: List[dict] = []
    done: List[dict] = []
    open_m: List[dict] = []
    done_m: List[dict] = []
    lay = {"blurFill": 0, "pillarbox": 0, "split": 0, "pip": 0, "n": 0, "pipBoxes": []}
    step = 1.0 / P2_FPS
    for k, (t, f) in enumerate(frames(path, P2_FPS, P2_W, P2_H, 0.0, seconds)):
        lines, marks = text_lines(f)
        if k % P2_FPS == 0:
            fl = layout_flags(f)
            lay["n"] += 1
            for key_ in ("blurFill", "pillarbox", "split"):
                lay[key_] += int(fl[key_])
            if fl["pip"]:
                lay["pip"] += 1
                lay["pipBoxes"].append(dict(fl["pip"], t=round(t, 1)))
        still = []
        for ln in lines:
            best, bi = 0.0, -1
            for j, o in enumerate(open_t):
                if o["colour"] != ln["colour"] or o["boxed"] != ln["boxed"]:
                    continue
                v = _iou(o["last"], ln)
                if v > best:
                    best, bi = v, j
            if bi >= 0 and best > 0.45:
                o = open_t[bi]
                same = float(np.mean(np.abs(cv2.resize(o["last"]["sig"], (48, 12)).astype(np.float32)
                                            - ln["sig"].astype(np.float32)))) < 60
                if same or not o["boxed"]:
                    o["last"], o["t1"] = ln, t + step
                    o["boxes"].append((ln["x0"], ln["y0"], ln["x1"], ln["y1"]))
                    o["hs"].append(ln["h"])
                    still.append(o)
                    open_t.pop(bi)
                    continue
            still.append({"colour": ln["colour"], "boxed": ln["boxed"], "box": ln["box"], "t0": t, "t1": t + step,
                          "last": ln, "first": ln, "boxes": [(ln["x0"], ln["y0"], ln["x1"], ln["y1"])],
                          "hs": [ln["h"]], "outlined": ln["outlined"], "n": ln["n"]})
        done.extend(open_t)
        open_t = still
        still_m = []
        for mk in marks:
            hit = None
            for j, o in enumerate(open_m):
                if o["shape"] == mk["shape"] and o["colour"] == mk["colour"] and _iou(o["last"], mk) > 0.2:
                    hit = j
                    break
            if hit is not None:
                o = open_m.pop(hit)
                o["last"], o["t1"] = mk, t + step
                o["areas"].append(mk["area"])
                still_m.append(o)
            else:
                still_m.append({"shape": mk["shape"], "colour": mk["colour"], "t0": t, "t1": t + step, "last": mk,
                                "first": mk, "areas": [mk["area"]]})
        done_m.extend(open_m)
        open_m = still_m
    done.extend(open_t)
    done_m.extend(open_m)
    texts = []
    for o in done:
        if o["t1"] - o["t0"] < 2 * step - 1e-6:
            continue
        b = np.median(np.array(o["boxes"]), axis=0)
        texts.append({"colour": o["colour"], "boxed": o["boxed"], "box": o["box"], "t0": round(o["t0"], 2),
                      "t1": round(o["t1"], 2), "x0": float(b[0]), "y0": float(b[1]), "x1": float(b[2]), "y1": float(b[3]),
                      "h": float(np.median(o["hs"])), "outlined": o["outlined"], "n": o["n"],
                      "growth": round(float((o["last"]["x1"] - o["last"]["x0"]) / max(1e-6, o["first"]["x1"] - o["first"]["x0"])), 3)})
    marks = []
    for o in done_m:
        if o["t1"] - o["t0"] < 2 * step - 1e-6:
            continue
        l = o["last"]
        marks.append({"shape": o["shape"], "colour": o["colour"], "t0": round(o["t0"], 2), "t1": round(o["t1"], 2),
                      "x0": l["x0"], "y0": l["y0"], "x1": l["x1"], "y1": l["y1"],
                      "areaGrowth": round(float(o["areas"][-1] / max(1e-9, o["areas"][0])), 2)})
    n = max(1, lay["n"])
    layouts = {"blurFillShare": round(lay["blurFill"] / n, 3), "pillarboxShare": round(lay["pillarbox"] / n, 3),
               "splitShare": round(lay["split"] / n, 3), "pipShare": round(lay["pip"] / n, 3),
               "pipBoxes": lay["pipBoxes"][:12]}
    return {"texts": texts, "marks": marks, "layouts": layouts, "seconds": seconds}


# ------------------------------------------------------------------ clustering text instances into element types
def _size_bucket(h: float) -> int:
    return int(round(math.log(max(h, 1e-3)) / math.log(1.4)))


def cluster_texts(texts: List[dict]) -> List[dict]:
    groups: Dict[tuple, List[dict]] = {}
    for t in texts:
        yc = (t["y0"] + t["y1"]) / 2
        band = "bottom" if yc > 0.72 else ("top" if yc < 0.28 else "middle")
        k = (t["colour"], bool(t["boxed"]), t["outlined"] >= 0.45, _size_bucket(t["h"]), band)
        groups.setdefault(k, []).append(t)
    # merge neighbours that differ only by one size step
    keys = sorted(groups, key=lambda k: -len(groups[k]))
    merged: List[Tuple[tuple, List[dict]]] = []
    for k in keys:
        for mk, lst in merged:
            if mk[:3] == k[:3] and mk[4] == k[4] and abs(mk[3] - k[3]) <= 1:
                lst.extend(groups[k])
                break
        else:
            merged.append((k, list(groups[k])))
    out = []
    for k, lst in merged:
        total = sum(t["t1"] - t["t0"] for t in lst)
        if len(lst) < 2 and total < 1.5:
            continue
        lst.sort(key=lambda t: t["t0"])
        out.append({"colour": k[0], "boxed": k[1], "outlined": k[2], "band": k[4], "instances": lst,
                    "count": len(lst), "seconds": round(total, 1)})
    out.sort(key=lambda c: -c["seconds"])
    return out


# ------------------------------------------------------------------ full-resolution measurement of one instance
def measure_instance(full: np.ndarray, inst: dict) -> dict:
    """Colours, stroke, glow band, shadow, box, cap height, tilt and the glyph mask of one text line."""
    Hf, Wf = full.shape[:2]
    padx, pady = 0.04 * Wf, 0.5 * inst["h"] * Hf + 0.02 * Hf
    x0, x1 = int(max(0, inst["x0"] * Wf - padx)), int(min(Wf, inst["x1"] * Wf + padx))
    y0, y1 = int(max(0, inst["y0"] * Hf - pady)), int(min(Hf, inst["y1"] * Hf + pady))
    crop = full[y0:y1, x0:x1]
    if crop.size == 0:
        return {}
    hsv = _hsv(crop)
    m = colour_masks(hsv)[inst["colour"]] if inst["colour"] in COLOURS[:-1] else None
    if m is None or not m.any():
        return {}
    m8 = m.astype(np.uint8)
    # keep the glyph-sized components only (drop specks and big background areas of the same colour)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m8, 8)
    hh = inst["h"] * Hf
    keep = np.zeros_like(m8)
    ly0, ly1 = inst["y0"] * Hf - y0, inst["y1"] * Hf - y0          # the line's own rows and columns in the crop
    lx0, lx1 = inst["x0"] * Wf - x0 - 0.5 * hh, inst["x1"] * Wf - x0 + 0.5 * hh
    for i in range(1, n):
        x, y, w, h, a = st[i]
        ov = max(0.0, min(y + h, ly1) - max(y, ly0)) / max(1.0, h)
        if 0.45 * hh <= h <= 1.8 * hh and a >= 6 and ov >= 0.6 and x >= lx0 and x + w <= lx1                 and w <= 3.5 * h and 0.12 <= a / float(w * h) <= 0.92:
            keep[lab == i] = 1
    if keep.sum() < 20:
        keep = m8
    fill = np.median(crop[keep > 0].reshape(-1, 3), axis=0)
    out = {"fill": _hex(fill)}
    ys, xs = np.where(keep > 0)
    # tilt: a line through the glyph-centre columns
    if len(xs) > 30 and xs.max() - xs.min() > 20:
        A = np.vstack([xs, np.ones_like(xs)]).T
        slope = np.linalg.lstsq(A.astype(float), ys.astype(float), rcond=None)[0][0]
        out["tilt"] = round(float(-math.degrees(math.atan(slope))), 1)
    out["capH"] = round(float((ys.max() - ys.min() + 1) / Hf), 4)
    # rings outward from the glyphs: stroke (dark), then a band (glow / second outline), then background
    dist = cv2.distanceTransform((1 - keep).astype(np.uint8), cv2.DIST_L2, 3)
    rings = []
    for r in range(1, int(max(6, 0.06 * Hf)) + 1):
        sel = (dist > r - 1) & (dist <= r)
        if sel.sum() < 10:
            break
        rings.append(np.median(crop[sel].reshape(-1, 3), axis=0))
    def lum(c):
        return 0.114 * c[0] + 0.587 * c[1] + 0.299 * c[2]
    if inst.get("boxed") and inst.get("box"):
        out["box"] = inst["box"]
        # box padding: how far the flat colour runs past the glyphs
        bc = np.array([int(inst["box"][5:7], 16), int(inst["box"][3:5], 16), int(inst["box"][1:3], 16)], float)
        flat = (np.abs(crop.astype(np.float32) - bc).max(axis=2) < 30)
        cols = np.where(flat.mean(axis=0) > 0.5)[0]
        rows_ = np.where(flat[:, xs.min():xs.max() + 1].mean(axis=1) > 0.5)[0] if len(xs) else []
        if len(cols) and len(rows_):
            out["boxPadX"] = round(float(max(0, xs.min() - cols.min()) / Hf), 4)
            out["boxPadY"] = round(float(max(0, ys.min() - rows_.min()) / Hf), 4)
            out["boxH"] = round(float((rows_.max() - rows_.min() + 1) / Hf), 4)
            out["boxCenterY"] = round(float((y0 + (rows_.max() + rows_.min()) / 2) / Hf), 4)
    else:
        sw, sc, band, bandw = 0, None, None, 0
        for i, c in enumerate(rings):
            if lum(c) < min(95.0, 0.55 * lum(fill)):
                sw, sc = i + 1, c
            else:
                break
        if sw:
            rest = rings[sw:]
            bg = rings[-1] if rings else None
            for j, c in enumerate(rest):
                if bg is not None and np.abs(c - bg).max() > 25 and lum(c) < lum(fill) - 30:
                    band, bandw = c, j + 1
                else:
                    break
        out["stroke"] = {"width": round(sw / Hf, 4), "color": _hex(sc) if sc is not None else None}
        if band is not None and bandw >= 2:
            out["glow"] = {"width": round(bandw / Hf, 4), "color": _hex(band)}
        # drop shadow: darker below-right than above-left of the glyphs
        sh = np.zeros_like(keep)
        o = max(2, int(0.006 * Hf))
        sh[o:, o:] = keep[:-o, :-o]
        below = (sh > 0) & (keep == 0)
        above = np.zeros_like(keep)
        above[:-o, :-o] = keep[o:, o:]
        above = (above > 0) & (keep == 0)
        if below.any() and above.any():
            d = float(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)[above].mean() - cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)[below].mean())
            if d > 18:
                out["shadow"] = {"offset": round(o / Hf, 4), "strength": round(min(1.0, d / 120), 2)}
    # the glyph mask, levelled, for the font match
    gm = keep[max(0, ys.min() - 2):ys.max() + 3, max(0, xs.min() - 2):xs.max() + 3] if len(xs) else keep
    if "tilt" in out and abs(out["tilt"]) > 1.0:
        hgt, wid = gm.shape
        M = cv2.getRotationMatrix2D((wid / 2, hgt / 2), -out["tilt"], 1.0)
        gm = cv2.warpAffine(gm * 255, M, (wid, hgt)) > 127
    out["_mask"] = gm.astype(bool)
    out["_crop_box"] = (x0, y0, x1, y1)
    return out


def motion(path: str, inst: dict, fps_native: float, at: str = "in") -> dict:
    """
    The entrance (at='in') or exit (at='out') of one text line, frame by frame at the native rate.

    Timing comes from the SETTLED glyph mask (the line as it rests mid-hold): each frame's share of those glyph
    pixels that are already drawn. That is immune to a previous caption sitting in the same box (a text swap
    reads as a one-frame cut, not a fade). The kind comes from what the partly drawn frames look like: the
    drawn part growing from one side (per-letter / wipe), growing about its centre (scale), offset from its
    rest place (slide), or the whole line present but faint (fade).
    """
    x0, y0, x1, y1 = inst["x0"], inst["y0"], inst["x1"], inst["y1"]
    w, h = x1 - x0, y1 - y0
    cx0, cy0 = max(0.0, x0 - 0.35 * w - 0.03), max(0.0, y0 - 1.2 * h - 0.03)
    cx1, cy1 = min(1.0, x1 + 0.35 * w + 0.03), min(1.0, y1 + 1.2 * h + 0.03)
    crop = f"crop=iw*{cx1 - cx0:.4f}:ih*{cy1 - cy0:.4f}:iw*{cx0:.4f}:ih*{cy0:.4f}"
    W2 = 480
    H2 = max(40, int(round(W2 * (cy1 - cy0) / max(1e-3, cx1 - cx0) * 9 / 16)))
    H2 -= H2 % 2
    mid = min((inst["t0"] + inst["t1"]) / 2, inst["t0"] + 0.9) if at == "in" else max((inst["t0"] + inst["t1"]) / 2, inst["t1"] - 0.9)
    ref = None
    for _, f in frames(path, 0, W2, H2, max(0.0, mid), 0.1, crop=crop):
        ref = colour_masks(_hsv(f))[inst["colour"]]
        break
    if ref is None or ref.sum() < 8:
        return {}
    # the glyph rows only (the line itself, not other things of the same colour in the margin)
    ry0 = int((y0 - cy0) / (cy1 - cy0) * H2) - 2
    ry1 = int((y1 - cy0) / (cy1 - cy0) * H2) + 2
    band = np.zeros_like(ref)
    band[max(0, ry0):max(0, ry1)] = True
    ref = ref & band
    if ref.sum() < 8:
        return {}
    ys_r, xs_r = np.where(ref)
    rcx, rcy, rw = xs_r.mean(), ys_r.mean(), xs_r.max() - xs_r.min() + 1
    t = max(0.0, inst["t0"] - 0.5) if at == "in" else max(0.0, inst["t1"] - 0.7)
    rows = []
    for tt, f in frames(path, 0, W2, H2, t, 1.1, crop=crop):
        m = colour_masks(_hsv(f))[inst["colour"]]
        rec = float((m & ref).sum()) / float(ref.sum())
        ys, xs = np.where(m & cv2.dilate(band.astype(np.uint8), np.ones((15, 1), np.uint8)).astype(bool))
        geo = (xs.min(), xs.max(), xs.mean(), ys.mean(), len(xs)) if len(xs) > 6 else None
        rows.append((tt, rec, geo))
    if not rows:
        return {}
    dt = 1.0 / max(1.0, fps_native)
    rec = np.array([r[1] for r in rows])
    out: dict = {"fps": fps_native}
    if at == "in":
        full_i = next((i for i in range(len(rec)) if rec[i] >= 0.8), None)
        if full_i is None:
            return {}
        i0 = full_i
        while i0 > 0 and rec[i0 - 1] > 0.08:
            i0 -= 1
        # a moving line is not yet on its rest pixels: look further back for the same-size shape arriving
        j = i0
        while j > 0 and rows[j - 1][2] and rows[j - 1][2][4] > 0.3 * ref.sum() and rec[j - 1] <= 0.08                 and (full_i - j) < int(0.6 / dt):
            j -= 1
        moving = j < i0
        start = j if moving else i0
        out["frames"] = int(full_i - start + 1)
        out["seconds"] = round(out["frames"] * dt, 3)
        out["t"] = round(rows[start][0], 3)
        mids = [r for r in rows[start:full_i] if r[2]]
        if out["frames"] <= 2:
            out["kind"] = "cut"
        elif moving and mids:
            g = mids[0][2]
            dx, dy = (g[2] - rcx) / max(1.0, rw), (g[3] - rcy) / max(1.0, ry1 - ry0)
            out["kind"] = "slide"
            out["dir"] = ("from-right" if dx > 0 else "from-left") if abs(dx) >= abs(dy) else ("from-below" if dy > 0 else "from-above")
        elif mids:
            g = mids[len(mids) // 2][2]
            width = (g[1] - g[0] + 1) / rw
            left_same = abs(g[0] - xs_r.min()) < 0.08 * rw
            if left_same and width < 0.8:
                out["kind"] = "per-letter" if out["frames"] >= 4 else "wipe"
            elif width < 0.85:
                out["kind"] = "scale"
            else:
                out["kind"] = "fade"
        else:
            out["kind"] = "fade"
        # overshoot: the drawn width against the rest width just after landing
        ws = [(r[2][1] - r[2][0] + 1) / rw for r in rows[start:min(len(rows), full_i + 8)] if r[2]]
        out["overshoot"] = round(max(1.0, max(ws)) if ws else 1.0, 2)
    else:
        last = max((i for i in range(len(rec)) if rec[i] >= 0.8), default=None)
        if last is None:
            return {}
        gone = next((i for i in range(last + 1, len(rec)) if rec[i] < 0.08), None)
        if gone is None:
            return {}
        out["frames"] = int(gone - last)
        out["seconds"] = round(out["frames"] * dt, 3)
        out["t"] = round(rows[gone][0], 3)
        out["kind"] = "cut" if out["frames"] <= 2 else "fade"
        if out["frames"] > 2:
            g = rows[min(gone, last + 1 + (gone - last) // 2)][2]
            if g:
                dx, dy = (g[2] - rcx) / max(1.0, rw), (g[3] - rcy) / max(1.0, ry1 - ry0)
                if abs(dx) > 0.2 or abs(dy) > 0.4:
                    out["kind"] = "slide"
                elif (g[1] - g[0] + 1) / rw < 0.8:
                    out["kind"] = "scale"
    return out


# ------------------------------------------------------------------ faces (for marks and labels)
def faces(full: np.ndarray) -> List[dict]:
    try:
        from .. import reframe
        rgb = full[..., ::-1]
        found = reframe._yunet(rgb, 640, 0.6)
        return [{"x": f[0], "y": f[1], "w": f[2], "h": f[3], "score": f[4]} for f in found]
    except Exception:  # noqa: BLE001 - no model: marks are measured without the face relation
        return []


def mark_detail(path: str, mk: dict, dims: Tuple[int, int]) -> dict:
    """Full-res look of a mark (colour, stroke, size vs the nearest face) and how it arrives."""
    W, H = dims
    mid = (mk["t0"] + mk["t1"]) / 2
    full = frame_at(path, mid, W, H)
    out = {}
    if full is not None:
        out["_frame"] = cv2.resize(full, (640, 360), interpolation=cv2.INTER_AREA)
        x0, y0, x1, y1 = int(mk["x0"] * W), int(mk["y0"] * H), int(mk["x1"] * W), int(mk["y1"] * H)
        crop = full[y0:y1 + 1, x0:x1 + 1]
        m = colour_masks(_hsv(crop))[mk["colour"]] if crop.size else None
        if m is not None and m.any():
            hv = _hsv(crop)
            vals = hv[..., 2][m]
            lit = m & (hv[..., 2] >= np.percentile(vals, 60))      # the lit face, not an extruded dark side
            out["color"] = _hex(np.median(crop[lit if lit.any() else m].reshape(-1, 3), axis=0))
            dark_side = m & (hv[..., 2] < 0.75 * np.percentile(vals, 80))
            out["darkSide"] = round(float(dark_side.sum()) / float(m.sum()), 2)
            # an editor's mark is one flat, saturated colour; a red shirt or a logo in the footage is not
            lit_v = hv[..., 2][lit] if lit.any() else hv[..., 2][m]
            out["flat"] = bool(float(lit_v.std()) < 22 and float(np.median(hv[..., 1][m])) > 170)
            if mk["shape"] == "ring":
                d = cv2.distanceTransform(m.astype(np.uint8), cv2.DIST_L2, 3)
                out["strokeW"] = round(float(2 * d.max() / H), 4)
        out["size"] = round((y1 - y0) / H, 3)
        fs = faces(full)
        if fs:
            cx, cy = (mk["x0"] + mk["x1"]) / 2, (mk["y0"] + mk["y1"]) / 2
            f = min(fs, key=lambda f: (f["x"] + f["w"] / 2 - cx) ** 2 + (f["y"] + f["h"] / 2 - cy) ** 2)
            fcx, fcy = f["x"] + f["w"] / 2, f["y"] + f["h"] / 2
            out["face"] = {"dx": round((cx - fcx) / max(1e-3, f["h"]), 2), "dy": round((cy - fcy) / max(1e-3, f["h"]), 2),
                           "sizeVsFace": round(((mk["y1"] - mk["y0"])) / max(1e-3, f["h"]), 2),
                           "onFace": bool(abs(cx - fcx) < f["w"] and abs(cy - fcy) < f["h"])}
            if mk["shape"] == "triangle":
                out["face"]["above"] = bool(mk["y1"] <= f["y"] + 0.15 * f["h"])
    # arrival: a ring that draws on keeps growing its mask over ~0.3-1 s; a pop is full size at once
    seq = []
    for _, f in frames(path, 0, 320, 180, max(0.0, mk["t0"] - 0.3), 1.2):
        m = colour_masks(_hsv(f))[mk["colour"]]
        x0, y0, x1, y1 = int(mk["x0"] * 320), int(mk["y0"] * 180), int(mk["x1"] * 320) + 1, int(mk["y1"] * 180) + 1
        seq.append(float(m[y0:y1, x0:x1].sum()))
    if seq and max(seq) > 0:
        s = np.array(seq) / max(seq)
        on = np.where(s > 0.05)[0]
        if len(on):
            i0 = on[0]
            full_i = next((i for i in range(i0, len(s)) if s[i] >= 0.9), i0)
            nat = probe(path)["fps"]
            out["enterSeconds"] = round((full_i - i0 + 1) / nat, 3)
            out["enter"] = "draw" if mk["shape"] in ("ring", "box") and full_i - i0 >= 4 else (
                "cut" if full_i == i0 else "scale")
            out["overshoot"] = round(float(np.sqrt(s[i0:full_i + 6].max() / max(1e-6, s[min(len(s) - 1, full_i + 6)]))), 2)
    return out


# ------------------------------------------------------------------ audio
def _ebur128(path: str, seconds: float) -> Optional[float]:
    p = subprocess.run(["ffmpeg", "-nostdin", "-v", "info", "-t", f"{seconds:.1f}", "-i", path, "-vn", "-af",
                        "ebur128=framelog=quiet", "-f", "null", "-"], capture_output=True, text=True, timeout=900)
    txt = p.stderr or ""
    i = txt.rfind("I:")
    if i < 0:
        return None
    try:
        return float(txt[i + 2:].strip().split()[0])
    except (ValueError, IndexError):
        return None


def audio(path: str, seconds: float, cuts: List[float], element_starts: List[float]) -> dict:
    sr = 16000
    p = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-t", f"{seconds:.1f}", "-i", path, "-vn", "-ac", "1",
                        "-ar", str(sr), "-f", "f32le", "-"], capture_output=True, timeout=900)
    x = np.frombuffer(p.stdout, np.float32)
    if x.size < sr:
        return {"present": False}
    hop = sr // 20
    n = x.size // hop
    fr = x[: n * hop].reshape(n, hop)
    spec = np.abs(np.fft.rfft(fr * np.hanning(hop), axis=1)) ** 2
    freqs = np.fft.rfftfreq(hop, 1 / sr)
    tot = spec.sum(axis=1) + 1e-12
    speech = spec[:, (freqs >= 300) & (freqs <= 3400)].sum(axis=1)
    high = spec[:, (freqs >= 4000)].sum(axis=1) + 1e-12
    rms = np.sqrt((fr ** 2).mean(axis=1)) + 1e-9
    db = 20 * np.log10(rms)
    hdb = 10 * np.log10(high)
    alive = db > -80
    p95 = _q(db[alive], 95)
    voiced = alive & (db > p95 - 18) & (speech / tot > 0.55)
    voice = _q(db[voiced], 50) if voiced.any() else _q(db[alive], 60)
    floor = _q(db[alive], 5)
    # pauses: 250 ms+ runs under the voice by 12 dB - what plays there is the bed
    quiet = alive & (db < voice - 12)
    bed = _q(db[quiet], 50) if quiet.sum() > 20 else floor
    out = {"present": True, "lufs": _ebur128(path, seconds), "voiceDb": round(voice, 1), "floorDb": round(floor, 1),
           "bedDb": round(bed, 1), "musicUnderVoiceDb": round(voice - bed, 1),
           "music": "none" if bed < -58 else ("quiet" if voice - bed > 16 else "present"),
           "speechShare": round(float(voiced.mean()), 2)}
    # transient sound effects (whoosh, pop, hit): on a 20 ms grid the >5 kHz band jumps 10 dB over its level
    # 40-300 ms before AND sits in its loudest 15 %. Sibilants also do this, so every rate below is compared
    # with the same rate at random moments (the "excess" is the share an editor put there on purpose).
    hop2 = sr // 50
    n2 = x.size // hop2
    sp2 = np.abs(np.fft.rfft(x[: n2 * hop2].reshape(n2, hop2) * np.hanning(hop2), axis=1)) ** 2
    f2 = np.fft.rfftfreq(hop2, 1 / sr)
    hb = np.convolve(10 * np.log10(sp2[:, f2 >= 5000].sum(axis=1) + 1e-12), np.ones(3) / 3, "same")
    cs = np.concatenate([[0.0], np.cumsum(hb)])
    prev = np.array([(cs[max(1, i - 2)] - cs[max(0, i - 15)]) / max(1, max(1, i - 2) - max(0, i - 15)) for i in range(n2)])
    hit = np.where((hb - prev > 10) & (hb > np.percentile(hb, 85)))[0]
    on_t = []
    for i in hit:
        tt = i / 50.0
        if not on_t or tt - on_t[-1] > 0.3:
            on_t.append(tt)
    on_t = np.array(on_t)

    def rate_at(times, win=0.12):
        times = [t for t in times if t < seconds - 1]
        if not times or not on_t.size:
            return 0.0
        return float(np.mean([np.any(np.abs(on_t - t) <= win) for t in times]))
    rng = np.random.default_rng(7)
    random_t = rng.uniform(1, max(2, seconds - 1), 400)
    base_rate = rate_at(random_t)

    def excess(times):
        r = rate_at(times)
        return round(max(0.0, (r - base_rate) / max(1e-6, 1 - base_rate)), 2), round(r, 2)
    cut_ex, cut_raw = excess(cuts)
    el_ex, el_raw = excess(element_starts)
    lv = []
    for t in cuts:
        near = on_t[np.abs(on_t - t) <= 0.12] if on_t.size else []
        for o in near[:1]:
            i = int(o * 20)
            lv.append(db[i:i + 3].max() - voice)
    out["sfx"] = {"onsetsPerMin": round(len(on_t) / (seconds / 60), 1), "baseRate": round(base_rate, 2),
                  "onCutsShare": cut_ex, "onCutsRaw": cut_raw, "onElementsShare": el_ex, "onElementsRaw": el_raw,
                  "levelVsVoiceDb": round(float(np.median(lv)), 1) if lv else None}
    out["_onsets"] = [round(float(x), 2) for x in on_t]
    return out


def transcript(path: str, seconds: float, workdir: str) -> List[dict]:
    """Word times of the first `seconds` (local whisper, the worker's own model): which text is a spoken word."""
    wav = os.path.join(workdir, "speech.wav")
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-t", f"{seconds:.1f}", "-i", path, "-vn", "-ac", "1",
                        "-ar", "16000", wav], check=True, timeout=600)
        from .. import transcribe
        return [{"w": w.text, "s": round(w.start, 2), "e": round(w.end, 2)} for w in transcribe.transcribe_words(wav)]
    except Exception as e:  # noqa: BLE001 - no words: triggers are judged from timing alone
        print(f"[style-match] transcript skipped: {type(e).__name__}: {str(e)[:120]}", flush=True)
        return []


# ------------------------------------------------------------------ the whole analysis
def analyse(path: str, workdir: str, detail_seconds: float = 360.0, max_seconds: float = 1800.0,
            log=print, words: bool = True) -> dict:
    if cv2 is None:
        raise RuntimeError("opencv is not installed")
    os.makedirs(workdir, exist_ok=True)
    pr = probe(path)
    dur = min(pr["duration"], max_seconds)
    detail = min(dur, detail_seconds)
    log(f"[style-match] {os.path.basename(path)}: {pr['width']}x{pr['height']} {pr['fps']} fps, {pr['duration']:.0f} s")
    p1 = pass1(path, dur, detail)
    cuts = detect_cuts(p1)
    pace = pacing(cuts["cuts"], dur)
    cam = camera(p1, [c for c in cuts["cuts"] if c < detail])
    gr = grade(p1["thumbs"])
    log(f"[style-match] pass 1: {len(cuts['cuts'])} cuts, {len(cuts['transitions'])} other transitions")
    p2 = pass2(path, detail)
    groups = cluster_texts(p2["texts"])
    log(f"[style-match] pass 2: {len(p2['texts'])} text appearances in {len(groups)} types, {len(p2['marks'])} marks")
    W, H = pr["width"], pr["height"]
    fulls = []
    # editorial looks first (outlined or boxed, a sane size), then the rest by time on screen
    groups.sort(key=lambda g: -(g["seconds"] * (3.0 if (g["outlined"] or g["boxed"]) else 1.0)
                                * (0.4 if np.median([i["h"] for i in g["instances"]]) > 0.12 else 1.0)))
    for g in groups[:14]:
        insts = g["instances"]
        # a spread of examples, longest first within each third of the list
        pick = sorted(insts, key=lambda i: -(i["t1"] - i["t0"]))[:3] + insts[:: max(1, len(insts) // 3)][:3]
        seen, chosen = set(), []
        for i in pick:
            if id(i) not in seen:
                seen.add(id(i))
                chosen.append(i)
        g["samples"] = []
        for inst in chosen[:4]:
            t = (inst["t0"] + inst["t1"]) / 2
            full = frame_at(path, t, W, H)
            if full is None:
                continue
            if len(fulls) < 12:
                fulls.append(full)
            mi = measure_instance(full, inst)
            if not mi:
                continue
            mi["t"] = round(t, 2)
            mi["inst"] = inst
            mi["_frame"] = cv2.resize(full, (640, 360), interpolation=cv2.INTER_AREA)
            fs = faces(full)
            if fs:
                cx, cy = (inst["x0"] + inst["x1"]) / 2, (inst["y0"] + inst["y1"]) / 2
                f = min(fs, key=lambda f: (f["x"] + f["w"] / 2 - cx) ** 2 + (f["y"] + f["h"] / 2 - cy) ** 2)
                mi["face"] = {"dx": round((cx - f["x"] - f["w"] / 2) / max(1e-3, f["h"]), 2),
                              "dy": round((cy - f["y"] - f["h"] / 2) / max(1e-3, f["h"]), 2), "h": round(f["h"], 3)}
            mi["in"] = motion(path, inst, pr["fps"], "in")
            mi["out"] = motion(path, inst, pr["fps"], "out")
            g["samples"].append(mi)
    marks = []
    for mk in sorted(p2["marks"], key=lambda m: -(m["t1"] - m["t0"]))[:12]:
        md = mark_detail(path, mk, (W, H))
        marks.append(dict(mk, **md))
    elem_starts = [i["t0"] for g in groups for i in g["instances"]]
    au = audio(path, dur, cuts["cuts"], elem_starts) if pr["audio"] else {"present": False}
    if pr["audio"] and dur > detail + 30:
        # the opening minutes on their own: effects are often denser there (the kit takes the stronger rate)
        try:
            ad = audio(path, detail, [c for c in cuts["cuts"] if c < detail], elem_starts)
            au["sfxOpening"] = ad.get("sfx")
        except Exception:  # noqa: BLE001
            pass
    log(f"[style-match] audio: {json.dumps({k: au.get(k) for k in ('lufs', 'voiceDb', 'musicUnderVoiceDb', 'music')})}")
    tx = transcript(path, detail, workdir) if (words and pr["audio"]) else []
    log(f"[style-match] transcript: {len(tx)} words")
    return {"probe": pr, "duration": dur, "detailSeconds": detail, "words": tx, "cuts": cuts, "pacing": pace, "camera": cam,
            "grade": dict(gr, grain=grain(fulls[:6])), "groups": groups, "marks": marks, "layouts": p2["layouts"],
            "audio": au, "_thumbs": p1["thumbs"]}
