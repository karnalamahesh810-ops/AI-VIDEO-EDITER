"""
The owner's Las Vegas video (2026-10-05): every date / percent / number on its word as a clean KT look, no
look ending before its animation, map places in the story's country, overlay pictures that load, and the
"relook" action that puts all of it on a made timeline. Offline: no network, no bucket, no database.
"""
import copy
import io
import unittest
from unittest import mock

from src import datalooks as dl
from src import geocode, overlayimages, recut, relook

FPS = 30


def words_for(lines, gap=0.6, per_word=0.32):
    """[(t, "a line"), ...] -> timed words as the transcript gives them ('50 ,000', '27 %' split as TTS does)."""
    out = []
    for t, line in lines:
        for tok in line.split(" "):
            if not tok:
                continue
            out.append({"text": tok, "start": round(t, 3), "end": round(t + per_word - 0.02, 3)})
            t += per_word
    return out


def doc_for(lines, overlays=None, seconds=None):
    words = words_for(lines)
    end = seconds or (words[-1]["end"] + 8.0)
    total = int(end * FPS)
    scenes, step = [], 150
    for i in range(0, total, step):
        scenes.append({"id": f"s{i // step:04d}", "startFrame": i, "durationInFrames": min(step, total - i),
                       "text": "", "words": [w for w in words if i / FPS <= w["start"] < (i + step) / FPS],
                       "media": {"type": "video", "url": f"https://pub-x.r2.dev/projects/p/media/s{i}.mp4"}})
    return {"fps": FPS, "width": 1920, "height": 1080, "durationInFrames": total, "scenes": scenes,
            "overlays": overlays or [], "music": {"url": "m.mp3"}, "audio": {"url": "v.mp3"}, "sfx": [],
            "meta": {"story": {"places": ["Lake Mead", "Las Vegas, Nevada", "Lake Powell"]}}}


# Real lines of the Las Vegas script (project bd165068), as its transcript splits them.
LV = [
    (0.0, "A water intake built in 1970 sits in Lake Mead,"),
    (8.0, "It cannot draw a single drop. The lake that was built to cover it is less than 27 % full."),
    (46.7, "Nevada's cut is 50 ,000 acre feet a year."),
    (50.2, "Arizona's cut is 760 ,000 acre feet a year."),
    (54.9, "Read that again. The state next door loses more than 15 times"),
    (75.6, "The accusation is easy to picture. Lights on the strip at three in the morning."),
    (192.4, "can Las Vegas still run dry? A city of more than 2 million people sits at the end of one pipe system"),
    (278.2, "It was how much and from whom. On Friday, August 21, 2026,"),
    (677.3, "Irrigated agriculture accounts for 72 % of Arizona's total water consumption."),
    (691.5, "Nearly three of every four gallons the state uses goes onto land like that."),
    (1137.4, "the federal cut takes one. 25 million acre feet a year from the lower basin."),
]


def plan(lines):
    return dl.plan(words_for(lines), FPS)


class Coverage(unittest.TestCase):
    def test_every_date_percent_and_number_gets_its_look(self):
        looks, log = plan(LV)
        by = {}
        for o in looks:
            by.setdefault(o["template"], []).append(o)
        pct = [o for o in looks if o["template"] in (dl.KT_PERCENT, dl.KT_PROGRESS) and o.get("value") == 27]
        self.assertTrue(pct, "27 % has a ring")
        self.assertAlmostEqual(pct[0]["_at"], 8.0 + 0.32 * 17)              # on the word "27"
        self.assertTrue(any(o["template"] == dl.KT_MULTIPLIER and o["value"] == 15 for o in looks), "15 times")
        date = next(o for o in looks if o["template"] == dl.KT_DATE)
        self.assertEqual((date["text"], date["subtitle"], date["label"]), ("August 21", "2026", "FRIDAY"))
        self.assertTrue(any(o["template"] == dl.KT_TIME and o["text"] == "3 AM" for o in looks), "three in the morning")
        self.assertTrue(any(o["template"] in (dl.KT_YEAR, dl.KT_DATE) and "1970" in str(o.get("value", "")) +
                            str(o.get("subtitle", "")) for o in looks), "1970")
        people = next(o for o in looks if "2 million people" in o["said"])
        self.assertEqual((people["value"], people["suffix"]), (2, "MILLION"))
        self.assertIn("people", people["subtitle"].lower())
        cmp_ = next(o for o in looks if o["template"] == dl.KT_COMPARE)
        self.assertEqual([i["value"] for i in cmp_["items"]], [50000, 760000])
        self.assertEqual([i["label"] for i in cmp_["items"]], ["NEVADA", "ARIZONA"])
        # the comparison lands when its last value is said, never before
        self.assertGreaterEqual(cmp_["_at"], 50.2)
        share = next(o for o in looks if "three of every four" in o["said"])
        self.assertEqual((share["template"], share["value"], share["total"]), (dl.KT_PROGRESS, 3, 4))
        self.assertTrue(any(o["template"] in (dl.KT_PERCENT, dl.KT_PROGRESS) and o.get("value") == 72 for o in looks))
        # "one. 25 million" is the voice's 1.25 million
        cut = next(o for o in looks if "25 million" in o["said"])
        self.assertAlmostEqual(cut["value"], 1.25)

    def test_never_a_retired_look_and_never_the_same_style_twice_in_a_row(self):
        looks, _ = plan(LV)
        ids = [o["template"] for o in looks]
        self.assertFalse(set(ids) & dl.RETIRED_IDS)
        self.assertTrue(set(ids) <= set(dl.KT_IDS))
        for a, b in zip(ids, ids[1:]):
            if a == b:
                self.assertIn(a, (dl.KT_DATE, dl.KT_COMPARE))        # a calendar date keeps its own look
        for o in looks:
            self.assertEqual(o["variant"], dl.variant_of(o["template"]))

    def test_filler_and_repeats_are_skipped_and_close_ones_merge(self):
        looks, log = plan([(10.0, "One of the two great reservoirs held a couple of feet more."),
                           (20.0, "The lake is 27 % full."), (40.0, "Again, 27 % full."),
                           (300.0, "Today it is 27 % full."), (305.0, "It fell 50 feet and 2020 was the year.")])
        said = [o["said"] for o in looks]
        self.assertFalse(any("two" in s.lower() or "couple" in s.lower() for s in said))
        self.assertEqual(sum(1 for o in looks if o.get("value") == 27), 2)       # 20 s and 300 s, not 40 s
        self.assertTrue(any("shown" in (r.get("why") or "") for r in log))
        # "50 feet" and "2020" land within 2.5 s: one look
        late = [o for o in looks if o["_at"] >= 305.0]
        self.assertEqual(len(late), 1)


class NeverEndEarly(unittest.TestCase):
    def test_minimums_include_entry_landing_and_exit(self):
        self.assertGreaterEqual(dl.min_seconds({"type": "map", "template": "MAP_TRACE_V1"}), 5.5 + 0.9)
        self.assertGreaterEqual(dl.min_seconds({"template": "LIB_PR_DOC_SPOTLIGHT"}), 5.0 + 0.9)
        self.assertGreaterEqual(dl.min_seconds({"template": dl.KT_NUMBER}), 3.0 + 0.9)
        self.assertGreaterEqual(dl.min_seconds({"template": dl.KT_PERCENT}), 3.0 + 0.9)
        self.assertGreaterEqual(dl.min_seconds({"template": dl.KT_DATE}), 3.0 + 0.9)
        typed = dl.min_seconds({"template": dl.KT_STATEMENT, "text": "x" * 44})
        self.assertGreaterEqual(typed, 0.5 + 44 / dl.TYPE_CPS + 2.5 + 0.4 - 1e-6)

    def test_no_planned_overlay_is_shorter_than_its_minimum_or_overlaps(self):
        # a crowded stretch: a map, picture looks of 2.5 s, a date and numbers said close together
        over = [
            {"type": "map", "template": "MAP_DISTANCE_V1", "startFrame": 30 * 60, "durationInFrames": 105,
             "locations": [{"label": "Lake Mead", "lat": 36.25, "lon": -114.39}]},
            {"type": "motion", "template": "LIB_PX_POSTCARD", "startFrame": 30 * 64, "durationInFrames": 75,
             "text": "Colorado River"},
            {"type": "motion", "template": "LIB_PE_FRAME_DROP", "startFrame": 30 * 67, "durationInFrames": 75,
             "text": "Southern Nevada Water Authority"},
            {"type": "motion", "template": "LIB_ED_BOX_STACK", "startFrame": 30 * 125, "durationInFrames": 69,
             "text": "almost 15"},
            {"type": "motion", "template": "TEXT_KICKER_V1", "startFrame": 30 * 70, "durationInFrames": 60,
             "text": "The real story"},
        ]
        doc = doc_for(LV, overlays=copy.deepcopy(over), seconds=1160)
        rep = dl.finish(doc)
        self.assertEqual(dl.short_overlays(doc["overlays"], FPS), [])
        self.assertEqual(dl.overlapping(doc["overlays"]), [])
        self.assertEqual(rep["shortAfter"], 0)
        self.assertGreater(rep["shortBefore"], 0)
        for o in doc["overlays"]:
            self.assertGreaterEqual(o["durationInFrames"], dl.min_frames(o, FPS), o)
            self.assertLessEqual(o["startFrame"] + o["durationInFrames"], doc["durationInFrames"])
            self.assertNotIn(o["template"], dl.RETIRED_IDS)
            self.assertFalse(any(k.startswith("_") for k in o))
        m = next(o for o in doc["overlays"] if o["template"] == "MAP_DISTANCE_V1")
        self.assertGreaterEqual(m["durationInFrames"] / FPS, 6.4)

    def test_a_look_is_delayed_or_left_out_never_cut(self):
        a = {"type": "map", "template": "MAP_FOCUS_V1", "startFrame": 0, "durationInFrames": 90,
             "locations": [{"label": "Phoenix", "lat": 33.4, "lon": -112.0}]}
        b = {"type": "motion", "template": "LIB_PX_POSTCARD", "startFrame": 120, "durationInFrames": 90, "text": "x"}
        c = {"type": "motion", "template": "LIB_PX_VIEWFINDER", "startFrame": 150, "durationInFrames": 90, "text": "y"}
        placed, dropped = dl.schedule([a, b, c], FPS, 30 * 60)
        for o in placed:
            self.assertGreaterEqual(o["durationInFrames"], dl.min_frames(o, FPS))
        self.assertEqual(dl.overlapping(placed), [])
        self.assertTrue(dropped or len(placed) == 3)
        self.assertGreaterEqual(placed[0]["durationInFrames"], dl.min_frames(a, FPS))

    def test_the_end_of_the_video_never_cuts_a_look(self):
        late = {"type": "map", "template": "MAP_FOCUS_V1", "startFrame": 30 * 58, "durationInFrames": 90,
                "locations": [{"label": "Phoenix", "lat": 33.4, "lon": -112.0}]}
        placed, dropped = dl.schedule([late], FPS, 30 * 60)
        self.assertEqual(placed, [])
        self.assertEqual(dropped[0]["why"], "too close to the end of the video")


class Retired(unittest.TestCase):
    def test_retired_looks_become_their_clean_equivalent(self):
        self.assertEqual(dl.remap_retired({"template": "LIB_ED_WORD_BY_WORD", "text": "15 times"})["template"],
                         dl.KT_MULTIPLIER)
        box = dl.remap_retired({"template": "LIB_ED_BOX_STACK", "text": "almost 15", "startFrame": 9})
        self.assertEqual((box["template"], box["value"], box["label"], box["startFrame"]), (dl.KT_NUMBER, 15, "ALMOST", 9))
        pct = dl.remap_retired({"template": "LIB_BT_COUNT", "value": 72, "suffix": "%", "text": ""})
        self.assertEqual(pct["template"], dl.KT_PERCENT)
        self.assertEqual(dl.remap_retired({"template": "TEXT_TYPEWRITER_V1", "text": "It cannot draw a single drop"})
                         ["template"], dl.KT_STATEMENT)
        self.assertEqual(dl.remap_retired({"template": "TEXT_KICKER_V1", "text": "Arizona"})["template"], dl.KT_KEYWORD)
        self.assertIsNone(dl.remap_retired({"template": "MAP_TRACE_V1"}))


class _Reply:
    def __init__(self, hits):
        self.hits = hits

    def raise_for_status(self):
        pass

    def json(self):
        return self.hits


def _hit(lat, lon, cc, name, cls="boundary", typ="administrative"):
    return {"lat": str(lat), "lon": str(lon), "category": cls, "type": typ, "addresstype": "city",
            "display_name": name, "address": {"country_code": cc}}


# What Nominatim answers (the first hit first), by name; a countrycodes restriction keeps that country's hits.
WORLD = {
    "portland": [_hit(45.52, -122.68, "us", "Portland, Oregon"), _hit(43.66, -70.26, "us", "Portland, Maine"),
                 _hit(-38.34, 141.6, "au", "Portland, Victoria, Australia")],
    "springfield": [_hit(39.8, -89.64, "us", "Springfield, Illinois"), _hit(-27.68, 152.9, "au", "Springfield, QLD")],
    "perth": [_hit(-31.95, 115.86, "au", "Perth, Western Australia"), _hit(56.39, -3.43, "gb", "Perth, Scotland")],
    "victoria": [_hit(-37.0, 144.0, "au", "Victoria, Australia", "boundary", "state"),
                 _hit(48.43, -123.37, "ca", "Victoria, British Columbia, Canada")],
    "lake powell": [_hit(37.07, -111.24, "us", "Lake Powell, Utah", "natural", "water"),
                    _hit(-34.72, 142.93, "au", "Lake Powell, Victoria", "natural", "water")],
}


def fake_get(url, headers=None, params=None, timeout=None):
    name = str(params["q"]).split(",")[0].strip().lower()
    hits = WORLD.get(name, [])
    cc = params.get("countrycodes")
    if cc:
        hits = [h for h in hits if h["address"]["country_code"] == cc]
    return _Reply(hits)


class MapPlaces(unittest.TestCase):
    def setUp(self):
        geocode.reset_cache()
        self.p = [mock.patch.object(geocode, "_RATE_LIMIT_SECONDS", 0.0),
                  mock.patch.object(geocode.requests, "get", side_effect=fake_get)]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        geocode.reset_cache()

    def test_lake_mead_to_lake_powell_stays_in_the_us(self):
        line = "Look upstream, about 300 miles of river away, from Lake Mead to Lake Powell."
        got = geocode.resolve_all(["Lake Mead", "Lake Powell"], text=line,
                                  brief={"places": ["Lake Mead", "Las Vegas, Nevada"]})
        self.assertEqual([g["label"] for g in got], ["Lake Mead", "Lake Powell"])
        for g in got:
            self.assertTrue(30 < g["lat"] < 40 and -120 < g["lon"] < -105, g)
        geocode.requests.get.assert_not_called()           # the built-in gazetteer answers these

    def test_lake_powell_alone(self):
        got = geocode.resolve_all(["Lake Powell"], text="Lake Powell had fallen to 25 percent.")
        self.assertEqual((got[0]["lat"], got[0]["lon"]), (37.07, -111.24))
        # even without a story region the gazetteer never says Australia
        self.assertGreater(geocode.lookup("Lake Powell").lon, -120)

    def test_ambiguous_names_follow_the_story(self):
        us = {"places": ["Las Vegas, Nevada", "Phoenix"]}
        self.assertEqual(geocode.resolve_all(["Portland"], "Portland, Oregon", us)[0]["lat"], 45.52)
        self.assertEqual(geocode.resolve_all(["Springfield"], "the Illinois capital", us)[0]["lat"], 39.8)
        self.assertEqual(geocode.resolve_all(["Perth"], "Perth", {"places": ["Western Australia"], "event": "Australia drought"})
                         [0]["lat"], -31.95)
        self.assertEqual(geocode.resolve_all(["Victoria"], "Victoria on Vancouver Island", {"places": ["Canada"]})
                         [0]["lat"], 48.43)
        # Perth in a US story: no US Perth, so no map rather than Australia
        self.assertEqual(geocode.resolve_all(["Perth"], "", us), [])
        # a name that says its country is looked up there
        self.assertEqual(geocode.lookup("Perth, Australia").lat, -31.95)

    def test_points_that_cannot_be_one_path_drop_the_map(self):
        why = []
        far = geocode.resolve_all(["Portland", "Lake Mead"], "from Portland, Maine to Lake Mead",
                                  {"places": ["Nevada"]}, region="us", why=why)
        self.assertEqual(far, [])
        self.assertIn("km apart", why[0])
        # unless the narration says the distance
        ok = geocode.resolve_all(["Portland", "Lake Mead"], "the 1,300 miles from Portland to Lake Mead",
                                 {"places": ["Nevada"]}, region="us")
        self.assertEqual(len(ok), 2)
        mixed = geocode.sane([geocode.Place("A", 36, -114, country="us"), geocode.Place("B", -34, 142, country="au")])
        self.assertIn("different countries", mixed)
        # both countries named: allowed across the border, but still not as one 13,000 km path
        both = geocode.sane([geocode.Place("A", 36, -114, country="us"), geocode.Place("B", -34, 142, country="au")],
                            "the United States and Australia")
        self.assertIn("km apart", both)

    def test_relook_fixes_the_australian_path(self):
        doc = doc_for([(496.0, "Look upstream, about 300 miles of river away. Lake Mead to Lake Powell.")])
        doc["overlays"] = [{"type": "map", "template": "MAP_DISTANCE_V1", "startFrame": 14905, "durationInFrames": 180,
                            "text": "Lake Mead", "locations": [
                                {"kind": "canal", "label": "Lake Mead", "lat": 25.20382, "lon": 55.1483},
                                {"kind": "city_district", "label": "Lake Powell", "lat": -34.71517, "lon": 142.9339}]}]
        rep = relook.fix_maps(doc, brief=doc["meta"]["story"])
        self.assertEqual(rep["fixed"], 1)
        locs = doc["overlays"][0]["locations"]
        self.assertTrue(all(l["lon"] < -100 for l in locs))


def _png(w=640, h=480):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (w, h), (90, 120, 160)).save(b, "PNG")
    return b.getvalue()


class OverlayPictures(unittest.TestCase):
    def setUp(self):
        self.files = {
            "https://example.org/good.jpg": (_png(), "image/png"),
            "https://example.org/tiny.jpg": (_png(64, 64), "image/png"),
            "https://example.org/page.jpg": (b"<!DOCTYPE html><html>Forbidden</html>", "text/html"),
            "https://pub-x.r2.dev/projects/p1/media/s1.jpg": (_png(), "image/jpeg"),
            "https://example.org/source-page-picture.jpg": (_png(800, 600), "image/png"),
        }
        self.put_calls = []

    def fetch(self, url):
        if url not in self.files:
            raise OSError("404")
        return self.files[url]

    def put(self, data, key, ctype):
        self.put_calls.append(key)
        return "https://pub-x.r2.dev/" + key

    def test_check(self):
        self.assertTrue(overlayimages.check(_png())[0])
        self.assertFalse(overlayimages.check(_png(64, 64))[0])
        self.assertFalse(overlayimages.check(b"<html>no</html>", "text/html")[0])
        self.assertFalse(overlayimages.check(b"\xff\xd8\xff garbage")[0])

    def test_good_pictures_are_rehosted_bad_ones_replaced_or_text(self):
        ovs = [
            {"template": "LIB_PA_TILT_CARD", "startFrame": 0, "text": "Colorado River",
             "media": [{"type": "image", "url": "https://example.org/good.jpg"}]},
            {"template": "LIB_PB_ANNOTATED", "startFrame": 30, "text": "Allocations",
             "media": [{"type": "image", "url": "https://example.org/page.jpg",
                        "sourceUrl": "https://example.org/source-page-picture.jpg"}]},
            {"template": "LIB_PF_PROFILE", "startFrame": 60, "text": "Katie Hobbs", "subtitle": "Governor of Arizona",
             "media": [{"type": "image", "url": "/tmp/work/pod-x/wikipedia_KatieHobbs.jpg"}]},
            {"template": "LIB_PE_FOCUS_PULL", "startFrame": 90, "text": "Lake Mead",
             "media": [{"type": "image", "url": "https://example.org/tiny.jpg"}]},
            {"template": "LIB_PX_POSTCARD", "startFrame": 120, "text": "",
             "media": [{"type": "image", "url": "https://example.org/gone.jpg"}]},
        ]
        scenes = [{"id": "s1", "startFrame": 90, "media": {"type": "image",
                                                           "url": "https://pub-x.r2.dev/projects/p1/media/s1.jpg"}}]
        rep = overlayimages.fix(ovs, project_id="p1", scenes=scenes, fetch=self.fetch, put=self.put)
        self.assertEqual(ovs[0]["media"][0]["url"].split("/")[-3:-1], ["p1", "overlay"])
        self.assertTrue(ovs[1]["media"][0]["url"].startswith("https://pub-x.r2.dev/projects/p1/overlay/"))
        self.assertEqual((ovs[2]["template"], ovs[2]["text"], ovs[2]["label"]),
                         ("KT_LOWER_THIRD", "Katie Hobbs", "Governor of Arizona"))
        self.assertNotIn("media", ovs[2])
        self.assertEqual(ovs[3]["media"][0]["url"], "https://pub-x.r2.dev/projects/p1/media/s1.jpg")  # scene picture
        self.assertEqual(len(ovs), 5)
        self.assertEqual(rep["rehosted"], 1)
        self.assertEqual(rep["replaced"], 3)          # the source page's picture, then the scene picture (x2)
        self.assertEqual(rep["textOnly"], 1)
        # nothing to stand in and no words: left out, never shown broken
        lost = [{"template": "LIB_PX_POSTCARD", "startFrame": 0, "text": "",
                 "media": [{"type": "image", "url": "https://example.org/gone.jpg"}]}]
        self.assertEqual(overlayimages.fix(lost, project_id="p1", fetch=self.fetch, put=self.put)["dropped"], 1)
        self.assertEqual(lost, [])
        for o in ovs:
            for m in overlayimages.image_entries(o):
                self.assertTrue(m["url"].startswith("https://pub-x.r2.dev/projects/p1/"), o)

    def test_a_slow_server_never_costs_a_picture(self):
        import requests

        def slow(url):
            raise requests.exceptions.ReadTimeout("read timed out")
        ovs = [{"template": "CMP_SPLIT_V1", "startFrame": 0, "text": "x",
                "media": [{"type": "image", "url": "https://pub-x.r2.dev/projects/p1/split/1.jpg",
                           "sourceUrl": "https://example.org/good.jpg"}]}]
        rep = overlayimages.fix(ovs, project_id="p1", fetch=slow, put=self.put)
        self.assertEqual(ovs[0]["media"][0]["url"], "https://pub-x.r2.dev/projects/p1/split/1.jpg")
        self.assertEqual((rep["unchecked"], rep["replaced"]), (1, 0))

    def test_a_dry_run_changes_no_link(self):
        ovs = [{"template": "LIB_PA_TILT_CARD", "startFrame": 0, "text": "x",
                "media": [{"type": "image", "url": "https://example.org/good.jpg"}]}]
        rep = overlayimages.fix(ovs, project_id="p1", fetch=self.fetch, put=None)
        self.assertEqual(ovs[0]["media"][0]["url"], "https://example.org/good.jpg")
        self.assertEqual(rep["wouldRehost"], 1)
        self.assertEqual(self.put_calls, [])


class RelookAction(unittest.TestCase):
    def doc(self):
        d = doc_for(LV, overlays=[
            {"type": "motion", "template": "LIB_BT_COUNT", "startFrame": int(12.6 * FPS), "durationInFrames": 76,
             "value": 27, "suffix": "%", "text": ""},
            {"type": "motion", "template": "LIB_ED_BOX_STACK", "startFrame": int(125 * FPS), "durationInFrames": 69,
             "text": "almost 15"},
            {"type": "motion", "template": "LIB_PF_MAGAZINE", "startFrame": int(320 * FPS), "durationInFrames": 108,
             "text": "J.B. Hamby", "subtitle": "California Basin State Commissioner",
             "media": [{"type": "image", "url": "https://www.iid.com/home/showpublishedimage/6356/1"}]},
        ], seconds=1160)
        return d

    def fetch(self, url):
        raise OSError("403")

    def test_dry_run_returns_the_new_timeline_and_writes_nothing(self):
        doc = self.doc()
        before = copy.deepcopy(doc)
        with mock.patch.object(recut, "save_json") as save, mock.patch.object(recut, "write_project") as write:
            out = relook.run({"project_id": "bd165068-54dc-4f0e-97db-12665fe21eb2"}, doc, fetch=self.fetch)
        save.assert_not_called()
        write.assert_not_called()
        self.assertEqual(doc, before)                                    # the input is never changed
        self.assertTrue(out["ok"] and out["dry_run"])
        new = out["timeline"]
        for k in ("scenes", "music", "audio", "sfx", "durationInFrames"):
            self.assertEqual(new[k], before[k], k)
        ids = [o["template"] for o in new["overlays"]]
        self.assertFalse(set(ids) & dl.RETIRED_IDS)
        self.assertIn("KT_LOWER_THIRD", ids)                             # the 403 portrait
        s = out["summary"]
        self.assertGreaterEqual(s["addedPercents"], 2)
        self.assertGreaterEqual(s["addedDates"], 2)
        self.assertGreaterEqual(s["addedNumbers"], 3)
        self.assertEqual(s["shortAfter"], 0)
        self.assertEqual(s["overlapAfter"], 0)
        self.assertEqual(s["imagesTextOnly"], 1)
        self.assertEqual(out["fingerprint"], recut.fingerprint(before))

    def test_an_apply_needs_the_fingerprint_and_refuses_another_timeline(self):
        doc = self.doc()
        with self.assertRaises(relook.RelookError):
            relook.run({"project_id": "bd165068-54dc", "apply": True}, doc, fetch=self.fetch)
        with self.assertRaises(relook.RelookError):
            relook.run({"project_id": "bd165068-54dc", "apply": True, "expect_fingerprint": "00" * 32}, doc,
                       fetch=self.fetch)

    def test_an_apply_keeps_a_backup_then_writes_once(self):
        doc = self.doc()
        fp = recut.fingerprint(doc)
        with mock.patch.object(relook.r2, "enabled", return_value=True), \
                mock.patch.object(recut, "save_json", side_effect=lambda p, k, d: k) as save, \
                mock.patch.object(recut, "write_project", return_value=(True, "")) as write:
            out = relook.run({"project_id": "bd165068-54dc", "apply": True, "expect_fingerprint": fp,
                              "_job_id": "job1"}, doc, fetch=self.fetch, put=lambda d, k, c: "https://r2/" + k)
        self.assertTrue(out["written"])
        self.assertEqual(save.call_count, 2)
        self.assertIs(save.call_args_list[0].args[2], doc)               # the timeline as it was, first
        self.assertEqual(write.call_count, 1)
        self.assertEqual(write.call_args.kwargs["step"], "Graphics re-planned")

    def test_the_handler_runs_it(self):
        import handler
        doc = self.doc()
        with mock.patch.object(relook.overlayimages, "default_fetch", side_effect=OSError("offline")):
            out = handler.handler({"id": "j1", "input": {"action": "relook", "timeline": doc,
                                                         "project_id": "bd165068-54dc"}})
        self.assertTrue(out["ok"], out.get("error"))
        self.assertEqual(out["action"], "relook")
        self.assertTrue(out["dry_run"])


if __name__ == "__main__":
    unittest.main()
