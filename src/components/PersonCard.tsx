import React from "react";
import { interpolate, spring, useVideoConfig } from "remotion";
import { StateData } from "../data/topStates";

interface PersonCardProps {
  state: StateData;
  progress: number; // 0–1
  slideInProgress: number; // 0–1 for slide-in animation
}

export const PersonCard: React.FC<PersonCardProps> = ({
  state,
  progress,
  slideInProgress,
}) => {
  const slideX = interpolate(slideInProgress, [0, 1], [120, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        transform: `translateX(${slideX}px)`,
        opacity: interpolate(slideInProgress, [0, 0.3], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        }),
      }}
    >
      {/* Rank badge */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          marginBottom: 20,
        }}
      >
        <div
          style={{
            width: 44,
            height: 44,
            borderRadius: "50%",
            background: `linear-gradient(135deg, ${state.color}, ${state.color}88)`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 20,
            fontWeight: 900,
            color: "#1a1a2e",
            boxShadow: `0 0 20px ${state.glowColor}`,
          }}
        >
          #{state.rank}
        </div>
        <div>
          <div
            style={{
              fontSize: 12,
              color: "rgba(255,255,255,0.4)",
              textTransform: "uppercase",
              letterSpacing: "0.12em",
            }}
          >
            National Rank
          </div>
          <div
            style={{
              fontSize: 14,
              color: state.color,
              fontWeight: 600,
            }}
          >
            Top Performer
          </div>
        </div>
      </div>

      {/* State name */}
      <div
        style={{
          fontSize: 42,
          fontWeight: 900,
          color: "#ffffff",
          lineHeight: 1,
          marginBottom: 6,
          textShadow: `0 0 40px ${state.glowColor}`,
        }}
      >
        {state.name}
      </div>
      <div
        style={{
          fontSize: 14,
          color: "rgba(255,255,255,0.4)",
          marginBottom: 30,
          letterSpacing: "0.15em",
          textTransform: "uppercase",
        }}
      >
        {state.abbreviation} · United States
      </div>

      {/* Divider */}
      <div
        style={{
          height: 1,
          background: `linear-gradient(90deg, ${state.color}88, transparent)`,
          marginBottom: 24,
          width: `${100 * progress}%`,
        }}
      />

      {/* Person info */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 16,
          marginBottom: 24,
        }}
      >
        {/* Avatar */}
        <div
          style={{
            width: 60,
            height: 60,
            borderRadius: "50%",
            background: `linear-gradient(135deg, ${state.color}66, ${state.color}22)`,
            border: `2px solid ${state.color}`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 18,
            fontWeight: 800,
            color: state.color,
            boxShadow: `0 0 20px ${state.glowColor}, inset 0 0 20px ${state.glowColor}`,
            flexShrink: 0,
          }}
        >
          {state.person.avatar}
        </div>

        <div>
          <div
            style={{
              fontSize: 22,
              fontWeight: 700,
              color: "#ffffff",
              marginBottom: 3,
            }}
          >
            {state.person.name}
          </div>
          <div
            style={{
              fontSize: 13,
              color: state.color,
              fontWeight: 500,
              textTransform: "uppercase",
              letterSpacing: "0.08em",
            }}
          >
            {state.person.role}
          </div>
        </div>
      </div>
    </div>
  );
};
