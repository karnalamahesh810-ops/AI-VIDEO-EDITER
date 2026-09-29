import React, { useMemo } from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { geoMercator, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import worldTopology from "world-atlas/countries-110m.json";
import statesTopology from "../../data/us-states.json";
import { INTER, LABEL } from "../fonts";
import type { MapLocation, Overlay } from "../../types";

/**
 * Weather maps (family "wx-"): the animated forecast-model view news-weather
 * channels screen-record from Windy.com (a quarter of the Nor'easter
 * reference videos), drawn offline from the bundled outlines so it renders
 * the same on the worker and in the editor.
 *
 *   wx-wind-flow   a colour field of wind speed (blue -> green -> yellow ->
 *                  magenta) with thousands of streaks spiralling into the
 *                  storm centre, state lines, city dots, a legend and a
 *                  model-time chip; the camera drifts in slowly
 *   wx-rain-bands  the same engine as a precipitation view: rain bands
 *                  (green -> yellow -> red) wrapping around the low
 *
 * Props: overlay.locations (the region; the first place centres the map),
 * overlay.anchor {x, y} 0..1 = storm centre on screen (default offshore
 * right of centre), overlay.text = title ("WIND GUSTS"), overlay.label =
 * time chip ("SAT 26 SEP · 18:00"). Everything is a pure function of the
 * frame (no Math.random / Date); nothing throws on missing props.
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;
type Pt = [number, number];

const WORLD = feature(worldTopology as never, (worldTopology as any).objects.countries as never) as any;
const STATES = feature(statesTopology as never, (statesTopology as any).objects.states as never) as any;

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const ease = Easing.bezier(0.33, 0, 0.2, 1);
const fract = (v: number) => v - Math.floor(v);
const rnd = (i: number, k: number) => fract(Math.sin(i * 12.9898 + k * 78.233) * 43758.5453);
const str = (s?: unknown) => (typeof s === "string" ? s : s == null ? "" : String(s));

// Windy-like speed palette (0..1) and a radar palette.
const WIND_STOPS: [number, [number, number, number]][] = [
  [0.0, [52, 66, 150]], [0.22, [48, 132, 196]], [0.4, [52, 170, 140]], [0.55, [96, 190, 72]],
  [0.68, [214, 200, 64]], [0.8, [226, 120, 52]], [0.9, [206, 52, 76]], [1.0, [170, 40, 150]],
];
const RAIN_STOPS: [number, [number, number, number]][] = [
  [0.0, [20, 30, 45]], [0.25, [40, 120, 70]], [0.45, [70, 190, 70]], [0.62, [230, 220, 60]],
  [0.78, [240, 140, 40]], [0.9, [220, 40, 40]], [1.0, [190, 60, 200]],
];
const colour = (stops: typeof WIND_STOPS, t: number, a = 1) => {
  const v = Math.max(0, Math.min(1, t));
  for (let i = 1; i < stops.length; i++) {
    if (v <= stops[i][0]) {
      const [t0, c0] = stops[i - 1];
      const [t1, c1] = stops[i];
      const u = (v - t0) / Math.max(1e-6, t1 - t0);
      const c = c0.map((x, j) => Math.round(x + (c1[j] - x) * u));
      return `rgba(${c[0]},${c[1]},${c[2]},${a})`;
    }
  }
  const c = stops[stops.length - 1][1];
  return `rgba(${c[0]},${c[1]},${c[2]},${a})`;
};

/** Wind at a point: a cyclone (counter-clockwise, spiralling in) plus a westerly drift. */
const field = (p: Pt, c: Pt, R: number): { v: Pt; speed: number } => {
  const dx = p[0] - c[0], dy = p[1] - c[1];
  const r = Math.hypot(dx, dy) + 1e-3;
  const q = r / R;
  const s = q * Math.exp(1 - q);                       // peaks at the radius of max wind
  const tx = dy / r, ty = -dx / r;                     // counter-clockwise on screen (y down)
  const vx = (tx - 0.28 * dx / r) * s + 0.22;           // inflow + westerly steering
  const vy = (ty - 0.28 * dy / r) * s - 0.04;
  return { v: [vx, vy], speed: Math.min(1, Math.hypot(vx, vy)) };
};

const useMap = (overlay: Overlay, width: number, height: number) =>
  useMemo(() => {
    const locs = (overlay.locations || []) as MapLocation[];
    const first = locs.find((l) => Number.isFinite(l?.lat) && Number.isFinite(l?.lon));
    const lat = first ? first.lat : 39.5, lon = first ? first.lon : -74.5;
    const proj = geoMercator().center([lon, lat]).scale(width * 2.2).translate([width * 0.46, height * 0.5]);
    const path = geoPath(proj);
    const land = path(WORLD) || "";
    const states = path(STATES) || "";
    const cities = locs
      .filter((l) => Number.isFinite(l?.lat) && Number.isFinite(l?.lon))
      .slice(0, 6)
      .map((l) => ({ name: str(l.label || (l as any).name).split(",")[0].toUpperCase(), p: proj([l.lon, l.lat]) as Pt }))
      .filter((c) => c.p && c.p[0] > 40 && c.p[0] < width - 40 && c.p[1] > 40 && c.p[1] < height - 40);
    return { land, states, cities };
  }, [overlay.locations, width, height]);

const WeatherMap: React.FC<{ overlay: Overlay; mode: "wind" | "rain" }> = ({ overlay, mode }) => {
  const frame = useCurrentFrame();
  const { width, height, durationInFrames, fps } = useVideoConfig();
  const k = width / 1920;
  const map = useMap(overlay, width, height);
  const anchor = (overlay as any).anchor || {};
  const centre: Pt = [
    width * (Number.isFinite(anchor.x) ? anchor.x : 0.63),
    height * (Number.isFinite(anchor.y) ? anchor.y : 0.47),
  ];
  const R = 190 * k;
  const stops = mode === "wind" ? WIND_STOPS : RAIN_STOPS;

  // The colour field: a coarse grid, blurred into a smooth wash. Static per
  // video except for a slow rotation of the rain bands.
  const cells = useMemo(() => {
    const out: { x: number; y: number; w: number; h: number; c: string }[] = [];
    const nx = 40, ny = 23, cw = width / nx, ch = height / ny;
    for (let i = 0; i < nx; i++) {
      for (let j = 0; j < ny; j++) {
        const p: Pt = [(i + 0.5) * cw, (j + 0.5) * ch];
        let t: number;
        if (mode === "wind") {
          t = field(p, centre, R).speed * 0.88 + 0.07 * rnd(i, j);
        } else {
          const dx = p[0] - centre[0], dy = p[1] - centre[1];
          const r = Math.hypot(dx, dy), a = Math.atan2(dy, dx);
          const arm = 0.5 + 0.5 * Math.sin(a * 2 + r / (70 * k));        // two spiral arms
          t = Math.max(0, arm * Math.exp(-r / (520 * k)) * 1.25 - 0.12 + 0.12 * rnd(i, j));
        }
        out.push({ x: i * cw, y: j * ch, w: cw + 1, h: ch + 1, c: colour(stops, t, mode === "wind" ? 0.9 : 0.8) });
      }
    }
    return out;
  }, [width, height, mode, centre[0], centre[1], R]);

  // Streaks: each particle is born at a hashed point, lives LIFE frames and
  // is integrated through the field from birth, so frame N is reproducible.
  const N = mode === "wind" ? 1400 : 420, LIFE = 60, STEP = 2.6 * k, TRAIL = 11;
  const streaks = useMemo(() => {
    const out: { d: string; o: number; w: number }[] = [];
    for (let i = 0; i < N; i++) {
      const age = (frame + Math.floor(rnd(i, 3) * LIFE)) % LIFE;
      const born = frame - age;
      let p: Pt = [rnd(i, born * 0.013 + 1) * width * 1.1 - width * 0.05,
                   rnd(i, born * 0.017 + 2) * height * 1.1 - height * 0.05];
      const pts: Pt[] = [p];
      for (let s = 0; s < age; s++) {
        const { v } = field(p, centre, R);
        p = [p[0] + v[0] * STEP * 2.2, p[1] + v[1] * STEP * 2.2];
        pts.push(p);
      }
      const tail = pts.slice(-TRAIL);
      if (tail.length < 2) continue;
      const fade = Math.min(1, age / 8, (LIFE - age) / 10);
      out.push({ d: "M" + tail.map((q) => `${q[0].toFixed(1)},${q[1].toFixed(1)}`).join("L"),
                 o: 0.7 * fade, w: (mode === "wind" ? 1.5 : 1.1) * k });
    }
    return out;
  }, [frame, width, height, N, mode, centre[0], centre[1], R, k]);

  const intro = interpolate(frame, [0, 14], [0, 1], { ...clamp, easing: ease });
  const outro = interpolate(frame, [durationInFrames - 12, durationInFrames], [1, 0], clamp);
  const zoom = interpolate(frame, [0, durationInFrames], [1.0, 1.07], clamp);
  const title = str(overlay.text).toUpperCase() || (mode === "wind" ? "WIND GUSTS" : "RAIN & SNOW");
  const chip = str(overlay.label).toUpperCase();
  const spin = (frame / fps) * (mode === "rain" ? 6 : 0);

  return (
    <AbsoluteFill style={{ background: "#0b1420", opacity: intro * outro }}>
      <AbsoluteFill style={{ transform: `scale(${zoom})`, transformOrigin: `${centre[0]}px ${centre[1]}px` }}>
        <AbsoluteFill style={{ filter: `blur(${26 * k}px) saturate(1.1)`, transform: `rotate(${spin}deg) scale(1.08)`,
                               transformOrigin: `${centre[0]}px ${centre[1]}px` }}>
          <svg width={width} height={height}>
            {cells.map((c, i) => <rect key={i} x={c.x} y={c.y} width={c.w} height={c.h} fill={c.c} />)}
          </svg>
        </AbsoluteFill>
        <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0 }}>
          <path d={map.land} fill="rgba(10,16,24,0.18)" stroke="rgba(255,255,255,0.55)" strokeWidth={1.3 * k} />
          <path d={map.states} fill="none" stroke="rgba(255,255,255,0.32)" strokeWidth={0.9 * k} />
          <g stroke="rgba(255,255,255,0.9)" fill="none" strokeLinecap="round">
            {streaks.map((s, i) => <path key={i} d={s.d} strokeOpacity={s.o} strokeWidth={s.w} />)}
          </g>
          {mode === "wind" && (
            <g>
              <circle cx={centre[0]} cy={centre[1]} r={16 * k} fill="none" stroke="#fff" strokeWidth={3 * k}
                      opacity={0.85} />
              <text x={centre[0]} y={centre[1] + 8 * k} textAnchor="middle" fill="#fff"
                    style={{ font: `800 ${22 * k}px ${LABEL}` }}>L</text>
            </g>
          )}
          {map.cities.map((c, i) => {
            const a = interpolate(frame, [10 + i * 5, 22 + i * 5], [0, 1], clamp);
            return (
              <g key={c.name + i} opacity={a}>
                <circle cx={c.p[0]} cy={c.p[1]} r={6 * k} fill="#fff" stroke="rgba(0,0,0,0.5)" strokeWidth={2 * k} />
                <text x={c.p[0] + 12 * k} y={c.p[1] + 7 * k} fill="#fff"
                      style={{ font: `700 ${24 * k}px ${INTER}`, paintOrder: "stroke" }}
                      stroke="rgba(0,0,0,0.65)" strokeWidth={4 * k}>{c.name}</text>
              </g>
            );
          })}
        </svg>
      </AbsoluteFill>

      {/* Title, legend and model-time chip: small, clean, out of the way. */}
      <div style={{ position: "absolute", left: 96 * k, top: 88 * k,
                    transform: `translateY(${(1 - intro) * -16 * k}px)` }}>
        <div style={{ font: `800 ${46 * k}px ${LABEL}`, color: "#fff", letterSpacing: 1.5 * k,
                      textShadow: "0 2px 12px rgba(0,0,0,0.55)" }}>{title}</div>
        <div style={{ font: `600 ${22 * k}px ${INTER}`, color: "rgba(255,255,255,0.8)", marginTop: 4 * k }}>
          {mode === "wind" ? "Forecast model · surface wind" : "Forecast model · precipitation"}
        </div>
      </div>
      <div style={{ position: "absolute", right: 96 * k, bottom: 84 * k, width: 380 * k }}>
        <div style={{ height: 12 * k, borderRadius: 6 * k,
                      background: `linear-gradient(90deg, ${stops.map(([t]) => colour(stops, t)).join(",")})` }} />
        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6 * k,
                      font: `600 ${18 * k}px ${INTER}`, color: "rgba(255,255,255,0.85)" }}>
          {(mode === "wind" ? ["0", "20", "40", "60", "80 mph"] : ["light", "", "moderate", "", "heavy"])
            .map((t, i) => <span key={i}>{t}</span>)}
        </div>
      </div>
      {chip && (
        <div style={{ position: "absolute", left: 96 * k, bottom: 84 * k, padding: `${10 * k}px ${18 * k}px`,
                      borderRadius: 8 * k, background: "rgba(8,12,18,0.72)", color: "#fff",
                      font: `700 ${24 * k}px ${INTER}`, letterSpacing: 0.5 * k }}>{chip}</div>
      )}
    </AbsoluteFill>
  );
};

const WindFlow: Look = ({ overlay }) => <WeatherMap overlay={overlay} mode="wind" />;
const RainBands: Look = ({ overlay }) => <WeatherMap overlay={overlay} mode="rain" />;

export const LOOKS: Record<string, Look> = {
  "wx-wind-flow": WindFlow,
  "wx-rain-bands": RainBands,
};
