import React from "react";
import { continueRender, delayRender } from "remotion";

/**
 * Every picture the renderer draws is loaded once here first, and that load always settles: loaded, failed,
 * or given up after PICTURE_PROBE_MS. Remotion's <Img> holds the frame until its picture loads, and a picture
 * that never does - a host that never answers, or a broken picture whose <Img> has an error handler that
 * leaves it mounted (remotion 4: the handler is called and the frame's hold is never let go) - runs the
 * render out of time. 2026-10-07: the Obama video's first chunk failed that way on the pod, on a worker and
 * as a whole-video render. Only a picture known to load reaches an <Img> (safePicture.tsx); the rest are
 * drawn as their fallback and the render goes on.
 */

/** A picture a look shows must be at least this many pixels a side (an error page's 1 px gif is not). */
export const MIN_SIDE = 32;
/** The longest one picture's first load may take. */
export const PICTURE_PROBE_MS = 25000;
/** The longest a picture known to load may then take to draw (from the browser's cache by then). */
export const PICTURE_DRAW_MS = 30000;

type Found = { ok: boolean; w: number; h: number };
const found = new Map<string, Found>();
const pending = new Map<string, Promise<boolean>>();

/** Whether `url` loaded (any size, an SVG without one too): undefined while unknown. */
export const pictureLoads = (url: string): boolean | undefined => found.get(url)?.ok;

/** Whether `url` loaded at least MIN_SIDE a side (a usable photo for a look): undefined while unknown. */
export const pictureUsable = (url: string): boolean | undefined => {
  const f = found.get(url);
  return f ? f.ok && f.w >= MIN_SIDE && f.h >= MIN_SIDE : undefined;
};

/** Loads `url` once per page: true when it loaded. Always settles (false after PICTURE_PROBE_MS). */
export const probePicture = (url: string): Promise<boolean> => {
  const f = found.get(url);
  if (f) return Promise.resolve(f.ok);
  const had = pending.get(url);
  if (had) return had;
  const p = new Promise<boolean>((resolve) => {
    let done = false;
    let im: HTMLImageElement | null = null;
    const finish = (ok: boolean, w: number, h: number) => {
      if (done) return;
      done = true;
      found.set(url, { ok, w, h });
      pending.delete(url);
      resolve(ok);
    };
    const started = Date.now();
    const attempt = (left: number) => {
      try {
        const img = new Image();
        im = img;
        img.onload = () => finish(true, img.naturalWidth || 0, img.naturalHeight || 0);
        img.onerror = () => {
          // Once more after a second (a tile server's moment of refusal), while there is time for it.
          if (left > 0 && !done && Date.now() - started < PICTURE_PROBE_MS - 5000) {
            setTimeout(() => {
              if (!done) attempt(left - 1);
            }, 1000);
            return;
          }
          finish(false, 0, 0);
        };
        img.src = url;
      } catch {
        finish(false, 0, 0);
      }
    };
    attempt(1);
    setTimeout(() => {
      if (done) return;
      finish(false, 0, 0);
      try {
        // The load is dropped: it must not hold one of the host's few connections.
        if (im) {
          im.onload = null;
          im.onerror = null;
          im.src = "";
        }
      } catch {
        /* nothing to drop */
      }
    }, PICTURE_PROBE_MS);
  });
  pending.set(url, p);
  return p;
};

const verdict = (urls: string[], usable: boolean): boolean | null => {
  if (!urls.length) return false;
  let all = true;
  for (const u of urls) {
    const ok = usable ? pictureUsable(u) : pictureLoads(u);
    if (ok === undefined) return null;
    if (!ok) all = false;
  }
  return all;
};

/**
 * Whether every picture in `urls` loads (`usable`: at least MIN_SIDE a side): null while one is still being
 * loaded - the frame waits for it under a hold of its own, which cannot run out first (the load always
 * settles within PICTURE_PROBE_MS). No pictures: false.
 */
export const usePicturesLoad = (urls: string[], usable = false): boolean | null => {
  const key = urls.join("\n");
  const [ok, setOk] = React.useState<boolean | null>(() => verdict(urls, usable));
  const [handle] = React.useState(() => (verdict(urls, usable) === null
    ? delayRender(`Loading ${urls.length === 1 ? `the picture ${urls[0].slice(-60)}` : `${urls.length} pictures`} first`,
      { timeoutInMilliseconds: PICTURE_PROBE_MS + 20000 })
    : null));
  React.useEffect(() => {
    let live = true;
    Promise.all(urls.map(probePicture)).then(() => {
      if (live) setOk(verdict(urls, usable));
      if (handle !== null) continueRender(handle);
    });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, usable]);
  return ok;
};

/** usePicturesLoad for one picture ("" or undefined: false). */
export const usePictureLoads = (src: string | undefined): boolean | null => usePicturesLoad(src ? [src] : []);
