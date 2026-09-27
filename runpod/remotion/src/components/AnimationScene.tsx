import React from "react";
import { AbsoluteFill, Img, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
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
    if (!(ov.media && ov.media.length) && backdrop && backdrop.url) {
      // A photo card borrows the nearest image; the case-file looks take a
      // still of the nearest clip too (the board print, the newspaper photo).
      const still = backdrop.type === "image" ? backdrop
        : backdrop.thumbnail ? { ...backdrop, type: "image" as const, url: backdrop.thumbnail } : null;
      const photoCard = ov.type === "photo-card" || ov.type === "name-card";
      const caseLook = ["board", "clipping", "doc", "facts", "dossier", "window", "audio", "evidence"].includes(ov.variant || "");
      if ((photoCard && backdrop.type === "image") || (caseLook && still)) ov.media = [still || backdrop];
    }
    const Component = OVERLAYS[ov.type];
    const t = templateFor(ov.template);
    // Maps and the case-file looks (own-backdrop) draw their whole frame.
    const fullFrame = ov.type === "map" || t?.kind === "map" || Boolean(t?.tags?.includes("own-backdrop"));
    const col = accentFor(ov, accent);
    const drift = interpolate(frame, [0, Math.max(1, scene.durationInFrames)], [0, 1], clamp);
    // A still of the neighbouring clip (its thumbnail), never a second video
    // decode of it: two OffthreadVideos on one file at different times made
    // Remotion's compositor miss frames ("No frame found at position") and
    // blurred to 22 px a still is indistinguishable.
    const still = backdrop ? (backdrop.type === "image" ? backdrop.url : (backdrop.thumbnail || "")) : "";
    const blurStyle: React.CSSProperties = {
      width: "100%", height: "100%", objectFit: "cover",
      transform: `scale(${1.18 + drift * 0.06})`,
      filter: "blur(16px) grayscale(0.4) brightness(0.55) contrast(1.05)",
    };

    return (
      <AbsoluteFill style={{ backgroundColor: "#08080a", overflow: "hidden" }}>
        {!fullFrame ? (
          <>
            {still ? (
              <AbsoluteFill>
                <Img src={still} style={blurStyle} />
              </AbsoluteFill>
            ) : (
              <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 42%, #1b1c21 0%, #0e0e12 60%, #08080a 100%)" }} />
            )}
            {/* A fine grid (VidRush's dark chart cards), fading toward the edges. */}
            <AbsoluteFill style={{ opacity: still ? 0.07 : 0.1,
              backgroundImage: "linear-gradient(rgba(255,255,255,.6) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.6) 1px, transparent 1px)",
              backgroundSize: `${72 * k}px ${72 * k}px`, transform: `translateY(${-drift * 24 * k}px)`,
              maskImage: "radial-gradient(ellipse at center, #000 30%, transparent 80%)",
              WebkitMaskImage: "radial-gradient(ellipse at center, #000 30%, transparent 80%)" }} />
            <AbsoluteFill style={{ boxShadow: `inset 0 0 ${280 * k}px rgba(0,0,0,.6)`, pointerEvents: "none" }} />
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
