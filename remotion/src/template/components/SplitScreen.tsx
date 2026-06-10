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

// Split screen: two equal half-frame panels. The left panel slides in from the left and
// the right panel from the right, meeting at center. Each shows its image (or a theme.panel
// placeholder with its label) under a gentle internal ken-burns push. A thin white divider
// runs down the middle (default on). Bold white labels sit centered near the bottom of each
// half. Whole scene fades out near the end.
export const SplitScreen: React.FC<{
  left: { src?: string; label?: string };
  right: { src?: string; label?: string };
  divider?: boolean;
  theme: Theme;
  durationInFrames: number;
}> = ({ left, right, divider = true, theme, durationInFrames }) => {
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

  // Each panel slides in from its outer edge, meeting at the center seam.
  const leftSlide = slideIn(frame, fps, { side: "left", delay: 0, dist: W / 2, outAt, outDur: 10 });
  const rightSlide = slideIn(frame, fps, { side: "right", delay: 0, dist: W / 2, outAt, outDur: 10 });

  // Divider draws down once both panels have essentially met.
  const dividerH = interpolate(frame, [16, 30], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  const Half: React.FC<{
    item: { src?: string; label?: string };
    slide: { opacity: number; transform: string };
    kbFrom: number;
    kbTo: number;
    originX: "left" | "right";
  }> = ({ item, slide, kbFrom, kbTo, originX }) => {
    // Gentle internal ken-burns push; bias the origin toward the seam for a converging feel.
    const kb = interpolate(frame, [0, durationInFrames], [kbFrom, kbTo], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.inOut(Easing.ease),
    });
    return (
      <div
        style={{
          position: "relative",
          width: W / 2,
          height: H,
          overflow: "hidden",
          background: theme.panel,
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
            transformOrigin: `${originX} center`,
          }}
        >
          {item.src ? (
            <img
              src={staticFile(item.src)}
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
              {item.label ?? "PHOTO"}
            </div>
          )}
        </div>

        {/* Bottom gradient scrim so the label stays legible over any image. */}
        {item.label ? (
          <div
            style={{
              position: "absolute",
              left: 0,
              right: 0,
              bottom: 0,
              height: 220,
              background: "linear-gradient(0deg, rgba(0,0,0,0.72), rgba(0,0,0,0))",
              pointerEvents: "none",
            }}
          />
        ) : null}

        {/* Bold white label centered near the bottom of the half. */}
        {item.label ? (
          <div
            style={{
              position: "absolute",
              left: 0,
              right: 0,
              bottom: 70,
              textAlign: "center",
              padding: "0 40px",
              fontFamily: theme.bodyFont,
              fontWeight: 800,
              fontSize: 48,
              color: theme.text,
              letterSpacing: 0.4,
              textShadow: "0 2px 16px rgba(0,0,0,.7)",
            }}
          >
            {item.label}
          </div>
        ) : null}
      </div>
    );
  };

  return (
    <AbsoluteFill style={{ background: theme.bg, opacity: rootOpacity }}>
      <AbsoluteFill style={{ display: "flex", flexDirection: "row" }}>
        <Half item={left} slide={leftSlide} kbFrom={1.06} kbTo={1.14} originX="right" />
        <Half item={right} slide={rightSlide} kbFrom={1.06} kbTo={1.14} originX="left" />
      </AbsoluteFill>

      {/* Thin white divider down the middle. */}
      {divider ? (
        <div
          style={{
            position: "absolute",
            left: W / 2 - 2,
            top: `${(1 - dividerH) * 50}%`,
            width: 4,
            height: `${dividerH * 100}%`,
            background: "#FFFFFF",
            boxShadow: "0 0 18px rgba(0,0,0,0.6)",
            opacity: 0.95,
          }}
        />
      ) : null}
    </AbsoluteFill>
  );
};
