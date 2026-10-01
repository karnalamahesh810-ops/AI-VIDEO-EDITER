/**
 * Spoken numbers to digits for the words the date, time and number looks
 * show (the owner, 2026-10-01: "when the number is said, like September 29
 * or 5 days, you show it as a word ('five days') instead of numbers - fix").
 *
 * The twin of src/numwords.py (the planner normalises the words it writes;
 * this reads older documents and the editor's own words the same way), and
 * tests/test_numwords.py runs both on the same cases:
 *
 *   spokenToDigits("five days")                  "5 days"
 *   spokenToDigits("SEPTEMBER TWENTY-NINTH")     "SEPTEMBER 29"
 *   spokenToDigits("three thousand homes")       "3,000 homes"
 *   spokenToDigits("two point five inches")      "2.5 inches"
 *   spokenToDigits("the fifteenth of September") "September 15"
 *   spokenToDigits("seven thirty pm")            "7:30 pm"
 *   spokenToDigits("Three Rivers")               "Three Rivers" (a name: nothing numeric follows it)
 *
 * Pure string work (no React, no Remotion).
 */

const list = (s: string) => s.split(" ");
const UNITS: Record<string, number> = {};
list("zero one two three four five six seven eight nine").forEach((w, i) => { UNITS[w] = i; });
const TEENS: Record<string, number> = {};
list("ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen").forEach((w, i) => { TEENS[w] = i + 10; });
const TENS: Record<string, number> = {};
list("twenty thirty forty fifty sixty seventy eighty ninety").forEach((w, i) => { TENS[w] = (i + 2) * 10; });
const SCALES: Record<string, number> = { thousand: 1e3, million: 1e6, billion: 1e9, trillion: 1e12 };
const ORD_UNITS: Record<string, number> = {};
list("first second third fourth fifth sixth seventh eighth ninth").forEach((w, i) => { ORD_UNITS[w] = i + 1; });
const ORD_TEENS: Record<string, number> = {};
list("tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth")
  .forEach((w, i) => { ORD_TEENS[w] = i + 10; });
const ORD_TENS: Record<string, number> = {};
list("twentieth thirtieth fortieth fiftieth sixtieth seventieth eightieth ninetieth").forEach((w, i) => { ORD_TENS[w] = (i + 2) * 10; });
const ORD_SCALES: Record<string, number> = { thousandth: 1e3, millionth: 1e6, billionth: 1e9 };
const has = (o: Record<string, number>, w: string) => Object.prototype.hasOwnProperty.call(o, w);

const VOCAB = Array.from(new Set([...Object.keys(UNITS), ...Object.keys(TEENS), ...Object.keys(TENS), ...Object.keys(SCALES),
  ...Object.keys(ORD_UNITS), ...Object.keys(ORD_TEENS), ...Object.keys(ORD_TENS), ...Object.keys(ORD_SCALES),
  "hundred", "hundredth", "oh", "a", "an", "and", "point", "half"]))
  .sort((a, b) => b.length - a.length || (a < b ? -1 : a > b ? 1 : 0));
const ALT = VOCAB.join("|");
const RUN = new RegExp(`\\b(?:${ALT})(?:(?:\\s+|\\s*-\\s*)(?:${ALT}))*\\b`, "gi");
const WORD = /[A-Za-z]+/g;

const MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december|"
  + "jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec";
const MONTH_NAMES = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER",
  "NOVEMBER", "DECEMBER"];
/** Words that make the number before them a quantity (never a river, a lake, an oak or a spring). */
const UNIT_WORDS = "seconds?|minutes?|hours?|days?|nights?|weeks?|weekends?|months?|years?|decades?|centuries|century|"
  + "inch|inches|foot|feet|ft|yards?|miles?|meters?|metres?|kilometers?|kilometres?|km|mph|knots?|"
  + "acres?|acre-feet|acre-foot|square|cubic|gallons?|liters?|litres?|barrels?|tons?|tonnes?|pounds?|lbs|"
  + "ounces?|degrees?|cents?|"
  + "people|persons?|residents?|homes?|houses?|households?|families|family|children|child|kids?|students?|"
  + "workers?|jobs?|deaths?|lives|victims?|structures?|buildings?|businesses|business|farms?|vehicles?|cars?|"
  + "trucks?|animals?|trees?|visitors?|tourists?|customers?|patients?|soldiers?|troops?|refugees?|migrants?|"
  + "voters?|employees?|firefighters?|states?|counties|county|cities|city|towns?|communities|community|"
  + "countries|country|schools?|hospitals?|roads?|dams?|reservoirs?|storms?|floods?|fires?|wildfires?|"
  + "earthquakes?|tornado(?:e?s)?|hurricanes?|times|percent|per\\s+cent|dollars?";
const UNIT_AFTER = new RegExp(`^\\s*-?\\s*(?:${UNIT_WORDS})\\b`, "i");
const PERCENT_AFTER = /^\s*(?:%|percent\b|per\s+cent\b)/i;
const DOLLARS_AFTER = /^\s*dollars?\b/i;
const AMPM_AFTER = /^\s*[ap]\.?\s?m\b\.?/i;
const OCLOCK_AFTER = /^\s*o['’]?\s?clock\b/i;
const MONTH_BEFORE = new RegExp(`\\b(${MONTHS})\\.?\\s+(?:the\\s+)?$`, "i");
const THE_BEFORE = /\bthe\s+$/i;
const OF_MONTH_AFTER = new RegExp(`^\\s+of\\s+(${MONTHS})\\b\\.?`, "i");
const MONTH_AFTER = new RegExp(`^\\s+(${MONTHS})\\b`, "i");
const YEAR_BEFORE = /\b(?:in|since|by|until|from|of|year|before|after)\s+$/i;
const SENTENCE_START = /(?:^|[.!?:;—("“]\s*)$/;
const ALNUM = /[A-Za-z0-9]/;
const DIGIT_ORDINAL = new RegExp(`\\b(${MONTHS})(\\.?\\s+)(\\d{1,2})(?:st|nd|rd|th)\\b`, "gi");
const DIGIT_THOUSAND = /\b(\d{1,3}(?:\.\d+)?)\s+thousand\b/gi;
const CLOCK = /\b((?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)(?:\s+(?:oh\s+)?[a-z]+(?:[\s-][a-z]+)?))(\s*[ap]\.?\s?m\b\.?)/gi;

type Kind = "cardinal" | "ordinal" | "decimal" | "year";
type Read = { value: number; used: number; kind: Kind; scale: string; big: boolean; words: number };

/** A number read word by word (feed one word at a time; value() once it is a whole number). */
class Parse {
  total = 0;
  cur = 0;
  unit = false;
  teen = false;
  tens = false;
  hund = false;
  lastScale = 0;
  leadA = false;
  n = 0;
  andPending = false;
  halfStep = 0;
  afterBig = false;
  point = false;
  dec = "";
  half = false;
  ordinal = false;
  done = false;
  scaleWord = "";
  big = false;

  value(): number | null {
    if (this.andPending || this.point || this.halfStep || (this.n === 0 && !this.dec)) return null;
    const v = this.total + this.cur + (this.dec ? Number(`0.${this.dec}`) : 0);
    return this.half ? v + 0.5 : v;
  }

  feed(raw: string): boolean {
    const w = raw.toLowerCase();
    if (this.done) return false;
    if (this.halfStep === 1) {
      if (w === "a" || w === "an") {
        this.halfStep = 2;
        this.andPending = false;
        return true;
      }
      if (!this.andPending) return false;
      this.halfStep = 0;
    } else if (this.halfStep === 2) {
      if (w !== "half") return false;
      this.halfStep = 0;
      this.half = this.done = this.big = true;
      return true;
    }
    if (this.point || this.dec) {
      if (has(UNITS, w) || w === "oh") {
        this.dec += String(has(UNITS, w) ? UNITS[w] : 0);
        this.point = false;
        return true;
      }
      if (has(SCALES, w) && this.dec && !this.total && this.cur < 1000) {
        this.cur = (this.cur + Number(`0.${this.dec}`)) * SCALES[w];
        this.dec = "";
        this.scaleWord = raw;
        this.done = true;
        this.n += 1;
        return true;
      }
      return false;
    }
    if (w === "a" || w === "an") {
      if (this.n || this.leadA) return false;
      this.leadA = true;
      return true;
    }
    if (w === "and") {
      if (this.andPending || !this.n) return false;
      this.andPending = this.afterBig;
      this.halfStep = 1;
      return true;
    }
    if (w === "point") {
      if (this.hund || this.afterBig || this.leadA) return false;
      this.point = this.big = true;
      return true;
    }
    if (w === "half" || w === "oh") return false;
    if (this.leadA && !has(SCALES, w) && !has(ORD_SCALES, w) && w !== "hundred" && w !== "hundredth") return false;
    if (w === "zero") {
      if (this.n) return false;
      this.n = 1;
      this.done = true;
      return true;
    }
    if (has(UNITS, w) || has(ORD_UNITS, w)) {
      if (this.unit || this.teen) return false;
      this.cur += has(UNITS, w) ? UNITS[w] : ORD_UNITS[w];
      this.unit = true;
      this.ordinal = this.done = has(ORD_UNITS, w);
    } else if (has(TEENS, w) || has(ORD_TEENS, w)) {
      if (this.unit || this.teen || this.tens) return false;
      this.cur += has(TEENS, w) ? TEENS[w] : ORD_TEENS[w];
      this.teen = true;
      this.ordinal = this.done = has(ORD_TEENS, w);
    } else if (has(TENS, w) || has(ORD_TENS, w)) {
      if (this.unit || this.teen || this.tens) return false;
      this.cur += has(TENS, w) ? TENS[w] : ORD_TENS[w];
      this.tens = true;
      this.ordinal = this.done = has(ORD_TENS, w);
    } else if (w === "hundred" || w === "hundredth") {
      if (this.hund || this.cur >= 100 || (!this.cur && !this.leadA)) return false;
      this.cur = (this.cur || 1) * 100;
      this.unit = this.teen = this.tens = false;
      this.hund = this.big = true;
      this.ordinal = this.done = w === "hundredth";
    } else if (has(SCALES, w) || has(ORD_SCALES, w)) {
      const scale = has(SCALES, w) ? SCALES[w] : ORD_SCALES[w];
      if ((!this.cur && !this.leadA) || (this.lastScale && scale >= this.lastScale)) return false;
      this.total += (this.cur || 1) * scale;
      this.cur = 0;
      this.unit = this.teen = this.tens = this.hund = false;
      this.lastScale = scale;
      this.scaleWord = this.scaleWord || raw;
      this.big = true;
      this.ordinal = this.done = has(ORD_SCALES, w);
    } else {
      return false;
    }
    this.afterBig = w === "hundred" || has(SCALES, w);
    this.leadA = false;
    this.n += 1;
    this.andPending = false;
    this.halfStep = 0;
    return true;
  }
}

/** The 01-99 a year or a clock's minutes end on ("sixty-one", "oh five", "twenty"): [value, words used]. */
const twoDigits = (words: string[]): [number | null, number] => {
  if (!words.length) return [null, 0];
  const w = words[0].toLowerCase();
  const nxt = words.length > 1 ? words[1].toLowerCase() : "";
  if (w === "oh" && has(UNITS, nxt) && nxt !== "zero") return [UNITS[nxt], 2];
  if (has(TEENS, w)) return [TEENS[w], 1];
  if (has(TENS, w)) return has(UNITS, nxt) && nxt !== "zero" ? [TENS[w] + UNITS[nxt], 2] : [TENS[w], 1];
  return [null, 0];
};

/** The longest number the words start with, or null. */
const read = (words: string[]): Read | null => {
  if (words.length >= 3 && words[0].toLowerCase() === "half" && ["a", "an"].includes(words[1].toLowerCase())
    && has(SCALES, words[2].toLowerCase())) {
    return { value: 0.5 * SCALES[words[2].toLowerCase()], used: 3, kind: "cardinal", scale: words[2], big: true, words: 2 };
  }
  const p = new Parse();
  let best: Read | null = null;
  let stop = words.length;
  for (let i = 0; i < words.length; i++) {
    if (!p.feed(words[i])) {
      stop = i;
      break;
    }
    const v = p.value();
    if (v !== null) {
      best = { value: v, used: i + 1, kind: p.ordinal ? "ordinal" : p.dec ? "decimal" : "cardinal", scale: p.scaleWord,
        big: p.big, words: p.n };
    }
  }
  if (best && best.kind === "cardinal" && !best.big && best.used === stop && stop < words.length
    && p.cur >= 15 && p.cur <= 20 && !p.unit) {
    // A year said in pairs: "nineteen sixty-one", "twenty twenty-six", "nineteen oh five".
    const [rest, used] = twoDigits(words.slice(stop));
    if (rest !== null) {
      return { value: p.cur * 100 + rest, used: stop + used, kind: "year", scale: "", big: true, words: best.words + used };
    }
  }
  return best;
};

const wordsOf = (s: string): string[] => s.match(WORD) || [];

/** The number a phrase says when the whole phrase is one ("twenty-two", "two point five"), else null. */
export const parseNumber = (text: string): number | null => {
  const words = wordsOf(text || "");
  const got = words.length ? read(words) : null;
  return got && got.used === words.length && got.kind !== "ordinal" ? got.value : null;
};

/** The number an ordinal says ("twenty-ninth" -> 29, "29th" -> 29), else null. */
export const ordinalNumber = (text: string): number | null => {
  const m = /^\s*(\d{1,3})(?:st|nd|rd|th)\s*$/i.exec(text || "");
  if (m) return Number(m[1]);
  const words = wordsOf(text || "");
  const got = words.length ? read(words) : null;
  return got && got.used === words.length && got.kind === "ordinal" ? Math.trunc(got.value) : null;
};

const isUpper = (w: string) => w === w.toUpperCase() && w !== w.toLowerCase();

/** 2.5 -> "2.5", 75 -> "75", 1.25 -> "1.25" (at most three decimals). */
const plain = (q: number): string => q.toFixed(3).replace(/0+$/, "").replace(/\.$/, "") || "0";
const grouped = (whole: string): string => whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");

const digitsOf = (value: number, kind: Kind, scale: string, comma: boolean): string => {
  if (kind === "year") return String(Math.trunc(value));
  const big = (scale || "").toLowerCase();
  if (big === "million" || big === "billion" || big === "trillion") {
    // "75 million", "1.2 billion"; half a billion is "500 million" (half a million is 500,000).
    for (const name of ["trillion", "billion", "million"]) {
      if (SCALES[name] <= SCALES[big] && value >= SCALES[name]) {
        const word = name === big ? scale : isUpper(scale) ? name.toUpperCase()
          : /^[A-Z]/.test(scale) ? name.charAt(0).toUpperCase() + name.slice(1) : name;
        return `${plain(value / SCALES[name])} ${word}`;
      }
    }
  }
  const s = plain(value);
  const dot = s.indexOf(".");
  let whole = dot >= 0 ? s.slice(0, dot) : s;
  const frac = dot >= 0 ? s.slice(dot + 1) : "";
  if (comma && Number(whole) >= 1000) whole = grouped(whole);
  return whole + (frac ? `.${frac}` : "");
};

/** Ordinary sentence case (most words begin lower case): a capital mid-sentence then marks a name. */
const informativeCase = (text: string): boolean => {
  const words = text.match(/[A-Za-z][A-Za-z'’-]*/g) || [];
  return words.length >= 3 && 2 * words.filter((w) => /^[a-z]/.test(w)).length >= words.length;
};

/** "sept" -> "September" in the word's own case. */
const monthName = (word: string): string => {
  const name = MONTH_NAMES.find((m) => m.startsWith(word.toUpperCase().slice(0, 3))) || word.toUpperCase();
  if (isUpper(word)) return name;
  return /^[A-Z]/.test(word) ? name.charAt(0) + name.slice(1).toLowerCase() : name.toLowerCase();
};

const monthBefore = (before: string): boolean => {
  const m = MONTH_BEFORE.exec(before);
  return Boolean(m) && m![1] !== "may";            // "it may one day" is not May 1
};

/** [replacement, start, end] for the number said at text[a, b), or null to leave it as said. */
const render = (text: string, a: number, b: number, got: Read, first: string, informative: boolean)
  : [string, number, number] | null => {
  const before = text.slice(0, a);
  const after = text.slice(b);
  const { value, kind } = got;
  const mBefore = monthBefore(before);
  let mAfter = MONTH_AFTER.exec(after);
  if (mAfter && mAfter[1] === "may") mAfter = null;
  const ofMonth = OF_MONTH_AFTER.exec(after);
  const day = Number.isInteger(value) && value >= 1 && value <= 31 ? value : 0;
  const the = THE_BEFORE.exec(before);
  if (ofMonth && day && (kind === "ordinal" || (kind === "cardinal" && the))) {
    // "the twenty-ninth of September" -> "September 29"
    return [`${monthName(ofMonth[1])} ${day}`, the ? the.index : a, b + ofMonth[0].length];
  }
  if (kind === "ordinal") {
    if (!day || !(mBefore || mAfter)) return null;
    // "September the twenty-ninth" -> "September 29"
    return [String(day), the && mBefore ? the.index : a, b];
  }
  const unit = UNIT_AFTER.exec(after);
  const ampm = AMPM_AFTER.exec(after);
  const oclock = OCLOCK_AFTER.exec(after);
  const whole = !ALNUM.test(before) && !ALNUM.test(after);
  const strong = Boolean(unit || ampm || oclock || mBefore || mAfter) || kind === "year" || kind === "decimal" || got.big;
  if (!strong) {
    const name = informative && /^[A-Z]/.test(first) && !SENTENCE_START.test(before);
    if (name || !(got.words >= 2 || whole)) return null;
  }
  if (oclock && day && value <= 12) return [`${day}:00`, a, b + oclock[0].length];
  const yearLike = kind === "year" || (Number.isInteger(value) && value >= 1000 && value <= 2099 && !unit
    && (mBefore || whole || YEAR_BEFORE.test(before)));
  const digits = digitsOf(value, yearLike ? "year" : kind, got.scale, !yearLike);
  const percent = PERCENT_AFTER.exec(after);
  if (percent) return [`${digits}%`, a, b + percent[0].length];
  const dollars = DOLLARS_AFTER.exec(after);
  if (dollars) return [`$${digits}`, a, b + dollars[0].length];
  return [digits, a, b];
};

/** "seven thirty pm" -> "7:30 pm", "eleven oh five a.m." -> "11:05 a.m." */
const clock = (text: string): string => text.replace(CLOCK, (all: string, g1: string, g2: string) => {
  const words = wordsOf(g1);
  const [mins, used] = twoDigits(words.slice(1));
  const h = read(words.slice(0, 1));
  if (!h || h.value < 1 || h.value > 12 || mins === null || used !== words.length - 1 || mins > 59) return all;
  return `${Math.trunc(h.value)}:${String(mins).padStart(2, "0")}${g2}`;
});

/** The text with every plainly numeric spoken number in digits (src/numwords.py normalize). */
export const spokenToDigits = (input: string): string => {
  if (!input || typeof input !== "string") return input;
  let text = input.replace(DIGIT_ORDINAL, (_m: string, mo: string, gap: string, d: string) => `${mo}${gap}${d}`);
  text = text.replace(DIGIT_THOUSAND, (_m: string, n: string) => digitsOf(Number(n) * 1000, "cardinal", "", true));
  text = clock(text);
  const informative = informativeCase(text);
  const out: string[] = [];
  let pos = 0;
  RUN.lastIndex = 0;
  for (const run of Array.from(text.matchAll(RUN))) {
    const base = run.index ?? 0;
    const spans: [number, number][] = Array.from(run[0].matchAll(WORD)).map((m) => [base + (m.index ?? 0),
      base + (m.index ?? 0) + m[0].length]);
    const words = spans.map(([x, y]) => text.slice(x, y));
    let s = 0;
    while (s < words.length) {
      if (spans[s][0] < pos) {
        s += 1;
        continue;
      }
      const got = read(words.slice(s));
      const rep = got ? render(text, spans[s][0], spans[s + got.used - 1][1], got, words[s], informative) : null;
      if (!got || !rep || rep[1] < pos) {
        s += 1;
        continue;
      }
      out.push(text.slice(pos, rep[1]), rep[0]);
      pos = rep[2];
      s += got.used;
    }
  }
  out.push(text.slice(pos));
  return out.join("");
};
