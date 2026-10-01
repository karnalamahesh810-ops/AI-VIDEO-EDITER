/**
 * The sound built into every look (the owner, 2026-09-30: "when you make an
 * animation, the animation needs its specific sound BUILT IN - not us adding
 * sounds on the timeline"): which files a look plays, when, and how loud.
 *
 * Pure arithmetic over plain data (no React, no Remotion), so it runs the
 * same in the renderer, the editor's Player and a node test. Its Python twin
 * is the second half of src/sfxplan.py (look_sounds, plan_looks); the two
 * round alike and tests/test_builtin_sounds.py runs this file against it.
 *
 * A look's sound design is a list of cues: the registry's defaults.sounds
 * (scripts/build_registry.py writes them for every look from the sound and
 * hit frame the timeline planner used), or the cues a component schedules
 * from its own animation (useLookSound in LookSounds.tsx). Cue fields:
 *
 *   name     a file in public/sfx (no extension); `alt` its stand-ins while it
 *            does not ship, then its category's (soundLevels.categoryFallback)
 *   at       30-fps frame from the look's first frame where the sound's
 *            loudest moment lands (align "peak", one-shots) or where it
 *            starts (align "start": loops, runs, typing)
 *   until    a run: it plays from `at` to this frame, a loopable file looping
 *   kind     "typing": the video's typing take for the typing contract's span
 *   every/count  the cue again every `every` frames, `count` times in all
 *            ("items" / "locations": once per overlay item / place)
 *   gain_db  dB against the file's category level for this voice
 *   fade     fade-out frames at its end (a sound cut by the look's end fades anyway)
 *   when     "value" / "no-value": only when the overlay has (no) number
 *   fixed    not scaled by the style pack's intensity (a date's deep hit)
 *   scale    cue frames stretch with the look's length against its default
 *   pitch    the render's tone change (Audio toneFrequency; 1 = as recorded)
 *
 * Levels are the planner's, against the narration's measured loudness
 * (doc.meta.voiceLufs): every file is loudness-matched to refLufs (its
 * measured loudest 400 ms is sfx_meta.json "lufs": a hotter file is turned
 * down by the difference, a quieter one never raised), so a gain puts its
 * loudest moment a category's dB under the voice (typing 10, whooshes and
 * glitches 9, clicks/ticks/paper 7, hits 6), times 10^(gain_db/20), the
 * pack's intensity (doc.lookSounds.intensity; not for a fixed cue), the
 * overlay's soundGain trim and the document's sfxVolume - never above the
 * ceiling (capUnder dB under the voice, a glitch capUnderCategory's 9; the
 * owner, 2026-10-01: no sound is ever louder than the narration), never above 1.
 */
import registry from "../../templates/registry.json";
import sfxMetaJson from "../../data/sfx_meta.json";

export interface SoundCue {
  name: string;
  alt?: string[];
  at: number;
  align?: "peak" | "start";
  until?: number;
  kind?: "typing";
  every?: number;
  count?: number | "items" | "locations";
  gain_db?: number;
  fade?: number;
  when?: "value" | "no-value";
  fixed?: boolean;
  scale?: boolean;
  pitch?: number;
}

/** One sound as the renderer plays it: `from` counted from the look's first frame. */
export interface ScheduledSound {
  name: string;
  from: number;
  frames: number;
  /** Frames skipped at the head of the file (its peak lands early on the look). */
  trim: number;
  loop: boolean;
  fade: number;
  volume: number;
  pitch: number;
}

export interface SoundLevels {
  refLufs: number;
  voiceDefault: number;
  underDefault: number;
  capUnder: number;
  /** A category held further under the voice than capUnder (glitch: 9 dB). */
  capUnderCategory?: Record<string, number>;
  categoryUnder: Record<string, number>;
  nameCategory: Record<string, string>;
  categoryFallback: Record<string, string[]>;
  loopNames: string[];
  typingTakes: string[];
  typeStart: number;
  typingMaxSeconds: number;
  maxSeconds: number;
  minAudible: number;
  clashSeconds: number;
  defaultHit: number;
  maxRepeats: number;
  dateCues: string[];
  protectedComponents: string[];
}

export type SoundMeta = Record<string, { duration?: number; peak?: number; category?: string; loop?: boolean;
  /** The file's loudest 400 ms (LUFS) and its sample peak (dBFS), measured. */
  lufs?: number; peakDb?: number }>;

export interface SoundData {
  meta: SoundMeta;
  levels: SoundLevels;
}

/** What the renderer ships: public/sfx as sfx_meta.json lists it, and the registry's levels. */
export const SOUND_DATA: SoundData = {
  meta: sfxMetaJson as unknown as SoundMeta,
  levels: (registry as unknown as { soundLevels: SoundLevels }).soundLevels,
};

/** The template fields the sound plan reads (templates/registry.json). */
export interface SoundTemplate {
  id?: string;
  component?: string;
  emphasis?: string;
  cues?: string[];
  defaults?: {
    duration?: number;
    sfx?: { name?: string; volume?: number } | string;
    sfxAt?: number;
    sounds?: SoundCue[];
    soundTiming?: string;
    ownSound?: boolean;
    ownSfx?: boolean;
  };
}

/** The overlay fields the sound plan reads. */
export interface SoundOverlay {
  text?: unknown;
  value?: unknown;
  sfx?: unknown;
  soundGain?: unknown;
  emphasis?: unknown;
  items?: unknown;
  locations?: unknown;
}

const BASE_FPS = 30;
const RANK: Record<string, number> = { high: 0, medium: 1, low: 2 };

/** Math.round (halves up); the Python twin's _jr. */
export const jr = (x: number): number => Math.floor(x + 0.5);
const r4 = (x: number): number => Math.floor(x * 10000 + 0.5) / 10000;

/** A finite number (a numeric string counts, a boolean does not), else null: the twin's _number. */
export const num = (v: unknown): number | null => {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
};
export const numOr = (v: unknown, d: number): number => {
  const n = num(v);
  return n === null ? d : n;
};

// ------------------------------------------------------------------ levels
export const voiceLevel = (voiceLufs: unknown, data: SoundData = SOUND_DATA): number => {
  const v = num(voiceLufs);
  return v !== null && v > -60 && v < 0 ? v : data.levels.voiceDefault;
};

export const categoryOf = (name: string, data: SoundData = SOUND_DATA): string => {
  const got = data.meta[name]?.category;
  if (typeof got === "string" && got.trim().toLowerCase() in data.levels.categoryUnder) return got.trim().toLowerCase();
  return data.levels.nameCategory[name] || "";
};

/** A file's loudest 400 ms as levelled: its measured lufs when hotter than refLufs, else refLufs (never raised). */
export const fileLufs = (name: string | null | undefined, data: SoundData = SOUND_DATA): number => {
  const v = name ? num(data.meta[name]?.lufs) : null;
  return v === null ? data.levels.refLufs : Math.max(data.levels.refLufs, v);
};

/** The linear gain that puts a file's loudest moment `dbUnder` dB under the voice (`name`: that file's own loudness). */
export const gainFor = (dbUnder: number, voice: number, data: SoundData = SOUND_DATA, name?: string | null): number =>
  10 ** ((voice - dbUnder - fileLufs(name, data)) / 20);

/** How close to the voice a sound may come at its loudest (dB under): capUnder, a glitch's further. */
export const ceilingFor = (name: string | null | undefined, data: SoundData = SOUND_DATA): number => {
  const own = name ? data.levels.capUnderCategory?.[categoryOf(name, data)] : undefined;
  return Math.max(data.levels.capUnder, typeof own === "number" ? own : data.levels.capUnder);
};

/** The ceiling a sound is held under (never above the renderer's 1.0); without a name, a matched file's. */
export const capFor = (voice: number, data: SoundData = SOUND_DATA, name?: string | null): number =>
  Math.min(1, gainFor(ceilingFor(name, data), voice, data, name));

/** The planned gain of a file against this voice (the category's level, under its ceiling). */
export const levelFor = (name: string, voice: number, data: SoundData = SOUND_DATA): number => {
  const under = data.levels.categoryUnder[categoryOf(name, data)];
  return Math.min(capFor(voice, data, name),
    gainFor(typeof under === "number" ? under : data.levels.underDefault, voice, data, name));
};

// ------------------------------------------------------------------ files
export const shipped = (name: unknown, data: SoundData = SOUND_DATA): name is string =>
  typeof name === "string" && name !== "" && Object.prototype.hasOwnProperty.call(data.meta, name);

/** `name` if it ships, else its first shipped stand-in (`alt`, then its category's), else null. */
export const resolveSound = (name: unknown, alt?: unknown, data: SoundData = SOUND_DATA): string | null => {
  const order: unknown[] = [name, ...(Array.isArray(alt) ? alt.filter((a) => typeof a === "string") : []),
    ...(data.levels.categoryFallback[categoryOf(String(name ?? ""), data)] || [])];
  for (const x of order) if (shipped(x, data)) return x;
  return null;
};

export const loopable = (name: string, data: SoundData = SOUND_DATA): boolean => {
  const got = data.meta[name]?.loop;
  return typeof got === "boolean" ? got : data.levels.loopNames.includes(name);
};

const fileFrames = (name: string, fps: number, data: SoundData): number => {
  const d = num(data.meta[name]?.duration);
  return Math.max(1, Math.ceil((d !== null && d > 0 ? d : 3.0) * fps));
};
const peakFrames = (name: string, fps: number, data: SoundData): number =>
  Math.max(0, jr(numOr(data.meta[name]?.peak, 0) * fps));

// ------------------------------------------------------------------ one look
export const valueOf = (ov: SoundOverlay | undefined | null): number | null => {
  const v = ov?.value;
  return typeof v === "number" && Number.isFinite(v) ? v : null;
};
export const textOf = (ov: SoundOverlay | undefined | null): string => {
  const t = ov?.text;
  return typeof t === "string" ? t : t === null || t === undefined ? "" : String(t);
};

export const cueLive = (cue: SoundCue, text: string, value: number | null): boolean => {
  if ((cue.when === "value" && value === null) || (cue.when === "no-value" && value !== null)) return false;
  return !(cue.kind === "typing" && !text.trim());
};

/** The typing contract's span: 2 frames a character up to 48, else 1 (at 30 fps), at most typingMaxSeconds. */
export const typingSpan = (text: string, fps: number, data: SoundData = SOUND_DATA): number => {
  const n = text.length;
  return Math.min(jr(((n <= 48 ? 2 : 1) * n * fps) / BASE_FPS), jr(data.levels.typingMaxSeconds * fps));
};

export interface ScheduleContext {
  fps: number;
  /** The look's length in frames: nothing rings past it. */
  frames: number;
  text?: string;
  value?: number | null;
  /** The video's typing take for this look (planLooks). */
  take?: string | null;
  /** The template's default length in frames (for `scale` cues). */
  defaultFrames?: number;
  voice?: unknown;
  intensity?: number;
  /** The overlay's soundGain trim. */
  gain?: number;
  /** The document's sfxVolume. */
  master?: number;
  /** How many items / places the overlay has (cues counted "items" / "locations"). */
  items?: number;
  locations?: number;
}

/**
 * The sounds one look plays. Nothing rings past the look: a sound running
 * over its last frame is cut there and fades over its last frames, a hit
 * that would land in its last minAudible frames does not play, and neither
 * does a sound the look's end would cut to less than that.
 */
export const scheduleCues = (cues: readonly SoundCue[] | undefined | null, ctx: ScheduleContext,
  data: SoundData = SOUND_DATA): ScheduledSound[] => {
  const fps = Math.floor(numOr(ctx.fps, BASE_FPS)) || BASE_FPS;
  const frames = Math.floor(numOr(ctx.frames, 0));
  if (frames <= 0 || !cues) return [];
  const L = data.levels;
  const s = fps / BASE_FPS;
  const voice = voiceLevel(ctx.voice, data);
  const defaultFrames = numOr(ctx.defaultFrames, 0);
  const stretch = defaultFrames > 0 ? frames / defaultFrames : 1;
  const least = jr(L.minAudible * s);
  const longest = jr(L.maxSeconds * fps);
  const text = typeof ctx.text === "string" ? ctx.text : "";
  const value = ctx.value === undefined ? null : ctx.value;
  const trimGain = Math.max(0, numOr(ctx.gain, 1));
  const master = Math.max(0, numOr(ctx.master, 1));
  const pack = Math.max(0, numOr(ctx.intensity, 1));
  const out: ScheduledSound[] = [];
  for (const cue of cues) {
    if (!cue || typeof cue !== "object" || !cueLive(cue, text, value)) continue;
    const at0 = numOr(cue.at, 0);
    const every = numOr(cue.every, 0);
    const per = cue.count;
    const count = every <= 0 ? 1
      : per === "items" || per === "locations"
        ? Math.max(0, Math.min(L.maxRepeats, Math.trunc(numOr(per === "items" ? ctx.items : ctx.locations, 0))))
        : Math.max(1, Math.min(L.maxRepeats, Math.floor(numOr(per, 1))));
    const k = cue.scale ? stretch : 1;
    const until = num(cue.until);
    const typing = cue.kind === "typing";
    for (let r = 0; r < count; r++) {
      const at = jr((at0 + r * every) * s * k);
      const name = (typing && ctx.take ? ctx.take : null) || resolveSound(cue.name, cue.alt, data);
      if (!name) continue;
      const file = fileFrames(name, fps, data);
      const loops = loopable(name, data);
      let start: number;
      let trim: number;
      let want: number;
      if (typing) {
        start = at;
        trim = 0;
        want = until !== null ? jr(until * s * k) - at : typingSpan(text, fps, data);
      } else {
        const align = cue.align || (loops || until !== null ? "start" : "peak");
        // Its hit would land as the look leaves: not played.
        if (until === null && align === "peak" && at >= frames - least) continue;
        const raw = at - (align === "peak" ? peakFrames(name, fps, data) : 0);
        start = Math.max(0, raw);
        trim = start - raw;
        want = until !== null ? jr(until * s * k) - start : file - trim;
      }
      if (start >= frames) continue;
      const natural = file - trim;
      if (!loops) want = Math.min(want, natural);
      want = Math.min(want, longest);
      if (want <= 0) continue;
      const n = Math.min(want, frames - start);
      // Cut by the look's end to almost nothing: not played.
      if (n < want && n < least) continue;
      const looped = loops && n > natural;
      const asked = num(cue.fade);
      let fade = asked !== null && asked > 0 ? jr(asked * s)
        : n < natural || looped ? Math.max(1, Math.min(jr(4 * s), Math.floor(n / 3))) : 0;
      fade = Math.min(fade, n);
      const db = numOr(cue.gain_db, 0);
      const vol = r4(Math.min(capFor(voice, data, name), Math.max(0, levelFor(name, voice, data) * 10 ** (db / 20)
        * (cue.fixed ? 1 : pack) * trimGain * master)));
      if (vol <= 0.001) continue;
      const pitch = num(cue.pitch);
      out.push({ name, from: start, frames: n, trim, loop: looped, fade, volume: vol,
        pitch: pitch !== null && pitch > 0 ? pitch : 1 });
    }
  }
  // Stable: equal starts keep the cue order (as Python's sort does).
  return out.sort((a, b) => a.from - b.from);
};

// ------------------------------------------------------------------ the document's pass
const defaultName = (t: SoundTemplate): string => {
  const s = t.defaults?.sfx;
  if (s && typeof s === "object") return String(s.name || "none");
  return typeof s === "string" && s ? s : "none";
};

/**
 * The editor's pick for a look's sound: "none" silences it (the string
 * "none" always), another name replaces its design with that one hit, null
 * keeps the design (a resolved {name, volume} equal to the default included).
 */
export const sfxChoice = (ov: SoundOverlay, t: SoundTemplate): string | null => {
  const dflt = defaultName(t);
  const raw = ov?.sfx;
  if (raw && typeof raw === "object") {
    const got = String((raw as { name?: unknown }).name || "");
    return got && got !== "default" && got !== dflt ? got : null;
  }
  if (typeof raw === "string" && raw) {
    if (raw === "none") return "none";
    return raw !== "default" && raw !== dflt ? raw : null;
  }
  return null;
};

export type LookMode = "own" | "self" | "cues" | "none";

/**
 * How a look sounds: "own" (its component plays its own <Audio>), "self"
 * (the component schedules its cues with useLookSound), "cues" (the
 * registry design, <LookSounds>), "none". Registry designs play only on
 * documents that carry them (doc.lookSounds); older documents keep their sfx rows.
 */
export const lookMode = (t: SoundTemplate | undefined | null, ov: SoundOverlay, builtIn: boolean): LookMode => {
  if (!t) return "none";
  const d = t.defaults || {};
  if (d.ownSound || d.ownSfx) return "own";
  const choice = sfxChoice(ov, t);
  if (choice === "none") return "none";
  if (d.soundTiming === "look") return "self";
  if (!builtIn || !Array.isArray(d.sounds)) return "none";
  if (choice) return "cues";
  const text = textOf(ov);
  const value = valueOf(ov);
  return d.sounds.some((c) => c && typeof c === "object" && cueLive(c, text, value)) ? "cues" : "none";
};

/** The cues a look plays: its design, or the editor's one sound on its hit. */
export const entryCues = (t: SoundTemplate, ov: SoundOverlay, mode: LookMode, data: SoundData = SOUND_DATA): SoundCue[] => {
  const d = t.defaults || {};
  const choice = mode === "cues" ? sfxChoice(ov, t) : null;
  if (choice && choice !== "none") {
    const at = num(d.sfxAt);
    return [{ name: choice, at: at ? at : data.levels.defaultHit }];
  }
  return (Array.isArray(d.sounds) ? d.sounds : []).filter((c) => c && typeof c === "object");
};

export interface LookEntry {
  start: number;
  frames: number;
  template?: SoundTemplate | null;
  overlay: SoundOverlay;
  /** Where it comes from: the index in overlays, or in scenes (an animation scene). */
  ref?: { overlay?: number; scene?: number };
}

export interface LookState {
  mode: LookMode;
  muted: boolean;
  take: string | null;
}

type SceneLike = { startFrame?: unknown; durationInFrames?: unknown; text?: unknown; media?: { type?: unknown } | null;
  animation?: unknown };
type OverlayLike = SoundOverlay & { template?: unknown; startFrame?: unknown; durationInFrames?: unknown };

/** Every look of a document, in the renderer's order: the overlays, then the full-screen animation scenes. */
export const lookEntries = (overlays: readonly OverlayLike[] | undefined | null, scenes: readonly SceneLike[] | undefined | null,
  templateOf: (id?: string) => SoundTemplate | undefined | null): LookEntry[] => {
  const out: LookEntry[] = [];
  (overlays || []).forEach((ov, i) => {
    if (!ov || typeof ov !== "object") return;
    out.push({ start: Math.trunc(numOr(ov.startFrame, 0)), frames: Math.trunc(numOr(ov.durationInFrames, 0)),
      template: templateOf(typeof ov.template === "string" ? ov.template : "") || null, overlay: ov, ref: { overlay: i } });
  });
  (scenes || []).forEach((sc, i) => {
    if (!sc || typeof sc !== "object" || sc.media?.type !== "animation") return;
    const spec = (sc.animation && typeof sc.animation === "object" ? sc.animation : {}) as OverlayLike;
    out.push({ start: Math.trunc(numOr(sc.startFrame, 0)), frames: Math.trunc(numOr(sc.durationInFrames, 0)),
      template: templateOf(typeof spec.template === "string" ? spec.template : "") || null,
      overlay: { ...spec, text: spec.text || sc.text || "" }, ref: { scene: i } });
  });
  return out;
};

const protectedKind = (t: SoundTemplate, data: SoundData): boolean => {
  const cues = t.defaults?.sounds || [];
  if (cues.some((c) => c && (c.kind === "typing" || c.fixed))) return true;
  return (t.cues || []).some((c) => data.levels.dateCues.includes(c))
    || data.levels.protectedComponents.includes(t.component || "");
};

/**
 * The document's one pass over its looks: each look's mode, whether it is
 * muted (of two looks starting within clashSeconds only the stronger one
 * sounds: emphasis, then a typing or date look alone on screen, then the
 * first), and the typing take it plays (the owner's keyboards in turn).
 */
export const planLooks = (entries: readonly LookEntry[], fps: number, builtIn: boolean,
  data: SoundData = SOUND_DATA): LookState[] => {
  const f = Math.floor(numOr(fps, BASE_FPS)) || BASE_FPS;
  const clash = jr(data.levels.clashSeconds * f);
  const states: LookState[] = entries.map((e) => ({ mode: lookMode(e.template, e.overlay || {}, builtIn), muted: false,
    take: null }));
  const spans = entries.map((e) => {
    const a = Math.trunc(numOr(e.start, 0));
    return [a, a + Math.max(1, Math.trunc(numOr(e.frames, 0)))] as const;
  });
  const alone = (i: number) => !spans.some(([a, b], j) => j !== i && a < spans[i][1] && spans[i][0] < b);
  const rank = (i: number): number[] => {
    const t = entries[i].template || {};
    const ov = entries[i].overlay || {};
    const emph = typeof ov.emphasis === "string" && ov.emphasis in RANK ? ov.emphasis : t.emphasis;
    const r = typeof emph === "string" && emph in RANK ? RANK[emph] : 1;
    return [r, protectedKind(t, data) && alone(i) ? 0 : 1, spans[i][0], i];
  };
  const less = (x: number[], y: number[]) => {
    for (let q = 0; q < x.length; q++) if (x[q] !== y[q]) return x[q] < y[q];
    return false;
  };
  const order = states.map((_, i) => i).filter((i) => states[i].mode === "cues" || states[i].mode === "self")
    .sort((a, b) => spans[a][0] - spans[b][0] || a - b);
  const kept: number[] = [];
  for (const i of order) {
    const rival = kept.find((k) => Math.abs(spans[i][0] - spans[k][0]) <= clash);
    if (rival === undefined) kept.push(i);
    else if (less(rank(i), rank(rival))) {
      kept[kept.indexOf(rival)] = i;
      states[rival].muted = true;
    } else states[i].muted = true;
  }
  const takes = data.levels.typingTakes.filter((t) => shipped(t, data));
  let n = 0;
  for (const i of order) {
    const st = states[i];
    if (st.muted || st.mode !== "cues" || !takes.length) continue;
    const t = entries[i].template;
    if (t && entryCues(t, entries[i].overlay || {}, st.mode, data).some((c) => c.kind === "typing")) {
      st.take = takes[n % takes.length];
      n += 1;
    }
  }
  return states;
};

// ------------------------------------------------------------------ a whole document
export interface DocLike {
  fps?: unknown;
  overlays?: readonly OverlayLike[] | null;
  scenes?: readonly SceneLike[] | null;
  lookSounds?: unknown;
  meta?: unknown;
  sfxEnabled?: unknown;
  sfxVolume?: unknown;
}

/** One look's sound plan: its entry, its state, what to schedule with, and its design (registry cues or the editor's one sound). */
export interface LookPlan {
  key: string;
  /** Its index among the document's looks (lookEntries). */
  index: number;
  entry: LookEntry;
  state: LookState;
  ctx: ScheduleContext;
  on: boolean;
  design: SoundCue[];
}

/** Whether a document's looks play their built-in sounds (doc.lookSounds present: an object, or true). */
export const lookSoundsOn = (doc: DocLike): boolean =>
  doc.lookSounds === true || (typeof doc.lookSounds === "object" && doc.lookSounds !== null);

/**
 * Every sounding look of a document ("o<index>" an overlay, "s<index>" an
 * animation scene), from one pass (planLooks), with what each is scheduled
 * with: the look's length, the voice (meta.voiceLufs), the pack's intensity
 * (lookSounds.intensity), the overlay's soundGain, the document's sfxVolume.
 */
export const planDocSounds = (doc: DocLike, fps: number, templateOf: (id?: string) => SoundTemplate | undefined | null,
  data: SoundData = SOUND_DATA): LookPlan[] => {
  const entries = lookEntries(doc.overlays, doc.scenes, templateOf);
  const states = planLooks(entries, fps, lookSoundsOn(doc), data);
  const settings = (doc.lookSounds && typeof doc.lookSounds === "object" ? doc.lookSounds : {}) as { intensity?: unknown };
  const meta = (doc.meta && typeof doc.meta === "object" ? doc.meta : {}) as { voiceLufs?: unknown };
  const out: LookPlan[] = [];
  entries.forEach((e, i) => {
    const st = states[i];
    if (st.mode !== "cues" && st.mode !== "self") return;
    const t = e.template || {};
    const ov = e.overlay as SoundOverlay;
    const ctx: ScheduleContext = {
      fps, frames: e.frames, text: textOf(ov), value: valueOf(ov), take: st.take,
      defaultFrames: jr(numOr(t.defaults?.duration, 0) * fps), voice: meta.voiceLufs,
      intensity: numOr(settings.intensity, 1), gain: numOr(ov.soundGain, 1), master: numOr(doc.sfxVolume, 1),
      items: Array.isArray(ov.items) ? ov.items.length : 0, locations: Array.isArray(ov.locations) ? ov.locations.length : 0,
    };
    out.push({ key: e.ref?.scene !== undefined ? `s${e.ref.scene}` : `o${e.ref?.overlay ?? i}`, index: i, entry: e, state: st, ctx,
      on: doc.sfxEnabled !== false && !st.muted, design: entryCues(t, ov, st.mode, data) });
  });
  return out;
};

/**
 * Every sound a document's looks play, in absolute frames - self-timed looks
 * counted with their registry design (their component's own frames depend on
 * the drawing). The Python twin is sfxplan.doc_look_sounds.
 */
export const docLookSounds = (doc: DocLike, fps: number, templateOf: (id?: string) => SoundTemplate | undefined | null,
  data: SoundData = SOUND_DATA) => {
  const out: (ScheduledSound & { startFrame: number; look: number })[] = [];
  for (const p of planDocSounds(doc, fps, templateOf, data)) {
    if (!p.on) continue;
    for (const s of scheduleCues(p.design, p.ctx, data)) out.push({ ...s, startFrame: p.entry.start + s.from, look: p.index });
  }
  return out.sort((a, b) => a.startFrame - b.startFrame || a.look - b.look);
};
