import React from "react";
import { AbsoluteFill, OffthreadVideo, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { SafeImg } from "../motion/safePicture";
import { BlurBackdrop } from "../AnimationScene";
import { brandFont } from "./brandFonts";
import type { BrandClip, BrandOutroCard, BrandWatermark } from "../../types";

/**
 * The brand kit's own layers (src/brandkit.py): the logo in a corner of the
 * narration's timeline, the customer's intro sting before it, and their outro
 * after it - an end card, or their own outro video. Main.tsx places each in
 * its Sequence; these only draw.
 */
const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };

/** Margin from the frame's edge for the corner logo, as a share of the width and height. */
const EDGE_X = 0.028;
const EDGE_Y = 0.045;

/**
 * The logo, small in its corner, over the whole narration (above the
 * captions and graphics): faded in over the first half second and out over
 * the last. Drawn inside a square of `size` x the frame's width, held to the
 * corner, so a wide logo and a tall one take the same room.
 */
export const Watermark: React.FC<{ mark: BrandWatermark }> = ({ mark }) => {
  const frame = useCurrentFrame();
  const { width, height, fps, durationInFrames } = useVideoConfig();
  const box = Math.round(mark.size * width);
  const fade = Math.max(1, Math.round(fps * 0.5));
  const opacity = mark.opacity * interpolate(frame, [0, fade, Math.max(fade + 1, durationInFrames - fade),
    Math.max(fade + 2, durationInFrames)], [0, 1, 1, 0], clamp);
  const top = mark.position.startsWith("top");
  const left = mark.position.endsWith("left");
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div style={{
        position: "absolute", width: box, height: box,
        [top ? "top" : "bottom"]: Math.round(EDGE_Y * height),
        [left ? "left" : "right"]: Math.round(EDGE_X * width),
        opacity,
        filter: "drop-shadow(0 2px 6px rgba(0,0,0,0.45))",
      }}>
        <SafeImg src={mark.url} style={{
          width: "100%", height: "100%", objectFit: "contain",
          objectPosition: `${left ? "left" : "right"} ${top ? "top" : "bottom"}`,
        }} />
      </div>
    </AbsoluteFill>
  );
};

/** The customer's intro sting or outro video, whole, on black (never cropped). */
export const BrandVideo: React.FC<{ clip: BrandClip }> = ({ clip }) => (
  <AbsoluteFill style={{ backgroundColor: "#000" }}>
    <OffthreadVideo src={clip.url} volume={typeof clip.volume === "number" ? Math.max(0, Math.min(1, clip.volume)) : 0.8}
      style={{ width: "100%", height: "100%", objectFit: "contain" }} />
  </AbsoluteFill>
);

/** A bell, for the subscribe button. */
const Bell: React.FC<{ size: number; color: string }> = ({ size, color }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
    <path d="M12 3a6 6 0 0 0-6 6v3.6L4.4 15.5a1 1 0 0 0 .9 1.5h13.4a1 1 0 0 0 .9-1.5L18 12.6V9a6 6 0 0 0-6-6Z"
      fill={color} />
    <path d="M9.5 19a2.5 2.5 0 0 0 5 0" stroke={color} strokeWidth={2} strokeLinecap="round" />
  </svg>
);

/**
 * The end card: the video's last picture blurred behind the brand's colour,
 * the logo, a title ("Thanks for watching"), the subscribe button in the
 * accent colour and a line under it. Laid on the left: the right half stays
 * clear for YouTube's own end-screen boxes.
 */
export const EndCard: React.FC<{
  card: BrandOutroCard; accent: string; accent2?: string; fontFamily?: string; logo?: string; still?: string;
}> = ({ card, accent, accent2, fontFamily, logo, still }) => {
  const frame = useCurrentFrame();
  const { width, height, fps, durationInFrames } = useVideoConfig();
  const k = width / 1920;
  const font = brandFont(fontFamily);
  const enter = (delay: number) => spring({ frame: frame - delay, fps, config: { damping: 200, mass: 0.8 } });
  const out = interpolate(frame, [Math.max(1, durationInFrames - Math.round(fps * 0.5)), durationInFrames], [1, 0], clamp);
  const pic = logo || card.logo;
  const title = card.title || "";
  const text = card.text || "";
  const sub = card.subtext || "";
  const rise = (p: number) => `translateY(${(1 - p) * 34 * k}px)`;
  const pLogo = enter(2), pTitle = enter(8), pButton = enter(15), pSub = enter(21);
  return (
    <AbsoluteFill style={{ backgroundColor: "#08080a", opacity: out }}>
      <BlurBackdrop still={still || ""} frames={durationInFrames} />
      <AbsoluteFill style={{
        background: `radial-gradient(ellipse at 22% 50%, ${accent}38 0%, transparent 58%), `
          + "linear-gradient(90deg, rgba(5,5,7,0.82) 0%, rgba(5,5,7,0.55) 55%, rgba(5,5,7,0.25) 100%)",
      }} />
      <div style={{
        position: "absolute", left: Math.round(0.08 * width), top: 0, bottom: 0, width: Math.round(0.46 * width),
        display: "flex", flexDirection: "column", justifyContent: "center", gap: Math.round(26 * k),
      }}>
        {pic ? (
          <div style={{ height: Math.round(0.13 * height), opacity: pLogo, transform: `scale(${0.85 + 0.15 * pLogo})`,
            transformOrigin: "left center" }}>
            <SafeImg src={pic} style={{ height: "100%", maxWidth: "100%", objectFit: "contain", objectPosition: "left center" }} />
          </div>
        ) : null}
        {title ? (
          <div style={{ fontFamily: font, fontWeight: 800, fontSize: Math.round(84 * k), lineHeight: 1.05, color: "#fff",
            letterSpacing: "-0.01em", opacity: pTitle, transform: rise(pTitle),
            textShadow: "0 4px 24px rgba(0,0,0,0.6)" }}>{title}</div>
        ) : null}
        {text ? (
          <div style={{ opacity: pButton, transform: rise(pButton) }}>
            <span style={{
              display: "inline-flex", alignItems: "center", gap: Math.round(16 * k),
              padding: `${Math.round(18 * k)}px ${Math.round(34 * k)}px`, borderRadius: Math.round(14 * k),
              background: accent, color: "#fff", fontFamily: font, fontWeight: 800, fontSize: Math.round(44 * k),
              letterSpacing: "0.02em", textTransform: "uppercase", boxShadow: `0 ${Math.round(10 * k)}px ${Math.round(34 * k)}px ${accent}55`,
            }}>
              <Bell size={Math.round(40 * k)} color="#fff" />{text}
            </span>
          </div>
        ) : null}
        {sub ? (
          <div style={{ fontFamily: font, fontWeight: 600, fontSize: Math.round(36 * k), lineHeight: 1.3,
            color: accent2 || "rgba(255,255,255,0.82)", opacity: pSub, transform: rise(pSub) }}>{sub}</div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
