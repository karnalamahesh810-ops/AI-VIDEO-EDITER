import React from "react";
import { AbsoluteFill, Easing, interpolate, random, useCurrentFrame } from "remotion";
import type { SceneEffect, SceneTransition } from "../types";
import { isCutTransition } from "../transitions/timing";

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
 *
 * The editor-grade cut transitions (flash, chromatic-flash, glitch, vhs-glitch,
 * film-burn, light-leak, whip-pan, zoom-punch, shake-cut, blur-dissolve,
 * luma-fade) live in ../transitions and straddle the cut; this file keeps the
 * older entrance-only moves (fade, zoom, slide, whip, dip, blur, punch, the
 * wipes, mosaic, colour wash).
 */

const IN = 12; // frames an entrance transition lasts (0.4s at 30fps)

/** CSS transform/filter/opacity for the media during its entrance. */
export const entranceStyle = (
  t: SceneTransition | undefined,
  frame: number
): React.CSSProperties => {
  if (isCutTransition(t)) return {};   // drawn by TransitionFrame
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
    case "whip":
      // A fast horizontal whip: the frame arrives smeared and settles.
      return {
        transform: `translateX(${(1 - p) * 35}%)`,
        filter: p < 1 ? `blur(${(1 - p) * 18}px)` : undefined,
      };
    case "dip":
      return { opacity: interpolate(frame, [0, 3, IN], [0, 0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) };
    case "blur":
      return { filter: p < 1 ? `blur(${(1 - p) * 14}px) brightness(${1 + (1 - p) * 0.25})` : undefined };
    case "punch":
      // A quick punch-in that lands on the beat.
      return { transform: `scale(${1.12 - 0.12 * p})` };
    case "split-wipe":
      // Barn doors: the incoming shot opens from the centre line outward.
      return { clipPath: `inset(0 ${(1 - p) * 50}% 0 ${(1 - p) * 50}%)` };
    case "bar-wipe":
      // Revealed left to right behind a coloured bar (TransitionLayer).
      return { clipPath: `inset(0 ${(1 - p) * 100}% 0 0)` };
    case "color-wash":
      return { filter: p < 1 ? `saturate(${0.2 + 0.8 * p}) brightness(${1.35 - 0.35 * p})` : undefined };
    default:
      return {};
  }
};

/** Full-frame layer drawn over the media for the entrance (flashes, bars). */
export const TransitionLayer: React.FC<{ transition?: SceneTransition }> = ({ transition }) => {
  const frame = useCurrentFrame();
  if (!transition || frame > IN + 4 || isCutTransition(transition)) return null;

  if (transition === "bar-wipe" && frame <= IN) {
    // The bar leads the reveal by a hair so the edge never shows a seam.
    const x = interpolate(frame, [0, IN], [0, 100], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
    return (
      <AbsoluteFill style={{ pointerEvents: "none" }}>
        <div style={{ position: "absolute", top: 0, bottom: 0, left: `${x}%`, width: "3.5%",
          transform: "translateX(-60%)", background: "#f4a100", boxShadow: "0 0 40px rgba(244,161,0,0.7)" }} />
      </AbsoluteFill>
    );
  }

  if (transition === "mosaic" && frame < IN + 2) {
    // A grid of tiles that clear in a fixed random order: a pixel mosaic
    // resolving into the shot. Deterministic, so renders are reproducible.
    const cols = 16, rows = 9;
    const p = frame / (IN + 2);
    const tiles: React.ReactNode[] = [];
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const order = random(`mz${r}-${c}`);
        if (order < p) continue;
        const tone = 30 + Math.floor(random(`mt${r}-${c}`) * 60);
        tiles.push(
          <div key={`${r}-${c}`} style={{ position: "absolute", left: `${(c / cols) * 100}%`, top: `${(r / rows) * 100}%`,
            width: `${100 / cols + 0.1}%`, height: `${100 / rows + 0.1}%`, background: `rgb(${tone},${tone},${tone + 8})` }} />,
        );
      }
    }
    return <AbsoluteFill style={{ pointerEvents: "none" }}>{tiles}</AbsoluteFill>;
  }

  if (transition === "color-wash") {
    const o = interpolate(frame, [0, 3, IN + 4], [0.85, 0.7, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
    return <AbsoluteFill style={{ background: "#1f5fd6", mixBlendMode: "screen", opacity: o, pointerEvents: "none" }} />;
  }

  if (transition === "split-wipe" && frame <= IN) {
    // Thin light seams on the two opening edges so the doors read as doors.
    const p = interpolate(frame, [0, IN], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) });
    const edge = (1 - p) * 50;
    const seam: React.CSSProperties = { position: "absolute", top: 0, bottom: 0, width: 4, background: "rgba(255,255,255,0.85)" };
    return (
      <AbsoluteFill style={{ pointerEvents: "none", opacity: 1 - p }}>
        <div style={{ ...seam, left: `${edge}%` }} />
        <div style={{ ...seam, right: `${edge}%` }} />
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
    // Flicker around full brightness, never below it.
    const b = 1.0 + random(`fl${Math.floor(frame / 2)}`) * 0.05;
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
