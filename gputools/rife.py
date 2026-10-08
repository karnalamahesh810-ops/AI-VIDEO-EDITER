"""
Real 60 fps: a clip retimed to the render's frame rate with RIFE 4.25 (MIT) - every output frame that falls
between two source frames is made by the flow network at that exact point in time (24 -> 60 has no 2-3 judder,
30 -> 60 no doubled frames). A cut inside the clip (Practical-RIFE's test: SSIM of 32x32 thumbnails under 0.2)
holds the nearest source frame instead of blending two shots.
"""
from __future__ import annotations

import os
import time
from typing import Dict, Optional

import numpy as np
import torch
import torch.nn.functional as F

import media
import plan

MODEL_PATH = os.environ.get("RIFE_MODEL", "/models/rife-4.25/flownet.pkl")


def _ssim32(a: torch.Tensor, b: torch.Tensor) -> float:
    """SSIM of two frames' 32x32 thumbnails (a simple global-window SSIM on luma; cut detection only)."""
    def small(x):
        y = F.interpolate(x.float(), (32, 32), mode="bilinear", align_corners=False)
        return (0.299 * y[:, 0] + 0.587 * y[:, 1] + 0.114 * y[:, 2]).flatten()
    x, y = small(a), small(b)
    c1, c2 = 0.01 ** 2, 0.03 ** 2
    mx, my = x.mean(), y.mean()
    vx, vy = x.var(unbiased=False), y.var(unbiased=False)
    cov = ((x - mx) * (y - my)).mean()
    return float(((2 * mx * my + c1) * (2 * cov + c2)) / ((mx * mx + my * my + c1) * (vx + vy + c2)))


class Rife:
    def __init__(self, model_path: str = MODEL_PATH, device: str = "cuda", half: bool = True):
        import rife_net
        t0 = time.time()
        self.device = device
        self.half = half and device == "cuda"
        self.net = rife_net.load(model_path, device)
        if self.half:
            self.net = self.net.half()
        self.load_seconds = round(time.time() - t0, 1)

    def _tensor(self, rgb: np.ndarray, ph: int, pw: int) -> torch.Tensor:
        t = torch.from_numpy(rgb).to(self.device, non_blocking=True).permute(2, 0, 1).unsqueeze(0)
        t = t.half() if self.half else t.float()
        t = t / 255.0
        h, w = rgb.shape[:2]
        if ph != h or pw != w:
            t = F.pad(t, (0, pw - w, 0, ph - h), mode="replicate")
        return t

    @staticmethod
    def _rgb(t: torch.Tensor, h: int, w: int) -> np.ndarray:
        return (t[0, :, :h, :w].clamp(0, 1) * 255.0 + 0.5).byte().permute(1, 2, 0).contiguous().cpu().numpy()

    @torch.inference_mode()
    def retime(self, src: str, out: str, fps_out: float = 60.0, start: float = 0.0, seconds: float = 0.0,
               scene: float = plan.SCENE_SSIM, crf: int = 17, info: Optional[Dict] = None,
               frames=None) -> Dict:
        """`src` (or already-decoded `frames` with `info`) retimed to fps_out -> `out` (H.264, the source's sound).
        Returns the counts and timings."""
        t0 = time.time()
        info = info or media.probe(src)
        w, h, fps_in = int(info["w"]), int(info["h"]), float(info["fps"] or 30.0)
        if frames is None:
            frames = list(media.decode(src, info, start=start, seconds=seconds))
        n_in = len(frames)
        if n_in < 2:
            raise plan.InputError("the clip has fewer than 2 frames")
        sched = plan.retime(n_in, fps_in, fps_out)
        t_dec = time.time() - t0
        scale = 0.5 if min(w, h) > 1200 else 1.0          # Practical-RIFE: scale 0.5 for 4K
        mult = 64 if scale == 1.0 else 128
        ph, pw = plan.padded(h, mult), plan.padded(w, mult)
        enc = media.Encoder(out, w, h, fps_out, crf=crf, preset=media.PRESET,
                            audio_from=src if info.get("audio") and src else "", audio_start=start,
                            audio_seconds=seconds, video_seconds=len(sched) / fps_out)
        cache: Dict[int, torch.Tensor] = {}
        feats: Dict[int, torch.Tensor] = {}
        cuts: Dict[int, bool] = {}
        made = held = 0
        t1 = time.time()
        try:
            for i, t in sched:
                if t == 0.0:
                    enc.write(frames[i])
                    continue
                for j in (i, i + 1):
                    if j not in cache:
                        cache[j] = self._tensor(frames[j], ph, pw)
                for j in list(cache):
                    if j < i:
                        del cache[j]
                        feats.pop(j, None)
                if i not in cuts:
                    cuts[i] = _ssim32(cache[i], cache[i + 1]) < scene
                if cuts[i]:
                    enc.write(frames[i] if t < 0.5 else frames[i + 1])
                    held += 1
                    continue
                for j in (i, i + 1):
                    if j not in feats:
                        feats[j] = self.net.encode(cache[j][:, :3])
                mid = self.net(cache[i], cache[i + 1], timestep=float(t), scale=scale, f0=feats[i], f1=feats[i + 1])
                enc.write(self._rgb(mid, h, w))
                made += 1
            torch.cuda.synchronize()
            t_gpu = time.time() - t1
            enc.close()
        except BaseException:
            enc.abort()
            raise
        return {"frames_in": n_in, "frames_out": len(sched), "interpolated": made, "held_at_cuts": held,
                "cuts": sum(1 for v in cuts.values() if v), "fps_in": round(fps_in, 3), "fps_out": fps_out,
                "width": w, "height": h, "seconds": round(len(sched) / fps_out, 3),
                "timings": {"decode": round(t_dec, 2), "interpolate_and_encode": round(t_gpu, 2),
                            "total": round(time.time() - t0, 2)}}
