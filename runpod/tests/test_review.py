"""
The AI review (src/review.py): after the render a vision model watches the
finished video scene by scene, fixes what it safely can through the quality
gate's one second render, and lists the rest.

Offline: the vision model is a fake that answers from the narration lines it
is shown, ffmpeg is stubbed wherever a test does not need it (the frame grab,
the sound measurement) and run for real only in the tests marked so, the
renderer is a fake that writes prepared files. Nothing here talks to a model
or to storage.
"""
import base64
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import handler  # noqa: E402
from src import config, costs, events, gapfill, quality, render, review  # noqa: E402

FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
MEDIA = ""


def _ff(*args) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, capture_output=True)


def _clip(name: str, seconds: float, size: str = "160x90") -> str:
    path = os.path.join(MEDIA, name)
    if not os.path.isfile(path):
        if FFMPEG:
            _ff("-f", "lavfi", "-i", f"testsrc2=s={size}:r=30:d={seconds}", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", path)
        else:
            with open(path, "wb") as fh:
                fh.write(b"\x00\x00\x00\x18ftypisom" + bytes(9000))
    return path


def _video(name: str, parts, audio: str = "sine", size: str = "320x180") -> str:
    """A finished-video stand-in: ("moving" | "black", seconds) segments with sound or silence."""
    path = os.path.join(MEDIA, name)
    if os.path.isfile(path):
        return path
    args, labels = [], []
    for k, (kind, sec) in enumerate(parts):
        src = (f"color=c=black:s={size}:r=30:d={sec}" if kind == "black"
               else f"smptebars=s={size}:r=30:d={sec}" if kind == "bars" else f"testsrc2=s={size}:r=30:d={sec}")
        args += ["-f", "lavfi", "-i", src]
        labels.append(f"[{k}:v]")
    total = sum(sec for _k, sec in parts)
    sound = f"sine=f=300:d={total}" if audio == "sine" else f"anullsrc=r=48000:cl=stereo:d={total}"
    args += ["-f", "lavfi", "-i", sound]
    graph = "".join(labels) + f"concat=n={len(parts)}:v=1:a=0[v]"
    _ff(*args, "-filter_complex", graph, "-map", "[v]", "-map", f"{len(parts)}:a", "-c:v", "libx264", "-preset",
        "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path)
    return path


def _jpg(name: str, seed: int = 1, size=(64, 36), flat: bool = False) -> str:
    """A small frame of seeded noise (two seeds never hash alike); `flat` = one colour, which hashes to nothing."""
    import random
    from PIL import Image
    path = os.path.join(MEDIA, name)
    if not os.path.isfile(path):
        im = Image.new("RGB", size, (20, 20, 20))
        if not flat:
            rnd = random.Random(seed)
            px = im.load()
            for x in range(size[0]):
                for y in range(size[1]):
                    px[x, y] = (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
        im.save(path, "JPEG", quality=95)
    return path


def setUpModule():
    global MEDIA
    MEDIA = tempfile.mkdtemp(prefix="review_media_")
    events.start_job("review-test", "")


def tearDownModule():
    shutil.rmtree(MEDIA, ignore_errors=True)


def scene(i: int, media: dict, seconds: float = 3.0, fps: int = 30, text: str = "", **extra) -> dict:
    start = int(i * seconds * fps)
    words = [{"text": "w", "start": start / fps + 0.1, "end": start / fps + seconds - 0.4}]
    s = {"id": f"s{i:04d}", "startFrame": start, "durationInFrames": int(seconds * fps),
         "text": text or f"Lake Mead dropped again in line {i}", "transition": "none", "motion": "none",
         "media": media, "words": words,
         "semanticMetadata": {"subject": "Lake Mead", "subjectType": "place", "intent": "the lake", "alternatives": []}}
    s.update(extra)
    return s


def video(url: str, clip: float = None, asset: str = "") -> dict:
    m = {"type": "video", "url": url, "source": "youtube"}
    if clip:
        m["clipSeconds"] = clip
    return m


def doc_of(scenes, fps: int = 30, narration: str = "") -> dict:
    total = sum(int(s["durationInFrames"]) for s in scenes)
    return {"fps": fps, "width": 640, "height": 360, "durationInFrames": total,
            "audio": {"url": narration or _narration(), "volume": 1}, "bgm": None,
            "captions": {"enabled": True, "position": "bottom", "accent": "#d6a83c", "fontFamily": "Inter"},
            "scenes": scenes, "overlays": [], "meta": {"warnings": []}}


def _narration() -> str:
    path = os.path.join(MEDIA, "vo.wav")
    if not os.path.isfile(path):
        if FFMPEG:
            _ff("-f", "lavfi", "-i", "sine=f=200:d=1", path)
        else:
            with open(path, "wb") as fh:
                fh.write(b"RIFF" + bytes(2000))
    return path


def alternative(path: str, score: float = 0.9, ident: str = "yt:altvideo1", page: str = "", published: bool = True,
                quality_score: float = 0.8) -> dict:
    alt = {"assetId": ident, "url": page or f"https://www.youtube.com/watch?v={ident[3:]}", "title": "another clip",
           "score": score, "quality": quality_score, "finalScore": score, "specificity": "", "moment": {"start": 12.0},
           "description": "the lake from the air", "source": "youtube"}
    if published:
        alt["media"] = {"type": "video", "url": path, "thumbnail": ""}
    else:
        alt["localPath"] = path
    return alt


def fake_vision(bad: dict = None, prose: bool = False, delay: float = 0.0):
    """
    A stand-in for the model: every scene fits (match 0.9) except the lines in
    `bad` {line text: {"match", "issues", "face", "covering", "note"}}; `prose`
    answers in words, not JSON. Records every call's messages.
    """
    calls = []

    def ask(messages, max_tokens, accept=None):
        calls.append(messages)
        if delay:
            time.sleep(delay)
        if prose:
            return "I looked at the frames and they all seem fine to me.", "fake"
        rows = []
        k = 0
        for part in messages[1]["content"]:
            if part.get("type") == "text" and part["text"].startswith("SCENE "):
                k += 1
                line = part["text"].split("NARRATION: ", 1)[1].split("\n", 1)[0]
                v = next((b for key, b in (bad or {}).items() if key in line), None)
                rows.append({"scene": k, "match": v.get("match", 0.2) if v else 0.9,
                             "issues": (v or {}).get("issues", []), "face": (v or {}).get("face", ""),
                             "covering": (v or {}).get("covering", ""), "note": (v or {}).get("note", "")})
        return json.dumps({"scenes": rows}), "fake/model"
    ask.calls = calls
    return ask


def _frames_from(jpg: str = "", asked: list = None, delay: float = 0.0):
    """A frame grab that needs no ffmpeg: `jpg` for every frame, else a different noise frame per frame number.
    `asked` collects the frame numbers asked for; `delay` makes the grab slow."""
    def grab(path, numbers, folder, width=512, timeout=None, **kw):
        if asked is not None:
            asked.append(sorted(int(n) for n in numbers))
        if delay:
            time.sleep(delay)
        return {int(n): jpg or _jpg(f"frame_{int(n)}.jpg", seed=1000 + int(n)) for n in numbers}
    return grab


class _Review:
    """The review's own settings for a test: on, quick, no sound, stubs for ffmpeg and the model."""

    def __init__(self, ask=None, pics=None, **flags):
        self.ask = ask or fake_vision()
        self.pics = pics or _frames_from()
        self.flags = {"AI_REVIEW": True, "AI_REVIEW_FIX": True, "AI_REVIEW_AUDIO": False, "AI_REVIEW_PARALLEL": 2,
                      "AI_REVIEW_SECONDS": 30, "QUALITY_HTTP_TIMEOUT": 2, "QUALITY_AUDIT_SECONDS": 60,
                      "ANIMATION_FILL": False, "QUALITY_REPAIR_GENERATED": False}
        self.flags.update(flags)
        self.patches = []

    def __enter__(self):
        self.patches = [
            mock.patch.multiple(config, **self.flags),
            mock.patch.object(review, "_ask", side_effect=self.ask),
            mock.patch.object(review, "_vision_on", return_value=True),
            mock.patch.object(review, "grab_frames", side_effect=self.pics),
            mock.patch.object(review, "probe", return_value={"fps": 30.0, "duration": 9.0, "audio": False}),
            mock.patch.object(review, "clip_seconds", return_value=4.0),
            mock.patch.object(review, "still_ok", return_value=True),
        ]
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()
        quality.reset()
        gapfill.reset()
        return False


class FakeGate:
    """What the review asks of the quality gate, without a render."""

    def __init__(self, ladder: dict = None, join: bool = True):
        self.repairs = []
        self.rerendered = False
        self.ladder = ladder or {}
        self.join = join
        self.asked = []
        self.seconds = []

    def another_shot(self, problems, seconds=None):
        self.asked.append(dict(problems))
        self.seconds.append(seconds)
        return {i: how for i, how in self.ladder.items() if i in problems}

    def join_second_render(self, scenes, why):
        self.rerendered = self.join
        return self.join


# --------------------------------------------------------------------------- #
# Grouping, the call order, the model's answer
# --------------------------------------------------------------------------- #

class Grouping(unittest.TestCase):
    def test_groups_are_four_to_six_and_evened_out(self):
        self.assertEqual([len(g) for g in review.groups_of(list(range(11)), 5)], [4, 4, 3])
        self.assertEqual([len(g) for g in review.groups_of(list(range(13)), 5)], [5, 4, 4])
        self.assertEqual([len(g) for g in review.groups_of(list(range(3)), 5)], [3])
        self.assertEqual(review.groups_of([], 5), [])
        sizes = [len(g) for g in review.groups_of(list(range(133)), 5)]
        self.assertEqual(sum(sizes), 133)
        self.assertTrue(all(4 <= n <= 5 for n in sizes), sizes)
        self.assertEqual(review.groups_of(list(range(7)), 5), [[0, 1, 2, 3], [4, 5, 6]])    # order kept

    def test_the_call_order_opens_with_the_hook_then_the_ending_then_spreads_over_the_middle(self):
        self.assertEqual(review.call_order(5), [0, 4, 1, 3, 2])
        self.assertEqual(review.call_order(2), [0, 1])
        self.assertEqual(review.call_order(1), [0])
        self.assertEqual(review.call_order(0), [])
        order = review.call_order(27)
        self.assertEqual(sorted(order), list(range(27)))
        self.assertEqual(order[:2], [0, 26])
        self.assertTrue(any(9 <= k <= 18 for k in order[:4]), order[:4])     # the middle comes early too


class Verdicts(unittest.TestCase):
    def test_strict_json_is_read_per_scene(self):
        text = json.dumps({"scenes": [{"scene": 1, "match": 0.9, "issues": [], "note": ""},
                                      {"scene": 2, "match": 0.2, "issues": ["watermark"], "note": "Getty across it"}]})
        got = review.parse_verdicts(text, 2)
        self.assertEqual(got[0], {"match": 0.9, "issues": [], "note": "", "face": "", "covering": ""})
        self.assertEqual(got[1]["issues"], ["mismatch", "watermark"])       # under the floor: a mismatch too
        self.assertEqual(got[1]["note"], "Getty across it")

    def test_what_covers_a_face_is_read_the_captions_by_any_name(self):
        text = json.dumps({"scenes": [
            {"scene": 1, "match": 0.9, "issues": ["text-over-face"], "face": "left", "covering": "the Captions"},
            {"scene": 2, "match": 0.9, "issues": ["text-over-face"], "face": "right",
             "covering": 'lower-third "HOOVER DAM"'}]})
        got = review.parse_verdicts(text, 2)
        self.assertEqual(got[0]["covering"], "captions")
        self.assertEqual(got[1]["covering"], 'lower-third "HOOVER DAM"')

    def test_fenced_or_wrapped_json_and_the_models_own_words_for_an_issue(self):
        text = ('Here you go:\n```json\n[{"scene": 1, "match": "0.8", "issues": "Text over face", "face": "LEFT"},'
                ' {"scene": 2, "match": 0.7, "issues": ["AI generated", "blurry", "nonsense"]}]\n```')
        got = review.parse_verdicts(text, 2)
        self.assertEqual(got[0]["issues"], ["text-over-face"])
        self.assertEqual(got[0]["face"], "left")
        self.assertEqual(got[1]["issues"], ["ai-looking", "blur", "other"])

    def test_bad_json_is_no_verdict_and_a_row_without_a_score_is_dropped(self):
        self.assertIsNone(review.parse_verdicts("All the scenes look fine.", 3))
        self.assertIsNone(review.parse_verdicts("", 3))
        self.assertIsNone(review.parse_verdicts('{"scenes": "fine"}', 3))
        got = review.parse_verdicts('{"scenes": [{"scene": 1, "issues": []}, {"scene": 2, "match": 1}]}', 2)
        self.assertEqual(list(got), [1])
        got = review.parse_verdicts('{"scenes": [{"scene": 9, "match": 1}, {"match": 0.5}]}', 2)
        self.assertEqual(list(got), [1])                                     # out of range dropped, no number = its place

    def test_a_prose_answer_leaves_the_group_unchecked(self):
        frame = _jpg("frame.jpg")
        doc = doc_of([scene(i, video(f"/x/{i}.mp4", 4.0)) for i in range(2)])
        samples, _skipped = review.plan_samples(doc)
        with mock.patch.object(review, "_ask", side_effect=fake_vision(prose=True)):
            got, model = review.ask_group(doc, samples, {f: frame for s in samples for f in s.file_frames})
        self.assertEqual(got, {})
        self.assertEqual(model, "")


# --------------------------------------------------------------------------- #
# Which frames are looked at
# --------------------------------------------------------------------------- #

class Samples(unittest.TestCase):
    def test_one_frame_at_the_midpoint_two_for_a_long_scene_none_for_graphics_and_flashes(self):
        scenes = [scene(0, video("/x/0.mp4", 4.0), seconds=4.0),
                  scene(1, {"type": "animation", "url": "", "source": "template"}, seconds=4.0),
                  scene(2, video("/x/2.mp4", 4.0), seconds=4.0, teaser=True),
                  scene(3, video("/x/3.mp4", 12.0), seconds=10.0)]
        doc = doc_of(scenes)
        samples, skipped = review.plan_samples(doc)
        by = {s.index: s for s in samples}
        self.assertEqual(sorted(by), [0, 3])
        self.assertEqual(by[0].frames, [60])                                  # the midpoint of frames 0..119
        s3 = scenes[3]["startFrame"]
        self.assertEqual(by[3].frames, [s3 + 90, s3 + 210])                    # 30 % and 70 % of a 10 s scene
        self.assertEqual(by[3].file_frames, by[3].frames)
        self.assertIn("graphic", skipped[1])
        self.assertIn("flash", skipped[2])

    def test_the_sample_moves_off_a_full_screen_graphic_and_notes_the_titles_on_screen(self):
        doc = doc_of([scene(0, video("/x/0.mp4", 4.0), seconds=4.0), scene(1, video("/x/1.mp4", 4.0), seconds=4.0)])
        doc["overlays"] = [{"type": "stat", "text": "40 %", "value": 40, "startFrame": 50, "durationInFrames": 30,
                            "backdrop": "blur"},                                 # covers frame 60, the midpoint
                           {"type": "lower-third", "text": "Hoover Dam", "startFrame": 120, "durationInFrames": 120}]
        samples, skipped = review.plan_samples(doc)
        self.assertEqual(samples[0].frames, [42])                              # moved to 35 %
        self.assertEqual(samples[0].graphics, [])
        self.assertEqual(samples[1].graphics, [1])                             # our title is on this frame
        doc["overlays"][0].update(startFrame=0, durationInFrames=120)          # the whole scene under it
        samples, skipped = review.plan_samples(doc)
        self.assertEqual([s.index for s in samples], [1])
        self.assertIn("full-screen graphic", skipped[0])

    def test_a_brand_intro_and_the_files_frame_rate_move_the_frame_numbers(self):
        doc = doc_of([scene(0, video("/x/0.mp4", 4.0), seconds=4.0)])
        doc["brand"] = {"intro": {"url": "https://x/intro.mp4", "frames": 90}}
        samples, _ = review.plan_samples(doc, file_fps=60.0)
        self.assertEqual(samples[0].frames, [60])
        self.assertEqual(samples[0].file_frames, [(90 + 60) * 2])

    def test_scenes_the_gate_just_replaced_are_not_judged_on_their_old_picture(self):
        doc = doc_of([scene(0, video("/x/0.mp4", 4.0)), scene(1, video("/x/1.mp4", 4.0))])
        samples, skipped = review.plan_samples(doc, skip_ids={"s0001"})
        self.assertEqual([s.index for s in samples], [0])
        self.assertIn("quality check", skipped[1])

    def test_the_message_carries_the_line_our_graphics_and_the_frames(self):
        frame = _jpg("frame.jpg")
        doc = doc_of([scene(0, video("/x/0.mp4", 4.0), text="The dam held back the Colorado.")])
        doc["meta"]["story"] = {"summary": "Lake Mead's decline", "places": ["Nevada"], "year": 2022}
        doc["overlays"] = [{"type": "lower-third", "text": "HOOVER DAM", "startFrame": 0, "durationInFrames": 90}]
        samples, _ = review.plan_samples(doc)
        messages = review.build_messages(doc, samples, {samples[0].file_frames[0]: frame})
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn('"watermark"', messages[0]["content"])
        texts = [p["text"] for p in messages[1]["content"] if p.get("type") == "text"]
        self.assertIn("STORY: Lake Mead's decline | places: Nevada | year: 2022", texts[0])
        self.assertIn("captions run along the bottom", texts[0])
        self.assertIn("NARRATION: The dam held back the Colorado.", texts[1])
        self.assertIn('OUR GRAPHICS ON SCREEN: lower-third "HOOVER DAM"', texts[1])
        images = [p for p in messages[1]["content"] if p.get("type") == "image_url"]
        self.assertEqual(len(images), 1)
        self.assertTrue(images[0]["image_url"]["url"].startswith("data:image/jpeg;base64,"))


class LookAlikes(unittest.TestCase):
    def test_the_same_picture_twice_is_a_repeat_a_planned_chain_is_not(self):
        same = _jpg("same_a.jpg", seed=7)
        other = _jpg("other.jpg", seed=8)
        scenes = [scene(i, video(f"/x/{i}.mp4", 4.0)) for i in range(4)]
        doc = doc_of(scenes)
        samples, _ = review.plan_samples(doc)
        pics = {samples[0].file_frames[0]: same, samples[1].file_frames[0]: other,
                samples[2].file_frames[0]: same, samples[3].file_frames[0]: same}
        self.assertEqual(review.find_look_alikes(doc, samples, pics), {2: 0, 3: 0})
        scenes[3]["semanticMetadata"]["moment"] = {"start": 5.0, "chain": True}
        pics[samples[1].file_frames[0]] = same
        got = review.find_look_alikes(doc, samples, pics)
        self.assertEqual(got, {1: 0, 2: 0, 3: 0})          # scene 3 chains scene 2, but also repeats scene 0
        self.assertIsNone(review.picture_hash(_jpg("flat.jpg", flat=True)))


# --------------------------------------------------------------------------- #
# The sound, without a model
# --------------------------------------------------------------------------- #

def _windows(seconds: float, level, step: float = 0.05, peak=None):
    """Windows over `seconds`, `level` a dB value or a function of time; peaks `peak` dB (None = not measured)."""
    out = []
    t = 0.0
    while t < seconds:
        lv = level(t) if callable(level) else level
        pk = peak(t) if callable(peak) else peak
        out.append((round(t, 3), lv, pk))
        t += step
    return out


def _talk_doc(seconds: float = 60.0, scene_seconds: float = 5.0, bgm: bool = True) -> dict:
    """Words 1.2 s on, 0.8 s off, every 2 s; scenes every `scene_seconds`."""
    fps = 30
    n = int(seconds // scene_seconds)
    scenes = []
    for i in range(n):
        t0 = i * scene_seconds
        words = []
        for a in [x * 2.0 for x in range(int(seconds // 2))]:
            if t0 <= a < t0 + scene_seconds:
                words += [{"text": "w", "start": a, "end": a + 0.5}, {"text": "w", "start": a + 0.6, "end": a + 1.2}]
        scenes.append({"id": f"s{i:04d}", "startFrame": int(t0 * fps), "durationInFrames": int(scene_seconds * fps),
                       "text": "x", "media": {"type": "video", "url": "/x.mp4"}, "words": words})
    return {"fps": fps, "durationInFrames": int(seconds * fps), "scenes": scenes, "overlays": [],
            "bgm": {"url": "bgm://calm", "volume": 0.5} if bgm else None}


def _speaking(t: float) -> bool:
    return (t % 2.0) < 1.2


class Sound(unittest.TestCase):
    def test_music_well_under_the_voice_is_fine_music_as_loud_as_the_voice_is_flagged(self):
        doc = _talk_doc()
        quiet = {"windows": _windows(60, lambda t: -20.0 if _speaking(t) else -40.0), "truePeak": -2.0}
        self.assertEqual(review.audio_findings(doc, quiet), [])
        loud = {"windows": _windows(60, lambda t: -20.0 if _speaking(t) else -24.0), "truePeak": -2.0}
        rows = review.audio_findings(doc, loud)
        self.assertEqual([r["issue"] for r in rows], ["music-over-voice"])
        self.assertIn("from 0:00 to 1:00", rows[0]["note"])
        self.assertIn("only about 2 dB under the voice", rows[0]["note"])   # -20 over a -24 bed: the voice is -22
        louder = {"windows": _windows(60, lambda t: -20.0 if _speaking(t) else -19.0), "truePeak": -2.0}
        self.assertIn("louder than the voice", review.audio_findings(doc, louder)[0]["note"])

    def test_music_that_stops_part_way_is_named_with_its_time(self):
        doc = _talk_doc(seconds=120)
        stops = {"windows": _windows(120, lambda t: -20.0 if _speaking(t) else (-38.0 if t < 30 else -80.0)),
                 "truePeak": -2.0}
        rows = review.audio_findings(doc, stops)
        self.assertEqual([(r["issue"], r["at"]) for r in rows], [("music-stops", 30.0)])
        self.assertIn("stops near 0:30", rows[0]["note"])
        doc["bgm"] = None                                            # no music planned: nothing to stop
        self.assertEqual(review.audio_findings(doc, stops), [])

    def test_dead_air_inside_a_scene_is_flagged_a_pause_on_a_scene_boundary_is_not(self):
        doc = _talk_doc(seconds=60, scene_seconds=10.0)
        for s in doc["scenes"]:
            s["words"] = []                                           # no word timings: the voice check sits out
        inside = {"windows": _windows(60, lambda t: -80.0 if 22.0 <= t < 25.0 else -20.0), "truePeak": -2.0}
        rows = review.audio_findings(doc, inside)
        self.assertEqual([r["issue"] for r in rows], ["dead-air"])
        self.assertAlmostEqual(rows[0]["at"], 22.0, places=1)
        self.assertIn("3.0 s of silence", rows[0]["note"])
        at_cut = {"windows": _windows(60, lambda t: -80.0 if 28.5 <= t < 31.5 else -20.0), "truePeak": -2.0}
        self.assertEqual(review.audio_findings(doc, at_cut), [])            # a boundary at 30 s sits inside it
        short = {"windows": _windows(60, lambda t: -80.0 if 22.0 <= t < 24.0 else -20.0), "truePeak": -2.0}
        self.assertEqual(review.audio_findings(doc, short), [])

    def test_clipping_is_counted_from_the_windows_or_the_true_peak(self):
        doc = _talk_doc(seconds=20)
        for s in doc["scenes"]:
            s["words"] = []
        hot = {"windows": _windows(20, -20.0, peak=lambda t: 0.0 if 5.0 <= t < 5.2 else -6.0), "truePeak": 0.3}
        rows = review.audio_findings(doc, hot)
        self.assertEqual([r["issue"] for r in rows], ["clipping"])
        self.assertIn("first at 0:05", rows[0]["note"])
        once = {"windows": _windows(20, -20.0, peak=lambda t: 0.0 if 5.0 <= t < 5.05 else -6.0), "truePeak": 0.3}
        self.assertEqual(review.audio_findings(doc, once), [])             # one stray peak is not clipping
        no_peaks = {"windows": _windows(20, -20.0), "truePeak": 0.4}
        self.assertEqual([r["issue"] for r in review.audio_findings(doc, no_peaks)], ["clipping"])

    def test_the_intro_is_taken_off_the_times(self):
        doc = _talk_doc(seconds=60, scene_seconds=10.0)
        for s in doc["scenes"]:
            s["words"] = []
        doc["brand"] = {"intro": {"url": "https://x/intro.mp4", "frames": 300}}       # 10 s before the narration
        rows = review.audio_findings(doc, {"windows": _windows(70, lambda t: -80.0 if 32.0 <= t < 35.0 else -20.0),
                                           "truePeak": -2.0})
        self.assertEqual([(r["issue"], round(r["at"], 1)) for r in rows], [("dead-air", 22.0)])


# --------------------------------------------------------------------------- #
# The fixes
# --------------------------------------------------------------------------- #

class Alternatives(unittest.TestCase):
    # Real YouTube ids are 11 characters (gapfill._video_of reads only those as one video's moments).
    CURRENT, ALT1, ALT2 = "current0001", "altvideo001", "altvideo002"

    def _doc(self):
        alt1 = _clip("alt1.mp4", 4.0)
        alt2 = _clip("alt2.mp4", 4.0)
        scenes = [scene(0, video(_clip("s0.mp4", 4.0), 4.0)), scene(1, video(_clip("s1.mp4", 4.0), 4.0)),
                  scene(2, video(_clip("s2.mp4", 4.0), 4.0))]
        scenes[1]["semanticMetadata"].update({"assetId": f"yt:{self.CURRENT}",
                                              "sourceUrl": f"https://www.youtube.com/watch?v={self.CURRENT}",
                                              "moment": {"start": 3.0}})
        scenes[1]["semanticMetadata"]["alternatives"] = [
            alternative(alt1, score=0.95, ident=f"yt:{self.ALT1}"),
            alternative(alt2, score=0.80, ident=f"yt:{self.ALT2}"),
        ]
        return doc_of(scenes), alt1, alt2

    def _used(self, doc):
        used = gapfill.Used()
        for k, s in enumerate(doc["scenes"]):
            shot = gapfill.Shot.of_scene(s, 30)
            if shot is not None:
                used.add(k, shot)
        return used

    def test_the_best_choice_above_the_floor_that_covers_the_scene_wins(self):
        doc, alt1, _alt2 = self._doc()
        with mock.patch.object(review, "clip_seconds", return_value=4.0):
            pick = review.pick_alternative(doc, 1, self._used(doc), ["mismatch"])
        self.assertEqual((pick["src"], pick["rank"], pick["kind"]), (alt1, 1, "video"))
        self.assertEqual(pick["seconds"], 4.0)

    def test_under_the_floor_too_short_or_already_shown_elsewhere_is_passed_over(self):
        doc, alt1, alt2 = self._doc()
        alts = doc["scenes"][1]["semanticMetadata"]["alternatives"]
        alts[0]["score"] = 0.6                                       # under VISION_MIN_SCORE
        with mock.patch.object(review, "clip_seconds", return_value=4.0):
            self.assertEqual(review.pick_alternative(doc, 1, self._used(doc), ["mismatch"])["src"], alt2)
        with mock.patch.object(review, "clip_seconds", return_value=1.0):   # 1 s cannot fill a 4 s scene
            self.assertIsNone(review.pick_alternative(doc, 1, self._used(doc), ["mismatch"]))
        alts[0]["score"] = 0.95
        doc["scenes"][2]["media"]["url"] = alt1                      # scene 3 already shows the first choice
        with mock.patch.object(review, "clip_seconds", return_value=4.0):
            self.assertEqual(review.pick_alternative(doc, 1, self._used(doc), ["mismatch"])["src"], alt2)

    def test_a_watermark_or_blur_never_takes_another_moment_of_the_same_source(self):
        doc, alt1, alt2 = self._doc()
        alts = doc["scenes"][1]["semanticMetadata"]["alternatives"]
        alts[0]["assetId"] = f"yt:{self.CURRENT}"
        alts[0]["url"] = f"https://www.youtube.com/watch?v={self.CURRENT}&t=40"
        alts[0]["moment"] = {"start": 40.0}
        with mock.patch.object(review, "clip_seconds", return_value=4.0):
            self.assertEqual(review.pick_alternative(doc, 1, self._used(doc), ["watermark"])["src"], alt2)
            self.assertEqual(review.pick_alternative(doc, 1, self._used(doc), ["mismatch"])["src"], alt1)

    def test_the_shot_the_scene_already_shows_is_never_its_other_choice(self):
        doc, _alt1, alt2 = self._doc()
        alts = doc["scenes"][1]["semanticMetadata"]["alternatives"]
        alts[0]["assetId"] = f"yt:{self.CURRENT}"                       # the very moment on screen now
        alts[0]["url"] = f"https://www.youtube.com/watch?v={self.CURRENT}"
        alts[0]["moment"] = {"start": 3.0}
        with mock.patch.object(review, "clip_seconds", return_value=4.0):
            self.assertEqual(review.pick_alternative(doc, 1, self._used(doc), ["mismatch"])["src"], alt2)
            alts[0]["moment"] = {"start": 3.0}
            alts[1]["media"]["url"] = doc["scenes"][1]["media"]["url"]   # the same file as the scene's
            self.assertIsNone(review.pick_alternative(doc, 1, self._used(doc), ["mismatch"]))

    def test_nothing_more_is_measured_past_the_deadline(self):
        doc, _alt1, _alt2 = self._doc()
        with mock.patch.object(review, "clip_seconds", return_value=4.0) as measured:
            self.assertIsNone(review.pick_alternative(doc, 1, self._used(doc), ["mismatch"],
                                                      deadline=time.time() - 1))
        self.assertEqual(measured.call_count, 0)

    def test_a_published_link_or_a_file_on_this_disk_both_count_nothing_else_does(self):
        doc, alt1, alt2 = self._doc()
        alts = doc["scenes"][1]["semanticMetadata"]["alternatives"]
        alts[0]["media"] = {"type": "video", "url": "https://pub.r2.dev/alts/s0001_alt1.mp4"}
        alts[1].pop("media")
        alts[1]["localPath"] = alt2
        with mock.patch.object(review, "clip_seconds", return_value=4.0):
            self.assertEqual(review.pick_alternative(doc, 1, self._used(doc), ["mismatch"])["src"],
                             "https://pub.r2.dev/alts/s0001_alt1.mp4")
        alts[0]["media"] = {}
        alts[1]["localPath"] = os.path.join(MEDIA, "gone.mp4")
        with mock.patch.object(review, "clip_seconds", return_value=4.0):
            self.assertIsNone(review.pick_alternative(doc, 1, self._used(doc), ["mismatch"]))

    def test_the_swap_puts_the_choice_on_the_scene_the_way_the_renderer_and_editor_read_it(self):
        doc, alt1, _alt2 = self._doc()
        s = doc["scenes"][1]
        with mock.patch.object(review, "clip_seconds", return_value=4.0):
            pick = review.pick_alternative(doc, 1, self._used(doc), ["mismatch"])
        review.swap_in(s, pick, "the picture does not show what the line says")
        self.assertEqual(s["media"]["url"], alt1)
        self.assertEqual(s["media"]["clipSeconds"], 4.0)
        self.assertEqual(s["media"]["type"], "video")
        self.assertEqual(s["semanticMetadata"]["assetId"], f"yt:{self.ALT1}")
        self.assertEqual(s["semanticMetadata"]["moment"], {"start": 12.0})
        self.assertEqual(len(s["semanticMetadata"]["alternatives"]), 1)             # the chosen one left the list
        self.assertTrue(s["reviewRequired"])
        self.assertIn("AI review swapped", s["reviewReason"])
        self.assertEqual(gapfill.find_repeats(doc), [])


class Titles(unittest.TestCase):
    TID = next(t["id"] for t in review.templates.all_templates() if "align" in (t.get("props") or {}))

    def test_a_corner_figure_goes_to_the_other_corner_only_when_it_is_on_the_faces_side(self):
        ov = {"type": "stat", "template": "LIB_NUM_RANK", "compact": True, "position": "bottom-left",
              "startFrame": 0, "durationInFrames": 120}
        self.assertEqual(review.move_graphic(ov, "left", 30), "moved to the right corner")
        self.assertEqual(ov["position"], "bottom-right")
        self.assertEqual(review.move_graphic(ov, "left", 30), "")          # now on the other side: not over it
        self.assertEqual(review.move_graphic(ov, "center", 30), "")        # a corner never covers the middle
        self.assertEqual(ov["durationInFrames"], 120)

    def test_a_text_look_moves_to_the_side_away_from_the_face(self):
        ov = {"type": "lower-third", "template": self.TID, "align": "left", "startFrame": 0, "durationInFrames": 120}
        self.assertEqual(review.move_graphic(ov, "left", 30), "moved to the right")
        self.assertEqual(ov["align"], "right")
        ov = {"type": "lower-third", "template": self.TID, "align": "center", "startFrame": 0, "durationInFrames": 120}
        self.assertEqual(review.move_graphic(ov, "right", 30), "moved to the left")
        self.assertEqual(ov["align"], "left")

    def test_a_look_already_on_the_other_side_is_not_moved_or_cut(self):
        # Our looks draw on the left when no side is set (LibBoldText / LibPackNumbers alignOf): a face on
        # the right is not under them, and "moving" them left would change nothing but cost a render.
        for align in ("right", None, "auto"):
            ov = {"type": "lower-third", "template": self.TID, "startFrame": 0, "durationInFrames": 120}
            if align:
                ov["align"] = align
            face = "left" if align == "right" else "right"
            self.assertEqual(review.move_graphic(ov, face, 30), "", align)
            self.assertEqual(ov["durationInFrames"], 120)
            self.assertEqual(ov.get("align"), align)
        ov = {"type": "lower-third", "template": self.TID, "startFrame": 0, "durationInFrames": 120}
        self.assertEqual(review.move_graphic(ov, "left", 30), "moved to the right")   # no side set = the left

    def test_anything_else_is_shortened_never_under_its_own_least_time_or_left_alone(self):
        ov = {"type": "highlight", "text": "x", "startFrame": 0, "durationInFrames": 150}
        self.assertEqual(review.move_graphic(ov, "center", 30), "shortened to 2 s")
        self.assertEqual(ov["durationInFrames"], 60)
        ov = {"type": "highlight", "text": "x", "startFrame": 0, "durationInFrames": 60}
        self.assertEqual(review.move_graphic(ov, "center", 30), "")
        self.assertEqual(ov["durationInFrames"], 60)
        slow = {"defaults": {"sfxAt": 75}, "props": {"duration": {"min": 1.5}}}     # lands 2.5 s in
        with mock.patch.object(review.templates, "get", return_value=slow):
            ov = {"type": "stat", "template": "SLOW", "startFrame": 0, "durationInFrames": 300}
            how = review.move_graphic(ov, "center", 30)
        least = review._least_seconds(slow)
        self.assertGreater(least, 2.5)
        self.assertEqual(how, f"shortened to {round(least, 1):g} s")
        self.assertGreaterEqual(ov["durationInFrames"], least * 30 - 1e-6)


class Fixes(unittest.TestCase):
    """Review.after_render on a document, with a fake gate: what is swapped, moved, sent to the ladder or left."""

    def _doc(self, n: int = 5):
        scenes = [scene(i, video(_clip(f"c{i}.mp4", 4.0), 4.0), seconds=4.0) for i in range(n)]
        for i, s in enumerate(scenes):
            s["semanticMetadata"]["alternatives"] = [alternative(_clip(f"alt_{i}.mp4", 4.0), ident=f"yt:alt{i}")]
        return doc_of(scenes)

    def test_a_mismatch_with_a_ready_choice_is_swapped_the_rest_is_listed(self):
        doc = self._doc()
        doc["scenes"][3]["semanticMetadata"]["alternatives"] = []
        bad = {"line 1": {"match": 0.2, "issues": ["mismatch"], "note": "a harbour, not a dam"},
               "line 3": {"match": 0.1, "issues": ["mismatch"]},
               "line 4": {"match": 0.9, "issues": ["talking-head"]}}
        gate = FakeGate()
        with _Review(fake_vision(bad)) as ctx:
            rev = review.Review(doc, tempfile.mkdtemp())
            again = rev.after_render("/x/final.mp4", gate, may_fix=True)
        self.assertTrue(again)
        self.assertTrue(gate.rerendered)
        self.assertEqual(len(ctx.ask.calls), 1)                                     # 5 scenes, one call
        self.assertEqual([(r["scene"], r["issue"]) for r in rev.fixed], [("s0001", "mismatch")])
        self.assertIn("swapped for its choice 1", rev.fixed[0]["how"])
        self.assertEqual(doc["scenes"][1]["media"]["url"], _clip("alt_1.mp4", 4.0))
        self.assertEqual([(r["scene"], r["issue"]) for r in rev.left], [("s0003", "mismatch"), ("s0004", "talking-head")])
        self.assertIn("no other choice", rev.left[0]["why"])
        self.assertEqual(doc["scenes"][3]["media"]["url"], _clip("c3.mp4", 4.0))        # untouched
        report = rev.finish()
        self.assertEqual(report["summary"],
                         "AI review: 3/5 scenes fit the narration, 1 clip swapped, 2 left for you")
        self.assertEqual(report["status"], "done")
        self.assertTrue(report["rerendered"])

    def test_a_mismatch_the_model_names_but_scores_well_is_listed_not_swapped(self):
        doc = self._doc()
        bad = {"line 1": {"match": 0.6, "issues": ["mismatch"], "note": "maybe"}}
        with _Review(fake_vision(bad)):
            rev = review.Review(doc, tempfile.mkdtemp())
            self.assertFalse(rev.after_render("/x/final.mp4", FakeGate(), may_fix=True))
        self.assertEqual(rev.fixed, [])
        self.assertEqual([r["issue"] for r in rev.left], ["mismatch"])
        self.assertEqual(doc["scenes"][1]["media"]["url"], _clip("c1.mp4", 4.0))

    def test_a_watermark_blur_or_ai_picture_is_swapped_too_and_a_scene_with_two_faults_once(self):
        doc = self._doc()
        bad = {"line 1": {"match": 0.9, "issues": ["watermark", "blur"], "note": "Alamy across it"},
               "line 2": {"match": 0.8, "issues": ["ai-looking"]}}
        with _Review(fake_vision(bad)):
            rev = review.Review(doc, tempfile.mkdtemp())
            self.assertTrue(rev.after_render("/x/final.mp4", FakeGate(), may_fix=True))
        self.assertEqual([(r["scene"], r["issue"], r.get("also")) for r in rev.fixed],
                         [("s0001", "watermark", ["blur"]), ("s0002", "ai-looking", None)])
        self.assertEqual(rev.left, [])
        self.assertIn("2 clips swapped", rev.summary())
        self.assertIn("5/5 scenes fit", rev.summary())

    def test_a_repeat_takes_its_choice_else_the_ladder_else_it_is_listed(self):
        doc = self._doc()
        doc["scenes"][3]["semanticMetadata"]["alternatives"] = []
        doc["scenes"][4]["semanticMetadata"]["alternatives"] = []
        # The model calls four scenes repeats of one another: the first to show the shot keeps it.
        bad = {f"line {i}": {"match": 0.9, "issues": ["repeat"], "note": ""} for i in (1, 2, 3, 4)}
        gate = FakeGate(ladder={3: "a library clip"})
        with _Review(fake_vision(bad)):
            rev = review.Review(doc, tempfile.mkdtemp())
            self.assertTrue(rev.after_render("/x/final.mp4", gate, may_fix=True))
        self.assertEqual(rev.verdicts[1]["issues"], [])
        self.assertEqual(gate.asked, [{3: ("repeat", "the shot looks like one already shown"),
                                       4: ("repeat", "the shot looks like one already shown")}])
        self.assertEqual([(r["scene"], r["how"]) for r in rev.fixed],
                         [("s0002", "swapped for its choice 1 (scored 0.90 for this line)"),
                          ("s0003", "replaced with a library clip")])
        self.assertEqual([(r["scene"], r["why"]) for r in rev.left], [("s0004", "no other shot was found for this scene")])
        self.assertEqual(doc["scenes"][1]["media"]["url"], _clip("c1.mp4", 4.0))

    def test_the_same_picture_twice_in_the_video_is_found_on_the_frames(self):
        doc = self._doc(3)
        same, other = _jpg("rep_same.jpg", seed=3), _jpg("rep_other.jpg", seed=4)

        def grab(path, numbers, folder, width=512, timeout=None, **kw):
            nums = sorted(numbers)
            return {nums[0]: same, nums[1]: other, nums[2]: same}
        with _Review(fake_vision(), pics=grab):
            rev = review.Review(doc, tempfile.mkdtemp())
            self.assertTrue(rev.after_render("/x/final.mp4", FakeGate(), may_fix=True))
        self.assertEqual([(r["scene"], r["issue"]) for r in rev.fixed], [("s0002", "repeat")])
        self.assertEqual(rev.fixed[0]["note"], "looks the same as the shot at 0:00")

    def test_a_title_over_a_face_is_moved_to_the_other_side(self):
        doc = self._doc(2)
        tid = next(t["id"] for t in review.templates.all_templates() if "align" in (t.get("props") or {}))
        doc["overlays"] = [{"type": "lower-third", "template": tid, "text": "HOOVER DAM", "align": "left",
                            "startFrame": 120, "durationInFrames": 120}]
        bad = {"line 1": {"match": 0.9, "issues": ["text-over-face"], "face": "left", "note": "the title sits on his face"}}
        with _Review(fake_vision(bad)):
            rev = review.Review(doc, tempfile.mkdtemp())
            self.assertTrue(rev.after_render("/x/final.mp4", FakeGate(), may_fix=True))
        self.assertEqual(doc["overlays"][0]["align"], "right")
        self.assertEqual([(r["issue"], r["how"]) for r in rev.fixed],
                         [("text-over-face", 'lower-third "HOOVER DAM" moved to the right')])
        self.assertEqual(rev.summary(), "AI review: 2/2 scenes fit the narration, 1 title moved")

    def _two_titles(self):
        doc = self._doc(2)
        tid = Titles.TID
        doc["overlays"] = [{"type": "lower-third", "template": tid, "text": "HOOVER DAM", "align": "left",
                            "startFrame": 120, "durationInFrames": 120},
                           {"type": "stat", "template": tid, "text": "40 % LOWER", "align": "left",
                            "startFrame": 150, "durationInFrames": 60}]
        return doc

    def test_only_the_graphic_the_model_names_is_moved_and_captions_are_left_alone(self):
        doc = self._two_titles()
        bad = {"line 1": {"match": 0.9, "issues": ["text-over-face"], "face": "left",
                          "covering": 'stat "40 % LOWER"'}}
        with _Review(fake_vision(bad)):
            rev = review.Review(doc, tempfile.mkdtemp())
            self.assertTrue(rev.after_render("/x/final.mp4", FakeGate(), may_fix=True))
        self.assertEqual([ov["align"] for ov in doc["overlays"]], ["left", "right"])
        doc = self._two_titles()
        before = copy.deepcopy(doc)
        bad["line 1"]["covering"] = "captions"
        with _Review(fake_vision(bad)):
            rev = review.Review(doc, tempfile.mkdtemp())
            self.assertFalse(rev.after_render("/x/final.mp4", FakeGate(), may_fix=True))
        self.assertEqual(doc, before)
        self.assertEqual([(r["issue"], r["why"]) for r in rev.left],
                         [("text-over-face", "the captions cover the face - move them in the editor")])

    def test_a_title_already_clear_of_the_face_costs_no_second_render(self):
        doc = self._two_titles()
        bad = {"line 1": {"match": 0.9, "issues": ["text-over-face"], "face": "right"}}   # ours sit on the left
        gate = FakeGate()
        with _Review(fake_vision(bad)):
            rev = review.Review(doc, tempfile.mkdtemp())
            self.assertFalse(rev.after_render("/x/final.mp4", gate, may_fix=True))
        self.assertFalse(gate.rerendered)
        self.assertEqual([ov["align"] for ov in doc["overlays"]], ["left", "left"])
        self.assertIn("already clear", rev.left[0]["why"])

    def test_a_review_that_breaks_after_a_fix_takes_its_changes_back(self):
        doc = self._doc()
        before = copy.deepcopy(doc)

        class Breaks(FakeGate):
            def join_second_render(self, scenes, why):
                raise RuntimeError("a bug")
        bad = {"line 1": {"match": 0.2, "issues": ["mismatch"]}}
        gate = Breaks()
        with _Review(fake_vision(bad)):
            rev = review.Review(doc, tempfile.mkdtemp())
            self.assertFalse(rev.after_render("/x/final.mp4", gate, may_fix=True))
        self.assertEqual(doc["scenes"], before["scenes"])
        self.assertEqual(rev.fixed, [])
        self.assertIn("review broke", rev.left[0]["why"])
        self.assertFalse(rev.finish()["rerendered"])

    def test_too_many_swaps_wanted_means_none_everything_listed(self):
        doc = self._doc(6)
        bad = {f"line {i}": {"match": 0.1, "issues": ["mismatch"]} for i in range(4)}
        with _Review(fake_vision(bad)):
            rev = review.Review(doc, tempfile.mkdtemp())
            self.assertFalse(rev.after_render("/x/final.mp4", FakeGate(), may_fix=True))
        self.assertEqual(rev.fixed, [])
        self.assertEqual(len(rev.left), 4)
        self.assertIn("too many to trust", rev.left[0]["why"])
        self.assertTrue(all(s["media"]["url"] == _clip(f"c{i}.mp4", 4.0) for i, s in enumerate(doc["scenes"])))

    def test_with_fixing_off_or_the_second_render_spent_the_review_only_lists(self):
        doc = self._doc()
        bad = {"line 1": {"match": 0.2, "issues": ["mismatch"]}}
        with _Review(fake_vision(bad), AI_REVIEW_FIX=False):
            rev = review.Review(doc, tempfile.mkdtemp())
            self.assertFalse(rev.after_render("/x/final.mp4", FakeGate(), may_fix=True))
        self.assertEqual([r["why"] for r in rev.left], ["fixing is switched off (AI_REVIEW_FIX)"])
        with _Review(fake_vision(bad)):
            rev = review.Review(doc, tempfile.mkdtemp())
            self.assertFalse(rev.after_render("/x/final.mp4", FakeGate(), may_fix=False))
        self.assertEqual([r["why"] for r in rev.left], ["the one second render was already used"])
        self.assertEqual(doc["scenes"][1]["media"]["url"], _clip("c1.mp4", 4.0))

    def test_a_second_render_that_is_not_kept_takes_the_fixes_back(self):
        doc = self._doc()
        before = copy.deepcopy(doc)
        bad = {"line 1": {"match": 0.2, "issues": ["mismatch"]}}
        with _Review(fake_vision(bad)):
            rev = review.Review(doc, tempfile.mkdtemp())
            self.assertTrue(rev.after_render("/x/final.mp4", FakeGate(), may_fix=True))
            self.assertNotEqual(doc["scenes"][1]["media"]["url"], before["scenes"][1]["media"]["url"])
            rev.after_rerender("first")
        self.assertEqual(doc["scenes"], before["scenes"])
        self.assertEqual(rev.fixed, [])
        self.assertEqual([(r["scene"], r["why"]) for r in rev.left],
                         [("s0001", "the second render came out worse, so the first one is kept")])
        self.assertFalse(rev.finish()["rerendered"])

    def test_a_gate_that_cannot_prepare_the_second_render_takes_the_fixes_back(self):
        doc = self._doc()
        before = copy.deepcopy(doc)
        bad = {"line 1": {"match": 0.2, "issues": ["mismatch"]}}
        with _Review(fake_vision(bad)):
            rev = review.Review(doc, tempfile.mkdtemp())
            self.assertFalse(rev.after_render("/x/final.mp4", FakeGate(join=False), may_fix=True))
        self.assertEqual(doc["scenes"], before["scenes"])
        self.assertEqual(rev.fixed, [])


class PlannedBeforeTheGate(unittest.TestCase):
    """The frames come from the first render; the gate's repair after its scan merges scenes and drops looks."""

    def test_a_merged_scene_is_not_judged_and_the_rest_keep_what_was_drawn(self):
        doc = doc_of([scene(i, video(_clip(f"p{i}.mp4", 8.0), 8.0), seconds=4.0) for i in range(3)])
        doc["overlays"] = [{"type": "stat", "template": Titles.TID, "text": "GONE SOON", "align": "left",
                            "startFrame": 0, "durationInFrames": 90},
                           {"type": "lower-third", "template": Titles.TID, "text": "HOOVER DAM", "align": "left",
                            "startFrame": 260, "durationInFrames": 90}]
        asked = []
        bad = {"line 2": {"match": 0.9, "issues": ["text-over-face"], "face": "left",
                          "covering": 'lower-third "HOOVER DAM"'}}
        with _Review(fake_vision(bad), pics=_frames_from(asked=asked)) as ctx:
            rev = review.Review(doc, tempfile.mkdtemp())
            rev.plan()
            # The gate's repair after its scan: scene 1 merged into its neighbours (they grow over its
            # time, its words go to the line before), the first look dropped from the list.
            self.assertTrue(gapfill._hold(doc, 1, None))
            title = doc["overlays"][1]
            del doc["overlays"][0]
            gate = FakeGate()
            gate.repairs = [{"scene": "s0001", "stage": "after the render", "how": "held over by its neighbouring shots"}]
            self.assertTrue(rev.after_render("/x/final.mp4", gate, may_fix=True))
        self.assertEqual(asked, [[60, 300]])               # the midpoints drawn, not the merged scenes' [90, 270]
        texts = [p["text"] for p in ctx.ask.calls[0][1]["content"] if p.get("type") == "text"]
        self.assertFalse(any("line 1" in t for t in texts))                    # the merged scene: not asked about
        self.assertTrue(any("NARRATION: Lake Mead dropped again in line 0\n" in t for t in texts))   # as drawn
        self.assertTrue(any('OUR GRAPHICS ON SCREEN: stat "GONE SOON"' in t for t in texts))     # on that frame
        self.assertEqual(rev.not_reviewed[1], "the quality check has just replaced it")
        self.assertEqual(doc["overlays"], [title])
        self.assertEqual(title["align"], "right")                                  # the look named, wherever it sits now
        self.assertEqual([(r["scene"], r["at"]) for r in rev.fixed], [("s0002", "0:08")])


class Budgets(unittest.TestCase):
    def _doc(self, n):
        return doc_of([scene(i, video(_clip(f"b{i}.mp4", 4.0), 4.0)) for i in range(n)])

    def test_the_call_cap_leaves_scattered_scenes_unchecked_never_the_ending(self):
        doc = self._doc(30)
        with _Review(fake_vision(), AI_REVIEW_MAX_CALLS=3, AI_REVIEW_GROUP=5) as ctx:
            rev = review.Review(doc, tempfile.mkdtemp())
            rev.after_render("/x/final.mp4", FakeGate(), may_fix=True)
        self.assertEqual(len(ctx.ask.calls), 3)                                    # fuller calls (6) before any cut
        self.assertEqual(len(rev.verdicts), 18)
        self.assertEqual(len(rev.unchecked), 12)
        self.assertIn(0, rev.verdicts)
        self.assertIn(29, rev.verdicts)                                            # the ending was seen
        self.assertTrue(all("budget" in why for why in rev.unchecked.values()))
        report = rev.finish()
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["summary"], "AI review: 18/18 scenes fit the narration, 12 not checked")

    def test_the_time_cap_leaves_the_slow_calls_unchecked(self):
        doc = self._doc(10)
        with _Review(fake_vision(delay=1.5), AI_REVIEW_SECONDS=0.3, AI_REVIEW_PARALLEL=1):
            rev = review.Review(doc, tempfile.mkdtemp())
            rev.after_render("/x/final.mp4", FakeGate(), may_fix=True)
        self.assertLess(len(rev.verdicts), 10)
        self.assertTrue(any("time ran out" in why for why in rev.unchecked.values()))

    def test_the_whole_review_keeps_to_its_time_and_a_late_answer_is_never_counted(self):
        # Slow frames and a model that answers after the budget: the review gives up on time, the
        # call still out is abandoned (not waited for, its answer never read, its cost not booked).
        doc = self._doc(10)
        costs.reset()
        t0 = time.time()
        with _Review(fake_vision(delay=3.0), pics=_frames_from(delay=0.3), AI_REVIEW_SECONDS=1.5,
                     AI_REVIEW_PARALLEL=2):
            rev = review.Review(doc, tempfile.mkdtemp())
            self.assertFalse(rev.after_render("/x/final.mp4", FakeGate(), may_fix=True))
            took = time.time() - t0
        self.assertLess(took, 2.5)
        self.assertEqual(rev.verdicts, {})
        report = rev.finish()
        self.assertEqual(report["status"], "skipped")
        self.assertIn("time ran out", report["summary"])
        self.assertEqual(report["calls"], 2)                                      # sent, then abandoned
        self.assertTrue(any("still out" in n for n in report["notes"]))
        time.sleep(max(0.0, 3.6 - (time.time() - t0)))                            # the late answers come back
        self.assertNotIn("vision.review", costs.LEDGER.units)
        self.assertEqual(report["cost"], 0.0)

    def test_fixes_stop_when_the_time_is_up_and_the_ladder_gets_only_what_is_left(self):
        doc = doc_of([scene(i, video(_clip(f"t{i}.mp4", 4.0), 4.0), seconds=4.0) for i in range(6)])
        for i, s in enumerate(doc["scenes"]):
            s["semanticMetadata"]["alternatives"] = [alternative(_clip(f"t_alt{i}.mp4", 4.0), ident=f"yt:talt{i}")]
        bad = {f"line {i}": {"match": 0.1, "issues": ["mismatch"]} for i in (1, 2, 3)}
        real = review.pick_alternative

        def slow(*a, **k):                  # each choice takes 1.6 s to measure
            got = real(*a, **k)
            time.sleep(1.6)
            return got
        with _Review(fake_vision(bad), AI_REVIEW_SECONDS=3.0), mock.patch.object(review, "pick_alternative",
                                                                                 side_effect=slow):
            rev = review.Review(doc, tempfile.mkdtemp())
            self.assertTrue(rev.after_render("/x/final.mp4", FakeGate(), may_fix=True))
        self.assertEqual([r["scene"] for r in rev.fixed], ["s0001", "s0002"])
        self.assertEqual([(r["scene"], r["why"]) for r in rev.left],
                         [("s0003", "the review's time ran out before this scene was fixed")])
        doc = self._doc(3)
        for s in doc["scenes"]:
            s["semanticMetadata"]["alternatives"] = []
        gate = FakeGate(ladder={2: "a library clip"})
        with _Review(fake_vision({"line 2": {"match": 0.9, "issues": ["repeat"]}}), AI_REVIEW_SECONDS=60):
            rev = review.Review(doc, tempfile.mkdtemp())
            self.assertTrue(rev.after_render("/x/final.mp4", gate, may_fix=True))
        self.assertEqual(len(gate.seconds), 1)
        self.assertLessEqual(gate.seconds[0], 60)
        self.assertLessEqual(gate.seconds[0], config.QUALITY_REPAIR_SECONDS)

    def test_the_cost_is_counted_from_the_providers_price_or_estimated(self):
        doc = self._doc(5)
        costs.reset()
        ask = fake_vision()

        def priced(messages, max_tokens, accept=None):
            costs.record("vision.usd", 0.0021)
            return ask(messages, max_tokens, accept)
        with _Review(priced):
            rev = review.Review(doc, tempfile.mkdtemp())
            rev.after_render("/x/final.mp4", FakeGate(), may_fix=True)
        self.assertAlmostEqual(rev.finish()["cost"], 0.0021)
        self.assertTrue(rev.cost_measured)
        costs.reset()
        with _Review(fake_vision()):
            rev = review.Review(doc, tempfile.mkdtemp())
            rev.after_render("/x/final.mp4", FakeGate(), may_fix=True)
        self.assertFalse(rev.cost_measured)
        self.assertAlmostEqual(rev.finish()["cost"], costs.DEFAULT_PRICES["vision.review"] * costs.DEFAULT_PRICES["kie.credit"])
        self.assertEqual(costs.LEDGER.units["vision.review"], 1)


class NeverTheCause(unittest.TestCase):
    def test_a_prose_answer_a_missing_model_or_a_broken_step_is_a_skipped_review(self):
        doc = doc_of([scene(i, video(_clip(f"n{i}.mp4", 4.0), 4.0)) for i in range(3)])
        with _Review(fake_vision(prose=True)):
            rev = review.Review(doc, tempfile.mkdtemp())
            self.assertFalse(rev.after_render("/x/final.mp4", FakeGate(), may_fix=True))
        self.assertEqual(rev.finish()["status"], "skipped")
        self.assertIn("no usable answer", rev.finish()["summary"])
        with _Review(fake_vision()), mock.patch.object(review, "_vision_on", return_value=False):
            rev = review.Review(doc, tempfile.mkdtemp())
            rev.after_render("/x/final.mp4", FakeGate(), may_fix=True)
        self.assertIn("no vision model", rev.finish()["summary"])
        with _Review(fake_vision()), mock.patch.object(review, "plan_samples", side_effect=RuntimeError("a bug")):
            rev = review.Review(doc, tempfile.mkdtemp())
            self.assertFalse(rev.after_render("/x/final.mp4", FakeGate(), may_fix=True))
        report = rev.finish()
        self.assertEqual(report["status"], "skipped")
        self.assertTrue(any("picture review broke" in n for n in report["notes"]))
        self.assertTrue(any(e["event"] == "check_failed" for e in events._EVENTS if e["stage"] == "review"))

    def test_off_means_nothing_happens(self):
        doc = doc_of([scene(0, video(_clip("off0.mp4", 4.0), 4.0))])
        before = copy.deepcopy(doc)
        with _Review(fake_vision(), AI_REVIEW=False) as ctx:
            rev = review.Review(doc, tempfile.mkdtemp())
            rev.plan()
            self.assertIsNone(rev.planned)
            self.assertFalse(rev.after_render("/x/final.mp4", FakeGate(), may_fix=True))
            rev.after_rerender("first")
            rev.rerender_failed(RuntimeError("x"))
        self.assertIsNone(rev.finish())
        self.assertEqual(ctx.ask.calls, [])
        self.assertEqual(doc, before)

    def test_a_document_with_odd_numbers_never_breaks_the_review_setup(self):
        for doc in ({"fps": "abc", "scenes": []}, None, {"fps": 30, "scenes": [{"id": "s0000"}]}):
            with _Review(fake_vision()):
                rev = review.Review(doc, tempfile.mkdtemp())
                rev.plan()
                self.assertFalse(rev.after_render("/x/final.mp4", FakeGate(), may_fix=True))
                self.assertIn("AI review", rev.finish()["summary"])


class Report(unittest.TestCase):
    def test_the_shape_the_app_reads_and_the_job_progress_copy(self):
        doc = doc_of([scene(i, video(_clip(f"r{i}.mp4", 4.0), 4.0)) for i in range(3)])
        doc["scenes"][1]["semanticMetadata"]["alternatives"] = [alternative(_clip("r_alt.mp4", 4.0))]
        bad = {"line 1": {"match": 0.2, "issues": ["mismatch"], "note": "a harbour"},
               "line 2": {"match": 0.9, "issues": ["logo"], "note": "a station bug"}}

        class Rep:
            extra = {}

            def __call__(self, step, pct=None, **kw):
                pass
        rep = Rep()
        with _Review(fake_vision(bad)):
            rev = review.Review(doc, tempfile.mkdtemp(), rep)
            rev.after_render("/x/final.mp4", FakeGate(), may_fix=True)
        out = rev.finish()
        for key in ("summary", "status", "checked", "fixed", "left", "cost", "seconds", "calls", "model", "audio",
                    "scenes", "fit", "notChecked", "rerendered"):
            self.assertIn(key, out)
        self.assertEqual(out["checked"], 3)
        self.assertEqual(out["model"], "fake/model")
        self.assertEqual(out["fixed"][0]["scene"], "s0001")
        self.assertEqual(set(out["left"][0]) >= {"scene", "issue", "note", "at"}, True)
        progress = rep.extra["review"]
        self.assertEqual(progress["summary"], out["summary"])
        self.assertEqual(progress["fixed"], [{"scene": "s0001", "at": "0:03", "issue": "mismatch",
                                              "how": "swapped for its choice 1 (scored 0.90 for this line)"}])
        self.assertEqual(progress["left"], [{"scene": "s0002", "at": "0:06", "issue": "logo", "note": "a station bug"}])
        rows = [e for e in events._EVENTS if e["stage"] == "review"]
        self.assertIn("summary", [e["event"] for e in rows])
        self.assertIn("fixed", [e["event"] for e in rows])
        self.assertEqual(rows[-1]["message"], out["summary"])
        self.assertIs(rev.finish(), out)                                          # written once

    def test_the_saved_timeline_is_marked_where_the_video_changed(self):
        doc = doc_of([scene(i, video(f"/x/{i}.mp4", 4.0)) for i in range(3)])
        reviewed = {"fixed": [{"scene": "s0001", "issue": "mismatch", "note": "a harbour", "how": "swapped for its choice 1"},
                              {"scene": "s0000", "issue": "text-over-face", "note": "x", "how": "moved"}],
                    "left": [{"scene": "s0002", "issue": "watermark", "note": "Getty"},
                             {"scene": "s0000", "issue": "music-over-voice", "note": "loud", "sound": True}]}
        self.assertEqual(review.mark_for_review(doc, reviewed), 2)
        self.assertIn("AI review changed this scene", doc["scenes"][1]["reviewReason"])
        self.assertEqual(doc["scenes"][2]["reviewReason"], "The AI review: watermark - Getty")
        self.assertNotIn("reviewRequired", doc["scenes"][0])


# --------------------------------------------------------------------------- #
# The quality gate's part: the ladder for another check, the one second render
# --------------------------------------------------------------------------- #

class GateSide(unittest.TestCase):
    def test_another_shot_keeps_a_scene_the_ladder_finds_nothing_for(self):
        doc = doc_of([scene(0, video("/x/0.mp4", 4.0)), scene(1, video("/x/1.mp4", 4.0))])
        before = copy.deepcopy(doc["scenes"][1])
        quality.set_context(ladder=True)
        try:
            gate = quality.Gate(doc, tempfile.mkdtemp())
            boxes = []

            def ladder(order, banned, problems, seconds=None):
                boxes.append(seconds)
                return {}
            with mock.patch.object(config, "FALLBACK_FILL", True), \
                    mock.patch.object(gate, "_ladder", side_effect=ladder):
                self.assertEqual(gate.another_shot({1: ("repeat", "x")}, seconds=42.0), {})
            self.assertEqual(boxes, [42.0])                                         # the caller's time box
            self.assertEqual(doc["scenes"][1], before)
            with mock.patch.object(config, "FALLBACK_FILL", True), \
                    mock.patch.object(gate, "_ladder", side_effect=RuntimeError("boom")):
                self.assertEqual(gate.another_shot({1: ("repeat", "x")}), {})
            self.assertEqual(doc["scenes"][1], before)
            with mock.patch.object(config, "FALLBACK_FILL", False):
                self.assertEqual(gate.another_shot({1: ("repeat", "x")}), {})
        finally:
            quality.reset()

    def test_the_ladder_takes_the_callers_time_box_and_the_gates_own_otherwise(self):
        doc = doc_of([scene(0, video("/x/0.mp4", 4.0)), scene(1, video("/x/1.mp4", 4.0))])
        gate = quality.Gate(doc, tempfile.mkdtemp())
        boxes = []
        with mock.patch.object(gapfill, "fill_empty", side_effect=lambda *a, **k: boxes.append(k["seconds"])):
            gate._ladder([1], [], {1: ("repeat", "x")}, seconds=12.5)
            gate._ladder([1], [], {1: ("repeat", "x")})
        self.assertEqual(boxes, [12.5, config.QUALITY_REPAIR_SECONDS])
        quality.reset()

    def test_no_third_draw_after_a_render_that_failed_and_was_drawn_again(self):
        doc = doc_of([scene(0, video("/x/0.mp4", 4.0))])
        gate = quality.Gate(doc, tempfile.mkdtemp())
        gate.render["afterFailure"] = True                  # Gate.recover drew the second render already
        with mock.patch.object(config, "QUALITY_RERENDER", True):
            self.assertFalse(gate.join_second_render([0], "the AI review"))
        quality.reset()

    def test_what_the_first_scan_left_is_listed_once_after_the_reviews_second_render(self):
        # A defect with no scene to repair (the gate leaves it and draws nothing more), then the
        # review's fix takes the second render: the defect is judged again, never listed twice.
        doc = doc_of([scene(0, video("/x/0.mp4", 4.0))])
        work = tempfile.mkdtemp()
        first, final = os.path.join(work, "final.first.mp4"), os.path.join(work, "final.mp4")
        for p in (first, final):
            with open(p, "wb") as fh:
                fh.write(b"x" * 2048)
        silent = {"kind": "silent", "start": 0.0, "end": 3.0, "at": "0:00", "scenes": [], "why": "the video has no sound"}
        scanned = {"ok": True, "why": "", "black": [], "frozen": [], "silent": [], "seconds": 0.1}
        gate = quality.Gate(doc, work)
        with mock.patch.object(quality, "scan", return_value=scanned), \
                mock.patch.object(quality, "classify", return_value=([silent], [])), \
                mock.patch.object(config, "QUALITY_RERENDER", True):
            self.assertFalse(gate.after_render(final))
            self.assertEqual(len(gate.unresolved), 1)
            self.assertTrue(gate.join_second_render([0], "the AI review"))
            self.assertEqual(gate.unresolved, [])
            self.assertEqual(gate.after_rerender(final, first), "repaired")
        self.assertEqual([u["kind"] for u in gate.unresolved], ["silent"])
        quality.reset()

    def test_join_second_render_marks_the_gate_and_respects_the_switch(self):
        doc = doc_of([scene(0, video("/x/0.mp4", 4.0))])
        gate = quality.Gate(doc, tempfile.mkdtemp())
        with mock.patch.object(config, "QUALITY_RERENDER", False):
            self.assertFalse(gate.join_second_render([0], "the AI review"))
        self.assertFalse(gate.rerendered)
        with mock.patch.object(config, "QUALITY_RERENDER", True):
            self.assertTrue(gate.join_second_render([0], "the AI review"))
        self.assertTrue(gate.rerendered)
        self.assertTrue(gate.render["rerendered"])
        self.assertEqual(gate.render["askedBy"], "the AI review")
        quality.reset()


# --------------------------------------------------------------------------- #
# do_render end to end: the review's fix and the gate's repair share ONE second render
# --------------------------------------------------------------------------- #

@unittest.skipUnless(FFMPEG, "needs ffmpeg")
class DoRender(unittest.TestCase):
    def setUp(self):
        events.start_job("review-render", "")
        self.alt = _clip("e2e_alt.mp4", 4.0)
        scenes = [scene(i, video(_clip(f"e2e_{i}.mp4", 4.0), 4.0), seconds=2.0) for i in range(3)]
        scenes[1]["semanticMetadata"]["alternatives"] = [alternative(self.alt, published=False)]
        self.doc = doc_of(scenes)
        self.clean = _video("e2e_clean.mp4", [("moving", 6.0)])
        # Scene 3 black for 1.2 s - inside the video: black in its last 0.25 s is "the last moments".
        self.black = _video("e2e_black_inside.mp4", [("moving", 4.1), ("black", 1.2), ("moving", 0.7)])
        self.worse = _video("e2e_worse.mp4", [("moving", 1.0), ("black", 4.0), ("moving", 1.0)])
        self.bad = {"line 1": {"match": 0.2, "issues": ["mismatch"], "note": "a harbour, not a lake"}}

    def _run(self, outputs, ask=None, inp=None, pics=None, **flags):
        calls = []

        def fake_render(doc, path, **kw):
            calls.append(copy.deepcopy(doc))
            out = outputs[min(len(calls), len(outputs)) - 1]
            if isinstance(out, Exception):
                raise out if not callable(getattr(out, "for_doc", None)) else out.for_doc(doc)
            shutil.copy(out, path)
            return path
        work = tempfile.mkdtemp()
        ctx = _Review(ask or fake_vision(self.bad), pics=pics, **flags)
        with ctx, mock.patch.object(config, "RENDER_SEPARATE_AUDIO", False), \
                mock.patch.object(handler.renderer, "render", side_effect=fake_render), \
                mock.patch.object(handler.renderer, "normalize_loudness", return_value=False), \
                mock.patch.object(handler.timeline, "relevel_to_voice"), \
                mock.patch.object(handler, "_keep_render"), \
                mock.patch.object(handler.r2, "enabled", return_value=False):
            out = handler.do_render(self.doc, {"return_video": True, **(inp or {})}, work, lambda *a, **k: None)
        return out, calls, ctx

    def _final(self, out) -> bytes:
        return base64.b64decode(out["video_b64"])

    def test_a_swapped_clip_means_one_more_render_and_the_report_rides_with_the_video(self):
        out, calls, ctx = self._run([self.clean, self.clean])
        self.assertEqual(len(calls), 2)                                           # the one second render
        self.assertEqual(calls[1]["scenes"][1]["media"]["url"], self.alt)
        self.assertEqual(calls[0]["scenes"][1]["media"]["url"], _clip("e2e_1.mp4", 4.0))
        self.assertEqual(len(ctx.ask.calls), 1)
        rev = out["review"]
        self.assertEqual(rev["summary"], "AI review: 2/3 scenes fit the narration, 1 clip swapped")
        self.assertTrue(rev["rerendered"])
        self.assertEqual(self.doc["meta"]["review"]["summary"], rev["summary"])
        self.assertEqual(out["quality"]["render"]["kept"], "repaired")
        self.assertEqual(out["quality"]["render"]["askedBy"], "the AI review")

    def test_the_gates_repair_and_the_reviews_fix_share_one_second_render(self):
        out, calls, _ctx = self._run([self.black, self.clean])
        self.assertEqual(len(calls), 2)                                           # never a third
        self.assertTrue(out["quality"]["render"]["rerendered"])
        self.assertEqual(out["quality"]["render"]["fixed"], 1)                      # the black stretch
        self.assertEqual(calls[1]["scenes"][1]["media"]["url"], self.alt)          # and the swap, in the same draw
        self.assertEqual(out["review"]["fixed"][0]["scene"], "s0001")

    def test_a_scene_the_gate_replaces_is_not_judged_again_on_its_old_picture(self):
        black_mid = _video("e2e_black_mid.mp4", [("moving", 2.0), ("black", 2.0), ("moving", 2.0)])   # scene 2 is black
        asked = []
        out, calls, ctx = self._run([black_mid, self.clean], pics=_frames_from(asked=asked))
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(calls[1]["scenes"]), 2)                             # the gate merged the black scene away
        texts = [p["text"] for p in ctx.ask.calls[0][1]["content"] if p.get("type") == "text"]
        self.assertFalse(any("line 1" in t for t in texts))                       # the gate's scene left out
        # Its neighbours grew over its time; their frames are still the ones the first render drew.
        self.assertEqual(asked, [[30, 150]])
        self.assertEqual(out["review"]["fixed"], [])
        self.assertNotIn(self.alt, [s["media"].get("url") for s in calls[1]["scenes"]])

    def test_when_the_second_render_is_already_spent_the_review_only_lists(self):
        class Named(Exception):
            def for_doc(self, doc):
                served = os.path.basename(doc["scenes"][2]["media"]["url"])
                return render.RenderError(f"remotion render failed (exit 1): Error: Could not extract frame from "
                                          f"http://127.0.0.1:61234/_extra/{served} at time 1.2")
        out, calls, _ctx = self._run([Named(), self.clean])
        self.assertEqual(len(calls), 2)                                           # the failed draw and its repair
        self.assertEqual(calls[1]["scenes"][1]["media"]["url"], _clip("e2e_1.mp4", 4.0))   # not swapped
        self.assertEqual(out["review"]["fixed"], [])
        self.assertEqual(out["review"]["left"][0]["why"], "the one second render was already used")
        self.assertIn("1 left for you", out["review"]["summary"])

    def test_a_worse_second_render_is_not_kept_and_the_swap_is_taken_back(self):
        out, calls, _ctx = self._run([self.clean, self.worse])
        self.assertEqual(len(calls), 2)
        self.assertEqual(out["quality"]["render"]["kept"], "first")
        with open(self.clean, "rb") as fh:
            self.assertEqual(self._final(out), fh.read())
        self.assertEqual(self.doc["scenes"][1]["media"]["url"], _clip("e2e_1.mp4", 4.0))
        self.assertEqual(out["review"]["fixed"], [])
        self.assertIn("first one is kept", out["review"]["left"][0]["why"])

    def test_a_second_render_that_breaks_leaves_the_first_and_takes_the_swap_back(self):
        out, calls, _ctx = self._run([self.clean, render.RenderError("chrome crashed")])
        self.assertEqual(len(calls), 2)
        with open(self.clean, "rb") as fh:
            self.assertEqual(self._final(out), fh.read())
        self.assertEqual(self.doc["scenes"][1]["media"]["url"], _clip("e2e_1.mp4", 4.0))
        self.assertIn("second render failed", out["review"]["left"][0]["why"])

    def test_nothing_to_fix_means_no_second_render(self):
        out, calls, _ctx = self._run([self.clean], ask=fake_vision())
        self.assertEqual(len(calls), 1)
        self.assertEqual(out["review"]["summary"], "AI review: 3/3 scenes fit the narration, nothing to fix")
        self.assertFalse(out["quality"]["render"].get("rerendered"))

    def test_the_review_switched_off_is_exactly_the_render_without_it(self):
        # The same renders twice: AI_REVIEW off, and the review taken out of the handler altogether
        # (as before it was built) - a clean first render, and one the gate repairs and draws again.
        class NoReview:
            def __init__(self, *a, **k):
                pass

            def plan(self):
                pass

            def after_render(self, *a, **k):
                return False

            def after_rerender(self, *a, **k):
                pass

            def rerender_failed(self, *a, **k):
                pass

            def finish(self):
                return None

        def shape(doc, out, calls):
            scenes = [(s.get("id"), s.get("startFrame"), s.get("durationInFrames"), (s.get("media") or {}).get("type"),
                       (s.get("media") or {}).get("url"), s.get("text"), s.get("reviewReason")) for s in doc["scenes"]]
            drawn = [[((s.get("media") or {}).get("url"), s.get("durationInFrames")) for s in c["scenes"]]
                     for c in calls]
            render_info = {k: v for k, v in out["quality"]["render"].items() if k != "seconds"}
            return (scenes, doc.get("overlays"), sorted(doc["meta"]), sorted(out), out["quality"]["summary"],
                    render_info, out["video_b64"], drawn)
        start = copy.deepcopy(self.doc)
        asked = []
        for outputs in ([self.clean], [self.black, self.clean]):
            self.doc = copy.deepcopy(start)
            out, calls, ctx = self._run(outputs, pics=_frames_from(asked=asked), AI_REVIEW=False)
            off = shape(self.doc, out, calls)
            self.assertEqual(ctx.ask.calls, [])
            self.assertNotIn("review", out)
            self.assertNotIn("review", self.doc["meta"])
            self.doc = copy.deepcopy(start)
            with mock.patch.object(handler.review, "Review", NoReview):
                out, calls, _ctx = self._run(outputs, pics=_frames_from(asked=asked))
            self.assertEqual(off, shape(self.doc, out, calls), f"{len(outputs)} render(s)")
        self.assertEqual(asked, [])                                                 # not one frame taken

    def test_a_review_that_only_lists_still_rides_with_the_video(self):
        out, calls, _ctx = self._run([self.clean], AI_REVIEW_FIX=False)
        self.assertEqual(len(calls), 1)
        self.assertEqual(out["review"]["left"][0]["why"], "fixing is switched off (AI_REVIEW_FIX)")
        self.assertFalse(out["review"]["rerendered"])


class HandlerWiring(unittest.TestCase):
    def test_a_build_keeps_the_review_with_its_timeline_and_marks_the_scenes(self):
        from tests.test_pipeline import build_doc
        doc = build_doc(n=2, seconds=3.0)
        reviewed = {"summary": "AI review: 1/2 scenes fit the narration, 1 clip swapped",
                    "fixed": [{"scene": doc["scenes"][1]["id"], "issue": "mismatch", "note": "a harbour",
                               "how": "swapped for its choice 1"}], "left": []}

        def fake_render(d, inp, work, report, split=False):
            return {"video_url": "u", "duration": 6, "quality": {"summary": "Quality check: 2/2 scenes OK", "repairs": []},
                    "review": reviewed}
        with mock.patch.object(handler, "do_plan", return_value=doc), \
                mock.patch.object(handler, "_require_youtube"), mock.patch.object(handler, "_require_ai_credit"), \
                mock.patch.object(handler, "do_render", side_effect=fake_render), \
                mock.patch.object(handler, "publish_media"), mock.patch.object(handler.storage, "patch_project"):
            out = handler.handler({"id": "job-r", "input": {"action": "build", "project_id": "p1"}})
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["timeline"]["meta"]["review"], reviewed)
        self.assertEqual(out["review"], reviewed)
        self.assertIn("AI review changed this scene", out["timeline"]["scenes"][1]["reviewReason"])

    def test_the_review_flags_can_be_set_per_job(self):
        prev = handler._apply_config({"AI_REVIEW": "1", "AI_REVIEW_FIX": "0", "AI_REVIEW_MAX_CALLS": "3"})
        try:
            self.assertTrue(config.AI_REVIEW)
            self.assertFalse(config.AI_REVIEW_FIX)
            self.assertEqual(config.AI_REVIEW_MAX_CALLS, 3)
        finally:
            handler._restore_config(prev)
        self.assertFalse(config.AI_REVIEW)                                         # off by default


# --------------------------------------------------------------------------- #
# ffmpeg for real: the one-pass frame grab and the sound measurement
# --------------------------------------------------------------------------- #

@unittest.skipUnless(FFMPEG, "needs ffmpeg")
class WithFfmpeg(unittest.TestCase):
    def test_each_frame_is_the_one_asked_for(self):
        path = _video("ff_frames.mp4", [("moving", 6.0)])
        self.assertEqual(review.probe(path)["fps"], 30.0)
        pics = review.grab_frames(path, [0, 15, 75, 150, 9999], os.path.join(MEDIA, "grab"), width=96)
        self.assertEqual(sorted(pics), [0, 15, 75, 150])                            # past the end: no file
        from PIL import Image, ImageChops, ImageStat

        def exact(n: int) -> str:
            out = os.path.join(MEDIA, f"exact_{n}.jpg")
            _ff("-i", path, "-vf", f"select=eq(n\\,{n}),scale=96:-2", "-frames:v", "1", "-q:v", "5", out)
            return out

        def diff(a: str, b: str) -> float:
            with Image.open(a) as x, Image.open(b) as y:
                return sum(ImageStat.Stat(ImageChops.difference(x.convert("RGB"), y.convert("RGB"))).mean)
        for n in (15, 75):
            self.assertLess(diff(pics[n], exact(n)), 1.0, n)                        # frame n itself...
            self.assertGreater(diff(pics[n], exact(n + 1)), diff(pics[n], exact(n)) + 1.0, n)   # ...not n + 1
        with Image.open(pics[15]) as im:
            self.assertEqual(im.size[0], 96)
        self.assertEqual(review.grab_frames(path, [], os.path.join(MEDIA, "grab")), {})
        self.assertEqual(review.grab_frames(os.path.join(MEDIA, "missing.mp4"), [1], os.path.join(MEDIA, "grab")), {})

    def test_a_long_list_of_frames_is_no_problem(self):
        # One ffmpeg pass with select='eq(n,..)+...' failed past ~100 frames ("Cannot allocate memory")
        # - every real video asks for more than that.
        path = _video("ff_many.mp4", [("moving", 6.0)])
        pics = review.grab_frames(path, list(range(0, 180, 1))[:150], os.path.join(MEDIA, "grab_many"), width=64)
        self.assertEqual(len(pics), 150)

    def test_the_sound_is_measured_in_windows_with_its_loudness_and_peak(self):
        path = _video("ff_sound.mp4", [("moving", 4.0)])
        m = review.measure_audio(path)
        self.assertTrue(m["ok"], m["why"])
        self.assertGreater(len(m["windows"]), 60)                                  # 4 s in ~50 ms windows
        t, rms, peak = m["windows"][10]
        self.assertTrue(-40 < rms < 0 and peak is not None and rms <= peak + 0.01, (rms, peak))
        self.assertIsNotNone(m["lufs"])
        self.assertIsNotNone(m["truePeak"])
        silent = _video("ff_silent.mp4", [("moving", 4.0)], audio="silent")
        m = review.measure_audio(silent)
        self.assertTrue(m["ok"])
        self.assertTrue(all(r <= -90 for _t, r, _p in m["windows"]))

    def test_a_whole_review_on_a_real_file_with_a_fake_model(self):
        # Scenes 1 and 3 are the same test pattern, scene 2 colour bars: the frames themselves say "repeat".
        path = _video("ff_whole.mp4", [("moving", 3.0), ("bars", 3.0), ("moving", 3.0)], audio="silent")
        doc = doc_of([scene(i, video(_clip(f"w{i}.mp4", 4.0), 4.0)) for i in range(3)])
        with mock.patch.multiple(config, AI_REVIEW=True, AI_REVIEW_FIX=True, AI_REVIEW_AUDIO=True), \
                mock.patch.object(review, "_ask", side_effect=fake_vision()), \
                mock.patch.object(review, "_vision_on", return_value=True):
            rev = review.Review(doc, tempfile.mkdtemp())
            self.assertFalse(rev.after_render(path, FakeGate(), may_fix=True))     # no other choice: listed
        report = rev.finish()
        self.assertEqual(report["summary"], "AI review: 3/3 scenes fit the narration, 1 left for you")
        self.assertEqual([(r["scene"], r["issue"], r["note"]) for r in report["left"]],
                         [("s0002", "repeat", "looks the same as the shot at 0:00")])
        self.assertTrue(report["audio"]["checked"])
        self.assertGreater(report["seconds"], 0)
        self.assertIn("frames", report["timings"])


if __name__ == "__main__":
    unittest.main()
