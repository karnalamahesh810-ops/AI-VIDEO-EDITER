import React from "react";
import {
  AbsoluteFill,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  Easing,
  staticFile,
} from "remotion";
import { Theme } from "../theme";
import { fadeRise } from "../anim";

// Light-grey paper panel (subtle vignette) holding running body text, with an optional
// framed B&W photo near the top (thin white border) and a small right-aligned italic
// caption beneath it. If `highlightPhrase` occurs in `paragraph`, that phrase gets a
// yellow highlighter swipe behind it that wipes in left->right as it is "read".
export const HighlighterQuote: React.FC<{
  paragraph: string;
  highlightPhrase?: string;
  photoSrc?: string;
  photoCaption?: string;
  theme: Theme;
  durationInFrames: number;
}> = ({ paragraph, highlightPhrase, photoSrc, photoCaption, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  useVideoConfig();
  const outAt = durationInFrames - 12;

  const fade = interpolate(frame, [0, 10], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const fadeOut = interpolate(frame, [outAt, outAt + 12], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const rootOpacity = fade * fadeOut;

  // Split the paragraph around the (first) highlight phrase, if present.
  const hp = highlightPhrase && highlightPhrase.length > 0 ? highlightPhrase : null;
  const idx = hp ? paragraph.indexOf(hp) : -1;
  const before = idx >= 0 ? paragraph.slice(0, idx) : paragraph;
  const mid = idx >= 0 ? paragraph.slice(idx, idx + hp!.length) : "";
  const after = idx >= 0 ? paragraph.slice(idx + hp!.length) : "";

  // Highlighter wipe progress (left->right), timed to start a beat after text appears.
  const wipe = interpolate(frame, [22, 22 + 26], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  const body = fadeRise(frame, { delay: 8, dur: 14, dist: 18, outAt, outDur: 10 });
  const photo = fadeRise(frame, { delay: 2, dur: 12, dist: 16, outAt, outDur: 10 });
  const HIGHLIGHT = "#F2E84B";

  return (
    <AbsoluteFill style={{ opacity: rootOpacity }}>
      {/* Light-grey paper panel with gradient + vignette. */}
      <AbsoluteFill
        style={{
          background:
            "radial-gradient(120% 120% at 50% 40%, #E4E4E2 0%, #D9D9D9 55%, #C7C7C5 100%)",
        }}
      />
      {/* Subtle inner vignette. */}
      <AbsoluteFill
        style={{
          boxShadow: "inset 0 0 240px rgba(0,0,0,0.18)",
        }}
      />

      <div
        style={{
          position: "absolute",
          left: "12%",
          right: "12%",
          top: "50%",
          transform: "translateY(-50%)",
          display: "flex",
          flexDirection: "column",
          alignItems: "stretch",
        }}
      >
        {/* Optional framed B&W photo near the top. */}
        {photoSrc !== undefined ? (
          <div
            style={{
              alignSelf: "center",
              opacity: photo.opacity,
              transform: photo.transform,
              marginBottom: 18,
              maxWidth: 720,
            }}
          >
            <div
              style={{
                border: "8px solid #FFFFFF",
                boxShadow: "0 18px 48px rgba(0,0,0,0.32)",
                background: theme.panel,
                lineHeight: 0,
              }}
            >
              {photoSrc ? (
                <img
                  src={staticFile(photoSrc)}
                  alt=""
                  style={{
                    display: "block",
                    width: 700,
                    height: 360,
                    objectFit: "cover",
                    filter: "grayscale(1) contrast(1.05)",
                  }}
                />
              ) : (
                <div
                  style={{
                    width: 700,
                    height: 360,
                    background: `linear-gradient(135deg, ${theme.panel}, ${theme.bg})`,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: theme.textMute,
                    fontFamily: theme.bodyFont,
                    fontWeight: 700,
                    fontSize: 26,
                    letterSpacing: 1,
                  }}
                >
                  PHOTO
                </div>
              )}
            </div>
            {photoCaption ? (
              <div
                style={{
                  textAlign: "right",
                  marginTop: 8,
                  fontFamily: "Georgia,'Times New Roman',serif",
                  fontStyle: "italic",
                  fontSize: 24,
                  color: "#4A4A4A",
                }}
              >
                {photoCaption}
              </div>
            ) : null}
          </div>
        ) : null}

        {/* Running body text with optional highlighter swipe on the phrase. */}
        <div
          style={{
            fontFamily: "Georgia,'Times New Roman',serif",
            fontSize: 46,
            lineHeight: 1.5,
            color: "#1B1B1B",
            opacity: body.opacity,
            transform: body.transform,
            textAlign: "left",
          }}
        >
          {before}
          {idx >= 0 ? (
            <span
              style={{
                position: "relative",
                display: "inline",
                whiteSpace: "pre-wrap",
                // Highlighter swipe via a clipped gradient background that grows L->R.
                backgroundImage: `linear-gradient(${HIGHLIGHT}, ${HIGHLIGHT})`,
                backgroundRepeat: "no-repeat",
                backgroundPosition: "left center",
                backgroundSize: `${wipe * 100}% 78%`,
                // boxDecorationBreak lets the highlight wrap across line breaks cleanly.
                boxDecorationBreak: "clone",
                WebkitBoxDecorationBreak: "clone",
                borderRadius: 2,
                paddingBottom: 2,
              }}
            >
              {mid}
            </span>
          ) : null}
          {after}
        </div>
      </div>
    </AbsoluteFill>
  );
};
