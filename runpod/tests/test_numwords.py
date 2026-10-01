"""
Spoken numbers in digits on the date, time and number looks (the owner, 2026-10-01: "when the number
is said, like September 29 or 5 days, you show it as a word ('five days') instead of numbers - fix"):

  * src/numwords.py reads a number said in words (cardinals, ordinals, decimals, years said in pairs,
    "and a half", "a hundred and twenty") and writes the plainly numeric ones in digits, leaving names
    ("Three Rivers") and loose words ("one of the worst") alone;
  * the planner writes the date, time and number looks' words in digits;
  * the renderer's twin (remotion/src/components/lib/numWords.ts) agrees case for case (node + esbuild,
    skipped without them).
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from src import numwords, templates, treatments
from src.transcribe import Segment, Word

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REMOTION = os.path.join(ROOT, "remotion")
TWIN_TS = os.path.join(REMOTION, "src", "components", "lib", "numWords.ts")

# (said, shown)
CASES = [
    # The owner's own examples.
    ("five days", "5 days"),
    ("September twenty-ninth", "September 29"),
    ("SEPTEMBER TWENTY-NINTH", "SEPTEMBER 29"),
    ("forty-eight hours", "48 hours"),
    ("three thousand homes", "3,000 homes"),
    ("two point five inches", "2.5 inches"),
    ("a hundred and twenty", "120"),
    # Dates and years.
    ("the fifteenth of September", "September 15"),
    ("THE TWENTY-NINTH OF SEPT.", "SEPTEMBER 29"),
    ("September the twenty-first", "September 21"),
    ("May fifth", "May 5"),
    ("SEPTEMBER 29TH", "SEPTEMBER 29"),
    ("nineteen sixty-one", "1961"),
    ("nineteen oh five", "1905"),
    ("September twenty-ninth, twenty twenty-six", "September 29, 2026"),
    ("SEPTEMBER TWENTY-FIVE, TWENTY TWENTY-SIX · THREE FORTY-FIVE PM", "SEPTEMBER 25, 2026 · 3:45 PM"),
    ("in two thousand five", "in 2005"),
    ("between nineteen ninety and twenty twenty", "between 1990 and 2020"),
    # Times of day.
    ("seven thirty pm", "7:30 pm"),
    ("eleven oh five a.m.", "11:05 a.m."),
    ("twelve fifteen am", "12:15 am"),
    ("seven o'clock", "7:00"),
    ("EIGHT AM ET", "8 AM ET"),
    # Quantities.
    ("FORTY-EIGHT HOURS LATER", "48 HOURS LATER"),
    ("ONE DAY LATER", "1 DAY LATER"),
    ("Five Days Without Power", "5 Days Without Power"),
    ("eighty-seven years old", "87 years old"),
    ("seventy-five million acre-feet", "75 million acre-feet"),
    ("SEVENTY-FIVE MILLION ACRE-FEET", "75 MILLION ACRE-FEET"),
    ("half a million people", "500,000 people"),
    ("half a billion dollars", "$500 million"),
    ("one point two million dollars", "$1.2 million"),
    ("two and a half feet", "2.5 feet"),
    ("twenty-two percent", "22%"),
    ("Twenty-five percent of the lake", "25% of the lake"),
    ("FIVE STATES", "5 STATES"),
    ("THREE TIMES", "3 TIMES"),
    ("sixteen people", "16 people"),
    ("3 thousand homes", "3,000 homes"),
    ("2.5 thousand", "2,500"),
    ("a thousand and one nights", "1,001 nights"),
    ("two point oh five", "2.05"),
    ("TWENTY FIVE", "25"),
    ("FIVE", "5"),
    ("Route Sixty-Six", "Route 66"),
    # Left alone: names, loose words, ordinals outside a date, what is already digits.
    ("Three Rivers", "Three Rivers"),
    ("Seven Oaks", "Seven Oaks"),
    ("Thousand Oaks", "Thousand Oaks"),
    ("the Three Gorges Dam in China", "the Three Gorges Dam in China"),
    ("He met Seven Hills residents", "He met Seven Hills residents"),
    ("one of the worst", "one of the worst"),
    ("No one knew", "No one knew"),
    ("the second storm", "the second storm"),
    ("may fifth", "may fifth"),
    ("nine eleven", "nine eleven"),
    ("ten twenty", "ten twenty"),
    ("TUESDAY NIGHT", "TUESDAY NIGHT"),
    ("Wednesday through Thursday", "Wednesday through Thursday"),
    ("3:45 PM", "3:45 PM"),
    ("90,000 PEOPLE", "90,000 PEOPLE"),
    ("1.2 million", "1.2 million"),
    ("", ""),
]
PARSES = [("twenty-two", 22.0), ("a hundred and twenty", 120.0), ("two point five", 2.5), ("nineteen sixty-one", 1961.0),
          ("three thousand", 3000.0), ("one million two hundred thousand", 1200000.0), ("zero", 0.0),
          ("twenty-ninth", None), ("five days", None), ("a", None), ("and", None), ("Thousand", None)]
ORDINALS = [("twenty-ninth", 29), ("29th", 29), ("first", 1), ("thirty-first", 31), ("one hundred and first", 101),
            ("five", None), ("second", 2)]


class Words(unittest.TestCase):
    def test_spoken_numbers_become_digits(self):
        for said, shown in CASES:
            self.assertEqual(numwords.normalize(said), shown, said)

    def test_parse_and_ordinal(self):
        for said, value in PARSES:
            self.assertEqual(numwords.parse(said), value, said)
        for said, value in ORDINALS:
            self.assertEqual(numwords.ordinal(said), value, said)

    def test_odd_input_is_returned_as_it_came(self):
        self.assertIsNone(numwords.normalize(None))
        self.assertEqual(numwords.normalize("no numbers here"), "no numbers here")


# --------------------------------------------------------------------------- the planner
def _seg(i, text, seconds=6.0):
    words = [Word(text=w, start=i * seconds + j * 0.3, end=i * seconds + j * 0.3 + 0.25)
             for j, w in enumerate(text.split())]
    return Segment(text=text, start=i * seconds, end=(i + 1) * seconds, words=words)


def _plan(lines, shots=None):
    segs = [_seg(i, t) for i, t in enumerate(lines)]
    scenes = [{"id": f"s{i}", "startFrame": i * 180, "durationInFrames": 180,
               "media": {"type": "video", "url": f"https://x/{i}.mp4"}, "transition": "none", "motion": "none",
               "effect": "none"} for i in range(len(lines))]
    brief = {"kind": "explainer", "hookBeats": [], "sections": []}
    from src import timeline
    return treatments.plan(segs, shots or [{"subject": "Lake Mead"} for _ in lines], scenes, 30, len(lines) * 180,
                           brief, treatments.pack_for(brief, "documentary"), timeline._OVERLAY_SECONDS)


PLAIN = "Plain words about the water here."


class Planner(unittest.TestCase):
    def test_the_looks_words_are_digits(self):
        lines = ["On September twenty-ninth, the gates opened.", PLAIN,
                 "Five days later, the lake had fallen.", PLAIN,
                 "Some three thousand homes lost power.", PLAIN]
        out = _plan(lines)
        shown = [(o["template"], str(o.get("text") or ""), o.get("value")) for o in out["overlays"]]
        dates = [s for s in shown if s[0] in treatments.VR_LOOKS]
        self.assertEqual([s[1] for s in dates], ["SEPTEMBER 29"], shown)
        counts = [s for s in shown if s[2] is not None]
        self.assertTrue(counts, shown)
        for tid, text, _value in shown:
            for word in ("FIVE", "THREE", "THOUSAND", "TWENTY", "NINTH"):
                self.assertNotIn(word, text.upper(), (tid, text))

    def test_a_spoken_date_is_shown_in_digits_and_a_directors_unsaid_date_not_at_all(self):
        out = _plan(["On the twenty-ninth of September the water came.", PLAIN])
        [o] = [o for o in out["overlays"] if o["template"] in treatments.VR_LOOKS]
        self.assertEqual((o["template"], o["text"]), (treatments.VR_HERO, "SEPTEMBER 29"))
        # The director's date stamp on a line that never says the date (the owner, 2026-10-01).
        hint = {"type": "date-stamp", "text": "SEPTEMBER TWENTY-NINTH"}
        out = _plan(["The water came that week.", PLAIN], shots=[{"subject": "Lake Mead", "overlay": hint},
                                                                 {"subject": "Lake Mead"}])
        self.assertFalse([o for o in out["overlays"] if o["template"] in treatments.VR_LOOKS
                          or o["template"] in treatments.OLD_DATE_LOOKS], out["overlays"])

    def test_the_registry_keeps_the_text_style_choice(self):
        for tid in (treatments.TEXT_DATE_LOOK, treatments.BOLD_COUNT_LOOK):
            spec = templates.get(tid)["props"]["textStyle"]
            self.assertEqual(spec["options"], ["auto", "clean", "shine", "accent", "shade"], tid)


# --------------------------------------------------------------------------- the TypeScript twin
def _node():
    node = shutil.which("node")
    esbuild = os.path.join(REMOTION, "node_modules", "esbuild", "bin", "esbuild")
    return (node, esbuild) if node and os.path.isfile(esbuild) else (None, None)


HARNESS = """
import { spokenToDigits, parseNumber, ordinalNumber } from "%(twin)s";
import * as fs from "fs";
const input = JSON.parse(fs.readFileSync(0, "utf-8"));
process.stdout.write(JSON.stringify({
  normalize: input.normalize.map((s: string) => spokenToDigits(s)),
  parse: input.parse.map((s: string) => parseNumber(s)),
  ordinal: input.ordinal.map((s: string) => ordinalNumber(s)),
}));
"""


@unittest.skipUnless(all(_node()), "needs node and remotion's esbuild")
class TypeScriptTwin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node, esbuild = _node()
        cls.dir = tempfile.mkdtemp()
        entry = os.path.join(cls.dir, "harness.ts")
        with open(entry, "w", encoding="utf-8") as fh:
            fh.write(HARNESS % {"twin": TWIN_TS.replace("\\", "/")[:-3]})
        cls.bundle = os.path.join(cls.dir, "harness.cjs")
        subprocess.run([node, esbuild, entry, "--bundle", "--platform=node", "--format=cjs", f"--outfile={cls.bundle}",
                        "--log-level=error"], check=True, cwd=REMOTION, timeout=120)
        cls.node = node

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_the_twins_agree(self):
        extra = ["it may one day return", "THREE QUARTERS", "the twenty-nine of March", "Lake Mead fell for three days",
                 "one hundred and first", "a dozen homes", "forty mile creek", "point five inches", "two thousand",
                 "the year two thousand", "twenty thirty", "fifteen hundred", "two hundred five", "zero"]
        said = [c[0] for c in CASES] + extra
        payload = {"normalize": said, "parse": [p[0] for p in PARSES], "ordinal": [o[0] for o in ORDINALS]}
        run = subprocess.run([self.node, self.bundle], input=json.dumps(payload), capture_output=True, text=True,
                             encoding="utf-8", timeout=120, check=True)
        got = json.loads(run.stdout)
        for s, ts in zip(said, got["normalize"]):
            self.assertEqual(ts, numwords.normalize(s), s)
        for (s, _v), ts in zip(PARSES, got["parse"]):
            self.assertEqual(ts, numwords.parse(s), s)
        for (s, _v), ts in zip(ORDINALS, got["ordinal"]):
            self.assertEqual(ts, numwords.ordinal(s), s)


if __name__ == "__main__":
    unittest.main()
