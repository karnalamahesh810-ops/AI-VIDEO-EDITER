import React from "react";
import { AbsoluteFill, OffthreadVideo, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { SafeImg } from "../motion/safePicture";
import { DISPLAY, LABEL } from "../fonts";
import { MaskLine, ramp, useK } from "./ProGraphics";
import type { Overlay, SceneMedia } from "../../types";

/**
 * A contrast told with pictures (the owner: "a picture left, a picture right,
 * a line in the middle"): two images side by side, the right one wiping in
 * behind an accent divider, each half pushing slowly its own way, a white
 * label pill on each, an optional title across the top.
 */
const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };

const Half: React.FC<{ m: SceneMedia; drift: number; dir: 1 | -1 }> = ({ m, drift, dir }) => {
  const style: React.CSSProperties = {
    width: "100%", height: "100%", objectFit: "cover",
    transform: `scale(${1.1 + drift * 0.06}) translateX(${dir * drift * 1.5}%)`,
  };
  return m.type === "video" ? <OffthreadVideo src={m.url} muted style={style} /> : <SafeImg src={m.url} style={style} />;
};

export const ProSplit: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const media = (overlay.media || []).filter((m) => m && m.url).slice(0, 2);
  if (media.length < 2) return null;
  const labels = (overlay.items || []).map((it) => it.label || it.text || "");
  const drift = interpolate(frame, [0, Math.max(1, durationInFrames)], [0, 1], clamp);
  const left = ramp(frame, 0, Math.round(fps * 0.5));
  const right = ramp(frame, Math.round(fps * 0.35), Math.round(fps * 0.6));
  const line = ramp(frame, Math.round(fps * 0.3), Math.round(fps * 0.5));
  const pill = (text: string, at: number) => text ? (
    <div style={{ opacity: ramp(frame, at, 8), transform: `translateY(${(1 - ramp(frame, at, 12)) * 20 * k}px)`,
      background: "#fff", color: "#111", fontFamily: LABEL, fontWeight: 800, fontSize: 40 * k, letterSpacing: "0.04em",
      padding: `${10 * k}px ${28 * k}px`, borderRadius: 44 * k, textTransform: "uppercase",
      boxShadow: "0 12px 34px rgba(0,0,0,.45)" }}>{text}</div>
  ) : null;
  return (
    <AbsoluteFill style={{ background: "#0b0b0e" }}>
      <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: "50%", overflow: "hidden",
        clipPath: `inset(0 ${(1 - left) * 100}% 0 0)` }}>
        <Half m={media[0]} drift={drift} dir={-1} />
      </div>
      <div style={{ position: "absolute", right: 0, top: 0, bottom: 0, width: "50%", overflow: "hidden",
        clipPath: `inset(0 0 0 ${(1 - right) * 100}%)` }}>
        <Half m={media[1]} drift={drift} dir={1} />
      </div>
      <AbsoluteFill style={{ background: "linear-gradient(to top, rgba(0,0,0,.5) 0%, rgba(0,0,0,0) 35%), linear-gradient(to bottom, rgba(0,0,0,.35) 0%, rgba(0,0,0,0) 22%)" }} />
      {/* The divider: drawn top to bottom, with a glow and a small diamond at its middle. */}
      <div style={{ position: "absolute", left: "50%", top: 0, width: 8 * k, height: `${line * 100}%`,
        transform: "translateX(-50%)", background: accent, boxShadow: `0 0 ${24 * k}px ${accent}` }} />
      <div style={{ position: "absolute", left: "50%", top: "50%", width: 34 * k, height: 34 * k, background: "#fff",
        transform: `translate(-50%, -50%) rotate(45deg) scale(${ramp(frame, Math.round(fps * 0.7), 10)})`,
        border: `${6 * k}px solid ${accent}` }} />
      {overlay.text ? (
        <div style={{ position: "absolute", top: 60 * k, left: 0, right: 0, textAlign: "center" }}>
          <MaskLine at={4}><span style={{ fontFamily: DISPLAY, fontSize: 66 * k, color: "#fff", letterSpacing: "0.05em",
            textShadow: "0 6px 26px rgba(0,0,0,.6)" }}>{overlay.text.toUpperCase()}</span></MaskLine>
        </div>
      ) : null}
      <div style={{ position: "absolute", left: 0, width: "50%", bottom: 150 * k, display: "flex", justifyContent: "center" }}>
        {pill(labels[0] || "", Math.round(fps * 0.5))}
      </div>
      <div style={{ position: "absolute", right: 0, width: "50%", bottom: 150 * k, display: "flex", justifyContent: "center" }}>
        {pill(labels[1] || "", Math.round(fps * 0.8))}
      </div>
    </AbsoluteFill>
  );
};
