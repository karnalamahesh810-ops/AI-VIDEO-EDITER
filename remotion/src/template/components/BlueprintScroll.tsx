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
import { fadeRise, drawOn } from "../anim";

const W = 1920;
const H = 1080;

// Schematic/technical interstitial on white. With imgSrc: a black line-art image drifts
// slowly horizontally at slight scale. Without imgSrc: a generic side-profile airplane
// blueprint is drawn in inline SVG (thin black strokes) that animate on via
// stroke-dashoffset. Optional small dark caption bottom-left. Fades out near the end.
export const BlueprintScroll: React.FC<{
  imgSrc?: string;
  caption?: string;
  theme: Theme;
  durationInFrames: number;
}> = ({ imgSrc, caption, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  useVideoConfig();
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

  // Slow horizontal drift (used for image variant); a slight scale for parallax feel.
  const drift = interpolate(frame, [0, durationInFrames], [-60, 60], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.ease),
  });
  const imgScale = interpolate(frame, [0, durationInFrames], [1.04, 1.1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.ease),
  });

  const cap = fadeRise(frame, { delay: 16, dur: 12, dist: 12, outAt, outDur: 10 });

  // Stroke parameters for each wireframe segment (path d + estimated length).
  // Estimated lengths are rough perimeter approximations — only used for dasharray.
  const fuselageLen = 3200; // long ellipse perimeter
  const wingLen = 1100;
  const tailLen = 700;
  const detailLen = 900;

  const dFuselage = draw01(frame, 14, 40);
  const dWing = draw01(frame, 30, 34);
  const dTail = draw01(frame, 46, 30);
  const dDetail = draw01(frame, 58, 30);

  const stroke = "#111111";

  return (
    <AbsoluteFill style={{ background: "#FFFFFF", opacity: rootOpacity }}>
      {imgSrc ? (
        // Black line-art image drifting slowly.
        <AbsoluteFill
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            transform: `translateX(${drift}px) scale(${imgScale})`,
            transformOrigin: "center center",
          }}
        >
          <img
            src={staticFile(imgSrc)}
            alt=""
            style={{
              width: "92%",
              height: "82%",
              objectFit: "contain",
              display: "block",
            }}
          />
        </AbsoluteFill>
      ) : (
        // Inline airplane / blueprint wireframe, strokes drawing on.
        <AbsoluteFill>
          <svg
            viewBox={`0 0 ${W} ${H}`}
            width="100%"
            height="100%"
            style={{ display: "block", overflow: "visible" }}
          >
            {/* Faint blueprint graph paper grid. */}
            {Array.from({ length: 25 }, (_, i) => (
              <line
                key={`gv${i}`}
                x1={(i / 24) * W}
                y1={0}
                x2={(i / 24) * W}
                y2={H}
                stroke="#111111"
                strokeWidth={1}
                opacity={0.04}
              />
            ))}
            {Array.from({ length: 14 }, (_, i) => (
              <line
                key={`gh${i}`}
                x1={0}
                y1={(i / 13) * H}
                x2={W}
                y2={(i / 13) * H}
                stroke="#111111"
                strokeWidth={1}
                opacity={0.04}
              />
            ))}

            {/* Fuselage: a long side-profile ellipse, nose to the right. */}
            <ellipse
              cx={W / 2}
              cy={H / 2}
              rx={680}
              ry={120}
              fill="none"
              stroke={stroke}
              strokeWidth={2.5}
              strokeDasharray={fuselageLen}
              strokeDashoffset={fuselageLen * (1 - dFuselage)}
            />
            {/* Nose cone hint (tapered tip on the right). */}
            <path
              d={`M ${W / 2 + 680} ${H / 2} l 120 -20 l 0 40 z`}
              fill="none"
              stroke={stroke}
              strokeWidth={2.5}
              strokeDasharray={detailLen}
              strokeDashoffset={detailLen * (1 - dDetail)}
            />

            {/* Main wing (swept, projecting up-left from mid-fuselage). */}
            <path
              d={`M ${W / 2 - 120} ${H / 2} L ${W / 2 - 420} ${H / 2 - 230} L ${
                W / 2 - 250
              } ${H / 2 - 230} L ${W / 2 + 30} ${H / 2} Z`}
              fill="none"
              stroke={stroke}
              strokeWidth={2.5}
              strokeLinejoin="round"
              strokeDasharray={wingLen}
              strokeDashoffset={wingLen * (1 - dWing)}
            />

            {/* Vertical stabilizer (tail fin, left end up). */}
            <path
              d={`M ${W / 2 - 560} ${H / 2} L ${W / 2 - 640} ${H / 2 - 180} L ${
                W / 2 - 520
              } ${H / 2 - 180} L ${W / 2 - 440} ${H / 2} Z`}
              fill="none"
              stroke={stroke}
              strokeWidth={2.5}
              strokeLinejoin="round"
              strokeDasharray={tailLen}
              strokeDashoffset={tailLen * (1 - dTail)}
            />

            {/* Horizontal stabilizer (small tailplane, lower-left). */}
            <path
              d={`M ${W / 2 - 560} ${H / 2 + 30} L ${W / 2 - 700} ${H / 2 + 110} L ${
                W / 2 - 580
              } ${H / 2 + 110} L ${W / 2 - 470} ${H / 2 + 40} Z`}
              fill="none"
              stroke={stroke}
              strokeWidth={2.5}
              strokeLinejoin="round"
              strokeDasharray={tailLen}
              strokeDashoffset={tailLen * (1 - dTail)}
            />

            {/* Center reference line through the fuselage. */}
            <line
              x1={W / 2 - 680}
              y1={H / 2}
              x2={W / 2 + 800}
              y2={H / 2}
              stroke={stroke}
              strokeWidth={1}
              opacity={0.5}
              strokeDasharray={`8 10`}
              strokeDashoffset={1500 * (1 - dDetail)}
            />

            {/* A couple of cabin window dots along the fuselage. */}
            {Array.from({ length: 8 }, (_, i) => {
              const wx = W / 2 - 380 + i * 110;
              return (
                <circle
                  key={`win${i}`}
                  cx={wx}
                  cy={H / 2 - 30}
                  r={9}
                  fill="none"
                  stroke={stroke}
                  strokeWidth={2}
                  opacity={dDetail}
                />
              );
            })}
          </svg>
        </AbsoluteFill>
      )}

      {/* Optional caption bottom-left. */}
      {caption ? (
        <div
          style={{
            position: "absolute",
            left: 70,
            bottom: 64,
            opacity: cap.opacity,
            transform: cap.transform,
            fontFamily: theme.bodyFont,
            fontWeight: 700,
            fontSize: 30,
            color: "#1A1A1A",
            letterSpacing: 0.4,
          }}
        >
          {caption}
        </div>
      ) : null}
    </AbsoluteFill>
  );

  // Local draw helper bound to this frame (keeps the JSX above terse).
  function draw01(f: number, delay: number, dur: number) {
    return drawOn(f, { delay, dur });
  }
};
