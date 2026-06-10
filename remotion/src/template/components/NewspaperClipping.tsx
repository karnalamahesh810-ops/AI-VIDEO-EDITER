import React from "react";
import { AbsoluteFill, useCurrentFrame, interpolate, Easing } from "remotion";
import { Theme } from "../theme";
import { fadeRise, drawOn } from "../anim";

// Newspaper clipping: a centered off-white page (~1200x760) with paper texture + shadow,
// a thin serif masthead rule at top, 2-3 columns of "greeked" body text (rows of short
// grey bars), and a large serif headline (Georgia bold) across the top columns with an
// optional dek beneath. If `circle`, a hand-drawn red (theme.alert) ellipse strokes on
// around the headline via stroke-dashoffset. Slow ken-burns push-in on the whole page.
// Small italic grey source bottom.
export const NewspaperClipping: React.FC<{
  headline: string;
  dek?: string;
  source?: string;
  circle?: boolean;
  theme: Theme;
  durationInFrames: number;
}> = ({ headline, dek, source, circle = false, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const outAt = durationInFrames - 12;

  const SERIF = "Georgia,'Times New Roman',serif";
  const PAPER = "#F3EFE6";
  const INK = "#1A1A18";
  const BAR = "#C9C4B8";

  const CARD_W = 1200;
  const CARD_H = 760;

  // Slow ken-burns push-in across the whole clip.
  const kb = interpolate(frame, [0, durationInFrames], [1.0, 1.06], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.ease),
  });

  // Page fadeRise in, fade out near the end.
  const page = fadeRise(frame, { delay: 0, dur: 12, dist: 22, outAt, outDur: 10 });
  const headA = fadeRise(frame, { delay: 6, dur: 12, dist: 14, outAt, outDur: 10 });
  const dekA = fadeRise(frame, { delay: 12, dur: 12, dist: 12, outAt, outDur: 10 });
  const fadeOut = interpolate(frame, [outAt, outAt + 12], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Layout geometry.
  const padX = 70;
  const mastTop = 44;
  const colTop = 250; // body columns begin below the headline block
  const contentW = CARD_W - padX * 2;

  // Headline circle: an ellipse around the headline block that draws on after settle.
  const ellCx = CARD_W / 2;
  const ellCy = 168;
  const ellRx = contentW / 2 + 8;
  const ellRy = 92;
  // Ramanujan ellipse-perimeter approximation for dasharray length.
  const hh = Math.pow(ellRx - ellRy, 2) / Math.pow(ellRx + ellRy, 2);
  const ellLen = Math.PI * (ellRx + ellRy) * (1 + (3 * hh) / (10 + Math.sqrt(4 - 3 * hh)));
  const circDraw = drawOn(frame, { delay: 22, dur: 34 });

  // Greeked body: 3 columns of short grey bars. Vary widths for a natural rag.
  const COLS = 3;
  const colGap = 36;
  const colW = (contentW - colGap * (COLS - 1)) / COLS;
  const lineH = 26; // vertical pitch per greeked line
  const barH = 9;
  const colAreaH = CARD_H - colTop - 80; // leave room for source line
  const linesPerCol = Math.floor(colAreaH / lineH);
  const widths = [1, 0.96, 0.88, 1, 0.78, 0.94, 0.85, 1, 0.7, 0.92, 0.98, 0.82, 0.9, 1, 0.75, 0.95, 0.88, 0.8, 1, 0.86];

  return (
    <AbsoluteFill
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      {/* Ken-burns wrapper around the paper page. */}
      <div
        style={{
          width: CARD_W,
          height: CARD_H,
          transform: `${page.transform} scale(${kb})`,
          transformOrigin: "center center",
          opacity: page.opacity,
        }}
      >
        <div
          style={{
            position: "relative",
            width: "100%",
            height: "100%",
            background: PAPER,
            borderRadius: 3,
            boxShadow: "0 40px 90px rgba(0,0,0,0.5), 0 6px 18px rgba(0,0,0,0.3)",
            overflow: "hidden",
            fontFamily: SERIF,
          }}
        >
          {/* Subtle paper texture: a faint vignette + grain-ish soft gradient overlay. */}
          <div
            style={{
              position: "absolute",
              inset: 0,
              background:
                "radial-gradient(120% 120% at 50% 0%, rgba(0,0,0,0) 60%, rgba(0,0,0,0.06) 100%)",
              pointerEvents: "none",
            }}
          />
          <div
            style={{
              position: "absolute",
              inset: 0,
              background:
                "linear-gradient(115deg, rgba(255,255,255,0.35) 0%, rgba(0,0,0,0) 35%, rgba(0,0,0,0.04) 100%)",
              pointerEvents: "none",
            }}
          />

          {/* Thin serif masthead rule at top (double rule). */}
          <div
            style={{
              position: "absolute",
              left: padX,
              right: padX,
              top: mastTop,
              borderTop: `2px solid ${INK}`,
              borderBottom: `1px solid ${INK}`,
              height: 10,
              opacity: 0.85,
            }}
          />

          {/* Large serif headline across the top columns. */}
          <div
            style={{
              position: "absolute",
              left: padX,
              right: padX,
              top: 92,
              fontFamily: SERIF,
              fontWeight: 800,
              fontSize: 64,
              lineHeight: 1.04,
              color: INK,
              textAlign: "center",
              letterSpacing: 0.2,
              opacity: headA.opacity,
              transform: headA.transform,
            }}
          >
            {headline}
          </div>

          {/* Optional dek (subhead) under the headline. */}
          {dek ? (
            <div
              style={{
                position: "absolute",
                left: padX + 60,
                right: padX + 60,
                top: 200,
                fontFamily: SERIF,
                fontStyle: "italic",
                fontWeight: 500,
                fontSize: 30,
                lineHeight: 1.25,
                color: "#4A4A45",
                textAlign: "center",
                opacity: dekA.opacity,
                transform: dekA.transform,
              }}
            >
              {dek}
            </div>
          ) : null}

          {/* Greeked body columns (rows of short grey bars). */}
          <svg
            viewBox={`0 0 ${CARD_W} ${CARD_H}`}
            width="100%"
            height="100%"
            style={{ position: "absolute", inset: 0, display: "block", opacity: 0.9 * fadeOut }}
          >
            {Array.from({ length: COLS }, (_, c) => {
              const cx = padX + c * (colW + colGap);
              return (
                <g key={`col${c}`}>
                  {Array.from({ length: linesPerCol }, (_, r) => {
                    const y = (dek ? colTop + 24 : colTop) + r * lineH;
                    if (y > CARD_H - 70) return null;
                    const wMul = widths[(c * 7 + r) % widths.length];
                    return (
                      <rect
                        key={`b${c}-${r}`}
                        x={cx}
                        y={y}
                        width={colW * wMul}
                        height={barH}
                        rx={2}
                        fill={BAR}
                      />
                    );
                  })}
                </g>
              );
            })}
            {/* Thin column separators. */}
            {Array.from({ length: COLS - 1 }, (_, i) => {
              const x = padX + (i + 1) * colW + colGap * i + colGap / 2;
              return (
                <line
                  key={`sep${i}`}
                  x1={x}
                  x2={x}
                  y1={(dek ? colTop + 16 : colTop - 8)}
                  y2={CARD_H - 78}
                  stroke={BAR}
                  strokeWidth={1}
                  opacity={0.7}
                />
              );
            })}
          </svg>

          {/* Hand-drawn red ellipse around the headline, draws on. */}
          {circle ? (
            <svg
              viewBox={`0 0 ${CARD_W} ${CARD_H}`}
              width="100%"
              height="100%"
              style={{ position: "absolute", inset: 0, display: "block", overflow: "visible" }}
            >
              <ellipse
                cx={ellCx}
                cy={ellCy}
                rx={ellRx}
                ry={ellRy}
                fill="none"
                stroke={theme.alert}
                strokeWidth={6}
                strokeLinecap="round"
                strokeDasharray={ellLen}
                strokeDashoffset={ellLen * (1 - circDraw)}
                transform={`rotate(-4 ${ellCx} ${ellCy})`}
                opacity={fadeOut}
                style={{ filter: "drop-shadow(0 2px 4px rgba(0,0,0,.25))" }}
              />
            </svg>
          ) : null}

          {/* Small italic grey source line, bottom. */}
          {source ? (
            <div
              style={{
                position: "absolute",
                left: padX,
                bottom: 30,
                fontFamily: SERIF,
                fontStyle: "italic",
                fontSize: 26,
                color: theme.textMute,
                opacity: 0.9 * fadeOut,
              }}
            >
              {source}
            </div>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};
