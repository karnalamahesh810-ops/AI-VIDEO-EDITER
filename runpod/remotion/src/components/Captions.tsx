import React, { useMemo } from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { useScale } from "./layout";
import { INTER } from "./fonts";
import type { Scene, SceneWord, TimelineProps } from "../types";

/**
 * Word-synced captions, shown a few words at a time.
 *
 * The earlier version put a whole scene's narration on screen as one
 * paragraph and swept a colour highlight through it — readable for a 3-word
 * beat, an unreadable wall of text for a 15-word one. Real caption styles
 * (VidRush included) show a short rolling phrase and replace it as the
 * narration moves on, so a viewer is never asked to read ahead of the voice.
 */

interface Group {
  start: number;
  end: number;
  words: SceneWord[];
}

// A pause this long is a natural phrase break; group size is capped either
// way so a long unbroken sentence still gets cut into readable chunks.
const PAUSE_BREAK = 0.35;
const MAX_WORDS = 5;
const POP_MS = 140;

function groupWords(words: SceneWord[]): Group[] {
  const groups: Group[] = [];
  let cur: SceneWord[] = [];
  for (const w of words) {
    const prev = cur[cur.length - 1];
    const gap = prev ? w.start - prev.end : 0;
    if (cur.length && (cur.length >= MAX_WORDS || gap > PAUSE_BREAK)) {
      groups.push({ start: cur[0].start, end: cur[cur.length - 1].end, words: cur });
      cur = [];
    }
    cur.push(w);
  }
  if (cur.length) groups.push({ start: cur[0].start, end: cur[cur.length - 1].end, words: cur });
  return groups;
}

export const Captions: React.FC<{
  scene: Scene;
  style: TimelineProps["captions"];
}> = ({ scene, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = useScale();

  const sceneStartSec = scene.startFrame / fps;
  const nowSec = sceneStartSec + frame / fps;

  const hasWords = scene.words && scene.words.length > 0;
  const groups = useMemo(() => (hasWords ? groupWords(scene.words) : []), [hasWords, scene.words]);

  // The active phrase is the last one that has started; it stays on screen
  // through any gap until the next phrase begins, rather than blanking.
  let active: Group | null = null;
  for (const g of groups) {
    if (g.start <= nowSec) active = g;
    else break;
  }

  const body = active ? (
    active.words.map((w, i) => {
      const spoken = nowSec >= w.start;
      const pop = interpolate(
        (nowSec - w.start) * 1000, [0, POP_MS], [0, 1],
        { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
      );
      return (
        <span
          key={i}
          style={{
            color: nowSec >= w.start && nowSec <= w.end ? style.accent : "#fff",
            marginRight: "0.32em",
            display: "inline-block",
            opacity: spoken ? 1 : 0.94,
            transform: `translateY(${(1 - pop) * 10}px) scale(${0.92 + pop * 0.08})`,
            transition: "color 60ms linear",
          }}
        >
          {w.text}
        </span>
      );
    })
  ) : !hasWords ? (
    <span style={{ color: "#fff" }}>{scene.text}</span>
  ) : null;

  if (!body) return null;

  return (
    <AbsoluteFill
      style={{
        justifyContent: style.position === "center" ? "center" : "flex-end",
        alignItems: "center",
        padding: `0 10% ${s(70)}px`,
      }}
    >
      <div
        style={{
          fontFamily: style.fontFamily && style.fontFamily !== "Inter"
            ? `${style.fontFamily}, ${INTER}` : INTER,
          fontSize: s(64),
          fontWeight: 800,
          lineHeight: 1.18,
          textAlign: "center",
          maxWidth: "82%",
          textShadow: "0 4px 18px rgba(0,0,0,0.85), 0 2px 4px rgba(0,0,0,0.9)",
          letterSpacing: "-0.01em",
        }}
      >
        {body}
      </div>
    </AbsoluteFill>
  );
};
