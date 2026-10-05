import React, { useMemo } from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { TimelineProps } from "../types";
import { cueAt } from "./captionCues";
import { planCaptions, type CaptionPlan } from "./captionPlan";
import { BOX_GAP, BOX_PAD, LEFT_EDGE, bandHeight, bandPad, unitFor } from "./captionLayout";
import { highlightColor, rgba, textStyle } from "./captionStyle";

/**
 * The burned-in subtitles: one track over the whole narration (Main.tsx),
 * drawn like professional subtitles - phrase cues of at most two lines
 * (captionCues.ts), each shown whole and still, with a short fade only where
 * a cue starts or ends after a pause, placed clear of the graphics on screen
 * with it (captionPlan.ts, captionPlace.ts). Seven styles, all data
 * (templates/registry.json captionStyles); an older document's style id
 * draws as its closest new one (templates.ts captionStyleId).
 *
 * Until 2026-10-05 this was a CapCut-like five-word strip, every word
 * popping up and scaling in. The owner: "Netflix kind of styles, clean ...
 * not cartoonish" - nothing here pops, zooms or bounces.
 */

/** Seconds a cue fades in or out where it starts or ends alone. */
const FADE_SECONDS = 0.16;
/** Seconds the spoken word takes to brighten in a highlighting style. */
const HIGHLIGHT_SECONDS = 0.08;

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };

const Band: React.FC<{ plan: CaptionPlan; frame: number; fade: number }> = ({ plan, frame, fade }) => {
  const { width, height } = useVideoConfig();
  const run = plan.bands.find(([a, b]) => frame >= a && frame < b);
  if (!run) return null;
  const f = Math.min(fade, Math.max(1, Math.floor((run[1] - run[0]) / 3)));
  const opacity = interpolate(frame, [run[0], run[0] + f, run[1] - f, run[1]], [0, 1, 1, 0], clamp);
  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", pointerEvents: "none" }}>
      <div style={{ height: bandHeight(plan.style, width, height), background: plan.style.boxColor, opacity }} />
    </AbsoluteFill>
  );
};

type TrackProps = Pick<TimelineProps, "scenes" | "overlays" | "overlaysEnabled" | "brand" | "captions">;

export const CaptionTrack: React.FC<{ props: TrackProps }> = ({ props }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const plan = useMemo(() => planCaptions(props, fps, width, height),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [props.scenes, props.overlays, props.overlaysEnabled, props.brand, props.captions?.style,
      props.captions?.position, fps, width, height]);
  const { style } = plan;
  const fade = Math.max(1, Math.round(FADE_SECONDS * fps));
  const band = style.background === "band" ? <Band plan={plan} frame={frame} fade={fade} /> : null;
  const cue = cueAt(plan.cues, frame);
  if (!cue) return band;
  const place = plan.places[plan.cues.indexOf(cue)];
  const unit = unitFor(width, height);
  const fadeIn = cue.fadeIn ? Math.min(1, (frame - cue.from + 1) / fade) : 1;
  const fadeOut = cue.fadeOut ? Math.min(1, (cue.to - frame) / fade) : 1;
  const opacity = Math.max(0, Math.min(fadeIn, fadeOut));
  // In the band only where it belongs; a cue moved clear of a graphic draws on line boxes instead.
  const inBand = style.background === "band" && place.mode === "default";
  const boxed = style.background === "box" || (style.background === "band" && !inBand);
  const nowSec = frame / fps;
  const hi = style.highlight === "word" ? highlightColor(props.captions?.accent || "#FFD400") : null;
  const words = cue.lines.flat();

  const lineNodes = cue.lines.map((line, li) => {
    const content = hi ? line.map((w, wi) => {
      // The spoken word brightens over 80 ms and settles back when the next one starts; nothing moves.
      const next = words[words.indexOf(w) + 1];
      const on = interpolate(nowSec - w.start, [0, HIGHLIGHT_SECONDS], [0, 1], clamp)
        * (next ? 1 - interpolate(nowSec - next.start, [0, HIGHLIGHT_SECONDS], [0, 1], clamp) : 1);
      const mix = (v: number) => Math.round(255 + (v - 255) * on);
      return (
        <span key={wi} style={{ color: rgba([mix(hi[0]), mix(hi[1]), mix(hi[2])], style.dim + (1 - style.dim) * on) }}>
          {wi ? " " : ""}{w.text}
        </span>
      );
    }) : line.map((w) => w.text).join(" ");
    return (
      <div key={li} style={{ textAlign: style.align === "left" ? "left" : "center" }}>
        <span style={boxed ? {
          display: "inline-block",
          background: style.boxColor || "rgba(12,12,14,0.72)",
          padding: `${BOX_PAD[0]}em ${BOX_PAD[1]}em`,
          borderRadius: style.radius * unit,
          marginTop: li ? `${BOX_GAP}em` : 0,
        } : undefined}>
          {content}
        </span>
      </div>
    );
  });

  // In the band: centred in it whatever the cue's lines; elsewhere: the planned bottom edge.
  const textH = cue.lines.length * style.lineHeight * style.size * unit;
  const bottom = inBand
    ? bandPad(style, height) + Math.max(0, (bandHeight(style, width, height) - 2 * bandPad(style, height) - textH) / 2)
    : Math.round((1 - place.y1) * height);
  const left = style.align === "left";
  return (
    <>
      {band}
      <AbsoluteFill style={{ pointerEvents: "none" }}>
        <div
          style={{
            position: "absolute",
            bottom,
            left: left ? Math.round(LEFT_EDGE * width) : "4%",
            right: "4%",
            display: "flex",
            flexDirection: "column",
            alignItems: left ? "flex-start" : "center",
            opacity,
            ...textStyle(style, unit),
            ...(boxed ? { textShadow: "none" } : null),
          }}
        >
          {lineNodes}
        </div>
      </AbsoluteFill>
    </>
  );
};
