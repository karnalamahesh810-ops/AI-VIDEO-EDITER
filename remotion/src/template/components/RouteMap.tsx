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
import { popIn, drawOn } from "../anim";

const W = 1920;
const H = 1080;

// Route map: desaturated relief (image or placeholder) with slow ken-burns, two red
// pins, and a downward-bowing red arc that draws on connecting from -> to. Pill
// labels pop at each end (origin first, destination when the arc completes).
export const RouteMap: React.FC<{
  mapSrc?: string;
  from: { x: number; y: number; label: string };
  to: { x: number; y: number; label: string };
  theme: Theme;
  durationInFrames: number;
}> = ({ mapSrc, from, to, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const outAt = durationInFrames - 12;

  // Absolute frame coords from 0..1 fractions.
  const fx = from.x * W;
  const fy = from.y * H;
  const tx = to.x * W;
  const ty = to.y * H;

  // Quadratic control point bowing downward (below the chord midpoint).
  const mx = (fx + tx) / 2;
  const my = (fy + ty) / 2;
  const dist = Math.hypot(tx - fx, ty - fy);
  const cx = mx;
  const cy = my + Math.max(80, dist * 0.32);
  const arcPath = `M ${fx} ${fy} Q ${cx} ${cy} ${tx} ${ty}`;
  // Quadratic bezier length approximation (chord + control-leg average).
  const legs = Math.hypot(cx - fx, cy - fy) + Math.hypot(tx - cx, ty - cy);
  const chord = Math.hypot(tx - fx, ty - fy);
  const arcLen = (legs + chord) / 2;

  const arcDur = 100;
  const arcStart = 14;
  const draw = drawOn(frame, { delay: arcStart, dur: arcDur });

  // Ken-burns scale 1.05 -> 1.12 across the clip.
  const kb = interpolate(frame, [0, durationInFrames], [1.05, 1.12], {
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

  // Origin pill pops at arc start; destination pill when the arc completes.
  const fromPop = popIn(frame, fps, { delay: arcStart, from: 0.7, outAt, outDur: 10 });
  const toPop = popIn(frame, fps, { delay: arcStart + arcDur, from: 0.7, outAt, outDur: 10 });

  const pinR = 11;
  const Pill: React.FC<{
    x: number;
    y: number;
    label: string;
    pop: { opacity: number; transform: string };
  }> = ({ x, y, label, pop }) => {
    const padX = 22;
    const padY = 12;
    const fontSize = 28;
    const wEst = label.length * fontSize * 0.6 + padX * 2;
    const hEst = fontSize + padY * 2;
    // Place the pill above its pin.
    const px = x - wEst / 2;
    const py = y - pinR - 18 - hEst;
    return (
      <g
        style={{
          opacity: pop.opacity,
          transform: `${pop.transform}`,
          transformBox: "fill-box",
          transformOrigin: "center bottom",
        }}
      >
        <rect x={px} y={py} width={wEst} height={hEst} rx={10} fill="#0E0E0E" opacity={0.9} />
        <text
          x={x}
          y={py + hEst / 2}
          fill="#FFFFFF"
          fontFamily={theme.bodyFont}
          fontSize={fontSize}
          fontWeight={700}
          textAnchor="middle"
          dominantBaseline="central"
        >
          {label}
        </text>
      </g>
    );
  };

  return (
    <AbsoluteFill style={{ background: theme.bg, opacity: rootOpacity }}>
      {/* Map layer (image or placeholder), ken-burns */}
      <AbsoluteFill
        style={{
          transform: `scale(${kb})`,
          transformOrigin: "center center",
        }}
      >
        {mapSrc ? (
          <img
            src={staticFile(mapSrc)}
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
              filter: "grayscale(0.3) brightness(0.9)",
            }}
            alt=""
          />
        ) : (
          <svg viewBox={`0 0 ${W} ${H}`} width="100%" height="100%" style={{ display: "block" }}>
            <defs>
              <linearGradient id="rm-relief" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stopColor="#3A3F45" />
                <stop offset="50%" stopColor="#2C3034" />
                <stop offset="100%" stopColor="#212427" />
              </linearGradient>
            </defs>
            <rect x={0} y={0} width={W} height={H} fill="url(#rm-relief)" />
            {/* Faint grid graticule */}
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
          </svg>
        )}
      </AbsoluteFill>

      {/* Overlay: arc + pins + pills (not scaled, sits in screen space) */}
      <AbsoluteFill>
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" height="100%" style={{ display: "block", overflow: "visible" }}>
          {/* Curved route arc, draws on */}
          <path
            d={arcPath}
            fill="none"
            stroke={theme.alert}
            strokeWidth={5}
            strokeLinecap="round"
            strokeDasharray={arcLen}
            strokeDashoffset={arcLen * (1 - draw)}
            style={{ filter: "drop-shadow(0 2px 6px rgba(0,0,0,.5))" }}
          />

          {/* Pins */}
          <circle cx={fx} cy={fy} r={pinR} fill={theme.alert} stroke="#FFFFFF" strokeWidth={3} opacity={fromPop.opacity} />
          <circle cx={tx} cy={ty} r={pinR} fill={theme.alert} stroke="#FFFFFF" strokeWidth={3} opacity={toPop.opacity} />

          {/* Pills */}
          <Pill x={fx} y={fy} label={from.label} pop={fromPop} />
          <Pill x={tx} y={ty} label={to.label} pop={toPop} />
        </svg>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
