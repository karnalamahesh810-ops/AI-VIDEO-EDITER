import React from "react";
import {
  AbsoluteFill,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  Easing,
  staticFile,
} from "remotion";
import { Theme } from "../theme";
import { slideIn } from "../anim";

const W = 1920;
const H = 1080;

// Photo carousel: dark backdrop with a faint receding perspective grid, and 1-2 framed
// photo panels (thick cobalt border + drop shadow) that slide in horizontally, staggered.
// Each image gets a gentle internal ken-burns push. Optional accent2 "#n" pill at the
// bottom edge of the lead panel. Whole scene fades out near the end.
export const PhotoCarousel: React.FC<{
  items: { src?: string; label?: string }[];
  number?: number;
  fullBg?: boolean;
  theme: Theme;
  durationInFrames: number;
}> = ({ items, number, fullBg = false, theme, durationInFrames }) => {
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

  // Show at most two panels.
  const panels = items.slice(0, 2);
  const n = Math.max(1, panels.length);

  // Panel geometry: one centered large panel, or two side-by-side.
  const gap = 70;
  const panelW = n === 1 ? 1180 : 820;
  const panelH = n === 1 ? 760 : 760;

  return (
    <AbsoluteFill style={{ background: theme.bg, opacity: rootOpacity }}>
      {/* Faint receding perspective grid (floor lines + verticals to a vanishing point). */}
      <AbsoluteFill style={{ opacity: fullBg ? 0.5 : 1 }}>
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" height="100%" style={{ display: "block" }}>
          {/* Vanishing point near horizon. */}
          {(() => {
            const vpX = W / 2;
            const vpY = H * 0.42;
            const horizonY = H * 0.52;
            // Receding floor lines: 9 horizontals compressing toward the horizon.
            const floors = Array.from({ length: 9 }, (_, i) => {
              const t = i / 8; // 0..1
              // Ease so lines bunch near the horizon.
              const y = horizonY + (H - horizonY) * (t * t);
              return (
                <line
                  key={`f${i}`}
                  x1={0}
                  y1={y}
                  x2={W}
                  y2={y}
                  stroke={theme.textMute}
                  strokeWidth={1.5}
                  opacity={0.1 * (0.4 + 0.6 * t)}
                />
              );
            });
            // Radial verticals fanning from the vanishing point down to the bottom edge.
            const rays = Array.from({ length: 17 }, (_, i) => {
              const x = (i / 16) * W;
              return (
                <line
                  key={`r${i}`}
                  x1={vpX}
                  y1={vpY}
                  x2={x}
                  y2={H}
                  stroke={theme.textMute}
                  strokeWidth={1.5}
                  opacity={0.08}
                />
              );
            });
            return (
              <>
                {floors}
                {rays}
              </>
            );
          })()}
        </svg>
      </AbsoluteFill>

      {/* Photo panels row, centered. */}
      <AbsoluteFill
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "center",
          gap,
        }}
      >
        {panels.map((it, i) => {
          // Stagger the slide-in; alternate entry side for the carousel feel.
          const side: "left" | "right" = i % 2 === 0 ? "left" : "right";
          const slide = slideIn(frame, fps, {
            side,
            delay: i * 8,
            dist: 220,
            outAt,
            outDur: 10,
          });
          // Gentle internal ken-burns push, offset per panel.
          const kb = interpolate(
            frame,
            [0, durationInFrames],
            [1.06, 1.16],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.inOut(Easing.ease) }
          );
          const isLead = i === 0;
          return (
            <div
              key={i}
              style={{
                position: "relative",
                width: panelW,
                height: panelH,
                borderRadius: 22,
                border: `6px solid ${theme.accent2}`,
                background: theme.panel,
                boxShadow: "0 26px 70px rgba(0,0,0,0.55)",
                overflow: "hidden",
                opacity: slide.opacity,
                transform: slide.transform,
              }}
            >
              {/* Image (or placeholder) with internal ken-burns. */}
              <div
                style={{
                  position: "absolute",
                  inset: 0,
                  transform: `scale(${kb})`,
                  transformOrigin: "center center",
                }}
              >
                {it.src ? (
                  <img
                    src={staticFile(it.src)}
                    alt=""
                    style={{
                      width: "100%",
                      height: "100%",
                      objectFit: "cover",
                      display: "block",
                    }}
                  />
                ) : (
                  <div
                    style={{
                      width: "100%",
                      height: "100%",
                      background: `linear-gradient(135deg, ${theme.panel} 0%, ${theme.bg} 100%)`,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: theme.textMute,
                      fontFamily: theme.bodyFont,
                      fontWeight: 700,
                      fontSize: 30,
                      letterSpacing: 1,
                    }}
                  >
                    {it.label ?? "PHOTO"}
                  </div>
                )}
              </div>

              {/* Optional caption strip for labelled images. */}
              {it.label && it.src ? (
                <div
                  style={{
                    position: "absolute",
                    left: 0,
                    right: 0,
                    bottom: 0,
                    padding: "16px 22px",
                    background: "linear-gradient(0deg, rgba(0,0,0,0.78), rgba(0,0,0,0))",
                    color: theme.text,
                    fontFamily: theme.bodyFont,
                    fontWeight: 700,
                    fontSize: 26,
                  }}
                >
                  {it.label}
                </div>
              ) : null}

              {/* "#number" pill centered on the bottom edge of the lead panel. */}
              {isLead && number != null ? (
                <div
                  style={{
                    position: "absolute",
                    left: "50%",
                    bottom: -22,
                    transform: "translateX(-50%)",
                    background: theme.accent2,
                    color: "#fff",
                    fontFamily: theme.headerFont,
                    fontWeight: 700,
                    fontSize: 28,
                    letterSpacing: 1,
                    padding: "8px 22px",
                    borderRadius: 999,
                    boxShadow: "0 8px 22px rgba(0,0,0,0.5)",
                  }}
                >
                  #{number}
                </div>
              ) : null}
            </div>
          );
        })}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
