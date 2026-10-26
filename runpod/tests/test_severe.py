"""The severe weather update style (src/severe.py, src/styles.py severe_weather): offline, no network."""
import unittest
from unittest import mock

from src import severe, styles

FPS = 30

# The forecast part of a real test script (docs/style-refs/severe-weather-usa/test_script.txt), one line a scene.
LINES = [
    "Floodwater broke into the Bloomfield wastewater plant, and the river near Bloomfield is a hazardous zone.",
    "Colorado has declared a disaster emergency for 11 counties.",
    "So what happens next? Let's go day by day.",
    "Today, the threat is not over.",
    "The National Weather Service in Albuquerque has a flash flood watch from noon to midnight for Santa Fe.",
    "On ground this wet, even a moderate storm can turn into a flash flood, and rain rates could top an inch an hour.",
    "Monday brings real relief.",
    "Farmington, Albuquerque and Santa Fe all drop to near zero chance of rain.",
    "But dry skies do not mean safe rivers.",
    "Tuesday and Wednesday are the clearest days in nearly a week, with highs near seventy.",
    "Albuquerque reaches 68, Santa Fe 64, and Farmington 64.",
    "By Friday and Saturday, rain chances jump again, up to 80 percent in Farmington and Santa Fe.",
    "Let me close with the key takeaways.",
    "If this update helped you, hit like and subscribe. Stay safe.",
]


def scenes(lines, seconds=6.0, lead=40):
    """Scenes of `seconds` each, after `lead` plain scenes so the forecast sits in the back of the video."""
    out, f = [], 0
    for k in range(lead):
        out.append({"id": f"p{k}", "startFrame": f, "durationInFrames": int(seconds * FPS), "text": "The river rose."})
        f += int(seconds * FPS)
    for k, t in enumerate(lines):
        out.append({"id": f"s{k}", "startFrame": f, "durationInFrames": int(seconds * FPS), "text": t})
        f += int(seconds * FPS)
    return out


class StyleTests(unittest.TestCase):
    def test_style_resolves_and_matches_the_reference_pacing(self):
        self.assertEqual(styles.resolve("severe_weather"), "severe_weather")
        self.assertEqual(styles.resolve("Severe weather update"), "")      # labels are not ids
        self.assertEqual(styles.resolve("severe-weather"), "severe_weather")
        cfg = styles.STYLES["severe_weather"]["config"]
        self.assertGreaterEqual(cfg["TARGET_SCENE_SECONDS"], 7.0)            # median 6.2-9.6 s measured
        self.assertLessEqual(cfg["SHOT_MAX_SECONDS"], 12.0)                  # the shot cap's ceiling
        self.assertFalse(cfg["MARKS_ENABLED"])
        self.assertEqual(cfg["IMAGE_MAX_PER_VIDEO"], 0)

    def test_apply_sets_crossfades_no_sfx_and_no_editing_v3(self):
        inp = {"video_style": "severe_weather"}
        self.assertEqual(styles.apply(inp), "severe_weather")
        self.assertEqual(inp["style"], "crossfade")
        self.assertIs(inp["sfx"], False)
        self.assertIs(inp["editing_v3"], False)
        self.assertEqual(inp["config"]["SHOT_MAX_SECONDS"], 12.0)


class ForecastTests(unittest.TestCase):
    def test_spoken_figures_are_only_what_the_line_says(self):
        self.assertEqual(severe.spoken_figures("Albuquerque reaches 68, Santa Fe 64, and Farmington 64."),
                         [("Albuquerque", 68), ("Santa Fe", 64), ("Farmington", 64)])
        self.assertEqual(severe.spoken_figures("up to 80 percent in Farmington"), [])
        self.assertEqual(severe.spoken_figures("Highway 64 west of Shiprock is closed"), [])

    def test_views_and_days(self):
        self.assertEqual(severe.view_of("Albuquerque reaches 68, Santa Fe 64"), "rain")   # no temperature word
        self.assertEqual(severe.view_of("highs near seventy, Albuquerque reaches 68"), "temp")
        self.assertEqual(severe.view_of("rain chances jump again, up to 80 percent"), "rain")
        self.assertEqual(severe.view_of("wind gusts of 60 mph"), "wind")
        self.assertEqual(severe.day_of("By Friday and Saturday, rain chances jump"), "FRIDAY")
        self.assertEqual(severe.day_of("the clearest days in nearly a week"), "")

    def test_the_block_covers_the_forecast_and_stops_before_the_sign_off(self):
        sc = scenes(LINES)
        blocks = severe.find_blocks(sc, FPS)
        self.assertEqual(len(blocks), 1)
        a, b = blocks[0]
        self.assertIn("day by day", sc[a]["text"].lower() + sc[a - 1]["text"].lower() + sc[a + 1]["text"].lower())
        self.assertIn("80 percent", sc[b]["text"])
        self.assertNotIn("takeaways", " ".join(s["text"] for s in sc[a:b + 1]))

    def test_no_block_in_the_opening(self):
        self.assertEqual(severe.find_blocks(scenes(LINES[3:12], lead=0) + scenes(["The river rose."] * 40, lead=0),
                                            FPS), [])

    def test_finish_keeps_only_the_maps_and_stamps_the_channel(self):
        sc = scenes(LINES)
        total = sc[-1]["startFrame"] + sc[-1]["durationInFrames"]
        doc = {"fps": FPS, "durationInFrames": total, "scenes": sc, "meta": {},
               "overlays": [{"type": "lib", "template": "LIB_VR_DATE_HERO", "startFrame": 30, "durationInFrames": 90},
                            {"type": "motion", "template": "LIB_WX_RAIN_BANDS", "variant": "wx-rain-bands", "startFrame": 60, "durationInFrames": 90}],
               "sfx": [{"name": "whoosh", "startFrame": 10}]}
        with mock.patch("src.geocode.resolve_all", return_value=[
                {"label": "Farmington, New Mexico", "lat": 36.73, "lon": -108.22, "kind": ""},
                {"label": "Albuquerque, New Mexico", "lat": 35.08, "lon": -106.65, "kind": ""},
                {"label": "Santa Fe, New Mexico", "lat": 35.69, "lon": -105.94, "kind": ""}]):
            rep = severe.finish(doc, {"video_style": "severe_weather", "channel_watermark": "  Storm  Desk "})
        self.assertNotIn("error", rep)
        self.assertEqual(rep["graphicsDropped"], 1)
        self.assertEqual(doc["channelMark"]["text"], "Storm Desk")
        self.assertEqual(doc["sfx"], [])
        views = [o for o in doc["overlays"] if o.get("severeForecast")]
        self.assertGreaterEqual(len(views), 2)
        self.assertTrue(all(o["plain"] is True and o["text"] == "" and o["variant"].startswith("wx-") for o in views))
        # Back to back, never overlapping.
        for x, y in zip(views, views[1:]):
            self.assertEqual(x["startFrame"] + x["durationInFrames"], y["startFrame"])
        temp = [o for o in views if o["template"] == "LIB_WX_TEMP"]
        self.assertTrue(temp and {i["label"]: i["value"] for i in temp[0]["items"]} ==
                        {"Albuquerque": 68, "Santa Fe": 64, "Farmington": 64})
        # Chips only name days the narration said.
        said = {"TODAY", "MONDAY", "TUESDAY", "WEDNESDAY", "FRIDAY", "SATURDAY", ""}
        self.assertTrue({o["label"] for o in views} <= said)

    def test_no_watermark_without_a_channel_name(self):
        self.assertIsNone(severe.channel_mark({}))
        self.assertIsNone(severe.channel_mark({"channel_watermark": False}))
        self.assertEqual(severe.channel_mark({"channel_watermark": {"text": "X", "opacity": 2}})["opacity"], 0.6)


if __name__ == "__main__":
    unittest.main()
