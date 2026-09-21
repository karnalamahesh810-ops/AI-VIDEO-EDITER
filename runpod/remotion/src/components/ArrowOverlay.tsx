import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import { PANEL_BG, SANS, growth, useOverlayAnim, useOverlaySafeStyle, useScale } from "./layout";
import type { Overlay } from "../types";

/**
 * A hand-drawn-feeling arrow that sweeps in and points at a label.
 *
 * The stroke draws itself with a dash-offset animation rather than fading in,
 * which is what makes it read as annotation rather than as a graphic that was
 * always there.
 */
export const ArrowOverlay: React.FC<{ overlay: Overlay; accent: string }> = ({
  overlay,
  accent,
}) => {
  const { frame, enter, opacity, durationInFrames } = useOverlayAnim(14, 10);
  const s = useScale();
  const safe = useOverlaySafeStyle();

  const w = s(700);
  const h = s(260);
  // A single curve sweeping down and to the right, finishing almost
  // horizontal so the head points AT the label rather than past it.
  const tipX = s(330);
  const tipY = s(170);
  const d = `M ${s(30)} ${s(30)} Q ${s(150)} ${s(210)} ${tipX} ${tipY}`;
  const length = s(460);
  // The curve leaves its control point heading right and slightly up; the
  // head is rotated to match so it sits flush on the end of the stroke.
  const HEAD_ANGLE = -12.5;
  const draw = growth(frame, Math.min(22, Math.floor(durationInFrames * 0.4)));
  const headIn = growth(frame - 16, 8);

  return (
    <AbsoluteFill
      style={{ ...safe, justifyContent: "center", alignItems: "center", opacity }}
    >
      <div style={{ position: "relative", width: w, height: h }}>
        <svg width={w} height={h} style={{ position: "absolute", inset: 0 }}>
          <path
            d={d}
            fill="none"
            stroke={accent}
            strokeWidth={s(9)}
            strokeLinecap="round"
            strokeDasharray={length}
            strokeDashoffset={length * (1 - draw)}
            style={{ filter: `drop-shadow(0 ${s(4)}px ${s(12)}px rgba(0,0,0,0.7))` }}
          />
          <polygon
            points={`${tipX},${tipY} ${tipX - s(40)},${tipY - s(21)} ${tipX - s(40)},${tipY + s(21)}`}
            fill={accent}
            opacity={headIn}
            // The scale is expressed as translate/scale/translate rather than
            // with a CSS transform-origin: Chrome applies transform-origin to
            // the SVG transform attribute too, which double-offsets the
            // rotate and leaves the head detached from the stroke.
            transform={
              `rotate(${HEAD_ANGLE} ${tipX} ${tipY}) ` +
              `translate(${tipX} ${tipY}) ` +
              `scale(${interpolate(headIn, [0, 1], [0.4, 1])}) ` +
              `translate(${-tipX} ${-tipY})`
            }
          />
        </svg>
        {overlay.text ? (
          <div
            style={{
              position: "absolute",
              left: tipX + s(24),
              top: tipY - s(38),
              background: PANEL_BG,
              borderRadius: s(12),
              padding: `${s(14)}px ${s(24)}px`,
              fontFamily: SANS,
              fontSize: s(38),
              fontWeight: 800,
              color: "#fff",
              whiteSpace: "nowrap",
              opacity: interpolate(enter, [0.4, 1], [0, 1], {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
              }),
            }}
          >
            {overlay.text}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
