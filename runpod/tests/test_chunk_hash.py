"""
Chunk reuse (src/fanout.py chunk_hash): a chunk's fingerprint covers every
scene that draws in it, including one playing on under the next scene's
crossfade and the next scene's cut transition drawn over a scene's tail.
"""
import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import fanout, timeline  # noqa: E402


def _doc(transitions=("none", "crossfade", "none")):
    scenes = [{"id": f"s{i}", "startFrame": 100 * i, "durationInFrames": 100, "text": f"beat {i}",
               "transition": t, "media": {"type": "video", "url": f"https://x/{i}.mp4",
                                           "storage": {"bucket": "b", "path": f"projects/x/media/s{i}.mp4"}}}
              for i, t in enumerate(transitions)]
    return {"fps": 30, "width": 1920, "height": 1080, "durationInFrames": 100 * len(scenes),
            "scenes": scenes, "overlays": [], "captions": {"enabled": False}}


def _replace_clip(doc, i):
    out = copy.deepcopy(doc)
    out["scenes"][i]["media"] = {"type": "video", "url": "https://x/new.mp4",
                                 "storage": {"bucket": "b", "path": "projects/x/media/new.mp4"}}
    return out


class ChunkHash(unittest.TestCase):
    def test_a_scene_dissolving_under_the_next_counts_in_the_next_chunk(self):
        doc = _doc()
        # Scene 0 ends at frame 99 but plays on to 114 under scene 1's crossfade.
        self.assertNotEqual(fanout.chunk_hash(_replace_clip(doc, 0), 105, 199), fanout.chunk_hash(doc, 105, 199))
        # Past the dissolve it no longer draws there.
        self.assertEqual(fanout.chunk_hash(_replace_clip(doc, 0), 115, 199), fanout.chunk_hash(doc, 115, 199))
        # A hard cut into scene 1: scene 0 stops at 99.
        cut = _doc(("none", "none", "none"))
        self.assertEqual(fanout.chunk_hash(_replace_clip(cut, 0), 100, 199), fanout.chunk_hash(cut, 100, 199))

    def test_the_next_scenes_transition_counts_for_this_scenes_tail(self):
        doc = _doc(("none", "none", "none"))
        flash = copy.deepcopy(doc)
        flash["scenes"][2]["transition"] = "flash"
        # Chunk 0-195 ends in scene 1's last frames, where scene 2's flash starts.
        self.assertNotEqual(fanout.chunk_hash(flash, 0, 195), fanout.chunk_hash(doc, 0, 195))
        # A chunk that ends before scene 1 is untouched.
        self.assertEqual(fanout.chunk_hash(flash, 0, 99), fanout.chunk_hash(doc, 0, 99))

    def test_the_crossfade_length_matches_the_renderer(self):
        self.assertEqual(fanout.CROSSFADE_FRAMES, timeline.CROSSFADE_FRAMES)
        with open(os.path.join(ROOT, "remotion", "src", "Main.tsx"), encoding="utf-8") as fh:
            self.assertIn(f"CROSSFADE_FRAMES = {fanout.CROSSFADE_FRAMES}", fh.read())


if __name__ == "__main__":
    unittest.main()
