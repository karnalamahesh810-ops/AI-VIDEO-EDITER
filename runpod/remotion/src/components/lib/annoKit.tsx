import React from "react";
import type { Box, Overlay, SceneMedia } from "../../types";
import { ANTON, ANTON_CAP, LABEL } from "../fonts";
import { SUBLINE, caps, clamp01, easeOut, fit, rnd, textWidth, type Face } from "./proKit";

/**
 * The annotation kit (2026-10-05): what every look that marks something on a
 * picture shares - the premium photo focus and document spotlight
 * (LibPremium) and the annotation looks (LibAnnotate, "an-").
 *
 *  - WHERE the subject is, from what the worker already knows and never
 *    guessed: the vision anchor of the line's thing (overlay.anchor, the
 *    marks pass), else the subject smart reframing found in the picture
 *    (media.focus.box: faces, the main object, saliency), else a centred safe
 *    region - and then a look that points says so (`found`), so a pointer is
 *    never aimed at a random spot;
 *  - WHERE NOT to write: somebody else's logo, watermark or chyron
 *    (overlay.avoid, media.focus.logos / bands) and the frame's safe margin;
 *    every label is placed by trying its candidate spots in order and taking
 *    the first that is clear (placeRect);
 *  - one camera: a push-in about the subject that leans it toward the middle
 *    and never uncovers the frame's edge (camera);
 *  - drawn strokes: a hand loop that hugs a box (it goes round the thing, not
 *    through it), a stroke that draws on at 30 or 60 fps alike;
 *  - labels in the type system: Barlow Condensed 700 caps on near-black
 *    glass with the accent edge, or the accent as a tag with dark letters -
 *    whole words only: a label that cannot fit whole is not drawn.
 */

export type Rect = { x: number; y: number; w: number; h: number };
export const GLASS = "rgba(9,11,15,0.86)";
export const INK = "#0b0d11";

// ------------------------------------------------------------------ rectangles
export const rect = (x: number, y: number, w: number, h: number): Rect => ({ x, y, w, h });
export const centreOf = (r: Rect): [number, number] => [r.x + r.w / 2, r.y + r.h / 2];
export const inflate = (r: Rect, dx: number, dy = dx): Rect => ({ x: r.x - dx, y: r.y - dy, w: r.w + 2 * dx, h: r.h + 2 * dy });
/** The area two rectangles share (0 when apart). */
export const overlapArea = (a: Rect, b: Rect): number => {
  const w = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
  const h = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
  return w > 0 && h > 0 ? w * h : 0;
};
/** Inside the frame with `m` px to spare on every side. */
export const insideFrame = (r: Rect, W: number, H: number, m: number): boolean =>
  r.x >= m && r.y >= m && r.x + r.w <= W - m && r.y + r.h <= H - m;
/** How far outside the frame's margin a rectangle reaches (px, 0 when inside). */
const spill = (r: Rect, W: number, H: number, m: number): number =>
  Math.max(0, m - r.x) + Math.max(0, m - r.y) + Math.max(0, r.x + r.w - (W - m)) + Math.max(0, r.y + r.h - (H - m));

/**
 * The first candidate inside the frame's safe margin and clear of every
 * blocker (each padded by `pad`); when none is, the one that covers the least
 * of them and reaches the least outside the frame, pulled back inside it.
 */
export const placeRect = (cands: Rect[], blockers: Rect[], W: number, H: number, m: number, pad = 0): Rect => {
  const padded = blockers.map((b) => inflate(b, pad));
  for (const c of cands) {
    if (insideFrame(c, W, H, m) && padded.every((b) => overlapArea(c, b) <= 0)) return c;
  }
  let best = cands[0];
  let score = Infinity;
  for (const c of cands) {
    const s = padded.reduce((a, b) => a + overlapArea(c, b), 0) + spill(c, W, H, m) * Math.max(c.w, c.h) * 4;
    if (s < score) {
      score = s;
      best = c;
    }
  }
  return pullInside(best, W, H, m);
};
export const pullInside = (r: Rect, W: number, H: number, m: number): Rect => ({
  ...r, x: Math.max(m, Math.min(W - m - r.w, r.x)), y: Math.max(m, Math.min(H - m - r.h, r.y)),
});

// ------------------------------------------------------------------ the picture and its subject
/** The picture a still look shows (Main.tsx lookPictures binds the scene's own: its image or its clip's frame). */
export const pictureOf = (overlay: Overlay, i = 0): SceneMedia | null => {
  const all = (Array.isArray(overlay.media) ? overlay.media : []).filter((m) => m && m.url);
  return all[i] || null;
};

/**
 * A box of the source picture in frame shares once the picture covers a
 * frame of aspect `dst` (objectFit: cover, centred), cut to the frame: the
 * same as src/reframe.py cover_box. Null when less than `keep` of it is on screen.
 */
export const coverBox = (b: Box, src: number, dst: number, keep = 0.5): Box | null => {
  if (![b?.x, b?.y, b?.w, b?.h].every((v) => typeof v === "number" && Number.isFinite(v)) || b.w <= 0 || b.h <= 0) return null;
  let { x, y, w, h } = b;
  if (src > 0 && dst > 0 && Math.abs(src - dst) > 1e-3) {
    if (src > dst) {
      const k = dst / src;
      x = (b.x - (1 - k) / 2) / k;
      w = b.w / k;
    } else {
      const k = src / dst;
      y = (b.y - (1 - k) / 2) / k;
      h = b.h / k;
    }
  }
  const x0 = Math.max(0, x), y0 = Math.max(0, y), x1 = Math.min(1, x + w), y1 = Math.min(1, y + h);
  if (x1 <= x0 || y1 <= y0 || (x1 - x0) * (y1 - y0) < keep * w * h) return null;
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
};

export interface Subject {
  /** The subject's box on the frame, px (before any camera move). */
  box: Rect;
  cx: number;
  cy: number;
  /** Where it came from: the vision anchor, the picture's found subject, or nothing known (the centre). */
  found: "anchor" | "focus" | "centre";
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const FOCUS_KINDS = new Set(["face", "object", "action", "saliency"]);

/**
 * The subject of the picture under a look, px: the vision anchor of the
 * thing the line names (overlay.anchor), else the subject reframing found in
 * the picture (media.focus.box; a weak saliency guess is not trusted), else
 * the centred safe region a photograph keeps its subject in. Kept inside the
 * frame's safe area and never smaller than a mark can ring.
 */
export const subjectOf = (overlay: Overlay, W: number, H: number): Subject => {
  const short = Math.min(W, H);
  const make = (x: number, y: number, w: number, h: number, found: Subject["found"]): Subject => {
    const bw = Math.max(0.1 * short, Math.min(0.62 * W, w));
    const bh = Math.max(0.1 * short, Math.min(0.62 * H, h));
    const cx = Math.max(0.1 * W + bw * 0.25, Math.min(0.9 * W - bw * 0.25, x));
    const cy = Math.max(0.12 * H + bh * 0.25, Math.min(0.88 * H - bh * 0.25, y));
    return { box: rect(cx - bw / 2, cy - bh / 2, bw, bh), cx, cy, found };
  };
  const an = overlay.anchor;
  const ax = num(an?.x), ay = num(an?.y);
  if (an && ax !== null && ay !== null) {
    const r = num(an.r);
    const w = num(an.w) ? (an.w as number) * W : r ? r * short * 2 : 0.24 * short;
    const h = num(an.h) ? (an.h as number) * H : r ? r * short * 2 : 0.24 * short;
    return make(ax * W, ay * H, w, h, "anchor");
  }
  const pic = pictureOf(overlay);
  const focus = pic?.focus;
  if (focus && focus.box && FOCUS_KINDS.has(String(focus.kind || "")) && (num(focus.confidence) ?? 1) >= 0.35) {
    const b = coverBox(focus.box, num(focus.aspect) || W / H, W / H);
    if (b && b.w * b.h < 0.7) return make((b.x + b.w / 2) * W, (b.y + b.h / 2) * H, b.w * W, b.h * H, "focus");
  }
  const sub = pic?.reframe?.subject;
  if (sub && num(sub.x) !== null && num(sub.w) && num(sub.h)) {
    return make((sub.x + sub.w / 2) * W, (sub.y + sub.h / 2) * H, sub.w * W, sub.h * H, "focus");
  }
  return make(0.5 * W, 0.46 * H, 0.36 * W, 0.42 * H, "centre");
};

/** The faces of the picture under a look, px boxes (media.focus.faceBoxes), left to right. */
export const facesOf = (overlay: Overlay, W: number, H: number): Rect[] => {
  const focus = pictureOf(overlay)?.focus;
  const list = Array.isArray(focus?.faceBoxes) ? focus!.faceBoxes! : [];
  const out: Rect[] = [];
  for (const f of list) {
    if (!Array.isArray(f) || f.length < 4) continue;
    const b = coverBox({ x: f[0], y: f[1], w: f[2], h: f[3] }, num(focus?.aspect) || W / H, W / H);
    if (b) out.push(rect(b.x * W, b.y * H, b.w * W, b.h * H));
  }
  return out.sort((a, b) => a.x - b.x);
};

/**
 * Where a look must not write, px: overlay.avoid (Main.tsx: the logos and
 * lettering of the scene under it) and the logo corners and lettering bands
 * of its own picture (media.focus.logos / bands).
 */
export const avoidOf = (overlay: Overlay, W: number, H: number): Rect[] => {
  const out: Rect[] = [];
  const add = (b: Box | null) => {
    if (b && b.w > 0 && b.h > 0) out.push(rect(b.x * W, b.y * H, b.w * W, b.h * H));
  };
  for (const b of Array.isArray(overlay.avoid) ? overlay.avoid : []) add(coverBox(b, W / H, W / H, 0));
  const focus = pictureOf(overlay)?.focus;
  const aspect = num(focus?.aspect) || W / H;
  for (const l of Array.isArray(focus?.logos) ? focus!.logos! : []) add(coverBox(l, aspect, W / H, 0));
  for (const band of Array.isArray(focus?.bands) ? focus!.bands! : []) {
    add(coverBox({ x: 0, y: band.y, w: 1, h: band.h }, aspect, W / H, 0));
  }
  return out;
};

// ------------------------------------------------------------------ the camera
export interface Camera {
  s: number;
  /** Where the subject's centre is on screen now. */
  at: [number, number];
  /** A point of the picture (frame px before the move) on screen now. */
  toScreen: (x: number, y: number) => [number, number];
  /** The CSS transform for the picture layer (transform-origin 0 0). */
  css: string;
}

/**
 * The camera on a still: scale `s` about the subject, the subject leaning
 * `lean` of the way toward (tx, ty) as it pushes in, and never so far that the
 * picture's edge comes into the frame.
 */
export const camera = (sub: Subject, s: number, lean: number, W: number, H: number, tx = W / 2, ty = H / 2): Camera => {
  const sc = Math.max(1, s);
  let ax = sub.cx + (tx - sub.cx) * clamp01(lean);
  let ay = sub.cy + (ty - sub.cy) * clamp01(lean);
  // the picture [0, W] maps to [ax - cx*s, ax + (W - cx)*s]: it must still cover [0, W]
  ax = Math.max(W - (W - sub.cx) * sc, Math.min(sub.cx * sc, ax));
  ay = Math.max(H - (H - sub.cy) * sc, Math.min(sub.cy * sc, ay));
  const ox = ax - sub.cx * sc, oy = ay - sub.cy * sc;
  return {
    s: sc,
    at: [ax, ay],
    toScreen: (x, y) => [ox + x * sc, oy + y * sc],
    css: `translate(${ox.toFixed(2)}px, ${oy.toFixed(2)}px) scale(${sc.toFixed(5)})`,
  };
};
/** The subject's box on screen under a camera. */
export const boxOn = (cam: Camera, b: Rect): Rect => {
  const [x0, y0] = cam.toScreen(b.x, b.y);
  return rect(x0, y0, b.w * cam.s, b.h * cam.s);
};

// ------------------------------------------------------------------ strokes
/**
 * A loop drawn by hand round a box: a superellipse (n 2 = an ellipse, higher
 * squarer) that clears the box by (px, py) everywhere, a little over one turn
 * from upper left, the radius growing a few percent so the end crosses past
 * the start the way a marker does. Deterministic for a seed.
 */
export const loopAround = (b: Rect, px: number, py: number, seed: number, n = 2.6, turns = 1.08): string => {
  const cx = b.x + b.w / 2, cy = b.y + b.h / 2;
  // the superellipse through the box's corners, then cleared by the padding
  const e = 2 / n;
  const k = 2 ** (1 / n);              // a superellipse of half-sides a, b reaches its corner diagonal at a / k
  const a = (b.w / 2) * k + px;
  const bb = (b.h / 2) * k + py;
  const a0 = -Math.PI * 0.78 + (rnd(seed) - 0.5) * 0.3;
  const ph = rnd(seed + 7) * Math.PI * 2;
  const steps = 96;
  const pts: string[] = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const th = a0 + t * turns * Math.PI * 2;
    const c = Math.cos(th), s = Math.sin(th);
    const grow = 1 + 0.035 * t + 0.012 * Math.sin(t * Math.PI * 3 + ph);
    const x = cx + Math.sign(c) * Math.abs(c) ** e * a * grow;
    const y = cy + Math.sign(s) * Math.abs(s) ** e * bb * grow * (1 + 0.01 * Math.sin(t * 7 + ph));
    pts.push(`${x.toFixed(1)},${y.toFixed(1)}`);
  }
  return `M${pts[0]} L${pts.slice(1).join(" ")}`;
};

/** A circle path (for strokes that draw on), starting at angle `a0` (radians), clockwise unless `ccw`. */
export const circlePath = (cx: number, cy: number, r: number, a0 = -Math.PI / 2, ccw = false): string => {
  const p = (a: number) => `${(cx + r * Math.cos(a)).toFixed(2)},${(cy + r * Math.sin(a)).toFixed(2)}`;
  const d = ccw ? -1 : 1;
  return `M${p(a0)} A${r.toFixed(2)},${r.toFixed(2)} 0 1 ${ccw ? 0 : 1} ${p(a0 + d * Math.PI)} `
    + `A${r.toFixed(2)},${r.toFixed(2)} 0 1 ${ccw ? 0 : 1} ${p(a0 + d * Math.PI * 1.9999)}`;
};

/** A rounded rectangle path from its top-left corner's end, clockwise. */
export const roundRectPath = (r: Rect, rad: number): string => {
  const q = Math.max(0, Math.min(rad, r.w / 2, r.h / 2));
  const { x, y, w, h } = r;
  return `M${(x + q).toFixed(1)},${y.toFixed(1)} H${(x + w - q).toFixed(1)} Q${(x + w).toFixed(1)},${y.toFixed(1)} ${(x + w).toFixed(1)},${(y + q).toFixed(1)} `
    + `V${(y + h - q).toFixed(1)} Q${(x + w).toFixed(1)},${(y + h).toFixed(1)} ${(x + w - q).toFixed(1)},${(y + h).toFixed(1)} `
    + `H${(x + q).toFixed(1)} Q${x.toFixed(1)},${(y + h).toFixed(1)} ${x.toFixed(1)},${(y + h - q).toFixed(1)} `
    + `V${(y + q).toFixed(1)} Q${x.toFixed(1)},${y.toFixed(1)} ${(x + q).toFixed(1)},${y.toFixed(1)} Z`;
};

/** A drawn stroke: `p` 0..1 of its length shown, a soft shadow under it so it holds on bright and dark pictures. */
export const Stroke: React.FC<{ d: string; p: number; color: string; width: number; shadow?: boolean; opacity?: number;
  cap?: "round" | "butt" | "square" }> = ({ d, p, color, width, shadow = true, opacity = 1, cap = "round" }) => (p <= 0 ? null : (
    <path d={d} pathLength={1} fill="none" stroke={color} strokeWidth={width} strokeLinecap={cap} strokeLinejoin="round"
      strokeDasharray="1 1" strokeDashoffset={1 - clamp01(p)} opacity={opacity}
      style={shadow ? { filter: `drop-shadow(0 ${(width * 0.3).toFixed(1)}px ${(width * 0.9).toFixed(1)}px rgba(0,0,0,.55))` }
        : undefined} />
  ));

// ------------------------------------------------------------------ type metrics
let mctx: CanvasRenderingContext2D | null | undefined;
const measurer = (): CanvasRenderingContext2D | null => {
  if (mctx !== undefined) return mctx;
  try {
    mctx = typeof document !== "undefined" ? document.createElement("canvas").getContext("2d") : null;
  } catch {
    mctx = null;
  }
  return mctx;
};
/**
 * A line of type's vertical metrics at `size` px: the ink of `text` above and
 * below the baseline (asc, desc) and the font's box (fAsc, fDesc), measured
 * with the real font in the browser, estimated without one. In a line box of
 * height L the baseline sits at (L - fAsc - fDesc) / 2 + fAsc from its top.
 */
export const inkOf = (text: string, font: string, weight: number | string, size: number) => {
  const c = measurer();
  if (c) {
    c.font = `${weight} ${size}px ${font}`;
    const m = c.measureText(text || "Hg");
    const fAsc = m.fontBoundingBoxAscent || size * 0.92;
    const fDesc = m.fontBoundingBoxDescent || size * 0.26;
    return { asc: m.actualBoundingBoxAscent || size * 0.72, desc: m.actualBoundingBoxDescent || 0, fAsc, fDesc };
  }
  return { asc: size * 0.72, desc: /[gjpqy,]/.test(text) ? size * 0.22 : size * 0.02, fAsc: size * 0.92, fDesc: size * 0.26 };
};
/** Where the baseline of a line of `size` px sits in a line box `lh` px tall (from the box's top). */
export const baselineIn = (font: string, weight: number | string, size: number, lh: number): number => {
  const m = inkOf("Hg", font, weight, size);
  return (lh - m.fAsc - m.fDesc) / 2 + m.fAsc;
};

// ------------------------------------------------------------------ labels
export const LABEL_FACE: Face = { font: LABEL, weight: 700, tracking: 0.03 };

export interface Fitted2 {
  lines: string[];
  size: number;
  width: number;
}

/**
 * `text` in condensed caps at `size` (down to 80 % of it), one line or two
 * balanced ones no wider than `maxW` - or null: a label is shown whole or not
 * at all, never cut to a fragment.
 */
export const fitWhole = (text: string, maxW: number, size: number, face: Face = LABEL_FACE, maxLines = 2): Fitted2 | null => {
  const t = (text || "").trim().toUpperCase();
  if (!t) return null;
  const f = fit(t, face, maxW, size, size * 0.8, maxLines);
  if (!f.lines.length || f.lines.some((l) => l.endsWith("…"))) return null;
  return f;
};

/** The size of a callout plate for a fitted label (and an optional small line), px. */
export const plateSize = (f: Fitted2, k: number, sub?: string): { w: number; h: number } => {
  const subW = sub ? textWidth(sub.toUpperCase(), SUBLINE, 19 * k, 700, 0.16) : 0;
  return { w: Math.max(f.width, subW) + 46 * k, h: f.lines.length * f.size * 1.04 + (sub ? 27 * k : 0) + 30 * k };
};

/**
 * A callout plate at (x, y) top-left: near-black glass, the accent edge on the
 * side it is read from, condensed caps and an optional small tracked line.
 * Enters with a short slide and a wipe (p 0..1).
 */
export const Plate: React.FC<{ x: number; y: number; f: Fitted2; sub?: string; p: number; hot: string; k: number;
  edge?: "left" | "right" }> = ({ x, y, f, sub, p, hot, k, edge = "left" }) => {
  if (p <= 0) return null;
  const q = easeOut(p);
  const { w } = plateSize(f, k, sub);
  const left = edge === "left";
  return (
    <div style={{ position: "absolute", left: x, top: y, width: w, boxSizing: "border-box",
      padding: `${14 * k}px ${22 * k}px ${16 * k}px`, background: GLASS,
      borderLeft: left ? `${6 * k}px solid ${hot}` : undefined, borderRight: left ? undefined : `${6 * k}px solid ${hot}`,
      borderRadius: 4 * k, boxShadow: `0 ${14 * k}px ${40 * k}px rgba(0,0,0,.5)`, opacity: q,
      transform: `translateX(${((1 - q) * (left ? -16 : 16) * k).toFixed(1)}px)`,
      clipPath: `inset(0 ${left ? ((1 - q) * 100).toFixed(1) : 0}% 0 ${left ? 0 : ((1 - q) * 100).toFixed(1)}%)` }}>
      {f.lines.map((ln, i) => (
        <div key={i} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: f.size, lineHeight: 1.04, letterSpacing: "0.03em",
          color: "#fff", whiteSpace: "nowrap", textAlign: left ? "left" : "right" }}>{ln}</div>
      ))}
      {sub ? <div style={{ ...caps(19 * k, "rgba(255,255,255,.74)", 0.16), marginTop: 8 * k, textAlign: left ? "left" : "right" }}>
        {sub.toUpperCase()}</div> : null}
    </div>
  );
};

/** The accent as a tag: dark condensed caps on the accent, a short wipe in from `from`. */
export const Tag: React.FC<{ x: number; y: number; f: Fitted2; p: number; hot: string; k: number; ink?: string;
  from?: "left" | "right" }> = ({ x, y, f, p, hot, k, ink = INK, from = "left" }) => {
  if (p <= 0) return null;
  const q = easeOut(p);
  return (
    <div style={{ position: "absolute", left: x, top: y, padding: `${10 * k}px ${18 * k}px ${11 * k}px`, background: hot,
      borderRadius: 3 * k, boxShadow: `0 ${10 * k}px ${28 * k}px rgba(0,0,0,.45)`,
      clipPath: from === "left" ? `inset(0 ${((1 - q) * 100).toFixed(1)}% 0 0)` : `inset(0 0 0 ${((1 - q) * 100).toFixed(1)}%)` }}>
      {f.lines.map((ln, i) => (
        <div key={i} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: f.size, lineHeight: 1.02, letterSpacing: "0.035em",
          color: ink, whiteSpace: "nowrap" }}>{ln}</div>
      ))}
    </div>
  );
};
export const tagSize = (f: Fitted2, k: number) => ({ w: f.width + 36 * k, h: f.lines.length * f.size * 1.02 + 21 * k });

// ------------------------------------------------------------------ numbers
/**
 * The one size rule for a figure that carries a moment (the owner,
 * 2026-10-05: "the perfect size - not big, not small"): its digits stand
 * HERO_SHARE of the frame's height (12-16 %); a narrow column may shrink it
 * to HERO_MIN, never below. Its unit is set at UNIT_SHARE of the digits, the
 * line of context under it at CONTEXT_SHARE of the frame. Returns font sizes, px.
 */
export const HERO_SHARE = 0.14;
export const HERO_MIN = 0.12;
export const HERO_MAX = 0.16;
export const UNIT_SHARE = 0.36;
export const CONTEXT_SHARE = 0.031;
export const heroType = (H: number, text: string, maxW: number, share = HERO_SHARE) => {
  const want = (Math.max(HERO_MIN, Math.min(HERO_MAX, share)) * H) / ANTON_CAP;
  const least = (HERO_MIN * H) / ANTON_CAP;
  const em = Math.max(0.5, textWidth(text, ANTON, 100, 400) / 100);
  const size = Math.max(least, Math.min(want, maxW / em));
  return { size, cap: size * ANTON_CAP, unit: size * UNIT_SHARE, context: CONTEXT_SHARE * H };
};
