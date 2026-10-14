/**
 * Where a clip plays from and how fast: the editor's slip, split, roll and speed (the pro editor, 2026-10-09).
 *
 * Pure arithmetic over plain data, so the renderer (SceneClip, the picture-in-picture layers), the editor's
 * Player and the worker's quality check (src/cliptime.py, the same rules in Python; a test runs both) agree
 * on every frame. Nothing here is set on a document the editor never touched: such a clip plays exactly as
 * before - from its first frame, slowed just enough to fill a scene it is shorter than (never under 0.6x).
 *
 * The fields (all optional):
 *   media.trimStart  seconds into the clip file the scene starts at (slip; the second half of a split)
 *   speed            a constant speed, 0.1-8 (1 = as shot)
 *   speedRamp        [{ t, v }]: the speed v at t seconds from the clip's start, straight lines between
 *                    (slow motion into a moment and back, a speed-up); before the first key its value,
 *                    after the last one its value
 * An edited clip that runs out of picture is slowed just enough to reach the end of its scene (never frozen).
 */

/** The slowest an unedited clip is slowed to fill its scene (src/quality.py MIN_RATE). */
export const MIN_FILL_RATE = 0.6;
export const MIN_SPEED = 0.1;
export const MAX_SPEED = 8;
/** No stretch plays slower than this (a browser's video element refuses rates under 1/16). */
export const MIN_PLAY_RATE = 0.0625;

export interface SpeedKey { t: number; v: number }

/** What a clip's timing is read from: the media's length and in-point, the scene's (or layer's) speed. */
export interface ClipTiming {
  clipSeconds?: number | null;
  trimStart?: number | null;
  speed?: number | null;
  speedRamp?: SpeedKey[] | null;
}

/** One stretch of a clip at one speed: the first frame of the scene it covers, its length, its rate and the source frame it starts on. */
export interface ClipSegment {
  from: number;
  frames: number;
  rate: number;
  /** The clip's frame (counted at the document's frame rate) the stretch starts on; 0 = the file's first. */
  trimBefore: number;
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/** The in-point in seconds (0 when unset or invalid). */
export const trimStartOf = (media: { trimStart?: unknown } | null | undefined): number => {
  const t = num(media?.trimStart);
  return t !== null && t > 0 ? t : 0;
};

/** A constant speed set on the clip (1 when unset or invalid). */
export const speedOf = (clip: { speed?: unknown } | null | undefined): number => {
  const s = num(clip?.speed);
  return s !== null && s > 0 ? clamp(s, MIN_SPEED, MAX_SPEED) : 1;
};

/** A speed ramp's keys, in order, each speed kept in range; null without at least one valid key. */
export const rampOf = (clip: { speedRamp?: unknown } | null | undefined): SpeedKey[] | null => {
  const raw = clip?.speedRamp;
  if (!Array.isArray(raw)) return null;
  const keys: SpeedKey[] = [];
  for (const k of raw) {
    const t = num((k as SpeedKey | null)?.t), v = num((k as SpeedKey | null)?.v);
    if (t === null || v === null || v <= 0) continue;
    keys.push({ t: Math.max(0, t), v: clamp(v, MIN_SPEED, MAX_SPEED) });
  }
  if (!keys.length) return null;
  keys.sort((a, b) => a.t - b.t);
  return keys;
};

/** A ramp's speed at `t` seconds: straight lines between its keys, held before the first and after the last. */
export const rampAt = (keys: SpeedKey[], t: number): number => {
  if (t <= keys[0].t) return keys[0].v;
  const last = keys[keys.length - 1];
  if (t >= last.t) return last.v;
  for (let i = 1; i < keys.length; i++) {
    const b = keys[i];
    if (t <= b.t) {
      const a = keys[i - 1];
      const span = b.t - a.t;
      return span > 0 ? a.v + ((b.v - a.v) * (t - a.t)) / span : b.v;
    }
  }
  return last.v;
};

/** True when the editor changed how this clip plays (an in-point, a speed or a ramp). */
export const isEditedTiming = (t: ClipTiming): boolean =>
  trimStartOf(t) > 0 || speedOf(t) !== 1 || rampOf(t) !== null;

/**
 * The rate an unedited clip plays at (SceneClip before the pro editor): slowed to fill a scene it is shorter
 * than, never under MIN_FILL_RATE.
 */
export const fillRate = (clipSeconds: number, sceneSeconds: number): number =>
  clipSeconds > 0 && clipSeconds < sceneSeconds ? Math.max(MIN_FILL_RATE, clipSeconds / sceneSeconds) : 1;

/** Frames of the ramp's stretches: a new stretch at most every sixth of a second (a speed change reads smooth). */
const rampStep = (fps: number) => Math.max(1, Math.round(fps / 6));

/**
 * How a clip covers `frames` frames of its scene: one stretch for a constant speed, several for a ramp.
 * Stretches tile the scene and each starts on the source frame the one before ended on.
 */
export const clipPlan = (timing: ClipTiming, frames: number, fps: number): ClipSegment[] => {
  const n = Math.max(1, Math.round(frames));
  const f = fps > 0 ? fps : 30;
  const need = n / f;
  const clip = Math.max(0, num(timing.clipSeconds) ?? 0);
  if (!isEditedTiming(timing)) return [{ from: 0, frames: n, rate: fillRate(clip, need), trimBefore: 0 }];

  // The in-point: never past the clip's last frame.
  let trim = trimStartOf(timing);
  if (clip > 0) trim = Math.min(trim, Math.max(0, clip - 1 / f));
  const start = Math.round(trim * f);
  const avail = clip > 0 ? Math.max(0, clip - start / f) : 0;
  const ramp = rampOf(timing);

  if (!ramp) {
    const s = speedOf(timing);
    // Slowed just enough to reach the scene's end when the picture would run out.
    const rate = avail > 0 && need * s > avail ? Math.max(MIN_PLAY_RATE, avail / need) : s;
    return [{ from: 0, frames: n, rate, trimBefore: start }];
  }

  // A ramp: the speed at the middle of each frame, scaled down together when the picture would run out.
  const v = new Float64Array(n);
  let total = 0;
  for (let i = 0; i < n; i++) { v[i] = rampAt(ramp, (i + 0.5) / f); total += v[i]; }
  const fit = avail > 0 && total / f > avail ? (avail * f) / total : 1;
  const pos = new Float64Array(n + 1);
  pos[0] = start;
  for (let i = 0; i < n; i++) pos[i + 1] = pos[i] + v[i] * fit;

  const step = rampStep(f);
  const out: ClipSegment[] = [];
  let first = pos[0];
  for (let a = 0; a < n; a += step) {
    const b = Math.min(n, a + step);
    const rate = Math.max(MIN_PLAY_RATE, (pos[b] - pos[a]) / (b - a));
    const prev = out[out.length - 1];
    // A steady stretch (the same speed as the one before, within half a percent) joins it.
    if (prev && Math.abs(prev.rate - rate) <= prev.rate * 0.005) {
      prev.frames += b - a;
      prev.rate = Math.max(MIN_PLAY_RATE, (pos[b] - first) / prev.frames);
      continue;
    }
    first = pos[a];
    out.push({ from: a, frames: b - a, rate, trimBefore: Math.round(pos[a]) });
  }
  return out;
};

/** Seconds of the clip file a plan shows (the in-point to where its last stretch ends). */
export const planSourceSeconds = (plan: ClipSegment[], fps: number): number => {
  if (!plan.length) return 0;
  const last = plan[plan.length - 1];
  return (last.trimBefore + last.rate * last.frames - plan[0].trimBefore) / (fps > 0 ? fps : 30);
};

/** The clip's own second shown on the scene's frame `frame` (where the playhead is in the file). */
export const sourceSecondAt = (plan: ClipSegment[], frame: number, fps: number): number => {
  const f = fps > 0 ? fps : 30;
  let seg = plan[0];
  for (const s of plan) if (frame >= s.from) seg = s;
  if (!seg) return 0;
  return (seg.trimBefore + Math.max(0, frame - seg.from) * seg.rate) / f;
};
