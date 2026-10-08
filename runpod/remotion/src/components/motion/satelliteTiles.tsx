import React from "react";
import { continueRender, delayRender } from "remotion";
import { PICTURE_PROBE_MS } from "./pictureProbe";
import { SafeImg } from "./safePicture";
import { USGS_MAX, childTiles, dropNoData, hawaiiTile, tileUrl, usgsZoom } from "./tiles";

export { GIBS_MAX, TILE, USGS_MAX, childTiles, hawaiiTile, tileUrl, usgsZoom } from "./tiles";

/**
 * The public imagery every satellite map draws - MapLooks' satellite looks, the geo- maps (LibGeoMaps) and the
 * pro maps (LibMapsPro): USGS orthoimagery (The National Map, public domain) inside the US from zoom 7, NASA
 * GIBS Blue Marble below that and everywhere else (to zoom 8), 256 px web-mercator tiles.
 *
 * The USGS cache is not clean outside the 48 states (measured 2026-10-08 on the Obama video's Honolulu map at
 * 1:47, free tile requests):
 *   - its Hawaii mosaic paints no-data as flat opaque slabs - cream, orange, periwinkle and white - beside the
 *     black it uses elsewhere. The old filter dropped only black, so pale cream and orange rectangles sat on
 *     the sea around Oahu at zooms 10-12 (tiles.ts).
 *   - whole levels are missing: Hawaii has no z9 at all (404), parts of Alaska no z9-z11. Such a tile left only
 *     the Blue Marble underlay (zoom 8, its sea dropped): the island went soft and pale mid-zoom.
 * So each USGS tile is fetched once per page (both servers allow it: Access-Control-Allow-Origin *), its
 * no-data dropped on a canvas (tiles.dropNoData), and drawn from that copy - no filter left to run on every
 * frame (an SVG filter doing the same cost ~25x the render time); a USGS tile the cache does not have (404)
 * draws its four children one level down instead. A tile that cannot be fetched that way is drawn as it comes
 * through the old black-only filter.
 */

/** Alpha from colour: near-black (USGS no-data) goes, dark water stays (alpha = 9 x (R + G + B) - 0.1). */
export const BLACK_KEY = "1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  9 9 9 0 -0.1";
/** Blue Marble's near-black open sea goes under a USGS zoom (alpha = 4 x (R + G + B) - 0.4); land stays. */
export const DARK_SEA_KEY = "1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  4 4 4 0 -0.4";

/** The filters a map's tiles may be drawn through (once per map, under the id its tiles name). */
export const TileFilters: React.FC<{ id: string }> = ({ id }) => (
  <svg width={0} height={0} style={{ position: "absolute" }}>
    {/* a USGS tile that could not be cleaned: black no-data out, as before */}
    <filter id={`${id}nd`} colorInterpolationFilters="sRGB">
      <feColorMatrix type="matrix" values={BLACK_KEY} />
    </filter>
    <filter id={`${id}sea`} colorInterpolationFilters="sRGB">
      <feColorMatrix type="matrix" values={DARK_SEA_KEY} />
    </filter>
  </svg>
);

// ------------------------------------------------------------------ one clean copy of each USGS tile
/** What became of a tile: `src` its clean copy; `missing` the cache has no such tile (404); `dead` it never
 *  answered in time; none of them: it could not be cleaned (drawn as it comes). */
export type Cleaned = { src?: string; missing?: boolean; dead?: boolean };

/** The longest one tile's clean copy may take (as long as a picture's first load). */
export const TILE_CLEAN_MS = PICTURE_PROBE_MS;
/** Clean copies a page keeps (a map shot draws ~100-300 tiles; a copy is ~50-150 KB): the oldest go first. */
export const TILE_COPIES_KEPT = 512;
const done = new Map<string, Cleaned>();
const pending = new Map<string, Promise<Cleaned>>();

/** Keep a settled result, newest last; past TILE_COPIES_KEPT the oldest copy is let go. */
const keep = (key: string, c: Cleaned) => {
  done.delete(key);
  done.set(key, c);
  while (done.size > TILE_COPIES_KEPT) {
    const [oldest, gone] = done.entries().next().value as [string, Cleaned];
    done.delete(oldest);
    if (gone.src && gone.src.startsWith("blob:")) URL.revokeObjectURL(gone.src);
  }
};

const cleanCopy = async (url: string, white: boolean): Promise<Cleaned> => {
  const started = Date.now();
  let timedOut = false;
  for (let attempt = 0; attempt < 2; attempt++) {
    const left = TILE_CLEAN_MS - (Date.now() - started);
    if (left < 2000) break;
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), left);
    try {
      const res = await fetch(url, { mode: "cors", credentials: "omit", signal: ctl.signal });
      if (res.status === 404) return { missing: true };
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      // The file's own values (no colour management): the fill colours are matched exactly.
      const bmp = await createImageBitmap(await res.blob(), { colorSpaceConversion: "none" });
      const w = bmp.width, h = bmp.height;
      const canvas = new OffscreenCanvas(w, h);
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      if (!ctx) return {};
      ctx.drawImage(bmp, 0, 0);
      bmp.close();
      const image = ctx.getImageData(0, 0, w, h);
      // Nothing to drop (most tiles inland): the tile itself, from the browser's cache by now.
      if (!dropNoData(image.data, w, h, white).changed) return { src: url };
      ctx.putImageData(image, 0, 0);
      return { src: URL.createObjectURL(await canvas.convertToBlob({ type: "image/png" })) };
    } catch {
      timedOut = ctl.signal.aborted;
      // A tile server's moment of refusal: once more after a second while there is time for it.
      if (attempt === 0 && !timedOut) await new Promise((r) => setTimeout(r, 1000));
    } finally {
      clearTimeout(timer);
    }
  }
  return timedOut ? { dead: true } : {};
};

/** The tile's clean copy, made once per page whoever asks. Always settles (within about TILE_CLEAN_MS). */
export const cleanTile = (url: string, white: boolean): Promise<Cleaned> => {
  const key = `${white ? "w" : "n"}|${url}`;
  const had = done.get(key);
  if (had) {
    keep(key, had);                                       // in use again: the newest
    return Promise.resolve(had);
  }
  const waiting = pending.get(key);
  if (waiting) return waiting;
  const p = cleanCopy(url, white).catch((): Cleaned => ({})).then((c) => {
    keep(key, c);
    pending.delete(key);
    return c;
  });
  pending.set(key, p);
  return p;
};

/** cleanTile as a hook: undefined while it is being made - the frame waits under a hold of its own. */
export const useCleanTile = (url: string, white: boolean): Cleaned | undefined => {
  const key = url ? `${white ? "w" : "n"}|${url}` : "";
  const [got, setGot] = React.useState<Cleaned | undefined>(() => (key ? done.get(key) : {}));
  const [handle] = React.useState(() => (key && !done.has(key)
    ? delayRender(`Cleaning the map tile ${url.slice(-40)}`, { timeoutInMilliseconds: TILE_CLEAN_MS + 20000 })
    : null));
  React.useEffect(() => {
    if (!key) return;
    let live = true;
    cleanTile(url, white).then((c) => {
      if (live) setGot(c);
      if (handle !== null) continueRender(handle);
    });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return got;
};

// ------------------------------------------------------------------ one tile
type TileProps = {
  /** TileFilters' id. */
  id: string;
  z: number;
  /** The tile's column, already wrapped into 0 .. 2^z - 1. */
  x: number;
  y: number;
  /** The map is inside the US (USGS from zoom 7). */
  us: boolean;
  /** A tile of the Blue Marble underlay (its dark sea dropped). */
  under?: boolean;
  left: number;
  top: number;
  /** The tile's side on screen (px). */
  size: number;
  opacity?: number;
  /** A child drawn for a missing parent: no further level down. */
  leaf?: boolean;
};

/**
 * One imagery tile; it never fails or holds up the render. A USGS tile is drawn from its clean copy (no-data
 * dropped); one the cache does not have - Hawaii's z9, Alaska's z9-z11 - draws its four children instead of
 * leaving its square to the soft underlay.
 */
export const ImageryTile: React.FC<TileProps> = (p) => {
  const usgs = !p.under && usgsZoom(p.z, p.us);
  const url = tileUrl(p.z, p.x, p.y, usgs);
  const clean = useCleanTile(usgs ? url : "", usgs && hawaiiTile(p.z, p.x, p.y));
  const box = { position: "absolute" as const, left: p.left, top: p.top, width: Math.ceil(p.size) + 1,
    height: Math.ceil(p.size) + 1, opacity: p.opacity };
  if (!usgs) {
    return <SafeImg src={url} onError={() => undefined} maxRetries={3} delayRenderTimeoutInMilliseconds={60000}
      style={{ ...box, filter: p.under ? `url(#${p.id}sea)` : undefined }} />;
  }
  if (clean === undefined || clean.dead) return null;      // (the frame waits for the first; the second is gone)
  if (clean.missing) {
    if (p.leaf || p.z + 1 > USGS_MAX) return null;
    const half = p.size / 2;
    return (
      <>
        {childTiles(p.z, p.x, p.y).map(([z, x, y, col, row]) => (
          <ImageryTile key={`${z}-${x}-${y}`} id={p.id} z={z} x={x} y={y} us={p.us} left={p.left + col * half}
            top={p.top + row * half} size={half} opacity={p.opacity} leaf />
        ))}
      </>
    );
  }
  // The clean copy (or the tile itself when it had nothing to drop); one that could not be cleaned is drawn as
  // it comes through the black-only filter.
  return <SafeImg src={clean.src || url} onError={() => undefined} maxRetries={3} delayRenderTimeoutInMilliseconds={60000}
    style={{ ...box, filter: clean.src ? undefined : `url(#${p.id}nd)` }} />;
};
