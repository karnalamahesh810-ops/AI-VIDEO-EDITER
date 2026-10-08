"""
The AI presenter style (src/presenter), offline: the shot planner against the
owner's reference recipe, the cost estimator, the budget guard, every
fallback of the generator (with a fake provider that writes real files), the
assembled timeline, kits, costs and the renderer contract. No network: the
provider, the storage and the checks' model are fakes.
"""
import io
import json
import os
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from PIL import Image

import handler
from src import config, costs, styles, timeline, transcribe
from src.presenter import (assemble, budget as budget_mod, checks, director, estimate, generate, kits, media_io,
                           providers, shotplan, store, tiers)
from src.presenter.providers import ChatResult, ImageResult, ProviderError, VideoJob, VideoResult

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


# ------------------------------------------------------------------ fixtures
def words_for(sentences, start=0.0, wps=2.9, gap=0.35):
    """Evenly paced words for a list of sentences (a beat of narration each)."""
    out, t = [], start
    for sent in sentences:
        for tok in sent.split():
            out.append(transcribe.Word(text=tok, start=round(t, 3), end=round(t + 1.0 / wps * 0.9, 3)))
            t += 1.0 / wps
        t += gap
    return out


SENTENCES = [
    "Stop keeping your potatoes and onions in the same basket right now.",
    "I have watched good folks lose half their winter potatoes that way.",
    "Onions put off moisture and a gas that makes potatoes sprout fast.",
    "And the potatoes turn right around and rot your onions in a week.",
    "My name is Walt, I am seventy eight, from Taylor County in Texas.",
    "My mama taught me better on our farm outside Abilene in 1961.",
    "Here is the first thing, potatoes go in a wooden crate or a box.",
    "Do not wash them, just brush the dry dirt off with your hand.",
    "Lay newspaper between every layer of potatoes in the crate.",
    "Set the box somewhere dark and cool like the cellar or the stairs.",
    "Water pours off the roof in spring and the cellar stays damp.",
    "Steam rises from the pot when the potatoes boil on the stove.",
    "Now the onions, drop them in an old pair of pantyhose.",
    "Tie a knot between each onion so they never touch each other.",
    "Hang them up where the air moves, on the porch rafter.",
    "When you need one, snip it off below the knot with scissors.",
    "The wind sways the string of onions on the porch all winter.",
    "Here is the secret most people never hear about at all.",
    "Keep an apple out of both baskets, it ripens everything near it.",
    "We ate our own potatoes clear through to March every year.",
    "Try it this fall and tell me your county in the comments.",
    "I read every comment, and next week I will show you the root cellar.",
]


def segments_for(sentences=SENTENCES):
    words = words_for(sentences)
    segs, i = [], 0
    for sent in sentences:
        n = len(sent.split())
        ws = words[i:i + n]
        i += n
        segs.append(transcribe.Segment(text=sent, start=ws[0].start, end=ws[-1].end, words=ws))
    total = words[-1].end + 0.6
    return segs, total


def make_png(path, w=1920, h=1080, colour=(140, 110, 80)):
    im = Image.new("RGB", (w, h), colour)
    for x in range(0, w, 97):           # some structure, so it is not a flat field
        for y in range(0, h, 61):
            im.putpixel((x, y), (255 - colour[0], 200, 30))
    im.save(path)
    return path


def png_bytes(w=1920, h=1080):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (120, 100, 70)).save(buf, "PNG")
    return buf.getvalue()


def make_video(path, seconds=12.0, size="640x360", audio=False):
    args = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=25"]
    if audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000"]
    args += ["-t", f"{seconds:.2f}", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast"]
    if audio:
        args += ["-c:a", "aac", "-shortest"]
    subprocess.run(args + [path], check=True)
    return path


def make_wav(path, seconds=20.0):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"sine=frequency=220:sample_rate=24000:duration={seconds:.2f}", "-ac", "1", path], check=True)
    return path


class FakeProvider(providers.Provider):
    """Answers like OpenRouter, writes real files, records every call."""
    name = "fake"

    def __init__(self, fail_models=(), verdict=None, clip_seconds=12.0):
        self.fail_models = set(fail_models)
        self.verdict = verdict
        self.clip_seconds = clip_seconds
        self.videos, self.images, self.chats = [], [], []

    def available(self):
        return True

    def submit_video(self, req):
        self.videos.append(req)
        if req.model in self.fail_models:
            raise ProviderError(f"{req.model} refused", status=400)
        return VideoJob(id=f"job{len(self.videos)}", model=req.model, submitted=time.time())

    def poll_video(self, job):
        return VideoResult(status="completed", cost=0.3)

    def download_video(self, job, result, out_path):
        return make_video(out_path, self.clip_seconds)

    def image(self, req):
        self.images.append(req)
        if req.model in self.fail_models:
            raise ProviderError(f"{req.model} refused", status=400)
        return ImageResult(data=png_bytes(), ext=".png", cost=0.05, model=req.model, seconds=0.1)

    def chat(self, model, messages, **kw):
        self.chats.append(messages)
        text = messages[-1]["content"]
        text = text if isinstance(text, str) else json.dumps(text)
        if self.verdict is not None:
            body = self.verdict(text)
        elif "same_person" in text:
            body = {"same_person": 0.92, "natural": 0.9, "issues": []}
        else:
            body = {"real": 0.9, "match": 0.85, "issues": []}
        return ChatResult(text=json.dumps(body), cost=0.0005, model=model, seconds=0.1)


class FakeStore(store.Store):
    def __init__(self):
        super().__init__("proj", "job", enabled=False)
        self.puts = []

    def put(self, local, name, temp=False, content_type=""):
        self.puts.append((name, temp))
        return f"https://r2.example.test/{'inputs' if temp else 'assets'}/{name}"

    def cleanup(self):
        return 0


def kit_in(folder, framings=("medium", "wide"), sets=("kitchen",)):
    os.makedirs(folder, exist_ok=True)
    make_png(os.path.join(folder, "master.png"), 2752, 1536)
    raw = {"id": "walt", "name": "Walt", "title": "West Texas farmer", "_base": folder,
           "persona": "a fictional 78-year-old West Texas farmer", "wardrobe": "plaid flannel shirt",
           "master": "master.png",
           "framings": [{"id": f, "url": make_png(os.path.join(folder, f"{f}.png"))} for f in framings],
           "sets": [{"id": s, "url": make_png(os.path.join(folder, f"{s}.png"), colour=(90, 80, 60))} for s in sets]}
    return kits.normalize(raw)


# ------------------------------------------------------------------ the shot planner
class ShotPlan(unittest.TestCase):
    def plan(self, share=0.14, video=0.15, split=0.33, broll=0.15, sentences=SENTENCES):
        segs, total = segments_for(sentences)
        shots = shotplan.plan(segs, total, presenter_share=share, ai_video_share=video, presenter_broll=broll,
                              framings=("medium", "wide"), split_share=split)
        return shots, total

    def test_shots_tile_the_narration_exactly(self):
        shots, total = self.plan()
        self.assertAlmostEqual(shots[0].start, 0.0)
        self.assertAlmostEqual(shots[-1].end, total)
        for a, b in zip(shots, shots[1:]):
            self.assertAlmostEqual(a.end, b.start)
            self.assertGreater(a.seconds, 0.9)

    def test_opens_and_closes_on_the_presenter_with_broll_between(self):
        shots, _ = self.plan()
        self.assertEqual(shots[0].kind, "presenter")
        self.assertEqual(shots[0].role, "hook")
        self.assertEqual(shots[-1].kind, "presenter")
        for a, b in zip(shots, shots[1:]):
            self.assertFalse(a.kind == "presenter" and b.kind == "presenter", (a.as_dict(), b.as_dict()))

    def test_reference_mix_and_pace(self):
        shots, total = self.plan()
        st = shotplan.stats(shots, total)
        self.assertGreaterEqual(st["shares"]["presenter"], 0.12)
        self.assertLessEqual(st["shares"]["presenter"], 0.30)       # the hook and close are fixed costs on 75 s
        self.assertGreater(st["shares"]["ai_video"], 0.06)
        self.assertGreater(st["shares"]["picture"], 0.45)
        self.assertGreaterEqual(st["cutsPerMinute"], 10)
        self.assertLessEqual(st["cutsPerMinute"], 20)

    def test_presenter_shot_lengths(self):
        shots, _ = self.plan()
        pres = [s for s in shots if s.kind == "presenter"]
        self.assertLessEqual(pres[0].seconds, shotplan.PRESENTER_FIRST_MAX + 1e-6)
        for s in pres:
            self.assertGreaterEqual(s.seconds, 2.0)
        for s in pres[1:]:
            self.assertLessEqual(s.seconds, shotplan.PRESENTER_MAX + 0.6)

    def test_presenter_comes_back_within_the_gap_on_a_long_video(self):
        shots, total = self.plan(sentences=SENTENCES * 4)
        pres = [s for s in shots if s.kind == "presenter"]
        gaps = [b.start - a.end for a, b in zip(pres, pres[1:])]
        self.assertLessEqual(max(gaps), shotplan.MAX_GAP + 8.0)
        st = shotplan.stats(shots, total)
        self.assertGreaterEqual(st["shares"]["presenter"], 0.11)
        self.assertLessEqual(st["shares"]["presenter"], 0.22)

    def test_a_long_opening_line_cuts_away_on_a_word_while_the_voice_runs_on(self):
        long = ("Stop keeping your potatoes and onions in the same basket, because I have watched good folks "
                "lose half their winter potatoes that way, year after year, and it breaks my heart every time, "
                "because those folks worked all summer long in the heat for every single one of those potatoes.")
        shots, _ = self.plan(sentences=[long] + SENTENCES[1:])
        first = shots[0]
        self.assertEqual(first.kind, "presenter")
        self.assertLessEqual(first.seconds, shotplan.PRESENTER_FIRST_MAX + 1e-6)
        self.assertNotEqual(shots[1].kind, "presenter")
        self.assertEqual(shots[1].beats[0], 0)                   # the same line goes on under the b-roll
        starts = {w.start for w in shots[1].words}
        self.assertIn(shots[1].start, starts)                    # the cut lands on a word

    def test_about_a_third_of_middle_appearances_split_never_hook_or_close(self):
        shots, _ = self.plan(sentences=SENTENCES * 4)
        pres = [s for s in shots if s.kind == "presenter"]
        self.assertFalse(pres[0].split)
        self.assertFalse(pres[-1].split)
        middle = [s for s in pres if s.role not in ("hook", "close")]
        self.assertTrue(middle)
        share = sum(s.split for s in middle) / len(middle)
        self.assertGreater(share, 0.15)
        self.assertLess(share, 0.5)

    def test_no_presenter_share_no_presenter(self):
        shots, _ = self.plan(share=0.0, video=0.0)
        self.assertEqual({s.kind for s in shots}, {"picture"})

    def test_the_jobs_cap_on_the_presenters_time(self):
        # presenter_max_seconds (only when the job sends it): a 13-minute plan whose share asks for ~145 s keeps
        # its hook and close and spreads the rest evenly within the cap; split screens count.
        segs, total = segments_for(SENTENCES * 12)

        def plan(cap):
            planner = shotplan.Planner(shotplan.beats_from(segs, total),
                                       [shotplan.rule_note(s.text, i, len(segs)) for i, s in enumerate(segs)], total,
                                       presenter_share=0.14, ai_video_share=0.15, presenter_broll=0.15,
                                       framings=("medium", "wide"), split_share=0.33, max_seconds=cap)
            shots = planner.plan()
            return shots, [s for s in shots if s.kind == "presenter"], planner
        _shots, free, planner = plan(None)
        self.assertIsNone(planner.capped)
        self.assertGreater(sum(s.seconds for s in free), 120.0)
        shots, pres, planner = plan(120.0)
        self.assertLessEqual(sum(s.seconds for s in pres), 120.0 + 1e-6)     # split screens included
        self.assertTrue(any(s.split for s in pres))
        self.assertEqual((pres[0].role, pres[0].start, pres[-1].role), ("hook", 0.0, "close"))
        self.assertAlmostEqual(pres[-1].end, total)
        self.assertEqual(planner.capped["maxSeconds"], 120.0)
        gaps = [b.start - a.end for a, b in zip(pres, pres[1:])]
        self.assertLessEqual(max(gaps), 2.0 * total / (len(pres) - 1))      # spread over the whole video
        self.assertAlmostEqual(shots[0].start, 0.0)                          # the shots still tile the narration
        self.assertAlmostEqual(shots[-1].end, total)
        for a, b in zip(shots, shots[1:]):
            self.assertAlmostEqual(a.end, b.start)
        # A tiny cap keeps the hook and the close alone; a plan within the cap is exactly the uncapped one.
        _s, pres, _p = plan(5.0)
        self.assertEqual([s.role for s in pres], ["hook", "close"])
        short, total_short = segments_for()
        kw = dict(presenter_share=0.14, ai_video_share=0.15, presenter_broll=0.15, framings=("medium", "wide"),
                  split_share=0.33)
        self.assertEqual([s.as_dict() for s in shotplan.plan(short, total_short, max_seconds=120.0, **kw)],
                         [s.as_dict() for s in shotplan.plan(short, total_short, **kw)])

    def test_framings_alternate_like_two_cameras(self):
        shots, _ = self.plan(sentences=SENTENCES * 2)
        fr = [s.framing for s in shots if s.kind == "presenter"]
        self.assertEqual(fr[0], "medium")
        self.assertIn("wide", fr)

    def test_moving_lines_become_ai_video(self):
        shots, _ = self.plan(video=0.15)
        vids = [s for s in shots if s.kind == "ai_video"]
        self.assertTrue(vids)
        self.assertTrue(all(s.seconds >= shotplan.AI_MIN - 1e-6 for s in vids))
        text = " ".join(s.text for s in vids).lower()
        self.assertTrue(any(w in text for w in ("water", "steam", "wind", "sways", "pours", "boil")), text)

    def test_notes_from_the_planner_set_prompts_and_the_alternative_goes_to_a_second_piece(self):
        segs, total = segments_for()
        beats = shotplan.beats_from(segs, total)
        notes = [shotplan.Note(role="body", presenter_fit=0.1, still=f"still {b.index}", alt=f"alt {b.index}",
                               motion=f"move {b.index}") for b in beats]
        shots = shotplan.Planner(beats, notes, total, presenter_share=0.14, ai_video_share=0.1,
                                 framings=("medium",)).plan()
        pic = next(s for s in shots if s.kind != "presenter")
        self.assertEqual(pic.still, f"still {pic.beats[0]}")
        self.assertEqual(pic.motion, f"move {pic.beats[0]}")

    def test_rules_note(self):
        n = shotplan.rule_note("Here is the secret most people never hear.", 5, 20)
        self.assertEqual(n.role, "chapter")
        self.assertGreater(n.presenter_fit, 0.5)
        self.assertGreater(shotplan.rule_note("Steam rises from the pot.", 3, 9).needs_motion, 0.5)
        self.assertTrue(shotplan.rule_note("I tie a knot between each onion.", 3, 9).in_shot)
        self.assertEqual(shotplan.rule_note("anything", 0, 9).role, "hook")


# ------------------------------------------------------------------ tiers and the estimator
class TiersAndEstimate(unittest.TestCase):
    def test_default_tier_is_the_reference_mix(self):
        t = tiers.resolve(None)
        self.assertEqual(t["id"], "budget")
        self.assertEqual(tiers.resolve("reference")["id"], "budget")
        self.assertAlmostEqual(t["presenter_share"], 0.14)
        self.assertAlmostEqual(t["ai_video_share"], 0.15)
        self.assertAlmostEqual(t["split_share"], 0.33)
        for name in tiers.all_tiers():
            spec = tiers.resolve(name)
            # The presenter in the b-roll is always drawn from the master on Nano Banana Pro.
            self.assertEqual(tiers.pairs(spec, "presenter_image_models")[0][0], "google/gemini-3-pro-image")
            self.assertEqual(spec["presenter_model"][0], "heygen/avatar-iv")
            for model, _res in tiers.pairs(spec, "video_models") + tiers.pairs(spec, "image_models"):
                self.assertIn(model, tiers.MODELS, model)

    def test_standard_and_premium_raise_the_clip_share(self):
        b, s, p = (tiers.resolve(x)["ai_video_share"] for x in ("budget", "standard", "premium"))
        self.assertLess(b, s)
        self.assertLess(s, p)

    def test_job_and_environment_overrides(self):
        t = tiers.resolve("standard", {"ai_video_share": 0.5, "video_models": [["google/veo-3.1-lite", "720p"]]})
        self.assertEqual(t["ai_video_share"], 0.5)
        self.assertEqual(tiers.pairs(t, "video_models"), [("google/veo-3.1-lite", "720p")])
        with mock.patch.dict(os.environ, {"PRESENTER_TIERS": json.dumps({"budget": {"presenter_share": 0.2}})}):
            self.assertEqual(tiers.resolve("budget")["presenter_share"], 0.2)
        self.assertEqual(tiers.resolve("nonsense")["id"], tiers.DEFAULT_TIER)

    def test_clip_lengths_the_model_accepts(self):
        self.assertEqual(tiers.clip_seconds_for("google/veo-3.1-lite", 4.6), 6)
        self.assertEqual(tiers.clip_seconds_for("bytedance/seedance-1-5-pro", 3.0), 4)
        self.assertEqual(tiers.clip_seconds_for("minimax/hailuo-3-max", 30.0), 15)

    def test_twenty_minutes_matches_the_reference_counts(self):
        e = estimate.estimate(20, "budget")
        self.assertGreaterEqual(e["counts"]["stills"], 200)
        self.assertLessEqual(e["counts"]["stills"], 240)
        self.assertGreaterEqual(e["counts"]["aiClips"], 30)
        self.assertLessEqual(e["counts"]["aiClips"], 40)
        self.assertGreaterEqual(e["counts"]["presenterMinutes"], 2.5)
        self.assertLessEqual(e["counts"]["presenterMinutes"], 4.0)
        self.assertAlmostEqual(e["usd"], round(sum(e["parts"].values()), 2), places=1)

    def test_table_for_the_app(self):
        t = estimate.table()
        self.assertEqual(set(t["tiers"]), {"budget", "standard", "premium"})
        for tier in t["tiers"].values():
            self.assertEqual(set(tier["byMinutes"]), {"10", "15", "20"})
            u = [tier["byMinutes"][m]["usd"] for m in ("10", "15", "20")]
            self.assertTrue(u[0] < u[1] < u[2])
        for m in ("10", "15", "20"):
            b, s, p = (t["tiers"][x]["byMinutes"][m]["usd"] for x in ("budget", "standard", "premium"))
            self.assertTrue(b < s < p, (m, b, s, p))
        own = estimate.estimate(15, "budget", own_voice=True)
        self.assertEqual(own["parts"]["voice"], 0.0)

    def test_the_estimate_keeps_to_the_jobs_cap(self):
        free, capped = estimate.estimate(20, "budget"), estimate.estimate(20, "budget", max_seconds=120)
        self.assertEqual((free["seconds"]["presenter"], capped["seconds"]["presenter"]), (168, 120))
        self.assertEqual(capped["seconds"]["stills"] - free["seconds"]["stills"], 48)     # the stills take the rest
        self.assertLess(capped["usd"], free["usd"])
        self.assertEqual((free["maxSeconds"], capped["maxSeconds"]), (None, 120.0))
        # Within the cap nothing changes.
        short = estimate.estimate(10, "budget", max_seconds=120)
        self.assertEqual({k: v for k, v in short.items() if k != "maxSeconds"},
                         {k: v for k, v in estimate.estimate(10, "budget").items() if k != "maxSeconds"})


# ------------------------------------------------------------------ the budget guard
class BudgetGuard(unittest.TestCase):
    def test_reserve_settle_release_and_refuse(self):
        b = budget_mod.Budget(1.0)
        t1 = b.reserve(0.6, "a")
        with self.assertRaises(budget_mod.BudgetExceeded):
            b.reserve(0.5, "b")                       # 0.6 reserved + 0.5 > 1.0
        b.settle(t1, 0.4)
        self.assertAlmostEqual(b.spent, 0.4)
        t2 = b.reserve(0.5, "c")
        b.release(t2, "failed before billing")
        self.assertAlmostEqual(b.committed, 0.4)
        t3 = b.reserve(0.3, "d")
        b.settle(t3, None)                            # no price in the answer: the projection counts
        self.assertAlmostEqual(b.spent, 0.7)
        self.assertEqual(b.report()["refused"], 1)


# ------------------------------------------------------------------ requests as OpenRouter takes them
class Requests(unittest.TestCase):
    def test_avatar_body_matches_the_prototypes_working_call(self):
        body = providers.VideoRequest(model="heygen/avatar-iv", prompt="talks", resolution="1080p",
                                      images=["data:image/jpeg;base64,xx"], audio_url="https://r2/x.wav",
                                      options={"heygen": {"motion_prompt": "calm"}}).body()
        self.assertEqual(body["input_references"][0]["type"], "image_url")
        self.assertEqual(body["input_references"][1], {"type": "audio_url", "audio_url": {"url": "https://r2/x.wav"}})
        self.assertEqual(body["provider"], {"options": {"heygen": {"motion_prompt": "calm"}}})
        self.assertNotIn("duration", body)

    def test_clip_body(self):
        body = providers.VideoRequest(model="bytedance/seedance-1-5-pro", prompt="push in", resolution="720p",
                                      duration=5, first_frame="https://r2/a.jpg", generate_audio=False, seed=7).body()
        self.assertEqual(body["frame_images"][0]["frame_type"], "first_frame")
        self.assertIs(body["generate_audio"], False)
        self.assertEqual(body["duration"], 5)

    def test_the_key_comes_from_the_workers_openrouter_settings(self):
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}), \
                mock.patch.object(config, "DIRECTOR_API_BASE", "https://openrouter.ai/api/v1"), \
                mock.patch.object(config, "DIRECTOR_API_KEY", "k-director"):
            self.assertEqual(providers.openrouter_key(), "k-director")
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}), \
                mock.patch.object(config, "DIRECTOR_API_BASE", "https://api.kie.ai/v1"), \
                mock.patch.object(config, "DIRECTOR_API_KEY", "k-kie"), \
                mock.patch.object(config, "VISION_API_BASE", "https://vision.invalid/v1"), \
                mock.patch.object(config, "IMAGE_API_BASE", "https://api.openai.com/v1"):
            self.assertEqual(providers.openrouter_key(), "")            # never a Kie key

    def test_algrow_is_a_slot_not_a_provider_yet(self):
        self.assertFalse(providers.AlgrowREST().available())
        with mock.patch.dict(os.environ, {"PRESENTER_PROVIDER": "algrow"}):
            self.assertIsInstance(providers.get(), providers.OpenRouter)


# ------------------------------------------------------------------ ffmpeg helpers
class MediaHelpers(unittest.TestCase):
    def test_a_window_past_the_start_is_padded_so_the_scene_starts_at_the_lead(self):
        with tempfile.TemporaryDirectory() as d:
            wav = make_wav(os.path.join(d, "n.wav"), 10)
            got = media_io.cut_window(wav, 0.0, 4.0, os.path.join(d, "w.wav"), pad_before=0.3, pad_after=0.6,
                                      total=10.0)
            self.assertAlmostEqual(got["lead"], 0.3)
            self.assertAlmostEqual(media_io.duration(got["path"]), 4.9, delta=0.05)
            end = media_io.cut_window(wav, 8.0, 10.0, os.path.join(d, "e.wav"), pad_before=0.3, pad_after=0.6,
                                      total=10.0)
            self.assertAlmostEqual(media_io.duration(end["path"]), 2.9, delta=0.05)

    def test_audio_lag_finds_a_shift(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "bursts.wav")
            # Speech-like bursts: noise on and off.
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "anoisesrc=d=6:c=pink:r=16000:a=0.5", "-af",
                            "volume='if(lt(mod(t,0.9),0.45),1,0.02)':eval=frame", src], check=True)
            late = os.path.join(d, "late.wav")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-af", "adelay=120:all=1", late], check=True)
            lag = media_io.audio_lag(late, src)
            self.assertIsNotNone(lag)
            self.assertAlmostEqual(lag, 0.12, delta=0.03)

    def test_trim_removes_the_sound(self):
        with tempfile.TemporaryDirectory() as d:
            v = make_video(os.path.join(d, "v.mp4"), 6, audio=True)
            out = media_io.trim(v, os.path.join(d, "t.mp4"), 1.0, 3.0)
            info = media_io.probe(out)
            self.assertEqual(info["audio"], 0)
            self.assertAlmostEqual(info["duration"], 3.0, delta=0.1)


# ------------------------------------------------------------------ the generator: tries, retries, fallbacks
class Generation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = self.tmp.name
        self.kit = kit_in(os.path.join(self.work, "kitsrc"))
        self.wav = make_wav(os.path.join(self.work, "n.wav"), 30)

    def tearDown(self):
        self.tmp.cleanup()

    def gen(self, provider, cap=10.0, tier="budget"):
        b = budget_mod.Budget(cap)
        st = FakeStore()
        g = generate.Generator(provider=provider, budget=b, tier=tiers.resolve(tier), kit=self.kit, work=self.work,
                               store=st, cache=store.Cache(os.path.join(self.work, "cache")),
                               checker=checks.Checker(provider, b, self.work), narration_wav=self.wav, total=30.0,
                               bible={"place": "a farm", "light": "window light"})
        return g, b, st

    @staticmethod
    def shot(kind, start=0.0, end=5.0, sid="p000", framing="medium", split=False, in_shot=False):
        return shotplan.Shot(kind=kind, start=start, end=end, text="a line", words=[], beats=[0], framing=framing,
                             still="a crate of potatoes", motion="slow push in", id=sid, split=split, in_shot=in_shot)

    def test_presenter_shot_trimmed_to_its_scene_muted_and_checked(self):
        p = FakeProvider()
        g, b, st = self.gen(p)
        a = g.presenter(self.shot("presenter", 0.0, 5.0))
        self.assertEqual(a.source, "ai-presenter")
        self.assertEqual(a.attempts, 1)
        info = media_io.probe(a.path)
        self.assertEqual(info["audio"], 0)
        self.assertGreaterEqual(info["duration"], 5.0 - 0.05)
        self.assertLessEqual(info["duration"], 5.0 + generate.CLIP_HANDLE + 0.1)
        req = p.videos[0]
        self.assertEqual(req.model, "heygen/avatar-iv")
        self.assertTrue(req.audio_url.startswith("https://"))           # audio by https link only
        self.assertTrue(a.checks["face"]["ok"])
        self.assertIn(("p000_medium_0.wav", True), st.puts)             # the voice window went up as a temp input

    def test_presenter_retries_on_the_other_framing(self):
        p = FakeProvider()
        calls = {"n": 0}
        real = p.submit_video

        def flaky(req):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ProviderError("upstream 502", status=502)
            return real(req)
        p.submit_video = flaky
        g, _b, _s = self.gen(p)
        a = g.presenter(self.shot("presenter"))
        self.assertEqual(a.source, "ai-presenter")
        self.assertEqual(a.attempts, 2)
        self.assertNotEqual(a.framing, "medium")                         # the other camera

    def test_presenter_face_check_failure_falls_back_to_a_still(self):
        def verdict(text):
            if "same_person" in text:
                return {"same_person": 0.2, "natural": 0.9, "issues": ["different_person"]}
            return {"real": 0.9, "match": 0.9, "issues": []}
        p = FakeProvider(verdict=verdict)
        g, _b, _s = self.gen(p)
        a = g.presenter(self.shot("presenter"))
        self.assertEqual(a.kind, "image")
        self.assertEqual(a.source, "ai-image")
        self.assertIn("presenter -> still", a.fallback)
        self.assertEqual(len(p.videos), 2)                               # both framings tried first

    def test_clip_falls_back_to_its_still_when_every_model_fails(self):
        p = FakeProvider(fail_models={"bytedance/seedance-1-5-pro", "google/veo-3.1-lite"})
        g, _b, _s = self.gen(p)
        a = g.ai_video(self.shot("ai_video", 5.0, 9.0, sid="v001"))
        self.assertEqual(a.kind, "image")
        self.assertIn("AI video -> its still", a.fallback)
        self.assertEqual([r.model for r in p.videos], ["bytedance/seedance-1-5-pro", "google/veo-3.1-lite"])

    def test_clip_rejected_by_the_look_check_tries_the_next_model(self):
        seen = {"n": 0}

        def verdict(text):
            if "frames (start, middle, end)" in text:
                seen["n"] += 1
                if seen["n"] == 1:
                    return {"real": 0.8, "match": 0.8, "issues": ["melted_hands"]}
            return {"real": 0.9, "match": 0.9, "issues": []}
        p = FakeProvider(verdict=verdict)
        g, _b, _s = self.gen(p)
        a = g.ai_video(self.shot("ai_video", 5.0, 9.0, sid="v002"))
        self.assertEqual(a.source, "ai-video")
        self.assertEqual(a.attempts, 2)
        self.assertEqual(a.model, "google/veo-3.1-lite")
        self.assertIsNone(media_io.probe(a.path)["audio"] or None)

    def test_a_retry_asks_for_what_the_check_found_wrong(self):
        seen = {"n": 0}

        def verdict(text):
            if "b-roll photograph" in text:
                seen["n"] += 1
                if seen["n"] == 1:
                    return {"real": 0.9, "match": 0.9, "issues": ["garbled_text"]}
            return {"real": 0.9, "match": 0.9, "issues": []}
        p = FakeProvider(verdict=verdict)
        g, _b, _s = self.gen(p)
        a = g.still(self.shot("picture", sid="i009"), in_shot=False)
        self.assertEqual(a.attempts, 2)
        self.assertNotIn("no legible letters", p.images[0].prompt)
        self.assertIn("no legible letters", p.images[1].prompt)

    def test_still_falls_back_to_the_kit_set_once_never_twice(self):
        p = FakeProvider(fail_models={"google/gemini-nano-banana-2.1", "google/gemini-3.1-flash-image"})
        g, _b, _s = self.gen(p)
        first = g.still(self.shot("picture", sid="i001"), in_shot=False)
        self.assertEqual(first.source, "kit-set")
        self.assertIsNone(g.still(self.shot("picture", sid="i002"), in_shot=False))

    def test_presenter_in_the_broll_uses_the_master_on_nano_banana_pro(self):
        p = FakeProvider()
        g, _b, _s = self.gen(p)
        a = g.still(self.shot("picture", sid="i003", in_shot=True), in_shot=True)
        self.assertEqual(a.model, "google/gemini-3-pro-image")
        self.assertEqual(len(p.images[0].references), 1)
        self.assertIn("reference photo", p.images[0].prompt)

    def test_over_the_cap_nothing_is_called_and_the_video_still_gets_a_picture(self):
        p = FakeProvider()
        g, b, _s = self.gen(p, cap=0.01)
        a = g.presenter(self.shot("presenter"))
        self.assertEqual(a.source, "kit-set")
        self.assertEqual(p.videos, [])
        self.assertEqual(p.images, [])
        self.assertGreater(b.report()["refused"], 0)

    def test_a_paid_call_is_never_paid_twice(self):
        p = FakeProvider()
        g, b, _s = self.gen(p)
        g.presenter(self.shot("presenter"))
        spent = b.spent
        g2, b2, _s2 = self.gen(p)
        a = g2.presenter(self.shot("presenter"))
        self.assertEqual(a.cached, "disk")
        self.assertEqual(len(p.videos), 1)
        self.assertGreater(spent, 0)

    def test_a_split_half_has_no_people_and_a_back_view_is_the_presenters(self):
        kit = dict(self.kit, from_behind="an old man with short white hair in a brown canvas jacket")
        half = generate.still_prompt("a person seen from behind, face not visible, at the table", {}, kit, False,
                                     no_people=True)
        self.assertIn("No people and no hands", half)
        back = generate.still_prompt("a person seen from behind, face not visible, at the cellar door", {}, kit, False)
        self.assertIn("The person seen from behind is an old man with short white hair", back)
        plain = generate.still_prompt("a person seen from behind at the door", {}, dict(self.kit), False)
        self.assertIn("dressed in plaid flannel shirt", plain)

    def test_run_makes_every_shot_and_split_halves(self):
        p = FakeProvider()
        g, _b, _s = self.gen(p)
        shots = [self.shot("presenter", 0, 5, "p000"), self.shot("picture", 5, 9, "i001"),
                 self.shot("ai_video", 9, 13, "v002"), self.shot("presenter", 13, 18, "p003", "wide", split=True),
                 self.shot("picture", 18, 22, "i004")]
        got = g.run(shots)
        self.assertEqual(set(got), {"p000", "i001", "v002", "p003", "i004", "p003" + generate.SPLIT})
        self.assertTrue(all(v is not None for v in got.values()))
        self.assertEqual(got["p003" + generate.SPLIT].kind, "image")


# ------------------------------------------------------------------ the planner model
class Planner(unittest.TestCase):
    def test_model_notes_are_used_and_hook_close_kept(self):
        segs, total = segments_for(SENTENCES[:6])
        beats = shotplan.beats_from(segs, total)

        def verdict(text):
            return {"bible": {"place": "a West Texas farm", "season": "autumn"},
                    "beats": [{"i": b.index, "role": "body", "fit": 0.1, "move": 0.9, "me": b.index == 2,
                               "still": f"still {b.index}", "alt": f"alt {b.index}", "motion": "push"} for b in beats]}
        p = FakeProvider(verdict=verdict)
        got = director.annotate(beats, title="t", kit={"persona": "Walt", "world": {}}, provider=p,
                                budget=budget_mod.Budget(1.0), models=["m1"])
        self.assertEqual(got["planner"], "m1")
        self.assertEqual(got["notes"][0].role, "hook")
        self.assertEqual(got["notes"][-1].role, "close")
        self.assertEqual(got["notes"][3].still, "still 3")
        self.assertTrue(got["notes"][2].in_shot)
        self.assertEqual(got["bible"]["place"], "a West Texas farm")
        self.assertIn("Setting: a West Texas farm", director.bible_line(got["bible"]))

    def test_the_same_request_is_answered_from_the_cache(self):
        segs, total = segments_for(SENTENCES[:3])
        beats = shotplan.beats_from(segs, total)
        answer = {"bible": {"place": "farm"}, "beats": [{"i": b.index, "still": f"s{b.index}"} for b in beats]}
        p = FakeProvider(verdict=lambda t: answer)
        with tempfile.TemporaryDirectory() as d:
            for _ in range(2):
                got = director.annotate(beats, title="t", kit={"world": {}}, provider=p,
                                        budget=budget_mod.Budget(1.0), models=["m1"], cache=d)
                self.assertEqual(got["notes"][1].still, "s1")
        self.assertEqual(len(p.chats), 1)                                  # paid once

    def test_rules_when_the_model_fails_or_the_budget_is_spent(self):
        segs, total = segments_for(SENTENCES[:4])
        beats = shotplan.beats_from(segs, total)
        bad = FakeProvider(verdict=lambda t: {"nope": 1})
        got = director.annotate(beats, title="t", kit={"world": {}}, provider=bad, budget=budget_mod.Budget(1.0),
                                models=["m1"])
        self.assertEqual(got["planner"], "rules")
        got = director.annotate(beats, title="t", kit={"world": {}}, provider=FakeProvider(),
                                budget=budget_mod.Budget(0.0), models=["m1"])
        self.assertEqual(got["planner"], "rules")
        self.assertTrue(got["errors"])


# ------------------------------------------------------------------ the timeline
class Assembly(unittest.TestCase):
    def test_a_line_with_nothing_is_held_by_a_still_or_a_clip_never_the_presenter(self):
        A, S = generate.Asset, shotplan.Shot
        shots = [S("presenter", 0, 5, "a", [], [0], id="p0"), S("picture", 5, 7, "b", [], [1], id="i1"),
                 S("presenter", 7, 12, "c", [], [2], id="p2"), S("picture", 12, 14, "d", [], [3], id="i3"),
                 S("ai_video", 14, 18, "e", [], [4], id="v4"), S("picture", 18, 30, "f", [], [5], id="i5")]
        assets = {"p0": A("p0", "video", "p0.mp4", "ai-presenter", seconds=5.5), "i1": None,
                  "p2": A("p2", "video", "p2.mp4", "ai-presenter", seconds=5.5), "i3": None,
                  "v4": A("v4", "video", "v4.mp4", "ai-video", seconds=4.5), "i5": None}
        got = assemble.settle(shots, assets)
        ids = [(s.id, round(s.start, 1), round(s.end, 1), a.source if a else None) for s, a in got]
        self.assertEqual(ids[1], ("i1", 5, 7, None))                 # between two presenter shots: stays empty
        self.assertEqual(ids[3], ("v4", 12, 18, "ai-video"))         # held forward by the clip (4.5 s over 6 s)
        self.assertEqual(ids[4], ("i5", 18, 30, None))               # 12 s is too long for a 4.5 s clip


    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.kit = kit_in(os.path.join(d, "kitsrc"))
        self.wav = make_wav(os.path.join(d, "narration.wav"), 20)
        self.clip = make_video(os.path.join(d, "p.mp4"), 6.0)
        self.clip2 = make_video(os.path.join(d, "p2.mp4"), 6.0)
        self.vclip = make_video(os.path.join(d, "v.mp4"), 5.0)
        self.stills = [make_png(os.path.join(d, f"s{i}.jpg"), colour=(60 + 20 * i, 90, 70)) for i in range(4)]

    def tearDown(self):
        self.tmp.cleanup()

    def assets(self):
        A = generate.Asset
        return {
            "p000": A("p000", "video", self.clip, "ai-presenter", "heygen/avatar-iv", 0.25, seconds=5.5,
                      framing="medium", width=640, height=360),
            "i001": A("i001", "image", self.stills[0], "ai-image", "nb", 0.05, url="https://r2.test/i001.jpg"),
            "v002": A("v002", "video", self.vclip, "ai-video", "seedance", 0.13, seconds=5.0, width=640, height=360),
            "i003": None,
            "p004": A("p004", "video", self.clip2, "ai-presenter", "heygen/avatar-iv", 0.25, seconds=5.5,
                      framing="wide", width=640, height=360),
            "p004" + generate.SPLIT: A("p004s", "image", self.stills[1], "ai-image", "nb", 0.05,
                                       url="https://r2.test/split.jpg"),
            "i005": A("i005", "image", self.stills[2], "ai-image", "nb", 0.05),
        }

    def shots(self):
        S = shotplan.Shot
        w = lambda a: [shotplan.W("word", a + 0.1, a + 0.4)]   # noqa: E731
        return [S("presenter", 0.0, 5.0, "hook line", w(0), [0], role="hook", framing="medium", id="p000"),
                S("picture", 5.0, 8.5, "crate", w(5), [1], still="a crate", id="i001"),
                S("ai_video", 8.5, 12.5, "steam", w(8.5), [2], still="steam", id="v002"),
                S("picture", 12.5, 14.0, "missing", w(12.5), [3], id="i003"),
                S("presenter", 14.0, 18.5, "key line", w(14), [4], role="why", framing="wide", split=True, id="p004"),
                S("picture", 18.5, 20.0, "close", w(18.5), [5], id="i005")]

    def build(self, **inp):
        return assemble.build(shots=self.shots(), assets=self.assets(), audio_url=self.wav, narration_path=self.wav,
                              duration=20.0, inp={"title": "t", **inp}, kit=self.kit)

    def test_document_tiles_and_is_valid(self):
        doc, items = self.build()
        timeline.validate(doc, require_media=True)
        self.assertEqual(len(doc["scenes"]), 5)                      # the missing line is held by the clip before
        self.assertEqual(doc["scenes"][2]["durationInFrames"], round(14.0 * 30) - round(8.5 * 30))
        self.assertEqual([s["media"]["source"] for s in doc["scenes"]],
                         ["ai-presenter", "ai-image", "ai-video", "ai-presenter", "ai-image"])

    def test_bare_edit_by_default(self):
        doc, _ = self.build()
        self.assertTrue(all(s["transition"] == "none" for s in doc["scenes"]))
        self.assertTrue(all(s["effect"] == "none" and s["treatment"] == "none" for s in doc["scenes"]))
        self.assertFalse(doc["captions"]["enabled"])
        self.assertEqual(doc["overlays"], [])
        self.assertEqual(doc["sfx"], [])
        self.assertIsNone(doc["bgm"])
        self.assertIsNone(doc.get("grade"))
        self.assertNotIn("look", doc)
        self.assertEqual(doc["scenes"][1]["motion"] in assemble.STILL_MOVES, True)

    def test_living_photos_run_with_the_bare_look_too(self):
        with mock.patch.object(assemble.living, "place", return_value={"layered": 0}) as lp, \
                mock.patch.object(config, "LIVING_PHOTOS", True):
            doc, _ = self.build()
        lp.assert_called_once()
        self.assertEqual(doc["meta"]["living"], {"layered": 0})

    def test_split_screen_scene(self):
        doc, _ = self.build()
        sc = doc["scenes"][3]
        self.assertEqual(sc["frame"], "split")
        self.assertEqual(sc["media"]["split"]["url"], "https://r2.test/split.jpg")
        self.assertEqual(sc["media"]["split"]["type"], "image")
        self.assertEqual(sc["semanticMetadata"]["presenter"]["framing"], "wide")

    def test_toggles(self):
        doc, _ = self.build(look="warm", lower_third=True, captions=True, dissolves=1.0)
        self.assertEqual(doc["grade"]["preset"], "warm-doc")
        self.assertGreater(doc["look"]["grain"], 0)
        lt = [o for o in doc["overlays"] if o.get("template") == "KT_LOWER_THIRD"]
        self.assertEqual(len(lt), 1)
        self.assertEqual(lt[0]["text"], "Walt")
        self.assertGreaterEqual(lt[0]["startFrame"], 0)
        self.assertTrue(doc["captions"]["enabled"])
        # Dissolves only between b-roll, never into or out of the presenter.
        tr = [s["transition"] for s in doc["scenes"]]
        self.assertEqual(tr[0], "none")
        self.assertEqual(tr[1], "none")
        self.assertEqual(tr[3], "none")
        self.assertEqual(tr[4], "none")
        timeline.validate(doc, require_media=True)


# ------------------------------------------------------------------ kits
class Kits(unittest.TestCase):
    def test_another_catalogue_layout_loads(self):
        with tempfile.TemporaryDirectory() as d:
            make_png(os.path.join(d, "ruth_master.png"))
            make_png(os.path.join(d, "ruth_a.png"))
            make_png(os.path.join(d, "plate_b.png"))
            cat = {"presenters": [{"slug": "ruth", "persona": {"name": "Ruth Calder", "title": "butcher",
                                                                "wardrobe": "brown apron", "description": "a 79-year-old"},
                                   "master_url": "ruth_master.png", "angles": ["ruth_a.png"],
                                   "plates": {"kitchen": {"path": "plate_b.png"}}, "style": "camera"}]}
            p = os.path.join(d, "catalogue.json")
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(cat, fh)
            with mock.patch.dict(os.environ, {"PRESENTER_KITS_FILE": p}):
                kits.catalogue(refresh=True)
                k = kits.for_job({"presenter_id": "ruth"})
            kits.catalogue(refresh=True)
            self.assertEqual(k["name"], "Ruth Calder")
            self.assertEqual(k["title"], "butcher")
            self.assertEqual(k["wardrobe"], "brown apron")
            self.assertEqual([f["id"] for f in k["framings"]], ["master", "f0"])
            self.assertEqual(k["sets"][0]["id"], "kitchen")
            self.assertTrue(os.path.isfile(kits.fetch(k, k["sets"][0]["url"], os.path.join(d, "got"))))

    def test_the_five_kit_catalogue_layout(self):
        """The layout of C:\\ThumGenius\\presenter_kits_2026-10-07\\catalogue.json (the kits agent, 2026-10-07)."""
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "rosa"))
            names = ("rosa_master", "rosa_wide", "rosa_closeup", "rosa_three_quarter", "rosa_set_plate",
                     "rosa_set_wide", "rosa_task")
            for n in names:
                make_png(os.path.join(d, "rosa", f"{n}.png"), 640, 360)
            cat = {"kit_dir": d, "presenters": [{
                "id": "rosa", "display_name": "Rosa Delgado", "age": 66, "bio": "Rosa Delgado, 66, raised a big family.",
                "room": "Her bright family kitchen with blue tile.", "wardrobe": "Cream cotton blouse.",
                "camera": "Handheld phone selfie at arm's length.",
                "images": {"master": "rosa/rosa_master.png",
                           "framings": {"wide": "rosa/rosa_wide.png", "closeup": "rosa/rosa_closeup.png",
                                        "three_quarter": "rosa/rosa_three_quarter.png"},
                           "sets": {"set_plate": "rosa/rosa_set_plate.png", "set_wide": "rosa/rosa_set_wide.png"},
                           "task": "rosa/rosa_task.png"},
                "voice": {"id": "mexican_grandmother", "label": "Mexican grandmother", "sample_mp3": "rosa/v.mp3",
                          "recommended_speed": 0.85}}]}
            p = os.path.join(d, "catalogue.json")
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(cat, fh)
            with mock.patch.dict(os.environ, {"PRESENTER_KITS_FILE": p}):
                kits.catalogue(refresh=True)
                k = kits.for_job({"presenter_id": "rosa"})
            kits.catalogue(refresh=True)
            self.assertEqual(k["name"], "Rosa Delgado")
            self.assertEqual([f["id"] for f in k["framings"]], ["master", "closeup", "wide", "three_quarter"])
            self.assertEqual([s["id"] for s in k["sets"]], ["set_plate", "set_wide", "task"])
            self.assertIn("blue tile", k["world"]["place"])
            self.assertIn("selfie", k["avatar"]["motion_prompt"].lower())
            self.assertEqual(k["voice"]["suggested"], "Mexican grandmother")
            for f in k["framings"] + k["sets"]:
                self.assertTrue(os.path.isfile(kits.fetch(k, f["url"], os.path.join(d, "got"))))

    def test_a_job_brings_its_catalogue_with_a_base_url(self):
        cat = {"presenters": [{"id": "ruth", "display_name": "Ruth Calder",
                               "images": {"master": "ruth/ruth_master.png",
                                          "framings": {"closeup": "ruth/ruth_closeup.png"}}}]}
        k = kits.for_job({"presenter_id": "ruth", "presenter_catalogue": cat,
                          "presenter_base_url": "https://pub.example/presenters/"})
        self.assertEqual(kits.link(k, k["master"]), "https://pub.example/presenters/ruth/ruth_master.png")
        self.assertEqual([f["id"] for f in k["framings"]], ["master", "closeup"])
        inline = kits.for_job({"presenter_kit": {"id": "hollis", "master": "hollis/m.png"},
                               "presenter_base_url": "https://pub.example/presenters"})
        self.assertEqual(kits.link(inline, inline["master"]), "https://pub.example/presenters/hollis/m.png")
        self.assertEqual(kits.link({"_base": "/x"}, "a/b.png"), "")          # a local catalogue stays files

    def test_a_catalogue_by_link(self):
        class R:
            status_code = 200

            @staticmethod
            def json():
                return {"kits": [{"id": "mae", "name": "Mae", "master": "https://x.test/mae.jpg"}]}
        with mock.patch.dict(os.environ, {"PRESENTER_KITS_URL": "https://x.test/catalogue.json"}), \
                mock.patch.object(kits.requests, "get", return_value=R()) as get:
            kits.catalogue(refresh=True)
            k = kits.for_job({"presenter_id": "mae"})
        kits.catalogue(refresh=True)
        self.assertEqual(k["name"], "Mae")
        get.assert_called_once()
        self.assertEqual(json.load(open(kits.CATALOGUE, encoding="utf-8"))["kits"], [])   # nothing in the public repo

    def test_inline_kit_unknown_id_and_selfie_motion(self):
        k = kits.for_job({"presenter_kit": {"id": "rosa", "name": "Rosa", "master": "https://x.test/m.jpg",
                                            "style": "selfie"}})
        self.assertIn("selfie", k["avatar"]["motion_prompt"].lower())
        with self.assertRaises(kits.KitError):
            kits.for_job({"presenter_id": "nobody-at-all"})


# ------------------------------------------------------------------ the whole pipeline, offline
class Pipeline(unittest.TestCase):
    def test_script_words_take_the_scripts_text_and_the_voices_times(self):
        from src.presenter import pipeline
        spoken = words_for(["My daddy called it walking the rose."])
        got = pipeline.script_words(spoken, "My daddy called it walking the rows.")
        self.assertEqual([w.text for w in got], "My daddy called it walking the rows.".split())
        self.assertAlmostEqual(got[-1].start, spoken[-1].start)
        self.assertEqual(pipeline.script_words(spoken, "Something else entirely here."), spoken)

    def test_words_from_a_job_and_the_budget_cap(self):
        from src.presenter import pipeline
        got = pipeline.words_from([{"w": "Hi", "s": 0.1, "e": 0.4}, {"text": "x", "start": 1, "end": 1},
                                   {"word": "there", "start": 0.5, "end": 0.9}])
        self.assertEqual([w.text for w in got], ["Hi", "there"])          # the zero-length word dropped
        self.assertEqual(pipeline.budget_cap({"presenter_budget_usd": 2.5}, {"usd": 9}), 2.5)
        with mock.patch.dict(os.environ, {"PRESENTER_BUDGET_USD": ""}):
            self.assertEqual(pipeline.budget_cap({}, {"usd": 4.0}), 6.0)

    def test_the_presenters_time_is_capped_only_when_the_job_sends_it(self):
        from src.presenter import pipeline
        self.assertIsNone(pipeline.max_seconds_of({}))
        self.assertEqual(pipeline.max_seconds_of({"presenter_max_seconds": 120}), 120.0)
        self.assertEqual(pipeline.max_seconds_of({"presenter_max_seconds": "90"}), 90.0)
        for bad in (0, -3, True, "lots", None, float("inf")):
            self.assertIsNone(pipeline.max_seconds_of({"presenter_max_seconds": bad}), bad)

        class Planned(Exception):
            pass
        seen = []

        def planner(*a, **kw):
            seen.append(kw.get("max_seconds"))
            raise Planned()
        with tempfile.TemporaryDirectory() as d:
            kit = kit_in(os.path.join(d, "kitsrc"))
            wav = make_wav(os.path.join(d, "voice.wav"), 76.0)
            segs, _total = segments_for()
            words = [{"text": w.text, "start": w.start, "end": w.end} for s in segs for w in s.words]
            for extra in ({}, {"presenter_max_seconds": 30}):
                work = os.path.join(d, f"work{len(seen)}")
                os.makedirs(work)
                with mock.patch.object(providers, "get", return_value=FakeProvider()), \
                        mock.patch.object(pipeline, "Store", lambda *a, **k: FakeStore()), \
                        mock.patch.object(pipeline.shotplan, "Planner", side_effect=planner), \
                        mock.patch.object(pipeline.estimate, "estimate", wraps=estimate.estimate) as est, \
                        mock.patch.dict(os.environ, {"PRESENTER_CACHE_DIR": os.path.join(d, "cache")}):
                    with self.assertRaises(Planned):
                        pipeline.plan(dict({"video_style": "ai_presenter", "presenter_kit": dict(kit), "audio_path": wav,
                                            "words": words, "title": "Potatoes"}, **extra), work, mock.MagicMock())
                self.assertEqual(est.call_args.kwargs.get("max_seconds"), seen[-1])
        self.assertEqual(seen, [None, 30.0])          # the plan and the estimate behind the budget both keep to it

    def test_a_presenter_span_runs_on_to_its_sentence_end(self):
        segs, total = segments_for(["Stop keeping your potatoes and onions in the same basket, I have watched good "
                                    "folks lose half their winter potatoes that way.", "Onions put off a gas."] +
                                   SENTENCES[2:])
        shots = shotplan.plan(segs, total, presenter_share=0.14, ai_video_share=0.1, framings=("m",))
        last_word = [w for w in shots[0].words][-1].text
        self.assertTrue(last_word.endswith("."), last_word)

    def test_plan_end_to_end_with_fakes(self):
        from src.presenter import pipeline
        with tempfile.TemporaryDirectory() as d:
            kit = kit_in(os.path.join(d, "kitsrc"))
            raw_kit = {k: v for k, v in kit.items()}
            wav = make_wav(os.path.join(d, "voice.wav"), 76.0)
            segs, total = segments_for()
            words = [{"text": w.text, "start": w.start, "end": w.end} for s in segs for w in s.words]
            work = os.path.join(d, "work")
            os.makedirs(work)
            report = mock.MagicMock()
            fake = FakeProvider()
            with mock.patch.object(providers, "get", return_value=fake), \
                    mock.patch.object(pipeline, "Store", lambda *a, **k: FakeStore()), \
                    mock.patch.dict(os.environ, {"PRESENTER_CACHE_DIR": os.path.join(d, "cache")}):
                doc = pipeline.plan({"video_style": "ai_presenter", "presenter_kit": raw_kit, "audio_path": wav,
                                     "words": words, "title": "Potatoes", "script": " ".join(SENTENCES),
                                     "presenter_budget_usd": 20}, work, report)
            timeline.validate(doc, require_media=True)
            meta = doc["meta"]
            self.assertEqual(meta["videoStyle"], "ai_presenter")
            p = meta["presenter"]
            self.assertEqual(p["tier"]["id"], "budget")
            self.assertEqual(p["empty"], 0)
            self.assertGreater(p["costs"]["presenterUsd"], 0)
            self.assertGreater(p["costs"]["imagesUsd"], 0)
            self.assertEqual(doc["scenes"][0]["media"]["source"], "ai-presenter")
            self.assertTrue(any(s.get("frame") == "split" for s in doc["scenes"]))
            self.assertIn("Altered or synthetic content", meta["warnings"][0])
            self.assertTrue(all(s["media"]["url"] and os.path.isfile(s["media"]["url"]) for s in doc["scenes"]))


# ------------------------------------------------------------------ style, costs, handler, renderer
class Wiring(unittest.TestCase):
    def test_the_style(self):
        inp = {"video_style": "AI presenter"}
        self.assertEqual(styles.apply(inp), "ai_presenter")
        self.assertIs(inp["allow_youtube"], False)
        self.assertFalse(inp["config"]["TREATMENTS"])
        self.assertLessEqual(inp["config"]["SHOT_MAX_SECONDS"], 12.0)
        own = {"video_style": "ai_presenter", "allow_youtube": True}
        styles.apply(own)
        self.assertIs(own["allow_youtube"], True)                     # the job's own choice wins
        for key in styles.STYLES["ai_presenter"]["config"]:
            self.assertIn(key, handler.CONFIG_OVERRIDABLE, key)

    def test_costs_carry_presenter_and_clip_money(self):
        costs.reset()
        costs.record("presenter.usd", 0.44)
        costs.record("presenter.avatar.usd", 0.44)
        costs.record("presenter.avatar.calls")
        costs.record("presenter.seconds", 8.8)
        costs.record("aivideo.usd", 0.3)
        costs.record("aivideo.seconds", 6)
        costs.record("image.usd", 0.05)
        s = costs.summary(1.0)
        self.assertAlmostEqual(s["presenter"], 0.44)
        self.assertAlmostEqual(s["aivideo"], 0.3)
        self.assertAlmostEqual(s["image"], 0.05)
        self.assertEqual(s["other"], 0.0)                              # seconds are counts, never priced
        self.assertGreaterEqual(s["total"], 0.79)
        self.assertEqual(s["breakdown"]["presenter"]["avatar"], {"usd": 0.44, "calls": 1})
        costs.reset()
        self.assertNotIn("presenter", costs.summary(1.0))               # other videos' costs keep their shape

    def test_presenter_info_action(self):
        out = handler.handler({"id": "t-info", "input": {"action": "presenter_info"}})
        self.assertTrue(out["ok"])
        self.assertEqual(out["defaultTier"], "budget")
        self.assertIn("20", out["estimate"]["tiers"]["standard"]["byMinutes"])
        self.assertEqual(out["script"]["wordsPerMinute"], 175)

    def test_footage_passes_skip_a_presenter_document(self):
        doc = {"meta": {"videoStyle": "ai_presenter"}, "scenes": []}
        with mock.patch.object(handler, "_no_repeats") as nr, mock.patch.object(handler, "_hook_check") as hc, \
                mock.patch.object(handler, "_keep_in_library") as kl:
            handler._after_plan(doc, "", None)
        nr.assert_not_called()
        hc.assert_not_called()
        kl.assert_not_called()

    def test_replace_clip_never_swaps_out_the_presenter(self):
        doc = {"fps": 30, "scenes": [{"id": "s0", "startFrame": 0, "durationInFrames": 150, "text": "hi",
                                      "media": {"type": "video", "url": "p.mp4", "source": "ai-presenter"}}]}
        with self.assertRaises(ValueError) as e:
            handler.do_resource({"timeline": doc, "scene_index": 0}, "", mock.MagicMock())
        self.assertIn("AI presenter", str(e.exception))

    def test_renderer_knows_the_split_frame_and_the_look(self):
        types, main, clip, look = (_read(f"remotion/src/{n}") for n in
                                   ("types.ts", "Main.tsx", "components/SceneClip.tsx", "components/FilmLook.tsx"))
        self.assertIn('"split"', types)
        self.assertIn("look?: { grain?: number; vignette?: number } | null", types)
        self.assertIn("<FilmLook look={props.look} />", main)
        self.assertIn('scene.frame === "split"', clip)
        self.assertNotIn("<Img", look)
        self.assertEqual(set(assemble.LOOK), {"grain", "vignette"})


if __name__ == "__main__":
    unittest.main()
