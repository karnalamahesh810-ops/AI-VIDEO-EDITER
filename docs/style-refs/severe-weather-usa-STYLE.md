# Severe Weather USA — measured style spec

Channel: [Severe Weather USA](https://www.youtube.com/@SevereWeatherUSA) (UC_opcefdzIh27TitnW4_WTw).

- 56.2K subscribers, 18.4M views, 103 videos. Joined 2025-05-20.
- Uploads daily, often several a day.
- Its About page says the narration is an AI voice.

Measured 2026-10-26 on a RunPod CPU pod. Nothing heavy ran on the laptop.

## What was measured

**Scripts:** the transcripts of the 10 newest uploads (2026-10-17 to 10-25):

- ec1p58S7Hps, MJhw1P6zaxw, v9-4pibGMgA, _-znsyzSOJI, q5goRQMQEPQ
- 5rRoGF-N67A, S1r_fvG52qE, xJkXqqsYnE0, -UOJx-hbjpI, _9du-eq6nJY

**Pictures and sound:** eight full videos at 1080p. Five are recent and three are top performers:

| Video | Topic | Views |
|---|---|---|
| ec1p58S7Hps | NM/CO floods | 191K |
| q5goRQMQEPQ | Arizona hail | 643K |
| S1r_fvG52qE | Alaska snow | 78K |
| _9du-eq6nJY | Bryson fire | 71K |
| MJhw1P6zaxw | San Juan record | 264K |
| hmejzMwPnAw | Nor'easter, top | 1.6M |
| bgCRwtHedSs | Hurricane Rachel | 881K |
| N3fhL7zqyOk | Western snow | 523K |

**How it was measured:**

- **Cuts:** frames every 0.25 s, with a dissolve-aware boundary test.
  - A boundary counts where the picture 1.5 s apart changes in both layout and colours, while the change on either side stays low.
  - The worker's own Style Match pass missed most of this channel's dissolves.
- **Crossfade length:** measured frame by frame at 30 fps, as the mix ratio between the two shots.
- **Watermark:** the median of 240 frames spread over each video.
- **Audio:**
  - EBU R128 loudness.
  - Spleeter voice/accompaniment separation on 6 × 30 s windows per video.
  - Voice pitch from autocorrelation on the voice stem.
- **Shot sheets:** in the session scratchpad `swusa/m2/` (`*_s2_*.jpg`).
- **Raw numbers:** `swusa/m2/*_shots_k.json` and `*_m2.json`.

## Script formula (10 transcripts)

| | Measured |
|---|---|
| Length | 12:50–19:11, about 13–19 min |
| Words | 1,970–3,120 |
| Pace | **150–166 wpm**, median 160. Narration runs non-stop, with no pauses for clip audio. |
| Person | First person singular: "I'm breaking down…", "I'll be watching…", "I want to flag…". Between 1 and 12 "I"s per video. |
| Footage named in narration | Almost never. 0–4 mentions of "video", "footage" or "you can see" per video. The clips illustrate the place and event; the voice never introduces a clip. |
| Sources named | The NWS office by name, 9–46 times per video: "NWS Albuquerque", "the National Weather Service in Fairbanks". |

The structure is the same in every video:

1. **Hook, 15–30 s.** Opens with "Right now…" or "[Event] is [verb]-ing…". Gives the headline numbers (record crest, homes evacuated, inches of snow). Ends on a forward pull: "and the worst is still ahead", "a second storm is already…".
2. **Date and scope line.** "Welcome back. Today is Sunday, the 25th of October 2026" or "This is your complete Alaska weather forecast for Monday, the 19th of October, 2026". Then a promise: "I'm covering every active NWS warning, the river data, the rescues and the full forecast."
3. **Cause.** "Let's start with the cause": the storm system, moisture source or setup.
4. **Warnings, region by region.** "Let me walk you through the active NWS warnings…", "Moving into New Mexico…", "Now let's head to Colorado". Each warning gets its office, river or zone, crest, flood stage, record and end time. This is the bulk of the video.
5. **Human impact.** Evacuations, outages, closures, infrastructure.
6. **Rescues and officials.** National Guard numbers, governors' declarations.
7. **Day-by-day forecast.** "So what happens from here? Let's go day by day". Today, then Monday, Tuesday and so on, with city highs and rain chances named one by one.
8. **Late-week flag.** "Now, I need to flag something important…", followed by the next system.
9. **Key takeaways.** Sometimes "four key takeaways: First… Second…".
10. **Sign-off.** "If this coverage was helpful, please hit like, subscribe and turn on notifications… My thoughts are with every family in [towns]… I'll see you in the next one. Stay safe."

## Voice

- **Gender and tone:** female, calm and steady, newsreader-like.
- **AI:** declared on the About page.
- **Pitch:** median F0 196–211 Hz across all 8 videos, so it is one voice. p10/p90 is about 184/230 Hz.
- **Delivery:** very even. Loudness range (LRA) is 2.0–2.4 LU.
- **Loudness:** integrated −32 to −34 LUFS, which is very quiet. Ours stays at the worker's normal −16 LUFS. Their low level is not a style choice worth copying.
- **Closest voice we have:** ThumbGenius voice preset `doc-female`. Speed 1.0 lands at roughly their pace; check the words per minute after making the voice-over.

## Music, SFX and clip sound

- **No music.**
  - The accompaniment stem drops to −69 to −92 dB between words.
  - Where it reads −69 dB, it is a constant noise floor, about 35 dB under the voice.
- **No sound effects**, whooshes or stingers.
- **No clip audio.** The narration only.

## Pictures

### Pacing (8 videos)

| | Range | Typical |
|---|---|---|
| Shot length, median | 5.0–9.6 s | ~7 s |
| Shot length, mean | 6.5–15.8 s | ~10 s |
| Shot p10 / p90 | 2.9–4.2 / 10–33 s | 3.5 / 16 s |
| Longest shot | 25–130 s | Usually a Windy recording or a reposted social montage |
| Cuts per minute | 3.8–9.1 | ~6 |
| First 60 s | 7–12 shots | No faster than the rest. No cold-open montage, no title card, no logo sting. |
| Transitions | 60–100% cross-dissolves, median 97% | Dissolves run **~0.6–0.7 s** (17–19 frames at 30 fps). No flashes, whips, zooms or glitches. |
| Camera moves | None added | Photos and graphics are held still. |

### Footage mix

Share of runtime, from the classifier plus eyeballed sheets. Windy detection is approximate.

| Type | Share | Notes |
|---|---|---|
| Eyewitness and social clips | 40–75% | Phone video of the named towns, drone, dashcam, storm-chaser clips. Many are reposts of TikTok/IG compilations: their burned-in caption ("Shiprock, NM 10/24/26", white bold with a black outline, top centre) and their internal cuts are kept. Some local TV "FILE" clips. |
| …of which vertical, on a blurred copy of itself | 17–60% of all time (median ~34%) | Centre band fitted to height, heavy gaussian blur of the same clip filling the sides, not darkened. |
| News still photos | ~5–15% | Held still, 2–6 s. Often three in a row in the hook (photo, photo, photo). |
| NWS / NOAA graphics | 5–20% | See below. |
| Windy.com forecast-model screen recording | 4–31% | Full UI, played through the timeline. |

The NWS / NOAA graphics are:

- the office's own briefing slides (pdf decks, "Winter Storm Products", "Expected Storm Total Snow");
- graphicasts ("Flash Flood Watch — Noon Today Until Midnight Tonight");
- the office "Watches, Warnings & Advisories" county map (weather.gov/wwamap);
- SPC and WPC outlooks;
- the WPC surface analysis.

These are held 5–11 s. A 16:9 slide fills the frame; a squarer map is fitted to height on a blur of itself.

The Windy recordings show temperature, rain/thunder, radar, satellite and wind layers. They come either as one long block under the forecast section (last ~20%: 692 s to the end of a 14:24 video) or as 30–60 s inserts mid-video.

### On-screen text the channel adds

- **Only a watermark.** "Severe Weather USA" sits dead centre, measured from the 240-frame median:
  - centre x 0.50, y 0.496;
  - the line about 35% of the frame's width, letters about 5.6% of its height;
  - a condensed bold sans (closest free match: Oswald 700);
  - white at about 25–30% opacity with a faint shadow;
  - on every frame, maps included.
- **No other channel text:** no location labels, date cards, lower thirds, captions, credits or subscribe prompts.
- **Text inside the footage:** source captions, TV chyrons and "FILE" bugs are left in.

### Thumbnails and titles

- **Title formula:** 🚨 + "[Place] [Event noun]" + "|" or ":" + three hard figures joined with commas and "&".
  - "🚨 New Mexico Flood Disaster | San Juan River Breaks 117-Year Record & 1,500 Homes Evacuated"
  - "🚨 Arizona Storm Disaster | Golf-Ball Hail, Major Flooding & Tornado Threat"
- **Vocabulary:** Disaster, Crisis, Slams, Hits, Hammer, Threatens. Figures: inches, mph, feet, homes, outages, millions.
- **Description:** one paragraph restating the title with the towns, then 7 hashtags. The tags list the state, its cities and generic weather terms.
- **Thumbnails:** a dramatic event photo, usually aerial flooding or a storm, with big bold outlined figure text. The tool's thumbnail tools already cover this; it was not part of this build.

## Gap table — reference vs ThumbGenius

"Before" is what our closest styles did. `news_compilation` / `nature_weather` were built from this same channel's Nor'easter videos in September. "Now" is the new `severe_weather` style (worker branch `feature/severe-weather-style`).

| Element | Reference | Before | Now (severe_weather) |
|---|---|---|---|
| Shot length | median ~7 s, mean ~10 s, p90 16 s | median 5.3 s, every shot capped at 7 s | median target 7.5 s, cap 12 s (the shot cap's ceiling for every style); long takes continue the same clip (CHAIN_MAX 4) |
| Hook pace | same as the rest | 1.2–1.25× slower, plus Hook Booster cuts | 1.0×, Hook Booster off |
| Transitions | ~97% dissolves of ~0.65 s | 80% dissolves of 0.5 s (plus pack flashes in Nature & Weather) | 80% dissolves of 0.5 s, no pack transitions. The share and length differ slightly; see "Still different". |
| Vertical clips | blur-fill, ~34% of the time | blur-fill | blur-fill, same |
| Footage | eyewitness clips of the named towns, recent | same sourcing (eyewitness searches, region blocks, recent first) | same, plus clips-first, 4 rungs |
| Stills | news photos 2–6 s, held still | up to 8–12 per 10 min, Nature & Weather held still | up to 10 per 10 min, held still, never AI |
| Forecast section | Windy recording, 30–180 s block | a 6 s forecast-map card at most every 75 s, with a big title | **forecast block**: the forecast lines play over our own model map (rain, wind or new temperature view), one view per day the voice names, day chip, no title, the cities' spoken highs on the map |
| NWS office graphics | 5–20% | GOES satellite loop only | not yet (see "Still different") |
| Watermark | channel name centred, ~28% white, condensed bold | none | **channelMark**: the job's channel name, Oswald 700, 28%, centred (job input `channel_watermark`) |
| Other text | none | dates and figures (minimal density) | none: the pass keeps only the forecast maps (and source tags if the job asked for them) |
| Music | none | on (owner rule, Sept 30) | on, ducked: the owner's standing "music under every style" rule. A job's `bgm: false` matches the reference exactly. |
| SFX | none | some | none (`sfx: false`) |
| Punch-ins / editing v3 | none | editing v3 punch-ins and splits | editing v3 off for this style |
| Voice | AI female, ~160 wpm, flat | whatever the user picks | the user's pick; closest preset is the ThumbGenius `doc-female` voice (not auto-selected yet) |
| Script | fixed 10-part formula (above) | any script | the formula is documented here; the app has no script template for it yet |

## Still different (follow-ups)

1. **NWS office graphics.** These are the reference's second-biggest picture type.
   - Live sources exist and are public domain:
     - weather.gov/wwamap/png/{wfo}.png;
     - SPC day 1–3 outlooks;
     - WPC excessive-rain and QPF maps;
     - office graphicasts (often stale).
   - The WWA map is only 354×274, so it can't fill the frame without upscaling (the owner's rule).
   - The right build is a crisp vector "NWS warnings map" drawn from api.weather.gov alert polygons, plus SPC/WPC maps framed at native size on a blur. Not built today.
2. **Dissolve length and share:** 0.65 s and ~97% in the reference, against our fixed 0.5 s and 80%. These are renderer and chunk-split constants (Main.tsx, fanout.py, timeline.py); changing them per style touches the split render, so it was left for a careful change.
3. **Shots over 12 s:** the reference holds clips 20–100 s; we cap at 12 s and chain the same clip.
4. **Real Windy recordings:** we draw our own model-style map from city figures and a synthetic field. It is not Windy's real model data or UI; we deliberately don't copy their branding. Real model fields (NOAA GFS/NBM) would be the next step.
5. **Script template in the app:** the 10-part formula above could become a script preset ("Severe weather update").

## Test video (2026-10-26)

The owner's own Lake Mead narration ("Lake Mead hit 1,037.16 feet on Thursday", 18:33), built entirely on the laptop at the owner's request.

- **Video:** https://pub-85b1063e5318421a84e390a0f0fde47c.r2.dev/previews/severe-weather-usa/lake_mead_severe_weather-eace1a612868.mp4 (1080p, 4.5 Mbps web copy)
- **Side-by-side, first 30 s:** https://pub-85b1063e5318421a84e390a0f0fde47c.r2.dev/previews/severe-weather-usa/side_by_side_lake_mead-2719ca11b65a.mp4
- **Result:** 129 shots, median 8.0 s, 83% crossfades. Real video 47% of screen time, pictures 49%, graphics 4%. The forecast block ran 133 s over 12 views. Watermark "US Weather Alert". Narration only (no music or SFX in the laptop render).
- **Shot check:** every shot was checked by eye before the render, and 33 were swapped:
  - a YouTuber selfie;
  - other creators' text and graphics;
  - another channel's watermark;
  - an AI-looking render;
  - 13 repeats;
  - 8 full-screen number graphics.
- **Cost:** $1.83 OpenRouter (account-measured) and $0 RunPod.
- **Laptop time:** 4 h. That includes two harness mistakes, about 35 min plus $0.49; a clean laptop run is about 2.5-3 h.

| Element | Score /10 | Why |
|---|---|---|
| Pacing | 9 | median 8.0 s vs ~7 s |
| Transitions | 7 | 83% dissolves of 0.5 s vs 97% of 0.65 s |
| Footage mix | 4 | 47% clips (reference 40-75%), but 49% pictures vs their ~10%. Laptop downloads are bandwidth-bound. |
| Vertical blur-fill | 8 | as the reference |
| On-screen text / watermark | 9 | only the watermark. One creator graphic (before/after arrow, ~8:00) slipped through. |
| Forecast block | 7 | our own model map with the spoken day chips; not Windy's real data |
| Sound | 10 | narration only, as theirs |
| NWS office graphics | 2 | not built yet |
| **Overall** | **~7** | |
