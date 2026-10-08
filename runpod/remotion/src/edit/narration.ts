/**
 * The narration after the editor's ripple deletes (the pro editor, 2026-10-09).
 *
 * doc.audio.keep lists the stretches of the narration file the video keeps, in order, as [start, end] seconds
 * of the file: [[0, 41.2], [44.9, 612.0]] plays the file's first 41.2 s and then, straight after, from 44.9 s
 * on - the 3.7 s between were deleted with the clips that showed them, and everything after moved up. Absent
 * (every document before the pro editor): the file plays whole from frame 0, exactly as before.
 *
 * Pure arithmetic, read by Main (the narration's pieces), the editor's Player and its waveform, and the
 * editor's cut (lib/proEdit). Word times in the document are always the video's own (after the cuts).
 */

export type KeepRange = [number, number];

/** One piece of the narration on the video: from frame `from`, `frames` long, starting at the file's frame `trimBefore`. */
export interface AudioPiece { from: number; frames: number; trimBefore: number }

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** The kept stretches, cleaned (each at least 1 ms, none before the file's start); null = the whole file. */
export const keepRanges = (audio: { keep?: unknown } | null | undefined): KeepRange[] | null => {
  const raw = audio?.keep;
  if (!Array.isArray(raw)) return null;
  const out: KeepRange[] = [];
  for (const r of raw) {
    if (!Array.isArray(r) || r.length < 2) continue;
    const a = num(r[0]), b = num(r[1]);
    if (a === null || b === null) continue;
    const s = Math.max(0, a);
    if (b - s >= 0.001) out.push([s, b]);
  }
  return out.length ? out : null;
};

/** Seconds of the video the kept stretches fill. */
export const keptSeconds = (keep: KeepRange[]): number => keep.reduce((sum, [a, b]) => sum + (b - a), 0);

/**
 * The narration's pieces on the video's frames (null = the whole file from frame 0). Each piece starts where
 * the one before ended (frames rounded on the running total, so rounding never adds up); none runs past
 * `totalFrames`.
 */
export const narrationPieces = (keep: KeepRange[] | null, fps: number, totalFrames: number): AudioPiece[] | null => {
  if (!keep) return null;
  const f = fps > 0 ? fps : 30;
  const out: AudioPiece[] = [];
  let cum = 0;
  for (const [a, b] of keep) {
    const from = Math.round(cum * f);
    cum += b - a;
    const to = Math.min(Math.max(1, Math.round(totalFrames)), Math.round(cum * f));
    if (to - from >= 1) out.push({ from, frames: to - from, trimBefore: Math.round(a * f) });
    if (to >= totalFrames) break;
  }
  return out;
};

/** The file's second heard at the video's second `t` (the same second when nothing was cut). */
export const programToSource = (keep: KeepRange[] | null, t: number): number => {
  if (!keep) return t;
  let cum = 0;
  for (const [a, b] of keep) {
    const len = b - a;
    if (t < cum + len) return a + Math.max(0, t - cum);
    cum += len;
  }
  const last = keep[keep.length - 1];
  return last ? last[1] + (t - cum) : t;
};

/** The video's second where the file's second `s` is heard; null when it was cut. */
export const sourceToProgram = (keep: KeepRange[] | null, s: number): number | null => {
  if (!keep) return s;
  let cum = 0;
  for (const [a, b] of keep) {
    if (s >= a && s < b) return cum + (s - a);
    cum += b - a;
  }
  return null;
};

/**
 * The kept stretches after the video's seconds [from, to) are deleted (a ripple delete): the narration heard
 * there is gone and what followed plays right after `from`. `total` is the video's length in seconds (the
 * whole file when nothing was cut before).
 */
export const cutProgram = (keep: KeepRange[] | null, from: number, to: number, total: number): KeepRange[] => {
  const ranges: KeepRange[] = keep ? keep.map(([a, b]) => [a, b] as KeepRange) : [[0, Math.max(0, total)]];
  if (!(to > from)) return ranges;
  const out: KeepRange[] = [];
  let cum = 0;
  for (const [a, b] of ranges) {
    const p0 = cum, p1 = cum + (b - a);
    cum = p1;
    // The part of this stretch before the cut, and the part after it.
    if (from > p0) out.push([a, a + (Math.min(from, p1) - p0)]);
    if (to < p1) out.push([a + (Math.max(to, p0) - p0), b]);
  }
  // Two pieces that meet again in the file (a cut undone by hand) become one.
  const merged: KeepRange[] = [];
  for (const r of out) {
    if (r[1] - r[0] < 1e-6) continue;
    const prev = merged[merged.length - 1];
    if (prev && Math.abs(prev[1] - r[0]) < 1e-6) prev[1] = r[1];
    else merged.push([r[0], r[1]]);
  }
  return merged;
};
