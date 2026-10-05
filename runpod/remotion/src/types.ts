export type Motion = "none" | "zoom-in" | "zoom-out" | "pan-left" | "pan-right"
  // Stills (VidRush): the photo slides in from a side while it settles from a
  // close zoom, then keeps pushing; or a slow push with a slight turn.
  | "reveal-left" | "reveal-right" | "push-rotate"
  // A documentary editor's hand moves on stills (transitions/stillMotion.tsx):
  // push to an off-centre point, pull back to reveal, diagonal drift, a sharp
  // print drifting over a blurred copy (parallax), a slight turn that settles.
  | "push-offcenter" | "pull-back" | "drift-diagonal" | "parallax" | "rotate-settle";

/**
 * The grade applied to a scene's footage.
 *
 * Borrowed clips come from different cameras, decades and upload qualities, so
 * a shared grade is what makes them read as one film. `vintage` and `archival`
 * additionally mark a beat as the past without narrating it.
 *
 * Must match TREATMENTS in src/director.py; a test asserts they agree.
 */
export type Treatment = "none" | "film" | "vintage" | "archival";

/**
 * How a scene enters. Most cuts are hard ("none"). src/timeline.py plans the
 * rest by cutting style: documentary / history / story mark section changes
 * softly (~1 cut in 6 at most), news / compilation / trending punctuate more
 * (~1 cut in 3-4). The cut transitions (remotion/src/transitions) straddle
 * the cut: the outgoing scene draws their first half.
 * Must match TRANSITIONS in src/timeline.py; a test asserts they agree.
 */
export type SceneTransition =
  | "none" | "fade" | "film-burn" | "zoom" | "glitch" | "slide"
  | "whip" | "flash" | "light-leak" | "dip" | "blur" | "punch"
  // VidRush section changes: barn-door split, a coloured bar sweep, a pixel
  // mosaic into archival material, a blue wash into a quote.
  | "split-wipe" | "bar-wipe" | "mosaic" | "color-wash"
  // Editor cut transitions that straddle the cut (remotion/src/transitions).
  | "whip-pan" | "zoom-punch" | "shake-cut" | "blur-dissolve" | "luma-fade"
  | "chromatic-flash" | "vhs-glitch"
  // News-compilation cross-dissolve: the outgoing shot plays on under the
  // incoming one while it fades in (Main.tsx extends the outgoing scene).
  | "crossfade"
  // The owner's overlay transition pack ("pack:mlt5"): a hard cut with the
  // pack clip laid over it, screen-blended, its own sound levelled under the
  // narration (Scene.transitionGain; transitions/PackTransition.tsx). The names are data/transitions_meta.json's,
  // checked against timeline.pack_meta() rather than this list.
  | `pack:${string}`;

/**
 * One effect per clip, so borrowed footage reads as designed.
 * Must match EFFECTS in src/timeline.py; a test asserts they agree.
 */
export type SceneEffect =
  | "none"
  | "ken-burns"
  | "light-leaks"
  | "dust"
  | "film-flicker"
  | "color-shift";

/**
 * Every animation template the renderer can draw.
 *
 * This list is the renderer's half of a three-way contract: it must match
 * `TEMPLATES` in src/director.py and the switch in Main.tsx. A type present
 * here but missing from the switch renders as a plain title card — silently,
 * which is why the Python test suite asserts all three agree.
 */
export type OverlayType =
  | "title"
  | "chapter"
  | "callout"
  | "typewriter"
  | "stat"
  | "bar-chart"
  | "map"
  | "quote"
  | "timeline"
  | "highlight"
  | "lower-third"
  | "comparison"
  | "stat-tag"
  | "label-boxes"
  | "ring-stat"
  | "bullets"
  | "swoosh-title"
  | "kicker"
  | "memo-box"
  | "word-type"
  | "underline-title"
  | "bar-title"
  | "age-tag"
  | "clock-badge"
  | "red-strip"
  | "line-chart"
  | "path-steps"
  | "progress-steps"
  | "span"
  | "icon-pop"
  | "arrow"
  | "split"
  // VidRush's own text animations, read off their exports.
  | "sentence-highlight"
  | "article-zoom"
  | "date-stamp"
  | "photo-card"
  | "name-card"
  // Broadcast data graphics and motion graphics (MotionGraphics.tsx).
  | "donut"
  | "area-chart"
  | "progress-bar"
  | "icon-array"
  | "ranking"
  | "counter"
  | "number-roll"
  | "trend"
  | "year-roll"
  | "banner"
  | "scale-compare"
  // The animation library (components/lib/*): the variant names the look.
  | "motion";

export interface SceneWord {
  text: string;
  start: number;
  end: number;
}

/** A rectangle as shares (0..1) of the frame - or, in focus.box, of the source picture. x/y: top-left. */
export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** What the worker found in a scene's picture (src/reframe.py), kept for the editor. */
export interface MediaFocus {
  /** The subject: head and shoulders for faces, the main object, or where the action is (source shares). */
  box?: Box;
  kind?: "face" | "object" | "action" | "saliency" | "text" | "none";
  confidence?: number;
  /** The clip's own camera move over the shown stretch: a moving shot is never reframed. */
  motion?: { moving?: boolean; pan?: number; panRate?: number; zoom?: number; shake?: number; cut?: boolean };
  /** Burned-in lettering or a station logo: such a clip is never cropped. */
  overlay?: boolean;
  /** Real detail in lines (soft or upscaled pictures are pushed less, or not at all). */
  lines?: number;
  why?: string;
  [key: string]: unknown;
}

/**
 * The worker's planned move for THIS picture (src/reframe.py): `from` and
 * `to` viewports (frame shares) drawn by components/reframe.ts; on a still
 * only `subject`, which the still's own motion is aimed at. Bound to the
 * picture by `source` and planned for the frame `aspect`.
 */
export interface MediaReframe {
  from?: Box;
  to?: Box;
  kind?: "push" | "pull" | "drift";
  subject?: Box;
  zoom?: number;
  aspect?: number;
  seconds?: number;
  source?: string;
  by?: string;
}

/**
 * The editor's per-scene say on reframing: "off" (or false) = no move on
 * this scene whatever the plan; "auto" / absent = the plan (media.reframe);
 * {from, to} = its own move, in frame shares.
 */
export type SceneReframe = "off" | "auto" | false | null | { from: Box; to: Box };

/** One depth layer of a living photo (src/living.py), listed back to front. */
export interface LivingLayer {
  url: string;
  /** Its depth, 0 = far .. 1 = near: how far it moves against the others. */
  depth: number;
  /** Cut to its own box ([x0, y0, x1, y1], shares of the picture); absent = the whole picture. */
  box?: [number, number, number, number];
}

/**
 * A still drawn with real depth (src/living.py; transitions/livingPhoto.tsx):
 * the scene's own move on the stack, each layer moved against it by its
 * depth. Bound to the picture by `source`; missing or unloadable layers =
 * the flat picture, as before.
 */
export interface MediaLiving {
  v?: number;
  layers: LivingLayer[];
  /** The nearest layer's middle (shares of the picture): the camera moves about it. */
  focus?: { x: number; y: number };
  /** The picture's width / height the layers were cut at. */
  aspect?: number;
  /** The shift between the nearest and the farthest layer over a shot (a share of the frame). */
  strength?: number;
  quality?: number;
  source?: string;
  by?: string;
}

export interface SceneMedia {
  /** "animation": the scene is a full-screen motion graphic (scene.animation). */
  type: "video" | "image" | "color" | "animation";
  url: string;
  source: string;
  attribution?: string;
  license?: string;
  /** Measured length of a video file; shorter than the scene = slowed to fill it. */
  clipSeconds?: number;
  /** A still frame of the clip (the editor's thumbnail); an animation scene's blurred backdrop. */
  thumbnail?: string;
  /**
   * The picture's measured tone (src/grade.py): mean luma l, its 2nd/98th
   * percentiles lo/hi, mean chroma s, red and blue against green in the
   * midtones rg/bg. The video's grade pulls each scene toward the median of
   * these (components/gradeMath.ts).
   */
  tone?: { l: number; lo: number; hi: number; s: number; rg: number; bg: number; v?: number };
  /** Smart reframing: what was found in the picture, and the move planned for it. */
  focus?: MediaFocus;
  reframe?: MediaReframe;
  /** A still's depth layers (living photos); absent = drawn flat. */
  living?: MediaLiving;
}

export interface Scene {
  id: string;
  startFrame: number;
  durationInFrames: number;
  text: string;
  /** What the sourcing step searched for — shown in the editor, not on screen. */
  query?: string;
  visualType?: "footage" | "image" | "animation";
  media: SceneMedia;
  /**
   * For media.type "animation": the template and its props, drawn full-screen
   * by AnimationScene (VidRush's purple blocks: a graphic instead of a clip).
   */
  animation?: Partial<Overlay>;
  motion: Motion;
  /** Footage grade — film grain, vintage warmth, archival black and white. */
  treatment?: Treatment;
  transition: SceneTransition;
  /**
   * A pack transition's ("pack:<name>") own sound level, planned against the
   * narration (src/timeline.py pack_gain): its loudest moment 6 dB under the
   * voice, a glitch clip 9. The renderer never plays it louder than that
   * ceiling or 1; absent, it plays at the ceiling.
   */
  transitionGain?: number;
  /** "inset": media framed on a backdrop at its own shape (archival, low-res, 4:3). */
  /** "window": the footage plays inside a floating player window on a designed backdrop (case-file look). */
  frame?: "full" | "inset" | "window";
  /** The editor's reframing choice for this scene (see SceneReframe). */
  reframe?: SceneReframe;
  /** The editor's say on a living photo: "off" (or false) = the still drawn flat; absent / "auto" = its layers. */
  living?: "off" | "auto" | false | null;
  /** Per-clip effect drawn over / applied to the media. */
  effect?: SceneEffect;
  /** Vision-model match record: what the frames actually show, and how well. */
  semanticMetadata?: {
    intent?: string;
    subject?: string;
    searchQuery?: string;
    /** "event" / "year" for a news-type story's beats: re-sourcing keeps them on that event. */
    eventWindow?: string;
    contentDescription?: string;
    relevanceScore?: number;
    /** The vision judge's 0-1 rating of the footage itself: sharp, stable, lit, framed. */
    qualityScore?: number;
    provider?: string;
  };
  words: SceneWord[];
  /** Set when the media is generated or unlicensed and a human should look. */
  reviewRequired?: boolean;
  reviewReason?: string;
}

/** One row of a chart, comparison or timeline. */
export interface OverlayItem {
  label: string;
  value?: number;
  text?: string;
}

/**
 * A map pin. Coordinates always come from a gazetteer lookup in geocode.py,
 * never from a language model, and `label` is what that lookup returned.
 */
export interface MapLocation {
  label: string;
  lat: number;
  lon: number;
  kind?: string;
}

/**
 * The geometry of an auto map (src/automaps.py): a river or canal as lines, a lake or
 * reservoir as outlines, the dam as a pin - all in lon/lat, from the bundled geodata.
 */
export interface GeoDoc {
  kind: "river" | "canal" | "reservoir" | "dam" | "lake";
  name: string;
  label: string;
  /** [west, south, east, north]: the frame the camera settles on. */
  bbox: [number, number, number, number];
  lines?: [number, number][][];
  rings?: [number, number][][];
  /** Faint lines for context (the river that feeds a reservoir). */
  context?: [number, number][][];
  pins?: { label: string; lat: number; lon: number; kind?: string }[];
  /** The lines run source to mouth: the water may stream along them. */
  flow?: boolean;
  /** A hand-traced route (a canal): drawn dashed. */
  approx?: boolean;
  river?: string;
}

/**
 * The real numbers a data graphic draws (src/datagraphics.py from src/realdata.py: USBR, USGS, the U.S. Drought
 * Monitor, NOAA) - never the narration's or a model's. Dates are ISO ("2026-10-03"); `points` run oldest first
 * and end on the latest reading itself. Drawn by components/lib/LibRealData.tsx (rd-line, rd-number, rd-bars,
 * rd-gauge); every field but `points` and `latest` is optional.
 */
export interface DataDoc {
  v?: number;
  look?: string;
  /** elevation | percent_full | storage | flow | drought | temperature | precip | alerts */
  metric?: string;
  entity?: string;
  /** "LAKE POWELL", "COLORADO RIVER AT LEES FERRY, AZ" (the overlay's text, when set, wins). */
  title?: string;
  /** "PERCENT OF LIVE CAPACITY" (the overlay's label, when set, wins). */
  kicker?: string;
  /** "FT", "%", "MAF", "CFS", "°F", "IN". */
  unit?: string;
  decimals?: number;
  /** How far apart the points are: day | week | month | year. */
  step?: string;
  points?: [string, number][];
  latest?: { date: string; value: number; label?: string };
  /** The reading the line compares with (a year said, a year ago, the start of the window). */
  compare?: { date: string; value: number; label?: string };
  /** The change since `compare` as written by the planner: "−158.5 FT SINCE JAN 2001". */
  delta?: { value?: number; text: string };
  /** Levels the source itself states (full pool, minimum power pool, dead pool). */
  refs?: { label: string; value: number }[];
  /** A fixed axis ([0, 100] for a share). */
  range?: [number, number];
  /** rd-bars: the rows, the one the narration names highlighted. */
  bars?: { label: string; value: number; highlight?: boolean }[];
  /** rd-gauge: the storage behind the share, out of the capacity (million acre-feet). */
  storage?: { value: number; capacity: number; unit?: string };
  /** A record year: its value, rank and the word ("WARMEST OF 131 YEARS"). */
  record?: { date: string; value: number; label: string; rank: number; of: number; word: string };
  /** The short name shown ("USBR"), the agency in full, the official data URL (never "url": that is media). */
  source?: string;
  sourceName?: string;
  sourceUrl?: string;
  asOf?: string;
  /** "OCT 3, 2026", "THROUGH 2025": the date of the data, shown in the corner. */
  asOfLabel?: string;
  week?: string;
}

export interface Overlay {
  type: OverlayType;
  /** An auto map's geometry (src/automaps.py). */
  geo?: GeoDoc;
  /** A real data graphic's numbers (src/datagraphics.py). */
  data?: DataDoc;
  text: string;
  subtitle?: string;
  label?: string;
  /** Unit drawn after a stat's number: "%", "km", "years". */
  suffix?: string;
  /** Drawn before the number: "$" for money. */
  prefix?: string;
  value?: number;
  /** The whole a count is out of: "1 in 4" is value 1, total 4 (ratio graphics). */
  total?: number;
  items?: OverlayItem[];
  locations?: MapLocation[];
  /** Only used by "split": the two visuals to show, top then bottom. */
  media?: SceneMedia[];
  /**
   * An image look's pictures taken from the story's own scenes, by scene id,
   * in slot order (src/treatments.py bind_look_pictures: the scene under it,
   * then nearby scenes about the same subject). The renderer draws each
   * scene's current picture - its still, or a frame of its clip - before any
   * library picture in `media` (source "library").
   */
  mediaFrom?: string[];
  variant?: string;
  /** Words to emphasise (sentence-highlight) or the phrase to mark (article-zoom). */
  highlight?: string;
  /** Document body for article-zoom; only ever text taken from the plan. */
  body?: string;
  /** Normalized frame positions, supplied after visual review, not guessed. */
  anchor?: { x: number; y: number };
  labelPosition?: { x: number; y: number };
  /** Entrance move (MotionWrap.tsx): rise, drop, slide-left, zoom-in, glitch... */
  motion?: string;
  /** Colour theme replacing the brand accent: gold, red, teal, blue, white, amber; "accent2" = the brand's second colour. */
  theme?: string;
  /**
   * The premade animation this overlay is an instance of (templates/registry.json)
   * and the customisations the editor or the planner set on it. Unset fields
   * are filled from the template (templates.ts resolveOverlay).
   */
  template?: string;
  style?: string;
  exit?: string;
  speed?: number;
  position?: string;
  scale?: number;
  opacity?: number;
  fontScale?: number;
  /** Set by AnimationScene: the graphic IS the frame (no scrim over footage). */
  fullFrame?: boolean;
  /** A single figure riding on the clip: no full-frame darkening, placed small in a corner. */
  compact?: boolean;
  /** "blur": a full-screen graphic over the clip, drawn on a blurred still of that clip for its moment. */
  backdrop?: "blur";
  /** Where a text-only look sits (LibBoldText): low "left", "right" or "center"; "auto" = left. */
  align?: string;
  /**
   * How a text-only look is lettered (LibBoldText): "clean" (white, soft shadow,
   * a thin amber rule), "shine" (silver with one light sweep), "accent" (the key
   * part in amber), "shade" (white on a soft feathered shade); "auto" or absent =
   * one picked from the overlay's start frame. The planner turns them per occurrence.
   */
  textStyle?: string;
  /**
   * The look's own sound (built in, components/lib/LookSounds.tsx): "none"
   * silences it; another file name plays that one sound on its hit instead.
   * The planner leaves it out; older documents may carry {name, volume}.
   */
  sfx?: string | { name: string; volume?: number };
  /** Older editors' absolute level for the look's timeline sound (unused by built-in sounds). */
  sfxVolume?: number;
  /** A trim on the look's built-in sound: 1 = as designed against the voice, 0 = silent (never above the cap). */
  soundGain?: number;
  /** high | medium | low: of two looks landing together, the stronger one keeps its sound. */
  emphasis?: string;
  startFrame: number;
  durationInFrames: number;
}

/** The brand kit's corner logo (src/brandkit.py; components/brand). */
export interface BrandWatermark {
  url: string;
  position: "top-left" | "top-right" | "bottom-left" | "bottom-right";
  /** Width of the logo's square, as a share of the frame's width (0.04-0.3). */
  size: number;
  opacity: number;
}

/** The customer's intro sting or outro video. `frames` is written by the render (none: not drawn). */
export interface BrandClip {
  url: string;
  frames?: number;
  seconds?: number;
  /** Its sound against the narration (the render measures it); absent = 0.8. */
  volume?: number;
}

/** The end card: title, subscribe button text, a line under it. `frames` is written by the render. */
export interface BrandOutroCard {
  kind: "card";
  frames?: number;
  seconds?: number;
  title?: string;
  text?: string;
  subtext?: string;
  logo?: string;
}

/**
 * The brand kit's identity on a document (src/brandkit.py doc_brand): the
 * accent colours and font every look and caption uses, the corner logo, and
 * the intro and outro that play before and after the narration's timeline
 * (components/brand/brandLayout.ts brandFrames).
 */
export interface BrandBlock {
  accent?: string;
  /** The second colour: the figures and charts (overlay theme "accent2"). */
  accent2?: string;
  fontFamily?: string;
  watermark?: BrandWatermark;
  intro?: BrandClip;
  outro?: BrandOutroCard | (BrandClip & { kind: "video" });
  kit?: { id?: string; name?: string };
}

/** A music section: the level the music sits at between two frames, by mood. */
export interface MusicSection {
  startFrame: number;
  endFrame: number;
  mood: string;
  volume: number;
  /** What the worker's plan made it: fade-in, voice, pause, fade-out. Absent = a level set in the editor. */
  kind?: string;
}

export interface TimelineProps {
  schemaVersion?: number;
  fps: number;
  width: number;
  height: number;
  durationInFrames: number;
  audio: { url: string; volume: number };
  /** track / trackSeconds: the bundled track's name, or an own file's measured length (musicMix.ts trackSeconds). */
  bgm?: { url: string; volume: number; track?: string; trackSeconds?: number } | null;
  /**
   * Music automation over the bgm: sections with a mood and a level, ramped
   * between; `duck` is the share of the section level kept under speech.
   */
  /** gain: the editor's music level, a multiplier on the automatic sections (1 = default);
   *  from / to: the editor's trim in frames (music silent outside, 1.5 s fades), absent = the
   *  whole video. components/musicMix.ts is the one reading of all of it. */
  music?: { sections: MusicSection[]; duck?: number; gain?: number; from?: number; to?: number } | null;
  captions: {
    enabled: boolean;
    position: "bottom" | "center";
    accent: string;
    fontFamily: string;
    /** documentary | news | modern (templates/registry.json captionStyles). */
    style?: string;
  };
  scenes: Scene[];
  overlays: Overlay[];
  /** Editor track toggle for text animations / graphics. Absent = on. */
  overlaysEnabled?: boolean;
  /**
   * Sounds on the timeline: the transitions' sounds and the editor's own
   * (and, in documents from before lookSounds, one per animation). `name` is a
   * file in public/sfx/. sfxVolume scales every sound, the looks' own
   * included (the editor's slider); sfxEnabled false mutes them all. Absent = on, 1.
   */
  sfx?: {
    name: string;
    startFrame: number;
    volume: number;
    /** How long the sound may play; absent = the file's length (sfx_meta.json), at most 6 s. */
    durationFrames?: number;
    /** Frames skipped at the head of the file, so its peak lands on the look's
     *  hit without the sound starting before the look is on screen. */
    trimFrames?: number;
    /** What planned it: an overlay's animation (older documents), a scene transition, a swell into a
     *  reveal (src/ambience.py); absent = the editor's. */
    kind?: "overlay" | "transition" | "riser";
  }[];
  sfxVolume?: number;
  sfxEnabled?: boolean;
  /**
   * Present on documents planned since 2026-09-30: every overlay and every
   * full-screen animation scene plays the sound built into its look
   * (registry defaults.sounds, components/lib/LookSounds.tsx), set against
   * meta.voiceLufs at the style pack's `intensity`; sfx rows of kind
   * "overlay" are then ignored (they would double it). Absent (older
   * documents): the sfx rows carry every sound, exactly as before.
   */
  lookSounds?: { intensity?: number } | null;
  /**
   * One grade over every scene's picture, never the graphics
   * (components/gradeMath.ts, src/grade.py): preset none | neutral |
   * documentary | warm-doc | cool-news | archival, strength 0-1 (1 = as
   * designed), normalize (default true) pulls each scene toward the video's
   * median tone first. Absent or null = the pictures as sourced.
   */
  grade?: { preset?: string; strength?: number; normalize?: boolean } | null;
  /**
   * Ambience beds (src/ambience.py): looped sfx/amb-*.mp3 under the scenes
   * that are somewhere, one at a time. `level` is their master (1 = as
   * planned against the voice, 0 = off; never over a bed's ceiling),
   * `enabled` false turns them off, `duck` is the share kept while a word is
   * spoken. Each bed: name, startFrame, durationInFrames, volume, ceiling,
   * fadeIn / fadeOut (frames), holes ([start, end] frames from its start:
   * silent under full-screen graphics). Absent = no ambience, as before.
   */
  ambience?: {
    enabled?: boolean; level?: number; duck?: number;
    beds?: { name: string; startFrame: number; durationInFrames: number; volume: number; ceiling?: number;
      fadeIn?: number; fadeOut?: number; holes?: number[][] }[];
  } | null;
  /**
   * The customer's brand kit. Its intro plays before the narration's
   * timeline and its outro after it, so the video is longer than
   * durationInFrames (brandFrames); absent = exactly as before.
   */
  brand?: BrandBlock | null;
  meta?: Record<string, unknown>;
  /**
   * Remotion requires composition props to be assignable to
   * Record<string, unknown>. Without this index signature <Composition> falls
   * back to that type and every field inside calculateMetadata reads as
   * `unknown`. Declared fields above keep their real types.
   */
  [key: string]: unknown;
}
