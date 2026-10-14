/**
 * The maps-v2 map itself, drawn on one canvas per frame: a near-black sea, the land in the kit's relief grey, the
 * focus areas filled in the kit's region colour, Natural Earth's shaded relief laid over all the land (overlay
 * blend, so the region's fill shows the terrain too - the owner's reference), the borders and a fine coast light.
 * Or, for a globe, an orthographic earth with its atmosphere.
 *
 * The relief tiles are local files (public/maps2/relief, z0-z5): each frame waits under its own delayRender until
 * the tiles it needs have loaded or failed (a failed tile draws flat), so no frame is ever drawn half-textured and
 * no picture can stop the render (the hold always settles: RELIEF_MS). No remotion <Img> is used (safePicture).
 */
import React from "react";
import { continueRender, delayRender, staticFile, useVideoConfig } from "remotion";
import { geoGraticule10, geoOrthographic, geoPath, type GeoProjection } from "d3-geo";
import manifest from "../../data/maps2/relief_manifest.json";
import { countries, mercX, mercY, projectionOf, regions, regionsOf, worldPx, type Area, type Cam, type XY } from "./geo";
import { alpha, mix, type MapKit } from "./kit";

export interface Fill { area: Area; color: string; opacity: number; glow?: number }
export interface Tilt { deg: number; persp: number }

const RELIEF_MS = 20000;
/** From this zoom (1920-frame tile zoom) the land is drawn from the states / provinces. */
export const FINE_Z = 4.4;
const MAXZ = (manifest as { maxZoom: number }).maxZoom;
const BITS = (manifest as { z: Record<string, string> }).z;
/** Whether the relief tile exists (flat tiles - open sea, plains - were left out of the bundle). */
export const hasTile = (z: number, x: number, y: number) => {
  const s = BITS[String(z)];
  if (!s) return false;
  const i = x + y * 2 ** z;
  const d = s.length - 1 - (i >> 2);
  if (d < 0) return false;
  return ((parseInt(s[d], 16) >> (i & 3)) & 1) === 1;
};
const tileUrl = (z: number, x: number, y: number) => staticFile(`maps2/relief/${z}/${x}_${y}.jpg`);

// ------------------------------------------------------------------ the tiles: load once, always settle
const IMG = new Map<string, HTMLImageElement | null>();
const LOADING = new Map<string, Promise<void>>();
const loadTile = (url: string): Promise<void> => {
  if (IMG.has(url)) return Promise.resolve();
  const busy = LOADING.get(url);
  if (busy) return busy;
  const p = new Promise<void>((resolve) => {
    const img = new Image();
    let done = false;
    const end = (ok: boolean) => {
      if (done) return;
      done = true;
      IMG.set(url, ok && img.naturalWidth > 0 ? img : null);
      LOADING.delete(url);
      resolve();
    };
    const timer = setTimeout(() => end(false), RELIEF_MS);
    img.onload = () => {
      clearTimeout(timer);
      // decoded before the frame is drawn (a canvas draw of an undecoded picture can come out blank)
      const dec = typeof img.decode === "function" ? img.decode().catch(() => undefined) : Promise.resolve();
      dec.then(() => end(true));
    };
    img.onerror = () => {
      clearTimeout(timer);
      end(false);
    };
    img.src = url;
  });
  LOADING.set(url, p);
  return p;
};

type TileRef = { url: string; o: number; sx: number; sy: number; size: number };

/**
 * The relief tiles a framing needs on a cw x ch canvas whose frame centre sits at (W/2 + off[0], H/2 + off[1]):
 * one level, the next fading in as the camera zooms toward it.
 */
const tilesFor = (cam: Cam, W: number, H: number, cw: number, ch: number, off: XY): TileRef[] => {
  const lvl = Math.max(0, cam.z + Math.log2(W / 1920) + 0.35);
  const base = Math.min(MAXZ, Math.floor(lvl));
  const frac = lvl - base;
  const levels: { z: number; o: number }[] = [{ z: base, o: 1 }];
  if (base + 1 <= MAXZ && frac > 0.45) levels.push({ z: base + 1, o: Math.min(1, (frac - 0.45) / 0.45) });
  const wp = worldPx(cam.z, W);
  const left = mercX(cam.lon) - (W / 2 + off[0]) / wp;
  const top = mercY(cam.lat) - (H / 2 + off[1]) / wp;
  const out: TileRef[] = [];
  for (const { z, o } of levels) {
    const n = 2 ** z;
    const tx0 = Math.floor(left * n), tx1 = Math.floor((left + cw / wp) * n);
    const ty0 = Math.max(0, Math.floor(top * n)), ty1 = Math.min(n - 1, Math.floor((top + ch / wp) * n));
    for (let ty = ty0; ty <= ty1; ty++) {
      for (let tx = tx0; tx <= tx1; tx++) {
        const x = ((tx % n) + n) % n;
        if (!hasTile(z, x, ty)) continue;
        out.push({ url: tileUrl(z, x, ty), o, sx: (tx / n - left) * wp, sy: (ty / n - top) * wp, size: wp / n });
      }
    }
  }
  return out;
};

/** Holds the frame until every tile in `urls` has settled; returns a counter that changes when they have. */
const useTiles = (urls: string[]): number => {
  const [n, setN] = React.useState(0);
  const missing = urls.filter((u) => !IMG.has(u));
  const key = missing.join("|");
  const handle = React.useRef<number | null>(null);
  if (missing.length && handle.current === null) handle.current = delayRender(`maps2 relief (${missing.length})`, { timeoutInMilliseconds: RELIEF_MS + 15000 });
  React.useEffect(() => {
    if (!key) return;
    let live = true;
    Promise.all(key.split("|").map(loadTile)).then(() => {
      if (live) setN((v) => v + 1);
    });
    return () => {
      live = false;
    };
  }, [key]);
  React.useEffect(() => {
    // after the frame drawn with every tile (the canvas effect runs first: it is a layout effect)
    if (!missing.length && handle.current !== null) {
      continueRender(handle.current);
      handle.current = null;
    }
  });
  React.useEffect(() => () => {
    if (handle.current !== null) continueRender(handle.current);
  }, []);
  return n;
};

// ------------------------------------------------------------------ drawing
const inView = (a: Area, b: { w: number; e: number; s: number; n: number }) => {
  const [[w, s], [e, n]] = a.bounds;
  if (n < b.s || s > b.n) return false;
  if (b.e - b.w >= 350) return true;
  if (e < w) return true;
  const sh = (x: number, c: number) => x + 360 * Math.round((c - x) / 360);
  const cw = sh(w, (b.w + b.e) / 2), ce = cw + (e - w);
  return ce >= b.w && cw <= b.e;
};

/** The framing's view in degrees (west / east may run past +-180: inView shifts each area to the view's side). */
const viewBox = (cam: Cam, W: number, H: number, cw: number, ch: number, off: XY) => {
  const wp = worldPx(cam.z, W);
  const half = ((cw / 2 + Math.abs(off[0]) + 80) / wp) * 360;
  const top = mercY(cam.lat) - (H / 2 + off[1] + 80) / wp;
  const bottom = top + (ch + 160) / wp;
  const lat = (y: number) => (Math.atan(Math.sinh(Math.PI * (1 - 2 * Math.max(0, Math.min(1, y))))) * 180) / Math.PI;
  return half >= 180 ? { w: -180, e: 180, n: lat(top), s: lat(bottom) }
    : { w: cam.lon - half, e: cam.lon + half, n: lat(top), s: lat(bottom) };
};

export interface MapLayers {
  /** Areas filled over the land (in order), each with its colour and opacity 0..1. */
  fills?: Fill[];
  /** Relief strength 0..1 (default 1). */
  relief?: number;
  /** A country whose states / provinces show their lines (zoomed in). */
  inner?: string;
  /** Dim everything but the fills (0..1). */
  dim?: number;
}

/** Draw a Mercator map of a framing onto ctx (cw x ch canvas, frame centre at W/2 + off). */
export const drawFlat = (ctx: CanvasRenderingContext2D, cam: Cam, W: number, H: number, cw: number, ch: number, off: XY,
  kit: MapKit, layers: MapLayers, tiles: TileRef[]) => {
  const proj = projectionOf(cam, W, H, off, cw, ch);
  const path = geoPath(proj, ctx);
  const vb = viewBox(cam, W, H, cw, ch, off);
  const u = W / 1920;
  // Close in (a state, a city's surroundings) the land is drawn from the 1:10m states / provinces, whose coasts hold
  // up at that scale; further out from the 1:50m countries.
  const fine = cam.z + Math.log2(u) > FINE_Z;
  // (Antarctica is left as sea: in Mercator it would swallow the bottom of every world view)
  const land = (fine ? regions() : countries()).filter((a) => a.a3 !== "ATA" && inView(a, vb));
  const shapes = (a: Area) => (fine && a.kind === "country" ? regionsOf(a.a3).map((r) => r.geometry) : [a.geometry]);
  // sea: a soft pool of light at the centre, darker toward the edges
  const g = ctx.createRadialGradient(W / 2 + off[0], H / 2 + off[1], 0, W / 2 + off[0], H / 2 + off[1], Math.max(cw, ch) * 0.75);
  g.addColorStop(0, kit.sea2);
  g.addColorStop(1, kit.sea);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, cw, ch);
  // land
  ctx.beginPath();
  for (const a of land) path(a.geometry as never);
  ctx.fillStyle = kit.land;
  ctx.fill();
  // fills
  for (const f of layers.fills || []) {
    if (f.opacity <= 0) continue;
    ctx.beginPath();
    for (const gm of shapes(f.area)) path(gm as never);
    ctx.globalAlpha = Math.min(1, f.opacity);
    ctx.fillStyle = f.color;
    ctx.fill();
    ctx.globalAlpha = 1;
  }
  // relief over all the land (the fills included)
  // (past the bundled detail - z5 tiles - the relief softens away rather than turn to blur)
  const rel = (layers.relief ?? 1) * Math.max(0.25, Math.min(1, 1 - (cam.z + Math.log2(u) - 7.2) / 1.6));
  if (rel > 0 && tiles.length) {
    ctx.save();
    ctx.beginPath();
    for (const a of land) path(a.geometry as never);
    ctx.clip();
    ctx.globalCompositeOperation = "overlay";
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    for (const t of tiles) {
      const img = IMG.get(t.url);
      if (!img) continue;
      ctx.globalAlpha = rel * t.o;
      ctx.drawImage(img, t.sx - 0.5, t.sy - 0.5, t.size + 1, t.size + 1);
    }
    ctx.restore();
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
  }
  // a country's inner lines (states / provinces), when close enough to read them
  if (!fine && layers.inner && cam.z + Math.log2(u) > 2.6) {
    ctx.beginPath();
    for (const r of regionsOf(layers.inner)) if (inView(r, vb)) path(r.geometry as never);
    ctx.strokeStyle = "rgba(20,21,24,0.45)";
    ctx.lineWidth = 1.1 * u;
    ctx.stroke();
  }
  // borders and the coast light (close in: every state / province line, lighter)
  ctx.beginPath();
  for (const a of land) path(a.geometry as never);
  ctx.strokeStyle = fine ? "rgba(16,17,20,0.5)" : kit.border;
  ctx.lineWidth = (fine ? 1.2 : 1.4) * u;
  ctx.stroke();
  ctx.strokeStyle = "rgba(255,255,255,0.07)";
  ctx.lineWidth = 0.8 * u;
  ctx.stroke();
  // dim the rest, keep the fills lit
  const dim = layers.dim ?? 0;
  if (dim > 0) {
    ctx.save();
    ctx.globalAlpha = dim * 0.55;
    ctx.fillStyle = "#000";
    ctx.beginPath();
    ctx.rect(0, 0, cw, ch);
    for (const f of layers.fills || []) for (const gm of shapes(f.area)) path(gm as never);
    ctx.fill("evenodd");
    ctx.restore();
  }
  // the fills' edges: a light rim and a soft glow (a country drawn from its states: the glow only, no inner rims)
  for (const f of layers.fills || []) {
    if (f.opacity <= 0) continue;
    const parts = shapes(f.area);
    ctx.beginPath();
    for (const gm of parts) path(gm as never);
    ctx.save();
    ctx.shadowColor = alpha(f.color, 0.9 * Math.min(1, f.opacity));
    ctx.shadowBlur = (f.glow ?? 0.5) * 26 * u;
    ctx.strokeStyle = alpha(mix(f.color, "#ffffff", 0.5), (parts.length > 1 ? 0.0 : 0.85) * Math.min(1, f.opacity));
    ctx.lineWidth = 1.8 * u;
    ctx.stroke();
    ctx.restore();
  }
};

/** Draw an orthographic globe: radius r, facing [lon, lat], spin in degrees; fills on its land. */
export const drawGlobe = (ctx: CanvasRenderingContext2D, W: number, H: number, center: XY, r: number, face: XY,
  kit: MapKit, fills: Fill[], bg = true) => {
  const proj = geoOrthographic().scale(r).translate(center).rotate([-face[0], -face[1]]).clipAngle(90).precision(0.6);
  const path = geoPath(proj, ctx);
  const u = W / 1920;
  if (bg) {
    ctx.fillStyle = kit.sea;
    ctx.fillRect(0, 0, W, H);
  }
  // atmosphere
  const atm = ctx.createRadialGradient(center[0], center[1], r * 0.92, center[0], center[1], r * 1.22);
  atm.addColorStop(0, alpha(mix(kit.region, "#ffffff", 0.35), 0.38));
  atm.addColorStop(1, alpha(kit.region, 0));
  ctx.fillStyle = atm;
  ctx.beginPath();
  ctx.arc(center[0], center[1], r * 1.22, 0, Math.PI * 2);
  ctx.fill();
  // ocean sphere
  const sea = ctx.createRadialGradient(center[0] - r * 0.35, center[1] - r * 0.4, r * 0.1, center[0], center[1], r);
  sea.addColorStop(0, mix(kit.sea2, "#3a3f4a", 0.45));
  sea.addColorStop(1, mix(kit.sea, "#000000", 0.2));
  ctx.fillStyle = sea;
  ctx.beginPath();
  path({ type: "Sphere" } as never);
  ctx.fill();
  // graticule
  ctx.beginPath();
  path(geoGraticule10() as never);
  ctx.strokeStyle = "rgba(255,255,255,0.05)";
  ctx.lineWidth = 1 * u;
  ctx.stroke();
  // land
  ctx.beginPath();
  for (const a of countries()) if (a.a3 !== "ATA") path(a.geometry as never);
  ctx.fillStyle = mix(kit.land, "#ffffff", 0.05);
  ctx.fill();
  ctx.strokeStyle = kit.border;
  ctx.lineWidth = 0.9 * u;
  ctx.stroke();
  for (const f of fills) {
    if (f.opacity <= 0) continue;
    ctx.beginPath();
    path(f.area.geometry as never);
    ctx.globalAlpha = Math.min(1, f.opacity);
    ctx.fillStyle = f.color;
    ctx.fill();
    ctx.globalAlpha = 1;
    ctx.save();
    ctx.shadowColor = alpha(f.color, 0.9);
    ctx.shadowBlur = 18 * u;
    ctx.strokeStyle = alpha(mix(f.color, "#ffffff", 0.5), 0.8 * f.opacity);
    ctx.lineWidth = 1.4 * u;
    ctx.stroke();
    ctx.restore();
  }
  // light: a lit limb top-left, the night side bottom-right
  const shade = ctx.createRadialGradient(center[0] - r * 0.45, center[1] - r * 0.5, r * 0.15, center[0], center[1], r * 1.02);
  shade.addColorStop(0, "rgba(255,255,255,0.10)");
  shade.addColorStop(0.55, "rgba(0,0,0,0)");
  shade.addColorStop(1, "rgba(0,0,0,0.55)");
  ctx.fillStyle = shade;
  ctx.beginPath();
  path({ type: "Sphere" } as never);
  ctx.fill();
  return proj;
};

/** A point on the tilted plane (frame px from the frame's top-left, h px up out of the plane) on screen. */
export const tiltPoint = (x: number, y: number, h: number, t: Tilt | null | undefined, W: number, H: number): XY => {
  if (!t || !t.deg) return [x, y - h];
  const a = (t.deg * Math.PI) / 180;
  const X = x - W / 2, Y = y - H / 2;
  const y2 = Y * Math.cos(a) - h * Math.sin(a);
  const z2 = Y * Math.sin(a) + h * Math.cos(a);
  const s = 1 / (1 - z2 / t.persp);
  return [W / 2 + X * s, H / 2 + y2 * s];
};

/** How much bigger than the frame the tilted plane's canvas is drawn (it must still fill the frame's top). */
const PLANE = 1.9;
/** ... and in a vertical frame, whose far edge would otherwise show. */
const PLANE_TALL = 2.6;

/**
 * The map layer: a Mercator framing (cam), or a globe (globe set), drawn on a canvas each frame. `tilt` lays the
 * map plane back in 3D (CSS perspective + rotateX about the frame's centre; tiltPoint gives the matching screen
 * position of anything drawn over it).
 */
export const MapCanvas: React.FC<{
  cam: Cam;
  kit: MapKit;
  layers?: MapLayers;
  tilt?: Tilt | null;
  globe?: { center: XY; r: number; face: XY; fills: Fill[] } | null;
  opacity?: number;
}> = ({ cam, kit, layers = {}, tilt, globe, opacity = 1 }) => {
  const { width: W, height: H } = useVideoConfig();
  const ref = React.useRef<HTMLCanvasElement>(null);
  const big = !!tilt && tilt.deg > 0;
  const plane = W < H ? PLANE_TALL : PLANE;
  const cw = Math.round(big ? W * plane : W), ch = Math.round(big ? H * plane : H);
  const off: XY = [(cw - W) / 2, (ch - H) / 2];
  const tiles = globe ? [] : tilesFor(cam, W, H, cw, ch, off);
  const ready = useTiles(tiles.map((t) => t.url));
  React.useLayoutEffect(() => {
    const c = ref.current;
    const ctx = c?.getContext("2d");
    if (!c || !ctx) return;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, cw, ch);
    if (globe) drawGlobe(ctx, W, H, globe.center, globe.r, globe.face, kit, globe.fills);
    else drawFlat(ctx, cam, W, H, cw, ch, off, kit, layers, tiles);
  });
  void ready;
  const style: React.CSSProperties = big
    ? { position: "absolute", left: -off[0], top: -off[1], width: cw, height: ch, opacity,
      transform: `perspective(${tilt!.persp}px) rotateX(${tilt!.deg}deg)`, transformOrigin: "50% 50%" }
    : { position: "absolute", left: 0, top: 0, width: W, height: H, opacity };
  return <canvas ref={ref} width={cw} height={ch} style={style} />;
};

/** The projection a frame's overlays use (the same framing as the map; frame coordinates). */
export const useProjection = (cam: Cam): GeoProjection => {
  const { width: W, height: H } = useVideoConfig();
  return projectionOf(cam, W, H, [0, 0], W, H);
};
