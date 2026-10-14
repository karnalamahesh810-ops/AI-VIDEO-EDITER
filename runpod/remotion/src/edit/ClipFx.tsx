import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { motionBlurAt, transformAt, type ClipKeyframes } from "./keyframes";
import {
  cleanClipFx, colourMatrix, filterOf, liveEffects, svgEffect, unsharpAmount,
  type ClipEffect, type ClipMask,
} from "./effects";

/**
 * A clip's own keyframes, effects stack, mask and motion blur (Editor v2): one wrapper around the clip's
 * picture, drawn after (outside) its look - the grade, treatment and effect SceneClip already gives it.
 * A scene with none of these draws its children as they are: an old document renders exactly as before.
 *
 * The layers, inside out (After Effects' order, near enough):
 *   effects   one CSS filter list on the picture, in the stack's order: brightness, contrast, saturation,
 *             exposure, blur and black & white are CSS functions (GPU-composited); temperature, tint, the
 *             warm / cool looks (colour matrices), sharpen (an unsharp mask), colour split and a clip's glow
 *             are SVG filters referenced by url(#...) in the same list. Grain (a frame-seeded feTurbulence drawn at half size) and the
 *             vignette (a radial gradient) are layers over the picture. A still's glow is a blurred,
 *             screen-blended copy of the still itself (cheap: the picture is already decoded); a video's is
 *             an SVG bloom on the same element (a second video element would decode the clip twice).
 *   mask      CSS masks (gradients, for a feather) or a clip-path (a hard edge) in the clip's own space, so
 *             it moves with the keys; inverted: a black shape over the clip instead.
 *   keys      one transform (translate, rotate, scale about the anchor) and an opacity.
 *   blur      a motion blur in screen space: an SVG Gaussian whose x / y deviation is the keyframed travel
 *             over the last frame times the shutter (keyframes.ts motionBlurAt); none when nothing moves.
 * Everything is a function of the frame number: no randomness, no timers.
 */
export const ClipFx: React.FC<{
  /** The scene (or layer) carrying keyframes / effects / mask / motionBlur. */
  fx: { id?: string; keyframes?: unknown; effects?: unknown; mask?: unknown; motionBlur?: unknown };
  /** True when the clip is a still picture (its glow can be a blurred copy). */
  still?: boolean;
  /** The look's own layers over the picture (SceneClip's EffectLayer, FilmLayer): they move, mask and filter with it. */
  over?: React.ReactNode;
  /** The clip's picture. */
  children: React.ReactNode;
}> = ({ fx, still = false, over, children }) => {
  const spec = React.useMemo(() => cleanClipFx(fx), [fx.keyframes, fx.effects, fx.mask, fx.motionBlur]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!spec) return <>{children}{over}</>;
  return <ClipFxDrawn id={fx.id || "clip"} keyframes={spec.keyframes} effects={spec.effects} mask={spec.mask}
    shutter={spec.motionBlur ?? 0} still={still} over={over}>{children}</ClipFxDrawn>;
};

const safeId = (id: string) => `cfx-${id.replace(/[^A-Za-z0-9_-]/g, "_")}`;
const pct = (v: number) => `${Math.round(v * 1e6) / 1e4}%`;

const ClipFxDrawn: React.FC<{
  id: string; keyframes?: ClipKeyframes; effects?: ClipEffect[]; mask?: ClipMask; shutter: number; still: boolean;
  over?: React.ReactNode; children: React.ReactNode;
}> = ({ id, keyframes, effects, mask, shutter, still, over, children }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const ids = safeId(id);
  const t = frame / fps;
  const scale = height / 1080;

  // ---- effects -----------------------------------------------------------------------------------
  const live = liveEffects(effects);
  const filter = live.length && effects ? filterOf(effects, ids, scale, still) : "";
  const svgDefs = effects ? effects.map((e, i) => (e.on === false || e.value === 0 || !svgEffect(e.type, still)) ? null
    : <EffectFilter key={i} id={`${ids}-${i}`} effect={e} scale={scale} />) : [];
  const glow = still ? live.find((e) => e.type === "glow") : undefined;
  const grain = live.find((e) => e.type === "grain");
  const vignette = live.find((e) => e.type === "vignette");

  let body: React.ReactNode = <>{children}{over}</>;
  if (filter || glow || grain || vignette) {
    body = (
      <AbsoluteFill style={{ filter: filter || undefined, isolation: "isolate" }}>
        {children}
        {over}
        {glow && (
          <AbsoluteFill style={{ filter: `blur(${Math.round((10 + 26 * glow.value) * scale)}px) brightness(${1 + 0.35 * glow.value})`,
            mixBlendMode: "screen", opacity: Math.min(1, 0.3 + 0.6 * glow.value) }}>
            {children}
          </AbsoluteFill>
        )}
        {vignette && <AbsoluteFill style={{ background: `radial-gradient(ellipse at 50% 50%, rgba(0,0,0,0) ${Math.round(72 - 42 * vignette.value)}%, rgba(0,0,0,${Math.min(0.95, 0.35 + 0.6 * vignette.value).toFixed(3)}) 100%)` }} />}
        {grain && <Grain id={`${ids}-grain`} value={grain.value} frame={frame} width={width} height={height} />}
      </AbsoluteFill>
    );
  }

  // ---- mask --------------------------------------------------------------------------------------
  if (mask) body = <Masked mask={mask} width={width} height={height}>{body}</Masked>;

  // ---- keys --------------------------------------------------------------------------------------
  if (keyframes) {
    const k = transformAt(keyframes, t);
    const moved = k.x !== 0 || k.y !== 0 || k.scale !== 1 || k.rotation !== 0;
    if (moved || k.opacity !== 1) {
      body = (
        <AbsoluteFill style={{
          transform: moved ? `translate(${(k.x * width).toFixed(2)}px, ${(k.y * height).toFixed(2)}px) rotate(${k.rotation.toFixed(3)}deg) scale(${k.scale.toFixed(5)})` : undefined,
          transformOrigin: `${pct(0.5 + k.anchorX)} ${pct(0.5 + k.anchorY)}`,
          opacity: k.opacity !== 1 ? k.opacity : undefined,
        }}>{body}</AbsoluteFill>
      );
    }
  }

  // ---- motion blur -------------------------------------------------------------------------------
  const mb = keyframes && shutter > 0 ? motionBlurAt(keyframes, t, fps, width, height, shutter) : { sx: 0, sy: 0 };
  const blurred = mb.sx > 0 || mb.sy > 0;
  if (blurred) body = <AbsoluteFill style={{ filter: `url(#${ids}-mb)` }}>{body}</AbsoluteFill>;

  const defs = svgDefs.some(Boolean) || blurred;
  return (
    <>
      {defs && (
        <svg width={0} height={0} style={{ position: "absolute", width: 0, height: 0, overflow: "hidden" }} aria-hidden>
          <defs>
            {svgDefs}
            {blurred && (
              <filter id={`${ids}-mb`} x="-5%" y="-5%" width="110%" height="110%" colorInterpolationFilters="sRGB">
                <feGaussianBlur stdDeviation={`${mb.sx} ${mb.sy}`} />
              </filter>
            )}
          </defs>
        </svg>
      )}
      {body}
    </>
  );
};

/** One SVG-drawn effect of the stack. */
const EffectFilter: React.FC<{ id: string; effect: ClipEffect; scale: number }> = ({ id, effect, scale }) => {
  const v = effect.value;
  switch (effect.type) {
    case "temperature": case "tint": case "lut-warm": case "lut-cool":
      return <filter id={id} colorInterpolationFilters="sRGB"><feColorMatrix type="matrix" values={colourMatrix(effect.type, v).join(" ")} /></filter>;
    case "sharpen": {
      // An unsharp mask: the picture plus `a` times (picture - its blur). Skia blurs fast on the CPU; a 3x3
      // feConvolveMatrix cost 3-4x a whole frame's drawing in software (the render machines have no GPU).
      const a = unsharpAmount(v);
      return (
        <filter id={id} colorInterpolationFilters="sRGB">
          <feGaussianBlur in="SourceGraphic" stdDeviation={Math.max(0.6, Math.round(1.1 * scale * 100) / 100)} result="soft" />
          <feComposite in="SourceGraphic" in2="soft" operator="arithmetic" k1={0} k2={1 + a} k3={-a} k4={0} />
        </filter>
      );
    }
    case "chromatic": {
      const d = Math.round(v * 10 * scale * 100) / 100;
      return (
        <filter id={id} colorInterpolationFilters="sRGB">
          <feColorMatrix in="SourceGraphic" type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="r" />
          <feOffset in="r" dx={d} dy={0} result="ro" />
          <feColorMatrix in="SourceGraphic" type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0" result="g" />
          <feColorMatrix in="SourceGraphic" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0" result="b" />
          <feOffset in="b" dx={-d} dy={0} result="bo" />
          <feBlend in="ro" in2="g" mode="screen" result="rg" />
          <feBlend in="rg" in2="bo" mode="screen" />
        </filter>
      );
    }
    case "glow": {
      // A video's bloom: its highlights blurred and screened back over it, one filter on the one element.
      const r = Math.round((8 + 22 * v) * scale * 100) / 100;
      const slope = (1.2 + 1.2 * v).toFixed(3), cut = (-0.45).toFixed(3);
      return (
        <filter id={id} colorInterpolationFilters="sRGB">
          <feGaussianBlur in="SourceGraphic" stdDeviation={r} result="b" />
          <feComponentTransfer in="b" result="hi">
            <feFuncR type="linear" slope={slope} intercept={cut} />
            <feFuncG type="linear" slope={slope} intercept={cut} />
            <feFuncB type="linear" slope={slope} intercept={cut} />
          </feComponentTransfer>
          <feBlend in="SourceGraphic" in2="hi" mode="screen" />
        </filter>
      );
    }
    default: return null;
  }
};

/**
 * Film grain: fractal noise seeded by the frame number (deterministic: the same frame always gets the same
 * grain), grey, overlay-blended. Drawn at half the frame's size and scaled up - a quarter of the pixels to
 * make, and a slightly coarser, filmic grain - with one octave of noise (half the work of two; at this
 * frequency the second octave is below a pixel anyway). Measured on the CPU, a tiled noise (feTile) cost
 * twice as much as this.
 */
const Grain: React.FC<{ id: string; value: number; frame: number; width: number; height: number }> = ({ id, value, frame, width, height }) => {
  const w = Math.max(2, Math.round(width / 2)), h = Math.max(2, Math.round(height / 2));
  return (
    <svg width={w} height={h} style={{ position: "absolute", left: 0, top: 0, transform: "scale(2)", transformOrigin: "0 0",
      opacity: Math.round((0.1 + 0.4 * value) * 1000) / 1000, mixBlendMode: "overlay", pointerEvents: "none" }} aria-hidden>
      <filter id={id} x="0" y="0" width="100%" height="100%" colorInterpolationFilters="sRGB">
        <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves={1} seed={(frame % 9973) + 1} />
        <feColorMatrix type="matrix" values="0.33 0.33 0.33 0 0  0.33 0.33 0.33 0 0  0.33 0.33 0.33 0 0  0 0 0 0 1" />
      </filter>
      <rect width="100%" height="100%" filter={`url(#${id})`} />
    </svg>
  );
};

/** The style that cuts an element to a mask shape (no `invert`: the shape itself). */
export const maskStyles = (m: ClipMask, width: number, height: number): React.CSSProperties[] => {
  const short = Math.min(width, height);
  const fx = (m.feather * short) / width, fy = (m.feather * short) / height;
  const x0 = m.x, y0 = m.y, x1 = m.x + m.w, y1 = m.y + m.h;
  if (m.feather <= 0) {
    if (m.shape === "ellipse") {
      return [{ clipPath: `ellipse(${pct(m.w / 2)} ${pct(m.h / 2)} at ${pct(x0 + m.w / 2)} ${pct(y0 + m.h / 2)})` }];
    }
    const round = m.shape === "roundrect" ? ` round ${Math.round((m.radius ?? 0.05) * short)}px` : "";
    return [{ clipPath: `inset(${pct(y0)} ${pct(1 - x1)} ${pct(1 - y1)} ${pct(x0)}${round})` }];
  }
  if (m.shape === "ellipse") {
    // Stops along the ellipse's radius: the edge in the middle of the feather.
    const radius = Math.max(1, Math.min(m.w * width, m.h * height) / 2);
    const f = (m.feather * short) / radius;
    const a = Math.max(0, 1 - f / 2), b = 1 + f / 2;
    const g = `radial-gradient(ellipse ${pct(m.w / 2)} ${pct(m.h / 2)} at ${pct(x0 + m.w / 2)} ${pct(y0 + m.h / 2)}, #000 ${pct(a)}, rgba(0,0,0,0) ${pct(b)})`;
    return [{ maskImage: g, WebkitMaskImage: g }];
  }
  // A rectangle: the product of a horizontal and a vertical ramp (two nested masks); a rounded one is also
  // clipped to its rounded outline, grown by half the feather so the soft edge is not cut.
  const ramp = (dir: "right" | "bottom", a: number, b: number, f: number) => {
    let s = a + f / 2, e = b - f / 2;
    if (s > e) s = e = (a + b) / 2;
    return `linear-gradient(to ${dir}, rgba(0,0,0,0) ${pct(a - f / 2)}, #000 ${pct(s)}, #000 ${pct(e)}, rgba(0,0,0,0) ${pct(b + f / 2)})`;
  };
  const h = ramp("right", x0, x1, fx), v = ramp("bottom", y0, y1, fy);
  const outer: React.CSSProperties = { maskImage: h, WebkitMaskImage: h };
  if (m.shape === "roundrect") {
    const r = Math.round((m.radius ?? 0.05) * short + (m.feather * short) / 2);
    outer.clipPath = `inset(${pct(y0 - fy / 2)} ${pct(1 - x1 - fx / 2)} ${pct(1 - y1 - fy / 2)} ${pct(x0 - fx / 2)} round ${r}px)`;
  }
  return [outer, { maskImage: v, WebkitMaskImage: v }];
};

const Masked: React.FC<{ mask: ClipMask; width: number; height: number; children: React.ReactNode }> = ({ mask, width, height, children }) => {
  const styles = maskStyles(mask, width, height);
  if (mask.invert) {
    // The clip outside the shape; inside it, the video's black.
    const shape = styles.reduceRight<React.ReactNode>((inner, s) => <AbsoluteFill style={s}>{inner}</AbsoluteFill>,
      <AbsoluteFill style={{ backgroundColor: "#000" }} />);
    return <AbsoluteFill>{children}{shape}</AbsoluteFill>;
  }
  return <>{styles.reduceRight<React.ReactNode>((inner, s) => <AbsoluteFill style={s}>{inner}</AbsoluteFill>, children)}</>;
};
