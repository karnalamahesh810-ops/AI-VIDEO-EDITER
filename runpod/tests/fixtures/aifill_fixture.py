"""
Fixed gap timelines for the AI fill tests (tests/test_aifill.py). Like
hybrid_fixture.py it imports nothing from the worker: the modules come in as
arguments, so the SAME steps can run against the base commit's code (536a8a3,
before AI fill existed) to make the golden documents
(tests/fixtures/aifill_golden_*.json) and against today's code to prove that a
job WITHOUT an ai_fill block is byte-for-byte what it was.

  gap_inputs     the hybrid fixture's 18-line plan with six lines nothing real
                 was found for: two in the opening, a run of two, one that
                 states a figure (a data look), one at the end;
  last_resort    that plan's timeline through gapfill.hold_or_animate and the
                 quality gate's no_empty_scenes, with the shot cap on or off;
  plan_doc       handler.do_plan on that plan (planning, search, the ladder
                 and every network call faked) up to the colour grade - the
                 timeline as the build hands it on, after the last resort.
"""
import copy
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("hybrid_fixture_for_aifill", os.path.join(HERE, "hybrid_fixture.py"))
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

# The lines with no clip or picture: 1 and 2 (the opening), 6 and 7 (a run), 5 (a figure: "100 feet since 1950"),
# 16 (near the end).
GAPS = (1, 2, 5, 6, 7, 16)
STORY = {"kind": "explainer", "summary": "The Ogallala Aquifer under the Texas Panhandle is running dry",
         "event": "Ogallala Aquifer decline", "year": 2026, "recent": False, "places": ["Texas Panhandle"],
         "people": [], "hookBeats": [0], "cast": [],
         "sections": [{"from": 0, "to": 8, "when": "2026", "where": "Texas Panhandle", "footage": []},
                      {"from": 9, "to": 17, "when": "2011", "where": "Texas Panhandle", "footage": []}]}


def gap_inputs(Segment, Word, MediaAsset):
    """(segments, shots, assets, inp, duration) with GAPS empty."""
    segments, shots, assets, inp, duration = base.inputs(Segment, Word, MediaAsset)
    assets = [None if i in GAPS else a for i, a in enumerate(assets)]
    inp = dict(inp, brief=dict(STORY))
    return segments, shots, assets, inp, duration


def gap_doc(timeline, Segment, Word, MediaAsset):
    segments, shots, assets, inp, duration = gap_inputs(Segment, Word, MediaAsset)
    return timeline.build(segments, shots, assets, audio_url="https://example.test/fixture/narration.mp3",
                          audio_duration=duration, inp=inp, planner="rules", warnings=[], narration_path="")


def last_resort(timeline, gapfill, quality, config, mock, Segment, Word, MediaAsset, work, shot_max=7.0):
    """The gap timeline through the last resort and the gate's final step (no fetching: no plan in this job)."""
    doc = gap_doc(timeline, Segment, Word, MediaAsset)
    with mock.patch.object(config, "SHOT_MAX_SECONDS", float(shot_max)):
        got = gapfill.hold_or_animate(doc, label="golden", laddered=True, search=False)
        doc.setdefault("meta", {})["goldenLastResort"] = dict(got)
        gate = quality.Gate(doc, work)
        doc["meta"]["goldenText"] = gate.no_empty_scenes()
    return doc


class Built(Exception):
    def __init__(self, doc):
        super().__init__("built")
        self.doc = doc


def _fake_download(url, dest, timeout=0, headers=None):
    with open(dest, "wb") as fh:
        fh.write(b"\x00\x00\x00\x18ftypisom" + bytes(3000))
    return dest


LADDER = {"asked": len(GAPS), "pack": 0, "library": 0, "reserve": 0, "moment": 0, "still": 0, "generated": 0,
          "left": len(GAPS), "seconds": 0.0}


def plan_doc(handler, config, mock, tempfile, Segment, Word, MediaAsset, extra_input=None, patches=()):
    """
    handler.do_plan on the gap plan, every paid or network step faked, up to
    the colour grade (grade.prepare raises Built with the document). The
    ladder (gapfill.fill_empty) finds nothing; the last resort runs for real.
    """
    segs, shots, assets, inp, total = gap_inputs(Segment, Word, MediaAsset)
    line_at = {round(float(seg.start), 2): i for i, seg in enumerate(segs)}

    def line_of(start: float) -> int:
        """The fixture line a beat belongs to (a piece of a line the shot cap cut belongs to that line)."""
        i = line_at.get(round(float(start), 2))
        return i if i is not None else max(k for k, s in enumerate(segs) if float(s.start) <= float(start) + 1e-6)

    def plan(segments, **kw):
        # One shot per beat as the planner gives it (the shot cap may have cut a line into two beats).
        return [copy.deepcopy(shots[line_of(seg.start)]) for seg in segments], "ai", []

    def source_many(jobs_, work, **kw):
        # A line's own asset (known by where it starts); the second piece of a line the shot cap cut found nothing.
        out = []
        for j in jobs_:
            i = line_at.get(round(float(j.get("start") or 0.0), 2))
            out.append(copy.deepcopy(assets[i]) if i is not None else None)
        return out

    def prepare(doc, **kw):
        raise Built(doc)

    work = tempfile.mkdtemp()
    ps = [mock.patch.object(handler.storage, "resolve_audio", return_value="https://x/vo.mp3"),
          mock.patch.object(handler.storage, "download", side_effect=_fake_download),
          mock.patch.object(handler.renderer, "probe_duration", return_value=total),
          mock.patch.object(handler.transcribe, "transcribe_words", return_value=[object()]),
          mock.patch.object(handler.transcribe, "segment_words", return_value=segs),
          mock.patch.object(handler.director, "story_brief", return_value=dict(inp["brief"])),
          mock.patch.object(handler.director, "plan", side_effect=plan),
          mock.patch.object(handler.library.Library, "load", return_value=None),
          mock.patch.object(handler.fanout, "enabled_for", return_value=False),
          mock.patch.object(handler.pools, "source_by_subject", return_value={}),
          mock.patch.object(handler.media, "source_many", side_effect=source_many),
          mock.patch.object(handler.media, "rescue_fill", return_value={}),
          mock.patch.object(handler.gapfill, "fill_empty", return_value=dict(LADDER)),
          # (The last resort's fresh shots - another moment of a clip the video shows - would go to YouTube.)
          mock.patch.object(handler.gapfill, "_from_moment", return_value=None),
          mock.patch.object(handler.shotcap, "other_moments", return_value={}),
          mock.patch.object(handler.grade, "prepare", side_effect=prepare),
          mock.patch.object(handler.marks, "place", return_value={"placed": 0}),
          mock.patch.object(config, "UPSCALE_ENABLED", False), mock.patch.object(config, "ALLOW_VERTICAL", False),
          mock.patch.object(config, "ARCHIVE_RESTORE", False), mock.patch.object(config, "MENTION_CUTS", False),
          mock.patch.object(config, "DATA_GRAPHICS", False)] + list(patches)
    for p in ps:
        p.start()
    try:
        try:
            handler.do_plan(dict(inp, audio_url="vo.mp3", project_id="", **(extra_input or {})), work,
                            handler.Reporter(""))
        except Built as b:
            return b.doc, work
        raise AssertionError("do_plan never reached the colour grade")
    finally:
        for p in reversed(ps):
            p.stop()
        handler.vision.set_story({})
        handler.gapfill.reset()
