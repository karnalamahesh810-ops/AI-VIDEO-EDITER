import React from "react";
import { AbsoluteFill } from "remotion";
import { geoCentroid, geoContains, geoDistance, geoGraticule, geoMercator, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import worldTopology from "world-atlas/countries-110m.json";
import statesTopology from "../../data/us-states.json";
import { GROTESK, GROTESK_CAP, MONO } from "../fonts";
import { backOut, clamp01, cubicInOut, cubicOut, expoOut, idle, lerp, prog } from "../motion/ease";
import { Grain, guard, rgba, useSvgId, type Look } from "./proKit";
import { coordText, placeName, placesOf, str } from "./proFormat";
import { WHITE, softShadow, widthOf } from "./typeKit";
import { useLook } from "./LibKinetic";
import { Caps, DIM, Glass, RiseLine, capsWidth, riseWidth } from "./LibKtDates";
import scale from "./typeScale.json";

/**
 * THE LOOK PACK, its places (2026-10-07; LibKtPack.tsx has the words and the
 * data, LibKtPictures.tsx the pictures). A place the narration names, from the
 * gazetteer's coordinates only (overlay.locations: src/geocode.py, never a
 * model's guess), drawn on the bundled outlines (the US states, else the
 * world's countries) - no tiles, no network:
 *
 *   kt-locator   LOCATOR MAP   full frame: a dark map of the country, the camera easing in to the
 *                              place (frames 6-54) while a dot marks it; a ring draws round it on the
 *                              landing and pings out, its glass tag (the name, the region, the
 *                              coordinates) opens on a leader line, a scale bar measures the view
 *   kt-place     PLACE TAG     low left on the footage: a frosted card with a small map of the
 *                              state (or the country) the place is in - its outline drawing on, the
 *                              place's dot dropping in and rippling - beside its name and region
 *
 * The owner, 2026-10-05: zoom-ins with circles and rings, smooth eased motion;
 * the type system of every kt- look (white bold grotesk, one accent, glass).
 */

type Feat = { type: string; id?: string | number; properties?: { name?: string }; geometry: unknown };
type FeatColl = { type: "FeatureCollection"; features: Feat[] };
const WORLD = (feature(worldTopology as never, worldTopology.objects.countries as never) as unknown as FeatColl).features
  .filter((x) => x.properties?.name !== "Antarctica");
const STATES = (feature(statesTopology as never, statesTopology.objects.states as never) as unknown as FeatColl).features;
const inUS = (p: { lat: number; lon: number }) => p.lat > 18 && p.lat < 72 && p.lon > -170 && p.lon < -64;
const R_MILES = 3958.8;
const unitOf = (W: number, H: number) => Math.min(H, (W * 9) / 16);
const capFont = (sh: number, U: number, ks: number, cap = GROTESK_CAP) => (sh * U * ks) / cap;

/**
 * The state (in the US) or the country a place is in: the one its gazetteer label names when that one is
 * near ("Lake Mead, Nevada" sits on the Nevada / Arizona line), else the one containing it, else the nearest.
 */
const regionOf = (p: { lat: number; lon: number }, named = ""): Feat | null => {
  const set = inUS(p) ? STATES : WORLD;
  const pt: [number, number] = [p.lon, p.lat];
  const want = named.trim().toLowerCase();
  if (want) {
    const g = set.find((x) => String(x.properties?.name || "").toLowerCase() === want);
    try {
      if (g && geoDistance(geoCentroid(g as never) as [number, number], pt) < 0.16) return g;
    } catch {
      // fall through to the containing one
    }
  }
  for (const g of set) {
    try {
      if (geoContains(g as never, pt)) return g;
    } catch {
      // a malformed outline: skip it
    }
  }
  let best: Feat | null = null;
  let d = Infinity;
  for (const g of set) {
    try {
      const c = geoCentroid(g as never) as [number, number];
      const dd = geoDistance(c, pt);
      if (dd < d) {
        d = dd;
        best = g;
      }
    } catch {
      // skip
    }
  }
  return d < 0.12 ? best : null;
};

/** A round length for a scale bar between `lo` and `hi` px at `pxPerUnit`. */
const niceBar = (pxPerUnit: number, lo: number, hi: number): number => {
  const steps = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000];
  return steps.find((s) => s * pxPerUnit >= lo && s * pxPerUnit <= hi) ?? steps.reduce((a, s) => (Math.abs(s * pxPerUnit - (lo + hi) / 2)
    < Math.abs(a * pxPerUnit - (lo + hi) / 2) ? s : a), 1);
};

// ================================================================== kt-locator
/**
 * The place on a dark map, full frame. The camera starts wide (the contiguous
 * US for a place in it, else about 2,600 miles round the place) with a dot
 * already on the place so the eye has it, and eases in (frames 6-54, cubic
 * in-out, zoom and pan as one move: the place glides to its spot left of
 * centre) to a view about 420 miles across (600 outside the US); the state or
 * country it is in lifts out of the dark with an accent edge. On the landing a
 * ring draws round the place and two rings ping out of it, a leader draws to
 * its glass tag - the kicker, the name, the region and the coordinates - and a
 * scale bar measures the view (a round number of miles, kilometres outside
 * the US). The camera keeps creeping in while it holds.
 */
const Locator: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, hot, out, ks } = useLook(overlay, accent);
  const clipId = useSvgId("ktlocclip");
  const glowId = useSvgId("ktlocglow");
  const A = placesOf(overlay.locations, 1)[0];
  if (!A) return null;
  const pn = placeName(A.label);
  const name = (pn.name || str(overlay.text)).toUpperCase();
  if (!name) return null;
  const region = str(overlay.subtitle) || pn.region;
  const textKicker = str(overlay.text);
  const kicker = (str(overlay.label) || (textKicker && textKicker.toUpperCase() !== name ? textKicker : "Location")).toUpperCase();
  const us = inUS(A);
  const geo = us ? STATES : WORLD;
  const home = regionOf(A, pn.region);
  const U = unitOf(W, H);
  const C: [number, number] = [W / 2, H / 2];
  const place: [number, number] = [0.42 * W, 0.53 * H];
  const cosLat = Math.max(0.2, Math.cos((A.lat * Math.PI) / 180));
  const across = us ? 820 : 1100;
  const s1 = (W * R_MILES * cosLat) / across;
  const proj = geoMercator().center([A.lon, A.lat]).scale(s1).translate(place);
  const path = geoPath(proj as never);
  // the wide view: its centre (the US's middle, or the place) and zoom
  const wideCentre: [number, number] = us ? [-98.6, 39.2] : [A.lon, A.lat];
  const z0 = across / (us ? 3500 : 3200);
  const m0 = (proj(wideCentre) as [number, number]) || place;
  const s0: [number, number] = [(place[0] - m0[0]) * z0 + C[0], (place[1] - m0[1]) * z0 + C[1]];
  const cam = prog(f, 6, 48, S, cubicInOut);
  const land = 54;
  const creep = 1 + 0.035 * idle(f, land * S, dur);
  const z = Math.exp(lerp(Math.log(z0), 0, cam)) * creep;
  const sA: [number, number] = [lerp(s0[0], place[0], cam), lerp(s0[1], place[1], cam)];
  // the map point under the screen's centre, so that the place sits at sA at zoom z
  const m: [number, number] = [place[0] - (sA[0] - C[0]) / z, place[1] - (sA[1] - C[1]) / z];
  const toScreen = (p: [number, number]): [number, number] => [(p[0] - m[0]) * z + C[0], (p[1] - m[1]) * z + C[1]];
  const grat = geoGraticule().step(us ? [2, 2] : [5, 5]).extent([[A.lon - 60, A.lat - 35], [A.lon + 60, A.lat + 35]]);
  const o = prog(f, 0, 10, S, cubicOut) * (1 - clamp01(out * 1.2));
  const xo = 1 - clamp01(out * 1.4);
  // the marks on the place (screen space)
  const P = toScreen(place);
  const ringR = 30 * k;
  const ring = prog(f, land - 4, 18, S, cubicInOut) * xo;
  const dot = prog(f, 2, 12, S, (u) => backOut(u, 1.6)) * xo;
  const t = f / S;
  const pings = [0, 1].map((i) => {
    const p = ((t - land - i * 14) % 42) / 42;
    return t >= land + i * 14 ? clamp01(p) : -1;
  });
  // the tag: right of the place, the leader from the ring
  const nSize = capFont(scale.pack.mapLabel.share, U, ks);
  const kSize = capFont(scale.pack.packKicker.share, U, ks);
  const sSize = capFont(scale.pack.placeSmall.share, U, ks);
  const coords = coordText(A.lat, A.lon, 4);
  const sub = region ? region.toUpperCase() : "";
  const nameW = riseWidth(name, GROTESK, nSize, 800, 0.01);
  const padX = 0.5 * nSize, padY = 0.36 * nSize;
  const tagW = Math.max(nameW, capsWidth(kicker, kSize), sub ? capsWidth(sub, sSize, 0.16) : 0,
    widthOf(coords, MONO, sSize, 600, 0.04)) + padX * 2;
  const tagH = padY * 2 + kSize + 0.22 * nSize + nSize * 1.2 + 0.18 * nSize + (sub ? sSize + 10 * k : 0) + sSize;
  const tagX = Math.min(W - 0.06 * W - tagW, P[0] + ringR + 90 * k);
  const tagY = Math.max(0.1 * H, P[1] - tagH - 40 * k);
  const lead = prog(f, land + 2, 12, S, cubicInOut) * xo;
  const a0: [number, number] = [P[0] + ringR * 0.72 + 4 * k, P[1] - ringR * 0.72 - 4 * k];
  const a1: [number, number] = [tagX, tagY + tagH * 0.62];
  const knee: [number, number] = [a0[0] + Math.min(46 * k, (a1[0] - a0[0]) * 0.4), a1[1]];
  // the scale bar: a round distance, 120-240 px at the landed zoom
  const pxPerMile = (s1 * z) / (R_MILES * cosLat);
  const unit = us ? "MI" : "KM";
  const pxPerUnit = us ? pxPerMile : pxPerMile / 1.609344;
  const barUnits = niceBar(pxPerUnit, 120 * k, 240 * k);
  const barW = barUnits * pxPerUnit;
  const barIn = prog(f, land + 8, 16, S, expoOut) * xo;
  // the names of the land round the place, faint, once the camera has landed
  const names = prog(f, land - 16, 22, S, cubicOut) * xo * 0.5;
  const label = (g: Feat) => {
    try {
      const c = proj(geoCentroid(g as never) as [number, number]) as [number, number] | null;
      return c ? { c: toScreen(c), n: String(g.properties?.name || "").toUpperCase() } : null;
    } catch {
      return null;
    }
  };
  const nearTag = (q: [number, number]) => q[0] > tagX - 60 * k && q[0] < tagX + tagW + 60 * k && q[1] > tagY - 40 * k
    && q[1] < tagY + tagH + 40 * k;
  return (
    <AbsoluteFill style={{ opacity: o, background: "radial-gradient(ellipse 90% 80% at 45% 50%, #0a1018 0%, #05080d 62%, #030407 100%)" }}>
      <AbsoluteFill style={{ transformOrigin: "0 0",
        transform: `translate(${C[0].toFixed(1)}px, ${C[1].toFixed(1)}px) scale(${z.toFixed(5)}) translate(${(-m[0]).toFixed(1)}px, ${(-m[1]).toFixed(1)}px)` }}>
        <svg width={W} height={H} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          <defs>
            <clipPath id={clipId}>{geo.map((g, i) => <path key={i} d={path(g as never) || ""} />)}</clipPath>
            <filter id={glowId} x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation={6} />
            </filter>
          </defs>
          <path d={path(grat() as never) || ""} fill="none" stroke="rgba(150,175,205,0.07)" strokeWidth={1.2 * k}
            vectorEffect="non-scaling-stroke" />
          {geo.map((g, i) => <path key={`f${i}`} d={path(g as never) || ""} fill={g === home ? "#22344c" : "#172231"} />)}
          {home ? (
            <path d={path(home as never) || ""} fill="none" stroke={rgba(hot, 0.5)} strokeWidth={9 * k} vectorEffect="non-scaling-stroke"
              filter={`url(#${glowId})`} opacity={prog(f, land - 14, 20, S, cubicOut) * xo} clipPath={`url(#${clipId})`} />
          ) : null}
          {geo.map((g, i) => (g === home ? null : <path key={`s${i}`} d={path(g as never) || ""} fill="none" stroke="#4a5d76"
            strokeWidth={1.4 * k} vectorEffect="non-scaling-stroke" />))}
          {home ? <path d={path(home as never) || ""} fill="none" stroke={rgba(hot, 0.9)} strokeWidth={2.4 * k}
            vectorEffect="non-scaling-stroke" opacity={0.35 + 0.65 * prog(f, land - 14, 20, S, cubicOut)} /> : null}
        </svg>
      </AbsoluteFill>
      {/* a soft light on the place, so the eye lands there */}
      <AbsoluteFill style={{ mixBlendMode: "screen", pointerEvents: "none", opacity: prog(f, 20, 34, S, cubicOut) * xo,
        background: `radial-gradient(circle ${(0.6 * H).toFixed(0)}px at ${P[0].toFixed(0)}px ${P[1].toFixed(0)}px, rgba(120,150,190,0.1) 0%, `
          + "rgba(120,150,190,0.05) 35%, rgba(120,150,190,0.015) 70%, rgba(120,150,190,0) 100%)" }} />
      {/* faint names of the land round it */}
      {names > 0.01 ? (
        <AbsoluteFill style={{ opacity: names }}>
          {geo.map((g, i) => {
            const l = label(g);
            if (!l || !l.n || l.c[0] < 0.06 * W || l.c[0] > 0.94 * W || l.c[1] < 0.07 * H || l.c[1] > 0.9 * H) return null;
            if (Math.hypot(l.c[0] - P[0], l.c[1] - P[1]) < 120 * k || nearTag(l.c)) return null;
            return (
              <div key={i} style={{ position: "absolute", left: l.c[0], top: l.c[1], transform: "translate(-50%, -50%)",
                fontFamily: GROTESK, fontWeight: 700, fontSize: sSize, letterSpacing: "0.3em", color: "rgba(196,210,228,1)",
                whiteSpace: "nowrap" }}>{l.n}</div>
            );
          })}
        </AbsoluteFill>
      ) : null}
      <svg width={W} height={H} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
        {pings.map((p, i) => (p >= 0 && p < 1 ? (
          <circle key={i} cx={P[0]} cy={P[1]} r={ringR * (1 + 2.2 * cubicOut(p))} fill="none" stroke={hot} strokeWidth={2.2 * k}
            opacity={(1 - p) * 0.75 * xo} />
        ) : null))}
        <circle cx={P[0]} cy={P[1]} r={ringR} fill="none" stroke={hot} strokeWidth={Math.max(2.5, 4 * k)} pathLength={1}
          strokeDasharray="1 1" strokeDashoffset={1 - ring} transform={`rotate(-90 ${P[0]} ${P[1]})`}
          style={{ filter: `drop-shadow(0 0 ${(8 * k).toFixed(1)}px ${rgba(hot, 0.6)})` }} />
        <circle cx={P[0]} cy={P[1]} r={9 * k * dot} fill="#fff" stroke={hot} strokeWidth={4 * k * dot} />
        {lead > 0.001 ? (
          <path d={`M${a0[0].toFixed(1)},${a0[1].toFixed(1)} L${knee[0].toFixed(1)},${knee[1].toFixed(1)} L${a1[0].toFixed(1)},${a1[1].toFixed(1)}`}
            pathLength={1} fill="none" stroke="rgba(255,255,255,0.9)" strokeWidth={Math.max(1.5, 2.5 * k)} strokeLinecap="round"
            strokeLinejoin="round" strokeDasharray="1 1" strokeDashoffset={1 - lead}
            style={{ filter: `drop-shadow(0 ${(1 * k).toFixed(1)}px ${(3 * k).toFixed(1)}px rgba(0,0,0,0.6))` }} />
        ) : null}
      </svg>
      <Glass x={tagX} y={tagY} w={tagW} h={tagH} k={k} p={prog(f, land + 6, 16, S, expoOut)} out={out} radius={14}>
        <div style={{ position: "absolute", left: padX, top: padY }}>
          <div style={{ height: kSize, marginBottom: 0.22 * nSize }}>
            <Caps text={kicker} size={kSize} color={hot} at={land + 9} out={out} k={k} />
          </div>
          <RiseLine text={name} size={nSize} font={GROTESK} weight={800} at={land + 11} out={out} k={k} tracking={0.01} />
          <div style={{ height: 0.18 * nSize }} />
          {sub ? (
            <div style={{ height: sSize, marginBottom: 10 * k }}>
              <Caps text={sub} size={sSize} color="rgba(250,250,247,0.86)" at={land + 15} out={out} k={k} tracking={0.16} />
            </div>
          ) : null}
          <div style={{ fontFamily: MONO, fontWeight: 600, fontSize: sSize, lineHeight: 1, color: DIM, whiteSpace: "nowrap",
            letterSpacing: "0.04em", opacity: prog(f, land + 18, 12, S, cubicOut) * xo }}>{coords}</div>
        </div>
      </Glass>
      {/* the scale bar, low left */}
      <div style={{ position: "absolute", left: 0.068 * W, bottom: 0.1 * H, opacity: barIn }}>
        <div style={{ fontFamily: GROTESK, fontWeight: 700, fontSize: sSize, letterSpacing: "0.12em", color: WHITE,
          textShadow: softShadow(k, 0.6), marginBottom: 10 * k, whiteSpace: "nowrap" }}>{`${barUnits.toLocaleString("en-US")} ${unit}`}</div>
        <div style={{ position: "relative", width: barW * barIn, height: 10 * k }}>
          <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: Math.max(2, 3 * k), background: WHITE,
            boxShadow: "0 1px 4px rgba(0,0,0,0.6)" }} />
          <div style={{ position: "absolute", left: 0, bottom: 0, width: Math.max(2, 3 * k), height: 10 * k, background: WHITE }} />
          <div style={{ position: "absolute", right: 0, bottom: 0, width: Math.max(2, 3 * k), height: 10 * k, background: WHITE }} />
          <div style={{ position: "absolute", left: 0, bottom: 0, width: "50%", height: Math.max(2, 3 * k), background: hot }} />
        </div>
      </div>
      <Grain opacity={0.05} />
      <AbsoluteFill style={{ pointerEvents: "none", background: "radial-gradient(ellipse 75% 70% at 45% 50%, rgba(0,0,0,0) 55%, rgba(0,0,0,0.5) 100%)" }} />
    </AbsoluteFill>
  );
};

// ================================================================== kt-place
/**
 * A place named on footage of it, as a frosted card low left: a small map of
 * the state (in the US) or the country the place is in - its neighbours faint,
 * its outline drawing on (frames 8-30), its face filling - and the place's dot
 * dropping in (24) and rippling once; beside it the kicker, the name rising
 * letter by letter and the region (or what the planner says it is). The card
 * opens from its side and closes back into it.
 */
const PlaceTag: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, hot, out, ks } = useLook(overlay, accent);
  const clip = useSvgId("ktplace");
  const A = placesOf(overlay.locations, 1)[0];
  if (!A) return null;
  const pn = placeName(A.label);
  const name = (str(overlay.text) || pn.name).toUpperCase();
  if (!name) return null;
  const sub = (str(overlay.subtitle) || pn.region).toUpperCase();
  const kicker = str(overlay.label).toUpperCase();
  const home = regionOf(A, pn.region);
  const U = unitOf(W, H);
  const Sm = scale.pack.miniMap.share * U * ks;
  const nSize0 = capFont(scale.pack.placeName.share, U, ks);
  const kSize = capFont(scale.pack.packKicker.share, U, ks);
  const sSize = capFont(scale.pack.placeSmall.share, U, ks);
  let nSize = nSize0;
  while (nSize > nSize0 * 0.74 && riseWidth(name, GROTESK, nSize, 800, 0.01) > 0.34 * W) nSize *= 0.96;
  const nameW = riseWidth(name, GROTESK, nSize, 800, 0.01);
  if (nameW > 0.36 * W) return null;
  const pad = 18 * k;
  const gap = 22 * k;
  const colW = Math.max(nameW, kicker ? capsWidth(kicker, kSize) : 0, sub ? capsWidth(sub, sSize, 0.16) : 0);
  const colH = (kicker ? kSize + 0.22 * nSize : 0) + nSize * 1.2 + (sub ? 0.2 * nSize + sSize : 0);
  const w = pad + Sm + gap + colW + pad * 1.4;
  const h = Math.max(Sm, colH) + pad * 2;
  const mx = scale.safe.x * W;
  const avoid = Array.isArray(overlay.avoid) ? overlay.avoid : [];
  const bottomY = H - scale.safe.bottom * H - h;
  const leftBox = { x: mx / W, y: bottomY / H, w: w / W, h: h / H };
  const hitsLeft = avoid.some((b) => b.x < leftBox.x + leftBox.w && b.x + b.w > leftBox.x && b.y < leftBox.y + leftBox.h && b.y + b.h > leftBox.y);
  const rightBox = { x: (W - mx - w) / W, y: leftBox.y, w: leftBox.w, h: leftBox.h };
  const hits = (r: typeof leftBox) => avoid.filter((b) => b.x < r.x + r.w && b.x + b.w > r.x && b.y < r.y + r.h && b.y + b.h > r.y);
  const zoneRight = String((overlay as { zone?: string }).zone || "").endsWith("right") || (hitsLeft && !hits(rightBox).length);
  const x = zoneRight ? W - mx - w : mx;
  // lettering across the whole bottom of the picture (a chyron): the card sits above it
  const under = hits(zoneRight ? rightBox : leftBox);
  const y = under.length ? Math.max(0.1 * H, Math.min(...under.map((b) => b.y * H)) - h - 14 * k) : bottomY;
  // the mini map: the region it is in fitted to the square, its neighbours round it
  const set = inUS(A) ? STATES : WORLD;
  const proj = geoMercator();
  if (home) proj.fitExtent([[Sm * 0.1, Sm * 0.1], [Sm * 0.9, Sm * 0.9]], home as never);
  else proj.center([A.lon, A.lat]).scale((Sm * R_MILES) / 300).translate([Sm / 2, Sm / 2]);
  const path = geoPath(proj as never);
  const dotP = proj([A.lon, A.lat]) as [number, number] | null;
  const open = prog(f, 0, 16, S, expoOut);
  const xo = 1 - clamp01(out * 1.4);
  const draw = prog(f, 8, 22, S, cubicInOut) * xo;
  const faceIn = prog(f, 18, 14, S, cubicOut) * xo;
  const drop = prog(f, 24, 12, S, (u) => backOut(u, 1.8)) * xo;
  const ripple = clamp01((f / S - 28) / 24);
  return (
    <AbsoluteFill>
      <Glass x={x} y={y} w={w} h={h} k={k} p={open} out={out} right={zoneRight} radius={14}>
        <div style={{ position: "absolute", left: pad, top: (h - Sm) / 2, width: Sm, height: Sm, borderRadius: 10 * k, overflow: "hidden",
          background: "radial-gradient(circle at 50% 45%, rgba(40,52,68,0.65) 0%, rgba(12,16,22,0.7) 100%)",
          boxShadow: `inset 0 0 0 ${Math.max(1, k).toFixed(1)}px rgba(255,255,255,0.1)` }}>
          <svg width={Sm} height={Sm} style={{ position: "absolute", inset: 0 }}>
            <defs><clipPath id={clip}><rect x={0} y={0} width={Sm} height={Sm} /></clipPath></defs>
            <g clipPath={`url(#${clip})`} opacity={prog(f, 4, 14, S, cubicOut) * xo}>
              {set.map((g, i) => (g === home ? null : <path key={i} d={path(g as never) || ""} fill="rgba(255,255,255,0.04)"
                stroke="rgba(255,255,255,0.16)" strokeWidth={Math.max(0.8, 1 * k)} />))}
            </g>
            {home ? (
              <>
                <path d={path(home as never) || ""} fill={rgba(hot, 0.16)} opacity={faceIn} />
                <path d={path(home as never) || ""} pathLength={1} fill="none" stroke="rgba(255,255,255,0.95)" strokeWidth={Math.max(1.5, 2 * k)}
                  strokeLinejoin="round" strokeDasharray="1 1" strokeDashoffset={1 - draw} />
              </>
            ) : null}
            {dotP ? (
              <>
                {ripple > 0 && ripple < 1 ? <circle cx={dotP[0]} cy={dotP[1]} r={(6 + 20 * cubicOut(ripple)) * k} fill="none" stroke={hot}
                  strokeWidth={2 * k} opacity={(1 - ripple) * xo} /> : null}
                <circle cx={dotP[0]} cy={dotP[1] - (1 - drop) * 14 * k} r={6 * k * Math.max(0, drop)} fill={hot} stroke="#fff"
                  strokeWidth={2 * k * Math.max(0, drop)} />
              </>
            ) : null}
          </svg>
        </div>
        <div style={{ position: "absolute", left: pad + Sm + gap, top: (h - colH) / 2 }}>
          {kicker ? (
            <div style={{ height: kSize, marginBottom: 0.22 * nSize }}>
              <Caps text={kicker} size={kSize} color={hot} at={8} out={out} k={k} />
            </div>
          ) : null}
          <RiseLine text={name} size={nSize} font={GROTESK} weight={800} at={10} out={out} k={k} tracking={0.01} />
          {sub ? (
            <div style={{ height: sSize, marginTop: 0.2 * nSize }}>
              <Caps text={sub} size={sSize} color={kicker ? "rgba(250,250,247,0.82)" : hot} at={16} out={out} k={k} tracking={0.16} />
            </div>
          ) : null}
        </div>
      </Glass>
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "kt-locator": guard(Locator),
  "kt-place": guard(PlaceTag),
};
