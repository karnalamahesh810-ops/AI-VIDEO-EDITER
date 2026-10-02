/**
 * The video's grade: one look over every scene's picture (video and photos,
 * never the overlays or text), so clips from a hundred cameras read as one
 * film. src/grade.py writes the document side: doc.grade = {preset,
 * strength, normalize} and each scene's measured tone (scene.media.tone).
 *
 * Pure arithmetic over plain data (no React), so the renderer, the editor's
 * Player and a node test compute the same numbers; everything comes from the
 * document, so every machine of a split render draws the same grade.
 *
 * Per scene, two parts folded into one SVG filter (Grade.tsx): a saturation
 * matrix and one 33-point table per channel, in sRGB.
 *
 *  1. normalize (doc.grade.normalize, scenes with a tone): the scene pulled
 *     part of the way toward the video's own median - exposure by a gamma
 *     (black and white stay put), hazy blacks and dim highlights by a gentle
 *     levels move that never pushes the scene's own darkest 2% under 4%,
 *     saturation, and its colour cast (red and blue against green in the
 *     midtones, gains within 4%, only ever lowering a channel so nothing
 *     clips). A video of red rock stays red: only the clip that stands out
 *     from the rest is moved. Archival and vintage scenes keep their colour.
 *  2. look (doc.grade.preset): a soft S-curve around a pivot whose toe is
 *     lifted and shoulder rolled (blacks are never crushed: black itself
 *     lifts to about 1%, no shadow is pulled down by more than about 1% of
 *     full scale, and the white rolls off to 98.5% instead of clipping), a
 *     tint in the midtones only (black and white stay neutral: no
 *     orange-and-teal), a saturation trim.
 *
 * `strength` (0-1) scales both parts. "none" is no filter at all; "neutral"
 * is the normalizing alone.
 */

/** Must match PRESETS in src/grade.py (a test keeps them equal). */
export const GRADE_PRESETS = ["none", "neutral", "documentary", "warm-doc", "cool-news", "archival"] as const;
export type GradePreset = (typeof GRADE_PRESETS)[number];

/** A scene picture's measured tone (src/grade.py tone_of): sRGB 0-1. */
export interface Tone {
  /** mean luma, its 2nd and 98th percentiles */
  l: number; lo: number; hi: number;
  /** mean chroma (max - min of the channels) */
  s: number;
  /** red and blue against green, in the midtones */
  rg: number; bg: number;
  v?: number;
}

export interface GradeSettings { preset?: string; strength?: number; normalize?: boolean }

export interface GradeMedians { l: number; s: number; rg: number; bg: number; n: number }

interface Look {
  /** output at input 0 and 1: a lifted toe and a rolled shoulder */
  lift: number; gain: number;
  /** the S-curve's pivot and its slope there (1 = none, under 1 flattens) */
  pivot: number; contrast: number;
  sat: number;
  /** red, green, blue in the midtones only (1 = neutral) */
  tint: [number, number, number];
}

export const LOOKS: Record<GradePreset, Look | null> = {
  none: null,
  neutral: { lift: 0, gain: 1, pivot: 0.45, contrast: 1, sat: 1, tint: [1, 1, 1] },
  // The default: a touch of contrast and a filmic toe and shoulder, colour a
  // shade restrained, the faintest warmth in the midtones.
  documentary: { lift: 0.012, gain: 0.985, pivot: 0.42, contrast: 1.12, sat: 0.97, tint: [1.008, 1, 0.99] },
  "warm-doc": { lift: 0.012, gain: 0.985, pivot: 0.42, contrast: 1.1, sat: 1.0, tint: [1.022, 1.004, 0.97] },
  "cool-news": { lift: 0.008, gain: 0.99, pivot: 0.45, contrast: 1.15, sat: 0.98, tint: [0.988, 1.0, 1.018] },
  // Faded print: lifted blacks, lowered whites, less contrast, half the colour, a warm cast.
  archival: { lift: 0.045, gain: 0.93, pivot: 0.45, contrast: 0.92, sat: 0.72, tint: [1.03, 1.0, 0.945] },
};

export const TABLE_SIZE = 33;

/** One scene's filter: the saturation and the three channel tables (0-1). */
export interface SceneGrade { sat: number; r: number[]; g: number[]; b: number[] }

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/**
 * A contrast curve through (0,0), (pivot,pivot) and (1,1) with slope
 * `contrast` at the pivot: two power curves meeting there (smooth, monotonic).
 */
export const sCurve = (x: number, pivot: number, contrast: number): number => {
  const v = clamp(x, 0, 1);
  if (contrast === 1) return v;
  if (v <= pivot) return pivot * Math.pow(v / pivot, contrast);
  return 1 - (1 - pivot) * Math.pow((1 - v) / (1 - pivot), contrast);
};

/** The look's tone curve at `strength` (no tint). */
export const lookCurve = (y: number, look: Look, strength: number): number => {
  const full = look.lift + (look.gain - look.lift) * sCurve(y, look.pivot, look.contrast);
  return y + strength * (full - y);
};

export const validTone = (t: unknown): t is Tone => {
  const o = t as Tone | null;
  return !!o && typeof o === "object" && [o.l, o.lo, o.hi, o.s, o.rg, o.bg].every(finite)
    && o.l > 0 && o.l < 1 && o.rg > 0 && o.bg > 0;
};

type GradedScene = { treatment?: string; media?: { type?: string; tone?: unknown } | null };

const KEEPS_COLOUR = new Set(["archival", "vintage"]);

const median = (xs: number[]) => {
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};

const r4 = (v: number) => Math.round(v * 10000) / 10000;

/**
 * The video's common tone: the median of its colour scenes' tones (null under
 * 3 such scenes). src/grade.py medians() is its twin: the worker freezes the
 * result in doc.grade.medians.
 */
export const gradeMedians = (scenes: GradedScene[]): GradeMedians | null => {
  const tones = scenes
    .filter((sc) => !KEEPS_COLOUR.has(String(sc.treatment || "")) && (sc.media?.type === "video" || sc.media?.type === "image"))
    .map((sc) => sc.media?.tone)
    .filter(validTone)
    .filter((t) => t.s >= 0.04);
  if (tones.length < 3) return null;
  return { l: r4(median(tones.map((t) => t.l))), s: r4(median(tones.map((t) => t.s))),
    rg: r4(median(tones.map((t) => t.rg))), bg: r4(median(tones.map((t) => t.bg))), n: tones.length };
};

export const validMedians = (m: unknown): m is GradeMedians => {
  const o = m as GradeMedians | null;
  return !!o && typeof o === "object" && [o.l, o.s, o.rg, o.bg].every(finite) && o.l > 0 && o.l < 1
    && o.rg > 0 && o.bg > 0;
};

export const presetOf = (settings: GradeSettings | null | undefined): GradePreset | null => {
  if (!settings || typeof settings !== "object") return null;
  const p = String(settings.preset || "documentary").toLowerCase();
  return (GRADE_PRESETS as readonly string[]).includes(p) ? (p as GradePreset) : "documentary";
};

export const strengthOf = (settings: GradeSettings | null | undefined): number => {
  const s = Number(settings?.strength ?? 1);
  return Number.isFinite(s) ? clamp(s, 0, 1) : 1;
};

/** The scene's own correction toward the video's median: levels, gamma, saturation, channel gains. */
export const normalizeFor = (tone: Tone, medians: GradeMedians, strength: number, keepColour: boolean) => {
  const k = strength;
  // Hazy blacks and dim highlights, a part of the way, never past the
  // scene's own darkest 2% landing at 4%.
  let bp = 0, wp = 1;
  if (tone.lo > 0.08) bp = clamp((tone.lo - 0.05) * 0.5 * k, 0, 0.06);
  if (tone.hi < 0.88 && tone.hi > tone.lo + 0.2) wp = 1 - clamp((0.88 - tone.hi) * 0.5 * k, 0, 0.08);
  if (bp > 0 && (tone.lo - bp) / (wp - bp) < 0.04) bp = Math.max(0, (tone.lo - 0.04 * wp) / 0.96);
  // Exposure: a gamma that moves the mean part of the way toward the
  // median (itself pulled a little toward a documentary middle grey).
  const l = clamp((tone.l - bp) / (wp - bp), 0.02, 0.98);
  const target = clamp(medians.l + (0.44 - medians.l) * 0.3, 0.34, 0.52);
  let gamma = 1;
  if (tone.l > 0.04 && tone.l < 0.96) {
    const full = Math.log(target) / Math.log(l);
    gamma = Math.exp(Math.log(full) * 0.6 * k);
    gamma = clamp(gamma, tone.l < 0.12 ? 0.88 : 0.8, tone.l > 0.7 ? 1.15 : 1.25);
  }
  let sat = 1, gr = 1, gb = 1;
  if (!keepColour && tone.s >= 0.04 && medians.s >= 0.04) {
    sat = clamp(Math.exp(Math.log(medians.s / tone.s) * 0.5 * k), 0.85, 1.18);
    gr = clamp(Math.exp(Math.log(medians.rg / tone.rg) * 0.5 * k), 0.96, 1.04);
    gb = clamp(Math.exp(Math.log(medians.bg / tone.bg) * 0.5 * k), 0.96, 1.04);
  }
  // Only ever lower a channel: a gain over 1 would clip its highlights.
  const top = Math.max(gr, 1, gb);
  return { bp, wp, gamma, sat, gains: [gr / top, 1 / top, gb / top] as [number, number, number] };
};

/**
 * The scene's filter, or null when it would change nothing (no grade, "none",
 * strength 0, or "neutral" with nothing to correct).
 */
export const sceneGrade = (scene: GradedScene, settings: GradeSettings | null | undefined,
  medians: GradeMedians | null): SceneGrade | null => {
  const preset = presetOf(settings);
  const look = preset ? LOOKS[preset] : null;
  const strength = strengthOf(settings);
  if (!look || strength <= 0) return null;
  const type = scene.media?.type;
  if (type !== "video" && type !== "image") return null;
  const tone = scene.media?.tone;
  const keepColour = KEEPS_COLOUR.has(String(scene.treatment || ""));
  const norm = settings?.normalize !== false && medians && validTone(tone)
    ? normalizeFor(tone, medians, strength, keepColour) : null;
  const bp = norm?.bp ?? 0, wp = norm?.wp ?? 1, gamma = norm?.gamma ?? 1;
  const gains = norm?.gains ?? [1, 1, 1];
  const tint = look.tint.map((t) => 1 + strength * (t - 1));
  const tables: number[][] = [[], [], []];
  for (let i = 0; i < TABLE_SIZE; i++) {
    const x = i / (TABLE_SIZE - 1);
    for (let c = 0; c < 3; c++) {
      let y = clamp((x * gains[c] - bp) / (wp - bp), 0, 1);
      y = Math.pow(y, gamma);
      y = lookCurve(y, look, strength);
      // A tint in the midtones only: nothing at black or white.
      y += (tint[c] - 1) * 4 * y * (1 - y) * 0.5;
      tables[c].push(Math.round(clamp(y, 0, 1) * 10000) / 10000);
    }
  }
  const sat = Math.round((norm?.sat ?? 1) * (1 + strength * (look.sat - 1)) * 10000) / 10000;
  const identity = sat === 1 && tables.every((t) => t.every((v, i) => Math.abs(v - i / (TABLE_SIZE - 1)) < 1e-4));
  return identity ? null : { sat, r: tables[0], g: tables[1], b: tables[2] };
};
