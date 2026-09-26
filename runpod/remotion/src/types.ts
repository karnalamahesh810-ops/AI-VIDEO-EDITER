export type Motion = "none" | "zoom-in" | "zoom-out" | "pan-left" | "pan-right";

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
 * How a scene enters. Most cuts are hard ("none"); real transitions are kept
 * for section changes, the way VidRush uses them (~1 cut in 4).
 * Must match TRANSITIONS in src/timeline.py; a test asserts they agree.
 */
export type SceneTransition =
  | "none" | "fade" | "film-burn" | "zoom" | "glitch" | "slide"
  | "whip" | "flash" | "light-leak" | "dip" | "blur" | "punch";

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
  | "name-card";

export interface SceneWord {
  text: string;
  start: number;
  end: number;
}

export interface SceneMedia {
  type: "video" | "image" | "color";
  url: string;
  source: string;
  attribution?: string;
  license?: string;
  /** Measured length of a video file; shorter than the scene = slowed to fill it. */
  clipSeconds?: number;
}

export interface Scene {
  id: string;
  startFrame: number;
  durationInFrames: number;
  text: string;
  /** What the sourcing step searched for — shown in the editor, not on screen. */
  query?: string;
  visualType?: "footage" | "image";
  media: SceneMedia;
  motion: Motion;
  /** Footage grade — film grain, vintage warmth, archival black and white. */
  treatment?: Treatment;
  transition: SceneTransition;
  /** "inset": media framed on a backdrop at its own shape (archival, low-res, 4:3). */
  frame?: "full" | "inset";
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

export interface Overlay {
  type: OverlayType;
  text: string;
  subtitle?: string;
  label?: string;
  /** Unit drawn after a stat's number: "%", "km", "years". */
  suffix?: string;
  value?: number;
  items?: OverlayItem[];
  locations?: MapLocation[];
  /** Only used by "split": the two visuals to show, top then bottom. */
  media?: SceneMedia[];
  variant?: string;
  /** Words to emphasise (sentence-highlight) or the phrase to mark (article-zoom). */
  highlight?: string;
  /** Document body for article-zoom; only ever text taken from the plan. */
  body?: string;
  /** Normalized frame positions, supplied after visual review, not guessed. */
  anchor?: { x: number; y: number };
  labelPosition?: { x: number; y: number };
  startFrame: number;
  durationInFrames: number;
}

export interface TimelineProps {
  schemaVersion?: number;
  fps: number;
  width: number;
  height: number;
  durationInFrames: number;
  audio: { url: string; volume: number };
  bgm?: { url: string; volume: number } | null;
  captions: {
    enabled: boolean;
    position: "bottom" | "center";
    accent: string;
    fontFamily: string;
  };
  scenes: Scene[];
  overlays: Overlay[];
  /** Editor track toggle for text animations / graphics. Absent = on. */
  overlaysEnabled?: boolean;
  /**
   * Sound effects, each tied to an animation moment (VidRush: ~1 per 2-3 min,
   * 20-35% volume). `name` is a file in public/sfx/. sfxVolume scales them all
   * (the editor's slider); sfxEnabled false mutes the track. Absent = on, 1.
   */
  sfx?: { name: string; startFrame: number; volume: number }[];
  sfxVolume?: number;
  sfxEnabled?: boolean;
  meta?: Record<string, unknown>;
  /**
   * Remotion requires composition props to be assignable to
   * Record<string, unknown>. Without this index signature <Composition> falls
   * back to that type and every field inside calculateMetadata reads as
   * `unknown`. Declared fields above keep their real types.
   */
  [key: string]: unknown;
}
