"""
Image looks never show an empty slot (the owner's Lake Powell video,
2026-10-01: a split look showed one picture beside two dark, empty slots).

  * the cause in the editor: the app's page CSS (Tailwind's preflight,
    img { max-width: 100% }) clamped every picture to its box, so a strip
    showing its third of a full-frame photo slid out of it; the composition
    now resets that for its own pictures (Main.tsx PAGE_CSS_GUARD);
  * the planner gives every slot of every image look a real picture
    (treatments.bind_look_pictures): the scene's own still or footage frame,
    then nearby scenes' pictures of the same subject (stills first, nearest
    first, never the same file twice), then the clip library; a look short
    of pictures becomes a one-picture look, a look with none is left out; a
    person's look shows only its own scene; the web-photo windows are the
    build's to fill;
  * a build carries the result, and the renderer reads it (mediaFrom).
"""
import os
import unittest

from src import templates, timeline, treatments
from tests import test_planner_quality as quality

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REMOTION = os.path.join(ROOT, "remotion")


def scene(i, kind="image", subject="Lake Powell", url=None, subject_type="place"):
    media = {"type": kind, "url": url if url is not None else f"https://pub.example/media/s{i}.{'jpg' if kind == 'image' else 'mp4'}",
             "source": "web_image"}
    if kind in ("animation", "color"):
        media = {"type": kind, "url": "", "source": "template"}
    return {"id": f"s{i:04d}", "startFrame": i * 90, "durationInFrames": 90, "text": f"line {i}", "media": media,
            "semanticMetadata": {"subject": subject, "subjectType": subject_type}}


def look(tid, i, **kw):
    t = templates.get(tid)
    return {"type": t["component"], "template": tid, "variant": (t.get("defaults") or {}).get("variant"),
            "startFrame": i * 90 + 10, "durationInFrames": 120, "text": "LAKE POWELL", **kw}


class FakeLibrary:
    def __init__(self, n):
        self.n = n
        self.asked = []

    def find(self, subject, exclude=None, n=1, min_score=None, kind="video", story=None):
        self.asked.append((subject, n, kind))
        return [{"id": f"lib{k}", "read_url": f"https://r2.example/library/images/{k}.jpg", "attribution": "NPS"}
                for k in range(min(n, self.n))]


class Slots(unittest.TestCase):
    def test_every_look_that_shows_pictures_says_how_many(self):
        self.assertEqual(treatments.look_slots(templates.get("LIB_PE_SPLIT_PANELS")), (1, 1))
        self.assertEqual(treatments.look_slots(templates.get("LIB_PB_TRIPTYCH")), (3, 3))
        self.assertEqual(treatments.look_slots(templates.get("LIB_CP_PHOTO_VERSUS")), (2, 2))
        self.assertEqual(treatments.look_slots(templates.get("PHOTO_COLLAGE_V1")), (3, 6))
        self.assertEqual(treatments.look_slots(templates.get("PHOTO_CARD_V1")), (1, 1))
        self.assertEqual(treatments.look_slots(templates.get("TEXT_TYPEWRITER_V1")), (0, 0))
        # Every multi-picture look of the registry is counted, and every fallback is a real one-picture look.
        for t in templates.all_templates():
            if "stills" in (t.get("tags") or []):
                self.assertIn((t.get("defaults") or {}).get("variant"), treatments.LOOK_SLOTS, t["id"])
        for tid in treatments.ONE_PICTURE_LOOKS:
            self.assertEqual(treatments.look_slots(templates.get(tid)), (1, 1), tid)

    def test_same_subject(self):
        self.assertTrue(treatments.same_subject("Lake Powell", "Lake Powell low water launch ramps"))
        self.assertTrue(treatments.same_subject("Texas", "the Texas Hill Country"))
        self.assertFalse(treatments.same_subject("Lake Powell", "Lake Mead"))
        self.assertFalse(treatments.same_subject("Glen Canyon Dam", "Lake Powell"))
        self.assertFalse(treatments.same_subject("", "Lake Powell"))


class Binding(unittest.TestCase):
    def test_a_one_picture_look_takes_its_own_scenes_picture(self):
        scenes = [scene(i) for i in range(5)]
        ovs = [look("LIB_PE_SPLIT_PANELS", 2)]
        got = treatments.bind_look_pictures(ovs, scenes)
        self.assertEqual(got, {"bound": 1, "swapped": 0, "dropped": 0})
        self.assertEqual(ovs[0]["mediaFrom"], ["s0002"])
        self.assertNotIn("media", ovs[0])

    def test_over_a_scene_without_a_picture_it_takes_a_neighbour_of_the_same_subject_or_goes(self):
        scenes = [scene(0, subject="Lake Mead"), scene(1, "animation"), scene(2, subject="Lake Powell ramps"),
                  scene(3, "video")]
        ovs = [look("LIB_PE_SPLIT_PANELS", 1)]
        treatments.bind_look_pictures(ovs, scenes)
        self.assertEqual(ovs[0]["mediaFrom"], ["s0002"])          # the still of the same subject, not Lake Mead
        scenes = [scene(0, subject="Lake Mead"), scene(1, "animation"), scene(2, subject="Hoover Dam")]
        ovs = [look("LIB_PE_SPLIT_PANELS", 1)]
        self.assertEqual(treatments.bind_look_pictures(ovs, scenes)["dropped"], 1)
        self.assertEqual(ovs, [])

    def test_a_several_picture_look_fills_every_slot_stills_first_nearest_first(self):
        scenes = [scene(0, "video"), scene(1), scene(2, "video"), scene(3), scene(4), scene(5, subject="Lake Mead"),
                  scene(6)]
        ovs = [look("LIB_PB_TRIPTYCH", 3)]
        treatments.bind_look_pictures(ovs, scenes)
        # Its own scene, then Lake Powell's stills nearest first (4, then 1) before the nearer clip at 2.
        self.assertEqual(ovs[0]["mediaFrom"][0], "s0003")
        self.assertEqual(len(ovs[0]["mediaFrom"]), 3)
        self.assertEqual(ovs[0]["mediaFrom"][1:], ["s0004", "s0001"])
        self.assertNotIn("s0005", ovs[0]["mediaFrom"])            # another subject

    def test_the_same_file_never_fills_two_slots(self):
        same = "https://pub.example/media/clip.mp4"
        scenes = [scene(0, "video", url=same), scene(1, "video", url=same), scene(2, "video", url=same)]
        ovs = [look("LIB_PB_WIPE_COMPARE", 1)]
        got = treatments.bind_look_pictures(ovs, scenes)
        self.assertEqual(got["swapped"], 1)                       # one picture: a one-picture look instead
        self.assertIn(ovs[0]["template"], treatments.ONE_PICTURE_LOOKS)
        self.assertEqual(ovs[0]["variant"], templates.get(ovs[0]["template"])["defaults"]["variant"])
        self.assertEqual(ovs[0]["mediaFrom"], ["s0001"])

    def test_the_library_fills_what_the_story_cannot(self):
        scenes = [scene(0, subject="Lake Mead"), scene(1), scene(2, subject="Lake Mead")]
        lib = FakeLibrary(5)
        ovs = [look("LIB_PB_TRIPTYCH", 1)]
        got = treatments.bind_look_pictures(ovs, scenes, library=lib)
        self.assertEqual(got["bound"], 1)
        self.assertEqual(ovs[0]["mediaFrom"], ["s0001"])
        self.assertEqual([m["source"] for m in ovs[0]["media"]], ["library", "library"])
        self.assertEqual(lib.asked, [("Lake Powell", 2, "image")])
        # With too few there either: a one-picture look.
        ovs = [look("LIB_PB_TRIPTYCH", 1)]
        self.assertEqual(treatments.bind_look_pictures(ovs, scenes, library=FakeLibrary(1))["swapped"], 1)

    def test_a_persons_look_shows_only_its_own_scene(self):
        scenes = [scene(0, subject="Greg Abbott", subject_type="person"), scene(1, "animation", subject="Greg Abbott",
                                                                                 subject_type="person")]
        lib = FakeLibrary(5)
        ovs = [look("LIB_PF_PROFILE", 1)]
        self.assertEqual(treatments.bind_look_pictures(ovs, scenes, library=lib)["dropped"], 1)
        self.assertEqual(lib.asked, [])
        ovs = [look("LIB_PE_FRAME_DROP", 1)]                      # any photo look over a person's beat
        self.assertEqual(treatments.bind_look_pictures(ovs, scenes, library=lib)["dropped"], 1)
        ovs = [look("LIB_PF_PROFILE", 0)]
        treatments.bind_look_pictures(ovs, scenes)
        self.assertEqual(ovs[0]["mediaFrom"], ["s0000"])
        # Over a clip of the beat, a person card is left out: a frame of a clip can be anyone in it.
        scenes = [scene(0, "video", subject="Greg Abbott", subject_type="person")]
        ovs = [look("PERSON_CARD_V1", 0)]
        self.assertEqual(treatments.bind_look_pictures(ovs, scenes)["dropped"], 1)

    def test_looks_with_their_pictures_and_web_photo_windows_are_left_alone(self):
        scenes = [scene(i) for i in range(3)]
        given = look("PHOTO_CARD_V1", 1, media=[{"type": "image", "url": "https://x/own.jpg", "source": "web"}])
        pip = look("PHOTO_PIP_V1", 1)
        mosaic = look("LIB_PA_MOSAIC_ASSEMBLE", 1)                 # a subject photo the build searches the web for
        text = look("TEXT_TYPEWRITER_V1", 1)
        ovs = [given, pip, mosaic, text]
        self.assertEqual(treatments.bind_look_pictures(ovs, scenes), {"bound": 0, "swapped": 0, "dropped": 0})
        self.assertEqual(len(ovs), 4)
        for ov in ovs:
            self.assertNotIn("mediaFrom", ov)


class Build(unittest.TestCase):
    def test_every_image_look_of_a_build_has_a_picture_for_every_slot(self):
        doc = quality.build_doc(quality.FLOOD, inp={"voice_lufs": -20.0})
        self.assertIn("lookPictures", doc["meta"])
        by_id = {s["id"]: s for s in doc["scenes"]}
        looked = 0
        for ov in doc["overlays"]:
            t = templates.get(ov.get("template") or "")
            need, _most = treatments.look_slots(t)
            if not need or treatments._web_photo_look(ov, t):
                continue
            looked += 1
            pics = [m for m in ov.get("media") or [] if m.get("url")]
            for sid in ov.get("mediaFrom") or []:
                self.assertTrue(treatments._scene_picture(by_id[sid]), (ov["template"], sid))
            self.assertGreaterEqual(len(pics) + len(ov.get("mediaFrom") or []), need, ov)
        # And what a render does with it passes.
        timeline.drop_invalid_overlays(doc)
        timeline.validate(doc, require_media=False)
        self.assertGreaterEqual(looked, 0)

    def test_a_photo_card_the_planner_filled_from_a_scene_validates(self):
        ov = {"type": "photo-card", "template": "PHOTO_CARD_V1", "variant": "frame", "startFrame": 0,
              "durationInFrames": 60, "mediaFrom": ["s0000"]}
        self.assertTrue(timeline._borrows_pictures(ov))


class Renderer(unittest.TestCase):
    def _read(self, *parts):
        with open(os.path.join(REMOTION, "src", *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_the_page_css_never_resizes_the_pictures(self):
        main = self._read("Main.tsx")
        self.assertIn('".tg-composition img, .tg-composition video { max-width: none; max-height: none; }"', main)
        self.assertIn('<AbsoluteFill className="tg-composition"', main)
        self.assertIn("<style>{PAGE_CSS_GUARD}</style>", main)

    def test_the_renderer_draws_the_planners_pictures_and_never_an_empty_slot(self):
        main = self._read("Main.tsx")
        self.assertIn("ov.mediaFrom", main)
        self.assertIn("const pics = lookPictures(ov, scenes);", main)
        self.assertIn("mediaFrom?: string[];", self._read("types.ts"))
        # The split panels draw one picture into every strip (no per-strip picture that could be missing).
        split = self._read("components", "lib", "LibPhotoEditor.tsx")
        body = split[split.index("const SplitPanels: Look"):split.index("// ================================================================== pe-frame-drop")]
        self.assertIn("const src = photoOf(overlay);", body)
        self.assertIn("if (!src) return null;", body)


if __name__ == "__main__":
    unittest.main()
