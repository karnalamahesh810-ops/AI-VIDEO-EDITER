import sys, os, json, glob, time
sys.path.insert(0, r"C:\Users\karna\AppData\Local\Temp\claude\C--ThumGenius\7bdcd241-daa1-45bb-abcc-fca27af8754a\scratchpad\celeb"); import env
SP = os.path.dirname(os.path.abspath(__file__))
os.environ["OPENROUTER_API_KEY"] = json.load(open(os.path.join(SP, "..", "openrouter_secret.json")))["api_key"]
os.environ["CELEB_FACE_CACHE"] = os.path.join(SP, "faces_cache.json")
from src.celeb import script, reel, fx, faces
from src.celeb.compose import duration
stage = sys.argv[1] if len(sys.argv) > 1 else "all"
out = os.path.join(SP, "celeb_test_5min.mp4")
blocks = script.parse(open(os.path.join(SP, "script5.txt"), encoding="utf-8").read())
narr = json.load(open(os.path.join(SP, "voice5_order.json")))
sources = {}
for f in glob.glob(os.path.join(SP, "src_dl", "yt_*.mp4")):
    vid = os.path.basename(f)[3:14]
    sources[vid] = reel.Source(vid, f, json.load(open(os.path.join(SP, "src_dl", f"words_{vid}.json"))),
                               [float(x) for x in open(os.path.join(SP, "src_dl", f"cuts_{vid}.txt"))], duration(f))
tl = reel.build(blocks, narr, sources)
print("total", tl.total, "shots", len(tl.shots), "captions", len(tl.captions), "marks", len(tl.marks))
json.dump({"log": tl.log, "total": tl.total, "clip_spans": tl.clip_spans, "narr_spans": tl.narr_spans,
           "marks": [m.__dict__ for m in tl.marks]}, open(os.path.join(SP, "timeline5.json"), "w"), indent=1)
work = os.path.join(SP, "render5")
t0 = time.time()
base = os.path.join(work, "base.mp4")
if stage in ("all", "base"):
    base = reel.render_base(tl, work); print("base", round(time.time() - t0))
if stage in ("all", "mix", "base"):
    mixp = reel.mix(tl, work, music=r"C:\ThumGenius\gpu_tools_test\music_ai_uplifting_bed.mp3",
                    sfx=r"C:\ThumGenius-celeb\runpod\remotion\public\sfx\camera-flash-pop.mp3"); print("mix", round(time.time() - t0))
posters = {"Spider-Man Far From Home": os.path.join(SP, "posters", "ffh.jpg"),
           "Spider-Man No Way Home": os.path.join(SP, "posters", "nwh.jpg"),
           "Spider-Man Brand New Day": os.path.join(SP, "posters", "bnd.jpg")}
els = reel.elements(tl, base, posters)
print("elements", len(els), "faces", faces.spent)
fx.composite(base, els, out, audio=os.path.join(work, "mix.wav"), progress=lambda i, n: print(f"  {i}/{n}", flush=True) if i % 1800 == 0 else None)
print("done", round(time.time() - t0), out)
