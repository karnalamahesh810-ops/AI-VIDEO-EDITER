import React from "react";
import { AbsoluteFill, Img, OffthreadVideo, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { OVERLAYS, accentFor } from "../overlays";
import { resolveOverlay, templateFor } from "../templates";
import { MotionWrap } from "./MotionWrap";
import { TransitionLayer } from "./SceneEffects";
import type { Overlay, Scene, SceneMedia } from "../types";

/**
 * A scene that IS a motion graphic: VidRush's purple timeline blocks. Where a
 * beat has no footage, or the line is a chart moment, the template draws
 * full-screen instead of a clip.
 *
 * The backdrop is the nearest clip of the story itself, blurred, darkened
 * and slowly pushing (VidRush puts its numbers over the darkened picture,
 * never over a flat colour); with no clip nearby, a charcoal grid. Maps bring
 * their own full-frame look and skip it.
 */
const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };

export const AnimationScene: React.FC<{ scene: Scene; accent: string; backdrop?: SceneMedia | null }> =
  ({ scene, accent, backdrop }) => {
    const frame = useCurrentFrame();
    const { width, height } = useVideoConfig();
    const k = width / 1920;
    const spec = (scene.animation || {}) as Partial<Overlay>;
    const ov = resolveOverlay({
      type: (spec.type || "typewriter") as Overlay["type"],
      text: spec.text || scene.text || "",
      startFrame: 0,
      durationInFrames: scene.durationInFrames,
      ...spec,
      fullFrame: true,
    } as Overlay);
    const Component = OVERLAYS[ov.type];
    const t = templateFor(ov.template);
    const fullFrame = ov.type === "map" || t?.kind === "map";
    const col = accentFor(ov, accent);
    const drift = interpolate(frame, [0, Math.max(1, scene.durationInFrames)], [0, 1], clamp);
    const bg = backdrop && backdrop.url && (backdrop.type === "video" || backdrop.type === "image") ? backdrop : null;
    const blurStyle: React.CSSProperties = {
      width: "100%", height: "100%", objectFit: "cover",
      transform: `scale(${1.18 + drift * 0.06})`,
      filter: "blur(22px) grayscale(0.55) brightness(0.38) contrast(1.1)",
    };

    return (
      <AbsoluteFill style={{ backgroundColor: "#08080a", overflow: "hidden" }}>
        {!fullFrame ? (
          <>
            {bg ? (
              <AbsoluteFill>
                {bg.type === "video" ? <OffthreadVideo src={bg.url} muted style={blurStyle} /> : <Img src={bg.url} style={blurStyle} />}
              </AbsoluteFill>
            ) : (
              <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 42%, #1b1c21 0%, #0e0e12 60%, #08080a 100%)" }} />
            )}
            {/* A fine grid (VidRush's dark chart cards), fading toward the edges. */}
            <AbsoluteFill style={{ opacity: bg ? 0.07 : 0.1,
              backgroundImage: "linear-gradient(rgba(255,255,255,.6) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.6) 1px, transparent 1px)",
              backgroundSize: `${72 * k}px ${72 * k}px`, transform: `translateY(${-drift * 24 * k}px)`,
              maskImage: "radial-gradient(ellipse at center, #000 30%, transparent 80%)",
              WebkitMaskImage: "radial-gradient(ellipse at center, #000 30%, transparent 80%)" }} />
            <AbsoluteFill style={{ boxShadow: `inset 0 0 ${320 * k}px rgba(0,0,0,.85)`, pointerEvents: "none" }} />
          </>
        ) : null}
        {Component ? (
          <MotionWrap motion={ov.motion} exit={ov.exit} speed={ov.speed}
            placement={{ position: ov.position, scale: ov.scale, opacity: ov.opacity }}>
            <Component overlay={ov} accent={col} />
          </MotionWrap>
        ) : null}
        <TransitionLayer transition={scene.transition} />
        {height ? null : null}
      </AbsoluteFill>
    );
  };
