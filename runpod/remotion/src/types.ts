export type Motion = "none" | "zoom-in" | "zoom-out" | "pan-left" | "pan-right";

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
  media: SceneMedia;
  motion: Motion;
  transition: "none" | "fade";
  words: SceneWord[];
}

export interface Overlay {
  /** title = multi-font card, callout = fact pill, typewriter = typed line,
   *  split = horizontal split-screen comparison (needs two media entries). */
  type: "title" | "callout" | "typewriter" | "split";
  variant?: string;
  text: string;
  startFrame: number;
  durationInFrames: number;
  /** Only used by "split": the two visuals to show, top then bottom. */
  media?: SceneMedia[];
}

export interface TimelineProps {
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
