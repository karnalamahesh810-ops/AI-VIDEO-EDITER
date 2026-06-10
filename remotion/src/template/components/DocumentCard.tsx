import React from "react";
import { AbsoluteFill, useCurrentFrame, interpolate, Easing } from "remotion";
import { Theme } from "../theme";
import { fadeRise, stagger } from "../anim";

// "Official document" card. A centered off-white paper panel (~1100x680) with a
// subtle drop shadow + faint horizontal page lines, shown with a slow ken-burns
// push-in (scale 1.0 -> 1.06). Optional bold dark title at top. Each row is a ruled
// line with a left label (dark) and right value (dark bold) in a serif face. If
// `highlightRow` is set, a yellow (#F2E84B) highlighter swipe wipes left->right
// behind that row after the rows settle. Small italic grey source line bottom-right.
export const DocumentCard: React.FC<{
  title?: string;
  rows: { label: string; value: string }[];
  highlightRow?: number;
  source?: string;
  theme: Theme;
  durationInFrames: number;
}> = ({ title, rows, highlightRow, source, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const outAt = durationInFrames - 12;

  const SERIF = "Georgia,'Times New Roman',serif";
  const PAPER = "#F6F6F3";
  const INK = "#1B1B1B";
  const RULE = "#D7D7D0";
  const HIGHLIGHT = "#F2E84B";

  const CARD_W = 1100;
  const CARD_H = 680;

  // Slow ken-burns push-in across the whole clip.
  const kb = interpolate(frame, [0, durationInFrames], [1.0, 1.06], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.ease),
  });

  // Panel fadeRise in, fade out near the end.
  const panel = fadeRise(frame, { delay: 0, dur: 12, dist: 22, outAt, outDur: 10 });
  const titleA = fadeRise(frame, { delay: 6, dur: 12, dist: 14, outAt, outDur: 10 });
  const fadeOut = interpolate(frame, [outAt, outAt + 12], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Rows stagger in after the panel/title; highlight sweep starts once rows settle.
  const ROW_DELAY = 16;
  const ROW_STEP = 5;
  const rowsSettledAt = ROW_DELAY + rows.length * ROW_STEP + 8;
  const wipe = interpolate(frame, [rowsSettledAt, rowsSettledAt + 26], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  // Layout: title block then evenly spaced rows inside the paper padding.
  const padX = 80;
  const padTop = title ? 150 : 90;
  const padBottom = 110; // leaves room for the source line
  const rowAreaH = CARD_H - padTop - padBottom;
  const rowH = rows.length > 0 ? rowAreaH / rows.length : rowAreaH;

  return (
    <AbsoluteFill
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      {/* Ken-burns wrapper around the paper panel. */}
      <div
        style={{
          width: CARD_W,
          height: CARD_H,
          transform: `${panel.transform} scale(${kb})`,
          transformOrigin: "center center",
          opacity: panel.opacity,
        }}
      >
        <div
          style={{
            position: "relative",
            width: "100%",
            height: "100%",
            background: PAPER,
            borderRadius: 6,
            boxShadow: "0 40px 90px rgba(0,0,0,0.45), 0 6px 18px rgba(0,0,0,0.25)",
            overflow: "hidden",
            fontFamily: SERIF,
          }}
        >
          {/* Faint full-bleed page lines behind everything. */}
          <svg
            viewBox={`0 0 ${CARD_W} ${CARD_H}`}
            width="100%"
            height="100%"
            style={{ position: "absolute", inset: 0, display: "block" }}
          >
            {Array.from({ length: 14 }, (_, i) => {
              const y = 70 + i * 42;
              if (y > CARD_H - 30) return null;
              return (
                <line
                  key={`pl${i}`}
                  x1={padX}
                  x2={CARD_W - padX}
                  y1={y}
                  y2={y}
                  stroke={RULE}
                  strokeWidth={1}
                  opacity={0.5}
                />
              );
            })}
            {/* Left margin rule (red, like notebook paper). */}
            <line
              x1={padX - 26}
              x2={padX - 26}
              y1={40}
              y2={CARD_H - 40}
              stroke="#E0B4B0"
              strokeWidth={2}
              opacity={0.55}
            />
          </svg>

          {/* Optional bold dark title. */}
          {title ? (
            <div
              style={{
                position: "absolute",
                left: padX,
                right: padX,
                top: 56,
                fontFamily: SERIF,
                fontWeight: 800,
                fontSize: 56,
                color: INK,
                letterSpacing: 0.5,
                opacity: titleA.opacity,
                transform: titleA.transform,
              }}
            >
              {title}
              {/* Underline beneath the title. */}
              <div
                style={{
                  marginTop: 14,
                  height: 3,
                  background: INK,
                  opacity: 0.85,
                  borderRadius: 2,
                }}
              />
            </div>
          ) : null}

          {/* Rows: ruled lines with left label + right bold value. */}
          {rows.map((r, i) => {
            const rowTop = padTop + i * rowH;
            const rowProg = stagger(frame, i, { delay: ROW_DELAY, step: ROW_STEP, dur: 10 });
            const isHi = highlightRow === i;
            return (
              <div
                key={`row${i}`}
                style={{
                  position: "absolute",
                  left: padX,
                  right: padX,
                  top: rowTop,
                  height: rowH,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  opacity: rowProg * fadeOut,
                  transform: `translateY(${(1 - rowProg) * 12}px)`,
                  borderBottom: `1px solid ${RULE}`,
                }}
              >
                {/* Yellow highlighter swipe behind the highlighted row. */}
                {isHi ? (
                  <div
                    style={{
                      position: "absolute",
                      left: -10,
                      top: "50%",
                      transform: "translateY(-50%)",
                      height: Math.min(64, rowH * 0.7),
                      width: `calc((100% + 20px) * ${wipe})`,
                      background: HIGHLIGHT,
                      opacity: 0.85,
                      borderRadius: 4,
                      zIndex: 0,
                    }}
                  />
                ) : null}

                <span
                  style={{
                    position: "relative",
                    zIndex: 1,
                    fontFamily: SERIF,
                    fontWeight: 500,
                    fontSize: 38,
                    color: INK,
                  }}
                >
                  {r.label}
                </span>
                <span
                  style={{
                    position: "relative",
                    zIndex: 1,
                    fontFamily: SERIF,
                    fontWeight: 800,
                    fontSize: 38,
                    color: INK,
                    textAlign: "right",
                    marginLeft: 40,
                  }}
                >
                  {r.value}
                </span>
              </div>
            );
          })}

          {/* Small italic grey source line, bottom-right. */}
          {source ? (
            <div
              style={{
                position: "absolute",
                right: padX,
                bottom: 36,
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
