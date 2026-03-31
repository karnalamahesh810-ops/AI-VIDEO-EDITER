import React, { useMemo } from "react";
import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
  Easing,
} from "remotion";
import { USAMapSVG } from "../components/USAMapSVG";
import { PersonCard } from "../components/PersonCard";
import { MotionGraph } from "../components/MotionGraph";
import {
  TOP_5_STATES,
  INTRO_FRAMES,
  STATE_DURATION,
  StateData,
} from "../data/topStates";

// Animation phases
const MAP_REVEAL_START = INTRO_FRAMES; // 60
const MAP_REVEAL_END = 150;
const SPOTLIGHTS_START = 150;
// Each state spotlight: 72 frames = 2.4s
const OUTRO_START = SPOTLIGHTS_START + TOP_5_STATES.length * STATE_DURATION; // 150 + 360 = 510

export const USAMapComposition: React.FC = () => {
  const frame = useCurrentFrame();
  const { width, height, fps } = useVideoConfig();

  // ── Phase helpers ────────────────────────────────────────────────────────
  const introProgress = interpolate(frame, [0, 45], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  const mapRevealProgress = interpolate(
    frame,
    [MAP_REVEAL_START, MAP_REVEAL_END],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  // Which state spotlight is active?
  const activeStateIndex = useMemo(() => {
    if (frame < SPOTLIGHTS_START) return -1;
    const idx = Math.floor((frame - SPOTLIGHTS_START) / STATE_DURATION);
    return Math.min(idx, TOP_5_STATES.length - 1);
  }, [frame]);

  const activeState: StateData | null =
    activeStateIndex >= 0 ? TOP_5_STATES[activeStateIndex] : null;

  // Progress within the current state spotlight (0–1)
  const spotlightLocalFrame =
    activeStateIndex >= 0
      ? frame - SPOTLIGHTS_START - activeStateIndex * STATE_DURATION
      : 0;

  const spotlightProgress = interpolate(
    spotlightLocalFrame,
    [0, STATE_DURATION * 0.6],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const slideInProgress = interpolate(spotlightLocalFrame, [0, 25], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.back(1.2)),
  });

  // Pulse animation for the highlighted state
  const pulseProgress = spotlightLocalFrame / STATE_DURATION;

  // Outro
  const outroProgress = interpolate(
    frame,
    [OUTRO_START, OUTRO_START + 50],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  // ── Map zoom transform ────────────────────────────────────────────────────
  // When a state is highlighted, zoom the map so that state fills the left panel
  const mapZoom = useMemo(() => {
    if (!activeState || spotlightProgress < 0.05) return null;

    // Approximate zoom targets for each state (in 960x600 space)
    const zoomTargets: Record<string, { cx: number; cy: number; scale: number }> = {
      "06": { cx: 113, cy: 285, scale: 3.2 }, // California
      "48": { cx: 450, cy: 390, scale: 2.5 }, // Texas
      "12": { cx: 680, cy: 445, scale: 3.5 }, // Florida
      "36": { cx: 757, cy: 190, scale: 4.0 }, // New York
      "42": { cx: 750, cy: 213, scale: 4.0 }, // Pennsylvania
    };

    const target = zoomTargets[activeState.fips] ?? { cx: 480, cy: 300, scale: 2 };

    // Scale coordinates to actual render size
    const scaleX = (width * 0.5) / 960;
    const scaleY = height / 600;

    const cx = target.cx * scaleX;
    const cy = target.cy * scaleY;
    const sc = target.scale;

    // We want the state centroid to appear at (panelWidth/4, height/2)
    const panelWidth = width * 0.5;
    const targetX = panelWidth * 0.5;
    const targetY = height * 0.5;

    const zoomIn = spring({
      frame: spotlightLocalFrame,
      fps,
      config: { damping: 20, stiffness: 80 },
      durationInFrames: 30,
    });

    const animatedScale = interpolate(zoomIn, [0, 1], [1, sc]);
    const animatedX = interpolate(zoomIn, [0, 1], [0, targetX - cx * sc]);
    const animatedY = interpolate(zoomIn, [0, 1], [0, targetY - cy * sc]);

    return { x: animatedX, y: animatedY, scale: animatedScale };
  }, [activeState, spotlightProgress, spotlightLocalFrame, fps, width, height]);

  // ── Background ────────────────────────────────────────────────────────────
  const bgGradient = activeState
    ? `radial-gradient(ellipse at 20% 50%, ${activeState.color}18 0%, transparent 60%),
       linear-gradient(135deg, #0d0d1a 0%, #1a1a2e 50%, #0d1117 100%)`
    : "linear-gradient(135deg, #0d0d1a 0%, #1a1a2e 50%, #0d1117 100%)";

  return (
    <div
      style={{
        width,
        height,
        background: bgGradient,
        fontFamily: "'Segoe UI', Arial, sans-serif",
        overflow: "hidden",
        position: "relative",
      }}
    >
      {/* Animated background particles */}
      <BackgroundGrid width={width} height={height} frame={frame} />

      {/* ── Title (intro only) ─────────────────────────────── */}
      {frame < MAP_REVEAL_END && (
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width,
            height,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 10,
            opacity: interpolate(
              frame,
              [0, 20, MAP_REVEAL_START - 10, MAP_REVEAL_END - 5],
              [0, 1, 1, 0],
              { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
            ),
          }}
        >
          <div
            style={{
              fontSize: 72,
              fontWeight: 900,
              color: "#ffffff",
              letterSpacing: "-0.02em",
              textAlign: "center",
              textShadow: "0 0 80px rgba(78,205,196,0.5)",
              transform: `scale(${interpolate(introProgress, [0, 1], [0.8, 1])})`,
            }}
          >
            🗺 USA Regional
          </div>
          <div
            style={{
              fontSize: 72,
              fontWeight: 900,
              background: "linear-gradient(90deg, #4ECDC4, #FF6B6B, #FFE66D)",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              letterSpacing: "-0.02em",
              textAlign: "center",
              transform: `scale(${interpolate(introProgress, [0, 1], [0.8, 1])})`,
            }}
          >
            Analysis 2024
          </div>
          <div
            style={{
              fontSize: 22,
              color: "rgba(255,255,255,0.5)",
              marginTop: 20,
              letterSpacing: "0.2em",
              textTransform: "uppercase",
              opacity: interpolate(introProgress, [0.5, 1], [0, 1], {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
              }),
            }}
          >
            Top 5 States · Performance Leaders
          </div>
        </div>
      )}

      {/* ── Main layout (map + sidebar) ──────────────────── */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width,
          height,
          display: "flex",
          opacity: mapRevealProgress,
        }}
      >
        {/* LEFT: Map panel */}
        <div
          style={{
            width: activeState ? "55%" : "100%",
            height: "100%",
            position: "relative",
            transition: "none",
            overflow: "hidden",
          }}
        >
          {/* Map */}
          <div
            style={{
              position: "absolute",
              top: "50%",
              left: "50%",
              transform: "translate(-50%, -50%)",
            }}
          >
            <USAMapSVG
              width={activeState ? width * 0.55 : width * 0.9}
              height={activeState ? height : height * 0.85}
              highlightedFips={activeState?.fips ?? null}
              topStates={TOP_5_STATES}
              zoomTransform={mapZoom ?? undefined}
              mapOpacity={mapRevealProgress}
              pulseProgress={pulseProgress}
            />
          </div>

          {/* State counter pill */}
          {activeState && (
            <div
              style={{
                position: "absolute",
                bottom: 30,
                left: "50%",
                transform: "translateX(-50%)",
                display: "flex",
                gap: 8,
              }}
            >
              {TOP_5_STATES.map((s, i) => (
                <div
                  key={s.fips}
                  style={{
                    width: i === activeStateIndex ? 32 : 8,
                    height: 8,
                    borderRadius: 4,
                    background: i === activeStateIndex ? s.color : "rgba(255,255,255,0.2)",
                    boxShadow: i === activeStateIndex ? `0 0 10px ${s.color}` : "none",
                    transition: "none",
                  }}
                />
              ))}
            </div>
          )}

          {/* "USA Regional Analysis" small label */}
          {activeState && (
            <div
              style={{
                position: "absolute",
                top: 24,
                left: 28,
                fontSize: 13,
                color: "rgba(255,255,255,0.4)",
                letterSpacing: "0.15em",
                textTransform: "uppercase",
              }}
            >
              USA Regional Analysis
            </div>
          )}
        </div>

        {/* RIGHT: Info panel */}
        {activeState && (
          <div
            style={{
              width: "45%",
              height: "100%",
              padding: "50px 40px",
              display: "flex",
              flexDirection: "column",
              justifyContent: "center",
              boxSizing: "border-box",
              borderLeft: `1px solid ${activeState.color}22`,
              background: `linear-gradient(180deg, ${activeState.color}08 0%, transparent 100%)`,
            }}
          >
            <PersonCard
              state={activeState}
              progress={spotlightProgress}
              slideInProgress={slideInProgress}
            />

            <MotionGraph
              state={activeState}
              progress={spotlightProgress}
              frame={spotlightLocalFrame}
            />
          </div>
        )}
      </div>

      {/* ── Full map overview labels (no spotlight) ─────── */}
      {!activeState && mapRevealProgress > 0.5 && (
        <div
          style={{
            position: "absolute",
            bottom: 30,
            left: "50%",
            transform: "translateX(-50%)",
            display: "flex",
            gap: 20,
            opacity: interpolate(mapRevealProgress, [0.5, 1], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
          }}
        >
          {TOP_5_STATES.map((s) => (
            <div
              key={s.fips}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "6px 14px",
                borderRadius: 20,
                background: `${s.color}22`,
                border: `1px solid ${s.color}66`,
              }}
            >
              <div
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: "50%",
                  background: s.color,
                  boxShadow: `0 0 8px ${s.color}`,
                }}
              />
              <span style={{ color: "white", fontSize: 13, fontWeight: 600 }}>
                {s.abbreviation}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* ── Outro overlay ───────────────────────────────── */}
      {frame >= OUTRO_START && (
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width,
            height,
            background: "linear-gradient(135deg, #0d0d1a 0%, #1a1a2e 100%)",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            opacity: outroProgress,
            zIndex: 20,
          }}
        >
          <div
            style={{
              fontSize: 56,
              fontWeight: 900,
              color: "#ffffff",
              textAlign: "center",
              marginBottom: 20,
            }}
          >
            Top 5 States Summary
          </div>
          <div
            style={{
              display: "flex",
              gap: 20,
              flexWrap: "wrap",
              justifyContent: "center",
              maxWidth: 900,
            }}
          >
            {TOP_5_STATES.map((s, i) => (
              <div
                key={s.fips}
                style={{
                  padding: "20px 24px",
                  borderRadius: 16,
                  background: `${s.color}15`,
                  border: `1px solid ${s.color}44`,
                  minWidth: 140,
                  textAlign: "center",
                  opacity: interpolate(
                    outroProgress,
                    [i * 0.08, i * 0.08 + 0.4],
                    [0, 1],
                    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
                  ),
                  transform: `translateY(${interpolate(outroProgress, [i * 0.08, i * 0.08 + 0.4], [20, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })}px)`,
                }}
              >
                <div
                  style={{
                    fontSize: 28,
                    fontWeight: 900,
                    color: s.color,
                    marginBottom: 4,
                  }}
                >
                  #{s.rank}
                </div>
                <div style={{ fontSize: 18, fontWeight: 700, color: "#fff" }}>
                  {s.abbreviation}
                </div>
                <div style={{ fontSize: 12, color: "rgba(255,255,255,0.5)" }}>
                  {s.person.name}
                </div>
                <div
                  style={{
                    fontSize: 22,
                    fontWeight: 800,
                    color: s.color,
                    marginTop: 8,
                  }}
                >
                  {s.score}
                  <span style={{ fontSize: 12, opacity: 0.6 }}>/100</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Frame counter (debug, remove for production) */}
      {/* <div style={{position:'absolute',top:10,right:10,color:'white',fontSize:12,opacity:0.3}}>f:{frame}</div> */}
    </div>
  );
};

// Subtle background grid
const BackgroundGrid: React.FC<{
  width: number;
  height: number;
  frame: number;
}> = ({ width, height, frame }) => {
  const cols = 20;
  const rows = 12;
  const cellW = width / cols;
  const cellH = height / rows;

  return (
    <svg
      style={{ position: "absolute", top: 0, left: 0, opacity: 0.03 }}
      width={width}
      height={height}
    >
      <defs>
        <pattern
          id="grid"
          x={0}
          y={0}
          width={cellW}
          height={cellH}
          patternUnits="userSpaceOnUse"
        >
          <path
            d={`M ${cellW} 0 L 0 0 0 ${cellH}`}
            fill="none"
            stroke="rgba(255,255,255,0.5)"
            strokeWidth={0.5}
          />
        </pattern>
      </defs>
      <rect width={width} height={height} fill="url(#grid)" />
    </svg>
  );
};
