/**
 * Pure helpers for the pro looks (LibDataPro "dx-", LibMapsPro "mx-",
 * LibDocsPro "kx-"): how a figure, a unit, a place, a distance or a line of
 * words is written on screen. No React and no Remotion, so the same code runs
 * in the renderer, the editor's Player and a node test
 * (tests/test_pro_looks.py runs it through esbuild).
 *
 * The owner's rules this file keeps:
 *  - numbers in digits ("three thousand" -> "3,000"; numWords.ts), grouped
 *    with commas, a year never ("2026", not "2,026");
 *  - only what the narration said: a missing value stays missing (null), a
 *    label is never invented;
 *  - short, clean words: a long line is cut at a word, never mid-word and
 *    never on a dangling "the", "of", "and".
 */
import { spokenToDigits } from "./numWords";

// ------------------------------------------------------------------ plain values
/** A string from anything the plan may have put there (a number is written out; anything else is ""). */
export const str = (v: unknown): string =>
  (typeof v === "string" ? v : typeof v === "number" && Number.isFinite(v) ? String(v) : "").replace(/\s+/g, " ").trim();

/** A finite number from a number or a numeric string ("3,517", "22%", "−8", "$4.5"), else null. */
export const num = (v: unknown): number | null => {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v !== "string") return null;
  const m = /-?\d[\d,]*(?:\.\d+)?|-?\.\d+/.exec(v.replace(/[−–]/g, "-"));
  if (!m) return null;
  const n = Number(m[0].replace(/,/g, ""));
  return Number.isFinite(n) ? n : null;
};

/** Spoken numbers in digits ("twenty-two percent" -> "22 percent"), never throwing. */
export const digits = (s: string): string => {
  try {
    return spokenToDigits(s).replace(/\s+/g, " ").trim();
  } catch {
    return s;
  }
};

const SMALL_TAIL = /[\s,;:\-–—]+(?:the|a|an|of|in|at|on|and|or|to|for|by|with|from|before|after|near|as|is|was)?$/i;

/** At most n characters, cut at a word, never ending on a dangling small word or a comma. `dots` adds an ellipsis. */
export const clip = (s: string, n: number, dots = false): string => {
  const t = str(s);
  if (t.length <= n) return t;
  let cut = t.slice(0, Math.max(1, dots ? n - 1 : n)).replace(/\s+\S*$/, "").trim();
  for (let i = 0; i < 4 && SMALL_TAIL.test(cut); i++) cut = cut.replace(SMALL_TAIL, "").trim();
  if (!cut) cut = t.slice(0, n);
  return dots ? `${cut.replace(/[\s,.;:!?-]+$/, "")}…` : cut;
};

/** "LAKE POWELL" / "lake powell" -> "Lake Powell"; short words stay low ("Bureau of Reclamation"). */
export const titleCase = (s: string): string => {
  const low = new Set(["of", "the", "and", "in", "on", "at", "to", "for", "a", "an", "by", "de", "del", "la"]);
  return str(s).toLowerCase().split(" ").map((w, i) => (i > 0 && low.has(w) ? w
    : w.replace(/(^|[-/(])([a-z])/g, (_m, a: string, b: string) => a + b.toUpperCase()))).join(" ");
};

// ------------------------------------------------------------------ figures
/** A whole year (1000-2100) with no unit: written without a thousands comma. */
export const isYear = (v: number, suffix = ""): boolean =>
  Number.isInteger(v) && v >= 1000 && v <= 2100 && !str(suffix);

/** The decimals a value needs: none at 100 and above or for whole numbers, at most 1 below 100 (2 below 1). */
export const decimalsOf = (v: number): number => {
  const a = Math.abs(v);
  if (!Number.isFinite(a) || a >= 100) return 0;
  const most = a >= 1 ? 1 : 2;
  for (let d = 0; d < most; d++) {
    const m = a * 10 ** d;
    if (Math.abs(m - Math.round(m)) < 1e-6 * Math.max(1, m)) return d;
  }
  return most;
};

/** "3,517", "22", "4.5", "2026" (a year is never grouped), "−183" with the typographic minus. */
export const fmtNumber = (v: number, decimals?: number, grouping = true): string => {
  if (!Number.isFinite(v)) return "";
  const d = decimals ?? decimalsOf(v);
  const x = Math.abs(v) < 10 ** -(d + 1) ? 0 : v;
  const text = Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d,
    useGrouping: grouping && !isYear(Math.abs(x)) });
  return `${x < 0 ? "−" : ""}${text}`;
};

// Units as a figure carries them on screen. Scale letters and "%" sit on the
// digits; a unit word follows after a thin space in smaller caps.
// (A scale WORD the planner wrote - "MILLION", "BILLION" - stays a word: "75 MILLION".)
const UNIT_ALIASES: Record<string, string> = {
  feet: "FT", foot: "FT", ft: "FT", "ft.": "FT", miles: "MI", mile: "MI", mi: "MI", meters: "M", meter: "M",
  metres: "M", metre: "M", kilometers: "KM", kilometres: "KM", km: "KM", inches: "IN", inch: "IN",
  percent: "%", "per cent": "%", pct: "%", "acre-feet": "ACRE-FT", "acre feet": "ACRE-FT", maf: "MAF",
  degrees: "°", "°f": "°F", "°c": "°C", mph: "MPH",
};
const SCALE_LETTERS = new Set(["K", "M", "B", "T"]);

/** The unit as written on screen: "feet" -> "FT", "percent" -> "%", else its caps (at most 10). */
export const unitOf = (suffix: unknown): string => {
  const s = str(suffix);
  if (!s) return "";
  const alias = UNIT_ALIASES[s.toLowerCase()];
  return alias ?? s.toUpperCase().slice(0, 10);
};

export interface Figure {
  /** "$" (money) or "". */
  prefix: string;
  /** The digits: "3,517", "4.5". */
  main: string;
  /** What sits on the digits: "%", "M", "B", "°F"... */
  glued: string;
  /** A unit word after a space: "FT", "MI", "ACRE-FT", "PEOPLE". */
  unit: string;
  value: number;
  pct: boolean;
}

/**
 * A figure split for drawing: "$4.5B" -> {prefix "$", main "4.5", glued "B"},
 * "3,517 FT" -> {main "3,517", unit "FT"}. A scale letter sits on the digits
 * ("4.4M"), except "M" on a length look (`length`), where it is metres ("120 M").
 */
export const figureOf = (value: number, suffix?: unknown, prefix?: unknown, length = false): Figure => {
  const u = unitOf(suffix);
  const p = str(prefix) === "$" ? "$" : "";
  const scale = SCALE_LETTERS.has(u) && !(u === "M" && length && !p);
  const glued = u === "%" || u.startsWith("°") || scale ? u : "";
  return { prefix: p, main: fmtNumber(value, undefined, !(isYear(value, u) && !p)), glued, unit: glued ? "" : u, value,
    pct: u === "%" };
};

/** The figure as one string: "3,517 FT", "22%", "$4.5B". */
export const figureText = (fig: Figure): string =>
  `${fig.prefix}${fig.main}${fig.glued}${fig.unit ? ` ${fig.unit}` : ""}`;

/** The same figure partway through a count (from 0, or `from`), with the decimals of the final value. */
export const countText = (fig: Figure, p: number, from = 0): string => {
  const q = Math.max(0, Math.min(1, p));
  const v = from + (fig.value - from) * q;
  const d = decimalsOf(fig.value);
  const grouping = !(isYear(fig.value, fig.unit || fig.glued) && !fig.prefix);
  return fmtNumber(q >= 1 ? fig.value : Number(v.toFixed(d)), d, grouping);
};

/** Signed percent change, first to last: "−35%", "+12%"; "" when it cannot be said. */
export const percentChange = (from: number, to: number): string => {
  if (!Number.isFinite(from) || !Number.isFinite(to) || Math.abs(from) < 1e-9) return "";
  const pct = ((to - from) / Math.abs(from)) * 100;
  const a = Math.abs(pct);
  if (a < 0.05) return "0%";
  return `${pct < 0 ? "−" : "+"}${a >= 10 ? Math.round(a) : a.toFixed(1).replace(/\.0$/, "")}%`;
};

/** How many times larger the first is than the second: "4.5×", "12×"; "" under 1.05. */
export const ratioText = (big: number, small: number): string => {
  if (!(big > 0) || !(small > 0)) return "";
  const r = big / small;
  if (r < 1.05) return "";
  return `${r >= 10 ? Math.round(r) : r.toFixed(1).replace(/\.0$/, "")}×`;
};

// ------------------------------------------------------------------ axes
const niceStep = (raw: number): number => {
  if (!(raw > 0) || !Number.isFinite(raw)) return 1;
  const p = 10 ** Math.floor(Math.log10(raw));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= raw - 1e-12) return m * p;
  return 10 * p;
};

/** A round axis around [lo, hi] with about `count` steps: {min, max, step, ticks}. */
export const niceScale = (lo: number, hi: number, count = 4) => {
  let a = Math.min(lo, hi);
  let b = Math.max(lo, hi);
  if (!Number.isFinite(a) || !Number.isFinite(b)) {
    a = 0;
    b = 1;
  }
  if (b - a < 1e-9) b = a + (Math.abs(a) * 0.1 || 1);
  const step = niceStep((b - a) / Math.max(1, count));
  const min = Math.floor(a / step + 1e-9) * step;
  let max = Math.ceil(b / step - 1e-9) * step;
  if (max <= min) max = min + step;
  const ticks: number[] = [];
  for (let i = 0; i <= 24; i++) {
    const t = min + i * step;
    if (t > max + step * 1e-6) break;
    ticks.push(Math.round(t * 1e6) / 1e6);
  }
  return { min, max, step, ticks };
};

/** The axis for a series: from zero when the data sits close to it, else padded around the data. */
export const seriesScale = (vals: number[], count = 4) => {
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const span = hi - lo || Math.abs(hi) || 1;
  const zero = lo >= 0 && lo <= hi * 0.45;
  return niceScale(zero ? 0 : lo - span * 0.22, hi + span * 0.14, count);
};

// ------------------------------------------------------------------ data rows
export interface Row {
  label: string;
  value: number;
  suffix: string;
  prefix: string;
  text: string;
}

/** The overlay's items that carry a finite value (labels as strings), at most `max`. */
export const rowsOf = (items: unknown, max = 12): Row[] => {
  const out: Row[] = [];
  if (!Array.isArray(items)) return out;
  for (const it of items) {
    if (!it || typeof it !== "object") continue;
    const o = it as Record<string, unknown>;
    const v = num(o.value);
    if (v === null) continue;
    out.push({ label: digits(str(o.label)), value: v, suffix: str(o.suffix), prefix: str(o.prefix), text: str(o.text) });
    if (out.length >= max) break;
  }
  return out;
};

/** The one unit a set of rows shares (the overlay's own first): suffix and prefix. */
export const unitsOf = (rows: Row[], suffix?: unknown, prefix?: unknown) => ({
  suffix: str(suffix) || rows.find((r) => r.suffix)?.suffix || "",
  prefix: str(prefix) || rows.find((r) => r.prefix)?.prefix || "",
});

// ------------------------------------------------------------------ places
export interface Place {
  label: string;
  lat: number;
  lon: number;
  kind?: string;
}

/** Valid gazetteer places only: finite, in range, labels as strings. Nothing here ever invents one. */
export const placesOf = (locations: unknown, max = 8): Place[] => {
  const out: Place[] = [];
  if (!Array.isArray(locations)) return out;
  for (const p of locations) {
    if (!p || typeof p !== "object") continue;
    const o = p as Record<string, unknown>;
    const lat = num(o.lat);
    const lon = num(o.lon);
    if (lat === null || lon === null || Math.abs(lat) > 90 || Math.abs(lon) > 180) continue;
    out.push({ label: str(o.label), lat, lon, kind: typeof o.kind === "string" ? o.kind : undefined });
    if (out.length >= max) break;
  }
  return out;
};

const COUNTRY_TAILS = /,\s*(?:United States(?: of America)?|USA|U\.S\.A?\.?|US)$/i;
const US_STATES: Record<string, string> = {
  AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas", CA: "California", CO: "Colorado", CT: "Connecticut",
  DE: "Delaware", FL: "Florida", GA: "Georgia", HI: "Hawaii", ID: "Idaho", IL: "Illinois", IN: "Indiana", IA: "Iowa",
  KS: "Kansas", KY: "Kentucky", LA: "Louisiana", ME: "Maine", MD: "Maryland", MA: "Massachusetts", MI: "Michigan",
  MN: "Minnesota", MS: "Mississippi", MO: "Missouri", MT: "Montana", NE: "Nebraska", NV: "Nevada",
  NH: "New Hampshire", NJ: "New Jersey", NM: "New Mexico", NY: "New York", NC: "North Carolina", ND: "North Dakota",
  OH: "Ohio", OK: "Oklahoma", OR: "Oregon", PA: "Pennsylvania", RI: "Rhode Island", SC: "South Carolina",
  SD: "South Dakota", TN: "Tennessee", TX: "Texas", UT: "Utah", VT: "Vermont", VA: "Virginia", WA: "Washington",
  WV: "West Virginia", WI: "Wisconsin", WY: "Wyoming",
};

/**
 * A gazetteer label as a map writes it: the name ("Page") and the region it
 * is in ("Arizona"), from "Page, Coconino County, Arizona, United States".
 * The country is dropped for a US place; a county is never the region.
 */
export const placeName = (label: string): { name: string; region: string } => {
  const raw = str(label).replace(COUNTRY_TAILS, "");
  const parts = raw.split(",").map((x) => x.trim()).filter(Boolean);
  const name = parts[0] || "";
  const rest = parts.slice(1).filter((x) => !/\b(county|parish|borough|municipality|district)\b/i.test(x));
  let region = rest.length ? rest[rest.length - 1] : "";
  if (/^[A-Z]{2}$/.test(region) && US_STATES[region]) region = US_STATES[region];
  return { name, region: region === name ? "" : region };
};

const RAD = Math.PI / 180;
/** Great-circle miles between two places. */
export const milesBetween = (a: { lat: number; lon: number }, b: { lat: number; lon: number }): number => {
  const h = Math.sin(((b.lat - a.lat) * RAD) / 2) ** 2
    + Math.cos(a.lat * RAD) * Math.cos(b.lat * RAD) * Math.sin(((b.lon - a.lon) * RAD) / 2) ** 2;
  return 3958.8 * 2 * Math.asin(Math.min(1, Math.sqrt(h)));
};

/**
 * The distance as a map writes it: the figure the narration said when it
 * said one (value + MI / KM), else the straight-line miles between the two
 * places ("2.4 MI", "290 MI"); "" when neither is known.
 */
export const distanceText = (miles: number | null, said?: number | null, saidUnit?: unknown): string => {
  const u = unitOf(saidUnit);
  if (said !== null && said !== undefined && Number.isFinite(said) && said > 0 && (u === "MI" || u === "KM")) {
    return `${fmtNumber(said)} ${u}`;
  }
  if (miles === null || !Number.isFinite(miles) || miles <= 0) return "";
  const v = miles < 10 ? Math.round(miles * 10) / 10 : Math.round(miles);
  return `${fmtNumber(v)} MI`;
};

/** "36.9375° N · 111.4844° W" (four decimals). */
export const coordText = (lat: number, lon: number, d = 4): string =>
  `${Math.abs(lat).toFixed(d)}° ${lat >= 0 ? "N" : "S"} · ${Math.abs(lon).toFixed(d)}° ${lon >= 0 ? "E" : "W"}`;

// ------------------------------------------------------------------ words
/** Text and its highlighted part: [before, the part, after] (case-insensitive; the whole text when absent). */
export const splitHighlight = (text: string, highlight: string): [string, string, string] => {
  const t = str(text);
  const h = str(highlight);
  if (!h) return [t, "", ""];
  const at = t.toLowerCase().indexOf(h.toLowerCase());
  if (at < 0) return [t, "", ""];
  return [t.slice(0, at), t.slice(at, at + h.length), t.slice(at + h.length)];
};

const STACK_SKIP = new Set(["the", "a", "an", "of", "and", "to", "in", "on", "at", "for", "is", "was", "are", "were",
  "it", "its", "that", "this", "with", "by", "as", "be", "been", "has", "have", "had"]);

/**
 * A headline as 2-4 short stacked lines for the keyword stack: every line one
 * to three words, small words kept with the word after them ("OF THE RIVER"),
 * never more than `maxChars` letters on a line.
 */
export const stackLines = (text: string, maxLines = 4, maxChars = 14): string[] => {
  const words = digits(str(text)).replace(/[“”"]/g, "").split(" ").filter(Boolean);
  if (!words.length) return [];
  const lines: string[] = [];
  let cur: string[] = [];
  const flush = () => {
    if (cur.length) lines.push(cur.join(" "));
    cur = [];
  };
  for (const w of words) {
    const cand = [...cur, w].join(" ");
    const smallOnly = cur.length > 0 && cur.every((x) => STACK_SKIP.has(x.toLowerCase().replace(/[^a-z']/g, "")));
    if (cur.length && (cand.length > maxChars || cur.length >= 3) && !smallOnly) flush();
    cur.push(w);
  }
  flush();
  if (lines.length <= maxLines) return lines;
  // Too many lines: keep the first maxLines, the last one cut at a word.
  const out = lines.slice(0, maxLines);
  out[maxLines - 1] = clip(lines.slice(maxLines - 1).join(" "), maxChars + 6);
  return out;
};

/** Initials for an avatar: "Arizona Department of Water Resources" -> "AD", "Floyd Dominy" -> "FD". */
export const initials = (name: string): string => {
  const words = str(name).replace(/[^A-Za-z0-9 ]/g, " ").split(" ").filter((w) => w && !STACK_SKIP.has(w.toLowerCase()));
  if (!words.length) return "";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
};

/** A handle as written: "@AZWater" (only when one was given; never made up). */
export const handleOf = (s: unknown): string => {
  const t = str(s).replace(/\s+/g, "");
  if (!t) return "";
  return t.startsWith("@") ? t.slice(0, 24) : `@${t.slice(0, 23)}`;
};
