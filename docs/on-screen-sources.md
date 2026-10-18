# On-screen sources

When the narration states a fact and we know where it comes from, a small citation chip shows in the low left
corner for about 4 seconds, for example "SOURCE: NOAA, 2024", "SOURCE: FBI" or "SOURCE: U.S. CENSUS BUREAU". It
works for every niche: history, finance, tech, science, true crime, sports and health, not only weather.

The feature is off by default until the owner approves the look from the sample stills.

## Switches

| Switch | Where | Effect |
| --- | --- | --- |
| `ON_SCREEN_SOURCES` | worker env, or job `config` | Turns the tags on (default `false`). |
| `SOURCE_TAGS` | worker env, or job `config` | The older name for the same switch. Either one turns the tags on. |
| `on_screen_sources: false` | top-level job field | Off for this job, whatever the flags say. |
| `on_screen_sources: true` | top-level job field | On for this job. |
| `SOURCE_TAG_GAP` | env / `config` | At most one tag per this many seconds (default 45). |
| `SOURCE_TAG_FIRST_SECONDS` | env / `config` | No tag in the opening hook (default 5). |
| `SOURCE_TAG_SECONDS` | env / `config` | Time on screen (default 4; the planner never shows one under 3 s). |
| `SOURCE_TAG_FOLLOW_SECONDS` | env / `config` | How late a tag may land after its word when another graphic is in the way (default 5). |

The job field is folded into the job's `config` at the start (`sources.fold_job_switch`), so parts and pods of
the same job read the same answer.

## Where a source comes from (never invented)

The planner uses only two sources of truth. It makes no model call and never guesses.

1. **The narration names it.** For example: "according to the FBI…", "a 2023 Pew Research Center survey found…",
   "researchers at Stanford University found…", "a study published in Nature…", "Guinness World Records
   confirmed…". `src/sources.py find()` reads the attribution with fixed rules:
   - It knows more than 120 bodies across niches by name and acronym (agencies, journals, leagues, analysts,
     newsrooms). It also accepts any capitalised organisation name ("… Institute", "University of …",
     "… Museum").
   - The year is shown only when the line says it of that source.
   - These get **no tag**: "experts say", "studies show", "according to police", an agency doing something
     ("the FBI arrested him"), a person, a year still to come, and a figure with nobody named.
2. **The script's own research**, when the job carries it. A line that states a researched fact gets that fact's
   source (`match_research`). To count as stating the fact, the line must:
   - say the same figure, within 2.5 % to allow for rounding ("230 million" matches a fact of 231 million), and
   - share at least 2 of the words the fact is about. A count under 13 needs 3 shared words, and so does a year
     on its own.

   Some facts are never cited from research:
   - facts marked `"confidence": "medium"`,
   - sources whose only name is a web address,
   - facts with no figure or date to recognise them by.

   Each fact is cited at most once.

When a line names its own source, that source wins over the research. A line with no known source gets no tag.

### Job contract: `research` (optional)

This is the app's script writer v2 shape (`supabase/functions/_shared/scriptV2/facts.ts`), passed as-is. The worker
also accepts the key `script_research`.

```json
"research": {
  "facts":   [{"id": "F1", "text": "The Great Fire of London destroyed 13,200 houses in 1666",
               "number": "13,200", "when": "1666", "source": "S1", "confidence": "high"}],
  "sources": [{"id": "S1", "org": "Museum of London", "title": "The Great Fire", "url": "https://…",
               "date": "2016-09-02"}]
}
```

- **Tag text:** the source's `org`. A known body is shown by its short form, for example "Federal Bureau of
  Investigation" becomes "FBI".
- **Year:** taken from the source's `date`, and only if that year is not in the future.
- **Fact `source` field:** either a source id or the organisation's name.
- **Kept away from models:** the research is held outside the story brief, so it never adds tokens to any model
  call.
- **Not yet sent by the app:** `video-v2` does not pass `research` today. Until it does, only the narration-named
  path works.

## Placement rules (`treatments._source_tags`)

- **Timing:** the tag lands on its word: the source's name, or the figure for a research tag. It may appear up to
  2 frames early, never more. It stays 4 s.
- **Spacing:** never in the first 5 s, and at most one tag every 45 s.
- **One graphic at a time** (the owner's rule):
  - A tag never shares the screen with another overlay, and a breath is kept between them.
  - If the fact's own number or date look is up when the word is said, the tag waits and lands as that look
    leaves. This is never before the word, and at most 5 s after it. Later than that, the tag is left out.
  - A tag that cannot get 3 s before the next graphic is left out, never squeezed in.
  - The audit row (`doc.meta.sourceTags` / `plan.sources`) marks these delayed tags with `afterGraphic` and
    `saidAt`.
- **Where it never goes:**
  - on an animation scene or a full-screen graphic,
  - on a presenter scene,
  - in a news compilation (`graphics_density` minimal),
  - while the brand kit leaves the look out or the owner has banned it.
- **Corner:**
  - It goes in the brand watermark's opposite corner when the watermark sits low left.
  - `settle()` moves it off a face (to the other low corner) or leaves it out.
  - With captions on, it sits above the caption strip.

## The look (`LibSourceTag.tsx`, look id `src-tag`, template `LIB_SRC_TAG`)

- **Chip:** a small dark glass chip in the low left corner, 96 px from the side and 88 px from the bottom at 1080p.
  The glass is `rgba(8,10,14,.70)` with a 12 px backdrop blur, a hairline edge and a soft shadow.
- **Accent rule:** one 3 px rule in the video's **brand accent** runs down the chip's corner edge.
- **Text:** white tracked caps in Inter Tight, 26 px at 1080p (caps about 19 px, 2.6 % of the frame height).
  - "SOURCE:" is 78 % white at weight 600, the name is full white at 700, and the year is 86 % white.
  - At a 480p preview the text is about 12 px and still readable over a white sky.
  - A long name shrinks to fit 42 % of the frame width, down to a minimum of 20 px.
- **Motion:**
  - In: 7 frames (233 ms), a fade plus a 14 px slide from the corner on a cubic ease-out. The rule grows down
    over frames 0–6.
  - Out: 5 frames (167 ms), a cubic ease-in.
- **Rendering:**
  - `Main.tsx` draws the chip without `MotionWrap`. The wrapper's fade would stretch the entry, and its opacity
    would stop the glass from blurring.
  - The chip is silent and loads no picture, so the SafeImg rule does not apply.

**References:** none of the catalogued reference channels shows a standalone citation chip (the
`docs/style-refs` celeb set, `runpod/docs/reference-catalog.md`, the VidRush notes). Only the reference
catalogue's percent gauge has a "source line below". So the size follows the existing data-graphic source line
(`SourceLine`, same font family and tracking), made about 8 % larger to work at 480p, plus the glass chip from the
owner's brief. Before the look is final, a side-by-side against a channel the owner picks is still owed.

## Sample frames

- **Contact sheet:** `docs/style-refs/on_screen_sources_sheet.jpg`. The panels are:
  - top row, 1080p: bright sky, busy picture, right corner with a long name and year;
  - bottom row: frame 3 of the entry (1080p), then bright and busy at 480p.
- **Full-size PNGs:** the session scratchpad `oss/stills/` (`tag_1080_*.png`, `tag_480_*.png`).
- **How they were made:** `npx remotion still` with `oss/make_props.py`. Picture-only stills work on the laptop
  despite Smart App Control, because no compositor or ffprobe is needed.

## Tests (offline)

`SKIP_DOTENV=1 python -m unittest discover -s tests -t .` from `runpod/`.

- **`tests/test_on_screen_sources.py`:**
  - Claude-written narration for 7 niches: named sources, unnamed facts, research matching, and the
    never-invented cases.
  - Whole-script plans with every other graphic on. These check: hook-free, 45 s spacing, 3–5 s on screen, never
    before the word, never overlapping, and labels only from the allowed set.
  - The switches.
- **`tests/test_source_tags.py`:** the earlier detection and settle tests, updated to the new timing.

## Copying into the editor app (do not forget)

The app keeps a renderer copy in `C:\ThumGenius-app\src\remotion`. Copy:

- `runpod/remotion/src/components/lib/LibSourceTag.tsx` to `src/remotion/components/lib/LibSourceTag.tsx` (the
  whole file).
- `runpod/remotion/src/Main.tsx`: only the `src-tag` branch in `renderOverlay`, just before
  `let ov = resolveOverlay(raw);`.
- `runpod/remotion/src/templates/registry.json` to `src/remotion/templates/registry.json`. Only the `LIB_SRC_TAG`
  description and its 4 s duration changed.

## Turning it on

1. The owner looks at the sample sheet and approves the look, or asks for changes.
2. To test one job, pass `{"config": {"ON_SCREEN_SOURCES": true}}`. To make it the default, set the env var
   `ON_SCREEN_SOURCES=1` on the endpoint or template (a deploy step for the owner).
3. Optional: have `video-v2` pass the script's `facts` and `sources` as `research`, so research-backed lines get
   tags even when the narration does not name the source.
