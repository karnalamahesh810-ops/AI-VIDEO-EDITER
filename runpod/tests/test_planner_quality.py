"""
The owner's review of the Texas flood video (news_compilation, 858 s, 2026-09-30):

  A. the sound was super low, a few sounds at full volume: every sound is set
     against the measured voice (typing ~10 dB under it, whooshes ~9, clicks
     and paper ~7, hits and dates ~5), under one cap, the editor's 100% included;
  B. a date drew a simple calendar: every date is BOLD TYPE on the deep hit, the
     countdown only for a real span of time, a time of day keeps its clock;
  C. numbers were labelled "GREG ABBOTT", "LOOK LIKE", and the Weather Prediction
     Center got a full-screen WHO IS card: labels are counted nouns, person cards
     are for people;
  D. music in every style, the whole video long, ducked under the voice;
  E. news never uses AI-generated pictures;
  and the follow-ups: a graphic starts on its word and leaves with its phrase,
  its sound follows it, one graphic at a time and none over a full-screen scene,
  a map only for a real place labelled as said.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from src import config, geocode, sfxplan, styles, templates, timeline, treatments
from src.media import MediaAsset
from src.transcribe import Segment, Word

FPS = 30
# Dates and times since 2026-10-01: the four VidRush looks only (the letter drop and
# the placed looks of pack A stay in the registry for the editor).
VR = set(treatments.VR_LOOKS)
OLD_DATES = treatments.OLD_DATE_LOOKS
NOT_A_DATE_LOOK = {"LIB_DT_CALENDAR_PAGE", "LIB_DT_REC_STAMP", "LIB_DT_COUNTDOWN_DAYS", "TL_DATE_STAMP_V1",
                   "LIB_DT_TIMELINE_TICK", "LIB_DT_STAMP_BAR"}
AT_16 = {5: 0.891, 6: 0.794, 7: 0.708, 9: 0.562, 10: 0.501}      # 10 ** ((-16 - dB + 20) / 20)


def spoken(text, start, pace=0.36):
    """A line with a word every `pace` seconds."""
    words, t = [], start
    for w in text.split():
        words.append(Word(text=w, start=round(t, 3), end=round(t + pace * 0.8, 3)))
        t += pace
    return Segment(text=text, start=start, end=round(t, 3), words=words)


def story(lines, pause=0.5, start=0.4, kinds=None):
    """(segments with word timings, one scene per line, total frames)."""
    segs, t = [], start
    for line in lines:
        s = spoken(line, t)
        segs.append(s)
        t = s.end + pause
    scenes = []
    for i, s in enumerate(segs):
        a = 0 if i == 0 else int(round(s.start * FPS))
        b = int(round(segs[i + 1].start * FPS)) if i + 1 < len(segs) else int(round((s.end + 1.0) * FPS))
        kind = (kinds or {}).get(i, "video")
        scenes.append({"id": f"s{i}", "startFrame": a, "durationInFrames": b - a,
                       "media": {"type": kind, "url": "" if kind == "animation" else f"https://x/{i}.mp4"},
                       "transition": "none", "motion": "none", "effect": "none"})
    return segs, scenes, scenes[-1]["startFrame"] + scenes[-1]["durationInFrames"]


def plan(lines, shots=None, brief=None, pack="news", density="rich", kinds=None, pause=0.5, **kw):
    segs, scenes, total = story(lines, pause=pause, kinds=kinds)
    shots = shots or [{"subject": "Texas Hill Country"} for _ in lines]
    brief = brief or {"kind": "news", "hookBeats": [], "sections": []}
    with mock.patch.object(config, "GRAPHICS_DENSITY", density):
        out = treatments.plan(segs, shots, scenes, FPS, total, brief, treatments.pack_for(brief, pack),
                              timeline._OVERLAY_SECONDS, **kw)
    return segs, scenes, out


def cues_of(o):
    return set(templates.cues_of(templates.get(o["template"]) or {}))


def span(o):
    return o["startFrame"], o["startFrame"] + o["durationInFrames"]


def sound_end(s):
    return s["startFrame"] + s["durationFrames"] - s.get("trimFrames", 0)


FLOOD = ["On Wednesday, July 2, heavy rain began to fall over the Texas Hill Country.",
         "The Weather Prediction Center warned of flash flooding across the region.",
         "Governor Greg Abbott said 4,000 people look like they will need shelter.",
         "By Friday the Guadalupe River had risen 26 feet in just 45 minutes.",
         "Three days later, crews were still searching the riverbanks.",
         "At least 27 deaths were reported in Kerr County alone.",
         "The storm dumped 12 inches of rain on some towns.",
         "About 40 percent of people in the county lost power.",
         "The death toll rose to 104 by the weekend.",
         "Over the next 48 hours, more storms are expected.",
         "Plain words about the recovery effort continue here.",
         "On Saturday, July 5, the river finally began to fall."]
FLOOD_BRIEF = {"kind": "news", "hookBeats": [0], "sections": [],
               "people": ["Greg Abbott", "Weather Prediction Center"],
               "cast": [{"name": "Weather Prediction Center", "role": "Forecasters", "aliases": []},
                        {"name": "Greg Abbott", "role": "Governor of Texas", "aliases": ["Abbott"]}],
               "places": ["Kerr County, Texas", "Guadalupe River"]}


def flood_shots():
    shots = [{"subject": "Texas Hill Country"} for _ in FLOOD]
    shots[1] = {"subject": "Weather Prediction Center", "subjectType": "person"}
    shots[2] = {"subject": "Greg Abbott", "subjectType": "person"}
    return shots


# --------------------------------------------------------------------------- A. sound levels
class SoundLevels(unittest.TestCase):
    def test_every_kind_of_sound_sits_under_the_voice(self):
        # Against a -16 LUFS voice. The owner, 2026-10-01: no sound is ever louder than the narration -
        # its loudest moment 6 dB under the voice at most, a glitch 9.
        self.assertEqual(round(sfxplan.level("keys-type", -16.0), 3), AT_16[10])     # typing ~10 dB under
        self.assertEqual(round(sfxplan.level("whoosh-soft", -16.0), 3), AT_16[9])    # soft whooshes ~9
        self.assertEqual(round(sfxplan.level("click", -16.0), 3), AT_16[7])          # ui ~7
        self.assertEqual(round(sfxplan.level("paper", -16.0), 3), AT_16[7])          # paper ~7
        self.assertEqual(round(sfxplan.level("hit-deep", -16.0), 3), AT_16[6])       # impacts ~6
        # A glitch 9 dB under, counted from its own measured loudness (glitch-pro is 0.4 dB hot).
        self.assertAlmostEqual(sfxplan.peak_under_voice("glitch-pro", sfxplan.level("glitch-pro", -16.0), -16.0), 9.0,
                               places=6)
        # The ceiling, the hits' level: nothing is ever louder than 6 dB under the voice.
        self.assertEqual(round(sfxplan.cap(-16.0), 3), AT_16[6])
        for name in templates.sfx_files():
            self.assertLessEqual(sfxplan.level(name), sfxplan.cap(None, name) + 1e-9, name)
            self.assertGreaterEqual(sfxplan.peak_under_voice(name, sfxplan.level(name)), 6.0 - 1e-6, name)

    def test_a_quiet_narration_takes_the_sounds_down_with_it(self):
        self.assertAlmostEqual(sfxplan.cap(-20.0), 10 ** (-6 / 20), places=4)
        self.assertAlmostEqual(sfxplan.level("hit-deep", -20.0) / sfxplan.level("hit-deep", -16.0), 10 ** (-4 / 20),
                               places=4)
        # A very loud one never asks the renderer for more than 1.0.
        self.assertEqual(sfxplan.cap(-6.0), 1.0)

    def test_a_whole_plan_is_under_the_cap_and_no_longer_a_whisper(self):
        doc = build_doc(FLOOD, inp={"voice_lufs": -20.0})
        self.assertEqual((doc["meta"]["voiceLufs"], doc["meta"]["voiceLufsSource"]), (-20.0, "given"))
        top = round(sfxplan.cap(-20.0), 3)
        # Every look plays its own sound (doc.lookSounds, LookSounds.tsx): the
        # rows are the transitions' only, and nothing is above the one cap.
        self.assertIn("lookSounds", doc)
        self.assertFalse([s for s in doc["sfx"] if s.get("kind") == "overlay"])
        for s in doc["sfx"]:
            self.assertLessEqual(s["volume"], top, s)
        sounds = sfxplan.doc_look_sounds(doc)
        self.assertTrue(sounds)
        for s in sounds:
            self.assertLessEqual(s["volume"], sfxplan.cap(-20.0) + 1e-4, s)
        # Each look's loudest moment is no whisper (the old plan played 0.07-0.135).
        for look in {s["look"] for s in sounds}:
            self.assertGreaterEqual(max(s["volume"] for s in sounds if s["look"] == look), 0.2, look)
        # No punch anywhere, and a date or a number only ever ticks (the owner, 2026-10-01).
        self.assertFalse([s for s in sounds if s["name"] in ("date-slam", "impact-punch")])
        texty = {i for i, o in enumerate(doc["overlays"])
                 if o.get("template") in (treatments.TEXT_DATE_LOOK, treatments.BOLD_COUNT_LOOK)}
        self.assertTrue(texty)
        for s in sounds:
            if s["look"] in texty:
                self.assertEqual(sfxplan.category(s["name"]), "tick", s)

    def test_the_editors_full_volume_comes_back_under_the_cap(self):
        doc = build_doc(FLOOD[:3], inp={"voice_lufs": -20.0})
        doc["sfx"] = [{"name": "hit-deep", "startFrame": 30, "volume": 1.0},
                      {"name": "whoosh", "startFrame": 200, "volume": 0.2},
                      {"name": "pop", "startFrame": 260, "volume": True}]
        timeline.validate(doc, require_media=False)
        self.assertEqual(doc["sfx"][0]["volume"], round(sfxplan.cap(-20.0), 3))
        self.assertEqual(doc["sfx"][1]["volume"], 0.2)                        # a quieter choice stands
        self.assertIs(doc["sfx"][2]["volume"], True)                          # not a number: left alone
        # A master above 1 lowers the ceiling to match (the renderer multiplies it in).
        doc["sfx"] = [{"name": "hit-deep", "startFrame": 30, "volume": 1.0}]
        doc["sfxVolume"] = 2.0
        timeline.cap_sfx_levels(doc)
        self.assertAlmostEqual(doc["sfx"][0]["volume"] * 2.0, sfxplan.cap(-20.0), places=2)

    def test_the_fallback_sound_pass_is_held_to_the_same_levels(self):
        t = next(t for t in templates.all_templates() if (t["defaults"].get("sfx") or {}).get("name") == "impact")
        out = treatments._plan_sfx([{"template": t["id"], "startFrame": 0, "durationInFrames": 90}], [], FPS, 3.0)
        self.assertEqual(out[0]["volume"], round(sfxplan.cap(), 3))


@unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
class VoiceMeasurement(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def tone(self, path, db):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anoisesrc=d=4:c=pink:a=0.5",
                        "-af", f"volume={db}dB", "-f", "wav", path], check=True)
        return path

    def test_the_narration_is_measured_once_from_the_handlers_copy(self):
        job = "job-voice-1"
        self.tone(os.path.join(self.dir, job, "narration.mp3"), -10)         # the name the handler downloads to
        with mock.patch.object(config, "WORK_DIR", self.dir):
            lufs, how = timeline.voice_loudness("https://signed.example/narration.mp3", {"_job_id": job})
        self.assertEqual(how, "measured")
        self.assertTrue(-40 < lufs < -5, lufs)
        # 6 dB quieter measures 6 dB quieter.
        quieter = timeline.measure_lufs(self.tone(os.path.join(self.dir, "q.wav"), -16))
        self.assertAlmostEqual(lufs - quieter, 6.0, delta=0.6)

    def test_a_signed_url_alone_is_never_downloaded_again(self):
        lufs, how = timeline.voice_loudness("https://signed.example/narration.mp3", {"_job_id": "../etc"})
        self.assertEqual((lufs, how), (sfxplan.VOICE_LUFS_DEFAULT, "assumed"))
        self.assertEqual(timeline.narration_file("https://x/a.mp3", {"audio_path": "https://y/b.mp3"}), "")
        self.assertIsNone(timeline.measure_lufs(os.path.join(self.dir, "missing.mp3")))

    def test_build_measures_a_local_narration(self):
        path = self.tone(os.path.join(self.dir, "narration.mp3"), -12)
        doc = build_doc(FLOOD[:4], audio_url="https://signed.example/n.mp3", narration_path=path)
        self.assertEqual(doc["meta"]["voiceLufsSource"], "measured")
        self.assertAlmostEqual(doc["meta"]["voiceLufs"], timeline.measure_lufs(path), places=1)


def build_doc(lines, inp=None, audio_url="https://signed.example/narration.mp3", **kw):
    segs, _scenes, total = story(lines)
    shots = flood_shots()[:len(lines)] if len(lines) <= len(FLOOD) else [{"subject": "x"} for _ in lines]
    assets = [MediaAsset(kind="video", source="youtube", url=f"https://x/{i}.mp4", local_path="")
              for i in range(len(lines))]
    job = {"style_pack": "news", "brief": dict(FLOOD_BRIEF), **(inp or {})}
    with mock.patch.object(config, "TREATMENTS", True):
        return timeline.build(segs, shots, assets, audio_url=audio_url, audio_duration=total / FPS, inp=job, **kw)


# --------------------------------------------------------------------------- A2. the sound follows its look
class SoundFollowsTheLook(unittest.TestCase):
    def test_every_graphic_sound_starts_with_its_look_and_is_over_when_it_leaves(self):
        _segs, _scenes, out = plan(FLOOD, flood_shots(), FLOOD_BRIEF)
        # The sound is built into each look (LookSounds.tsx): no row on the timeline.
        self.assertEqual(out["sfx"], [])
        doc = {"fps": FPS, "overlays": out["overlays"], "lookSounds": out["lookSounds"]}
        sounds = sfxplan.doc_look_sounds(doc)
        self.assertTrue(sounds)
        for s in sounds:
            a, b = span(out["overlays"][s["look"]])
            self.assertTrue(a <= s["startFrame"] < b, s)
            self.assertLessEqual(s["startFrame"] + s["frames"], b, s)
        # Two looks landing within half a second: only one of them sounds.
        heard = sorted({span(out["overlays"][s["look"]])[0] for s in sounds})
        self.assertTrue(all(y - x > 15 for x, y in zip(heard, heard[1:])), heard)


# --------------------------------------------------------------------------- B. dates
class Dates(unittest.TestCase):
    """The owner, 2026-10-01, after four VidRush exports: one date or time graphic every two to three minutes,
    each look in its one place, one theme per video, nothing the narration did not say."""

    def test_a_date_takes_a_vidrush_look_and_never_the_old_rotation(self):
        lines = ["On Wednesday, July 2, the rain began.", "Plain words about the river.",
                 "By September 15, 2026, the lake had dropped.", "Plain words about the town.",
                 "At 3:45 pm on July 4, the gates opened.", "Plain words about the dam.",
                 "Sept. 25 was the deadline.", "Plain words about the crews.",
                 "In October 2025 the lake hit a new low."]
        _s, _sc, out = plan(lines, pack="documentary", brief={"kind": "explainer", "hookBeats": [], "sections": []})
        used = [o["template"] for o in out["overlays"]]
        self.assertFalse(set(used) & OLD_DATES, used)
        self.assertFalse([t for t in used if t.startswith("LIB_DTX_") or t in NOT_A_DATE_LOOK], used)
        # Five dates said within half a minute: one graphic, the first date (the story's start), centred.
        dated = [o for o in out["overlays"] if o["template"] in VR]
        self.assertEqual([(o["template"], o["text"], o.get("subtitle")) for o in dated],
                         [(treatments.VR_HERO, "JULY 2", "")], used)
        self.assertNotIn("WEDNESDAY", str(dated))                 # the weekday is not part of the date look

    def test_a_directors_date_stamp_shows_nothing_the_line_did_not_say(self):
        shots = [{"subject": "Texas", "overlay": {"type": "date-stamp", "text": "Wednesday"}},
                 {"subject": "Texas"}]
        _s, _sc, out = plan(["That was when the water started to rise.", "Plain words follow here."], shots)
        self.assertFalse([o for o in out["overlays"] if o["template"] in VR or o["template"] in OLD_DATES], out)
        # A calendar look asked for by name, a date the line never says: nothing either.
        shots[0]["overlay"] = {"type": "motion", "variant": "dt-calendar-page", "text": "July 2"}
        _s, _sc, out = plan(["That was when the water started to rise.", "Plain words follow here."], shots)
        self.assertEqual(out["overlays"], [])

    def test_a_span_of_time_or_a_relative_time_gets_no_graphic(self):
        self.assertEqual(treatments.time_span_in("Three days later, crews returned.")[0], "3 DAYS LATER")
        self.assertEqual(treatments.time_span_in("Over the next 48 hours, more rain.")[0], "48 HOURS")
        self.assertEqual(treatments.time_span_in("It rained for forty-eight hours.")[0], "48 HOURS")
        self.assertEqual(treatments.time_span_in("A day later it was over.")[0], "1 DAY LATER")
        for plain in ("On Wednesday it rained.", "On July 2 it rained.", "It rained for days.", "At 3 pm it rained."):
            self.assertIsNone(treatments.time_span_in(plain), plain)
        _s, _sc, out = plan(["Three days later, crews were still searching the riverbanks.",
                             "Plain words about the recovery.", "Last night the river crested.",
                             "Over the next 48 hours, more storms are expected.", "This week the town waits.",
                             "From July 2 to July 5 the rain never stopped.", "On Friday the water rose.",
                             "They left the marina at dawn.", "The meeting ran past midnight."])
        shown = [(o["template"], o.get("text"), o.get("value")) for o in out["overlays"]]
        self.assertFalse([s for s in shown if s[0] in VR or s[0] in OLD_DATES or s[0] == treatments.BOLD_COUNT_LOOK
                          or s[2] in (3.0, 48.0)], shown)
        self.assertNotIn(treatments.COUNTDOWN_LOOK, [t["id"] for t in treatments.date_looks("date")])
        self.assertNotIn(treatments.COUNTDOWN_LOOK, [t["id"] for t in treatments.date_looks("datetime")])

    def test_a_clock_time_is_the_time_card(self):
        _s, _sc, out = plan(["The call came in at 3:45 pm.", "Plain words follow here."])
        [o] = [o for o in out["overlays"] if o["template"] in VR]
        self.assertEqual((o["template"], o["text"], o["subtitle"]), (treatments.VR_TIME, "3:45 PM", ""))
        self.assertEqual(o["theme"], "serif")                     # a news story: the gold serif theme

    def test_dates_never_punch(self):
        lines = ["On July 2, the rain began.", "Plain words about the river.", "Plain words about the town.",
                 "By September 15, 2026, the lake had dropped.", "Plain words about the dam.",
                 "Plain words about the crews.", "Sept. 25 was the deadline."]
        _s, _sc, out = plan(lines, pack="documentary", brief={"kind": "explainer", "hookBeats": [], "sections": []})
        dated = [o for o in out["overlays"] if o["template"] in VR]
        self.assertEqual(len(dated), 1)
        # The sound is the look's own, under the voice; never a punch (the owner, 2026-10-01).
        self.assertEqual(out["sfx"], [])
        sounds = sfxplan.doc_look_sounds({"fps": FPS, "overlays": out["overlays"], "lookSounds": out["lookSounds"]})
        for o in dated:
            mine = [s for s in sounds if out["overlays"][s["look"]] is o]
            self.assertFalse([s for s in mine if s["name"] in ("hit-deep", "date-slam", "impact-punch")], mine)

    def test_the_registry_still_offers_the_old_date_looks_for_the_editor(self):
        # Bold text only: the letter drop for a date, a date and a time, a time of day.
        for cue in ("date", "datetime", "time-of-day"):
            self.assertEqual([t["id"] for t in treatments.date_looks(cue)], [treatments.TEXT_DATE_LOOK], cue)
        # A registry without it falls back to the bold type looks left (the boxed
        # and banded date cards are banned: the 2026-09-30 audit); never a banned look.
        real = templates.get
        hidden = {treatments.TEXT_DATE_LOOK}
        with mock.patch.object(templates, "get", lambda tid: None if tid in hidden else real(tid)):
            for cue in ("date", "datetime"):
                self.assertEqual([t["id"] for t in treatments.date_looks(cue)],
                                 ["LIB_DT_BOLD_HEADLINE", "LIB_DT_BIG_STACK"], cue)
            for cue in ("date", "datetime", "time-of-day"):
                self.assertFalse([t["id"] for t in treatments.date_looks(cue) if templates.banned(t["id"])], cue)


# --------------------------------------------------------------------------- C. labels and person cards
class Labels(unittest.TestCase):
    def cue(self, text, name, shot=None, brief=None):
        seg = Segment(text=text, start=0.0, end=6.0)
        got = [c for c in treatments.cues_for(seg, shot or {"subject": "Texas Hill Country"}, brief)
               if c["cue"] == name]
        return got[0]["props"] if got else None

    def test_a_number_is_labelled_by_what_it_counts_never_a_person_or_a_verb(self):
        abbott = {"subject": "Greg Abbott", "subjectType": "person"}
        p = self.cue("Governor Greg Abbott said 4,000 people look like they will need shelter.", "count",
                     abbott, FLOOD_BRIEF)
        self.assertEqual(p["text"], "PEOPLE")
        p = self.cue("Greg Abbott said 26 percent look like they are gone.", "percent", abbott, FLOOD_BRIEF)
        self.assertNotIn(p["text"], ("LOOK LIKE", "LOOK", "GREG ABBOTT"))
        self.assertEqual(p["text"], "")
        p = self.cue("Abbott warned 12,000 Texans could lose power.", "count", abbott, FLOOD_BRIEF)
        self.assertIsNone(p)                       # "Texans" is no unit: nothing to count - no label either
        p = self.cue("That 4 million Greg Abbott mentioned was spent.", "big-number", abbott, FLOOD_BRIEF)
        self.assertNotIn("ABBOTT", p["text"])

    def test_labels_read_the_counted_noun_or_the_phrase_it_completes(self):
        self.assertEqual(self.cue("The death toll rose to 104 by the weekend.", "change")["text"], "DEATH TOLL")
        self.assertEqual(self.cue("Water levels dropped 12 feet overnight.", "change-length")["text"], "WATER LEVELS")
        self.assertEqual(self.cue("Roughly 12,000 people were displaced that week.", "count")["text"],
                         "PEOPLE DISPLACED")
        self.assertEqual(self.cue("At least 27 people died in the flood.", "count")["text"], "PEOPLE DIED")
        self.assertEqual(self.cue("Lake Mead is now at 26% capacity.", "percent")["text"], "CAPACITY")
        self.assertEqual(self.cue("The storm dumped 12 inches of rain.", "measurement")["text"], "RAIN")
        self.assertEqual(self.cue("A death toll of 27 was confirmed.", "big-number"), None)
        # No noun anywhere and no subject the line names: no label at all.
        self.assertEqual(self.cue("Officials counted 41 percent.", "percent")["text"], "")

    def test_a_chart_title_is_never_a_person(self):
        p = self.cue("In 2020 turnout was 40 percent; by 2026 it was 26 percent.", "then-now",
                     {"subject": "Katie Hobbs", "subjectType": "person"}, {"cast": [{"name": "Katie Hobbs"}]})
        self.assertEqual(p["text"], "")
        p = self.cue("In 2020 the lake was 40 percent full; by 2026 it was 26 percent.", "then-now",
                     {"subject": "Lake Mead"})
        self.assertEqual(p["text"], "LAKE MEAD")


class PersonCards(unittest.TestCase):
    def cue(self, text, shot=None, brief=None):
        seg = Segment(text=text, start=0.0, end=6.0)
        return [c for c in treatments.cues_for(seg, shot or {}, brief) if c["cue"] == "person-full"]

    def test_organisations_agencies_and_places_never_get_a_who_is_card(self):
        brief = {"cast": [{"name": "Weather Prediction Center", "role": "Forecasters", "aliases": ["forecasters"]},
                          {"name": "National Weather Service", "role": "", "aliases": []}],
                 "people": ["Kerr County Sheriff's Office", "Texas Division of Emergency Management"]}
        for line in ("The Weather Prediction Center warned of flash flooding.",
                     "The forecasters warned of flash flooding.",
                     "The National Weather Service issued a warning.",
                     "Kerr County Sheriff's Office asked people to stay home.",
                     "Texas Division of Emergency Management opened shelters."):
            self.assertEqual(self.cue(line, brief=brief), [], line)
        self.assertEqual(self.cue("They warned of flash flooding.",
                                  {"subject": "Weather Prediction Center", "subjectType": "person"}), [])
        self.assertEqual(self.cue("It sits in the valley.", {"subject": "Guadalupe River", "subjectType": "person"}),
                         [])

    def test_a_real_person_still_does_and_an_unnamed_one_does_not(self):
        [c] = self.cue("Greg Abbott declared a disaster.", brief=FLOOD_BRIEF)
        self.assertEqual((c["props"]["text"], c["props"]["subtitle"]), ("Greg Abbott", "Governor of Texas"))
        self.assertEqual(self.cue("The boy was never found.", brief={"cast": [{"name": "", "aliases": ["the boy"]}]}),
                         [])

    def test_what_is_an_organisation_or_a_place(self):
        for name in ("Weather Prediction Center", "National Weather Service", "Kerr County", "Guadalupe River",
                     "FEMA", "Texas A&M University", "Camp Mystic", "Harris County Flood Control District"):
            self.assertTrue(treatments._is_org_or_place(name), name)
        for name in ("Greg Abbott", "Katie Hobbs", "Brad Udall", "Kevin Park", "Pat Mulroy"):
            self.assertFalse(treatments._is_org_or_place(name), name)

    def test_the_flood_plan_introduces_the_governor_only(self):
        _s, _sc, out = plan(FLOOD, flood_shots(), FLOOD_BRIEF)
        intros = [o for o in out["overlays"] if "person-full" in cues_of(o)]
        self.assertEqual([o["text"] for o in intros], ["Greg Abbott"])


# --------------------------------------------------------------------------- D. music
class Music(unittest.TestCase):
    def test_news_styles_keep_their_music(self):
        for style in ("news_compilation", "trending_news"):
            inp = {"video_style": style}
            styles.apply(inp)
            self.assertNotIn("bgm", inp, style)
            self.assertFalse(any("bgm" in spec for spec in styles.STYLES.values()))
        inp = {"video_style": "news_compilation"}
        styles.apply(inp)
        doc = build_doc(FLOOD[:4], inp={k: v for k, v in inp.items() if k != "config"})
        self.assertEqual(doc["bgm"]["genre"], "suspense")
        self.assertTrue(doc["bgm"]["loop"])
        # A job that turns music off still can.
        self.assertIsNone(build_doc(FLOOD[:2], inp={"bgm": False})["bgm"])

    def test_the_track_covers_the_whole_video(self):
        for seconds in (60.0, 858.0, 1500.0):
            got = timeline._bgm_for({"bgm": True, "project_id": "p"}, None, {"kind": "news"}, seconds)
            self.assertGreaterEqual(got["trackSeconds"], seconds, got)
        longer = timeline._bgm_for({"bgm": True}, None, {"kind": "news"}, 2400.0)
        self.assertLess(longer["trackSeconds"], 2400.0)
        self.assertTrue(longer["loop"])                  # Main.tsx loops it to the end
        # Every track the planner names has a measured level.
        for tracks in timeline.BGM_TRACKS.values():
            for name, _n in tracks:
                self.assertIn(name, timeline.BGM_LUFS)

    def test_the_track_follows_the_storys_mood(self):
        pick = lambda brief, text="", **inp: timeline._bgm_for({"bgm": True, **inp}, None, brief, 300.0, text)["genre"]
        self.assertEqual(pick({"kind": "weather"}), "suspense")
        self.assertEqual(pick({"kind": "history"}), "investigative")
        self.assertEqual(pick({"kind": "news"}, "Police arrested two suspects after the murder; the trial "
                                                "starts in May."), "crime")
        self.assertEqual(pick({"kind": "news"}, bgm_genre="documentary"), "investigative")
        self.assertEqual(pick({"kind": "news"}, bgm_genre="true-crime"), "crime")

    def test_the_music_is_ducked_under_the_voice_and_fades_in_and_out(self):
        segs = [spoken("The water kept rising through the night.", 0.4),
                spoken("Crews worked until dawn.", 3.9),               # a 0.6 s pause before it: no rise
                spoken("Then the rain stopped.", 7.3)]                  # a 2.5 s pause before it: a rise
        total = int(round((segs[-1].end + 4.0) * FPS))
        bgm = {"track": "suspense-v2"}
        m = timeline.music_automation({"sections": []}, bgm, segs, FPS, total, voice_lufs=-24.0)
        s = m["sections"]
        self.assertEqual(m["duck"], 1.0)
        self.assertEqual((s[0]["startFrame"], s[0]["volume"]), (0, 0.0))            # silence at frame 0 ...
        self.assertEqual(s[1]["startFrame"], 1)                                     # ... up over 1.5 s
        speech = 10 ** ((-24.0 - 18.0 - timeline.BGM_LUFS["suspense-v2"]) / 20)     # 18 dB under the voice
        self.assertAlmostEqual(s[1]["volume"], speech, places=3)
        rises = [x for x in s if x["kind"] == "pause"]
        self.assertEqual(len(rises), 2)                                             # the 2.5 s pause and the end
        first = rises[0]
        self.assertAlmostEqual(first["volume"], speech * 10 ** (3 / 20), places=3)
        self.assertGreaterEqual(first["startFrame"], int(segs[1].end * FPS))
        back = next(x for x in s if x["startFrame"] > first["startFrame"])
        self.assertEqual(back["kind"], "voice")
        self.assertLessEqual(back["startFrame"], int((segs[2].start - 1.0) * FPS))  # down again for the next word
        self.assertFalse([x for x in rises if int(segs[0].end * FPS) < x["startFrame"] < int(segs[1].start * FPS)])
        # Out over the last 3 s: half way at total - 3 s, silent at total - 1.5 s (+1.5 s ramp).
        self.assertEqual([(x["startFrame"], x["kind"]) for x in s[-2:]],
                         [(total - 90, "fade-out"), (total - 45, "fade-out")])
        self.assertEqual(s[-1]["volume"], 0.0)
        self.assertTrue(all(0.0 <= x["volume"] <= 1.0 for x in s))
        self.assertEqual([x["startFrame"] for x in s], sorted(x["startFrame"] for x in s))

    def test_a_loud_track_of_the_jobs_own_sits_18_db_under_the_voice(self):
        segs = [spoken("The water kept rising through the night.", 0.4)]
        m = timeline.music_automation({"sections": []}, {"url": "https://x/own.mp3"}, segs, FPS, 300, -16.0)
        self.assertAlmostEqual(m["sections"][1]["volume"], 10 ** ((-16.0 - 18.0 + 14.0) / 20), places=3)
        # A job's own bgm_volume trims it: 0.12 is the automatic level, 0.24 twice as loud (+6 dB).
        auto = 10 ** ((-16.0 - 18.0 + 14.0) / 20)
        for asked, want in ((0.12, auto), (0.24, 2 * auto), (0.0, 0.0)):
            m = timeline.music_automation({"sections": []}, {"url": "https://x/own.mp3"}, segs, FPS, 300, -16.0,
                                          level=asked)
            self.assertAlmostEqual(m["sections"][1]["volume"], want, places=3)

    def test_build_writes_the_automation(self):
        doc = build_doc(FLOOD[:5], inp={"voice_lufs": -18.0})
        m = doc["music"]
        self.assertEqual(m["duck"], 1.0)
        self.assertEqual(m["sections"][0]["volume"], 0.0)
        self.assertEqual(m["levels"]["voiceLufs"], -18.0)
        self.assertEqual(doc["bgm"]["volume"], m["levels"]["speech"])


# --------------------------------------------------------------------------- E. styles
class NewsStyles(unittest.TestCase):
    def test_news_never_uses_generated_pictures(self):
        for style in ("news_compilation", "trending_news"):
            cfg = styles.STYLES[style]["config"]
            self.assertEqual((cfg["IMAGE_MAX_PER_VIDEO"], cfg["PREFER_GENERATED_IMAGES"]), (0, False), style)
            inp = {"video_style": style, "config": {"IMAGE_MAX_PER_VIDEO": 3}}
            styles.apply(inp)
            self.assertEqual(inp["config"]["IMAGE_MAX_PER_VIDEO"], 3)        # the job's own override wins
            self.assertIs(inp["config"]["PREFER_GENERATED_IMAGES"], False)


# --------------------------------------------------------------------------- timing
class Timing(unittest.TestCase):
    def test_a_graphic_starts_on_its_word_and_leaves_with_its_phrase(self):
        lines = ["After a long and very difficult night the lake stood at 26 percent of capacity.",
                 "Plain words about the town follow here.", "More plain words about the river here.",
                 "Plain words about the crews at work tonight.",
                 "By then the whole county had lost roughly 12,000 homes."]
        segs, _sc, out = plan(lines, pack="documentary", brief={"kind": "explainer", "hookBeats": [], "sections": []},
                              pause=0.6)
        figures = [o for o in out["overlays"] if o.get("value") in (26.0, 12000.0)]
        self.assertEqual(len(figures), 2, [o["template"] for o in out["overlays"]])
        for o in figures:
            seg = next(s for s in segs if s.start * FPS - 1 <= o["startFrame"] <= s.end * FPS)
            word = next(w for w in seg.words if w.text.replace(",", "").startswith(str(int(o["value"]))))
            # On the word: at most 2 frames early, never late.
            self.assertTrue(word.start * FPS - 2.5 <= o["startFrame"] <= word.start * FPS + 0.5,
                            (o["startFrame"], word.start * FPS))
            t = templates.get(o["template"])
            lo, hi = treatments.layout_window(t, "figure")
            end = (o["startFrame"] + o["durationInFrames"]) / FPS
            # Leaves with its phrase (+0.4 s), unless its own animation needs longer.
            self.assertLessEqual(end, max(seg.end + treatments.TAIL, o["startFrame"] / FPS + lo) + 1 / FPS)
            self.assertLessEqual(o["durationInFrames"] / FPS, hi + 1e-6)

    def test_windows_by_kind_and_never_shorter_than_the_looks_own_animation(self):
        self.assertEqual(treatments.LAYOUT_WINDOWS["figure"], (2.0, 4.0))
        self.assertEqual(treatments.LAYOUT_WINDOWS["text"], (2.0, 4.0))
        self.assertEqual(treatments.LAYOUT_WINDOWS["full"], (2.5, 5.0))
        card = next(t for t in templates.all_templates() if t.get("kind") == "card" and t["category"] == "TEXT")
        self.assertEqual(treatments.layout_window(card, "text")[1], 5.0)
        slow = templates.get("LIB_CT_DOT_GRID")                     # its count lands at frame 54
        lo, _hi = treatments.layout_window(slow, "figure")
        self.assertGreaterEqual(lo, (54 + treatments.EXIT_FRAMES) / 30.0)
        self.assertEqual(treatments.animation_seconds({"defaults": {}}),
                         (treatments.ENTRANCE_FRAMES + treatments.EXIT_FRAMES) / 30.0 + treatments.SETTLE)
        _s, _sc, out = plan(FLOOD, flood_shots(), FLOOD_BRIEF)
        for o in out["overlays"]:
            t = templates.get(o["template"])
            self.assertGreaterEqual(o["durationInFrames"] / FPS + 1 / FPS, treatments.animation_seconds(t), o)
            cap = 12.0 if treatments.is_persist_look(t) else treatments.TALKING_MAX
            self.assertLessEqual(o["durationInFrames"] / FPS, cap + 1e-6, o)

    def test_a_map_stays_longer_only_while_the_narration_keeps_talking_about_it(self):
        el_paso = {"subject": "El Paso", "overlay": {"type": "map", "text": "El Paso", "locations": [
            {"label": "El Paso", "lat": 31.76, "lon": -106.49}]}}
        on = ["It all began just outside El Paso.", "El Paso had never seen water like it in living memory."]
        off = ["It all began just outside El Paso.", "Crews worked through the long night shift here."]
        for lines, longer in ((on, True), (off, False)):
            _s, _sc, out = plan(lines, [el_paso, {"subject": "El Paso"}], pause=0.3)
            [m] = [o for o in out["overlays"] if o["type"] == "map" or (templates.get(o["template"]) or {}).get("kind") == "map"]
            secs = m["durationInFrames"] / FPS
            if longer:
                self.assertGreater(secs, 5.0)
                self.assertLessEqual(secs, treatments.TALKING_MAX + 1e-6)
            else:
                self.assertLessEqual(secs, 5.0 + 1e-6)


# --------------------------------------------------------------------------- one graphic at a time
class OneAtATime(unittest.TestCase):
    def test_no_two_graphics_overlap_over_twenty_minutes(self):
        from tests import test_look_variety as lv
        segs, shots, scenes, brief = lv.build()
        total = scenes[-1]["startFrame"] + scenes[-1]["durationInFrames"]
        for pack in ("documentary", "news"):
            out = treatments.plan(segs, shots, scenes, FPS, total, brief, treatments.pack_for(brief, pack),
                                  timeline._OVERLAY_SECONDS)
            ovs = sorted(out["overlays"], key=lambda o: o["startFrame"])
            for a, b in zip(ovs, ovs[1:]):
                self.assertLessEqual(span(a)[1], b["startFrame"], (pack, a["template"], b["template"]))

    def test_nothing_lands_on_or_runs_into_a_full_screen_scene(self):
        lines = ["By noon the county said 40 percent of homes had no water at all.",
                 "Here the numbers take over the whole screen.",
                 "Then 26 percent of the wells ran dry within the week.",
                 "Plain words about the town follow here."]
        _s, scenes, out = plan(lines, kinds={1: "animation"}, pause=0.0)
        block = (scenes[1]["startFrame"], scenes[1]["startFrame"] + scenes[1]["durationInFrames"])
        self.assertTrue(out["overlays"])
        for o in out["overlays"]:
            a, b = span(o)
            self.assertFalse(a < block[1] and block[0] < b, (o["template"], (a, b), block))

    def test_the_jobs_title_card_is_kept_clear(self):
        doc = build_doc(FLOOD[:4], inp={"title_overlay": "The Texas Flood"})
        title = next(o for o in doc["overlays"] if o["type"] == "title")
        for o in doc["overlays"]:
            if o is not title:
                self.assertFalse(span(o)[0] < span(title)[1] and span(title)[0] < span(o)[1], o["template"])


# --------------------------------------------------------------------------- maps: real places only
class _Reply:
    def __init__(self, hits):
        self.hits = hits

    def raise_for_status(self):
        pass

    def json(self):
        return self.hits


class Maps(unittest.TestCase):
    def setUp(self):
        geocode.reset_cache()
        self.slow = mock.patch.object(geocode, "_RATE_LIMIT_SECONDS", 0.0)
        self.slow.start()

    def tearDown(self):
        self.slow.stop()
        geocode.reset_cache()

    def lookup(self, name, hits):
        with mock.patch.object(geocode.requests, "get", return_value=_Reply(hits)) as get:
            got = geocode.lookup(name)
        self.assertEqual(get.call_args.kwargs["params"]["limit"], 5)
        return got

    def test_a_business_is_never_mapped(self):
        shop = {"lat": "31.77", "lon": "-106.44", "category": "shop", "type": "paint",
                "display_name": "Sherwin-Williams, 123 Main St, El Paso, Texas, United States"}
        office = {"lat": "31.7", "lon": "-106.4", "category": "office", "type": "company",
                  "display_name": "Sherwin-Williams Company, United States"}
        self.assertIsNone(self.lookup("Sherwin-Williams", [shop, office]))
        self.assertEqual(geocode.resolve_all(["Sherwin-Williams"]), [])       # cached: still nothing

    def test_a_real_place_is_labelled_as_the_story_says_it(self):
        shop = {"lat": "31.77", "lon": "-106.44", "category": "amenity", "type": "restaurant",
                "display_name": "El Paso Grill, Denver, Colorado, United States"}
        city = {"lat": "31.7619", "lon": "-106.485", "category": "boundary", "type": "administrative",
                "addresstype": "city", "display_name": "El Paso, El Paso County, Texas, United States"}
        got = self.lookup("El Paso, Texas, USA", [shop, city])
        self.assertEqual((got.label, got.lat, got.kind), ("El Paso, Texas", 31.7619, "city"))
        region = {"lat": "33.2", "lon": "-97.1", "class": "place", "type": "region", "display_name": "North Texas"}
        self.assertEqual(self.lookup("North Texas", [region]).label, "North Texas")
        river = {"lat": "29.6", "lon": "-97.9", "category": "waterway", "type": "river",
                 "display_name": "Guadalupe River, Texas, United States"}
        self.assertEqual(self.lookup("Guadalupe River", [river]).label, "Guadalupe River")

    def test_place_classes(self):
        for cls in ("boundary", "place", "natural", "waterway", "highway"):
            self.assertTrue(geocode.is_place({"category": cls}), cls)
        for cls in ("shop", "office", "amenity", "building", "tourism", "craft", ""):
            self.assertFalse(geocode.is_place({"category": cls}), cls)
        self.assertEqual(geocode.spoken_label("  Kerrville,  Texas, United States "), "Kerrville, Texas")


if __name__ == "__main__":
    unittest.main()
