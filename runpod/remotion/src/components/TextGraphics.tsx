import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import { TEXT_SHADOW, useOverlayAnim, useScale } from "./layout";
import { INTER, NARROW, SERIF, SERIF_ITALIC, TYPEWRITER } from "./fonts";
import type { Overlay } from "../types";

/**
 * VidRush's text looks, each read off frames of their exports (see the
 * catalog in docs/vidrush-graphics.md). All of them sit ON the footage; the
 * heaviest is a partial shade behind the text, never an opaque card.
 */

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };

function ease(frame: number, at: number, frames: number) {
  return interpolate(frame, [at, at + Math.max(1, frames)], [0, 1], {
    ...clamp,
    easing: (t) => 1 - Math.pow(1 - t, 3),
  });
}

function typed(text: string, frame: number, at: number, frames: number) {
  return text.slice(0, Math.floor(text.length * ease(frame, at, frames)));
}

/** Serif title with a red hand-drawn swoosh under it ("Clerk Work", "MAUI UNION"). */
export const SwooshTitle: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(10, 10);
  const s = useScale();
  const rise = ease(frame, 0, fps * 0.45);
  const draw = ease(frame, fps * 0.35, fps * 0.6);
  const w = s(260);
  return (
    <AbsoluteFill style={{ opacity, alignItems: "center", justifyContent: "center",
      background: "radial-gradient(ellipse at 50% 45%, rgba(0,0,0,.55) 0%, rgba(0,0,0,.25) 60%, rgba(0,0,0,0) 100%)" }}>
      <div style={{ transform: `translateY(${(1 - rise) * s(24)}px)`, textAlign: "center" }}>
        <div style={{ fontFamily: SERIF, fontWeight: 400, fontSize: s(112), color: "#fff",
          textShadow: TEXT_SHADOW, letterSpacing: "0.01em" }}>
          {overlay.text}
        </div>
        <svg width={w} height={s(90)} viewBox="0 0 260 90" style={{ marginTop: s(-6) }}>
          <path d="M 250 8 C 240 55, 170 78, 20 70" fill="none" stroke={accent || "#d62828"}
            strokeWidth={5} strokeLinecap="round" pathLength={1}
            strokeDasharray={1} strokeDashoffset={1 - draw} />
        </svg>
      </div>
    </AbsoluteFill>
  );
};

/** Red boxes of typewriter text, stacked, typed on ("NO INTERVIEW." / "NO LINE."). */
export const Kicker: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(6, 10);
  const s = useScale();
  const lines = (overlay.items?.length ? overlay.items.map((i) => i.text || i.label || "")
    : (overlay.text || "").split(/\s*\|\s*|(?<=[.!?])\s+/)).filter(Boolean).slice(0, 3);
  const top = overlay.variant === "top-left";
  return (
    <AbsoluteFill style={{ opacity }}>
      <div style={{ position: "absolute", left: top ? s(90) : "50%", top: top ? s(80) : undefined,
        bottom: top ? undefined : s(140), transform: top ? undefined : "translateX(-50%)",
        display: "flex", flexDirection: "column", alignItems: top ? "flex-start" : "center", gap: s(6) }}>
        {lines.map((line, i) => {
          const at = i * fps * 0.45;
          return (
            <span key={i} style={{ opacity: ease(frame, at, 3), background: accent || "#d62828",
              color: "#fff", fontFamily: TYPEWRITER, fontWeight: 700, fontSize: s(64),
              padding: `${s(2)}px ${s(14)}px`, textTransform: "uppercase", letterSpacing: "0.02em" }}>
              {typed(line.toUpperCase(), frame, at, fps * 0.4)}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

/** A dark translucent box of large grey typewriter text ("Administrative Exclusion"). */
export const MemoBox: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay }) => {
  const { frame, fps, opacity } = useOverlayAnim(8, 10);
  const s = useScale();
  const box = ease(frame, 0, fps * 0.3);
  return (
    <AbsoluteFill style={{ opacity }}>
      <div style={{ position: "absolute", left: s(90), bottom: s(110), maxWidth: "58%",
        padding: `${s(22)}px ${s(30)}px`, background: `rgba(20,20,22,${0.62 * box})`,
        fontFamily: TYPEWRITER, fontSize: s(64), lineHeight: 1.25, color: "rgba(235,235,230,.82)" }}>
        {typed(overlay.text || "", frame, fps * 0.2, fps * 1.1)}
      </div>
    </AbsoluteFill>
  );
};

/** One to three words typed large over the footage ("She W|", "WATER"). */
export const WordType: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay }) => {
  const { frame, fps, opacity } = useOverlayAnim(4, 10);
  const s = useScale();
  const text = overlay.text || "";
  const shown = typed(text, frame, 0, fps * 0.6);
  const caps = overlay.variant === "caps";
  return (
    <AbsoluteFill style={{ opacity, justifyContent: "center", alignItems: caps ? "center" : "flex-start",
      paddingLeft: caps ? 0 : s(150) }}>
      <div style={{ fontFamily: caps ? SERIF : SERIF, fontSize: s(caps ? 84 : 96),
        letterSpacing: caps ? "0.08em" : "0.01em", color: "#fff", textShadow: TEXT_SHADOW,
        textTransform: caps ? "uppercase" : "none" }}>
        {shown}
        {shown.length < text.length ? <span style={{ opacity: 0.8 }}>|</span> : null}
      </div>
    </AbsoluteFill>
  );
};

/** A serif line low on the frame with a thin accent rule drawing under it. */
export const UnderlineTitle: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(10, 10);
  const s = useScale();
  const rule = ease(frame, fps * 0.2, fps * 0.6);
  return (
    <AbsoluteFill style={{ opacity, justifyContent: "flex-end", alignItems: "center", paddingBottom: s(150),
      background: "linear-gradient(to top, rgba(0,0,0,.45) 0%, rgba(0,0,0,0) 45%)" }}>
      <div style={{ fontFamily: SERIF, fontSize: s(64), color: "#fff", textShadow: TEXT_SHADOW,
        textAlign: "center", maxWidth: "80%" }}>
        {overlay.text}
      </div>
      <div style={{ width: `${34 * rule}%`, height: s(3), background: accent || "#d62828", marginTop: s(14) }} />
    </AbsoluteFill>
  );
};

/** A dark bar across the left of the frame, typewriter text typing into it. */
export const BarTitle: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay }) => {
  const { frame, fps, opacity } = useOverlayAnim(8, 10);
  const s = useScale();
  const bar = ease(frame, 0, fps * 0.35);
  return (
    <AbsoluteFill style={{ opacity, justifyContent: "center" }}>
      <div style={{ width: `${62 * bar}%`, background: "rgba(40,48,60,0.78)", padding: `${s(20)}px ${s(40)}px`,
        fontFamily: TYPEWRITER, fontSize: s(62), lineHeight: 1.2, color: "#f2f2ee", overflow: "hidden",
        whiteSpace: "pre-wrap", minHeight: s(80) }}>
        {typed(overlay.text || "", frame, fps * 0.25, fps * 1.0)}
      </div>
    </AbsoluteFill>
  );
};

/** "AGE 18" / "ANN, AGE 25" - a small white typewriter tag near the person. */
export const AgeTag: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay }) => {
  const { frame, fps, opacity } = useOverlayAnim(6, 10);
  const s = useScale();
  const bottom = overlay.variant === "bottom";
  const pop = ease(frame, 0, fps * 0.25);
  return (
    <AbsoluteFill style={{ opacity }}>
      <div style={{ position: "absolute", left: bottom ? "50%" : s(80), top: bottom ? undefined : s(70),
        bottom: bottom ? s(80) : undefined,
        transform: `${bottom ? "translateX(-50%) " : ""}scale(${0.9 + 0.1 * pop})`,
        background: "#f4f1ea", color: "#111", fontFamily: TYPEWRITER, fontWeight: 700, fontSize: s(46),
        padding: `${s(4)}px ${s(16)}px`, letterSpacing: "0.06em", boxShadow: "0 6px 20px rgba(0,0,0,.35)" }}>
        {typed((overlay.text || "").toUpperCase(), frame, fps * 0.1, fps * 0.4)}
      </div>
    </AbsoluteFill>
  );
};

/** The news clock badge: "00:30" over a place line, yellow, top centre. */
export const ClockBadge: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay }) => {
  const { frame, fps, opacity } = useOverlayAnim(8, 10);
  const s = useScale();
  const drop = ease(frame, 0, fps * 0.35);
  return (
    <AbsoluteFill style={{ opacity }}>
      <div style={{ position: "absolute", top: s(60), right: s(90),
        transform: `translateY(${(1 - drop) * -s(30)}px)`, display: "flex", flexDirection: "column",
        alignItems: "stretch", boxShadow: "0 8px 24px rgba(0,0,0,.45)" }}>
        <div style={{ background: "#f2c230", color: "#111", fontFamily: SERIF, fontWeight: 400,
          fontSize: s(58), textAlign: "center", padding: `${s(2)}px ${s(34)}px` }}>
          {overlay.text}
        </div>
        {overlay.subtitle ? (
          <div style={{ background: "#111", color: "#fff", fontFamily: INTER, fontWeight: 700,
            fontSize: s(18), letterSpacing: "0.08em", textAlign: "center", padding: `${s(4)}px ${s(10)}px`,
            textTransform: "uppercase" }}>
            {overlay.subtitle}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

/**
 * Person name looks other than the classic red lower-third, by variant:
 *   tag     white typewriter box, bottom-left   ("OBAMA SR.")
 *   line    red rule + name (+ year)             ("Barack Obama Sr., 1964")
 *   serif   plain serif name, bottom-right       ("Sally H. Jacobs")
 *   chyron  rounded glass bar with a dot icon    ("The Dust Bowl / America")
 */
export const PersonTag: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(8, 10);
  const s = useScale();
  const v = overlay.variant;
  const name = overlay.text || "";
  const sub = overlay.subtitle || "";
  const inX = (1 - ease(frame, 0, fps * 0.35)) * -s(30);

  if (v === "tag") {
    return (
      <AbsoluteFill style={{ opacity }}>
        <div style={{ position: "absolute", left: s(80), bottom: s(80), transform: `translateX(${inX}px)`,
          background: "#f4f1ea", color: "#111", fontFamily: TYPEWRITER, fontWeight: 700, fontSize: s(48),
          padding: `${s(4)}px ${s(18)}px`, boxShadow: "0 6px 20px rgba(0,0,0,.35)" }}>
          {typed(name.toUpperCase(), frame, 0, fps * 0.5)}
        </div>
      </AbsoluteFill>
    );
  }
  if (v === "serif") {
    return (
      <AbsoluteFill style={{ opacity }}>
        <div style={{ position: "absolute", left: s(90), bottom: s(90), fontFamily: SERIF,
          fontSize: s(54), color: "#fff", textShadow: TEXT_SHADOW }}>
          {typed(name, frame, 0, fps * 0.6)}
        </div>
      </AbsoluteFill>
    );
  }
  if (v === "chyron") {
    return (
      <AbsoluteFill style={{ opacity }}>
        <div style={{ position: "absolute", left: "50%", bottom: s(110),
          transform: `translate(-50%, ${(1 - ease(frame, 0, fps * 0.35)) * s(30)}px)`,
          minWidth: "34%", display: "flex", alignItems: "center", gap: s(22),
          padding: `${s(18)}px ${s(30)}px`, borderRadius: s(18),
          background: "rgba(24,26,30,0.72)", border: "1px solid rgba(255,255,255,.18)" }}>
          <div style={{ width: s(46), height: s(46), borderRadius: "50%", flexShrink: 0,
            border: "2px solid rgba(255,255,255,.7)", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <div style={{ width: s(12), height: s(12), borderRadius: "50%", background: accent || "#d62828" }} />
          </div>
          <div>
            <div style={{ fontFamily: INTER, fontWeight: 800, fontSize: s(38), color: "#fff" }}>{name}</div>
            {sub ? <div style={{ fontFamily: INTER, fontSize: s(24), color: "rgba(255,255,255,.65)" }}>{sub}</div> : null}
          </div>
        </div>
      </AbsoluteFill>
    );
  }
  // "line"
  return (
    <AbsoluteFill style={{ opacity }}>
      <div style={{ position: "absolute", left: s(80), bottom: s(80), display: "flex", alignItems: "center",
        gap: s(16), transform: `translateX(${inX}px)` }}>
        <div style={{ width: s(7), height: s(56), background: accent || "#d62828" }} />
        <div style={{ fontFamily: NARROW, fontWeight: 500, fontSize: s(46), color: "#fff", textShadow: TEXT_SHADOW }}>
          {typed(sub ? `${name}, ${sub}` : name, frame, fps * 0.1, fps * 0.6)}
        </div>
      </div>
    </AbsoluteFill>
  );
};

/** Italic-serif pull line over the shot, the key phrase in a red box (sentence-highlight's sibling). */
export const RedStrip: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(8, 10);
  const s = useScale();
  const strip = ease(frame, 0, fps * 0.35);
  return (
    <AbsoluteFill style={{ opacity, justifyContent: "center" }}>
      <div style={{ height: s(150), width: "100%", display: "flex", alignItems: "center", justifyContent: "center",
        background: `linear-gradient(90deg, rgba(120,10,10,0) 0%, ${accent || "#d62828"}aa ${50 - 50 * strip}%, ${accent || "#d62828"}aa ${50 + 50 * strip}%, rgba(120,10,10,0) 100%)` }}>
        <div style={{ fontFamily: SERIF_ITALIC, fontSize: s(80), color: "#fff", textShadow: TEXT_SHADOW,
          letterSpacing: "0.02em" }}>
          {typed(overlay.text || "", frame, fps * 0.15, fps * 0.8)}
        </div>
      </div>
    </AbsoluteFill>
  );
};
