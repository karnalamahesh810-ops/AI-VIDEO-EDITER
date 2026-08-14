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
  type: "title" | "callout";
  variant?: string;
  text: string;
  startFrame: number;
  durationInFrames: number;
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
}
