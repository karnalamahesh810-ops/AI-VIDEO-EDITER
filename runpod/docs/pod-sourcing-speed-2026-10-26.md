# Pod sourcing speed (2026-10-26)

Branch `fix/pod-sourcing-speed` (worker). Not merged, not deployed.

The owner asked why the Hoover Dam video (project 82e7cae1, pod job pod-c7z9rr7fcbwxrg, 16 vCPU cpu3c,
$0.48/h, option B) took so long. The footage search took 44 of its 47 build minutes.

## Where the time went (measured: scene_data.meta + video_job_events)

Whole video: created 08:14:54, done 09:43:22 (88.5 min) for 17.8 min of video (204 scenes, 195 searched lines,
news_compilation style). Build pod: boot 2 min, narration 6 s, transcribe 41 s, plan 133 s, **footage 08:19:57 -
09:01:45 (41.8 min)**, then design/AI fill/publish; the render ran as its own job 09:18:45 - 09:43:22 (24.6 min,
one quality re-render). Build cost $3.05 (RunPod $0.39 for 2,934 pod-seconds, vision $1.70, planner $0.78,
AI pictures $0.19); the render's cost is not in the timeline.

The 41.8 footage minutes:

| step | time | result |
|---|---|---|
| subject pools (before pass 1) | ~3 min | 6 of 125 lines covered |
| pass 1 (195 lines, 28 threads, 300 s a line) | 24.9 min | 159 found, 36 empty; ended on its own (box 2,340 s not reached) |
| pass 2 | 2.4 min | 0 of 36 replaced |
| AI recheck + generated stills | 4.1 min | 2 of 36 (32 still attempts, 0) |
| variety hold + rescue box + ladder + upscale | ~7.5 min | 65 photos held for the style's 14-photo cap (64 restored); rescue asked 115, filled ~4; ladder 134 s: 44 of 49 (12 spare clips, 25 spare pictures, 6 other moments, 1 picture) |

Inside pass 1 (thread-seconds, 28 threads x 1,495 s = 41,860):

- **CPU (the main limit).** 600 YouTube sections at **26.0 s each** (15,604 s, 37% of all thread time). The
  same proxies and the same 10.6 s sections took **14.4-15.3 s after pass 1 ended** (08:50-09:05) against
  23.6-28.4 s during it; the clip gate's slop check took 4.18 s a clip against 1.65 s on an idle pod of the same
  type. Each section was re-encoded at x264 medium crf 16: measured 22.6 CPU-s a section with 16 at once, i.e.
  ~12,000 CPU-s for pass 1's 600 sections = about **half the pod's 16 cores for the whole 25 minutes**, before the
  scene scans, trims, CLIP checks (548 s + 256 s queued) and sharpness checks (1,065 s).
- **Network.** 2.39 GB through **3 of the 13 proxies**: proxies 8, 11, 13 carried 1,029-1,296 requests each at
  11-12.7 s a request (five yt-dlp processes per address); the other 10 were degraded by one early bot check
  (4-13 requests, 62-87% success) and never asked again.
- **AI: not a limit.** 3,479 vision calls, 3.5 s of slot waiting in total (20 slots), 1.52 s a call.
- **Time boxes: not the limit in pass 1** (it ended at 1,495 s of a 2,340 s box: every line settled on its own
  time, so "end pass 1 when every line is settled" already holds). The tail boxes cost time for little: pass 2
  141 s for nothing, the rescue box up to 300 s for ~4 lines.

Compared with Mount Rainier (b6cef117, 2026-10-23, same 16-core pod, 235 lines, before the empty-spots fix):
pass 1 2,141 s, sections 46.5 s each, clip gate 46.1 s, picture gate 35.4 s, pass 2 446 s, 109 lines left to holds
and cards, $4.12. The 2026-10-05 audit (serverless fan-out, 10 parts) found ~20 min of footage time for 15 min of
video.

## Why 49 lines were empty on a well-covered topic

1. **The supply is slop.** YouTube's results for this story are full of AI-made and slideshow uploads: the gate
   turned down 119 AI-painted pictures, 82 slideshows of stills, 56 stills with a slow pan, 21 with other
   creators' captions; 145 judged candidates had text or watermarks and 60 were studios/talking heads. Only 51 of
   195 lines got a YouTube clip; 75 got web pictures.
2. **Each candidate was slow.** A clip candidate cost ~26 s of download plus ~6 s of gate under the CPU load, so
   a line's 300 s share covered ~3 candidates (3.1 downloads a line on average) before falling back to pictures.
3. **The photo cap.** news_compilation allows 14 photos; 92 were used, so 60 photos were taken off and sent through
   the rescue box (115 lines asked, ~4 filled) before 64 were put back; ~15 lines whose photo could not come back
   (cap, "a still in the opening") joined the ~34 lines pass 1 found nothing for: **49 = ~34 never found + ~15
   held by the variety rules**. The ladder then filled 44 of them from the spare bank in 134 s.
4. Proxies: 3 working routes for 16 network slots (above).

## Free fixes in this branch

### 1. Near-lossless intermediate for sections that are cut again (DOWNLOAD_TIDY_FAST, on)

Every footage section is downloaded with 2 s of margin on each side and re-encoded by yt-dlp's ffmpeg at
x264 **medium crf 16**. `filters.tidy_clip` then cuts the clip out of it and re-encodes **again**
(ultrafast crf 20): the file the viewer sees is always that cut, never the download. So the expensive encode
went to waste on the ~4 of 5 candidates the gate turns down, and on the rest it was only an intermediate.

The download a caller cuts again at once (`media.fetch_clean_clip`, the main path) is now an x264
**ultrafast crf 12** intermediate. Audio/hero sections (celeb) and every path that keeps the download as it is
keep the medium crf-16 encode.

Measured on a throwaway 16-vCPU cpu3c pod (the live image, 4 real 1080p clips of this video, 12 s sections,
then the worker's own trim, scored against the source's same 8.5 s):

| intermediate | CPU-s alone (4 clips) | 16 side by side: wall / CPU-s | final PSNR (dB) | final SSIM |
|---|---|---|---|---|
| medium crf 16 (before) | 13.7 / 15.5 / 18.9 / 21.9 | 26.9 s / 361 | 44.15 / 42.00 / 43.43 / 43.09 | 0.9835 / 0.9891 / 0.9838 / 0.9842 |
| **ultrafast crf 12 (now)** | 1.7 / 2.6 / 2.7 / 2.8 | **3.9 s / 55** | **45.51 / 43.05 / 44.92 / 44.64** | **0.9869 / 0.9910 / 0.9875 / 0.9887** |
| ultrafast crf 14 | 2.0 / 2.5 / 2.5 / 3.1 | 4.3 s / 55 | 45.34 / 42.75 / 44.55 / 44.28 | |
| veryfast crf 14 | 6.5 / 7.3 / 7.8 / 8.9 | 11.5 s / 157 | 44.12 / 41.93 / 43.67 / 43.07 | |

The clip shown is closer to the source (+1.0 to +1.6 dB) and slightly smaller, at about 1/7 of the CPU.
The intermediate itself (what the gate's checks read) is far closer to the source (PSNR 51-54 vs 45-47 dB).
It is bigger on disk (19-41 MB vs 9-16 MB for 12 s) but only until `tidy_clip` replaces it.

### 2. Real core count and a machine sampler (src/machine.py)

The pod's container has no cgroup CPU quota (`cpu.max` = `max`) and reports the **host's 192 cores** in
`os.cpu_count()`; it is held to 16 by affinity. `machine.cpus()` takes the smallest of quota, affinity and host.
The footage search now records the machine every 5 s: CPU use against the 16 cores, memory headroom,
throttling and how many ffmpeg / yt-dlp processes ran (`meta.sourcing.machine`), and the yt-dlp network queue
records its waits per kind (`meta.sourcing.gateQueues.network`). Before this, "was the pod CPU-bound?" could not
be read from a job.

x264 threads (DOWNLOAD_THREADS, default x264's own): measured, x264's own choice gives the best throughput
(16 medium encodes at once: own 26.5 s, 4 threads 27.7 s, 2 threads 28.7 s, 1 thread 31.8 s; 8 at once: own
13.4 s, 2 threads 16.2 s). Its cost is memory: 16 at once held 16.9 GB of the pod's 32 (2 threads: 8.6 GB). With
the ultrafast intermediate that pressure goes away, so the default is unchanged.

`SOURCE_WORKERS_PER_CPU` (default 0 = off) can clamp the app's SOURCE_WORKERS 28 to the cores.

### 3. Degraded proxies stay in the rotation (src/proxies.py)

A route degraded by one refusal with a short record (one failure in a row, at least 2 successes, at least 60% of
its requests through) now takes traffic once the healthy routes each carry 2 more requests than it does, and earns
its way back with 3 successes; a second refusal in a row still quarantines it. The Lake Powell fix (2026-10-01)
only covered routes with 10+ successes at 90%+, so an early bot check still sidelined a route for the whole job.

### 4. Pass 2 skips lines whose whole search already ran (PASS2_SKIP_EXHAUSTED, on)

An empty line whose pass-1 search ran its whole plan inside its own time (for a clip-first line: its clip stages
ran to their end, `_CLIP_SEARCHED`) is not searched again one result further down; the AI recheck, the rescue
pass and the ladder still take it. A line cut short by its time still gets pass 2. Hoover: pass 2 spent 141 s for
0 of 36; Mount Rainier spent 446 s on it.

### Expected effect on a video like this one

| fix | expected |
|---|---|
| tidy intermediate | sections ~26 s -> ~15 s in pass 1 (the after-pass-1 / idle-pod level), slop check ~4.2 -> ~1.7 s; a line's ~215 thread-s -> ~170: pass 1 ~25 -> ~20 min, and more clip candidates a line inside its 300 s (fewer empties) |
| pass 2 skip | up to -2.4 min (this video), -7 min (Mount Rainier) |
| proxy rotation | 16 yt-dlp slots over up to 13 addresses instead of 3; not measured |
| total | ~42 -> ~32-35 min of footage search, same or better clips, no new spend |

Not changed (owner decisions, reported): the subject pools covered 6 of 125 lines in ~3 min; the 14-photo cap
sends ~60 good photos through a 300 s rescue box that filled ~4 before they are put back.

## Fast sourcing (costs more; off by default)

A job input `"fast_sourcing": true` (or a number of machines, 2-6) splits one pod build's footage search over
`FAST_SOURCING_PARTS` (4) machines: the pod plus 3 serverless workers of the existing endpoint, through the
existing `fanout.source` / `source_part` path. What is new:

- `fanout.fold_fast_sourcing` turns the input into the job's own config overrides (BUILD_FANOUT 1,
  SOURCE_PARTS N, SOURCE_PART_ROUNDS 1), put back after the job like every override. The default stays one
  machine per build (BUILD_FANOUT off - the owner's 2026-10-07 cost decision). `FAST_SOURCING=0` on a template
  refuses every job's ask.
- `SOURCE_PARTS` is separate from `FANOUT_PARTS` (which the app sets to 1 on a pod and which also caps a
  serverless parent's render chunks), so a job's parts never change its render. `_Units` no longer sizes its
  thread pools from FANOUT_PARTS (it would have been `ThreadPoolExecutor(max_workers=0)` on a pod).
- Deadline-aware: the job's sourcing deadline is `fanout.fast_deadline` = each machine's share of the lines at
  SINGLE_PASS1_PER_SCENE (12 s) a line + SINGLE_TAIL_SECONDS (600), never under 900 s, never past the usual
  budget. Every part's pass 1 is cut at that deadline (`run_part`), so a worker bills at most that long.
- Few, big parts and one round: 4 contiguous parts of ~50 lines each; what they leave empty is filled on the
  pod (rescue, spare bank, ladder) and never sent out a second time.
- Shared spare bank: each part returns its best 60 judged spares **without files** (`spares.export`); the pod
  banks them (`spares.add_remote`) and its ladder downloads one only when it is about to judge it for a line
  (`spares.fetch_remote`). The pod's fill so drew on every part's footage, not just its own quarter.

**Measured / estimated cost and time** (from this video's own phases; serverless worker $0.576/h, pod $0.48/h;
a part = 60 s cold start + its subjects' pools ~120 s + pass 1 at the pod's measured 215 thread-s a line + 30 s
collect + 60 s upload; the pod's own fill afterwards ~10 min as measured):

| video | today, one pod | fast, 3 parts | fast, 4 parts |
|---|---|---|---|
| Hoover Dam (195 lines, 17.8 min) | 41.8 min | 29 min, **+$0.26** | 25 min, **+$0.31** |
| 15-min video (~165 lines) | ~38 min | 27 min, +$0.23 | 24 min, +$0.28 |
| same, after the free fixes | ~32-35 min | 24-26 min, +$0.22-0.24 | 22-23 min, +$0.26-0.29 |

("+$" = the workers' seconds minus the pod-seconds saved; vision and planner spend is the same lines judged.)
Every case is above the owner's ~$0.20 line, so **the default stays off**: offer it as a paid "Fast build".
Not measured live (a fast build needs the serverless workers on this image; the endpoint runs the live one).

## App spec: "Fast build" toggle (not built; the app is not edited in this branch)

Worker side is ready (`fast_sourcing` in the job input). The app needs:

1. **Setting.** `render_settings.fast_build: boolean` (default false), saved like `run_on`
   (`useCreateVideo.ts`: `fastBuild = settings.fast_build === true`, `setFastBuild(v) => setSetting({ fast_build: v })`).
2. **UI.** `src/components/createvideo/create/MoreOptions.tsx`, a `SettingRow` next to "Machine":
   name **"Fast build (+$X)"** (X = about $0.02 a narration minute, e.g. "+$0.30" for 15 min: the table above;
   for customers shown in credits, see 4), hint **"Finds the footage on 4 machines: about 10-15 minutes sooner"**,
   a switch (`role="switch"`, same control as the other on/off rows). Disabled with the hint "Pod only" when
   Machine = Serverless (a serverless build already runs on the endpoint) - or simply leave it on: the worker
   honours it on serverless too. Shown to everyone (it is a paid speed option), or admins only first.
3. **video-v2** (`supabase/functions/video-v2/index.ts`, where the worker input is built, ~line 765 next to
   `graphics_density`): `if (settings.fast_build === true && (action === "plan" || action === "build"))
   input.fast_sourcing = true;` Nothing changes in `launchPod` (the pod env stays FANOUT_PARTS 1: the job's
   own `fast_sourcing` turns the parts on for that job only). The serverless endpoint must have free workers:
   it is the same endpoint the render helpers use, so 3 parts + a render never overlap (parts end before the
   render starts).
4. **Charge.** `_shared/creditRules.ts`: `FAST_BUILD_CREDITS_PER_MINUTE` (proposed 1 credit a narration minute,
   about $0.03 at the Creator plan's price - covers the measured extra cost below with margin);
   `videoCredits(seconds, fps, { fast })` adds it for a plan/build with `fast_build`, and the charge's `meta`
   records `fast_build: true` so refunds and the usage page show it.
5. **Show it.** BuildView's machine row: "Pod · fast build (4 machines)". The job's `meta.sourcing.fanout`
   (parts, children seconds, remote spares) is in the timeline for the owner's cost page.
6. **Deploy.** video-v2 only (and the UI). No migration (render_settings is JSON). The worker image must be this
   branch or later before the switch is shown, or the input is ignored (one machine, as today).

## Verification

- Offline suite (`SKIP_DOTENV=1 python -m unittest discover -s tests -t .`): 3660 tests, only the two known
  failures (the chart test and the style_match text test). New: `tests/test_machine_sizing.py` (core count,
  sampler, network-queue waits, the tidy intermediate only where a cut follows, fast-sourcing fold / deadline / pass-1 box /
  part count, remote spares, pass-2 skip) and `tests/test_proxies.py` (early bot check no longer sidelines).
- Encode and quality measurements: two throwaway 16-vCPU cpu3c pods (live image, no secrets), deleted after.
- Live check of this branch on a throwaway 16-vCPU cpu3c pod (live image + this branch's files, the app's pod env,
  bench narration `lake_mead`, plan only, no project): 15 scenes, 0 empty (12 clips, 3 pictures), footage search
  471 s; 80 YouTube sections with the ultrafast intermediate, 16.6 s each on average (download incl. encode);
  the sampler and the network-queue waits came back in `meta.sourcing` (CPU 24% mean, p90 58%, 17 ffmpeg at
  peak; searches waited 2.5 s on average for one of the 16 network slots). Cost $0.28 (RunPod $0.10, AI $0.18).
  The "medium" half of the A/B was stopped to stay under the $0.30 AI cap; the medium encode alone takes
  7.3-11.1 s of wall time per 12 s section on an idle pod of this type (quality pod, above), which every section
  paid on top.
