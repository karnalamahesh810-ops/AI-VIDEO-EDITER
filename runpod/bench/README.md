# Footage benchmark

Seven one-minute narrations, one per kind of story the product targets, with
the entities and places a correct edit must show:

| case | kind | what a correct edit shows |
| --- | --- | --- |
| lake_mead | weather, current | Lake Mead, Hoover Dam, Colorado River, Las Vegas intake |
| california_wildfire | disaster, Jan 2025 | Palisades and Eaton fires, Altadena, Cal Fire |
| new_mexico_flash_flood | weather, Jul 2025 | Ruidoso, Rio Ruidoso, South Fork burn scar |
| wwii_midway | history, 1942 | Battle of Midway, USS Yorktown, Akagi, Nimitz |
| locomotive_big_boy | explainer, 2019 | Union Pacific Big Boy 4014, Cheyenne, Sherman Hill |
| biography_obama | biography, 1961-1996 | Barack Obama, Ann Dunham, Punahou, Occidental, Columbia |
| technology_iphone | history, 2007 | Steve Jobs, Macworld, Moscone Center, first iPhone |

`cases/<name>.json` holds the narration and the expected entities;
`audio/<name>.mp3` is the narration read by a Windows voice (the voice does
not matter: whisper aligns it, the footage search does the rest). The audio
is copied into the worker image, so a benchmark job sends
`audio_url: "bench://<name>"` and needs no upload and no credentials.

## Running

```bash
python scripts/bench.py --label "A: pool on"                       # all seven, current settings
python scripts/bench.py --label "A: pool off" --config CANDIDATE_POOL=0 --config JUDGE_BEST_OF=1
python scripts/bench.py --cases lake_mead,wwii_midway --label "smoke"
python scripts/bench.py --report                                   # every recorded run, means by label
```

`--config KEY=VALUE` sets a per-job override (the keys in
`handler.CONFIG_OVERRIDABLE`), applied on the parent and every fan-out part,
so two settings can be compared on one image.

## What is measured (per case, appended to `results.jsonl`)

- `fill_pct`, `video_pct`: scenes with any media / with a video clip.
- `entity_acc`, `location_acc`: of the scenes whose intent names entities or
  locations, the share whose chosen clip's description or title names one.
- `case_entity_coverage`: filled scenes whose clip names any of the case's
  expected entities.
- `visual_relevance`: mean vision score of the chosen clips;
  `timestamp_relevance`: mean moment score of the chosen grabs.
- `duplicate_rate`: repeated video ids among video scenes.
- `generic_rate`: event-specific scenes that ended up with a clip the judge
  classed generic.
- `avg_candidates`, `avg_winning_score`: pool size and combined score.
- `generation_s`, `ai_usd` (Kie credits at $0.005), `runpod_usd` (an estimate
  from the parent's wall time and the parts used), `total_usd`.

A run is a paid, live run against RunPod, YouTube and Kie: about seven to
ten minutes and under a dollar for all seven cases.
