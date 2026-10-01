import React from "react";
import { AbsoluteFill, Easing, Img, continueRender, delayRender, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { ANTON, ANTON_CAP, HAND, LABEL, SERIF, SERIF_ITALIC, SUBLINE } from "../fonts";
import type { Overlay, OverlayItem, SceneMedia } from "../../types";
import { ramp, useK } from "../pro/ProGraphics";
import { BODY, FLICK, markerPath, poly } from "./LibVideoMarks";

/**
 * Photo looks, pro set (family "px-"): what a documentary editor does with
 * the story's stills (overlay.media; a clip lends its thumbnail), each look a
 * full frame of its own with one clear move, a hit frame the planner times
 * to the spoken word (registry sfxAt), a caption that reads on any picture
 * and a clean exit. This file holds the family's shared pieces, the
 * cinematic / editorial reveals and the paper looks; LibPhotosPro2.tsx the
 * archive and several-picture looks.
 *
 *   px-aperture-iris     a camera iris of eight metal blades opens on the photo, closes it at the end
 *   px-slit-reveal       a line of light splits into a widening band that opens on the photo
 *   px-color-bloom       the photo in black and white, its colour blooming out from the point
 *   px-diagonal-slices   five slanted slices slide in along their own edges and close into one picture
 *   px-level-line        water rises over the photo to a level, a dashed waterline and its tag lock on
 *   px-detail-inset      a box draws round a detail and an enlarged inset slides out of it on two leaders
 *   px-viewfinder        a rangefinder's split image focuses, the shutter blinks, the photo is taken
 *   px-torn-strips       the print torn in three strips that slide in from alternate sides, torn seams showing
 *   px-folded-print      a print folded in three opens out in 3D, its creases left in the paper
 *   px-field-journal     the print taped into a field notebook, the name handwritten beside it, an arrow to it
 *   px-magazine-spread   the photo across a glossy magazine spread under its headline, a sheen crossing it
 *   px-postcard          a postcard slides in on its stamped, postmarked back and flips over to the picture
 *
 * Props: text (the title: a place, a thing), label (a kicker or a date),
 * subtitle (a second line), items (dates for the several-picture looks),
 * anchor {x, y[, r]} (the point a mark, a bloom or a waterline uses; frame
 * share as src/anchors.py gives it, the photo cover-cropped to the frame).
 * Pictures are never stretched: full-frame photos are cover-cropped (a
 * portrait photo over a blurred fill when no anchor pins the crop), prints
 * take the photo's own shape. Text is Anton for the line that carries it and
 * Inter Tight caps for the small lines, white with one accent, over a soft
 * scrim, inside the safe margins.
 */

export type Look = React.FC<{ overlay: Overlay; accent: string }>;
export type CSS = React.CSSProperties;
export type Pt = { x: number; y: number };

// ------------------------------------------------------------------ motion
export const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
export const EXPO_OUT = Easing.bezier(0.16, 1, 0.3, 1);
export const EXPO_IN = Easing.bezier(0.7, 0, 0.84, 0);
export const IN_OUT = Easing.bezier(0.65, 0, 0.35, 1);
export const DRIFT = Easing.bezier(0.33, 0, 0.45, 1);
export const BACK_OUT = Easing.bezier(0.34, 1.32, 0.64, 1);
export const clamp01 = (v: number): number => (!Number.isFinite(v) ? 0 : v < 0 ? 0 : v > 1 ? 1 : v);
export const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;
export { ramp };

/** 0 while the look holds, easing to 1 over its last `frames` frames. */
export const useOut = (frames = 12): number => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return ramp(frame, Math.max(0, durationInFrames - frames - 1), frames, EXPO_IN);
};

/** 0 -> 1 across the whole look on a gentle curve (camera moves). */
export const useLife = (ease = DRIFT): number => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return interpolate(frame, [0, Math.max(1, durationInFrames)], [0, 1], { ...clamp, easing: ease });
};

/** Deterministic 0..1 noise of a number (no Math.random anywhere). */
export const hash01 = (n: number): number => {
  const x = Math.sin(n * 127.1 + 311.7) * 43758.5453123;
  return x - Math.floor(x);
};
export const hashStr = (s: string): number => {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619) >>> 0;
  return h;
};
export const uidOf = (id: string): string => id.replace(/[^A-Za-z0-9]/g, "");

// ------------------------------------------------------------------ words
/** Any planner field as clean text (numbers kept, anything else dropped), so .trim() never throws. */
export const str = (v: unknown): string =>
  (typeof v === "string" ? v : typeof v === "number" && Number.isFinite(v) ? String(v) : "")
    .replace(/[‘’]/g, "'").replace(/[“”]/g, "\"").replace(/\s+/g, " ").trim();

const SMALL_TAIL = /[\s,;:\-–—·]+(?:the|a|an|of|in|at|on|and|or|to|for|by|with|from)?$/i;
/** At most n characters, cut at a word, never ending on a dangling small word or a comma. */
export const cut = (s: string, n: number): string => {
  if (s.length <= n) return s;
  let c = s.slice(0, n).replace(/\s+\S*$/, "").trim();
  for (let i = 0; i < 4 && SMALL_TAIL.test(c); i++) c = c.replace(SMALL_TAIL, "").trim();
  return c || s.slice(0, n);
};
export const caps = (v: unknown, max = 60): string => cut(str(v).toUpperCase(), max);

const SMALL_WORDS = new Set(["of", "the", "and", "in", "at", "on", "a", "an", "to", "for", "by", "from", "de", "la"]);
/** "LAKE POWELL" -> "Lake Powell" (the planner sends some names in caps). */
export const titleCase = (s: string): string =>
  s.toLowerCase().split(" ").map((w, i) => (i > 0 && SMALL_WORDS.has(w) ? w : w.replace(/(^|[-'(/])([a-z])/g,
    (_m, a: string, b: string) => a + b.toUpperCase()))).join(" ");
/** A name as typed or written by hand: caps turned to title case, anything else as given. */
export const asWritten = (v: unknown, max = 48): string => {
  const s = str(v);
  const t = /[A-Z]/.test(s) && s === s.toUpperCase() ? titleCase(s) : s;
  return cut(t, max);
};
export const listOf = <T,>(v: T[] | null | undefined): T[] => (Array.isArray(v) ? v : []);
export const itemsOf = (ov: Overlay): OverlayItem[] => listOf(ov.items).filter((i) => i && typeof i === "object");
/** A year said in a string ("1955", "the 1950s"), else "". */
export const yearIn = (s: string): string => {
  const m = /\b(1[6-9]\d0s|20[0-2]0s|1[6-9]\d\d|20\d\d)\b/.exec(s);
  return m ? m[1] : "";
};

// Anton's advance widths (em), as measured for the bold-text looks (LibPackPlaces).
const ADV: Record<string, number> = {
  A: 0.485, B: 0.479, C: 0.474, D: 0.493, E: 0.412, F: 0.399, G: 0.485, H: 0.499, I: 0.227, J: 0.466, K: 0.472,
  L: 0.397, M: 0.746, N: 0.498, O: 0.486, P: 0.472, Q: 0.494, R: 0.477, S: 0.461, T: 0.396, U: 0.474, V: 0.469,
  W: 0.712, X: 0.484, Y: 0.446, Z: 0.41, "0": 0.494, "1": 0.331, "2": 0.494, "3": 0.494, "4": 0.494, "5": 0.494,
  "6": 0.494, "7": 0.494, "8": 0.494, "9": 0.494, " ": 0.234, ".": 0.229, ",": 0.236, ":": 0.242, "%": 1.057,
  "$": 0.462, "°": 0.389, "-": 0.311, "–": 0.311, "—": 0.563, "·": 0.234, "'": 0.214, "&": 0.52, "/": 0.405,
  "+": 0.355, "(": 0.291, ")": 0.291, "?": 0.492, "!": 0.229, "#": 0.546, "@": 0.8,
};
export const ANTON_TRACK = 0.012;
export const antonEm = (s: string): number => Array.from(s).reduce((a, c) => a + (ADV[c] ?? 0.48) + ANTON_TRACK, 0);
/** Inter Tight 700 caps, roughly (em), with `track` em of letter spacing. */
export const subEm = (s: string, track = 0.16): number =>
  Array.from(s).reduce((a, c) => a + (c === " " ? 0.24 : /[0-9]/.test(c) ? 0.56 : /[MW@]/.test(c) ? 0.86
    : /[IJ1.,:'·|]/.test(c) ? 0.3 : 0.64) + track, 0);

const wrapBy = (text: string, room: number, width: (s: string) => number): string[] => {
  const out: string[] = [];
  let cur = "";
  for (const w of text.split(" ").filter(Boolean)) {
    const next = cur ? `${cur} ${w}` : w;
    if (cur && width(next) > room) {
      out.push(cur);
      cur = w;
    } else cur = next;
  }
  if (cur) out.push(cur);
  return out;
};

/**
 * Anton caps in at most `maxLines` lines `room` px wide: the largest cap
 * height from `cap` down to `minCap` (px at 1080p, times k) that fits, the
 * lines balanced; past that, the last line ends in an ellipsis.
 */
export const fitAnton = (text: string, cap: number, minCap: number, room: number, k: number, maxLines = 2):
  { size: number; lines: string[] } => {
  const t = str(text);
  if (!t) return { size: (minCap / ANTON_CAP) * k, lines: [] };
  for (let c = cap; c >= minCap - 0.01; c -= 2) {
    const size = (c / ANTON_CAP) * k;
    const ls = wrapBy(t, room, (s) => antonEm(s) * size);
    if (ls.length <= maxLines && ls.every((l) => antonEm(l) * size <= room + 0.5)) {
      if (ls.length < 2) return { size, lines: ls };
      let best = ls;
      for (let r = room * 0.96; r > room * 0.45; r *= 0.96) {
        const b = wrapBy(t, r, (s) => antonEm(s) * size);
        if (b.length !== ls.length || !b.every((l) => antonEm(l) * size <= r + 0.5)) break;
        best = b;
      }
      return { size, lines: best };
    }
  }
  const size = (minCap / ANTON_CAP) * k;
  let ls = wrapBy(t, room, (s) => antonEm(s) * size);
  if (ls.length > maxLines) {
    ls = ls.slice(0, maxLines);
    let l = ls[maxLines - 1];
    while (l.length > 1 && antonEm(`${l}…`) * size > room) l = l.slice(0, -1).trimEnd();
    ls[maxLines - 1] = `${l}…`;
  }
  return { size: Math.min(size, ...ls.map((l) => (room / Math.max(0.3, antonEm(l))))), lines: ls };
};

// ------------------------------------------------------------------ pictures
/** The picture of a media entry: an image's url, a clip's thumbnail (non-strings dropped). */
export const stillOf = (m: SceneMedia | null | undefined): string => {
  if (!m || typeof m !== "object") return "";
  const u: unknown = m.type === "image" ? m.url : m.thumbnail;
  return typeof u === "string" ? u.trim() : "";
};
/** Up to `max` different stills of the overlay (its media; the renderer fills them, never an empty slot). */
export const photosOf = (ov: Overlay, max: number): string[] => {
  const out: string[] = [];
  for (const m of listOf(ov.media)) {
    const s = stillOf(m);
    if (s && !out.includes(s)) out.push(s);
    if (out.length >= max) break;
  }
  return out;
};
export const photoOf = (ov: Overlay): string => photosOf(ov, 1)[0] || "";

// A picture's own shape (width / height) and pixel width, read once per picture per page.
export type PhotoInfo = { ar: number; w: number };
const INFO = new Map<string, PhotoInfo>();
const LOADING = new Map<string, Promise<PhotoInfo>>();
const loadInfo = (src: string, fallback: number): Promise<PhotoInfo> => {
  const got = LOADING.get(src);
  if (got) return got;
  const p = new Promise<PhotoInfo>((resolve) => {
    const img = new Image();
    let done = false;
    const finish = (v: PhotoInfo) => {
      if (done) return;
      done = true;
      INFO.set(src, v);
      resolve(v);
    };
    // A picture that never answers draws in the look's usual shape rather than holding the render.
    const timer = setTimeout(() => finish({ ar: fallback, w: 0 }), 12000);
    img.onload = () => {
      clearTimeout(timer);
      const ok = img.naturalWidth > 0 && img.naturalHeight > 0;
      finish({ ar: ok ? img.naturalWidth / img.naturalHeight : fallback, w: ok ? img.naturalWidth : 0 });
    };
    img.onerror = () => {
      clearTimeout(timer);
      finish({ ar: fallback, w: 0 });
    };
    img.src = src;
  });
  LOADING.set(src, p);
  return p;
};

/**
 * The picture's own shape and pixel width (w 0 while unknown): the render
 * waits for them; the editor's preview starts at `fallback` and updates.
 */
export const usePhotoInfo = (src: string, fallback = 1.5): PhotoInfo => {
  const [info, setInfo] = React.useState<PhotoInfo | null>(() => (src ? INFO.get(src) ?? null : null));
  const [handle] = React.useState(() => (src && !INFO.has(src) ? delayRender(`photo shape ${src.slice(-60)}`) : null));
  React.useEffect(() => {
    let live = true;
    if (!src) {
      if (handle !== null) continueRender(handle);
      return;
    }
    const known = INFO.get(src);
    if (known) {
      setInfo(known);
      if (handle !== null) continueRender(handle);
      return;
    }
    loadInfo(src, fallback).then((v) => {
      if (live) setInfo(v);
      if (handle !== null) continueRender(handle);
    });
    return () => {
      live = false;
    };
  }, [src, fallback, handle]);
  return info && info.ar > 0 ? info : { ar: fallback, w: 0 };
};
/** The picture's own width / height. */
export const useAspect = (src: string, fallback = 1.5): number => usePhotoInfo(src, fallback).ar;
/** How far a look may push into a picture before it softens (a clip's 320 px thumbnail barely at all). */
export const zoomRoom = (w: number, most: number): number => (w > 0 ? Math.max(1.12, Math.min(most, w / 980)) : most);

/** A print's shape for a picture: the usual paper shapes, never the picture stretched. */
export const printAspect = (ar: number): number =>
  ar >= 1.62 ? 16 / 10 : ar >= 1.42 ? 3 / 2 : ar >= 1.18 ? 4 / 3 : ar >= 0.9 ? 1 : ar >= 0.72 ? 3 / 4 : 2 / 3;

/** A picture cover-cropped to its box (never stretched), held about `pos`. */
export const Cover: React.FC<{ src: string; pos?: string; style?: CSS }> = ({ src, pos = "50% 50%", style }) => (
  <Img src={src} style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "100%", objectFit: "cover",
    objectPosition: pos, ...style }} />
);

/**
 * A photo filling the frame: cover-cropped, or - a portrait or square photo
 * nothing pins to the frame - whole over a blurred, darkened copy of itself
 * (cover-cropping a portrait to 16:9 would cut its top and bottom away).
 */
export const FullPhoto: React.FC<{ src: string; ar: number; filter?: string; pinned?: boolean; pos?: string }> =
  ({ src, ar, filter, pinned, pos = "50% 50%" }) => {
    const { width: W, height: H } = useVideoConfig();
    if (pinned || ar >= 1.25) return <Cover src={src} pos={pos} style={{ filter }} />;
    const h = H, w = Math.min(W, h * ar);
    return (
      <>
        <Cover src={src} style={{ filter: `blur(${(W / 48).toFixed(1)}px) brightness(.42) saturate(.8)`, transform: "scale(1.12)" }} />
        <div style={{ position: "absolute", left: (W - w) / 2, top: 0, width: w, height: h, overflow: "hidden",
          boxShadow: `0 0 ${W / 24}px rgba(0,0,0,.55)` }}>
          <Cover src={src} style={{ filter }} />
        </div>
      </>
    );
  };

/** overlay.anchor as a point in 0..1 of the frame (clamped to [lo, hi]), else (fx, fy). */
export const anchorOf = (ov: Overlay, fx: number, fy: number, lo = 0.08, hi = 0.92): Pt => {
  const a = ov.anchor as { x?: unknown; y?: unknown } | undefined;
  const x = Number(a?.x), y = Number(a?.y);
  const cl = (v: number) => Math.min(hi, Math.max(lo, v));
  return a && Number.isFinite(x) && Number.isFinite(y) ? { x: cl(x), y: cl(y) } : { x: fx, y: fy };
};
export const hasAnchor = (ov: Overlay): boolean => {
  const a = ov.anchor as { x?: unknown; y?: unknown } | undefined;
  return Boolean(a && Number.isFinite(Number(a.x)) && Number.isFinite(Number(a.y)));
};
/** overlay.anchor.r (the thing's radius, 0..0.5 of the frame's shorter side) when given, else `def`. */
export const anchorR = (ov: Overlay, def: number): number => {
  const a = ov.anchor as { r?: unknown } | undefined;
  const r = Number(a?.r);
  return Number.isFinite(r) && r > 0 ? Math.min(0.5, r) : def;
};

// ------------------------------------------------------------------ surfaces
/** Film grain: animated fractal noise at half resolution, overlaid. */
export const Grain: React.FC<{ opacity?: number; every?: number }> = ({ opacity = 0.1, every = 2 }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const id = `pxGrain${uidOf(React.useId())}`;
  return (
    <svg width={width / 2} height={height / 2} style={{ position: "absolute", left: 0, top: 0, transform: "scale(2)",
      transformOrigin: "0 0", opacity, mixBlendMode: "overlay", pointerEvents: "none" }}>
      <filter id={id} x="0" y="0" width="100%" height="100%">
        <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves={2} seed={Math.floor(frame / every) % 16} stitchTiles="stitch" />
        <feColorMatrix type="saturate" values="0" />
      </filter>
      <rect width={width / 2} height={height / 2} filter={`url(#${id})`} />
    </svg>
  );
};

/** Paper fibre: a still fractal texture multiplied over a surface (w x h px), tinted `rgb` (0..1 each). */
export const PaperGrain: React.FC<{ w: number; h: number; seed?: number; opacity?: number; freq?: number;
  rgb?: [number, number, number]; style?: CSS }> = ({ w, h, seed = 3, opacity = 0.22, freq = 0.8, rgb = [0.45, 0.38, 0.28], style }) => {
  const id = `pxPaper${uidOf(React.useId())}`;
  return (
    <svg width={w} height={h} style={{ position: "absolute", left: 0, top: 0, opacity, mixBlendMode: "multiply",
      pointerEvents: "none", ...style }}>
      <filter id={id} x="0" y="0" width="100%" height="100%">
        <feTurbulence type="fractalNoise" baseFrequency={freq} numOctaves={3} seed={seed} stitchTiles="stitch" />
        <feColorMatrix type="matrix" values={`0 0 0 0 ${rgb[0]}  0 0 0 0 ${rgb[1]}  0 0 0 0 ${rgb[2]}  0 0 0 1.15 -.38`} />
      </filter>
      <rect width={w} height={h} filter={`url(#${id})`} />
    </svg>
  );
};

/** A soft dark pool rising from the lower left so a caption reads on any picture. */
export const CaptionShade: React.FC<{ show: boolean; strength?: number; side?: "left" | "right" }> =
  ({ show, strength = 0.72, side = "left" }) => (show ? (
    <AbsoluteFill style={{ background: `linear-gradient(${side === "left" ? 18 : -18}deg, rgba(0,0,0,${strength}) 0%, `
      + `rgba(0,0,0,${(strength * 0.42).toFixed(3)}) 30%, rgba(0,0,0,0) 56%)` }} />
  ) : null);
export const hasCaption = (ov: Overlay): boolean => Boolean(str(ov.text) || str(ov.label) || str(ov.subtitle));

// ------------------------------------------------------------------ the caption
export const SHADOW = "0 2px 3px rgba(0,0,0,.35), 0 4px 22px rgba(0,0,0,.55)";
const SUB_TRACK = 0.16;

/** A line sliding up out of its mask at `at`, and back down as `q` goes to 1. */
export const Rise: React.FC<{ at: number; q: number; children: React.ReactNode; style?: CSS; frames?: number }> =
  ({ at, q, children, style, frames = 14 }) => {
    const frame = useCurrentFrame();
    const p = ramp(frame, at, frames);
    return (
      <div style={{ overflow: "hidden", paddingBottom: "0.16em", marginBottom: "-0.16em", ...style }}>
        <div style={{ transform: `translateY(${((1 - p) * 115 + q * 115).toFixed(2)}%)`, opacity: p > 0.002 ? 1 : 0 }}>{children}</div>
      </div>
    );
  };

/**
 * The family's caption, always in the same place (lower left inside the safe
 * margin): the kicker (overlay.label) in small tracked caps in the accent,
 * the title (overlay.text) in Anton caps, the subtitle in Inter Tight; each
 * line rises out of its mask, and drops back at the exit.
 */
export const PxCaption: React.FC<{ ov: Overlay; at: number; q: number; accent: string; left?: number; bottom?: number;
  room?: number; cap?: number; minCap?: number; kicker?: string | null; title?: string | null; sub?: string | null;
  align?: "left" | "center" }> = ({ ov, at, q, accent, left = 112, bottom = 112, room = 1120, cap = 50, minCap = 36,
  kicker, title, sub, align = "left" }) => {
  const k = useK();
  const { width: W } = useVideoConfig();
  const kick = kicker === null ? "" : caps(kicker ?? ov.label, 44);
  const head = fitAnton(caps(title === null ? "" : title ?? ov.text, 80), cap, minCap, room * k, k, 2);
  const line = sub === null ? "" : cut(str(sub ?? ov.subtitle), 70);
  if (!kick && !head.lines.length && !line) return null;
  const subPx = 25 * k;
  const pos: CSS = align === "center" ? { left: 0, width: W, alignItems: "center" } : { left: left * k, alignItems: "flex-start" };
  return (
    <div style={{ position: "absolute", bottom: bottom * k, display: "flex", flexDirection: "column", ...pos }}>
      {kick ? (
        <Rise at={at} q={q} style={{ marginBottom: 10 * k }}>
          <div style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: 23 * k, letterSpacing: `${SUB_TRACK + 0.06}em`,
            color: accent, whiteSpace: "nowrap", textShadow: SHADOW }}>{kick}</div>
        </Rise>
      ) : null}
      {head.lines.map((ln, i) => (
        <Rise key={i} at={at + 2 + i * 3} q={q}>
          <div style={{ fontFamily: ANTON, fontSize: head.size, lineHeight: 1.04, letterSpacing: `${ANTON_TRACK}em`,
            color: "#fff", whiteSpace: "nowrap", textShadow: SHADOW, textAlign: align }}>{ln}</div>
        </Rise>
      ))}
      {line ? (
        <Rise at={at + 6 + head.lines.length * 3} q={q} style={{ marginTop: 10 * k }}>
          <div style={{ fontFamily: SUBLINE, fontWeight: 600, fontSize: subPx, letterSpacing: "0.02em",
            color: "rgba(255,255,255,.9)", whiteSpace: "nowrap", textShadow: SHADOW }}>{line}</div>
        </Rise>
      ) : null}
    </div>
  );
};

// ================================================================== px-aperture-iris
/**
 * The blades of an eight-blade iris whose opening has inradius r (px) about
 * the frame's centre: each blade's visible face runs from one side of the
 * opening out between its own trailing edge and the next blade's, so the
 * blades tile everything outside the opening, turning as it opens.
 */
const IrisBlades: React.FC<{ r: number; turn: number; W: number; H: number; k: number; id: string }> = ({ r, turn, W, H, k, id }) => {
  const N = 8;
  const cx = W / 2, cy = H / 2;
  const L = Math.hypot(W, H) * 1.4;
  const a = r * Math.tan(Math.PI / N);
  const f = (x: number, y: number) => `${x.toFixed(1)} ${y.toFixed(1)}`;
  const blades: React.ReactNode[] = [];
  const edges: React.ReactNode[] = [];
  const clips: React.ReactNode[] = [];
  const sides: string[] = [];
  for (let i = 0; i < N; i++) {
    const p = turn + (i * 2 * Math.PI) / N;
    const p2 = turn + ((i + 1) * 2 * Math.PI) / N;
    const ux = Math.cos(p), uy = Math.sin(p), tx = -uy, ty = ux;
    const u2x = Math.cos(p2), u2y = Math.sin(p2);
    const ax = cx + r * ux - a * tx, ay = cy + r * uy - a * ty;
    const bx = cx + r * ux + a * tx, by = cy + r * uy + a * ty;
    // The trailing edges bow a little, as a real blade's curved edge does.
    const bow = (sx: number, sy: number, dx: number, dy: number) => {
      const mx = sx + dx * L * 0.5 + -dy * L * 0.06, my = sy + dy * L * 0.5 + dx * L * 0.06;
      return { mx, my, ex: sx + dx * L, ey: sy + dy * L };
    };
    const e1 = bow(ax, ay, ux, uy);
    const e2 = bow(bx, by, u2x, u2y);
    const d = `M${f(ax, ay)} L${f(bx, by)} Q${f(e2.mx, e2.my)} ${f(e2.ex, e2.ey)} L${f(e1.ex, e1.ey)} Q${f(e1.mx, e1.my)} ${f(ax, ay)} Z`;
    const shade = i % 2 ? 0.05 : 0;
    blades.push(<path key={i} d={d} fill={`url(#${id}g)`} />);
    if (shade) blades.push(<path key={`s${i}`} d={d} fill={`rgba(255,255,255,${shade})`} />);
    // A soft sheen across each blade, as satin-black metal catches a light from the upper left.
    blades.push(<path key={`l${i}`} d={d} fill={`url(#${id}s)`} opacity={0.5 + 0.5 * Math.cos(p + 2.3)} />);
    // The next blade's edge lies over this one: its shadow, a dark lip and a fine highlight.
    const edge = `M${f(bx, by)} Q${f(e2.mx, e2.my)} ${f(e2.ex, e2.ey)}`;
    clips.push(<clipPath key={i} id={`${id}c${i}`}><path d={d} /></clipPath>);
    edges.push(
      <g key={`d${i}`} clipPath={`url(#${id}c${i})`}>
        <path d={edge} fill="none" stroke="rgba(0,0,0,.55)" strokeWidth={22 * k} filter={`url(#${id}e)`} />
      </g>,
    );
    edges.push(<path key={`e${i}`} d={edge} fill="none" stroke="rgba(0,0,0,.7)" strokeWidth={4 * k} />);
    edges.push(<path key={`h${i}`} d={edge} fill="none" stroke="rgba(255,255,255,.12)" strokeWidth={1.4 * k}
      transform={`translate(${(-1.8 * k).toFixed(2)} ${(-0.6 * k).toFixed(2)})`} />);
    sides.push(`${i ? "L" : "M"}${f(ax, ay)}`);
  }
  const opening = `${sides.join(" ")} Z`;
  return (
    <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
      <defs>
        <radialGradient id={`${id}g`} cx={cx} cy={cy} r={Math.max(W, H) * 0.75} gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#3a3c42" />
          <stop offset="28%" stopColor="#25272b" />
          <stop offset="100%" stopColor="#0c0d0f" />
        </radialGradient>
        <linearGradient id={`${id}s`} x1="0" y1="0" x2={W} y2={H} gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="rgba(255,255,255,.07)" />
          <stop offset="45%" stopColor="rgba(255,255,255,0)" />
          <stop offset="100%" stopColor="rgba(0,0,0,.18)" />
        </linearGradient>
        <filter id={`${id}b`} x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation={16 * k} />
        </filter>
        <filter id={`${id}e`} x="-10%" y="-10%" width="120%" height="120%">
          <feGaussianBlur stdDeviation={7 * k} />
        </filter>
        {clips}
      </defs>
      {/* The blades' shadow falling into the opening. */}
      {r > 1 ? <path d={opening} fill="none" stroke="rgba(0,0,0,.75)" strokeWidth={46 * k} filter={`url(#${id}b)`} /> : null}
      {blades}
      {edges}
      {/* The bevel of each blade's inner edge catching the light. */}
      {r > 1 ? <path d={opening} fill="none" stroke="rgba(255,255,255,.2)" strokeWidth={1.6 * k} /> : null}
    </svg>
  );
};

// The closed iris holds for 3 frames, opens over 3 -> 17 (sfx_at 6, the shutter: a quick start, a long
// settle); the photo settles and sharpens under it; the caption rises from 16. At the end the iris closes on
// the picture over the last 11 frames.
const IRIS_OPEN = Easing.bezier(0.45, 0.05, 0.15, 1);
const ApertureIris: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const q = useOut(10);
  const life = useLife();
  const id = `pxIris${uidOf(React.useId())}`;
  const src = photoOf(overlay);
  const ar = useAspect(src);
  if (!src) return null;
  const R = (Math.hypot(W, H) / 2) / Math.cos(Math.PI / 8) + 12 * k;
  const open = ramp(frame, 3, 14, IRIS_OPEN);
  const close = ramp(frame, dur - 12, 11, IN_OUT);
  const r = R * open * (1 - close);
  const turn = -0.3 - 0.62 * (1 - open) + 0.5 * close;
  const settle = ramp(frame, 3, 22, EXPO_OUT);
  const flash = interpolate(frame, [4, 7, 18], [0, 0.22, 0], clamp);
  const cap_ = hasCaption(overlay);
  return (
    <AbsoluteFill style={{ background: "#000", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${((1.1 - 0.1 * settle) * (1 + 0.045 * life)).toFixed(4)})`,
        filter: `blur(${(5 * k * (1 - settle)).toFixed(2)}px) brightness(${(0.62 + 0.38 * settle).toFixed(3)})` }}>
        <FullPhoto src={src} ar={ar} filter="contrast(1.04) saturate(.98)" />
      </AbsoluteFill>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 50%, rgba(255,236,206,1) 0%, rgba(255,236,206,0) 70%)",
        opacity: flash, mixBlendMode: "screen" }} />
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 50%, rgba(0,0,0,0) 52%, rgba(0,0,0,.42) 100%)" }} />
      <CaptionShade show={cap_} strength={0.62} />
      <PxCaption ov={overlay} at={16} q={q} accent={accent} />
      {r < R - 1 ? <IrisBlades r={r} turn={turn} W={W} H={H} k={k} id={id} /> : null}
    </AbsoluteFill>
  );
};

// ================================================================== px-slit-reveal
// A line of light grows from the centre over 1 -> 10, splits at 10 (sfx_at 10) into a band that opens on
// the photo by 25; the caption rises from 20. At the exit the band closes to the line over the footage.
const SlitReveal: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const q = useOut(12);
  const life = useLife();
  const src = photoOf(overlay);
  const ar = useAspect(src);
  if (!src) return null;
  const grow = ramp(frame, 1, 9, IN_OUT);
  const open = ramp(frame, 10, 15, EXPO_OUT);
  const shut = ramp(frame, dur - 13, 11, IN_OUT);
  const gone = ramp(frame, dur - 4, 3);
  const h = H * open * (1 - shut);
  const top = (H - h) / 2;
  const lineW = W * grow;
  const edge = (1 - ramp(frame, 14, 12)) * (frame >= 10 ? 1 : 0) + shut * (1 - gone);
  const line = frame < 10 ? 1 : 0;
  const settle = ramp(frame, 10, 24, EXPO_OUT);
  const cap_ = hasCaption(overlay);
  const glow = `0 0 ${10 * k}px rgba(255,244,226,.95), 0 0 ${34 * k}px rgba(255,226,186,.55)`;
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{ background: "#000", opacity: 1 - shut }} />
      <div style={{ position: "absolute", left: 0, top, width: W, height: h, overflow: "hidden" }}>
        <div style={{ position: "absolute", left: 0, top: -top, width: W, height: H,
          transform: `scale(${((1.07 - 0.07 * settle) * (1 + 0.04 * life)).toFixed(4)})` }}>
          <FullPhoto src={src} ar={ar} filter={`contrast(1.05) brightness(${(0.8 + 0.2 * settle).toFixed(3)})`} />
          <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 50%, rgba(0,0,0,0) 55%, rgba(0,0,0,.38) 100%)" }} />
          <CaptionShade show={cap_} strength={0.62} />
          <PxCaption ov={overlay} at={20} q={q} accent={accent} />
        </div>
      </div>
      {/* The line, then the band's two lit edges. */}
      {line ? (
        <>
          <div style={{ position: "absolute", left: (W - lineW) / 2, top: H / 2 - 1.5 * k, width: lineW, height: 3 * k,
            background: "linear-gradient(90deg, rgba(255,240,220,0), #fff 18%, #fff 82%, rgba(255,240,220,0))", boxShadow: glow }} />
          <div style={{ position: "absolute", left: W / 2 - 520 * k, top: H / 2 - 60 * k, width: 1040 * k, height: 120 * k,
            background: "radial-gradient(ellipse at 50% 50%, rgba(255,232,200,.34) 0%, rgba(255,232,200,0) 70%)",
            opacity: grow, mixBlendMode: "screen" }} />
        </>
      ) : null}
      {edge > 0.01 && h > 0 ? (
        [top, top + h].map((y, i) => (
          <div key={i} style={{ position: "absolute", left: 0, top: y - 1.5 * k, width: W, height: 3 * k, opacity: edge,
            background: "linear-gradient(90deg, rgba(255,240,220,0), rgba(255,250,240,.95) 20%, rgba(255,250,240,.95) 80%, rgba(255,240,220,0))",
            boxShadow: glow }} />
        ))
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== px-color-bloom
// The photo sits in black and white; from frame 4 its colour blooms out of the point (anchor, else the
// upper middle), half way at ~18 (sfx_at 18, a shimmer), the whole frame by 34; the caption rises from 22.
const ColorBloom: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H } = useVideoConfig();
  const k = useK();
  const q = useOut(12);
  const life = useLife();
  const src = photoOf(overlay);
  const ar = useAspect(src);
  if (!src) return null;
  const pinned = hasAnchor(overlay);
  const A = anchorOf(overlay, 0.5, 0.44, 0.1, 0.9);
  const ax = A.x * W, ay = A.y * H;
  const far = Math.max(Math.hypot(ax, ay), Math.hypot(W - ax, ay), Math.hypot(ax, H - ay), Math.hypot(W - ax, H - ay));
  const feather = 240 * k;
  const p = ramp(frame, 4, 30, IN_OUT);
  const R = ((far + feather) / 0.82) * p;
  // The colour spreads like a wash, not a circle: a core and nine lobes round it, each feathered,
  // turning slowly as they grow (their union is the mask).
  const seed = hashStr(src) % 97;
  const blob = (x: number, y: number, r: number, f: number) =>
    `radial-gradient(circle at ${x.toFixed(1)}px ${y.toFixed(1)}px, #000 ${Math.max(0, r - f).toFixed(1)}px, rgba(0,0,0,0) ${Math.max(0.1, r).toFixed(1)}px)`;
  const lobes = Array.from({ length: 9 }, (_, i) => {
    const th = (i / 9) * Math.PI * 2 + seed * 0.37 + 0.35 * p;
    const d = R * (0.55 + 0.18 * hash01(seed + i * 7));
    const rr = R * (0.36 + 0.2 * hash01(seed + i * 13));
    return blob(ax + Math.cos(th) * d, ay + Math.sin(th) * d * 0.8, rr, Math.min(rr, feather * 0.8));
  });
  const mask = [blob(ax, ay, R * 0.82, feather), ...lobes].join(", ");
  const s = (1 + 0.06 * life).toFixed(4);
  const origin = `${ax.toFixed(1)}px ${ay.toFixed(1)}px`;
  const cap_ = hasCaption(overlay);
  return (
    <AbsoluteFill style={{ background: "#000", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${s})`, transformOrigin: origin }}>
        <FullPhoto src={src} ar={ar} pinned={pinned} filter="grayscale(1) contrast(1.08) brightness(.9)" />
      </AbsoluteFill>
      {p > 0.001 ? (
        <AbsoluteFill style={{ transform: `scale(${s})`, transformOrigin: origin, WebkitMaskImage: mask, maskImage: mask }}>
          <FullPhoto src={src} ar={ar} pinned={pinned} filter="contrast(1.04) saturate(1.12)" />
        </AbsoluteFill>
      ) : null}
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 50%, rgba(0,0,0,0) 55%, rgba(0,0,0,.4) 100%)" }} />
      <CaptionShade show={cap_} strength={0.6} />
      <PxCaption ov={overlay} at={22} q={q} accent={accent} />
    </AbsoluteFill>
  );
};

// ================================================================== px-diagonal-slices
// Five slanted slices slide in along their own edges, from above and below in turn (0 -> ~24, the first
// landing at ~10: sfx_at 10), the gaps close 18 -> 30; the caption rises from 26. At the exit the slices
// slide out the other way over the footage.
const DiagonalSlices: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const q = useOut(12);
  const life = useLife();
  const src = photoOf(overlay);
  const ar = useAspect(src);
  if (!src) return null;
  const N = 5;
  const s = H * Math.tan((17 * Math.PI) / 180);
  const step = (W + s) / N;
  const len = Math.hypot(s, H);
  const dx = -s / len, dy = H / len;              // down along a slice
  const merge = ramp(frame, 18, 12, IN_OUT);
  const gap = 22 * k * (1 - merge);
  const leave = (i: number) => ramp(frame, dur - 13 + (i % 2), 11, EXPO_IN);
  const fade = ramp(frame, dur - 12, 11, Easing.linear);
  const cap_ = hasCaption(overlay);
  const scale = (0.95 + 0.05 * merge) * (1 + 0.05 * life);
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 45%, #1a1d24 0%, #0b0d12 70%)", opacity: 1 - fade }} />
      <AbsoluteFill style={{ transform: `scale(${scale.toFixed(4)})` }}>
        {Array.from({ length: N }, (_, i) => {
          const t0 = i * step, t1 = (i + 1) * step;
          const clip = `polygon(${t0.toFixed(1)}px 0px, ${(t1 + 0.6).toFixed(1)}px 0px, ${(t1 - s + 0.6).toFixed(1)}px ${H}px, ${(t0 - s).toFixed(1)}px ${H}px)`;
          const fromTop = i % 2 === 0;
          const e = ramp(frame, i * 3, 17, EXPO_OUT);
          const out = leave(i);
          const travel = (len + 40 * k) * ((1 - e) * (fromTop ? -1 : 1) + out * (fromTop ? 1 : -1));
          const ox = dx * travel + (i - (N - 1) / 2) * gap;
          const oy = dy * travel;
          return (
            <div key={i} style={{ position: "absolute", inset: 0, transform: `translate(${ox.toFixed(2)}px, ${oy.toFixed(2)}px)`,
              filter: merge < 0.999 ? `drop-shadow(0 ${14 * k}px ${26 * k}px rgba(0,0,0,${(0.55 * (1 - merge)).toFixed(3)}))` : undefined }}>
              <div style={{ position: "absolute", inset: 0, clipPath: clip }}>
                <FullPhoto src={src} ar={ar} filter={`brightness(${(0.8 + 0.2 * e).toFixed(3)}) contrast(1.04)`} />
              </div>
            </div>
          );
        })}
      </AbsoluteFill>
      <div style={{ position: "absolute", inset: 0, opacity: 1 - fade }}>
        <CaptionShade show={cap_} strength={0.6} />
      </div>
      <PxCaption ov={overlay} at={26} q={q} accent={accent} />
    </AbsoluteFill>
  );
};

// ================================================================== px-level-line
/** The engineers' water-level mark: an inverted triangle over two short lines. */
const LevelMark: React.FC<{ size: number; color: string }> = ({ size, color }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" style={{ overflow: "visible" }}>
    <path d="M3 4 H21 L12 15 Z" fill="none" stroke={color} strokeWidth={2.6} strokeLinejoin="round" />
    <path d="M6 19 H18 M9 23 H15" stroke={color} strokeWidth={2.6} strokeLinecap="round" />
  </svg>
);

// Water rises from the bottom to the level over 2 -> 26 (sfx_at 24); the dashed waterline draws 24 -> 38
// and its tag rises from 28; from max(44, end - 40) the water drains away, leaving the line.
const LevelLine: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const q = useOut(12);
  const life = useLife();
  const id = `pxLvl${uidOf(React.useId())}`;
  const src = photoOf(overlay);
  const ar = useAspect(src);
  if (!src) return null;
  const pinned = hasAnchor(overlay);
  const A = anchorOf(overlay, 0.5, 0.4, 0.16, 0.8);
  const level = A.y * H;
  const rise = ramp(frame, 2, 24, IN_OUT);
  const drainAt = Math.max(44, Math.min(96, dur - 40));
  const drain = ramp(frame, drainAt, 24, IN_OUT);
  const surface = lerp(H + 24 * k, level, rise * (1 - drain));
  const wet = rise > 0.002 && surface < H + 20 * k;
  const draw = ramp(frame, 24, 14, IN_OUT);
  const t = frame / 30;
  const wave = (x: number) => Math.sin(x / (160 * k) + t * 2.4) * 2.6 * k + Math.sin(x / (61 * k) - t * 3.1) * 1.1 * k;
  const pts: string[] = [];
  for (let x = 0; x <= W; x += 24 * k) pts.push(`${x.toFixed(1)} ${(surface + wave(x)).toFixed(1)}`);
  const surfaceD = `M${pts.join(" L")}`;
  const title = caps(overlay.label || overlay.text, 40);
  const sub = caps(overlay.label ? overlay.subtitle || overlay.text : overlay.subtitle, 44);
  const head = fitAnton(title, 40, 30, 700 * k, k, 1);
  const tagIn = 28;
  const M = 112 * k;
  const above = level > 240 * k;
  return (
    <AbsoluteFill style={{ background: "#000", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${(1.015 + 0.04 * life).toFixed(4)})` }}>
        <FullPhoto src={src} ar={ar} pinned={pinned} filter="contrast(1.05) brightness(.92) saturate(.94)" />
      </AbsoluteFill>
      {wet ? (
        <>
          {/* The water: a deep body under a lit surface, long ripples drifting on it; the rock still reads through. */}
          <div style={{ position: "absolute", left: 0, top: surface, width: W, height: Math.max(0, H - surface + 30 * k),
            background: "linear-gradient(180deg, rgba(40,118,150,.7) 0%, rgba(22,84,116,.8) 45%, rgba(10,50,74,.88) 100%)",
            mixBlendMode: "multiply" }} />
          <div style={{ position: "absolute", left: 0, top: surface, width: W, height: Math.max(0, H - surface + 30 * k),
            background: "linear-gradient(180deg, rgba(34,104,138,.3) 0%, rgba(16,66,96,.38) 100%)" }} />
          <svg width={W} height={Math.max(1, H - surface + 30 * k)} style={{ position: "absolute", left: 0, top: surface,
            mixBlendMode: "screen", opacity: 0.3 }}>
            <filter id={`${id}r`} x="0" y="0" width="100%" height="100%">
              <feTurbulence type="fractalNoise" baseFrequency={`${(0.003 / k).toFixed(5)} ${(0.09 / k).toFixed(5)}`} numOctaves={2}
                seed={7 + Math.floor(frame / 3) % 5} />
              <feColorMatrix type="matrix" values="0 0 0 0 .62  0 0 0 0 .82  0 0 0 0 .92  0 0 0 1.7 -.95" />
            </filter>
            <rect width={W} height={H} filter={`url(#${id}r)`} />
          </svg>
          <div style={{ position: "absolute", left: 0, top: surface, width: W, height: 260 * k,
            background: "linear-gradient(180deg, rgba(170,220,250,.34) 0px, rgba(150,210,245,.1) 70px, rgba(150,210,245,0) 260px)",
            mixBlendMode: "screen" }} />
          <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
            <defs>
              <filter id={`${id}g`} x="-5%" y="-50%" width="110%" height="200%"><feGaussianBlur stdDeviation={3 * k} /></filter>
            </defs>
            <path d={surfaceD} fill="none" stroke="rgba(214,238,255,.75)" strokeWidth={6 * k} filter={`url(#${id}g)`} />
            <path d={surfaceD} fill="none" stroke="rgba(240,250,255,.95)" strokeWidth={2 * k} />
          </svg>
        </>
      ) : null}
      {/* The waterline: dashed, white over a dark edge, drawn left to right. */}
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, opacity: 1 - q }}>
        <defs>
          <clipPath id={`${id}c`}><rect x={0} y={0} width={W * draw} height={H} /></clipPath>
        </defs>
        <g clipPath={`url(#${id}c)`}>
          <line x1={0} y1={level} x2={W} y2={level} stroke="rgba(0,0,0,.6)" strokeWidth={9 * k} strokeDasharray={`${28 * k} ${16 * k}`} />
          <line x1={0} y1={level} x2={W} y2={level} stroke="#fff" strokeWidth={4.4 * k} strokeDasharray={`${28 * k} ${16 * k}`} />
        </g>
      </svg>
      {head.lines.length ? (
        <>
          <div style={{ position: "absolute", right: 0, top: level - 210 * k, width: 900 * k, height: 420 * k, opacity: draw * (1 - q),
            background: "radial-gradient(ellipse at 78% 50%, rgba(0,0,0,.5) 0%, rgba(0,0,0,0) 62%)" }} />
          <div style={{ position: "absolute", right: M, ...(above ? { bottom: H - level + 18 * k } : { top: level + 22 * k }),
            display: "flex", flexDirection: "column", alignItems: "flex-end" }}>
            <Rise at={tagIn} q={q}>
              <div style={{ display: "flex", alignItems: "center", gap: 16 * k }}>
                <div style={{ filter: "drop-shadow(0 2px 6px rgba(0,0,0,.6))", marginTop: 4 * k }}>
                  <LevelMark size={34 * k} color={accent} />
                </div>
                <div style={{ fontFamily: ANTON, fontSize: head.size, lineHeight: 1.04, letterSpacing: `${ANTON_TRACK}em`, color: "#fff",
                  whiteSpace: "nowrap", textShadow: SHADOW }}>{head.lines[0]}</div>
              </div>
            </Rise>
            {sub ? (
              <Rise at={tagIn + 5} q={q} style={{ marginTop: 6 * k }}>
                <div style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: 24 * k, letterSpacing: `${SUB_TRACK}em`,
                  color: "rgba(255,255,255,.92)", whiteSpace: "nowrap", textShadow: SHADOW }}>{sub}</div>
              </Rise>
            ) : null}
          </div>
        </>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== px-detail-inset
// The picture dims as a white box draws round the detail (4 -> 14); an enlarged inset slides out of the box
// to the open side on two leader lines (12 -> 24, sfx_at 20); its label rises from 24. At the exit the
// inset folds back into the box.
const DetailInset: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const q = useOut(12);
  const life = useLife();
  const src = photoOf(overlay);
  const ar = useAspect(src);
  if (!src) return null;
  const pinned = hasAnchor(overlay);
  const A = anchorOf(overlay, 0.58, 0.5, 0.06, 0.94);
  // The detail box (16:9, like the inset), sized by the thing's radius, inside the frame.
  const bw = Math.max(200 * k, Math.min(480 * k, anchorR(overlay, 0.09) * H * 2.8));
  const bh = (bw * 9) / 16;
  const m0 = 40 * k;
  const bx = Math.max(m0, Math.min(W - m0 - bw, A.x * W - bw / 2));
  const by = Math.max(m0, Math.min(H - m0 - bh, A.y * H - bh / 2));
  // The inset in the other half of the frame, toward the open space above or below the detail, so the
  // two leaders run long and clear.
  const right = bx + bw / 2 < W / 2;
  const iw = 0.38 * W, ih = (iw * 9) / 16;
  const M = 112 * k;
  // The label sits inside the inset, low left over a soft shade: the leaders can never cross it.
  const pad = 26 * k;
  const title = fitAnton(caps(overlay.text, 50), 32, 26, iw - 2 * pad, k, 1);
  const sub = caps(overlay.subtitle || overlay.label, 48);
  const labelled = title.lines.length > 0 || Boolean(sub);
  const ix = right ? W - M - iw : M;
  const cy = by + bh / 2;
  const iyTop = 96 * k, iyLow = H - 112 * k - ih;
  const iy = cy > H * 0.56 ? iyTop : cy < H * 0.44 ? iyLow : Math.max(iyTop, Math.min(iyLow, cy - ih / 2));
  const s = 1 + 0.035 * life;
  // The box as drawn on screen moves with the push about the centre.
  const sx = W / 2 + (bx - W / 2) * s, sy = H / 2 + (by - H / 2) * s, sw = bw * s, sh = bh * s;
  const box = ramp(frame, 4, 10, IN_OUT);
  const out = ramp(frame, dur - 13, 10, EXPO_IN);
  const grow = ramp(frame, 12, 13, EXPO_OUT) * (1 - out);
  const dim = ramp(frame, 5, 12) * (1 - ramp(frame, dur - 8, 7));
  const R = { x: lerp(sx, ix, grow), y: lerp(sy, iy, grow), w: lerp(sw, iw, grow), h: lerp(sh, ih, grow) };
  const m = R.w / sw;
  const boxLen = 2 * (sw + sh);
  // The leaders join matching corners on the outside of the pair: beside each other, the facing edges'
  // corners; one above the other, the far corners (they never cross either rectangle).
  const c = (x: number, y: number, w: number, h: number, i: number) => ({ x: x + (i % 2) * w, y: y + Math.floor(i / 2) * h });
  const up = iy + ih < sy, down = iy > sy + sh;
  const pairs: [number, number][] = up || down
    ? (right === up ? [[0, 0], [3, 3]] : [[1, 1], [2, 2]])
    : right ? [[1, 0], [3, 2]] : [[0, 1], [2, 3]];
  const [ptsA, ptsB] = pairs.map(([a, b]) => [c(sx, sy, sw, sh, a), c(R.x, R.y, R.w, R.h, b)]);
  const photo = (
    <div style={{ position: "absolute", left: 0, top: 0, width: W, height: H, transform: `scale(${s.toFixed(4)})` }}>
      <FullPhoto src={src} ar={ar} pinned={pinned} filter="contrast(1.05)" />
    </div>
  );
  return (
    <AbsoluteFill style={{ background: "#000", overflow: "hidden" }}>
      {photo}
      <div style={{ position: "absolute", left: sx, top: sy, width: sw, height: sh,
        boxShadow: `0 0 0 ${3000 * k}px rgba(0,0,0,${(0.5 * dim).toFixed(3)})` }} />
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        {grow > 0.01 ? [ptsA, ptsB].map((p, i) => (
          <g key={i}>
            <line x1={p[0].x} y1={p[0].y} x2={p[1].x} y2={p[1].y} stroke="rgba(0,0,0,.45)" strokeWidth={4.5 * k} />
            <line x1={p[0].x} y1={p[0].y} x2={p[1].x} y2={p[1].y} stroke="rgba(255,255,255,.85)" strokeWidth={2 * k} />
          </g>
        )) : null}
        <rect x={sx} y={sy} width={sw} height={sh} fill="none" stroke="rgba(0,0,0,.5)" strokeWidth={6 * k}
          strokeDasharray={`${boxLen * box} ${boxLen}`} />
        <rect x={sx} y={sy} width={sw} height={sh} fill="none" stroke="#fff" strokeWidth={3 * k}
          strokeDasharray={`${boxLen * box} ${boxLen}`} />
      </svg>
      {grow > 0.004 ? (
        <div style={{ position: "absolute", left: R.x, top: R.y, width: R.w, height: R.h, overflow: "hidden", background: "#111",
          boxShadow: `0 0 0 ${3.5 * k}px #fff, 0 ${22 * k}px ${60 * k}px rgba(0,0,0,.65)` }}>
          <div style={{ position: "absolute", left: -m * sx, top: -m * sy, width: W, height: H,
            transform: `scale(${m.toFixed(5)})`, transformOrigin: "0 0" }}>
            {photo}
          </div>
          {labelled ? (
            <>
              <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: "56%", opacity: ramp(frame, 20, 10) * (1 - out),
                background: "linear-gradient(0deg, rgba(0,0,0,.72) 0%, rgba(0,0,0,.3) 55%, rgba(0,0,0,0) 100%)" }} />
              <div style={{ position: "absolute", left: pad, bottom: pad * 0.8, display: "flex", flexDirection: "column" }}>
                {sub ? (
                  <Rise at={24} q={Math.max(q, out)} style={{ marginBottom: 6 * k }}>
                    <div style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: 20 * k, letterSpacing: `${SUB_TRACK + 0.04}em`,
                      color: accent, whiteSpace: "nowrap", textShadow: SHADOW }}>{sub}</div>
                  </Rise>
                ) : null}
                {title.lines.length ? (
                  <Rise at={26} q={Math.max(q, out)}>
                    <div style={{ fontFamily: ANTON, fontSize: title.size, lineHeight: 1.04, letterSpacing: `${ANTON_TRACK}em`,
                      color: "#fff", whiteSpace: "nowrap", textShadow: SHADOW }}>{title.lines[0]}</div>
                  </Rise>
                ) : null}
              </div>
            </>
          ) : null}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== px-viewfinder
// Through a rangefinder's window the split image comes together 3 -> 16; the shutter blinks on 18-19
// (sfx_at 18) and the photo is there, full frame, under a soft flash; the caption rises from 24.
const Viewfinder: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H } = useVideoConfig();
  const k = useK();
  const q = useOut(12);
  const life = useLife();
  const src = photoOf(overlay);
  const ar = useAspect(src);
  if (!src) return null;
  const SHOT = 18;
  const focus = ramp(frame, 3, 13, IN_OUT);
  const taken = frame >= SHOT + 2;
  const blink = frame >= SHOT && frame < SHOT + 2;
  const cap_ = hasCaption(overlay);
  if (blink) return <AbsoluteFill style={{ background: "#000" }} />;
  if (taken) {
    const settle = ramp(frame, SHOT + 2, 16, EXPO_OUT);
    const flash = interpolate(frame, [SHOT + 2, SHOT + 9], [0.38, 0], clamp);
    return (
      <AbsoluteFill style={{ background: "#000", overflow: "hidden" }}>
        <AbsoluteFill style={{ transform: `scale(${((1.035 - 0.035 * settle) * (1 + 0.04 * life)).toFixed(4)})` }}>
          <FullPhoto src={src} ar={ar} filter="contrast(1.05)" />
        </AbsoluteFill>
        <AbsoluteFill style={{ background: "#fff", opacity: flash }} />
        <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 50%, rgba(0,0,0,0) 55%, rgba(0,0,0,.38) 100%)" }} />
        <CaptionShade show={cap_} strength={0.6} />
        <PxCaption ov={overlay} at={24} q={q} accent={accent} />
      </AbsoluteFill>
    );
  }
  // The finder: a rounded window in the black, the frame lines, the split-image circle in the middle.
  const fx = 150 * k, fy = 104 * k, fw = W - 2 * fx, fh = H - 2 * fy;
  const cr = 100 * k;
  const off = 44 * k * (1 - focus);
  const soft = 3 * k * (1 - focus);
  const view = (dx: number) => (
    <div style={{ position: "absolute", left: dx, top: 0, width: W, height: H, transform: "scale(1.06)" }}>
      <FullPhoto src={src} ar={ar} filter={`brightness(.84) contrast(.98) saturate(.86) blur(${soft.toFixed(2)}px)`} />
    </div>
  );
  const corner = 74 * k, lx = fx + 70 * k, ly = fy + 56 * k, lw = fw - 140 * k, lh = fh - 112 * k;
  const brackets = [[lx, ly, 1, 1], [lx + lw, ly, -1, 1], [lx, ly + lh, 1, -1], [lx + lw, ly + lh, -1, -1]]
    .map(([x, y, a, b]) => `M${x + a * corner} ${y} L${x} ${y} L${x} ${y + b * corner}`).join(" ");
  const appear = ramp(frame, 0, 5);
  return (
    <AbsoluteFill style={{ background: "#000", overflow: "hidden" }}>
      <div style={{ position: "absolute", left: fx, top: fy, width: fw, height: fh, borderRadius: 30 * k, overflow: "hidden",
        opacity: appear }}>
        <div style={{ position: "absolute", left: -fx, top: -fy, width: W, height: H }}>
          {view(0)}
          {/* The split image: the top half and the bottom half of the circle shifted apart until in focus. */}
          <div style={{ position: "absolute", left: W / 2 - cr, top: H / 2 - cr, width: 2 * cr, height: cr, overflow: "hidden",
            borderRadius: `${cr}px ${cr}px 0 0` }}>
            <div style={{ position: "absolute", left: -(W / 2 - cr), top: -(H / 2 - cr), width: W, height: H }}>{view(off)}</div>
          </div>
          <div style={{ position: "absolute", left: W / 2 - cr, top: H / 2, width: 2 * cr, height: cr, overflow: "hidden",
            borderRadius: `0 0 ${cr}px ${cr}px` }}>
            <div style={{ position: "absolute", left: -(W / 2 - cr), top: -H / 2, width: W, height: H }}>{view(-off)}</div>
          </div>
        </div>
        <div style={{ position: "absolute", inset: 0, borderRadius: 30 * k, boxShadow: `inset 0 0 ${90 * k}px rgba(0,0,0,.75)` }} />
      </div>
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, opacity: appear }}>
        <path d={brackets} fill="none" stroke="rgba(255,250,235,.85)" strokeWidth={3 * k} strokeLinecap="square"
          style={{ filter: `drop-shadow(0 0 ${5 * k}px rgba(255,240,210,.6))` }} />
        <circle cx={W / 2} cy={H / 2} r={cr} fill="none" stroke="rgba(0,0,0,.45)" strokeWidth={4 * k} />
        <circle cx={W / 2} cy={H / 2} r={cr} fill="none" stroke="rgba(255,255,255,.78)" strokeWidth={1.8 * k} />
        <line x1={W / 2 - cr} y1={H / 2} x2={W / 2 + cr} y2={H / 2} stroke="rgba(255,255,255,.34)" strokeWidth={1.2 * k} />
        <circle cx={W / 2} cy={H / 2} r={cr + 40 * k} fill="none" stroke="rgba(255,255,255,.22)" strokeWidth={1.2 * k} />
      </svg>
    </AbsoluteFill>
  );
};

// ================================================================== paper
/** A photo filling a w x h box: cover-cropped, or a portrait whole over a blurred copy of itself. */
export const FillPhoto: React.FC<{ src: string; ar: number; w: number; h: number; filter?: string; pos?: string }> =
  ({ src, ar, w, h, filter, pos = "50% 45%" }) => {
    const box = w / Math.max(1, h);
    if (ar >= box * 0.72) return <Cover src={src} pos={pos} style={{ filter }} />;
    const iw = Math.min(w, h * ar);
    return (
      <>
        <Cover src={src} style={{ filter: `blur(${(w / 50).toFixed(1)}px) brightness(.5) saturate(.8)`, transform: "scale(1.12)" }} />
        <div style={{ position: "absolute", left: (w - iw) / 2, top: 0, width: iw, height: h, overflow: "hidden" }}>
          <Cover src={src} style={{ filter }} />
        </div>
      </>
    );
  };

/** Smooth 1-D value noise in -0.5..0.5: random values every `every` steps, eased between. */
export const smoothNoise = (i: number, every: number, seed: number): number => {
  const a = Math.floor(i / every), f = i / every - a;
  const s = f * f * (3 - 2 * f);
  return lerp(hash01(seed * 17.3 + a * 3.71), hash01(seed * 17.3 + (a + 1) * 3.71), s) - 0.5;
};

/** A torn edge across x0..x1 about y: a slow wander, smaller bumps and the fibres' fine grain (deterministic). */
export const tornEdge = (x0: number, x1: number, y: number, amp: number, seed: number, step: number): Pt[] => {
  const n = Math.max(2, Math.ceil((x1 - x0) / Math.max(1, step)));
  const out: Pt[] = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n;
    const slow = Math.sin(t * 5.3 + seed) * 0.5 + Math.sin(t * 11.7 + seed * 1.9) * 0.28 + Math.sin(t * 2.2 + seed * 0.7) * 0.42;
    const bumps = smoothNoise(i, 4, seed) * 0.9 + smoothNoise(i, 1.7, seed + 5) * 0.45;
    const grain = (hash01(seed * 131 + i * 7.13) - 0.5) * 0.12;
    out.push({ x: x0 + (x1 - x0) * t, y: y + amp * (slow * 0.72 + bumps * 0.42 + grain) });
  }
  return out;
};
const polyCss = (pts: Pt[]): string => `polygon(${pts.map((p) => `${p.x.toFixed(1)}px ${p.y.toFixed(1)}px`).join(", ")})`;

/** A strip of masking tape, w x h px about (x, y), turned rot degrees, its ends torn. */
export const Tape: React.FC<{ x: number; y: number; w: number; h: number; rot: number; seed: number; k: number; p?: number }> =
  ({ x, y, w, h, rot, seed, k, p = 1 }) => {
    if (p <= 0.001) return null;
    const teeth = 7;
    const pts: string[] = ["2% 0%", "98% 0%"];
    for (let i = 1; i < teeth; i++) pts.push(`${(100 - 5 * hash01(seed + i)).toFixed(1)}% ${((i / teeth) * 100).toFixed(1)}%`);
    pts.push("98% 100%", "2% 100%");
    for (let i = teeth - 1; i > 0; i--) pts.push(`${(5 * hash01(seed + 40 + i)).toFixed(1)}% ${((i / teeth) * 100).toFixed(1)}%`);
    const s = 1.22 - 0.22 * p;
    return (
      <div style={{ position: "absolute", left: x - w / 2, top: y - h / 2, width: w, height: h, opacity: clamp01(p * 2.5),
        transform: `rotate(${rot}deg) scale(${s.toFixed(4)})`, filter: `drop-shadow(0 ${1.5 * k}px ${2.5 * k}px rgba(0,0,0,.28))` }}>
        <div style={{ position: "absolute", inset: 0, clipPath: `polygon(${pts.join(", ")})`,
          background: "linear-gradient(178deg, rgba(243,236,214,.9) 0%, rgba(230,220,194,.86) 100%)" }}>
          <div style={{ position: "absolute", inset: 0, backgroundImage: `repeating-linear-gradient(90deg, rgba(255,255,255,.12) 0px, `
            + `rgba(255,255,255,.12) ${1.2 * k}px, rgba(0,0,0,0) ${1.2 * k}px, rgba(0,0,0,0) ${4 * k}px)` }} />
        </div>
      </div>
    );
  };

/** Handwriting: each letter inked left to right under a soft clip wipe, from `at`, `step` frames apart. */
export const Handwrite: React.FC<{ text: string; at: number; step: number; style: CSS }> = ({ text, at, step, style }) => {
  const frame = useCurrentFrame();
  return (
    <div style={{ whiteSpace: "pre", lineHeight: 1.12, ...style }}>
      {Array.from(text).map((c, i) => {
        const p = ramp(frame, at + i * step, 6, Easing.linear);
        return (
          <span key={i} style={{ display: "inline-block", opacity: p > 0.01 ? 1 : 0,
            clipPath: p >= 0.999 ? undefined : `inset(-40% ${((1 - p) * 125 - 25).toFixed(1)}% -40% 0)` }}>{c}</span>
        );
      })}
    </div>
  );
};
/** Lines of handwriting `room` px wide at `px` (Caveat, about 0.42 em a letter), balanced (no lone last word). */
const handLines = (text: string, room: number, px: number, max: number): string[] => {
  const width = (s: string) => s.length * px * 0.42;
  const ls = wrapBy(text, room, width);
  if (ls.length > max) {
    const out = ls.slice(0, max);
    out[max - 1] = `${cut(out[max - 1], Math.max(4, out[max - 1].length - 1))}…`;
    return out;
  }
  let best = ls;
  for (let r = room * 0.96; ls.length > 1 && r > room * 0.4; r *= 0.96) {
    const b = wrapBy(text, r, width);
    if (b.length !== ls.length) break;
    best = b;
  }
  return best;
};

const DESK = "radial-gradient(ellipse at 46% 38%, #3b3128 0%, #231c16 52%, #0d0a08 100%)";
const DeskGrain: React.FC<{ k: number }> = ({ k }) => (
  <AbsoluteFill style={{ backgroundImage: `repeating-linear-gradient(91deg, rgba(255,235,210,.022) 0px, rgba(255,235,210,.022) ${2 * k}px, `
    + `rgba(0,0,0,0) ${2 * k}px, rgba(0,0,0,0) ${12 * k}px)` }} />
);

// ================================================================== px-torn-strips
// The print, torn into three strips, slides in from alternate sides (0 -> 23, the strips landing at 15, 19
// and 23; sfx_at 19); the torn seams stay open a little; the caption rises from 24. At the exit the strips
// slide out the way they came, over the footage.
const TornStrips: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const q = useOut(12);
  const life = useLife();
  const src = photoOf(overlay);
  const ar = useAspect(src);
  if (!src) return null;
  const seed = hashStr(src) % 97;
  const PW = 1720 * k, PH = (PW * 9) / 16;
  const px0 = (W - PW) / 2, py0 = (H - PH) / 2 - 4 * k;
  const cuts = [PH * (0.34 + 0.04 * (hash01(seed) - 0.5)), PH * (0.67 + 0.04 * (hash01(seed + 3) - 0.5))];
  const tears = cuts.map((y, i) => tornEdge(-12 * k, PW + 12 * k, y, 24 * k, seed + i * 17, 7 * k));
  // The white of the paper showing along a tear: wider and narrower in soft runs, never a saw.
  const rim = (pts: Pt[], dir: number, s: number) => pts.map((p, j) => ({ x: p.x,
    y: p.y + dir * (6 + 9 * (smoothNoise(j, 5, s) + 0.5) + 2 * smoothNoise(j, 1.5, s + 3)) * k }));
  const flat = (y: number): Pt[] => [{ x: -12 * k, y }, { x: PW + 12 * k, y }];
  const fade = ramp(frame, dur - 12, 11, Easing.linear);
  const cap_ = hasCaption(overlay);
  const strips = [0, 1, 2].map((i) => {
    const top = i === 0 ? flat(0) : tears[i - 1];
    const bot = i === 2 ? flat(PH) : tears[i];
    const photoPts = [...top, ...[...bot].reverse()];
    const paperPts = [...(i === 0 ? top : rim(top, -1, seed + i)), ...[...(i === 2 ? bot : rim(bot, 1, seed + i * 9))].reverse()];
    const from = i % 2 ? 1 : -1;
    const e = ramp(frame, i * 4, 15, EXPO_OUT);
    const o = ramp(frame, dur - 13 + i, 11, EXPO_IN);
    const dx = from * W * 0.95 * (1 - e) - from * W * 1.05 * o + [-7, 10, -5][i] * k;
    const dy = [-7, 0, 7][i] * k;
    const rot = from * 3.5 * (1 - e) + [-0.35, 0.25, -0.2][i] - from * 2 * o;
    return (
      <div key={i} style={{ position: "absolute", left: px0, top: py0, width: PW, height: PH,
        transform: `translate(${dx.toFixed(2)}px, ${dy.toFixed(2)}px) rotate(${rot.toFixed(3)}deg)`,
        filter: `drop-shadow(0 ${10 * k}px ${16 * k}px rgba(0,0,0,.5))` }}>
        <div style={{ position: "absolute", inset: 0, clipPath: polyCss(paperPts), background: "#f1ede4" }} />
        <div style={{ position: "absolute", inset: 0, clipPath: polyCss(photoPts), overflow: "hidden" }}>
          <FillPhoto src={src} ar={ar} w={PW} h={PH} filter="contrast(1.05) saturate(.96)" />
          <div style={{ position: "absolute", inset: 0, background: `linear-gradient(180deg, rgba(255,255,255,.05) 0%, rgba(0,0,0,0) 40%, rgba(0,0,0,.1) 100%)` }} />
        </div>
      </div>
    );
  });
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 45%, #2a2622 0%, #151311 60%, #0a0908 100%)", opacity: 1 - fade }} />
      <AbsoluteFill style={{ transform: `scale(${(1 + 0.045 * life).toFixed(4)})` }}>{strips}</AbsoluteFill>
      <div style={{ position: "absolute", inset: 0, opacity: 1 - fade }}>
        <CaptionShade show={cap_} strength={0.55} />
      </div>
      <PxCaption ov={overlay} at={24} q={q} accent={accent} />
    </AbsoluteFill>
  );
};

// ================================================================== px-folded-print
// The folded print rises in (0 -> 12); its front panel opens out toward the viewer (5 -> 19) and the back
// one from behind (9 -> 23; sfx_at 18, the paper's turn); it lies open by 23 with its creases; the caption
// rises from 24; the camera leans in.
const UNFOLD = Easing.bezier(0.5, 0, 0.18, 1);
const FoldedPrint: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width: W } = useVideoConfig();
  const k = useK();
  const q = useOut(12);
  const life = useLife();
  const src = photoOf(overlay);
  const ar = useAspect(src);
  if (!src) return null;
  const pa = ar >= 1 ? Math.max(4 / 3, Math.min(16 / 9, ar)) : printAspect(ar);
  let SW = 1440 * k, SH = SW / pa;
  if (SH > 770 * k) {
    SH = 770 * k;
    SW = SH * pa;
  }
  const cx = W / 2, cy = 468 * k;
  const P = SW / 3;
  const appear = ramp(frame, 0, 12, EXPO_OUT);
  const uL = ramp(frame, 5, 14, UNFOLD), uR = ramp(frame, 9, 14, UNFOLD);
  const thL = 172 * (1 - uL) + 2.2 * uL;       // the left panel folds over the front
  const thR = 174 * (1 - uR) - 2.2 * uR;       // the right panel folds behind
  // How dark a panel turned th degrees from the viewer looks (edge-on darkest), and its sheen.
  const dark = (th: number) => 0.62 * Math.pow(Math.sin(((Math.abs(th) % 180) * Math.PI) / 180), 1.4);
  const sheen = (th: number) => Math.max(0, Math.cos(((Math.abs(th) - 32) * Math.PI) / 52)) * (Math.abs(th) < 80 ? 1 : 0);
  const paperBack = "linear-gradient(160deg, #f4f1ea 0%, #e8e3d8 100%)";
  const face = (i: number, th: number) => (
    <>
      <div style={{ position: "absolute", inset: 0, overflow: "hidden", backfaceVisibility: "hidden" }}>
        <div style={{ position: "absolute", left: -i * P, top: 0, width: SW, height: SH }}>
          <FillPhoto src={src} ar={ar} w={SW} h={SH} filter="contrast(1.05) saturate(.97)" />
        </div>
        <div style={{ position: "absolute", inset: 0, background: `rgba(0,0,0,${dark(th).toFixed(3)})` }} />
        <div style={{ position: "absolute", inset: 0, opacity: 0.35 * sheen(th),
          background: "linear-gradient(105deg, rgba(255,255,255,0) 20%, rgba(255,255,255,.55) 50%, rgba(255,255,255,0) 80%)" }} />
        {/* The crease left in the paper at the hinge. */}
        {i !== 1 ? (
          <div style={{ position: "absolute", top: 0, bottom: 0, [i === 0 ? "right" : "left"]: 0, width: 30 * k,
            background: `linear-gradient(${i === 0 ? 270 : 90}deg, rgba(0,0,0,.3) 0%, rgba(0,0,0,0) 100%)` } as CSS} />
        ) : (
          <>
            <div style={{ position: "absolute", top: 0, bottom: 0, left: 0, width: 22 * k, background: "linear-gradient(90deg, rgba(255,255,255,.2) 0%, rgba(255,255,255,0) 100%)" }} />
            <div style={{ position: "absolute", top: 0, bottom: 0, right: 0, width: 22 * k, background: "linear-gradient(270deg, rgba(0,0,0,.24) 0%, rgba(0,0,0,0) 100%)" }} />
          </>
        )}
      </div>
      <div style={{ position: "absolute", inset: 0, background: paperBack, backfaceVisibility: "hidden", transform: "rotateY(180deg)" }}>
        <div style={{ position: "absolute", inset: 0, background: `rgba(0,0,0,${(dark(th) * 0.8).toFixed(3)})` }} />
      </div>
    </>
  );
  const panel = (i: number, th: number, origin: string) => (
    <div key={i} style={{ position: "absolute", left: i * P, top: 0, width: P + 0.5, height: SH, transformStyle: "preserve-3d",
      transformOrigin: origin, transform: `rotateY(${th.toFixed(3)}deg)` }}>
      {face(i, th)}
    </div>
  );
  const shadowSpread = (1 - appear) * 30 + 30;
  return (
    <AbsoluteFill style={{ background: DESK, overflow: "hidden" }}>
      <DeskGrain k={k} />
      <AbsoluteFill style={{ transform: `scale(${(1 + 0.05 * life).toFixed(4)})`, transformOrigin: `50% ${((cy / (1080 * k)) * 100).toFixed(1)}%` }}>
        <div style={{ position: "absolute", left: cx - SW / 2, top: cy - SH / 2, width: SW, height: SH, perspective: 2600 * k,
          opacity: ramp(frame, 0, 5), transform: `translateY(${((1 - appear) * 120 * k).toFixed(2)}px) scale(${(0.9 + 0.1 * appear).toFixed(4)})` }}>
          {/* The shadow the sheet casts on the desk: under whatever part of it lies open. */}
          <div style={{ position: "absolute", top: 0, bottom: 0,
            left: thL < 90 ? P - P * Math.cos((thL * Math.PI) / 180) : P,
            right: Math.abs(thR) < 90 ? P - P * Math.cos((thR * Math.PI) / 180) : P,
            boxShadow: `0 ${24 * k}px ${shadowSpread * k}px rgba(0,0,0,.55)` }} />
          <div style={{ position: "absolute", inset: 0, transformStyle: "preserve-3d" }}>
            {panel(1, 0, "50% 50%")}
            {panel(0, thL, "100% 50%")}
            {panel(2, thR, "0% 50%")}
          </div>
        </div>
      </AbsoluteFill>
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${300 * k}px rgba(0,0,0,.6)` }} />
      <PxCaption ov={overlay} at={24} q={q} accent={accent} bottom={92} />
    </AbsoluteFill>
  );
};

// ================================================================== px-field-journal
// The notebook lies open; the print drops onto the left page (2 -> 12) and the tape goes on (12 -> 15;
// sfx_at 13, the tape); the name is handwritten on the right page from 17, the second line after it, and a
// pencil arrow draws from the words to the print.
const FieldJournal: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const life = useLife();
  const src = photoOf(overlay);
  const ar = useAspect(src);
  if (!src) return null;
  const seed = hashStr(src) % 97;
  const NX = 90 * k, NY = 66 * k, NW = 1740 * k, NH = 952 * k, half = NW / 2;
  const pa = printAspect(ar);
  const B = 14 * k;
  const IW = pa >= 1 ? 690 * k : 450 * k;
  const IH = IW / pa;
  const pcx = half * 0.52, pcy = NH * 0.47;
  const drop = ramp(frame, 2, 10, EXPO_OUT);
  const tapeP = ramp(frame, 12, 4, EXPO_OUT);
  const ink = "#22305a";
  const title = asWritten(overlay.text, 60);
  const sub = asWritten(overlay.subtitle, 70);
  const date = asWritten(overlay.label, 24);
  const room = half - 200 * k;
  const TS = 84, SS = 54;
  const tl = handLines(title, room, TS * k, 2);
  const sl = handLines(sub, room, SS * k, 2);
  const n = tl.join("").length + sl.join("").length;
  const step = Math.max(0.55, Math.min(1.15, 34 / Math.max(1, n)));
  const tAt = 17;
  const sAt = tAt + tl.join("").length * step + 4;
  const textEnd = sAt + sl.join("").length * step;
  // The notes face the print, their block centred on its middle.
  const blockH = tl.length * TS * 1.12 * k + (sl.length ? 10 * k + sl.length * SS * 1.12 * k : 0);
  const x0 = half + 120 * k, y0 = Math.max(150 * k, pcy - blockH / 2 - 10 * k);
  // The arrow: from the left of the words, bowing down to the print's right edge.
  const S = { x: x0 - 22 * k, y: y0 + TS * 0.62 * k };
  const E = { x: pcx + IW / 2 + B + 24 * k, y: pcy + IH * 0.06 };
  const pts: Pt[] = [];
  for (let i = 0; i <= 32; i++) {
    const t = i / 32;
    const mx = (S.x + E.x) / 2, my = Math.max(S.y, E.y) + 56 * k;
    pts.push({ x: (1 - t) * (1 - t) * S.x + 2 * (1 - t) * t * mx + t * t * E.x, y: (1 - t) * (1 - t) * S.y + 2 * (1 - t) * t * my + t * t * E.y });
  }
  const arrowAt = Math.max(textEnd + 2, 30);
  const draw = ramp(frame, arrowAt, 12, Easing.bezier(0.45, 0, 0.2, 1));
  const head = ramp(frame, arrowAt + 11, 4);
  const pl = poly(pts);
  const n2 = pts.length - 1;
  const ux = (pts[n2].x - pts[n2 - 3].x), uy = (pts[n2].y - pts[n2 - 3].y);
  const ul = Math.hypot(ux, uy) || 1;
  const wings = [-1, 1].map((sg) => {
    const a = (sg * 145 * Math.PI) / 180;
    const dx = (ux / ul) * Math.cos(a) - (uy / ul) * Math.sin(a), dy = (ux / ul) * Math.sin(a) + (uy / ul) * Math.cos(a);
    return poly([0, 1, 2, 3, 4, 5, 6].map((j) => ({ x: E.x + dx * 30 * k * (j / 6), y: E.y + dy * 30 * k * (j / 6) })));
  });
  const ruled = `repeating-linear-gradient(180deg, rgba(0,0,0,0) 0px, rgba(0,0,0,0) ${39 * k}px, rgba(82,112,158,.24) ${39 * k}px, `
    + `rgba(82,112,158,.24) ${41 * k}px)`;
  return (
    <AbsoluteFill style={{ background: DESK, overflow: "hidden" }}>
      <DeskGrain k={k} />
      <AbsoluteFill style={{ transform: `scale(${(1.1 + 0.05 * life).toFixed(4)})`, transformOrigin: "47% 47%" }}>
        <div style={{ position: "absolute", left: NX, top: NY, width: NW, height: NH, transform: "rotate(-0.9deg)" }}>
          {/* The cover under the pages, then the two pages. */}
          <div style={{ position: "absolute", left: -16 * k, top: -14 * k, right: -16 * k, bottom: -16 * k, borderRadius: 10 * k,
            background: "linear-gradient(160deg, #3d2a1c 0%, #2a1c12 100%)", boxShadow: `0 ${28 * k}px ${60 * k}px rgba(0,0,0,.6)` }} />
          {[0, 1].map((side) => (
            <div key={side} style={{ position: "absolute", left: side * half, top: 0, width: half, height: NH, overflow: "hidden",
              background: "linear-gradient(170deg, #f5f0e3 0%, #ece5d4 100%)",
              borderRadius: side ? `0 ${6 * k}px ${6 * k}px 0` : `${6 * k}px 0 0 ${6 * k}px` }}>
              <div style={{ position: "absolute", left: 0, right: 0, top: 104 * k, bottom: 40 * k, backgroundImage: ruled }} />
              {side === 0 ? <div style={{ position: "absolute", top: 0, bottom: 0, left: 92 * k, width: 2 * k, background: "rgba(196,72,72,.35)" }} /> : null}
              <PaperGrain w={half} h={NH} seed={seed + side} opacity={0.16} />
              <div style={{ position: "absolute", top: 0, bottom: 0, [side ? "left" : "right"]: 0, width: 90 * k,
                background: `linear-gradient(${side ? 90 : 270}deg, rgba(60,40,20,.26) 0%, rgba(60,40,20,.08) 35%, rgba(60,40,20,0) 100%)` } as CSS} />
            </div>
          ))}
          {/* The print, dropped and taped on. */}
          <div style={{ position: "absolute", left: pcx - IW / 2 - B, top: pcy - IH / 2 - B, width: IW + 2 * B, height: IH + 2 * B,
            background: "#fbfaf6", opacity: ramp(frame, 2, 3),
            transform: `translate(${((1 - drop) * -30 * k).toFixed(2)}px, ${((1 - drop) * -70 * k).toFixed(2)}px) rotate(${(-3.2 - 5 * (1 - drop)).toFixed(3)}deg) scale(${(1 + 0.08 * (1 - drop)).toFixed(4)})`,
            boxShadow: `${(4 + 14 * (1 - drop)) * k}px ${(6 + 26 * (1 - drop)) * k}px ${(10 + 30 * (1 - drop)) * k}px rgba(0,0,0,${(0.34 - 0.1 * (1 - drop)).toFixed(3)})` }}>
            <div style={{ position: "absolute", left: B, top: B, width: IW, height: IH, overflow: "hidden", background: "#222" }}>
              <Cover src={src} pos="50% 42%" style={{ filter: "contrast(1.04) saturate(.94) sepia(.05)" }} />
              <div style={{ position: "absolute", inset: 0, background: "linear-gradient(125deg, rgba(255,255,255,.12) 0%, rgba(255,255,255,0) 38%)" }} />
            </div>
            <Tape x={B + 34 * k} y={6 * k} w={170 * k} h={46 * k} rot={-36} seed={seed} k={k} p={tapeP} />
            <Tape x={IW + B - 30 * k} y={8 * k} w={170 * k} h={46 * k} rot={33} seed={seed + 9} k={k} p={tapeP} />
          </div>
          {/* The notes on the right page. */}
          {date ? (
            <div style={{ position: "absolute", right: 150 * k, top: 100 * k }}>
              <Handwrite text={date} at={14} step={0.9} style={{ fontFamily: HAND, fontWeight: 600, fontSize: 44 * k, color: ink, opacity: 0.8 }} />
            </div>
          ) : null}
          <div style={{ position: "absolute", left: x0, top: y0, display: "flex", flexDirection: "column", gap: 2 * k }}>
            {tl.map((ln, i) => (
              <Handwrite key={i} text={ln} at={tAt + tl.slice(0, i).join("").length * step} step={step}
                style={{ fontFamily: HAND, fontWeight: 700, fontSize: TS * k, color: ink }} />
            ))}
            {sl.map((ln, i) => (
              <Handwrite key={`s${i}`} text={ln} at={sAt + sl.slice(0, i).join("").length * step} step={step}
                style={{ fontFamily: HAND, fontWeight: 600, fontSize: SS * k, color: ink, opacity: 0.86, marginTop: i ? 0 : 10 * k }} />
            ))}
          </div>
          {tl.length ? (
            <svg width={NW} height={NH} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
              <path d={markerPath(pl, 0, draw, 5.5 * k, BODY, seed)} fill="#3b3f4a" opacity={0.85} />
              {head > 0.01 ? wings.map((w, i) => <path key={i} d={markerPath(w, 0, head, 5 * k, FLICK, seed + i)} fill="#3b3f4a" opacity={0.85} />) : null}
            </svg>
          ) : null}
        </div>
      </AbsoluteFill>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 42% 36%, rgba(255,228,190,.07) 0%, rgba(0,0,0,0) 50%, rgba(0,0,0,.42) 100%)" }} />
    </AbsoluteFill>
  );
};

// ================================================================== px-magazine-spread
// The magazine slides in and lands at 12 (sfx_at 12, the paper); a gloss sweeps across the picture 10 -> 36;
// the headline and the deck sit on the picture's own shade; the camera glides in.
const MagazineSpread: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H } = useVideoConfig();
  const k = useK();
  const life = useLife();
  const src = photoOf(overlay);
  const ar = useAspect(src);
  if (!src) return null;
  const seed = hashStr(src) % 97;
  // An opener spread: the picture bled across both pages at their own 3:2-ish shape.
  const SW = 1640 * k, SH = 1060 * k, half = SW / 2;
  const e = ramp(frame, 0, 15, EXPO_OUT);
  const kick = caps(overlay.label, 40);
  const head = cut(str(overlay.text), 64);
  const fit = (px: number) => wrapBy(head, 700 * k, (s) => s.length * px * k * 0.46);
  const hs = fit(84).length <= 2 ? 84 : fit(70).length <= 2 ? 70 : 58;
  const hls = fit(hs).slice(0, 2);
  const deck = cut(str(overlay.subtitle), 120);
  const deckLines = wrapBy(deck, 640 * k, (s) => s.length * 30 * k * 0.43).slice(0, 2);
  const sweep = interpolate(frame, [10, 36], [-40, 140], { ...clamp, easing: IN_OUT });
  const sweepA = ramp(frame, 10, 6) * (1 - ramp(frame, 30, 8));
  const scale = 0.93 * (1 + 0.05 * life);
  const words = ramp(frame, 14, 12);
  return (
    <AbsoluteFill style={{ background: DESK, overflow: "hidden" }}>
      <DeskGrain k={k} />
      <div style={{ position: "absolute", left: W / 2 - SW / 2, top: H / 2 - SH / 2 + 6 * k, width: SW, height: SH,
        transform: `translate(${((1 - e) * 1250 * k).toFixed(2)}px, ${((1 - e) * 60 * k).toFixed(2)}px) rotate(${(-1.2 - 5 * (1 - e)).toFixed(3)}deg) scale(${scale.toFixed(4)})`,
        boxShadow: `0 ${(20 + 30 * (1 - e)) * k}px ${(50 + 40 * (1 - e)) * k}px rgba(0,0,0,.6)`, background: "#f6f4ee", overflow: "hidden" }}>
        <FillPhoto src={src} ar={ar} w={SW} h={SH} filter="contrast(1.06) saturate(1.06)" />
        <div style={{ position: "absolute", inset: 0, opacity: sweepA, mixBlendMode: "screen", transform: `translateX(${sweep.toFixed(2)}%)`,
          background: "linear-gradient(110deg, rgba(255,255,255,0) 35%, rgba(255,255,255,.2) 48%, rgba(255,255,255,.28) 50%, rgba(255,255,255,0) 64%)" }} />
        {/* The shade the art director put under the words. */}
        <div style={{ position: "absolute", left: 0, top: 0, width: SW, height: SH,
          background: "linear-gradient(14deg, rgba(0,0,0,.72) 0%, rgba(0,0,0,.42) 26%, rgba(0,0,0,0) 52%)" }} />
        {/* The left page: the kicker, the headline, the deck. */}
        <div style={{ position: "absolute", left: 76 * k, bottom: 86 * k, width: half - 130 * k, opacity: words,
          transform: `translateY(${((1 - words) * 16 * k).toFixed(2)}px)` }}>
          {kick ? <div style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.32em", color: accent, marginBottom: 14 * k,
            whiteSpace: "nowrap", textShadow: "0 2px 10px rgba(0,0,0,.5)" }}>{kick}</div> : null}
          {hls.map((ln, i) => (
            <div key={i} style={{ fontFamily: SERIF, fontSize: hs * k, lineHeight: 1.02, color: "#fff", whiteSpace: "nowrap",
              letterSpacing: "-0.012em", textShadow: "0 4px 26px rgba(0,0,0,.45)" }}>{ln}</div>
          ))}
          {deckLines.map((ln, i) => (
            <div key={`d${i}`} style={{ fontFamily: SERIF_ITALIC, fontSize: 30 * k, lineHeight: 1.28, color: "rgba(255,255,255,.9)",
              whiteSpace: "nowrap", marginTop: i ? 0 : 18 * k, textShadow: "0 2px 12px rgba(0,0,0,.5)" }}>{ln}</div>
          ))}
        </div>
        <PaperGrain w={SW} h={SH} seed={seed} opacity={0.06} />
        {/* The fold down the middle, and the page's gloss either side of it. */}
        <div style={{ position: "absolute", top: 0, bottom: 0, left: half - 80 * k, width: 160 * k,
          background: "linear-gradient(90deg, rgba(0,0,0,0) 0%, rgba(0,0,0,.1) 34%, rgba(0,0,0,.4) 50%, rgba(255,255,255,.14) 53%, rgba(0,0,0,.08) 68%, rgba(0,0,0,0) 100%)" }} />
        <div style={{ position: "absolute", inset: 0, background: "linear-gradient(90deg, rgba(255,255,255,.06) 0%, rgba(255,255,255,0) 20%, rgba(0,0,0,0) 80%, rgba(0,0,0,.12) 100%)" }} />
      </div>
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${280 * k}px rgba(0,0,0,.55)` }} />
    </AbsoluteFill>
  );
};

// ================================================================== px-postcard
/** The back of a postcard: the header, the divider, a stamp of the picture, its postmark, a written line. */
const PostcardBack: React.FC<{ w: number; h: number; k: number; src: string; place: string; date: string; note: string;
  seed: number; id: string }> = ({ w, h, k, src, place, date, note, seed, id }) => {
  const sw = 118 * k, sh = 144 * k, sx = w - sw - 46 * k, sy = 42 * k;
  const pcx = sx - 6 * k, pcy = sy + sh - 18 * k, pr = 64 * k;
  const ring = cut(place.toUpperCase(), 26);
  const narrow = w < h;
  const notePx = narrow ? 36 * k : 44 * k;
  const lines = handLines(note, w * 0.55 - 100 * k, notePx, narrow ? 4 : 3);
  // The stamp's paper: a white rectangle with half-round bites all round its edge.
  const holes: React.ReactNode[] = [];
  const hr = 4.2 * k, gap = 11 * k;
  for (let x = gap / 2; x < sw; x += gap) holes.push(<circle key={`t${x}`} cx={x} cy={0} r={hr} />, <circle key={`b${x}`} cx={x} cy={sh} r={hr} />);
  for (let y = gap / 2; y < sh; y += gap) holes.push(<circle key={`l${y}`} cx={0} cy={y} r={hr} />, <circle key={`r${y}`} cx={sw} cy={y} r={hr} />);
  const waves = [0, 1, 2, 3, 4].map((i) => {
    const y = sy + 30 * k + i * 22 * k;
    let d = `M ${pcx + pr + 8 * k} ${y}`;
    for (let x = pcx + pr + 8 * k; x <= sx + sw + 34 * k; x += 6 * k) d += ` L ${x.toFixed(1)} ${(y + Math.sin((x / (34 * k)) * Math.PI * 2) * 5 * k).toFixed(1)}`;
    return d;
  });
  return (
    <div style={{ position: "absolute", inset: 0, background: "linear-gradient(165deg, #f5f0e4 0%, #ebe4d4 100%)", overflow: "hidden" }}>
      <PaperGrain w={w} h={h} seed={seed + 2} opacity={0.18} />
      <div style={{ position: "absolute", left: 0, width: narrow ? sx - 10 * k : w, top: 40 * k, textAlign: "center", fontFamily: SERIF,
        fontSize: (narrow ? 28 : 34) * k, letterSpacing: "0.32em", color: "#4c4436", whiteSpace: "nowrap" }}>POST CARD</div>
      <div style={{ position: "absolute", left: w * 0.55, top: 130 * k, bottom: 60 * k, width: 2 * k, background: "rgba(110,100,82,.7)" }} />
      {[0, 1, 2].map((i) => (
        <div key={i} style={{ position: "absolute", left: w * 0.6, right: 60 * k, top: h - (230 - i * 64) * k, height: 2 * k, background: "rgba(110,100,82,.55)" }} />
      ))}
      {/* The stamp: the picture itself, engraved-looking, on a perforated paper. */}
      <div style={{ position: "absolute", left: sx, top: sy, width: sw, height: sh, filter: `drop-shadow(0 ${1 * k}px ${2 * k}px rgba(0,0,0,.28))` }}>
        <svg width={sw} height={sh} style={{ position: "absolute", left: 0, top: 0 }}>
          <defs>
            <mask id={`${id}perf`} maskUnits="userSpaceOnUse" x={0} y={0} width={sw} height={sh}>
              <rect width={sw} height={sh} fill="#fff" />
              <g fill="#000">{holes}</g>
            </mask>
          </defs>
          <rect width={sw} height={sh} fill="#fbf8ef" mask={`url(#${id}perf)`} />
        </svg>
        <div style={{ position: "absolute", inset: 11 * k, overflow: "hidden", background: "#30302c" }}>
          <Cover src={src} style={{ filter: "grayscale(1) contrast(1.3) sepia(.55) hue-rotate(-12deg) saturate(1.4)" }} />
        </div>
      </div>
      <svg width={w} height={h} style={{ position: "absolute", left: 0, top: 0, overflow: "visible", opacity: 0.78 }}>
        <defs>
          <path id={`${id}arc`} d={`M ${pcx - pr * 0.78} ${pcy} A ${pr * 0.78} ${pr * 0.78} 0 1 1 ${pcx + pr * 0.78} ${pcy}`} />
        </defs>
        <circle cx={pcx} cy={pcy} r={pr} fill="none" stroke="#28264e" strokeWidth={3 * k} />
        <circle cx={pcx} cy={pcy} r={pr * 0.62} fill="none" stroke="#28264e" strokeWidth={2 * k} />
        {ring ? (
          <text fontFamily={LABEL} fontWeight={700} fontSize={14 * k} letterSpacing={2.4 * k} fill="#28264e">
            <textPath href={`#${id}arc`} startOffset="50%" textAnchor="middle">{ring}</textPath>
          </text>
        ) : null}
        {date ? <text x={pcx} y={pcy + 6 * k} textAnchor="middle" fontFamily={LABEL} fontWeight={700} fontSize={17 * k}
          letterSpacing={1.2 * k} fill="#28264e">{cut(date.toUpperCase(), 12)}</text> : null}
        {waves.map((d, i) => <path key={i} d={d} fill="none" stroke="#28264e" strokeWidth={2.4 * k} />)}
      </svg>
      <div style={{ position: "absolute", left: (narrow ? 40 : 60) * k, top: (narrow ? 150 : 170) * k, display: "flex", flexDirection: "column" }}>
        {lines.map((ln, i) => (
          <div key={i} style={{ fontFamily: HAND, fontWeight: 600, fontSize: notePx, lineHeight: 1.25, color: "#23397a", whiteSpace: "nowrap" }}>{ln}</div>
        ))}
      </div>
    </div>
  );
};

// The card slides in on its back (0 -> 13), turns over (12 -> 26; sfx_at 22, the flip) and lands on its
// picture at 26, then settles; at the exit it slides away up and to the left.
const Postcard: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const life = useLife();
  const id = `pxPc${uidOf(React.useId())}`;
  const src = photoOf(overlay);
  const ar = useAspect(src);
  if (!src) return null;
  const seed = hashStr(src) % 97;
  const portrait = printAspect(ar) < 1;
  const CW = portrait ? 620 * k : 1200 * k, CH = portrait ? 930 * k : 800 * k;
  const BW = 24 * k, BB = 74 * k;
  const enter = ramp(frame, 0, 14, EXPO_OUT);
  const flip = ramp(frame, 12, 14, IN_OUT);
  const leave = ramp(frame, dur - 13, 12, EXPO_IN);
  const fade = ramp(frame, dur - 12, 11, Easing.linear);
  const rho = 180 + 180 * flip;
  const lift = Math.sin(Math.PI * flip);
  const rotZ = 12 * (1 - enter) + 2.5 * (1 - flip) - 1.6 * flip - 8 * leave;
  const tx = (1 - enter) * 760 * k - leave * 1500 * k, ty = (1 - enter) * 300 * k - leave * 420 * k;
  // The postmark carries the place (the label when it is not a year, else the title) and the year said.
  const label = str(overlay.label);
  const date = yearIn(`${label} ${str(overlay.subtitle)}`);
  const place = label && !/^\s*\d{4}s?\s*$/.test(label) ? label : str(overlay.text);
  const note = str(overlay.subtitle);
  const capLine = caps(overlay.text, 44) + (str(overlay.label) ? `  ·  ${caps(overlay.label, 30)}` : "");
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{ background: DESK, opacity: 1 - fade }} />
      <AbsoluteFill style={{ opacity: 1 - fade }}><DeskGrain k={k} /></AbsoluteFill>
      <AbsoluteFill style={{ transform: `scale(${(1 + 0.04 * life).toFixed(4)})` }}>
        <div style={{ position: "absolute", left: W / 2 - CW / 2, top: H / 2 - CH / 2, width: CW, height: CH, perspective: 3000 * k,
          transform: `translate(${tx.toFixed(2)}px, ${ty.toFixed(2)}px) rotate(${rotZ.toFixed(3)}deg) scale(${(1 + 0.06 * lift).toFixed(4)})` }}>
          <div style={{ position: "absolute", inset: 0, boxShadow: `${(10 + 30 * lift) * k}px ${(18 + 40 * lift) * k}px ${(34 + 50 * lift) * k}px rgba(0,0,0,${(0.55 - 0.15 * lift).toFixed(3)})`,
            transform: `scaleX(${Math.max(0.02, Math.abs(Math.cos((rho * Math.PI) / 180))).toFixed(4)})` }} />
          <div style={{ position: "absolute", inset: 0, transformStyle: "preserve-3d", transform: `rotateY(${rho.toFixed(3)}deg)` }}>
            {/* The picture side. */}
            <div style={{ position: "absolute", inset: 0, backfaceVisibility: "hidden", background: "#fbf9f3", borderRadius: 3 * k, overflow: "hidden" }}>
              <div style={{ position: "absolute", left: BW, top: BW, right: BW, bottom: BB, overflow: "hidden", background: "#222" }}>
                <Cover src={src} pos="50% 45%" style={{ filter: "contrast(1.07) saturate(1.12) sepia(.06)" }} />
                <div style={{ position: "absolute", inset: 0, background: "linear-gradient(125deg, rgba(255,255,255,.13) 0%, rgba(255,255,255,0) 40%)" }} />
              </div>
              <div style={{ position: "absolute", left: BW + 4 * k, right: BW, bottom: 0, height: BB, display: "flex", alignItems: "center",
                fontFamily: LABEL, fontWeight: 600, fontSize: 22 * k, letterSpacing: "0.16em", color: "#3d3a33", whiteSpace: "nowrap", overflow: "hidden" }}>
                {capLine}
              </div>
              <PaperGrain w={CW} h={CH} seed={seed} opacity={0.07} />
            </div>
            {/* The written side. */}
            <div style={{ position: "absolute", inset: 0, backfaceVisibility: "hidden", transform: "rotateY(180deg)", borderRadius: 3 * k, overflow: "hidden" }}>
              <PostcardBack w={CW} h={CH} k={k} src={src} place={place} date={date} note={note} seed={seed} id={id} />
            </div>
          </div>
        </div>
      </AbsoluteFill>
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${300 * k}px rgba(0,0,0,.55)`, opacity: 1 - fade }} />
    </AbsoluteFill>
  );
};

// ================================================================== registry
export const LOOKS: Record<string, Look> = {
  "px-aperture-iris": ApertureIris,
  "px-slit-reveal": SlitReveal,
  "px-color-bloom": ColorBloom,
  "px-diagonal-slices": DiagonalSlices,
  "px-level-line": LevelLine,
  "px-detail-inset": DetailInset,
  "px-viewfinder": Viewfinder,
  "px-torn-strips": TornStrips,
  "px-folded-print": FoldedPrint,
  "px-field-journal": FieldJournal,
  "px-magazine-spread": MagazineSpread,
  "px-postcard": Postcard,
};
