"""
Smart re-render (src/rendercache.py, src/fanout.py render_pod): chunk
boundaries that follow the timeline, the hash of everything that draws a
chunk, the reuse of unchanged chunks and of the whole sound mix, the audio
shift rule (a narration that moves after time T: every chunk before T is
reused), the store and its clean-up. RunPod, R2 and Remotion are faked; the
look-picture port and the stream check run the real renderer code / ffmpeg.
"""
import copy
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import handler  # noqa: E402
from src import config, costs, fanout, r2, render, rendercache  # noqa: E402
from tests.test_render_chunks import FakeWorkers, _doc, _fake_count, _frames_file, _pod_env  # noqa: E402

REMOTION = os.path.join(ROOT, "remotion")
SRC = os.path.join(REMOTION, "src")
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "timeline_looks_sample.json")
ENC = {"renderer": "fp1", "crf": 18, "x264": "veryfast", "jpeg": 0}


def _hashes(doc, ranges, enc=None):
    d = rendercache.Doc(doc)
    return [rendercache.picture_hash(doc, a, b, enc or ENC, d) for a, b in ranges]


def _ranges(doc, seconds=20):
    with mock.patch.object(config, "POD_RENDER_CHUNK_SECONDS", seconds), \
            mock.patch.object(config, "POD_RENDER_MIN_CHUNK_FRAMES", 30):
        return rendercache.stable_chunks(doc, rendercache.chunk_frames(doc), config.POD_RENDER_MIN_CHUNK_FRAMES)


def _changed(a, b):
    return [i for i, (x, y) in enumerate(zip(a, b)) if x != y]


def _chunk_of(ranges, frame):
    return next(i for i, (a, b) in enumerate(ranges) if a <= frame <= b)


def _shift_after(doc, k, frames):
    """The narration's timing after scene k-1 moves by `frames` (scene k-1 is longer): everything after it shifts."""
    d = copy.deepcopy(doc)
    t = d["scenes"][k]["startFrame"]
    d["scenes"][k - 1]["durationInFrames"] += frames
    for s in d["scenes"][k:]:
        s["startFrame"] += frames
    for o in d.get("overlays") or []:
        if o["startFrame"] >= t:
            o["startFrame"] += frames
    for x in d.get("sfx") or []:
        if x.get("startFrame", 0) >= t:
            x["startFrame"] += frames
    d["durationInFrames"] += frames
    return d, t


# --------------------------------------------------------------------------- chunk boundaries
class StableChunks(unittest.TestCase):
    def test_chunks_cover_the_video_without_gaps_and_stay_near_their_length(self):
        rnd = random.Random(11)
        for seed in range(40):
            rnd.seed(seed)
            doc = _doc([rnd.randint(60, 300) for _ in range(rnd.randint(2, 220))],
                       {i: rnd.choice(["none", "none", "crossfade", "flash", "pack:mlt5"]) for i in range(220)})
            ranges = _ranges(doc)
            total = doc["durationInFrames"]
            self.assertEqual(ranges[0][0], 0)
            self.assertEqual(ranges[-1][1], total - 1)
            for (a, b), (c, _d) in zip(ranges, ranges[1:]):
                self.assertEqual(c, b + 1)
            for a, b in ranges[:-1]:
                self.assertLessEqual(b - a + 1, 900)            # 1.5 x the 600-frame target at most
                self.assertGreaterEqual(b - a + 1, 300)

    def test_boundaries_fall_on_clean_cuts_when_there_are_any(self):
        trans = {i: ("crossfade" if i % 3 == 1 else "flash" if i % 3 == 2 else "none") for i in range(60)}
        doc = _doc([200] * 60, trans)
        starts = {s["startFrame"]: s["transition"] for s in doc["scenes"]}
        for a, _b in _ranges(doc)[1:]:
            self.assertIn(a, starts)
            self.assertEqual(starts[a], "none")

    def test_an_edit_never_moves_an_earlier_boundary(self):
        rnd = random.Random(5)
        doc = _doc([rnd.randint(90, 240) for _ in range(200)])           # ~19 minutes
        ranges = _ranges(doc, seconds=90)
        target = 90 * 30
        for k in (70, 120, 170):
            for edit in ("longer", "shorter", "insert", "remove"):
                d = copy.deepcopy(doc)
                t = d["scenes"][k]["startFrame"]
                if edit == "longer":
                    d, t = _shift_after(doc, k, 37)
                elif edit == "shorter":
                    d, t = _shift_after(doc, k, -45)
                elif edit == "insert":
                    d, t = _shift_after(doc, k, 150)
                else:
                    gone = d["scenes"].pop(k)
                    for s in d["scenes"][k:]:
                        s["startFrame"] -= gone["durationInFrames"]
                    d["durationInFrames"] -= gone["durationInFrames"]
                new = _ranges(d, seconds=90)
                safe = [r for r in ranges if r[1] < t - int(target * 1.5)]
                self.assertTrue(safe)
                self.assertEqual(new[:len(safe)], safe, f"{edit} at scene {k}")

    def test_the_machine_never_changes_the_cut(self):
        doc = _doc([150] * 300)
        with mock.patch.object(config, "RENDER_CPUS", 8), mock.patch.object(config, "RENDER_CONCURRENCY", 4):
            small = _ranges(doc, seconds=90)
        with mock.patch.object(config, "RENDER_CPUS", 32), mock.patch.object(config, "RENDER_CONCURRENCY", 24):
            big = _ranges(doc, seconds=90)
        self.assertEqual(small, big)

    def test_a_short_tail_joins_the_chunk_before_it(self):
        doc = _doc([600] * 2 + [100])                                      # 1300 frames, target 600
        ranges = _ranges(doc)
        self.assertEqual(ranges[-1][1], 1299)
        self.assertGreaterEqual(ranges[-1][1] - ranges[-1][0] + 1, 300)
        self.assertEqual(_ranges(_doc([150] * 4)), [(0, 599)])            # one chunk's worth: one chunk

    def test_the_brand_seams_are_cut_points(self):
        doc = _doc([150] * 40)
        doc["brand"] = {"intro": {"url": "https://pub.example/intro.mp4", "frames": 120},
                        "outro": {"kind": "video", "url": "https://pub.example/outro.mp4", "frames": 150}}
        with mock.patch.object(fanout.brandkit, "layout", return_value=(120, 6000, 150, 6270)):
            clean, _visual, _every = fanout.chunk_cuts(doc)
            self.assertIn(120, clean)
            self.assertIn(6120, clean)
            ranges = _ranges(doc)
        self.assertEqual(ranges[-1][1], 6269)


# --------------------------------------------------------------------------- the picture hash
class PictureHash(unittest.TestCase):
    def setUp(self):
        self.doc = _doc([150] * 40)
        self.ranges = _ranges(self.doc)                                    # 600-frame chunks
        self.base = _hashes(self.doc, self.ranges)

    def edit(self, fn):
        d = copy.deepcopy(self.doc)
        fn(d)
        return _changed(self.base, _hashes(d, self.ranges))

    def test_the_same_document_hashes_the_same(self):
        self.assertEqual(_hashes(json.loads(json.dumps(self.doc)), self.ranges), self.base)
        self.assertEqual(len(set(self.base)), len(self.base))

    def test_a_swapped_clip_changes_its_chunk_only(self):
        def swap(d):
            d["scenes"][9]["media"]["url"] = "https://pub.example/media/other.mp4"
        self.assertEqual(self.edit(swap), [_chunk_of(self.ranges, 9 * 150)])

    def test_a_re_signed_link_is_the_same_file(self):
        def sign(d, token):
            d["scenes"][5]["media"]["url"] = f"https://sb.example/storage/v1/object/sign/m/s5.mp4?token={token}"
        a, b = copy.deepcopy(self.doc), copy.deepcopy(self.doc)
        sign(a, "aaa")
        sign(b, "bbb")
        self.assertEqual(_hashes(a, self.ranges), _hashes(b, self.ranges))
        c = copy.deepcopy(self.doc)
        c["scenes"][5]["media"]["url"] = "https://img.example/p.jpg?w=1280"
        d = copy.deepcopy(self.doc)
        d["scenes"][5]["media"]["url"] = "https://img.example/p.jpg?w=640"
        self.assertNotEqual(_hashes(c, self.ranges), _hashes(d, self.ranges))      # a real query is the file

    def test_a_local_file_counts_by_its_bytes(self):
        d1, d2 = tempfile.mkdtemp(), tempfile.mkdtemp()
        for folder, data in ((d1, b"same picture"), (d2, b"same picture")):
            with open(os.path.join(folder, "still.jpg"), "wb") as fh:
                fh.write(data)
        a, b = copy.deepcopy(self.doc), copy.deepcopy(self.doc)
        a["scenes"][3]["media"] = {"type": "image", "url": os.path.join(d1, "still.jpg")}
        b["scenes"][3]["media"] = {"type": "image", "url": os.path.join(d2, "still.jpg")}
        self.assertEqual(_hashes(a, self.ranges), _hashes(b, self.ranges))
        with open(os.path.join(d2, "still.jpg"), "wb") as fh:
            fh.write(b"another picture!")
        rendercache.FILES.seen.clear()
        self.assertNotEqual(_hashes(a, self.ranges)[0], _hashes(b, self.ranges)[0])

    def test_what_the_renderer_never_reads_does_not_count(self):
        def notes(d):
            s = d["scenes"][9]
            s["semanticMetadata"] = {"intent": "x", "searchQuery": "y", "alternatives": [{"url": "z"}]}
            s.update(query="q", reviewReason="r", reviewRequired=True, visualType="v", visualTreatment="t",
                     words=[{"text": "hi", "start": 1, "end": 2}])
            s["media"].update(attribution="a", license="l", qualityScore=0.4, relevanceScore=0.2,
                              previewUrl="https://pub.example/p.mp4", storage={"path": "x"}, sourceStart=3)
        self.assertEqual(self.edit(notes), [])

    def test_what_the_renderer_reads_counts(self):
        at = _chunk_of(self.ranges, 9 * 150)
        for change in ({"motion": "zoom-out"}, {"effect": "dust"}, {"treatment": "vintage"}, {"frame": "inset"},
                       {"text": "a new line"}, {"durationInFrames": 151}):
            self.assertIn(at, self.edit(lambda d, c=change: d["scenes"][9].update(c)), change)
        for change in ({"tone": {"l": 0.3}}, {"fallbackStill": "https://pub.example/f.jpg"},
                       {"living": {"layers": [{"url": "https://pub.example/l.png"}]}}, {"fit": "contain"}):
            self.assertIn(at, self.edit(lambda d, c=change: d["scenes"][9]["media"].update(c)), change)
        self.assertIn(at, self.edit(lambda d: d["scenes"][9].update(
            semanticMetadata={"subject": "Hoover Dam"})))                   # image looks compare subjects

    def test_the_next_scenes_transition_counts_for_the_scene_before_it(self):
        # Scene 8 ends at frame 1349, chunk 2 (1200-1799): a cut transition into scene 9 is drawn over its end.
        changed = self.edit(lambda d: d["scenes"][9].update(transition="flash"))
        self.assertEqual(changed, [_chunk_of(self.ranges, 1349)])
        # Across a chunk boundary: scene 4 starts chunk 1 (600); its crossfade draws over scene 3 too.
        doc = _doc([150] * 40)
        doc["scenes"][4]["transition"] = "crossfade"
        ranges = _ranges(doc)
        self.assertNotIn(600, [a for a, _ in ranges])                      # never a cut inside a crossfade

    def test_a_pack_transition_counts_where_its_clip_plays(self):
        meta = {"mlt5": {"fps": 30, "peakFrame": 12, "frames": 32, "peak": 0.4, "duration": 1.07}}
        with mock.patch.dict(rendercache._PACK_META, meta, clear=True):
            base = _hashes(self.doc, self.ranges)
            d = copy.deepcopy(self.doc)
            d["scenes"][12]["transition"] = "pack:mlt5"                     # cut at 1800: chunk 3 starts there
            new = _hashes(d, _ranges(d))
        changed = _changed(base, new)
        self.assertIn(_chunk_of(self.ranges, 1790), changed)               # the clip starts 12 frames before

    def test_an_animation_counts_the_shot_behind_it(self):
        doc = copy.deepcopy(self.doc)
        doc["scenes"][13]["media"] = {"type": "animation", "url": ""}
        doc["scenes"][13]["animation"] = {"template": "stat"}
        ranges = _ranges(doc)
        base = _hashes(doc, ranges)
        d = copy.deepcopy(doc)
        d["scenes"][12]["media"]["thumbnail"] = "https://pub.example/thumbs/new.jpg"   # its nearest real shot
        changed = _changed(base, _hashes(d, ranges))
        self.assertIn(_chunk_of(ranges, 13 * 150), changed)

    def test_an_overlay_counts_for_the_frames_near_it(self):
        ov = {"type": "stat", "template": "", "startFrame": 1805, "durationInFrames": 90}
        doc = copy.deepcopy(self.doc)
        doc["overlays"] = [ov]
        ranges = _ranges(doc)
        base = _hashes(doc, ranges)
        d = copy.deepcopy(doc)
        d["overlays"][0]["text"] = "40%"
        changed = _changed(base, _hashes(d, ranges))
        # A full-screen graphic moves the clip under it a few frames before itself: the chunk before counts too.
        self.assertEqual(changed, sorted({_chunk_of(ranges, 1795), _chunk_of(ranges, 1805)}))

    def test_what_an_overlay_reads_of_the_scene_it_starts_on(self):
        doc = copy.deepcopy(self.doc)
        doc["overlays"] = [{"type": "stat", "startFrame": 1210, "durationInFrames": 90}]
        ranges = _ranges(doc)
        base = _hashes(doc, ranges)
        d = copy.deepcopy(doc)
        d["scenes"][8]["media"]["focus"] = {"logos": [{"x": 0.8, "y": 0.05, "w": 0.1, "h": 0.1}]}
        self.assertEqual(_changed(base, _hashes(d, ranges)), [_chunk_of(ranges, 1210)])

    def test_an_image_look_counts_only_the_pictures_it_shows(self):
        doc = copy.deepcopy(self.doc)
        for i, s in enumerate(doc["scenes"]):
            s["semanticMetadata"] = {"subject": "Lake Mead" if i % 2 else f"thing {i}"}
        # A photo card with no picture of its own borrows the scene under it (scene 30 at 4500).
        doc["overlays"] = [{"type": "photo-card", "startFrame": 4520, "durationInFrames": 90}]
        ranges = _ranges(doc)
        base = _hashes(doc, ranges)
        d = copy.deepcopy(doc)
        d["scenes"][30]["media"]["thumbnail"] = "https://pub.example/thumbs/new30.jpg"
        self.assertIn(_chunk_of(ranges, 4520), _changed(base, _hashes(d, ranges)))
        # With a picture of its own it borrows nothing: the scene under it changing its clip is not seen.
        doc["overlays"][0]["media"] = [{"type": "image", "url": "https://pub.example/own.jpg"}]
        base = _hashes(doc, ranges)
        d = copy.deepcopy(doc)
        d["scenes"][30]["media"]["thumbnail"] = "https://pub.example/thumbs/new30.jpg"
        self.assertNotIn(_chunk_of(ranges, 4520), _changed(base, _hashes(d, ranges)) if 30 * 150 not in
                         range(*ranges[_chunk_of(ranges, 4520)]) else [])

    def test_subtitles_tie_every_chunk_to_the_whole_narration(self):
        doc = copy.deepcopy(self.doc)
        doc["captions"] = {"enabled": True, "style": "netflix"}
        for i, s in enumerate(doc["scenes"]):
            s["words"] = [{"text": f"w{i}", "start": i * 5 + 0.1, "end": i * 5 + 0.5}]
        ranges = _ranges(doc)
        base = _hashes(doc, ranges)
        d = copy.deepcopy(doc)
        d["scenes"][39]["words"][0]["text"] = "changed"
        self.assertEqual(_changed(base, _hashes(d, ranges)), list(range(len(ranges))))
        # Off, the words draw nothing.
        self.assertEqual(self.edit(lambda d: d["scenes"][39].update(words=[{"text": "x", "start": 1, "end": 2}])),
                         [])

    def test_the_grade_counts_everywhere_and_its_frozen_median_keeps_a_new_tone_local(self):
        doc = copy.deepcopy(self.doc)
        doc["grade"] = {"preset": "documentary", "strength": 1, "medians": {"l": 0.4, "s": 0.1, "rg": 1, "bg": 1}}
        ranges = _ranges(doc)
        base = _hashes(doc, ranges)
        d = copy.deepcopy(doc)
        d["scenes"][9]["media"]["tone"] = {"l": 0.2, "s": 0.3, "rg": 1, "bg": 1}
        self.assertEqual(_changed(base, _hashes(d, ranges)), [_chunk_of(ranges, 9 * 150)])
        d = copy.deepcopy(doc)
        d["grade"]["strength"] = 0.5
        self.assertEqual(_changed(base, _hashes(d, ranges)), list(range(len(ranges))))
        # No frozen median: the renderer takes it from every scene's tone - every chunk depends on each.
        doc["grade"].pop("medians")
        base = _hashes(doc, ranges)
        d = copy.deepcopy(doc)
        d["scenes"][9]["media"]["tone"] = {"l": 0.2, "s": 0.3, "rg": 1, "bg": 1}
        self.assertEqual(_changed(base, _hashes(d, ranges)), list(range(len(ranges))))

    def test_the_renderer_and_every_encoder_setting_count(self):
        for change in ({"renderer": "fp2"}, {"crf": 20}, {"x264": "faster"}, {"jpeg": 92}, {"gl": "angle"}):
            self.assertEqual(_changed(self.base, _hashes(self.doc, self.ranges, {**ENC, **change})),
                             list(range(len(self.ranges))), change)
        with mock.patch.object(render, "renderer_fingerprint", return_value="fpX"), \
                mock.patch.object(config, "RENDER_JPEG_QUALITY", 92):
            enc = render.encoder_settings()
        self.assertEqual((enc["renderer"], enc["jpeg"], enc["crf"]), ("fpX", 92, config.RENDER_CRF))

    def test_the_length_counts_only_near_the_end(self):
        d = copy.deepcopy(self.doc)
        d["scenes"][-1]["durationInFrames"] += 30
        d["durationInFrames"] += 30
        changed = _changed(self.base, _hashes(d, _ranges(d)))
        self.assertEqual(changed, [len(self.ranges) - 1])

    def test_the_brand_watermark_counts_everywhere_its_intro_and_outro_only_there(self):
        doc = copy.deepcopy(self.doc)
        doc["brand"] = {"watermark": {"url": "https://pub.example/logo.png"},
                        "outro": {"kind": "card", "logo": "https://pub.example/logo.png"}}
        with mock.patch.object(fanout.brandkit, "layout", return_value=(0, 6000, 150, 6150)), \
                mock.patch.object(rendercache.brandkit, "layout", return_value=(0, 6000, 150, 6150)):
            ranges = _ranges(doc)
            base = _hashes(doc, ranges)
            d = copy.deepcopy(doc)
            d["brand"]["watermark"]["url"] = "https://pub.example/logo2.png"
            self.assertEqual(_changed(base, _hashes(d, ranges)), list(range(len(ranges))))
            d = copy.deepcopy(doc)
            d["brand"]["outro"]["title"] = "Subscribe"
            self.assertEqual(_changed(base, _hashes(d, ranges)), [len(ranges) - 1])
            d = copy.deepcopy(doc)
            d["scenes"][-1]["media"]["thumbnail"] = "https://pub.example/thumbs/last2.jpg"   # the end card's still
            self.assertIn(len(ranges) - 1, _changed(base, _hashes(d, ranges)))


class AudioHash(unittest.TestCase):
    def setUp(self):
        self.doc = _doc([150] * 20, sfx=[{"name": "whoosh", "startFrame": 300}])
        self.doc["overlays"] = [{"type": "stat", "template": "", "startFrame": 900, "durationInFrames": 60,
                                 "text": "40%"}]
        with mock.patch.object(render, "renderer_fingerprint", return_value="fp1"):
            self.base = rendercache.audio_hash(self.doc)

    def changes(self, fn):
        d = copy.deepcopy(self.doc)
        fn(d)
        with mock.patch.object(render, "renderer_fingerprint", return_value="fp1"):
            return rendercache.audio_hash(d) != self.base

    def test_what_is_heard_counts(self):
        self.assertTrue(self.changes(lambda d: d["bgm"].update(volume=0.5)))
        self.assertTrue(self.changes(lambda d: d["audio"].update(url="https://sb.example/narration2.mp3")))
        self.assertTrue(self.changes(lambda d: d["sfx"].append({"name": "ding", "startFrame": 600})))
        self.assertTrue(self.changes(lambda d: d["overlays"][0].update(text="41%")))   # a look's own sound
        self.assertTrue(self.changes(lambda d: d["scenes"][3].update(transition="pack:mlt5")))
        self.assertTrue(self.changes(lambda d: d["scenes"][3].update(words=[{"text": "a", "start": 1, "end": 2}])))
        self.assertTrue(self.changes(lambda d: d.update(sfxEnabled=False)))

    def test_what_is_only_seen_does_not(self):
        self.assertFalse(self.changes(lambda d: d["scenes"][3]["media"].update(url="https://pub.example/x.mp4")))
        self.assertFalse(self.changes(lambda d: d.update(grade={"preset": "warm"})))
        self.assertFalse(self.changes(lambda d: d.update(captions={"enabled": True})))
        self.assertFalse(self.changes(lambda d: d["scenes"][3].update(motion="zoom-in", effect="dust")))


# --------------------------------------------------------------------------- the lists stay true to the renderer
class TrueToTheRenderer(unittest.TestCase):
    def _sources(self):
        out = {}
        for dirpath, _dirs, files in os.walk(SRC):
            for name in files:
                if name.endswith((".ts", ".tsx")) and name != "types.ts":
                    with open(os.path.join(dirpath, name), encoding="utf-8") as fh:
                        # Comments out: a word in a sentence is not a read.
                        text = re.sub(r"/\*.*?\*/|//[^\n]*", "", fh.read(), flags=re.S)
                    out[os.path.relpath(os.path.join(dirpath, name), SRC).replace("\\", "/")] = text
        return out

    def test_the_fields_left_out_are_never_read_by_the_main_composition(self):
        sources = self._sources()
        # The Short (short/) is another composition, never a chunk of a video.
        main = {k: v for k, v in sources.items() if not k.startswith("short/")}
        for key in sorted((rendercache.SCENE_NOT_DRAWN | rendercache.MEDIA_NOT_DRAWN) - {"words"}):
            pattern = re.compile(r"(?:\.|\?\.)" + re.escape(key) + r"\b|\[\s*[\"']" + re.escape(key) + r"[\"']\s*\]")
            readers = [k for k, v in main.items() if pattern.search(v)]
            if key == "semanticMetadata":
                # Only the subject (counted: rendercache.Doc.drawn), by Main.tsx's image looks.
                self.assertEqual(readers, ["Main.tsx"], readers)
                self.assertEqual(set(re.findall(r"semanticMetadata\?\.(\w+)", main["Main.tsx"])), {"subject"})
                continue
            if key in ("attribution", "storage"):
                # A look's own words or data (overlay.attribution, a realdata storage figure), never a scene's.
                readers = [k for k in readers if not re.search(r"(?:overlay|d|ov|o)\." + key, main[k])]
            self.assertEqual(readers, [], f"the renderer reads {key}: it must count in rendercache's hash")
        # Scene words: the subtitles (counted with captions on) and the music's and beds' ducking (the sound).
        words = [k for k, v in main.items() if re.search(r"(?:\.|\?\.)words\b", v) and "sc.words" in v]
        self.assertEqual(sorted(words), ["components/ambienceMix.ts", "components/captionCues.ts",
                                         "components/musicMix.ts"])

    def test_the_constants_match_main_tsx(self):
        with open(os.path.join(SRC, "Main.tsx"), encoding="utf-8") as fh:
            main = fh.read()
        sets = {name: set(re.findall(r'"([^"]+)"', re.search(name + r"\s*=\s*new Set[^(]*\(\[(.*?)\]\)", main,
                                                               re.S).group(1)))
                for name in ("PHOTO_CARDS", "STILL_LOOKS", "PERSON_CUES", "SUBJECT_STOP")}
        self.assertEqual(sets["PHOTO_CARDS"], set(rendercache.PHOTO_CARDS))
        self.assertEqual(sets["STILL_LOOKS"], set(rendercache.STILL_LOOKS))
        self.assertEqual(sets["PERSON_CUES"], set(rendercache.PERSON_CUES))
        self.assertEqual(sets["SUBJECT_STOP"], set(rendercache._SUBJECT_STOP))
        self.assertEqual(int(re.search(r"PICTURE_NEAR\s*=\s*(\d+)", main).group(1)), rendercache.PICTURE_NEAR)
        self.assertEqual(int(re.search(r"const CROSSFADE_FRAMES\s*=\s*(\d+)", main).group(1)),
                         rendercache.CROSSFADE_FRAMES)
        self.assertIn("out.length < 6", main)
        with open(os.path.join(SRC, "components", "motion", "stage.tsx"), encoding="utf-8") as fh:
            stage = fh.read()
        pre = int(re.search(r"STAGE_PRE\s*=\s*(\d+)", stage).group(1))
        post = int(re.search(r"STAGE_POST\s*=\s*(\d+)", stage).group(1))
        self.assertGreaterEqual(rendercache.STAGE_REACH_30FPS, max(pre, post))


def _node():
    node = shutil.which("node")
    esbuild = os.path.join(REMOTION, "node_modules", "esbuild", "bin", "esbuild")
    return (node, esbuild) if node and os.path.isfile(esbuild) else (None, None)


@unittest.skipUnless(all(_node()), "needs node and remotion's esbuild")
class LookPicturesPort(unittest.TestCase):
    """rendercache.look_pictures against Main.tsx lookPictures itself (its source cut out and run under node)."""

    @classmethod
    def setUpClass(cls):
        node, esbuild = _node()
        with open(os.path.join(SRC, "Main.tsx"), encoding="utf-8") as fh:
            main = fh.read()
        start = main.index("const PHOTO_CARDS")
        end = main.index("return out.slice(0, many ? 6 : Math.max(1, own.length));")
        block = main[start:main.index("};", end) + 2]
        src = SRC.replace("\\", "/")
        harness = (f'import {{ resolveOverlay, templateFor }} from "{src}/templates";\n'
                   f'import type {{ Overlay, OverlayType, SceneMedia, TimelineProps }} from "{src}/types";\n'
                   f"{block}\n"
                   'import * as fs from "fs";\n'
                   "const input = JSON.parse(fs.readFileSync(0, 'utf-8'));\n"
                   "const out = input.overlays.map((ov: any) => { const p = lookPictures(resolveOverlay(ov), "
                   "input.scenes); return p ? p.map((m: any) => m.url) : null; });\n"
                   "process.stdout.write(JSON.stringify(out));\n")
        cls.dir = tempfile.mkdtemp()
        entry = os.path.join(cls.dir, "looks.ts")
        with open(entry, "w", encoding="utf-8") as fh:
            fh.write(harness)
        cls.bundle = os.path.join(cls.dir, "looks.cjs")
        subprocess.run([node, esbuild, entry, "--bundle", "--platform=node", "--format=cjs",
                        f"--outfile={cls.bundle}", "--log-level=error"], check=True, cwd=REMOTION, timeout=180)
        cls.node = node

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def compare(self, doc):
        run = subprocess.run([self.node, self.bundle], input=json.dumps(doc), capture_output=True, text=True,
                             encoding="utf-8", timeout=120, check=True)
        want = json.loads(run.stdout)
        d = rendercache.Doc(doc)
        n = 0
        for ov, ts in zip(doc["overlays"], want):
            tpl = rendercache.templates.get(str(ov.get("template") or "")) if ov.get("template") else None
            if tpl and tpl.get("retired"):
                continue
            self.assertEqual(rendercache.look_pictures(d, ov), ts, ov)
            n += ts is not None
        return n

    def test_a_real_timeline(self):
        with open(FIXTURE, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertGreater(self.compare(doc), 5)

    def test_every_branch(self):
        reg = rendercache.templates.all_templates()
        image_ids = [t["id"] for t in reg if not t.get("retired") and (
            "stills" in (t.get("tags") or []) or "still" in (t.get("tags") or [])
            or (t.get("defaults") or {}).get("variant") in rendercache.STILL_LOOKS
            or t.get("component") in rendercache.PHOTO_CARDS)]
        person = [t["id"] for t in reg if set(t.get("cues") or []) & rendercache.PERSON_CUES]
        other = [t["id"] for t in reg if not t.get("retired")][:20]
        rnd = random.Random(3)
        subjects = ["Lake Mead", "the Hoover Dam", "Lake Mead water level", "Barack Obama", "Obama's father", "",
                    "Glen Canyon Dam spillway", "dam"]
        scenes, f = [], 0
        for i in range(60):
            kind = rnd.choice(["video", "video", "image", "animation", "color"])
            m = {"type": kind, "url": "" if kind in ("animation", "color") else f"https://pub.example/m{i % 45}.x",
                 "source": rnd.choice(["youtube", "library", "web_image"])}
            if kind == "video" and rnd.random() < 0.8:
                m["thumbnail"] = f"https://pub.example/t{i % 40}.jpg"
            scenes.append({"id": f"s{i:03d}" if i != 7 else "s006", "startFrame": f, "durationInFrames": 120,
                           "media": m, "semanticMetadata": {"subject": rnd.choice(subjects)}})
            f += 120
        overlays = []
        for k in range(400):
            ov = {"template": rnd.choice(image_ids + person + other + ["", "NOT_A_LOOK"]),
                  "startFrame": rnd.randint(0, f + 50), "durationInFrames": 90}
            if rnd.random() < 0.3:
                ov["type"] = rnd.choice(["photo-card", "name-card", "stat"])
            if rnd.random() < 0.3:
                ov["variant"] = rnd.choice(["collage", "board", "window", "plain"])
            if rnd.random() < 0.4:
                ov["media"] = [rnd.choice([{"type": "image", "url": f"https://pub.example/o{k}.jpg",
                                            "source": rnd.choice(["web_image", "library"])},
                                           {"type": "video", "url": "https://pub.example/v.mp4",
                                            "thumbnail": "https://pub.example/t3.jpg"}, {}])
                               for _ in range(rnd.randint(0, 3))]
            if rnd.random() < 0.4:
                ov["mediaFrom"] = [rnd.choice(["s001", "s006", "s040", "nope"]) for _ in range(rnd.randint(0, 3))]
            overlays.append(ov)
        self.assertGreater(self.compare({"fps": 30, "scenes": scenes, "overlays": overlays}), 50)


# --------------------------------------------------------------------------- the store
class FakeStore:
    """R2 as the render cache sees it: objects with their bytes and their age."""

    def __init__(self):
        self.objects = {}
        self.copies, self.touched, self.puts = [], [], []
        self.lock = threading.Lock()
        self.now = time.time()

    def upload(self, path, key, **kw):
        with open(path, "rb") as fh:
            data = fh.read()
        with self.lock:
            self.objects[key] = (data, self.now)
            self.puts.append(key)
        return f"https://pub.example/{key}"

    def upload_bytes(self, data, key, **kw):
        with self.lock:
            self.objects[key] = (data, self.now)
        return f"https://pub.example/{key}"

    def copy(self, src, key, bucket="", src_bucket="", replace_metadata=False):
        with self.lock:
            if src not in self.objects:
                raise RuntimeError("no such key")
            self.objects[key] = (self.objects[src][0], self.now)
            (self.touched if src == key else self.copies).append(key)

    def list_keys(self, prefix="", bucket="", limit=10000):
        with self.lock:
            return [{"key": k, "size": len(v[0]),
                     "modified": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(v[1]))}
                    for k, v in sorted(self.objects.items()) if k.startswith(prefix)]

    def delete(self, key, bucket=""):
        with self.lock:
            return self.objects.pop(key, None) is not None

    def fetch(self, workers, url, path, key="", bucket="", tries=4):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not key:                                      # a scene's media prefetched for a chunk drawn here
            with open(path, "wb") as fh:
                fh.write(b"media")
            return path
        with self.lock:
            obj = self.objects.get(key)
        if obj is not None:
            with open(path, "wb") as fh:
                fh.write(obj[0])
            return path
        if key.endswith(".mp4") and workers is not None:
            _frames_file(path, workers.frames_for_key(key))
            with self.lock:                              # what the worker put in R2
                with open(path, "rb") as fh:
                    self.objects[key] = (fh.read(), self.now)
            return path
        if key.endswith(".wav"):
            with open(path, "wb") as fh:
                fh.write(b"RIFF" + b"\0" * 100)
            return path
        raise RuntimeError(f"R2 GET {key}: HTTP 404")


class Reuse(unittest.TestCase):
    """render_pod with the cache: a first render keeps its chunks, a re-render draws only what changed."""

    def setUp(self):
        self.store = FakeStore()

    def render(self, doc, workers=None, mode="on", helpers=True, odd=None, **env):
        work = tempfile.mkdtemp()
        calls = {"render": [], "mix": [], "finalize": [], "joined": None}
        workers = workers or FakeWorkers()

        def fake_render(d, path, frames=None, audio_to=None, cancel=None, codec=None, muted=False, **kw):
            if codec == "wav":
                calls["mix"].append(path)
                with open(path, "wb") as fh:
                    fh.write(b"RIFF" + b"M" * 2000)
                return path
            calls["render"].append((tuple(frames), bool(muted), audio_to is not None))
            _frames_file(path, frames[1] - frames[0] + 1)
            if audio_to:
                with open(audio_to, "wb") as fh:
                    fh.write(b"RIFF" + b"\0" * 100)
            return path

        def fake_join_videos(paths, out, frames):
            calls["joined"] = [os.path.basename(p) for p in paths]
            _frames_file(out, frames)
            return out

        def fake_join_wavs(parts, fps, out):
            with open(out, "wb") as fh:
                fh.write(b"RIFF" + b"S" * 2000)
            return out

        def fake_finalize(video, audio, out, **kw):
            with open(audio, "rb") as fh:
                calls["finalize"].append(fh.read(5))
            with open(out, "wb") as fh:
                fh.write(b"final")
            return {}

        def fake_flac(wav, out):
            shutil.copy(wav, out)
            return out
        env.setdefault("POD_RENDER_CHUNK_SECONDS", 20)
        patches = [mock.patch.object(config, "RENDER_CACHE", True),
                   mock.patch.object(config, "RENDER_CACHE_PREFIX", "render-cache/v1/"),
                   mock.patch.object(config, "POD_RENDER_LOCAL_CHUNKS", env.pop("LOCAL", 2)),
                   mock.patch.object(fanout, "_pod_submit", side_effect=workers.submit),
                   mock.patch.object(fanout, "_pod_status", side_effect=workers.status),
                   mock.patch.object(fanout, "_pod_cancel", side_effect=workers.cancel),
                   mock.patch.object(fanout, "_fetch", side_effect=lambda *a, **k: self.store.fetch(workers, *a, **k)),
                   mock.patch.object(fanout, "_count_frames", side_effect=_fake_count),
                   mock.patch.object(fanout, "join_videos", side_effect=fake_join_videos),
                   mock.patch.object(fanout, "join_wavs", side_effect=fake_join_wavs),
                   mock.patch.object(fanout, "_flac", side_effect=fake_flac),
                   mock.patch.object(fanout, "_delete_keys"),
                   mock.patch.object(fanout.r2, "upload", side_effect=self.store.upload),
                   mock.patch.object(fanout.r2, "upload_bytes", side_effect=self.store.upload_bytes),
                   mock.patch.object(fanout.r2, "copy", side_effect=self.store.copy),
                   mock.patch.object(fanout.r2, "list_keys", side_effect=self.store.list_keys),
                   mock.patch.object(fanout.renderer, "render", side_effect=fake_render),
                   mock.patch.object(fanout.renderer, "renderer_fingerprint", return_value="fp1"),
                   mock.patch.object(fanout.renderer, "finalize", side_effect=fake_finalize)]
        if odd is not None:
            patches.append(mock.patch.object(fanout, "stream_config", side_effect=odd))
        if not helpers:
            patches.append(mock.patch.object(fanout, "pod_render_enabled", return_value=False))
        costs.reset()
        with _pod_env(**env):
            for p in patches:
                p.start()
            try:
                ok = fanout.render_pod(doc, os.path.join(work, "final.mp4"), job_id="rp-1", work=work,
                                       report=lambda *a, **k: None, concurrency=8, cache_scope="proj-1",
                                       cache_mode=mode)
            finally:
                for p in reversed(patches):
                    p.stop()
            fanout.finish_cleanup(5)
        calls["ok"] = ok
        calls["stats"] = dict(fanout.media.LAST_STATS.get("pod_render") or {})
        calls["manifest"] = fanout.media.LAST_STATS.get("render_manifest")
        calls["payloads"] = [p["input"] for p in workers.payloads]
        calls["costs"] = costs.summary()
        return calls

    def chunk_keys(self):
        return sorted(k for k in self.store.objects if re.search(r"/c-[0-9a-f]{20}\.mp4$", k))

    def test_a_first_render_keeps_every_chunk_and_the_whole_mix(self):
        doc = _doc([150] * 16)                                     # 2400 frames: four 600-frame chunks
        first = self.render(doc)
        self.assertTrue(first["ok"])
        self.assertEqual(first["stats"]["fromCache"], 0)
        self.assertEqual(len(first["payloads"]), 3)                # spread as before: three on workers
        self.assertTrue(all(not p.get("picture_only") for p in first["payloads"]))
        self.assertEqual(len(self.chunk_keys()), 4)
        self.assertEqual(len(self.store.copies), 3)                # the workers' chunks copied inside R2
        self.assertTrue(any(k.endswith(".flac") for k in self.store.objects))
        self.assertTrue(all(k.startswith("render-cache/v1/proj-1/") for k in self.chunk_keys()))
        self.assertEqual(first["finalize"], [b"RIFFS"])            # the sound slices, joined
        m = first["manifest"]
        self.assertEqual([c["source"] for c in m["chunks"]], ["pod", "worker", "worker", "worker"])
        self.assertEqual(len(m["sig"]["scenes"]), 16)
        self.assertEqual(first["costs"]["render"]["reused"], 0)

    def test_one_swapped_clip_draws_one_chunk_here_and_reuses_the_rest_and_the_mix(self):
        doc = _doc([150] * 16)
        self.render(doc)
        d = copy.deepcopy(doc)
        d["scenes"][9]["media"]["url"] = "https://pub.example/media/new.mp4"     # frame 1350: chunk 2
        again = self.render(d)
        self.assertTrue(again["ok"])
        self.assertEqual(again["payloads"], [])                    # no worker woken for one chunk
        self.assertEqual(again["render"], [((1200, 1799), True, False)])  # drawn here, picture only
        self.assertEqual(again["mix"], [])                         # nothing audible changed: the kept mix
        self.assertEqual(again["finalize"], [b"RIFFS"])
        self.assertEqual(again["joined"], ["cchunk_000.mp4", "cchunk_001.mp4", "pchunk_002.pod.mp4",
                                           "cchunk_003.mp4"])
        self.assertEqual(again["stats"]["fromCache"], 3)
        c = again["stats"]["cache"]
        self.assertEqual((c["reused"], c["framesReused"], c["framesDrawn"], c["mixReused"]), (3, 1800, 600, True))
        self.assertGreater(c["savedUsd"], 0)
        self.assertEqual(again["costs"]["render"]["reused"], 3)
        self.assertEqual([x["source"] for x in again["manifest"]["chunks"]], ["cache", "cache", "pod", "cache"])
        self.assertEqual(len(self.chunk_keys()), 5)                 # the new chunk kept beside the old
        self.assertEqual(len(self.store.touched), 4)                # three chunks and the mix start their age again

    def test_a_change_that_is_only_heard_reuses_every_picture_and_draws_the_mix_whole(self):
        doc = _doc([150] * 16)
        self.render(doc)
        d = copy.deepcopy(doc)
        d["bgm"]["volume"] = 0.08
        again = self.render(d)
        self.assertTrue(again["ok"])
        self.assertEqual(again["render"], [])
        self.assertEqual(len(again["mix"]), 1)                     # the whole mix, drawn from the timeline
        self.assertEqual(again["finalize"], [b"RIFFM"])            # and the loudness set from it
        self.assertEqual(again["stats"]["fromCache"], 4)
        self.assertFalse(again["stats"]["cache"]["mixReused"])

    def test_narration_that_moves_after_t_redraws_after_t_and_reuses_before(self):
        doc = _doc([150] * 32)                                     # 4800 frames: eight chunks
        self.render(doc)
        d, t = _shift_after(doc, 22, 40)                           # scene 21 longer: everything after 3300 moves
        again = self.render(d)
        self.assertTrue(again["ok"])
        sources = [c["source"] for c in again["manifest"]["chunks"]]
        frames = [tuple(c["frames"]) for c in again["manifest"]["chunks"]]
        for (a, b), src in zip(frames, sources):
            if b < t - 1:
                self.assertEqual(src, "cache", (a, b))
        self.assertTrue(all(s != "cache" for (a, b), s in zip(frames, sources) if b >= t))
        self.assertEqual(len(again["mix"]), 1)                     # the narration moved: the mix is drawn again

    def test_many_changed_chunks_go_to_the_workers_without_their_sound(self):
        doc = _doc([150] * 32)
        self.render(doc)
        d = copy.deepcopy(doc)
        for i in (1, 9, 17, 25):                                   # four chunks
            d["scenes"][i]["media"]["url"] = f"https://pub.example/media/new{i}.mp4"
        again = self.render(d)
        self.assertTrue(again["ok"])
        self.assertEqual(len(again["payloads"]), 3)                # the pod draws one, three go to workers
        self.assertTrue(all(p["picture_only"] for p in again["payloads"]))
        self.assertEqual(again["stats"]["fromCache"], 4)

    def test_off_and_refresh(self):
        doc = _doc([150] * 16)
        self.render(doc)
        off = self.render(doc, mode="off")
        self.assertEqual(off["stats"].get("fromCache"), 0)
        self.assertNotIn("cache", off["stats"])
        refresh = self.render(doc, mode="refresh")
        self.assertEqual(refresh["stats"]["fromCache"], 0)
        self.assertEqual(refresh["stats"]["cache"]["mode"], "refresh")
        again = self.render(doc)
        self.assertEqual(again["stats"]["fromCache"], 4)
        self.assertEqual(again["render"], [])

    def test_without_workers_a_re_render_still_reuses(self):
        doc = _doc([150] * 16)
        self.render(doc)
        d = copy.deepcopy(doc)
        d["scenes"][1]["media"]["url"] = "https://pub.example/media/new.mp4"
        again = self.render(d, helpers=False)
        self.assertTrue(again["ok"])
        self.assertEqual(again["render"], [((0, 599), True, False)])
        # Nothing cached and no workers: the whole video on one machine, as before (unless RENDER_LOCAL_CHUNKED).
        self.store.objects.clear()
        self.assertFalse(self.render(d, helpers=False)["ok"])
        with mock.patch.object(config, "RENDER_LOCAL_CHUNKED", True):
            local = self.render(d, helpers=False)
        self.assertTrue(local["ok"])
        self.assertEqual(len(local["render"]), 4)
        self.assertEqual(local["payloads"], [])

    def test_an_unusable_kept_chunk_is_drawn_again(self):
        doc = _doc([150] * 16)
        self.render(doc)
        key = self.chunk_keys()[0]
        self.store.objects[key] = (b"FRAMES=12\n", self.store.now)    # truncated
        again = self.render(doc)
        self.assertTrue(again["ok"])
        self.assertEqual(again["stats"]["fromCache"], 3)
        self.assertEqual(len(again["render"]), 1)

    def test_a_kept_chunk_encoded_differently_is_drawn_again_before_the_join(self):
        doc = _doc([150] * 16)
        self.render(doc)
        d = copy.deepcopy(doc)
        d["scenes"][9]["media"]["url"] = "https://pub.example/media/new.mp4"
        again = self.render(d, odd=lambda path: b"B" if os.path.basename(path) == "cchunk_000.mp4" else b"A")
        self.assertTrue(again["ok"])
        drawn = sorted(f for f, _m, _a in again["render"])
        self.assertEqual(drawn, [(0, 599), (1200, 1799)])
        self.assertEqual(again["joined"][0], "pchunk_000.pod.mp4")

    def test_a_cache_that_cannot_be_read_never_costs_the_render(self):
        doc = _doc([150] * 16)
        with mock.patch.object(self.store, "list_keys", side_effect=RuntimeError("R2 down")):
            out = self.render(doc)
        self.assertTrue(out["ok"])
        self.assertEqual(out["stats"]["fromCache"], 0)


class Store(unittest.TestCase):
    def test_cleanup_deletes_only_old_cache_entries(self):
        store = FakeStore()
        now = time.time()
        store.objects = {"render-cache/v1/p1/c-a.mp4": (b"x", now - 30 * 86400),
                         "render-cache/v1/p1/c-b.mp4": (b"xy", now - 86400),
                         "render-cache/v1/p2/a-c.flac": (b"xyz", now - 20 * 86400),
                         "projects/p1/final-1.mp4": (b"video", now - 90 * 86400)}
        with mock.patch.object(r2, "list_keys", side_effect=store.list_keys), \
                mock.patch.object(r2, "delete", side_effect=store.delete), \
                mock.patch.object(config, "RENDER_CACHE_PREFIX", "render-cache/v1/"):
            dry = rendercache.cleanup(days=14, now=now)
            self.assertEqual((dry["old"], dry["deleted"], dry["bytes"]), (2, 0, 4))
            self.assertEqual(len(store.objects), 4)
            one = rendercache.cleanup(days=14, scope="p1", dry_run=False, now=now)
            self.assertEqual(one["deleted"], 1)
            done = rendercache.cleanup(days=14, dry_run=False, now=now)
            self.assertEqual(done["deleted"], 1)
        self.assertEqual(sorted(store.objects), ["projects/p1/final-1.mp4", "render-cache/v1/p1/c-b.mp4"])
        with mock.patch.object(config, "RENDER_CACHE_PREFIX", "projects/"):
            with self.assertRaises(ValueError):
                rendercache.cleanup(days=1)

    def test_the_handler_cleans_up_on_request_and_dry_by_default(self):
        with mock.patch.object(handler.rendercache, "cleanup", return_value={"old": 3, "deleted": 0}) as clean:
            out = handler.handler({"id": "j1", "input": {"action": "render_cache_cleanup", "days": 7}})
        self.assertTrue(out["ok"])
        self.assertEqual(clean.call_args.kwargs, {"days": 7, "scope": "", "dry_run": True})

    def test_r2_copy_signs_the_copy_source(self):
        resp = mock.Mock(status_code=200, content=b"<CopyObjectResult/>", text="")
        with mock.patch.object(config, "R2_ACCOUNT_ID", "acct"), mock.patch.object(config, "R2_ACCESS_KEY_ID", "k"), \
                mock.patch.object(config, "R2_SECRET_ACCESS_KEY", "s"), mock.patch.object(config, "R2_BUCKET", "b"), \
                mock.patch.object(r2.requests, "put", return_value=resp) as put:
            r2.copy("chunks/x/001.mp4", "render-cache/v1/p/c-1.mp4")
            headers = put.call_args.kwargs["headers"]
            self.assertEqual(headers["x-amz-copy-source"], "/b/chunks/x/001.mp4")
            self.assertIn("x-amz-copy-source", headers["Authorization"])
            r2.copy("k1", "k1", replace_metadata=True)
            self.assertEqual(put.call_args.kwargs["headers"]["x-amz-metadata-directive"], "REPLACE")
        bad = mock.Mock(status_code=200, content=b"<Error><Code>NoSuchKey</Code></Error>", text="<Error>")
        with mock.patch.object(r2.requests, "put", return_value=bad):
            with self.assertRaises(RuntimeError):
                r2.copy("a", "b")

    @unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
    def test_the_stream_check_reads_the_decoder_configuration(self):
        d = tempfile.mkdtemp()

        def clip(name, size, crf):
            path = os.path.join(d, name)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=30",
                            "-frames:v", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
                            "-pix_fmt", "yuv420p", path], check=True, timeout=60)
            return path
        a, b = clip("a.mp4", "320x180", 18), clip("b.mp4", "320x180", 18)
        c = clip("c.mp4", "640x360", 18)
        self.assertTrue(fanout.stream_config(a))
        self.assertEqual(fanout.stream_config(a), fanout.stream_config(b))
        self.assertNotEqual(fanout.stream_config(a), fanout.stream_config(c))
        with open(os.path.join(d, "x.mp4"), "wb") as fh:
            fh.write(b"FRAMES=3\n")
        self.assertIsNone(fanout.stream_config(os.path.join(d, "x.mp4")))


class WorkerChunks(unittest.TestCase):
    def _run(self, **kw):
        inp = {"action": "render_chunk", "upload": "r2", "chunk": 2, "frames": [600, 899],
               "prefix": "chunks/pod-abc-1234567890/", "renderer": "fp1", "timeline_key": "chunks/x/timeline.json",
               "timeline_url": "https://pub.example/timeline.json", "crf": 18, "x264": "veryfast",
               "deadline_at": time.time() + 600}
        inp.update(kw)
        seen = {"uploads": [], "renders": []}

        def fake_render(doc, path, frames=None, audio_to=None, muted=False, **k):
            seen["renders"].append((frames, audio_to, muted, config.RENDER_JPEG_QUALITY))
            _frames_file(path, frames[1] - frames[0] + 1)
            if audio_to:
                with open(audio_to, "wb") as fh:
                    fh.write(b"RIFF")
            return path
        with mock.patch.object(fanout.r2, "enabled", return_value=True), \
                mock.patch.object(config, "POD_RENDER_PREFIX", "chunks/"), \
                mock.patch.object(fanout.renderer, "renderer_fingerprint", return_value="fp1"), \
                mock.patch.object(fanout, "_load_timeline", return_value=_doc([300] * 4)), \
                mock.patch.object(fanout, "_localize", return_value={"files": 3}), \
                mock.patch.object(fanout, "_count_frames", side_effect=_fake_count), \
                mock.patch.object(fanout.renderer, "render", side_effect=fake_render), \
                mock.patch.object(fanout.r2, "upload",
                                  side_effect=lambda p, k, **x: seen["uploads"].append(k) or f"https://pub/{k}"):
            out = fanout.run_pod_chunk(inp, tempfile.mkdtemp())
        return out, seen

    def test_a_picture_only_chunk_draws_and_hands_over_no_sound(self):
        out, seen = self._run(picture_only=True)
        self.assertTrue(out["ok"], out)
        self.assertEqual(seen["renders"][0][1:3], (None, True))
        self.assertEqual(len(seen["uploads"]), 1)
        self.assertNotIn("audio_key", out)
        self.assertIn("fps", out)

    def test_the_jpeg_quality_travels_and_an_older_worker_refuses_it(self):
        out, seen = self._run(jpeg=92, renderer=fanout.renderer_id_for("fp1", 92))
        self.assertTrue(out["ok"], out)
        self.assertEqual(seen["renders"][0][3], 92)
        self.assertEqual(config.RENDER_JPEG_QUALITY, 0)            # the worker's own setting back
        # A worker that does not know the setting compares the plain fingerprint: it refuses.
        self.assertNotEqual(fanout.renderer_id_for("fp1", 92), "fp1")
        self.assertEqual(fanout.renderer_id_for("fp1", 0), "fp1")


class Wiring(unittest.TestCase):
    def test_a_render_passes_its_project_as_the_cache_scope(self):
        doc = _doc([150] * 40)
        seen = {}

        def fake_pod(d, out, **kw):
            seen.update(kw)
            with open(out, "wb") as fh:
                fh.write(b"final")
            return True
        with mock.patch.object(config, "RENDER_CACHE", True), \
                mock.patch.object(handler.fanout, "pod_render_enabled", return_value=False), \
                mock.patch.object(handler.fanout, "render_pod", side_effect=fake_pod), \
                mock.patch.object(handler, "_sanitize_stills", return_value=0):
            handler._draw(doc, {"project_id": "p9", "render_cache": "refresh"}, tempfile.mkdtemp(),
                          lambda *a, **k: None, False, os.path.join(tempfile.mkdtemp(), "final.mp4"))
        self.assertEqual((seen["cache_scope"], seen["cache_mode"]), ("p9", "refresh"))
        self.assertEqual(rendercache.mode_of("nonsense"), "on")


if __name__ == "__main__":
    unittest.main()
