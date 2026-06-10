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

// Migration map: full-frame desaturated map (image or a STYLIZED light-grey landmass
// placeholder over theme.bg with a faint grid), and one or more thick orange curved
// arrows that draw on via stroke-dashoffset, staggered ~12 frames apart, each capped
// with an arrowhead. Slow ken-burns push. Optional bold white label bottom-left.
export const MigrationMap: React.FC<{
  mapSrc?: string;
  arrows?: { fromX: number; fromY: number; toX: number; toY: number }[];
  label?: string;
  fullBg?: boolean;
  theme: Theme;
  durationInFrames: number;
}> = ({ mapSrc, arrows = [], label, fullBg = false, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const outAt = durationInFrames - 12;

  const ARROW_COLOR = "#F6921E";

  // Ken-burns push across the whole clip.
  const kb = interpolate(frame, [0, durationInFrames], [1.04, 1.12], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.ease),
  });

  const fade = interpolate(frame, [0, 10], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const fadeOut = interpolate(frame, [outAt, outAt + 12], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const rootOpacity = fade * fadeOut;

  // Arrows fade out a touch before the root so the heads don't linger.
  const arrowsOut = interpolate(frame, [outAt, outAt + 10], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const labelA = fadeRise(frame, { delay: 14, dur: 14, dist: 18, outAt, outDur: 10 });

  const ARROW_START = 14;
  const ARROW_DUR = 40;
  const ARROW_STEP = 12;

  return (
    <AbsoluteFill style={{ background: theme.bg, opacity: rootOpacity }}>
      {/* Map layer (image or stylized placeholder), ken-burns. */}
      <AbsoluteFill style={{ transform: `scale(${kb})`, transformOrigin: "center center" }}>
        {mapSrc ? (
          <img
            src={staticFile(mapSrc)}
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
              filter: "grayscale(0.85) brightness(1.02) contrast(0.96)",
            }}
            alt=""
          />
        ) : (
          <svg viewBox={`0 0 ${W} ${H}`} width="100%" height="100%" style={{ display: "block", opacity: fullBg ? 0.85 : 1 }}>
            <defs>
              <radialGradient id="mm-blob" cx="50%" cy="48%" r="70%">
                <stop offset="0%" stopColor="#E2E4E7" />
                <stop offset="65%" stopColor="#CED2D7" />
                <stop offset="100%" stopColor="#B9BEC4" />
              </radialGradient>
            </defs>
            {/* Faint grid graticule under the landmass. */}
            {Array.from({ length: 13 }, (_, i) => (
              <line
                key={`v${i}`}
                x1={(i / 12) * W}
                y1={0}
                x2={(i / 12) * W}
                y2={H}
                stroke="#FFFFFF"
                strokeWidth={1}
                opacity={0.05}
              />
            ))}
            {Array.from({ length: 8 }, (_, i) => (
              <line
                key={`h${i}`}
                x1={0}
                y1={(i / 7) * H}
                x2={W}
                y2={(i / 7) * H}
                stroke="#FFFFFF"
                strokeWidth={1}
                opacity={0.05}
              />
            ))}
            {/* Soft rounded landmass blob: a big organic rounded path plus a couple of
                satellite ellipses for an island/peninsula feel. NOT an accurate outline. */}
            <g style={{ filter: "drop-shadow(0 18px 40px rgba(0,0,0,0.35))" }}>
              <path
                d={
                  "M 360 470 " +
                  "C 300 360 470 250 640 270 " +
                  "C 760 284 880 220 1040 250 " +
                  "C 1230 286 1430 250 1540 360 " +
                  "C 1640 460 1560 600 1430 660 " +
                  "C 1320 712 1240 700 1120 740 " +
                  "C 980 788 900 760 760 770 " +
                  "C 600 782 440 760 380 640 " +
                  "C 348 576 372 520 360 470 Z"
                }
                fill="url(#mm-blob)"
              />
              <ellipse cx={1610} cy={760} rx={120} ry={70} fill="url(#mm-blob)" opacity={0.95} />
              <ellipse cx={300} cy={730} rx={95} ry={58} fill="url(#mm-blob)" opacity={0.95} />
            </g>
          </svg>
        )}
      </AbsoluteFill>

      {/* Overlay: orange curved arrows (screen space, unscaled). */}
      <AbsoluteFill>
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" height="100%" style={{ display: "block", overflow: "visible" }}>
          <defs>
            {arrows.map((_, i) => (
              <marker
                key={`mk${i}`}
                id={`mm-head-${i}`}
                viewBox="0 0 10 10"
                refX={7}
                refY={5}
                markerWidth={6}
                markerHeight={6}
                orient="auto-start-reverse"
                markerUnits="strokeWidth"
              >
                <path d="M 0 0 L 10 5 L 0 10 L 3 5 Z" fill={ARROW_COLOR} />
              </marker>
            ))}
          </defs>
          {arrows.map((a, i) => {
            const fx = a.fromX * W;
            const fy = a.fromY * H;
            const tx = a.toX * W;
            const ty = a.toY * H;

            // Quadratic control point bowing perpendicular to the chord (upward bow).
            const mx = (fx + tx) / 2;
            const my = (fy + ty) / 2;
            const dx = tx - fx;
            const dy = ty - fy;
            const dist = Math.hypot(dx, dy) || 1;
            const bow = Math.max(70, dist * 0.26);
            // Perpendicular (rotate the unit chord -90deg) pushed "up" on screen.
            let nx = -dy / dist;
            let ny = dx / dist;
            if (ny > 0) {
              nx = -nx;
              ny = -ny;
            }
            const cx = mx + nx * bow;
            const cy = my + ny * bow;
            const arcPath = `M ${fx} ${fy} Q ${cx} ${cy} ${tx} ${ty}`;

            // Quadratic bezier length approximation (chord + control-leg average).
            const legs = Math.hypot(cx - fx, cy - fy) + Math.hypot(tx - cx, ty - cy);
            const chord = dist;
            const arcLen = (legs + chord) / 2;

            const draw = drawOn(frame, { delay: ARROW_START + i * ARROW_STEP, dur: ARROW_DUR });
            const done = frame >= ARROW_START + i * ARROW_STEP + ARROW_DUR;

            return (
              <g key={`ar${i}`} opacity={arrowsOut}>
                {/* Origin dot. */}
                <circle
                  cx={fx}
                  cy={fy}
                  r={9}
                  fill={ARROW_COLOR}
                  stroke="#FFFFFF"
                  strokeWidth={2.5}
                  opacity={draw > 0.02 ? 1 : 0}
                />
                {/* Curved arrow; arrowhead only once the line has essentially drawn. */}
                <path
                  d={arcPath}
                  fill="none"
                  stroke={ARROW_COLOR}
                  strokeWidth={7}
                  strokeLinecap="round"
                  strokeDasharray={arcLen}
                  strokeDashoffset={arcLen * (1 - draw)}
                  markerEnd={done ? `url(#mm-head-${i})` : undefined}
                  style={{ filter: "drop-shadow(0 2px 6px rgba(0,0,0,.45))" }}
                />
              </g>
            );
          })}
        </svg>
      </AbsoluteFill>

      {/* Optional bottom-left bold white label. */}
      {label ? (
        <div
          style={{
            position: "absolute",
            left: "6%",
            bottom: "8%",
            opacity: labelA.opacity,
            transform: labelA.transform,
            fontFamily: theme.bodyFont,
            fontWeight: 800,
            fontSize: 58,
            color: theme.text,
            letterSpacing: 0.3,
            textShadow: "0 2px 18px rgba(0,0,0,.6), 0 0 28px rgba(0,0,0,.45)",
            maxWidth: "70%",
          }}
        >
          {label}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
