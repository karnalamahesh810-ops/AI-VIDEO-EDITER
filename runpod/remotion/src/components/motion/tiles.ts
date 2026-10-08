/**
 * The satellite maps' imagery tiles, the pure part (no DOM, no React: satelliteTiles.tsx draws them, and
 * tests/test_map_tiles.py runs this under node on recorded tiles).
 *
 * Which tile: USGS orthoimagery (The National Map, public domain) inside the US from zoom 7, NASA GIBS Blue
 * Marble below that and everywhere else (to zoom 8), 256 px web-mercator tiles.
 *
 * USGS no-data out of a tile's pixels: the cache paints no-data black (open water), and around Hawaii also as
 * flat opaque slabs - cream (255,255,205), orange (255,188,120), periwinkle (128,127,254) and, near the Big
 * Island, white. Measured 2026-10-08 on the Obama video's Honolulu map at 1:47: the old filter dropped only
 * black, so pale cream and orange rectangles sat on the sea around Oahu at zooms 10-12.
 *
 *   - black: alpha = 9 x (R + G + B) - 0.1 of the colour (near-black goes, dark water stays), as before;
 *   - a fill: a pixel within FILL_TOLERANCE of a fill colour on every channel, kept only where such pixels run
 *     at least 2 x FILL_OPEN + 1 px across or down (a slab or a strip one pixel thick goes; a few pixels of
 *     real imagery in a fill's colour - a yellowish cloud, red soil - stay), then grown FILL_GROW px past the
 *     slab's edge (the blend of its edge with what is beside it);
 *   - white the same, on Hawaii's tiles only and with longer runs (WHITE_OPEN): elsewhere that white is snow
 *     and glacier, and a cloud's blown-out core is white too (no recorded Hawaii cloud held a 15 px run of it;
 *     every white slab did).
 */

export const TILE = 256;
export const GIBS_MAX = 8;
export const USGS_MAX = 16;

/** USGS imagery from this zoom up inside the US; NASA Blue Marble below it and everywhere else. */
export const usgsZoom = (z: number, us: boolean) => us && z > GIBS_MAX - 2;

/** One tile's address: USGS when `us` and the zoom is a USGS one, else Blue Marble. */
export const tileUrl = (z: number, x: number, y: number, us: boolean) => (usgsZoom(z, us)
  ? `https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/${z}/${y}/${x}`
  : `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_NextGeneration/default/GoogleMapsCompatible_Level8/${z}/${y}/${x}.jpeg`);

/** The Hawaii box of the US boxes the maps use: [lat south, lat north, lon west, lon east]. */
export const HAWAII_BOX = [18, 23, -161, -154] as const;
const tileLon = (x: number, z: number) => (x / 2 ** z) * 360 - 180;
const tileLat = (y: number, z: number) => (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / 2 ** z))) * 180) / Math.PI;

/** Whether tile (z, x, y) touches Hawaii (its white slabs are no-data there; elsewhere white is snow). */
export const hawaiiTile = (z: number, x: number, y: number) => {
  const [s, n, w, e] = HAWAII_BOX;
  return tileLon(x + 1, z) >= w && tileLon(x, z) <= e && tileLat(y, z) >= s && tileLat(y + 1, z) <= n;
};

/** The four tiles one level down that cover tile (z, x, y): [z, x, y, column, row]. */
export const childTiles = (z: number, x: number, y: number): [number, number, number, number, number][] =>
  [0, 1, 2, 3].map((i) => [z + 1, 2 * x + (i & 1), 2 * y + (i >> 1), i & 1, i >> 1]);

export type Rgb = readonly [number, number, number];

export const USGS_FILLS: readonly Rgb[] = [[255, 255, 205], [255, 188, 120], [128, 127, 254]];
/** Per channel, 0-255 (inside a slab JPEG noise stays within ~5; its edge column is often a few steps off). */
export const FILL_TOLERANCE = 10;
export const HAWAII_WHITE: Rgb = [255, 255, 255];
export const WHITE_TOLERANCE = 3;
/** Runs of a fill's colour at least 2r+1 px long (across or down) count as the fill. */
export const FILL_OPEN = 3;
export const WHITE_OPEN = 7;
/** How far past a fill's edge the key reaches (px). */
export const FILL_GROW = 3;

/** 1 where the pixel is within `tol` of one of `fills` on every channel (and not already transparent). */
export const fillMask = (px: Uint8ClampedArray | Uint8Array, w: number, h: number, fills: readonly Rgb[], tol: number) => {
  const out = new Uint8Array(w * h);
  for (let i = 0, p = 0; i < w * h; i++, p += 4) {
    if (px[p + 3] === 0) continue;
    const r = px[p], g = px[p + 1], b = px[p + 2];
    for (const c of fills) {
      if (Math.abs(r - c[0]) <= tol && Math.abs(g - c[1]) <= tol && Math.abs(b - c[2]) <= tol) {
        out[i] = 1;
        break;
      }
    }
  }
  return out;
};

/** The mask's pixels that lie on a run of at least `len` across or down (a 1-D opening each way, merged). */
export const runs = (m: Uint8Array, w: number, h: number, len: number) => {
  const out = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    let x = 0;
    while (x < w) {
      if (!m[y * w + x]) { x++; continue; }
      let e = x;
      while (e < w && m[y * w + e]) e++;
      if (e - x >= len) for (let k = x; k < e; k++) out[y * w + k] = 1;
      x = e;
    }
  }
  for (let x = 0; x < w; x++) {
    let y = 0;
    while (y < h) {
      if (!m[y * w + x]) { y++; continue; }
      let e = y;
      while (e < h && m[e * w + x]) e++;
      if (e - y >= len) for (let k = y; k < e; k++) out[k * w + x] = 1;
      y = e;
    }
  }
  return out;
};

/** The mask grown by `r` px each way (a (2r+1)-square dilation, done across then down). */
export const grow = (m: Uint8Array, w: number, h: number, r: number) => {
  if (r <= 0) return m;
  const across = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    // two sweeps: a set pixel within r to the left, then to the right
    let prev = -Infinity;
    for (let x = 0; x < w; x++) {
      if (m[y * w + x]) prev = x;
      if (x - prev <= r) across[y * w + x] = 1;
    }
    let next = Infinity;
    for (let x = w - 1; x >= 0; x--) {
      if (m[y * w + x]) next = x;
      if (next - x <= r) across[y * w + x] = 1;
    }
  }
  const out = new Uint8Array(w * h);
  for (let x = 0; x < w; x++) {
    let prev = -Infinity;
    for (let y = 0; y < h; y++) {
      if (across[y * w + x]) prev = y;
      if (y - prev <= r) out[y * w + x] = 1;
    }
    let next = Infinity;
    for (let y = h - 1; y >= 0; y--) {
      if (across[y * w + x]) next = y;
      if (next - y <= r) out[y * w + x] = 1;
    }
  }
  return out;
};

/** The key: every pixel of a fill slab or strip, grown past its edge (1 = goes). */
export const noDataKey = (px: Uint8ClampedArray | Uint8Array, w: number, h: number, white: boolean) => {
  // (typed plainly: the editor's newer TypeScript keeps Uint8Array<ArrayBuffer> and Uint8Array<ArrayBufferLike> apart)
  let key: Uint8Array = runs(fillMask(px, w, h, USGS_FILLS, FILL_TOLERANCE), w, h, 2 * FILL_OPEN + 1);
  if (white) {
    const wk = runs(fillMask(px, w, h, [HAWAII_WHITE], WHITE_TOLERANCE), w, h, 2 * WHITE_OPEN + 1);
    for (let i = 0; i < key.length; i++) key[i] |= wk[i];
  }
  key = grow(key, w, h, FILL_GROW);
  return key;
};

/**
 * Drop USGS no-data from RGBA pixels in place (unpremultiplied, as a canvas's getImageData gives them): black
 * fades out by the old rule, fill slabs and strips go. `white`: Hawaii's white slabs too. Returns how many
 * pixels the fills took and how many pixels changed at all (0: the tile is drawn as it is).
 */
export const dropNoData = (px: Uint8ClampedArray | Uint8Array, w: number, h: number,
  white: boolean): { fills: number; changed: number } => {
  const key = noDataKey(px, w, h, white);
  let fills = 0, changed = 0;
  for (let i = 0, p = 0; i < w * h; i++, p += 4) {
    const before = px[p + 3];
    if (key[i]) {
      if (before) fills++;
      px[p + 3] = 0;
    } else {
      const a = Math.max(0, Math.min(1, (9 * (px[p] + px[p + 1] + px[p + 2])) / 255 - 0.1));
      px[p + 3] = Math.round(before * a);
    }
    if (px[p + 3] !== before) changed++;
  }
  return { fills, changed };
};
