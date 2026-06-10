import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate, Easing, staticFile } from "remotion";
import { Theme } from "../theme";
import { popIn } from "../anim";

// Centered archival photo with a thin white border (~10px) + soft drop shadow. Defaults
// to black-and-white (grayscale + slight contrast) and a slow ken-burns push
// (scale 1.04 -> 1.10). `full` makes it large (~70% width), otherwise medium. An optional
// grey italic caption sits centered beneath. Fades + scales in; theme.panel placeholder
// when no imgSrc. Whole thing fades out near the end.
export const ArchivalPhoto: React.FC<{
  imgSrc?: string;
  caption?: string;
  bw?: boolean;
  full?: boolean;
  theme: Theme;
  durationInFrames: number;
}> = ({ imgSrc, caption, bw = true, full = false, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const outAt = durationInFrames - 12;

  // Fade + slight scale-up entrance, fade-out exit.
  const pop = popIn(frame, fps, { delay: 0, from: 0.94, outAt, outDur: 12 });

  // Slow ken-burns push across the whole shot.
  const kb = interpolate(frame, [0, durationInFrames], [1.04, 1.1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.ease),
  });

  const border = 10;
  const photoW = full ? 1344 : 880; // ~70% vs ~46% of 1920
  const photoH = full ? 756 : 560;
  const imgFilter = bw ? "grayscale(1) contrast(1.05)" : undefined;

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 24,
        }}
      >
        <div
          style={{
            opacity: pop.opacity,
            transform: pop.transform,
            background: "#FFFFFF",
            padding: border,
            boxShadow: "0 30px 80px rgba(0,0,0,0.6)",
          }}
        >
          <div
            style={{
              position: "relative",
              width: photoW,
              height: photoH,
              overflow: "hidden",
              background: theme.panel,
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
                  display: "block",
                  transform: `scale(${kb})`,
                  filter: imgFilter,
                }}
              />
            ) : (
              <div
                style={{
                  width: "100%",
                  height: "100%",
                  transform: `scale(${kb})`,
                  filter: imgFilter,
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
                PHOTO
              </div>
            )}
          </div>
        </div>

        {caption ? (
          <div
            style={{
              opacity: pop.opacity,
              fontFamily: theme.bodyFont,
              fontStyle: "italic",
              fontWeight: 400,
              fontSize: 28,
              lineHeight: 1.3,
              color: theme.textMute,
              textAlign: "center",
              maxWidth: photoW,
            }}
          >
            {caption}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
