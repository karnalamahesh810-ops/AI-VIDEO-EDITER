"""
Language versions (the owner, 2026-10-09): a finished video made again in another language - translated
fragment by fragment, voiced by our own voice endpoint, the finished timeline re-timed to the new voice.
Offline: the model, the voice endpoint and whisper are stand-ins; ffmpeg makes the stand-in audio.
"""
import base64
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import langversion as lv  # noqa: E402
from src import timeline  # noqa: E402

FPS = 30

LINES = [
    "On July 27, 2022,",
    "the water at Hoover Dam stood at 1 ,040 feet above sea level.",
    "",                                     # a silent scene (a teaser flash)
    "Full is 1 ,229, that gap is taller than a building,",
    "and it was all air. I have stood on the dam",
    "where the number is read every single day.",
]


def make_doc(lines=LINES, per_word=0.3, gap=0.5, lead=0.15, fps=FPS):
    """A finished video's document: one scene per line, its words `per_word` apart (seconds), a scene cut `lead`
    before its first word; "" = a silent scene of one second."""
    t = 0.0
    starts, scenes = [], []
    for i, text in enumerate(lines):
        words = []
        if text:
            first = t if i == 0 else t + lead
            if i == 0:
                starts.append(0.0)
            else:
                starts.append(t)
            w = first
            for tok in text.split():
                words.append({"text": tok, "start": round(w, 3), "end": round(w + per_word - 0.05, 3)})
                w += per_word
            t = w + (gap if lv.ends_sentence(text) else 0.05)
        else:
            starts.append(t)
            t += 1.0
        scenes.append({"id": f"s{i:04d}", "text": text, "words": words, "query": "q",
                       "media": {"type": "video", "url": f"https://r2.example/s{i}.mp4", "source": "youtube",
                                 "clipSeconds": 6.0},
                       "motion": "none", "transition": "none", "visualType": "footage"})
    total_s = t + 0.8
    total = int(round(total_s * fps))
    frames = [int(round(s * fps)) for s in starts]
    for i, sc in enumerate(scenes):
        sc["startFrame"] = frames[i]
        sc["durationInFrames"] = (frames[i + 1] if i + 1 < len(frames) else total) - frames[i]
    num_word = next(w for w in scenes[1]["words"] if w["text"] == "1")
    looks = [
        {"type": "motion", "variant": "kt-number", "template": "KT_NUMBER", "said": "1,040 feet above sea level",
         "value": 1040, "suffix": "FT", "label": "HOOVER DAM", "subtitle": "above sea level",
         "startFrame": int(round(num_word["start"] * fps)), "durationInFrames": 90},
        {"type": "motion", "variant": "kt-keyword", "template": "KT_KEYWORD", "text": "All Air",
         "highlight": "Air", "startFrame": scenes[4]["startFrame"] + 6, "durationInFrames": 60},
        {"type": "bullets", "text": "", "items": [{"label": "Arizona"}, {"label": "Nevada"}],
         "startFrame": scenes[5]["startFrame"], "durationInFrames": 45},
    ]
    return {
        "schemaVersion": 2, "fps": fps, "width": 1920, "height": 1080, "durationInFrames": total,
        "audio": {"url": "https://storage.example/narration.m4a", "volume": 1.0},
        "bgm": {"url": "bgm://investigative-20m", "volume": 0.5, "loop": True},
        "captions": {"enabled": False, "position": "bottom", "accent": "#EF4444", "fontFamily": "Inter",
                     "style": "netflix"},
        "music": {"duck": 0.8, "sections": [{"startFrame": 0, "endFrame": 2, "volume": 0, "mood": "INTRO"},
                                            {"startFrame": 2, "endFrame": total - 30, "volume": 0.5, "mood": "INTRO"},
                                            {"startFrame": total - 30, "endFrame": total, "volume": 0, "mood": "INTRO"}]},
        "scenes": scenes, "overlays": looks,
        "sfx": [{"kind": "transition", "name": "whoosh-soft-v2", "volume": 0.2,
                 "startFrame": scenes[3]["startFrame"] - 4, "durationFrames": 40}],
        "meta": {"voiceLufs": -20.0, "voiceLufsSource": "measured", "audioSource": "https://storage.example/n.m4a",
                 "audioBucket": "video-audio", "quality": {"summary": "old"}, "reportFor": "https://old.mp4",
                 "story": {"summary": "Lake Mead and its dam.", "places": ["Hoover Dam", "Lake Mead"]}},
    }


SPANISH = {
    "On July 27, 2022,": ("El 27 de julio de 2022,", "El veintisiete de julio de dos mil veintidós,"),
    "the water at Hoover Dam stood at 1,040 feet above sea level.":
        ("el agua de la presa Hoover estaba a 1.040 pies sobre el nivel del mar.",
         "el agua de la presa Hoover estaba a mil cuarenta pies sobre el nivel del mar."),
    "Full is 1,229, that gap is taller than a building,":
        ("Lleno es 1.229, esa diferencia es más alta que un edificio,",
         "Lleno es mil doscientos veintinueve, esa diferencia es más alta que un edificio,"),
    "and it was all air. I have stood on the dam": ("y todo era aire. He estado en la presa",
                                                     "y todo era aire. He estado en la presa"),
    "where the number is read every single day.": ("donde se lee el número cada día.",
                                                     "donde se lee el número cada día."),
}


class FakeChat:
    """The model: Spanish from a table; can drop a number once (to test the second ask) or a fragment."""

    def __init__(self, lose_number_once=False, drop_fragment=None):
        self.calls = []
        self.lose = lose_number_once
        self.drop = drop_fragment

    def __call__(self, system, payload, kind="translate", **_kw):
        self.calls.append((kind, payload))
        if kind == "glossary":
            return {"glossary": {t: ("presa Hoover" if t == "Hoover Dam" else t) for t in payload["terms"]}}
        if kind == "screen_text":
            out = []
            for it in payload["items"]:
                text = it["text"]
                tr = {"FT": "PIES", "HOOVER DAM": "PRESA HOOVER", "above sea level": "sobre el nivel del mar",
                      "All Air": "Todo Aire", "Air": "Aire", "Arizona": "Arizona", "Nevada": "Nevada"}.get(text, "ES " + text)
                out.append({"id": it["id"], "text": tr})
            return {"items": out}
        rows = []
        for group in payload["groups"]:
            for frag in group:
                src = frag["text"]
                if src not in SPANISH and len(group) == 1:          # a whole group asked as one text
                    rows.append({"i": frag["i"], "text": "ES " + src, "say": "ES " + src})
                    continue
                text, say = SPANISH[src]
                if self.lose and "note" not in payload and "1.040" in text:
                    text = text.replace("1.040", "mil")
                if self.drop is not None and frag["i"] == self.drop and "note" not in payload:
                    continue
                rows.append({"i": frag["i"], "text": text, "say": say})
        return {"fragments": rows}


class Fragments(unittest.TestCase):
    def test_one_fragment_a_scene_groups_end_on_sentences(self):
        doc = make_doc()
        frags = lv.fragments_of(doc)
        self.assertEqual(len(frags), len(doc["scenes"]))
        self.assertFalse(frags[2].spoken)
        self.assertEqual(frags[1].text, "the water at Hoover Dam stood at 1,040 feet above sea level.")
        groups = lv.group_fragments(frags)
        # "On July 27, 2022," runs into the next scene's sentence, "...I have stood on the dam" into the last
        # one's; the silent scene belongs to no group.
        self.assertEqual(groups, [[0, 1], [3, 4, 5]])
        self.assertEqual(frags[2].group, -1)

    def test_a_long_run_without_a_sentence_end_is_still_closed(self):
        frags = [lv.Fragment(scene=i, text="and then more words", words=[{"text": "x", "start": i, "end": i + .5}])
                 for i in range(25)]
        groups = lv.group_fragments(frags, max_frags=10)
        self.assertEqual([len(g) for g in groups], [10, 10, 5])


class Numbers(unittest.TestCase):
    def test_values_across_writing_styles(self):
        self.assertEqual(lv.numbers_in("stood at 1 ,040 feet"), ["1040"])
        self.assertEqual(lv.numbers_in("a 1.040 pies, en 2022"), ["1040", "2022"])
        self.assertEqual(lv.numbers_in("3,5 metros y 3.5 metros"), ["3.5", "3.5"])
        self.assertEqual(lv.numbers_in("25 millones de personas"), ["25"])
        self.assertEqual(lv.numbers_in("1 040 pieds"), ["1040"])

    def test_missing_numbers(self):
        self.assertEqual(lv.numbers_match("On July 27, 2022,", "El 27 de julio de 2022,"), [])
        self.assertEqual(lv.numbers_match("stood at 1 ,040 feet", "estaba a mil pies"), ["1040"])
        self.assertEqual(lv.numbers_match("15 and 15", "15"), ["15"])


class Translation(unittest.TestCase):
    def setUp(self):
        self.doc = make_doc()
        self.frags = lv.fragments_of(self.doc)
        self.groups = lv.group_fragments(self.frags)

    def test_every_spoken_fragment_gets_its_own_translation(self):
        chat = FakeChat()
        rep = lv.translate(self.frags, self.groups, "es", chat=chat)
        self.assertEqual(self.frags[0].out, "El 27 de julio de 2022,")
        self.assertIn("mil cuarenta", self.frags[1].say)
        self.assertEqual(self.frags[2].out, "")
        self.assertEqual(rep["numberIssues"], [])
        self.assertEqual(rep["retried"], 0)

    def test_a_lost_number_is_asked_again_and_the_whole_group_replaced(self):
        chat = FakeChat(lose_number_once=True)
        rep = lv.translate(self.frags, self.groups, "es", chat=chat)
        self.assertEqual(rep["retried"], 1)
        self.assertIn("1.040", self.frags[1].out)
        self.assertEqual(rep["numberIssues"], [])
        again = [p for k, p in chat.calls if k == "translate" and "note" in p]
        self.assertEqual(len(again), 1)
        self.assertIn("1040", again[0]["note"])

    def test_a_fragment_that_repeats_itself_is_asked_again(self):
        class Twice(FakeChat):
            def __call__(self, system, payload, kind="translate", **kw):
                out = super().__call__(system, payload, kind, **kw)
                if kind == "translate" and "note" not in payload:
                    for r in out["fragments"]:
                        if r["i"] == 5:
                            r["text"] = r["say"] = " ".join([r["text"]] * 4)
                return out
        chat = Twice()
        rep = lv.translate(self.frags, self.groups, "es", chat=chat)
        self.assertEqual(rep["retried"], 1)
        self.assertEqual(self.frags[5].out, "donde se lee el número cada día.")
        self.assertIn("length", [p for k, p in chat.calls if k == "translate" and "note" in p][0]["note"])

    def test_a_fragment_missing_twice_is_translated_whole_and_split(self):
        class Never(FakeChat):
            def __call__(self, system, payload, kind="translate", **kw):
                out = super().__call__(system, payload, kind, **kw)
                if kind == "translate" and len(payload["groups"]) == 1 and len(payload["groups"][0]) == 1:
                    return out
                if kind == "translate":
                    out["fragments"] = [r for r in out["fragments"] if r["i"] != 4]
                return out
        rep = lv.translate(self.frags, self.groups, "es", chat=Never())
        self.assertEqual(rep["split"], 1)
        self.assertTrue(self.frags[3].out and self.frags[4].out)
        joined = self.frags[3].out + " " + self.frags[4].out
        self.assertTrue(joined.startswith("ES Full is"))

    def test_split_like_keeps_every_word_once(self):
        pieces = lv._split_like("uno dos tres cuatro cinco seis", ["aaaa", "aaaaaaaa"])
        self.assertEqual(len(pieces), 2)
        self.assertEqual(" ".join(pieces), "uno dos tres cuatro cinco seis")
        self.assertTrue(all(pieces))


class ScreenText(unittest.TestCase):
    def test_looks_translated_numbers_kept_highlight_checked(self):
        doc = make_doc()
        frags = lv.fragments_of(doc)
        lv.group_fragments(frags)
        lv.translate(frags, lv.group_fragments(frags), "es", chat=FakeChat())
        rep = lv.translate_screen_text(doc, frags, "es", chat=FakeChat())
        num, kw, bullets = doc["overlays"]
        self.assertEqual(num["suffix"], "PIES")
        self.assertEqual(num["label"], "PRESA HOOVER")
        self.assertEqual(num["value"], 1040)                 # numbers are not text
        self.assertEqual(kw["text"], "Todo Aire")
        self.assertEqual(kw["highlight"], "Aire")            # inside its own text: kept
        self.assertEqual(bullets["items"][0]["label"], "Arizona")
        self.assertGreaterEqual(rep["translated"], 5)

    def test_a_changed_number_keeps_the_source_text_and_a_lost_highlight_is_dropped(self):
        doc = make_doc()
        doc["overlays"][1]["text"] = "Since 1937"
        doc["overlays"][1]["highlight"] = "1937"     # no letters: not display text, kept as it is

        def chat(system, payload, kind="screen_text", **_kw):
            return {"items": [{"id": it["id"], "text": "Desde 1938" if it["text"] == "Since 1937" else "ES"}
                              for it in payload["items"]]}
        lv.translate_screen_text(doc, [], "es", chat=chat)
        self.assertEqual(doc["overlays"][1]["text"], "Since 1937")
        doc2 = make_doc()

        def chat2(system, payload, kind="screen_text", **_kw):
            return {"items": [{"id": it["id"], "text": "Brillo" if it["field"] == "highlight" else "Todo aire"}
                              for it in payload["items"]]}
        rep = lv.translate_screen_text(doc2, [], "es", chat=chat2)
        self.assertEqual(doc2["overlays"][1]["highlight"], "")
        self.assertEqual(rep["highlightsDropped"], 1)

    def test_display_fields_are_found_in_data_geo_and_animation_scenes(self):
        doc = make_doc()
        doc["overlays"].append({"type": "motion", "variant": "rd-line", "startFrame": 0, "durationInFrames": 30,
                                "data": {"title": "LAKE MEAD", "kicker": "ELEVATION", "unit": "FT", "source": "USBR",
                                         "delta": {"text": "-158 FT SINCE 2001"}, "refs": [{"label": "Dead pool",
                                                                                             "value": 895}]},
                                "geo": {"kind": "lake", "name": "mead", "label": "Lake Mead", "bbox": [0, 0, 1, 1],
                                        "pins": [{"label": "Hoover Dam", "lat": 36, "lon": -114}]}})
        doc["scenes"][0]["animation"] = {"type": "stat", "text": "Record low", "value": 1040}
        ids = {it["id"] for it in lv.screen_texts(doc)}
        for want in ("o3.data.title", "o3.data.kicker", "o3.data.unit", "o3.data.delta.text", "o3.data.refs0.label",
                     "o3.geo.label", "o3.geo.pins0.label", "s0.animation.text"):
            self.assertIn(want, ids)
        self.assertNotIn("o3.data.source", ids)              # an agency's short name stays


class Parts(unittest.TestCase):
    def test_parts_cut_between_sentences_with_paragraphs_after_long_pauses(self):
        doc = make_doc(gap=1.4)
        frags = lv.fragments_of(doc)
        groups = lv.group_fragments(frags)
        lv.translate(frags, groups, "es", chat=FakeChat())
        parts = lv.plan_parts(frags, groups, "es", max_chars=10_000)
        self.assertEqual(len(parts), 1)
        self.assertIn("\n\n", parts[0].text)                   # a 1.4 s pause in the source: a paragraph
        self.assertIn("mil cuarenta", parts[0].text)           # the spoken form goes to the voice
        small = lv.plan_parts(frags, groups, "es", max_chars=60)
        self.assertEqual(sum(len(p.frags) for p in small), 5)
        self.assertGreater(len(small), 1)

    def test_chinese_goes_one_sentence_a_line(self):
        frags = [lv.Fragment(scene=0, text="One.", words=[{"text": "One.", "start": 0, "end": .4}],
                             out="一。", say="第一句话。第二句话，很长。"),
                 lv.Fragment(scene=1, text="Two.", words=[{"text": "Two.", "start": 1, "end": 1.4}],
                             out="二。", say="第三句话。")]
        groups = lv.group_fragments(frags)
        parts = lv.plan_parts(frags, groups, "zh", max_chars=1000)
        self.assertEqual(parts[0].text.split("\n"), ["第一句话。", "第二句话，很长。", "第三句话。"])

    def test_voice_request(self):
        part = lv.Part(index=0, frags=[0], text="Hola.")
        body = lv.voice_body(part, "es", {"b64": "QUJD", "text": "abc", "key": "narration-1", "extra": 1}, seed=7)
        self.assertEqual(body["language"], "es")
        self.assertEqual(body["voice"], {"b64": "QUJD", "text": "abc", "key": "narration-1"})
        self.assertEqual(body["tail_pause"], 0.0)
        self.assertEqual(body["return"], "url")
        self.assertEqual(body["max_attempts"], 2)
        self.assertEqual(lv.voice_body(part, "ru", {"url": "https://x"}, seed=7)["max_attempts"], 1)


class Alignment(unittest.TestCase):
    def test_words_timed_by_what_whisper_heard(self):
        frags = [lv.Fragment(scene=0, text="a", words=[{"text": "a", "start": 0, "end": 1}],
                             out="el agua estaba a 1.040 pies."),
                 lv.Fragment(scene=1, text="b", words=[{"text": "b", "start": 1, "end": 2}], out="Lleno es aire.")]
        heard = [{"text": t, "start": s, "end": s + 0.3} for t, s in
                 (("El", 0.2), ("agua", 0.5), ("estaba", 0.9), ("a", 1.3), ("mil", 1.5), ("cuarenta", 1.9),
                  ("pies.", 2.4), ("Lleno", 3.4), ("es", 3.8), ("aire.", 4.1))]
        rep = lv.align(frags, heard, "es")
        self.assertEqual([w["text"] for w in frags[0].new_words], ["el", "agua", "estaba", "a", "1.040", "pies."])
        self.assertAlmostEqual(frags[0].new_words[0]["start"], 0.2)
        num = frags[0].new_words[4]
        self.assertGreaterEqual(num["start"], 1.5 - 1e-6)     # spread over "mil cuarenta"
        self.assertLessEqual(num["end"], 2.2 + 1e-6)
        self.assertAlmostEqual(frags[1].new_start, 3.4)
        self.assertEqual(rep["byFragment"][1], 1.0)
        self.assertLess(rep["ratio"], 1.0)

    def test_chinese_by_character(self):
        frags = [lv.Fragment(scene=0, text="a", words=[{"text": "a", "start": 0, "end": 1}], out="湖水下降了。")]
        heard = [{"text": "湖水", "start": 0.0, "end": 0.6}, {"text": "下降了。", "start": 0.6, "end": 1.5}]
        lv.align(frags, heard, "zh")
        self.assertEqual("".join(w["text"] for w in frags[0].new_words), "湖水下降了。")
        self.assertAlmostEqual(frags[0].new_words[2]["start"], 0.6)


def retimed(doc, scale=1.25, shift=0.4):
    """Every fragment translated (its own text) and its words placed `scale` x later than before, plus `shift`."""
    frags = lv.fragments_of(doc)
    lv.group_fragments(frags)
    for f in frags:
        if f.spoken:
            f.out = f.text
            f.new_words = [{"text": w["text"], "start": round(shift + w["start"] * scale, 3),
                            "end": round(shift + w["end"] * scale, 3)} for w in f.words]
    total = doc["durationInFrames"] / doc["fps"] * scale + shift
    return frags, total


class Retime(unittest.TestCase):
    def test_scenes_follow_their_new_words_and_tile_the_new_narration(self):
        doc = make_doc()
        frags, total = retimed(doc)
        new, rep = lv.retime(doc, frags, total)
        timeline.validate(new, require_media=True, allow_stock=True)
        self.assertEqual(new["durationInFrames"], int(round(total * FPS)))
        s = new["scenes"]
        self.assertEqual(s[0]["startFrame"], 0)
        for i in (1, 3, 4, 5):
            first = frags[i].new_start
            lead = min(lv.LEAD_MAX, frags[i].start - doc["scenes"][i]["startFrame"] / FPS)
            self.assertAlmostEqual(s[i]["startFrame"] / FPS, first - lead, delta=1.5 / FPS)
        # The silent scene sits between its neighbours, by the old clock.
        self.assertLess(s[1]["startFrame"], s[2]["startFrame"])
        self.assertLess(s[2]["startFrame"], s[3]["startFrame"])
        self.assertEqual(s[1]["words"], frags[1].new_words)
        self.assertEqual(s[1]["sourceText"], frags[1].text)
        self.assertAlmostEqual(rep["stretch"], 1.25, delta=0.1)

    def test_the_original_document_is_not_changed(self):
        doc = make_doc()
        before = json.dumps(doc, sort_keys=True)
        frags, total = retimed(doc)
        lv.retime(doc, frags, total)
        self.assertEqual(json.dumps(doc, sort_keys=True), before)

    def test_a_number_look_lands_on_its_number_in_the_new_order(self):
        doc = make_doc()
        frags, total = retimed(doc)
        # The new language says the number at the END of its line (another word order).
        f1 = frags[1]
        num = next(w for w in f1.new_words if w["text"] in ("1", "1,040"))
        last = f1.new_words[-1]
        num_start = last["start"] + 0.1
        f1.new_words = [w for w in f1.new_words if w is not num] + [{"text": "1.040", "start": num_start,
                                                                       "end": num_start + 0.3}]
        f1.new_words.sort(key=lambda w: w["start"])
        new, rep = lv.retime(doc, frags, total + 1)
        look = new["overlays"][0]
        self.assertAlmostEqual(look["startFrame"] / FPS, num_start, delta=0.5)
        self.assertGreaterEqual(rep["looksOnTheirWord"], 1)

    def test_sounds_music_and_looks_follow_the_warp(self):
        doc = make_doc()
        frags, total = retimed(doc)
        new, _ = lv.retime(doc, frags, total)
        cut = new["scenes"][3]["startFrame"]
        self.assertAlmostEqual(new["sfx"][0]["startFrame"], cut - 5, delta=3)
        secs = new["music"]["sections"]
        self.assertEqual(secs[0]["startFrame"], 0)
        self.assertEqual(secs[-1]["endFrame"], new["durationInFrames"])
        self.assertTrue(all(a["endFrame"] <= b["startFrame"] for a, b in zip(secs, secs[1:])))
        for ov in new["overlays"]:
            self.assertGreaterEqual(ov["durationInFrames"], 1)
            self.assertLessEqual(ov["startFrame"] + ov["durationInFrames"], new["durationInFrames"])
        # A look keeps at least its length when it is stretched.
        self.assertGreaterEqual(new["overlays"][0]["durationInFrames"], doc["overlays"][0]["durationInFrames"])

    def test_a_shorter_language_trims_scenes_but_never_below_the_floor(self):
        doc = make_doc()
        frags, total = retimed(doc, scale=0.6, shift=0.0)
        new, rep = lv.retime(doc, frags, total)
        timeline.validate(new, require_media=True, allow_stock=True)
        self.assertTrue(all(s["durationInFrames"] >= int(0.4 * FPS) - 1 for s in new["scenes"]))
        self.assertLess(rep["stretch"], 1.0)

    def test_two_looks_that_did_not_overlap_never_do(self):
        doc = make_doc()
        a, b = doc["overlays"][1], doc["overlays"][2]
        a["durationInFrames"] = b["startFrame"] - a["startFrame"]          # back to back
        frags, total = retimed(doc, scale=1.0, shift=0.0)
        # The second look's scene comes much earlier in the new language.
        for w in frags[5].new_words:
            w["start"] -= 0.6
            w["end"] -= 0.6
        new, _ = lv.retime(doc, frags, total)
        na, nb = new["overlays"][1], new["overlays"][2]
        self.assertLessEqual(na["startFrame"] + na["durationInFrames"], nb["startFrame"] + 1)

    def test_warp_is_linear_between_anchors_and_extends_at_the_ends(self):
        w = lv.Warp([0, 10, 20], [0, 12, 30])
        self.assertAlmostEqual(w(5), 6)
        self.assertAlmostEqual(w(15), 21)
        self.assertAlmostEqual(w(22), 33.6)


class VoiceSample(unittest.TestCase):
    def test_whole_sentences_without_figures(self):
        words, t = [], 0.0
        script = ("Lake Mead was full in 1983. " + "The water rose every spring and the boats came back. " * 4 +
                  "Then the long drought began and nobody stopped it.")
        for tok in script.split():
            words.append({"text": tok, "start": round(t, 2), "end": round(t + 0.3, 2)})
            t += 0.35
        frags = [lv.Fragment(scene=0, text=script, words=words)]
        a, b, text = lv.pick_sample(frags)
        self.assertNotIn("1983", text)
        self.assertTrue(text.endswith("."))
        self.assertTrue(10.0 <= b - a <= 24.0)
        self.assertTrue(text[0].isupper())

    def test_no_window_none(self):
        frags = [lv.Fragment(scene=0, text="Hi.", words=[{"text": "Hi.", "start": 0, "end": 0.3}])]
        self.assertIsNone(lv.pick_sample(frags))


class Refusals(unittest.TestCase):
    def test_never_the_source_row_never_a_presenter_never_its_own_language(self):
        doc = make_doc()
        with self.assertRaises(lv.LanguageError):
            lv.check_input({"project_id": "p1", "source_project_id": "p1", "language": "es"}, doc)
        with self.assertRaises(lv.LanguageError):
            lv.check_input({"project_id": "p2", "source_project_id": "p1", "language": "hi"}, doc)
        with self.assertRaises(lv.LanguageError):
            lv.check_input({"project_id": "p2", "source_project_id": "p1", "language": "en"}, doc)
        pres = make_doc()
        pres["scenes"][1]["media"]["source"] = "ai-presenter"
        with self.assertRaises(lv.LanguageError):
            lv.check_input({"project_id": "p2", "source_project_id": "p1", "language": "es"}, pres)
        self.assertEqual(lv.check_input({"project_id": "p2", "source_project_id": "p1", "language": "ES"}, doc), "es")
        version = make_doc()
        version["meta"]["languageVersion"] = {"language": "es"}
        self.assertEqual(lv.check_input({"project_id": "p3", "source_project_id": "p2", "language": "en"},
                                        version), "en")

    def test_titles_and_keys(self):
        self.assertEqual(lv.strip_language_suffix("Lake Mead (Español)"), "Lake Mead")
        self.assertEqual(lv.strip_language_suffix("Lake Mead"), "Lake Mead")
        self.assertEqual(lv.narration_key("p9", "es", "projects/p9/narration-es-abc.mp3"),
                         "projects/p9/narration-es-abc.mp3")
        self.assertTrue(lv.narration_key("p9", "es", "projects/OTHER/x.mp3").startswith("projects/p9/narration-es-"))


def _tone(path, seconds):
    subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-t", f"{seconds:.3f}",
                    "-i", "sine=frequency=220:sample_rate=24000", "-c:a", "libmp3lame", "-b:a", "64k", path],
                   check=True, capture_output=True, timeout=60)


class FakeServer:
    """The voice endpoint: a tone as long as the words, and what it was asked (to hear it back)."""

    def __init__(self, per_word=0.32):
        self.per_word = per_word
        self.asked = []
        self.jobs = []
        self.tmp = tempfile.mkdtemp()

    def voice(self, body, timeout):
        n = len(body["text"].split())
        seconds = max(0.5, n * self.per_word)
        path = os.path.join(self.tmp, f"p{len(self.asked)}.mp3")
        _tone(path, seconds)
        self.asked.append((body, seconds))
        self.jobs.append({"id": str(len(self.asked)), "delayMs": 1000.0, "executionMs": 2000.0})
        with open(path, "rb") as fh:
            return {"ok": True, "audio_b64": base64.b64encode(fh.read()).decode(), "seconds": seconds}

    def gpu_seconds(self):
        return round(sum(j["delayMs"] + j["executionMs"] for j in self.jobs) / 1000.0, 1)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is needed for the stand-in audio")
class WholeVersion(unittest.TestCase):
    def test_prepare_makes_a_valid_document_in_the_new_language(self):
        doc = make_doc()
        work = tempfile.mkdtemp()
        narration = os.path.join(work, "src.mp3")
        _tone(narration, doc["durationInFrames"] / FPS)
        server = FakeServer()

        def transcribe(path, lang):
            # What whisper would hear: each part's spoken words spread over its tone, laid out as joined.
            out, t = [], None
            lead = 0.1
            t = lead
            for body, seconds in server.asked[-len(server.asked):]:
                toks = body["text"].split()
                step = seconds / max(1, len(toks))
                for k, tok in enumerate(toks):
                    out.append({"text": tok, "start": t + k * step, "end": t + (k + 1) * step - 0.02})
                t += seconds + 0.45
            return out
        reports = []
        inp = {"project_id": "new", "source_project_id": "src", "language": "es", "title": "Lake Mead (Español)",
               "source_audio_path": narration}
        with mock.patch.object(lv, "clone_sample", return_value={"b64": "QUJD", "text": "Hi.", "key": "k",
                                                                    "seconds": 12.0, "from": 1.0, "to": 13.0}):
            new, info, path = lv.prepare(inp, doc, work, lambda step, pct=None, **_: reports.append(step),
                                         server=server, transcribe=transcribe, chat=FakeChat())
        timeline.validate(new, require_media=True, allow_stock=True)
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(info["language"], "es")
        self.assertEqual(info["voice"], "clone")
        self.assertEqual(info["numberIssues"], [])
        self.assertEqual(new["scenes"][0]["text"], "El 27 de julio de 2022,")
        self.assertEqual(new["overlays"][0]["suffix"], "PIES")
        self.assertTrue(any(s.startswith("Translating") for s in reports))
        self.assertTrue(any(s.startswith("Voicing") for s in reports))
        self.assertTrue(any(s.startswith("Matching") for s in reports))
        # One voice request, the clone inline, the same seed for every part.
        body = server.asked[0][0]
        self.assertEqual(body["voice"]["b64"], "QUJD")
        self.assertEqual(body["language"], "es")
        final = lv.finish_doc(new, info, "https://r2.example/narration-es.mp3", captions=True, lufs=-19.6)
        self.assertEqual(final["audio"]["url"], "https://r2.example/narration-es.mp3")
        self.assertEqual(final["meta"]["audioSource"], "https://r2.example/narration-es.mp3")
        self.assertTrue(final["captions"]["enabled"])
        self.assertNotIn("quality", final["meta"])
        self.assertNotIn("reportFor", final["meta"])
        self.assertEqual(final["meta"]["languageVersion"]["language"], "es")
        self.assertEqual(final["meta"]["voiceLufs"], -19.6)
        # The source document is untouched.
        self.assertEqual(doc["scenes"][0]["text"], "On July 27, 2022,")


class Handler(unittest.TestCase):
    def test_the_job_writes_only_the_new_project_and_renders_the_new_document(self):
        import handler
        doc = make_doc()
        new_doc = copy.deepcopy(doc)
        new_doc["meta"]["languageVersion"] = {"language": "es"}
        info = {"language": "es", "from": "en", "voice": "clone", "lufs": -20.0, "numberIssues": [],
                "translatedTitle": "Lago Mead"}
        writes = []
        renders = []

        def patch(pid, fields, wait=False):
            writes.append((pid, sorted(fields)))
            return True

        def render(d, inp, work, report, split=False):
            renders.append((d["audio"]["url"], inp["audio_url"], split))
            return {"video_url": "https://r2.example/final.mp4", "duration": 12.0, "quality": {"summary": "ok"}}
        job = {"id": "job-1", "input": {"action": "translate_version", "project_id": "NEW", "source_project_id": "SRC",
                                        "language": "es", "timeline": doc, "title": "T (Español)", "captions": True}}
        with mock.patch.object(handler.langversion, "prepare", return_value=(new_doc, info, "/tmp/n.mp3")), \
                mock.patch.object(handler, "_store_version_narration", return_value="https://r2.example/n-es.mp3"), \
                mock.patch.object(handler, "do_render", side_effect=render), \
                mock.patch.object(handler.storage, "patch_project", side_effect=patch), \
                mock.patch.object(handler.storage, "broker_events"), \
                mock.patch.object(handler, "_require_openrouter_credit"), \
                mock.patch.object(handler.fanout, "render_enabled", return_value=False):
            out = handler.handler(job)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["action"], "translate_version")
        self.assertEqual(out["audio_url"], "https://r2.example/n-es.mp3")
        self.assertEqual(out["video_url"], "https://r2.example/final.mp4")
        self.assertEqual({pid for pid, _ in writes}, {"NEW"})
        # The new timeline is saved before the render, the done fields after it.
        saved = [i for i, (_, f) in enumerate(writes) if "scene_data" in f]
        done = [i for i, (_, f) in enumerate(writes) if "video_url" in f]
        self.assertTrue(saved and done and saved[0] < done[-1])
        self.assertEqual(renders, [("https://r2.example/n-es.mp3", "https://r2.example/n-es.mp3", False)])
        self.assertTrue(out["timeline"]["captions"]["enabled"])

    def test_a_job_naming_the_source_as_its_project_fails_without_writing_it(self):
        import handler
        writes = []
        job = {"id": "job-2", "input": {"action": "translate_version", "project_id": "SRC",
                                        "source_project_id": "SRC", "language": "es", "timeline": make_doc()}}
        with mock.patch.object(handler.storage, "patch_project",
                               side_effect=lambda pid, fields, wait=False: writes.append((pid, fields))), \
                mock.patch.object(handler, "_require_openrouter_credit"):
            out = handler.handler(job)
        self.assertFalse(out["ok"])
        self.assertIn("new project", out["error"])
        # Nothing at all: not even the job's "rendering" / "failed" status, which would hide the source's video.
        self.assertEqual(writes, [])


class Glossary(unittest.TestCase):
    def test_name_runs_stop_at_sentences_commas_and_and(self):
        runs = lv._capital_runs("Lately the Colorado River Compact of 1922 said so. Phoenix and Los Angeles, the "
                                "Bureau of Reclamation agreed. Rose of servers stood there. On July 27 Mexico. Lately")
        self.assertIn("Colorado River Compact", runs)
        self.assertIn("Los Angeles", runs)
        self.assertIn("Bureau of Reclamation", runs)
        self.assertNotIn("Phoenix and Los Angeles", runs)
        self.assertNotIn("Rose", runs)                      # only ever the first word of a sentence
        self.assertFalse(any(k.startswith(("On", "July", "Lately")) for k in runs))

    def test_terms_lead_with_the_story_places(self):
        doc = make_doc()
        terms = lv.glossary_terms(doc, lv.fragments_of(doc))
        self.assertEqual(terms[:2], ["Hoover Dam", "Lake Mead"])


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is needed")
class Loudness(unittest.TestCase):
    def test_a_narration_short_of_its_target_is_lifted_under_a_limiter(self):
        from src import voicepolish
        work = tempfile.mkdtemp()
        path = os.path.join(work, "n.mp3")
        subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-t", "6",
                        "-i", "sine=frequency=330:sample_rate=44100", "-af", "volume=-24dB", "-ac", "1",
                        "-c:a", "libmp3lame", "-b:a", "128k", path], check=True, capture_output=True, timeout=60)
        have = voicepolish.loudness(path)["lufs"]
        got = lv._lift(path, have + 3.0, have)
        self.assertIsNotNone(got)
        self.assertAlmostEqual(voicepolish.loudness(path)["lufs"], have + 3.0, delta=0.5)
        self.assertIsNone(lv._lift(path, have, have))        # nothing to do

    def test_the_new_voice_is_set_to_the_source_files_measured_loudness(self):
        doc = make_doc()                                     # meta.voiceLufs -20, the file itself louder
        work = tempfile.mkdtemp()
        narration = os.path.join(work, "src.mp3")
        subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-t", "8",
                        "-i", "sine=frequency=220:sample_rate=24000", "-af", "volume=-6dB", "-c:a", "libmp3lame",
                        narration], check=True, capture_output=True, timeout=60)
        from src import timeline as tl
        want = tl.measure_lufs(narration)
        seen = {}

        def join(parts, frags, w, target_lufs, lead, tail, gap=0.0):
            seen["target"] = target_lufs
            raise RuntimeError("stop here")
        with mock.patch.object(lv, "join_narration", side_effect=join), \
                mock.patch.object(lv, "clone_sample", return_value={"b64": "QUJD", "text": "Hi.", "key": "k",
                                                                    "seconds": 12, "from": 0, "to": 12}), \
                mock.patch.object(lv, "synthesize", return_value=[]):
            with self.assertRaises(RuntimeError):
                lv.prepare({"project_id": "n", "source_project_id": "s", "language": "es",
                            "source_audio_path": narration}, doc, work, lambda *a, **k: None,
                           server=FakeServer(), transcribe=lambda p, l: [], chat=FakeChat())
        self.assertAlmostEqual(seen["target"], want, places=1)


class Costs(unittest.TestCase):
    def test_voice_billing_counts_each_workers_start_and_idle_once(self):
        s = lv.VoiceServer(endpoint="x", key="k")
        s.jobs = [{"id": "a", "worker": "w1", "delayMs": 90_000, "executionMs": 30_000},
                  {"id": "b", "worker": "w2", "delayMs": 400_000, "executionMs": 40_000},   # a slow boot: capped
                  {"id": "c", "worker": "w1", "delayMs": 120_000, "executionMs": 30_000}]   # queued: not billed
        self.assertAlmostEqual(s.gpu_seconds(), 100 + 90 + 150 + 2 * 60)
        s.jobs = [{"id": "a", "delayMs": 10_000, "executionMs": 20_000}]
        self.assertAlmostEqual(s.gpu_seconds(), 20 + 10 + 60)

    def test_voice_gpu_seconds_are_priced_as_tts(self):
        from src import costs
        costs.reset()
        costs.record("lang.tts_gpu_seconds", 1000)
        self.assertAlmostEqual(costs.summary(0)["tts"], 0.19, places=3)


if __name__ == "__main__":
    unittest.main()
