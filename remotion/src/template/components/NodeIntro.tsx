import React from "react";
import {
  AbsoluteFill,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
} from "remotion";
import { Theme } from "../theme";
import { fadeRise, popIn, drawOn } from "../anim";

const W = 1920;
const H = 1080;

// Mind-map / flowchart intro on near-black: white curved bezier connectors that draw on
// (stroke-dashoffset), staggered, then glowing accent2 nodes that pop in with bold grey
// labels fading+rising beside each. Whole scene fades out near the end.
export const NodeIntro: React.FC<{
  nodes: { label: string; x: number; y: number }[];
  links: [number, number][];
  theme: Theme;
  durationInFrames: number;
}> = ({ nodes, links, theme, durationInFrames }) => {
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

  // Absolute pixel coords for each node.
  const px = (i: number) => nodes[i].x * W;
  const py = (i: number) => nodes[i].y * H;

  const linkStart = 6;
  const linkStep = 7;
  const linkDur = 26;
  const dotR = 22;

  // Nodes start popping after their first incoming link begins drawing.
  const nodeBase = linkStart + 10;

  return (
    <AbsoluteFill style={{ background: "#060810", opacity: rootOpacity }}>
      {/* Connectors layer (curved bezier paths drawing on). */}
      <AbsoluteFill>
        <svg
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          height="100%"
          style={{ display: "block", overflow: "visible" }}
        >
          {links.map(([a, b], i) => {
            const ax = px(a);
            const ay = py(a);
            const bx = px(b);
            const by = py(b);
            // Cubic bezier with control points pulled toward the midpoint horizontally
            // for a gentle S/arc curve.
            const mx = (ax + bx) / 2;
            const c1x = mx;
            const c1y = ay;
            const c2x = mx;
            const c2y = by;
            const d = `M ${ax} ${ay} C ${c1x} ${c1y} ${c2x} ${c2y} ${bx} ${by}`;
            // Path-length approximation (control-leg + chord average) for dasharray.
            const legs =
              Math.hypot(c1x - ax, c1y - ay) +
              Math.hypot(c2x - c1x, c2y - c1y) +
              Math.hypot(bx - c2x, by - c2y);
            const chord = Math.hypot(bx - ax, by - ay);
            const len = (legs + chord) / 2;
            const draw = drawOn(frame, { delay: linkStart + i * linkStep, dur: linkDur });
            return (
              <path
                key={i}
                d={d}
                fill="none"
                stroke="#FFFFFF"
                strokeWidth={3}
                strokeLinecap="round"
                opacity={0.85}
                strokeDasharray={len}
                strokeDashoffset={len * (1 - draw)}
              />
            );
          })}
        </svg>
      </AbsoluteFill>

      {/* Nodes layer: glowing dots + grey labels. */}
      {nodes.map((node, i) => {
        const x = node.x * W;
        const y = node.y * H;
        const pop = popIn(frame, fps, { delay: nodeBase + i * 5, from: 0.4, outAt, outDur: 10 });
        const lbl = fadeRise(frame, {
          delay: nodeBase + i * 5 + 6,
          dur: 12,
          dist: 14,
          outAt,
          outDur: 10,
        });
        // Place the label to the right of the dot, unless the node hugs the right edge.
        const labelLeft = node.x > 0.7;
        return (
          <div key={i} style={{ position: "absolute", left: x, top: y }}>
            {/* Glowing dot. */}
            <div
              style={{
                position: "absolute",
                left: -dotR / 2,
                top: -dotR / 2,
                width: dotR,
                height: dotR,
                borderRadius: "50%",
                background: theme.accent2,
                boxShadow: `0 0 18px 6px ${theme.accent2}AA, 0 0 40px 14px ${theme.accent2}55`,
                opacity: pop.opacity,
                transform: pop.transform,
              }}
            />
            {/* Bold grey label beside the dot. */}
            <div
              style={{
                position: "absolute",
                left: labelLeft ? undefined : dotR,
                right: labelLeft ? dotR : undefined,
                top: -16,
                whiteSpace: "nowrap",
                textAlign: labelLeft ? "right" : "left",
                transform: `translateX(${labelLeft ? "-100%" : "0"}) ${lbl.transform}`,
                opacity: lbl.opacity,
                fontFamily: theme.bodyFont,
                fontWeight: 800,
                fontSize: 32,
                color: theme.textMute,
                letterSpacing: 0.3,
                textShadow: "0 2px 12px rgba(0,0,0,0.6)",
              }}
            >
              {node.label}
            </div>
          </div>
        );
      })}
    </AbsoluteFill>
  );
};
