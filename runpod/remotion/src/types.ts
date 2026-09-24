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
export type SceneTransition = "none" | "fade" | "film-burn" | "zoom" | "glitch" | "slide";

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
  | "arrow"
  | "split";

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
  /** Per-clip effect drawn over / applied to the media. */
  effect?: SceneEffect;
  /** Vision-model match record: what the frames actually show, and how well. */
  semanticMetadata?: {
    intent?: string;
    subject?: string;
    searchQuery?: string;
    contentDescription?: string;
    relevanceScore?: number;
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
  meta?: Record<string, unknown>;
  /**
   * Remotion requires composition props to be assignable to
   * Record<string, unknown>. Without this index signature <Composition> falls
   * back to that type and every field inside calculateMetadata reads as
   * `unknown`. Declared fields above keep their real types.
   */
  [key: string]: unknown;
}
