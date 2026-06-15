import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { Theme } from "../theme";
import { slideIn, popIn, stagger } from "../anim";

// SIGNATURE reference device: a titled "✓ checklist" fact-card. A colored header bar
// with an uppercase title, then 3-6 rows, each led by a rounded check box and an
// italic line of text. Two looks (matching the reference channels):
//   "panel" — dark glass card, accent header bar, light italic rows (reads over b-roll)
//   "paper" — white rounded card, dark ink, accent check boxes (the "fact-check" look)
// The card slides in from the chosen side (pops if centered); rows stagger in. Fades out.
export const FactCard: React.FC<{
  title: string;
  items: string[];
  variant?: "panel" | "paper";
  side?: "right" | "left" | "center";
  theme: Theme;
  durationInFrames: number;
}> = ({ title, items, variant = "panel", side = "right", theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const outAt = durationInFrames - 12;
  const rows = (items || []).slice(0, 6);
  const paper = variant === "paper";

  const enter =
    side === "center"
      ? popIn(frame, fps, { delay: 0, from: 0.92, outAt, outDur: 10 })
      : slideIn(frame, fps, { side: side === "left" ? "left" : "right", delay: 0, dist: 90, outAt, outDur: 10 });

  const CHECK = paper ? theme.accent : theme.accent2; // check-box fill
  const cardBg = paper ? theme.cardPaper : theme.panel;
  const ink = paper ? theme.cardInk : theme.text;
  const titleInk = paper ? theme.cardInk : "#fff";

  const justify =
    side === "center" ? "center" : side === "left" ? "flex-start" : "flex-end";
  const pad =
    side === "center" ? {} : side === "left" ? { paddingLeft: "5%" } : { paddingRight: "5%" };

  return (
    <AbsoluteFill style={{ pointerEvents: "none", display: "flex", alignItems: "center", justifyContent: justify, ...pad }}>
      <div
        style={{
          width: 780,
          maxWidth: "46%",
          background: cardBg,
          borderRadius: 18,
          overflow: "hidden",
          boxShadow: "0 24px 70px rgba(0,0,0,.55)",
          border: paper ? "1px solid rgba(0,0,0,.06)" : "1px solid rgba(255,255,255,.08)",
          opacity: enter.opacity * (paper ? 1 : 0.96),
          transform: enter.transform,
        }}
      >
        {/* Header bar */}
        <div
          style={{
            background: paper ? "transparent" : theme.accent,
            padding: paper ? "26px 32px 12px" : "20px 32px",
            borderBottom: paper ? `3px solid ${theme.accent}` : "none",
          }}
        >
          <div
            style={{
              fontFamily: theme.headerFont,
              fontWeight: 800,
              textTransform: "uppercase",
              letterSpacing: 1.2,
              fontSize: 34,
              color: titleInk,
              lineHeight: 1.12,
            }}
          >
            {title}
          </div>
        </div>

        {/* Rows */}
        <div style={{ padding: "12px 30px 22px" }}>
          {rows.map((it, i) => {
            const p = stagger(frame, i, { delay: 8, step: 6, dur: 9 });
            return (
              <div
                key={i}
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 16,
                  padding: "13px 0",
                  borderTop: i ? `1px solid ${paper ? "rgba(0,0,0,.07)" : "rgba(255,255,255,.08)"}` : "none",
                  opacity: p,
                  transform: `translateX(${(1 - p) * 20}px)`,
                }}
              >
                <div
                  style={{
                    flex: "0 0 auto",
                    width: 34,
                    height: 34,
                    borderRadius: 8,
                    background: CHECK,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    marginTop: 3,
                    boxShadow: "0 2px 8px rgba(0,0,0,.25)",
                  }}
                >
                  <span style={{ color: "#fff", fontWeight: 900, fontSize: 22, lineHeight: 1 }}>✓</span>
                </div>
                <div
                  style={{
                    fontFamily: theme.cardBulletFont,
                    fontStyle: "italic",
                    fontWeight: 600,
                    fontSize: 28,
                    lineHeight: 1.3,
                    color: ink,
                  }}
                >
                  {it}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};
