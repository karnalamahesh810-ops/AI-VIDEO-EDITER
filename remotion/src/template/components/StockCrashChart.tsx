import React from "react";
import { AbsoluteFill, useCurrentFrame, interpolate, Easing } from "remotion";
import { Theme } from "../theme";
import { fadeRise, drawOn, stagger } from "../anim";

const W = 1920;
const H = 1080;

// Stock-crash graphic. Dark navy financial grid (#0b1a2e) with faint grid lines,
// ~12 small candlesticks (alternating green up / red down) along the bottom-mid,
// a yellow (#F2E84B) jagged price line crossing them with right-axis tick labels,
// glowing blue volume bars along the very bottom, and a big 3D-style RED downward
// arrow that sweeps in from top-left to its landing position to convey a crash.
// Renders full-bg (props.fullBg) over the navy field, or transparent over b-roll.
export const StockCrashChart: React.FC<{
  title?: string;
  fullBg?: boolean;
  theme: Theme;
  durationInFrames: number;
}> = ({ title, fullBg = false, theme, durationInFrames }) => {
  const frame = useCurrentFrame();
  const outAt = durationInFrames - 12;

  const NAVY = "#0b1a2e";
  const YELLOW = "#F2E84B";
  const GREEN = theme.chartA || "#25c281";
  const RED = theme.alert || "#E8202B";

  // Plot geometry inside the 1920x1080 design.
  const padL = 120;
  const padR = 150; // room for right-axis tick labels
  const padT = 150;
  const padB = 150; // room for volume bars
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const x0 = padL;
  const yTop = padT;
  const y0 = H - padB; // baseline (bottom of price plot)

  // Overall fade for the chart furniture (grid, axes, candles, line).
  const axisA = fadeRise(frame, { delay: 0, dur: 12, dist: 0, outAt, outDur: 10 });
  const fadeOut = interpolate(frame, [outAt, outAt + 12], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // --- Candlesticks (deterministic walk, generally trending down). ---
  const N_CANDLES = 12;
  const slot = plotW / N_CANDLES;
  const candleW = slot * 0.42;
  const candles = React.useMemo(() => {
    const out: { up: boolean; openV: number; closeV: number; hiV: number; loV: number }[] = [];
    let price = 0.82; // start high (fraction of plot, 0 = bottom, 1 = top)
    for (let i = 0; i < N_CANDLES; i++) {
      // Pseudo-random but stable per index; net downward drift.
      const wig = Math.sin(i * 1.7) * 0.05 + Math.cos(i * 0.9) * 0.03;
      const drift = -0.052;
      const openV = price;
      const closeV = Math.max(0.06, Math.min(0.94, price + drift + wig));
      const up = closeV >= openV;
      const bodyHi = Math.max(openV, closeV);
      const bodyLo = Math.min(openV, closeV);
      const hiV = Math.min(0.98, bodyHi + 0.03 + Math.abs(wig) * 0.5);
      const loV = Math.max(0.02, bodyLo - 0.03 - Math.abs(wig) * 0.5);
      out.push({ up, openV, closeV, hiV, loV });
      price = closeV;
    }
    return out;
  }, []);

  const vy = (f: number) => y0 - f * plotH; // fraction (0..1) -> y

  // Yellow jagged price line follows the candle closes (in screen coords).
  const linePts = candles.map((c, i) => ({
    x: x0 + slot * i + slot / 2,
    y: vy(c.closeV),
  }));
  const linePath = linePts.length
    ? "M " + linePts.map((p) => `${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" L ")
    : "";
  // Generous dash length so the left->right reveal fully hides the polyline.
  const lineLen = (plotW + plotH) * 2.2;
  const lineDraw = drawOn(frame, { delay: 10, dur: 70 });

  // Right-axis tick labels (5), high->low to match the decline.
  const ticks = [100, 80, 60, 40, 20];
  const tickYs = ticks.map((_, i) => yTop + (i / (ticks.length - 1)) * plotH);

  // Faint grid.
  const gridYs = Array.from({ length: 6 }, (_, i) => yTop + (i / 5) * plotH);
  const gridXs = Array.from({ length: N_CANDLES + 1 }, (_, i) => x0 + (i / N_CANDLES) * plotW);

  // --- Volume bars along the very bottom (glowing blue). ---
  const volTop = H - padB + 36;
  const volMaxH = padB - 56;
  const volBaseline = H - 20;
  const N_VOL = N_CANDLES;
  const volSlot = plotW / N_VOL;
  const volW = volSlot * 0.5;

  // --- Big 3D red downward arrow sweeping top-left -> bottom-right. ---
  // Arrow drawn pointing down-right around a local origin, then translated/scaled in.
  const arrowDraw = interpolate(frame, [8, 40], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  // Landing offset: start up-left and small, settle at full size in place.
  const arrowDX = interpolate(arrowDraw, [0, 1], [-520, 0]);
  const arrowDY = interpolate(arrowDraw, [0, 1], [-360, 0]);
  const arrowScale = interpolate(arrowDraw, [0, 1], [0.55, 1]);
  const arrowOpacity = interpolate(frame, [8, 22], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  }) * fadeOut;

  // Tapered arrow polygon (thick shaft, big head) oriented down-right ~38deg.
  // Local-space points (before the sweep transform). Head at bottom-right.
  const ax1 = 560; // shaft start x (top-left of arrow)
  const ay1 = 300; // shaft start y
  const arrowPoly = [
    [ax1 - 70, ay1 - 30], // shaft top edge start
    [ax1 + 720, ay1 + 470], // shaft top edge near head
    [ax1 + 690, ay1 + 360], // head upper barb inner
    [ax1 + 900, ay1 + 560], // head outer upper
    [ax1 + 760, ay1 + 800], // arrow tip (point)
    [ax1 + 560, ay1 + 590], // head outer lower
    [ax1 + 600, ay1 + 700], // head lower barb inner
    [ax1 - 30, ay1 + 250], // shaft bottom edge near head
    [ax1 - 130, ay1 + 30], // shaft bottom edge start
  ]
    .map((p) => p.join(","))
    .join(" ");

  return (
    <AbsoluteFill style={{ ...(fullBg ? { background: NAVY } : {}) }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height="100%"
        style={{ display: "block", overflow: "visible" }}
      >
        <defs>
          {/* 3D-ish red gradient + drop shadow for the crash arrow. */}
          <linearGradient id="scc-arrow" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#FF5A4D" />
            <stop offset="45%" stopColor={RED} />
            <stop offset="100%" stopColor="#9E0A12" />
          </linearGradient>
          <filter id="scc-arrow-shadow" x="-40%" y="-40%" width="180%" height="180%">
            <feDropShadow dx="14" dy="18" stdDeviation="14" floodColor="#000000" floodOpacity="0.55" />
          </filter>
          {/* Glow for volume bars. */}
          <filter id="scc-vol-glow" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="6" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Navy field (only when not full-bg, so panel reads over b-roll). */}
        {!fullBg && (
          <rect x={0} y={0} width={W} height={H} fill={NAVY} opacity={0.92 * axisA.opacity} />
        )}

        {/* Faint grid lines. */}
        {gridYs.map((gy, i) => (
          <line
            key={`gy${i}`}
            x1={x0}
            x2={x0 + plotW}
            y1={gy}
            y2={gy}
            stroke="#FFFFFF"
            strokeWidth={1}
            opacity={0.07 * axisA.opacity}
          />
        ))}
        {gridXs.map((gx, i) => (
          <line
            key={`gx${i}`}
            x1={gx}
            x2={gx}
            y1={yTop}
            y2={y0}
            stroke="#FFFFFF"
            strokeWidth={1}
            opacity={0.05 * axisA.opacity}
          />
        ))}

        {/* Volume bars along the very bottom (glowing blue). */}
        <g style={{ filter: "url(#scc-vol-glow)" }}>
          {Array.from({ length: N_VOL }, (_, i) => {
            const cx = x0 + volSlot * i + volSlot / 2;
            const frac = 0.35 + Math.abs(Math.sin(i * 1.3)) * 0.6; // 0.35..0.95
            const targetH = frac * volMaxH;
            const grow = stagger(frame, i, { delay: 14, step: 2, dur: 10 });
            const h = targetH * grow;
            return (
              <rect
                key={`v${i}`}
                x={cx - volW / 2}
                y={volBaseline - h}
                width={volW}
                height={Math.max(0, h)}
                rx={3}
                fill={theme.accent || "#3B7DF0"}
                opacity={0.32 * axisA.opacity}
              />
            );
          })}
        </g>

        {/* Candlesticks (wick + body), staggered grow from baseline. */}
        {candles.map((c, i) => {
          const cx = x0 + slot * i + slot / 2;
          const grow = stagger(frame, i, { delay: 6, step: 3, dur: 10 });
          const yHi = vy(c.hiV);
          const yLo = vy(c.loV);
          const yOpen = vy(c.openV);
          const yClose = vy(c.closeV);
          const bodyTop = Math.min(yOpen, yClose);
          const bodyBot = Math.max(yOpen, yClose);
          const bodyH = Math.max(4, bodyBot - bodyTop);
          const col = c.up ? GREEN : RED;
          // Animate by scaling height from the baseline-ish anchor (use grow as opacity+scaleY).
          return (
            <g
              key={`c${i}`}
              style={{
                opacity: grow * axisA.opacity,
                transform: `scaleY(${0.6 + grow * 0.4})`,
                transformBox: "fill-box",
                transformOrigin: "center bottom",
              }}
            >
              {/* Wick */}
              <line x1={cx} x2={cx} y1={yHi} y2={yLo} stroke={col} strokeWidth={3} />
              {/* Body */}
              <rect x={cx - candleW / 2} y={bodyTop} width={candleW} height={bodyH} rx={2} fill={col} />
            </g>
          );
        })}

        {/* Yellow jagged price line crossing the candles, draws on L->R. */}
        <path
          d={linePath}
          fill="none"
          stroke={YELLOW}
          strokeWidth={5}
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeDasharray={lineLen}
          strokeDashoffset={lineLen * (1 - lineDraw)}
          opacity={fadeOut}
          style={{ filter: "drop-shadow(0 0 8px rgba(242,232,75,0.45))" }}
        />

        {/* Right-axis tick labels. */}
        {tickYs.map((ty, i) => (
          <text
            key={`t${i}`}
            x={x0 + plotW + 24}
            y={ty}
            fill={theme.textMute}
            fontFamily={theme.bodyFont}
            fontSize={26}
            fontWeight={600}
            textAnchor="start"
            dominantBaseline="central"
            opacity={axisA.opacity}
          >
            {ticks[i]}
          </text>
        ))}

        {/* Big 3D red downward crash arrow, sweeps in top-left -> bottom-right. */}
        <g
          style={{
            opacity: arrowOpacity,
            transform: `translate(${arrowDX}px, ${arrowDY}px) scale(${arrowScale})`,
            transformBox: "view-box",
            transformOrigin: "center center",
            filter: "url(#scc-arrow-shadow)",
          }}
        >
          <polygon points={arrowPoly} fill="url(#scc-arrow)" stroke="#5C0610" strokeWidth={3} strokeLinejoin="round" />
          {/* Subtle top highlight edge for the 3D feel. */}
          <polygon
            points={arrowPoly}
            fill="none"
            stroke="#FFFFFF"
            strokeWidth={2}
            strokeLinejoin="round"
            opacity={0.18}
          />
        </g>

        {/* Optional title, top-center. */}
        {title ? (
          <text
            x={W / 2}
            y={84}
            fill={theme.text}
            fontFamily={theme.headerFont}
            fontSize={56}
            fontWeight={800}
            textAnchor="middle"
            opacity={axisA.opacity}
            style={{ letterSpacing: 1 }}
          >
            {title}
          </text>
        ) : null}
      </svg>
    </AbsoluteFill>
  );
};
