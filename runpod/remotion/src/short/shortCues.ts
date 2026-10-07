import { buildCues, cueFrames, type CueOptions, type FrameCue } from "../components/captionCues";
import type { ShortWord } from "./shortLayout";

/**
 * A Short's caption cues, set by the same subtitler as the long video's captions
 * (components/captionCues.ts) with phone-sized lines: at most ~16 characters a line, two lines, at most
 * ~3 s a cue, a cue ending at a short pause. Pure (no React): tests/test_shorts.py runs it under node.
 */
export const SHORT_CUES: CueOptions = {
  maxLineChars: 16,
  minSeconds: 0.5,
  maxSeconds: 3.0,
  readingCps: 18,
  linger: 0.25,
  chainGap: 0.6,
  gapFrames: 0,
  breakPause: 0.55,
};

/** The Short's cues on its frames. */
export const shortCues = (words: ShortWord[], fps: number): FrameCue[] =>
  cueFrames(buildCues(words || [], { ...SHORT_CUES, fps }), fps, 0);
