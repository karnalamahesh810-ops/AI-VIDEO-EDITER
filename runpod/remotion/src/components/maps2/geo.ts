/**
 * Maps v2 geography (2026-10-14): Natural Earth countries (1:50m), states / provinces (1:10m admin-1, simplified)
 * and key cities, bundled (src/data/maps2, public domain - LICENSE-natural-earth.txt), and the camera every
 * maps-v2 look moves: a Web-Mercator camera {lon, lat, z} (z: tile zoom, a 1920-wide frame shows 256 x 2^z px of
 * world per tile), fitted to shapes and flown between two framings on van Wijk's smooth zoom path.
 * Pure functions: nothing here touches the network or the DOM.
 */
import { geoArea, geoBounds, geoCentroid, geoContains, geoDistance, geoMercator, type GeoProjection } from "d3-geo";
import { feature } from "topojson-client";
import countriesTopo from "../../data/maps2/ne_countries.json";
import regionsTopo from "../../data/maps2/ne_regions.json";
import citiesData from "../../data/maps2/ne_cities.json";

export type XY = [number, number];
export type Geometry = { type: string; coordinates: unknown };
export interface Area {
  /** Country: ISO A3 ("TWN"); region: its ISO 3166-2 ("US-TX") or "<A3>:<name>" when it has none. */
  id: string;
  kind: "country" | "region";
  name: string;
  /** Another name it goes by (a region's English name: "Kyōto Prefecture"; a country's long name). */
  alt: string;
  /** The country (A3) a region is in; a country's own. */
  a3: string;
  geometry: Geometry;
  /** [[west, south], [east, north]] in degrees (east may exceed 180 across the antimeridian). */
  bounds: [XY, XY];
  centroid: XY;
}

type Feat = { properties: Record<string, string>; geometry: Geometry | null };
const feats = (topo: unknown, key: string): Feat[] => {
  const t = topo as { objects: Record<string, unknown> };
  return (feature(t as never, t.objects[key] as never) as unknown as { features: Feat[] }).features;
};

const areaOf = (f: Feat, kind: Area["kind"]): Area | null => {
  if (!f.geometry) return null;
  const p = f.properties || {};
  const a3 = String(p.a || "");
  const name = String(p.n || p.e || "");
  const alt = String((kind === "region" ? p.e : p.l) || "");
  const code = String(p.c || "");
  const id = kind === "country" ? a3 : (code && code !== "-99" ? code : `${a3}:${name}`);
  // A ring wound the wrong way reads as the whole globe but the shape (two Maldives atolls in the 1:10m set):
  // turned round, it is the atoll again.
  let geometry = f.geometry;
  if (geoArea(geometry as never) > 2 * Math.PI) geometry = rewound(geometry);
  const g = geometry as never;
  return { id, kind, name, alt, a3, geometry, bounds: geoBounds(g) as [XY, XY], centroid: geoCentroid(g) as XY };
};

const rewound = (g: Geometry): Geometry => {
  const rev = (poly: number[][][]) => poly.map((ring) => ring.slice().reverse());
  if (g.type === "Polygon") return { type: g.type, coordinates: rev(g.coordinates as number[][][]) };
  if (g.type === "MultiPolygon") return { type: g.type, coordinates: (g.coordinates as number[][][][]).map(rev) };
  return g;
};

let COUNTRIES_: Area[] | null = null;
let REGIONS_: Area[] | null = null;
/** Every country (Antarctica too: it is drawn, never picked). */
export const countries = (): Area[] => (COUNTRIES_ ||= feats(countriesTopo, "countries").map((f) => areaOf(f, "country"))
  .filter((a): a is Area => !!a));
/** Every state / province / region. */
export const regions = (): Area[] => (REGIONS_ ||= feats(regionsTopo, "regions").map((f) => areaOf(f, "region"))
  .filter((a): a is Area => !!a));

const norm = (s: string) => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

/** An area by id ("TWN", "US-TX", "IND:Kerala") or by name ("Taiwan", "Texas"); null when none. */
export const findArea = (key: string | undefined | null): Area | null => {
  if (!key) return null;
  const k = String(key).trim();
  const byId = countries().find((a) => a.id === k) || regions().find((a) => a.id === k);
  if (byId) return byId;
  const n = norm(k.split(",")[0]);
  if (!n) return null;
  const named = (a: Area) => norm(a.name) === n || (!!a.alt && norm(a.alt) === n);
  return countries().find(named) || regions().find(named) || null;
};

const inBounds = (b: [XY, XY], lon: number, lat: number) => {
  const [[w, s], [e, n]] = b;
  if (lat < s - 0.01 || lat > n + 0.01) return false;
  return w <= e ? lon >= w - 0.01 && lon <= e + 0.01 : lon >= w - 0.01 || lon <= e + 0.01;
};

/** The country holding a point (else the nearest country within ~150 km: a coastal city on a simplified coast). */
export const countryAt = (lon: number, lat: number): Area | null => {
  const hit = countries().find((a) => inBounds(a.bounds, lon, lat) && geoContains(a.geometry as never, [lon, lat]));
  if (hit) return hit;
  return nearest(countries(), lon, lat, 150);
};

/** The state / province holding a point (same rule). */
export const regionAt = (lon: number, lat: number): Area | null => {
  const hit = regions().find((a) => inBounds(a.bounds, lon, lat) && geoContains(a.geometry as never, [lon, lat]));
  if (hit) return hit;
  return nearest(regions(), lon, lat, 60);
};

const nearest = (list: Area[], lon: number, lat: number, km: number): Area | null => {
  let best: Area | null = null;
  let bd = km / 6371;
  for (const a of list) {
    const d = geoDistance(a.centroid, [lon, lat]);
    if (d < bd * 4 && d < bd + 0.08) {
      // the centroid is a rough guide only: keep the closest whose box reaches the point
      const [[w, s], [e, n]] = a.bounds;
      const pad = km / 111;
      if (lat >= s - pad && lat <= n + pad && (w <= e ? lon >= w - pad && lon <= e + pad : true)) {
        best = a;
        bd = d;
      }
    }
  }
  return best;
};

/** The regions of a country (for its inner lines when zoomed in). */
export const regionsOf = (a3: string): Area[] => regions().filter((r) => r.a3 === a3);

// ------------------------------------------------------------------ cities
export interface City { name: string; lat: number; lon: number; a3: string; rank: number; pop: number; capital: boolean }
let CITIES_: City[] | null = null;
export const cities = (): City[] => (CITIES_ ||= (citiesData as { rows: (string | number)[][] }).rows.map((r) => ({
  name: String(r[0]), lat: Number(r[1]), lon: Number(r[2]), a3: String(r[3]), rank: Number(r[4]), pop: Number(r[5]),
  capital: Number(r[6]) === 1,
})));

// ------------------------------------------------------------------ distance
export const kmBetween = (a: XY, b: XY) => geoDistance(a, b) * 6371.0088;

// ------------------------------------------------------------------ camera
/** A framing: the centre in degrees and the tile zoom (fractional). */
export interface Cam { lon: number; lat: number; z: number }

const TILE = 256;
export const mercX = (lon: number) => (lon + 180) / 360;
export const mercY = (lat: number) => {
  const s = Math.sin((Math.max(-85, Math.min(85, lat)) * Math.PI) / 180);
  return 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI);
};
export const lonOf = (mx: number) => mx * 360 - 180;
export const latOf = (my: number) => (Math.atan(Math.sinh(Math.PI * (1 - 2 * my))) * 180) / Math.PI;

/** World width in px at zoom z for a frame `width` wide (the 1920 frame is the unit). */
export const worldPx = (z: number, width: number) => TILE * 2 ** z * (width / 1920);

/**
 * The d3 Mercator projection of a framing in a W x H frame; `off` shifts it onto a bigger canvas (the tilted
 * plane's: frame point (x, y) is canvas point (x + off[0], y + off[1])), clipped to the canvas `cw` x `ch`.
 */
export const projectionOf = (cam: Cam, W: number, H: number, off: XY = [0, 0], cw = W, ch = H): GeoProjection => {
  const wp = worldPx(cam.z, W);
  // rotated onto the camera's meridian: a map round the date line (Fiji, Kamchatka, Alaska) stays whole
  return geoMercator().rotate([-cam.lon, 0]).scale(wp / (2 * Math.PI))
    .translate([W / 2 + off[0], H / 2 + off[1] + (0.5 - mercY(cam.lat)) * wp])
    .clipExtent([[-40, -40], [cw + 40, ch + 40]]).precision(0.5);
};

/** A point's screen position under a framing. */
export const toScreen = (cam: Cam, W: number, H: number, lon: number, lat: number): XY => {
  const wp = worldPx(cam.z, W);
  let dx = mercX(lon) - mercX(cam.lon);
  if (dx > 0.5) dx -= 1;
  if (dx < -0.5) dx += 1;
  return [W / 2 + dx * wp, H / 2 + (mercY(lat) - mercY(cam.lat)) * wp];
};

/**
 * The framing that shows a box (degrees) inside the frame's safe part: `pad` is the share of each side kept
 * clear, `bias` shifts the box's place (frame shares; e.g. [-0.12, 0] keeps it left of a figure on the right).
 */
export const fitCam = (b: [XY, XY], W: number, H: number, pad = 0.18, maxZ = 9, bias: XY = [0, 0]): Cam => {
  let [[w, s], [e, n]] = b;
  if (e < w) e += 360;
  const x0 = mercX(w), x1 = mercX(e), y0 = mercY(n), y1 = mercY(s);
  const dx = Math.max(1e-6, x1 - x0), dy = Math.max(1e-6, y1 - y0);
  const zx = Math.log2((W * (1 - 2 * pad)) / (dx * worldPx(0, W)));
  const zy = Math.log2((H * (1 - 2 * pad)) / (dy * worldPx(0, W)));
  const z = Math.max(0.6, Math.min(maxZ, Math.min(zx, zy)));
  const wp = worldPx(z, W);
  const cx = (x0 + x1) / 2 - (bias[0] * W) / wp;
  const cy = (y0 + y1) / 2 - (bias[1] * H) / wp;
  let lon = lonOf(cx);
  if (lon > 180) lon -= 360;
  return { lon, lat: latOf(cy), z };
};

/** The box round several points (degrees), at least `minDeg` across. */
export const boxOf = (pts: XY[], minDeg = 0.6): [XY, XY] => {
  let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
  for (const [x, y] of pts) {
    w = Math.min(w, x); e = Math.max(e, x); s = Math.min(s, y); n = Math.max(n, y);
  }
  const cx = (w + e) / 2, cy = (s + n) / 2;
  const hw = Math.max(minDeg, e - w) / 2, hh = Math.max(minDeg * 0.6, n - s) / 2;
  return [[cx - hw, cy - hh], [cx + hw, cy + hh]];
};

/** Union of two boxes. */
export const joinBox = (a: [XY, XY], b: [XY, XY]): [XY, XY] => boxOf([a[0], a[1], b[0], b[1]], 0);

/**
 * The camera between two framings at t (0..1): van Wijk & Nuij's smooth zoom-and-pan (rho = 1.3), the path a
 * viewer reads as one move - out, across, in - with constant perceived speed.
 */
export const flyCam = (a: Cam, b: Cam, t: number): Cam => {
  if (t <= 0) return a;
  if (t >= 1) return b;
  const rho = 1.3, r2 = rho * rho, r4 = r2 * r2;
  // in "zoom-0 world" units: w = the frame's width in world units
  const ux0 = mercX(a.lon), uy0 = mercY(a.lat);
  let ux1 = mercX(b.lon);
  if (ux1 - ux0 > 0.5) ux1 -= 1;
  if (ux1 - ux0 < -0.5) ux1 += 1;
  const uy1 = mercY(b.lat);
  // the frame's width in world units (a 1920 frame shows 1920 / (256 x 2^z) of the zoom-0 world)
  const w0 = 7.5 * 2 ** -a.z, w1 = 7.5 * 2 ** -b.z;
  const dx = ux1 - ux0, dy = uy1 - uy0, d2 = dx * dx + dy * dy, d1 = Math.sqrt(d2);
  let ux: number, uy: number, w: number;
  if (d1 < 1e-9) {
    const S = Math.log(w1 / w0) / rho;
    ux = ux0; uy = uy0; w = w0 * Math.exp(rho * t * S);
  } else {
    const b0 = (w1 * w1 - w0 * w0 + r4 * d2) / (2 * w0 * r2 * d1);
    const b1 = (w1 * w1 - w0 * w0 - r4 * d2) / (2 * w1 * r2 * d1);
    const r0 = Math.log(Math.sqrt(b0 * b0 + 1) - b0);
    const r1 = Math.log(Math.sqrt(b1 * b1 + 1) - b1);
    const S = (r1 - r0) / rho;
    const s = t * S;
    const coshr0 = Math.cosh(r0);
    const u = (w0 / (r2 * d1)) * (coshr0 * Math.tanh(rho * s + r0) - Math.sinh(r0));
    ux = ux0 + u * dx; uy = uy0 + u * dy; w = (w0 * coshr0) / Math.cosh(rho * s + r0);
  }
  let lon = lonOf(((ux % 1) + 1) % 1);
  if (lon > 180) lon -= 360;
  return { lon, lat: latOf(uy), z: -Math.log2(w / 7.5) };
};

/** A gentle drift on a held framing (a slow push in: never a frozen map). */
export const drift = (c: Cam, frames: number, perSecond = 0.035, fps = 30): Cam => ({ ...c, z: c.z + (frames / fps) * perSecond });

const ringArea = (ring: number[][]) => {
  let s = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) s += (ring[j][0] + ring[i][0]) * (ring[j][1] - ring[i][1]);
  return Math.abs(s / 2) * Math.cos((ring[0][1] * Math.PI) / 180);
};
const polysOf = (g: Geometry): number[][][][] => (g.type === "MultiPolygon" ? g.coordinates as number[][][][]
  : g.type === "Polygon" ? [g.coordinates as number[][][]] : []);
const FRAME = new Map<string, [XY, XY]>();
/**
 * The box a camera frames an area on: its main land only - the polygons at least half its largest - so the
 * United States frames the lower 48 (not the Aleutians across the date line) and France its mainland.
 */
export const frameBox = (a: Area): [XY, XY] => {
  const k = `${a.kind}:${a.id}`;
  const got = FRAME.get(k);
  if (got) return got;
  const polys = polysOf(a.geometry).map((p) => ({ p, s: ringArea(p[0]) }));
  const top = Math.max(0, ...polys.map((x) => x.s));
  const keep = polys.filter((x) => x.s >= top * 0.5);
  const box = keep.length ? boxOf(keep.flatMap((x) => x.p[0] as unknown as XY[]), 0.05) : a.bounds;
  FRAME.set(k, box);
  return box;
};

export const areaBox = (areas: Area[]): [XY, XY] => areas.map(frameBox).reduce(joinBox);

const MAIN = new Map<string, Geometry>();
/** An area's main land as one geometry (the same polygons frameBox keeps): France without its overseas parts. */
export const mainGeometry = (a: Area): Geometry => {
  const k = `${a.kind}:${a.id}`;
  const got = MAIN.get(k);
  if (got) return got;
  const polys = polysOf(a.geometry).map((p) => ({ p, s: ringArea(p[0]) }));
  const top = Math.max(0, ...polys.map((x) => x.s));
  const g: Geometry = { type: "MultiPolygon", coordinates: polys.filter((x) => x.s >= top * 0.5).map((x) => x.p) };
  MAIN.set(k, g);
  return g;
};

/** The point a region's label sits on: its biggest polygon's centroid. */
export const labelPoint = (a: Area): XY => {
  if (a.geometry.type !== "MultiPolygon") return a.centroid;
  let best = 0, at: XY = a.centroid;
  for (const poly of polysOf(a.geometry)) {
    const area = ringArea(poly[0]);
    if (area > best) {
      best = area;
      at = geoCentroid({ type: "Polygon", coordinates: poly } as never) as XY;
    }
  }
  return at;
};
