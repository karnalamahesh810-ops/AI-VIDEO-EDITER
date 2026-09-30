import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { useK } from "./ProGraphics";
import { EASE, F, bright, boldCaps, caps, fit, measure, outline, str, tween, useExit } from "./Kit";
import { INTER } from "../fonts";
import type { Overlay } from "../../types";

/**
 * Tags that ride on the footage, in the owner's text language (2026-09-30:
 * "NO background layout, ONLY TEXT: bold white text with a black stroke, on
 * the sides"): no pill, plate, panel or box - bold condensed caps with their
 * own black outline and a soft shadow, the key part in the accent.
 *
 *   ProLabels  one to three contrasted labels low in the frame, joined by a
 *              drawn connector with a glowing node ("DROUGHT-HARDENED SOIL
 *              ◆ RECORD RAINFALL"), the second in the accent
 *   ProList    two to four points stacked on the right side: an accent
 *              numeral, the point in outlined bold caps, each sliding in
 *   ProKicker  a place / aside slug top-left: the line in outlined bold caps,
 *              a quieter second line under it, an accent tick drawing first
 *
 * Every line is measured and fitted (it shrinks, wraps, then ellipsises) so
 * nothing runs off the frame; 96 px margins at 1080p; each look leaves in its
 * last 12 frames, element by element.
 */

/** The labels to draw: "label: text" when both are given, else whichever is. */
const labelsOf = (ov: Overlay, max: number): string[] => {
  const out = (ov.items || [])
    .map((it) => (it.label && it.text ? `${str(it.label)}: ${str(it.text)}` : str(it.label) || str(it.text)))
    .filter(Boolean)
    .slice(0, max);
  if (!out.length && str(ov.text)) out.push(str(ov.text));
  return out;
};

/** Letters of a caps line rising one after another out of a mask, dropping out again with `q`. */
const Letters: React.FC<{ text: string; at: number; q?: number; step?: number; style: React.CSSProperties }> =
  ({ text, at, q = 0, step = 0.9, style }) => {
    const frame = useCurrentFrame();
    const chars = Array.from(text);
    return (
      <div style={{ ...style, display: "flex" }}>
        {chars.map((c, i) => {
          const p = tween(frame, at + i * step, 12);
          const y = (1 - p) * 60 + q * 60;
          return (
            <span key={i} style={{ display: "inline-block", whiteSpace: "pre", transform: `translateY(${y.toFixed(2)}%)`,
              opacity: Math.min(1, p * 2.5) * (1 - q) }}>{c}</span>
          );
        })}
      </div>
    );
  };

// ================================================================== ProLabels
/** One to three contrasted labels low in the frame, joined by a connector with a node; the second in the accent. */
export const ProLabels: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const k = useK();
  const q = useExit(12);
  const labels = labelsOf(overlay, 3);
  if (!labels.length) return null;
  const n = labels.length;
  const hot = bright(accent);
  const CONN = n > 1 ? 130 * k : 0;
  const TR = 0.02;
  const room = (width - 192 * k - CONN * (n - 1)) / n;
  // One size for every label (the smallest that fits them all), so they read as a set.
  const fits = labels.map((t) => fit(t.toUpperCase(), F.label, 76 * k, 40 * k, room, 1, TR));
  const size = Math.min(...fits.map((f) => f.size));
  const texts = fits.map((f) => f.lines[0] || "");
  const widths = texts.map((t) => measure(t, F.label, TR) * size);
  const total = widths.reduce((a, b) => a + b, 0) + CONN * (n - 1);
  const single = n === 1;
  const cy = height * 0.68;
  let x = single ? 96 * k + 34 * k : Math.max(96 * k, (width - total) / 2);
  const out: React.ReactNode[] = [];
  texts.forEach((t, i) => {
    const at = 3 + i * 6;
    const left = x;
    const w = widths[i];
    x += w + CONN;
    const colour = i % 2 === 1 ? hot : "#fff";
    out.push(
      <div key={`t${i}`} style={{ position: "absolute", left, top: cy - size * 0.55 }}>
        <Letters text={t} at={at} q={tween(frame, 0, 1) * q} style={boldCaps(size, colour, k, TR)} />
      </div>,
    );
    if (i < n - 1) {
      const a0 = left + w + 18 * k, a1 = left + w + CONN - 18 * k;
      const mid = (a0 + a1) / 2;
      const p = tween(frame, at + 4, 14, EASE.inOut) * (1 - q);
      const half = ((a1 - a0) / 2) * p;
      out.push(
        <React.Fragment key={`c${i}`}>
          <div style={{ position: "absolute", left: mid - half, width: half * 2, top: cy - 2.5 * k, height: 5 * k, borderRadius: 3 * k,
            background: "#fff", boxShadow: "0 0 0 2.5px #000, 0 6px 18px rgba(0,0,0,.55)" }} />
          <div style={{ position: "absolute", left: mid - 14 * k, top: cy - 14 * k, width: 28 * k, height: 28 * k, borderRadius: 4 * k,
            background: hot, transform: `rotate(45deg) scale(${(tween(frame, at + 8, 14, EASE.back) * (1 - q)).toFixed(4)})`,
            boxShadow: `0 0 0 ${3 * k}px #000, 0 0 ${22 * k}px ${hot}` }} />
        </React.Fragment>,
      );
    }
  });
  return (
    <AbsoluteFill>
      {single ? (
        <div style={{ position: "absolute", left: 96 * k, top: cy - size * 0.5, width: 12 * k, height: size * 0.98, background: hot,
          borderRadius: 2 * k, boxShadow: `0 0 0 ${3 * k}px #000, 0 0 ${18 * k}px ${hot}`,
          transform: `scaleY(${(tween(frame, 0, 12) * (1 - q)).toFixed(4)})`, transformOrigin: "50% 100%" }} />
      ) : null}
      {out}
    </AbsoluteFill>
  );
};

// ================================================================== ProList
/** Two to four points stacked on the right: accent numerals, outlined bold caps, sliding in one after another. */
export const ProList: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, width, height } = useVideoConfig();
  const k = useK();
  const q = useExit(12);
  const items = (overlay.items || []).map((it) => str(it.text) || str(it.label)).filter(Boolean).slice(0, 4);
  if (!items.length) return null;
  const n = items.length;
  const hot = bright(accent);
  const title = str(overlay.text) && str(overlay.text) !== items[0] ? caps(overlay.text) : "";
  const RIGHT = 96 * k;
  const NUMW = 92 * k;
  const room = Math.min(900 * k, width * 0.5) - NUMW;
  const base = n <= 2 ? 78 : n === 3 ? 70 : 60;
  const fits = items.map((t) => fit(t.toUpperCase(), F.label, base * k, 38 * k, room, 2, 0.02));
  const size = Math.min(...fits.map((f) => f.size));
  const rows = items.map((t) => fit(t.toUpperCase(), F.label, size, size, room, 2, 0.02));
  const step = Math.max(6, Math.min(Math.round(fps * 0.34), Math.floor((durationInFrames * 0.45) / n)));
  const rowAt = (i: number) => 3 + (title ? 5 : 0) + i * step;
  const GAP = 14 * k;
  const rowH = rows.map((r) => r.lines.length * size * 1.02);
  const titleH = title ? 44 * k + 16 * k : 0;
  const total = rowH.reduce((a, b) => a + b, 0) + GAP * (n - 1) + titleH;
  const top = Math.max(96 * k, Math.min(height * 0.72 - total, height * 0.46 - total / 2));
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", right: RIGHT, top, display: "flex", flexDirection: "column", alignItems: "flex-start", gap: GAP }}>
        {title ? (
          <div style={{ marginBottom: 16 * k - GAP, marginLeft: NUMW * 0.62 + 18 * k }}>
            <Letters text={title} at={0} q={q} step={0.6} style={boldCaps(44 * k, hot, k, 0.12)} />
          </div>
        ) : null}
        {rows.map((r, i) => {
          const at = rowAt(i);
          const p = tween(frame, at, 16);
          const qi = tween(frame, durationInFrames - 13 + (n - 1 - i) * 0.6, 9, EASE.in);
          return (
            <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 18 * k, alignSelf: "stretch",
              transform: `translateX(${((1 - p) * 70 * k + qi * 50 * k).toFixed(2)}px)`, opacity: Math.min(1, p * 2) * (1 - qi) }}>
              <div style={{ width: NUMW * 0.62, flexShrink: 0, display: "flex", justifyContent: "flex-end" }}>
                <span style={{ ...boldCaps(size, hot, k, 0), transform: `scale(${(0.7 + 0.3 * tween(frame, at + 2, 12, EASE.back)).toFixed(4)})`,
                  display: "inline-block", transformOrigin: "100% 60%" }}>{i + 1}</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
                {r.lines.map((ln, j) => (
                  <div key={j} style={boldCaps(size, "#fff", k, 0.02)}>{ln}</div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== ProKicker
/** A slug top-left: an accent tick, the line in outlined bold caps, a quieter second line under it. */
export const ProKicker: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const q = useExit(12);
  let lines = (overlay.items?.length ? overlay.items.map((i) => str(i.text) || str(i.label))
    : str(overlay.text).split(/\s*\|\s*/)).filter(Boolean).slice(0, 2);
  if (!lines.length) return null;
  if (lines.length === 1) {
    // "Kerrville, Texas · Tuesday night": the place leads, the rest is the quieter line.
    const m = /^(.{3,}?)\s+[·•—–]\s+(.{2,})$/.exec(lines[0]);
    if (m) lines = [m[1], m[2]];
  }
  const hot = bright(accent);
  const MAXW = 1000 * k;
  const head = fit(caps(lines[0]), F.label, 68 * k, 40 * k, MAXW, 2, 0.02);
  const sub = lines[1] ? fit(caps(lines[1]), F.label, 38 * k, 28 * k, MAXW, 1, 0.1) : null;
  const tick = tween(frame, 0, 10) * (1 - q);
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: 96 * k, top: 86 * k, display: "flex", gap: 20 * k, alignItems: "stretch" }}>
        <div style={{ width: 10 * k, borderRadius: 2 * k, background: hot, transform: `scaleY(${tick.toFixed(4)})`, transformOrigin: "50% 0",
          boxShadow: `0 0 0 ${3 * k}px #000, 0 0 ${16 * k}px ${hot}` }} />
        <div>
          {head.lines.map((ln, i) => (
            <Letters key={i} text={ln} at={2 + i * 4} q={q} step={0.7} style={boldCaps(head.size, "#fff", k, 0.02)} />
          ))}
          {sub ? (
            <div style={{ marginTop: 4 * k, opacity: tween(frame, 8 + head.lines.length * 4, 10) * (1 - q),
              transform: `translateY(${((1 - tween(frame, 8 + head.lines.length * 4, 14)) * 16 * k).toFixed(2)}px)` }}>
              <span style={{ ...boldCaps(sub.size, hot, k, 0.1) }}>{sub.lines[0]}</span>
            </div>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};

/** Sentence-case outlined text (Inter 800), for longer lines that must stay readable in lower case. */
export const outlinedSentence = (size: number, color = "#fff", k = 1): React.CSSProperties => ({
  fontFamily: INTER, fontWeight: 800, fontSize: size, lineHeight: 1.14, letterSpacing: "-0.01em", whiteSpace: "nowrap",
  ...outline(size, color, k),
});
