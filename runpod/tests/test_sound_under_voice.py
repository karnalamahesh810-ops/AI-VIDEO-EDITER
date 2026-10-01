"""
No sound is ever louder than the narration (the owner, 2026-10-01: the sound
effects and transition sounds stood over the voiceover, the glitchy ones
most). Every sound a document plans - the transitions' rows, the sounds built
into the looks, the owner's pack clips - keeps its loudest moment at least
6 dB under the voice's loudness (doc.meta.voiceLufs), a glitch or static
sound 9 dB:

  * a sample document at a loud, a usual and a quiet voice: every planned
    gain, against the file's own measured loudness;
  * every transition sound at any style-pack intensity, every pack clip, the
    editor's 100% slider on a glitch;
  * the measured loudness ships with the renderer (sfx_meta.json,
    transitions_meta.json "lufs" / "peakDb") and is real (re-measured here);
  * the renderer's twin (transitions/packLevels.ts) agrees with the planner;
  * the narration is measured: the plan hands the build its file, and a
    render re-measures a voice the plan only assumed.
"""
import copy
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from src import config, sfxplan, timeline
from src.media import MediaAsset
from tests import test_pack_transitions as packs
from tests import test_planner_quality as quality

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REMOTION = os.path.join(ROOT, "remotion")
FPS = 30
VOICES = (-14.0, -20.0, -26.0)
SLACK = 0.01      # dB: volumes are stored to 3 decimals


def _sfx_lufs(name: str) -> float:
    """A sound file's loudest 400 ms as measured (sfx_meta.json "lufs")."""
    return float(sfxplan._meta()[name]["lufs"])


def _glitch(name: str) -> bool:
    return sfxplan.category(name) == "glitch"


def _as_rendered(doc: dict) -> dict:
    """What a render does to a document before drawing it (handler.do_render): drop what cannot draw, validate."""
    timeline.drop_invalid_overlays(doc)
    timeline.validate(doc, require_media=False)
    return doc


def planned_sounds(doc: dict) -> list:
    """
    (name, kind, volume as played, the file's loudest LUFS, glitch?) of every
    sound the document plays: the rows (times the master, as Main.tsx plays
    them), the looks' own (sfxplan.doc_look_sounds, the renderer's twin), and
    each pack clip at its planned transitionGain.
    """
    if doc.get("sfxEnabled") is False:
        return []
    master = float(doc.get("sfxVolume", 1.0))
    out = []
    for fx in doc.get("sfx") or []:
        out.append((fx["name"], "row", min(1.0, fx["volume"] * master), _sfx_lufs(fx["name"]), _glitch(fx["name"])))
    for s in sfxplan.doc_look_sounds(doc):
        out.append((s["name"], "look", s["volume"], _sfx_lufs(s["name"]), _glitch(s["name"])))
    meta = timeline.pack_meta()
    for sc in doc.get("scenes") or []:
        name = timeline.pack_name(sc.get("transition"))
        if name:
            m = meta[name]
            out.append((name, "pack", min(1.0, sc["transitionGain"] * min(1.0, master)), float(m["lufs"]),
                        m["character"] == "glitch"))
    return out


class Rule(unittest.TestCase):
    def assertUnderTheVoice(self, sounds, voice, where=""):
        self.assertTrue(sounds, where)
        for name, kind, vol, loud, glitch in sounds:
            if vol <= 0:
                continue
            under = voice - (loud + 20 * math.log10(vol))
            need = 9.0 if glitch else 6.0
            self.assertGreaterEqual(under, need - SLACK, (where, name, kind, vol, round(under, 2)))


# --------------------------------------------------------------------------- a whole document
class SampleDocument(Rule):
    def test_every_planned_sound_sits_6_db_under_the_voice_and_a_glitch_9(self):
        kinds = set()
        for voice in VOICES:
            # The looks' own sounds and the rows (the news pack, the Texas flood story).
            doc = quality.build_doc(quality.FLOOD, inp={"voice_lufs": voice})
            _as_rendered(doc)
            self.assertEqual(doc["meta"]["voiceLufs"], voice)
            got = planned_sounds(doc)
            kinds |= {k for _n, k, _v, _l, _g in got}
            self.assertUnderTheVoice(got, voice, f"flood doc at {voice}")
            # A long news cut: glitch and flash transitions, the owner's pack clips.
            segments, shots, _ = packs._script(n=90, seconds=3.0)
            assets = [MediaAsset(kind="video", source="youtube", url=f"file:///tmp/{i}.mp4",
                                 local_path=f"file:///tmp/{i}.mp4") for i in range(len(segments))]
            with mock.patch.object(config, "TREATMENTS", False), mock.patch.object(config, "TRANSITION_PACK", True):
                doc = timeline.build(segments, shots, assets, audio_url="file:///tmp/vo.mp3",
                                     audio_duration=len(segments) * 3.0,
                                     inp={"style": "news", "sfx": True, "voice_lufs": voice})
            _as_rendered(doc)
            got = planned_sounds(doc)
            kinds |= {k for _n, k, _v, _l, _g in got}
            self.assertTrue(any(g for _n, k, _v, _l, g in got if k == "row"), "a glitch transition was planned")
            self.assertTrue(any(k == "pack" for _n, k, _v, _l, _g in got), "a pack clip was planned")
            self.assertUnderTheVoice(got, voice, f"news cut at {voice}")
        self.assertEqual(kinds, {"row", "look", "pack"})

    def test_a_louder_master_never_lifts_a_sound_over_its_ceiling(self):
        doc = quality.build_doc(quality.FLOOD, inp={"voice_lufs": -20.0, "sfx_volume": 2.0})
        doc["sfx"].append({"name": "glitch-pro", "startFrame": 40, "volume": 1.0})      # the editor's 100%
        _as_rendered(doc)
        self.assertUnderTheVoice(planned_sounds(doc), -20.0, "master 2.0")


# --------------------------------------------------------------------------- every sound on its own
class EverySound(Rule):
    def test_every_transition_sound_at_any_intensity(self):
        for t in sorted(timeline._TRANSITION_SFX):
            scenes = [{"startFrame": 0, "durationInFrames": 90, "transition": "none"},
                      {"startFrame": 90, "durationInFrames": 90, "transition": t}]
            for voice in VOICES:
                for intensity in (0.6, 1.0, 1.6):
                    picks = timeline.plan_transition_sfx(scenes, FPS, [], intensity, voice_lufs=voice)
                    self.assertEqual(len(picks), 1, t)
                    p = picks[0]
                    self.assertUnderTheVoice([(p["name"], "row", p["volume"], _sfx_lufs(p["name"]), _glitch(p["name"]))],
                                             voice, (t, intensity))
        # The glitch transitions sit 9 dB under the voice (at full intensity, exactly there).
        [p] = timeline.plan_transition_sfx([{"startFrame": 0, "durationInFrames": 90, "transition": "none"},
                                            {"startFrame": 90, "durationInFrames": 90, "transition": "glitch"}],
                                           FPS, [], 1.0, voice_lufs=-20.0)
        self.assertAlmostEqual(sfxplan.peak_under_voice(p["name"], p["volume"], -20.0), 9.0, delta=0.02)

    def test_every_sound_file_at_its_level_and_its_ceiling(self):
        for name in sorted(n for n in sfxplan._meta() if sfxplan.exists(n)):
            for voice in VOICES:
                for vol in (sfxplan.level(name, voice), sfxplan.cap(voice, name), sfxplan.clamp(1.0, voice, 1.0, name)):
                    self.assertUnderTheVoice([(name, "file", vol, _sfx_lufs(name), _glitch(name))], voice, name)

    def test_the_built_in_glitch_looks_sit_under_the_glitch_ceiling(self):
        # The glitchy animations (glitch resolve, glitch slice, scan ID, LED counter) play glitch files.
        for tid in ("LIB_CH_GLITCH_RESOLVE", "LIB_FX_GLITCH_SLICE", "LIB_PA_SCAN_ID", "LIB_NC_LED_COUNTER"):
            ov = {"template": tid, "startFrame": 0, "durationInFrames": 150, "text": "SIGNAL LOST", "value": 42}
            for voice in VOICES:
                doc = {"fps": FPS, "overlays": [ov], "scenes": [], "lookSounds": {"intensity": 1.5},
                       "meta": {"voiceLufs": voice}, "sfxVolume": 1.0}
                got = [(s["name"], "look", s["volume"], _sfx_lufs(s["name"]), _glitch(s["name"]))
                       for s in sfxplan.doc_look_sounds(doc)]
                self.assertTrue(any(g for *_x, g in got), tid)
                self.assertUnderTheVoice(got, voice, tid)

    def test_every_pack_clip_at_any_voice(self):
        meta = timeline.pack_meta()
        for name, m in meta.items():
            for voice in VOICES + (-8.0, -40.0):
                g = timeline.pack_gain(name, voice)
                self.assertLessEqual(g, 1.0)
                self.assertGreater(g, 0.0)
                self.assertUnderTheVoice([(name, "pack", g, float(m["lufs"]), m["character"] == "glitch")], voice, name)
            # Exactly at the ceiling where it need not be held at its recorded level.
            g = timeline.pack_gain(name, -40.0)
            under = 9.0 if m["character"] == "glitch" else 6.0
            self.assertAlmostEqual(-40.0 - (m["lufs"] + 20 * math.log10(g)), under, places=6)
        # A loud voice leaves the clips as recorded, never above.
        self.assertEqual(timeline.pack_gain("mlt8", -8.0), 1.0)
        # A glitch clip sits 3 dB further under than a flash of the same loudness would.
        glitch, flash = timeline.pack_gain("mlt9", -30.0), 10 ** ((-30.0 - 6.0 - meta["mlt9"]["lufs"]) / 20)
        self.assertAlmostEqual(20 * math.log10(flash / glitch), 3.0, places=6)

    def test_a_build_stores_each_pack_clips_gain(self):
        segments, shots, bounds = packs._script(n=60, seconds=3.0)
        scenes = [{"startFrame": bounds[i], "durationInFrames": bounds[i + 1] - bounds[i], "transition": "glitch"}
                  for i in range(len(segments))]
        picks = {5: "mlt2", 20: "mlt11"}
        timeline.apply_pack_transitions(scenes, picks, FPS, voice_lufs=-22.0)
        for i, name in picks.items():
            self.assertEqual(scenes[i]["transition"], "pack:" + name)
            self.assertEqual(scenes[i]["transitionGain"], round(timeline.pack_gain(name, -22.0), 3))
        self.assertLess(scenes[20]["transitionGain"], 1.0)       # mlt11, the loudest clip, comes down for a -22 voice


# --------------------------------------------------------------------------- the measurements
class Measured(unittest.TestCase):
    def test_every_file_and_clip_carries_its_measured_loudness(self):
        for copy_ in ("public/sfx/sfx_meta.json", "src/data/sfx_meta.json"):
            with open(os.path.join(REMOTION, *copy_.split("/")), encoding="utf-8") as fh:
                meta = json.load(fh)
            for name, m in meta.items():
                self.assertTrue(-45.0 < m["lufs"] < -10.0, (copy_, name, m))
                self.assertTrue(-40.0 < m["peakDb"] <= 0.0, (copy_, name, m))
                self.assertGreater(m["peakDb"], m["lufs"], name)       # a peak is never under the loudness
        for name, m in timeline.pack_meta().items():
            self.assertTrue(-45.0 < m["lufs"] < -10.0, (name, m))
            self.assertTrue(-40.0 < m["peakDb"] <= 0.0, (name, m))

    @unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
    def test_the_numbers_are_the_files_own(self):
        def measure(path):
            # The loudest 400 ms (ffmpeg steps 100 ms; the stored figure was taken on a 10 ms hop) and the peak.
            p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-vn", "-af",
                                "adelay=delays=400:all=1,apad=pad_dur=1,ebur128=framelog=info,volumedetect",
                                "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace")
            ms = [float(x) for x in re.findall(r"\bM:\s*(-?\d+(?:\.\d+)?)", p.stderr)]
            peak = re.findall(r"max_volume:\s*(-?[\d.]+) dB", p.stderr)
            return max(ms), float(peak[-1])

        sfx = sfxplan._meta()
        for name in ("glitch-pro", "glitch-short-v2", "whoosh-fast", "letter-tick"):
            m, peak = measure(os.path.join(REMOTION, "public", "sfx", f"{name}.mp3"))
            self.assertAlmostEqual(m, sfx[name]["lufs"], delta=1.5, msg=name)
            self.assertAlmostEqual(peak, sfx[name]["peakDb"], delta=0.6, msg=name)
        for name in ("mlt2", "mlt11", "mlt17"):
            clip = timeline.pack_meta()[name]
            m, peak = measure(os.path.join(REMOTION, "public", clip["file"]))
            self.assertAlmostEqual(m, clip["lufs"], delta=1.5, msg=name)
            self.assertAlmostEqual(peak, clip["peakDb"], delta=0.6, msg=name)


# --------------------------------------------------------------------------- the narration is measured
class TheVoiceIsMeasured(unittest.TestCase):
    def test_the_plan_hands_the_build_its_narration_file(self):
        with open(os.path.join(ROOT, "handler.py"), encoding="utf-8") as fh:
            src = fh.read()
        call = src[src.index("doc = timeline.build("):]
        call = call[:call.index(")\n")]
        self.assertIn("narration_path=audio_path", call)

    def test_a_measured_file_wins_over_the_guess(self):
        with mock.patch.object(timeline, "measure_lufs", return_value=-23.4):
            d = tempfile.mkdtemp()
            path = os.path.join(d, "narration.mp3")
            open(path, "wb").close()
            self.assertEqual(timeline.voice_loudness("https://signed/x.mp3", {}, path), (-23.4, "measured"))
        self.assertEqual(timeline.voice_loudness("https://signed/x.mp3", {}), (sfxplan.VOICE_LUFS_DEFAULT, "assumed"))

    def _assumed_doc(self):
        return {"fps": FPS, "audio": {"url": "https://sb.example/narration.mp3"},
                "meta": {"voiceLufs": -16.0, "voiceLufsSource": "assumed"}, "sfxVolume": 1.0,
                "scenes": [{"id": "a", "startFrame": 0, "durationInFrames": 90, "transition": "none"},
                           {"id": "b", "startFrame": 90, "durationInFrames": 90, "transition": "pack:mlt11",
                            "transitionGain": 1.0}],
                "sfx": [{"name": "glitch-pro", "startFrame": 80, "volume": 0.708, "kind": "transition"},
                        {"name": "whoosh-fast", "startFrame": 20, "volume": 0.562, "kind": "transition"},
                        {"name": "hit-deep", "startFrame": 120, "volume": 0.3}]}

    def test_a_render_measures_a_voice_the_plan_only_assumed(self):
        doc = self._assumed_doc()
        seen = []
        self.assertTrue(timeline.relevel_to_voice(doc, measure=lambda url: seen.append(url) or -22.0))
        self.assertEqual(seen, ["https://sb.example/narration.mp3"])
        self.assertEqual((doc["meta"]["voiceLufs"], doc["meta"]["voiceLufsSource"], doc["meta"]["voiceLufsPlanned"]),
                         (-22.0, "measured", -16.0))
        k = 10 ** (-6 / 20)
        rows = {fx["name"]: fx["volume"] for fx in doc["sfx"]}
        # The planned rows come down with the voice (then under their ceilings); the editor's own stays.
        self.assertLessEqual(rows["glitch-pro"], round(0.708 * k, 3))
        self.assertAlmostEqual(rows["whoosh-fast"], round(0.562 * k, 3), places=3)
        self.assertEqual(rows["hit-deep"], 0.3)
        self.assertAlmostEqual(doc["scenes"][1]["transitionGain"], round(1.0 * k, 3), places=3)
        self.assertGreaterEqual(sfxplan.peak_under_voice("glitch-pro", rows["glitch-pro"], -22.0), 9.0 - SLACK)

    def test_a_louder_voice_never_raises_a_sound_and_a_known_voice_is_left_alone(self):
        doc = self._assumed_doc()
        before = copy.deepcopy(doc["sfx"])
        self.assertTrue(timeline.relevel_to_voice(doc, measure=lambda url: -12.0))
        self.assertEqual([fx["volume"] for fx in doc["sfx"]][1:], [fx["volume"] for fx in before][1:])
        for source in ("measured", "given"):
            doc = self._assumed_doc()
            doc["meta"]["voiceLufsSource"] = source
            self.assertFalse(timeline.relevel_to_voice(doc, measure=lambda url: self.fail("measured again")))
        doc = self._assumed_doc()
        self.assertFalse(timeline.relevel_to_voice(doc, measure=lambda url: None))     # unreadable: as planned
        self.assertEqual(doc["meta"]["voiceLufsSource"], "assumed")
        self.assertIsNone(timeline.measure_lufs_url("file:///tmp/vo.mp3"))            # only a web link is read


# --------------------------------------------------------------------------- the renderer's twin
def _node():
    node = shutil.which("node")
    esbuild = os.path.join(REMOTION, "node_modules", "esbuild", "bin", "esbuild")
    return (node, esbuild) if node and os.path.isfile(esbuild) else (None, None)


HARNESS = """
import { PACK_CLIPS, packGain, packVolume } from "%(levels)s";
import * as fs from "fs";
const input = JSON.parse(fs.readFileSync(0, "utf-8"));
const gains: Record<string, number> = {};
for (const name of Object.keys(PACK_CLIPS)) for (const v of input.voices) gains[`${name}@${v}`] = packGain(name, v);
const volumes = input.scenes.map((s: any) => packVolume(s.scene, s.voice, s.master));
process.stdout.write(JSON.stringify({ gains, volumes }));
"""


@unittest.skipUnless(all(_node()), "needs node and remotion's esbuild")
class RendererTwin(unittest.TestCase):
    def test_the_renderer_levels_a_pack_clip_like_the_planner(self):
        node, esbuild = _node()
        d = tempfile.mkdtemp()
        try:
            entry = os.path.join(d, "harness.ts")
            levels = os.path.join(REMOTION, "src", "transitions", "packLevels").replace("\\", "/")
            with open(entry, "w", encoding="utf-8") as fh:
                fh.write(HARNESS % {"levels": levels})
            bundle = os.path.join(d, "harness.cjs")
            subprocess.run([node, esbuild, entry, "--bundle", "--platform=node", "--format=cjs", f"--outfile={bundle}",
                            "--log-level=error"], check=True, cwd=REMOTION, timeout=120)
            voices = [-30.0, -20.0, -16.0, -8.0, None]
            scenes = [
                {"scene": {"transition": "pack:mlt11", "transitionGain": 1.0}, "voice": -22.0, "master": 1.0},
                {"scene": {"transition": "pack:mlt11", "transitionGain": 0.4}, "voice": -22.0, "master": 1.0},
                {"scene": {"transition": "pack:mlt2"}, "voice": -20.0, "master": 0.5},
                {"scene": {"transition": "pack:mlt7", "transitionGain": 0.9}, "voice": None, "master": 3.0},
                {"scene": {"transition": "pack:mlt7"}, "voice": -20.0, "master": 0.0},
                {"scene": {"transition": "glitch"}, "voice": -20.0, "master": 1.0},
            ]
            run = subprocess.run([node, bundle], input=json.dumps({"voices": voices, "scenes": scenes}),
                                 capture_output=True, text=True, timeout=120, check=True)
            got = json.loads(run.stdout)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        for name in timeline.pack_meta():
            for v in voices:
                key = f"{name}@{'null' if v is None else (int(v) if float(v).is_integer() else v)}"
                self.assertAlmostEqual(got["gains"][key], timeline.pack_gain(name, v), places=9, msg=key)

        def py_volume(s):
            name = timeline.pack_name(s["scene"]["transition"])
            if not name:
                return 0.0
            ceiling = timeline.pack_gain(name, s["voice"])
            asked = s["scene"].get("transitionGain")
            gain = min(asked, ceiling) if isinstance(asked, (int, float)) else ceiling
            return max(0.0, min(1.0, gain * max(0.0, min(1.0, s["master"]))))

        for s, v in zip(scenes, got["volumes"]):
            self.assertAlmostEqual(v, py_volume(s), places=9, msg=s)
        self.assertEqual(got["volumes"][-2:], [0, 0])     # muted master; not a pack transition


if __name__ == "__main__":
    unittest.main()
