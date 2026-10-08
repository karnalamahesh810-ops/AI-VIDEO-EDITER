import React, { useState } from "react";
import { AbsoluteFill, Easing, interpolate } from "remotion";
import type { Box, MediaLiving, Motion, Scene } from "../types";
import { hashStr } from "./timing";
import { StillPicture, stillTransform } from "./stillMotion";
import { aimGlide } from "../components/reframe";
import { usePicturesLoad } from "../components/motion/pictureProbe";
import { SafeImg } from "../components/motion/safePicture";

/**
 * Living photos: a still drawn with real depth (src/living.py cuts it into 2-3
 * layers along its depth edges; media.living lists them back to front).
 *
 * The stack takes the scene's own move, exactly as a flat still would
 * (stillMotion.tsx: push, pull, pan, drift, reveal, turn - aimed at the
 * subject when the plan found one), and inside it the layers move against each
 * other as a real camera move would show them:
 *
 *   push / pull     a dolly: the subject (the nearest layer) keeps the move's
 *                   own zoom while the far layers grow less - the background
 *                   hardly changes size - and slide a little behind it (an
 *                   orbit about the subject)
 *   pan / drift     a truck: the nearer a layer, the further it travels
 *   reveal          the nearer layers slide in further, then settle
 *
 * The nearest and the farthest layer part by `strength` of the frame over the
 * shot (never more than LIVING_MAX_STRENGTH, and at most LIVING_RATE a second:
 * a short shot moves less, never faster), eased like the move itself. A dolly
 * never uncovers anything (the near layer is always at least as big as at
 * rest); only sideways moves reveal what src/living.py filled in behind.
 *
 * The overscan is solved against the move's own margin: the layers are
 * enlarged only when, on some frame, an edge of one would otherwise show - all
 * of them alike, so at rest they line up into the picture exactly.
 *
 * Pure data and the frame number: every machine of a split render draws the
 * same pixels. A layer that cannot load: the flat still, as before.
 */

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const smooth = Easing.bezier(0.45, 0.05, 0.55, 0.95);     // stillMotion.tsx's ease
const settle = Easing.bezier(0.16, 1, 0.3, 1);

/** The shift between the nearest and the farthest layer never exceeds this share of the frame. */
export const LIVING_MAX_STRENGTH = 0.1;
/** ...nor this share per second of the shot. */
export const LIVING_RATE = 0.02;
/** A dolly: how much less the farthest layer zooms than the subject, per unit of strength. */
export const DOLLY_GAIN = 1.2;
/** A dolly: the orbit about the subject, per unit of strength. */
export const ORBIT_GAIN = 0.6;
/** The camera turns about a point no nearer the frame's edge than this. */
const PIVOT_EDGE = 0.25;
/** How many frames of the shot the overscan is solved on (the motion is smooth between them). */
const SAMPLES = 24;

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

export interface LivingPlan {
  /** Back to front; `near`: 0 = the farthest layer .. 1 = the nearest. */
  layers: { url: string; near: number; box?: [number, number, number, number] }[];
  /** The nearest layer's middle, shares of the picture. */
  focus: { x: number; y: number };
  /** The picture's width / height (0: unknown - no cut layer can then be placed). */
  aspect: number;
  strength: number;
}

const validCut = (b: unknown): b is [number, number, number, number] =>
  Array.isArray(b) && b.length === 4 && b.every(finite) && b[0] >= -0.001 && b[1] >= -0.001
  && b[2] <= 1.001 && b[3] <= 1.001 && b[2] - b[0] > 0.001 && b[3] - b[1] > 0.001;

/**
 * The layers a scene's still is drawn with, or null (drawn flat): only an
 * image with 2-4 well-formed layers, bound to its own source, not switched off
 * by the editor (scene.living "off").
 */
export const resolveLiving = (scene: Scene): LivingPlan | null => {
  if (scene.living === "off" || scene.living === false) return null;
  const m = scene.media;
  const liv: MediaLiving | undefined = m?.living;
  if (!m || m.type !== "image" || !m.url || !liv || typeof liv !== "object" || !Array.isArray(liv.layers)) return null;
  if (liv.source !== undefined && liv.source !== (m.source ?? "")) return null;
  const raw = liv.layers;
  if (raw.length < 2 || raw.length > 4) return null;
  if (!raw.every((l) => l && typeof l.url === "string" && l.url.length > 0 && finite(l.depth))) return null;
  if (raw[0].box !== undefined || !raw.slice(1).every((l) => l.box === undefined || validCut(l.box))) return null;
  const aspect = finite(liv.aspect) && liv.aspect > 0.1 && liv.aspect < 10 ? liv.aspect : 0;
  if (!aspect && raw.some((l) => l.box !== undefined)) return null;
  const d0 = raw[0].depth;
  const span = raw[raw.length - 1].depth - d0;
  const layers = raw.map((l, i) => ({
    url: l.url,
    near: span > 0.01 ? Math.max(0, Math.min(1, (l.depth - d0) / span)) : i / (raw.length - 1),
    box: l.box,
  }));
  const fx = finite(liv.focus?.x) ? Math.max(0, Math.min(1, liv.focus!.x)) : 0.5;
  const fy = finite(liv.focus?.y) ? Math.max(0, Math.min(1, liv.focus!.y)) : 0.5;
  const strength = finite(liv.strength) ? Math.max(0, Math.min(LIVING_MAX_STRENGTH, liv.strength)) : 0.03;
  return { layers, focus: { x: fx, y: fy }, aspect, strength };
};

/** Where the picture lies in the frame when it covers it (frame shares: left, top, width, height). */
export const coverRect = (picAspect: number, frameAspect: number): [number, number, number, number] => {
  if (!(picAspect > 0) || !(frameAspect > 0)) return [0, 0, 1, 1];
  if (picAspect >= frameAspect) {
    const w = picAspect / frameAspect;
    return [(1 - w) / 2, 0, w, 1];
  }
  const h = frameAspect / picAspect;
  return [0, (1 - h) / 2, 1, h];
};

/** The move a "parallax" still makes with real layers: a pan (it no longer needs its print on a blurred copy). */
export const livingMotion = (motion: Motion | undefined, seedKey: string): Motion | undefined =>
  motion === "parallax" ? (hashStr(seedKey || "still") % 2 ? "pan-left" : "pan-right") : motion;

/** Which way a pan or drift carries the picture across the frame ([x, y], -1..1), as stillMotion.tsx moves it. */
const travel = (motion: Motion | undefined, h: number, subject?: Box): [number, number] => {
  if (motion === "pan-left" || motion === "pan-right") {
    const own = motion === "pan-left" ? -1 : 1;
    if (!subject) return [own, 0];
    const [a, b] = aimGlide(subject.x, subject.x + subject.w, 1 / 1.15, 0.064, motion === "pan-left" ? 1 : -1);
    return [Math.abs(b - a) > 1e-4 ? -Math.sign(b - a) : own, 0];
  }
  if (motion === "drift-diagonal") {
    const sx = h % 2 ? 1 : -1;
    const sy = (h >>> 1) % 2 ? 1 : -1;
    if (!subject) return [sx, 0.7 * sy];
    const [ax, bx] = aimGlide(subject.x, subject.x + subject.w, 1 / 1.16, 0.052, -sx, 1 / 1.13);
    const [ay, by] = aimGlide(subject.y, subject.y + subject.h, 1 / 1.16, 0.036, -sy, 1 / 1.13);
    const dx = Math.abs(bx - ax) > 1e-4 ? -Math.sign(bx - ax) : 0;
    const dy = Math.abs(by - ay) > 1e-4 ? -Math.sign(by - ay) * 0.7 : 0;
    return dx || dy ? [dx, dy] : [sx, 0.7 * sy];
  }
  return [0, 0];
};

/** A layer's own move inside the stack at a frame: its shift (frame shares) and its scale about the pivot. */
export interface LayerMove { x: number; y: number; s: number }

/**
 * Where a layer `near` (0 far .. 1 near) sits against the stack at a frame of
 * the shot, for the scene's move. The subject is the nearest layer.
 */
export const layerMove = (
  motion: Motion | undefined, near: number, frame: number, durationInFrames: number, fps: number,
  strength: number, seedKey: string, subject?: Box,
): LayerMove => {
  const dur = Math.max(1, durationInFrames);
  const amp = Math.max(0, Math.min(strength, LIVING_RATE * (dur / Math.max(1, fps)), LIVING_MAX_STRENGTH));
  const e = smooth(interpolate(frame, [0, dur], [0, 1], clamp));
  const h = hashStr(seedKey || "still");
  const across = h % 2 ? 1 : -1;
  const far = 1 - near;
  switch (motion) {
    case "pan-left":
    case "pan-right":
    case "drift-diagonal": {
      // A truck: about the middle depth, the nearer travelling further the picture's own way.
      const [dx, dy] = travel(motion, h, subject);
      const k = amp * (near - 0.5) * (e - 0.5);
      return { x: k * dx, y: k * dy, s: 1 };
    }
    case "reveal-left":
    case "reveal-right": {
      // The side it slides in from (stillMotion.tsx): the nearer layers travel further while it
      // slides in (centred on the slide: the gap is never the whole shift), then a gentle dolly.
      const c = subject ? subject.x + subject.w / 2 : 0.5;
      const side = c > 0.55 ? -1 : c < 0.45 ? 1 : motion === "reveal-left" ? -1 : 1;
      const s = interpolate(frame, [0, Math.round(fps * 1.0)], [0, 1], { ...clamp, easing: settle });
      return { x: amp * 0.7 * side * (0.5 - s) * (near - 0.5), y: 0, s: 1 - far * amp * DOLLY_GAIN * 0.5 * e };
    }
    case "zoom-out":
    case "pull-back":
      // A dolly out: the far layers start smaller than the subject and meet it at the end.
      return { x: -far * amp * ORBIT_GAIN * (e - 0.5) * across, y: 0, s: 1 - far * amp * DOLLY_GAIN * (1 - e) };
    default:
      // A dolly in (zoom-in, push-offcenter, push-rotate, rotate-settle, a ken-burns still):
      // the far layers zoom less than the subject and slide behind it.
      return { x: -far * amp * ORBIT_GAIN * (e - 0.5) * across, y: 0, s: 1 - far * amp * DOLLY_GAIN * e };
  }
};

/** A 2-D affine transform [a, b, c, d, e, f]: x' = a x + c y + e, y' = b x + d y + f (px). */
type Affine = [number, number, number, number, number, number];
const mul = (m: Affine, n: Affine): Affine => [
  m[0] * n[0] + m[2] * n[1], m[1] * n[0] + m[3] * n[1],
  m[0] * n[2] + m[2] * n[3], m[1] * n[2] + m[3] * n[3],
  m[0] * n[4] + m[2] * n[5] + m[4], m[1] * n[4] + m[3] * n[5] + m[5],
];

/**
 * A CSS transform (the functions stillMotion.tsx writes: scale, translate,
 * translateX/Y, rotate) about its origin, as an affine map of an element w x h px.
 */
export const cssAffine = (css: string, w: number, h: number, origin?: string): Affine => {
  const len = (v: string, ref: number) => (v.trim().endsWith("%") ? (parseFloat(v) / 100) * ref : parseFloat(v));
  let m: Affine = [1, 0, 0, 1, 0, 0];
  for (const [, fn, args] of css.matchAll(/([a-zA-Z]+)\(([^)]*)\)/g)) {
    const v = args.split(",");
    if (fn === "scale") {
      const sx = parseFloat(v[0]);
      const sy = v.length > 1 ? parseFloat(v[1]) : sx;
      m = mul(m, [sx, 0, 0, sy, 0, 0]);
    } else if (fn === "translate") {
      m = mul(m, [1, 0, 0, 1, len(v[0], w), v.length > 1 ? len(v[1], h) : 0]);
    } else if (fn === "translateX") {
      m = mul(m, [1, 0, 0, 1, len(v[0], w), 0]);
    } else if (fn === "translateY") {
      m = mul(m, [1, 0, 0, 1, 0, len(v[0], h)]);
    } else if (fn === "rotate") {
      const r = (parseFloat(v[0]) * Math.PI) / 180;
      m = mul(m, [Math.cos(r), Math.sin(r), -Math.sin(r), Math.cos(r), 0, 0]);
    }
  }
  const o = (origin || "50% 50%").trim().split(/\s+/);
  const ox = len(o[0] ?? "50%", w);
  const oy = len(o[1] ?? "50%", h);
  return mul(mul([1, 0, 0, 1, ox, oy], m), [1, 0, 0, 1, -ox, -oy]);
};

/** Where the frame's corners lie inside a stack drawn with `m` (shares of the stack's box). */
const visibleCorners = (m: Affine, w: number, h: number): [number, number][] => {
  const det = m[0] * m[3] - m[1] * m[2];
  if (Math.abs(det) < 1e-9) return [[0, 0], [1, 0], [0, 1], [1, 1]];
  const inv = (x: number, y: number): [number, number] => {
    const px = x - m[4];
    const py = y - m[5];
    return [((m[3] * px - m[2] * py) / det) / w, ((-m[1] * px + m[0] * py) / det) / h];
  };
  return [inv(0, 0), inv(w, 0), inv(0, h), inv(w, h)];
};

/**
 * The one overscan (>= 1) every layer gets so that, on every frame, each
 * layer - moved by `moves[layer][frame]` about `pivot` - still covers the part
 * of the stack the frame shows (`corners[frame]`). Exact per corner and axis:
 * the layer covers c when pivot + (c - pivot - shift) / (k s) lies in 0..1.
 */
export const overscan = (moves: LayerMove[][], corners: [number, number][][], pivot: [number, number]): number => {
  let need = 1;
  for (const path of moves) {
    path.forEach((mv, f) => {
      for (const c of corners[f]) {
        for (const ax of [0, 1]) {
          const d = c[ax] - pivot[ax] - (ax === 0 ? mv.x : mv.y);
          const k = d > 0 ? d / (mv.s * (1 - pivot[ax])) : -d / (mv.s * pivot[ax]);
          need = Math.max(need, k);
        }
      }
    });
  }
  return need + 0.002;
};

/**
 * A still with depth: the scene's move on the stack, each layer moved
 * against it by its depth. `src` is the flat picture: the move is seeded by
 * it exactly as the flat still's, and drawn instead when a layer fails (every
 * layer is loaded first, pictureProbe: one that cannot load never reaches the
 * frame, and never holds up the render).
 */
export const LivingPicture: React.FC<{
  src: string;
  living: LivingPlan;
  motion: Motion | undefined;
  frame: number;
  durationInFrames: number;
  fps: number;
  width: number;
  height: number;
  filter?: string;
  subject?: Box;
  /** Drawn blurred instead when even the flat picture cannot be drawn (the shot before it). */
  fallbackStill?: string | string[];
  /** What the move is seeded by: the scene's id (StillPicture's seed), else the picture's link. */
  seed?: string;
}> = ({ src, living, motion, frame, durationInFrames, fps, width, height, filter, subject, fallbackStill, seed }) => {
  const key = seed || src;
  const [failed, setFailed] = useState(false);
  const layersLoad = usePicturesLoad(living.layers.map((l) => l.url));
  if (failed || layersLoad === false) {
    return <StillPicture src={src} motion={motion} frame={frame} durationInFrames={durationInFrames} fps={fps}
      width={width} filter={filter} subject={subject} fallbackStill={fallbackStill} seed={seed} />;
  }
  if (layersLoad === null) return null;
  const move = livingMotion(motion, key);
  const outer = stillTransform(move, frame, durationInFrames, fps, key, subject);
  const frameAspect = width / Math.max(1, height);
  const [cl, ct, cw, ch] = coverRect(living.aspect || frameAspect, frameAspect);
  // The camera turns about the subject the move is aimed at, else the nearest layer's middle.
  const fx = subject ? subject.x + subject.w / 2 : cl + living.focus.x * cw;
  const fy = subject ? subject.y + subject.h / 2 : ct + living.focus.y * ch;
  const pivot: [number, number] = [Math.max(PIVOT_EDGE, Math.min(1 - PIVOT_EDGE, fx)),
    Math.max(PIVOT_EDGE, Math.min(1 - PIVOT_EDGE, fy))];
  const dur = Math.max(1, durationInFrames);
  // The overscan: solved on SAMPLES frames of the whole shot (the same on every frame).
  const corners: [number, number][][] = [];
  const at: number[] = [];
  for (let k = 0; k <= SAMPLES; k++) {
    const f = (k / SAMPLES) * (dur - 1);
    at.push(f);
    const o = stillTransform(move, f, durationInFrames, fps, key, subject);
    corners.push(visibleCorners(cssAffine(o.transform, width, height, o.transformOrigin), width, height));
  }
  const moves = living.layers.map((l) => at.map((f) => layerMove(move, l.near, f, dur, fps, living.strength, key,
    subject)));
  const pad = overscan(moves, corners, pivot);
  const origin = `${(pivot[0] * 100).toFixed(3)}% ${(pivot[1] * 100).toFixed(3)}%`;
  const fail = () => setFailed(true);
  return (
    <AbsoluteFill style={{ transform: outer.transform, transformOrigin: outer.transformOrigin, filter }}>
      {living.layers.map((layer, i) => {
        const mv = layerMove(move, layer.near, frame, dur, fps, living.strength, key, subject);
        const transform = `translate(${(mv.x * 100).toFixed(4)}%, ${(mv.y * 100).toFixed(4)}%) `
          + `scale(${(pad * mv.s).toFixed(5)})`;
        if (!layer.box) {
          return (
            <SafeImg key={i} src={layer.url} onFail={fail} fallback={null} maxRetries={1}
              style={{ position: "absolute", width: "100%", height: "100%", objectFit: "cover", transform,
                transformOrigin: origin }} />
          );
        }
        const [x0, y0, x1, y1] = layer.box;
        return (
          <AbsoluteFill key={i} style={{ transform, transformOrigin: origin }}>
            <SafeImg src={layer.url} onFail={fail} fallback={null} maxRetries={1}
              style={{ position: "absolute", left: `${((cl + x0 * cw) * 100).toFixed(4)}%`,
                top: `${((ct + y0 * ch) * 100).toFixed(4)}%`, width: `${((x1 - x0) * cw * 100).toFixed(4)}%`,
                height: `${((y1 - y0) * ch * 100).toFixed(4)}%`, objectFit: "fill" }} />
          </AbsoluteFill>
        );
      })}
    </AbsoluteFill>
  );
};
