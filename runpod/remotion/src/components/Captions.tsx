import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import type { Scene, TimelineProps } from "../types";

/**
 * Word-synced captions.
 *
 * Word timings come from whisper, so the active word highlights exactly on the
 * beat. Falls back to showing the whole clause when word timings are absent.
 */
export const Captions: React.FC<{
  scene: Scene;
  style: TimelineProps["captions"];
}> = ({ scene, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Scene-relative frame -> absolute seconds, to compare against word timings.
  const sceneStartSec = scene.startFrame / fps;
  const nowSec = sceneStartSec + frame / fps;

  const hasWords = scene.words && scene.words.length > 0;

  const body = hasWords ? (
    <>
      {scene.words.map((w, i) => {
        const active = nowSec >= w.start && nowSec <= w.end;
        return (
          <span
            key={i}
            style={{
              color: active ? style.accent : "#fff",
              marginRight: "0.32em",
              transition: "color 60ms linear",
            }}
          >
            {w.text}
          </span>
        );
      })}
    </>
  ) : (
    <span style={{ color: "#fff" }}>{scene.text}</span>
  );

  return (
    <AbsoluteFill
      style={{
        justifyContent: style.position === "center" ? "center" : "flex-end",
        alignItems: "center",
        padding: "0 8% 6%",
      }}
    >
      <div
        style={{
          fontFamily: `${style.fontFamily}, Inter, system-ui, sans-serif`,
          fontSize: 62,
          fontWeight: 800,
          lineHeight: 1.22,
          textAlign: "center",
          textShadow: "0 4px 18px rgba(0,0,0,0.85), 0 2px 4px rgba(0,0,0,0.9)",
          letterSpacing: "-0.01em",
        }}
      >
        {body}
      </div>
    </AbsoluteFill>
  );
};
