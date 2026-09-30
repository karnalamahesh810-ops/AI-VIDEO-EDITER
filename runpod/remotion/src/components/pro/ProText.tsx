import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY, LABEL } from "../fonts";
import { LetterLine, MaskLine, Scrim, Tag, lines, ramp, useK } from "./ProGraphics";
import { EASE, F, boldCaps, bright, caps, fit, tween, useExit } from "./Kit";
import type { Overlay } from "../../types";

/**
 * The text treatments in the pro style (the owner rejected the serif looks):
 * condensed caps that slide up out of masks, an accent block behind the key
 * word, small and placed so the footage stays the picture.
 *
 *   ProHeadline   a statement: low-left (default), centred ("center"), or with
 *                 an accent rule under it ("underline")
 *   ProHighlight  a sentence, the key words on accent blocks
 *   ProWarning    a red band across the frame, white caps
 *   ProQuote      a quote: a big accent mark, the words, the speaker
 *   ProChapter    a chapter: kicker, title, accent bar, on a light scrim
 */

const norm = (w: string) => w.toLowerCase().replace(/[^\p{L}\p{N}']/gu, "");

/**
 * One line of caps, letter by letter in and out (each letter rises out of the
 * mask in turn and drops out in turn at the end), the marked words on accent
 * blocks that wipe in behind them.
 */
const MarkedLine: React.FC<{ text: string; mark: Set<string>; accent: string; at: number; size: number }> =
  ({ text, mark, accent, at, size }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();
    const end = durationInFrames - 14;
    const words = text.split(/\s+/).filter(Boolean);
    let n = 0;
    return (
      <div style={{ overflow: "hidden", paddingBottom: "0.08em" }}>
        <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: size, lineHeight: 1.08, color: "#fff",
          textTransform: "uppercase", letterSpacing: "0.02em", textShadow: "0 6px 26px rgba(0,0,0,.55)" }}>
          {words.map((w, wi) => {
            const hot = mark.has(norm(w));
            const wipe = hot ? ramp(frame, at + 8 + n, 10) : 0;
            const letters = Array.from(w).map((c, ci) => {
              const idx = n + ci;
              const pin = ramp(frame, at + idx, 12);
              const pout = ramp(frame, end + idx * 0.6, 9);
              return <span key={ci} style={{ display: "inline-block", transform: `translateY(${(1 - pin) * 105 - pout * 105}%)` }}>{c}</span>;
            });
            n += w.length;
            return (
              <span key={wi} style={{ position: "relative", display: "inline-block", marginRight: "0.26em",
                padding: hot ? "0 0.14em" : 0 }}>
                {hot ? <span style={{ position: "absolute", inset: "6% 0 2% 0", background: accent,
                  transform: `scaleX(${wipe * (1 - ramp(frame, end, 10))})`, transformOrigin: "left" }} /> : null}
                <span style={{ position: "relative" }}>{letters}</span>
              </span>
            );
          })}
        </span>
      </div>
    );
  };

const keyWords = (text: string, given?: string): Set<string> => {
  const set = new Set((given || "").split(/[\s,]+/).map(norm).filter(Boolean));
  if (set.size) return set;
  // No marked words given: the longest word (five letters or more) carries it.
  const longest = text.split(/\s+/).reduce((m, w) => (norm(w).length > norm(m).length ? w : m), "");
  return norm(longest).length >= 5 ? new Set([norm(longest)]) : new Set();
};

export const ProHeadline: React.FC<{ overlay: Overlay; accent: string; variant?: string }> = ({ overlay, accent, variant }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const v = variant || overlay.variant || "low";
  const text = (overlay.text || "").trim();
  if (!text) return null;
  const words = text.split(/\s+/).length;
  const size = (v === "center" ? (words > 8 ? 62 : 80) : words > 8 ? 50 : 62) * k;
  const ls = lines(text, v === "center" ? 26 : 32).slice(0, 3);
  const mark = keyWords(text, overlay.highlight);
  const rule = ramp(frame, Math.round(fps * 0.4), 14);
  const block = (
    <div style={{ display: "flex", flexDirection: "column", alignItems: v === "center" ? "center" : "flex-start",
      textAlign: v === "center" ? "center" : "left" }}>
      {ls.map((ln, i) => <MarkedLine key={i} text={ln} mark={mark} accent={accent} at={2 + i * 4} size={size} />)}
      {v === "underline" ? (
        <div style={{ marginTop: 12 * k, width: 220 * k * rule, height: 6 * k, background: accent }} />
      ) : null}
    </div>
  );
  if (v === "center") {
    return (
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <AbsoluteFill style={{ background: "radial-gradient(ellipse at center, rgba(0,0,0,.35) 0%, rgba(0,0,0,0) 65%)",
          opacity: ramp(frame, 0, 10) }} />
        <div style={{ maxWidth: "76%" }}>{block}</div>
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ background: "linear-gradient(to top, rgba(0,0,0,.45) 0%, rgba(0,0,0,.15) 32%, rgba(0,0,0,0) 55%)",
        opacity: ramp(frame, 0, 10) }} />
      <div style={{ position: "absolute", left: 100 * k, bottom: 190 * k, maxWidth: "62%" }}>{block}</div>
    </AbsoluteFill>
  );
};

export const ProHighlight: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => (
  <ProHeadline overlay={overlay} accent={accent} variant="low" />
);

/**
 * An alert: a compact red pill at the top, a warning icon with a pulsing ring,
 * the words letter by letter. (The owner rejected the full-width red band.)
 */
export const ProWarning: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const red = "#e5202a";
  const text = (overlay.text || "").toUpperCase();
  const pop = ramp(frame, 0, 12);
  const pulse = (frame % Math.round(fps * 1.2)) / Math.round(fps * 1.2);
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", top: 90 * k, left: 0, right: 0, display: "flex", justifyContent: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 18 * k, padding: `${12 * k}px ${30 * k}px ${12 * k}px ${18 * k}px`,
          borderRadius: 60 * k, background: red, boxShadow: `0 14px 40px rgba(0,0,0,.45), 0 0 ${30 * k}px ${red}66`,
          transform: `scale(${0.85 + 0.15 * pop})`, opacity: pop }}>
          <div style={{ position: "relative", width: 44 * k, height: 44 * k }}>
            <div style={{ position: "absolute", inset: 0, borderRadius: "50%", border: `${3 * k}px solid #fff`,
              transform: `scale(${1 + pulse * 0.8})`, opacity: 1 - pulse }} />
            <svg width={44 * k} height={44 * k} viewBox="0 0 44 44" style={{ position: "absolute", inset: 0 }}>
              <circle cx="22" cy="22" r="21" fill="#fff" />
              <path d="M22 11 L34 32 H10 Z" fill={red} />
              <path d="M22 18 V26 M22 29 V30" stroke="#fff" strokeWidth="3" strokeLinecap="round" />
            </svg>
          </div>
          <LetterLine text={text} at={6} step={0.8} style={{ fontFamily: LABEL, fontWeight: 800,
            fontSize: (text.length > 34 ? 32 : 40) * k, color: "#fff", letterSpacing: "0.08em" }} />
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const ProQuote: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const body = (overlay.text || "").replace(/^["“”']+|["“”']+$/g, "");
  const who = overlay.label || overlay.subtitle || "";
  const ls = lines(body, 34).slice(0, 4);
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ justifyContent: "center", paddingLeft: "12%", paddingRight: "12%" }}>
        <div style={{ fontFamily: DISPLAY, fontSize: 200 * k, lineHeight: 0.6, color: accent, height: 90 * k,
          opacity: ramp(frame, 0, 10), transform: `translateY(${(1 - ramp(frame, 0, 14)) * 30 * k}px)` }}>“</div>
        {ls.map((ln, i) => (
          <MaskLine key={i} at={4 + i * 4}>
            <span style={{ fontFamily: LABEL, fontWeight: 600, fontStyle: "italic", fontSize: 64 * k, lineHeight: 1.12,
              color: "#fff", textShadow: "0 6px 26px rgba(0,0,0,.5)" }}>{ln}</span>
          </MaskLine>
        ))}
        {who ? <div style={{ marginTop: 22 * k }}><Tag text={who} at={10 + ls.length * 4} accent={accent} size={30} /></div> : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/**
 * A chapter break (HEADLINE_CHAPTER_GHOST_V1 "echo", HEADLINE_EDITORIAL_V1),
 * rebuilt 2026-09-30 in the owner's text language: the footage dims, the
 * kicker ("CHAPTER TWO") types on in outlined accent caps, the title slams up
 * letter by letter in big outlined bold caps (fitted, two lines at most) with
 * its key word in the accent, and an accent bar draws under it. "echo" adds
 * the title's key word as a giant hollow ghost behind, drifting slowly.
 * Everything drops out in the last 12 frames.
 */
export const ProChapter: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const q = useExit(12);
  const hot = bright(accent);
  const title = caps(overlay.text);
  if (!title) return null;
  const kicker = caps(overlay.subtitle) || "CHAPTER";
  const f = fit(title, F.label, 150 * k, 80 * k, Math.min(1500 * k, width - 240 * k), 2, 0.01);
  const key = keyWord(title);
  const echo = overlay.variant === "echo";
  const ghost = echo ? keyWord(title) || title.split(" ")[0] : "";
  const ghostSize = ghost ? Math.min(560 * k, (width * 0.92) / Math.max(0.5, measureCaps(ghost))) : 0;
  const drift = interpolate(frame, [0, D], [30 * k, -30 * k]);
  const bar = tween(frame, 16, 18, EASE.inOut) * (1 - q);
  let n = 0;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      {ghost ? (
        <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", opacity: tween(frame, 2, 24) * (1 - q) }}>
          <span style={{ fontFamily: DISPLAY, fontSize: ghostSize, lineHeight: 1, color: "transparent", whiteSpace: "nowrap",
            WebkitTextStroke: `${Math.max(2, 3 * k)}px rgba(255,255,255,.3)`, transform: `translateX(${drift.toFixed(2)}px)`,
            letterSpacing: "0.02em" }}>{ghost}</span>
        </AbsoluteFill>
      ) : null}
      <AbsoluteFill style={{ justifyContent: "center", paddingLeft: 120 * k }}>
        <div style={{ ...boldCaps(50 * k, hot, k, 0.18), marginBottom: 8 * k,
          clipPath: `inset(0 ${((1 - tween(frame, 0, 12)) * 100).toFixed(2)}% 0 0)`, opacity: 1 - q }}>{kicker}</div>
        {f.lines.map((ln, li) => (
          <div key={li} style={{ display: "flex", whiteSpace: "pre" }}>
            {Array.from(ln).map((c, ci) => {
              const i = n++;
              const p = tween(frame, 3 + i * 0.55, 11, EASE.out);
              const qi = tween(frame, D - 13 + i * 0.25, 9, EASE.in);
              const inKey = key && wordAt(ln, ci) === key;
              if (c === " ") return <span key={ci} style={{ display: "inline-block", width: f.size * 0.24 }} />;
              return (
                <span key={ci} style={{ ...boldCaps(f.size, inKey ? hot : "#fff", k, 0.01), display: "inline-block",
                  transform: `translateY(${((1 - p) * 70 + qi * 70).toFixed(2)}%)`, opacity: Math.min(1, p * 3) * (1 - qi) }}>{c}</span>
              );
            })}
          </div>
        ))}
        <div style={{ width: Math.min(420 * k, f.size * 3) * bar, height: 12 * k, borderRadius: 3 * k, background: hot, marginTop: 16 * k,
          boxShadow: `0 0 0 ${3 * k}px #000, 0 0 ${20 * k}px ${hot}` }} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const CH_STOP = new Set(["THE", "A", "AN", "OF", "IN", "ON", "AT", "TO", "FOR", "AND", "OR", "IS", "ARE", "WAS", "WHAT", "WHY",
  "HOW", "WHO", "THIS", "THAT", "IT", "ITS", "WITH", "FROM", "BY", "AS", "BE", "DO", "DOES", "DID", "WHEN", "WHERE"]);
/** The title's key word: its longest content word (the one the accent and the ghost carry). */
const keyWord = (title: string): string =>
  title.split(/\s+/).map((w) => w.replace(/[^\p{L}\p{N}'-]/gu, "")).filter((w) => w && !CH_STOP.has(w))
    .sort((a, b) => b.length - a.length)[0] || "";
/** The (cleaned) word a character index of a line belongs to. */
const wordAt = (line: string, idx: number): string => {
  let a = idx, b = idx;
  while (a > 0 && line[a - 1] !== " ") a--;
  while (b < line.length && line[b] !== " ") b++;
  return line.slice(a, b).replace(/[^\p{L}\p{N}'-]/gu, "");
};
/** Bebas Neue caps width in em. */
const measureCaps = (s: string): number => Array.from(s).length * 0.4;
