"""
GoMotion's persistent figure: a compact ring or number riding on a clip
stays up across the short cuts that follow it ("22% OF CAPACITY REMAINING"
held over three consecutive shots) instead of leaving with its sentence.
"""
import unittest
from unittest import mock

from src import config, templates, treatments
from src.transcribe import Segment

FPS = 30


def build(durations, texts):
    """Segments and scenes laid end to end with the given lengths (seconds)."""
    segments, scenes, at = [], [], 0.0
    for i, (d, t) in enumerate(zip(durations, texts)):
        segments.append(Segment(text=t, start=at, end=at + d))
        scenes.append({"id": f"s{i}", "startFrame": int(round(at * FPS)), "durationInFrames": int(round(d * FPS)),
                       "media": {"type": "video", "url": "x"}, "transition": "none", "motion": "none", "effect": "none"})
        at += d
    return segments, scenes


def plan(durations, texts, scenes=None):
    segments, built = build(durations, texts)
    scenes = scenes or built
    total = scenes[-1]["startFrame"] + scenes[-1]["durationInFrames"]
    brief = {"kind": "explainer", "sections": [], "hookBeats": []}
    return treatments.plan(segments, [{"subject": "Lake Powell"} for _ in texts], scenes, FPS, total, brief,
                           treatments.pack_for(brief))


FIGURE = "Lake Powell is now at 22 percent capacity."
PLAIN = ["Plain words about the water here.", "More plain words about the canyon.", "And the marina sits in dry gravel."]


def figure_overlay(out):
    ovs = [o for o in out["overlays"] if o.get("value") == 22.0]
    assert ovs, out["overlays"]
    return ovs[0]


class Persist(unittest.TestCase):
    def test_a_figure_holds_across_two_short_scenes(self):
        out = plan([4.0, 2.0, 2.0], [FIGURE] + PLAIN[:2])
        ov = figure_overlay(out)
        self.assertEqual(ov["startFrame"], 0)
        # Extended to the end of the second short scene (8 s in all, the ceiling
        # since 2026-09-30: "don't keep it longer").
        self.assertEqual(ov["startFrame"] + ov["durationInFrames"], 8 * FPS)
        # The treatment's duration follows the overlay.
        tr = next(t for t in out["treatments"] if t["template"] == ov["template"])
        self.assertAlmostEqual(tr["duration"], 8.0)
        # Still one figure on the clip: not a full-screen graphic.
        self.assertNotEqual(ov.get("backdrop"), "blur")

    def test_the_run_stops_at_the_ceiling(self):
        out = plan([4.0, 2.0, 2.0, 2.0], [FIGURE] + PLAIN)
        ov = figure_overlay(out)
        self.assertLessEqual(ov["durationInFrames"] / FPS, config.PERSIST_MAX_SECONDS + 1e-6)
        self.assertEqual(ov["startFrame"] + ov["durationInFrames"], 8 * FPS)

    def test_no_extension_over_a_long_scene(self):
        out = plan([6.0, 6.0, 3.0], [FIGURE] + PLAIN[:2])
        ov = figure_overlay(out)
        # The voice window alone: never past the figure window's 4 s.
        self.assertLessEqual(ov["durationInFrames"] / FPS, treatments.LAYOUT_WINDOWS["figure"][1] + 1e-6)

    def test_a_figure_never_runs_into_the_next_overlay(self):
        # Without rule (c) the figure would run to 8 s, over the 45% graphic that lands at 6 s.
        out = plan([4.0, 2.0, 2.0], [FIGURE, PLAIN[0], "Its neighbour Lake Mead holds 45 percent of its water."])
        ovs = sorted(out["overlays"], key=lambda o: o["startFrame"])
        self.assertGreaterEqual(len(ovs), 2, ovs)
        first, second = ovs[0], ovs[1]
        self.assertEqual((first.get("value"), second.get("value")), (22.0, 45.0))
        # Held over the plain shot, released as the next graphic lands.
        self.assertEqual(first["startFrame"] + first["durationInFrames"], 6 * FPS)
        self.assertLessEqual(first["startFrame"] + first["durationInFrames"], second["startFrame"])

    def test_no_extension_under_an_animation_scene(self):
        segments, scenes = build([6.0, 3.0, 3.0], [FIGURE] + PLAIN[:2])
        scenes[1]["media"] = {"type": "animation", "url": ""}
        scenes[1]["animation"] = {"template": "NUM_PERCENT_V1", "value": 60.0}
        out = plan([6.0, 3.0, 3.0], [FIGURE] + PLAIN[:2], scenes=scenes)
        ov = figure_overlay(out)
        self.assertLessEqual(ov["durationInFrames"] / FPS, treatments.LAYOUT_WINDOWS["figure"][1] + 1e-6)

    def test_flag_off_leaves_the_plan_unchanged(self):
        with mock.patch.object(config, "PERSIST_FIGURES", False):
            off = plan([4.0, 2.0, 2.0], [FIGURE] + PLAIN[:2])
        on = plan([4.0, 2.0, 2.0], [FIGURE] + PLAIN[:2])
        a, b = figure_overlay(off), figure_overlay(on)
        self.assertLessEqual(a["durationInFrames"] / FPS, treatments.LAYOUT_WINDOWS["figure"][1] + 1e-6)
        self.assertGreater(b["durationInFrames"], a["durationInFrames"])
        # Everything else about the overlay is the same (the corner alternates per plan call).
        skip = {"durationInFrames", "position"}
        self.assertEqual({k: v for k, v in a.items() if k not in skip}, {k: v for k, v in b.items() if k not in skip})


class PersistLooks(unittest.TestCase):
    """The LibPersist family ("ps-") is its own layout class: a long hold, no compact scaling, one at a time."""

    def test_ps_looks_get_the_persist_class(self):
        t = {"id": "LIB_PS_PERCENT_RING", "kind": "tag", "category": "NUMBERS", "tags": [],
             "defaults": {"variant": "ps-percent-ring", "duration": 10.0}}
        self.assertEqual(treatments.layout_class(t, "percent"), "persist")
        self.assertEqual(treatments.LAYOUT_WINDOWS["persist"], (5.0, 8.0))
        ov = {"template": t["id"]}
        treatments.apply_layout(ov, t, "persist")
        self.assertNotIn("compact", ov)
        self.assertNotIn("scale", ov)
        self.assertNotIn("backdrop", ov)
        # An ordinary percent look is still a figure.
        self.assertEqual(treatments.layout_class(templates.get("NUM_PERCENT_V1"), "percent"), "figure")


if __name__ == "__main__":
    unittest.main()
