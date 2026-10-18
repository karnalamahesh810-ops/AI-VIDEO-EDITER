# Smart Editor proof (2026-10-18)

**Verdict: keep `SMART_EDITOR` OFF and fix first.** On a non-weather slice, the Smart Editor times
every graphic exactly on its word. Its big statement cards look clearly more premium than today's. But
it **removed more information than it added**, and it **circled a stranger and labelled him with a real
person's name**. Two small fixes are on branch `feature/smart-editor-proof` (d2527f8, offline tests,
not deployed). Four more fixes are needed before it goes on. They are listed at the end.

## What was rendered

- **Material:** app project `70bc06d2` "Why Barack Obama's Brothers HATED Him So Much" (biography, built
  2026-10-07). The test uses its first **107.1 s** (frames 0–3212, 16 scenes, ending on a cut). The
  timeline is the saved `scene_data`, with the same clips, pictures, narration (the project's long-lived
  signed audio link), music and grade.
- **A** = that timeline as the planner made it: 11 graphics, which is what users get today.
- **B** = the same timeline after `smart_editor.edit()`:
  - live code 81fc404, same models as the endpoint (`google/gemini-3.8-flash` director and critic,
    `google/gemini-2.5-flash` marks);
  - kit `noir` (`brandkits.choose`: the project has no video style);
  - the critic's stills were drawn by the **deployed worker** (a tiny render job), as
    `render_stills_worker` does.
  - The editor ran on the laptop because it only exists inside `timeline._build` (plan stage). A
    worker plan job would have re-sourced the footage and broken the A/B.
- **B2** = B's exact director answer (no new model call) replayed through the fixed guard on this branch,
  then the real critic again.
- All three were rendered on the live serverless endpoint `tuxcziwby5plod` (image 81fc404). The
  render action had no `project_id`, so nothing was written to the app DB. No endpoint or template env
  was changed, nothing was recycled, and nobody else's job was touched.

## Links

| | R2 (`previews/`) | local (`C:\ThumGenius\smart_editor_proof\`) |
|---|---|---|
| A (off) | https://pub-85b1063e5318421a84e390a0f0fde47c.r2.dev/previews/smart_editor_proof_2026-10-18_A_0b71430baade.mp4 | A.mp4 |
| B (on, live code) | https://pub-85b1063e5318421a84e390a0f0fde47c.r2.dev/previews/smart_editor_proof_2026-10-18_B_d8d43b6ecf4f.mp4 | B.mp4 |
| B2 (on + fixes) | https://pub-85b1063e5318421a84e390a0f0fde47c.r2.dev/previews/smart_editor_proof_2026-10-18_B2_657253704748.mp4 | B2.mp4 |
| Sheet A/B/B2 | https://pub-85b1063e5318421a84e390a0f0fde47c.r2.dev/previews/smart_editor_proof_2026-10-18_contact_sheet_A_B_B2.jpg | contact_sheet_A_B_B2.jpg |
| Sheet A/B | https://pub-85b1063e5318421a84e390a0f0fde47c.r2.dev/previews/smart_editor_proof_2026-10-18_contact_sheet_A_vs_B.jpg | contact_sheet_A_vs_B.jpg |

The same folder also holds:
- the timelines: `doc_A.json`, `doc_B_precritic.json`, `doc_B.json`, `doc_B2.json`;
- the Smart Editor report: `smart_report.json`;
- the worker results: `render_*_result.json`;
- the critic stills: `critic/`, `critic_b2/`.

The harness scripts are in this session's scratchpad: `se_env.py`, `se_edit.py`, `se_critic.py`,
`se_replay.py`, `se_render.py`, `se_sheet*.py`, `se_timing.py`, `se_publish.py`.

## Side by side (8 matched timestamps)

| t | A (off) | B (on) | Better |
|---|---|---|---|
| 0:03 | "October 3 / 1992" date chip **over** the scene's text card (2 graphics at once) | text card only; the hook has no smart graphic until 0:15 (both hook designs were refused: "WEDDING DAY" is not in the narration) | A (richer) / B (cleaner) |
| 0:18 | photo-focus look (dimmed footage) | "MALIK OBAMA" lower-third over a debate crowd he is not identifiable in | neither |
| 0:29 | "George" newsprint card, **2.1 s early** | **circle on an anonymous man carrying tyres + "GEORGE OBAMA / NAIROBI, KENYA"**. The photo is a 2013 *New Humanitarian* slum feature: this is a false identification | **A** (B is a serious defect) |
| 0:40 | small "That's the official myth" | big "THE OFFICIAL MYTH" + "THE PAPERWORK READS COLDER", brackets, gold accent (critic moved it off the face) | **B** |
| 0:46 | "2011" flip counter | nothing: the date was dropped | **A** |
| 1:00 | nothing | "IS HATRED EVEN THE RIGHT WORD?" serif quote, but over the speaker's forehead (moved below the face in B2) | **B** (B2) |
| 1:17 | "LAKE VICTORIA 1936" with a 1936–2011 line | "1936 / BORN IN KENYA · BARACK OBAMA SR." | tie (B cleaner) |
| 1:33 | "WHO IS – KEZIA AYOKO – Obama Sr.'s first wife (customary)" file card with photo, **2.1 s early** | plain "KEZIA AYOKO" name pill over a village shot | **A** |

**Score: A 3, B 2, 1 tie, 2 neither or split. B also has one defect that must never ship** (naming a
stranger).

### What B adds

- **Exact timing.** All 7 designs start within 0.01 s of their word, against 2 of A's looks that
  started 2.1 s early (George, Kezia: a break of the graphics-timing rule). There is never more than one
  graphic at a time; A put two on screen at 0:00–0:06.
- **Premium statement and question cards** in one brand kit. The B frames at 0:40 and 1:00 are the best
  graphics in this test.
- **One SFX per graphic**: paper-slide, camera-flash-pop, hit-deep, stamp, reverse-swell, count-tick,
  ui-pop. Loudness is unchanged (all three are −14.0 LUFS after the render's normalise).
- **3 more cut transitions**: shutter, crossfade, soft-whip.
- **The critic**: it reviewed all 7 graphics and repositioned 3–4 of them (off faces, smaller, a glass
  panel).

### What B breaks

1. **A false identification.** The mark pipeline asked vision to find "one man carrying tires", found
   him, and labelled the circle with a cast member's name. Nothing checked that the shot shows that
   person. **Fixed** (see below).
2. **Information loss.** It dropped 10 of 10 planner looks in its span and added 7.
   - Lost: the 2011 and 1958/1960 dates, the who-is file card, the newsprint card and the photo-focus
     look.
   - The director never used `keep` for photo cards. Picture looks were kept only if no new design
     overlapped them, and dates and years counted as "words only", so they were always dropped.
     **Dates partly fixed** (see below).
3. **An empty hook**: 0–15 s has only the scene's text card. The director's hook designs used words that
   are not in the narration ("WEDDING DAY"), so the guard refused them, correctly. Nothing replaced them.
4. **Name labels over unrelated shots**: MALIK OBAMA over a crowd, GEORGE OBAMA over strangers (still
   there in B2 without the circle). This is softer than the circle, but a lower-third reads as "this is
   him".
5. **Text over faces**: "THE OFFICIAL MYTH" and the hatred quote, before the critic moved them. The
   critic catches some of these.
6. **Weak design scores and font mixing.** The critic's own scores were 6, 4, 5, 6, 4, 7, 6 (mean
   5.4/10); B2 got 6, 6, 4, 6, 3, 7, 6. It uses six fonts in 100 s: kinetic, mono, serif, serif-italic,
   narrow, grotesk. That is not the clean editorial system the owner asked for (no-yellow-outlined rule:
   "clean white editorial type + small gold accent").
7. **No wrong facts in the text itself.** All the words and figures were grounded in the narration; the
   ground check refused 2 designs.

## Time and money

| | A | B | B2 |
|---|---|---|---|
| Smart Editor pass | – | 71.8 s wall: 1 director call, 2 mark calls, critic stills job 22 s, critic call | replay + critic 40 s |
| Smart Editor $ (OpenRouter, ledger) | – | $0.0144 + critic $0.0069 = **$0.021** | critic $0.0067 |
| Render on the worker (exec) | 170 s | 134 s | 129 s |
| Render $ (worker ledger) | $0.045 | $0.034 | $0.034 |

- B is **not slower to render**: its SMART_SPEC overlays cost no more than the planner's library looks.
- For a full video, the Smart Editor costs about **$0.12 per 15 minutes** for the director and marks,
  plus about $0.007 for the critic and about $0.004 of stills machine time. That is in line with the
  ~$0.10–0.15 estimate.

**Total spend for this proof:**
- RunPod ≈ **$0.13**: 3 renders, 3 stills jobs and 2 failed harness jobs, plus boot. The cap was $1.50.
- OpenRouter ≈ **$0.031**: the account's usage went up by $0.0309 during the test. The cap was $0.30.

## Fixes on `feature/smart-editor-proof` (d2527f8, offline tests in `tests/test_smart_editor.py`, 18/18 pass)

1. **`person_mark_ok`**: a mark whose label or text names a story person (`story.cast`) is placed only
   when the shot's own metadata names that person.
   - The metadata checked: contentDescription, attribution and title.
   - It matches on the distinctive part of the name ("george", not the shared "obama"). A person known
     only by a shared name, such as Barack Obama vs Barack Obama Sr., is checked on the whole name.
   - Otherwise the circle is dropped (push-to-point becomes push-in) and the graphic stays. No vision
     call is spent on it.
   - In B2 the George circle is gone.
2. **Restore pass**: figure looks (`kt-year/date/number/percent/money/price`, `pr-number-reveal`) and
   picture looks that the director did not redesign now come back.
   - A look returns wherever its own start is free, cut before the next graphic, with at least 2 s
     left.
   - In B2 "2011" (cut to 3.6 s) and "1958 / 1960" are back. The Kezia file card still does not fit:
     only 1.7 s is free before the director's label.

## Still to fix before turning it on

3. **Picture looks beat plain labels.** A label or spot design without a mark must never displace a
   picture or file look (dossier, newsprint, photo cards). The director prompt should also put those
   looks in `keep`.
4. **Hook fallback.** When the hook's designs are refused, keep the planner's hook looks, or ask once
   more for verbatim words.
5. **Name labels need the person in the shot.** Apply the same `person_mark_ok` test to label and spot
   kinds that name a person. If the person is not in the shot, use an upper or centre statement
   instead of a lower-third.
6. **The kit pins two fonts.** Limit fonts to the kit's headline and label pair, and make the critic
   drop designs scored ≤ 4 instead of only moving them.

**Recommended next step:**
1. Build fixes 3–6 on this branch, with offline tests.
2. Re-run this same harness on this Obama slice and on one tech and one history slice: about $0.05
   OpenRouter and $0.15 RunPod.
3. If B wins on all three, turn it on per job first, which already works with job `"smart_editor": true`.
   This would be an admin-only "Smart graphics" option in Create Video. Only after that would it become
   the default.
4. Until then, leave `SMART_EDITOR` off on the endpoint. Nothing is deployed from this branch.
