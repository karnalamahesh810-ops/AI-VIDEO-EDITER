import React from "react";
import { AbsoluteFill, Easing, interpolate, random, useCurrentFrame } from "remotion";
import type { SceneEffect, SceneTransition } from "../types";

/**
 * Transitions and per-clip effects, modelled on what VidRush's own timelines
 * carry: every clip has an effect (film grain, Ken Burns, light leaks, dust,
 * flicker, colour drift), while real transitions are reserved for roughly one
 * cut in four — Film Burn, Zoom, Glitch, Sliding Pan. Most cuts are hard cuts.
 *
 * A transition here is an entrance: it plays over the first frames of the
 * incoming scene rather than overlapping two sequences. That keeps every scene
 * a self-contained Sequence (so scenes still tile the narration exactly) while
 * reading on screen as the cut between them.
 *
 * Both lists are half a contract: they must match TRANSITIONS and EFFECTS in
 * src/timeline.py, and a test asserts they agree.
 */

const IN = 12; // frames an entrance transition lasts (0.4s at 30fps)

/** CSS transform/filter/opacity for the media during its entrance. */
export const entranceStyle = (
  t: SceneTransition | undefined,
  frame: number
): React.CSSProperties => {
  const p = interpolate(frame, [0, IN], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  switch (t) {
    case "fade":
      return { opacity: p };
    case "zoom":
      return {
        transform: `scale(${1.28 - 0.28 * p})`,
        filter: p < 1 ? `blur(${(1 - p) * 6}px)` : undefined,
      };
    case "slide":
      return { transform: `translateX(${(1 - p) * 100}%)` };
    case "glitch": {
      if (frame >= IN) return {};
      const jitter = (random(`gx${frame}`) - 0.5) * 60 * (1 - p);
      return {
        transform: `translateX(${jitter}px)`,
        filter: `hue-rotate(${Math.round(random(`gh${frame}`) * 90)}deg) saturate(1.6)`,
      };
    }
    default:
      return {};
  }
};

/** Full-frame layer drawn over the media for the entrance (flashes, bars). */
export const TransitionLayer: React.FC<{ transition?: SceneTransition }> = ({ transition }) => {
  const frame = useCurrentFrame();
  if (!transition || frame > IN + 4) return null;

  if (transition === "film-burn") {
    const o = interpolate(frame, [0, 3, IN + 4], [0.95, 0.85, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
    return (
      <AbsoluteFill
        style={{
          opacity: o,
          mixBlendMode: "screen",
          background:
            "radial-gradient(ellipse at 30% 50%, rgba(255,240,200,1) 0%, " +
            "rgba(255,140,40,0.95) 30%, rgba(200,40,0,0.6) 60%, rgba(0,0,0,0) 85%)",
        }}
      />
    );
  }

  if (transition === "glitch" && frame < IN) {
    const bars = [0, 1, 2, 3].map((i) => ({
      top: `${Math.floor(random(`gb${frame}-${i}`) * 90)}%`,
      height: `${2 + Math.floor(random(`gbh${frame}-${i}`) * 7)}%`,
      shift: (random(`gbs${frame}-${i}`) - 0.5) * 120,
    }));
    return (
      <AbsoluteFill style={{ pointerEvents: "none" }}>
        {bars.map((b, i) => (
          <div
            key={i}
            style={{
              position: "absolute",
              left: 0,
              right: 0,
              top: b.top,
              height: b.height,
              transform: `translateX(${b.shift}px)`,
              background: i % 2 ? "rgba(0,255,255,0.35)" : "rgba(255,0,80,0.35)",
              mixBlendMode: "screen",
            }}
          />
        ))}
      </AbsoluteFill>
    );
  }
  return null;
};

/** CSS filter contribution of a per-clip effect (combined with the grade). */
export const effectFilter = (e: SceneEffect | undefined, frame: number): string => {
  if (e === "color-shift") {
    const hue = Math.sin(frame / 45) * 8;
    return `hue-rotate(${hue.toFixed(2)}deg) saturate(1.08)`;
  }
  if (e === "film-flicker") {
    const b = 0.94 + random(`fl${Math.floor(frame / 2)}`) * 0.1;
    return `brightness(${b.toFixed(3)})`;
  }
  return "";
};

/** Full-duration overlay for effects that draw on top of the media. */
export const EffectLayer: React.FC<{ effect?: SceneEffect; durationInFrames: number }> = ({
  effect,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  if (!effect || effect === "none" || effect === "ken-burns") return null;

  if (effect === "light-leaks") {
    const p = durationInFrames > 1 ? frame / durationInFrames : 0;
    const x = 10 + p * 70;
    const o = 0.22 + Math.sin(frame / 18) * 0.08;
    return (
      <AbsoluteFill
        style={{
          pointerEvents: "none",
          mixBlendMode: "screen",
          opacity: o,
          background: `radial-gradient(ellipse at ${x}% 30%, rgba(255,170,80,0.9) 0%, ` +
            "rgba(255,90,40,0.35) 35%, rgba(0,0,0,0) 70%)",
        }}
      />
    );
  }

  if (effect === "dust") {
    // Reseeded every other frame; deterministic so renders are reproducible.
    const seed = Math.floor(frame / 2);
    const specks = Array.from({ length: 14 }, (_, i) => ({
      x: random(`dx${seed}-${i}`) * 100,
      y: random(`dy${seed}-${i}`) * 100,
      r: 1 + random(`dr${seed}-${i}`) * 2.5,
      o: 0.25 + random(`do${seed}-${i}`) * 0.5,
    }));
    return (
      <AbsoluteFill style={{ pointerEvents: "none" }}>
        <svg width="100%" height="100%">
          {specks.map((s, i) => (
            <circle key={i} cx={`${s.x}%`} cy={`${s.y}%`} r={s.r} fill={`rgba(255,255,255,${s.o})`} />
          ))}
        </svg>
      </AbsoluteFill>
    );
  }
  return null;
};
