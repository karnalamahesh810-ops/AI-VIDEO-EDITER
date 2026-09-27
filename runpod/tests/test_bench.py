import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("bench", os.path.join(ROOT, "scripts", "bench.py"))
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def scene(i, desc="", attribution="", entities=None, locations=None, spec_intent="event",
          spec_seen="event", rel=0.8, final=0.7, ts=0.9, asset="", kind="video", cands=12):
    return {"id": f"s{i}", "startFrame": i * 180, "durationInFrames": 180, "text": "x",
            "media": {"type": kind, "url": f"/w/{i}.mp4", "attribution": attribution} if asset else {"type": "color"},
            "semanticMetadata": {"contentDescription": desc, "relevanceScore": rel, "finalScore": final,
                                 "scoreParts": {"timestamp": ts}, "assetId": asset,
                                 "specificity": spec_seen, "candidates": {"candidates": cands},
                                 "sceneIntent": {"entities": entities or [], "locations": locations or [],
                                                 "specificity": spec_intent}}}


class Scoring(unittest.TestCase):
    def test_metrics_from_a_synthetic_timeline(self):
        case = {"name": "new_mexico_flash_flood", "entities": ["Ruidoso", "Rio Ruidoso"], "locations": ["New Mexico"]}
        doc = {"scenes": [
            scene(0, "Aerial view of Ruidoso flooding, brown water", entities=["Ruidoso"], locations=["New Mexico"],
                  asset="yt:A", spec_seen="event"),
            scene(1, "A flooded street somewhere", entities=["Ruidoso"], locations=["New Mexico"],
                  asset="yt:B", spec_seen="generic"),
            scene(2, "Rio Ruidoso at record crest", attribution="YouTube: Ruidoso flood", entities=["Rio Ruidoso"],
                  asset="yt:A", spec_seen="event"),
            scene(3, "", asset=""),                              # empty slot
        ], "meta": {"aiUsage": {"estimatedCredits": 20, "visionCalls": 9}, "warnings": ["w"],
                    "sourcing": {"fanout": {"parts": 3}}}}
        m = bench.score_timeline(doc, case, elapsed=300)
        self.assertEqual(m["scenes"], 4)
        self.assertEqual(m["fill_pct"], 75.0)
        self.assertEqual(m["entity_acc"], 66.7)              # scene 1 saw no Ruidoso
        self.assertEqual(m["location_acc"], 0.0)             # nothing described New Mexico
        self.assertEqual(m["case_entity_coverage"], 66.7)
        self.assertAlmostEqual(m["visual_relevance"], 0.8)
        self.assertAlmostEqual(m["timestamp_relevance"], 0.9)
        self.assertEqual(m["duplicate_rate"], 33.3)          # yt:A twice in three
        self.assertEqual(m["generic_rate"], 33.3)
        self.assertEqual(m["avg_candidates"], 12.0)
        self.assertEqual(m["vision_calls"], 9)
        self.assertEqual(m["ai_usd"], 0.1)
        self.assertGreater(m["runpod_usd"], 0)
        self.assertEqual(m["warnings"], 1)

    def test_cases_load_with_audio(self):
        cases = bench.load_cases()
        self.assertEqual(len(cases), 7)
        for c in cases:
            self.assertTrue(os.path.isfile(os.path.join(ROOT, "bench", "audio", f"{c['name']}.mp3")), c["name"])
            self.assertTrue(c["entities"] and c["narration"])


if __name__ == "__main__":
    unittest.main()
