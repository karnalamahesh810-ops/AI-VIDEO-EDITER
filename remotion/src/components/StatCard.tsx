import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate, spring, Easing } from "remotion";

// VidRush-style stat card: white rounded card with a bold UPPERCASE accent header bar and
// italic-serif checkmark bullets. Springs in from a side, holds, then slides out. Bullets
// reveal staggered. Drives off `durationInFrames` (length of its own Sequence).
export type StatCardProps = {
  title: string;
  bullets: string[];
  accent?: string;
  side?: "right" | "left";
  durationInFrames: number;
};

export const StatCard: React.FC<StatCardProps> = ({
  title,
  bullets,
  accent = "#1c5a9e",
  side = "right",
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const enter = spring({ frame, fps, config: { damping: 16, mass: 0.7 }, durationInFrames: 16 });
  const exitStart = durationInFrames - 12;
  const exit = interpolate(frame, [exitStart, durationInFrames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const dir = side === "right" ? 1 : -1;
  const offX = ((1 - enter) + exit) * dir * 120; // px offscreen on enter/exit
  const opacity = interpolate(frame, [0, 8], [0, 1], { extrapolateRight: "clamp" }) * (1 - exit);

  const pos: React.CSSProperties =
    side === "right" ? { right: 70, top: 90 } : { left: 70, top: 90 };

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          width: 640,
          ...pos,
          transform: `translateX(${offX}px)`,
          opacity,
          background: "#f4f5f7",
          borderRadius: 12,
          overflow: "hidden",
          boxShadow: "0 18px 50px rgba(0,0,0,0.45)",
          fontFamily: "Georgia, 'Times New Roman', serif",
        }}
      >
        <div
          style={{
            background: accent,
            color: "#fff",
            fontFamily: "'Arial Narrow', Arial, sans-serif",
            fontWeight: 800,
            fontStyle: "normal",
            textTransform: "uppercase",
            letterSpacing: 1.2,
            fontSize: 30,
            padding: "16px 22px",
          }}
        >
          {title}
        </div>
        <div style={{ padding: "20px 24px 24px" }}>
          {bullets.map((b, i) => {
            const bf = interpolate(frame, [10 + i * 5, 18 + i * 5], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.out(Easing.ease),
            });
            return (
              <div
                key={i}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 14,
                  marginBottom: 14,
                  opacity: bf,
                  transform: `translateX(${(1 - bf) * 18}px)`,
                }}
              >
                <div
                  style={{
                    flex: "0 0 auto",
                    width: 30,
                    height: 30,
                    borderRadius: 6,
                    background: accent,
                    color: "#fff",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontWeight: 900,
                    fontSize: 18,
                  }}
                >
                  ✓
                </div>
                <div style={{ fontStyle: "italic", fontSize: 27, color: "#1a1d24", lineHeight: 1.25 }}>
                  {b}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};
