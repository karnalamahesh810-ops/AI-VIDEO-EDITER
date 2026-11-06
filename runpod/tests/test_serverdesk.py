"""The Breaking News Desk's 2026-11-07 rules (the owner's laptop kit, on the server): offline, no network, no paid call."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from PIL import Image

from src import stormdesk, stormlooks, stormpieces


def _red_share(fr, box):
    """Share of the box's pixels that are strongly red."""
    import numpy as np
    a = np.asarray(fr.convert("RGB").crop(box)).astype(int)
    return float(((a[..., 0] > 150) & (a[..., 1] < 90) & (a[..., 2] < 90)).mean())


class StatStyle(unittest.TestCase):
    def test_options_default_to_small_top_right_no_plate(self):
        self.assertEqual(stormlooks.stat_options({}), {"style": "corner", "size": "small", "color": ""})
        self.assertEqual(stormlooks.stat_options(None)["style"], "corner")

    def test_options_take_the_jobs_and_refuse_nonsense(self):
        o = stormlooks.stat_options({"stat_style": "CENTER", "stat_color": "#ffcc00", "stat_size": "medium"})
        self.assertEqual(o, {"style": "center", "size": "medium", "color": "#FFCC00"})
        o = stormlooks.stat_options({"stat_style": "huge", "stat_color": "red;", "stat_size": "giant"})
        self.assertEqual(o, {"style": "corner", "size": "small", "color": ""})
        self.assertEqual(stormlooks.stat_options({"stat_style": "center"})["size"], "large")     # the old big one

    def test_a_shot_spec_carries_the_style(self):
        tl = {"stats": [[1.0, 3.0, "13 DAYS"]]}
        row = stormpieces.looks_for_shot(tl, 0, 300, 30, {"style": "corner_plate", "size": "large", "color": "#00FF00"})[0]
        self.assertEqual(row, ["stat", 1.0, 3.0, "13 DAYS", "corner_plate", 72, "#00FF00"])
        self.assertEqual(stormpieces.looks_for_shot(tl, 0, 300, 30)[0][4:], ["corner", 46, ""])

    def test_the_style_changes_the_shots_name(self):
        def scene_doc(style):
            return {"fps": 30, "durationInFrames": 300, "stormDesk": {"statStyle": style, "looks": {"stats": [[1.0, 3.0, "13 DAYS"]]}},
                    "scenes": [{"id": "a", "startFrame": 0, "durationInFrames": 300, "media": {"type": "video", "url": "/tmp/a.mp4"}}]}
        a = stormpieces.spec_key(stormpieces.build_specs(scene_doc({"style": "corner"}))[0])
        b = stormpieces.spec_key(stormpieces.build_specs(scene_doc({"style": "center"}))[0])
        self.assertNotEqual(a, b)

    def _drawn(self, row):
        from src.sdkit import looks as L
        fr = Image.new("RGBA", (1920, 1080), (40, 60, 80, 255))
        stormpieces._draw_stat(fr, 1.5, row, L)
        return fr

    def test_corner_draws_top_right_center_draws_the_middle(self):
        corner = self._drawn(["stat", 1.0, 3.0, "13 DAYS UP", "corner", 46, ""])
        self.assertGreater(_red_share(corner, (1500, 80, 1900, 160)), 0.02)
        self.assertLess(_red_share(corner, (500, 400, 1420, 560)), 0.001)
        center = self._drawn(["stat", 1.0, 3.0, "13 DAYS UP", "center", 104, ""])
        self.assertGreater(_red_share(center, (500, 400, 1420, 560)), 0.02)
        self.assertLess(_red_share(center, (1500, 80, 1900, 160)), 0.001)

    def test_plate_darkens_behind_the_stat_and_colour_replaces_red(self):
        import numpy as np
        plain = self._drawn(["stat", 1.0, 3.0, "13 DAYS UP", "corner", 46, ""])
        plated = self._drawn(["stat", 1.0, 3.0, "13 DAYS UP", "corner_plate", 46, ""])
        box = (1500, 80, 1900, 160)
        self.assertLess(np.asarray(plated.convert("L").crop(box)).mean(), np.asarray(plain.convert("L").crop(box)).mean())
        green = self._drawn(["stat", 1.0, 3.0, "13 DAYS UP", "corner", 46, "#00FF00"])
        self.assertLess(_red_share(green, box), 0.001)

    def test_no_stat_outside_its_time(self):
        from src.sdkit import looks as L
        fr = Image.new("RGBA", (1920, 1080), (40, 60, 80, 255))
        before = fr.tobytes()
        L.corner_stat(fr, 5.0, 1.0, 3.0, "X")
        self.assertEqual(fr.tobytes(), before)


class ScreenChips(unittest.TestCase):
    def _keys(self, credit):
        d = {"fps": 30, "durationInFrames": 90, "stormDesk": {"logo": {"text": "T"}},
             "scenes": [{"id": "a", "startFrame": 0, "durationInFrames": 90, "credit": credit, "media": {"type": "video", "url": "/tmp/a.mp4"}}]}
        return stormpieces.scene_spec(d, 0, [])["layers"][0][1]

    def test_ai_chip_stays_archive_and_names_do_not(self):
        self.assertIn(("chip", "AI ILLUSTRATION", True), self._keys({"text": "AI ILLUSTRATION", "ai": True}))
        self.assertFalse(any(k[0] == "chip" for k in self._keys({"text": "VIDEO: KSL News"})))
        self.assertFalse(any(k[0] == "chip" for k in self._keys({"text": "VIDEO: KSL News", "archive": True})))


def _tone(path, seconds, freq=220, vol=0.5):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={seconds}",
                    "-af", f"volume={vol}", "-ac", "2", "-c:a", "libmp3lame", path], check=True)
    return path


def _db(x):
    import numpy as np
    return float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9))


class Sound(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_clip_sound_is_off_by_default(self):
        self.assertEqual(stormdesk.clip_sound_mode({}), "off")
        self.assertEqual(stormdesk.clip_sound_mode(stormdesk.options({})), "off")
        self.assertEqual(stormdesk.clip_sound_mode({"clip_sound": "ambient"}), "ambient")

    def test_bgm_options(self):
        self.assertEqual(stormdesk.bgm_options({}), {"lufs": -39.0, "onlyUnderVoice": True})
        self.assertEqual(stormdesk.bgm_options({"bgm_lufs": -5})["lufs"], -20.0)
        self.assertFalse(stormdesk.bgm_options({"bgm_only_under_voice": False})["onlyUnderVoice"])

    def test_bgm_only_under_the_voice_and_low(self):
        """A real ffmpeg mix: -39 LUFS (which TP -14 used to refuse), silent in the pauses, no pumping on a breath."""
        trk = _tone(os.path.join(self.d, "t.mp3"), 40)
        doc = {"bgm": {"url": trk}, "stormDesk": {"bgm": {"lufs": -39.0, "onlyUnderVoice": True}}}
        spans = [(10.0, 15.0), (15.8, 20.0), (30.0, 35.0)]        # a pause 20-30
        bed = stormpieces.music_bed(doc, 40.0, self.d, spans)
        sr = stormpieces.SR
        self.assertLess(_db(bed[3 * sr:9 * sr]), -80)              # nothing during the opening clip
        self.assertLess(_db(bed[23 * sr:27 * sr]), -80)            # nothing during the pause
        under = _db(bed[11 * sr:19 * sr])
        self.assertGreater(under, -45)                            # it is there (TP=-14 returned nothing)
        self.assertLess(under, -33)                               # and low
        breath = _db(bed[int(15.2 * sr):int(15.6 * sr)])          # the 0.8 s breath between the sentences
        self.assertLess(abs(breath - under), 1.0)

    def test_a_timeline_from_before_keeps_its_mix(self):
        trk = _tone(os.path.join(self.d, "t.mp3"), 20)
        bed = stormpieces.music_bed({"bgm": {"url": trk}}, 20.0, self.d, [(5.0, 8.0)])
        sr = stormpieces.SR
        self.assertGreater(_db(bed[12 * sr:14 * sr]), -40)        # plays with nobody talking

    def test_voice_blocks(self):
        self.assertEqual(stormpieces.voice_blocks([(1, 2), (2.5, 3), (10, 11)]), [(1, 3), (10, 11)])

    def _hook_doc(self, url, kind="nature", talk=False, secs=4, **media):
        return {"fps": 30, "durationInFrames": 300, "meta": {"stormDesk": {"pauses": [{"t0": 0.0, "t1": secs, "open": True}]}},
                "scenes": [{"id": "h", "startFrame": 0, "durationInFrames": secs * 30, "natSound": True, "openClip": True,
                            **({"talk": True} if talk else {}),
                            "media": {"type": "video", "url": url, "trimStart": 0.0, "clipAudio": {"kind": kind}, **media}}]}

    def test_a_clips_music_never_plays_in_a_pause(self):
        src = _tone(os.path.join(self.d, "m.mp3"), 10, freq=1000)
        track, rows = stormdesk.nat_track(self._hook_doc(src, kind="music"), 10.0, 0.0)
        self.assertEqual(rows[0].get("water"), "its sound is music")
        self.assertGreater(_db(track[:4 * 48000]), -50)
        import numpy as np
        spec = np.abs(np.fft.rfft(track[:4 * 48000, 0]))
        freqs = np.fft.rfftfreq(4 * 48000, 1 / 48000)
        tone = spec[(freqs > 990) & (freqs < 1010)].max()
        self.assertLess(tone, spec.max() * 0.9)                   # not the clip's 1 kHz tone: real water

    def test_a_hook_clips_own_sound_plays_and_audio_in_is_heard(self):
        src = os.path.join(self.d, "two.mp3")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000:duration=5", "-f", "lavfi", "-i",
                        "anullsrc=r=48000:cl=mono", "-filter_complex", "[1:a]atrim=0:5[z];[0:a][z]concat=n=2:v=0:a=1,aformat=channel_layouts=stereo",
                        "-c:a", "libmp3lame", src], check=True)
        # The picture sits in the silent half, the sound comes from the first 5 s.
        track, rows = stormdesk.nat_track(self._hook_doc(src, trimStart=6.0, audioIn=0.0), 10.0, 0.0)
        self.assertTrue(rows[0]["ok"])
        self.assertGreater(_db(track[:3 * 48000]), -40)
        silent, _r = stormdesk.nat_track(self._hook_doc(src, trimStart=6.0), 10.0, 0.0)
        self.assertLess(_db(silent[:3 * 48000]), -60)

    def test_a_silent_first_hook_gets_water(self):
        import numpy as np
        nat = np.zeros((10 * 48000, 2), np.float32)
        doc = self._hook_doc("/x.mp4")
        rep = stormdesk.hook_water(doc, nat, 10.0, 0.0)
        self.assertTrue(rep["added"])
        self.assertGreater(_db(nat[int(0.5 * 48000):3 * 48000]), -50)
        self.assertLess(_db(nat[5 * 48000:]), -80)                # gone after the clip

    def test_a_hook_with_its_own_sound_gets_none(self):
        import numpy as np
        nat = np.random.default_rng(1).normal(0, 0.1, (10 * 48000, 2)).astype(np.float32)
        before = nat.copy()
        self.assertIsNone(stormdesk.hook_water(self._hook_doc("/x.mp4"), nat, 10.0, 0.0))
        self.assertTrue((nat == before).all())


if __name__ == "__main__":
    unittest.main()
