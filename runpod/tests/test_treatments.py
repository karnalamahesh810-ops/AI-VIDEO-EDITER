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
        # 2026-09-29: every clear figure now gets its counting look (the 150 ft
        # measurement used to be crowded out), and the look comes out of the
        # rotation over every look for the cue, not the first in the registry.
        out = self._plan([
            "Lake Mead is now at 26% capacity.",                       # percent -> a percent look
            "The white bathtub ring stands 150 feet tall.",            # a clear figure: always shown
            "Boat ramps at Boulder Harbor end in dry gravel.",         # nothing
            "So what happens next?",                                   # question, 18 s later: allowed
            "Marinas have been dragged downhill again and again.",     # nothing
            "The lake has fallen 40 feet since 2020.",                 # change: allowed
        ])
        ovs = out["overlays"]
        cues = lambda o: templates.cues_of(templates.get(o["template"]))
        self.assertIn("percent", cues(ovs[0]))
        at = {o["startFrame"] // 180: o for o in ovs}
        self.assertIn("measurement", cues(at[1]))
        self.assertEqual(at[1]["value"], 150.0)
        self.assertNotIn(2, at)
        self.assertTrue({"question", "typewriter"} & set(cues(at[3])))
        self.assertTrue({"change", "change-length"} & set(cues(at[5])))
        first = ovs[0]
        self.assertEqual((first["value"], first["suffix"], first["text"]), (26.0, "%", "CAPACITY"))
        self.assertIn(first["motion"], templates.load()["entrances"])
        self.assertEqual(first["startFrame"], 0)
        # On the voice, not the whole scene: readable, never past the figure window.
        self.assertGreaterEqual(first["durationInFrames"], int(treatments.LAYOUT_WINDOWS["figure"][0] * 30))
        self.assertLessEqual(first["durationInFrames"], int(treatments.LAYOUT_WINDOWS["figure"][1] * 30) + 1)
        vt = out["treatments"][0]
        self.assertEqual((vt["primaryType"], vt["template"]), ("footage", first["template"]))
        self.assertEqual(vt["data"]["value"], 26.0)
        self.assertEqual(vt["musicCue"], "INTRO")
        self.assertEqual(out["treatments"][2]["template"], None)
        c = out["counts"]
        self.assertEqual(c["footage_scenes"], 6)
        self.assertEqual(c["music_cues"], 2)
        self.assertEqual(sum(c["by_category"].values()), 4)
        # Every sound is a file the renderer ships.
        self.assertTrue(all(s["name"] in templates.sfx_files() for s in out["sfx"]))
        # Nothing is ever the banned headline family.
        self.assertFalse([o for o in ovs if templates.banned(o["template"])])

    def test_the_directors_map_and_chapter_hints_become_pack_templates(self):
        # Beat 0 is a section start (brief sections from 0), so its short
        # chapter title keeps the pack's chapter card; the director's
        # satellite-dark map is honoured.
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
        # The sound pass (src/sfxplan.py, or the fallback) gives each graphic
        # at most one sound, in time order, from files that exist.
        self.assertTrue(out["sfx"])
        self.assertLessEqual(len(out["sfx"]), 2)
        self.assertEqual([s["startFrame"] for s in out["sfx"]], sorted(s["startFrame"] for s in out["sfx"]))
        self.assertTrue(all(s["name"] in templates.sfx_files() for s in out["sfx"]))

    def test_a_long_quiet_stretch_gets_a_light_label(self):
        # 2026-09-29: the label rotates over the caption / key-phrase looks and
        # shows the line's key phrase (a name the line says), not a fixed kicker.
        texts = ["Plain footage line one.", "Plain footage line two.", "Plain footage line three.",
                 "Plain footage line four.", "Plain footage line five.", "Plain footage line six.",
                 "Plain footage line seven.", "Now Hoover Dam comes into view."]
        shots = [{"subject": ""} for _ in texts[:-1]] + [{"subject": "Hoover Dam"}]
        segments = [seg(t, i) for i, t in enumerate(texts)]
        scenes = [scene(i) for i in range(len(texts))]
        brief = {"kind": "explainer", "sections": [], "hookBeats": []}
        out = treatments.plan(segments, shots, scenes, 30, len(texts) * 180, brief, treatments.pack_for(brief),
                              timeline._OVERLAY_SECONDS)
        self.assertEqual(len(out["overlays"]), 1)
        o = out["overlays"][0]
        self.assertTrue({"caption", "key-phrase"} & set(templates.cues_of(templates.get(o["template"]))), o["template"])
        self.assertEqual(o["text"].upper(), "HOOVER DAM")
        self.assertEqual(o["startFrame"], 7 * 180)
        self.assertNotEqual(o["template"], "TEXT_SENTENCE_HIGHLIGHT_V1")

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


class NewCues(unittest.TestCase):
    """The cue vocabulary of the 2026-09-29 looks pass: times, spelled-out figures, counts, people, text."""

    def cue(self, text, name, shot=None, brief=None):
        found = [c for c in treatments.cues_for(seg(text, 0), shot or {"subject": "Lake Mead"}, brief) if c["cue"] == name]
        return found[0] if found else None

    def test_times_of_day_and_date_with_time(self):
        self.assertEqual(treatments.time_in("The spillway opened at 3:45 pm.")[0], "3:45 PM")
        self.assertEqual(treatments.time_in("By 3 p.m. the road was gone.")[0], "3 PM")
        self.assertEqual(treatments.time_in("The call came at midnight.")[0], "12:00 AM")
        self.assertEqual(treatments.time_in("They left at dawn.")[0], "DAWN")
        self.assertEqual(treatments.time_in("It was seven o'clock that evening.")[0], "7:00 PM")
        self.assertIsNone(treatments.time_in("It was the afternoon of a long day with 5 amendments."))
        c = self.cue("At 3:45 pm on September 25, 2026, the dam released water.", "datetime")
        self.assertEqual(c["props"]["text"], "SEPTEMBER 25, 2026 · 3:45 PM")
        self.assertEqual((c["props"]["date"], c["props"]["time"]), ("SEPTEMBER 25, 2026", "3:45 PM"))
        self.assertEqual(self.cue("The call came in at noon.", "time-of-day")["props"]["text"], "12:00 PM")

    def test_more_ways_to_say_a_date(self):
        self.assertEqual(treatments.date_in("Sept. 25 was the deadline.")[0], "SEPTEMBER 25")
        self.assertEqual(treatments.date_in("Filed on 9/25/2026 in Phoenix.")[0], "SEPTEMBER 25, 2026")
        self.assertIsNone(treatments.date_in("Nothing can mar 5 years of work."))
        c = self.cue("On Monday, September 15, the gauge read low.", "date")
        self.assertEqual((c["props"]["text"], c["props"]["label"]), ("SEPTEMBER 15", "MONDAY"))

    def test_spelled_out_figures_and_counts(self):
        c = self.cue("The lake is at twenty-two percent of capacity.", "percent")
        self.assertEqual((c["props"]["value"], c["props"]["suffix"]), (22.0, "%"))
        c = self.cue("The basin lost three million acre-feet last year.", "big-number")
        self.assertEqual((c["props"]["value"], c["props"]["suffix"]), (3.0, "MILLION"))
        c = self.cue("Nearly three thousand homes were evacuated.", "count")
        self.assertEqual((c["props"]["value"], c["props"]["text"]), (3000.0, "HOMES EVACUATED"))
        c = self.cue("Roughly 12,000 people were displaced that week.", "count")
        self.assertEqual((c["props"]["value"], c["props"]["text"]), (12000.0, "PEOPLE DISPLACED"))
        self.assertIsNone(self.cue("There are a million reasons to worry.", "big-number"))

    def test_a_named_person_asks_for_a_full_screen_introduction(self):
        brief = {"cast": [{"name": "Brad Udall", "aliases": ["Udall"], "role": "Water researcher"}]}
        c = self.cue("Brad Udall has studied the river for decades.", "person-full", brief=brief)
        self.assertEqual((c["props"]["text"], c["props"]["subtitle"], c["props"]["label"]),
                         ("Brad Udall", "Water researcher", "WHO IS"))
        c = self.cue("She says the numbers do not add up.", "person-full",
                     shot={"subject": "Katie Hobbs", "subjectType": "person"})
        self.assertEqual((c["props"]["text"], c["props"]["subtitle"]), ("Katie Hobbs", ""))
        self.assertIsNone(self.cue("Lake Powell is shrinking.", "person-full",
                                   shot={"subject": "Lake Powell", "subjectType": "person"}))

    def test_text_cues(self):
        self.assertEqual(self.cue("The dam changed everything.", "headline")["props"]["text"], "The dam changed everything")
        self.assertEqual(self.cue("Now Hoover Dam comes into view.", "key-phrase", shot={})["props"]["text"], "Hoover Dam")
        self.assertEqual(self.cue("Now Hoover Dam comes into view.", "caption", shot={})["props"]["text"], "HOOVER DAM")
        self.assertIsNotNone(self.cue("Nobody was ready for what came next.", "typewriter"))
        self.assertEqual(self.cue("Engineers call it the dead pool line.", "term")["props"]["text"], "Dead Pool Line")
        self.assertIsNotNone(self.cue("It is the largest reservoir in the country by volume.", "fact"))
        self.assertIsNone(self.cue("It happened in 2020.", "headline"))


class LookHelpers(unittest.TestCase):
    def test_banned_looks_are_never_offered(self):
        for tid in templates.BANNED:
            t = templates.get(tid)
            if not t:
                continue
            for cue in templates.cues_of(t):
                self.assertNotIn(tid, [x["id"] for x in templates.for_cue(cue)])
            self.assertNotIn(tid, [x["id"] for x in templates.for_component(t["component"])])
            self.assertFalse(treatments.look_fits(tid, "anything"))

    def test_families_and_typing(self):
        self.assertEqual(templates.family(templates.get("TEXT_KICKER_V1")), "TEXT")
        self.assertEqual(templates.family(templates.get("LIB_QS_GIANT_MARKS")), "qs")
        self.assertEqual(templates.family(templates.get("PLACE_CARD_V1")), "PHOTO")
        self.assertTrue(templates.types(templates.get("TEXT_MEMO_V1")))
        self.assertTrue(templates.types(templates.get("TL_DATE_STAMP_V1")))
        self.assertFalse(templates.types(templates.get("TL_DATE_TITLE_V1")))
        # The typewriter cue only ever offers looks that really type.
        self.assertTrue(all(templates.types(t) for t in treatments._Planner(
            [], [], [], 30, 1, {}, treatments.pack_for({}), {})._pool("typewriter", "x", {})))

    def test_the_directors_map_variant_is_honoured_and_places_rotate_over_satellite_looks(self):
        pack = treatments.pack_for({"kind": "history"})
        one = {"type": "map", "locations": [{"label": "Nevada", "lat": 38.0, "lon": -117.0}]}
        ids, first = treatments._map_ids(dict(one, variant="satellite-tilt"), pack)
        self.assertEqual(first, "MAP_TILT_V1")
        ids, first = treatments._map_ids(one, pack)
        self.assertEqual(first, "")
        self.assertTrue(set(ids) <= set(treatments.SATELLITE_PLACE_MAPS) | {"MAP_PHOTO_PIN_V1"}, ids)
        # History mixes its paper map in, at most one map in four.
        self.assertIn(pack["map"], treatments._map_ids(one, pack, n_maps=3)[0])
        two = {"type": "map", "locations": one["locations"] * 2}
        self.assertEqual(treatments._map_ids(two, pack)[0], treatments.TWO_PLACE_MAPS)
        three = {"type": "map", "locations": one["locations"] * 3}
        self.assertEqual(treatments._map_ids(three, pack)[0], [pack["multi"]])
        self.assertIn("MAP_PHOTO_PIN_V1", treatments._map_ids(one, pack, still=True)[0])

    def test_turn_counters_start_from_zero_every_video(self):
        treatments._corner_turn[0] = 7
        treatments._ARCHIVE_COUNTS["TAG_SOURCE_V1"] = 9
        treatments._kind_turn["place"][0] = 5
        a = Planner("_plan")._plan(["Lake Mead is now at 26% capacity."])
        self.assertEqual(treatments._ARCHIVE_COUNTS, {})
        self.assertEqual(treatments._kind_turn["place"][0], 0)
        b = Planner("_plan")._plan(["Lake Mead is now at 26% capacity."])
        self.assertEqual(a["overlays"], b["overlays"])


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
