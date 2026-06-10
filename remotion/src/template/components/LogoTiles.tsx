import React from "react";
import {
  AbsoluteFill,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  staticFile,
} from "remotion";
import { Theme } from "../theme";
import { popIn, fadeRise } from "../anim";

// 2-3 rounded square logo tiles centered side-by-side over a dimmed/transparent backdrop.
// Each tile is a white (or tile.color) rounded rect holding the logo image (or a colored
// first-letter placeholder), with a white sans label beneath. Tiles pop in sequentially;
// labels fade up under them. Whole group fades out near the end.
export const LogoTiles: React.FC<{
  tiles: { label: string; src?: string; color?: string }[];
  theme: Theme;
  durationInFrames: number;
}> = ({ tiles, theme, durationInFrames }) => {
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

  // Show at most three tiles.
  const shown = tiles.slice(0, 3);
  const tileSize = shown.length >= 3 ? 320 : 360;
  const gap = 80;

  return (
    <AbsoluteFill style={{ opacity: rootOpacity }}>
      {/* Dimmed backdrop so tiles read over whatever sits behind the scene. */}
      <AbsoluteFill style={{ background: "rgba(0,0,0,0.45)" }} />

      <AbsoluteFill
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "center",
          gap,
        }}
      >
        {shown.map((t, i) => {
          const pop = popIn(frame, fps, { delay: i * 6, from: 0.6, outAt, outDur: 10 });
          const lbl = fadeRise(frame, {
            delay: i * 6 + 8,
            dur: 12,
            dist: 14,
            outAt,
            outDur: 10,
          });
          const tileColor = t.color ?? "#FFFFFF";
          const letter = (t.label || "?").trim().charAt(0).toUpperCase();
          return (
            <div
              key={i}
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
              }}
            >
              {/* Tile. */}
              <div
                style={{
                  width: tileSize,
                  height: tileSize,
                  borderRadius: 44,
                  background: tileColor,
                  boxShadow: "0 24px 60px rgba(0,0,0,0.5)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  overflow: "hidden",
                  opacity: pop.opacity,
                  transform: pop.transform,
                }}
              >
                {t.src ? (
                  <img
                    src={staticFile(t.src)}
                    alt=""
                    style={{
                      width: "70%",
                      height: "70%",
                      objectFit: "contain",
                      display: "block",
                    }}
                  />
                ) : (
                  <div
                    style={{
                      width: "70%",
                      height: "70%",
                      borderRadius: 28,
                      background: t.color
                        ? "rgba(255,255,255,0.18)"
                        : theme.accent2,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: "#FFFFFF",
                      fontFamily: theme.headerFont,
                      fontWeight: 700,
                      fontSize: tileSize * 0.42,
                      lineHeight: 1,
                    }}
                  >
                    {letter}
                  </div>
                )}
              </div>

              {/* Label beneath. */}
              <div
                style={{
                  marginTop: 24,
                  opacity: lbl.opacity,
                  transform: lbl.transform,
                  fontFamily: theme.bodyFont,
                  fontWeight: 700,
                  fontSize: 34,
                  color: "#FFFFFF",
                  letterSpacing: 0.4,
                  textAlign: "center",
                  textShadow: "0 2px 14px rgba(0,0,0,0.6)",
                  maxWidth: tileSize + 60,
                }}
              >
                {t.label}
              </div>
            </div>
          );
        })}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
