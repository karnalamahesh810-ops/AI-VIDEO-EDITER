"""
No footage cut opens on the end of a shot (the owner's 5-minute Glen Canyon test, 2026-10-05: "the
first second or two didn't match").

The test video's first clip was cut from a 7.5 s section of its source (184.6-192.1 s) for the moment
at 186.6 s. A hard cut 1.467 s after that moment - from another creator's "CAVITATION" explainer
graphic to 1983 footage of the spillway gates - scored 0.36 in ffmpeg's scene detector, under the 0.4
the clean-cut trimming looked for: the job recorded "cuts": 0, kept the planned in-point, and the
video opened on 1.43 s of the shot before.

  A. shot changes the fixed threshold missed (filters.shot_changes)
  B. no in-point under CUT_GUARD_SECONDS before a shot change (filters.clean_window, snap_past_cut)
  C. the same on real files (filters.scene_cuts, tidy_clip)
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from src import config, filters

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def rows_of(scores, fps=30.0):
    """(frame, seconds, score) rows as filters._scan returns them."""
    return [(n, round(n / fps, 4), s) for n, s in enumerate(scores)]


def _picture(seed):
    """A small grey frame with structure (48x27, as _scan writes them): `seed` picks the picture."""
    import numpy as np
    y, x = np.mgrid[0:27, 0:48]
    return (128 + 60 * np.sin(x / (3.0 + seed) + seed) * np.cos(y / (2.0 + seed / 2.0))).astype("uint8")


def pictures_of(*runs):
    """One picture per frame from [(frames, picture)] runs - a shot holding still."""
    import numpy as np
    return np.stack([pic for count, pic in runs for _ in range(count)])


def _video(path, parts, fps=25):
    """A test section from [(seconds, lum expression)] - static grey stripes, so the only
    change between frames is where one part meets the next."""
    args, chains = [], []
    for k, (secs, lum) in enumerate(parts):
        args += ["-f", "lavfi", "-i", f"nullsrc=s=320x180:r={fps}:d={secs},geq=lum='{lum}':cb=128:cr=128"]
        chains.append(f"[{k}:v]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args, "-filter_complex",
                    f"{''.join(chains)}concat=n={len(parts)}:v=1:a=0,format=yuv420p[v]", "-map", "[v]",
                    "-c:v", "libx264", "-preset", "ultrafast", path], check=True, timeout=120)
    return path


def _swing(path, px_per_frame, onset=1.5, total=4.0, fps=30):
    """One shot of a textured picture held still, then the camera swinging sideways at once at
    `px_per_frame` (640 px wide; the picture wraps round) - one continuous shot, no cut."""
    lum = "128+45*sin(X/53)*cos(Y/37)+35*sin((X+2*Y)/97)+25*cos(X/211)"
    fc = (f"[0:v]geq=lum='{lum}':cb=128:cr=128,split=2[a][b];"
          f"[a]trim=end={onset},setpts=PTS-STARTPTS[s];"
          f"[b]trim=end={total - onset},setpts=PTS-STARTPTS,scroll=horizontal={px_per_frame / 640:.5f}[m];"
          f"[s][m]concat=n=2:v=1:a=0,format=yuv420p[v]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"nullsrc=s=640x360:r={fps}:d={total}",
                    "-filter_complex", fc, "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", path],
                   check=True, timeout=120)
    return path


ACROSS = "128+40*sin(X/6)"           # the shot before: stripes across
DOWN = "128+40*sin(Y/6)"             # the shot after: stripes down, the same grey (a cut ffmpeg scores ~0.32)


def _first_frame_like(path, other, at_other):
    """How alike `path`'s first frame is to `other`'s frame at `at_other` s (filters.same_picture)."""
    import numpy as np

    def grab(p, t):
        out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", p, "-frames:v", "1",
                              "-vf", "scale=48:27,format=gray", "-f", "rawvideo", "-"],
                             capture_output=True, timeout=60).stdout
        return np.frombuffer(out, dtype=np.uint8).reshape(27, 48)
    return filters.same_picture(grab(path, 0.04), grab(other, at_other))


# --------------------------------------------------------------------------- A. shot changes
class ShotChanges(unittest.TestCase):
    def test_the_glen_canyon_cut_scored_under_the_old_threshold_is_found(self):
        # Measured on the published video: 0.365 at 1.467 s against ~0.02-0.08 around it.
        scores = [0.0] + [0.02, 0.06, 0.01, 0.05] * 10 + [0.06, 0.02, 0.365, 0.03, 0.05] + [0.02, 0.06] * 15
        rows = rows_of(scores)
        at = scores.index(0.365)
        cut = rows[at][1]
        frames = pictures_of((at, _picture(1)), (len(scores) - at, _picture(4)))
        self.assertEqual(filters.shot_changes(rows, frames), [cut])
        with mock.patch.object(config, "SHOT_CUT_SOFT_THRESHOLD", 0.0):
            self.assertEqual(filters.shot_changes(rows, frames), [])  # the fixed threshold alone: missed

    def test_a_softer_jump_needs_frames_that_line_up(self):
        # Without the frames - or with one picture too many or too few, a variable-rate file written
        # at a constant rate - the flicker check cannot run: only the fixed threshold counts.
        scores = [0.0] + [0.02] * 40 + [0.36] + [0.02] * 40
        rows = rows_of(scores)
        good = pictures_of((41, _picture(1)), (41, _picture(4)))
        self.assertEqual(len(filters.shot_changes(rows, good)), 1)
        self.assertEqual(filters.shot_changes(rows), [])
        self.assertEqual(filters.shot_changes(rows, pictures_of((41, _picture(1)), (42, _picture(4)))), [])
        self.assertEqual(filters.shot_changes(rows, pictures_of((40, _picture(1)), (41, _picture(4)))), [])

    def test_the_same_picture_brighter_is_a_flicker_not_a_cut(self):
        import numpy as np
        scores = [0.0] + [0.01] * 30 + [0.23] + [0.01] * 30
        rows = rows_of(scores)
        base = (np.arange(27 * 48).reshape(27, 48) % 37).astype("uint8") * 4
        same = np.stack([base] * 31 + [np.clip(base.astype(int) + 40, 0, 255).astype("uint8")] * 31)
        other = np.stack([base] * 31 + [base.T.copy().reshape(27, 48)[::-1]] * 31)
        self.assertEqual(filters.shot_changes(rows, same), [])        # an old film's exposure jump (0.87 there)
        self.assertEqual(len(filters.shot_changes(rows, other)), 1)   # a different picture: a cut

    def test_a_camera_starting_to_swing_is_not_a_cut(self):
        # ffmpeg's score answers a change in motion: a swing that starts at once jumps it for one frame
        # (0.3 against ~0.01), the two frames either side differ, and the picture keeps moving after it.
        import numpy as np
        scores = [0.0] + [0.01] * 40 + [0.3] + [0.01] * 40
        rows = rows_of(scores)
        still = _picture(1)
        frames = np.stack([still] * 41 + [np.roll(still, 6 * (j + 1), axis=1) for j in range(41)])
        self.assertEqual(filters.shot_changes(rows, frames), [])
        # Too fast for the same picture to be found moved: the frames after it never hold steady.
        fast = np.stack([still] * 41 + [np.roll(still, 13 * (j + 1), axis=1) for j in range(41)])
        self.assertEqual(filters.shot_changes(rows, fast), [])
        with mock.patch.multiple(config, SHOT_CUT_STEADY=0.0, SHOT_CUT_MOVED=0.0):
            self.assertEqual(len(filters.shot_changes(rows, frames)), 1)   # unchecked: read as a cut

    def test_a_cut_into_a_moving_shot_is_still_a_cut(self):
        # Another picture after the jump, panning gently from there: a new shot that holds steady.
        import numpy as np
        scores = [0.0] + [0.01] * 40 + [0.3] + [0.01] * 40
        rows = rows_of(scores)
        other = _picture(4)
        frames = np.stack([_picture(1)] * 41 + [np.roll(other, 2 * j, axis=1) for j in range(41)])
        self.assertEqual(filters.shot_changes(rows, frames), [rows[41][1]])

    def test_steady_motion_never_reads_as_a_cut(self):
        rows = rows_of([0.0] + [0.25, 0.3, 0.27, 0.22] * 20)          # a fast pan: every frame changes alike
        self.assertEqual(filters.shot_changes(rows), [])

    def test_hard_cuts_count_as_before(self):
        rows = rows_of([0.0] + [0.01] * 20 + [0.62] + [0.3] * 20)
        self.assertEqual(filters.shot_changes(rows), [rows[21][1]])


# --------------------------------------------------------------------------- B. clean in-points
class CleanInPoints(unittest.TestCase):
    def test_the_glen_canyon_section_now_opens_after_its_cut_and_keeps_its_length(self):
        # The job's section: 184.6-192.1 s (7.5 s), the moment at 186.6 s (prefer 2.0), 3.5 s wanted,
        # the cut 1.467 s after the moment. Unseen, the clip opened 1.47 s before it.
        self.assertEqual(filters.clean_window(7.5, [], 3.5, 2.0), (2.0, True, 0))
        off, clean, n = filters.clean_window(7.5, [2.0 + 1.467], 3.5, 2.0)
        self.assertAlmostEqual(off, 3.467 + config.CUT_SNAP_PAD, places=3)
        self.assertTrue(clean)
        self.assertEqual(n, 1)
        self.assertGreaterEqual(7.5 - off, 3.5)                       # its length kept, from later in the section

    def test_rapid_cutting_never_opens_just_before_a_cut(self):
        off, clean, n = filters.clean_window(11.0, [2.5, 4.0, 6.0, 8.0, 10.0], 7.0, 2.0)
        self.assertFalse(clean)                                       # no stretch long enough: as before
        self.assertAlmostEqual(off, 2.5 + config.CUT_SNAP_PAD)        # but never 0.5 s before a cut

    def test_a_remainder_too_short_is_not_used(self):
        self.assertEqual(filters.clean_window(6.0, [2.6, 3.3, 4.0], 3.5, 2.0), (None, False, 3))

    def test_snapping_past_cuts(self):
        self.assertAlmostEqual(filters.snap_past_cut(2.0, [2.4, 2.9, 5.0]), 3.0)   # one after the other
        self.assertAlmostEqual(filters.snap_past_cut(2.0, [1.95]), 2.05)           # its frames still on screen
        self.assertEqual(filters.snap_past_cut(2.0, [1.5, 3.2]), 2.0)              # none within the guard


# --------------------------------------------------------------------------- C. on real files
@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg needed")
class CleanInPointsOnRealFiles(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_a_cut_the_old_threshold_missed_is_found_and_the_clip_opens_after_it(self):
        # The Glen Canyon geometry: the section opens 2 s before the moment, the cut 1.47 s after it.
        src = _video(os.path.join(self.d, "yt_R_z4cbZu3Ok_184600_7500_abcdef0123.mp4"),
                     [(3.48, ACROSS), (4.04, DOWN)])
        ref = os.path.join(self.d, "ref.mp4")
        shutil.copy(src, ref)
        self.assertEqual(filters.scene_cuts(src, threshold=0.4), [])          # what the job saw: no cut
        cuts = filters.scene_cuts(src)
        self.assertEqual(len(cuts), 1)
        self.assertAlmostEqual(cuts[0], 3.48, delta=0.05)
        with mock.patch.object(config, "CLEAN_CUTS", True):
            out, clean, n = filters.tidy_clip(src, 3.5, prefer=2.0)
        self.assertTrue(out and os.path.exists(out) and not os.path.exists(src))
        self.assertTrue(clean)
        self.assertEqual(n, 1)
        self.assertGreaterEqual(filters._video_seconds(out), 3.4)
        self.assertEqual(filters.scene_cuts(out), [])                         # no cut inside the clip
        self.assertGreater(_first_frame_like(out, ref, 5.0), 0.9)             # it opens on the shot after
        self.assertLess(_first_frame_like(out, ref, 1.0), 0.5)                # not on the shot before

    def test_a_file_with_a_frame_missing_still_finds_its_softer_cut(self):
        # A phone or web file's timing has gaps: written at a constant rate, ffmpeg filled the gap with
        # a copy after the scores were numbered, every later picture was one frame late, and the cut
        # at 2.0 s was compared across two copies of the same frame - missed.
        src = _video(os.path.join(self.d, "steady.mp4"), [(2.0, ACROSS), (2.0, DOWN)])
        gap = os.path.join(self.d, "gap.mp4")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-vf", r"select='not(eq(n\,20))'",
                        "-fps_mode", "passthrough", "-c:v", "libx264", "-preset", "ultrafast", gap],
                       check=True, timeout=120)
        rows, pictures = filters._scan(gap, frames=True)
        self.assertEqual(len(pictures), max(r[0] for r in rows) + 1)
        self.assertEqual(filters.scene_cuts(gap, threshold=0.4), [])
        cuts = filters.scene_cuts(gap)
        self.assertEqual(len(cuts), 1)
        self.assertAlmostEqual(cuts[0], 2.0, delta=0.05)

    def test_a_fast_camera_swing_is_not_a_cut_and_keeps_the_in_point(self):
        # Measured: the swing's first frame scores ~0.32, the frames either side differ (0.41), and the
        # soft-cut path alone read it as a shot change - a clip from this section moved its in-point
        # to the end of the swing, marked clean.
        src = _swing(os.path.join(self.d, "swing.mp4"), 80)
        rows, _pictures = filters._scan(src, frames=True)
        self.assertTrue(any(s >= config.SHOT_CUT_SOFT_THRESHOLD for _n, _t, s in rows))  # the score did jump
        self.assertEqual(filters.scene_cuts(src, threshold=0.4), [])
        self.assertEqual(filters.scene_cuts(src), [])
        self.assertEqual(filters.clean_window(4.0, filters.scene_cuts(src), 2.0, 1.4), (1.4, True, 0))

    def test_an_exposure_flicker_is_not_a_cut(self):
        src = _video(os.path.join(self.d, "flicker.mp4"), [(1.4, "118+40*sin(X/6)"), (3.0, "148+40*sin(X/6)")])
        self.assertEqual(filters.scene_cuts(src), [])

    def test_a_short_section_opening_on_a_cut_starts_after_it_or_is_not_used(self):
        ok = _video(os.path.join(self.d, "short_ok.mp4"), [(0.5, ACROSS), (3.6, DOWN)])
        with mock.patch.object(config, "CLEAN_CUTS", True):
            out, clean, _n = filters.tidy_clip(ok, 3.5, prefer=0.0)
        self.assertTrue(out and out != ok and os.path.exists(out))            # moved past the cut: 3.5 s left
        self.assertEqual(filters.scene_cuts(out), [])
        short = _video(os.path.join(self.d, "short_bad.mp4"), [(0.5, ACROSS), (3.0, DOWN)])
        with mock.patch.object(config, "CLEAN_CUTS", True):
            out, clean, _n = filters.tidy_clip(short, 3.5, prefer=0.0)
        self.assertEqual((out, clean), ("", False))                           # never slowed: the next candidate
        self.assertFalse(os.path.exists(short))


if __name__ == "__main__":
    unittest.main()
