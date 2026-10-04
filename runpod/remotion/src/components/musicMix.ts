/**
 * The music under the narration: its level at every frame, the part of the
 * video it plays under, and how a track shorter than the video repeats. Pure
 * arithmetic over the document (no React), so the renderer, the editor's
 * Player, the editor's music bar and a node test (tests/test_music_span.py)
 * all compute the same thing: what the bar shows is what the preview plays
 * and what the export contains.
 *
 * The owner (2026-10-04): "the music didn't match the full length of the
 * narration, it is only going 30 seconds, it is not even stretching out, I
 * tried to stretch it out". What was wrong, each fixed here:
 *
 *  - The editor's 60 fps export doubled every frame number of the document
 *    except the music's, so the planned fade-out (3 s before the end at
 *    30 fps) sat in the middle of the 60 fps video: the music faded out
 *    halfway and the second half was silent (Yellowstone, 2026-10-03:
 *    sections ending at frame 52,810 of 105,620). fitMusic puts sections left
 *    on another clock back on the video's own, at render and in the editor.
 *  - The editor's music bar read the first section, which in the worker's mix
 *    is the one-frame fade-in: a sliver that could not be stretched, and
 *    dragging it only set a trim a few seconds long. musicSpan is the one
 *    answer to "where does the music play": music.from / music.to, absent =
 *    the whole video.
 *  - Remotion's own loop repeats a track with a hard cut (and 16 silent
 *    samples); the crime bed ends in 11 s of its own fade and silence. A
 *    track shorter than the video is played pass after pass, crossfaded over
 *    MUSIC_LOOP_CROSSFADE at equal power, before its own tail (musicPasses).
 */
import { bedPasses, type BedPass } from "./ambienceMix";

/** The owner's mix (src/config.py MUSIC_LEVEL / MUSIC_DUCK, 2026-10-02): "put it on fifty percent". */
export const MUSIC_LEVEL = 0.5;
export const MUSIC_DUCK = 0.8;
/** Seconds a section takes to reach its level, and the fade at the video's end (src/timeline.py). */
export const MUSIC_RAMP = 1.5;
export const MUSIC_FADE_OUT = 3.0;
/** Seconds two passes of a repeated track overlap. */
export const MUSIC_LOOP_CROSSFADE = 3.0;

/**
 * The bundled tracks (public/bgm/<name>.mp3): each file's length and how much
 * of its end is its own fade-out or silence, in seconds (ffprobe and a
 * per-second level scan, 2026-10-04; a test keeps them equal to the files).
 * The next pass comes in before that tail.
 */
export const BGM_META: Record<string, { seconds: number; tail: number }> = {
  "investigative-v5": { seconds: 1800.04, tail: 0 },
  "investigative-20m": { seconds: 1199.12, tail: 0 },
  "suspense-v2": { seconds: 1800.04, tail: 0 },
  "crime-v1": { seconds: 1800.04, tail: 12 },
};

export type MusicSection = { startFrame: number; endFrame?: number; volume: number; mood?: string; kind?: string };
export type MusicPlan = {
  sections?: MusicSection[]; duck?: number; gain?: number; from?: number; to?: number;
  [k: string]: unknown;
};
type Track = { url?: string | null; volume?: number; track?: unknown; trackSeconds?: unknown } | null | undefined | false;
export type MusicDoc = {
  fps: number; durationInFrames: number; bgm?: Track; music?: MusicPlan | null;
  scenes: { words?: { start: number; end: number }[] }[];
};

const num = (v: unknown, fallback = 0): number => {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
};
const round4 = (v: number) => Math.round(v * 1e4) / 1e4;
const sectionsOf = (music: MusicPlan | null | undefined): MusicSection[] =>
  (Array.isArray(music?.sections) ? music!.sections! : []).filter((s) => s && typeof s === "object");

/** The worker's own mix: its sections say what they are (fade-in, voice, pause, fade-out). */
export const isPlanned = (music: MusicPlan | null | undefined): boolean => sectionsOf(music).some((s) => Boolean(s.kind));

/** The worker's flat mix (src/timeline.py music_flat): in from silence, one level, out over the last 3 s. */
export const flatSections = (total: number, fps: number, level: number, mood = ""): MusicSection[] => {
  const n = Math.max(1, Math.round(total));
  const lv = round4(Math.max(0, Math.min(1, num(level))));
  const fadeOut = Math.max(2, n - Math.floor(MUSIC_FADE_OUT * fps + 0.5));
  const fadeHalf = Math.max(fadeOut + 1, n - Math.floor(MUSIC_RAMP * fps + 0.5));
  const out: MusicSection[] = [
    { startFrame: 0, volume: 0, mood, kind: "fade-in" },
    { startFrame: 1, volume: lv, mood, kind: "voice" },
    { startFrame: fadeOut, volume: round4(lv / 2), mood, kind: "fade-out" },
    { startFrame: fadeHalf, volume: 0, mood, kind: "fade-out" },
  ];
  return out.map((s, k) => ({ ...s, endFrame: Math.max(s.startFrame + 1, k + 1 < out.length ? out[k + 1].startFrame : n) }));
};

/** The owner's mix as a document's `music`: MUSIC_LEVEL flat, x MUSIC_DUCK while a word is spoken. */
export const flatMusic = (total: number, fps: number, level = MUSIC_LEVEL, duck = MUSIC_DUCK, mood = ""): MusicPlan => ({
  sections: flatSections(total, fps, level, mood),
  duck: Math.max(0, Math.min(1, num(duck, MUSIC_DUCK))),
  levels: { mode: "flat", speech: round4(Math.max(0, Math.min(1, num(level)))) },
});

/**
 * The music on the video's own clock (src/timeline.py music_fit is the same
 * rule, for the worker's check before a render). Sections that end where the
 * video ends are returned as they are. Otherwise:
 *  - a lone level set in the editor (no plan) covers the whole video;
 *  - sections that end at exactly half or twice the video's length were left
 *    behind by a 30 <-> 60 fps export: every frame number (and the trim) is
 *    scaled to the video's clock;
 *  - a plan whose video was made longer or shorter keeps its levels and gets
 *    its fade-out at the new end.
 */
export const fitMusic = <T extends MusicPlan | null | undefined>(music: T, total: number, fps: number): T => {
  const all = sectionsOf(music);
  if (!music || !all.length) return music;
  const n = Math.max(1, Math.round(total));
  const planned = all.some((s) => Boolean(s.kind));
  if (!planned && all.length === 1) {
    const only = all[0];
    if (num(only.startFrame) === 0 && num(only.endFrame) === n) return music;
    return { ...music, sections: [{ ...only, startFrame: 0, endFrame: n }] };
  }
  const end = Math.max(...all.map((s) => num(s.endFrame)));
  if (!(end > 0) || Math.abs(end - n) <= 1) return music;
  const scale = Math.abs(end * 2 - n) <= 2 ? 2 : Math.abs(end - n * 2) <= 2 ? 0.5 : 1;
  const at = (v: unknown) => Math.max(0, Math.floor(num(v) * scale + 0.5));
  let sections: MusicSection[] = all.map((s) => ({ ...s, startFrame: at(s.startFrame), endFrame: at(s.endFrame) }));
  if (planned && Math.abs(at(end) - n) > 1) {
    const fadeOut = Math.max(2, n - Math.floor(MUSIC_FADE_OUT * fps + 0.5));
    const fadeHalf = Math.max(fadeOut + 1, n - Math.floor(MUSIC_RAMP * fps + 0.5));
    const body = sections.filter((s) => s.kind !== "fade-out" && s.startFrame < fadeOut);
    const voice = [...body].reverse().find((s) => s.kind === "voice") || body[body.length - 1];
    const level = voice ? num(voice.volume) : 0;
    const mood = voice?.mood ?? "";
    sections = [...body, { startFrame: fadeOut, volume: round4(level / 2), mood, kind: "fade-out" },
      { startFrame: fadeHalf, volume: 0, mood, kind: "fade-out" }];
  }
  sections = sections.map((s, k) => ({ s, k })).sort((a, b) => a.s.startFrame - b.s.startFrame || a.k - b.k).map((x) => x.s);
  sections = sections.map((s, k) => ({
    ...s, endFrame: Math.max(s.startFrame + 1, k + 1 < sections.length ? sections[k + 1].startFrame : n),
  }));
  const out: MusicPlan = { ...music, sections };
  if (scale !== 1) {
    if (typeof music.from === "number") out.from = at(music.from);
    if (typeof music.to === "number") out.to = at(music.to);
  }
  return out as T;
};

const spanOf = (music: MusicPlan | null | undefined, n: number) => {
  const from = Math.max(0, Math.min(n - 1, Math.round(num(music?.from))));
  const to = Math.max(from + 1, Math.min(n, Math.round(num(music?.to, n) || n)));
  return { from, to };
};

/**
 * The part of the video the music plays under, in frames: the editor's trim
 * (music.from / music.to), absent = the whole video. The editor's bar draws
 * exactly this and the renderer is silent outside it.
 */
export const musicSpan = (music: MusicPlan | null | undefined, total: number, fps: number): { from: number; to: number } => {
  const n = Math.max(1, Math.round(total));
  return spanOf(fitMusic(music, n, fps), n);
};

/**
 * The music level at a frame: the section's level, ramped over 1.5 s at each
 * section change, times the editor's level (gain), ducked while a word is
 * spoken, silent outside the trim with a 1.5 s fade at a trimmed end. A level
 * set in the editor with no plan (one section, no fades of its own) is faded
 * in over 1.5 s and out over the last 3 s like the worker's mix.
 */
export const musicVolume = (doc: MusicDoc): ((f: number) => number) => {
  const fps = doc.fps;
  const total = Math.max(1, Math.ceil(doc.durationInFrames));
  const music = fitMusic(doc.music, total, fps);
  const base = (doc.bgm ? doc.bgm.volume : undefined) ?? 0.12;
  const sections = sectionsOf(music);
  const duck = music?.duck ?? 0.55;
  // The editor's "Music level" (1 = the automatic mix under the voice). The
  // planner's sections used to ignore every editor setting, so the owner could
  // not turn the music up at all (2026-10-01).
  const gain = Math.max(0, Number(music?.gain ?? 1) || 0);
  // Whether a word is being spoken, per frame (0.15 s before a word to 0.35 s
  // after it), built once. The Player evaluates this callback for EVERY frame of
  // the video whenever it changes, and it used to scan every word each time:
  // 0.2-0.45 s per preview frame on a 22-minute video, so the editor played at
  // a few frames a second.
  const speaking = new Uint8Array(total + 1);
  for (const sc of doc.scenes) {
    for (const w of sc.words || []) {
      const a = Math.max(0, Math.ceil((w.start - 0.15) * fps));
      const b = Math.min(total, Math.floor((w.end + 0.35) * fps));
      for (let f = a; f <= b; f++) speaking[f] = 1;
    }
  }
  const ramp = Math.max(1, Math.round(fps * MUSIC_RAMP));
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
  const { from, to } = spanOf(music, total);
  const own = isPlanned(music);         // the plan carries its own fade-in and fade-out
  const out = Math.max(1, Math.round(fps * MUSIC_FADE_OUT));
  const edges = (f: number): number => {
    if (f < from || f > to) return 0;
    const head = from > 0 || !own ? (f - from) / ramp : 1;
    const tail = to < total ? (to - f) / ramp : own ? 1 : (to - f) / out;
    return Math.max(0, Math.min(1, head, tail));
  };
  return (f: number) => {
    const level = levelAt(f) * (sections.length ? gain : 1) * edges(f);
    const on = speaking[Math.min(total, Math.max(0, Math.round(f)))] === 1;
    return Math.max(0, Math.min(1, on ? level * duck : level));
  };
};

/**
 * Seconds of a track one pass plays before the next comes in, 0 when its
 * length is not known (Remotion's own loop then). `name` is the bundled
 * track ("" for the job's own or an uploaded file, whose length the document
 * carries in bgm.trackSeconds - but not next to a leftover bgm.track: that
 * length belongs to the bundled track the file replaced).
 */
export const trackSeconds = (name: string, bgm?: Track): number => {
  const meta = BGM_META[name];
  if (meta) return meta.seconds - meta.tail;
  if (name || !bgm || bgm.track) return 0;
  const s = num(bgm.trackSeconds);
  return s > 0 ? s : 0;
};

/**
 * How the track is played under `total` frames: one pass when it is long
 * enough, else pass after pass, each starting MUSIC_LOOP_CROSSFADE before the
 * last one ends (ambienceMix.ts bedPasses / passGain: equal power, no dip).
 */
export const musicPasses = (total: number, fps: number, seconds: number): BedPass[] =>
  bedPasses(total, seconds * fps, MUSIC_LOOP_CROSSFADE * fps);
