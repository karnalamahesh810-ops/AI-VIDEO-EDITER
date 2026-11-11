# Storm Desk cloud cost: free checks, shared library (2026-11-11)

Branch `feature/storm-desk-cost-2026-11-11` (82e585d, 0e850fb, e3b16c5 on top of 4ee40f9). **Not deployed, not merged.**

## Status in one paragraph

The worker now does the laptop kit's shot checks locally (no paid vision), screens footage before the cut and keeps the
verdicts in a shared library on R2, refills bad shots from the neighbour's take, frames square/letterboxed clips like the
kit (`fit`, `rect:`), and drops background music for ambience beds. The two measured test builds (gcd 10.9 min, elp
16.9 min) **stopped at the planning step because the shared OpenRouter balance ran out**, so no cloud render and no
side-by-side with the laptop videos exist yet. They need about **$1 of OpenRouter** (owner's call). Everything below
marked *measured* comes from real pods; *projected* is arithmetic from those numbers.

## What changed (worker)

| Piece from the kit | Where now | Notes |
|---|---|---|
| clean_fill `clean()`: dark, bars, pillarbox | `src/shotcheck.py` `frame_reason` | 640x360 frames at 5/50/95 % of the shot |
| faces.py (YuNet) | `stormgate.face_share` via shotcheck | face > 0.15 % of frame refuses |
| persondet.py (ssdlite) | `src/sdkit/models/person_ssdlite.onnx` | exported from torchvision; 2 threads/session |
| RapidOCR text check | `stormgate.read_text` | 2 threads per reader (e3b16c5) |
| prescreen.py | `stormlib.prescreen` + `shotcheck.screen/flush` | verdicts keyed `id@a-b@mode@v1` in `sdlib/v1/screened.json` (private bucket) |
| merge_clean / fixloop | `stormgate._rung_stretch` | neighbour's take continues; never next to pause/hook clips |
| audit + refill | `stormgate` autofix (FULL_CHECKS) | the ladder: spare, library, originals, stretch, ai (off when free), hold |
| render3 `fit`, `rect:x,y,w,h` | `stormpieces.vf_for`, `shotcheck.auto_frame` | auto-picked by cropdetect + SAR |
| per-pause `amb_bed`, no music | `stormdesk.set_amb_beds`, `music_wanted` | default no music; `rushing_water` bundled |
| source bank without a model | `srcbank.review_local`, `match_local` | CLIP prompts instead of a vision call |
| switch | `STORM_FREE` (on), per-job overridable | turns off VISION, OFFTOPIC_AI, HOOK_CUT_CHECK, SOURCE_BANK_MODEL_MATCH for storm_desk |
| cost per stage | `costs.stage()` | `costs.stages` in every result: seconds + paid USD per stage |

Tests: `tests/test_storm_free.py` (21) + the storm suites (201) pass offline. The full suite was not run (laptop memory).

## Free checks vs the kit (measured, laptop)

- 25 shots the kit approved: 21 pass, 4 refused (3 text, 1 pillarbox); not yet reviewed by eye whether those 4 are false alarms.
- 13 stretches the kit rejected: 13 of 13 refused.
- Speed: ~5 s per shot on the laptop (3 frames, OCR dominant); on a pod they run in parallel.

## Measured on pods

| Run | What happened | RunPod | OpenRouter |
|---|---|---|---|
| smoke 1 (16 vCPU) | stopped by the AI-balance preflight (it still counted paid checks: fixed 0e850fb) | $0.002 | $0 |
| smoke 2 (16 vCPU) | never started its job; ran to the 75 min limit (no log then; logging added) | ~$0.60 | $0 |
| smoke 3 (8 vCPU, 120 s voice) | 22 min image pull, then sourcing; library index then had only 14 sources, so it fell back to search; my wait cap stopped it | ~$0.22 | ~$0.13 |
| gcd (8 vCPU, 10.9 min) | transcribe 35.5 s; plan stopped by OpenRouter credit after 6 calls | $0.0065 | $0.130 |
| elp (8 vCPU, 16.9 min) | preflight: $0.11 left, needs $0.12; stopped, nothing spent | $0.001 | $0 |
| **Total test spend** | | **~$0.83 of $1.50** | **~$0.26 of $0.30** |

gcd's plan, measured: 6 plan calls on `google/gemini-2.5-flash`, 36k prompt tokens, 48k completion tokens of which
**21k were reasoning**, $0.125 (+ $0.006 brief) before it stopped unfinished. Reasoning is now off in the test env
(`DIRECTOR_REASONING_EFFORT=none` -> `reasoning.max_tokens 0` on Gemini 2.5).

Source bank on the smoke pod, measured: 26 searches, 9 sources, 39 MB downloaded, local review 57 s, CLIP match 0.1 s,
**$0 vision**. Almost every per-line YouTube fetch failed with "video is unavailable" on that pod: the library (R2) has
to carry the footage, not search.

## Per 15-minute video: what still costs money (projected)

"Before" splits are approximate (the live $4-5 total from earlier runs, divided by what dominated it).

| Stage | Before (live) | Now (free path) | Basis |
|---|---|---|---|
| Shot checks (vision) | $2-3 | **$0** | local checks, measured |
| Off-topic / hook checks | $0.2-0.4 | **$0** | off for storm_desk |
| Plan (director LLM) | $0.3-0.6 (gpt-5.2) | **$0.08-0.12** flash, no reasoning; ~$0.02-0.03 flash-lite | gcd partial $0.125 with reasoning, 44 % of tokens were reasoning |
| Footage | proxy GB + re-downloads | **~$0** when the library has it (R2 egress free) | 93 % / 73 % of gcd/elp footage was already in the owner's earlier videos |
| RunPod | 16-32 vCPU, ~1-2 h, failed runs | **$0.18-0.25** (8 vCPU $0.24/h, ~45-60 min) | rate measured; build time not yet measured |
| Image pull | | **$0-0.09** (0-22 min) | measured both ends |
| Thumbnail picture | ~$0.14 | ~$0.14 (off in the test) | unchanged |
| R2 library | | ~$0.18 / month total (12 GB), shared by all videos | R2 price |
| **Total** | **$4-5** | **~$0.30-0.45 + thumbnail** | |

The target ($0.20-0.50) is in reach without the thumbnail; with flash-lite planning and a cached image it nears $0.25.

## Compute

- 8 vCPU cpu3c/cpu5c at $0.24-0.28/h was available when 16 vCPU was not (21:45 IST). One machine per build.
- The image pull (22 min on a fresh host) is billed: keep pods in data centres that already hold the image, or a
  slimmer storm-desk image.
- Spot/interruptible CPU and AWS Spot are in `compute-providers-2026-10-07`; not tried here.

## Open items

1. **OpenRouter top-up (~$1, owner)**, then: `python sdtest.py start gcd 8 4200` / `start elp 8 4200` + `wait`, then
   `compare.py gcd <server.mp4>` / `compare.py elp ...` for the side-by-side (scratchpad tools; see hand-over note).
2. Library upload still running: 136/187 sources (5,497 shots) indexed; re-run `libindex.py` when it ends.
3. Try `DIRECTOR_MODEL=google/gemini-2.5-flash-lite` for storm_desk plans (quality check needed).
4. The test ledger sits in the public videos bucket (privacy): move ledgers to the private sdlib bucket.
5. Ambience beds beyond `rushing_water` need licence-clean sources.
6. Deploy needs: private bucket env `R2_SDLIB_BUCKET=thumbgenius-sdlib` on the template, rapidocr in the image,
   `DIRECTOR_REASONING_EFFORT` decision. Owner's yes before any of it.
