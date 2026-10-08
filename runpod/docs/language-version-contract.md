# Language versions: app ↔ worker contract

"Make a language version" turns a FINISHED video into a new project in another language: the narration is
translated line by line, voiced by our own voice server (Qwen3-TTS, RunPod endpoint `noxv85ue2spsrl`), and the
existing timeline is re-timed to the new voice - the same shots and looks, each scene stretched or trimmed to its
line's new length, captions and the looks' on-screen text in the new language. No footage search.

The original video is never written. The version is a NEW `video_projects` row, "<title> (Español)".

## Languages

Our voice server speaks: `en` English, `es` Spanish (Español), `pt` Portuguese (Português), `fr` French
(Français), `de` German (Deutsch), `it` Italian (Italiano), `ru` Russian (Русский), `zh` Chinese (中文),
`ja` Japanese (日本語), `ko` Korean (한국어). The source's own language is not offered (a version's language is
`scene_data.meta.languageVersion.language`; any other video counts as English). Hindi and the rest are not
supported by the voice server.

## Who does what

| Step | Where |
| --- | --- |
| Check the source (finished video, timeline, not the AI presenter style or a hybrid presenter video), price, consent | app, `video-v2` action `translate` |
| Create the new row (status `rendering`, `job_action` `translate`) and start the job | app, `video-v2` (seconds; the 150 s edge limit is never near) |
| Translate, voice, align, re-time, save the new timeline, render, upload | worker action `translate_version` (serverless, endpoint `tuxcziwby5plod`) |
| Progress, the finished video, the new timeline, the new narration link | worker → `worker-storage` broker (as any render) + the status sync (`video-status` / `video-webhook` → `_shared/videoJob.ts`) |

## video-v2 action `translate`

Request body: `{ action: "translate", projectId: <SOURCE project id>, language: "es", captions?: boolean,
consent?: boolean, quote?: boolean }`.

* `quote: true` creates nothing: `{ ok, quote: { language, languageName, nativeName, title, seconds, credits,
  fps, voice: "same" | "clone", voiceName?, needsConsent } }` or `{ error }` with why it cannot be made.
* Otherwise: refuses (400) a source without `video_url`, without a timeline or without its narration file
  (`source_audio_url` is required), a source that is `rendering`, the AI presenter style or a timeline with
  presenter scenes (lip-sync would not match), an unknown language or the source's own language, and - when the
  voice is cloned from the narration - `consent !== true` (`code: "consent"`).
* A version of the same source in the same language that is still `rendering` is returned (`busy: true`), never
  started twice.
* Price: `languageVersionCredits(sourceSeconds, fps)` (`_shared/creditRules.ts`) = a render of the same length
  (10 credits a minute, 60 fps x1.25) times `LANGUAGE_VERSION_FACTOR` (1 for now: the owner sets the price).
  Checked (dry run) before anything is created; charged under the job's own key once RunPod has the job, to the
  SOURCE's owner, `feature: "video"`, `refType: "video_project"`, `refId: <new id>`; refunded like any job on
  Cancel.
* The new row: `user_id` = the source's owner, `title` = "<source title> (<native name>)", `status`
  `rendering`, `job_action` `translate`, `contract_version` 2, `source_mode` "audio", `audio_url` = the planned
  narration link (R2 public base + `narration_key`, below), channel / format / youtube / policy fields copied,
  `voice_id` = the source's `preset:<id>` when the voice is ours (else null, so a version of the version keeps
  our voice), `render_settings` = the source's (without `last_pod_error`, `thumbnails`) + `captions` +
  `language_version: { source_project_id, language, created_by, created_at, voice }` (`voice` "same" | "clone";
  a cloned voice's record also keeps the person's word: `consent: { text, at }`).
* Answer: `{ ok, action: "translate", jobId, project: <new row> }`; the app opens `/create-video/<new id>`.

## Worker input (`action: "translate_version"`)

```jsonc
{
  "action": "translate_version",
  "contract_version": 2,
  "project_id": "<NEW project id>",          // the only row the job writes (refused when == source_project_id)
  "source_project_id": "<SOURCE project id>",
  "owner_id": "<user id>",
  "language": "es",
  "title": "<source title> (Español)",
  "timeline": { /* the source's scene_data, media links re-signed (refreshTimelineMedia) */ },
  "source_audio_url": "<the source narration, re-signed for 12 h>",  // the voice cloned when `voice` is absent
  "voice": { "url": "https://...wav", "text": "<its exact transcript>", "key": "preset:doc-male" }, // optional
  "narration_key": "projects/<new id>/narration-es-<12 hex>.mp3",  // optional: where the new narration goes (R2)
  "captions": true,                           // optional: subtitles on in the version (default: the source's)
  "media_bucket": "video-media",
  "prices": { }                               // optional, provider_prices
}
```

`voice` is sent when the source was voiced with one of our own voices (`voice_id` `preset:<id>` →
`_shared/ownTts.ts` `OWN_PRESETS` refUrl / refText). An uploaded narration (`source_mode` "audio") keeps the voice
picked before it on the row, so it counts as cloned - except a version we voiced ourselves
(`language_version.voice` "same"). Otherwise the worker clones the narrator from a clean 12-25 s stretch of the
source narration (kept private: sent inline to the voice server, never stored).

## Worker output

```jsonc
{ "ok": true, "action": "translate_version", "language": "es",
  "timeline": { /* the new document */ },
  "video_url": "https://pub-...r2.dev/projects/<new>/final-....mp4", "duration": 1234.5,
  "object_path": "...", "bucket": "r2:thumbgenius-videos",
  "audio_url": "https://pub-...r2.dev/projects/<new>/narration-es-....mp3",
  "translation": { "model": "...", "fragments": 0, "numberIssues": [], "voice": "clone" | "same", "ttsSeconds": 0 },
  "costs": { }, "events": { }, "elapsed": 0 }
```

`{ "ok": false, "error": "..." }` (or a FAILED job) marks the NEW project failed; the source is never touched.

While it runs the worker writes the new row like a build: progress (`job_progress.phase`: `translate`, `voice`,
`align`, then `save`, `render`, `upload`), the new timeline before the render (so a failed render keeps an
editable version), then the done fields. The status sync treats a completed `translate` job like a `build`
(its `timeline` becomes `scene_data`) and also sets `audio_url` from `out.audio_url`.

## The new timeline

* Same shots, looks, transitions, music and sounds; every frame position re-timed to the new narration (scene
  cuts on the new lines, looks re-anchored on their number or name where it is said, else carried proportionally).
* `scenes[].text` and `scenes[].words` in the new language (captions follow them); the looks' display text
  translated (titles, labels, items, units, dates); names, numbers and places kept.
* `audio.url` / `meta.audioSource` = the new narration; `meta.languageVersion = { language, from,
  sourceProjectId, voice, model, fragments, numberIssues, ttsSeconds, translatedTitle }`.
