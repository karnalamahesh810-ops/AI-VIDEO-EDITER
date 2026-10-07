import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { GROTESK, INTER } from "../components/fonts";
import { HOOK_TOP, hookSize, type ShortHook } from "./shortLayout";

/**
 * The hook line at the top of a Short's first seconds: a small gold kicker (the place or subject) over a
 * clean white headline - editorial type, a soft shade behind it, an eased rise in and a fade out. The
 * owner's taste (2026-10-05): bold clean grotesk, small gold accent; no outlines, no yellow fills, no pop.
 */

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const OUT = Easing.out(Easing.cubic);

export const HookTitle: React.FC<{ hook: ShortHook | null; accent?: string; fit?: number }> = ({ hook, accent, fit = 0 }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  if (!hook || !hook.text || frame >= hook.frames) return null;
  const u = width / 1080;
  const enter = Math.round(0.42 * fps);
  const leave = Math.max(4, Math.round(0.3 * fps));
  const kickIn = interpolate(frame, [0, enter], [0, 1], { ...clamp, easing: OUT });
  const lineIn = interpolate(frame, [Math.round(0.08 * fps), Math.round(0.08 * fps) + enter], [0, 1], { ...clamp, easing: OUT });
  const out = interpolate(frame, [hook.frames - leave, hook.frames], [1, 0], clamp);
  const size = hookSize(hook.text, width);
  const gold = accent || "#F2B544";
  // A shade behind the words on bright footage; lighter when the frame is already the dimmed backdrop.
  const shade = 0.58 * (1 - 0.45 * fit) * Math.min(kickIn, 1) * out;
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div style={{
        position: "absolute", left: 0, right: 0, top: 0, height: Math.round(0.47 * height),
        background: `linear-gradient(180deg, rgba(0,0,0,${shade}) 0%, rgba(0,0,0,${shade * 0.72}) 55%, rgba(0,0,0,0) 100%)`,
      }} />
      <div style={{
        position: "absolute", left: "8%", right: "8%", top: Math.round(HOOK_TOP * height),
        display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", opacity: out,
      }}>
        {hook.kicker ? (
          <div style={{
            display: "flex", alignItems: "center", gap: Math.round(14 * u), marginBottom: Math.round(20 * u),
            opacity: kickIn, transform: `translateY(${(1 - kickIn) * 14 * u}px)`,
          }}>
            <span style={{ width: Math.round(30 * u * kickIn), height: Math.max(2, Math.round(3 * u)), background: gold, borderRadius: 2 }} />
            <span style={{
              fontFamily: INTER, fontWeight: 700, fontSize: Math.round(27 * u), letterSpacing: "0.2em", color: gold,
              textTransform: "uppercase", textShadow: "0 2px 10px rgba(0,0,0,0.6)", whiteSpace: "nowrap",
            }}>{hook.kicker}</span>
            <span style={{ width: Math.round(30 * u * kickIn), height: Math.max(2, Math.round(3 * u)), background: gold, borderRadius: 2 }} />
          </div>
        ) : null}
        <div style={{
          fontFamily: GROTESK, fontWeight: 800, fontSize: size, lineHeight: 1.06, letterSpacing: "-0.018em", color: "#fff",
          textShadow: `0 0 ${2 * u}px rgba(0,0,0,0.55), 0 ${3 * u}px ${18 * u}px rgba(0,0,0,0.6)`,
          opacity: lineIn, transform: `translateY(${(1 - lineIn) * 26 * u}px)`,
          clipPath: `inset(0 0 ${Math.round((1 - lineIn) * 40)}% 0)`,
          ...({ textWrap: "balance" } as React.CSSProperties),
        }}>{hook.text}</div>
      </div>
    </AbsoluteFill>
  );
};
