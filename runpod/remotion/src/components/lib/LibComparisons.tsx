import React from "react";
import { AbsoluteFill, Easing, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { SafeImg } from "../motion/safePicture";
import { DISPLAY, INTER, LABEL, MONO } from "../fonts";
import type { Overlay, OverlayItem, SceneMedia } from "../../types";
import { LetterLine, Odometer, Scrim, formatValue, lines, ramp, useHold, useK } from "../pro/ProGraphics";
import { Heading } from "../pro/ProCharts";

/**
 * Comparisons (family "cp-"): ten looks that set one thing against another,
 * in the pro house style - condensed caps, one accent, numbers that roll,
 * text rising out of its mask and leaving through it at the end, graphics
 * landing on expo / back-out curves and retracting in the last frames.
 *
 *   cp-split-statement   own backdrop: a graphite half and a paper half slide in
 *                        and lock on a diagonal accent seam, one statement a side
 *                        (items[0] / items[1]: label + text); they part like doors
 *   cp-balance-scale     a balance: weights stack onto two pans, the beam tips
 *                        toward the heavier item value on a damped spring
 *   cp-venn              two rings slide together; the overlap fills with the
 *                        accent like rising water and names what they share
 *                        (text, or highlight; the heading is then text/subtitle)
 *   cp-tick-table        a scored table: rows (items, marks in text "yes|no"),
 *                        columns named in label "A|B"; a scan runs down each
 *                        column popping ticks, the column with most ticks lights
 *   cp-myth-fact         a tri-vision board: the MYTH card (text) turns over slat
 *                        by slat, in a wave, to its paper FACT side (subtitle)
 *   cp-spectrum-marker   a low-to-high spectrum band, a lens marker springs to
 *                        value / total, the zone under it (item labels) lights
 *   cp-quadrant-matrix   a 2x2 matrix: items[0] = x axis name + score, items[1] =
 *                        y axis name + score; the dot (label) flies into its
 *                        quadrant, which floods, and a verdict chip names it
 *   cp-then-now-morph    one disc morphs THEN -> NOW (area to scale, 2-4 items),
 *                        the digits roll straight from one number into the next
 *   cp-mirror-bars       a butterfly chart: groups in label "A|B", each item's
 *                        value grows left and its text (a number) grows right
 *   cp-photo-versus      own backdrop: two photo cards turned toward each other
 *                        in 3D, a V and an S slamming together between them
 *
 * Deterministic (no Math.random / Date); every size is 1080p-referenced times k.
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;
type Row = { label: string; text: string; value: number; suffix: string; prefix: string };
type Mark = 0 | 0.5 | 1;
type Tile = { t: number; col: number; row: number; x: number; y: number; hot: boolean };

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const IN_OUT = Easing.bezier(0.65, 0, 0.35, 1);
const BACK = Easing.bezier(0.34, 1.56, 0.64, 1);
const IN = Easing.bezier(0.7, 0, 0.84, 0);
const FLIP = Easing.bezier(0.6, 0, 0.3, 1.22);
const RED = "#ff3b30";
const GREEN = "#27d17f";
const CYAN = "#53c8ff";
const INK = "#0c0c0f";
const GOLD = "#F2B544";

// ------------------------------------------------------------------ data helpers
/** Any planner field as a clean string (numbers spelled out, anything else ""). */
const str = (v: unknown): string =>
  typeof v === "string" ? v.replace(/\s+/g, " ").trim()
    : typeof v === "number" && Number.isFinite(v) ? String(v) : "";
const cap = (v: unknown): string => str(v).toUpperCase();
const clip = (s: string, n: number): string => (s.length > n ? `${s.slice(0, Math.max(1, n - 1)).trimEnd()}…` : s);
const clamp01 = (v: number): number => (Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : 0);
const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;

/** A number from a number or a numeric string ("27%", "1,234", "−8"); NaN otherwise. */
const toNum = (raw: unknown): number => {
  if (typeof raw === "number") return Number.isFinite(raw) ? raw : NaN;
  if (typeof raw === "string") {
    const m = /-?\d[\d,]*(?:\.\d+)?|-?\.\d+/.exec(raw.replace(/[−–]/g, "-"));
    return m ? Number(m[0].replace(/,/g, "")) : NaN;
  }
  return NaN;
};

/** Every item as a clean row (strings trimmed, value NaN when absent), at most `max`. */
const rowsOf = (items: OverlayItem[] | undefined, max = 6): Row[] => {
  const out: Row[] = [];
  if (!Array.isArray(items)) return out;
  for (const it of items) {
    if (!it || typeof it !== "object") continue;
    const ex = it as unknown as Record<string, unknown>;
    const raw = ex.value;
    out.push({
      label: str(ex.label), text: str(ex.text),
      value: raw === undefined || raw === null || raw === "" ? NaN : toNum(raw),
      suffix: str(ex.suffix), prefix: str(ex.prefix),
    });
    if (out.length >= max) break;
  }
  return out;
};
const textRow = (text: string): Row => ({ label: "", text, value: NaN, suffix: "", prefix: "" });

/** "%" and one-letter units hug the number ("40M"); longer units get a space ("12 MAF"). */
const unitOf = (s: unknown): string => {
  const t = str(s);
  if (!t) return "";
  return t === "%" || t.length === 1 ? t.toUpperCase() : ` ${t.toUpperCase()}`;
};
const fmt = (v: number): string => formatValue(v).text;

/** "A | B", "A vs B", "A versus B" -> names (empty when the field does not split). */
const namesOf = (v: unknown, max = 3): string[] => {
  const s = str(v);
  if (!s) return [];
  const parts = s.split(/\s*\|\s*|\s+(?:vs\.?|versus|v\.)\s+/i).map((p) => p.trim()).filter(Boolean);
  return parts.length >= 2 ? parts.slice(0, max) : [];
};

/** Deterministic 0..1 of a number (never Math.random). */
const seeded = (n: number): number => {
  const x = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
};

/** Word-wrap into at most `max` lines of about `chars`; the last is cut with an ellipsis when it runs over. */
const wrapN = (text: string, chars: number, max: number): string[] => {
  const all = lines(text, chars).map((l) => clip(l, Math.round(chars * 1.3)));
  if (all.length <= max) return all;
  const kept = all.slice(0, max);
  kept[max - 1] = `${kept[max - 1].replace(/[\s,;:.\-–—]+$/, "")}…`;
  return kept;
};

const niceCeil = (v: number): number => {
  if (!(v > 0) || !Number.isFinite(v)) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * p >= v - 1e-9) return m * p;
  return 10 * p;
};

/** The picture of a media entry: an image's url, anything else its thumbnail. */
const stillOf = (m?: SceneMedia | null): string => {
  if (!m || typeof m !== "object") return "";
  const u: unknown = m.type === "image" ? m.url : m.thumbnail;
  return typeof u === "string" ? u.trim() : "";
};
const stills = (ov: Overlay, max: number): string[] => {
  const found: string[] = [];
  for (const m of Array.isArray(ov.media) ? ov.media : []) {
    const s = stillOf(m);
    if (s && found.indexOf(s) < 0) found.push(s);
    if (found.length >= max) break;
  }
  return found;
};

// ------------------------------------------------------------------ colour helpers
const rgbOf = (c: string): [number, number, number] | null => {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec((c || "").trim());
  if (!m) return null;
  const h = m[1].length === 3 ? m[1].split("").map((x) => x + x).join("") : m[1];
  const n = parseInt(h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
/** The accent as #hex (gold when the prop is not a usable hex colour). */
const hexOk = (c: string): string => {
  const s = (typeof c === "string" ? c : "").trim();
  return rgbOf(s) ? (s[0] === "#" ? s : `#${s}`) : GOLD;
};
const alpha = (c: string, a: number): string => {
  const v = rgbOf(c) || [242, 181, 68];
  return `rgba(${v[0]},${v[1]},${v[2]},${clamp01(a).toFixed(3)})`;
};
/** Near-black ink on a light accent (gold, teal, white, amber), white on a dark one (red, blue). */
const inkOn = (c: string): string => {
  const v = rgbOf(c);
  if (!v) return INK;
  const lin = (x: number) => {
    const s = x / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * lin(v[0]) + 0.7152 * lin(v[1]) + 0.0722 * lin(v[2]) > 0.3 ? INK : "#fff";
};

// ------------------------------------------------------------------ timing helpers
/** Seconds to frames, scaled to the overlay length: a 3 s beat builds faster than a 6 s one. */
const useT = () => {
  const { fps, durationInFrames } = useVideoConfig();
  const tempo = Math.max(0.6, Math.min(1.1, durationInFrames / 150));
  return (sec: number) => Math.round(fps * sec * tempo);
};
/** The frame the exits start (text leaves through its masks, graphics retract). */
const useEnd = () => {
  const { durationInFrames } = useVideoConfig();
  return Math.max(24, durationInFrames - 14);
};
/** 0 -> 1 over the exit. */
const useOut = () => {
  const frame = useCurrentFrame();
  const end = useEnd();
  return ramp(frame, end, 11, IN);
};
/** Guard over the very last frames for any residue after the designed exits. */
const useFin = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return 1 - ramp(frame, durationInFrames - 5, 4);
};
/** LetterLine's exit start pulled earlier for long lines, so the last letter is gone by end + 11. */
const outFor = (end: number, len: number): number => end + 2 - Math.min(14, Math.round(0.6 * Math.max(0, len - 1)));

// ------------------------------------------------------------------ text pieces
/** A block that rises out of its mask at `at` and leaves upward through it at the end. */
const Rise: React.FC<{ at: number; frames?: number; delay?: number; children: React.ReactNode; style?: React.CSSProperties }> =
  ({ at, frames = 14, delay = 0, children, style }) => {
    const frame = useCurrentFrame();
    const end = useEnd();
    const pin = ramp(frame, at, frames);
    const pout = ramp(frame, end + delay, 10, IN);
    return (
      <div style={{ overflow: "hidden", paddingBottom: "0.08em", ...style }}>
        <div style={{ transform: `translateY(${((1 - pin) * 115 - pout * 115).toFixed(2)}%)`,
          opacity: pin < 0.01 || pout > 0.99 ? 0 : 1 }}>{children}</div>
      </div>
    );
  };

/** Exit-only mask for pieces that animate their own entrance (Heading, LetterLine, rolling numbers). */
const Exit: React.FC<{ children: React.ReactNode; delay?: number }> = ({ children, delay = 0 }) => {
  const frame = useCurrentFrame();
  const end = useEnd();
  const k = useK();
  const p = ramp(frame, end + delay, 10, IN);
  return (
    <div style={{ overflow: "hidden", padding: `${10 * k}px ${14 * k}px`, margin: `${-10 * k}px ${-14 * k}px` }}>
      <div style={{ transform: `translateY(calc(${(-p * 118).toFixed(2)}% - ${(p * 12 * k).toFixed(2)}px))` }}>{children}</div>
    </div>
  );
};

/** Letters rising in one by one; at the end they drop out and the line leaves through its mask. */
const Line: React.FC<{ text: string; at: number; step?: number; delay?: number; style?: React.CSSProperties }> =
  ({ text, at, step = 0.7, delay = 0, style }) => {
    const end = useEnd();
    if (!text) return null;
    return (
      <Exit delay={delay}>
        <LetterLine text={text} at={at} step={step} outAt={outFor(end + delay, text.length)} style={style} />
      </Exit>
    );
  };

/** The chart heading (letters in, accent bar), leaving through a mask; long ones wrap to two lines. */
const Head: React.FC<{ text?: string; accent: string; size?: number; center?: boolean; at?: number }> =
  ({ text, accent, size = 58, center, at = 0 }) => {
    const frame = useCurrentFrame();
    const k = useK();
    const t = str(text);
    if (!t) return null;
    if (t.length <= 42) return <Exit><Heading text={t} accent={accent} size={size} center={center} at={at} /></Exit>;
    const ls = wrapN(cap(t), 40, 2);
    return (
      <Exit>
        <div style={{ display: "flex", flexDirection: "column", alignItems: center ? "center" : "flex-start", gap: 6 * k }}>
          {ls.map((ln, i) => (
            <LetterLine key={i} text={ln} at={at + i * 4} step={0.5} style={{ fontFamily: DISPLAY, fontSize: size * 0.86 * k,
              color: "#fff", letterSpacing: "0.04em", lineHeight: 1, textAlign: center ? "center" : "left", whiteSpace: "nowrap",
              textShadow: "0 6px 26px rgba(0,0,0,.5)" }} />
          ))}
          <div style={{ width: ramp(frame, at + 6, 16) * 110 * k, height: 5 * k, background: accent, marginTop: 4 * k }} />
        </div>
      </Exit>
    );
  };

const labelCss = (k: number, size: number, color: string, spacing = "0.14em"): React.CSSProperties => ({
  fontFamily: LABEL, fontWeight: 800, fontSize: size * k, letterSpacing: spacing, color, lineHeight: 1.05,
  whiteSpace: "nowrap", textShadow: "0 3px 14px rgba(0,0,0,.45)",
});

/** An accent bar that draws in and retracts at the end. */
const Bar: React.FC<{ at: number; width: number; color: string; thick?: number }> = ({ at, width, color, thick = 5 }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const end = useEnd();
  const p = ramp(frame, at, 16) * (1 - ramp(frame, end, 10, IN));
  return <div style={{ width: width * k * p, height: thick * k, background: color }} />;
};

/** A small solid chip (a ratio, a verdict): it wipes open, and shut again at the end. */
const Chip: React.FC<{ text: string; at: number; bg: string; color: string; size?: number }> =
  ({ text, at, bg, color, size = 30 }) => {
    const frame = useCurrentFrame();
    const end = useEnd();
    const k = useK();
    const p = ramp(frame, at, 14);
    const q = ramp(frame, end, 10, IN);
    if (!text || p <= 0) return null;
    return (
      <div style={{ display: "inline-flex", alignItems: "center", background: bg, color, fontFamily: LABEL, fontWeight: 800,
        fontSize: size * k, letterSpacing: "0.1em", lineHeight: 1, padding: `${10 * k}px ${22 * k}px ${8 * k}px`,
        borderRadius: 6 * k, whiteSpace: "nowrap",
        clipPath: `inset(0 ${((1 - p) * 100).toFixed(2)}% 0 ${(q * 100).toFixed(2)}%)` }}>
        {text}
      </div>
    );
  };

/**
 * A data card: the footage scrim first (rendered directly, as in the rest of the
 * library - an opacity wrapper would cut its backdrop-filter off from the
 * footage), then the content on a slow push with a last-frames guard.
 */
const Card: React.FC<{ overlay: Overlay; children: React.ReactNode }> = ({ overlay, children }) => {
  const hold = useHold();
  const fin = useFin();
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ transform: `scale(${hold})`, opacity: fin }}>{children}</AbsoluteFill>
    </AbsoluteFill>
  );
};

/**
 * A light odometer for dense rows: every digit column spins into place like
 * the Odometer, but draws only the two glyphs in view (4 nodes, not 13).
 */
const LiteRoll: React.FC<{ value: number; at: number; frames: number; size: number; color: string; prefix?: string;
  suffix?: string; suffixColor?: string }> = ({ value, at, frames, size, color, prefix = "", suffix = "", suffixColor }) => {
  const frame = useCurrentFrame();
  const chars = fmt(value).split("");
  const nd = chars.filter((c) => /\d/.test(c)).length;
  let di = 0;
  return (
    <span style={{ display: "inline-flex", alignItems: "flex-start", fontFamily: DISPLAY, fontSize: size, lineHeight: 1, color,
      whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
      {prefix ? <span>{prefix}</span> : null}
      {chars.map((c, i) => {
        if (!/\d/.test(c)) return <span key={i} style={{ opacity: ramp(frame, at, Math.max(1, frames * 0.3)) }}>{c}</span>;
        const fromRight = nd - 1 - di;
        di += 1;
        const travel = (1 + Math.min(2, fromRight)) * 10 + Number(c);
        const pos = ramp(frame, at + fromRight * 2, frames) * travel;
        const lo = Math.floor(pos);
        const f = pos - lo;
        return (
          <span key={i} style={{ position: "relative", display: "inline-block", height: size, overflow: "hidden" }}>
            <span style={{ visibility: "hidden" }}>0</span>
            <span style={{ position: "absolute", left: 0, right: 0, top: 0, textAlign: "center",
              transform: `translateY(${(-f * size).toFixed(2)}px)` }}>{lo % 10}</span>
            <span style={{ position: "absolute", left: 0, right: 0, top: 0, textAlign: "center",
              transform: `translateY(${((1 - f) * size).toFixed(2)}px)` }}>{(lo + 1) % 10}</span>
          </span>
        );
      })}
      {suffix ? (
        <span style={{ fontSize: size * 0.5, marginLeft: size * 0.04, marginTop: size * 0.06, color: suffixColor || color,
          opacity: ramp(frame, at + frames * 0.35, Math.max(1, frames * 0.4)) }}>{suffix}</span>
      ) : null}
    </span>
  );
};

// ================================================================== 1. split statement (own backdrop)
/**
 * Two statements on a frame cut diagonally. A graphite half slides in from the
 * left and a paper half from the right; they lock on an accent seam that
 * flashes, then a spark keeps running up it. On each side an accent bar draws,
 * the headline rises letter by letter and the lines beneath slide up out of
 * their masks. At the end the text drops away and the halves part like doors.
 * items[0] / items[1]: label (+ text); text: a small kicker. Without two items:
 * text vs subtitle.
 */
const SplitStatement: Look = ({ overlay, accent: accentIn }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H, fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const end = useEnd();
  const accent = hexOk(accentIn);
  let kicker = str(overlay.text);
  let sides = rowsOf(overlay.items, 6).filter((r) => r.label || r.text).slice(0, 2);
  if (sides.length < 2) {
    const sub = str(overlay.subtitle);
    if (!kicker || !sub) return null;
    sides = [textRow(kicker), textRow(sub)];
    kicker = "";
  }
  const topX = W * 0.575, botX = W * 0.425;
  const slope = (topX - botX) / H;
  const xAt = (y: number) => topX - slope * y;
  const pIn = ramp(frame, 0, 18);
  const pOut = ramp(frame, end + 1, 12, IN);
  const away = 1 - pIn + pOut;
  const dxL = -away * (topX + 60 * k);
  const dxR = away * (W - botX + 60 * k);
  const flash = interpolate(frame, [7, 10, 30], [0, 1, 0], clamp);
  const drift = interpolate(frame, [0, Math.max(1, dur)], [0, 1], clamp);
  const cycle = Math.max(1, Math.round(fps * 2.2));
  const cyc = Math.max(0, frame - 18) / cycle;
  const sp = cyc - Math.floor(cyc);
  const y0 = H * (1 - Math.min(1, sp + 0.07));
  const y1 = H * (1 - Math.max(0, sp - 0.07));
  const seamOn = ramp(frame, 5, 6) * (1 - pOut);
  const seam = `M${xAt(-30 * k).toFixed(1)} ${(-30 * k).toFixed(1)} L${xAt(H + 30 * k).toFixed(1)} ${(H + 30 * k).toFixed(1)}`;
  const kick = clip(cap(kicker), 34);             // ~21 px a letter: stays clear of the seam at the top

  const block = (r: Row, dark: boolean) => {
    const at = dark ? 9 : 15;
    const head = cap(r.label);
    const ink = dark ? "#ffffff" : "#111216";
    const soft = dark ? "rgba(255,255,255,.78)" : "rgba(17,18,22,.76)";
    const bar = ramp(frame, at, 16) * (1 - ramp(frame, end, 10, IN));
    let size: number;
    let heads: string[];
    let body: string[];
    if (head) {
      size = head.length <= 12 ? 84 : head.length <= 26 ? 68 : 54;
      heads = wrapN(head, size === 84 ? 12 : size === 68 ? 15 : 20, size === 54 ? 3 : 2);
      body = wrapN(r.text, 32, 4);
    } else {
      const t = cap(r.text);
      size = t.length <= 30 ? 72 : t.length <= 60 ? 60 : 50;
      heads = wrapN(t, size === 72 ? 16 : size === 60 ? 19 : 23, 4);
      body = [];
    }
    return (
      <div style={{ position: "absolute", top: 0, bottom: 0, left: (dark ? 150 : 1120) * k, width: 650 * k, display: "flex",
        flexDirection: "column", justifyContent: "center", alignItems: dark ? "flex-end" : "flex-start",
        textAlign: dark ? "right" : "left", gap: 4 * k,
        transform: `translateX(${((dark ? -1 : 1) * drift * 16 * k).toFixed(2)}px)` }}>
        <div style={{ width: 64 * k * bar, height: 6 * k, background: accent, marginBottom: 16 * k }} />
        {heads.map((ln, i) => (
          <LetterLine key={i} text={ln} at={at + 2 + i * 4} step={0.9} outAt={outFor(end, ln.length)}
            style={{ fontFamily: DISPLAY, fontSize: size * k, lineHeight: 0.96, color: ink, letterSpacing: "0.02em",
              whiteSpace: "nowrap" }} />
        ))}
        {body.length ? <div style={{ height: 12 * k }} /> : null}
        {body.map((ln, i) => (
          <Rise key={`b${i}`} at={at + 12 + i * 3}>
            <span style={{ display: "block", fontFamily: INTER, fontWeight: 400, fontSize: 34 * k, lineHeight: 1.32,
              color: soft, whiteSpace: "nowrap" }}>{ln}</span>
          </Rise>
        ))}
      </div>
    );
  };

  const leftBg = [
    "linear-gradient(105deg, rgba(0,0,0,0) 36%, rgba(0,0,0,.5) 50%)",
    "radial-gradient(ellipse at 26% 46%, rgba(255,255,255,.08) 0%, rgba(255,255,255,0) 55%)",
    `repeating-linear-gradient(105deg, rgba(255,255,255,.024) 0px, rgba(255,255,255,.024) ${2 * k}px, rgba(255,255,255,0) ${2 * k}px, rgba(255,255,255,0) ${16 * k}px)`,
    "linear-gradient(160deg, #1b1c22 0%, #0f1014 55%, #07080a 100%)",
  ].join(", ");
  const rightBg = [
    "linear-gradient(105deg, rgba(255,255,255,.6) 50%, rgba(255,255,255,0) 57%)",
    `radial-gradient(ellipse at 90% 88%, ${alpha(accent, 0.3)} 0%, rgba(0,0,0,0) 48%)`,
    `repeating-linear-gradient(105deg, rgba(0,0,0,.03) 0px, rgba(0,0,0,.03) ${2 * k}px, rgba(0,0,0,0) ${2 * k}px, rgba(0,0,0,0) ${16 * k}px)`,
    "linear-gradient(160deg, #f5f3ed 0%, #e8e5dc 55%, #d4d0c5 100%)",
  ].join(", ");

  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${hold})` }}>
        <AbsoluteFill style={{ background: leftBg, transform: `translateX(${dxL.toFixed(2)}px)`,
          clipPath: `polygon(0px 0px, ${(topX + 1).toFixed(1)}px 0px, ${(botX + 1).toFixed(1)}px ${H}px, 0px ${H}px)` }}>
          {kick ? (
            <div style={{ position: "absolute", left: 150 * k, top: 118 * k, display: "flex", alignItems: "center", gap: 16 * k }}>
              <div style={{ width: 36 * k * ramp(frame, 8, 14) * (1 - ramp(frame, end, 10, IN)), height: 4 * k, background: accent }} />
              <LetterLine text={kick} at={10} step={0.6} outAt={outFor(end, kick.length)} style={{ fontFamily: LABEL,
                fontWeight: 800, fontSize: 28 * k, letterSpacing: "0.28em", color: accent, whiteSpace: "nowrap" }} />
            </div>
          ) : null}
          {block(sides[0], true)}
        </AbsoluteFill>
        <AbsoluteFill style={{ background: rightBg, transform: `translateX(${dxR.toFixed(2)}px)`,
          clipPath: `polygon(${topX.toFixed(1)}px 0px, ${W}px 0px, ${W}px ${H}px, ${botX.toFixed(1)}px ${H}px)` }}>
          {block(sides[1], false)}
        </AbsoluteFill>
        <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible", opacity: seamOn,
          transform: `translateX(${dxR.toFixed(2)}px)` }}>
          <path d={seam} fill="none" stroke={accent} strokeWidth={(12 + 44 * flash) * k} strokeOpacity={0.16 + 0.24 * flash} />
          <path d={seam} fill="none" stroke={accent} strokeWidth={7 * k} />
          <path d={`M${xAt(y0).toFixed(1)} ${y0.toFixed(1)} L${xAt(y1).toFixed(1)} ${y1.toFixed(1)}`} fill="none" stroke="#fff"
            strokeWidth={4 * k} strokeLinecap="round" opacity={Math.sin(Math.PI * sp) * 0.9 * ramp(frame, 18, 10)} />
        </svg>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 2. balance scale
/**
 * A balance. The pillar rises out of its base, the beam extends, the pans drop
 * onto their strings and weights stack onto each pan (more for the bigger
 * value), each landing nudging the beam. Then the beam tips toward the heavier
 * side on a damped spring - swinging past, settling, swaying a little - while
 * the values roll under the pans and the ratio wipes open under the base. At
 * the end it levels, folds in and the text leaves through its masks.
 * items[0] / items[1]: label + value (prefix / suffix per item or on the overlay).
 */
const BalanceScale: Look = ({ overlay, accent: accentIn }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H, fps } = useVideoConfig();
  const k = useK();
  const T = useT();
  const out = useOut();
  const accent = hexOk(accentIn);
  const two = rowsOf(overlay.items, 6).filter((r) => Number.isFinite(r.value)).slice(0, 2);
  if (two.length < 2) return null;
  const suffix = str(overlay.suffix), prefix = str(overlay.prefix);
  const va = Math.abs(two[0].value), vb = Math.abs(two[1].value);
  const big = Math.max(va, vb), small = Math.min(va, vb);
  const heavy = va === vb ? -1 : vb > va ? 1 : 0;
  const target = big > 0 ? (13 * (vb - va)) / big : 0;          // degrees; + tips the right pan down
  const tipAt = Math.max(20, T(0.85));
  const sp = frame < tipAt ? 0 : spring({ frame: frame - tipAt, fps, config: { damping: 7, stiffness: 55, mass: 1 } });
  const bump = (t: number) => (t <= 0 ? 0 : Math.sin(t * 0.55) * Math.exp(-t / 7));
  const loads = [T(0.4), T(0.57)];
  const sway = 0.35 * Math.sin((frame / fps) * 1.5) * ramp(frame, tipAt + 30, 20);
  const theta = (target * sp - 1.5 * bump(frame - loads[0]) + 1.5 * bump(frame - loads[1]) + sway) * (1 - out);
  const th = (theta * Math.PI) / 180;
  const cx = W / 2, py = 372 * k, baseY = 812 * k;
  const L = 430 * k * ramp(frame, 6, 16) * (1 - out);
  const S = 210 * k, RIM = 150 * k;
  const pillar = ramp(frame, 0, 14) * (1 - out);
  const panIn = ramp(frame, 10, 16, BACK);
  const panOp = ramp(frame, 10, 8) * (1 - out);
  const id = `cpbal${String(overlay.startFrame ?? 0)}`;
  const BH = 17 * k, BG = 4 * k;
  const nOf = (v: number) => (big > 0 ? Math.max(1, Math.round((v / big) * 6)) : 1);
  const pans = [0, 1].map((i) => {
    const s = i === 0 ? -1 : 1;
    const ax = cx + s * L * Math.cos(th), ay = py + s * L * Math.sin(th);
    return { i, ax, ay, rx: ax, ry: ay + S - (1 - panIn) * 60 * k };
  });
  const ratio = small > 0 ? big / small : NaN;
  const heavyLabel = heavy >= 0 ? clip(cap(two[heavy].label), 20) : "";
  const chip = heavy < 0 ? "EVEN" : !Number.isFinite(ratio) ? "" : ratio < 1.05 ? "NEARLY EVEN"
    : `${heavyLabel ? `${heavyLabel} · ` : ""}${ratio >= 10 ? Math.round(ratio) : ratio.toFixed(1)}×`;
  const colH = baseY - 12 * k - py;
  return (
    <Card overlay={overlay}>
      <div style={{ position: "absolute", left: 0, right: 0, top: 96 * k, display: "flex", justifyContent: "center" }}>
        <Head text={overlay.text} accent={accent} size={54} center />
      </div>
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        <defs>
          <linearGradient id={`${id}m`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#ffffff" />
            <stop offset="55%" stopColor="#cfd0d6" />
            <stop offset="100%" stopColor="#85868e" />
          </linearGradient>
          <linearGradient id={`${id}a`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={accent} />
            <stop offset="100%" stopColor={alpha(accent, 0.62)} />
          </linearGradient>
        </defs>
        <ellipse cx={cx} cy={baseY + 24 * k} rx={Math.max(0.001, 210 * k * pillar)} ry={14 * k} fill="rgba(0,0,0,.35)" />
        <rect x={cx - 160 * k * pillar} y={baseY} width={320 * k * pillar} height={16 * k} rx={8 * k} fill={`url(#${id}m)`} />
        <rect x={cx - 90 * k * pillar} y={baseY - 12 * k} width={180 * k * pillar} height={14 * k} rx={6 * k}
          fill={`url(#${id}m)`} opacity={0.9} />
        <rect x={cx - 7 * k} y={baseY - 12 * k - colH * pillar} width={14 * k} height={colH * pillar} rx={5 * k}
          fill={`url(#${id}m)`} />
        <path d={`M${cx} ${py - 6 * k} L${cx - 30 * k} ${py + 46 * k} L${cx + 30 * k} ${py + 46 * k} Z`}
          fill={`url(#${id}m)`} opacity={pillar} />
        {pans.map(({ i, ax, ay, rx, ry }) => {
          const hot = heavy === i;
          const n = nOf(i === 0 ? va : vb);
          return (
            <g key={i} opacity={panOp}>
              <path d={`M${ax} ${ay} L${rx - RIM} ${ry} M${ax} ${ay} L${rx + RIM} ${ry}`} fill="none"
                stroke="rgba(255,255,255,.72)" strokeWidth={2.5 * k} />
              <ellipse cx={rx} cy={ry} rx={RIM + 10 * k} ry={10 * k} fill="rgba(255,255,255,.12)"
                stroke="rgba(255,255,255,.55)" strokeWidth={2 * k} />
              {Array.from({ length: n }, (_, j) => {
                const p = ramp(frame, loads[i] + j * 2, 10, BACK);
                if (p <= 0.001) return null;
                const hTop = j * (BH + BG) + BH;
                const hw = Math.min(116 * k, 0.8 * RIM * Math.max(0.2, 1 - hTop / S));
                const yb = ry + 6 * k - j * (BH + BG) - (1 - p) * 90 * k;
                return (
                  <rect key={j} x={rx - hw} y={yb - BH} width={2 * hw} height={BH} rx={3 * k}
                    fill={hot ? `url(#${id}a)` : `url(#${id}m)`} stroke="rgba(0,0,0,.3)" strokeWidth={1.2 * k} />
                );
              })}
              <path d={`M${rx - RIM - 10 * k} ${ry} Q${rx} ${ry + 74 * k} ${rx + RIM + 10 * k} ${ry} Z`}
                fill={`url(#${id}m)`} stroke={hot ? accent : "rgba(255,255,255,.9)"} strokeWidth={2.5 * k} />
              <circle cx={ax} cy={ay} r={6 * k} fill="none" stroke="#fff" strokeWidth={2.5 * k} />
            </g>
          );
        })}
        <g transform={`rotate(${theta.toFixed(3)} ${cx} ${py})`} opacity={L > 1 ? 1 : 0}>
          <rect x={cx - L} y={py - 8 * k} width={2 * L} height={16 * k} rx={8 * k} fill={`url(#${id}m)`} />
          <rect x={cx - L} y={py - 8 * k} width={2 * L} height={4 * k} rx={2 * k} fill="rgba(255,255,255,.55)" />
          <circle cx={cx - L} cy={py} r={11 * k} fill="#f4f4f6" />
          <circle cx={cx + L} cy={py} r={11 * k} fill="#f4f4f6" />
        </g>
        <circle cx={cx} cy={py} r={Math.max(0.001, 17 * k * pillar)} fill={INK} stroke={accent} strokeWidth={5 * k}
          opacity={pillar > 0.01 ? 1 : 0} />
      </svg>
      {pans.map(({ i, rx, ry }) => {
        const it = two[i];
        const hot = heavy === i;
        const at = loads[i];
        return (
          <div key={`n${i}`} style={{ position: "absolute", left: rx - 240 * k, width: 480 * k, top: ry + 52 * k,
            display: "flex", flexDirection: "column", alignItems: "center", gap: 4 * k, opacity: panOp }}>
            <Rise at={at - 2} frames={12}>
              <Odometer value={it.value} at={at} frames={T(1.0)} size={92 * k} color="#fff" prefix={it.prefix || prefix}
                suffix={unitOf(it.suffix || suffix)} suffixScale={0.45} suffixColor={hot ? accent : "rgba(255,255,255,.7)"} />
            </Rise>
            <Line text={clip(cap(it.label), 24)} at={at + 5} step={0.7}
              style={labelCss(k, 30, hot ? accent : "rgba(255,255,255,.85)")} />
          </div>
        );
      })}
      {chip ? (
        <div style={{ position: "absolute", left: 0, right: 0, top: baseY + 70 * k, display: "flex", justifyContent: "center" }}>
          <Chip text={chip} at={tipAt + T(0.75)} bg={heavy >= 0 ? accent : "rgba(255,255,255,.92)"}
            color={heavy >= 0 ? inkOn(accent) : INK} size={30} />
        </div>
      ) : null}
    </Card>
  );
};

// ================================================================== 3. venn
/**
 * Two rings draw on apart, then slide together on a spring. Once they
 * overlap, the lens between them fills with the accent from the bottom like
 * rising water (a wave on its surface settling), and the shared label rises
 * inside it - or under the rings on a leader when it is long. Each set's name
 * (items[0], items[1]: label, optional text / value) sits in its own crescent.
 * The overlap is overlay.highlight when set (then text is the heading), else
 * overlay.text (then subtitle is the heading). At the end the water drains,
 * the rings drift apart and undraw.
 */
const Venn: Look = ({ overlay, accent: accentIn }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H, fps } = useVideoConfig();
  const k = useK();
  const T = useT();
  const end = useEnd();
  const accent = hexOk(accentIn);
  const sets = rowsOf(overlay.items, 6).filter((r) => r.label || r.text).slice(0, 2);
  if (sets.length < 2) return null;
  const hl = str(overlay.highlight);
  const shared = cap(hl || overlay.text);
  const heading = hl ? str(overlay.text) : str(overlay.subtitle);
  const inLines = lines(shared, 12);
  const inside = inLines.length > 0 && inLines.length <= 3 && inLines.every((l) => l.length <= 13);
  const R = 290 * k;
  const cx = W / 2;
  const cy = (heading ? 575 : 545) * k - (inside || !shared ? 0 : 45 * k);
  const slideAt = T(0.8);
  const s = frame < slideAt ? 0 : spring({ frame: frame - slideAt, fps, config: { damping: 15, stiffness: 70, mass: 1 } });
  const part = ramp(frame, end, 12, IN);
  const D = lerp(2.3 * R, 1.15 * R, s) + 0.5 * R * part;
  const r = R * (1 + 0.006 * Math.sin(frame / (fps * 0.9))) * (1 - 0.08 * part);
  const cxA = cx - D / 2, cxB = cx + D / 2;
  const draw = ramp(frame, T(0.05), T(0.7), IN_OUT) * (1 - part);
  const fillOp = ramp(frame, T(0.25), T(0.5)) * (1 - part);
  const lens = D < 2 * r - 1;
  const yi = lens ? Math.sqrt(Math.max(0, r * r - (D / 2) * (D / 2))) : 0;
  const f1 = (v: number) => v.toFixed(1);
  const lensD = lens
    ? `M${f1(cx)} ${f1(cy - yi)} A${f1(r)} ${f1(r)} 0 0 1 ${f1(cx)} ${f1(cy + yi)} A${f1(r)} ${f1(r)} 0 0 1 ${f1(cx)} ${f1(cy - yi)} Z`
    : "M0 0";
  const fillAt = slideAt + T(0.55);
  const lvl = ramp(frame, fillAt, T(0.8), IN_OUT) * (1 - ramp(frame, end - 3, 11, IN));
  const settle = ramp(frame, fillAt + T(0.6), T(0.8));
  const amp = (3 + 8 * (1 - settle)) * k;
  const surf = cy + yi - lvl * (2 * yi + 18 * k);
  const pts: string[] = [];
  for (let j = 0; j <= 18; j++) {
    const x = cx - r + (j / 18) * 2 * r;
    pts.push(`${f1(x)} ${f1(surf + Math.sin(x / (58 * k) + frame * 0.2) * amp)}`);
  }
  const waveTop = `M${pts.join(" L")}`;
  const bottom = f1(cy + r + 40 * k);
  const wave = `M${f1(cx - r)} ${bottom} L${pts.join(" L")} L${f1(cx + r)} ${bottom} Z`;
  const rim = ramp(frame, fillAt + T(0.6), 10) * (1 - part);
  const sharedAt = fillAt + T(0.5);
  const lead = ramp(frame, fillAt + T(0.4), T(0.4), IN_OUT) * (1 - part);
  const id = `cpvn${String(overlay.startFrame ?? 0)}`;
  const midA = (cxA - r + Math.min(cxA + r, cxB - r)) / 2;
  const midB = (Math.max(cxB - r, cxA + r) + cxB + r) / 2;

  const setBlock = (row: Row, i: number, mid: number) => {
    const at = T(0.3) + i * 4;
    const nameLs = wrapN(cap(row.label || row.text), 13, 2);
    const desc = row.label ? wrapN(row.text, 20, 2) : [];
    return (
      <div key={`set${i}`} style={{ position: "absolute", left: mid - 165 * k, width: 330 * k, top: cy - 200 * k, height: 400 * k,
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 4 * k, textAlign: "center" }}>
        {Number.isFinite(row.value) ? (
          <Rise at={at}>
            <Odometer value={row.value} at={at + 2} frames={T(1.0)} size={62 * k} color="#fff"
              prefix={row.prefix || str(overlay.prefix)} suffix={unitOf(row.suffix || overlay.suffix)} suffixScale={0.5}
              suffixColor={accent} />
          </Rise>
        ) : null}
        {nameLs.map((ln, j) => (
          <Line key={j} text={ln} at={at + 3 + j * 3} step={0.8} style={labelCss(k, 38, "#fff", "0.1em")} />
        ))}
        {desc.map((ln, j) => (
          <Rise key={`d${j}`} at={at + 9 + j * 3}>
            <span style={{ display: "block", fontFamily: INTER, fontWeight: 400, fontSize: 24 * k, lineHeight: 1.3,
              color: "rgba(255,255,255,.72)", whiteSpace: "nowrap" }}>{ln}</span>
          </Rise>
        ))}
      </div>
    );
  };

  return (
    <Card overlay={overlay}>
      {heading ? (
        <div style={{ position: "absolute", left: 0, right: 0, top: 92 * k, display: "flex", justifyContent: "center" }}>
          <Head text={heading} accent={accent} size={56} center />
        </div>
      ) : null}
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        <defs>
          <clipPath id={`${id}l`}><path d={lensD} /></clipPath>
          <clipPath id={`${id}w`}><path d={wave} /></clipPath>
        </defs>
        <circle cx={cxA} cy={cy} r={r} fill="rgba(255,255,255,.07)" opacity={fillOp} />
        <circle cx={cxB} cy={cy} r={r} fill="rgba(255,255,255,.07)" opacity={fillOp} />
        {lens && lvl > 0.001 ? (
          <g clipPath={`url(#${id}l)`}>
            <path d={lensD} fill={accent} clipPath={`url(#${id}w)`} />
            <path d={waveTop} fill="none" stroke="rgba(255,255,255,.6)" strokeWidth={2.5 * k} />
          </g>
        ) : null}
        <circle cx={cxA} cy={cy} r={r} fill="none" stroke="rgba(255,255,255,.12)" strokeWidth={12 * k} opacity={draw} />
        <circle cx={cxB} cy={cy} r={r} fill="none" stroke="rgba(255,255,255,.12)" strokeWidth={12 * k} opacity={draw} />
        <circle cx={cxA} cy={cy} r={r} fill="none" stroke="rgba(255,255,255,.9)" strokeWidth={3.5 * k} pathLength={1}
          strokeDasharray={`${draw.toFixed(4)} 1`} transform={`rotate(-90 ${f1(cxA)} ${f1(cy)})`} />
        <circle cx={cxB} cy={cy} r={r} fill="none" stroke="rgba(255,255,255,.9)" strokeWidth={3.5 * k} pathLength={1}
          strokeDasharray={`${draw.toFixed(4)} 1`}
          transform={`translate(${f1(cxB)} ${f1(cy)}) scale(-1 1) rotate(-90) translate(${f1(-cxB)} ${f1(-cy)})`} />
        {lens ? <path d={lensD} fill="none" stroke={accent} strokeWidth={4.5 * k} strokeLinejoin="round" opacity={rim} /> : null}
        {!inside && shared && lens ? (
          <g opacity={lead}>
            <line x1={cx} x2={cx} y1={cy + yi} y2={cy + yi + (r - yi + 22 * k) * lead} stroke={accent} strokeWidth={3 * k} />
            <circle cx={cx} cy={cy + yi} r={6 * k} fill={accent} />
          </g>
        ) : null}
      </svg>
      {setBlock(sets[0], 0, midA)}
      {setBlock(sets[1], 1, midB)}
      {inside && lens ? (
        <div style={{ position: "absolute", left: cx - 125 * k, width: 250 * k, top: cy - 120 * k, height: 240 * k,
          display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
          {inLines.map((ln, j) => (
            <Line key={j} text={ln} at={sharedAt + j * 3} step={0.7}
              style={{ ...labelCss(k, 30, inkOn(accent), "0.08em"), textShadow: "none" }} />
          ))}
        </div>
      ) : null}
      {!inside && shared ? (
        <div style={{ position: "absolute", left: cx - 560 * k, width: 1120 * k, top: cy + R + 30 * k, display: "flex",
          flexDirection: "column", alignItems: "center", gap: 2 * k }}>
          {wrapN(shared, 30, 2).map((ln, j) => (
            <Line key={j} text={ln} at={sharedAt + j * 4} step={0.6} style={{ fontFamily: DISPLAY, fontSize: 50 * k, color: "#fff",
              letterSpacing: "0.04em", lineHeight: 1, whiteSpace: "nowrap", textShadow: "0 6px 26px rgba(0,0,0,.5)" }} />
          ))}
        </div>
      ) : null}
    </Card>
  );
};

// ================================================================== 4. tick table
const YES = ["yes", "y", "true", "1", "✓", "✔", "☑", "check", "checked", "tick", "ok", "pass", "+", "full", "has"];
const NO = ["no", "n", "false", "0", "✗", "✘", "×", "x", "cross", "none", "fail", "-", "–", "—", "lacks"];
const PART = ["partial", "part", "partly", "some", "half", "~", "½", "limited", "mixed", "maybe", "?", "sometimes"];
/** "yes|no", "✓ ✗", "yes, partial" -> marks (1 tick, 0 cross, 0.5 half), at most three. */
const marksOf = (text: string): Mark[] => {
  const found: Mark[] = [];
  const spaced = text.toLowerCase().replace(/([✓✔☑✗✘×~½])/g, " $1 ");
  for (const tok of spaced.split(/[|,/;]+|\s+/)) {
    const t = tok.trim();
    if (!t) continue;
    if (YES.indexOf(t) >= 0) found.push(1);
    else if (NO.indexOf(t) >= 0) found.push(0);
    else if (PART.indexOf(t) >= 0) found.push(0.5);
    if (found.length >= 3) break;
  }
  return found;
};

/**
 * A comparison table. Rows (items: label, marks in text "yes|no|partial")
 * rise in with hairlines drawing under them; then a scan line runs down each
 * column in turn (column names in label "A|B" or subtitle) and every cell
 * pops its mark as it passes - an accent disc with a drawn tick, a grey
 * cross, or a half disc. Last, the scores roll in under each column and the
 * column with the most ticks lights up in the accent. A row without marks
 * but with a value counts it as one column (value >= 1 tick, 0 cross).
 */
const TickTable: Look = ({ overlay, accent: accentIn }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const T = useT();
  const end = useEnd();
  const out = useOut();
  const accent = hexOk(accentIn);
  const rows = rowsOf(overlay.items, 12)
    .map((r) => {
      let marks: Mark[] = marksOf(r.text);
      if (!marks.length && Number.isFinite(r.value)) marks = [r.value >= 1 ? 1 : r.value > 0 ? 0.5 : 0];
      return { label: r.label, marks };
    })
    .filter((r) => r.label.length > 0 && r.marks.length > 0)
    .slice(0, 6);
  if (rows.length < 2) return null;
  const n = rows.length;
  const C = Math.min(3, Math.max(...rows.map((r) => r.marks.length)));
  let heads = namesOf(overlay.label, 3);
  if (heads.length < C) {
    const alt = namesOf(overlay.subtitle, 3);
    if (alt.length > heads.length) heads = alt;
  }
  if (!heads.length && C === 1) heads = [str(overlay.label) || str(overlay.subtitle)];
  const score = Array.from({ length: C }, (_, c) => rows.reduce((a, r) => a + (c < r.marks.length ? r.marks[c] : 0), 0));
  const best = Math.max(...score);
  const winner = C > 1 && best > 0 && score.filter((v) => v === best).length === 1 ? score.indexOf(best) : -1;
  const RH = (n <= 4 ? 84 : n === 5 ? 76 : 68) * k;
  const LW = (C === 3 ? 520 : 600) * k;
  const CW = (C === 1 ? 280 : C === 2 ? 260 : 240) * k;
  const TW = LW + C * CW;
  const HH = 88 * k, FH = 84 * k;
  const bodyH = n * RH;
  const TH = HH + bodyH + FH;
  const marksAt = T(0.8);
  const budget = Math.max(C * 8, T(1.7));
  const colDur = budget / C;
  const stepF = colDur / (n + 0.5);
  const markAt = (c: number, i: number) => marksAt + c * colDur + i * stepF;
  const tallyAt = Math.round(marksAt + budget + T(0.1));
  const band = ramp(frame, tallyAt + 4, T(0.5), IN_OUT) * (1 - out);
  const lit = ramp(frame, tallyAt, 10);
  const rule = ramp(frame, T(0.1), T(0.6), IN_OUT) * (1 - out);
  const labelMax = C === 3 ? 24 : 26;
  const id = `cptt${String(overlay.startFrame ?? 0)}`;
  const colX = (c: number) => LW + c * CW + CW / 2;
  const cells: { i: number; c: number; m: Mark }[] = [];
  rows.forEach((row, i) => {
    for (let c = 0; c < C; c++) if (c < row.marks.length) cells.push({ i, c, m: row.marks[c] });
  });
  return (
    <Card overlay={overlay}>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 34 * k }}>
          <Head text={overlay.text} accent={accent} size={56} />
          <div style={{ position: "relative", width: TW, height: TH }}>
            <svg width={TW} height={TH} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
              <defs>
                <linearGradient id={`${id}g`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stopColor={accent} stopOpacity={0} />
                  <stop offset="1" stopColor={accent} stopOpacity={0.24} />
                </linearGradient>
              </defs>
              {winner >= 0 && band > 0.001 ? (
                <rect x={LW + winner * CW + 10 * k} y={4 * k} width={CW - 20 * k} height={Math.max(0, (TH - 8 * k) * band)}
                  rx={16 * k} fill={alpha(accent, 0.08)} stroke={alpha(accent, 0.55)} strokeWidth={2 * k} />
              ) : null}
              {Array.from({ length: C }, (_, c) => {
                const t0 = marksAt + c * colDur;
                const q = (frame - t0) / Math.max(1, colDur);
                if (q < -0.02 || q > 1.15) return null;
                const sy = HH + clamp01(q) * bodyH;
                const gy = Math.max(HH, sy - 48 * k);
                const o = interpolate(q, [-0.02, 0.05, 1, 1.15], [0, 1, 1, 0], clamp);
                return (
                  <g key={`s${c}`} opacity={o}>
                    <rect x={LW + c * CW + 16 * k} y={gy} width={CW - 32 * k} height={Math.max(0, sy - gy)} fill={`url(#${id}g)`} />
                    <rect x={LW + c * CW + 16 * k} y={sy - 1.5 * k} width={CW - 32 * k} height={3 * k} fill={accent} />
                  </g>
                );
              })}
              {cells.map(({ i, c, m }) => {
                const at = markAt(c, i);
                const pin = ramp(frame, at, 12, BACK);
                const pout = ramp(frame, end - 3 + (i + c) * 0.6, 8, IN);
                const s = Math.max(0, pin) * (1 - pout);
                if (s <= 0.001) return null;
                const x = colX(c), y = HH + i * RH + RH / 2;
                const d1 = ramp(frame, at + 3, 8, IN_OUT);
                const d2 = ramp(frame, at + 7, 7, IN_OUT);
                const rip = ramp(frame, at, 16);
                const rr = 22 * k;
                return (
                  <g key={`m${i}-${c}`} transform={`translate(${x.toFixed(1)} ${y.toFixed(1)}) scale(${s.toFixed(3)})`}>
                    {m === 1 ? (
                      <>
                        {rip < 1 ? (
                          <circle r={rr + 20 * k * rip} fill="none" stroke={accent} strokeWidth={2.5 * k} opacity={(1 - rip) * 0.7} />
                        ) : null}
                        <circle r={rr} fill={accent} />
                        <path d={`M${-10 * k} ${1 * k} L${-3 * k} ${8 * k} L${11 * k} ${-8 * k}`} fill="none" stroke={inkOn(accent)}
                          strokeWidth={4.5 * k} strokeLinecap="round" strokeLinejoin="round" pathLength={1}
                          strokeDasharray={`${d1.toFixed(4)} 1`} opacity={d1 > 0.01 ? 1 : 0} />
                      </>
                    ) : m === 0 ? (
                      <>
                        <circle r={rr} fill="rgba(255,255,255,.04)" stroke="rgba(255,255,255,.3)" strokeWidth={2 * k} />
                        <path d={`M${-8 * k} ${-8 * k} L${8 * k} ${8 * k}`} fill="none" stroke="rgba(255,255,255,.55)"
                          strokeWidth={3.5 * k} strokeLinecap="round" pathLength={1} strokeDasharray={`${d1.toFixed(4)} 1`}
                          opacity={d1 > 0.01 ? 1 : 0} />
                        <path d={`M${8 * k} ${-8 * k} L${-8 * k} ${8 * k}`} fill="none" stroke="rgba(255,255,255,.55)"
                          strokeWidth={3.5 * k} strokeLinecap="round" pathLength={1} strokeDasharray={`${d2.toFixed(4)} 1`}
                          opacity={d2 > 0.01 ? 1 : 0} />
                      </>
                    ) : (
                      <>
                        <circle r={rr} fill="none" stroke={accent} strokeWidth={3 * k} />
                        <path d={`M0 ${-rr} A${rr} ${rr} 0 0 0 0 ${rr} Z`} fill={alpha(accent, 0.85)} />
                      </>
                    )}
                  </g>
                );
              })}
            </svg>
            <div style={{ position: "absolute", left: 0, top: HH - 1 * k, width: TW, height: 2 * k, background: "rgba(255,255,255,.4)",
              transform: `scaleX(${rule})`, transformOrigin: "0 50%" }} />
            {Array.from({ length: C }, (_, c) => {
              const at = T(0.15) + c * 3;
              const hot = c === winner;
              const capP = ramp(frame, at, T(0.4), IN_OUT) * (1 - out);
              const name = clip(cap(heads[c] || ""), 14);
              return (
                <div key={`h${c}`} style={{ position: "absolute", left: LW + c * CW, top: 0, width: CW, height: HH, display: "flex",
                  flexDirection: "column", alignItems: "center", justifyContent: "flex-end", gap: 12 * k, paddingBottom: 18 * k,
                  boxSizing: "border-box" }}>
                  <div style={{ position: "relative", width: 54 * k, height: 5 * k, borderRadius: 3 * k,
                    background: "rgba(255,255,255,.55)", transform: `scaleX(${capP})` }}>
                    <div style={{ position: "absolute", left: 0, top: 0, right: 0, bottom: 0, borderRadius: 3 * k, background: accent,
                      opacity: hot ? lit : 0 }} />
                  </div>
                  {name ? (
                    <Line text={name} at={at + 3} step={0.7} style={labelCss(k, 28, hot && lit > 0.5 ? accent : "#fff", "0.12em")} />
                  ) : null}
                </div>
              );
            })}
            {rows.map((row, i) => {
              const at = T(0.3) + i * T(0.07);
              const hair = ramp(frame, at, T(0.5), IN_OUT) * (1 - ramp(frame, end - 1 + i * 0.5, 10, IN));
              return (
                <React.Fragment key={`r${i}`}>
                  <div style={{ position: "absolute", left: 0, top: HH + i * RH, width: LW - 30 * k, height: RH, display: "flex",
                    alignItems: "center" }}>
                    <Rise at={at}>
                      <span style={{ ...labelCss(k, 34, "rgba(255,255,255,.92)", "0.06em"), fontWeight: 700 }}>
                        {clip(cap(row.label), labelMax)}
                      </span>
                    </Rise>
                  </div>
                  <div style={{ position: "absolute", left: 0, top: HH + (i + 1) * RH - 1 * k, width: TW, height: 1.5 * k,
                    background: "rgba(255,255,255,.14)", transform: `scaleX(${hair})`, transformOrigin: "0 50%" }} />
                </React.Fragment>
              );
            })}
            <div style={{ position: "absolute", left: 0, top: HH + bodyH, width: LW - 30 * k, height: FH, display: "flex",
              alignItems: "center" }}>
              <Rise at={tallyAt - 2}>
                <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.22em",
                  color: "rgba(255,255,255,.55)" }}>SCORE</span>
              </Rise>
            </div>
            {score.map((v, c) => {
              const hot = c === winner;
              return (
                <div key={`t${c}`} style={{ position: "absolute", left: LW + c * CW, width: CW, top: HH + bodyH, height: FH,
                  display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <Rise at={tallyAt + c * 3}>
                    <div style={{ display: "flex", alignItems: "flex-end", gap: 6 * k }}>
                      <Odometer value={v} at={tallyAt + c * 3} frames={T(0.7)} size={56 * k} color={hot ? accent : "#fff"} />
                      <span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 24 * k, color: "rgba(255,255,255,.5)" }}>/{n}</span>
                    </div>
                  </Rise>
                </div>
              );
            })}
          </div>
        </div>
      </AbsoluteFill>
    </Card>
  );
};

// ================================================================== 5. myth vs fact
/**
 * A tri-vision board. A graphite card built from six vertical slats unfolds
 * slat by slat; it carries the claim (text) under a MYTH marker, and a red
 * cross draws beside it while the claim dims. Then the slats turn over one
 * after another, in a wave, each rotating on its own axis with depth shading,
 * to the paper FACT side: the correction (subtitle) in ink under an accent
 * FACT chip, an accent tick popping in. At the end the lines leave through
 * their masks and the slats turn edge-on and vanish. label "CLAIM|REALITY"
 * renames the two sides.
 */
const MythFact: Look = ({ overlay, accent: accentIn }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const T = useT();
  const end = useEnd();
  const accent = hexOk(accentIn);
  const myth = str(overlay.text);
  const fact = str(overlay.subtitle) || str(overlay.body) || str(overlay.highlight);
  if (!myth || !fact) return null;
  const names = namesOf(overlay.label, 2);
  const mythName = clip(cap(names[0] || "Myth"), 14);
  const factName = clip(cap(names[1] || "Fact"), 14);
  const W = 1260 * k, H = 560 * k, N = 6, SW = W / N;
  const fitOf = (t: string) => (t.length <= 40 ? { size: 76, chars: 22 } : t.length <= 80 ? { size: 62, chars: 27 }
    : { size: 50, chars: 33 });
  const mf = fitOf(myth), ff = fitOf(fact);
  const mLines = wrapN(cap(myth), mf.chars, 4);
  const fLines = wrapN(cap(fact), ff.chars, 4);
  const inAt = (i: number) => T(0.05) + i * 2;
  const flipAt = Math.max(T(1.7), Math.round(dur * 0.4));
  const flipStep = Math.max(1, T(0.07));
  const flipDur = T(0.6);
  const flipDone = flipAt + (N - 1) * flipStep + flipDur;
  const xAt = T(0.8);
  const dim = ramp(frame, xAt + 6, T(0.4));
  const ring1 = ramp(frame, xAt - 4, T(0.4), IN_OUT);
  const x1 = ramp(frame, xAt, T(0.22), IN_OUT);
  const x2 = ramp(frame, xAt + T(0.14), T(0.22), IN_OUT);
  const tickAt = flipDone - 4;
  const tickPop = ramp(frame, tickAt, 12, BACK);
  const tickDraw = ramp(frame, tickAt + 4, T(0.3), IN_OUT);
  const angle = (i: number) =>
    -90 * (1 - ramp(frame, inAt(i), T(0.55), BACK))
    + 180 * ramp(frame, flipAt + i * flipStep, flipDur, FLIP)
    + 90 * ramp(frame, end + 1 + i * 0.7, 9, IN);
  const flipAll = ramp(frame, flipAt, Math.max(1, flipDone - flipAt), IN_OUT);
  const lift = 1 + 0.025 * Math.sin(Math.PI * flipAll);
  const shadowOp = ramp(frame, T(0.1), T(0.5)) * (1 - ramp(frame, end + 1, 11, IN));
  const iconX = W - 168 * k, iconY = H / 2, ringR = 54 * k;
  const textBox: React.CSSProperties = { position: "absolute", left: 76 * k, top: 120 * k, width: W - 76 * k - 300 * k,
    bottom: 60 * k, display: "flex", flexDirection: "column", justifyContent: "center" };

  const mythFace = (
    <>
      <div style={{ position: "absolute", left: 0, top: 0, width: W, height: H,
        background: "linear-gradient(150deg, #2c2d34 0%, #18191e 58%, #0f1013 100%)" }} />
      <div style={{ position: "absolute", left: 0, top: 0, width: W, height: H,
        backgroundImage: `repeating-linear-gradient(125deg, rgba(255,255,255,.028) 0px, rgba(255,255,255,.028) ${2 * k}px, rgba(0,0,0,0) ${2 * k}px, rgba(0,0,0,0) ${15 * k}px)` }} />
      <div style={{ position: "absolute", left: 76 * k, top: 58 * k, display: "flex", alignItems: "center", gap: 14 * k }}>
        <div style={{ width: 14 * k, height: 14 * k, borderRadius: "50%", background: RED,
          transform: `scale(${Math.max(0, ramp(frame, T(0.2), 12, BACK)).toFixed(3)})` }} />
        <Rise at={T(0.22)}>
          <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k, letterSpacing: "0.34em",
            color: "rgba(255,255,255,.9)", lineHeight: 1 }}>{mythName}</span>
        </Rise>
      </div>
      <div style={{ ...textBox, opacity: 1 - 0.42 * dim }}>
        {mLines.map((ln, i) => (
          <Rise key={i} at={T(0.3) + i * 3}>
            <span style={{ display: "block", fontFamily: DISPLAY, fontSize: mf.size * k, lineHeight: 1.02, letterSpacing: "0.02em",
              color: "#fff", whiteSpace: "nowrap" }}>{ln}</span>
          </Rise>
        ))}
      </div>
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        <circle cx={iconX} cy={iconY} r={ringR} fill="none" stroke={RED} strokeWidth={5 * k} pathLength={1}
          strokeDasharray={`${ring1.toFixed(4)} 1`} transform={`rotate(-90 ${iconX} ${iconY})`} />
        <path d={`M${iconX - 20 * k} ${iconY - 20 * k} L${iconX + 20 * k} ${iconY + 20 * k}`} fill="none" stroke={RED}
          strokeWidth={7 * k} strokeLinecap="round" pathLength={1} strokeDasharray={`${x1.toFixed(4)} 1`} opacity={x1 > 0.01 ? 1 : 0} />
        <path d={`M${iconX + 20 * k} ${iconY - 20 * k} L${iconX - 20 * k} ${iconY + 20 * k}`} fill="none" stroke={RED}
          strokeWidth={7 * k} strokeLinecap="round" pathLength={1} strokeDasharray={`${x2.toFixed(4)} 1`} opacity={x2 > 0.01 ? 1 : 0} />
      </svg>
    </>
  );

  const factFace = (
    <>
      <div style={{ position: "absolute", left: 0, top: 0, width: W, height: H,
        background: "linear-gradient(150deg, #f7f5ef 0%, #ebe8df 60%, #dcd8cc 100%)" }} />
      <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 10 * k, background: accent }} />
      <div style={{ position: "absolute", left: 76 * k, top: 52 * k, padding: `${9 * k}px ${18 * k}px ${5 * k}px`, borderRadius: 4 * k,
        background: accent }}>
        <Rise at={flipAt - 8} delay={-3}>
          <span style={{ display: "block", color: inkOn(accent), fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k,
            letterSpacing: "0.34em", lineHeight: 1 }}>{factName}</span>
        </Rise>
      </div>
      <div style={textBox}>
        {fLines.map((ln, i) => (
          <Rise key={i} at={flipAt - 8} delay={-3}>
            <span style={{ display: "block", fontFamily: DISPLAY, fontSize: ff.size * k, lineHeight: 1.02, letterSpacing: "0.02em",
              color: "#15161a", whiteSpace: "nowrap" }}>{ln}</span>
          </Rise>
        ))}
      </div>
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        <g transform={`translate(${iconX} ${iconY}) scale(${Math.max(0.001, tickPop).toFixed(3)})`}>
          <circle r={ringR} fill={accent} />
          <path d={`M${-22 * k} ${2 * k} L${-7 * k} ${17 * k} L${24 * k} ${-16 * k}`} fill="none" stroke={inkOn(accent)}
            strokeWidth={9 * k} strokeLinecap="round" strokeLinejoin="round" pathLength={1}
            strokeDasharray={`${tickDraw.toFixed(4)} 1`} opacity={tickDraw > 0.01 ? 1 : 0} />
        </g>
      </svg>
    </>
  );

  const face = (i: number): React.CSSProperties => ({
    position: "absolute", left: 0, top: 0, width: SW + 0.5, height: H, overflow: "hidden", boxSizing: "border-box",
    backfaceVisibility: "hidden", WebkitBackfaceVisibility: "hidden",
    borderRadius: i === 0 ? `${14 * k}px 0 0 ${14 * k}px` : i === N - 1 ? `0 ${14 * k}px ${14 * k}px 0` : 0,
  });

  return (
    <Card overlay={overlay}>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{ position: "relative", width: W, height: H, perspective: 2400 * k, transform: `scale(${lift.toFixed(4)})` }}>
          <div style={{ position: "absolute", left: 0, top: 0, width: W, height: H, borderRadius: 14 * k,
            boxShadow: `0 ${40 * k}px ${90 * k}px rgba(0,0,0,.55)`, opacity: shadowOp }} />
          {Array.from({ length: N }, (_, i) => {
            const a = angle(i);
            const c = Math.cos((a * Math.PI) / 180);
            const shade = 0.62 * (1 - Math.abs(c));
            return (
              <div key={i} style={{ position: "absolute", left: i * SW, top: 0, width: SW, height: H, transformStyle: "preserve-3d",
                transform: `rotateY(${a.toFixed(2)}deg)`, opacity: Math.abs(c) < 0.01 ? 0 : 1 }}>
                <div style={{ ...face(i), borderRight: i < N - 1 ? `${1.5 * k}px solid rgba(255,255,255,.07)` : undefined }}>
                  <div style={{ position: "absolute", left: -i * SW, top: 0, width: W, height: H }}>{mythFace}</div>
                  <div style={{ position: "absolute", left: 0, top: 0, right: 0, bottom: 0, background: "#000", opacity: shade }} />
                </div>
                <div style={{ ...face(i), transform: "rotateY(180deg)",
                  borderRight: i < N - 1 ? `${1.5 * k}px solid rgba(0,0,0,.14)` : undefined }}>
                  <div style={{ position: "absolute", left: -i * SW, top: 0, width: W, height: H }}>{factFace}</div>
                  <div style={{ position: "absolute", left: 0, top: 0, right: 0, bottom: 0, background: "#000", opacity: shade * 0.8 }} />
                </div>
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
    </Card>
  );
};

// ================================================================== 6. spectrum marker
/**
 * Where a value sits on a scale from low to high. A spectrum band (pale to
 * the accent) draws in under a fine ruler; a lens marker springs along it to
 * value / total (total defaults to 100 for a percentage, else 1 / 10 / 100 by
 * size) while the reading rolls in a callout above the needle and the band
 * lights up to it. Zones (item labels, evenly split, or item values as upper
 * bounds) sit under the band and the one under the marker lights in the
 * accent; without zones the ends are named from label "LOW|HIGH".
 */
const Spectrum: Look = ({ overlay, accent: accentIn }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const T = useT();
  const out = useOut();
  const accent = hexOk(accentIn);
  const value = toNum(overlay.value);
  if (!Number.isFinite(value)) return null;
  const sfxRaw = str(overlay.suffix);
  const pct = sfxRaw === "%";
  const tot = toNum(overlay.total);
  const total = Number.isFinite(tot) && tot > 0 ? tot
    : pct ? 100 : value >= 0 && value <= 1 ? 1 : value >= 0 && value <= 10 ? 10 : value >= 0 && value <= 100 ? 100 : NaN;
  if (!Number.isFinite(total) || total <= 0) return null;
  const frac = clamp01(value / total);
  const zones = rowsOf(overlay.items, 8).filter((r) => r.label).slice(0, 6);
  const zn = zones.length >= 2 ? zones.length : 0;
  let bounds: number[] = Array.from({ length: zn }, (_, i) => (i + 1) / zn);
  if (zn) {
    const vs = zones.map((z) => z.value / total);
    const ok = vs.every((v, i) => Number.isFinite(v) && v > (i ? vs[i - 1] : 0) && v <= 1.0001);
    if (ok) bounds = vs.map((v, i) => (i === zn - 1 ? 1 : Math.min(1, v)));
  }
  let active = -1;
  for (let i = 0; i < zn; i++) {
    if (frac <= bounds[i] + 1e-9) {
      active = i;
      break;
    }
  }
  if (zn && active < 0) active = zn - 1;
  const ends = namesOf(overlay.label, 2);
  const endL = zn ? "" : clip(cap(ends[0] || "Low"), 16);
  const endR = zn ? "" : clip(cap(ends[1] || "High"), 16);
  const prefix = str(overlay.prefix);
  const BW = 1300 * k, BH = 34 * k, bandY = 196 * k;
  const MH = bandY + BH + 110 * k;
  const draw = ramp(frame, T(0.1), T(0.6), IN_OUT) * (1 - out);
  const mAt = T(0.75);
  const sp = frame < mAt ? 0 : spring({ frame: frame - mAt, fps, config: { damping: 13, stiffness: 40, mass: 1.1 } });
  const mf = Math.max(0, frac * sp);
  const mx = mf * BW;
  const mOn = ramp(frame, mAt - 4, 8) * (1 - out);
  const settleAt = mAt + T(1.1);
  const settled = ramp(frame, settleAt - 6, 10);
  const cycle = Math.max(20, T(1.2));
  const ping = frame > settleAt ? ((frame - settleAt) % cycle) / cycle : 0;
  const calloutX = Math.max(170 * k, Math.min(BW - 170 * k, mx));
  const grad = `linear-gradient(90deg, rgba(255,255,255,.16) 0%, ${alpha(accent, 0.5)} 55%, ${accent} 100%)`;
  const showTotal = !pct && Number.isFinite(tot) && tot > 0;
  const lens = bandY + BH / 2;
  const scaleCss: React.CSSProperties = { fontFamily: MONO, fontWeight: 500, fontSize: 24 * k, color: "rgba(255,255,255,.6)",
    whiteSpace: "nowrap" };
  return (
    <Card overlay={overlay}>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{ width: BW, display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 10 * k }}>
          {str(overlay.subtitle) ? (
            <Line text={clip(cap(overlay.subtitle), 44)} at={0} step={0.5} style={labelCss(k, 26, accent, "0.24em")} />
          ) : null}
          <Head text={overlay.text} accent={accent} size={58} at={2} />
          <div style={{ position: "relative", width: BW, height: MH, marginTop: 40 * k }}>
            <div style={{ position: "absolute", left: 0, top: bandY, width: BW, height: BH, borderRadius: BH / 2, background: grad,
              opacity: 0.34, clipPath: `inset(0 ${((1 - draw) * 100).toFixed(2)}% 0 0 round ${BH / 2}px)` }} />
            <div style={{ position: "absolute", left: 0, top: bandY, width: BW, height: BH, borderRadius: BH / 2, background: grad,
              clipPath: `inset(0 ${((1 - Math.min(draw, mf)) * 100).toFixed(2)}% 0 0 round ${BH / 2}px)` }} />
            <svg width={BW} height={MH} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
              {Array.from({ length: 51 }, (_, i) => {
                const t = i / 50;
                if (t > draw + 1e-6) return null;
                const x = t * BW;
                const major = i % 10 === 0;
                const on = mOn > 0.01 && x <= mx + 0.5;
                return <line key={i} x1={x} x2={x} y1={bandY - (major ? 24 : 12) * k} y2={bandY - 5 * k}
                  stroke={on ? accent : "rgba(255,255,255,.4)"} strokeWidth={(major ? 3 : 1.6) * k} />;
              })}
              {bounds.slice(0, -1).map((b, i) => (
                <line key={`z${i}`} x1={b * BW} x2={b * BW} y1={bandY - 8 * k} y2={bandY + BH + 48 * k}
                  stroke="rgba(255,255,255,.28)" strokeWidth={2 * k} opacity={draw >= b ? 1 : 0} />
              ))}
              <g opacity={mOn}>
                <line x1={mx} x2={mx} y1={124 * k} y2={bandY + BH + 12 * k} stroke="#fff" strokeWidth={4 * k} strokeLinecap="round" />
                {ping > 0 ? (
                  <circle cx={mx} cy={lens} r={(30 + 34 * ping) * k} fill="none" stroke={accent} strokeWidth={3 * k}
                    opacity={(1 - ping) * 0.8} />
                ) : null}
                <circle cx={mx} cy={lens} r={30 * k} fill="rgba(12,12,15,.35)" stroke="#fff" strokeWidth={4 * k} />
                <circle cx={mx} cy={lens} r={8 * k} fill={accent} />
              </g>
            </svg>
            <div style={{ position: "absolute", left: mx - 12 * k, top: 110 * k, width: 0, height: 0, opacity: mOn,
              borderLeft: `${12 * k}px solid transparent`, borderRight: `${12 * k}px solid transparent`,
              borderTop: `${14 * k}px solid ${alpha(accent, 0.55)}` }} />
            <div style={{ position: "absolute", left: calloutX, top: 0, transform: "translateX(-50%)", opacity: mOn,
              display: "flex", alignItems: "flex-end", gap: 12 * k, padding: `${14 * k}px ${26 * k}px ${10 * k}px`,
              borderRadius: 12 * k, background: "rgba(12,12,15,.74)", border: `${1.5 * k}px solid ${alpha(accent, 0.55)}`,
              whiteSpace: "nowrap" }}>
              <Rise at={mAt - 2}>
                <Odometer value={value} at={mAt} frames={T(1.2)} size={78 * k} color="#fff" prefix={prefix}
                  suffix={unitOf(sfxRaw)} suffixScale={0.5} suffixColor={accent} />
              </Rise>
              {showTotal ? (
                <Rise at={mAt + 6}>
                  <span style={{ ...scaleCss, fontSize: 26 * k, color: "rgba(255,255,255,.55)" }}>/ {fmt(total)}</span>
                </Rise>
              ) : null}
            </div>
            {zn ? zones.map((z, i) => {
              const b0 = i ? bounds[i - 1] : 0;
              const w = (bounds[i] - b0) * BW;
              const hot = i === active && settled > 0.5;
              const maxCh = Math.max(4, Math.floor(w / (26 * k * 0.62)));
              return (
                <div key={`zl${i}`} style={{ position: "absolute", left: b0 * BW, width: w, top: bandY + BH + 16 * k, display: "flex",
                  flexDirection: "column", alignItems: "center", gap: 6 * k }}>
                  <Rise at={T(0.35) + i * 3}>
                    <span style={labelCss(k, 26, hot ? accent : "rgba(255,255,255,.62)", "0.12em")}>{clip(cap(z.label), maxCh)}</span>
                  </Rise>
                  <div style={{ width: Math.min(w * 0.6, 90 * k) * (i === active ? settled : 0) * (1 - out), height: 3 * k,
                    background: accent }} />
                </div>
              );
            }) : (
              <>
                <div style={{ position: "absolute", left: 0, top: bandY + BH + 14 * k }}>
                  <Rise at={T(0.35)}><span style={scaleCss}>{prefix}{fmt(0)}</span></Rise>
                </div>
                <div style={{ position: "absolute", left: BW / 2 - 100 * k, width: 200 * k, top: bandY + BH + 14 * k, display: "flex",
                  justifyContent: "center" }}>
                  <Rise at={T(0.4)}><span style={scaleCss}>{prefix}{fmt(total / 2)}</span></Rise>
                </div>
                <div style={{ position: "absolute", right: 0, top: bandY + BH + 14 * k }}>
                  <Rise at={T(0.45)}><span style={scaleCss}>{prefix}{fmt(total)}{pct ? "%" : ""}</span></Rise>
                </div>
                <div style={{ position: "absolute", left: 0, top: bandY + BH + 52 * k }}>
                  <Rise at={T(0.4)}><span style={labelCss(k, 26, "rgba(255,255,255,.7)", "0.2em")}>{endL}</span></Rise>
                </div>
                <div style={{ position: "absolute", right: 0, top: bandY + BH + 52 * k }}>
                  <Rise at={T(0.45)}><span style={labelCss(k, 26, accent, "0.2em")}>{endR}</span></Rise>
                </div>
              </>
            )}
          </div>
        </div>
      </AbsoluteFill>
    </Card>
  );
};

// ================================================================== 7. quadrant matrix
/**
 * A 2x2 matrix: the centre cross draws out, four tiles pop in from the middle
 * with their quadrant names ("HIGH COST / LOW RELIABILITY"). A dot launches
 * from the origin and flies on a curve, leaving a fading trail, into the spot
 * set by items[0] (x axis name + score) and items[1] (y axis name + score) on
 * a 0..total scale (default 100, or 10 / 1 by size, symmetric when negative).
 * It lands with a shockwave, its quadrant floods with the accent from the dot
 * outward, cyan guides drop to the axes, and beside the matrix the subject
 * (label) and both scores roll above a verdict chip naming the quadrant.
 */
const Quadrant: Look = ({ overlay, accent: accentIn }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const T = useT();
  const end = useEnd();
  const out = useOut();
  const accent = hexOk(accentIn);
  const axes = rowsOf(overlay.items, 6).filter((r) => Number.isFinite(r.value)).slice(0, 2);
  if (axes.length < 2) return null;
  const ax = axes[0], ay = axes[1];
  const xName = clip(cap(ax.label) || "X AXIS", 16);
  const yName = clip(cap(ay.label) || "Y AXIS", 16);
  const subject = cap(overlay.label) || cap(overlay.highlight);
  const tot = toNum(overlay.total);
  const maxAbs = Math.max(Math.abs(ax.value), Math.abs(ay.value));
  let lo = 0;
  let hi = 100;
  if (Number.isFinite(tot) && tot > 0) hi = tot;
  else if (Math.min(ax.value, ay.value) < 0) {
    hi = niceCeil(maxAbs);
    lo = -hi;
  } else if (maxAbs <= 1) hi = 1;
  else if (maxAbs <= 10) hi = 10;
  else if (maxAbs <= 100) hi = 100;
  else hi = niceCeil(maxAbs);
  const mid = (lo + hi) / 2;
  const fx = clamp01((ax.value - lo) / (hi - lo));
  const fy = clamp01((ay.value - lo) / (hi - lo));
  const qx = ax.value >= mid ? 1 : 0;
  const qy = ay.value >= mid ? 1 : 0;
  const S = 600 * k, G = 10 * k, TS = (S - G) / 2, PAD = 26 * k;
  const px = PAD + fx * (S - 2 * PAD), py = PAD + (1 - fy) * (S - 2 * PAD);
  const tiles: Tile[] = [0, 1, 2, 3].map((t) => {
    const col = t % 2, row = Math.floor(t / 2);
    return { t, col, row, x: col * (TS + G), y: row * (TS + G), hot: col === qx && row === 1 - qy };
  });
  const flyAt = T(1.0), flyDur = T(0.8), landAt = flyAt + flyDur;
  const c0 = S / 2;
  const dx = px - c0, dy = py - c0;
  const dist = Math.hypot(dx, dy) || 1;
  const cpx = (c0 + px) / 2 - (dy / dist) * dist * 0.28;
  const cpy = (c0 + py) / 2 + (dx / dist) * dist * 0.28;
  const ft = ramp(frame, flyAt, flyDur, IN_OUT);
  const bx = (1 - ft) * (1 - ft) * c0 + 2 * (1 - ft) * ft * cpx + ft * ft * px;
  const by = (1 - ft) * (1 - ft) * c0 + 2 * (1 - ft) * ft * cpy + ft * ft * py;
  const trailD = `M${c0.toFixed(1)} ${c0.toFixed(1)} Q${cpx.toFixed(1)} ${cpy.toFixed(1)} ${px.toFixed(1)} ${py.toFixed(1)}`;
  const trailOp = 0.55 * (1 - ramp(frame, landAt + 6, T(0.6)));
  const landed = ramp(frame, landAt - 2, 6);
  const shock = ramp(frame, landAt, T(0.6));
  const flood = ramp(frame, landAt, T(0.6), IN_OUT) * (1 - out);
  const guides = ramp(frame, landAt + T(0.2), T(0.45), IN_OUT) * (1 - out);
  const dotS = ramp(frame, flyAt - 6, 10, BACK) * (1 - out);
  const float = Math.sin(frame / (fps * 0.6)) * 3 * k * landed;
  const pulseCycle = Math.max(20, T(1.1));
  const pulse = frame > landAt + 4 ? ((frame - landAt - 4) % pulseCycle) / pulseCycle : 0;
  const axisDraw = ramp(frame, T(0.2), T(0.6), IN_OUT) * (1 - out);
  const id = `cpqm${String(overlay.startFrame ?? 0)}`;
  const verdict = clip(`${qx ? "HIGH" : "LOW"} ${xName} · ${qy ? "HIGH" : "LOW"} ${yName}`, 38);
  /** The hot tile's names go to whichever corner is farthest from the dot; the others sit in their outer corners. */
  const cornerOf = (tile: Tile): number => {
    const outer = tile.row === 0 ? (tile.col === 0 ? 0 : 1) : (tile.col === 0 ? 2 : 3);
    if (!tile.hot) return outer;
    let bestC = outer;
    let bestD = -1;
    for (let c = 0; c < 4; c++) {
      const lx = tile.x + (c % 2 ? TS - 130 * k : 130 * k);
      const ly = tile.y + (c < 2 ? 45 * k : TS - 45 * k);
      const d = Math.hypot(lx - px, ly - py);
      if (d > bestD) {
        bestD = d;
        bestC = c;
      }
    }
    return bestC;
  };
  const tileCss: React.CSSProperties = { fontFamily: LABEL, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.1em",
    lineHeight: 1.1, whiteSpace: "nowrap" };
  const axisCss = (color: string): React.CSSProperties => ({ ...labelCss(k, 24, color, "0.16em"), fontWeight: 700 });
  return (
    <Card overlay={overlay}>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 40 * k }}>
          <Head text={overlay.text} accent={accent} size={56} />
          <div style={{ display: "flex", alignItems: "center", gap: 120 * k }}>
            <div style={{ position: "relative", width: S, height: S, marginLeft: 70 * k, marginBottom: 56 * k }}>
              <svg width={S} height={S} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
                <defs>
                  <radialGradient id={`${id}f`} gradientUnits="userSpaceOnUse" cx={px} cy={py} r={TS * 1.3}>
                    <stop offset="0" stopColor={accent} stopOpacity={0.5} />
                    <stop offset="1" stopColor={accent} stopOpacity={0.06} />
                  </radialGradient>
                  <clipPath id={`${id}c`}><circle cx={px} cy={py} r={Math.max(0.001, flood * TS * 1.6)} /></clipPath>
                </defs>
                {tiles.map((tile) => {
                  const p = ramp(frame, T(0.1) + tile.t * 3, T(0.5), BACK) * (1 - ramp(frame, end + 1 + tile.t, 10, IN));
                  const tcx = tile.x + TS / 2, tcy = tile.y + TS / 2;
                  return (
                    <g key={tile.t} transform={`translate(${tcx} ${tcy}) scale(${Math.max(0.001, p).toFixed(3)}) translate(${-tcx} ${-tcy})`}>
                      <rect x={tile.x} y={tile.y} width={TS} height={TS} rx={12 * k} fill="rgba(255,255,255,.045)"
                        stroke="rgba(255,255,255,.14)" strokeWidth={1.5 * k} />
                      {tile.hot && flood > 0.001 ? (
                        <rect x={tile.x} y={tile.y} width={TS} height={TS} rx={12 * k} fill={`url(#${id}f)`} stroke={accent}
                          strokeWidth={2.5 * k} clipPath={`url(#${id}c)`} />
                      ) : null}
                    </g>
                  );
                })}
                <line x1={c0 - axisDraw * c0} x2={c0 + axisDraw * c0} y1={c0} y2={c0} stroke="rgba(255,255,255,.55)"
                  strokeWidth={2.5 * k} />
                <line x1={c0} x2={c0} y1={c0 - axisDraw * c0} y2={c0 + axisDraw * c0} stroke="rgba(255,255,255,.55)"
                  strokeWidth={2.5 * k} />
                <g opacity={axisDraw > 0.97 ? 1 : 0}>
                  <path d={`M${S - 12 * k} ${c0 - 8 * k} L${S + 2 * k} ${c0} L${S - 12 * k} ${c0 + 8 * k}`} fill="none"
                    stroke="rgba(255,255,255,.7)" strokeWidth={2.5 * k} strokeLinejoin="round" />
                  <path d={`M${c0 - 8 * k} ${12 * k} L${c0} ${-2 * k} L${c0 + 8 * k} ${12 * k}`} fill="none"
                    stroke="rgba(255,255,255,.7)" strokeWidth={2.5 * k} strokeLinejoin="round" />
                </g>
                {ft > 0.001 ? (
                  <path d={trailD} fill="none" stroke={accent} strokeWidth={3 * k} strokeLinecap="round" pathLength={1}
                    strokeDasharray={`${ft.toFixed(4)} 1`} opacity={trailOp} />
                ) : null}
                <g opacity={guides}>
                  <line x1={px} x2={px} y1={py} y2={py + (S - py) * guides} stroke={CYAN} strokeWidth={2 * k}
                    strokeDasharray={`${6 * k} ${7 * k}`} />
                  <line x1={px} x2={px - px * guides} y1={py} y2={py} stroke={CYAN} strokeWidth={2 * k}
                    strokeDasharray={`${6 * k} ${7 * k}`} />
                </g>
                <g transform={`translate(${bx.toFixed(1)} ${(by + float).toFixed(1)}) scale(${Math.max(0.001, dotS).toFixed(3)})`}>
                  {pulse > 0 ? (
                    <circle r={(18 + 30 * pulse) * k} fill="none" stroke={accent} strokeWidth={3 * k} opacity={(1 - pulse) * 0.8} />
                  ) : null}
                  {shock > 0 && shock < 1 ? (
                    <circle r={(20 + 80 * shock) * k} fill="none" stroke="#fff" strokeWidth={3 * k} opacity={1 - shock} />
                  ) : null}
                  <circle r={17 * k} fill="#fff" stroke={accent} strokeWidth={6 * k} />
                </g>
              </svg>
              {tiles.map((tile) => {
                const c = cornerOf(tile);
                const right = c % 2 === 1;
                const bottom = c >= 2;
                const hotOn = tile.hot && landed > 0.5;
                const base = hotOn ? "#fff" : "rgba(255,255,255,.5)";
                const leadC = hotOn ? accent : "rgba(255,255,255,.66)";
                const at = T(0.4) + tile.t * 2;
                return (
                  <div key={`q${tile.t}`} style={{ position: "absolute", left: tile.x + 18 * k, width: TS - 36 * k,
                    top: bottom ? tile.y + TS - 74 * k : tile.y + 16 * k, display: "flex", flexDirection: "column",
                    alignItems: right ? "flex-end" : "flex-start", gap: 2 * k }}>
                    <Rise at={at}>
                      <span style={{ ...tileCss, color: base }}><span style={{ color: leadC }}>{tile.col ? "HIGH" : "LOW"}</span> {xName}</span>
                    </Rise>
                    <Rise at={at + 2}>
                      <span style={{ ...tileCss, color: base }}><span style={{ color: leadC }}>{tile.row === 0 ? "HIGH" : "LOW"}</span> {yName}</span>
                    </Rise>
                  </div>
                );
              })}
              <div style={{ position: "absolute", left: 0, top: S + 14 * k, width: S, display: "flex", justifyContent: "space-between",
                alignItems: "center" }}>
                <Rise at={T(0.5)}><span style={axisCss("rgba(255,255,255,.55)")}>LOW</span></Rise>
                <Rise at={T(0.55)}><span style={labelCss(k, 26, "rgba(255,255,255,.9)", "0.2em")}>{xName}</span></Rise>
                <Rise at={T(0.6)}><span style={axisCss("rgba(255,255,255,.55)")}>HIGH</span></Rise>
              </div>
              <div style={{ position: "absolute", left: -46 * k - S / 2, top: S / 2 - 18 * k, width: S, height: 36 * k,
                transform: "rotate(-90deg)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <Rise at={T(0.5)}><span style={axisCss("rgba(255,255,255,.55)")}>LOW</span></Rise>
                <Rise at={T(0.55)}><span style={labelCss(k, 26, "rgba(255,255,255,.9)", "0.2em")}>{yName}</span></Rise>
                <Rise at={T(0.6)}><span style={axisCss("rgba(255,255,255,.55)")}>HIGH</span></Rise>
              </div>
            </div>
            <div style={{ width: 560 * k, display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 12 * k }}>
              {subject ? wrapN(subject, 16, 2).map((ln, i) => (
                <Line key={i} text={ln} at={T(0.3) + i * 4} step={0.7} style={{ fontFamily: DISPLAY, fontSize: 70 * k, color: "#fff",
                  lineHeight: 1, letterSpacing: "0.03em", whiteSpace: "nowrap", textShadow: "0 6px 26px rgba(0,0,0,.5)" }} />
              )) : null}
              <Bar at={T(0.4)} width={90} color={accent} />
              {[ax, ay].map((a, i) => (
                <div key={`v${i}`} style={{ display: "flex", flexDirection: "column", gap: 2 * k, marginTop: 10 * k }}>
                  <Line text={i === 0 ? xName : yName} at={T(0.5) + i * 4} step={0.6}
                    style={labelCss(k, 26, "rgba(255,255,255,.62)", "0.2em")} />
                  <div style={{ display: "flex", alignItems: "flex-end", gap: 10 * k }}>
                    <Rise at={flyAt - 2 + i * 3}>
                      <Odometer value={a.value} at={flyAt + i * 3} frames={flyDur + T(0.3)} size={76 * k} color="#fff"
                        prefix={a.prefix} suffix={unitOf(a.suffix)} suffixScale={0.5} suffixColor={accent} />
                    </Rise>
                    {lo === 0 ? (
                      <Rise at={flyAt + 4 + i * 3}>
                        <span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 24 * k, color: "rgba(255,255,255,.5)" }}>/ {fmt(hi)}</span>
                      </Rise>
                    ) : null}
                  </div>
                </div>
              ))}
              <div style={{ marginTop: 18 * k, minHeight: 48 * k }}>
                <Chip text={verdict} at={landAt + T(0.25)} bg={accent} color={inkOn(accent)} size={26} />
              </div>
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </Card>
  );
};

// ================================================================== 8. then -> now morph
const glyphW = (ch: string): number => (/\d/.test(ch) ? 0.48 : ch === "," || ch === "." ? 0.2 : ch === " " ? 0 : 0.34);

/**
 * A number that rolls from one value straight into the next: `texts` are the
 * stage strings right-aligned to one length (the first all blank), `p` the
 * stage position (1.5 = halfway from texts[1] to texts[2]). Each digit column
 * spins from its old digit to its new one - up when the value grows, down when
 * it falls, the right-most column leading and spinning a full extra turn;
 * columns that appear or vanish grow or shrink in width.
 */
const MorphNumber: React.FC<{ texts: string[]; p: number; size: number; color: string }> = ({ texts, p, size, color }) => {
  if (!texts.length) return null;
  const L = texts[0].length;
  const a = Math.max(0, Math.min(texts.length - 1, Math.floor(p)));
  const b = Math.min(texts.length - 1, a + 1);
  const t = a === b ? 0 : clamp01(p - a);
  const va = toNum(texts[a]);
  const vb = toNum(texts[b]);
  const down = Number.isFinite(va) && Number.isFinite(vb) && vb < va;
  const cols: React.ReactNode[] = [];
  for (let c = 0; c < L; c++) {
    const ca = texts[a].charAt(c) || " ";
    const cb = texts[b].charAt(c) || " ";
    if (ca === " " && cb === " ") continue;
    const rc = L - 1 - c;
    const d = Math.min(0.3, rc * 0.07);
    const tc = clamp01((t - d) / (1 - d));
    const w = lerp(glyphW(ca), glyphW(cb), tc);
    const isA = /\d/.test(ca), isB = /\d/.test(cb);
    if (isA || isB) {
      const from = isA ? Number(ca) : 0;
      const to = isB ? Number(cb) : 0;
      const turns = rc === 0 && isA && isB && ca !== cb ? 1 : 0;
      const steps = down ? (from - to + 10) % 10 : (to - from + 10) % 10;
      const pos = from + tc * (down ? -1 : 1) * (turns * 10 + steps);
      const idx = ((pos % 10) + 10) % 10;
      const lo = Math.floor(idx);
      const f = idx - lo;
      cols.push(
        <span key={c} style={{ position: "relative", display: "inline-block", width: `${w.toFixed(3)}em`, height: size,
          overflow: "hidden", opacity: isA && isB ? 1 : isA ? 1 - tc : tc }}>
          <span style={{ position: "absolute", left: 0, right: 0, top: 0, textAlign: "center",
            transform: `translateY(${(-f * size).toFixed(2)}px)` }}>{lo % 10}</span>
          <span style={{ position: "absolute", left: 0, right: 0, top: 0, textAlign: "center",
            transform: `translateY(${((1 - f) * size).toFixed(2)}px)` }}>{(lo + 1) % 10}</span>
        </span>,
      );
    } else {
      cols.push(
        <span key={c} style={{ position: "relative", display: "inline-block", width: `${w.toFixed(3)}em`, height: size,
          overflow: "hidden" }}>
          {ca !== " " ? (
            <span style={{ position: "absolute", left: 0, right: 0, top: 0, textAlign: "center", opacity: ca === cb ? 1 : 1 - tc }}>{ca}</span>
          ) : null}
          {cb !== " " && cb !== ca ? (
            <span style={{ position: "absolute", left: 0, right: 0, top: 0, textAlign: "center", opacity: tc }}>{cb}</span>
          ) : null}
        </span>,
      );
    }
  }
  return (
    <span style={{ display: "inline-flex", alignItems: "flex-start", fontFamily: DISPLAY, fontSize: size, lineHeight: 1, color,
      height: size, whiteSpace: "nowrap" }}>{cols}</span>
  );
};

/** Stacked one-line labels rolling up through a mask as `p` (a stage index) advances. */
const Roller: React.FC<{ items: string[]; p: number; height: number; width: number; style: React.CSSProperties;
  colors?: string[] }> = ({ items, p, height, width, style, colors }) => (
  <div style={{ position: "relative", width, height, overflow: "hidden" }}>
    {items.map((t, i) => {
      const off = i - p;
      if (!t || Math.abs(off) >= 1.02) return null;
      return (
        <div key={i} style={{ position: "absolute", left: 0, top: 0, height, lineHeight: `${height}px`, whiteSpace: "nowrap",
          transform: `translateY(${(off * 108).toFixed(2)}%)`, ...style,
          color: colors && colors[i] ? colors[i] : style.color }}>{t}</div>
      );
    })}
  </div>
);

/**
 * THEN -> NOW as one shape changing. A disc sized by area pops in with the
 * first item's value rolling in beside it; then the disc morphs to each next
 * item (2-4 stages) while the digits roll straight from one number into the
 * next and the era label (item label) and note (item text) roll over. The
 * THEN size stays as a dashed ghost ring, the band lost or gained between
 * them hatched red or green, a timeline marker walks the stages, and the
 * change from first to last lands in a red / green chip.
 */
const ThenNow: Look = ({ overlay, accent: accentIn }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const T = useT();
  const out = useOut();
  const accent = hexOk(accentIn);
  const st = rowsOf(overlay.items, 8).filter((r) => Number.isFinite(r.value)).slice(0, 4);
  if (st.length < 2) return null;
  const n = st.length;
  const first = st[0], last = st[n - 1];
  const sfxRaw = str(overlay.suffix) || last.suffix || first.suffix;
  const unit = unitOf(sfxRaw).trim();
  const prefix = str(overlay.prefix) || last.prefix || first.prefix;
  const allInt = st.every((s) => Number.isInteger(s.value));
  const maxAbs = Math.max(...st.map((s) => Math.abs(s.value)), 1e-9);
  const dec = allInt ? 0 : maxAbs >= 100 ? 0 : 1;
  const yearish = allInt && !sfxRaw && st.every((s) => s.value >= 1500 && s.value <= 2100);
  const fmtD = (v: number) => `${v < 0 ? "−" : ""}${Math.abs(v).toLocaleString("en-US",
    { minimumFractionDigits: dec, maximumFractionDigits: dec, useGrouping: !yearish })}`;
  const raw = ["", ...st.map((s) => fmtD(s.value))];
  const L = Math.max(...raw.map((s) => s.length));
  const texts = raw.map((s) => s.padStart(L, " "));
  const numSize = (L <= 4 ? 190 : L <= 6 ? 160 : 128) * k;
  const introAt = T(0.3), introDur = T(0.75);
  const stepsAt = introAt + introDur + T(0.45);
  const gap = T(0.22);
  const budget = Math.round(dur * 0.64) - stepsAt;
  const stepDur = Math.max(10, Math.min(T(1.0), Math.round((budget - (n - 2) * gap) / (n - 1))));
  const stepAt = (j: number) => stepsAt + (j - 1) * (stepDur + gap);
  let p = ramp(frame, introAt, introDur, IN_OUT);
  for (let j = 1; j < n; j++) p += ramp(frame, stepAt(j), stepDur, IN_OUT);
  const doneAt = stepAt(n - 1) + stepDur;
  const morph = clamp01((p - 1) / (n - 1));
  const RMAX = 245 * k;
  const radii = st.map((s) => Math.max(22 * k, RMAX * Math.sqrt(Math.abs(s.value) / maxAbs)));
  const a0 = Math.max(0, Math.min(n - 1, Math.floor(p - 1)));
  const rCur = p < 1 ? radii[0] * Math.max(0, ramp(frame, introAt, T(0.6), BACK))
    : lerp(radii[a0], radii[Math.min(n - 1, a0 + 1)], clamp01(p - 1 - a0));
  const rNow = Math.max(0.001, rCur * (1 - out));
  const r0 = radii[0] * (1 - out);
  const shrink = radii[n - 1] < radii[0];
  const col = shrink ? RED : GREEN;
  const bandOp = clamp01(morph * 2) * (1 - out);
  const DX = 280 * k, DY = 270 * k;
  const f1 = (v: number) => v.toFixed(1);
  const circ = (rr: number) =>
    `M${f1(DX - rr)} ${f1(DY)} a${f1(rr)} ${f1(rr)} 0 1 0 ${f1(2 * rr)} 0 a${f1(rr)} ${f1(rr)} 0 1 0 ${f1(-2 * rr)} 0 Z`;
  const R1 = Math.max(r0, rNow), R2 = Math.min(r0, rNow);
  const id = `cptn${String(overlay.startFrame ?? 0)}`;
  const pctChg = first.value !== 0 ? ((last.value - first.value) / Math.abs(first.value)) * 100 : NaN;
  const chgTxt = Number.isFinite(pctChg) && Math.abs(pctChg) >= 0.05
    ? `${pctChg < 0 ? "▼" : "▲"} ${Math.abs(pctChg) >= 10 ? Math.round(Math.abs(pctChg)) : Math.abs(pctChg).toFixed(1)}%` : "";
  const eras = st.map((s) => clip(cap(s.label), 18));
  const eraColors = st.map((_, i) => (i === n - 1 ? accent : i === 0 ? "rgba(255,255,255,.72)" : "#fff"));
  const descs = st.map((s) => clip(s.text, 36));
  const hasDesc = descs.some(Boolean);
  const kicker = clip(cap(overlay.subtitle), 40);
  const TW = 1100 * k;
  const tl = ramp(frame, T(0.15), T(0.6), IN_OUT) * (1 - out);
  const xs = st.map((_, i) => (i / (n - 1)) * TW);
  const mX = clamp01((p - 1) / (n - 1)) * TW;
  const markerOn = ramp(frame, introAt, T(0.5), BACK) * (1 - out);
  return (
    <Card overlay={overlay}>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 30 * k, width: 1240 * k }}>
          <Head text={overlay.text} accent={accent} size={56} center />
          <div style={{ display: "flex", alignItems: "center", gap: 60 * k, width: 1240 * k }}>
            <div style={{ position: "relative", width: 560 * k, height: 540 * k, flexShrink: 0 }}>
              <svg width={560 * k} height={540 * k} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
                <defs>
                  <pattern id={`${id}h`} width={14 * k} height={14 * k} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                    <rect width={5 * k} height={14 * k} fill={col} opacity={0.6} />
                  </pattern>
                  <radialGradient id={`${id}s`} cx="35%" cy="30%" r="75%">
                    <stop offset="0" stopColor="#fff" stopOpacity={0.38} />
                    <stop offset="1" stopColor="#fff" stopOpacity={0} />
                  </radialGradient>
                </defs>
                {bandOp > 0.001 && R1 - R2 > 1 ? (
                  <path d={`${circ(R1)} ${circ(R2)}`} fill={`url(#${id}h)`} fillRule="evenodd" opacity={bandOp} />
                ) : null}
                <circle cx={DX} cy={DY} r={rNow} fill="#d9dbe0" />
                <circle cx={DX} cy={DY} r={rNow} fill={accent} opacity={morph} />
                <circle cx={DX} cy={DY} r={rNow} fill={`url(#${id}s)`} />
                <circle cx={DX} cy={DY} r={rNow} fill="none" stroke="rgba(255,255,255,.55)" strokeWidth={2 * k} />
                {st.slice(0, n - 1).map((_, i) => {
                  const g = clamp01((p - (i + 1)) * 5) * (1 - out) * (i === 0 ? 0.85 : 0.45);
                  if (g <= 0.001) return null;
                  return (
                    <circle key={`g${i}`} cx={DX} cy={DY} r={Math.max(0.001, radii[i] * (1 - out))} fill="none"
                      stroke="rgba(255,255,255,.8)" strokeWidth={2.5 * k} strokeDasharray={`${8 * k} ${8 * k}`} opacity={g} />
                  );
                })}
              </svg>
            </div>
            <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 8 * k }}>
              {kicker ? <Line text={kicker} at={T(0.1)} step={0.5} style={labelCss(k, 26, accent, "0.24em")} /> : null}
              <Exit>
                <Roller items={eras} p={p - 1} height={50 * k} width={600 * k} colors={eraColors}
                  style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 40 * k, letterSpacing: "0.14em", color: "#fff" }} />
              </Exit>
              <Exit delay={1}>
                <div style={{ display: "flex", alignItems: "flex-start", height: numSize * 1.04 }}>
                  {prefix ? (
                    <Rise at={introAt}>
                      <span style={{ fontFamily: DISPLAY, fontSize: numSize, lineHeight: 1, color: "rgba(255,255,255,.8)" }}>{prefix}</span>
                    </Rise>
                  ) : null}
                  <MorphNumber texts={texts} p={p} size={numSize} color="#fff" />
                  {unit ? (
                    <Rise at={introAt + 6} style={{ marginLeft: numSize * 0.05, marginTop: numSize * 0.06 }}>
                      <span style={{ fontFamily: DISPLAY, fontSize: numSize * 0.42, lineHeight: 1, color: accent }}>{unit}</span>
                    </Rise>
                  ) : null}
                </div>
              </Exit>
              {hasDesc ? (
                <Exit delay={2}>
                  <Roller items={descs} p={p - 1} height={42 * k} width={600 * k}
                    style={{ fontFamily: INTER, fontWeight: 700, fontSize: 30 * k, color: "rgba(255,255,255,.74)" }} />
                </Exit>
              ) : null}
              <div style={{ marginTop: 14 * k, minHeight: 52 * k }}>
                <Chip text={chgTxt} at={doneAt + 2} bg={pctChg < 0 ? RED : GREEN} color="#fff" size={32} />
              </div>
            </div>
          </div>
          <div style={{ position: "relative", width: TW, height: 96 * k }}>
            <svg width={TW} height={40 * k} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
              <line x1={0} x2={TW * tl} y1={20 * k} y2={20 * k} stroke="rgba(255,255,255,.25)" strokeWidth={3 * k} />
              <line x1={0} x2={Math.min(mX, TW * tl)} y1={20 * k} y2={20 * k} stroke={accent} strokeWidth={3 * k} />
              {xs.map((x, i) => {
                const passed = p >= i + 1 - 0.02;
                const on = ramp(frame, T(0.2) + i * 3, T(0.4), BACK) * (1 - out);
                return (
                  <circle key={i} cx={x} cy={20 * k} r={Math.max(0.001, 9 * k * on)} fill={passed ? accent : INK}
                    stroke={passed ? accent : "rgba(255,255,255,.6)"} strokeWidth={2.5 * k} />
                );
              })}
              <circle cx={mX} cy={20 * k} r={Math.max(0.001, 14 * k * markerOn)} fill="#fff" stroke={accent} strokeWidth={4 * k} />
            </svg>
            {xs.map((x, i) => (
              <div key={`l${i}`} style={{ position: "absolute", left: x - 110 * k, width: 220 * k, top: 42 * k, display: "flex",
                justifyContent: "center" }}>
                <Rise at={T(0.3) + i * 3}>
                  <span style={labelCss(k, 26, p >= i + 1 - 0.02 ? "#fff" : "rgba(255,255,255,.55)", "0.12em")}>
                    {clip(cap(st[i].label), 14)}
                  </span>
                </Rise>
              </div>
            ))}
          </div>
        </div>
      </AbsoluteFill>
    </Card>
  );
};

// ================================================================== 9. mirror bars
/**
 * A butterfly chart: a shared column of category labels in the middle, one
 * group's bars growing left and the other's growing right from it, row after
 * row, each value rolling at its bar's end; a light sheen passes along the
 * bars while they hold, and at the end they retract into the column. items:
 * label = category, value = left group, text = right group as a number;
 * group names in label "A|B" (or subtitle).
 */
const MirrorBars: Look = ({ overlay, accent: accentIn }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const T = useT();
  const end = useEnd();
  const out = useOut();
  const accent = hexOk(accentIn);
  const rows = rowsOf(overlay.items, 12)
    .map((r) => ({ label: r.label, left: r.value, right: toNum(r.text) }))
    .filter((r) => r.label.length > 0 && Number.isFinite(r.left) && Number.isFinite(r.right))
    .slice(0, 7);
  if (rows.length < 2) return null;
  const n = rows.length;
  let groups = namesOf(overlay.label, 2);
  if (groups.length < 2) groups = namesOf(overlay.subtitle, 2);
  const gL = clip(cap(groups[0] || ""), 18);
  const gR = clip(cap(groups[1] || ""), 18);
  const max = Math.max(...rows.map((r) => Math.max(Math.abs(r.left), Math.abs(r.right))), 1e-9);
  const unit = unitOf(overlay.suffix);
  const prefix = str(overlay.prefix);
  const W = 1500 * k, CW = 250 * k;
  const xl = (W - CW) / 2, xr = (W + CW) / 2;
  const BL = 470 * k;
  const RH = (n <= 4 ? 86 : n === 5 ? 76 : 66) * k;
  const BT = RH * 0.56;
  const HH = (gL || gR ? 78 : 22) * k;
  const H = HH + n * RH;
  const spine = ramp(frame, T(0.05), T(0.6), IN_OUT) * (1 - out);
  const rowAt = (i: number) => T(0.35) + i * T(0.09);
  const growDur = T(0.95);
  const settleAt = rowAt(n - 1) + growDur;
  const cycle = Math.max(40, T(2.2));
  const SH = 150 * k;
  const numSize = RH * 0.5;
  return (
    <Card overlay={overlay}>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 30 * k }}>
          <Head text={overlay.text} accent={accent} size={56} center />
          <div style={{ position: "relative", width: W, height: H }}>
            <div style={{ position: "absolute", left: xl, top: HH - 10 * k, width: CW, height: (n * RH + 20 * k) * spine,
              background: "rgba(255,255,255,.045)", borderLeft: `${1.5 * k}px solid rgba(255,255,255,.18)`,
              borderRight: `${1.5 * k}px solid rgba(255,255,255,.18)`, boxSizing: "border-box" }} />
            {gL ? (
              <div style={{ position: "absolute", right: W - xl + 16 * k, top: 0, height: HH - 24 * k, display: "flex",
                alignItems: "center", gap: 12 * k }}>
                <Line text={gL} at={T(0.15)} step={0.7} style={labelCss(k, 32, "#fff", "0.14em")} />
                <div style={{ width: 18 * k, height: 18 * k, borderRadius: 4 * k, background: "#d9dbe0", transform: `scale(${spine})` }} />
              </div>
            ) : null}
            {gR ? (
              <div style={{ position: "absolute", left: xr + 16 * k, top: 0, height: HH - 24 * k, display: "flex",
                alignItems: "center", gap: 12 * k }}>
                <div style={{ width: 18 * k, height: 18 * k, borderRadius: 4 * k, background: accent, transform: `scale(${spine})` }} />
                <Line text={gR} at={T(0.2)} step={0.7} style={labelCss(k, 32, accent, "0.14em")} />
              </div>
            ) : null}
            {rows.map((r, i) => {
              const at = rowAt(i);
              const g = ramp(frame, at + 3, growDur, IN_OUT) * (1 - ramp(frame, end - 2 + (n - 1 - i) * 0.8, 10, IN));
              const lenL = (Math.abs(r.left) / max) * BL * g;
              const lenR = (Math.abs(r.right) / max) * BL * g;
              const top = HH + i * RH;
              const yb = top + (RH - BT) / 2;
              const ph = frame - settleAt - i * 3;
              const sw = ph >= 0 ? (ph % cycle) / cycle : -1;
              const shL = sw >= 0 ? lenL - sw * (lenL + SH) : -9999;
              const shR = sw >= 0 ? sw * (lenR + SH) - SH : -9999;
              const bigL = Math.abs(r.left) > Math.abs(r.right);
              const bigR = Math.abs(r.right) > Math.abs(r.left);
              return (
                <React.Fragment key={i}>
                  {lenL > 0.5 ? (
                    <div style={{ position: "absolute", left: xl - lenL, top: yb, width: lenL, height: BT,
                      borderRadius: `${6 * k}px 0 0 ${6 * k}px`,
                      backgroundImage: "linear-gradient(90deg, rgba(255,255,255,0), rgba(255,255,255,.55), rgba(255,255,255,0)), linear-gradient(270deg, #f3f4f7, #9ea1a9)",
                      backgroundSize: `${SH}px 100%, 100% 100%`, backgroundRepeat: "no-repeat",
                      backgroundPosition: `${shL.toFixed(1)}px 0px, 0px 0px` }} />
                  ) : null}
                  {lenR > 0.5 ? (
                    <div style={{ position: "absolute", left: xr, top: yb, width: lenR, height: BT,
                      borderRadius: `0 ${6 * k}px ${6 * k}px 0`,
                      backgroundImage: `linear-gradient(90deg, rgba(255,255,255,0), rgba(255,255,255,.45), rgba(255,255,255,0)), linear-gradient(90deg, ${alpha(accent, 0.72)}, ${accent})`,
                      backgroundSize: `${SH}px 100%, 100% 100%`, backgroundRepeat: "no-repeat",
                      backgroundPosition: `${shR.toFixed(1)}px 0px, 0px 0px` }} />
                  ) : null}
                  <div style={{ position: "absolute", right: W - (xl - lenL) + 14 * k, top, height: RH, display: "flex",
                    alignItems: "center" }}>
                    <Rise at={at + 4}>
                      <LiteRoll value={r.left} at={at + 4} frames={growDur} size={numSize}
                        color={bigL ? "#fff" : "rgba(255,255,255,.72)"} prefix={prefix} suffix={unit}
                        suffixColor="rgba(255,255,255,.6)" />
                    </Rise>
                  </div>
                  <div style={{ position: "absolute", left: xr + lenR + 14 * k, top, height: RH, display: "flex",
                    alignItems: "center" }}>
                    <Rise at={at + 6}>
                      <LiteRoll value={r.right} at={at + 6} frames={growDur} size={numSize}
                        color={bigR ? "#fff" : "rgba(255,255,255,.72)"} prefix={prefix} suffix={unit} suffixColor={accent} />
                    </Rise>
                  </div>
                  <div style={{ position: "absolute", left: xl, width: CW, top, height: RH, display: "flex", alignItems: "center",
                    justifyContent: "center" }}>
                    <Rise at={at}>
                      <span style={labelCss(k, 30, "#fff", "0.1em")}>{clip(cap(r.label), 13)}</span>
                    </Rise>
                  </div>
                </React.Fragment>
              );
            })}
          </div>
        </div>
      </AbsoluteFill>
    </Card>
  );
};

// ================================================================== 10. photo versus (own backdrop)
/**
 * Two pictures squared up. On a dark stage two photo cards swing in from the
 * sides, turned toward each other in 3D (outer edges near, inner edges far),
 * a light sweeping across each. A V and an S slam in from opposite corners
 * and collide between them - a shockwave, streaks and a short camera shake -
 * then an accent divider draws through the gap and the letters breathe.
 * Name plates (items[i].label, or label "A|B") wipe open under each card with
 * a value or note (item value / text) beneath. At the end the plates wipe
 * shut, the letters implode and the cards swing away. media[0], media[1]
 * (one picture is split into its left and right halves).
 */
const PhotoVersus: Look = ({ overlay, accent: accentIn }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H, fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const T = useT();
  const end = useEnd();
  const out = useOut();
  const hold = useHold();
  const accent = hexOk(accentIn);
  const pics = stills(overlay, 2);
  if (!pics.length) return null;
  const same = pics.length < 2;
  const srcA = pics[0];
  const srcB = pics[1] || pics[0];
  const rows = rowsOf(overlay.items, 6);
  const alt = namesOf(overlay.label, 2);
  const nameA = clip(cap((rows[0] && rows[0].label) || alt[0] || ""), 18);
  const nameB = clip(cap((rows[1] && rows[1].label) || alt[1] || ""), 18);
  const title = str(overlay.text);
  const CW = 600 * k, CH = 620 * k;
  const cyC = (title ? 560 : 520) * k;
  const top = cyC - CH / 2;
  const cxA = W / 2 - 430 * k, cxB = W / 2 + 430 * k;
  const pa = ramp(frame, 0, T(0.7)), pb = ramp(frame, 4, T(0.7));
  const qa = ramp(frame, end + 1, 11, IN), qb = ramp(frame, end + 2, 11, IN);
  const angA = lerp(58, 16, pa) + 50 * qa;
  const angB = -(lerp(58, 16, pb) + 50 * qb);
  const offA = -(1 - pa) * 760 * k - qa * 700 * k;
  const offB = (1 - pb) * 760 * k + qb * 700 * k;
  const life = interpolate(frame, [0, Math.max(1, dur)], [0, 1], clamp);
  const vsAt = T(0.55), vsDur = Math.max(6, T(0.26));
  const hit = vsAt + vsDur;
  const vsIn = ramp(frame, vsAt, vsDur, IN);
  const vsOut = ramp(frame, end, 10, IN);
  const vsOn = ramp(frame, vsAt, 3);
  const shock = frame >= hit ? ramp(frame, hit, T(0.55)) : 0;
  const shakeEnv = frame >= hit ? interpolate(frame, [hit, hit + 9], [1, 0], clamp) : 0;
  const shakeX = Math.sin(frame * 2.7) * 10 * k * shakeEnv;
  const shakeY = Math.cos(frame * 3.3) * 7 * k * shakeEnv;
  const breathe = 1 + 0.025 * Math.sin((frame - hit) / (fps * 0.4)) * ramp(frame, hit + 6, 10);
  const divider = ramp(frame, hit, T(0.5), IN_OUT) * (1 - out);
  const glow = ramp(frame, hit - 2, 10) * (1 - out);
  const bgFade = ramp(frame, 0, 8) * (1 - ramp(frame, dur - 7, 6));
  const sheenA = interpolate(frame, [T(0.75), T(0.75) + 22], [-130, 130], clamp);
  const sheenB = interpolate(frame, [T(0.85), T(0.85) + 22], [-130, 130], clamp);
  const vsScale = lerp(1.5, 1, vsIn) * breathe * (1 - vsOut);
  const vsCss: React.CSSProperties = { position: "absolute", left: W / 2, top: cyC, fontFamily: DISPLAY, fontSize: 180 * k,
    lineHeight: 1, opacity: vsOn * (vsScale > 0.02 ? 1 : 0), textShadow: `0 ${10 * k}px ${40 * k}px rgba(0,0,0,.65)` };
  // The letters start beyond opposite corners of the frame and accelerate into each other.
  const vT = `translate(-50%, -50%) translate(${(lerp(-720, -44, vsIn) * k).toFixed(1)}px, ${(lerp(-640, -6, vsIn) * k).toFixed(1)}px) rotate(${(lerp(-26, -4, vsIn) - 30 * vsOut).toFixed(2)}deg) scale(${Math.max(0.001, vsScale).toFixed(3)})`;
  const sT = `translate(-50%, -50%) translate(${(lerp(720, 44, vsIn) * k).toFixed(1)}px, ${(lerp(640, 6, vsIn) * k).toFixed(1)}px) rotate(${(lerp(26, -4, vsIn) + 30 * vsOut).toFixed(2)}deg) scale(${Math.max(0.001, vsScale).toFixed(3)})`;

  const card = (src: string, cxC: number, ang: number, off: number, p: number, q: number, right: boolean, sheen: number) => (
    <div style={{ position: "absolute", left: cxC - CW / 2 + off, top, width: CW, height: CH, perspective: 1700 * k,
      opacity: Math.min(1, p * 3) * (q > 0.97 ? 0 : 1) }}>
      <div style={{ position: "absolute", left: 0, top: 0, width: CW, height: CH, transform: `rotateY(${ang.toFixed(2)}deg)`,
        borderRadius: 14 * k, overflow: "hidden", background: INK, boxSizing: "border-box",
        border: `${2.5 * k}px solid ${right ? accent : "rgba(255,255,255,.85)"}`,
        boxShadow: `0 ${40 * k}px ${90 * k}px rgba(0,0,0,.6)` }}>
        <SafeImg src={src} style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "100%", objectFit: "cover",
          objectPosition: same ? (right ? "74% 50%" : "26% 50%") : "50% 50%",
          transform: `scale(${(1.08 + 0.06 * life).toFixed(4)}) translateX(${((right ? -1 : 1) * (life - 0.5) * 16 * k).toFixed(2)}px)`,
          filter: right ? "saturate(1.06) contrast(1.05)" : "grayscale(.3) contrast(1.06) brightness(.93)" }} />
        <div style={{ position: "absolute", left: 0, top: 0, right: 0, bottom: 0,
          background: "linear-gradient(180deg, rgba(0,0,0,.28) 0%, rgba(0,0,0,0) 28%, rgba(0,0,0,0) 58%, rgba(0,0,0,.62) 100%)" }} />
        <div style={{ position: "absolute", left: 0, top: 0, right: 0, bottom: 0, transform: `translateX(${sheen.toFixed(2)}%)`,
          background: "linear-gradient(105deg, rgba(255,255,255,0) 40%, rgba(255,255,255,.18) 50%, rgba(255,255,255,0) 60%)" }} />
      </div>
    </div>
  );

  const plate = (name: string, row: Row | undefined, cxP: number, at: number, right: boolean) => {
    if (!name) return null;
    const p = ramp(frame, at, T(0.4), IN_OUT);
    const q = ramp(frame, end, 10, IN);
    const ins = Math.max(1 - p, q) * 50;
    const hasVal = row ? Number.isFinite(row.value) : false;
    const desc = row && !hasVal ? clip(cap(row.text), 34) : "";
    return (
      <div style={{ position: "absolute", left: cxP - 300 * k, width: 600 * k, top: top + CH - 38 * k, display: "flex",
        flexDirection: "column", alignItems: "center", gap: 12 * k }}>
        <div style={{ background: right ? accent : "#f4f4f6", padding: `${10 * k}px ${30 * k}px ${6 * k}px`, borderRadius: 6 * k,
          clipPath: `inset(0 ${ins.toFixed(2)}% 0 ${ins.toFixed(2)}%)` }}>
          <Rise at={at + 4}>
            <span style={{ display: "block", fontFamily: DISPLAY, fontSize: 56 * k, lineHeight: 1, letterSpacing: "0.04em",
              color: right ? inkOn(accent) : INK, whiteSpace: "nowrap" }}>{name}</span>
          </Rise>
        </div>
        {row && hasVal ? (
          <Rise at={at + 8}>
            <Odometer value={row.value} at={at + 8} frames={T(0.9)} size={52 * k} color="#fff"
              prefix={row.prefix || str(overlay.prefix)} suffix={unitOf(row.suffix || overlay.suffix)} suffixScale={0.5}
              suffixColor={right ? accent : "rgba(255,255,255,.7)"} />
          </Rise>
        ) : desc ? (
          <Rise at={at + 8}><span style={labelCss(k, 28, "rgba(255,255,255,.8)", "0.12em")}>{desc}</span></Rise>
        ) : null}
      </div>
    );
  };

  return (
    <AbsoluteFill style={{ opacity: bgFade, overflow: "hidden" }}>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 42%, #22232a 0%, #111216 55%, #060607 100%)" }} />
      <AbsoluteFill style={{ backgroundImage: `repeating-linear-gradient(115deg, rgba(255,255,255,.022) 0px, rgba(255,255,255,.022) ${1 * k}px, rgba(0,0,0,0) ${1 * k}px, rgba(0,0,0,0) ${13 * k}px)` }} />
      <AbsoluteFill style={{ opacity: glow,
        background: `radial-gradient(ellipse 30% 55% at 50% ${((cyC / H) * 100).toFixed(1)}%, ${alpha(accent, 0.2)} 0%, rgba(0,0,0,0) 70%)` }} />
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${300 * k}px rgba(0,0,0,.85)` }} />
      <AbsoluteFill style={{ transform: `translate(${shakeX.toFixed(2)}px, ${shakeY.toFixed(2)}px) scale(${hold})` }}>
        {title ? (
          <div style={{ position: "absolute", left: 0, right: 0, top: 84 * k, display: "flex", justifyContent: "center" }}>
            <Head text={title} accent={accent} size={56} center />
          </div>
        ) : null}
        <div style={{ position: "absolute", left: W / 2 - 1.5 * k, top: cyC - (CH / 2 + 30 * k) * divider, width: 3 * k,
          height: (CH + 60 * k) * divider, background: `linear-gradient(180deg, ${alpha(accent, 0)}, ${accent} 50%, ${alpha(accent, 0)})` }} />
        {card(srcA, cxA, angA, offA, pa, qa, false, sheenA)}
        {card(srcB, cxB, angB, offB, pb, qb, true, sheenB)}
        {shock > 0 && shock < 1 ? (
          <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
            <circle cx={W / 2} cy={cyC} r={(60 + 250 * shock) * k} fill="none" stroke={accent}
              strokeWidth={(8 * (1 - shock) + 1) * k} opacity={1 - shock} />
            <circle cx={W / 2} cy={cyC} r={(40 + 120 * shock) * k} fill="#fff" opacity={Math.max(0, 0.55 - shock * 1.6)} />
            {Array.from({ length: 12 }, (_, i) => {
              const ang = (i / 12) * Math.PI * 2 + 0.2;
              const len = (40 + 60 * seeded(i + 3)) * k * (1 - shock);
              const r1 = (90 + 200 * shock) * k;
              return (
                <line key={i} x1={W / 2 + Math.cos(ang) * r1} y1={cyC + Math.sin(ang) * r1}
                  x2={W / 2 + Math.cos(ang) * (r1 + len)} y2={cyC + Math.sin(ang) * (r1 + len)}
                  stroke="#fff" strokeWidth={3 * k} strokeLinecap="round" opacity={1 - shock} />
              );
            })}
          </svg>
        ) : null}
        <div style={{ ...vsCss, color: "#fff", transform: vT }}>V</div>
        <div style={{ ...vsCss, color: accent, transform: sT }}>S</div>
        {plate(nameA, rows[0], cxA, T(0.95), false)}
        {plate(nameB, rows[1], cxB, T(1.05), true)}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== exports
/** A malformed overlay (not an object) renders nothing instead of crashing the render. */
const safe = (Inner: Look): Look => {
  const Guarded: Look = ({ overlay, accent }) =>
    overlay && typeof overlay === "object"
      ? <Inner overlay={overlay} accent={typeof accent === "string" && accent ? accent : GOLD} /> : null;
  return Guarded;
};

export const LOOKS: Record<string, Look> = {
  "cp-split-statement": safe(SplitStatement),
  "cp-balance-scale": safe(BalanceScale),
  "cp-venn": safe(Venn),
  "cp-tick-table": safe(TickTable),
  "cp-myth-fact": safe(MythFact),
  "cp-spectrum-marker": safe(Spectrum),
  "cp-quadrant-matrix": safe(Quadrant),
  "cp-then-now-morph": safe(ThenNow),
  "cp-mirror-bars": safe(MirrorBars),
  "cp-photo-versus": safe(PhotoVersus),
};
