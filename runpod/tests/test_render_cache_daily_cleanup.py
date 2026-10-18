"""rendercache.daily_cleanup: at most once a day, only cache keys, every deleted key logged outside the cache."""
import json
import unittest
from unittest import mock

from src import config, rendercache

DAY = 86400.0
NOW = 1_800_000_000.0


class FakeR2:
    def __init__(self, objects, marker_at=None):
        self.objects = dict(objects)  # key -> (iso modified, size)
        self.store = {}
        if marker_at is not None:
            self.store[rendercache.CLEANUP_MARKER] = json.dumps({"at": marker_at}).encode()
        self.deleted = []

    def enabled(self):
        return True

    def get_bytes(self, key, bucket="", timeout=60):
        return self.store.get(key)

    def upload_bytes(self, data, key, content_type="application/json", **kw):
        self.store[key] = data
        return f"https://r2.test/{key}"

    def list_keys(self, prefix="", bucket="", limit=10000):
        return [{"key": k, "modified": m, "size": s} for k, (m, s) in self.objects.items() if k.startswith(prefix)]

    def delete(self, key, bucket=""):
        self.deleted.append(key)
        self.objects.pop(key, None)
        return True


def iso(t):
    import datetime
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat().replace("+00:00", "Z")


class DailyCleanup(unittest.TestCase):
    def setUp(self):
        self.objects = {
            "render-cache/v1/projA/chunk-old.mp4": (iso(NOW - 20 * DAY), 1000),
            "render-cache/v1/projA/chunk-new.mp4": (iso(NOW - 2 * DAY), 2000),
            "render-cache/v1/projB/slice-old.aac": (iso(NOW - 15 * DAY), 300),
            "projects/projA/final.mp4": (iso(NOW - 90 * DAY), 9_000_000),   # never a cache key
        }

    def run_with(self, fake, cache=True, auto=True):
        with mock.patch.object(rendercache, "r2", fake), \
             mock.patch.object(config, "RENDER_CACHE", cache), \
             mock.patch.object(config, "RENDER_CACHE_AUTO_CLEANUP", auto), \
             mock.patch.object(config, "RENDER_CACHE_KEEP_DAYS", 14.0), \
             mock.patch.object(config, "RENDER_CACHE_PREFIX", "render-cache/v1/"):
            return rendercache.daily_cleanup(now=NOW)

    def test_deletes_only_old_cache_keys_and_logs_them(self):
        fake = FakeR2(self.objects)
        log = self.run_with(fake)
        self.assertEqual(sorted(fake.deleted), ["render-cache/v1/projA/chunk-old.mp4", "render-cache/v1/projB/slice-old.aac"])
        self.assertIn("projects/projA/final.mp4", fake.objects)
        self.assertEqual(log["deleted"], 2)
        logs = [k for k in fake.store if k.startswith(rendercache.CLEANUP_LOG_PREFIX) and k != rendercache.CLEANUP_MARKER]
        self.assertEqual(len(logs), 1)
        self.assertFalse(logs[0].startswith("render-cache/"))       # the log is kept, outside the cache
        self.assertEqual(sorted(json.loads(fake.store[logs[0]])["keys"]), sorted(fake.deleted))

    def test_at_most_once_a_day(self):
        fake = FakeR2(self.objects, marker_at=NOW - 3600)
        self.assertIsNone(self.run_with(fake))
        self.assertEqual(fake.deleted, [])
        fake2 = FakeR2(self.objects, marker_at=NOW - DAY - 1)
        self.assertIsNotNone(self.run_with(fake2))

    def test_off_unless_cache_and_auto_cleanup_on(self):
        fake = FakeR2(self.objects)
        self.assertIsNone(self.run_with(fake, cache=False))
        self.assertIsNone(self.run_with(fake, auto=False))
        self.assertEqual(fake.deleted, [])

    def test_never_raises(self):
        fake = FakeR2(self.objects)
        fake.list_keys = mock.Mock(side_effect=RuntimeError("R2 down"))
        self.assertIsNone(self.run_with(fake))


if __name__ == "__main__":
    unittest.main()
