import React from "react";
import { AbsoluteFill, interpolate, random, useCurrentFrame, useVideoConfig } from "remotion";

/**
 * The entrance/exit a graphic moves with (overlay.motion), layered over the
 * template's own fade. Twelve moves, the ones an editor reaches for:
 * rise, drop, slide-left, slide-right, zoom-in, zoom-out, blur, wipe,
 * wipe-up, flip, glitch, and fade (no movement).
 */
export const MOTIONS = ["fade", "rise", "drop", "slide-left", "slide-right", "zoom-in", "zoom-out",
  "blur", "wipe", "wipe-up", "flip", "glitch"] as const;

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };

export const MotionWrap: React.FC<{ motion?: string; children: React.ReactNode }> = ({ motion, children }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, width } = useVideoConfig();
  if (!motion || motion === "fade") return <>{children}</>;
  const inF = Math.min(Math.round(fps * 0.5), Math.max(2, Math.floor(durationInFrames / 3)));
  const outF = Math.min(Math.round(fps * 0.35), Math.max(2, Math.floor(durationInFrames / 4)));
  const e = interpolate(frame, [0, inF], [0, 1], { ...clamp, easing: (t) => 1 - Math.pow(1 - t, 3) });
  const x = interpolate(frame, [durationInFrames - outF, durationInFrames], [0, 1], { ...clamp, easing: (t) => t * t });
  const k = width / 1920;
  const from = 1 - e + x;
  let style: React.CSSProperties = {};
  switch (motion) {
    case "rise": style = { transform: `translateY(${from * 90 * k}px)` }; break;
    case "drop": style = { transform: `translateY(${-from * 90 * k}px)` }; break;
    case "slide-left": style = { transform: `translateX(${(1 - e) * 260 * k - x * 260 * k}px)` }; break;
    case "slide-right": style = { transform: `translateX(${-(1 - e) * 260 * k + x * 260 * k}px)` }; break;
    case "zoom-in": style = { transform: `scale(${0.8 + 0.2 * e + 0.08 * x})` }; break;
    case "zoom-out": style = { transform: `scale(${1.25 - 0.25 * e - 0.1 * x})` }; break;
    case "blur": style = { filter: `blur(${from * 18 * k}px)` }; break;
    case "wipe": style = { clipPath: `inset(0 ${(1 - e) * 100}% 0 ${x * 100}%)` }; break;
    case "wipe-up": style = { clipPath: `inset(${(1 - e) * 100}% 0 ${x * 100}% 0)` }; break;
    case "flip": style = { transform: `perspective(${1400 * k}px) rotateY(${(1 - e) * 70 - x * 70}deg)` }; break;
    case "glitch": {
      const active = frame < inF || frame > durationInFrames - outF;
      const j = active ? (random(`g${Math.floor(frame / 2)}`) - 0.5) * 40 * k : 0;
      const band = active ? random(`b${Math.floor(frame / 2)}`) * 80 : 0;
      style = { transform: `translateX(${j}px)`, clipPath: active ? `inset(${band}% 0 ${Math.max(0, 80 - band)}% 0)` : undefined };
      if (active && random(`o${frame}`) > 0.5) style.clipPath = undefined;
      break;
    }
    default: break;
  }
  return <AbsoluteFill style={style}>{children}</AbsoluteFill>;
};
