"""
Sounds built into the looks (the owner, 2026-09-30: "when you make an animation, the animation needs
its specific sound BUILT IN - not us adding sounds on the timeline"):

  * every registry look carries its sound design (defaults.sounds), written by
    scripts/build_registry.py from its old sound and the sound designer's map, and nothing lost its sound;
  * the renderer's schedule (remotion/src/components/lib/lookSoundPlan.ts) and its Python twin
    (sfxplan.look_sounds / plan_looks / doc_look_sounds): the peak on the look's frame, never past the
    look, scaled for the fps, set against the voice under the one cap, trimmed per overlay;
  * the planner no longer writes a timeline row for a look, and keeps the transitions clear of the looks';
  * the text-only looks: every date / time is the letter drop, a number leads with the bold count;
  * the TypeScript and the Python agree frame for frame (node + esbuild, skipped without them).
"""
import copy
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from src import config, sfxplan, templates, timeline, treatments
from src.media import MediaAsset
from src.transcribe import Segment, Word

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REMOTION = os.path.join(ROOT, "remotion")
REGISTRY = os.path.join(REMOTION, "src", "templates", "registry.json")
PLAN_TS = os.path.join(REMOTION, "src", "components", "lib", "lookSoundPlan.ts")
FPS = 30


def _build_registry():
    spec = importlib.util.spec_from_file_location("build_registry", os.path.join(ROOT, "scripts", "build_registry.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _registry() -> dict:
    with open(REGISTRY, encoding="utf-8") as fh:
        return json.load(fh)


def ov(tid, start, frames=120, **kw):
    return {"template": tid, "startFrame": start, "durationInFrames": frames, **kw}


def doc_of(overlays, scenes=None, **kw):
    return {"fps": FPS, "overlays": overlays, "scenes": scenes or [], "lookSounds": {}, **kw}


# --------------------------------------------------------------------------- the registry
class Registry(unittest.TestCase):
    def test_every_look_has_its_sound_design_and_every_file_ships(self):
        for t in _registry()["templates"]:
            d = t["defaults"]
            self.assertIsInstance(d.get("sounds"), list, t["id"])
            if d.get("ownSound"):
                self.assertEqual(d["sounds"], [], t["id"])      # its component plays its own <Audio>
            for c in d["sounds"]:
                self.assertIsInstance(c.get("name"), str, t["id"])
                self.assertIsInstance(c.get("at"), (int, float), t["id"])
                self.assertIn(c.get("align"), (None, "peak", "start"), t["id"])
                self.assertIn(c.get("kind"), (None, "typing"), t["id"])
                self.assertIn(c.get("when"), (None, "value", "no-value"), t["id"])
                # The file or a shipped stand-in: a missing file would 404 and fail the render.
                self.assertIsNotNone(sfxplan.resolve_sound(c["name"], c.get("alt")), (t["id"], c))

    def test_nothing_lost_its_sound(self):
        br = _build_registry()
        reg = {t["id"]: t for t in _registry()["templates"]}
        had = {t["id"] for t in br.TEMPLATES if (t["defaults"].get("sfx") or {}).get("name", "none") != "none"
               or sfxplan._types(t) or sfxplan.is_calendar_date(t)}
        with open(os.path.join(ROOT, "scripts", "library_looks.json"), encoding="utf-8") as fh:
            had |= {"LIB_" + look["id"].upper().replace("-", "_") for look in json.load(fh)
                    if (look.get("sfx") or "none") != "none" or look.get("types")}
        silent = sorted(tid for tid in had if not reg[tid]["defaults"]["sounds"] and not reg[tid]["defaults"].get("ownSound"))
        self.assertEqual(silent, [])

    def test_the_registry_file_is_generated(self):
        self.assertEqual(_build_registry().build(), _registry())

    def test_the_renderer_sets_levels_like_the_planner(self):
        levels = _registry()["soundLevels"]
        self.assertEqual(levels, json.loads(json.dumps(sfxplan.sound_levels())))
        self.assertEqual((levels["capUnder"], levels["refLufs"], levels["voiceDefault"]), (5.0, -20.0, -16.0))

    def test_the_sound_designers_map_is_applied(self):
        reg = {t["id"]: t for t in _registry()["templates"]}
        # Timing read off the components: the podium's first place lands at 60, the date slam look's day at 17,
        # where it now ticks softly (the owner, 2026-10-01: no punch, no slam).
        self.assertEqual(reg["LIB_NS_PODIUM"]["defaults"]["sfxAt"], 60)
        self.assertEqual(reg["LIB_DT_DATE_SLAM"]["defaults"]["sfxAt"], 17)
        self.assertEqual(reg["LIB_DT_DATE_SLAM"]["defaults"]["sounds"][0]["name"], "ui-tick")
        self.assertEqual(reg["LIB_DT_DATE_SLAM"]["defaults"]["sounds"][0]["alt"], ["tick"])
        with open(os.path.join(ROOT, "scripts", "look_sounds.json"), encoding="utf-8") as fh:
            design = json.load(fh)["looks"]
        for tid, e in design.items():
            d = reg[tid]["defaults"]
            if e.get("types"):
                self.assertTrue(d.get("types"), tid)
            if not d.get("ownSound"):
                self.assertEqual(d["sfx"]["name"], e["sfx"], tid)        # older documents: its main sound

    def test_the_punch_sounds_are_gone(self):
        # The owner, 2026-10-01: "you used a punch sound as well, we don't need that, that sound is super
        # bad, remove that sound effect from our list".
        reg = _registry()
        gone = {"date-slam", "impact-punch"}
        for t in reg["templates"]:
            d = t["defaults"]
            names = {c["name"] for c in d["sounds"]} | {a for c in d["sounds"] for a in c.get("alt") or []}
            self.assertFalse(names & gone, t["id"])
            self.assertNotIn(d["sfx"]["name"], gone, t["id"])
        self.assertFalse({s["file"] for s in reg["sfx"].values()} & gone)          # the editor's sound list
        for name in gone:
            self.assertFalse(os.path.exists(os.path.join(REMOTION, "public", "sfx", name + ".mp3")), name)
            self.assertNotIn(name, sfxplan._meta())
            self.assertNotIn(name, sfxplan.CATEGORY)
        # The date and number text looks tick softly and never land on a hit, not even as a stand-in.
        for tid in ("LIB_DT_LETTER_DROP", "LIB_BT_COUNT"):
            for c in templates.get(tid)["defaults"]["sounds"]:
                for name in [c["name"]] + list(c.get("alt") or []):
                    self.assertEqual(sfxplan.category(name), "tick", (tid, name))
        # A calendar date the designer's map leaves alone ticks too.
        self.assertEqual([c["name"] for c in templates.get("LIB_DT_BOLD_HEADLINE")["defaults"]["sounds"]],
                         [sfxplan.DATE_SOUND])

    def test_counters_roll_and_land(self):
        d = templates.get("NUM_BIG_COUNTER_V1")["defaults"]
        names = [(c["name"], c.get("when")) for c in d["sounds"]]
        self.assertIn(("count-roll", "value"), names)
        self.assertIn(("count-final", "value"), names)

    def test_the_text_only_looks_schedule_their_own_cues(self):
        for tid in ("LIB_DT_LETTER_DROP", "LIB_BT_COUNT"):
            t = templates.get(tid)
            self.assertEqual(t["defaults"]["soundTiming"], "look", tid)
            self.assertEqual(t["kind"], "tag", tid)
            self.assertIn("align", t["props"], tid)
        self.assertEqual(set(templates.cues_of(templates.get("LIB_DT_LETTER_DROP"))), {"date", "datetime", "time-of-day"})
        self.assertTrue({"big-number", "count", "percent", "money", "age"} <= set(templates.get("LIB_BT_COUNT")["cues"]))

    def test_the_editor_switches_a_looks_sound_and_trims_it(self):
        props = _registry()["templates"][0]["props"]
        self.assertEqual(props["sfx"]["options"], ["default", "none"])
        self.assertEqual((props["soundGain"]["min"], props["soundGain"]["max"], props["soundGain"]["default"]),
                         (0.0, 1.5, 1.0))
        self.assertNotIn("sfxVolume", props)
        self.assertEqual(templates.check(), [])


# --------------------------------------------------------------------------- one look's schedule
def sched(cues, **kw):
    kw.setdefault("fps", FPS)
    kw.setdefault("frames", 120)
    return sfxplan.look_sounds(cues, **kw)


class Schedule(unittest.TestCase):
    def test_a_hit_lands_its_peak_on_its_frame(self):
        peak = sfxplan._peak("swoosh-text", FPS)
        self.assertGreater(peak, 0)
        [s] = sched([{"name": "swoosh-text", "at": 20}])
        self.assertEqual((s["from"] + peak, s["trim"]), (20, 0))
        # Its peak due before the look starts: the head is skipped, never started early.
        [s] = sched([{"name": "swoosh-text", "at": 0}])
        self.assertEqual((s["from"], s["trim"]), (0, peak))
        # "start": it starts on the frame (a run with the move).
        [s] = sched([{"name": "swoosh-text", "at": 20, "align": "start"}])
        self.assertEqual(s["from"], 20)

    def test_nothing_rings_past_the_look(self):
        [s] = sched([{"name": "hit-deep", "at": 20}], frames=40)
        self.assertEqual(s["from"] + s["frames"], 40)
        self.assertGreater(s["fade"], 0)                                # cut there, it fades
        self.assertEqual(sched([{"name": "hit-deep", "at": 37}], frames=40), [])   # lands as the look leaves
        [whole] = sched([{"name": "ui-tick", "at": 10}], frames=200)
        self.assertEqual(whole["fade"], 0)                               # played whole: no fade

    def test_frames_scale_with_the_fps(self):
        [a] = sched([{"name": "swoosh-text", "at": 30}])
        [b] = sched([{"name": "swoosh-text", "at": 30}], fps=60, frames=240)
        self.assertEqual(b["from"] + sfxplan._peak("swoosh-text", 60), 60)
        self.assertEqual(a["from"] + sfxplan._peak("swoosh-text", 30), 30)

    def test_levels_follow_the_voice_the_pack_and_the_trims(self):
        cue = {"name": "whoosh-soft-v2", "at": 20}
        [s] = sched([cue])
        self.assertAlmostEqual(s["volume"], sfxplan.level("whoosh-soft-v2"), places=4)
        [q] = sched([cue], voice_lufs=-22.0)
        self.assertAlmostEqual(s["volume"] / q["volume"], 10 ** (6 / 20), places=2)
        [g] = sched([dict(cue, gain_db=-6.0)], intensity=0.5, gain=0.5, master=0.5)
        self.assertAlmostEqual(g["volume"], sfxplan.level("whoosh-soft-v2") * 10 ** (-6 / 20) * 0.125, places=4)
        # A fixed cue ignores the pack's intensity, never the trims.
        [f] = sched([{"name": "hit-deep", "at": 20, "fixed": True}], intensity=0.5)
        self.assertAlmostEqual(f["volume"], sfxplan.level("hit-deep"), places=4)
        # Never above the one cap, however it is pushed; a trim of 0 is silence.
        [loud] = sched([dict(cue, gain_db=20.0)], gain=1.5, master=2.0)
        self.assertLessEqual(loud["volume"], sfxplan.cap() + 1e-4)
        self.assertEqual(sched([cue], gain=0.0), [])
        self.assertLessEqual(sched([cue], voice_lufs=-6.0)[0]["volume"], 1.0)

    def test_a_pattern_repeats_and_conditions_hold(self):
        out = sched([{"name": "ui-tick", "at": 10, "every": 3, "count": 5}])
        self.assertEqual([s["from"] + sfxplan._peak("ui-tick", FPS) for s in out], [10, 13, 16, 19, 22])
        both = [{"name": "count-roll", "at": 6, "until": 40, "when": "value"}, {"name": "ui-pop", "at": 8, "when": "no-value"}]
        self.assertEqual([s["name"] for s in sched(both, value=42.0)], ["count-roll"])
        self.assertEqual([s["name"] for s in sched(both)], ["ui-pop"])
        [roll] = sched(both, value=1.0)
        self.assertEqual((roll["from"], roll["frames"]), (6, 34))       # runs to its until, not past it

    def test_a_typing_run_lasts_the_typing_span_on_the_videos_take(self):
        [s] = sched([{"name": "keys", "kind": "typing", "at": 6}], text="THE WATER", take="keys-laptop")
        self.assertEqual((s["name"], s["from"], s["frames"]), ("keys-laptop", 6, sfxplan.typing_span("THE WATER", FPS)))
        self.assertEqual(sched([{"name": "keys", "kind": "typing", "at": 6}], text="   "), [])
        long = sched([{"name": "keys", "kind": "typing", "at": 6}], text="x" * 400, frames=400)[0]
        self.assertEqual(long["frames"], int(sfxplan.TYPING_MAX_SECONDS * FPS))
        self.assertTrue(long["loop"])

    def test_a_missing_file_plays_its_stand_in_or_nothing(self):
        [s] = sched([{"name": "no-such-sound", "alt": ["tick"], "at": 10}])
        self.assertEqual(s["name"], "tick")
        meta = {k: v for k, v in sfxplan._meta().items() if k != "boom-sub"}
        with mock.patch.object(sfxplan, "_meta", lambda: meta):
            [d] = sched([{"name": "boom-sub", "at": 20}])               # no alt: its category's stand-in
            self.assertEqual(d["name"], "hit-deep")
        self.assertEqual(sched([{"name": "no-such-sound", "at": 10}]), [])

    def test_a_cue_repeats_once_per_item_or_place(self):
        cue = {"name": "ui-click", "at": 3, "every": 10, "count": "items"}
        self.assertEqual(len(sched([cue], items=3)), 3)
        self.assertEqual(sched([cue]), [])
        self.assertEqual(len(sched([dict(cue, count="locations")], locations=2, items=5)), 2)
        doc = doc_of([ov("CALL_BULLETS_V1", 0, 165, items=[{"label": "a"}, {"label": "b"}, {"label": "c"}, {"label": "d"}])])
        self.assertEqual(len(sfxplan.doc_look_sounds(doc)), 4)

    def test_scale_stretches_with_the_look(self):
        [s] = sched([{"name": "ui-pop", "at": 50, "scale": True, "align": "start"}], frames=200, default_frames=100)
        self.assertEqual(s["from"], 100)


# --------------------------------------------------------------------------- the document's pass
class DocumentPass(unittest.TestCase):
    def looks(self, doc):
        return sorted({s["look"] for s in sfxplan.doc_look_sounds(doc)})

    def test_of_two_looks_landing_together_only_the_stronger_sounds(self):
        # A low look and a high one 10 frames apart: the high one wins.
        low = "TEXT_KICKER_V1"                  # a low-emphasis tag with one plain hit
        self.assertEqual(templates.get(low)["emphasis"], "low")
        high = "LIB_DT_DATE_SLAM"
        doc = doc_of([ov(low, 0, 60), ov(high, 10, 90, text="MAY 5")])
        self.assertEqual(self.looks(doc), [1])
        doc = doc_of([ov(low, 0, 60), ov(high, 40, 90, text="MAY 5")])     # 1.3 s apart: both
        self.assertEqual(self.looks(doc), [0, 1])

    def test_typing_looks_take_the_keyboards_in_turn(self):
        ovs = [ov("TEXT_TYPEWRITER_V1", 300 * i, 240, text="The water kept falling") for i in range(5)]
        names = [s["name"] for s in sfxplan.doc_look_sounds(doc_of(ovs))]
        self.assertEqual(names, ["keys-type", "keys-laptop", "keys-mech", "keys", "keys-type"])

    def test_the_editor_silences_or_swaps_a_looks_sound(self):
        self.assertEqual(self.looks(doc_of([ov("LIB_DT_DATE_SLAM", 0, text="MAY 5", sfx="none")])), [])
        [s] = sfxplan.doc_look_sounds(doc_of([ov("LIB_DT_DATE_SLAM", 0, text="MAY 5", sfx="ui-pop")]))
        self.assertEqual(s["name"], "ui-pop")
        self.assertEqual(s["startFrame"] + sfxplan._peak("ui-pop", FPS), 17)    # on the look's hit (sfxAt)
        # The planner's own resolved choice equal to the default is not an override.
        default = templates.get("LIB_DT_DATE_SLAM")["defaults"]["sfx"]
        self.assertEqual(self.looks(doc_of([ov("LIB_DT_DATE_SLAM", 0, text="MAY 5", sfx=dict(default))])), [0])
        # The soundGain trim scales it.
        [a] = sfxplan.doc_look_sounds(doc_of([ov("LIB_DT_DATE_SLAM", 0, text="MAY 5")]))
        [b] = sfxplan.doc_look_sounds(doc_of([ov("LIB_DT_DATE_SLAM", 0, text="MAY 5", soundGain=0.5)]))
        self.assertAlmostEqual(b["volume"], a["volume"] * 0.5, places=3)

    def test_sounds_off_is_off(self):
        self.assertEqual(sfxplan.doc_look_sounds(doc_of([ov("LIB_DT_DATE_SLAM", 0)], sfxEnabled=False)), [])

    def test_older_documents_keep_their_rows(self):
        # No lookSounds: the rows carry every sound as before; only a look that
        # schedules its own cues (useLookSound) plays on its own.
        doc = doc_of([ov("LIB_DT_DATE_SLAM", 0, text="MAY 5"), ov("LIB_DT_LETTER_DROP", 300, text="MAY 5")])
        doc.pop("lookSounds")
        self.assertEqual(self.looks(doc), [1])
        self.assertFalse(sfxplan.look_sounds_on(doc))
        self.assertTrue(sfxplan.look_sounds_on({"lookSounds": {}}))

    def test_own_sound_looks_are_left_to_their_components(self):
        entries = sfxplan.look_entries([ov("LIB_SP_CHECKLIST", 0)], [])
        [state] = sfxplan.plan_looks(entries, FPS)
        self.assertEqual(state["mode"], "own")
        self.assertEqual(sfxplan.doc_look_sounds(doc_of([ov("LIB_SP_CHECKLIST", 0)])), [])

    def test_an_animation_scene_plays_its_looks_sound(self):
        scenes = [{"id": "s0", "startFrame": 0, "durationInFrames": 150, "text": "It fell 26 percent.",
                   "media": {"type": "animation", "url": ""},
                   "animation": {"template": "NUM_BIG_COUNTER_V1", "value": 26, "suffix": "%"}}]
        names = [s["name"] for s in sfxplan.doc_look_sounds(doc_of([], scenes))]
        self.assertEqual(names, ["count-roll", "count-final"])


# --------------------------------------------------------------------------- the planner
def _seg(i, text, seconds=6.0):
    words = [Word(text=w, start=i * seconds + j * 0.3, end=i * seconds + j * 0.3 + 0.25) for j, w in enumerate(text.split())]
    return Segment(text=text, start=i * seconds, end=(i + 1) * seconds, words=words)


def _plan(lines, pack="documentary", shots=None):
    segs = [_seg(i, t) for i, t in enumerate(lines)]
    scenes = [{"id": f"s{i}", "startFrame": i * 180, "durationInFrames": 180,
               "media": {"type": "video", "url": f"https://x/{i}.mp4"}, "transition": "none", "motion": "none",
               "effect": "none"} for i in range(len(lines))]
    shots = shots or [{"subject": "Lake Mead"} for _ in lines]
    brief = {"kind": "explainer", "hookBeats": [], "sections": []}
    return treatments.plan(segs, shots, scenes, FPS, len(lines) * 180, brief, treatments.pack_for(brief, pack),
                           timeline._OVERLAY_SECONDS)


PLAIN = "Plain words about the water here."


class Planner(unittest.TestCase):
    def test_no_timeline_row_for_a_look_with_its_sound_built_in(self):
        ovs = [ov(t["id"], 400 * i, 150, text="x", value=5.0) for i, t in enumerate(templates.all_templates()[:60])]
        self.assertEqual(sfxplan.plan(ovs, FPS, 1.0), [])

    def test_the_document_carries_the_looks_sounds_and_the_transitions_keep_clear(self):
        n = 8
        segs = [_seg(i, f"On September {i + 10}, 2026, the lake fell {20 + i} percent.") for i in range(n)]
        shots = [{"query": f"q{i}", "visualType": "footage", "overlay": None, "subject": f"place {i}"} for i in range(n)]
        assets = [MediaAsset(kind="video", source="youtube", url=f"file:///tmp/{i}.mp4", local_path=f"file:///tmp/{i}.mp4")
                  for i in range(n)]
        with mock.patch.object(config, "TREATMENTS", True):
            doc = timeline.build(segs, shots, assets, audio_url="file:///tmp/vo.mp3", audio_duration=n * 6.0,
                                 inp={"style": "news", "style_pack": "news"})
        self.assertEqual(doc["lookSounds"], {"intensity": templates.style_packs()["news"]["sfxIntensity"]})
        self.assertFalse([s for s in doc["sfx"] if s.get("kind") != "transition"])
        looks = sfxplan.doc_look_sounds(doc)
        self.assertTrue(looks)
        # A transition's sound never lands within a second of a look's own, nor over it.
        for tr in doc["sfx"]:
            for s in looks:
                self.assertFalse(abs(tr["startFrame"] - s["startFrame"]) <= 30
                                 or (s["startFrame"] < tr["startFrame"] + tr["durationFrames"]
                                     and tr["startFrame"] < s["startFrame"] + s["frames"]), (tr, s))

    def test_every_date_and_time_is_the_letter_drop_in_every_style(self):
        lines = ["On July 2, the rain began.", PLAIN, "By September 15, 2026, the lake had dropped.", PLAIN,
                 "At 3:45 pm the gates opened.", PLAIN, "Sept. 25 was the deadline.", PLAIN]
        for pack in templates.style_packs():
            out = _plan(lines, pack)
            dated = [o for o in out["overlays"]
                     if set(templates.cues_of(templates.get(o["template"]))) & set(treatments.DATE_CUES)]
            self.assertEqual(len(dated), 4, (pack, [o["template"] for o in out["overlays"]]))
            self.assertEqual({o["template"] for o in dated}, {treatments.TEXT_DATE_LOOK}, pack)
            # The lower third at the safe margin, left and right in turn - never mid-frame (2026-10-01).
            self.assertEqual([o["align"] for o in dated], ["left", "right", "left", "right"], pack)
            # Lettered in turn: no two dates in a row look the same.
            styles = [o["textStyle"] for o in dated]
            self.assertTrue(set(styles) <= set(treatments.TEXT_LOOK_STYLES), styles)
            self.assertTrue(all(a != b for a, b in zip(styles, styles[1:])), styles)

    def test_never_the_centre_on_a_persons_shot(self):
        lines = ["On July 2, the rain began.", PLAIN, "On July 9, the river rose.", PLAIN, "On July 16, it fell."]
        shots = [{"subject": "Lake Mead"}, {"subject": "x"}, {"subject": "x"}, {"subject": "x"},
                 {"subject": "residents", "subjectType": "person"}]
        out = _plan(lines, shots=shots)
        self.assertEqual([o["align"] for o in out["overlays"] if o["template"] == treatments.TEXT_DATE_LOOK],
                         ["left", "right", "left"])

    def test_a_number_leads_with_the_bold_count(self):
        lines = ["Lake Mead is now at 26 percent.", PLAIN, "Some 12,000 people lost power.", PLAIN,
                 "The repairs cost $1.2 million.", PLAIN, "Only 18 percent was left.", PLAIN]
        out = _plan(lines)
        figures = [o for o in out["overlays"] if o.get("value") is not None]
        looks = [o["template"] for o in figures]
        self.assertEqual(looks[:2], [treatments.BOLD_COUNT_LOOK] * 2, looks)
        self.assertNotEqual(looks[2], treatments.BOLD_COUNT_LOOK, looks)     # variety after two in a row
        self.assertEqual(looks[3], treatments.BOLD_COUNT_LOOK, looks)
        for o in figures:
            if o["template"] == treatments.BOLD_COUNT_LOOK:
                self.assertIn(o["align"], ("left", "right", "center"))


# --------------------------------------------------------------------------- the TypeScript twin
def _node():
    node = shutil.which("node")
    esbuild = os.path.join(REMOTION, "node_modules", "esbuild", "bin", "esbuild")
    return (node, esbuild) if node and os.path.isfile(esbuild) else (None, None)


HARNESS = """
import { docLookSounds, scheduleCues } from "%(plan)s";
import registry from "%(registry)s";
import * as fs from "fs";
const T: Record<string, any> = {};
for (const t of (registry as any).templates) T[t.id] = t;
const input = JSON.parse(fs.readFileSync(0, "utf-8"));
const out = {
  docs: input.docs.map((d: any) => docLookSounds(d, d.fps, (id?: string) => (id ? T[id] : undefined))),
  schedules: input.schedules.map((s: any) => scheduleCues(s.cues, s.ctx)),
};
process.stdout.write(JSON.stringify(out));
"""


def _fixtures():
    all_ids = [t["id"] for t in templates.all_templates()]
    docs = []
    # Every look of the registry once, 5 s apart, with words and a number.
    docs.append(doc_of([ov(tid, 150 * i, 135, text="THE WATER FELL 26 PERCENT", value=26.0) for i, tid in enumerate(all_ids)],
                       meta={"voiceLufs": -18.3}, lookSounds={"intensity": 0.8}, sfxVolume=1.2))
    # The same without a number, short looks (cut sounds), 25 fps, a quiet voice.
    d = doc_of([ov(tid, 100 * i, 40, text="SEPTEMBER 30") for i, tid in enumerate(all_ids[::3])],
               meta={"voiceLufs": -23.0}, lookSounds={"intensity": 0.6})
    d["fps"] = 25
    docs.append(d)
    # Clashes, overrides, trims, typing takes, an animation scene, 60 fps.
    d = doc_of([ov("TEXT_TYPEWRITER_V1", 0, 200, text="Why did the lake fall?"),
                ov("LIB_DT_DATE_SLAM", 5, 90, text="MAY 5", emphasis="high"),
                ov("TEXT_MEMO_V1", 400, 200, text="A MEMO"),
                ov("LIB_DT_DATE_SLAM", 700, 90, text="MAY 6", sfx="ui-pop"),
                ov("LIB_DT_DATE_SLAM", 900, 90, text="MAY 7", sfx="none"),
                ov("MAP_LOCATION_ZOOM_V1", 1100, 330, text="Lake Mead", soundGain=0.4),
                ov("LIB_BT_COUNT", 1500, 120, value=90000, text="PEOPLE"),
                ov("LIB_DT_LETTER_DROP", 1700, 105, text="SEPTEMBER 30"),
                # Once per item / per place (the rebuilt list and spread map).
                ov("CALL_BULLETS_V1", 2300, 165, items=[{"label": "a"}, {"label": "b"}, {"label": "c"}]),
                ov("MAP_SPREAD_V1", 2600, 180, locations=[{"label": "Utah", "lat": 39, "lon": -111},
                                                          {"label": "Nevada", "lat": 38, "lon": -117}])],
               [{"id": "a", "startFrame": 2000, "durationInFrames": 150, "text": "It fell.",
                 "media": {"type": "animation", "url": ""}, "animation": {"template": "NUM_BIG_COUNTER_V1", "value": 26}}],
               meta={"voiceLufs": -14.0})
    d["fps"] = 60
    docs.append(d)
    scheds = [
        {"cues": [{"name": "swoosh-text", "at": 0}, {"name": "hit-deep", "at": 37}, {"name": "ui-tick", "at": 3.5, "every": 2.5,
                   "count": 7, "gain_db": -6, "pitch": 1.08}],
         "ctx": {"fps": 30, "frames": 40}},
        {"cues": [{"name": "keys", "kind": "typing", "at": 6}, {"name": "count-roll", "at": 5, "until": 300, "when": "value"},
                  {"name": "no-such", "alt": ["nope", "ui-pop"], "at": 12, "fade": 3}],
         "ctx": {"fps": 24, "frames": 250, "text": "x" * 60, "value": 3, "take": "keys-mech", "voice": -30,
                 "intensity": 0.5, "gain": 1.3, "master": 0.7}},
        {"cues": [{"name": "map-swoop", "at": 51, "scale": True}, {"name": "pin-drop", "at": 92, "scale": True, "gain_db": -2.2}],
         "ctx": {"fps": 30, "frames": 250, "defaultFrames": 165}},
    ]
    return docs, scheds


@unittest.skipUnless(all(_node()), "needs node and remotion's esbuild")
class TypeScriptTwin(unittest.TestCase):
    """The renderer's lookSoundPlan.ts and sfxplan's twin agree frame for frame, volume to 1e-4."""

    @classmethod
    def setUpClass(cls):
        node, esbuild = _node()
        cls.dir = tempfile.mkdtemp()
        entry = os.path.join(cls.dir, "harness.ts")
        with open(entry, "w", encoding="utf-8") as fh:
            fh.write(HARNESS % {"plan": PLAN_TS.replace("\\", "/")[:-3], "registry": REGISTRY.replace("\\", "/")})
        cls.bundle = os.path.join(cls.dir, "harness.cjs")
        subprocess.run([node, esbuild, entry, "--bundle", "--platform=node", "--format=cjs", f"--outfile={cls.bundle}",
                        "--log-level=error"], check=True, cwd=REMOTION, timeout=120)
        cls.node = node

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _compare(self, a, b, where):
        self.assertEqual(len(a), len(b), where)
        for x, y in zip(a, b):
            for k in ("name", "from", "frames", "trim", "loop", "fade"):
                self.assertEqual(x[k], y[k], (where, k, x, y))
            self.assertAlmostEqual(x["volume"], y["volume"], delta=1e-4, msg=(where, x, y))
            self.assertAlmostEqual(x["pitch"], y["pitch"], delta=1e-9, msg=(where, x, y))
            for k in ("startFrame", "look"):
                if k in x:
                    self.assertEqual(x[k], y[k], (where, k, x, y))

    def test_the_twins_agree(self):
        docs, scheds = _fixtures()
        run = subprocess.run([self.node, self.bundle], input=json.dumps({"docs": docs, "schedules": scheds}),
                             capture_output=True, text=True, timeout=120, check=True)
        got = json.loads(run.stdout)
        self.assertGreater(sum(len(x) for x in got["docs"]), 300)
        for i, d in enumerate(docs):
            self._compare(got["docs"][i], sfxplan.doc_look_sounds(copy.deepcopy(d)), f"doc {i}")
        for i, s in enumerate(scheds):
            c = s["ctx"]
            py = sfxplan.look_sounds(s["cues"], fps=c["fps"], frames=c["frames"], text=c.get("text", ""),
                                     value=c.get("value"), take=c.get("take"), default_frames=c.get("defaultFrames", 0),
                                     voice_lufs=c.get("voice"), intensity=c.get("intensity", 1.0),
                                     gain=c.get("gain", 1.0), master=c.get("master", 1.0))
            self._compare(got["schedules"][i], py, f"schedule {i}")


if __name__ == "__main__":
    unittest.main()
