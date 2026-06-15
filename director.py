"""DIRECTOR — the smart auto-editor brain (serverless copy, baked into the image).
Reads the narration (segments.json) and decides WHICH template animation to place
WHERE, with WHAT data + WHICH sfx -> writes edit.json (consumed by the AutoDoc renderer).

pipeline_sl.py imports build_prompt + validate from this module, so it MUST ship in the
image (Dockerfile copies director.py into /app). build_prompt/validate are pure functions;
the RUNTIME path below is only used by main() for standalone local runs.

Output is validated against the real component registry + sfx set, so it can't emit
components or sounds that don't exist."""
import json, os, re

RUNTIME = os.environ.get("RUNTIME_DIR") or (
    r"C:\app\vidrush_style\runtime" if os.name == "nt" else "/app/runtime"
)
SEG = os.path.join(RUNTIME, "segments.json")
OUT = os.path.join(RUNTIME, "edit.json")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")


def _read_key():
    k = os.environ.get("GEMINI_API_KEY")
    if not k:
        p = os.path.join(RUNTIME, "gemini_key.txt")
        if os.path.exists(p):
            k = open(p, encoding="utf-8").read().strip()
    return k


# component -> (when to use, props hint). The director may only choose from these.
CATALOG = {
    "FactCard": ("THE CHANNEL SIGNATURE — a titled ✓ checklist of 3-5 facts/reasons/risks/criteria/findings. "
                 "Use this often, whenever the narration enumerates or summarizes related points (why X happened, "
                 "what's at stake, the warning signs, the conditions). title = short ALL-CAPS label.",
                 "title:string, items:string[3-5 short phrases], variant?:'panel'|'paper', side?:'right'|'left'|'center'"),
    "NewsLowerThird": ("news-style alert lower-third: a kicker tag + a bold headline + one body line; "
                       "for a key reveal, finding, or authoritative statement",
                       "kicker?:string (short, e.g. 'USGS ALERT'), headline:string, body?:string"),
    "HookCaption": ("opening hook / VO subtitle with a red caret", "lines:string[], keyword?:string"),
    "KineticTitle": ("full-screen chapter title (big caps)", "lines:string[]"),
    "SectionTitle": ("chapter divider headline + subtitle over b-roll", "headline:string, subtitle?:string"),
    "LowerThirdTitle": ("a sentence headline lower-third", "lines:string[]"),
    "LowerThirdName": ("a person's name + title (interview)", "name:string, title?:string"),
    "DateStamp": ("a date marker", "day:string, year:string, typed?:bool"),
    "BigNumber": ("a single big number/stat in the line", "value:number, prefix?, suffix?, compact?, label?, countup?:bool, scrim?:bool, align?:'center'|'tl'"),
    "StatChip": ("a single percent/figure with a label", "value:number, suffix?, label?, countup?:bool"),
    "PillChyron": ("a number+label pill lower-third", "value:string, label:string"),
    "StatCard": ("3-5 bullet fact panel (plain, no checkmarks)", "title:string, bullets:string[], side?:'left'|'right'"),
    "ComparisonTable": ("two-option comparison", "leftTitle, rightTitle, rows:[{label,left,right}]"),
    "CountdownList": ("ranked list #N..#1", "title?, items:[{rank,label,value?}]"),
    "LineChart": ("a trend over time", "title, series:[{points:number[]}], xLabels?, yLabel?"),
    "AreaChart": ("a filled trend", "title?, points:number[], xLabels?, yLabel?"),
    "BarChart": ("compare categories (vertical)", "title, bars:[{label,value,spotlight?}], valueFmt?"),
    "HBarCompare": ("compare categories (horizontal)", "title?, bars:[{label,value,spotlight?}], valueFmt?"),
    "DonutStat": ("a single proportion %", "value:number, suffix?, label?"),
    "PieBreakdown": ("a breakdown into parts", "title?, slices:[{label,value}]"),
    "BarGauge": ("a single % gauge (HUD)", "value:number, suffix?, label?, footnote?"),
    "RouteMap": ("movement A->B on a map", "from:{x,y,label}, to:{x,y,label}"),
    "MapHighlight": ("highlight a place on a map", "target:{x,y,r}, label:string"),
    "MigrationMap": ("flows across a region", "arrows:[{fromX,fromY,toX,toY}], label?"),
    "PullQuote": ("a spoken quote", "quote:string, cite?:string, bg?:'black'|'broll', typed?:bool"),
    "HighlighterQuote": ("a written passage w/ a highlighted phrase", "paragraph:string, highlightPhrase?:string"),
    "HighlightCaption": ("emphasis caption w/ a highlighted line", "lines:[{text,highlight?:bool}]"),
    "GhostKeyword": ("faint big keyword", "text:string"),
    "ProcessSteps": ("a sequence of steps", "steps:[{label,sub?}]"),
    "NodeIntro": ("a concept mind-map", "nodes:[{label,x,y}], links:[[i,j]]"),
    "Timeline": ("a point on a timeline", "ticks:string[], activeIndex:number, label:string"),
    "SpotlightCallout": ("isolate a spot on screen", "x,y,r, label?, shape?:'circle'|'rect'"),
    "ArrowCallout": ("point at a spot", "fromX,fromY,toX,toY, label:string"),
    "DocumentCard": ("show figures like a document", "title?, rows:[{label,value}], highlightRow?, source?"),
    "NewspaperClipping": ("a headline as evidence", "headline:string, dek?, source?, circle?:bool"),
    "ArchivalPhoto": ("an old/archival photo beat", "caption?:string, bw?:bool, full?:bool"),
    "PolaroidFrame": ("a snapshot beat", "caption:string, rotate?:number"),
    "PortraitFrame": ("a person portrait", "side?:'left'|'right', label?:string"),
    "TweetCard": ("a social post quote", "handle, time, body, avatarLetter?, bgColor?"),
    "LogoTiles": ("compare brands/entities", "tiles:[{label,color?}]"),
    "PhotoCarousel": ("a few images in sequence", "items:[{label?}], number?"),
    "StockCrashChart": ("a market/decline moment", "title?:string"),
    "BlueprintScroll": ("a technical/schematic beat", "caption?:string"),
    "SplitScreen": ("before/after two-up", "left:{label?}, right:{label?}"),
}
SFX = ["whoosh", "pop", "impact", "boom", "click", "riser", "swoosh", "cash", "type", "paper", "highlight", "ding", "glitch"]


def build_prompt(segs):
    cat = "\n".join(f"- {n}: {use}  PROPS: {props}" for n, (use, props) in CATALOG.items())
    script = "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in segs)
    total = segs[-1]["end"] if segs else 240
    target = max(8, round(total / 16))  # ~one overlay every 16s
    facts = max(2, round(total / 150))  # a couple of FactCards per ~2.5 min
    return f"""You are a motion-graphics DIRECTOR for a faceless documentary (the "Boeing-leaves-Seattle / invasive-species / supervolcano" reference style). Given the narration (with timestamps), place on-screen animations + sound effects so it feels like that polished, graphic-rich explainer.

THE LOOK (match these reference channels):
- They lean HARD on one signature device: the FactCard — a titled card with a colored header and 3-5 checkmark rows. Use it whenever the narration lists reasons, risks, factors, criteria, findings, or a summary of points. Aim for about {facts} FactCards across this video.
- Big single stats land as BigNumber (with a count-up + scrim) or a StatChip. Dates land as DateStamp ("OCTOBER" / "2020"). Key reveals / authoritative statements land as NewsLowerThird (kicker + headline + body). Section changes use SectionTitle / KineticTitle. Quotes use PullQuote.
- Maps (MapHighlight / RouteMap) when a place or a move between places is named.

RULES:
- Place each overlay ON the line it illustrates (start = seconds from the timestamps). dur = 3.5-7s (FactCards can be up to 7s so they're readable).
- This is a GRAPHIC-RICH style: aim for roughly ONE overlay every 12-20 seconds (about {target} overlays total). Keep them VARIED — never the same component twice in a row, and never overlap two overlays in time.
- Choose the component whose purpose matches the line. Fill props with REAL content from the narration (actual numbers, names, places, short paraphrased points). Keep every line of text SHORT and punchy (FactCard items = 3-7 words each).
- Use ONLY clean, modern overlays. Never use torn/grunge/distressed styles.
- Add an `sfx` from this set when it fits: {SFX} (impact/boom for big numbers, pop for cards, whoosh for cuts, riser for builds, cash for money, ding for highlights).
- Set a global "theme" (business|navy|minimal|essay) that fits the topic, and "grade":{{"vignette":0.4,"grain":0.08}}.

COMPONENTS (name: when to use; props):
{cat}

NARRATION:
{script}

Return ONLY valid JSON of this shape:
{{"theme":"navy","grade":{{"vignette":0.4,"grain":0.08}},"overlays":[
 {{"start":3.2,"dur":4.5,"component":"SectionTitle","props":{{"headline":"THE EXIT","subtitle":"How a 110-year-old home was lost"}},"sfx":"whoosh"}},
 {{"start":28.0,"dur":6.5,"component":"FactCard","props":{{"title":"WHY BOEING LEFT","items":["Record $8.7B tax break expired","Repeated relocation threats","Cheaper non-union labor","Closer to defense contracts"],"variant":"panel","side":"right"}},"sfx":"pop"}},
 {{"start":54.0,"dur":4.5,"component":"BigNumber","props":{{"value":2200,"label":"WASHINGTON JOBS LOST","countup":true,"scrim":true}},"sfx":"impact"}}
]}}"""


def validate(data, total):
    names, sset = set(CATALOG.keys()), set(SFX)
    clean = []
    for o in data.get("overlays", []):
        if o.get("component") not in names:
            continue
        try:
            st, du = float(o["start"]), float(o.get("dur", 4))
        except Exception:
            continue
        if st < 0 or st > total:
            continue
        o["start"], o["dur"] = round(st, 2), round(max(2.0, min(8.0, du)), 2)
        if o.get("sfx") not in sset:
            o.pop("sfx", None)
        if not isinstance(o.get("props"), dict):
            o["props"] = {}
        clean.append(o)
    clean.sort(key=lambda x: x["start"])
    # de-overlap: nudge any overlay that starts before the previous one ends
    for i in range(1, len(clean)):
        prev = clean[i - 1]
        if clean[i]["start"] < prev["start"] + min(prev["dur"], 3.0):
            clean[i]["start"] = round(prev["start"] + min(prev["dur"], 3.0), 2)
    return {"theme": data.get("theme", "business"),
            "grade": data.get("grade", {"vignette": 0.4, "grain": 0.08}),
            "overlays": clean}


def main():
    segs = json.load(open(SEG, encoding="utf-8"))["segments"]
    total = segs[-1]["end"]
    prompt = build_prompt(segs)
    key = _read_key()
    if not key:
        open(os.path.join(RUNTIME, "director_prompt.txt"), "w", encoding="utf-8").write(prompt)
        print("GEMINI_API_KEY not set. Wrote director_prompt.txt — set the key and re-run, "
              "or paste that prompt into any LLM and save its JSON as edit.json.")
        return
    import google.generativeai as genai
    genai.configure(api_key=key)
    model = genai.GenerativeModel(MODEL)
    resp = model.generate_content(prompt, generation_config={"response_mime_type": "application/json", "temperature": 0.6})
    raw = re.sub(r"^```json|```$", "", resp.text.strip(), flags=re.M)
    out = validate(json.loads(raw), total)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"WROTE {OUT}  overlays={len(out['overlays'])}  (model={MODEL})")


if __name__ == "__main__":
    main()
