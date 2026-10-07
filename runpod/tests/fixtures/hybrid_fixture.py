"""
A fixed footage plan - lines, shots, sourced assets, job input - for the
presenter-hybrid tests (tests/test_presenter_hybrid.py). It imports nothing
from the worker: the classes come in as arguments, so the SAME inputs can be
built against the base commit's code (68205fc) to make the golden timeline
(tests/fixtures/hybrid_golden_timeline.json) and against today's code to
prove a timeline without a presenter block is byte-for-byte what it was.
"""

LINES = [
    "Under the Texas Panhandle sits the water that built this country, and it is running out.",
    "It is called the Ogallala Aquifer, and it stretches under eight states.",
    "Farmers pump it up through center pivots to grow corn, cotton and wheat.",
    "Ranchers pump it for their cattle, from windmills beside the stock tanks.",
    "But it fills back up far slower than we take it out.",
    "In some Panhandle counties the water table has dropped more than 100 feet since 1950.",
    "Now, I have seen what that looks like up close.",
    "When I started cooking for ranch crews, the windmills never stopped turning.",
    "Today a lot of those windmills stand still, and the wells under them are dry.",
    "The drought of 2011 was the worst one-year drought Texas ever recorded.",
    "Ponds turned to cracked mud, and the grass burned brown by June.",
    "Ranchers hauled water in trucks, or sold off half the herd before summer.",
    "Here is the part that worries me most.",
    "Once a stretch of the aquifer is pumped out, it can take thousands of years to fill again.",
    "Some towns are already drilling deeper wells, at 3 times the old cost.",
    "Some farms have gone back to dryland crops that live on rain alone.",
    "So the next time you see a windmill standing still, you will know why.",
    "Tell me what county you are in, and whether your wells are holding up.",
]

SUBJECTS = ["Texas Panhandle", "Ogallala Aquifer", "center pivot irrigation", "windmill stock tank",
            "Ogallala Aquifer", "water table", "ranch", "windmill", "dry well", "2011 Texas drought",
            "cracked mud pond", "cattle water truck", "Ogallala Aquifer", "aquifer", "water well drilling",
            "dryland farming", "windmill", "ranch"]


def words_for(lines, Word, wps=2.7, gap=0.45):
    out, t, per_line = [], 0.0, []
    for sent in lines:
        ws = []
        for tok in sent.split():
            ws.append(Word(text=tok, start=round(t, 3), end=round(t + 0.9 / wps, 3)))
            t += 1.0 / wps
        t += gap
        out.extend(ws)
        per_line.append(ws)
    return out, per_line


def inputs(Segment, Word, MediaAsset):
    """(segments, shots, assets, inp, duration): a 18-line, ~70 s footage plan with dates and numbers."""
    _all, per_line = words_for(LINES, Word)
    segments = [Segment(text=line, start=ws[0].start, end=ws[-1].end, words=list(ws))
                for line, ws in zip(LINES, per_line)]
    duration = round(per_line[-1][-1].end + 0.7, 3)
    shots, assets = [], []
    for i, line in enumerate(LINES):
        image = i % 4 == 3
        shots.append({"query": f"{SUBJECTS[i]} footage", "visualType": "image" if image else "footage",
                      "overlay": None, "intent": SUBJECTS[i], "subject": SUBJECTS[i],
                      "subjectType": "place", "fallbacks": [SUBJECTS[i]], "prompt": ""})
        seconds = segments[i].end - segments[i].start + 1.5
        if image:
            assets.append(MediaAsset(kind="image", source="wikimedia",
                                     url=f"https://upload.wikimedia.org/fixture/picture_{i:02d}.jpg",
                                     width=1920, height=1080, attribution="Wikimedia Commons", license="cc-by",
                                     query=shots[-1]["query"], relevance_score=0.82, quality=0.7,
                                     content_description=f"a photo of the {SUBJECTS[i]}"))
        else:
            vid = f"FIXTURE{i:04d}"[:11]
            assets.append(MediaAsset(kind="video", source="youtube",
                                     url=f"https://www.youtube.com/watch?v={vid}&t={10 + i}",
                                     width=1920, height=1080, duration=round(seconds, 2),
                                     attribution="YouTube (CC BY)", license="cc-by", query=shots[-1]["query"],
                                     relevance_score=0.86, quality=0.74, moment_key=f"yt:{vid}@{10 + i}",
                                     content_description=f"footage of the {SUBJECTS[i]}"))
    inp = {"title": "The Water Under Texas Is Running Out", "voice_lufs": -16.0, "video_style": "",
           "brief": {"kind": "explainer", "summary": "The Ogallala Aquifer under the Texas Panhandle is running dry",
                     "event": "Ogallala Aquifer decline", "year": 2026, "recent": False,
                     "places": ["Texas Panhandle"], "people": [], "hookBeats": [0], "cast": [], "sections": []}}
    return segments, shots, assets, inp, duration


def build(timeline, Segment, Word, MediaAsset):
    """The fixture's render document, built by the given timeline module."""
    segments, shots, assets, inp, duration = inputs(Segment, Word, MediaAsset)
    return timeline.build(segments, shots, assets, audio_url="https://example.test/fixture/narration.mp3",
                          audio_duration=duration, inp=inp, planner="rules", warnings=[], narration_path="")
