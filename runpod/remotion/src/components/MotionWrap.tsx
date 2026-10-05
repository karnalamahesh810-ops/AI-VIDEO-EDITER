import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { clamp01, cubicIn, cubicOut, expoOut, sineInOut } from "./motion/ease";
import type { MotionClass } from "./motion/lookClass";

/**
 * The entrance and exit a graphic moves with, plus its placement.
 *
 * Every look gets a designed entry and a mirrored exit by what it is on
 * screen (components/motion/lookClass.ts; the owner, 2026-10-05: "the other
 * overlay animations are also not smooth - make them smoother and better"):
 *
 *   full   grows in from 96 % out of a soft focus (the clip under it pushes
 *          in and dims at the same time: components/motion/stage.tsx), and
 *          leaves growing a touch and softening;
 *   panel  grows in from 97 % with a short focus pull, leaves the same way;
 *   text   rises a few pixels into focus, leaves rising out of focus;
 *   tag    slides a short way in, leaves the way it came;
 *   mark   fades (its stroke draws itself on).
 *
 * Entries run 12-16 frames on expo / cubic curves, exits 12 frames eased in,
 * at 30 fps and scaled by the real rate (60 fps moves the same in seconds).
 * No exit is ever a hard cut ("none" now leaves like "fade"), and nothing
 * jitters (the old "glitch" entrance arrives as a focus pull).
 *
 * `motion` (overlay.motion) may still name an entrance an editor reaches for:
 * rise, drop, slide-left, slide-right, zoom-in, zoom-out, blur, wipe,
 * wipe-up, flip, glitch, fade ("fade" = the class's own entry). `exit` is
 * fade, slide, scale or none. `speed` scales both. `placement` (position,
 * scale, opacity) is how the editor moves a premade animation around.
 */
export const MOTIONS = ["fade", "rise", "drop", "slide-left", "slide-right", "zoom-in", "zoom-out",
  "blur", "wipe", "wipe-up", "flip", "glitch"] as const;
export const EXITS = ["fade", "slide", "scale", "none"] as const;

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

type Parts = { o: number; tx: number; ty: number; s: number; blur: number; clip?: string; rot?: number };
const REST: Parts = { o: 1, tx: 0, ty: 0, s: 1, blur: 0 };

/** The class's own entry at progress frames `t` (30-fps frames since the start, already rate-scaled). */
const classIn = (klass: MotionClass, t: number, k: number): Parts => {
  switch (klass) {
    case "full": return { o: cubicOut(t / 12), tx: 0, ty: 0, s: 0.96 + 0.04 * expoOut(t / 16), blur: 10 * k * (1 - cubicOut(t / 13)) };
    case "panel": return { o: cubicOut(t / 10), tx: 0, ty: 0, s: 0.97 + 0.03 * expoOut(t / 15), blur: 6 * k * (1 - cubicOut(t / 11)) };
    case "tag": return { o: cubicOut(t / 9), tx: -18 * k * (1 - expoOut(t / 14)), ty: 0, s: 1, blur: 3 * k * (1 - cubicOut(t / 8)) };
    case "mark": return { o: cubicOut(t / 8), tx: 0, ty: 0, s: 1, blur: 0 };
    default: return { o: cubicOut(t / 9), tx: 0, ty: 16 * k * (1 - expoOut(t / 15)), s: 1, blur: 5 * k * (1 - cubicOut(t / 11)) };
  }
};

/** The class's own exit at progress x (0 holding, 1 gone), eased in. */
const classOut = (klass: MotionClass, x: number, k: number): Parts => {
  switch (klass) {
    case "full": return { o: 1 - x, tx: 0, ty: 0, s: 1 + 0.018 * x, blur: 8 * k * x };
    case "panel": return { o: 1 - x, tx: 0, ty: 0, s: 1 - 0.015 * x, blur: 5 * k * x };
    case "tag": return { o: 1 - x, tx: -14 * k * x, ty: 0, s: 1, blur: 2 * k * x };
    case "mark": return { o: 1 - x, tx: 0, ty: 0, s: 1, blur: 0 };
    default: return { o: 1 - x, tx: 0, ty: -10 * k * x, s: 1, blur: 4 * k * x };
  }
};

/** A named entrance an editor chose, at progress e (0..1, expo-out). */
const namedIn = (name: string, e: number, k: number): Parts => {
  const from = 1 - e;
  switch (name) {
    case "rise": return { ...REST, o: clamp01(e * 1.6), ty: from * 70 * k };
    case "drop": return { ...REST, o: clamp01(e * 1.6), ty: -from * 70 * k };
    case "slide-left": return { ...REST, o: clamp01(e * 1.6), tx: from * 200 * k };
    case "slide-right": return { ...REST, o: clamp01(e * 1.6), tx: -from * 200 * k };
    case "zoom-in": return { ...REST, o: clamp01(e * 1.6), s: 0.86 + 0.14 * e };
    case "zoom-out": return { ...REST, o: clamp01(e * 1.6), s: 1.14 - 0.14 * e };
    case "blur": case "glitch": return { ...REST, o: clamp01(e * 1.4), blur: from * 16 * k, s: 1.03 - 0.03 * e };
    case "wipe": return { ...REST, clip: `inset(0 ${(from * 100).toFixed(2)}% 0 0)` };
    case "wipe-up": return { ...REST, clip: `inset(${(from * 100).toFixed(2)}% 0 0 0)` };
    case "flip": return { ...REST, o: clamp01(e * 1.6), rot: from * 60 };
    default: return REST;
  }
};

const namedOut = (name: string, x: number, k: number): Parts | null => {
  switch (name) {
    case "slide": case "slide-left": return { ...REST, o: 1 - x, tx: -x * 160 * k };
    case "slide-right": return { ...REST, o: 1 - x, tx: x * 160 * k };
    case "rise": return { ...REST, o: 1 - x, ty: -x * 60 * k };
    case "drop": return { ...REST, o: 1 - x, ty: x * 60 * k };
    case "scale": case "zoom-in": return { ...REST, o: 1 - x, s: 1 + 0.06 * x };
    case "zoom-out": return { ...REST, o: 1 - x, s: 1 - 0.08 * x };
    case "blur": case "glitch": return { ...REST, o: 1 - x, blur: x * 14 * k };
    case "wipe": return { ...REST, clip: `inset(0 0 0 ${(x * 100).toFixed(2)}%)` };
    case "wipe-up": return { ...REST, clip: `inset(0 0 ${(x * 100).toFixed(2)}% 0)` };
    case "flip": return { ...REST, o: 1 - x, rot: -x * 60 };
    default: return null;
  }
};

const css = (p: Parts, k: number): React.CSSProperties => {
  const t: string[] = [];
  if (p.tx || p.ty) t.push(`translate(${p.tx.toFixed(2)}px, ${p.ty.toFixed(2)}px)`);
  if (p.rot) t.push(`perspective(${(1400 * k).toFixed(0)}px) rotateY(${p.rot.toFixed(2)}deg)`);
  if (p.s !== 1) t.push(`scale(${p.s.toFixed(5)})`);
  const out: React.CSSProperties = {};
  if (t.length) out.transform = t.join(" ");
  if (p.o < 1) out.opacity = Math.max(0, p.o);
  if (p.blur > 0.05) out.filter = `blur(${p.blur.toFixed(2)}px)`;
  if (p.clip) out.clipPath = p.clip;
  return out;
};

export const MotionWrap: React.FC<{
  motion?: string;
  exit?: string;
  speed?: number;
  placement?: Placement;
  klass?: MotionClass;
  children: React.ReactNode;
}> = ({ motion, exit, speed, placement, klass = "text", children }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, width, height } = useVideoConfig();
  const k = width / 1920;
  const S = fps / 30;
  const spd = Math.max(0.5, Math.min(2, speed || 1));
  // 30-fps frames since the start, at this rate and speed.
  const t = (frame / S) * spd;
  const dur30 = (durationInFrames / S) * spd;
  // The exit: 12 frames (never more than a quarter of the look), eased in.
  const outLen = Math.max(2, Math.min(12, Math.floor(dur30 / 4)));
  const x = cubicIn(clamp01((t - (dur30 - outLen)) / outLen));
  const named = motion && motion !== "fade" ? motion : "";
  const inLen = Math.max(2, Math.min(16, Math.floor(dur30 / 3)));
  const entry = named ? namedIn(named, expoOut(t / inLen), k) : classIn(klass, t * (16 / Math.max(16, inLen)), k);
  const exitKind = exit && exit !== "none" && exit !== "fade" ? exit : "";
  const leave = x > 0 ? (exitKind && namedOut(exitKind, x, k)) || classOut(klass, x, k) : REST;

  // Placement: a named position, a scale and an opacity around everything.
  const pos = placement?.position && placement.position !== "auto" ? POSITION_SHIFT[placement.position] : undefined;
  const scale = placement?.scale && placement.scale !== 1 ? placement.scale : 1;
  const opacity = placement?.opacity !== undefined ? placement.opacity : 1;
  const placed: React.CSSProperties = (pos || scale !== 1 || opacity !== 1)
    ? { transform: `translate(${(pos?.[0] ?? 0) * width}px, ${(pos?.[1] ?? 0) * height}px) scale(${scale})`, opacity }
    : {};
  // A gentle idle over the hold (entry landed -> exit start): a slow eased creep, never a loop or a jitter -
  // a full-screen graphic or a panel pushes in a touch, words rise a few pixels, a drawn mark stays put.
  const hold = sineInOut(clamp01((t - inLen) / Math.max(1, dur30 - outLen - inLen)));
  const drift: Parts = klass === "full" ? { ...REST, s: 1 + 0.012 * hold }
    : klass === "panel" ? { ...REST, s: 1 + 0.01 * hold }
      : klass === "mark" ? REST : { ...REST, ty: -3 * k * hold };
  const inner = (
    <AbsoluteFill style={css(leave, k)}>
      <AbsoluteFill style={css(drift, k)}>
        <AbsoluteFill style={css(entry, k)}>{children}</AbsoluteFill>
      </AbsoluteFill>
    </AbsoluteFill>
  );
  return Object.keys(placed).length ? <AbsoluteFill style={placed}>{inner}</AbsoluteFill> : inner;
};
