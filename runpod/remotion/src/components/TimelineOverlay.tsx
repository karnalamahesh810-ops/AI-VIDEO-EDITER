import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import {
  PANEL_BG, PANEL_SHADOW, SANS, growth,
  useOverlayAnim, useOverlaySafeStyle, useScale,
} from "./layout";
import type { Overlay } from "../types";

/**
 * Event timeline: a rule that draws itself left to right, with each node
 * popping in as the line reaches it.
 *
 * Nodes alternate above and below the rule so long labels have room without
 * colliding with their neighbours — at four or more events, same-side labels
 * overlap at any readable font size.
 */
export const TimelineOverlay: React.FC<{ overlay: Overlay; accent: string }> = ({
  overlay,
  accent,
}) => {
  const { frame, opacity, durationInFrames } = useOverlayAnim(18, 12);
  const s = useScale();
  const safe = useOverlaySafeStyle();

  const items = (overlay.items || []).slice(0, 6);
  if (items.length < 2) return null;

  const drawFrames = Math.floor(durationInFrames * 0.55);
  const lineProgress = growth(frame, drawFrames);

  return (
    <AbsoluteFill
      style={{ ...safe, justifyContent: "center", alignItems: "center", opacity }}
    >
      <div
        style={{
          background: PANEL_BG,
          borderRadius: s(20),
          padding: `${s(44)}px ${s(60)}px`,
          width: "76%",
          boxShadow: PANEL_SHADOW,
          backdropFilter: "blur(10px)",
        }}
      >
        {overlay.text ? (
          <div
            style={{
              fontFamily: SANS,
              fontSize: s(38),
              fontWeight: 800,
              color: "#fff",
              textAlign: "center",
              marginBottom: s(40),
            }}
          >
            {overlay.text}
          </div>
        ) : null}

        {/* Inset the track so the first and last labels, which are centred on
            their nodes, stay inside the panel instead of hanging off it. */}
        <div style={{ position: "relative", height: s(230), margin: `0 ${s(120)}px` }}>
          {/* The rule, drawn left to right */}
          <div
            style={{
              position: "absolute",
              top: "50%",
              left: 0,
              height: s(4),
              width: `${lineProgress * 100}%`,
              background: accent,
              boxShadow: `0 0 ${s(18)}px ${accent}`,
            }}
          />
          <div
            style={{
              position: "absolute",
              top: "50%",
              left: 0,
              height: s(4),
              width: "100%",
              background: "rgba(255,255,255,0.12)",
              zIndex: -1,
            }}
          />

          {items.map((item, i) => {
            const at = items.length === 1 ? 0.5 : i / (items.length - 1);
            // Each node wakes up as the line arrives at its position.
            const pop = growth(frame - at * drawFrames, 10);
            const above = i % 2 === 0;
            return (
              <div
                key={i}
                style={{
                  position: "absolute",
                  left: `${at * 100}%`,
                  top: "50%",
                  transform: "translate(-50%, -50%)",
                  opacity: pop,
                }}
              >
                <div
                  style={{
                    width: s(22),
                    height: s(22),
                    borderRadius: "50%",
                    background: accent,
                    border: `${s(4)}px solid #0a0a0c`,
                    transform: `scale(${interpolate(pop, [0, 1], [0.2, 1])})`,
                  }}
                />
                <div
                  style={{
                    position: "absolute",
                    left: "50%",
                    [above ? "bottom" : "top"]: s(26),
                    transform: "translateX(-50%)",
                    width: s(230),
                    textAlign: "center",
                  }}
                >
                  <div
                    style={{
                      fontFamily: SANS,
                      fontSize: s(30),
                      fontWeight: 900,
                      color: accent,
                      letterSpacing: "-0.01em",
                    }}
                  >
                    {item.label}
                  </div>
                  {item.text ? (
                    <div
                      style={{
                        fontFamily: SANS,
                        fontSize: s(23),
                        fontWeight: 500,
                        lineHeight: 1.25,
                        color: "rgba(255,255,255,0.8)",
                        marginTop: s(4),
                      }}
                    >
                      {item.text}
                    </div>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};
