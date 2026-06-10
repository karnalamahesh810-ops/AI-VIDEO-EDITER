import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate } from "remotion";
import { Theme } from "../theme";
import { fadeRise, popIn, drawOn } from "../anim";

const W = 1920;
const H = 1080;

// "How it works" sequence: a horizontal row of numbered accent circles (white number
// 1..N) connected by a horizontal line BETWEEN circles that draws on left->right
// (stroke-dashoffset) as each next circle pops in, staggered. Under each circle a bold
// white label + optional muted sub fade+rise. Centered vertically. Fades out near end.
export const ProcessSteps: React.FC<{
  steps: { label: string; sub?: string }[];
  theme: Theme;
  durationInFrames: number;
}> = ({ steps, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
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

  const n = Math.max(1, steps.length);

  // Row geometry: evenly spaced circle centers across a padded span, vertically centered.
  const rowY = H / 2;
  const padX = 260;
  const x0 = padX;
  const x1 = W - padX;
  const span = x1 - x0;
  const stepX = (i: number) => (n <= 1 ? (x0 + x1) / 2 : x0 + (i / (n - 1)) * span);

  const circleR = 56;
  // Label box width: roughly the per-step slot, capped so neighbours don't collide.
  const slot = n <= 1 ? 420 : span / (n - 1);
  const labelW = Math.min(360, Math.max(180, slot - 28));

  // Cadence: each circle pops, then the connector to the NEXT circle draws on, then the
  // next circle pops, etc. Keep ins ~popIn(16f) + draw(14f).
  const stepStart = 6;
  const stepStep = 18;
  const drawDur = 14;

  return (
    <AbsoluteFill style={{ pointerEvents: "none", opacity: rootOpacity }}>
      {/* Connector lines between adjacent circles (drawn first, behind circles). */}
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height="100%"
        style={{ display: "block", overflow: "visible" }}
      >
        {steps.slice(0, n - 1).map((_, i) => {
          const ax = stepX(i) + circleR;
          const bx = stepX(i + 1) - circleR;
          const len = Math.max(0, bx - ax);
          // The connector after circle i draws as circle i+1 is about to appear.
          const draw = drawOn(frame, { delay: stepStart + i * stepStep + 8, dur: drawDur });
          return (
            <line
              key={`c${i}`}
              x1={ax}
              y1={rowY}
              x2={bx}
              y2={rowY}
              stroke={theme.accent}
              strokeWidth={6}
              strokeLinecap="round"
              strokeDasharray={len}
              strokeDashoffset={len * (1 - draw)}
              opacity={0.9}
            />
          );
        })}
      </svg>

      {/* Numbered circles + labels (HTML, positioned over the SVG row). */}
      {steps.map((s, i) => {
        const cx = stepX(i);
        const pop = popIn(frame, fps, { delay: stepStart + i * stepStep, from: 0.4, outAt, outDur: 10 });
        const lbl = fadeRise(frame, {
          delay: stepStart + i * stepStep + 8,
          dur: 12,
          dist: 14,
          outAt,
          outDur: 10,
        });
        return (
          <div key={i} style={{ position: "absolute", left: cx, top: rowY }}>
            {/* Numbered accent circle. */}
            <div
              style={{
                position: "absolute",
                left: -circleR,
                top: -circleR,
                width: circleR * 2,
                height: circleR * 2,
                borderRadius: "50%",
                background: theme.accent,
                border: "4px solid #FFFFFF",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "#FFFFFF",
                fontFamily: theme.headerFont,
                fontWeight: 700,
                fontSize: 52,
                lineHeight: 1,
                opacity: pop.opacity,
                transform: pop.transform,
                boxShadow: `0 10px 28px rgba(0,0,0,0.45), 0 0 18px ${theme.accent}66`,
              }}
            >
              {i + 1}
            </div>
            {/* Label + optional sub, centered under the circle. */}
            <div
              style={{
                position: "absolute",
                top: circleR + 22,
                left: -labelW / 2,
                width: labelW,
                textAlign: "center",
                opacity: lbl.opacity,
                transform: lbl.transform,
              }}
            >
              <div
                style={{
                  fontFamily: theme.bodyFont,
                  fontWeight: 800,
                  fontSize: 34,
                  color: theme.text,
                  letterSpacing: 0.3,
                  lineHeight: 1.15,
                  textShadow: "0 2px 14px rgba(0,0,0,0.6)",
                }}
              >
                {s.label}
              </div>
              {s.sub ? (
                <div
                  style={{
                    marginTop: 8,
                    fontFamily: theme.bodyFont,
                    fontWeight: 500,
                    fontSize: 24,
                    color: theme.textMute,
                    lineHeight: 1.2,
                    textShadow: "0 2px 12px rgba(0,0,0,0.55)",
                  }}
                >
                  {s.sub}
                </div>
              ) : null}
            </div>
          </div>
        );
      })}
    </AbsoluteFill>
  );
};
