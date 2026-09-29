import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile, useVideoConfig } from "remotion";
import { SceneClip } from "./components/SceneClip";
import { BlurBackdrop } from "./components/AnimationScene";
import { KScale } from "./components/pro/ProGraphics";
import { Captions } from "./components/Captions";
import { MotionWrap } from "./components/MotionWrap";
import { resolveOverlay, templateFor } from "./templates";
import { OVERLAYS, accentFor } from "./overlays";
import type { Overlay, OverlayType, SceneMedia, TimelineProps } from "./types";

const PHOTO_CARDS = new Set<OverlayType>(["photo-card", "name-card"]);
// Case-file looks that show a still of the story when they were given no
// picture: the scene's own image, or a frame of its clip (the newspaper
// photo, the print on the board, the portrait on a facts card).
const STILL_LOOKS = new Set(["board", "clipping", "doc", "facts", "dossier", "window", "audio", "evidence"]);
const stillOf = (m?: SceneMedia | null) =>
  m && m.url ? (m.type === "image" ? m : m.thumbnail ? { ...m, type: "image" as const, url: m.thumbnail } : null) : null;

const renderOverlay = (raw: Overlay, accent: string, scenes: TimelineProps["scenes"]) => {
  // An overlay that names a template gets its unset fields from the
  // registry, so the editor's pick and the planner's draw the same way.
  let ov = resolveOverlay(raw);
  if (PHOTO_CARDS.has(ov.type) && !(ov.media && ov.media.length)) {
    // A photo or person card dropped on a scene borrows that scene's image.
    const under = scenes.find((s) => ov.startFrame >= s.startFrame && ov.startFrame < s.startFrame + s.durationInFrames);
    if (under && under.media.type === "image" && under.media.url) ov = { ...ov, media: [under.media] };
  }
  if (!(ov.media && ov.media.length)) {
    const v = ov.variant || "";
    const tags = templateFor(ov.template)?.tags || [];
    const at = scenes.findIndex((s) => ov.startFrame >= s.startFrame && ov.startFrame < s.startFrame + s.durationInFrames);
    if (v === "collage" || tags.includes("stills")) {
      // A burst of the story's own pictures: the stills of the scenes that follow.
      const pics: SceneMedia[] = [];
      for (let i = Math.max(0, at + 1); i < scenes.length && pics.length < 6; i++) {
        const m = stillOf(scenes[i].media);
        if (m && !pics.some((p) => p.url === m.url)) pics.push(m);
      }
      if (pics.length) ov = { ...ov, media: pics };
    } else if ((STILL_LOOKS.has(v) || tags.includes("still")) && at >= 0) {
      const m = stillOf(scenes[at].media);
      if (m) ov = { ...ov, media: [m] };
    }
  }
  const Component = OVERLAYS[ov.type];
  // A document can arrive from the editor or an older schema, so an unknown
  // type is possible at runtime even though it is not at compile time.
  if (!Component) return null;
  const scale = textScale(ov);
  if (ov.backdrop === "blur") {
    // Full screen for its moment only: a blurred still of the clip under it,
    // the graphic drawn as a full-frame scene; the clip keeps its slot.
    const under = scenes.find((s) => ov.startFrame >= s.startFrame && ov.startFrame < s.startFrame + s.durationInFrames);
    const m = under?.media;
    const still = m ? (m.type === "image" ? m.url : m.thumbnail || "") : "";
    return (
      <MotionWrap motion="fade" exit="fade" speed={1.6}>
        <BlurBackdrop still={still} frames={ov.durationInFrames} />
        <KScale.Provider value={scale}>
          <Component overlay={{ ...ov, fullFrame: true }} accent={accentFor(ov, accent)} />
        </KScale.Provider>
      </MotionWrap>
    );
  }
  return (
    <MotionWrap motion={ov.motion} exit={ov.exit} speed={ov.speed}
      placement={{ position: ov.position, scale: ov.scale, opacity: ov.opacity }}>
      <KScale.Provider value={scale}>
        <Component overlay={ov} accent={accentFor(ov, accent)} />
      </KScale.Provider>
    </MotionWrap>
  );
};

/**
 * How large an overlay draws (KScale, read by useK): the editor's text-size
 * setting when set, else a fifth larger for the text families (the owner:
 * the text went from too big to too small), else as designed.
 */
const TEXT_CATEGORIES = new Set(["TEXT", "HEADLINES", "QUOTES", "LOWER_THIRDS"]);
const textScale = (ov: Overlay): number => {
  if (typeof ov.fontScale === "number" && ov.fontScale > 0) return Math.max(0.6, Math.min(1.8, ov.fontScale));
  const t = templateFor(ov.template);
  if (t && TEXT_CATEGORIES.has(t.category)) return 1.2;
  if (!t && ["typewriter", "word-type", "underline-title", "swoosh-title", "sentence-highlight", "quote", "kicker",
    "lower-third", "chapter", "title"].includes(ov.type)) return 1.2;
  return 1;
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
  // Whether a word is being spoken, per frame (0.15 s before a word to 0.35 s
  // after it), built once. The Player evaluates this callback for EVERY frame of
  // the video whenever it changes, and it used to scan every word each time:
  // 0.2-0.45 s per preview frame on a 22-minute video, so the editor played at
  // a few frames a second.
  const total = Math.max(1, Math.ceil(props.durationInFrames));
  const speaking = new Uint8Array(total + 1);
  for (const sc of props.scenes) {
    for (const w of sc.words || []) {
      const a = Math.max(0, Math.ceil((w.start - 0.15) * fps));
      const b = Math.min(total, Math.floor((w.end + 0.35) * fps));
      for (let f = a; f <= b; f++) speaking[f] = 1;
    }
  }
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
    const on = speaking[Math.min(total, Math.max(0, Math.round(f)))] === 1;
    return Math.max(0, Math.min(1, on ? level * duck : level));
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
  // Stable across re-renders: a new volume function makes the Player re-run it
  // over the whole video.
  const musicVolume = React.useMemo(
    () => (bgm?.url ? makeMusicVolume(props) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [scenes, bgm?.url, bgm?.volume, props.music, props.fps, props.durationInFrames]);
  const overlayNodes = React.useMemo(
    () => (overlays || []).map((ov) => renderOverlay(ov, captions.accent, scenes)),
    [overlays, captions.accent, scenes]);

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
          {overlayNodes[i]}
        </Sequence>
      ))}

      {/* Audio: narration drives the whole timeline; bgm sits well under it */}
      {audio?.url ? <Audio src={audio.url} volume={audio.volume ?? 1} /> : null}
      {bgm?.url && musicVolume ? (
        <Audio
          src={bgm.url.startsWith("bgm://") ? staticFile(`bgm/${bgm.url.slice(6)}.mp3`) : bgm.url}
          volume={musicVolume}
          loop
          // A 12-minute bed under a 22-minute video: the ducking must follow the
          // video's frames, not restart with each loop of the track.
          loopVolumeCurveBehavior="extend"
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
