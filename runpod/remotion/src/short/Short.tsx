import React from "react";
import { AbsoluteFill, OffthreadVideo, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { Main } from "../Main";
import { BlurredHold, SafeImg } from "../components/motion/safePicture";
import type { SceneMedia } from "../types";
import { HookTitle } from "./HookTitle";
import { ShortCaptions } from "./ShortCaptions";
import { STAGE_H, STAGE_W, bandRect, scenesIn, viewAt, type FrameSpan, type ShortProps } from "./shortLayout";

/**
 * A 9:16 Short (src/shorts.py makes the props): the long video's own picture - its "stage", the document
 * cut to the moment and drawn by Main at 1920x1080 inside a Sequence of that size - framed for a phone
 * shot by shot (shortLayout.ts: crop on the subject, or the whole picture in a band over a blurred copy of
 * the shot), a vertical source drawn straight into the frame, and on top the hook line and the captions.
 * The sound is the stage's: the narration slice, the music bed, the transition and look sounds.
 *
 * Every picture here goes through SafeImg (a picture never stops a render: components/motion/safePicture.tsx).
 */

const sceneSeconds = (frames: number, fps: number) => Math.max(0.04, frames / fps);

/** The rate a clip plays at to fill its scene (SceneClip's rule: slowed, never below 0.6x). */
const clipRate = (m: { type?: string; clipSeconds?: number }, frames: number, fps: number) => {
  const clip = m.type === "video" ? Number(m.clipSeconds || 0) : 0;
  const need = sceneSeconds(frames, fps);
  return clip > 0 && clip < need ? Math.max(0.6, clip / need) : 1;
};

type ShortMedia = SceneMedia & { previewUrl?: string | null; backdropStill?: boolean };

/**
 * Behind the fitted band: the shot itself, blurred and dimmed, filling the frame. Drawn small and scaled
 * up (the same look as a wide blur at a sixteenth of the work). A clip's backdrop plays its own file
 * (media.previewUrl: the light preview, or a copy - src/shorts.py _backdrop_copies), never the one the
 * stage draws on the same frame; without one it is the clip's still.
 */
const Backdrop: React.FC<{ media: ShortMedia; frames: number; opacity: number }> = ({ media, frames, opacity }) => {
  const { fps, width, height } = useVideoConfig();
  if (opacity <= 0.002 || !media || !media.url) return null;
  const k = 4;
  const w = Math.ceil(width / k) + 8;
  const h = Math.ceil(height / k) + 8;
  const fill: React.CSSProperties = { width: "100%", height: "100%", objectFit: "cover" };
  const still = media.type === "image" ? media.url : media.thumbnail || "";
  const own = media.type === "video" && !media.backdropStill && media.previewUrl ? media.previewUrl : "";
  return (
    <AbsoluteFill style={{ opacity, overflow: "hidden", backgroundColor: "#0b0c0f" }}>
      <div style={{
        position: "absolute", left: -16, top: -16, width: w, height: h, transformOrigin: "0 0",
        transform: `scale(${(width + 32) / (w - 8)})`, filter: "blur(7px) brightness(0.5) saturate(1.12)",
      }}>
        {own ? (
          <OffthreadVideo src={own} muted style={fill} playbackRate={clipRate(media, frames, fps)} />
        ) : still ? (
          <SafeImg src={still} style={fill} fallback={null} />
        ) : null}
      </div>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 45%, rgba(0,0,0,0) 35%, rgba(0,0,0,0.35) 100%)" }} />
    </AbsoluteFill>
  );
};

/** A vertical source drawn straight into the frame, centred on its subject. */
const NativeShot: React.FC<{ media: NonNullable<FrameSpan["media"]>; frames: number; cx: number; opacity: number }> = ({ media, frames, cx, opacity }) => {
  const { fps } = useVideoConfig();
  if (opacity <= 0.002 || !media || !media.url) return null;
  const fill: React.CSSProperties = {
    width: "100%", height: "100%", objectFit: "cover", objectPosition: `${Math.round(cx * 1000) / 10}% 50%`,
  };
  return (
    <AbsoluteFill style={{ opacity, backgroundColor: "#000", overflow: "hidden" }}>
      {media.type === "video" ? (
        <OffthreadVideo src={media.url} muted style={fill}
          playbackRate={clipRate(media, frames, fps)} />
      ) : (
        <SafeImg src={media.url} style={fill} fallback={<BlurredHold still={media.thumbnail || ""} />} />
      )}
    </AbsoluteFill>
  );
};

export const Short: React.FC<ShortProps> = (props) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const { stage, framing } = props;
  const scenes = stage.scenes || [];
  const fitScenes = React.useMemo(() => scenesIn(framing, "fit"), [framing]);
  const nativeScenes = React.useMemo(() => scenesIn(framing, "native"), [framing]);
  const native = React.useMemo(() => {
    const out: Record<number, { cx: number; media: NonNullable<FrameSpan["media"]> }> = {};
    for (const s of framing) {
      if (s.mode === "native" && typeof s.scene === "number" && s.media && s.media.url) out[s.scene] = { cx: s.cx, media: s.media };
    }
    return out;
  }, [framing]);
  const view = viewAt(framing, frame, width, height);
  const { rect } = view;
  const band = bandRect(width, height);
  const accent = props.accent || props.captions?.accent || "#F2B544";
  return (
    <AbsoluteFill style={{ backgroundColor: "#000", overflow: "hidden" }}>
      {/* The blurred shot behind the band, for the shots that are ever fitted. */}
      {scenes.map((sc, i) => (fitScenes.has(i) ? (
        <Sequence key={`bg-${sc.id}-${i}`} from={sc.startFrame} durationInFrames={sc.durationInFrames} layout="none">
          <Backdrop media={sc.media} frames={sc.durationInFrames} opacity={view.fit} />
        </Sequence>
      ) : null))}

      {/* The long video's own picture, framed. */}
      <div style={{
        position: "absolute", left: 0, top: 0, width: STAGE_W, height: STAGE_H, transformOrigin: "0 0",
        transform: `translate(${rect.x.toFixed(2)}px, ${rect.y.toFixed(2)}px) scale(${(rect.w / STAGE_W).toFixed(5)})`,
        overflow: "hidden",
      }}>
        <Sequence width={STAGE_W} height={STAGE_H} durationInFrames={stage.durationInFrames} name="Stage">
          <Main {...stage} />
        </Sequence>
      </div>
      {view.fit > 0.002 ? (
        // The band sits on the backdrop with a soft shadow, not a hard cut-out.
        <div style={{
          position: "absolute", left: 0, top: band.y, width: band.w, height: band.h, pointerEvents: "none",
          boxShadow: `0 ${Math.round(24 * view.fit)}px ${Math.round(70 * view.fit)}px rgba(0,0,0,${(0.55 * view.fit).toFixed(3)})`,
        }} />
      ) : null}

      {/* A vertical source fills the frame itself. */}
      {scenes.map((sc, i) => (nativeScenes.has(i) && native[i] ? (
        <Sequence key={`native-${sc.id}-${i}`} from={sc.startFrame} durationInFrames={sc.durationInFrames} layout="none">
          <NativeShot media={native[i].media} frames={sc.durationInFrames} cx={native[i].cx} opacity={view.native} />
        </Sequence>
      ) : null))}

      <HookTitle hook={props.hook} accent={accent} fit={view.fit} />
      {props.captions?.enabled ? <ShortCaptions words={props.captions.words || []} accent={accent} /> : null}
    </AbsoluteFill>
  );
};
