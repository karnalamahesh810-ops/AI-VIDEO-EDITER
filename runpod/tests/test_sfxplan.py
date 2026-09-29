"""The overlay sound planner (src/sfxplan.py): on the hit, quiet, sparse, varied."""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from src import sfxplan

FILES = {  # name: (duration s, peak s)
    "whoosh": (2.3, 0.7), "whoosh-soft": (1.1, 0.4), "swipe": (0.44, 0.2),
    "impact": (2.4, 0.6), "boom-soft": (1.7, 0.3), "click": (0.11, 0.0), "tick": (0.09, 0.0),
    "keys": (5.0, 0.4), "count-tick": (1.32, 0.96), "pop": (0.48, 0.03), "marker": (0.7, 0.16),
}


def T(tid, sfx="whoosh", emphasis="medium", cues=(), component="motion", **defaults):
    return {"id": tid, "component": component, "cues": list(cues), "emphasis": emphasis,
            "defaults": {"duration": 3.0, "sfx": {"name": sfx, "volume": 0.3}, **defaults}}


REG = {t["id"]: t for t in [
    T("LOOK_A", "whoosh", sfxAt=12),
    T("LOOK_B", "whoosh"),
    T("LOOK_HIGH", "impact", emphasis="high"),
    T("LOOK_LOW", "pop", emphasis="low"),
    T("TYPE_LOOK", "none", types=True),
    T("TEXT_TYPEWRITER_V1", "typewriter", component="typewriter"),
    T("KICKER", "typewriter", types=False),
    T("DATE_LOOK", "impact", cues=["date"], emphasis="high", sfxAt=20),
    T("COUNT_LOOK", "pop", cues=["percent"]),
    T("COUNT_HIT", "pop", cues=["big-number"], sfxAt=45),
    T("SILENT", "none"),
    T("MISSING", "no-such-sound"),
    T("LIB_CC_TICK_BARS", "pop"), T("LIB_BM_STATE_CALLOUT", "map-whoosh"),
    T("LIB_SP_STATEMENT_CARD", "paper"), T("LIB_PS_PERCENT_RING", "pop"),
]}


def ov(tid, start, frames=90, **kw):
    return {"template": tid, "startFrame": start, "durationInFrames": frames, **kw}


class SfxPlanTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        for name in FILES:
            open(os.path.join(self.dir, f"{name}.mp3"), "wb").close()
        with open(os.path.join(self.dir, "sfx_meta.json"), "w", encoding="utf-8") as fh:
            json.dump({n: {"duration": d, "peak": p} for n, (d, p) in FILES.items()}, fh)
        self.patches = [mock.patch.object(sfxplan, "SFX_DIR", self.dir),
                        mock.patch.object(sfxplan.templates, "get", lambda tid: REG.get(tid or ""))]
        for p in self.patches:
            p.start()
        sfxplan.reload()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        sfxplan.reload()
        shutil.rmtree(self.dir, ignore_errors=True)

    def remove(self, *names):
        for n in names:
            os.remove(os.path.join(self.dir, f"{n}.mp3"))


class Alignment(SfxPlanTest):
    def test_the_peak_lands_on_the_looks_hit(self):
        [s] = sfxplan.plan([ov("LOOK_A", 300)], 30, 1.0)
        # hit = 300 + sfxAt 12; whoosh peaks 0.7 s (21 frames) in. The sound
        # never starts before its look: it starts with it and skips the head
        # of the file, so the peak still lands on frame 312.
        self.assertEqual((s["name"], s["startFrame"], s["trimFrames"]), ("whoosh", 300, 9))
        self.assertEqual(s["startFrame"] - s["trimFrames"] + 21, 312)
        self.assertEqual(s["durationFrames"], 69)          # the whole file: it ends inside the look
        # A look shorter than its sound: the sound stops (short release) with it.
        [s] = sfxplan.plan([ov("LOOK_A", 300, frames=30)], 30, 1.0)
        self.assertEqual(s["durationFrames"], 9 + 30 + 6)
        self.assertEqual(s["kind"], "overlay")
        self.assertEqual(set(s), {"name", "startFrame", "volume", "durationFrames", "kind", "trimFrames"})

    def test_frames_scale_with_the_frame_rate(self):
        [s] = sfxplan.plan([ov("LOOK_A", 600)], 60, 1.0)
        self.assertEqual((s["startFrame"], s["trimFrames"]), (600, 18))      # peak on 624

    def test_no_sfx_at_means_the_entrance_and_never_before_the_look(self):
        [s] = sfxplan.plan([ov("LOOK_B", 300)], 30, 1.0)
        # No hit frame: the entrance lands ~8 frames in; peak (21) on 308.
        self.assertEqual((s["startFrame"], s["trimFrames"]), (300, 13))
        [s] = sfxplan.plan([ov("LOOK_B", 5)], 30, 1.0)
        self.assertEqual(s["startFrame"], 5)

    def test_an_overlay_can_carry_its_own_hit_frame(self):
        [s] = sfxplan.plan([ov("LOOK_B", 300, sfxAt=30)], 30, 1.0)
        self.assertEqual(s["startFrame"], 300 + 30 - 21)             # late enough: no trim
        self.assertNotIn("trimFrames", s)

    def test_exports(self):
        self.assertEqual(sfxplan.peak_frames("whoosh", 30), 21)
        self.assertEqual(sfxplan.peak_frames("whoosh", 60), 42)
        self.assertTrue(sfxplan.exists("keys"))
        self.assertFalse(sfxplan.exists("no-such-sound"))
        self.assertFalse(sfxplan.exists("none"))
        self.assertFalse(sfxplan.exists("../keys"))


class Typing(SfxPlanTest):
    def test_keys_run_exactly_while_the_text_types(self):
        text = "Where did the water go?"                  # 23 chars <= 48: 2 frames a character
        [s] = sfxplan.plan([ov("TYPE_LOOK", 100, 200, text=text)], 30, 1.0)
        self.assertEqual((s["name"], s["startFrame"], s["durationFrames"]), ("keys", 106, 46))
        self.assertEqual(s["volume"], 0.1)

    def test_long_text_types_one_frame_a_character_and_is_capped(self):
        text = "x" * 60
        [s] = sfxplan.plan([ov("TYPE_LOOK", 0, 400, text=text)], 30, 1.0)
        self.assertEqual((s["startFrame"], s["durationFrames"]), (6, 60))
        [s] = sfxplan.plan([ov("TYPE_LOOK", 0, 900, text="y" * 400)], 30, 1.0)
        self.assertEqual(s["durationFrames"], 180)          # 6 s cap
        [s] = sfxplan.plan([ov("TYPE_LOOK", 0, 900, text="y" * 20)], 60, 1.0)
        self.assertEqual((s["startFrame"], s["durationFrames"]), (12, 80))

    def test_typing_stops_when_the_look_leaves(self):
        [s] = sfxplan.plan([ov("TYPE_LOOK", 0, 30, text="z" * 40)], 30, 1.0)
        self.assertEqual(s["durationFrames"], 24)
        self.assertEqual(sfxplan.plan([ov("TYPE_LOOK", 0, 5, text="z")], 30, 1.0), [])
        self.assertEqual(sfxplan.plan([ov("TYPE_LOOK", 0, 90, text="  ")], 30, 1.0), [])

    def test_a_typing_look_with_a_silent_registry_sound_still_types_aloud(self):
        # The planner may leave the resolved default {"name": "none"} on the overlay.
        [s] = sfxplan.plan([ov("TYPE_LOOK", 0, 90, text="abc", sfx={"name": "none", "volume": 0.0})], 30, 1.0)
        self.assertEqual(s["name"], "keys")
        self.assertEqual(sfxplan.plan([ov("TYPE_LOOK", 0, 90, text="abc", sfx="none")], 30, 1.0), [])

    def test_the_typewriter_template_types_even_without_the_flag(self):
        [s] = sfxplan.plan([ov("TEXT_TYPEWRITER_V1", 0, 90, text="Why?")], 30, 1.0)
        self.assertEqual((s["name"], s["startFrame"], s["durationFrames"]), ("keys", 6, 8))

    def test_a_look_that_does_not_type_never_clacks(self):
        [s] = sfxplan.plan([ov("KICKER", 0, 90, text="LAKE MEAD")], 30, 1.0)
        self.assertEqual(s["name"], "click")

    def test_the_old_typing_file_stands_in_for_keys(self):
        self.remove("keys")
        open(os.path.join(self.dir, "typewriter.mp3"), "wb").close()
        [s] = sfxplan.plan([ov("TYPE_LOOK", 0, 90, text="abc")], 30, 1.0)
        self.assertEqual(s["name"], "typewriter")
        os.remove(os.path.join(self.dir, "typewriter.mp3"))
        self.assertEqual(sfxplan.plan([ov("TYPE_LOOK", 0, 90, text="abc")], 30, 1.0), [])


class Counting(SfxPlanTest):
    def test_a_number_that_counts_ticks_for_the_count(self):
        [s] = sfxplan.plan([ov("COUNT_LOOK", 300, value=22, suffix="%")], 30, 1.0)
        self.assertEqual((s["name"], s["startFrame"], s["durationFrames"]), ("count-tick", 306, 39))

    def test_the_count_ends_on_the_hit(self):
        [s] = sfxplan.plan([ov("COUNT_HIT", 300, value=1200)], 30, 1.0)
        self.assertEqual((s["startFrame"], s["durationFrames"]), (306, 39))

    def test_no_value_or_no_tick_file_keeps_the_looks_own_sound(self):
        [s] = sfxplan.plan([ov("COUNT_LOOK", 300)], 30, 1.0)
        self.assertEqual(s["name"], "pop")
        self.remove("count-tick")
        [s] = sfxplan.plan([ov("COUNT_LOOK", 300, value=22)], 30, 1.0)
        self.assertEqual(s["name"], "pop")


class Volume(SfxPlanTest):
    def test_quiet_by_kind_and_scaled_by_the_pack(self):
        got = {s["name"]: s["volume"] for s in sfxplan.plan(
            [ov("LOOK_HIGH", 0), ov("LOOK_B", 300), ov("KICKER", 600, text="A"),
             ov("TYPE_LOOK", 900, text="abc")], 30, 1.0)}
        self.assertEqual(got, {"impact": 0.13, "whoosh": 0.15, "click": 0.15, "keys": 0.1})
        half = sfxplan.plan([ov("LOOK_B", 300)], 30, 0.5)
        self.assertEqual(half[0]["volume"], 0.075)

    def test_never_louder_than_the_cap(self):
        loud = sfxplan.plan([ov("LOOK_B", 0), ov("LOOK_B", 400, sfxVolume=0.9)], 30, 3.0)
        self.assertTrue(all(s["volume"] <= sfxplan.MAX_VOLUME for s in loud))
        self.assertEqual(loud[1]["volume"], sfxplan.MAX_VOLUME)

    def test_zero_intensity_is_silence(self):
        self.assertEqual(sfxplan.plan([ov("LOOK_B", 0)], 30, 0.0), [])


class Spacing(SfxPlanTest):
    def test_one_sound_per_six_seconds_the_stronger_look_winning(self):
        out = sfxplan.plan([ov("LOOK_LOW", 0), ov("LOOK_HIGH", 60), ov("LOOK_B", 120)], 30, 1.0)
        self.assertEqual([s["name"] for s in out], ["impact"])
        out = sfxplan.plan([ov("LOOK_B", 0), ov("LOOK_A", 60)], 30, 1.0)   # equal emphasis: first stays
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["startFrame"], 0)
        out = sfxplan.plan([ov("LOOK_B", 0), ov("LOOK_B", 180)], 30, 1.0)
        self.assertEqual(len(out), 2)

    def test_typing_and_dates_alone_on_screen_always_keep_their_sound(self):
        out = sfxplan.plan([ov("LOOK_HIGH", 0, 60), ov("TYPE_LOOK", 70, 60, text="Gone."),
                            ov("DATE_LOOK", 140, 60, text="SEPTEMBER 25, 2026")], 30, 1.0)
        self.assertEqual([s["name"] for s in out], ["impact", "keys", "boom-soft"])
        # The date's impact peak (0.3 s boom-soft after variation) lands on its sfxAt.
        self.assertEqual(out[2]["startFrame"], 140 + 20 - 9)

    def test_but_not_when_another_look_shares_the_screen(self):
        out = sfxplan.plan([ov("LOOK_HIGH", 0, 200), ov("TYPE_LOOK", 70, 60, text="Gone.")], 30, 1.0)
        self.assertEqual([s["name"] for s in out], ["impact"])

    def test_a_protected_sound_is_never_displaced(self):
        out = sfxplan.plan([ov("TYPE_LOOK", 0, 60, text="Gone."), ov("LOOK_HIGH", 90, 60)], 30, 1.0)
        self.assertEqual([s["name"] for s in out], ["keys"])


class Choice(SfxPlanTest):
    def test_looks_with_their_own_sounds_are_skipped(self):
        for tid in ("LIB_CC_TICK_BARS", "LIB_BM_STATE_CALLOUT", "LIB_SP_STATEMENT_CARD", "LIB_PS_PERCENT_RING"):
            self.assertEqual(sfxplan.plan([ov(tid, 0, value=40)], 30, 1.0), [], tid)

    def test_silent_missing_and_unknown(self):
        self.assertEqual(sfxplan.plan([ov("SILENT", 0), ov("MISSING", 300), ov("NOPE", 600),
                                       {"type": "map", "startFrame": 900}], 30, 1.0), [])

    def test_editor_overrides(self):
        self.assertEqual(sfxplan.plan([ov("LOOK_B", 0, sfx="none")], 30, 1.0), [])
        self.assertEqual(sfxplan.plan([ov("LOOK_B", 0, sfx={"name": "none", "volume": 0})], 30, 1.0), [])
        [s] = sfxplan.plan([ov("LOOK_B", 300, sfx="marker")], 30, 1.0)
        self.assertEqual((s["name"], s["startFrame"]), ("marker", 300 + 8 - 5))
        [s] = sfxplan.plan([ov("LOOK_B", 300, sfx={"name": "whoosh", "volume": 0.3})], 30, 1.0)
        self.assertEqual(s["name"], "whoosh")               # the resolved default is not an override
        [s] = sfxplan.plan([ov("TYPE_LOOK", 300, sfx="swipe", text="abc")], 30, 1.0)
        self.assertEqual(s["name"], "swipe")                # an explicit sound beats typing
        self.assertEqual(sfxplan.plan([ov("LOOK_B", 0, sfx="no-such-sound")], 30, 1.0), [])

    def test_a_repeated_sound_alternates_with_its_siblings(self):
        out = sfxplan.plan([ov("LOOK_B", 0), ov("LOOK_B", 200), ov("LOOK_B", 400), ov("LOOK_B", 1300)], 30, 1.0)
        self.assertEqual([s["name"] for s in out], ["whoosh", "whoosh-soft", "swipe", "whoosh"])

    def test_quiet_packs_start_soft(self):
        [s] = sfxplan.plan([ov("LOOK_B", 300)], 30, 1.0, style="cinematic")
        self.assertEqual(s["name"], "whoosh-soft")

    def test_missing_meta_is_tolerated(self):
        os.remove(os.path.join(self.dir, "sfx_meta.json"))
        sfxplan.reload()
        [s] = sfxplan.plan([ov("LOOK_B", 300)], 30, 1.0)
        self.assertEqual((s["startFrame"], s["trimFrames"]), (300, 13))   # measured peak of the original whoosh
        self.assertEqual(sfxplan.peak_frames("swipe", 30), 0)
        self.assertEqual(sfxplan.duration_frames("swipe", 30), 90)

    def test_output_is_sorted(self):
        out = sfxplan.plan([ov("LOOK_B", 900), ov("LOOK_HIGH", 0), ov("TYPE_LOOK", 400, text="abc")], 30, 1.0)
        self.assertEqual([s["startFrame"] for s in out], sorted(s["startFrame"] for s in out))


class RealFolder(unittest.TestCase):
    def test_every_sound_the_planner_names_ships(self):
        names = {sfxplan.TYPING_SOUND, sfxplan.COUNT_SOUND, sfxplan.NOT_TYPING_SOUND}
        names |= set(sfxplan.VARIANTS) | {v for vs in sfxplan.VARIANTS.values() for v in vs}
        missing = sorted(n for n in names if not sfxplan.exists(n))
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()


class OwnerSounds(unittest.TestCase):
    """The owner's own keyboard and glitch recordings (real sound folder)."""

    def test_typing_looks_take_the_owner_keyboards_in_turn(self):
        from src import templates
        typing = [t["id"] for t in templates.all_templates() if (t.get("defaults") or {}).get("types")][:1]
        self.assertTrue(typing)
        ovs = [{"template": typing[0], "startFrame": 300 * i, "durationInFrames": 240, "text": "The water kept falling"}
               for i in range(3)]
        names = [s["name"] for s in sfxplan.plan(ovs, 30, 1.0)]
        self.assertEqual(names[:2], ["keys-type", "keys-mech"])

    def test_the_files_are_there_and_measured(self):
        import json
        meta = json.load(open("remotion/public/sfx/sfx_meta.json", encoding="utf-8"))
        for name in ("keys-mech", "keys-type", "glitch-pro"):
            self.assertTrue(sfxplan.exists(name), name)
            self.assertIn(name, meta)
        main = open("remotion/src/Main.tsx", encoding="utf-8").read()
        self.assertIn('"keys-mech", "keys-type"', main)
