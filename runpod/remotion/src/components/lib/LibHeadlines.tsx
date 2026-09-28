import React from "react";
import { AbsoluteFill, Easing, interpolate, interpolateColors, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY, INTER, LABEL } from "../fonts";
import type { Overlay } from "../../types";
import { LetterLine, Scrim, lines, ramp, useHold, useK } from "../pro/ProGraphics";
import { CaseBackdrop } from "../pro/ProCase";

/**
 * Headline reveals (family "hl-"): ten title treatments in the pro style.
 * Condensed caps, the accent for the key word only, every line entering with
 * a designed move and leaving with one in the last ~14 frames.
 *
 *   hl-word-stack     2-4 words stacked, each slamming down with a tiny camera
 *                     shake, a shockwave outline and an accent spine growing
 *   hl-split-line     a rule draws, splits open and the headline slides out
 *                     of the gap; an accent glint runs along the rules
 *   hl-wipe-bar       AE block reveal: an accent bar wipes over each line and
 *                     leaves the words behind it, then wipes them away
 *   hl-keyword-pop    a sentence rising word by word, the key word growing in
 *                     the accent with an underline and a spark burst
 *   hl-focus-pull     words pulled from a soft blur into focus one by one,
 *                     bokeh depth and camera focus brackets locking on
 *   hl-letter-flip    letters rolling in on the X axis like a cube, in
 *                     perspective, cascading, rolling away at the end
 *   hl-outline-fill   a stroked title on a designed backdrop, filling left to
 *                     right behind a slanted glinting front
 *   hl-marker-sweep   an editorial headline on paper, a translucent
 *                     highlighter sweeping behind the key words
 *   hl-center-stack   kicker, title and note centred, three weights, hairline
 *                     rules with accent diamonds drawing outward
 *   hl-ticker-slide   a compact skewed accent band sliding in with parallax
 *                     text, a kicker chip rising from behind it, a sheen
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const expoOut = Easing.bezier(0.16, 1, 0.3, 1);
const expoIn = Easing.bezier(0.7, 0, 0.84, 0);
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const flipEase = Easing.bezier(0.3, 1.32, 0.55, 1);
const markerEase = Easing.bezier(0.45, 0, 0.3, 1);
const INK = "#0c0c0f";
const GOLD = "#d6a83c";

// ------------------------------------------------------------------ helpers
const str = (s: unknown): string => (typeof s === "string" ? s.replace(/\s+/g, " ").trim() : "");
const norm = (w: string): string => w.toLowerCase().replace(/[^\p{L}\p{N}']/gu, "");

/** A deterministic 0..1 hash of a number (never Math.random). */
const rnd = (n: number): number => {
  const x = Math.sin(n * 12.9898 + 78.233) * 43758.5453;
  return x - Math.floor(x);
};
const seedOf = (s: string): number => {
  let h = 7;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 100003;
  return h;
};

const rgb = (hex: string): [number, number, number] | null => {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(str(hex));
  if (!m) return null;
  const h = m[1].length === 3 ? m[1].split("").map((c) => c + c).join("") : m[1];
  const v = parseInt(h, 16);
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
};
/** The accent as a #hex colour, gold when the prop is not a usable hex. */
const safeAccent = (a: string): string => {
  const s = str(a);
  return rgb(s) ? (s[0] === "#" ? s : `#${s}`) : GOLD;
};
const alpha = (hex: string, a: number): string => {
  const c = rgb(hex) || ([214, 168, 60] as [number, number, number]);
  return `rgba(${c[0]},${c[1]},${c[2]},${Math.max(0, Math.min(1, a)).toFixed(3)})`;
};
/** Perceived lightness 0..1 of a #hex colour (0.5 when it is not one). */
const lum = (hex: string): number => {
  const c = rgb(hex);
  return c ? (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255 : 0.5;
};
/** Near-black on a light accent, white on a dark one. */
const readableOn = (hex: string): string => (lum(hex) > 0.55 ? INK : "#ffffff");

/** The words to mark: the highlight prop's words that are in the text, else the longest word. */
const keyWords = (text: string, highlight?: string): Set<string> => {
  const inText = text.split(" ").map(norm).filter(Boolean);
  const given = str(highlight).split(/[\s,]+/).map(norm).filter((w) => w && inText.indexOf(w) >= 0);
  if (given.length) return new Set(given);
  const best = inText.reduce((m, w) => (w.length > m.length ? w : m), "");
  return best.length >= 4 ? new Set([best]) : new Set<string>();
};

/**
 * Word-wrap at about `chars` a line like lines(), then even the lines out: the same number of lines,
 * each as close to the same length as possible (no one-word widow such as "...TO ITS / FARMS"), at
 * most `max` lines and never a word dropped. A title too long for `max` lines at `chars` gets longer
 * lines, which the caller shrinks with fit().
 */
const wrap = (text: string, chars: number, max: number): string[] => {
  const t = str(text);
  if (!t) return [];
  const n = Math.max(1, Math.min(max, lines(t, chars).length));
  let w = Math.max(Math.ceil(t.length / n), ...t.split(" ").map((x) => x.length));
  while (lines(t, w).length > n) w += 1;
  return lines(t, w);
};

/** The type scale that keeps the longest line within about `chars` characters' width. */
const fit = (ls: string[], chars: number, min = 0.62): number =>
  Math.max(min, Math.min(1, chars / Math.max(1, ...ls.map((l) => l.length))));

/** A secondary line (kicker, note, source): evened out over `max` lines, cut with an ellipsis past them. */
const upTo = (text: string, chars: number, max: number): string[] => {
  const t = str(text);
  const all = lines(t, chars);
  if (all.length <= max) return wrap(t, chars, max);
  const out = all.slice(0, max);
  out[max - 1] = `${out[max - 1].replace(/[\s,;:.\-–—]+$/, "")}…`;
  return out;
};

/** A headline as stack units: a word a line, a short word (of, is, the...) riding with the next ("IS DYING"). */
const stackOf = (text: string): string[] => {
  const words = text.split(" ").filter(Boolean);
  const out: string[] = [];
  let carry = "";
  for (const w of words) {
    const cur = carry ? `${carry} ${w}` : w;
    if (w.length <= 3 && cur.length <= 7) {
      carry = cur;
      continue;
    }
    out.push(cur);
    carry = "";
  }
  if (carry) {
    if (out.length) out[out.length - 1] = `${out[out.length - 1]} ${carry}`;
    else out.push(carry);
  }
  return out.length >= 2 || words.length < 2 ? out : words;
};

/** The frame clock: the exit starts 14 frames before the end (never before 60% of it). */
const useClock = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const outAt = Math.max(Math.round(durationInFrames * 0.6), durationInFrames - 14);
  return { frame, fps, outAt };
};

/** A per-item exit stagger that always finishes inside the last 14 frames. */
const outStep = (n: number, max: number) => Math.min(max, 4 / Math.max(1, n));

/** A soft local gradient over the footage (nothing when the graphic is the whole frame). */
const Shade: React.FC<{ ov: Overlay; bg: string; outAt: number }> = ({ ov, bg, outAt }) => {
  const frame = useCurrentFrame();
  if (ov.fullFrame) return null;
  const o = ramp(frame, 0, 12) * (1 - ramp(frame, outAt + 3, 10));
  return <AbsoluteFill style={{ background: bg, opacity: o }} />;
};

/**
 * A word or line rising out of its mask and, at the end, rising out of it again. The mask is a clip
 * reaching 0.8 em past the sides and 0.3 em above and below (an overflow box hugging the word cut its
 * soft shadow into a hard-edged rectangle on bright footage); the 140% travel clears it either way.
 */
const Rise: React.FC<{ at: number; outAt: number; frames?: number; children: React.ReactNode;
  style?: React.CSSProperties }> = ({ at, outAt, frames = 14, children, style }) => {
  const frame = useCurrentFrame();
  const pin = ramp(frame, at, frames);
  const pout = ramp(frame, outAt, 10, expoIn);
  const y = (1 - pin) * 140 - pout * 140;
  return (
    <span style={{ display: "inline-block", verticalAlign: "bottom", whiteSpace: "nowrap",
      clipPath: "inset(-0.3em -0.8em -0.3em -0.8em)", ...style }}>
      <span style={{ display: "inline-block", transform: `translateY(${y}%)`, opacity: pin <= 0 || pout >= 1 ? 0 : 1 }}>
        {children}
      </span>
    </span>
  );
};

/**
 * LetterLine's exit start, pulled earlier for long lines: its letters leave 0.6 frame apart over 9 frames,
 * so starting here the last letter of a line up to ~50 characters is gone by outAt + 12.
 */
const letterOut = (outAt: number, len: number) =>
  outAt + 3 - Math.min(30, Math.round(0.6 * Math.max(0, len - 1)));

/**
 * A kicker or note line: evened out over at most two short lines (never running off the frame, cut
 * with an ellipsis past them), each letter rising out of its mask and dropping out again at the end.
 */
const Sub: React.FC<{ text: string; at: number; outAt: number; align?: "center" | "flex-start"; chars?: number;
  step?: number; style: React.CSSProperties; box?: React.CSSProperties }> =
  ({ text, at, outAt, align = "center", chars = 34, step = 0.6, style, box }) => {
    const ls = upTo(text, chars, 2);
    if (!ls.length) return null;
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: align, ...box }}>
        {ls.map((ln, i) => (
          <LetterLine key={i} text={ln} at={at + i * 4} step={step} outAt={letterOut(outAt, ln.length) - 1 + i}
            style={{ textAlign: align === "center" ? "center" : "left", ...style }} />
        ))}
      </div>
    );
  };

/** A line's words, the key words in the accent. */
const Words: React.FC<{ line: string; keys: Set<string>; accent: string; base?: string }> =
  ({ line, keys, accent, base = "#fff" }) => {
    const ws = line.split(" ");
    return (
      <>
        {ws.map((w, j) => (
          <span key={j} style={{ color: keys.has(norm(w)) ? accent : base }}>{w}{j < ws.length - 1 ? " " : ""}</span>
        ))}
      </>
    );
  };

// ================================================================== 1. word stack slam
const WordStack: Look = ({ overlay, accent }) => {
  const { frame, fps, outAt } = useClock();
  const k = useK();
  const hold = useHold();
  const acc = safeAccent(accent);
  const text = str(overlay.text).toUpperCase();
  if (!text) return null;
  // A word a line (short words ride with the next one); a longer headline as up to four even lines.
  let units: string[] = stackOf(text);
  if (units.length > 4) units = wrap(text, Math.max(10, Math.ceil(text.length / 4) + 2), 4);
  if (!units.length) return null;
  const longest = Math.max(...units.map((u) => u.length));
  const base = (longest <= 9 ? 80 : longest <= 15 ? 68 : longest <= 22 ? 56 : 46) * k;
  const keys = keyWords(text, overlay.highlight);
  const hotOf = (u: string) => u.split(" ").some((w) => keys.has(norm(w)));
  const sizes = units.map((u) => (hotOf(u) ? Math.min(86 * k, base * 1.08) : base));
  const LH = 0.94;
  const gap = 4 * k;
  const kicker = str(overlay.subtitle).toUpperCase();
  const step = Math.max(5, Math.round(fps * 0.23));
  const at0 = kicker ? 8 : 3;
  // The camera shake: each landing adds a quickly decaying jolt to the whole stack.
  let sx = 0;
  let sy = 0;
  let spine = 0;
  units.forEach((_, i) => {
    const land = at0 + i * step + 5;
    const t = frame - land;
    if (t >= 0 && t < 18) {
      const d = Math.exp(-t / 3.2) * (i === units.length - 1 ? 1.35 : 1);
      sx += Math.sin(t * 2.9 + i * 1.7) * 6 * k * d;
      sy += Math.cos(t * 3.6 + i) * 5 * k * d;
    }
    spine += (sizes[i] * LH + (i ? gap : 0)) * ramp(frame, land - 1, 6);
  });
  const exitAt = outAt - 3;
  const spineOut = ramp(frame, exitAt + 4, 9, expoIn);
  return (
    <AbsoluteFill>
      <Shade ov={overlay} outAt={outAt}
        bg="linear-gradient(90deg, rgba(0,0,0,.62) 0%, rgba(0,0,0,.34) 32%, rgba(0,0,0,0) 62%)" />
      <AbsoluteFill style={{ justifyContent: "center", paddingLeft: 124 * k }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start",
          transform: `translate(${sx}px, ${sy}px) scale(${hold})`, transformOrigin: "0% 50%" }}>
          {kicker ? (
            <Sub text={kicker} at={0} outAt={outAt} align="flex-start" chars={30} box={{ marginBottom: 14 * k }}
              style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 28 * k, letterSpacing: "0.32em", color: acc,
                textShadow: "0 2px 9px rgba(0,0,0,.6)" }} />
          ) : null}
          <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "flex-start", gap }}>
            <div style={{ position: "absolute", left: -32 * k, top: 0, width: 7 * k, height: spine, background: acc,
              boxShadow: `0 0 ${18 * k}px ${alpha(acc, 0.55)}`, transform: `scaleY(${1 - spineOut})`,
              transformOrigin: "50% 0%" }} />
            {units.map((u, i) => {
              const at = at0 + i * step;
              const land = at + 5;
              const fall = ramp(frame, at, 5, Easing.in(Easing.quad));
              const sc = frame < land ? 1.8 - 0.84 * fall
                : interpolate(frame, [land, land + 3, land + 7], [0.96, 1.025, 1], clamp);
              const ring = ramp(frame, land, 13);
              const streak = frame < land ? 1 - fall : 0;
              const pout = ramp(frame, exitAt + (units.length - 1 - i) * 2, 9, expoIn);
              const hot = hotOf(u);
              return (
                <div key={i} style={{ position: "relative", height: sizes[i] * LH, lineHeight: LH, fontFamily: DISPLAY,
                  fontSize: sizes[i], letterSpacing: "0.02em", whiteSpace: "nowrap",
                  clipPath: pout > 0 ? `inset(-30% ${pout * 100}% -30% -10%)` : undefined,
                  transform: `translateX(${-pout * 30 * k}px)` }}>
                  {ring > 0 && ring < 1 ? (
                    <span style={{ position: "absolute", left: 0, top: 0, color: "transparent",
                      WebkitTextStroke: `${2 * k}px ${hot ? acc : "rgba(255,255,255,.9)"}`,
                      transform: `scale(${1 + 0.16 * ring})`, transformOrigin: "50% 55%", opacity: (1 - ring) * 0.75 }}>
                      {u}
                    </span>
                  ) : null}
                  <span style={{ display: "inline-block", opacity: interpolate(frame, [at - 1, at + 2], [0, 1], clamp),
                    transform: `translateY(${-(1 - fall) * 22}%) scale(${sc})`, transformOrigin: "0% 60%",
                    textShadow: streak > 0
                      ? `0 ${-streak * 26 * k}px 0 ${alpha("#ffffff", 0.16)}, 0 8px 30px rgba(0,0,0,.5)`
                      : "0 8px 30px rgba(0,0,0,.5)" }}>
                    <Words line={u} keys={keys} accent={acc} />
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 2. split-line slide
const SplitLine: Look = ({ overlay, accent }) => {
  const { frame, fps, outAt } = useClock();
  const k = useK();
  const hold = useHold();
  const acc = safeAccent(accent);
  const text = str(overlay.text).toUpperCase();
  if (!text) return null;
  const long = text.length > 44;
  const chars = long ? 34 : 24;
  const ls = wrap(text, chars, 3);
  const size = (long ? 58 : text.length > 26 ? 70 : 84) * k * fit(ls, chars);
  const keys = keyWords(text, overlay.highlight);
  const sub = str(overlay.subtitle).toUpperCase();
  const maxChars = Math.max(1, ...ls.map((l) => l.length));
  const W = Math.min(1480 * k, Math.max(620 * k, maxChars * size * 0.47 + 180 * k));
  const blockH = ls.length * size * 1.02 + 46 * k;
  // The rule draws out from the centre, then splits into two that part to open the gap.
  const draw = ramp(frame, 0, 14) * (1 - ramp(frame, outAt + 5, 8, expoIn));
  const open = ramp(frame, 10, 18) * (1 - ramp(frame, outAt - 3, 9, inOut));
  const gap = open * blockH;
  const top = (blockH - gap) / 2;
  const gl = ramp(frame, 26, Math.round(fps * 1.4), inOut) * 124 - 12;
  const dim = "rgba(255,255,255,.78)";
  const ruleBg = `linear-gradient(90deg, ${dim} 0%, ${dim} ${gl - 7}%, ${acc} ${gl}%, ${dim} ${gl + 7}%, ${dim} 100%)`;
  const rule = (y: number) => (
    <div style={{ position: "absolute", left: "50%", top: y - 1.5 * k, width: W * draw, height: 3 * k,
      transform: "translateX(-50%)", background: ruleBg, boxShadow: "0 2px 12px rgba(0,0,0,.4)" }}>
      {draw > 0.05 ? (
        <>
          <div style={{ position: "absolute", left: 0, top: -6 * k, width: 3 * k, height: 15 * k, background: "#fff" }} />
          <div style={{ position: "absolute", right: 0, top: -6 * k, width: 3 * k, height: 15 * k, background: "#fff" }} />
        </>
      ) : null}
    </div>
  );
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column",
        transform: `scale(${hold})` }}>
        <div style={{ position: "relative", width: W, height: blockH }}>
          <div style={{ position: "absolute", left: -240 * k, right: -240 * k, top, height: gap, overflow: "hidden" }}>
            <div style={{ position: "absolute", left: 0, right: 0, top: -top, height: blockH, display: "flex",
              flexDirection: "column", alignItems: "center", justifyContent: "center",
              transform: `translateY(${(1 - open) * 0.35 * blockH}px)` }}>
              {ls.map((ln, i) => (
                <div key={i} style={{ fontFamily: DISPLAY, fontSize: size, lineHeight: 1.02, letterSpacing: "0.03em",
                  whiteSpace: "nowrap", textShadow: "0 6px 26px rgba(0,0,0,.5)",
                  transform: `translateY(${(1 - ramp(frame, 12 + i * 3, 16)) * 40 * k}px)` }}>
                  <Words line={ln} keys={keys} accent={acc} />
                </div>
              ))}
            </div>
          </div>
          {rule(top)}
          {rule(top + gap)}
        </div>
        {sub ? (
          <Sub text={sub} at={22} outAt={outAt} box={{ marginTop: 26 * k }}
            style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 32 * k, letterSpacing: "0.3em",
              paddingLeft: "0.3em", color: "rgba(255,255,255,.86)" }} />
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 3. wipe-bar reveal
/** One line behind an AE block reveal: the bar covers it, leaves it behind; covers it again at the end. */
const BlockLine: React.FC<{ at: number; outAt: number; bar: string; children: React.ReactNode }> =
  ({ at, outAt, bar, children }) => {
    const frame = useCurrentFrame();
    const k = useK();
    const cover = ramp(frame, at, 9, inOut);
    const uncover = ramp(frame, at + 10, 12, inOut);
    const recover = ramp(frame, outAt, 6, inOut);
    const leave = ramp(frame, outAt + 6, 7, inOut);
    const exiting = frame >= outAt;
    const l = exiting ? (recover < 1 ? 0 : leave) : frame < at + 10 ? 0 : uncover;
    const r = exiting ? recover : frame < at + 10 ? cover : 1;
    const shown = frame >= at + 9 && !(exiting && recover >= 1);
    return (
      <div style={{ position: "relative", display: "inline-block" }}>
        <div style={{ opacity: shown ? 1 : 0, transform: `translateX(${(1 - uncover) * -14 * k}px)` }}>{children}</div>
        {r - l > 0.001 ? (
          <div style={{ position: "absolute", top: 0, bottom: 0, left: `${l * 100}%`, width: `${(r - l) * 100}%`,
            background: bar, boxShadow: "0 8px 24px rgba(0,0,0,.3)" }} />
        ) : null}
      </div>
    );
  };

const WipeBar: Look = ({ overlay, accent }) => {
  const { frame, outAt } = useClock();
  const k = useK();
  const hold = useHold();
  const acc = safeAccent(accent);
  const text = str(overlay.text).toUpperCase();
  if (!text) return null;
  const chars = text.length > 40 ? 32 : 26;
  const ls = wrap(text, chars, 3);
  const size = (text.length > 40 ? 58 : 72) * k * fit(ls, chars);
  const keys = keyWords(text, overlay.highlight);
  const subs = upTo(str(overlay.subtitle).toUpperCase(), 44, 2);
  // Each block needs 13 frames to cover and clear its line and they leave a frame apart; the last one
  // must be fully gone on the final frame (outAt + 13), so the exit starts that many frames early.
  const exitAt = outAt - Math.max(2, ls.length + subs.length - 1);
  const spine = ramp(frame, 0, 12) * (1 - ramp(frame, exitAt + 8, 7, expoIn));
  return (
    <AbsoluteFill>
      <Shade ov={overlay} outAt={outAt}
        bg="linear-gradient(20deg, rgba(0,0,0,.62) 0%, rgba(0,0,0,.28) 30%, rgba(0,0,0,0) 55%)" />
      <div style={{ position: "absolute", left: 110 * k, bottom: 150 * k, display: "flex", gap: 24 * k,
        transform: `scale(${hold})`, transformOrigin: "0% 100%" }}>
        <div style={{ width: 6 * k, background: acc, transform: `scaleY(${spine})`, transformOrigin: "50% 0%",
          boxShadow: `0 0 ${14 * k}px ${alpha(acc, 0.5)}` }} />
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 6 * k }}>
          {ls.map((ln, i) => (
            <BlockLine key={i} at={2 + i * 4} outAt={exitAt + i} bar={acc}>
              <div style={{ fontFamily: DISPLAY, fontSize: size, lineHeight: 1.02, letterSpacing: "0.02em",
                padding: `${4 * k}px ${10 * k}px 0`, whiteSpace: "nowrap", textShadow: "0 6px 24px rgba(0,0,0,.55)" }}>
                <Words line={ln} keys={keys} accent={acc} />
              </div>
            </BlockLine>
          ))}
          {subs.map((sub, j) => (
            <div key={`s${j}`} style={{ marginTop: j ? 0 : 10 * k }}>
              <BlockLine at={6 + (ls.length + j) * 4} outAt={exitAt + ls.length + j} bar="#ffffff">
                <div style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 32 * k, letterSpacing: "0.22em",
                  color: "rgba(255,255,255,.9)", padding: `${6 * k}px ${10 * k}px ${4 * k}px`, whiteSpace: "nowrap",
                  textShadow: "0 3px 14px rgba(0,0,0,.6)" }}>{sub}</div>
              </BlockLine>
            </div>
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 4. scale-pop keyword
const KeywordPop: Look = ({ overlay, accent }) => {
  const { frame, outAt } = useClock();
  const k = useK();
  const hold = useHold();
  const acc = safeAccent(accent);
  const text = str(overlay.text);
  if (!text) return null;
  const count = text.split(" ").length;
  const chars = count > 12 ? 42 : 32;
  const ls = wrap(text, chars, 3);
  const base = (count > 12 ? 46 : count > 7 ? 54 : 62) * k * fit(ls, chars);
  const keys = keyWords(text, overlay.highlight);
  const kicker = str(overlay.subtitle).toUpperCase();
  const n = ls.reduce((a, l) => a + l.split(" ").length, 0);
  const at0 = kicker ? 6 : 2;
  const step = Math.max(1.2, Math.min(4, 36 / Math.max(1, n)));
  // The pop lands once the sentence has risen, and always with time to hold before the exit.
  const popAt = Math.round(Math.min(at0 + (n - 1) * step + 12, Math.max(at0 + 12, outAt - 26)));
  const pop = ramp(frame, popAt, 18, backOut);
  const popCol = interpolateColors(Math.max(0, Math.min(1, pop)), [0, 0.5], ["#ffffff", acc]);
  const burst = ramp(frame, popAt + 2, 16);
  const exitAt = outAt - 2;
  const os = outStep(n, 0.8);
  const font: React.CSSProperties = { fontFamily: INTER, fontWeight: 800, lineHeight: 1.12, letterSpacing: "-0.01em",
    textShadow: "0 4px 24px rgba(0,0,0,.55)" };
  let wi = 0;
  let popped = 0;
  return (
    <AbsoluteFill>
      <Shade ov={overlay} outAt={outAt}
        bg="linear-gradient(to top, rgba(0,0,0,.6) 0%, rgba(0,0,0,.3) 28%, rgba(0,0,0,0) 50%)" />
      <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", paddingBottom: 150 * k }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", maxWidth: 1600 * k,
          transform: `scale(${hold})`, transformOrigin: "50% 100%" }}>
          {kicker ? (
            <Sub text={kicker} at={0} outAt={outAt} box={{ marginBottom: 14 * k }}
              style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 26 * k, letterSpacing: "0.3em", paddingLeft: "0.3em",
                color: acc, textShadow: "0 2px 9px rgba(0,0,0,.6)" }} />
          ) : null}
          {ls.map((ln, li) => (
            <div key={li} style={{ display: "flex", justifyContent: "center", alignItems: "flex-end", columnGap: 0.26 * base }}>
              {ln.split(" ").map((w, j) => {
                const idx = wi++;
                const at = at0 + idx * step;
                const out = exitAt + idx * os;
                const isKey = keys.has(norm(w)) && popped < 2;
                if (isKey) popped += 1;
                if (!isKey) {
                  return <Rise key={j} at={at} outAt={out} style={{ ...font, fontSize: base, color: "#fff" }}>{w}</Rise>;
                }
                const fs = base * (1 + 0.36 * pop);
                const wEst = Math.max(2, w.length) * fs * 0.6;
                const under = pop * (1 - ramp(frame, out, 8, expoIn));
                return (
                  <span key={j} style={{ position: "relative", display: "inline-block",
                    transform: `translateY(${-(fs - base) * 0.16}px)` }}>
                    <Rise at={at} outAt={out} style={{ ...font, fontSize: fs, color: popCol }}>{w}</Rise>
                    <span style={{ position: "absolute", left: "4%", right: "4%", bottom: -3 * k, height: 6 * k,
                      borderRadius: 3 * k, background: acc, transform: `scaleX(${under})`, transformOrigin: "0% 50%",
                      boxShadow: `0 0 ${12 * k}px ${alpha(acc, 0.6)}` }} />
                    {burst > 0 && burst < 1 ? (
                      <svg width={2} height={2} style={{ position: "absolute", left: "50%", top: "50%", overflow: "visible" }}>
                        {Array.from({ length: 8 }, (_, b) => {
                          const a = (b / 8) * Math.PI * 2 + Math.PI / 8;
                          const ux = Math.cos(a);
                          const uy = Math.sin(a);
                          const px = ux * (wEst / 2 + 10 * k);
                          const py = uy * fs * 0.62;
                          const s0 = 8 * k + 34 * k * burst;
                          const len = 26 * k * (1 - burst) + 3 * k;
                          return (
                            <line key={b} x1={px + ux * s0} y1={py + uy * s0} x2={px + ux * (s0 + len)}
                              y2={py + uy * (s0 + len)} stroke={acc} strokeWidth={4 * k} strokeLinecap="round"
                              opacity={1 - burst} />
                          );
                        })}
                      </svg>
                    ) : null}
                  </span>
                );
              })}
            </div>
          ))}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 5. focus pull
const FocusPull: Look = ({ overlay, accent }) => {
  const { frame, fps, outAt } = useClock();
  const k = useK();
  const hold = useHold();
  const { width, height } = useVideoConfig();
  const acc = safeAccent(accent);
  const text = str(overlay.text).toUpperCase();
  if (!text) return null;
  const chars = text.length > 44 ? 32 : 22;
  const ls = wrap(text, chars, 3);
  const size = (text.length > 44 ? 56 : text.length > 24 ? 68 : 82) * k * fit(ls, chars);
  const keys = keyWords(text, overlay.highlight);
  const sub = str(overlay.subtitle).toUpperCase();
  const n = ls.reduce((a, l) => a + l.split(" ").length, 0);
  const step = Math.max(3, Math.min(7, Math.round(42 / Math.max(1, n))));
  const at0 = 4;
  const lockAt = Math.min(at0 + (n - 1) * step + 14, Math.max(at0 + 14, outAt - 30));
  const lock = ramp(frame, lockAt, 14);
  const exitAt = outAt - 2;
  const os = outStep(n, 1.2);
  const appear = ramp(frame, 0, 18);
  const leave = 1 - ramp(frame, exitAt, 12);
  const seed = seedOf(text);
  const t = frame / fps;
  const rack = 1.18 - 0.18 * ramp(frame, 0, 40, expoOut);
  // Bokeh: soft rimmed discs above and below the title band, drifting in parallax.
  const discs = Array.from({ length: 8 }, (_, i) => {
    const s = (110 + rnd(seed + i * 5.7) * 230) * k;
    const x = (0.05 + 0.9 * rnd(seed + i * 7.3)) * width;
    const band = rnd(seed + i * 9.1);
    const y = (band < 0.5 ? 0.05 + band * 0.54 : 0.68 + (band - 0.5) * 0.54) * height;
    const sp = (8 + rnd(seed + i * 3.1) * 14) * k * (i % 2 ? 1 : -1);
    const col = i % 3 === 0 ? acc : "#ffffff";
    const o = (0.07 + rnd(seed + i * 11.9) * 0.1) * appear * leave;
    return (
      <div key={i} style={{ position: "absolute", left: x - s / 2 + sp * t, top: y - s / 2 - sp * 0.5 * t, width: s,
        height: s, borderRadius: "50%", transform: `scale(${rack})`,
        background: `radial-gradient(circle, ${alpha(col, o * 0.55)} 0%, ${alpha(col, o * 0.75)} 58%, ` +
          `${alpha(col, o * 1.15)} 66%, ${alpha(col, 0)} 71%)` }} />
    );
  });
  const bi = (24 + 60 * (1 - lock) + 40 * ramp(frame, exitAt, 12, expoIn)) * k;
  const bo = ramp(frame, 2, 12) * (1 - ramp(frame, exitAt, 10));
  const bc = lock >= 1 && frame < lockAt + 26 ? acc : "rgba(255,255,255,.72)";
  const edge = `${2.5 * k}px solid ${bc}`;
  let wi = 0;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ overflow: "hidden" }}>{discs}</AbsoluteFill>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column",
        transform: `scale(${hold})` }}>
        <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "center",
          padding: `${10 * k}px ${30 * k}px` }}>
          {(["tl", "tr", "bl", "br"] as const).map((c) => (
            <div key={c} style={{ position: "absolute", width: 34 * k, height: 34 * k, opacity: bo,
              top: c[0] === "t" ? -bi : undefined, bottom: c[0] === "b" ? -bi : undefined,
              left: c[1] === "l" ? -bi : undefined, right: c[1] === "r" ? -bi : undefined,
              borderTop: c[0] === "t" ? edge : "none", borderBottom: c[0] === "b" ? edge : "none",
              borderLeft: c[1] === "l" ? edge : "none", borderRight: c[1] === "r" ? edge : "none" }} />
          ))}
          {ls.map((ln, li) => (
            <div key={li} style={{ display: "flex", justifyContent: "center", columnGap: size * 0.28, whiteSpace: "nowrap" }}>
              {ln.split(" ").map((w, j) => {
                const idx = wi++;
                const p = ramp(frame, at0 + idx * step, 20);
                const q = ramp(frame, exitAt + idx * os, 11, expoIn);
                const f = p * (1 - q);
                const vis = Math.min(1, p * 2.2) * (1 - q);
                const col = keys.has(norm(w)) ? acc : "#ffffff";
                const sc = q > 0 ? 1 - 0.12 * q : 1.24 - 0.24 * p;
                return (
                  <span key={j} style={{ display: "inline-block", fontFamily: LABEL, fontWeight: 800, fontSize: size,
                    lineHeight: 1.05, letterSpacing: "0.04em", color: alpha(col, f), opacity: vis,
                    textShadow: `0 0 ${(1 - f) * 24 * k}px ${alpha(col, 0.9 * (1 - f))}, 0 6px 26px rgba(0,0,0,${(0.5 * f).toFixed(3)})`,
                    transform: `scale(${sc}) translateY(${-q * 12 * k}px)` }}>{w}</span>
                );
              })}
            </div>
          ))}
        </div>
        {sub ? (
          <Sub text={sub} at={Math.min(lockAt + 4, outAt - 40)} outAt={outAt} box={{ marginTop: 40 * k }}
            style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 30 * k, letterSpacing: "0.3em",
              paddingLeft: "0.3em", color: acc, textShadow: "0 2px 9px rgba(0,0,0,.6)" }} />
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 6. 3D letter flip
const LetterFlip: Look = ({ overlay, accent }) => {
  const { frame, outAt } = useClock();
  const k = useK();
  const hold = useHold();
  const acc = safeAccent(accent);
  const text = str(overlay.text).toUpperCase();
  if (!text) return null;
  const per = text.length > 34 ? 38 : 28;
  const ls = wrap(text, per, 2);
  const size = (text.length > 34 ? 58 : 76) * k * fit(ls, per);
  const keys = keyWords(text, overlay.highlight);
  const sub = str(overlay.subtitle).toUpperCase();
  const chars = ls.reduce((a, l) => a + l.length, 0);
  const step = Math.max(0.35, Math.min(1.3, 34 / Math.max(1, chars)));
  const exitAt = outAt - 2;
  const os = outStep(chars, 0.45);
  const rule = ramp(frame, 10, 18) * (1 - ramp(frame, exitAt + 3, 8, expoIn));
  let ci = 0;
  return (
    <AbsoluteFill>
      <Shade ov={overlay} outAt={outAt}
        bg="linear-gradient(to bottom, rgba(0,0,0,.58) 0%, rgba(0,0,0,.28) 24%, rgba(0,0,0,0) 44%)" />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "flex-start", paddingTop: 100 * k }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", transform: `scale(${hold})`,
          transformOrigin: "50% 0%" }}>
          {ls.map((ln, li) => {
            const ws = ln.split(" ");
            return (
              <div key={li} style={{ display: "flex", justifyContent: "center", fontFamily: DISPLAY, fontSize: size,
                lineHeight: 1.04, letterSpacing: "0.03em" }}>
                {ws.map((w, wj) => {
                  const hot = keys.has(norm(w));
                  return (
                    <span key={wj} style={{ display: "inline-block", whiteSpace: "pre" }}>
                      {Array.from(wj < ws.length - 1 ? `${w} ` : w).map((c, cj) => {
                        const i = ci++;
                        const pin = ramp(frame, 2 + i * step, 16, flipEase);
                        const pout = ramp(frame, exitAt + i * os, 10, expoIn);
                        const ang = -96 * (1 - pin) + 96 * pout;
                        const light = Math.max(0, Math.cos((ang * Math.PI) / 180));
                        const vis = pin > 0.01 && pout < 0.99 ? 1 : 0;
                        return (
                          <span key={cj} style={{ display: "inline-block", color: hot ? acc : "#fff",
                            transform: `perspective(${520 * k}px) rotateX(${ang}deg)`,
                            transformOrigin: `50% 50% ${-size * 0.32}px`, backfaceVisibility: "hidden",
                            opacity: vis * (0.25 + 0.75 * light), textShadow: "0 6px 22px rgba(0,0,0,.55)" }}>{c}</span>
                        );
                      })}
                    </span>
                  );
                })}
              </div>
            );
          })}
          <div style={{ width: 150 * k, height: 5 * k, margin: `${14 * k}px 0 ${12 * k}px`, background: acc,
            transform: `scaleX(${rule})`, boxShadow: `0 0 ${14 * k}px ${alpha(acc, 0.55)}` }} />
          {sub ? (
            <Sub text={sub} at={14} outAt={outAt}
              style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 30 * k, letterSpacing: "0.26em", paddingLeft: "0.26em",
                color: "rgba(255,255,255,.88)", textShadow: "0 2px 9px rgba(0,0,0,.6)" }} />
          ) : null}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 7. outline to fill
const OutlineFill: Look = ({ overlay, accent }) => {
  const { frame, fps, outAt } = useClock();
  const k = useK();
  const hold = useHold();
  const acc = safeAccent(accent);
  const text = str(overlay.text).toUpperCase();
  if (!text) return null;
  const seed = seedOf(text);
  const per = text.length > 30 ? 24 : 18;
  const ls = wrap(text, per, 3);
  const size = (text.length > 30 ? 66 : text.length > 14 ? 78 : 86) * k * fit(ls, per);
  const keys = keyWords(text, overlay.highlight);
  const sub = str(overlay.subtitle).toUpperCase();
  const chars = ls.reduce((a, l) => a + l.length, 0);
  const step = Math.max(0.5, Math.min(1.1, 26 / Math.max(1, chars)));
  const exitAt = outAt - 2;
  const os = outStep(chars, 0.5);
  // The fill starts once the letters are up, but never so late that it has no time to hold.
  const fillAt = Math.min(Math.round(3 + chars * step + 6), Math.max(12, outAt - 50));
  const fill = ramp(frame, fillAt, Math.round(fps * 1.15), inOut);
  const S = 7;
  const X = fill * (100 + 2 * S) - S;
  const settle = ramp(frame, 0, 30);
  const glyph = (i: number) => {
    const pin = ramp(frame, 3 + i * step, 13);
    const pout = ramp(frame, exitAt + i * os, 9, expoIn);
    return { y: (1 - pin) * 108 - pout * 108, vis: pin > 0.01 && pout < 0.99 ? 1 : 0 };
  };
  // Two identical layers: the outline in flow, the filled copy on top clipped by the slanted front.
  const layer = (mode: "stroke" | "fill") => {
    let ci = 0;
    return ls.map((ln, li) => {
      const ws = ln.split(" ");
      return (
        <div key={li} style={{ overflow: "hidden", padding: "0.04em 0.08em 0.06em", whiteSpace: "pre", textAlign: "center" }}>
          {ws.map((w, wj) => {
            const hot = keys.has(norm(w));
            return (
              <span key={wj} style={{ display: "inline-block" }}>
                {Array.from(wj < ws.length - 1 ? `${w} ` : w).map((c, cj) => {
                  const g = glyph(ci++);
                  const look: React.CSSProperties = mode === "stroke"
                    ? { color: "transparent", WebkitTextStroke: `${2.2 * k}px ${hot ? alpha(acc, 0.95) : "rgba(255,255,255,.9)"}` }
                    : { color: hot ? acc : "#ffffff", textShadow: "0 8px 30px rgba(0,0,0,.4)" };
                  return (
                    <span key={cj} style={{ display: "inline-block", transform: `translateY(${g.y}%)`, opacity: g.vis,
                      ...look }}>{c}</span>
                  );
                })}
              </span>
            );
          })}
        </div>
      );
    });
  };
  const ruleW = ramp(frame, fillAt + 10, 16) * (1 - ramp(frame, exitAt + 4, 8, expoIn));
  return (
    <AbsoluteFill style={{ background: "#040b18" }}>
      <AbsoluteFill style={{ transform: `scale(${1.06 - 0.06 * settle})` }}>
        <CaseBackdrop tone="dark" seed={seed % 7} />
      </AbsoluteFill>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 50%, rgba(3,8,18,.66) 0%, rgba(3,8,18,.28) 45%, rgba(3,8,18,0) 72%)" }} />
      <AbsoluteFill style={{ background: `radial-gradient(ellipse at 50% 48%, ${alpha(acc, 0.16 * fill)} 0%, ${alpha(acc, 0)} 42%)` }} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column",
        transform: `scale(${hold})` }}>
        <div style={{ position: "relative", fontFamily: DISPLAY, fontSize: size, lineHeight: 1.0, letterSpacing: "0.05em" }}>
          <div>{layer("stroke")}</div>
          <div style={{ position: "absolute", inset: 0, clipPath: `polygon(0% -20%, ${X + S}% -20%, ${X - S}% 120%, 0% 120%)` }}>
            {layer("fill")}
          </div>
          {fill > 0 && fill < 1 ? (
            <div style={{ position: "absolute", inset: 0,
              clipPath: `polygon(${X + S - 0.5}% -20%, ${X + S + 0.5}% -20%, ${X - S + 0.5}% 120%, ${X - S - 0.5}% 120%)`,
              background: `linear-gradient(180deg, ${alpha(acc, 0)} 0%, ${acc} 28%, #ffffff 50%, ${acc} 72%, ${alpha(acc, 0)} 100%)` }} />
          ) : null}
        </div>
        <div style={{ width: 130 * k, height: 5 * k, margin: `${26 * k}px 0 ${18 * k}px`, background: acc,
          transform: `scaleX(${ruleW})`, boxShadow: `0 0 ${16 * k}px ${alpha(acc, 0.6)}` }} />
        {sub ? (
          <Sub text={sub} at={fillAt + 14} outAt={outAt}
            style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 32 * k, letterSpacing: "0.34em", paddingLeft: "0.34em",
              color: "rgba(255,255,255,.9)" }} />
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 8. marker sweep
/** A jittered band, the shape of a highlighter stroke (viewBox 100 x 20). */
const roughBand = (s: number): string => {
  const top = [0, 18, 36, 54, 72, 90, 100].map((x, i) => `${x} ${(1 + rnd(s + i * 1.7) * 3).toFixed(2)}`);
  const bot = [100, 82, 64, 46, 28, 10, 0].map((x, i) => `${x} ${(16.5 + rnd(s + 20 + i * 2.3) * 3).toFixed(2)}`);
  return `M${[...top, ...bot].join(" L")} Z`;
};

/** The highlighter behind one word: it sweeps in left to right, its tip leading, and lifts off left to right. */
const Marker: React.FC<{ p: number; r: number; seed: number; color: string; ext: boolean }> =
  ({ p, r, seed, color, ext }) => {
    if (p <= 0 || r >= 1) return null;
    return (
      <span style={{ position: "absolute", left: "-0.12em", right: ext ? "-0.3em" : "-0.12em", top: "0.3em",
        height: "0.72em", transform: "rotate(-1.2deg)", clipPath: `inset(-10% ${(1 - p) * 100}% -10% ${r * 100}%)` }}>
        <svg width="100%" height="100%" viewBox="0 0 100 20" preserveAspectRatio="none"
          style={{ display: "block", overflow: "visible" }}>
          <path d={roughBand(seed)} fill={alpha(color, 0.58)} />
        </svg>
        {p < 1 ? (
          <span style={{ position: "absolute", top: "-4%", bottom: "-4%", left: `calc(${p * 100}% - 0.1em)`,
            width: "0.14em", borderRadius: "0.05em", background: alpha(color, 0.9) }} />
        ) : null}
      </span>
    );
  };

type MarkWord = { w: string; idx: number; key: boolean; order: number; ext: boolean };

const MarkerSweep: Look = ({ overlay, accent }) => {
  const { frame, outAt } = useClock();
  const k = useK();
  const hold = useHold();
  const { width, height } = useVideoConfig();
  // A near-white theme accent would vanish on the paper: the highlighter falls back to gold.
  const acc = lum(safeAccent(accent)) > 0.8 ? GOLD : safeAccent(accent);
  const text = str(overlay.text);
  if (!text) return null;
  const seed = seedOf(text);
  // An editorial headline: even lines of about 34 characters (all of them kept), the type as large as the
  // paper's column allows (Inter 800 runs about 0.55 em a character).
  const ls = wrap(text, 34, 4);
  const size = Math.max(44, Math.min(72, 1380 / (Math.max(1, ...ls.map((l) => l.length)) * 0.55))) * k;
  const keys = keyWords(text, overlay.highlight);
  const kicker = str(overlay.subtitle).toUpperCase();
  const source = str(overlay.label);
  let gi = 0;
  let ko = 0;
  const rows: MarkWord[][] = ls.map((ln) => {
    const ws = ln.split(" ");
    const flags = ws.map((w) => keys.has(norm(w)));
    return ws.map((w, j) => ({ w, idx: gi++, key: flags[j], order: flags[j] ? ko++ : -1,
      ext: j < ws.length - 1 && flags[j + 1] }));
  });
  const n = gi;
  const step = Math.max(1, Math.min(3, Math.round(34 / Math.max(1, n))));
  const at0 = kicker ? 8 : 4;
  const exitAt = outAt - 2;
  // The highlighter sweeps once the sentence is up, but on a short overlay by mid-hold at the latest,
  // and the strokes are spaced so the last one has landed well before they lift off.
  const landAt = Math.min(at0 + n * step + 8, Math.max(at0 + 20, Math.round(outAt * 0.5)));
  const kStep = Math.max(3, Math.min(7, Math.floor((exitAt - 20 - landAt) / Math.max(1, ko))));
  const srcLs = upTo(source, 90, 2);
  const os = outStep(n, 0.7);
  const sq = ramp(frame, 2, 12, backOut) * (1 - ramp(frame, exitAt, 8, expoIn));
  const light = 26 + frame * 0.05;
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 32% 28%, #fdfbf6 0%, #f1ece1 55%, #ddd4c2 100%)" }} />
      <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0 }}>
        {Array.from({ length: 34 }, (_, i) => {
          const x = rnd(seed + i * 1.3) * width;
          const y = rnd(seed + i * 2.9) * height;
          const L = (30 + rnd(seed + i * 4.1) * 70) * k;
          const a = rnd(seed + i * 6.7) * Math.PI;
          const bend = (rnd(seed + i * 8.3) - 0.5) * 20 * k;
          return (
            <path key={i} d={`M${x.toFixed(1)} ${y.toFixed(1)} q${(Math.cos(a) * L / 2 + bend).toFixed(1)} ` +
              `${(Math.sin(a) * L / 2 - bend).toFixed(1)} ${(Math.cos(a) * L).toFixed(1)} ${(Math.sin(a) * L).toFixed(1)}`}
              stroke="#6b5a3c" strokeOpacity={0.05 + rnd(seed + i * 9.7) * 0.06} strokeWidth={1.3 * k} fill="none" />
          );
        })}
      </svg>
      <AbsoluteFill style={{ background: `radial-gradient(ellipse at ${light}% 30%, rgba(255,255,255,.4) 0%, rgba(255,255,255,0) 50%)` }} />
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${280 * k}px rgba(96,74,40,.24)` }} />
      <AbsoluteFill style={{ justifyContent: "center", paddingLeft: "12%", paddingRight: "12%" }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", transform: `scale(${hold})`,
          transformOrigin: "0% 50%" }}>
          {kicker ? (
            <div style={{ display: "flex", alignItems: "center", gap: 14 * k, marginBottom: 22 * k }}>
              <div style={{ width: 14 * k, height: 14 * k, flexShrink: 0, background: acc, transform: `scale(${sq})` }} />
              <Sub text={kicker} at={2} outAt={outAt} align="flex-start" chars={44}
                style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 28 * k, letterSpacing: "0.24em", color: "#5b554c" }} />
            </div>
          ) : null}
          <div style={{ fontFamily: INTER, fontWeight: 800, fontSize: size, lineHeight: 1.14, letterSpacing: "-0.015em",
            color: "#16161a" }}>
            {rows.map((row, ri) => (
              <div key={ri} style={{ display: "flex", flexWrap: "nowrap", alignItems: "flex-end" }}>
                {row.map((x, j) => {
                  const sAt = Math.max(landAt + x.order * kStep, at0 + x.idx * step + 8);
                  const p = x.key ? ramp(frame, sAt, 10, markerEase) : 0;
                  const r = x.key ? ramp(frame, exitAt - 6 + x.order, 8, inOut) : 0;
                  return (
                    <span key={j} style={{ position: "relative", display: "inline-block",
                      marginRight: j < row.length - 1 ? "0.26em" : 0 }}>
                      {x.key ? <Marker p={p} r={r} seed={seed + x.idx * 13} color={acc} ext={x.ext} /> : null}
                      <span style={{ position: "relative" }}>
                        <Rise at={at0 + x.idx * step} outAt={exitAt + x.idx * os}>{x.w}</Rise>
                      </span>
                    </span>
                  );
                })}
              </div>
            ))}
          </div>
          {srcLs.length ? (
            <div style={{ marginTop: 28 * k, display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
              {srcLs.map((ln, i) => (
                <Rise key={i} at={landAt + 4 + i * 3} outAt={exitAt + i} style={{ fontFamily: INTER, fontWeight: 400,
                  fontSize: 24 * k, lineHeight: 1.3, color: "#6f685d", letterSpacing: "0.01em" }}>{ln}</Rise>
              ))}
            </div>
          ) : null}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 9. center stack
const CenterStack: Look = ({ overlay, accent }) => {
  const { frame, outAt } = useClock();
  const k = useK();
  const hold = useHold();
  const acc = safeAccent(accent);
  const main = str(overlay.text).toUpperCase();
  if (!main) return null;
  const kicker = str(overlay.subtitle).toUpperCase();
  const foot = str(overlay.label) || str(overlay.body);
  const per = main.length > 40 ? 30 : 24;
  const ls = wrap(main, per, 3);
  const size = (main.length > 40 ? 60 : main.length > 22 ? 72 : 86) * k * fit(ls, per);
  const fl = upTo(foot, 64, 2);
  const maxChars = Math.max(1, ...ls.map((l) => l.length));
  // A divider narrower than the title: an editorial hierarchy, not a frame round it (that is hl-split-line).
  const W = Math.min(1000 * k, Math.max(380 * k, maxChars * size * 0.36));
  const exitAt = outAt - 2;
  const mainAt = kicker ? 8 : 4;
  // The cinematic tracking-in: the title's letter spacing closes slowly over the whole hold.
  const track = interpolate(frame, [mainAt, Math.max(mainAt + 1, outAt)], [0, 1],
    { ...clamp, easing: Easing.out(Easing.quad) });
  const sp = (0.17 - 0.12 * track).toFixed(4);
  const dash = ramp(frame, 5, 14) * (1 - ramp(frame, exitAt + 2, 8, expoIn));
  const divAt = mainAt + 8 + ls.length * 4;
  const draw = ramp(frame, divAt, 22, inOut) * (1 - ramp(frame, exitAt + 2, 10, inOut));
  const dia = ramp(frame, divAt, 14, backOut) * (1 - ramp(frame, exitAt, 8, expoIn));
  const half = Math.max(0, W / 2 - 18 * k) * draw;
  const dashEl = (origin: string) => (
    <div style={{ width: 46 * k, height: 3 * k, flexShrink: 0, background: acc, transform: `scaleX(${dash})`,
      transformOrigin: origin, boxShadow: `0 0 ${10 * k}px ${alpha(acc, 0.5)}` }} />
  );
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column",
        transform: `scale(${hold})` }}>
        {kicker ? (
          <div style={{ display: "flex", alignItems: "center", gap: 20 * k, marginBottom: 22 * k }}>
            {dashEl("100% 50%")}
            <Sub text={kicker} at={2} outAt={outAt} step={0.7} chars={28}
              style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k, letterSpacing: "0.42em",
                paddingLeft: "0.42em", color: acc, textShadow: "0 2px 9px rgba(0,0,0,.5)" }} />
            {dashEl("0% 50%")}
          </div>
        ) : null}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
          {ls.map((ln, i) => (
            <LetterLine key={i} text={ln} at={mainAt + i * 4} step={0.8} outAt={letterOut(outAt - 2 + i, ln.length)}
              style={{ fontFamily: DISPLAY, fontSize: size, lineHeight: 1.0, letterSpacing: `${sp}em`, paddingLeft: `${sp}em`,
                color: "#fff", textAlign: "center", textShadow: "0 4px 16px rgba(0,0,0,.45)" }} />
          ))}
        </div>
        <div style={{ position: "relative", width: W, height: 16 * k, marginTop: 22 * k, display: "flex",
          alignItems: "center", justifyContent: "center" }}>
          <div style={{ position: "absolute", top: 7 * k, right: "50%", marginRight: 18 * k, width: half, height: 2 * k,
            background: "linear-gradient(270deg, rgba(255,255,255,.85), rgba(255,255,255,0))" }} />
          <div style={{ position: "absolute", top: 7 * k, left: "50%", marginLeft: 18 * k, width: half, height: 2 * k,
            background: "linear-gradient(90deg, rgba(255,255,255,.85), rgba(255,255,255,0))" }} />
          <div style={{ width: 12 * k, height: 12 * k, background: acc, transform: `rotate(45deg) scale(${dia})`,
            boxShadow: `0 0 ${12 * k}px ${alpha(acc, 0.6)}` }} />
        </div>
        {fl.length ? (
          <div style={{ marginTop: 20 * k, display: "flex", flexDirection: "column", alignItems: "center", gap: 4 * k }}>
            {fl.map((ln, i) => (
              <Rise key={i} at={divAt + 6 + i * 3} outAt={exitAt + i * 2}
                style={{ fontFamily: INTER, fontWeight: 400, fontSize: 32 * k, lineHeight: 1.3,
                  color: "rgba(255,255,255,.84)", letterSpacing: "0.01em" }}>{ln}</Rise>
            ))}
          </div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 10. ticker slide
const TickerSlide: Look = ({ overlay, accent }) => {
  const { frame, fps, outAt } = useClock();
  const k = useK();
  const hold = useHold();
  const acc = safeAccent(accent);
  const text = str(overlay.text).toUpperCase();
  if (!text) return null;
  // The chip holds a short label: its first words up to ~24 characters, never a word cut in half.
  const kicker = lines(str(overlay.label).toUpperCase(), 24)[0] || "";
  // The note under the band wraps to two lines at most instead of running off the right of the frame.
  const subs = upTo(str(overlay.subtitle), 56, 2);
  const per = text.length > 30 ? 38 : 30;
  const ls = wrap(text, per, 2);
  const size = (text.length > 30 ? 50 : 62) * k * fit(ls, per);
  const ink = readableOn(acc);
  const SK = -14;
  const exitAt = outAt - 2;
  const band = ramp(frame, 3, 16);
  const chipIn = ramp(frame, 13, 14, backOut);
  const sheen = ramp(frame, 22, Math.round(fps * 0.8), inOut);
  const textOut = ramp(frame, exitAt, 8, expoIn);
  const chipOut = ramp(frame, exitAt - 1, 7, expoIn);
  const wipe = ramp(frame, exitAt + 4, 9, expoIn);
  const notchA = ramp(frame, 9, 14);
  const notchB = ramp(frame, 12, 14);
  return (
    <AbsoluteFill>
      <Shade ov={overlay} outAt={outAt}
        bg="linear-gradient(20deg, rgba(0,0,0,.55) 0%, rgba(0,0,0,.22) 30%, rgba(0,0,0,0) 52%)" />
      <div style={{ position: "absolute", left: 110 * k, bottom: 150 * k, display: "flex", flexDirection: "column",
        alignItems: "flex-start", gap: 18 * k, transform: `scale(${hold})`, transformOrigin: "0% 100%" }}>
        <div style={{ position: "relative", display: "flex", alignItems: "stretch", gap: 8 * k,
          transform: `translateX(${(1 - band) * -118}%)`,
          // Bottom -80%: room for the band's 14/40 px drop shadow (at -30% it was cut in a hard line).
          clipPath: `inset(-140% ${-6 + wipe * 112}% -80% -12%)` }}>
          {kicker ? (
            <div style={{ position: "absolute", left: 18 * k, bottom: "100%", marginBottom: -3 * k, overflow: "hidden",
              padding: `${4 * k}px ${10 * k}px 0` }}>
              <div style={{ transform: `translateY(${(1 - chipIn) * 110 + chipOut * 110}%) skewX(${SK}deg)`,
                background: "#ffffff", padding: `${6 * k}px ${16 * k}px ${4 * k}px`, boxShadow: "0 6px 18px rgba(0,0,0,.35)" }}>
                <div style={{ transform: `skewX(${-SK}deg)`, fontFamily: LABEL, fontWeight: 800, fontSize: 24 * k,
                  letterSpacing: "0.2em", color: INK, whiteSpace: "nowrap" }}>{kicker}</div>
              </div>
            </div>
          ) : null}
          <div style={{ position: "relative", zIndex: 1, overflow: "hidden", transform: `skewX(${SK}deg)`,
            background: `linear-gradient(180deg, rgba(255,255,255,.2) 0%, rgba(255,255,255,0) 55%), ${acc}`,
            padding: `${12 * k}px ${46 * k}px ${8 * k}px ${36 * k}px`, boxShadow: "0 14px 40px rgba(0,0,0,.42)" }}>
            <div style={{ transform: `skewX(${-SK}deg)` }}>
              {ls.map((ln, i) => (
                <div key={i} style={{ transform: `translateX(${-textOut * 120}%)` }}>
                  <div style={{ fontFamily: DISPLAY, fontSize: size, lineHeight: 1.02, letterSpacing: "0.03em", color: ink,
                    whiteSpace: "nowrap", transform: `translateX(${(1 - ramp(frame, 8 + i * 3, 18)) * -90 * k}px)` }}>{ln}</div>
                </div>
              ))}
            </div>
            {sheen > 0 && sheen < 1 ? (
              <div style={{ position: "absolute", top: 0, bottom: 0, left: `${-40 + sheen * 180}%`, width: "30%",
                background: "linear-gradient(90deg, rgba(255,255,255,0), rgba(255,255,255,.42), rgba(255,255,255,0))" }} />
            ) : null}
          </div>
          <div style={{ width: 12 * k, background: acc, opacity: notchA > 0.02 ? 1 : 0,
            transform: `skewX(${SK}deg) translateX(${(1 - notchA) * -40 * k}px)` }} />
          <div style={{ width: 7 * k, background: "rgba(255,255,255,.78)", opacity: notchB > 0.02 ? 1 : 0,
            transform: `skewX(${SK}deg) translateX(${(1 - notchB) * -60 * k}px)` }} />
        </div>
        {subs.length ? (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", marginLeft: 22 * k }}>
            {subs.map((ln, i) => (
              <Rise key={i} at={16 + i * 3} outAt={exitAt + i} style={{ fontFamily: LABEL, fontWeight: 600,
                fontSize: 32 * k, lineHeight: 1.2, color: "#fff", letterSpacing: "0.04em",
                textShadow: "0 3px 14px rgba(0,0,0,.7)" }}>{ln}</Rise>
            ))}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "hl-word-stack": WordStack,
  "hl-split-line": SplitLine,
  "hl-wipe-bar": WipeBar,
  "hl-keyword-pop": KeywordPop,
  "hl-focus-pull": FocusPull,
  "hl-letter-flip": LetterFlip,
  "hl-outline-fill": OutlineFill,
  "hl-marker-sweep": MarkerSweep,
  "hl-center-stack": CenterStack,
  "hl-ticker-slide": TickerSlide,
};
