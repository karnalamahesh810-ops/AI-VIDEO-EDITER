import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import { TEXT_SHADOW, useOverlayAnim, useScale } from "./layout";
import { INTER, NARROW, SERIF, SERIF_ITALIC } from "./fonts";
import { Rule, Shade, Words, run, useDrift } from "./kinetic";
import type { Overlay } from "../types";

/**
 * VidRush's text looks, rebuilt at broadcast scale: big type, words that rise
 * out of a blur, rules that draw, plates that settle, a slow drift on hold.
 * All of them sit ON the footage; the heaviest is a partial shade, never an
 * opaque card (the full-screen versions get their backdrop from
 * AnimationScene).
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

/** Serif title with a hand-drawn accent swoosh under it ("Clerk Work", "MAUI UNION"). */
export const SwooshTitle: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(10, 10);
  const s = useScale();
  const drift = useDrift(8);
  const draw = run(frame, fps * 0.5, fps * 0.7);
  const words = (overlay.text || "").split(/\s+/).filter(Boolean).length;
  const size = words > 5 ? 96 : 132;
  const w = s(460);
  return (
    <AbsoluteFill style={{ opacity, alignItems: "center", justifyContent: "center" }}>
      <Shade p={run(frame, 0, fps * 0.4)} strength={0.5} />
      <div style={{ textAlign: "center", transform: drift, maxWidth: "84%" }}>
        <div style={{ fontFamily: SERIF, fontWeight: 400, fontSize: s(size), color: "#fff", lineHeight: 1.08,
          textShadow: TEXT_SHADOW, letterSpacing: "0.01em" }}>
          <Words text={overlay.text} at={Math.round(fps * 0.1)} step={4} rise={36} />
        </div>
        <svg width={w} height={s(110)} viewBox="0 0 460 110" style={{ marginTop: s(-4) }}>
          <path d="M 440 12 C 420 80, 300 104, 20 88" fill="none" stroke={accent || "#d62828"}
            strokeWidth={9} strokeLinecap="round" pathLength={1}
            strokeDasharray={1} strokeDashoffset={1 - draw} />
        </svg>
      </div>
    </AbsoluteFill>
  );
};

/** Accent boxes of typewriter caps, stacked, typed on ("NO INTERVIEW." / "NO LINE."). */
export const Kicker: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(6, 10);
  const s = useScale();
  const lines = (overlay.items?.length ? overlay.items.map((i) => i.text || i.label || "")
    : (overlay.text || "").split(/\s*\|\s*|(?<=[.!?])\s+/)).filter(Boolean).slice(0, 3);
  const top = overlay.variant === "top-left";
  return (
    <AbsoluteFill style={{ opacity }}>
      <div style={{ position: "absolute", left: top ? s(96) : "50%", top: top ? s(96) : undefined,
        bottom: top ? undefined : s(150), transform: top ? undefined : "translateX(-50%)",
        display: "flex", flexDirection: "column", alignItems: top ? "flex-start" : "center", gap: s(10) }}>
        {lines.map((line, i) => {
          const at = i * fps * 0.45;
          const p = run(frame, at, fps * 0.3);
          return (
            <span key={i} style={{ background: accent || "#d62828", color: "#fff", fontFamily: NARROW, fontWeight: 700,
              fontSize: s(72), padding: `${s(6)}px ${s(28)}px`, textTransform: "uppercase", letterSpacing: "0.06em",
              boxShadow: "0 14px 40px rgba(0,0,0,.45)", clipPath: `inset(0 ${(1 - p) * 100}% 0 0)`,
              transform: `translateY(${(1 - p) * s(16)}px)` }}>
              {typed(line.toUpperCase(), frame, at + 2, fps * 0.45)}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

/** A glass memo plate of large typewriter text, an accent bar down its side. */
export const MemoBox: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(8, 10);
  const s = useScale();
  const drift = useDrift(6);
  const box = run(frame, 0, fps * 0.4);
  const text = overlay.text || "";
  const size = text.length > 70 ? 54 : 70;
  return (
    <AbsoluteFill style={{ opacity }}>
      <div style={{ position: "absolute", left: s(96), bottom: s(130), maxWidth: "62%", display: "flex", alignItems: "stretch",
        transform: drift, opacity: box, filter: "drop-shadow(0 24px 60px rgba(0,0,0,.55))" }}>
        <div style={{ width: s(12), background: accent || "#d62828", transform: `scaleY(${box})`, transformOrigin: "bottom" }} />
        <div style={{ padding: `${s(26)}px ${s(40)}px`, background: "linear-gradient(135deg, rgba(16,16,20,.86), rgba(10,10,13,.7))",
          backdropFilter: "blur(12px)", border: "1px solid rgba(255,255,255,.08)", borderLeft: "none",
          clipPath: `inset(0 ${(1 - box) * 100}% 0 0)`, fontFamily: INTER, fontWeight: 600, fontSize: s(size), lineHeight: 1.3,
          color: "rgba(244,242,238,.96)", letterSpacing: "-0.01em" }}>
          {typed(text, frame, fps * 0.2, fps * 1.2)}
          <span style={{ color: accent, opacity: Math.floor(frame / Math.max(1, Math.round(fps * 0.4))) % 2 ? 0.2 : 1 }}>|</span>
        </div>
      </div>
    </AbsoluteFill>
  );
};

/** One to three words, huge, rising out of a blur one after another ("WATER", "SHE LEFT"). */
export const WordType: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(4, 10);
  const s = useScale();
  const drift = useDrift(10);
  const text = overlay.text || "";
  const caps = overlay.variant === "caps";
  const words = text.split(/\s+/).filter(Boolean).length;
  const size = words > 5 ? 96 : words > 3 ? 120 : 150;
  const rule = run(frame, fps * 0.3 + words * 5, fps * 0.6);
  return (
    <AbsoluteFill style={{ opacity, justifyContent: "center", alignItems: "center" }}>
      <Shade p={run(frame, 0, fps * 0.3)} strength={0.45} />
      <div style={{ textAlign: "center", maxWidth: "88%", transform: drift }}>
        <div style={{ fontFamily: SERIF, fontSize: s(size), lineHeight: 1.05, letterSpacing: caps ? "0.08em" : "0.01em",
          color: "#fff", textShadow: TEXT_SHADOW, textTransform: caps ? "uppercase" : "none" }}>
          <Words text={text} at={Math.round(fps * 0.05)} step={5} rise={50} />
        </div>
        <div style={{ display: "flex", justifyContent: "center", marginTop: s(20) }}>
          <Rule p={rule} width={s(220)} height={s(6)} color={accent || "#d62828"} style={{ transformOrigin: "center" }} />
        </div>
      </div>
    </AbsoluteFill>
  );
};

/** A serif line at the lower third with an accent rule drawing under it; clear of the captions. */
export const UnderlineTitle: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(10, 10);
  const s = useScale();
  const drift = useDrift(6);
  const rule = run(frame, fps * 0.35, fps * 0.7);
  const words = (overlay.text || "").split(/\s+/).filter(Boolean).length;
  const size = words > 8 ? 62 : 84;
  return (
    <AbsoluteFill style={{ opacity, justifyContent: "flex-end", alignItems: "center", paddingBottom: "30%",
      background: "linear-gradient(to top, rgba(0,0,0,.5) 0%, rgba(0,0,0,.2) 40%, rgba(0,0,0,0) 65%)" }}>
      <div style={{ textAlign: "center", maxWidth: "80%", transform: drift }}>
        <div style={{ fontFamily: SERIF, fontSize: s(size), lineHeight: 1.15, color: "#fff", textShadow: TEXT_SHADOW }}>
          <Words text={overlay.text} at={0} step={3} rise={30} />
        </div>
        <div style={{ display: "flex", justifyContent: "center", marginTop: s(18) }}>
          <Rule p={rule} width="46%" height={s(5)} color={accent || "#d62828"} style={{ transformOrigin: "center" }} />
        </div>
      </div>
    </AbsoluteFill>
  );
};

/** A dark bar across the left of the frame, typewriter text typing into it. */
export const BarTitle: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(8, 10);
  const s = useScale();
  const bar = run(frame, 0, fps * 0.45);
  const text = overlay.text || "";
  const size = text.length > 50 ? 56 : 74;
  return (
    <AbsoluteFill style={{ opacity, justifyContent: "center" }}>
      <div style={{ width: `${70 * bar}%`, display: "flex", alignItems: "stretch", overflow: "hidden",
        boxShadow: "0 24px 70px rgba(0,0,0,.5)" }}>
        <div style={{ width: s(16), background: accent || "#d62828", flexShrink: 0 }} />
        <div style={{ flex: 1, background: "linear-gradient(90deg, rgba(20,24,32,.9) 0%, rgba(20,24,32,.72) 100%)",
          backdropFilter: "blur(10px)", padding: `${s(30)}px ${s(56)}px`, fontFamily: NARROW, fontWeight: 700, fontSize: s(size + 6),
          lineHeight: 1.16, color: "#f2f2ee", whiteSpace: "pre-wrap", minHeight: s(100), textTransform: "uppercase",
          letterSpacing: "0.03em" }}>
          {typed(text, frame, fps * 0.3, fps * 1.1)}
        </div>
      </div>
    </AbsoluteFill>
  );
};

/** "AGE 18" / "ANN, AGE 25": a cream typewriter tag near the person. */
export const AgeTag: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(6, 10);
  const s = useScale();
  const bottom = overlay.variant === "bottom";
  const pop = run(frame, 0, fps * 0.35);
  return (
    <AbsoluteFill style={{ opacity }}>
      <div style={{ position: "absolute", left: bottom ? "50%" : s(96), top: bottom ? undefined : s(90),
        bottom: bottom ? s(110) : undefined, display: "flex", alignItems: "stretch",
        transform: `${bottom ? "translateX(-50%) " : ""}scale(${0.85 + 0.15 * pop})`, opacity: pop,
        boxShadow: "0 14px 40px rgba(0,0,0,.45)" }}>
        <div style={{ width: s(10), background: accent || "#d62828" }} />
        <div style={{ background: "#f4f1ea", color: "#111", fontFamily: INTER, fontWeight: 800, fontSize: s(52),
          padding: `${s(8)}px ${s(28)}px`, letterSpacing: "0.1em" }}>
          {typed((overlay.text || "").toUpperCase(), frame, fps * 0.1, fps * 0.45)}
        </div>
      </div>
    </AbsoluteFill>
  );
};

/** The news clock badge: "06:42" over a place line, top right. */
export const ClockBadge: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay }) => {
  const { frame, fps, opacity } = useOverlayAnim(8, 10);
  const s = useScale();
  const drop = run(frame, 0, fps * 0.4);
  return (
    <AbsoluteFill style={{ opacity }}>
      <div style={{ position: "absolute", top: s(80), right: s(96), opacity: drop,
        transform: `translateY(${(1 - drop) * -s(40)}px)`, display: "flex", flexDirection: "column",
        alignItems: "stretch", boxShadow: "0 16px 40px rgba(0,0,0,.5)" }}>
        <div style={{ background: "#f2c230", color: "#111", fontFamily: NARROW, fontWeight: 700,
          fontSize: s(76), textAlign: "center", padding: `${s(4)}px ${s(40)}px`, letterSpacing: "0.04em" }}>
          {overlay.text}
        </div>
        <div style={{ background: "#111", color: "#fff", fontFamily: INTER, fontWeight: 700,
          fontSize: s(22), letterSpacing: "0.16em", textAlign: "center", padding: `${s(6)}px ${s(12)}px`,
          textTransform: "uppercase" }}>
          {overlay.subtitle || "Local time"}
        </div>
      </div>
    </AbsoluteFill>
  );
};

/**
 * Person name looks other than the classic lower-third, by variant:
 *   tag     cream typewriter box, bottom-left   ("OBAMA SR.")
 *   line    accent rule + name (+ role)         ("Barack Obama Sr., 1964")
 *   serif   plain serif name, bottom-left       ("Sally H. Jacobs")
 *   chyron  rounded glass bar with a dot icon   ("The Dust Bowl / America")
 */
export const PersonTag: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(8, 10);
  const s = useScale();
  const v = overlay.variant;
  const name = overlay.text || "";
  const sub = overlay.subtitle || "";
  const inP = run(frame, 0, fps * 0.4);
  const inX = (1 - inP) * -s(40);

  if (v === "tag") {
    return (
      <AbsoluteFill style={{ opacity }}>
        <div style={{ position: "absolute", left: s(96), bottom: "30%", display: "flex", alignItems: "stretch",
          transform: `translateX(${inX}px)`, opacity: inP, boxShadow: "0 14px 40px rgba(0,0,0,.45)" }}>
          <div style={{ width: s(10), background: accent || "#d62828" }} />
          <div style={{ background: "#f4f1ea", color: "#111", fontFamily: INTER, fontWeight: 800, fontSize: s(54),
            padding: `${s(8)}px ${s(30)}px`, letterSpacing: "0.06em" }}>
            {typed(name.toUpperCase(), frame, 0, fps * 0.5)}
          </div>
        </div>
        {sub ? (
          <div style={{ position: "absolute", left: s(106), bottom: `calc(30% - ${s(48)}px)`, fontFamily: INTER, fontWeight: 700,
            fontSize: s(26), letterSpacing: "0.14em", textTransform: "uppercase", color: "#fff", textShadow: TEXT_SHADOW,
            opacity: run(frame, fps * 0.4, fps * 0.3) }}>{sub}</div>
        ) : null}
      </AbsoluteFill>
    );
  }
  if (v === "serif") {
    return (
      <AbsoluteFill style={{ opacity }}>
        <div style={{ position: "absolute", left: s(96), bottom: "30%", fontFamily: SERIF, fontSize: s(72), color: "#fff",
          textShadow: TEXT_SHADOW, lineHeight: 1.1 }}>
          <Words text={name} at={0} step={4} rise={26} />
          {sub ? (
            <div style={{ fontFamily: SERIF_ITALIC, fontStyle: "italic", fontSize: s(34), color: "rgba(255,255,255,.85)", marginTop: s(6),
              opacity: run(frame, fps * 0.4, fps * 0.4) }}>{sub}</div>
          ) : null}
          <Rule p={run(frame, fps * 0.3, fps * 0.6)} width={s(160)} height={s(4)} color={accent || "#d62828"} style={{ marginTop: s(14) }} />
        </div>
      </AbsoluteFill>
    );
  }
  if (v === "chyron") {
    return (
      <AbsoluteFill style={{ opacity }}>
        <div style={{ position: "absolute", left: "50%", bottom: "29%",
          transform: `translate(-50%, ${(1 - inP) * s(40)}px)`, opacity: inP,
          minWidth: "40%", display: "flex", alignItems: "center", gap: s(26),
          padding: `${s(20)}px ${s(38)}px`, borderRadius: s(22),
          background: "linear-gradient(135deg, rgba(20,22,28,0.86), rgba(12,12,16,0.7))", backdropFilter: "blur(12px)",
          border: "1px solid rgba(255,255,255,.14)", boxShadow: "0 24px 60px rgba(0,0,0,.5)" }}>
          <div style={{ width: s(58), height: s(58), borderRadius: "50%", flexShrink: 0,
            border: `${s(3)}px solid rgba(255,255,255,.75)`, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <div style={{ width: s(16), height: s(16), borderRadius: "50%", background: accent || "#d62828",
              boxShadow: `0 0 ${s(16)}px ${accent || "#d62828"}` }} />
          </div>
          <div>
            <div style={{ fontFamily: INTER, fontWeight: 800, fontSize: s(48), color: "#fff", lineHeight: 1.1 }}>{name}</div>
            {sub ? <div style={{ fontFamily: INTER, fontSize: s(28), color: "rgba(255,255,255,.7)", marginTop: s(4) }}>{sub}</div> : null}
          </div>
        </div>
      </AbsoluteFill>
    );
  }
  // "line"
  return (
    <AbsoluteFill style={{ opacity }}>
      <div style={{ position: "absolute", left: s(96), bottom: "30%", display: "flex", alignItems: "center",
        gap: s(22), transform: `translateX(${inX}px)`, opacity: inP }}>
        <div style={{ width: s(9), height: s(76), background: accent || "#d62828", transform: `scaleY(${inP})` }} />
        <div>
          <div style={{ fontFamily: NARROW, fontWeight: 700, fontSize: s(62), color: "#fff", textShadow: TEXT_SHADOW, lineHeight: 1.05 }}>
            {typed(name, frame, fps * 0.1, fps * 0.5)}
          </div>
          {sub ? (
            <div style={{ fontFamily: INTER, fontWeight: 500, fontSize: s(30), color: "rgba(255,255,255,.8)", textShadow: TEXT_SHADOW,
              marginTop: s(4), opacity: run(frame, fps * 0.5, fps * 0.4) }}>{sub}</div>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};

/** Italic-serif pull line across an accent strip that opens from the centre. */
export const RedStrip: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(8, 10);
  const s = useScale();
  const strip = run(frame, 0, fps * 0.45);
  const col = accent || "#d62828";
  const text = overlay.text || "";
  const size = text.length > 40 ? 52 : text.length > 22 ? 64 : 88;
  return (
    <AbsoluteFill style={{ opacity, justifyContent: "center" }}>
      <div style={{ height: s(190), width: "100%", display: "flex", alignItems: "center", justifyContent: "center",
        background: `linear-gradient(90deg, ${col}00 0%, ${col}cc ${50 - 50 * strip}%, ${col}cc ${50 + 50 * strip}%, ${col}00 100%)`,
        boxShadow: `0 0 ${s(60)}px rgba(0,0,0,.35)` }}>
        <div style={{ fontFamily: SERIF_ITALIC, fontStyle: "italic", fontSize: s(size), color: "#fff", textShadow: TEXT_SHADOW,
          letterSpacing: "0.02em", maxWidth: "88%", textAlign: "center" }}>
          <Words text={text} at={Math.round(fps * 0.15)} step={3} rise={26} />
        </div>
      </div>
    </AbsoluteFill>
  );
};
