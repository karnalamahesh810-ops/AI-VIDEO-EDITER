"""
The Avatar III presenter model (src/presenter/heygen.py + the choice in tiers / generate / pipeline / hybrid),
offline: HeyGen's API is a fake session, the HeyGen provider a stand-in, no key exists. No network, no paid call.
"""
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from src import costs
from src.presenter import budget as budget_mod, checks, estimate, generate, heygen, hybrid, store, tiers
from src.presenter.providers import Provider, ProviderError, VideoJob, VideoRequest, VideoResult
from tests.test_presenter import FakeProvider, FakeStore, kit_in, make_video, make_wav, shotplan


# ------------------------------------------------------------------ the choice
class Choice(unittest.TestCase):
    def test_ids_and_aliases(self):
        for v in ("avatar_iii", "Avatar-III", "heygen/avatar-iii", "iii", "3", " avatar iii "):
            self.assertEqual(tiers.presenter_model_id(v), "avatar_iii", v)
        for v in ("avatar_iv", "avatar-iv", "heygen/avatar-iv", "IV", 4):
            self.assertEqual(tiers.presenter_model_id(v), "avatar_iv", v)
        for v in (None, "", "v", "avatar_v", 5):
            self.assertEqual(tiers.presenter_model_id(v), "", v)

    def test_the_job_wins_then_the_presenter_then_avatar_iv(self):
        self.assertEqual(tiers.chosen_presenter_model("avatar_iii", "avatar_iv"), "avatar_iii")
        self.assertEqual(tiers.chosen_presenter_model(None, "avatar_iii"), "avatar_iii")
        self.assertEqual(tiers.chosen_presenter_model("nonsense", None), "avatar_iv")
        self.assertEqual(tiers.chosen_presenter_model(), "avatar_iv")
        with mock.patch.dict(os.environ, {"PRESENTER_MODEL_DEFAULT": "avatar_iii"}):
            self.assertEqual(tiers.chosen_presenter_model(None, None), "avatar_iii")

    def test_no_key_means_avatar_iv_and_a_warning(self):
        with mock.patch.dict(os.environ, {"HEYGEN_API_KEY": ""}):
            model, prov, warning = heygen.resolve("avatar_iii")
        self.assertEqual((model, prov), ("heygen/avatar-iv", None))
        self.assertIn("Avatar IV", warning)
        self.assertIn("HEYGEN_API_KEY", warning)
        self.assertEqual(heygen.resolve("avatar_iv"), ("heygen/avatar-iv", None, ""))

    def test_with_a_key_avatar_iii_goes_to_heygen(self):
        stand_in = StandInHeyGen()
        self.assertEqual(heygen.resolve("avatar_iii", provider=stand_in), ("heygen/avatar-iii", stand_in, ""))
        with mock.patch.dict(os.environ, {"HEYGEN_API_KEY": "test-not-a-key"}):
            model, prov, warning = heygen.resolve("iii")
        self.assertEqual((model, warning), ("heygen/avatar-iii", ""))
        self.assertIsInstance(prov, heygen.HeyGen)

    def test_prices(self):
        self.assertEqual(tiers.usd_per_second("heygen/avatar-iii", "1080p"), 0.0165)
        self.assertEqual(tiers.usd_per_second("heygen/avatar-iv", "1080p"), 0.05)
        info = {m["id"]: m for m in tiers.presenter_models_info(False)}
        self.assertEqual((info["avatar_iv"]["usdPerMinute"], info["avatar_iii"]["usdPerMinute"]), (3.0, 0.99))
        self.assertEqual(info["avatar_iii"]["lookSetupUsd"], 1.32)
        self.assertFalse(info["avatar_iii"]["available"])
        self.assertTrue(info["avatar_iv"]["default"])
        self.assertTrue({m["id"]: m for m in tiers.presenter_models_info(True)}["avatar_iii"]["available"])


# ------------------------------------------------------------------ estimates
class Estimates(unittest.TestCase):
    def test_style_estimate_uses_the_models_rate(self):
        iv = estimate.estimate(15, "budget", max_seconds=120)
        iii = estimate.estimate(15, dict(tiers.resolve("budget"), presenter_model=["heygen/avatar-iii", "1080p"]),
                                max_seconds=120)
        self.assertEqual(iv["parts"]["presenter"], 6.6)              # 120 s x 1.1 x $0.05 (unchanged)
        self.assertEqual(iii["parts"]["presenter"], 2.18)            # 120 s x 1.1 x $0.0165
        self.assertEqual(round(iv["usd"] - iii["usd"], 2), 4.42)
        self.assertEqual(iii["models"]["presenter"], ["heygen/avatar-iii", "1080p"])

    def test_hybrid_estimate_and_budget_rate(self):
        iv = hybrid.estimate(15, "medium")
        iii = hybrid.estimate(15, "medium", model="avatar_iii")
        self.assertEqual(iv["usdPerPresenterSecond"], 0.05)
        self.assertEqual(iii["usdPerPresenterSecond"], 0.0165)
        self.assertEqual(iii["lookSetupUsd"], 1.32)
        self.assertNotIn("lookSetupUsd", iv)
        self.assertAlmostEqual(iii["parts"]["presenter"] / iv["parts"]["presenter"], 0.33, places=2)
        self.assertAlmostEqual(hybrid.take_usd(10.0, 1, rate=0.0165), (10.9 * 0.0165) + hybrid.CHECK_USD)
        self.assertEqual(hybrid.take_usd(10.0, 1), hybrid.take_usd(10.0, 1, rate=0.05))
        table = hybrid.estimate_table()
        self.assertIn("avatar_iii", table["byModel"])
        self.assertLess(table["byModel"]["avatar_iii"]["byShare"]["medium"]["15"]["usd"],
                        table["byShare"]["medium"]["15"]["usd"])

    def test_the_hybrid_block_reads_the_model(self):
        b = hybrid.block({"video_style": "documentary", "presenter": {"presenter_id": "ruth", "model": "avatar-iii"}})
        self.assertEqual(b["model"], "avatar_iii")
        b = hybrid.block({"video_style": "documentary", "presenter": {"presenter_id": "ruth"}})
        self.assertEqual(b["model"], "")

    def test_presenter_info_lists_both_models(self):
        from src.presenter import pipeline
        got = pipeline.info()
        self.assertEqual([m["id"] for m in got["presenterModels"]], ["avatar_iv", "avatar_iii"])


# ------------------------------------------------------------------ the HeyGen client (a fake session)
class _Resp:
    def __init__(self, status=200, body=None, content=b""):
        self.status_code, self._body, self.content = status, body, content
        self.text = json.dumps(body) if body is not None else ""

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakeSession:
    """HeyGen v3 as documented (developers.heygen.com, 2026-10-25), recording every request."""

    def __init__(self, engines=("avatar_iii", "avatar_iv"), video_status=("processing", "completed"),
                 wallet_empty=False):
        self.calls = []
        self.engines = list(engines)
        self.video_status = list(video_status)
        self.look_polls = 0
        self.wallet_empty = wallet_empty

    def request(self, method, url, headers=None, json=None, files=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": dict(headers or {}), "json": json,
                           "files": sorted((files or {}).keys())})
        path = url.split("api.heygen.test", 1)[1]
        if path == "/v3/assets" and method == "POST":
            return _Resp(200, {"data": {"asset_id": f"asset{len(self.calls)}", "url": "https://heygen/asset"}})
        if path == "/v3/avatars" and method == "POST":
            return _Resp(200, {"data": {"avatar_item": {"id": "look123"}, "avatar_group": {"id": "g1"}}})
        if path.startswith("/v3/avatars/looks/"):
            self.look_polls += 1
            status = "processing" if self.look_polls == 1 else "completed"
            return _Resp(200, {"data": {"id": "look123", "status": status, "supported_api_engines": self.engines}})
        if path == "/v3/videos" and method == "POST":
            if self.wallet_empty:
                return _Resp(402, {"error": {"code": "insufficient_balance", "message": "Insufficient balance"}})
            return _Resp(200, {"data": {"video_id": "vid9", "status": "waiting", "output_format": "mp4"}})
        if path.startswith("/v3/videos/"):
            st = self.video_status.pop(0) if len(self.video_status) > 1 else self.video_status[0]
            body = {"id": "vid9", "status": st}
            if st == "completed":
                body.update(video_url="https://files.heygen.test/vid9.mp4?Expires=1", duration=6.4)
            return _Resp(200, {"data": body})
        return _Resp(404, {"error": {"message": f"no route {method} {path}"}})

    def get(self, url, timeout=None, headers=None):
        self.calls.append({"method": "GET", "url": url, "headers": dict(headers or {})})
        return _Resp(200, None, content=b"\x00" * 9000)


class Client(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pic = os.path.join(self.tmp.name, "framing.jpg")
        with open(self.pic, "wb") as fh:
            fh.write(b"\xff\xd8 a picture " * 50)
        self.wav = os.path.join(self.tmp.name, "win.wav")
        with open(self.wav, "wb") as fh:
            fh.write(b"RIFF" + b"\x00" * 400)

    def tearDown(self):
        self.tmp.cleanup()

    def client(self, session):
        return heygen.HeyGen(key="secret-test-key", base="https://api.heygen.test", session=session,
                             cache_dir=os.path.join(self.tmp.name, "looks"), sleep=lambda s: None, r2_cache=False)

    def test_look_then_take_then_download(self):
        s = FakeSession()
        c = self.client(s)
        look, made = c.ensure_look(self.pic, name="Walt medium")
        self.assertEqual((look, made), ("look123", True))
        create = next(x for x in s.calls if x["url"].endswith("/v3/avatars"))
        self.assertEqual(create["json"]["type"], "photo")
        self.assertEqual(create["json"]["file"]["type"], "asset_id")
        upload = s.calls[0]
        self.assertEqual(upload["files"], ["file"])                      # multipart, one field "file"
        self.assertNotIn("Content-Type", upload["headers"])
        self.assertTrue(all(x["headers"].get("x-api-key") == "secret-test-key"
                            for x in s.calls if "api.heygen.test" in x["url"]))
        # The same picture again: the cached look, nothing made or paid.
        n = len(s.calls)
        self.assertEqual(c.ensure_look(self.pic), ("look123", False))
        self.assertEqual(c.cached_look(self.pic), "look123")
        self.assertEqual(len(s.calls), n)
        # The take: our own audio by link, the Avatar III engine, no prompt / motion / expressiveness.
        req = VideoRequest(model=heygen.MODEL, resolution="1080p", audio_url="https://r2/win.wav",
                           audio_file=self.wav, options={"heygen_direct": {"avatar_id": look}})
        job = c.submit_video(req)
        body = s.calls[-1]["json"]
        self.assertEqual(body, {"type": "avatar", "avatar_id": "look123", "engine": {"type": "avatar_iii"},
                                "resolution": "1080p", "aspect_ratio": "16:9", "fit": "cover",
                                "audio_url": "https://r2/win.wav"})
        res = c.wait_video(job, poll=0, sleep=lambda s: None)
        self.assertEqual(res.status, "completed")
        self.assertAlmostEqual(res.cost, 6.4 * 0.0165)                   # length x the published rate
        out = os.path.join(self.tmp.name, "take.mp4")
        c.download_video(job, res, out)
        self.assertEqual(os.path.getsize(out), 9000)
        self.assertNotIn("x-api-key", s.calls[-1]["headers"])            # the signed link takes no key

    def test_audio_without_a_link_is_uploaded(self):
        s = FakeSession()
        c = self.client(s)
        c.submit_video(VideoRequest(model=heygen.MODEL, resolution="1080p", audio_url="", audio_file=self.wav,
                                    options={"heygen_direct": {"avatar_id": "look123"}}))
        body = s.calls[-1]["json"]
        self.assertTrue(body["audio_asset_id"].startswith("asset"))
        self.assertNotIn("audio_url", body)

    def test_a_look_avatar_iii_cannot_animate_is_an_account_problem(self):
        c = self.client(FakeSession(engines=("avatar_iv",)))
        with self.assertRaises(ProviderError) as cm:
            c.ensure_look(self.pic)
        self.assertTrue(heygen.account_problem(cm.exception))
        self.assertTrue(cm.exception.billed)                              # the photo avatar was made (and paid)
        self.assertIsNone(c.cached_look(self.pic))

    def test_an_empty_wallet_is_an_account_problem_and_the_key_is_never_shown(self):
        c = self.client(FakeSession(wallet_empty=True))
        with self.assertRaises(ProviderError) as cm:
            c.submit_video(VideoRequest(model=heygen.MODEL, audio_url="https://r2/w.wav",
                                        options={"heygen_direct": {"avatar_id": "look123"}}))
        self.assertEqual(cm.exception.status, 402)
        self.assertTrue(heygen.account_problem(cm.exception))
        self.assertNotIn("secret-test-key", str(cm.exception))

    def test_a_failed_take_costs_nothing(self):
        c = self.client(FakeSession(video_status=("failed",)))
        res = c.poll_video(VideoJob(id="vid9", model=heygen.MODEL, submitted=time.time(), raw={"resolution": "1080p"}))
        self.assertEqual((res.status, res.cost), ("failed", 0.0))

    def test_no_key_no_call(self):
        c = heygen.HeyGen(key="", base="https://api.heygen.test", session=FakeSession())
        self.assertFalse(c.available())
        with self.assertRaises(ProviderError):
            c.upload_asset(self.pic)


# ------------------------------------------------------------------ the generator with Avatar III
class StandInHeyGen(Provider):
    """The HeyGen provider's surface, writing real clips; `fail` raises that ProviderError on submit."""
    name = "heygen"

    def __init__(self, fail=None):
        self.fail = fail
        self.looks = {}
        self.made = 0
        self.videos = []

    def available(self):
        return True

    def cached_look(self, path):
        return self.looks.get(path)

    def ensure_look(self, path, name=""):
        if path in self.looks:
            return self.looks[path], False
        self.made += 1
        self.looks[path] = f"look{self.made}"
        return self.looks[path], True

    def forget_look(self, path):
        self.looks.pop(path, None)

    def submit_video(self, req):
        self.videos.append(req)
        if self.fail is not None:
            raise self.fail
        return VideoJob(id=f"hg{len(self.videos)}", model=req.model, submitted=time.time(),
                        raw={"resolution": req.resolution})

    def poll_video(self, job):
        return VideoResult(status="completed", cost=round(8.0 * 0.0165, 6))

    def download_video(self, job, result, out_path):
        return make_video(out_path, 12.0)


class Generation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = self.tmp.name
        self.kit = kit_in(os.path.join(self.work, "kitsrc"))
        self.wav = make_wav(os.path.join(self.work, "n.wav"), 30)
        costs.reset()

    def tearDown(self):
        costs.reset()
        self.tmp.cleanup()

    def gen(self, provider, hg, cap=10.0):
        b = budget_mod.Budget(cap)
        tier = dict(tiers.resolve("budget"), presenter_model=["heygen/avatar-iii", "1080p"])
        g = generate.Generator(provider=provider, budget=b, tier=tier, kit=self.kit, work=self.work,
                               store=FakeStore(), cache=store.Cache(os.path.join(self.work, "cache")),
                               checker=checks.Checker(provider, b, self.work), narration_wav=self.wav, total=30.0,
                               bible={}, avatar_provider=hg)
        return g, b

    @staticmethod
    def shot(sid="p000", start=0.0, end=5.0, framing="medium"):
        return shotplan.Shot(kind="presenter", start=start, end=end, text="a line", words=[], beats=[0],
                             framing=framing, still="a crate", motion="", id=sid)

    def test_takes_go_to_heygen_and_the_look_is_paid_once(self):
        orp, hg = FakeProvider(), StandInHeyGen()
        g, b = self.gen(orp, hg)
        a1 = g.presenter(self.shot("p000", 0.0, 5.0))
        a2 = g.presenter(self.shot("p001", 6.0, 11.0))
        self.assertEqual((a1.source, a1.model, a2.model), ("ai-presenter", "heygen/avatar-iii", "heygen/avatar-iii"))
        self.assertEqual(len(hg.videos), 2)
        self.assertFalse([r for r in orp.videos if "avatar" in r.model])    # no presenter take on OpenRouter
        req = hg.videos[0]
        self.assertEqual(req.options, {"heygen_direct": {"avatar_id": "look1"}})
        self.assertEqual(req.prompt, "")                                    # Avatar III takes no prompt
        self.assertTrue(req.audio_file.endswith(".wav"))
        looks = [r for r in b.rows if r.get("kind") == "heygen_look"]
        self.assertEqual(len(looks), 1)                                     # one photo avatar for the framing
        self.assertEqual(looks[0]["usd"], heygen.LOOK_USD)
        self.assertEqual(g.looks_made, 1)
        s = costs.summary(1.0)
        self.assertEqual(s["breakdown"]["presenter"]["avatar_iii"]["calls"], 2)
        self.assertEqual(s["breakdown"]["presenter"]["heygen_look"]["calls"], 1)
        self.assertEqual(g.warnings, [])

    def test_an_account_problem_moves_the_job_to_avatar_iv(self):
        orp = FakeProvider()
        hg = StandInHeyGen(fail=ProviderError("submit heygen/avatar-iii: HTTP 402: Insufficient balance", 402))
        g, _b = self.gen(orp, hg)
        a = g.presenter(self.shot())
        self.assertEqual(a.source, "ai-presenter")
        self.assertEqual(a.model, "heygen/avatar-iv")
        self.assertEqual(a.framing, "medium")                               # the same framing, now on Avatar IV
        self.assertEqual([r.model for r in orp.videos], ["heygen/avatar-iv"])
        self.assertTrue(g.heygen_off)
        self.assertEqual(len(g.warnings), 1)
        self.assertIn("Avatar IV", g.warnings[0])
        # Later takes skip HeyGen.
        g.presenter(self.shot("p001", 6.0, 11.0))
        self.assertEqual(len(hg.videos), 1)
        rep = heygen.model_report("avatar_iii", "heygen/avatar-iii", g)
        self.assertEqual((rep["asked"], rep["used"], rep["provider"]), ("avatar_iii", "avatar_iv", "openrouter"))
        self.assertTrue(rep["fallback"])

    def test_a_passing_error_stays_on_heygen(self):
        orp = FakeProvider()
        hg = StandInHeyGen(fail=ProviderError("submit heygen/avatar-iii: HTTP 503: busy", 503))
        g, _b = self.gen(orp, hg)
        a = g.presenter(self.shot())
        # Both framings tried on HeyGen, then the still fallback: never a silent switch to the dearer model.
        self.assertEqual(len(hg.videos), 2)
        self.assertFalse(g.heygen_off)
        self.assertEqual(a.kind, "image")

    def test_the_budget_refuses_a_look_it_has_no_room_for(self):
        orp, hg = FakeProvider(), StandInHeyGen()
        g, _b = self.gen(orp, hg, cap=0.5)
        a = g.presenter(self.shot())
        self.assertEqual(hg.made, 0)
        self.assertNotEqual(getattr(a, "source", ""), "ai-presenter")

    def test_report_without_heygen(self):
        rep = heygen.model_report("avatar_iii", "heygen/avatar-iv", None)
        self.assertEqual((rep["used"], rep["fallback"]), ("avatar_iv", "no HeyGen API key on this worker"))
        rep = heygen.model_report("avatar_iv", "heygen/avatar-iv", None)
        self.assertEqual((rep["asked"], rep["used"], rep["fallback"], rep["usdPerSecond"]),
                         ("avatar_iv", "avatar_iv", "", 0.05))


if __name__ == "__main__":
    unittest.main()
