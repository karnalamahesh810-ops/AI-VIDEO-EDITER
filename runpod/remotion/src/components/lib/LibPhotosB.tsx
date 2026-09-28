import React from "react";
import { AbsoluteFill, Easing, Img, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY, HAND, INTER, LABEL, MARKER, MONO } from "../fonts";
import type { Overlay, OverlayItem, SceneMedia } from "../../types";
import { LetterLine, Odometer, Tag, lines, ramp, useHold, useK } from "../pro/ProGraphics";

/**
 * Photo motion II (family "pb-"): stills from overlay.media turned into designed
 * full-frame moments, each with its own backdrop and one memorable move.
 *
 *   pb-wipe-compare     THEN / NOW under a draggable divider that sweeps, overshoots and settles
 *   pb-triptych         three tall panels rising in from alternating sides with counter-parallax
 *   pb-carousel         photos on a turning 3D ring with a floor reflection, the front one enlarged
 *   pb-corkboard        prints dropping onto cork, pins pushed in, each print swinging on its pin
 *   pb-double-exposure  two photos blended through a travelling mask with an accent light leak
 *   pb-zoom-through     a window opens in the centre of photo 1 and the camera dives into photo 2
 *   pb-annotated        a photo racks into focus, pulsing markers, curved arrows drawing on, labels
 *   pb-grid-pop         a 2x2 / 3x2 grid popping in with flashes, gutters closing into a mosaic
 *   pb-parallax-stack   three photos at three depths trucking at three speeds, dust in front
 *   pb-date-plate       a photo wiped on, a year plate sliding over the corner, the year rolling
 *
 * Text rises letter by letter out of masks and drops out at the end; pictures
 * exit with their own move in the last ~14 frames.
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const easeIn = Easing.bezier(0.7, 0, 0.84, 0);
const CYAN = "#53c8ff";
const INK = "#0b0b0e";

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
/** Deterministic 0..1 noise of a number (no Math.random anywhere). */
const hash = (n: number): number => {
  const x = Math.sin(n * 127.1 + 311.7) * 43758.5453123;
  return x - Math.floor(x);
};
const pad = (n: number) => String(n).padStart(2, "0");
/** Any planner field as a trimmed string (numbers kept, anything else dropped), so .trim() never throws. */
const str = (v: unknown): string =>
  (typeof v === "string" ? v : typeof v === "number" && Number.isFinite(v) ? String(v) : "").trim();
/**
 * When a LetterLine of `len` letters must start its exit so its LAST letter
 * (0.6 f stagger + 9 f drop) is gone by the final frame.
 */
const outFor = (dur: number, len: number): number => dur - 11 - Math.ceil(Math.max(0, len - 1) * 0.6);

/** A planner list field as an array (anything else -> empty), so .map / .filter never throw. */
const listOf = <T,>(v: T[] | null | undefined): T[] => (Array.isArray(v) ? v : []);

/** The picture of a media entry: an image's url, anything else its thumbnail (non-strings dropped). */
const stillOf = (m?: SceneMedia | null): string => {
  if (!m || typeof m !== "object") return "";
  const u: unknown = m.type === "image" ? m.url : m.thumbnail;
  return typeof u === "string" ? u.trim() : "";
};

/** Up to `max` distinct stills from the overlay's media (video -> its thumbnail). */
const stills = (ov: Overlay, max: number): string[] => {
  const out: string[] = [];
  for (const m of listOf(ov.media)) {
    const s = stillOf(m);
    if (s && out.indexOf(s) < 0) out.push(s);
    if (out.length >= max) break;
  }
  return out;
};
const pick = (list: string[], i: number): string => list[((i % list.length) + list.length) % list.length];

/** 0 -> 1 over the last `frames` frames (ease-in), the exit. */
const useExit = (frames = 12): number => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return ramp(frame, durationInFrames - frames, Math.max(1, frames - 2), easeIn);
};

/** 0 -> 1 across the whole overlay, for slow drifts. */
const useLife = (): number => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return interpolate(frame, [0, Math.max(1, durationInFrames)], [0, 1], clamp);
};

const fitTitle = (text: string, size: number, chars: number) => {
  const n = (text || "").trim().length;
  if (n > chars * 2.2) return { size: Math.max(44, size * 0.7), chars: Math.round(chars * 1.4) };
  if (n > chars * 1.4) return { size: Math.max(44, size * 0.84), chars: Math.round(chars * 1.18) };
  return { size, chars };
};

// ------------------------------------------------------------------ text pieces
/** Condensed caps, word-wrapped; letters rise in and drop out in time for the end. */
const Title: React.FC<{
  text?: string; at: number; size: number; chars: number; align?: "left" | "center" | "right"; color?: string;
  maxLines?: number; font?: string; weight?: number; spacing?: string; shadow?: boolean; lineHeight?: number;
}> = ({ text, at, size, chars, align = "left", color = "#fff", maxLines = 2, font = DISPLAY, weight, spacing = "0.02em",
        shadow = true, lineHeight = 0.98 }) => {
  const k = useK();
  const { durationInFrames } = useVideoConfig();
  const all = lines(str(text).toUpperCase(), chars);
  const ls = all.slice(0, maxLines);
  if (!ls.length) return null;
  if (all.length > maxLines) ls[ls.length - 1] = `${ls[ls.length - 1]}…`;
  const longest = Math.max(...ls.map((l) => l.length));
  // Long lines rise faster so they are fully in early; the exit is timed so every letter is gone by the end.
  const step = Math.min(0.7, 18 / Math.max(1, longest));
  const outAt = outFor(durationInFrames, longest);
  return (
    <div style={{ display: "flex", flexDirection: "column",
      alignItems: align === "center" ? "center" : align === "right" ? "flex-end" : "flex-start" }}>
      {ls.map((ln, i) => (
        <LetterLine key={i} text={ln} at={at + i * 4} step={step} outAt={outAt} style={{ fontFamily: font, fontWeight: weight,
          fontSize: size * k, lineHeight, color, letterSpacing: spacing, textAlign: align, whiteSpace: "nowrap",
          textShadow: shadow ? "0 6px 28px rgba(0,0,0,.6)" : undefined }} />
      ))}
    </div>
  );
};

/** The small spaced caps line above a title, in the accent. */
const Kicker: React.FC<{ text?: string; at: number; color: string; size?: number; spacing?: string }> =
  ({ text, at, color, size = 28, spacing = "0.28em" }) => {
    const k = useK();
    const { durationInFrames } = useVideoConfig();
    const raw = str(text).toUpperCase();
    if (!raw) return null;
    const t = raw.length > 44 ? `${raw.slice(0, 43)}…` : raw;
    return (
      <LetterLine text={t} at={at} step={0.5} outAt={outFor(durationInFrames, t.length)}
        style={{ fontFamily: LABEL, fontWeight: 800, fontSize: size * k, letterSpacing: spacing, color, lineHeight: 1.1,
          whiteSpace: "nowrap", textShadow: "0 3px 14px rgba(0,0,0,.45)" }} />
    );
  };

/** An accent bar that draws in and retracts to the right at the end. */
const Rule: React.FC<{ at: number; width: number; color: string; thick?: number; center?: boolean }> =
  ({ at, width, color, thick = 5, center }) => {
    const frame = useCurrentFrame();
    const k = useK();
    const q = useExit(14);
    const p = ramp(frame, at, 18);
    return (
      <div style={{ width: width * k, height: thick * k, background: color, transform: `scaleX(${p * (1 - q)})`,
        transformOrigin: q > 0 ? "right" : center ? "center" : "left" }} />
    );
  };

/** The house Tag, wiped away to the right at the end. */
const TagOut: React.FC<{ text?: string; at: number; accent: string; size?: number }> = ({ text, at, accent, size = 30 }) => {
  const q = useExit(12);
  const t = str(text);
  if (!t) return null;
  return (
    <div style={{ display: "inline-block", clipPath: `inset(0 0 0 ${q * 100}%)` }}>
      <Tag text={t.length > 34 ? `${t.slice(0, 33)}…` : t} at={at} accent={accent} size={size} />
    </div>
  );
};

/**
 * A small body line that rises out of its mask as one piece and leaves the
 * same way (one node instead of one per letter, for dense note text).
 */
const LineRise: React.FC<{ text: string; at: number; outAt: number; style?: React.CSSProperties }> =
  ({ text, at, outAt, style }) => {
    const frame = useCurrentFrame();
    const pin = ramp(frame, at, 14);
    const pout = ramp(frame, outAt, 9, easeIn);
    if (!text) return null;
    return (
      <div style={{ overflow: "hidden", paddingBottom: "0.1em", ...style }}>
        <div style={{ transform: `translateY(${(1 - pin) * 112 - pout * 112}%)`, whiteSpace: "nowrap" }}>{text}</div>
      </div>
    );
  };

/** A designed dark stage: deep radial, a drifting accent glow, fine diagonal hairlines, vignette. */
const Stage: React.FC<{ accent: string; children?: React.ReactNode }> = ({ accent, children }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const gx = 30 + 10 * Math.sin(frame / (fps * 3));
  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 45%, #1d1d23 0%, #0e0e12 55%, #060608 100%)",
      overflow: "hidden" }}>
      <AbsoluteFill style={{ background: `radial-gradient(ellipse at ${gx}% 18%, ${accent}1f 0%, rgba(0,0,0,0) 46%)` }} />
      <AbsoluteFill style={{ backgroundImage: `repeating-linear-gradient(115deg, rgba(255,255,255,.022) 0px, rgba(255,255,255,.022) ${1 * k}px, rgba(0,0,0,0) ${1 * k}px, rgba(0,0,0,0) ${13 * k}px)` }} />
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${280 * k}px rgba(0,0,0,.82)` }} />
      {children}
    </AbsoluteFill>
  );
};

const cover: React.CSSProperties = { position: "absolute", left: 0, top: 0, width: "100%", height: "100%", objectFit: "cover" };

// ================================================================== 1. wipe slider compare
const SideLabel: React.FC<{ text: string; at: number; bar: string; side: "left" | "right" }> = ({ text, at, bar, side }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const k = useK();
  const q = useExit(14);
  if (!text) return null;
  return (
    <div style={{ position: "absolute", top: 32 * k, left: side === "left" ? 36 * k : undefined,
      right: side === "right" ? 36 * k : undefined, display: "flex", alignItems: "center", gap: 14 * k,
      flexDirection: side === "left" ? "row" : "row-reverse" }}>
      <div style={{ width: 5 * k, height: 36 * k, background: bar, transform: `scaleY(${ramp(frame, at, 12) * (1 - q)})` }} />
      <LetterLine text={text} at={at + 3} step={0.8} outAt={outFor(durationInFrames, text.length) - 4}
        style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 38 * k,
        letterSpacing: "0.2em", color: "#fff", lineHeight: 1, whiteSpace: "nowrap", textShadow: "0 3px 16px rgba(0,0,0,.75)" }} />
    </div>
  );
};

const WipeCompare: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const q = useExit(14);
  const drift = useLife();
  const pics = stills(overlay, 2);
  if (!pics.length) return null;
  const same = pics.length < 2;
  const A = pics[0];
  const B = pics[1] || pics[0];
  const items = listOf(overlay.items);
  const labA = (str(items[0]?.label) || "Then").toUpperCase().slice(0, 22);
  const labB = (str(items[1]?.label) || "Now").toUpperCase().slice(0, 22);
  const title = str(overlay.text);
  const ft = fitTitle(title, 62, 44);
  const twoLines = title ? lines(title.toUpperCase(), ft.chars).length > 1 : false;
  const W = 1480 * k;
  const H = (title ? (twoLines ? 680 : 740) : 820) * k;
  const open = ramp(frame, 2, 18);
  // Short overlays get a quicker drag so the divider has settled well before the frame closes.
  const tight = durationInFrames < 120;
  const sw = tight ? 18 : 26;
  const t0 = Math.round(fps * (tight ? 0.5 : 0.65));
  const t1 = t0 + sw + 8;
  const settle = Easing.bezier(0.45, 0, 0.2, 1.3);
  // The divider: parked right (all THEN), dragged far left (all NOW), then back past the middle and settling.
  const divAt = (f: number): number => {
    const s1 = ramp(f, t0, sw, inOut);
    const s2 = ramp(f, t1, sw, settle);
    const tail = f > t1 + sw ? 0.012 * Math.sin((f - t1 - sw) / (fps * 0.7)) : 0;
    return 0.93 + (0.12 - 0.93) * s1 + (0.52 - 0.12) * s2 + tail;
  };
  const d = Math.max(0.02, Math.min(0.98, divAt(frame)));
  const glow = Math.min(1, Math.abs(divAt(frame) - divAt(frame - 1)) * 28);
  const hIn = ramp(frame, t0 - 10, 14, backOut);
  const ins = Math.min(50, (1 - open) * 50 + q * 50);
  return (
    <Stage accent={accent}>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 28 * k }}>
        {title ? (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8 * k }}>
            <Kicker text={overlay.subtitle} at={0} color={accent} />
            <Title text={title} at={4} size={ft.size} chars={ft.chars} align="center" maxLines={2} />
          </div>
        ) : null}
        <div style={{ position: "relative", width: W, height: H, transform: `scale(${hold})` }}>
          <div style={{ position: "absolute", inset: 0, boxShadow: "0 40px 110px rgba(0,0,0,.75)", opacity: open * (1 - q) }} />
          <div style={{ position: "absolute", inset: 0, overflow: "hidden", borderRadius: 4 * k, background: INK,
            clipPath: `inset(${ins}% 0 ${ins}% 0)` }}>
            <Img src={A} style={{ ...cover, transform: `scale(${1.07 + 0.03 * drift}) translateX(${(drift - 0.5) * 18 * k}px)`,
              filter: same ? "grayscale(1) sepia(.35) contrast(1.1) brightness(.88)"
                : "grayscale(.5) sepia(.18) contrast(1.06) brightness(.92)" }} />
            <div style={{ position: "absolute", inset: 0, clipPath: `inset(0 0 0 ${d * 100}%)` }}>
              <Img src={B} style={{ ...cover, transform: `scale(${1.07 + 0.03 * drift}) translateX(${(0.5 - drift) * 18 * k}px)`,
                filter: "saturate(1.08) contrast(1.04)" }} />
            </div>
            <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: "26%",
              background: "linear-gradient(180deg, rgba(0,0,0,.5), rgba(0,0,0,0))" }} />
            <div style={{ position: "absolute", inset: 0, clipPath: `inset(0 ${(1 - d) * 100}% 0 0)` }}>
              <SideLabel text={labA} at={t0 - 4} bar="rgba(255,255,255,.7)" side="left" />
            </div>
            <div style={{ position: "absolute", inset: 0, clipPath: `inset(0 0 0 ${d * 100}%)` }}>
              <SideLabel text={labB} at={t0 + 6} bar={accent} side="right" />
            </div>
          </div>
          <div style={{ position: "absolute", top: 0, bottom: 0, left: d * W - 2 * k, width: 4 * k, background: "#fff",
            boxShadow: `0 0 ${(12 + 22 * glow) * k}px rgba(0,0,0,.6)`,
            transform: `scaleY(${Math.max(0, Math.min(1, hIn)) * (1 - q)})` }} />
          <div style={{ position: "absolute", left: d * W - 38 * k, top: H / 2 - 38 * k, width: 76 * k, height: 76 * k,
            boxSizing: "border-box", borderRadius: "50%", border: `${3 * k}px solid #fff`, background: "rgba(12,12,16,.5)",
            backdropFilter: "blur(8px)", WebkitBackdropFilter: "blur(8px)",
            boxShadow: `0 0 0 ${glow * 10 * k}px ${accent}44, 0 12px 34px rgba(0,0,0,.55)`,
            display: "flex", alignItems: "center", justifyContent: "center",
            transform: `scale(${Math.max(0, hIn) * (1 + 0.1 * glow) * (1 - q)})` }}>
            <svg width={42 * k} height={22 * k} viewBox="0 0 42 22">
              <path d="M14 3 L5 11 L14 19 M28 3 L37 11 L28 19" fill="none" stroke="#fff" strokeWidth={3.2}
                strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
        </div>
      </AbsoluteFill>
    </Stage>
  );
};

// ================================================================== 2. triptych
const Triptych: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const k = useK();
  const t = useLife();
  const pics = stills(overlay, 3);
  if (!pics.length) return null;
  // One photo: it is sliced across the three panels (they align as they land).
  const sliced = pics.length === 1;
  const items = listOf(overlay.items);
  const title = str(overlay.text);
  const ft = fitTitle(title, 64, 42);
  const PW = 500 * k;
  const G = 26 * k;
  // With a title the panels stop short so a two-line title still ends above the 90 px bottom margin.
  const PH = (title ? 630 : 790) * k;
  const total = 3 * PW + 2 * G;
  const left0 = (1920 * k - total) / 2;
  const top0 = (title ? 112 : 145) * k;
  const lift = [20, -20, 20];
  const pan = [-30, 16, 36];
  return (
    <Stage accent={accent}>
      {[0, 1, 2].map((i) => {
        const at = 3 + i * 5;
        const p = ramp(frame, at, 24);
        const dir = i === 1 ? -1 : 1;
        const qi = ramp(frame, durationInFrames - 15 + i * 2, 10, easeIn);
        const y = top0 + lift[i] * k + dir * (1 - p) * 110 * k - dir * qi * 80 * k;
        const insTop = dir > 0 ? (1 - p) * 100 : qi * 100;
        const insBot = dir > 0 ? qi * 100 : (1 - p) * 100;
        // Counter-parallax inside the panel; the picture starts zoomed in by enough (0.36) that the
        // offset never uncovers the panel's edge, and settles as the panel lands.
        const counter = -dir * (1 - p) * 150 * k;
        const zoomIn = 0.36 * (1 - p);
        const lab = str(items[i]?.label);
        return (
          <div key={i} style={{ position: "absolute", left: left0 + i * (PW + G), top: y, width: PW, height: PH,
            overflow: "hidden", background: INK, clipPath: `inset(${insTop}% 0 ${insBot}% 0)` }}>
            {sliced ? (
              <Img src={pics[0]} style={{ position: "absolute", top: 0, left: -i * (PW + G), width: total, height: PH,
                objectFit: "cover", transform: `translateY(${counter}px) scale(${1.12 + 0.05 * t + zoomIn})` }} />
            ) : (
              <Img src={pick(pics, i)} style={{ ...cover,
                transform: `translate(${pan[i] * k * (t - 0.5)}px, ${counter}px) scale(${1.24 - 0.1 * p + 0.05 * t + zoomIn})` }} />
            )}
            {lab ? (
              <>
                <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: "36%",
                  background: "linear-gradient(0deg, rgba(0,0,0,.74), rgba(0,0,0,0))" }} />
                <div style={{ position: "absolute", left: 30 * k, right: 24 * k, bottom: 28 * k, display: "flex",
                  flexDirection: "column", gap: 6 * k }}>
                  <LetterLine text={pad(i + 1)} at={at + 14} style={{ fontFamily: MONO, fontWeight: 700, fontSize: 24 * k,
                    color: accent, letterSpacing: "0.1em" }} />
                  <Title text={lab} at={at + 16} size={36} chars={20} maxLines={2} font={LABEL} weight={800}
                    spacing="0.06em" lineHeight={1.02} />
                </div>
              </>
            ) : null}
            <div style={{ position: "absolute", inset: 0, boxShadow: "inset 0 0 0 1px rgba(255,255,255,.14)" }} />
          </div>
        );
      })}
      {title ? (
        <div style={{ position: "absolute", left: 0, right: 0, top: top0 + PH + 52 * k, display: "flex",
          flexDirection: "column", alignItems: "center", gap: 10 * k }}>
          <Kicker text={overlay.subtitle} at={14} color={accent} />
          <Title text={title} at={18} size={ft.size} chars={ft.chars} align="center" maxLines={2} />
        </div>
      ) : null}
    </Stage>
  );
};

// ================================================================== 3. 3D carousel
const Carousel: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const q = useExit(14);
  const pics = stills(overlay, 6);
  if (!pics.length) return null;
  const uniq = pics.length;
  const N = Math.min(8, Math.max(5, uniq >= 5 ? uniq : uniq * Math.ceil(5 / uniq)));
  const stepDeg = 360 / N;
  const CW = (N >= 7 ? 500 : 560) * k;
  const CH = CW * 0.62;
  const R = (N * CW * 1.1) / (2 * Math.PI);
  const land0 = Math.round(fps * 1.1);
  const I = Math.max(36, Math.round(fps * 1.35));
  const TR = 18;
  // One step per further distinct photo (a single photo never "steps" onto a copy of itself).
  const S = uniq >= 2 ? Math.max(0, Math.min(uniq - 1, 3, Math.floor((durationInFrames - land0 - 30) / I))) : 0;
  const starts = Array.from({ length: S }, (_, j) => land0 + (j + 1) * I - TR);
  // Ring angle: spins in and lands on photo 1, then steps one photo at a time, spins away at the end.
  const thetaAt = (f: number): number => {
    let th = -160 * (1 - ramp(f, 0, land0));
    for (const s of starts) th += stepDeg * ramp(f, s, TR, inOut);
    // No steps: a slow idle turn so the ring never freezes.
    if (!S) th += 5 * interpolate(f, [land0, Math.max(land0 + 1, durationInFrames)], [0, 1], clamp);
    return th + 80 * ramp(f, durationInFrames - 14, 12, easeIn);
  };
  const theta = thetaAt(frame);
  const appear = ramp(frame, 0, 14);
  const title = str(overlay.text);
  const ft = fitTitle(title, 60, 40);
  const items = listOf(overlay.items);
  const cy = (title ? 585 : 545) * k;
  const cards = Array.from({ length: N }, (_, i) => {
    const deg = i * stepDeg - theta;
    const a = (deg * Math.PI) / 180;
    const z = Math.cos(a) * R - R;
    const f = Math.max(0, Math.cos(a));
    return { i, deg, x: Math.sin(a) * R, y: z * 0.13, z, enl: 1 + 0.2 * Math.pow(f, 8),
      light: 0.25 + 0.75 * Math.pow(0.5 + 0.5 * Math.cos(a), 1.5), face: f };
  }).sort((u, v) => u.z - v.z);
  const caps = Array.from({ length: S + 1 }, (_, j) => ({
    j,
    at: j === 0 ? land0 - 8 : starts[j - 1] + TR - 4,
    outAt: j < S ? starts[j] - 6 : durationInFrames - 14,
  }));
  return (
    <Stage accent={accent}>
      <div style={{ position: "absolute", left: 960 * k - 700 * k, width: 1400 * k, top: cy + CH * 0.35, height: 360 * k,
        background: `radial-gradient(ellipse at 50% 30%, ${accent}26 0%, rgba(0,0,0,0) 62%)`, opacity: appear * (1 - q) }} />
      <AbsoluteFill style={{ perspective: 1900 * k, perspectiveOrigin: `50% ${cy - 90 * k}px` }}>
        {cards.map((c) => (
          <div key={c.i} style={{ position: "absolute", left: 960 * k - CW / 2, top: cy - CH / 2, width: CW, height: CH,
            transform: `translate3d(${c.x}px, ${c.y}px, ${c.z}px) rotateY(${c.deg}deg) scale(${c.enl * (0.85 + 0.15 * appear) * (1 - 0.15 * q)})`,
            opacity: appear * (1 - q), borderRadius: 6 * k, overflow: "hidden", background: INK,
            WebkitBoxReflect: `below ${8 * k}px linear-gradient(rgba(0,0,0,0) 62%, rgba(255,255,255,.22))`,
            boxShadow: "0 24px 60px rgba(0,0,0,.55)" }}>
            <Img src={pick(pics, c.i)} style={{ ...cover, filter: `brightness(${c.light.toFixed(3)})` }} />
            <div style={{ position: "absolute", inset: 0,
              boxShadow: `inset 0 0 0 ${2 * k}px rgba(255,255,255,${(0.08 + 0.3 * c.face).toFixed(3)})` }} />
          </div>
        ))}
      </AbsoluteFill>
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 260 * k,
        background: "linear-gradient(0deg, rgba(6,6,8,.9), rgba(6,6,8,0))" }} />
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 92 * k, height: 50 * k, display: "flex",
        justifyContent: "center", alignItems: "center" }}>
        {caps.filter((w) => frame >= w.at - 1 && frame <= w.outAt + 14).map((w) => {
          const n = w.j % uniq;
          const raw = str(items[n]?.label).toUpperCase();
          const lab = raw.length > 30 ? `${raw.slice(0, 29)}…` : raw;
          const count = uniq > 1 ? `${pad(n + 1)} / ${pad(uniq)}` : "";
          const bar = ramp(frame, w.at, 10) * (1 - ramp(frame, w.outAt, 8));
          return (
            <div key={w.j} style={{ position: "absolute", display: "flex", alignItems: "center", gap: 18 * k }}>
              {count ? (
                <LetterLine text={count} at={w.at} outAt={w.outAt} step={0.5}
                  style={{ fontFamily: MONO, fontWeight: 700, fontSize: 24 * k, color: accent, letterSpacing: "0.08em",
                    whiteSpace: "nowrap" }} />
              ) : null}
              {lab && count ? <div style={{ width: 2 * k, height: 34 * k, background: "rgba(255,255,255,.45)",
                transform: `scaleY(${bar})` }} /> : null}
              {/* The name rises out of its mask as one line (in 14 f, out 9 f) so captions swap cleanly between
                  steps whatever their length, and the last one is gone before the final frame. */}
              {lab ? (
                <LineRise text={lab} at={w.at + 3} outAt={w.outAt + 1}
                  style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 40 * k, color: "#fff", letterSpacing: "0.12em",
                    lineHeight: 1 }} />
              ) : null}
            </div>
          );
        })}
      </div>
      {title ? (
        <div style={{ position: "absolute", top: 94 * k, left: 0, right: 0, display: "flex", flexDirection: "column",
          alignItems: "center", gap: 8 * k }}>
          <Kicker text={overlay.subtitle} at={2} color={accent} />
          <Title text={title} at={6} size={ft.size} chars={ft.chars} align="center" maxLines={1} />
        </div>
      ) : null}
    </Stage>
  );
};

// ================================================================== 4. corkboard pins
type Slot = { x: number; y: number; w: number; r: number };
const CORK: Slot[][] = [
  [{ x: 1140, y: 590, w: 860, r: -2.5 }],
  [{ x: 760, y: 640, w: 640, r: -4 }, { x: 1390, y: 520, w: 640, r: 3.2 }],
  [{ x: 560, y: 700, w: 540, r: -5 }, { x: 1060, y: 560, w: 560, r: 2.4 }, { x: 1530, y: 690, w: 500, r: -2.2 }],
  [{ x: 540, y: 710, w: 520, r: -4.5 }, { x: 1010, y: 610, w: 540, r: 2.2 }, { x: 1500, y: 730, w: 480, r: -2.6 },
    { x: 1470, y: 300, w: 440, r: 4 }],
];

/** A push pin dropping onto the board: it falls from above the lens and its shadow closes in. */
const Pin: React.FC<{ at: number; accent: string; top?: number }> = ({ at, accent, top = 24 }) => {
  const frame = useCurrentFrame();
  const k = useK();
  if (frame < at) return null;
  const p = ramp(frame, at, 8, easeIn);
  const up = 1 - p;
  const S = 34 * k;
  return (
    <div style={{ position: "absolute", left: "50%", top: top * k, width: 0, height: 0 }}>
      <div style={{ position: "absolute", left: -S * 0.4 + (5 + up * 30) * k, top: -S * 0.4 + (7 + up * 38) * k,
        width: S * 0.8, height: S * 0.8, borderRadius: "50%", background: `rgba(0,0,0,${0.38 - up * 0.2})`,
        boxShadow: `0 0 ${(6 + up * 12) * k}px rgba(0,0,0,.35)` }} />
      <div style={{ position: "absolute", left: -S / 2, top: -S / 2, width: S, height: S, borderRadius: "50%",
        background: `radial-gradient(circle at 34% 30%, rgba(255,255,255,.95) 0%, ${accent} 26%, #121212 100%)`,
        boxShadow: "0 2px 3px rgba(0,0,0,.45)", opacity: Math.min(1, p * 5 + 0.2),
        transform: `translate(${-up * 12 * k}px, ${-up * 30 * k}px) scale(${1 + up * 1.3})` }} />
    </div>
  );
};

const PinnedPrint: React.FC<{ src: string; slot: Slot; at: number; index: number; accent: string; caption: string }> =
  ({ src, slot, at, index, accent, caption }) => {
    const frame = useCurrentFrame();
    const { fps, durationInFrames } = useVideoConfig();
    const k = useK();
    if (frame < at) return null;
    const w = slot.w * k;
    const B = 16 * k;
    const ph = (slot.w - 32) * 0.7 * k;
    const h = B + ph + 66 * k;
    const p = ramp(frame, at, 18, backOut);
    const pe = ramp(frame, at, 18);
    const air = 1 - pe;
    const hit = at + 20;
    const tt = frame - hit;
    // Pinned at the top: a damped swing when the pin goes in, then a faint idle sway.
    const swing = tt > 0 ? 2.4 * Math.exp(-tt / 15) * Math.sin(tt / 2.8) : 0;
    const idle = 0.3 * Math.sin(frame / (fps * 1.2) + index * 1.9);
    const side = index % 2 ? 1 : -1;
    const qi = ramp(frame, durationInFrames - 14 + index * 1.5, 10, easeIn);
    const rot = slot.r + air * 7 * side + swing + idle + qi * 12 * side;
    return (
      <div style={{ position: "absolute", left: slot.x * k - w / 2, top: slot.y * k - h / 2, width: w, height: h,
        boxSizing: "border-box", padding: `${B}px ${B}px 0`, background: "#f6f3ec",
        transform: `translateY(${-(1 - p) * 240 * k - qi * 1100 * k}px) rotate(${rot}deg) scale(${1 + air * 0.16 + qi * 0.06})`,
        transformOrigin: `50% ${24 * k}px`, opacity: Math.min(1, pe * 4),
        boxShadow: `${(3 + swing * 2 + air * 26) * k}px ${(12 + air * 46) * k}px ${(22 + air * 40) * k}px rgba(0,0,0,${(0.5 - air * 0.22).toFixed(3)})` }}>
        <div style={{ width: "100%", height: ph, overflow: "hidden", background: "#222" }}>
          <Img src={src} style={{ width: "100%", height: "100%", objectFit: "cover", filter: "contrast(1.05) saturate(.9)" }} />
        </div>
        {caption ? (
          <div style={{ height: 66 * k, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <LetterLine text={caption} at={hit + 4} step={Math.min(0.7, 12 / Math.max(1, caption.length))}
              outAt={outFor(durationInFrames, caption.length)} style={{ fontFamily: HAND, fontWeight: 700, fontSize: 38 * k,
              color: "#27221d", lineHeight: 1, whiteSpace: "nowrap" }} />
          </div>
        ) : null}
        <Pin at={at + 12} accent={accent} />
      </div>
    );
  };

const IndexCard: React.FC<{ title: string; sub: string; at: number; accent: string }> = ({ title, sub, at, accent }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const k = useK();
  if (frame < at) return null;
  const p = ramp(frame, at, 18, backOut);
  const pe = ramp(frame, at, 18);
  const air = 1 - pe;
  const qi = ramp(frame, durationInFrames - 16, 10, easeIn);
  const long = title.length > 28;
  const subText = sub.length > 30 ? `${sub.slice(0, 29)}…` : sub;
  return (
    <div style={{ position: "absolute", left: 150 * k, top: 124 * k, width: 520 * k, boxSizing: "border-box",
      padding: `${40 * k}px ${36 * k}px ${34 * k}px`, background: "#f5f1e6",
      backgroundImage: `repeating-linear-gradient(180deg, rgba(0,0,0,0) 0px, rgba(0,0,0,0) ${47 * k}px, rgba(70,100,150,.16) ${47 * k}px, rgba(70,100,150,.16) ${49 * k}px)`,
      borderTop: `${7 * k}px solid ${accent}`, display: "flex", flexDirection: "column", gap: 6 * k,
      transform: `translateY(${-(1 - p) * 200 * k - qi * 1100 * k}px) rotate(${-2.5 - air * 6 - qi * 8}deg) scale(${1 + air * 0.14})`,
      opacity: Math.min(1, pe * 4),
      boxShadow: `${(4 + air * 24) * k}px ${(12 + air * 40) * k}px ${(22 + air * 36) * k}px rgba(0,0,0,${(0.45 - air * 0.2).toFixed(3)})` }}>
      <div style={{ position: "absolute", left: "50%", top: -20 * k, width: 150 * k, height: 40 * k, marginLeft: -75 * k,
        background: "rgba(246,241,226,.6)", border: "1px solid rgba(255,255,255,.4)", transform: "rotate(-4deg)",
        boxShadow: "0 2px 6px rgba(0,0,0,.15)" }} />
      {subText ? (
        <LetterLine text={subText} at={at + 10} step={0.6} outAt={outFor(durationInFrames, subText.length)}
          style={{ fontFamily: HAND, fontWeight: 700, fontSize: 34 * k, color: "#6a5d50", lineHeight: 1.1, whiteSpace: "nowrap" }} />
      ) : null}
      <Title text={title} at={at + 12} size={long ? 42 : 50} chars={long ? 16 : 13} maxLines={3} font={MARKER}
        color="#1c1915" shadow={false} lineHeight={1.1} spacing="0.01em" />
    </div>
  );
};

/**
 * Cork grain: fractal noise pushed to high contrast and overlaid on the warm base, so the board
 * reads as organic granules (a lattice of repeating gradient dots read as pegboard and crawled
 * under the slow push).
 */
const CorkGrain: React.FC = () => {
  const { width, height } = useVideoConfig();
  return (
    <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0, mixBlendMode: "overlay", opacity: 0.62 }}>
      <filter id="pbCorkGrain" x="0" y="0" width="100%" height="100%" colorInterpolationFilters="sRGB">
        <feTurbulence type="fractalNoise" baseFrequency="0.21" numOctaves={4} seed={7} />
        <feColorMatrix type="saturate" values="0" />
        <feComponentTransfer>
          <feFuncR type="linear" slope={2.4} intercept={-0.7} />
          <feFuncG type="linear" slope={2.4} intercept={-0.7} />
          <feFuncB type="linear" slope={2.4} intercept={-0.7} />
          <feFuncA type="linear" slope={0} intercept={1} />
        </feComponentTransfer>
      </filter>
      <rect width={width} height={height} filter="url(#pbCorkGrain)" />
    </svg>
  );
};

const Corkboard: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const k = useK();
  const t = useLife();
  const pics = stills(overlay, 4);
  if (!pics.length) return null;
  const slots = CORK[pics.length - 1];
  const items = listOf(overlay.items);
  const title = str(overlay.text);
  const fade = 1 - ramp(frame, durationInFrames - 6, 5);
  // Prints land one after another; short overlays tighten the stagger so the last caption is
  // fully written (about 48 f after its print lands) before the exit begins.
  const base = title ? 8 : 3;
  const gap = pics.length > 1
    ? Math.max(3, Math.min(9, Math.floor((durationInFrames - 74 - base) / (pics.length - 1)))) : 0;
  return (
    <AbsoluteFill style={{ background: "#6e4f31", overflow: "hidden", opacity: fade }}>
      <AbsoluteFill style={{ transform: `scale(${1.03 + 0.035 * t}) translate(${-12 * k * t}px, ${-6 * k * t}px)` }}>
        <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 40%, #ad8052 0%, #8f6640 52%, #62442a 100%)" }} />
        <CorkGrain />
        <AbsoluteFill style={{ background: "radial-gradient(ellipse at 30% 16%, rgba(255,228,184,.3) 0%, rgba(255,228,184,0) 55%)" }} />
        {title ? <IndexCard title={title} sub={str(overlay.subtitle)} at={2} accent={accent} /> : null}
        {pics.map((src, i) => (
          <PinnedPrint key={i} src={src} slot={slots[i]} at={base + i * gap} index={i} accent={accent}
            caption={str(items[i]?.label).slice(0, 24)} />
        ))}
      </AbsoluteFill>
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${300 * k}px rgba(25,12,4,.85)` }} />
    </AbsoluteFill>
  );
};

// ================================================================== 5. double exposure
const DoubleExposure: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const q = useExit(14);
  const t = useLife();
  const pics = stills(overlay, 2);
  if (!pics.length) return null;
  const A = pics[0];
  const B = pics[1] || pics[0];
  const mirror = pics.length < 2;
  const e = ramp(frame, 0, 20);
  const mix = ramp(frame, Math.round(fps * 0.4), Math.round(fps * 1.8), inOut);
  const m = lerp(150, 58, mix);
  const mask = `linear-gradient(100deg, rgba(0,0,0,0) ${m - 45}%, rgba(0,0,0,1) ${m}%)`;
  const lx = lerp(-10, 110, t);
  const flick = 0.78 + 0.12 * Math.sin(frame * 0.41) * Math.sin(frame * 0.23 + 1.3);
  const flash = Math.sin(q * Math.PI);
  const fadeAll = 1 - ramp(frame, durationInFrames - 7, 6);
  const title = str(overlay.text);
  const ft = fitTitle(title, 78, 24);
  return (
    <AbsoluteFill style={{ background: "#060608", overflow: "hidden", opacity: fadeAll }}>
      <Img src={A} style={{ ...cover, opacity: e, transform: `scale(${1.16 - 0.06 * e + 0.06 * t}) translateX(${-24 * k * t}px)`,
        filter: "grayscale(.45) contrast(1.14) brightness(.78)" }} />
      <Img src={B} style={{ ...cover, opacity: 0.92 * mix, mixBlendMode: "screen",
        transform: `${mirror ? "scaleX(-1) " : ""}scale(${1.3 - 0.14 * t}) translateX(${(40 - 70 * t) * k}px)`,
        filter: "grayscale(.25) contrast(1.25) brightness(.95)", WebkitMaskImage: mask, maskImage: mask }} />
      <AbsoluteFill style={{ mixBlendMode: "screen", opacity: flick * ramp(frame, 6, 24) * (1 + 0.6 * flash),
        background: `radial-gradient(ellipse 55% 75% at ${lx}% 35%, rgba(255,240,215,.72) 0%, ${accent}99 22%, ${accent}33 45%, rgba(0,0,0,0) 70%)` }} />
      <AbsoluteFill style={{ mixBlendMode: "screen", opacity: 0.5 * flick * e,
        background: `linear-gradient(90deg, ${accent}55 0%, rgba(0,0,0,0) 22%, rgba(0,0,0,0) 80%, ${accent}33 100%)` }} />
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 20% 88%, rgba(0,0,0,.62) 0%, rgba(0,0,0,0) 55%)" }} />
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${260 * k}px rgba(0,0,0,.75)` }} />
      <AbsoluteFill style={{ background: "#fff", opacity: flash * 0.3 }} />
      {title ? (
        <div style={{ position: "absolute", left: 110 * k, bottom: 110 * k, display: "flex", flexDirection: "column",
          gap: 10 * k }}>
          <Kicker text={overlay.subtitle} at={16} color={accent} />
          <Title text={title} at={20} size={ft.size} chars={ft.chars} maxLines={2} />
          <Rule at={28} width={140} color={accent} />
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== 6. zoom-through
const ZoomThrough: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const q = useExit(14);
  const pics = stills(overlay, 2);
  if (!pics.length) return null;
  const A = pics[0];
  const B = pics[1] || pics[0];
  const Z = 5;
  const W = 1920 * k;
  const H = 1080 * k;
  // Short overlays run the same beats faster, so the title still gets about a second after the dive
  // (at 3 s: window at 8 f, dive 26-40 f, title exit from ~70 f).
  const sp = Math.max(0.55, Math.min(1, (durationInFrames - 48) / 70));
  const winAt = Math.round(fps * 0.45 * sp);
  const zAt = Math.max(winAt + Math.round(22 * sp), Math.round(fps * 1.45 * sp));
  const zD = Math.max(12, Math.round(fps * 0.8 * sp));
  const land = zAt + zD;
  const zEase = Easing.bezier(0.76, 0, 0.24, 1);
  const sA = (f: number): number =>
    (1.1 - 0.1 * ramp(f, 0, 18) + 0.04 * interpolate(f, [0, zAt], [0, 1], clamp)) * Math.pow(Z, ramp(f, zAt, zD, zEase));
  const s1 = sA(frame);
  const z = ramp(frame, zAt, zD, zEase);
  const ratio = s1 / Math.max(1e-6, sA(frame - 1));
  const blur = Math.min(14, Math.max(0, ratio - 1) * 80) * k;
  const w = Math.max(0, ramp(frame, winAt, 16, backOut));
  const post = interpolate(frame, [land, Math.max(land + 1, durationInFrames)], [0, 0.07], clamp);
  const sB = (s1 / Z) * w * (1 + post) * (1 + 0.2 * q);
  const sBs = Math.max(0.05, sB);
  const e = ramp(frame, 0, 12);
  // The finder brackets and the readout around the window, gone once the dive starts.
  const br = ramp(frame, winAt + 6, 14) * (1 - interpolate(z, [0, 0.35], [0, 1], clamp));
  const ww = W * sB;
  const wh = H * sB;
  const P = 16 * k;
  const L = 34 * k;
  const bx0 = W / 2 - ww / 2 - P;
  const by0 = H / 2 - wh / 2 - P;
  const bx1 = W / 2 + ww / 2 + P;
  const by1 = H / 2 + wh / 2 + P;
  const corners = [
    `M${bx0} ${by0 + L} L${bx0} ${by0} L${bx0 + L} ${by0}`, `M${bx1 - L} ${by0} L${bx1} ${by0} L${bx1} ${by0 + L}`,
    `M${bx0} ${by1 - L} L${bx0} ${by1} L${bx0 + L} ${by1}`, `M${bx1 - L} ${by1} L${bx1} ${by1} L${bx1} ${by1 - L}`,
  ];
  const mag = Math.pow(Z, z);
  const flash = ramp(frame, land - 3, 3) * (1 - ramp(frame, land, 12));
  const border = 1 - interpolate(z, [0.45, 0.9], [0, 1], clamp);
  const labRaw = str(overlay.label).toUpperCase();
  const label = labRaw.length > 30 ? `${labRaw.slice(0, 29)}…` : labRaw;
  // The label names photo 1: it is fully up well before the dive and drops out as the camera goes in.
  const labOut = Math.max(zAt - 4, 26);
  const title = str(overlay.text);
  const ft = fitTitle(title, 72, 26);
  return (
    <AbsoluteFill style={{ background: INK, overflow: "hidden", opacity: 1 - ramp(frame, durationInFrames - 5, 4) }}>
      {z < 0.999 ? (
        <Img src={A} style={{ ...cover, opacity: e, transform: `scale(${s1})`,
          filter: `${blur > 0.05 ? `blur(${blur.toFixed(2)}px) ` : ""}brightness(${(0.92 - 0.22 * Math.min(1, w) * (1 - z)).toFixed(3)})` }} />
      ) : null}
      {w > 0.001 ? (
        <div style={{ position: "absolute", left: 0, top: 0, width: W, height: H, overflow: "hidden",
          transform: `scale(${sB})`, outline: `${(3 * k) / sBs}px solid rgba(255,255,255,${(0.95 * border).toFixed(3)})`,
          boxShadow: `0 ${(30 * k) / sBs}px ${(80 * k) / sBs}px rgba(0,0,0,${(0.6 * (1 - z)).toFixed(3)})`,
          opacity: 1 - q }}>
          <Img src={B} style={{ ...cover }} />
        </div>
      ) : null}
      {br > 0.01 ? (
        <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
          {corners.map((d, i) => (
            <path key={i} d={d} fill="none" stroke={CYAN} strokeWidth={3 * k} strokeLinecap="square" pathLength={1}
              strokeDasharray={1} strokeDashoffset={1 - br} />
          ))}
        </svg>
      ) : null}
      {br > 0.01 ? (
        <div style={{ position: "absolute", left: bx0, top: by0 - 42 * k, fontFamily: MONO, fontWeight: 700, fontSize: 24 * k,
          color: CYAN, letterSpacing: "0.08em", whiteSpace: "nowrap", clipPath: `inset(0 ${(1 - br) * 100}% 0 0)`,
          textShadow: "0 2px 10px rgba(0,0,0,.7)" }}>
          {`ZOOM ×${mag.toFixed(1)}`}
        </div>
      ) : null}
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${(220 + 160 * Math.sin(z * Math.PI)) * k}px rgba(0,0,0,.8)` }} />
      <AbsoluteFill style={{ background: "#fff", opacity: flash * 0.35 }} />
      {label ? (
        <div style={{ position: "absolute", left: 110 * k, top: 96 * k, display: "flex", alignItems: "center", gap: 14 * k }}>
          <div style={{ width: 5 * k, height: 34 * k, background: accent,
            transform: `scaleY(${ramp(frame, 2, 12) * (1 - ramp(frame, labOut + 4, 8))})` }} />
          <LetterLine text={label} at={3} step={Math.min(0.6, 8 / Math.max(1, label.length))} outAt={labOut}
            style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 34 * k, letterSpacing: "0.2em", color: "#fff",
              lineHeight: 1, whiteSpace: "nowrap", textShadow: "0 3px 14px rgba(0,0,0,.7)" }} />
        </div>
      ) : null}
      {title ? (
        <>
          <AbsoluteFill style={{ background: "radial-gradient(ellipse at 18% 90%, rgba(0,0,0,.6) 0%, rgba(0,0,0,0) 55%)",
            opacity: ramp(frame, land - 6, 14) }} />
          <div style={{ position: "absolute", left: 110 * k, bottom: 110 * k, display: "flex", flexDirection: "column",
            gap: 10 * k }}>
            <Kicker text={overlay.subtitle} at={land - 6} color={accent} />
            <Title text={title} at={land - 2} size={ft.size} chars={ft.chars} maxLines={2} />
          </div>
        </>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== 7. annotated photo
const ANCHORS: [number, number][] = [[0.42, 0.47], [0.61, 0.41], [0.58, 0.66], [0.39, 0.69]];

const rot2 = (x: number, y: number, a: number): [number, number] =>
  [x * Math.cos(a) - y * Math.sin(a), x * Math.sin(a) + y * Math.cos(a)];

const Annotated: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const q = useExit(14);
  const t = useLife();
  const pics = stills(overlay, 1);
  if (!pics.length) return null;
  const dur = durationInFrames;
  const raw: OverlayItem[] = listOf(overlay.items).filter((it) => Boolean(it) && str(it.label).length > 0);
  const lab0 = str(overlay.label);
  const fallback: OverlayItem[] = lab0 ? [{ label: lab0 }] : [];
  // Every callout needs about a second on screen, so short overlays carry fewer of them.
  const maxNotes = dur >= 140 ? 4 : dur >= 105 ? 3 : 2;
  const notes: OverlayItem[] = (raw.length ? raw : fallback).slice(0, maxNotes);
  const pace = Math.max(0.6, Math.min(1, (dur - 30) / 120));
  const first = Math.round(fps * 0.8 * pace);
  const every = Math.round(fps * 0.5 * pace);
  const W = 1920 * k;
  const H = 1080 * k;
  const e = ramp(frame, 0, 22);
  // Rack focus: the photo pulls sharp as it lands and softens again as the callouts retract.
  const focus = ramp(frame, 0, 26, inOut);
  const soft = (1 - focus) * 16 + q * 10;
  const fadeAll = 1 - ramp(frame, dur - 7, 6);
  const title = str(overlay.text);
  const ft = fitTitle(title, 60, 30);
  const geo = notes.map((n, i) => {
    const [ax, ay] = ANCHORS[i];
    const labText = str(n.label).toUpperCase();
    const len0 = labText.length;
    const sx = (ax + (hash(i * 7.3 + len0) - 0.5) * 0.05) * W;
    const sy = (ay + (hash(i * 3.1 + len0 * 1.7) - 0.5) * 0.05) * H;
    const left = ax < 0.5;
    const LW = 400 * k;
    const lx = Math.max(100 * k, Math.min(W - 100 * k - LW, left ? sx - 200 * k - LW : sx + 200 * k));
    const ly = sy - 100 * k;
    const x0 = left ? lx + LW + 14 * k : lx - 14 * k;
    const y0 = ly + 22 * k;
    const dx = sx - x0;
    const dy = sy - y0;
    const len = Math.hypot(dx, dy) || 1;
    const ux = dx / len;
    const uy = dy / len;
    const x1 = sx - ux * 36 * k;
    const y1 = sy - uy * 36 * k;
    let px = uy;
    let py = -ux;
    if (py > 0) { px = -px; py = -py; }
    const cx = (x0 + x1) / 2 + px * len * 0.22;
    const cy = (y0 + y1) / 2 + py * len * 0.22;
    const tl = Math.hypot(x1 - cx, y1 - cy) || 1;
    const tx = (x1 - cx) / tl;
    const ty = (y1 - cy) / tl;
    const ah = 18 * k;
    const [r1x, r1y] = rot2(-tx, -ty, 0.45);
    const [r2x, r2y] = rot2(-tx, -ty, -0.45);
    const f = (v: number) => v.toFixed(1);
    return {
      i, sx, sy, left, LW, lx, ly, x1, y1,
      label: len0 > 20 ? `${labText.slice(0, 19)}…` : labText,
      note: str(n.text),
      d: `M${f(x0)} ${f(y0)} Q${f(cx)} ${f(cy)} ${f(x1)} ${f(y1)}`,
      head: `M${f(x1 + ah * r1x)} ${f(y1 + ah * r1y)} L${f(x1)} ${f(y1)} L${f(x1 + ah * r2x)} ${f(y1 + ah * r2y)}`,
      at: first + i * every,
    };
  });
  return (
    <AbsoluteFill style={{ background: INK, overflow: "hidden", opacity: fadeAll }}>
      <Img src={pics[0]} style={{ ...cover, opacity: Math.min(1, e * 2),
        transform: `scale(${1.16 - 0.08 * e + 0.04 * t + 0.03 * q})`,
        filter: `${soft > 0.05 ? `blur(${(soft * k).toFixed(2)}px) ` : ""}brightness(${(0.52 + 0.26 * focus - 0.16 * q).toFixed(3)}) contrast(1.06) saturate(.92)` }} />
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${260 * k}px rgba(0,0,0,.7)` }} />
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 14% 12%, rgba(0,0,0,.55) 0%, rgba(0,0,0,0) 45%)" }} />
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible",
        filter: `drop-shadow(0 ${3 * k}px ${5 * k}px rgba(0,0,0,.6))` }}>
        {geo.map((g) => {
          const mp = Math.max(0, ramp(frame, g.at, 14, backOut) * (1 - q));
          const dr = ramp(frame, g.at + 6, 16, inOut) * (1 - q);
          const hp = Math.max(0, ramp(frame, g.at + 18, 8, backOut) * (1 - q));
          const ph = frame > g.at + 10 ? ((frame - g.at - 10) % 40) / 40 : -1;
          return (
            <g key={g.i}>
              {ph >= 0 ? (
                <circle cx={g.sx} cy={g.sy} r={(22 + ph * 46) * k} fill="none" stroke={accent} strokeWidth={2.5 * k}
                  opacity={(1 - ph) * 0.7 * (1 - q)} />
              ) : null}
              <circle cx={g.sx} cy={g.sy} r={22 * k * mp} fill="none" stroke="#fff" strokeWidth={3 * k} />
              <circle cx={g.sx} cy={g.sy} r={7 * k * mp} fill={accent} />
              <path d={g.d} fill="none" stroke="#fff" strokeWidth={3.5 * k} strokeLinecap="round" pathLength={1}
                strokeDasharray={1} strokeDashoffset={1 - dr} opacity={dr > 0.01 ? 1 : 0} />
              <path d={g.head} fill="none" stroke="#fff" strokeWidth={3.5 * k} strokeLinecap="round" strokeLinejoin="round"
                opacity={hp > 0.01 ? 1 : 0}
                transform={`translate(${g.x1} ${g.y1}) scale(${hp}) translate(${-g.x1} ${-g.y1})`} />
            </g>
          );
        })}
      </svg>
      {geo.map((g) => {
        const ul = ramp(frame, g.at + 16, 14) * (1 - q);
        const sub = lines(g.note, 28).slice(0, 2);
        return (
          <div key={g.i} style={{ position: "absolute", left: g.lx, top: g.ly, width: g.LW, display: "flex",
            flexDirection: "column", alignItems: g.left ? "flex-end" : "flex-start", gap: 6 * k,
            textAlign: g.left ? "right" : "left" }}>
            <div style={{ position: "absolute", left: -60 * k, right: -60 * k, top: -40 * k, bottom: -40 * k,
              background: "radial-gradient(ellipse at 50% 50%, rgba(0,0,0,.5) 0%, rgba(0,0,0,0) 70%)",
              opacity: ramp(frame, g.at + 8, 12) * (1 - q) }} />
            <div style={{ position: "relative", display: "flex", alignItems: "baseline", gap: 12 * k,
              flexDirection: g.left ? "row-reverse" : "row" }}>
              <LetterLine text={pad(g.i + 1)} at={g.at + 12} style={{ fontFamily: MONO, fontWeight: 700, fontSize: 24 * k,
                color: accent }} />
              <LetterLine text={g.label} at={g.at + 14} step={Math.min(0.6, 8 / Math.max(1, g.label.length))}
                outAt={outFor(dur, g.label.length)}
                style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 34 * k, color: "#fff", letterSpacing: "0.06em",
                  lineHeight: 1, whiteSpace: "nowrap", textShadow: "0 3px 12px rgba(0,0,0,.6)" }} />
            </div>
            <div style={{ position: "relative", width: 90 * k, height: 3 * k, background: accent, transform: `scaleX(${ul})`,
              transformOrigin: g.left ? "right" : "left" }} />
            {/* Note lines rise as whole lines (one node each, not one per letter) to stay inside the node budget. */}
            {sub.map((s, si) => (
              <LineRise key={si} text={s} at={g.at + 20 + si * 3} outAt={dur - 13 + si} style={{ position: "relative",
                fontFamily: INTER, fontWeight: 400, fontSize: 24 * k, color: "rgba(255,255,255,.9)", lineHeight: 1.25,
                textShadow: "0 2px 10px rgba(0,0,0,.7)" }} />
            ))}
          </div>
        );
      })}
      {title ? (
        <div style={{ position: "absolute", left: 110 * k, top: 90 * k, display: "flex", flexDirection: "column", gap: 8 * k }}>
          <Kicker text={overlay.subtitle} at={2} color={accent} size={26} />
          <Title text={title} at={6} size={ft.size} chars={ft.chars} maxLines={2} />
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== 8. grid pop
/** With a single photo each cell pushes into a different detail of it (a contact sheet, not four copies). */
const CROPS = ["24% 30%", "76% 28%", "28% 74%", "74% 72%", "50% 24%", "50% 78%"];

const GridPop: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const q = useExit(14);
  const t = useLife();
  const pics = stills(overlay, 6);
  if (!pics.length) return null;
  const single = pics.length === 1;
  const cols = pics.length >= 5 ? 3 : 2;
  const rows = 2;
  // Short overlays merge sooner so the title still holds about a second before it drops out.
  const pace = Math.max(0.6, Math.min(1, (durationInFrames - 50) / 80));
  const mergeAt = Math.round(fps * 1.3 * pace);
  const mD = Math.max(12, Math.round(fps * 0.75 * pace));
  const m = ramp(frame, mergeAt, mD, inOut);
  // Spaced grid on the stage, then the gutters close and it grows into a full-bleed mosaic.
  const W = lerp((cols === 3 ? 1500 : 1380) * k, 1924 * k, m);
  const H = lerp(790 * k, 1084 * k, m);
  const G = lerp(42 * k, 6 * k, m);
  const cw = (W - (cols - 1) * G) / cols;
  const ch = (H - (rows - 1) * G) / rows;
  const x0 = (1920 * k - W) / 2;
  const y0 = (1080 * k - H) / 2;
  const title = str(overlay.text);
  const ft = fitTitle(title, 82, 22);
  const dim = title ? ramp(frame, mergeAt + mD - 12, 18) * (1 - q) : 0;
  return (
    <Stage accent={accent}>
      {Array.from({ length: cols * rows }, (_, idx) => {
        const c = idx % cols;
        const r = Math.floor(idx / cols);
        const order = c + r;
        const at = 3 + order * 5 + r * 2;
        if (frame < at) return null;
        const p = ramp(frame, at, 16, backOut);
        const pe = ramp(frame, at, 16);
        const flash = (1 - ramp(frame, at + 1, 12)) * 0.55;
        const tilt = (hash(idx + 3) - 0.5) * 9 * (1 - pe);
        // Cells flip edge-on in the same diagonal order they popped in; the last (order 3 of a 3x2)
        // is fully edge-on by the final frame.
        const qi = ramp(frame, durationInFrames - 16 + order * 1.5, 10, easeIn);
        const flipDir = c < (cols - 1) / 2 ? -1 : 1;
        const px = (hash(idx * 2.3) - 0.5) * 50 * k * t;
        const py = (hash(idx * 4.1) - 0.5) * 30 * k * t;
        const src = pick(pics, pics.length === 2 ? c + r : idx);
        return (
          <div key={idx} style={{ position: "absolute", left: x0 + c * (cw + G), top: y0 + r * (ch + G), width: cw, height: ch,
            overflow: "hidden", background: INK, opacity: Math.min(1, pe * 3),
            transform: `perspective(${1500 * k}px) rotateY(${qi * 90 * flipDir}deg) rotate(${tilt}deg) scale(${0.55 + 0.45 * p})`,
            boxShadow: `0 ${24 * k * (1 - m)}px ${60 * k * (1 - m)}px rgba(0,0,0,.55)` }}>
            <Img src={src} style={{ ...cover, transformOrigin: single ? CROPS[idx % CROPS.length] : "50% 50%",
              transform: `translate(${px}px, ${py}px) scale(${(single ? 1.62 : 1.28) - 0.12 * pe + 0.06 * t})` }} />
            {flash > 0.01 ? <AbsoluteFill style={{ background: "#fff", opacity: flash }} /> : null}
          </div>
        );
      })}
      {title ? (
        <>
          <AbsoluteFill style={{ opacity: dim,
            background: "radial-gradient(ellipse 60% 55% at 50% 50%, rgba(0,0,0,.74) 0%, rgba(0,0,0,.38) 55%, rgba(0,0,0,0) 82%)" }} />
          <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 12 * k }}>
            <Kicker text={overlay.subtitle} at={mergeAt + mD - 8} color={accent} />
            <Title text={title} at={mergeAt + mD - 4} size={ft.size} chars={ft.chars} align="center" maxLines={2} />
            <Rule at={mergeAt + mD + 4} width={140} color={accent} center />
          </AbsoluteFill>
        </>
      ) : null}
    </Stage>
  );
};

// ================================================================== 9. parallax stack
const ParallaxStack: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const k = useK();
  const t = useLife();
  const pics = stills(overlay, 3);
  if (!pics.length) return null;
  const mid = pics[0];
  const front = pics[1] || pics[0];
  const back = pics[2] || pics[0];
  const crop = pics.length < 2;
  const dur = durationInFrames;
  const eb = ramp(frame, 0, 20);
  const pm = ramp(frame, 3, 26);
  const pf = ramp(frame, 12, 28);
  const qf = ramp(frame, dur - 15, 11, easeIn);
  const qm = ramp(frame, dur - 13, 10, easeIn);
  const qb = ramp(frame, dur - 10, 9, easeIn);
  const W = 1920 * k;
  const H = 1080 * k;
  const span = W * 1.2;
  // Dust in front of the lens: the nearer a mote, the bigger, brighter and faster it drifts.
  const motes = Array.from({ length: 22 }, (_, j) => {
    const d = 0.25 + 0.75 * hash(j * 3.7 + 1);
    const bx = hash(j * 1.9 + 4) * span;
    const x = (((bx - t * d * 520 * k) % span) + span) % span - W * 0.1;
    const y = hash(j * 5.3 + 2) * H - t * d * 70 * k + Math.sin(frame / 38 + j) * 8 * k;
    const s = (2 + 5 * d) * k;
    const tw = 0.6 + 0.4 * Math.sin(frame / 11 + j * 2.1);
    return { j, x, y, s, o: (0.12 + 0.45 * d) * tw };
  });
  const title = str(overlay.text);
  const tag = str(overlay.label);
  const ft = fitTitle(title, 70, 24);
  return (
    <AbsoluteFill style={{ background: "#08080b", overflow: "hidden" }}>
      <AbsoluteFill style={{ opacity: eb * (1 - qb) }}>
        <Img src={back} style={{ ...cover,
          transform: `scale(${1.22 - 0.06 * eb + 0.05 * t + 0.1 * qb}) translateX(${-30 * k * t}px)`,
          filter: `blur(${12 * k}px) brightness(.42) saturate(.85)` }} />
      </AbsoluteFill>
      <AbsoluteFill style={{ opacity: eb * (1 - qb), transform: `translateX(${lerp(-120, 160, t) * k}px)`,
        background: `linear-gradient(112deg, rgba(0,0,0,0) 22%, ${accent}1c 38%, rgba(255,255,255,.05) 44%, rgba(0,0,0,0) 58%)` }} />
      {/* The middle plane sits high enough (bottom ~700 px at its largest) to clear a two-line title block with its tag. */}
      <div style={{ position: "absolute", left: 300 * k, top: 116 * k, width: 1000 * k, height: 562 * k, borderRadius: 8 * k,
        overflow: "hidden", background: INK, opacity: Math.min(1, pm * 2.5) * (1 - qm),
        transform: `translate(${((1 - pm) * 170 - 90 * t) * k}px, ${-10 * k * t}px) scale(${(0.95 + 0.05 * pm + 0.05 * t) * (1 + 0.25 * qm)})`,
        boxShadow: "0 40px 100px rgba(0,0,0,.7)" }}>
        <Img src={mid} style={{ ...cover, transform: `scale(${1.12 - 0.05 * pm}) translateX(${20 * k * t}px)` }} />
        <div style={{ position: "absolute", inset: 0, boxShadow: "inset 0 0 0 1px rgba(255,255,255,.14)" }} />
      </div>
      <div style={{ position: "absolute", left: 1140 * k, top: 450 * k, width: 600 * k, height: 400 * k, borderRadius: 6 * k,
        overflow: "hidden", background: INK, border: `${6 * k}px solid #f4f1ea`,
        opacity: Math.min(1, pf * 2.5) * (1 - qf),
        transform: `translate(${((1 - pf) * 460 - 210 * t + qf * 520) * k}px, ${((1 - pf) * 80 - 30 * t) * k}px) rotate(${-2.2 - (1 - pf) * 7}deg) scale(${(1.45 - 0.45 * pf + 0.08 * t) * (1 + 0.7 * qf)})`,
        boxShadow: "0 50px 110px rgba(0,0,0,.75)" }}>
        <Img src={front} style={{ ...cover, objectPosition: crop ? "35% 40%" : "50% 50%",
          transform: `scale(${crop ? 1.8 : 1.06})` }} />
      </div>
      {motes.map((mo) => (
        <div key={mo.j} style={{ position: "absolute", left: mo.x, top: mo.y, width: mo.s, height: mo.s, borderRadius: "50%",
          background: "rgb(255,244,225)", opacity: mo.o * eb * (1 - qf), boxShadow: `0 0 ${mo.s * 2.5}px rgba(255,236,200,.8)` }} />
      ))}
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 16% 92%, rgba(0,0,0,.66) 0%, rgba(0,0,0,0) 50%)" }} />
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${240 * k}px rgba(0,0,0,.7)` }} />
      {title || tag ? (
        <div style={{ position: "absolute", left: 110 * k, bottom: 100 * k, display: "flex", flexDirection: "column",
          alignItems: "flex-start", gap: 10 * k }}>
          {title ? <Kicker text={overlay.subtitle} at={18} color={accent} /> : null}
          {title ? <Title text={title} at={22} size={ft.size} chars={ft.chars} maxLines={2} /> : null}
          <TagOut text={tag} at={title ? 32 : 20} accent={accent} size={28} />
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== 10. photo with date plate
const DatePlate: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const t = useLife();
  const pics = stills(overlay, 1);
  if (!pics.length) return null;
  let v = Number(overlay.value ?? NaN);
  if (!Number.isFinite(v)) {
    const found = /\b(1[5-9]\d\d|20\d\d)\b/.exec(`${overlay.label || ""} ${overlay.text || ""} ${overlay.subtitle || ""}`);
    if (found) v = Number(found[1]);
  }
  if (!Number.isFinite(v)) return null;
  const yearLike = Number.isInteger(v) && v >= 1000 && v <= 2100;
  const old = yearLike && v < 1975;
  const W = 1920 * k;
  const Hh = 1080 * k;
  const rev = ramp(frame, 0, 22, inOut);
  const qW = ramp(frame, durationInFrames - 12, 10, easeIn);
  const pAt = Math.round(fps * 0.45);
  const PW = 660 * k;
  const PH = 250 * k;
  const SK = 76 * k;
  const BOT = 124 * k;
  const p1 = ramp(frame, pAt, 22);
  const p2 = ramp(frame, pAt + 5, 22);
  const q1 = ramp(frame, durationInFrames - 13, 10, easeIn);
  const q2 = ramp(frame, durationInFrames - 15, 10, easeIn);
  const travel = PW + 140 * k;
  const lab = str(overlay.label);
  const subtitle = str(overlay.subtitle);
  const kickRaw = (lab || subtitle).toUpperCase();
  // 24 wide-tracked caps is what fits the plate beside its slanted edge.
  const kick = kickRaw.length > 24 ? `${kickRaw.slice(0, 23)}…` : kickRaw;
  const sub = lab && subtitle ? subtitle : "";
  const title = str(overlay.text);
  const ft = fitTitle(title, 58, 28);
  // A year rolls at 150 px; longer figures step down so they stay inside the plate.
  const digits = yearLike ? 4 : String(Math.trunc(Math.abs(v))).length;
  const numSize = digits <= 4 ? 150 : digits <= 6 ? 120 : 96;
  const edgeIn = rev > 0.001 && rev < 0.999;
  const edgeOut = qW > 0.001 && qW < 0.999;
  const cm = ramp(frame, 8, 16) * (1 - ramp(frame, durationInFrames - 14, 10));
  const I = 90 * k;
  const L = 46 * k;
  const marks = [
    `M${I} ${I + L} L${I} ${I} L${I + L} ${I}`, `M${W - I - L} ${I} L${W - I} ${I} L${W - I} ${I + L}`,
    `M${I} ${Hh - I - L} L${I} ${Hh - I} L${I + L} ${Hh - I}`, `M${W - I - L} ${Hh - I} L${W - I} ${Hh - I} L${W - I} ${Hh - I - L}`,
  ];
  return (
    <AbsoluteFill style={{ background: INK, overflow: "hidden" }}>
      <AbsoluteFill style={{ clipPath: `inset(0 ${(1 - rev) * 100}% 0 ${qW * 100}%)` }}>
        <Img src={pics[0]} style={{ ...cover, transform: `scale(${1.1 - 0.04 * rev + 0.05 * t})`,
          filter: old ? "grayscale(.85) sepia(.3) contrast(1.1) brightness(.92)" : "contrast(1.05) saturate(.95) brightness(.95)" }} />
        <AbsoluteFill style={{ background: "linear-gradient(0deg, rgba(0,0,0,.62) 0%, rgba(0,0,0,.15) 38%, rgba(0,0,0,0) 60%)" }} />
        <AbsoluteFill style={{ boxShadow: `inset 0 0 ${240 * k}px rgba(0,0,0,.6)` }} />
      </AbsoluteFill>
      {edgeIn || edgeOut ? (
        <div style={{ position: "absolute", top: 0, bottom: 0, left: (edgeIn ? rev : qW) * W - 2 * k, width: 4 * k,
          background: accent, boxShadow: `0 0 ${24 * k}px ${accent}` }} />
      ) : null}
      {cm > 0.01 ? (
        <svg width={W} height={Hh} style={{ position: "absolute", left: 0, top: 0 }}>
          {marks.map((d, i) => (
            <path key={i} d={d} fill="none" stroke="rgba(255,255,255,.85)" strokeWidth={2.5 * k} pathLength={1}
              strokeDasharray={1} strokeDashoffset={1 - cm} />
          ))}
        </svg>
      ) : null}
      {title ? (
        <div style={{ position: "absolute", left: 110 * k, bottom: 128 * k, display: "flex", flexDirection: "column",
          gap: 10 * k, maxWidth: 1000 * k }}>
          <Kicker text={sub} at={pAt + 12} color={accent} size={26} />
          <Title text={title} at={pAt + 14} size={ft.size} chars={ft.chars} maxLines={2} />
        </div>
      ) : null}
      <div style={{ position: "absolute", right: 0, bottom: BOT - 14 * k, width: PW + 36 * k, height: PH + 28 * k,
        background: accent, clipPath: `polygon(${SK}px 0, 100% 0, 100% 100%, 0 100%)`,
        transform: `translateX(${(1 - p1 + q1) * travel}px)` }} />
      <div style={{ position: "absolute", right: 0, bottom: BOT, width: PW, height: PH, boxSizing: "border-box",
        background: "linear-gradient(135deg, rgba(18,18,22,.97), rgba(8,8,10,.94))",
        clipPath: `polygon(${SK}px 0, 100% 0, 100% 100%, 0 100%)`, transform: `translateX(${(1 - p2 + q2) * travel}px)`,
        display: "flex", flexDirection: "column", justifyContent: "center", gap: 2 * k, paddingLeft: SK + 44 * k }}>
        {kick ? (
          <LetterLine text={kick} at={pAt + 10} step={0.5} outAt={outFor(durationInFrames, kick.length) - 3}
            style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 26 * k, letterSpacing: "0.26em", color: accent,
              lineHeight: 1.1, whiteSpace: "nowrap" }} />
        ) : null}
        <Odometer value={v} at={pAt + 8} frames={Math.round(fps * 1.2)} size={numSize * k} color="#fff"
          grouping={!yearLike} prefix={yearLike ? "" : str(overlay.prefix)} suffix={yearLike ? "" : str(overlay.suffix)}
          suffixColor={accent} />
      </div>
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "pb-wipe-compare": WipeCompare,
  "pb-triptych": Triptych,
  "pb-carousel": Carousel,
  "pb-corkboard": Corkboard,
  "pb-double-exposure": DoubleExposure,
  "pb-zoom-through": ZoomThrough,
  "pb-annotated": Annotated,
  "pb-grid-pop": GridPop,
  "pb-parallax-stack": ParallaxStack,
  "pb-date-plate": DatePlate,
};
