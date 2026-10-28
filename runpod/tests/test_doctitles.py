"""Documentary titles render offline (no network): each look gives a full-frame RGBA frame at any time."""
import unittest

from src import doctitles as D


class Looks(unittest.TestCase):
    def test_every_look_renders(self):
        looks = [D.ActCard("Act 2", "The Flood That Went to the Wrong Lake", 2.8),
                 D.Number("1,037.16 ft", "Lake Mead · record low", 3.0, count_from=1000.0),
                 D.LowerThird("Katie Hobbs", "Governor of Arizona", 4.0)]
        for look in looks:
            for t in (0.0, 0.2, 1.5, look.seconds - 0.05):
                im = look.frame(t)
                self.assertEqual(im.size, (D.W, D.H))
                self.assertEqual(im.mode, "RGBA")
        # Fully faded at the very end, visible in the middle.
        self.assertEqual(looks[1].frame(3.0).split()[3].getextrema()[1], 0)
        self.assertGreater(looks[1].frame(1.5).split()[3].getextrema()[1], 200)

    def test_count_up_keeps_the_format(self):
        self.assertEqual(D._format_like("1,037.16 ft", 1000.0), "1,000.00 ft")
        self.assertEqual(D._format_like("−40%", 12.4), "−12%")

    def test_map_uses_real_geography(self):
        hoover, glen = (-114.7378, 36.0156), (-111.4836, 36.9375)
        m = D.MapScene(bbox=(-115.6, 35.3, -109.9, 38.2), seconds=4.0, lakes={"Lake Mead": 0.0},
                       river=("colorado-river", 0.0, 2.0, glen, hoover),
                       labels=[D.Label("Hoover Dam", *hoover, kind="pin", dx=-60, dy=60)])
        self.assertTrue(D.lake_rings("Lake Mead"))
        self.assertTrue(D.states(["US-AZ"]))
        im = m.frame(2.0)
        self.assertEqual(im.size, (D.W, D.H))


if __name__ == "__main__":
    unittest.main()
