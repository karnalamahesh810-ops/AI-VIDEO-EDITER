"""Celeb compilation style: script parser, quote finder maths, timeline plan, voice-over alignment (offline)."""
import unittest

from src.celeb import plan, script, voalign
from src.celeb.quotes import W, match_quote, parse_json3, rank, snap


def words(text, start=0.0, step=0.3, gaps=None):
    out, t = [], start
    for k, w in enumerate(text.split()):
        t += (gaps or {}).get(k, 0.0)
        out.append(W(w, t, t + step * 0.9))
        t += step
    return out


class ScriptTest(unittest.TestCase):
    def test_blocks_and_fields(self):
        b = script.parse('Intro line.\nSecond line.\n[CLIP: Tom Holland, Zendaya | "spider-man\'s in space" | '
                         'Jimmy Kimmel Live | 12-20s | label=JIMMY KIMMEL LIVE]\nBridge.\n'
                         '[CLIP: url=https://youtu.be/cocE4mUbc7A start=0:44 end=0:56 | cold=1]')
        self.assertEqual([x.kind for x in b], ["narr", "clip", "narr", "clip"])
        self.assertEqual(b[0].text, "Intro line. Second line.")
        self.assertEqual(b[1].who, ["Tom Holland", "Zendaya"])
        self.assertEqual(b[1].quote, "spider-man's in space")
        self.assertEqual((b[1].where, b[1].min_s, b[1].max_s, b[1].label),
                         ("Jimmy Kimmel Live", 12.0, 20.0, "JIMMY KIMMEL LIVE"))
        self.assertEqual((b[3].video_id, b[3].start, b[3].end, b[3].cold), ("cocE4mUbc7A", 44.0, 56.0, True))

    def test_timecodes(self):
        self.assertEqual(script.timecode("1:02:03"), 3723.0)
        self.assertEqual(script.duration_hint("15s"), (0.0, 15.0))


class QuoteTest(unittest.TestCase):
    def test_fuzzy_match_tolerates_caption_slips(self):
        ws = words("so the fake scrip stuff and I was reading what I thought was a fake scrip because it was like "
                   "spider-man's in space so I didn't finish")
        score, i, j = match_quote(ws, "I was reading what I thought was a fake script, because it was like "
                                      "Spider-Man's in space")
        self.assertGreater(score, 0.85)
        self.assertEqual(ws[i].text, "I")
        self.assertEqual(ws[j].text, "space")

    def test_json3_word_times(self):
        data = {"events": [{"tStartMs": 1000, "dDurationMs": 2000,
                            "segs": [{"utf8": "hello"}, {"utf8": " there", "tOffsetMs": 500}]},
                           {"tStartMs": 4000, "dDurationMs": 1000, "segs": [{"utf8": "manual line here"}]}]}
        ws = parse_json3(data)
        self.assertEqual([w.text for w in ws], ["hello", "there", "manual", "line", "here"])
        self.assertAlmostEqual(ws[1].start, 1.5)
        self.assertLess(ws[2].start, ws[3].start)          # a manual line's words are spread, not stacked

    def test_snap_takes_setup_and_finishes_a_run_on_thought(self):
        ws = words("You're right. The funny thing is I read the fake script. It was like Spider-Man's in space. "
                   "So I didn't finish it but it was real. Okay.", step=0.5, gaps={20: 0.2, 28: 1.5})
        q = [k for k, w in enumerate(ws) if w.text in ("It", "space.")]
        a, b = snap(ws, q[0], q[-1])
        said = [w.text for w in ws if a <= w.start and w.end <= b]
        self.assertEqual(said[0], "The")                    # the setup sentence, not mid-sentence
        self.assertEqual(said[-1], "real.")                 # the speaker ran on: the thought is finished

    def test_rank_prefers_official_show(self):
        c = [{"id": "a", "title": "Tom Holland funniest moments compilation", "channel": "fan", "duration": 600},
             {"id": "b", "title": "Tom Holland on spoilers", "channel": "Jimmy Kimmel Live", "duration": 400}]
        self.assertEqual(rank(c, ["Tom Holland"], "Jimmy Kimmel")[0]["id"], "b")


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.blocks = script.parse("Intro. [CLIP: A | \"x\" | label=SHOW ONE] Bridge. [CLIP: B | \"y\" | cold=1] Outro.")
        w = [{"text": "Hello", "start": 0.5, "end": 0.9}, {"text": "there.", "start": 1.0, "end": 1.4},
             {"text": "Big", "start": 6.0, "end": 6.3}, {"text": "laugh.", "start": 6.4, "end": 6.9}]
        self.clips = {1: plan.Clip("c1.mp4", "w1.mp4", 100.0, 117.0, 130.0, (2.0, 6.0), "SHOW ONE", False, w),
                      3: plan.Clip("c2.mp4", "w2.mp4", 40.0, 57.0, 71.0, (8.0, 11.0), "", True, w)}
        self.lens = {"w1.mp4": 40.0, "w2.mp4": 40.0}

    def test_timeline(self):
        p = plan.build(self.blocks, [8.0, 5.0, 6.0], ["n0", "n1", "n2"], self.clips, self.lens)
        kinds = [s.kind for s in p.shots]
        self.assertEqual(kinds[:2], ["cold", "flash"])          # cold open first, a flash after it
        t = 0.0
        for s in p.shots:                                        # the picture never has a hole
            self.assertAlmostEqual(s.at, t, places=3)
            t = s.at + s.dur
        self.assertAlmostEqual(t, p.total, places=3)
        clip1 = next(s for s in p.shots if s.kind == "clip" and s.clip == 1)
        narr1 = next(s for s in p.sounds if s.kind == "narr")
        snd1 = next(s for s in p.sounds if s.kind == "clip" and s.clip == 1)
        self.assertAlmostEqual(snd1.at, narr1.at + 8.0)           # clip sound starts as the narrator stops
        self.assertLess(clip1.at, snd1.at)                        # J-cut: picture leads the sound
        self.assertAlmostEqual(clip1.src_in, 17.0 - (snd1.at - clip1.at))
        self.assertTrue(clip1.push)
        self.assertEqual(p.labels[0][2], "SHOW ONE")
        for s in p.shots:
            if s.kind == "broll":
                self.assertLessEqual(s.dur, 3.0 + 1.3)
        self.assertTrue(all(a < b for a, b, _ in p.captions))

    def test_music_ducks_inside_clips(self):
        p = plan.build(self.blocks, [8.0, 5.0, 6.0], ["n0", "n1", "n2"], self.clips, self.lens)
        pts = dict(plan.music_gain_points(p))
        a, b = p.clip_spans[1]
        self.assertAlmostEqual(pts[a], plan.MUSIC_LEVEL * plan.MUSIC_IN_CLIP)
        self.assertAlmostEqual(pts[round(b + 0.5, 3)], plan.MUSIC_LEVEL * plan.MUSIC_DUCK)

    def test_cold_open_starts_on_a_sentence(self):
        a, b = plan.cold_span(self.clips[3])
        self.assertTrue(plan.COLD_MIN <= b - a <= plan.COLD_MAX)


class VoAlignTest(unittest.TestCase):
    def test_blocks_found_and_read_quote_dropped(self):
        heard = words("Tom cannot keep a secret. I was reading a fake script. So Jimmy made it a game.",
                      gaps={5: 0.8, 11: 0.8})
        spans = voalign.align_blocks(heard, ["Tom cannot keep a secret.", "So Jimmy made it a game."])
        self.assertEqual(spans, [(0, 4), (11, 16)])
        cuts = voalign.cut_points(heard, spans, [(1.7, 2.4), (5.5, 6.2)], 10.0)
        self.assertLess(cuts[0][1], heard[5].start)          # block 1 ends before the read quote
        self.assertGreater(cuts[1][0], heard[10].end)        # block 2 starts after it


if __name__ == "__main__":
    unittest.main()


class ReelTest(unittest.TestCase):
    def test_specs_and_swears(self):
        from src.celeb import reel
        self.assertEqual(reel.spec('"HA HA HA"@10.4@largest'), ("HA HA HA", 10.4, "largest"))
        self.assertEqual(reel.spec('"OMG..."@center'), ("OMG...", 0.0, "center"))
        self.assertEqual(reel.starred("Fucking"), "F***ing")
        self.assertTrue(reel.SWEAR.search("Motherf***er!"))
        self.assertFalse(reel.UNCENSORED.search("F***."))
        sid, rng, opts = reel._montage_item('XG_CimbpVMQ@42.3-43.3 pop="HA HA HA"@left speed')
        self.assertEqual((sid, rng), ("XG_CimbpVMQ", (42.3, 43.3)))
        self.assertEqual(opts, ['pop="HA HA HA"@left', "speed"])

    def test_captions_break_at_camera_cuts(self):
        from src.celeb import reel
        ws = [{"text": t, "start": s, "end": s + 0.3} for t, s in
              (("You", 10.0), ("got", 10.3), ("a", 10.6), ("spider", 10.9), ("web.", 11.2), ("Spider", 12.0), ("-Man", 12.3))]
        caps = reel.caption_phrases(ws, 10.0, 14.0, [10.75], offset=100.0)
        self.assertEqual([c[2] for c in caps], ["YOU GOT A", "SPIDER WEB.", "SPIDER-MAN"])
        self.assertAlmostEqual(caps[0][0], 100.0)
        self.assertTrue(all(a < b for a, b, _ in caps))

    def test_elements_draw(self):
        from src.celeb import fx
        for e in (fx.Pop("pop", 0, 1.4, text='"F***"'), fx.NameLabel("name", 0, 1.9, text="ZENDAYA"),
                  fx.Circle("c", 0, 1.9), fx.Pointer("p", 0, 1.6), fx.Arrow3D("a", 0, 1.0), fx.SpeedLines("s", 0, 0.8)):
            for t in (0.02, 0.2, 0.9):
                got = e.draw(t)
                if got:
                    im, x, y = got
                    self.assertGreater(im.getbbox()[2] if im.getbbox() else 1, 0)


class Round3Test(unittest.TestCase):
    def test_arrow_follows_measured_scale_curve(self):
        from src.celeb import fx
        track = [{"cx": 0.4, "cy": 0.35, "w": 0.15, "h": 0.3}] * 40
        a = fx.Arrow3D("a", 0, 1.0, track=track)
        sizes = [a.draw(f / fx.FPS)[0].getbbox() for f in (0, 5, 10)]
        widths = [b[2] - b[0] for b in sizes]
        self.assertLess(widths[0], widths[2])           # grows in from 22 %
        self.assertGreater(widths[1], widths[2])        # overshoots to 110 % on frame 6, settles
        im, x, y = a.draw(0.5)
        self.assertGreater(y + im.height / 2, 0.35 * fx.H)  # sits below the face centre: never covers the face

    def test_circle_frames_the_tracked_face(self):
        from src.celeb import fx
        c = fx.Circle("c", 0, 2, track=[{"cx": 0.3, "cy": 0.4, "w": 0.15, "h": 0.3}] * 70)
        im, x, y = c.draw(1.5)
        self.assertAlmostEqual((x + im.width / 2) / fx.W, 0.3, places=2)
        self.assertAlmostEqual((y + im.height / 2) / fx.H, 0.4, places=2)

    def test_premiere_levels_are_linear(self):
        from src.celeb import premiere
        self.assertIn("<value>1.00000</value>", premiere._level(0.0))
        self.assertIn("<value>0.50119</value>", premiere._level(-6.0))
