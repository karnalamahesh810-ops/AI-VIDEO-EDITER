/**
 * Subtitle cues from the narration's word timings, set the way a
 * professional subtitler would (the Netflix Timed Text Style Guide is the
 * reference): phrase cues of at most two lines of ~42 characters, broken at
 * natural phrase boundaries, each on screen 1-7 s, appearing with its first
 * word and leaving shortly after its last, a 2-frame gap between chained cues
 * (a gap under half a second is closed, so nothing blinks between them).
 *
 * The old captions (until 2026-10-05) showed five words at a time, each word
 * popping and scaling in - a CapCut look the owner rejected ("zooming out on
 * one line - that's crazy"). Nothing here moves: Captions.tsx draws a cue
 * whole, with at most a short opacity fade where it starts or ends alone.
 *
 * Pure functions, no React or Remotion: tests run them under node
 * (tests/test_captions.py), and the editor's Player and the render compute
 * the same cues from the same document.
 */

export interface CueWord {
  text: string;
  start: number;
  end: number;
}

export interface Cue {
  /** Seconds: on screen from `start` (its first word) until `end`. */
  start: number;
  end: number;
  /** One or two lines, each a run of the narration's words. */
  lines: CueWord[][];
  /** The lines' text, joined with "\n". */
  text: string;
  /** The longest line, in characters. */
  width: number;
  /** Starts after a real pause: a short fade in (a chained cue replaces the last one outright). */
  fadeIn: boolean;
  /** Followed by a pause: a short fade out. */
  fadeOut: boolean;
}

export interface CueOptions {
  /** Characters per line (Netflix: 42). */
  maxLineChars?: number;
  /** Seconds a cue stays at least (when the next one leaves room) and at most. */
  minSeconds?: number;
  maxSeconds?: number;
  /** Characters a second a viewer reads comfortably (Netflix adult English: 20). */
  readingCps?: number;
  /** Seconds a cue stays after its last word ends. */
  linger?: number;
  /** A gap shorter than this between two cues is closed (Netflix: 12 frames at 24 fps). */
  chainGap?: number;
  /** Frames between two chained cues (Netflix: 2). */
  gapFrames?: number;
  /** A pause at least this long between two words always ends a cue. */
  breakPause?: number;
  /** Shot changes (seconds): a cue prefers to end on one. */
  shotChanges?: number[];
  fps?: number;
}

export const CUE_DEFAULTS: Required<Omit<CueOptions, "shotChanges">> = {
  maxLineChars: 42,
  minSeconds: 1.0,
  maxSeconds: 7.0,
  readingCps: 20,
  linger: 0.45,
  chainGap: 0.5,
  gapFrames: 2,
  breakPause: 1.2,
  fps: 30,
};

// --------------------------------------------------------------------------- words

const WORDLESS = /^[^\p{L}\p{N}]+$/u;

/**
 * The narration's words cleaned for setting: blanks dropped, times made
 * sane and in order, a lone punctuation token ("—", "...") joined to the word
 * before it rather than set as a word of its own.
 */
export function cleanWords(words: CueWord[]): CueWord[] {
  const out: CueWord[] = [];
  const sorted = (words || [])
    .filter((w) => w && typeof w.text === "string" && w.text.trim() && Number.isFinite(Number(w.start)))
    .map((w) => {
      const start = Math.max(0, Number(w.start));
      const end = Number.isFinite(Number(w.end)) ? Math.max(start, Number(w.end)) : start;
      return { text: w.text.trim().replace(/\s+/g, " "), start, end };
    })
    .sort((a, b) => a.start - b.start);
  for (const w of sorted) {
    const prev = out[out.length - 1];
    // A lone mark, or the rest of a word the aligner split off ("Four" "-foot", "it" "'s").
    const joins = WORDLESS.test(w.text) || /^[-'’]\p{L}/u.test(w.text) || /^n['’]t\b/i.test(w.text);
    if (prev && joins) {
      prev.text = /^[—–-]+$/.test(w.text) ? `${prev.text} ${w.text}` : `${prev.text}${w.text}`;
      prev.end = Math.max(prev.end, w.end);
      continue;
    }
    if (prev && w.start < prev.end) {
      // Overlapping timings (an aligner's rounding): the earlier word ends where this one starts.
      prev.end = Math.max(prev.start, w.start);
    }
    out.push({ ...w });
  }
  return out;
}

// --------------------------------------------------------------------------- where a phrase may break

const SENTENCE_END = /[.!?…]["'”’)\]]*$/;
const CLAUSE_END = /([,;:]["'”’)\]]*|\s?[—–]|--)$/;
// A line or cue may well start with these: conjunctions, relative words, prepositions, a clause's subject.
const BREAK_BEFORE = new Set([
  "and", "but", "or", "nor", "so", "yet", "because", "which", "who", "whom", "whose", "that", "when", "where",
  "while", "until", "unless", "although", "though", "if", "as", "after", "before", "since", "than", "then",
  "to", "of", "in", "on", "at", "for", "with", "from", "by", "into", "onto", "over", "under", "through",
  "across", "about", "against", "between", "during", "without", "within", "along", "around", "behind",
  "beyond", "toward", "towards", "upon", "instead", "despite", "above", "below", "beneath", "underneath",
  "inside", "outside", "near", "past", "like", "among", "throughout", "i", "we", "they", "he", "she", "it",
  "you", "there", "nobody", "everyone", "someone",
]);
// Never end a line or cue on these: an article or determiner leaves its noun, a
// preposition its object, an auxiliary its verb, a subject pronoun its verb.
const NO_BREAK_AFTER = new Set([
  "a", "an", "the", "this", "that", "these", "those", "my", "your", "his", "her", "its", "our", "their",
  "to", "of", "in", "on", "at", "for", "with", "from", "by", "into", "onto", "over", "under", "through",
  "across", "about", "between", "during", "without", "within", "above", "below", "beneath", "near", "among",
  "toward", "towards", "upon", "is", "are", "was", "were", "be", "been",
  "being", "has", "have", "had", "will", "would", "can", "could", "should", "shall", "may", "might", "must",
  "do", "does", "did", "not", "no", "very", "more", "most", "less", "least", "such", "than", "as", "and",
  "or", "but", "nor", "i", "we", "they", "he", "she", "it", "you", "mr.", "mrs.", "ms.", "dr.", "st.", "mt.",
  "every", "each", "some", "any", "all", "both", "few", "many", "much", "one", "two", "three", "what", "how",
]);

const bare = (t: string) => t.toLowerCase().replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}.]+$/gu, "");

/**
 * What it costs to break between word i and word i+1: 0 at a sentence end,
 * 3 at a comma, 6 before a conjunction, preposition or a clause's subject,
 * 12 mid-phrase, more where it would split what belongs together (an article
 * from its noun, an auxiliary from its verb, a name, a number from its unit).
 * A pause in the voice and a shot change make any break cheaper.
 */
export function breakCost(ws: CueWord[], i: number, shots?: Set<number>): number {
  const a = ws[i];
  const b = ws[i + 1];
  if (!b) return 0;
  const t = a.text;
  let c = 12;
  if (SENTENCE_END.test(t)) c = 0;
  else if (CLAUSE_END.test(t)) c = 3;
  else {
    const low = bare(t);
    const next = bare(b.text);
    if (BREAK_BEFORE.has(next)) c -= 6;
    if (NO_BREAK_AFTER.has(low)) c += 10;
    // A name of several words (Glen Canyon Dam) and a number with its unit (1,000 people) stay together.
    if (/^\p{Lu}/u.test(t) && /^\p{Lu}/u.test(b.text) && !NO_BREAK_AFTER.has(low)) c += 8;
    if (/\d/.test(t) && /^[\p{Ll}%]/u.test(b.text)) c += 6;
  }
  const pause = b.start - a.end;
  if (pause >= 0.6) c -= 7;
  else if (pause >= 0.3) c -= 4;
  if (shots && shots.has(i)) c -= 2;
  return Math.max(0, c);
}

// --------------------------------------------------------------------------- lines

interface Split {
  /** Index of the first line's last word (-1: one line). */
  k: number;
  cost: number;
}

/**
 * How words a..b (inclusive) sit on at most two lines of `max` characters:
 * one line when they fit, else the break that reads best - at a natural
 * phrase boundary, the lines as even as possible (a slightly shorter top line
 * preferred), never a single orphan word on a line of its own. null: the
 * words do not fit two lines.
 */
function splitLines(len: (a: number, b: number) => number, costs: number[], a: number, b: number,
  max: number, tail: (a: number, b: number) => number): Split | null {
  if (len(a, b) <= max || a === b) return { k: -1, cost: 0 };
  const n = b - a + 1;
  let best: Split | null = null;
  for (let k = a; k < b; k++) {
    const top = len(a, k);
    const bottom = len(k + 1, b);
    if (top > max || bottom > max) continue;
    const topWords = k - a + 1;
    const bottomWords = b - k;
    // An orphan: one word alone on a line (allowed only when the cue is that short).
    if (n >= 4 && (topWords < 2 || bottomWords < 2)) continue;
    let cost = costs[k] + Math.abs(top - bottom) * 0.12 + tail(a, k);
    if (top > bottom) cost += (top - bottom) * 0.05;          // a pyramid: the top line the shorter
    if (n === 3 && Math.min(topWords, bottomWords) === 1) cost += 4;
    if (!best || cost < best.cost) best = { k, cost };
  }
  return best;
}

// --------------------------------------------------------------------------- cues

/**
 * The cues for a run of words (absolute seconds), segmented by dynamic
 * programming over every place a cue may end: each cue costs where it breaks
 * (a sentence end is free, mid-phrase is dear), how its lines break, and how
 * far it is from a comfortable size (not a flicker of one short word, not a
 * 7-second wall); a pause of `breakPause` or more always ends one.
 */
export function buildCues(input: CueWord[], options: CueOptions = {}): Cue[] {
  const o = { ...CUE_DEFAULTS, ...options };
  const ws = cleanWords(input);
  const n = ws.length;
  if (!n) return [];
  const shots = new Set<number>();
  if (o.shotChanges && o.shotChanges.length) {
    // A shot change "between" two words: it falls between the first one's start and the second one's end.
    const cuts = [...o.shotChanges].sort((x, y) => x - y);
    let c = 0;
    for (let i = 0; i + 1 < n; i++) {
      while (c < cuts.length && cuts[c] < ws[i].end - 0.05) c++;
      if (c < cuts.length && cuts[c] <= ws[i + 1].start + 0.15) shots.add(i);
    }
  }
  const costs = ws.map((_, i) => breakCost(ws, i, shots));
  const prefix = [0];
  for (const w of ws) prefix.push(prefix[prefix.length - 1] + w.text.length);
  const len = (a: number, b: number) => prefix[b + 1] - prefix[a] + (b - a);
  const max = o.maxLineChars;
  // The first words of the next sentence left dangling at the end of a line or cue ("... planned for. So").
  const tail = (a: number, b: number): number => {
    if (b >= n - 1 || SENTENCE_END.test(ws[b].text)) return 0;
    for (let k = b - 1; k >= a; k--) {
      if (SENTENCE_END.test(ws[k].text)) {
        const rest = len(k + 1, b);
        return rest < 24 ? 10 - rest * 0.3 : 0;
      }
    }
    return 0;
  };
  // The last words of the previous sentence opening a cue that goes on into the next ("they could. They ...").
  const head = (a: number, b: number): number => {
    if (a === 0 || SENTENCE_END.test(ws[a - 1].text)) return 0;
    for (let k = a; k < b; k++) {
      if (SENTENCE_END.test(ws[k].text)) {
        const first = len(a, k);
        return first < 16 ? 8 - first * 0.3 : 0;
      }
    }
    return 0;
  };

  const cueCost = (a: number, b: number): { cost: number; split: Split } | null => {
    const split = splitLines(len, costs, a, b, max, tail);
    if (!split) return null;
    const chars = len(a, b);
    const span = ws[b].end - ws[a].start;
    let c = 3;                                              // a cue each: fewer, fuller cues
    if (b < n - 1) c += costs[b] * 1.2;                     // where it ends
    c += split.cost;
    if (chars < 16) c += (16 - chars) * 0.3;                // a flicker of one or two short words
    if (span < o.minSeconds) c += (o.minSeconds - span) * 8;
    if (span > 5) c += (span - 5) * 4;                      // near the 7-second ceiling
    if (split.k >= 0) c += 2.5 + Math.max(0, chars - 64) * 0.1;   // two lines only when they earn it
    c += tail(a, b) + head(a, b);
    const cps = chars / Math.max(span, 0.4);
    if (cps > o.readingCps * 1.4) c += (cps - o.readingCps * 1.4) * 0.3;
    return { cost: c, split };
  };

  // best[i]: the cheapest setting of words 0..i-1; from[i]: where its last cue starts.
  const best = new Array<number>(n + 1).fill(Infinity);
  const from = new Array<number>(n + 1).fill(-1);
  const splits = new Array<Split | null>(n + 1).fill(null);
  best[0] = 0;
  for (let i = 1; i <= n; i++) {
    const b = i - 1;
    for (let a = b; a >= 0; a--) {
      if (a < b) {
        // A long pause inside the cue, more than two lines, past the ceiling: no cue spans it.
        if (ws[a + 1].start - ws[a].end >= o.breakPause) break;
        if (len(a, b) > max * 2) break;
        if (ws[b].end - ws[a].start > o.maxSeconds - 0.25) break;
      }
      if (best[a] === Infinity) continue;
      const cc = cueCost(a, b);
      if (!cc) continue;
      const total = best[a] + cc.cost;
      if (total < best[i]) {
        best[i] = total;
        from[i] = a;
        splits[i] = cc.split;
      }
    }
    if (best[i] === Infinity) {
      // Nothing fits (one word longer than a line): it is a cue of its own.
      best[i] = best[b] + 50;
      from[i] = b;
      splits[i] = { k: -1, cost: 0 };
    }
  }
  const spans: { a: number; b: number; split: Split }[] = [];
  for (let i = n; i > 0; i = from[i]) spans.push({ a: from[i], b: i - 1, split: splits[i] as Split });
  spans.reverse();
  const cues: Cue[] = spans.map(({ a, b, split }) => {
    const words = ws.slice(a, b + 1);
    const lines = split.k < 0 ? [words] : [ws.slice(a, split.k + 1), ws.slice(split.k + 1, b + 1)];
    const texts = lines.map((l) => l.map((w) => w.text).join(" "));
    return {
      start: words[0].start, end: words[words.length - 1].end, lines, text: texts.join("\n"),
      width: Math.max(...texts.map((t) => t.length)), fadeIn: true, fadeOut: true,
    };
  });
  return timeCues(cues, o);
}

/**
 * When each cue leaves: shortly after its last word (`linger`), longer if the
 * text needs it to be read (`readingCps`) or the cue would be under
 * `minSeconds` - never over `maxSeconds`, never into the next cue, and a gap
 * under `chainGap` is closed to `gapFrames` so two cues in a row replace each
 * other without a blink.
 */
export function timeCues(cues: Cue[], options: CueOptions = {}): Cue[] {
  const o = { ...CUE_DEFAULTS, ...options };
  const gap = o.gapFrames / o.fps;
  const out = cues.map((c) => ({ ...c }));
  for (let i = 0; i < out.length; i++) {
    const c = out[i];
    const speechEnd = c.end;
    const chars = c.text.replace(/\n/g, " ").length;
    let end = Math.max(speechEnd + o.linger, c.start + o.minSeconds, c.start + chars / o.readingCps);
    end = Math.min(end, Math.max(speechEnd, c.start + o.maxSeconds));
    const next = out[i + 1];
    if (next) {
      if (end > next.start - gap) end = Math.max(c.start + 1 / o.fps, next.start - gap);
      else if (next.start - end < o.chainGap) end = Math.min(next.start - gap, Math.max(end, c.start + o.maxSeconds));
    }
    c.end = end;
  }
  for (let i = 0; i < out.length; i++) {
    const next = out[i + 1];
    const chained = !!next && next.start - out[i].end <= gap + 1e-6;
    out[i].fadeOut = !chained;
    if (next) next.fadeIn = !chained;
  }
  return out;
}

/** A cue in frames: on screen for frames [from, to). */
export interface FrameCue extends Cue {
  from: number;
  to: number;
}

/**
 * The cues on the frame grid: each starts on the frame its first word does,
 * and a chained cue keeps exactly `gapFrames` clear before the next one.
 */
export function cueFrames(cues: Cue[], fps: number, gapFrames = CUE_DEFAULTS.gapFrames): FrameCue[] {
  const out: FrameCue[] = cues.map((c) => ({ ...c, from: Math.round(c.start * fps), to: Math.round(c.end * fps) }));
  for (let i = 0; i < out.length; i++) {
    const c = out[i];
    const prev = out[i - 1];
    if (prev && c.from < prev.to) c.from = prev.to;          // words a frame apart: never two cues at once
    const next = out[i + 1];
    if (next && (!c.fadeOut || c.to > next.from - gapFrames)) c.to = next.from - gapFrames;
    if (c.to <= c.from) c.to = c.from + 1;
  }
  return out;
}

/** The cue on screen at `frame` (binary search over cues in order), or null. */
export function cueAt(cues: FrameCue[], frame: number): FrameCue | null {
  let lo = 0;
  let hi = cues.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const c = cues[mid];
    if (frame < c.from) hi = mid - 1;
    else if (frame >= c.to) lo = mid + 1;
    else return c;
  }
  return null;
}

/**
 * Every word the narration speaks, from the scenes (absolute seconds), and
 * the shot changes between them. A scene without word timings (an older
 * document, a pasted script) has its text spread evenly over its own frames.
 */
export function narrationWords(scenes: { startFrame: number; durationInFrames: number; text?: string;
  words?: CueWord[] }[], fps: number): { words: CueWord[]; shots: number[] } {
  const words: CueWord[] = [];
  const shots: number[] = [];
  for (const sc of scenes || []) {
    const s0 = sc.startFrame / fps;
    const s1 = (sc.startFrame + sc.durationInFrames) / fps;
    if (words.length) shots.push(s0);
    if (sc.words && sc.words.length) {
      words.push(...sc.words);
      continue;
    }
    const tokens = (sc.text || "").split(/\s+/).filter(Boolean);
    if (!tokens.length) continue;
    const step = Math.max(0.05, (s1 - s0 - 0.2) / tokens.length);
    tokens.forEach((t, i) => words.push({ text: t, start: s0 + 0.1 + i * step, end: s0 + 0.1 + (i + 1) * step - 0.02 }));
  }
  return { words, shots };
}
