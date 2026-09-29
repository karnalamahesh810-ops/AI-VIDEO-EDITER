import React from "react";
import { AbsoluteFill, random, useCurrentFrame, useVideoConfig } from "remotion";
import type { SceneTransition } from "../types";
import {
  easeInOutSine, easeInQuad, easeOutCubic, hashStr, transitionState,
  type TransitionState,
} from "./timing";

/**
 * The cut transitions a human editor reaches for, applied to the scene
 * CONTENT itself (the clip, its grade and grain) rather than laid flat over it:
 *
 *   flash            exposure blooms to white into the cut and back out
 *   chromatic-flash  the same bloom with the colour channels tearing apart
 *   glitch           RGB channel split + displaced horizontal slices + scanlines
 *   vhs-glitch       chroma bleed, a rolling tracking band, wobble and scanlines
 *   film-burn        an organic warm burn (turbulence-warped gradient) with grain
 *   light-leak       soft amber/rose leaks drifting across the cut, with grain
 *   whip-pan         directional motion-blur slide out and in
 *   zoom-punch       a zoom punch-in with blur that settles on the new shot
 *   shake-cut        a short camera shake on impact
 *   blur-dissolve    defocus out of the old shot, refocus into the new one
 *   luma-fade        dip through black where shadows fall first
 *
 * Only the few frames around a cut do any work: outside the windows the
 * wrapper is a plain full-frame div with no filter, so the rest of the video
 * pays nothing. The DOM shape never changes between frames (no remounts of
 * the video underneath).
 */

interface Look {
  /** Style for the content container: transform / filter / opacity. */
  style: React.CSSProperties;
  /**
   * SVG filter primitives for this frame (referenced by style.filter as
   * url(#id)). They read the picture from the result named "SRC": the scene
   * itself, or with `tile` the scene repeated edge to edge, so a whip or a
   * displaced slice pulls in picture instead of black past the frame edge.
   */
  filter?: React.ReactNode;
  tile?: boolean;
  /** Filter region as fractions of the frame (default: 5% margin). */
  region?: { x: number; w: number };
  /** Layers drawn above the content. */
  over?: React.ReactNode;
}

const R = (seed: string) => random(seed);

const rgbSplit = (src: string, rx: number, bx: number, blurR = 0, blurB = 0): React.ReactNode => (
  <>
    <feColorMatrix in={src} type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="cr" />
    {blurR > 0 ? <feGaussianBlur in="cr" stdDeviation={`${blurR} 0`} result="crb" /> : null}
    <feOffset in={blurR > 0 ? "crb" : "cr"} dx={rx} dy={0} result="cr2" />
    <feColorMatrix in={src} type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0" result="cg" />
    <feColorMatrix in={src} type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0" result="cb" />
    {blurB > 0 ? <feGaussianBlur in="cb" stdDeviation={`${blurB} 0`} result="cbb" /> : null}
    <feOffset in={blurB > 0 ? "cbb" : "cb"} dx={bx} dy={0} result="cb2" />
    <feBlend in="cr2" in2="cg" mode="screen" result="crg" />
    <feBlend in="crg" in2="cb2" mode="screen" />
  </>
);

/** Horizontal bands from 1-D noise, quantised into slices, as a displacement map. */
const slices = (seed: number, yFreq: number, scale: number, out: string): React.ReactNode => (
  <>
    <feTurbulence type="fractalNoise" baseFrequency={`0.00001 ${yFreq}`} numOctaves={1} seed={seed} result="sn" />
    <feComponentTransfer in="sn" result="sm">
      <feFuncR type="discrete" tableValues="0.5 0.5 0.5 0.12 0.5 0.86 0.5 0.5 0.3 0.5 0.72 0.5" />
      <feFuncG type="linear" slope={0} intercept={0.5} />
      <feFuncB type="linear" slope={0} intercept={0.5} />
      <feFuncA type="linear" slope={0} intercept={1} />
    </feComponentTransfer>
    <feDisplacementMap in="SRC" in2="sm" scale={scale} xChannelSelector="R" yChannelSelector="G" result={out} />
  </>
);

const Grain: React.FC<{ id: string; seed: number; opacity: number }> = ({ id, seed, opacity }) => (
  <svg width="100%" height="100%" style={{ position: "absolute", inset: 0, opacity, mixBlendMode: "overlay", pointerEvents: "none" }}>
    <filter id={`${id}-grain`} x="0" y="0" width="100%" height="100%">
      <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves={2} seed={seed} />
      <feColorMatrix type="saturate" values="0" />
    </filter>
    <rect width="100%" height="100%" filter={`url(#${id}-grain)`} />
  </svg>
);

const Scanlines: React.FC<{ opacity: number; k: number }> = ({ opacity, k }) => (
  <AbsoluteFill style={{
    opacity, pointerEvents: "none", mixBlendMode: "multiply",
    backgroundImage: `repeating-linear-gradient(0deg, rgba(0,0,0,0.55) 0px, rgba(0,0,0,0.55) ${Math.max(1, 2 * k)}px, rgba(0,0,0,0) ${Math.max(1, 2 * k)}px, rgba(0,0,0,0) ${Math.max(2, 4 * k)}px)`,
  }} />
);

const lookFor = (s: TransitionState, id: string, fid: string, k: number): Look => {
  const { name, rel, side, p } = s;
  const seedBase = hashStr(id);
  switch (name) {
    case "flash": {
      // Exposure bloom: the old shot overexposes into white, the new one comes
      // back out of it. Peak on the cut.
      const e = side === "out" ? easeInQuad(p) : Math.pow(1 - p, 2.6);
      return {
        style: { filter: `brightness(${(1 + 2.4 * e).toFixed(3)}) saturate(${(1 - 0.4 * e).toFixed(3)}) contrast(${(1 - 0.2 * e).toFixed(3)}) blur(${(2.5 * e * k).toFixed(2)}px)` },
        over: (
          <AbsoluteFill style={{
            pointerEvents: "none",
            opacity: Math.min(1, (side === "in" && rel === 0 ? 0.97 : 0.92 * Math.pow(e, 1.4))),
            background: "radial-gradient(ellipse at 50% 50%, #ffffff 0%, #fffdf6 45%, rgba(255,250,240,0.88) 100%)",
          }} />
        ),
      };
    }
    case "chromatic-flash": {
      const e = side === "out" ? easeInQuad(p) : Math.pow(1 - p, 2);
      const d = 34 * e * k;
      return {
        style: {
          filter: `url(#${fid}) brightness(${(1 + 1.7 * e).toFixed(3)}) saturate(${(1 + 0.3 * e).toFixed(3)})`,
          transform: `scale(${(1 + 0.04 * e).toFixed(4)})`,
        },
        filter: rgbSplit("SRC", -d, d),
        over: (
          <AbsoluteFill style={{
            pointerEvents: "none",
            opacity: Math.min(1, side === "in" && rel === 0 ? 0.9 : 0.85 * Math.pow(e, 1.6)),
            background: "radial-gradient(ellipse at 50% 50%, rgba(255,255,255,1) 0%, rgba(255,255,255,0.95) 38%, rgba(255,150,225,0.8) 72%, rgba(90,210,255,0.8) 100%)",
            mixBlendMode: "screen",
          }} />
        ),
      };
    }
    case "glitch": {
      // Stuttering: a frame or two drops almost clean between the hits.
      const env = side === "out" ? 0.3 + 0.7 * p : Math.pow(1 - p, 1.3);
      // (never on the frames either side of the cut, which carry the hit)
      const stutter = rel !== 0 && rel !== -1 && R(`gst${id}${rel}`) < 0.22 ? 0.25 : 1;
      const e = env * stutter;
      const rx = -(8 + 26 * R(`grx${id}${rel}`)) * e * k;
      const bx = (8 + 26 * R(`gbx${id}${rel}`)) * e * k;
      const sc = (70 + 170 * R(`gsc${id}${rel}`)) * e * k;
      const yf = 0.004 + 0.022 * R(`gyf${id}${rel}`);
      const jit = (R(`gj${id}${rel}`) - 0.5) * 36 * e * k;
      const bars = [0, 1, 2].map((i) => ({
        top: R(`gbt${id}${rel}${i}`) * 94,
        h: 0.6 + R(`gbh${id}${rel}${i}`) * 3.2,
        x: (R(`gbs${id}${rel}${i}`) - 0.5) * 160 * k,
        c: i % 2 ? "rgba(0,255,240,0.28)" : "rgba(255,40,120,0.28)",
      }));
      return {
        style: {
          filter: `url(#${fid}) contrast(${(1 + 0.15 * e).toFixed(3)}) brightness(${(1 + 0.08 * e).toFixed(3)})`,
          transform: `translateX(${jit.toFixed(1)}px)`,
        },
        tile: true,
        filter: (
          <>
            {slices(seedBase % 997 + rel + 40, yf, sc, "sl")}
            {rgbSplit("sl", rx, bx)}
          </>
        ),
        over: (
          <>
            <Scanlines opacity={0.45 * e} k={k} />
            <AbsoluteFill style={{ pointerEvents: "none", opacity: Math.min(1, e * 1.2) }}>
              {bars.map((b, i) => (
                <div key={i} style={{ position: "absolute", left: 0, right: 0, top: `${b.top}%`, height: `${b.h}%`,
                  transform: `translateX(${b.x}px)`, background: b.c, mixBlendMode: "screen" }} />
              ))}
            </AbsoluteFill>
          </>
        ),
      };
    }
    case "vhs-glitch": {
      const e = side === "out" ? 0.35 + 0.65 * p : Math.pow(1 - p, 1.15);
      const total = 13;
      const t = (rel + 3) / total;                          // 0..1 across the whole transition
      const bandTop = -12 + t * 118;                          // the tracking band rolls down the frame
      const wob = (6 + 22 * e) * k;
      const jy = (R(`vj${id}${Math.floor(rel / 2)}`) - 0.5) * 8 * e * k;
      return {
        style: {
          filter: `url(#${fid}) saturate(${(1 - 0.3 * e).toFixed(3)}) contrast(${(1 + 0.12 * e).toFixed(3)}) brightness(${(1 + 0.06 * e).toFixed(3)})`,
          transform: `translateY(${jy.toFixed(1)}px)`,
        },
        tile: true,
        filter: (
          <>
            <feTurbulence type="fractalNoise" baseFrequency="0.00001 0.011" numOctaves={2}
              seed={(seedBase % 991) + Math.floor(rel / 2) + 7} result="vw" />
            <feComponentTransfer in="vw" result="vwm">
              <feFuncG type="linear" slope={0} intercept={0.5} />
            </feComponentTransfer>
            <feDisplacementMap in="SRC" in2="vwm" scale={wob} xChannelSelector="R" yChannelSelector="G" result="vd" />
            {rgbSplit("vd", (5 + 9 * e) * k, -(4 + 7 * e) * k, (2 + 7 * e) * k, (2 + 6 * e) * k)}
          </>
        ),
        over: (
          <>
            <Scanlines opacity={0.35 * e} k={k} />
            {/* The tracking band: a streak of bright noise rolling down, a dark smear under it. */}
            <div style={{ position: "absolute", left: 0, right: 0, top: `${bandTop}%`, height: "7%", opacity: 0.75 * e,
              pointerEvents: "none", mixBlendMode: "screen" }}>
              <svg width="100%" height="100%" preserveAspectRatio="none">
                <filter id={`${fid}-band`} x="0" y="0" width="100%" height="100%">
                  <feTurbulence type="fractalNoise" baseFrequency="0.9 0.04" numOctaves={1} seed={rel + 3} />
                  <feColorMatrix type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  2.2 0 0 0 -0.9" />
                </filter>
                <rect width="100%" height="100%" filter={`url(#${fid}-band)`} />
              </svg>
            </div>
            <div style={{ position: "absolute", left: 0, right: 0, top: `${bandTop + 7}%`, height: "3%", opacity: 0.5 * e,
              pointerEvents: "none", background: "linear-gradient(rgba(0,0,0,0.6), rgba(0,0,0,0))" }} />
            {/* Head-switching noise at the bottom edge. */}
            <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: "3.2%", opacity: 0.6 * e,
              pointerEvents: "none", transform: `translateX(${(R(`vh${id}${rel}`) - 0.5) * 60 * k}px)`,
              background: "linear-gradient(90deg, rgba(255,255,255,0.0), rgba(220,220,255,0.65) 30%, rgba(255,255,255,0.15) 55%, rgba(200,255,240,0.6) 80%, rgba(255,255,255,0))" }} />
          </>
        ),
      };
    }
    case "film-burn": {
      // Warm, organic: a turbulence-warped hot gradient that flares across the
      // cut from one side, white-hot at its core, with grain on top.
      const e = side === "out" ? Math.pow(p, 1.5) : Math.pow(1 - p, 1.25);
      const fromLeft = seedBase % 2 === 0;
      // The burn travels the whole transition: in from one edge, past the
      // middle on the cut (where it is widest and white-hot), out the far side.
      const tt = Math.max(0, Math.min(1, (rel + 6) / 20));   // film-burn spans 6 frames out + 14 in
      const cx = fromLeft ? -12 + tt * 100 : 112 - tt * 100;
      const r = 30 + 75 * e;
      const seed = (seedBase % 97) + Math.floor((rel + 8) / 2);
      return {
        style: { filter: `brightness(${(1 + 0.5 * e).toFixed(3)}) sepia(${(0.4 * e).toFixed(3)}) saturate(${(1 + 0.4 * e).toFixed(3)})` },
        over: (
          <>
            <svg width="100%" height="100%" viewBox="0 0 1920 1080" preserveAspectRatio="none"
              style={{ position: "absolute", inset: 0, mixBlendMode: "screen", opacity: Math.min(1, 0.3 + e), pointerEvents: "none" }}>
              <defs>
                <radialGradient id={`${fid}-burn`} cx={`${cx}%`} cy="46%" r={`${r}%`}>
                  <stop offset="0%" stopColor="#fffdf5" stopOpacity={1} />
                  <stop offset="18%" stopColor="#ffe2a6" stopOpacity={1} />
                  <stop offset="38%" stopColor="#ffa040" stopOpacity={0.95} />
                  <stop offset="58%" stopColor="#e2480f" stopOpacity={0.8} />
                  <stop offset="76%" stopColor="#8a1600" stopOpacity={0.45} />
                  <stop offset="100%" stopColor="#000000" stopOpacity={0} />
                </radialGradient>
                <radialGradient id={`${fid}-edge`} cx={fromLeft ? "0%" : "100%"} cy="70%" r={`${20 + 40 * e}%`}>
                  <stop offset="0%" stopColor="#ff6a1a" stopOpacity={0.95} />
                  <stop offset="55%" stopColor="#b82200" stopOpacity={0.55} />
                  <stop offset="100%" stopColor="#000000" stopOpacity={0} />
                </radialGradient>
                {/* Turbulence warps the glow into blotches; the alpha curve gives them a burnt edge. */}
                <filter id={`${fid}-warp`} x="-10%" y="-10%" width="120%" height="120%" colorInterpolationFilters="sRGB">
                  <feTurbulence type="fractalNoise" baseFrequency="0.0042 0.0065" numOctaves={4} seed={seed} result="bt" />
                  <feDisplacementMap in="SourceGraphic" in2="bt" scale={380 + 220 * e} xChannelSelector="R" yChannelSelector="G" result="bw" />
                  <feComponentTransfer in="bw" result="be">
                    <feFuncA type="linear" slope={2.1} intercept={-0.28} />
                  </feComponentTransfer>
                  <feGaussianBlur in="be" stdDeviation={10} />
                </filter>
              </defs>
              <g filter={`url(#${fid}-warp)`}>
                <rect x="-100" y="-100" width="2120" height="1280" fill={`url(#${fid}-burn)`} />
                <rect x="-100" y="-100" width="2120" height="1280" fill={`url(#${fid}-edge)`} />
              </g>
            </svg>
            <Grain id={fid} seed={(rel + 20) % 50} opacity={0.35 * Math.min(1, e + 0.2)} />
          </>
        ),
      };
    }
    case "light-leak": {
      const e = side === "out" ? easeInOutSine(p) : Math.pow(1 - p, 1.4);
      const dir = seedBase % 2 === 0 ? 1 : -1;
      const t = side === "out" ? p * 0.4 : 0.4 + p * 0.6;
      const x1 = 50 + dir * (60 - t * 95);
      const x2 = 50 + dir * (85 - t * 120);
      return {
        style: { filter: `brightness(${(1 + 0.3 * e).toFixed(3)}) sepia(${(0.12 * e).toFixed(3)})` },
        over: (
          <>
            <AbsoluteFill style={{
              pointerEvents: "none", mixBlendMode: "screen", opacity: 0.95 * e,
              background:
                `radial-gradient(ellipse 55% 85% at ${x1}% 40%, rgba(255,214,150,0.95) 0%, rgba(255,150,70,0.65) 32%, rgba(230,80,40,0.25) 58%, rgba(0,0,0,0) 78%),` +
                `radial-gradient(ellipse 35% 70% at ${x2}% 70%, rgba(255,120,150,0.7) 0%, rgba(255,90,90,0.3) 45%, rgba(0,0,0,0) 75%)`,
              filter: `blur(${(18 * k).toFixed(1)}px)`,
            }} />
            <Grain id={fid} seed={(rel + 30) % 50} opacity={0.22 * e} />
          </>
        ),
      };
    }
    case "whip-pan": {
      // The camera whips: the picture slides hard with a directional motion
      // blur. The scene is tiled past its edges inside the filter, so the
      // slide pulls in (blurred) picture rather than black.
      const dir = seedBase % 2 === 0 ? 1 : -1;      // 1: the camera whips right (content leaves left)
      const e = side === "out" ? easeInQuad(p) : Math.pow(1 - easeOutCubic(p), 1.3);
      const shift = (side === "out" ? -dir : dir) * 42 * e;
      const blurX = 150 * e * k;
      if (blurX < 0.5 && Math.abs(shift) < 0.05) return { style: {} };
      return {
        style: {
          transform: `translateX(${shift.toFixed(2)}%) scale(${(1 + 0.03 * e).toFixed(4)})`,
          filter: `url(#${fid}) brightness(${(1 + 0.06 * e).toFixed(3)})`,
        },
        tile: true,
        region: { x: -0.6, w: 2.2 },
        filter: <feGaussianBlur in="SRC" stdDeviation={`${blurX.toFixed(1)} ${(blurX * 0.04).toFixed(1)}`} />,
      };
    }
    case "zoom-punch": {
      if (side === "out") {
        const e = easeInQuad(p);
        return { style: { transform: `scale(${(1 + 0.16 * e).toFixed(4)})`,
          filter: `blur(${(3 * e * k).toFixed(2)}px) brightness(${(1 + 0.18 * e).toFixed(3)})` } };
      }
      const q = easeOutCubic(p);
      const s = 1 + 0.22 * (1 - q) + 0.012 * Math.sin(Math.PI * q) * (1 - q);
      const b = Math.pow(1 - p, 2);
      return { style: { transform: `scale(${s.toFixed(4)})`,
        filter: b > 0.01 ? `blur(${(6 * b * k).toFixed(2)}px) brightness(${(1 + 0.22 * b).toFixed(3)})` : undefined } };
    }
    case "shake-cut": {
      const a = Math.pow(1 - p, 1.6);
      const amp = 30 * a * k;
      const x = (R(`shx${id}${rel}`) - 0.5) * 2 * amp;
      const y = (R(`shy${id}${rel}`) - 0.5) * 1.2 * amp;
      const rot = (R(`shr${id}${rel}`) - 0.5) * 1.6 * a;
      const s = 1 + 0.06 * Math.pow(1 - p, 0.8);
      return { style: {
        transform: `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px) rotate(${rot.toFixed(3)}deg) scale(${s.toFixed(4)})`,
        filter: `blur(${(1.4 * a * k).toFixed(2)}px) brightness(${(1 + (rel === 0 ? 0.22 : 0.06 * a)).toFixed(3)})`,
      } };
    }
    case "blur-dissolve": {
      const e = side === "out" ? easeInOutSine(p) : Math.pow(1 - easeOutCubic(p), 1.1);
      return { style: {
        transform: `scale(${(1 + 0.06 * e).toFixed(4)})`,
        filter: e > 0.01 ? `blur(${(20 * e * k).toFixed(2)}px) brightness(${(1 + 0.1 * e).toFixed(3)}) saturate(${(1 - 0.2 * e).toFixed(3)})` : undefined,
      } };
    }
    case "luma-fade": {
      // Dip through black with a luminance key feel: the shadows sink first,
      // the highlights hold on a beat longer.
      const e = side === "out" ? easeInOutSine(p) : 1 - easeOutCubic(p);
      return { style: {
        filter: e > 0.005 ? `brightness(${(1 - 0.97 * e).toFixed(3)}) contrast(${(1 + 0.6 * e).toFixed(3)}) saturate(${(1 - 0.3 * e).toFixed(3)})` : undefined,
      } };
    }
    default:
      return { style: {} };
  }
};

export const TransitionFrame: React.FC<{
  /** Stable id (the scene id), for SVG filter ids and per-scene variation. */
  id: string;
  /** The scene's own entrance (drawn from its first frame, the cut). */
  inT?: SceneTransition;
  /** The NEXT scene's entrance (drawn over this scene's last frames, before the cut). */
  outT?: SceneTransition;
  children: React.ReactNode;
}> = ({ id, inT, outT, children }) => {
  const frame = useCurrentFrame();
  const { durationInFrames, width, height } = useVideoConfig();
  const k = width / 1920;
  const safe = id.replace(/[^A-Za-z0-9_-]/g, "_");
  const fid = `tf-${safe}`;
  const state = transitionState(inT, outT, frame, durationInFrames);
  const look = state ? lookFor(state, safe, fid, k) : null;
  const region = look?.region || { x: -0.05, w: 1.1 };

  return (
    <AbsoluteFill style={{ overflow: "hidden", backgroundColor: "#000" }}>
      <svg width="0" height="0" style={{ position: "absolute", width: 0, height: 0 }} aria-hidden>
        {look?.filter ? (
          <filter id={fid} x={`${region.x * 100}%`} y="-5%" width={`${region.w * 100}%`} height="110%"
            colorInterpolationFilters="sRGB">
            {look.tile ? (
              <>
                {/* The frame itself as the tile (user space = the element's box, in px). */}
                <feOffset in="SourceGraphic" dx={0} dy={0} x={0} y={0} width={width} height={height} result="SRC0" />
                <feTile in="SRC0" result="SRC" />
              </>
            ) : (
              <feOffset in="SourceGraphic" dx={0} dy={0} result="SRC" />
            )}
            {look.filter}
          </filter>
        ) : null}
      </svg>
      <AbsoluteFill style={look?.style || undefined}>{children}</AbsoluteFill>
      {look?.over ? <AbsoluteFill style={{ pointerEvents: "none" }}>{look.over}</AbsoluteFill> : null}
    </AbsoluteFill>
  );
};
