import React from "react";
import { AbsoluteFill, Easing, Img, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { HAND, INTER, LABEL, SERIF, SERIF_ITALIC, TYPEWRITER } from "../fonts";
import type { Overlay, SceneMedia } from "../../types";
import { lines, ramp, useK } from "../pro/ProGraphics";
import { HandArrow, LabelBox, MARK_RED, MarkerLoop, PEN, arrowPts, fitCaps, labelSize, loopPts, markShadow, placeLabel,
  shortOf } from "./LibVideoMarks";

/**
 * Photo editor moves (family "pe-"): what a documentary editor does with one
 * still of the story (overlay.media[0]; a clip lends its thumbnail) instead of
 * showing it in a photo viewer. Each look draws its own full frame.
 *
 *   pe-zoom-circle   a slow push toward a point, then a red marker loop is drawn
 *                    round it and a label with a hand-drawn arrow points at it
 *   pe-highlight-box the picture dims outside a red box that draws on, then the
 *                    camera pushes into the box
 *   pe-focus-pull    the still racks from soft to sharp under a light sweep and
 *                    a vignette; the caption fades up
 *   pe-split-panels  three vertical strips of the photo slide in staggered from
 *                    above and below, then close into one picture
 *   pe-frame-drop    a framed print drops onto a dark desk, settles its turn,
 *                    and the camera leans in; a museum label slides beside it
 *   pe-parallax      2.5D: a blurred, scaled copy drifts one way behind a sharp
 *                    crop drifting the other
 *   pe-newsprint     the photo printed in halftone on a newspaper page under a
 *                    headline strip (overlay.text)
 *   pe-punch-in      a fast zoom-blur punch that settles, then a slow drift
 *   pe-duotone       a duotone grade (dark + accent) with a big caption
 *   pe-light-sweep   a slow push with a diagonal light sweep and film grain,
 *                    a small location label
 *   pe-polaroid-pan  a shutter flash, an instant print the camera pans across,
 *                    the caption handwritten on it
 *   pe-case-file     the photo clipped into a manila case folder, a typed label
 *                    strip, a red marker circle drawn round the point; the
 *                    camera pushes into the circle
 *   pe-circle-spotlight  the photo dims except a circle of light that opens on
 *                    the point, a red ring draws round it, a label on a leader
 *   pe-magnify       a magnifying glass glides in and settles over the point,
 *                    enlarging it; a label beside the lens
 *   pe-red-arrow     a bold label, and a hand-drawn red marker arrow sweeping
 *                    from it to the point while the camera pushes in
 *
 * Props: text (caption / label / headline), subtitle, label (kicker), and
 * overlay.anchor {x, y} in 0..1 of the frame for the point the circle, box,
 * lens and arrow mark (a sensible off-centre point when absent), optionally
 * r (0..0.5: the thing's radius as a share of the frame's shorter side, from
 * src/anchors.find_anchor) to size the circle and the arrow's stand-off.
 * Red is used only for the marks. Everything leaves in the last ~12 frames.
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;
type Pt = [number, number];

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const expoOut = Easing.bezier(0.16, 1, 0.3, 1);
const expoIn = Easing.bezier(0.7, 0, 0.84, 0);
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const drift = Easing.bezier(0.33, 0, 0.45, 1);
const backOut = Easing.bezier(0.34, 1.4, 0.64, 1);
const MARKER_RED = "#e3242b";
const INK = "#1b1a18";
const SHADOW = "0 4px 24px rgba(0,0,0,.55)";

// ------------------------------------------------------------------ helpers
const str = (s: unknown): string => (typeof s === "string" ? s.replace(/\s+/g, " ").trim() : "");
const cap = (s: unknown): string => str(s).toUpperCase();
const clamp01 = (v: number) => Math.max(0, Math.min(1, Number.isFinite(v) ? v : 0));

const stillOf = (m: SceneMedia | null | undefined): string => {
  if (!m || typeof m !== "object") return "";
  const s = m.type === "image" ? m.url : m.thumbnail;
  return typeof s === "string" ? s.trim() : "";
};
/** The overlay's picture as a still URL (a video lends its thumbnail). */
const photoOf = (ov: Overlay): string => {
  const media: SceneMedia[] = Array.isArray(ov.media) ? ov.media : [];
  for (const m of media) {
    const s = stillOf(m);
    if (s) return s;
  }
  return "";
};

const hashStr = (s: string): number => {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619) >>> 0;
  return h;
};

type RGB = [number, number, number];
const toRgb = (c: string): RGB => {
  const s = (c || "").trim().replace(/^#/, "");
  let hex = "";
  if (/^[0-9a-f]{6}$/i.test(s)) hex = s;
  else if (/^[0-9a-f]{3}$/i.test(s)) hex = s.split("").map((x) => x + x).join("");
  const m = /^rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)/i.exec((c || "").trim());
  if (!hex && m) return [Number(m[1]), Number(m[2]), Number(m[3])];
  const n = hex ? parseInt(hex, 16) : 0xd6a83c;
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
const mix = (a: string, b: string, t: number) => {
  const x = toRgb(a), y = toRgb(b);
  const f = (i: number) => Math.round(x[i] + (y[i] - x[i]) * clamp01(t));
  return `rgb(${f(0)},${f(1)},${f(2)})`;
};
const rgba = (c: string, a: number) => {
  const [r, g, b] = toRgb(c);
  return `rgba(${r},${g},${b},${a})`;
};

/** The point of interest: overlay.anchor when valid (clamped), else the default. */
const anchorOf = (ov: Overlay, fx: number, fy: number, lo: number, hi: number): Pt => {
  const a = ov.anchor;
  const cl = (v: number) => Math.min(hi, Math.max(lo, v));
  if (a && typeof a === "object" && Number.isFinite(a.x) && Number.isFinite(a.y)) return [cl(a.x), cl(a.y)];
  return [fx, fy];
};

/** Re-wrap `ls` into the same number of lines, as even in length as the room allows (no orphan last word). */
const balance = (t: string, ls: string[], per: number): string[] => {
  if (ls.length < 2) return ls;
  for (let p = Math.ceil(t.length / ls.length); p < per; p++) {
    const b = lines(t, p);
    if (b.length <= ls.length && b.every((l) => l.length <= per)) return b;
  }
  return ls;
};

/** The largest size at which `text` wraps into at most `maxLines` lines `room` px wide (1080p px). */
const fitLines = (text: string, room: number, sizes: number[], em: number, maxLines: number): { size: number; ls: string[] } => {
  const t = str(text);
  const last = sizes[sizes.length - 1];
  if (!t) return { size: last, ls: [] };
  for (const s of sizes) {
    const per = Math.max(4, Math.floor(room / (em * s)));
    const ls = lines(t, per);
    if (ls.length <= maxLines && ls.every((l) => l.length <= per)) return { size: s, ls: balance(t, ls, per) };
  }
  const per = Math.max(4, Math.floor(room / (em * last)));
  const words = t.split(" ").flatMap((w) => (w.length > per ? (w.match(new RegExp(`.{1,${per - 1}}`, "g")) || [w]) : [w]));
  let ls = lines(words.join(" "), per);
  if (ls.length > maxLines) {
    ls = ls.slice(0, maxLines);
    const l = ls[maxLines - 1];
    ls[maxLines - 1] = `${l.length > per - 1 ? l.slice(0, per - 1).trimEnd() : l}…`;
  }
  return { size: last, ls };
};

/** 0 while the look holds, easing to 1 over its last `frames` frames. */
const useOut = (frames = 12) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return ramp(frame, Math.max(0, durationInFrames - frames - 1), frames, expoIn);
};

/** 0 -> 1 across the whole look on a gentle curve (camera moves). */
const useDrift = (ease = drift) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return interpolate(frame, [0, Math.max(1, durationInFrames)], [0, 1], { ...clamp, easing: ease });
};

/** A line sliding up out of its mask at `at` and back down as `q` goes to 1. */
const Rise: React.FC<{ at: number; q: number; children: React.ReactNode; style?: React.CSSProperties; frames?: number }> =
  ({ at, q, children, style, frames = 16 }) => {
    const frame = useCurrentFrame();
    const p = ramp(frame, at, frames);
    return (
      <div style={{ overflow: "hidden", paddingBottom: "0.14em", marginBottom: "-0.14em", ...style }}>
        <div style={{ transform: `translateY(${((1 - p) * 112 + q * 112).toFixed(2)}%)`, opacity: p > 0.002 ? 1 : 0 }}>{children}</div>
      </div>
    );
  };

const Photo: React.FC<{ src: string; style?: React.CSSProperties }> = ({ src, style }) => (
  <Img src={src} style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "100%", objectFit: "cover", ...style }} />
);

/** Film grain: animated fractal noise at half resolution, overlaid. */
const Grain: React.FC<{ opacity?: number }> = ({ opacity = 0.12 }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const id = `peGrain${React.useId().replace(/[^A-Za-z0-9]/g, "")}`;
  return (
    <svg width={width / 2} height={height / 2} style={{ position: "absolute", left: 0, top: 0, transform: "scale(2)", transformOrigin: "0 0",
      opacity, mixBlendMode: "overlay", pointerEvents: "none" }}>
      <filter id={id} x="0" y="0" width="100%" height="100%">
        <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves={2} seed={frame % 12} stitchTiles="stitch" />
        <feColorMatrix type="saturate" values="0" />
      </filter>
      <rect width={width / 2} height={height / 2} filter={`url(#${id})`} />
    </svg>
  );
};

/** A duotone SVG filter: luminance mapped from `dark` (shadows) to `light` (highlights). */
const DuoFilter: React.FC<{ id: string; dark: string; light: string }> = ({ id, dark, light }) => {
  const d = toRgb(dark).map((v) => (v / 255).toFixed(3));
  const l = toRgb(light).map((v) => (v / 255).toFixed(3));
  return (
    <svg width={0} height={0} style={{ position: "absolute" }}>
      <filter id={id} colorInterpolationFilters="sRGB">
        <feColorMatrix type="matrix" values=".2126 .7152 .0722 0 0  .2126 .7152 .0722 0 0  .2126 .7152 .0722 0 0  0 0 0 1 0" />
        <feComponentTransfer>
          <feFuncR type="table" tableValues={`${d[0]} ${l[0]}`} />
          <feFuncG type="table" tableValues={`${d[1]} ${l[1]}`} />
          <feFuncB type="table" tableValues={`${d[2]} ${l[2]}`} />
        </feComponentTransfer>
      </filter>
    </svg>
  );
};

/**
 * The lower-left caption most looks share: a kicker (overlay.label) with an
 * accent tick, the title (overlay.text) in condensed caps, the subtitle in Inter.
 */
const LowerCaption: React.FC<{ ov: Overlay; at: number; q: number; accent: string; left?: number; bottom?: number; room?: number;
  sizes?: number[]; kicker?: boolean }> = ({ ov, at, q, accent, left = 110, bottom = 120, room = 1150, sizes = [66, 60, 54, 48], kicker = true }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const title = fitLines(cap(ov.text), room, sizes, 0.47, 2);
  const kick = kicker ? cap(ov.label) : "";
  const sub = fitLines(str(ov.subtitle), room, [34, 32, 30], 0.5, 2);
  if (!title.ls.length && !kick && !sub.ls.length) return null;
  return (
    <div style={{ position: "absolute", left: left * k, bottom: bottom * k, display: "flex", flexDirection: "column", gap: 4 * k,
      maxWidth: (room + 40) * k }}>
      {kick ? (
        <div style={{ display: "flex", alignItems: "center", gap: 14 * k, marginBottom: 6 * k }}>
          <div style={{ width: 26 * k * ramp(frame, at - 2, 12, inOut) * (1 - q), height: 4 * k, background: accent }} />
          <Rise at={at} q={q}>
            <div style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 30 * k, letterSpacing: "0.26em", color: "rgba(255,255,255,.9)",
              whiteSpace: "nowrap", textShadow: SHADOW }}>{kick.slice(0, 44)}</div>
          </Rise>
        </div>
      ) : null}
      {title.ls.map((ln, i) => (
        <Rise key={i} at={at + 3 + i * 4} q={q}>
          <div style={{ fontFamily: LABEL, fontWeight: 800, fontSize: title.size * k, letterSpacing: "0.04em", color: "#fff", lineHeight: 1.02,
            whiteSpace: "nowrap", textShadow: SHADOW }}>{ln}</div>
        </Rise>
      ))}
      {sub.ls.map((ln, i) => (
        <Rise key={`s${i}`} at={at + 9 + title.ls.length * 4 + i * 3} q={q} style={{ marginTop: i === 0 ? 8 * k : 0 }}>
          <div style={{ fontFamily: INTER, fontWeight: 400, fontSize: sub.size * k, color: "rgba(255,255,255,.86)", whiteSpace: "nowrap",
            lineHeight: 1.2, textShadow: SHADOW }}>{ln}</div>
        </Rise>
      ))}
    </div>
  );
};

/** A dark gradient rising from the bottom-left so a caption reads on any picture. */
const CaptionShade: React.FC<{ show: boolean; strength?: number }> = ({ show, strength = 0.7 }) =>
  show ? (
    <AbsoluteFill style={{ background: `linear-gradient(20deg, rgba(0,0,0,${strength}) 0%, rgba(0,0,0,${strength * 0.45}) 32%, rgba(0,0,0,0) 58%)` }} />
  ) : null;
const hasCaption = (ov: Overlay) => Boolean(str(ov.text) || str(ov.label) || str(ov.subtitle));

// ================================================================== pe-zoom-circle
/** A hand-drawn loop round an ellipse: slightly uneven, overshooting its start. */
const markerLoop = (cx: number, cy: number, rx: number, ry: number, seed: number): string => {
  const N = 64;
  const start = -2.25 + (seed % 7) * 0.05;
  const sweep = Math.PI * 2 * 1.12;
  const rot = -0.12;
  const pts: string[] = [];
  for (let i = 0; i <= N; i++) {
    const t = i / N;
    const a = start + sweep * t;
    const w = 1 + 0.035 * Math.sin(a * 3 + seed) + 0.025 * Math.sin(a * 5 + seed * 1.7);
    const g = 0.97 + 0.08 * t;
    const x = rx * w * g * Math.cos(a), y = ry * w * g * Math.sin(a);
    const X = cx + x * Math.cos(rot) - y * Math.sin(rot), Y = cy + x * Math.sin(rot) + y * Math.cos(rot);
    pts.push(`${i ? "L" : "M"} ${X.toFixed(1)} ${Y.toFixed(1)}`);
  }
  return pts.join(" ");
};

// The push runs the whole look; the loop draws frames 20 -> 38 (sfx_at 22), the arrow and label follow.
const ZoomCircle: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H } = useVideoConfig();
  const k = useK();
  const q = useOut();
  const d = useDrift();
  const src = photoOf(overlay);
  if (!src) return null;
  const [ax, ay] = anchorOf(overlay, 0.62, 0.42, 0.2, 0.8);
  const cx = ax * W, cy = ay * H;
  const rx = 178 * k, ry = 132 * k;
  const seed = hashStr(src) % 97;
  const draw = ramp(frame, 20, 18, inOut);
  const label = fitLines(cap(overlay.text), 460, [40, 36, 32], 0.5, 2);
  const hasLabel = label.ls.length > 0;
  // The label sits away from the circle, on the side with more room.
  const side = ax > 0.5 ? -1 : 1;
  const below = ay < 0.5;
  const lw = Math.min(520, Math.max(...label.ls.map((l) => l.length), 1) * label.size * 0.52 + 56) * k;
  const lh = (label.ls.length * label.size * 1.12 + 34) * k;
  let lx = cx + side * (rx + 150 * k) - (side < 0 ? lw : 0);
  let ly = cy + (below ? ry + 70 * k : -(ry + 70 * k) - lh);
  lx = Math.max(96 * k, Math.min(W - 96 * k - lw, lx));
  ly = Math.max(96 * k, Math.min(H - 96 * k - lh, ly));
  // The arrow runs from the label's nearest edge to just outside the loop.
  const sx = side < 0 ? lx + lw + 14 * k : lx - 14 * k;
  const sy = ly + lh / 2;
  const th = Math.atan2(sy - cy, sx - cx);
  const ex = cx + (rx + 22 * k) * Math.cos(th), ey = cy + (ry + 22 * k) * Math.sin(th);
  const mx = (sx + ex) / 2 + (below ? -1 : 1) * 40 * k * side, my = (sy + ey) / 2 + (below ? 1 : -1) * 30 * k;
  const arrow = ramp(frame, 34, 12, inOut);
  const tang = Math.atan2(ey - my, ex - mx);
  const hl = 26 * k;
  const pop = ramp(frame, 30, 14, backOut);
  const photoIn = ramp(frame, 0, 14);
  return (
    <AbsoluteFill style={{ background: "#000", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${1.02 + 0.16 * d})`, transformOrigin: `${(ax * 100).toFixed(2)}% ${(ay * 100).toFixed(2)}%`,
        opacity: photoIn }}>
        <Photo src={src} style={{ filter: "saturate(.95) contrast(1.05)" }} />
      </AbsoluteFill>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 50%, rgba(0,0,0,0) 50%, rgba(0,0,0,.5) 100%)" }} />
      <svg width={W} height={H} style={{ position: "absolute", inset: 0, overflow: "visible", opacity: 1 - q }}>
        <path d={markerLoop(cx, cy, rx, ry, seed)} fill="none" stroke={MARKER_RED} strokeWidth={9 * k} strokeLinecap="round"
          strokeLinejoin="round" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - draw}
          style={{ filter: `drop-shadow(0 ${3 * k}px ${5 * k}px rgba(0,0,0,.45))` }} />
        {hasLabel && arrow > 0 ? (
          <g style={{ filter: `drop-shadow(0 ${3 * k}px ${5 * k}px rgba(0,0,0,.45))` }}>
            <path d={`M ${sx.toFixed(1)} ${sy.toFixed(1)} Q ${mx.toFixed(1)} ${my.toFixed(1)} ${ex.toFixed(1)} ${ey.toFixed(1)}`} fill="none"
              stroke={MARKER_RED} strokeWidth={6 * k} strokeLinecap="round" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - arrow} />
            {arrow > 0.92 ? (
              <path d={`M ${(ex - hl * Math.cos(tang - 0.5)).toFixed(1)} ${(ey - hl * Math.sin(tang - 0.5)).toFixed(1)} L ${ex.toFixed(1)} ${ey.toFixed(1)} L ${(ex - hl * Math.cos(tang + 0.5)).toFixed(1)} ${(ey - hl * Math.sin(tang + 0.5)).toFixed(1)}`}
                fill="none" stroke={MARKER_RED} strokeWidth={6 * k} strokeLinecap="round" strokeLinejoin="round" />
            ) : null}
          </g>
        ) : null}
      </svg>
      {hasLabel ? (
        <div style={{ position: "absolute", left: lx, top: ly, width: lw, padding: `${16 * k}px ${26 * k}px`, background: "#fff",
          borderRadius: 6 * k, boxShadow: "0 14px 40px rgba(0,0,0,.45)", borderLeft: `${7 * k}px solid ${MARKER_RED}`,
          opacity: clamp01(pop * 3) * (1 - q), transform: `translateY(${((1 - pop) * 18 * k).toFixed(2)}px) scale(${0.92 + 0.08 * pop})`,
          transformOrigin: side < 0 ? "100% 50%" : "0 50%" }}>
          {label.ls.map((ln, i) => (
            <div key={i} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: label.size * k, letterSpacing: "0.06em", color: INK,
              lineHeight: 1.12, whiteSpace: "nowrap" }}>{ln}</div>
          ))}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== pe-highlight-box
// The box draws frames 16 -> 32 (sfx_at 18); the dim follows; the push into the box runs 30 -> end.
const HighlightBox: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const q = useOut();
  const src = photoOf(overlay);
  if (!src) return null;
  const [ax, ay] = anchorOf(overlay, 0.58, 0.47, 0.22, 0.78);
  const bw = W * 0.36, bh = H * 0.42;
  const bx = Math.max(110 * k, Math.min(W - 110 * k - bw, ax * W - bw / 2));
  const by = Math.max(150 * k, Math.min(H - 110 * k - bh, ay * H - bh / 2));
  const draw = ramp(frame, 16, 16, inOut);
  const dim = ramp(frame, 18, 16, inOut) * (1 - q);
  const push = interpolate(frame, [30, Math.max(31, dur)], [0, 1], { ...clamp, easing: inOut });
  const settle = ramp(frame, 0, 18);
  const tag = fitLines(cap(overlay.text), bw / k - 40, [36, 32, 30], 0.5, 1);
  const tagIn = ramp(frame, 28, 14);
  const tagAbove = by > 190 * k;
  const ox = ((bx + bw / 2) / W) * 100, oy = ((by + bh / 2) / H) * 100;
  return (
    <AbsoluteFill style={{ background: "#000", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${(1.06 - 0.06 * settle) * (1 + 0.14 * push)})`, transformOrigin: `${ox.toFixed(2)}% ${oy.toFixed(2)}%`,
        opacity: ramp(frame, 0, 10) }}>
        <Photo src={src} style={{ filter: `saturate(${1 - 0.35 * dim}) contrast(1.04)` }} />
        <div style={{ position: "absolute", left: bx, top: by, width: bw, height: bh,
          boxShadow: `0 0 0 ${3000 * k}px rgba(0,0,0,${(0.58 * dim).toFixed(3)})` }} />
        <svg width={W} height={H} style={{ position: "absolute", inset: 0, opacity: 1 - q }}>
          <path d={`M ${bx} ${by} H ${bx + bw} V ${by + bh} H ${bx} Z`} fill="none" stroke={MARKER_RED} strokeWidth={7 * k}
            strokeLinejoin="round" strokeLinecap="round" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - draw}
            style={{ filter: `drop-shadow(0 0 ${8 * k}px rgba(227,36,43,.45))` }} />
        </svg>
        {tag.ls.length ? (
          <div style={{ position: "absolute", left: bx - 3.5 * k, top: tagAbove ? by - 3.5 * k : by + bh + 3.5 * k,
            transform: tagAbove ? "translateY(-100%)" : undefined, overflow: "hidden", opacity: 1 - q }}>
            <div style={{ background: MARKER_RED, color: "#fff", fontFamily: LABEL, fontWeight: 800, fontSize: tag.size * k,
              letterSpacing: "0.08em", padding: `${8 * k}px ${20 * k}px ${6 * k}px`, whiteSpace: "nowrap",
              transform: `translateY(${((1 - tagIn) * (tagAbove ? 105 : -105)).toFixed(2)}%)` }}>{tag.ls[0]}</div>
          </div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== pe-focus-pull
// Focus lands at frame ~24 under the light sweep (sfx_at 20); the caption fades up from 28.
const FocusPull: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const q = useOut();
  const d = useDrift();
  const src = photoOf(overlay);
  if (!src) return null;
  const focus = ramp(frame, 0, 26, inOut);
  const blur = (1 - focus) * 18 * k;
  const sweep = interpolate(frame, [8, 42], [-45, 145], { ...clamp, easing: inOut });
  const sweepA = ramp(frame, 8, 8) * (1 - ramp(frame, 34, 10));
  const vig = 0.75 - 0.25 * focus;
  const cap_ = hasCaption(overlay);
  return (
    <AbsoluteFill style={{ background: "#000", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${1.1 + 0.06 * d})` }}>
        <Photo src={src} style={{ filter: `blur(${blur.toFixed(2)}px) brightness(${0.7 + 0.3 * focus}) saturate(${0.8 + 0.2 * focus})` }} />
      </AbsoluteFill>
      <AbsoluteFill style={{ opacity: sweepA, mixBlendMode: "screen",
        background: "linear-gradient(105deg, rgba(255,240,214,0) 0%, rgba(255,240,214,0) 38%, rgba(255,240,214,.34) 50%, rgba(255,240,214,0) 62%, rgba(255,240,214,0) 100%)",
        transform: `translateX(${sweep.toFixed(2)}%)` }} />
      <AbsoluteFill style={{ background: `radial-gradient(ellipse at 50% 48%, rgba(0,0,0,0) 42%, rgba(0,0,0,${vig.toFixed(3)}) 100%)` }} />
      <CaptionShade show={cap_} strength={0.62} />
      <div style={{ opacity: ramp(frame, 26, 16) }}>
        <LowerCaption ov={overlay} at={28} q={q} accent={accent} />
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== pe-split-panels
// The strips slide in staggered 0 -> 24 (sfx_at 8), close into one picture 30 -> 44.
const SplitPanels: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H } = useVideoConfig();
  const k = useK();
  const q = useOut();
  const d = useDrift();
  const src = photoOf(overlay);
  if (!src) return null;
  const merge = ramp(frame, 30, 14, inOut);
  const gap = 26 * k * (1 - merge);
  const PW = W / 3;
  const cap_ = hasCaption(overlay);
  return (
    <AbsoluteFill style={{ background: "#0b0d12", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${(0.92 + 0.08 * merge) * (1 + 0.06 * d)})` }}>
        {[0, 1, 2].map((i) => {
          const e = ramp(frame, i * 5, 20, expoOut);
          const from = i === 1 ? 1 : -1;
          return (
            <div key={i} style={{ position: "absolute", top: 0, height: H, left: i * PW + (i - 1) * gap, width: PW + (i < 2 ? 1 : 0),
              overflow: "hidden", transform: `translateY(${((1 - e) * from * 104).toFixed(2)}%)`,
              boxShadow: merge < 1 ? `0 ${20 * k}px ${50 * k}px rgba(0,0,0,${(0.5 * (1 - merge)).toFixed(3)})` : undefined }}>
              <Img src={src} style={{ position: "absolute", top: 0, left: -i * PW, width: W, height: H, objectFit: "cover",
                filter: `brightness(${(0.82 + 0.18 * e).toFixed(3)})` }} />
            </div>
          );
        })}
      </AbsoluteFill>
      <CaptionShade show={cap_} strength={0.6} />
      <LowerCaption ov={overlay} at={38} q={q} accent={accent} />
    </AbsoluteFill>
  );
};

// ================================================================== pe-frame-drop
// The print falls and lands at frame 14 (sfx_at 13); the camera leans in from 18.
const FrameDrop: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const q = useOut();
  const src = photoOf(overlay);
  if (!src) return null;
  const T = 14;
  const fall = interpolate(frame, [0, T], [1, 0], { ...clamp, easing: Easing.in(Easing.quad) });
  const bt = clamp01((frame - T) / 9);
  const bump = frame >= T ? Math.sin(bt * Math.PI) * (1 - bt) : 0;
  const settle = ramp(frame, T, 22);
  const push = interpolate(frame, [18, Math.max(19, dur)], [0, 1], { ...clamp, easing: inOut });
  const PW = 1000 * k, PH = 600 * k, MAT = 44 * k, FR = 28 * k;
  const FW = PW + 2 * (MAT + FR), FH = PH + 2 * (MAT + FR);
  const rot = -8 * fall - 2.2 + 0.8 * settle;
  const scale = 1 + 0.32 * fall - 0.012 * bump;
  const shadow = `${(10 + 40 * fall) * k}px ${(18 + 70 * fall) * k}px ${(30 + 80 * fall) * k}px rgba(0,0,0,${(0.62 - 0.3 * fall).toFixed(3)})`;
  const text = fitLines(cap(overlay.text), 360, [32, 30, 28], 0.5, 2);
  const sub = fitLines(str(overlay.subtitle), 360, [28], 0.52, 2);
  const cardIn = ramp(frame, 22, 16, expoOut);
  const hasCard = text.ls.length > 0 || sub.ls.length > 0;
  const shiftX = hasCard ? -110 * k : 0;
  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 48% 38%, #3a3129 0%, #211c17 50%, #0b0908 100%)", overflow: "hidden" }}>
      <AbsoluteFill style={{ backgroundImage: `repeating-linear-gradient(92deg, rgba(255,255,255,.02) 0px, rgba(255,255,255,.02) ${2 * k}px, rgba(0,0,0,0) ${2 * k}px, rgba(0,0,0,0) ${11 * k}px)` }} />
      <AbsoluteFill style={{ transform: `scale(${1 + 0.1 * push})`, transformOrigin: "48% 50%" }}>
        <div style={{ position: "absolute", left: W / 2 - FW / 2 + shiftX, top: H / 2 - FH / 2, width: FW, height: FH,
          opacity: ramp(frame, 0, 4), transform: `translate(${(40 * fall * k).toFixed(2)}px, ${(-180 * fall * k).toFixed(2)}px) rotate(${rot.toFixed(2)}deg) scale(${scale.toFixed(4)})`,
          boxShadow: shadow, borderRadius: 3 * k,
          background: "linear-gradient(135deg, #3b2c20 0%, #1c140e 45%, #2e2218 100%)", padding: FR }}>
          <div style={{ position: "absolute", inset: FR * 0.35, border: `${Math.max(1, 1.5 * k)}px solid rgba(255,220,170,.12)`, borderRadius: 2 * k }} />
          <div style={{ position: "relative", width: FW - 2 * FR, height: FH - 2 * FR, background: "linear-gradient(170deg, #f7f4ec 0%, #ebe6da 100%)",
            boxShadow: `inset 0 0 ${10 * k}px rgba(0,0,0,.35)`, padding: MAT }}>
            <div style={{ position: "relative", width: PW, height: PH, overflow: "hidden", boxShadow: `inset 0 0 0 ${Math.max(1, k)}px rgba(0,0,0,.25)` }}>
              <Photo src={src} style={{ objectPosition: "50% 32%", filter: "contrast(1.04) saturate(.95)" }} />
              <div style={{ position: "absolute", inset: 0, background: "linear-gradient(125deg, rgba(255,255,255,.14) 0%, rgba(255,255,255,0) 38%)" }} />
            </div>
          </div>
        </div>
        {hasCard ? (
          <div style={{ position: "absolute", left: W / 2 + FW / 2 + shiftX - 90 * k, top: H / 2 + FH / 2 - 150 * k, width: 420 * k,
            padding: `${22 * k}px ${26 * k}px`, background: "#f3efe6", borderRadius: 3 * k, boxShadow: "0 18px 40px rgba(0,0,0,.5)",
            opacity: cardIn * (1 - q), transform: `translate(${((1 - cardIn) * 60 * k).toFixed(2)}px, 0) rotate(${(2.5 - 1.5 * cardIn).toFixed(2)}deg)` }}>
            <div style={{ width: 40 * k, height: 4 * k, background: accent, marginBottom: 12 * k }} />
            {text.ls.map((ln, i) => (
              <div key={i} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: text.size * k, letterSpacing: "0.06em", color: INK,
                lineHeight: 1.1, whiteSpace: "nowrap" }}>{ln}</div>
            ))}
            {sub.ls.map((ln, i) => (
              <div key={`s${i}`} style={{ fontFamily: INTER, fontSize: sub.size * k, color: "#4a4640", lineHeight: 1.25, marginTop: i ? 0 : 8 * k,
                whiteSpace: "nowrap" }}>{ln}</div>
            ))}
          </div>
        ) : null}
      </AbsoluteFill>
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${320 * k}px rgba(0,0,0,.7)` }} />
    </AbsoluteFill>
  );
};

// ================================================================== pe-parallax
// The sharp crop eases in over 4 -> 22, landing at ~14 (sfx_at 14); the layers drift apart for the rest of the look.
const Parallax: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H } = useVideoConfig();
  const k = useK();
  const q = useOut();
  const d = useDrift(inOut);
  const src = photoOf(overlay);
  if (!src) return null;
  const e = ramp(frame, 4, 18, expoOut);
  const dir = hashStr(src) % 2 ? 1 : -1;
  const CW = 1340 * k, CH = 760 * k;
  const cap_ = hasCaption(overlay);
  return (
    <AbsoluteFill style={{ background: "#000", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(1.32) translateX(${(dir * (2.6 - 5.2 * d)).toFixed(3)}%)`, opacity: ramp(frame, 0, 12) }}>
        <Photo src={src} style={{ filter: `blur(${16 * k}px) brightness(.5) saturate(.85)` }} />
      </AbsoluteFill>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 50%, rgba(0,0,0,0) 30%, rgba(0,0,0,.55) 100%)" }} />
      <div style={{ position: "absolute", left: (W - CW) / 2, top: (H - CH) / 2 - 10 * k, width: CW, height: CH, overflow: "hidden",
        borderRadius: 8 * k, boxShadow: `0 ${40 * k}px ${90 * k}px rgba(0,0,0,.65), 0 0 0 ${Math.max(1, k)}px rgba(255,255,255,.14)`,
        opacity: e, transform: `translateX(${(-dir * (34 - 68 * d) * k).toFixed(2)}px) scale(${(1.08 - 0.08 * e).toFixed(4)})` }}>
        <div style={{ position: "absolute", inset: 0, transform: `scale(1.14) translateX(${(dir * (1.8 - 3.6 * d)).toFixed(3)}%)` }}>
          <Photo src={src} style={{ filter: "contrast(1.05)" }} />
        </div>
        {cap_ ? (
          <div style={{ position: "absolute", inset: 0, background: "linear-gradient(0deg, rgba(0,0,0,.72) 0%, rgba(0,0,0,.25) 34%, rgba(0,0,0,0) 55%)" }} />
        ) : null}
        <LowerCaption ov={overlay} at={20} q={q} accent={accent} left={56} bottom={48} room={1150} sizes={[60, 54, 48, 44]} />
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== pe-newsprint
/** The picture as a halftone print: dot size follows darkness (a screen blend thresholded by contrast). */
const Halftone: React.FC<{ src: string; w: number; h: number; cell: number; ink: string }> = ({ src, w, h, cell, ink }) => (
  <div style={{ position: "relative", width: w, height: h, mixBlendMode: "multiply", opacity: 0.94 }}>
    <div style={{ position: "absolute", inset: 0, overflow: "hidden", background: "#fff", filter: "contrast(14)" }}>
      <Img src={src} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover",
        filter: `grayscale(1) brightness(.74) contrast(1.35) blur(${(cell * 0.14).toFixed(2)}px)` }} />
      <div style={{ position: "absolute", inset: "-40%", backgroundImage: "radial-gradient(circle at center, #000 0%, #fff 86%)",
        backgroundSize: `${cell}px ${cell}px`, mixBlendMode: "screen", transform: "rotate(15deg)" }} />
    </div>
    <div style={{ position: "absolute", inset: 0, background: ink, mixBlendMode: "screen" }} />
  </div>
);

// The page slides in over 2 -> 18 and lands at ~12 (sfx_at 12); the headline rises, the camera leans in.
const Newsprint: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width: W } = useVideoConfig();
  const k = useK();
  const q = useOut();
  const d = useDrift();
  const src = photoOf(overlay);
  if (!src) return null;
  const e = ramp(frame, 2, 16, expoOut);
  const PW = 1520 * k;
  const IW = 1360 * k;
  const head = fitLines(str(overlay.text), 1360, [78, 70, 62, 56], 0.5, 2);
  const kick = cap(overlay.label);
  const sub = str(overlay.subtitle);
  const IH = (head.ls.length > 1 ? 560 : 640) * k;
  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 40%, #2a2724 0%, #121110 60%, #070707 100%)", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${1 + 0.07 * d})`, transformOrigin: "50% 62%" }}>
        <div style={{ position: "absolute", left: (W - PW) / 2, top: 64 * k, width: PW, minHeight: 1100 * k, padding: `${36 * k}px ${80 * k}px`,
          background: "linear-gradient(175deg, #efe9dc 0%, #e6dfcf 100%)", boxShadow: "0 30px 90px rgba(0,0,0,.6)",
          opacity: ramp(frame, 2, 5) * (1 - q), transform: `translate(${((1 - e) * 90 * k).toFixed(2)}px, ${((1 - e) * 380 * k + q * 40 * k).toFixed(2)}px) rotate(${(-1.2 - 5 * (1 - e)).toFixed(3)}deg)` }}>
          <div style={{ borderTop: `${3 * k}px solid ${INK}`, borderBottom: `${1.2 * k}px solid ${INK}`, height: 8 * k, marginBottom: 14 * k }} />
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 * k,
            fontFamily: LABEL, fontWeight: 700, fontSize: 28 * k, letterSpacing: "0.22em", color: "#3a3631" }}>
            <span>{kick.slice(0, 48)}</span>
            <span style={{ width: 60 * k, height: 4 * k, background: accent, display: "inline-block" }} />
          </div>
          {head.ls.map((ln, i) => (
            <Rise key={i} at={8 + i * 4} q={0}>
              <div style={{ fontFamily: SERIF, fontWeight: 400, fontSize: head.size * k, lineHeight: 1.08, color: INK, whiteSpace: "nowrap",
                letterSpacing: "-0.01em" }}>{ln}</div>
            </Rise>
          ))}
          <div style={{ height: 1.2 * k, background: INK, margin: `${18 * k}px 0 ${20 * k}px`, opacity: 0.8 }} />
          <div style={{ position: "relative", width: IW, height: IH }}>
            <Halftone src={src} w={IW} h={IH} cell={Math.max(4, 7 * k)} ink="#241f1a" />
          </div>
          {sub ? (
            <div style={{ fontFamily: SERIF_ITALIC, fontSize: 30 * k, color: "#3a3631", marginTop: 12 * k, whiteSpace: "nowrap", overflow: "hidden",
              textOverflow: "ellipsis", maxWidth: IW }}>{sub}</div>
          ) : null}
        </div>
      </AbsoluteFill>
      <Grain opacity={0.08} />
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${300 * k}px rgba(0,0,0,.6)` }} />
    </AbsoluteFill>
  );
};

// ================================================================== pe-punch-in
// The punch lands at frame ~6 (sfx_at 6), then the camera drifts.
const PunchIn: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: dur } = useVideoConfig();
  const q = useOut();
  const src = photoOf(overlay);
  if (!src) return null;
  const punch = ramp(frame, 0, 10, expoOut);
  const driftP = interpolate(frame, [8, Math.max(9, dur)], [0, 1], { ...clamp, easing: drift });
  const s = 1.55 - 0.45 * punch + 0.07 * driftP;
  const blurAmt = 1 - ramp(frame, 0, 9);
  const dir = hashStr(src) % 2 ? 1 : -1;
  const tx = dir * 1.4 * driftP;
  const flash = interpolate(frame, [3, 6, 14], [0, 0.32, 0], clamp);
  const cap_ = hasCaption(overlay);
  return (
    <AbsoluteFill style={{ background: "#000", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${s.toFixed(4)}) translateX(${tx.toFixed(3)}%)` }}>
        <Photo src={src} style={{ filter: `brightness(${(1 + 0.25 * blurAmt).toFixed(3)}) contrast(1.05)` }} />
      </AbsoluteFill>
      {blurAmt > 0.01
        ? [1, 2, 3, 4].map((i) => (
          <AbsoluteFill key={i} style={{ transform: `scale(${(s * (1 + 0.045 * i * blurAmt)).toFixed(4)}) translateX(${tx.toFixed(3)}%)`,
            opacity: (0.34 / i) * blurAmt }}>
            <Photo src={src} />
          </AbsoluteFill>
        ))
        : null}
      <AbsoluteFill style={{ background: "#fff", opacity: flash }} />
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 50%, rgba(0,0,0,0) 48%, rgba(0,0,0,.5) 100%)" }} />
      <CaptionShade show={cap_} strength={0.6} />
      <LowerCaption ov={overlay} at={14} q={q} accent={accent} />
    </AbsoluteFill>
  );
};

// ================================================================== pe-duotone
// The graded picture wipes in over 2 -> 20, half way at ~11 (sfx_at 13); the caption rises from 12.
const Duotone: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const q = useOut();
  const d = useDrift();
  const id = `peDuo${React.useId().replace(/[^A-Za-z0-9]/g, "")}`;
  const src = photoOf(overlay);
  if (!src) return null;
  const dark = mix(accent, "#05070b", 0.84);
  const light = mix(accent, "#ffffff", 0.5);
  const wipe = ramp(frame, 2, 18, inOut);
  const words = str(overlay.text).split(" ").filter(Boolean).length;
  const title = fitLines(cap(overlay.text), 1250, words <= 4 ? [124, 112, 100, 88, 76] : [92, 84, 76, 68, 60], 0.6, 3);
  const sub = cap(overlay.subtitle) || cap(overlay.label);
  const rule = ramp(frame, 10, 18, inOut) * (1 - q);
  const x = -20 + 140 * wipe;
  return (
    <AbsoluteFill style={{ background: dark, overflow: "hidden" }}>
      <DuoFilter id={id} dark={dark} light={light} />
      <AbsoluteFill style={{ clipPath: `polygon(0 0, ${x}% 0, ${x - 20}% 100%, 0 100%)` }}>
        <AbsoluteFill style={{ transform: `scale(${1.1 + 0.07 * d})` }}>
          <Photo src={src} style={{ filter: `brightness(1.12) contrast(1.3) url(#${id})` }} />
        </AbsoluteFill>
      </AbsoluteFill>
      <AbsoluteFill style={{ background: `linear-gradient(90deg, ${rgba(dark, 0.82)} 0%, ${rgba(dark, 0.45)} 45%, ${rgba(dark, 0)} 75%)` }} />
      <Grain opacity={0.07} />
      <div style={{ position: "absolute", left: 120 * k, bottom: 150 * k, display: "flex", flexDirection: "column", maxWidth: 1320 * k }}>
        <div style={{ width: 140 * k * rule, height: 5 * k, background: light, marginBottom: 26 * k }} />
        {title.ls.map((ln, i) => (
          <Rise key={i} at={12 + i * 4} q={q}>
            <div style={{ fontFamily: INTER, fontWeight: 800, fontSize: title.size * k, letterSpacing: "-0.02em", lineHeight: 1.0, color: "#fff",
              whiteSpace: "nowrap", textShadow: "0 8px 40px rgba(0,0,0,.35)" }}>{ln}</div>
          </Rise>
        ))}
        {sub ? (
          <Rise at={20 + title.ls.length * 4} q={q} style={{ marginTop: 22 * k }}>
            <div style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 32 * k, letterSpacing: "0.24em", color: light, whiteSpace: "nowrap" }}>
              {sub.slice(0, 60)}
            </div>
          </Rise>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== pe-light-sweep
const Pin: React.FC<{ size: number; color: string }> = ({ size, color }) => (
  <svg width={size} height={size * 1.3} viewBox="0 0 24 31">
    <path d="M12 1.5C6.2 1.5 1.8 5.9 1.8 11.6c0 7.4 10.2 17.9 10.2 17.9s10.2-10.5 10.2-17.9C22.2 5.9 17.8 1.5 12 1.5z" fill={color} />
    <circle cx={12} cy={11.4} r={3.9} fill="rgba(0,0,0,.55)" />
  </svg>
);

// The light crosses the frame centre at ~22 (sfx_at 22); the location label rises from 18.
const LightSweep: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const q = useOut();
  const d = useDrift();
  const src = photoOf(overlay);
  if (!src) return null;
  const ORIGINS = ["30% 40%", "70% 40%", "40% 60%", "62% 58%"];
  const origin = ORIGINS[hashStr(src) % ORIGINS.length];
  const sweep = interpolate(frame, [6, 40], [-60, 150], { ...clamp, easing: inOut });
  const sweepA = ramp(frame, 6, 8) * (1 - ramp(frame, 34, 10));
  const place = fitLines(cap(overlay.text), 900, [44, 40, 36, 32], 0.55, 2);
  const sub = str(overlay.subtitle) || str(overlay.label);
  const pin = ramp(frame, 16, 14, backOut);
  const line = ramp(frame, 20, 20, inOut) * (1 - q);
  return (
    <AbsoluteFill style={{ background: "#000", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${1.04 + 0.1 * d})`, transformOrigin: origin, opacity: ramp(frame, 0, 12) }}>
        <Photo src={src} style={{ filter: "contrast(1.06) saturate(.92)" }} />
      </AbsoluteFill>
      <AbsoluteFill style={{ opacity: sweepA, mixBlendMode: "screen", transform: `translateX(${sweep.toFixed(2)}%)`,
        background: "linear-gradient(115deg, rgba(255,236,200,0) 30%, rgba(255,236,200,.16) 42%, rgba(255,244,222,.45) 50%, rgba(255,236,200,.16) 58%, rgba(255,236,200,0) 70%)" }} />
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 45%, rgba(0,0,0,0) 45%, rgba(0,0,0,.55) 100%)" }} />
      <Grain opacity={0.13} />
      {place.ls.length ? (
        <>
          <AbsoluteFill style={{ background: "linear-gradient(15deg, rgba(0,0,0,.6) 0%, rgba(0,0,0,.2) 25%, rgba(0,0,0,0) 45%)" }} />
          <div style={{ position: "absolute", left: 110 * k, bottom: 118 * k, display: "flex", alignItems: "flex-start", gap: 20 * k }}>
            <div style={{ transform: `scale(${pin * (1 - q)})`, transformOrigin: "50% 100%", marginTop: 2 * k,
              filter: `drop-shadow(0 ${4 * k}px ${8 * k}px rgba(0,0,0,.5))` }}>
              <Pin size={34 * k} color={accent} />
            </div>
            <div style={{ display: "flex", flexDirection: "column" }}>
              {place.ls.map((ln, i) => (
                <Rise key={i} at={18 + i * 4} q={q}>
                  <div style={{ fontFamily: LABEL, fontWeight: 700, fontSize: place.size * k, letterSpacing: "0.14em", color: "#fff",
                    lineHeight: 1.08, whiteSpace: "nowrap", textShadow: SHADOW }}>{ln}</div>
                </Rise>
              ))}
              <div style={{ width: 240 * k * line, height: 2 * k, background: "rgba(255,255,255,.75)", margin: `${10 * k}px 0` }} />
              {sub ? (
                <Rise at={28} q={q}>
                  <div style={{ fontFamily: INTER, fontSize: 30 * k, color: "rgba(255,255,255,.85)", whiteSpace: "nowrap", textShadow: SHADOW }}>
                    {sub.slice(0, 60)}
                  </div>
                </Rise>
              ) : null}
            </div>
          </div>
        </>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== pe-polaroid-pan
/** Handwriting: each letter inked left to right with a soft clip wipe. */
const Handwrite: React.FC<{ text: string; at: number; step: number; style: React.CSSProperties }> = ({ text, at, step, style }) => {
  const frame = useCurrentFrame();
  return (
    <div style={{ whiteSpace: "pre", lineHeight: 1.15, ...style }}>
      {Array.from(text).map((c, i) => {
        const p = ramp(frame, at + i * step, 7);
        return (
          <span key={i} style={{ display: "inline-block", opacity: p > 0.01 ? 1 : 0,
            clipPath: p >= 0.999 ? undefined : `inset(-40% ${((1 - p) * 125 - 25).toFixed(1)}% -40% 0)` }}>{c}</span>
        );
      })}
    </div>
  );
};

// The shutter fires at frame 3 (sfx_at 3); the caption is handwritten from 14 while the camera pans.
const PolaroidPan: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H } = useVideoConfig();
  const k = useK();
  const q = useOut();
  const d = useDrift(inOut);
  const src = photoOf(overlay);
  if (!src) return null;
  const flash = interpolate(frame, [0, 3, 12], [0, 0.9, 0], clamp);
  const expose = ramp(frame, 3, 16);
  const B = 40 * k, PW = 900 * k, PH = 620 * k, BOT = 190 * k;
  const CW = PW + 2 * B, CH = B + PH + BOT;
  const dir = hashStr(src) % 2 ? 1 : -1;
  const x = dir * (170 - 340 * d) * k;
  const cap_ = fitLines(str(overlay.text), 820, [64, 58, 52], 0.42, 1);
  const date = str(overlay.label);
  const n = Array.from(cap_.ls.join("")).length;
  const step = Math.max(0.6, Math.min(1.3, 34 / Math.max(1, n + date.length)));
  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 45% 35%, #4a4035 0%, #2a241e 55%, #120f0c 100%)", overflow: "hidden" }}>
      <AbsoluteFill style={{ backgroundImage: `repeating-linear-gradient(0deg, rgba(255,255,255,.018) 0px, rgba(255,255,255,.018) ${1.5 * k}px, rgba(0,0,0,0) ${1.5 * k}px, rgba(0,0,0,0) ${6 * k}px), repeating-linear-gradient(90deg, rgba(0,0,0,.05) 0px, rgba(0,0,0,.05) ${1.5 * k}px, rgba(0,0,0,0) ${1.5 * k}px, rgba(0,0,0,0) ${7 * k}px)` }} />
      <div style={{ position: "absolute", left: W / 2 - CW / 2, top: H / 2 - CH / 2, width: CW, height: CH,
        background: "linear-gradient(172deg, #fcfbf7 0%, #efebe1 100%)", borderRadius: 3 * k,
        boxShadow: `${14 * k}px ${30 * k}px ${60 * k}px rgba(0,0,0,.55), 0 ${2 * k}px ${4 * k}px rgba(0,0,0,.3)`,
        opacity: 1 - q, transform: `translate(${x.toFixed(2)}px, ${(q * 30 * k).toFixed(2)}px) rotate(${(2.6 - 1.2 * d).toFixed(3)}deg) scale(${(1.1 - 0.03 * d).toFixed(4)})` }}>
        <div style={{ position: "absolute", left: B, top: B, width: PW, height: PH, overflow: "hidden", background: "#222" }}>
          <Photo src={src} style={{ filter: `brightness(${(1.7 - 0.7 * expose).toFixed(3)}) saturate(${(0.6 + 0.35 * expose).toFixed(3)}) contrast(${(0.8 + 0.25 * expose).toFixed(3)}) sepia(.08)` }} />
          <div style={{ position: "absolute", inset: 0, background: "linear-gradient(125deg, rgba(255,255,255,.16) 0%, rgba(255,255,255,0) 40%)" }} />
          <div style={{ position: "absolute", inset: 0, boxShadow: `inset 0 0 ${40 * k}px rgba(0,0,0,.3)` }} />
        </div>
        <div style={{ position: "absolute", left: B + 10 * k, right: B + 10 * k, top: B + PH + 36 * k, display: "flex",
          justifyContent: "space-between", alignItems: "flex-start", gap: 24 * k }}>
          {cap_.ls.length ? (
            <Handwrite text={cap_.ls[0]} at={14} step={step} style={{ fontFamily: HAND, fontWeight: 700, fontSize: cap_.size * k, color: "#1f2440" }} />
          ) : <span />}
          {date ? (
            <Handwrite text={date.slice(0, 18)} at={14 + n * step + 4} step={step}
              style={{ fontFamily: HAND, fontWeight: 600, fontSize: 40 * k, color: "#1f2440", opacity: 0.8, marginTop: 10 * k }} />
          ) : null}
        </div>
      </div>
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${320 * k}px rgba(0,0,0,.65)` }} />
      <AbsoluteFill style={{ background: "#fff", opacity: flash }} />
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ marks on the photo
/** overlay.anchor.r (the thing's radius, 0..0.5 of the frame's shorter side) when given, else `def`. */
const anchorR = (ov: Overlay, def: number): number => {
  const a = ov.anchor as { r?: unknown } | undefined;
  const r = a && typeof a === "object" ? Number(a.r) : NaN;
  return Number.isFinite(r) && r > 0 ? Math.min(0.5, r) : def;
};
const rot = (p: Pt, deg: number): Pt => {
  const a = (deg * Math.PI) / 180;
  return [p[0] * Math.cos(a) - p[1] * Math.sin(a), p[0] * Math.sin(a) + p[1] * Math.cos(a)];
};

// ================================================================== pe-case-file
/** A gem paper clip, 46 x 132 px at scale 1 (wire drawn as one path). */
const PaperClip: React.FC<{ x: number; y: number; s: number; angle: number; id: string }> = ({ x, y, s, angle, id }) => {
  const d = "M 16 40 V 104 A 7 7 0 0 0 30 104 V 20 A 12 12 0 0 0 6 20 V 112 A 17 17 0 0 0 40 112 V 34";
  return (
    <svg width={52 * s} height={140 * s} viewBox="-3 -3 52 140" style={{ position: "absolute", left: x, top: y, overflow: "visible",
      transform: `rotate(${angle}deg)`, transformOrigin: "50% 30%", filter: `drop-shadow(${2 * s}px ${3 * s}px ${2.5 * s}px rgba(0,0,0,.45))` }}>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#7e858d" />
          <stop offset="35%" stopColor="#eef1f4" />
          <stop offset="60%" stopColor="#a7aeb6" />
          <stop offset="100%" stopColor="#dfe3e7" />
        </linearGradient>
      </defs>
      <path d={d} fill="none" stroke="rgba(40,44,50,.55)" strokeWidth={5.4} strokeLinecap="round" strokeLinejoin="round" />
      <path d={d} fill="none" stroke={`url(#${id})`} strokeWidth={3.8} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
};

/** Rows of "typed" words at a glance: grey word bars, a heading, one redaction bar. Deterministic from `seed`. */
const TypedLines: React.FC<{ w: number; rows: number; u: number; seed: number }> = ({ w, rows, u, seed }) => {
  const rnd = (i: number) => {
    const x = Math.sin((i + 1) * 12.9898 + seed * 78.233) * 43758.5453;
    return x - Math.floor(x);
  };
  const out: React.ReactNode[] = [];
  for (let r = 0; r < rows; r++) {
    const words: React.ReactNode[] = [];
    let x = 0;
    const end = r % 5 === 4 ? w * (0.35 + 0.3 * rnd(r * 7)) : w;
    for (let j = 0; x < end - 30 * u && j < 16; j++) {
      const ww = Math.min(end - x, (22 + 70 * rnd(r * 31 + j)) * u);
      const redact = r === 6 && j >= 1 && j <= 3;
      words.push(<div key={j} style={{ position: "absolute", left: x, top: 0, width: ww, height: redact ? 15 * u : 8 * u,
        marginTop: redact ? -3.5 * u : 0, borderRadius: 1.5 * u, background: redact ? "#15130f" : "rgba(38,34,28,.5)" }} />);
      x += ww + (redact ? 0 : 11 * u);
    }
    out.push(<div key={r} style={{ position: "relative", height: 8 * u, marginBottom: 20 * u }}>{words}</div>);
  }
  return <div style={{ width: w }}>{out}</div>;
};

// The print drops onto the folder and lands at 13 (sfx_at 12, paper-slide); the label strip slaps on 16 -> 24;
// the red marker circle draws 24 -> 42; the camera settles, then pushes into the circle from 20 to the end.
const CaseFile: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const u = W / 1920;
  const q = useOut();
  const uid = React.useId().replace(/[^A-Za-z0-9]/g, "");
  const src = photoOf(overlay);
  if (!src) return null;
  const [ax, ay] = anchorOf(overlay, 0.62, 0.44, 0.08, 0.92);
  const seed = hashStr(src) % 97;
  // The folder: a closed manila folder on the desk, turned a little; everything below is in its frame.
  const FX = 176 * u, FY = 168 * u, FW = 1568 * u, FH = 846 * u, FROT = -1.2;
  // The print: the 16:9 photo in a white border, clipped on the folder's left, turned the other way.
  const B = 16 * u, PW = 1024 * u, PH = (PW * 9) / 16;
  const PRW = PW + 2 * B, PRH = PH + 2 * B;
  const PX = 64 * u, PY = 58 * u, PROT = -1.6;
  // Where the circle's centre lands on screen (the camera pushes about it).
  const local: Pt = [B + ax * PW, B + ay * PH];
  const inFolder: Pt = (() => {
    const v = rot([local[0] - PRW / 2, local[1] - PRH / 2], PROT);
    return [PX + PRW / 2 + v[0], PY + PRH / 2 + v[1]];
  })();
  const screen: Pt = (() => {
    const v = rot([inFolder[0] - FW / 2, inFolder[1] - FH / 2], FROT);
    return [FX + FW / 2 + v[0], FY + FH / 2 + v[1]];
  })();
  const settle = ramp(frame, 0, 22);
  const push = interpolate(frame, [20, Math.max(21, dur)], [0, 1], { ...clamp, easing: inOut });
  const cam = (1.035 - 0.035 * settle) * (1 + 0.17 * push);
  // The print falls and lands at 13 with a small bump.
  const LAND = 13;
  const fall = interpolate(frame, [1, LAND], [1, 0], { ...clamp, easing: Easing.in(Easing.quad) });
  const bt = clamp01((frame - LAND) / 8);
  const bump = frame >= LAND ? Math.sin(bt * Math.PI) * (1 - bt) : 0;
  const printS = 1 + 0.09 * fall - 0.008 * bump;
  const printShadow = `${(6 + 30 * fall) * u}px ${(10 + 46 * fall) * u}px ${(16 + 50 * fall) * u}px rgba(0,0,0,${(0.42 - 0.18 * fall).toFixed(3)})`;
  // The typed label strip.
  const text = cap(overlay.text);
  const strip = fitLines(text, 760, [46, 42, 38, 34], 0.66, 1);
  const slap = ramp(frame, 16, 9, backOut);
  const tab = cap(overlay.label) || "CASE FILE";
  const sub = cap(overlay.subtitle);
  // The marker circle round the point, in the photo's own pixels.
  const rPx = anchorR(overlay, 0.13) * PH;
  const rx = Math.max(64 * u, Math.min(PW * 0.42, rPx * 1.18 + 16 * u));
  const ry = Math.max(54 * u, Math.min(PH * 0.44, rPx * 0.96 + 14 * u));
  const loop = loopPts(B + ax * PW, B + ay * PH, rx, ry, seed, 1.12, -0.09);
  const draw = ramp(frame, 24, 18, PEN);
  const manila = "linear-gradient(162deg, #e9d19d 0%, #dfc189 38%, #d5b477 72%, #cfab6c 100%)";
  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 44% 38%, #3b2d21 0%, #21180f 55%, #0c0806 100%)", overflow: "hidden" }}>
      <AbsoluteFill style={{ backgroundImage: `repeating-linear-gradient(87deg, rgba(255,235,210,.022) 0px, rgba(255,235,210,.022) ${2 * u}px, rgba(0,0,0,0) ${2 * u}px, rgba(0,0,0,0) ${13 * u}px)` }} />
      <AbsoluteFill style={{ transform: `scale(${cam.toFixed(4)})`, transformOrigin: `${screen[0].toFixed(1)}px ${screen[1].toFixed(1)}px` }}>
        <div style={{ position: "absolute", left: FX, top: FY, width: FW, height: FH, transform: `rotate(${FROT}deg)` }}>
          {/* The back cover's edge, the tab, the front cover. */}
          <div style={{ position: "absolute", left: 12 * u, top: 10 * u, width: FW, height: FH, borderRadius: 10 * u,
            background: "linear-gradient(162deg, #cfb07a 0%, #bf9d63 100%)", boxShadow: `0 ${30 * u}px ${70 * u}px rgba(0,0,0,.6)` }} />
          <div style={{ position: "absolute", left: 70 * u, top: -54 * u, width: 430 * u, height: 70 * u, borderRadius: `${14 * u}px ${14 * u}px 0 0`,
            background: manila, boxShadow: `inset 0 ${2 * u}px 0 rgba(255,255,255,.25)`, display: "flex", alignItems: "flex-start",
            padding: `${12 * u}px ${26 * u}px 0`, overflow: "hidden" }}>
            <div style={{ fontFamily: TYPEWRITER, fontWeight: 700, fontSize: 28 * u, letterSpacing: "0.14em", color: "#3a2a15",
              whiteSpace: "nowrap", opacity: 0.88 }}>{tab.slice(0, 22)}</div>
          </div>
          <div style={{ position: "absolute", inset: 0, borderRadius: `0 ${10 * u}px ${10 * u}px ${10 * u}px`, background: manila,
            boxShadow: `inset 0 0 0 ${1.5 * u}px rgba(120,86,40,.35), inset 0 ${-30 * u}px ${60 * u}px rgba(120,80,30,.12)`, overflow: "hidden" }}>
            <svg width={FW} height={FH} style={{ position: "absolute", inset: 0, opacity: 0.2, mixBlendMode: "multiply" }}>
              <filter id={`cfp${uid}`} x="0" y="0" width="100%" height="100%">
                <feTurbulence type="fractalNoise" baseFrequency={0.75} numOctaves={3} seed={seed} stitchTiles="stitch" />
                <feColorMatrix type="matrix" values="0 0 0 0 .45  0 0 0 0 .32  0 0 0 0 .16  0 0 0 1.1 -.35" />
              </filter>
              <rect width={FW} height={FH} filter={`url(#cfp${uid})`} />
            </svg>
            <div style={{ position: "absolute", left: 0, right: 0, top: FH * 0.9, height: Math.max(1, 1.5 * u), background: "rgba(110,78,36,.28)",
              boxShadow: `0 ${1.5 * u}px 0 rgba(255,245,220,.25)` }} />
          </div>
          {/* A typed report under the print. */}
          <div style={{ position: "absolute", left: 1060 * u, top: 64 * u, width: 450 * u, height: 700 * u, background: "#f6f2e8",
            transform: "rotate(2.4deg)", boxShadow: `0 ${6 * u}px ${18 * u}px rgba(0,0,0,.3)`,
            padding: `${52 * u}px ${40 * u}px ${52 * u}px ${104 * u}px`, overflow: "hidden" }}>
            {sub ? (
              <div style={{ fontFamily: TYPEWRITER, fontWeight: 700, fontSize: 24 * u, letterSpacing: "0.1em", color: "#2a2620",
                marginBottom: 28 * u, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 306 * u }}>{sub}</div>
            ) : (
              <div style={{ width: 230 * u, height: 14 * u, borderRadius: 2 * u, background: "rgba(30,27,22,.78)", marginBottom: 34 * u }} />
            )}
            <TypedLines w={306 * u} rows={17} u={u} seed={seed} />
          </div>
          {/* The print, with the marker circle drawn on it. */}
          <div style={{ position: "absolute", left: PX, top: PY, width: PRW, height: PRH, background: "#fbfaf6",
            transform: `translateY(${(-60 * u * fall).toFixed(2)}px) rotate(${PROT}deg) scale(${printS.toFixed(4)})`, boxShadow: printShadow,
            opacity: ramp(frame, 0, 3, Easing.linear) }}>
            <div style={{ position: "absolute", left: B, top: B, width: PW, height: PH, overflow: "hidden", background: "#222" }}>
              <Photo src={src} style={{ filter: "contrast(1.05) saturate(.9) sepia(.06)" }} />
              <div style={{ position: "absolute", inset: 0, background: "linear-gradient(128deg, rgba(255,255,255,.12) 0%, rgba(255,255,255,0) 36%)" }} />
              <div style={{ position: "absolute", inset: 0, boxShadow: `inset 0 0 ${30 * u}px rgba(0,0,0,.28)` }} />
            </div>
            <svg width={PRW} height={PRH} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
              <MarkerLoop pts={loop} to={draw} width={10 * u} k={u} seed={seed} />
            </svg>
          </div>
          <PaperClip x={PX + 90 * u} y={PY - 50 * u} s={u * 1.05} angle={-8} id={`cfc${uid}`} />
          {/* The typed label strip, taped on under the print. */}
          {strip.ls.length ? (
            <div style={{ position: "absolute", left: PX + 44 * u, top: PY + PRH - 30 * u, opacity: clamp01(slap * 3),
              transform: `rotate(${(1.1 + 3 * (1 - slap)).toFixed(3)}deg) scale(${(1.14 - 0.14 * slap).toFixed(4)})`, transformOrigin: "30% 50%" }}>
              <div style={{ position: "relative", background: "linear-gradient(180deg, #fbf6e8 0%, #f1e9d3 100%)", padding: `${12 * u}px ${30 * u}px ${10 * u}px`,
                boxShadow: `0 ${4 * u}px ${12 * u}px rgba(0,0,0,.35)`, fontFamily: TYPEWRITER, fontWeight: 700, fontSize: strip.size * u,
                letterSpacing: "0.06em", color: "#1d1a15", whiteSpace: "nowrap", lineHeight: 1.1 }}>
                {strip.ls[0]}
                {[-1, 1].map((sd) => (
                  <div key={sd} style={{ position: "absolute", top: -12 * u, bottom: -12 * u, [sd < 0 ? "left" : "right"]: -16 * u, width: 50 * u,
                    background: "linear-gradient(180deg, rgba(250,246,232,.78) 0%, rgba(236,230,212,.7) 100%)",
                    boxShadow: `0 ${1 * u}px ${3 * u}px rgba(0,0,0,.14)`, transform: `rotate(${sd * 4.5}deg)`,
                    clipPath: "polygon(0% 3%, 22% 0%, 48% 3%, 76% 0%, 100% 3%, 100% 97%, 74% 100%, 50% 97%, 24% 100%, 0% 97%)" } as React.CSSProperties} />
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </AbsoluteFill>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 38% 30%, rgba(255,226,180,.07) 0%, rgba(0,0,0,0) 45%, rgba(0,0,0,.5) 100%)" }} />
      <Grain opacity={0.06} />
    </AbsoluteFill>
  );
};

// ================================================================== pe-circle-spotlight
// The spotlight opens 3 -> 21 while the rest dims and softens; the red ring draws 10 -> 26 (sfx_at 13);
// the leader draws from 22 and the label rises from 26. At the exit the ring erases and the iris opens.
const CircleSpotlight: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const q = useOut();
  const src = photoOf(overlay);
  if (!src) return null;
  const [ax, ay] = anchorOf(overlay, 0.6, 0.44, 0.06, 0.94);
  // The circle stays whole on screen: smaller near an edge (never under 120 px), then nudged in.
  const edgeRoom = Math.min(ax * W, (1 - ax) * W, ay * H, (1 - ay) * H) - 18 * k;
  const Rb = Math.max(120 * k, Math.min(320 * k, edgeRoom, anchorR(overlay, 0.15) * Math.min(W, H) * 1.18 + 22 * k));
  const cx = Math.max(Rb + 18 * k, Math.min(W - Rb - 18 * k, ax * W));
  const cy = Math.max(Rb + 18 * k, Math.min(H - Rb - 18 * k, ay * H));
  const grow = ramp(frame, 3, 18);
  const dim = ramp(frame, 2, 16, inOut) * (1 - q);
  const R = Rb * (0.3 + 0.7 * grow) * (1 + 6 * q * q);
  const push = interpolate(frame, [0, Math.max(1, dur)], [0, 1], { ...clamp, easing: drift });
  const s = 1.015 + 0.075 * push;
  const origin = `${cx.toFixed(1)}px ${cy.toFixed(1)}px`;
  const ring = ramp(frame, 10, 16, PEN);
  const ringOut = ramp(frame, dur - 15, 10, expoIn);
  // The label on a leader line, on the side with room.
  const title = fitCaps(cap(overlay.text), 560 * k, [56 * k, 50 * k, 44 * k], 2);
  const sub = str(overlay.subtitle).slice(0, 60);
  const titleW = Math.max(0, ...title.ls.map((l) => l.length * title.size * 0.55));
  const subW = sub.length * 28 * k * 0.5;
  const labelW = Math.max(titleW, subW);
  const M = 110 * k;
  const roomR = W - M - (cx + Rb + 90 * k), roomL = cx - Rb - 90 * k - M;
  const onRight = roomR >= labelW || roomR >= roomL;
  const sd = onRight ? 1 : -1;
  const up = cy > H * 0.38;
  const ang = ((up ? -36 : 36) * Math.PI) / 180;
  const P0 = { x: cx + sd * Math.cos(ang) * Rb, y: cy + Math.sin(ang) * Rb };
  const P1 = { x: P0.x + sd * 58 * k, y: P0.y + (up ? -46 : 46) * k };
  const run = Math.max(160 * k, Math.min(labelW + 24 * k, onRight ? W - M - P1.x : P1.x - M));
  const P2 = { x: P1.x + sd * run, y: P1.y };
  const lead = ramp(frame, 22, 12, inOut) * (1 - ringOut);
  const dot = ramp(frame, 22, 8, backOut) * (1 - ringOut);
  const hasLabel = title.ls.length > 0 || Boolean(sub);
  const textSide: React.CSSProperties = onRight ? { left: P1.x + 4 * k } : { right: W - (P1.x - 4 * k) };
  return (
    <AbsoluteFill style={{ background: "#000", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${s.toFixed(4)})`, transformOrigin: origin }}>
        <Photo src={src} style={{ filter: `brightness(${(1 - 0.56 * dim).toFixed(3)}) saturate(${(1 - 0.65 * dim).toFixed(3)}) blur(${(2.5 * k * dim).toFixed(2)}px)` }} />
      </AbsoluteFill>
      <AbsoluteFill style={{ clipPath: `circle(${R.toFixed(1)}px at ${cx.toFixed(1)}px ${cy.toFixed(1)}px)` }}>
        <AbsoluteFill style={{ transform: `scale(${s.toFixed(4)})`, transformOrigin: origin }}>
          <Photo src={src} style={{ filter: "contrast(1.06) saturate(1.04) brightness(1.03)" }} />
        </AbsoluteFill>
      </AbsoluteFill>
      <AbsoluteFill style={{ opacity: dim, background: `radial-gradient(circle at ${cx.toFixed(1)}px ${cy.toFixed(1)}px, rgba(0,0,0,0) ${R.toFixed(1)}px, ` +
        `rgba(0,0,0,.34) ${(R + 1.5 * k).toFixed(1)}px, rgba(0,0,0,0) ${(R + 110 * k).toFixed(1)}px)` }} />
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        <circle cx={cx} cy={cy} r={R + 9 * k} fill="none" stroke="rgba(255,255,255,.5)" strokeWidth={1.6 * k}
          strokeOpacity={ramp(frame, 18, 12) * (1 - ringOut)} />
        <circle cx={cx} cy={cy} r={R} fill="none" stroke={MARK_RED} strokeWidth={6.5 * k} strokeLinecap="round" pathLength={1}
          transform={`rotate(-100 ${cx} ${cy})`} strokeDasharray={`${Math.max(0.0001, ring - ringOut).toFixed(4)} 2`}
          strokeDashoffset={(-ringOut).toFixed(4)} strokeOpacity={ring - ringOut > 0.002 ? 1 : 0} style={{ filter: markShadow(k) }} />
        {hasLabel && lead > 0.01 ? (
          <g style={{ filter: `drop-shadow(0 ${1.5 * k}px ${3 * k}px rgba(0,0,0,.6))` }}>
            <path d={`M${P0.x} ${P0.y} L${P1.x} ${P1.y} L${P2.x} ${P2.y}`} fill="none" stroke="#fff" strokeWidth={2.6 * k}
              strokeLinecap="round" strokeLinejoin="round" pathLength={1} strokeDasharray={`${lead.toFixed(4)} 2`} />
            <circle cx={P0.x} cy={P0.y} r={Math.max(0, 6.5 * k * dot)} fill={MARK_RED} stroke="#fff" strokeWidth={2 * k} />
          </g>
        ) : null}
      </svg>
      {hasLabel ? (
        <>
          <div style={{ position: "absolute", ...textSide, bottom: H - (P1.y - 10 * k), display: "flex", flexDirection: "column",
            alignItems: onRight ? "flex-start" : "flex-end" }}>
            {title.ls.map((ln, i) => (
              <Rise key={i} at={26 + i * 4} q={q}>
                <div style={{ fontFamily: LABEL, fontWeight: 800, fontSize: title.size, letterSpacing: "0.04em", color: "#fff", lineHeight: 1.02,
                  whiteSpace: "nowrap", textShadow: SHADOW }}>{ln}</div>
              </Rise>
            ))}
          </div>
          {sub ? (
            <div style={{ position: "absolute", ...textSide, top: P1.y + 12 * k }}>
              <Rise at={32} q={q}>
                <div style={{ fontFamily: INTER, fontWeight: 400, fontSize: 28 * k, color: "rgba(255,255,255,.9)", whiteSpace: "nowrap",
                  textShadow: SHADOW }}>{sub}</div>
              </Rise>
            </div>
          ) : null}
        </>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== pe-magnify
// The lens glides in from the lower right on a curve and settles over the point at ~22 (sfx_at 14, the
// whoosh); it floats while it holds, the label pops beside it at 22, and at the exit the lens lifts away.
const Magnify: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H, durationInFrames: dur, fps } = useVideoConfig();
  const k = useK();
  const u = W / 1920;
  const q = useOut();
  const uid = React.useId().replace(/[^A-Za-z0-9]/g, "");
  const src = photoOf(overlay);
  if (!src) return null;
  const [ax, ay] = anchorOf(overlay, 0.56, 0.46, 0.06, 0.94);
  const A = { x: ax * W, y: ay * H };
  const RL = 214 * u, RIM = 17 * u;
  // Enough magnification to matter, less for a big thing (it must still fit the lens).
  const MAG = Math.max(1.7, Math.min(2.3, (RL * 0.78) / Math.max(1, anchorR(overlay, 0.07) * Math.min(W, H))));
  const push = interpolate(frame, [0, Math.max(1, dur)], [0, 1], { ...clamp, easing: drift });
  const s = 1 + 0.05 * push;
  const edge = RL + RIM + 70 * u;
  const Lf = { x: Math.max(edge, Math.min(W - edge, A.x)), y: Math.max(edge, Math.min(H - edge, A.y)) };
  const g = ramp(frame, 0, 22, Easing.bezier(0.2, 0.62, 0.3, 1));
  const P0 = { x: Lf.x + 760 * u, y: H + RL + 180 * u };
  const C = { x: Lf.x + 600 * u, y: Lf.y + 60 * u };
  const bz = (t: number) => ({
    x: (1 - t) * (1 - t) * P0.x + 2 * (1 - t) * t * C.x + t * t * Lf.x,
    y: (1 - t) * (1 - t) * P0.y + 2 * (1 - t) * t * C.y + t * t * Lf.y,
  });
  const hoverT = Math.max(0, frame - 22) / fps;
  const hov = { x: Math.sin(hoverT * 1.25) * 5 * u * g, y: Math.sin(hoverT * 0.95 + 1.2) * 4 * u * g };
  const lift = q;
  const B0 = bz(g);
  const L = { x: B0.x + hov.x + lift * 40 * u, y: B0.y + hov.y - lift * 60 * u };
  const lensS = 1 + 0.08 * lift;
  const lensO = 1 - lift;
  // What the lens shows: the photo about F (the point under it, drifting to the anchor as it settles), MAG times larger.
  const F = { x: L.x + (A.x - Lf.x) * g, y: L.y + (A.y - Lf.y) * g };
  const sc = s * MAG;
  const imgL = RL + MAG * (A.x * (1 - s) - F.x), imgT = RL + MAG * (A.y * (1 - s) - F.y);
  // The label beside the lens, away from the handle (lower right).
  const title = fitCaps(cap(overlay.text), 520 * k, [52 * k, 46 * k, 42 * k], 2);
  const sub = str(overlay.subtitle).slice(0, 48);
  const box = labelSize(title.ls, title.size, k, sub, 26 * k);
  const M = 110 * u;
  const leftRoom = Lf.x - RL - RIM - 40 * u - M;
  let css: React.CSSProperties;
  let origin: string;
  if (box.w <= leftRoom) {
    css = { right: W - (Lf.x - RL - RIM - 40 * u), top: Math.max(M, Math.min(H - M - box.h, Lf.y - RL * 0.62)) };
    origin = "100% 50%";
  } else if (Lf.x + RL + RIM + 40 * u + box.w <= W - M) {
    css = { left: Lf.x + RL + RIM + 40 * u, top: Math.max(M, Math.min(H - M - box.h, Lf.y - RL - 10 * u)) };
    origin = "0% 50%";
  } else {
    css = { left: Math.max(M, Math.min(W - M - box.w, Lf.x - box.w / 2)), bottom: H - (Lf.y - RL - RIM - 28 * u) };
    origin = "50% 100%";
  }
  const pop = ramp(frame, 22, 12, backOut);
  const hasLabel = title.ls.length > 0 || Boolean(sub);
  const D = 2 * (RL + RIM);
  const rim = RL + RIM / 2;
  return (
    <AbsoluteFill style={{ background: "#000", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${s.toFixed(4)})`, transformOrigin: `${A.x.toFixed(1)}px ${A.y.toFixed(1)}px` }}>
        <Photo src={src} style={{ filter: `contrast(1.03) brightness(${(1 - 0.14 * g * (1 - lift)).toFixed(3)})` }} />
      </AbsoluteFill>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 50%, rgba(0,0,0,0) 55%, rgba(0,0,0,.4) 100%)" }} />
      <div style={{ position: "absolute", left: L.x - RL - RIM, top: L.y - RL - RIM, width: D, height: D, opacity: lensO,
        transform: `scale(${lensS.toFixed(4)})`, transformOrigin: "50% 50%" }}>
        {/* The shadow the glass and its handle cast on the photo. */}
        <div style={{ position: "absolute", left: 30 * u, top: 40 * u, width: D, height: D, borderRadius: "50%",
          background: "radial-gradient(circle, rgba(0,0,0,.55) 58%, rgba(0,0,0,0) 72%)", filter: `blur(${10 * u}px)` }} />
        <div style={{ position: "absolute", left: D / 2 + 30 * u, top: D / 2 + 40 * u, width: 300 * u, height: 50 * u, borderRadius: 25 * u,
          background: "rgba(0,0,0,.45)", filter: `blur(${12 * u}px)`, transform: "rotate(45deg)", transformOrigin: "0 50%" }} />
        {/* The handle, down and to the right. */}
        <svg width={D} height={D} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          <defs>
            <linearGradient id={`mgf${uid}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#4a4f57" />
              <stop offset="40%" stopColor="#d9dde2" />
              <stop offset="100%" stopColor="#3a3e44" />
            </linearGradient>
            <linearGradient id={`mgh${uid}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#3a2418" />
              <stop offset="35%" stopColor="#6d4630" />
              <stop offset="100%" stopColor="#1f130c" />
            </linearGradient>
          </defs>
          <g transform={`translate(${D / 2} ${D / 2}) rotate(45)`}>
            <rect x={RL + RIM - 6 * u} y={-19 * u} width={52 * u} height={38 * u} rx={5 * u} fill={`url(#mgf${uid})`} />
            <rect x={RL + RIM + 42 * u} y={-23 * u} width={210 * u} height={46 * u} rx={23 * u} fill={`url(#mgh${uid})`} />
            <rect x={RL + RIM + 56 * u} y={-17 * u} width={180 * u} height={6 * u} rx={3 * u} fill="rgba(255,255,255,.14)" />
          </g>
        </svg>
        {/* The glass: the photo enlarged about the point, an inner shade and a glare. */}
        <div style={{ position: "absolute", left: RIM, top: RIM, width: 2 * RL, height: 2 * RL, borderRadius: "50%", overflow: "hidden",
          background: "#111" }}>
          <div style={{ position: "absolute", left: imgL, top: imgT, width: W * sc, height: H * sc }}>
            <Photo src={src} style={{ filter: "contrast(1.08) saturate(1.06)" }} />
          </div>
          <div style={{ position: "absolute", inset: 0, borderRadius: "50%",
            background: "radial-gradient(circle, rgba(0,0,0,0) 72%, rgba(0,0,0,.34) 100%)" }} />
          <div style={{ position: "absolute", inset: 0, borderRadius: "50%",
            background: "linear-gradient(138deg, rgba(255,255,255,.26) 0%, rgba(255,255,255,.08) 26%, rgba(255,255,255,0) 44%)" }} />
        </div>
        {/* The rim. */}
        <svg width={D} height={D} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          <defs>
            <linearGradient id={`mgr${uid}`} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#9aa1a9" />
              <stop offset="22%" stopColor="#2b2f35" />
              <stop offset="50%" stopColor="#15181c" />
              <stop offset="78%" stopColor="#3b4047" />
              <stop offset="100%" stopColor="#8d949c" />
            </linearGradient>
          </defs>
          <circle cx={D / 2} cy={D / 2} r={rim} fill="none" stroke={`url(#mgr${uid})`} strokeWidth={RIM} />
          <circle cx={D / 2} cy={D / 2} r={RL + 0.8 * u} fill="none" stroke="rgba(255,255,255,.4)" strokeWidth={1.4 * u} />
          <circle cx={D / 2} cy={D / 2} r={RL + RIM - 0.8 * u} fill="none" stroke="rgba(0,0,0,.55)" strokeWidth={1.4 * u} />
          <path d={`M ${D / 2 - Math.cos(0.5) * rim} ${D / 2 - Math.sin(0.5) * rim} A ${rim} ${rim} 0 0 1 ${D / 2 - Math.cos(1.25) * rim} ${D / 2 - Math.sin(1.25) * rim}`}
            fill="none" stroke="rgba(255,255,255,.55)" strokeWidth={3 * u} strokeLinecap="round" />
        </svg>
      </div>
      {hasLabel ? (
        <LabelBox spot={{ x0: 0, y0: 0, w: box.w, h: box.h, css, origin, S: { x: 0, y: 0 }, dir: { x: 0, y: 0 } }}
          ls={title.ls} size={title.size} k={k} p={pop} out={q} sub={sub} subSize={26 * k} />
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== pe-red-arrow
// The bold label pops at 4; the red marker arrow sweeps out of it 9 -> 21 and its head flicks open on the
// point at 21 (sfx_at 16, the swipe); the camera pushes in about the point the whole time (it stays put).
const RedArrow: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const q = useOut();
  const src = photoOf(overlay);
  if (!src) return null;
  const [ax, ay] = anchorOf(overlay, 0.6, 0.42, 0.1, 0.9);
  const T = { x: ax * W, y: ay * H };
  const R = Math.max(24 * k, Math.min(240 * k, anchorR(overlay, 0.06) * Math.min(W, H)));
  const push = interpolate(frame, [0, Math.max(1, dur)], [0, 1], { ...clamp, easing: drift });
  const title = fitCaps(cap(overlay.text), 640 * k, [68 * k, 62 * k, 56 * k, 50 * k], 2);
  const sub = str(overlay.subtitle).slice(0, 60);
  const subSize = 30 * k;
  const box = labelSize(title.ls, title.size, k, sub, subSize);
  const spot = placeLabel(T, R, box.w || 1, box.h || 1, W, H, k, box.w ? 240 : 300);
  // No label: the arrow still comes from a point clear of the thing, inside the safe area.
  const S = box.w ? spot.S : { x: spot.x0, y: spot.y0 };
  const E = shortOf(T, S, R + 14 * k);
  const seed = hashStr(src) % 97;
  const pts = arrowPts(S, E, W, 0.22, seed);
  const draw = ramp(frame, 9, 12, PEN);
  const head = ramp(frame, 21, 5);
  const erase = ramp(frame, dur - 15, 10, expoIn);
  const pop = ramp(frame, 4, 13, backOut);
  return (
    <AbsoluteFill style={{ background: "#000", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${(1 + 0.12 * push).toFixed(4)})`, transformOrigin: `${T.x.toFixed(1)}px ${T.y.toFixed(1)}px` }}>
        <Photo src={src} style={{ filter: "contrast(1.05) saturate(.96)" }} />
      </AbsoluteFill>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 50%, rgba(0,0,0,0) 52%, rgba(0,0,0,.42) 100%)" }} />
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        <HandArrow pts={pts} draw={draw} head={head} erase={erase} width={19 * k} k={k} seed={seed} />
      </svg>
      {box.w ? <LabelBox spot={spot} ls={title.ls} size={title.size} k={k} p={pop} out={q} sub={sub} subSize={subSize} /> : null}
    </AbsoluteFill>
  );
};

// ================================================================== registry
export const LOOKS: Record<string, Look> = {
  "pe-zoom-circle": ZoomCircle,
  "pe-highlight-box": HighlightBox,
  "pe-focus-pull": FocusPull,
  "pe-split-panels": SplitPanels,
  "pe-frame-drop": FrameDrop,
  "pe-parallax": Parallax,
  "pe-newsprint": Newsprint,
  "pe-punch-in": PunchIn,
  "pe-duotone": Duotone,
  "pe-light-sweep": LightSweep,
  "pe-polaroid-pan": PolaroidPan,
  "pe-case-file": CaseFile,
  "pe-circle-spotlight": CircleSpotlight,
  "pe-magnify": Magnify,
  "pe-red-arrow": RedArrow,
};
