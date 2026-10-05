import React from "react";
import { AbsoluteFill, Easing, useCurrentFrame, useVideoConfig } from "remotion";
import { INTER, LABEL } from "../fonts";
import type { Overlay } from "../../types";
import { Scrim, lines, ramp, useHold, useK } from "../pro/ProGraphics";

/**
 * Counting numbers (family "ct-"): every figure COUNTS UP from zero in
 * tabular figures with thousands separators and a soft eased landing, the
 * way an editor keys a number in After Effects. The width of the finished
 * number is reserved up front, so nothing shuffles sideways while it counts.
 *
 *   ct-clean-count     the figure counts up big and clean, a thin accent line
 *                      draws beneath it, the label rises under the line
 *   ct-rolling-digits  slot-machine drums, one per digit, that land one by one
 *                      left to right, each tile flashing the accent as it lands
 *   ct-bar-percent     a percent counting while a horizontal bar fills with it
 *   ct-ring-pro        a ring gauge with a gradient stroke filling round the
 *                      count, a tick bezel lighting as the arc passes
 *   ct-dot-grid        100 people in a 10 x 10 grid filling to the percent,
 *                      the count and "N in every 100" beside it
 *   ct-split-compare   two figures side by side counting together (before and
 *                      after, A against B), each on its own panel
 *   ct-corner-stat     (tag) a compact stat card in the top-right corner over
 *                      the footage: a counting figure and a one-line label
 *   ct-pie-slice       a pie whose share sweeps in with the count, then the
 *                      slice pulls out of the pie
 *   ct-money-stack     money counting beside a stack of notes that lands with it
 *
 * Numbers read overlay.value / prefix / suffix; labels read overlay.text, with
 * overlay.subtitle (or overlay.label) as a quieter second line. The compare
 * look reads overlay.items [{label, value, prefix?, suffix?}].
 * Sizes are 1080p pixels times k. Everything leaves in the last ~12 frames.
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;

const expoOut = Easing.bezier(0.16, 1, 0.3, 1);
const expoIn = Easing.bezier(0.7, 0, 0.84, 0);
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
/** A count: brisk at first, then a long soft landing on the final digits. */
const countEase = Easing.bezier(0.25, 0.85, 0.3, 1);
const backOut = Easing.bezier(0.34, 1.45, 0.64, 1);

const SOFT = "rgba(255,255,255,.76)";
const TRACK = "rgba(255,255,255,.14)";
const PANEL = "rgba(10,12,18,.74)";
const SHADOW = "0 6px 26px rgba(0,0,0,.42)";

// ------------------------------------------------------------------ helpers
const str = (v: unknown): string => (typeof v === "string" ? v.trim() : typeof v === "number" && Number.isFinite(v) ? String(v) : "");
const cap = (v: unknown): string => str(v).toUpperCase();
const num = (v: unknown): number => {
  if (typeof v === "number") return v;
  if (typeof v === "string" && v.trim() !== "") return Number(v.replace(/[,\s]/g, ""));
  return NaN;
};
const clamp01 = (v: number) => Math.max(0, Math.min(1, Number.isFinite(v) ? v : 0));

type RGB = [number, number, number];
const toRgb = (c: string): RGB => {
  const s = (c || "").trim().replace(/^#/, "");
  let hex = "";
  if (/^[0-9a-f]{6}$/i.test(s)) hex = s;
  else if (/^[0-9a-f]{3}$/i.test(s)) hex = s.split("").map((x) => x + x).join("");
  const m = /^rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)/i.exec((c || "").trim());
  if (!hex && m) return [Number(m[1]), Number(m[2]), Number(m[3])];
  const n = hex ? parseInt(hex, 16) : 0xf2b544;
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
const rgba = (c: string, a: number) => {
  const [r, g, b] = toRgb(c);
  return `rgba(${r},${g},${b},${a})`;
};
const mix = (a: string, b: string, t: number) => {
  const x = toRgb(a), y = toRgb(b);
  const f = (i: number) => Math.round(x[i] + (y[i] - x[i]) * clamp01(t));
  return `rgb(${f(0)},${f(1)},${f(2)})`;
};
const luma = (c: string) => {
  const [r, g, b] = toRgb(c);
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
};
/** The accent as a colour that reads on a dark ground (a navy accent is lifted toward white, a red only a touch). */
const readable = (accent: string) => {
  const l = luma(accent);
  return l < 0.2 ? mix(accent, "#ffffff", 0.55) : l < 0.3 ? mix(accent, "#ffffff", 0.16) : accent;
};

/** Re-wrap `ls` into the same number of lines, as even in length as the room allows (no orphan last word). */
const balance = (t: string, ls: string[], per: number): string[] => {
  if (ls.length < 2) return ls;
  for (let p = Math.ceil(t.length / ls.length); p < per; p++) {
    const b = lines(t, p);
    if (b.length <= ls.length && b.every((l) => l.length <= per)) return b;
  }
  return ls;
};

/** The largest size (1080p px) at which `text` wraps into at most `maxLines` lines `room` px wide. */
const fitLines = (text: string, room: number, sizes: number[], em: number, maxLines: number): { size: number; ls: string[] } => {
  const t = (text || "").replace(/\s+/g, " ").trim();
  const last = sizes[sizes.length - 1];
  if (!t) return { size: last, ls: [] };
  for (const s of sizes) {
    const per = Math.max(4, Math.floor(room / (em * s)));
    const ls = lines(t, per);
    if (ls.length <= maxLines && ls.every((l) => l.length <= per)) return { size: s, ls: balance(t, ls, per) };
  }
  const per = Math.max(4, Math.floor(room / (em * last)));
  const words = t.split(" ").flatMap((w) => (w.length > per ? (w.match(new RegExp(`.{1,${per - 1}}`, "g")) || [w]).map((x, i, a) => (i < a.length - 1 ? `${x}-` : x)) : [w]));
  let ls = lines(words.join(" "), per);
  if (ls.length > maxLines) {
    ls = ls.slice(0, maxLines);
    const l = ls[maxLines - 1];
    ls[maxLines - 1] = `${l.length > per - 1 ? l.slice(0, per - 1).trimEnd() : l}…`;
  }
  return { size: last, ls };
};

/** 0 while the graphic holds, easing to 1 over its last `frames` frames. */
const useOut = (frames = 12) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return ramp(frame, Math.max(0, durationInFrames - frames - 1), frames, expoIn);
};

/** A line sliding up out of its mask at `at`, and down out of it again as `q` goes to 1. */
const Rise: React.FC<{ at: number; q: number; children: React.ReactNode; style?: React.CSSProperties; frames?: number }> =
  ({ at, q, children, style, frames = 16 }) => {
    const frame = useCurrentFrame();
    const p = ramp(frame, at, frames);
    return (
      <div style={{ overflow: "hidden", paddingBottom: "0.14em", marginBottom: "-0.14em", ...style }}>
        <div style={{ transform: `translateY(${((1 - p) * 112 + q * 112).toFixed(2)}%)`, opacity: p > 0.002 ? 1 : 0 }}>{children}</div>
      </div>
    );
  };

// ------------------------------------------------------------------ number text
type Num = { value: number; from: number; dec: number; grouping: boolean; prefix: string; unit: string };
const WORD_UNIT: Record<string, string> = { K: "THOUSAND", M: "MILLION", MN: "MILLION", B: "BILLION", BN: "BILLION", T: "TRILLION" };

const decimalsOf = (v: number): number => {
  if (Number.isInteger(v)) return 0;
  const frac = (v.toFixed(6).split(".")[1] || "").replace(/0+$/, "");
  return Math.min(Math.abs(v) >= 100 ? 1 : 2, frac.length);
};
const fmt = (v: number, dec: number, grouping: boolean) =>
  (Number.isFinite(v) ? v : 0).toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec, useGrouping: grouping });

/** What a figure reads: value, prefix, and the unit as drawn ("%", "FT", "MILLION"). */
const numOf = (ov: { value?: unknown; prefix?: unknown; suffix?: unknown }, opts: { pct?: boolean; money?: boolean } = {}): Num | null => {
  let value = num(ov.value);
  if (!Number.isFinite(value)) return null;
  let prefix = str(ov.prefix);
  const suffix = str(ov.suffix);
  const pct = opts.pct || suffix === "%";
  const money = opts.money || prefix.includes("$") || /^(usd|dollars?)$/i.test(suffix);
  let unit = pct ? "%" : suffix;
  if (money) {
    if (!prefix) prefix = "$";
    const up = suffix.toUpperCase();
    unit = WORD_UNIT[up] || (/^(USD|DOLLARS?)$/.test(up) ? "" : suffix.toUpperCase());
    if (!unit && Math.abs(value) >= 1e9) {
      value = Math.round(value / 1e7) / 100;
      unit = "BILLION";
    } else if (!unit && Math.abs(value) >= 1e6) {
      value = Math.round(value / 1e4) / 100;
      unit = "MILLION";
    }
  }
  const year = Number.isInteger(value) && value >= 1500 && value <= 2100 && !prefix && !unit;
  return { value, from: year ? value - 40 : 0, dec: decimalsOf(value), grouping: !year, prefix, unit };
};

/** The finished figure's width in em of its size (Inter 800 tabular). */
const figEm = (n: Num): number => {
  let em = 0;
  for (const c of fmt(n.value, n.dec, n.grouping)) em += /\d/.test(c) ? 0.66 : c === "," || c === "." ? 0.3 : 0.62;
  if (n.prefix) em += 0.4 * n.prefix.length + 0.04;
  if (n.unit === "%") em += 0.46;
  else if (n.unit === "°") em += 0.3;
  else if (n.unit) em += 0.14 + n.unit.length * (n.unit.length <= 3 ? 0.21 : 0.17);
  return em;
};
const figSize = (n: Num, room: number, max: number, min = 44) => Math.max(min, Math.min(max, room / figEm(n)));

/**
 * The counting digits. The finished number is laid out invisibly to hold
 * the width, and the running count is drawn over it right-aligned, so the
 * figure never jitters sideways as digits are added.
 */
const Count: React.FC<{ n: Num; p: number; style?: React.CSSProperties }> = ({ n, p, style }) => {
  const cur = n.from + (n.value - n.from) * clamp01(p);
  return (
    <span style={{ position: "relative", display: "inline-block", whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums",
      fontFeatureSettings: '"tnum" 1', ...style }}>
      <span style={{ visibility: "hidden" }}>{fmt(n.value, n.dec, n.grouping)}</span>
      <span style={{ position: "absolute", right: 0, top: 0 }}>{fmt(p >= 1 ? n.value : cur, n.dec, n.grouping)}</span>
    </span>
  );
};

/** Prefix + count + unit on one baseline. */
const Figure: React.FC<{ n: Num; p: number; size: number; accent: string; color?: string; unitColor?: string }> =
  ({ n, p, size, accent, color = "#fff", unitColor }) => {
    const acc = readable(accent);
    const u = n.unit;
    const pct = u === "%";
    const deg = u === "°";
    const short = !pct && !deg && u.length <= 3;
    const uStyle: React.CSSProperties = pct ? { fontSize: size * 0.5, color: unitColor || acc, marginLeft: size * 0.03 }
      : deg ? { fontSize: size * 0.62, color: unitColor || acc }
      : { fontFamily: LABEL, fontWeight: 800, fontSize: size * (short ? 0.36 : 0.3), letterSpacing: "0.08em", color: unitColor || SOFT,
        marginLeft: size * 0.12 };
    return (
      <div style={{ display: "flex", alignItems: "baseline", whiteSpace: "nowrap", fontFamily: INTER, fontWeight: 800, color,
        lineHeight: 1, letterSpacing: "-0.02em", textShadow: "0 6px 30px rgba(0,0,0,.35)" }}>
        {n.prefix ? (
          <span style={{ fontSize: size * 0.58, color: acc, marginRight: size * 0.03, position: "relative", top: -size * 0.3 }}>{n.prefix}</span>
        ) : null}
        <Count n={n} p={p} style={{ fontSize: size }} />
        {u ? <span style={uStyle}>{u}</span> : null}
      </div>
    );
  };

/** The label (overlay.text) and a quieter second line (subtitle or label), centred or left. */
const Caption: React.FC<{ ov: Overlay; at: number; q: number; room: number; align?: "center" | "left"; big?: number; cz?: number }> =
  ({ ov, at, q, room, align = "center", big = 42, cz = 1 }) => {
    const k = useK();
    const head = fitLines(cap(ov.text), room, [big, big - 4, big - 8, 32].map((s) => s * cz), 0.52, 2);
    const second = str(ov.subtitle) || (str(ov.label) !== str(ov.text) ? str(ov.label) : "");
    const sub = fitLines(second, room, [32, 30, 28].map((s) => s * cz), 0.5, 2);
    const ta = align === "center" ? "center" : "left";
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: align === "center" ? "center" : "flex-start", gap: 4 * k }}>
        {head.ls.map((ln, i) => (
          <Rise key={`h${i}`} at={at + i * 4} q={q}>
            <div style={{ fontFamily: LABEL, fontWeight: 700, fontSize: head.size * k, letterSpacing: "0.12em", color: "#fff",
              textAlign: ta, whiteSpace: "nowrap", lineHeight: 1.08, textShadow: SHADOW }}>{ln}</div>
          </Rise>
        ))}
        {sub.ls.map((ln, i) => (
          <Rise key={`s${i}`} at={at + 6 + head.ls.length * 4 + i * 3} q={q} style={{ marginTop: i === 0 ? 6 * k : 0 }}>
            <div style={{ fontFamily: INTER, fontWeight: 400, fontSize: sub.size * k, color: SOFT, textAlign: ta, whiteSpace: "nowrap",
              lineHeight: 1.2, textShadow: SHADOW }}>{ln}</div>
          </Rise>
        ))}
      </div>
    );
  };

// ================================================================== ct-clean-count
// The count runs frames 6 -> 44; the sound lands with it (sfx_at 44).
const CleanCount: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const hold = useHold();
  const q = useOut();
  const n = numOf(overlay);
  if (!n) return null;
  const cz = overlay.compact ? 1.35 : 1;
  const p = ramp(frame, 6, 38, countEase);
  const size = figSize(n, 1400, 140 * (overlay.compact ? 1.2 : 1));
  const line = ramp(frame, 26, 22, inOut) * (1 - q);
  const lift = ramp(frame, 0, 18);
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", opacity: 1 - q,
          transform: `translateY(${(-q * 26 * k).toFixed(2)}px)` }}>
          <div style={{ opacity: ramp(frame, 1, 8), transform: `translateY(${((1 - lift) * 30 * k).toFixed(2)}px)` }}>
            <Figure n={n} p={p} size={size * k} accent={accent} />
          </div>
          <div style={{ width: Math.min(size * 3.2, 420) * k * line, height: 4 * k, borderRadius: 2 * k, background: readable(accent),
            margin: `${24 * k}px 0 ${22 * k}px`, boxShadow: `0 0 ${16 * k}px ${rgba(accent, 0.55)}` }} />
          <Caption ov={overlay} at={30} q={0} room={1200} cz={cz} />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== ct-rolling-digits
/**
 * One odometer column of outlined digits: spins from `start`, lands on `d` at
 * `land` with a small settle; a motion blur while it moves. No tile behind it
 * (the owner: only text, bold white with a black outline).
 */
const Reel: React.FC<{ d: number; start: number; land: number; turns: number; size: number; style: React.CSSProperties; flash: string }> =
  ({ d, start, land, turns, size, style, flash }) => {
    const frame = useCurrentFrame();
    const h = size * 1.08;
    const travel = turns * 10 + d;
    const span = Math.max(1, land - start);
    const t = clamp01((frame - start) / span);
    const main = travel * (1 - Math.pow(1 - t, 3));
    const s = frame - land;
    const settle = s > 0 ? -0.18 * Math.sin(s * 0.8) * Math.exp(-s * 0.32) : 0;
    const pos = main + settle;
    const frac = ((pos % 10) + 10) % 10;
    const speed = t < 1 ? (3 * travel * Math.pow(1 - t, 2)) / span : 0;
    const hot = s >= 0 ? Math.exp(-s * 0.18) : 0;
    return (
      <span style={{ position: "relative", display: "inline-block", height: h, width: size * 0.64, overflow: "hidden",
        // the reel's own mask: digits fade in and out at its top and bottom edges
        maskImage: "linear-gradient(180deg, transparent 0%, #000 22%, #000 78%, transparent 100%)",
        WebkitMaskImage: "linear-gradient(180deg, transparent 0%, #000 22%, #000 78%, transparent 100%)" }}>
        <span style={{ position: "absolute", left: 0, right: 0, top: 0, transform: `translateY(${(-(frac + 1) * h).toFixed(2)}px)`,
          filter: speed > 0.35 ? `blur(${Math.min(5, speed * 1.1).toFixed(2)}px)` : undefined }}>
          {Array.from({ length: 12 }, (_, i) => i - 1).map((v) => (
            <span key={v} style={{ height: h, display: "flex", alignItems: "center", justifyContent: "center", ...style,
              color: hot > 0.03 ? mix("#ffffff", flash, hot * 0.85) : "#fff" }}>
              {((v % 10) + 10) % 10}
            </span>
          ))}
        </span>
      </span>
    );
  };

/** Outlined text style for the count looks (bold white, black outline under the fill, a soft shadow). */
const outlined = (size: number, color: string, k: number): React.CSSProperties => {
  const sw = Math.max(5 * k, Math.min(13 * k, size * 0.105));
  return {
    color, WebkitTextStroke: `${sw.toFixed(2)}px #000`, paintOrder: "stroke fill",
    textShadow: `0 ${3 * k}px ${4 * k}px rgba(0,0,0,.35), 0 ${8 * k}px ${26 * k}px rgba(0,0,0,.5)`,
  } as React.CSSProperties;
};

// The reels land between frames 16 and 42, left to right; the last landing is the hit (sfx_at 42).
const RollingDigits: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const { width, height } = useVideoConfig();
  const q = useOut();
  const n = numOf(overlay);
  if (!n) return null;
  const text = fmt(n.value, n.dec, n.grouping);
  const chars = Array.from(text);
  const nd = chars.filter((c) => /\d/.test(c)).length;
  const FIRST = 16, LAST = 42;
  const acc = readable(accent);
  const unitWord = Boolean(n.unit) && n.unit !== "%" && n.unit.length > 2;
  const em = nd * 0.64 + (chars.length - nd) * 0.3 + (n.prefix ? 0.42 * n.prefix.length : 0)
    + (n.unit ? (n.unit === "%" ? 0.5 : unitWord ? 0.12 + n.unit.length * 0.2 : 0.2 + n.unit.length * 0.44) : 0);
  const size = Math.max(90 * k, Math.min(260 * k * (overlay.compact ? 1.1 : 1), (width - 280 * k) / em));
  const digit: React.CSSProperties = { fontFamily: INTER, fontWeight: 800, fontSize: size, lineHeight: 1, letterSpacing: "-0.02em",
    fontVariantNumeric: "tabular-nums", ...outlined(size * 0.62, "#fff", k) };
  const label = cap(overlay.text) || (str(overlay.label) ? cap(overlay.label) : "");
  const labelFit = fitLines(label, Math.min(1400, (width / k) - 280), [72, 64, 56, 48], 0.5, 2);
  const enter = ramp(frame, 0, 14);
  let j = 0;
  const cells = chars.map((c, i) => {
    if (!/\d/.test(c)) {
      return (
        <span key={i} style={{ ...digit, width: size * 0.3, textAlign: "center", opacity: ramp(frame, 6, 10) }}>{c}</span>
      );
    }
    const land = nd > 1 ? FIRST + (j * (LAST - FIRST)) / (nd - 1) : LAST;
    const turns = 2 + j;
    j += 1;
    return <Reel key={i} d={Number(c)} start={3} land={Math.round(land)} turns={turns} size={size} style={digit} flash={acc} />;
  });
  const punch = frame >= LAST ? 1 + 0.05 * Math.exp(-(frame - LAST) / 3.5) * Math.cos((frame - LAST) / 2.2) : 1;
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", marginTop: -height * 0.06,
          opacity: (1 - q) * Math.min(1, enter * 2), transform: `translateY(${((1 - enter) * 26 * k + q * 34 * k).toFixed(2)}px)` }}>
          <div style={{ display: "flex", alignItems: "center", transform: `scale(${punch.toFixed(4)})` }}>
            {n.prefix ? (
              <span style={{ ...digit, ...outlined(size * 0.4, acc, k), fontSize: size * 0.62, marginRight: size * 0.04 }}>{n.prefix}</span>
            ) : null}
            {cells}
            {n.unit ? (
              <span style={unitWord
                ? { fontFamily: LABEL, fontWeight: 800, fontSize: size * 0.4, letterSpacing: "0.04em", marginLeft: size * 0.1,
                  ...outlined(size * 0.4, acc, k), opacity: ramp(frame, LAST - 6, 10), alignSelf: "flex-end", marginBottom: size * 0.16 }
                : { ...digit, ...outlined(size * 0.45, acc, k), fontSize: size * (n.unit === "%" ? 0.62 : 0.72), marginLeft: size * 0.03,
                  opacity: ramp(frame, 6, 10) }}>{n.unit}</span>
            ) : null}
          </div>
          {labelFit.ls.map((ln, i) => {
            const lp = ramp(frame, LAST - 8 + i * 4, 16);
            return (
              <div key={i} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: labelFit.size * k, lineHeight: 1.04, letterSpacing: "0.03em",
                whiteSpace: "nowrap", marginTop: i ? 0 : 4 * k, ...outlined(labelFit.size * k, "#fff", k),
                transform: `translateY(${((1 - lp) * 28 * k).toFixed(2)}px)`, opacity: Math.min(1, lp * 2) }}>{ln}</div>
            );
          })}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== ct-bar-percent
// Bar and count fill together, frames 8 -> 50; the riser peaks as it lands (sfx_at 50).
const BarPercent: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const hold = useHold();
  const q = useOut();
  const n = numOf(overlay, { pct: true });
  if (!n) return null;
  const cz = overlay.compact ? 1.3 : 1;
  const p = ramp(frame, 8, 42, inOut);
  const frac = clamp01(n.value / 100) * p;
  const W = 1200;
  const head = fitLines(cap(overlay.text), 640, [46, 42, 38, 34].map((s) => s * cz), 0.52, 2);
  const second = str(overlay.subtitle) || (str(overlay.label) !== str(overlay.text) ? str(overlay.label) : "");
  const size = figSize(n, 470, 128 * (overlay.compact ? 1.15 : 1));
  const track = ramp(frame, 2, 18, expoOut);
  const enter = ramp(frame, 0, 16);
  const deep = mix(accent, "#000000", 0.35);
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ width: W * k, padding: `${46 * k}px ${58 * k}px ${40 * k}px`, borderRadius: 22 * k, background: PANEL,
          border: `1px solid rgba(255,255,255,.08)`, boxShadow: "0 30px 80px rgba(0,0,0,.45)", backdropFilter: "blur(8px)",
          opacity: enter * (1 - q), transform: `translateY(${((1 - enter) * 34 * k - q * 24 * k).toFixed(2)}px)` }}>
          <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 40 * k }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 2 * k, paddingBottom: 12 * k }}>
              {head.ls.map((ln, i) => (
                <Rise key={i} at={6 + i * 4} q={0}>
                  <div style={{ fontFamily: LABEL, fontWeight: 800, fontSize: head.size * k, letterSpacing: "0.1em", color: "#fff",
                    whiteSpace: "nowrap", lineHeight: 1.05 }}>{ln}</div>
                </Rise>
              ))}
            </div>
            <Figure n={n} p={p} size={size * k} accent={accent} />
          </div>
          <div style={{ position: "relative", height: 28 * k, marginTop: 30 * k, borderRadius: 14 * k, background: TRACK,
            transform: `scaleX(${track})`, transformOrigin: "0 50%" }}>
            <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${frac * 100}%`, borderRadius: 14 * k,
              background: `linear-gradient(90deg, ${deep} 0%, ${accent} 100%)`, boxShadow: `0 0 ${22 * k}px ${rgba(accent, 0.5)}` }} />
            {[25, 50, 75].map((t) => (
              <div key={t} style={{ position: "absolute", left: `${t}%`, top: 6 * k, bottom: 6 * k, width: 2 * k, background: "rgba(0,0,0,.28)" }} />
            ))}
            {frac > 0.002 ? (
              <div style={{ position: "absolute", left: `${frac * 100}%`, top: "50%", width: 36 * k, height: 36 * k, marginLeft: -18 * k,
                marginTop: -18 * k, borderRadius: "50%", background: "#fff", boxShadow: `0 0 0 ${5 * k}px ${rgba(accent, 0.45)}, 0 0 ${24 * k}px ${rgba(accent, 0.8)}` }} />
            ) : null}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: 14 * k, fontFamily: LABEL, fontWeight: 600,
            fontSize: 28 * k, letterSpacing: "0.1em", color: "rgba(255,255,255,.5)", opacity: ramp(frame, 12, 12) }}>
            <span>0</span><span>50</span><span>100%</span>
          </div>
          {second ? (
            <Rise at={46} q={0} style={{ marginTop: 14 * k }}>
              <div style={{ fontFamily: INTER, fontWeight: 400, fontSize: 32 * cz * k, color: SOFT, whiteSpace: "nowrap", overflow: "hidden",
                textOverflow: "ellipsis" }}>{second}</div>
            </Rise>
          ) : null}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== ct-ring-pro
// The arc and count fill frames 10 -> 52; the riser peaks as they land (sfx_at 52).
const RingPro: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const hold = useHold();
  const q = useOut();
  const n = numOf(overlay, { pct: true });
  if (!n) return null;
  const cz = overlay.compact ? 1.3 : 1;
  const D = 460 * (overlay.compact ? 1.12 : 1) * k, T = 30 * (overlay.compact ? 1.12 : 1) * k;
  const p = ramp(frame, 10, 42, inOut);
  const frac = clamp01(n.value / 100) * p;
  const ang = frac * 360;
  const enter = ramp(frame, 0, 18);
  const light = mix(accent, "#ffffff", 0.45);
  const acc = readable(accent);
  const rMid = D / 2 - T / 2;
  const endX = D / 2 + rMid * Math.sin((ang * Math.PI) / 180);
  const endY = D / 2 - rMid * Math.cos((ang * Math.PI) / 180);
  const ring = `radial-gradient(farthest-side, transparent calc(100% - ${T.toFixed(2)}px), #000 calc(100% - ${(T - 1).toFixed(2)}px))`;
  const size = figSize(n, (D - 2 * T - 70 * k) / k, 132 * (overlay.compact ? 1.12 : 1));
  const R2 = D / 2 + 24 * k;
  const S = D + 70 * k;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 30 * k, opacity: 1 - q,
          transform: `translateY(${(-q * 26 * k).toFixed(2)}px)` }}>
          <div style={{ position: "relative", width: S, height: S, opacity: enter, transform: `scale(${0.9 + 0.1 * enter}) rotate(${(1 - enter) * -20}deg)` }}>
            <svg width={S} height={S} style={{ position: "absolute", inset: 0 }}>
              {Array.from({ length: 60 }, (_, i) => {
                const a = (i / 60) * Math.PI * 2;
                const on = i / 60 < frac - 1e-6;
                const r1 = R2, r2 = R2 + (i % 5 === 0 ? 14 : 8) * k;
                return (
                  <line key={i} x1={S / 2 + r1 * Math.sin(a)} y1={S / 2 - r1 * Math.cos(a)} x2={S / 2 + r2 * Math.sin(a)} y2={S / 2 - r2 * Math.cos(a)}
                    stroke={on ? acc : "rgba(255,255,255,.28)"} strokeWidth={Math.max(1, 2.4 * k)} strokeLinecap="round" />
                );
              })}
            </svg>
            <div style={{ position: "absolute", left: (S - D) / 2, top: (S - D) / 2, width: D, height: D }}>
              <div style={{ position: "absolute", inset: 0, borderRadius: "50%", background: TRACK, WebkitMaskImage: ring, maskImage: ring }} />
              <div style={{ position: "absolute", inset: 0, borderRadius: "50%", WebkitMaskImage: ring, maskImage: ring,
                background: `conic-gradient(from 0deg, ${light} 0deg, ${accent} ${Math.max(0.01, ang).toFixed(2)}deg, transparent ${Math.max(0.01, ang).toFixed(2)}deg)` }} />
              {ang > 0.6 ? (
                <>
                  <div style={{ position: "absolute", left: D / 2 - T / 2, top: 0, width: T, height: T, borderRadius: "50%", background: light }} />
                  <div style={{ position: "absolute", left: endX - T / 2, top: endY - T / 2, width: T, height: T, borderRadius: "50%", background: accent,
                    boxShadow: `0 0 ${20 * k}px ${rgba(accent, 0.85)}` }} />
                </>
              ) : null}
              <div style={{ position: "absolute", inset: T + 18 * k, borderRadius: "50%",
                background: "radial-gradient(circle, rgba(0,0,0,.34) 0%, rgba(0,0,0,.1) 70%, rgba(0,0,0,0) 100%)" }} />
              <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
                <Figure n={n} p={p} size={size * k} accent={accent} />
              </div>
            </div>
          </div>
          <Caption ov={overlay} at={34} q={0} room={1100} cz={cz} />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== ct-dot-grid
const Person: React.FC<{ w: number; h: number; color: string }> = ({ w, h, color }) => (
  <svg width={w} height={h} viewBox="0 0 24 30" style={{ display: "block" }}>
    <circle cx={12} cy={7} r={5.6} fill={color} />
    <path d="M2.5 29 C2.5 20 6 15.2 12 15.2 C18 15.2 21.5 20 21.5 29 Z" fill={color} />
  </svg>
);

// 100 people fill with the count, frames 10 -> 54; a tick marks the landing (sfx_at 54).
const DotGrid: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const hold = useHold();
  const q = useOut();
  const n = numOf(overlay, { pct: true });
  if (!n) return null;
  const cz = overlay.compact ? 1.3 : 1;
  const p = ramp(frame, 10, 44, inOut);
  const target = Math.round(Math.max(0, Math.min(100, n.value)));
  const lit = target * p;
  const cw = 46 * k, ch = 54 * k, gap = 8 * k;
  const acc = readable(accent);
  const size = figSize(n, 600, 132 * (overlay.compact ? 1.12 : 1));
  const inEvery = n.value > 0 && n.value <= 100 && Number.isInteger(n.value) ? `${n.value} IN EVERY 100` : "";
  const head = fitLines(cap(overlay.text), 640, [42, 38, 34, 32].map((s) => s * cz), 0.52, 3);
  const second = str(overlay.subtitle) || (str(overlay.label) !== str(overlay.text) ? str(overlay.label) : "");
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 90 * k, opacity: 1 - q, transform: `translateY(${(-q * 26 * k).toFixed(2)}px)` }}>
          <div style={{ display: "grid", gridTemplateColumns: `repeat(10, ${cw}px)`, gridAutoRows: `${ch}px`, gap }}>
            {Array.from({ length: 100 }, (_, i) => {
              const row = Math.floor(i / 10), col = i % 10;
              const appear = ramp(frame, 1 + (row + col) * 0.7, 10);
              const on = clamp01(lit - i);
              return (
                <div key={i} style={{ opacity: appear, transform: `scale(${(0.6 + 0.4 * appear) * (1 + 0.1 * Math.sin(on * Math.PI))})` }}>
                  <Person w={cw} h={ch} color={on > 0 ? mix("#5a5f6b", accent, on) : "rgba(255,255,255,.2)"} />
                </div>
              );
            })}
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", maxWidth: 660 * k }}>
            <div style={{ opacity: ramp(frame, 4, 10) }}>
              <Figure n={n} p={p} size={size * k} accent={accent} />
            </div>
            {inEvery ? (
              <Rise at={24} q={0} style={{ marginTop: 14 * k }}>
                <div style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 30 * cz * k, letterSpacing: "0.18em", color: acc, whiteSpace: "nowrap" }}>{inEvery}</div>
              </Rise>
            ) : null}
            <div style={{ width: 90 * k * ramp(frame, 26, 18, inOut), height: 4 * k, background: readable(accent), margin: `${22 * k}px 0 ${18 * k}px`, borderRadius: 2 * k }} />
            {head.ls.map((ln, i) => (
              <Rise key={i} at={30 + i * 4} q={0}>
                <div style={{ fontFamily: LABEL, fontWeight: 700, fontSize: head.size * k, letterSpacing: "0.1em", color: "#fff",
                  whiteSpace: "nowrap", lineHeight: 1.08, textShadow: SHADOW }}>{ln}</div>
              </Rise>
            ))}
            {second ? (
              <Rise at={42} q={0} style={{ marginTop: 10 * k }}>
                <div style={{ fontFamily: INTER, fontSize: 30 * cz * k, color: SOFT, maxWidth: 640 * k, lineHeight: 1.25 }}>{second}</div>
              </Rise>
            ) : null}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== ct-split-compare
type Side = { label: string; n: Num };
const sidesOf = (ov: Overlay): Side[] => {
  const raw: unknown[] = Array.isArray(ov.items) ? ov.items : [];
  const out: Side[] = [];
  for (const it of raw) {
    if (!it || typeof it !== "object") continue;
    const x = it as { label?: unknown; value?: unknown; prefix?: unknown; suffix?: unknown };
    const n = numOf({ value: x.value, prefix: str(x.prefix) || ov.prefix, suffix: str(x.suffix) || ov.suffix });
    if (n) out.push({ label: cap(x.label), n });
    if (out.length === 2) break;
  }
  return out;
};

// The two panels swipe in and meet at frame ~10 (sfx_at 10); the figures count 12 -> 50.
const SplitCompare: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const hold = useHold();
  const q = useOut();
  const sides = sidesOf(overlay);
  if (sides.length < 2) return <CleanCount overlay={overlay} accent={accent} />;
  const cz = overlay.compact ? 1.25 : 1;
  const PW = 640, PH = 400;
  const p = ramp(frame, 12, 38, countEase);
  const title = fitLines(cap(overlay.text), 1300, [46, 42, 38, 34].map((s) => s * cz), 0.52, 2);
  const size = Math.min(...sides.map((s) => figSize(s.n, PW - 110, 132)));
  const badge = ramp(frame, 12, 14, backOut);
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 40 * k, opacity: 1 - q,
          transform: `translateY(${(-q * 26 * k).toFixed(2)}px)` }}>
          {title.ls.length ? (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
              {title.ls.map((ln, i) => (
                <Rise key={i} at={2 + i * 4} q={0}>
                  <div style={{ fontFamily: LABEL, fontWeight: 800, fontSize: title.size * k, letterSpacing: "0.12em", color: "#fff",
                    whiteSpace: "nowrap", lineHeight: 1.06, textShadow: SHADOW }}>{ln}</div>
                </Rise>
              ))}
            </div>
          ) : null}
          <div style={{ position: "relative", display: "flex", gap: 64 * k }}>
            {sides.map((s, i) => {
              const e = ramp(frame, i * 3, 16, expoOut);
              const dx = (i === 0 ? -1 : 1) * (1 - e) * 220 * k;
              const lab = fitLines(s.label, PW - 110, [36, 32, 30, 28].map((v) => v * cz), 0.52, 2);
              return (
                <div key={i} style={{ position: "relative", width: PW * k, height: PH * k, borderRadius: 20 * k, background: PANEL,
                  border: "1px solid rgba(255,255,255,.08)", overflow: "hidden", opacity: e, transform: `translateX(${dx.toFixed(2)}px)`,
                  boxShadow: "0 30px 70px rgba(0,0,0,.45)", display: "flex", flexDirection: "column", justifyContent: "center",
                  padding: `0 ${55 * k}px` }}>
                  <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 7 * k,
                    background: i === 0 ? "rgba(255,255,255,.55)" : accent, transform: `scaleX(${ramp(frame, 10 + i * 3, 16, inOut)})`,
                    transformOrigin: i === 0 ? "100% 50%" : "0 50%" }} />
                  {lab.ls.map((ln, li) => (
                    <Rise key={li} at={14 + i * 3 + li * 3} q={0}>
                      <div style={{ fontFamily: LABEL, fontWeight: 700, fontSize: lab.size * k, letterSpacing: "0.14em",
                        color: i === 0 ? SOFT : readable(accent), whiteSpace: "nowrap", lineHeight: 1.08 }}>{ln}</div>
                    </Rise>
                  ))}
                  <div style={{ marginTop: 20 * k }}>
                    <Figure n={s.n} p={p} size={size * k} accent={accent} />
                  </div>
                </div>
              );
            })}
            <div style={{ position: "absolute", left: "50%", top: "50%", width: 76 * k, height: 76 * k, marginLeft: -38 * k, marginTop: -38 * k,
              borderRadius: "50%", background: accent, boxShadow: `0 10px 30px rgba(0,0,0,.5), 0 0 0 ${6 * k}px rgba(10,12,18,.9)`,
              display: "flex", alignItems: "center", justifyContent: "center", transform: `scale(${badge})` }}>
              <svg width={34 * k} height={34 * k} viewBox="0 0 24 24">
                <path d="M5 12h13M13 6l6 6-6 6" fill="none" stroke={luma(accent) > 0.62 ? "#111" : "#fff"} strokeWidth={3}
                  strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== ct-corner-stat
/**
 * A figure riding the footage top right, in the owner's text language (no
 * card): the count in outlined Inter 800 right-aligned at the 96 px margin,
 * its unit in the accent, a short accent tick drawing under it, then the
 * label in outlined bold caps. It clicks in at frame 6 (sfx_at 6); the count
 * runs 8 -> 40 and lands with a small punch; it slides back out at the end.
 */
const CornerStat: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const { width } = useVideoConfig();
  const q = useOut();
  const n = numOf(overlay);
  if (!n) return null;
  const acc = readable(accent);
  const e = ramp(frame, 0, 14, expoOut);
  const p = ramp(frame, 8, 32, countEase);
  const LAND = 40;
  const room = Math.min(760 * k, width * 0.42);
  const size = Math.max(70 * k, Math.min(150 * k, room / Math.max(0.1, figEm(n))));
  const label = cap(overlay.text) || cap(overlay.label);
  const fitL = fitLines(label, room / k, [52, 46, 40, 36], 0.5, 2);
  const unitWord = Boolean(n.unit) && n.unit !== "%" && n.unit.length > 2;
  const digit: React.CSSProperties = { fontFamily: INTER, fontWeight: 800, fontSize: size, lineHeight: 1, letterSpacing: "-0.02em",
    ...outlined(size * 0.6, "#fff", k) };
  const punch = frame >= LAND ? 1 + 0.06 * Math.exp(-(frame - LAND) / 3.5) * Math.cos((frame - LAND) / 2.2) : 1;
  const tick = ramp(frame, LAND - 4, 14, inOut) * (1 - q);
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", top: 90 * k, right: 96 * k, display: "flex", flexDirection: "column", alignItems: "flex-end",
        opacity: Math.min(1, e * 2) * (1 - q), transform: `translateX(${((1 - e) * 60 * k + q * 60 * k).toFixed(2)}px)` }}>
        <div style={{ display: "flex", alignItems: "baseline", whiteSpace: "nowrap", transform: `scale(${punch.toFixed(4)})`,
          transformOrigin: "100% 80%" }}>
          {n.prefix ? <span style={{ ...digit, ...outlined(size * 0.4, acc, k), fontSize: size * 0.62, marginRight: size * 0.03 }}>{n.prefix}</span> : null}
          <Count n={n} p={p} style={digit} />
          {n.unit ? (
            <span style={unitWord
              ? { fontFamily: LABEL, fontWeight: 800, fontSize: size * 0.44, letterSpacing: "0.04em", marginLeft: size * 0.1,
                ...outlined(size * 0.44, acc, k) }
              : { ...digit, ...outlined(size * 0.45, acc, k), fontSize: size * (n.unit === "%" ? 0.62 : 0.72), marginLeft: size * 0.03 }}>
              {n.unit}</span>
          ) : null}
        </div>
        <div style={{ width: 120 * k * tick, height: 8 * k, borderRadius: 2 * k, background: acc, margin: `${10 * k}px 0 ${8 * k}px`,
          boxShadow: `0 0 0 ${2.5 * k}px #000, 0 0 ${14 * k}px ${acc}` }} />
        {fitL.ls.map((ln, i) => {
          const lp = ramp(frame, 12 + i * 4, 16);
          return (
            <div key={i} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: fitL.size * k, lineHeight: 1.04, letterSpacing: "0.04em",
              whiteSpace: "nowrap", textAlign: "right", ...outlined(fitL.size * k, "#fff", k),
              transform: `translateY(${((1 - lp) * 24 * k).toFixed(2)}px)`, opacity: Math.min(1, lp * 2) }}>{ln}</div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== ct-pie-slice
const wedge = (cx: number, cy: number, r: number, a0: number, a1: number): string => {
  const rad = (d: number) => ((d - 90) * Math.PI) / 180;
  if (a1 - a0 >= 359.99) {
    return `M ${cx} ${cy - r} A ${r} ${r} 0 1 1 ${cx - 0.01} ${cy - r} Z`;
  }
  const x0 = cx + r * Math.cos(rad(a0)), y0 = cy + r * Math.sin(rad(a0));
  const x1 = cx + r * Math.cos(rad(a1)), y1 = cy + r * Math.sin(rad(a1));
  return `M ${cx} ${cy} L ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)} Z`;
};

// The share sweeps in with the count, frames 8 -> 40; the slice pulls out 40 -> 52 (sfx_at 46).
const PieSlice: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const hold = useHold();
  const q = useOut();
  const id = `ctPie${React.useId().replace(/[^A-Za-z0-9]/g, "")}`;
  const n = numOf(overlay, { pct: true });
  if (!n) return null;
  const cz = overlay.compact ? 1.3 : 1;
  const R = 230 * k;
  const S = 2 * R + 120 * k;
  const c = S / 2;
  const p = ramp(frame, 8, 32, inOut);
  const share = clamp01(n.value / 100);
  const a = share * 360 * p;
  const pull = ramp(frame, 40, 14, backOut);
  const mid = ((a / 2 - 90) * Math.PI) / 180;
  const off = share < 0.999 ? pull * 34 * k : 0;
  const enter = ramp(frame, 0, 16);
  const light = mix(accent, "#ffffff", 0.3);
  const size = figSize(n, 560, 132 * (overlay.compact ? 1.12 : 1));
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 70 * k, opacity: 1 - q, transform: `translateY(${(-q * 26 * k).toFixed(2)}px)` }}>
          <svg width={S} height={S} style={{ overflow: "visible", opacity: enter, transform: `scale(${0.88 + 0.12 * enter}) rotate(${(1 - enter) * -30}deg)` }}>
            <defs>
              <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stopColor={light} />
                <stop offset="100%" stopColor={accent} />
              </linearGradient>
            </defs>
            <circle cx={c} cy={c} r={R} fill="rgba(18,20,26,.55)" stroke="rgba(255,255,255,.3)" strokeWidth={Math.max(1, 2 * k)} />
            <circle cx={c} cy={c} r={R} fill="rgba(255,255,255,.1)" />
            {a > 0.2 ? (
              <path d={wedge(c + off * Math.cos(mid), c + off * Math.sin(mid), R, 0, a)} fill={`url(#${id})`}
                stroke="rgba(255,255,255,.9)" strokeWidth={Math.max(1, 3 * k * pull)} strokeLinejoin="round"
                style={{ filter: `drop-shadow(0 ${12 * k * pull}px ${22 * k * pull}px rgba(0,0,0,.45))` }} />
            ) : null}
            <circle cx={c} cy={c} r={R} fill="none" stroke="rgba(0,0,0,.18)" strokeWidth={1} />
          </svg>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", maxWidth: 680 * k }}>
            <div style={{ opacity: ramp(frame, 4, 10) }}>
              <Figure n={n} p={p} size={size * k} accent={accent} />
            </div>
            <div style={{ width: 90 * k * ramp(frame, 34, 18, inOut), height: 4 * k, background: readable(accent), margin: `${24 * k}px 0 ${18 * k}px`, borderRadius: 2 * k }} />
            <Caption ov={overlay} at={38} q={0} room={660} align="left" cz={cz} />
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== ct-money-stack
const Note: React.FC<{ w: number; h: number; tint: string }> = ({ w, h, tint }) => (
  <svg width={w} height={h} viewBox="0 0 300 130" style={{ display: "block" }}>
    <rect x={1} y={1} width={298} height={128} rx={8} fill={tint} stroke="rgba(0,0,0,.35)" strokeWidth={2} />
    <rect x={12} y={12} width={276} height={106} rx={5} fill="none" stroke="rgba(255,255,255,.4)" strokeWidth={2} />
    <ellipse cx={150} cy={65} rx={34} ry={40} fill="none" stroke="rgba(255,255,255,.45)" strokeWidth={3} />
    <circle cx={42} cy={65} r={16} fill="none" stroke="rgba(255,255,255,.3)" strokeWidth={2} />
    <circle cx={258} cy={65} r={16} fill="none" stroke="rgba(255,255,255,.3)" strokeWidth={2} />
    <rect x={70} y={20} width={50} height={6} rx={3} fill="rgba(255,255,255,.22)" />
    <rect x={180} y={104} width={50} height={6} rx={3} fill="rgba(255,255,255,.22)" />
  </svg>
);

// Notes drop onto the stack while the money counts, frames 10 -> 50 (sfx_at 50).
const MoneyStack: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const hold = useHold();
  const q = useOut();
  const n = numOf(overlay, { money: true });
  if (!n) return null;
  const cz = overlay.compact ? 1.3 : 1;
  const p = ramp(frame, 10, 40, countEase);
  const NW = 330 * k, NH = 143 * k;
  const COUNT = 9;
  const size = figSize(n, 800, 132 * (overlay.compact ? 1.12 : 1));
  const stackH = NH + (COUNT - 1) * 17 * k + 40 * k;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 80 * k, opacity: 1 - q, transform: `translateY(${(-q * 26 * k).toFixed(2)}px)` }}>
          <div style={{ position: "relative", width: NW + 40 * k, height: stackH, perspective: `${1200 * k}px` }}>
            <div style={{ position: "absolute", left: 10 * k, right: 10 * k, bottom: 0, height: 26 * k, borderRadius: "50%",
              background: "radial-gradient(ellipse, rgba(0,0,0,.5) 0%, rgba(0,0,0,0) 70%)", opacity: ramp(frame, 4, 12) }} />
            {Array.from({ length: COUNT }, (_, i) => {
              const at = 6 + i * 4.2;
              const d = ramp(frame, at, 10, expoOut);
              const settle = ramp(frame, at + 6, 8);
              const jx = (Math.sin(i * 12.9898) * 43758.5453 % 1) * 14 * k;
              const rot = Math.sin(i * 4.1) * 2.6;
              const tint = i % 2 ? "#5b7755" : "#66835f";
              return (
                <div key={i} style={{ position: "absolute", left: 20 * k + jx, bottom: 18 * k + i * 17 * k, opacity: ramp(frame, at, 4),
                  transform: `translateY(${((1 - d) * -120 * k).toFixed(2)}px) rotate(${(rot + (1 - settle) * 5).toFixed(2)}deg) rotateX(58deg)`,
                  transformOrigin: "50% 100%", filter: "drop-shadow(0 6px 8px rgba(0,0,0,.35))" }}>
                  <Note w={NW} h={NH} tint={tint} />
                </div>
              );
            })}
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", maxWidth: 840 * k }}>
            <div style={{ opacity: ramp(frame, 4, 10), transform: `translateY(${((1 - ramp(frame, 2, 16)) * 24 * k).toFixed(2)}px)` }}>
              <Figure n={n} p={p} size={size * k} accent={accent} />
            </div>
            <div style={{ width: 90 * k * ramp(frame, 30, 18, inOut), height: 4 * k, background: readable(accent), margin: `${24 * k}px 0 ${18 * k}px`, borderRadius: 2 * k }} />
            <Caption ov={overlay} at={34} q={0} room={800} align="left" cz={cz} />
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== registry
export const LOOKS: Record<string, Look> = {
  "ct-clean-count": CleanCount,
  "ct-rolling-digits": RollingDigits,
  "ct-bar-percent": BarPercent,
  "ct-ring-pro": RingPro,
  "ct-dot-grid": DotGrid,
  "ct-split-compare": SplitCompare,
  "ct-corner-stat": CornerStat,
  "ct-pie-slice": PieSlice,
  "ct-money-stack": MoneyStack,
};
