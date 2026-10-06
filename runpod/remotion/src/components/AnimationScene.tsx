import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { OVERLAYS, accentFor } from "../overlays";
import { resolveOverlay, templateFor } from "../templates";
import { MotionWrap } from "./MotionWrap";
import { TransitionLayer } from "./SceneEffects";
import { SafeImg } from "./motion/safePicture";
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
/** The charcoal field a graphic sits on when there is no still to blur (or it cannot be drawn). */
const FIELD = "radial-gradient(ellipse at 50% 42%, #1b1c21 0%, #0e0e12 60%, #08080a 100%)";

/**
 * A still of the story's own footage, blurred, darkened and slowly pushing,
 * with a fine grid and a vignette: what a full-screen number or chart sits
 * on (an animation scene, or a full-screen overlay over its clip).
 */
export const BlurBackdrop: React.FC<{ still: string; frames: number }> = ({ still, frames }) => {
  const frame = useCurrentFrame();
  const { width } = useVideoConfig();
  const k = width / 1920;
  const drift = interpolate(frame, [0, Math.max(1, frames)], [0, 1], clamp);
  return (
    <AbsoluteFill style={{ backgroundColor: "#08080a", overflow: "hidden" }}>
      {still ? (
        <AbsoluteFill>
          <SafeImg src={still} fallback={<AbsoluteFill style={{ background: FIELD }} />} maxRetries={1}
            style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${1.18 + drift * 0.06})`,
            filter: "blur(16px) grayscale(0.4) brightness(0.55) contrast(1.05)" }} />
        </AbsoluteFill>
      ) : (
        <AbsoluteFill style={{ background: FIELD }} />
      )}
      <AbsoluteFill style={{ opacity: still ? 0.07 : 0.1,
        backgroundImage: "linear-gradient(rgba(255,255,255,.6) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.6) 1px, transparent 1px)",
        backgroundSize: `${72 * k}px ${72 * k}px`, transform: `translateY(${-drift * 24 * k}px)`,
        maskImage: "radial-gradient(ellipse at center, #000 30%, transparent 80%)",
        WebkitMaskImage: "radial-gradient(ellipse at center, #000 30%, transparent 80%)" }} />
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${280 * k}px rgba(0,0,0,.6)`, pointerEvents: "none" }} />
    </AbsoluteFill>
  );
};

export const AnimationScene: React.FC<{ scene: Scene; accent: string; accent2?: string; backdrop?: SceneMedia | null }> =
  ({ scene, accent, accent2, backdrop }) => {
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
      const caseLook = ["board", "clipping", "doc", "facts", "dossier", "window", "audio", "evidence"].includes(ov.variant || "")
        || Boolean(templateFor(ov.template)?.tags?.some((x) => x === "still" || x === "stills"));
      if ((photoCard && backdrop.type === "image") || (caseLook && still)) ov.media = [still || backdrop];
    }
    const Component = OVERLAYS[ov.type];
    const t = templateFor(ov.template);
    // Maps and the case-file looks (own-backdrop) draw their whole frame.
    const fullFrame = ov.type === "map" || t?.kind === "map" || Boolean(t?.tags?.includes("own-backdrop"));
    const col = accentFor(ov, accent, accent2);
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
                <SafeImg src={still} style={blurStyle} fallback={<AbsoluteFill style={{ background: FIELD }} />} />
              </AbsoluteFill>
            ) : (
              <AbsoluteFill style={{ background: FIELD }} />
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
