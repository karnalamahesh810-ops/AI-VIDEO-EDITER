"""Celeb caption colours by speaker (src/celeb/speakers.py, separate.py): offline, no network, no model download."""
import os
import unittest
from unittest import mock

import numpy as np

from src.celeb import separate, speakers


def unit(v):
    v = np.asarray(v, np.float32)
    return v / np.linalg.norm(v)


def voice(base, k, noise=0.05, dim=16):
    """A noisy embedding near voice `base` (deterministic per k)."""
    rng = np.random.default_rng(1000 * base + k)
    centre = np.zeros(dim, np.float32)
    centre[base] = 1.0
    return unit(centre + noise * rng.standard_normal(dim))


class TurnsTest(unittest.TestCase):
    def test_sentence_runs_on_without_a_pause(self):
        ph = [(0.0, 0.8, "I THINK AS LONG"), (0.9, 1.6, "AS WE CAN DO JUSTICE."), (1.7, 2.2, "GOOD"),
              (3.0, 3.5, "NO WAY")]
        # 0+1 continue one sentence; 2 has no end mark but 3 starts 0.8 s later (a pause)
        self.assertEqual(speakers.turns_of(ph), [[0, 1], [2], [3]])

    def test_sentence_end_closes_the_turn(self):
        ph = [(0.0, 0.5, "WHAT'S YOUR NAME?"), (0.55, 1.0, "I'M WILLIAM")]
        self.assertEqual(speakers.turns_of(ph), [[0], [1]])

    def test_empty(self):
        self.assertEqual(speakers.turns_of([]), [])


class AssignTest(unittest.TestCase):
    def test_two_clear_voices_first_heard_is_zero(self):
        embs = [voice(3, 0), voice(7, 0), voice(3, 1), voice(7, 1), voice(3, 2), voice(7, 2)]
        self.assertEqual(speakers.assign(embs), [0, 1, 0, 1, 0, 1])

    def test_order_follows_first_appearance_not_cluster_id(self):
        embs = [voice(7, 0), voice(7, 1), voice(3, 0), voice(3, 1)]
        self.assertEqual(speakers.assign(embs), [0, 0, 1, 1])

    def test_three_voices(self):
        embs = [voice(b, k) for k in range(3) for b in (1, 5, 9)]
        self.assertEqual(speakers.assign(embs), [0, 1, 2] * 3)

    def test_weak_split_stays_one_voice(self):
        # two groups that differ only a little (noisy clip audio): gap below GAP -> one voice
        a = np.zeros(16, np.float32)
        a[0] = 1.0
        b = a.copy()
        b[1] = 0.25
        embs = [unit(a + 0.01 * k) if k % 2 == 0 else unit(b + 0.01 * k) for k in range(6)]
        self.assertEqual(speakers.assign(embs), [0] * 6)

    def test_too_few_turns_per_voice_stays_one_voice(self):
        embs = [voice(3, 0), voice(3, 1), voice(3, 2), voice(7, 0)]       # the second voice has 1 turn only
        self.assertEqual(speakers.assign(embs), [0, 0, 0, 0])

    def test_missing_embeddings_take_the_neighbour(self):
        embs = [None, voice(3, 0), voice(7, 0), None, voice(3, 1), voice(7, 1)]
        self.assertEqual(speakers.assign(embs), [0, 0, 1, 1, 0, 1])

    def test_all_missing(self):
        self.assertEqual(speakers.assign([None, None]), [0, 0])
        self.assertEqual(speakers.assign([]), [])

    def test_separation_measure(self):
        X = np.stack([voice(3, 0), voice(3, 1), voice(7, 0), voice(7, 1)])
        self.assertGreater(speakers.separation(X, [0, 0, 1, 1]), 0.5)
        self.assertLess(speakers.separation(X, [0, 1, 0, 1]), 0.0)
        self.assertEqual(speakers.separation(X, [0, 0, 0, 0]), -1.0)

    def test_renumber(self):
        self.assertEqual(speakers.renumber([5, 5, 2, 9, 2]), [0, 0, 1, 2, 1])


class RolesTest(unittest.TestCase):
    W, Y, G = speakers.WHITE, speakers.YELLOW, speakers.GREEN

    def test_one_voice_is_the_celebrity(self):
        self.assertEqual(speakers.roles([0, 0, 0], [1, 1, 1], ["", "", ""], "Tom Holland"), [self.W] * 3)
        self.assertEqual(speakers.roles([], [], []), [])

    def test_most_speech_is_white_rest_yellow(self):
        out = speakers.roles([0, 1, 0, 1], [0.5, 3.0, 0.5, 2.0], ["", "", "", ""], "", conf=0.6)
        self.assertEqual(out, [self.Y, self.W, self.Y, self.W])

    def test_not_confident_stays_white(self):
        out = speakers.roles([0, 1, 0, 1], [1.0, 1.2, 1.0, 1.0], ["", "", "", ""], "Tom Holland", conf=0.6)
        self.assertEqual(out, [self.W] * 4)

    def test_saying_the_featured_name_is_someone_else(self):
        # voice 1 talks most, but its turns say "Tom": it is the host, voice 0 is Tom
        texts = ["I'M SPIDER-MAN", "PLEASE WELCOME TOM HOLLAND", "THANK YOU", "TOM, TELL US"]
        out = speakers.roles([0, 1, 0, 1], [1.5, 2.5, 1.0, 1.5], texts, "Tom Holland", conf=0.3)
        self.assertEqual(out, [self.W, self.Y, self.W, self.Y])
        self.assertTrue(speakers.mentions("WELL, HOLLAND...", "Tom Holland"))
        self.assertFalse(speakers.mentions("TOMORROW", "Tom Holland"))
        self.assertFalse(speakers.mentions("ANYTHING", ""))

    def test_third_voice_yellow_unless_green_is_on(self):
        v, s, t = [0, 1, 2, 0], [3.0, 0.5, 0.5, 3.0], ["", "", "", ""]
        self.assertEqual(speakers.roles(v, s, t, conf=0.6), [self.W, self.Y, self.Y, self.W])
        with mock.patch.object(speakers, "GREEN_THIRD", True):
            self.assertEqual(speakers.roles(v, s, t, conf=0.6), [self.W, self.Y, self.G, self.W])

    def test_colour_indices_match_colours(self):
        self.assertEqual(tuple(speakers.COLOURS[speakers.YELLOW][:3]), (252, 255, 4))
        self.assertEqual(tuple(speakers.COLOURS[speakers.WHITE][:3]), (255, 255, 255))
        self.assertEqual(tuple(speakers.COLOURS[speakers.GREEN][:3]), (49, 255, 3))


class SpeakerIndexTest(unittest.TestCase):
    def test_colours_round_trip(self):
        for k, c in enumerate(speakers.COLOURS):
            self.assertEqual(speakers.speaker_index(c), k)
            self.assertEqual(speakers.speaker_index(tuple(c[:3])), k)
            self.assertEqual(speakers.speaker_index(list(c)), k)

    def test_hex(self):
        self.assertEqual(speakers.speaker_index("#FCFF04"), 0)
        self.assertEqual(speakers.speaker_index("#ffffff"), 1)
        self.assertEqual(speakers.speaker_index("31FF03"), 2)

    def test_unknown_reads_as_first_voice(self):
        self.assertEqual(speakers.speaker_index((1, 2, 3, 255)), 0)
        self.assertEqual(speakers.speaker_index(None), 0)
        self.assertEqual(speakers.speaker_index("#zzzzzz"), 0)
        self.assertEqual(speakers.speaker_index(""), 0)

    def test_reference_colours(self):
        self.assertEqual(tuple(speakers.COLOURS[0][:3]), (252, 255, 4))
        self.assertEqual(tuple(speakers.COLOURS[1][:3]), (255, 255, 255))
        self.assertEqual(tuple(speakers.COLOURS[2][:3]), (49, 255, 3))


class ColourPhrasesTest(unittest.TestCase):
    PH = [(10.0, 10.8, "WHAT'S YOUR NAME?"), (11.0, 11.6, "I'M WILLIAM."), (12.0, 12.9, "NICE TO MEET YOU."),
          (13.2, 13.8, "YOU TOO."), (14.0, 14.5, "HIGH FIVE"), (14.55, 15.2, "BUDDY."), (16.0, 16.6, "YEAH.")]

    def test_empty(self):
        self.assertEqual(speakers.colour_phrases("x.mp4", 0.0, [], 0.0, []), [])

    def test_no_model_means_the_celebrity_everywhere(self):
        with mock.patch.object(speakers, "available", return_value=False):
            out = speakers.colour_phrases("x.mp4", 0.0, self.PH, 0.0, [], featured="Tom Holland")
        self.assertEqual([o[3] for o in out], [speakers.COLOURS[speakers.WHITE]] * len(self.PH))
        self.assertEqual([o[:3] for o in out], list(self.PH))

    def test_turns_map_back_to_phrases_on_the_source_clock(self):
        # clip starts at 10.0 on the output clock and at 100.0 on the source file
        src_in, offset = 100.0, 10.0
        seen = {}

        def fake_audio(path, a, b):
            seen["range"] = (a, b)
            return np.zeros(int((b - a) * speakers.SR), np.float32)

        who = iter([3, 7, 3, 7, 3, 7])            # one voice per TURN: 6 turns ("HIGH FIVE BUDDY." is one)
        calls = []

        def fake_embed(x, a, b):
            calls.append((round(a, 3), round(b, 3)))
            return voice(next(who), len(calls))

        with mock.patch.object(speakers, "available", return_value=True), \
                mock.patch.object(speakers, "_clip_audio", side_effect=fake_audio), \
                mock.patch.object(speakers, "embed_array", side_effect=fake_embed), \
                mock.patch.object(speakers, "CONF", 0.55):
            out = speakers.colour_phrases("src.mp4", src_in, self.PH, offset, [12.0])
        # decoded once: first phrase - 0.5 .. last phrase + 0.5 on the source clock
        self.assertEqual(tuple(round(v, 3) for v in seen["range"]), (99.5, 107.1))
        # turn times relative to the decoded range
        self.assertEqual(calls[0], (0.5, 1.3))
        self.assertEqual(calls[4], (4.5, 5.7))             # "HIGH FIVE" + "BUDDY." as one turn
        cols = [speakers.speaker_index(o[3]) for o in out]
        # voice A speaks 2.85 s of 4.65 (61 %): the celebrity, white; voice B yellow
        W, Y = speakers.WHITE, speakers.YELLOW
        self.assertEqual(cols, [W, Y, W, Y, W, W, Y])
        self.assertEqual([o[:3] for o in out], list(self.PH))  # times and text untouched

    def test_audio_failure_falls_back_to_the_celebrity(self):
        with mock.patch.object(speakers, "available", return_value=True), \
                mock.patch.object(speakers, "_clip_audio", side_effect=RuntimeError("ffmpeg")):
            out = speakers.colour_phrases("src.mp4", 0.0, self.PH, 0.0, [])
        self.assertEqual({o[3] for o in out}, {speakers.COLOURS[speakers.WHITE]})


class SeparateTest(unittest.TestCase):
    def test_cache_path_is_stable_and_range_specific(self):
        with mock.patch.dict(os.environ, {"CELEB_VOCALS_CACHE": os.path.join(os.getcwd(), "tmp_vox_test")}):
            try:
                a = separate._cache_path("missing.mp4", 1.0, 5.0)
                b = separate._cache_path("missing.mp4", 1.0, 5.0)
                c = separate._cache_path("missing.mp4", 1.0, 6.0)
            finally:
                d = os.path.join(os.getcwd(), "tmp_vox_test")
                if os.path.isdir(d) and not os.listdir(d):
                    os.rmdir(d)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertTrue(a.endswith(".npy"))

    def test_unavailable_returns_none(self):
        with mock.patch.object(separate, "available", return_value=False), \
                mock.patch.object(separate, "_cache_path", return_value="no/such/dir/x.npy"):
            self.assertIsNone(separate.vocals("missing.mp4", 0.0, 3.0))
        self.assertIsNone(separate.vocals("missing.mp4", 2.0, 2.0))   # empty range


def _present(*dirs_and_name):
    *dirs, name = dirs_and_name
    return any(os.path.isfile(os.path.join(d, name)) for d in dirs)


@unittest.skipUnless(_present(speakers.BAKED, speakers.LOCAL, speakers.MODEL_NAME),
                     "speaker model not on this machine (never downloaded by the tests)")
class ModelTest(unittest.TestCase):
    def test_embedding_is_unit_length_and_short_audio_is_none(self):
        try:
            import sherpa_onnx  # noqa: F401
        except Exception:  # noqa: BLE001
            self.skipTest("sherpa_onnx not installed")
        t = np.arange(speakers.SR * 2) / speakers.SR
        x = (0.2 * np.sin(2 * np.pi * 180 * t) * (1 + 0.5 * np.sin(2 * np.pi * 3 * t))).astype(np.float32)
        v = speakers.embed_array(x, 0.2, 1.6)
        self.assertIsNotNone(v)
        self.assertAlmostEqual(float(np.linalg.norm(v)), 1.0, places=4)
        self.assertIsNone(speakers.embed_array(x[:1000], 0.0, 0.05))


if __name__ == "__main__":
    unittest.main()
