"""
A music bed made for each video: ACE-Step 1.5 (MIT, code and weights; github.com/ace-step/ACE-Step-1.5) - the
2B turbo DiT (8 steps) with the 5 Hz LM planner, an instrumental from a mood caption at the video's length,
then cut, faded and brought to the library tracks' loudness (-27 LUFS) so the renderer's flat 50% bed and its
0.8 duck under the voice sound the same as with a library track.
"""
from __future__ import annotations

import glob
import os
import shutil
import sys
import tempfile
import time
from typing import Dict, Optional

import media
import plan

ACE_DIR = os.environ.get("ACESTEP_DIR", "/opt/ACE-Step-1.5")
CKPT_DIR = os.environ.get("ACESTEP_CHECKPOINTS_DIR", "/models/acestep")
DIT = os.environ.get("ACESTEP_DIT", "acestep-v15-turbo")
LM = os.environ.get("ACESTEP_LM", "acestep-5Hz-lm-1.7B")
LM_BACKEND = os.environ.get("ACESTEP_LM_BACKEND", "vllm")


class Music:
    def __init__(self, dit: str = DIT, lm: Optional[str] = LM, ckpt_dir: str = CKPT_DIR, ace_dir: str = ACE_DIR,
                 backend: str = LM_BACKEND):
        t0 = time.time()
        if ace_dir not in sys.path:
            sys.path.insert(0, ace_dir)
        os.environ.setdefault("ACESTEP_CHECKPOINTS_DIR", ckpt_dir)
        from acestep.handler import AceStepHandler
        from acestep.llm_inference import LLMHandler

        self.dit = AceStepHandler()
        msg, ok = self.dit.initialize_service(project_root=os.path.dirname(ckpt_dir.rstrip("/")), config_path=dit,
                                              device="cuda", offload_to_cpu=False)
        if not ok:
            raise RuntimeError(f"ACE-Step DiT failed to load: {str(msg)[:300]}")
        self.lm = None
        self.lm_name = ""
        if lm:
            handler = LLMHandler()
            msg, ok = handler.initialize(checkpoint_dir=ckpt_dir, lm_model_path=lm, backend=backend, device="cuda",
                                         offload_to_cpu=False, dtype=None)
            if not ok:
                raise RuntimeError(f"ACE-Step LM failed to load: {str(msg)[:300]}")
            self.lm, self.lm_name = handler, lm
        self.dit_name = dit
        self.load_seconds = round(time.time() - t0, 1)

    def generate(self, out_mp3: str, caption: str, seconds: float, seed: int = 1247, bpm: int = 0,
                 keyscale: str = "", steps: int = 8, use_lm: bool = True, lufs: float = plan.MUSIC_DEFAULT_LUFS,
                 fade_in: float = 0.5, fade_out: float = 1.0, carve_db: float = plan.MUSIC_CARVE_DB) -> Dict:
        """One instrumental of `seconds` (10-600) -> `out_mp3` at `lufs`. Returns the timings and the measured
        loudness. The model makes a little more than asked; the bed is cut to the exact length and faded."""
        from acestep.inference import GenerationConfig, GenerationParams, generate_music

        t0 = time.time()
        gen_seconds = min(plan.MUSIC_MAX_SECONDS, max(plan.MUSIC_MIN_SECONDS, float(seconds)))
        thinking = bool(use_lm and self.lm is not None)
        params = GenerationParams(
            task_type="text2music", caption=caption, lyrics="[Instrumental]", instrumental=True,
            vocal_language="unknown", bpm=bpm or None, keyscale=keyscale or "", duration=gen_seconds,
            inference_steps=int(steps), guidance_scale=1.0, seed=int(seed), shift=3.0,
            thinking=thinking, use_cot_metas=thinking, use_cot_caption=False, use_cot_language=False)
        config = GenerationConfig(batch_size=1, use_random_seed=False, seeds=[int(seed)], audio_format="wav")
        work = tempfile.mkdtemp(prefix="music_")
        try:
            res = generate_music(self.dit, self.lm if thinking else None, params=params, config=config,
                                 save_dir=work)
            if not res.success or not res.audios:
                raise RuntimeError(f"ACE-Step: {res.error or res.status_message or 'no audio'}"[:300])
            raw = res.audios[0].get("path") or next(iter(glob.glob(os.path.join(work, "*.wav"))), "")
            if not raw or not os.path.isfile(raw):
                raise RuntimeError("ACE-Step returned no file")
            t_gen = time.time() - t0
            raw_seconds = media.duration(raw)
            cut = min(float(seconds), raw_seconds) if raw_seconds > 0 else float(seconds)
            # The piece's own ending, not its trailing silence: the bed is cut where the music stops and the
            # renderer repeats it with its crossfade if the video runs longer (trackSeconds = "seconds").
            end = media.music_end(raw)
            if end > plan.MUSIC_MIN_SECONDS:
                cut = min(cut, end)
            t1 = time.time()
            level = media.finish_music(raw, out_mp3, cut, lufs, fade_in, min(fade_out, cut / 4), carve_db)
            meta = {k: v for k, v in ((res.audios[0].get("params") or {}).items())
                    if k in ("bpm", "keyscale", "timesignature", "seed", "duration")}
            return {"seconds": round(cut, 2), "raw_seconds": round(raw_seconds, 2), "seed": int(seed),
                    "lm": self.lm_name if thinking else "", "dit": self.dit_name, "steps": int(steps),
                    "carve_db": float(carve_db),
                    "meta": meta, **level,
                    "timings": {"generate": round(t_gen, 2), "finish": round(time.time() - t1, 2),
                                "total": round(time.time() - t0, 2)}}
        finally:
            shutil.rmtree(work, ignore_errors=True)
