/**
 * One motion language for every look (the owner, 2026-10-05: "the other
 * overlay animations are also not smooth - make them smoother and better",
 * "Adobe After Effects kind of thing").
 *
 * Rules every look follows through these helpers:
 *  - entries 10-18 frames at 30 fps on expo / cubic / back curves, never a
 *    linear move and never a first frame that is already most of the look;
 *  - a gentle idle (a slow eased drift, never a per-frame random);
 *  - exits that mirror the entry over 10-14 frames, eased in;
 *  - every duration is written in 30 fps frames and scaled by S = fps / 30,
 *    so a look moves the same in seconds at 30 and at 60 fps.
 */

export const clamp01 = (x: number): number => (x < 0 ? 0 : x > 1 ? 1 : x);
export const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;

// ------------------------------------------------------------------ curves
export const linear = (t: number) => clamp01(t);
export const cubicOut = (t: number) => 1 - (1 - clamp01(t)) ** 3;
export const cubicIn = (t: number) => clamp01(t) ** 3;
export const cubicInOut = (t: number) => {
  const x = clamp01(t);
  return x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2;
};
export const quartOut = (t: number) => 1 - (1 - clamp01(t)) ** 4;
export const quintOut = (t: number) => 1 - (1 - clamp01(t)) ** 5;
export const expoOut = (t: number) => {
  const x = clamp01(t);
  return x >= 1 ? 1 : 1 - 2 ** (-10 * x);
};
export const expoIn = (t: number) => {
  const x = clamp01(t);
  return x <= 0 ? 0 : 2 ** (10 * x - 10);
};
export const expoInOut = (t: number) => {
  const x = clamp01(t);
  if (x <= 0 || x >= 1) return x;
  return x < 0.5 ? 2 ** (20 * x - 10) / 2 : (2 - 2 ** (-20 * x + 10)) / 2;
};
export const sineInOut = (t: number) => -(Math.cos(Math.PI * clamp01(t)) - 1) / 2;
/** Ease-out with a small overshoot (s 1.0 ~ 8 %, 1.7 ~ 10 %): a settle, never a bounce. */
export const backOut = (t: number, s = 1.15) => {
  const x = clamp01(t) - 1;
  return 1 + (s + 1) * x * x * x + s * x * x;
};

/**
 * Progress 0..1 of a move that starts `at` (30 fps frames) and lasts `len`
 * (30 fps frames), on curve `ease`, at the composition's real rate (S = fps / 30).
 */
export const prog = (f: number, at: number, len: number, S = 1, ease: (t: number) => number = expoOut) =>
  ease(clamp01((f - at * S) / Math.max(1, len * S)));

/**
 * The exit, 0 while the look holds and 1 on its last frame: `len` 30-fps
 * frames before the end (never more than a third of the look), eased in so
 * it leaves softly and quickly.
 */
export const exitProg = (f: number, dur: number, len = 12, S = 1, ease: (t: number) => number = cubicIn) => {
  const n = Math.max(2, Math.min(Math.round(len * S), Math.floor(dur / 3)));
  return ease(clamp01((f - (dur - n)) / n));
};

/** Staggered progress for item `i` of a group: each starts `gap` frames after the one before. */
export const stagger = (f: number, at: number, i: number, gap: number, len: number, S = 1,
  ease: (t: number) => number = expoOut) => prog(f, at + i * gap, len, S, ease);

/**
 * A gentle idle: a slow eased drift from 0 to 1 over the hold (no jitter, no
 * loop), for a parallax push or a creep of a few pixels.
 */
export const idle = (f: number, from: number, to: number) =>
  sineInOut(clamp01((f - from) / Math.max(1, to - from)));

/**
 * Simulated motion blur for a fast move: px of blur for a speed of `v` px per
 * frame (30 fps), capped; nothing for a slow move.
 */
export const motionBlur = (v: number, k = 1, cap = 6) => {
  const a = Math.abs(v);
  return a < 2 * k ? 0 : Math.min(cap * k, (a - 2 * k) * 0.35);
};

/** The speed (px a 30-fps frame) of x(f) at frame f, measured over one frame. */
export const speedOf = (x: (f: number) => number, f: number, S = 1) => (x(f + S) - x(f)) / 1;
