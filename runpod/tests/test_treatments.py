import os
import unittest
from unittest import mock

from src import config, templates, treatments, timeline
from src.transcribe import Segment


def seg(text, i, dur=6.0):
    return Segment(text=text, start=i * dur, end=(i + 1) * dur)


def scene(i, kind="video", dur=6.0, fps=30):
    return {"id": f"s{i}", "startFrame": int(i * dur * fps), "durationInFrames": int(dur * fps),
            "media": {"type": kind, "url": "x"}, "transition": "none", "motion": "none", "effect": "none"}


class Cues(unittest.TestCase):
    def test_numbers_places_quotes_questions_and_warnings_are_read_from_the_line(self):
        shot = {"subject": "Lake Mead"}
        c = treatments.cues_for(seg("Lake Mead is now at 26% capacity.", 0), shot, None)
        self.assertEqual(c[0]["cue"], "percent")
        self.assertEqual(c[0]["props"]["value"], 26.0)
        self.assertEqual(c[0]["props"]["text"], "CAPACITY")
        c = treatments.cues_for(seg("Water levels dropped 12 feet in a single summer.", 0), shot, None)
        # A fall in feet is a level on a ruler as well as a trend (change-length).
        self.assertEqual(c[0]["cue"], "change-length")
        self.assertEqual((c[0]["props"]["value"], c[0]["props"]["suffix"], c[0]["props"]["label"]), (12.0, "FT", "down"))
        c = treatments.cues_for(seg("In 2020 the lake stood at 40 percent; by 2026 it was 26 percent.", 0), shot, None)
        self.assertEqual(c[0]["cue"], "then-now")
        self.assertEqual([it["label"] for it in c[0]["props"]["items"]], ["2020", "2026"])
        c = treatments.cues_for(seg("“We are running out of options,” the manager said.", 0), shot, None)
        self.assertEqual(c[0]["cue"], "quote")
        self.assertEqual(c[0]["props"]["text"], "We are running out of options,")
        c = treatments.cues_for(seg("So what happens next?", 0), shot, None)
        self.assertEqual(c[0]["cue"], "question")
        c = treatments.cues_for(seg("Officials issued an evacuation warning for the canyon.", 0), shot, None)
        self.assertEqual(c[0]["cue"], "warning")
        c = treatments.cues_for(seg("It happened in September 2026.", 0), shot, None)
        self.assertEqual(c[0]["cue"], "date")
        self.assertEqual(c[0]["props"]["text"], "SEPTEMBER 2026")
        shot_route = {"subject": "Colorado River", "overlay": {"type": "map", "locations": [
            {"label": "Lake Powell", "lat": 37.0, "lon": -111.0}, {"label": "Lake Mead", "lat": 36.0, "lon": -114.0}]}}
        c = treatments.cues_for(seg("The water travels from Lake Powell to Lake Mead.", 0), shot_route, None)
        self.assertEqual(c[0]["cue"], "route")


class Planner(unittest.TestCase):
    def _plan(self, texts, shots=None, pack="documentary", kind="explainer", scene_kind="video"):
        segments = [seg(t, i) for i, t in enumerate(texts)]
        shots = shots or [{"subject": "Lake Mead"} for _ in texts]
        scenes = [scene(i, scene_kind) for i in range(len(texts))]
        brief = {"kind": kind, "sections": [{"from": 0, "to": len(texts) // 2}, {"from": len(texts) // 2 + 1, "to": len(texts) - 1}],
                 "hookBeats": [0]}
        return treatments.plan(segments, shots, scenes, 30, len(texts) * 180, brief,
                               treatments.pack_for(brief, pack), timeline._OVERLAY_SECONDS)

    def test_meaning_chooses_the_template_and_rhythm_keeps_them_apart(self):
        out = self._plan([
            "Lake Mead is now at 26% capacity.",                       # percent -> gauge
            "The white bathtub ring stands 150 feet tall.",            # number, but 6 s after: skipped
            "Boat ramps at Boulder Harbor end in dry gravel.",         # nothing
            "So what happens next?",                                   # question, 18 s later: allowed
            "Marinas have been dragged downhill again and again.",     # nothing
            "The lake has fallen 40 feet since 2020.",                 # change: allowed (high, 8.5 s after)
        ])
        ids = [o["template"] for o in out["overlays"]]
        self.assertEqual(ids[0], "NUM_PERCENT_V1")
        self.assertIn("TEXT_QUESTION_V1", ids)
        self.assertIn("NUM_TREND_V1", ids)
        self.assertNotIn("NUM_BIG_COUNTER_V1", ids)                    # crowded out by the gauge
        first = out["overlays"][0]
        self.assertEqual((first["type"], first["value"], first["suffix"], first["text"]), ("stat", 26.0, "%", "CAPACITY"))
        self.assertIn(first["motion"], templates.load()["entrances"])
        self.assertEqual(first["startFrame"], 0)
        # On the voice, not the whole scene: readable, never past the template's hold + slack.
        self.assertGreaterEqual(first["durationInFrames"], int(treatments.MIN_HOLD * 30))
        self.assertLessEqual(first["durationInFrames"], int((3.5 + treatments.HOLD_SLACK) * 30) + 1)
        vt = out["treatments"][0]
        self.assertEqual((vt["primaryType"], vt["secondaryType"], vt["template"]), ("footage", "numbers", "NUM_PERCENT_V1"))
        self.assertEqual(vt["data"]["value"], 26.0)
        self.assertEqual(vt["sfx"]["name"], "pop")
        self.assertEqual(vt["musicCue"], "INTRO")
        self.assertEqual(out["treatments"][2]["template"], None)
        c = out["counts"]
        self.assertEqual(c["data_graphics"], 2)
        self.assertEqual(c["text_treatments"], 1)
        self.assertEqual(c["footage_scenes"], 6)
        self.assertEqual(c["music_cues"], 2)

    def test_the_directors_map_and_chapter_hints_become_pack_templates(self):
        shots = [{"subject": "Lake Mead", "overlay": {"type": "chapter", "text": "The Bathtub Ring"}},
                 {"subject": "Nevada", "overlay": {"type": "map", "variant": "satellite-dark", "text": "Nevada",
                                                   "locations": [{"label": "Nevada", "lat": 38.0, "lon": -117.0}]}},
                 {"subject": "Lake Mead"}]
        out = self._plan(["A new chapter begins.", "It sits in Nevada.", "And so on."], shots, pack="weather", kind="weather")
        ids = [o["template"] for o in out["overlays"]]
        self.assertEqual(ids, ["HEADLINE_CHAPTER_GHOST_V1", "MAP_DISASTER_V1"])
        m = out["overlays"][1]
        self.assertEqual((m["type"], m["variant"], m["locations"][0]["label"]), ("map", "satellite-dark", "Nevada"))
        self.assertEqual(out["treatments"][1]["mapData"]["locations"][0]["label"], "Nevada")
        self.assertEqual(len(out["sfx"]), 1)                       # two sounds 6 s apart: the stronger wins
        self.assertEqual(out["sfx"][0]["name"], "impact")

    def test_a_long_quiet_stretch_gets_a_light_label(self):
        texts = ["Plain footage line one.", "Plain footage line two.", "Plain footage line three.",
                 "Plain footage line four.", "Plain footage line five.", "Plain footage line six.",
                 "Plain footage line seven.", "Now Hoover Dam comes into view."]
        shots = [{"subject": ""} for _ in texts[:-1]] + [{"subject": "Hoover Dam"}]
        out = self._plan(texts, shots)
        self.assertEqual([o["template"] for o in out["overlays"]], ["TEXT_KICKER_V1"])
        self.assertEqual(out["overlays"][0]["text"], "HOOVER DAM")

    def test_style_pack_follows_the_story_kind_and_the_request(self):
        self.assertEqual(treatments.pack_for({"kind": "weather"})["id"], "weather")
        self.assertEqual(treatments.pack_for({"kind": "biography"})["id"], "history")
        self.assertEqual(treatments.pack_for({"kind": "weather"}, "cinematic")["id"], "cinematic")
        self.assertEqual(treatments.pack_for({"kind": "weather"}, "nope")["id"], "weather")


class Registry(unittest.TestCase):
    def test_registry_is_consistent_and_covers_every_planner_type(self):
        from src import director
        self.assertEqual(templates.check(), [])
        comps = {t["component"] for t in templates.all_templates()}
        self.assertEqual(director.TEMPLATES - comps, set())
        self.assertGreaterEqual(len(templates.all_templates()), 60)
        # 18 built-in map looks, plus the vector maps of the animation library.
        self.assertEqual(len([t for t in templates.by_category("MAPS") if t["component"] != "motion"]), 18)

    def test_resolve_keeps_only_known_props_in_range(self):
        r = templates.resolve("MAP_ROUTE_DARK_V1", style="news", entrance="whip", exit_="scale",
                              props={"duration": 99, "scale": 3, "bogus": True, "sfx": "none"})
        self.assertEqual((r["type"], r["variant"], r["exit"]), ("map", "route-dark", "scale"))
        self.assertEqual(r["motion"], "fade")                 # whip is not an entrance: the default stands
        self.assertEqual(r["seconds"], 15.0)                  # clamped to the prop's max
        self.assertEqual(r["scale"], 1.6)
        self.assertEqual(r["sfx"]["name"], "none")
        self.assertNotIn("bogus", r)


class TimelineIntegration(unittest.TestCase):
    def test_build_carries_treatments_music_and_counts(self):
        from tests.test_pipeline import build_doc
        with mock.patch.object(config, "TREATMENTS", True):
            doc = build_doc(n=6, seconds=6.0, inp={"style_pack": "news"})
        self.assertIn("music", doc)
        self.assertIn("visualTreatment", doc["scenes"][0])
        self.assertIn("treatments", doc["meta"])
        self.assertEqual(doc["captions"]["style"], "news")
        self.assertEqual(doc["meta"]["stylePack"], "news")
        # Music: a bundled track by the story's kind when the job names none.
        with mock.patch.object(config, "TREATMENTS", True), mock.patch.object(config, "BGM_AUTO", True):
            doc = build_doc(n=3, seconds=6.0, inp={"style_pack": "weather", "brief": {"kind": "weather"}})
            self.assertEqual(doc["bgm"]["url"], "bgm://suspense-v2")
            self.assertEqual(doc["bgm"]["genre"], "suspense")
            doc = build_doc(n=3, seconds=6.0, inp={"style_pack": "history", "brief": {"kind": "history"},
                                                  "bgm_url": "https://x/track.mp3"})
            self.assertEqual(doc["bgm"]["url"], "https://x/track.mp3")
            doc = build_doc(n=3, seconds=6.0, inp={"style_pack": "history", "bgm": False})
            self.assertIsNone(doc["bgm"])

    def test_music_tracks_cover_the_narration_and_vary_between_projects(self):
        from src import timeline
        on = {"bgm": True}
        # A 22-minute narration gets the 30-minute investigative track, never the 20-minute one.
        got = timeline._bgm_for({**on, "project_id": "a"}, {"id": "x"}, {"kind": "history"}, 1320.0)
        self.assertEqual(got["url"], "bgm://investigative-v5")
        # Short videos spread over the owner's tracks by project.
        picks = {timeline._bgm_for({**on, "project_id": str(i)}, {"id": "x"}, {"kind": "history"}, 180.0)["track"]
                 for i in range(40)}
        self.assertEqual(picks, {"investigative-v5", "investigative-20m"})
        # A named track wins, including the old 12-minute beds existing projects use.
        got = timeline._bgm_for({**on, "bgm_track": "crime"}, {"id": "x"}, {"kind": "history"}, 60.0)
        self.assertEqual(got["url"], "bgm://crime")
        got = timeline._bgm_for({**on, "bgm_genre": "crime"}, {"id": "x"}, {}, 60.0)
        self.assertEqual(got["url"], "bgm://crime-v1")
        # The editor's music list sends a track name as the genre.
        got = timeline._bgm_for({**on, "bgm_genre": "investigative-20m"}, {"id": "x"}, {"kind": "news"}, 60.0)
        self.assertEqual((got["url"], got["genre"]), ("bgm://investigative-20m", "investigative"))
        # Every track the planner can name ships with the renderer.
        root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "remotion", "public", "bgm")
        for tracks in timeline.BGM_TRACKS.values():
            for name, _ in tracks:
                self.assertTrue(os.path.isfile(os.path.join(root, name + ".mp3")), name)


if __name__ == "__main__":
    unittest.main()
