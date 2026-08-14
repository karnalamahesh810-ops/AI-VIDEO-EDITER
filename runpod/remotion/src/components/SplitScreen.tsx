import React from "react";
import { AbsoluteFill, Img, OffthreadVideo, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { SceneMedia } from "../types";

/**
 * "Horizontal Split Screen Animation" — two visuals meet in the middle.
 *
 * Used for comparisons (before/after, two places, then/now). The halves slide
 * in from opposite edges and settle against a thin accent seam.
 */
export const SplitScreen: React.FC<{
  top: SceneMedia;
  bottom: SceneMedia;
  accent: string;
}> = ({ top, bottom, accent }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const t = interpolate(frame, [0, 18], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const offset = interpolate(t, [0, 1], [55, 0]);
  const fade = interpolate(
    frame,
    [0, 6, durationInFrames - 6, durationInFrames],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const half: React.CSSProperties = {
    position: "absolute",
    left: 0,
    width: "100%",
    height: "50%",
    overflow: "hidden",
  };
  const fill: React.CSSProperties = {
    width: "100%",
    height: "100%",
    objectFit: "cover",
    transform: "scale(1.08)",
  };

  const render = (m: SceneMedia) =>
    !m || !m.url ? (
      <div style={{ width: "100%", height: "100%", background: "#0b0b0d" }} />
    ) : m.type === "video" ? (
      <OffthreadVideo src={m.url} style={fill} muted />
    ) : (
      <Img src={m.url} style={fill} />
    );

  return (
    <AbsoluteFill style={{ backgroundColor: "#000", opacity: fade }}>
      <div style={{ ...half, top: 0, transform: `translateX(-${offset}%)` }}>
        {render(top)}
      </div>
      <div style={{ ...half, top: "50%", transform: `translateX(${offset}%)` }}>
        {render(bottom)}
      </div>
      <div
        style={{
          position: "absolute",
          top: "calc(50% - 2px)",
          left: 0,
          width: "100%",
          height: 4,
          background: accent,
          opacity: t,
          boxShadow: `0 0 24px ${accent}`,
        }}
      />
    </AbsoluteFill>
  );
};
