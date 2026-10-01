import React from "react";
import { AbsoluteFill, Audio, Easing, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { SceneClip } from "./components/SceneClip";
import { BlurBackdrop } from "./components/AnimationScene";
import { KScale } from "./components/pro/ProGraphics";
import { Captions } from "./components/Captions";
import { MotionWrap } from "./components/MotionWrap";
import { resolveOverlay, templateFor } from "./templates";
import { OVERLAYS, accentFor } from "./overlays";
import type { Overlay, OverlayType, SceneMedia, TimelineProps } from "./types";
import sfxMeta from "./data/sfx_meta.json";   // a copy of public/sfx/sfx_meta.json (a test keeps them equal)
import { LookSoundContext, LookSounds, type LookSoundScope } from "./components/lib/LookSounds";
import { lookSoundsOn, planDocSounds, type SoundCue, type SoundTemplate } from "./components/lib/lookSoundPlan";

const PHOTO_CARDS = new Set<OverlayType>(["photo-card", "name-card"]);
// Case-file looks that show a still of the story when they were given no
// picture: the scene's own image, or a frame of its clip (the newspaper
// photo, the print on the board, the portrait on a facts card).
const STILL_LOOKS = new Set(["board", "clipping", "doc", "facts", "dossier", "window", "audio", "evidence"]);
const stillOf = (m?: SceneMedia | null) =>
  m && m.url ? (m.type === "image" ? m : m.thumbnail ? { ...m, type: "image" as const, url: m.thumbnail } : null) : null;

/** A look's built-in sound: its scope (LookSounds.tsx) and, for a registry design, the cues to play. */
type LookSound = { scope: LookSoundScope; cues: SoundCue[] | null };

/** A look with its sound: the scope around it (useLookSound reads it) and its registry design beside it. */
const withSound = (node: React.ReactNode, sound?: LookSound | null) => (sound ? (
  <LookSoundContext.Provider value={sound.scope}>
    {node}
    {sound.cues && sound.scope.on ? <LookSounds cues={sound.cues} /> : null}
  </LookSoundContext.Provider>
) : node);

const soundTemplate = (id?: string) => templateFor(id) as unknown as SoundTemplate | undefined;

/**
 * Every look's sound, from one pass over the document (lookSoundPlan.ts
 * planDocSounds: of two looks landing within half a second only the
 * stronger sounds; typing looks take the keyboards in turn), keyed
 * "o<index>" for an overlay and "s<index>" for an animation scene. Registry
 * designs play only on documents that carry lookSounds; a look that
 * schedules its own cues (useLookSound) plays on any document.
 */
const planLookSounds = (props: TimelineProps, fps: number): Record<string, LookSound> => {
  const out: Record<string, LookSound> = {};
  for (const p of planDocSounds(props, fps, soundTemplate)) {
    out[p.key] = { scope: { ...p.ctx, on: p.on, mode: p.state.mode }, cues: p.state.mode === "cues" ? p.design : null };
  }
  return out;
};

const renderOverlay = (raw: Overlay, accent: string, scenes: TimelineProps["scenes"], sound?: LookSound | null) => {
  // An overlay that names a template gets its unset fields from the
  // registry, so the editor's pick and the planner's draw the same way.
  let ov = resolveOverlay(raw);
  if (PHOTO_CARDS.has(ov.type) && !(ov.media && ov.media.length)) {
    // A photo or person card dropped on a scene borrows that scene's image.
    const under = scenes.find((s) => ov.startFrame >= s.startFrame && ov.startFrame < s.startFrame + s.durationInFrames);
    // On a clip, a frame of it (a person introduced over footage of them).
    const m = under ? stillOf(under.media) : null;
    if (m) ov = { ...ov, media: [m] };
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
    return withSound(
      <MotionWrap motion="fade" exit="fade" speed={1.6}>
        <BlurBackdrop still={still} frames={ov.durationInFrames} />
        <KScale.Provider value={scale}>
          <Component overlay={{ ...ov, fullFrame: true }} accent={accentFor(ov, accent)} />
        </KScale.Provider>
      </MotionWrap>, sound);
  }
  return withSound(
    <MotionWrap motion={ov.motion} exit={ov.exit} speed={ov.speed}
      placement={{ position: ov.position, scale: ov.scale, opacity: ov.opacity }}>
      <KScale.Provider value={scale}>
        <Component overlay={ov} accent={accentFor(ov, accent)} />
      </KScale.Provider>
    </MotionWrap>, sound);
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
  if (t && TEXT_CATEGORIES.has(t.category)) return 1.12;
  if (!t && ["typewriter", "word-type", "underline-title", "swoosh-title", "sentence-highlight", "quote", "kicker",
    "lower-third", "chapter", "title"].includes(ov.type)) return 1.12;
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
  // The editor's "Music level" (1 = the automatic mix under the voice). The
  // planner's sections used to ignore every editor setting, so the owner could
  // not turn the music up at all (2026-10-01).
  const gain = Math.max(0, Number(props.music?.gain ?? 1) || 0);
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
  // The editor's trim: music only between `from` and `to` (frames), faded over
  // 1.5 s at each end. Unset = the whole video.
  const from = Math.max(0, Number(props.music?.from ?? 0) || 0);
  const to = Math.min(total, Number(props.music?.to ?? total) || total);
  const trimmed = (f: number) => {
    if (f < from || f > to) return 0;
    return Math.min(1, (f - from) / ramp + (from > 0 ? 0 : 1), (to - f) / ramp + (to < total ? 0 : 1));
  };
  return (f: number) => {
    const level = levelAt(f) * (sections.length ? gain : 1) * trimmed(f);
    const on = speaking[Math.min(total, Math.max(0, Math.round(f)))] === 1;
    return Math.max(0, Math.min(1, on ? level * duck : level));
  };
};

/** Length and loudest point of every file in public/sfx (written with the files). */
const SFX_META = sfxMeta as Record<string, { duration: number; peak: number }>;
const SFX_MAX_SECONDS = 6;
// Sounds that can repeat seamlessly to cover a longer planned span.
const LOOPABLE_SFX = new Set(["keys", "typewriter", "keys-mech", "keys-type", "keys-laptop", "count-roll",
  "typewriter-clean"]);

type SfxCue = NonNullable<TimelineProps["sfx"]>[number];

const sfxNode = (fx: SfxCue, i: number, fps: number, master?: number) => {
  const fileFrames = Math.max(1, Math.ceil((SFX_META[fx.name]?.duration ?? 3) * fps));
  const planned = typeof fx.durationFrames === "number" && fx.durationFrames > 0 ? Math.ceil(fx.durationFrames) : 0;
  const frames = Math.max(1, Math.min(planned || fileFrames, Math.ceil(SFX_MAX_SECONDS * fps)));
  const start = Math.round(fx.startFrame || 0);
  // A sound planned to peak on frame 0-ish may start before the video does:
  // keep the timing by skipping its head instead of shifting it late.
  // The planner also skips a head so a sound's peak lands on its look's hit
  // without starting before the look is on screen (trimFrames).
  const trim = typeof fx.trimFrames === "number" && fx.trimFrames > 0 ? Math.round(fx.trimFrames) : 0;
  const skip = Math.max(start < 0 ? -start : 0, trim);
  const level = Math.max(0, Math.min(1, (Number(fx.volume) || 0) * (master ?? 1)));
  const cut = frames < fileFrames || (planned > 0 && LOOPABLE_SFX.has(fx.name));
  // A sound stopped before its own end fades over its last frames (no click).
  const fade = cut ? Math.max(1, Math.min(4, Math.floor(frames / 3))) : 0;
  const volume = fade
    ? (f: number) => level * Math.max(0, Math.min(1, (frames - skip - f) / fade))
    : level;
  return (
    <Sequence key={`sfx-${i}`} from={Math.max(0, start)} durationInFrames={Math.max(1, frames - skip)} layout="none">
      {/* Looped, the fade must count frames across every pass, not restart each loop. */}
      <Audio src={staticFile(`sfx/${fx.name}.mp3`)} volume={volume} trimBefore={skip || undefined}
        loop={LOOPABLE_SFX.has(fx.name) && frames > fileFrames ? true : undefined}
        loopVolumeCurveBehavior="extend" />
    </Sequence>
  );
};

/**
 * On a document whose looks carry their own sounds, the sfx rows that would
 * play a look's sound a second time: a row planned for an overlay (kind
 * "overlay", from an older planner or a pass that still writes one), and the
 * row an older editor adds when its per-overlay sound menu is touched - no
 * kind, starting on the overlay's first frame, playing that look's sound.
 */
const doublesLook = (overlays: Overlay[], sounds: Record<string, { scope: LookSoundScope }>) => {
  const own = new Map<number, Set<string>>();
  overlays.forEach((ov, i) => {
    if (!sounds[`o${i}`]) return;
    const names = own.get(ov.startFrame) || new Set<string>();
    const d = soundTemplate(ov.template)?.defaults;
    const main = d && typeof d.sfx === "object" && d.sfx ? d.sfx.name : typeof d?.sfx === "string" ? d.sfx : "";
    if (main) names.add(main);
    if (typeof ov.sfx === "string") names.add(ov.sfx);
    for (const c of d?.sounds || []) names.add(c.name);
    own.set(ov.startFrame, names);
  });
  return (fx: SfxCue) => fx.kind === "overlay"
    || (!fx.kind && Boolean(own.get(Math.round(fx.startFrame || 0))?.has(fx.name)));
};

/** Frames a "crossfade" scene takes to fade in over the previous one (0.5 s). */
const CROSSFADE_FRAMES = 15;

/** Fades its scene in over the one underneath (a true cross-dissolve). */
const CrossfadeIn: React.FC<{ active: boolean; children: React.ReactNode }> = ({ active, children }) => {
  const frame = useCurrentFrame();
  if (!active) return <>{children}</>;
  const opacity = interpolate(frame, [0, CROSSFADE_FRAMES], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.inOut(Easing.quad),
  });
  return <AbsoluteFill style={{ opacity }}>{children}</AbsoluteFill>;
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
  // The sound built into each look (LookSounds.tsx), from one pass over the document.
  const lookSounds = React.useMemo(
    () => planLookSounds(props, fps),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [overlays, scenes, props.lookSounds, props.meta, props.sfxEnabled, props.sfxVolume, fps]);
  const overlayNodes = React.useMemo(
    () => (overlays || []).map((ov, i) => renderOverlay(ov, captions.accent, scenes, lookSounds[`o${i}`])),
    [overlays, captions.accent, scenes, lookSounds]);
  // Built once per sfx list: each sound plays for its planned span (a typing
  // run lasts exactly as long as the letters appear) or, unplanned, for the
  // file's own length - never the old fixed 3 s that cut risers and typing.
  // When the looks carry their own sounds, a row planned for an overlay
  // would double its look's sound: only transitions and the editor's own play.
  const builtIn = lookSoundsOn(props);
  const sfxNodes = React.useMemo(() => {
    if (props.sfxEnabled === false) return [];
    const doubles = builtIn ? doublesLook(overlays || [], lookSounds) : () => false;
    return (props.sfx || []).map((fx, i) => (doubles(fx) ? null : sfxNode(fx, i, fps, props.sfxVolume)));
  }, [props.sfx, props.sfxEnabled, props.sfxVolume, fps, builtIn, overlays, lookSounds]);

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {/* Visual track — one clip per spoken clause */}
      {scenes.map((scene, i) => (
        <Sequence
          key={scene.id}
          from={scene.startFrame}
          // A cross-dissolve into the next scene: this one plays on underneath
          // for the length of the dissolve (the next scene is drawn on top).
          durationInFrames={scene.durationInFrames
            + (scenes[i + 1]?.transition === "crossfade" ? CROSSFADE_FRAMES : 0)}
          premountFor={premount}
        >
          {/* The next scene's transition starts over this scene's last frames. */}
          <CrossfadeIn active={scene.transition === "crossfade" && i > 0}>
            {/* A full-screen animation scene plays its look's own sound too. */}
            {withSound(<SceneClip scene={scene} accent={captions.accent} backdrop={backdrops[scene.id]}
              nextTransition={scenes[i + 1]?.transition} />, lookSounds[`s${i}`])}
          </CrossfadeIn>
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
      {sfxNodes}
    </AbsoluteFill>
  );
};
