# Sourcing yield, 2026-10-18

Branch `feature/sourcing-yield-2026-10-18` (worker repo, cut from `thumbgenius-video-worker` 98693b0).
Not deployed. Commits:

- `6fcb6c1` pictures: skip SVG, fix Yandex sizes, other copies, second route
- `24f1a83` YouTube: retries go through routes not yet tried

## The starting point

The owner's last 3 real renders (video_job_events, 2026-10-12/13): 1,441 `download_ok` against
about 1,000 failures.

| provider / event | class | count | sample |
|---|---|---|---|
| download_yandex_image | MEDIA_UNAVAILABLE | 216 | 404 Not Found |
| download_yandex_image | UNKNOWN | 144 | 400 Client Error: Use thumbnail sizes l... |
| download_web_image | UNKNOWN | 149 | not a photo (svg) |
| download_web_image | MEDIA_UNAVAILABLE | 81 | 404 |
| download_web_image | ACCESS_DENIED | 62 | 403 |
| download_web_image | PROXY_FAILURE | 48 | 422 / HTML error page, then the proxy try failed |
| download_web_image | NETWORK_TIMEOUT | 22 | timed out |
| youtube download_failed | STREAM_REFUSED | 164 | Server returned 403 Forbidden, then ffmpeg exited with code 1 |
| youtube (metadata + download) | BOT_CHECK | 94 | Sign in to confirm you're not a bot |

What the code was doing (src/imagefix.py, src/media.py, src/ytdlp.py):

- The "after 1 attempt(s)" in the message is one `storage.download` call. `imagefix._fetch_raw`
  already makes up to five tries: plain, browser headers, og:image, a Chrome fingerprint, then
  one residential route. The event message is cut at 100 characters, so it only shows the
  first try. The PROXY_FAILURE class comes from the words "via proxy" in the joined message.
- An SVG link was downloaded in full and only then refused by `normalize()`.
- A Yandex 400 went through all four other tries, each with the same 400. Two of them also
  counted as the site refusing, so `avatars.mds.yandex.net` was then skipped for 30 minutes
  for every picture on it.
- Yandex results carried only the original's link. A 404 there was final: no page (Referer),
  no thumbnail, no other copy.
- The residential try was a single proxy, with no second route.
- YouTube: `RETRY` already gives STREAM_REFUSED and BOT_CHECK 2 more tries "on another proxy".
  But `ProxyManager.acquire` ranks healthy routes by latency. One STREAM_REFUSED leaves a route
  healthy, so the retry usually went back to the same fastest route that had just refused.

## What changed (each behind a flag in src/config.py)

| flag | default | what it does |
|---|---|---|
| `PICTURE_SKIP_SVG` | on | `imagefix.not_a_photo_url`: a link that says SVG (`.svg`/`.svgz` path, `format=`/`fm=svg`, an `data:image/svg+xml` link) is left out of the web and Yandex results and is never fetched. A download whose Content-Type is `image/svg+xml` stops at the headers with `NotAPhoto`: no body is read, and there is no browser, fingerprint, route or alternate try. The message keeps the words "not a photo (svg)". It never counts as the site refusing. A Wikimedia `...x.svg.png` rendering is still a photo. |
| `PICTURE_BAD_REQUEST_FINAL` | on | A 400 for both the plain and the browser try is final, like a 404: no fingerprint or residential try. A 400 never marks the host as refusing. |
| `YANDEX_RESULT_DETAILS` | on | `media._yandex_details` reads each result's own JSON record on the results page: size (`origWidth`/`origHeight`), page (`snippet.url`, used as the Referer), Yandex's thumbnail (`avatars.mds.yandex.net/i?id=...`) and its duplicates (`dups`/`preview`/`sizes`: other sites' copies, biggest first, never a stock agency's). A Yandex-hosted link without a valid size gets one (`/get-.../<group>/<name>` gets `/orig`, `/i?id=` gets `n=13`). A page laid out differently gives no details and the links work as before. |
| `PICTURE_ALTERNATES` / `PICTURE_ALTERNATES_MAX=2` | on / 2 | When a picture fails, `imagefix._from_alternates` asks first for a Yandex-hosted link at `orig` / `n=13` (after a 400 for its size), then for the result's duplicates. At most 2 copies, one plain and one browser try each; a 404 on a copy moves on to the next. It never runs after the scene's stop, for an SVG, for an agency copy, or for a host that is being skipped. Copies are also tried when the original's host is being skipped. The small search-engine thumbnail stays the last resort, as before (only with `PICTURE_SHARPNESS_CHECK` off). |
| `PICTURE_SECOND_ROUTE` | on | A residential try that failed because of the route (proxy error, connect/read timeout, SSL or connection drop, an HTML page, 407/422/5xx, a cut or empty transfer) is made once more through a different `IMAGE_PROXIES` route. The origin's own 400/403/404/410/429 through a home address is final. |
| `YTDLP_RETRY_OTHER_ROUTE` | on | `media._yt_fetch_retry` collects the routes this clip has tried (`ytdlp.AVOID_ROUTES`). `ProxyManager.acquire(avoid=)` takes the best untried route that is not quarantined, and falls back to the best of all routes only when every one has been tried. MEDIA_UNAVAILABLE (paid, members-only, removed) is still tried once and then remembered (`_NEVER`). |
| `YTDLP_RETRY_PLAYER_CLIENT` | "" (off) | After a STREAM_REFUSED or BOT_CHECK, the retry can add `--extractor-args youtube:player_client=<value>` (for example `tv,web_safari`; the value is cleaned to `[a-z0-9_,-]`). It stays off because no offline test can prove a client still serves formats with yt-dlp 2026.8.19. Turn it on only after a pod probe. |

`MediaAsset` gained `alt_urls` (a list). `fanout`/`resume` rebuild assets by field name, so old
records still load.

## Expected effect per class (estimates; measure after deploy)

| class (count) | fix | expected |
|---|---|---|
| web "not a photo (svg)" (149) | PICTURE_SKIP_SVG | These can never become photos. Links that say SVG (probably most of them) leave the log entirely. The rest stop at the headers. Saves about 149 wasted downloads and their scene time. It adds no pictures directly, but each scene reaches its next candidate sooner. |
| Yandex 400 "thumbnail sizes" (144) | YANDEX_RESULT_DETAILS + `orig` retry + 400 not a refusal | About 70-130 recovered. A link missing its size is fixed before the first try; a wrong alias gets `orig`; and the Yandex host is no longer skipped for 30 minutes after two of these. Each one that is still final now takes 2 tries instead of 5. Uncertain: no sample link was available offline. |
| Yandex 404 (216) | duplicates on other sites | About 65-110 recovered, depending on how many results carry duplicates. Page-as-Referer also helps a few hotlink-blocked copies. |
| web 404 (81) | none | 0. Final, and Bing/DuckDuckGo give no other copy. |
| web 403 (62) | none | 0. These already get every try (browser, og:image, fingerprint, residential). |
| web PROXY_FAILURE (48) | PICTURE_SECOND_ROUTE | About 20-30 recovered. |
| web NETWORK_TIMEOUT (22) | PICTURE_SECOND_ROUTE (only when the routed try timed out) | About 5-10 recovered. |
| YouTube STREAM_REFUSED (164 events) | YTDLP_RETRY_OTHER_ROUTE | The refused link is a passing session on that address (6-11% on most routes, measured 2026-10-07), so a retry on a fresh route should come down about 9 times in 10. Expect about 30-60 fewer STREAM_REFUSED events (no second refusal on the same route) and close to zero clips given up after 3 tries. |
| YouTube BOT_CHECK (94) | YTDLP_RETRY_OTHER_ROUTE | Small, about 5-15. A bot check already degrades the route at once (ranked after healthy routes). The new rule only stops a retry from landing on it again when it is still the best-ranked route. |

Total: roughly 250-450 of the ~1,000 failures are recovered or never attempted, with fewer
tries and less scene time spent on links that cannot succeed. Nothing paid is called more
often. The extra tries are free HTTP GETs (at most 2 alternates + 1 route per picture) and,
for YouTube, the same 2 retries as before.

## Tests (offline)

- `tests/test_sourcing_yield_pictures.py` (23): SVG link and Content-Type rejection (one request,
  no body, no further tries), web search drops SVG, Yandex record parsing on a fixture page,
  search carrying size/page/thumbnail/duplicates (agency copies dropped), the flag off keeps links
  only, size fixes and the `orig` retry after "Use thumbnail sizes", a 400 is not a refusal,
  duplicates after a 404 (limit, flag off, skipped host), the second route on proxy error, timeout,
  HTML, 422 and 502 but not on 400/403/404/410/429, and a 400 final after 2 tries.
- `tests/test_sourcing_yield_youtube.py` (14): the measured messages classify (paid and members-only
  are MEDIA_UNAVAILABLE), acquire(avoid=) picks untried and non-quarantined routes, retries avoid
  tried routes (direct included), paid videos are tried once, the player client is off by default,
  only after a refused stream or bot check, and lands in the yt-dlp command, and the flag off
  ignores the avoid list.
- Full offline suite: `SKIP_DOTENV=1 python -m unittest discover -s tests -t .` from `runpod/`.

## How to verify after deploy

1. Deploy the worker image from this branch. Nothing else is needed: no app change and no
   migration. Then run 2-3 real renders.
2. Compare with the same query over the 2026-10-12/13 jobs:

```sql
-- failures by provider / event / class for the chosen jobs
select provider, event, failure_class, count(*) as n,
       min(left(message, 90)) as sample
from video_job_events
where job_id in ('<job 1>', '<job 2>', '<job 3>')          -- or: created_at >= '<deploy time>'
  and level = 'warning'
  and (event in ('download_failed', 'metadata_failed', 'empty_download')
       or provider like 'download_%')
group by 1, 2, 3
order by n desc;

-- successful YouTube downloads for the same jobs
select count(*) from video_job_events
where job_id in ('<job 1>', '<job 2>', '<job 3>') and event = 'download_ok';
```

What to look for:

- `download_web_image` UNKNOWN "not a photo (svg)" falls from about 149 to a few. The ones left
  are SVG answers stopped at the headers, with the message "...the site sent image/svg+xml".
- `download_yandex_image` UNKNOWN "Use thumbnail sizes" falls steeply.
- `download_yandex_image` MEDIA_UNAVAILABLE (404) falls by about a third or more.
- `download_web_image` PROXY_FAILURE messages now show "via another proxy" when both routes failed.
- `youtube` STREAM_REFUSED per video: rarely more than one, and the log line "giving up on ...
  after 3 attempt(s): STREAM_REFUSED" becomes rare.
- `meta.sourcing.stageSeconds` `download:picture_failed` thread-seconds go down.

Rollback is per flag: set it to `0` on the endpoint/template env. `YTDLP_RETRY_PLAYER_CLIENT`
stays empty until a small check shows the client still downloads: a few section downloads
through the proxies with `--extractor-args youtube:player_client=<value>` added. `probe_download`
does not apply this variable.
