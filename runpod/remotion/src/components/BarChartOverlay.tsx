import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import {
  PANEL_BG, PANEL_SHADOW, SANS, formatNumber,
  growth, useOverlayAnim, useOverlaySafeStyle, useScale,
} from "./layout";
import type { Overlay } from "../types";

/**
 * Horizontal bar chart — the "Official vs Civilian" graphic from the
 * reference renders.
 *
 * Bars are staggered so the eye reads them in order rather than watching
 * everything grow at once, and each bar is scaled against the largest value
 * so the longest one always fills the track. Values are validated finite
 * upstream; a non-finite one here would silently produce a zero-width bar.
 */
export const BarChartOverlay: React.FC<{ overlay: Overlay; accent: string }> = ({
  overlay,
  accent,
}) => {
  const { frame, enter, opacity, durationInFrames } = useOverlayAnim(18, 12);
  const s = useScale();
  const safe = useOverlaySafeStyle();

  const items = (overlay.items || []).filter((i) => Number.isFinite(i.value as number));
  if (items.length < 2) return null;

  const max = Math.max(...items.map((i) => Math.abs(i.value as number)), 1);
  // Leave the back half of the clip for reading the finished chart.
  const growFrames = Math.floor(durationInFrames * 0.45);
  const stagger = Math.max(2, Math.floor(growFrames / (items.length * 3)));

  return (
    <AbsoluteFill
      style={{
        ...safe,
        justifyContent: "center",
        alignItems: "center",
        opacity,
        transform: `translateY(${interpolate(enter, [0, 1], [s(40), 0])}px)`,
      }}
    >
      <div
        style={{
          background: PANEL_BG,
          borderRadius: s(20),
          padding: `${s(38)}px ${s(48)}px`,
          minWidth: "52%",
          maxWidth: "76%",
          boxShadow: PANEL_SHADOW,
          backdropFilter: "blur(10px)",
        }}
      >
        {overlay.text ? (
          <div
            style={{
              fontFamily: SANS,
              fontSize: s(40),
              fontWeight: 800,
              color: "#fff",
              marginBottom: s(28),
              letterSpacing: "-0.01em",
            }}
          >
            {overlay.text}
          </div>
        ) : null}

        {items.map((item, i) => {
          const grow = growth(frame - i * stagger, growFrames);
          const width = (Math.abs(item.value as number) / max) * 100 * grow;
          return (
            <div key={i} style={{ marginBottom: i === items.length - 1 ? 0 : s(22) }}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "baseline",
                  fontFamily: SANS,
                  fontSize: s(30),
                  fontWeight: 600,
                  color: "rgba(255,255,255,0.9)",
                  marginBottom: s(8),
                }}
              >
                <span>{item.label}</span>
                <span
                  style={{
                    color: accent,
                    fontWeight: 900,
                    fontSize: s(36),
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {formatNumber((item.value as number) * grow)}
                </span>
              </div>
              <div
                style={{
                  height: s(18),
                  borderRadius: s(9),
                  background: "rgba(255,255,255,0.12)",
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    width: `${width}%`,
                    height: "100%",
                    borderRadius: s(9),
                    // Alternating weight separates adjacent bars without
                    // introducing a second hue that means nothing.
                    background: i % 2 === 0 ? accent : "rgba(255,255,255,0.55)",
                    boxShadow: i % 2 === 0 ? `0 0 ${s(22)}px ${accent}` : "none",
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
