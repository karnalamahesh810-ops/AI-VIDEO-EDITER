import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY, LABEL } from "../fonts";
import { LetterLine, MaskLine, Scrim, Tag, lines, ramp, useK } from "./ProGraphics";
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

export const ProChapter: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const title = (overlay.text || "").toUpperCase();
  const ls = lines(title, 22).slice(0, 3);
  const bar = ramp(frame, 0, 16);
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ justifyContent: "center", paddingLeft: "10%" }}>
        <MaskLine at={0}><span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 32 * k, letterSpacing: "0.34em",
          color: accent }}>{(overlay.subtitle || "Chapter").toUpperCase()}</span></MaskLine>
        <div style={{ width: 160 * k * bar, height: 7 * k, background: accent, margin: `${14 * k}px 0 ${18 * k}px` }} />
        {ls.map((ln, i) => (
          <LetterLine key={i} text={ln} at={4 + i * 5} style={{ fontFamily: DISPLAY, fontSize: 84 * k, lineHeight: 0.98,
            color: "#fff", textShadow: "0 8px 30px rgba(0,0,0,.5)" }} />
        ))}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
