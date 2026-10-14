import { kitColor, kitEase, kitFont, kitOf } from "./brandKits";
/**
 * The Smart Editor's motion spec: the data, the clean-up and the arithmetic (2026-10-14).
 *
 * A motion spec is a small After-Effects-like composition the AI edit director designs for one moment of the
 * narration (src/smart_editor.py writes it, src/motionspec.py checks it the same way this file does). One
 * renderer (SmartSpec.tsx) draws any spec, so the director can design a new graphic each time instead of
 * picking the same template again.
 *
 * Everything is pure and deterministic: a spec plus a frame number gives the same picture in the worker's
 * render and in the editor's Player. Times are SECONDS from the graphic's first frame (fps independent);
 * positions and sizes are shares of the frame (x, w of its width; y, h, text size of its height).
 *
 * A spec that is not an object, or has no drawable layer after clean-up, is dropped (null) - never an error,
 * never a hang. Every number is clamped to a sane range; unknown kinds, fonts and easings are ignored.
 */

export type Key = [number, number, string?];
export type Keys = Record<string, Key[]>;

export type LayerKind =
  | "text" | "counter" | "rect" | "ellipse" | "line" | "arrow" | "bracket" | "pin" | "spot" | "image"
  | "particles"
  // The brand-kit primitives (2026-10-14): a full-frame kit backdrop, a flat vector illustration that builds
  // piece by piece, a waffle / unit chart, a measurement arrow with its value, a circular loupe on a picture,
  // a row of tiles that pop in one by one, a label pill.
  | "backdrop" | "shape" | "waffle" | "measure" | "loupe" | "tiles" | "pill";

/** One piece of a flat vector illustration, in the layer's own box (0..1 of its w / h). */
export interface ShapePart {
  t: "rect" | "poly" | "ellipse" | "line";
  x?: number; y?: number; w?: number; h?: number;
  p?: [number, number][];
  c: string;
  sw?: number;
  r?: number;
}

export interface Animator {
  /** What moves on its own: each character, word or line. */
  unit: "char" | "word" | "line";
  /** Seconds between units (ignored for the units that have their own time in `at`). */
  stagger: number;
  /** Seconds each unit takes to arrive. */
  dur: number;
  ease: string;
  /** Where each unit starts from (it arrives at the rest pose: 0 / 1). */
  from: Partial<Record<"opacity" | "x" | "y" | "scale" | "rot" | "rotX" | "rotY" | "blur" | "tracking", number>>;
  /** Seconds each word lands (the narration's own word times), when known: per-word sync. */
  at?: number[];
}

export interface Layer {
  id: string;
  kind: LayerKind;
  /** Centre (or the anchor side for left/right text), shares of the frame. */
  x: number;
  y: number;
  w: number;
  h: number;
  anchor: "c" | "l" | "r";
  /** Seconds from the graphic's start this layer is on (to = end). */
  from: number;
  to: number;
  keys: Keys;
  color: string;
  fill?: string;
  stroke?: number;
  opacity: number;
  blend?: string;
  /** Depth for the parallax drift (0 = screen plane, + nearer). */
  z: number;
  // text / counter
  text?: string;
  font?: string;
  size?: number;
  weight?: number;
  tracking?: number;
  upper?: boolean;
  italic?: boolean;
  align?: "left" | "center" | "right";
  maxW?: number;
  lineH?: number;
  emph?: number[];
  emphColor?: string;
  emphStyle?: "color" | "box" | "underline" | "glow";
  shadow?: "soft" | "hard" | "none";
  glow?: number;
  extrude?: number;
  extrudeColor?: string;
  panel?: { color: string; opacity: number; pad: number; radius: number; blur: number };
  animator?: Animator;
  /** A second line under the words, arriving at `at` seconds. */
  sub?: { text: string; size: number; font: string; weight: number; color: string; tracking: number; upper: boolean; at: number };
  /** A small tag above the words (wiped on at `at`). */
  kicker?: { text: string; size: number; color: string; bg: string; at: number };
  /** The block's furniture, each an accent colour or absent; drawn on from `at` seconds. */
  deco?: { bar?: string; underline?: string; rule?: string; bracket?: string; at: number };
  // counter
  valueFrom?: number;
  valueTo?: number;
  decimals?: number;
  prefix?: string;
  suffix?: string;
  /** Thousands separators (false for a year). */
  group?: boolean;
  // shapes
  radius?: number;
  points?: [number, number][];
  curve?: number;
  head?: number;
  dash?: number;
  // image
  src?: string;
  // particles
  count?: number;
  seed?: number;
  speed?: number;
  // shape: the parts, how they build (up = each grows from its base, pop, draw, left, fade), seconds between
  shapes?: ShapePart[];
  build?: "up" | "pop" | "draw" | "left" | "fade";
  stagger?: number;
  bdur?: number;
  ease?: string;
  // waffle
  cols?: number;
  rows?: number;
  value?: number;
  offColor?: string;
  fillFor?: number;
  // loupe: the picture point (0..1 of the picture) it magnifies, and how much
  fx?: number;
  fy?: number;
  zoom?: number;
  // tiles
  items?: string[];
  // backdrop
  color2?: string;
  grid?: boolean;
}

export interface MotionSpec {
  v: 1;
  /** Perspective distance at a 1080-line frame (smaller = stronger 3D). */
  persp: number;
  /** A readability scrim over the footage under the graphic. */
  shade?: { kind: "vignette" | "bottom" | "top" | "left" | "right" | "full"; amount: number };
  /** A move on the clip itself (CameraFx): keys scale, x, y, rot, shake, blur, dim. */
  camera?: { keys: Keys };
  /** How the whole graphic leaves over its last `dur` seconds. */
  exit: { kind: "fade" | "blur" | "drop" | "scale" | "wipe"; dur: number };
  /** Gentle drift of the whole stage (depth parallax): shares of the frame over the graphic's life. */
  drift: { x: number; y: number; rotY: number };
  layers: Layer[];
}

const KINDS = new Set<LayerKind>(["text", "counter", "rect", "ellipse", "line", "arrow", "bracket", "pin", "spot",
  "image", "particles", "backdrop", "shape", "waffle", "measure", "loupe", "tiles", "pill"]);
export const FONT_KEYS = ["grotesk", "kinetic", "display", "serif", "serif-italic", "mono", "narrow", "inter"] as const;
const KEYED = new Set(["x", "y", "scale", "sx", "sy", "rot", "rotX", "rotY", "z", "opacity", "blur", "draw", "wipe",
  "glow", "p", "tracking", "shake", "dim"]);
const BLENDS = new Set(["normal", "screen", "overlay", "multiply", "lighten", "soft-light", "difference", "plus-lighter"]);
const MAX_LAYERS = 24;
const MAX_KEYS = 16;

// ------------------------------------------------------------------ easing
const c01 = (t: number) => (t < 0 ? 0 : t > 1 ? 1 : t);
const backOut = (t: number) => { const c1 = 1.70158, c3 = c1 + 1; const x = c01(t) - 1; return 1 + c3 * x * x * x + c1 * x * x; };
const backIn = (t: number) => { const c1 = 1.70158, c3 = c1 + 1; const x = c01(t); return c3 * x * x * x - c1 * x * x; };
const expoOut = (t: number) => (c01(t) >= 1 ? 1 : 1 - 2 ** (-10 * c01(t)));
const expoIn = (t: number) => (c01(t) <= 0 ? 0 : 2 ** (10 * c01(t) - 10));
const expoInOut = (t: number) => {
  const x = c01(t);
  if (x <= 0 || x >= 1) return x;
  return x < 0.5 ? 2 ** (20 * x - 10) / 2 : (2 - 2 ** (-20 * x + 10)) / 2;
};
/** A critically damped-ish spring settle with one small overshoot (deterministic, no physics state). */
const spring = (t: number) => { const x = c01(t); return 1 - Math.exp(-6.5 * x) * Math.cos(9 * x) * (1 - x * 0.15); };
const elastic = (t: number) => {
  const x = c01(t);
  if (x <= 0 || x >= 1) return x;
  return 2 ** (-10 * x) * Math.sin((x * 10 - 0.75) * ((2 * Math.PI) / 3)) + 1;
};

export const EASES: Record<string, (t: number) => number> = {
  linear: c01,
  in: (t) => c01(t) ** 3,
  out: (t) => 1 - (1 - c01(t)) ** 3,
  inOut: (t) => { const x = c01(t); return x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2; },
  quintOut: (t) => 1 - (1 - c01(t)) ** 5,
  expoOut, expoIn, expoInOut, backOut, backIn, spring, elastic,
  sine: (t) => -(Math.cos(Math.PI * c01(t)) - 1) / 2,
  hold: (t) => (c01(t) >= 1 ? 1 : 0),
};
export const easeOf = (name?: string) => EASES[name || ""] || EASES.out;

// ------------------------------------------------------------------ values
/** The value of keyed property `prop` at second `t`; `rest` when the property has no keys. */
export const valueAt = (keys: Keys | undefined, prop: string, t: number, rest: number): number => {
  const ks = keys && keys[prop];
  if (!ks || !ks.length) return rest;
  if (t <= ks[0][0]) return ks[0][1];
  for (let i = 1; i < ks.length; i++) {
    const [t1, v1, e] = ks[i];
    if (t <= t1) {
      const [t0, v0] = ks[i - 1];
      const span = t1 - t0;
      const p = span <= 0 ? 1 : easeOf(e)((t - t0) / span);
      return v0 + (v1 - v0) * p;
    }
  }
  return ks[ks.length - 1][1];
};

/** One unit's arrival progress (0 = at `from`, 1 = at rest) for animator unit `i` of `n`. */
export const unitProgress = (a: Animator, i: number, t: number): number => {
  const start = a.at && Number.isFinite(a.at[i]) ? (a.at[i] as number) : a.stagger * i;
  return easeOf(a.ease)((t - start) / Math.max(0.01, a.dur));
};

// ------------------------------------------------------------------ clean-up
const num = (v: unknown, lo: number, hi: number, dflt: number): number =>
  typeof v === "number" && Number.isFinite(v) ? Math.max(lo, Math.min(hi, v)) : dflt;
const str = (v: unknown, max = 200): string => (typeof v === "string" ? v.slice(0, max) : "");
const COLOR = /^(#[0-9a-fA-F]{3,8}|rgba?\([\d\s.,%]+\)|hsla?\([\d\s.,%deg]+\)|white|black|transparent)$/;
const color = (v: unknown, dflt: string): string => (typeof v === "string" && COLOR.test(v.trim()) ? v.trim() : dflt);

const cleanKeys = (raw: unknown, dur: number): Keys => {
  const out: Keys = {};
  if (!raw || typeof raw !== "object") return out;
  for (const [prop, list] of Object.entries(raw as Record<string, unknown>)) {
    if (!KEYED.has(prop) || !Array.isArray(list)) continue;
    const ks: Key[] = [];
    for (const k of list.slice(0, MAX_KEYS)) {
      if (!Array.isArray(k) || k.length < 2) continue;
      const t = num(k[0], 0, dur, NaN);
      const v = num(k[1], -1e6, 1e6, NaN);
      if (!Number.isFinite(t) || !Number.isFinite(v)) continue;
      ks.push([t, v, typeof k[2] === "string" && EASES[k[2]] ? k[2] : undefined]);
    }
    ks.sort((a, b) => a[0] - b[0]);
    if (ks.length) out[prop] = ks;
  }
  return out;
};

const cleanAnimator = (raw: unknown, dur: number): Animator | undefined => {
  if (!raw || typeof raw !== "object") return undefined;
  const a = raw as Record<string, unknown>;
  const unit = a.unit === "char" || a.unit === "line" ? a.unit : "word";
  const from: Animator["from"] = {};
  const f = (a.from && typeof a.from === "object" ? a.from : {}) as Record<string, unknown>;
  for (const k of ["opacity", "x", "y", "scale", "rot", "rotX", "rotY", "blur", "tracking"] as const) {
    if (typeof f[k] === "number" && Number.isFinite(f[k])) from[k] = num(f[k], -720, 720, 0);
  }
  const at = Array.isArray(a.at) ? a.at.slice(0, 80).map((v) => num(v, 0, dur, NaN)) : undefined;
  return { unit, stagger: num(a.stagger, 0, 2, 0.05), dur: num(a.dur, 0.04, 3, 0.45),
    ease: typeof a.ease === "string" && EASES[a.ease] ? a.ease : "expoOut", from, at };
};

const cleanLayer = (raw: unknown, i: number, dur: number): Layer | null => {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const kind = r.kind as LayerKind;
  if (!KINDS.has(kind)) return null;
  const from = num(r.from, 0, dur, 0);
  const L: Layer = {
    id: str(r.id, 40) || `l${i}`, kind,
    x: num(r.x, -0.5, 1.5, 0.5), y: num(r.y, -0.5, 1.5, 0.5), w: num(r.w, 0, 2, 0.2), h: num(r.h, 0, 2, 0.1),
    anchor: r.anchor === "l" || r.anchor === "r" ? r.anchor : "c",
    from, to: num(r.to, from, dur, dur), keys: cleanKeys(r.keys, dur),
    color: color(r.color, "#ffffff"), fill: r.fill === undefined ? undefined : color(r.fill, "transparent"),
    stroke: r.stroke === undefined ? undefined : num(r.stroke, 0, 0.05, 0.004),
    opacity: num(r.opacity, 0, 1, 1), blend: typeof r.blend === "string" && BLENDS.has(r.blend) ? r.blend : undefined,
    z: num(r.z, -1, 1, 0),
  };
  if (kind === "text" || kind === "counter" || kind === "pin") {
    L.text = str(r.text, 160);
    if (kind === "text" && !L.text.trim()) return null;
    L.font = FONT_KEYS.includes(r.font as never) ? (r.font as string) : "grotesk";
    L.size = num(r.size, 0.012, 0.4, 0.06);
    L.weight = Math.round(num(r.weight, 300, 900, 800) / 100) * 100;
    L.tracking = num(r.tracking, -0.1, 0.6, 0);
    L.upper = r.upper === true;
    L.italic = r.italic === true;
    L.align = r.align === "left" || r.align === "right" ? r.align : "center";
    L.maxW = num(r.maxW, 0.1, 0.96, 0.8);
    L.lineH = num(r.lineH, 0.8, 1.6, 1.05);
    L.emph = Array.isArray(r.emph) ? r.emph.filter((n) => Number.isInteger(n) && n >= 0 && n < 60).slice(0, 8) as number[] : [];
    L.emphColor = color(r.emphColor, "#f2c14e");
    L.emphStyle = ["box", "underline", "glow"].includes(r.emphStyle as string) ? r.emphStyle as Layer["emphStyle"] : "color";
    L.shadow = r.shadow === "hard" || r.shadow === "none" ? r.shadow : "soft";
    L.glow = num(r.glow, 0, 60, 0);
    L.extrude = Math.round(num(r.extrude, 0, 14, 0));
    L.extrudeColor = color(r.extrudeColor, "#1b1f27");
    if (r.panel && typeof r.panel === "object") {
      const p = r.panel as Record<string, unknown>;
      L.panel = { color: color(p.color, "#0c0e12"), opacity: num(p.opacity, 0, 1, 0.72), pad: num(p.pad, 0, 0.1, 0.018),
        radius: num(p.radius, 0, 0.05, 0.006), blur: num(p.blur, 0, 40, 14) };
    }
    L.animator = cleanAnimator(r.animator, dur);
    if (r.sub && typeof r.sub === "object") {
      const u = r.sub as Record<string, unknown>;
      const text = str(u.text, 120);
      if (text.trim()) L.sub = { text, size: num(u.size, 0.018, 0.08, 0.032), font: FONT_KEYS.includes(u.font as never) ? u.font as string : "inter",
        weight: Math.round(num(u.weight, 300, 900, 600) / 100) * 100, color: color(u.color, "#e9e9ea"),
        tracking: num(u.tracking, -0.05, 0.4, 0.02), upper: u.upper === true, at: num(u.at, 0, dur, 0.4) };
    }
    if (r.kicker && typeof r.kicker === "object") {
      const u = r.kicker as Record<string, unknown>;
      const text = str(u.text, 40);
      if (text.trim()) L.kicker = { text, size: num(u.size, 0.016, 0.05, 0.025), color: color(u.color, "#0b0c10"),
        bg: color(u.bg, "#f2c14e"), at: num(u.at, 0, dur, 0) };
    }
    if (r.deco && typeof r.deco === "object") {
      const u = r.deco as Record<string, unknown>;
      const c = (v: unknown) => (v === undefined ? undefined : color(v, "#f2c14e"));
      L.deco = { bar: c(u.bar), underline: c(u.underline), rule: c(u.rule), bracket: c(u.bracket), at: num(u.at, 0, dur, 0.3) };
    }
  }
  if (kind === "counter") {
    L.valueFrom = num(r.valueFrom, -1e12, 1e12, 0);
    L.valueTo = num(r.valueTo, -1e12, 1e12, 0);
    L.decimals = Math.round(num(r.decimals, 0, 3, 0));
    L.prefix = str(r.prefix, 8);
    L.suffix = str(r.suffix, 24);
    L.group = r.group !== false;
  }
  if (kind === "rect" || kind === "bracket" || kind === "image") L.radius = num(r.radius, 0, 0.2, 0);
  if (kind === "line" || kind === "arrow") {
    const pts = Array.isArray(r.points) ? r.points : [];
    L.points = pts.slice(0, 12).filter((p): p is [number, number] => Array.isArray(p) && p.length >= 2
      && Number.isFinite(p[0]) && Number.isFinite(p[1])).map((p) => [num(p[0], -0.2, 1.2, 0), num(p[1], -0.2, 1.2, 0)]);
    if (L.points.length < 2) return null;
    L.curve = num(r.curve, -0.5, 0.5, 0);
    L.head = num(r.head, 0, 0.08, kind === "arrow" ? 0.025 : 0);
    L.dash = num(r.dash, 0, 0.05, 0);
  }
  if (kind === "image") {
    L.src = str(r.src, 2000);
    if (!/^https?:\/\//.test(L.src) && !L.src.startsWith("data:image/")) return null;
  }
  if (kind === "pill") {
    L.text = str(r.text, 40);
    if (!L.text.trim()) return null;
    L.size = num(r.size, 0.014, 0.06, 0.026);
    L.fill = color(r.fill, "#f2b630");
    L.color = color(r.color, "#141414");
    L.font = FONT_KEYS.includes(r.font as never) ? (r.font as string) : "narrow";
  }
  if (kind === "backdrop") {
    L.color2 = color(r.color2, "#000000");
    L.grid = r.grid === true;
  }
  if (kind === "shape") {
    const parts = Array.isArray(r.shapes) ? r.shapes.slice(0, 40) : [];
    L.shapes = parts.map((q): ShapePart | null => {
      if (!q || typeof q !== "object") return null;
      const o = q as Record<string, unknown>;
      const t = o.t === "poly" || o.t === "ellipse" || o.t === "line" ? o.t : o.t === "rect" ? "rect" : null;
      if (!t) return null;
      const P: ShapePart = { t, c: color(o.c, "#ffffff"), sw: num(o.sw, 0, 0.05, 0.01), r: num(o.r, 0, 0.5, 0) };
      if (t === "poly" || t === "line") {
        const pts = (Array.isArray(o.p) ? o.p : []).slice(0, 24).filter((v): v is [number, number] =>
          Array.isArray(v) && v.length >= 2 && Number.isFinite(v[0]) && Number.isFinite(v[1]));
        if (pts.length < 2) return null;
        P.p = pts.map((v) => [num(v[0], -0.5, 1.5, 0), num(v[1], -0.5, 1.5, 0)]);
      } else {
        P.x = num(o.x, -0.5, 1.5, 0); P.y = num(o.y, -0.5, 1.5, 0); P.w = num(o.w, 0, 2, 0.1); P.h = num(o.h, 0, 2, 0.1);
      }
      return P;
    }).filter((q): q is ShapePart => !!q);
    if (!L.shapes.length) return null;
    L.build = ["pop", "draw", "left", "fade"].includes(r.build as string) ? r.build as Layer["build"] : "up";
    L.stagger = num(r.stagger, 0, 1, 0.06);
    L.bdur = num(r.bdur, 0.05, 2, 0.45);
    L.ease = typeof r.ease === "string" && EASES[r.ease] ? r.ease : "quintOut";
  }
  if (kind === "waffle") {
    L.cols = Math.round(num(r.cols, 2, 30, 10));
    L.rows = Math.round(num(r.rows, 1, 20, 10));
    L.value = Math.round(num(r.value, 0, L.cols * L.rows, 50));
    L.fill = color(r.fill, "#f2b630");
    L.offColor = color(r.offColor, "rgba(255,255,255,0.18)");
    L.fillFor = num(r.fillFor, 0.2, 4, 1.4);
  }
  if (kind === "measure") {
    const pts = Array.isArray(r.points) ? r.points : [];
    L.points = pts.slice(0, 2).filter((p): p is [number, number] => Array.isArray(p) && p.length >= 2
      && Number.isFinite(p[0]) && Number.isFinite(p[1])).map((p) => [num(p[0], 0, 1, 0), num(p[1], 0, 1, 0)]);
    if (L.points.length < 2) return null;
    L.text = str(r.text, 30);
    L.size = num(r.size, 0.016, 0.08, 0.034);
    L.font = FONT_KEYS.includes(r.font as never) ? (r.font as string) : "grotesk";
  }
  if (kind === "loupe") {
    L.src = str(r.src, 2000);
    if (!/^https?:\/\//.test(L.src) && !L.src.startsWith("data:image/")) return null;
    L.fx = num(r.fx, 0, 1, 0.5); L.fy = num(r.fy, 0, 1, 0.5); L.zoom = num(r.zoom, 1, 8, 2.5);
  }
  if (kind === "tiles") {
    L.items = (Array.isArray(r.items) ? r.items : []).slice(0, 6).map((v) => str(v, 24)).filter((v) => v.trim());
    if (!L.items.length) return null;
    L.size = num(r.size, 0.02, 0.2, 0.09);
    L.stagger = num(r.stagger, 0, 1, 0.18);
    L.fill = color(r.fill, "#ffffff");
    L.color = color(r.color, "#141414");
  }
  if (kind === "particles") {
    L.count = Math.round(num(r.count, 1, 120, 40));
    L.seed = Math.round(num(r.seed, 0, 1e6, i * 7 + 1));
    L.speed = num(r.speed, 0, 1, 0.15);
    L.size = num(r.size, 0.001, 0.05, 0.004);
  }
  return L;
};

/** The spec cleaned for drawing, or null when nothing in it can be drawn. `dur` = the graphic's seconds. */
export const cleanSpec = (raw: unknown, dur: number): MotionSpec | null => {
  if (!raw || typeof raw !== "object" || !(dur > 0)) return null;
  const s = resolveKit(raw) as Record<string, unknown>;
  const layers = (Array.isArray(s.layers) ? s.layers : []).slice(0, MAX_LAYERS)
    .map((l, i) => cleanLayer(l, i, dur)).filter((l): l is Layer => !!l);
  if (!layers.length) return null;
  const shadeRaw = (s.shade && typeof s.shade === "object" ? s.shade : null) as Record<string, unknown> | null;
  const shadeKinds = ["vignette", "bottom", "top", "left", "right", "full"];
  const exitRaw = (s.exit && typeof s.exit === "object" ? s.exit : {}) as Record<string, unknown>;
  const driftRaw = (s.drift && typeof s.drift === "object" ? s.drift : {}) as Record<string, unknown>;
  const cam = s.camera && typeof s.camera === "object" ? cleanKeys((s.camera as Record<string, unknown>).keys, dur) : {};
  return {
    v: 1, persp: num(s.persp, 300, 6000, 1400), layers,
    shade: shadeRaw && shadeKinds.includes(shadeRaw.kind as string)
      ? { kind: shadeRaw.kind as NonNullable<MotionSpec["shade"]>["kind"], amount: num(shadeRaw.amount, 0, 0.9, 0.4) }
      : undefined,
    camera: Object.keys(cam).length ? { keys: cam } : undefined,
    exit: { kind: ["blur", "drop", "scale", "wipe"].includes(exitRaw.kind as string)
      ? exitRaw.kind as MotionSpec["exit"]["kind"] : "fade", dur: num(exitRaw.dur, 0, Math.min(1.5, dur / 2), 0.35) },
    drift: { x: num(driftRaw.x, -0.05, 0.05, 0), y: num(driftRaw.y, -0.05, 0.05, 0), rotY: num(driftRaw.rotY, -12, 12, 0) },
  };
};

/** Every brand-kit token in a spec replaced by the kit's value (fonts by a font key, easings by an ease key). */
export const resolveKit = (raw: unknown): unknown => {
  const kit = kitOf((raw as { kit?: unknown })?.kit);
  const walk = (v: unknown, key: string): unknown => {
    if (typeof v === "string") {
      if (!v.startsWith("$")) return v;
      if (key === "font") return kitFont(v, kit);
      if (key === "ease" || key === "2") return kitEase(v, kit);
      return kitColor(v, kit);
    }
    if (Array.isArray(v)) return v.map((x, i) => walk(x, String(i)));
    if (v && typeof v === "object") {
      const o: Record<string, unknown> = {};
      for (const [k, x] of Object.entries(v as Record<string, unknown>)) o[k] = walk(x, k);
      return o;
    }
    return v;
  };
  return walk(raw, "");
};

/** "1,234.5" with the counter's decimals. */
export const formatCount = (v: number, decimals: number, group = true): string => {
  const fixed = Math.abs(v).toFixed(decimals);
  const [int, frac] = fixed.split(".");
  const grouped = group ? int.replace(/\B(?=(\d{3})+(?!\d))/g, ",") : int;
  return (v < 0 ? "-" : "") + grouped + (frac ? `.${frac}` : "");
};

/** A tiny deterministic random in [0, 1) (mulberry32): particles and shake. */
export const rand = (seed: number): number => {
  let t = (seed + 0x6d2b79f5) | 0;
  t = Math.imul(t ^ (t >>> 15), t | 1);
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};

/** The camera move at second `t` of a graphic (the clip under it): identity when there is none. */
export const cameraAt = (spec: MotionSpec | null, t: number) => {
  const k = spec?.camera?.keys;
  const shake = valueAt(k, "shake", t, 0);
  const sx = shake ? (Math.sin(t * 37.1) * 0.6 + Math.sin(t * 61.7) * 0.4) * shake : 0;
  const sy = shake ? (Math.sin(t * 43.3 + 1.3) * 0.6 + Math.sin(t * 71.9) * 0.4) * shake : 0;
  return {
    scale: valueAt(k, "scale", t, 1), x: valueAt(k, "x", t, 0) + sx, y: valueAt(k, "y", t, 0) + sy,
    rot: valueAt(k, "rot", t, 0), blur: valueAt(k, "blur", t, 0), dim: valueAt(k, "dim", t, 0),
  };
};
