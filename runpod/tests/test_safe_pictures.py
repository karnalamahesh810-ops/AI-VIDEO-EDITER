"""
A picture never stops a render (2026-10-07: the Obama video's first chunk failed three renders in a row -
on the pod, on a worker and as a whole-video render - on a remotion <Img> whose load never ended).

  - the check before the render (src/quality.py _verify_pictures) fetches and decodes every picture it put
    on screen itself - a repair, a sharper shot, a still held over an empty line - within a time limit; one
    that cannot be had is let go (the scene holds the shot beside it, else shows its line as text), and each
    one kept gets the shot before it as media.fallbackStill, which every machine is given like other media;
  - the renderer (remotion/src/components/motion: pictureProbe.ts, safePicture.tsx) loads every picture once
    first, a load that always settles, draws only one that loaded, takes down one that fails or hangs while
    drawing, and draws the fallback instead: no <Img> of remotion's is used anywhere else.

Offline: pictures are made here; every download is a stub.
"""
import io
import os
import re
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import assetserver, config, fanout, quality  # noqa: E402

REMOTION = os.path.join(ROOT, "remotion", "src")
FPS = 30


def _jpeg(w=640, h=360, colour=(40, 90, 160)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(out, "JPEG", quality=90)
    return out.getvalue()


def _file(folder, name, w=640, h=360) -> str:
    path = os.path.join(folder, name)
    with open(path, "wb") as fh:
        fh.write(_jpeg(w, h))
    return path


def scene(n, media):
    return {"id": f"s{n:04d}", "startFrame": n * 90, "durationInFrames": 90, "text": f"line {n} about the senator",
            "media": media, "motion": "none", "semanticMetadata": {"subject": "Barack Obama"}}


def photo(url):
    return {"type": "image", "url": url, "source": "web_image"}


def clip(url, thumb=""):
    m = {"type": "video", "url": url, "source": "youtube", "clipSeconds": 3.0}
    if thumb:
        m["thumbnail"] = thumb
    return m


EMPTY = {"type": "color", "url": "", "source": "none"}


class Resp:
    def __init__(self, code=200, body=b""):
        self.status_code = code
        self.content = body
        self.headers = {}


def held(**more):
    base = dict(NO_TEXT_FILL=True, NO_TEXT_HOLD_MAX=18.0, ANIMATION_FILL=False)
    base.update(more)
    return mock.patch.multiple(config, **base)


class ThePicturesTheCheckPutOnScreen(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="qa_safe_")
        self.own = _file(self.work, "own.jpg")
        self.after = _file(self.work, "after.jpg")
        r2 = mock.patch.object(quality.r2, "_creds", return_value=None)      # never our storage's API here
        r2.start()
        self.addCleanup(r2.stop)

    def gate(self, doc):
        g = quality.Gate(doc, self.work)
        g.fps = FPS
        return g

    def test_a_new_web_picture_is_fetched_and_decoded_before_the_render(self):
        doc = {"fps": FPS, "overlays": [], "scenes": [scene(0, photo(self.own)), scene(1, EMPTY),
                                                      scene(2, clip("https://cdn.example/c.mp4", self.after))]}
        g = self.gate(doc)
        url = "https://images.example/debate-hall.jpg"
        doc["scenes"][1]["media"] = photo(url)                      # the ladder's picture for the empty line
        body = _jpeg()
        with held(), mock.patch.object(quality.requests, "get", return_value=Resp(200, body)) as get:
            let_go = g._verify_pictures()
        self.assertEqual(let_go, 0)
        self.assertEqual(get.call_count, 1)
        self.assertTrue(os.path.isfile(g.fetched[url]))            # the render draws this copy (_sanitize_stills)
        m = doc["scenes"][1]["media"]
        self.assertEqual(m["url"], url)
        self.assertEqual(m["fallbackStill"], self.own)              # the shot before it, should it not draw

    def test_a_new_picture_that_cannot_be_downloaded_is_let_go_and_the_shot_beside_it_holds(self):
        doc = {"fps": FPS, "overlays": [], "scenes": [scene(0, photo(self.own)), scene(1, EMPTY),
                                                      scene(2, clip("https://cdn.example/c.mp4"))]}
        g = self.gate(doc)
        url = "https://images.example/gone.jpg"
        doc["scenes"][1]["media"] = photo(url)
        with held(), mock.patch.object(quality.requests, "get", return_value=Resp(404)):
            let_go = g._verify_pictures()
        self.assertEqual(let_go, 1)
        s1 = doc["scenes"][1]
        self.assertEqual(s1["media"]["url"], self.own)              # held: the picture beside it
        self.assertEqual(s1["semanticMetadata"]["borrowedFrom"], "s0000")
        self.assertIn("s0001", g.borrowed)
        self.assertEqual(g.found["picture"], 1)
        row = g.repairs[-1]
        self.assertEqual((row["scene"], row["problem"]), ("s0001", "picture"))
        self.assertTrue(row["how"].startswith("held"))
        self.assertIn("could not be downloaded", row["detail"])

    def test_a_picture_that_never_arrives_is_let_go_in_time(self):
        doc = {"fps": FPS, "overlays": [], "scenes": [scene(0, clip("https://cdn.example/a.mp4")), scene(1, EMPTY),
                                                      scene(2, clip("https://cdn.example/c.mp4"))]}
        g = self.gate(doc)
        doc["scenes"][1]["media"] = photo("https://slow.example/never.jpg")
        stop = threading.Event()
        self.addCleanup(stop.set)

        def hang(url, dest, timeout):
            stop.wait(30)
            return ""
        t0 = time.time()
        with held(), mock.patch.object(quality, "_fetch", side_effect=hang):
            let_go = g._verify_pictures(seconds=0.5)
        self.assertLess(time.time() - t0, 5.0)
        self.assertEqual(let_go, 1)
        s1 = doc["scenes"][1]
        self.assertEqual(s1["media"]["type"], "animation")         # no still beside it: its line as text
        self.assertIn("did not arrive", g.repairs[-1]["detail"])
        self.assertEqual(g.repairs[-1]["how"], "its line as a full-screen text graphic")
        self.assertEqual(g.fixed["text"], 1)

    def test_a_held_still_that_cannot_load_becomes_the_line_as_text(self):
        dead = "https://images.example/dead.jpg"
        doc = {"fps": FPS, "overlays": [], "scenes": [scene(0, photo(dead)), scene(1, EMPTY),
                                                      scene(2, clip("https://cdn.example/c.mp4"))]}
        g = self.gate(doc)
        with held():
            g.no_empty_scenes()                                     # s0001 holds s0000's picture
            self.assertIn("s0001", g.borrowed)
            self.assertEqual(g.fixed["held"], 1)
            with mock.patch.object(quality.requests, "get", return_value=Resp(404)):
                let_go = g._verify_pictures()
        self.assertEqual(let_go, 1)
        s1 = doc["scenes"][1]
        self.assertEqual(s1["media"]["type"], "animation")         # the same dead picture is never held again
        self.assertNotIn("borrowedFrom", s1.get("semanticMetadata") or {})
        self.assertNotIn("s0001", g.borrowed)
        self.assertEqual((g.fixed["held"], g.fixed["text"]), (0, 1))
        self.assertEqual(doc["scenes"][0]["media"]["url"], dead)    # the scene's own picture is not the check's

    def test_the_scenes_own_pictures_are_not_fetched_again(self):
        doc = {"fps": FPS, "overlays": [], "scenes": [scene(0, photo("https://images.example/a.jpg")),
                                                      scene(1, photo(self.own))]}
        g = self.gate(doc)
        with held(), mock.patch.object(quality, "_fetch", side_effect=AssertionError("fetched again")):
            self.assertEqual(g._verify_pictures(), 0)
        self.assertNotIn("fallbackStill", doc["scenes"][0]["media"])

    def test_a_new_local_picture_that_does_not_decode_is_let_go(self):
        page = os.path.join(self.work, "page.jpg")
        with open(page, "wb") as fh:
            fh.write(b"<html><body>403 Forbidden</body></html>" + b" " * 2000)
        doc = {"fps": FPS, "overlays": [], "scenes": [scene(0, photo(self.own)), scene(1, photo(self.after))]}
        g = self.gate(doc)
        doc["scenes"][1]["media"] = photo(page)                     # a sharper shot that is an error page
        with held():
            self.assertEqual(g._verify_pictures(), 1)
        self.assertEqual(doc["scenes"][1]["media"]["url"], self.own)

    def test_a_check_that_breaks_never_fails_the_video(self):
        doc = {"fps": FPS, "overlays": [], "scenes": [scene(0, photo(self.own)), scene(1, EMPTY)]}
        g = self.gate(doc)
        doc["scenes"][1]["media"] = photo("https://images.example/x.jpg")
        with held(), mock.patch.object(quality.Gate, "_verify", side_effect=RuntimeError("boom")):
            self.assertEqual(g._verify_pictures(), 0)
        self.assertTrue(any("new pictures" in n for n in g.notes))

    def test_every_repair_path_checks_the_new_pictures_before_drawing(self):
        import inspect
        for fn in (quality.Gate._before_render, quality.Gate._after_render, quality.Gate._recover,
                   quality.Gate.join_second_render):
            src = inspect.getsource(fn)
            self.assertIn("self._verify_pictures()", src, fn.__name__)
            self.assertLess(src.index("self.no_empty_scenes()"), src.index("self._verify_pictures()"), fn.__name__)


class TheFallbackTravelsLikeOtherMedia(unittest.TestCase):
    def test_a_local_fallback_still_is_served_and_published(self):
        work = tempfile.mkdtemp(prefix="qa_safe_")
        still = _file(work, "held.jpg")
        doc = {"scenes": [{"id": "s0", "media": {"type": "image", "url": "https://x.example/a.jpg",
                                                 "fallbackStill": still}}]}
        self.assertIn("fallbackStill", assetserver.MEDIA_FIELDS)
        refs = fanout.local_refs(doc)
        self.assertIn(("fallbackStill", still), [(f, p) for _m, f, p in refs])

        class Server:
            def url_for(self, path):
                return "http://127.0.0.1:9/" + os.path.basename(path)
        assetserver.localise(doc, Server())
        self.assertEqual(doc["scenes"][0]["media"]["fallbackStill"], "http://127.0.0.1:9/held.jpg")


class TheRenderer(unittest.TestCase):
    """remotion/src, read as text (the other renderer contracts are checked the same way)."""

    def _src(self, *parts):
        with open(os.path.join(REMOTION, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_no_picture_is_drawn_by_remotions_img_except_through_safeimg(self):
        left = []
        for base, _dirs, files in os.walk(REMOTION):
            for fn in files:
                if not fn.endswith((".tsx", ".ts")):
                    continue
                path = os.path.join(base, fn)
                if os.path.normcase(path) == os.path.normcase(os.path.join(REMOTION, "components", "motion",
                                                                             "safePicture.tsx")):
                    continue
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)             # (the notes may name it)
                text = re.sub(r"(^|\s)//[^\n]*", r"\1", text)
                if re.search(r"<Img[\s/>]", text) or re.search(r"import\s*\{[^}]*\bImg\b[^}]*\}\s*from\s*['\"]remotion",
                                                              text):
                    left.append(os.path.relpath(path, REMOTION))
        self.assertEqual(left, [])

    def test_every_hold_on_a_picture_runs_out_before_the_renders_own(self):
        probe = self._src("components", "motion", "pictureProbe.ts")
        ms = {k: int(v) for k, v in re.findall(r"export const (PICTURE_PROBE_MS|PICTURE_DRAW_MS) = (\d+);", probe)}
        self.assertEqual(set(ms), {"PICTURE_PROBE_MS", "PICTURE_DRAW_MS"})
        self.assertIn("timeoutInMilliseconds: PICTURE_PROBE_MS + 20000", probe)
        self.assertIn("setTimeout(() => {", probe)                          # the load always settles
        limit = int(config.RENDER_DELAY_TIMEOUT_MS)
        self.assertLess(ms["PICTURE_PROBE_MS"] + 20000, limit)
        self.assertLess(ms["PICTURE_DRAW_MS"], limit)
        guard = self._src("components", "motion", "pictureGuard.tsx")
        self.assertIn("PICTURE_PROBE_MS + 15000", guard)

    def test_a_picture_that_fails_or_hangs_is_taken_down_for_its_fallback(self):
        safe = self._src("components", "motion", "safePicture.tsx")
        self.assertIn("usePictureLoads(", safe)
        self.assertIn("setTimeout(giveUp, PICTURE_DRAW_MS)", safe)          # drawn from the cache, or let go
        self.assertRegex(safe, r"onError=\{\(e\) => \{\s*onError\?\.\(e\);\s*giveUp\(\);")
        self.assertIn("key={String(props.src", safe)                        # a new picture loads afresh

    def test_a_scene_picture_falls_back_to_the_shot_before_it_blurred(self):
        clip_src = self._src("components", "SceneClip.tsx")
        self.assertIn("media.fallbackStill ||", clip_src)
        self.assertEqual(clip_src.count("fallback={hold}"), 3)              # window, inset, framed by hand
        self.assertEqual(clip_src.count("fallbackStill={holdStill}"), 3)    # living, still, a split screen's half
        still = self._src("transitions", "stillMotion.tsx")
        self.assertIn("<BlurredHold still={fallbackStill} />", still)
        main = self._src("Main.tsx")
        self.assertIn('sc.media?.type !== "image"', main)                   # a picture's neighbour is passed too
        types = self._src("types.ts")
        self.assertIn("fallbackStill?: string;", types)


if __name__ == "__main__":
    unittest.main()
