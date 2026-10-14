/**
 * A clip's keyframes (Editor v2, the After-Effects layer): position, scale, rotation, opacity and anchor
 * animated over the scene, read by ClipFx.tsx on every frame and by the editor's key strips.
 *
 * Pure arithmetic over plain data (no Math.random, no clock), so the renderer, the editor's Player and the
 * worker's check (src/clipfx.py: the same cleaning in Python; a test runs both) agree on every frame.
 *
 *   scene.keyframes = { x?, y?, scale?, rotation?, opacity?, anchorX?, anchorY?: [{ t, v, e? }] }
 *     t  seconds from the scene's start
 *     v  x / y / anchorX / anchorY: shares of the frame (0 = centred); scale: 1 = as drawn now;
 *        rotation: degrees; opacity: 0..1
 *     e  the ease INTO this key (from the key before): linear (default), hold, easeIn, easeOut, easeInOut
 *        (cubic), expoOut, backOut, or "bezier:x1,y1,x2,y2" (a CSS cubic-bezier, solved numerically)
 * Before the first key a property holds the first key's value, after the last the last one's.
 */

export type KeyProp = "x" | "y" | "scale" | "rotation" | "opacity" | "anchorX" | "anchorY";
export const KEY_PROPS: KeyProp[] = ["x", "y", "scale", "rotation", "opacity", "anchorX", "anchorY"];

export type EaseName = "linear" | "hold" | "easeIn" | "easeOut" | "easeInOut" | "expoOut" | "backOut" | `bezier:${string}`;
export const EASE_NAMES: EaseName[] = ["linear", "hold", "easeIn", "easeOut", "easeInOut", "expoOut", "backOut"];

export interface Key { t: number; v: number; e?: EaseName }
export type ClipKeyframes = Partial<Record<KeyProp, Key[]>>;

/** Each property's value when it has no keys, and the range a key's value is held to. */
export const PROP_DEFAULT: Record<KeyProp, number> = { x: 0, y: 0, scale: 1, rotation: 0, opacity: 1, anchorX: 0, anchorY: 0 };
export const PROP_RANGE: Record<KeyProp, [number, number]> = {
  x: [-4, 4], y: [-4, 4], scale: [0, 20], rotation: [-3600, 3600], opacity: [0, 1], anchorX: [-2, 2], anchorY: [-2, 2],
};
/** The longest a key's time may be (seconds) and the most keys one property keeps. */
export const MAX_KEY_T = 86400;
export const MAX_KEYS = 256;

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

// ---- easing ---------------------------------------------------------------------------------------

const BEZIER = /^bezier:\s*(-?[\d.]+(?:e-?\d+)?)\s*,\s*(-?[\d.]+(?:e-?\d+)?)\s*,\s*(-?[\d.]+(?:e-?\d+)?)\s*,\s*(-?[\d.]+(?:e-?\d+)?)\s*$/i;

/** A "bezier:x1,y1,x2,y2" ease's four numbers, or null when it is not one a CSS cubic-bezier allows (x in 0..1). */
export const parseBezier = (e: unknown): [number, number, number, number] | null => {
  if (typeof e !== "string") return null;
  const m = BEZIER.exec(e);
  if (!m) return null;
  const p = m.slice(1, 5).map(Number) as [number, number, number, number];
  if (!p.every((x) => Number.isFinite(x))) return null;
  if (p[0] < 0 || p[0] > 1 || p[2] < 0 || p[2] > 1 || Math.abs(p[1]) > 5 || Math.abs(p[3]) > 5) return null;
  return p;
};

/** True for an ease the renderer knows. */
export const isEase = (e: unknown): e is EaseName =>
  typeof e === "string" && ((EASE_NAMES as string[]).includes(e) || parseBezier(e) !== null);

/**
 * A CSS cubic-bezier(x1, y1, x2, y2) at progress x: the curve's t for x found by Newton's method (falling back
 * to bisection), then its y. Deterministic, accurate to ~1e-7.
 */
export const cubicBezier = (x1: number, y1: number, x2: number, y2: number, x: number): number => {
  if (x <= 0) return 0;
  if (x >= 1) return 1;
  const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
  const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
  const sx = (t: number) => ((ax * t + bx) * t + cx) * t;
  const dx = (t: number) => (3 * ax * t + 2 * bx) * t + cx;
  const sy = (t: number) => ((ay * t + by) * t + cy) * t;
  let t = x;
  for (let i = 0; i < 8; i++) {
    const err = sx(t) - x;
    if (Math.abs(err) < 1e-7) return sy(t);
    const d = dx(t);
    if (Math.abs(d) < 1e-6) break;
    t -= err / d;
  }
  let lo = 0, hi = 1;
  t = x;
  for (let i = 0; i < 60; i++) {
    const v = sx(t);
    if (Math.abs(v - x) < 1e-7) break;
    if (v < x) lo = t; else hi = t;
    t = (lo + hi) / 2;
  }
  return sy(t);
};

/** An ease's progress (0..1 in, usually 0..1 out; backOut and a bezier may overshoot). Unknown = linear. */
export const ease = (e: EaseName | string | undefined, p: number): number => {
  const x = clamp(p, 0, 1);
  switch (e) {
    case "hold": return x >= 1 ? 1 : 0;
    case "easeIn": return x * x * x;
    case "easeOut": return 1 - Math.pow(1 - x, 3);
    case "easeInOut": return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
    case "expoOut": return x >= 1 ? 1 : 1 - Math.pow(2, -10 * x);
    case "backOut": { const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2); }
    default: {
      const b = parseBezier(e);
      return b ? cubicBezier(b[0], b[1], b[2], b[3], x) : x;
    }
  }
};

// ---- cleaning -------------------------------------------------------------------------------------

/** One property's keys: each valid key kept (time >= 0, value in range, a known ease), in time order. */
export const cleanKeys = (raw: unknown, prop: KeyProp): Key[] | null => {
  if (!Array.isArray(raw)) return null;
  const [lo, hi] = PROP_RANGE[prop];
  const out: Key[] = [];
  for (const k of raw) {
    if (!k || typeof k !== "object") continue;
    const t = num((k as Key).t), v = num((k as Key).v);
    if (t === null || v === null) continue;
    const key: Key = { t: clamp(t, 0, MAX_KEY_T), v: clamp(v, lo, hi) };
    const e = (k as Key).e;
    if (isEase(e) && e !== "linear") key.e = e;
    out.push(key);
    if (out.length >= MAX_KEYS) break;
  }
  if (!out.length) return null;
  out.sort((a, b) => a.t - b.t);
  return out;
};

/** A scene's keyframes cleaned (bad keys and unknown properties dropped); null when nothing is left. */
export const cleanKeyframes = (raw: unknown): ClipKeyframes | null => {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const out: ClipKeyframes = {};
  for (const prop of KEY_PROPS) {
    const keys = cleanKeys((raw as Record<string, unknown>)[prop], prop);
    if (keys) out[prop] = keys;
  }
  return Object.keys(out).length ? out : null;
};

// ---- reading -------------------------------------------------------------------------------------

/** A property's value at `t` seconds (keys in time order): eased between keys, held outside them. */
export const valueAt = (keys: Key[] | null | undefined, t: number, fallback = 0): number => {
  if (!keys || !keys.length) return fallback;
  if (t <= keys[0].t) return keys[0].v;
  const last = keys[keys.length - 1];
  if (t >= last.t) return last.v;
  // The last key at or before t (several keys may share one time: the later one wins from that time).
  let i = 1;
  while (i < keys.length && keys[i].t <= t) i++;
  const a = keys[i - 1], b = keys[i];
  const span = b.t - a.t;
  if (span <= 0) return b.v;
  return a.v + (b.v - a.v) * ease(b.e, (t - a.t) / span);
};

export interface ClipTransform { x: number; y: number; scale: number; rotation: number; opacity: number; anchorX: number; anchorY: number }

/** Every property at `t` (an absent property is at its default). */
export const transformAt = (kf: ClipKeyframes | null | undefined, t: number): ClipTransform => {
  const out = { ...PROP_DEFAULT } as ClipTransform;
  if (!kf) return out;
  for (const prop of KEY_PROPS) out[prop] = valueAt(kf[prop], t, PROP_DEFAULT[prop]);
  out.opacity = clamp(out.opacity, 0, 1);
  out.scale = Math.max(0, out.scale);
  return out;
};

/** True when a value changes anywhere (a single key, or keys all the same, never moves). */
export const animates = (keys: Key[] | null | undefined): boolean =>
  !!keys && keys.length > 1 && keys.some((k) => k.v !== keys[0].v);

/**
 * How far each property moved over the last frame (value at t minus value one frame earlier). The motion
 * blur reads it: zero when nothing moves.
 */
export const deltaAt = (kf: ClipKeyframes | null | undefined, t: number, dt: number): ClipTransform => {
  const now = transformAt(kf, t), before = transformAt(kf, Math.max(0, t - dt));
  const out = {} as ClipTransform;
  for (const prop of KEY_PROPS) out[prop] = t - dt < 0 ? 0 : now[prop] - before[prop];
  return out;
};

/** The longest a motion blur streak is held to (pixels at 1080 lines). */
export const MAX_BLUR_PX = 48;

/**
 * The motion blur at `t` (seconds), as a Gaussian's standard deviation along x and y in pixels of a
 * `width` x `height` frame: the per-frame travel times the shutter (0..1; 0.5 = a 180-degree shutter).
 * Position moves streak along their axis; a scale or rotation move adds a smaller blur on both axes (the
 * travel of a point half way out from the centre). A box blur of length L has a deviation of about L / 3.5.
 */
export const motionBlurAt = (kf: ClipKeyframes | null | undefined, t: number, fps: number, width: number,
  height: number, shutter: number): { sx: number; sy: number } => {
  if (!kf || shutter <= 0 || fps <= 0) return { sx: 0, sy: 0 };
  const d = deltaAt(kf, t, 1 / fps);
  const half = Math.min(width, height) / 4;
  const radial = (Math.abs(d.scale) + Math.abs(d.rotation) * Math.PI / 180) * half;
  const lx = Math.abs(d.x) * width + radial;
  const ly = Math.abs(d.y) * height + radial;
  const cap = MAX_BLUR_PX * height / 1080;
  const k = shutter / 3.5;
  const round = (v: number) => Math.round(Math.min(cap, v * k) * 100) / 100;
  const sx = round(lx), sy = round(ly);
  // Under a third of a pixel reads as sharp: no filter at all.
  return { sx: sx < 0.34 ? 0 : sx, sy: sy < 0.34 ? 0 : sy };
};
