import React from "react";
import { AbsoluteFill, Easing, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY, INTER, LABEL } from "../fonts";
import type { Overlay, OverlayItem } from "../../types";
import { Scrim, lines, ramp, useHold, useK } from "../pro/ProGraphics";

/**
 * Quotes & statements (family "qs-", registry category QUOTES): ten ways to
 * put somebody's words on screen in the pro house style. Condensed sans and
 * Inter only, words rise out of their masks and leave upward at the end, the
 * accent is kept for the one thing that matters in each look.
 *
 *   qs-giant-marks        oversized accent quote marks spin in over a faint ghost mark, the quote
 *                         rises line by line, the speaker slides out of an accent rule
 *   qs-testimony-rail     own backdrop: an accent rail draws down with a glowing tip, each line slides
 *                         out of the rail as the tip passes it, the speaker at the foot
 *   qs-side-panel         (tag) a frosted panel slides in from the right with the quote, footage stays
 *   qs-but-pivot          the statement, then "BUT" drops between two rules and the reality rises in
 *                         the accent while the statement dims
 *   qs-strike-correction  a claim is struck through in red by a hot spark (the claim shakes and dims),
 *                         the correction rises beneath it
 *   qs-karaoke            the sentence in white, each word filling with the accent in speaking rhythm
 *   qs-zoom-word          a sentence, then the camera dives into its key word; focus brackets snap round
 *   qs-said-stamp         the quote, then a rotating seal with the speaker's name slams down (camera
 *                         shake, shock ring, sparks)
 *   qs-double-cards       two short quotes on two cards that flip over in 3D, a sheen crossing each
 *   qs-whisper            (tag) a lowercase line low on the footage, tracking in from wide, a hairline
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const easeIn = Easing.bezier(0.7, 0, 0.84, 0);
const fallIn = Easing.bezier(0.55, 0, 1, 0.45);
const GOLD = "#d6a83c";
const RED = "#ff3b30";
const WHITE = "#ffffff";
const SHADOW = "0 6px 28px rgba(0,0,0,.55)";

// ================================================================== text helpers
/** The words without outer quotation marks or doubled spaces. */
const clean = (s?: string): string =>
  (typeof s === "string" ? s : "").replace(/\s+/g, " ").trim().replace(/^["“”'‘’«»]+|["“”'‘’«»]+$/g, "").trim();
const cap = (s?: string): string => (s || "").toUpperCase();
const norm = (w: string): string => w.toLowerCase().replace(/[^\p{L}\p{N}']/gu, "");
const words = (s: string): string[] => (s || "").split(/\s+/).filter(Boolean);
const hiSet = (h?: string): Set<string> =>
  new Set((typeof h === "string" ? h : "").split(/[\s,]+/).map(norm).filter(Boolean));
const countWords = (ls: string[]): number => ls.reduce((n, l) => n + words(l).length, 0);
const starts = (ls: string[]): number[] => {
  const out: number[] = [];
  let n = 0;
  for (const l of ls) {
    out.push(n);
    n += words(l).length;
  }
  return out;
};
/**
 * Word-wrapped lines, capped; the last kept line ends in an ellipsis when words
 * were dropped. Lines that fit are balanced: the narrowest measure that keeps the
 * same line count, so a quote never ends on a one-word orphan line.
 */
const wrap = (text: string, chars: number, max: number): string[] => {
  let ls = lines(text, chars);
  if (ls.length > 1 && ls.length <= max) {
    const n = ls.length;
    for (let c = Math.max(6, Math.ceil(text.length / n)); c < chars; c++) {
      const t = lines(text, c);
      if (t.length === n) {
        ls = t;
        break;
      }
    }
  }
  if (ls.length <= max) return ls;
  const out = ls.slice(0, max);
  out[max - 1] = `${out[max - 1].replace(/[,.;:!?…-]+$/, "")}…`;
  return out;
};
/** A hex colour at an alpha (anything else is returned as it is). */
const alpha = (color: string, a: number): string => {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec((color || "").trim());
  if (!m) return color;
  const h = m[1].length === 3 ? m[1].split("").map((c) => c + c).join("") : m[1];
  const v = parseInt(h, 16);
  return `rgba(${(v >> 16) & 255},${(v >> 8) & 255},${v & 255},${Math.max(0, Math.min(1, a))})`;
};
/** Deterministic 0..1 noise from an index (never Math.random). */
const rnd = (i: number, seed = 0): number => {
  const x = Math.sin((i + 1) * 127.1 + seed * 311.7) * 43758.5453;
  return x - Math.floor(x);
};
/** A stable non-negative hash of a string (for SVG ids that must not collide between overlays). */
const hash = (s: string): number => {
  let h = 7;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
};
/** At most n characters, cut at a word where possible, ending in an ellipsis (names, roles, kickers). */
const clip = (s: string, n: number): string => {
  if (s.length <= n) return s;
  const cut = s.slice(0, Math.max(1, n - 1));
  const sp = cut.lastIndexOf(" ");
  return `${(sp > n * 0.6 ? cut.slice(0, sp) : cut).replace(/[\s,.;:–—-]+$/, "")}…`;
};
/** Like wrap, but a text too long keeps its END (the words nearest what follows), led by an ellipsis. */
const wrapTail = (text: string, chars: number, max: number): string[] => {
  const all = lines(text, chars);
  if (all.length <= max) return wrap(text, chars, max);
  const out = all.slice(all.length - max);
  out[0] = `…${out[0]}`;
  return out;
};

/** 0 -> 1 over the last `frames` frames (ease-in), for graphics leaving. */
const useExit = (frames = 12): number => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return ramp(frame, durationInFrames - frames, Math.max(1, frames - 2), easeIn);
};

// ================================================================== reveal primitives
interface Rise { y: number; on: boolean }

/**
 * A word's rise: up out of its mask at `at + gi * step`, and up out of the
 * mask again at the end, the whole block gone within ~12 frames.
 */
const rise = (frame: number, gi: number, total: number, at: number, step: number, D: number, outLead = 14): Rise => {
  const pin = ramp(frame, at + gi * step, 14);
  const spread = Math.min(5, Math.max(0, total - 1) * 0.7);
  const pout = ramp(frame, D - outLead + (total > 1 ? (gi / (total - 1)) * spread : 0), 8, easeIn);
  return { y: (1 - pin) * 118 - pout * 118, on: pin > 0.01 && pout < 0.99 };
};

/**
 * One word in its own mask. `pad` is the headroom (em) kept above it for lifts, `padX` the room kept
 * each side for a word that scales up (the mask would shave its first and last letters otherwise).
 */
const MaskWord: React.FC<{ r: Rise; inner?: React.CSSProperties; pad?: number; padX?: number; children: React.ReactNode }> =
  ({ r, inner, pad = 0.06, padX = 0.02, children }) => (
    <span style={{ display: "inline-block", overflow: "hidden", verticalAlign: "top",
      padding: `${pad}em ${padX}em 0.14em`, margin: `-${pad}em -${padX}em -0.14em` }}>
      <span style={{ display: "inline-block", position: "relative", transform: `translateY(${r.y}%)`,
        opacity: r.on ? 1 : 0, ...inner }}>{children}</span>
    </span>
  );

/** A line of words rising in one after another (global index `start` of `total`). */
const WordLine: React.FC<{
  text: string; start: number; total: number; at: number; step: number; style?: React.CSSProperties;
  hot?: Set<string>; hotColor?: string; outLead?: number; justify?: "flex-start" | "center" | "flex-end";
}> = ({ text, start, total, at, step, style, hot, hotColor, outLead, justify = "flex-start" }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return (
    <div style={{ display: "flex", flexWrap: "nowrap", justifyContent: justify, columnGap: "0.26em", whiteSpace: "nowrap",
      ...style }}>
      {words(text).map((w, i) => {
        const r = rise(frame, start + i, total, at, step, durationInFrames, outLead);
        const isHot = Boolean(hot && hotColor && hot.has(norm(w)));
        return <MaskWord key={i} r={r} inner={isHot ? { color: hotColor } : undefined}>{w}</MaskWord>;
      })}
    </div>
  );
};

/**
 * Letters rising out of the mask one by one (or dropping in from above with
 * `from` -1) and leaving upward one by one at the end, all gone by the last frame.
 */
const Letters: React.FC<{
  text: string; at: number; step?: number; style?: React.CSSProperties; outLead?: number; from?: 1 | -1;
  ease?: (t: number) => number;
}> = ({ text, at, step = 0.8, style, outLead = 14, from = 1, ease }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: D } = useVideoConfig();
  const chars = Array.from(text);
  const n = chars.length;
  const st = Math.min(step, 26 / Math.max(1, n));
  // The last letter starts leaving at most 5 frames after the first and is gone 8 frames later, so with
  // the default outLead (14) every letter is out by the last frame (D - 1), not half-way out of the mask.
  const spread = Math.min(5, n * 0.5);
  return (
    <div style={{ overflow: "hidden", padding: "0.08em 0.02em 0.1em", whiteSpace: "pre", ...style }}>
      {chars.map((c, i) => {
        const pin = ease ? ramp(frame, at + i * st, 13, ease) : ramp(frame, at + i * st, 13);
        const pout = ramp(frame, D - outLead + (n > 1 ? (i / (n - 1)) * spread : 0), 8, easeIn);
        const y = from * (1 - pin) * 110 - pout * 110;
        return (
          <span key={i} style={{ display: "inline-block", whiteSpace: "pre", transform: `translateY(${y}%)`,
            opacity: pin < 0.02 || pout > 0.98 ? 0 : 1 }}>{c}</span>
        );
      })}
    </div>
  );
};

/** A whole line rising out of its mask with a slight tilt that straightens (AE text reveal). */
const RiseLine: React.FC<{ at: number; index: number; count: number; children: React.ReactNode; style?: React.CSSProperties }> =
  ({ at, index, count, children, style }) => {
    const frame = useCurrentFrame();
    const { durationInFrames: D } = useVideoConfig();
    const pin = ramp(frame, at, 18);
    const pout = ramp(frame, D - 14 + (count > 1 ? (index / (count - 1)) * 4 : 0), 9, easeIn);
    return (
      <div style={{ overflow: "hidden", padding: "0.05em 0 0.14em", margin: "-0.05em 0 -0.14em", ...style }}>
        <div style={{ transform: `translateY(${(1 - pin) * 118 - pout * 118}%) rotate(${(1 - pin) * 3}deg)`,
          transformOrigin: "0 100%", opacity: pin < 0.01 || pout > 0.99 ? 0 : 1 }}>{children}</div>
      </div>
    );
  };

/** Content sliding in sideways out of a mask (and back into it at the end). */
const SlideIn: React.FC<{ at: number; outLead?: number; children: React.ReactNode }> = ({ at, outLead = 14, children }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: D } = useVideoConfig();
  const pin = ramp(frame, at, 18);
  const pout = ramp(frame, D - outLead, 10, easeIn);
  return (
    <div style={{ overflow: "hidden" }}>
      <div style={{ transform: `translateX(${(-(1 - pin) - pout) * 104}%)`, whiteSpace: "nowrap" }}>{children}</div>
    </div>
  );
};

/** A drawn pair of quotation marks (66 opening, 99 closing): crisp at any size. */
const QuoteGlyph: React.FC<{ w: number; color: string; close?: boolean }> = ({ w, color, close }) => (
  <svg width={w} height={w * 0.78} viewBox="0 0 120 94" style={{ display: "block", overflow: "visible" }}>
    <g transform={close ? "rotate(180 60 47)" : undefined}>
      {[0, 64].map((dx) => (
        <g key={dx} transform={`translate(${dx} 0)`}>
          <circle cx={26} cy={67} r={26} fill={color} />
          <path d="M1 70 C-1 36 15 11 47 0 L52 9 C33 19 24 33 25 43 Z" fill={color} />
        </g>
      ))}
    </g>
  </svg>
);

/** Text with the highlighted words in a colour. */
const HotText: React.FC<{ text: string; hot: Set<string>; color: string }> = ({ text, hot, color }) => {
  if (!hot.size) return <>{text}</>;
  return (
    <>
      {words(text).map((w, i) => (
        <React.Fragment key={i}>
          {i ? " " : ""}
          {hot.has(norm(w)) ? <span style={{ color }}>{w}</span> : w}
        </React.Fragment>
      ))}
    </>
  );
};

// ================================================================== 1. giant marks
/** Oversized quote marks spin in, the quote rises line by line, the speaker slides out of an accent rule. */
const GiantMarks: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit(14);
  const body = clean(overlay.text);
  if (!body) return null;
  const n = words(body).length;
  const size = n <= 12 ? 62 : n <= 22 ? 54 : 46;
  const ls = wrap(body, size >= 62 ? 30 : size >= 54 ? 36 : 44, 5);
  const hot = hiSet(overlay.highlight);
  const who = clip(cap(clean(overlay.label)), 48);
  const role = clip(clean(overlay.subtitle), 70);
  const lineAt = (i: number) => 9 + i * 5;
  const endAt = lineAt(ls.length) + 6;
  const markP = ramp(frame, 0, 22, backOut);
  const markR = ramp(frame, 0, 28);
  const closeP = ramp(frame, endAt, 18, backOut);
  const rule = ramp(frame, endAt + 2, 16);
  const float = Math.sin(frame / (fps * 0.9)) * 5 * k;
  const ghostIn = ramp(frame, 0, 30);
  const drift = interpolate(frame, [0, D], [30, -30], clamp) * k;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <div style={{ position: "absolute", left: 120 * k + drift, top: 96 * k, opacity: 0.065 * ghostIn * (1 - exit),
        transform: `rotate(${-8 + 8 * ghostIn}deg) scale(${0.85 + 0.15 * ghostIn})`, transformOrigin: "0 0" }}>
        <QuoteGlyph w={640 * k} color={WHITE} />
      </div>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{ position: "relative", maxWidth: 1360 * k, transform: `scale(${hold})` }}>
          <div style={{ width: 170 * k, marginBottom: 26 * k, marginLeft: -6 * k, opacity: Math.min(1, markP * 2) * (1 - exit),
            transform: `translateY(${float}px) rotate(${-36 * (1 - markR) - 16 * exit}deg) scale(${(0.3 + 0.7 * markP) * (1 - 0.35 * exit)})`,
            transformOrigin: "25% 75%" }}>
            <QuoteGlyph w={170 * k} color={accent} />
          </div>
          {ls.map((ln, i) => (
            <RiseLine key={i} at={lineAt(i)} index={i} count={ls.length}
              style={{ fontFamily: INTER, fontWeight: 700, fontSize: size * k, lineHeight: 1.2, color: WHITE,
                letterSpacing: "-0.01em", textShadow: SHADOW, whiteSpace: "nowrap" }}>
              <HotText text={ln} hot={hot} color={accent} />
            </RiseLine>
          ))}
          <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 40 * k, marginTop: 34 * k }}>
            <div style={{ display: "flex", alignItems: "center", gap: 20 * k, minHeight: 10 * k }}>
              {/* Drawn with scaleX, not width: a growing width re-flowed the row and slid the name sideways. */}
              <div style={{ width: 70 * k, height: 4 * k, flexShrink: 0, background: accent,
                transform: `scaleX(${Math.max(0, rule * (1 - exit))})`, transformOrigin: "0 50%",
                boxShadow: `0 0 ${12 * k}px ${alpha(accent, 0.55)}` }} />
              {who || role ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 2 * k }}>
                  {who ? (
                    <SlideIn at={endAt + 6}>
                      <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 34 * k, letterSpacing: "0.16em", color: WHITE }}>{who}</span>
                    </SlideIn>
                  ) : null}
                  {role ? (
                    <SlideIn at={endAt + 11}>
                      <span style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 26 * k, letterSpacing: "0.05em",
                        color: "rgba(255,255,255,.66)" }}>{role}</span>
                    </SlideIn>
                  ) : null}
                </div>
              ) : null}
            </div>
            <div style={{ width: 86 * k, opacity: Math.min(1, closeP * 2) * (1 - exit),
              transform: `rotate(${40 * (1 - closeP) + 14 * exit}deg) scale(${Math.max(0, closeP) * (1 - 0.35 * exit)})` }}>
              <QuoteGlyph w={86 * k} color={accent} close />
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 2. testimony rail
/** Own backdrop. A rail draws down; each line slides out of it as the glowing tip passes; the speaker at the foot. */
const TestimonyRail: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit(14);
  const body = clean(overlay.text);
  if (!body) return null;
  const n = words(body).length;
  const size = n <= 14 ? 56 : n <= 26 ? 50 : 44;
  const ls = wrap(body, size >= 56 ? 36 : size >= 50 ? 42 : 50, 5);
  const who = clip(cap(clean(overlay.label)), 56);
  const role = clip(clean(overlay.subtitle), 80);
  const hasWho = Boolean(who || role);
  const lh = size * 1.32 * k;
  const head = 74 * k;
  const textH = ls.length * lh;
  const whoY = head + textH + 44 * k;
  const H = hasWho ? whoY + 100 * k : head + textH + 16 * k;
  const drawAt = 4;
  const drawF = Math.max(26, Math.min(58, 14 + ls.length * 8 + (hasWho ? 8 : 0)));
  const d = ramp(frame, drawAt, drawF, inOut);
  /** The frame at which the tip reaches y. */
  const tipAt = (y: number): number => {
    for (let f = 0; f <= drawF; f++) if (ramp(drawAt + f, drawAt, drawF, inOut) * H >= y) return drawAt + f;
    return drawAt + drawF;
  };
  const tipY = d * H;
  const topY = exit * H;
  const settled = frame >= drawAt + drawF;
  const period = Math.max(1, Math.round(fps * 1.4));
  const pulse = settled ? ((frame - drawAt - drawF) % period) / period : 0;
  const X0 = 44 * k;
  const glow = 14 + 2 * Math.sin(frame / (fps * 1.3));
  const txt: React.CSSProperties = { fontFamily: LABEL, fontWeight: 600, fontSize: size * k, color: WHITE, whiteSpace: "nowrap",
    lineHeight: 1.1, letterSpacing: "0.005em" };
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 30% 45%, #1c1e24 0%, #0f1014 55%, #050506 100%)" }} />
      <AbsoluteFill style={{ background: `radial-gradient(circle at ${glow}% 50%, ${alpha(accent, 0.16)} 0%, rgba(0,0,0,0) 36%)` }} />
      <AbsoluteFill style={{ backgroundImage:
        "repeating-linear-gradient(0deg, rgba(255,255,255,.03) 0px, rgba(255,255,255,.03) 1px, rgba(0,0,0,0) 1px, rgba(0,0,0,0) 5px)" }} />
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${280 * k}px rgba(0,0,0,.75)` }} />
      <AbsoluteFill style={{ justifyContent: "center", paddingLeft: 250 * k }}>
        <div style={{ position: "relative", width: 1400 * k, height: H, transform: `scale(${hold})`, transformOrigin: "0 50%" }}>
          <div style={{ position: "absolute", left: -1 * k, top: 0, width: 2 * k, height: H, background: "rgba(255,255,255,.1)",
            opacity: ramp(frame, 0, 10) * (1 - exit) }} />
          <div style={{ position: "absolute", left: -3 * k, top: topY, width: 6 * k, height: Math.max(0, tipY - topY),
            background: `linear-gradient(180deg, ${alpha(accent, 0.45)}, ${accent})`, boxShadow: `0 0 ${16 * k}px ${alpha(accent, 0.55)}` }} />
          {tipY > topY + 1 ? (
            <div style={{ position: "absolute", left: -9 * k, top: tipY - 9 * k, width: 18 * k, height: 18 * k, borderRadius: "50%",
              background: WHITE, boxShadow: `0 0 ${18 * k}px ${accent}, 0 0 ${4 * k}px ${WHITE}`, transform: `scale(${1 - exit})` }} />
          ) : null}
          {settled && exit < 0.34 ? (
            <div style={{ position: "absolute", left: -9 * k, top: H - 9 * k, width: 18 * k, height: 18 * k, borderRadius: "50%",
              border: `${2 * k}px solid ${accent}`, transform: `scale(${1 + pulse * 2.2})`,
              opacity: (1 - pulse) * Math.max(0, 1 - exit * 3) }} />
          ) : null}
          <div style={{ position: "absolute", left: X0, top: 0 }}>
            <Letters text="ON THE RECORD" at={tipAt(6 * k)} step={0.6} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 24 * k,
              letterSpacing: "0.34em", color: accent }} />
          </div>
          {ls.map((ln, i) => {
            const y = head + i * lh;
            const at = tipAt(y + lh * 0.35);
            const p = ramp(frame, at, 18);
            // Five lines at most: the last starts back into the rail at D - 10 and is gone by D - 1.
            const po = ramp(frame, D - 14 + i, 9, easeIn);
            const first = i === 0;
            const last = i === ls.length - 1;
            return (
              <React.Fragment key={i}>
                <div style={{ position: "absolute", left: 0, top: y + lh * 0.5, width: 22 * k, height: 2 * k,
                  background: "rgba(255,255,255,.55)", transform: `scaleX(${p * (1 - po)})`, transformOrigin: "0 50%" }} />
                <div style={{ position: "absolute", left: X0, top: y, height: lh, display: "flex", alignItems: "center",
                  overflow: "hidden", paddingRight: 24 * k }}>
                  <div style={{ ...txt, transform: `translateX(${(-(1 - p) - po) * 104}%)`, textShadow: SHADOW }}>
                    {first ? <span style={{ color: accent }}>“</span> : null}{ln}{last ? <span style={{ color: accent }}>”</span> : null}
                  </div>
                </div>
              </React.Fragment>
            );
          })}
          {hasWho ? (
            <>
              <div style={{ position: "absolute", left: -8 * k, top: whoY + 16 * k, width: 16 * k, height: 16 * k, background: accent,
                transform: `rotate(45deg) scale(${Math.max(0, ramp(frame, tipAt(whoY + 16 * k), 12, backOut)) * (1 - exit)})` }} />
              <div style={{ position: "absolute", left: X0, top: whoY }}>
                {who ? (
                  <Letters text={who} at={tipAt(whoY)} step={0.6} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 36 * k,
                    letterSpacing: "0.12em", color: WHITE }} />
                ) : null}
                {role ? (
                  <Letters text={role} at={tipAt(whoY) + 5} step={0.4} style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 26 * k,
                    letterSpacing: "0.06em", color: "rgba(255,255,255,.62)" }} />
                ) : null}
              </div>
            </>
          ) : null}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 3. side panel (tag)
/** A frosted pull-quote panel slides in from the right over the footage; its accent edge draws down. */
const SidePanel: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: D } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const body = clean(overlay.text);
  if (!body) return null;
  const n = words(body).length;
  const size = n <= 12 ? 44 : n <= 24 ? 38 : 33;
  // The panel's text column is ~574px wide: measures kept short enough for Inter Bold to fit.
  const ls = wrap(body, size >= 44 ? 20 : size >= 38 ? 24 : 28, 7);
  const total = countWords(ls);
  const st = starts(ls);
  const hot = hiSet(overlay.highlight);
  // The text column is ~574 px: longer names are cut rather than clipped mid-letter by the panel edge.
  const who = clip(cap(clean(overlay.label)), 32);
  const role = clip(clean(overlay.subtitle), 46);
  const W = 680 * k;
  const pin = ramp(frame, 0, 22);
  const pout = ramp(frame, D - 12, 11, easeIn);
  const off = W + 160 * k;
  const x = (1 - pin) * off + pout * off;
  const lag = (1 - ramp(frame, 3, 26)) * 70 * k;
  const bar = ramp(frame, 8, 24, inOut);
  const glyph = ramp(frame, 10, 20, backOut);
  const sheen = ramp(frame, 12, 34, inOut);
  const textAt = 14;
  const step = Math.min(1.6, 30 / Math.max(1, total));
  const doneAt = textAt + total * step + 8;
  const rule = ramp(frame, doneAt, 18, inOut);
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: ramp(frame, 0, 14) * (1 - pout),
        background: "linear-gradient(270deg, rgba(0,0,0,.45) 0%, rgba(0,0,0,.18) 28%, rgba(0,0,0,0) 46%)" }} />
      <div style={{ position: "absolute", right: 96 * k, top: "50%", width: W, transformOrigin: "100% 50%",
        transform: `translate(${x}px, -50%) scale(${hold})` }}>
        <div style={{ position: "relative", overflow: "hidden", borderRadius: 4 * k,
          padding: `${46 * k}px ${48 * k}px ${42 * k}px ${58 * k}px`,
          background: "linear-gradient(165deg, rgba(34,36,44,.58) 0%, rgba(10,11,14,.74) 100%)",
          backdropFilter: "blur(24px) saturate(1.25)", WebkitBackdropFilter: "blur(24px) saturate(1.25)",
          border: `${1.5 * k}px solid rgba(255,255,255,.16)`,
          boxShadow: `0 ${40 * k}px ${90 * k}px rgba(0,0,0,.45), inset 0 ${1 * k}px 0 rgba(255,255,255,.14)` }}>
          <div style={{ position: "absolute", left: 0, top: 0, width: 6 * k, height: `${bar * 100}%`, background: accent,
            boxShadow: `0 0 ${18 * k}px ${alpha(accent, 0.6)}` }} />
          <div style={{ position: "absolute", inset: 0, transform: `translateX(${-110 + sheen * 220}%)`,
            background: "linear-gradient(105deg, rgba(255,255,255,0) 35%, rgba(255,255,255,.08) 50%, rgba(255,255,255,0) 65%)" }} />
          <div style={{ position: "relative", transform: `translateX(${lag}px)` }}>
            <div style={{ width: 62 * k, marginBottom: 22 * k, transformOrigin: "30% 70%",
              transform: `rotate(${-30 * (1 - glyph)}deg) scale(${Math.max(0, glyph)})` }}>
              <QuoteGlyph w={62 * k} color={accent} />
            </div>
            {ls.map((ln, i) => (
              <WordLine key={i} text={ln} start={st[i]} total={total} at={textAt} step={step} hot={hot} hotColor={accent}
                outLead={20} style={{ fontFamily: INTER, fontWeight: 700, fontSize: size * k, lineHeight: 1.26, color: WHITE,
                  letterSpacing: "-0.01em" }} />
            ))}
            {who || role ? (
              <>
                <div style={{ height: 1.5 * k, width: `${rule * (1 - pout) * 100}%`, background: "rgba(255,255,255,.22)",
                  margin: `${30 * k}px 0 ${18 * k}px` }} />
                {who ? (
                  <Letters text={who} at={doneAt + 4} step={0.6} outLead={20} style={{ fontFamily: LABEL, fontWeight: 800,
                    fontSize: 28 * k, letterSpacing: "0.16em", color: WHITE }} />
                ) : null}
                {role ? (
                  <Letters text={role} at={doneAt + 9} step={0.4} outLead={20} style={{ fontFamily: LABEL, fontWeight: 600,
                    fontSize: 24 * k, letterSpacing: "0.05em", color: "rgba(255,255,255,.62)" }} />
                ) : null}
              </>
            ) : null}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 4. statement vs reality
/** The statement, then "BUT" drops between two rules, the statement dims and the reality rises in the accent. */
const ButPivot: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit(14);
  let a = clean(overlay.text);
  let b = clean(overlay.subtitle);
  if (a && !b) {
    // One sentence with its own "but": split it there.
    const m = /^(.+?)[,;]?\s+but\s+(.+)$/i.exec(a);
    if (m) {
      a = m[1];
      b = m[2];
    }
  }
  if (!a || !b) return null;
  const aW = words(a).length;
  const sizeA = aW <= 10 ? 54 : aW <= 20 ? 48 : 42;
  const lsA = wrap(a, sizeA >= 54 ? 40 : 48, 3);
  const totalA = countWords(lsA);
  const stA = starts(lsA);
  const stepA = Math.min(2, 24 / Math.max(1, totalA));
  const B = cap(b.replace(/[.!]+$/, ""));
  const sizeB = B.length <= 24 ? 84 : B.length <= 48 ? 72 : 60;
  const lsB = wrap(B, sizeB >= 84 ? 24 : sizeB >= 72 ? 30 : 36, 3);
  const kicker = clip(cap(clean(overlay.label)), 48);
  const aDone = 4 + totalA * stepA + 12;
  const P = Math.max(14, Math.min(Math.max(Math.round(fps * 1.4), Math.round(aDone + 4)), D - 66));
  const piv = ramp(frame, P, 22);
  const ruleP = ramp(frame, P + 2, 20, inOut) * (1 - exit);
  const bump = interpolate(frame, [P, P + 5, P + 22], [0, 1, 0], clamp);
  const flash = interpolate(frame, [P, P + 4, P + 24], [0, 1, 0], clamp);
  const pivotH = 110 * k;
  const bH = lsB.length * sizeB * 1.02 * k + 10 * k;
  const shift = ((1 - piv) * (pivotH + bH)) / 2;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", maxWidth: 1500 * k,
          transform: `translateY(${shift}px) scale(${hold * (1 + 0.022 * bump)})` }}>
          {kicker ? (
            <Letters text={kicker} at={0} step={0.6} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 24 * k,
              letterSpacing: "0.32em", color: "rgba(255,255,255,.6)", marginBottom: 14 * k }} />
          ) : null}
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", opacity: 1 - 0.5 * piv,
            transform: `scale(${1 - 0.06 * piv})` }}>
            {lsA.map((ln, i) => (
              <WordLine key={i} text={ln} start={stA[i]} total={totalA} at={4} step={stepA} justify="center"
                style={{ fontFamily: LABEL, fontWeight: 700, fontSize: sizeA * k, lineHeight: 1.16, color: WHITE, textShadow: SHADOW }} />
            ))}
          </div>
          <div style={{ position: "relative", height: pivotH, width: 900 * k, display: "flex", alignItems: "center",
            justifyContent: "center", gap: 28 * k }}>
            <div style={{ position: "absolute", left: "50%", top: "50%", width: 560 * k, height: 220 * k, transform: "translate(-50%, -50%)",
              background: `radial-gradient(ellipse at center, ${alpha(accent, 0.32)} 0%, rgba(0,0,0,0) 65%)`, opacity: flash }} />
            <div style={{ width: 300 * k, display: "flex", justifyContent: "flex-end" }}>
              <div style={{ width: `${ruleP * 100}%`, height: 2 * k,
                background: "linear-gradient(90deg, rgba(255,255,255,0), rgba(255,255,255,.75))" }} />
            </div>
            <Letters text="BUT" at={P} step={1.6} from={-1} ease={backOut} style={{ position: "relative", fontFamily: DISPLAY,
              fontSize: 66 * k, lineHeight: 1, color: accent, letterSpacing: "0.12em", padding: "0.08em 0.02em 0.1em 0.12em" }} />
            <div style={{ width: 300 * k, display: "flex", justifyContent: "flex-start" }}>
              <div style={{ width: `${ruleP * 100}%`, height: 2 * k,
                background: "linear-gradient(270deg, rgba(255,255,255,0), rgba(255,255,255,.75))" }} />
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
            {lsB.map((ln, i) => (
              <Letters key={i} text={ln} at={P + 8 + i * 5} step={0.7} style={{ fontFamily: DISPLAY, fontSize: sizeB * k, lineHeight: 1,
                color: accent, letterSpacing: "0.03em", textAlign: "center", textShadow: SHADOW }} />
            ))}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 5. strike-through correction
/** A claim, struck through in red by a hot spark (it shakes and dims), the correction rising beneath. */
const StrikeCorrection: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit(14);
  const claim = clean(overlay.text);
  if (!claim) return null;
  const fix = clean(overlay.subtitle);
  const cW = words(claim).length;
  const sizeC = cW <= 9 ? 62 : cW <= 18 ? 52 : 44;
  const lsC = wrap(claim, sizeC >= 62 ? 30 : sizeC >= 52 ? 38 : 46, 3);
  const totalC = countWords(lsC);
  const stC = starts(lsC);
  const stepC = Math.min(2, 22 / Math.max(1, totalC));
  const cDone = 6 + totalC * stepC + 10;
  const S = Math.max(16, Math.min(Math.max(Math.round(fps * 1.1), Math.round(cDone + 2)), D - 62));
  const SF = 11;
  const hit = S + (lsC.length - 1) * 4 + SF;
  const F = hit + 5;
  const FIX = cap(fix.replace(/[.!]+$/, ""));
  const sizeF = FIX.length <= 26 ? 78 : FIX.length <= 52 ? 66 : 56;
  const lsF = FIX ? wrap(FIX, sizeF >= 78 ? 26 : sizeF >= 66 ? 32 : 38, 3) : [];
  const kickF = clip(cap(clean(overlay.label)), 40) || "THE FACTS";
  const struck = ramp(frame, hit - 2, 8);
  const dt = frame - hit;
  const shake = dt >= 0 && dt < 10 ? Math.sin(dt * 2.3) * 8 * k * (1 - dt / 10) : 0;
  const fixH = lsF.length ? 70 * k + lsF.length * sizeF * 1.02 * k : 0;
  const shift = ((1 - ramp(frame, F - 2, 24)) * fixH) / 2;
  const retract = ramp(frame, D - 14, 10, easeIn);
  const kick: React.CSSProperties = { fontFamily: LABEL, fontWeight: 800, fontSize: 24 * k, letterSpacing: "0.32em" };
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", maxWidth: 1500 * k,
          transform: `translateY(${shift}px) scale(${hold})` }}>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", transform: `translateX(${shake}px)` }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 * k, marginBottom: 12 * k }}>
              <div style={{ width: 10 * k, height: 10 * k, background: struck > 0.5 ? RED : "rgba(255,255,255,.55)",
                transform: `scale(${Math.max(0, ramp(frame, 2, 12, backOut)) * (1 - exit)})` }} />
              <Letters text="THE CLAIM" at={2} step={0.6} style={{ ...kick, color: struck > 0.5 ? RED : "rgba(255,255,255,.6)" }} />
            </div>
            {lsC.map((ln, i) => {
              const sp = ramp(frame, S + i * 4, SF, inOut) * (1 - retract);
              const moving = frame >= S + i * 4 && sp > 0.01 && sp < 0.99 && retract < 0.01;
              return (
                <div key={i} style={{ position: "relative", display: "inline-block" }}>
                  <WordLine text={ln} start={stC[i]} total={totalC} at={6} step={stepC} justify="center"
                    style={{ fontFamily: LABEL, fontWeight: 700, fontSize: sizeC * k, lineHeight: 1.18, color: WHITE,
                      textShadow: SHADOW, opacity: 1 - 0.55 * struck }} />
                  <div style={{ position: "absolute", left: "-3%", top: "57%", width: `${106 * sp}%`, height: 7 * k, marginTop: -3.5 * k,
                    background: RED, borderRadius: 4 * k, transform: `rotate(${i % 2 ? 0.9 : -1.2}deg)`, transformOrigin: "0 50%",
                    boxShadow: `0 0 ${14 * k}px ${alpha(RED, 0.6)}` }} />
                  {moving ? (
                    <div style={{ position: "absolute", left: `${-3 + 106 * sp}%`, top: "57%", width: 22 * k, height: 22 * k,
                      margin: `${-11 * k}px 0 0 ${-11 * k}px`, borderRadius: "50%", background: WHITE,
                      boxShadow: `0 0 ${20 * k}px ${RED}, 0 0 ${44 * k}px ${RED}` }} />
                  ) : null}
                </div>
              );
            })}
          </div>
          {lsF.length ? (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", marginTop: 40 * k }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12 * k, marginBottom: 6 * k }}>
                <div style={{ width: 10 * k, height: 10 * k, background: accent,
                  transform: `scale(${Math.max(0, ramp(frame, F, 12, backOut)) * (1 - exit)})` }} />
                <Letters text={kickF} at={F} step={0.6} style={{ ...kick, color: accent }} />
              </div>
              {lsF.map((ln, i) => (
                <Letters key={i} text={ln} at={F + 4 + i * 5} step={0.7} style={{ fontFamily: DISPLAY, fontSize: sizeF * k,
                  lineHeight: 1, color: WHITE, letterSpacing: "0.03em", textAlign: "center", textShadow: SHADOW }} />
              ))}
            </div>
          ) : null}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 6. karaoke
/** The sentence sits in white; each word fills with the accent, left to right, in speaking rhythm. */
const Karaoke: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit(14);
  const body = clean(overlay.text);
  if (!body) return null;
  const n0 = words(body).length;
  const size = n0 <= 12 ? 60 : n0 <= 22 ? 52 : n0 <= 34 ? 46 : 40;
  const ls = wrap(body, size >= 60 ? 30 : size >= 52 ? 36 : size >= 46 ? 42 : 48, 5);
  const total = countWords(ls);
  const st = starts(ls);
  const step = Math.min(1.5, 20 / Math.max(1, total));
  const inDone = 4 + total * step + 10;
  const K0 = Math.round(Math.max(fps * 0.8, inDone));
  const K1 = Math.max(K0 + 24, D - 26);
  // Longer words take longer to say: each word's share of the run is its length.
  const flat: string[] = [];
  ls.forEach((l) => words(l).forEach((w) => flat.push(w)));
  const weights = flat.map((w) => Math.max(2, norm(w).length) + 1.6);
  const cum: number[] = [];
  let acc = 0;
  weights.forEach((w) => {
    cum.push(acc);
    acc += w;
  });
  const pos = interpolate(frame, [K0, K1], [0, Math.max(1, acc)], clamp);
  const who = clip(cap(clean(overlay.label)), 48);
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", maxWidth: 1500 * k, transform: `scale(${hold})` }}>
          {ls.map((ln, li) => (
            <div key={li} style={{ display: "flex", justifyContent: "center", columnGap: "0.28em", whiteSpace: "nowrap",
              fontFamily: INTER, fontWeight: 800, fontSize: size * k, lineHeight: 1.3, letterSpacing: "-0.01em" }}>
              {words(ln).map((w, wi) => {
                const gi = st[li] + wi;
                const r = rise(frame, gi, total, 4, step, D);
                const wp = Math.max(0, Math.min(1, (pos - (cum[gi] ?? 0)) / (weights[gi] ?? 1)));
                const after = (pos - (cum[gi] ?? 0) - (weights[gi] ?? 1)) / 3;
                const lift = Math.sin(Math.PI * wp);
                const under = wp <= 0 ? 0 : wp < 1 ? 1 : Math.max(0, 1 - after);
                // The pop grows each side by pop/2 of the word's width (~0.62 em a letter): kept inside the
                // mask's 0.13 em side room, so long words pop less instead of losing their outer letters.
                const pop = Math.min(0.05, 0.24 / Math.max(1, Array.from(w).length * 0.62));
                return (
                  <MaskWord key={wi} r={r} pad={0.16} padX={0.13}>
                    <span style={{ display: "inline-block", position: "relative", transformOrigin: "50% 80%",
                      transform: `translateY(${-0.07 * lift}em) scale(${1 + pop * lift})` }}>
                      <span style={{ color: "rgba(255,255,255,.95)", textShadow: "0 5px 24px rgba(0,0,0,.5)" }}>{w}</span>
                      <span style={{ position: "absolute", left: 0, top: 0, color: accent, whiteSpace: "nowrap",
                        clipPath: `inset(0 ${(1 - wp) * 100}% 0 0)` }}>{w}</span>
                      <span style={{ position: "absolute", left: 0, bottom: "0.1em", height: 5 * k, width: `${wp * 100}%`,
                        background: accent, opacity: under, borderRadius: 3 * k, boxShadow: `0 0 ${12 * k}px ${alpha(accent, 0.7)}` }} />
                    </span>
                  </MaskWord>
                );
              })}
            </div>
          ))}
          {who ? (
            <div style={{ display: "flex", alignItems: "center", gap: 16 * k, marginTop: 34 * k }}>
              <div style={{ width: 44 * k, height: 3 * k, flexShrink: 0, background: accent, transformOrigin: "100% 50%",
                transform: `scaleX(${Math.max(0, ramp(frame, inDone, 16) * (1 - exit))})` }} />
              <Letters text={who} at={inDone + 2} step={0.6} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 28 * k,
                letterSpacing: "0.2em", color: "rgba(255,255,255,.78)" }} />
            </div>
          ) : null}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 7. emphasis zoom
/** Bebas Neue cap widths (em), approximate: only sizes the focus brackets and caps the zoom. */
const BEBAS: Record<string, number> = {
  A: 0.4, B: 0.41, C: 0.39, D: 0.41, E: 0.35, F: 0.33, G: 0.4, H: 0.42, I: 0.18, J: 0.27, K: 0.41, L: 0.33, M: 0.53,
  N: 0.43, O: 0.4, P: 0.39, Q: 0.4, R: 0.41, S: 0.38, T: 0.34, U: 0.41, V: 0.4, W: 0.56, X: 0.4, Y: 0.39, Z: 0.35,
};
const emW = (s: string): number => Array.from(s).reduce((a, c) =>
  a + (BEBAS[c] ?? (/[0-9]/.test(c) ? 0.39 : /[.,:;'’!|]/.test(c) ? 0.17 : /[-–—]/.test(c) ? 0.3 : 0.38)) + 0.02, 0);

/**
 * A sentence, then the camera dives into its key word (highlight, else the longest word) and focus
 * brackets snap round it. The key word sits alone on its own centred line (the words before it above,
 * the words after it below), so the dive lands on it exactly: no guessing where it falls on a line
 * from estimated letter widths, which put the word off-centre inside its brackets once zoomed.
 */
const ZoomWord: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: D, width, height } = useVideoConfig();
  const k = useK();
  const exit = useExit(14);
  const T = cap(clean(overlay.text)).replace(/[.]+$/, "");
  if (!T) return null;
  const all = words(T);
  const hot = hiSet(overlay.highlight);
  let ki = all.findIndex((w) => hot.has(norm(w)));
  if (ki < 0) {
    let best = 0;
    all.forEach((w, i) => {
      const len = norm(w).length;
      if (len > best) {
        best = len;
        ki = i;
      }
    });
  }
  if (ki < 0) return null;
  const keyWord = all[ki].replace(/[,;:]+$/, "") || all[ki];
  const base = T.length <= 28 ? 84 : T.length <= 56 ? 72 : 60;
  const size = base * k;
  const chars = base >= 84 ? 26 : base >= 72 ? 32 : 40;
  const pre = wrapTail(all.slice(0, ki).join(" "), chars, 2);
  const post = wrap(all.slice(ki + 1).join(" "), chars, 2);
  const ls = [...pre, keyWord, ...post];
  const kl = pre.length;
  const gap = 0.24;
  const lh = size * 1.1;
  const blockTop = height / 2 - (ls.length * lh) / 2;
  const keyW = emW(keyWord) * size;
  const kx = width / 2;
  const ky = blockTop + kl * lh + size * 0.5;
  const total = countWords(ls);
  const st = starts(ls);
  const step = Math.min(2, 18 / Math.max(1, total));
  const inDone = 4 + total * step + 12;
  const Z = Math.max(18, Math.min(Math.max(Math.round(fps * 1.3), Math.round(inDone + 6)), D - 56));
  const ZF = 24;
  const z = ramp(frame, Z, ZF, inOut);
  const zPrev = ramp(frame - 1, Z, ZF, inOut);
  // Zoomed, the key word stays under ~170 px tall and ~1300 px wide (big-number limits, safe margins).
  const Tm = Math.max(1.4, Math.min(3, (170 * k) / size, (1300 * k) / Math.max(1, keyW)));
  const push = 1 + 0.045 * interpolate(frame, [Z + ZF, Math.max(Z + ZF + 1, D)], [0, 1], clamp);
  const s = (1 + (Tm - 1) * z) * push;
  const blur = Math.min(8, Math.abs(z - zPrev) * (Tm - 1) * 30) * k;
  const charge = ramp(frame, Z - 12, 12, inOut) * (1 - z);
  const br = ramp(frame, Z + ZF - 8, 16);
  const bw = keyW * Tm * push + 110 * k;
  const bh = size * 0.7 * Tm * push + 90 * k;
  const bs = (1.25 - 0.25 * br) * (1 + 0.12 * exit);
  const L = 42 * k;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ transformOrigin: `${kx}px ${ky}px`,
        transform: `translate(${(width / 2 - kx) * z}px, ${(height / 2 - ky) * z}px) scale(${s})`,
        filter: blur > 0.3 ? `blur(${blur}px)` : undefined }}>
        {ls.map((ln, li) => (
          <div key={li} style={{ position: "absolute", left: 0, right: 0, top: blockTop + li * lh, height: lh, display: "flex",
            justifyContent: "center", alignItems: "center", columnGap: `${gap}em`, fontFamily: DISPLAY, fontSize: size, lineHeight: 1,
            letterSpacing: "0.02em", color: WHITE, whiteSpace: "nowrap" }}>
            {words(ln).map((w, wi) => {
              const r = rise(frame, st[li] + wi, total, 4, step, D);
              const isKey = li === kl;
              return (
                <MaskWord key={wi} r={r}>
                  {isKey ? (
                    <span style={{ position: "relative", display: "inline-block", textShadow: SHADOW }}>
                      <span>{w}</span>
                      <span style={{ position: "absolute", left: 0, top: 0, color: accent, opacity: z }}>{w}</span>
                      <span style={{ position: "absolute", left: 0, right: 0, bottom: "0.02em", height: "0.05em", background: accent,
                        transform: `scaleX(${charge})`, transformOrigin: "0 50%" }} />
                    </span>
                  ) : (
                    <span style={{ opacity: 1 - 0.9 * z, textShadow: SHADOW }}>{w}</span>
                  )}
                </MaskWord>
              );
            })}
          </div>
        ))}
      </AbsoluteFill>
      {br > 0 ? (
        <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0, opacity: Math.min(1, br * 1.5) * (1 - exit) }}>
          <g transform={`translate(${width / 2} ${height / 2}) scale(${bs})`}>
            {[[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([sx, sy], i) => (
              <path key={i} fill="none" stroke={accent} strokeWidth={4 * k} strokeLinecap="square"
                d={`M${(sx * bw) / 2} ${(sy * bh) / 2 - sy * L} L${(sx * bw) / 2} ${(sy * bh) / 2} L${(sx * bw) / 2 - sx * L} ${(sy * bh) / 2}`} />
            ))}
          </g>
        </svg>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== 8. said-by stamp
/** The quote, then a rotating seal with the speaker's name slams down: camera shake, shock ring, sparks. */
const SaidStamp: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit(12);
  const body = clean(overlay.text);
  if (!body) return null;
  const n = words(body).length;
  const size = n <= 12 ? 58 : n <= 22 ? 50 : 44;
  const ls = wrap(body, size >= 58 ? 28 : size >= 50 ? 34 : 42, 5);
  const total = countWords(ls);
  const st = starts(ls);
  const hot = hiSet(overlay.highlight);
  const step = Math.min(1.8, 24 / Math.max(1, total));
  const inDone = 8 + total * step + 10;
  const L = Math.max(16, Math.min(Math.max(Math.round(fps * 1.2), Math.round(inDone + 2)), D - 50));
  const I = L + 7;
  const label = cap(clean(overlay.label));
  const sub = clean(overlay.subtitle);
  // The ring holds ~44 characters: a long name is cut so the letters never crush together.
  const nameRaw = label || cap(sub) || "ON THE RECORD";
  const name = nameRaw.length > 30 ? `${nameRaw.slice(0, 29).trim()}…` : nameRaw;
  // The seal's centre: a short subtitle as it is, else the year inside it ("Hearing, 2016"), else SAID.
  const yearM = /\b(1[5-9]\d\d|20\d\d)\b/.exec(sub);
  const centre = label && sub ? (sub.length <= 6 ? cap(sub) : yearM ? yearM[1] : "SAID") : "SAID";
  const cs = centre.length <= 4 ? 58 : 46;
  const fall = ramp(frame, L, 7, fallIn);
  const sc = frame < I ? 2.6 - 1.68 * fall : interpolate(frame, [I, I + 4, I + 10], [0.92, 1.04, 1], clamp);
  const rot = -40 + 28 * fall + 6 * exit;
  const spin = Math.max(0, frame - L) * 0.55;
  const dt = frame - I;
  const shake = dt >= 0 && dt < 11 ? Math.sin(dt * 2.2) * 10 * k * (1 - dt / 11) : 0;
  const shock = ramp(frame, I, 16);
  const burst = ramp(frame, I, 22);
  const S = 270 * k;
  // Unique per overlay: animation scenes all start at frame 0, so the start alone could repeat an id on the page.
  const pid = `qs-stamp-${Math.round(Number(overlay.startFrame) || 0)}-${hash(`${body}|${name}`)}`;
  const R = 94;
  const ringLen = 2 * Math.PI * R;
  const unit = `${name} • `;
  const ring = unit.repeat(Math.max(1, Math.round(44 / unit.length)));
  const fs = Math.max(14, Math.min(24, ringLen / Math.max(1, ring.length) / 0.62));
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{ position: "relative", maxWidth: 1160 * k,
          transform: `translate(${shake - 60 * k}px, ${shake * 0.4 - 90 * k}px) scale(${hold})` }}>
          <div style={{ width: 70 * k, marginBottom: 20 * k, transformOrigin: "0 100%",
            transform: `scale(${Math.max(0, ramp(frame, 0, 16, backOut)) * (1 - exit)})` }}>
            <QuoteGlyph w={70 * k} color={accent} />
          </div>
          {ls.map((ln, i) => (
            <WordLine key={i} text={ln} start={st[i]} total={total} at={8} step={step} hot={hot} hotColor={accent}
              style={{ fontFamily: INTER, fontWeight: 700, fontSize: size * k, lineHeight: 1.22, color: WHITE, letterSpacing: "-0.01em",
                textShadow: SHADOW }} />
          ))}
          {/* Lands under the end of the last line like a signature seal: only its rim touches the text block. */}
          <div style={{ position: "absolute", right: -S * 0.5, bottom: -S * 0.94, width: S, height: S,
            opacity: ramp(frame, L, 3) * (1 - exit), transform: `rotate(${rot}deg) scale(${sc * (1 + 0.15 * exit)})` }}>
            <svg width={S} height={S} viewBox="0 0 260 260" style={{ display: "block", overflow: "visible" }}>
              <defs>
                <path id={pid} d={`M 130 130 m -${R} 0 a ${R} ${R} 0 1 1 ${2 * R} 0 a ${R} ${R} 0 1 1 -${2 * R} 0`} />
              </defs>
              {shock > 0 && shock < 1 ? (
                <circle cx={130} cy={130} r={124 + 84 * shock} fill="none" stroke={accent} strokeWidth={5 * (1 - shock)}
                  opacity={0.85 * (1 - shock)} />
              ) : null}
              {burst > 0 && burst < 1
                ? Array.from({ length: 14 }, (_, i) => {
                  const a = rnd(i, 3) * Math.PI * 2;
                  const dd = 120 + (50 + 80 * rnd(i, 5)) * burst;
                  return (
                    <circle key={i} cx={130 + Math.cos(a) * dd} cy={130 + Math.sin(a) * dd}
                      r={(2 + 4 * rnd(i, 7)) * (1 - burst * 0.6)} fill={i % 3 === 0 ? WHITE : accent} opacity={1 - burst} />
                  );
                })
                : null}
              <circle cx={130} cy={130} r={124} fill="rgba(12,12,15,.74)" stroke={accent} strokeWidth={5} />
              <circle cx={130} cy={130} r={76} fill="none" stroke={accent} strokeWidth={2.5} />
              <g transform={`rotate(${spin} 130 130)`}>
                <text fontFamily={LABEL} fontWeight={800} fontSize={fs} fill={accent} letterSpacing={1}>
                  <textPath href={`#${pid}`} startOffset={0} textLength={ringLen - 8} lengthAdjust="spacing">{ring}</textPath>
                </text>
              </g>
              <text x={130} y={130 + cs * 0.36} textAnchor="middle" fontFamily={DISPLAY} fontSize={cs} fill={WHITE}
                letterSpacing={2}>{centre}</text>
              <line x1={104} x2={156} y1={130 + cs * 0.36 + 14} y2={130 + cs * 0.36 + 14} stroke={accent} strokeWidth={2.5} />
            </svg>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 9. double quote cards
/** One card: shows its accent back, flips over in 3D to the quote, a sheen crosses it, flips away at the end. */
const FlipCard: React.FC<{ item: OverlayItem; index: number; accent: string; size: number; chars: number; maxLines: number }> =
  ({ item, index, accent, size, chars, maxLines }) => {
    const frame = useCurrentFrame();
    const { fps, durationInFrames: D } = useVideoConfig();
    const k = useK();
    const W = 660 * k;
    const H = 520 * k;
    const at = 4 + index * 9;
    const enter = ramp(frame, at, 16);
    const flip = spring({ frame: Math.max(0, frame - (at + 8)), fps, config: { damping: 13, stiffness: 95, mass: 0.9 } });
    const outP = ramp(frame, D - 12 + index * 2, 9, easeIn);
    const dir = index === 0 ? -1 : 1;
    const rot = dir * 180 * (1 - flip) - dir * 90 * outP;
    const shade = Math.min(0.65, Math.abs(Math.sin((rot * Math.PI) / 180)) * 0.75);
    const ls = wrap(clean(item.text), chars, maxLines);
    const total = countWords(ls);
    const st = starts(ls);
    const textAt = at + 22;
    const step = Math.min(1.6, 24 / Math.max(1, total));
    const done = textAt + total * step + 6;
    const sheen = ramp(frame, at + 30, 26, inOut);
    // The name row has ~536 px beside its marker: longer names are cut, not clipped by the card edge.
    const who = clip(cap(clean(item.label)), 30);
    const face: React.CSSProperties = { position: "absolute", left: 0, top: 0, width: W, height: H, borderRadius: 16 * k,
      overflow: "hidden", backfaceVisibility: "hidden", WebkitBackfaceVisibility: "hidden" };
    return (
      <div style={{ width: W, height: H, opacity: Math.min(1, enter * 1.5) * (outP > 0.98 ? 0 : 1),
        transform: `translateY(${(1 - enter) * 90 * k}px)` }}>
        <div style={{ position: "relative", width: W, height: H, transformStyle: "preserve-3d",
          transform: `perspective(${1900 * k}px) translateZ(${-140 * k * (1 - flip)}px) rotateY(${rot}deg)` }}>
          <div style={{ ...face, transform: "rotateY(180deg)", display: "flex", alignItems: "center", justifyContent: "center",
            background: `linear-gradient(150deg, ${accent} 0%, ${alpha(accent, 0.72)} 100%)`,
            boxShadow: `0 ${30 * k}px ${80 * k}px rgba(0,0,0,.45)` }}>
            <div style={{ position: "absolute", left: 18 * k, top: 18 * k, right: 18 * k, bottom: 18 * k,
              border: `${2 * k}px solid rgba(12,12,15,.35)`, borderRadius: 10 * k }} />
            <QuoteGlyph w={170 * k} color="rgba(12,12,15,.82)" />
          </div>
          <div style={{ ...face, background: "linear-gradient(160deg, rgba(48,50,58,.94) 0%, rgba(18,19,23,.96) 55%, rgba(10,10,13,.97) 100%)",
            border: `${1.5 * k}px solid rgba(255,255,255,.16)`, boxShadow: `0 ${40 * k}px ${90 * k}px rgba(0,0,0,.5)` }}>
            <div style={{ position: "absolute", left: 0, top: 0, right: 0, height: 5 * k,
              background: index === 0 ? "rgba(255,255,255,.8)" : accent }} />
            <div style={{ position: "absolute", left: 0, top: 0, right: 0, bottom: 0, padding: `${46 * k}px ${50 * k}px ${40 * k}px`,
              display: "flex", flexDirection: "column" }}>
              <QuoteGlyph w={54 * k} color={accent} />
              <div style={{ marginTop: 24 * k, flex: 1 }}>
                {ls.map((ln, li) => (
                  <WordLine key={li} text={ln} start={st[li]} total={total} at={textAt} step={step} outLead={20}
                    style={{ fontFamily: INTER, fontWeight: 700, fontSize: size * k, lineHeight: 1.26, color: WHITE,
                      letterSpacing: "-0.01em" }} />
                ))}
              </div>
              {who ? (
                <>
                  <div style={{ height: 1.5 * k, width: `${ramp(frame, done, 16, inOut) * 100}%`, background: "rgba(255,255,255,.18)",
                    marginBottom: 16 * k }} />
                  <div style={{ display: "flex", alignItems: "center", gap: 14 * k }}>
                    <div style={{ width: 10 * k, height: 10 * k, background: accent, flexShrink: 0,
                      transform: `scale(${Math.max(0, ramp(frame, done + 2, 12, backOut))})` }} />
                    <Letters text={who} at={done + 4} step={0.6} outLead={20} style={{ fontFamily: LABEL, fontWeight: 800,
                      fontSize: 26 * k, letterSpacing: "0.16em", color: WHITE }} />
                  </div>
                </>
              ) : null}
            </div>
            <div style={{ position: "absolute", left: 0, top: 0, right: 0, bottom: 0, transform: `translateX(${-120 + 240 * sheen}%)`,
              background: "linear-gradient(105deg, rgba(255,255,255,0) 38%, rgba(255,255,255,.1) 50%, rgba(255,255,255,0) 62%)" }} />
            <div style={{ position: "absolute", left: 0, top: 0, right: 0, bottom: 0, background: "#000", opacity: shade }} />
          </div>
        </div>
      </div>
    );
  };

/** Two short quotes side by side on cards that flip over in turn. */
const DoubleCards: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const hold = useHold();
  const exit = useExit(14);
  const pair = (Array.isArray(overlay.items) ? overlay.items : [])
    .filter((it) => Boolean(it) && clean(it.text).length > 0)
    .slice(0, 2);
  if (pair.length < 2) return null;
  const longest = Math.max(...pair.map((it) => clean(it.text).length));
  const size = longest <= 60 ? 42 : longest <= 110 ? 36 : 31;
  // The card's text column is 560 px; Inter Bold runs ~0.58 em a character, so these measures keep a line inside it.
  const chars = size >= 42 ? 21 : size >= 36 ? 25 : 29;
  const maxLines = size >= 42 ? 5 : size >= 36 ? 6 : 7;
  // One heading line (cut with an ellipsis): its letters rise in and leave, its accent bar draws and retracts.
  const title = cap(wrap(clean(overlay.text), 44, 1)[0] || "");
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 44 * k }}>
        {title ? (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 * k }}>
            <Letters text={title} at={0} step={0.7} style={{ fontFamily: DISPLAY, fontSize: 56 * k, lineHeight: 1, color: WHITE,
              letterSpacing: "0.04em", textShadow: SHADOW }} />
            <div style={{ width: 110 * k * ramp(frame, 4, 16) * (1 - exit), height: 5 * k, background: accent,
              boxShadow: `0 0 ${12 * k}px ${alpha(accent, 0.5)}` }} />
          </div>
        ) : null}
        <div style={{ display: "flex", gap: 70 * k, transform: `scale(${hold})` }}>
          {pair.map((it, i) => (
            <FlipCard key={i} item={it} index={i} accent={accent} size={size} chars={chars} maxLines={maxLines} />
          ))}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 10. whisper subtitle (tag)
/** One lowercase line: letters rise from the centre outward while the tracking closes in. */
const WhisperLine: React.FC<{ text: string; at: number; tracking: number; style: React.CSSProperties }> =
  ({ text, at, tracking, style }) => {
    const frame = useCurrentFrame();
    const { durationInFrames: D } = useVideoConfig();
    const chars = Array.from(text);
    const n = chars.length;
    const mid = (n - 1) / 2;
    const st = Math.min(0.55, 16 / Math.max(1, mid));
    return (
      <div style={{ overflow: "hidden", padding: `0.1em 0 0.16em ${tracking}em`, whiteSpace: "pre", letterSpacing: `${tracking}em`,
        textAlign: "center", ...style }}>
        {chars.map((c, i) => {
          const d = Math.abs(i - mid);
          const pin = ramp(frame, at + d * st, 22);
          const od = mid > 0 ? (1 - d / mid) * 5 : 0;
          const pout = ramp(frame, D - 15 + od, 9, easeIn);
          return (
            <span key={i} style={{ display: "inline-block", whiteSpace: "pre", transform: `translateY(${(1 - pin) * 70 - pout * 70}%)`,
              opacity: Math.min(1, pin * 1.6) * (1 - pout) }}>{c}</span>
          );
        })}
      </div>
    );
  };

/** A cinematic lowercase quote low on the footage: wide tracking closing in, a hairline and an accent dot. */
const Whisper: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const body = clean(overlay.text).toLowerCase();
  if (!body) return null;
  const size = body.length <= 48 ? 44 : body.length <= 90 ? 38 : 34;
  const ls = wrap(body, size >= 44 ? 42 : size >= 38 ? 50 : 58, 2);
  const who = clip(cap(clean(overlay.label)), 40);
  const inP = ramp(frame, 2, Math.round(fps * 1.8));
  const outP = ramp(frame, D - 16, 15, easeIn);
  const tracking = 0.34 * (1 - inP) + 0.07 + 0.035 * interpolate(frame, [0, D], [0, 1], clamp) + 0.22 * outP;
  const line = ramp(frame, 8, 34, inOut) * (1 - outP);
  const dot = Math.max(0, ramp(frame, 6, 16, backOut)) * (1 - outP);
  const shade = ramp(frame, 0, 16) * (1 - ramp(frame, D - 10, 10));
  const drift = -interpolate(frame, [0, D], [0, 10], clamp) * k;
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: shade,
        background: "linear-gradient(to top, rgba(0,0,0,.52) 0%, rgba(0,0,0,.2) 26%, rgba(0,0,0,0) 44%)" }} />
      <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", paddingBottom: 140 * k }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", transform: `translateY(${drift}px)` }}>
          {ls.map((ln, i) => (
            <WhisperLine key={i} text={ln} at={4 + i * 6} tracking={tracking} style={{ fontFamily: INTER, fontWeight: 400,
              fontSize: size * k, lineHeight: 1.3, color: "rgba(255,255,255,.95)", textShadow: "0 3px 18px rgba(0,0,0,.65)" }} />
          ))}
          <div style={{ position: "relative", width: 640 * k, height: 14 * k, marginTop: 22 * k, display: "flex", alignItems: "center",
            justifyContent: "center" }}>
            <div style={{ width: `${line * 100}%`, height: 1.5 * k,
              background: "linear-gradient(90deg, rgba(255,255,255,0), rgba(255,255,255,.72) 22%, rgba(255,255,255,.72) 78%, rgba(255,255,255,0))" }} />
            <div style={{ position: "absolute", left: "50%", top: "50%", width: 9 * k, height: 9 * k, margin: `${-4.5 * k}px 0 0 ${-4.5 * k}px`,
              borderRadius: "50%", background: accent, transform: `scale(${dot})`, boxShadow: `0 0 ${12 * k}px ${accent}` }} />
          </div>
          {who ? (
            <Letters text={who} at={22} step={0.5} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.42em",
              padding: "0.08em 0.02em 0.1em 0.42em", color: "rgba(255,255,255,.62)", marginTop: 14 * k, textAlign: "center" }} />
          ) : null}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== registry
/** Guards every look: no overlay draws nothing, a missing accent falls back to the house gold. */
const safe = (Inner: Look): Look => {
  const Guarded: Look = ({ overlay, accent }) =>
    overlay ? <Inner overlay={overlay} accent={accent || GOLD} /> : null;
  return Guarded;
};

export const LOOKS: Record<string, Look> = {
  "qs-giant-marks": safe(GiantMarks),
  "qs-testimony-rail": safe(TestimonyRail),
  "qs-side-panel": safe(SidePanel),
  "qs-but-pivot": safe(ButPivot),
  "qs-strike-correction": safe(StrikeCorrection),
  "qs-karaoke": safe(Karaoke),
  "qs-zoom-word": safe(ZoomWord),
  "qs-said-stamp": safe(SaidStamp),
  "qs-double-cards": safe(DoubleCards),
  "qs-whisper": safe(Whisper),
};
