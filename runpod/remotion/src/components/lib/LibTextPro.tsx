import React from "react";
import { AbsoluteFill } from "remotion";
import { TYPEWRITER } from "../fonts";
import type { Overlay, OverlayItem } from "../../types";
import { useLookSound } from "./LookSounds";
import type { SoundCue } from "./lookSoundPlan";
import {
  ANTON, ANTON_CAP, ANTON_TOP, CREAM, Caps, CornerShade, type CSS, Glyphs, type Look, MASK, SERIF_ITAL, SERIF_TEXT, SOFT,
  SUBLINE, Stage, Vignette, WHITE, type Clock, antonEm, clamp01, easeIn, easeInOut, easeOut, glyphY, inkOn, jitter, lerp,
  outOf, prog, pushOf, px, readable, rgba, serifEm, settle, shadow, useClock, useSvgId, wordTicks, wrapBalanced,
} from "./nxKit";
import { clip, digits, str, trimEnds } from "./nxFormat";

/**
 * TEXT PRO (family "tx-"): twelve looks for the narration's own words, set
 * the way a top documentary's title designer sets them - one clear device
 * each, one place each, the video's one accent, never a bar or an underline
 * beside or under a long line (the owner's rule). Built from the owner's
 * VidRush reference (the serif sentence with its gold marker, the type-writer
 * lower third, the centred serif quote) and an editorial title vocabulary:
 *
 *   tx-sentence-highlight  LOWER LEFT  the spoken sentence types in serif; its key phrase gets a gold
 *                                      marker that wipes in as it types, the phrase in dark italic on it
 *   tx-typewriter-lower    LOWER LEFT  a type-writer lower third: the name types in, its line under it,
 *                                      a block cursor blinking after (the typing contract)
 *   tx-kicker-headline     LOWER LEFT  a small accent kicker over a clean Anton headline whose words rise
 *                                      out of their masks, the key word in the accent
 *   tx-word-kinetic        LOWER LEFT  a short line word by word: the words that carry it in Anton caps,
 *                                      the small words in serif italic, each landing with a soft settle
 *   tx-quote-serif         CENTRE      VidRush's quote: serif lines fading in word by word as if spoken,
 *                                      the speaker and role small under it
 *   tx-pull-quote          MID LEFT    an editorial pull-quote: a large accent quotation mark, the quote in
 *                                      serif rising line by line, the key words in italic
 *   tx-statement-card      RIGHT       an official statement on a dark glass card: the source as its
 *                                      header, the words in serif italic, the role under them
 *   tx-name-card           LOWER LEFT  a name in Anton pulled into focus as its tracking closes, the role
 *                                      and organisation under it
 *   tx-question            LOWER LEFT  the question in serif italic word by word, its question mark drawn
 *                                      in the accent and filled
 *   tx-contrast            LOWER LEFT  two lines that turn on each other: the first lands, steps back and
 *                                      dims as the second rises in the accent
 *   tx-ink-reveal          LOWER LEFT  a serif headline revealed by an organic ink-edged wipe, a kicker
 *                                      over it
 *   tx-notice              LOWER LEFT  a tasteful warning: an accent triangle draws itself, the warning as
 *                                      said beside it, one soft pulse
 *
 * Only the overlay's words are set (text / highlight / label / subtitle /
 * items as the plan gave them - the narration's own; src/treatments.py
 * text_line_props); spoken numbers are shown in digits. Sounds are scheduled
 * on the real frames (useLookSound) and stay soft: a text swoosh, a marker, a
 * type-writer for a typed line, a soft tick per landing word.
 */

// ------------------------------------------------------------------ words
const said = (v: unknown, max = 160): string => clip(trimEnds(digits(str(v))), max);
const SMALL = new Set(["a", "an", "the", "of", "in", "on", "at", "to", "for", "by", "and", "or", "but", "is", "are", "was",
  "were", "be", "its", "it's", "it", "as", "from", "with", "than", "that", "this", "into", "out", "not", "no", "so", "yet"]);
const bareOf = (w: string) => w.toLowerCase().replace(/[^a-z0-9'%$]/g, "");
/** [before, phrase, after] when `phrase` is in `text` (case and spacing aside), else null. */
const splitOn = (text: string, phrase: string): [string, string, string] | null => {
  const p = trimEnds(phrase);
  if (!p) return null;
  const i = text.toLowerCase().indexOf(p.toLowerCase());
  return i < 0 ? null : [text.slice(0, i), text.slice(i, i + p.length), text.slice(i + p.length)];
};
/** The key words: the highlight's words, else the longest word that carries meaning. */
const keyWords = (words: string[], highlight: string): boolean[] => {
  const hw = highlight.split(/\s+/).map(bareOf).filter(Boolean);
  const bw = words.map(bareOf);
  const out = words.map(() => false);
  if (hw.length) {
    for (let i = 0; i + hw.length <= bw.length; i++) {
      if (hw.every((h, j) => bw[i + j] === h)) {
        for (let j = 0; j < hw.length; j++) out[i + j] = true;
        return out;
      }
    }
    bw.forEach((b, i) => {
      if (hw.includes(b) && !SMALL.has(b)) out[i] = true;
    });
    if (out.some(Boolean)) return out;
  }
  let best = -1;
  let len = 4;
  bw.forEach((b, i) => {
    if (!SMALL.has(b) && b.length > len) {
      best = i;
      len = b.length;
    }
  });
  if (best >= 0) out[best] = true;
  return out;
};
/** A soft entrance swoosh for words (never a hit). */
const swoosh = (at: number, gain = -6): SoundCue => ({ name: "swoosh-text", alt: ["whoosh-soft-v2", "whoosh-soft"], at, gain_db: gain });

// ================================================================== tx-sentence-highlight
/**
 * VidRush's sentence highlight: the sentence types in a warm serif a letter
 * at a time (soft, no cursor); as the key phrase types, a gold marker wipes in
 * under it and the phrase sets in dark italic on the marker.
 */
const SentenceHighlight: Look = ({ overlay, accent }) => {
  const t = useClock();
  const { k } = t;
  const text = said(overlay.text, 150);
  const parts = splitOn(text, said(overlay.highlight, 60)) || (() => {
    // No phrase given: the words that carry the most meaning (the longest), as said.
    const ws = text.split(" ");
    const key = keyWords(ws, "");
    const i = key.indexOf(true);
    if (i < 0) return [text, "", ""] as [string, string, string];
    const before = ws.slice(0, i).join(" ");
    return [before ? `${before} ` : "", ws[i], ws.slice(i + 1).length ? ` ${ws.slice(i + 1).join(" ")}` : ""] as [string, string, string];
  })();
  // A marker holds a few words on one line (VidRush's "less rain"): a longer phrase keeps its first words marked.
  const [before, phrase0, after0] = parts;
  const phrase = phrase0.length > 26 ? clip(phrase0, 26) : phrase0;
  const after = `${phrase0.slice(phrase.length)}${after0}`;
  const marker = mixMarker(accent);
  const all = `${before}${phrase}${after}`;
  const n = Array.from(all).length;
  const per = Math.min(0.8, 34 / Math.max(1, n));       // the whole line types in at most ~40 frames
  const T0 = 4;
  const startOf = (i: number) => T0 + i * per;
  const pa = Array.from(before).length;
  const pb = pa + Array.from(phrase).length;
  const typedEnd = startOf(n);
  const size = (n > 90 ? 50 : n > 60 ? 54 : 58) * k;
  const maxW = Math.min(0.52 * t.width, 1000 * t.kw);
  const out = outOf(t, 9);
  const mp = phrase ? clamp01((t.f - startOf(pa) + 1.5) / Math.max(1, (pb - pa) * per + 2)) : 0;
  const sound = useLookSound(phrase ? [{ name: "marker-draw", alt: ["marker-underline", "marker"], at: Math.round(startOf(pa)), align: "start",
    gain_db: -7 }] : [swoosh(3, -8)]);
  const letter = (c: string, i: number, ink?: string) => {
    const p = prog(t.f, startOf(i), 4);
    return <span key={i} style={{ opacity: p, color: ink }}>{c}</span>;
  };
  const run = (s: string, from: number) => {
    // Words stay whole (no break inside a word); the spaces between them wrap.
    const nodes: React.ReactNode[] = [];
    let i = from;
    for (const part of s.split(/(\s+)/)) {
      if (!part) continue;
      if (/^\s+$/.test(part)) {
        nodes.push(" ");
        i += Array.from(part).length;
        continue;
      }
      const chars = Array.from(part);
      nodes.push(<span key={`w${i}`} style={{ display: "inline-block", whiteSpace: "nowrap" }}>{chars.map((c, j) => letter(c, i + j))}</span>);
      i += chars.length;
    }
    return nodes;
  };
  const ink = inkOn(marker) === "#ffffff" ? "#ffffff" : "#17130c";
  return (
    <AbsoluteFill>
      {sound}
      <CornerShade o={prog(t.f, 0, 10) * out} />
      <Stage t={t} place="lower-left" push={pushOf(t, typedEnd, 0.01)}>
        <div style={{ maxWidth: maxW, fontFamily: SERIF_TEXT, fontWeight: 500, fontSize: size, lineHeight: 1.36, color: "#F7F2E8",
          textWrap: "balance", filter: shadow(k), opacity: out, transform: `translateY(${((1 - out) * -10 * k).toFixed(2)}px)` } as CSS}>
          {run(before, 0)}
          {phrase ? (
            <span style={{ position: "relative", display: "inline-block", whiteSpace: "nowrap", padding: "0 0.16em", margin: "0 -0.04em" }}>
              <span style={{ position: "absolute", left: 0, right: 0, top: "0.12em", bottom: "0.06em", background: marker, borderRadius: "0.07em",
                transform: `scaleX(${mp.toFixed(4)})`, transformOrigin: "0% 50%", opacity: mp > 0 ? 1 : 0,
                boxShadow: `0 ${px(3 * k)} ${px(10 * k)} rgba(0,0,0,.25)` }} />
              <span style={{ position: "relative", fontFamily: SERIF_ITAL, fontStyle: "italic", fontWeight: 700, filter: "none" }}>
                {Array.from(phrase).map((c, j) => letter(c, pa + j, ink))}
              </span>
            </span>
          ) : null}
          {run(after, pb)}
        </div>
      </Stage>
    </AbsoluteFill>
  );
};
/** VidRush's marker gold, or the video's own accent when it is not a yellow or gold. */
const mixMarker = (accent: string): string => readable(accent);

// ================================================================== tx-typewriter-lower
/** The typing contract (src/treatments.py TYPE_START): the first letter at frame 6, 2 frames a letter (1 past 48). */
const TYPE_START = 6;
const TypewriterLower: Look = ({ overlay, accent }) => {
  const t = useClock();
  const { k, kw } = t;
  const name = clip(said(overlay.text, 60), 48);
  const line = clip(said(overlay.subtitle || overlay.label, 60), 52);
  const nn = Array.from(name).length;
  const per = nn <= 48 ? 2 : 1;
  const nameEnd = TYPE_START + per * nn;
  const L0 = nameEnd + 4;
  const nl = Array.from(line).length;
  const lineEnd = L0 + nl;
  const typedEnd = line ? lineEnd : nameEnd;
  const shown = (start: number, step: number, count: number) => Math.max(0, Math.min(count, Math.floor((t.f - start) / step) + 1));
  const a = shown(TYPE_START, per, nn);
  const b = line ? shown(L0, 1, nl) : 0;
  const out = outOf(t, 9);
  const after = t.f - typedEnd;
  const cursorOn = t.f >= TYPE_START - 2 && (after < 0 || (after < 24 && Math.floor(after / 5) % 2 === 0));
  const onLine2 = line && t.f >= L0 - 1;
  const size1 = 54 * k;
  const size2 = 31 * k;
  const acc = readable(accent);
  const sound = useLookSound([{ name: "typewriter-clean", alt: ["typewriter", "keys"], at: TYPE_START - 1, align: "start", until: typedEnd,
    gain_db: -6 }]);
  const cursor = (size: number) => (
    <span style={{ display: "inline-block", width: "0.5em", height: "0.72em", marginLeft: "0.08em", verticalAlign: "-0.04em",
      background: acc, opacity: cursorOn ? 0.95 : 0, fontSize: size }} />
  );
  return (
    <AbsoluteFill>
      {sound}
      <CornerShade o={prog(t.f, 0, 10) * out} strength={1.1} />
      <div style={{ position: "absolute", left: 96 * kw, bottom: t.height * 0.25, display: "flex", flexDirection: "column",
        alignItems: "flex-start", opacity: out, filter: shadow(k, true) }}>
        <div style={{ fontFamily: TYPEWRITER, fontWeight: 700, fontSize: size1, lineHeight: 1.1, color: CREAM, whiteSpace: "pre" }}>
          {Array.from(name).slice(0, a).join("")}
          {!onLine2 ? cursor(size1) : null}
        </div>
        {line ? (
          <div style={{ marginTop: 12 * k, fontFamily: TYPEWRITER, fontWeight: 400, fontSize: size2, lineHeight: 1.1, letterSpacing: "0.02em",
            color: "rgba(244,238,226,.82)", whiteSpace: "pre", minHeight: size2 * 1.1 }}>
            {Array.from(line).slice(0, b).join("")}
            {onLine2 ? cursor(size2) : null}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== tx-kicker-headline
const KickerHeadline: Look = ({ overlay, accent }) => {
  const t = useClock();
  const { k } = t;
  const acc = readable(accent);
  const head = said(overlay.text, 80).toUpperCase();
  const kicker = said(overlay.label, 40).toUpperCase();
  const sub = said(overlay.subtitle, 80);
  const words = head.split(" ").filter(Boolean);
  const key = keyWords(words, said(overlay.highlight, 60).toUpperCase());
  const maxW = Math.min(0.5 * t.width, 980 * t.kw);
  const CAP = 64;
  const fit = (() => {
    for (let c = CAP; c >= 44; c -= 2) {
      const size = (c / ANTON_CAP) * k;
      const ls = wrapBalanced(words, maxW, (s) => antonEm(s) * size, 2);
      if (ls.length <= 2 && ls.every((l) => antonEm(l) * size <= maxW + 1)) return { size, lines: ls };
    }
    const size = (44 / ANTON_CAP) * k;
    return { size, lines: wrapBalanced(words, maxW, (s) => antonEm(s) * size, 3) };
  })();
  const T0 = kicker ? 7 : 3;
  const STEP = 1.6;
  let wi = 0;
  const lastAt = T0 + (words.length - 1) * STEP;
  const out = outOf(t, 9);
  const sound = useLookSound([swoosh(T0 - 1)]);
  return (
    <AbsoluteFill>
      {sound}
      <CornerShade o={prog(t.f, 0, 10) * out} />
      <Stage t={t} place="lower-left" push={pushOf(t, lastAt + 8, 0.01)}>
        {kicker ? <div style={{ marginBottom: 18 * k }}><Caps text={kicker} size={23 * k} t={t} at={2} color={acc} track={0.26} /></div> : null}
        {fit.lines.map((l, li) => (
          <div key={li} style={{ display: "flex", marginTop: li ? fit.size * 0.06 : 0 }}>
            {l.split(" ").map((w, j) => {
              const i = wi++;
              return (
                <div key={j} style={{ marginRight: `${0.234 * fit.size}px` }}>
                  <Glyphs text={w} size={fit.size} t={t} enter={T0 + i * STEP} stagger={0.35} exitFrom={i} color={key[i] ? acc : WHITE} />
                </div>
              );
            })}
          </div>
        ))}
        {sub ? (
          <div style={{ marginTop: 16 * k, fontFamily: SERIF_ITAL, fontStyle: "italic", fontWeight: 400, fontSize: 34 * k, color: SOFT,
            maxWidth: maxW, opacity: prog(t.f, lastAt + 4, 10) * out, filter: shadow(k, true),
            transform: `translateY(${((1 - prog(t.f, lastAt + 4, 10)) * 8 * k).toFixed(2)}px)` }}>{sub}</div>
        ) : null}
      </Stage>
    </AbsoluteFill>
  );
};

// ================================================================== tx-word-kinetic
const WordKinetic: Look = ({ overlay, accent }) => {
  const t = useClock();
  const { k } = t;
  const acc = readable(accent);
  const text = said(overlay.text, 90);
  const words = text.split(" ").filter(Boolean).slice(0, 12);
  const key = keyWords(words, said(overlay.highlight, 60));
  const small = words.map((w) => SMALL.has(bareOf(w)) && !key[words.indexOf(w)]);
  const maxW = Math.min(0.5 * t.width, 1000 * t.kw);
  // The line's width: Anton caps for the words that carry it, Playfair italic for the small ones.
  const capFor = (c: number) => {
    const size = (c / ANTON_CAP) * k;
    const width = (ws: string[], off: number) => ws.reduce((a, w, j) => a + (small[off + j] ? serifEm(w, true) * size * 0.92
      : antonEm(w.toUpperCase()) * size) + (j ? 0.26 * size : 0), 0);
    return { size, width };
  };
  let size = (70 / ANTON_CAP) * k;
  let lines: number[][] = [words.map((_, i) => i)];
  for (let c = 72; c >= 46; c -= 2) {
    const { size: s, width } = capFor(c);
    // Two balanced lines when one does not fit.
    if (width(words, 0) <= maxW) {
      size = s;
      lines = [words.map((_, i) => i)];
      break;
    }
    let best: number[][] | null = null;
    let score = Infinity;
    for (let i = 1; i < words.length; i++) {
      const w1 = width(words.slice(0, i), 0);
      const w2 = width(words.slice(i), i);
      const m = Math.max(w1, w2);
      if (m <= maxW && m < score) {
        score = m;
        best = [words.slice(0, i).map((_, j) => j), words.slice(i).map((_, j) => i + j)];
      }
    }
    if (best) {
      size = s;
      lines = best;
      break;
    }
    size = s;
  }
  const STEP = 2.6;
  const T0 = 3;
  const out = outOf(t, 9);
  const ats = words.map((_, i) => T0 + i * STEP);
  const sound = useLookSound(wordTicks(ats.map((a) => a + 3), -11));
  const last = ats[ats.length - 1] || T0;
  return (
    <AbsoluteFill>
      {sound}
      <CornerShade o={prog(t.f, 0, 10) * out} />
      <Stage t={t} place="lower-left" push={pushOf(t, last + 6, 0.012)}>
        {lines.map((ln, li) => (
          <div key={li} style={{ display: "flex", alignItems: "baseline", marginTop: li ? size * 0.1 : 0 }}>
            {ln.map((i) => {
              const p = prog(t.f, ats[i], 7, (x) => x);
              const s = settle(p, 1.4);
              const blur = (1 - p) * 7 * k;
              const q = 1 - outOf(t, 6, i * 0.4);
              const base: CSS = { display: "inline-block", marginRight: `${0.26 * size}px`, opacity: Math.min(1, p * 1.8) * (1 - q),
                transform: `translateY(${((1 - s) * 0.16 + q * 0.2).toFixed(4)}em) scale(${(1.14 - 0.14 * s).toFixed(4)})`,
                transformOrigin: "50% 80%", filter: blur > 0.05 ? `blur(${blur.toFixed(2)}px)` : undefined };
              return small[i] ? (
                <span key={i} style={{ ...base, fontFamily: SERIF_ITAL, fontStyle: "italic", fontWeight: 400, fontSize: size * 0.92,
                  color: "rgba(255,255,255,.92)", lineHeight: 1 }}>{words[i].toLowerCase()}</span>
              ) : (
                <span key={i} style={{ ...base, fontFamily: ANTON, fontSize: size, lineHeight: 1, letterSpacing: "0.012em",
                  color: key[i] ? acc : WHITE }}>{words[i].toUpperCase()}</span>
              );
            })}
          </div>
        ))}
      </Stage>
      <div style={{ display: "none" }}>{jitter(0)}</div>
    </AbsoluteFill>
  );
};

// ================================================================== tx-quote-serif
const QuoteSerif: Look = ({ overlay, accent }) => {
  const t = useClock();
  const { k } = t;
  const acc = readable(accent);
  const quote = said(overlay.text, 180).replace(/^["“”']+|["“”']+$/g, "");
  const who = said(overlay.label, 48);
  const role = said(overlay.subtitle, 64);
  const words = quote.split(" ").filter(Boolean);
  const n = quote.length;
  const size = (n > 120 ? 50 : n > 80 ? 56 : 62) * k;
  const STEP = Math.min(1.8, 34 / Math.max(1, words.length));
  const T0 = 4;
  const end = T0 + (words.length - 1) * STEP + 8;
  const out = outOf(t, 10);
  const sound = useLookSound([{ name: "whoosh-soft-v2", alt: ["whoosh-soft", "swoosh-text"], at: 3, gain_db: -9 }]);
  const attribution = [who, role].filter(Boolean).join(", ");
  const ap = prog(t.f, end, 12);
  return (
    <AbsoluteFill>
      {sound}
      <Vignette o={prog(t.f, 0, 12) * out} centre={0.42} edge={0.68} />
      <Stage t={t} place="center" push={pushOf(t, end, 0.012)}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", maxWidth: Math.min(1360 * t.kw, 0.74 * t.width) }}>
          <div style={{ fontFamily: SERIF_TEXT, fontWeight: 400, fontSize: size, lineHeight: 1.32, color: "#FBF8F2", textAlign: "center",
            textWrap: "balance", filter: shadow(k), opacity: out } as CSS}>
            <span style={{ color: acc, opacity: prog(t.f, T0 - 2, 8), marginRight: "0.06em" }}>“</span>
            {words.map((w, i) => {
              const p = prog(t.f, T0 + i * STEP, 9);
              const blur = (1 - p) * 4 * k;
              return (
                <React.Fragment key={i}>
                  <span style={{ display: "inline-block", opacity: p, transform: `translateY(${((1 - p) * 0.18).toFixed(4)}em)`,
                    filter: blur > 0.05 ? `blur(${blur.toFixed(2)}px)` : undefined }}>{w}</span>
                  {i < words.length - 1 ? " " : null}
                </React.Fragment>
              );
            })}
            <span style={{ color: acc, opacity: prog(t.f, end - 6, 8), marginLeft: "0.04em" }}>”</span>
          </div>
          {attribution ? (
            <div style={{ marginTop: 30 * k, display: "flex", alignItems: "center", opacity: ap * out,
              transform: `translateY(${((1 - ap) * 8 * k).toFixed(2)}px)`, filter: shadow(k, true) }}>
              <span style={{ width: 26 * k, height: Math.max(1.5, 2 * k), background: acc, marginRight: 16 * k, borderRadius: k }} />
              <span style={{ fontFamily: SUBLINE, fontWeight: 600, fontSize: 25 * k, letterSpacing: "0.18em", color: "rgba(255,255,255,.88)",
                textTransform: "uppercase", whiteSpace: "nowrap" }}>{attribution}</span>
            </div>
          ) : null}
        </div>
      </Stage>
    </AbsoluteFill>
  );
};

// ================================================================== tx-pull-quote
const PullQuote: Look = ({ overlay, accent }) => {
  const t = useClock();
  const { k, width: W } = t;
  const acc = readable(accent);
  const quote = said(overlay.text, 170).replace(/^["“”']+|["“”']+$/g, "");
  const who = said(overlay.label, 48).toUpperCase();
  const role = said(overlay.subtitle, 64).toUpperCase();
  const words = quote.split(" ").filter(Boolean);
  const key = keyWords(words, said(overlay.highlight, 60));
  const hasKey = Boolean(said(overlay.highlight, 60));
  const n = quote.length;
  const size = (n > 110 ? 48 : n > 70 ? 54 : 60) * k;
  const maxW = Math.min(0.5 * W, 980 * t.kw);
  const lines = wrapBalanced(words, maxW, (s) => serifEm(s) * size * 1.02, 5);
  const LSTEP = 4;
  const T0 = 6;
  const out = outOf(t, 10);
  const markP = prog(t.f, 1, 12);
  const lastLine = T0 + (lines.length - 1) * LSTEP;
  const ap = prog(t.f, lastLine + 8, 12);
  const sound = useLookSound([{ name: "paper-slide-v2", alt: ["paper-slide", "swoosh-text"], at: 4, gain_db: -6 }]);
  let wi = 0;
  return (
    <AbsoluteFill>
      {sound}
      <AbsoluteFill style={{ opacity: prog(t.f, 0, 12) * out, pointerEvents: "none",
        background: "linear-gradient(90deg, rgba(0,0,0,.72) 0%, rgba(0,0,0,.55) 30%, rgba(0,0,0,.2) 58%, rgba(0,0,0,0) 75%)" }} />
      <Stage t={t} place="mid-left" push={pushOf(t, lastLine, 0.012)}>
        <div style={{ position: "relative", paddingTop: 92 * k }}>
          <div style={{ position: "absolute", left: -10 * k, top: -34 * k, fontFamily: SERIF_TEXT, fontWeight: 700, fontSize: 240 * k, lineHeight: 1,
            color: acc, opacity: markP * out, transform: `scale(${(0.75 + 0.25 * easeOut(markP)).toFixed(4)})`, transformOrigin: "20% 60%",
            filter: shadow(k, true) }}>“</div>
          {lines.map((l, li) => {
            const at = T0 + li * LSTEP;
            const ws = l.split(" ");
            return (
              <div key={li} style={{ clipPath: MASK, marginTop: li ? size * 0.16 : 0 }}>
                <div style={{ fontFamily: SERIF_TEXT, fontWeight: 500, fontSize: size, lineHeight: 1.12, color: WHITE, whiteSpace: "nowrap",
                  transform: `translateY(${glyphY(t, at, t.exit + li * 1.5).toFixed(4)}em)`, filter: shadow(k) }}>
                  {ws.map((w, j) => {
                    const i = wi++;
                    const em = hasKey && key[i];
                    return (
                      <React.Fragment key={j}>
                        <span style={em ? { fontFamily: SERIF_ITAL, fontStyle: "italic", fontWeight: 700, color: acc } : undefined}>{w}</span>
                        {j < ws.length - 1 ? " " : null}
                      </React.Fragment>
                    );
                  })}
                </div>
              </div>
            );
          })}
          {who || role ? (
            <div style={{ marginTop: 34 * k, opacity: ap * out, transform: `translateY(${((1 - ap) * 8 * k).toFixed(2)}px)`, filter: shadow(k, true) }}>
              {who ? <div style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.18em", color: acc, whiteSpace: "nowrap" }}>{who}</div> : null}
              {role ? <div style={{ marginTop: 8 * k, fontFamily: SUBLINE, fontWeight: 600, fontSize: 19 * k, letterSpacing: "0.16em",
                color: "rgba(255,255,255,.72)", whiteSpace: "nowrap" }}>{role}</div> : null}
            </div>
          ) : null}
        </div>
      </Stage>
    </AbsoluteFill>
  );
};

// ================================================================== tx-statement-card
const StatementCard: Look = ({ overlay, accent }) => {
  const t = useClock();
  const { k, kw, width: W, height: H } = t;
  const acc = readable(accent);
  const quote = said(overlay.text, 220).replace(/^["“”']+|["“”']+$/g, "");
  const source = said(overlay.label, 48).toUpperCase();
  const role = said(overlay.subtitle, 64).toUpperCase();
  const words = quote.split(" ").filter(Boolean);
  const n = quote.length;
  const size = (n > 150 ? 34 : n > 100 ? 38 : 42) * k;
  const cardW = Math.min(0.4 * W, 760 * kw);
  const STEP = Math.min(1.4, 36 / Math.max(1, words.length));
  const T0 = 9;
  const end = T0 + (words.length - 1) * STEP + 8;
  const out = outOf(t, 10);
  const enter = prog(t.f, 0, 14);
  const sound = useLookSound([{ name: "ui-swipe", alt: ["swipe", "whoosh-soft-v2"], at: 2, gain_db: -7 }]);
  return (
    <AbsoluteFill>
      {sound}
      <div style={{ position: "absolute", right: 96 * kw, top: H / 2, width: cardW,
        transform: `translate(${((1 - enter) * 50 * k + (1 - out) * 40 * k).toFixed(2)}px, -50%)` }}>
        <div style={{ position: "absolute", inset: 0, borderRadius: 12 * k, opacity: enter * out,
          background: "linear-gradient(165deg, rgba(16,18,24,.78) 0%, rgba(8,9,13,.72) 100%)",
          backdropFilter: "blur(14px) saturate(0.85)", WebkitBackdropFilter: "blur(14px) saturate(0.85)",
          border: `${px(1.2 * k)} solid rgba(255,255,255,.14)`, boxShadow: `0 ${px(24 * k)} ${px(60 * k)} rgba(0,0,0,.45)` } as CSS} />
        <div style={{ position: "relative", padding: `${46 * k}px ${50 * k}px ${44 * k}px`, opacity: out }}>
          {source ? (
            <div style={{ display: "flex", alignItems: "center", marginBottom: 26 * k, opacity: prog(t.f, 4, 10) }}>
              <span style={{ width: 10 * k, height: 10 * k, borderRadius: "50%", background: acc, marginRight: 14 * k,
                boxShadow: `0 0 ${px(10 * k)} ${rgba(acc, 0.7)}` }} />
              <span style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: 21 * k, letterSpacing: "0.2em", color: acc, whiteSpace: "nowrap" }}>{source}</span>
            </div>
          ) : null}
          <div style={{ fontFamily: SERIF_ITAL, fontStyle: "italic", fontWeight: 400, fontSize: size, lineHeight: 1.34, color: "#FBF8F2" }}>
            {words.map((w, i) => {
              const p = prog(t.f, T0 + i * STEP, 8);
              return (
                <React.Fragment key={i}>
                  <span style={{ opacity: p }}>{i === 0 ? `“${w}` : i === words.length - 1 ? `${w}”` : w}</span>
                  {i < words.length - 1 ? " " : null}
                </React.Fragment>
              );
            })}
          </div>
          {role ? (
            <div style={{ marginTop: 26 * k, fontFamily: SUBLINE, fontWeight: 600, fontSize: 18 * k, letterSpacing: "0.18em",
              color: "rgba(255,255,255,.62)", opacity: prog(t.f, end, 10), whiteSpace: "nowrap" }}>{role}</div>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== tx-name-card
const NameCard: Look = ({ overlay, accent }) => {
  const t = useClock();
  const { k } = t;
  const acc = readable(accent);
  const name = said(overlay.text, 40).toUpperCase();
  const role = said(overlay.subtitle, 60).toUpperCase();
  const org = said(overlay.label, 48).toUpperCase();
  const maxW = Math.min(0.5 * t.width, 980 * t.kw);
  const size = Math.min((64 / ANTON_CAP) * k, maxW / Math.max(1, antonEm(name)));
  const p = prog(t.f, 1, 15, easeOut);
  const track = 0.22 * (1 - p) + 0.012;
  const blur = (1 - p) * 12 * k;
  const out = outOf(t, 9);
  const q = 1 - out;
  // One soft light passing across the name once it is in focus.
  const sweep = clamp01((t.f - 13) / 14);
  const sound = useLookSound([swoosh(2, -7)]);
  return (
    <AbsoluteFill>
      {sound}
      <CornerShade o={prog(t.f, 0, 10) * out} />
      <Stage t={t} place="lower-left" push={pushOf(t, 16, 0.01)}>
        <div style={{ position: "relative", fontFamily: ANTON, fontSize: size, lineHeight: 1, letterSpacing: `${track.toFixed(4)}em`, whiteSpace: "nowrap",
          color: WHITE, opacity: Math.min(1, p * 1.4) * (1 - q), filter: `${blur > 0.05 ? `blur(${(blur + q * 8 * k).toFixed(2)}px) ` : q > 0.01 ? `blur(${(q * 8 * k).toFixed(2)}px) ` : ""}${shadow(k)}` }}>
          {name}
          {sweep > 0 && sweep < 1 ? (
            <span aria-hidden style={{ position: "absolute", left: 0, top: 0, color: "transparent",
              backgroundImage: `linear-gradient(105deg, rgba(255,255,255,0) ${(sweep * 140 - 30).toFixed(1)}%, ${rgba(acc, 0.9)} ${(sweep * 140 - 15).toFixed(1)}%, rgba(255,255,255,0) ${(sweep * 140).toFixed(1)}%)`,
              WebkitBackgroundClip: "text", backgroundClip: "text" } as CSS}>{name}</span>
          ) : null}
        </div>
        {role ? (
          <div style={{ marginTop: 18 * k }}>
            <Caps text={role} size={25 * k} t={t} at={10} track={0.16} />
          </div>
        ) : null}
        {org ? (
          <div style={{ marginTop: 12 * k, display: "flex", alignItems: "center" }}>
            <Caps text={org} size={20 * k} t={t} at={14} color={acc} track={0.2} />
          </div>
        ) : null}
      </Stage>
    </AbsoluteFill>
  );
};

// ================================================================== tx-question
const Question: Look = ({ overlay, accent }) => {
  const t = useClock();
  const { k } = t;
  const acc = readable(accent);
  const raw = said(overlay.text, 110);
  const text = raw.replace(/\?+\s*$/, "");
  const words = text.split(" ").filter(Boolean);
  const n = text.length;
  const size = (n > 70 ? 56 : n > 45 ? 64 : 72) * k;
  const maxW = Math.min(0.55 * t.width, 1060 * t.kw);
  const STEP = Math.min(2.2, 30 / Math.max(1, words.length));
  const T0 = 3;
  const qAt = T0 + words.length * STEP + 1;
  const out = outOf(t, 9);
  // The question mark: in the accent, a size up, it drops in from above with a blur and settles.
  const qp = prog(t.f, qAt, 9, (x) => x);
  const qs = settle(qp, 1.2);
  const qBlur = (1 - qp) * 6 * k;
  const sound = useLookSound([...wordTicks(words.map((_, i) => T0 + i * STEP + 3), -12, 8),
    { name: "ui-pop", alt: ["pop", "tick"], at: Math.round(qAt + 5), gain_db: -8 }]);
  return (
    <AbsoluteFill>
      {sound}
      <CornerShade o={prog(t.f, 0, 10) * out} />
      <Stage t={t} place="lower-left" push={pushOf(t, qAt, 0.012)}>
        <div style={{ maxWidth: maxW, fontFamily: SERIF_ITAL, fontStyle: "italic", fontWeight: 500, fontSize: size, lineHeight: 1.22,
          color: "#FBF8F2", textWrap: "balance", filter: shadow(k), opacity: out } as CSS}>
          {words.map((w, i) => {
            const p = prog(t.f, T0 + i * STEP, 8);
            const blur = (1 - p) * 5 * k;
            const isLast = i === words.length - 1;
            const word = (
              <span style={{ display: "inline-block", opacity: p, transform: `translateY(${((1 - p) * 0.2).toFixed(4)}em)`,
                filter: blur > 0.05 ? `blur(${blur.toFixed(2)}px)` : undefined }}>{w}</span>
            );
            return (
              <React.Fragment key={i}>
                {isLast ? (
                  <span style={{ display: "inline-block", whiteSpace: "nowrap" }}>
                    {word}
                    <span style={{ display: "inline-block", marginLeft: "0.05em", fontFamily: SERIF_TEXT, fontStyle: "normal", fontWeight: 700,
                      fontSize: "1.12em", lineHeight: 0.8, color: acc, opacity: Math.min(1, qp * 2),
                      transform: `translateY(${((1 - qs) * -0.45).toFixed(4)}em) rotate(${((1 - qs) * -12).toFixed(2)}deg)`,
                      transformOrigin: "50% 100%", filter: qBlur > 0.05 ? `blur(${qBlur.toFixed(2)}px)` : undefined }}>?</span>
                  </span>
                ) : word}
                {!isLast ? " " : null}
              </React.Fragment>
            );
          })}
        </div>
      </Stage>
    </AbsoluteFill>
  );
};

// ================================================================== tx-contrast
/** The two sides of a contrast: items [line 1, line 2], else text and subtitle, else the line split where it turns. */
const sidesOfContrast = (ov: Overlay): [string, string] => {
  const items: OverlayItem[] = Array.isArray(ov.items) ? ov.items.filter((i) => i && typeof i === "object") : [];
  const a = said(items[0]?.label || items[0]?.text, 70);
  const b = said(items[1]?.label || items[1]?.text, 70);
  if (a && b) return [a, b];
  const text = said(ov.text, 140);
  const sub = said(ov.subtitle, 70);
  if (text && sub) return [text, sub];
  const m = /^(.*?\b(?:not|isn't|wasn't|no longer)\b.*?)[,;.:—–-]+\s*((?:but|it's|it is|it was|now|instead)\b.*)$/i.exec(text);
  return m ? [m[1].trim(), m[2].trim()] : [text, ""];
};
const Contrast: Look = ({ overlay, accent }) => {
  const t = useClock();
  const { k } = t;
  const acc = readable(accent);
  const [l1, l2] = sidesOfContrast(overlay);
  const maxW = Math.min(0.5 * t.width, 980 * t.kw);
  const fitLine = (s: string, cap: number) => {
    const words = s.toUpperCase().split(" ").filter(Boolean);
    for (let c = cap; c >= cap * 0.66; c -= 2) {
      const size = (c / ANTON_CAP) * k;
      const ls = wrapBalanced(words, maxW, (x) => antonEm(x) * size, 2);
      if (ls.every((l) => antonEm(l) * size <= maxW + 1)) return { size, lines: ls };
    }
    const size = ((cap * 0.66) / ANTON_CAP) * k;
    return { size, lines: wrapBalanced(words, maxW, (x) => antonEm(x) * size, 3) };
  };
  const a = fitLine(l1, 52);
  const b = fitLine(l2, 68);
  const T2 = 18;
  const dim = prog(t.f, T2 - 4, 10, easeInOut);
  const out = outOf(t, 9);
  const sound = useLookSound(l2 ? [swoosh(2, -8), swoosh(T2, -6)] : [swoosh(2, -7)]);
  let wi = 0;
  const lineOf = (f: { size: number; lines: string[] }, start: number, color: string) => f.lines.map((l, li) => (
    <div key={li} style={{ display: "flex", marginTop: li ? f.size * 0.06 : 0 }}>
      {l.split(" ").map((w, j) => {
        const i = wi++;
        return (
          <div key={j} style={{ marginRight: `${0.234 * f.size}px` }}>
            <Glyphs text={w} size={f.size} t={t} enter={start + i * 1.4} stagger={0.3} exitFrom={i} color={color} />
          </div>
        );
      })}
    </div>
  ));
  return (
    <AbsoluteFill>
      {sound}
      <CornerShade o={prog(t.f, 0, 10) * out} strength={1.15} />
      <Stage t={t} place="lower-left" push={pushOf(t, T2 + 8, 0.012)}>
        <div style={{ opacity: l2 ? 1 - 0.38 * dim : 1, transform: `translateY(${(-dim * 6 * k).toFixed(2)}px) scale(${(1 - 0.04 * dim).toFixed(4)})`,
          transformOrigin: "0% 100%" }}>
          {lineOf(a, 2, WHITE)}
        </div>
        {l2 ? <div style={{ marginTop: 16 * k }}>{lineOf(b, T2, acc)}</div> : null}
      </Stage>
    </AbsoluteFill>
  );
};

// ================================================================== tx-ink-reveal
/**
 * The mask that reveals a line like ink soaking into paper: a solid wash up
 * to the edge, and along the edge a column of soft round blots (fixed sizes
 * and offsets per line, so the front keeps its shape as it travels) that
 * swell as the front passes - an uneven, feathered front, never a straight
 * wipe. CSS gradient layers (unioned), `p` 0 -> 1 carrying the front from
 * before the line's start to past its end; `w` x `h` is the masked box in px.
 */
const inkMask = (w: number, h: number, p: number, seed: number): string => {
  const edge = -0.2 * w + p * 1.4 * w;
  const layers: string[] = [
    `linear-gradient(90deg, #000 0px, #000 ${Math.max(0, edge - 0.62 * h).toFixed(1)}px, transparent ${Math.max(1, edge - 0.3 * h).toFixed(1)}px)`,
  ];
  const N = 13;
  for (let i = 0; i < N; i++) {
    const j1 = jitter(seed * 13 + i);
    const j2 = jitter(seed * 7 + i * 3 + 1);
    const y = ((i + 0.5) / N) * h + (j2 - 0.5) * (h / N) * 0.8;
    const r = h * (0.17 + 0.22 * j1);
    const x = edge - 0.34 * h + j2 * h * 0.72;
    layers.push(`radial-gradient(circle ${r.toFixed(1)}px at ${x.toFixed(1)}px ${y.toFixed(1)}px, #000 0%, #000 52%, transparent 100%)`);
  }
  return layers.join(", ");
};
const InkReveal: Look = ({ overlay, accent }) => {
  const t = useClock();
  const { k } = t;
  const acc = readable(accent);
  const head = said(overlay.text, 90);
  const kicker = said(overlay.label, 40).toUpperCase();
  const maxW = Math.min(0.55 * t.width, 1060 * t.kw);
  const n = head.length;
  const size = (n > 60 ? 56 : n > 36 ? 66 : 76) * k;
  const lines = wrapBalanced(head.split(" ").filter(Boolean), maxW, (s) => serifEm(s) * size * 1.06, 3);
  const T0 = kicker ? 6 : 3;
  const LEN = 20;
  const out = outOf(t, 10);
  const sound = useLookSound([{ name: "whoosh-soft-v2", alt: ["whoosh-soft", "swoosh-text"], at: T0, gain_db: -7 }]);
  const pad = 30 * k;
  return (
    <AbsoluteFill>
      {sound}
      <CornerShade o={prog(t.f, 0, 10) * out} strength={1.2} />
      <Stage t={t} place="lower-left" push={pushOf(t, T0 + LEN, 0.012)}>
        {kicker ? <div style={{ marginBottom: 14 * k }}><Caps text={kicker} size={23 * k} t={t} at={2} color={acc} track={0.26} /></div> : null}
        {lines.map((l, li) => {
          const p = easeInOut(clamp01((t.f - T0 - li * 5) / LEN));
          const q = 1 - outOf(t, 8, li * 1.5);
          const w = serifEm(l) * size * 1.08 + 2 * pad;
          const h = size * 1.12 + 2 * pad;
          const m = p >= 1 ? undefined : inkMask(w, h, p, 3 + li * 7);
          return (
            <div key={li} style={{ position: "relative", margin: `${li ? size * 0.04 - pad : -pad}px ${-pad}px ${-pad}px`, padding: pad,
              maskImage: m, WebkitMaskImage: m, maskRepeat: "no-repeat", WebkitMaskRepeat: "no-repeat" } as CSS}>
              <div style={{ fontFamily: SERIF_TEXT, fontWeight: 700, fontSize: size, lineHeight: 1.12, color: WHITE, whiteSpace: "nowrap",
                opacity: 1 - q, filter: shadow(k), transform: `translateY(${(q * 0.12).toFixed(4)}em)` }}>{l}</div>
            </div>
          );
        })}
      </Stage>
    </AbsoluteFill>
  );
};

// ================================================================== tx-notice
const Notice: Look = ({ overlay, accent }) => {
  const t = useClock();
  const { k } = t;
  const acc = readable(accent);
  const words = said(overlay.text, 60).toUpperCase();
  const sub = said(overlay.subtitle, 70).toUpperCase();
  const maxW = Math.min(0.46 * t.width, 900 * t.kw);
  const fit = (() => {
    const ws = words.split(" ").filter(Boolean);
    for (let c = 58; c >= 40; c -= 2) {
      const size = (c / ANTON_CAP) * k;
      const ls = wrapBalanced(ws, maxW, (x) => antonEm(x) * size, 2);
      if (ls.every((l) => antonEm(l) * size <= maxW + 1)) return { size, lines: ls };
    }
    const size = (40 / ANTON_CAP) * k;
    return { size, lines: wrapBalanced(ws, maxW, (x) => antonEm(x) * size, 2) };
  })();
  const S = Math.max(96 * k, fit.size * ANTON_CAP * (fit.lines.length > 1 ? 1.75 : 1.6));
  const draw = prog(t.f, 2, 14, easeInOut);
  const bang = prog(t.f, 12, 7);
  const pulse = t.f > 20 ? Math.exp(-(t.f - 20) / 7) * Math.sin(((t.f - 20) / 14) * Math.PI) : 0;
  const ring = clamp01((t.f - 20) / 16);
  const out = outOf(t, 9);
  const per = 3 * 92;
  const sound = useLookSound([{ name: "ui-pop", alt: ["pop", "tick"], at: 13, gain_db: -6 }, swoosh(5, -9)]);
  let wi = 0;
  return (
    <AbsoluteFill>
      {sound}
      <CornerShade o={prog(t.f, 0, 10) * out} />
      <Stage t={t} place="lower-left" push={pushOf(t, 20, 0.01)}>
        <div style={{ display: "flex", alignItems: "center" }}>
          <div style={{ position: "relative", width: S, height: S, marginRight: 30 * k, opacity: out, flex: "none",
            transform: `scale(${(1 + 0.07 * pulse).toFixed(4)})` }}>
            {ring > 0 && ring < 1 ? (
              <svg width={S} height={S} viewBox="0 0 100 100" style={{ position: "absolute", inset: 0, overflow: "visible" }}>
                <path d="M50 8 L94 88 L6 88 Z" fill="none" stroke={acc} strokeWidth={2.5} strokeLinejoin="round"
                  opacity={(1 - ring) * 0.7} transform={`translate(50 60) scale(${(1 + 0.35 * ring).toFixed(4)}) translate(-50 -60)`} />
              </svg>
            ) : null}
            <svg width={S} height={S} viewBox="0 0 100 100" style={{ position: "absolute", inset: 0, overflow: "visible", filter: shadow(k, true) }}>
              <path d="M50 8 L94 88 L6 88 Z" fill={rgba(acc, 0.18 * bang)} stroke={acc} strokeWidth={7} strokeLinejoin="round"
                strokeDasharray={`${(per * draw).toFixed(2)} ${per}`} />
              <g opacity={bang} transform={`translate(50 56) scale(${(0.6 + 0.4 * settle(bang)).toFixed(4)}) translate(-50 -56)`}>
                <rect x={45.5} y={34} width={9} height={30} rx={4.5} fill={acc} />
                <circle cx={50} cy={74.5} r={5.2} fill={acc} />
              </g>
            </svg>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
            {fit.lines.map((l, li) => (
              <div key={li} style={{ display: "flex", marginTop: li ? fit.size * 0.06 : 0 }}>
                {l.split(" ").map((w, j) => {
                  const i = wi++;
                  return (
                    <div key={j} style={{ marginRight: `${0.234 * fit.size}px` }}>
                      <Glyphs text={w} size={fit.size} t={t} enter={8 + i * 1.5} stagger={0.3} exitFrom={i} />
                    </div>
                  );
                })}
              </div>
            ))}
            {sub ? <div style={{ marginTop: 16 * k }}><Caps text={sub} size={24 * k} t={t} at={18} color={SOFT} /></div> : null}
          </div>
        </div>
      </Stage>
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ the looks
export const LOOKS: Record<string, Look> = {
  "tx-sentence-highlight": SentenceHighlight,
  "tx-typewriter-lower": TypewriterLower,
  "tx-kicker-headline": KickerHeadline,
  "tx-word-kinetic": WordKinetic,
  "tx-quote-serif": QuoteSerif,
  "tx-pull-quote": PullQuote,
  "tx-statement-card": StatementCard,
  "tx-name-card": NameCard,
  "tx-question": Question,
  "tx-contrast": Contrast,
  "tx-ink-reveal": InkReveal,
  "tx-notice": Notice,
};

/** The words the sentence highlight marks (tests): [before, phrase, after] as it splits the overlay's words. */
export const sentenceParts = (text: string, highlight: string): [string, string, string] | null => splitOn(said(text, 150), said(highlight, 60));
export { lerp, easeIn, ANTON_TOP };
