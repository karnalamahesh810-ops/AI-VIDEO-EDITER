import React from "react";
import { AbsoluteFill, interpolate, random, useCurrentFrame, useVideoConfig } from "remotion";

/**
 * The entrance and exit a graphic moves with, plus its placement.
 *
 * `motion` (overlay.motion) is the entrance, one of twelve moves an editor
 * reaches for: rise, drop, slide-left, slide-right, zoom-in, zoom-out, blur,
 * wipe, wipe-up, flip, glitch, and fade (no movement). `exit` is separate
 * (fade, slide, scale, none), so a graphic that slides in can fade out.
 * `speed` scales both. `placement` (position, scale, opacity) is how the
 * editor moves a premade animation around without touching its template.
 */
export const MOTIONS = ["fade", "rise", "drop", "slide-left", "slide-right", "zoom-in", "zoom-out",
  "blur", "wipe", "wipe-up", "flip", "glitch"] as const;
export const EXITS = ["fade", "slide", "scale", "none"] as const;

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };

// Where an "auto" placement leaves the template's own layout alone; the
// named positions nudge the whole graphic toward a corner or the centre.
const POSITION_SHIFT: Record<string, [number, number]> = {
  "top-left": [-0.22, -0.22], top: [0, -0.22], "top-right": [0.22, -0.22],
  center: [0, 0], "bottom-left": [-0.22, 0.22], bottom: [0, 0.22], "bottom-right": [0.22, 0.22],
};

export interface Placement {
  position?: string;
  scale?: number;
  opacity?: number;
}

export const MotionWrap: React.FC<{
  motion?: string;
  exit?: string;
  speed?: number;
  placement?: Placement;
  children: React.ReactNode;
}> = ({ motion, exit, speed, placement, children }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, width, height } = useVideoConfig();
  const k = width / 1920;
  const spd = Math.max(0.5, Math.min(2, speed || 1));
  const inF = Math.min(Math.round((fps * 0.5) / spd), Math.max(2, Math.floor(durationInFrames / 3)));
  const outF = Math.min(Math.round((fps * 0.35) / spd), Math.max(2, Math.floor(durationInFrames / 4)));
  const e = interpolate(frame, [0, inF], [0, 1], { ...clamp, easing: (t) => 1 - Math.pow(1 - t, 3) });
  const exitKind = exit || (motion && motion !== "fade" ? "same" : "fade");
  // How far into the exit we are, 0..1; "none" never moves out ...
  const x = exitKind === "none" ? 0
    : interpolate(frame, [durationInFrames - outF, durationInFrames], [0, 1], { ...clamp, easing: (t) => t * t });
  // ... but never pops off on a hard cut either (the owner, 2026-10-05: "an animation going only a short
  // time and then skipping"): a look with no exit of its own fades over its last few frames.
  const tailF = Math.max(1, Math.min(6, Math.floor(durationInFrames / 6)));
  const tail = exitKind === "none"
    ? interpolate(frame, [durationInFrames - tailF, durationInFrames], [1, 0], { ...clamp, easing: (t) => t * t })
    : 1;

  const entrance = motion && motion !== "fade" ? motion : "";
  const from = 1 - e;
  let style: React.CSSProperties = {};
  // Entrance.
  switch (entrance) {
    case "rise": style = { transform: `translateY(${from * 90 * k}px)` }; break;
    case "drop": style = { transform: `translateY(${-from * 90 * k}px)` }; break;
    case "slide-left": style = { transform: `translateX(${from * 260 * k}px)` }; break;
    case "slide-right": style = { transform: `translateX(${-from * 260 * k}px)` }; break;
    case "zoom-in": style = { transform: `scale(${0.8 + 0.2 * e})` }; break;
    case "zoom-out": style = { transform: `scale(${1.25 - 0.25 * e})` }; break;
    case "blur": style = { filter: `blur(${from * 18 * k}px)` }; break;
    case "wipe": style = { clipPath: `inset(0 ${from * 100}% 0 0)` }; break;
    case "wipe-up": style = { clipPath: `inset(${from * 100}% 0 0 0)` }; break;
    case "flip": style = { transform: `perspective(${1400 * k}px) rotateY(${from * 70}deg)` }; break;
    case "glitch": {
      const active = frame < inF;
      const j = active ? (random(`g${Math.floor(frame / 2)}`) - 0.5) * 40 * k : 0;
      const band = active ? random(`b${Math.floor(frame / 2)}`) * 80 : 0;
      style = { transform: `translateX(${j}px)`, clipPath: active ? `inset(${band}% 0 ${Math.max(0, 80 - band)}% 0)` : undefined };
      if (active && random(`o${frame}`) > 0.5) style.clipPath = undefined;
      break;
    }
    default: break;
  }
  // Exit, layered on top of the entrance's transform once the entrance is done.
  let exitStyle: React.CSSProperties = {};
  if (x > 0) {
    const kind = exitKind === "same" ? entrance : exitKind;
    switch (kind) {
      case "fade": exitStyle = { opacity: 1 - x }; break;
      case "slide": case "slide-left": exitStyle = { transform: `translateX(${-x * 260 * k}px)`, opacity: 1 - x }; break;
      case "slide-right": exitStyle = { transform: `translateX(${x * 260 * k}px)`, opacity: 1 - x }; break;
      case "rise": exitStyle = { transform: `translateY(${-x * 90 * k}px)`, opacity: 1 - x }; break;
      case "drop": exitStyle = { transform: `translateY(${x * 90 * k}px)`, opacity: 1 - x }; break;
      case "scale": case "zoom-in": exitStyle = { transform: `scale(${1 + 0.08 * x})`, opacity: 1 - x }; break;
      case "zoom-out": exitStyle = { transform: `scale(${1 - 0.1 * x})`, opacity: 1 - x }; break;
      case "blur": exitStyle = { filter: `blur(${x * 18 * k}px)`, opacity: 1 - x }; break;
      case "wipe": exitStyle = { clipPath: `inset(0 0 0 ${x * 100}%)` }; break;
      case "wipe-up": exitStyle = { clipPath: `inset(0 0 ${x * 100}% 0)` }; break;
      case "flip": exitStyle = { transform: `perspective(${1400 * k}px) rotateY(${-x * 70}deg)`, opacity: 1 - x }; break;
      case "glitch": {
        const j = (random(`x${Math.floor(frame / 2)}`) - 0.5) * 40 * k;
        exitStyle = { transform: `translateX(${j}px)`, opacity: 1 - x * 0.7 };
        break;
      }
      default: exitStyle = { opacity: 1 - x };
    }
  }

  // Placement: a named position, a scale and an opacity around everything.
  const pos = placement?.position && placement.position !== "auto" ? POSITION_SHIFT[placement.position] : undefined;
  const scale = placement?.scale && placement.scale !== 1 ? placement.scale : 1;
  const opacity = placement?.opacity !== undefined ? placement.opacity : 1;
  const placed: React.CSSProperties = (pos || scale !== 1 || opacity !== 1)
    ? { transform: `translate(${(pos?.[0] ?? 0) * width}px, ${(pos?.[1] ?? 0) * height}px) scale(${scale})`, opacity }
    : {};

  const outer: React.CSSProperties = tail < 1
    ? { ...exitStyle, opacity: (exitStyle.opacity === undefined ? 1 : Number(exitStyle.opacity)) * tail }
    : exitStyle;
  const inner = <AbsoluteFill style={outer}><AbsoluteFill style={style}>{children}</AbsoluteFill></AbsoluteFill>;
  return Object.keys(placed).length ? <AbsoluteFill style={placed}>{inner}</AbsoluteFill> : inner;
};
