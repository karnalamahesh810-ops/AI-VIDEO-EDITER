import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate, Easing } from "remotion";
import { Theme } from "../theme";
import { fadeRise, popIn } from "../anim";

const W = 1920;
const H = 1080;

// Spotlight callout: darkens the WHOLE frame with a semi-opaque black overlay (~0.62)
// EXCEPT a transparent hole at (x,y) that reveals the b-roll beneath — a circle (radius r)
// or a rounded rect (~2:1 around r). Implemented with an SVG <mask>: a full white rect
// minus a black shape at the hole, applied to the dark <rect>. The hole eases in (r grows
// from 0). Optional label fades in just below/beside the spotlight after it opens.
export const SpotlightCallout: React.FC<{
  x: number;
  y: number;
  r: number;
  label?: string;
  shape?: "circle" | "rect";
  theme: Theme;
  durationInFrames: number;
}> = ({ x, y, r, label, shape = "circle", theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const outAt = durationInFrames - 12;

  // Absolute hole center from 0..1 fractions.
  const cx = x * W;
  const cy = y * H;

  // The overlay fades in; the hole eases open (scale of r from 0 -> 1).
  const fade = interpolate(frame, [0, 10], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const fadeOut = interpolate(frame, [outAt, outAt + 12], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const rootOpacity = fade * fadeOut;

  const open = interpolate(frame, [6, 24], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const rr = r * open;

  // Rounded-rect hole dims (~2:1 landscape window centered on the point).
  const rectW = rr * 2.2;
  const rectH = rr * 1.4;
  const rectRad = Math.min(28, rr * 0.35);

  const maskId = "spot-mask";

  // Label appears once the spotlight has essentially opened; sits just below the hole.
  const halfH = shape === "rect" ? rectH / 2 : rr;
  const labelTop = (cy + halfH + 28) / H;
  const lbl = fadeRise(frame, { delay: 24, dur: 12, dist: 14, outAt, outDur: 10 });
  // Slight pop so the label has a touch of life (matches sibling callouts).
  const lblPop = popIn(frame, fps, { delay: 24, from: 0.9, outAt, outDur: 10 });
  const lblScale = lblPop.transform.replace("scale(", "").replace(")", "");

  return (
    <AbsoluteFill style={{ pointerEvents: "none", opacity: rootOpacity }}>
      {/* Dark overlay with a transparent hole punched via mask. */}
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height="100%"
        style={{ display: "block" }}
      >
        <defs>
          <mask id={maskId} maskUnits="userSpaceOnUse" x={0} y={0} width={W} height={H}>
            {/* White = visible (darkened), black = hole (reveals b-roll). */}
            <rect x={0} y={0} width={W} height={H} fill="#FFFFFF" />
            {shape === "rect" ? (
              <rect
                x={cx - rectW / 2}
                y={cy - rectH / 2}
                width={rectW}
                height={rectH}
                rx={rectRad}
                ry={rectRad}
                fill="#000000"
              />
            ) : (
              <circle cx={cx} cy={cy} r={rr} fill="#000000" />
            )}
          </mask>
        </defs>
        <rect x={0} y={0} width={W} height={H} fill="#000000" opacity={0.62} mask={`url(#${maskId})`} />
        {/* Thin accent ring around the hole edge for a crisp "lens" feel. */}
        {shape === "rect" ? (
          <rect
            x={cx - rectW / 2}
            y={cy - rectH / 2}
            width={rectW}
            height={rectH}
            rx={rectRad}
            ry={rectRad}
            fill="none"
            stroke="#FFFFFF"
            strokeWidth={3}
            opacity={0.5 * open}
          />
        ) : (
          <circle
            cx={cx}
            cy={cy}
            r={rr}
            fill="none"
            stroke="#FFFFFF"
            strokeWidth={3}
            opacity={0.5 * open}
          />
        )}
      </svg>

      {/* Optional label just below the spotlight. */}
      {label ? (
        <div
          style={{
            position: "absolute",
            left: `${x * 100}%`,
            top: `${labelTop * 100}%`,
            transform: `translate(-50%, 0) scale(${lblScale})`,
            transformOrigin: "center top",
            opacity: lbl.opacity,
            fontFamily: theme.bodyFont,
            fontWeight: 700,
            fontSize: 38,
            color: theme.text,
            letterSpacing: 0.3,
            textAlign: "center",
            maxWidth: "60%",
            textShadow: "0 2px 18px rgba(0,0,0,.7), 0 0 28px rgba(0,0,0,.5)",
          }}
        >
          {label}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
