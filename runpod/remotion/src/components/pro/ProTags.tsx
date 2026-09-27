import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { LABEL } from "../fonts";
import { MaskLine, ramp, useK } from "./ProGraphics";
import type { Overlay } from "../../types";

/**
 * Tags that ride on the footage, rebuilt after the owner rejected the dark
 * glass label boxes: VidRush's clean white pills ("Shocks", "Cars stalled",
 * "Dragged chains") with a dot and a short leader line, a compact numbered
 * list on a frosted panel, and a kicker line with an accent bar. All small:
 * the footage stays the picture.
 */
const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };

/** Up to three white pill labels, each popping in on a spring with its dot and leader line. */
export const ProLabels: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const labels = (overlay.items || [])
    .map((it) => (it.label && it.text ? `${it.label}: ${it.text}` : it.label || it.text || ""))
    .filter(Boolean)
    .slice(0, 3);
  if (!labels.length && overlay.text) labels.push(overlay.text);
  // Where the pills sit, by how many there are (never over the caption strip).
  const spots: { x: number; y: number; side: 1 | -1 }[][] = [
    [{ x: 0.2, y: 0.34, side: 1 }],
    [{ x: 0.16, y: 0.3, side: 1 }, { x: 0.66, y: 0.46, side: -1 }],
    [{ x: 0.14, y: 0.26, side: 1 }, { x: 0.64, y: 0.36, side: -1 }, { x: 0.22, y: 0.58, side: 1 }],
  ];
  const place = spots[labels.length - 1];
  return (
    <AbsoluteFill>
      {labels.map((text, i) => {
        const at = Math.round(fps * 0.1) + i * Math.round(fps * 0.35);
        const pop = spring({ frame: frame - at, fps, config: { damping: 14, stiffness: 180, mass: 0.6 } });
        const line = ramp(frame, at + 6, 10);
        const { x, y, side } = place[i];
        const lineW = 70 * k;
        return (
          <div key={i} style={{ position: "absolute", left: `${x * 100}%`, top: `${y * 100}%`, display: "flex",
            alignItems: "center", flexDirection: side === 1 ? "row" : "row-reverse", gap: 0,
            opacity: interpolate(frame - at, [0, 4], [0, 1], clamp) }}>
            <div style={{ background: "#fff", color: "#111", fontFamily: LABEL, fontWeight: 700, fontSize: 38 * k,
              padding: `${8 * k}px ${22 * k}px`, borderRadius: 40 * k, letterSpacing: "0.01em", whiteSpace: "nowrap",
              boxShadow: "0 10px 30px rgba(0,0,0,.35)", transform: `scale(${pop})`,
              transformOrigin: side === 1 ? "right center" : "left center" }}>{text}</div>
            <div style={{ width: lineW * line, height: 3 * k, background: "#fff", boxShadow: "0 0 6px rgba(0,0,0,.5)" }} />
            <div style={{ width: 16 * k, height: 16 * k, borderRadius: "50%", background: accent, border: `${3 * k}px solid #fff`,
              transform: `scale(${line})`, boxShadow: `0 0 ${12 * k}px ${accent}` }} />
          </div>
        );
      })}
    </AbsoluteFill>
  );
};

/** Three or four points on a compact frosted panel at the right, each sliding in with its number chip. */
export const ProList: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const items = (overlay.items || []).map((it) => it.text || it.label || "").filter(Boolean).slice(0, 4);
  if (!items.length) return null;
  const panel = ramp(frame, 0, 14);
  const step = Math.min(fps * 0.6, (durationInFrames * 0.5) / Math.max(1, items.length));
  const title = overlay.text && overlay.text !== items[0] ? overlay.text : "";
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", right: 90 * k, top: "50%", transform: `translate(${(1 - panel) * 60 * k}px, -50%)`,
        opacity: panel, width: 620 * k, padding: `${26 * k}px ${30 * k}px`, borderRadius: 18 * k,
        background: "linear-gradient(135deg, rgba(16,16,20,.82), rgba(16,16,20,.66))", backdropFilter: "blur(14px)",
        border: "1px solid rgba(255,255,255,.12)", boxShadow: "0 24px 60px rgba(0,0,0,.45)",
        display: "flex", flexDirection: "column", gap: 14 * k }}>
        {title ? (
          <MaskLine at={2}><span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k, letterSpacing: "0.2em",
            color: accent, textTransform: "uppercase" }}>{title}</span></MaskLine>
        ) : null}
        {items.map((text, i) => {
          const p = ramp(frame, Math.round(fps * 0.2 + i * step), 12);
          return (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 16 * k, opacity: p,
              transform: `translateX(${(1 - p) * 30 * k}px)` }}>
              <div style={{ width: 40 * k, height: 40 * k, borderRadius: 10 * k, background: accent, color: "#fff",
                fontFamily: LABEL, fontWeight: 800, fontSize: 26 * k, display: "flex", alignItems: "center",
                justifyContent: "center", flexShrink: 0 }}>{i + 1}</div>
              <div style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 36 * k, color: "#fff", lineHeight: 1.12 }}>{text}</div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

/** A kicker top-left: an accent bar grows, one or two short lines slide up beside it. */
export const ProKicker: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const lines = (overlay.items?.length ? overlay.items.map((i) => i.text || i.label || "")
    : (overlay.text || "").split(/\s*\|\s*/)).filter(Boolean).slice(0, 2);
  if (!lines.length) return null;
  const bar = ramp(frame, 0, 12);
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: 96 * k, top: 90 * k, display: "flex", gap: 18 * k, alignItems: "stretch" }}>
        <div style={{ width: 7 * k, background: accent, transform: `scaleY(${bar})`, transformOrigin: "top",
          boxShadow: `0 0 ${10 * k}px ${accent}` }} />
        <div style={{ display: "flex", flexDirection: "column", gap: 2 * k }}>
          {lines.map((ln, i) => (
            <MaskLine key={i} at={3 + i * 4}>
              <span style={{ fontFamily: LABEL, fontWeight: i === 0 ? 800 : 600, fontSize: (i === 0 ? 46 : 32) * k,
                letterSpacing: i === 0 ? "0.06em" : "0.1em", color: i === 0 ? "#fff" : "rgba(255,255,255,.82)",
                textTransform: "uppercase", textShadow: "0 4px 18px rgba(0,0,0,.7)" }}>{ln}</span>
            </MaskLine>
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};
