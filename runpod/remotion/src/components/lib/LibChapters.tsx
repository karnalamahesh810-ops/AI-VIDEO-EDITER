import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { geoGraticule10, geoOrthographic, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import topology from "world-atlas/countries-110m.json";
import { DISPLAY, LABEL, MONO } from "../fonts";
import type { MapLocation, Overlay } from "../../types";
import { LetterLine, Scrim, lines, ramp, useHold, useK } from "../pro/ProGraphics";
import { CaseBackdrop } from "../pro/ProCase";

/**
 * Titles and chapter cards (family "ch-"). Ten looks, each with its own
 * motion hook; all text rises out of a mask (letter by letter or by line) and
 * leaves the same way in the last half second.
 *
 *   ch-number-roll     huge chapter number spinning into place, title beside
 *                      an accent rule, chapter progress segments below
 *   ch-part-divider    two rules drawing from the centre outward, "PART II"
 *                      set into the top rule, the title between them
 *   ch-episode-card    a dark card flipping in (3D), its outline number
 *                      drawing on stroke by stroke, a light sheen across
 *   ch-letterbox       cinema bars slide in over the footage, the title
 *                      tracking out slowly in the gap, bars leave
 *   ch-glitch-resolve  RGB-split slices snapping into the clean title in
 *                      ~14 frames, then it holds clean
 *   ch-chrome-sweep    a chrome title on a studio floor with its reflection,
 *                      a light band sweeping across the letters
 *   ch-fraction-tag    "02 / 05" digits rolling low-left over the footage,
 *                      the slash drawing, chapter segments beneath
 *   ch-coordinates     a mini globe spinning to the place, brackets locking,
 *                      the lat/lon readout ticking to its value
 *   ch-year-tape       a mechanical year counter rolling up to the year over
 *                      a scrolling timeline tape, on a light card
 *   ch-countdown       3-2-1 ring countdown; the ring bursts and shrinks into
 *                      an emblem above the chapter title
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;

// ================================================================== shared
const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const expoIn = Easing.bezier(0.7, 0, 0.84, 0);
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const INK = "#141518";
const CYAN = "#53c8ff";
const DIGITS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 0];

/** Any text field as a plain string (a finite number becomes its digits, anything else is empty). */
const str = (s: unknown): string =>
  typeof s === "string" ? s : typeof s === "number" && Number.isFinite(s) ? String(s) : "";
const cap = (s?: unknown): string => str(s).replace(/\s+/g, " ").trim().toUpperCase();
const pad2 = (n: number): string => String(n).padStart(2, "0");
/** A single-line label of at most `max` characters, cut at a word with an ellipsis. */
const clip = (s: string, max: number): string => {
  const chars = Array.from(s);
  if (chars.length <= max) return s;
  const head = lines(s, max - 1)[0] || "";
  const cut = head && Array.from(head).length <= max - 1 ? head : chars.slice(0, max - 1).join("");
  return `${cut.replace(/[\s,;:·-]+$/, "")}…`;
};

/** "#d6a83c" / "rgb(214,168,60)" -> "rgba(214,168,60,a)"; anything else falls back to the house gold. */
const withAlpha = (c: string, a: number): string => {
  const s = (c || "").trim();
  const rgb = /^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)/i.exec(s);
  if (rgb) return `rgba(${rgb[1]},${rgb[2]},${rgb[3]},${a})`;
  const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(s);
  if (!m) return `rgba(214,168,60,${a})`;
  let h = m[1];
  if (h.length === 3) h = h.split("").map((x) => x + x).join("");
  const n = parseInt(h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
};

/** Deterministic 0..1 noise from an integer seed (one mulberry32 step). */
const rnd = (seed: number): number => {
  let t = (Math.imul(Math.floor(seed) | 0, 0x6d2b79f5) + 0x9e3779b9) | 0;
  t = Math.imul(t ^ (t >>> 15), t | 1);
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};

/**
 * A title's size and lines: shrinks from `big` until it fits `maxLines` and
 * no single word runs past the line width (a long word sits alone on a line).
 */
const fit = (text: string, big: number, chars: number, maxLines: number): { size: number; ls: string[] } => {
  const longest = (xs: string[]): number => Math.max(0, ...xs.map((x) => Array.from(x).length));
  let size = big;
  let per = chars;
  let ls = lines(text, per);
  while ((ls.length > maxLines || longest(ls) > per) && size > 50) {
    size -= 6;
    per = Math.round((chars * big) / size);
    ls = lines(text, per);
  }
  if (ls.length > maxLines) {
    ls = ls.slice(0, maxLines);
    ls[maxLines - 1] = `${ls[maxLines - 1]}…`;
  }
  return { size, ls };
};

/** Letter stagger so any line lands inside ~0.9 s. */
const stepFor = (t: string): number => Math.max(0.4, Math.min(1, 14 / Math.max(1, Array.from(t).length)));
/**
 * When a line's letters start dropping so the last one is gone by the final
 * frame (LetterLine drops one letter every 0.6 frames over 9 frames). The
 * floor lets lines of up to ~48 characters finish; labels are clipped shorter.
 */
const outFor = (t: string, D: number): number =>
  Math.max(D - 40, D - 11 - Math.ceil(Math.max(0, Array.from(t).length - 1) * 0.6));

/** LetterLine with an in-stagger and an out-time fitted to the line's length. */
const Letters: React.FC<{ text: string; at: number; style: React.CSSProperties }> = ({ text, at, style }) => {
  const { durationInFrames } = useVideoConfig();
  return <LetterLine text={text} at={at} step={stepFor(text)} outAt={outFor(text, durationInFrames)} style={style} />;
};

/** A line rising out of its mask, and rising away through it at the end. */
const Rise: React.FC<{ at: number; frames?: number; outAt?: number; style?: React.CSSProperties;
  children: React.ReactNode }> = ({ at, frames = 16, outAt, style, children }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const pin = ramp(frame, at, frames);
  const pout = ramp(frame, outAt ?? durationInFrames - 13, 10, expoIn);
  return (
    <div style={{ overflow: "hidden", paddingBottom: "0.08em", ...style }}>
      <div style={{ transform: `translateY(${(1 - pin) * 110 - pout * 110}%)` }}>{children}</div>
    </div>
  );
};

/** Exit progress: 0 while the graphic holds, 1 once it has left. */
const useExit = (lead = 12, frames = 10): number => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return ramp(frame, durationInFrames - lead, frames, expoIn);
};

/** An own backdrop: always on as a full-screen scene, a quick dissolve over footage. */
const useBackdrop = (ov: Overlay): number => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  if (ov.fullFrame) return 1;
  return ramp(frame, 0, 7) * (1 - ramp(frame, durationInFrames - 9, 9, inOut));
};

/**
 * Digits that spin into place (leading zeros kept, "03"): each column turns
 * one to three times, left digit first, with a ghosted motion trail instead
 * of a blur filter.
 */
const SpinDigits: React.FC<{ text: string; at: number; frames: number; size: number; color: string;
  ghost?: string; stagger?: number }> = ({ text, at, frames, size, color, ghost, stagger = 3 }) => {
  const frame = useCurrentFrame();
  const chars = Array.from(text);
  const count = chars.filter((c) => /\d/.test(c)).length;
  const trail = ghost || withAlpha(color, 0.32);
  let di = 0;
  return (
    <span style={{ display: "inline-flex", fontFamily: DISPLAY, fontSize: size, lineHeight: 1, color,
      fontVariantNumeric: "tabular-nums", letterSpacing: "0.01em" }}>
      {chars.map((c, i) => {
        if (!/\d/.test(c)) return <span key={i}>{c}</span>;
        const order = di;
        di += 1;
        const travel = (1 + Math.min(2, count - 1 - order)) * 10 + Number(c);
        const start = at + order * stagger;
        const pos = ramp(frame, start, frames) * travel;
        const prev = ramp(frame - 1, start, frames) * travel;
        const sp = Math.min(1.3, Math.abs(pos - prev));
        const sh = sp > 0.04
          ? `0 ${sp * size * 0.16}px ${sp * size * 0.06}px ${trail}, 0 ${-sp * size * 0.16}px ${sp * size * 0.06}px ${trail}`
          : undefined;
        return (
          <span key={i} style={{ display: "inline-block", height: size, overflow: "hidden" }}>
            <span style={{ display: "flex", flexDirection: "column", transform: `translateY(${-(pos % 10) * size}px)`,
              textShadow: sh }}>
              {DIGITS.map((d, j) => <span key={j} style={{ height: size, display: "block" }}>{d}</span>)}
            </span>
          </span>
        );
      })}
    </span>
  );
};

/**
 * A mechanical counter showing the continuous value `v`: the ones wheel runs
 * freely, every higher wheel only turns while the wheel below it rolls 9 -> 0.
 */
const MechDigits: React.FC<{ v: number; vp: number; digits: number; size: number; color: string; trail: string }> =
  ({ v, vp, digits, size, color, trail }) => {
    const wheel = (x: number, p: number): number => {
      if (p === 0) return x;
      const unit = Math.pow(10, p);
      const whole = Math.floor(x / unit);
      const lower = x - whole * unit;
      return whole + Math.max(0, lower - (unit - 1));
    };
    const places = Array.from({ length: digits }, (_, i) => digits - 1 - i);
    return (
      <span style={{ display: "inline-flex", fontFamily: DISPLAY, fontSize: size, lineHeight: 1, color,
        fontVariantNumeric: "tabular-nums", letterSpacing: "0.01em" }}>
        {places.map((p) => {
          const a = wheel(v, p);
          const sp = Math.min(1.5, Math.abs(a - wheel(vp, p)));
          const m = ((a % 10) + 10) % 10;
          const sh = sp > 0.04
            ? `0 ${sp * size * 0.14}px ${sp * size * 0.05}px ${trail}, 0 ${-sp * size * 0.14}px ${sp * size * 0.05}px ${trail}`
            : undefined;
          return (
            <span key={p} style={{ display: "inline-block", height: size, overflow: "hidden" }}>
              <span style={{ display: "flex", flexDirection: "column", transform: `translateY(${-m * size}px)`, textShadow: sh }}>
                {DIGITS.map((d, j) => <span key={j} style={{ height: size, display: "block" }}>{d}</span>)}
              </span>
            </span>
          );
        })}
      </span>
    );
  };

// ================================================================== 1. chapter number roll
const ChapterNumberRoll: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const ex = useExit();
  const bg = useBackdrop(overlay);
  const n = Math.round(Number(overlay.value ?? NaN));
  const title = cap(overlay.text);
  if (!Number.isFinite(n) || n < 0 || n > 999 || !title) return null;
  const total = Math.round(Number(overlay.total ?? NaN));
  const hasTotal = Number.isFinite(total) && total >= Math.max(2, n) && total <= 16;
  const num = pad2(n);
  const kicker = clip(cap(overlay.label), 30) || "CHAPTER";
  const { size, ls } = fit(title, 84, 18, 2);
  const sub = lines(str(overlay.subtitle), 46).slice(0, 2);
  // The number rises out of its mask while it spins (never sits static at "00" on frame 0).
  const numIn = ramp(frame, 0, 14);
  const numOut = ramp(frame, D - 15, 11, expoIn);
  const rule = ramp(frame, 8, 18) * (1 - ex);
  const drift = interpolate(frame, [0, D], [0, 1], clamp);
  const barAt = Math.round(fps * 0.5);
  const draw = ramp(frame, barAt, Math.round(fps * 0.8), inOut);
  const beam = interpolate(frame, [0, D], [-20, 120], clamp);
  const pulse = 0.85 + 0.15 * Math.sin(frame / (fps * 0.8));
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: bg,
        background: "radial-gradient(ellipse 90% 80% at 26% 48%, #1c1e24 0%, #0e0f12 50%, #060607 100%)" }}>
        <AbsoluteFill style={{ opacity: pulse,
          background: `radial-gradient(circle at 21% 48%, ${withAlpha(accent, 0.16)} 0%, rgba(0,0,0,0) 32%)` }} />
        <AbsoluteFill style={{ background: `linear-gradient(105deg, rgba(255,255,255,0) ${beam - 10}%, rgba(255,255,255,.035) ${beam}%, rgba(255,255,255,0) ${beam + 10}%)` }} />
      </AbsoluteFill>
      <AbsoluteFill style={{ justifyContent: "center", paddingLeft: 200 * k, paddingRight: 140 * k,
        transform: `scale(${hold})`, transformOrigin: "20% 50%" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 44 * k }}>
          <div style={{ overflow: "hidden", height: 200 * k, transform: `translateX(${-drift * 14 * k}px)` }}>
            <div style={{ transform: `translateY(${(1 - numIn) * 112 - numOut * 112}%)` }}>
              <SpinDigits text={num} at={3} frames={Math.round(fps * 1.0)} size={200 * k} color="#fff" />
            </div>
          </div>
          <div style={{ width: 4 * k, height: 190 * k, background: accent, transform: `scaleY(${rule})`,
            transformOrigin: "50% 0%", boxShadow: `0 0 ${16 * k}px ${withAlpha(accent, 0.55)}` }} />
          <div style={{ display: "flex", flexDirection: "column", gap: 6 * k, maxWidth: 1100 * k,
            transform: `translateX(${drift * 14 * k}px)` }}>
            <Letters text={kicker} at={10} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k,
              letterSpacing: "0.34em", color: accent, whiteSpace: "nowrap" }} />
            {ls.map((ln, i) => (
              <Letters key={i} text={ln} at={13 + i * 5} style={{ fontFamily: DISPLAY, fontSize: size * k, lineHeight: 0.98,
                letterSpacing: "0.02em", color: "#fff", whiteSpace: "nowrap" }} />
            ))}
            {sub.map((ln, i) => (
              <Rise key={`s${i}`} at={22 + i * 3} style={{ marginTop: i === 0 ? 8 * k : 0 }}>
                <span style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 30 * k, letterSpacing: "0.04em",
                  color: "rgba(255,255,255,.62)" }}>{ln}</span>
              </Rise>
            ))}
          </div>
        </div>
      </AbsoluteFill>
      <div style={{ position: "absolute", left: 200 * k, right: 200 * k, bottom: 150 * k, opacity: bg }}>
        <div style={{ height: 6 * k, clipPath: `inset(-${20 * k}px ${(1 - draw) * 100}% -${20 * k}px ${ex * 100}%)` }}>
          {hasTotal ? (
            <div style={{ display: "flex", gap: 8 * k, height: "100%" }}>
              {Array.from({ length: total }, (_, i) => {
                const done = i < n - 1;
                const cur = i === n - 1;
                const f = cur ? ramp(frame, barAt + 12, 22, inOut) : 0;
                return (
                  <div key={i} style={{ flex: 1, position: "relative", borderRadius: 3 * k, overflow: "hidden",
                    background: done ? "rgba(255,255,255,.72)" : "rgba(255,255,255,.16)" }}>
                    {cur ? <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${f * 100}%`,
                      background: accent }} /> : null}
                  </div>
                );
              })}
            </div>
          ) : (
            <div style={{ position: "relative", height: "100%" }}>
              <div style={{ position: "absolute", left: 0, right: 0, top: 2 * k, height: 2 * k, background: "rgba(255,255,255,.22)" }} />
              <div style={{ position: "absolute", left: 0, top: 0, height: 6 * k, width: 160 * k, borderRadius: 3 * k,
                background: accent }} />
            </div>
          )}
        </div>
        {hasTotal ? (
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 14 * k }}>
            <Rise at={barAt + 6}>
              <span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 24 * k, letterSpacing: "0.14em",
                color: "rgba(255,255,255,.62)" }}>
                {num}<span style={{ color: "rgba(255,255,255,.3)" }}> / </span>{pad2(total)}
              </span>
            </Rise>
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 2. part divider
const toRoman = (value: number): string => {
  const table: [number, string][] = [[1000, "M"], [900, "CM"], [500, "D"], [400, "CD"], [100, "C"], [90, "XC"],
    [50, "L"], [40, "XL"], [10, "X"], [9, "IX"], [5, "V"], [4, "IV"], [1, "I"]];
  let x = Math.round(value);
  let out = "";
  for (const [v, s] of table) {
    while (x >= v) {
      out += s;
      x -= v;
    }
  }
  return out;
};

/** One half of a divider rule, growing outward from its inner (centre) end. */
const HalfRule: React.FC<{ p: number; len: number; side: "l" | "r"; k: number }> = ({ p, len, side, k }) => (
  <div style={{ width: len, height: 14 * k, display: "flex", alignItems: "center",
    justifyContent: side === "l" ? "flex-end" : "flex-start" }}>
    <div style={{ position: "relative", width: len * p, height: 2 * k,
      background: side === "l" ? "linear-gradient(90deg, rgba(255,255,255,.25), rgba(255,255,255,.9))"
        : "linear-gradient(90deg, rgba(255,255,255,.9), rgba(255,255,255,.25))" }}>
      <div style={{ position: "absolute", left: side === "l" ? 0 : undefined, right: side === "r" ? 0 : undefined,
        top: -5 * k, width: 2 * k, height: 12 * k, background: "rgba(255,255,255,.6)", opacity: p > 0.96 ? 1 : 0 }} />
    </div>
  </div>
);

const Gem: React.FC<{ p: number; k: number; accent: string }> = ({ p, k, accent }) => (
  <div style={{ width: 12 * k, height: 12 * k, background: accent, transform: `rotate(45deg) scale(${p})`,
    boxShadow: `0 0 ${12 * k}px ${withAlpha(accent, 0.7)}` }} />
);

const PartDivider: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const ex = useExit();
  const bg = useBackdrop(overlay);
  const title = cap(overlay.text);
  if (!title) return null;
  const v = Math.round(Number(overlay.value ?? NaN));
  const roman = Number.isFinite(v) && v >= 1 && v <= 50 ? toRoman(v) : "";
  // Clipped so the kicker plus both 430px rules stays inside the safe area.
  const kicker = clip(cap(overlay.label), 26) || (roman ? `PART ${roman}` : "");
  const { size, ls } = fit(title, 82, 22, 2);
  const sub = lines(str(overlay.subtitle), 52).slice(0, 2);
  const HALF = 430 * k;
  const l1 = ramp(frame, 3, Math.round(fps * 0.6)) * (1 - ex);
  const l2 = ramp(frame, 10, Math.round(fps * 0.6)) * (1 - ex);
  const gem1 = ramp(frame, 0, 12, backOut) * (1 - ex);
  const gem2 = ramp(frame, 8, 12, backOut) * (1 - ex);
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: bg }}>
        <CaseBackdrop tone="dark" seed={7} />
        <AbsoluteFill style={{ background: "radial-gradient(ellipse 60% 50% at 50% 50%, rgba(3,8,18,.62) 0%, rgba(3,8,18,.25) 60%, rgba(0,0,0,.35) 100%)" }} />
      </AbsoluteFill>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 26 * k }}>
            <HalfRule p={l1} len={HALF} side="l" k={k} />
            {kicker ? (
              <Letters text={kicker} at={6} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 32 * k,
                letterSpacing: "0.42em", paddingLeft: "0.42em", color: accent, whiteSpace: "nowrap" }} />
            ) : <Gem p={gem1} k={k} accent={accent} />}
            <HalfRule p={l1} len={HALF} side="r" k={k} />
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", margin: `${34 * k}px 0 ${28 * k}px` }}>
            {ls.map((ln, i) => (
              <Letters key={i} text={ln} at={10 + i * 5} style={{ fontFamily: DISPLAY, fontSize: size * k, lineHeight: 1,
                letterSpacing: "0.05em", color: "#fff", textAlign: "center", whiteSpace: "nowrap",
                textShadow: "0 4px 16px rgba(0,0,0,.45)" }} />
            ))}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 22 * k }}>
            <HalfRule p={l2} len={HALF} side="l" k={k} />
            <Gem p={gem2} k={k} accent={accent} />
            <HalfRule p={l2} len={HALF} side="r" k={k} />
          </div>
          {sub.length ? (
            <div style={{ marginTop: 26 * k, display: "flex", flexDirection: "column", alignItems: "center" }}>
              {sub.map((ln, i) => (
                <Rise key={i} at={20 + i * 3}>
                  <span style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 30 * k, letterSpacing: "0.12em",
                    color: "rgba(220,232,248,.72)" }}>{cap(ln)}</span>
                </Rise>
              ))}
            </div>
          ) : null}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 3. episode card
const EpisodeCard: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const ex = useExit(14, 12);
  const title = cap(overlay.text);
  if (!title) return null;
  const n = Math.round(Number(overlay.value ?? NaN));
  const hasNum = Number.isFinite(n) && n >= 0 && n <= 999;
  const num = hasNum ? pad2(n) : "";
  const kicker = clip(cap(overlay.label), 24) || "EPISODE";
  const { size, ls } = fit(title, 70, 20, 3);
  const sub = lines(str(overlay.subtitle), 40).slice(0, 2);
  const flip = ramp(frame, 0, 24);
  const rotY = (1 - flip) * -62 + ex * 58 + Math.sin(frame / (fps * 1.6)) * 1.6 * (1 - ex);
  const rotX = (1 - flip) * 8 + Math.cos(frame / (fps * 2.1)) * 1.0;
  const cardOp = Math.min(1, flip * 3) * (1 - ex);
  const W = (hasNum ? 1240 : 1000) * k, H = 440 * k;
  const fs = (num.length > 2 ? 160 : 200) * k;
  const L = fs * 6;
  const drawP = ramp(frame, 8, Math.round(fps * 1.1), inOut) * (1 - ex);
  const glowIn = ramp(frame, 10 + fps, 20);
  const sweep = interpolate(frame, [16, 16 + Math.round(fps * 0.9)], [-40, 140], { ...clamp, easing: inOut });
  const topLine = ramp(frame, 12, 22, inOut);
  const divider = ramp(frame, 10, 18);
  const uline = ramp(frame, 20, 16);
  const numW = 400 * k;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", perspective: `${1800 * k}px` }}>
        <div style={{ position: "relative", width: W, height: H, borderRadius: 20 * k, overflow: "hidden", display: "flex",
          alignItems: "center", opacity: cardOp,
          transform: `translateX(${(1 - flip) * -80 * k}px) rotateY(${rotY}deg) rotateX(${rotX}deg) scale(${hold})`,
          background: "linear-gradient(135deg, #1d1f25 0%, #111216 48%, #0a0a0c 100%)",
          border: `${1.5 * k}px solid rgba(255,255,255,.12)`,
          boxShadow: `0 ${40 * k}px ${120 * k}px rgba(0,0,0,.65), inset 0 1px 0 rgba(255,255,255,.08)` }}>
          <div style={{ position: "absolute", left: 0, top: 0, height: 3 * k, width: `${topLine * 100}%`, background: accent }} />
          {hasNum ? (
            <div style={{ position: "relative", width: numW, height: "100%", flexShrink: 0, display: "flex",
              flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
              <div style={{ position: "absolute", inset: 0,
                background: `radial-gradient(circle at 50% 50%, ${withAlpha(accent, 0.2 * glowIn)} 0%, rgba(0,0,0,0) 62%)` }} />
              <svg width={numW} height={fs} style={{ position: "relative", overflow: "visible" }}>
                <text x={numW / 2} y={fs * 0.85} textAnchor="middle" fontFamily={DISPLAY} fontSize={fs} letterSpacing={6 * k}
                  fill={withAlpha(accent, 0.12 * glowIn)} stroke="#fff" strokeOpacity={0.92} strokeWidth={2.6 * k}
                  strokeLinejoin="round" strokeDasharray={`${L} ${L}`} strokeDashoffset={L * (1 - drawP)}
                  style={{ filter: `drop-shadow(0 0 ${8 * k}px ${withAlpha(accent, 0.5)})` }}>{num}</text>
              </svg>
              <div style={{ position: "relative", width: 90 * k * uline * (1 - ex), height: 4 * k, background: accent,
                marginTop: 12 * k }} />
            </div>
          ) : null}
          {hasNum ? (
            <div style={{ width: 1.5 * k, height: H * 0.62, background: "rgba(255,255,255,.14)", flexShrink: 0,
              transform: `scaleY(${divider})` }} />
          ) : null}
          <div style={{ position: "relative", flex: 1, display: "flex", flexDirection: "column", justifyContent: "center",
            gap: 6 * k, padding: `0 ${64 * k}px` }}>
            <Letters text={kicker} at={10} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 28 * k,
              letterSpacing: "0.34em", color: accent, whiteSpace: "nowrap" }} />
            {ls.map((ln, i) => (
              <Letters key={i} text={ln} at={14 + i * 5} style={{ fontFamily: DISPLAY, fontSize: size * k, lineHeight: 0.98,
                letterSpacing: "0.03em", color: "#fff", whiteSpace: "nowrap" }} />
            ))}
            {sub.map((ln, i) => (
              <Rise key={`s${i}`} at={24 + i * 3} style={{ marginTop: i === 0 ? 10 * k : 0 }}>
                <span style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 28 * k, letterSpacing: "0.04em",
                  color: "rgba(255,255,255,.6)" }}>{ln}</span>
              </Rise>
            ))}
          </div>
          <div style={{ position: "absolute", inset: 0,
            background: `linear-gradient(105deg, rgba(255,255,255,0) ${sweep - 14}%, rgba(255,255,255,.08) ${sweep - 4}%, rgba(255,255,255,.2) ${sweep}%, rgba(255,255,255,.08) ${sweep + 4}%, rgba(255,255,255,0) ${sweep + 14}%)` }} />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 4. letterbox title
const LetterboxTitle: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const title = cap(overlay.text);
  if (!title) return null;
  // 2.5:1 bars; the bar text sits against the picture edge so it stays >= 90px inside the frame.
  const BAR = 146 * k;
  const bars = ramp(frame, 0, Math.round(fps * 0.55)) * (1 - ramp(frame, D - 12, 11, expoIn));
  const { size, ls } = fit(title, 80, 22, 2);
  const track = interpolate(frame, [0, D], [0.1, 0.17], clamp);
  const kicker = clip(cap(overlay.label), 40);
  const sub = clip(cap(overlay.subtitle), 40);
  const rule = ramp(frame, 14, 20) * (1 - ramp(frame, D - 14, 10, expoIn));
  const dash = ramp(frame, 8, 16) * (1 - ramp(frame, D - 14, 10, expoIn));
  const shade = ramp(frame, 0, 12) * (1 - ramp(frame, D - 12, 11));
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: shade,
        background: "radial-gradient(ellipse 50% 32% at 50% 50%, rgba(0,0,0,.42) 0%, rgba(0,0,0,0) 100%)" }} />
      <AbsoluteFill style={{ top: BAR, bottom: BAR, height: "auto", alignItems: "center", justifyContent: "center",
        transform: `scale(${hold})` }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
          {ls.map((ln, i) => (
            <Letters key={i} text={ln} at={8 + i * 5} style={{ fontFamily: DISPLAY, fontSize: size * k, lineHeight: 1,
              letterSpacing: `${track}em`, paddingLeft: `${track}em`, color: "#fff", textAlign: "center", whiteSpace: "nowrap",
              textShadow: "0 4px 18px rgba(0,0,0,.6)" }} />
          ))}
          <div style={{ width: 180 * k, height: 3 * k, marginTop: 16 * k, background: accent, transform: `scaleX(${rule})`,
            boxShadow: `0 0 ${12 * k}px ${withAlpha(accent, 0.6)}` }} />
        </div>
      </AbsoluteFill>
      <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: BAR, background: "#000",
        transform: `translateY(${-(1 - bars) * 100}%)`, boxShadow: `0 0 ${40 * k}px rgba(0,0,0,.5)` }}>
        <div style={{ position: "absolute", left: 110 * k, right: 110 * k, bottom: 20 * k, display: "flex",
          alignItems: "center", gap: 20 * k }}>
          <div style={{ width: 48 * k, height: 3 * k, flexShrink: 0, background: accent, transform: `scaleX(${dash})`,
            transformOrigin: "0 50%" }} />
          {kicker ? (
            <Letters text={kicker} at={10} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 26 * k, lineHeight: 1.15,
              letterSpacing: "0.34em", color: "rgba(255,255,255,.78)", whiteSpace: "nowrap" }} />
          ) : null}
        </div>
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: BAR, background: "#000",
        transform: `translateY(${(1 - bars) * 100}%)`, boxShadow: `0 0 ${40 * k}px rgba(0,0,0,.5)` }}>
        {sub ? (
          <div style={{ position: "absolute", left: 110 * k, right: 110 * k, top: 20 * k, display: "flex",
            justifyContent: "flex-end", alignItems: "center" }}>
            <Letters text={sub} at={16} style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 26 * k, lineHeight: 1.15,
              letterSpacing: "0.24em", color: "rgba(255,255,255,.6)", whiteSpace: "nowrap" }} />
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 5. glitch resolve
const GlitchResolve: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: D } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const ex = useExit();
  const title = cap(overlay.text);
  if (!title) return null;
  const { size, ls } = fit(title, 84, 20, 2);
  const kicker = clip(cap(overlay.label), 36);
  const sub = lines(str(overlay.subtitle), 50).slice(0, 2);
  const END = 14;
  const g = interpolate(frame, [0, 4, 8, END], [1, 0.9, 0.45, 0], clamp);
  const glitching = g > 0.001;
  const step = Math.floor(frame / 2);
  const S = 6;
  // Share of slices dropped out: sparse flicker on the first frames, then the full glitch resolving.
  const sparse = 0.22 + 0.45 * (1 - ramp(frame, 0, 5));
  const lineStyle: React.CSSProperties = { fontFamily: DISPLAY, fontSize: size * k, lineHeight: 1, letterSpacing: "0.05em",
    whiteSpace: "nowrap" };
  // A copy of the title block laid out exactly like the clean lines below.
  const copy = (color: string, dx: number, key: string, opacity: number) => (
    <div key={key} style={{ position: "absolute", left: 0, right: 0, top: 0, bottom: 0, display: "flex",
      flexDirection: "column", alignItems: "center", color, opacity, transform: `translateX(${dx}px)` }}>
      {ls.map((ln, i) => (
        <div key={i} style={{ overflow: "hidden", paddingBottom: "0.08em" }}>
          <div><span style={lineStyle}>{ln}</span></div>
        </div>
      ))}
    </div>
  );
  const bounds = Array.from({ length: S + 1 }, (_, i) =>
    i === 0 ? -30 : i === S ? 130 : (i / S) * 100 + (rnd(i * 31 + step * 7) - 0.5) * (100 / S) * 0.9 * g);
  const rule = ramp(frame, END, 16) * (1 - ex);
  const scan = interpolate(frame, [0, END], [-10, 110], clamp);
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      {glitching ? (
        <AbsoluteFill style={{ opacity: g * 0.9,
          background: "repeating-linear-gradient(0deg, rgba(255,255,255,.05) 0px, rgba(255,255,255,.05) 1px, rgba(0,0,0,0) 1px, rgba(0,0,0,0) 4px)" }} />
      ) : null}
      {glitching ? [0, 1].map((t) => (
        <div key={t} style={{ position: "absolute", top: `${28 + rnd(step * 19 + t * 5) * 44}%`,
          left: `${rnd(step * 23 + t * 3) * 55}%`, width: `${18 + rnd(step * 29 + t) * 26}%`, height: 2 * k,
          background: t ? accent : CYAN, opacity: 0.75 * g }} />
      )) : null}
      {glitching ? (
        <div style={{ position: "absolute", left: 0, right: 0, top: `${scan}%`, height: 1.5 * k, background: CYAN,
          opacity: 0.6 * g, boxShadow: `0 0 ${10 * k}px ${CYAN}` }} />
      ) : null}
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
          {kicker ? (
            <Letters text={`[ ${kicker} ]`} at={8} style={{ fontFamily: MONO, fontWeight: 700, fontSize: 24 * k,
              letterSpacing: "0.3em", paddingLeft: "0.3em", color: accent, whiteSpace: "nowrap", marginBottom: 18 * k }} />
          ) : null}
          <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "center" }}>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", color: "#fff",
              opacity: glitching ? 0 : 1, textShadow: "0 4px 16px rgba(0,0,0,.5)" }}>
              {ls.map((ln, i) => (
                <Rise key={i} at={-40} outAt={D - 13 + i * 2}>
                  <span style={lineStyle}>{ln}</span>
                </Rise>
              ))}
            </div>
            {glitching ? (
              <div style={{ position: "absolute", inset: 0, transform: `translateY(${(rnd(step * 3 + 1) - 0.5) * 8 * k * g}px)` }}>
                {Array.from({ length: S }, (_, s) => {
                  if (rnd(s * 17 + step * 5) < sparse * g) return null;
                  const strong = rnd(s * 7 + step * 11) > 0.5;
                  const dx = (rnd(s * 53 + step * 13) - 0.5) * 2 * (strong ? 80 : 14) * k * g;
                  const split = (6 + 10 * rnd(s * 29 + step)) * k * g;
                  return (
                    <div key={s} style={{ position: "absolute", inset: 0,
                      clipPath: `inset(${bounds[s]}% -30% ${100 - bounds[s + 1]}% -30%)` }}>
                      {copy(CYAN, dx - split, "c", 0.9)}
                      {copy(accent, dx + split, "a", 0.9)}
                      {copy("#fff", dx, "w", 1)}
                    </div>
                  );
                })}
              </div>
            ) : null}
          </div>
          <div style={{ width: 220 * k, height: 3 * k, marginTop: 20 * k, background: accent, transform: `scaleX(${rule})`,
            boxShadow: `0 0 ${12 * k}px ${withAlpha(accent, 0.6)}` }} />
          {sub.map((ln, i) => (
            <Rise key={`s${i}`} at={END + 4 + i * 3} style={{ marginTop: i === 0 ? 16 * k : 0 }}>
              <span style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 30 * k, letterSpacing: "0.06em",
                color: "rgba(255,255,255,.7)" }}>{ln}</span>
            </Rise>
          ))}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 6. chrome sweep
const CHROME: React.CSSProperties = {
  backgroundImage: "linear-gradient(180deg, #ffffff 0%, #f1f2f5 28%, #a3a8b1 50%, #5d626b 54%, #c9ccd2 72%, #ffffff 100%)",
  WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent", WebkitTextFillColor: "transparent",
};
const BAND = "linear-gradient(100deg, rgba(255,255,255,0) 43%, rgba(255,255,255,.95) 50%, rgba(255,255,255,0) 57%)";

const ChromeSweep: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const ex = useExit();
  const bg = useBackdrop(overlay);
  const title = cap(overlay.text);
  if (!title) return null;
  const { size, ls } = fit(title, 86, 20, 2);
  const kicker = clip(cap(overlay.label), 36);
  const sub = clip(cap(overlay.subtitle), 46);
  const lineAt = (i: number) => 6 + i * 5;
  // Tracking-in: the letters close up from wide spacing as each line rises.
  const track = (i: number) => 0.3 - 0.22 * ramp(frame, lineAt(i), 28);
  const s1 = interpolate(frame, [14, 14 + Math.round(fps * 0.9)], [1, 0], { ...clamp, easing: inOut });
  const s2At = Math.round(D * 0.58);
  const s2 = interpolate(frame, [s2At, s2At + Math.round(fps * 1.1)], [1, 0], { ...clamp, easing: inOut });
  const floor = ramp(frame, 10, 24, inOut) * (1 - ex);
  const spot = 50 + Math.sin(frame / (fps * 2.4)) * 6;
  const block = (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
      {ls.map((ln, i) => {
        const t = track(i);
        const face: React.CSSProperties = { display: "inline-block", fontFamily: DISPLAY, fontSize: size * k, lineHeight: 1,
          letterSpacing: `${t}em`, whiteSpace: "nowrap" };
        return (
          <Rise key={i} at={lineAt(i)} frames={20} outAt={D - 14 + i * 2} style={{ paddingLeft: t * size * k }}>
            <span style={{ position: "relative", display: "inline-block" }}>
              <span style={{ ...face, position: "absolute", left: 0, top: 4 * k, color: withAlpha(accent, 0.5) }}>{ln}</span>
              <span style={{ ...face, ...CHROME, position: "relative" }}>{ln}</span>
              <span style={{ ...face, position: "absolute", left: 0, top: 0, backgroundImage: `${BAND}, ${BAND}`,
                backgroundSize: "300% 100%, 300% 100%", backgroundRepeat: "no-repeat",
                backgroundPosition: `${s1 * 100}% 0%, ${s2 * 100}% 0%`, WebkitBackgroundClip: "text", backgroundClip: "text",
                color: "transparent", WebkitTextFillColor: "transparent" }}>{ln}</span>
            </span>
          </Rise>
        );
      })}
    </div>
  );
  const fade = "linear-gradient(to top, rgba(0,0,0,1) 0%, rgba(0,0,0,0) 60%)";
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: bg,
        background: "radial-gradient(ellipse 70% 60% at 50% 42%, #25272d 0%, #111215 50%, #050506 100%)" }}>
        <AbsoluteFill style={{ background: `radial-gradient(ellipse 34% 62% at ${spot}% 0%, rgba(255,255,255,.1) 0%, rgba(255,255,255,0) 70%)` }} />
        <AbsoluteFill style={{ background: `radial-gradient(ellipse 40% 22% at 50% 48%, ${withAlpha(accent, 0.1)} 0%, rgba(0,0,0,0) 100%)` }} />
        <div style={{ position: "absolute", left: 0, right: 0, top: "53%", bottom: 0,
          background: "linear-gradient(180deg, rgba(255,255,255,.045) 0%, rgba(255,255,255,0) 45%)" }} />
      </AbsoluteFill>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
          {kicker ? (
            <Letters text={kicker} at={2} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k, letterSpacing: "0.4em",
              paddingLeft: "0.4em", color: accent, whiteSpace: "nowrap", marginBottom: 20 * k }} />
          ) : null}
          {block}
          <div style={{ width: 1000 * k, height: 1.5 * k, marginTop: 4 * k, transform: `scaleX(${floor})`,
            background: "linear-gradient(90deg, rgba(255,255,255,0), rgba(255,255,255,.42), rgba(255,255,255,0))" }} />
          <div style={{ transform: "scaleY(-1)", opacity: 0.24, marginTop: 4 * k, WebkitMaskImage: fade, maskImage: fade }}>
            {block}
          </div>
        </div>
      </AbsoluteFill>
      {sub ? (
        <div style={{ position: "absolute", left: 0, right: 0, bottom: 130 * k, display: "flex", justifyContent: "center" }}>
          <Letters text={sub} at={22} style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 30 * k, letterSpacing: "0.2em",
            paddingLeft: "0.2em", color: "rgba(255,255,255,.62)", whiteSpace: "nowrap" }} />
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== 7. chapter fraction
const FractionTag: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const ex = useExit();
  const n = Math.round(Number(overlay.value ?? NaN));
  const title = cap(overlay.text);
  if (!Number.isFinite(n) || n < 0 || n > 99 || !title) return null;
  const tot = Math.round(Number(overlay.total ?? NaN));
  const hasTot = Number.isFinite(tot) && tot >= Math.max(1, n) && tot <= 99;
  const segs = hasTot && tot <= 12 ? tot : 0;
  const kicker = clip(cap(overlay.label), 30) || "CHAPTER";
  const { size, ls } = fit(title, 62, 22, 2);
  const BIG = 132 * k, SMALL = 64 * k;
  const numOut = ramp(frame, D - 15, 11, expoIn);
  const slash = ramp(frame, 7, 14) * (1 - ex);
  const divider = ramp(frame, 10, 16) * (1 - ex);
  const shade = ramp(frame, 0, 12) * (1 - ramp(frame, D - 10, 10));
  // Each digit group rises out of its mask while it spins, and leaves the same way.
  const mask = (h: number, at: number, child: React.ReactNode) => (
    <div style={{ height: h, overflow: "hidden" }}>
      <div style={{ transform: `translateY(${(1 - ramp(frame, at, 12)) * 112 - numOut * 112}%)` }}>{child}</div>
    </div>
  );
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: shade,
        background: "radial-gradient(ellipse 60% 48% at 10% 94%, rgba(0,0,0,.66) 0%, rgba(0,0,0,.28) 48%, rgba(0,0,0,0) 100%)" }} />
      <div style={{ position: "absolute", left: 110 * k, bottom: 120 * k, display: "flex", alignItems: "center", gap: 36 * k,
        transform: `scale(${hold})`, transformOrigin: "0% 100%" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 14 * k }}>
          <div style={{ display: "flex", alignItems: "flex-end" }}>
            {mask(BIG, 0, <SpinDigits text={pad2(n)} at={2} frames={Math.round(fps * 0.9)} size={BIG} color="#fff" />)}
            {hasTot ? (
              <>
                <svg width={52 * k} height={BIG} style={{ overflow: "visible" }}>
                  <path d={`M${44 * k} ${BIG * 0.14} L${10 * k} ${BIG * 0.84}`} fill="none" stroke={accent} strokeWidth={5 * k}
                    strokeLinecap="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - slash} />
                </svg>
                <div style={{ marginBottom: 0.2 * (BIG - SMALL) }}>
                  {mask(SMALL, 6, <SpinDigits text={pad2(tot)} at={8} frames={Math.round(fps * 0.9)} size={SMALL}
                    color="rgba(255,255,255,.6)" ghost="rgba(255,255,255,.2)" />)}
                </div>
              </>
            ) : null}
          </div>
          {segs ? (
            <div style={{ display: "flex", gap: 6 * k }}>
              {Array.from({ length: segs }, (_, i) => {
                const p = ramp(frame, 14 + i * 2, 12, backOut) * (1 - ramp(frame, D - 14 + i * 0.5, 8, expoIn));
                const done = i < n - 1;
                const cur = i === n - 1;
                const fill = cur ? ramp(frame, 24, 18, inOut) : 0;
                return (
                  <div key={i} style={{ position: "relative", width: 30 * k, height: 5 * k, borderRadius: 3 * k, overflow: "hidden",
                    background: done ? "rgba(255,255,255,.78)" : "rgba(255,255,255,.22)", transform: `scaleX(${p})`,
                    transformOrigin: "0 50%" }}>
                    {cur ? <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${fill * 100}%`,
                      background: accent }} /> : null}
                  </div>
                );
              })}
            </div>
          ) : null}
        </div>
        <div style={{ width: 2 * k, height: 150 * k, background: "rgba(255,255,255,.4)", transform: `scaleY(${divider})`,
          transformOrigin: "50% 100%" }} />
        <div style={{ display: "flex", flexDirection: "column", gap: 4 * k, maxWidth: 900 * k }}>
          <Letters text={kicker} at={9} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 26 * k, letterSpacing: "0.3em",
            color: accent, whiteSpace: "nowrap", textShadow: "0 2px 10px rgba(0,0,0,.6)" }} />
          {ls.map((ln, i) => (
            <Letters key={i} text={ln} at={12 + i * 5} style={{ fontFamily: DISPLAY, fontSize: size * k, lineHeight: 0.98,
              letterSpacing: "0.03em", color: "#fff", whiteSpace: "nowrap", textShadow: "0 3px 14px rgba(0,0,0,.6)" }} />
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 8. coordinates
const LAND = feature(topology as never, topology.objects.land as never) as unknown as object;
const GRATICULE = geoGraticule10();
const shortPlace = (s: string): string => s.split(",").map((x) => x.trim()).filter(Boolean).slice(0, 2).join(", ");
/** A coordinate as a number; null / empty / non-numeric is NaN (Number(null) would be 0, a pin in the Gulf of Guinea). */
const coordNum = (v: unknown): number =>
  typeof v === "number" ? v : typeof v === "string" && v.trim() ? Number(v) : NaN;
const coord = (v: number, pos: string, neg: string): string => `${Math.abs(v).toFixed(4)}°${v >= 0 ? pos : neg}`;

const Coordinates: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const ex = useExit();
  const locs: MapLocation[] = Array.isArray(overlay.locations) ? overlay.locations : [];
  const loc: MapLocation | undefined = locs.find((l) => Boolean(l) && typeof l === "object"
    && Math.abs(coordNum(l.lat)) <= 90 && Math.abs(coordNum(l.lon)) <= 180);
  if (!loc) return null;
  const lat = coordNum(loc.lat);
  const lon = coordNum(loc.lon);
  const place = cap(shortPlace(str(loc.label)));
  const title = cap(overlay.text) || place;
  if (!title) return null;
  const kicker = cap(overlay.text) ? clip(place || cap(overlay.label), 40) : clip(cap(overlay.label), 40) || "LOCATION";
  const { size, ls } = fit(title, 68, 22, 2);
  // The globe spins from 120 degrees east of the place and tilts onto it.
  const R = 88 * k, S = 2 * R + 60 * k, C = S / 2;
  const spinDur = Math.round(fps * 1.3);
  const spin = ramp(frame, 2, spinDur, inOut);
  const proj = geoOrthographic().scale(R).translate([C, C])
    .rotate([-lon + (1 - spin) * 120, -lat * (0.25 + 0.75 * spin), 0]).clipAngle(90);
  const path = geoPath(proj);
  const sphere = path({ type: "Sphere" } as never) || "";
  const land = path(LAND as never) || "";
  const grat = path(GRATICULE as never) || "";
  const settle = 2 + spinDur;
  const pin = proj([lon, lat]) || [C, C];
  const pinP = ramp(frame, settle - 6, 12, backOut) * (1 - ex);
  const cyc = Math.round(fps * 1.1);
  const pulse = frame >= settle ? ((frame - settle) % cyc) / cyc : 0;
  const pop = ramp(frame, 0, 16, backOut);
  const gScale = (0.7 + 0.3 * pop) * (1 - 0.25 * ex);
  const gOp = Math.min(1, pop * 2) * (1 - ex);
  const off = (1 - ramp(frame, 4, spinDur, inOut)) * 30 * k;
  const b = 18 * k, e = C - R - 12 * k - off, f = C + R + 12 * k + off;
  const corners = `M${e} ${e + b} V${e} H${e + b} M${f - b} ${e} H${f} V${e + b} M${f} ${f - b} V${f} H${f - b} M${e + b} ${f} H${e} V${f - b}`;
  const locked = frame >= settle;
  const chars = Array.from(`${coord(lat, "N", "S")}  ${coord(lon, "E", "W")}`);
  const nDig = chars.filter((c) => /\d/.test(c)).length;
  const lockSpan = Math.max(8, spinDur - 14);
  const shade = ramp(frame, 0, 12) * (1 - ramp(frame, D - 10, 10));
  const id = `chglobe${overlay.startFrame}`;
  let di = 0;
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: shade,
        background: "radial-gradient(ellipse 62% 52% at 12% 90%, rgba(0,0,0,.66) 0%, rgba(0,0,0,.26) 50%, rgba(0,0,0,0) 100%)" }} />
      <div style={{ position: "absolute", left: 96 * k, bottom: 100 * k, display: "flex", alignItems: "center", gap: 30 * k,
        transform: `scale(${hold})`, transformOrigin: "0% 100%" }}>
        <svg width={S} height={S} style={{ overflow: "visible", flexShrink: 0, opacity: gOp, transform: `scale(${gScale})` }}>
          <defs>
            <radialGradient id={id} cx="38%" cy="32%" r="75%">
              <stop offset="0%" stopColor="#22324a" />
              <stop offset="100%" stopColor="#060a12" />
            </radialGradient>
          </defs>
          <path d={sphere} fill={`url(#${id})`} />
          <path d={grat} fill="none" stroke="rgba(255,255,255,.1)" strokeWidth={1 * k} />
          <path d={land} fill="rgba(255,255,255,.28)" stroke="rgba(255,255,255,.5)" strokeWidth={0.7 * k} strokeLinejoin="round" />
          <path d={sphere} fill="none" stroke="rgba(255,255,255,.6)" strokeWidth={1.5 * k} />
          <path d={`M${C - R - 8 * k} ${C} H${C + R + 8 * k} M${C} ${C - R - 8 * k} V${C + R + 8 * k}`} stroke={CYAN}
            strokeOpacity={0.4} strokeWidth={1 * k} strokeDasharray={`${4 * k} ${5 * k}`} />
          <path d={corners} fill="none" stroke={locked ? accent : "rgba(255,255,255,.75)"} strokeWidth={2.5 * k}
            strokeLinecap="round" strokeLinejoin="round" />
          {pinP > 0 ? (
            <g>
              <circle cx={pin[0]} cy={pin[1]} r={(8 + 30 * pulse) * k} fill="none" stroke={accent} strokeWidth={2.5 * k}
                opacity={(1 - pulse) * pinP} />
              <circle cx={pin[0]} cy={pin[1]} r={7 * k * pinP} fill={accent} stroke="#fff" strokeWidth={2 * k} />
            </g>
          ) : null}
        </svg>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 * k, maxWidth: 1000 * k }}>
          {kicker ? (
            <Letters text={kicker} at={8} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 26 * k, letterSpacing: "0.3em",
              color: accent, whiteSpace: "nowrap", textShadow: "0 2px 10px rgba(0,0,0,.6)" }} />
          ) : null}
          {ls.map((ln, i) => (
            <Letters key={i} text={ln} at={11 + i * 5} style={{ fontFamily: DISPLAY, fontSize: size * k, lineHeight: 0.98,
              letterSpacing: "0.03em", color: "#fff", whiteSpace: "nowrap", textShadow: "0 3px 14px rgba(0,0,0,.6)" }} />
          ))}
          <Rise at={14} style={{ marginTop: 10 * k }}>
            <div style={{ display: "flex", alignItems: "center", gap: 14 * k, fontFamily: MONO, fontWeight: 500,
              fontSize: 26 * k, letterSpacing: "0.06em", textShadow: "0 3px 14px rgba(0,0,0,.7)" }}>
              <span style={{ width: 10 * k, height: 10 * k, borderRadius: "50%", flexShrink: 0,
                background: locked ? accent : CYAN }} />
              <span style={{ whiteSpace: "pre" }}>
                {chars.map((c, i) => {
                  if (!/\d/.test(c)) return <span key={i} style={{ color: "rgba(255,255,255,.55)" }}>{c}</span>;
                  const order = di;
                  di += 1;
                  const done = frame >= 16 + (order / Math.max(1, nDig - 1)) * lockSpan;
                  return (
                    <span key={i} style={{ color: done ? "#fff" : CYAN }}>
                      {done ? c : String(Math.floor(rnd(i * 97 + frame * 13) * 10))}
                    </span>
                  );
                })}
              </span>
            </div>
          </Rise>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 9. year tape
const YearTape: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const ex = useExit();
  const bg = useBackdrop(overlay);
  const year = Math.round(Number(overlay.value ?? NaN));
  const title = cap(overlay.text);
  if (!Number.isFinite(year) || year < 1 || year > 9999 || !title) return null;
  const from = Math.max(0, year - 48);
  const at = 6;
  const frames = Math.round(fps * 1.5);
  const ease = Easing.bezier(0.3, 0.05, 0.1, 1);
  const yAt = (f: number) => from + (year - from) * interpolate(f, [at, at + frames], [0, 1], { ...clamp, easing: ease });
  const v = yAt(frame);
  const vp = yAt(frame - 1);
  const digits = String(year).length;
  const kicker = clip(cap(overlay.label), 36);
  const { size, ls } = fit(title, 76, 22, 2);
  const sub = lines(str(overlay.subtitle), 50).slice(0, 2);
  const TW = 1240 * k, TH = 78 * k, PX = 26 * k;
  const tape = ramp(frame, 4, 22, inOut) * (1 - ex);
  const rule = ramp(frame, at + frames - 12, 18) * (1 - ex);
  const needle = ramp(frame, 8, 14, backOut) * (1 - ex);
  const lo = Math.floor(v - TW / 2 / PX) - 1;
  const hi = Math.ceil(v + TW / 2 / PX) + 1;
  const ticks: React.ReactNode[] = [];
  for (let y = Math.max(0, lo); y <= hi; y++) {
    const x = TW / 2 + (y - v) * PX;
    const major = y % 10 === 0;
    const mid = y % 5 === 0;
    ticks.push(<line key={`l${y}`} x1={x} x2={x} y1={8 * k} y2={(8 + (major ? 30 : mid ? 20 : 11)) * k} stroke={INK}
      strokeOpacity={major ? 0.75 : 0.35} strokeWidth={(major ? 2.5 : 1.5) * k} />);
    if (major) {
      ticks.push(<text key={`t${y}`} x={x} y={70 * k} textAnchor="middle" fontFamily={LABEL} fontWeight={700}
        fontSize={24 * k} fill={INK} fillOpacity={0.55} letterSpacing={1 * k}>{y}</text>);
    }
  }
  const edge = "linear-gradient(90deg, rgba(0,0,0,0) 0%, #000 16%, #000 84%, rgba(0,0,0,0) 100%)";
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: bg,
        background: "radial-gradient(ellipse 85% 75% at 50% 42%, #f7f6f2 0%, #e7e5df 58%, #cfccc4 100%)" }}>
        <AbsoluteFill style={{ background: `linear-gradient(180deg, rgba(0,0,0,0) 70%, ${withAlpha(accent, 0.12)} 100%)` }} />
        <AbsoluteFill style={{ boxShadow: `inset 0 0 ${260 * k}px rgba(60,55,45,.28)` }} />
      </AbsoluteFill>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
          {kicker ? (
            <Letters text={kicker} at={2} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k, letterSpacing: "0.34em",
              paddingLeft: "0.34em", color: withAlpha(INK, 0.62), whiteSpace: "nowrap", marginBottom: 6 * k }} />
          ) : null}
          <Rise at={0} frames={14} outAt={D - 15}>
            <MechDigits v={v} vp={vp} digits={digits} size={190 * k} color={INK} trail={withAlpha(INK, 0.28)} />
          </Rise>
          <div style={{ position: "relative", width: TW, height: TH, marginTop: 14 * k }}>
            <div style={{ position: "absolute", left: 0, top: 0, width: TW, height: TH, WebkitMaskImage: edge, maskImage: edge,
              clipPath: `inset(0 ${(1 - tape) * 50}% 0 ${(1 - tape) * 50}%)` }}>
              <svg width={TW} height={TH}>
                <line x1={0} x2={TW} y1={8 * k} y2={8 * k} stroke={INK} strokeOpacity={0.3} strokeWidth={1.5 * k} />
                {ticks}
              </svg>
            </div>
            <svg width={TW} height={TH} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
              <path d={`M${TW / 2} ${-4 * k} V${-4 * k + 54 * k * needle}`} stroke={accent} strokeWidth={3 * k} />
              <path d={`M${TW / 2 - 9 * k} ${-16 * k} L${TW / 2 + 9 * k} ${-16 * k} L${TW / 2} ${-2 * k} Z`} fill={accent}
                opacity={needle} />
            </svg>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", marginTop: 34 * k }}>
            {ls.map((ln, i) => (
              <Letters key={i} text={ln} at={16 + i * 5} style={{ fontFamily: DISPLAY, fontSize: size * k, lineHeight: 1,
                letterSpacing: "0.04em", color: INK, textAlign: "center", whiteSpace: "nowrap" }} />
            ))}
          </div>
          <div style={{ width: 240 * k, height: 5 * k, marginTop: 16 * k, background: accent, transform: `scaleX(${rule})` }} />
          {sub.map((ln, i) => (
            <Rise key={`s${i}`} at={26 + i * 3} style={{ marginTop: i === 0 ? 16 * k : 0 }}>
              <span style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 30 * k, letterSpacing: "0.06em",
                color: withAlpha(INK, 0.58) }}>{ln}</span>
            </Rise>
          ))}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 10. countdown to chapter
const Countdown: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: D, width, height } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const ex = useExit();
  const bg = useBackdrop(overlay);
  const title = cap(overlay.text);
  if (!title) return null;
  const c = D >= 150 ? 12 : D >= 96 ? 10 : 8;   // frames per count
  const T = 3 * c;                               // the resolve
  const n = Math.round(Number(overlay.value ?? NaN));
  const hasNum = Number.isFinite(n) && n >= 0 && n <= 99;
  const kicker = clip(cap(overlay.label), 34) || "CHAPTER";
  const { size, ls } = fit(title, 84, 20, 2);
  const sub = lines(str(overlay.subtitle), 50).slice(0, 2);
  const cx = width / 2;
  const mid = height / 2;
  const R = 150 * k, r2 = 48 * k;
  const emblemY = mid - (ls.length > 1 ? 190 : 150) * k;
  const morph = ramp(frame, T, 18);
  const ringR = R + (r2 - R) * morph;
  const cy = mid + (emblemY - mid) * morph;
  const counting = frame < T;
  const idx = Math.min(2, Math.max(0, Math.floor(frame / c)));
  const arc = counting ? Math.min(1, (frame - idx * c + 1) / c) : 1;
  const beat = counting ? 1 - Math.min(1, ((frame - idx * c) / c) * 3) : 0;
  const furn = (1 - morph) * ramp(frame, 0, 8);
  const circ = 2 * Math.PI * ringR;
  const shock = ramp(frame, T, 20);
  const flash = interpolate(frame, [T - 2, T, T + 12], [0, 1, 0], clamp);
  const ringPop = ramp(frame, 0, 12, backOut);
  const textTop = emblemY + r2 + 38 * k;
  const ruleP = ramp(frame, T + 14, 18) * (1 - ex);
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: bg,
        background: "radial-gradient(ellipse 70% 62% at 50% 46%, #17181c 0%, #0b0b0d 55%, #040405 100%)" }} />
      <AbsoluteFill style={{ opacity: flash * 0.8 * bg,
        background: `radial-gradient(circle at 50% 50%, ${withAlpha(accent, 0.35)} 0%, rgba(0,0,0,0) 40%)` }} />
      <AbsoluteFill style={{ transform: `scale(${hold})` }}>
        {furn > 0.01 ? (
          <div style={{ position: "absolute", left: cx - R, top: mid - R, width: 2 * R, height: 2 * R, borderRadius: "50%",
            opacity: 0.9 * furn,
            background: `conic-gradient(${withAlpha(accent, 0.04)} 0deg, ${withAlpha(accent, 0.26)} ${arc * 360}deg, rgba(0,0,0,0) ${arc * 360}deg 360deg)` }} />
        ) : null}
        <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0 }}>
          <path d={`M${cx - R - 130 * k} ${mid} H${cx + R + 130 * k} M${cx} ${mid - R - 130 * k} V${mid + R + 130 * k}`}
            stroke="#fff" strokeOpacity={0.16 * furn} strokeWidth={1.5 * k} />
          <g opacity={0.5 * furn} transform={`rotate(${frame * 0.6} ${cx} ${mid})`}>
            {Array.from({ length: 24 }, (_, i) => {
              const a = (i / 24) * Math.PI * 2;
              const r0 = R + 20 * k;
              const r1 = R + (i % 6 === 0 ? 38 : 28) * k;
              return <line key={i} x1={cx + Math.cos(a) * r0} y1={mid + Math.sin(a) * r0} x2={cx + Math.cos(a) * r1}
                y2={mid + Math.sin(a) * r1} stroke="#fff" strokeWidth={(i % 6 === 0 ? 2.5 : 1.5) * k} />;
            })}
          </g>
          <circle cx={cx} cy={cy} r={ringR * (0.85 + 0.15 * ringPop)} fill="none" stroke="#fff"
            strokeOpacity={(0.22 + 0.5 * beat) * furn} strokeWidth={2 * k} />
          <circle cx={cx} cy={cy} r={ringR} fill="none" stroke={accent} strokeWidth={(6 - 3 * morph) * k} strokeLinecap="round"
            strokeDasharray={`${circ * arc * (1 - ex)} ${circ}`} transform={`rotate(-90 ${cx} ${cy})`}
            opacity={Math.min(1, ringPop)} style={{ filter: `drop-shadow(0 0 ${10 * k}px ${withAlpha(accent, 0.6)})` }} />
          {frame >= T && shock < 1 ? (
            <g>
              <circle cx={cx} cy={mid} r={R + shock * 280 * k} fill="none" stroke={accent} strokeWidth={3 * k * (1 - shock)}
                opacity={1 - shock} />
              {Array.from({ length: 18 }, (_, i) => {
                const a = (i / 18) * Math.PI * 2 + rnd(i * 7 + 3) * 0.3;
                const dist = R + (60 + rnd(i * 13 + 5) * 220) * k * shock;
                return <circle key={i} cx={cx + Math.cos(a) * dist} cy={mid + Math.sin(a) * dist}
                  r={(2 + rnd(i * 5 + 1) * 2.5) * k * (1 - 0.6 * shock)} fill={i % 3 === 0 ? accent : "#fff"}
                  opacity={1 - shock} />;
              })}
            </g>
          ) : null}
        </svg>
        {[3, 2, 1].map((num, i) => {
          const start = i * c;
          if (frame < start) return null;
          const inP = ramp(frame, start, 7);
          const outP = ramp(frame, start + c - 1, 6, expoIn);
          if (outP >= 1) return null;
          return (
            <div key={num} style={{ position: "absolute", left: cx - 150 * k, top: mid - 95 * k, width: 300 * k, height: 190 * k,
              overflow: "hidden", display: "flex", justifyContent: "center" }}>
              <div style={{ fontFamily: DISPLAY, fontSize: 190 * k, lineHeight: 1, color: "#fff", paddingTop: 12 * k,
                transform: `translateY(${(1 - inP) * 100 - outP * 100}%)` }}>{num}</div>
            </div>
          );
        })}
        {hasNum ? (
          <div style={{ position: "absolute", left: cx - r2, top: emblemY - r2, width: 2 * r2, height: 2 * r2, display: "flex",
            alignItems: "center", justifyContent: "center" }}>
            <Rise at={T + 8} frames={12} outAt={D - 15}>
              <span style={{ display: "block", fontFamily: DISPLAY, fontSize: 50 * k, lineHeight: 1, color: "#fff",
                paddingTop: 5 * k }}>{pad2(n)}</span>
            </Rise>
          </div>
        ) : (
          <div style={{ position: "absolute", left: cx - 6 * k, top: emblemY - 6 * k, width: 12 * k, height: 12 * k,
            borderRadius: "50%", background: accent, transform: `scale(${ramp(frame, T + 8, 12, backOut) * (1 - ex)})` }} />
        )}
        <div style={{ position: "absolute", left: 0, right: 0, top: textTop, display: "flex", flexDirection: "column",
          alignItems: "center" }}>
          <Letters text={kicker} at={T + 4} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k, letterSpacing: "0.36em",
            paddingLeft: "0.36em", color: accent, whiteSpace: "nowrap", marginBottom: 10 * k }} />
          {ls.map((ln, i) => (
            <Letters key={i} text={ln} at={T + 8 + i * 5} style={{ fontFamily: DISPLAY, fontSize: size * k, lineHeight: 1,
              letterSpacing: "0.04em", color: "#fff", textAlign: "center", whiteSpace: "nowrap" }} />
          ))}
          <div style={{ width: 200 * k, height: 4 * k, marginTop: 18 * k, background: accent, transform: `scaleX(${ruleP})` }} />
          {sub.map((ln, i) => (
            <Rise key={`s${i}`} at={T + 18 + i * 3} style={{ marginTop: i === 0 ? 16 * k : 0 }}>
              <span style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 30 * k, letterSpacing: "0.06em",
                color: "rgba(255,255,255,.66)" }}>{ln}</span>
            </Rise>
          ))}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "ch-number-roll": ChapterNumberRoll,
  "ch-part-divider": PartDivider,
  "ch-episode-card": EpisodeCard,
  "ch-letterbox": LetterboxTitle,
  "ch-glitch-resolve": GlitchResolve,
  "ch-chrome-sweep": ChromeSweep,
  "ch-fraction-tag": FractionTag,
  "ch-coordinates": Coordinates,
  "ch-year-tape": YearTape,
  "ch-countdown": Countdown,
};
