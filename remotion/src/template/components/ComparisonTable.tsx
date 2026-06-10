import React from "react";
import { AbsoluteFill, useCurrentFrame, interpolate } from "remotion";
import { Theme } from "../theme";
import { fadeRise, stagger } from "../anim";

// Side-by-side comparison table on a dark panel. Three columns: a row label, the left
// value, and the right value. The header row tints the left title cell with theme.alert
// and the right title cell with theme.accent (both white bold). Body rows alternate
// subtle striping; a boolean true -> green "✓", false -> red "✗"; strings render as
// text. Rows stagger-fade in top->bottom. Renders full-bg (solid theme.panel) or as a
// translucent glass panel over b-roll. Fades out near the end.
export const ComparisonTable: React.FC<{
  leftTitle: string;
  rightTitle: string;
  rows: { label: string; left: string | boolean; right: string | boolean }[];
  fullBg?: boolean;
  theme: Theme;
  durationInFrames: number;
}> = ({ leftTitle, rightTitle, rows, fullBg = false, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const outAt = durationInFrames - 12;

  const fade = interpolate(frame, [0, 10], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const fadeOut = interpolate(frame, [outAt, outAt + 12], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const rootOpacity = fade * fadeOut;

  const panelA = fadeRise(frame, { delay: 0, dur: 12, dist: fullBg ? 0 : 18, outAt, outDur: 10 });
  const headA = fadeRise(frame, { delay: 6, dur: 12, dist: 14, outAt, outDur: 10 });

  const GREEN = "#2FBF5B";
  const RED = theme.alert;

  // Column template: wide label gutter, then two equal value columns.
  const cols = "1.4fr 1fr 1fr";

  // Render a boolean as a colored glyph, otherwise the string as-is.
  const renderCell = (v: string | boolean): React.ReactNode => {
    if (typeof v === "boolean") {
      return (
        <span
          style={{
            fontFamily: theme.bodyFont,
            fontWeight: 900,
            fontSize: 46,
            color: v ? GREEN : RED,
            lineHeight: 1,
          }}
        >
          {v ? "✓" : "✗"}
        </span>
      );
    }
    return (
      <span
        style={{
          fontFamily: theme.bodyFont,
          fontWeight: 600,
          fontSize: 34,
          color: theme.text,
          lineHeight: 1.15,
        }}
      >
        {v}
      </span>
    );
  };

  const panelStyle: React.CSSProperties = fullBg
    ? { position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }
    : { position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" };

  const PW = fullBg ? 1500 : 1320;

  return (
    <AbsoluteFill style={{ ...(fullBg ? { background: theme.bg } : {}), pointerEvents: "none", opacity: rootOpacity }}>
      <div style={panelStyle}>
        <div
          style={{
            width: PW,
            background: theme.panel,
            opacity: fullBg ? 1 : 0.82,
            borderRadius: fullBg ? 0 : 22,
            overflow: "hidden",
            boxShadow: fullBg ? "none" : "0 24px 60px rgba(0,0,0,0.5)",
            transform: panelA.transform,
          }}
        >
          {/* Header row: blank label cell + two tinted title cells. */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: cols,
              alignItems: "stretch",
              opacity: headA.opacity,
              transform: headA.transform,
            }}
          >
            <div style={{ padding: "22px 30px" }} />
            <div
              style={{
                background: RED,
                padding: "22px 30px",
                textAlign: "center",
                fontFamily: theme.headerFont,
                fontWeight: 800,
                textTransform: "uppercase",
                letterSpacing: 1,
                fontSize: 38,
                color: theme.text,
              }}
            >
              {leftTitle}
            </div>
            <div
              style={{
                background: theme.accent,
                padding: "22px 30px",
                textAlign: "center",
                fontFamily: theme.headerFont,
                fontWeight: 800,
                textTransform: "uppercase",
                letterSpacing: 1,
                fontSize: 38,
                color: theme.text,
              }}
            >
              {rightTitle}
            </div>
          </div>

          {/* Body rows: stagger-fade top->bottom, subtle alternating stripes. */}
          {rows.map((r, i) => {
            const rowP = stagger(frame, i, { delay: 14, step: 5, dur: 10 });
            const stripe = i % 2 === 1;
            return (
              <div
                key={`row${i}`}
                style={{
                  display: "grid",
                  gridTemplateColumns: cols,
                  alignItems: "center",
                  background: stripe ? "rgba(255,255,255,0.05)" : "transparent",
                  borderTop: "1px solid rgba(255,255,255,0.08)",
                  opacity: rowP,
                  transform: `translateY(${(1 - rowP) * 12}px)`,
                }}
              >
                {/* Row label. */}
                <div
                  style={{
                    padding: "22px 30px",
                    fontFamily: theme.bodyFont,
                    fontWeight: 700,
                    fontSize: 34,
                    color: theme.text,
                    lineHeight: 1.15,
                  }}
                >
                  {r.label}
                </div>
                {/* Left value. */}
                <div style={{ padding: "22px 30px", textAlign: "center" }}>
                  {renderCell(r.left)}
                </div>
                {/* Right value. */}
                <div style={{ padding: "22px 30px", textAlign: "center" }}>
                  {renderCell(r.right)}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};
