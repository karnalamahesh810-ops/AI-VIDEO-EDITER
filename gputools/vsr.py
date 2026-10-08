"""
HD boost for low-resolution clips: FlashVSR v1.1 (Apache-2.0; OpenImagingLab/FlashVSR, one-step diffusion video
super-resolution on Wan2.1-1.3B with locality-constrained block-sparse attention and the tiny conditional
decoder). The used section of a clip under 720 lines comes back at 1080 lines (its short side), every frame, the
same length, its colours and its sound.

How a clip goes through: decoded at its own size -> upsampled on the GPU (bicubic) straight to the target size
-> padded up to multiples of 128 (the model's attention windows; the padding is cropped off again) -> the clip's
last frame repeated so the pipeline (8n+1 frames in, 8n-3 out) returns every frame -> FlashVSR tiny ->
the text guard (textguard.py: lettering burned into the clip keeps the faithful upsampled picture, FlashVSR
invents wrong strokes on small text) -> H.264 (NVENC, else x264), BT.709.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from typing import Dict, Optional

import numpy as np
import torch
import torch.nn.functional as F

import media
import plan
import textguard

CODE_DIR = os.environ.get("FLASHVSR_DIR", "/opt/FlashVSR")
MODELS_DIR = os.environ.get("FLASHVSR_MODELS", "/models/FlashVSR-v1.1")
# "tiny" (default) = the all-on-GPU pipeline: an 8 s 16:9 clip peaked at 30 GB on the A40 - a 48 GB card.
# "long" = FlashVSR's tiny-long pipeline: the same model and decoder (PSNR 38-48 dB against "tiny"), but the clip
# stays in CPU memory and each 8-frame step is decoded and colour-fixed as it is made: 20.6 GB peak, it ran under
# a 22 GB cap with PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True - a 24 GB card - ~30% slower.
PIPELINE = os.environ.get("FLASHVSR_PIPELINE", "tiny").strip().lower()


class FlashVSR:
    def __init__(self, models_dir: str = MODELS_DIR, code_dir: str = CODE_DIR, device: str = "cuda",
                 pipeline: str = PIPELINE):
        t0 = time.time()
        for p in (code_dir, os.path.join(code_dir, "examples", "WanVSR")):
            if p not in sys.path:
                sys.path.insert(0, p)
        from diffsynth import FlashVSRTinyLongPipeline, FlashVSRTinyPipeline, ModelManager
        from utils.TCDecoder import build_tcdecoder
        from utils.utils import Causal_LQ4x_Proj

        self.device = device
        self.long = pipeline != "tiny"
        mm = ModelManager(torch_dtype=torch.bfloat16, device="cpu")
        mm.load_models([os.path.join(models_dir, "diffusion_pytorch_model_streaming_dmd.safetensors")])
        cls = FlashVSRTinyLongPipeline if self.long else FlashVSRTinyPipeline
        pipe = cls.from_model_manager(mm, device=device)
        proj = Causal_LQ4x_Proj(in_dim=3, out_dim=1536, layer_num=1).to(device, dtype=torch.bfloat16)
        proj.load_state_dict(torch.load(os.path.join(models_dir, "LQ_proj_in.ckpt"), map_location="cpu",
                                        weights_only=True), strict=True)
        pipe.denoising_model().LQ_proj_in = proj.to(device)
        pipe.TCDecoder = build_tcdecoder(new_channels=[512, 256, 128, 128], new_latent_channels=16 + 768)
        missing = pipe.TCDecoder.load_state_dict(torch.load(os.path.join(models_dir, "TCDecoder.ckpt"),
                                                            map_location="cpu", weights_only=True), strict=False)
        if getattr(missing, "missing_keys", None):
            raise RuntimeError(f"TCDecoder weights miss {len(missing.missing_keys)} tensors")
        pipe.to(device)
        pipe.enable_vram_management(num_persistent_param_in_dit=None)
        ctx = torch.load(os.path.join(code_dir, "examples", "WanVSR", "prompt_tensor", "posi_prompt.pth"),
                         map_location="cpu", weights_only=True)
        pipe.init_cross_kv(context_tensor=ctx)
        pipe.load_models_to_device(["dit", "vae"])
        self.pipe = pipe
        self.load_seconds = round(time.time() - t0, 1)

    def _lq(self, frames, n_feed: int, H: int, W: int, PH: int, PW: int) -> torch.Tensor:
        """(1, 3, n_feed, PH, PW) bf16 in [-1, 1]: each frame upsampled to H x W on the GPU, padded to PH x PW;
        kept in (pinned) CPU memory for the long pipeline, on the GPU for the tiny one."""
        n = len(frames)
        if self.long:
            lq = torch.empty((1, 3, n_feed, PH, PW), dtype=torch.bfloat16, pin_memory=True)
        else:
            lq = torch.empty((1, 3, n_feed, PH, PW), dtype=torch.bfloat16, device=self.device)
        for k in range(n_feed):
            t = torch.from_numpy(frames[min(k, n - 1)]).to(self.device).permute(2, 0, 1).unsqueeze(0).float()
            t = F.interpolate(t / 255.0, size=(H, W), mode="bicubic", align_corners=False).clamp_(0, 1)
            if PH != H or PW != W:
                t = F.pad(t, (0, PW - W, 0, PH - H), mode="replicate")
            lq[0, :, k] = (t[0] * 2.0 - 1.0).to(torch.bfloat16)
        return lq

    @torch.inference_mode()
    def upscale(self, src: str, out: str, lines: int = 1080, start: float = 0.0, seconds: float = 0.0,
                sparse: float = 2.0, local_range: int = 11, seed: int = 0, info: Optional[Dict] = None,
                keep_frames: bool = False, crf: int = 17, text_guard: bool = True) -> Dict:
        """`src` -> `out` at `lines` (the short side). With keep_frames, the upscaled frames (RGB uint8) are also
        returned under "frames" (for a retime in the same job)."""
        t0 = time.time()
        info = info or media.probe(src)
        w, h = int(info["w"]), int(info["h"])
        frames = list(media.decode(src, info, start=start, seconds=seconds))
        n = len(frames)
        if n < 2:
            raise plan.InputError("the clip has fewer than 2 frames")
        if n / max(1.0, float(info["fps"])) > plan.UPSCALE_MAX_SECONDS + 0.5:
            raise plan.InputError(f"the section is longer than {plan.UPSCALE_MAX_SECONDS:.0f} s; send the used part")
        W, H = plan.target_size(w, h, lines)
        PW, PH = plan.padded(W), plan.padded(H)
        n_feed = plan.vsr_frames(n)
        t_dec = time.time() - t0
        torch.cuda.reset_peak_memory_stats()
        t1 = time.time()
        fps = float(info["fps"] or 30.0)
        # The text guard's detector runs on the CPU while the GPU upscales (onnxruntime lets go of the GIL).
        guard: Dict = {}
        finder = None
        if text_guard:
            if not textguard.available():
                raise RuntimeError(f"the text detector is missing ({textguard.DET_MODEL})")

            def find():
                try:
                    guard["g"] = textguard.Guard(frames, fps, (H, W))
                except Exception as e:  # noqa: BLE001 - reported below: no guard, no upscale
                    guard["error"] = f"{type(e).__name__}: {str(e)[:160]}"
            finder = threading.Thread(target=find, name="textguard", daemon=True)
            finder.start()
        lq = self._lq(frames, n_feed, H, W, PH, PW)
        video = self.pipe(prompt="", negative_prompt="", cfg_scale=1.0, num_inference_steps=1, seed=seed,
                          LQ_video=lq, num_frames=n_feed, height=PH, width=PW, is_full_block=False, if_buffer=True,
                          topk_ratio=sparse * 768 * 1280 / (PH * PW), kv_ratio=3.0, local_range=local_range,
                          color_fix=True)
        torch.cuda.synchronize()
        t_vsr = time.time() - t1
        got = int(video.shape[1])
        if got < n:
            raise RuntimeError(f"FlashVSR returned {got} frames for {n}")
        g = None
        if finder is not None:
            finder.join()
            if "error" in guard:
                raise RuntimeError(f"text guard: {guard['error']}")
            g = guard["g"]
        if g is None or not g.any():
            del lq
            lq = None
        t2 = time.time()
        masks: Dict[int, torch.Tensor] = {}
        enc = media.Encoder(out, W, H, fps, crf=crf, preset=media.PRESET,
                            audio_from=src if info.get("audio") else "", audio_start=start, audio_seconds=seconds,
                            video_seconds=n / fps)
        kept = [] if keep_frames else None
        try:
            for k in range(n):
                fr = video[:, k, :H, :W].to(self.device, non_blocking=True)     # the long pipeline's are on the CPU
                fr = fr.float().clamp(-1, 1)
                if lq is not None:
                    m = g.mask(k)
                    if m is not None:
                        key = id(m)
                        if key not in masks:
                            masks.clear()
                            masks[key] = torch.from_numpy(m).to(self.device)
                        safe = _faithful(lq[0, :, k, :H, :W].to(self.device, non_blocking=True))
                        mt = masks[key]
                        fr = fr * (1.0 - mt) + safe * mt
                fr = ((fr + 1.0) * 127.5 + 0.5).clamp(0, 255).byte()
                rgb = fr.permute(1, 2, 0).contiguous().cpu().numpy()
                enc.write(rgb)
                if kept is not None:
                    kept.append(rgb)
            enc.close()
        except BaseException:
            enc.abort()
            raise
        del video, lq
        peak = torch.cuda.max_memory_allocated() / 2 ** 30
        torch.cuda.empty_cache()
        res = {"frames": n, "fed": n_feed, "fps": round(fps, 3), "source": plan.summary_size(w, h),
               "size": plan.summary_size(W, H), "processed": plan.summary_size(PW, PH),
               "seconds": round(n / fps, 3), "peak_vram_gb": round(peak, 2),
               "timings": {"decode": round(t_dec, 2), "vsr": round(t_vsr, 2), "encode": round(time.time() - t2, 2),
                           "total": round(time.time() - t0, 2)}}
        if g is not None:
            res["text_guard"] = {"text_share": g.share, "samples": len(g.samples), "seconds": g.seconds}
        if kept is not None:
            res["rgb"] = kept
            res["info"] = {"w": W, "h": H, "fps": fps, "audio": False}
        return res


_BLUR: Dict[str, torch.Tensor] = {}


def _faithful(x: torch.Tensor) -> torch.Tensor:
    """The source frame as FlashVSR received it (bicubic to the target size, -1..1, C x H x W), sharpened like
    the CPU path (unsharp 5x5, amount 0.55): what the text guard shows inside lettering."""
    x = x.float()
    key = str(x.device)
    if key not in _BLUR:
        g = torch.tensor([1.0, 4.0, 6.0, 4.0, 1.0], device=x.device)
        g = g / g.sum()
        _BLUR[key] = (g[:, None] * g[None, :]).expand(3, 1, 5, 5).contiguous()
    blur = F.conv2d(F.pad(x[None], (2, 2, 2, 2), mode="replicate"), _BLUR[key], groups=3)[0]
    return (x + 0.55 * (x - blur)).clamp(-1, 1)


def lanczos_baseline(src: str, out: str, lines: int = 1080, start: float = 0.0, seconds: float = 0.0) -> Dict:
    """The video worker's own CPU path today (runpod/src/upscale.upscale_clip): light denoise, Lanczos to the
    target lines, unsharp mask - for the before/after."""
    import subprocess
    t0 = time.time()
    info = media.probe(src)
    W, H = plan.target_size(info["w"], info["h"], lines)
    vf = (f"hqdn3d=1.2:1.2:4:4,scale={W}:{H}:flags=lanczos+accurate_rnd,"
          "unsharp=5:5:0.55:5:5:0.0,format=yuv420p")
    cmd = [media.FFMPEG, "-v", "error", "-y", "-nostdin"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", src]
    if seconds > 0:
        cmd += ["-t", f"{seconds:.3f}"]
    cmd += ["-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "copy",
            "-movflags", "+faststart", out]
    p = subprocess.run(cmd, capture_output=True, timeout=600)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or b"")[-300:].decode("utf-8", "replace"))
    return {"size": plan.summary_size(W, H), "seconds_taken": round(time.time() - t0, 2)}


def frames_psnr(a: np.ndarray, b: np.ndarray) -> float:
    d = (a.astype(np.float32) - b.astype(np.float32)) ** 2
    mse = float(d.mean())
    return 99.0 if mse <= 1e-10 else 10.0 * np.log10(255.0 ** 2 / mse)
