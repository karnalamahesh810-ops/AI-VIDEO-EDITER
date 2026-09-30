import React from "react";
import { AbsoluteFill, Easing, useCurrentFrame, useVideoConfig } from "remotion";
import { INTER, LABEL } from "../fonts";
import type { Overlay } from "../../types";
import { ramp, useK } from "../pro/ProGraphics";

/**
 * Marks drawn ON the playing footage (family "vm-"): the editor's red pen
 * over a clip, pointing at the one thing the line is about. They are
 * transparent (the clip keeps playing underneath) and draw only the mark and
 * its label.
 *
 *   vm-arrow   a hand-drawn red marker arrow sweeps from a bold label to the thing
 *   vm-circle  a red marker loop draws round the thing and pulses once; a label if given
 *   vm-box     a red box draws round the thing, the rest of the frame dims a touch,
 *              a red tag names it
 *
 * They need overlay.anchor: {x, y} in 0..1 of the frame (where the thing is,
 * from src/anchors.find_anchor on the clip's frame at the moment the mark
 * lands), optionally r (0..0.5: the thing's radius as a share of the frame's
 * shorter side) and w, h (the thing's box as shares of the frame's width and
 * height). Without a usable anchor a mark draws NOTHING: a red arrow pointing
 * at nothing is worse than no arrow.
 *
 * The drawing kit below (tapered felt-marker strokes, the hand-drawn arrow
 * and loop, the label box and where it goes) is shared with the photo looks
 * in LibPhotoEditor, so a red arrow looks the same on a photo and on video.
 * Everything is a pure function of the frame; nothing throws on missing props.
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;
export type Pt = { x: number; y: number };
export type Anchor = { x: number; y: number; r?: number; w?: number; h?: number };

export const MARK_RED = "#E3242B";
const INK = "#14161B";
/** A pen stroke: a quick start, an eased landing. */
export const PEN = Easing.bezier(0.45, 0, 0.2, 1);
const IN = Easing.bezier(0.7, 0, 0.84, 0);
const BACK = Easing.bezier(0.34, 1.45, 0.64, 1);
const INOUT = Easing.bezier(0.65, 0, 0.35, 1);
const EXPO = Easing.bezier(0.16, 1, 0.3, 1);
/** The soft shadow under every red mark (it must read on snow and on night footage). */
export const markShadow = (k: number) => `drop-shadow(0 ${(2.5 * k).toFixed(2)}px ${(3.5 * k).toFixed(2)}px rgba(0,0,0,.55))`;

// ------------------------------------------------------------------ props
const num = (v: unknown): number | null => {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
};

/** overlay.anchor as a point in 0..1 (with r / w / h when given and sane), or null when there is none. */
export const anchorFrom = (ov: Overlay | null | undefined): Anchor | null => {
  const raw = ov && typeof ov === "object" ? (ov as { anchor?: unknown }).anchor : undefined;
  if (!raw || typeof raw !== "object") return null;
  const a = raw as Record<string, unknown>;
  const x = num(a.x), y = num(a.y);
  if (x === null || y === null || x < -0.02 || x > 1.02 || y < -0.02 || y > 1.02) return null;
  const out: Anchor = { x: Math.min(1, Math.max(0, x)), y: Math.min(1, Math.max(0, y)) };
  const r = num(a.r), w = num(a.w), h = num(a.h);
  if (r !== null && r > 0) out.r = Math.min(0.5, r);
  if (w !== null && w > 0) out.w = Math.min(1, w);
  if (h !== null && h > 0) out.h = Math.min(1, h);
  return out;
};

const clean = (s: unknown): string =>
  (typeof s === "string" ? s : typeof s === "number" && Number.isFinite(s) ? String(s) : "").replace(/\s+/g, " ").trim();
export const capsOf = (s: unknown): string => clean(s).toUpperCase();

/** Width of bold condensed caps (Barlow Condensed 800) at `px`, with `track` em of letter spacing. */
export const capsW = (t: string, px: number, track = 0.04): number => {
  let w = 0;
  for (const c of t) {
    w += (c === " " ? 0.2 : /[IJ1.,:;'!|]/.test(c) ? 0.25 : /[MW]/.test(c) ? 0.7 : /[A-Z]/.test(c) ? 0.53
      : /[0-9]/.test(c) ? 0.5 : 0.48) + track;
  }
  return w * px;
};

const wrapCaps = (text: string, room: number, px: number, track: number): string[] => {
  const out: string[] = [];
  let cur = "";
  for (const w of text.split(" ").filter(Boolean)) {
    const next = cur ? `${cur} ${w}` : w;
    if (cur && capsW(next, px, track) > room) {
      out.push(cur);
      cur = w;
    } else {
      cur = next;
    }
  }
  if (cur) out.push(cur);
  return out;
};

/**
 * Condensed caps wrapped into at most `maxLines` lines no wider than `room`
 * px, at the first of `sizes` (px) that fits, the lines balanced (no orphan
 * word). The last size breaks an over-long word and ends with an ellipsis.
 */
export const fitCaps = (text: string, room: number, sizes: number[], maxLines: number, track = 0.04): { ls: string[]; size: number } => {
  const t = clean(text);
  const last = sizes[sizes.length - 1];
  if (!t) return { ls: [], size: last };
  for (const s of sizes) {
    const ls = wrapCaps(t, room, s, track);
    if (ls.length <= maxLines && ls.every((l) => capsW(l, s, track) <= room + 0.5)) {
      if (ls.length < 2) return { ls, size: s };
      // Balance: the narrowest room that still gives the same number of lines.
      let best = ls;
      for (let r = room * 0.96; r > room * 0.4; r *= 0.96) {
        const b = wrapCaps(t, r, s, track);
        if (b.length !== ls.length || !b.every((l) => capsW(l, s, track) <= r + 0.5)) break;
        best = b;
      }
      return { ls: best, size: s };
    }
  }
  const per = Math.max(4, Math.floor(room / (0.55 * last)));
  const words = t.split(" ").flatMap((w) => (w.length > per ? (w.match(new RegExp(`.{1,${per - 1}}`, "g")) || [w]) : [w]));
  let ls = wrapCaps(words.join(" "), room, last, track);
  if (ls.length > maxLines) {
    ls = ls.slice(0, maxLines);
    let l = ls[maxLines - 1];
    while (l.length > 1 && capsW(`${l}…`, last, track) > room) l = l.slice(0, -1).trimEnd();
    ls[maxLines - 1] = `${l}…`;
  }
  return { ls, size: last };
};

// ------------------------------------------------------------------ strokes
export type Poly = { pts: Pt[]; acc: number[]; total: number };
export const poly = (pts: Pt[]): Poly => {
  const acc = [0];
  for (let i = 1; i < pts.length; i++) acc.push(acc[i - 1] + Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y));
  return { pts, acc, total: acc[acc.length - 1] || 0 };
};

/** The point and the unit direction at arc fraction s of a polyline. */
const pointAt = (pl: Poly, s: number): { p: Pt; t: Pt } => {
  const n = pl.pts.length;
  if (n < 2) return { p: pl.pts[0] || { x: 0, y: 0 }, t: { x: 1, y: 0 } };
  const d = Math.max(0, Math.min(1, s)) * pl.total;
  let i = 1;
  while (i < n - 1 && pl.acc[i] < d) i++;
  const a = pl.pts[i - 1], b = pl.pts[i];
  const seg = Math.max(1e-6, pl.acc[i] - pl.acc[i - 1]);
  const f = Math.max(0, Math.min(1, (d - pl.acc[i - 1]) / seg));
  const dx = b.x - a.x, dy = b.y - a.y;
  const l = Math.hypot(dx, dy) || 1;
  return { p: { x: a.x + dx * f, y: a.y + dy * f }, t: { x: dx / l, y: dy / l } };
};

const smooth = (a: number, b: number, x: number) => {
  const t = Math.max(0, Math.min(1, (x - a) / Math.max(1e-6, b - a)));
  return t * t * (3 - 2 * t);
};
export type Profile = (s: number) => number;
/** A felt-marker body: a thin tail swelling to full width, a slightly worn nib. */
export const BODY: Profile = (s) => (0.38 + 0.62 * smooth(0, 0.32, s)) * (1 - 0.16 * smooth(0.84, 1, s));
/** A flick (an arrowhead wing): full at the tip, thinning out. */
export const FLICK: Profile = (s) => 1 - 0.5 * smooth(0.15, 1, s);
/** A loop: even, with soft ends where the pen lands and lifts. */
export const LOOP: Profile = (s) => (0.5 + 0.5 * smooth(0, 0.1, s)) * (1 - 0.45 * smooth(0.9, 1, s));

/**
 * The filled outline of a marker stroke along `pl`, between arc fractions
 * a and b, `width` px at its widest, shaped by `profile` (of the whole
 * stroke, so drawing it on reveals the same shape) with round ends.
 */
export const markerPath = (pl: Poly, a: number, b: number, width: number, profile: Profile = BODY, seed = 0): string => {
  const lo = Math.max(0, Math.min(1, a)), hi = Math.max(0, Math.min(1, b));
  if (hi - lo < 0.002 || pl.total < 1) return "";
  const n = Math.max(6, Math.ceil((hi - lo) * (pl.pts.length - 1) * 2));
  const L: Pt[] = [], R: Pt[] = [];
  let r0 = 0, r1 = 0;
  for (let i = 0; i <= n; i++) {
    const s = lo + ((hi - lo) * i) / n;
    const { p, t } = pointAt(pl, s);
    const w = Math.max(0.5, (width * profile(s) * (1 + 0.05 * Math.sin(s * 17 + seed))) / 2);
    if (i === 0) r0 = w;
    if (i === n) r1 = w;
    L.push({ x: p.x - t.y * w, y: p.y + t.x * w });
    R.push({ x: p.x + t.y * w, y: p.y - t.x * w });
  }
  const f = (p: Pt) => `${p.x.toFixed(1)} ${p.y.toFixed(1)}`;
  let d = `M${f(L[0])}`;
  for (let i = 1; i <= n; i++) d += `L${f(L[i])}`;
  d += `A${r1.toFixed(1)} ${r1.toFixed(1)} 0 0 0 ${f(R[n])}`;
  for (let i = n - 1; i >= 0; i--) d += `L${f(R[i])}`;
  d += `A${r0.toFixed(1)} ${r0.toFixed(1)} 0 0 0 ${f(L[0])}Z`;
  return d;
};

export const bezier = (S: Pt, C1: Pt, C2: Pt, E: Pt, n = 48): Pt[] => {
  const out: Pt[] = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n, m = 1 - t;
    out.push({
      x: m * m * m * S.x + 3 * m * m * t * C1.x + 3 * m * t * t * C2.x + t * t * t * E.x,
      y: m * m * m * S.y + 3 * m * m * t * C1.y + 3 * m * t * t * C2.y + t * t * t * E.y,
    });
  }
  return out;
};

/**
 * The body of a hand-drawn arrow from S to E: a bowed curve, bulging upward
 * (toward the frame's centre when the arrow is near vertical) the way a hand
 * throws an arrow at a picture, with a slight wobble of the hand.
 */
export const arrowPts = (S: Pt, E: Pt, W: number, bow = 0.2, seed = 0): Pt[] => {
  const dx = E.x - S.x, dy = E.y - S.y;
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len, uy = dy / len;
  let nx = -uy, ny = ux;
  const vertical = Math.abs(ux) < 0.25;
  if (vertical ? nx * (W / 2 - (S.x + E.x) / 2) < 0 : ny > 0) {
    nx = -nx;
    ny = -ny;
  }
  const b = bow * len;
  const C1 = { x: S.x + dx * 0.3 + nx * b, y: S.y + dy * 0.3 + ny * b };
  const C2 = { x: S.x + dx * 0.72 + nx * b * 0.62, y: S.y + dy * 0.72 + ny * b * 0.62 };
  return bezier(S, C1, C2, E).map((p, i, all) => {
    const t = i / (all.length - 1);
    const wob = Math.sin(t * Math.PI) * Math.sin(t * 9 + seed) * len * 0.006;
    return { x: p.x + nx * wob, y: p.y + ny * wob };
  });
};

/** A hand-drawn loop round an ellipse: slightly uneven, a little more than one turn, the second pass running wide. */
export const loopPts = (cx: number, cy: number, rx: number, ry: number, seed: number, turns = 1.12, tilt = -0.1, N = 84): Pt[] => {
  const start = -2.2 + (seed % 7) * 0.06;
  const pts: Pt[] = [];
  for (let i = 0; i <= N; i++) {
    const t = i / N;
    const a = start + Math.PI * 2 * turns * t;
    const w = 1 + 0.03 * Math.sin(a * 3 + seed) + 0.018 * Math.sin(a * 5 + seed * 1.7);
    const g = 0.975 + 0.075 * t;
    const x = rx * w * g * Math.cos(a), y = ry * w * g * Math.sin(a);
    pts.push({ x: cx + x * Math.cos(tilt) - y * Math.sin(tilt), y: cy + x * Math.sin(tilt) + y * Math.cos(tilt) });
  }
  return pts;
};

/**
 * A red felt-marker arrow: the body drawn on to `draw` (0..1), the two head
 * flicks to `head`, erased from the tail by `erase` at the exit.
 */
export const HandArrow: React.FC<{ pts: Pt[]; draw: number; head: number; erase?: number; width: number; k: number;
  color?: string; seed?: number }> = ({ pts, draw, head, erase = 0, width, k, color = MARK_RED, seed = 0 }) => {
  if (pts.length < 2) return null;
  const pl = poly(pts);
  const body = markerPath(pl, erase, draw, width, BODY, seed);
  const n = pts.length - 1;
  const E = pts[n], B = pts[Math.max(0, n - 4)];
  const dl = Math.hypot(E.x - B.x, E.y - B.y) || 1;
  const ux = (E.x - B.x) / dl, uy = (E.y - B.y) / dl;
  const hl = Math.min(width * 3.5, pl.total * 0.32);
  const headOp = (1 - smooth(0.72, 0.95, erase)) * (draw > 0.96 ? 1 : 0);
  const wings = [-1, 1].map((sg) => {
    const ang = (sg * 150 * Math.PI) / 180;
    const dx = ux * Math.cos(ang) - uy * Math.sin(ang), dy = ux * Math.sin(ang) + uy * Math.cos(ang);
    const bend = hl * 0.07 * sg;
    const w: Pt[] = [];
    for (let i = 0; i <= 8; i++) {
      const t = i / 8;
      w.push({ x: E.x + dx * hl * t - dy * bend * Math.sin(t * Math.PI), y: E.y + dy * hl * t + dx * bend * Math.sin(t * Math.PI) });
    }
    return poly(w);
  });
  return (
    <g style={{ filter: markShadow(k) }}>
      {body ? <path d={body} fill={color} /> : null}
      {head > 0.01 && headOp > 0.01
        ? wings.map((w, i) => <path key={i} d={markerPath(w, 0, head, width * 0.95, FLICK, seed + i * 3)} fill={color} opacity={headOp} />)
        : null}
    </g>
  );
};

/** A red marker loop drawn from `from` to `to` (0..1 of its length). */
export const MarkerLoop: React.FC<{ pts: Pt[]; from?: number; to: number; width: number; k: number; color?: string; seed?: number;
  opacity?: number }> = ({ pts, from = 0, to, width, k, color = MARK_RED, seed = 0, opacity = 1 }) => {
  const d = markerPath(poly(pts), from, to, width, LOOP, seed);
  return d ? <path d={d} fill={color} opacity={opacity} style={{ filter: markShadow(k) }} /> : null;
};

// ------------------------------------------------------------------ labels
/** The label box's inner spacing for text `size` px (kept here so its measure and its drawing agree). */
const pads = (size: number, k: number) => ({ t: size * 0.2, b: size * 0.16, l: size * 0.34 + 7 * k, r: size * 0.4 });

/** The size of a label box: condensed caps lines plus an optional smaller second line. */
export const labelSize = (ls: string[], size: number, k: number, sub = "", subSize = 0): { w: number; h: number } => {
  if (!ls.length && !sub) return { w: 0, h: 0 };
  const p = pads(size, k);
  const tw = Math.max(0, ...ls.map((l) => capsW(l, size))) * 1.03;
  const sw = sub ? sub.length * subSize * 0.52 : 0;
  return { w: Math.max(tw, sw) + p.l + p.r, h: ls.length * size * 1.04 + (sub ? subSize * 1.35 : 0) + p.t + p.b };
};

export type LabelSpot = { x0: number; y0: number; w: number; h: number; css: React.CSSProperties; origin: string; S: Pt; dir: Pt };

/**
 * Where a label of w x h px goes for a mark on T (the thing's radius R):
 * clear of the thing, inside the safe area (110 px at 1080p), on the side
 * with room, preferring a diagonal toward the frame's centre (the arrow then
 * reads into the picture). S is where an arrow leaves the label for T.
 * The box is pinned by its edges nearest T (css), so an estimate of its
 * width never moves the end the arrow touches.
 */
export const placeLabel = (T: Pt, R: number, w: number, h: number, W: number, H: number, k: number, reach = 150): LabelSpot => {
  const M = 110 * k;
  const dirs: [number, number][] = [[-0.8, 0.6], [0.8, 0.6], [-0.8, -0.6], [0.8, -0.6], [-1, 0], [1, 0], [0, 1], [0, -1]];
  const cx0 = W / 2 - T.x, cy0 = H / 2 - T.y;
  const cl = Math.hypot(cx0, cy0) || 1;
  let best: { x0: number; y0: number; score: number; dir: Pt } | null = null;
  dirs.forEach(([dx, dy], i) => {
    const ext = Math.abs(dx) * (w / 2) + Math.abs(dy) * (h / 2);
    const d = R + reach * k + ext;
    let x0 = T.x + dx * d - w / 2, y0 = T.y + dy * d - h / 2;
    x0 = Math.max(M, Math.min(W - M - w, x0));
    y0 = Math.max(M, Math.min(H - M - h, y0));
    // Clearance: how far the (clamped) box stays from the thing's edge.
    const nx = Math.max(x0, Math.min(x0 + w, T.x)), ny = Math.max(y0, Math.min(y0 + h, T.y));
    const clear = Math.hypot(T.x - nx, T.y - ny) - R;
    const toC = (cx0 * dx + cy0 * dy) / cl;
    const score = Math.max(0, 140 * k - clear) * 3 + (clear < 36 * k ? 2000 * k : 0) + (i >= 4 ? 45 * k : 0) - toC * 36 * k;
    if (!best || score < best.score) best = { x0, y0, score, dir: { x: dx, y: dy } };
  });
  const b = best as unknown as { x0: number; y0: number; dir: Pt };
  const x0 = b.x0, y0 = b.y0;
  const cx = x0 + w / 2, cy = y0 + h / 2;
  const leftOf = cx < T.x, above = cy < T.y;
  const css: React.CSSProperties = {
    ...(leftOf ? { right: W - (x0 + w) } : { left: x0 }),
    ...(above ? { bottom: H - (y0 + h) } : { top: y0 }),
  };
  // The arrow leaves from the box's point nearest the thing, a little off the box.
  let sx = Math.max(x0, Math.min(x0 + w, T.x)), sy = Math.max(y0, Math.min(y0 + h, T.y));
  if (sx === T.x && sy === T.y) {
    sx = cx;
    sy = cy;
  }
  // Leave from a third of the way along the edge rather than the very corner.
  if (sy === y0 || sy === y0 + h) sx = Math.max(x0 + w * 0.2, Math.min(x0 + w * 0.8, sx));
  if (sx === x0 || sx === x0 + w) sy = Math.max(y0 + h * 0.25, Math.min(y0 + h * 0.75, sy));
  const vx = T.x - sx, vy = T.y - sy;
  const vl = Math.hypot(vx, vy) || 1;
  const S = { x: sx + (vx / vl) * 16 * k, y: sy + (vy / vl) * 16 * k };
  return { x0, y0, w, h, css, origin: `${leftOf ? "100%" : "0%"} ${above ? "100%" : "0%"}`, S, dir: b.dir };
};

/** The point `gap` px short of T on the way from S (where an arrow's tip stops). */
export const shortOf = (T: Pt, S: Pt, gap: number): Pt => {
  const vx = T.x - S.x, vy = T.y - S.y;
  const l = Math.hypot(vx, vy) || 1;
  const g = Math.min(gap, l * 0.55);
  return { x: T.x - (vx / l) * g, y: T.y - (vy / l) * g };
};

/**
 * The bold label: black condensed caps on a white card with a red edge
 * (tone "red": white caps on red), popping out of the corner that faces the
 * mark; an optional smaller line under it.
 */
export const LabelBox: React.FC<{ spot: LabelSpot; ls: string[]; size: number; k: number; p: number; out: number;
  sub?: string; subSize?: number; tone?: "white" | "red" }> = ({ spot, ls, size, k, p, out, sub = "", subSize = 0, tone = "white" }) => {
  if (!ls.length && !sub) return null;
  const pd = pads(size, k);
  const red = tone === "red";
  return (
    <div style={{ position: "absolute", ...spot.css, display: "flex", flexDirection: "column", alignItems: "flex-start",
      padding: `${pd.t}px ${pd.r}px ${pd.b}px ${pd.l - (red ? 0 : 7 * k)}px`, background: red ? MARK_RED : "#fff",
      borderRadius: 5 * k, borderLeft: red ? undefined : `${7 * k}px solid ${MARK_RED}`,
      boxShadow: `0 ${12 * k}px ${34 * k}px rgba(0,0,0,.42), 0 ${2 * k}px ${5 * k}px rgba(0,0,0,.25)`,
      opacity: Math.min(1, p * 2.5) * (1 - out), transformOrigin: spot.origin,
      transform: `translateY(${((1 - p) * 12 + out * 14) * k}px) scale(${(0.88 + 0.12 * p).toFixed(4)})` }}>
      {ls.map((l, i) => (
        <div key={i} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: size, lineHeight: 1.04, letterSpacing: "0.04em",
          color: red ? "#fff" : INK, whiteSpace: "nowrap" }}>{l}</div>
      ))}
      {sub ? (
        <div style={{ fontFamily: INTER, fontWeight: 700, fontSize: subSize, lineHeight: 1.35, color: red ? "rgba(255,255,255,.88)" : "#50545c",
          whiteSpace: "nowrap", marginTop: ls.length ? 2 * k : 0 }}>{sub}</div>
      ) : null}
    </div>
  );
};

// ------------------------------------------------------------------ looks
const seedOf = (s: string): number => {
  let h = 17;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 9973;
  return h;
};
const shortSub = (s: unknown, n = 44): string => {
  const t = clean(s);
  return t.length > n ? `${t.slice(0, n - 1).trimEnd()}…` : t;
};

/** 0 -> 1 over the last ~12 frames: the mark's exit. */
const useExit = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return ramp(frame, durationInFrames - 13, 11, IN);
};

// ================================================================== vm-arrow
/**
 * The bold label pops up clear of the thing (frame 2); a red felt-marker
 * arrow sweeps out of it on a bowed curve (frames 6 -> 18, the swipe peaking
 * mid-sweep at 14, sfx_at) and its head flicks open on the thing at 18; at
 * the exit the arrow is erased from its tail and the label drops away.
 */
const VmArrow: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const out = useExit();
  const a = anchorFrom(overlay);
  if (!a) return null;
  const T = { x: a.x * W, y: a.y * H };
  const R = Math.max(18 * k, Math.min(230 * k, (a.r ?? 0.045) * Math.min(W, H)));
  const text = capsOf(overlay.text);
  const sub = shortSub(overlay.subtitle);
  const { ls, size } = fitCaps(text, 560 * k, [56 * k, 50 * k, 44 * k], 2);
  const subSize = 28 * k;
  const box = labelSize(ls, size, k, sub, subSize);
  const spot = placeLabel(T, R, box.w || 1, box.h || 1, W, H, k, box.w ? 215 : 280);
  // No label: the arrow still comes from a point clear of the thing, inside the safe area.
  const S = box.w ? spot.S : { x: spot.x0, y: spot.y0 };
  const E = shortOf(T, S, R + 12 * k);
  const seed = seedOf(text || "arrow");
  const pts = arrowPts(S, E, W, 0.2, seed);
  const draw = ramp(frame, 6, 12, PEN);
  const head = ramp(frame, 18, 5, EXPO);
  const erase = ramp(frame, dur - 14, 10, IN);
  const pop = ramp(frame, 2, 12, BACK);
  return (
    <AbsoluteFill>
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        <HandArrow pts={pts} draw={draw} head={head} erase={erase} width={17 * k} k={k} seed={seed} />
      </svg>
      {box.w ? <LabelBox spot={spot} ls={ls} size={size} k={k} p={pop} out={out} sub={sub} subSize={subSize} /> : null}
    </AbsoluteFill>
  );
};

// ================================================================== vm-circle
/**
 * A red marker loop draws round the thing (a little more than one turn, its
 * ends overlapping like a real pen; frame 3 on, sfx_at 7), then pulses once:
 * a small bump and one soft ring going out. A label, when given, sits beside
 * it on a short red tick. At the exit the loop is erased in stroke order.
 */
const VmCircle: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const out = useExit();
  const a = anchorFrom(overlay);
  if (!a) return null;
  const T = { x: a.x * W, y: a.y * H };
  const R = Math.max(50 * k, Math.min(330 * k, (a.r ?? 0.1) * Math.min(W, H)));
  let rx = R * 1.08 + 14 * k, ry = R * 0.9 + 12 * k;
  if (a.w && a.h) {
    rx = Math.max(56 * k, ((a.w * W) / 2) * 1.2 + 16 * k);
    ry = Math.max(48 * k, ((a.h * H) / 2) * 1.2 + 16 * k);
    // Never a sliver: a loop round a pole is still a loop.
    if (rx / ry > 1.9) ry = rx / 1.9;
    if (ry / rx > 1.6) rx = ry / 1.6;
  }
  // A loop cut by the frame's edge looks like a mistake: keep it whole, a little off-centre if it must be.
  rx = Math.min(rx, W / 2 - 34 * k);
  ry = Math.min(ry, H / 2 - 34 * k);
  T.x = Math.max(rx * 1.1 + 24 * k, Math.min(W - rx * 1.1 - 24 * k, T.x));
  T.y = Math.max(ry * 1.1 + 24 * k, Math.min(H - ry * 1.1 - 24 * k, T.y));
  const text = capsOf(overlay.text);
  const seed = seedOf(text || `${a.x}${a.y}`);
  const pts = loopPts(T.x, T.y, rx, ry, seed, 1.12, -0.1);
  const draw = ramp(frame, 3, 14, PEN);
  const erase = ramp(frame, dur - 13, 11, IN);
  const pp = ramp(frame, 17, 12, Easing.linear);
  const bump = 1 + 0.05 * Math.sin(Math.PI * pp);
  const ring = ramp(frame, 17, 20, EXPO);
  // Label (optional): beside the loop on the roomier side, on a short tick.
  const { ls, size } = fitCaps(text, 480 * k, [50 * k, 44 * k, 40 * k], 2);
  const box = labelSize(ls, size, k);
  const M = 110 * k;
  const roomR = W - M - (T.x + rx + 70 * k);
  const roomL = T.x - rx - 70 * k - M;
  const onRight = roomR >= box.w || roomR >= roomL;
  const tickX0 = T.x + (onRight ? rx * 1.06 : -rx * 1.06);
  const tickX1 = tickX0 + (onRight ? 46 : -46) * k;
  const boxTop = Math.max(M, Math.min(H - M - box.h, T.y - box.h / 2));
  const spot: LabelSpot = {
    x0: onRight ? tickX1 + 8 * k : tickX1 - 8 * k - box.w, y0: boxTop, w: box.w, h: box.h,
    css: onRight ? { left: tickX1 + 8 * k, top: boxTop } : { right: W - (tickX1 - 8 * k), top: boxTop },
    origin: onRight ? "0% 50%" : "100% 50%", S: { x: tickX1, y: T.y }, dir: { x: onRight ? 1 : -1, y: 0 },
  };
  const tick = ramp(frame, 12, 8, INOUT) * (1 - out);
  const pop = ramp(frame, 14, 12, BACK);
  return (
    <AbsoluteFill>
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        {ring > 0 && ring < 1 ? (
          <ellipse cx={T.x} cy={T.y} rx={rx * (1.05 + 0.32 * ring)} ry={ry * (1.05 + 0.32 * ring)} fill="none" stroke={MARK_RED}
            strokeWidth={(4.5 * (1 - ring) + 1) * k} strokeOpacity={0.7 * (1 - ring) * (1 - out)} transform={`rotate(-5.7 ${T.x} ${T.y})`} />
        ) : null}
        <g transform={`translate(${T.x} ${T.y}) scale(${bump.toFixed(4)}) translate(${-T.x} ${-T.y})`}>
          <MarkerLoop pts={pts} from={erase} to={draw} width={10 * k} k={k} seed={seed} />
        </g>
        {ls.length && tick > 0.01 ? (
          <line x1={tickX0} y1={T.y} x2={tickX0 + (tickX1 - tickX0) * tick} y2={T.y} stroke={MARK_RED} strokeWidth={5 * k}
            strokeLinecap="round" style={{ filter: markShadow(k) }} />
        ) : null}
      </svg>
      {ls.length ? <LabelBox spot={spot} ls={ls} size={size} k={k} p={pop} out={out} /> : null}
    </AbsoluteFill>
  );
};

// ================================================================== vm-box
/**
 * A red box draws round the thing from its top-left corner, clockwise
 * (frame 3 -> 15, sfx_at 5), while the rest of the frame dims a touch; a red
 * tag with the name slides out of the box's top edge (below it near the top
 * of the frame). At the exit the stroke retracts and the dim lifts.
 */
const VmBox: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const out = useExit();
  const a = anchorFrom(overlay);
  if (!a) return null;
  const T = { x: a.x * W, y: a.y * H };
  const R = Math.max(50 * k, Math.min(330 * k, (a.r ?? 0.12) * Math.min(W, H)));
  const E = 44 * k;
  const bw = Math.max(110 * k, Math.min(W - 2 * E, (a.w ? a.w * W : R * 1.9) * 1.14 + 26 * k));
  const bh = Math.max(96 * k, Math.min(H - 2 * E, (a.h ? a.h * H : R * 1.6) * 1.14 + 26 * k));
  const x0 = Math.max(E, Math.min(W - E - bw, T.x - bw / 2));
  const y0 = Math.max(E, Math.min(H - E - bh, T.y - bh / 2));
  const x1 = x0 + bw, y1 = y0 + bh;
  const rr = 7 * k;
  const d = `M${x0 + rr} ${y0} H${x1 - rr} A${rr} ${rr} 0 0 1 ${x1} ${y0 + rr} V${y1 - rr} A${rr} ${rr} 0 0 1 ${x1 - rr} ${y1} ` +
    `H${x0 + rr} A${rr} ${rr} 0 0 1 ${x0} ${y1 - rr} V${y0 + rr} A${rr} ${rr} 0 0 1 ${x0 + rr} ${y0} Z`;
  const draw = ramp(frame, 3, 12, INOUT);
  const retract = ramp(frame, dur - 13, 10, IN);
  const len = Math.max(0.0001, draw - retract);
  const dim = 0.3 * ramp(frame, 4, 12) * (1 - out);
  const text = capsOf(overlay.text);
  const tagSize = 36 * k;
  const room = Math.min(620 * k, W - 110 * k - x0);
  const { ls, size } = fitCaps(text, Math.max(200 * k, room - 40 * k), [tagSize, 32 * k, 28 * k], 1);
  const tagAbove = y0 > 150 * k;
  const tagIn = ramp(frame, 12, 12, EXPO) * (1 - ramp(frame, dur - 14, 9, IN));
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: x0, top: y0, width: bw, height: bh, borderRadius: rr,
        boxShadow: `0 0 0 ${(4000 * k).toFixed(0)}px rgba(0,0,0,${dim.toFixed(3)})` }} />
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        <path d={d} fill="none" stroke={MARK_RED} strokeWidth={6.5 * k} strokeLinejoin="round" strokeLinecap="round" pathLength={1}
          strokeDasharray={`${len.toFixed(4)} 2`} strokeDashoffset={(-retract).toFixed(4)} strokeOpacity={draw - retract > 0.003 ? 1 : 0}
          style={{ filter: markShadow(k) }} />
      </svg>
      {ls.length ? (
        <div style={{ position: "absolute", left: x0 - 3.25 * k, top: tagAbove ? undefined : y1 + 3.25 * k,
          bottom: tagAbove ? H - (y0 - 3.25 * k) : undefined, overflow: "hidden", paddingBottom: tagAbove ? 0 : 12 * k }}>
          <div style={{ background: MARK_RED, color: "#fff", fontFamily: LABEL, fontWeight: 800, fontSize: size, letterSpacing: "0.06em",
            lineHeight: 1.1, padding: `${7 * k}px ${18 * k}px ${5 * k}px`, whiteSpace: "nowrap", boxShadow: `0 ${6 * k}px ${16 * k}px rgba(0,0,0,.3)`,
            transform: `translateY(${((1 - tagIn) * (tagAbove ? 106 : -106)).toFixed(2)}%)` }}>{ls[0]}</div>
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "vm-arrow": VmArrow,
  "vm-circle": VmCircle,
  "vm-box": VmBox,
};
