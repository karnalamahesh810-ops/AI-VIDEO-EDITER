import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate, Easing, staticFile } from "remotion";
import { Theme } from "../theme";
import { popIn, typewriter } from "../anim";

// Tilted white polaroid frame (thick ~24px border + soft drop shadow) on a dark backdrop,
// holding an image (or a theme.panel placeholder). A black caption bar overlays the lower
// portion with caption text that types in. The frame drops/scales in and its rotation
// settles to `rotate`. Fades out near the end.
export const PolaroidFrame: React.FC<{
  imgSrc?: string;
  caption: string;
  rotate?: number;
  theme: Theme;
  durationInFrames: number;
}> = ({ imgSrc, caption, rotate = -3, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const outAt = durationInFrames - 12;

  const fadeOut = interpolate(frame, [outAt, outAt + 12], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Pop the frame in (scale + fade), and settle the tilt from upright toward `rotate`.
  const pop = popIn(frame, fps, { delay: 0, from: 0.78, outAt, outDur: 12 });
  const rot = interpolate(frame, [0, 20], [rotate * 0.15 - 6, rotate], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  // Caption types in after the frame has dropped into place.
  const tw = typewriter(frame, fps, caption, { delay: 16, cps: 34, cursor: true });

  const border = 24;
  const photoW = 720;
  const photoH = 720;

  return (
    <AbsoluteFill
      style={{
        background: theme.bg,
        opacity: fadeOut,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          transform: `${pop.transform} rotate(${rot}deg)`,
          opacity: pop.opacity,
        }}
      >
        <div
          style={{
            position: "relative",
            background: "#FFFFFF",
            padding: border,
            paddingBottom: border,
            boxShadow: "0 36px 90px rgba(0,0,0,0.6)",
            borderRadius: 4,
          }}
        >
          {/* Photo (or placeholder). */}
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
                style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
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
                PHOTO
              </div>
            )}

            {/* Black caption bar over the lower portion, with typed caption text. */}
            <div
              style={{
                position: "absolute",
                left: 0,
                right: 0,
                bottom: 0,
                padding: "22px 26px",
                background: "rgba(0,0,0,0.82)",
                color: "#FFFFFF",
                fontFamily: theme.bodyFont,
                fontWeight: 700,
                fontSize: 34,
                lineHeight: 1.25,
              }}
            >
              {tw.text}
              {tw.cursor ? <span style={{ fontWeight: 400 }}>|</span> : null}
            </div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
