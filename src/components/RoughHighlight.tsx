import React, { useEffect, useRef } from "react";
import rough from "roughjs";

interface Props {
  /** X position within the image coordinate space (image px) */
  imgX: number;
  /** Y position within the image coordinate space (image px) */
  imgY: number;
  /** Width in image px */
  imgW: number;
  /** Height in image px */
  imgH: number;
  /** Scale factor: image px → rendered px */
  scale: number;
  /** Left offset of the image on the canvas (rendered px) */
  imgLeft: number;
  /** Top offset of the image on the canvas (rendered px) */
  imgTop: number;
  /**
   * Progress of the reveal animation: 0 = hidden, 1 = fully revealed.
   * The highlight grows from left to right.
   */
  progress: number;
  /** Highlight fill colour (semi-transparent yellow by default) */
  color?: string;
  /** Rough.js seed for deterministic paths across frames */
  seed?: number;
}

/**
 * Draws a rough.js rectangle highlight on an SVG that fills the whole canvas.
 * The rectangle is clipped to reveal progressively from left to right.
 * Place this component BELOW the article image so the highlight sits behind text.
 */
export const RoughHighlight: React.FC<Props> = ({
  imgX,
  imgY,
  imgW,
  imgH,
  scale,
  imgLeft,
  imgTop,
  progress,
  color = "rgba(255, 220, 30, 0.55)",
  seed = 42,
}) => {
  const svgRef = useRef<SVGSVGElement>(null);

  // Rendered rect coords on the full canvas
  const rx = imgLeft + imgX * scale;
  const ry = imgTop + imgY * scale;
  const rw = imgW * scale;
  const rh = imgH * scale;

  // Extra vertical padding so the marker looks generous around the text
  const pad = rh * 0.45;

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;

    // Clear any previously drawn nodes
    while (svg.lastChild) svg.removeChild(svg.lastChild);

    const rc = rough.svg(svg);
    const node = rc.rectangle(rx, ry - pad, rw, rh + pad * 2, {
      seed,
      fill: color,
      fillStyle: "solid",
      roughness: 2.2,
      stroke: color.replace(/[\d.]+\)$/, "0.7)"),
      strokeWidth: 1.2,
      bowing: 1.5,
    });
    svg.appendChild(node);
  }, [rx, ry, rw, rh, pad, color, seed]);

  if (progress <= 0) return null;

  // Clip the SVG from the right so the highlight grows left→right
  const clipRight = `${Math.max(0, (1 - progress) * 100).toFixed(2)}%`;

  return (
    <svg
      ref={svgRef}
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
        overflow: "visible",
        clipPath: `inset(0 ${clipRight} 0 0)`,
        pointerEvents: "none",
      }}
    />
  );
};
