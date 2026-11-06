"""The Breaking News Desk's 2026-11-07 rules (the owner's laptop kit, on the server): offline, no network, no paid call."""
import json
import os
import shutil
import tempfile
import unittest

from PIL import Image

from src import stormlooks, stormpieces


def _red_share(fr, box):
    """Share of the box's pixels that are strongly red."""
    import numpy as np
    a = np.asarray(fr.convert("RGB").crop(box)).astype(int)
    return float(((a[..., 0] > 150) & (a[..., 1] < 90) & (a[..., 2] < 90)).mean())


class StatStyle(unittest.TestCase):
    def test_options_default_to_small_top_right_no_plate(self):
        self.assertEqual(stormlooks.stat_options({}), {"style": "corner", "size": "small", "color": ""})
        self.assertEqual(stormlooks.stat_options(None)["style"], "corner")

    def test_options_take_the_jobs_and_refuse_nonsense(self):
        o = stormlooks.stat_options({"stat_style": "CENTER", "stat_color": "#ffcc00", "stat_size": "medium"})
        self.assertEqual(o, {"style": "center", "size": "medium", "color": "#FFCC00"})
        o = stormlooks.stat_options({"stat_style": "huge", "stat_color": "red;", "stat_size": "giant"})
        self.assertEqual(o, {"style": "corner", "size": "small", "color": ""})
        self.assertEqual(stormlooks.stat_options({"stat_style": "center"})["size"], "large")     # the old big one

    def test_a_shot_spec_carries_the_style(self):
        tl = {"stats": [[1.0, 3.0, "13 DAYS"]]}
        row = stormpieces.looks_for_shot(tl, 0, 300, 30, {"style": "corner_plate", "size": "large", "color": "#00FF00"})[0]
        self.assertEqual(row, ["stat", 1.0, 3.0, "13 DAYS", "corner_plate", 72, "#00FF00"])
        self.assertEqual(stormpieces.looks_for_shot(tl, 0, 300, 30)[0][4:], ["corner", 46, ""])

    def test_the_style_changes_the_shots_name(self):
        def scene_doc(style):
            return {"fps": 30, "durationInFrames": 300, "stormDesk": {"statStyle": style, "looks": {"stats": [[1.0, 3.0, "13 DAYS"]]}},
                    "scenes": [{"id": "a", "startFrame": 0, "durationInFrames": 300, "media": {"type": "video", "url": "/tmp/a.mp4"}}]}
        a = stormpieces.spec_key(stormpieces.build_specs(scene_doc({"style": "corner"}))[0])
        b = stormpieces.spec_key(stormpieces.build_specs(scene_doc({"style": "center"}))[0])
        self.assertNotEqual(a, b)

    def _drawn(self, row):
        from src.sdkit import looks as L
        fr = Image.new("RGBA", (1920, 1080), (40, 60, 80, 255))
        stormpieces._draw_stat(fr, 1.5, row, L)
        return fr

    def test_corner_draws_top_right_center_draws_the_middle(self):
        corner = self._drawn(["stat", 1.0, 3.0, "13 DAYS UP", "corner", 46, ""])
        self.assertGreater(_red_share(corner, (1500, 80, 1900, 160)), 0.02)
        self.assertLess(_red_share(corner, (500, 400, 1420, 560)), 0.001)
        center = self._drawn(["stat", 1.0, 3.0, "13 DAYS UP", "center", 104, ""])
        self.assertGreater(_red_share(center, (500, 400, 1420, 560)), 0.02)
        self.assertLess(_red_share(center, (1500, 80, 1900, 160)), 0.001)

    def test_plate_darkens_behind_the_stat_and_colour_replaces_red(self):
        import numpy as np
        plain = self._drawn(["stat", 1.0, 3.0, "13 DAYS UP", "corner", 46, ""])
        plated = self._drawn(["stat", 1.0, 3.0, "13 DAYS UP", "corner_plate", 46, ""])
        box = (1500, 80, 1900, 160)
        self.assertLess(np.asarray(plated.convert("L").crop(box)).mean(), np.asarray(plain.convert("L").crop(box)).mean())
        green = self._drawn(["stat", 1.0, 3.0, "13 DAYS UP", "corner", 46, "#00FF00"])
        self.assertLess(_red_share(green, box), 0.001)

    def test_no_stat_outside_its_time(self):
        from src.sdkit import looks as L
        fr = Image.new("RGBA", (1920, 1080), (40, 60, 80, 255))
        before = fr.tobytes()
        L.corner_stat(fr, 5.0, 1.0, 3.0, "X")
        self.assertEqual(fr.tobytes(), before)


class ScreenChips(unittest.TestCase):
    def _keys(self, credit):
        d = {"fps": 30, "durationInFrames": 90, "stormDesk": {"logo": {"text": "T"}},
             "scenes": [{"id": "a", "startFrame": 0, "durationInFrames": 90, "credit": credit, "media": {"type": "video", "url": "/tmp/a.mp4"}}]}
        return stormpieces.scene_spec(d, 0, [])["layers"][0][1]

    def test_ai_chip_stays_archive_and_names_do_not(self):
        self.assertIn(("chip", "AI ILLUSTRATION", True), self._keys({"text": "AI ILLUSTRATION", "ai": True}))
        self.assertFalse(any(k[0] == "chip" for k in self._keys({"text": "VIDEO: KSL News"})))
        self.assertFalse(any(k[0] == "chip" for k in self._keys({"text": "VIDEO: KSL News", "archive": True})))


if __name__ == "__main__":
    unittest.main()
