import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate, staticFile } from "remotion";
import { Theme } from "../theme";
import { slideIn } from "../anim";

const H = 1080;

// Cutout subject in a thin rectangular accent2 border (~5px, sharp corners) with a drop
// shadow, anchored to the left or right third and vertically centered. The subject sits
// slightly proud of the top frame line (overlaps ~8%) for depth. Optional label pill sits
// under the frame. Enters via slideIn from `side`; if no imgSrc, a theme.panel silhouette
// placeholder is shown. Fades out near the end.
export const PortraitFrame: React.FC<{
  imgSrc?: string;
  side?: "left" | "right";
  label?: string;
  theme: Theme;
  durationInFrames: number;
}> = ({ imgSrc, side = "right", label, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const outAt = durationInFrames - 12;

  const slide = slideIn(frame, fps, { side, delay: 0, dist: 160, outAt, outDur: 10 });

  // Frame geometry, anchored to the chosen side third.
  const frameW = 520;
  const frameH = 760;
  const overlap = frameH * 0.08; // how far the subject rises above the top frame line
  const sideOffset = 200; // distance of the frame's outer edge from the screen edge

  const anchor: React.CSSProperties =
    side === "right" ? { right: sideOffset } : { left: sideOffset };

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          top: H / 2,
          ...anchor,
          transform: `translateY(-50%) ${slide.transform}`,
          opacity: slide.opacity,
        }}
      >
        {/* Frame box: thin sharp-cornered accent2 border + drop shadow. */}
        <div
          style={{
            position: "relative",
            width: frameW,
            height: frameH,
            border: `5px solid ${theme.accent2}`,
            background: theme.panel,
            boxShadow: "0 30px 70px rgba(0,0,0,0.6)",
          }}
        >
          {/* Subject, rising slightly above the top frame line for depth. */}
          <div
            style={{
              position: "absolute",
              left: 0,
              right: 0,
              bottom: 0,
              top: -overlap,
              overflow: "visible",
            }}
          >
            {imgSrc ? (
              <img
                src={staticFile(imgSrc)}
                alt=""
                style={{
                  width: "100%",
                  height: "100%",
                  objectFit: "cover",
                  objectPosition: "top center",
                  display: "block",
                  filter: "drop-shadow(0 14px 24px rgba(0,0,0,0.45))",
                }}
              />
            ) : (
              // Silhouette placeholder: a head+shoulders bust on the panel fill.
              <svg
                viewBox="0 0 520 820"
                width="100%"
                height="100%"
                preserveAspectRatio="xMidYMax meet"
                style={{ display: "block" }}
              >
                <g fill={theme.textMute} opacity={0.5}>
                  <circle cx={260} cy={300} r={130} />
                  <path d="M 80 820 C 80 600 160 500 260 500 C 360 500 440 600 440 820 Z" />
                </g>
              </svg>
            )}
          </div>
        </div>

        {/* Optional label pill under the frame. */}
        {label ? (
          <div
            style={{
              position: "absolute",
              left: "50%",
              top: frameH + 18,
              transform: "translateX(-50%)",
              background: theme.accent2,
              color: theme.bg,
              fontFamily: theme.bodyFont,
              fontWeight: 800,
              fontSize: 26,
              letterSpacing: 0.5,
              padding: "8px 24px",
              borderRadius: 999,
              whiteSpace: "nowrap",
              boxShadow: "0 8px 20px rgba(0,0,0,0.5)",
            }}
          >
            {label}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
