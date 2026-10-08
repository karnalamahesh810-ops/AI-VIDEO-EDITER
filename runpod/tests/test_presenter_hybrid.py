"""
The AI presenter inside a footage style (src/presenter/hybrid.py), offline:
which lines the presenter says on camera, the takes cut into one clip per
line, the timeline with full-screen and split-screen appearances, the
fallback to real footage when a take fails, every footage pass leaving the
presenter alone, the estimate - and that a job WITHOUT a presenter block is
built exactly as before (a golden timeline from the base commit, 68205fc).
No network: the provider, the storage and the checks' model are fakes.
"""
import copy
import importlib.util
import json
import os
import tempfile
import unittest
from unittest import mock

import handler
from src import config, datalooks, gapfill, hookcheck, ledger, library, recut, reclip, restore, review, timeline
from src import quality
from src.media import MediaAsset
from src.presenter import PRESENTER_SOURCE, hybrid, is_presenter_scene, kits, media_io, providers, generate
from src.presenter import budget as budget_mod, checks, store, tiers
from src.transcribe import Segment, Word
from tests.test_presenter import FakeProvider, FakeStore, kit_in, make_wav

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("hybrid_fixture", os.path.join(HERE, "fixtures", "hybrid_fixture.py"))
fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixture)
GOLDEN = os.path.join(HERE, "fixtures", "hybrid_golden_timeline.json")
REAL_START = hybrid.start               # (do_plan's own call is patched in Unchanged)


def plan_inputs():
    return fixture.inputs(Segment, Word, MediaAsset)


def long_plan(minutes=10.0, line_seconds=4.2):
    """A long synthetic narration: one line every ~4 s, a chapter opening every ~45 s, sentences of 1-2 lines."""
    segs, shots, t, i = [], [], 0.0, 0
    while t < minutes * 60.0:
        if i % 11 == 6:
            text = f"Now, here is the next part of the story number {i}."
        elif i % 2 == 0:
            text = f"The river ran low through the valley that summer and the farms waited for rain line {i},"
        else:
            text = f"and you could see the dry fields from the road for miles line {i}."
        words = []
        toks = text.split()
        for k, tok in enumerate(toks):
            a = t + k * (line_seconds - 0.4) / len(toks)
            words.append(Word(text=tok, start=round(a, 3), end=round(a + 0.25, 3)))
        segs.append(Segment(text=text, start=words[0].start, end=words[-1].end, words=words))
        shots.append({"query": "river", "visualType": "footage", "overlay": None, "subjectType": "place"})
        t += line_seconds
        i += 1
    return segs, shots, t


# ------------------------------------------------------------------ the block
class Block(unittest.TestCase):
    def test_no_block_no_hybrid(self):
        self.assertIsNone(hybrid.block({}))
        self.assertIsNone(hybrid.block({"presenter": None}))
        self.assertIsNone(hybrid.block({"presenter": "hollis"}))           # a bare id is the presenter style's field
        self.assertIsNone(hybrid.block({"presenter": {"presenter_id": "hollis", "enabled": False}}))
        # The AI presenter style is all presenter: its own pipeline, never hybrid.
        self.assertIsNone(hybrid.block({"video_style": "ai_presenter", "presenter": {"presenter_id": "hollis"}}))

    def test_block_fields(self):
        b = hybrid.block({"video_style": "documentary",
                          "presenter": {"presenter_id": "hollis", "share": "light", "split_screen": False,
                                        "budget_usd": "1.5"}})
        self.assertEqual((b["share_name"], b["share"], b["split_screen"], b["budget_usd"]), ("light", 0.08, False, 1.5))
        b = hybrid.block({"presenter": {"presenter_id": "leo"}})
        self.assertEqual((b["share_name"], b["share"], b["split_screen"], b["budget_usd"]), ("medium", 0.14, True, None))
        self.assertEqual(hybrid.share_of(12), ("custom", 0.12))
        self.assertEqual(hybrid.share_of(0.9), ("custom", 0.3))

    def test_the_apps_block_share_number_and_level_label(self):
        # docs/ai-presenter-contract.md section 10: "share": 0.08 | 0.14, "level": "light" | "medium".
        for blk, want in (({"share": 0.14, "level": "medium"}, ("medium", 0.14)),
                          ({"share": 0.08, "level": "light"}, ("light", 0.08)),
                          ({"share": 0.1, "level": "light"}, ("light", 0.1)),        # the number is what is used
                          ({"level": "light"}, ("light", 0.08)),
                          ({"share": 0.14}, ("medium", 0.14))):
            b = hybrid.block({"presenter": dict(blk, presenter_id="ruth")})
            self.assertEqual((b["share_name"], b["share"]), want, blk)

    def test_the_plan_fits_the_cap_dropping_middles_latest_first(self):
        mk = lambda role, a, b, i: hybrid.Appearance(lines=[i], start=a, end=b, role=role, id=f"h{i:02d}")  # noqa: E731
        aps = [mk("hook", 0, 6, 0), mk("chapter", 30, 35, 1), mk("beat", 60, 65, 2), mk("close", 95, 100, 3)]
        keep, dropped = hybrid.fit_budget(aps, None)
        self.assertEqual((len(keep), dropped), (4, []))
        retry = hybrid.take_usd(6.0)                                             # the dearest take, once more
        full = sum(hybrid.take_usd(a.seconds) for a in aps)
        keep, dropped = hybrid.fit_budget(aps, full + retry + 0.001)
        self.assertEqual(len(keep), 4)
        keep, dropped = hybrid.fit_budget(aps, full - hybrid.take_usd(5.0) + retry + 0.001)
        self.assertEqual([a.id for a in dropped], ["h02"])                     # the latest middle one first
        keep, dropped = hybrid.fit_budget(aps, 2 * retry + 0.001)
        self.assertEqual([a.role for a in keep], ["hook"])                       # the opening is the last to go

    def test_a_failed_takes_lines_get_a_search_box_of_their_own(self):
        self.assertEqual(hybrid.retry_seconds(2), hybrid.RETRY_BASE_SECONDS + 2 * hybrid.RETRY_LINE_SECONDS)
        self.assertEqual(hybrid.retry_seconds(2, 120.0), 120.0)          # never past the main search's own box

    def test_kit_request_reads_the_presenter_styles_fields(self):
        req = hybrid.kit_request({"presenter_id": "hollis", "catalogue": "https://r2.example/presenters/catalogue.json",
                                  "base_url": "https://r2.example/presenters/"})
        self.assertEqual(req, {"presenter_id": "hollis",
                               "presenter_catalogue_url": "https://r2.example/presenters/catalogue.json",
                               "presenter_base_url": "https://r2.example/presenters/"})
        inline = {"id": "x", "master": "https://r2.example/x.png"}
        self.assertEqual(hybrid.kit_request({"presenter_kit": inline})["presenter_kit"], inline)


# ------------------------------------------------------------------ which lines
class LineSelection(unittest.TestCase):
    def setUp(self):
        self.segs, self.shots, _a, _inp, self.total = plan_inputs()

    def pick(self, share="medium", split=True, shots=None, segs=None, total=None):
        return hybrid.select(segs or self.segs, shots or self.shots, total or self.total, fps=30,
                             share=hybrid.SHARES[share], split=split, framings=["master", "closeup"])

    def test_hook_first_sentence_and_the_close(self):
        aps = self.pick()
        self.assertEqual(aps[0].role, "hook")
        self.assertEqual(aps[0].lines, [0])                                   # the first sentence is line 0
        self.assertEqual(aps[0].start, 0.0)
        self.assertFalse(aps[0].split)
        self.assertEqual(aps[-1].role, "close")
        self.assertEqual(aps[-1].lines[-1], len(self.segs) - 1)
        self.assertAlmostEqual(aps[-1].end, self.total, delta=1 / 30)
        self.assertFalse(aps[-1].split)

    def test_spans_are_the_timelines_own_frames_and_whole_lines(self):
        bounds = hybrid.frame_bounds(self.segs, self.total, 30)
        for ap in self.pick():
            self.assertAlmostEqual(ap.start, bounds[ap.lines[0]] / 30, places=6)
            self.assertAlmostEqual(ap.end, bounds[ap.lines[-1] + 1] / 30, places=6)
            self.assertEqual(ap.lines, list(range(ap.lines[0], ap.lines[-1] + 1)))

    def test_chapter_openings_and_spacing(self):
        aps = self.pick()
        middle = [a for a in aps if a.role not in ("hook", "close")]
        self.assertTrue(any(a.role == "chapter" for a in middle))
        self.assertIn(6, [i for a in middle for i in a.lines] + [12])       # "Now, I have seen..." or "Here is the part..."
        for a, b in zip(aps, aps[1:]):
            self.assertGreaterEqual(b.start - a.end, hybrid.MIN_APART - 1e-6)

    def test_share_on_a_long_video_and_coming_back(self):
        segs, shots, total = long_plan(10.0)
        for share, want in (("light", 0.08), ("medium", 0.14)):
            aps = self.pick(share, segs=segs, shots=shots, total=total)
            used = sum(a.seconds for a in aps) / total
            self.assertGreater(used, want * 0.75, share)
            self.assertLess(used, want * 1.45, share)
            for a in aps:
                cap = hybrid.HOOK_MAX if a.role == "hook" else hybrid.PMAX
                self.assertLessEqual(a.seconds, cap + 1e-6)
                self.assertGreaterEqual(a.seconds, 2.0)
        aps = self.pick("medium", segs=segs, shots=shots, total=total)
        gaps = [b.start - a.end for a, b in zip(aps, aps[1:])]
        self.assertLessEqual(max(gaps), 2 * hybrid.MAX_GAP)                  # it keeps coming back
        early = sum(a.seconds for a in aps if a.start < 120.0)
        late = sum(a.seconds for a in aps if 360.0 <= a.start < 480.0)
        self.assertGreaterEqual(early, late)                                # heavier early

    def test_about_a_third_split_never_hook_or_close_and_none_without_split_screen(self):
        segs, shots, total = long_plan(10.0)
        aps = self.pick("medium", segs=segs, shots=shots, total=total)
        middle = [a for a in aps if a.role not in ("hook", "close")]
        splits = [a for a in middle if a.split]
        self.assertTrue(abs(len(splits) - len(middle) / 3.0) <= 1.0)
        self.assertFalse(any(a.split for a in aps if a.role in ("hook", "close")))
        self.assertFalse(any(a.split for a in self.pick("medium", split=False, segs=segs, shots=shots, total=total)))

    def test_the_sign_off_takes_the_planners_graphic_hint_too(self):
        shots = copy.deepcopy(self.shots)
        shots[-1]["overlay"] = {"type": "callout", "text": "Comment your county"}
        aps = self.pick(shots=shots)
        self.assertEqual(aps[-1].role, "close")
        self.assertEqual(aps[-1].lines[-1], len(self.segs) - 1)
        shots[-1]["subjectType"] = "document"
        sel = hybrid.Selector(*hybrid.plan_lines(self.segs, shots, self.total, 30), share=0.14, split=True)
        aps = sel.plan()
        self.assertNotIn(len(self.segs) - 1, {i for a in aps for i in a.lines})
        self.assertTrue(any("last line" in n for n in sel.notes))

    def test_the_presenter_is_nobody_to_search_for(self):
        kit = {"name": "Hollis Reed"}
        shots = [{"query": "Hollis Reed Texas Panhandle ranch cook reading phone comment", "subject": "Hollis Reed",
                  "subjectType": "person", "fallbacks": ["Hollis Reed", "Texas Panhandle ranch"], "prompt": ""},
                 {"query": "dry stock pond cracked mud", "subject": "stock pond", "subjectType": "place",
                  "fallbacks": ["cracked mud"]},
                 {"query": "reeds along a dry creek", "subject": "creek", "subjectType": "place", "fallbacks": []},
                 {"query": "Hollis's windmill", "subject": "windmill", "subjectType": "place", "fallbacks": []}]
        n = hybrid.scrub_presenter(shots, kit, {"event": "Ogallala Aquifer decline"})
        self.assertEqual(n, 2)
        self.assertEqual(shots[0]["query"], "Texas Panhandle ranch cook reading phone comment")
        self.assertEqual((shots[0]["subject"], shots[0]["subjectType"]), ("Ogallala Aquifer decline", "place"))
        self.assertTrue(shots[0]["aboutPresenter"])
        self.assertEqual(shots[0]["fallbacks"], ["Texas Panhandle ranch"])
        self.assertEqual(shots[1]["query"], "dry stock pond cracked mud")              # untouched
        self.assertEqual(shots[2]["query"], "reeds along a dry creek")                 # "reeds" is not the name
        self.assertEqual(shots[3]["query"], "Ogallala Aquifer decline windmill")       # a bare word gets the story
        self.assertNotIn("aboutPresenter", shots[3])
        # A line about the presenter is the presenter's to say: full-screen and first in line.
        segs, sh, _a, _inp, total = plan_inputs()
        sh = copy.deepcopy(sh)
        sh[13].update(subject="Hollis Reed", subjectType="person")
        hybrid.scrub_presenter(sh, kit, {"event": "Ogallala Aquifer decline"})
        lines, _t = hybrid.plan_lines(segs, sh, total, 30)
        self.assertTrue(lines[13].full_ok and lines[13].about_presenter)

    def test_the_presenter_is_not_the_storys_cast(self):
        brief = {"people": ["Hollis Reed", "Barack Obama"],
                 "cast": [{"name": "Hollis Reed", "aliases": ["my name is Hollis Reed"]}, {"name": "Barack Obama"}]}
        self.assertEqual(hybrid.scrub_brief(brief, {"name": "Hollis Reed"}), 2)
        self.assertEqual(brief, {"people": ["Barack Obama"], "cast": [{"name": "Barack Obama"}]})
        self.assertEqual(hybrid.scrub_brief(brief, {"name": ""}), 0)

    def test_lines_that_keep_their_footage(self):
        shots = copy.deepcopy(self.shots)
        shots[12]["overlay"] = {"type": "stat", "value": 3}                 # a graphic planned on a chapter line
        shots[6]["subjectType"] = "person"                                   # a named person on a chapter line
        aps = self.pick(shots=shots)
        lines = {i: a for a in aps for i in a.lines}
        self.assertNotIn(12, lines)                                          # its graphic stays on the footage
        if 6 in lines:
            self.assertTrue(lines[6].split)                                  # the person stays on screen beside
        aps = self.pick(shots=shots, split=False)
        self.assertNotIn(6, {i for a in aps for i in a.lines})

    def test_the_opening_sentence_takes_the_planners_graphic_hint_but_not_a_persons_line(self):
        shots = copy.deepcopy(self.shots)
        shots[0]["overlay"] = {"type": "map", "locations": [{"label": "Texas Panhandle"}]}
        aps = self.pick(shots=shots)
        self.assertEqual((aps[0].role, aps[0].lines), ("hook", [0]))        # the presenter still opens the video
        shots[0]["subjectType"] = "person"                                   # ...unless the line must show a person
        sel = hybrid.Selector(*hybrid.plan_lines(self.segs, shots, self.total, 30), share=0.14, split=True)
        aps = sel.plan()
        self.assertNotIn(0, {i for a in aps for i in a.lines})
        self.assertTrue(any("first line" in n for n in sel.notes))

    def test_a_short_video_gets_the_opening_only(self):
        segs, shots, total = long_plan(0.4)
        aps = self.pick(segs=segs, shots=shots, total=total)
        self.assertEqual([a.role for a in aps], ["hook"])


# ------------------------------------------------------------------ at most two minutes of presenter
def on_screen(aps):
    """The presenter's whole time on screen: every appearance, split screens included (they are paid the same)."""
    return sum(a.seconds for a in aps)


class Cap(unittest.TestCase):
    """The owner (2026-10-08): the presenter is never on screen more than about two minutes a video, however long
    the video - the presenter is what costs. max_seconds (default 120) caps the plan; split screens count."""

    def pick(self, minutes, share="medium", split=True, **kw):
        segs, shots, total = long_plan(minutes)
        return hybrid.select(segs, shots, total, fps=30, share=hybrid.SHARES[share], split=split,
                             framings=["master", "closeup"], **kw), total, len(segs)

    def test_a_25_minute_script_at_medium_ends_within_two_minutes(self):
        self.assertEqual(hybrid.MAX_SECONDS, 120.0)
        free, _t, _n = self.pick(25.0, max_seconds=None)
        self.assertGreater(on_screen(free), 2 * 120)                         # the share alone: 0.14 x 25 min and more
        aps, _t, _n = self.pick(25.0)                                         # the hybrid's default cap
        self.assertLessEqual(on_screen(aps), 120.0 + 1e-6)
        self.assertGreater(on_screen(aps), 120.0 - hybrid.PMAX)               # ...and close to it, not far under
        # The job's block carries the cap (default 120); a longer cap is the job's to send.
        blk = hybrid.block({"presenter": {"presenter_id": "ruth", "share": 0.14, "level": "medium"}})
        self.assertEqual(blk["max_seconds"], 120.0)
        longer, _t, _n = self.pick(25.0, max_seconds=200)
        self.assertLessEqual(on_screen(longer), 200.0 + 1e-6)
        self.assertGreater(on_screen(longer), on_screen(aps))

    def test_short_videos_are_unchanged(self):
        for minutes, share in ((5.0, "light"), (5.0, "medium"), (10.0, "light"), (10.0, "medium"), (15.0, "light")):
            free, _t, _n = self.pick(minutes, share, max_seconds=None)
            aps, _t, _n = self.pick(minutes, share)
            self.assertLessEqual(on_screen(free), 120.0, (minutes, share))
            self.assertEqual([a.as_dict() for a in aps], [a.as_dict() for a in free], (minutes, share))
        segs, shots, _a, _inp, total = plan_inputs()
        kw = dict(fps=30, share=0.14, split=True, framings=["master", "closeup"])
        self.assertEqual([a.as_dict() for a in hybrid.select(segs, shots, total, **kw)],
                         [a.as_dict() for a in hybrid.select(segs, shots, total, max_seconds=None, **kw)])

    def test_the_opening_and_the_close_are_always_kept(self):
        for max_seconds in (120, 30, 5):
            aps, _t, n = self.pick(25.0, max_seconds=max_seconds)
            self.assertEqual((aps[0].role, aps[0].lines[0], aps[0].start), ("hook", 0, 0.0), max_seconds)
            self.assertEqual((aps[-1].role, aps[-1].lines[-1]), ("close", n - 1), max_seconds)
        self.assertEqual([a.role for a in aps], ["hook", "close"])          # a cap under both: the two alone

    def test_the_beats_between_are_spread_evenly(self):
        aps, total, _n = self.pick(25.0)
        middle = [a for a in aps if a.role not in ("hook", "close")]
        self.assertGreaterEqual(len(middle), 20)
        for k in range(5):                                                   # every fifth of the video has some
            a, b = total * k / 5, total * (k + 1) / 5
            self.assertGreaterEqual(sum(1 for x in middle if a <= x.start < b), 3, k)
        gaps = [b.start - a.end for a, b in zip(aps, aps[1:])]
        self.assertGreaterEqual(min(gaps), hybrid.MIN_APART - 1e-6)
        self.assertLessEqual(max(gaps), 2.0 * total / (len(aps) - 1))       # never a long stretch without them

    def test_split_screens_count_toward_the_cap(self):
        aps, _t, _n = self.pick(25.0, split=True)
        splits = [a for a in aps if a.split]
        self.assertTrue(splits)
        self.assertLessEqual(on_screen(aps), 120.0 + 1e-6)                  # the split appearances inside the 120 s
        self.assertFalse(any(a.split for a in aps if a.role in ("hook", "close")))
        full, _t, _n = self.pick(25.0, split=False)
        self.assertFalse(any(a.split for a in full))
        self.assertLessEqual(on_screen(full), 120.0 + 1e-6)

    def test_a_long_light_video_is_capped_too(self):
        free, _t, _n = self.pick(30.0, "light", max_seconds=None)
        aps, _t, _n = self.pick(30.0, "light")
        self.assertGreater(on_screen(free), 120.0)
        self.assertLessEqual(on_screen(aps), 120.0 + 1e-6)

    def test_the_blocks_max_seconds(self):
        def cap(v):
            return hybrid.block({"presenter": {"presenter_id": "ruth", "max_seconds": v}})["max_seconds"]
        self.assertEqual(cap(90), 90.0)
        self.assertEqual(cap("150"), 150.0)
        for bad in (None, "", 0, -5, "lots", True, float("nan")):
            self.assertEqual(cap(bad), hybrid.MAX_SECONDS, bad)

    def test_the_estimate_and_the_report_carry_the_cap(self):
        e = hybrid.estimate(25, "medium")
        self.assertEqual((e["presenterSeconds"], e["capped"]), (120, True))
        self.assertEqual(hybrid.estimate(25, "medium", max_seconds=None)["presenterSeconds"], 210)
        self.assertEqual((hybrid.estimate(10, "medium")["presenterSeconds"], hybrid.estimate(10, "medium")["capped"]),
                         (84, False))
        # Past the cap a longer video adds only its footage build: the presenter's part stays where it is.
        self.assertEqual(hybrid.estimate(20, "medium")["parts"]["presenter"], e["parts"]["presenter"])
        self.assertAlmostEqual(e["usd"] - hybrid.estimate(20, "medium")["usd"], 5 * hybrid.NORMAL_PER_MIN, delta=0.011)
        self.assertLess(hybrid.estimate(25, "medium")["parts"]["presenter"],
                        hybrid.estimate(25, "medium", max_seconds=None)["parts"]["presenter"])
        table = hybrid.estimate_table()
        self.assertEqual(table["maxSeconds"], 120.0)
        self.assertEqual(table["byShare"]["medium"]["20"]["presenterSeconds"], 120)
        self.assertEqual(table["byShare"]["light"]["10"]["presenterSeconds"], 48)


class CapBudget(unittest.TestCase):
    """The money cap (budget_usd) still applies inside the time cap: the lower of the two wins."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = self.tmp.name
        self.kit = kit_in(os.path.join(self.work, "kitsrc"), framings=("medium", "closeup"))

    def tearDown(self):
        self.tmp.cleanup()

    def begin(self, minutes=25.0, **extra):
        """A Hybrid planned for a long narration, begun with the takes themselves switched off (no file is made)."""
        segs, shots, total = long_plan(minutes)
        blk = hybrid.block({"video_style": "documentary",
                            "presenter": dict({"presenter_kit": self.kit, "share": "medium"}, **extra)})
        lines, total = hybrid.plan_lines(segs, shots, total, 30)
        sel = hybrid.Selector(lines, total, share=blk["share"], split=blk["split_screen"],
                              framings=["medium", "closeup"], max_seconds=blk["max_seconds"])
        planned = sel.plan()
        hy = hybrid.Hybrid(inp={"project_id": ""}, blk=blk, kit=self.kit, appearances=list(planned),
                           spans={ln.index: (ln.start, ln.end) for ln in lines}, duration=total, fps=30, work=self.work)
        hy.capped = sel.capped
        with mock.patch.object(hybrid.Hybrid, "_make_all", lambda self: None), \
                mock.patch.object(media_io, "to_wav", return_value=os.path.join(self.work, "vo.wav")), \
                mock.patch.dict(os.environ, {"PRESENTER_BUDGET_USD": ""}):
            hy.begin("vo.mp3", provider=FakeProvider(), store=FakeStore(), cache_dir=os.path.join(self.work, "cache"))
        hy._thread.join(10)
        return hy, planned, total

    @staticmethod
    def cost(aps):
        """fit_budget's own sum: every take once and one retry of the dearest."""
        return sum(hybrid.take_usd(a.seconds) for a in aps) + max((hybrid.take_usd(a.seconds) for a in aps), default=0.0)

    def test_a_budget_lower_than_the_cap_still_wins(self):
        hy, planned, _total = self.begin(budget_usd=2.0)
        self.assertLessEqual(on_screen(planned), 120.0 + 1e-6)
        self.assertGreater(self.cost(planned), 2.0)                          # 120 s would cost more than the budget
        self.assertEqual(hy.budget.cap, 2.0)
        self.assertTrue(hy.dropped)
        self.assertLess(on_screen(hy.appearances), on_screen(planned))
        self.assertLessEqual(self.cost(hy.appearances), 2.0 + 1e-9)
        self.assertEqual(hy.appearances[0].role, "hook")                     # the opening is the last to go

    def test_the_default_budget_follows_the_capped_time(self):
        hy, planned, total = self.begin()
        self.assertEqual(hy.dropped, [])
        uncapped = round(total * 0.14 * hybrid.USD_PER_SECOND * 1.5, 2)       # what the share alone would have set
        want = max(0.5, round(min(total * 0.14, 120.0) * hybrid.USD_PER_SECOND * 1.5, 2),
                   round(hybrid.take_usd(on_screen(planned), len(planned)) * 1.6, 2))
        self.assertAlmostEqual(hy.budget.cap, want, places=6)
        self.assertLess(hy.budget.cap, uncapped)
        # The app's budget for any video past the cap (120 s x $0.05 x 1.5 = $9.00) makes every planned take.
        keep, dropped = hybrid.fit_budget(list(planned), 9.0)
        self.assertEqual((len(keep), dropped), (len(planned), []))

    def test_the_jobs_plan_keeps_to_the_blocks_cap(self):
        segs, shots, total = long_plan(25.0)
        for extra, cap in (({}, 120.0), ({"max_seconds": 60}, 60.0)):
            inp = {"video_style": "documentary", "project_id": "",
                   "presenter": dict({"presenter_kit": self.kit, "share": 0.14, "level": "medium"}, **extra)}
            with mock.patch.object(hybrid.Hybrid, "begin", lambda self, *a, **k: None):
                hy = hybrid.start(inp, segs, shots, narration_path="vo.mp3", duration=total, work=self.work)
            self.assertLessEqual(on_screen(hy.appearances), cap + 1e-6)
            self.assertEqual((hy.appearances[0].role, hy.appearances[-1].role), ("hook", "close"))
            self.assertEqual(hy.capped["maxSeconds"], cap)
            self.assertTrue(any(f"past the cap of {cap:.0f} s" in line for line in hy.log), hy.log)

    def test_the_report_says_the_cap_held(self):
        hy, planned, _total = self.begin()
        rep = hy.finish({"scenes": [], "durationInFrames": 1, "meta": {}})
        self.assertEqual(rep["maxSeconds"], 120.0)
        self.assertEqual(rep["capped"]["maxSeconds"], 120.0)
        self.assertGreater(rep["capped"]["askedSeconds"], 120.0)
        self.assertLessEqual(rep["plannedSeconds"], 120.0 + 1e-6)
        self.assertEqual(rep["estimate"]["presenterSeconds"], 120)
        self.assertTrue(any("at most 120 s" in line for line in hy.log))


# ------------------------------------------------------------------ the takes
class FailFor(FakeProvider):
    """Fails every take whose voice window belongs to the named appearances."""

    def __init__(self, ids, **kw):
        super().__init__(**kw)
        self.ids = set(ids)

    def submit_video(self, req):
        if any(f"/{a}_" in req.audio_url or req.audio_url.rsplit("/", 1)[-1].startswith(f"{a}_") for a in self.ids):
            self.videos.append(req)
            raise providers.ProviderError("upstream refused", status=400)
        return super().submit_video(req)


class Takes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = self.tmp.name
        self.segs, self.shots, self.assets, inp, self.total = plan_inputs()
        self.kit = kit_in(os.path.join(self.work, "kitsrc"), framings=("medium", "closeup"))
        self.wav = make_wav(os.path.join(self.work, "narration.wav"), self.total + 1.0)
        self.inp = dict(inp, video_style="documentary", project_id="",
                        presenter={"presenter_kit": self.kit, "share": "medium", "split_screen": True,
                                   "budget_usd": 5.0})

    def tearDown(self):
        self.tmp.cleanup()

    def start(self, provider):
        hy = hybrid.start(self.inp, self.segs, self.shots, narration_path=self.wav, duration=self.total,
                          work=self.work, provider=provider, store=FakeStore(),
                          cache_dir=os.path.join(self.work, "cache"))
        hy.wait()
        return hy

    def test_each_line_gets_its_own_clip_cut_from_one_take(self):
        p = FakeProvider(clip_seconds=12.0)
        hy = self.start(p)
        self.assertEqual(len(p.videos), len(hy.appearances))                  # one take per appearance
        self.assertTrue(all(r.model == "heygen/avatar-iv" for r in p.videos))
        self.assertEqual(p.images, [])                                        # no AI picture, ever
        for m in hy.made.values():
            self.assertEqual(sorted(m.parts), m.appearance.lines)
            for i, part in m.parts.items():
                a, b = hy.line_spans[i]
                info = media_io.probe(part.local_path)
                self.assertEqual(info["audio"], 0)                            # the narration is the only sound
                self.assertGreaterEqual(info["duration"], b - a - 0.04)      # never slowed to fill its scene
                self.assertEqual(part.source, PRESENTER_SOURCE)
        self.assertEqual(hy.failed_full(), [])
        self.assertEqual(hy.settled(), {i for ap in hy.appearances for i in ap.lines})

    def test_search_and_fill_lines(self):
        hy = self.start(FakeProvider())
        jobs = [{"index": i} for i in range(len(self.segs))]
        full = {i for ap in hy.appearances if not ap.split for i in ap.lines}
        split = {i for ap in hy.appearances if ap.split for i in ap.lines}
        self.assertTrue(full and split)
        searched = {j["index"] for j in hy.search_jobs(jobs)}
        self.assertFalse(full & searched)                                     # no search for a full-screen line
        self.assertTrue(split <= searched)                                    # a split line keeps its search
        self.assertFalse(full & {j["index"] for j in hy.fill_jobs(jobs)})

    def test_a_failed_take_gives_its_lines_back_to_the_footage_search(self):
        hy = hybrid.start(self.inp, self.segs, self.shots, narration_path=self.wav, duration=self.total,
                          work=self.work, provider=FailFor({"h00"}), store=FakeStore(),
                          cache_dir=os.path.join(self.work, "cache"))
        hy.wait()
        self.assertEqual(hy.failed_full(), hy.made["h00"].appearance.lines)
        self.assertEqual(hy.made["h00"].parts, {})
        jobs = [{"index": i} for i in range(len(self.segs))]
        self.assertTrue(set(hy.failed_full()) <= {j["index"] for j in hy.fill_jobs(jobs)})
        built = hy.for_build(list(self.assets))
        for i in hy.failed_full():
            self.assertIs(built[i], self.assets[i])                           # the line's real footage

    def test_no_still_fallback_in_hybrid(self):
        def verdict(text):
            if "same_person" in text:
                return {"same_person": 0.1, "natural": 0.9, "issues": ["different_person"]}
            return {"real": 0.9, "match": 0.9, "issues": []}
        p = FakeProvider(verdict=verdict)
        hy = self.start(p)
        self.assertEqual(p.images, [])                                        # never an AI still or a kit set
        self.assertEqual(sorted(hy.failed_full()), sorted(i for ap in hy.appearances if not ap.split for i in ap.lines))
        self.assertEqual(hy.settled(), set())

    def test_a_severe_issue_needs_the_checks_own_scores_to_agree(self):
        from tests.test_presenter import make_video
        clip = make_video(os.path.join(self.work, "clip.mp4"), 3.0)
        master = os.path.join(self.work, "kitsrc", "master.png")

        def run(verdict):
            p = FakeProvider(verdict=lambda text: verdict)
            return checks.Checker(p, budget_mod.Budget(1.0), self.work).presenter(clip, master, "t")["ok"]
        # The laptop test's opening take: a blink and an open mouth read as "melted" - the scores say natural.
        self.assertTrue(run({"same_person": 1.0, "natural": 0.8, "issues": ["bad_mouth", "melted_face"]}))
        self.assertFalse(run({"same_person": 1.0, "natural": 0.6, "issues": ["melted_face"]}))
        self.assertFalse(run({"same_person": 0.7, "natural": 0.9, "issues": ["different_person"]}))
        self.assertFalse(run({"same_person": 0.5, "natural": 0.9, "issues": []}))
        self.assertTrue(run({"same_person": 0.9, "natural": 0.9, "issues": ["bad_eyes"]}))

    def test_generator_switch(self):
        b = budget_mod.Budget(5.0)
        p = FakeProvider(fail_models={"heygen/avatar-iv"})
        g = generate.Generator(provider=p, budget=b, tier=tiers.resolve("budget"), kit=self.kit, work=self.work,
                               store=FakeStore(), cache=store.Cache(os.path.join(self.work, "c2")),
                               checker=checks.Checker(p, b, self.work), narration_wav=self.wav, total=self.total,
                               bible={}, still_fallback=False)
        from src.presenter.shotplan import Shot
        shot = Shot(kind="presenter", start=0.0, end=5.0, text="", words=[], beats=[0], framing="medium", id="h00")
        self.assertIsNone(g.presenter(shot))
        self.assertEqual(p.images, [])

    def test_parallel_takes_never_read_a_half_written_kit_picture(self):
        # The laptop test's "broken PNG": five takes fetched the 6.6 MB master at once and read it half-written.
        import io as _io
        import time as _time
        from concurrent.futures import ThreadPoolExecutor
        from PIL import Image
        buf = _io.BytesIO()
        Image.new("RGB", (2752, 1536), (90, 70, 50)).save(buf, "PNG")
        body = buf.getvalue()

        class Slow:
            status_code = 200

            @property
            def content(self):
                _time.sleep(0.05)
                return body
        kit = dict(self.kit, master="https://r2.example.test/presenters/x/x_master.png")
        folder = os.path.join(self.work, "kitdl")
        with mock.patch.object(kits.requests, "get", return_value=Slow()):
            with ThreadPoolExecutor(max_workers=8) as pool:
                paths = list(pool.map(lambda _i: kits.fetch(kit, kit["master"], folder), range(16)))
        self.assertEqual(len(set(paths)), 1)
        with Image.open(paths[0]) as im:
            im.load()
        self.assertEqual([f for f in os.listdir(folder) if f.endswith(".part")], [])

    def test_a_take_later_than_the_wait_is_never_used(self):
        import time as _time

        class Slow(FakeProvider):
            def submit_video(self, req):
                _time.sleep(1.5)
                return super().submit_video(req)
        hy = hybrid.start(self.inp, self.segs, self.shots, narration_path=self.wav, duration=self.total,
                          work=self.work, provider=Slow(), store=FakeStore(), cache_dir=os.path.join(self.work, "cache"))
        hy.wait(timeout=0.2)
        full = sorted(i for ap in hy.appearances if not ap.split for i in ap.lines)
        self.assertEqual(hy.failed_full(), full)                              # searched like any line
        hy._thread.join(30)                                                    # the takes land late...
        self.assertEqual(hy.settled(), set())                                 # ...and are not used
        self.assertEqual(hy.for_build(list(self.assets)), list(self.assets))

    def test_an_unexpected_presenter_error_leaves_a_footage_video(self):
        with mock.patch.object(hybrid.Hybrid, "begin", side_effect=RuntimeError("disk full")):
            hy = hybrid.start(self.inp, self.segs, self.shots, narration_path=self.wav, duration=self.total,
                              work=self.work, provider=FakeProvider(), store=FakeStore())
        self.assertEqual((hy.appearances, hy.made), ([], {}))
        jobs = [{"index": i} for i in range(len(self.segs))]
        self.assertEqual(hy.search_jobs(jobs), jobs)
        self.assertTrue(hy.warnings)

    def test_a_bad_block_fails_before_anything_is_spent(self):
        inp = dict(self.inp, presenter={"presenter_id": "nobody-at-all"})
        with self.assertRaises(ValueError):
            hybrid.start(inp, self.segs, self.shots, narration_path=self.wav, duration=self.total, work=self.work,
                         provider=FakeProvider(), store=FakeStore())


# ------------------------------------------------------------------ the timeline
def hybrid_doc(work, provider=None, split=True, share="medium"):
    segs, shots, assets, inp, total = plan_inputs()
    kit = kit_in(os.path.join(work, "kitsrc"), framings=("medium", "closeup"))
    wav = make_wav(os.path.join(work, "narration.wav"), total + 1.0)
    inp = dict(inp, video_style="documentary", presenter={"presenter_kit": kit, "share": share,
                                                         "split_screen": split, "budget_usd": 5.0})
    hy = hybrid.start(inp, segs, shots, narration_path=wav, duration=total, work=work,
                      provider=provider or FakeProvider(), store=FakeStore(), cache_dir=os.path.join(work, "cache"))
    hy.wait()
    doc = timeline.build(segs, shots, hy.for_build(list(assets)), audio_url="https://example.test/vo.mp3",
                         audio_duration=total, inp=inp, planner="rules", warnings=[], narration_path="")
    hy.decorate(doc)
    return doc, hy, assets


class Timeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_and_split_appearances(self):
        doc, hy, assets = hybrid_doc(self.work)
        hy.finish(doc)
        scenes = doc["scenes"]
        pres = [i for i, s in enumerate(scenes) if is_presenter_scene(s)]
        self.assertEqual(set(pres), hy.settled())
        for i in pres:
            s = scenes[i]
            self.assertEqual((s["effect"], s["treatment"], s["motion"], s["reframe"]), ("none", "none", "none", "off"))
            self.assertEqual(s["transition"], "none")                         # a hard cut into the presenter
            if i + 1 < len(scenes):
                self.assertEqual(scenes[i + 1]["transition"], "none")         # ...and out of it
            self.assertEqual(s["semanticMetadata"]["shotKind"], "presenter")
            self.assertEqual(s["semanticMetadata"]["alternatives"], [])
            self.assertFalse(s["reviewRequired"])
            self.assertGreaterEqual(s["media"]["clipSeconds"], s["durationInFrames"] / 30 - 0.04)
        splits = [scenes[i] for i in pres if scenes[i].get("frame") == "split"]
        self.assertTrue(splits)
        for s in splits:
            half = s["media"]["split"]
            i = scenes.index(s)
            real = assets[i]
            self.assertEqual(half["source"], real.source)                     # the line's REAL clip or picture
            self.assertEqual(half["assetId"], real.identity)
            self.assertEqual(half["type"], real.kind)
            self.assertTrue(half["url"])
        full = [scenes[i] for i in pres if scenes[i].get("frame") != "split"]
        self.assertTrue(full)
        self.assertTrue(all("split" not in s["media"] for s in full))
        # Nothing generated but the presenter: every other scene is the real asset it was given.
        for i, s in enumerate(scenes):
            if i not in pres:
                self.assertIn(s["media"]["source"], ("youtube", "wikimedia"))
        timeline.validate(doc, require_media=False)

    def test_no_look_or_sound_over_the_presenter(self):
        doc, hy, _a = hybrid_doc(self.work)
        spans = hy.spans(doc)
        # A look from the footage before that runs into the presenter, and one laid right on the presenter.
        first = spans[1]
        doc["overlays"].append({"type": "motion", "template": "KT_KEYWORD", "text": "before", "startFrame": first[0] - 90,
                                "durationInFrames": 150})
        doc["overlays"].append({"type": "motion", "template": "KT_KEYWORD", "text": "on", "startFrame": first[0] + 5,
                                "durationInFrames": 60})
        doc["sfx"].append({"name": "whoosh", "kind": "look", "startFrame": first[0] + 3, "volume": 0.3})
        report = hy.finish(doc)
        for ov in doc["overlays"]:
            a, b = int(ov["startFrame"]), int(ov["startFrame"]) + int(ov["durationInFrames"])
            self.assertFalse(any(a < y and b > x for x, y in spans), ov)
        for fx in doc["sfx"]:
            self.assertFalse(any(x <= int(fx["startFrame"]) < y for x, y in spans), fx)
        self.assertEqual(report["swept"]["trimmed"], 1)
        self.assertGreaterEqual(report["swept"]["dropped"], 1)
        self.assertTrue(any(o.get("text") == "before" and o["durationInFrames"] == 90 for o in doc["overlays"]))

    def test_the_planner_and_the_data_looks_leave_presenter_scenes_alone(self):
        doc, hy, _a = hybrid_doc(self.work)
        spans = hy.spans(doc)
        for ov in doc["overlays"]:
            a, b = int(ov["startFrame"]), int(ov["startFrame"]) + int(ov["durationInFrames"])
            self.assertFalse(any(a < y and b > x for x, y in spans), (ov.get("template"), a, b, spans))
        self.assertFalse(any(s.get("media", {}).get("type") == "animation" and is_presenter_scene(s)
                             for s in doc["scenes"]))
        # The data looks once more (the relook action's pass): still none over the presenter.
        datalooks.finish(doc)
        for ov in doc["overlays"]:
            a, b = int(ov["startFrame"]), int(ov["startFrame"]) + int(ov["durationInFrames"])
            self.assertFalse(any(a < y and b > x for x, y in spans))

    def test_report_costs_and_disclosure(self):
        doc, hy, _a = hybrid_doc(self.work)
        rep = hy.finish(doc)
        meta = doc["meta"]["presenterHybrid"]
        self.assertIs(meta, rep)
        self.assertEqual(meta["made"], [a.id for a in hy.appearances])
        self.assertEqual(meta["fellBack"], [])
        self.assertGreater(meta["costs"]["presenterUsd"], 0)
        self.assertEqual(doc["meta"]["warnings"][0], hybrid.DISCLOSURE)
        self.assertTrue(hybrid.is_hybrid_doc(doc))
        self.assertGreater(meta["screen"]["share"], 0.05)

    def test_every_take_failed_is_a_normal_footage_video(self):
        doc, hy, assets = hybrid_doc(self.work, provider=FakeProvider(fail_models={"heygen/avatar-iv"}))
        hy.finish(doc)
        self.assertFalse(any(is_presenter_scene(s) for s in doc["scenes"]))
        self.assertEqual([s["media"]["source"] for s in doc["scenes"]], [a.source for a in assets])
        self.assertEqual(len(doc["meta"]["presenterHybrid"]["fellBack"]), len(hy.appearances))
        self.assertNotIn(hybrid.DISCLOSURE, doc["meta"].get("warnings") or [])


# ------------------------------------------------------------------ the footage passes leave it alone
class FootagePasses(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = self.tmp.name
        self.doc, self.hy, self.assets = hybrid_doc(self.work)
        self.hy.finish(self.doc)
        self.scenes = self.doc["scenes"]
        self.pres = [i for i, s in enumerate(self.scenes) if is_presenter_scene(s)]

    def tearDown(self):
        self.tmp.cleanup()

    def test_never_held_over_an_empty_neighbour(self):
        doc = copy.deepcopy(self.doc)
        i = next(k for k in self.pres if k + 1 < len(doc["scenes"]) and not is_presenter_scene(doc["scenes"][k + 1]))
        before = copy.deepcopy(doc["scenes"][i])
        doc["scenes"][i + 1]["media"] = {"type": "color", "url": "", "source": "none"}
        gapfill._hold(doc, i + 1, None)
        self.assertEqual(doc["scenes"][i]["durationInFrames"], before["durationInFrames"])
        self.assertEqual(doc["scenes"][i]["words"], before["words"])

    def test_gate_review_hook_check_recut_reclip(self):
        for i in self.pres:
            s = self.scenes[i]
            self.assertEqual(hookcheck._hook_shot(s), "")
            self.assertEqual(recut.kind_of(s), "presenter")
            self.assertEqual(reclip.kind_of(s), "presenter")
            self.assertFalse(reclip.needs_check(s))
        samples, skipped = review.plan_samples(self.doc)
        self.assertFalse(set(self.pres) & {smp.index for smp in samples})        # never sent to the AI review
        self.assertTrue(set(self.pres) <= set(skipped))
        # The gate: a presenter clip is never re-timed (0.5 s measured: "short") nor called a repeat.
        gate = quality.Gate(copy.deepcopy(self.doc), self.work)
        checks_ = {str(s["media"]["url"]): quality.Check(ok=True, reached=True, seconds=0.5)
                   for s in self.scenes if s["media"].get("url")}
        problems = gate._scene_problems(checks_)
        self.assertFalse(set(self.pres) & set(problems))

    def test_library_and_ledger_keep_the_real_half_never_the_presenter(self):
        items = ledger.items_from_doc(self.doc)
        self.assertFalse(any("presenter" in str(it.get("a") or "") for it in items))
        halves = [self.scenes[i]["media"]["split"] for i in self.pres if self.scenes[i].get("frame") == "split"]
        for h in halves:
            self.assertTrue(any(it.get("a") == h["assetId"][:160] for it in items), h["assetId"])
        doc = copy.deepcopy(self.doc)
        for k, s in enumerate(doc["scenes"]):
            s["media"]["url"] = f"{config.R2_PUBLIC_BASE or 'https://pub.example.r2.dev'}/projects/p/media/s{k}.mp4"
            if "split" in s["media"]:
                s["media"]["split"]["url"] = f"{config.R2_PUBLIC_BASE or 'https://pub.example.r2.dev'}/projects/p/media/s{k}_split.mp4"
        with mock.patch.object(library, "_r2_location", side_effect=lambda u: ("thumbgenius-videos", u.split(".dev/", 1)[-1])
                               if u else None):
            rows = library.shown_rows(doc, "p")
        paths = {r["storage_path"] for r in rows}
        for i in self.pres:
            self.assertNotIn(f"projects/p/media/s{i}.mp4", paths)             # never the presenter's clip
            if "split" in doc["scenes"][i]["media"]:
                self.assertIn(f"projects/p/media/s{i}_split.mp4", paths)      # its real half is shown footage

    def test_repeat_checks_see_the_real_half(self):
        doc = copy.deepcopy(self.doc)
        i = next(k for k in self.pres if doc["scenes"][k].get("frame") == "split")
        j = next(k for k in range(len(doc["scenes"])) if k > i and not is_presenter_scene(doc["scenes"][k]))
        half = doc["scenes"][i]["media"]["split"]
        doc["scenes"][j]["media"] = {"type": half["type"], "url": half["url"], "source": half["source"]}
        doc["scenes"][j]["semanticMetadata"]["assetId"] = half["assetId"]
        doc["scenes"][j]["semanticMetadata"]["sourceUrl"] = half.get("sourceUrl", "")
        found = dict(gapfill.find_repeats(doc))
        self.assertIn(j, found)                     # the later scene repeats the split's real half...
        self.assertNotIn(i, found)                  # ...and the presenter is never the one cleared

    def test_restore_never_refetches_a_presenter_clip(self):
        link = restore.Link(bucket="b", key="k", kind="video", role="scene", label="s0001", index=1,
                            provider=PRESENTER_SOURCE)
        how, why = restore.origin(link)
        self.assertEqual(how, "")
        self.assertIn("presenter", why)

    def test_split_half_without_r2_falls_back_to_full_screen(self):
        doc = copy.deepcopy(self.doc)
        for s in doc["scenes"]:
            if "split" in s["media"]:
                s["media"]["split"]["url"] = os.path.join(self.work, "half.mp4")
                open(s["media"]["split"]["url"], "wb").write(b"x" * 4000)
        with mock.patch.object(handler.r2, "enabled", return_value=False):
            n = handler._publish_split_halves(doc, "proj")
        self.assertEqual(n, 0)
        self.assertFalse(any("split" in s["media"] or s.get("frame") == "split" for s in doc["scenes"]))


# ------------------------------------------------------------------ the estimate and the app card
class Estimate(unittest.TestCase):
    def test_normal_build_plus_presenter_seconds(self):
        e = hybrid.estimate(10, "medium")
        self.assertEqual(e["presenterSeconds"], 84)
        billed = (84 + hybrid.PAD_SECONDS * 84 / 5.0) * (1 + hybrid.RETRY_SHARE)
        self.assertAlmostEqual(e["parts"]["presenter"], round(billed * 0.05, 2), places=2)
        self.assertAlmostEqual(e["parts"]["normalBuild"], round(10 * hybrid.NORMAL_PER_MIN, 2), places=2)
        self.assertLess(hybrid.estimate(10, "light")["usd"], e["usd"])
        self.assertLess(e["usd"], hybrid.estimate(15, "medium")["usd"])

    def test_presenter_info_carries_the_hybrid_table(self):
        out = handler.handler({"id": "t-info", "input": {"action": "presenter_info"}})
        h = out["hybrid"]
        self.assertEqual(set(h["byShare"]), {"light", "medium"})
        for share in ("light", "medium"):
            self.assertEqual(set(h["byShare"][share]), {"10", "15", "20"})
        self.assertEqual(h["shares"], {"light": 0.08, "medium": 0.14})
        self.assertIn("disclosure", h)


# ------------------------------------------------------------------ without a block, nothing changes
class _Built(Exception):
    pass


def fake_download(url, dest, timeout=0, headers=None):
    with open(dest, "wb") as fh:
        fh.write(b"\x00\x00\x00\x18ftypisom" + bytes(3000))
    return dest


class Unchanged(unittest.TestCase):
    def test_timeline_without_a_block_is_the_base_commits_byte_for_byte(self):
        doc = fixture.build(timeline, Segment, Word, MediaAsset)
        got = json.dumps(doc, sort_keys=True, indent=1, default=str)
        with open(GOLDEN, encoding="utf-8") as fh:
            want = fh.read()
        self.assertEqual(got, want)

    def test_force_config_only_with_a_block(self):
        inp = {"action": "build", "video_style": "documentary", "config": {"GRADE": True}}
        self.assertIsNone(hybrid.block(inp))
        b = dict(inp, presenter={"presenter_id": "hollis"})
        hybrid.force_config(b)
        self.assertEqual(b["config"], {"GRADE": True, **hybrid.FORCED_CONFIG})
        for k in hybrid.FORCED_CONFIG:
            self.assertIn(k, handler.CONFIG_OVERRIDABLE)

    def _plan(self, inp, start=None, sourced=None):
        segs, shots, assets, _inp, total = plan_inputs()
        seen = {"asked": []}

        line_of = {seg.text: i for i, seg in enumerate(segs)}

        def source_many(jobs_, work, **kw):
            # (handler.local numbers a call's lines 0..n-1 again: each is known by its own words.)
            asked = sorted(line_of[j["context"]] for j in jobs_)
            seen["asked"].append(asked)
            return [MediaAsset(kind="video", source="youtube", url=f"https://www.youtube.com/watch?v=SRCH{k:07d}",
                               local_path="", moment_key=f"yt:SRCH{k:07d}@1", duration=8.0)
                    for k in asked]

        def build(segments, shots_, assets_, **kw):
            seen["assets"] = list(assets_)
            raise _Built()
        patches = [mock.patch.object(handler.storage, "resolve_audio", return_value="https://x/vo.mp3"),
                   mock.patch.object(handler.storage, "download", side_effect=fake_download),
                   mock.patch.object(handler.renderer, "probe_duration", return_value=total),
                   mock.patch.object(handler.transcribe, "transcribe_words", return_value=[object()]),
                   mock.patch.object(handler.transcribe, "segment_words", return_value=segs),
                   mock.patch.object(handler.director, "story_brief", return_value=dict(_inp["brief"])),
                   mock.patch.object(handler.director, "plan", return_value=(shots, "ai", [])),
                   mock.patch.object(handler.library.Library, "load", return_value=None),
                   mock.patch.object(handler.fanout, "enabled_for", return_value=False),
                   mock.patch.object(handler.pools, "source_by_subject", return_value={}),
                   mock.patch.object(handler.media, "source_many", side_effect=source_many),
                   mock.patch.object(handler.media, "rescue_fill", return_value={}),
                   mock.patch.object(handler.timeline, "build", side_effect=build),
                   mock.patch.object(config, "UPSCALE_ENABLED", False), mock.patch.object(config, "ALLOW_VERTICAL", False),
                   mock.patch.object(config, "ARCHIVE_RESTORE", False), mock.patch.object(config, "MENTION_CUTS", False),
                   mock.patch.object(config, "SHOT_MAX_SECONDS", 0.0)]
        if start is not None:
            patches.append(mock.patch.object(handler.presenter_hybrid, "start", side_effect=start))
        for p in patches:
            p.start()
        try:
            with self.assertRaises(_Built):
                handler.do_plan(dict(inp, audio_url="vo.mp3", project_id=""), tempfile.mkdtemp(), handler.Reporter(""))
        finally:
            for p in reversed(patches):
                p.stop()
            handler.vision.set_story({})
            gapfill.reset()
        return seen, segs

    def test_do_plan_without_a_block_never_touches_the_hybrid(self):
        def boom(*a, **kw):
            raise AssertionError("the hybrid ran without a presenter block")
        seen, segs = self._plan({"video_style": ""}, start=boom)
        self.assertEqual(seen["asked"], [list(range(len(segs)))])               # every line searched, once
        self.assertTrue(all(a is not None and a.source == "youtube" for a in seen["assets"]))

    def test_a_bad_block_fails_the_plan_before_anything_is_paid_for(self):
        with mock.patch.object(handler.storage, "download", side_effect=AssertionError("downloaded")),                 mock.patch.object(handler.director, "story_brief", side_effect=AssertionError("planned")):
            with self.assertRaises(ValueError) as e:
                handler.do_plan({"audio_url": "vo.mp3", "project_id": "", "video_style": "documentary",
                                 "presenter": {"presenter_id": "nobody-at-all"}}, tempfile.mkdtemp(),
                                handler.Reporter(""))
        self.assertIn("presenter", str(e.exception))

    def test_do_plan_with_a_block(self):
        tmp = tempfile.mkdtemp()
        kit = kit_in(os.path.join(tmp, "kitsrc"), framings=("medium", "closeup"))
        _segs, _shots, _assets, _inp, total = plan_inputs()
        wav = make_wav(os.path.join(tmp, "narration.wav"), total + 1.0)
        made = {}

        def start(inp, segments, shots, *, narration_path, duration, work, brief=None, **kw):
            hy = REAL_START(inp, segments, shots, narration_path=wav, duration=duration, work=work, brief=brief,
                            provider=FailFor({"h00"}), store=FakeStore(), cache_dir=os.path.join(tmp, "cache"))
            made["hy"] = hy
            return hy
        seen, segs = self._plan({"video_style": "",
                                 "presenter": {"presenter_kit": kit, "share": "medium", "split_screen": True}},
                                start=start)
        hy = made["hy"]
        full = {i for ap in hy.appearances if not ap.split for i in ap.lines}
        failed = set(hy.failed_full())
        first = set(seen["asked"][0])
        self.assertFalse(full & first)                                         # never searched up front
        self.assertTrue({i for ap in hy.appearances if ap.split for i in ap.lines} <= first)
        self.assertEqual(set(seen["asked"][1]), failed)                        # the failed take's lines, after
        assets = seen["assets"]
        for i in hy.settled():
            self.assertEqual(assets[i].source, PRESENTER_SOURCE)
        for i in failed:
            self.assertEqual(assets[i].source, "youtube")                      # real footage for its line
        self.assertTrue(all(a is not None for a in assets))


if __name__ == "__main__":
    unittest.main()
