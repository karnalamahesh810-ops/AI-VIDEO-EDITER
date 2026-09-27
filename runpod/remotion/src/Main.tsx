import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile, useVideoConfig } from "remotion";
import { SceneClip } from "./components/SceneClip";
import { Captions } from "./components/Captions";
import { MotionWrap } from "./components/MotionWrap";
import { resolveOverlay } from "./templates";
import { OVERLAYS, accentFor } from "./overlays";
import type { Overlay, OverlayType, SceneMedia, TimelineProps } from "./types";

const PHOTO_CARDS = new Set<OverlayType>(["photo-card", "name-card"]);

const renderOverlay = (raw: Overlay, accent: string, scenes: TimelineProps["scenes"]) => {
  // An overlay that names a template gets its unset fields from the
  // registry, so the editor's pick and the planner's draw the same way.
  let ov = resolveOverlay(raw);
  if (PHOTO_CARDS.has(ov.type) && !(ov.media && ov.media.length)) {
    // A photo or person card dropped on a scene borrows that scene's image.
    const under = scenes.find((s) => ov.startFrame >= s.startFrame && ov.startFrame < s.startFrame + s.durationInFrames);
    if (under && under.media.type === "image" && under.media.url) ov = { ...ov, media: [under.media] };
  }
  const Component = OVERLAYS[ov.type];
  // A document can arrive from the editor or an older schema, so an unknown
  // type is possible at runtime even though it is not at compile time.
  if (!Component) return null;
  return (
    <MotionWrap motion={ov.motion} exit={ov.exit} speed={ov.speed}
      placement={{ position: ov.position, scale: ov.scale, opacity: ov.opacity }}>
      <Component overlay={ov} accent={accentFor(ov, accent)} />
    </MotionWrap>
  );
};

/**
 * The music level at a frame: the section's mood level, ramped over 1.5 s at
 * each section change, and ducked under speech (a word is being spoken).
 */
const makeMusicVolume = (props: TimelineProps) => {
  const base = props.bgm?.volume ?? 0.12;
  const sections = props.music?.sections || [];
  const duck = props.music?.duck ?? 0.55;
  const fps = props.fps;
  const words: [number, number][] = [];
  for (const sc of props.scenes) {
    for (const w of sc.words || []) words.push([w.start, w.end]);
  }
  words.sort((a, b) => a[0] - b[0]);
  const ramp = Math.max(1, Math.round(fps * 1.5));
  const levelAt = (f: number): number => {
    if (!sections.length) return base;
    let level = sections[0].volume;
    for (const s of sections) {
      if (f >= s.startFrame) {
        const t = Math.min(1, (f - s.startFrame) / ramp);
        level = level + (s.volume - level) * t;
      }
    }
    return level;
  };
  return (f: number) => {
    const level = levelAt(f);
    const sec = f / fps;
    let speaking = false;
    for (const [a, b] of words) {
      if (a > sec + 0.15) break;
      if (sec >= a - 0.15 && sec <= b + 0.35) { speaking = true; break; }
    }
    return Math.max(0, Math.min(1, speaking ? level * duck : level));
  };
};

export const Main: React.FC<TimelineProps> = (props) => {
  const { scenes, overlays, audio, bgm, captions } = props;
  // Track toggles from the editor. Absent means on, so older timelines
  // render exactly as before.
  const showOverlays = props.overlaysEnabled !== false;
  // In the editor's Player, mount each clip this long before it appears so its
  // video has loaded by its first frame; without it every cut stalled on a
  // fresh download. Rendering ignores premounting.
  const { fps } = useVideoConfig();
  const premount = Math.round(fps * 2);
  // An animation scene's backdrop: the nearest clip of the story, blurred.
  const backdrops = React.useMemo(() => {
    const out: Record<string, SceneMedia | null> = {};
    const real = (i: number) => {
      const m = scenes[i]?.media;
      return m && m.url && (m.type === "video" || m.type === "image") ? m : null;
    };
    scenes.forEach((sc, i) => {
      if (sc.media?.type !== "animation") return;
      let pick: SceneMedia | null = null;
      for (let d = 1; d < scenes.length && !pick; d++) pick = real(i - d) || real(i + d);
      out[sc.id] = pick;
    });
    return out;
  }, [scenes]);

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {/* Visual track — one clip per spoken clause */}
      {scenes.map((scene) => (
        <Sequence
          key={scene.id}
          from={scene.startFrame}
          durationInFrames={scene.durationInFrames}
          premountFor={premount}
        >
          <SceneClip scene={scene} accent={captions.accent} backdrop={backdrops[scene.id]} />
        </Sequence>
      ))}

      {/* Caption track, burned in over the visuals but under the graphics */}
      {captions.enabled &&
        scenes.map((scene) => (
          <Sequence
            key={`cap-${scene.id}`}
            from={scene.startFrame}
            durationInFrames={scene.durationInFrames}
          >
            <Captions scene={scene} style={captions} />
          </Sequence>
        ))}

      {/* Overlay track — graphics sit on top of everything visual */}
      {showOverlays && (overlays || []).map((ov, i) => (
        <Sequence
          key={`ov-${i}`}
          from={ov.startFrame}
          durationInFrames={ov.durationInFrames}
          premountFor={premount}
        >
          {renderOverlay(ov, captions.accent, scenes)}
        </Sequence>
      ))}

      {/* Audio: narration drives the whole timeline; bgm sits well under it */}
      {audio?.url ? <Audio src={audio.url} volume={audio.volume ?? 1} /> : null}
      {bgm?.url ? (
        <Audio
          src={bgm.url.startsWith("bgm://") ? staticFile(`bgm/${bgm.url.slice(6)}.mp3`) : bgm.url}
          volume={makeMusicVolume(props)}
          loop
        />
      ) : null}
      {props.sfxEnabled !== false && (props.sfx || []).map((fx, i) => (
        <Sequence key={`sfx-${i}`} from={Math.max(0, fx.startFrame)} durationInFrames={90} layout="none">
          <Audio src={staticFile(`sfx/${fx.name}.mp3`)}
            volume={Math.max(0, Math.min(1, fx.volume * (props.sfxVolume ?? 1)))} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
