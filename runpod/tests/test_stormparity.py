"""The laptop kit's rules on the server (src/stormdesk.py, stormledger, stormlooks, stormpieces, stormthumbs): offline, tiny clips."""
import datetime
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from PIL import Image

from src import config, stormdesk, stormledger, stormlooks, stormpieces, stormthumbs
from src.transcribe import Word

FPS = 30


def w(t, a, b):
    return {"text": t, "start": a, "end": b}


def words_of(text, start=0.0, each=0.4, gap_after=None):
    out, t = [], start
    for tok in text.split():
        out.append(Word(text=tok, start=t, end=t + each))
        t += each + 0.05
        if tok.endswith((".", "!", "?")):
            t += gap_after or 0.1
    return out


def vid_id(vid):
    return (vid + "___________")[:11]


def scene(i, start, n, vid="abc", at=0.0, ch="KSL News", **extra):
    vid = vid_id(vid)
    s = {"id": f"s{i}", "startFrame": start, "durationInFrames": n, "text": f"line {i}", "visualType": "footage",
         "media": {"type": "video", "url": f"/tmp/{vid}.mp4", "source": "youtube", "trimStart": 0.0, "clipSeconds": 60.0},
         "semanticMetadata": {"channel": ch, "sourceUrl": f"https://www.youtube.com/watch?v={vid}&t={int(at)}",
                              "moment": {"start": at}, "assetId": f"yt:{vid}@{int(at)}"}, "words": []}
    s.update(extra)
    return s


def doc_of(scenes):
    total = max(x["startFrame"] + x["durationInFrames"] for x in scenes)
    return {"fps": FPS, "durationInFrames": total, "width": 1920, "height": 1080, "scenes": scenes, "overlays": [],
            "audio": {"url": "x"}, "meta": {}}


class HookTests(unittest.TestCase):
    def test_three_hook_clips_about_twenty_seconds(self):
        ps = stormdesk.plan_pauses(words_of("Lake Mead went up again today. " * 40), 100.0, {"pauses": 0})
        hook = [p for p in ps if p.get("open")]
        self.assertEqual(len(hook), 3)
        self.assertAlmostEqual(sum(p["secs"] for p in hook), 20.0, delta=0.1)
        self.assertTrue(all(p["at"] == 0.0 for p in hook))

    def test_one_clip_when_asked_and_padded_words_shift_by_all_of_them(self):
        ps = stormdesk.plan_pauses(words_of("Lake Mead went up. " * 10), 40.0, {"pauses": 0, "hook_clips": 1, "open_seconds": 5})
        self.assertEqual(len(ps), 1)
        ps = stormdesk.plan_pauses(words_of("Lake Mead went up. " * 10), 40.0, {"pauses": 0})
        out = stormdesk.out_pauses(ps)
        self.assertAlmostEqual(out[-1]["t1"], 20.0, delta=0.01)
        self.assertAlmostEqual(stormdesk.shift(0.0, ps), 20.0, delta=0.01)

    def test_hook_tail_dissolves_from_the_last_hook_clip(self):
        d = doc_of([scene(0, 0, 200, "h1", openClip=True, natSound=True), scene(1, 200, 200, "h2", openClip=True, natSound=True),
                    scene(2, 400, 100, "story")])
        self.assertTrue(stormdesk.set_hook_tail(d))
        self.assertEqual(d["scenes"][2]["hookTail"]["src"], f"/tmp/{vid_id('h2')}.mp4")
        self.assertAlmostEqual(d["scenes"][2]["hookTail"]["ss"], 200 / 30.0, delta=0.01)
        d["scenes"][1]["media"]["clipSeconds"] = 6.8
        d["scenes"][2].pop("hookTail")
        self.assertFalse(stormdesk.set_hook_tail(d))


class StopTests(unittest.TestCase):
    def test_never_where_the_next_sentence_leans_on_this_one(self):
        a = {"text": "The lake rose two feet.", "end": 10.0}
        self.assertEqual(stormdesk.natural_stop(a, {"text": "And it kept rising.", "start": 10.3}), 0.0)
        self.assertEqual(stormdesk.natural_stop(a, {"text": "It kept rising.", "start": 10.3}), 0.0)
        self.assertEqual(stormdesk.natural_stop({"text": "So where is it coming from?", "end": 10.0},
                                                {"text": "The rivers below the dam.", "start": 10.3}), 0.0)

    def test_a_breath_and_a_new_point_score_higher(self):
        a = {"text": "The lake rose two feet.", "end": 10.0}
        low = stormdesk.natural_stop(a, {"text": "Crews worked overnight.", "start": 10.1})
        high = stormdesk.natural_stop(a, {"text": "Now here's the part nobody saw.", "start": 11.2})
        self.assertGreater(high, low)
        self.assertGreater(low, 0.0)


class TalkWindowTests(unittest.TestCase):
    def clip(self):
        return (words_of("rest of a sentence the fetch cut.", 0.0) +
                words_of("The water came up so fast. We had to get out of the car.", 3.0) +
                words_of("Then the road was gone and", 12.0))

    def test_whole_sentences_only_padded(self):
        win = stormdesk.talk_window(self.clip(), 14.0, "the water rose fast")
        self.assertIsNotNone(win)
        self.assertLessEqual(win["start"], 3.0)
        self.assertGreaterEqual(win["start"], 2.8)
        self.assertNotIn("rest of", win["text"])
        self.assertNotIn("road was gone", win["text"])
        self.assertIn("get out of the car.", win["text"])

    def test_nothing_whole_nothing_plays(self):
        self.assertIsNone(stormdesk.talk_window(words_of("all one cut sentence with no end", 0.0), 3.0))

    def test_never_over_fifteen_seconds(self):
        long = words_of("This sentence goes on. " * 30, 1.0)
        win = stormdesk.talk_window(long, 60.0)
        self.assertLessEqual(win["seconds"], 15.0)


class FitTests(unittest.TestCase):
    def test_a_pause_takes_its_clips_length_and_all_moves(self):
        s0 = scene(0, 0, 90, "a", words=[w("one", 1.0, 1.5)])
        p = scene(1, 90, 210, "p", natSound=True, _fitSecs=9.0)
        s2 = scene(2, 300, 90, "b", words=[w("two", 10.5, 11.0)])
        d = doc_of([s0, p, s2])
        pauses = [{"t0": 3.0, "t1": 10.0}]
        inp = {"_storm_pauses": [{"at": 3.0, "secs": 7.0}]}
        got = []
        self.assertEqual(stormdesk.apply_fits(d, pauses, inp, lambda plan: got.append(plan) or "https://new"), 1)
        self.assertEqual(p["durationInFrames"], 270)
        self.assertEqual(s2["startFrame"], 360)
        self.assertAlmostEqual(s2["words"][0]["start"], 12.5)
        self.assertEqual(d["durationInFrames"], 450)
        self.assertEqual(d["audio"]["url"], "https://new")
        self.assertAlmostEqual(got[0][0]["secs"], 9.0)
        self.assertAlmostEqual(pauses[0]["t1"], 12.0)
        self.assertNotIn("_fitSecs", p)

    def test_no_new_narration_nothing_moves(self):
        d = doc_of([scene(0, 0, 210, "p", natSound=True, _fitSecs=9.0), scene(1, 210, 90, "b")])
        pauses = [{"t0": 0.0, "t1": 7.0}]
        self.assertEqual(stormdesk.apply_fits(d, pauses, {"_storm_pauses": [{"at": 0.0, "secs": 7.0}]}, lambda _p: ""), 0)
        self.assertEqual(d["scenes"][1]["startFrame"], 210)
        self.assertEqual(d["durationInFrames"], 300)

    def test_a_slot_with_no_clip_closes(self):
        d = doc_of([scene(0, 0, 200, "h", natSound=True, openClip=True), scene(1, 200, 100, "a"), scene(2, 300, 100, "b"),
                    scene(3, 400, 200, "h3", natSound=True, openClip=True), scene(4, 600, 90, "c", words=[w("x", 20.5, 21.0)])])
        pauses = [{"t0": 0.0, "t1": 200 / 30.0, "open": True}, {"t0": 200 / 30.0, "t1": 400 / 30.0, "open": True},
                  {"t0": 400 / 30.0, "t1": 20.0, "open": True}]
        inp = {"_storm_pauses": [{"at": 0.0, "secs": 200 / 30.0}, {"at": 0.0, "secs": 200 / 30.0}, {"at": 0.0, "secs": 200 / 30.0}]}
        plans = []
        self.assertEqual(stormdesk.apply_fits(d, pauses, inp, lambda p: plans.append(p) or "u"), 1)
        self.assertEqual([s["id"] for s in d["scenes"]], ["s0", "s3", "s4"])
        self.assertEqual([s["startFrame"] for s in d["scenes"]], [0, 200, 400])
        self.assertEqual(d["durationInFrames"], 490)
        self.assertEqual(len(pauses), 2)
        self.assertEqual(len(plans[0]), 2)
        self.assertAlmostEqual(d["scenes"][2]["words"][0]["start"], 20.5 - 200 / 30.0)

    def test_several_pauses_stay_in_step(self):
        d = doc_of([scene(0, 0, 210, "h", natSound=True, openClip=True, _fitSecs=5.0), scene(1, 210, 90, "b"),
                    scene(2, 300, 210, "p", natSound=True, _fitSecs=10.0), scene(3, 510, 60, "c")])
        pauses = [{"t0": 0.0, "t1": 7.0, "open": True}, {"t0": 10.0, "t1": 17.0}]
        inp = {"_storm_pauses": [{"at": 0.0, "secs": 7.0}, {"at": 3.0, "secs": 7.0}]}
        self.assertEqual(stormdesk.apply_fits(d, pauses, inp, lambda _p: "u"), 2)
        sc = d["scenes"]
        self.assertEqual([x["startFrame"] for x in sc], [0, 150, 240, 540])
        self.assertEqual(sc[2]["durationInFrames"], 300)
        self.assertAlmostEqual(pauses[1]["t0"], 8.0)
        self.assertAlmostEqual(pauses[1]["t1"], 18.0)
        self.assertEqual(d["durationInFrames"], 600)


class OwnerRules1105(unittest.TestCase):
    def test_plain_pauses_kept_to_two_talking_ones_stay(self):
        sc = [scene(0, 0, 90, "a")]
        rows = []
        for i, (score, talk) in enumerate(((0.9, False), (0.2, False), (0.5, False), (0.1, True))):
            s = scene(i + 1, 90 + i * 300, 210, f"p{i}", natSound=True, **({"talk": True} if talk else {}))
            sc.append(s)
            rows.append({"clip": os.path.basename(s["media"]["url"]), "score": score})
        d = doc_of(sc)
        self.assertEqual(stormdesk.drop_plain_pauses(d, rows), 1)
        self.assertEqual([r["clip"] is None for r in rows], [False, True, False, False])
        self.assertEqual(sum(1 for s in d["scenes"] if s.get("natSound")), 3)

    def test_talking_on_camera_needs_speech_and_a_real_face(self):
        import numpy as np
        fr = [np.zeros((180, 320, 3), np.uint8)] * 6
        big = lambda _f: [(100, 40, 60, 80)]          # noqa: E731
        small = lambda _f: [(100, 40, 8, 8)]          # noqa: E731
        self.assertTrue(stormdesk.is_talking_shot(fr, "speech", big))
        self.assertFalse(stormdesk.is_talking_shot(fr, "speech", small))
        self.assertFalse(stormdesk.is_talking_shot(fr, "nature", big))
        self.assertTrue(stormdesk.is_talking_shot(fr, "speech", lambda _f: [(0.3, 0.2, 0.2, 0.3)]))     # find_faces: shares of the frame
        self.assertFalse(stormdesk.is_talking_shot(fr, "speech", lambda _f: [(0.3, 0.2, 0.05, 0.05)]))

    def test_stats_may_come_every_five_seconds(self):
        self.assertEqual(stormlooks.STAT_EVERY, 5.0)


class ChannelRuleTests(unittest.TestCase):
    def test_personality_never_creator_two_shots_station_free(self):
        sc = [scene(i, i * 90, 90, f"v{i}", at=i * 10.0, ch="Joe Drone Pilot") for i in range(4)]
        sc += [scene(4, 360, 90, "v4", ch="Fuel For Travel"), scene(5, 450, 90, "v5", ch="KSL News"),
               scene(6, 540, 90, "v6", ch="Our RV Life Family")]
        rows = stormdesk.mark_channels(doc_of(sc))
        self.assertEqual(sorted(r["shot"] for r in rows), [2, 3, 4, 6])
        self.assertTrue(all(s.get("_reject") for s in (sc[2], sc[3], sc[4], sc[6])))
        self.assertFalse(sc[5].get("_reject"))

    def test_the_same_frames_twice_are_marked(self):
        sc = [scene(0, 0, 90, "x", at=10.0), scene(1, 90, 90, "y", at=5.0), scene(2, 180, 90, "x", at=11.0), scene(3, 270, 90, "x", at=60.0)]
        self.assertEqual([r["shot"] for r in stormdesk.mark_channels(doc_of(sc))], [2])

    def test_a_creators_channel_never_fills_a_pause(self):
        self.assertFalse(stormdesk.pause_source_ok("Joe Drone Pilot"))
        self.assertFalse(stormdesk.pause_source_ok("Fuel For Travel"))
        self.assertTrue(stormdesk.pause_source_ok("KUTV 2 News"))

    def test_station_crop_kutv_tighter(self):
        self.assertEqual(stormdesk.station_crop("KUTV 2 News"), "news0.68@0.02")
        self.assertEqual(stormdesk.station_crop("KSL News"), "news0.76@0.0")
        self.assertEqual(stormdesk.station_crop("Joe Drone Pilot"), "")


class LedgerTests(unittest.TestCase):
    def test_an_earlier_videos_moment_is_marked_and_gated(self):
        led = stormledger.Ledger([[vid_id("abc"), 10.0, 15.0, "old"]], "new")
        s = scene(0, 0, 90, "abc", at=12.0)
        d = doc_of([s, scene(1, 90, 90, "abc", at=100.0)])
        rows = stormdesk.mark_channels(d, led)
        self.assertEqual([r["shot"] for r in rows], [0])
        g = stormdesk.reuse_gate(d, led)
        self.assertEqual(len(g["earlier"]), 1)

    def test_a_projects_own_moments_do_not_block_it(self):
        led = stormledger.Ledger([["abc", 10.0, 15.0, "mine"]], "mine")
        self.assertFalse(led.used("yt:abc", 10.0, 15.0))
        led2 = stormledger.Ledger([["abc", 10.0, 15.0, "other"]], "mine")
        self.assertTrue(led2.used("yt:abc", 10.0, 15.0))

    def test_same_frames_twice_in_one_video(self):
        d = doc_of([scene(0, 0, 90, "abc", at=10.0), scene(1, 90, 90, "abc", at=11.0), scene(2, 180, 90, "abc", at=40.0)])
        g = stormledger.gate(d, stormledger.Ledger([]), stormdesk.moment)
        self.assertEqual(g["same"], [(0, 1, vid_id("abc"))])

    def test_add_replaces_this_projects_moments(self):
        led = stormledger.Ledger([["a", 0.0, 5.0, "p"], ["b", 0.0, 5.0, "q"]], "p")
        led.add([("yt:c", 1.0, 2.0, 0)])
        self.assertEqual({m[0] for m in led.moments}, {"b", "c"})
        self.assertEqual(json.loads(led.dumps())["moments"][-1][:3], ["c", 1.0, 2.0])

    def test_no_owner_no_ledger(self):
        self.assertEqual(stormledger.load({}).moments, [])
        self.assertFalse(stormledger.save({}, stormledger.Ledger([])))
        self.assertIn("own-1", stormledger.key_for("own-1", "ch 2"))


class LooksTests(unittest.TestCase):
    def doc(self):
        ws = []
        t = 25.0
        text = ("Lake Mead has gone up 13 days in a row . On October 15 the Hoover Dam released 7,750 cfs and the "
                "lake still rose 2 feet this week . That is 26.5 percent full and nobody expected it at all . ").split() * 3
        for tok in text:
            ws.append(w(tok, t, t + 0.35))
            t += 0.4
        d = doc_of([scene(0, 0, 600, "h", natSound=True, openClip=True), scene(1, 600, int((t + 5 - 20) * FPS), "s", words=ws)])
        return d

    def test_stats_land_on_their_number_and_never_overlap(self):
        d = self.doc()
        tl = stormlooks.timeline(d, [], [{"t0": 0.0, "t1": 20.0, "open": True}], {"places": []}, today=datetime.date(2026, 11, 5))
        self.assertTrue(tl["stats"])
        words = stormlooks._words(d)
        for a, _b, text in tl["stats"]:
            self.assertTrue(stormlooks.stat_ok(text, words, a), text)
            self.assertTrue(any(abs(x["s"] - a) < 0.01 and x["t"][0].isdigit() for x in words))
        spans = sorted([(x[0], x[1]) for k in ("stats", "places", "stamps") for x in tl[k]])
        for (a, b), (c, _d) in zip(spans, spans[1:]):
            self.assertLessEqual(b, c)
        self.assertGreater(tl["stats"][0][0], 20.0)         # nothing over the hook

    def test_spoken_date_becomes_a_stamp(self):
        blocks, pauses = [{"start": 25.0, "tab": "HOOVER DAM"}], [{"t0": 0.0, "t1": 20.0, "open": True}]
        self.assertFalse(stormlooks.timeline(self.doc(), blocks, pauses, {}, today=datetime.date(2026, 11, 5))["stamps"])    # off by default
        tl = stormlooks.timeline(self.doc(), blocks, pauses, {}, today=datetime.date(2026, 11, 5), opts={"stamps": True})
        self.assertTrue(tl["stamps"])
        self.assertEqual(tl["stamps"][0][2], "10-15-2026")
        self.assertEqual(tl["stamps"][0][3], "HOOVER DAM")

    def test_a_number_the_script_does_not_say_is_thrown_away(self):
        ws = [{"t": "the", "s": 1.0, "e": 1.1}, {"t": "13", "s": 1.2, "e": 1.3}, {"t": "days", "s": 1.4, "e": 1.5}]
        self.assertTrue(stormlooks.stat_ok("13 DAYS UP", ws, 1.2))
        self.assertFalse(stormlooks.stat_ok("14 DAYS UP", ws, 1.2))
        cands = stormlooks.stat_candidates(ws)
        got = stormlooks.word_stats(cands, ws, lambda _s, _p: {"stats": [{"i": 0, "text": "99 DAYS", "keep": True}]})
        self.assertEqual(got[0]["text"], "13 DAYS")         # the rule's wording, not the invented number

    def test_a_year_or_bare_number_is_no_stat(self):
        ws = [{"t": "in", "s": 0, "e": .1}, {"t": "2025", "s": .2, "e": .3}, {"t": "the", "s": .4, "e": .5}, {"t": "lake", "s": .6, "e": .7}]
        self.assertEqual(stormlooks.stat_candidates(ws), [])

    def test_titles_before_a_pause_maps_on_their_word(self):
        d = self.doc()
        blocks = [{"start": 25.0, "headline": "LAKE MEAD RISING", "tab": "LAKE MEAD"}]
        place = mock.Mock(lat=36.0, lon=-114.7, country="us")
        mosaic = mock.Mock(return_value={"file": "/x.png", "meta": {"z": 13, "ox": 0, "oy": 0, "w": 1, "h": 1}})
        tl = stormlooks.timeline(d, blocks, [{"t0": 0.0, "t1": 20.0, "open": True}, {"t0": 60.0, "t1": 67.0}],
                                 {"places": ["Hoover Dam, NV"]}, lookup=lambda _n: place, mosaic=mosaic,
                                 today=datetime.date(2026, 11, 5))
        self.assertEqual(len(tl["titles"]), 1)
        self.assertLess(tl["titles"][0][2], 60.0)
        self.assertEqual(tl["maps"][0]["label"], "Hoover Dam")
        self.assertAlmostEqual(tl["maps"][0]["pin"], stormlooks.find_phrase(stormlooks._words(d), "Hoover Dam", 20.0))

    def test_outside_the_us_no_pin_map(self):
        place = mock.Mock(lat=48.0, lon=2.0, country="fr")
        d = self.doc()
        tl = stormlooks.timeline(d, [], [{"t0": 0.0, "t1": 20.0, "open": True}], {"places": ["Hoover Dam"]}, lookup=lambda _n: place,
                                 mosaic=mock.Mock(side_effect=AssertionError), today=datetime.date(2026, 11, 5))
        self.assertEqual(tl["maps"], [])


@unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
class HookSoundTests(unittest.TestCase):
    def test_every_hook_clip_plays_its_own_sound_edge_to_edge(self):
        t = tempfile.mkdtemp()
        try:
            clip = os.path.join(t, "c.mp4")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=64x36:rate=30:duration=20", "-f", "lavfi",
                            "-i", "anoisesrc=color=pink:amplitude=0.4:sample_rate=48000:duration=20", "-c:v", "libx264", "-preset", "ultrafast",
                            "-c:a", "aac", "-shortest", clip], check=True)
            sc = [scene(i, i * 180, 180, f"h{i}", natSound=True, openClip=True) for i in range(3)] + [scene(3, 540, 90, "s")]
            for s in sc:
                s["media"]["url"] = clip
            sc[1]["talk"] = True
            d = doc_of(sc)
            d["meta"]["stormDesk"] = {"pauses": [{"t0": k * 6.0, "t1": (k + 1) * 6.0, "open": True} for k in range(3)]}
            track, rows = stormdesk.nat_track(d, 21.0, 0.0)
            self.assertEqual([r["ok"] for r in rows], [True, True, True])
            self.assertEqual([round(r["seconds"], 1) for r in rows], [6.0, 6.0, 6.6])
            self.assertEqual([r["tail"] for r in rows], [0.0, 0.0, 0.6])
        finally:
            shutil.rmtree(t, ignore_errors=True)


class SoundTests(unittest.TestCase):
    def test_owner_levels(self):
        self.assertEqual(stormpieces.MUSIC_UNDER_VOICE_DB, 15.0)
        self.assertEqual(stormpieces.LEVEL_DB, -13.0)
        self.assertEqual(stormdesk.MUSIC_UNDER_VOICE_DB, 15.0)
        self.assertEqual(stormdesk.MASTER_LUFS, -14.0)

    def test_every_cue_has_a_sound_file(self):
        tl = {"stats": [[1.0, 3.0, "13 DAYS"]], "places": [[5.0, 8.0, "X"]], "stamps": [[9.0, 12.0, "d", "c"]],
              "titles": [[13.0, 15.0, 16.0, "T", "S"]], "type": [[0.4, 3.0, "d"]],
              "maps": [{"t0": 20.0, "t1": 27.0, "pin": 21.0, "stat": "X"}]}
        cues = stormpieces.sfx_cues(tl)
        self.assertGreaterEqual(len(cues), 8)
        for _t, f, _trim, db in cues:
            self.assertTrue(os.path.isfile(os.path.join(stormpieces.sfx_dir(), f)), f)
            self.assertLessEqual(db, -13.0)

    def test_tracks_take_turns(self):
        got = stormdesk.music_plan(["https://a/1.mp3", {"url": "https://a/2.mp3", "offset": 9}, "nope"], 600.0)
        self.assertEqual([(r["url"][-5:], r["at"], r["offset"]) for r in got], [("1.mp3", 0.0, 0.0), ("2.mp3", 300.0, 9.0)])
        self.assertEqual(stormdesk.music_plan(None, 600.0), [])

    def test_music_sections(self):
        self.assertEqual(stormpieces.music_sections({"stormDesk": {"music": [{"url": "u", "at": 3, "offset": 9}]}}),
                         [{"url": "u", "at": 3.0, "offset": 9.0}])
        self.assertEqual(stormpieces.music_sections({"bgm": {"url": "b"}})[0]["url"], "b")
        self.assertEqual(stormpieces.music_sections({}), [])

    def test_speech_mask_swells(self):
        m = stormpieces.speech_mask([(1.0, 2.0)], 48000 * 3)
        self.assertEqual(float(m[0]), 0.0)
        self.assertAlmostEqual(float(m[int(1.5 * 48000)]), 1.0, places=2)


class SpecTests(unittest.TestCase):
    def test_a_later_shot_moved_by_a_pause_keeps_its_name(self):
        a = doc_of([scene(0, 0, 90, "x"), scene(1, 90, 90, "y")])
        a["stormDesk"] = {"engine": "pieces"}
        b = json.loads(json.dumps(a))
        b["scenes"][1]["startFrame"] += 300
        b["durationInFrames"] += 300
        k1 = stormpieces.spec_key(stormpieces.scene_spec(a, 1, []))
        b["durationInFrames"] += 300                # (the last shot's end fade travels with it)
        k2 = stormpieces.spec_key(stormpieces.scene_spec(b, 1, []))
        self.assertNotEqual(k1, "")
        a2 = doc_of([scene(0, 0, 90, "x"), scene(1, 90, 90, "y"), scene(2, 180, 30, "z")])
        a3 = json.loads(json.dumps(a2))
        a3["scenes"][1]["startFrame"] += 300
        a3["scenes"][2]["startFrame"] += 300
        a3["durationInFrames"] += 300
        self.assertEqual(stormpieces.spec_key(stormpieces.scene_spec(a2, 1, [])), stormpieces.spec_key(stormpieces.scene_spec(a3, 1, [])))

    def test_a_changed_shot_gets_a_new_name_its_link_does_not(self):
        a = doc_of([scene(0, 0, 90, "x"), scene(1, 90, 90, "y"), scene(2, 180, 90, "z")])
        k = stormpieces.spec_key(stormpieces.scene_spec(a, 1, []))
        b = json.loads(json.dumps(a))
        b["scenes"][1]["media"]["url"] = "https://r2/x/y.mp4"
        self.assertEqual(stormpieces.spec_key(stormpieces.scene_spec(b, 1, [])), k)
        b["scenes"][1]["media"]["trimStart"] = 2.0
        self.assertNotEqual(stormpieces.spec_key(stormpieces.scene_spec(b, 1, [])), k)

    def test_no_source_names_on_screen(self):
        d = doc_of([scene(0, 0, 90, "x", credit={"text": "VIDEO: KSL News"}), scene(1, 90, 90, "y", credit={"text": "VIDEO: X", "archive": True})])
        d["stormDesk"] = {"credits": False, "logo": {"text": "T"}}
        keys = stormpieces.scene_spec(d, 0, [])["layers"][0][1]
        self.assertFalse(any(k[0] == "chip" for k in keys))
        keys = stormpieces.scene_spec(d, 1, [])["layers"][0][1]     # no ARCHIVE tag either (the owner 2026-11-06)
        self.assertFalse(any(k[0] == "chip" for k in keys))

    def test_old_timelines_stay_on_remotion(self):
        self.assertEqual(stormpieces.engine_of({"stormDesk": {"lowerThirds": []}}), "remotion")
        self.assertEqual(stormpieces.engine_of({"stormDesk": {"engine": "pieces"}}), "pieces")
        self.assertEqual(stormpieces.engine_of(None, {"storm_desk": {"engine": "pieces"}}), "pieces")

    def test_not_supported_goes_to_remotion(self):
        d = doc_of([scene(0, 0, 90, "x")])
        self.assertEqual(stormpieces.supported(d), "")
        d["overlays"] = [{"type": "x"}]
        self.assertIn("overlays", stormpieces.supported(d))
        d["overlays"] = []
        d["scenes"][0]["media"]["type"] = "lottie"
        self.assertIn("lottie", stormpieces.supported(d))
        d["scenes"][0]["media"]["type"] = "animation"       # the quality check's text line: drawn as a card
        self.assertEqual(stormpieces.supported(d), "")

    def test_delogo_stays_inside_the_frame(self):
        c = stormpieces.delogo_chain([[0.0, 0.0, 0.1, 0.1], [0.95, 0.95, 0.2, 0.2]], 1920, 1080)
        for part in c.strip(",").split(","):
            vals = dict(x.split("=") for x in part.replace("delogo=", "").split(":"))
            self.assertGreaterEqual(int(vals["x"]), 1)
            self.assertLess(int(vals["x"]) + int(vals["w"]), 1920)
            self.assertLess(int(vals["y"]) + int(vals["h"]), 1080)


@unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
class DrawTests(unittest.TestCase):
    """One real render of a tiny video: exact frames, the shot cache, the join without an encode."""

    @classmethod
    def setUpClass(cls):
        cls.t = tempfile.mkdtemp()
        cls.clip = os.path.join(cls.t, "c.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=3",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", cls.clip], check=True)
        cls.env = mock.patch.dict(os.environ, {"STORM_PIECES_WORKERS": "1"})
        cls.env.start()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        shutil.rmtree(cls.t, ignore_errors=True)

    def test_one_shot_exact_frames_with_a_look_and_a_short_source(self):
        spec = {"v": 1, "kind": "video", "src": self.clip, "ss": 2.5, "n": 45, "fps": 30, "mode": "news0.76@0.0", "delogo": [[0.02, 0.02, 0.1, 0.1]],
                "flip": False, "adjust": {}, "layers": [[45, ()]], "looks": [["stat", 0.1, 1.2, "13 DAYS UP"]],
                "edge": {"first": True, "last": False}}
        out = os.path.join(self.t, "a", "one.mp4")
        stormpieces.render_one(spec, out, threads=1)
        self.assertEqual(stormpieces.frames_of(out), 45)    # the source had 0.5 s left: the last frame holds

    def test_fast_path_and_join_keep_every_frame(self):
        a = dict(v=1, kind="video", src=self.clip, ss=0.0, n=30, fps=30, mode="full", delogo=[], flip=False, adjust={}, layers=[[30, ()]])
        b = dict(a, ss=1.0, n=20)
        pa, pb = os.path.join(self.t, "j", "a.mp4"), os.path.join(self.t, "j", "b.mp4")
        stormpieces.render_one(a, pa, threads=1)
        stormpieces.render_one(b, pb, threads=1)
        os.makedirs(os.path.join(self.t, "sdpieces"), exist_ok=True)
        out = stormpieces.join([pa, pb], os.path.join(self.t, "joined.mp4"), self.t)
        self.assertEqual(stormpieces.frames_of(out), 50)

    def test_only_changed_shots_are_drawn_again(self):
        d = doc_of([scene(0, 0, 20, "x"), scene(1, 20, 20, "y")])
        for s in d["scenes"]:
            s["media"]["url"] = self.clip
        work = os.path.join(self.t, "w")
        seen = []
        stormpieces.render_pieces(d, work, lambda done, total, reused: seen.append((done, total, reused)))
        self.assertEqual(seen[0], (0, 2, 0))
        seen.clear()
        d["scenes"][1]["media"]["trimStart"] = 1.0
        d["scenes"][1]["semanticMetadata"]["moment"]["start"] = 1.0
        with mock.patch.object(stormpieces, "ProcessPoolExecutor", wraps=stormpieces.ProcessPoolExecutor) as pool:
            stormpieces.render_pieces(d, work, lambda done, total, reused: seen.append((done, total, reused)))
        self.assertEqual(seen[0], (1, 2, 1))
        self.assertEqual(pool.call_count, 1)

    def test_a_small_graph_over_a_clip_draws(self):
        spec = dict(v=1, kind="video", src=self.clip, ss=0.0, n=20, fps=30, mode="full", delogo=[], flip=False, adjust={}, layers=[[20, ()]],
                    looks=[["graph", 0.0, 0.6, "FORECAST VS. ACTUAL", [["Forecast", "1,033.97 FT", 1033.97, False], ["Actual", "1,039.21 FT", 1039.21, True]], 1030.0]])
        out = os.path.join(self.t, "graph", "g.mp4")
        stormpieces.render_one(spec, out, threads=1)
        self.assertEqual(stormpieces.frames_of(out), 20)

    def test_a_text_card_scene_draws(self):
        spec = dict(v=1, kind="animation", src="", ss=0.0, n=15, fps=30, mode="full", delogo=[], flip=False, adjust={},
                    layers=[[15, (("card", "The lake rose two feet"),)]])
        out = os.path.join(self.t, "card", "c.mp4")
        stormpieces.render_one(spec, out, threads=1)
        self.assertEqual(stormpieces.frames_of(out), 15)

    def test_a_broken_source_fails_loudly_never_hangs(self):
        spec = dict(v=1, kind="video", src=os.path.join(self.t, "missing.mp4"), ss=0.0, n=10, fps=30, mode="full", delogo=[], flip=False, adjust={},
                    layers=[[10, ()]])
        with mock.patch.object(stormpieces, "PIECE_TRIES", 1):
            with self.assertRaises(RuntimeError):
                stormpieces.render_one(spec, os.path.join(self.t, "b", "x.mp4"), threads=1)


class ThumbTests(unittest.TestCase):
    def test_both_looks_are_4k_and_under_2mb(self):
        t = tempfile.mkdtemp()
        try:
            im = Image.effect_noise((1344, 768), 40).convert("RGB")
            for fn, name in ((stormthumbs.own, "o.jpg"), (stormthumbs.new, "n.jpg")):
                p = fn(im, "LAKE MEAD ALERT!", os.path.join(t, name))
                with Image.open(p) as x:
                    self.assertEqual(x.size, (3840, 2160))
                self.assertLessEqual(os.path.getsize(p), 2_000_000)
        finally:
            shutil.rmtree(t, ignore_errors=True)

    def test_headlines_truthful_numbers_only(self):
        p = stormthumbs.plan("Lake Mead up", "the lake rose 13 days", ["Lake Mead, NV"],
                             lambda _s, _p: {"own": "99 FEET", "new": "13 DAYS UP!", "picture": "a dam"})
        self.assertEqual(p["own"], "LAKE MEAD ALERT")
        self.assertEqual(p["new"], "13 DAYS UP!")

    def test_no_picture_no_thumbnails_no_failure(self):
        d = doc_of([scene(0, 0, 30, "x")])
        out = stormthumbs.make(d, {"title": "T"}, tempfile.gettempdir(), draw=lambda _p: None)
        self.assertEqual(out.get("error"), "no picture")


class CaptionTests(unittest.TestCase):
    def test_a_caption_with_an_invented_number_is_dropped(self):
        d = doc_of([scene(0, 0, 90, "a"), scene(1, 90, 90, "b", natSound=True), scene(2, 180, 90, "c", natSound=True)])
        d["scenes"][0]["text"] = "the lake rose 2 feet"
        got = stormdesk.write_captions(d, lambda _s, _p: {"captions": [{"i": 0, "text": "Lake up 2 feet."}, {"i": 1, "text": "Lake up 90 feet"}]})
        self.assertEqual(got, 1)
        self.assertEqual(d["scenes"][1]["caption"], "Lake up 2 feet")
        self.assertNotIn("caption", d["scenes"][2])


if __name__ == "__main__":
    unittest.main()
