"""
Shorts (owner-approved 2026-10-07): the best 30-60 s moments of a finished video, cut from its own timeline
as 9:16 Shorts - framed shot by shot for a phone (crop on the subject, or the whole picture in a band over a
blurred copy: graphics, news logos and lettering are never cut off), clean white captions, a hook line.
Offline: no network, no R2, no RunPod; renders are stubbed (a real one is a local scratchpad run).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import shorts  # noqa: E402

REMOTION = os.path.join(ROOT, "remotion")
FPS = 60          # the long video's own rate (the owner's videos are often 60 fps)


def doc_for(sentences, gap=0.5, per_word=0.3, fps=FPS, scene_media=None, overlays=None, title="", extra=None):
    """
    A finished video's document: one scene per sentence, words timed per_word apart (seconds), the scenes
    tiling the narration at `fps`. scene_media(i) -> media dict for scene i.
    """
    t = 0.2
    scenes = []
    for i, text in enumerate(sentences):
        words = []
        for tok in text.split():
            words.append({"text": tok, "start": round(t, 3), "end": round(t + per_word - 0.04, 3)})
            t += per_word
        start = words[0]["start"] if i else 0.0
        t += gap
        scenes.append({"id": f"s{i:04d}", "text": text, "words": words, "_start": start, "_end": t})
    total = int(round(t * fps)) + fps
    out = []
    for i, sc in enumerate(scenes):
        a = int(round(sc["_start"] * fps))
        b = int(round(scenes[i + 1]["_start"] * fps)) if i + 1 < len(scenes) else total
        media = (scene_media(i) if scene_media else None) or {
            "type": "video", "url": f"https://pub-x.r2.dev/projects/p/media/s{i:04d}.mp4",
            "thumbnail": f"https://pub-x.r2.dev/projects/p/thumbs/s{i:04d}.jpg", "source": "youtube",
            "clipSeconds": 6.0}
        out.append({"id": sc["id"], "startFrame": a, "durationInFrames": b - a, "text": sc["text"], "words": sc["words"],
                    "media": media, "transition": "flash" if i else "none", "visualType": "footage"})
    doc = {"fps": fps, "width": 1920, "height": 1080, "durationInFrames": total, "scenes": out,
           "overlays": overlays or [], "sfx": [], "audio": {"url": "https://x/v.m4a", "volume": 1, "boostDb": 2},
           "bgm": {"url": "bgm://investigative-v5", "volume": 0.5, "track": "investigative-v5"},
           "music": {"duck": 0.8, "levels": {"mode": "flat", "speech": 0.5}, "sections": []},
           "captions": {"enabled": True, "style": "netflix", "accent": "#EF4444"}, "grade": {"preset": "documentary"},
           "lookSounds": {"intensity": 0.8}, "sfxVolume": 0.4, "sfxEnabled": True,
           "meta": {"voiceLufs": -20, "story": {"places": ["Biscuit Basin", "Lake Mead"], "people": []}},
           "title": title}
    doc.update(extra or {})
    return doc


PLAIN = "The water level kept moving through the week and the crews kept watching it closely."
STORY = (
    ["And then they went back to the office for the rest of the afternoon."] * 3
    + ["At 10:19 on a Tuesday morning, the ground at Biscuit Basin blew open.",
       "A column of boiling water climbed about 100 feet over the pool.",
       "Nobody on the boardwalk had any warning at all.",
       "Rocks the size of fists were landing on the planks within seconds.",
       "The planks under the blast were buried in mud and gravel.",
       "It was the biggest explosion in the basin in decades.",
       "Scientists said the system had been building pressure for years.",
       "So was the supervolcano waking up?"]
    + [PLAIN] * 6
    + ["Thanks for watching, and subscribe for the next video about Lake Mead."] * 2
)


class Sentences(unittest.TestCase):
    def test_whisper_tails_go_back_on_their_word(self):
        doc = doc_for(["At 10 .19 the level hit 1 ,000 feet, a record -setting day."])
        words = [w["text"] for w in shorts.words_of(doc)]
        self.assertIn("10.19", words)
        self.assertIn("1,000", words)
        self.assertIn("record-setting", words)

    def test_abbreviations_and_initials_do_not_end_a_sentence(self):
        doc = doc_for(["Dr. Smith lives on Mt. Hood in the U.S. and works for J. R. Lee.", "Then it rained."])
        sents = shorts.sentences_of(doc)
        self.assertEqual(len(sents), 2, [s["text"] for s in sents])
        self.assertTrue(sents[0]["text"].startswith("Dr. Smith"))

    def test_a_long_unpunctuated_run_is_cut_at_a_pause(self):
        long_line = " ".join(["word"] * 90)
        doc = doc_for([long_line], gap=0.5)
        # Two pauses inside: words 45 and 46 are a second apart.
        words = doc["scenes"][0]["words"]
        for w in words[45:]:
            w["start"] += 1.0
            w["end"] += 1.0
        self.assertGreaterEqual(len(shorts.sentences_of(doc)), 2)


class Scoring(unittest.TestCase):
    def test_a_line_leaning_on_what_came_before_opens_worse(self):
        strong = shorts.opener_score(shorts.line_features("A column of boiling water climbed about 100 feet."))
        leaning = shorts.opener_score(shorts.line_features("And that's why they climbed about 100 feet."))
        pronoun = shorts.opener_score(shorts.line_features("It climbed about 100 feet."))
        self.assertGreater(strong, leaning + 0.3)
        self.assertGreater(strong, pronoun + 0.2)

    def test_numbers_superlatives_stakes_and_questions_open_better(self):
        plain = shorts.opener_score(shorts.line_features("The crews kept watching the water through the week."))
        for line in ("The level dropped 150 feet in twenty years.", "It is the deadliest flood on record.",
                     "Nobody had any warning before it exploded.", "Why did the lake vanish?"):
            self.assertGreater(shorts.opener_score(shorts.line_features(line)), plain, line)

    def test_the_best_moment_is_the_story_not_the_filler_or_the_outro(self):
        doc = doc_for(STORY)
        best = shorts.pick(doc, 1)[0]
        ctx = shorts._Ctx(doc)
        self.assertTrue(ctx.sents[best["firstSentence"]]["text"].startswith(("At 10:19", "A column")),
                        best["firstLine"])
        self.assertGreaterEqual(best["end"] - best["start"], 15)

    def test_moments_are_whole_sentences_inside_the_limits_and_never_overlap(self):
        doc = doc_for(STORY * 3)
        cands = shorts.candidates(doc, min_s=20, max_s=40, limit=8)
        self.assertGreaterEqual(len(cands), 3)
        for m in cands:
            self.assertGreaterEqual(m["end"] - m["start"], 20 - 1e-6)
            self.assertLessEqual(m["end"] - m["start"], 40 + 1e-6)
            self.assertTrue(0 <= m["score"] <= 100)
            self.assertLessEqual(len(m["reasons"]), 4)
            self.assertLessEqual(len(m["hook"]), 70)
        for i, a in enumerate(cands):
            for b in cands[i + 1:]:
                self.assertFalse(a["start"] < b["end"] and b["start"] < a["end"], (a, b))
        self.assertEqual(cands, sorted(cands, key=lambda m: -m["score"]))

    def test_pick_keeps_to_one_to_five(self):
        doc = doc_for(STORY * 4)
        self.assertLessEqual(len(shorts.pick(doc, 9, min_s=10, max_s=30)), 5)
        self.assertEqual(len(shorts.pick(doc, 0, min_s=10, max_s=30)), shorts.DEFAULT_COUNT)

    def test_a_window_with_a_call_to_action_scores_lower(self):
        doc = doc_for(STORY)
        ctx = shorts._Ctx(doc)
        last = len(ctx.sents) - 1
        with_cta, _, parts = shorts.score_window(ctx, last - 3, last)
        without, _, _ = shorts.score_window(ctx, last - 5, last - 2)
        self.assertTrue(parts["cta"])
        self.assertLess(with_cta, without)


class Hooks(unittest.TestCase):
    def test_a_clause_that_stands_alone_is_offered(self):
        opts = shorts._line_options("At 10:19 on a Tuesday morning, the ground at Biscuit Basin blew open.")
        self.assertIn("The ground at Biscuit Basin blew open", opts)
        self.assertNotIn("At 10:19 on a Tuesday morning", opts)

    def test_the_hook_is_a_short_striking_line_without_a_leading_and(self):
        doc = doc_for(STORY, title="Yellowstone Just EXPLODED Again — Boiling Water Shoots 100 FEET")
        ctx = shorts._Ctx(doc)
        hook, kicker, title = shorts.hook_for(ctx, 3, 10)
        self.assertTrue(hook)
        self.assertLessEqual(len(hook), 70)
        self.assertFalse(hook.lower().startswith(("and ", "but ", "so ")), hook)
        self.assertFalse(hook.endswith("."), hook)
        self.assertEqual(kicker, "BISCUIT BASIN")
        self.assertTrue(title)

    def test_a_moment_with_no_good_line_falls_back_on_the_title(self):
        doc = doc_for([PLAIN] * 10, title="Yellowstone Just EXPLODED Again — Boiling Water Shoots 100 FEET")
        ctx = shorts._Ctx(doc)
        hook, _, _ = shorts.hook_for(ctx, 0, 5)
        self.assertEqual(hook, "Yellowstone Just Exploded Again")

    def test_the_subject_is_the_titles_name_the_narration_uses(self):
        doc = doc_for(["Later the town of Nairobi grew.", "Nairobi was busy.", "Barack Obama wrote a book.",
                       "Then Obama went home.", "Nairobi again."] * 2,
                      title="Why Barack Obama's Brothers HATED Him So Much")
        self.assertEqual(shorts._Ctx(doc).subject(), "Barack Obama")


class Snap(unittest.TestCase):
    def test_a_sent_moment_lands_on_whole_words_and_never_takes_a_neighbours(self):
        doc = doc_for(STORY)
        ctx = shorts._Ctx(doc)
        s3 = ctx.sents[3]
        s5 = ctx.sents[5]
        start, end = shorts.snap(ctx, s3["start"] + 0.05, s5["end"] - 0.05)
        self.assertLessEqual(start, s3["start"])
        self.assertGreater(start, ctx.words[s3["w0"] - 1]["end"])
        self.assertGreaterEqual(end, s5["end"])
        self.assertLess(end, ctx.words[s5["w1"] + 1]["start"])


class Stage(unittest.TestCase):
    def setUp(self):
        overlays = [
            {"type": "motion", "variant": "kt-number", "startFrame": 30 * FPS, "durationInFrames": 4 * FPS},
            # Mostly before the window: dropped.
            {"type": "motion", "variant": "kt-chip", "startFrame": 5 * FPS, "durationInFrames": 6 * FPS},
            # Half in it: kept, from the Short's first frame.
            {"type": "motion", "variant": "kt-date", "startFrame": int(8.5 * FPS), "durationInFrames": 4 * FPS},
        ]
        self.doc = doc_for(STORY, overlays=overlays)
        self.doc["sfx"] = [{"name": "whoosh-fast", "startFrame": 12 * FPS, "volume": 0.3, "durationFrames": 28,
                            "trimFrames": 4, "kind": "transition"},
                           {"name": "whoosh-fast", "startFrame": 2 * FPS, "volume": 0.3}]

    def test_the_stage_tiles_the_short_from_frame_zero_at_its_own_rate(self):
        st = shorts.stage_doc(self.doc, 10.5, 40.0, fps=30, audio_url="/w/narration.wav")
        self.assertEqual(st["fps"], 30)
        self.assertEqual((st["width"], st["height"]), (1920, 1080))
        self.assertEqual(st["durationInFrames"], round(29.5 * 30))
        cursor = 0
        for sc in st["scenes"]:
            self.assertEqual(sc["startFrame"], cursor)
            self.assertGreater(sc["durationInFrames"], 0)
            cursor += sc["durationInFrames"]
        self.assertEqual(cursor, st["durationInFrames"])
        self.assertEqual(st["scenes"][0]["transition"], "none")
        for sc in st["scenes"]:
            for w in sc["words"]:
                self.assertGreater(w["end"], 0)
                self.assertLess(w["start"], 29.5)

    def test_graphics_sounds_music_and_the_narration_follow_the_window(self):
        st = shorts.stage_doc(self.doc, 10.5, 40.0, fps=30, audio_url="/w/narration.wav")
        variants = [o["variant"] for o in st["overlays"]]
        self.assertEqual(sorted(variants), ["kt-date", "kt-number"])
        num = next(o for o in st["overlays"] if o["variant"] == "kt-number")
        self.assertEqual(num["startFrame"], round((30 - 10.5) * 30))
        self.assertEqual(num["durationInFrames"], 4 * 30)
        date = next(o for o in st["overlays"] if o["variant"] == "kt-date")
        self.assertEqual(date["startFrame"], 0)
        self.assertEqual([fx["startFrame"] for fx in st["sfx"]], [round(1.5 * 30)])
        self.assertEqual(st["sfx"][0]["durationFrames"], 14)
        self.assertEqual(st["sfx"][0]["trimFrames"], 2)
        self.assertEqual(st["audio"]["url"], "/w/narration.wav")
        self.assertNotIn("boostDb", st["audio"])
        self.assertFalse(st["captions"]["enabled"])
        sections = st["music"]["sections"]
        self.assertEqual(sections[-1]["endFrame"], st["durationInFrames"])
        self.assertEqual(st["music"]["duck"], 0.8)
        self.assertEqual(st["grade"], {"preset": "documentary"})

    def test_a_sliver_of_the_shot_before_or_after_never_flashes(self):
        second = self.doc["scenes"][4]
        start = second["startFrame"] / FPS - 0.12            # a breath before the moment's first word
        nxt = self.doc["scenes"][9]
        end = nxt["startFrame"] / FPS + 0.1                  # a breath after its last
        st = shorts.stage_doc(self.doc, start, end, fps=30)
        self.assertEqual(st["scenes"][0]["id"], second["id"])
        self.assertEqual(st["scenes"][0]["startFrame"], 0)
        self.assertEqual(st["scenes"][-1]["id"], self.doc["scenes"][8]["id"])
        self.assertEqual(st["scenes"][-1]["startFrame"] + st["scenes"][-1]["durationInFrames"], st["durationInFrames"])

    def test_no_music_and_the_hook_preview_keeps_the_videos_captions(self):
        st = shorts.stage_doc(self.doc, 0, 30, music=False, keep_captions=True)
        self.assertIsNone(st["music"])
        self.assertIsNone(st["bgm"])
        self.assertTrue(st["captions"]["enabled"])

    def test_caption_words_are_on_the_shorts_clock(self):
        ctx = shorts._Ctx(self.doc)
        words = shorts.caption_words(ctx, 10.5, 20.0)
        self.assertTrue(words)
        self.assertGreaterEqual(words[0]["start"], 0)
        self.assertLessEqual(words[-1]["end"], 9.5)


class Framing(unittest.TestCase):
    def scene(self, media, frame="full"):
        return {"id": "s1", "startFrame": 0, "durationInFrames": 150, "media": media, "frame": frame}

    def test_what_must_not_be_cut_is_fitted(self):
        clip = {"type": "video", "url": "/a.mp4"}
        self.assertEqual(shorts.scene_framing(self.scene({"type": "animation", "url": ""}), None)["mode"], "fit")
        self.assertEqual(shorts.scene_framing(self.scene(clip, frame="window"), None)["mode"], "fit")
        news = {**clip, "attribution": "Geyser blast caught on camera - FOX Weather"}
        self.assertEqual(shorts.scene_framing(self.scene(news), None)["mode"], "fit")
        lettering = {"kind": "none", "overlay": True, "aspect": 16 / 9}
        self.assertEqual(shorts.scene_framing(self.scene(clip), lettering)["mode"], "fit")
        wide = {"kind": "object", "confidence": 0.9, "aspect": 16 / 9, "box": {"x": 0.1, "y": 0.3, "w": 0.8, "h": 0.4}}
        self.assertEqual(shorts.scene_framing(self.scene(clip), wide)["mode"], "fit")

    def test_a_subject_the_window_holds_is_cropped_on(self):
        clip = {"type": "video", "url": "/a.mp4"}
        face = {"kind": "face", "confidence": 0.9, "aspect": 16 / 9, "box": {"x": 0.62, "y": 0.2, "w": 0.12, "h": 0.3}}
        f = shorts.scene_framing(self.scene(clip), face)
        self.assertEqual(f["mode"], "crop")
        self.assertAlmostEqual(f["cx"], 0.68, places=2)
        edge = {"kind": "face", "confidence": 0.9, "aspect": 16 / 9, "box": {"x": 0.95, "y": 0.2, "w": 0.05, "h": 0.2}}
        self.assertLessEqual(shorts.scene_framing(self.scene(clip), edge)["cx"], 1 - shorts.WINDOW / 2 + 1e-9)
        self.assertEqual(shorts.scene_framing(self.scene(clip), None), {"mode": "crop", "cx": 0.5, "why": "centre"})

    def test_no_push_in_for_a_moment_before_or_after_a_graphic(self):
        stage = {"fps": 30, "durationInFrames": 300,
                 "scenes": [{"id": "a", "startFrame": 0, "durationInFrames": 300, "media": {"type": "video", "url": "/a"}}],
                 "overlays": [{"startFrame": 20, "durationInFrames": 90}]}
        spans = shorts.plan_framing(stage, {})
        # The first 0.5 s would have been cropped and then pulled out: the Short opens fitted instead.
        self.assertEqual((spans[0]["from"], spans[0]["mode"], spans[0]["ease"]), (0, "fit", 0))
        self.assertEqual(spans[1]["mode"], "crop")
        self.assertEqual(spans[1]["ease"], shorts.EASE_FRAMES)

    def test_a_letterboxed_shot_is_fitted_with_its_bars_left_out(self):
        clip = {"type": "video", "url": "/a.mp4"}
        boxed = {"kind": "none", "aspect": 16 / 9, "why": "letterbox bars",
                 "bars": {"top": 0.12, "bottom": 0.12, "left": 0.0, "right": 0.0}}
        f = shorts.scene_framing(self.scene(clip), boxed)
        self.assertEqual((f["mode"], f["clip"]), ("fit", [0.12, 0.12]))
        # A 4:3 source cover-fitted to 16:9 loses part of its bars to the fit.
        four3 = {"kind": "none", "aspect": 4 / 3, "bars": {"top": 0.2, "bottom": 0.2}}
        f = shorts.scene_framing(self.scene(clip), four3)
        self.assertAlmostEqual(f["clip"][0], (0.2 - 0.125) / 0.75, places=3)
        stage = {"fps": 30, "durationInFrames": 300,
                 "scenes": [{"id": "a", "startFrame": 0, "durationInFrames": 300, "media": clip}],
                 "overlays": [{"startFrame": 120, "durationInFrames": 60}]}
        spans = shorts.plan_framing(stage, {"a": boxed})
        self.assertEqual(spans[0]["clip"], [0.12, 0.12])
        self.assertNotIn("clip", next(s for s in spans if s["why"] == "graphic on screen" or s["from"] >= 115))

    def test_looks_that_only_say_the_words_stay_out_of_a_short(self):
        self.assertTrue(shorts.says_words({"type": "motion", "variant": "kt-statement", "template": "KT_STATEMENT"}))
        self.assertTrue(shorts.says_words({"type": "chapter", "variant": "editorial"}))
        self.assertFalse(shorts.says_words({"type": "motion", "variant": "kt-number", "template": "KT_NUMBER"}))
        self.assertFalse(shorts.says_words({"type": "map"}))
        doc = doc_for(STORY, overlays=[
            {"type": "motion", "variant": "kt-statement", "template": "KT_STATEMENT", "startFrame": 12 * FPS, "durationInFrames": 120},
            {"type": "motion", "variant": "kt-number", "template": "KT_NUMBER", "startFrame": 14 * FPS, "durationInFrames": 120}])
        kept = shorts.stage_doc(doc, 10.0, 30.0, drop_text_looks=True)["overlays"]
        self.assertEqual([o["variant"] for o in kept], ["kt-number"])
        self.assertEqual(len(shorts.stage_doc(doc, 10.0, 30.0)["overlays"]), 2)   # the hook preview keeps its look

    def test_a_vertical_source_fills_the_frame_itself(self):
        clip = {"type": "video", "url": "/a.mp4"}
        tall = {"kind": "none", "aspect": 0.5625}
        self.assertEqual(shorts.scene_framing(self.scene(clip), tall)["mode"], "native")

    def test_a_graphic_mid_shot_eases_out_to_fit_and_back(self):
        stage = {"fps": 30, "durationInFrames": 300,
                 "scenes": [{"id": "a", "startFrame": 0, "durationInFrames": 200, "media": {"type": "video", "url": "/a"}},
                            {"id": "b", "startFrame": 200, "durationInFrames": 100, "media": {"type": "video", "url": "/b"}}],
                 "overlays": [{"startFrame": 90, "durationInFrames": 60}]}
        spans = shorts.plan_framing(stage, {})
        self.assertEqual(spans[0]["from"], 0)
        self.assertEqual(spans[-1]["to"], 300)
        for a, b in zip(spans, spans[1:]):
            self.assertEqual(a["to"], b["from"])
        modes = [(s["mode"], s["ease"]) for s in spans]
        self.assertEqual(modes[0], ("crop", 0))
        self.assertIn(("fit", shorts.EASE_FRAMES), modes)
        fit = next(s for s in spans if s["mode"] == "fit")
        self.assertEqual(fit["from"], 90 - round(0.15 * 30))
        back = spans[spans.index(fit) + 1]
        self.assertEqual((back["mode"], back["ease"]), ("crop", shorts.EASE_FRAMES))
        self.assertEqual(spans[-1]["ease"], 0)          # the cut into scene b snaps


def _ffmpeg():
    return shutil.which("ffmpeg") and shutil.which("ffprobe")


@unittest.skipUnless(_ffmpeg(), "needs ffmpeg")
class Run(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.voice = os.path.join(self.tmp, "voice.wav")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "sine=frequency=220:duration=40", "-ac", "1", self.voice], check=True)
        self.doc = doc_for(STORY, fps=30)
        self.calls = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def render(self, props, out, composition="Main", audio_to=None, **kw):
        self.calls.append({"props": props, "composition": composition})
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        f"color=c=gray:s={props['width']}x{props['height']}:d=2:r=30", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", out], check=True)
        shutil.copy2(self.voice, audio_to)
        return out

    def finalize(self, picture, sound, final):
        shutil.copy2(picture, final)
        return {"lufsIn": -16.0, "lufsTarget": -14.0, "gainApplied": True}

    def inp(self, **more):
        base = {"timeline": self.doc, "audio_url": self.voice, "title": "Yellowstone Just Exploded Again",
                "project_id": "2a2200b3-4066", "_render": self.render, "_finalize": self.finalize,
                "_fetch": lambda url, dest: (_ for _ in ()).throw(OSError("offline")),
                "_detect_clip": lambda path, shown, timeout=25.0: None, "_detect_still": lambda path: None}
        base.update(more)
        return base

    def test_a_moment_becomes_a_vertical_short(self):
        ctx = shorts._Ctx(self.doc)
        m = shorts.moment(ctx, 3, 9)
        out = shorts.run(self.inp(moment={**m, "hook": "The ground blew open", "kicker": "biscuit basin"},
                                  short_id="abc123"), self.tmp)
        self.assertTrue(out["ok"], out.get("error"))
        short = out["shorts"][0]
        self.assertEqual(short["short_id"], "abc123")
        self.assertEqual((short["width"], short["height"]), (1080, 1920))
        self.assertEqual(short["kicker"], "BISCUIT BASIN")
        self.assertTrue(os.path.isfile(short["local_path"]))
        self.assertTrue(short["local_poster"].endswith(".jpg") and os.path.isfile(short["local_poster"]))
        call = self.calls[0]
        self.assertEqual(call["composition"], "Short")
        props = call["props"]
        self.assertEqual((props["width"], props["height"], props["fps"]), (1080, 1920, 30))
        self.assertEqual(props["hook"]["text"], "The ground blew open")
        self.assertEqual(props["hook"]["frames"], round(shorts.HOOK_SECONDS * 30))
        self.assertTrue(props["captions"]["enabled"])
        self.assertGreaterEqual(props["captions"]["words"][0]["start"], 0)
        self.assertTrue(props["stage"]["audio"]["url"].endswith("narration.wav"))
        spans = props["framing"]
        self.assertEqual((spans[0]["from"], spans[-1]["to"]), (0, props["durationInFrames"]))
        # The clips could not be fetched offline: each holds its own still instead (never a failed render).
        self.assertTrue(all(sc["media"]["type"] == "image" for sc in props["stage"]["scenes"]))

    def test_with_no_moment_it_picks_its_own_and_says_which(self):
        out = shorts.run(self.inp(count=1), self.tmp)
        self.assertTrue(out["ok"], out.get("error"))
        self.assertEqual(len(out["shorts"]), 1)
        self.assertEqual(len(out["candidates"]), 1)
        self.assertNotIn("parts", out["candidates"][0])

    def test_the_hook_preview_is_the_long_videos_own_look(self):
        out = shorts.run(self.inp(aspect="landscape", moment={"start": 0, "end": 20}), self.tmp)
        self.assertTrue(out["ok"], out.get("error"))
        call = self.calls[0]
        self.assertEqual(call["composition"], "Main")
        self.assertEqual((call["props"]["width"], call["props"]["height"]), (1920, 1080))
        self.assertTrue(call["props"]["captions"]["enabled"])
        self.assertEqual(out["shorts"][0]["aspect"], "landscape")

    def test_saved_to_r2_under_the_shorts_own_keys(self):
        put = []

        def upload(path, key, content_type="video/mp4", content_disposition="", **kw):
            put.append((key, content_type, content_disposition))
            return "https://pub-x.r2.dev/" + key
        m = shorts.moment(shorts._Ctx(self.doc), 3, 9)
        with mock.patch("src.r2.enabled", return_value=True), mock.patch("src.r2.upload", side_effect=upload):
            out = shorts.run(self.inp(moment=m, short_id="s1", upload="r2"), self.tmp)
        self.assertTrue(out["ok"], out.get("error"))
        keys = [p[0] for p in put]
        self.assertEqual(keys, ["projects/2a2200b3-4066/shorts/s1.mp4", "projects/2a2200b3-4066/shorts/s1.jpg"])
        self.assertIn("attachment", put[0][2])
        self.assertIn("Short 1", put[0][2])
        short = out["shorts"][0]
        self.assertEqual(short["video_url"], "https://pub-x.r2.dev/projects/2a2200b3-4066/shorts/s1.mp4")
        self.assertNotIn("local_path", short)

    def test_what_it_refuses(self):
        m = shorts.moment(shorts._Ctx(self.doc), 3, 9)
        self.assertFalse(shorts.run(self.inp(moment={"start": 0, "end": 90}), self.tmp)["ok"])
        self.assertFalse(shorts.run(self.inp(moment=m, audio_url="", timeline={**self.doc, "audio": {}}), self.tmp)["ok"])
        bare = {**self.doc, "scenes": [{**sc, "words": []} for sc in self.doc["scenes"]]}
        self.assertFalse(shorts.run(self.inp(timeline=bare), self.tmp)["ok"])
        with mock.patch("src.r2.enabled", return_value=False):
            self.assertFalse(shorts.run(self.inp(moment=m, upload="r2"), self.tmp)["ok"])

    def test_no_two_players_ever_read_one_file_on_the_same_frames(self):
        clip = os.path.join(self.tmp, "clip.mp4")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc=s=320x180:d=3:r=30", "-pix_fmt", "yuv420p", clip], check=True)

        def fetch(url, dest):
            shutil.copyfile(clip, dest)
            return dest
        stage = shorts.stage_doc(self.doc, 3.0, 25.0, fps=30)
        for k, sc in enumerate(stage["scenes"]):
            if k % 2:
                sc["media"]["previewUrl"] = f"https://pub-x.r2.dev/previews/{sc['id']}.mp4"
        shorts.fetch_media(stage, self.tmp, time.time() + 60, fetch=fetch)
        for sc in stage["scenes"]:
            m = sc["media"]
            self.assertTrue(os.path.isfile(m["url"]))
            self.assertTrue(os.path.isfile(m["previewUrl"]))
            self.assertNotEqual(os.path.normcase(m["url"]), os.path.normcase(m["previewUrl"]))
            self.assertTrue(m["previewUrl"].endswith("-backdrop.jpg"))      # a still: one video per frame
        # A vertical shot plays its own file in the frame; the stage shows its still under it.
        spans = [{"from": 0, "to": stage["durationInFrames"], "mode": "native", "cx": 0.5, "scene": 0, "ease": 0}]
        own = stage["scenes"][0]["media"]["url"]
        shorts.native_media(stage, spans)
        self.assertEqual(spans[0]["media"]["url"], own)
        self.assertEqual(stage["scenes"][0]["media"]["type"], "image")
        self.assertTrue(stage["scenes"][0]["media"]["url"].endswith("-backdrop.jpg"))

    def test_the_handler_runs_it_and_never_writes_the_project(self):
        import handler
        with mock.patch.object(handler.shorts, "run", return_value={"ok": True, "shorts": []}) as run, \
                mock.patch.object(handler.storage, "patch_project") as patch:
            out = handler.handler({"id": "job-1", "input": {"action": "shorts", "project_id": "p1",
                                                            "timeline": self.doc}})
        self.assertTrue(out["ok"])
        self.assertEqual(out["action"], "shorts")
        self.assertEqual(run.call_count, 1)
        patch.assert_not_called()


class Renderer(unittest.TestCase):
    """remotion/src read as text, and the pure parts run under node."""

    def read(self, *parts):
        with open(os.path.join(REMOTION, "src", *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_the_composition_is_registered_with_the_props_size(self):
        root = self.read("Root.tsx")
        self.assertIn('id="Short"', root)
        self.assertIn("component={Short}", root)
        self.assertIn("props.durationInFrames", root[root.index('id="Short"'):])

    def test_the_short_draws_the_long_videos_main_on_a_stage_of_its_size(self):
        src = self.read("short", "Short.tsx")
        self.assertIn('import { Main } from "../Main"', src)
        self.assertIn("<Sequence width={STAGE_W} height={STAGE_H}", src)
        layout = self.read("short", "shortLayout.ts")
        self.assertIn("export const STAGE_W = 1920", layout)
        self.assertIn("export const STAGE_H = 1080", layout)
        self.assertEqual((shorts.STAGE_W, shorts.STAGE_H, shorts.SHORT_W, shorts.SHORT_H), (1920, 1080, 1080, 1920))

    def test_no_yellow_outlined_words(self):
        for name in ("ShortCaptions.tsx", "HookTitle.tsx"):
            src = self.read("short", name)
            src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)                # (the notes name what is banned)
            src = re.sub(r"(^|\s)//[^\n]*", r"\1", src)
            self.assertNotIn("WebkitTextStroke", src)
            self.assertNotRegex(src, r"#FFD400|#ffd400|yellow")
            self.assertNotIn("ANTON", src)


def _node():
    node = shutil.which("node")
    esbuild = os.path.join(REMOTION, "node_modules", "esbuild", "bin", "esbuild")
    return (node, esbuild) if node and os.path.isfile(esbuild) else (None, None)


HARNESS = """
import * as layout from "%(s)s/shortLayout";
import { shortCues } from "%(s)s/shortCues";
import * as fs from "fs";
const input = JSON.parse(fs.readFileSync(0, "utf-8"));
const out = input.map((c: any) => {
  switch (c.op) {
    case "view": return layout.viewAt(c.spans, c.frame, 1080, 1920);
    case "rect": return layout.stageRect(c.mode, c.cx, 1080, 1920, c.clip);
    case "band": return layout.bandRect(1080, 1920);
    case "cues": return shortCues(c.words, 30).map((q: any) => ({ from: q.from, to: q.to, lines: q.lines.map((l: any) => l.map((w: any) => w.text).join(" ")) }));
    default: return null;
  }
});
process.stdout.write(JSON.stringify(out));
"""

@unittest.skipUnless(all(_node()), "needs node and remotion's esbuild")
class Layout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node, esbuild = _node()
        cls.dir = tempfile.mkdtemp()
        s = os.path.join(REMOTION, "src", "short").replace("\\", "/")
        entry = os.path.join(cls.dir, "harness.ts")
        with open(entry, "w", encoding="utf-8") as fh:
            fh.write(HARNESS % {"s": s})
        cls.bundle = os.path.join(cls.dir, "harness.cjs")
        subprocess.run([node, esbuild, entry, "--bundle", "--platform=node", "--format=cjs", f"--outfile={cls.bundle}",
                        "--log-level=error"], check=True, cwd=REMOTION, timeout=180)
        cls.node = node

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def run_calls(self, *calls):
        run = subprocess.run([self.node, self.bundle], input=json.dumps(list(calls)), capture_output=True, text=True,
                             encoding="utf-8", timeout=120, check=True)
        return json.loads(run.stdout)

    def test_crop_fills_the_frame_on_the_subject_and_fit_is_the_band(self):
        crop, fit, edge, band = self.run_calls({"op": "rect", "mode": "crop", "cx": 0.5},
                                               {"op": "rect", "mode": "fit", "cx": 0.5},
                                               {"op": "rect", "mode": "crop", "cx": 0.99}, {"op": "band"})
        self.assertAlmostEqual(crop["h"], 1920)
        self.assertAlmostEqual(crop["w"], 1920 * 1920 / 1080, places=3)
        self.assertAlmostEqual(crop["x"] + crop["w"] / 2, 540, places=3)
        self.assertAlmostEqual(edge["x"], 1080 - edge["w"], places=3)        # never past the stage's edge
        self.assertEqual(fit, band)
        self.assertAlmostEqual(fit["w"], 1080)
        self.assertAlmostEqual(fit["h"], 607.5)

    def test_the_framing_eases_inside_a_shot_and_snaps_on_a_cut(self):
        spans = [{"from": 0, "to": 90, "mode": "crop", "cx": 0.5, "ease": 0},
                 {"from": 90, "to": 150, "mode": "fit", "cx": 0.5, "ease": 12},
                 {"from": 150, "to": 300, "mode": "crop", "cx": 0.3, "ease": 0}]
        before, start, mid, done, cut = self.run_calls(*[{"op": "view", "spans": spans, "frame": f}
                                                         for f in (89, 90, 96, 102, 150)])
        self.assertEqual(before["fit"], 0)
        self.assertTrue(0 < start["fit"] < mid["fit"] < 1)
        self.assertEqual(done["fit"], 1)
        self.assertEqual(cut["fit"], 0)
        self.assertNotAlmostEqual(cut["rect"]["x"], before["rect"]["x"])

    def test_a_letterboxed_band_centres_its_picture_and_eases_its_bars(self):
        plain, boxed = self.run_calls({"op": "rect", "mode": "fit", "cx": 0.5},
                                      {"op": "rect", "mode": "fit", "cx": 0.5, "clip": [0.12, 0.12]})
        self.assertAlmostEqual(boxed["h"], plain["h"])
        shown_top = boxed["y"] + 0.12 * boxed["h"]
        shown_h = boxed["h"] * 0.76
        self.assertAlmostEqual(shown_top + shown_h / 2, 0.43 * 1920, delta=1)
        spans = [{"from": 0, "to": 60, "mode": "crop", "cx": 0.5, "ease": 0},
                 {"from": 60, "to": 120, "mode": "fit", "cx": 0.5, "ease": 12, "clip": [0.1, 0.1]}]
        mid, done = self.run_calls({"op": "view", "spans": spans, "frame": 66}, {"op": "view", "spans": spans, "frame": 90})
        self.assertTrue(0 < mid["clip"][0] < 0.1)
        self.assertEqual(done["clip"], [0.1, 0.1])

    def test_captions_are_short_phone_lines_with_every_word_once(self):
        words, t = [], 0.0
        text = ("At 10:19 on a Tuesday morning the ground at Biscuit Basin blew open and a column of boiling "
                "water climbed about one hundred feet over Black Diamond Pool").split()
        for w in text:
            words.append({"text": w, "start": round(t, 2), "end": round(t + 0.28, 2)})
            t += 0.32
        cues = self.run_calls({"op": "cues", "words": words})[0]
        self.assertEqual(" ".join(" ".join(c["lines"]) for c in cues).split(), text)
        for c in cues:
            self.assertLessEqual(len(c["lines"]), 2)
            for line in c["lines"]:
                self.assertLessEqual(len(line), 18, line)
        for a, b in zip(cues, cues[1:]):
            self.assertLessEqual(a["to"], b["from"])


if __name__ == "__main__":
    unittest.main()
