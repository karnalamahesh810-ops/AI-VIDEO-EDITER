"""
The AI presenter in a set that fits the video (src/presenter/sets.py) and how it moves (src/presenter/motion.py),
offline: fake OpenRouter, fake R2. Run with the suite: SKIP_DOTENV=1 python -m unittest discover -s tests -t .
"""
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from PIL import Image

import handler
from src.presenter import generate, hybrid, kits, media_io, motion, pipeline, providers, sets
from src.presenter.budget import Budget, BudgetExceeded
from src.presenter.checks import Checker
from src.presenter.providers import ImageResult, ProviderError
from tests.test_presenter import FakeProvider, FakeStore, kit_in, make_wav, segments_for, SENTENCES
from tests.test_presenter_hybrid import plan_inputs

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = json.load(open(os.path.join(HERE, "fixtures", "set_choice_samples.json"), encoding="utf-8"))["samples"]
BLUE = (20, 60, 200)


def blue_png(w=2048, h=1152):
    buf = io.BytesIO()
    im = Image.new("RGB", (w, h), BLUE)
    for x in range(0, w, 97):
        im.putpixel((x, 7), (200, 200, 30))
    im.save(buf, "PNG")
    return buf.getvalue()


def mean_rgb(path):
    import numpy as np
    with Image.open(path) as im:
        small = np.asarray(im.convert("RGB").resize((16, 9)), dtype=float)
    return tuple(small.reshape(-1, 3).mean(axis=0))


class SetProvider(FakeProvider):
    """The fake OpenRouter, drawing set pictures in blue (so a take's framing shows where it came from)."""

    def __init__(self, *a, image_fail=False, model_answer=None, **kw):
        super().__init__(*a, **kw)
        self.image_fail = image_fail
        self.model_answer = model_answer

    def image(self, req):
        self.images.append(req)
        if self.image_fail:
            raise ProviderError("image model down", status=503)
        return ImageResult(data=blue_png(), ext=".png", cost=0.139, model=req.model, seconds=0.1)

    def chat(self, model, messages, **kw):
        text = messages[-1]["content"]
        text = text if isinstance(text, str) else json.dumps(text)
        if "where a YouTube presenter is filmed" in text:
            self.chats.append(messages)
            from src.presenter.providers import ChatResult
            body = self.model_answer if self.model_answer is not None else {"set": "studio", "confidence": 0.3}
            return ChatResult(text=json.dumps(body) if isinstance(body, dict) else str(body), cost=0.0004,
                              model=model, seconds=0.1)
        return super().chat(model, messages, **kw)


class FakeSetStore(sets.SetStore):
    """R2 in a folder: JSON by key, files copied (their 'links' are the local copies)."""

    def __init__(self, folder, on=True):
        self.folder, self.on = folder, on
        self.json, self.files = {}, {}
        os.makedirs(folder, exist_ok=True)

    def enabled(self):
        return self.on

    def get_json(self, key):
        v = self.json.get(key)
        return json.loads(json.dumps(v)) if v is not None else None

    def put_json(self, key, data):
        self.json[key] = json.loads(json.dumps(data))
        return f"https://r2.example.test/{key}"

    def put_file(self, local, key):
        dest = os.path.join(self.folder, key.replace("/", "__"))
        shutil.copyfile(local, dest)
        self.files[key] = dest
        return dest


def hollis_like(folder, home_set="kitchen"):
    kit = kit_in(folder, framings=("medium", "closeup"))
    kit = dict(kit, name="Hollis Reed", wardrobe="faded light-blue pearl-snap western shirt, brown canvas vest",
               room="A ranch cookhouse kitchen with a cast-iron wood stove", home_set=home_set)
    return kits.normalize(kit)


# ------------------------------------------------------------------ the catalogue
class Catalogue(unittest.TestCase):
    def test_every_set_is_complete_and_the_ids_are_the_apps(self):
        self.assertEqual(sets.ids(), ["studio", "office", "tech_desk", "podcast", "newsroom", "trading_desk",
                                      "weather_studio", "classroom", "library", "dark_room", "science_lab", "kitchen",
                                      "workshop", "living_room", "gym", "car", "city_street", "nature", "landmark",
                                      "storm"])
        groups = {g for g, _label in sets.GROUPS}
        for s in sets.SETS:
            for f in ("label", "hint", "niches", "where", "room", "stance", "light"):
                self.assertTrue(getattr(s, f).strip(), (s.id, f))
            self.assertIn(s.group, groups)
            self.assertNotIn(s.wardrobe.partition(": ")[0], ("over_", "x"))
        self.assertEqual(sets.DEFAULT_SET, "studio")
        # Weather is two sets of twenty: everything else is any other niche.
        weathery = [s.id for s in sets.SETS if "weather" in s.room or "storm" in s.room]
        self.assertEqual(sorted(weathery), ["storm", "weather_studio"])

    def test_screens_never_show_text_and_no_brand_is_named(self):
        for s in sets.SETS:
            if "screen" in s.room or "monitor" in s.room:
                self.assertTrue(s.screens, s.id)
                self.assertRegex(s.screens.lower(), r"no (letters|words|text)", s.id)
            for brand in ("cnn", "fox", "bbc", "apple", "nike", "bloomberg", "nasdaq", "weather channel"):
                self.assertNotRegex(f" {s.room.lower()} {s.screens.lower()} ", rf"{brand}", (s.id, brand))

    def test_presenter_info_carries_the_catalogue(self):
        info = pipeline.info()
        self.assertEqual([s["id"] for s in info["sets"]["catalogue"]], sets.ids())
        self.assertEqual(info["sets"]["default"], "studio")
        self.assertAlmostEqual(info["sets"]["pairUsd"], 0.28)
        self.assertNotIn("room", info["sets"]["catalogue"][0])           # no prompts for the app


# ------------------------------------------------------------------ auto
class Auto(unittest.TestCase):
    def test_sample_scripts_across_niches_pick_sensible_sets(self):
        self.assertGreaterEqual(len({s["niche"] for s in SAMPLES}), 12)
        for s in SAMPLES:
            pick, sc = sets.rule_pick(s["title"], s["script"])
            self.assertEqual(pick or sets.DEFAULT_SET, s["expect"], (s["niche"], sc))

    def test_the_title_counts_three_times_and_one_word_said_often_counts_three_times(self):
        self.assertEqual(sets.scores("The Last Emperor", ""), {"library": 3.0})
        self.assertEqual(sets.scores("The Roman Empire", ""), {"library": 3.0})   # the longer phrase, once
        self.assertEqual(sets.scores("", "empire " * 30), {"library": 3.0})

    def test_hyphens_curly_quotes_and_old_years(self):
        self.assertIn("kitchen", sets.scores("", "a cast-iron skillet"))
        self.assertEqual(sets.scores("", "In 1776 and in 2008"), {"library": 0.5})
        self.assertEqual(sets.scores("", "let’s talk"), sets.scores("", "let's talk"))

    def test_a_close_call_is_unsure(self):
        pick, sc = sets.rule_pick("", "the stock market and the weather forecast")
        self.assertIsNone(pick, sc)

    def test_unsure_asks_the_model_once_then_trusts_a_confident_answer(self):
        p = SetProvider(model_answer={"set": "office", "confidence": 0.8})
        c = sets.choose({"id": "auto"}, None, title="Ten Things I Wish I Knew Sooner", text="Here are ten things.",
                        provider=p)
        self.assertEqual((c.id, c.how), ("office", "model"))
        self.assertEqual(len(p.chats), 1)
        self.assertIn("tech_desk", p.chats[0][-1]["content"])           # the catalogue is in the question

    def test_an_unsure_or_failed_model_gives_the_neutral_studio(self):
        for answer in ({"set": "office", "confidence": 0.2}, {"set": "moon base", "confidence": 0.99}, "not json"):
            c = sets.choose({"id": "auto"}, None, title="Ten things", text="", provider=SetProvider(model_answer=answer))
            self.assertEqual((c.id, c.how), ("studio", "default"), answer)

        class Down(SetProvider):
            def chat(self, model, messages, **kw):
                raise ProviderError("down", status=503)
        c = sets.choose({"id": "auto"}, None, title="Ten things", provider=Down())
        self.assertEqual((c.id, c.how), ("studio", "default"))
        self.assertIn("error", c.report()["model"])

    def test_sure_rules_never_call_the_model(self):
        p = SetProvider()
        s = next(x for x in SAMPLES if x["niche"] == "finance")
        c = sets.choose({"id": "auto"}, None, title=s["title"], text=s["script"], provider=p)
        self.assertEqual((c.id, c.how), ("trading_desk", "rules"))
        self.assertEqual(p.chats, [])

    def test_the_model_call_goes_through_the_budget(self):
        b = Budget(0.001)                                              # under one pick's reservation
        p = SetProvider(model_answer={"set": "office", "confidence": 0.9})
        c = sets.choose({"id": "auto"}, None, title="Ten things", provider=p, budget=b)
        self.assertEqual(c.id, "studio")
        self.assertEqual(p.chats, [])

    def test_a_pick_of_the_kits_own_set_is_the_kit_itself(self):
        with tempfile.TemporaryDirectory() as d:
            kit = hollis_like(d)
            food = next(x for x in SAMPLES if x["niche"] == "food")
            c = sets.choose({"id": "auto"}, kit, title=food["title"], text=food["script"])
            self.assertEqual((c.id, c.how, c.home_match), ("home", "home", "kitchen"))
            self.assertEqual(sets.choose({"id": "kitchen"}, kit).id, "home")
            self.assertEqual(sets.choose({"id": "library"}, kit).id, "library")

    def test_a_kit_without_home_set_is_read_from_its_room(self):
        self.assertEqual(sets.home_of({"room": "His timber-framed workshop: a pegboard of hand tools, a workbench"}),
                         "workshop")
        self.assertEqual(sets.home_of({"room": "His small corner butcher shop: sausages on a rail, a meat case"}),
                         "kitchen")
        self.assertEqual(sets.home_of({"room": "A plain room"}), "")
        self.assertEqual(sets.home_of({"home_set": "newsroom", "room": "a kitchen"}), "newsroom")


# ------------------------------------------------------------------ the job's request
class Request(unittest.TestCase):
    def test_what_a_job_may_send(self):
        self.assertIsNone(sets.request_of(None))
        self.assertIsNone(sets.request_of(""))
        self.assertIsNone(sets.request_of(False))
        self.assertEqual(sets.request_of("library")["id"], "library")
        self.assertEqual(sets.request_of({"id": "HOME"}), {"id": "home"})
        self.assertEqual(sets.request_of({"id": "moon base"})["id"], "auto")
        self.assertEqual(sets.request_of({"id": "auto"})["id"], "auto")
        got = sets.request_of({"id": "custom", "description": "  a lighthouse\non a rocky coast <b> "})
        self.assertEqual(got["id"], "custom")
        self.assertEqual(got["description"], "a lighthouse on a rocky coast b")
        self.assertEqual(sets.request_of({"description": "a quiet bakery at dawn"})["id"], "custom")
        self.assertEqual(sets.request_of({"id": "custom", "description": "x"})["id"], "auto")
        imgs = {"master": "https://r2.example.test/m.png", "closeup": "https://r2.example.test/c.png"}
        self.assertEqual(sets.request_of({"id": "office", "images": imgs})["images"], imgs)
        self.assertEqual(sets.request_of({"id": "office", "images": {"master": "file:///x"}})["images"], {})
        self.assertEqual(sets.request_of({"id": "auto", "images": imgs})["images"], {})   # whose pair would it be?

    def test_a_described_set_is_the_same_set_every_time(self):
        a = sets.custom_spec("A lighthouse on a rocky coast at sunset")
        b = sets.custom_spec("a  lighthouse on a ROCKY coast at sunset.")
        self.assertEqual(a.id, b.id)
        self.assertRegex(a.id, r"^custom-[0-9a-f]{10}$")
        self.assertEqual(a.where, "in A lighthouse on a rocky coast at sunset")
        self.assertEqual(sets.custom_spec("on a beach at dawn").where, "on a beach at dawn")
        self.assertIn("no readable text", a.room)
        c = sets.choose({"id": "custom", "description": "a lighthouse on a rocky coast"}, None)
        self.assertEqual((c.id[:7], c.how), ("custom-", "asked"))
        self.assertEqual(c.report()["description"], "a lighthouse on a rocky coast")


# ------------------------------------------------------------------ the pictures' prompts
class Prompts(unittest.TestCase):
    def setUp(self):
        self.kit = {"wardrobe": "faded light-blue pearl-snap western shirt, brown canvas vest."}

    def test_the_main_camera_keeps_the_person_and_the_clothes(self):
        lib = sets.spec("library")
        p = sets.master_prompt(self.kit, lib)
        self.assertIn("exactly this same person", p)
        self.assertIn("pearl-snap western shirt, brown canvas vest)", p)
        self.assertIn(lib.room, p)
        self.assertIn("No text anywhere", p)
        self.assertIn("waist up", p)
        self.assertNotIn("Important:", p)
        self.assertIn("Important: it must be unmistakably the same person", sets.master_prompt(self.kit, lib, retry=True))

    def test_clothes_adapt_lightly(self):
        self.assertIn("with a plain dark rain jacket, hood down over them", sets.master_prompt(self.kit, sets.spec("storm")))
        self.assertIn("a plain white lab coat", sets.master_prompt(self.kit, sets.spec("science_lab")))
        gym = sets.master_prompt(self.kit, sets.spec("gym"))
        self.assertIn("training jacket", gym)
        self.assertNotIn("pearl-snap", gym)
        self.assertEqual(sets.wardrobe_for(self.kit, sets.spec("nature")),
                         "faded light-blue pearl-snap western shirt, brown canvas vest, with a plain outdoor jacket over it")

    def test_the_close_up(self):
        p = sets.closeup_prompt(self.kit, sets.spec("trading_desk"))
        self.assertIn("image 2 is the same person", p)
        self.assertIn("mid-chest up", p)
        self.assertIn("Hands out of frame", p)
        self.assertIn("no letters, numbers, tickers or logos", p)


# ------------------------------------------------------------------ the pair: cache and making
class Pairs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        self.kit = hollis_like(os.path.join(self.d, "kit"))
        self.store = FakeSetStore(os.path.join(self.d, "r2"))
        self.work = os.path.join(self.d, "work")

    def tearDown(self):
        self.tmp.cleanup()

    def ensure(self, provider, set_id="library", budget=5.0, store=None, kit=None, **kw):
        b = Budget(budget)
        choice = sets.choose({"id": set_id}, kit or self.kit)
        return sets.ensure(kit or self.kit, choice, provider=provider, budget=b, work=self.work,
                           checker=Checker(provider, b, self.work), store=store or self.store,
                           log=lambda m: None, **kw), b

    def test_made_once_then_from_the_cache(self):
        p = SetProvider()
        pair, b = self.ensure(p)
        self.assertEqual(len(p.images), 2)
        master_req, close_req = p.images
        self.assertEqual(master_req.model, "google/gemini-3-pro-image")
        self.assertEqual((master_req.size, master_req.aspect_ratio), ("2K", "16:9"))
        self.assertEqual(len(master_req.references), 1)               # the kit's master
        self.assertEqual(len(close_req.references), 2)                # the new set master + the kit's master
        self.assertEqual(pair.cached, "")
        self.assertAlmostEqual(pair.usd, 0.278, places=3)
        folder = pair.folder
        self.assertTrue(folder.endswith("/sets/library"))
        manifest = self.store.json[f"{folder}/set.json"]
        self.assertEqual(manifest["status"], "ready")
        self.assertEqual(manifest["made_from"], sets._identity_master(self.kit))
        index = self.store.json[f"{folder.rsplit('/', 1)[0]}/index.json"]
        self.assertEqual(set(index["sets"]), {"library"})
        self.assertTrue(index["sets"]["library"]["master_1280"])
        self.assertTrue(all(v.get("ok") for v in pair.checks.values()))
        # The next job (any user, any video): no picture paid again.
        p2 = SetProvider()
        again, _ = self.ensure(p2)
        self.assertEqual((again.cached, len(p2.images)), ("r2", 0))
        self.assertEqual(again.master_url, pair.master_url)

    def test_a_newer_master_makes_the_pair_again(self):
        self.ensure(SetProvider())
        kit2 = kits.normalize(dict(self.kit, master=kits.framing(self.kit, "medium")["url"]))
        p = SetProvider()
        pair, _ = self.ensure(p, kit=kit2)
        self.assertEqual((pair.cached, len(p.images)), ("", 2))

    def test_another_job_making_it_is_waited_for(self):
        folder = f"{sets.folder_for(self.kit)}/library"
        self.store.json[f"{folder}/set.json"] = {"status": "making", "at": __import__("time").time()}
        ready = {"status": "ready", "images": {"master": "/x/m.png", "closeup": "/x/c.png"}}

        def sleep(_s):
            self.store.json[f"{folder}/set.json"] = ready             # the other job finished meanwhile
        p = SetProvider()
        pair, _ = self.ensure(p, sleep=sleep)
        self.assertEqual((pair.cached, pair.master_url, len(p.images)), ("r2", "/x/m.png", 0))

    def test_a_stale_claim_is_made_again(self):
        folder = f"{sets.folder_for(self.kit)}/library"
        self.store.json[f"{folder}/set.json"] = {"status": "making", "at": 1.0}
        p = SetProvider()
        pair, _ = self.ensure(p)
        self.assertEqual((pair.cached, len(p.images)), ("", 2))

    def test_a_picture_that_fails_its_check_is_redone_once_then_the_set_fails(self):
        verdicts = iter([{"same_person": 0.3, "natural": 0.9, "issues": ["different_person"]},
                         {"same_person": 0.9, "natural": 0.9, "issues": []},
                         {"same_person": 0.9, "natural": 0.9, "issues": []}])
        p = SetProvider(verdict=lambda text: next(verdicts))
        pair, _ = self.ensure(p)
        self.assertEqual(len(p.images), 3)                              # master twice, close-up once
        self.assertIn("Important: it must be unmistakably the same person", p.images[1].prompt)
        self.assertFalse(pair.checks["master0"]["ok"])
        bad = SetProvider(verdict=lambda text: {"same_person": 0.2, "natural": 0.9, "issues": ["different_person"]})
        with self.assertRaises(sets.SetError):
            self.ensure(bad, set_id="office")
        folder = f"{sets.folder_for(self.kit)}/office"
        self.assertEqual(self.store.json[f"{folder}/set.json"]["status"], "failed")

    def test_a_close_up_that_cannot_be_had_leaves_the_main_camera(self):
        class NoCloseUp(SetProvider):
            def image(self, req):
                if "image 2 is the same person" in req.prompt:
                    self.images.append(req)
                    raise ProviderError("image model down", status=503)
                return super().image(req)
        p = NoCloseUp()
        pair, _ = self.ensure(p)
        self.assertEqual(pair.closeup_url, pair.master_url)
        self.assertEqual(pair.checks["closeupFallback"], "the main camera")
        self.assertIn("image model down", pair.checks["closeupError"])
        manifest = self.store.json[f"{pair.folder}/set.json"]
        self.assertEqual(manifest["images"]["closeup"], manifest["images"]["master"])
        self.assertEqual(len(self.store.files), 2)                      # one picture and its preview, uploaded once

    def test_the_budget_stops_it(self):
        with self.assertRaises(BudgetExceeded):
            self.ensure(SetProvider(), budget=0.1)

    def test_a_pair_the_job_brings_costs_nothing(self):
        p = SetProvider()
        given = {"master": "https://r2.example.test/m.png", "closeup": "https://r2.example.test/c.png"}
        pair, _ = self.ensure(p, given=given)
        self.assertEqual((pair.cached, pair.master_url, len(p.images)), ("job", given["master"], 0))

    def test_without_r2_the_pair_is_made_for_the_job_only(self):
        p = SetProvider()
        pair, _ = self.ensure(p, store=FakeSetStore(os.path.join(self.d, "off"), on=False))
        self.assertEqual(len(p.images), 2)
        self.assertTrue(os.path.isfile(pair.master_url) and os.path.isfile(pair.closeup_url))

    def test_where_a_kits_sets_are_kept(self):
        with mock.patch.multiple(sets.config, R2_PUBLIC_BASE="https://pub.example.r2.dev", R2_BUCKET="thumbgenius-videos"), \
                mock.patch.object(sets.config, "R2_LIBRARY_PUBLIC_BASE", "", create=True):
            lib = {"id": "hollis", "master": "https://pub.example.r2.dev/presenters/hollis/hollis_master.png"}
            self.assertEqual(sets.folder_for(lib), "presenters/hollis/sets")
            own = {"id": "user-p1", "master": "https://pub.example.r2.dev/presenters/user/u1/p1/master-abc123.png"}
            self.assertEqual(sets.folder_for(own), "presenters/user/u1/p1/sets")
            # A set made from a user's presenter stays in that presenter's folder (its identity master).
            self.assertEqual(sets.folder_for(dict(own, master="https://x.test/set.png",
                                                  identity_master=own["master"])), "presenters/user/u1/p1/sets")
            other = sets.folder_for({"id": "Walt!", "master": "https://elsewhere.test/walt.png"})
            self.assertRegex(other, r"^presenters/_other/walt-[0-9a-f]{10}/sets$")


class Apply(unittest.TestCase):
    def test_the_kit_in_the_set(self):
        with tempfile.TemporaryDirectory() as d:
            kit = hollis_like(d)
            choice = sets.choose({"id": "nature"}, kit)
            pair = sets.Pair("nature", "Nature / outdoors", "https://r2.test/m.png", "https://r2.test/c.png",
                             cached="r2")
            k = sets.apply(kit, choice, pair)
            self.assertEqual([f["id"] for f in k["framings"]], ["master", "closeup"])
            self.assertEqual(k["master"], pair.master_url)
            self.assertEqual(k["identity_master"], kit["master"])
            self.assertEqual(k["sets"], [])                             # the home set's empty plates show another room
            self.assertIn("plain outdoor jacket", k["wardrobe"])
            self.assertEqual(k["world"]["place"], sets.spec("nature").room)
            self.assertEqual(k["filming_set"]["id"], "nature")
            self.assertEqual(k["set_where"], "outdoors on a forest trail")
            self.assertIn("medium", [f["id"] for f in kit["framings"]])  # the home kit is untouched
            self.assertNotIn("filming_set", kit)
            self.assertEqual(kits.public_summary(k)["filmingSet"]["id"], "nature")


class Job(unittest.TestCase):
    def test_a_set_that_cannot_be_had_keeps_the_kits_own_set(self):
        with tempfile.TemporaryDirectory() as d:
            kit = hollis_like(os.path.join(d, "kit"))
            b = Budget(5.0)
            p = SetProvider(image_fail=True)
            sj = sets.SetJob(kit, "office", provider=p, budget=b, work=d, checker=Checker(p, b, d),
                             store=FakeSetStore(os.path.join(d, "r2")), log=lambda m: None)
            sj.choose()
            self.assertTrue(sj.needs_pair())
            self.assertAlmostEqual(sj.extra_budget(), sets.PAIR_PROJECTED_USD)
            self.assertIs(sj.run(), kit)
            self.assertIn("Modern office", sj.warning())
            rep = sj.report()
            self.assertEqual((rep["id"], rep["used"]), ("office", "home"))
            self.assertIn("image model down", rep["error"])

    def test_no_request_is_the_old_behaviour(self):
        sj = sets.SetJob({"id": "k"}, None)
        self.assertFalse(sj.requested)
        self.assertEqual(sj.choose().id, "home")
        self.assertFalse(sj.needs_pair())
        self.assertEqual(sj.extra_budget(), 0.0)

    def test_the_action_outside_a_video(self):
        with tempfile.TemporaryDirectory() as d:
            kit = hollis_like(os.path.join(d, "kit"))
            raw = {k: v for k, v in kit.items()}
            history = next(x for x in SAMPLES if x["niche"] == "history")
            store = FakeSetStore(os.path.join(d, "r2"))
            with mock.patch.object(providers, "get", return_value=SetProvider()), \
                    mock.patch.object(sets, "SetStore", return_value=store):
                out = handler.handler({"id": "t1", "input": {"action": "presenter_set", "presenter_kit": raw,
                                                             "set": "auto", "title": history["title"],
                                                             "script": history["script"]}})
                self.assertTrue(out["ok"], out)
                self.assertEqual((out["set"]["id"], out["set"]["how"], out["cached"]), ("library", "rules", False))
                self.assertEqual(out["usd"], 0.0)                       # nothing made without make: true
                made = handler.handler({"id": "t2", "input": {"action": "presenter_set", "presenter_kit": raw,
                                                              "set": "library", "make": True}})
                self.assertTrue(made["ok"], made)
                self.assertAlmostEqual(made["usd"], 0.279, delta=0.002)   # two pictures and their two checks
                self.assertTrue(made["pair"]["master"])
                again = handler.handler({"id": "t3", "input": {"action": "presenter_set", "presenter_kit": raw,
                                                               "set": "library"}})
                self.assertTrue(again["cached"])


# ------------------------------------------------------------------ in a hybrid video
class Hybrid(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = self.tmp.name
        self.segs, self.shots, self.assets, inp, self.total = plan_inputs()
        self.kit = hollis_like(os.path.join(self.work, "kitsrc"))
        self.wav = make_wav(os.path.join(self.work, "narration.wav"), self.total + 1.0)
        self.inp = dict(inp, video_style="documentary", project_id="",
                        presenter={"presenter_kit": self.kit, "share": "medium", "split_screen": True,
                                   "budget_usd": 5.0, "set": "library"})
        self.store = FakeSetStore(os.path.join(self.work, "r2"))

    def tearDown(self):
        self.tmp.cleanup()

    def start(self, provider, inp=None):
        hy = hybrid.start(inp or self.inp, self.segs, self.shots, narration_path=self.wav, duration=self.total,
                          work=self.work, provider=provider, store=FakeStore(),
                          cache_dir=os.path.join(self.work, "cache"), set_store=self.store)
        hy.wait()
        return hy

    def test_the_presenter_is_filmed_in_the_set_before_any_take(self):
        p = SetProvider()
        hy = self.start(p)
        self.assertEqual(len(p.images), 2)                              # the pair, and no other picture
        self.assertEqual(hy.kit["filming_set"]["id"], "library")
        self.assertIs(hy.gen.kit, hy.kit)
        self.assertTrue(hy.appearances and all(ap.framing in ("master", "closeup") for ap in hy.appearances))
        self.assertTrue(len(p.videos) >= len(hy.appearances))
        for fid, (local, _link) in hy.gen._framing_cache.items():
            r, g, b = mean_rgb(local)
            self.assertGreater(b, r + 80, fid)                          # the set's (blue) picture, not the home kit's
        doc = {"scenes": [], "durationInFrames": 1, "fps": 30}
        rep = hy.finish(doc)
        self.assertEqual((rep["set"]["id"], rep["set"]["used"]), ("library", "library"))
        self.assertGreater(rep["costs"]["setUsd"], 0.2)
        self.assertEqual(rep["kit"]["filmingSet"]["id"], "library")
        self.assertGreater(hy.budget.cap, 5.0)                          # the pair had room of its own

    def test_takes_carry_their_lines_words_and_the_tuned_motion(self):
        p = SetProvider()
        hy = self.start(p)
        hook = next(ap for ap in hy.appearances if ap.role == "hook")
        req = next(r for r in p.videos if r.audio_url and hook.id in r.audio_url)
        heygen = req.options["heygen"]
        self.assertIn("quick, natural blinks", heygen["motion_prompt"])
        self.assertIn("greeting the viewer", heygen["motion_prompt"])  # the hook's tone
        self.assertIn(heygen["expressiveness"], ("low", "medium"))
        self.assertIn("in a wood-panelled study", req.prompt)

    def test_a_cached_pair_adds_no_cost_and_no_room(self):
        self.start(SetProvider())
        p = SetProvider()
        hy = self.start(p, inp=dict(self.inp, presenter=dict(self.inp["presenter"], budget_usd=5.0)))
        self.assertEqual(len(p.images), 0)
        self.assertEqual(hy.budget.cap, 5.0)
        self.assertEqual(hy.finish({"scenes": []})["set"]["pair"]["cached"], "r2")

    def test_a_failed_set_keeps_the_home_set_and_still_makes_the_takes(self):
        p = SetProvider(image_fail=True)
        hy = self.start(p)
        self.assertNotIn("filming_set", hy.kit)
        self.assertTrue(any(m.parts for m in hy.made.values()))
        self.assertTrue(any("could not be put in" in w for w in hy.warnings))
        rep = hy.finish({"scenes": []})
        self.assertEqual(rep["set"]["used"], "home")

    def test_auto_on_a_food_story_is_the_presenters_own_kitchen(self):
        p = SetProvider()
        inp = dict(self.inp, title="The Easiest Sourdough Bread Recipe",
                   presenter=dict(self.inp["presenter"], set="auto"))
        hy = self.start(p, inp=inp)
        self.assertEqual(len(p.images), 0)
        self.assertEqual(hy.set_job.choice.id, "home")
        self.assertNotIn("filming_set", hy.kit)


# ------------------------------------------------------------------ in the AI presenter style
class Style(unittest.TestCase):
    def test_plan_with_a_set(self):
        with tempfile.TemporaryDirectory() as d:
            kit = hollis_like(os.path.join(d, "kitsrc"))
            wav = make_wav(os.path.join(d, "voice.wav"), 76.0)
            segs, _total = segments_for()
            words = [{"text": w.text, "start": w.start, "end": w.end} for s in segs for w in s.words]
            work = os.path.join(d, "work")
            os.makedirs(work)
            store = FakeSetStore(os.path.join(d, "r2"))
            p = SetProvider()
            with mock.patch.object(providers, "get", return_value=p), \
                    mock.patch.object(pipeline, "Store", lambda *a, **k: FakeStore()), \
                    mock.patch.object(sets, "SetStore", return_value=store), \
                    mock.patch.dict(os.environ, {"PRESENTER_CACHE_DIR": os.path.join(d, "cache")}):
                doc = pipeline.plan({"video_style": "ai_presenter", "presenter_kit": dict(kit), "audio_path": wav,
                                     "words": words, "title": "Potatoes", "script": " ".join(SENTENCES),
                                     "presenter_budget_usd": 20, "presenter_set": "science_lab"}, work,
                                    mock.MagicMock())
            meta = doc["meta"]["presenter"]
            self.assertEqual((meta["set"]["id"], meta["set"]["used"]), ("science_lab", "science_lab"))
            self.assertEqual(meta["kit"]["framings"], ["master", "closeup"])
            self.assertGreater(meta["costs"]["setUsd"], 0.2)
            pres = [s for s in doc["scenes"] if s["media"]["source"] == "ai-presenter"]
            self.assertTrue(pres)
            set_prompts = [r for r in p.images if "lab coat" in r.prompt]
            self.assertEqual(len(set_prompts), 2)


# ------------------------------------------------------------------ how the presenter moves
class Motion(unittest.TestCase):
    def test_tones(self):
        self.assertEqual(motion.tone_of("Have you ever wondered why?")["tone"], "question")
        self.assertEqual(motion.tone_of("Three people died in the flood.")["tone"], "serious")
        self.assertEqual(motion.tone_of("This is the single most honest thing here.")["tone"], "emphasis")
        self.assertEqual(motion.tone_of("I remember when I was a boy on the farm.")["tone"], "story")
        self.assertEqual(motion.tone_of("Number three: keep it dry.")["tone"], "list")
        self.assertEqual(motion.tone_of("The cellar stays cool.")["tone"], "plain")
        self.assertEqual(motion.tone_of("x", "close")["role"], "close")

    def test_the_main_camera_and_the_close_up(self):
        kit = {"name": "Hollis Reed", "persona": "Hollis Reed, a ranch cook in his cookhouse"}
        medium = motion.for_shot(kit, "The cellar stays cool.", framing={"id": "master", "shot": "medium shot"})
        self.assertIn("small, calm gesture at chest height", medium["motion_prompt"])
        self.assertIn("never come near the face", medium["motion_prompt"])
        self.assertIn("quick, natural blinks", medium["motion_prompt"])
        self.assertIn("never held shut, no squinting", medium["motion_prompt"])
        self.assertEqual(medium["expressiveness"], "low")              # HeyGen's own default (the 2026-10-08 proof)
        with mock.patch.object(motion, "DEFAULT_EXPRESSIVENESS", "medium"):
            raised = motion.for_shot(kit, "The cellar stays cool.", framing={"id": "master"})
            calm_close = motion.for_shot(kit, "The cellar stays cool.", framing={"id": "closeup"})
        self.assertEqual((raised["expressiveness"], calm_close["expressiveness"]), ("medium", "low"))
        self.assertIn("Hollis Reed, a ranch cook in his cookhouse talks", medium["prompt"])
        close = motion.for_shot(kit, "The cellar stays cool.", framing={"id": "closeup", "shot": "medium close-up"})
        self.assertIn("hands stay below the frame", close["motion_prompt"])
        self.assertNotIn("chest height", close["motion_prompt"])
        self.assertEqual(close["expressiveness"], "low")

    def test_tone_lines(self):
        kit = {"name": "Hollis Reed", "set_where": "in a wood-panelled study"}
        end = motion.for_shot(kit, "Keep your fire low and your coffee strong.", role="close")
        self.assertIn("warm, genuine smile", end["motion_prompt"])
        sad = motion.for_shot(kit, "Two families lost everything, and one man died.", role="close")
        self.assertIn("no smile", sad["motion_prompt"])
        self.assertIn("calm, sincere look", sad["motion_prompt"])
        self.assertEqual(sad["expressiveness"], "low")
        self.assertIn("talks seriously and calmly", sad["prompt"])
        q = motion.for_shot(kit, "So why does it matter?", framing={"id": "master"})
        self.assertIn("head tilt", q["motion_prompt"])
        lst = motion.for_shot(kit, "First, brush the dirt off.", framing={"id": "closeup"})
        self.assertIn("small nod as each point", lst["motion_prompt"])
        self.assertIn("Hollis Reed in a wood-panelled study talks", end["prompt"])

    def test_a_kits_own_words_and_the_selfie(self):
        own = {"name": "R", "avatar": {"motion_prompt": "Gentle sway.", "custom_motion": True, "prompt": "R talks.",
                                       "custom_prompt": True, "expressiveness": "high"}}
        got = motion.for_shot(own, "Why?", role="hook")
        self.assertTrue(got["motion_prompt"].startswith("Gentle sway."))
        self.assertIn("greeting the viewer", got["motion_prompt"])
        self.assertEqual((got["prompt"], got["expressiveness"]), ("R talks.", "high"))
        selfie = kits.normalize({"id": "rosa", "name": "Rosa", "master": "https://x.test/m.png",
                                 "camera": "Handheld phone selfie at arm's length"})
        s = motion.for_shot(selfie, "The cellar stays cool.", framing={"id": "master"})
        self.assertIn("Handheld phone selfie", s["motion_prompt"])
        self.assertEqual(s["expressiveness"], "low")
        plain = kits.normalize({"id": "w", "name": "W", "master": "https://x.test/m.png"})
        self.assertFalse(plain["avatar"]["custom_motion"])
        self.assertEqual(plain["avatar"]["motion_prompt"], motion.MEDIUM)

    def test_expressiveness_env(self):
        self.assertIn(motion.DEFAULT_EXPRESSIVENESS, motion.EXPRESSIVENESS)


# ------------------------------------------------------------------ any voice reaches the avatar at one level
class VoiceLevel(unittest.TestCase):
    def test_the_gain(self):
        self.assertEqual(media_io.avatar_gain(None), 0.0)
        self.assertEqual(media_io.avatar_gain({"lufs": -18.4, "peak": -3.0}), 0.0)          # close enough
        self.assertEqual(media_io.avatar_gain({"lufs": -32.0, "peak": -20.0}), 14.0)       # a quiet phone recording
        self.assertEqual(media_io.avatar_gain({"lufs": -30.0, "peak": -6.0}), 5.0)         # held under the peak
        self.assertEqual(media_io.avatar_gain({"lufs": -11.0, "peak": 0.5}), -7.0)         # a hot one, turned down
        self.assertEqual(media_io.avatar_gain({"lufs": -2.0, "peak": 0.0}), -8.0)          # never more than -8 dB

    def test_the_window_is_levelled_but_never_moved(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "v.wav")                              # bursts, like words and pauses
            __import__("subprocess").run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                                          r"aevalsrc=sin(2*PI*220*t)*0.3*mod(floor(t*3.3)\,2):s=24000:d=6",
                                          "-ac", "1", src], check=True)
            plain = media_io.cut_window(src, 1.0, 3.0, os.path.join(d, "a.wav"), pad_before=0.3, pad_after=0.6,
                                        total=6.0)
            loud = media_io.cut_window(src, 1.0, 3.0, os.path.join(d, "b.wav"), pad_before=0.3, pad_after=0.6,
                                       total=6.0, gain_db=6.0, highpass=70)
            self.assertEqual((plain["lead"], plain["seconds"]), (loud["lead"], loud["seconds"]))
            self.assertEqual(loud["gainDb"], 6.0)
            self.assertAlmostEqual(media_io.duration(plain["path"]), media_io.duration(loud["path"]), places=2)
            a, b = media_io.loudness(plain["path"]), media_io.loudness(loud["path"])
            self.assertAlmostEqual(b["lufs"] - a["lufs"], 6.0, delta=0.5)
            lag = media_io.audio_lag(loud["path"], plain["path"])
            self.assertIn(lag, (None, 0.0))

    def test_the_generator_measures_once(self):
        with tempfile.TemporaryDirectory() as d:
            wav = make_wav(os.path.join(d, "v.wav"), 4.0)
            gen = generate.Generator(provider=FakeProvider(), budget=Budget(1), tier={}, kit={"framings": []},
                                     work=d, store=FakeStore(), cache=None, checker=None, narration_wav=wav,
                                     total=4.0, bible={})
            with mock.patch.object(media_io, "loudness", wraps=media_io.loudness) as meas:
                g1, g2 = gen.voice_gain(), gen.voice_gain()
            self.assertEqual(g1, g2)
            self.assertEqual(meas.call_count, 1)
            self.assertIsNotNone(gen.voice_level)


if __name__ == "__main__":
    unittest.main()
