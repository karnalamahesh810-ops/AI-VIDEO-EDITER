import React from "react";
import {
  AbsoluteFill, Img, OffthreadVideo,
  useCurrentFrame, useVideoConfig,
} from "remotion";
import { FilmLayer, cssFilterFor } from "./FilmLayer";
import { EffectLayer, TransitionLayer, effectFilter, entranceStyle } from "./SceneEffects";
import { AnimationScene } from "./AnimationScene";
import { PlayerWindow } from "./pro/ProCase";
import { StillPicture, TransitionFrame } from "../transitions";
import type { Motion, Scene, SceneMedia, SceneTransition } from "../types";

/**
 * One visual for one spoken clause.
 *
 * Cuts are hard by default. The previous version faded every scene in from
 * black over six frames, so every cut dipped to black — which reads as a
 * slideshow, not an edit. Transitions now happen only where the timeline asks
 * for one (see SceneEffects), and every clip carries one effect so borrowed
 * footage still feels designed.
 *
 * Cut transitions straddle the cut (../transitions): this scene draws its own
 * entrance from frame 0 and, given `nextTransition`, the first half of the
 * next scene's transition over its own last few frames.
 */
export const SceneClip: React.FC<{
  scene: Scene; accent?: string; accent2?: string; backdrop?: SceneMedia | null; nextTransition?: SceneTransition;
}> = ({ scene, accent, accent2, backdrop, nextTransition }) => {
  const frame = useCurrentFrame();
  const { durationInFrames, fps, width } = useVideoConfig();
  const { media, motion, treatment, transition, effect } = scene;

  const progress = durationInFrames > 1 ? frame / durationInFrames : 0;

  // Footage plays as it is, full frame, never zoomed or cropped (the owner:
  // GoMotion does not zoom into clips - a 6% crop on every clip and a 1.24x
  // cut-in halfway through long ones read as zooming). Stills move with the
  // scene's own motion (timeline.py rotates it so neighbours differ); the
  // "ken-burns" effect only stands in when a still has no motion at all. It
  // used to be checked first, so every still in 7 of 8 style packs got the
  // same slow zoom-in and the rotation never showed.
  const stillMotion: Motion | undefined =
    motion && motion !== "none" ? motion : effect === "ken-burns" ? "zoom-in" : undefined;

  if (media.type === "animation") {
    // The beat is a motion graphic, not a clip (VidRush's purple blocks).
    return (
      <TransitionFrame id={scene.id} inT={transition} outT={nextTransition}>
        <AnimationScene scene={scene} accent={accent || "#d6a83c"} accent2={accent2} backdrop={backdrop} />
      </TransitionFrame>
    );
  }

  if (media.type === "color" || !media.url) {
    // No clip and no image for this beat. Never a flat black hole: a subtle
    // dark gradient reads as a deliberately quiet background rather than a
    // broken frame, and lets a fallback text overlay (see
    // handler._fill_missing_media) actually sit on something.
    return (
      <TransitionFrame id={scene.id} inT={transition} outT={nextTransition}>
        <AbsoluteFill
          style={{
            background: "radial-gradient(ellipse at 50% 40%, #1b1c22 0%, #0a0a0d 75%)",
          }}
        />
      </TransitionFrame>
    );
  }

  const entrance = entranceStyle(transition, frame);
  // A clip shorter than its scene used to run out and leave the rest of the
  // scene black (a real job: 3.48 s of footage in a 5.10 s scene). Slow it
  // just enough to fill the scene, never below 0.6x.
  // (useVideoConfig was called again here, after the early returns above - a
  // conditional hook. The values from the top of the component are the same.)
  const sceneSeconds = durationInFrames / fps;
  const clip = media.type === "video" ? media.clipSeconds ?? 0 : 0;
  const rate = clip > 0 && clip < sceneSeconds ? Math.max(0.6, clip / sceneSeconds) : 1;
  const filters = [cssFilterFor(treatment), effectFilter(effect, frame), entrance.filter]
    .filter((f) => f && f !== "none")
    .join(" ");

  const fill: React.CSSProperties = {
    width: "100%",
    height: "100%",
    objectFit: "cover",
    filter: filters || undefined,
  };

  if (scene.frame === "window") {
    // The case-file look: the footage plays inside a player window on the
    // desk (a recording, an interview, archive film shown as footage).
    const tone = scene.id.charCodeAt(scene.id.length - 1) % 2 ? "dark" : "light";
    const media100: React.CSSProperties = { width: "100%", height: "100%", objectFit: "cover",
      transform: media.type === "video" ? undefined : `scale(${1.02 + progress * 0.04})`, filter: filters || undefined };
    return (
      <TransitionFrame id={scene.id} inT={transition} outT={nextTransition}>
        <AbsoluteFill style={{ backgroundColor: "#000" }}>
          <PlayerWindow tone={tone} seed={scene.startFrame % 7}
            title={(scene.treatment === "archival" || scene.treatment === "vintage") ? "Archive film" : "Video player"}>
            {media.type === "video" ? (
              <OffthreadVideo src={media.url} style={media100} muted playbackRate={rate} />
            ) : (
              <Img src={media.url} style={media100} />
            )}
            <FilmLayer treatment={treatment} />
          </PlayerWindow>
          <TransitionLayer transition={transition} />
        </AbsoluteFill>
      </TransitionFrame>
    );
  }

  if (scene.frame === "inset") {
    // VidRush's framing for archival photos, documents and low-resolution or
    // 4:3 footage: the media keeps its own shape, inset with a shadow on a
    // grainy deep-green field, instead of being cropped or upscaled to fill
    // 16:9. It is what makes a 320x240 newsreel look intentional.
    const inset: React.CSSProperties = {
      maxWidth: "74%",
      maxHeight: "80%",
      width: "auto",
      height: "auto",
      boxShadow: "0 22px 60px rgba(0,0,0,0.6)",
      transform: media.type === "video" ? undefined : `scale(${1 + progress * 0.05})`,
      filter: filters || undefined,
    };
    return (
      <TransitionFrame id={scene.id} inT={transition} outT={nextTransition}>
        <AbsoluteFill
          style={{
            background: "radial-gradient(ellipse at 50% 45%, #145c46 0%, #0b3a2c 70%, #072a20 100%)",
            justifyContent: "center",
            alignItems: "center",
            overflow: "hidden",
          }}
        >
          <svg width="100%" height="100%" style={{ position: "absolute", inset: 0, opacity: 0.22 }}>
            <filter id={`grain-${scene.id}`}>
              <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed={frame % 7} />
            </filter>
            <rect width="100%" height="100%" filter={`url(#grain-${scene.id})`} />
          </svg>
          <AbsoluteFill
            style={{
              justifyContent: "center",
              alignItems: "center",
              opacity: entrance.opacity ?? 1,
              transform: entrance.transform,
            }}
          >
            {media.type === "video" ? (
              <OffthreadVideo src={media.url} style={inset} muted playbackRate={rate} />
            ) : (
              <Img src={media.url} style={inset} />
            )}
          </AbsoluteFill>
          <FilmLayer treatment={treatment} />
          <TransitionLayer transition={transition} />
        </AbsoluteFill>
      </TransitionFrame>
    );
  }

  return (
    <TransitionFrame id={scene.id} inT={transition} outT={nextTransition}>
      <AbsoluteFill style={{ overflow: "hidden", backgroundColor: "#000" }}>
        <AbsoluteFill
          style={{
            opacity: entrance.opacity ?? 1,
            transform: entrance.transform,
            clipPath: entrance.clipPath,
          }}
        >
          {media.type === "video" ? (
            <OffthreadVideo src={media.url} style={fill} muted playbackRate={rate} />
          ) : (
            <StillPicture src={media.url} motion={stillMotion} frame={frame} durationInFrames={durationInFrames}
              fps={fps} width={width} filter={filters || undefined} />
          )}
        </AbsoluteFill>
        <EffectLayer effect={effect} durationInFrames={durationInFrames} />
        <FilmLayer treatment={treatment} />
        <TransitionLayer transition={transition} />
      </AbsoluteFill>
    </TransitionFrame>
  );
};
