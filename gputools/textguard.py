"""
Text guard for the HD boost. FlashVSR paints plausible detail, and on small lettering burned into a clip that
detail is wrong: the 2026-10-09 test turned "USGS Station No: 08386505 ... 13:20:22" into unreadable strokes and
"13" into "19" (gpu_tools_test/notes.md). So lettering is found in the low-resolution source and, inside it, the
result shows the faithful picture instead (the source upsampled and lightly sharpened - the CPU path's look);
everywhere else it keeps FlashVSR's detail.

The finder is PaddleOCR's PP-OCRv4 text detector (DBNet; Apache-2.0, the 4.7 MB ONNX that RapidOCR ships),
run on onnxruntime's CPU provider on a frame every ~0.4 s; each frame takes the mask of its nearest sampled
frame (captions, timestamps, timecode windows, lower thirds and tickers; a cut changes the mask with the
picture). Its probability map is thresholded at 0.3 (RapidOCR's own), grown to cover whole glyphs and feathered.
A false hit (a roof line, a fence) only gives that patch the softer faithful look - the safe way to be wrong.
"""
from __future__ import annotations

import os
import time
from typing import Dict, List, Optional, Sequence

import numpy as np

DET_MODEL = os.environ.get("TEXT_DET_MODEL", "/models/ppocr/ch_PP-OCRv4_det_infer.onnx")
DET_SHORT = 736          # RapidOCR's limit_side_len with limit_type "min": the short side scaled up to this
THRESH = 0.3             # RapidOCR's det thresh
GROW = 9                 # px at the detector's scale: the map marks shrunk text kernels (DB), glyphs reach further
EVERY_SECONDS = 0.4      # one detection per this much of the clip
_SESS: Dict[str, object] = {}


def _session():
    if "s" not in _SESS:
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, int(os.environ.get("TEXT_DET_THREADS", "4")))
        _SESS["s"] = ort.InferenceSession(DET_MODEL, opts, providers=["CPUExecutionProvider"])
        _SESS["in"] = _SESS["s"].get_inputs()[0].name
    return _SESS["s"], _SESS["in"]


def available() -> bool:
    return os.path.isfile(DET_MODEL)


def _resize_nearest(a: np.ndarray, h: int, w: int) -> np.ndarray:
    ys = np.minimum((np.arange(h) * a.shape[0] / float(h)).astype(int), a.shape[0] - 1)
    xs = np.minimum((np.arange(w) * a.shape[1] / float(w)).astype(int), a.shape[1] - 1)
    return a[ys][:, xs]


def text_map(rgb: np.ndarray) -> np.ndarray:
    """The detector's text probability map of one RGB uint8 frame, at the detector's own scale (float32 0-1)."""
    h, w = rgb.shape[:2]
    s = DET_SHORT / float(min(h, w))
    nh, nw = max(32, int(round(h * s / 32.0)) * 32), max(32, int(round(w * s / 32.0)) * 32)
    img = _resize_nearest(rgb, nh, nw)[..., ::-1].astype(np.float32) / 255.0      # BGR, as PaddleOCR reads (cv2)
    x = ((img - 0.5) / 0.5).transpose(2, 0, 1)[None]
    sess, name = _session()
    return sess.run(None, {name: np.ascontiguousarray(x)})[0][0, 0]


def _grow(b: np.ndarray, r: int) -> np.ndarray:
    """Binary dilation by a (2r+1) square (separable max over shifts)."""
    if r <= 0 or not b.any():
        return b
    out = b.copy()
    for d in range(1, r + 1):
        out[:, d:] |= b[:, :-d]
        out[:, :-d] |= b[:, d:]
    b2 = out.copy()
    for d in range(1, r + 1):
        out[d:, :] |= b2[:-d, :]
        out[:-d, :] |= b2[d:, :]
    return out


def _feather(m: np.ndarray, r: int) -> np.ndarray:
    """Box blur twice (separable, edge-clamped): a soft edge of about 2r px."""
    if r <= 0 or not m.any():
        return m
    k = 2 * r + 1
    for _ in range(2):
        p = np.pad(m, ((0, 0), (r, r)), mode="edge")
        c = np.cumsum(np.pad(p, ((0, 0), (1, 0))), axis=1)
        m = (c[:, k:] - c[:, :-k]) / k
        p = np.pad(m, ((r, r), (0, 0)), mode="edge")
        c = np.cumsum(np.pad(p, ((1, 0), (0, 0))), axis=0)
        m = (c[k:, :] - c[:-k, :]) / k
    return m.astype(np.float32)


class Guard:
    """The text masks of one clip: built from its source frames, read per output frame at the output size."""

    def __init__(self, frames: Sequence[np.ndarray], fps: float, out_hw, feather: int = 6):
        t0 = time.time()
        self.n = len(frames)
        self.out_hw = (int(out_hw[0]), int(out_hw[1]))
        step = max(1, int(round(EVERY_SECONDS * max(1.0, float(fps)))))
        self.samples: List[int] = list(range(0, self.n, step)) or [0]
        if self.samples[-1] != self.n - 1 and self.n > 1:
            self.samples.append(self.n - 1)
        self._masks: List[Optional[np.ndarray]] = []
        cover = []
        for i in self.samples:
            b = _grow(text_map(np.asarray(frames[i])) > THRESH, GROW)
            cover.append(float(b.mean()))
            if not b.any():
                self._masks.append(None)
                continue
            self._masks.append(_feather(_resize_nearest(b.astype(np.float32), *self.out_hw), feather))
        self.share = round(float(np.mean(cover)) if cover else 0.0, 4)
        self.seconds = round(time.time() - t0, 2)

    def any(self) -> bool:
        return any(m is not None for m in self._masks)

    def mask(self, k: int) -> Optional[np.ndarray]:
        """The out_h x out_w mask (0-1) for frame k: its nearest sampled frame's (None = no text there)."""
        j = int(np.argmin([abs(k - s) for s in self.samples]))
        return self._masks[j]


def blend(sharp: np.ndarray, safe: np.ndarray, m: Optional[np.ndarray]) -> np.ndarray:
    """sharp outside the mask, safe inside it (uint8 RGB frames of the same size)."""
    if m is None:
        return sharp
    mm = m[..., None]
    out = sharp.astype(np.float32) * (1.0 - mm) + safe.astype(np.float32) * mm
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)
