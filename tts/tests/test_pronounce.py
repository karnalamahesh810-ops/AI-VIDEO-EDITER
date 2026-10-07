"""
A channel's pronunciation list on our own voice server (textnorm.protect_pronunciations and the
handler wiring). Pure Python: the voice model, the recognizer, ffmpeg and R2 are faked.
"""
import os
import tempfile
import unittest
from unittest import mock

import numpy as np

import handler
from textnorm import apply_pronunciations, clean_pronounce, normalize, plan_chunks, protect_pronunciations

LIST = [
    {"word": "Mead", "say": "meed"},
    {"word": "Lake Mead", "say": "lake MEED"},
    {"word": "Yosemite", "say": "yo-SEM-it-ee"},
    {"word": "I-15", "say": "eye fifteen"},
    {"word": "CO2", "say": "see oh two"},
    {"word": "US", "say": "you ess", "matchCase": True},
    {"word": "O'Hare", "say": "oh HAIR"},
    {"word": "Biscuit Basin", "say": "BIS-kit BAY-sin"},
]


class Cleaning(unittest.TestCase):
    def test_keeps_well_formed_entries_only(self):
        self.assertEqual(clean_pronounce(None), [])
        self.assertEqual(clean_pronounce({"word": "Mead", "say": "meed"}), [])
        out = clean_pronounce([
            {"word": "  Lake   Mead ", "say": " lake  MEED ", "matchCase": False},
            {"word": "US", "say": "you ess", "matchCase": True},
            {"word": "", "say": "x"}, {"word": "Mead", "say": ""}, {"word": "x" * 61, "say": "y"},
            {"word": "Ok", "say": "y" * 121}, {"word": "[pause]", "say": "paws"}, {"word": "Yosemite", "say": "<b>yo</b>"},
            {"word": "!!!", "say": "bang"}, {"word": "Mead", "say": "Mead"}, {"word": 7, "say": "seven"}, "Mead",
        ])
        self.assertEqual(out, [{"word": "Lake Mead", "say": "lake MEED", "matchCase": False},
                               {"word": "US", "say": "you ess", "matchCase": True}])

    def test_first_of_a_spelling_and_at_most_300(self):
        out = clean_pronounce([{"word": "Mead", "say": "meed"}, {"word": "MEAD", "say": "mayd"},
                               {"word": "MEAD", "say": "M E A D", "matchCase": True}])
        self.assertEqual([e["say"] for e in out], ["meed", "M E A D"])
        many = [{"word": f"Place{i}", "say": f"place {i}"} for i in range(320)]
        self.assertEqual(len(clean_pronounce(many)), 300)


class SameRulesAsTheApp(unittest.TestCase):
    """The cases of src/test/pronunciations.test.ts ("saying a text the channel way"), word for word."""

    def say(self, text, entries=LIST):
        return apply_pronunciations(text, entries)

    def test_whole_words_only(self):
        self.assertEqual(self.say("The Meadow and Meadows near Mead."), "The Meadow and Meadows near meed.")
        self.assertEqual(self.say("Take I-15 north, not I-150."), "Take eye fifteen north, not I-150.")
        self.assertEqual(self.say("CO2 and CO2e and 2CO2."), "see oh two and CO2e and 2CO2.")

    def test_capitals(self):
        self.assertEqual(self.say("MEAD, mead and Mead."), "meed, meed and meed.")
        self.assertEqual(self.say("The US told us."), "The you ess told us.")

    def test_longest_first_and_one_pass(self):
        self.assertEqual(self.say("Lake Mead is low; Mead is low."), "lake MEED is low; meed is low.")
        chain = [{"word": "Mead", "say": "Meed"}, {"word": "Meed", "say": "WRONG"}]
        self.assertEqual(self.say("Mead and Meed", chain), "Meed and WRONG")

    def test_punctuation_and_phrases(self):
        self.assertEqual(self.say('(Yosemite), "Yosemite!" Yosemite\'s falls'),
                         '(yo-SEM-it-ee), "yo-SEM-it-ee!" yo-SEM-it-ee\'s falls')
        self.assertEqual(self.say("Biscuit  Basin / Biscuit\nBasin / Biscuit\n\nBasin"),
                         "BIS-kit BAY-sin / BIS-kit BAY-sin / Biscuit\n\nBasin")

    def test_apostrophes_hyphens_and_stage_directions(self):
        self.assertEqual(self.say("Flights from O’Hare on I‑15."), "Flights from oh HAIR on eye fifteen.")
        self.assertEqual(self.say("[pause] then a pause", [{"word": "pause", "say": "pawz"}]), "[pause] then a pawz")


class AroundTheNumberReading(unittest.TestCase):
    def test_matches_the_text_as_written_and_keeps_the_respelling_away_from_normalize(self):
        entries = [{"word": "I-15", "say": "eye fifteen"}, {"word": "US-93", "say": "U S 93"},
                   {"word": "NOAA", "say": "N.O.A.A."}]
        text = "Take I-15 to US-93 in 1987, says NOAA."
        said = protect_pronunciations(text, entries)
        self.assertEqual(said.count, 3)
        self.assertEqual(said.words, 3)
        chunks = plan_chunks(normalize(said.text))
        self.assertEqual(len(chunks), 1)
        voice = said.for_voice(chunks[0].text)
        check = said.for_check(chunks[0].text)
        # The respellings exactly as written (no "ninety-three", no "N O A A"); the rest read as usual.
        self.assertEqual(voice, "Take eye fifteen to U S 93 in nineteen eighty-seven, says N.O.A.A..")
        # The check compares with what a listener would write: the words themselves, normalized.
        self.assertEqual(check, "Take I-fifteen to US-ninety-three in nineteen eighty-seven, says NOAA.")
        for t in (voice, check):
            self.assertNotIn("zqv", t.lower())

    def test_the_sentence_and_pause_rules_see_what_they_saw_before(self):
        text = "We drove past Lake Mead. Yosemite was next.\n\nThen O'Hare."
        entries = [{"word": "Lake Mead", "say": "lake meed"}, {"word": "Yosemite", "say": "yo-SEM-it-ee"},
                   {"word": "O'Hare", "say": "oh HAIR"}]
        before = plan_chunks(normalize(text), max_chars=30, min_chars=10)
        said = protect_pronunciations(text, entries)
        after = plan_chunks(normalize(said.text), max_chars=30, min_chars=10)
        self.assertEqual(len(after), len(before))
        self.assertEqual([c.pause for c in after], [c.pause for c in before])
        self.assertEqual([c.ends_paragraph for c in after], [c.ends_paragraph for c in before])
        self.assertEqual([said.for_check(c.text) for c in after], [c.text for c in before])
        self.assertEqual([said.for_voice(c.text) for c in after],
                         ["We drove past lake meed.", "yo-SEM-it-ee was next.", "Then oh HAIR."])

    def test_abbreviation_rules_around_a_word_still_work(self):
        said = protect_pronunciations("Mt. Rainier rose.", [{"word": "Rainier", "say": "ray-NEER"}])
        self.assertEqual(said.for_voice(normalize(said.text)), "Mount ray-NEER rose.")

    def test_no_match_leaves_the_text_alone(self):
        said = protect_pronunciations("Nothing to change.", LIST)
        self.assertEqual((said.text, said.count), ("Nothing to change.", 0))
        self.assertEqual(said.for_voice("x"), "x")

    def test_placeholder_letters_already_in_the_text(self):
        text = "Zqv and vqz near Mead."
        said = protect_pronunciations(text, LIST)
        self.assertEqual(said.count, 1)
        self.assertEqual(said.for_voice(normalize(said.text)), "Zqv and vqz near meed.")

    def test_other_languages(self):
        said = protect_pronunciations("Hay 25 presas cerca de Mead.", LIST, "es")
        self.assertEqual(said.for_voice(normalize(said.text, "es")), "Hay 25 presas cerca de meed.")


class FakePool:
    n = 0
    broken = {}

    def __init__(self):
        self.tasks = []

    def heal(self):
        return False

    def run(self, tasks, on_done=None):
        self.tasks.extend(tasks)
        if tasks and tasks[0].get("op") == "part":
            n = len(tasks[0]["texts"])
            return [{"sr": 24000, "gen_seconds": 1.0, "wavs": [np.zeros(240, np.float32)] * n,
                     "checks": [{"wer": 0.0, "ratio": 1.0, "seconds": 0.01}] * n, "attempts": [1] * n}]
        return [{"wav": np.zeros(240, np.float32), "check": {"wer": 0.0, "ratio": 1.0, "seconds": 0.01},
                 "attempts": 1, "gen_seconds": 0.1} for _ in tasks]


class Handler(unittest.TestCase):
    TEXT = "Lake Mead fell 12 feet in 2022. Yosemite saw record crowds."

    def run_tts(self, inp, engine):
        pool = FakePool()
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp.close()

        def finish(track, sr, out_path, fmt="mp3", speed=1.0):
            with open(out_path, "wb") as f:
                f.write(b"ID3")
            return {"seconds": 1.0, "bytes": 3}

        with mock.patch.object(handler, "POOL", pool), mock.patch.object(handler, "ENGINE", engine), \
                mock.patch.object(handler, "resolve_voice", return_value=("preset-x:abc", "/tmp/ref.wav", {})), \
                mock.patch.object(handler.audio, "stitch", return_value=np.zeros(10, np.float32)), \
                mock.patch.object(handler.audio, "temp_path", return_value=tmp.name), \
                mock.patch.object(handler.audio, "finish", side_effect=finish), \
                mock.patch.object(handler.r2, "enabled", return_value=False):
            answer = handler.tts(dict(inp, voice={"url": "https://x/ref.wav", "key": "preset-x", "text": "ref"}), "job-1", lambda d: None)
        if os.path.exists(tmp.name):
            os.remove(tmp.name)
        return answer, pool.tasks

    def test_without_pronounce_the_job_is_exactly_as_before(self):
        for engine in ("qwen", "chatterbox"):
            answer, tasks = self.run_tts({"text": self.TEXT, "seed": 7}, engine)
            self.assertTrue(answer["ok"])
            self.assertNotIn("pronounced", answer)
            expected = [c.text for c in plan_chunks(normalize(self.TEXT), max_chars=360 if engine == "qwen" else 280)]
            if engine == "qwen":
                self.assertEqual(list(tasks[0].keys()), ["op", "voice_key", "ref_path", "ref_text", "texts", "params",
                                                         "seed", "validate", "max_attempts", "lang"])
                self.assertEqual(tasks[0]["texts"], expected)
            else:
                self.assertEqual([t["text"] for t in tasks], expected)
                self.assertTrue(all("check_text" not in t for t in tasks))

    def test_with_pronounce_the_model_reads_the_respelling_and_the_check_hears_the_word(self):
        pronounce = [{"word": "Mead", "say": "meed", "matchCase": False},
                     {"word": "Yosemite", "say": "yo-SEM-it-ee", "matchCase": False}]
        answer, tasks = self.run_tts({"text": self.TEXT, "seed": 7, "pronounce": pronounce}, "qwen")
        self.assertEqual(answer["pronounced"], 2)
        self.assertEqual(tasks[0]["texts"], ["Lake meed fell twelve feet in twenty twenty-two. yo-SEM-it-ee saw record crowds."])
        self.assertEqual(tasks[0]["check_texts"], ["Lake Mead fell twelve feet in twenty twenty-two. Yosemite saw record crowds."])
        answer, tasks = self.run_tts({"text": self.TEXT, "seed": 7, "pronounce": pronounce}, "chatterbox")
        self.assertEqual([t["text"] for t in tasks], ["Lake meed fell twelve feet in twenty twenty-two. yo-SEM-it-ee saw record crowds."])
        self.assertEqual([t["check_text"] for t in tasks], ["Lake Mead fell twelve feet in twenty twenty-two. Yosemite saw record crowds."])

    def test_a_list_with_nothing_in_this_part_changes_nothing_but_says_so(self):
        answer, tasks = self.run_tts({"text": self.TEXT, "pronounce": [{"word": "Hoover", "say": "HOO-ver"}]}, "qwen")
        self.assertEqual(answer["pronounced"], 0)
        self.assertNotIn("check_texts", tasks[0])
        answer, tasks = self.run_tts({"text": self.TEXT, "pronounce": "not a list"}, "qwen")
        self.assertNotIn("pronounced", answer)


class Engines(unittest.TestCase):
    def test_qwen_checks_each_piece_against_its_check_text(self):
        from engine_qwen import QwenHost
        host = QwenHost(device="cpu", want_asr=False)
        host.model = mock.Mock()
        host.model.generate_voice_clone.return_value = ([np.zeros(24000, np.float32), np.zeros(24000, np.float32)], 24000)
        host.prompts["k"] = object()
        seen = []

        def check(text, wav, lang, use_asr):
            seen.append(text)
            return {"seconds": 1.0, "ratio": 1.0, "wer": 0.0, "ok": True, "score": 0.0}

        with mock.patch.object(host, "check", side_effect=check), mock.patch("engine_qwen.seed_all"), \
                mock.patch("engine_qwen.trim", side_effect=lambda w, sr: w):
            host.run_part({"texts": ["lake meed.", "yo-SEM-it-ee."], "check_texts": ["Lake Mead.", "Yosemite."],
                           "voice_key": "k", "ref_path": "/x.wav", "seed": 1})
            host.run_part({"texts": ["Plain one.", "Plain two."], "voice_key": "k", "ref_path": "/x.wav", "seed": 1})
        self.assertEqual(seen, ["Lake Mead.", "Yosemite.", "Plain one.", "Plain two."])

    def test_chatterbox_checks_a_chunk_against_its_check_text(self):
        from engine import ModelHost
        host = ModelHost(device="cpu", want_asr=False)
        seen = []

        def check(text, wav, lang, use_asr):
            seen.append(text)
            return {"seconds": 1.0, "ratio": 1.0, "wer": 0.0, "ok": True, "score": 0.0}

        with mock.patch.object(host, "load"), mock.patch.object(host, "generate", return_value=np.zeros(24000, np.float32)), \
                mock.patch.object(host, "check", side_effect=check), mock.patch("engine.trim", side_effect=lambda w, sr, cut_end=0.0: w):
            host.run_chunk({"model": "en", "text": "lake meed.", "check_text": "Lake Mead.", "voice_key": "k", "params": {}, "seed": 1})
            host.run_chunk({"model": "en", "text": "Plain.", "voice_key": "k", "params": {}, "seed": 1})
        self.assertEqual(seen, ["Lake Mead.", "Plain."])


if __name__ == "__main__":
    unittest.main()
