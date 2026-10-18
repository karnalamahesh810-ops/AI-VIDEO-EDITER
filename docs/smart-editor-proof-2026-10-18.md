# Smart Editor proof (2026-10-18)

**Final verdict (after round 2): ready for a per-job, admin-only trial, but only once this branch is
deployed. Keep the endpoint default `SMART_EDITOR` off.**
- With the round-2 guard, Smart Editor won 2 of 3 non-weather slices (history, tech) and tied the third
  (Obama).
- None of the three round-2 renders had a defect: no named strangers, no early text, never two graphics
  at once.
- **Never enable it on the live image 81fc404.** That image still has the false-identification bug
  found in round 1.

| Slice | Round-2 verdict | Why |
|---|---|---|
| History: Bighorn Medicine Wheel (`e2f339d5`, 300.8–394.5 s) | **B better** | +4 graphics in the hook and body ("TWO STONES NEVER MEANT TOGETHER", "SINGLE DESIGN VS DIFFERENT CENTURIES", "1903 / FIRST CAREFUL DESCRIPTION", the Crow-oral-record quote); every planner picture look kept |
| Tech: desert data centres (`a197d293`, 531.0–620.9 s) | **B better** | arrow + box on "COOLING TOWERS", "THEY SWEAT", and A's double graphic at 1:13 is gone. It lost the "LAS VEGAS" place pin to a statement |
| Obama brothers (`70bc06d2`, 0–107 s), same director answer replayed | **tie (A ≈ B3)** | the 3 name labels were refused (people not in the shot) and the dossier, newsprint and 2011 are back. But the critic scored "THE OFFICIAL MYTH" and the hatred quote 4/10 (in both runs) and dropped them, so nothing was gained over A |

Round 1 (below) found the defects. Round 2 fixed them; see "Round 2" at the end for the fixes, the
spend and the open points.

---

*Round 1 (same day, live code 81fc404):*

**Round-1 verdict: keep `SMART_EDITOR` OFF and fix first.** On a non-weather slice, the Smart Editor
times every graphic exactly on its word. Its big statement cards look clearly more premium than
today's. But it **removed more information than it added**, and it **circled a stranger and labelled
him with a real person's name**. Two small fixes are on branch `feature/smart-editor-proof` (d2527f8,
offline tests, not deployed). Four more fixes are needed before it goes on. They are listed at the end.

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

---

## Round 2 (2026-10-18 evening): fixes 3–6, then three slices

### What changed (branch `feature/smart-editor-proof`: eb892b7, 4885c9e; 27 offline tests in `tests/test_smart_editor.py`, plus maps_v2 and render_cache; 109 pass)

| # | Fix | Where | Test |
|---|---|---|---|
| 3 | **Picture, date and figure looks beat plain labels.** A `label` or `spot` design with no mark is refused ("a picture or figure look holds this moment") where the planner placed a picture, file card, date or figure look. A statement still wins the room | `_edit`, step 3 guard (`held`) | `PictureBeatsLabelTests` |
| 4 | **Hook fallback.** When no design and no look starts in the first 15 s (`HOOK_BARE_S`), the planner's own hook looks come back wherever their start is free | after the restore pass (`hookFallback` in the report) | `HookFallbackTests` (fires when the hook designs are refused; not when a design lands) |
| 5 | **A name label only over the person.** `person_shown_ok` (was `person_mark_ok`) now runs when each design is timed. A `label` or `spot` naming a cast member over a shot whose metadata does not name them is refused; another kind loses only its mark | `_edit`, step 2 | `PersonShownTests` |
| 6a | **Two fonts per video.** `motionspec.apply_kit` maps every face to the kit's title face (headline) or label face (subs, kickers, pins, list rows, second lines). Figures use the kit's number face only when it is one of those two. Text is laid out in the kit's title face, so it is never sized for a narrower face | `motionspec.py` | `TwoFontsTests` (every kit × 7 fonts × 8 kinds ≤ 2 faces) |
| 6b | **The critic drops designs it scores ≤ 4** (`CRITIC_DROP_AT`), together with their sound cue (a dropped design used to leave its SFX playing). The freed moment goes back to the planner's own look there: a picture or figure look, or the words look the design had replaced | `_critic`, `_drop_smart`, the post-critic `_fit_back` | `CriticDropTests` (2 tests) |

### Material and method

- **History:** "Something About Wyoming's Bighorn Medicine Wheel No Longer Makes Sense" (`e2f339d5`), 300.8–394.5 s. That is 93.7 s and 19 scenes: the 1880s–1903 written record.
- **Tech:** "Farming Isn't Lake Mead's Newest Enemy — Data Centers Are" (`a197d293`), 531.0–620.9 s. That is 89.9 s and 18 scenes about servers, evaporative cooling towers, Google/Microsoft/Meta water reports and the Mesa Google campus.
  - The app DB has no tech project. Making one would need a sourcing run (about $0.25 OpenRouter, over the cap), so I used this purely data-centre stretch. It does come from a water-themed video.
- **Obama:** the same 107 s slice as round 1.
- **How the slices were cut:** each was cut from the saved `scene_data` on a scene boundary, then retimed from 60 to 30 fps the editor's way. The narration was trimmed with `audio.keep`: the renderer's own narration ranges.
- **Fresh vs replay:**
  - History and tech: a **fresh** director call each, on the branch code, live models, kit `noir`. The critic stills were drawn on the worker.
  - Obama: B3 = **round 1's exact director answer** replayed through the round-2 guard, plus a fresh critic. This isolates the fixes and costs no director call.
- A and B were rendered on the live endpoint with no `project_id`.

### Results

- **History:**
  - 7 designs: 1 refused as ungrounded, 6 placed. The critic scored them 5, 4, 6, 7, 4, 5, dropped 2 and moved 3. Marks: 3 grounded.
  - All 4 planner picture looks were restored: myth/fact, photo-focus map, 1880s newsprint, journal frame.
  - B adds the hook statement, the "design vs centuries" panel, "1903 / FIRST CAREFUL DESCRIPTION" (A: a bare 1903 counter) and the closing quote. **B better.**
- **Tech:**
  - 8 designs: 4 refused because their wording was not verbatim ("1M GALLONS = 3 ACRE-FEET" for "a million gallons is a little over 3 acre feet"; "INITIAL CONSUMPTION").
  - 4 placed. The critic scored them 5, 6, 5, 6 and dropped none. 1 mark grounded: an arrow and box on the cooling towers.
  - A's chip-plus-counter double graphic at 1:13 is gone. The "LAS VEGAS" place pin lost to "LEAVES THE BASIN". **B better.**
- **Obama B3:**
  - Rejected: 3 name labels (MALIK, GEORGE and KEZIA are not in their shots) and 1 label that yielded to the 2011 year.
  - The critic scored the 3 survivors 4, 4, 7 and dropped "THE OFFICIAL MYTH" and "IS HATRED EVEN THE RIGHT WORD?". Their planner line came back ("That's the official myth").
  - Net: A's looks are back (newsprint, dossier, 2011, 1958/1960) plus "1936 / BORN IN KENYA". It lost A's "October 3" (it overlapped the text card), "Harvard" and "Family name". **Tie.**
- **Hook fallback** did not fire on these slices: each had a design or a look in its first 15 s. The offline tests cover it.
- **Two fonts:** every B frame now uses grotesk headlines and narrow labels. The serif and mono mix of round 1 is gone.

### Open points (not blockers for an admin-only trial)

1. **The critic is noisy.**
   - It gave the same two graphics 5 and 4 in round 1, then 4 and 4 twice in round 2.
   - Its 4s came with fixable advice ("move-left", "panel"). With the ≤ 4 rule it removed the two graphics a human would call the best in the Obama slice.
   - Suggestion: drop at ≤ 3, or at ≤ 4 only when its fix is "drop". The other option is to apply the fix and score again (+$0.004).
   - Kept at ≤ 4 as asked.
2. **Paraphrase refusals.** Half the tech designs were refused for not being verbatim. That is correct, but it wastes the call. Tell the director in the prompt to copy the narration's exact words for figures.
3. **Words-only planner looks** (keywords, side notes) are still replaced even where no design lands, as with "Harvard". Restoring them into free room would keep density, at the cost of the template sameness the owner disliked. This is the owner's call.

### Spend

| | Round 1 | Round 2 | Cap (round 2) |
|---|---|---|---|
| OpenRouter (account usage delta) | $0.031 | **$0.039**: director $0.018, marks $0.005, critic $0.013, render vision $0.003 | $0.10 |
| RunPod | ≈ $0.13 | **≈ $0.14 by execution time (≈ $0.20 by the worker's own ledger)**: 6 renders, 5 stills jobs | $0.30 |

### Links (all on R2 `previews/`, base `https://pub-85b1063e5318421a84e390a0f0fde47c.r2.dev/previews/`)

- **History:** `smart_editor_proof_2026-10-18_history_A_045a957502a9.mp4`, `..._history_B_2d89ba49d91e.mp4`. Sheet: `..._contact_sheet_history_A_vs_B.jpg`.
- **Tech:** `..._tech_A_d23d73424daa.mp4`, `..._tech_B_ae33fdad7a91.mp4`. Sheet: `..._contact_sheet_tech_A_vs_B.jpg`.
- **Obama:** `..._obama_B3_f1aec64ac0c3.mp4`, with A and B as in round 1. Sheet: `..._contact_sheet_obama_A_B_B3.jpg`.
- **Local copies:**
  - `C:\ThumGenius\smart_editor_proof\` holds the Obama files (A, B, B2, B3, sheets, docs).
  - `history_medicine_wheel\` and `tech_data_centers\` (each: `doc_A.json`, `doc_B.json`, `smart_report.json`, `A.mp4`, `B.mp4`, the sheet, `critic\`).
  - `links.json` lists every URL.

### Ready to enable per job (admin-only `smart_editor: true`)?

**Yes, once this branch's worker code is live.**
- It is safe on all three slices.
- It is better on two and equal on the third.
- It costs about $0.02 per 90 s, or about $0.12–0.15 per 15 min. Render time is the same or less.

Steps:
1. Merge `feature/smart-editor-proof` into `thumbgenius-video-worker` and deploy (rp_update). This needs the owner's or coordinator's go.
2. Pass `smart_editor: true` from an admin-only Create Video option. The endpoint default stays off.
3. Watch the first 3–5 admin videos, and decide critic point 1 before any wider roll-out.
