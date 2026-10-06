import unittest

from textnorm import (int_words, normalize, ordinal_words, plan_chunks, word_error_rate, words_for_compare,
                      year_words)


class Numbers(unittest.TestCase):
    def test_int_words(self):
        self.assertEqual(int_words(0), "zero")
        self.assertEqual(int_words(21), "twenty-one")
        self.assertEqual(int_words(1050), "one thousand fifty")
        self.assertEqual(int_words(3_500_000), "three million five hundred thousand")
        self.assertEqual(int_words(-7), "minus seven")

    def test_years(self):
        self.assertEqual(year_words(1987), "nineteen eighty-seven")
        self.assertEqual(year_words(2005), "two thousand five")
        self.assertEqual(year_words(2026), "twenty twenty-six")
        self.assertEqual(year_words(1900), "nineteen hundred")
        self.assertEqual(year_words(1906), "nineteen oh six")

    def test_ordinals(self):
        self.assertEqual(ordinal_words(1), "first")
        self.assertEqual(ordinal_words(22), "twenty-second")
        self.assertEqual(ordinal_words(40), "fortieth")
        self.assertEqual(ordinal_words(112), "one hundred twelfth")


class Normalize(unittest.TestCase):
    def n(self, s):
        return normalize(s)

    def test_money(self):
        self.assertEqual(self.n("It cost $3.5 billion."), "It cost three point five billion dollars.")
        self.assertEqual(self.n("A $12 ticket."), "A twelve dollars ticket.")
        self.assertEqual(self.n("Only $1.25 each."), "Only one dollar and twenty-five cents each.")

    def test_percent_and_units(self):
        self.assertEqual(self.n("Lake Mead is 32% full."), "Lake Mead is thirty-two percent full.")
        self.assertIn("one hundred twenty miles per hour", self.n("Winds hit 120 mph."))
        self.assertIn("minus five degrees Fahrenheit", self.n("It fell to -5°F overnight."))
        self.assertIn("one thousand fifty feet", self.n("The lake dropped to 1,050 feet."))
        self.assertIn("one thousand fifty feet", self.n("The lake dropped to 1050 feet."))

    def test_round_hundreds_read_like_a_narrator(self):
        self.assertIn("twelve hundred acre-feet", self.n("It lost 1,200 acre-feet a day."))
        self.assertIn("one thousand fifty feet", self.n("The lake dropped to 1,050 feet."))
        self.assertIn("two thousand people", self.n("About 2,000 people left."))
        self.assertIn("twenty twenty-six", self.n("By 2026 the cuts begin."))

    def test_years_in_text(self):
        self.assertEqual(self.n("In 1987, the dam opened."), "In nineteen eighty-seven, the dam opened.")
        self.assertEqual(self.n("By 2030 it may be gone."), "By twenty thirty it may be gone.")
        self.assertIn("nineteen nineties", self.n("Since the 1990s, levels fell."))
        self.assertIn("twenty ten to twenty twenty", self.n("Between 2010-2020 it dropped."))

    def test_dates_and_times(self):
        self.assertIn("March fifteenth", self.n("On March 15, 2024 the river rose."))
        self.assertIn("twenty twenty-four", self.n("On March 15, 2024 the river rose."))
        self.assertIn("three forty-five p m", self.n("At 3:45 p.m. the levee broke."))

    def test_symbols_and_abbreviations(self):
        self.assertIn("U S", self.n("The U.S. government agreed."))
        self.assertIn("Doctor Smith", self.n("Dr. Smith said so."))
        self.assertNotIn("[", self.n("[whispers] It was gone."))
        self.assertEqual(self.n("Water & power"), "Water and power")
        self.assertIn("three times", self.n("A 3x increase."))

    def test_non_english_untouched(self):
        self.assertEqual(normalize("Hay 25 presas.", "es"), "Hay 25 presas.")


class Chunks(unittest.TestCase):
    TEXT = ("The Colorado River once ran all the way to the sea. Today, it rarely does. Behind Hoover Dam, "
            "Lake Mead has fallen more than one hundred and fifty feet since the year two thousand, exposing "
            "white rings of mineral on the canyon walls, abandoned marinas, and boats that sank decades ago.\n\n"
            "What happened? And what comes next for the forty million people who depend on it?")

    def test_sizes_and_pauses(self):
        chunks = plan_chunks(self.TEXT, max_chars=200)
        self.assertGreaterEqual(len(chunks), 3)
        self.assertTrue(all(len(c.text) <= 230 for c in chunks))
        self.assertTrue(chunks[-1].ends_paragraph)
        paragraph_ends = [c for c in chunks if c.ends_paragraph]
        self.assertEqual(len(paragraph_ends), 2)
        self.assertTrue(all(c.pause >= 0.6 for c in paragraph_ends))
        joined = " ".join(c.text for c in chunks)
        self.assertEqual(joined.split(), self.TEXT.split())

    def test_long_sentence_is_cut_at_a_comma(self):
        long = ("When the snow melts in the Rockies, the water runs through seven states, two countries, "
                "dozens of tribal nations, and the farms of the Imperial Valley, before it reaches the delta, "
                "where it now disappears into the sand long before the Gulf of California.")
        chunks = plan_chunks(long, max_chars=120)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c.text) <= 125 for c in chunks))
        self.assertTrue(chunks[0].text.endswith(","))

    def test_pause_scale(self):
        a = plan_chunks(self.TEXT, max_chars=200, pause_scale=1.0)
        b = plan_chunks(self.TEXT, max_chars=200, pause_scale=1.3)
        self.assertGreater(b[0].pause, a[0].pause)


class Compare(unittest.TestCase):
    def test_wer_with_digits_in_transcript(self):
        expected = words_for_compare("Lake Mead fell one thousand fifty feet in twenty twenty-two.")
        heard = words_for_compare("Lake Mead fell 1,050 feet in 2022.")
        self.assertLess(word_error_rate(expected, heard), 0.05)

    def test_wer_catches_skips(self):
        expected = words_for_compare("The river runs through seven states and two countries before the sea.")
        heard = words_for_compare("The river runs before the sea.")
        self.assertGreater(word_error_rate(expected, heard), 0.3)


if __name__ == "__main__":
    unittest.main()
