# Style Match: "Make it in this style" (2026-10-14)

Paste any YouTube video, or upload one, whose editing you want. The worker measures the style into a **Style Kit**, and the user's video is made in it.

The proof and its accuracy against the hand catalogue are in `C:\ThumGenius\docs\style-match-v2\README.md`.

## Worker (`runpod/src/style_match`)

| File | What it does |
|---|---|
| `measure.py` | Everything local: ffmpeg + OpenCV + YuNet + whisper. See the passes below. |
| `vision.py` | 3-4 calls on contact sheets the worker draws: what each text reads, its role, graphic vs footage, drawn arrow / ring / pointer, and the structure (cold open, hook, segments, content mix, captions on clip speech or narration). Model `STYLE_MATCH_VISION_MODEL`, capped by `STYLE_MATCH_MAX_USD` (default $0.02). |
| `fonts.py` | 45 free, commercial-safe Google Fonts (OFL / Apache), fetched once to `STYLE_FONT_DIR`. Matched letter by letter, or by the whole line when the letters touch, with the measured horizontal stretch and slant. |
| `kit.py` | Measurements → Style Kit, `clean()` (the app's hand edits go through it) and `card()`. |
| `compare.py` | Reference-vs-ours stills per element, with the confidence. |
| `apply.py` | Kit → timeline. See the list below. |
| `run.py` | Handler action `style_match`. Input: `url` or `video_url`, `channel_id`, `style_id`. Output: `kit`, `card`, `stills` and their R2 URLs under `style-kits/<owner>/<id>/`. |

`measure.py` runs these passes:
- shots and transitions: cuts, flashes, dips, crossfades, whips;
- pace;
- punch-ins and pushes;
- grade and grain;
- text lines tracked over time, clustered into element types;
- for each type, at full resolution:
  - fill, stroke, glow band, shadow and box;
  - cap height, position and tilt;
  - the glyph mask for the font match;
  - entrance and exit, frame by frame;
- marks: rings, triangles and arrows, with their face relation and flatness;
- blur-fill, split screen and picture-in-picture;
- loudness, voice level, music bed under the voice, and SFX transients on cuts and graphics (counted above chance);
- word times, used for the triggers.

`apply.py` does the following:
- Places each element as a Smart Editor motion spec on its trigger, deterministically:
  - captions on phrases;
  - pops on punchlines;
  - labels on every date and number;
  - name labels on a person's first mention;
  - titles on segment starts;
  - arrows and rings on faces.
- Keeps each element at the kit's per-minute rate.
- Copies the kit's transition shares, camera pushes, grade look, music level under the voice and SFX rates.
- Folds the kit's pace into the planner (`config_overrides`: scene seconds, hook seconds and factor, blur-fill).

Pipeline hooks:
- `handler.py`: a job with `input.style_kit` gets its pace through `prepare_input`.
- `timeline.build` runs `apply()` in place of the Smart Editor's free design.

Engine additions:
- `remotion/src/components/smart`:
  - text `outline`, `band` (the glow band), `stretch`, `skew`, and `lib:<Family>` fonts (`styleFonts.ts`, loaded lazily);
  - `panel.padY`;
  - a placement fix: a block wider than half the frame stays centred.
- `gradeMath.ts` / `grade.py`: `doc.grade.look`, a measured custom look.

New dependencies:
- `opencv-python-headless==4.12.0.88`;
- the font library, baked into the image by `scripts/fetch_style_fonts.py`.

The worker branch merges `feature/smart-editor`, the motion-spec engine the kit compiles to.

Tests: `SKIP_DOTENV=1 python -m unittest tests.test_style_match` (offline). It covers:
- a synthetic video for the cuts, the outlined text and its entrance;
- the triggers;
- the compile;
- clean;
- the font list against the renderer's.

## App (`feature/style-match` in the app repo)

| Piece | What it does |
|---|---|
| Migration `20261014120000_video_style_kits.sql` | The `video_style_kits` table (per channel; team-readable, owner-editable) and the private `style-refs` bucket. |
| Function `style-match` | `analyse` (link or upload → worker job), `status` (follows RunPod and saves the kit), `save` (hand edits, cleaned), `reset`, `delete`. 10 measurements a day per user. |
| Create Video → Style | "Make it in this style": paste, upload or pick a saved style. Saved as `render_settings.style_kit_id`. |
| Brand kits | A "Matched styles" tab per channel. |
| `StyleKitPreview` | Each element drawn with its own font and look, a confidence per part, the reference-vs-ours still, and every value adjustable: font, size, width, colour, outline, box, height, entrance, exit, trigger, rate and hold. |
| `video-v2` | Sends `input.style_kit` on plan and build. |

## Deploy steps (not done; the owner's call)

1. **Worker:**
   1. Merge `feature/style-match`. It brings `feature/smart-editor` with it.
   2. Rebuild the image. It adds OpenCV and the fonts.
   3. Roll the endpoint `tuxcziwby5plod`. Check `/health` first: never recycle with running jobs.
   4. Smoke test: `{"action": "style_match", "url": "https://youtu.be/kqTsZAmbByU", "detail_seconds": 120}`.
2. **App:**
   1. Merge `feature/style-match` and push.
   2. Apply the migration by hand.
   3. Ask Lovable to deploy the edge functions `style-match` and `video-v2`.
   4. Check them with `curl -X OPTIONS`.
3. **Optional:** set `STYLE_MATCH_VISION_MODEL` and `STYLE_MATCH_MAX_USD` on the endpoint. The defaults are `google/gemini-3.1-flash-lite` and $0.02.

Cost per measured style:
- 2-5 CPU minutes on the worker, about 1-2 cents;
- 3-4 vision calls, about $0.005.
