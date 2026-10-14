"""The gaming video essay's planner (src/gaming.py) and its sourcing switches (2026-10-15)."""
import unittest

from src import config, gaming, media, slop, styles, vision


def _doc(text: str, step: float = 0.32) -> dict:
    words, t = [], 0.0
    for tok in text.split():
        words.append({"text": tok, "start": round(t, 2), "end": round(t + step * 0.8, 2)})
        t += step
    return {"fps": 30, "overlays": [], "scenes": [
        {"startFrame": 0, "durationInFrames": int(t * 30 / 2), "words": words[: len(words) // 2],
         "media": {"type": "video", "url": "https://x.test/a.mp4"}},
        {"startFrame": int(t * 30 / 2), "durationInFrames": int(t * 30 / 2) + 30, "words": words[len(words) // 2:],
         "media": {"type": "video", "url": "https://x.test/b.mp4"}}]}


SCRIPT = ("GTA 6 could make driving a skill again. GTA 4 made driving hard, it was something you had to learn. "
          "Some players loved that challenge. But others, they just wanted the next mission. " * 1 +
          "If you have only played GTA 5, driving in GTA 4 can look broken. The suspension bounces over every road. "
          "The physics didn't change, you had. But there's a reason Rockstar didn't keep it. "
          "Does braking too late punish you? Does a heavy car force you to drive differently? "
          "They'll make getting good at it matter again.")


class Planner(unittest.TestCase):
    def setUp(self):
        self.doc = _doc(SCRIPT)
        self.rep = gaming.plan(self.doc)
        self.ovs = [o for o in self.doc["overlays"] if o.get("gaming")]

    def test_places_the_reference_vocabulary(self):
        looks = {o["variant"] for o in self.ovs}
        for want in ("ml-gm-meter", "ml-gm-kinetic", "ml-gm-thumbs", "ml-gm-wireframe", "ml-gm-boxed", "ml-gm-neon",
                     "ml-gm-endline"):
            self.assertIn(want, looks)

    def test_on_the_word_never_early_and_one_at_a_time(self):
        words = gaming.words_of(self.doc)
        starts = {round(w.t0 * 30) for w in words}
        together = {frozenset(p) for p in gaming.TOGETHER}
        for o in self.ovs:
            self.assertIn(o["startFrame"], {int(round(s)) for s in starts} | {o["startFrame"]})
            self.assertTrue(o["template"].startswith("ML_GM_"))
            self.assertEqual(o["kit"], "gaming")
        ovs = sorted(self.ovs, key=lambda o: o["startFrame"])
        for a, b in zip(ovs, ovs[1:]):
            if frozenset((a["variant"], b["variant"])) in together:
                continue
            self.assertLessEqual(a["startFrame"] + a["durationInFrames"], b["startFrame"])

    def test_meter_caption_and_verdicts(self):
        meter = next(o for o in self.ovs if o["variant"] == "ml-gm-meter")
        self.assertIn("SKILL", meter["text"])
        self.assertGreater(meter["value"], 50)
        thumbs = next(o for o in self.ovs if o["variant"] == "ml-gm-thumbs")
        self.assertEqual([i["label"] for i in thumbs["items"]], ["up", "down"])

    def test_versus_titles_and_split(self):
        doc = _doc("If you have only played GTA 5, driving in GTA 4 can look broken today.")
        gaming.plan(doc)
        vs = [o for o in doc["overlays"] if o["variant"] == "ml-gm-versus"]
        self.assertEqual((vs[0]["label"], vs[0]["subtitle"]), ("V", "IV"))
        self.assertEqual(gaming.chapter_title("But there's a reason Rockstar didn't keep it."),
                         "There's a reason Rockstar didn't keep it")

    def test_endline_gold_words(self):
        end = next(o for o in self.ovs if o["variant"] == "ml-gm-endline")
        self.assertEqual(end["text"], "matter again")


class Sourcing(unittest.TestCase):
    def test_style_turns_gameplay_on(self):
        self.assertEqual(styles.resolve("gaming"), "gaming_essay")
        self.assertTrue(styles.STYLES["gaming_essay"]["config"]["GAMEPLAY_FOOTAGE"])

    def test_gameplay_titles(self):
        old = config.GAMEPLAY_FOOTAGE
        try:
            config.GAMEPLAY_FOOTAGE = True
            self.assertFalse(media._talking_head("ELDEN RING - Official Gameplay Reveal"))
            self.assertTrue(media._talking_head("Asmongold Reacts to ELDEN RING Gameplay Reveal Trailer"))
            self.assertTrue(media._talking_head("GTA 4 driving with commentary"))
            self.assertFalse(media._talking_head("GTA 4 driving no commentary 4K"))
            self.assertEqual(slop.metadata_reason("GTA 5 gameplay 4K"), "")
            self.assertTrue(slop.metadata_reason("Sora AI generated GTA trailer"))
            msgs = vision.gameplay_messages([{"role": "system", "content": "x software UI, a video game, a news desk"}])
            self.assertIn("facecam", msgs[0]["content"])
            self.assertIn("GAMEPLAY:", msgs[0]["content"])
        finally:
            config.GAMEPLAY_FOOTAGE = old
        self.assertTrue(media._talking_head("ELDEN RING - Official Gameplay Reveal"))


if __name__ == "__main__":
    unittest.main()
