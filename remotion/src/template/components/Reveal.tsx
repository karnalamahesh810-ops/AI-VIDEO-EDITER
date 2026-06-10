import React from "react";
import { useCurrentFrame, useVideoConfig, interpolate, spring, Easing } from "remotion";

// Directional entrance/exit animation menu. Wrap ANY element to make it animate in
// (and out). Pick `dir`:
//   right       -> starts off-screen right, moves LEFT (right-to-left)   [#1]
//   left        -> from the left (left-to-right)                          [#2]
//   up          -> rises from below                                       [#3]
//   down        -> drops from above                                       [#4]
//   zoom        -> scales up into place                                   [#5]
//   zoom-out    -> starts big, settles down                              [#6]
//   pop         -> bouncy spring scale                                    [#7]
//   blur        -> blur + fade in                                         [#8]
//   flip        -> 3D Y-axis flip                                         [#9]
//   wipe-right  -> clip reveal L->R                                       [#10]
//   wipe-left   -> clip reveal R->L                                       [#11]
//   wipe-up     -> clip reveal bottom->top                                [#12]
//   wipe-down   -> clip reveal top->bottom                                [#13]
//   fade        -> opacity only                                          [#14]
export type RevealDir =
  | "right" | "left" | "up" | "down"
  | "zoom" | "zoom-out" | "pop" | "blur" | "flip"
  | "wipe-right" | "wipe-left" | "wipe-up" | "wipe-down"
  | "fade";

export const REVEAL_DIRS: RevealDir[] = [
  "right", "left", "up", "down", "zoom", "zoom-out", "pop", "blur", "flip",
  "wipe-right", "wipe-left", "wipe-up", "wipe-down", "fade",
];

export const Reveal: React.FC<{
  dir?: RevealDir;
  delay?: number;
  durationInFrames: number;
  distance?: number;
  exit?: boolean;
  style?: React.CSSProperties;
  children: React.ReactNode;
}> = ({ dir = "right", delay = 0, durationInFrames, distance = 140, exit = true, style, children }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const settle = spring({ frame: frame - delay, fps, config: { damping: 18, mass: 0.8 }, durationInFrames: 18 });
  const bounce = spring({ frame: frame - delay, fps, config: { damping: 9, mass: 0.8 }, durationInFrames: 22 });

  const outAt = durationInFrames - 12;
  const out = exit ? interpolate(frame, [outAt, outAt + 10], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) : 0;
  const off = (1 - settle) + out; // 0 at rest; >0 while entering/exiting

  let tx = 0, ty = 0, scale = 1, rotY = 0, blur = 0;
  let clip: string | undefined;
  let fade = interpolate(frame, [delay, delay + 6], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  switch (dir) {
    case "right": tx = off * distance; break;
    case "left": tx = -off * distance; break;
    case "down": ty = -off * distance; break;
    case "up": ty = off * distance; break;
    case "zoom": scale = 1 - off * 0.2; break;
    case "zoom-out": scale = 1 + off * 0.25; break;
    case "pop": scale = 0.5 + 0.5 * bounce; fade = interpolate(frame, [delay, delay + 4], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }); break;
    case "blur": blur = off * 18; break;
    case "flip": rotY = off * 90; break;
    case "wipe-right": clip = `inset(0 ${off * 100}% 0 0)`; fade = 1; break;
    case "wipe-left": clip = `inset(0 0 0 ${off * 100}%)`; fade = 1; break;
    case "wipe-up": clip = `inset(${off * 100}% 0 0 0)`; fade = 1; break;
    case "wipe-down": clip = `inset(0 0 ${off * 100}% 0)`; fade = 1; break;
    case "fade": break;
  }

  return (
    <div
      style={{
        transform: `perspective(1200px) translate(${tx}px, ${ty}px) scale(${scale}) rotateY(${rotY}deg)`,
        filter: blur ? `blur(${blur}px)` : undefined,
        clipPath: clip,
        WebkitClipPath: clip,
        opacity: fade * (1 - out),
        ...style,
      }}
    >
      {children}
    </div>
  );
};
