import React, { useMemo } from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { cueAt } from "../components/captionCues";
import { GROTESK } from "../components/fonts";
import { CAPTION_CENTER, type ShortWord } from "./shortLayout";
import { shortCues } from "./shortCues";

/**
 * A Short's captions: the narration's own words, two short lines at a time (shortCues.ts), in clean white
 * grotesk with a soft shadow; the spoken word a touch brighter with a thin gold bar under it. Never the
 * big yellow outlined words (the owner, 2026-10-05: "I DON'T WANT THIS STYLE"); nothing pops, scales or
 * bounces.
 */

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const SHADOW = (u: number) => [
  `0 0 ${1.6 * u}px rgba(0,0,0,0.9)`, `0 0 ${5 * u}px rgba(0,0,0,0.55)`,
  `0 ${2.5 * u}px ${5 * u}px rgba(0,0,0,0.7)`, `0 ${4 * u}px ${22 * u}px rgba(0,0,0,0.55)`,
].join(", ");
/** Seconds a cue fades where it starts or ends alone (a chained cue replaces the last one outright). */
const FADE = 0.12;
/** Seconds the spoken word takes to brighten. */
const LIGHT = 0.08;
/** The other words: solid, a little dimmer than the spoken one (never see-through). */
const DIM = 214;

export const ShortCaptions: React.FC<{ words: ShortWord[]; accent?: string }> = ({ words, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const cues = useMemo(() => shortCues(words, fps), [words, fps]);
  const cue = cueAt(cues, frame);
  if (!cue) return null;
  const u = width / 1080;
  const fade = Math.max(1, Math.round(FADE * fps));
  const opacity = Math.min(cue.fadeIn ? interpolate(frame - cue.from, [0, fade], [0, 1], clamp) : 1,
    cue.fadeOut ? interpolate(cue.to - frame, [0, fade], [0, 1], clamp) : 1);
  const now = frame / fps;
  const flat = cue.lines.flat();
  const gold = accent || "#F2B544";
  const size = Math.round(66 * u);
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div style={{
        position: "absolute", left: "7%", right: "11%", top: Math.round(CAPTION_CENTER * height), transform: "translateY(-50%)",
        display: "flex", flexDirection: "column", alignItems: "center", gap: Math.round(4 * u), opacity,
        fontFamily: GROTESK, fontWeight: 800, fontSize: size, lineHeight: 1.12, letterSpacing: "-0.012em",
        textShadow: SHADOW(u), textAlign: "center",
      }}>
        {cue.lines.map((line, li) => (
          <div key={li} style={{ whiteSpace: "nowrap" }}>
            {line.map((w, wi) => {
              const next = flat[flat.indexOf(w) + 1];
              const on = interpolate(now - w.start, [0, LIGHT], [0, 1], clamp)
                * (next ? 1 - interpolate(now - next.start, [0, LIGHT], [0, 1], clamp) : 1);
              const c = Math.round(DIM + (255 - DIM) * on);
              return (
                <span key={wi} style={{ position: "relative", display: "inline-block", color: `rgb(${c},${c},${c})` }}>
                  {wi ? " " : ""}{w.text}
                  <span style={{
                    position: "absolute", left: wi ? "0.42em" : "0.06em", right: "0.06em", bottom: "-0.02em",
                    height: Math.max(3, Math.round(5 * u)), borderRadius: 3, background: gold,
                    opacity: on * 0.95, boxShadow: "0 1px 6px rgba(0,0,0,0.45)",
                  }} />
                </span>
              );
            })}
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};
