/**
 * How the nx- number looks and the tx- text looks write a figure (the owner's
 * rules: numbers always in digits, the unit as it was said, nothing the
 * narration did not say). Pure string and number work - no React, no
 * Remotion - so tests/test_number_text_looks.py runs it in node:
 *
 *   figureOf({value: 4200000000, prefix: "$"})       $ 4.2 BILLION
 *   figureOf({value: 3517, suffix: "FT"})             3,517 FT
 *   figureOf({value: 22, suffix: "%"})                22 %
 *   figureOf({text: "forty million people"})          40 MILLION, label PEOPLE
 *   fmt(1963.0, 0, true)                              "1963" (a year is never grouped)
 *
 * Units as the planner writes them (src/treatments.py _UNIT_SHORT: FT, MI, IN,
 * ACRE-FT, GAL, USD, SQ MI, %, °...) are spelled the way a viewer reads them
 * (MILES, INCHES, ACRE-FEET, GALLONS, $); a scale word (MILLION, BILLION)
 * stays a word beside the figure.
 */
import { spokenToDigits } from "./numWords";

export type Unit = {
  /** Before the figure at its cap top: "$". */
  pre: string;
  /** After the figure at its cap top: "%", "°F", "°C", "°". */
  top: string;
  /** A unit word beside the figure: FT, MILES, MPH, ACRE-FEET. */
  tag: string;
  /** A scale word beside the figure: THOUSAND, MILLION, BILLION, TRILLION. */
  scale: string;
};
export const NO_UNIT: Unit = { pre: "", top: "", tag: "", scale: "" };
export const SCALE_X: Record<string, number> = { THOUSAND: 1e3, MILLION: 1e6, BILLION: 1e9, TRILLION: 1e12 };
const SCALE_LETTER: Record<string, string> = { K: "THOUSAND", M: "MILLION", MN: "MILLION", B: "BILLION", BN: "BILLION",
  T: "TRILLION" };

export const str = (v: unknown): string =>
  (typeof v === "string" ? v : typeof v === "number" && Number.isFinite(v) ? String(v) : "")
    .replace(/[‘’`]/g, "'").replace(/[“”]/g, "\"").replace(/\s+/g, " ").trim();

/** Spoken numbers in digits ("forty million" -> "40 million"), never throwing. */
export const digits = (s: string): string => {
  try {
    return spokenToDigits(s).replace(/\s+/g, " ").trim();
  } catch {
    return s;
  }
};

export const numOf = (v: unknown): number | null => {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string" && /^\s*[-−]?[\d,]*\.?\d+\s*$/.test(v)) {
    const n = Number(v.replace(/[,\s]/g, "").replace("−", "-"));
    return Number.isFinite(n) ? n : null;
  }
  return null;
};

const ENDS = /^[\s,.:;·\-–—&]+|[\s,.:;·\-–—&]+$/g;
export const trimEnds = (s: string): string => s.replace(/\s+/g, " ").replace(ENDS, "").trim();

const SMALL_TAIL = /[\s,;:\-–—·]+(?:the|a|an|of|in|at|on|and|or|to|for|by|with|from|its|their|is|was|are|were)?$/i;
/** At most n characters, cut at a word, never ending on a dangling small word or a comma. */
export const clip = (s: string, n: number): string => {
  if (s.length <= n) return s;
  let c = s.slice(0, n).replace(/\s+\S*$/, "").trim();
  for (let i = 0; i < 4 && SMALL_TAIL.test(c); i++) c = c.replace(SMALL_TAIL, "").trim();
  return c || s.slice(0, n);
};

/** A unit as the looks write it: a sign at the cap top (%, °F), a word beside (FT, MILES), a scale (BILLION), a $ before. */
export const unitOf = (raw: string, money = false): Unit => {
  const u = raw.toUpperCase().replace(/\s+/g, " ").replace(/\.$/, "").trim();
  if (!u) return NO_UNIT;
  if (u === "%" || /^PER ?CENT$|^PCT$/.test(u)) return { ...NO_UNIT, top: "%" };
  if (/^°\s?F$|^DEGREES? (F|FAHRENHEIT)$|^FAHRENHEIT$/.test(u)) return { ...NO_UNIT, top: "°F" };
  if (/^°\s?C$|^DEGREES? (C|CELSIUS)$|^CELSIUS$/.test(u)) return { ...NO_UNIT, top: "°C" };
  if (u === "°" || /^DEGREES?$/.test(u)) return { ...NO_UNIT, top: "°" };
  if (/^(USD|DOLLARS?|\$)$/.test(u)) return { ...NO_UNIT, pre: "$" };
  if (SCALE_X[u]) return { ...NO_UNIT, scale: u };
  if (money && SCALE_LETTER[u]) return { ...NO_UNIT, scale: SCALE_LETTER[u] };
  if (/^(FT|FEET|FOOT)$/.test(u)) return { ...NO_UNIT, tag: "FT" };
  if (/^(IN|INCH|INCHES|")$/.test(u)) return { ...NO_UNIT, tag: "INCHES" };
  if (/^(MI|MILE|MILES)$/.test(u)) return { ...NO_UNIT, tag: "MILES" };
  if (/^(M|METERS?|METRES?)$/.test(u)) return { ...NO_UNIT, tag: "METERS" };
  if (/^(KM|KILOMET(?:ER|RE)S?)$/.test(u)) return { ...NO_UNIT, tag: "KM" };
  if (/^(MPH|MILES (PER|AN) HOUR)$/.test(u)) return { ...NO_UNIT, tag: "MPH" };
  if (/^(KM\/?H|KPH|KMH)$/.test(u)) return { ...NO_UNIT, tag: "KM/H" };
  if (/^(ACRE[- ]?F(?:EE)?T|ACRE[- ]FOOT|AF|MAF)$/.test(u)) return { ...NO_UNIT, tag: "ACRE-FEET" };
  if (/^(GAL|GALLONS?)$/.test(u)) return { ...NO_UNIT, tag: "GALLONS" };
  if (/^(SQ ?MI|SQUARE MILES?)$/.test(u)) return { ...NO_UNIT, tag: "SQ MILES" };
  return { ...NO_UNIT, tag: u.slice(0, 12) };
};
export const mergeUnit = (mine: Unit, said: Unit): Unit => ({
  pre: mine.pre || said.pre, top: mine.top || said.top, tag: mine.tag || said.tag, scale: mine.scale || said.scale,
});

/** A number in the words with a $ before it and its unit after it. */
export const NUM_RX = /(\$|#)?((?:(?<![A-Z0-9])-)?\d[\d,]*(?:\.\d+)?)(?:(K|M|MN|B|BN)\b|\s?(%|°\s?[FC]?(?![A-Z])|PER ?CENT\b|DEGREES?(?:\s(?:F|C|FAHRENHEIT|CELSIUS)\b)?|FEET\b|FOOT\b|FT\b|INCHES\b|INCH\b|MILES\b|MILE\b|MPH\b|ACRE[- ]FEET\b|GALLONS\b|THOUSAND\b|MILLION\b|BILLION\b|TRILLION\b))?/;

export type Fig = {
  value: number | null;
  decimals: number;
  unit: Unit;
  /** What the figure counts (caps), the number taken out of the words. */
  label: string;
  /** A second line: the subtitle, or the label field when it is not the planner's "up" / "down". */
  extra: string;
  /** The words as given (spoken numbers in digits), in their own case. */
  words: string;
};

export const decimalsOf = (raw: string): number => Math.min(2, ((raw.split(".")[1] || "").replace(/0+$/, "")).length);
const cutOut = (s: string, a: number, b: number) => trimEnds(`${s.slice(0, a)} ${s.slice(b)}`);

/** The figure of an overlay: its value, how it is written and what it counts (all of it said). */
export const figureOf = (ov: { value?: unknown; prefix?: unknown; suffix?: unknown; text?: unknown; subtitle?: unknown;
  label?: unknown }, money = false): Fig => {
  const words = digits(str(ov.text));
  const up = words.toUpperCase();
  let value = numOf(ov.value);
  let decimals = value === null ? 0 : decimalsOf(String(value));
  const pre0 = str(ov.prefix).slice(0, 2);
  let unit = unitOf(str(ov.suffix), money || pre0 === "$");
  if (pre0 === "$") unit = { ...unit, pre: "$" };
  let label = up;
  const m = NUM_RX.exec(up);
  if (m) {
    const n = Number(m[2].replace(/,/g, ""));
    const said = unitOf(m[3] || m[4] || "", money || m[1] === "$" || unit.pre === "$");
    const sign: Unit = { ...said, pre: said.pre || (m[1] === "$" ? "$" : "") };
    if (Number.isFinite(n)) {
      const scaled = said.scale ? n * SCALE_X[said.scale] : n;
      const same = value !== null && (Math.abs(n - value) < 1e-9 || Math.abs(scaled - value) <= 1e-6 * Math.max(1, Math.abs(value)));
      if (value === null) {
        value = n;
        decimals = decimalsOf(m[2]);
      }
      if (value === n || same) {
        unit = mergeUnit(unit, sign);
        label = cutOut(up, m.index, m.index + m[0].length);
      }
    }
  }
  const lab = str(ov.label).toUpperCase();
  const extra = trimEnds(digits(str(ov.subtitle) || (/^(UP|DOWN)$/.test(lab) ? "" : lab)).toUpperCase());
  const lbl = trimEnds(label);
  return { value, decimals, unit, label: clip(lbl, 48), extra: extra === lbl ? "" : clip(extra, 48), words };
};

const group = (w: string) => w.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
/** 90000 -> "90,000", 8.9 -> "8.9", 1.20 -> "1.2"; `year` keeps 1963 whole ("1963", never "1,963"). */
export const fmt = (v: number, decimals: number, year = false): string => {
  const d = Math.max(0, Math.min(2, decimals));
  const fixed = Math.abs(v).toFixed(d);
  const [w, f] = fixed.split(".");
  const frac = f ? f.replace(/0+$/, "") : "";
  return `${v < 0 ? "-" : ""}${year ? w : group(w)}${frac ? `.${frac}` : ""}`;
};
/** Up to two decimals, the trailing zeros dropped. */
export const decimalsFor = (v: number): number => decimalsOf((Math.round(Math.abs(v) * 100) / 100).toFixed(2));
/** A whole number between 1500 and 2100 with no unit: a year. */
export const isYear = (v: number, unit: Unit): boolean =>
  Number.isInteger(v) && v >= 1500 && v <= 2100 && !unit.pre && !unit.top && !unit.tag && !unit.scale;

/** A figure as it is drawn: its text, the $ before it, a sign after it, its unit word (scale first). */
export type Drawn = { fig: string; value: number; decimals: number; pre: string; top: string; tag: string; year: boolean };

/**
 * The figure drawn in digits: money of a million or more is scaled into its
 * word ($4,200,000,000 -> $4.2 BILLION), a figure already scaled keeps its
 * word, a year is never grouped.
 */
export const drawnOf = (f: Fig, money = false): Drawn => {
  let value = f.value ?? 0;
  let scale = f.unit.scale;
  let decimals = f.decimals;
  if (scale && Math.abs(value) >= SCALE_X[scale]) {
    value /= SCALE_X[scale];
    decimals = decimalsFor(value);
  }
  if ((money || f.unit.pre === "$") && !scale) {
    for (const s of ["TRILLION", "BILLION", "MILLION"]) {
      if (Math.abs(value) >= SCALE_X[s]) {
        value /= SCALE_X[s];
        scale = s;
        decimals = decimalsFor(value);
        break;
      }
    }
  }
  const year = isYear(value, f.unit);
  return { fig: fmt(value, decimals, year), value, decimals, pre: f.unit.pre === "$" ? "$" : "", top: f.unit.top,
    tag: [scale, f.unit.tag].filter(Boolean).join(" "), year };
};

/** "22%", "$4.2 BILLION", "3,517 FT": a drawn figure as one plain string (tests, editor previews). */
export const plainOf = (d: Drawn): string => `${d.pre}${d.fig}${d.top}${d.tag ? ` ${d.tag}` : ""}`;

/** Two figures to compare: the first two items with values (their own unit, else the overlay's). */
export type Side = { label: string; drawn: Drawn; f: Fig };
export const sidesOf = (ov: { items?: unknown; prefix?: unknown; suffix?: unknown }, max = 2): Side[] => {
  const items = Array.isArray(ov.items) ? ov.items : [];
  const out: Side[] = [];
  for (const it of items) {
    if (!it || typeof it !== "object") continue;
    const x = it as { label?: unknown; value?: unknown; prefix?: unknown; suffix?: unknown; text?: unknown };
    const v = numOf(x.value);
    if (v === null) continue;
    const f = figureOf({ value: v, prefix: str(x.prefix) || str(ov.prefix), suffix: str(x.suffix) || str(ov.suffix) });
    out.push({ label: clip(trimEnds(digits(str(x.label) || str(x.text))).toUpperCase(), 24), drawn: drawnOf(f), f });
    if (out.length >= max) break;
  }
  return out;
};

/** Where a figure sits in its sentence: [start, end) of its digits as written, or null. */
export const figureSpan = (sentence: string, d: Drawn, raw: number | null): [number, number] | null => {
  const s = sentence;
  const tries = [d.fig, raw === null ? "" : fmt(raw, decimalsFor(raw)), raw === null ? "" : String(raw)]
    .filter((x, i, a) => x && a.indexOf(x) === i);
  for (const t of tries) {
    const re = new RegExp(`(^|[^\\d.,])(\\$?\\s?${t.replace(/[.,$]/g, (c) => `\\${c}`)})(?![\\d])`);
    const m = re.exec(s);
    if (m) {
      const at = m.index + m[1].length;
      return [at, at + m[2].length];
    }
  }
  return null;
};
