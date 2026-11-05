# Breaking News Desk: server vs laptop kit (2026-11-05)

Branches: worker `feature/storm-desk-parity-2026-11-05`, app `feature/storm-desk-parity`. Nothing merged or deployed.

## What is live today

| Thing | State |
|---|---|
| Worker (both RunPod templates) | 63e803e, from 2026-11-03 |
| App code and published site | 36975004, Breaking News Desk card and panel are in the published bundle |
| `storm_desk` in the app | Reaches the worker: picker card, panel, video-v2 job field |
| Laptop rules from 2026-11-04 and 11-05 | None on the server |

The owner is right: picking the style runs the 11-03 template, not what the laptop makes.

Two things blocked the app, separate from the template:

1. **App backend was down.** `wrcucopsyqftqbkhwjag.supabase.co` did not resolve on 2026-11-05 and Lovable reported the database as not accessible. The linked session reports the cause as the Lovable workspace running out of credits; the owner bought Pro at about 19:00 IST. At 19:02 the address answered again (HTTP 401 without a key); sign-in not tested.
2. **OpenRouter balance was $1.07 before this work's test spend.** The worker refuses a plan under its $2 floor ("Your AI balance is too low"), so new videos stay blocked. After the proof, about $0.78. **Still open.**

## Gap table

| Rule | Laptop | Live worker | This branch | State |
|---|---|---|---|---|
| Multi-clip hook | 3 clips, ~20 s, last dissolves | 1 clip, 6 s, hard cut | 3 clips, ~20 s, each at most 9 s, last dissolves | Ported |
| Pause placement | Natural stops, by hand | Most dramatic sentence | `natural_stop`: no question waiting for its answer, no next sentence leaning on this one; breath and new point score higher | Ported, rules not judgement |
| Sentence-exact talking pauses | Word times, up to ~15 s | Fixed 7 s, talking clips mostly refused | `talk_window`: whole sentences, 0.15/0.25 s pad, break length follows the clip, narration re-padded | Ported |
| Pause fits what was said | By hand | Source nearby | Talking clip must share words with what was just said, else refused | Partial: natural-sound clips are matched on title only |
| Small white pause caption | By hand | None | Model writes it, invented digits dropped | Ported |
| No moment reused | Ledger + `reusecheck` gate | Global ledger, 120 days, no laptop moments, no gate | Per-owner/channel ledger in R2, no expiry, fed to search and pauses, gate at plan and render, laptop's 1,718 moments ready to seed | Ported |
| Creator rule | No personalities, 2 shots, never pause or hook | Not there | `mark_channels`, `pause_source_ok`, names list plus vlog words | Ported; the repeat-channel cap (1 shot) is coded but not fed yet |
| Clean shots | Crop + tight delogo, checked by eye | Blur patch baked into the file | Station crop 0.76, KUTV 0.68, text check reads the crop, tighter crop before refusing, delogo fitted tight, nothing baked | Ported; no OCR, edge-based check |
| No source names on screen | Yes | "VIDEO: x" on every shot | ARCHIVE and AI labels only; `creditsText` for the description | Ported |
| Shots fit line and place | Hand-picked per topic | Model + source bank | Same as live | **Not at parity**, see below |
| Dark Horizon looks on words | Hand-written timeline | None | Same drawing code, placed automatically on spoken words, glow 0.38, numbers checked against the script | Ported; placement is rules, fewer looks than by hand |
| Satellite pin map | Yes | None | USGS tiles, auto on a place's first mention, US only | Ported |
| River maps | Hand-coded per video | Other map looks | Not ported | **Not ported** |
| Mix | BGM, SFX ~22%, -14 LUFS | BGM -21 dB, no look SFX | BGM -15 dB, x0.8 under speech, SFX -13 dB, -14 LUFS | Ported. Note below |
| His 4 BGM tracks | Crossfaded sections | One link | Several links in turn, new app field | Ported; tracks must go on R2 |
| 4K thumbnails, both styles | Yes | None | Same layouts after each render, under 2 MB, shown in the editor | Ported |
| Live progress, no stuck jobs | Local page, watchdog | App polls; pod capped at 5 h | "Rendering shots n/m"; shot retried 3 times then fails; pod says failed after 40 min of silence | Ported |
| Render during checks, only changed shots | Partly | Chunk cache | Shots named by content, on disk and R2; a build starts drawing during the checks | Ported |
| Single encode | Two encodes | Remotion + re-encodes | One encode per shot, joined by stream copy | Better than laptop |

Laptop mix note: `render3.py` loudnorms music to -34 LUFS against a -16 voice, which is 18 dB under, while its docs say 15. This branch uses 15 as asked.

## Owner rules that arrived during this work (2026-11-05, after the Lake Mead preview)

Offline tests only: none of these ran on a pod, because the test caps were used up.

| Rule | This branch |
|---|---|
| Nobody talking on camera under the narration | Speech on the clip + a real-size face in 2 of 3 frames: swapped. New, not tuned on real footage |
| No empty pauses | Talking clips stay; at most 2 plain natural-sound pauses a video. A proxy: a machine cannot judge "worth stopping for" |
| Red text on every spoken number | Stats up to every 5 s, was 9 |
| Stats animate in, drift, animate out | Kit's newest `red_stat` copied |
| Small graphs over a clip | Kit's `mini_graph` draws from `doc.stormDesk.looks.graphs`, but **nothing places them automatically yet** |

## Not at parity: the footage

The first proof (75 s of the owner's voice, new plan on a test pod) shows it. Graphics and sound behave; the picks are worse than the laptop's.

- YouTube refused 455 of 491 downloads on the pod, 454 of them bot checks. 1,612 of 1,689 s of the job went there.
- The clips that got through: only 2 stations, the rest explainer-style channels the rules count as "creators", 4 photos, and an interview about another dam project in the hook.
- The fit rule added after that run would refuse that interview, but it has not been run on a new plan (OpenRouter test cap used up).

The laptop gets its quality from direct downloads and a person looking at every source. Porting code cannot give that. The next levers: working download routes for pods, searches aimed at named stations, a footage check on "creator" channels. No cookies or accounts, per the rules.

## Editor limits

The editor preview still draws with Remotion, so it does not show the Dark Horizon looks or the exact lower third. The render does. Old timelines stay on Remotion.

## Proofs

**Same edit, server engine.** Rendered before the 2026-11-05 rules above. The laptop's Lake Mead edit (lm13: same shots, crops, captions, pauses, looks, BGM) rendered on a 16-core test pod.

- Full video: https://pub-85b1063e5318421a84e390a0f0fde47c.r2.dev/projects/adhoc/final-1793873029-13b0bb96ebcf.mp4
- Level check over the first 75 s, against the laptop's file:

| | Server | Laptop |
|---|---|---|
| Hook clips 1, 2, 3 | -16.2, -17.3, -19.4 dB | -15.3, -17.0, -19.0 dB |
| Voice | -15.4 dB | -15.0 dB |
| Between words (music and clip sound, some voice tail) | -27.1 dB | -26.4 dB |
| Master | -14.01 LUFS, peak -1.4 dB | not measured on the same range |
| Pause sound | 6 of 6 clips | |
| Picture vs sound | 0.03 s apart | |

The replay shows the engine only. A few shots may hold or differ, because lm13 was re-cut by another session during the test.

**New plan end to end.** 75 s of the owner's voice became a 112.8 s video: https://pub-85b1063e5318421a84e390a0f0fde47c.r2.dev/projects/adhoc/final-1793867441-3f2cf91a4a41.mp4. This ran before the fixes, so it shows 2 hook clips, a failed master and the poor footage described above. The fixes were then checked with offline tests and the replays. A new plan on the final code has **not** been run, because the OpenRouter test cap was used up.

**Only changed shots drawn.** With 2 shots changed, R2 held 151 shots, the 149 plus 2 new.

## Is the server faster? (9-minute video)

| Step | Laptop | Pod, 16 cores |
|---|---|---|
| Shots | 7.9 min | 5.1 min, looks included |
| Looks | about 6.5 min | in the line above |
| Join + sound | about 5.7 min | 1.8 min |
| **Drawing total** | **about 20 min** | **about 7 min** |
| Whole job with checks and upload | | 10.5 min, $0.11 |
| With shots kept on R2 | | 11.9 min, $0.13 |
| 2 shots changed, re-render | | 6.6 min, $0.07 (measured before the fix that stops it downloading unchanged shots' sources) |
| Footage work | about 2 h with a person picking | 27 min for 75 s of voice, and worse picks |

- **Drawing: about 3 times faster.** Measured on one video on 16 cores. 32 cores not measured.
- **Footage: not faster, and worse.** Whole-video time is therefore not better yet.
- The Remotion path on 32 cores took about 27 min for the same video, but that run included repairs and a second render, so it is no fair baseline.
- Drawing during the checks ran in the first proof, but its timing was not captured.

## Ported and not ported

Ported: everything marked Ported in the gap table.

Not ported or not equal:
- Footage choice as good as a person's, and downloads that work from pods
- River maps
- Look-alike shots (CLIP) are reported, not swapped
- Creator cap of 1 shot for a channel used in an earlier video
- OCR on station corners (edge-based check instead)
- Editor preview of the looks
- Automatic placing of the small graphs
- Natural-sound pause clips are matched on title only

## Spend

RunPod $1.46 (cap about $1.50). OpenRouter $0.288 (cap $0.30), with the worker's $2 balance floor lowered to $0.50 on the proof pod only. Avatarity for the thumbnail picture. Test files stay in R2 under `tests/parity-2026-11-05/`, `sdpieces/parity-proof-2/` and `projects/adhoc/`.

## Deploy steps (each needs the owner's yes)

No migration. No new database objects.

1. **Top up OpenRouter** above the $2 floor, or no plan starts.
2. **Worker image.** Run "Build video worker image" by hand on `feature/storm-desk-parity-2026-11-05`, check it, then fast-forward `thumbgenius-video-worker` to it.
3. **Point both templates** (gjr1mh79q6, rksecohuvp) at the new image with `deploy_image_only.py`, only when `/health` shows nothing running and no `thumbgenius-*` pod is rendering. Then `rp_recycle.py`, because warm workers keep the old image.
4. **Env:** none needed. `STORM_DESK_ENGINE` defaults to `pieces`; set it to `remotion` on the templates to switch new plans back. Old timelines stay on Remotion.
5. **Seed the ledger** with the owner's id, dry run first:
   `python scripts/seed_storm_ledger.py <owner id> <kit>/credits/used_moments.json`, then again with `--write`.
6. **App.** Merge `feature/storm-desk-parity` into main (merges cleanly with main at 455ce835), push, have Lovable redeploy `video-v2` (it uses `_shared/stormDeskJob.ts`), then Publish.
7. **BGM.** Upload his tracks to R2 and paste the links into "More music" in the panel.
8. **Check** with one short real video: `pod_*` job, hook count, `meta.stormDesk.render.pieces`, thumbnails in the editor.
9. **Later:** an R2 lifecycle rule on `sdpieces/`, since kept shots use about 0.9 GB per 9-minute video.
