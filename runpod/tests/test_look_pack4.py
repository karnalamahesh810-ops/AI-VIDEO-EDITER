"""
Looks pack 4 (2026-10-08, the owner: "it's not a weather channel creating tool ... it needs to do everything"): twelve
general looks for every faceless niche (remotion/src/components/lib/LibKtPack4.tsx, LibKtCards4.tsx;
scripts/library_looks_ktpack4.json) and two cuts (remotion/src/transitions/TransitionFrame.tsx).

  - registered (family "ktp4", template ids KT_*), the planner may pick each, with its least time, its built-in sound,
    its editor sample and its motion class; the cuts in the registry, the renderer and the styles' turns;
  - drawn by the renderer, sized from the one type scale (nothing a viewer reads under 24 px at 1080p), never the
    retired style, every picture through SafeImg, on frosted glass that really frosts;
  - picked only where the narration says what they show - finance, business, tech, history, biography, true crime,
    social, science, health, education, food, sports, travel, gaming, politics - with the narration's own words, each
    part on its own word, and never on lines that only look like them;
  - planned with pack 3 in one pass (the more specific look takes the words), spaced as one (24 s apart, two a
    minute, each look its own gap and cap), in place of an older look that says the same, on the relook action too;
  - a person's card shows their portrait only from a scene of that person; the cards take the calm side.
Offline: no network, no paid calls.
"""
import json
import os
import re
import unittest

from src import datalooks as dl
from src import lookpack3 as p3
from src import lookpack4 as p4
from src import lookplace, overlayimages, relook, templates, timeline, treatments

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REMOTION = os.path.join(ROOT, "remotion", "src")
LIB = os.path.join(REMOTION, "components", "lib")
FPS = 30
PACK = ["KT_PRICE", "KT_MONEY", "KT_TABLE", "KT_PROSCONS", "KT_PODIUM", "KT_VERSUS", "KT_PROFILE", "KT_STEPS",
        "KT_CHAIN", "KT_CASE", "KT_POST", "KT_FACTCHECK"]
FILES = {"LibKtPack4.tsx": ["kt-price", "kt-money", "kt-table", "kt-proscons", "kt-podium", "kt-versus"],
         "LibKtCards4.tsx": ["kt-profile", "kt-steps", "kt-chain", "kt-case", "kt-post", "kt-factcheck"]}

# One line a niche, and the look its words call for (the planner's own reading of narration across the product's
# niches; the owner: "it needs to do everything").
NICHE_LINES = [
    ("finance", "Bitcoin went from $1,000 in January 2017 to nearly $20,000 by December, then crashed to $3,200 a "
                "year later.", p4.PRICE),
    ("business", "In 2012, Facebook paid $1 billion for Instagram.", p4.MONEY),
    ("tech", "The iPhone 15 has 6 GB of RAM and a 48 megapixel camera, while the Pixel 8 has 8 GB of RAM and a 50 "
             "megapixel camera.", p4.TABLE),
    ("history", "The 1929 crash led to mass unemployment, which triggered bank runs, which caused the Great "
                "Depression.", p4.CHAIN),
    ("biography", "Steve Jobs, the co-founder of Apple, was born in 1955 in San Francisco.", p4.PROFILE),
    ("true crime", "On the night of June 4, 1998, Jenny Lin vanished from her home in Rockford, Illinois. The case "
                   "remains unsolved to this day.", p4.CASE),
    ("social", 'One user on Reddit wrote: "This is the worst update they have ever shipped." It racked up 12,000 '
               'upvotes.', p4.POST),
    ("science", "You may have heard that we only use 10 percent of our brains. That's a myth. In reality, we use "
                "virtually every part of the brain.", p4.FACTCHECK),
    ("health", "The benefits are weight loss, better sleep and more energy. The drawbacks are hunger and headaches.",
     p4.PROSCONS),
    ("education", "Here's how to start investing. First, open a brokerage account. Second, set up an automatic "
                  "monthly deposit. Third, buy a low-cost index fund.", p4.STEPS),
    ("food", "Step one: whisk the eggs and sugar. Step two: fold in the flour. Step three: bake for 25 minutes.",
     p4.STEPS),
    ("sports", "In the 2022 World Cup final, Argentina beat France 4-2 on penalties.", p4.VERSUS),
    ("travel", "The three most visited cities in the world are Bangkok, Paris and London.", p4.PODIUM),
    ("gaming", "In the grand final, Team Liquid defeated Fnatic 3-1.", p4.VERSUS),
    ("politics", "Obama won 365 electoral votes to McCain's 173.", p4.VERSUS),
    ("history battles", "At Cannae, 50,000 Carthaginians faced 86,000 Romans.", p4.VERSUS),
    ("food prices", "A Big Mac cost $0.45 in 1967, $1.60 in 1986 and $5.69 today.", p4.PRICE),
    ("olympics", "In the 2008 Olympic final, Usain Bolt took gold, Richard Thompson silver and Walter Dix bronze.",
     p4.PODIUM),
]

# Lines that only look like a look's: nothing of pack 4 is drawn on them.
NEGATIVES = [
    "It was the first time anyone had climbed it. The second attempt failed.",
    "Our company was born in a garage.",
    "This caused problems.",
    "You may have heard about the new law.",
    "The heart beat 72 times a minute.",
    "It cost $25 to get in.",
    "Apple is worth $3 trillion, Microsoft $2.8 trillion and Google $2 trillion.",
    "The pros know it well.",
    "Phoenix just endured 31 straight days above 110 degrees.",
]


def words_for(lines, per_word=0.32):
    out = []
    for t, line in lines:
        for tok in line.split(" "):
            if tok:
                out.append({"text": tok, "start": round(t, 3), "end": round(t + per_word - 0.02, 3)})
                t += per_word
    return out


def found(line, start=0.0):
    got, _log = p4.find(dl.Narration(words_for([(start, line)])), ok=lambda tid: True)
    return got


def one(line, tid):
    got = [c for c in found(line) if c["tid"] == tid]
    return got[0] if got else None


def doc_for(lines, overlays=(), seconds=None, scenes=None):
    words = words_for(lines)
    total = int((seconds or (max(w["end"] for w in words) + 12.0)) * FPS)
    sc = scenes or [{"id": "s0", "startFrame": 0, "durationInFrames": total, "text": "", "words": words,
                     "media": {"type": "video", "url": "https://x/0.mp4"}}]
    if scenes:
        sc[0]["words"] = words
    return {"fps": FPS, "width": 1920, "height": 1080, "durationInFrames": total, "overlays": list(overlays), "sfx": [],
            "scenes": sc}


def said_at(words, token):
    return next(w["start"] for w in words if w["text"].strip(",.:\"“”") == token)


class Registered(unittest.TestCase):
    def test_twelve_looks_the_planner_may_pick_with_their_least_time_sound_and_sample(self):
        for tid in PACK:
            t = templates.get(tid)
            self.assertTrue(t, tid)
            self.assertTrue(treatments.auto_ok(tid), tid)
            self.assertEqual(templates.family(t), "ktp4", tid)
            self.assertEqual(t["defaults"]["variant"], p4.variant_of(tid), tid)
            least = float(t["defaults"].get("leastSeconds") or 0)
            self.assertGreaterEqual(least, 3.0, tid)
            self.assertGreaterEqual(float(t["defaults"]["duration"]), least, tid)
            self.assertGreaterEqual(treatments.animation_seconds(t), least, tid)
            self.assertTrue(t["defaults"]["sounds"], tid)
            self.assertIsInstance(t["defaults"].get("sample"), dict, tid)
            self.assertEqual(t["kind"], "tag", tid)                     # they ride on the footage
            self.assertFalse(t.get("retired"), tid)
        self.assertEqual(set(PACK), set(p4.IDS))
        self.assertEqual(templates.check(), [])

    def test_the_samples_are_from_many_niches_and_never_weather(self):
        samples = json.dumps([templates.get(t)["defaults"]["sample"] for t in PACK]).lower()
        for weather in ("rain", "storm", "flood", "drought", "lake mead", "hurricane", "inches", "tornado", "snow"):
            self.assertIsNone(re.search(rf"\b{weather}\b", samples), weather)

    def test_every_look_fits_the_planners_minimum_on_its_sample(self):
        for tid in PACK:
            t = templates.get(tid)
            ov = {"template": tid, **t["defaults"]["sample"]}
            self.assertLessEqual(p4.min_seconds(ov, dl.EXIT), float(t["defaults"]["duration"]) + 1.0, tid)


class Drawn(unittest.TestCase):
    def test_the_renderer_draws_each_one_and_the_index_lists_it(self):
        with open(os.path.join(LIB, "index.ts"), encoding="utf-8") as fh:
            index = fh.read()
        for name, variants in FILES.items():
            with open(os.path.join(LIB, name), encoding="utf-8") as fh:
                src = fh.read()
            drawn = set(re.findall(r'"(kt-[a-z-]+)": guard\(', src[src.index("export const LOOKS"):]))
            self.assertEqual(drawn, set(variants), name)
            for v in variants:
                self.assertIn(f'"{v}"', index, v)

    def test_the_motion_classes_cards_on_the_footage(self):
        with open(os.path.join(REMOTION, "components", "motion", "lookClasses.json"), encoding="utf-8") as fh:
            classes = json.load(fh)["looks"]
        for tid in PACK:
            self.assertIn(classes.get(tid), ("panel", "text", "tag"), tid)     # never a full-frame takeover
        self.assertEqual((classes["KT_MONEY"], classes["KT_VERSUS"], classes["KT_CHAIN"]), ("text", "tag", "text"))

    def test_sizes_from_the_one_scale_readable_on_a_phone(self):
        with open(os.path.join(LIB, "typeScale.json"), encoding="utf-8") as fh:
            pack = json.load(fh)["pack4"]
        cap = 0.727
        for role, v in pack.items():
            if "share" in v and role not in ("portrait", "stepRing"):
                self.assertGreaterEqual(v["share"] / cap * 1080, 24.0, role)
        for card in ("priceCard", "tableCard", "profileCard", "stepsCard", "caseCard", "postCard", "factCard", "podiumCard"):
            self.assertLessEqual(pack[card]["w"], 0.45, card)                 # a card, not a takeover
        self.assertLessEqual(pack["moneyFigure"]["share"], 0.11)               # a figure, not a poster

    def test_never_the_retired_style_never_a_raw_picture_and_real_frosted_glass(self):
        for name in list(FILES) + ["frost.tsx"]:
            with open(os.path.join(LIB, name), encoding="utf-8") as fh:
                src = fh.read()
            for bad in ("WebkitTextStroke", "-webkit-text-stroke", "#FFD400", "ANTON", "Bebas", "Anton", "<Img", "<img"):
                self.assertNotIn(bad, src, (name, bad))
        for name in FILES:
            with open(os.path.join(LIB, name), encoding="utf-8") as fh:
                src = fh.read()
            self.assertIn('from "./frost"', src, name)
            self.assertNotIn("<Glass", src, name)        # (Glass clips its frosted layer's parent: the backdrop is lost)
        with open(os.path.join(LIB, "frost.tsx"), encoding="utf-8") as fh:
            frost = fh.read()
        self.assertIn("backdropFilter", frost)

    def test_the_two_cuts_are_registered_drawn_and_in_the_styles_turns(self):
        reg = templates.load()
        values = {t["value"]: t for t in reg["transitions"]}
        with open(os.path.join(REMOTION, "types.ts"), encoding="utf-8") as fh:
            types = fh.read()
        with open(os.path.join(REMOTION, "transitions", "TransitionFrame.tsx"), encoding="utf-8") as fh:
            frame = fh.read()
        with open(os.path.join(REMOTION, "transitions", "timing.ts"), encoding="utf-8") as fh:
            timing = fh.read()
        for v in p4.TRANSITIONS:
            self.assertIn(v, values, v)
            self.assertIn(v, timeline.TRANSITIONS, v)
            self.assertIn(v, timeline._TRANSITION_SFX, v)
            self.assertIn(f'"{v}"', types, v)
            self.assertIn(f'case "{v}"', frame, v)
            self.assertTrue(f'"{v}":' in timing or f"{v}:" in timing, v)
        cycles = {s: spec["cycle"] for s, spec in timeline._STYLE_TRANSITIONS.items()}
        for s in ("explainer", "news", "compilation", "trending"):
            self.assertIn("card-zoom", cycles[s], s)
        for s in ("history", "story"):
            self.assertIn("shutter", cycles[s], s)
        self.assertNotIn("card-zoom", cycles["documentary"])                    # the documentary turn is unchanged
        self.assertNotIn("shutter", cycles["documentary"])
        for s, cyc in cycles.items():
            for v in p4.TRANSITIONS:
                self.assertLessEqual(cyc.count(v), 1, (s, v))


class Niches(unittest.TestCase):
    def test_a_line_from_each_niche_takes_its_look(self):
        niches = set()
        for niche, line, tid in NICHE_LINES:
            got = [c["tid"] for c in found(line)]
            self.assertIn(tid, got, (niche, line, got))
            niches.add(niche.split()[0])
        self.assertGreaterEqual(len(niches), 12)

    def test_lines_that_only_look_like_them_draw_none_of_the_pack(self):
        for line in NEGATIVES:
            got = [c["tid"] for c in found(line) if c["tid"] in p4.IDS]
            self.assertEqual(got, [], line)


class Rules(unittest.TestCase):
    def test_a_price_series_lands_each_price_on_its_word_with_its_time_and_callout(self):
        c = one("Bitcoin went from $1,000 in January 2017 to nearly $20,000 by December, then crashed to $3,200 a year "
                "later.", p4.PRICE)
        p = c["props"]
        self.assertEqual((p["text"], p["prefix"]), ("Bitcoin", "$"))
        self.assertEqual([it["value"] for it in p["items"]], [1000, 20000, 3200])
        self.assertEqual([it["label"] for it in p["items"]], ["Jan 2017", "Dec", ""])      # a time is its own figure's
        self.assertEqual(p["items"][2]["text"], "Crash")
        ats = [it["at"] for it in p["items"]]
        self.assertEqual(ats, sorted(ats))
        c = one("GameStop shares peaked at $483 in January 2021 before collapsing to $40 a few weeks later.", p4.PRICE)
        self.assertEqual((c["props"]["text"], c["props"]["items"][0]["text"]), ("GameStop shares", "Peak"))
        c = one("A Big Mac cost $0.45 in 1967, $1.60 in 1986 and $5.69 today.", p4.PRICE)
        self.assertEqual([it["label"] for it in c["props"]["items"]], ["1967", "1986", "Today"])
        self.assertEqual(c["props"]["text"], "Big Mac price")

    def test_a_from_to_of_two_prices_stays_a_change_and_values_of_different_names_a_ranking(self):
        self.assertIsNone(one("Shares of the company rose from $17 to $483 in just two weeks.", p4.PRICE))
        self.assertIsNotNone(one("Shares of the company rose from $17 to $483 in just two weeks.", p3.DELTA))
        self.assertIsNone(one("Apple is worth $3 trillion, Microsoft $2.8 trillion and Google $2 trillion.", p4.PRICE))

    def test_a_big_sum_with_who_and_what_it_was(self):
        c = one("In 2012, Facebook paid $1 billion for Instagram.", p4.MONEY)
        self.assertEqual((c["props"]["value"], c["props"]["prefix"], c["props"]["suffix"]), (1, "$", "BILLION"))
        self.assertEqual((c["props"]["label"], c["props"]["subtitle"]), ("FACEBOOK", "For Instagram, in 2012"))
        c = one("Facebook paid $1 billion for Instagram.", p4.MONEY)
        self.assertEqual(c["props"]["subtitle"], "For Instagram")
        c = one("By 2021, the company was worth $2.5 billion.", p4.MONEY)
        self.assertEqual((c["props"]["label"], c["props"]["subtitle"]), ("BY 2021", "The company"))
        c = one("The Obama Presidential Center will cost about $830 million.", p4.MONEY)
        self.assertEqual((c["props"]["label"], c["props"]["subtitle"]), ("ABOUT", "The Obama Presidential Center"))
        c = one("The thieves walked away with more than $100 million in diamonds.", p4.MONEY)
        self.assertEqual((c["props"]["value"], c["props"]["label"]), (100, "MORE THAN"))
        self.assertIsNone(one("It cost $25 to get in.", p4.MONEY))                         # a small sum is a figure
        self.assertIsNone(one("The ticket was $250,000.", p4.MONEY))
        # two sums or more: a comparison or a series, never one of them alone as the big sum
        self.assertIsNone(one("Apple is worth $3 trillion, Microsoft $2.8 trillion and Google $2 trillion.", p4.MONEY))
        self.assertIsNone(one("The company lost $2 billion in 2022, after losing $1.5 billion the year before.", p4.MONEY))

    def test_a_table_of_two_sides_each_cell_on_its_word(self):
        c = one("Messi scored 672 goals in 778 games. Ronaldo scored 701 goals in 1,000 games.", p4.TABLE)
        p = c["props"]
        self.assertEqual(p["text"], "Messi vs Ronaldo")
        self.assertEqual([(it["label"], it["value"]) for it in p["items"]],
                         [("Goals", 672), ("Games", 778), ("Goals", 701), ("Games", 1000)])
        c = one("In 1970 a gallon of gas cost 36 cents, a new car $3,500 and the average home $23,000. Today gas is "
                "$3.50, a car $48,000 and a home $420,000.", p4.TABLE)
        self.assertEqual(c["props"]["text"], "1970 vs Today")
        self.assertEqual([it["label"] for it in c["props"]["items"]][:3], ["Gas", "Car", "Home"])
        self.assertEqual(c["props"]["items"][0].get("suffix"), "¢")
        c = one("The iPhone 15 has 6 GB of RAM and a 48 megapixel camera, while the Pixel 8 has 8 GB of RAM and a 50 "
                "megapixel camera.", p4.TABLE)
        self.assertEqual(c["props"]["text"], "iPhone 15 vs Pixel 8")             # the model number is the name's
        self.assertEqual([it.get("suffix") for it in c["props"]["items"]], ["GB", "MP", "GB", "MP"])
        self.assertIsNone(one("Messi scored 672 goals in 778 games.", p4.TABLE))       # one side is no table

    def test_pros_and_cons_each_on_its_word(self):
        c = one("The upside: lower fees and faster transfers. The downside: wild price swings and almost no "
                "regulation.", p4.PROSCONS)
        self.assertEqual([(it["label"], it["value"]) for it in c["props"]["items"]],
                         [("Lower fees", 1), ("Faster transfers", 1), ("Wild price swings", -1),
                          ("Almost no regulation", -1)])
        self.assertIsNone(one("The pros know it well. The downside is the cost.", p4.PROSCONS))
        # what they are the pros of, as said: the card's title
        c = one("The upside of electric cars: lower running costs and instant torque. The downside: a higher price up "
                "front and slow charging.", p4.PROSCONS)
        self.assertEqual((c["props"]["text"], c["props"]["items"][0]["label"]), ("Electric cars", "Lower running costs"))
        c = one("Electric cars have clear benefits: lower running costs and instant torque. The drawbacks are a higher "
                "price up front and slow charging.", p4.PROSCONS)
        self.assertEqual(c["props"]["text"], "Electric cars")
        c = one("The benefits of fasting are weight loss, better sleep and more energy. The drawbacks are hunger and "
                "headaches.", p4.PROSCONS)
        self.assertEqual((c["props"]["text"], len(c["props"]["items"])), ("Fasting", 5))

    def test_a_persons_card_with_the_facts_said(self):
        line = "Steve Jobs, the co-founder of Apple, was born in 1955 in San Francisco."
        c = one(line, p4.PROFILE)
        self.assertEqual((c["props"]["text"], c["props"]["subtitle"]), ("Steve Jobs", "Co-founder of Apple"))
        self.assertEqual([(it["label"], it["text"]) for it in c["props"]["items"]], [("Born", "1955 · San Francisco")])
        born = said_at(words_for([(0.0, line)]), "born")
        self.assertAlmostEqual(c["at"] + c["props"]["items"][0]["at"], born, delta=0.1)      # on its word
        c = one("Abraham Lincoln was born on February 12, 1809 in Kentucky. He died in 1865.", p4.PROFILE)
        self.assertEqual([(it["label"], it["text"]) for it in c["props"]["items"]],
                         [("Born", "Feb 12, 1809 · Kentucky"), ("Died", "1865")])
        c = one("Sarah Collins, 34, a nurse from Dayton, Ohio, was last seen leaving work.", p4.PROFILE)
        self.assertEqual((c["props"]["subtitle"], [(it["label"], it["text"]) for it in c["props"]["items"]]),
                         ("Nurse", [("Age", "34"), ("From", "Dayton, Ohio")]))
        c = one("Police say 34-year-old nurse Sarah Collins was last seen on March 3, 2019.", p4.PROFILE)
        self.assertIn(("Last seen", "Mar 3, 2019"), [(it["label"], it["text"]) for it in c["props"]["items"]])
        self.assertIsNone(one("Our company was born in a garage.", p4.PROFILE))
        self.assertIsNone(one("San Francisco was founded in 1776.", p4.PROFILE))

    def test_steps_said_close_together_are_one_list_and_far_apart_one_card_each(self):
        c = one("Here's how to start investing. First, open a brokerage account. Second, set up an automatic monthly "
                "deposit. Third, buy a low-cost index fund. Finally, leave it alone for years.", p4.STEPS)
        p = c["props"]
        self.assertEqual(p["text"], "How to start investing")
        self.assertEqual([it["label"] for it in p["items"]], ["Open a brokerage account", "Set up an automatic monthly deposit",
                                                               "Buy a low-cost index fund", "Leave it alone for years"])
        self.assertEqual(p["total"], 4)
        lines = [(0.0, "First, find the right agency."), (40.0, "Second, file a written request."),
                 (80.0, "Third, wait for the reply.")]
        got = [c for c in p4.find(dl.Narration(words_for(lines)), ok=lambda tid: True)[0] if c["tid"] == p4.STEPS]
        self.assertEqual(len(got), 3)
        self.assertEqual([len(c["props"]["items"]) for c in got], [1, 2, 3])
        self.assertNotIn("at", got[2]["props"]["items"][0])                     # the steps so far, checked
        self.assertEqual(got[2]["props"]["items"][2]["at"], 0.07)               # the new one on its word
        self.assertIsNone(one("It was the first time anyone had climbed it. The second attempt failed.", p4.STEPS))

    def test_a_chain_of_causes(self):
        c = one("The 1929 crash led to mass unemployment, which triggered bank runs, which caused the Great "
                "Depression.", p4.CHAIN)
        self.assertEqual([it["label"] for it in c["props"]["items"]],
                         ["The 1929 crash", "Mass unemployment", "Bank runs", "The Great Depression"])
        c = one("Rising ocean temperatures caused coral bleaching. That triggered the collapse of entire reef "
                "ecosystems.", p4.CHAIN)
        self.assertEqual(len(c["props"]["items"]), 3)                          # "That triggered ..." goes on
        self.assertIsNone(one("This caused problems.", p4.CHAIN))

    def test_a_case_file_with_its_status_on_its_word(self):
        c = one("On the night of June 4, 1998, Jenny Lin vanished from her home in Rockford, Illinois. The case "
                "remains unsolved to this day.", p4.CASE)
        self.assertEqual(c["props"]["text"], "The Jenny Lin case")
        self.assertEqual([(it["label"], it["text"]) for it in c["props"]["items"]],
                         [("Date", "Jun 4, 1998"), ("Location", "Rockford, Illinois"), ("Status", "Unsolved")])
        c = one("On November 24, 1971, a man known as D. B. Cooper hijacked a flight out of Portland, Oregon. The case "
                "remains unsolved.", p4.CASE)
        self.assertEqual(c["props"]["text"], "The D. B. Cooper case")               # (initials never end a sentence)
        c = one("The disappearance of Asha Degree in Shelby, North Carolina in 2000 remains one of the strangest "
                "cases. Police say it is still open.", p4.CASE)
        self.assertEqual(c["props"]["text"], "Disappearance of Asha Degree")
        self.assertIn(("Status", "Open"), [(it["label"], it["text"]) for it in c["props"]["items"]])

    def test_a_post_shows_only_what_was_said(self):
        c = one('In August 2018, Elon Musk tweeted: "Am considering taking Tesla private at $420. Funding secured." '
                'The post got 80,000 likes.', p4.POST)
        p = c["props"]
        self.assertEqual((p["label"], p["subtitle"], p["value"], p["suffix"]), ("Elon Musk", "Aug 2018", 80000, "likes"))
        self.assertNotIn("highlight", p)                                         # no platform was named
        c = one('One user on Reddit wrote: "This is the worst update they have ever shipped."', p4.POST)
        self.assertEqual((c["props"]["label"], c["props"]["highlight"]), ("User", "Reddit"))
        self.assertNotIn("value", c["props"])                                    # no likes were said
        c = one('The account @spacefan99 posted: "Launch day is finally here."', p4.POST)
        self.assertEqual((c["props"]["label"], c["props"]["subtitle"]), ("spacefan99", "@spacefan99"))
        # the time its sentence opens with is the post's date, beside the handle
        c = one('On March 3, 2021, the account @spacefan99 posted: "Launch day is finally here."', p4.POST)
        self.assertEqual(c["props"]["subtitle"], "@spacefan99 · Mar 3, 2021")

    def test_a_claim_and_its_verdict_on_its_word(self):
        c = one("You may have heard that we only use 10 percent of our brains. That's a myth. In reality, we use "
                "virtually every part of the brain.", p4.FACTCHECK)
        p = c["props"]
        self.assertEqual((p["text"], p["items"][0]["label"]), ("We only use 10 percent of our brains", "False"))
        self.assertEqual(p["subtitle"], "We use virtually every part of the brain")
        self.assertGreater(p["items"][0]["at"], 1.0)                                # the stamp waits for its word
        c = one("It's often said that cracking your knuckles causes arthritis. That claim is misleading.", p4.FACTCHECK)
        self.assertEqual(c["props"]["items"][0]["label"], "Misleading")
        c = one("Many people believe that octopuses have three hearts. It turns out that's true.", p4.FACTCHECK)
        self.assertEqual(c["props"]["items"][0]["label"], "True")
        c = one("In 1969, many people believed the moon landing was faked. That's a myth.", p4.FACTCHECK)
        self.assertEqual((c["props"]["text"], c["props"]["label"]), ("The moon landing was faked", "1969"))
        c = one("For decades, people believed that Napoleon was extremely short. That's not true. He was about average "
                "height for his time.", p4.FACTCHECK)
        self.assertEqual(c["props"]["subtitle"], "He was about average height for his time")
        self.assertIsNone(one("You may have heard about the new law.", p4.FACTCHECK))

    def test_a_top_three_on_the_podium_in_its_places(self):
        c = one("In the 2008 Olympic final, Usain Bolt took gold, Richard Thompson silver and Walter Dix bronze.",
                p4.PODIUM)
        self.assertEqual([it["label"] for it in c["props"]["items"]], ["Usain Bolt", "Richard Thompson", "Walter Dix"])
        self.assertEqual(c["props"]["text"], "2008 Olympic final")
        c = one("Walter Dix came third, Richard Thompson finished second and Usain Bolt finished first.", p4.PODIUM)
        self.assertEqual([it["label"] for it in c["props"]["items"]], ["Usain Bolt", "Richard Thompson", "Walter Dix"])

    def test_a_head_to_head_with_its_winner(self):
        c = one("In the 2022 World Cup final, Argentina beat France 4-2 on penalties.", p4.VERSUS)
        p = c["props"]
        self.assertEqual([(it["label"], it["value"]) for it in p["items"]], [("Argentina", 4), ("France", 2)])
        self.assertEqual((p["highlight"], p["label"], p["text"]), ("Argentina", "Final score", "2022 World Cup final"))
        c = one("Obama won 365 electoral votes to McCain's 173.", p4.VERSUS)
        self.assertEqual((c["props"]["label"], c["props"]["highlight"]), ("Electoral votes", "Obama"))
        c = one("At Cannae, 50,000 Carthaginians faced 86,000 Romans.", p4.VERSUS)
        self.assertNotIn("highlight", c["props"])                    # a battle's numbers name no winner
        self.assertEqual(c["props"]["text"], "Cannae")
        c = one("France lost 2-4 to Argentina.", p4.VERSUS)
        self.assertEqual([it["label"] for it in c["props"]["items"]], ["Argentina", "France"])
        self.assertIsNone(one("The heart beat 72 times a minute.", p4.VERSUS))


class OnePass(unittest.TestCase):
    def test_the_more_specific_look_takes_the_words(self):
        then_now = ("In 1970 a gallon of gas cost 36 cents, a new car $3,500 and the average home $23,000. Today gas is "
                    "$3.50, a car $48,000 and a home $420,000.")
        self.assertEqual([c["tid"] for c in found(then_now)], [p4.TABLE])
        self.assertEqual([c["tid"] for c in found("The three most visited cities in the world are Bangkok, Paris and "
                                                  "London.")], [p4.PODIUM])
        three = "Bitcoin went from $1,000 in January 2017 to nearly $20,000 by December, then crashed to $3,200."
        self.assertEqual([c["tid"] for c in found(three)], [p4.PRICE])
        self.assertEqual([c["tid"] for c in found("Phoenix just endured 31 straight days above 110 degrees.")], [p3.STREAK])

    def test_one_pace_for_both_packs_and_each_looks_cap(self):
        lines = [(0.0, "Phoenix just endured 31 straight days above 110 degrees."),
                 (10.0, "In 2012, Facebook paid $1 billion for Instagram.")]
        got = [c["tid"] for c in p4.find(dl.Narration(words_for(lines)), ok=lambda tid: True)[0]]
        self.assertEqual(len(got), 1, got)                                  # 10 s apart: one of the two
        pace = p4.Pace()
        for i in range(p4.MAX_PER_VIDEO[p4.PODIUM]):
            t = 400.0 * i
            self.assertTrue(pace.allows(p4.PODIUM, t))
            pace.note(p4.PODIUM, t)
        self.assertFalse(pace.allows(p4.PODIUM, 400.0 * 10))              # its cap for a video
        self.assertTrue(pace.allows(p3.RANKING, 400.0 * 10))
        pace.note(p3.RANKING, 4000.0)
        self.assertFalse(pace.allows(p4.VERSUS, 4010.0))                  # pack 3's look spaces pack 4's

    def test_the_same_person_is_carded_once(self):
        line = "Steve Jobs, the co-founder of Apple, was born in 1955 in San Francisco."
        lines = [(0.0, line), (200.0, line)]
        got = [c for c in p4.find(dl.Narration(words_for(lines)), ok=lambda tid: True)[0] if c["tid"] == p4.PROFILE]
        self.assertEqual(len(got), 1)


class Planned(unittest.TestCase):
    def test_on_their_words_and_their_figures_not_shown_twice(self):
        line = "In 2012, Facebook paid $1 billion for Instagram."
        doc = doc_for([(2.0, line)])
        dl.finish(doc)
        self.assertEqual([o["template"] for o in doc["overlays"]], [p4.MONEY])          # no KT_NUMBER for $1 billion
        o = doc["overlays"][0]
        words = doc["scenes"][0]["words"]
        self.assertLessEqual(abs(o["startFrame"] / FPS - (said_at(words, "$1") - dl.MAX_LEAD_S)), 0.1)
        self.assertGreaterEqual(o["durationInFrames"], dl.min_frames(o, FPS))
        self.assertTrue(o["dataLook"])

        line = "Messi scored 672 goals in 778 games. Ronaldo scored 701 goals in 1,000 games."
        doc = doc_for([(2.0, line)])
        dl.finish(doc)
        self.assertEqual([x["template"] for x in doc["overlays"]], [p4.TABLE])
        o = doc["overlays"][0]
        start = o["startFrame"] / FPS
        words = doc["scenes"][0]["words"]
        for it, token in zip(o["items"], ["672", "778", "701", "1,000"]):
            self.assertAlmostEqual(start + it["at"], said_at(words, token), delta=0.12)
        self.assertGreaterEqual(dl.min_seconds(o), max(it["at"] for it in o["items"]) + p4.HOLD[p4.TABLE])

    def test_a_time_its_sentence_opens_with_is_shown_on_the_card_never_a_date_look_in_its_place(self):
        cases = [("In 2012, Facebook paid $1 billion for Instagram.", p4.MONEY, "subtitle", "For Instagram, in 2012"),
                 ('In August 2018, Elon Musk tweeted: "Am considering taking Tesla private at $420. Funding secured."',
                  p4.POST, "subtitle", "Aug 2018"),
                 ("In 1969, many people believed the moon landing was faked. That's a myth.", p4.FACTCHECK, "label",
                  "1969")]
        for line, tid, field, shown in cases:
            doc = doc_for([(2.0, line)])
            dl.finish(doc)
            self.assertEqual([o["template"] for o in doc["overlays"]], [tid], line)
            self.assertEqual(doc["overlays"][0][field], shown, line)
        # a sentence no pack look takes keeps its year look
        doc = doc_for([(2.0, "In 1998, Google was founded by Larry Page and Sergey Brin.")])
        dl.finish(doc)
        self.assertEqual([o["template"] for o in doc["overlays"]], ["KT_YEAR"])

    def test_an_older_look_saying_the_same_gives_way_and_the_planners_own_are_planned_again(self):
        line = "The upside: lower fees and faster transfers. The downside: wild price swings and almost no regulation."
        old = {"type": "motion", "template": "LIB_LS_PROS_CONS", "variant": "ls-pros-cons", "startFrame": int(2.5 * FPS),
               "durationInFrames": 150, "text": "PROS"}
        doc = doc_for([(2.0, line)], [dict(old)])
        rep = dl.finish(doc)
        self.assertEqual([o["template"] for o in doc["overlays"]], [p4.PROSCONS])
        self.assertIn("LIB_LS_PROS_CONS", [r["template"] for r in rep["removed"]])
        dl.finish(doc)
        self.assertEqual([o["template"] for o in doc["overlays"]].count(p4.PROSCONS), 1)
        doc = doc_for([(2.0, line)], [dict(old)], seconds=60.0)
        dl.finish(doc)
        mine = {"type": "motion", "template": p4.CASE, "variant": "kt-case", "text": "My case", "startFrame": 900,
                "durationInFrames": 180, "items": [{"label": "Status", "text": "Open"}]}
        doc["overlays"].append(mine)
        dl.finish(doc)
        self.assertIn(p4.CASE, [o["template"] for o in doc["overlays"]])        # the editor's own stays

    def test_a_brand_kit_without_them_keeps_the_figures_as_kt_looks(self):
        doc = doc_for([(2.0, "In 2012, Facebook paid $1 billion for Instagram.")])
        with templates.only({"KT_NUMBER", "KT_CHIP", "KT_PERCENT"}):
            dl.finish(doc)
        ids = [o["template"] for o in doc["overlays"]]
        self.assertNotIn(p4.MONEY, ids)
        self.assertTrue(set(ids) & {"KT_NUMBER", "KT_CHIP"}, ids)

    def test_a_persons_card_gets_their_portrait_only_from_a_scene_of_them(self):
        line = "Steve Jobs, the co-founder of Apple, was born in 1955 in San Francisco."
        scenes = [{"id": "s0", "startFrame": 0, "durationInFrames": 600, "text": "",
                   "media": {"type": "image", "url": "https://x/jobs.jpg",
                             "focus": {"faceBoxes": [[0.4, 0.2, 0.2, 0.3]], "kind": "face"}},
                   "semanticMetadata": {"subject": "Steve Jobs at Macworld"}}]
        doc = doc_for([(2.0, line)], scenes=scenes)
        rep = dl.finish(doc)
        o = [x for x in doc["overlays"] if x["template"] == p4.PROFILE][0]
        self.assertEqual(o["media"][0]["url"], "https://x/jobs.jpg")
        self.assertEqual(o["media"][0]["focus"]["faceBoxes"], [[0.4, 0.2, 0.2, 0.3]])
        self.assertEqual(rep["portraits"], 1)
        # a scene of someone (or something) else: the initials, never a stranger's face
        scenes = [{"id": "s0", "startFrame": 0, "durationInFrames": 600, "text": "",
                   "media": {"type": "video", "url": "https://x/a.mp4", "thumbnail": "https://x/a.jpg"},
                   "semanticMetadata": {"subject": "Apple headquarters in Cupertino"}}]
        doc = doc_for([(2.0, line)], scenes=scenes)
        dl.finish(doc)
        o = [x for x in doc["overlays"] if x["template"] == p4.PROFILE][0]
        self.assertFalse(o.get("media"))
        # the junior is not the senior
        ov = {"template": p4.PROFILE, "text": "Barack Obama", "startFrame": 0}
        sc = [{"id": "a", "startFrame": 0, "durationInFrames": 300, "media": {"type": "image", "url": "https://x/sr.jpg"},
               "semanticMetadata": {"subject": "Barack Obama Sr."}}]
        self.assertIsNone(p4.portrait_for(ov, sc, FPS))

    def test_the_relook_plans_them_and_counts_them(self):
        doc = doc_for([(2.0, "In 2012, Facebook paid $1 billion for Instagram.")])
        diff = relook.replan(doc, resolve=lambda *a, **k: [], check_images=False)
        self.assertEqual(relook._summary(diff)["addedPack4"], 1)

    def test_a_lost_portrait_leaves_the_card_with_its_initials(self):
        ov = {"type": "motion", "template": p4.PROFILE, "variant": "kt-profile", "text": "Steve Jobs", "startFrame": 0,
              "durationInFrames": 150, "media": [{"type": "image", "url": "https://x/gone.jpg"}]}
        overlays = [ov]
        rep = overlayimages.fix(overlays, project_id="p", scenes=[
            {"id": "s", "startFrame": 0, "durationInFrames": 300, "media": {"type": "image", "url": "https://x/other.jpg"}}],
            fetch=lambda url: (_ for _ in ()).throw(RuntimeError("404")), put=None)
        self.assertEqual(len(overlays), 1)
        self.assertEqual(overlays[0]["template"], p4.PROFILE)
        self.assertEqual(overlays[0]["media"], [])                   # never the scene's picture of something else
        self.assertEqual(rep["textOnly"], 1)


class Placed(unittest.TestCase):
    def test_the_cards_take_the_calm_side_the_glass_ones_never_the_panel(self):
        ovs = [{"template": t, "startFrame": 0, "durationInFrames": 90} for t in PACK]
        scenes = [{"startFrame": 0, "durationInFrames": 300, "media": {"type": "image", "url": "x", "focus": {"busy": 0.9}}}]
        lookplace.place(ovs, scenes, fetch=lambda url: None)
        panels = {o["template"] for o in ovs if o.get("backing") == "panel"}
        self.assertEqual(panels, {"KT_MONEY"})                         # a figure on a soft shade, like kt-number
        self.assertFalse(any(o.get("zone") or o.get("backing") for o in ovs if o["template"] in lookplace.KT_PACK4_SELF))
        self.assertEqual(lookplace._home("KT_PRICE", False), "right-panel")
        self.assertEqual(lookplace._home("KT_STEPS", False), "left-panel")
        self.assertEqual(lookplace._home("KT_PROFILE", False), "lower-left")


if __name__ == "__main__":
    unittest.main()
