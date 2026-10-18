/**
 * Editor v2's motion library (2026-10-14): 35 premium looks (pack 1) + 32 more (pack 2: kinetic type, data charts,
 * mock-up callouts, hand-drawn emphasis, effect transitions) - titles, lower thirds, figures, emphasis marks and
 * overlay transitions - each a RECIPE that designs a motion spec (specMath.ts) for its words, the narration's
 * word times and the video's brand kit. One renderer (SmartSpec's SpecStage) draws them all, in the worker's
 * render and in the editor's Player alike.
 *
 * Why recipes and not fixed templates: a recipe lays its words out for their length (sizes fit the frame, a long
 * title breaks into balanced lines), lands every word on the moment it is spoken (`wordAt`), takes its colours,
 * faces and easing from the kit (royal / noir / bulletin / atlas, or a Style Kit's measured tokens), and varies
 * itself by `seed` (direction, stagger, accent furniture) - so the same look used twice never reads as a copy.
 *
 * Motion rules every recipe keeps (the owner rejected stiff, cheap motion on 2026-10-14):
 *   - entrances 0.45-0.9 s on expo / quint curves, staggered 50-90 ms; never a bare scale pop;
 *   - things arrive from a blur and settle (no overshoot on type, a gentle one at most on marks);
 *   - one accent colour per graphic; type is the kit's; units in small caps;
 *   - fast moves carry motion blur (layer.mb); everything idles a little (stage drift) instead of freezing;
 *   - every look leaves within its last 0.45 s (spec.exit) - a graphic never cuts off.
 *
 * Pure and deterministic: the same params give the same spec (tests: src/test/motionLibrary.test.ts).
 */
import { KITS, type BrandKit } from "./brandKits";
import { cleanSpec, FONT_KEYS, type MotionSpec } from "./specMath";

export type MxFamily = "title" | "lower-third" | "number" | "emphasis" | "transition" | "data" | "callout";

export interface MxParams {
  /** The main words. */
  text: string;
  /** A second line (a role, what a figure is of, an attribution). */
  sub?: string;
  /** A small tag above (a place, a category, a date). */
  kicker?: string;
  value?: number;
  prefix?: string;
  suffix?: string;
  decimals?: number;
  /** Short items (tiles, steps; a chart's "Label 41" rows). */
  items?: string[];
  /** Each item's figure when the editor has it (overlay items' own values; else parsed from the label). */
  values?: (number | undefined)[];
  /** Seconds from the look's first frame each item is spoken, when known. */
  itemAt?: number[];
  /** Seconds from the look's first frame each word of `text` is spoken (the narration's own times), when known. */
  wordAt?: number[];
  /** The look's length in seconds. */
  dur: number;
  /** Where on the frame (an overlay position: auto, top-left, top, top-right, center, bottom-left, bottom, bottom-right). */
  position?: string;
  /** A point on the frame a mark points at (shares, 0..1). */
  point?: { x: number; y: number };
  /** Varies direction / furniture between uses of the same look. */
  seed?: number;
  /** Animation speed (1 = the kit's tempo). */
  speed?: number;
  /** Size multiplier. */
  scale?: number;
  /** Frame width / height. */
  aspect?: number;
  /**
   * What the words must keep off on the shot under the look (faces, logos, burned-in lettering: shares of the
   * frame, components/motion/avoid.ts). On "auto" placement the look takes the side that stays clear of them.
   */
  avoid?: { x: number; y: number; w: number; h: number }[];
}

export interface MxRecipe {
  id: string;
  name: string;
  family: MxFamily;
  /** One line for the look picker. */
  about: string;
  /** When the edit director should reach for it (trigger notes for Smart edit and the AI director). */
  use?: string;
  /** Sample words for the picker's preview (on black). */
  sample: Partial<MxParams>;
  build: (p: Required<Pick<MxParams, "text" | "dur">> & MxParams, k: BrandKit, c: Ctx) => Raw;
}

type Raw = Record<string, unknown> & { layers: Record<string, unknown>[] };
type Lay = Record<string, unknown>;

interface Ctx {
  /** Seconds scaled by the kit's tempo and the look's speed. */
  s: (sec: number) => number;
  aspect: number;
  scale: number;
  side: "left" | "right" | "center";
  /** Vertical band from the position (0..1), or null for the recipe's own. */
  y: number | null;
  /** 0..1 deterministic variety. */
  r: (n: number) => number;
  /** The time word i lands (its spoken time, else a stagger from `start`). */
  wt: (i: number, start: number, stagger: number) => number;
  words: string[];
  /** The share of the frame's width a side-placed block may take before it reaches a face / logo (avoid). */
  room: number;
}

// ------------------------------------------------------------------ kits
/** The kit a look draws in: a kit id, a Style Kit's brand tokens (any family names), or the channel accent. */
export const kitFrom = (v: unknown, accent?: string): BrandKit => {
  if (typeof v === "string" && KITS[v]) return KITS[v];
  const base = KITS.noir;
  if (v && typeof v === "object") {
    const o = v as Partial<BrandKit> & { colors?: Record<string, string>; fonts?: Record<string, string> };
    const colors = { ...base.colors };
    for (const [key, val] of Object.entries(o.colors || {})) if (typeof val === "string" && /^#[0-9a-f]{3,8}$/i.test(val) && key in colors) (colors as Record<string, string>)[key] = val;
    const fonts = { ...base.fonts };
    for (const [key, val] of Object.entries(o.fonts || {})) if (typeof val === "string" && key in fonts) (fonts as Record<string, string>)[key] = fontKeyFor(val);
    return { ...base, id: typeof o.id === "string" ? o.id : "custom", name: typeof o.name === "string" ? o.name : "Style Kit", colors, fonts,
      titleWeight: typeof o.titleWeight === "number" ? Math.max(500, Math.min(900, o.titleWeight)) : base.titleWeight,
      titleTracking: typeof o.titleTracking === "number" ? o.titleTracking : base.titleTracking,
      ease: typeof o.ease === "string" ? o.ease : base.ease, easeSoft: typeof o.easeSoft === "string" ? o.easeSoft : base.easeSoft,
      tempo: typeof o.tempo === "number" ? Math.max(0.5, Math.min(2, o.tempo)) : base.tempo };
  }
  if (accent && /^#[0-9a-f]{6}$/i.test(accent)) return { ...base, id: "accent", colors: { ...base.colors, primary: accent, pillBg: accent, region: accent } };
  return base;
};

/** A font family name (a Style Kit measures real faces) as the nearest face the renderer has. */
export const fontKeyFor = (family: string): string => {
  if ((FONT_KEYS as readonly string[]).includes(family)) return family;
  const f = family.toLowerCase();
  if (/mono|code|courier|plex mono|jetbrains/.test(f)) return "mono";
  if (/italic/.test(f) && /serif|garamond|playfair|times|georgia|libre|lora|merri/.test(f)) return "serif-italic";
  if (/serif|garamond|playfair|times|georgia|libre bask|lora|merri|didot|bodoni/.test(f) && !/sans/.test(f)) return "serif";
  if (/condensed|narrow|oswald|bebas|anton|league gothic|barlow cond|compressed|impact/.test(f)) return "narrow";
  if (/archivo black|druk|kinetic|black|heavy/.test(f)) return "kinetic";
  if (/inter|helvetica|arial|roboto|open sans|lato|source sans|nunito/.test(f)) return "inter";
  return "grotesk";
};

// ------------------------------------------------------------------ type measure
/** Average advance of one character, in em, per face (measured on the renderer's faces, rounded up). */
const CH: Record<string, number> = { narrow: 0.45, grotesk: 0.6, kinetic: 0.56, display: 0.58, serif: 0.52, "serif-italic": 0.5, mono: 0.62, inter: 0.56, hand: 0.42 };

/** The size (share of the frame height) at which `lines` fit `maxW` of the frame's width, within [lo, hi]. */
const fitSize = (lines: string[], font: string, maxW: number, aspect: number, hi: number, lo: number, upper = false, tracking = 0): number => {
  const n = Math.max(1, ...lines.map((l) => l.length));
  const em = (CH[font] ?? 0.58) * (upper ? 1.1 : 1) + tracking;
  return Math.max(lo * SIZE_BOOST, Math.min(hi * SIZE_BOOST, (maxW * aspect) / (n * em)));
};
/**
 * The recipes' size ceilings were first set like on-footage subtitles; on frames they read small next to the
 * owner's references (PointShift titles fill a third of the frame). Calibrated on the contact sheets: x1.3.
 */
const SIZE_BOOST = 1.3;

/** Width (share of the frame width) of a line at `size`. */
const widthOf = (line: string, font: string, size: number, aspect: number, upper = false, tracking = 0) =>
  (line.length * ((CH[font] ?? 0.58) * (upper ? 1.1 : 1) + tracking) * size) / aspect;

/** Words broken into at most `max` balanced lines of at most `chars` characters. */
export const balance = (text: string, chars: number, max = 3): string[] => {
  const words = text.trim().split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const total = words.join(" ").length;
  const n = Math.min(max, Math.max(1, Math.ceil(total / Math.max(4, chars))));
  if (n === 1) return [words.join(" ")];
  const target = total / n;
  const out: string[] = [];
  let line = "";
  for (const w of words) {
    const next = line ? `${line} ${w}` : w;
    if (line && next.length > target * 1.15 && out.length < n - 1) { out.push(line); line = w; } else line = next;
  }
  if (line) out.push(line);
  return out;
};

const fmt = (v: number, decimals: number) => {
  const s = Math.abs(v).toFixed(decimals);
  const [i, d] = s.split(".");
  return (v < 0 ? "-" : "") + i.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (d ? `.${d}` : "");
};

const hexA = (c: string, a: number): string => {
  const m = /^#([0-9a-f]{6})$/i.exec(c);
  if (!m) return c;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a.toFixed(3)})`;
};

// ------------------------------------------------------------------ placement
const placeX = (side: Ctx["side"]) => (side === "left" ? { x: 0.075, anchor: "l", align: "left" } : side === "right"
  ? { x: 0.925, anchor: "r", align: "right" } : { x: 0.5, anchor: "c", align: "center" });

const sideOf = (position: string | undefined, dflt: Ctx["side"], seed: number): Ctx["side"] => {
  const p = String(position || "auto");
  if (p.endsWith("left")) return "left";
  if (p.endsWith("right")) return "right";
  if (p === "center" || p === "top" || p === "bottom") return "center";
  return dflt === "center" ? "center" : (seed % 2 ? "right" : "left");
};
type Box = { x: number; y: number; w: number; h: number };
/** The share of the region [x0, x1] x [y0, y1] of the frame the boxes cover (overlaps counted once per box, capped at 1). */
const coveredShare = (boxes: Box[], x0: number, x1: number, y0: number, y1: number): number => {
  let a = 0;
  for (const b of boxes) {
    const w = Math.min(x1, b.x + b.w) - Math.max(x0, b.x), h = Math.min(y1, b.y + b.h) - Math.max(y0, b.y);
    if (w > 0 && h > 0) a += w * h;
  }
  return Math.min(1, a / Math.max(1e-6, (x1 - x0) * (y1 - y0)));
};
/**
 * On "auto" placement, the side whose text region stays clearest of the shot's faces / logos / lettering (2026-10-18):
 * the look's own side while that is clear (under 4% covered), else the clearest other side. An explicit position
 * is the user's choice and is never moved.
 */
export const sideAway = (side: Ctx["side"], position: string | undefined, avoid: Box[] | undefined, y: number | null): Ctx["side"] => {
  if (!avoid || !avoid.length || (position && position !== "auto")) return side;
  const yc = y ?? 0.5;
  const y0 = Math.max(0, yc - 0.25), y1 = Math.min(1, yc + 0.25);
  const R: Record<Ctx["side"], [number, number]> = { left: [0.04, 0.52], center: [0.2, 0.8], right: [0.48, 0.96] };
  const cov = (s: Ctx["side"]) => coveredShare(avoid, R[s][0], R[s][1], y0, y1);
  let best = side, bc = cov(side);
  if (bc < 0.04) return side;
  const others: Ctx["side"][] = side === "center" ? ["left", "right"] : [side === "left" ? "right" : "left", "center"];
  for (const s of others) { const v = cov(s); if (v < bc - 0.02) { best = s; bc = v; } }
  return best;
};
/** How much of the width a block on `side` has before the first avoid box in its band (1 = no limit). */
export const roomOn = (side: Ctx["side"], avoid: Box[] | undefined, y: number | null): number => {
  if (!avoid || !avoid.length || side === "center") return 1;
  const yc = y ?? 0.5;
  const y0 = Math.max(0, yc - 0.25), y1 = Math.min(1, yc + 0.25);
  let room = 1;
  for (const b of avoid) {
    if (b.y + b.h <= y0 || b.y >= y1) continue;
    const r = side === "left" ? b.x - 0.075 - 0.025 : 0.925 - (b.x + b.w) - 0.025;
    if (r > 0.08) room = Math.min(room, r);
  }
  // x0.88: the face table under-measures heavy caps by ~10-15%, and this is a limit, not a target
  return room >= 1 ? 1 : Math.max(0.3, room * 0.88);
};
const bandOf = (position: string | undefined): number | null => {
  const p = String(position || "auto");
  if (p.startsWith("top")) return 0.2;
  if (p.startsWith("bottom")) return 0.8;
  if (p === "center") return 0.5;
  return null;
};

/** The exit every look shares, and its gentle stage drift. */
const finish = (layers: Lay[], c: Ctx, exit: "fade" | "blur" | "drop" | "scale" | "wipe" = "blur", extra: Partial<Raw> = {}): Raw => ({
  v: 1, persp: 1400, exit: { kind: exit, dur: 0.42 }, drift: { x: c.side === "right" ? -0.004 : 0.004, y: -0.002, rotY: 0 },
  ...extra, layers,
});

// ------------------------------------------------------------------ text helpers
interface TextOpts {
  lines: string[];
  font: string;
  size: number;
  weight?: number;
  color: string;
  upper?: boolean;
  tracking?: number;
  x: number;
  y: number;
  anchor: string;
  align: string;
  lineH?: number;
  animator?: Record<string, unknown>;
  emph?: number[];
  emphColor?: string;
  emphStyle?: string;
  extra?: Lay;
}
const text = (o: TextOpts): Lay => ({
  kind: "text", text: o.lines.join("\n"), font: o.font, size: o.size, weight: o.weight ?? 800, color: o.color,
  upper: o.upper ?? false, tracking: o.tracking ?? 0, x: o.x, y: o.y, anchor: o.anchor, align: o.align,
  lineH: o.lineH ?? 1.02, maxW: 0.96, shadow: "soft", animator: o.animator, emph: o.emph, emphColor: o.emphColor,
  emphStyle: o.emphStyle, ...(o.extra || {}),
});

/** A word animator landing each word on its spoken time (or a stagger). */
const wordAnim = (c: Ctx, from: Record<string, number>, start: number, stagger: number, dur: number, ease: string, clip = false, unit: "word" | "line" | "char" = "word") => {
  const n = unit === "word" ? c.words.length : 0;
  const at = unit === "word" ? Array.from({ length: n }, (_, i) => c.wt(i, start, stagger)) : undefined;
  return { unit, stagger: c.s(stagger), dur: c.s(dur), ease, from, ...(at ? { at } : {}), ...(clip ? { clip: true } : {}) };
};

/** The figure a number look shows ("130", "$1.5", "37"). */
const figure = (p: MxParams) => {
  const v = typeof p.value === "number" && Number.isFinite(p.value) ? p.value : null;
  return v;
};

// ------------------------------------------------------------------ motion pack 2 (2026-10-14)
/** A colour mixed toward white (f > 0) or black (f < 0). */
const mix = (c: string, f: number): string => {
  const m = /^#([0-9a-f]{6})$/i.exec(c);
  if (!m) return c;
  const n = parseInt(m[1], 16);
  const ch = (v: number) => Math.round(f >= 0 ? v + (255 - v) * f : v * (1 + f)).toString(16).padStart(2, "0");
  return `#${ch((n >> 16) & 255)}${ch((n >> 8) & 255)}${ch(n & 255)}`;
};

const UNIT: Record<string, string> = { million: "M", millions: "M", m: "M", billion: "B", billions: "B", b: "B", bn: "B", thousand: "K", k: "K", trillion: "T", t: "T" };
/** A chart row from a short label: "Texas 41", "France: 89 million", "41% Ohio", "$2.5B Apple" (the overlay's own value wins). */
export const parseItem = (raw: string, value?: number): { l: string; v: number | null; pre?: string; suf?: string; dec?: number } => {
  const s = String(raw || "").replace(/\s+/g, " ").trim();
  const num = (x: string) => Number(x.replace(/[,$£€]/g, ""));
  const dec = (x: string) => { const d = /\.(\d+)$/.exec(x); return d ? Math.min(3, d[1].length) : 0; };
  const unit = (u?: string) => {
    if (!u) return undefined;
    const k = u.toLowerCase();
    if (k === "%" || k === "percent") return "%";
    return UNIT[k] || (/^[a-z]{1,5}$/i.test(u) ? ` ${u}` : undefined);
  };
  let m = /^(.*?)[\s:=–-]+(-?[$£€]?\d[\d,]*(?:\.\d+)?)\s*(%|percent|[a-z]{1,9})?$/i.exec(s);
  if (m && m[1].trim() && !/^\d{4}$/.test(m[2])) {
    const pre = /^-?[$£€]/.exec(m[2]) ? m[2].replace(/^-/, "")[0] : undefined;
    return { l: m[1].trim(), v: typeof value === "number" ? value : num(m[2]), pre, suf: unit(m[3]), dec: dec(m[2]) };
  }
  m = /^(-?[$£€]?\d[\d,]*(?:\.\d+)?)\s*(%|percent|million|billion|thousand|bn|[kmb])?\s+(.+)$/i.exec(s);
  if (m && !/^\d{4}$/.test(m[1])) {
    const pre = /^-?[$£€]/.exec(m[1]) ? m[1].replace(/^-/, "")[0] : undefined;
    return { l: m[3].trim(), v: typeof value === "number" ? value : num(m[1]), pre, suf: unit(m[2]), dec: dec(m[1]) };
  }
  return { l: s, v: typeof value === "number" ? value : null };
};

/** The items a data look draws (at most `max`). */
const rowsOf = (p: MxParams, max: number) => (p.items || []).slice(0, max).map((it, i) => parseItem(it, p.values?.[i]));

/** When each of n items lands: its spoken time when the editor found it, else spread over the look from `start`. */
const itemTimes = (p: MxParams, c: Ctx, n: number, start: number, dur: number): number[] => {
  const gap = Math.max(0.28, Math.min(0.75, (dur - start - 2.2) / Math.max(1, n)));
  return Array.from({ length: n }, (_, i) => {
    const at = p.itemAt?.[i];
    return typeof at === "number" && Number.isFinite(at) && at >= 0 && at < dur ? at : c.s(start + i * gap);
  });
};

/** A data look's title: a small accent rule and the words, top left of the chart. */
const chartTitle = (p: MxParams, k: BrandKit, c: Ctx, x: number, y: number, size = 0.062): Lay[] => {
  const lines = balance(p.text, 34, 2);
  const s = fitSize(lines, k.fonts.title, 0.62, c.aspect, size, 0.03, true) * c.scale;
  return [text({ lines, font: k.fonts.title, size: s, weight: k.titleWeight, color: k.colors.text, upper: true, x, y, anchor: "l", align: "left",
    tracking: k.titleTracking, animator: wordAnim(c, { y: 1.1, blur: 3 }, 0.05, 0.06, 0.6, "expoOut", true),
    extra: { deco: { rule: k.colors.primary, at: 0 }, sub: p.sub ? { text: T(p.sub), size: s * 0.5, font: k.fonts.body, weight: 500, color: k.colors.muted,
      tracking: 0.01, upper: false, at: c.s(0.5) } : undefined } })];
};

/**
 * The polished looks' motion grammar (2026-10-18, docs/motion-polish-2026-10-18.md): a unit (word, line, element)
 * arrives in at most 0.3 s on expo-out, out of its own mask, from a slight blur - never from scale 0, never with an
 * overshoot - and the graphic leaves faster than it came (0.28 s).
 */
const QUICK_EXIT = 0.28;
const quick = (kind: "fade" | "blur" | "drop" | "scale" | "wipe") => ({ exit: { kind, dur: QUICK_EXIT } });
/** A word rising out of its own line in 0.28 s, on its spoken time. */
const riseIn = (c: Ctx, start: number, stagger: number) => wordAnim(c, { y: 1.05, blur: 2 }, start, stagger, 0.28, "expoOut", true);
/**
 * The scrim under a polished title: a side gradient when it sits on a side; centred, an even dim (a vignette
 * leaves the middle - where the words are - untouched, and white type over a bright shot then reads at 480p only
 * by its shadow).
 */
const titleShade = (c: Ctx, side = 0.55, centre = 0.34) =>
  (c.side === "center" ? { kind: "full", amount: centre } : { kind: c.side, amount: side });
/** Words in two lines whose longer line is as short as it can be (balance() is greedy and can leave one word alone). */
const split2 = (words: string[]): string[] => {
  if (words.length < 2) return [words.join(" ")];
  let best = 1, bestLen = Infinity;
  for (let i = 1; i < words.length; i++) {
    const m = Math.max(words.slice(0, i).join(" ").length, words.slice(i).join(" ").length);
    if (m < bestLen) { bestLen = m; best = i; }
  }
  return [words.slice(0, best).join(" "), words.slice(best).join(" ")];
};
/** A short accent rule (a share of the frame width) that draws on from its left at `at`. */
const accentRule = (k: BrandKit, x: number, y: number, anchor: string, at: number, w = 0.045, h = 0.0065): Lay => ({
  kind: "rect", x, y, w, h, anchor, fill: k.colors.primary, color: k.colors.primary,
  keys: { draw: [[0, 0], [at, 0], [at + 0.3, 1, "expoOut"]] },
});

const trans = (layers: Lay[]): Raw => ({ v: 1, persp: 1400, exit: { kind: "fade", dur: 0 }, drift: { x: 0, y: 0, rotY: 0 }, layers });
const verdictColor = (word: string, k: BrandKit) => (/fact[- ]?check/i.test(word) ? k.colors.primary : /\b(false|fake|myth|wrong|no|misleading|debunked|untrue|lie)\b/i.test(word) ? "#e5484d"
  : /\b(true|real|fact|confirmed|yes|correct|verified|accurate)\b/i.test(word) ? "#2fbf71" : k.colors.primary);

const PACK2: MxRecipe[] = [
  // ============================== KINETIC TYPE ==============================
  {
    id: "ml-title-stack", name: "Word stack slam", family: "title",
    about: "A justified block of stacked words, every line set to the same width in tight heavy caps; each line rises out of its own mask on its spoken word and the stack settles a hair as it lands.",
    use: "A punchy hook or a three-to-six word verdict said with force (\"they lost everything\"); the hook and big turns only.",
    sample: { text: "They lost everything overnight" },
    build: (p, k, c) => {
      // Polished 2026-10-18: no scale slam (it was a 1.9x scale pop from a 14 px blur) - a masked rise per line in
      // 0.26 s on its word, the stack justified to one width with tight tracking, an accent rule above it.
      const lines = balance(p.text, 9, 5);
      const TR = -0.025;
      const block = Math.min(0.4, c.room);
      let sizes = lines.map((l) => fitSize([l], k.fonts.title, block, c.aspect, 0.17, 0.05, true, TR));
      // The whole stack stays within ~64% of the frame's height.
      const fit = Math.min(1, 0.64 / sizes.reduce((a, b) => a + b * 0.9, 0));
      sizes = sizes.map((s) => s * fit * c.scale);
      const lh = sizes.map((s) => s * 0.9);
      const total = lh.reduce((a, b) => a + b, 0);
      const pl = placeX(c.side);
      const top = (c.y ?? 0.5) - total / 2;
      let y = top;
      let wi = 0;
      const lands = lines.map((l) => { const at = c.wt(wi, 0.1, 0.22); wi += l.split(/\s+/).length; return at; });
      const big = sizes.indexOf(Math.max(...sizes));
      const weight = Math.max(800, k.titleWeight);
      const layers: Lay[] = lines.map((line, i) => {
        const yy = y + lh[i] / 2;
        y += lh[i];
        // The lines already up settle 0.3% of the frame as each later line lands (a weight, not a bounce).
        const bump: unknown[] = [[0, 0]];
        for (let j = i + 1; j < lines.length && bump.length < 14; j++) bump.push([lands[j], 0], [lands[j] + 0.05, 0.003], [lands[j] + 0.2, 0, "out"]);
        return text({ lines: [line], font: k.fonts.title, size: sizes[i], weight, color: i === big ? k.colors.primary : k.colors.text,
          upper: true, tracking: TR, x: pl.x, y: yy, anchor: pl.anchor, align: pl.align, lineH: 0.9,
          animator: { unit: "line", stagger: 0, dur: c.s(0.26), ease: "expoOut", from: { y: 1.0, blur: 3 }, at: [lands[i]], clip: true },
          extra: { keys: { y: bump } } });
      });
      const rx = pl.anchor === "l" ? pl.x : pl.anchor === "r" ? pl.x - 0.045 : 0.5 - 0.0225;
      layers.unshift(accentRule(k, rx, top - Math.max(0.025, sizes[0] * 0.28), "l", Math.max(0, lands[0] - 0.05)));
      return finish(layers, c, "blur", { ...quick("blur"), shade: titleShade(c) });
    },
  },
  {
    id: "ml-title-slice", name: "Split reveal", family: "title",
    about: "One big line cut through the middle: its top half slides in from one side, its bottom half from the other, and they lock together on a bright accent seam.",
    use: "A short line that turns the story (\"everything changed\", a name reveal); one line, at most five words.",
    sample: { text: "Everything changed" },
    build: (p, k, c) => {
      // Polished 2026-10-18: the halves travelled 40% of the frame and the line was unreadable for 0.6 s; now a big
      // tight line whose halves travel 9% and lock in 0.42 s with motion blur, the seam drawing out from the centre.
      // A long line becomes two: the cut then falls between them (the first line from one side, the second from
      // the other), so the words stay big.
      const lines = T(p.text).length > 15 ? split2(c.words) : [T(p.text)];
      const TR = -0.02;
      // 0.7 of the width by the estimate: heavy caps (Archivo 900) run ~15% wider than the face table says
      const size = fitSize(lines, k.fonts.title, 0.7, c.aspect, 0.17, 0.05, true, TR) * c.scale;
      const y = c.y ?? 0.5;
      const blockH = lines.length * size * 0.95;
      const dir = c.r(1) > 0.5 ? 1 : -1;
      const t0 = Math.max(0, c.wt(0, 0.1, 0) - c.s(0.1)), join = t0 + c.s(0.42);
      const half = (cut: [number, number], d: number) => text({ lines, font: k.fonts.title, size, weight: Math.max(800, k.titleWeight), color: k.colors.text,
        upper: true, tracking: TR, lineH: 0.95, x: 0.5, y, anchor: "c", align: "center", emph: c.words.length > 1 ? [c.words.length - 1] : [], emphColor: k.colors.primary,
        extra: { cut, mb: 1, keys: { x: [[0, 0.09 * d], [t0, 0.09 * d], [join, 0, "expoOut"]], opacity: [[0, 0], [t0, 0], [t0 + 0.1, 1]] } } });
      const w = Math.min(0.92, Math.max(...lines.map((l) => widthOf(l, k.fonts.title, size, c.aspect, true, TR))) * 1.06);
      // A dark band across the frame carries the line on any shot (the VidRush centre band): it draws on from the
      // left just before the halves arrive.
      const bandH = blockH + size * (p.sub ? 1.5 : 0.8);
      const layers: Lay[] = [
        { kind: "rect", x: 0, y: y + (p.sub ? size * 0.36 : 0), w: 1, h: bandH, anchor: "l", fill: "rgba(6,7,10,0.62)", color: "rgba(6,7,10,0.62)",
          keys: { draw: [[0, 0], [Math.max(0, t0 - 0.12), 0], [t0 + 0.2, 1, "expoOut"]] } },
        half([0, 0.5], -dir), half([0.5, 0], dir),
        { kind: "rect", x: 0.5, y: y + size * 0.01, w, h: Math.max(0.003, size * 0.03), fill: k.colors.primary, color: k.colors.primary,
          keys: { sx: [[0, 0], [join - 0.06, 0], [join + 0.24, 1, "expoOut"]], opacity: [[0, 0], [join - 0.06, 1], [join + 0.35, 1], [join + 0.75, 0, "out"]] } },
      ];
      if (p.sub) layers.push(text({ lines: [T(p.sub)], font: k.fonts.label, size: Math.max(0.03, size * 0.22), weight: 700, color: k.colors.muted, upper: true, tracking: 0.14,
        x: 0.5, y: y + blockH / 2 + size * 0.38, anchor: "c", align: "center", extra: { keys: { opacity: [[0, 0], [join + 0.1, 0], [join + 0.35, 1, "out"]], y: [[0, 0.01], [join + 0.1, 0.01], [join + 0.38, 0, "expoOut"]] } } }));
      return finish(layers, c, "blur", { ...quick("blur"), shade: { kind: "vignette", amount: 0.55 } });
    },
  },
  {
    id: "ml-title-wipe", name: "Spoken mask wipe", family: "title",
    about: "A mask wipes big heavy words on left to right in step with the voice, line by line; an accent rule and an optional sub line settle under the last word.",
    use: "A full sentence worth reading along (a thesis, the stakes); lines up to about 8 words, any section.",
    sample: { text: "The deal that built a city", wordAt: [0.2, 0.5, 0.75, 1.0, 1.2, 1.6] },
    build: (p, k, c) => {
      // Polished 2026-10-18: the words were thin and small (9% at most) with a full-height bar floating off the line
      // (its x was an estimate of the type's width); now heavy tight caps up to 12%, no caret, an accent rule to finish.
      const TR = -0.015;
      const lines = balance(p.text, 18, 3);
      const weight = Math.max(800, k.titleWeight);
      const size = fitSize(lines, k.fonts.title, c.side === "center" ? 0.8 : Math.min(0.58, c.room), c.aspect, 0.13, 0.05, true, TR) * c.scale;
      const LH = 1.0;
      const y0 = (c.y ?? 0.5) - ((lines.length - 1) * size * LH) / 2;
      const layers: Lay[] = [];
      let wi = 0, last = 0;
      // Each line is its own layer, anchored to its side (centred: on the middle) so the browser's real widths decide
      // where it sits; the wipe reveals its own box from the left, word by word, on the voice.
      const pl = placeX(c.side);
      lines.forEach((line, li) => {
        const words = line.split(/\s+/);
        const keys: unknown[] = [[0, 0]];
        let chars = 0;
        const first = c.wt(wi, 0.15 + li * 0.45, 0.16);
        keys.push([Math.max(0, first - c.s(0.12)), 0]);
        words.forEach((w, j) => {
          chars += w.length + (j < words.length - 1 ? 1 : 0);
          const f = Math.min(1, chars / line.length);
          const t = c.wt(wi + j, 0.15 + li * 0.45, 0.16) + c.s(0.14);
          if (keys.length < 15) keys.push([t, f, "out"]);
        });
        last = Math.max(last, (keys[keys.length - 1] as number[])[0]);
        wi += words.length;
        layers.push(text({ lines: [line], font: k.fonts.title, size, weight, color: k.colors.text, upper: true, tracking: TR, lineH: LH,
          x: pl.x, y: y0 + li * size * LH, anchor: pl.anchor, align: pl.align, extra: { keys: { wipe: keys } } }));
      });
      const ry = y0 + (lines.length - 1) * size * LH + size * 0.72;
      const rw = 0.06;
      layers.push(accentRule(k, pl.anchor === "l" ? pl.x : pl.anchor === "r" ? pl.x - rw : 0.5 - rw / 2, ry, "l", last + 0.05, rw));
      if (p.sub) layers.push(text({ lines: [T(p.sub)], font: k.fonts.body, size: Math.max(0.032, size * 0.34), weight: 600, color: k.colors.muted,
        x: pl.x, y: ry + Math.max(0.045, size * 0.5), anchor: pl.anchor, align: pl.align,
        extra: { keys: { opacity: [[0, 0], [last + 0.12, 0], [last + 0.4, 1, "out"]], y: [[0, 0.012], [last + 0.12, 0.012], [last + 0.42, 0, "expoOut"]] } } }));
      return finish(layers, c, "blur", { ...quick("blur"), shade: titleShade(c) });
    },
  },
  {
    id: "ml-title-cardflip", name: "3D card flip", family: "title",
    about: "An accent card with a short setup turns over in 3D on the spoken word and shows the answer on its back.",
    use: "A setup and its answer (kicker = the setup, e.g. \"The cause\"; text = the reveal); question-then-answer moments.",
    sample: { text: "A single loose bolt", kicker: "The cause" },
    build: (p, k, c) => {
      const back = balance(p.text, 16, 3);
      const size = fitSize(back, k.fonts.title, 0.46, c.aspect, 0.085, 0.045, true) * c.scale;
      const front = T(p.kicker || "?");
      const fsz = fitSize([front], k.fonts.title, 0.4, c.aspect, 0.11, 0.05, true) * c.scale;
      const tf = Math.max(c.s(1.25), c.wt(0, 1.3, 0) - c.s(0.25));
      const half = c.s(0.26);
      const y = c.y ?? 0.5;
      return finish([
        text({ lines: [front], font: k.fonts.title, size: fsz, weight: k.titleWeight, color: k.colors.pillText, upper: true, x: 0.5, y, anchor: "c", align: "center",
          extra: { shadow: "none", panel: { color: k.colors.primary, opacity: 1, pad: 0.04, radius: 0.012, blur: 0, padY: 0.03 },
            keys: { rotY: [[0, 0], [tf, 0], [tf + half, 90, "in"]], opacity: [[0, 0], [c.s(0.3), 1, "out"], [tf + half, 1], [tf + half + 0.01, 0]],
              scale: [[0, 0.82], [c.s(0.7), 1, "expoOut"]], y: [[0, 0.04], [c.s(0.7), 0, "expoOut"]] } } }),
        text({ lines: back, font: k.fonts.title, size, weight: k.titleWeight, color: k.colors.text, upper: true, x: 0.5, y, anchor: "c", align: "center",
          emph: [c.words.length - 1], emphColor: k.colors.primary,
          extra: { shadow: "none", panel: { color: k.colors.bg2, opacity: 0.92, pad: 0.04, radius: 0.012, blur: 10, padY: 0.03 },
            keys: { rotY: [[0, -90], [tf + half, -90], [tf + half + c.s(0.55), 0, "quintOut"]], opacity: [[0, 0], [tf + half - 0.01, 0], [tf + half, 1]] } } }),
      ], c, "blur", { persp: 1000, shade: { kind: "vignette", amount: 0.42 } });
    },
  },
  {
    id: "ml-title-extrude", name: "Extruded 3D title", family: "title",
    about: "A monumental title in tight heavy caps with a shallow, dark extrusion: the words rise on their spoken beats, the block settles from a gentle 3D angle and keeps turning slowly; an accent rule draws out under it.",
    use: "An episode / topic title or a name that deserves a monument (\"Burj Khalifa\", \"The Great Fire\"); one to four words, openings and chapter starts.",
    sample: { text: "The Great Fire" },
    build: (p, k, c) => {
      // Polished 2026-10-18: it swung 42 degrees in from scale 0.62 with a 12-step extrusion in a muddy accent and
      // words popping from 1.35x; now a settle from 18 degrees / 0.94 (done by ~1.0 s, the registry's hit), a
      // 7-step extrusion in a near-black tint of the accent, words rising in 0.3 s, a slow living turn.
      const TR = -0.03;
      const lines = balance(p.text, 12, 2);
      const size = fitSize(lines, k.fonts.title, 0.7, c.aspect, 0.19, 0.06, true, TR) * c.scale;
      const dir = c.r(2) > 0.5 ? 1 : -1;
      const y = c.y ?? 0.47;
      const lastW = c.wt(c.words.length - 1, 0.1, 0.12);
      const bh = lines.length * size * 0.9;
      const lw = Math.min(0.9, Math.max(...lines.map((l) => widthOf(l, k.fonts.title, size, c.aspect, true, TR))));
      const layers: Lay[] = [
        text({ lines, font: k.fonts.title, size, weight: 900, color: k.colors.text, upper: true, tracking: TR, x: 0.5, y, anchor: "c", align: "center",
          lineH: 0.9, emph: lines.length > 1 || c.words.length > 2 ? [c.words.length - 1] : [], emphColor: k.colors.primary,
          animator: wordAnim(c, { opacity: 0, y: 0.3, blur: 4 }, 0.1, 0.12, 0.3, "expoOut"),
          extra: { extrude: 7, extrudeColor: mix(k.colors.primary, -0.8), shadow: "soft",
            keys: { rotX: [[0, 18], [c.s(1.0), 6, "expoOut"], [p.dur, 3, "linear"]], rotY: [[0, -18 * dir], [c.s(1.0), -6 * dir, "expoOut"], [p.dur, 4 * dir, "linear"]],
              scale: [[0, 0.94], [c.s(1.0), 1, "expoOut"], [p.dur, 1.035, "linear"]] } } }),
        // the rule grows out from the centre (sx), under the block
        { kind: "rect", x: 0.5, y: y + bh / 2 + size * 0.22, w: Math.min(0.16, lw * 0.35), h: Math.max(0.005, size * 0.045), fill: k.colors.primary, color: k.colors.primary,
          keys: { sx: [[0, 0], [lastW + 0.15, 0], [lastW + 0.45, 1, "expoOut"]] } },
      ];
      if (p.kicker) layers.push(text({ lines: [T(p.kicker)], font: k.fonts.label, size: Math.max(0.03, size * 0.2), weight: 700, color: k.colors.muted, upper: true,
        tracking: 0.16, x: 0.5, y: y - bh / 2 - size * 0.3, anchor: "c", align: "center", extra: { keys: { opacity: [[0, 0], [c.s(0.2), 1, "out"]], y: [[0, 0.01], [c.s(0.3), 0, "expoOut"]] } } }));
      if (p.sub) layers.push(text({ lines: [T(p.sub)], font: k.fonts.body, size: Math.max(0.032, size * 0.22), weight: 600, color: k.colors.text,
        x: 0.5, y: y + bh / 2 + size * 0.55, anchor: "c", align: "center", extra: { keys: { opacity: [[0, 0], [lastW + 0.3, 0], [lastW + 0.55, 1, "out"]] } } }));
      return finish(layers, c, "scale", { ...quick("scale"), persp: 1100, shade: { kind: "full", amount: 0.34 } });
    },
  },
  {
    id: "ml-title-redact", name: "Declassified", family: "title",
    about: "A typed paper slip with every word blacked out; each bar pulls away the moment its word is spoken.",
    use: "A secret, a leak, a hidden fact or a document quote coming out (\"the report admitted...\"); crime, history, politics, business.",
    sample: { text: "The test was never approved", kicker: "Declassified", wordAt: [0.4, 0.7, 1.0, 1.3, 1.6] },
    build: (p, k, c) => {
      const lines = balance(p.text, 22, 3);
      const size = fitSize(lines, "mono", 0.5, c.aspect, 0.06, 0.032) * c.scale;
      const pl = placeX(c.side);
      return finish([
        text({ lines, font: "mono", size, weight: 700, color: "#151515", x: pl.x, y: c.y ?? 0.5, anchor: pl.anchor, align: "left", lineH: 1.35,
          animator: wordAnim(c, { y: 0 }, 0.6, 0.28, 0.32, "inOut"),
          extra: { redact: "#0c0c0c", shadow: "none", panel: { color: "#efe9dc", opacity: 0.97, pad: 0.03, radius: 0.002, blur: 0, padY: 0.03 },
            kicker: p.kicker ? { text: T(p.kicker).toUpperCase(), size: size * 0.55, color: "#ffffff", bg: "#b3261e", at: c.s(0.2) } : undefined,
            keys: { y: [[0, 0.05], [c.s(0.7), 0, "expoOut"]], rot: [[0, -4], [c.s(0.8), -1.2, "expoOut"]], opacity: [[0, 0], [c.s(0.25), 1, "out"]] } } }),
      ], c, "drop", { shade: { kind: c.side === "center" ? "vignette" : c.side, amount: 0.45 } });
    },
  },
  // ============================== DATA ==============================
  {
    id: "ml-data-race", name: "Bar race", family: "data",
    about: "Horizontal bars grow on their spoken names, figures counting along, then re-sort themselves into rank order.",
    use: "Three to six things compared by one figure (countries, companies, players); items as \"Name 41\" in the narration's order.",
    sample: { text: "Most visited countries", sub: "International arrivals, millions", items: ["Spain 85", "France 100", "Italy 57", "USA 66"] },
    build: (p, k, c) => {
      const data = rowsOf(p, 6);
      if (!data.length) return finish([], c);
      return finish([
        ...chartTitle(p, k, c, 0.19, 0.2),
        { kind: "chart", chart: "race", data, times: itemTimes(p, c, data.length, 0.8, p.dur), x: 0.5, y: 0.6, w: 0.7 * c.scale, h: Math.min(0.62, 0.125 * data.length) * c.scale,
          fill: k.colors.primary, color: k.colors.text, color2: k.colors.secondary, offColor: hexA(k.colors.text, 0.08), emphColor: k.colors.pillText,
          font: k.fonts.label, font2: k.fonts.number, size: 0.042 * c.scale, prefix: p.prefix || "", suffix: p.suffix || "", decimals: p.decimals || 0, bdur: c.s(0.9) },
      ], c, "fade", { shade: { kind: "full", amount: 0.58 } });
    },
  },
  {
    id: "ml-data-line", name: "Line draw-on", family: "data",
    about: "A trend line draws itself point by point under a soft fill; the last point pulses and a callout lands with its figure.",
    use: "A figure changing over time (rose, fell, doubled, grew since...); items as \"2010 4.2\" (period then figure), three to eight points.",
    sample: { text: "Global smartphone users", sub: "Billions", items: ["2012 1.1", "2015 1.9", "2018 2.9", "2021 3.6", "2024 4.6"], suffix: "B", decimals: 1 },
    build: (p, k, c) => {
      const data = (p.items || []).slice(0, 8).map((it, i) => {
        const m = /^(\S+)\s+(.+)$/.exec(String(it).trim());
        const r = m ? parseItem(`x ${m[2]}`, p.values?.[i]) : parseItem(String(it), p.values?.[i]);
        return { l: m ? m[1] : r.l, v: r.v, pre: r.pre, suf: r.suf };
      }).filter((d) => d.v !== null);
      if (data.length < 2) return finish([], c);
      return finish([
        ...chartTitle(p, k, c, 0.15, 0.17),
        { kind: "chart", chart: "line", data, times: itemTimes(p, c, data.length, 0.7, p.dur), x: 0.5, y: 0.6, w: 0.76 * c.scale, h: 0.6 * c.scale,
          fill: k.colors.primary, color: k.colors.text, color2: k.colors.muted, offColor: hexA(k.colors.text, 0.12), emphColor: k.colors.pillText,
          font: k.fonts.label, font2: k.fonts.number, size: 0.036 * c.scale, prefix: p.prefix || "", suffix: p.suffix || "", decimals: p.decimals || 0, hi: data.length - 1 },
      ], c, "fade", { shade: { kind: "full", amount: 0.58 } });
    },
  },
  {
    id: "ml-data-donut", name: "Donut build", family: "data",
    about: "A donut builds slice by slice on the spoken parts; the first slice pops out and its share counts up in the middle.",
    use: "A whole split into two to five parts (shares, budgets, sources); items as \"Coal 36%\", the part the line is about first.",
    sample: { text: "Where the power comes from", items: ["Coal 36%", "Gas 22%", "Hydro 15%", "Other 27%"], suffix: "%" },
    build: (p, k, c) => {
      const data = rowsOf(p, 5).filter((d) => d.v !== null);
      if (!data.length) return finish([], c);
      return finish([
        ...chartTitle(p, k, c, 0.17, 0.18),
        { kind: "chart", chart: "donut", data, times: itemTimes(p, c, data.length, 0.7, p.dur), x: 0.5, y: 0.6, w: 0.7 * c.scale, h: 0.6 * c.scale, hi: 0,
          fill: k.colors.primary, color: k.colors.text, color2: k.colors.muted, offColor: hexA(k.colors.text, 0.3), emphColor: k.colors.pillText,
          palette: [k.colors.secondary, k.colors.muted, mix(k.colors.primary, -0.35), k.colors.region], font: k.fonts.label, font2: k.fonts.number,
          size: 0.04 * c.scale, prefix: p.prefix || "", suffix: p.suffix || "", decimals: p.decimals || 0, bdur: c.s(0.7) },
      ], c, "fade", { shade: { kind: "full", amount: 0.6 } });
    },
  },
  {
    id: "ml-data-grid", name: "Stat grid", family: "data",
    about: "Two to four glass tiles rise in turn, each figure counting up over its label, a kit-accent rule drawing across its top.",
    use: "Several figures said close together (a scorecard: cost, time, people, distance); items as \"Workers 3,000\" - two to four.",
    sample: { text: "The project in numbers", items: ["Workers 12,000", "Years 6", "Cost $1.5B", "Floors 163"] },
    build: (p, k, c) => {
      const data = rowsOf(p, 4).filter((d) => d.v !== null);
      if (!data.length) return finish([], c);
      const h = (data.length > 3 ? 0.54 : 0.34) * c.scale;
      return finish([
        ...chartTitle(p, k, c, 0.17, 0.2),
        { kind: "chart", chart: "grid", data, times: itemTimes(p, c, data.length, 0.6, p.dur), x: 0.5, y: 0.61, w: 0.7 * c.scale, h, hi: 0,
          fill: k.colors.primary, color: k.colors.number, color2: k.colors.muted, font: k.fonts.label, font2: k.fonts.number, size: 0.036 * c.scale,
          prefix: p.prefix || "", suffix: p.suffix || "", decimals: p.decimals || 0 },
      ], c, "fade", { shade: { kind: "full", amount: 0.5 } });
    },
  },
  {
    id: "ml-data-timeline", name: "Timeline scrubber", family: "data",
    about: "A track draws across, then a playhead scrubs from date to date as each is spoken, lighting it and its caption.",
    use: "Three to six dated events in order (a history, a career, a build); items as \"1872 First park\" - the date first.",
    sample: { text: "How it happened", items: ["1903 First flight", "1927 Atlantic", "1969 Moon", "2004 Private space"] },
    build: (p, k, c) => {
      const data = (p.items || []).slice(0, 6).map((l) => ({ l: String(l).trim(), v: null }));
      if (!data.length) return finish([], c);
      return finish([
        ...chartTitle(p, k, c, 0.1, 0.22),
        { kind: "chart", chart: "timeline", data, times: itemTimes(p, c, data.length, 1.0, p.dur), x: 0.5, y: 0.6, w: 0.84 * c.scale, h: 0.42 * c.scale,
          fill: k.colors.primary, color: k.colors.text, color2: k.colors.muted, offColor: hexA(k.colors.text, 0.25), font: k.fonts.label, font2: k.fonts.number,
          size: 0.042 * c.scale },
      ], c, "fade", { shade: { kind: "full", amount: 0.55 } });
    },
  },
  {
    id: "ml-data-ladder", name: "Ranking ladder", family: "data",
    about: "A top-five ladder that fills from the bottom rung up; number one lands last, in the accent, with a glow.",
    use: "A countdown or a top list (\"the five biggest...\", \"number one is...\"); items #1 first (\"Tokyo 37\" or just names), up to six.",
    sample: { text: "Largest cities", items: ["Tokyo 37M", "Delhi 33M", "Shanghai 29M", "Dhaka 23M", "Cairo 22M"] },
    build: (p, k, c) => {
      const data = rowsOf(p, 6);
      if (!data.length) return finish([], c);
      const n = data.length;
      const spread = itemTimes({ ...p, itemAt: undefined }, c, n, 0.8, p.dur);
      const times = data.map((_, i) => {
        const at = p.itemAt?.[i];
        return typeof at === "number" && Number.isFinite(at) && at >= 0 && at < p.dur ? at : spread[n - 1 - i];
      });
      return finish([
        ...chartTitle(p, k, c, 0.21, 0.13),
        { kind: "chart", chart: "ladder", data, times, x: 0.5, y: 0.58, w: 0.58 * c.scale, h: Math.min(0.68, 0.125 * n) * c.scale,
          fill: k.colors.primary, color: k.colors.text, color2: k.colors.muted, emphColor: k.colors.pillText, font: k.fonts.label, font2: k.fonts.number,
          size: 0.042 * c.scale, prefix: p.prefix || "", suffix: p.suffix || "", decimals: p.decimals || 0 },
      ], c, "fade", { shade: { kind: "full", amount: 0.55 } });
    },
  },
  {
    id: "ml-data-split", name: "Before / after slider", family: "data",
    about: "A slider handle sweeps across the shot: one side turns into an old black-and-white print, the other stays as it is now, labelled.",
    use: "Then versus now, before versus after, old versus new over one shot (items = the two labels, e.g. \"1950\", \"Today\").",
    sample: { text: "The same street, seventy years apart", items: ["1950", "Today"] },
    build: (p, k, c) => {
      const items = (p.items || []).slice(0, 2);
      const lines = balance(p.text, 40, 2);
      const size = fitSize(lines, k.fonts.body, 0.6, c.aspect, 0.04, 0.026) * c.scale;
      return finish([
        { kind: "fx", effect: "split", x: c.side === "left" ? 0.42 : c.side === "right" ? 0.58 : 0.5, y: 0.5, w: 1, h: 1, items: items.length === 2 ? items : ["Before", "After"],
          fill: k.colors.primary, color: k.colors.text, font: k.fonts.label, size: 0.032 * c.scale },
        text({ lines, font: k.fonts.body, size, weight: 600, color: k.colors.text, x: 0.5, y: 0.86, anchor: "c", align: "center",
          animator: wordAnim(c, { opacity: 0, y: 0.3, blur: 4 }, 0.9, 0.08, 0.5, "out"), extra: { shadow: "soft" } }),
      ], c, "fade", { shade: { kind: "bottom", amount: 0.45 } });
    },
  },
  // ============================== CALLOUTS ==============================
  {
    id: "ml-co-lens", name: "Magnifier focus", family: "callout",
    about: "A magnifying glass glides onto one point of the shot as it is named: everything else blurs and dims, the lens stays crisp and richer.",
    use: "Pointing at a detail the viewer must find in the picture (a crack, a face in a crowd, a line on a map); give point when known.",
    sample: { text: "The crack", point: { x: 0.6, y: 0.45 } },
    build: (p, k, c) => {
      const pt = p.point || { x: c.r(3) > 0.5 ? 0.6 : 0.4, y: 0.46 };
      const r = 0.17 * c.scale;
      const hit = c.wt(0, 0.3, 0);
      const right = pt.x < 0.62;
      const rx = r / c.aspect;
      return finish([
        { kind: "fx", effect: "lens", x: pt.x, y: pt.y, w: r, h: 1, mid: hit, fill: k.colors.primary, color2: k.colors.bg2, seed: Math.round(c.r(4) * 100) },
        ...(p.text ? [{ kind: "pill", text: T(p.text).toUpperCase(), size: 0.036 * c.scale, fill: k.colors.pillBg, color: k.colors.pillText, font: k.fonts.label,
          x: right ? pt.x + rx * 1.1 : pt.x - rx * 1.1, y: pt.y - r * 0.85, anchor: right ? "l" : "r", wipeFrom: right ? "l" : "r",
          keys: { wipe: [[0, 0], [hit + c.s(0.7), 0], [hit + c.s(1.1), 1, "expoOut"]] } }] : []),
      ], c, "fade");
    },
  },
  {
    id: "ml-co-sticky", name: "Sticky note", family: "callout",
    about: "A sticky note in a light tint of the kit accent slaps onto the frame and the words write themselves in by hand.",
    use: "A reminder, a takeaway or a to-do the narrator states (\"remember this\", \"rule number one\"); up to about 10 words.",
    sample: { text: "Never sell in a panic", sub: "Rule one" },
    build: (p, k, c) => {
      const chars = p.text.length;
      const w = 0.21 * c.scale;
      const inner = 0.8 * w * c.aspect;
      const size = Math.max(0.026, Math.min(0.066, Math.sqrt((inner * inner * 0.7) / Math.max(4, chars * 0.42 * 1.08))));
      const dir = c.side === "left" ? -1 : 1;
      const x = c.side === "center" ? 0.5 : c.side === "left" ? 0.24 : 0.76;
      return finish([
        { kind: "card", card: "sticky", x, y: c.y ?? 0.45, w, text: T(p.text), label: p.sub ? T(p.sub) : "", fill: mix(k.colors.primary, 0.62), color: "#1d1d1f",
          emphColor: mix(k.colors.primary, -0.25), size, mid: Math.max(c.s(0.45), c.wt(0, 0.5, 0)),
          keys: { scale: [[0, 1.35], [c.s(0.5), 1, "expoOut"]], opacity: [[0, 0], [c.s(0.12), 1]], blur: [[0, 10], [c.s(0.35), 0]],
            rot: [[0, 12 * dir], [c.s(0.7), -2.5 * dir, "backOut"], [p.dur, -1 * dir, "sine"]], y: [[0, -0.05], [c.s(0.5), 0, "expoOut"]] } },
      ], c, "drop");
    },
  },
  {
    id: "ml-co-polaroid", name: "Polaroid drop", family: "callout",
    about: "A polaroid frame tumbles onto the shot and the moment inside it develops from white, a handwritten caption underneath.",
    use: "Freezing a moment as a memory (a person, a place, a year: \"summer 1969\"); caption up to four words.",
    sample: { text: "Summer, 1969" },
    build: (p, k, c) => {
      const dir = c.side === "left" ? -1 : 1;
      const x = c.side === "center" ? 0.5 : c.side === "left" ? 0.3 : 0.7;
      const w = 0.25 * c.scale;
      return finish([
        { kind: "card", card: "polaroid", x, y: c.y ?? 0.48, w, text: T(p.text), size: Math.min(0.05, fitSize([T(p.text)], "hand", w * 0.8, c.aspect, 0.05, 0.022)),
          mid: c.s(0.55), emphColor: k.colors.primary, color: "#222",
          keys: { y: [[0, -0.75], [c.s(0.8), 0, "expoOut"]], rot: [[0, -18 * dir], [c.s(1.0), 4 * dir, "backOut"], [p.dur, 3 * dir, "sine"]],
            scale: [[0, 1.12], [c.s(0.85), 1, "expoOut"]] }, mb: 0.6 },
      ], c, "drop", { shade: { kind: "vignette", amount: 0.35 } });
    },
  },
  {
    id: "ml-co-document", name: "Document zoom", family: "callout",
    about: "A typed page settles into the frame with its quoted line set large in the middle; an accent marker sweeps under each word as it is read while the camera pushes in on the line.",
    use: "Quoting a report, a letter, a ruling, a contract or a study (the narrator reads its line); kicker = the source, sub = a date.",
    sample: { text: "The levees will not hold", kicker: "Army Corps report", sub: "1965" },
    build: (p, k, c) => {
      // Polished 2026-10-18 (round 2): the quoted line was 3% type in row 7 of a tall page that rose for 0.9 s from
      // 28 degrees, and the push-in (to 1.42x) cropped the page off-centre; now the line is set at up to 6% in the
      // middle of the page, the page settles in 0.3 s, the marker lands word by word on the voice (never before the
      // registry's marker sound at `mid`), and the push centres on the line. Off-centre on auto when a face is there.
      const mid = Math.max(c.s(1.1), c.wt(0, 1.1, 0));
      const quote = T(p.text);
      const w = (c.side === "center" ? 0.44 : Math.min(0.44, Math.max(0.3, c.room + 0.02))) * c.scale;
      const x = c.side === "center" ? 0.5 : c.side === "left" ? 0.06 + w / 2 : 0.94 - w / 2;
      // typed face, ~0.62 em per character; at most ~3 lines of 14-26 characters inside the page's 82%
      const cpl = Math.max(14, Math.min(26, Math.ceil(quote.length / 3)));
      const size = Math.max(0.036, Math.min(0.062, (w * 0.82 * c.aspect) / (cpl * 0.62))) * Math.min(1.15, c.scale);
      let prev = 0;
      const times = c.words.map((_, i) => (prev = Math.max(prev, mid, c.wt(i, 1.1, 0.12))));
      return finish([
        { kind: "card", card: "doc", x, y: c.y ?? 0.5, w, h: 0.8, text: quote, label: p.kicker ? T(p.kicker) : "Document", meta: p.sub ? T(p.sub) : "",
          fill: "#f6f2e8", color: "#141414", emphColor: k.colors.primary, mid, times, size, seed: Math.round(c.r(5) * 1000),
          keys: { y: [[0, 0.035], [c.s(0.3), 0, "expoOut"]], rotX: [[0, 10], [c.s(0.32), 0, "expoOut"]], opacity: [[0, 0], [c.s(0.14), 1, "out"]],
            scale: [[0, 0.97], [c.s(0.3), 1, "expoOut"], [mid, 1], [mid + c.s(1.3), 1.18, "inOut"], [p.dur, 1.22, "linear"]], rot: [[0, c.side === "right" ? 1 : -1]] } },
      ], c, "fade", { ...quick("fade"), persp: 1200, shade: c.side === "center" ? { kind: "full", amount: 0.5 } : { kind: c.side, amount: 0.6 } });
    },
  },
  {
    id: "ml-co-quote", name: "Quote card with portrait", family: "callout",
    about: "An editorial pull quote: a big accent quotation mark, the words set large in italic as they are said, then the speaker's name in tracked caps and their role under a short accent rule.",
    use: "Someone's own words quoted in the narration with the speaker named (sub = speaker, kicker = their role); up to about 20 words.",
    sample: { text: "We did not know the river could rise that fast", sub: "Maria Lopez", kicker: "Resident" },
    build: (p, k, c) => {
      // Polished 2026-10-18: the words were 3-5% type in a small glass box at the bottom with a fake initials
      // avatar; now the quote owns the frame like a magazine pull quote - italic at up to 7% on a side scrim, each
      // word landing on its spoken time in 0.28 s, the attribution settling once the last word is said.
      const side = c.side;
      const pl = placeX(side);
      const lines = balance(T(p.text), 20, 4);
      const size = fitSize(lines, "serif-italic", side === "center" ? 0.66 : Math.min(0.5, c.room), c.aspect, 0.085, 0.045) * c.scale;
      const LH = 1.14;
      const y = c.y ?? 0.5;
      const bh = lines.length * size * LH;
      const times = c.words.map((_, i) => c.wt(i, 0.35, 0.07));
      const done = (times[times.length - 1] || 0.5) + 0.3;
      const mk = size * 2.8;
      // the mark hangs at the block's start edge (centred: over the middle)
      const qx = pl.anchor === "l" ? pl.x - size * 0.06 : pl.anchor === "r" ? pl.x + size * 0.06 : 0.5;
      const nameSize = Math.max(0.034, size * 0.42);
      const ay = y + bh / 2 + Math.max(0.05, size * 0.9);
      const layers: Lay[] = [
        text({ lines: ["“"], font: "serif", size: mk, weight: 700, color: k.colors.primary, x: qx, y: y - bh / 2 - mk * 0.12, anchor: pl.anchor, align: pl.align, lineH: 1,
          extra: { shadow: "none", keys: { opacity: [[0, 0], [c.s(0.25), 1, "out"]], y: [[0, 0.015], [c.s(0.3), 0, "expoOut"]] } } }),
        text({ lines, font: "serif-italic", size, weight: 500, color: k.colors.text, x: pl.x, y, anchor: pl.anchor, align: pl.align, lineH: LH,
          animator: { unit: "word", stagger: c.s(0.07), dur: c.s(0.28), ease: "expoOut", from: { opacity: 0, y: 0.22, blur: 3 }, at: times } }),
      ];
      if (p.sub) layers.push(text({ lines: [T(p.sub)], font: k.fonts.label, size: nameSize, weight: 800, color: k.colors.primary, upper: true, tracking: 0.14,
        x: pl.x, y: ay, anchor: pl.anchor, align: pl.align,
        extra: { deco: { rule: k.colors.primary, at: done - 0.05 },
          sub: p.kicker ? { text: T(p.kicker), size: Math.max(0.028, nameSize * 0.85), font: k.fonts.body, weight: 500, color: k.colors.muted, tracking: 0.01, upper: false, at: done + 0.12 } : undefined,
          keys: { opacity: [[0, 0], [done, 0], [done + 0.22, 1, "out"]], y: [[0, 0.012], [done, 0.012], [done + 0.28, 0, "expoOut"]] } } }));
      return finish(layers, c, "blur", { ...quick("blur"), shade: side === "center" ? { kind: "full", amount: 0.5 } : { kind: side, amount: 0.68 } });
    },
  },
  {
    id: "ml-co-post", name: "Social post", family: "callout",
    about: "A clean social post card settles in, its words set large and lighting from a ghost grey as they are read; then the heart fills (and the likes count up, when they are said).",
    use: "A post, tweet or comment the narration quotes (sub = the account's name, kicker = a date, value = likes only when said).",
    sample: { text: "This is the worst traffic I have ever seen in this city", sub: "Daniel Reyes", kicker: "2h", value: 48200 },
    build: (p, k, c) => {
      // Polished 2026-10-18 (round 2): 3.4% text with unread words at 15% (unreadable), a 0.8 s rise from a 20 degree
      // tilt and a bouncing heart; now the words are set at up to 5.8% in at most ~4 lines, unread words wait at 32%
      // (the timeline's ghost state), the card settles in 0.3 s and the heart fills without a bounce on `mid` (the
      // registry's pop sound).
      const times = c.words.map((_, i) => c.wt(i, 0.5, 0.1));
      const w = (c.side === "center" ? 0.42 : Math.min(0.42, Math.max(0.32, c.room))) * c.scale;
      const x = c.side === "center" ? 0.5 : c.side === "left" ? 0.06 + w / 2 : 0.94 - w / 2;
      const cpl = Math.max(16, Math.ceil(T(p.text).length / 4));
      const size = Math.max(0.038, Math.min(0.058, (w * 0.88 * c.aspect) / (cpl * 0.5))) * Math.min(1.15, c.scale);
      return finish([
        { kind: "card", card: "social", x, y: c.y ?? 0.5, w, text: T(p.text), label: p.sub ? T(p.sub) : "", meta: p.kicker ? T(p.kicker) : "",
          times, mid: (times[times.length - 1] || 0.6) + c.s(0.3), fill: "#ffffff", color: "#0f1419", emphColor: k.colors.primary, size,
          ...(typeof p.value === "number" ? { valueTo: p.value } : {}),
          keys: { y: [[0, 0.035], [c.s(0.3), 0, "expoOut"]], rotX: [[0, -8], [c.s(0.32), 0, "expoOut"]], opacity: [[0, 0], [c.s(0.14), 1, "out"]],
            scale: [[0, 0.97], [c.s(0.3), 1, "expoOut"], [p.dur, 1.025, "linear"]] } },
      ], c, "drop", { ...quick("drop"), persp: 1100, shade: c.side === "center" ? { kind: "full", amount: 0.42 } : { kind: c.side, amount: 0.55 } });
    },
  },
  {
    id: "ml-co-phone", name: "Phone messages", family: "callout",
    about: "A phone settles into frame at a slight 3D angle and a chat plays out on it from the bottom up, typing dots first, each bubble rising in on its time.",
    use: "Texts, DMs or messages the narration reads out (items = the messages in order, sub = the contact's name); one to four short messages.",
    sample: { text: "Are you safe?", sub: "Mom", items: ["Are you safe?", "We are on the roof", "Help is coming"] },
    build: (p, k, c) => {
      // Polished 2026-10-18 (round 2): 3% bubbles popping from scale 0 with an overshoot on a phone that flew up half
      // the frame in 0.9 s from 34 degrees; now 3.6% bubbles rise in over 0.22 s, stacked from the bottom like a real
      // chat, on a phone that settles in 0.32 s and keeps a gentle turn. The first bubble stays at >= 1.1 s (the
      // registry's buzz).
      const items = (p.items && p.items.length ? p.items : [p.text]).slice(0, 4).map((s) => String(s).slice(0, 90));
      const times = itemTimes(p, c, items.length, 1.1, p.dur).map((t, i) => Math.max(t, c.s(1.1 + i * 0.3)));
      const dir = c.side === "left" ? -1 : 1;
      const w = 0.235 * c.scale;
      const x = c.side === "center" ? 0.5 : c.side === "left" ? 0.1 + w / 2 : 0.9 - w / 2;
      return finish([
        { kind: "card", card: "phone", x, y: c.y ?? 0.5, w, items, times, label: p.sub ? T(p.sub) : p.kicker ? T(p.kicker) : "",
          emphColor: k.colors.primary, color: "#ffffff", size: 0.036 * Math.min(1.15, c.scale),
          keys: { y: [[0, 0.06], [c.s(0.32), 0, "expoOut"]], opacity: [[0, 0], [c.s(0.14), 1, "out"]],
            rotY: [[0, 16 * dir], [c.s(0.4), 9 * dir, "expoOut"], [p.dur, 5 * dir, "linear"]],
            rotX: [[0, 7], [c.s(0.4), 2, "expoOut"]], rot: [[0, 2 * dir], [c.s(0.4), 0, "expoOut"]] } },
      ], c, "drop", { ...quick("drop"), persp: 1100, shade: c.side === "center" ? { kind: "full", amount: 0.42 } : { kind: c.side, amount: 0.55 } });
    },
  },
  {
    id: "ml-co-browser", name: "Browser window", family: "callout",
    about: "A browser window rises with its address typing in; the headline appears and a marker sweeps under it as it is read.",
    use: "A headline, article, website or search result the narration cites (kicker = the site, sub = a section or date; text = the headline as said).",
    sample: { text: "Record heat closes schools across the region", kicker: "dailynews.com", sub: "Breaking" },
    build: (p, k, c) => {
      const mid = Math.max(c.s(0.9), c.wt(0, 0.9, 0));
      return finish([
        { kind: "card", card: "browser", x: 0.5, y: c.y ?? 0.52, w: 0.54 * c.scale, h: 0.5 * c.scale, text: T(p.text), label: p.kicker ? T(p.kicker) : "",
          meta: p.sub ? T(p.sub) : "", fill: "#ffffff", color: "#111111", emphColor: k.colors.primary, font2: k.fonts.label, mid, seed: Math.round(c.r(6) * 1000),
          size: Math.max(0.038, Math.min(0.062, 2.3 / Math.max(30, p.text.length))) * c.scale,
          keys: { y: [[0, 0.06], [c.s(0.8), 0, "expoOut"]], rotX: [[0, 16], [c.s(0.9), 0, "expoOut"]], opacity: [[0, 0], [c.s(0.3), 1, "out"]],
            scale: [[0, 0.92], [c.s(0.85), 1, "expoOut"], [p.dur, 1.05, "linear"]] } },
      ], c, "fade", { persp: 1200, shade: { kind: "full", amount: 0.5 } });
    },
  },
  // ============================== EMPHASIS ==============================
  {
    id: "ml-em-scribble", name: "Scribble loop", family: "emphasis",
    about: "A fast marker scribble loops twice round the point as it is named, a handwritten note riding beside it.",
    use: "Circling something on screen in a loose, human way (a person, a car, a building); point when known, text = two or three words.",
    sample: { text: "That's him", point: { x: 0.55, y: 0.45 } },
    build: (p, k, c) => {
      const pt = p.point || { x: 0.5, y: 0.48 };
      const h = 0.3 * c.scale, w = (h / c.aspect) * 1.35;
      const hit = c.wt(0, 0.15, 0);
      const right = pt.x < 0.6;
      return finish([
        { kind: "scribble", scribble: "loop", x: pt.x, y: pt.y, w, h, color: k.colors.primary, stroke: 0.011, seed: 3 + Math.round(c.r(7) * 50),
          keys: { draw: [[0, 0], [hit, 0], [hit + c.s(0.75), 1, "inOut"]] } },
        ...(p.text ? [text({ lines: [T(p.text)], font: "hand", size: 0.07 * c.scale, weight: 700, color: k.colors.primary, x: right ? pt.x + w * 0.56 : pt.x - w * 0.56,
          y: pt.y - h * 0.62, anchor: right ? "l" : "r", align: right ? "left" : "right",
          animator: { unit: "char", stagger: c.s(0.03), dur: c.s(0.18), ease: "out", from: { opacity: 0, y: 0.15 } }, extra: { from: hit + c.s(0.5), keys: { rot: [[0, right ? -5 : 5]] } } })] : []),
      ], c, "fade");
    },
  },
  {
    id: "ml-em-swoosh", name: "Brush swoosh", family: "emphasis",
    about: "The line sets in large and a tapered brush stroke in the accent sweeps under it as its last word lands.",
    use: "A short line with a strong final word (\"and it worked\", \"completely free\"); up to six words, any section.",
    sample: { text: "And it actually worked" },
    build: (p, k, c) => {
      // Polished 2026-10-18: bigger tight caps rising out of their masks in 0.28 s on their words (they drifted up
      // from a blur over 0.55 s), the stroke snapping on under the last word in 0.32 s, a quicker exit.
      const TR = -0.02;
      const pl = placeX(c.side);
      const lines = c.room < 0.45 ? balance(p.text, 11, 3) : balance(p.text, 16, 2);
      const size = fitSize(lines, k.fonts.title, c.side === "center" ? 0.72 : Math.min(0.56, c.room), c.aspect, 0.135, 0.05, true, TR) * c.scale;
      const LH = 0.94;
      const y = c.y ?? 0.48;
      const lw = Math.min(0.9, Math.max(...lines.map((l) => widthOf(l, k.fonts.title, size, c.aspect, true, TR))));
      const last = c.wt(c.words.length - 1, 0.1, 0.07);
      const sx = pl.anchor === "l" ? pl.x + lw / 2 : pl.anchor === "r" ? pl.x - lw / 2 : 0.5;
      const by = y + (lines.length * size * LH) / 2;
      return finish([
        { kind: "scribble", scribble: "swoosh", x: sx, y: by - size * 0.12, w: lw * 1.04, h: size * 0.72, color: k.colors.primary, seed: 1 + Math.round(c.r(8) * 9),
          keys: { draw: [[0, 0], [last, 0], [last + c.s(0.32), 1, "expoOut"]] } },
        text({ lines, font: k.fonts.title, size, weight: Math.max(800, k.titleWeight), color: k.colors.text, upper: true, tracking: TR, lineH: LH,
          x: pl.x, y, anchor: pl.anchor, align: pl.align, animator: riseIn(c, 0.1, 0.07) }),
      ], c, "blur", { ...quick("blur"), shade: titleShade(c, 0.5, 0.3) });
    },
  },
  {
    id: "ml-em-looparrow", name: "Loop arrow", family: "emphasis",
    about: "A handwritten note, then a marker arrow that loops once on its way to the point on screen, its head snapping on.",
    use: "Naming something on screen with a bit of personality (\"the original\", \"still there today\"); point when known, two to four words.",
    sample: { text: "Still there today", point: { x: 0.64, y: 0.36 } },
    build: (p, k, c) => {
      const pt = p.point || { x: 0.62, y: 0.38 };
      const toLeft = pt.x > 0.5;
      const bw = 0.2 * c.scale, bh = 0.24 * c.scale;
      const cx = toLeft ? pt.x - bw / 2 : pt.x + bw / 2, cy = pt.y + bh / 2;
      const start = c.wt(0, 0.15, 0);
      const seed = 2 * (1 + Math.round(c.r(9) * 20)) + (toLeft ? 0 : 1);
      const nx = toLeft ? pt.x - bw : pt.x + bw;
      return finish([
        text({ lines: [T(p.text)], font: "hand", size: 0.07 * c.scale, weight: 700, color: k.colors.text, x: nx, y: pt.y + bh + 0.045,
          anchor: toLeft ? "r" : "l", align: toLeft ? "right" : "left",
          animator: { unit: "char", stagger: c.s(0.03), dur: c.s(0.18), ease: "out", from: { opacity: 0, y: 0.15 }, at: undefined }, extra: { keys: { rot: [[0, toLeft ? 4 : -4]] }, shadow: "hard" } }),
        { kind: "scribble", scribble: "looparrow", x: cx, y: cy, w: bw, h: bh, color: k.colors.primary, stroke: 0.01, seed,
          keys: { draw: [[0, 0], [start + c.s(0.45), 0], [start + c.s(1.35), 1, "inOut"]] } },
      ], c, "fade");
    },
  },
  {
    id: "ml-em-countdown", name: "Countdown ring", family: "emphasis",
    about: "A ring drains in steps while the figure in it ticks down; the last steps pulse and the ring flashes at zero.",
    use: "A countdown, a deadline or time running out (\"ten seconds\", \"three days left\"); value = the starting figure said, text = its unit.",
    sample: { text: "seconds", value: 10 },
    build: (p, k, c) => {
      const v = Math.max(1, Math.min(999, Math.round(typeof p.value === "number" ? p.value : 10)));
      const steps = v <= 12 ? v : 10;
      const t0 = Math.max(c.s(0.5), c.wt(0, 0.5, 0));
      const span = Math.max(1.5, Math.min(p.dur - t0 - 0.9, steps * 1.0));
      const st = span / steps;
      const R = 0.32 * c.scale;
      const cx = 0.5, cy = c.y ?? 0.47;
      const pk: unknown[] = [[0, 0], [t0, 0]];
      for (let i = 1; i <= steps && pk.length < 16; i++) pk.push([t0 + i * st, i / steps, "hold"]);
      const pulse: unknown[] = [[0, 1]];
      for (let i = Math.max(1, steps - 4); i <= steps && pulse.length < 15; i++) pulse.push([t0 + i * st - 0.01, 1], [t0 + i * st + 0.02, 1.14], [t0 + i * st + 0.3, 1, "out"]);
      const end = t0 + span;
      return finish([
        { kind: "ellipse", x: cx, y: cy, w: R / c.aspect, h: R, color: hexA(k.colors.text, 0.16), stroke: 0.016, keys: { draw: [[0, 0], [c.s(0.5), 1, "expoOut"]], rot: [[0, 38]] } },
        { kind: "ellipse", x: cx, y: cy, w: R / c.aspect, h: R, color: k.colors.primary, stroke: 0.016, keys: { draw: [[0, 0], [c.s(0.6), 1, "expoOut"], [t0, 1], [end, 0, "linear"]], rot: [[0, 38]] } },
        { kind: "ellipse", x: cx, y: cy, w: (R * 1.12) / c.aspect, h: R * 1.12, fill: hexA(k.colors.primary, 0.5), color: k.colors.primary, stroke: 0,
          keys: { opacity: [[0, 0], [end, 0], [end + 0.05, 0.9], [end + 0.6, 0, "out"]], scale: [[0, 0.9], [end, 0.9], [end + 0.6, 1.3, "out"]] } },
        { kind: "counter", valueFrom: v, valueTo: 0, group: false, font: k.fonts.number, size: R * 0.42, weight: 800, color: k.colors.number, x: cx, y: cy - R * 0.03, anchor: "c", align: "center",
          keys: { p: pk, scale: pulse, opacity: [[0, 0], [c.s(0.4), 1, "out"]] } },
        text({ lines: [T(p.text).toUpperCase()], font: k.fonts.label, size: R * 0.14, weight: 800, color: k.colors.primary, tracking: 0.16, x: cx, y: cy + R * 0.25,
          anchor: "c", align: "center", extra: { keys: { opacity: [[0, 0], [c.s(0.5), 0], [c.s(0.9), 1, "out"]] } } }),
      ], c, "scale", { shade: { kind: "vignette", amount: 0.5 } });
    },
  },
  {
    id: "ml-em-stamp", name: "Fact-check stamp", family: "emphasis",
    about: "The claim sets in large as a quote, word by word; on the verdict a solid badge hits beside it - red for false (the claim is struck through and dims), green for true, the accent otherwise.",
    use: "A claim being checked, a myth busted or confirmed (text = the claim as said; kicker = the verdict word said: False, Myth, True...).",
    sample: { text: "You only use ten percent of your brain", kicker: "Myth" },
    build: (p, k, c) => {
      // Polished 2026-10-18: a thin outlined stamp blurred in from 2.6x right over the words (they could not be read
      // under it); now a solid verdict badge that hits in 0.14 s below the claim, the claim struck through when false.
      const lines = balance(`“${T(p.text)}”`, 24, 3);
      const size = fitSize(lines, "serif-italic", 0.64, c.aspect, 0.085, 0.045) * c.scale;
      const LH = 1.15;
      const bh = lines.length * size * LH;
      const y = (c.y ?? 0.46) - size * 0.4;
      const hit = c.wt(c.words.length - 1, 0.2, 0.08) + c.s(0.45);
      const label = T(p.kicker || "Fact check").toUpperCase();
      const col = verdictColor(label, k);
      const bad = col === "#e5484d";
      const onCol = col === k.colors.primary ? k.colors.pillText : "#ffffff";
      const ss = Math.min(0.085, fitSize([label], "kinetic", 0.3, c.aspect, 0.085, 0.045, true)) * c.scale;
      const by = y + bh / 2 + ss * 1.05;
      const layers: Lay[] = [
        text({ lines, font: "serif-italic", size, weight: 500, color: k.colors.text, x: 0.5, y, anchor: "c", align: "center", lineH: LH,
          animator: wordAnim(c, { opacity: 0, y: 0.22, blur: 3 }, 0.2, 0.08, 0.28, "expoOut"),
          extra: { keys: { y: [[0, 0], [hit + 0.1, 0], [hit + 0.13, 0.004], [hit + 0.3, 0, "out"]],
            opacity: bad ? [[0, 1], [hit + 0.25, 1], [hit + 0.6, 0.55, "out"]] : [[0, 1]] } } }),
        text({ lines: [label], font: "kinetic", size: ss, weight: 900, color: onCol, upper: true, tracking: 0.06, x: 0.5, y: by, anchor: "c", align: "center",
          extra: { shadow: "none", panel: { color: col, opacity: 1, pad: Math.max(0.012, ss * 0.32), padY: Math.max(0.006, ss * 0.12), radius: 0.006, blur: 0 },
            keys: { scale: [[0, 1.3], [hit, 1.3], [hit + 0.14, 1, "expoOut"]], opacity: [[0, 0], [hit, 0], [hit + 0.05, 1]], blur: [[0, 5], [hit, 5], [hit + 0.12, 0]], rot: [[0, -4]] } } }),
      ];
      // False: each line of the claim struck through in the verdict colour, left to right, just after the hit.
      if (bad) lines.forEach((l, i) => {
        const lw = Math.min(0.9, widthOf(l, "serif-italic", size, c.aspect));
        const ly = y - bh / 2 + (i + 0.5) * size * LH + size * 0.06;
        layers.push({ kind: "rect", x: 0.5 - lw / 2, y: ly, w: lw, h: Math.max(0.004, size * 0.07), anchor: "l", fill: col, color: col,
          keys: { draw: [[0, 0], [hit + 0.06 + i * 0.06, 0], [hit + 0.3 + i * 0.06, 1, "expoOut"]] } });
      });
      return finish(layers, c, "fade", { ...quick("fade"), shade: { kind: "full", amount: 0.45 } });
    },
  },
  {
    id: "ml-em-strike", name: "Strike and correct", family: "emphasis",
    about: "The wrong words are set, a marker strikes them through, and the correction writes itself in by hand above in the accent.",
    use: "Correcting a belief or a figure (\"not 10 million - 30 million\", \"it wasn't an accident\"); text = the struck words, sub = the correction, both as said.",
    sample: { text: "An accident", sub: "A decision" },
    build: (p, k, c) => {
      const line = T(p.text);
      const size = fitSize([line], k.fonts.title, 0.5, c.aspect, 0.1, 0.045, true) * c.scale;
      const y = (c.y ?? 0.5) + size * 0.4;
      const lw = Math.min(0.85, widthOf(line, k.fonts.title, size, c.aspect, true));
      const hit = c.wt(c.words.length - 1, 0.2, 0.1) + c.s(0.35);
      const fix = T(p.sub || "");
      return finish([
        text({ lines: [line], font: k.fonts.title, size, weight: k.titleWeight, color: k.colors.text, upper: true, x: 0.5, y, anchor: "c", align: "center",
          animator: wordAnim(c, { opacity: 0, y: 0.3, blur: 4 }, 0.15, 0.1, 0.5, "expoOut"),
          extra: { keys: { opacity: [[0, 1], [hit + c.s(0.3), 1], [hit + c.s(0.8), 0.5, "out"]] } } }),
        { kind: "scribble", scribble: "strike", x: 0.5, y, w: lw * 1.04, h: size * 0.7, color: k.colors.primary, stroke: 0.012, seed: 5 + Math.round(c.r(10) * 30),
          keys: { draw: [[0, 0], [hit, 0], [hit + c.s(0.45), 1, "out"]] } },
        ...(fix ? [text({ lines: [fix], font: "hand", size: size * 1.05, weight: 700, color: k.colors.primary, x: 0.5 + lw * 0.08, y: y - size * 1.25, anchor: "c", align: "center",
          animator: { unit: "char", stagger: c.s(0.035), dur: c.s(0.2), ease: "out", from: { opacity: 0, y: 0.2 } },
          extra: { from: hit + c.s(0.4), keys: { rot: [[0, -4]] } } })] : []),
      ], c, "blur", { shade: { kind: "vignette", amount: 0.45 } });
    },
  },
  // ============================== TRANSITIONS (over a cut) ==============================
  {
    id: "ml-tr-ink", name: "Ink bleed", family: "transition",
    about: "Ink in the kit's deep colour blooms in from near one edge, its feathered edge led by a thin accent rim, until the shot is covered; the next shot bleeds through from the other side.",
    use: "A soft, artful change of place or time (a memory, a new chapter of a life story); calm or emotional sections.",
    sample: { text: "" },
    build: (p, k, c) => trans([{ kind: "fx", effect: "ink", x: 0.5, y: 0.5, w: 1, h: 1, color: k.colors.bg2, color2: k.colors.primary, mid: p.dur / 2, seed: 1 + Math.round(c.r(11) * 90) }]),
  },
  {
    id: "ml-tr-burn", name: "Film burn", family: "transition",
    about: "A warm light leak: a skewed band of film light sweeps across with a corner glow and gate streaks, flashing warm white for a moment over the cut, then cools away onto the next shot.",
    use: "A jump in time or a flashback (\"years earlier\", \"back in 1985\"), archive and nostalgic footage, emotional peaks.",
    sample: { text: "" },
    build: (p, k, c) => trans([{ kind: "fx", effect: "burn", x: 0.5, y: 0.5, w: 1, h: 1, color: k.colors.primary, mid: p.dur / 2, seed: 1 + Math.round(c.r(12) * 90) }]),
  },
  {
    id: "ml-tr-glitch", name: "Glitch slices", family: "transition",
    about: "The frame tears into jittering inverted slices and kit-coloured bands with scanlines, peaking on the cut.",
    use: "Tech, hacking, internet, breaking news, a sudden twist or a system failing; energetic sections, never in calm ones.",
    sample: { text: "" },
    build: (p, k, c) => trans([{ kind: "fx", effect: "glitch", x: 0.5, y: 0.5, w: 1, h: 1, color: k.colors.primary, color2: k.colors.bg2, fill: k.colors.secondary, mid: p.dur / 2, seed: 1 + Math.round(c.r(13) * 90) }]),
  },
  {
    id: "ml-tr-tear", name: "Paper tear", family: "transition",
    about: "A grained sheet in the kit colour, its torn edges ragged with a white fibrous core, slides across at a slight tilt, covering the cut and tearing away onto the next shot.",
    use: "Moving to a new topic or case in an explainer, scrapbook or history piece; playful or documentary.",
    sample: { text: "" },
    build: (p, k, c) => trans([{ kind: "fx", effect: "tear", x: 0.5, y: 0.5, w: 1, h: 1, color: k.colors.bg, mid: p.dur / 2, seed: 1 + Math.round(c.r(14) * 90) }]),
  },
  {
    id: "ml-tr-blocks", name: "Block dissolve", family: "transition",
    about: "A directional tile wipe in the kit's ground tones: tiles grow in as the wave reaches them, its front lit in the accent, cover the cut, then shrink away in the same direction onto the next shot.",
    use: "A modern, data or tech change of section (a new list item, a new chapter in an explainer).",
    sample: { text: "" },
    build: (p, k, c) => trans([{ kind: "fx", effect: "blocks", x: 0.5, y: 0.5, w: 1, h: 1, color: k.colors.bg, color2: k.colors.bg2, fill: k.colors.primary, mid: p.dur / 2, seed: 1 + Math.round(c.r(15) * 90) }]),
  },
];

// ------------------------------------------------------------------ the recipes
const T = (s: string) => s.trim();
// ------------------------------------------------------------------ the gaming video-essay pack (2026-10-15)
// Measured from the owner's reference "Why GTA 6 Is Making Driving HARD Again!" (docs/style-refs/gta6_driving/
// catalogue.md): every look draws a "game" layer (SpecGaming.tsx); the gaming_essay style's planner
// (src/gaming.py) places them on their trigger words. They work in any kit; the "gaming" kit is the reference's own.
const GM_STOP = new Set(("a an the to of and or but in on at by for with from that this it its is was were be been are as so if than then " +
  "you your we our they their he his she her i my me just still even not no had have has do did does can could would will").split(" "));
/** A line's words as the reference shows them: lead-in small words together, every stressed word alone. */
export const gmChunks = (words: string[]): { t: string; i: number }[] => {
  const out: { t: string; i: number }[] = [];
  let cur: string[] = [];
  let start = 0;
  words.forEach((w, i) => {
    const bare = w.toLowerCase().replace(/[^a-z0-9']/g, "");
    if (GM_STOP.has(bare)) { if (!cur.length) start = i; cur.push(w); return; }
    if (cur.length === 1 && cur[0].length <= 2) { out.push({ t: `${cur[0]} ${w}`, i: start }); cur = []; return; }
    if (cur.length) { out.push({ t: cur.join(" "), i: start }); cur = []; }
    out.push({ t: w, i });
  });
  if (cur.length) out.push({ t: cur.join(" "), i: start });
  return out.slice(0, 14);
};
const gmGold = (k: BrandKit) => (k.id === "gaming" ? "#f5c22b" : k.colors.primary);
const gmTimes = (p: MxParams, c: Ctx, n: number, start: number, gap: number) =>
  Array.from({ length: n }, (_, i) => { const a = p.itemAt?.[i]; return typeof a === "number" && a >= 0 && a < p.dur ? a : c.s(start + i * gap); });
const gmPoint = (p: MxParams, x: number, y: number) => (p.point ? { x: p.point.x, y: p.point.y } : { x, y });
const gmCaps = (w: string) => w === w.toUpperCase() && /[A-Z]{2}/.test(w);
const GAMING: MxRecipe[] = [
  {
    id: "ml-gm-kinetic", name: "Words in the scene", family: "title",
    about: "Big white words stand in the gameplay one chunk at a time, each swapped in on its spoken word (a hard three-frame cut, or a soft left-to-right letter fade); an all-caps word takes the gold accent.",
    use: "The stressed word of a line (\"learn\", \"driving\", \"Progression\", \"hour: 100\") with its lead-in words; the gaming essay's main punctuation, every few lines in the hook, every 8-15 s after.",
    sample: { text: "you had to LEARN" },
    build: (p, k, c) => {
      const ch = gmChunks(c.words);
      const hi = ch.findIndex((x) => gmCaps(x.t));
      const x = c.side === "left" ? 0.32 : c.side === "right" ? 0.68 : 0.5;
      return finish([{ kind: "game", game: "kinetic", x, y: c.y ?? 0.32, w: 1, h: 1, items: ch.map((q) => q.t),
        times: ch.map((q) => c.wt(q.i, 0.04, 0.34)), hi: hi >= 0 ? hi : undefined, size: 0.17 * c.scale, color: k.colors.text,
        emphColor: gmGold(k), label: c.r(4) > 0.72 ? "type" : "cut", seed: Math.round(c.r(5) * 90) }], c, "fade");
    },
  },
  {
    id: "ml-gm-boxed", name: "Boxed words", family: "emphasis",
    about: "Mono words typed one by one inside green-outlined dark boxes, the last word in the accent - a terminal-like punchline.",
    use: "A two-to-four-word punchline that turns the line round (\"you had\", \"it never changed\", \"you got better\").",
    sample: { text: "you had" },
    build: (p, k, c) => {
      const words = c.words.slice(0, 4);
      return finish([{ kind: "game", game: "boxed", x: c.side === "right" ? 0.55 : 0.07, y: c.y ?? 0.42, w: 1, h: 1, items: words,
        times: words.map((_, i) => c.wt(i, 0.05, 0.3)), size: 0.13 * c.scale, fill: k.colors.primary }], c, "fade");
    },
  },
  {
    id: "ml-gm-meter", name: "Difficulty meter", family: "data",
    about: "An Easy -> Hard pill fills with glowing segments sweeping green to red to the level said, its caption words land on their times and a hand-drawn arrow points down at the action.",
    use: "Difficulty talk: hard / easy / skill / challenge / forgiving / punishing (\"made driving hard\", \"a skill again\"); value = how hard (0-100), text = the caption words as said.",
    sample: { text: "driving a SKILL again", value: 90 },
    build: (p, k, c) => {
      const words = c.words.slice(0, 6);
      const hi = words.findIndex(gmCaps);
      const v = typeof p.value === "number" && Number.isFinite(p.value) ? Math.max(5, Math.min(100, p.value <= 1 ? p.value * 100 : p.value)) : 88;
      return finish([{ kind: "game", game: "meter", x: c.side === "right" ? 0.62 : 0.4, y: c.y ?? 0.22, w: 0.34 * c.scale, h: 0.085 * c.scale,
        valueTo: v, bdur: c.s(1.15), items: words, times: words.map((_, i) => c.wt(i, 0.7, 0.18)), hi: hi >= 0 ? hi : undefined,
        label: T(p.kicker || "Easy"), meta: T(p.sub || "Hard"), text: c.r(6) > 0.25 ? "arrow" : "plain" }], c, "fade");
    },
  },
  {
    id: "ml-gm-article", name: "Article clipping", family: "callout",
    about: "A newspaper clipping in tight close-up: soft depth-of-field lines around one sharp line, the quoted phrase swept with a yellow highlighter, a slow push.",
    use: "A press or critic phrase the narration quotes or names (\"arcade style\", \"boat-like\", \"too floaty\"); text = the phrase, kicker / sub = the words before / after it in that sentence.",
    sample: { text: "arcade style", kicker: "interest in", sub: "games," },
    build: (p, k, c) => finish([{ kind: "game", game: "article", x: 0.5, y: 0.5, w: 1, h: 1, text: T(p.text), label: T(p.kicker || ""), meta: T(p.sub || ""),
      items: p.items?.length ? p.items : ["the series that defined a", "decade of open-world design", "and the studio's next move is", "watched closely by fans who"],
      mid: c.s(0.45), size: 0.1 * c.scale, fill: "#f4e22b", seed: 1 + Math.round(c.r(7) * 400) }], c, "fade"),
  },
  {
    id: "ml-gm-versus", name: "Versus split", family: "title",
    about: "A white divider draws down the middle of a split, two big slab titles crown the halves; the side being talked about stays lit, the other dims, and a curved arrow swings over when the talk switches.",
    use: "Two games, versions or eras compared (\"GTA 4 ... GTA 6\", \"Souls vs Elden Ring\"); kicker = the left title, sub = the right title (short: \"IV\", \"VI\"), itemAt = when each is said.",
    sample: { text: "IV vs VI", kicker: "IV", sub: "VI" },
    build: (p, k, c) => finish([{ kind: "game", game: "versus", x: 0.5, y: 0.5, w: 1, h: 1, label: T(p.kicker || c.words[0] || ""),
      meta: T(p.sub || c.words[c.words.length - 1] || ""), times: gmTimes(p, c, 2, 0, 0.9), size: 0.16 * c.scale,
      color2: k.id === "gaming" ? "#ff4fd8" : k.colors.secondary, emphColor: k.id === "gaming" ? "#ff9a3c" : k.colors.primary }], c, "fade"),
  },
  {
    id: "ml-gm-board", name: "Cork-board chapter", family: "transition",
    about: "Out of black onto a map-textured cork board: a big chapter number, the chapter's taped label, polaroids that show the shot through them, red strings to a \"?\" card; the camera pushes in.",
    use: "Each new chapter of a gaming essay (about one a minute); text = the chapter title, value or kicker = its number, items = the other chapters' titles, sub = the question card's tape (\"THE ANSWER\").",
    sample: { text: "Driving you had to learn", kicker: "1", items: ["The solution", "The third attempt"] },
    build: (p, k, c) => trans([{ kind: "game", game: "board", x: 0.5, y: 0.5, w: 1, h: 1, text: T(p.text),
      label: typeof p.value === "number" ? String(Math.round(p.value)) : T(p.kicker || "1"), meta: T(p.sub || "The answer"),
      items: p.items || [], seed: 1 + Math.round(c.r(8) * 300) }]),
  },
  {
    id: "ml-gm-curve", name: "Learning curve", family: "data",
    about: "A curve draws itself over the footage, flat and red along the bottom then sweeping up green, with a glowing head and its label fading in letter by letter.",
    use: "Getting better over time: learning curve, practice, mastery, skill growing, \"your first hour vs your 100th\"; text = the label (\"Learning curve\").",
    sample: { text: "Learning curve" },
    build: (p, k, c) => finish([{ kind: "game", game: "curve", x: 0.14, y: c.y ?? 0.84, w: 0.68 * c.scale, h: 0.5 * c.scale, text: T(p.text),
      bdur: c.s(1.15), fill: k.id === "gaming" ? "#3dff4e" : k.colors.primary, color2: k.id === "gaming" ? "#ff2b2b" : k.colors.secondary, size: 0.045 * c.scale }], c, "fade"),
  },
  {
    id: "ml-gm-zone", name: "Map zone", family: "callout",
    about: "A glowing neon-green outline draws round a district of a map (the shot's own in-game map, or a drawn dark game map), the place's name typing on above it.",
    use: "A place in the game world named (a city, district, region, track: \"Liberty City\", \"Limgrave\", \"the corners\"); kicker \"map\" draws the dark game map when the shot is not one; anchor = the district.",
    sample: { text: "Corners", kicker: "map" },
    build: (p, k, c) => {
      const pt = gmPoint(p, 0.42, 0.56);
      return finish([{ kind: "game", game: "zone", x: pt.x, y: pt.y, w: 0.2 * c.scale, h: 0.3 * c.scale, text: T(p.text), label: /map/i.test(p.kicker || "") ? "map" : "",
        items: p.items || [], fill: k.id === "gaming" ? "#31ff45" : k.colors.region, bdur: c.s(0.9), size: 0.1 * c.scale, seed: 2 + Math.round(c.r(9) * 200) }], c, "fade");
    },
  },
  {
    id: "ml-gm-wireframe", name: "Wireframe tracker", family: "emphasis",
    about: "A green wireframe box draws itself edge by edge round the subject (a car, a character), following it, with a label laid on the ground plane in perspective.",
    use: "Physics, hitboxes, weight, handling, collision - the mechanics of a thing on screen (\"PHYSICS\", \"WEIGHT\", \"HITBOX\"); anchor = the subject (a chase-cam car sits low centre).",
    sample: { text: "PHYSICS" },
    build: (p, k, c) => {
      const pt = gmPoint(p, 0.52, 0.6);
      return finish([{ kind: "game", game: "wire", x: pt.x, y: pt.y, w: 0.28 * c.scale, h: 0.36 * c.scale, text: T(p.text), fill: k.id === "gaming" ? "#3cff3c" : k.colors.primary,
        size: 0.065 * c.scale, seed: Math.round(c.r(10) * 9) }], c, "fade");
    },
  },
  {
    id: "ml-gm-formulas", name: "Floating formulas", family: "emphasis",
    about: "Chalk formulas and triangles fade in and float over the shot round its subject - the \"thinking hard\" look.",
    use: "Calculation, understanding, figuring a system out, theory-crafting (\"you learn\", \"understood what the car would do\", \"the math behind it\").",
    sample: { text: "understood" },
    build: (p, k, c) => finish([{ kind: "game", game: "formula", x: 0.5, y: 0.5, w: 1, h: 1, items: p.items || [], seed: 3 + Math.round(c.r(11) * 500) }], c, "fade"),
  },
  {
    id: "ml-gm-thumbs", name: "Verdict thumbs", family: "emphasis",
    about: "A glowing green thumbs-up or red thumbs-down disc pops on the verdict word and slowly grows; a second verdict replaces it on its own word.",
    use: "A verdict or reaction: loved / hated, good / bad, worked / failed, fans for and against; items = \"up\" / \"down\" in the order said, itemAt = their words.",
    sample: { text: "loved hated", items: ["up", "down"] },
    build: (p, k, c) => {
      const v = (p.items?.length ? p.items : c.words.map((w) => (/hate|bad|worse|fail|wrong|broke|annoy|frustrat|^no$/i.test(w) ? "down" : "up")).slice(0, 1)).slice(0, 3);
      const pt = gmPoint(p, c.side === "left" ? 0.3 : 0.68, 0.5);
      return finish([{ kind: "game", game: "thumbs", x: pt.x, y: pt.y, w: 0.2, h: 0.27 * c.scale, items: v, times: gmTimes(p, c, v.length, 0.05, 1.2),
        size: 0.26 * c.scale, fill: k.id === "gaming" ? "#22d63a" : k.colors.primary }], c, "scale", { shade: { kind: "full", amount: 0.22 } });
    },
  },
  {
    id: "ml-gm-manual", name: "Game manual", family: "callout",
    about: "An old game manual rises in and opens: aged pages, the guide's title, numbered sections written on as they are said, a red pen circle round the one that matters, a sticky note.",
    use: "Rules, a system, a guide or steps the player had to learn (\"the basics\", \"braking\", \"cornering\"); text = the guide's title, items = the sections as said, sub = a sticky note.",
    sample: { text: "Driving guide", kicker: "Liberty City manual", items: ["The basics", "Braking", "Cornering", "Different cars"], sub: "Slow in, fast out" },
    build: (p, k, c) => {
      const items = (p.items || []).slice(0, 4);
      return finish([{ kind: "game", game: "manual", x: 0.5, y: 0.52, w: 1, h: 1, text: T(p.text), label: T(p.kicker || ""), meta: T(p.sub || ""),
        items, times: gmTimes(p, c, items.length, 0.8, 0.55), hi: items.length > 1 ? 1 : 0, mid: Math.max(c.s(2), p.dur - c.s(1.4)) }], c, "drop",
      { shade: { kind: "full", amount: 0.45 } });
    },
  },
  {
    id: "ml-gm-summary", name: "Summary card", family: "callout",
    about: "A dark summary card: the lead line typed on with its key phrase in the accent, then bold-led bullets typed one by one, the card slowly pushing in.",
    use: "Two camps or a debate summed up (\"Team Realistic: ...\", \"Team Arcade: ...\"), what fans say, the state of an argument; text = the lead, kicker = its key phrase, items = \"Name: point\" bullets.",
    sample: { text: "Fans are still fighting over it 20 years later.", kicker: "20 years later", items: ["Team Realistic: praises the weight", "Team Arcade: calls them boats"] },
    build: (p, k, c) => {
      const items = (p.items || []).slice(0, 4);
      return finish([{ kind: "game", game: "summary", x: 0.5, y: 0.5, w: 1, h: 1, text: T(p.text), label: T(p.kicker || ""), items,
        times: gmTimes(p, c, items.length, 1.0, 1.0), emphColor: gmGold(k) }], c, "fade");
    },
  },
  {
    id: "ml-gm-neon", name: "Neon question", family: "title",
    about: "A neon question box flickers on (pink-to-cyan frame, palm silhouette, a title badge) and the question types itself in with its letters closing up.",
    use: "A question the essay asks the viewer (\"Does braking too late punish you?\"); text = the question as said, sub = a bold second line, kicker = a short badge (\"VI\").",
    sample: { text: "Does a heavy SUV force you", sub: "to drive differently?", kicker: "VI" },
    build: (p, k, c) => finish([{ kind: "game", game: "neon", x: 0.36, y: c.y ?? 0.68, w: 0.6 * c.scale, h: 0.16 * c.scale, text: T(p.text), meta: T(p.sub || ""),
      label: T(p.kicker || ""), size: 0.034 * c.scale, mid: c.s(0.3) + T(p.text).length * 0.03 }], c, "blur"),
  },
  {
    id: "ml-gm-static", name: "TV static cut", family: "transition",
    about: "The picture breaks into TV static and jittering colour bars for a beat, then the next shot comes through.",
    use: "A cut to an old game, a flashback, a hard topic switch or a joke beat (\"back in 2008\", \"and then everything changed\").",
    sample: { text: "" },
    build: () => trans([{ kind: "game", game: "static", x: 0.5, y: 0.5, w: 1, h: 1 }]),
  },
  {
    id: "ml-gm-endline", name: "End line", family: "title",
    about: "On black: a small white lead line, then the closing words in bold gold capitals.",
    use: "The essay's last line (\"they'll make getting good at it - MATTER AGAIN\"); sub = the small lead, text = the gold words.",
    sample: { text: "Matter again", sub: "They'll make getting good at it" },
    build: (p, k, c) => finish([{ kind: "game", game: "endline", x: 0.5, y: 0.5, w: 1, h: 1, text: T(p.text), meta: T(p.sub || ""),
      mid: c.s(0.75), emphColor: gmGold(k), size: 0.044 * c.scale }], c, "fade"),
  },
];


export const RECIPES: MxRecipe[] = [
  // ============================== TITLES ==============================
  {
    id: "ml-title-rise", name: "Masked rise", family: "title",
    about: "Each word rises out of its own line on the beat it is spoken, an accent rule draws under the last one.",
    sample: { text: "The river ran dry", sub: "For the first time in 1,200 years" },
    build: (p, k, c) => {
      const pl = placeX(c.side);
      const lines = balance(p.text, 18, 2);
      const size = fitSize(lines, k.fonts.title, 0.6, c.aspect, 0.105, 0.05, true) * c.scale;
      const y = c.y ?? 0.5;
      const last = c.wt(c.words.length - 1, 0.1, 0.08);
      return finish([
        text({ lines, font: k.fonts.title, size, weight: k.titleWeight, color: k.colors.text, upper: true, tracking: k.titleTracking,
          x: pl.x, y, anchor: pl.anchor, align: pl.align,
          animator: wordAnim(c, { y: 1.15, blur: 4 }, 0.1, 0.08, 0.7, "expoOut", true),
          extra: { deco: { underline: k.colors.primary, at: last + c.s(0.25) },
            sub: p.sub ? { text: T(p.sub), size: size * 0.38, font: k.fonts.body, weight: 500, color: k.colors.muted, tracking: 0.01, upper: false, at: last + c.s(0.35) } : undefined } }),
      ], c, "blur", { shade: { kind: c.side === "center" ? "vignette" : c.side, amount: 0.38 } });
    },
  },
  {
    id: "ml-title-track", name: "Cinematic track-in", family: "title",
    about: "Letters drift together from wide tracking and soft focus - a slow, filmic title for an opening or a reveal.",
    sample: { text: "Ten years later", kicker: "Chapter two" },
    build: (p, k, c) => {
      const lines = balance(p.text, 22, 2);
      const size = fitSize(lines, k.fonts.title, 0.62, c.aspect, 0.095, 0.045, true, 0.12) * c.scale;
      const y = c.y ?? 0.48;
      return finish([
        text({ lines, font: k.fonts.title, size, weight: Math.min(800, k.titleWeight), color: k.colors.text, upper: true, x: 0.5, y,
          anchor: "c", align: "center", tracking: 0.04,
          animator: { unit: "char", stagger: c.s(0.022), dur: c.s(1.1), ease: "expoOut", from: { opacity: 0, blur: 14, x: 0.35 } },
          extra: { keys: { tracking: [[0, 0.32], [c.s(1.9), 0.06, "expoOut"], [p.dur, 0.09, "linear"]] },
            kicker: p.kicker ? { text: T(p.kicker).toUpperCase(), size: size * 0.24, color: k.colors.pillText, bg: k.colors.pillBg, at: c.s(0.9) } : undefined } }),
      ], c, "blur", { shade: { kind: "vignette", amount: 0.45 } });
    },
  },
  {
    id: "ml-title-split", name: "Split lines", family: "title",
    about: "Two lines slide in from opposite sides and meet on a divider that draws out from the centre.",
    sample: { text: "Same water, two countries" },
    build: (p, k, c) => {
      const words = c.words;
      const cut = Math.max(1, Math.ceil(words.length / 2));
      const a = words.slice(0, cut).join(" "), b = words.slice(cut).join(" ") || a;
      const size = fitSize([a, b], k.fonts.title, 0.56, c.aspect, 0.1, 0.05, true) * c.scale;
      const y = c.y ?? 0.5;
      const gap = size * 0.72;
      const t1 = c.wt(0, 0.1, 0.1), t2 = c.wt(cut, 0.45, 0.1);
      const slide = (dir: number, at: number) => ({ x: [[0, dir * 0.08], [at, dir * 0.08], [at + c.s(0.75), 0, "expoOut"]],
        opacity: [[0, 0], [at, 0], [at + c.s(0.35), 1, "out"]], blur: [[0, 10], [at, 10], [at + c.s(0.6), 0, "out"]] });
      return finish([
        { kind: "rect", x: 0.5, y, w: 0.5, h: 0.0035, fill: k.colors.primary, color: k.colors.primary,
          keys: { sx: [[0, 0], [t1 + c.s(0.2), 0], [t1 + c.s(0.95), 1, "expoInOut"]] } },
        text({ lines: [a], font: k.fonts.title, size, weight: k.titleWeight, color: k.colors.text, upper: true, x: 0.5, y: y - gap, anchor: "c", align: "center",
          extra: { keys: slide(-1, t1), mb: 0.8 } }),
        text({ lines: [b], font: k.fonts.title, size, weight: k.titleWeight, color: k.colors.primary, upper: true, x: 0.5, y: y + gap, anchor: "c", align: "center",
          extra: { keys: slide(1, t2), mb: 0.8 } }),
      ], c, "blur", { shade: { kind: "vignette", amount: 0.42 } });
    },
  },
  {
    id: "ml-title-flip", name: "3D flip-up", family: "title",
    about: "Words hinge up from below in 3D, one after another, and settle flat with a soft shadow.",
    sample: { text: "Nobody saw it coming" },
    build: (p, k, c) => {
      const pl = placeX(c.side);
      const lines = balance(p.text, 16, 3);
      const size = fitSize(lines, k.fonts.title, 0.55, c.aspect, 0.1, 0.05, true) * c.scale;
      return finish([
        text({ lines, font: k.fonts.title, size, weight: k.titleWeight, color: k.colors.text, upper: true, x: pl.x, y: c.y ?? 0.5,
          anchor: pl.anchor, align: pl.align, emph: [c.words.length - 1], emphColor: k.colors.primary,
          animator: wordAnim(c, { rotX: -88, y: 0.35, opacity: 0, blur: 3 }, 0.1, 0.09, 0.8, "quintOut") }),
      ], c, "blur", { persp: 900, shade: { kind: c.side === "center" ? "vignette" : c.side, amount: 0.38 } });
    },
  },
  {
    id: "ml-title-focus", name: "Focus pull", family: "title",
    about: "The whole line comes into focus as the camera pulls back a touch - for a quiet, heavy statement.",
    sample: { text: "It was never about the money" },
    build: (p, k, c) => {
      const lines = balance(p.text, 20, 2);
      const size = fitSize(lines, k.fonts.body === "inter" ? k.fonts.title : k.fonts.body, 0.6, c.aspect, 0.085, 0.045) * c.scale;
      return finish([
        text({ lines, font: k.fonts.title, size, weight: Math.min(k.titleWeight, 700), color: k.colors.text, x: 0.5, y: c.y ?? 0.5, anchor: "c", align: "center",
          tracking: -0.005, lineH: 1.1,
          extra: { keys: { blur: [[0, 22], [c.s(1.1), 0, "expoOut"]], opacity: [[0, 0], [c.s(0.5), 1, "out"]],
            scale: [[0, 1.09], [c.s(1.3), 1, "expoOut"], [p.dur, 0.985, "linear"]] } } }),
      ], c, "fade", { shade: { kind: "full", amount: 0.45 } });
    },
  },
  {
    id: "ml-title-sweep", name: "Bar sweep reveal", family: "title",
    about: "An accent bar sweeps across each line and leaves the words behind it - a news-desk reveal, line by line.",
    sample: { text: "Three cities. One deadline." },
    build: (p, k, c) => {
      const pl = placeX(c.side === "center" ? "left" : c.side);
      const lines = balance(p.text, 16, 3);
      const size = fitSize(lines, k.fonts.title, 0.5, c.aspect, 0.09, 0.045, true) * c.scale;
      const y0 = (c.y ?? 0.5) - ((lines.length - 1) * size * 1.25) / 2;
      let wi = 0;
      return finish(lines.map((line, i) => {
        const at = c.wt(wi, 0.1 + i * 0.32, 0.32);
        wi += line.split(/\s+/).length;
        return text({ lines: [line], font: k.fonts.title, size, weight: k.titleWeight, color: i === lines.length - 1 ? k.colors.primary : k.colors.text,
          upper: true, x: pl.x, y: y0 + i * size * 1.25, anchor: pl.anchor, align: pl.align,
          extra: { sweep: { color: i % 2 ? k.colors.text : k.colors.primary, at, dur: c.s(0.62) } } });
      }), c, "wipe", { shade: { kind: pl.anchor === "r" ? "right" : "left", amount: 0.42 } });
    },
  },
  {
    id: "ml-title-karaoke", name: "Spoken words", family: "title",
    about: "The line is set faintly, and each word lights up in the accent exactly as it is said.",
    sample: { text: "Every single drop was already promised", wordAt: [0.1, 0.4, 0.75, 1.0, 1.3, 1.6] },
    build: (p, k, c) => {
      const lines = balance(p.text, 26, 3);
      const size = fitSize(lines, k.fonts.title, 0.66, c.aspect, 0.075, 0.042) * c.scale;
      const y = c.y ?? 0.72;
      const base = text({ lines, font: k.fonts.title, size, weight: k.titleWeight, color: hexA(k.colors.text, 0.32), x: 0.5, y, anchor: "c", align: "center",
        extra: { keys: { opacity: [[0, 0], [c.s(0.3), 1, "out"]], y: [[0, 0.015], [c.s(0.5), 0, "expoOut"]] } } });
      const lit = text({ lines, font: k.fonts.title, size, weight: k.titleWeight, color: k.colors.text, x: 0.5, y, anchor: "c", align: "center",
        emph: c.words.length > 2 ? [c.words.length - 1] : [], emphColor: k.colors.primary,
        animator: wordAnim(c, { opacity: 0, blur: 6, y: 0.08 }, 0.25, 0.22, 0.32, "out"),
        extra: { shadow: "none", keys: { y: [[0, 0.015], [c.s(0.5), 0, "expoOut"]] } } });
      return finish([base, lit], c, "fade", { shade: { kind: "bottom", amount: 0.5 } });
    },
  },
  {
    id: "ml-title-card", name: "Kit title card", family: "title",
    about: "A full-screen card on the kit's ground: a huge condensed title in the accent, built word by word, a quiet sub line.",
    sample: { text: "Burj Khalifa", sub: "The tallest building ever built" },
    build: (p, k, c) => {
      const lines = balance(p.text, 9, 2);
      const size = fitSize(lines, "narrow", 0.62, c.aspect, 0.2, 0.08, true) * c.scale;
      return finish([
        { kind: "backdrop", color: k.colors.bg, color2: k.colors.bg2, keys: { opacity: [[0, 0], [c.s(0.35), 1, "out"]] } },
        text({ lines, font: k.fonts.title === "grotesk" ? "narrow" : k.fonts.title, size, weight: 800, color: k.colors.primary, upper: true, x: 0.5, y: c.y ?? 0.46,
          anchor: "c", align: "center", lineH: 0.92,
          animator: wordAnim(c, { y: 0.5, opacity: 0, blur: 8, scale: 0.94 }, 0.25, 0.12, 0.8, "expoOut"),
          extra: { shadow: "none", keys: { scale: [[0, 1], [p.dur, 1.045, "linear"]] },
            sub: p.sub ? { text: T(p.sub), size: Math.min(0.04, size * 0.24), font: k.fonts.body, weight: 600, color: k.colors.text, tracking: 0.02, upper: false, at: c.s(0.9) } : undefined } }),
      ], c, "fade");
    },
  },
  {
    id: "ml-title-quote", name: "Pull quote", family: "title",
    about: "A large serif quotation mark settles, the words follow in italic, the speaker's name tracks in under them.",
    sample: { text: "We had no idea how bad it was", sub: "Former site engineer" },
    build: (p, k, c) => {
      const pl = placeX(c.side);
      const lines = balance(p.text, 24, 3);
      const size = fitSize(lines, "serif-italic", 0.55, c.aspect, 0.07, 0.04) * c.scale;
      const y = c.y ?? 0.5;
      const qx = pl.anchor === "r" ? pl.x - 0.03 : pl.anchor === "c" ? 0.5 : pl.x + 0.012;
      return finish([
        text({ lines: ["“"], font: "serif", size: size * 3.2, weight: 700, color: k.colors.primary, x: qx, y: y - size * lines.length * 0.9,
          anchor: "c", align: "center", extra: { shadow: "none", keys: { opacity: [[0, 0], [c.s(0.5), 1, "out"]], y: [[0, -0.03], [c.s(0.9), 0, "expoOut"]], scale: [[0, 1.25], [c.s(0.9), 1, "expoOut"]] } } }),
        text({ lines, font: "serif-italic", size, weight: 500, color: k.colors.text, x: pl.x, y, anchor: pl.anchor, align: pl.align, lineH: 1.15,
          animator: wordAnim(c, { opacity: 0, blur: 5, y: 0.25 }, 0.35, 0.07, 0.6, "out"),
          extra: { sub: p.sub ? { text: `— ${T(p.sub)}`.toUpperCase(), size: size * 0.42, font: k.fonts.label, weight: 700, color: k.colors.muted, tracking: 0.12, upper: true,
            at: c.wt(c.words.length - 1, 0.35, 0.07) + c.s(0.4) } : undefined } }),
      ], c, "blur", { shade: { kind: c.side === "center" ? "vignette" : c.side, amount: 0.5 } });
    },
  },
  {
    id: "ml-title-question", name: "Open question", family: "title",
    about: "The question writes itself in word by word; the last word and its question mark land in the accent with a soft glow.",
    sample: { text: "So where did it all go?" },
    build: (p, k, c) => {
      const pl = placeX(c.side);
      const q = /\?\s*$/.test(p.text) ? T(p.text) : `${T(p.text)}?`;
      const lines = balance(q, 18, 3);
      const size = fitSize(lines, k.fonts.title, 0.55, c.aspect, 0.095, 0.05) * c.scale;
      return finish([
        text({ lines, font: k.fonts.title, size, weight: k.titleWeight, color: k.colors.text, x: pl.x, y: c.y ?? 0.5, anchor: pl.anchor, align: pl.align,
          emph: [c.words.length - 1], emphColor: k.colors.primary, emphStyle: "glow",
          animator: wordAnim(c, { opacity: 0, y: 0.4, blur: 6 }, 0.1, 0.1, 0.6, "expoOut") }),
      ], c, "blur", { shade: { kind: c.side === "center" ? "vignette" : c.side, amount: 0.4 } });
    },
  },

  // ============================== LOWER THIRDS ==============================
  {
    id: "ml-lt-bar", name: "Accent bar", family: "lower-third",
    about: "A thin accent bar grows, the name slides out from behind it, the role fades up underneath.",
    sample: { text: "Dr. Maya Okafor", sub: "Hydrologist, University of Arizona" },
    build: (p, k, c) => {
      const left = c.side !== "right";
      const x = left ? 0.085 : 0.915;
      const y = c.y ?? 0.8;
      const size = fitSize([T(p.text)], k.fonts.title, 0.38, c.aspect, 0.055, 0.034) * c.scale;
      return finish([
        { kind: "rect", x: left ? 0.075 : 0.925, y: y + size * 0.25, w: 0.0035, h: size * 2.1, fill: k.colors.primary, color: k.colors.primary,
          keys: { sy: [[0, 0], [c.s(0.45), 1, "expoOut"]] } },
        text({ lines: [T(p.text)], font: k.fonts.title, size, weight: k.titleWeight, color: k.colors.text, x, y, anchor: left ? "l" : "r", align: left ? "left" : "right",
          extra: { wipeFrom: left ? "l" : "r", keys: { wipe: [[0, 0], [c.s(0.2), 0], [c.s(0.85), 1, "expoOut"]], x: [[0, left ? -0.03 : 0.03], [c.s(0.2), left ? -0.03 : 0.03], [c.s(0.85), 0, "expoOut"]] }, mb: 0.6 } }),
        ...(p.sub ? [text({ lines: [T(p.sub)], font: k.fonts.body, size: size * 0.5, weight: 500, color: k.colors.muted, x, y: y + size * 0.95,
          anchor: left ? "l" : "r", align: left ? "left" : "right",
          extra: { keys: { opacity: [[0, 0], [c.s(0.55), 0], [c.s(0.95), 1, "out"]], y: [[0, 0.012], [c.s(0.55), 0.012], [c.s(1.1), 0, "expoOut"]] } } })] : []),
      ], c, "wipe", { shade: { kind: "bottom", amount: 0.32 } });
    },
  },
  {
    id: "ml-lt-glass", name: "Frosted card", family: "lower-third",
    about: "A frosted glass card slides in low on the calm side carrying the name and role; the edge catches the accent.",
    sample: { text: "Elena Ruiz", sub: "Lost her farm in 2022" },
    build: (p, k, c) => {
      const left = c.side !== "right";
      const x = left ? 0.07 : 0.93;
      const y = c.y ?? 0.8;
      const size = fitSize([T(p.text)], k.fonts.title, 0.32, c.aspect, 0.05, 0.032) * c.scale;
      return finish([
        text({ lines: [T(p.text)], font: k.fonts.title, size, weight: k.titleWeight, color: k.colors.text, x, y, anchor: left ? "l" : "r", align: left ? "left" : "right",
          extra: { panel: { color: "#0d0f14", opacity: 0.55, pad: 0.026, radius: 0.012, blur: 18 }, deco: { bar: k.colors.primary, at: c.s(0.3) },
            keys: { x: [[0, left ? -0.06 : 0.06], [c.s(0.75), 0, "expoOut"]], opacity: [[0, 0], [c.s(0.3), 1, "out"]] }, mb: 0.7,
            sub: p.sub ? { text: T(p.sub), size: size * 0.52, font: k.fonts.body, weight: 500, color: k.colors.muted, tracking: 0, upper: false, at: c.s(0.5) } : undefined } }),
      ], c, "drop");
    },
  },
  {
    id: "ml-lt-pill", name: "Tag and name", family: "lower-third",
    about: "A pill tag in the kit colours wipes on, then the name rises beside it - for a place, a date or a category.",
    sample: { text: "Lake Mead, Nevada", kicker: "Location" },
    build: (p, k, c) => {
      const left = c.side !== "right";
      const x = left ? 0.075 : 0.925;
      const y = c.y ?? 0.82;
      const size = fitSize([T(p.text)], k.fonts.title, 0.36, c.aspect, 0.05, 0.032) * c.scale;
      const tag = T(p.kicker || "").toUpperCase();
      return finish([
        ...(tag ? [{ kind: "pill", text: tag, size: size * 0.5, fill: k.colors.pillBg, color: k.colors.pillText, font: k.fonts.label,
          x, y: y - size * 0.95, anchor: left ? "l" : "r", wipeFrom: left ? "l" : "r", keys: { wipe: [[0, 0], [c.s(0.5), 1, "expoOut"]] } }] : []),
        text({ lines: [T(p.text)], font: k.fonts.title, size, weight: k.titleWeight, color: k.colors.text, x, y, anchor: left ? "l" : "r", align: left ? "left" : "right",
          animator: wordAnim(c, { y: 1.1 }, 0.3, 0.07, 0.6, "expoOut", true) }),
      ], c, "blur", { shade: { kind: "bottom", amount: 0.32 } });
    },
  },
  {
    id: "ml-lt-underline", name: "Underline", family: "lower-third",
    about: "Minimal: the name fades up out of soft focus and an accent line draws under it from the left.",
    sample: { text: "Marcus Bell", sub: "Former county sheriff" },
    build: (p, k, c) => {
      const left = c.side !== "right";
      const x = left ? 0.075 : 0.925;
      const size = fitSize([T(p.text)], k.fonts.title, 0.34, c.aspect, 0.052, 0.032) * c.scale;
      return finish([
        text({ lines: [T(p.text)], font: k.fonts.title, size, weight: k.titleWeight, color: k.colors.text, x, y: c.y ?? 0.8, anchor: left ? "l" : "r", align: left ? "left" : "right",
          extra: { keys: { opacity: [[0, 0], [c.s(0.45), 1, "out"]], blur: [[0, 10], [c.s(0.6), 0, "out"]] }, deco: { underline: k.colors.primary, at: c.s(0.25) },
            sub: p.sub ? { text: T(p.sub), size: size * 0.5, font: k.fonts.body, weight: 500, color: k.colors.muted, tracking: 0.01, upper: false, at: c.s(0.6) } : undefined } }),
      ], c, "fade", { shade: { kind: "bottom", amount: 0.3 } });
    },
  },
  {
    id: "ml-lt-two-tone", name: "Two-tone blocks", family: "lower-third",
    about: "Two solid blocks slide in one after the other - the label in the accent, the name in white - and lock together.",
    sample: { text: "Hoover Dam", kicker: "Built 1936" },
    build: (p, k, c) => {
      const left = c.side !== "right";
      const x = left ? 0.075 : 0.925;
      const y = c.y ?? 0.8;
      const size = fitSize([T(p.text)], k.fonts.title, 0.34, c.aspect, 0.05, 0.032, true) * c.scale;
      const tag = T(p.kicker || p.sub || "").toUpperCase();
      const slide = (at: number) => ({ x: [[0, left ? -0.25 : 0.25], [at, left ? -0.25 : 0.25], [at + c.s(0.7), 0, "expoOut"]], opacity: [[0, 0], [at, 0], [at + c.s(0.15), 1, "linear"]] });
      return finish([
        ...(tag ? [text({ lines: [tag], font: k.fonts.label, size: size * 0.55, weight: 800, color: k.colors.pillText, upper: true, tracking: 0.08, x, y: y - size * 0.92,
          anchor: left ? "l" : "r", align: left ? "left" : "right",
          extra: { shadow: "none", panel: { color: k.colors.pillBg, opacity: 1, pad: 0.012, radius: 0.002, blur: 0 }, keys: slide(0), mb: 1 } })] : []),
        text({ lines: [T(p.text)], font: k.fonts.title, size, weight: k.titleWeight, color: "#111318", upper: true, x, y, anchor: left ? "l" : "r", align: left ? "left" : "right",
          extra: { shadow: "none", panel: { color: "#ffffff", opacity: 1, pad: 0.016, radius: 0.002, blur: 0 }, keys: slide(c.s(0.14)), mb: 1 } }),
      ], c, "wipe");
    },
  },
  {
    id: "ml-lt-location", name: "Place marker", family: "lower-third",
    about: "A map-pin ring pulses once, the place name tracks in beside it and the coordinates type on in mono.",
    sample: { text: "Glen Canyon", sub: "36.94° N, 111.48° W" },
    build: (p, k, c) => {
      const left = c.side !== "right";
      const y = c.y ?? 0.82;
      const size = fitSize([T(p.text)], k.fonts.title, 0.32, c.aspect, 0.05, 0.032, true) * c.scale;
      const px = left ? 0.085 : 0.915;
      const tx = left ? 0.11 : 0.89;
      return finish([
        { kind: "pin", x: px, y: y - size * 0.05, color: k.colors.primary, text: "", keys: { opacity: [[0, 0], [c.s(0.2), 1, "out"]], scale: [[0, 0.3], [c.s(0.6), 1, "expoOut"]] } },
        text({ lines: [T(p.text)], font: k.fonts.title, size, weight: k.titleWeight, color: k.colors.text, upper: true, x: tx, y, anchor: left ? "l" : "r", align: left ? "left" : "right",
          animator: { unit: "char", stagger: c.s(0.025), dur: c.s(0.6), ease: "expoOut", from: { opacity: 0, x: 0.6, blur: 6 } } }),
        ...(p.sub ? [text({ lines: [T(p.sub)], font: "mono", size: size * 0.42, weight: 500, color: k.colors.muted, x: tx, y: y + size * 0.85, anchor: left ? "l" : "r", align: left ? "left" : "right",
          animator: { unit: "char", stagger: c.s(0.03), dur: c.s(0.05), ease: "hold", from: { opacity: 0 } }, extra: { from: c.s(0.6) } })] : []),
      ], c, "blur", { shade: { kind: "bottom", amount: 0.32 } });
    },
  },
  {
    id: "ml-lt-source", name: "Source credit", family: "lower-third",
    about: "A small, quiet credit in the corner - a short rule, SOURCE in caps, the name - for footage and figures.",
    sample: { text: "U.S. Bureau of Reclamation", kicker: "Source" },
    build: (p, k, c) => {
      const left = c.side !== "right";
      const x = left ? 0.06 : 0.94;
      const y = c.y ?? 0.9;
      const size = Math.min(0.03, fitSize([T(p.text)], k.fonts.body, 0.3, c.aspect, 0.03, 0.02)) * c.scale;
      return finish([
        text({ lines: [T(p.text)], font: k.fonts.body, size, weight: 600, color: k.colors.text, x, y, anchor: left ? "l" : "r", align: left ? "left" : "right",
          extra: { keys: { opacity: [[0, 0], [c.s(0.5), 0.92, "out"]], x: [[0, left ? -0.01 : 0.01], [c.s(0.7), 0, "expoOut"]] },
            kicker: { text: T(p.kicker || "Source").toUpperCase(), size: size * 0.7, color: k.colors.pillText, bg: k.colors.pillBg, at: 0 } } }),
      ], c, "fade");
    },
  },

  // ============================== NUMBERS ==============================
  {
    id: "ml-num-hero", name: "Hero figure", family: "number",
    about: "A big figure counts up on the beat it is said, its unit tracks in in small caps under it, a rule draws on.",
    sample: { text: "kilometres", value: 130, suffix: "", sub: "wide at its narrowest" },
    build: (p, k, c) => {
      const pl = placeX(c.side);
      const v = figure(p) ?? 0;
      const label = T(p.text || p.suffix || "").toUpperCase();
      const shown = `${p.prefix || ""}${fmt(v, p.decimals || 0)}${p.suffix && p.text ? p.suffix : ""}`;
      const size = fitSize([shown], k.fonts.number, 0.36, c.aspect, 0.2, 0.09) * c.scale;
      const y = Math.min(c.y ?? 0.46, 0.62);
      const hit = c.wt(0, 0.12, 0);
      return finish([
        { kind: "counter", valueFrom: v > 100 ? Math.round(v * 0.62) : 0, valueTo: v, decimals: p.decimals || 0, prefix: p.prefix || "", suffix: p.text ? p.suffix || "" : "",
          group: !(v >= 1000 && v <= 2100 && Number.isInteger(v)), font: k.fonts.number, size, weight: 800, color: k.colors.number,
          x: pl.x, y, anchor: pl.anchor, align: pl.align, shadow: "soft",
          keys: { p: [[0, 0], [hit, 0], [hit + c.s(1.2), 1, "expoOut"]], opacity: [[0, 0], [hit, 0], [hit + c.s(0.25), 1, "out"]],
            y: [[0, 0.03], [hit, 0.03], [hit + c.s(0.8), 0, "expoOut"]], blur: [[0, 8], [hit, 8], [hit + c.s(0.5), 0, "out"]] } },
        ...(label ? [text({ lines: [label], font: k.fonts.label, size: Math.max(0.036, size * 0.24), weight: 800, color: k.colors.text, upper: true, x: pl.x, y: y + size * 0.76, anchor: pl.anchor, align: pl.align,
          extra: { keys: { tracking: [[0, 0.5], [hit + c.s(0.3), 0.5], [hit + c.s(1.2), 0.14, "expoOut"]], opacity: [[0, 0], [hit + c.s(0.3), 0], [hit + c.s(0.7), 1, "out"]] },
            sub: p.sub ? { text: T(p.sub), size: Math.max(0.028, size * 0.17), font: k.fonts.body, weight: 500, color: k.colors.muted, tracking: 0, upper: false, at: hit + c.s(0.9) } : undefined,
            deco: { rule: k.colors.primary, at: hit + c.s(0.2) } } })] : []),
      ], c, "blur", { shade: { kind: c.side === "center" ? "vignette" : c.side, amount: 0.42 } });
    },
  },
  {
    id: "ml-num-card", name: "Kit figure card", family: "number",
    about: "A full-screen card on the kit's ground: the figure huge in the number colour, what it is of in the accent.",
    sample: { text: "Cost of the project", value: 1.5, prefix: "$", suffix: "B", decimals: 1 },
    build: (p, k, c) => {
      const v = figure(p) ?? 0;
      const shown = `${p.prefix || ""}${fmt(v, p.decimals || 0)}${p.suffix || ""}`;
      const size = fitSize([shown], k.fonts.number, 0.5, c.aspect, 0.26, 0.1) * c.scale;
      const hit = c.wt(0, 0.3, 0);
      return finish([
        { kind: "backdrop", color: k.colors.bg, color2: k.colors.bg2, grid: true, keys: { opacity: [[0, 0], [c.s(0.35), 1, "out"]] } },
        { kind: "counter", valueFrom: 0, valueTo: v, decimals: p.decimals || 0, prefix: p.prefix || "", suffix: p.suffix || "", font: k.fonts.number, size, weight: 800,
          color: k.colors.number, x: 0.5, y: c.y ?? 0.44, anchor: "c", align: "center", shadow: "none",
          group: !(v >= 1000 && v <= 2100 && Number.isInteger(v)),
          keys: { p: [[0, 0], [hit, 0], [hit + c.s(1.4), 1, "expoOut"]], scale: [[0, 0.9], [hit, 0.9], [hit + c.s(1.2), 1, "expoOut"], [p.dur, 1.03, "linear"]],
            opacity: [[0, 0], [hit, 0], [hit + c.s(0.3), 1, "out"]] } },
        ...(p.text ? [text({ lines: balance(T(p.text).toUpperCase(), 28, 2), font: k.fonts.label, size: Math.min(0.05, size * 0.2), weight: 800, color: k.colors.primary, upper: true,
          tracking: 0.08, x: 0.5, y: (c.y ?? 0.44) + size * 0.68, anchor: "c", align: "center",
          animator: { unit: "line", stagger: c.s(0.1), dur: c.s(0.6), ease: "expoOut", from: { opacity: 0, y: 0.6 } }, extra: { from: hit + c.s(0.4), shadow: "none" } })] : []),
      ], c, "fade");
    },
  },
  {
    id: "ml-num-ring", name: "Percent ring", family: "number",
    about: "A ring draws round to the percentage as the figure counts to it inside - for any share, rate or chance.",
    sample: { text: "of the river is used up", value: 37, suffix: "%" },
    build: (p, k, c) => {
      const pl = placeX(c.side === "center" ? "center" : c.side);
      const v = Math.max(0, Math.min(100, figure(p) ?? 0));
      const R = 0.42 * c.scale;
      const cx = pl.anchor === "l" ? 0.07 + (R / c.aspect) / 2 + 0.02 : pl.anchor === "r" ? 0.93 - (R / c.aspect) / 2 - 0.02 : 0.5;
      const cy = c.y ?? 0.47;
      const hit = c.wt(0, 0.2, 0);
      return finish([
        // The ring's stroke starts at 12 o'clock (the ellipse draws from -128 deg: turned 38 deg on).
        { kind: "ellipse", x: cx, y: cy, w: R / c.aspect, h: R, color: hexA(k.colors.text, 0.16), stroke: 0.014, keys: { draw: [[0, 0], [c.s(0.6), 1, "expoOut"]], rot: [[0, 38]] } },
        { kind: "ellipse", x: cx, y: cy, w: R / c.aspect, h: R, color: k.colors.primary, stroke: 0.014, keys: { draw: [[0, 0], [hit, 0], [hit + c.s(1.3), (v / 100) * 1.0, "expoOut"]], rot: [[0, 38]] } },
        { kind: "counter", valueFrom: 0, valueTo: v, decimals: p.decimals || 0, suffix: "%", font: k.fonts.number, size: R * 0.3, weight: 800, color: k.colors.number,
          x: cx, y: cy, anchor: "c", align: "center", keys: { p: [[0, 0], [hit, 0], [hit + c.s(1.3), 1, "expoOut"]], opacity: [[0, 0], [hit, 0], [hit + c.s(0.3), 1, "out"]] } },
        ...(p.text ? [text({ lines: balance(T(p.text), 20, 2), font: k.fonts.label, size: 0.042 * c.scale, weight: 700, color: k.colors.text, upper: true, tracking: 0.08,
          x: cx, y: cy + R / 2 + 0.075, anchor: "c", align: "center", extra: { keys: { opacity: [[0, 0], [hit + c.s(0.5), 0], [hit + c.s(0.9), 1, "out"]] } } })] : []),
      ], c, "scale", { shade: { kind: c.side === "center" ? "vignette" : c.side, amount: 0.45 } });
    },
  },
  {
    id: "ml-num-waffle", name: "Unit grid", family: "number",
    about: "A 10 x 10 grid settles in, then the share fills cell by cell from the bottom in the accent - a percentage you can see.",
    sample: { text: "of the climbs reach the summit", value: 37, suffix: "%" },
    build: (p, k, c) => {
      const v = Math.max(0, Math.min(100, Math.round(figure(p) ?? 0)));
      const right = c.side === "left" ? false : true;
      const gx = right ? 0.7 : 0.3, tx = right ? 0.3 : 0.7;
      return finish([
        { kind: "waffle", x: gx, y: 0.52, w: 0.3 * c.scale, h: 0.52 * c.scale, cols: 10, rows: 10, value: v, fill: k.colors.primary, offColor: hexA(k.colors.text, 0.14), fillFor: c.s(1.3) },
        { kind: "counter", valueFrom: 0, valueTo: v, suffix: "%", font: k.fonts.number, size: 0.19 * c.scale, weight: 800, color: k.colors.number, x: tx, y: 0.45, anchor: "c", align: "center",
          keys: { p: [[0, 0], [c.s(0.45), 0], [c.s(1.75), 1, "expoOut"]], opacity: [[0, 0], [c.s(0.3), 1, "out"]] } },
        ...(p.text ? [text({ lines: balance(T(p.text), 22, 2), font: k.fonts.label, size: 0.042 * c.scale, weight: 800, color: k.colors.text, upper: true, tracking: 0.08,
          x: tx, y: 0.6, anchor: "c", align: "center", extra: { keys: { opacity: [[0, 0], [c.s(0.8), 0], [c.s(1.2), 1, "out"]] } } })] : []),
      ], c, "fade", { shade: { kind: "full", amount: 0.55 } });
    },
  },
  {
    id: "ml-num-year", name: "Year roll", family: "number",
    about: "The year rolls up through the decades and lands on its word; a hairline and the event settle under it.",
    sample: { text: "The dam is finished", value: 1966 },
    build: (p, k, c) => {
      const pl = placeX(c.side);
      const v = Math.round(figure(p) ?? 2000);
      const size = 0.21 * c.scale;
      // A low position still keeps the event line inside the frame.
      const y = Math.min(c.y ?? 0.45, 0.64);
      const hit = c.wt(0, 0.15, 0);
      return finish([
        { kind: "counter", valueFrom: v - 40, valueTo: v, group: false, font: "mono", size, weight: 700, color: k.colors.number, x: pl.x, y, anchor: pl.anchor, align: pl.align,
          keys: { p: [[0, 0], [hit + c.s(1.0), 1, "expoOut"]], opacity: [[0, 0], [c.s(0.25), 1, "out"]], blur: [[0, 8], [hit + c.s(0.7), 0, "out"]], y: [[0, 0.04], [hit + c.s(0.9), 0, "expoOut"]] }, mb: 0.6 },
        ...(p.text ? [text({ lines: balance(T(p.text), 26, 2), font: k.fonts.body, size: 0.046 * c.scale, weight: 600, color: k.colors.text, x: pl.x, y: y + size * 0.75, anchor: pl.anchor, align: pl.align,
          extra: { deco: { rule: k.colors.primary, at: hit + c.s(0.6) }, keys: { opacity: [[0, 0], [hit + c.s(0.7), 0], [hit + c.s(1.1), 1, "out"]] } } })] : []),
      ], c, "blur", { shade: { kind: c.side === "center" ? "vignette" : c.side, amount: 0.42 } });
    },
  },
  {
    id: "ml-num-compare", name: "Then and now", family: "number",
    about: "Two figures side by side: the first lands, the second counts past it in the accent, a divider between them.",
    sample: { text: "1990", sub: "Today", value: 31, prefix: "", suffix: "M", items: ["12"] },
    build: (p, k, c) => {
      const a = Number((p.items || [])[0]);
      const before = Number.isFinite(a) ? a : (figure(p) ?? 0) * 0.5;
      const after = figure(p) ?? 0;
      const size = 0.18 * c.scale;
      const hitA = c.s(0.2), hitB = c.wt(1, c.s(1.1), 0);
      const num = (x: number, val: number, at: number, col: string) => ({ kind: "counter", valueFrom: 0, valueTo: val, prefix: p.prefix || "", suffix: p.suffix || "",
        decimals: p.decimals || 0, font: k.fonts.number, size, weight: 800, color: col, x, y: 0.47, anchor: "c", align: "center",
        keys: { p: [[0, 0], [at, 0], [at + c.s(1.1), 1, "expoOut"]], opacity: [[0, 0], [at, 0], [at + c.s(0.3), 1, "out"]], y: [[0, 0.03], [at, 0.03], [at + c.s(0.8), 0, "expoOut"]] } });
      const lab = (x: number, s: string, at: number) => text({ lines: [s.toUpperCase()], font: k.fonts.label, size: 0.042 * c.scale, weight: 800, color: k.colors.muted, upper: true, tracking: 0.12,
        x, y: 0.47 + size * 0.7, anchor: "c", align: "center", extra: { keys: { opacity: [[0, 0], [at + c.s(0.3), 0], [at + c.s(0.7), 1, "out"]] } } });
      return finish([
        { kind: "rect", x: 0.5, y: 0.5, w: 0.0025, h: 0.26, fill: hexA(k.colors.text, 0.5), color: k.colors.text, keys: { sy: [[0, 0], [c.s(0.7), 1, "expoInOut"]] } },
        num(0.3, before, hitA, k.colors.text), lab(0.3, T(p.text || "Before"), hitA),
        num(0.7, after, hitB, k.colors.primary), lab(0.7, T(p.sub || "Now"), hitB),
      ], c, "fade", { shade: { kind: "full", amount: 0.5 } });
    },
  },

  // ============================== EMPHASIS ==============================
  {
    id: "ml-em-circle", name: "Drawn circle", family: "emphasis",
    about: "A hand-drawn ring circles the thing on screen as it is named, with a label pill riding beside it.",
    sample: { text: "Intake tower", point: { x: 0.56, y: 0.48 } },
    build: (p, k, c) => {
      const pt = p.point || { x: 0.5, y: 0.5 };
      const r = 0.26 * c.scale;
      const hit = c.wt(0, 0.1, 0);
      const right = pt.x < 0.62;
      return finish([
        { kind: "ellipse", x: pt.x, y: pt.y, w: r / c.aspect * 1.25, h: r, color: k.colors.primary, stroke: 0.008, keys: { draw: [[0, 0], [hit, 0], [hit + c.s(0.75), 1, "inOut"]] } },
        ...(p.text ? [{ kind: "pill", text: T(p.text).toUpperCase(), size: 0.036 * c.scale, fill: k.colors.pillBg, color: k.colors.pillText, font: k.fonts.label,
          x: right ? pt.x + (r / c.aspect) * 0.66 : pt.x - (r / c.aspect) * 0.66, y: pt.y - r * 0.45, anchor: right ? "l" : "r", wipeFrom: right ? "l" : "r",
          keys: { wipe: [[0, 0], [hit + c.s(0.55), 0], [hit + c.s(1.0), 1, "expoOut"]] } }] : []),
      ], c, "fade");
    },
  },
  {
    id: "ml-em-arrow", name: "Curved arrow", family: "emphasis",
    about: "A curved arrow draws from a short label to the point on screen, its head snapping in at the end.",
    sample: { text: "The old waterline", point: { x: 0.6, y: 0.4 } },
    build: (p, k, c) => {
      const pt = p.point || { x: 0.55, y: 0.45 };
      const fromLeft = pt.x > 0.5;
      const tx = fromLeft ? Math.max(0.12, pt.x - 0.28) : Math.min(0.88, pt.x + 0.28);
      const ty = Math.min(0.85, pt.y + 0.22);
      const hit = c.wt(0, 0.1, 0);
      return finish([
        text({ lines: balance(T(p.text), 18, 2), font: k.fonts.title, size: 0.058 * c.scale, weight: 800, color: k.colors.text, x: tx, y: ty + 0.03, anchor: "c", align: "center",
          extra: { keys: { opacity: [[0, 0], [hit, 0], [hit + c.s(0.4), 1, "out"]], y: [[0, 0.015], [hit, 0.015], [hit + c.s(0.6), 0, "expoOut"]] } } }),
        { kind: "arrow", points: [[tx + (fromLeft ? 0.04 : -0.04), ty - 0.035], [pt.x + (fromLeft ? -0.015 : 0.015), pt.y + 0.025]], curve: fromLeft ? -0.25 : 0.25,
          color: k.colors.primary, stroke: 0.007, head: 0.032, keys: { draw: [[0, 0], [hit + c.s(0.3), 0], [hit + c.s(1.0), 1, "inOut"]] } },
      ], c, "fade");
    },
  },
  {
    id: "ml-em-highlight", name: "Marker highlight", family: "emphasis",
    about: "A line on the footage; the key word gets a marker block swept behind it in the accent as it is said.",
    sample: { text: "The water simply ran out", wordAt: [0.1, 0.3, 0.55, 0.8, 1.0] },
    build: (p, k, c) => {
      const pl = placeX(c.side);
      const lines = balance(p.text, 22, 2);
      const size = fitSize(lines, k.fonts.title, 0.55, c.aspect, 0.075, 0.045) * c.scale;
      const key = Math.max(0, c.words.length - 2);
      return finish([
        text({ lines, font: k.fonts.title, size, weight: k.titleWeight, color: k.colors.text, x: pl.x, y: c.y ?? 0.5, anchor: pl.anchor, align: pl.align,
          emph: [key], emphColor: k.colors.primary, emphStyle: "box",
          animator: wordAnim(c, { opacity: 0, y: 0.3, blur: 5 }, 0.1, 0.09, 0.55, "expoOut") }),
      ], c, "blur", { shade: { kind: c.side === "center" ? "vignette" : c.side, amount: 0.4 } });
    },
  },
  {
    id: "ml-em-brackets", name: "Focus brackets", family: "emphasis",
    about: "Four corner brackets close in on a spot like a camera locking focus, then a small label types under it.",
    sample: { text: "Target", point: { x: 0.5, y: 0.45 } },
    build: (p, k, c) => {
      const pt = p.point || { x: 0.5, y: 0.45 };
      const w = 0.22 * c.scale, h = 0.3 * c.scale;
      const hit = c.wt(0, 0.1, 0);
      return finish([
        { kind: "bracket", x: pt.x, y: pt.y, w, h, color: k.colors.primary, stroke: 0.004,
          keys: { draw: [[0, 0], [hit, 0], [hit + c.s(0.3), 1, "out"]], scale: [[0, 1.7], [hit, 1.7], [hit + c.s(0.7), 1, "expoOut"]], opacity: [[0, 0], [hit, 0], [hit + c.s(0.2), 1, "linear"]] }, mb: 0.6 },
        ...(p.text ? [text({ lines: [T(p.text).toUpperCase()], font: "mono", size: 0.036 * c.scale, weight: 600, color: k.colors.primary, upper: true, tracking: 0.1,
          x: pt.x, y: pt.y + h / 2 + 0.04, anchor: "c", align: "center",
          animator: { unit: "char", stagger: c.s(0.035), dur: c.s(0.05), ease: "hold", from: { opacity: 0 } }, extra: { from: hit + c.s(0.6), shadow: "hard" } })] : []),
      ], c, "fade");
    },
  },
  {
    id: "ml-em-spotlight", name: "Spotlight", family: "emphasis",
    about: "Everything but one spot dims slowly, so the eye goes where the narrator points; a soft label settles by it.",
    sample: { text: "Here", point: { x: 0.42, y: 0.5 } },
    build: (p, k, c) => {
      const pt = p.point || { x: 0.5, y: 0.5 };
      const hit = c.wt(0, 0.1, 0);
      return finish([
        { kind: "spot", x: pt.x, y: pt.y, w: 0.34 * c.scale, h: 0.5 * c.scale, fill: "#000000", keys: { opacity: [[0, 0], [hit + c.s(0.9), 1, "inOut"]] } },
        ...(p.text ? [text({ lines: [T(p.text)], font: k.fonts.title, size: 0.056 * c.scale, weight: 800, color: k.colors.text, x: pt.x, y: Math.min(0.88, pt.y + 0.31 * c.scale), anchor: "c", align: "center",
          extra: { deco: { underline: k.colors.primary, at: hit + c.s(0.7) }, keys: { opacity: [[0, 0], [hit + c.s(0.5), 0], [hit + c.s(0.9), 1, "out"]] } } })] : []),
      ], c, "fade");
    },
  },
  {
    id: "ml-em-statement", name: "Statement with rule", family: "emphasis",
    about: "A short statement on the footage: an accent rule draws first, then the words slide off it, the key word in the accent.",
    sample: { text: "It was a warning", wordAt: [0.2, 0.4, 0.55, 0.75] },
    build: (p, k, c) => {
      const pl = placeX(c.side === "center" ? (((p.seed || 0) % 2) ? "right" : "left") : c.side);
      const lines = balance(p.text, 16, 2);
      const size = fitSize(lines, k.fonts.title, 0.42, c.aspect, 0.085, 0.045, true) * c.scale;
      return finish([
        text({ lines, font: k.fonts.title, size, weight: k.titleWeight, color: k.colors.text, upper: true, x: pl.x, y: c.y ?? 0.5, anchor: pl.anchor, align: pl.align,
          emph: [c.words.length - 1], emphColor: k.colors.primary,
          animator: wordAnim(c, { x: pl.anchor === "r" ? 0.6 : -0.6, opacity: 0, blur: 6 }, 0.3, 0.08, 0.6, "expoOut", true),
          extra: { deco: { rule: k.colors.primary, at: 0 } } }),
      ], c, "wipe", { shade: { kind: pl.anchor === "r" ? "right" : "left", amount: 0.42 } });
    },
  },
  {
    id: "ml-em-tiles", name: "Name tiles", family: "emphasis",
    about: "Two to five names arrive as tiles one after another under a short header - organisations, places, products.",
    sample: { text: "Who controls it", items: ["Arizona", "Nevada", "California", "Mexico"] },
    build: (p, k, c) => {
      const items = (p.items || []).slice(0, 5);
      return finish([
        text({ lines: [T(p.text).toUpperCase()], font: k.fonts.title, size: 0.08 * c.scale, weight: k.titleWeight, color: k.colors.text, upper: true, x: 0.5, y: 0.36, anchor: "c", align: "center",
          animator: wordAnim(c, { y: 1.1 }, 0.1, 0.07, 0.6, "expoOut", true) }),
        { kind: "tiles", x: 0.5, y: 0.58, items, size: 0.15 * c.scale, fill: "#ffffff", color: "#141414", stagger: c.s(0.16), from: c.s(0.45) },
      ], c, "fade", { shade: { kind: "full", amount: 0.5 } });
    },
  },

  // ============================== TRANSITIONS (over a cut) ==============================
  {
    id: "ml-tr-panel", name: "Panel sweep", family: "transition",
    about: "A full-height accent panel sweeps across the cut with motion blur, a darker panel close behind it.",
    sample: { text: "" },
    build: (p, k, c) => {
      const d = p.dur;
      const m = d / 2;
      const dir = ((p.seed || 0) % 2) ? -1 : 1;
      const sweep = (lag: number) => ({ x: [[0, -1.2 * dir], [m - c.s(0.32) + lag, -1.2 * dir], [m + lag, 0, "expoInOut"], [m + c.s(0.32) + lag, 1.2 * dir, "expoIn"]] });
      return { v: 1, persp: 1400, exit: { kind: "fade", dur: 0 }, drift: { x: 0, y: 0, rotY: 0 }, layers: [
        { kind: "rect", x: 0.5, y: 0.5, w: 1.05, h: 1.02, fill: k.colors.bg2, color: k.colors.bg2, keys: sweep(c.s(0.06)), mb: 1 },
        { kind: "rect", x: 0.5, y: 0.5, w: 1.05, h: 1.02, fill: k.colors.primary, color: k.colors.primary, keys: sweep(0), mb: 1 },
      ] };
    },
  },
  {
    id: "ml-tr-bars", name: "Staggered bars", family: "transition",
    about: "Five vertical bars in the kit colours drop in one after another to cover the cut, then lift away.",
    sample: { text: "" },
    build: (p, k, c) => {
      const m = p.dur / 2;
      const cols = [k.colors.primary, k.colors.bg, k.colors.secondary, k.colors.bg2, k.colors.primary];
      return { v: 1, persp: 1400, exit: { kind: "fade", dur: 0 }, drift: { x: 0, y: 0, rotY: 0 }, layers: cols.map((col, i) => {
        const lag = c.s(0.045) * i;
        return { kind: "rect", x: 0.1 + i * 0.2, y: 0.5, w: 0.205, h: 1.02, fill: col, color: col, mb: 1,
          keys: { y: [[0, -1.05], [m - c.s(0.3) + lag, -1.05], [m + lag * 0.3, 0, "expoOut"], [m + c.s(0.12) + lag, 0, "linear"], [m + c.s(0.45) + lag, 1.05, "expoIn"]] } };
      }) };
    },
  },
  {
    id: "ml-tr-iris", name: "Iris", family: "transition",
    about: "A soft disc in the kit ground grows from the centre to swallow the shot, then opens out onto the next.",
    sample: { text: "" },
    build: (p, k, c) => {
      const m = p.dur / 2;
      const D = 2.4;
      return { v: 1, persp: 1400, exit: { kind: "fade", dur: 0 }, drift: { x: 0, y: 0, rotY: 0 }, layers: [
        { kind: "ellipse", x: 0.5, y: 0.5, w: D / c.aspect, h: D, fill: k.colors.bg2, color: k.colors.bg2, stroke: 0,
          keys: { scale: [[0, 0], [m - c.s(0.38), 0], [m, 1, "expoIn"], [m + c.s(0.42), 1, "linear"]], opacity: [[0, 1], [m + c.s(0.05), 1], [m + c.s(0.42), 0, "out"]],
            blur: [[0, 0], [m, 0], [m + c.s(0.42), 40, "out"]] } },
        { kind: "ellipse", x: 0.5, y: 0.5, w: 0.06 / c.aspect, h: 0.06, fill: k.colors.primary, color: k.colors.primary, stroke: 0,
          keys: { scale: [[0, 0], [m - c.s(0.25), 0], [m, 1, "expoOut"], [m + c.s(0.2), 0, "expoIn"]] } },
      ] };
    },
  },
  {
    id: "ml-tr-chapter", name: "Chapter wipe", family: "transition",
    about: "The kit ground wipes across the cut carrying a chapter title; it holds a beat, then wipes off onto the next shot.",
    sample: { text: "Part two: the deal", kicker: "Chapter 2" },
    build: (p, k, c) => {
      const d = p.dur;
      const inEnd = c.s(0.55), outStart = d - c.s(0.6);
      const lines = balance(T(p.text), 18, 2);
      const size = fitSize(lines, k.fonts.title, 0.6, c.aspect, 0.1, 0.05, true) * c.scale;
      return { v: 1, persp: 1400, exit: { kind: "fade", dur: 0 }, drift: { x: 0, y: 0, rotY: 0 }, layers: [
        { kind: "backdrop", color: k.colors.bg, color2: k.colors.bg2, wipeFrom: "l",
          keys: { wipe: [[0, 0], [inEnd, 1, "expoInOut"]], x: [[0, 0], [outStart, 0], [d, 1.02, "expoIn"]] }, mb: 0.6 },
        ...(lines.length && lines[0] ? [text({ lines, font: k.fonts.title, size, weight: k.titleWeight, color: k.colors.text, upper: true, x: 0.5, y: 0.52, anchor: "c", align: "center",
          animator: wordAnim(c, { y: 1.1 }, inEnd * 0.8, 0.08, 0.6, "expoOut", true),
          extra: { keys: { x: [[0, 0], [outStart, 0], [d, 1.02, "expoIn"]] }, mb: 0.6,
            kicker: p.kicker ? { text: T(p.kicker).toUpperCase(), size: size * 0.4, color: k.colors.pillText, bg: k.colors.pillBg, at: inEnd * 0.6 } : undefined } })] : []),
      ] };
    },
  },
  {
    id: "ml-tr-flash", name: "Light sweep", family: "transition",
    about: "A warm band of light rakes across the cut in screen blend - a soft, filmic way between two shots.",
    sample: { text: "" },
    build: (p, k, c) => {
      const m = p.dur / 2;
      const col = hexA(k.colors.primary, 0.85);
      return { v: 1, persp: 1400, exit: { kind: "fade", dur: 0 }, drift: { x: 0, y: 0, rotY: 0 }, layers: [
        { kind: "rect", x: 0.5, y: 0.5, w: 0.5, h: 1.6, fill: col, color: col, blend: "screen",
          keys: { x: [[0, -0.9], [m + c.s(0.4), 0.9, "inOut"]], rot: [[0, 18], [p.dur, 18]], blur: [[0, 60], [p.dur, 60]], opacity: [[0, 0], [m - c.s(0.2), 0.9, "out"], [m + c.s(0.35), 0, "in"]] } },
        { kind: "rect", x: 0.5, y: 0.5, w: 1.05, h: 1.02, fill: "#ffffff", color: "#ffffff", blend: "screen",
          keys: { opacity: [[0, 0], [m - c.s(0.08), 0, "linear"], [m, 0.55, "out"], [m + c.s(0.25), 0, "out"]] } },
      ] };
    },
  },
  // Motion pack 2 (2026-10-14): kinetic type, data, callouts, emphasis marks and transitions - see PACK2 above.
  ...PACK2,
  // The gaming video-essay pack (2026-10-15) - see GAMING above.
  ...GAMING,
];

export const RECIPE_BY_ID: Record<string, MxRecipe> = Object.fromEntries(RECIPES.map((r) => [r.id, r]));

/** Deterministic 0..1 from a seed. */
const hash01 = (n: number) => { const x = Math.sin(n * 12.9898 + 78.233) * 43758.5453; return x - Math.floor(x); };

/** The spec for look `id` with these params in this kit (null when the look or its words are missing). */
export const buildMotionLook = (id: string, params: MxParams, kit: BrandKit): MotionSpec | null => {
  const recipe = RECIPE_BY_ID[id];
  if (!recipe) return null;
  const dur = Math.max(0.5, Number(params.dur) || 3);
  const text = String(params.text || "").replace(/\s+/g, " ").trim();
  if (recipe.family !== "transition" && !text && !(typeof params.value === "number")) return null;
  const words = text.split(" ").filter(Boolean);
  const speed = Math.max(0.4, Math.min(2.5, Number(params.speed) || 1));
  const tempo = kit.tempo || 1;
  const seed = Math.round(Number(params.seed) || 0);
  const wordAt = Array.isArray(params.wordAt) ? params.wordAt.filter((v) => typeof v === "number" && Number.isFinite(v)) : [];
  const band = bandOf(params.position);
  const side = recipe.family === "transition" ? sideOf(params.position, "center", seed)
    : sideAway(sideOf(params.position, recipe.family === "lower-third" ? "left" : "center", seed), params.position, params.avoid, band);
  const c: Ctx = {
    s: (sec) => (sec * tempo) / speed,
    aspect: Math.max(0.4, Math.min(3, Number(params.aspect) || 16 / 9)),
    scale: Math.max(0.5, Math.min(1.8, Number(params.scale) || 1)),
    side,
    room: recipe.family === "transition" ? 1 : roomOn(side, params.avoid, band),
    y: band,
    r: (n) => hash01(seed * 31 + n),
    wt: (i, start, stagger) => {
      const at = wordAt[i];
      return at !== undefined && at >= 0 && at < dur ? at : ((start + i * stagger) * tempo) / speed;
    },
    words,
  };
  const raw = recipe.build({ ...params, text, dur }, kit, c);
  return cleanSpec(raw, dur);
};

/** The params a library overlay carries (the editor's fields), as a recipe reads them. */
export const paramsFromOverlay = (ov: Record<string, unknown>, fps: number, aspect: number): MxParams => {
  const rows = Array.isArray(ov.items) ? (ov.items as Record<string, unknown>[]).filter((i) => String(i?.label ?? i?.text ?? i?.value ?? "")) : [];
  const items = rows.length ? rows.map((i) => String(i?.label ?? i?.text ?? i?.value ?? "")) : undefined;
  const values = rows.length ? rows.map((i) => (typeof i?.value === "number" && Number.isFinite(i.value) && (i?.label ?? i?.text) ? i.value as number : undefined)) : undefined;
  const anchor = ov.anchor && typeof ov.anchor === "object" ? ov.anchor as { x?: number; y?: number } : null;
  return {
    text: String(ov.text ?? ""), sub: typeof ov.subtitle === "string" ? ov.subtitle : undefined,
    kicker: typeof ov.label === "string" ? ov.label : undefined,
    value: typeof ov.value === "number" ? ov.value : undefined, prefix: typeof ov.prefix === "string" ? ov.prefix : undefined,
    suffix: typeof ov.suffix === "string" ? ov.suffix : undefined, decimals: typeof ov.decimals === "number" ? ov.decimals : undefined,
    items, values, wordAt: Array.isArray(ov.wordAt) ? (ov.wordAt as number[]) : undefined,
    itemAt: Array.isArray(ov.itemAt) ? (ov.itemAt as number[]) : undefined,
    dur: Math.max(0.5, Number(ov.durationInFrames) / (fps || 30)), position: typeof ov.position === "string" ? ov.position : undefined,
    point: anchor && typeof anchor.x === "number" && typeof anchor.y === "number" ? { x: anchor.x, y: anchor.y } : undefined,
    seed: typeof ov.seed === "number" ? ov.seed : Math.round(Number(ov.startFrame) || 0), speed: typeof ov.speed === "number" ? ov.speed : 1,
    scale: typeof ov.scale === "number" ? ov.scale : 1, aspect,
    avoid: Array.isArray(ov.avoid) ? (ov.avoid as Box[]).filter((b) => b && [b.x, b.y, b.w, b.h].every((v) => typeof v === "number" && Number.isFinite(v))).slice(0, 12) : undefined,
  };
};
