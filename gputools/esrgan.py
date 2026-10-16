"""
"Enhance to 4K" in the cloud (ThumbGenius Studio's Fast cloud mode): Real-ESRGAN realesr-general-x4v3 (BSD-3,
xinntao/Real-ESRGAN), the SAME model and clean-up mix as Studio's local WebGPU mode, so both look alike:
weights = dn * realesr-general-x4v3 + (1 - dn) * realesr-general-wdn-x4v3 (light 0.25 / medium 0.5 / strong 1.0),
the official script's denoise-strength mix. A plain 4x upscaler that also removes blocks and noise; NOT a face
generator (no GFPGAN / CodeFormer): faces are sharpened, never redrawn.

How a clip goes through (all frame work on the GPU):
  ffmpeg decode (its own size, RGB) -> batches of frames, fp16, whole frames (no tiles, no seams) -> SRVGGNetCompact
  4x -> steadiness (Studio's rule: a 192 px source tile whose mean change from the last frame is under 1.2 levels
  keeps 40% of its last output, so still areas do not shimmer) -> resized to the target (2160 / 1440 lines,
  bicubic) -> BT.709 limited-range YUV 4:2:0 on the GPU -> NVENC H.264 / H.265 at a fixed high bitrate, with the
  section's sound.
Decoding, the GPU and encoding overlap (a reader thread and a writer thread).
"""
from __future__ import annotations

import os
import queue
import threading
import time
from typing import Callable, Dict, Optional

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

import media
import plan

WEIGHTS_DIR = os.environ.get("ESRGAN_DIR", "/models/realesrgan")
BATCH = int(os.environ.get("ESRGAN_BATCH", "4"))


class SRVGGNetCompact(nn.Module):
    """Real-ESRGAN's compact net (realesrgan/archs/srvgg_arch.py, BSD-3): conv + PReLU x (num_conv + 1), a last
    conv to 3 * 16 channels, pixel shuffle, plus the nearest-upsampled input."""

    def __init__(self, num_feat: int = 64, num_conv: int = 32, upscale: int = 4):
        super().__init__()
        self.upscale = upscale
        body = [nn.Conv2d(3, num_feat, 3, 1, 1), nn.PReLU(num_parameters=num_feat)]
        for _ in range(num_conv):
            body += [nn.Conv2d(num_feat, num_feat, 3, 1, 1), nn.PReLU(num_parameters=num_feat)]
        body.append(nn.Conv2d(num_feat, 3 * upscale * upscale, 3, 1, 1))
        self.body = nn.ModuleList(body)
        self.upsampler = nn.PixelShuffle(upscale)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = x
        for layer in self.body:
            out = layer(out)
        return self.upsampler(out) + F.interpolate(x, scale_factor=self.upscale, mode="nearest")


def _state(path: str) -> Dict[str, torch.Tensor]:
    sd = torch.load(path, map_location="cpu", weights_only=True)     # a plain state dict: no code can run
    if isinstance(sd, dict):
        for k in ("params_ema", "params"):
            if k in sd and isinstance(sd[k], dict):
                return sd[k]
    return sd


def mixed_state(dn: float, weights_dir: str = WEIGHTS_DIR) -> Dict[str, torch.Tensor]:
    """dn * x4v3 + (1 - dn) * wdn-x4v3 (dn 1.0 = x4v3 alone)."""
    a = _state(os.path.join(weights_dir, "realesr-general-x4v3.pth"))
    if dn >= 0.999:
        return {k: v.float() for k, v in a.items()}
    b = _state(os.path.join(weights_dir, "realesr-general-wdn-x4v3.pth"))
    return {k: dn * a[k].float() + (1.0 - dn) * b[k].float() for k in a}


def build(dn: float, device: str = "cpu", half: bool = False, weights_dir: str = WEIGHTS_DIR) -> SRVGGNetCompact:
    net = SRVGGNetCompact()
    net.load_state_dict(mixed_state(dn, weights_dir), strict=True)
    net.eval().requires_grad_(False)
    net = net.to(device)
    if half:
        net = net.half()
    return net.to(memory_format=torch.channels_last)


# ------------------------------------------------------------------ GPU picture helpers
def steady_mask(cur: torch.Tensor, prev: torch.Tensor, tile: int = plan.STEADY_TILE,
                levels: float = plan.STEADY_LEVELS) -> torch.Tensor:
    """(N, 1, h, w) 0/1 float at source size: 1 where the frame's tile did not change from `prev` (both N x 3 x h x w
    in 0..1). Tiles are laid from the top-left like Studio's (the last row / column may be smaller)."""
    d = (cur.float() - prev.float()).abs().mean(dim=1, keepdim=True)
    h, w = d.shape[-2:]
    th, tw = -(-h // tile), -(-w // tile)
    d = F.pad(d, (0, tw * tile - w, 0, th * tile - h))
    s = F.avg_pool2d(d, tile)                                         # mean over the padded tile
    area = F.avg_pool2d(F.pad(torch.ones_like(d[:, :, :h, :w]), (0, tw * tile - w, 0, th * tile - h)), tile)
    still = ((s / area.clamp_min(1e-6)) * 255.0 < levels).float()
    return F.interpolate(still, scale_factor=tile, mode="nearest")[..., :h, :w]


def rgb_to_yuv420(x: torch.Tensor) -> torch.Tensor:
    """3 x H x W RGB (0..1, H and W even) -> the planar YUV 4:2:0 bytes of one frame, BT.709 limited range, as a
    flat uint8 tensor (Y, then U, then V)."""
    r, g, b = x[0], x[1], x[2]
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    u = (b - y) / 1.8556
    v = (r - y) / 1.5748
    Y = (16.0 + 219.0 * y).round().clamp(0, 255).to(torch.uint8)
    uv = F.avg_pool2d(torch.stack([u, v])[:, None], 2)[:, 0]          # 2x2 average (centred chroma, like swscale)
    UV = (128.0 + 224.0 * uv).round().clamp(0, 255).to(torch.uint8)
    return torch.cat([Y.reshape(-1), UV[0].reshape(-1), UV[1].reshape(-1)])


class RealESRGAN:
    def __init__(self, device: str = "cuda", weights_dir: str = WEIGHTS_DIR):
        t0 = time.time()
        self.device, self.weights_dir = device, weights_dir
        self.nets: Dict[float, SRVGGNetCompact] = {}
        torch.backends.cudnn.benchmark = True                    # one frame size per job: pick the fastest kernels
        self.net(plan.ESRGAN_STRENGTH["light"])
        self.load_seconds = round(time.time() - t0, 1)

    def net(self, dn: float) -> SRVGGNetCompact:
        if dn not in self.nets:
            self.nets[dn] = build(dn, self.device, half=str(self.device).startswith("cuda"),
                                  weights_dir=self.weights_dir)
        return self.nets[dn]

    @torch.inference_mode()
    def upscale(self, src: str, out: str, lines: int = 2160, start: float = 0.0, seconds: float = 0.0,
                strength: str = "light", steady: bool = True, codec: str = "h264", bitrate_mbps: float = 45.0,
                info: Optional[Dict] = None, progress: Optional[Callable[[float, str], None]] = None) -> Dict:
        t0 = time.time()
        info = info or media.probe(src)
        w, h, fps = int(info["w"]), int(info["h"]), float(info["fps"] or 30.0)
        avail = max(0.0, float(info.get("seconds") or 0.0) - start)
        span = min(seconds, avail) if seconds > 0 else avail
        est_frames = int(round(span * fps)) if span > 0 else int(info.get("frames") or 0)
        W, H = plan.esrgan_plan(w, h, fps, est_frames, lines)
        net = self.net(plan.ESRGAN_STRENGTH.get(strength, 0.25))
        dtype = next(net.parameters()).dtype
        enc = media.YuvEncoder(out, W, H, fps, bitrate_mbps=bitrate_mbps, codec=codec,
                               audio_from=src if info.get("audio") else "", audio_start=start,
                               audio_seconds=seconds, video_seconds=(est_frames / fps) if est_frames else 0.0)
        # reader: decoded frames, a few batches ahead
        frames_q: "queue.Queue" = queue.Queue(maxsize=BATCH * 3)
        stop = threading.Event()

        def read():
            try:
                for fr in media.decode(src, info, start=start, seconds=seconds):
                    if stop.is_set():
                        break
                    frames_q.put(fr)
            except Exception as e:  # noqa: BLE001 - handed to the GPU loop
                frames_q.put(e)
            frames_q.put(None)

        # writer: YUV bytes to ffmpeg, so the GPU does not wait on the pipe
        out_q: "queue.Queue" = queue.Queue(maxsize=6)
        werr: Dict = {}

        def write():
            while True:
                item = out_q.get()
                if item is None:
                    return
                if werr:
                    continue
                try:
                    enc.write(item)
                except Exception as e:  # noqa: BLE001
                    werr["e"] = e

        rt = threading.Thread(target=read, name="esr-read", daemon=True)
        wt = threading.Thread(target=write, name="esr-write", daemon=True)
        rt.start()
        wt.start()
        prev_in = prev_out = None
        n = 0
        t_gpu = 0.0
        still_share = []
        last_report = 0.0
        try:
            done = False
            while not done:
                batch = []
                while len(batch) < BATCH:
                    item = frames_q.get()
                    if item is None:
                        done = True
                        break
                    if isinstance(item, Exception):
                        raise item
                    batch.append(item)
                if not batch:
                    break
                if n + len(batch) > plan.ESRGAN_MAX_FRAMES:
                    raise plan.InputError(f"the section has more than {plan.ESRGAN_MAX_FRAMES} frames")
                g0 = time.time()
                x = torch.from_numpy(np.stack(batch)).to(self.device, non_blocking=True)
                x = x.permute(0, 3, 1, 2).to(dtype).div_(255.0).contiguous(memory_format=torch.channels_last)
                y = net(x).float().clamp_(0, 1)                     # N x 3 x 4h x 4w
                for k in range(y.shape[0]):
                    yk, xk = y[k:k + 1], x[k:k + 1]
                    if steady and prev_in is not None:
                        m = steady_mask(xk, prev_in)
                        share = float(m.mean())
                        still_share.append(share)
                        if share > 0:
                            m4 = F.interpolate(m, scale_factor=4, mode="nearest")
                            yk = yk + (prev_out - yk) * (m4 * plan.STEADY_KEEP)
                    prev_in, prev_out = xk, yk
                    big = F.interpolate(yk, size=(H, W), mode="bicubic", align_corners=False,
                                        antialias=(H < yk.shape[-2])).clamp_(0, 1)[0]
                    out_q.put(rgb_to_yuv420(big).cpu().numpy().tobytes())
                    n += 1
                    if werr:
                        raise RuntimeError(f"encode: {werr['e']}")
                t_gpu += time.time() - g0
                if progress and time.time() - last_report > 2.0 and est_frames:
                    last_report = time.time()
                    progress(min(0.99, n / float(est_frames)), f"Enhancing frame {n} of {est_frames}")
            out_q.put(None)
            wt.join()
            if werr:
                raise RuntimeError(f"encode: {werr['e']}")
            if n < 2:
                raise plan.InputError("the section has fewer than 2 frames")
            t_enc = time.time()
            enc.close()
            t_close = time.time() - t_enc
        except BaseException:
            stop.set()
            enc.abort()                                              # ffmpeg gone: a blocked write fails now
            while wt.is_alive():
                try:
                    out_q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    out_q.put_nowait(None)
                except queue.Full:
                    pass
                wt.join(0.1)
            raise
        finally:
            stop.set()
            while rt.is_alive():                                     # unblock the reader
                try:
                    frames_q.get_nowait()
                except queue.Empty:
                    rt.join(0.1)
        peak = torch.cuda.max_memory_allocated() / 2 ** 30 if torch.cuda.is_available() else 0.0
        return {"frames": n, "fps": round(fps, 3), "source": plan.summary_size(w, h), "size": plan.summary_size(W, H),
                "width": W, "height": H, "seconds": round(n / fps, 3), "strength": strength, "steady": bool(steady),
                "still_share": round(float(np.mean(still_share)), 3) if still_share else 0.0,
                "codec": enc.codec, "bitrate_mbps": float(bitrate_mbps), "peak_vram_gb": round(peak, 2),
                "timings": {"gpu": round(t_gpu, 2), "finish_encode": round(t_close, 2),
                            "total": round(time.time() - t0, 2), "fps_overall": round(n / max(0.01, time.time() - t0), 1)}}


def encode_frames(frames, fps: float, W: int, H: int, out: str, device: str = "cuda", bitrate_mbps: float = 45.0,
                  codec: str = "h264", audio_from: str = "", audio_start: float = 0.0, audio_seconds: float = 0.0) -> Dict:
    """RGB uint8 frames (any size) -> `out` at W x H (bicubic on the GPU) through the same YUV / fixed-bitrate path:
    FlashVSR's 1080-line frames become a 2160 / 1440-line Studio file."""
    enc = media.YuvEncoder(out, W, H, fps, bitrate_mbps=bitrate_mbps, codec=codec, audio_from=audio_from,
                           audio_start=audio_start, audio_seconds=audio_seconds, video_seconds=len(frames) / fps)
    try:
        with torch.inference_mode():
            for fr in frames:
                t = torch.from_numpy(fr).to(device).permute(2, 0, 1)[None].float().div_(255.0)
                if t.shape[-2:] != (H, W):
                    t = F.interpolate(t, size=(H, W), mode="bicubic", align_corners=False,
                                      antialias=(H < t.shape[-2])).clamp_(0, 1)
                enc.write(rgb_to_yuv420(t[0]).cpu().numpy().tobytes())
        enc.close()
    except BaseException:
        enc.abort()
        raise
    return {"codec": enc.codec, "frames": len(frames)}
