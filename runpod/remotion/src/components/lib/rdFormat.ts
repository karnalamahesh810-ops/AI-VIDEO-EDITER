/**
 * Pure helpers for the real data looks (LibRealData.tsx, "rd-"): how a data document's points, values, units,
 * dates and axis years are read and written. No React and no Remotion, so the same code runs in the renderer, the
 * editor's Player and a node test (tests/test_data_graphics.py runs it through esbuild).
 *
 * Only the document's own numbers are written: a missing or non-finite value is left out, never made up.
 */
import type { DataDoc, Overlay } from "../../types";

export interface Pt { t: number; v: number; date: string }

/** The overlay's data document, or null. */
export const dataOf = (ov: Overlay | null | undefined): DataDoc | null => {
  const d = ov && typeof ov === "object" ? ov.data : null;
  return d && typeof d === "object" ? d : null;
};

/** An ISO date ("2026-10-03", or a bare year "2024" as mid-year) as milliseconds; NaN when it is not one. */
export const dayOf = (iso: unknown): number => {
  const s = String(iso ?? "").trim();
  if (/^\d{4}$/.test(s)) return Date.UTC(Number(s), 6, 1);
  // Strict ISO only: the engine's lenient parsing reads "nope-07-01" as a date.
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  return m ? Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : NaN;
};

/** The finite points, oldest first. */
export const seriesOf = (d: DataDoc | null): Pt[] => {
  const out: Pt[] = [];
  for (const p of Array.isArray(d?.points) ? (d as DataDoc).points as unknown[] : []) {
    if (!Array.isArray(p) || p.length < 2) continue;
    const t = dayOf(p[0]);
    const v = Number(p[1]);
    if (Number.isFinite(t) && Number.isFinite(v)) out.push({ t, v, date: String(p[0]) });
  }
  return out.sort((a, b) => a.t - b.t);
};

/** The document's decimals, 0-3 (1 when it gives none). */
export const decimalsOf = (d: DataDoc | null): number => {
  const n = Number(d?.decimals);
  return Number.isFinite(n) ? Math.max(0, Math.min(3, Math.round(n))) : 1;
};

/** "1,037.9", "22.3", "6,580": the value with the document's decimals, grouped. */
export const fmtVal = (v: number, decimals: number): string => (Number.isFinite(v)
  ? v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) : "");

/** A unit as it sits on the digits ("%", "°F") or after them ("FT", "CFS", "MAF"). */
export const unitParts = (unit: unknown): { glued: string; after: string } => {
  const u = String(unit ?? "").trim().toUpperCase().slice(0, 8);
  const glued = u === "%" || u.startsWith("°");
  return { glued: glued ? u : "", after: glued ? "" : u };
};

/** The value with its unit as one string: "1,037.9 FT", "22.3%". */
export const valueText = (v: number, decimals: number, unit: unknown): string => {
  const u = unitParts(unit);
  return `${fmtVal(v, decimals)}${u.glued}${u.after ? ` ${u.after}` : ""}`;
};

/** Round years to label a time axis with (steps of 1, 2, 5, 10, 20, 25, 50), at most `max`, inside the span. */
export const yearTicks = (t0: number, t1: number, max = 6): number[] => {
  const y0 = new Date(t0).getUTCFullYear();
  const y1 = new Date(t1).getUTCFullYear();
  for (const step of [1, 2, 5, 10, 20, 25, 50]) {
    const ys: number[] = [];
    for (let y = Math.ceil(y0 / step) * step; y <= y1; y += step) {
      const t = Date.UTC(y, 0, 1);
      if (t >= t0 && t <= t1) ys.push(y);
    }
    if (ys.length <= max) return ys;
  }
  return [y1];
};

const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

/** A point's date as an axis writes it: "JAN 2001", or "2001" for a yearly series. */
export const periodLabel = (iso: string, step?: string): string => {
  const t = dayOf(iso);
  if (!Number.isFinite(t)) return "";
  const dt = new Date(t);
  return step === "year" ? String(dt.getUTCFullYear()) : `${MONTHS[dt.getUTCMonth()]} ${dt.getUTCFullYear()}`;
};

/** "DATA AS OF OCT 3, 2026" / "DATA THROUGH 2025": the corner's note for the date of the data. */
export const asOfNote = (d: DataDoc | null): string => {
  const label = String(d?.asOfLabel ?? d?.latest?.label ?? "").trim().toUpperCase();
  if (!label) return "";
  return label.startsWith("THROUGH") ? `DATA ${label}` : `DATA AS OF ${label}`;
};

/** At most n characters, cut at a word with an ellipsis. */
export const clipText = (s: unknown, n: number): string => {
  const t = String(s ?? "").replace(/\s+/g, " ").trim();
  return t.length <= n ? t : `${t.slice(0, n - 1).replace(/\s+\S*$/, "")}…`;
};
