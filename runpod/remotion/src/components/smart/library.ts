/**
 * Editor v2's motion library (2026-10-14): 33 premium looks - titles, lower thirds, figures, emphasis marks and
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

export type MxFamily = "title" | "lower-third" | "number" | "emphasis" | "transition";

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
  /** Short items (tiles, steps). */
  items?: string[];
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
}

export interface MxRecipe {
  id: string;
  name: string;
  family: MxFamily;
  /** One line for the look picker. */
  about: string;
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
const CH: Record<string, number> = { narrow: 0.45, grotesk: 0.6, kinetic: 0.56, display: 0.58, serif: 0.52, "serif-italic": 0.5, mono: 0.62, inter: 0.56 };

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

// ------------------------------------------------------------------ the recipes
const T = (s: string) => s.trim();

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
  const c: Ctx = {
    s: (sec) => (sec * tempo) / speed,
    aspect: Math.max(0.4, Math.min(3, Number(params.aspect) || 16 / 9)),
    scale: Math.max(0.5, Math.min(1.8, Number(params.scale) || 1)),
    side: sideOf(params.position, recipe.family === "lower-third" ? "left" : "center", seed),
    y: bandOf(params.position),
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
  const items = Array.isArray(ov.items) ? (ov.items as Record<string, unknown>[]).map((i) => String(i?.label ?? i?.text ?? i?.value ?? "")).filter(Boolean) : undefined;
  const anchor = ov.anchor && typeof ov.anchor === "object" ? ov.anchor as { x?: number; y?: number } : null;
  return {
    text: String(ov.text ?? ""), sub: typeof ov.subtitle === "string" ? ov.subtitle : undefined,
    kicker: typeof ov.label === "string" ? ov.label : undefined,
    value: typeof ov.value === "number" ? ov.value : undefined, prefix: typeof ov.prefix === "string" ? ov.prefix : undefined,
    suffix: typeof ov.suffix === "string" ? ov.suffix : undefined, decimals: typeof ov.decimals === "number" ? ov.decimals : undefined,
    items, wordAt: Array.isArray(ov.wordAt) ? (ov.wordAt as number[]) : undefined,
    dur: Math.max(0.5, Number(ov.durationInFrames) / (fps || 30)), position: typeof ov.position === "string" ? ov.position : undefined,
    point: anchor && typeof anchor.x === "number" && typeof anchor.y === "number" ? { x: anchor.x, y: anchor.y } : undefined,
    seed: typeof ov.seed === "number" ? ov.seed : Math.round(Number(ov.startFrame) || 0), speed: typeof ov.speed === "number" ? ov.speed : 1,
    scale: typeof ov.scale === "number" ? ov.scale : 1, aspect,
  };
};
