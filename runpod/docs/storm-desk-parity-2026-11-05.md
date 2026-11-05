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

Two things block the app, separate from the template:

1. **App backend address does not resolve.** `wrcucopsyqftqbkhwjag.supabase.co` returned NXDOMAIN on Google and Cloudflare DNS on 2026-11-05, and Lovable reports the database as not accessible. The Lovable workspace reads plan "free", record updated 2026-11-04 12:11 UTC. Cause not proven; a paused backend after a plan change is a guess. Sign-in and new videos cannot work until it is back.
2. **OpenRouter balance is $1.07 before this work's test spend.** The worker refuses a plan under its $2 floor ("Your AI balance is too low"). After the proof, about $0.78.

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

## Not at parity: the footage

The first proof (75 s of the owner's voice, new plan on a test pod) shows it. Graphics and sound behave; the picks are worse than the laptop's.

- YouTube refused 455 of 491 downloads on the pod, 454 of them bot checks. 1,612 of 1,689 s of the job went there.
- The clips that got through: only 2 stations, the rest explainer-style channels the rules count as "creators", 4 photos, and an interview about another dam project in the hook.
- The fit rule added after that run would refuse that interview, but it has not been run on a new plan (OpenRouter test cap used up).

The laptop gets its quality from direct downloads and a person looking at every source. Porting code cannot give that. The next levers: working download routes for pods, searches aimed at named stations, a footage check on "creator" channels. No cookies or accounts, per the rules.

## Editor limits

The editor preview still draws with Remotion, so it does not show the Dark Horizon looks or the exact lower third. The render does. Old timelines stay on Remotion.
