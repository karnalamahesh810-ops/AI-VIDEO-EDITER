import React from "react";
import {
  AbsoluteFill, OffthreadVideo, Video,
  useCurrentFrame, useVideoConfig,
} from "remotion";
import { FilmLayer, cssFilterFor } from "./FilmLayer";
import { EffectLayer, TransitionLayer, effectFilter, entranceStyle } from "./SceneEffects";
import { AnimationScene } from "./AnimationScene";
import { useSceneGrade } from "./Grade";
import { PlayerWindow } from "./pro/ProCase";
import { LivingPicture, StillPicture, TransitionFrame, resolveLiving } from "../transitions";
import { reframeStyle, resolveAim, resolveMove } from "./reframe";
import { BlurredHold, SafeImg } from "./motion/safePicture";
import type { Motion, Scene, SceneMedia, SceneTransition } from "../types";

/**
 * A scene's clip: Remotion's OffthreadVideo (frame-exact, decoded by Remotion's own compositor), or with
 * `html5` the browser's own video element - for a machine whose security blocks Remotion's unsigned compositor
 * (Windows Smart App Control on the owner's laptop, 2026-10-07). Sound always off: the narration is the sound.
 */
const ClipVideo: React.FC<{ src: string; style?: React.CSSProperties; playbackRate?: number; html5?: boolean }> = (
  { src, style, playbackRate, html5 }) => (html5
  ? <Video src={src} style={style} muted playbackRate={playbackRate} />
  : <OffthreadVideo src={src} style={style} muted playbackRate={playbackRate} />);

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
  const { durationInFrames, fps, width, height } = useVideoConfig();
  const { media, motion, treatment, transition, effect } = scene;
  // The video's grade (Grade.tsx): this picture's filter, first in its list,
  // and the SVG that defines it. Null for an ungraded document or scene.
  const grade = useSceneGrade(scene);

  const progress = durationInFrames > 1 ? frame / durationInFrames : 0;

  // Footage plays as it is, full frame, never zoomed or cropped (the owner:
  // GoMotion does not zoom into clips - a 6% crop on every clip and a 1.24x
  // cut-in halfway through long ones read as zooming) - except the planned
  // smart reframe (./reframe.ts, src/reframe.py): on a few locked-off shots
  // only, a slow push toward the subject, which stays in frame throughout
  // (the owner, 2026-10-01: "auto-zoom/crop onto the subject ... it feels
  // hand-edited"). Stills move with the
  // scene's own motion (timeline.py rotates it so neighbours differ); the
  // "ken-burns" effect only stands in when a still has no motion at all. It
  // used to be checked first, so every still in 7 of 8 style packs got the
  // same slow zoom-in and the rotation never showed. A still's motion is
  // aimed at its subject when the plan found one.
  const stillMotion: Motion | undefined =
    motion && motion !== "none" ? motion : effect === "ken-burns" ? "zoom-in" : undefined;

  if (media.type === "animation") {
    // The beat is a motion graphic, not a clip (VidRush's purple blocks).
    return (
      <TransitionFrame id={scene.id} inT={transition} outT={nextTransition}>
        <AnimationScene scene={scene} accent={accent || "#F2B544"} accent2={accent2} backdrop={backdrop} />
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

  // What a picture that cannot be drawn is replaced by, blurred - the first of these that can be: the shot
  // the check before the render chose (media.fallbackStill), the shot beside it, its own small copy (a
  // picture never stops a render: ./motion/safePicture.tsx).
  const near = backdrop && backdrop.url ? (backdrop.type === "image" ? backdrop.url : backdrop.thumbnail || "") : "";
  const holdStill = [media.fallbackStill || "", near, media.thumbnail || ""].filter((u) => u && u !== media.url);
  const hold = <BlurredHold still={holdStill} />;

  const entrance = entranceStyle(transition, frame);
  // A clip shorter than its scene used to run out and leave the rest of the
  // scene black (a real job: 3.48 s of footage in a 5.10 s scene). Slow it
  // just enough to fill the scene, never below 0.6x.
  // (useVideoConfig was called again here, after the early returns above - a
  // conditional hook. The values from the top of the component are the same.)
  const sceneSeconds = durationInFrames / fps;
  const clip = media.type === "video" ? media.clipSeconds ?? 0 : 0;
  const rate = clip > 0 && clip < sceneSeconds ? Math.max(0.6, clip / sceneSeconds) : 1;
  const filters = [grade?.filter, cssFilterFor(treatment), effectFilter(effect, frame), entrance.filter]
    .filter((f) => f && f !== "none")
    .join(" ");

  const fill: React.CSSProperties = {
    width: "100%",
    height: "100%",
    objectFit: "cover",
    filter: filters || undefined,
  };

  const split = media.split;
  if (scene.frame === "split" && media.type === "video" && split && split.url) {
    // The AI presenter style's split screen (the owner's reference channels: about a third of the
    // presenter's appearances): the presenter on the left, cropped on the face (focusX), the line's own
    // picture on the right with its slow move. Both full height, no border; the seam is the cut.
    const half: React.CSSProperties = { position: "relative", width: "50%", height: "100%", overflow: "hidden" };
    return (
      <TransitionFrame id={scene.id} inT={transition} outT={nextTransition}>
        <AbsoluteFill style={{ backgroundColor: "#000", flexDirection: "row" }}>
          {grade?.defs}
          <div style={half}>
            <ClipVideo src={media.url} playbackRate={rate} html5={media.html5}
              style={{ ...fill, objectPosition: `${split.focusX ?? 50}% 50%` }} />
          </div>
          <div style={half}>
            {split.type === "video" ? (
              <ClipVideo src={split.url} style={fill} html5={split.html5} />
            ) : (
              <StillPicture src={split.url} motion={split.motion || "zoom-in"} frame={frame}
                durationInFrames={durationInFrames} fps={fps} width={width / 2} filter={filters || undefined}
                fallbackStill={holdStill} />
            )}
          </div>
        </AbsoluteFill>
        <TransitionLayer transition={transition} />
      </TransitionFrame>
    );
  }

  if (scene.frame === "window") {
    // The case-file look: the footage plays inside a player window on the
    // desk (a recording, an interview, archive film shown as footage).
    const tone = scene.id.charCodeAt(scene.id.length - 1) % 2 ? "dark" : "light";
    const media100: React.CSSProperties = { width: "100%", height: "100%", objectFit: "cover",
      transform: media.type === "video" ? undefined : `scale(${1.02 + progress * 0.04})`, filter: filters || undefined };
    return (
      <TransitionFrame id={scene.id} inT={transition} outT={nextTransition}>
        <AbsoluteFill style={{ backgroundColor: "#000" }}>
          {grade?.defs}
          <PlayerWindow tone={tone} seed={scene.startFrame % 7}
            title={(scene.treatment === "archival" || scene.treatment === "vintage") ? "Archive film" : "Video player"}>
            {media.type === "video" ? (
              <ClipVideo src={media.url} style={media100} playbackRate={rate} html5={media.html5} />
            ) : (
              <SafeImg src={media.url} style={media100} fallback={hold} />
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
          {grade?.defs}
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
              <ClipVideo src={media.url} style={inset} playbackRate={rate} html5={media.html5} />
            ) : (
              <SafeImg src={media.url} style={inset} fallback={hold} />
            )}
          </AbsoluteFill>
          <FilmLayer treatment={treatment} />
          <TransitionLayer transition={transition} />
        </AbsoluteFill>
      </TransitionFrame>
    );
  }

  // The planned (or the editor's) move: one transform from the frame number
  // and the scene's own length (not the Sequence's, which a crossfade into
  // the next scene extends: the move holds its last framing under it).
  const move = resolveMove(scene, width / height);
  const aim = media.type === "image" && !move ? resolveAim(scene, width / height) : undefined;
  const moved = move ? reframeStyle(move, frame, scene.durationInFrames, fps) : null;
  // A still with depth layers (living photos, src/living.py): its own move, with parallax.
  // Held still, or framed by hand in the editor: drawn flat as before.
  const living = media.type === "image" && !move && stillMotion ? resolveLiving(scene) : null;

  return (
    <TransitionFrame id={scene.id} inT={transition} outT={nextTransition}>
      <AbsoluteFill style={{ overflow: "hidden", backgroundColor: "#000" }}>
        {grade?.defs}
        <AbsoluteFill
          style={{
            opacity: entrance.opacity ?? 1,
            transform: entrance.transform,
            clipPath: entrance.clipPath,
          }}
        >
          {media.type === "video" ? (
            moved ? (
              <AbsoluteFill style={moved}>
                <ClipVideo src={media.url} style={fill} playbackRate={rate} html5={media.html5} />
              </AbsoluteFill>
            ) : (
              <ClipVideo src={media.url} style={fill} playbackRate={rate} html5={media.html5} />
            )
          ) : moved ? (
            // A still the editor framed by hand: the boxes replace its motion.
            <AbsoluteFill style={moved}>
              <SafeImg src={media.url} style={fill} fallback={hold} />
            </AbsoluteFill>
          ) : living ? (
            <LivingPicture src={media.url} living={living} motion={stillMotion} frame={frame}
              durationInFrames={durationInFrames} fps={fps} width={width} height={height}
              filter={filters || undefined} subject={aim} fallbackStill={holdStill} />
          ) : (
            <StillPicture src={media.url} motion={stillMotion} frame={frame} durationInFrames={durationInFrames}
              fps={fps} width={width} filter={filters || undefined} subject={aim} fallbackStill={holdStill} />
          )}
        </AbsoluteFill>
        <EffectLayer effect={effect} durationInFrames={durationInFrames} />
        <FilmLayer treatment={treatment} />
        <TransitionLayer transition={transition} />
      </AbsoluteFill>
    </TransitionFrame>
  );
};
