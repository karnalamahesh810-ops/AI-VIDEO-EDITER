import React from "react";
import {
  AbsoluteFill,
  OffthreadVideo,
  Img,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  Easing,
} from "remotion";

// One scene's b-roll, full-frame, with a gentle Ken-Burns push (alternating in/out
// + varied focal origin so consecutive scenes don't feel static). Images animate too.
export const SceneClip: React.FC<{ src: string | null; type: string; index: number; loop?: boolean; playbackRate?: number }> = ({
  src,
  type,
  index,
  loop = false,
  playbackRate = 1,
}) => {
  // No Ken-Burns zoom: per-clip zoom reset the scale at every cut (the "jump" you saw),
  // and the b-roll already has its own motion. Full-frame + static = smooth, clean cuts.
  void index;
  const style: React.CSSProperties = {
    width: "100%",
    height: "100%",
    objectFit: "cover",
  };

  return (
    <AbsoluteFill style={{ backgroundColor: "#0a0a0a", overflow: "hidden" }}>
      {src && type === "video" ? (
        <OffthreadVideo src={staticFile(src)} muted loop={loop} playbackRate={playbackRate} style={style} />
      ) : src && type === "image" ? (
        <Img src={staticFile(src)} style={style} />
      ) : (
        <AbsoluteFill style={{ background: "linear-gradient(135deg,#15171c,#2b2f38)" }} />
      )}
    </AbsoluteFill>
  );
};
