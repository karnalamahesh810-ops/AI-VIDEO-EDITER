import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate, staticFile } from "remotion";
import { Theme } from "../theme";
import { fadeRise, typewriter } from "../anim";

// Large pull quote left-of-center with curly quotation marks and an italic grey
// attribution. Optional full-black background, optional bottom-right portrait cut-out,
// optional typewriter reveal of the quote. Fades out near the end.
export const PullQuote: React.FC<{
  quote: string;
  cite?: string;
  portrait?: string;
  typed?: boolean;
  bg?: "black" | "broll";
  theme: Theme;
  durationInFrames: number;
}> = ({ quote, cite, portrait, typed = false, bg = "broll", theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const outAt = durationInFrames - 12;
  const out = interpolate(frame, [outAt, outAt + 10], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const tw = typewriter(frame, fps, quote, { delay: 6, cps: 32, cursor: true });
  const rise = fadeRise(frame, { delay: 6, dur: 12, dist: 18, outAt });
  const citeRise = fadeRise(frame, { delay: 18, dur: 12, dist: 14, outAt });

  return (
    <AbsoluteFill
      style={{
        pointerEvents: "none",
        background: bg === "black" ? "#000000" : "transparent",
      }}
    >
      {portrait ? (
        <img
          src={staticFile(portrait)}
          alt=""
          style={{
            position: "absolute",
            right: 0,
            bottom: 0,
            width: "38%",
            height: "auto",
            objectFit: "contain",
            objectPosition: "bottom right",
            opacity: 1 - out,
            filter: "drop-shadow(-10px 0 40px rgba(0,0,0,0.5))",
          }}
        />
      ) : null}

      <div
        style={{
          position: "absolute",
          left: 130,
          top: "50%",
          transform: "translateY(-50%)",
          maxWidth: 980,
        }}
      >
        <div
          style={{
            position: "relative",
            fontFamily: theme.bodyFont,
            fontWeight: 700,
            fontSize: 46,
            lineHeight: 1.3,
            color: "#fff",
            opacity: typed ? 1 - out : rise.opacity,
            transform: typed ? "none" : rise.transform,
          }}
        >
          <span
            style={{
              fontFamily: "Georgia, serif",
              color: theme.accent,
              fontSize: 90,
              lineHeight: 0,
              verticalAlign: "-0.35em",
              marginRight: 6,
            }}
          >
            “
          </span>
          {typed ? tw.text : quote}
          {typed && tw.cursor ? (
            <span style={{ color: theme.accent, fontWeight: 400 }}>|</span>
          ) : null}
          <span
            style={{
              fontFamily: "Georgia, serif",
              color: theme.accent,
              fontSize: 90,
              lineHeight: 0,
              verticalAlign: "-0.45em",
              marginLeft: 4,
            }}
          >
            ”
          </span>
        </div>

        {cite ? (
          <div
            style={{
              marginTop: 26,
              fontFamily: theme.bodyFont,
              fontStyle: "italic",
              fontSize: 28,
              color: theme.textMute,
              opacity: citeRise.opacity,
              transform: citeRise.transform,
            }}
          >
            — {cite}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
