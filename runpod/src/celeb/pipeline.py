"""
The celeb compilation style inside the worker's normal actions (handler.py; video_style "celeb_compilation").

  plan    script -> narration (our own voice per narration block, or the owner's upload cut at the clip spots)
          -> every [CLIP: ...] spot found and downloaded as a hero window (quotes.find: search, captions,
          whisper, sentence-snapped in/out; or the owner's url + start/end) -> [MONTAGE: ...] shots fetched
          -> the reel timeline (reel.build: cold open, J-cuts, b-roll from each clip's own footage, flashes,
          title cards, captions coloured by speaker) -> the picture without elements (base) and the mix,
          both kept on R2 so the editor's changes re-render without downloading anything again
  render  the saved document -> every element composited on the base (fx.composite) with the editor's caption
          colours -> the finished video
  build   plan, then render

No language model is called anywhere here: the script is the owner's, faces come from the local YuNet detector
and speakers from the local diarizer. The only paid calls are the downloads (proxy bytes) and the narration
(our own TTS endpoint).

The saved document ("scene_data") has no scenes; its "celeb" block is what the app's editor shows and edits:
captions (text, times, colour yellow | white | green), the rights log of every source, the spots no clip was
found for, and the links of the base picture and the mix.
"""
import copy
import json
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Callable, Dict, List, Optional, Tuple

STYLE = "celeb_compilation"
COLOUR_NAMES = ("yellow", "white", "green")
HERE = os.path.dirname(os.path.abspath(__file__))
RUNPOD = os.path.dirname(os.path.dirname(HERE))
MUSIC = os.path.join(RUNPOD, "remotion", "public", "bgm", "celeb-uplifting.mp3")
FLASH_SFX = os.path.join(RUNPOD, "remotion", "public", "sfx", "camera-flash-pop.mp3")
MONTAGE_PAD = 0.6            # seconds fetched either side of a montage shot
CLIP_WORKERS = 3


def is_celeb(inp: dict) -> bool:
    """A job of this style: its video_style, or (a render) a document made by it."""
    from .. import styles
    if styles.resolve(str(inp.get("video_style") or "")) == STYLE:
        return True
    tl = inp.get("timeline")
    return isinstance(tl, dict) and isinstance(tl.get("celeb"), dict)


def colour_name(rgba) -> str:
    from . import speakers
    want = tuple(rgba or ())[:3]
    for k, c in enumerate(speakers.COLOURS):
        if tuple(c)[:3] == want:
            return COLOUR_NAMES[min(k, len(COLOUR_NAMES) - 1)]
    return COLOUR_NAMES[0]                       # an unknown colour reads as the first voice


def featured_colour(inp: dict) -> str:
    """The job's "Featured person's captions" choice: "yellow" (default; r2op, UjOJ) or "white" (B4rM)."""
    v = str(inp.get("celeb_featured_colour") or "").strip().lower()
    return v if v in ("yellow", "white") else "yellow"


def colour_rgba(name: str) -> tuple:
    from . import speakers
    k = COLOUR_NAMES.index(name) if name in COLOUR_NAMES else 0
    return tuple(speakers.COLOURS[min(k, len(speakers.COLOURS) - 1)])


# ------------------------------------------------------------------ narration
def _voice_choice(inp: dict):
    """The narrator: a built-in preset ("energetic" default, "doc-male") or the job's reference voice."""
    ref = inp.get("tts_reference_audio")
    text = inp.get("tts_reference_text")
    if isinstance(ref, str) and ref.startswith("http") and isinstance(text, str) and text.strip():
        return {"url": ref, "text": text.strip()}
    return str(inp.get("celeb_voice") or "energetic")


def narration(texts: List[str], inp: dict, work: str) -> List[str]:
    """One levelled wav per narration block, in script order."""
    from . import voalign, voice
    raw = inp.get("audio_url") or inp.get("audio_path")
    if raw:
        if os.path.isfile(str(raw)):
            path = str(raw)
        else:
            from .. import storage
            src = storage.resolve_audio(raw, bucket=inp.get("audio_bucket", "video-audio"))
            path = storage.download(src, os.path.join(work, "upload_narration.mp3"))
        return voalign.split(path, texts, os.path.join(work, "vo"))
    speed = float(inp.get("tts_speed") or 1.0)
    # CELEB_VOICE_CACHE: a folder kept between runs (tests), where a line already voiced is not paid for again.
    where = os.environ.get("CELEB_VOICE_CACHE") or os.path.join(work, "voice")
    return voice.synthesize(texts, where, voice=_voice_choice(inp), speed=speed)


# ------------------------------------------------------------------ clips
def _words(ws) -> List[dict]:
    return [{"text": w.text, "start": round(float(w.start), 3), "end": round(float(w.end), 3)} for w in ws]


def find_clip(b, k: int, work: str, log: Callable = print) -> Optional[dict]:
    """One [CLIP: ...] spot -> its downloaded window and in/out on the window's clock, or None."""
    from . import quotes
    d = os.path.join(work, "clips", f"c{k:02d}")
    vid = b.youtube_id
    given = bool(vid and b.start is not None and b.end is not None)
    if not given and not (b.quote or vid):
        log(f"[celeb] spot {k}: no quote and no url+start+end")
        return None
    m = quotes.find(b.who, b.quote, b.where, d, min_s=b.min_s, max_s=b.max_s, video_id=vid,
                    start=b.start if given else None, end=b.end if given else None, log=log, trim_clip=False)
    if m is None or not m.window:
        return None
    from ..filters import scene_cuts
    from .compose import duration
    return {"key": f"c{k:02d}", "video": m.video_id, "title": m.title, "channel": m.channel,
            "path": m.window, "at0": m.window_at, "start": round(m.start - m.window_at, 3),
            "end": round(m.end - m.window_at, 3), "words": _words(m.window_words), "cuts": scene_cuts(m.window),
            "dur": duration(m.window), "score": m.score, "source": m.source}


def fetch_montage(item: str, n: int, work: str) -> Optional[Tuple[dict, str]]:
    """'VIDEOID@42.3-43.3 pop=...' -> a short hero section around it and the item re-written on its clock."""
    from .. import ytdlp
    from ..filters import scene_cuts
    from . import quotes
    from .compose import duration
    from .reel import _montage_item
    sid, (a, b), opts = _montage_item(item)
    w0 = max(0.0, a - MONTAGE_PAD)
    path = ytdlp._yt_fetch(sid, os.path.join(work, "montage"), w0, (b + MONTAGE_PAD) - w0, timeout=300, hero=True)
    if not path:
        return None
    w0 = quotes.window_start(path, w0)
    key = f"m{n:02d}"
    src = {"key": key, "video": sid, "path": path, "at0": w0, "words": [], "cuts": scene_cuts(path),
           "dur": duration(path), "montage": True}
    return src, f"{key}@{a - w0:.3f}-{b - w0:.3f} " + " ".join(opts)


# ------------------------------------------------------------------ posters (title cards)
def poster(film: str, work: str) -> str:
    """A film's poster for its title card: the film's Wikipedia page image (keyless). '' when none."""
    import requests
    title, sub, year = (list(map(str.strip, film.split("/"))) + ["", "", ""])[:3]
    name = f"{title}: {sub}" if sub else title
    ua = {"User-Agent": "ThumbGenius/1.0 (video worker; contact via thumbgenius.app)"}
    try:
        q = f"{name} {year} film".strip()
        r = requests.get("https://en.wikipedia.org/w/api.php", headers=ua, timeout=20, params={
            "action": "query", "list": "search", "srsearch": q, "srlimit": 3, "format": "json"})
        hits = [h["title"] for h in r.json().get("query", {}).get("search", [])]
        for page in hits:
            s = requests.get("https://en.wikipedia.org/api/rest_v1/page/summary/" + page.replace(" ", "_"),
                             headers=ua, timeout=20).json()
            img = (s.get("originalimage") or s.get("thumbnail") or {}).get("source")
            if not img:
                continue
            from urllib.parse import urlparse
            ext = os.path.splitext(urlparse(img).path)[1].lower()
            ext = ext if ext in (".jpg", ".jpeg", ".png", ".webp") else ".jpg"
            dst = os.path.join(work, "posters", re.sub(r"[^\w]+", "_", film)[:60] + ext)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            data = requests.get(img, headers=ua, timeout=30).content
            with open(dst, "wb") as fh:
                fh.write(data)
            return dst
    except Exception as e:  # noqa: BLE001 - a title card without its poster is left out, nothing fails
        print(f"[celeb] no poster for {film!r}: {type(e).__name__}", flush=True)
    return ""


def _poster_key(film: str) -> str:
    title, sub, _ = (list(map(str.strip, film.split("/"))) + ["", "", ""])[:3]
    return f"{title} {sub}"


# ------------------------------------------------------------------ the document
def _timeline_json(tl) -> dict:
    return {"total": tl.total, "cuts": tl.cuts, "clip_spans": tl.clip_spans, "narr_spans": tl.narr_spans,
            "marks": [asdict(m) for m in tl.marks]}


def _timeline_from(doc: dict):
    from . import reel
    c = doc["celeb"]
    t = c.get("timeline") or {}
    tl = reel.Timeline()
    tl.total = float(t.get("total") or c.get("duration") or 0.0)
    tl.cuts = [float(x) for x in t.get("cuts") or []]
    tl.clip_spans = [tuple(x) for x in t.get("clip_spans") or []]
    tl.narr_spans = [tuple(x) for x in t.get("narr_spans") or []]
    tl.marks = [reel.Mark(**m) for m in t.get("marks") or []]
    tl.captions = [(float(x["start"]), float(x["end"]), str(x["text"]), colour_rgba(str(x.get("color") or "")))
                   for x in c.get("captions") or []]
    return tl


def document(inp: dict, tl, found: List[dict], missing: List[dict], posters: Dict[str, str],
             media_urls: Dict[str, str], script_text: str) -> dict:
    by_key = {f["key"]: f for f in found}
    rights = []
    for row in tl.log:
        f = by_key.get(row["video"])
        if not f:
            continue
        rights.append({"video": f["video"], "url": f"https://www.youtube.com/watch?v={f['video']}",
                       "title": f.get("title", ""), "channel": f.get("channel", ""),
                       "in": round(f["at0"] + row["in"], 2), "out": round(f["at0"] + row["out"], 2),
                       "at": row["at"], "length": round(row["out"] - row["in"], 2)})
    used = {r["video"] for r in rights}
    for f in found:
        if f.get("montage") and f["video"] not in used:
            rights.append({"video": f["video"], "url": f"https://www.youtube.com/watch?v={f['video']}",
                           "title": "", "channel": "", "in": round(f["at0"], 2),
                           "out": round(f["at0"] + f["dur"], 2), "at": None, "length": round(f["dur"], 2),
                           "montage": True})
    captions = [{"i": i, "start": round(c[0], 3), "end": round(c[1], 3), "text": c[2],
                 "speaker": COLOUR_NAMES.index(colour_name(c[3])) if len(c) > 3 else 0,
                 "color": colour_name(c[3]) if len(c) > 3 else "yellow",
                 "auto": colour_name(c[3]) if len(c) > 3 else "yellow"} for i, c in enumerate(tl.captions)]
    return {"version": 1, "fps": 30, "width": 1920, "height": 1080, "scenes": [],
            "meta": {"videoStyle": STYLE, "title": str(inp.get("title") or ""), "events": {}},
            "celeb": {"version": 1, "duration": tl.total, "script": script_text, "captions": captions,
                      "featured_colour": featured_colour(inp),
                      "rights": rights, "missing": missing, "media": media_urls,
                      "posters": {k: v for k, v in posters.items() if str(v).startswith("http")},
                      "logo": str(inp.get("logo_url") or ""),
                      "timeline": _timeline_json(tl)}}


# ------------------------------------------------------------------ storage of the base + mix
def _keep(path: str, inp: dict, name: str, content_type: str) -> str:
    """The base picture / mix / poster on R2 so a later render needs no download from YouTube. '' without R2."""
    from .. import r2
    if not r2.enabled():
        return ""
    project = inp.get("project_id") or "adhoc"
    key = f"projects/{project}/celeb/{inp.get('_job_id') or uuid.uuid4().hex[:12]}-{uuid.uuid4().hex[:8]}/{name}"
    return r2.upload(path, key, content_type=content_type, deadline=time.time() + 900)


def _fetch(url: str, dst: str) -> str:
    if os.path.isfile(url):
        return url
    from .. import storage
    return storage.download(url, dst, timeout=600)


# ------------------------------------------------------------------ actions
def plan(inp: dict, work: str, report: Callable) -> Tuple[dict, dict]:
    """(document, local files {base, mix, posters, logo}) for a script with clip spots."""
    from . import reel, script
    from .compose import duration
    text = str(inp.get("script") or "")
    blocks = script.parse(text)
    spots = [b for b in blocks if b.kind == "clip"]
    if not spots:
        raise ValueError("A celeb compilation script needs at least one clip spot, e.g. "
                         "[CLIP: Tom Holland | \"I'm not allowed to say\" | Jimmy Kimmel Live | 12-20s]")
    os.makedirs(work, exist_ok=True)
    narr_texts = [b.text for b in blocks if b.kind == "narr"]

    report("Voicing the narration", 5)
    with ThreadPoolExecutor(max_workers=2) as side:
        voices = side.submit(narration, narr_texts, inp, work) if narr_texts else None

        report(f"Finding {len(spots)} clips", 10)
        found: List[dict] = []
        missing: List[dict] = []
        done = [0]

        def one(kb):
            k, b = kb
            got = None
            try:
                got = find_clip(b, k, work)
            except Exception as e:  # noqa: BLE001 - one spot never fails the video; it is listed as missing
                print(f"[celeb] spot {k} failed: {type(e).__name__}: {str(e)[:160]}", flush=True)
            done[0] += 1
            report(f"Found {done[0]} of {len(spots)} clips", 10 + int(45 * done[0] / len(spots)))
            return k, b, got

        with ThreadPoolExecutor(max_workers=CLIP_WORKERS) as pool:
            results = list(pool.map(one, list(enumerate(spots))))
        for k, b, got in results:
            if got is None:
                missing.append({"k": k, "who": b.who, "quote": b.quote, "url": b.url, "why": "no clip found"})
                b.kind = "skip"
                continue
            found.append(got)
            b.key, b.start, b.end = got["key"], got["start"], got["end"]
        n = 0
        for b in blocks:
            if b.kind != "montage":
                continue
            items = []
            for item in b.shots:
                try:
                    got = fetch_montage(item, n, work)
                except Exception as e:  # noqa: BLE001 - a montage shot less
                    print(f"[celeb] montage shot {item[:40]!r} failed: {type(e).__name__}", flush=True)
                    got = None
                n += 1
                if got:
                    found.append(got[0])
                    items.append(got[1])
            b.shots = items
        narr_paths = voices.result() if voices else []
    if not any(f for f in found if not f.get("montage")):
        raise RuntimeError("No clip could be found or downloaded for any clip spot; nothing was rendered.")

    blocks = [b for b in blocks if b.kind != "skip"]
    sources = {f["key"]: reel.Source(f["key"], f["path"], f["words"], f["cuts"], f["dur"], guard=(0.25, 0.25))
               for f in found}
    report("Building the edit", 58)
    tl = reel.build(blocks, narr_paths, sources, featured_colour=featured_colour(inp))
    films = {b.film for b in blocks if b.kind == "clip" and b.film}
    posters_local = {}
    for film in films:
        p = poster(film, work)
        if p:
            posters_local[_poster_key(film)] = p
    report("Rendering the picture", 62)
    base = reel.render_base(tl, os.path.join(work, "base"))
    report("Mixing the sound", 70)
    music = str(inp.get("bgm_url") or "") or MUSIC
    if music.startswith("http"):
        music = _fetch(music, os.path.join(work, "music_bed" + os.path.splitext(music.split("?")[0])[1][:5]))
    mix = reel.mix(tl, os.path.join(work, "base"), music=music if inp.get("bgm", True) is not False else "",
                   sfx=FLASH_SFX)
    logo = ""
    if inp.get("logo_url"):
        try:
            logo = _fetch(str(inp["logo_url"]), os.path.join(work, "logo.png"))
        except Exception:  # noqa: BLE001 - no logo, no failure
            logo = ""
    report("Saving the edit", 74)
    media_urls = {}
    flac = os.path.join(work, "base", "mix.flac")
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", mix, "-c:a", "flac", flac], check=True, timeout=600)
    try:
        media_urls = {"base": _keep(base, inp, "base.mp4", "video/mp4"), "mix": _keep(flac, inp, "mix.flac", "audio/flac")}
        posters_urls = {k: _keep(p, inp, "poster_" + os.path.basename(p), "image/jpeg") for k, p in posters_local.items()}
    except Exception as e:  # noqa: BLE001 - the video still renders; only an editor re-render would need these
        print(f"[celeb] base/mix not kept on R2: {type(e).__name__}: {str(e)[:160]}", flush=True)
        posters_urls = {}
    media_urls = {k: v for k, v in media_urls.items() if v}
    doc = document(inp, tl, found, missing, {**posters_local, **posters_urls}, media_urls, text)
    doc["celeb"]["posters"] = posters_urls
    print(f"[celeb] {len(found)} sources, {len(missing)} missing, {len(tl.captions)} captions, "
          f"{len(tl.marks)} marks, {tl.total:.1f} s", flush=True)
    return doc, {"base": base, "mix": mix, "posters": posters_local, "logo": logo}


def render(doc: dict, work: str, report: Callable, local: Optional[dict] = None, crf: int = 17) -> str:
    """The finished video from a celeb document: elements on the base, the mix under it."""
    from . import fx, reel
    os.makedirs(work, exist_ok=True)
    c = doc["celeb"]
    local = dict(local or {})
    if not (local.get("base") and os.path.isfile(local["base"])):
        if not (c.get("media") or {}).get("base"):
            raise ValueError("This celeb document has no saved picture to re-render from; build it again.")
        report("Fetching the saved edit", 10)
        local["base"] = _fetch(c["media"]["base"], os.path.join(work, "base.mp4"))
        local["mix"] = _fetch(c["media"]["mix"], os.path.join(work, "mix.flac"))
    posters = dict(local.get("posters") or {})
    for k, url in (c.get("posters") or {}).items():
        if k not in posters:
            try:
                posters[k] = _fetch(url, os.path.join(work, "poster_" + re.sub(r"[^\w]+", "_", k) + ".jpg"))
            except Exception:  # noqa: BLE001
                pass
    logo = local.get("logo") or ""
    if not logo and c.get("logo"):
        try:
            logo = _fetch(c["logo"], os.path.join(work, "logo.png"))
        except Exception:  # noqa: BLE001
            logo = ""
    tl = _timeline_from(doc)
    report("Placing captions, names and pops", 20)
    els = reel.elements(tl, local["base"], posters, logo=logo)
    out = os.path.join(work, "final.mp4")
    report("Rendering the video", 30)
    total = max(1, int(tl.total * fx.FPS))
    fx.composite(local["base"], els, out, audio=local["mix"], crf=crf,
                 progress=lambda i, n: report("Rendering the video", 30 + int(60 * i / max(1, total))))
    return out


def run(action: str, inp: dict, work: str, report: Callable) -> Tuple[dict, str, float]:
    """(document, finished video path or '', seconds) for a plan / build / render job of this style."""
    from .compose import duration
    if action == "render":
        doc = copy.deepcopy(inp.get("timeline") or {})
        out = render(doc, work, report)
        return doc, out, duration(out)
    doc, local = plan(inp, work, report)
    if action == "plan":
        return doc, "", float(doc["celeb"]["duration"])
    out = render(doc, os.path.join(work, "final"), lambda s, p: report(s, 75 + int(p * 0.2)), local=local)
    return doc, out, duration(out)
