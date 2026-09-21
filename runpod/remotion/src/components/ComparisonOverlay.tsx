import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import {
  PANEL_BG, PANEL_SHADOW, SANS, formatNumber,
  growth, useOverlayAnim, useOverlaySafeStyle, useScale,
} from "./layout";
import type { Overlay } from "../types";

/**
 * Two figures set against each other, meeting at a centre rule.
 *
 * Distinct from the bar chart on purpose: a chart ranks several things, a
 * comparison stages a confrontation between exactly two, which is how
 * documentary narration usually frames a discrepancy (reported vs actual,
 * then vs now). Extra items beyond the first two are ignored rather than
 * squeezed in.
 */
export const ComparisonOverlay: React.FC<{ overlay: Overlay; accent: string }> = ({
  overlay,
  accent,
}) => {
  const { frame, enter, opacity, durationInFrames } = useOverlayAnim(18, 12);
  const s = useScale();
  const safe = useOverlaySafeStyle();

  const items = (overlay.items || []).filter((i) => Number.isFinite(i.value as number));
  if (items.length < 2) return null;
  const [left, right] = items;
  const grow = growth(frame, Math.floor(durationInFrames * 0.45));

  const side = (
    label: string,
    value: number,
    text: string | undefined,
    colour: string,
    from: number
  ) => (
    <div
      style={{
        flex: 1,
        textAlign: "center",
        transform: `translateX(${interpolate(enter, [0, 1], [from, 0])}px)`,
      }}
    >
      <div
        style={{
          fontFamily: SANS,
          fontSize: s(28),
          fontWeight: 700,
          letterSpacing: "0.16em",
          textTransform: "uppercase",
          color: "rgba(255,255,255,0.7)",
          marginBottom: s(10),
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: SANS,
          fontSize: s(104),
          fontWeight: 900,
          lineHeight: 1,
          color: colour,
          letterSpacing: "-0.035em",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {formatNumber(value * grow)}
      </div>
      {text ? (
        <div
          style={{
            fontFamily: SANS,
            fontSize: s(26),
            fontWeight: 500,
            color: "rgba(255,255,255,0.72)",
            marginTop: s(10),
          }}
        >
          {text}
        </div>
      ) : null}
    </div>
  );

  return (
    <AbsoluteFill
      style={{ ...safe, justifyContent: "center", alignItems: "center", opacity }}
    >
      <div
        style={{
          background: PANEL_BG,
          borderRadius: s(20),
          padding: `${s(40)}px ${s(56)}px`,
          minWidth: "58%",
          boxShadow: PANEL_SHADOW,
          backdropFilter: "blur(10px)",
        }}
      >
        {overlay.text ? (
          <div
            style={{
              fontFamily: SANS,
              fontSize: s(38),
              fontWeight: 800,
              color: "#fff",
              textAlign: "center",
              marginBottom: s(30),
            }}
          >
            {overlay.text}
          </div>
        ) : null}
        <div style={{ display: "flex", alignItems: "center", gap: s(24) }}>
          {side(left.label, left.value as number, left.text, "#fff", s(-60))}
          <div
            style={{
              width: s(3),
              alignSelf: "stretch",
              background: "rgba(255,255,255,0.18)",
              position: "relative",
            }}
          >
            <div
              style={{
                position: "absolute",
                top: "50%",
                left: "50%",
                transform: "translate(-50%,-50%)",
                fontFamily: SANS,
                fontSize: s(26),
                fontWeight: 800,
                color: accent,
                background: "#0a0a0c",
                padding: `${s(6)}px ${s(12)}px`,
                borderRadius: s(8),
                letterSpacing: "0.08em",
              }}
            >
              VS
            </div>
          </div>
          {side(right.label, right.value as number, right.text, accent, s(60))}
        </div>
      </div>
    </AbsoluteFill>
  );
};
