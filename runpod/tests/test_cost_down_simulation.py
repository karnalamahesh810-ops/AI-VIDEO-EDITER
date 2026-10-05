"""A realistic scene set through the real sourcing code, with every paid call counted
(the cost plan, 2026-10-05).

24 footage lines about 4 places (6 lines each, as a passage stays on one subject)
go through media.source_many -> the provider registry -> the YouTube candidate
pool (scouts, the fine pass, downloads, the judge) and, when no clip passes, the
picture search - the same code a build runs. Only the outside world is simulated:
YouTube's search rows, its storyboards, the downloads, the picture search and
the vision model, whose answers come from a fixed truth per candidate:

  - each place's best-titled uploads are a channel with a logo bug and an AI-made
    "cinematic" video: a storyboard tile cannot show either, so the scout passes
    them and only the judge, on the real frames, turns them down;
  - the next ones are real footage of the place (scored 0.78-0.9), one is
    another place (the scout already sees that);
  - each place's top picture results are an agency preview with its watermark
    and an AI-made picture, then real photos.

Calls are priced at what they cost on OpenRouter (fitted to the Yellowstone and
Lake Powell builds' own bills, within $0.002): a judge call $0.00056, a scout
$0.00081, a fine pass $0.00142 on google/gemini-2.5-flash; $0.00025 and $0.00035
on google/gemini-2.5-flash-lite.

What must hold: with every lever off the shots are the ones the code always
picked; JUDGE_MEMORY makes fewer paid calls and fewer downloads for the same
shots; VISION_TILE_MODEL makes the same calls for less money, the same shots
when the cheaper model agrees, and only judge-approved shots when it does not.
"""
import base64
import json
import os
import shutil
import tempfile
import threading
import unittest
from collections import Counter
from unittest import mock

from src import config, media, moments, vision
from src.media import MediaAsset

OPENROUTER = "https://openrouter.ai/api/v1"
MAIN, CHEAP = "google/gemini-2.5-flash", "google/gemini-2.5-flash-lite"
PRICE = {("judge", MAIN): 0.00056, ("pick", MAIN): 0.00081, ("rate", MAIN): 0.00142,
         ("pick", CHEAP): 0.00025, ("rate", CHEAP): 0.00035, ("judge", CHEAP): 0.00021}

SUBJECTS = ["Lake Powell", "Glen Canyon Dam", "Lees Ferry", "Rainbow Bridge"]
ASPECTS = ["shoreline at low water", "aerial view", "boats on the water", "canyon walls",
           "visitors at the overlook", "sunset over the water"]
# (title words after the subject, what the frames really are, the judge's score for the subject)
VIDEOS = [("4K drone aerial footage", "watermark", 0.0),
          ("drone aerial footage 4k", "ai", 0.85),
          ("aerial footage", "good", 0.9),
          ("drone footage", "elsewhere", 0.45),      # titled for the place, filmed somewhere else
          ("raw footage", "good", 0.78),
          ("footage", "good", 0.8)]
PICTURES = [("agency", "watermark", 0.0), ("render", "ai", 0.8), ("photo1", "good", 0.86),
            ("elsewhere", "elsewhere", 0.4), ("photo2", "good", 0.8), ("photo3", "good", 0.76)]


def _vid(s: int, v: int) -> str:
    return f"s{s}v{v}xxxxxxxx"[:11]


def _b64(obj) -> str:
    return base64.b64encode(json.dumps(obj).encode()).decode()


class World:
    """The simulated outside world, and the bill."""

    def __init__(self, work: str, cheap_agrees: bool = True):
        self.work = work
        self.cheap_agrees = cheap_agrees
        self.lock = threading.Lock()
        self.calls = Counter()
        self.downloads = Counter()
        self.n = 0

    # --- YouTube -----------------------------------------------------------
    @staticmethod
    def rows(subject: str):
        s = SUBJECTS.index(subject)
        return [{"id": _vid(s, v), "title": f"{subject} {words}", "duration": 600.0, "aspect": 1.78,
                 "channel": f"channel {s}{v}", "url": f"https://www.youtube.com/watch?v={_vid(s, v)}"}
                for v, (words, _k, _sc) in enumerate(VIDEOS)]

    @staticmethod
    def truth(vid: str):
        s, v = int(vid[1]), int(vid[3])
        return SUBJECTS[s], VIDEOS[v][1], VIDEOS[v][2]

    def info(self, vid: str):
        subject, _k, _s = self.truth(vid)
        return {"id": vid, "title": f"{subject} video", "duration": 600.0, "width": 1920, "height": 1080}, ""

    def sheet(self, info, seconds, proxy="", tiles=20, window=None):
        if window:
            lo = max(0.0, window[0])
            times = [lo + k for k in range(int(window[1] - lo))][:tiles]
        else:
            times = [30.0 * k for k in range(1, 21)]
        return _b64({"vid": info["id"], "fine": bool(window)}), times

    def fetch(self, vid, out_dir, start, need, title="", least=None):
        bucket = int(start // 10)
        with self.lock:
            self.n += 1
            self.downloads["clip"] += 1
            path = os.path.join(out_dir, f"yt_{vid}_{bucket}_{self.n}.mp4")
        with open(path, "w") as fh:
            fh.write(f"clip|{vid}|{bucket}")
        return path, True, 0

    # --- pictures ------------------------------------------------------------
    @staticmethod
    def search_pictures(query, *a, **k):
        subject = next(s for s in SUBJECTS if s.split()[0] in query)
        slug = subject.replace(" ", "-").lower()
        return [MediaAsset(kind="image", source="web_image", url=f"https://img.example/{slug}/{pid}.jpg",
                           attribution=f"{subject} {pid}") for pid, _k, _s in PICTURES]

    def download(self, candidate, query, work_dir):
        with self.lock:
            self.n += 1
            self.downloads["picture"] += 1
            path = os.path.join(self.work, f"pic_{self.n}.jpg")
        with open(path, "w") as fh:
            fh.write(f"picture|{candidate.url}")
        candidate.local_path = path
        return candidate

    @staticmethod
    def picture_truth(url: str):
        slug, name = url.split("/")[-2], url.split("/")[-1][:-4]
        subject = next(s for s in SUBJECTS if s.replace(" ", "-").lower() == slug)
        kind, score = next((k, s) for pid, k, s in PICTURES if pid == name)
        return subject, kind, score

    # --- the vision model ----------------------------------------------------
    def frames(self, path, count=3, width=512):
        with open(path) as fh:
            return [base64.b64encode(fh.read().encode()).decode()]

    def ask(self, messages, max_tokens, accept=None, first=""):
        system = messages[0]["content"]
        system = system if isinstance(system, str) else system[0]["text"]
        user = messages[1]["content"]
        text = user[0]["text"]
        data = base64.b64decode(next(p for p in user if p["type"] == "image_url")["image_url"]["url"].split(",", 1)[1])
        model = first or MAIN
        if system.startswith("You check whether"):
            kind = "judge"
        elif system.startswith(vision._PICK_SYSTEM[:40]):
            kind = "pick"
        else:
            kind = "rate"
        with self.lock:
            self.calls[(kind, model)] += 1
        intent = text.split("INTENT", 1)[1] if "INTENT" in text else text
        if kind == "judge":
            what = data.decode().split("|")
            if what[0] == "clip":
                subject, truth, score = self.truth(what[1])
            else:
                subject, truth, score = self.picture_truth(what[1])
            if subject.split()[0] not in intent:
                score = min(score, 0.3)
            verdict = {"description": f"{truth} {subject}", "score": score, "quality": 0.8,
                       "has_text_or_watermark": truth == "watermark", "is_talking_head": False,
                       "ai_generated": truth == "ai", "studio": False, "specificity": "location"}
            return json.dumps(verdict), model
        sheet = json.loads(data)
        subject, truth, score = self.truth(sheet["vid"])
        # At thumbnail size a logo bug or an AI look cannot be seen; another place can -
        # unless it is the cheaper model getting it wrong.
        seen = 0.8 if truth in ("watermark", "ai") else score
        if truth == "elsewhere" and model == CHEAP and not self.cheap_agrees:
            seen = 0.8
        if kind == "pick":
            return json.dumps({"tile": 5, "score": seen, "description": f"tile of {subject}"}), model
        tiles = [{"tile": t, "score": max(seen, 0.75), "description": "x"} for t in range(4, 10)]
        return json.dumps({"tiles": tiles}), model

    def usd(self) -> float:
        return round(sum(PRICE[k] * n for k, n in self.calls.items()), 5)


def jobs():
    out = []
    for i in range(len(SUBJECTS) * len(ASPECTS)):
        subject, aspect = SUBJECTS[i // len(ASPECTS)], ASPECTS[i % len(ASPECTS)]
        out.append({"index": i, "query": f"{subject} {aspect}", "intent": f"{subject} {aspect}",
                    "subject": subject, "subject_type": "place", "visual_type": "footage", "seconds": 6.0,
                    "context": f"The {aspect} at {subject}.", "start": 7.0 * i})
    return out


def simulate(memory: bool = False, tile_model: str = "", cheap_agrees: bool = True) -> dict:
    work = tempfile.mkdtemp(prefix="costsim_")
    try:
        world = World(work, cheap_agrees)
        empty = lambda *a, **k: []  # noqa: E731
        settings = dict(VISION_API_BASE=OPENROUTER, VISION_API_KEY="k", VISION_MODEL=MAIN, VISION_FALLBACK_MODELS=[],
                        AI_FALLBACK_API_BASE="", AI_FALLBACK_API_KEY="", VISION_ENABLED=True,
                        VISION_TILE_MODEL=tile_model, JUDGE_MEMORY=memory, MOMENT_SELECTION=True,
                        MOMENT_FINE_PASS=True, CANDIDATE_POOL=True, POOL_SCOUT=2, JUDGE_BEST_OF=2,
                        EXCELLENT_SCORE=0.85, VISION_MAX_CANDIDATES=3, JUDGE_MAX_PER_SCENE=12,
                        ALLOW_DAILYMOTION=False, ALLOW_WEB_VIDEO=False, ALLOW_YANDEX_IMAGES=False,
                        ALLOW_ARCHIVE_ORG=False, OFFICIAL_IMAGERY=False, ALLOW_STOCK=False, ALLOW_YOUTUBE=True,
                        REQUIRE_CC=False, PREFER_GENERATED_IMAGES=False, IMAGE_MAX_PER_VIDEO=0,
                        FRESH_MOMENTS=False, PICTURE_PREFETCH=0, LOCAL_VISION_ENABLED=False,
                        EYEWITNESS_SEARCHES=False, PICK_A_SHOT=False, SHOT_MAX_SECONDS=0)
        patches = [mock.patch.multiple(config, **settings),
                   mock.patch.object(media, "_story_channels", return_value=[]),
                   mock.patch.object(media, "_yt_candidates_cached",
                                     side_effect=lambda target, cc, subject="", variant="": World.rows(subject)),
                   mock.patch.object(media, "_yt_info", side_effect=world.info),
                   mock.patch.object(media, "fetch_clean_clip", side_effect=world.fetch),
                   mock.patch.object(media, "motion_rejects", return_value=""),
                   mock.patch.object(media, "has_burned_captions", return_value=False),
                   mock.patch.object(media, "clip_detail_reason", return_value=""),
                   mock.patch.object(media, "apply_motion", return_value=None),
                   mock.patch.object(media, "_note_detail", return_value=None),
                   mock.patch.object(media, "slop_reason", return_value=""),
                   mock.patch.object(media, "watermark_reason", return_value=""),
                   mock.patch.object(media, "_photo_seen_before", return_value=False),
                   mock.patch.object(media, "_asset_ok", return_value=(True, "")),
                   mock.patch.object(media, "_download", side_effect=world.download),
                   mock.patch.object(media, "search_web_images", side_effect=world.search_pictures),
                   mock.patch.object(media, "search_wikipedia_article_images", side_effect=empty),
                   mock.patch.object(media, "search_wikimedia", side_effect=empty),
                   mock.patch.object(media, "search_nasa", side_effect=empty),
                   mock.patch.object(media, "search_openverse", side_effect=empty),
                   mock.patch.object(media, "search_nasa_video", side_effect=empty),
                   mock.patch.object(media, "search_wikimedia_video", side_effect=empty),
                   mock.patch.object(media, "search_archive_org_video", side_effect=empty),
                   mock.patch.object(moments, "contact_sheet", side_effect=world.sheet),
                   mock.patch.object(vision, "sample_frames", side_effect=world.frames),
                   mock.patch.object(vision, "_ask", side_effect=world.ask)]
        for p in patches:
            p.start()
        try:
            media.reset_cache()
            vision.set_story({})
            results = media.source_many(jobs(), work, workers=1, rescue=None)
            media.drain_pools(5.0)
            tile = vision.stats().get("tileModel")
        finally:
            for p in reversed(patches):
                p.stop()
            media.reset_cache()
        picks = {i: (a.identity if a else None) for i, a in enumerate(results)}
        scores = {i: a.relevance_score for i, a in enumerate(results) if a}
        return {"picks": picks, "scores": scores, "calls": dict(world.calls), "usd": world.usd(),
                "paid_calls": sum(world.calls.values()), "downloads": dict(world.downloads),
                "kinds": Counter(k for k, _m in world.calls.elements()), "tileModel": tile}
    finally:
        shutil.rmtree(work, True)


def _bad_pick(identity: str) -> bool:
    """A shot no line should show: another place, a logo bug, AI-made."""
    if not identity:
        return False
    if identity.startswith("yt:"):
        return World.truth(identity[3:])[1] != "good"
    return World.picture_truth(identity.split(":", 1)[1])[1] != "good"


class SceneSet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = simulate()
        cls.memory = simulate(memory=True)
        cls.tile = simulate(tile_model=CHEAP)
        cls.both = simulate(memory=True, tile_model=CHEAP)
        cls.tile_wrong = simulate(memory=True, tile_model=CHEAP, cheap_agrees=False)
        cls.report = {name: {k: r[k] for k in ("paid_calls", "usd", "downloads")} | {"kinds": dict(r["kinds"])}
                      for name, r in (("off", cls.base), ("JUDGE_MEMORY", cls.memory),
                                      ("VISION_TILE_MODEL", cls.tile), ("both", cls.both),
                                      ("both, cheap model wrong on places", cls.tile_wrong))}
        if os.environ.get("COST_SIM_REPORT"):
            print(json.dumps(cls.report, indent=1))

    def test_with_every_lever_off_the_scene_set_is_sourced_as_always(self):
        picks = self.base["picks"]
        self.assertEqual(len(picks), 24)
        self.assertTrue(all(picks.values()), picks)                       # every line found a shot
        self.assertFalse([p for p in picks.values() if _bad_pick(p)])    # and only good ones
        self.assertEqual(self.base["calls"].get(("pick", CHEAP), 0), 0)   # the cheap model never asked
        self.assertIsNone(self.base["tileModel"])

    def test_judge_memory_pays_less_for_the_same_shots(self):
        self.assertEqual(self.memory["picks"], self.base["picks"])
        self.assertEqual(self.memory["scores"], self.base["scores"])
        self.assertLess(self.memory["paid_calls"], self.base["paid_calls"])
        self.assertLess(self.memory["kinds"]["judge"], self.base["kinds"]["judge"])
        self.assertLess(sum(self.memory["downloads"].values()), sum(self.base["downloads"].values()))
        self.assertLess(self.memory["usd"], self.base["usd"])

    def test_the_tile_model_makes_the_same_calls_for_less_money_and_the_same_shots(self):
        self.assertEqual(self.tile["picks"], self.base["picks"])
        self.assertEqual(self.tile["paid_calls"], self.base["paid_calls"])
        self.assertEqual(self.tile["kinds"], self.base["kinds"])
        self.assertEqual(self.tile["calls"].get(("judge", CHEAP), 0), 0)   # the judge stays on the main model
        self.assertLess(self.tile["usd"], self.base["usd"] * 0.8)
        self.assertEqual(self.tile["tileModel"]["answered"], self.tile["tileModel"]["asked"])

    def test_both_together_cost_least(self):
        self.assertEqual(self.both["picks"], self.base["picks"])
        self.assertLess(self.both["usd"], min(self.memory["usd"], self.tile["usd"]))

    def test_a_cheap_model_that_misreads_places_only_costs_downloads(self):
        got = self.tile_wrong
        self.assertFalse([p for p in got["picks"].values() if _bad_pick(p)])   # the judge caught every one
        self.assertTrue(all(got["picks"].values()))
        self.assertGreaterEqual(sum(got["downloads"].values()), sum(self.both["downloads"].values()))


if __name__ == "__main__":
    unittest.main()
