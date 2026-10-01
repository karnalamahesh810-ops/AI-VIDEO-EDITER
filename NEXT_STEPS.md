# Smart reframing - where this branch stands

Branch: worktree-agent-ae983bc4a803af9ca, reset onto origin/thumbgenius-video-worker (852196b).
Not pushed, not deployed.

## Done (WIP commit)
- `runpod/src/reframe.py` - detection half, written but NOT yet run on real clips:
  frame decode (ffmpeg rawvideo), YuNet faces via onnxruntime (two scales, NMS,
  multi-frame tracks), saliency (spectral residual + Achanta colour contrast),
  subject box from a map, camera motion (block phase correlation: pan / zoom /
  shake / cut), burned-in logo/chyron check, effective sharpness (spectrum cutoff).
- `runpod/src/config.py` - REFRAME_* flags (REFRAME_ENABLED default off for now) + FACE_MODEL.
- Face model fetched locally for testing: scratchpad `models/yunet/face_detection_yunet_2023mar.onnx`
  (HF opencv/face_detection_yunet rev 3cc26e7f1014a5ee5d74a42acee58bafc9d0a310, MIT,
  sha256 8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4).
- Evaluation media: all 159 Lake Powell scene files in scratchpad `reframe_eval/media/`
  (s0000.mp4 ...), compact scene list `reframe_eval/lp_doc.json`.

## Left
1. `reframe.detect_clip` / `detect_still` (assemble the pieces into media.focus), calibrate the
   static-camera thresholds and saliency confidence on the Lake Powell clips (contact sheets).
2. Planner: focus -> media.reframe {from, to, kind, aspect, seconds, source}; subject kept inside
   both boxes (so every frame), scale caps by effective lines (<=1.15 on SD/720p), rate limits,
   min shot length, variety (not every shot), skip news / logos / framed vertical / anchored marks.
   Stills: media.reframe {subject} only - the renderer aims the existing motion at it.
3. handler.do_plan: run `reframe.place(doc)` after `marks.place(doc)` (clips still local), time-boxed.
4. Remotion: `components/reframe.ts` (box interpolation -> CSS transform, binding check on
   media.source, scene.reframe "off"/{from,to} editor override), SceneClip + stillMotion aiming, types.ts.
5. scripts/fetch_models.py: add YuNet with its sha256; README/config docs; styles: news_compilation +
   nature_weather turn clip reframes off; CONFIG_OVERRIDABLE.
6. Evidence: before/after sheets (first + last frame of each move) for ~15 scenes, plus a few real
   Remotion stills to prove the CSS matches; decide REFRAME_ENABLED default from them.
7. Tests (offline): `SKIP_DOTENV=1 python -m unittest discover -s tests -t .` from runpod/.
