# Pod sourcing speed (2026-10-26)

Branch `fix/pod-sourcing-speed` (worker). Not merged, not deployed.

The owner asked why the Hoover Dam video (project 82e7cae1, pod job pod-c7z9rr7fcbwxrg, 16 vCPU cpu3c,
$0.48/h, option B) took so long. The footage search took 44 of its 47 build minutes.

## Where the time went

_FILLED FROM THE JOB'S scene_data.meta AND video_job_events BELOW._

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

_Measurements / estimate below._

## App spec: "Fast build" toggle (not built; the app is not edited in this branch)

Worker side is ready (`fast_sourcing` in the job input). The app needs:

1. **Setting.** `render_settings.fast_build: boolean` (default false), saved like `run_on`
   (`useCreateVideo.ts`: `fastBuild = settings.fast_build === true`, `setFastBuild(v) => setSetting({ fast_build: v })`).
2. **UI.** `src/components/createvideo/create/MoreOptions.tsx`, a `SettingRow` next to "Machine":
   name **"Fast build (+$X)"** (X from the table below for the video's length, e.g. "+$0.30" for 15 min;
   for customers shown in credits, see 4), hint **"Finds the footage on 4 machines: about N minutes sooner"**,
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

- Offline suite (`SKIP_DOTENV=1 python -m unittest discover -s tests -t .`): 3655 tests, only the two known
  failures (the chart test and the style_match text test). New: `tests/test_machine_sizing.py` (core count,
  sampler, network-queue waits, the tidy intermediate only where a cut follows, fast-sourcing fold / deadline /
  part count, remote spares).
- Encode and quality measurements: two throwaway 16-vCPU cpu3c pods (live image, no secrets), deleted after.
- Live check of this branch on a throwaway 16-vCPU cpu3c pod (live image + this branch's files, the app's pod env,
  bench narration `lake_mead`, plan only, no project): 15 scenes, 0 empty (12 clips, 3 pictures), footage search
  471 s; 80 YouTube sections with the ultrafast intermediate, 16.6 s each on average (download incl. encode);
  the sampler and the network-queue waits came back in `meta.sourcing` (CPU 24% mean, p90 58%, 17 ffmpeg at
  peak; searches waited 2.5 s on average for one of the 16 network slots). Cost $0.28 (RunPod $0.10, AI $0.18).
  The "medium" half of the A/B was stopped to stay under the $0.30 AI cap; the medium encode alone takes
  7.3-11.1 s of wall time per 12 s section on an idle pod of this type (quality pod, above), which every section
  paid on top.
