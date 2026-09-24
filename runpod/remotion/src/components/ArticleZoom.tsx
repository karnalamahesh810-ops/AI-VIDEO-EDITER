import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import { useOverlayAnim, useScale } from "./layout";
import type { Overlay } from "../types";

/**
 * "Article Zoom Animation" — VidRush's document card.
 *
 * A paper page on a grey field: a small kicker ("ARCHIVAL REVIEW"), a
 * typewriter headline with its key phrase in red, and body text that types
 * in, while the whole card pushes in slowly. Used when the narration cites a
 * record, report, file, letter or article.
 *
 * Nothing is invented: the headline is the overlay text, the kicker is its
 * subtitle, and the body is `overlay.body` when the plan supplied one. With
 * no body the page shows faint ruled lines — what a document reads as from a
 * distance — rather than made-up prose.
 */
const TYPE = "'Liberation Mono', 'Courier New', 'DejaVu Sans Mono', monospace";

function splitHighlight(text: string, highlight: string): [string, string, string] {
  const h = (highlight || "").trim();
  if (!h) return [text, "", ""];
  const at = text.toLowerCase().indexOf(h.toLowerCase());
  if (at < 0) return [text, "", ""];
  return [text.slice(0, at), text.slice(at, at + h.length), text.slice(at + h.length)];
}

export const ArticleZoom: React.FC<{ overlay: Overlay; accent: string }> = ({
  overlay,
  accent,
}) => {
  const { frame, enter, opacity, durationInFrames } = useOverlayAnim(14, 10);
  const s = useScale();
  const red = accent || "#d62828";

  const headline = overlay.text || "";
  const typeEnd = Math.max(1, Math.floor(durationInFrames * 0.35));
  const shown = Math.floor(
    interpolate(frame, [0, typeEnd], [0, headline.length], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    }),
  );
  const [pre, hot, post] = splitHighlight(headline.slice(0, shown), overlay.highlight || "");

  const body = overlay.body || "";
  const bodyShown = Math.floor(
    interpolate(frame, [typeEnd, durationInFrames * 0.8], [0, body.length], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    }),
  );
  const bodyLines = interpolate(frame, [typeEnd, durationInFrames * 0.8], [0, 14], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // The "zoom": a slow push across the whole overlay, on top of the entrance.
  const push = interpolate(frame, [0, durationInFrames], [1, 1.09]);

  return (
    <AbsoluteFill
      style={{
        opacity,
        background: "radial-gradient(ellipse at center, #cfccc6 0%, #a9a6a0 100%)",
        justifyContent: "center",
        alignItems: "center",
      }}
    >
      <div
        style={{
          width: "50%",
          height: "88%",
          background: "#f1eee8",
          boxShadow: "0 24px 70px rgba(0,0,0,0.35)",
          padding: `${s(46)}px ${s(56)}px`,
          transform: `translateY(${(1 - enter) * s(40)}px) scale(${push})`,
          overflow: "hidden",
          boxSizing: "border-box",
        }}
      >
        {overlay.subtitle ? (
          <div
            style={{
              fontFamily: TYPE,
              fontSize: s(20),
              letterSpacing: "0.16em",
              textTransform: "uppercase",
              color: "#6b6760",
              marginBottom: s(14),
            }}
          >
            {overlay.subtitle}
          </div>
        ) : null}
        <div
          style={{
            fontFamily: TYPE,
            fontWeight: 700,
            fontSize: s(58),
            lineHeight: 1.15,
            color: "#1d1c1a",
            minHeight: s(100),
          }}
        >
          {pre}
          {hot ? (
            <span style={{ background: red, color: "#fff", padding: "0 0.12em" }}>{hot}</span>
          ) : null}
          {post}
        </div>
        <div style={{ height: 1, background: "#c9c4bb", margin: `${s(22)}px 0` }} />
        {body ? (
          <div
            style={{
              fontFamily: TYPE,
              fontSize: s(24),
              lineHeight: 1.55,
              color: "#2b2926",
              whiteSpace: "pre-wrap",
              marginBottom: s(22),
            }}
          >
            {body.slice(0, bodyShown)}
          </div>
        ) : null}
        {/* The rest of the page reads as text from a distance: ruled lines,
            never invented prose. */}
        {Array.from({ length: Math.floor(bodyLines) }).map((_, i) => (
          <div
            key={i}
            style={{
              height: s(11),
              width: `${i % 5 === 4 ? 58 : 92 - (i % 3) * 6}%`,
              background: "#d6d1c8",
              marginBottom: s(15),
            }}
          />
        ))}
      </div>
    </AbsoluteFill>
  );
};
