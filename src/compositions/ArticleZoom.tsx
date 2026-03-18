import React from "react";
import {
  AbsoluteFill,
  Img,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { RoughHighlight } from "../components/RoughHighlight";
import {
  ALL_HIGHLIGHT_BOXES,
  FUNDING_LAPSES_BOXES,
  GOVERNMENT_SHUTDOWN_BOXES,
  IMAGE_HEIGHT,
  IMAGE_WIDTH,
} from "../ocr-data";

// ─── Timing constants (frames at 30 fps) ────────────────────────────────────
const BLUR_IN_FRAMES = 30; // unblur over first 1 s
const H1_START = 33; // government shutdown highlight starts at ~1.1 s
const H1_END = 63; // …and finishes at ~2.1 s
const H2_START = 52; // funding lapses starts at ~1.7 s (overlaps slightly)
const H2_END = 82; // …and finishes at ~2.7 s

// ─── Layout ──────────────────────────────────────────────────────────────────
// Generous padding on a 1920×1080 canvas.
const PADDING = 160; // px on each side

export const ArticleZoom: React.FC = () => {
  const frame = useCurrentFrame();
  const { width, height, durationInFrames } = useVideoConfig();

  // ── Image layout (maintain aspect ratio, fit inside padded area) ──────────
  const maxW = width - PADDING * 2;
  const maxH = height - PADDING * 2;
  const scaleByW = maxW / IMAGE_WIDTH;
  const scaleByH = maxH / IMAGE_HEIGHT;
  const imgScale = Math.min(scaleByW, scaleByH);
  const renderedW = IMAGE_WIDTH * imgScale;
  const renderedH = IMAGE_HEIGHT * imgScale;
  const imgLeft = (width - renderedW) / 2;
  const imgTop = (height - renderedH) / 2;

  // ── Blur: 8px → 0 over the first second ──────────────────────────────────
  const blurPx = interpolate(frame, [0, BLUR_IN_FRAMES], [8, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // ── Subtle zoom: 1.0 → 1.09 over the full 5 s ────────────────────────────
  const zoom = interpolate(frame, [0, durationInFrames], [1.0, 1.09], {
    extrapolateRight: "clamp",
  });

  // ── 3D rotation: each axis sweeps ±7.5° (15° total) ──────────────────────
  const rotateY = interpolate(
    frame,
    [0, durationInFrames],
    [-7.5, 7.5],
    { extrapolateRight: "clamp" }
  );
  const rotateX = interpolate(
    frame,
    [0, durationInFrames],
    [-7.5, 7.5],
    { extrapolateRight: "clamp" }
  );

  // ── Highlight progress values ─────────────────────────────────────────────
  const h1Progress = interpolate(frame, [H1_START, H1_END], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const h2Progress = interpolate(frame, [H2_START, H2_END], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Map highlight boxes to progress values: first group → h1, second → h2
  const highlightProgress = [
    ...GOVERNMENT_SHUTDOWN_BOXES.map(() => h1Progress),
    ...FUNDING_LAPSES_BOXES.map(() => h2Progress),
  ];

  return (
    <AbsoluteFill style={{ background: "white" }}>
      {/*
       * Perspective wrapper – the 3D transform is applied here so zoom and
       * rotation work together in the same coordinate system.
       */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          perspective: 1200,
          perspectiveOrigin: "50% 50%",
        }}
      >
        <div
          style={{
            position: "absolute",
            inset: 0,
            transformOrigin: "50% 50%",
            transform: `scale(${zoom}) rotateX(${rotateX}deg) rotateY(${rotateY}deg)`,
            transformStyle: "preserve-3d",
            filter: `blur(${blurPx}px)`,
            willChange: "transform, filter",
          }}
        >
          {/*
           * ── Layer 1: rough.js highlights ──────────────────────────────────
           * Rendered BEFORE the image so they sit behind the text.
           * The article image above uses mix-blend-mode: multiply so its
           * white background becomes transparent and lets the yellow through,
           * while black text stays black.
           */}
          {ALL_HIGHLIGHT_BOXES.map((box, i) => (
            <RoughHighlight
              key={box.label}
              imgX={box.x}
              imgY={box.y}
              imgW={box.w}
              imgH={box.h}
              scale={imgScale}
              imgLeft={imgLeft}
              imgTop={imgTop}
              progress={highlightProgress[i]}
              color="rgba(255, 213, 0, 0.58)"
              seed={100 + i}
            />
          ))}

          {/*
           * ── Layer 2: article image ────────────────────────────────────────
           * mix-blend-mode: multiply makes the white background transparent
           * so the highlights below show through, while the black text
           * multiplied with yellow = dark/black (text stays readable).
           */}
          <Img
            src={staticFile("article.png")}
            style={{
              position: "absolute",
              left: imgLeft,
              top: imgTop,
              width: renderedW,
              height: renderedH,
              mixBlendMode: "multiply",
              display: "block",
            }}
          />
        </div>
      </div>
    </AbsoluteFill>
  );
};
