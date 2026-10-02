/**
 * The ambience beds' levels (src/ambience.py plans them; Main.tsx plays them):
 * pure arithmetic over the document, so the renderer, the editor's Player and
 * a node test (tests/test_ambience.py) compute the same numbers, and every
 * machine of a split render plays the same sound.
 *
 * A bed's level at a frame: its planned volume (against the voice) times the
 * document's ambience master, never over its ceiling; faded in over its first
 * fadeIn frames and out over its last fadeOut; silent inside its holes
 * (full-screen graphics), ramped over 0.4 s either side; and ducked to `duck`
 * of itself while a word is spoken (speechCurve, eased over 0.2 s).
 */

export type Bed = {
  name: string; startFrame: number; durationInFrames: number; volume: number;
  fadeIn?: number; fadeOut?: number; ceiling?: number; holes?: number[][];
};

export type Ambience = { enabled?: boolean; level?: number; duck?: number; beds?: Bed[] } | null | undefined;

type Words = { scenes: { words?: { start: number; end: number }[] }[]; fps: number; durationInFrames: number };

/** 1 while a word is spoken (0.1 s before it to 0.25 s after), 0 in the pauses, eased over 0.2 s. */
export const speechCurve = (doc: Words): Float32Array => {
  const fps = doc.fps;
  const total = Math.max(1, Math.ceil(doc.durationInFrames));
  const raw = new Float32Array(total + 1);
  for (const sc of doc.scenes) {
    for (const w of sc.words || []) {
      const a = Math.max(0, Math.ceil((w.start - 0.1) * fps));
      const b = Math.min(total, Math.floor((w.end + 0.25) * fps));
      for (let f = a; f <= b; f++) raw[f] = 1;
    }
  }
  const half = Math.max(1, Math.round(fps * 0.1));
  const out = new Float32Array(total + 1);
  let sum = 0;
  for (let f = -half; f <= total + half; f++) {
    sum += (f + half <= total && f + half >= 0 ? raw[f + half] : 0) - (f - half - 1 >= 0 ? raw[f - half - 1] : 0);
    if (f >= 0 && f <= total) out[f] = sum / (2 * half + 1);
  }
  return out;
};

/** The master and duck the document asks for, or null when the beds are off (absent, disabled, muted, level 0). */
export const ambienceSettings = (amb: Ambience, sfxEnabled?: unknown): { master: number; duck: number } | null => {
  if (!amb || typeof amb !== "object" || amb.enabled === false || sfxEnabled === false || !Array.isArray(amb.beds)) return null;
  const master = Math.max(0, Math.min(4, Number(amb.level ?? 1) || 0));
  const duck = Math.max(0, Math.min(1, Number(amb.duck ?? 0.7)));
  return master > 0 && amb.beds.length ? { master, duck } : null;
};

/**
 * How a bed longer than its file is played: one pass of the file after
 * another, each starting `overlap` frames before the last one ends, the
 * two crossfaded at equal power. Not Remotion's own loop: measured on
 * Remotion 4.0.511, a looped MP3 pass starts 16 samples into the file and the
 * next one on the frame boundary, leaving 16 silent samples (a faint tick)
 * at every repeat; under a crossfade any such edge is covered by the
 * incoming pass. `from` is the pass's first frame in the bed; fadeIn /
 * fadeOut are its crossfades (0 at the bed's own ends: the bed's fades
 * apply there). With an unknown file length, one looping pass.
 */
export type BedPass = { from: number; frames: number; fadeIn: number; fadeOut: number; loop: boolean };

export const bedPasses = (bedFrames: number, fileFrames: number, overlap: number): BedPass[] => {
  const total = Math.max(1, Math.round(bedFrames));
  const file = Math.round(fileFrames);
  const ov = Math.max(1, Math.round(overlap));
  if (!(file > 2 * ov)) return [{ from: 0, frames: total, fadeIn: 0, fadeOut: 0, loop: true }];
  const step = file - ov;
  const out: BedPass[] = [];
  for (let from = 0; ; from += step) {
    const last = from + file >= total;
    out.push({ from, frames: last ? total - from : file, fadeIn: from > 0 ? ov : 0, fadeOut: last ? 0 : ov,
      loop: false });
    if (last) break;
  }
  return out;
};

/** A pass's own crossfade gain at frame f of the pass (equal power: the two overlapping passes' squares sum to 1). */
export const passGain = (p: BedPass, f: number): number => {
  let g = 1;
  if (p.fadeIn > 0 && f < p.fadeIn) g *= Math.sin((Math.PI / 2) * Math.max(0, f / p.fadeIn));
  const tail = p.frames - p.fadeOut;
  if (p.fadeOut > 0 && f > tail) g *= Math.cos((Math.PI / 2) * Math.min(1, (f - tail) / p.fadeOut));
  return g;
};

/** A bed's level at frame f of its own timeline (0 = its first frame), or null for a bed that plays nothing. */
export const bedVolume = (b: Bed, fps: number, master: number, duck: number, speech: Float32Array) => {
  const start = Math.round(Number(b.startFrame) || 0);
  const frames = Math.max(1, Math.round(Number(b.durationInFrames) || 0));
  const ceiling = Number(b.ceiling ?? 1);
  const level = Math.min(Number.isFinite(ceiling) ? ceiling : 1, Math.max(0, Number(b.volume) || 0) * master);
  if (!(level > 0) || !b.name) return null;
  const fadeIn = Math.max(1, Math.round(Number(b.fadeIn ?? fps)));
  const fadeOut = Math.max(1, Math.round(Number(b.fadeOut ?? fps * 1.2)));
  const ramp = Math.max(1, Math.round(fps * 0.4));
  const holes = (Array.isArray(b.holes) ? b.holes : []).filter((h) => Array.isArray(h) && h.length === 2)
    .map((h) => [Number(h[0]), Number(h[1])]);
  return (f: number): number => {
    let g = Math.max(0, Math.min(1, f / fadeIn, (frames - f) / fadeOut));
    for (const [a, z] of holes) g *= 1 - Math.max(0, Math.min(1, Math.min(f - (a - ramp), z + ramp - f) / ramp));
    g *= 1 - (1 - duck) * (speech[Math.min(speech.length - 1, Math.max(0, start + Math.round(f)))] || 0);
    return Math.max(0, Math.min(1, level * g));
  };
};
