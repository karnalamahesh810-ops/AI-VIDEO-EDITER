import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY, INTER, LABEL, MONO } from "../fonts";
import type { MapLocation, Overlay, OverlayItem } from "../../types";
import { lines, ramp, useHold, useK } from "../pro/ProGraphics";

/**
 * Cinematic moments (family "cn-", registry category HEADLINES): the film
 * grammar of a documentary - the location stamp, the "based on true events"
 * card, scope bars, the black-and-white character intro, tunnel vision, the
 * stage light, the quiet quote, the end card, the credits and the chapter
 * scrubber. Tags ride on the playing footage (low ones kept clear of the
 * burned-in captions); cards draw their own full-frame backdrop (always on as
 * a full-screen scene; laid over footage they dissolve in and out, the end
 * card wipes in and out behind its arrow).
 *
 *   cn-place-stamp        (tag) the thriller location stamp low left: place,
 *                         date and time, the pin's coordinates in mono; letters
 *                         rise one by one behind an accent cursor bar that
 *                         leads the reveal row by row and blinks at the end
 *   cn-true-events        (card) "BASED ON TRUE EVENTS" on black film grain:
 *                         wide-tracked caps rising from the centre outward, the
 *                         tracking slowly opening, the word TRUE warming to the
 *                         accent under a projector flicker
 *   cn-letterbox-caption  (tag) 2.39:1 scope bars close in with a glint along
 *                         their edges, the picture takes a filmic grade, an
 *                         anamorphic streak crosses as the caption rises word
 *                         by word; a place line sits in the top bar
 *   cn-bw-flash-intro     (tag) a camera flash, the footage drops to grainy
 *                         black and white, the name whips out of its mask and
 *                         the role follows an accent rule; colour returns on a
 *                         softer second flash
 *   cn-focus-vignette     (tag) an iris vignette closes in, the edges fall out
 *                         of focus, one line rises letter by letter in the
 *                         clear centre, its key word warming to the accent
 *   cn-spotlight-title    (card) a stage lamp strikes on and its beam sweeps a
 *                         dark stage, each letter rising as the light finds it;
 *                         the beam swings back, opens over the title and cuts
 *                         out with a flicker
 *   cn-drift-quote        (card) a quote rising word by word on near-black, the
 *                         block drifting and pushing in, dust motes and soft
 *                         lights floating past at several depths
 *   cn-to-be-continued    (card) a white and an accent chevron sweep across and
 *                         uncover the end card: an arrow plate drawing on round
 *                         the words, its tip snapping in, chevrons pulsing
 *                         onward; the same arrow sweeps it all away
 *   cn-sources-roll       (card) end credits of the sources: what on the left,
 *                         who on the right, the reference number in the gutter
 *                         lighting up as each row passes the reading line
 *   cn-chapter-progress   (tag) a thin chapter scrubber across the top: the
 *                         segments draw, finished chapters fill, the current
 *                         one lifts in the accent with its playhead, the
 *                         chapter number rolls in beneath with the title
 *
 * Text never fades or types: letters and words rise out of masks (or whip out
 * of them) and leave the same way in the last ~14 frames. Deterministic:
 * seeded noise only.
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;
type RGB = [number, number, number];
type Pt = [number, number];

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const expoIn = Easing.bezier(0.7, 0, 0.84, 0);
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const softOut = Easing.bezier(0.22, 1, 0.36, 1);
const rollEase = Easing.bezier(0.35, 0, 0.35, 1);
const GOLD = "#F2B544";
const SHADOW = "0 6px 28px rgba(0,0,0,.55)";
const DIGITS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 0];
/**
 * Bottom edge (1080p px) the low tags keep clear of: burned-in captions sit
 * centred at the bottom and reach ~244 px when a caption wraps to two lines.
 */
const LOW = 262;

// ================================================================== helpers
const str = (s: unknown): string => (typeof s === "string" ? s.replace(/\s+/g, " ").trim() : "");
const cap = (s: unknown): string => str(s).toUpperCase();
const norm = (w: string): string => w.toLowerCase().replace(/[^\p{L}\p{N}']/gu, "");
const pad2 = (n: number): string => String(Math.max(0, Math.round(n))).padStart(2, "0");
/** A finite number, or null (null, "" and booleans are not 0). */
const finite = (v: unknown): number | null => {
  if (v === null || v === undefined || v === "" || typeof v === "boolean") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};
/** 0 -> 1 between two frames (never an invalid interpolate range). */
const span = (frame: number, a: number, b: number, ease?: (t: number) => number): number =>
  interpolate(frame, [a, Math.max(a + 1, b)], [0, 1], ease ? { ...clamp, easing: ease } : clamp);

/** Deterministic 0..1 noise from an integer seed (one mulberry32 step; never Math.random). */
const rnd = (seed: number): number => {
  let t = (Math.imul(Math.floor(seed) | 0, 0x6d2b79f5) + 0x9e3779b9) | 0;
  t = Math.imul(t ^ (t >>> 15), t | 1);
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};
const seedOf = (s: string): number => {
  let h = 7;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 1000003;
  return h;
};

/** #rgb, #rrggbb, #rrggbbaa or rgb()/rgba() -> [r, g, b]; null for anything else. */
const rgbOf = (c: string): RGB | null => {
  const s = typeof c === "string" ? c.trim() : "";
  const hex = /^#?([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.exec(s);
  if (hex) {
    const h = hex[1].length === 3 ? hex[1].split("").map((x) => x + x).join("") : hex[1].slice(0, 6);
    const n = parseInt(h, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  const rgb = /^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)/i.exec(s);
  return rgb ? [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])] : null;
};
const byte = (x: number): number => Math.max(0, Math.min(255, Math.round(Number.isFinite(x) ? x : 0)));
const hexOf = (v: RGB): string => `#${v.map((x) => byte(x).toString(16).padStart(2, "0")).join("")}`;
/** The accent as a clean #hex, the house gold when the prop is not a usable colour. */
const safeAccent = (a: string): string => {
  const v = rgbOf(str(a));
  return v ? hexOf(v) : GOLD;
};
const alpha = (c: string, a: number): string => {
  const v: RGB = rgbOf(c) ?? [242, 181, 68];
  return `rgba(${byte(v[0])},${byte(v[1])},${byte(v[2])},${Math.max(0, Math.min(1, a)).toFixed(3)})`;
};
/** a -> b by t (0..1), as rgb(). */
const mix = (a: string, b: string, t: number): string => {
  const x: RGB = rgbOf(a) ?? [255, 255, 255];
  const y: RGB = rgbOf(b) ?? [242, 181, 68];
  const u = Math.max(0, Math.min(1, Number.isFinite(t) ? t : 0));
  return `rgb(${byte(x[0] + (y[0] - x[0]) * u)},${byte(x[1] + (y[1] - x[1]) * u)},${byte(x[2] + (y[2] - x[2]) * u)})`;
};

/** Wrapped lines, capped; the last kept line ends in an ellipsis when words were dropped. */
const wrap = (text: string, chars: number, max: number): string[] => {
  const ls = lines(text, chars);
  if (ls.length <= max) return ls;
  const out = ls.slice(0, max);
  out[max - 1] = `${out[max - 1].replace(/[\s,.;:!?…–—-]+$/, "")}…`;
  return out;
};
/** One line of at most `max` characters, cut at a word with an ellipsis. */
const clip = (s: string, max: number): string => {
  const chars = Array.from(s);
  if (chars.length <= max) return s;
  const head = lines(s, max - 1)[0] || "";
  const cut = head && Array.from(head).length <= max - 1 ? head : chars.slice(0, max - 1).join("");
  return `${cut.replace(/[\s,;:·–—-]+$/, "")}…`;
};

/** The words to paint: overlay.highlight when given, else the fallback words found in the text. */
const markSet = (given: unknown, text: string, fallback: string[] = []): Set<string> => {
  const set = new Set(str(given).split(/[\s,]+/).map(norm).filter(Boolean));
  if (set.size) return set;
  const present = new Set(text.split(/\s+/).map(norm));
  return new Set(fallback.filter((w) => present.has(w)));
};

/** Per letter of a line: does it belong to a marked word? */
const hotLetters = (line: string, marks: Set<string>): boolean[] => {
  const chars = Array.from(line);
  const out: boolean[] = chars.map(() => false);
  if (!marks.size) return out;
  let start = 0;
  let word = "";
  const flush = (end: number) => {
    const hot = marks.has(norm(word));
    for (let i = start; i < end; i++) out[i] = hot;
  };
  chars.forEach((c, i) => {
    if (c === " ") {
      flush(i);
      word = "";
      start = i + 1;
    } else {
      word += c;
    }
  });
  flush(chars.length);
  return out;
};

// ================================================================== shared motion
/** Exit progress: 0 while the graphic holds, 1 once it has left. */
const useExit = (lead = 12, frames = 10): number => {
  const frame = useCurrentFrame();
  const { durationInFrames: D } = useVideoConfig();
  return ramp(frame, D - lead, frames, expoIn);
};

/** An own backdrop: always on as a full-screen scene; over footage it dissolves in and out. */
const useBackdrop = (ov: Overlay): number => {
  const frame = useCurrentFrame();
  const { durationInFrames: D } = useVideoConfig();
  if (ov.fullFrame) return 1;
  return ramp(frame, 0, 8) * (1 - ramp(frame, D - 10, 9, inOut));
};

/** A soft local shade behind a tag: in over 10 frames, out over the last 10. */
const useShade = (): number => {
  const frame = useCurrentFrame();
  const { durationInFrames: D } = useVideoConfig();
  return ramp(frame, 0, 10) * (1 - ramp(frame, D - 10, 10));
};

// ================================================================== shared components
/**
 * A line of letters rising out of its mask one after another - from the left,
 * or from the centre outward - and leaving up through it in the last frames
 * (the last letter is gone by the final frame). `starts` gives each letter its
 * own start frame instead of the stagger; marked letters (`hot`) turn to
 * `hotColor` from `hotAt`, with a soft glow.
 */
const Letters: React.FC<{
  text: string; at: number; spread?: number; rise?: number; order?: "ltr" | "center"; starts?: number[];
  outAt?: number; hot?: boolean[]; hotColor?: string; hotAt?: number; glow?: number; style?: React.CSSProperties;
}> = ({ text, at, spread = 14, rise = 12, order = "ltr", starts, outAt, hot, hotColor, hotAt = 0, glow = 0, style }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: D } = useVideoConfig();
  const chars = Array.from(text);
  const mid = (chars.length - 1) / 2;
  const maxRank = Math.max(0, order === "center" ? mid : chars.length - 1);
  const step = maxRank > 0 ? Math.min(1.1, spread / maxRank) : 0;
  const outStep = maxRank > 0 ? Math.min(0.6, 5 / maxRank) : 0;
  const end = outAt ?? D - 14;
  const lit = ramp(frame, hotAt, 14);
  const base = style && typeof style.color === "string" ? style.color : "#ffffff";
  const hc = hotColor || GOLD;
  return (
    <div style={{ overflow: "hidden", paddingBottom: "0.1em", whiteSpace: "pre", ...style }}>
      {chars.map((c, i) => {
        const rank = order === "center" ? Math.abs(i - mid) : i;
        const own = starts ? starts[i] : undefined;
        const s0 = typeof own === "number" && Number.isFinite(own) ? own : at + rank * step;
        const pin = ramp(frame, s0, rise);
        const pout = ramp(frame, end + rank * outStep, 8, expoIn);
        const isHot = Boolean(hot && hot[i]);
        return (
          <span key={i} style={{ display: "inline-block",
            transform: `translateY(${((1 - pin) * 108 - pout * 108).toFixed(2)}%)`,
            opacity: pin < 0.01 || pout > 0.99 ? 0 : 1, color: isHot ? mix(base, hc, lit) : undefined,
            textShadow: isHot && glow > 0 ? `0 0 ${glow.toFixed(1)}px ${alpha(hc, 0.55 * lit)}` : undefined }}>{c}</span>
        );
      })}
    </div>
  );
};

/**
 * A line of words rising out of its mask one after another and leaving up
 * through it at the end; marked words in `hotColor`, optional quotation marks
 * (`lead` / `tail`) riding on the first and last word.
 */
const Words: React.FC<{
  text: string; at: number; step?: number; rise?: number; outAt?: number; marks?: Set<string>; hotColor?: string;
  lead?: string; tail?: string; markColor?: string; style?: React.CSSProperties;
}> = ({ text, at, step = 3, rise = 14, outAt, marks, hotColor, lead, tail, markColor, style }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: D } = useVideoConfig();
  const ws = text.split(" ").filter(Boolean);
  const end = outAt ?? D - 14;
  const outStep = ws.length > 1 ? Math.min(1, 5 / (ws.length - 1)) : 0;
  return (
    <div style={{ overflow: "hidden", paddingBottom: "0.14em", whiteSpace: "nowrap", ...style }}>
      {ws.map((w, i) => {
        const pin = ramp(frame, at + i * step, rise);
        const pout = ramp(frame, end + i * outStep, 8, expoIn);
        const hot = Boolean(marks && hotColor && marks.has(norm(w)));
        return (
          <span key={i} style={{ display: "inline-block", whiteSpace: "pre",
            transform: `translateY(${((1 - pin) * 112 - pout * 112).toFixed(2)}%)`,
            opacity: pin < 0.01 || pout > 0.99 ? 0 : 1, color: hot ? hotColor : undefined }}>
            {i === 0 && lead ? <span style={{ color: markColor }}>{lead}</span> : null}
            {w}
            {i === ws.length - 1 && tail ? <span style={{ color: markColor }}>{tail}</span> : null}
            {i < ws.length - 1 ? " " : ""}
          </span>
        );
      })}
    </div>
  );
};

/** A line whipping out of its mask from the left, leaning with its speed, and leaving to the right at the end. */
const SlideLine: React.FC<{ at: number; outAt?: number; frames?: number; children: React.ReactNode;
  style?: React.CSSProperties }> = ({ at, outAt, frames = 16, children, style }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: D } = useVideoConfig();
  const oa = outAt ?? D - 13;
  const pin = ramp(frame, at, frames);
  const pout = ramp(frame, oa, 10, expoIn);
  const speed = (pin - ramp(frame - 1, at, frames)) + (pout - ramp(frame - 1, oa, 10, expoIn));
  const skew = -Math.min(14, Math.max(0, speed) * 150);
  return (
    <div style={{ overflow: "hidden", paddingBottom: "0.06em", ...style }}>
      <div style={{ transform: `translateX(${(-(1 - pin) * 104 + pout * 104).toFixed(2)}%) skewX(${skew.toFixed(2)}deg)`,
        opacity: pin < 0.01 || pout > 0.99 ? 0 : 1 }}>
        {children}
      </div>
    </div>
  );
};

/** Film grain: fractal noise re-seeded every other frame, laid over softly. */
const Grain: React.FC<{ id: string; opacity: number }> = ({ id, opacity }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  if (!(opacity > 0.001)) return null;
  return (
    <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0, opacity, mixBlendMode: "overlay",
      pointerEvents: "none" }}>
      <filter id={id} x="0" y="0" width="100%" height="100%">
        <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves={2} seed={Math.floor(frame / 2) % 16}
          stitchTiles="stitch" />
        <feColorMatrix type="saturate" values="0" />
      </filter>
      <rect width={width} height={height} filter={`url(#${id})`} />
    </svg>
  );
};

/**
 * A number whose digit columns spin into place (leading zeros kept, "03"),
 * the right-most turning furthest with a ghosted motion trail; the number
 * rises out of its mask as it spins and drops away through it at the end.
 */
const RollDigits: React.FC<{ text: string; at: number; frames: number; size: number; color: string; outAt: number }> =
  ({ text, at, frames, size, color, outAt }) => {
    const frame = useCurrentFrame();
    const chars = Array.from(text);
    const rise = ramp(frame, at, 12);
    const drop = ramp(frame, outAt, 10, expoIn);
    const trail = "rgba(255,255,255,.3)";
    let di = 0;
    return (
      <div style={{ height: size, overflow: "hidden" }}>
        <div style={{ display: "flex", fontFamily: DISPLAY, fontSize: size, lineHeight: 1, color,
          fontVariantNumeric: "tabular-nums", transform: `translateY(${((1 - rise) * 110 - drop * 110).toFixed(2)}%)` }}>
          {chars.map((c, i) => {
            if (!/\d/.test(c)) return <span key={i}>{c}</span>;
            const order = di;
            di += 1;
            const travel = (1 + Math.min(2, order)) * 10 + Number(c);
            const start = at + order * 3;
            const pos = ramp(frame, start, frames) * travel;
            const prev = ramp(frame - 1, start, frames) * travel;
            const sp = Math.min(1.3, Math.abs(pos - prev));
            const sh = sp > 0.04
              ? `0 ${(sp * size * 0.16).toFixed(1)}px ${(sp * size * 0.06).toFixed(1)}px ${trail}, ` +
                `0 ${(-sp * size * 0.16).toFixed(1)}px ${(sp * size * 0.06).toFixed(1)}px ${trail}`
              : undefined;
            return (
              <span key={i} style={{ display: "inline-block", height: size, overflow: "hidden" }}>
                <span style={{ display: "flex", flexDirection: "column", textShadow: sh,
                  transform: `translateY(${(-(pos % 10) * size).toFixed(2)}px)` }}>
                  {DIGITS.map((d, j) => <span key={j} style={{ height: size, display: "block" }}>{d}</span>)}
                </span>
              </span>
            );
          })}
        </div>
      </div>
    );
  };

// ================================================================== 1. place-time stamp
/** "36.2500°N   114.3900°W" from the first usable map pin; "" without one. */
const coordLine = (locs?: MapLocation[]): string => {
  if (!Array.isArray(locs)) return "";
  for (const l of locs) {
    if (!l || typeof l !== "object") continue;
    const lat = finite(l.lat);
    const lon = finite(l.lon);
    if (lat === null || lon === null || Math.abs(lat) > 90 || Math.abs(lon) > 180) continue;
    return `${Math.abs(lat).toFixed(4)}°${lat >= 0 ? "N" : "S"}   ${Math.abs(lon).toFixed(4)}°${lon >= 0 ? "E" : "W"}`;
  }
  return "";
};

type StampRow = { text: string; step: number; gap: number; style: React.CSSProperties };

/**
 * The thriller location stamp, low left on the footage: the place in heavy
 * condensed caps, the date and time under it (subtitle · label), the pin's
 * coordinates in mono. Letters rise one after another behind an accent cursor
 * bar that leads the reveal row by row, then blinks at the end of the last
 * row until the letters drop away and the bar collapses.
 */
const PlaceStamp: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const shade = useShade();
  const acc = safeAccent(accent);
  const place = cap(overlay.text);
  if (!place) return null;
  const when = [cap(overlay.subtitle), cap(overlay.label)].filter(Boolean).join(" · ");
  const coords = coordLine(overlay.locations);
  const placeLines = wrap(place, 24, 2);
  const big = (placeLines.length > 1 || place.length > 18 ? 48 : 56) * k;
  const rows: StampRow[] = [];
  placeLines.forEach((t, i) => rows.push({ text: t, step: 1, gap: i ? 2 : 0, style: { fontFamily: LABEL,
    fontWeight: 800, fontSize: big, lineHeight: 1.04, letterSpacing: "0.05em", color: "#fff" } }));
  wrap(when, 40, 2).forEach((t, i) => rows.push({ text: t, step: 0.7, gap: i ? 2 : 5, style: { fontFamily: LABEL,
    fontWeight: 600, fontSize: 30 * k, lineHeight: 1.12, letterSpacing: "0.16em", color: "rgba(255,255,255,.86)",
    marginTop: i ? 0 : 8 * k } }));
  if (coords) {
    rows.push({ text: coords, step: 0.4, gap: 4, style: { fontFamily: MONO, fontWeight: 500, fontSize: 24 * k,
      lineHeight: 1.25, letterSpacing: "0.06em", color: "rgba(255,255,255,.64)", marginTop: 12 * k } });
  }
  // The reveal clock: each row starts where the last one ended, the whole stamp out inside ~1.5 s.
  const lens = rows.map((r) => Array.from(r.text).length);
  const raw = rows.reduce((s, r, j) => s + r.gap + lens[j] * r.step, 0);
  const budget = fps * 1.5;
  const squeeze = raw > budget ? budget / raw : 1;
  const starts: number[] = [];
  const steps: number[] = [];
  let clock = 6;
  rows.forEach((r, j) => {
    const st = Math.max(0.05, r.step * squeeze);
    clock += r.gap * squeeze;
    starts.push(clock);
    steps.push(st);
    clock += lens[j] * st;
  });
  const revealEnd = clock;
  let active = 0;
  starts.forEach((s, j) => {
    if (frame >= s) active = j;
  });
  const startedIn = (j: number): number =>
    frame < starts[j] ? 0 : Math.min(lens[j], Math.floor((frame - starts[j]) / steps[j]) + 1);
  // Letters leave from here; the last one (row offset + stagger) is gone by the final frame.
  const end = D - 16;
  const half = Math.max(4, Math.round(fps * 0.5));
  const blinkOn = frame < revealEnd + 4 || Math.floor((frame - revealEnd - 4) / half) % 2 === 0;
  const cursorIn = ramp(frame, 1, 7, backOut);
  const cursorOut = ramp(frame, end, 6, expoIn);
  const drift = interpolate(frame, [0, Math.max(1, D)], [0, 8 * k], clamp);
  const cursor = (
    <span style={{ display: "inline-block", width: "0.11em", height: "0.8em", marginLeft: "0.1em", background: acc,
      verticalAlign: "baseline", transform: `scaleY(${Math.max(0, cursorIn * (1 - cursorOut)).toFixed(3)})`,
      transformOrigin: "50% 100%", opacity: blinkOn ? 1 : 0,
      boxShadow: `0 0 ${(10 * k).toFixed(1)}px ${alpha(acc, 0.6)}` }} />
  );
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: shade, background:
        "radial-gradient(ellipse 60% 62% at 0% 100%, rgba(0,0,0,.62) 0%, rgba(0,0,0,.3) 45%, rgba(0,0,0,0) 78%)" }} />
      <div style={{ position: "absolute", left: 110 * k, bottom: LOW * k, display: "flex", flexDirection: "column",
        alignItems: "flex-start", textShadow: SHADOW, transform: `translateX(${drift.toFixed(2)}px)` }}>
        {rows.map((r, j) => {
          const n = startedIn(j);
          const outStep = lens[j] > 1 ? Math.min(0.5, 5 / (lens[j] - 1)) : 0;
          const rowOut = end + Math.min(j, 2);
          return (
            <div key={j} style={{ overflow: "hidden", paddingBottom: "0.1em", whiteSpace: "pre", ...r.style }}>
              {j === active && n === 0 ? cursor : null}
              {Array.from(r.text).map((c, i) => {
                const pin = ramp(frame, starts[j] + i * steps[j], 10);
                const pout = ramp(frame, rowOut + i * outStep, 8, expoIn);
                return (
                  <React.Fragment key={i}>
                    <span style={{ display: "inline-block", opacity: i < n && pout < 0.99 ? 1 : 0,
                      transform: `translateY(${((1 - pin) * 105 - pout * 108).toFixed(2)}%)` }}>{c}</span>
                    {j === active && n > 0 && i === n - 1 ? cursor : null}
                  </React.Fragment>
                );
              })}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 2. true events card
/**
 * "BASED ON TRUE EVENTS": small wide-tracked caps on black film grain, each
 * line's letters rising from the centre outward while the tracking slowly
 * opens; once the lines have landed the marked word (TRUE / REAL by default,
 * or the highlight) warms to the accent with a faint bloom behind it. A
 * flickering projector light breathes over the grain.
 */
const TrueEvents: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const bg = useBackdrop(overlay);
  const acc = safeAccent(accent);
  const text = cap(overlay.text);
  if (!text) return null;
  const sub = clip(cap(overlay.subtitle), 44);
  const marks = markSet(overlay.highlight, text, ["true", "real"]);
  const ls = wrap(text, 24, 3);
  const longest = Math.max(1, ...ls.map((l) => Array.from(l).length));
  // Inter caps plus up to 0.56 em tracking advance ~1.28 em a letter: the widest line stays inside ~1500 px.
  const size = Math.min(ls.length > 1 ? 44 : 48, 1500 / (longest * 1.28)) * k;
  const track = interpolate(frame, [0, Math.max(1, D)], [0.44, 0.56], clamp);
  const lineAt = (i: number): number => 8 + i * 7;
  const hotAt = lineAt(ls.length - 1) + Math.round(fps * 0.7);
  const glow = ramp(frame, hotAt, 24) * (1 - ramp(frame, D - 14, 10));
  const breath = 0.84 + 0.16 * rnd(Math.floor(frame / 3) + 11);
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{ opacity: bg,
        background: "radial-gradient(ellipse at 50% 46%, #111113 0%, #070708 55%, #020203 100%)" }}>
        <AbsoluteFill style={{ opacity: breath, background:
          "radial-gradient(ellipse 50% 36% at 50% 48%, rgba(255,242,222,.075) 0%, rgba(255,242,222,0) 72%)" }} />
        <Grain id={`cnte${overlay.startFrame}`} opacity={0.075} />
        <AbsoluteFill style={{ boxShadow: `inset 0 0 ${(340 * k).toFixed(1)}px rgba(0,0,0,.92)` }} />
      </AbsoluteFill>
      <AbsoluteFill style={{ opacity: glow, background: `radial-gradient(ellipse ${(560 * k).toFixed(1)}px ` +
        `${(150 * k).toFixed(1)}px at 50% 50%, ${alpha(acc, 0.12)} 0%, ${alpha(acc, 0)} 100%)` }} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 14 * k, maxWidth: 1740 * k }}>
          {ls.map((ln, i) => (
            <Letters key={i} text={ln} at={lineAt(i)} spread={14} rise={16} order="center" hot={hotLetters(ln, marks)}
              hotColor={acc} hotAt={hotAt} glow={18 * k} style={{ fontFamily: INTER, fontWeight: 400, fontSize: size,
                lineHeight: 1.2, letterSpacing: `${track.toFixed(4)}em`, paddingLeft: `${track.toFixed(4)}em`,
                color: "#f1f1f1" }} />
          ))}
          {sub ? (
            <Letters text={sub} at={hotAt - 6} spread={12} rise={16} order="center" style={{ marginTop: 26 * k,
              fontFamily: LABEL, fontWeight: 600, fontSize: 24 * k, letterSpacing: "0.38em", paddingLeft: "0.38em",
              color: "rgba(255,255,255,.52)" }} />
          ) : null}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 3. letterbox caption
/**
 * Scope bars (2.39:1) close in over the footage with a glint running out along
 * their inner edges, and the picture takes a filmic grade (less colour, more
 * contrast, no darkening); an anamorphic streak crosses the caption line as its
 * words rise, centred in the lower picture above the burned-in captions. A
 * place or time line (subtitle) sits centred at the top bar's inner edge.
 */
const LetterboxCaption: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width: W, height: H, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const acc = safeAccent(accent);
  const text = str(overlay.text).replace(/^["“”'‘’«»]+|["“”'‘’«»]+$/g, "").trim();
  if (!text) return null;
  const sub = clip(cap(overlay.subtitle), 48);
  const marks = markSet(overlay.highlight, text);
  const BAR = Math.min(H * 0.16, Math.max(90 * k, (H - W / 2.39) / 2));
  const bars = ramp(frame, 0, Math.round(fps * 0.5)) * (1 - ramp(frame, D - 12, 11, expoIn));
  const grow = span(frame, 8, 26, inOut);
  const glint = span(frame, 8, 14) * (1 - span(frame, 22, 44));
  const ls = wrap(text, 44, 2);
  const size = (ls.length > 1 ? 44 : 50) * k;
  const capAt = Math.round(fps * 0.4);
  const counts = ls.map((l) => l.split(" ").filter(Boolean).length);
  const total = counts.reduce((a, b) => a + b, 0);
  const step = Math.max(1.5, Math.min(3, 36 / Math.max(1, total)));
  const lineAt = (i: number): number => capAt + counts.slice(0, i).reduce((a, b) => a + b, 0) * step;
  const capBottom = Math.max(BAR + 96 * k, LOW * k);
  const capY = H - capBottom - (ls.length * size * 1.3) / 2;
  // The anamorphic streak: a flare point crossing the caption line from left to right.
  const s0 = capAt - 4;
  const sp = span(frame, s0, s0 + Math.round(fps * 0.85), inOut);
  const sI = span(frame, s0, s0 + 6) * (1 - span(frame, s0 + Math.round(fps * 0.45), s0 + Math.round(fps * 1.05)));
  const sx = (-0.1 + 1.2 * sp) * W;
  const sxp = (sx / W) * 100;
  const glintStyle = (onTopBar: boolean): React.CSSProperties => ({
    position: "absolute", left: 0, right: 0, top: onTopBar ? undefined : 0, bottom: onTopBar ? 0 : undefined,
    height: 2 * k, background: `linear-gradient(90deg, ${alpha(acc, 0)} 0%, ${alpha(acc, 0.95)} 50%, ${alpha(acc, 0)} 100%)`,
    transform: `scaleX(${(0.15 + 0.85 * grow).toFixed(3)})`, opacity: glint,
    boxShadow: `0 0 ${(10 * k).toFixed(1)}px ${alpha(acc, 0.6)}`,
  });
  const grade = "saturate(0.8) contrast(1.1)";
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: bars, backdropFilter: grade, WebkitBackdropFilter: grade }} />
      <AbsoluteFill style={{ opacity: bars, background:
        "linear-gradient(to top, rgba(0,0,0,.5) 0%, rgba(0,0,0,.22) 34%, rgba(0,0,0,0) 55%)" }} />
      {sI > 0.001 ? (
        <>
          <div style={{ position: "absolute", left: 0, top: capY - 34 * k, width: W, height: 68 * k, opacity: sI * 0.6,
            background: `radial-gradient(ellipse ${(W * 0.4).toFixed(1)}px ${(34 * k).toFixed(1)}px at ${sx.toFixed(1)}px 50%, ` +
              `${alpha(acc, 0.4)} 0%, ${alpha(acc, 0)} 100%)` }} />
          <div style={{ position: "absolute", left: 0, top: capY - 1.5 * k, width: W, height: 3 * k, opacity: sI,
            background: `linear-gradient(90deg, rgba(255,255,255,0) ${(sxp - 42).toFixed(2)}%, ${alpha(acc, 0.65)} ` +
              `${(sxp - 10).toFixed(2)}%, #ffffff ${sxp.toFixed(2)}%, ${alpha(acc, 0.65)} ${(sxp + 10).toFixed(2)}%, ` +
              `rgba(255,255,255,0) ${(sxp + 42).toFixed(2)}%)` }} />
          <div style={{ position: "absolute", left: sx - 45 * k, top: capY - 45 * k, width: 90 * k, height: 90 * k,
            borderRadius: "50%", opacity: sI,
            background: "radial-gradient(circle, rgba(255,255,255,.95) 0%, rgba(255,255,255,.35) 18%, rgba(255,255,255,0) 60%)" }} />
        </>
      ) : null}
      <div style={{ position: "absolute", left: 90 * k, right: 90 * k, bottom: capBottom, display: "flex",
        flexDirection: "column", alignItems: "center", textAlign: "center", textShadow: SHADOW,
        transform: `scale(${hold})`, transformOrigin: "50% 100%" }}>
        {ls.map((ln, i) => (
          <Words key={i} text={ln} at={lineAt(i)} step={step} rise={16} marks={marks} hotColor={acc}
            style={{ fontFamily: LABEL, fontWeight: 600, fontSize: size, lineHeight: 1.16, letterSpacing: "0.02em",
              color: "#fff" }} />
        ))}
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: BAR, background: "#000",
        transform: `translateY(${(-(1 - bars) * 100).toFixed(2)}%)` }}>
        {sub ? (
          <div style={{ position: "absolute", left: 0, right: 0, bottom: 18 * k, display: "flex", justifyContent: "center" }}>
            <Letters text={sub} at={capAt + 4} spread={12} order="center" style={{ fontFamily: LABEL, fontWeight: 600,
              fontSize: 24 * k, lineHeight: 1.1, letterSpacing: "0.36em", paddingLeft: "0.36em",
              color: "rgba(255,255,255,.66)" }} />
          </div>
        ) : null}
        <div style={glintStyle(true)} />
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: BAR, background: "#000",
        transform: `translateY(${((1 - bars) * 100).toFixed(2)}%)` }}>
        <div style={glintStyle(false)} />
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 4. black-and-white flash intro
/**
 * The character intro: a camera flash whites out the frame and the footage
 * underneath drops to contrasty, grainy black and white; the name whips out of
 * its mask from the left (leaning with its speed), the role follows behind an
 * accent rule, a small kicker (label) rises above. A softer second flash
 * brings the colour back as the words leave to the right.
 */
const BwFlashIntro: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: D } = useVideoConfig();
  const k = useK();
  const shade = useShade();
  const acc = safeAccent(accent);
  const name = cap(overlay.text);
  if (!name) return null;
  const role = clip(cap(overlay.subtitle), 46);
  const kicker = clip(cap(overlay.label), 32);
  const FL = 3;
  const back = Math.max(FL + 24, D - 12);
  const flash = frame <= FL ? span(frame, 0, FL) * 0.95 : 0.95 * Math.exp(-(frame - FL) / 3.4);
  const flash2 = frame < back ? 0 : 0.4 * Math.exp(-(frame - back) / 2.6);
  const gray = frame < FL ? 0 : 1 - span(frame, back, back + 5);
  const ls = wrap(name, 20, 2);
  const size = (ls.length > 1 || name.length > 16 ? 72 : 86) * k;
  const nameAt = FL + 5;
  const roleAt = nameAt + 7 + ls.length * 3;
  const rule = ramp(frame, roleAt - 2, 14) * (1 - ramp(frame, D - 13, 9, expoIn));
  const drift = interpolate(frame, [0, Math.max(1, D)], [0, 10 * k], clamp);
  const mono = `grayscale(${gray.toFixed(3)}) contrast(${(1 + 0.24 * gray).toFixed(3)}) ` +
    `brightness(${(1 - 0.08 * gray).toFixed(3)})`;
  const white = Math.max(flash, flash2);
  return (
    <AbsoluteFill>
      {gray > 0.001 ? <AbsoluteFill style={{ backdropFilter: mono, WebkitBackdropFilter: mono }} /> : null}
      {gray > 0.5 ? <Grain id={`cnbw${overlay.startFrame}`} opacity={0.13 * gray} /> : null}
      {gray > 0.001 ? (
        <AbsoluteFill style={{ opacity: gray, boxShadow: `inset 0 0 ${(300 * k).toFixed(1)}px rgba(0,0,0,.6)` }} />
      ) : null}
      <AbsoluteFill style={{ opacity: shade, background:
        "radial-gradient(ellipse 62% 60% at 0% 100%, rgba(0,0,0,.6) 0%, rgba(0,0,0,.26) 48%, rgba(0,0,0,0) 80%)" }} />
      <div style={{ position: "absolute", left: 120 * k, bottom: LOW * k, display: "flex", flexDirection: "column",
        alignItems: "flex-start", textShadow: SHADOW, transform: `translateX(${drift.toFixed(2)}px)` }}>
        {kicker ? (
          <Letters text={kicker} at={nameAt - 1} spread={10} style={{ fontFamily: LABEL, fontWeight: 800,
            fontSize: 24 * k, letterSpacing: "0.34em", color: acc, marginBottom: 6 * k }} />
        ) : null}
        {ls.map((ln, i) => (
          <SlideLine key={i} at={nameAt + i * 4} outAt={D - 13 + i}>
            <span style={{ display: "inline-block", fontFamily: DISPLAY, fontSize: size, lineHeight: 0.98,
              letterSpacing: "0.02em", color: "#fff", whiteSpace: "nowrap" }}>{ln}</span>
          </SlideLine>
        ))}
        {role ? (
          <div style={{ display: "flex", alignItems: "center", gap: 16 * k, marginTop: 12 * k }}>
            <div style={{ width: 54 * k, height: 5 * k, background: acc, transform: `scaleX(${rule.toFixed(3)})`,
              transformOrigin: "0 50%", boxShadow: `0 0 ${(12 * k).toFixed(1)}px ${alpha(acc, 0.5)}` }} />
            <SlideLine at={roleAt} outAt={D - 12}>
              <span style={{ display: "inline-block", fontFamily: LABEL, fontWeight: 700, fontSize: 32 * k,
                letterSpacing: "0.14em", color: "rgba(255,255,255,.9)", whiteSpace: "nowrap" }}>{role}</span>
            </SlideLine>
          </div>
        ) : null}
      </div>
      {white > 0.002 ? <AbsoluteFill style={{ background: "#fff", opacity: white }} /> : null}
    </AbsoluteFill>
  );
};

// ================================================================== 5. focus vignette
/**
 * Tunnel vision: an iris vignette closes in on the footage and its edges fall
 * out of focus (a masked backdrop blur), breathing slightly, while one line
 * rises letter by letter in the clear centre, the marked word warming to the
 * accent, a hairline drawing out beneath. The iris opens as the line leaves.
 */
const FocusVignette: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const acc = safeAccent(accent);
  const text = cap(overlay.text);
  if (!text) return null;
  const kicker = clip(cap(overlay.label), 32);
  const marks = markSet(overlay.highlight, text);
  const close = ramp(frame, 0, Math.round(fps * 0.9), inOut) * (1 - ramp(frame, D - 13, 12, inOut));
  const breathe = Math.sin((frame / fps) * 1.7) * 1.6 * close;
  const inner = 74 - 42 * close + breathe;
  const outer = inner + 30;
  const dark = `radial-gradient(ellipse 70% 76% at 50% 50%, rgba(0,0,0,0) ${inner.toFixed(2)}%, ` +
    `rgba(0,0,0,${(0.62 * close).toFixed(3)}) ${(inner + 14).toFixed(2)}%, ` +
    `rgba(0,0,0,${(0.93 * close).toFixed(3)}) ${outer.toFixed(2)}%)`;
  const edge = `radial-gradient(ellipse 70% 76% at 50% 50%, rgba(0,0,0,0) ${(inner - 4).toFixed(2)}%, ` +
    `#000 ${(outer - 6).toFixed(2)}%)`;
  const blur = `blur(${(7 * k * close).toFixed(2)}px)`;
  const ls = wrap(text, 24, 2);
  const size = (ls.length > 1 ? 54 : 60) * k;
  const at0 = Math.round(fps * 0.35);
  const landed = at0 + (ls.length - 1) * 6 + 18;
  const rule = ramp(frame, landed, 16, inOut) * (1 - ramp(frame, D - 14, 10, expoIn));
  return (
    <AbsoluteFill>
      {close > 0.01 ? (
        <AbsoluteFill style={{ backdropFilter: blur, WebkitBackdropFilter: blur, maskImage: edge, WebkitMaskImage: edge }} />
      ) : null}
      <AbsoluteFill style={{ background: dark }} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", maxWidth: 1500 * k,
          textShadow: "0 4px 30px rgba(0,0,0,.7)" }}>
          {kicker ? (
            <Letters text={kicker} at={at0 - 4} spread={10} order="center" style={{ fontFamily: LABEL, fontWeight: 800,
              fontSize: 24 * k, letterSpacing: "0.42em", paddingLeft: "0.42em", color: acc, marginBottom: 14 * k }} />
          ) : null}
          {ls.map((ln, i) => (
            <Letters key={i} text={ln} at={at0 + i * 6} spread={16} rise={14} hot={hotLetters(ln, marks)} hotColor={acc}
              hotAt={landed - 4} glow={14 * k} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: size,
                lineHeight: 1.06, letterSpacing: "0.06em", paddingLeft: "0.06em", color: "#fff" }} />
          ))}
          <div style={{ width: 150 * k, height: 3 * k, marginTop: 18 * k, background: acc,
            transform: `scaleX(${rule.toFixed(3)})`, boxShadow: `0 0 ${(10 * k).toFixed(1)}px ${alpha(acc, 0.55)}` }} />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 6. spotlight sweep title
const LAMP_ON = [0, 0.55, 0.15, 0.8, 0.45, 1];
const LAMP_OFF = [1, 0.3, 0.85, 0.2, 0.6, 0.08, 0.35, 0];

/**
 * A dark stage and a lamp hanging above the frame. It strikes on with a
 * flicker, its beam sweeps the stage left to right and every letter of the
 * title rises as the light finds it; the beam swings back, settles on the
 * title and opens to light all of it, dust turning in the cone. At the end the
 * lamp cuts out with a flicker and the letters leave.
 */
const SpotlightTitle: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width: W, height: H, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const bg = useBackdrop(overlay);
  const acc = safeAccent(accent);
  const title = cap(overlay.text);
  if (!title) return null;
  const kicker = clip(cap(overlay.label), 30);
  const sub = clip(cap(overlay.subtitle), 44);
  const ls = wrap(title, 18, 2);
  const size = (ls.length > 1 ? 76 : 86) * k;
  const offAt = D - 14;
  const fi = Math.max(0, Math.floor(frame));
  const lamp = fi >= offAt ? LAMP_OFF[Math.min(LAMP_OFF.length - 1, fi - offAt)]
    : fi < LAMP_ON.length ? LAMP_ON[fi] : 1;
  // The pivot: the pool crosses the stage (8% -> 88%), swings back and settles under the title (50%).
  const a1 = 3;
  const s1 = Math.round(fps * 1.05);
  const s2 = Math.round(fps * 0.85);
  const settle = span(frame, a1 + s1, a1 + s1 + s2, softOut);
  const sway = Math.sin(((frame - a1 - s1 - s2) / fps) * 0.9) * 0.012 * settle;
  const txAt = (fr: number): number => W * (0.08 + 0.8 * span(fr, a1, a1 + s1, inOut));
  const tx = txAt(frame) - W * (0.38 * settle - sway);
  const sx = W * 0.5;
  const sy = -H * 0.3;
  const fy = H * 0.9;
  const titleH = ls.length * size * 1.1;
  const ty = H * 0.5 - 10 * k;
  const titleTop = ty - titleH / 2;
  const f = (y: number): number => (y - sy) / (fy - sy);
  const w0 = 24 * k;
  const w1 = (470 + 400 * settle) * k;
  const beamX = (y: number, x: number): number => sx + (x - sx) * f(y);
  const beamW = (y: number, wide: number): number => w0 + (wide - w0) * f(y);
  // Each letter rises on the frame the sweeping beam's leading edge first reaches it.
  const edgeT = beamW(ty, 470 * k) * 0.5;
  const firstLit = (x: number): number => {
    for (let fr = a1; fr <= a1 + s1; fr++) if (beamX(ty, txAt(fr)) + edgeT >= x) return fr;
    return a1 + s1;
  };
  const adv = 0.43; // Bebas Neue advance per capital incl. tracking, in em (estimate)
  const lineStarts: number[][] = ls.map((ln) => {
    const chars = Array.from(ln);
    const lw = chars.length * adv * size;
    return chars.map((_, i) => firstLit(W / 2 - lw / 2 + (i + 0.5) * adv * size));
  });
  const litX = beamX(ty, tx);
  const litR = beamW(ty, w1) * 1.15;
  const mask = `radial-gradient(ellipse ${litR.toFixed(1)}px ${(230 * k).toFixed(1)}px at ${litX.toFixed(1)}px ` +
    `${ty.toFixed(1)}px, #000 30%, rgba(0,0,0,.35) 70%, rgba(0,0,0,0) 100%)`;
  const late = a1 + s1 + Math.round(s2 * 0.4);
  const id = `cnsp${overlay.startFrame}`;
  const cone = `M${(sx - w0).toFixed(1)} ${sy.toFixed(1)} L${(sx + w0).toFixed(1)} ${sy.toFixed(1)} ` +
    `L${(tx + w1).toFixed(1)} ${fy.toFixed(1)} L${(tx - w1).toFixed(1)} ${fy.toFixed(1)} Z`;
  const t = frame / fps;
  const motes = Array.from({ length: 22 }, (_, i) => {
    const v = 0.14 + ((rnd(i * 7 + 3) * 0.8 + t * (0.012 + rnd(i * 5 + 1) * 0.02)) % 0.8);
    const u = (rnd(i * 11 + 5) * 2 - 1) * 0.85 + Math.sin(t * (0.6 + rnd(i * 3 + 2) * 0.8) + i) * 0.05;
    const y = sy + (fy - sy) * v;
    const x = beamX(y, tx) + u * beamW(y, w1);
    const tw = 0.4 + 0.6 * Math.abs(Math.sin(t * (1 + rnd(i * 13 + 4) * 2) + i * 1.7));
    return <circle key={i} cx={x} cy={y} r={(1.1 + rnd(i * 17 + 6) * 2.2) * k} fill="#fff6e6" opacity={0.55 * tw} />;
  });
  const block = (lit: boolean) => (
    <div style={{ position: "absolute", left: 0, right: 0, top: titleTop, display: "flex", flexDirection: "column",
      alignItems: "center" }}>
      {ls.map((ln, i) => (
        <Letters key={i} text={ln} at={0} starts={lineStarts[i]} rise={16} style={{ fontFamily: DISPLAY, fontSize: size,
          lineHeight: 1, letterSpacing: "0.04em", paddingLeft: "0.04em", color: lit ? "#fff8ec" : "rgba(255,255,255,.075)",
          textShadow: lit ? `0 0 ${(24 * k).toFixed(1)}px rgba(255,236,200,.35)` : undefined }} />
      ))}
    </div>
  );
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${hold})` }}>
        <AbsoluteFill style={{ opacity: bg }}>
          <AbsoluteFill style={{ background: "linear-gradient(180deg, #050506 0%, #09090b 58%, #0e0e11 71%, #060607 100%)" }} />
          <div style={{ position: "absolute", left: 0, right: 0, top: H * 0.71, height: 1.5 * k,
            background: "linear-gradient(90deg, rgba(255,255,255,0), rgba(255,255,255,.07), rgba(255,255,255,0))" }} />
          <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, opacity: lamp }}>
            <defs>
              <linearGradient id={`${id}g`} gradientUnits="userSpaceOnUse" x1={sx} y1={sy} x2={tx} y2={fy}>
                <stop offset="0%" stopColor="#fff4dc" stopOpacity={0.42} />
                <stop offset="55%" stopColor="#fff4dc" stopOpacity={0.13} />
                <stop offset="100%" stopColor="#fff4dc" stopOpacity={0.05} />
              </linearGradient>
              <radialGradient id={`${id}p`}>
                <stop offset="0%" stopColor="#fff2d8" stopOpacity={0.36} />
                <stop offset="100%" stopColor="#fff2d8" stopOpacity={0} />
              </radialGradient>
              <clipPath id={`${id}c`}><path d={cone} /></clipPath>
            </defs>
            <ellipse cx={tx} cy={fy} rx={w1 * 1.08} ry={70 * k} fill={`url(#${id}p)`} />
            <path d={cone} fill={`url(#${id}g)`} style={{ filter: `blur(${(14 * k).toFixed(1)}px)` }} />
            <g clipPath={`url(#${id}c)`}>{motes}</g>
          </svg>
          <AbsoluteFill style={{ opacity: lamp * 0.9, background: `radial-gradient(ellipse ${(litR * 1.6).toFixed(1)}px ` +
            `${(260 * k).toFixed(1)}px at ${litX.toFixed(1)}px ${ty.toFixed(1)}px, rgba(255,240,215,.06) 0%, ` +
            "rgba(255,240,215,0) 100%)" }} />
          <AbsoluteFill style={{ boxShadow: `inset 0 0 ${(300 * k).toFixed(1)}px rgba(0,0,0,.85)` }} />
        </AbsoluteFill>
        {block(false)}
        <AbsoluteFill style={{ maskImage: mask, WebkitMaskImage: mask, opacity: lamp }}>{block(true)}</AbsoluteFill>
        {kicker ? (
          <div style={{ position: "absolute", left: 0, right: 0, top: titleTop - 58 * k, display: "flex",
            justifyContent: "center", opacity: lamp }}>
            <Letters text={kicker} at={late} spread={10} order="center" style={{ fontFamily: LABEL, fontWeight: 800,
              fontSize: 26 * k, letterSpacing: "0.4em", paddingLeft: "0.4em", color: acc }} />
          </div>
        ) : null}
        {sub ? (
          <div style={{ position: "absolute", left: 0, right: 0, top: titleTop + titleH + 26 * k, display: "flex",
            justifyContent: "center", opacity: lamp }}>
            <Letters text={sub} at={late + 6} spread={12} order="center" style={{ fontFamily: LABEL, fontWeight: 600,
              fontSize: 28 * k, letterSpacing: "0.3em", paddingLeft: "0.3em", color: "rgba(255,255,255,.72)" }} />
          </div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 7. slow drift quote
/** Light dust at several depths: near motes bigger, brighter and faster, all rising and swaying. */
const Motes: React.FC<{ n: number; seed: number; accent: string }> = ({ n, seed, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width: W, height: H } = useVideoConfig();
  const k = W / 1920;
  const t = frame / fps;
  const M = H + 120 * k;
  return (
    <>
      {Array.from({ length: n }, (_, i) => {
        const d = rnd(seed + i * 7);
        const size = (1.4 + d * d * 5.5) * k;
        const speed = (6 + d * 30) * k;
        const x = rnd(seed + i * 13) * W + Math.sin(t * (0.25 + rnd(seed + i * 17) * 0.4) + i * 2.1) * (8 + d * 26) * k;
        const y0 = rnd(seed + i * 29) * M;
        const y = ((((y0 - speed * t) % M) + M) % M) - 60 * k;
        const tw = 0.35 + 0.65 * (0.5 + 0.5 * Math.sin(t * (0.7 + rnd(seed + i * 31) * 1.5) + i * 1.3));
        const col = rnd(seed + i * 37) > 0.84 ? accent : "#fff3e2";
        return (
          <div key={i} style={{ position: "absolute", left: x - size / 2, top: y - size / 2, width: size, height: size,
            borderRadius: "50%", background: col, opacity: tw * (0.18 + 0.62 * d),
            boxShadow: d > 0.7 ? `0 0 ${(size * 2.6).toFixed(1)}px ${alpha(col, 0.55)}` : undefined }} />
        );
      })}
    </>
  );
};

/**
 * A quote alone on near-black: its words rise one after another at a slow,
 * even pace, the whole block drifting up and pushing in by a few pixels while
 * dust motes float past at several depths and two soft lights wander behind.
 * The speaker (label) rises between accent hairlines, the source beneath.
 */
const DriftQuote: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const bg = useBackdrop(overlay);
  const ex = useExit(13, 10);
  const acc = safeAccent(accent);
  const quote = str(overlay.text).replace(/^["“”'‘’«»]+|["“”'‘’«»]+$/g, "").trim();
  if (!quote) return null;
  const who = clip(cap(overlay.label), 40);
  const sub = clip(cap(overlay.subtitle), 52);
  const marks = markSet(overlay.highlight, quote);
  const ls = wrap(quote, quote.length > 120 ? 44 : 36, 4);
  const size = (ls.length > 3 ? 50 : ls.length > 2 ? 56 : 62) * k;
  const counts = ls.map((l) => l.split(" ").filter(Boolean).length);
  const total = counts.reduce((a, b) => a + b, 0);
  const step = Math.max(1.5, Math.min(4, (fps * 1.6) / Math.max(1, total)));
  const at0 = Math.round(fps * 0.4);
  const lineAt = (i: number): number => at0 + counts.slice(0, i).reduce((a, b) => a + b, 0) * step;
  const doneAt = lineAt(ls.length);
  const pr = interpolate(frame, [0, Math.max(1, D)], [0, 1], clamp);
  const t = frame / fps;
  const rule = ramp(frame, doneAt + 4, 16) * (1 - ex);
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{ opacity: bg }}>
        <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 55%, #121318 0%, #09090c 55%, #040405 100%)" }} />
        <AbsoluteFill style={{ background: `radial-gradient(circle ${(520 * k).toFixed(1)}px at ` +
          `${(30 + Math.sin(t * 0.21) * 8).toFixed(2)}% ${(34 + Math.cos(t * 0.17) * 6).toFixed(2)}%, ` +
          "rgba(255,240,214,.06) 0%, rgba(255,240,214,0) 100%)" }} />
        <AbsoluteFill style={{ background: `radial-gradient(circle ${(460 * k).toFixed(1)}px at ` +
          `${(72 + Math.cos(t * 0.19) * 7).toFixed(2)}% ${(68 + Math.sin(t * 0.23) * 6).toFixed(2)}%, ` +
          `${alpha(acc, 0.07)} 0%, ${alpha(acc, 0)} 100%)` }} />
        <Motes n={38} seed={seedOf(quote)} accent={acc} />
        <AbsoluteFill style={{ boxShadow: `inset 0 0 ${(320 * k).toFixed(1)}px rgba(0,0,0,.85)` }} />
      </AbsoluteFill>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", maxWidth: 1400 * k, textAlign: "center",
          transform: `translate(${(Math.sin(t * 0.35) * 6 * k).toFixed(2)}px, ${((14 - 28 * pr) * k).toFixed(2)}px) ` +
            `scale(${(1 + 0.03 * pr).toFixed(4)})`, textShadow: "0 6px 30px rgba(0,0,0,.6)" }}>
          {ls.map((ln, i) => (
            <Words key={i} text={ln} at={lineAt(i)} step={step} rise={22} marks={marks} hotColor={acc}
              lead={i === 0 ? "“" : undefined} tail={i === ls.length - 1 ? "”" : undefined} markColor={acc}
              style={{ fontFamily: LABEL, fontWeight: 600, fontSize: size, lineHeight: 1.2, color: "#f3f3f3" }} />
          ))}
          {who ? (
            <div style={{ display: "flex", alignItems: "center", gap: 18 * k, marginTop: 34 * k }}>
              <div style={{ width: 44 * k, height: 2 * k, background: acc, transform: `scaleX(${rule.toFixed(3)})`,
                transformOrigin: "100% 50%" }} />
              <Letters text={who} at={doneAt + 6} spread={12} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 28 * k,
                letterSpacing: "0.26em", paddingLeft: "0.26em", color: acc }} />
              <div style={{ width: 44 * k, height: 2 * k, background: acc, transform: `scaleX(${rule.toFixed(3)})`,
                transformOrigin: "0% 50%" }} />
            </div>
          ) : null}
          {sub ? (
            <Letters text={sub} at={doneAt + 12} spread={12} order="center" style={{ marginTop: 10 * k, fontFamily: LABEL,
              fontWeight: 600, fontSize: 24 * k, letterSpacing: "0.22em", paddingLeft: "0.22em",
              color: "rgba(255,255,255,.5)" }} />
          ) : null}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 8. to be continued
/** Bebas Neue caps advance (em, estimated) of one character. */
const advOf = (c: string): number =>
  c === " " ? 0.18 : /[IJ1.,:;!'’|]/.test(c) ? 0.2 : /[MW]/.test(c) ? 0.54 : /[EFLTZ]/.test(c) ? 0.34 : 0.39;
/** Estimated width (em) of a line of Bebas Neue caps with `track` em of tracking per letter. */
const capsWidth = (text: string, track: number): number =>
  Array.from(text).reduce((w, c) => w + advOf(c) + track, 0);

/** How far past the top and bottom frame edges the chevron wipe reaches (px). */
const OVER = 12;
/** SVG points of a right-pointing chevron band over a frame H tall: its tail notch at x - B, its tip P ahead of x. */
const chevronPts = (x: number, B: number, P: number, H: number): string => {
  const pts: Pt[] = [[x - B, -OVER], [x, -OVER], [x + P, H / 2], [x, H + OVER], [x - B, H + OVER], [x - B + P, H / 2]];
  return pts.map(([a, b]) => `${a.toFixed(1)},${b.toFixed(1)}`).join(" ");
};
/** CSS clip of the frame behind (left of) a chevron band's tail, or still ahead of (right of) it. */
const tailClip = (x: number, B: number, P: number, W: number, H: number, side: "behind" | "ahead"): string => {
  const t = x - B;
  const pts: Pt[] = side === "behind"
    ? [[-20, -OVER], [t, -OVER], [t + P, H / 2], [t, H + OVER], [-20, H + OVER]]
    : [[t, -OVER], [W + 20, -OVER], [W + 20, H + OVER], [t, H + OVER], [t + P, H / 2]];
  return `polygon(${pts.map(([a, b]) => `${a.toFixed(1)}px ${b.toFixed(1)}px`).join(", ")})`;
};

/**
 * The end card. A thin white chevron leads a thick accent one across the
 * frame and the card is uncovered in their wake (over footage it is a real
 * wipe). An arrow plate draws on round the words, its solid accent tip snaps
 * in, a sheen crosses it, three chevrons pulse onward beside it; the kicker
 * (label) above, the next title (subtitle) below. At the end the same pair of
 * chevrons crosses again and takes the card away.
 */
const ToBeContinued: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width: W, height: H, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const acc = safeAccent(accent);
  const title = cap(overlay.text) || "TO BE CONTINUED";
  const kicker = clip(cap(overlay.label), 36);
  const sub = clip(cap(overlay.subtitle), 48);
  const ls = wrap(title, 22, 2);
  const size = (ls.length > 1 ? 64 : 80) * k;
  const TRACK = 0.08;
  const textW = Math.max(0, ...ls.map((l) => capsWidth(l, TRACK))) * size;
  const padX = 50 * k;
  const plateH = ls.length * size * 1.02 + 52 * k;
  const h2 = plateH / 2;
  const plateW = Math.min(1300 * k, textW + padX * 2 + h2 * 0.85);
  const body = plateW - h2;
  const sw = 3 * k;
  const id = `cntbc${overlay.startFrame}`;
  // The arrow wipe.
  const P = 0.3 * H;
  const BA = 300 * k;
  const BW = 26 * k;
  const pos = (p: number, B: number): number => -P - 30 * k + p * (W + B + P + 60 * k);
  const inW = span(frame, 0, 15, inOut);
  const inA = span(frame, 2, 19, inOut);
  const outW = span(frame, D - 16, D - 5, inOut);
  const outA = span(frame, D - 14, D - 2, inOut);
  const card = frame >= D - 14 ? tailClip(pos(outA, BA), BA, P, W, H, "ahead")
    : inA < 1 ? tailClip(pos(inA, BA), BA, P, W, H, "behind") : undefined;
  const bands: { x: number; B: number; fill: string }[] = [];
  if (inA > 0 && inA < 1) bands.push({ x: pos(inA, BA), B: BA, fill: acc });
  if (inW > 0 && inW < 1) bands.push({ x: pos(inW, BW), B: BW, fill: "#ffffff" });
  if (outA > 0 && outA < 1) bands.push({ x: pos(outA, BA), B: BA, fill: acc });
  if (outW > 0 && outW < 1) bands.push({ x: pos(outW, BW), B: BW, fill: "#ffffff" });
  // The card.
  const titleAt = 12;
  const draw = ramp(frame, 8, Math.round(fps * 0.7), inOut);
  const tipPop = ramp(frame, 8 + Math.round(fps * 0.55), 12, backOut);
  const sheenAt = Math.round(fps * 1.3);
  const sheen = interpolate(frame, [sheenAt, sheenAt + Math.max(1, Math.round(fps * 0.8))],
    [-140 * k, plateW + 80 * k], { ...clamp, easing: inOut });
  const stripe = (frame * 1.2 * k) % (48 * k);
  const platePath = `M${(sw / 2).toFixed(1)} ${(sw / 2).toFixed(1)} H${body.toFixed(1)} ` +
    `L${(plateW - sw).toFixed(1)} ${h2.toFixed(1)} L${body.toFixed(1)} ${(plateH - sw / 2).toFixed(1)} ` +
    `H${(sw / 2).toFixed(1)} Z`;
  const tipPts = `${body.toFixed(1)},${(sw / 2).toFixed(1)} ${(plateW - sw).toFixed(1)},${h2.toFixed(1)} ` +
    `${body.toFixed(1)},${(plateH - sw / 2).toFixed(1)}`;
  const chevH = Math.max(36 * k, plateH * 0.42);
  const chevW = chevH * 0.52;
  const chevAt = titleAt + 14;
  const period = Math.max(12, Math.round(fps * 0.9));
  const phase = frame < chevAt ? -1 : ((frame - chevAt) % period) / period;
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{ clipPath: card, WebkitClipPath: card }}>
        <AbsoluteFill style={{ background:
          "radial-gradient(ellipse 85% 75% at 42% 50%, #17181c 0%, #0c0c0f 55%, #050506 100%)" }} />
        <AbsoluteFill style={{ background:
          `radial-gradient(ellipse 36% 44% at 80% 50%, ${alpha(acc, 0.12)} 0%, ${alpha(acc, 0)} 100%)` }} />
        <AbsoluteFill style={{ backgroundImage: `repeating-linear-gradient(115deg, rgba(255,255,255,.03) ` +
          `${stripe.toFixed(1)}px, rgba(255,255,255,.03) ${(stripe + 2 * k).toFixed(1)}px, rgba(255,255,255,0) ` +
          `${(stripe + 2 * k).toFixed(1)}px, rgba(255,255,255,0) ${(stripe + 48 * k).toFixed(1)}px)` }} />
        <AbsoluteFill style={{ boxShadow: `inset 0 0 ${(300 * k).toFixed(1)}px rgba(0,0,0,.82)` }} />
        <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
            {kicker ? (
              <Letters text={kicker} at={16} spread={12} order="center" style={{ fontFamily: LABEL, fontWeight: 800,
                fontSize: 26 * k, letterSpacing: "0.42em", paddingLeft: "0.42em", color: acc, marginBottom: 26 * k }} />
            ) : null}
            <div style={{ display: "flex", alignItems: "center", gap: 34 * k }}>
              <div style={{ position: "relative", width: plateW, height: plateH }}>
                <svg width={plateW} height={plateH} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
                  <defs>
                    <linearGradient id={`${id}f`} x1="0" y1="0" x2="1" y2="0">
                      <stop offset="0%" stopColor={acc} stopOpacity={0.03} />
                      <stop offset="100%" stopColor={acc} stopOpacity={0.22} />
                    </linearGradient>
                    <linearGradient id={`${id}s`} x1="0" y1="0" x2="1" y2="0">
                      <stop offset="0%" stopColor="#ffffff" stopOpacity={0} />
                      <stop offset="50%" stopColor="#ffffff" stopOpacity={0.22} />
                      <stop offset="100%" stopColor="#ffffff" stopOpacity={0} />
                    </linearGradient>
                    <clipPath id={`${id}c`}><path d={platePath} /></clipPath>
                  </defs>
                  <path d={platePath} fill={`url(#${id}f)`} opacity={draw} />
                  <polygon points={tipPts} fill={acc} transform={`translate(${body.toFixed(1)} ${h2.toFixed(1)}) ` +
                    `scale(${Math.max(0, tipPop).toFixed(3)}) translate(${(-body).toFixed(1)} ${(-h2).toFixed(1)})`} />
                  <g clipPath={`url(#${id}c)`}>
                    <rect x={sheen} y={-20 * k} width={90 * k} height={plateH + 40 * k} fill={`url(#${id}s)`}
                      transform="skewX(-18)" />
                  </g>
                  <path d={platePath} fill="none" stroke="#ffffff" strokeOpacity={0.92} strokeWidth={sw}
                    strokeLinejoin="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - draw} />
                </svg>
                <div style={{ position: "absolute", left: padX, top: 0, bottom: 0, display: "flex", flexDirection: "column",
                  justifyContent: "center" }}>
                  {ls.map((ln, i) => (
                    <Letters key={i} text={ln} at={titleAt + i * 5} spread={12} rise={14} style={{ fontFamily: DISPLAY,
                      fontSize: size, lineHeight: 1.02, letterSpacing: `${TRACK}em`, color: "#fff" }} />
                  ))}
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 10 * k }}>
                {[0, 1, 2].map((i) => {
                  const pop = ramp(frame, chevAt + i * 3, 12, backOut);
                  const bump = phase < 0 ? 0 : Math.max(0, 1 - Math.abs(phase * 4 - (i + 0.5)));
                  return (
                    <svg key={i} width={chevW} height={chevH} style={{ overflow: "visible",
                      opacity: Math.min(1, Math.max(0, pop)) * (0.32 + 0.68 * bump),
                      transform: `translateX(${(bump * 8 * k).toFixed(2)}px) scale(${Math.max(0, pop).toFixed(3)})` }}>
                      <path d={`M${(4 * k).toFixed(1)} ${(4 * k).toFixed(1)} L${(chevW - 4 * k).toFixed(1)} ` +
                        `${(chevH / 2).toFixed(1)} L${(4 * k).toFixed(1)} ${(chevH - 4 * k).toFixed(1)}`}
                        fill="none" stroke={acc} strokeWidth={6 * k} strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  );
                })}
              </div>
            </div>
            {sub ? (
              <Letters text={sub} at={22} spread={12} order="center" style={{ fontFamily: LABEL, fontWeight: 600,
                fontSize: 30 * k, letterSpacing: "0.2em", paddingLeft: "0.2em", color: "rgba(255,255,255,.72)",
                marginTop: 30 * k }} />
            ) : null}
          </div>
        </AbsoluteFill>
      </AbsoluteFill>
      {bands.length ? (
        <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
          {bands.map((b, i) => <polygon key={i} points={chevronPts(b.x, b.B, P, H)} fill={b.fill} />)}
        </svg>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== 9. sources roll
/**
 * End credits of the sources on near-black: a centred heading with an accent
 * rule, then rows rolling up through a soft window - what was used (item
 * text) on the left, who it came from (item label) on the right, the reference
 * number in the gutter lighting up in the accent as its row passes the reading
 * line. A short list rises into place and drifts; a long one rolls through.
 * At the end every row rises out of its own mask.
 */
const SourcesRoll: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, height: H, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const bg = useBackdrop(overlay);
  const ex = useExit(14, 10);
  const acc = safeAccent(accent);
  const src: OverlayItem[] = Array.isArray(overlay.items) ? overlay.items : [];
  const rows = src.filter((it) => Boolean(it && str(it.label))).slice(0, 10);
  if (!rows.length) return null;
  const title = clip(cap(overlay.text), 24) || "SOURCES";
  const sub = clip(cap(overlay.subtitle), 60);
  const twoCol = rows.some((r) => Boolean(str(r.text)));
  const ROW = 80 * k;
  const TOP = 292 * k;
  const WH = Math.max(ROW * 3, H - 112 * k - TOP);
  const FE = 64 * k;
  const listH = rows.length * ROW;
  const fits = listH <= WH - FE * 2;
  const rollAt = 12;
  let y: number;
  if (fits) {
    const p = ramp(frame, rollAt, Math.round(fps * 1.1), softOut);
    const rest = (WH - listH) / 2;
    y = WH + (rest - WH) * p - interpolate(frame, [rollAt, Math.max(rollAt + 1, D)], [0, 16 * k], clamp);
  } else {
    const p = span(frame, rollAt, D - 20, rollEase);
    const from = WH - FE * 0.5;
    const to = WH - FE - listH;
    y = from + (to - from) * p;
  }
  const win = `linear-gradient(180deg, rgba(0,0,0,0) 0px, #000 ${FE.toFixed(1)}px, #000 ${(WH - FE).toFixed(1)}px, ` +
    `rgba(0,0,0,0) ${WH.toFixed(1)}px)`;
  const rule = ramp(frame, 8, 18, inOut) * (1 - ex);
  const LEFT = 620 * k;
  const GUT = 124 * k;
  const RIGHT = 620 * k;
  const nameStyle = (focus: number): React.CSSProperties => ({ fontFamily: LABEL, fontWeight: 700, fontSize: 36 * k,
    letterSpacing: "0.06em", color: mix("#b9bac2", "#ffffff", focus), whiteSpace: "nowrap" });
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{ opacity: bg }}>
        <AbsoluteFill style={{ background:
          "radial-gradient(ellipse 90% 80% at 50% 40%, #131417 0%, #09090b 60%, #040405 100%)" }} />
        <AbsoluteFill style={{ background:
          `radial-gradient(ellipse 42% 28% at 50% 0%, ${alpha(acc, 0.1)} 0%, ${alpha(acc, 0)} 100%)` }} />
        <Grain id={`cnsr${overlay.startFrame}`} opacity={0.06} />
        <AbsoluteFill style={{ boxShadow: `inset 0 0 ${(300 * k).toFixed(1)}px rgba(0,0,0,.85)` }} />
      </AbsoluteFill>
      <div style={{ position: "absolute", left: 0, right: 0, top: 104 * k, display: "flex", flexDirection: "column",
        alignItems: "center" }}>
        <Letters text={title} at={2} spread={12} order="center" style={{ fontFamily: DISPLAY, fontSize: 62 * k,
          lineHeight: 1, letterSpacing: "0.3em", paddingLeft: "0.3em", color: "#fff" }} />
        <div style={{ width: 120 * k, height: 3 * k, marginTop: 14 * k, background: acc,
          transform: `scaleX(${rule.toFixed(3)})`, boxShadow: `0 0 ${(10 * k).toFixed(1)}px ${alpha(acc, 0.5)}` }} />
        {sub ? (
          <Letters text={sub} at={10} spread={14} order="center" style={{ marginTop: 14 * k, fontFamily: LABEL,
            fontWeight: 600, fontSize: 24 * k, letterSpacing: "0.24em", paddingLeft: "0.24em",
            color: "rgba(255,255,255,.5)" }} />
        ) : null}
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: TOP, height: WH, overflow: "hidden",
        maskImage: win, WebkitMaskImage: win }}>
        <div style={{ position: "absolute", left: 0, right: 0, top: y }}>
          {rows.map((r, i) => {
            const cy = y + (i + 0.5) * ROW;
            const focus = Math.max(0, 1 - Math.abs(cy - WH / 2) / (WH * 0.42));
            const out = ramp(frame, D - 14 + Math.min(5, i * 0.6), 9, expoIn);
            const role = clip(cap(r.text), 34);
            const name = clip(cap(r.label), 30);
            const idx = (
              <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.08em",
                color: mix("#6f7079", acc, focus) }}>{pad2(i + 1)}</span>
            );
            return (
              <div key={i} style={{ height: ROW, overflow: "hidden", display: "flex", alignItems: "center",
                justifyContent: "center" }}>
                <div style={{ display: "flex", alignItems: "center", transform: `translateY(${(-out * ROW).toFixed(1)}px)` }}>
                  {twoCol ? (
                    <>
                      <div style={{ width: LEFT, textAlign: "right", fontFamily: LABEL, fontWeight: 600, fontSize: 26 * k,
                        letterSpacing: "0.2em", color: "rgba(255,255,255,.5)", whiteSpace: "nowrap" }}>{role}</div>
                      <div style={{ width: GUT, textAlign: "center" }}>{idx}</div>
                      <div style={{ width: RIGHT, textAlign: "left", ...nameStyle(focus) }}>{name}</div>
                    </>
                  ) : (
                    <>
                      <div style={{ marginRight: 28 * k }}>{idx}</div>
                      <div style={nameStyle(focus)}>{name}</div>
                    </>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 10. chapter progress
/**
 * A thin chapter scrubber across the top of the footage: the segments (total)
 * draw in left to right, the finished chapters fill white one after another,
 * the current one (value) lifts with a glow and fills in the accent behind a
 * pulsing playhead. A hairline drops from it to the label: the chapter number
 * rolling in, "/06" in mono, the kicker (label) and the chapter title (text).
 * More than 12 chapters become one continuous track; without a total the
 * whole track is this chapter, its playhead running across it.
 */
const ChapterProgress: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width: W, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const shade = useShade();
  const ex = useExit(14, 10);
  const acc = safeAccent(accent);
  const v = finite(overlay.value);
  const cur = v === null ? NaN : Math.round(v);
  if (!Number.isFinite(cur) || cur < 1 || cur > 99) return null;
  const tv = finite(overlay.total);
  const tot = tv === null ? NaN : Math.round(tv);
  const hasTot = Number.isFinite(tot) && tot >= Math.max(2, cur) && tot <= 99;
  const n = hasTot && tot <= 12 ? tot : 1;
  const title = clip(cap(overlay.text), 34);
  const kicker = clip(cap(overlay.label), 20) || "CHAPTER";
  const L = 110 * k;
  const TW = W - 220 * k;
  const TOP = 92 * k;
  const G = n > 1 ? 8 * k : 0;
  const segW = (TW - (n - 1) * G) / n;
  const ci = n > 1 ? cur - 1 : 0;
  // Where the current chapter sits on the track (px from its left end) and how long it is.
  const curX = n > 1 ? ci * (segW + G) : hasTot ? ((cur - 1) / tot) * TW : 0;
  const curW = n > 1 ? segW : hasTot ? TW / tot : TW;
  const drawStep = Math.min(2, 12 / n);
  const liftAt = 4 + (n - 1) * drawStep + 6;
  const fillAt = liftAt + 4;
  const fillIn = Math.round(fps * 0.8);
  const fill = hasTot
    ? 0.5 * ramp(frame, fillAt, fillIn, inOut) + 0.14 * span(frame, fillAt + fillIn, D - 14)
    : span(frame, fillAt, D - 14);
  const lift = ramp(frame, liftAt, 12, backOut) * (1 - ex);
  const doneAt = (i: number): number => 8 + i * drawStep;
  const pulse = 0.65 + 0.35 * Math.sin((frame / fps) * Math.PI * 1.6);
  const headX = curX + curW * fill;
  const head = Math.min(1, Math.max(0, ramp(frame, fillAt, 8) * (1 - ex)));
  // The label hangs under the current chapter, kept inside the safe area.
  const numSize = 60 * k;
  const textW = Math.max(Array.from(kicker).length * 0.74 * 24, Array.from(title).length * 0.5 * 36) * k;
  const blockW = numSize * 0.9 + (hasTot ? 70 * k : 0) + 40 * k + textW;
  const blockLeft = Math.max(L, Math.min(L + curX, W - 110 * k - blockW));
  const drop = ramp(frame, liftAt + 2, 12, inOut) * (1 - ex);
  const hair = ramp(frame, liftAt + 4, 14, inOut) * (1 - ex);
  const numAt = liftAt + 2;
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: shade, background:
        "linear-gradient(180deg, rgba(0,0,0,.52) 0%, rgba(0,0,0,.22) 15%, rgba(0,0,0,0) 32%)" }} />
      <div style={{ position: "absolute", left: L, top: TOP, width: TW, height: 12 * k }}>
        {Array.from({ length: n }, (_, i) => {
          const isCur = n === 1 || i === ci;
          const done = n > 1 && i < ci;
          const d = ramp(frame, 4 + i * drawStep, 16, softOut)
            * (1 - ramp(frame, D - 14 + (n - 1 - i) * Math.min(0.6, 4 / n), 9, expoIn));
          const h = (isCur ? 4 + 4 * lift : 4) * k;
          const white = done ? ramp(frame, doneAt(i), 12)
            : n === 1 && hasTot ? ((cur - 1) / tot) * ramp(frame, doneAt(0), 18, inOut) : 0;
          const a0 = n === 1 && hasTot ? (cur - 1) / tot : 0;
          const a1 = isCur ? a0 + (n === 1 && hasTot ? fill / tot : fill) : 0;
          return (
            <div key={i} style={{ position: "absolute", left: i * (segW + G), top: 6 * k - h / 2, width: segW, height: h,
              borderRadius: h / 2, overflow: "hidden", background: "rgba(255,255,255,.26)",
              transform: `scaleX(${Math.max(0, d).toFixed(4)})`, transformOrigin: "0 50%",
              boxShadow: isCur && lift > 0.01 ? `0 0 ${(14 * k * lift).toFixed(1)}px ${alpha(acc, 0.5)}` : undefined }}>
              {white > 0.001 ? (
                <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${(white * 100).toFixed(2)}%`,
                  background: "rgba(255,255,255,.92)" }} />
              ) : null}
              {a1 > a0 + 0.0005 ? (
                <div style={{ position: "absolute", left: `${(a0 * 100).toFixed(2)}%`, top: 0, bottom: 0,
                  width: `${((a1 - a0) * 100).toFixed(2)}%`, background: acc }} />
              ) : null}
            </div>
          );
        })}
        {head > 0.01 ? (
          <div style={{ position: "absolute", left: headX - 8 * k, top: -2 * k, width: 16 * k, height: 16 * k,
            borderRadius: "50%", background: "#fff", border: `${3 * k}px solid ${acc}`, boxSizing: "border-box",
            transform: `scale(${head.toFixed(3)})`,
            boxShadow: `0 0 ${(16 * k * pulse).toFixed(1)}px ${alpha(acc, 0.8)}` }} />
        ) : null}
      </div>
      <div style={{ position: "absolute", left: L + curX, top: TOP + 12 * k, width: 2 * k, height: 20 * k, background: acc,
        transform: `scaleY(${drop.toFixed(3)})`, transformOrigin: "50% 0%" }} />
      <div style={{ position: "absolute", left: blockLeft, top: TOP + 36 * k, display: "flex", alignItems: "center",
        gap: 18 * k, textShadow: "0 3px 14px rgba(0,0,0,.6)" }}>
        <div style={{ display: "flex", alignItems: "flex-start" }}>
          <RollDigits text={pad2(cur)} at={numAt} frames={Math.round(fps * 0.8)} size={numSize} color="#fff"
            outAt={D - 13} />
          {hasTot ? (
            <Letters text={`/${pad2(tot)}`} at={numAt + 8} spread={3} style={{ fontFamily: MONO, fontWeight: 500,
              fontSize: 24 * k, color: "rgba(255,255,255,.55)", marginLeft: 8 * k, marginTop: 4 * k }} />
          ) : null}
        </div>
        <div style={{ width: 2 * k, height: 56 * k, background: "rgba(255,255,255,.35)",
          transform: `scaleY(${hair.toFixed(3)})`, transformOrigin: "50% 0%" }} />
        <div style={{ display: "flex", flexDirection: "column", gap: 2 * k }}>
          <Letters text={kicker} at={numAt + 4} spread={8} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 24 * k,
            lineHeight: 1.1, letterSpacing: "0.3em", color: acc }} />
          {title ? (
            <Letters text={title} at={numAt + 8} spread={12} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 36 * k,
              lineHeight: 1.05, letterSpacing: "0.04em", color: "#fff" }} />
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== registry
/** A look never throws on a missing overlay and always has an accent. */
const safe = (Inner: Look): Look => {
  const Guarded: Look = ({ overlay, accent }) =>
    overlay && typeof overlay === "object"
      ? <Inner overlay={overlay} accent={typeof accent === "string" && accent ? accent : GOLD} />
      : null;
  return Guarded;
};

export const LOOKS: Record<string, Look> = {
  "cn-place-stamp": safe(PlaceStamp),
  "cn-true-events": safe(TrueEvents),
  "cn-letterbox-caption": safe(LetterboxCaption),
  "cn-bw-flash-intro": safe(BwFlashIntro),
  "cn-focus-vignette": safe(FocusVignette),
  "cn-spotlight-title": safe(SpotlightTitle),
  "cn-drift-quote": safe(DriftQuote),
  "cn-to-be-continued": safe(ToBeContinued),
  "cn-sources-roll": safe(SourcesRoll),
  "cn-chapter-progress": safe(ChapterProgress),
};
