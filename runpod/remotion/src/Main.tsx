import React from "react";
import { AbsoluteFill, Audio, Easing, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { SceneClip } from "./components/SceneClip";
import { BlurBackdrop } from "./components/AnimationScene";
import { KScale } from "./components/pro/ProGraphics";
import { CaptionTrack } from "./components/Captions";
import { CaptionsOn } from "./components/layout";
import { MotionWrap } from "./components/MotionWrap";
import { motionClass } from "./components/motion/lookClass";
import { StageFx, stageWindows } from "./components/motion/stage";
import { sceneAvoid, sceneBusy } from "./components/motion/avoid";
import { PictureGuard } from "./components/motion/pictureGuard";
import { resolveOverlay, templateFor } from "./templates";
import { OVERLAYS, accentFor } from "./overlays";
import type { Overlay, OverlayType, SceneMedia, TimelineProps } from "./types";
import sfxMeta from "./data/sfx_meta.json";   // a copy of public/sfx/sfx_meta.json (a test keeps them equal)
import { LookSoundContext, LookSounds, type LookSoundScope } from "./components/lib/LookSounds";
import { lookSoundsOn, planDocSounds, type SoundCue, type SoundTemplate } from "./components/lib/lookSoundPlan";
import { PackTransitions } from "./transitions/PackTransition";
import { GradeContext, gradeStateFor } from "./components/Grade";
import { ambienceSettings, bedPasses, bedVolume, passGain, speechCurve, type Ambience, type Bed }
  from "./components/ambienceMix";
import { BrandVideo, EndCard, Watermark } from "./components/brand/BrandLayers";
import { brandFrames, brandOf } from "./components/brand/brandLayout";
import { musicPasses, musicVolume as makeMusicVolume, trackSeconds } from "./components/musicMix";

// The music beds were replaced by the owner's own tracks (2026-10-01); a
// document planned before names the old bed, which no longer ships (its 404
// failed the whole render: "Could not play audio ... investigative.mp3").
const BGM_RENAMED: Record<string, string> = {
  investigative: "investigative-v5", suspense: "suspense-v2", crime: "crime-v1",
};
/** The bundled track a "bgm://<name>" link plays (an old bed's name = the track that replaced it). */
export const bgmTrack = (name: string): string => BGM_RENAMED[name] ?? name;
export const bgmFile = (name: string): string => `bgm/${bgmTrack(name)}.mp3`;

const PHOTO_CARDS = new Set<OverlayType>(["photo-card", "name-card"]);
// Case-file looks that show a still of the story when they were given no
// picture: the scene's own image, or a frame of its clip (the newspaper
// photo, the print on the board, the portrait on a facts card).
const STILL_LOOKS = new Set(["board", "clipping", "doc", "facts", "dossier", "window", "audio", "evidence"]);
const stillOf = (m?: SceneMedia | null) =>
  m && m.url ? (m.type === "image" ? m : m.thumbnail ? { ...m, type: "image" as const, url: m.thumbnail } : null) : null;

/**
 * The editor's Player draws this composition inside the app's page, whose
 * global CSS (Tailwind's preflight: img, video { max-width: 100%; height:
 * auto }) clamped every picture to its box. A look that shows a strip of a
 * full-frame photo (an image wider than its strip, shifted left: the split
 * panels, the triptych slices) shrank the photo into the first strip and
 * left the others dark - the owner's "empty slots" in the Lake Powell video
 * (2026-10-01). The render has no such sheet; this puts the preview back to
 * the browser defaults every look is drawn for.
 */
const PAGE_CSS_GUARD = ".tg-composition img, .tg-composition video { max-width: none; max-height: none; }";

// Looks about a person show the picture of their own scene only: a
// neighbour's could be someone else.
const PERSON_CUES = new Set(["person", "person-full", "profile"]);
const SUBJECT_STOP = new Set(["the", "and", "for", "with", "from", "this", "that", "its", "their", "over", "into",
  "near", "about"]);
const subjectWords = (s?: string): Set<string> =>
  new Set(((s || "").toLowerCase().match(/[a-z0-9]{3,}/g) || []).filter((w) => !SUBJECT_STOP.has(w)));
/** Two subjects name the same thing: most of the shorter one's words are in the other (src/treatments.py same_subject). */
const sameSubject = (a?: string, b?: string): boolean => {
  const wa = subjectWords(a), wb = subjectWords(b);
  if (!wa.size || !wb.size) return false;
  let both = 0;
  wa.forEach((w) => { if (wb.has(w)) both += 1; });
  return both >= Math.max(1, Math.ceil((3 * Math.min(wa.size, wb.size)) / 5));
};
const PICTURE_NEAR = 8;

/**
 * The pictures an image look shows, as stills (a clip lends its frame), or
 * null for a look that shows none. In order: its own pictures, the scenes the
 * planner chose (mediaFrom), the library's (source "library"). A look the
 * planner did not fill (an older document, the editor's own) borrows: the
 * scene under it, then nearby scenes about the same subject, and a
 * several-picture look the scenes that follow. Never an empty slot: a look
 * with no picture draws nothing, one with fewer repeats or folds its slots.
 */
const lookPictures = (ov: Overlay, scenes: TimelineProps["scenes"]): SceneMedia[] | null => {
  const v = ov.variant || "";
  const t = templateFor(ov.template);
  const tags = t?.tags || [];
  const many = v === "collage" || tags.includes("stills");
  if (!many && !(PHOTO_CARDS.has(ov.type) || STILL_LOOKS.has(v) || tags.includes("still"))) return null;
  const person = ov.type === "name-card" || ((t as { cues?: string[] } | undefined)?.cues || []).some((c) => PERSON_CUES.has(c));
  const out: SceneMedia[] = [];
  const add = (m?: SceneMedia | null) => {
    const s = stillOf(m);
    if (s && !out.some((p) => p.url === s.url)) out.push(s);
  };
  const own = (Array.isArray(ov.media) ? ov.media : []).filter((m): m is SceneMedia => !!m && typeof m === "object");
  own.filter((m) => m.source !== "library").forEach(add);
  (Array.isArray(ov.mediaFrom) ? ov.mediaFrom : []).forEach((id) => add(scenes.find((s) => s.id === id)?.media));
  own.filter((m) => m.source === "library").forEach(add);
  if (!out.length || (many && out.length < 2)) {
    const at = scenes.findIndex((s) => ov.startFrame >= s.startFrame && ov.startFrame < s.startFrame + s.durationInFrames);
    if (at >= 0) {
      add(scenes[at].media);
      const subject = scenes[at].semanticMetadata?.subject;
      for (let d = 1; !person && d <= PICTURE_NEAR && out.length < (many ? 6 : 1); d++) {
        for (const j of [at - d, at + d]) {
          if (j >= 0 && j < scenes.length && sameSubject(subject, scenes[j].semanticMetadata?.subject)) add(scenes[j].media);
        }
      }
      // A burst of the story's own pictures: the stills of the scenes that follow.
      for (let i = at + 1; many && i < scenes.length && out.length < 6; i++) add(scenes[i].media);
    }
  }
  return out.slice(0, many ? 6 : Math.max(1, own.length));
};

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

export const renderOverlay = (raw: Overlay, accent: string, scenes: TimelineProps["scenes"], sound?: LookSound | null,
  accent2?: string) => {
  // An overlay that names a template gets its unset fields from the
  // registry, so the editor's pick and the planner's draw the same way.
  let ov = resolveOverlay(raw);
  // An image look's pictures, every slot a real picture (lookPictures): the
  // planner's, else the scene's own (on a clip, a frame of it), else its
  // neighbours' about the same subject.
  const pics = lookPictures(ov, scenes);
  if (pics) ov = { ...ov, media: pics };
  const Component = OVERLAYS[ov.type];
  // A document can arrive from the editor or an older schema, so an unknown
  // type is possible at runtime even though it is not at compile time.
  if (!Component) return null;
  // Somebody else's graphics and the faces on the picture under the look (a station logo, a chyron, a
  // face): a look that places its words keeps them out of these (components/motion/avoid.ts).
  if (!ov.avoid) {
    const avoid = sceneAvoid(ov, scenes);
    if (avoid.length) ov = { ...ov, avoid };
  }
  // Words over busy footage (a detailed map, lettering in the picture) sit on a slim blurred panel instead of
  // a soft shade (the kinetic type looks read overlay.backing; the planner's choice wins when it made one).
  if (/^kt-/.test(ov.variant || "") && !(ov as { backing?: string }).backing && sceneBusy(ov, scenes)) {
    ov = { ...ov, backing: "panel" } as Overlay;
  }
  const scale = textScale(ov);
  const klass = motionClass(ov);
  if (ov.backdrop === "blur") {
    // Full screen for its moment only: a blurred still of the clip under it,
    // the graphic drawn as a full-frame scene; the clip keeps its slot.
    const under = scenes.find((s) => ov.startFrame >= s.startFrame && ov.startFrame < s.startFrame + s.durationInFrames);
    const m = under?.media;
    const still = m ? (m.type === "image" ? m.url : m.thumbnail || "") : "";
    return withSound(
      <MotionWrap motion="fade" exit="fade" klass="full">
        <BlurBackdrop still={still} frames={ov.durationInFrames} />
        <KScale.Provider value={scale}>
          <Component overlay={{ ...ov, fullFrame: true }} accent={accentFor(ov, accent, accent2)} />
        </KScale.Provider>
      </MotionWrap>, sound);
  }
  const hot = accentFor(ov, accent, accent2);
  // An image look draws only pictures that load; when none does it is drawn as the scene's own picture,
  // blurred, with the look's words (components/motion/pictureGuard.tsx) - never an empty box.
  const body = pics && pics.length ? (
    <PictureGuard media={pics} overlay={ov} still={stillUnder(ov, scenes)} accent={hot}
      render={(ok) => <Component overlay={{ ...ov, media: ok }} accent={hot} />} />
  ) : <Component overlay={ov} accent={hot} />;
  return withSound(
    <MotionWrap motion={ov.motion} exit={ov.exit} speed={ov.speed} klass={klass}
      placement={{ position: ov.position, scale: ov.scale, opacity: ov.opacity }}>
      <KScale.Provider value={scale}>
        {body}
      </KScale.Provider>
    </MotionWrap>, sound);
};

/** The still of the scene an overlay starts on (its picture, or its clip's thumbnail). */
const stillUnder = (ov: Overlay, scenes: TimelineProps["scenes"]): string => {
  const under = scenes.find((s) => ov.startFrame >= s.startFrame && ov.startFrame < s.startFrame + s.durationInFrames);
  const m = under?.media;
  return m ? (m.type === "image" ? m.url : m.thumbnail || "") : "";
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
 * The music under the whole narration (components/musicMix.ts: its level at
 * every frame, its trim, its repeats). One pass of the track when it is as
 * long as the video; a shorter one is played pass after pass, crossfaded over
 * 3 s at equal power before its own tail - Remotion's loop repeats with a
 * hard cut, and the crime bed ends in 11 s of its own fade and silence. An
 * own file whose length nobody measured still uses Remotion's loop.
 */
const musicNodes = (bgm: NonNullable<TimelineProps["bgm"]>, volume: (f: number) => number, fps: number,
  total: number) => {
  const track = bgm.url.startsWith("bgm://") ? bgmTrack(bgm.url.slice(6)) : "";
  const src = track ? staticFile(`bgm/${track}.mp3`) : bgm.url;
  return musicPasses(total, fps, trackSeconds(track, bgm)).map((p, k) => (
    <Sequence key={`bgm-${k}`} from={p.from} durationInFrames={p.frames} layout="none">
      {p.loop ? (
        // The ducking must follow the video's frames, not restart with each loop of the track.
        <Audio src={src} volume={volume} loop loopVolumeCurveBehavior="extend" />
      ) : (
        <Audio src={src} volume={(f: number) => volume(p.from + f) * passGain(p, f)} />
      )}
    </Sequence>
  ));
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

/**
 * Ambience beds (src/ambience.py, doc.ambience): one bed at a time under the
 * scenes that are somewhere, its file played pass after pass, at the level
 * ambienceMix.ts works out frame by frame (planned against the voice, the
 * document's master, faded at its cuts, silent under full-screen graphics,
 * ducked under the words).
 */
const bedNode = (b: Bed, i: number, fps: number, master: number, duck: number, speech: Float32Array) => {
  const volume = bedVolume(b, fps, master, duck, speech);
  if (!volume) return null;
  const start = Math.round(Number(b.startFrame) || 0);
  const frames = Math.max(1, Math.round(Number(b.durationInFrames) || 0));
  // The file played pass after pass, crossfaded over 0.25 s (ambienceMix.ts bedPasses).
  const passes = bedPasses(frames, (SFX_META[b.name]?.duration ?? 0) * fps, fps * 0.25);
  const src = staticFile(`sfx/${b.name}.mp3`);
  return (
    <React.Fragment key={`amb-${i}`}>
      {passes.map((p, k) => (
        <Sequence key={k} from={start + p.from} durationInFrames={p.frames} layout="none">
          {p.loop ? (
            // No file length known: Remotion's loop, the volume counting frames across every pass.
            <Audio src={src} volume={(f: number) => volume(p.from + f)} loop loopVolumeCurveBehavior="extend" />
          ) : (
            <Audio src={src} volume={(f: number) => volume(p.from + f) * passGain(p, f)} />
          )}
        </Sequence>
      ))}
    </React.Fragment>
  );
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

/**
 * The video. Without a brand kit, exactly the narration's timeline (Body).
 * With one (props.brand, src/brandkit.py): the customer's intro sting first,
 * the timeline after it with their logo in its corner, their outro last
 * (an end card or their own video). The timeline keeps its own frame
 * numbers inside its Sequence, so every scene, caption, graphic, sound and
 * the narration stay exactly aligned; Root.tsx makes the composition
 * intro + body + outro frames long (brandFrames).
 */
export const Main: React.FC<TimelineProps> = (props) => {
  const brand = React.useMemo(() => brandOf(props), [props.brand]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!brand || !(brand.watermark || brand.intro?.frames || brand.outro?.frames)) return <Body {...props} />;
  const { intro, body, outro } = brandFrames(props);
  const accent = brand.accent || props.captions?.accent || "#F2B544";
  const last = props.scenes[props.scenes.length - 1]?.media;
  const lastStill = last ? (last.type === "image" ? last.url : last.thumbnail || "") : "";
  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {intro > 0 && brand.intro ? (
        <Sequence from={0} durationInFrames={intro} name="Brand intro">
          <BrandVideo clip={brand.intro} />
        </Sequence>
      ) : null}
      <Sequence from={intro} durationInFrames={body} name="Video">
        <Body {...props} />
        {brand.watermark ? <Watermark mark={brand.watermark} /> : null}
      </Sequence>
      {outro > 0 && brand.outro ? (
        <Sequence from={intro + body} durationInFrames={outro} name="Brand outro">
          {brand.outro.kind === "card" ? (
            <EndCard card={brand.outro} accent={accent} accent2={brand.accent2} fontFamily={brand.fontFamily}
              logo={brand.outro.logo || brand.watermark?.url} still={lastStill} />
          ) : <BrandVideo clip={brand.outro} />}
        </Sequence>
      ) : null}
    </AbsoluteFill>
  );
};

/** The narration's timeline: scenes, transitions, captions, graphics, narration, music, sounds. */
const Body: React.FC<TimelineProps> = (props) => {
  const { scenes, overlays, audio, bgm, captions } = props;
  // The brand kit's second colour: its figures and charts (overlay theme "accent2").
  const accent2 = props.brand && typeof props.brand.accent2 === "string" ? props.brand.accent2 : undefined;
  // Track toggles from the editor. Absent means on, so older timelines
  // render exactly as before.
  const showOverlays = props.overlaysEnabled !== false;
  // In the editor's Player, mount each clip this long before it appears so its
  // video has loaded by its first frame; without it every cut stalled on a
  // fresh download. Rendering ignores premounting.
  const { fps, durationInFrames: bodyFrames } = useVideoConfig();
  const premount = Math.round(fps * 2);
  // An animation scene's backdrop: the nearest clip of the story, blurred. A picture's: the shot beside it
  // (the one before first), drawn blurred only if the picture itself cannot be (SceneClip's hold).
  const backdrops = React.useMemo(() => {
    const out: Record<string, SceneMedia | null> = {};
    const real = (i: number) => {
      const m = scenes[i]?.media;
      return m && m.url && (m.type === "video" || m.type === "image") ? m : null;
    };
    scenes.forEach((sc, i) => {
      if (sc.media?.type !== "animation" && sc.media?.type !== "image") return;
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
  const bgmNodes = React.useMemo(
    () => (bgm?.url && musicVolume
      ? musicNodes(bgm, musicVolume, fps, Math.max(1, Math.ceil(props.durationInFrames))) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [bgm?.url, bgm?.track, bgm?.trackSeconds, musicVolume, fps, props.durationInFrames]);
  // The sound built into each look (LookSounds.tsx), from one pass over the document.
  const lookSounds = React.useMemo(
    () => planLookSounds(props, fps),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [overlays, scenes, props.lookSounds, props.meta, props.sfxEnabled, props.sfxVolume, fps]);
  // The frames each full-screen graphic holds the screen (the clip under it moves: StageFx).
  const stageWins = React.useMemo(() => stageWindows((overlays || []).map((o) => resolveOverlay(o))), [overlays]);
  const overlayNodes = React.useMemo(
    () => (overlays || []).map((ov, i) => renderOverlay(ov, captions.accent, scenes, lookSounds[`o${i}`], accent2)),
    [overlays, captions.accent, scenes, lookSounds, accent2]);
  // Built once per sfx list: each sound plays for its planned span (a typing
  // run lasts exactly as long as the letters appear) or, unplanned, for the
  // file's own length - never the old fixed 3 s that cut risers and typing.
  // When the looks carry their own sounds, a row planned for an overlay
  // would double its look's sound: only transitions and the editor's own play.
  const builtIn = lookSoundsOn(props);
  // The video's grade (gradeMath.ts): settings and the scenes' median tone,
  // read by every SceneClip. Absent from the document = no grade, as before.
  const grade = React.useMemo(() => gradeStateFor(props.grade, scenes), [props.grade, scenes]);
  // The ambience beds (src/ambience.py): the editor's sound switch mutes them
  // with every other sound; "enabled" false or level 0 turns them off.
  const ambience = props.ambience as Ambience;
  const bedNodes = React.useMemo(() => {
    const on = ambienceSettings(ambience, props.sfxEnabled);
    if (!on || !ambience?.beds) return [];
    const speech = speechCurve(props);
    return ambience.beds.map((b, i) => bedNode(b, i, fps, on.master, on.duck, speech));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ambience, scenes, props.sfxEnabled, props.durationInFrames, fps]);
  const sfxNodes = React.useMemo(() => {
    if (props.sfxEnabled === false) return [];
    const doubles = builtIn ? doublesLook(overlays || [], lookSounds) : () => false;
    return (props.sfx || []).map((fx, i) => (doubles(fx) ? null : sfxNode(fx, i, fps, props.sfxVolume)));
  }, [props.sfx, props.sfxEnabled, props.sfxVolume, fps, builtIn, overlays, lookSounds]);

  return (
    <AbsoluteFill className="tg-composition" style={{ backgroundColor: "#000" }}>
      {/* The page's own CSS must not resize the pictures (the editor's Player). */}
      <style>{PAGE_CSS_GUARD}</style>
      {/* Visual track — one clip per spoken clause, under the video's one grade */}
      <GradeContext.Provider value={grade}>
      {/* Under a full-screen graphic the clip pushes in, softens and dims as the graphic grows in, and
          settles back as it leaves (components/motion/stage.tsx): no map or chart ever cuts in on a clip. */}
      <StageFx windows={showOverlays ? stageWins : []}>
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
            {withSound(<SceneClip scene={scene} accent={captions.accent} accent2={accent2} backdrop={backdrops[scene.id]}
              nextTransition={scenes[i + 1]?.transition} />, lookSounds[`s${i}`])}
          </CrossfadeIn>
        </Sequence>
      ))}
      </StageFx>
      </GradeContext.Provider>

      {/* The owner's overlay transitions ("pack:<name>"): a clip screen-blended
          over a hard cut, its own sound levelled under the narration
          (meta.voiceLufs; never above 1; the editor's sound switch mutes it,
          its master level can only turn it down). */}
      <PackTransitions scenes={scenes} fps={fps} durationInFrames={props.durationInFrames} premountFor={premount}
        voiceLufs={(props.meta as { voiceLufs?: unknown } | undefined)?.voiceLufs}
        volume={props.sfxEnabled === false ? 0 : Math.min(1, Math.max(0, Number(props.sfxVolume ?? 1)))} />

      {/* Overlay track — graphics sit on top of the visuals (a look in the
          bottom strip, the source tag, reads CaptionsOn to stay clear of the captions) */}
      <CaptionsOn.Provider value={Boolean(captions.enabled)}>
      {showOverlays && (overlays || []).map((ov, i) => (
        <Sequence
          key={`ov-${i}`}
          from={ov.startFrame}
          // Never past the end of the video: the look's own exit (MotionWrap, inside its duration) then
          // always plays whole instead of the outer sequence cutting it mid-exit.
          durationInFrames={Math.max(1, Math.min(ov.durationInFrames, bodyFrames - ov.startFrame))}
          premountFor={premount}
        >
          {overlayNodes[i]}
        </Sequence>
      ))}
      </CaptionsOn.Provider>

      {/* Caption track, burned in on top, as a player draws subtitles: one track over the whole
          narration, so a phrase cue is never cut at a scene's edge, each cue placed clear of the
          graphics on screen with it (components/Captions.tsx). On top, a cue that cannot clear a
          full-screen card (a map, a split's divider) stays readable instead of vanishing under it. */}
      {captions.enabled ? <CaptionTrack props={props} /> : null}

      {/* Audio: narration drives the whole timeline; bgm sits well under it */}
      {audio?.url ? <Audio src={audio.url} volume={audio.volume ?? 1} /> : null}
      {bgmNodes}
      {bedNodes}
      {sfxNodes}
    </AbsoluteFill>
  );
};
