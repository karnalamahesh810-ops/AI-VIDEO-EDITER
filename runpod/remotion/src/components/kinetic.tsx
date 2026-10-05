import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { useScale } from "./layout";

/**
 * Motion primitives shared by the text templates, so every one of them moves
 * with the same After-Effects grammar: words rise out of a blur one after
 * another on an expo-out curve, rules draw, plates settle from a hair too
 * small, and everything keeps a slow drift while it holds.
 */
const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };

/** Expo-out: fast start, long soft landing. */
export const expo = (t: number) => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t));

/** 0 -> 1 from `at` over `frames`, expo-out. */
export const run = (frame: number, at: number, frames: number) =>
  interpolate(frame, [at, at + Math.max(1, frames)], [0, 1], { ...clamp, easing: expo });

/** Style for one staggered element: rises, sharpens and fades in. */
export const riseStyle = (p: number, px: number, blur = 14): React.CSSProperties => ({
  opacity: p,
  transform: `translateY(${(1 - p) * px}px)`,
  filter: p < 1 ? `blur(${(1 - p) * blur}px)` : undefined,
});

/**
 * Text revealed word by word. `at` is the first word's frame, `step` the
 * frames between words, `mark` the words to draw as accent boxes (the box
 * wipes open a beat after its word lands).
 */
export const Words: React.FC<{
  text: string;
  at?: number;
  step?: number;
  mark?: Set<string>;
  accent?: string;
  boxColor?: string;
  style?: React.CSSProperties;
  markStyle?: React.CSSProperties;
  rise?: number;
}> = ({ text, at = 0, step = 3, mark, accent = "#F2B544", boxColor, style, markStyle, rise = 28 }) => {
  const frame = useCurrentFrame();
  const s = useScale();
  const words = text.split(/\s+/).filter(Boolean);
  const norm = (w: string) => w.toLowerCase().replace(/[^\p{L}\p{N}']/gu, "");
  return (
    <span style={style}>
      {words.map((w, i) => {
        const p = run(frame, at + i * step, 10);
        const hot = mark?.has(norm(w));
        const box = hot ? run(frame, at + i * step + 4, 8) : 0;
        return (
          <span key={i} style={{ display: "inline-block", marginRight: "0.28em", position: "relative", ...riseStyle(p, s(rise)) }}>
            {hot ? (
              <span style={{ position: "absolute", inset: `-0.06em -0.16em`, background: boxColor || accent,
                transform: `scaleX(${box})`, transformOrigin: "left center", borderRadius: s(4) }} />
            ) : null}
            <span style={{ position: "relative", ...(hot ? markStyle : undefined) }}>{w}</span>
          </span>
        );
      })}
    </span>
  );
};

/** A rule that draws from left to right. */
export const Rule: React.FC<{ p: number; width: number | string; height?: number; color: string; style?: React.CSSProperties }> =
  ({ p, width, height = 4, color, style }) => (
    <div style={{ width, height, background: color, transform: `scaleX(${p})`, transformOrigin: "left center", ...style }} />
  );

/**
 * A glass plate: dark, blurred, with a gradient edge and an accent bar that
 * grows in on the left. Settles from 0.96 scale.
 */
export const Plate: React.FC<{
  p: number;
  accent: string;
  bar?: boolean;
  radius?: number;
  padding?: string;
  style?: React.CSSProperties;
  children?: React.ReactNode;
}> = ({ p, accent, bar = true, radius = 18, padding, style, children }) => {
  const s = useScale();
  return (
    <div style={{
      position: "relative", opacity: p, transform: `scale(${0.96 + 0.04 * p})`,
      background: "linear-gradient(135deg, rgba(14,14,18,0.86) 0%, rgba(10,10,13,0.72) 100%)",
      backdropFilter: "blur(14px)", borderRadius: s(radius), padding: padding ?? `${s(30)}px ${s(46)}px`,
      boxShadow: "0 30px 80px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.08)",
      border: "1px solid rgba(255,255,255,0.08)", overflow: "hidden", ...style,
    }}>
      {bar ? (
        <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: s(10), background: accent,
          transform: `scaleY(${p})`, transformOrigin: "top" }} />
      ) : null}
      {children}
    </div>
  );
};

/** A slow continuous drift for a held element: never quite still. */
export const useDrift = (px = 10) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = useScale();
  const t = frame / fps;
  return `translate(${Math.sin(t * 0.6) * s(px) * 0.4}px, ${Math.cos(t * 0.45) * s(px) * 0.3}px)`;
};

/** A soft dark vignette behind a card so type stays readable on any footage. */
export const Shade: React.FC<{ p: number; strength?: number; at?: string }> = ({ p, strength = 0.55, at = "50% 50%" }) => (
  <div style={{ position: "absolute", inset: 0, opacity: p, pointerEvents: "none",
    background: `radial-gradient(ellipse at ${at}, rgba(0,0,0,${strength}) 0%, rgba(0,0,0,${strength * 0.5}) 45%, rgba(0,0,0,0) 80%)` }} />
);
