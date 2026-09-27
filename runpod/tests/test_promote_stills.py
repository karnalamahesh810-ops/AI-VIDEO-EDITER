import unittest

from src import director, timeline
from src.transcribe import Segment


def plan(texts, subjects, kind="place"):
    segs = [Segment(text=t, start=i * 5, end=i * 5 + 5) for i, t in enumerate(texts)]
    shots = [{"visualType": "footage", "subject": s, "subjectType": kind} for s in subjects]
    return segs, shots


class PromoteStills(unittest.TestCase):
    def test_a_line_about_a_photo_gets_a_photo(self):
        segs, shots = plan(["Lake Mead is shrinking.", "A photograph from 1983 shows the lake full.", "Boats wait."],
                           ["Lake Mead", "Lake Mead", "Boulder Harbor"])
        self.assertEqual(director.promote_stills(segs, shots, {}), 1)
        self.assertEqual(shots[1]["visualType"], "image")
        self.assertEqual(shots[1]["stillReason"], "photo mentioned")

    def test_variety_every_seventh_line_for_named_subjects_only(self):
        texts = [f"Line {i}." for i in range(16)]
        segs, shots = plan(texts, ["Hoover Dam"] * 16)
        director.promote_stills(segs, shots, {})
        idx = [i for i, s in enumerate(shots) if s["visualType"] == "image"]
        self.assertEqual(idx, [6, 13])            # the 7th and 14th lines
        segs, shots = plan(texts, ["the workers"] * 16, kind="person")
        self.assertEqual(director.promote_stills(segs, shots, {}), 0)   # never a stranger's photo

    def test_never_two_in_a_row_and_never_past_the_cap(self):
        texts = ["A photo of the dam.", "Another photograph of it.", "A third picture."] * 4
        segs, shots = plan(texts, ["Hoover Dam"] * 12)
        director.promote_stills(segs, shots, {})
        kinds = [s["visualType"] for s in shots]
        self.assertFalse(any(a == b == "image" for a, b in zip(kinds, kinds[1:])))
        self.assertLessEqual(kinds.count("image"), int(director.MAX_STILL_SHARE * 12))

    def test_photos_cycle_through_the_new_moves(self):
        self.assertIn("reveal-left", timeline._IMAGE_MOTIONS)
        self.assertIn("reveal-right", timeline._IMAGE_MOTIONS)
        self.assertIn("push-rotate", timeline._IMAGE_MOTIONS)
        with open("remotion/src/types.ts", encoding="utf-8") as fh:
            src = fh.read()
        for m in timeline._IMAGE_MOTIONS:
            self.assertIn(f'"{m}"', src)


if __name__ == "__main__":
    unittest.main()
