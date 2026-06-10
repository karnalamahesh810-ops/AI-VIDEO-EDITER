import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { Theme } from "../theme";
import { slideIn, popIn, stagger } from "../anim";

// THE signature "checklist fact panel": rounded paper card with a solid accent header
// bar overhanging to the left, accent rounded-square checkboxes + italic body bullets.
// Slides in from `side`, bullets reveal staggered (checkbox pops, text fades), slides out.
export const StatCard: React.FC<{
  title: string;
  bullets: string[];
  side?: "left" | "right";
  torn?: boolean;
  theme: Theme;
  durationInFrames: number;
}> = ({ title, bullets, side = "right", torn = false, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const outAt = durationInFrames - 12;
  const card = slideIn(frame, fps, { side, delay: 0, dist: 140, outAt });

  // Deckle / ragged top & bottom edge for the torn variant.
  const tornClip =
    "polygon(0% 2%, 6% 0%, 14% 2.5%, 23% 0.5%, 33% 2%, 44% 0%, 55% 2.5%, 66% 0.5%, 77% 2%, 88% 0%, 95% 2.5%, 100% 1%, 100% 98%, 94% 100%, 85% 97.5%, 75% 99.5%, 64% 98%, 53% 100%, 42% 97.5%, 31% 99.5%, 21% 98%, 11% 100%, 4% 97.5%, 0% 99%)";

  const pos: React.CSSProperties =
    side === "right" ? { right: 90, top: "50%" } : { left: 90, top: "50%" };

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          width: 640,
          ...pos,
          opacity: card.opacity,
          transform: `translateY(-50%) ${card.transform}`,
          filter: "drop-shadow(0 18px 50px rgba(0,0,0,0.45))",
        }}
      >
        {/* Header bar overhangs body ~12px to the left. */}
        <div
          style={{
            position: "relative",
            marginLeft: -12,
            background: theme.accent,
            color: "#fff",
            fontFamily: theme.headerFont,
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: 1.2,
            fontSize: 32,
            lineHeight: 1.1,
            padding: "16px 24px",
            borderRadius: "10px 10px 0 0",
            zIndex: 2,
          }}
        >
          {title}
        </div>
        {/* Card body (paper). */}
        <div
          style={{
            position: "relative",
            background: theme.cardPaper,
            borderRadius: torn ? 0 : "0 10px 10px 10px",
            padding: "26px 28px 28px",
            clipPath: torn ? tornClip : undefined,
            zIndex: 1,
          }}
        >
          {bullets.map((b, i) => {
            const box = popIn(frame, fps, { delay: 12 + i * 5, from: 0.5 });
            const textP = stagger(frame, i, { delay: 16, step: 5, dur: 8 });
            return (
              <div
                key={i}
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 16,
                  marginBottom: i === bullets.length - 1 ? 0 : 16,
                }}
              >
                <div
                  style={{
                    flex: "0 0 auto",
                    width: 30,
                    height: 30,
                    borderRadius: 6,
                    background: theme.accent,
                    color: "#fff",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontFamily: theme.bodyFont,
                    fontWeight: 900,
                    fontSize: 18,
                    opacity: box.opacity,
                    transform: box.transform,
                    marginTop: 3,
                  }}
                >
                  ✓
                </div>
                <div
                  style={{
                    fontFamily: theme.cardBulletFont,
                    fontStyle: "italic",
                    fontSize: 27,
                    lineHeight: 1.28,
                    color: theme.cardInk,
                    opacity: textP,
                    transform: `translateX(${(1 - textP) * 16}px)`,
                  }}
                >
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
