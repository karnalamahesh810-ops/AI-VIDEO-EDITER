import React from "react";
import { interpolate, spring, useVideoConfig } from "remotion";
import { StateData } from "../data/topStates";

interface MotionGraphProps {
  state: StateData;
  progress: number; // 0–1 animation progress
  frame: number;
  style?: React.CSSProperties;
}

const BARS = [
  { key: "population", label: "Population", unit: "M", max: 40, color: "#FF6B6B" },
  { key: "gdp", label: "GDP", unit: "T$", max: 4, color: "#4ECDC4" },
  { key: "growth", label: "Growth %", unit: "%", max: 6, color: "#FFE66D" },
  { key: "jobs", label: "Jobs", unit: "M", max: 20, color: "#A8E6CF" },
];

export const MotionGraph: React.FC<MotionGraphProps> = ({
  state,
  progress,
  frame,
  style,
}) => {
  const { fps } = useVideoConfig();

  return (
    <div
      style={{
        width: "100%",
        ...style,
      }}
    >
      {/* Header */}
      <div
        style={{
          fontSize: 18,
          fontWeight: 700,
          color: "#ffffff",
          marginBottom: 20,
          textTransform: "uppercase",
          letterSpacing: "0.1em",
          opacity: progress,
        }}
      >
        Key Metrics
      </div>

      {/* Bar chart */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 18,
        }}
      >
        {BARS.map((bar, i) => {
          const barProgress = interpolate(
            progress,
            [i * 0.15, i * 0.15 + 0.6],
            [0, 1],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
          );

          const value = (state.stats as Record<string, number>)[bar.key];
          const fillPct = (value / bar.max) * 100 * barProgress;

          return (
            <div key={bar.key}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  marginBottom: 6,
                }}
              >
                <span
                  style={{
                    fontSize: 14,
                    color: "rgba(255,255,255,0.7)",
                    fontWeight: 500,
                  }}
                >
                  {bar.label}
                </span>
                <span
                  style={{
                    fontSize: 14,
                    color: bar.color,
                    fontWeight: 700,
                  }}
                >
                  {(value * barProgress).toFixed(1)}
                  {bar.unit}
                </span>
              </div>
              {/* Track */}
              <div
                style={{
                  height: 10,
                  background: "rgba(255,255,255,0.1)",
                  borderRadius: 5,
                  overflow: "hidden",
                }}
              >
                {/* Fill */}
                <div
                  style={{
                    height: "100%",
                    width: `${fillPct}%`,
                    background: `linear-gradient(90deg, ${bar.color}88, ${bar.color})`,
                    borderRadius: 5,
                    boxShadow: `0 0 10px ${bar.color}80`,
                    transition: "none",
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>

      {/* Score ring */}
      <div
        style={{
          marginTop: 30,
          display: "flex",
          alignItems: "center",
          gap: 20,
          opacity: progress,
        }}
      >
        <ScoreRing score={state.score} color={state.color} progress={progress} />
        <div>
          <div style={{ fontSize: 13, color: "rgba(255,255,255,0.5)", marginBottom: 4 }}>
            Performance Score
          </div>
          <div style={{ fontSize: 32, fontWeight: 900, color: state.color }}>
            {Math.round(state.score * progress)}
            <span style={{ fontSize: 16, opacity: 0.6 }}>/100</span>
          </div>
        </div>
      </div>
    </div>
  );
};

const ScoreRing: React.FC<{
  score: number;
  color: string;
  progress: number;
}> = ({ score, color, progress }) => {
  const r = 35;
  const circumference = 2 * Math.PI * r;
  const strokeDashoffset = circumference - (score / 100) * circumference * progress;

  return (
    <svg width={90} height={90}>
      {/* Background ring */}
      <circle
        cx={45}
        cy={45}
        r={r}
        fill="none"
        stroke="rgba(255,255,255,0.1)"
        strokeWidth={8}
      />
      {/* Score arc */}
      <circle
        cx={45}
        cy={45}
        r={r}
        fill="none"
        stroke={color}
        strokeWidth={8}
        strokeDasharray={circumference}
        strokeDashoffset={strokeDashoffset}
        strokeLinecap="round"
        transform="rotate(-90 45 45)"
        style={{ filter: `drop-shadow(0 0 6px ${color})` }}
      />
      {/* Center text */}
      <text
        x={45}
        y={50}
        textAnchor="middle"
        fill="white"
        fontSize={16}
        fontWeight="bold"
        fontFamily="sans-serif"
      >
        #{score > 90 ? "1" : score > 85 ? "3" : score > 80 ? "5" : "5"}
      </text>
    </svg>
  );
};
