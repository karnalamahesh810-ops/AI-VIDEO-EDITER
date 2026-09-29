import React from "react";
import { AbsoluteFill, Audio, Easing, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY, HAND, LABEL, MONO } from "../fonts";
import type { Overlay } from "../../types";
import { Odometer, lines, ramp, useK } from "../pro/ProGraphics";

// The owner (2026-09-29): a look's own sounds sit at ~40% of their old level.
const IN_LOOK_SFX_SCALE = 0.4;

/**
 * Persistent tags (family "ps-"): looks built to ride on footage ACROSS cuts,
 * the way GoMotion's "22% OF CAPACITY REMAINING" ring stayed up over three
 * consecutive shots. They never darken the frame (no Scrim: only a soft
 * radial pool behind the graphic), enter once, hold with one slow living
 * detail, and leave only in their last 12 frames, so the graphic reads as one
 * object riding over the clips that change beneath it.
 *
 *   ps-percent-ring     a ring sweeps to the percentage, the number rolls inside, a chip names it
 *   ps-stat-ride        a bare bold figure ("3,491 FEET", "-1.3M ACRE FEET") riding top-right
 *   ps-paper-checklist  a cream paper card pinned top-right, rows ticked one by one
 *
 * The planner (src/treatments.py) gives the family its own "persist" layout
 * class: a 6-12 s hold, no compact scaling, one at a time. Placement:
 * overlay.position "center" is honoured here; the other positions are the
 * renderer's own shift of the default spot (MotionWrap), never doubled here;
 * overlay.compact scales a look down into a corner.
 *
 * Deterministic (no Math.random / Date), 1080p-referenced sizes times k.
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const expoIn = Easing.bezier(0.7, 0, 0.84, 0);
const expoOut = Easing.bezier(0.16, 1, 0.3, 1);
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const RED = "#ff3b30";
const GOLD = "#e9b949";
const INK = "#2a2118";
const PAPER = "#f3ecdc";
const TAB = "#b3261e";
const EXIT = 12;

// ------------------------------------------------------------------ helpers
/** A string from a text field that may arrive as a number or be missing (never throws). */
const S = (v: unknown): string =>
  typeof v === "string" ? v : typeof v === "number" && Number.isFinite(v) ? String(v) : "";
const cap = (v: unknown): string => S(v).replace(/\s+/g, " ").trim().toUpperCase();
/** A number from a number or a numeric string ("22%", "1,234", "−8"). */
const toNum = (raw: unknown): number => {
  if (typeof raw === "number") return raw;
  if (typeof raw === "string") {
    const m = /-?\d[\d,]*(?:\.\d+)?|-?\.\d+/.exec(raw.replace(/−/g, "-"));
    return m ? Number(m[0].replace(/,/g, "")) : NaN;
  }
  return NaN;
};
const clip = (s: string, n: number): string => (s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s);
/** Deterministic 0..1 noise from an integer. */
const rnd = (i: number): number => {
  const x = Math.sin(i * 127.1 + 311.7) * 43758.5453123;
  return x - Math.floor(x);
};
const hexRgb = (h: string): [number, number, number] => {
  const m = /^#?([0-9a-f]{6}|[0-9a-f]{3})$/i.exec((h || "").trim());
  if (!m) return [233, 185, 73];
  let s = m[1];
  if (s.length === 3) s = s.split("").map((c) => c + c).join("");
  return [parseInt(s.slice(0, 2), 16), parseInt(s.slice(2, 4), 16), parseInt(s.slice(4, 6), 16)];
};
/** The accent unless it reads green (the ring is red or gold, never green). */
const warm = (accent: string): string => {
  const [r, g, b] = hexRgb(accent);
  return g > r * 1.15 && g > b * 1.15 ? GOLD : accent;
};
/** The rows a checklist can show: items[].label (or .text) as strings, at most `max`. */
const itemsOf = (ov: Overlay, max: number): string[] => {
  const out: string[] = [];
  for (const it of Array.isArray(ov.items) ? ov.items : []) {
    if (!it || typeof it !== "object") continue;
    const t = S((it as { label?: unknown }).label) || S((it as { text?: unknown }).text);
    if (!t.trim()) continue;
    out.push(clip(t.trim(), 26));
    if (out.length >= max) break;
  }
  return out;
};

/** 0 while the graphic holds, easing to 1 over its last EXIT frames. */
const useExit = (): number => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return ramp(frame, durationInFrames - EXIT - 1, EXIT, expoIn);
};
/** A safety fade over the very last frames for any residue after the designed exits. */
const useFin = (): number => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return 1 - ramp(frame, durationInFrames - 3, 3);
};
/** A slow 0..1..0 breath with the given period in seconds. */
const useBreath = (seconds: number): number => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return 0.5 - 0.5 * Math.cos(((frame / fps) / Math.max(0.2, seconds)) * Math.PI * 2);
};

/**
 * The soft pool under a persistent tag: a radial darkening centred on the
 * graphic (x/y in % of the frame), at most .35 black, never a full-frame scrim.
 */
const Pool: React.FC<{ ov: Overlay; x: number; y: number; rx?: number; ry?: number; exit: number }> =
  ({ ov, x, y, rx = 34, ry = 46, exit }) => {
    const frame = useCurrentFrame();
    if (ov.fullFrame) return null;
    return (
      <AbsoluteFill style={{ opacity: ramp(frame, 0, 14) * (1 - exit), background:
        `radial-gradient(ellipse ${rx}% ${ry}% at ${x}% ${y}%, rgba(0,0,0,.35) 0%, rgba(0,0,0,.18) 48%, rgba(0,0,0,0) 78%)` }} />
    );
  };

/** Content rising out of a mask (pin 0..1) and dropping back out of it (pout 0..1). */
const MaskIO: React.FC<{ pin: number; pout: number; children: React.ReactNode; style?: React.CSSProperties }> =
  ({ pin, pout, children, style }) => (
    <div style={{ overflow: "hidden", paddingBottom: "0.08em", ...style }}>
      <div style={{ transform: `translateY(${((1 - pin) * 110 + pout * 110).toFixed(2)}%)`,
        opacity: pin < 0.02 || pout > 0.98 ? 0 : 1 }}>{children}</div>
    </div>
  );

/** A short pop, played once at `at` (never past the end of the graphic). */
const Tick: React.FC<{ at: number; name?: string; volume?: number }> = ({ at, name = "pop", volume = 0.3 }) => {
  const { durationInFrames } = useVideoConfig();
  if (at < 0 || at >= durationInFrames - 2) return null;
  return (
    <Sequence from={at} layout="none">
      <Audio src={staticFile(`sfx/${name}.mp3`)} volume={Math.max(0, Math.min(1, volume * IN_LOOK_SFX_SCALE))} />
    </Sequence>
  );
};

/**
 * A figure whose characters rise out of a mask one after another (all under
 * way inside `riseFrames`) while every digit spins into place like an odometer.
 */
const Roll: React.FC<{ text: string; at: number; frames: number; size: number; color: string; pout: number;
  riseFrames?: number; font?: string }> = ({ text, at, frames, size, color, pout, riseFrames = 12, font = DISPLAY }) => {
  const frame = useCurrentFrame();
  const chars = Array.from(text);
  const digits = chars.filter((c) => /\d/.test(c)).length;
  const step = chars.length > 1 ? riseFrames / (chars.length - 1) : 0;
  let di = 0;
  const h = size;
  return (
    <span style={{ display: "inline-flex", alignItems: "flex-start", fontFamily: font, fontSize: size, lineHeight: 1,
      color, letterSpacing: "0.01em", fontVariantNumeric: "tabular-nums", whiteSpace: "pre" }}>
      {chars.map((c, i) => {
        const pin = ramp(frame, at + i * step, 12);
        const y = (1 - pin) * 110 + pout * 110;
        let inner: React.ReactNode = c;
        if (/\d/.test(c)) {
          const fromRight = digits - 1 - di;
          di += 1;
          const d = Number(c);
          const travel = (1 + Math.min(3, fromRight)) * 10 + d;
          const start = at + fromRight * 2;
          const pos = interpolate(frame, [start, start + Math.max(1, frames)], [0, 1], { ...clamp, easing: expoOut }) * travel;
          inner = (
            <span style={{ display: "inline-block", height: h, overflow: "hidden", position: "relative" }}>
              <span style={{ display: "flex", flexDirection: "column", transform: `translateY(${(-(pos % 10) * h).toFixed(2)}px)` }}>
                {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 0].map((n, j) => (
                  <span key={j} style={{ height: h, display: "block" }}>{n}</span>
                ))}
              </span>
            </span>
          );
        }
        return (
          <span key={i} style={{ display: "inline-block", overflow: "hidden", paddingBottom: "0.06em" }}>
            <span style={{ display: "inline-block", transform: `translateY(${y.toFixed(2)}%)`,
              opacity: pin < 0.02 || pout > 0.98 ? 0 : 1 }}>{inner}</span>
          </span>
        );
      })}
    </span>
  );
};

// ================================================================== 1. percent ring
/**
 * GoMotion's ring at the upper centre of the frame: the track draws, the accent
 * arc sweeps from 12 o'clock to value/total with a bright head, and the percent
 * rolls inside; a dark chip with the noun rises beneath it. On the hold the head
 * glows in a 1.6 s breath and the ring breathes ±1.5%; nothing else moves, so the
 * ring reads as one object across the cuts under it. Red below 25%, gold above.
 * No value: the chip text alone.
 */
const PercentRing: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const k = useK();
  const exit = useExit();
  const fin = useFin();
  const breath = useBreath(1.6);
  const value = toNum(overlay.value);
  const hasValue = Number.isFinite(value);
  const totalRaw = toNum(overlay.total);
  const total = Number.isFinite(totalRaw) && totalRaw > 0 ? totalRaw : 100;
  const frac = hasValue ? Math.max(0, Math.min(1, value / total)) : 0;
  const shown = hasValue ? (total === 100 ? value : (value / total) * 100) : 0;
  const suffix = S(overlay.suffix).trim() || "%";
  const col = frac < 0.25 ? RED : warm(accent);
  const compact = Boolean(overlay.compact);
  const s = compact ? 0.6 : 1;
  const centre = overlay.position === "center";
  const R = 120 * k * s, TW = 14 * k * s, SZ = (R + TW) * 2 + 24 * k * s;
  const C = 2 * Math.PI * R;
  const track = ramp(frame, 0, Math.round(fps * 0.5), inOut);
  const sweepAt = Math.round(fps * 0.15);
  const sweepF = Math.round(fps * 0.85);
  const sweep = ramp(frame, sweepAt, sweepF, inOut) * (1 - exit);
  const arc = frac * sweep;
  const land = sweepAt + sweepF;
  const ang = -Math.PI / 2 + arc * Math.PI * 2;
  const hx = SZ / 2 + Math.cos(ang) * R, hy = SZ / 2 + Math.sin(ang) * R;
  const settled = ramp(frame, land, 8);
  const glow = 0.45 + 0.55 * (settled * breath + (1 - settled));
  const scale = 1 + settled * 0.015 * Math.sin(((frame / fps) / 3.2) * Math.PI * 2);
  const text = cap(overlay.text);
  const chipLines = text ? lines(text, 30).slice(0, 2) : [];
  const sub = S(overlay.subtitle).trim();
  const chipAt = hasValue ? Math.round(fps * 0.45) : 4;
  const spot: React.CSSProperties = centre
    ? { left: "50%", top: "50%", transform: "translate(-50%, -50%)" }
    : compact ? { right: 80 * k, top: 60 * k }
      : { left: "50%", top: 70 * k, transform: "translateX(-50%)" };
  const poolX = centre ? 50 : compact ? 100 - ((80 * k + SZ / 2) / width) * 100 : 50;
  const poolY = centre ? 50 : ((( compact ? 60 : 70) * k + SZ * 0.62) / height) * 100;
  const id = `psring${overlay.startFrame ?? 0}`;
  return (
    <AbsoluteFill style={{ opacity: fin }}>
      <Pool ov={overlay} x={poolX} y={poolY} rx={compact ? 22 : 30} ry={compact ? 34 : 50} exit={exit} />
      <div style={{ position: "absolute", display: "flex", flexDirection: "column", alignItems: "center",
        gap: 14 * k * s, ...spot }}>
        {hasValue ? (
          <div style={{ position: "relative", width: SZ, height: SZ, transform: `scale(${scale.toFixed(4)})` }}>
            <svg width={SZ} height={SZ} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
              <defs>
                <filter id={`${id}g`} x="-60%" y="-60%" width="220%" height="220%">
                  <feGaussianBlur stdDeviation={8 * k * s} />
                </filter>
              </defs>
              <circle cx={SZ / 2} cy={SZ / 2} r={R} fill="rgba(6,8,12,.28)" opacity={track} />
              <circle cx={SZ / 2} cy={SZ / 2} r={R} fill="none" stroke="rgba(255,255,255,.18)" strokeWidth={TW}
                strokeLinecap="round" strokeDasharray={`${(C * track).toFixed(2)} ${C.toFixed(2)}`}
                transform={`rotate(-90 ${SZ / 2} ${SZ / 2})`} opacity={1 - exit * 0.6} />
              {arc > 0.0005 ? (
                <>
                  <circle cx={SZ / 2} cy={SZ / 2} r={R} fill="none" stroke={col} strokeWidth={TW * 1.6} strokeLinecap="round"
                    strokeDasharray={`${(C * arc).toFixed(2)} ${C.toFixed(2)}`} transform={`rotate(-90 ${SZ / 2} ${SZ / 2})`}
                    opacity={0.35 * glow} filter={`url(#${id}g)`} />
                  <circle cx={SZ / 2} cy={SZ / 2} r={R} fill="none" stroke={col} strokeWidth={TW} strokeLinecap="round"
                    strokeDasharray={`${(C * arc).toFixed(2)} ${C.toFixed(2)}`} transform={`rotate(-90 ${SZ / 2} ${SZ / 2})`} />
                  <circle cx={hx} cy={hy} r={TW * 0.95} fill="#fff" opacity={0.35 + 0.65 * glow} filter={`url(#${id}g)`} />
                  <circle cx={hx} cy={hy} r={TW * 0.42} fill="#fff" opacity={0.75 + 0.25 * glow} />
                </>
              ) : null}
            </svg>
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <MaskIO pin={ramp(frame, Math.round(fps * 0.1), 12)} pout={exit}>
                <Odometer value={Math.round(shown * 10) / 10} at={Math.round(fps * 0.2)} frames={Math.round(fps * 0.9)}
                  size={92 * k * s} color="#fff" suffix={suffix} suffixScale={0.5} suffixColor={col} />
              </MaskIO>
            </div>
          </div>
        ) : null}
        {chipLines.length ? (
          <MaskIO pin={ramp(frame, chipAt, 14)} pout={exit}>
            <div style={{ background: "rgba(10,12,16,.82)", borderRadius: 8 * k * s, padding: `${10 * k * s}px ${22 * k * s}px`,
              display: "flex", flexDirection: "column", alignItems: "center", gap: 4 * k * s,
              boxShadow: `0 ${8 * k}px ${24 * k}px rgba(0,0,0,.35)` }}>
              {chipLines.map((ln, i) => (
                <span key={i} style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: 24 * k * s,
                  letterSpacing: "0.2em", color: "#fff", whiteSpace: "nowrap", lineHeight: 1.15, textAlign: "center" }}>{ln}</span>
              ))}
              {sub ? (
                <span style={{ display: "block", fontFamily: MONO, fontWeight: 500, fontSize: 18 * k * s, letterSpacing: "0.1em",
                  color: "rgba(255,255,255,.7)", whiteSpace: "nowrap", lineHeight: 1.2 }}>{clip(sub, 40)}</span>
              ) : null}
            </div>
          </MaskIO>
        ) : sub ? (
          <MaskIO pin={ramp(frame, chipAt, 14)} pout={exit}>
            <span style={{ display: "block", fontFamily: MONO, fontWeight: 500, fontSize: 18 * k * s, letterSpacing: "0.1em",
              color: "rgba(255,255,255,.8)", whiteSpace: "nowrap", textShadow: "0 2px 10px rgba(0,0,0,.7)" }}>{clip(sub, 40)}</span>
          </MaskIO>
        ) : null}
      </div>
      {hasValue && frac > 0 ? <Tick at={land - 2} volume={0.3} /> : null}
    </AbsoluteFill>
  );
};

// ================================================================== 2. stat ride
/**
 * A bare bold figure on the footage the way GoMotion sets "3,491 FEET": no box,
 * no pill, the number in DISPLAY white with a deep shadow over a soft pool, the
 * unit in the accent, the noun beneath (or inline after a bare one-word noun).
 * Rises out of its mask letter by letter while the digits roll; a 2-3 px drift
 * on the hold; sinks back into the mask to leave. No value: the noun alone.
 */
const fmtStat = (v: number, hasUnit: boolean): string => {
  const neg = v < 0;
  const a = Math.abs(v);
  let s: string;
  if (!Number.isInteger(a)) {
    const raw = String(a);
    const dec = raw.includes(".") ? Math.min(3, raw.split(".")[1].length) : 2;
    s = a.toFixed(dec);
  } else if (!hasUnit && a >= 1500 && a <= 2100) {
    s = String(a);
  } else if (a >= 100000 || (a >= 10000 && a % 1000 === 0)) {
    const [div, suf] = a >= 1e9 ? [1e9, "B"] : a >= 1e6 ? [1e6, "M"] : [1e3, "K"];
    const q = a / div;
    s = `${q >= 100 ? Math.round(q) : Math.round(q * 10) / 10}${suf}`;
  } else {
    s = a.toLocaleString("en-US");
  }
  return `${neg ? "−" : ""}${s}`;
};

const StatRide: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const k = useK();
  const exit = useExit();
  const fin = useFin();
  const value = toNum(overlay.value);
  const hasValue = Number.isFinite(value);
  const prefix = S(overlay.prefix).trim();
  const suffix = cap(overlay.suffix);
  const noun = cap(overlay.text);
  const sub = S(overlay.subtitle).trim();
  const compact = Boolean(overlay.compact);
  const centre = overlay.position === "center";
  const size = (centre ? 220 : 150) * k * (compact ? 0.5 : 1);
  const inline = hasValue && !suffix && noun.length > 0 && !noun.includes(" ") && noun.length <= 12;
  const figure = hasValue ? `${prefix}${fmtStat(value, Boolean(suffix) || Boolean(prefix))}` : "";
  const word = hasValue ? (inline ? noun : "") : clip(noun || cap(sub), 18);
  const line2 = hasValue && !inline ? clip(noun, 26) : "";
  const line3 = hasValue ? sub : (noun ? sub : "");
  if (!figure && !word) return null;
  const drift = 2.5 * k * Math.sin(((frame / fps) / 3.4) * Math.PI * 2);
  const at0 = 2;
  const align: "center" | "right" = centre ? "center" : "right";
  const spot: React.CSSProperties = centre
    ? { left: "50%", top: "50%", transform: `translate(-50%, -50%) translateY(${drift.toFixed(2)}px)` }
    : { right: 100 * k, top: 80 * k, transform: `translateY(${drift.toFixed(2)}px)` };
  const poolX = centre ? 50 : 100 - ((100 * k + (compact ? 260 : 420) * k) / width) * 100;
  const poolY = centre ? 50 : ((80 * k + size * 0.7) / height) * 100;
  const unitPx = size * 0.42;
  return (
    <AbsoluteFill style={{ opacity: fin }}>
      <Pool ov={overlay} x={poolX} y={poolY} rx={centre ? 34 : compact ? 20 : 28} ry={centre ? 46 : compact ? 26 : 34} exit={exit} />
      <div style={{ position: "absolute", display: "flex", flexDirection: "column", gap: 6 * k,
        alignItems: align === "center" ? "center" : "flex-end", textShadow: "0 6px 30px rgba(0,0,0,.75)", ...spot }}>
        <div style={{ display: "flex", alignItems: "flex-end", gap: 0.18 * size, whiteSpace: "nowrap" }}>
          {figure ? (
            <Roll text={figure} at={at0} frames={Math.round(fps * 0.6)} size={size} color="#fff" pout={exit} />
          ) : null}
          {suffix ? (
            <MaskIO pin={ramp(frame, at0 + 6, 12)} pout={exit} style={{ marginBottom: size * 0.16 }}>
              <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: unitPx, letterSpacing: "0.12em",
                lineHeight: 1, color: accent }}>{clip(suffix, 14)}</span>
            </MaskIO>
          ) : null}
          {word ? (
            <Roll text={word} at={figure ? at0 + 6 : at0} frames={1} size={figure ? unitPx : size} color={figure ? accent : "#fff"}
              pout={exit} font={figure ? LABEL : DISPLAY} />
          ) : null}
        </div>
        {line2 ? (
          <MaskIO pin={ramp(frame, at0 + 6, 12)} pout={exit}>
            <span style={{ display: "block", fontFamily: LABEL, fontWeight: 700, fontSize: 36 * k * (compact ? 0.5 : 1),
              letterSpacing: "0.2em", lineHeight: 1.1, color: "#fff", whiteSpace: "nowrap", textAlign: align }}>{line2}</span>
          </MaskIO>
        ) : null}
        {line3 ? (
          <MaskIO pin={ramp(frame, at0 + 12, 12)} pout={exit}>
            <span style={{ display: "block", fontFamily: MONO, fontWeight: 500, fontSize: 22 * k * (compact ? 0.5 : 1),
              letterSpacing: "0.1em", lineHeight: 1.2, color: "rgba(255,255,255,.72)", whiteSpace: "nowrap",
              textAlign: align }}>{clip(line3, 40)}</span>
          </MaskIO>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 3. paper checklist
/** A hand-drawn square (a slight wobble on every side) in a 40 x 40 box. */
const boxPath = (i: number): string => {
  const w = (j: number) => (rnd(i * 7 + j) - 0.5) * 3.2;
  return `M${(4 + w(1)).toFixed(1)} ${(4 + w(2)).toFixed(1)} L${(36 + w(3)).toFixed(1)} ${(3 + w(4)).toFixed(1)} ` +
    `L${(37 + w(5)).toFixed(1)} ${(36 + w(6)).toFixed(1)} L${(3 + w(7)).toFixed(1)} ${(37 + w(8)).toFixed(1)} Z`;
};
const TICK = "M8 21 L17 30 L34 9";

/**
 * A cream paper card pinned top-right, a red header tab with the title, rows in
 * a handwritten face with wobbly boxes at their left. The card slides down and
 * settles, the rows rise 4 frames apart, then one by one each box fills with the
 * accent and a tick draws through it with a small pop. On the hold the shadow
 * breathes; to leave, the card lifts off its pin and slides out to the right.
 * No items: the tab and an empty sheet; no text: the tab reads NOTES.
 */
const PaperChecklist: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur, width, height } = useVideoConfig();
  const k = useK();
  const exit = useExit();
  const fin = useFin();
  const breath = useBreath(2.4);
  const rows = itemsOf(overlay, 6);
  const n = rows.length;
  const title = cap(overlay.text) || "NOTES";
  const label = cap(overlay.label);
  const sub = S(overlay.subtitle).trim();
  const compact = Boolean(overlay.compact);
  const s = compact ? 0.7 : 1;
  const W = 520 * k * s, TABH = 64 * k * s, ROW = 72 * k * s;
  const H = (120 + 72 * n) * k * s + (sub ? 16 * k * s : 0);
  const settle = ramp(frame, 0, 18, backOut);
  const lift = exit;
  const y0 = -40 * k * (1 - settle) - 10 * k * lift;
  const x0 = (W + 260 * k) * lift;
  const rowsAt = 10;
  const tickStart = rowsAt + n * 4 + Math.round(fps * 0.45);
  const room = dur - EXIT - 8 - tickStart;
  const step = n > 0 ? Math.max(6, Math.min(Math.round(fps * 0.55), Math.floor(room / n))) : 0;
  const drawF = Math.max(6, Math.min(12, Math.round(step * 0.6)));
  const right = 90 * k, top = 70 * k;
  const poolX = 100 - ((right + W / 2) / width) * 100;
  const poolY = ((top + H / 2) / height) * 100;
  const fibre = `repeating-linear-gradient(0deg, rgba(120,90,40,.05) 0px, rgba(120,90,40,.05) 1px, transparent 1px, transparent 7px), ` +
    `repeating-linear-gradient(90deg, rgba(120,90,40,.04) 0px, rgba(120,90,40,.04) 1px, transparent 1px, transparent 11px), ${PAPER}`;
  return (
    <AbsoluteFill style={{ opacity: fin }}>
      <Pool ov={overlay} x={poolX} y={poolY} rx={26} ry={Math.min(60, 22 + n * 5)} exit={exit} />
      <div style={{ position: "absolute", right, top, width: W, height: H, transformOrigin: "50% 0%",
        transform: `translate(${x0.toFixed(2)}px, ${y0.toFixed(2)}px) rotate(${(-2 + 3 * lift).toFixed(2)}deg)`,
        opacity: settle < 0.02 ? 0 : 1 }}>
        <div style={{ position: "absolute", inset: 0, background: fibre, borderRadius: 3 * k,
          boxShadow: `0 ${(18 + 4 * breath) * k}px ${(40 + 10 * breath) * k}px rgba(0,0,0,${(0.45 - 0.06 * breath).toFixed(3)})` }} />
        <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: TABH, background: TAB, borderRadius: `${3 * k}px ${3 * k}px 0 0`,
          display: "flex", alignItems: "center", justifyContent: "space-between", padding: `0 ${22 * k * s}px`,
          boxShadow: `0 ${2 * k}px ${6 * k}px rgba(0,0,0,.25)` }}>
          <MaskIO pin={ramp(frame, 4, 12)} pout={exit}>
            <span style={{ display: "block", fontFamily: DISPLAY, fontSize: 34 * k * s, letterSpacing: "0.08em", color: "#fff",
              lineHeight: 1, whiteSpace: "nowrap" }}>{clip(title, label ? 18 : 26)}</span>
          </MaskIO>
          {label ? (
            <MaskIO pin={ramp(frame, 8, 12)} pout={exit}>
              <span style={{ display: "block", fontFamily: LABEL, fontWeight: 700, fontSize: 15 * k * s, letterSpacing: "0.14em",
                color: "rgba(255,255,255,.78)", lineHeight: 1, whiteSpace: "nowrap" }}>{clip(label, 16)}</span>
            </MaskIO>
          ) : null}
        </div>
        {rows.map((row, i) => {
          const at = rowsAt + i * 4;
          const pin = ramp(frame, at, 14);
          const tAt = tickStart + i * step;
          const fill = ramp(frame, tAt, 8);
          const draw = ramp(frame, tAt + 3, drawF, inOut);
          const BS = 40 * k * s;
          return (
            <div key={i} style={{ position: "absolute", left: 28 * k * s, right: 22 * k * s, top: TABH + 22 * k * s + i * ROW,
              height: ROW, display: "flex", alignItems: "center", gap: 20 * k * s, opacity: pin,
              transform: `translateY(${((1 - pin) * 16 * k).toFixed(2)}px)` }}>
              <svg width={BS} height={BS} viewBox="0 0 40 40" style={{ overflow: "visible", flexShrink: 0 }}>
                <path d={boxPath(i)} fill={accent} opacity={fill * 0.95} />
                <path d={boxPath(i)} fill="none" stroke={INK} strokeWidth={2.2} strokeLinejoin="round" opacity={0.85} />
                {draw > 0.001 ? (
                  <path d={TICK} fill="none" stroke="#fff" strokeWidth={4.2} strokeLinecap="round" strokeLinejoin="round"
                    pathLength={1} strokeDasharray={1} strokeDashoffset={1 - draw} />
                ) : null}
              </svg>
              <span style={{ fontFamily: HAND, fontWeight: 700, fontSize: 38 * k * s, color: INK, lineHeight: 1.05,
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                opacity: 1 - 0.28 * fill }}>{row}</span>
              <Tick at={tAt} volume={0.2} />
            </div>
          );
        })}
        {sub ? (
          <div style={{ position: "absolute", left: 28 * k * s, right: 22 * k * s, bottom: 14 * k * s }}>
            <MaskIO pin={ramp(frame, rowsAt + n * 4 + 4, 12)} pout={exit}>
              <span style={{ display: "block", fontFamily: MONO, fontWeight: 500, fontSize: 17 * k * s, letterSpacing: "0.08em",
                color: "rgba(42,33,24,.62)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                lineHeight: 1.2 }}>{clip(sub, 44)}</span>
            </MaskIO>
          </div>
        ) : null}
      </div>
      {/* The push-pin: stays on the footage while the card lifts away. */}
      <div style={{ position: "absolute", right: right + W / 2 - 9 * k, top: top - 6 * k, width: 18 * k, height: 18 * k,
        borderRadius: "50%", background: `radial-gradient(circle at 35% 35%, #fff6 0%, ${accent} 45%, rgba(0,0,0,.35) 100%)`,
        boxShadow: `0 ${3 * k}px ${8 * k}px rgba(0,0,0,.5)`, opacity: ramp(frame, 6, 8) * (1 - ramp(frame, dur - 5, 4)) }} />
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "ps-percent-ring": PercentRing,
  "ps-stat-ride": StatRide,
  "ps-paper-checklist": PaperChecklist,
};
