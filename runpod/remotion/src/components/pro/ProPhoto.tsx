import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { SafeImg } from "../motion/safePicture";
import { DISPLAY, LABEL, TYPEWRITER } from "../fonts";
import { MaskLine, Tag, ramp, useK } from "./ProGraphics";
import type { MapLocation, Overlay } from "../../types";

/**
 * Photo animations: a still of the story shown as a designed moment instead of
 * a plain zoom, VidRush's photo cards. The photo is the overlay's own media or
 * the scene's image underneath (Main.tsx lends it). Variants:
 *
 *   frame   the photo drops in with a white border and a slight turn onto a
 *           blurred copy of itself, a typed caption tag below   (photo-card)
 *   paper   the photo pinned on graph paper with a dashed outline
 *   place   the photo large with a location pin and the place name, the
 *           coordinates under it                                (place-card)
 *   object  the photo floating on a dark spotlight, turning slowly in 3D,
 *           its name on a leader line                           (object-card)
 *   stack   up to three photos dropping onto a pile, one after another
 *   person  a round portrait on an accent disc sliding in, the name in big
 *           condensed caps, the role in a tag                   (name-card)
 */
const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };

const photosOf = (ov: Overlay): string[] =>
  (ov.media || []).filter((m) => m && m.type === "image" && m.url).map((m) => m.url).slice(0, 3);

const Blurred: React.FC<{ src: string; brightness?: number }> = ({ src, brightness = 0.45 }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const drift = interpolate(frame, [0, Math.max(1, durationInFrames)], [0, 1], clamp);
  return (
    <AbsoluteFill>
      <SafeImg src={src} style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${1.2 + drift * 0.05})`,
        filter: `blur(26px) brightness(${brightness}) saturate(0.9)` }} />
    </AbsoluteFill>
  );
};

export const ProPhoto: React.FC<{ overlay: Overlay; accent: string; variant?: string }> = ({ overlay, accent, variant }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const photos = photosOf(overlay);
  const src = photos[0];
  const v = variant || overlay.variant || "frame";
  const hold = interpolate(frame, [0, Math.max(1, durationInFrames)], [0, 1], clamp);
  const drop = ramp(frame, 0, Math.round(fps * 0.8));
  const caption = (overlay.text || "").trim();
  if (!src) return null;

  if (v === "person") {
    const D = 560 * k;
    const slide = ramp(frame, 0, Math.round(fps * 0.9));
    return (
      <AbsoluteFill style={{ background: "#101014", overflow: "hidden" }}>
        <Blurred src={src} brightness={0.3} />
        <div style={{ position: "absolute", left: `${-8 + 20 * slide}%`, top: "50%", width: D * 1.12, height: D * 1.12,
          transform: "translateY(-50%)", borderRadius: "50%", background: accent, boxShadow: `0 0 ${80 * k}px ${accent}66` }} />
        <div style={{ position: "absolute", left: `${-6 + 21 * slide}%`, top: "50%", width: D, height: D,
          transform: `translateY(-50%) scale(${1 + hold * 0.04})`, borderRadius: "50%", overflow: "hidden",
          border: `${10 * k}px solid #fff`, boxShadow: "0 30px 80px rgba(0,0,0,.6)" }}>
          <SafeImg src={src} style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: "50% 22%" }} />
        </div>
        <div style={{ position: "absolute", left: "52%", right: "6%", top: "50%", transform: "translateY(-50%)",
          display: "flex", flexDirection: "column", gap: 18 * k }}>
          {overlay.subtitle ? <MaskLine at={10}><span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 38 * k,
            letterSpacing: "0.26em", color: "rgba(255,255,255,.8)", textTransform: "uppercase" }}>{overlay.subtitle}</span></MaskLine> : null}
          {caption.toUpperCase().split(/\s+/).reduce<string[]>((acc, w) => {
            const last = acc[acc.length - 1];
            if (last && (last + " " + w).length <= 14) acc[acc.length - 1] = last + " " + w; else acc.push(w);
            return acc;
          }, []).slice(0, 3).map((ln, i) => (
            <MaskLine key={i} at={14 + i * 4}><span style={{ fontFamily: DISPLAY, fontSize: 92 * k, lineHeight: 0.95,
              color: "#fff" }}>{ln}</span></MaskLine>
          ))}
          {overlay.label ? <Tag text={overlay.label} at={26} accent={accent} size={36} /> : null}
        </div>
      </AbsoluteFill>
    );
  }

  if (v === "place") {
    const loc = (overlay.locations || [])[0] as MapLocation | undefined;
    const coords = loc ? `${Math.abs(loc.lat).toFixed(2)}° ${loc.lat >= 0 ? "N" : "S"}  ${Math.abs(loc.lon).toFixed(2)}° ${loc.lon >= 0 ? "E" : "W"}` : "";
    const pin = ramp(frame, Math.round(fps * 0.5), 14);
    return (
      <AbsoluteFill style={{ background: "#0d0d10", overflow: "hidden" }}>
        <SafeImg src={src} style={{ width: "100%", height: "100%", objectFit: "cover",
          transform: `scale(${1.12 - 0.06 * drop + hold * 0.05})`, filter: "brightness(.9)" }} />
        <AbsoluteFill style={{ background: "linear-gradient(90deg, rgba(0,0,0,.72) 0%, rgba(0,0,0,.35) 45%, rgba(0,0,0,0) 70%)" }} />
        <div style={{ position: "absolute", left: 110 * k, bottom: 170 * k, display: "flex", flexDirection: "column", gap: 12 * k }}>
          <div style={{ display: "flex", alignItems: "center", gap: 22 * k }}>
            <svg width={70 * k} height={96 * k} viewBox="0 0 70 96" style={{ transform: `translateY(${(1 - pin) * -40 * k}px)`,
              opacity: pin, filter: `drop-shadow(0 8px 14px rgba(0,0,0,.5))` }}>
              <path d="M35 94 C35 94 4 56 4 34 A31 31 0 1 1 66 34 C66 56 35 94 35 94 Z" fill={accent} stroke="#fff" strokeWidth="4" />
              <circle cx="35" cy="34" r="12" fill="#fff" />
            </svg>
            <MaskLine at={Math.round(fps * 0.55)}><span style={{ fontFamily: DISPLAY, fontSize: 84 * k, lineHeight: 0.95,
              color: "#fff" }}>{caption.toUpperCase()}</span></MaskLine>
          </div>
          {coords ? <MaskLine at={Math.round(fps * 0.8)}><span style={{ fontFamily: TYPEWRITER, fontSize: 34 * k,
            color: "rgba(255,255,255,.85)", letterSpacing: "0.08em" }}>{coords}</span></MaskLine> : null}
          {overlay.subtitle ? <Tag text={overlay.subtitle} at={Math.round(fps * 0.9)} accent={accent} size={34} /> : null}
        </div>
      </AbsoluteFill>
    );
  }

  if (v === "object") {
    const turn = interpolate(frame, [0, Math.max(1, durationInFrames)], [-14, 10], clamp);
    const line = ramp(frame, Math.round(fps * 0.6), 16);
    const W = 820 * k, H = 560 * k;
    return (
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 45% 50%, #2a2622 0%, #121113 55%, #070708 100%)",
        alignItems: "center", justifyContent: "center", perspective: 1600 * k }}>
        <div style={{ position: "absolute", width: W * 1.3, height: W * 1.3, borderRadius: "50%",
          background: `radial-gradient(circle, ${accent}33 0%, transparent 65%)`, opacity: drop }} />
        <div style={{ width: W, height: H, transform: `rotateY(${turn}deg) scale(${0.9 + 0.1 * drop})`, opacity: drop,
          boxShadow: "0 40px 90px rgba(0,0,0,.7)", borderRadius: 14 * k, overflow: "hidden" }}>
          <SafeImg src={src} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        </div>
        {caption ? (
          <div style={{ position: "absolute", right: 150 * k, top: 190 * k, display: "flex", alignItems: "center" }}>
            <div style={{ width: `${line * 180 * k}px`, height: 3 * k, background: accent }} />
            <div style={{ opacity: line, border: `${2 * k}px solid ${accent}`, background: "rgba(10,10,12,.85)",
              padding: `${8 * k}px ${18 * k}px`, fontFamily: LABEL, fontWeight: 700, fontSize: 30 * k, color: "#fff",
              letterSpacing: "0.08em", textTransform: "uppercase" }}>{caption}</div>
          </div>
        ) : null}
      </AbsoluteFill>
    );
  }

  if (v === "stack") {
    const list = photos.length ? photos : [src];
    return (
      <AbsoluteFill style={{ background: "#141418", alignItems: "center", justifyContent: "center" }}>
        <Blurred src={list[0]} brightness={0.35} />
        {list.map((p, i) => {
          const at = i * Math.round(fps * 0.8);
          const d = ramp(frame, at, Math.round(fps * 0.6));
          const rot = [-6, 5, -2][i] || 0;
          return (
            <div key={i} style={{ position: "absolute", width: 900 * k, height: 600 * k, padding: 16 * k, background: "#f4f1ea",
              boxShadow: "0 30px 70px rgba(0,0,0,.55)", opacity: d,
              transform: `translate(${(i - 1) * 60 * k}px, ${(1 - d) * -220 * k}px) rotate(${rot + (1 - d) * 8}deg) scale(${1.08 - 0.08 * d})` }}>
              <SafeImg src={p} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
            </div>
          );
        })}
        {caption ? <div style={{ position: "absolute", bottom: 120 * k }}><Tag text={caption} at={Math.round(fps * 0.9)}
          accent={accent} size={36} /></div> : null}
      </AbsoluteFill>
    );
  }

  // frame (default) and paper
  const paper = v === "paper" || v === "grid";
  const turn = interpolate(drop, [0, 1], [-5, -1.5]);
  return (
    <AbsoluteFill style={{ background: paper ? "#ece8dc" : "#121216", alignItems: "center", justifyContent: "center", overflow: "hidden" }}>
      {paper ? (
        <AbsoluteFill style={{ backgroundImage: "linear-gradient(#7a756855 1px, transparent 1px), linear-gradient(90deg, #7a756855 1px, transparent 1px)",
          backgroundSize: `${54 * k}px ${54 * k}px` }} />
      ) : <Blurred src={src} />}
      <div style={{ position: "relative", width: 1180 * k, height: 720 * k, padding: 18 * k, background: paper ? "transparent" : "#f6f3ec",
        outline: paper ? `${3 * k}px dashed ${accent}` : "none", outlineOffset: 10 * k,
        boxShadow: paper ? "none" : "0 40px 90px rgba(0,0,0,.6)",
        transform: `translateY(${(1 - drop) * 120 * k}px) rotate(${turn}deg) scale(${0.94 + 0.06 * drop + hold * 0.03})`, opacity: drop }}>
        <SafeImg src={src} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      </div>
      {caption ? (
        <div style={{ position: "absolute", bottom: 90 * k, left: 0, right: 0, display: "flex", justifyContent: "center" }}>
          <div style={{ background: paper ? "#1b1a18" : "#0c0c0f", color: "#fff", fontFamily: TYPEWRITER, fontWeight: 700,
            fontSize: 32 * k, padding: `${8 * k}px ${22 * k}px`, letterSpacing: "0.04em",
            clipPath: `inset(0 ${(1 - ramp(frame, Math.round(fps * 0.6), 18)) * 100}% 0 0)` }}>{caption}</div>
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
