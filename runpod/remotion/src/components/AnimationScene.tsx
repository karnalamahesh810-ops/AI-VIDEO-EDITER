import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { OVERLAYS, accentFor } from "../overlays";
import { resolveOverlay, templateFor } from "../templates";
import { MotionWrap } from "./MotionWrap";
import { TransitionLayer } from "./SceneEffects";
import type { Overlay, Scene } from "../types";

/**
 * A scene that IS a motion graphic: VidRush's purple timeline blocks. Where a
 * beat has no footage (or the editor chose an animation over a clip) the
 * template draws full-screen on a designed backdrop instead of a clip.
 *
 * The backdrop is what keeps these from reading as "text on black": two
 * slow-moving colour fields under a deep gradient, a faint perspective grid,
 * drifting light streaks, a vignette and an accent frame that draws in.
 * Maps bring their own full-frame look and skip it.
 */
const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };

const hexToRgb = (hex: string): [number, number, number] => {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
  return m ? [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)] : [214, 168, 60];
};

export const AnimationScene: React.FC<{ scene: Scene; accent: string }> = ({ scene, accent }) => {
  const frame = useCurrentFrame();
  const { width, height, fps } = useVideoConfig();
  const k = width / 1920;
  const spec = (scene.animation || {}) as Partial<Overlay>;
  const ov = resolveOverlay({
    type: (spec.type || "typewriter") as Overlay["type"],
    text: spec.text || scene.text || "",
    startFrame: 0,
    durationInFrames: scene.durationInFrames,
    ...spec,
  } as Overlay);
  const Component = OVERLAYS[ov.type];
  const t = templateFor(ov.template);
  const fullFrame = ov.type === "map" || t?.kind === "map";
  const col = accentFor(ov, accent);
  const [r, g, b] = hexToRgb(col);
  const tint = (a: number) => `rgba(${r},${g},${b},${a})`;
  const sec = frame / fps;
  const frameIn = interpolate(frame, [fps * 0.1, fps * 1.1], [0, 1], { ...clamp, easing: (x) => 1 - Math.pow(1 - x, 3) });
  const drift = interpolate(frame, [0, Math.max(1, scene.durationInFrames)], [0, 1], clamp);

  return (
    <AbsoluteFill style={{ backgroundColor: "#06060a", overflow: "hidden" }}>
      {!fullFrame ? (
        <>
          <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 40%, #16171f 0%, #0b0b10 55%, #06060a 100%)" }} />
          {/* Two colour fields, slowly circling: the "aurora" under the graphic. */}
          <div style={{ position: "absolute", width: width * 0.9, height: height * 0.9, borderRadius: "50%",
            left: width * (0.05 + 0.18 * Math.sin(sec * 0.25)), top: height * (-0.35 + 0.1 * Math.cos(sec * 0.2)),
            background: `radial-gradient(circle, ${tint(0.22)} 0%, ${tint(0.06)} 40%, rgba(0,0,0,0) 70%)`, filter: `blur(${40 * k}px)` }} />
          <div style={{ position: "absolute", width: width * 0.8, height: height * 0.8, borderRadius: "50%",
            left: width * (0.45 + 0.15 * Math.cos(sec * 0.18)), top: height * (0.45 + 0.12 * Math.sin(sec * 0.22)),
            background: "radial-gradient(circle, rgba(60,80,140,0.28) 0%, rgba(40,50,90,0.08) 45%, rgba(0,0,0,0) 70%)", filter: `blur(${50 * k}px)` }} />
          {/* Perspective grid, receding toward the horizon. */}
          <AbsoluteFill style={{ opacity: 0.14, transformOrigin: "50% 100%", transform: `perspective(${900 * k}px) rotateX(58deg) translateY(${drift * 40 * k}px)`,
            backgroundImage: "linear-gradient(rgba(255,255,255,.5) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.5) 1px, transparent 1px)",
            backgroundSize: `${110 * k}px ${110 * k}px`, top: "45%", height: "120%", maskImage: "linear-gradient(to top, rgba(0,0,0,.9), transparent)",
            WebkitMaskImage: "linear-gradient(to top, rgba(0,0,0,.9), transparent)" }} />
          {/* Light streaks drifting across. */}
          {[0, 1, 2].map((i) => (
            <div key={i} style={{ position: "absolute", top: `${18 + i * 26}%`, left: `${((sec * (4 + i * 2) + i * 37) % 140) - 20}%`,
              width: width * 0.32, height: 2 * k, background: `linear-gradient(90deg, transparent, rgba(255,255,255,${0.22 - i * 0.05}), transparent)`,
              transform: "rotate(-8deg)" }} />
          ))}
          {/* Accent frame: two corners draw in. */}
          <div style={{ position: "absolute", left: "4%", top: "8%", width: `${frameIn * 10}%`, height: 5 * k, background: col }} />
          <div style={{ position: "absolute", left: "4%", top: "8%", width: 5 * k, height: `${frameIn * 14}%`, background: col }} />
          <div style={{ position: "absolute", right: "4%", bottom: "10%", width: `${frameIn * 10}%`, height: 5 * k, background: col, opacity: 0.8 }} />
          <div style={{ position: "absolute", right: "4%", bottom: "10%", width: 5 * k, height: `${frameIn * 14}%`, background: col, opacity: 0.8 }} />
          <AbsoluteFill style={{ boxShadow: `inset 0 0 ${300 * k}px rgba(0,0,0,.8)`, pointerEvents: "none" }} />
        </>
      ) : null}
      {Component ? (
        <MotionWrap motion={ov.motion} exit={ov.exit} speed={ov.speed}
          // A small stat card made to ride on footage is scaled up when it IS the frame.
          placement={{ position: ov.position, scale: ov.scale ?? (t?.category === "NUMBERS" || t?.category === "CALLOUTS" ? 1.3 : 1), opacity: ov.opacity }}>
          <Component overlay={ov} accent={col} />
        </MotionWrap>
      ) : null}
      <TransitionLayer transition={scene.transition} />
    </AbsoluteFill>
  );
};
