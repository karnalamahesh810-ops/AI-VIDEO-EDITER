#!/usr/bin/env python3
"""FULL-CLOUD video pipeline (RunPod). No laptop involved.
Usage:
  python3 pipeline_pod.py --audio /workspace/in/narration.mp3 \
      --channels newyorkreports1,inspectorjamesofficial,taxesreport,marcomonja-m6v

Steps: loudnorm -> whisper(GPU) -> scenes -> yt-dlp channels (cookieless) -> slice
       -> auto-QC (OpenCV) -> tag (Gemini vision if key, else fallback) -> match
       -> overlays (Gemini director if key, else template) -> portraits (Wikipedia)
       -> remotion render -> /workspace/out/final.mp4
Gemini key (optional, for smart tagging+overlays): put it in /workspace/gemini_key.txt
Status JSON written to /workspace/out/pipeline_status.json after each step (poll this
from the website backend later).
"""
import argparse, json, os, re, subprocess, sys, time, urllib.request, urllib.parse, io
from collections import defaultdict

WS = "/app"
RT = f"{WS}/runtime"; POOL = f"{RT}/broll_pool"; SRC = f"{WS}/channel_src"; OUT = f"{WS}/out"
for d in (RT, POOL, SRC, OUT): os.makedirs(d, exist_ok=True)
STATUS = f"{OUT}/pipeline_status.json"
T0 = time.time()

# Residential proxy for yt-dlp: RunPod workers have datacenter IPs that YouTube blocks, so
# channel/auto footage download fails in the cloud (it works on the laptop's home IP). Set
# YTDLP_PROXY on the endpoint to a residential/rotating proxy (http://user:pass@host:port)
# to route every yt-dlp call through a home-looking IP. Empty -> no proxy (uploaded-clips path).
PROXY = os.environ.get("YTDLP_PROXY", "").strip()
# accept a full URL (http://user:pass@host:port) OR Decodo's "host:port:user:pass" list format
if PROXY and "://" not in PROXY and PROXY.count(":") == 3:
    _h, _pt, _u, _pw = PROXY.split(":")
    PROXY = f"http://{urllib.parse.quote(_u, safe='')}:{urllib.parse.quote(_pw, safe='')}@{_h}:{_pt}"
PX = ["--proxy", PROXY] if PROXY else []

def status(stage, pct, detail=""):
    json.dump({"stage": stage, "pct": pct, "detail": detail, "elapsedSec": int(time.time()-T0)},
              open(STATUS, "w"))
    print(f"[{int(time.time()-T0):4d}s] {stage} {pct}% {detail}", flush=True)

def run(cmd, timeout=600, check=False):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=isinstance(cmd, str))
    if check and r.returncode != 0: raise RuntimeError(f"cmd failed: {cmd}\n{r.stderr[-800:]}")
    return r

def gem_key():
    p = f"{WS}/gemini_key.txt"
    return open(p).read().strip() if os.path.exists(p) else None

# kie.ai (OpenAI-compatible, per-model URL). Used when the key isn't a Google AIza key.
KIE_MODEL = os.environ.get("KIE_MODEL", "gemini-2.5-flash")
def kie_chat(prompt, image_paths=None, model=None, timeout=120):
    import base64
    key = gem_key()
    content = [{"type": "text", "text": prompt}]
    for p in (image_paths or []):
        b64 = base64.b64encode(open(p, "rb").read()).decode()
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    body = json.dumps({"messages": [{"role": "user", "content": content if image_paths else prompt}]}).encode()
    req = urllib.request.Request(
        f"https://api.kie.ai/{model or KIE_MODEL}/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    return r["choices"][0]["message"]["content"]

def llm_json(prompt, image_paths=None):
    """Route to Google SDK (AIza keys) or kie (everything else); parse JSON reply."""
    key = gem_key()
    if key and key.startswith("AIza"):
        import google.generativeai as genai
        genai.configure(api_key=key)
        m = genai.GenerativeModel(os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"))
        parts = [prompt]
        if image_paths:
            from PIL import Image
            parts += [Image.open(p) for p in image_paths]
        txt = m.generate_content(parts).text
    else:
        txt = kie_chat(prompt, image_paths)
    txt = re.sub(r"^```json|^```|```$", "", txt.strip(), flags=re.M).strip()
    return json.loads(txt)

# ---------- 1. audio ----------
def prep_audio(audio_in):
    status("audio", 2, "loudnorm -13.8 LUFS")
    run(["ffmpeg", "-y", "-i", audio_in, "-af", "loudnorm=I=-13.8:TP=-1.5:LRA=11",
         "-c:a", "libmp3lame", "-q:a", "2", f"{RT}/narration.mp3"], check=True)
    run(["ffmpeg", "-y", "-i", f"{RT}/narration.mp3", "-ar", "16000", "-ac", "1", f"{WS}/audio.wav"], check=True)

# ---------- 2. transcribe ----------
def transcribe():
    # CPU-only: the image ships no CUDA runtime (libcublas/cudnn), so cuda whisper crashes at
    # encode time (past the init try/except). small.en int8 on CPU is fast enough; render is CPU-bound too.
    status("transcribe", 6, "faster-whisper (CPU)")
    from faster_whisper import WhisperModel
    m = WhisperModel("small.en", device="cpu", compute_type="int8")
    segs, _ = m.transcribe(f"{WS}/audio.wav", vad_filter=True)
    segs = list(segs)
    out = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segs]
    json.dump({"segments": out}, open(f"{RT}/segments.json", "w"), indent=1)
    return out

# ---------- 3. scenes ----------
FALLBACK_TAGS = [
 ("company", ["ceo","corporation","headquarters","amazon","boeing","microsoft","starbucks","factory","plant","company"]),
 ("cityhall", ["mayor","governor","legislature","council","senator","signed","administration","officials","law","court","city hall"]),
 ("tax", ["tax","levy","irs","capital gains","estate","income","rate"]),
 ("money", ["billion","million","revenue","budget","deficit","wealth","millionaire","billionaire","dollars","economy","percent"]),
 ("moving", ["leave","leaving","left","moving","moved","relocat","exodus","migration","depart","fled"]),
 ("people", ["residents","families","households","population","workers","professionals","people"]),
 ("news", ["report","study","data","analysis","ranking","index","survey","poll"]),
]
def build_scenes(segs):
    status("scenes", 10, "merge + tag")
    def topic(t):
        t = t.lower()
        for name, kws in FALLBACK_TAGS:
            if any(k in t for k in kws): return name
        return "skyline"
    scenes, cur = [], None
    for s in segs:
        if cur is None: cur = {"start": s["start"], "end": s["end"], "text": s["text"]}
        elif cur["end"] - cur["start"] >= 5.5:
            scenes.append(cur); cur = {"start": s["start"], "end": s["end"], "text": s["text"]}
        else: cur["end"] = s["end"]; cur["text"] += " " + s["text"]
    if cur: scenes.append(cur)
    for i, sc in enumerate(scenes):
        sc["i"] = i; sc["type"] = "video"; sc["topic"] = topic(sc["text"]); sc["clip"] = None
    json.dump({"scenes": scenes}, open(f"{RT}/scenes.json", "w"), indent=1)
    return scenes

# ---------- 4. source videos (channels OR auto-discovered; cookieless) ----------
def discover_sources(segs, title=""):
    """AUTO mode: Gemini turns the narration into niche search queries, then ytsearch finds
    FULL 8-30min documentary/news-essay videos on that topic (the same kind of footage the
    user's hand-picked channels provide) — NOT stock-clip keywords (those gave bad b-roll)."""
    status("discover", 12, "Gemini: finding on-topic source videos")
    text = " ".join(s["text"] for s in segs)[:6000]
    try:
        q = llm_json("This is a documentary narration" + (f" titled '{title}'" if title else "") +
                     ". Write 5 YouTube SEARCH QUERIES that find FULL 10-20 minute documentary / "
                     "news-essay VIDEOS about this exact topic+niche, whose b-roll matches the story. "
                     "No stock footage queries, no shorts. Reply ONLY JSON {\"queries\":[...]}\n\n" + text)
        queries = [str(x) for x in q.get("queries", [])][:6]
    except Exception as e:
        print("  query-gen fallback:", e)
        queries = [segs[0]["text"][:60] + " documentary"]
    vids, seen_ch = [], set()
    for qy in queries:
        r = run([sys.executable, "-m", "yt_dlp", *PX, "--flat-playlist",
                 "--print", "%(id)s|%(duration)s|%(channel)s", "--playlist-end", "6",
                 "--extractor-args", "youtube:player_client=web_safari,android",
                 f"ytsearch6:{qy}"], timeout=180)
        for line in r.stdout.strip().splitlines():
            p = line.split("|")
            if len(p) < 3: continue
            try: dur = float(p[1])
            except: dur = 0
            ch = "|".join(p[2:])
            if not (480 <= dur <= 2400): continue      # full videos only — no shorts/streams
            if ch in seen_ch: continue                  # spread across distinct channels
            seen_ch.add(ch); vids.append(("auto", p[0]))
    print(f"  discovered {len(vids)} source videos across {len(seen_ch)} channels")
    return vids[:8]

def download_videos(vids):
    status("download", 14, f"{len(vids)} source videos")
    got = 0
    for i, (tag, vid) in enumerate(vids):
        base = f"{SRC}/{tag[:3]}_{vid}"
        if os.path.exists(base + ".mp4"): got += 1; continue
        for args in (["--extractor-args", "youtube:player_client=web_safari,android"],
                     ["--extractor-args", "youtube:player_client=tv"],):
            run([sys.executable, "-m", "yt_dlp", *PX, "-f", "bv*[height<=1080]/b[height<=1080]/best", *args,
                 "--remux-video", "mp4", "--socket-timeout", "30", "--retries", "3", "--fragment-retries", "3",
                 "-o", base + ".%(ext)s", "-q", "--no-warnings",
                 f"https://www.youtube.com/watch?v={vid}"], timeout=900)
            if os.path.exists(base + ".mp4") and os.path.getsize(base + ".mp4") > 1e6:
                got += 1; break
        status("download", 14 + int((i + 1) / max(1, len(vids)) * 16), f"{got}/{len(vids)} videos")
    if got == 0:
        hint = "set YTDLP_PROXY (residential proxy) on the endpoint" if not PROXY else \
               f"proxy is set but all downloads failed — check the proxy is residential + has quota"
        raise RuntimeError(f"ALL downloads failed (datacenter-IP block): {hint}")
    return got

def _channel_url(ch):
    """Accept a bare handle, @handle, or any YouTube channel URL (with ?si=... etc.) -> /videos URL."""
    ch = ch.strip()
    m = re.search(r"@([A-Za-z0-9._-]+)", ch)            # @handle or .../@handle?si=...
    if m:
        return f"https://www.youtube.com/@{m.group(1)}/videos"
    m = re.search(r"youtube\.com/((?:channel|c|user)/[A-Za-z0-9._-]+)", ch)   # /channel/UC.., /c/.., /user/..
    if m:
        return f"https://www.youtube.com/{m.group(1)}/videos"
    return f"https://www.youtube.com/@{ch.lstrip('@')}/videos"

def fetch_channels(channels, per=2):
    vids = []
    for ch in channels:
        url = _channel_url(ch)
        r = run([sys.executable, "-m", "yt_dlp", *PX, "--flat-playlist", "--print", "%(id)s",
                 "--playlist-end", str(per),
                 "--extractor-args", "youtube:player_client=web_safari,android",
                 url], timeout=150)
        ids = r.stdout.split()
        if not ids: print(f"  list FAILED {url}: {r.stderr[-200:]}")
        vids += [(ch, v) for v in ids]
    return download_videos(vids)

_VIDEXT = (".mp4", ".mov", ".webm", ".m4v", ".mkv", ".avi")

def _fetch_clip_source(u, j):
    """Download one clip source to local file(s). Handles direct URLs, Dropbox share links, and
    Google Drive file OR folder links (RunPod's datacenter bandwidth = no slow home upload).
    Returns a list of local video file paths."""
    import urllib.request as _ur
    u = u.strip()
    out = []
    try:
        if "drive.google.com" in u or "docs.google.com" in u:
            import gdown
            if "/folders/" in u:                       # a whole Drive folder of clips
                d = f"{SRC}/gd_{j}"; os.makedirs(d, exist_ok=True)
                # gdown 6.x download_folder has no file-count limit -> it would fetch the WHOLE folder
                # (can be thousands of clips). Instead list it (skip_download) then download a bounded,
                # evenly-spread sample by id — ample b-roll variety without downloading everything.
                listing = gdown.download_folder(url=u, output=d, skip_download=True, quiet=True, use_cookies=False) or []
                N = 60
                step = max(1, len(listing) // N)
                picks = [listing[k] for k in range(0, len(listing), step)][:N]
                def _dl(it):
                    op = os.path.join(d, os.path.basename(getattr(it, "path", "") or f"f{it.id}.mp4"))
                    try:
                        gdown.download(id=it.id, output=op, quiet=True)
                        return op if os.path.exists(op) else None
                    except Exception as ee:
                        print("  drive file fail:", getattr(it, "path", "?"), str(ee)[:80]); return None
                from concurrent.futures import ThreadPoolExecutor
                out = [p for p in ThreadPoolExecutor(8).map(_dl, picks) if p]   # 8 parallel = ~8x faster
            else:                                       # a single Drive file (handles confirm token)
                o = f"{SRC}/gd_{j}.mp4"; gdown.download(url=u, output=o, quiet=True, fuzzy=True)
                if os.path.exists(o): out = [o]
        else:
            if "dropbox.com" in u:                      # share link -> direct download
                u = u.split("?")[0] + "?dl=1"
                u = u.replace("www.dropbox.com", "dl.dropboxusercontent.com")
            o = f"{SRC}/own_src_{j}.mp4"; _ur.urlretrieve(u, o); out = [o]
    except Exception as e:
        print("  clip source fail:", u[:70], e)
    return [f for f in out if f.lower().endswith(_VIDEXT) and os.path.getsize(f) > 50000]

def fetch_own_clips(urls):
    """Clip sources = direct URLs / Dropbox links / Google Drive file or folder links. Each video is
    sliced into one or more 7s pool clips (no 90s gate). Fetched on RunPod, so no slow home upload."""
    status("download", 16, f"{len(urls)} clip source(s)")
    raw = []
    for j, u in enumerate(urls):
        if u.strip():
            raw += _fetch_clip_source(u, j)
    idx = 0
    for src in raw:
        d = float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                       "-of", "csv=p=0", src]).stdout.strip() or 0)
        if d <= 0:
            continue
        n = 1 if d <= 8 else min(12, max(1, int(d // 8)))
        loop_args = ["-stream_loop", "-1"] if d < 7.2 else []   # loop short clips to fill the full 7s -> no end-freeze in render
        for k in range(n):
            t = 0.0 if n == 1 else d * k / n
            o = f"{POOL}/own_{idx:03d}.mp4"
            run(["ffmpeg", "-y", *loop_args, "-ss", f"{t:.1f}", "-i", src, "-t", "7", "-an",
                 "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", o], timeout=120)
            if os.path.exists(o) and os.path.getsize(o) > 40000:
                idx += 1
    print(f"  own clips -> {idx} pool clips from {len(raw)} source files")
    return idx

# ---------- 5. slice ----------
def slice_videos(n_per=24, clip=7):
    status("slice", 32, "cutting 7s segments")
    idx = 0
    for f in sorted(os.listdir(SRC)):
        if not f.endswith(".mp4"): continue
        p = f"{SRC}/{f}"
        d = float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p]).stdout.strip() or 0)
        if d < 90: continue
        span = d - 55
        for k in range(n_per):
            t = 30 + span * k / n_per
            o = f"{POOL}/chan_{idx:03d}.mp4"
            run(["ffmpeg", "-y", "-ss", f"{t:.1f}", "-i", p, "-t", str(clip), "-an",
                 "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", o], timeout=120)
            if os.path.exists(o) and os.path.getsize(o) > 40000: idx += 1
    return idx

# ---------- 6. auto-QC (OpenCV): drop static text cards ----------
def auto_qc():
    status("qc", 48, "OpenCV motion+text filter")
    import cv2, numpy as np
    keep = {}
    for f in sorted(os.listdir(POOL)):
        if not f.endswith(".mp4"): continue
        if f.startswith("own_"):            # user-chosen clips (upload/Drive/Dropbox): always keep, skip text-card filter
            keep[f] = "news"; continue
        if not f.startswith("chan_"): continue
        cap = cv2.VideoCapture(f"{POOL}/{f}")
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); ok = True
        if n > 20:
            frames = []
            for fi in (5, n // 2, n - 10):
                cap.set(cv2.CAP_PROP_POS_FRAMES, fi); r, fr = cap.read()
                if r: frames.append(cv2.cvtColor(cv2.resize(fr, (320, 180)), cv2.COLOR_BGR2GRAY))
            if len(frames) >= 2:
                motion = float(np.mean([np.mean(cv2.absdiff(frames[i], frames[i + 1])) for i in range(len(frames) - 1)]))
                edges = cv2.Canny(frames[len(frames) // 2], 100, 200)
                edge_density = float(np.mean(edges > 0))
                # static (motion<1.5) AND text-heavy (edges>8%) = title/text card -> drop
                if motion < 1.5 and edge_density > 0.08: ok = False
        cap.release()
        if ok: keep[f] = "news"
    json.dump(keep, open(f"{RT}/clip_themes.json", "w"), indent=1)
    return keep

# ---------- 6b. Gemini Flash vision tagging (Google or kie) ----------
def gemini_tag(themes):
    key = gem_key()
    if not key: return themes
    status("tag", 56, f"Gemini Flash vision tagging ({len(themes)} clips)")
    VALID = {t for t, _ in FALLBACK_TAGS} | {"skyline", "streets", "corporate"}
    names = sorted(themes)
    CHUNK = 20
    tagged = 0
    for s in range(0, len(names), CHUNK):
        chunk = names[s:s + CHUNK]
        paths, idx = [], []
        for c in chunk:
            jp = f"/tmp/{c}.jpg"
            run(["ffmpeg", "-y", "-ss", "3", "-i", f"{POOL}/{c}", "-frames:v", "1",
                 "-vf", "scale=300:-1", jp], timeout=60)
            if os.path.exists(jp): paths.append(jp); idx.append(c)
        if not paths: continue
        prompt = ("Tag each numbered image (in order) with ONE theme from: skyline,streets,corporate,"
                  "company,money,tax,moving,cityhall,people,news. cityhall=politicians/podiums/chambers, "
                  "company=factories/logos/industry, news=anchors/interviews/articles. "
                  f"Reply ONLY JSON like {{\"0\":\"theme\"}}. {len(paths)} images.")
        try:
            tags = llm_json(prompt, paths)
            for k, v in tags.items():
                i = int(k)
                if i < len(idx) and v in VALID: themes[idx[i]] = v; tagged += 1
        except Exception as e:
            print(f"  tag chunk {s} skipped:", e)
        status("tag", 56 + int((s + CHUNK) / max(1, len(names)) * 5), f"{tagged} clips vision-tagged")
    json.dump(themes, open(f"{RT}/clip_themes.json", "w"), indent=1)
    return themes

# ---------- 7. match ----------
def match(scenes, themes):
    status("match", 62, "greedy theme match")
    PREF = {"skyline": ["skyline", "streets", "corporate"], "streets": ["streets", "skyline", "people"],
            "corporate": ["corporate", "company", "skyline"], "company": ["company", "corporate", "money"],
            "money": ["money", "corporate", "news"], "tax": ["tax", "money", "corporate"],
            "moving": ["company", "corporate", "streets"], "cityhall": ["cityhall", "news", "people"],
            "people": ["people", "streets", "cityhall"], "news": ["news", "people", "cityhall"]}
    FB = ["company", "corporate", "news", "people", "cityhall", "money", "skyline", "streets", "tax"]
    avail = defaultdict(list)
    for c, t in themes.items():
        if os.path.exists(f"{POOL}/{c}"): avail[t].append(c)
    for t in avail: avail[t].sort()
    usec = defaultdict(int); last = {}
    for sc in scenes:
        order = PREF.get(sc["topic"], ["news"]) + [t for t in FB if t not in PREF.get(sc["topic"], [])]
        pick = None
        for t in order:
            for c in avail.get(t, []):
                if usec[c] == 0: pick = c; break
            if pick: break
        if not pick:
            best = None
            for t in order:
                for c in avail.get(t, []):
                    gap = sc["i"] - last.get(c, -999)
                    k = (usec[c], -gap)
                    if gap >= 8 and (best is None or k < best[0]): best = (k, c)
            pick = best[1] if best else (sorted(themes)[0] if themes else None)
        if pick:
            sc["clip"] = f"{POOL}/{pick}"; usec[pick] += 1; last[pick] = sc["i"]
    json.dump({"scenes": scenes}, open(f"{RT}/scenes.json", "w"), indent=1)

# ---------- 8. overlays (Gemini Flash director via Google or kie) ----------
def overlays(scenes):
    key = gem_key()
    segs = json.load(open(f"{RT}/segments.json"))["segments"]
    if key:
        status("director", 68, "Gemini Flash authoring overlays")
        try:
            sys.path.insert(0, f"{WS}/runpod")
            from director import build_prompt, validate
            data = llm_json(build_prompt(segs))
            out = validate(data, segs[-1]["end"])
            # never allow grunge styles
            out["overlays"] = [o for o in out["overlays"] if o.get("component") != "GrungeTab"]
            json.dump(out, open(f"{RT}/edit.json", "w"), indent=1)
            print(f"  director wrote {len(out['overlays'])} overlays")
            return
        except Exception as e:
            print("  director failed -> fallback:", e)
    status("director", 68, "fallback minimal overlays")
    ovl = [{"start": 0.5, "dur": 4.5, "component": "SectionTitle",
            "props": {"headline": "THE STORY", "subtitle": ""}, "sfx": "riser"}]
    json.dump({"theme": "business", "grade": {"vignette": 0.35, "grain": 0.06}, "overlays": ovl},
              open(f"{RT}/edit.json", "w"), indent=1)

# ---------- 9. portraits ----------
def portraits(segs):
    status("portraits", 74, "Wikipedia portraits for mentioned people")
    text = " ".join(s["text"] for s in segs)
    cands = set(re.findall(r"(?:Mayor|Governor|Senator|Gov\.|Sen\.|CEO)\s+([A-Z][a-z]+ [A-Z][a-z]+)", text))
    cands |= set(re.findall(r"\b([A-Z][a-z]+ [A-Z][a-z]+)\b(?=,? (?:the )?(?:founder|former|billionaire|investor))", text))
    os.makedirs(f"{RT}/portraits", exist_ok=True)
    UA = {"User-Agent": "video-pipeline/1.0"}
    def get(u):
        return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30).read()
    from PIL import Image
    got = {}
    for name in list(cands)[:10]:
        slug = name.lower().replace(" ", "_")
        try:
            time.sleep(3)
            s = json.loads(get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(name)}"))
            img = (s.get("originalimage") or s.get("thumbnail") or {}).get("source")
            if not img: continue
            im = Image.open(io.BytesIO(get(img))).convert("RGB"); im.thumbnail((800, 1000))
            im.save(f"{RT}/portraits/{slug}.jpg", "JPEG", quality=85); got[name] = slug
        except Exception as e: print("  portrait skip", name, e)
    # naive placement: first mention of each name -> PortraitFrame
    if got:
        edit = json.load(open(f"{RT}/edit.json"))
        side = "right"
        for name, slug in got.items():
            for s in segs:
                if name in s["text"]:
                    edit["overlays"].append({"start": round(s["start"] + 0.2, 2), "dur": 4,
                        "component": "PortraitFrame",
                        "props": {"imgSrc": f"portraits/{slug}.jpg", "side": side, "label": name.upper()},
                        "sfx": "pop"})
                    side = "left" if side == "right" else "right"
                    break
        edit["overlays"].sort(key=lambda o: o["start"])
        json.dump(edit, open(f"{RT}/edit.json", "w"), indent=1)

# ---------- 10. render ----------
def render(scenes):
    for stub in ("overlays.json",):
        p = f"{RT}/{stub}"
        if not os.path.exists(p): json.dump({"overlays": []}, open(p, "w"))
    frames = max(1, round((scenes[-1]["end"] + 0.6) * 30))
    status("render", 80, f"{frames} frames")
    r = None
    for conc in (8, 4):                              # ladder+retry: big clip pools crash Chrome at high concurrency
        run(f"rm -f {OUT}/final.mp4", timeout=30)
        r = run(f"cd {WS}/remotion && npx remotion render src/index.ts AutoDoc {OUT}/final.mp4 "
                f"--public-dir={RT} --concurrency={conc} --image-format=jpeg --jpeg-quality=95 "
                f"--x264-preset=medium --crf=19 --offthreadvideo-cache-size-in-bytes=3000000000 "
                f"--timeout=120000 2>&1 | tail -6", timeout=3600)   # --timeout: slow-serving clips; cache: stability
        if os.path.exists(f"{OUT}/final.mp4") and os.path.getsize(f"{OUT}/final.mp4") > 500000:
            break
        print(f"  render concurrency={conc} produced no file -> retrying lower")
    print(r.stdout[-300:])
    if not os.path.exists(f"{OUT}/final.mp4"): raise RuntimeError("render produced no file")
    status("done", 100, f"final.mp4 {os.path.getsize(f'{OUT}/final.mp4')//1048576} MB")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True, help="path or URL to the voiceover")
    ap.add_argument("--channels", default="", help="comma-separated channel handles (no @)")
    ap.add_argument("--source", default=None, choices=["channels", "auto", "clips"],
                    help="auto = Gemini discovers on-topic source videos; clips = use --own-clips URLs")
    ap.add_argument("--own-clips", default="", help="comma-separated URLs of user-uploaded video clips")
    ap.add_argument("--title", default="", help="video title (improves auto discovery)")
    ap.add_argument("--skip-source", action="store_true", help="reuse existing broll_pool")
    a = ap.parse_args()
    if a.audio.startswith("http"):  # SaaS: audio arrives as a URL (e.g. Supabase Storage)
        import urllib.request as _ur
        _ur.urlretrieve(a.audio, f"{WS}/in_audio.mp3"); a.audio = f"{WS}/in_audio.mp3"
    prep_audio(a.audio)
    segs = transcribe()
    scenes = build_scenes(segs)
    mode = a.source or ("clips" if a.own_clips else ("channels" if a.channels else "auto"))
    if not a.skip_source:
        if mode == "clips":
            if fetch_own_clips([u for u in a.own_clips.split(",") if u.strip()]) == 0:
                raise RuntimeError("no usable uploaded clips")
        elif mode == "channels":
            fetch_channels([c.strip() for c in a.channels.split(",") if c.strip()])
            slice_videos()
        else:
            download_videos(discover_sources(segs, a.title))
            slice_videos()
    themes = auto_qc()
    themes = gemini_tag(themes)
    match(scenes, themes)
    overlays(scenes)
    portraits(segs)
    render(scenes)

