import React from "react";
import { AbsoluteFill } from "remotion";
import type { Overlay } from "../../types";
import { useLookSound } from "./LookSounds";
import type { SoundCue } from "./lookSoundPlan";
import {
  ANTON, SUBLINE, Grain, Pool, Stage, backOut, caps, clamp01, easeInOut, easeOut, exitOf, expoOut, fit, guard, heavy,
  hotOf, inOf, lerp, lift, mixHex, rgba, sineInOut, textWidth, useBase, useSvgId, type CSS, type Look,
} from "./proKit";
import {
  type Figure, type Row, clip, countText, digits, figureOf, figureText, fmtNumber, niceScale, num, percentChange,
  ratioText, rowsOf, seriesScale, str, unitsOf,
} from "./proFormat";

/**
 * DATA PRO (family "dx-"): eight data looks built to read like a top
 * documentary's graphics department (Bloomberg / Reuters / Vox charts, the
 * Netflix "number moment"), every one of them a device the library did not
 * have:
 *
 *   dx-line-endpoint      a line chart that DRAWS with the camera following its head, then pulls back;
 *                         the last point lands with its value and year called out (series)
 *   dx-ghost-bars         then vs now: the earlier bar stays as a dashed ghost under the later one, the
 *                         gap between them hatched and labelled with the change (then-now, two values)
 *   dx-nested-squares     two or three quantities as area-true squares from one corner, the ratio
 *                         between them (compare-values, then-now, money-compare)
 *   dx-unit-split         a hundred units (people when the line counts people) fill to the share, then the
 *                         share separates from the rest; "1 in 4" as four large units (percent, ratio)
 *   dx-filled-figure      the percentage as a giant outlined figure filled with water to its level
 *                         (percent of a reservoir, a lake, a capacity)
 *   dx-capacity-gauge     a fuel gauge from E to F, the needle swinging to the share (capacity, level)
 *   dx-drum-counter       a mechanical drum counter: the digits roll on lit drums and land left to right
 *                         (a big number, a count, money, a measurement)
 *   dx-reservoir-section  a canyon reservoir in cross-section: the water falls (or rises) to the level
 *                         said, a pale bathtub ring left on the walls, an elevation ruler with the level
 *                         called out, full pool and thresholds dashed when they were said
 *
 * Only the narration's own numbers are drawn (a change or a ratio is worked
 * out from two figures it said). Numbers count and land on a tick - a number
 * never whooshes or punches (useLookSound, scheduled on the real frames).
 * Sizes are 1080p-referenced; every look leaves in its last 12 frames.
 */

// ------------------------------------------------------------------ shared
const WHITE = "#FFFFFF";
const SOFT = "rgba(255,255,255,.62)";
const FAINT = "rgba(255,255,255,.38)";
const GRID = "rgba(255,255,255,.10)";
const INK = "#0b0d11";

/** The title block every full-screen data look shares: kicker (label) over the title (text), top-left. */
const Title: React.FC<{ ov: Overlay; accent: string; at?: number; out: number }> = ({ ov, accent, at = 4, out }) => {
  const { f, S, k, kw, width } = useBase();
  const title = clip(digits(str(ov.text)), 64, true).toUpperCase();
  const kicker = clip(digits(str(ov.label)), 40).toUpperCase();
  if (!title && !kicker) return null;
  const t = fit(title, { font: ANTON, tracking: 0.01 }, Math.min(1180 * kw, width - 240 * kw), 60 * k, 40 * k, 1);
  const p1 = inOf(f, at * S, 14 * S);
  const p2 = inOf(f, (at + 4) * S, 14 * S);
  return (
    <div style={{ position: "absolute", left: 120 * kw, top: 92 * kw, opacity: 1 - out,
      transform: `translateY(${(-out * 14 * k).toFixed(1)}px)` }}>
      {kicker ? (
        <div style={{ ...caps(22 * k, hotOf(accent), 0.2), opacity: p1, transform: `translateY(${((1 - p1) * 10 * k).toFixed(1)}px)`,
          marginBottom: 14 * k }}>{kicker}</div>
      ) : null}
      {t.lines.map((ln, i) => (
        <div key={i} style={{ overflow: "hidden", paddingBottom: 4 * k }}>
          <div style={{ ...heavy(t.size, WHITE, 0.01), transform: `translateY(${((1 - p2) * 110).toFixed(1)}%)` }}>{ln}</div>
        </div>
      ))}
    </div>
  );
};

/** The source line, bottom-left (subtitle), only when the plan gave one. */
const Source: React.FC<{ text: string; at: number; out: number }> = ({ text, at, out }) => {
  const { f, S, k, kw, height } = useBase();
  const s = clip(digits(str(text)), 70, true);
  if (!s) return null;
  const p = inOf(f, at * S, 14 * S);
  return (
    <div style={{ position: "absolute", left: 120 * kw, top: height - 112 * kw, ...caps(19 * k, FAINT, 0.16),
      opacity: p * (1 - out) }}>{s}</div>
  );
};

/** A figure drawn as Anton digits with its glued unit and its unit word smaller. */
const FigureText: React.FC<{ fig: Figure; text: string; size: number; color?: string; unitColor?: string; style?: CSS }> =
  ({ fig, text, size, color = WHITE, unitColor, style }) => (
    <span style={{ ...heavy(size, color), display: "inline-flex", alignItems: "baseline", ...style }}>
      {fig.prefix ? <span style={{ fontSize: size * 0.72, marginRight: size * 0.02 }}>{fig.prefix}</span> : null}
      <span>{text}</span>
      {fig.glued ? <span style={{ fontSize: fig.glued === "%" ? size * 0.7 : size * 0.78, color: unitColor || color,
        marginLeft: size * 0.02 }}>{fig.glued}</span> : null}
      {fig.unit ? <span style={{ fontSize: size * 0.46, color: unitColor || color, marginLeft: size * 0.12,
        letterSpacing: "0.04em" }}>{fig.unit}</span> : null}
    </span>
  );

/** The width of a figure drawn by FigureText at `size` (for layout). */
const figureWidth = (fig: Figure, text: string, size: number): number => {
  let w = textWidth(text, ANTON, size, 400, 0.01);
  if (fig.prefix) w += textWidth(fig.prefix, ANTON, size * 0.72) + size * 0.02;
  if (fig.glued) w += textWidth(fig.glued, ANTON, fig.glued === "%" ? size * 0.7 : size * 0.78) + size * 0.02;
  if (fig.unit) w += textWidth(fig.unit, ANTON, size * 0.46, 400, 0.04) + size * 0.12;
  return w;
};

/** A run of soft ticks for a count from `a` to `b` (30 fps frames) and one clean click as it lands. */
const countCues = (a: number, b: number, gain = -11): SoundCue[] => (b - a >= 6
  ? [{ name: "count-roll", alt: ["count-tick", "ui-tick"], at: a, align: "start", until: b - 1, gain_db: gain },
    { name: "count-final", alt: ["ui-tick", "tick"], at: b, gain_db: -5 }]
  : [{ name: "count-final", alt: ["ui-tick", "tick"], at: b, gain_db: -5 }]);

// ================================================================== dx-line-endpoint
const LINE = { drawAt: 14, drawFrames: 36, land: 50 };

/** The points of a series (at most 12, in order) and its unit, or null when fewer than two values. */
export const linePlan = (ov: Overlay) => {
  const rows = rowsOf(ov.items, 12);
  if (rows.length < 2) return null;
  const u = unitsOf(rows, ov.suffix, ov.prefix);
  // Years as labels, rising: the x axis is time to scale (1965 -> 1980 is wider than 2022 -> 2026).
  const years = rows.map((r) => (/^\d{4}$/.test(r.label) ? Number(r.label) : NaN));
  const timed = years.every((y, i) => Number.isFinite(y) && (i === 0 || y > years[i - 1]));
  const xs = timed ? years.map((y) => (y - years[0]) / (years[years.length - 1] - years[0] || 1))
    : rows.map((_, i) => i / (rows.length - 1));
  return { rows, xs, suffix: u.suffix, prefix: u.prefix };
};

/** A monotone cubic through the points (no overshoot, no fake plateaus): y at any x between them. */
const monotone = (xs: number[], ys: number[]) => {
  const n = xs.length;
  const d: number[] = [];
  for (let i = 0; i < n - 1; i++) d.push((ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i] || 1e-9));
  const m: number[] = new Array<number>(n).fill(0);
  m[0] = d[0] ?? 0;
  m[n - 1] = d[n - 2] ?? 0;
  for (let i = 1; i < n - 1; i++) m[i] = d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2;
  for (let i = 0; i < n - 1; i++) {
    if (d[i] === 0) {
      m[i] = 0;
      m[i + 1] = 0;
      continue;
    }
    const a = m[i] / d[i];
    const b = m[i + 1] / d[i];
    const s = a * a + b * b;
    if (s > 9) {
      const t = 3 / Math.sqrt(s);
      m[i] = t * a * d[i];
      m[i + 1] = t * b * d[i];
    }
  }
  return (x: number) => {
    let i = 0;
    while (i < n - 2 && x > xs[i + 1]) i++;
    const h = xs[i + 1] - xs[i] || 1e-9;
    const t = Math.max(0, Math.min(1, (x - xs[i]) / h));
    const t2 = t * t;
    const t3 = t2 * t;
    return (2 * t3 - 3 * t2 + 1) * ys[i] + (t3 - 2 * t2 + t) * h * m[i] + (-2 * t3 + 3 * t2) * ys[i + 1]
      + (t3 - t2) * h * m[i + 1];
  };
};

const LineEndpoint: Look = ({ overlay, accent }) => {
  const { f, S, k, kw, width, height, dur } = useBase();
  const id = useSvgId("dxl");
  const plan = linePlan(overlay);
  const hot = hotOf(accent);
  const out = exitOf(f, dur, S);
  const stageP = inOf(f, 0, 10 * S);
  const pts = plan ? plan.rows : [];
  const n = pts.length;

  // Plot box (1080p): the right side kept for the end label.
  const x0 = 250 * kw;
  const x1 = Math.min(1460 * kw, width - 360 * kw);
  const y0 = 330 * kw;
  const y1 = Math.min(840 * kw, height - 220 * kw);
  const vals = pts.map((p) => p.value);
  const sc = n ? seriesScale(vals, 4) : niceScale(0, 1);
  const X = (u: number) => x0 + (x1 - x0) * u;
  const Y = (v: number) => y1 - ((v - sc.min) / (sc.max - sc.min || 1)) * (y1 - y0);
  const ux = plan ? plan.xs : [];
  const P = pts.map((p, i) => [X(ux[i]), Y(p.value)] as [number, number]);
  const curve = n >= 2 ? monotone(P.map((p) => p[0]), P.map((p) => p[1])) : () => y1;

  // The draw runs along x (time), the head on the curve; reveal by x keeps the pace of the years.
  const draw = easeInOut(clamp01((f - LINE.drawAt * S) / (LINE.drawFrames * S)));
  const hx = n ? lerp(P[0][0], P[n - 1][0], draw) : x0;
  const head: [number, number] = [hx, curve(hx)];
  const steps = Math.max(2, Math.round(160 * draw));
  const shown: [number, number][] = [];
  for (let s = 0; s <= steps; s++) {
    const x = lerp(P[0]?.[0] ?? x0, hx, s / steps);
    shown.push([x, curve(x)]);
  }
  const d = shown.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const area = draw > 0 ? `${d} L${hx.toFixed(1)} ${y1.toFixed(1)} L${(P[0]?.[0] ?? x0).toFixed(1)} ${y1.toFixed(1)} Z` : "";

  // The camera starts close on the beginning, follows the head, then pulls back to the whole chart.
  const zIn = 1 - inOf(f, (LINE.land - 10) * S, 24 * S, easeInOut);
  const zoom = 1 + 0.28 * zIn;
  const hold = 1 + 0.014 * clamp01((f - LINE.land * S) / Math.max(1, dur - LINE.land * S));
  const half = (width / 2 - 110 * kw) / zoom;
  const camLo = x0 - 120 * kw + half;
  const camHi = x1 + 320 * kw - half;
  const follow = Math.max(camLo, Math.min(camHi, head[0]));
  const camX = lerp(width / 2, follow, zIn);
  const camY = lerp(height / 2, (y0 + y1) / 2 + (head[1] - (y0 + y1) / 2) * 0.3 + 30 * kw, zIn);
  const camera = `translate(${width / 2}px, ${height / 2}px) scale(${(zoom * hold).toFixed(4)}) translate(${-camX}px, ${-camY}px)`;

  // The frame the head passes each point (its dot pops, a soft tick).
  const passAt = P.map(([x]) => {
    const target = n > 1 ? (x - P[0][0]) / (P[n - 1][0] - P[0][0] || 1) : 0;
    for (let q = 0; q <= LINE.drawFrames; q++) if (easeInOut(q / LINE.drawFrames) >= target - 1e-6) return LINE.drawAt + q;
    return LINE.land;
  });
  const fig = n ? figureOf(pts[n - 1].value, plan?.suffix, plan?.prefix) : null;
  const startFig = n ? figureOf(pts[0].value, plan?.suffix, plan?.prefix) : null;
  const landP = inOf(f, LINE.land * S, 14 * S);
  const pulse = clamp01((f - LINE.land * S) / (24 * S));

  // X labels: first, last and evenly between, never crowding (at least 150 px apart at 1080p).
  const xLabels: number[] = [];
  pts.forEach((_, i) => {
    const far = (j: number) => Math.abs(P[i][0] - P[j][0]) >= 150 * kw;
    if (i === 0 || i === n - 1) return;
    if (xLabels.every(far) && far(0) && far(n - 1)) xLabels.push(i);
  });
  const labelled = n ? [0, ...xLabels, n - 1] : [];

  // The end label: right of the last point, or left of it when there is no room.
  const endSize = 66 * k;
  const endText = fig ? countText(fig, 1) : "";
  const endW = fig ? figureWidth(fig, endText, endSize) : 0;
  const [ex, ey] = P[n - 1] || [x1, y0];
  const right = ex + 34 * k + endW < width - 96 * kw;
  // The first value: beside its point, on the side the line leaves free.
  const startBelow = n > 1 && pts[1].value >= pts[0].value;
  const cues: SoundCue[] = passAt.slice(1, -1).filter((_, i) => i < 6).map((at) => ({ name: "ui-tick", alt: ["tick"], at,
    gain_db: -10 }));
  cues.push({ name: "count-final", alt: ["ui-tick", "tick"], at: LINE.land, gain_db: -4 });
  const sound = useLookSound(plan ? cues : []);
  if (!plan) return null;
  const decimals = sc.step < 1 ? Math.min(2, Math.max(0, -Math.floor(Math.log10(sc.step)))) : 0;
  const tickLabel = (v: number) => {
    const fv = figureOf(v, plan.suffix, plan.prefix);
    return `${fv.prefix}${fmtNumber(v, decimals, plan.suffix || plan.prefix ? true : undefined)}${fv.glued}`;
  };
  const yLabelSize = 26 * k;

  return (
    <AbsoluteFill>
      {sound}
      <Stage ov={overlay} p={stageP * (1 - out)} />
      <AbsoluteFill style={{ transform: camera, transformOrigin: "0 0", opacity: 1 - out }}>
        <svg width={width} height={height} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          <defs>
            <linearGradient id={`${id}a`} x1="0" y1={y0} x2="0" y2={y1} gradientUnits="userSpaceOnUse">
              <stop offset="0" stopColor={hot} stopOpacity={0.24} />
              <stop offset="1" stopColor={hot} stopOpacity={0} />
            </linearGradient>
            <filter id={`${id}g`} x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation={5 * k} result="b" />
              <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>
          {sc.ticks.map((t, i) => {
            const p = inOf(f, (5 + i * 2) * S, 16 * S, easeOut);
            const y = Y(t);
            return (
              <g key={i}>
                <line x1={x0} x2={x0 + (x1 - x0 + 40 * k) * p} y1={y} y2={y} stroke={t === sc.min ? "rgba(255,255,255,.28)" : GRID}
                  strokeWidth={Math.max(1, 1.4 * k)} />
                <text x={x0 - 24 * k} y={y + yLabelSize * 0.36} textAnchor="end" fill={SOFT} opacity={p}
                  style={{ fontFamily: SUBLINE, fontWeight: 600, fontSize: yLabelSize, fontVariantNumeric: "tabular-nums" }}>
                  {tickLabel(t)}
                </text>
              </g>
            );
          })}
          {labelled.map((i) => {
            const p = inOf(f, (passAt[i] - 3) * S, 12 * S);
            return (
              <g key={i} opacity={p}>
                <line x1={P[i][0]} x2={P[i][0]} y1={y1} y2={y1 + 10 * k} stroke="rgba(255,255,255,.4)" strokeWidth={2 * k} />
                <text x={P[i][0]} y={y1 + 50 * k} textAnchor="middle" fill={i === n - 1 ? WHITE : SOFT}
                  style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: 26 * k, letterSpacing: "0.04em" }}>
                  {clip(pts[i].label, 12)}
                </text>
              </g>
            );
          })}
          {area ? <path d={area} fill={`url(#${id}a)`} /> : null}
          {draw > 0 ? (
            <path d={d} fill="none" stroke={hot} strokeWidth={5 * k} strokeLinejoin="round" strokeLinecap="round"
              filter={`url(#${id}g)`} />
          ) : null}
          {P.map(([x, y], i) => {
            const p = inOf(f, passAt[i] * S, 10 * S, (t) => backOut(t, 2));
            if (p <= 0 || i === n - 1) return null;
            return <circle key={i} cx={x} cy={y} r={6 * k * p} fill={INK} stroke={hot} strokeWidth={3 * k} />;
          })}
          {draw > 0 && f < (LINE.land + 2) * S ? (
            <circle cx={head[0]} cy={head[1]} r={10 * k} fill={WHITE} style={{ filter: `drop-shadow(0 0 ${10 * k}px ${hot})` }} />
          ) : null}
          {f >= LINE.land * S ? (
            <g>
              <circle cx={ex} cy={ey} r={(12 + 40 * pulse) * k} fill="none" stroke={hot} strokeWidth={3 * k}
                opacity={(1 - pulse) * 0.8} />
              <circle cx={ex} cy={ey} r={11 * k * Math.min(1, landP * 1.4)} fill={WHITE}
                style={{ filter: `drop-shadow(0 0 ${12 * k}px ${hot})` }} />
            </g>
          ) : null}
        </svg>
        {/* The first value, small, beside its point on the free side. */}
        {startFig && n >= 3 ? (
          <div style={{ position: "absolute", left: P[0][0] + 16 * k, top: startBelow ? P[0][1] + 18 * k : P[0][1] - 50 * k,
            opacity: inOf(f, (LINE.drawAt + 1) * S, 12 * S) }}>
            <span style={{ ...caps(24 * k, SOFT, 0.04), textShadow: lift(k, 0.5) }}>{figureText(startFig)}</span>
          </div>
        ) : null}
        {/* The end: value and year called out beside the last point. */}
        {fig ? (
          <div style={{ position: "absolute", top: ey - endSize * 0.62, left: right ? ex + 34 * k : ex - 34 * k - endW,
            width: endW, display: "flex", flexDirection: "column", alignItems: right ? "flex-start" : "flex-end",
            opacity: landP, transform: `translateX(${((1 - landP) * (right ? -18 : 18) * k).toFixed(1)}px)` }}>
            <FigureText fig={fig} text={endText} size={endSize} unitColor={hot} style={{ textShadow: lift(k, 0.55) }} />
            <div style={{ ...caps(24 * k, SOFT, 0.14), marginTop: 12 * k }}>{clip(pts[n - 1].label, 16)}</div>
          </div>
        ) : null}
      </AbsoluteFill>
      <Title ov={overlay} accent={accent} out={out} />
      <Source text={str(overlay.subtitle)} at={20} out={out} />
    </AbsoluteFill>
  );
};

// ================================================================== dx-ghost-bars
const GHOST = { aAt: 6, aFrames: 18, ghostAt: 24, bAt: 27, bFrames: 18, land: 45 };

/**
 * The earlier and the later value (the first and last of the items) and the
 * change between them: in points for two percentages ("−73 PTS"), else in
 * percent ("−35%"); or null.
 */
export const ghostPlan = (ov: Overlay) => {
  const rows = rowsOf(ov.items, 6);
  if (rows.length < 2) return null;
  const a = rows[0];
  const b = rows[rows.length - 1];
  const u = unitsOf(rows, ov.suffix, ov.prefix);
  const pct = figureOf(1, a.suffix || u.suffix).pct;
  const diff = b.value - a.value;
  const change = pct ? `${diff < 0 ? "−" : "+"}${fmtNumber(Math.abs(diff))} PTS` : percentChange(a.value, b.value);
  return { a, b, suffix: u.suffix, prefix: u.prefix, change: Math.abs(diff) < 1e-9 ? "" : change };
};

const GhostBars: Look = ({ overlay, accent }) => {
  const { f, S, k, kw, width, height, dur } = useBase();
  const id = useSvgId("dxg");
  const plan = ghostPlan(overlay);
  const hot = hotOf(accent);
  const out = exitOf(f, dur, S);
  const cues = plan ? [...countCues(GHOST.aAt, GHOST.aAt + GHOST.aFrames, -12), ...countCues(GHOST.bAt, GHOST.land, -11)] : [];
  const sound = useLookSound(cues);
  if (!plan) return null;
  const { a, b } = plan;
  const max = Math.max(a.value, b.value, 1e-9);
  const barX = 480 * kw;
  const barMax = Math.min(1000 * kw, width - barX - 430 * kw);
  const len = (v: number) => (Math.max(0, v) / max) * barMax;
  const barH = 128 * k;
  const yA = height * 0.56 - barH - 42 * k;
  const yB = height * 0.56 + 42 * k;
  const pa = inOf(f, GHOST.aAt * S, GHOST.aFrames * S, easeOut);
  const pb = inOf(f, GHOST.bAt * S, GHOST.bFrames * S, easeOut);
  const ghostP = inOf(f, GHOST.ghostAt * S, 8 * S);
  const gapP = inOf(f, (GHOST.land - 4) * S, 12 * S);
  const landP = inOf(f, GHOST.land * S, 14 * S);
  const figA = figureOf(a.value, a.suffix || plan.suffix, a.prefix || plan.prefix);
  const figB = figureOf(b.value, b.suffix || plan.suffix, b.prefix || plan.prefix);
  const lA = len(a.value);
  const lB = len(b.value);
  const down = b.value < a.value;
  const valSize = 62 * k;
  const labA = clip(a.label || "THEN", 16).toUpperCase();
  const labB = clip(b.label || "NOW", 16).toUpperCase();
  const labSize = Math.min(fit(labA, { font: ANTON }, barX - 170 * kw, 70 * k, 32 * k, 1).size,
    fit(labB, { font: ANTON }, barX - 170 * kw, 70 * k, 32 * k, 1).size);
  const rowLabel = (label: string, y: number, p: number, bright: boolean) => (
    <div style={{ position: "absolute", left: 120 * kw, top: y + barH / 2 - labSize * 0.5, opacity: p,
      transform: `translateX(${((1 - p) * -16 * k).toFixed(1)}px)` }}>
      <span style={{ ...heavy(labSize, bright ? WHITE : SOFT), textShadow: lift(k, 0.5) }}>{label}</span>
    </div>
  );
  const valueAt = (fig: Figure, p: number, l: number, y: number, fill: string) => {
    const t = countText(fig, p);
    const w = figureWidth(fig, t, valSize);
    const inside = l * p > w + 60 * k;
    const ink = inside ? (fill === "light" ? INK : INK) : WHITE;
    return (
      <div style={{ position: "absolute", top: y + barH / 2 - valSize * 0.5, left: inside ? barX + l * p - w - 28 * k : barX + l * p + 24 * k,
        opacity: Math.min(1, p * 3) }}>
        <FigureText fig={fig} text={t} size={valSize} color={ink} unitColor={inside ? ink : hot} />
      </div>
    );
  };
  const gapX0 = barX + Math.min(lA, lB);
  const gapX1 = barX + Math.max(lA, lB);
  const changeSize = 64 * k;
  const changeW = textWidth(plan.change, ANTON, changeSize, 400, 0.01) + 44 * k;
  const changeX = Math.min(gapX1 + 36 * k, width - 96 * kw - changeW);
  return (
    <AbsoluteFill>
      {sound}
      <Stage ov={overlay} p={inOf(f, 0, 10 * S) * (1 - out)} />
      <AbsoluteFill style={{ opacity: 1 - out, transform: `translateY(${(-out * 16 * k).toFixed(1)}px)` }}>
        <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
          <defs>
            <pattern id={`${id}h`} width={16 * k} height={16 * k} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width={16 * k} height={16 * k} fill={rgba(hot, 0.1)} />
              <rect width={6 * k} height={16 * k} fill={rgba(hot, 0.5)} />
            </pattern>
            <linearGradient id={`${id}a`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#eef0f3" />
              <stop offset="1" stopColor="#c9ced6" />
            </linearGradient>
            <linearGradient id={`${id}b`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor={mixHex(hot, "#ffffff", 0.18)} />
              <stop offset="1" stopColor={hot} />
            </linearGradient>
          </defs>
          {/* the axis both bars stand on */}
          <line x1={barX} x2={barX} y1={yA - 34 * k} y2={yB + barH + 34 * k} stroke="rgba(255,255,255,.4)" strokeWidth={2.4 * k}
            opacity={inOf(f, 2 * S, 10 * S)} />
          <rect x={barX} y={yA} width={Math.max(0, lA * pa)} height={barH} rx={4 * k} fill={`url(#${id}a)`}
            style={{ filter: `drop-shadow(0 ${8 * k}px ${18 * k}px rgba(0,0,0,.35))` }} />
          {/* the ghost of the earlier bar on the later row */}
          <rect x={barX} y={yB} width={lA} height={barH} rx={4 * k} fill="none" stroke="rgba(255,255,255,.6)"
            strokeWidth={2.4 * k} strokeDasharray={`${10 * k} ${8 * k}`} opacity={ghostP} />
          {down ? <rect x={gapX0} y={yB} width={(gapX1 - gapX0) * gapP} height={barH} fill={`url(#${id}h)`} /> : null}
          <rect x={barX} y={yB} width={Math.max(0, lB * pb)} height={barH} rx={4 * k} fill={`url(#${id}b)`}
            style={{ filter: `drop-shadow(0 0 ${16 * k}px ${rgba(hot, 0.4)})` }} />
        </svg>
        {rowLabel(labA, yA, inOf(f, 3 * S, 12 * S), false)}
        {rowLabel(labB, yB, inOf(f, (GHOST.bAt - 4) * S, 12 * S), true)}
        {valueAt(figA, pa, lA, yA, "light")}
        {valueAt(figB, pb, lB, yB, "accent")}
        {plan.change ? (
          <div style={{ position: "absolute", left: changeX, top: yB + barH / 2 - changeSize * 0.5 - 14 * k, opacity: landP,
            transform: `translateX(${((1 - landP) * -16 * k).toFixed(1)}px)`, padding: `${14 * k}px ${22 * k}px`,
            borderRadius: 10 * k, background: "rgba(8,10,14,.78)", border: `${Math.max(1, 1.4 * k)}px solid ${rgba(hot, 0.55)}` }}>
            <span style={{ ...heavy(changeSize, hot) }}>{plan.change}</span>
          </div>
        ) : null}
      </AbsoluteFill>
      <Title ov={overlay} accent={accent} out={out} />
      <Source text={str(overlay.subtitle)} at={20} out={out} />
    </AbsoluteFill>
  );
};

// ================================================================== dx-nested-squares
const SQ = { bigAt: 5, bigFrames: 20, innerAt: 24, land: 40 };

/** Two or three values largest first (the ratio of the largest to the smallest), or null. */
export const squaresPlan = (ov: Overlay) => {
  const rows = rowsOf(ov.items, 3).filter((r) => r.value > 0);
  if (rows.length < 2) return null;
  const u = unitsOf(rows, ov.suffix, ov.prefix);
  const sorted = [...rows].sort((x, y) => y.value - x.value);
  return { rows: sorted, suffix: u.suffix, prefix: u.prefix, ratio: ratioText(sorted[0].value, sorted[sorted.length - 1].value) };
};

const NestedSquares: Look = ({ overlay, accent }) => {
  const { f, S, k, kw, width, height, dur } = useBase();
  const plan = squaresPlan(overlay);
  const hot = hotOf(accent);
  const out = exitOf(f, dur, S);
  const sound = useLookSound(plan ? [
    { name: "ui-tick", alt: ["tick"], at: SQ.bigAt + 14, gain_db: -10 },
    ...countCues(SQ.innerAt, SQ.land, -12),
  ] : []);
  if (!plan) return null;
  const side = Math.min(640 * k, height - 400 * kw);
  const rSize = 150 * k;
  const blockW = side + 140 * kw + 520 * k;
  const left = Math.max(150 * kw, (width - blockW) / 2);
  const bottom = height - 150 * kw;
  const top = bottom - side;
  const sides = plan.rows.map((r) => side * Math.sqrt(r.value / plan.rows[0].value));
  const bigP = inOf(f, SQ.bigAt * S, SQ.bigFrames * S, easeInOut);
  const fills = plan.rows.map((_, i) => (i === 0 ? inOf(f, (SQ.bigAt + 10) * S, 14 * S)
    : inOf(f, (SQ.innerAt + (i - 1) * 6) * S, (SQ.land - SQ.innerAt) * S, (t) => backOut(t, 0.6))));
  const per = 4 * side;
  const label = (i: number) => {
    const r = plan.rows[i];
    const s = sides[i];
    const fig = figureOf(r.value, r.suffix || plan.suffix, r.prefix || plan.prefix);
    const p = i === 0 ? inOf(f, (SQ.bigAt + 12) * S, 14 * S) : inOf(f, (SQ.innerAt + 6 + (i - 1) * 6) * S, 14 * S);
    const valSize = Math.max(38 * k, Math.min(68 * k, s * 0.17));
    const inside = s > 240 * k;
    const text = countText(fig, i === 0 ? p : fills[i]);
    // Inside its square at the top-left; a small square takes its label outside, to its right.
    const x = inside ? left + 26 * k : left + s + 24 * k;
    const y = inside ? bottom - s + 24 * k : bottom - s - 6 * k;
    const dark = i > 0 && inside;
    return (
      <div key={i} style={{ position: "absolute", left: x, top: y, opacity: p }}>
        <FigureText fig={fig} text={text} size={valSize} color={dark ? INK : WHITE} unitColor={dark ? INK : hot} />
        <div style={{ ...caps(23 * k, dark ? "rgba(11,13,17,.8)" : SOFT, 0.14), marginTop: 10 * k }}>{clip(r.label, 22)}</div>
      </div>
    );
  };
  const ratioP = inOf(f, (SQ.land + 2) * S, 14 * S);
  const rx = left + side + 140 * kw;
  const big = clip(plan.rows[0].label, 24).toUpperCase();
  const small = clip(plan.rows[plan.rows.length - 1].label, 24).toUpperCase();
  return (
    <AbsoluteFill>
      {sound}
      <Stage ov={overlay} p={inOf(f, 0, 10 * S) * (1 - out)} />
      <AbsoluteFill style={{ opacity: 1 - out, transform: `translateY(${(-out * 16 * k).toFixed(1)}px)` }}>
        <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
          {plan.rows.map((_, i) => {
            const s = sides[i];
            if (i === 0) {
              return (
                <g key={i}>
                  <rect x={left} y={top} width={s} height={s} fill="rgba(255,255,255,.07)" opacity={fills[0]} />
                  <rect x={left} y={top} width={s} height={s} fill="none" stroke="rgba(255,255,255,.88)" strokeWidth={2.6 * k}
                    strokeDasharray={per} strokeDashoffset={per * (1 - bigP)} />
                </g>
              );
            }
            const p = fills[i];
            return (
              <rect key={i} x={left} y={bottom - s * p} width={s * p} height={s * p}
                fill={i === 1 ? hot : mixHex(hot, "#ffffff", 0.5)}
                style={{ filter: i === 1 ? `drop-shadow(0 0 ${22 * k}px ${rgba(hot, 0.35)})` : undefined }} />
            );
          })}
        </svg>
        {plan.rows.map((_, i) => label(i))}
        {plan.ratio ? (
          <div style={{ position: "absolute", left: rx, top: top + side * 0.5 - rSize * 0.9, opacity: ratioP,
            transform: `translateY(${((1 - ratioP) * 20 * k).toFixed(1)}px)` }}>
            <div style={{ ...heavy(rSize, hot), textShadow: lift(k, 0.5) }}>{plan.ratio}</div>
            <div style={{ marginTop: 22 * k, display: "inline-flex", flexDirection: "column", alignItems: "flex-start" }}>
              <div style={{ ...caps(24 * k, WHITE, 0.14) }}>{big}</div>
              <div style={{ height: Math.max(1, 2 * k), width: Math.max(textWidth(big, SUBLINE, 24 * k, 700, 0.14),
                textWidth(small, SUBLINE, 24 * k, 700, 0.14)), background: "rgba(255,255,255,.5)", margin: `${12 * k}px 0` }} />
              <div style={{ ...caps(24 * k, SOFT, 0.14) }}>{small}</div>
            </div>
          </div>
        ) : null}
      </AbsoluteFill>
      <Title ov={overlay} accent={accent} out={out} />
      <Source text={str(overlay.subtitle)} at={20} out={out} />
    </AbsoluteFill>
  );
};

// ================================================================== dx-unit-split
const UNIT = { gridAt: 2, lightAt: 14, land: 38, splitAt: 42 };
const PEOPLE = /\b(people|persons?|residents?|americans?|households?|families|voters?|workers?|children|adults?|citizens?|users?|customers?|farmers?|students?|patients?|homeowners?|population)\b/i;

/** Units to draw and how many are lit: a percentage of 100, or "1 in 4" as four. */
export const unitPlan = (ov: Overlay) => {
  const v = num(ov.value);
  if (v === null) return null;
  const total = num(ov.total);
  const said = `${str(ov.text)} ${str(ov.label)} ${str(ov.subtitle)}`;
  if (total !== null && total >= 2 && total <= 10 && v >= 0 && v <= total) {
    return { count: Math.round(total), lit: Math.round(v), ratio: true, pct: (v / total) * 100, people: PEOPLE.test(said) };
  }
  const pct = Math.max(0, Math.min(100, v));
  return { count: 100, lit: Math.round(pct), ratio: false, pct, people: PEOPLE.test(said) };
};

/** A unit: a dot, or a person (a head and shoulders drawn clean, never clip-art). */
const Unit: React.FC<{ x: number; y: number; size: number; color: string; people: boolean; scale?: number; glow?: string }> =
  ({ x, y, size, color, people, scale = 1, glow }) => {
    const s = size * scale;
    if (s <= 0.1) return null;
    if (!people) {
      return <circle cx={x} cy={y} r={s / 2} fill={color} style={glow ? { filter: `drop-shadow(0 0 ${s * 0.35}px ${glow})` } : undefined} />;
    }
    return (
      <g transform={`translate(${x} ${y})`} style={glow ? { filter: `drop-shadow(0 0 ${s * 0.3}px ${glow})` } : undefined}>
        <circle cx={0} cy={-s * 0.25} r={s * 0.21} fill={color} />
        <path d={`M ${-s * 0.36} ${s * 0.48} C ${-s * 0.36} ${s * 0.08}, ${-s * 0.2} ${s * 0.0}, 0 ${s * 0.0} `
          + `C ${s * 0.2} ${s * 0.0}, ${s * 0.36} ${s * 0.08}, ${s * 0.36} ${s * 0.48} Z`} fill={color} />
      </g>
    );
  };

const UnitSplit: Look = ({ overlay, accent }) => {
  const { f, S, k, kw, width, height, dur } = useBase();
  const plan = unitPlan(overlay);
  const hot = hotOf(accent);
  const out = exitOf(f, dur, S);
  const sound = useLookSound(plan ? countCues(UNIT.lightAt, UNIT.land, -12) : []);
  if (!plan) return null;
  const { count, lit, people } = plan;
  const cols = plan.ratio ? count : 10;
  const rows = plan.ratio ? 1 : 10;
  const pitch = plan.ratio ? Math.min(190 * k, (880 * kw) / count) : 62 * k;
  const unit = pitch * (plan.ratio ? 0.66 : people ? 0.9 : 0.66);
  const gridW = cols * pitch;
  const gridH = rows * pitch;
  const cx = 150 * kw + 40 * k + gridW / 2;
  const cy = height * 0.52;
  const gx = cx - gridW / 2;
  const gy = cy - gridH / 2;
  const split = inOf(f, UNIT.splitAt * S, 16 * S, easeInOut) * (plan.ratio ? 0 : 1);
  const gap = 40 * k * split;
  const lightFrames = UNIT.land - UNIT.lightAt;
  const units: React.ReactNode[] = [];
  for (let i = 0; i < count; i++) {
    // Column-major: the share is the leftmost columns, so it separates cleanly.
    const col = plan.ratio ? i : Math.floor(i / rows);
    const row = plan.ratio ? 0 : i % rows;
    const isLit = i < lit;
    const appear = inOf(f, (UNIT.gridAt + (col + row) * 0.6) * S, 10 * S, (t) => backOut(t, 1.4));
    const litAt = UNIT.lightAt + (lit > 1 ? (i / Math.max(1, lit - 1)) * (lightFrames - 6) : 0);
    const lp = isLit ? inOf(f, litAt * S, 7 * S) : 0;
    const x = gx + col * pitch + pitch / 2 + (isLit ? -gap : gap);
    const y = gy + row * pitch + pitch / 2;
    const color = isLit ? mixHex("#59606d", hot, lp) : "#454b56";
    units.push(<Unit key={i} x={x} y={y} size={unit} color={color} people={people} scale={appear * (1 + 0.5 * lp * (1 - lp))}
      glow={isLit && lp > 0.5 ? rgba(hot, 0.4) : undefined} />);
  }
  const countP = easeOut(clamp01((f - UNIT.lightAt * S) / (lightFrames * S)));
  const figSize = 200 * k;
  const pctFig = figureOf(plan.pct, "%");
  const label = clip(digits(str(overlay.text)), 64).toUpperCase();
  const fx = gx + gridW + 140 * kw;
  const labelFit = fit(label, { font: SUBLINE, weight: 700, tracking: 0.08 }, width - fx - 110 * kw, 40 * k, 26 * k, 3);
  const textP = inOf(f, (UNIT.land - 4) * S, 14 * S);
  const shownLit = Math.round(lit * countP);
  return (
    <AbsoluteFill>
      {sound}
      <Stage ov={overlay} p={inOf(f, 0, 10 * S) * (1 - out)} />
      <AbsoluteFill style={{ opacity: 1 - out, transform: `scale(${(1 - out * 0.03).toFixed(4)})` }}>
        <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>{units}</svg>
        <div style={{ position: "absolute", left: fx, top: cy - figSize * 0.72 }}>
          {plan.ratio ? (
            <span style={{ ...heavy(figSize * 0.78, WHITE), textShadow: lift(k, 0.5) }}>
              <span style={{ color: hot }}>{fmtNumber(Math.max(0, Math.min(lit, shownLit)))}</span>
              <span style={{ fontSize: figSize * 0.4, margin: `0 ${figSize * 0.12}px`, color: SOFT }}>IN</span>
              {fmtNumber(count)}
            </span>
          ) : (
            <FigureText fig={pctFig} text={countText(pctFig, countP)} size={figSize} unitColor={hot}
              style={{ textShadow: lift(k, 0.5) }} />
          )}
          {labelFit.lines.length ? (
            <div style={{ marginTop: 26 * k, opacity: textP, transform: `translateY(${((1 - textP) * 14 * k).toFixed(1)}px)` }}>
              {labelFit.lines.map((ln, i) => (
                <div key={i} style={{ ...caps(labelFit.size, WHITE, 0.08), lineHeight: 1.3 }}>{ln}</div>
              ))}
            </div>
          ) : null}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== dx-filled-figure
const FILL = { drawAt: 0, drawFrames: 16, riseAt: 10, land: 42 };

/** The share 0-100 the figure fills to, or null. */
export const fillPlan = (ov: Overlay) => {
  const v = num(ov.value);
  if (v === null) return null;
  const pct = Math.max(0, Math.min(100, v));
  return { pct, fig: figureOf(pct, "%") };
};

const FilledFigure: Look = ({ overlay, accent }) => {
  const { f, S, k, kw, width, height, dur, fps } = useBase();
  const id = useSvgId("dxf");
  const plan = fillPlan(overlay);
  const hot = hotOf(accent);
  const out = exitOf(f, dur, S);
  const sound = useLookSound(plan ? countCues(FILL.riseAt, FILL.land, -12) : []);
  if (!plan) return null;
  const rise = inOf(f, FILL.riseAt * S, (FILL.land - FILL.riseAt) * S, easeOut);
  const finalText = `${countText(plan.fig, 1)}%`;
  // The figure: Anton, about half the frame wide, its cap about 430 px at 1080p.
  const size = Math.min(500 * k, (width * 0.46) / Math.max(0.5, textWidth(finalText, ANTON, 1, 400, 0.01)));
  const cap = size * 0.859;
  const left = 130 * kw;
  const baseline = height * 0.5 + cap * 0.5;
  const capTop = baseline - cap;
  const level = baseline - cap * (plan.pct / 100) * rise;
  const t = f / fps;
  // A gentle wave on the surface, a little slosh as it lands.
  const landed = f >= FILL.land * S;
  const amp = (4 + (landed ? 9 * Math.exp(-(f - FILL.land * S) / (9 * S)) : 4 * (1 - rise))) * k;
  const textW = textWidth(finalText, ANTON, size, 400, 0.01);
  const xs = left - 20 * k;
  const xe = left + textW + 40 * k;
  const crest: string[] = [];
  for (let i = 0; i <= 56; i++) {
    const x = xs + ((xe - xs) * i) / 56;
    const y = level + Math.sin(i * 0.5 + t * 3.1) * amp + Math.sin(i * 0.21 - t * 1.6) * amp * 0.55;
    crest.push(`${x.toFixed(1)} ${y.toFixed(1)}`);
  }
  const surfaceLine = `M${crest.join(" L")}`;
  const wave = `M${xs} ${baseline + 30 * k} L${crest.join(" L")} L${xe} ${baseline + 30 * k} Z`;
  const drawP = inOf(f, FILL.drawAt * S, FILL.drawFrames * S, easeInOut);
  const label = clip(digits(str(overlay.text)), 40).toUpperCase();
  const sub = clip(digits(str(overlay.subtitle || overlay.label)), 34).toUpperCase();
  const labelP = inOf(f, (FILL.land - 10) * S, 14 * S);
  const lx = left + textW + 64 * k;
  const room = width - lx - 100 * kw;
  const lab = fit(label, { font: ANTON, tracking: 0.01 }, room, 78 * k, 40 * k, 3);
  const textStyle: CSS = { fontFamily: ANTON, fontSize: size, letterSpacing: "0.01em" };
  const blockH = lab.lines.length * lab.size * 1.06 + (sub ? 56 * k : 0);
  return (
    <AbsoluteFill style={{ opacity: 1 - out, transform: `translateY(${(-out * 16 * k).toFixed(1)}px)` }}>
      {sound}
      <Pool x={left + textW * 0.5} y={height * 0.5} w={textW * 1.8} h={cap * 2.0} p={inOf(f, 0, 12 * S)} strength={0.7} />
      <Pool x={lx + Math.min(room, lab.width) * 0.5} y={height * 0.5} w={Math.min(room, lab.width) * 1.8 + 200 * k}
        h={blockH * 2.4} p={labelP} strength={0.55} />
      <svg width={width} height={height} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
        <defs>
          <clipPath id={`${id}c`}>
            <text x={left} y={baseline} style={textStyle}>{finalText}</text>
          </clipPath>
          <linearGradient id={`${id}w`} x1="0" y1={capTop} x2="0" y2={baseline} gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#8fd0f5" />
            <stop offset="0.4" stopColor="#3a90cc" />
            <stop offset="1" stopColor="#0f3f6e" />
          </linearGradient>
        </defs>
        {/* dark glass inside the letters, so they read on a bright sky */}
        <g clipPath={`url(#${id}c)`}>
          <rect x={xs} y={capTop - 30 * k} width={xe - xs} height={cap + 60 * k} fill="rgba(6,10,16,.42)" opacity={drawP} />
          <path d={wave} fill={`url(#${id}w)`} />
          <path d={surfaceLine} fill="none" stroke="rgba(214,240,255,.95)" strokeWidth={3 * k} />
        </g>
        {/* the outline draws on */}
        <text x={left} y={baseline} style={{ ...textStyle, fill: "none", stroke: WHITE, strokeWidth: 4.5 * k,
          strokeDasharray: 4200 * k, strokeDashoffset: 4200 * k * (1 - drawP), strokeLinejoin: "round",
          filter: `drop-shadow(0 ${3 * k}px ${10 * k}px rgba(0,0,0,.55))` }}>{finalText}</text>
      </svg>
      {lab.lines.length || sub ? (
        <div style={{ position: "absolute", left: lx, top: height * 0.5 - blockH / 2, opacity: labelP,
          transform: `translateX(${((1 - labelP) * -20 * k).toFixed(1)}px)` }}>
          {lab.lines.map((ln, i) => (
            <div key={i} style={{ ...heavy(lab.size, WHITE), lineHeight: 1.06, textShadow: lift(k, 0.55) }}>{ln}</div>
          ))}
          {sub ? <div style={{ ...caps(28 * k, hot, 0.18), marginTop: 22 * k, textShadow: lift(k, 0.6) }}>{sub}</div> : null}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== dx-capacity-gauge
const GAUGE = { arcAt: 0, swingAt: 12, land: 38 };

/** The share 0-100 the needle swings to, or null. */
export const gaugePlan = (ov: Overlay) => {
  const v = num(ov.value);
  if (v === null) return null;
  const total = num(ov.total);
  const pct = total && total > 0 && unitOfPct(ov) === false ? (v / total) * 100 : v;
  const p = Math.max(0, Math.min(100, pct));
  return { pct: p, fig: figureOf(p, "%") };
};
const unitOfPct = (ov: Overlay) => figureOf(1, ov.suffix).pct;

const CapacityGauge: Look = ({ overlay, accent }) => {
  const { f, S, k, width, height, dur } = useBase();
  const id = useSvgId("dxc");
  const plan = gaugePlan(overlay);
  const hot = hotOf(accent);
  const out = exitOf(f, dur, S);
  const sound = useLookSound(plan ? [
    { name: "count-roll", alt: ["count-tick", "ui-tick"], at: GAUGE.swingAt, align: "start", until: GAUGE.land - 1, gain_db: -13 },
    { name: "count-final", alt: ["ui-tick", "tick"], at: GAUGE.land, gain_db: -5 },
  ] : []);
  if (!plan) return null;
  const cx = width / 2;
  const cy = height * 0.6;
  const R = 330 * k;
  const sw = 34 * k;
  const swing = clamp01((f - GAUGE.swingAt * S) / ((GAUGE.land - GAUGE.swingAt) * S));
  // A damped needle: up to the value with a small overshoot, then a settle.
  const target = plan.pct / 100;
  const settleT = Math.max(0, (f - GAUGE.land * S) / S);
  const pos = f < GAUGE.land * S ? target * backOut(easeOut(swing) * 0.98 + 0.02 * swing, 0.7)
    : target + 0.025 * Math.exp(-settleT / 5) * Math.sin(settleT / 1.8) * (target > 0.02 ? 1 : 0);
  const p = Math.max(0, Math.min(1.03, pos));
  const ang = Math.PI * (1 - p);
  const pt = (a: number, r: number) => [cx + Math.cos(a) * r, cy - Math.sin(a) * r] as [number, number];
  const arcD = (a0: number, a1: number, r: number) => {
    const [x0, y0] = pt(a0, r);
    const [x1, y1] = pt(a1, r);
    return `M${x0.toFixed(1)} ${y0.toFixed(1)} A${r} ${r} 0 ${Math.abs(a0 - a1) > Math.PI ? 1 : 0} 1 ${x1.toFixed(1)} ${y1.toFixed(1)}`;
  };
  const arcP = inOf(f, GAUGE.arcAt * S, 16 * S, easeInOut);
  const figText = countText(plan.fig, f >= GAUGE.land * S ? 1 : clamp01(p / Math.max(1e-6, target)));
  const landP = inOf(f, GAUGE.land * S, 12 * S);
  const label = clip(digits(str(overlay.text)), 36).toUpperCase();
  const sub = clip(digits(str(overlay.subtitle || overlay.label || "FULL")), 24).toUpperCase();
  const needleL = R - 30 * k;
  const [nx, ny] = pt(ang, needleL);
  const [bx1, by1] = pt(ang + Math.PI / 2, 11 * k);
  const [bx2, by2] = pt(ang - Math.PI / 2, 11 * k);
  const [tx, ty] = pt(ang + Math.PI, 34 * k);
  const ticks: React.ReactNode[] = [];
  for (let i = 0; i <= 20; i++) {
    const a = Math.PI * (1 - i / 20);
    const major = i % 5 === 0;
    const tp = inOf(f, (4 + i * 0.6) * S, 10 * S);
    const [ax, ay] = pt(a, R - sw / 2 - 16 * k);
    const [bx, by] = pt(a, R - sw / 2 - (major ? 46 : 28) * k);
    ticks.push(<line key={i} x1={ax} y1={ay} x2={bx} y2={by} stroke={i <= 3 ? rgba(hot, 0.95) : "rgba(255,255,255,.7)"}
      strokeWidth={(major ? 4 : 2.2) * k} opacity={tp} strokeLinecap="round" />);
  }
  const [ex, ey] = pt(Math.PI - 0.0, R + sw / 2 + 52 * k);
  const [fx, fy] = pt(0, R + sw / 2 + 52 * k);
  const [hx, hy] = pt(Math.PI / 2, R - sw / 2 - 84 * k);
  const plateR = R + sw / 2 + 110 * k;
  return (
    <AbsoluteFill style={{ opacity: 1 - out, transform: `translateY(${(-out * 14 * k).toFixed(1)}px)` }}>
      {sound}
      <Pool x={cx} y={cy - R * 0.3} w={plateR * 2.6} h={plateR * 1.9} p={inOf(f, 0, 12 * S)} strength={0.55} />
      <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
        <defs>
          <radialGradient id={`${id}p`} cx={cx} cy={cy} r={plateR} gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="rgba(18,21,27,.86)" />
            <stop offset="0.82" stopColor="rgba(10,12,16,.82)" />
            <stop offset="1" stopColor="rgba(10,12,16,0)" />
          </radialGradient>
          <linearGradient id={`${id}f`} x1={cx - R} y1="0" x2={cx + R} y2="0" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor={hot} />
            <stop offset="1" stopColor={mixHex(hot, "#ffffff", 0.35)} />
          </linearGradient>
        </defs>
        <path d={`M${cx - plateR} ${cy + 70 * k} A${plateR} ${plateR} 0 0 1 ${cx + plateR} ${cy + 70 * k} Z`}
          fill={`url(#${id}p)`} opacity={arcP} />
        <path d={arcD(Math.PI, 0, R)} fill="none" stroke="rgba(255,255,255,.14)" strokeWidth={sw} strokeLinecap="round"
          strokeDasharray={Math.PI * R} strokeDashoffset={Math.PI * R * (1 - arcP)} />
        {p > 0.003 ? (
          <path d={arcD(Math.PI, Math.max(0.0001, ang), R)} fill="none" stroke={`url(#${id}f)`} strokeWidth={sw}
            strokeLinecap="round" style={{ filter: `drop-shadow(0 0 ${14 * k}px ${rgba(hot, 0.5)})` }} />
        ) : null}
        {ticks}
        <text x={ex} y={ey + 22 * k} textAnchor="middle" fill={hot} opacity={arcP} style={{ fontFamily: ANTON, fontSize: 64 * k }}>E</text>
        <text x={fx} y={fy + 22 * k} textAnchor="middle" fill={WHITE} opacity={arcP} style={{ fontFamily: ANTON, fontSize: 64 * k }}>F</text>
        <text x={hx} y={hy} textAnchor="middle" fill={SOFT} opacity={arcP}
          style={{ fontFamily: ANTON, fontSize: 40 * k }}>½</text>
        <polygon points={`${nx},${ny} ${bx1},${by1} ${tx},${ty} ${bx2},${by2}`} fill={WHITE} opacity={arcP}
          style={{ filter: `drop-shadow(0 ${3 * k}px ${8 * k}px rgba(0,0,0,.6))` }} />
        <circle cx={cx} cy={cy} r={28 * k} fill="#15181e" stroke="rgba(255,255,255,.8)" strokeWidth={3.4 * k} opacity={arcP} />
        <circle cx={cx} cy={cy} r={9 * k} fill={hot} opacity={arcP} />
      </svg>
      <div style={{ position: "absolute", left: 0, right: 0, top: cy + 58 * k, display: "flex", flexDirection: "column",
        alignItems: "center", opacity: inOf(f, GAUGE.swingAt * S, 8 * S) }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 20 * k }}>
          <FigureText fig={plan.fig} text={figText} size={120 * k} unitColor={hot} style={{ textShadow: lift(k, 0.6) }} />
          <span style={{ ...caps(34 * k, WHITE, 0.16), opacity: landP, textShadow: lift(k, 0.6) }}>{sub}</span>
        </div>
      </div>
      {label ? (
        <div style={{ position: "absolute", left: 0, right: 0, top: cy - R - sw / 2 - 150 * k, display: "flex", justifyContent: "center",
          opacity: inOf(f, 6 * S, 14 * S) }}>
          <span style={{ ...caps(34 * k, WHITE, 0.22), textShadow: lift(k, 0.7) }}>{label}</span>
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== dx-drum-counter
const DRUM = { inAt: 0, spinAt: 6, land: 42 };

/** The figure on the drums, or null. */
export const drumPlan = (ov: Overlay) => {
  const v = num(ov.value);
  if (v === null || Math.abs(v) >= 1e12) return null;
  const fig = figureOf(Math.abs(v), ov.suffix, ov.prefix, true);
  return { fig, text: countText(fig, 1) };
};

const DrumCounter: Look = ({ overlay, accent }) => {
  const { f, S, k, width, height, dur } = useBase();
  const id = useSvgId("dxd");
  const plan = drumPlan(overlay);
  const hot = hotOf(accent);
  const out = exitOf(f, dur, S);
  const sound = useLookSound(plan ? countCues(DRUM.spinAt, DRUM.land, -12) : []);
  if (!plan) return null;
  const chars = Array.from(plan.text);
  const digitIdx = chars.map((c, i) => (/\d/.test(c) ? i : -1)).filter((i) => i >= 0);
  const nd = digitIdx.length;
  // Sizes: digits on drums about 190 px cap at 1080p, fitted to the frame.
  const unitW = (plan.fig.unit ? textWidth(plan.fig.unit, ANTON, 1, 400, 0.04) * 0.55 + 0.25 : 0)
    + (plan.fig.glued ? textWidth(plan.fig.glued, ANTON, 1) * 0.8 + 0.06 : 0) + (plan.fig.prefix ? 0.42 : 0);
  const em = nd * 0.74 + (chars.length - nd) * 0.26 + unitW;
  const size = Math.min(230 * k, (width * 0.78) / Math.max(1, em));
  const drumW = size * 0.66;
  const drumH = size * 1.12;
  const gap = size * 0.07;
  const sepW = size * 0.24;
  const plateP = inOf(f, DRUM.inAt * S, 12 * S);
  const landP = inOf(f, DRUM.land * S, 14 * S);
  const columns: React.ReactNode[] = [];
  let x = 0;
  let di = 0;
  chars.forEach((c, i) => {
    if (!/\d/.test(c)) {
      columns.push(
        <div key={i} style={{ position: "absolute", left: x, top: drumH * 0.5 - size * 0.5, width: sepW, textAlign: "center",
          ...heavy(size * 0.7, "rgba(255,255,255,.75)"), lineHeight: `${size}px` }}>{c}</div>,
      );
      x += sepW;
      return;
    }
    const target = Number(c);
    const fromRight = nd - 1 - di;
    // The rightmost drum spins most and lands last; each lands 3 frames after the one on its left.
    const end = DRUM.land - fromRight * 0 - (nd - 1 - fromRight) * 3;
    const turns = 1 + fromRight * 0.6 + (nd - di) * 0.4;
    const q = inOf(f, (DRUM.spinAt + di * 1.5) * S, (end - DRUM.spinAt - di * 1.5) * S, easeOut);
    const pos = (target + 10 * Math.round(turns * 2)) * q;
    const speed = Math.abs(inOf(f + 1, (DRUM.spinAt + di * 1.5) * S, (end - DRUM.spinAt - di * 1.5) * S, easeOut) - q)
      * (target + 10 * Math.round(turns * 2));
    const blur = Math.min(10, speed * 2.2) * k;
    const appear = inOf(f, (2 + di * 1.2) * S, 10 * S);
    const strip: React.ReactNode[] = [];
    const base = Math.floor(pos);
    for (let s = -1; s <= 2; s++) {
      const n = base + s;
      const y = (n - pos) * drumH;
      // Cylinder: a digit away from the middle is squashed and darker.
      const rel = y / drumH;
      const squash = Math.cos(Math.max(-1.2, Math.min(1.2, rel * 1.15)));
      strip.push(
        <div key={s} style={{ position: "absolute", left: 0, right: 0, top: drumH / 2 - size * 0.5 - y * 0.92, height: size,
          display: "flex", justifyContent: "center", ...heavy(size, WHITE), lineHeight: `${size}px`,
          transform: `scaleY(${squash.toFixed(3)})`, opacity: 0.35 + 0.65 * squash }}>{((n % 10) + 10) % 10}</div>,
      );
    }
    columns.push(
      <div key={i} style={{ position: "absolute", left: x, top: 0, width: drumW, height: drumH, borderRadius: 10 * k, overflow: "hidden",
        background: "linear-gradient(180deg, #050608 0%, #1d2129 22%, #2a2f39 50%, #1d2129 78%, #050608 100%)",
        boxShadow: `inset 0 ${2 * k}px ${4 * k}px rgba(0,0,0,.8), inset 0 ${-1 * k}px 0 rgba(255,255,255,.08), 0 ${1 * k}px 0 rgba(255,255,255,.06)`,
        opacity: appear, transform: `translateY(${((1 - appear) * 18 * k).toFixed(1)}px)` }}>
        <div style={{ position: "absolute", inset: 0, filter: blur > 0.3 ? `blur(0px) url(#${id}m${Math.round(blur)})` : undefined }}>{strip}</div>
        <div style={{ position: "absolute", inset: 0, pointerEvents: "none",
          background: "linear-gradient(180deg, rgba(0,0,0,.72) 0%, rgba(0,0,0,0) 30%, rgba(255,255,255,.05) 46%, rgba(0,0,0,0) 62%, rgba(0,0,0,.72) 100%)" }} />
      </div>,
    );
    x += drumW + gap;
    di += 1;
  });
  const drumsW = x - gap;
  const unitSize = size * 0.5;
  const unit = plan.fig.unit || plan.fig.glued;
  const unitWpx = unit ? textWidth(unit, ANTON, unitSize, 400, 0.04) : 0;
  const prefixW = plan.fig.prefix ? textWidth(plan.fig.prefix, ANTON, size * 0.8) + 18 * k : 0;
  const totalW = prefixW + drumsW + (unit ? 26 * k + unitWpx : 0);
  const left = (width - totalW) / 2;
  const top = height * 0.46 - drumH / 2;
  const pad = 34 * k;
  const label = clip(digits(str(overlay.text)), 54).toUpperCase();
  const lab = fit(label, { font: SUBLINE, weight: 700, tracking: 0.16 }, Math.max(totalW, 700 * k), 34 * k, 24 * k, 2);
  const blurs = [2, 4, 6, 8, 10];
  return (
    <AbsoluteFill style={{ opacity: 1 - out, transform: `translateY(${(-out * 14 * k).toFixed(1)}px)` }}>
      {sound}
      <svg width={0} height={0} style={{ position: "absolute" }}>
        {blurs.map((b) => (
          <filter key={b} id={`${id}m${b}`} x="-10%" y="-40%" width="120%" height="180%">
            <feGaussianBlur stdDeviation={`0 ${b * k}`} />
          </filter>
        ))}
      </svg>
      <Pool x={width / 2} y={height * 0.5} w={totalW * 1.9} h={drumH * 3.2} p={plateP} strength={0.55} />
      <div style={{ position: "absolute", left: left - pad, top: top - pad, width: totalW + 2 * pad, height: drumH + 2 * pad,
        borderRadius: 22 * k, background: "linear-gradient(180deg, rgba(24,27,33,.82) 0%, rgba(10,11,14,.88) 100%)",
        backdropFilter: `blur(${16 * k}px)`, border: `${Math.max(1, 1.2 * k)}px solid rgba(255,255,255,.10)`,
        boxShadow: `0 ${30 * k}px ${80 * k}px rgba(0,0,0,.55), inset 0 1px 0 rgba(255,255,255,.08)`,
        opacity: plateP, transform: `scale(${(0.96 + 0.04 * plateP).toFixed(4)})` }} />
      {plan.fig.prefix ? (
        <div style={{ position: "absolute", left, top: top + drumH / 2 - size * 0.4, ...heavy(size * 0.8, hot), opacity: plateP }}>
          {plan.fig.prefix}
        </div>
      ) : null}
      <div style={{ position: "absolute", left: left + prefixW, top, width: drumsW, height: drumH }}>{columns}</div>
      {unit ? (
        <div style={{ position: "absolute", left: left + prefixW + drumsW + 26 * k, top: top + drumH / 2 + size * 0.36 - unitSize * 0.86,
          ...heavy(unitSize, hot, 0.04), opacity: landP, transform: `translateX(${((1 - landP) * -12 * k).toFixed(1)}px)` }}>{unit}</div>
      ) : null}
      {lab.lines.length ? (
        <div style={{ position: "absolute", left: 0, right: 0, top: top + drumH + pad + 30 * k, display: "flex", flexDirection: "column",
          alignItems: "center", opacity: landP, transform: `translateY(${((1 - landP) * 12 * k).toFixed(1)}px)` }}>
          {lab.lines.map((ln, i) => <div key={i} style={{ ...caps(lab.size, WHITE, 0.16), lineHeight: 1.3, textShadow: lift(k, 0.6) }}>{ln}</div>)}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== dx-reservoir-section
const RES = { inAt: 0, moveAt: 14, land: 46 };

/** The canyon's profile across the section, (x 0..1, depth 0 rim .. 1 floor): benches and cliffs. */
const PROFILE: [number, number][] = [
  [0.0, 0.0], [0.07, 0.0], [0.11, 0.05], [0.15, 0.19], [0.205, 0.215], [0.24, 0.37], [0.295, 0.395], [0.33, 0.58],
  [0.37, 0.6], [0.4, 0.8], [0.43, 0.93], [0.47, 0.985], [0.53, 1.0], [0.58, 0.975], [0.61, 0.86], [0.64, 0.83],
  [0.67, 0.63], [0.73, 0.6], [0.765, 0.4], [0.82, 0.375], [0.855, 0.2], [0.9, 0.17], [0.935, 0.03], [0.97, 0.0], [1.0, 0.0],
];

/** The level said, where the water starts, full pool and thresholds when said, and the range drawn. */
export const reservoirPlan = (ov: Overlay) => {
  const v = num(ov.value);
  if (v === null || v <= 0) return null;
  const total = num(ov.total);
  const full = total !== null && total > v * 0.5 && total < v * 2 && Math.abs(total - v) > 1e-9 ? total : null;
  const thresholds = rowsOf(ov.items, 3).filter((r) => r.value > 0 && Math.abs(r.value - v) > 1e-9 && r.value > v * 0.5
    && r.value < v * 2);
  const dir = str(ov.label).toLowerCase();
  const up = /\b(up|rose|rise|risen|higher|climb)/.test(dir) || (full !== null && full < v);
  const all = [v, ...(full !== null ? [full] : []), ...thresholds.map((t) => t.value)];
  let lo = Math.min(...all);
  let hi = Math.max(...all);
  if (hi - lo < 1e-9) {
    const span = Math.max(20, v * 0.1);
    lo = v - span * 0.55;
    hi = v + span * 0.45;
  } else {
    const span = hi - lo;
    lo -= span * 0.9;
    hi += span * 0.35;
  }
  const sc = niceScale(lo, hi, 4);
  const start = full !== null ? full : up ? sc.min + (sc.max - sc.min) * 0.18 : sc.max - (sc.max - sc.min) * 0.08;
  const fig = figureOf(v, ov.suffix || "FT", ov.prefix, true);
  const change = full !== null ? v - full : null;
  return { v, full, thresholds, sc, start, fig, change, up };
};

/** Labels on one column pushed apart (in order of their wanted y) so none overlap; returns their y. */
const spread = (wanted: { y: number; h: number }[], gap: number): number[] => {
  const order = wanted.map((w, i) => i).sort((a, b) => wanted[a].y - wanted[b].y);
  const ys = wanted.map((w) => w.y);
  for (let pass = 0; pass < 8; pass++) {
    for (let j = 1; j < order.length; j++) {
      const a = order[j - 1];
      const b = order[j];
      const need = (wanted[a].h + wanted[b].h) / 2 + gap;
      const d = ys[b] - ys[a];
      if (d < need) {
        const push = (need - d) / 2;
        ys[a] -= push;
        ys[b] += push;
      }
    }
  }
  return ys;
};

const ReservoirSection: Look = ({ overlay, accent }) => {
  const { f, S, k, kw, width, height, dur, fps } = useBase();
  const id = useSvgId("dxr");
  const plan = reservoirPlan(overlay);
  const hot = hotOf(accent);
  const out = exitOf(f, dur, S);
  const sound = useLookSound(plan ? countCues(RES.moveAt, RES.land, -12) : []);
  if (!plan) return null;
  const { sc } = plan;
  // The canyon on the left two thirds; the rock runs to both edges, the labels sit on it at the right.
  const L = 110 * kw;
  const R = 1330 * kw;
  const T = 300 * kw;
  const B = height - 70 * kw;
  const colR = width - 100 * kw;
  const rim = sc.max + (sc.max - sc.min) * 0.04;
  const floor = sc.min - (sc.max - sc.min) * 0.02;
  const Y = (e: number) => T + ((rim - e) / (rim - floor || 1)) * (B - T);
  const px = (x: number) => L + x * (R - L);
  const py = (d: number) => T + d * (B - T);
  const wall = PROFILE.map(([x, d]) => `${px(x).toFixed(1)} ${py(d).toFixed(1)}`);
  const canyon = `M${wall.join(" L")} Z`;
  const rockD = `M${-40 * kw} ${T} L${wall.join(" L")} L${width + 40 * kw} ${T} L${width + 40 * kw} ${height + 40 * kw} `
    + `L${-40 * kw} ${height + 40 * kw} Z`;
  const move = inOf(f, RES.moveAt * S, (RES.land - RES.moveAt) * S, easeInOut);
  const level = lerp(plan.start, plan.v, move);
  const t = f / fps;
  const slosh = f >= RES.land * S ? Math.exp(-(f - RES.land * S) / (12 * S)) : 0;
  const amp = (2.2 + 6 * slosh) * k;
  const wy = Y(level);
  const crest: string[] = [];
  for (let i = 0; i <= 44; i++) {
    const x = px(0.04 + (0.92 * i) / 44);
    crest.push(`${x.toFixed(1)} ${(wy + Math.sin(i * 0.9 + t * 2.6) * amp * 0.6 + Math.sin(i * 0.37 - t * 1.4) * amp * 0.4).toFixed(1)}`);
  }
  const surface = `M${crest.join(" L")}`;
  const water = `M${px(0)} ${wy} L${crest.join(" L")} L${px(1)} ${wy} L${px(1)} ${B + 40 * kw} L${px(0)} ${B + 40 * kw} Z`;
  const ringTop = Y(Math.max(plan.start, plan.v, plan.full ?? -Infinity));
  const ringP = !plan.up && ringTop < wy - 2 ? clamp01(move * 1.2) : 0;
  const sectionP = inOf(f, RES.inAt * S, 16 * S);
  const lineP = inOf(f, 8 * S, 14 * S);
  const landP = inOf(f, RES.land * S, 14 * S);
  const fig = plan.fig;
  const figNow = countText(fig, move, plan.start);
  const valSize = 74 * k;
  const label = clip(digits(str(overlay.text)), 28).toUpperCase();
  const strata = [0.06, 0.13, 0.22, 0.29, 0.41, 0.5, 0.58, 0.68, 0.75, 0.86, 0.93];
  const unitTxt = (e: number) => `${fmtNumber(e, undefined, true)}${fig.unit ? ` ${fig.unit}` : ""}`;
  const dash = `${12 * k} ${10 * k}`;
  const fullY = plan.full !== null ? Y(plan.full) : 0;
  const showDrop = plan.change !== null && Math.abs(fullY - Y(plan.v)) > 24 * k;
  // The label column: the level's plate, full pool above its line, each threshold under its own.
  const plateH = valSize * 1.0 + 28 * k + (label ? 40 * k : 0) + (showDrop && Math.abs(fullY - Y(plan.v)) <= 120 * k ? 34 * k : 0);
  // The drop's bracket: just right of where the full-pool line leaves the canyon wall; its figure beside it
  // when there is room between the two lines, else under the level's plate.
  const bx = R + 70 * kw;
  const bigGap = Math.abs(fullY - Y(plan.v)) > 120 * k;
  const dropText = plan.change !== null ? `${fmtNumber(Math.abs(plan.change), undefined, true)}${fig.unit ? ` ${fig.unit}` : ""}` : "";
  const dropWords = plan.change !== null && plan.change < 0 ? "BELOW FULL POOL" : "ABOVE FULL POOL";
  const items = [
    { key: "level", y: Y(plan.v) + plateH / 2 - valSize * 0.55, h: plateH },
    ...(plan.full !== null ? [{ key: "full", y: fullY - 24 * k, h: 34 * k }] : []),
    ...plan.thresholds.map((th, i) => ({ key: `th${i}`, y: Y(th.value) + 26 * k, h: 34 * k })),
  ];
  const placed = spread(items.map((it) => ({ y: it.y, h: it.h })), 14 * k);
  const yOf = (key: string) => placed[items.findIndex((it) => it.key === key)];
  const levelTop = (yOf("level") ?? Y(plan.v)) - plateH / 2;
  const capsLine = (txt: string, color: string, y: number, p: number) => (
    <div style={{ position: "absolute", right: width - colR - 12 * k, top: y - 23 * k, ...caps(25 * k, color, 0.14), opacity: p,
      padding: `${10 * k}px ${12 * k}px`, borderRadius: 6 * k, background: "rgba(10,8,7,.72)" }}>{txt}</div>
  );
  return (
    <AbsoluteFill>
      {sound}
      <Stage ov={overlay} p={inOf(f, 0, 10 * S) * (1 - out)} tone={0.9} />
      <AbsoluteFill style={{ opacity: 1 - out, transform: `translateY(${((1 - sectionP) * 40 * k - out * 18 * k).toFixed(1)}px)` }}>
        <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
          <defs>
            <linearGradient id={`${id}rock`} x1="0" y1={T} x2="0" y2={height} gradientUnits="userSpaceOnUse">
              <stop offset="0" stopColor="#9a6741" />
              <stop offset="0.35" stopColor="#6d4429" />
              <stop offset="1" stopColor="#24160e" />
            </linearGradient>
            <linearGradient id={`${id}water`} x1="0" y1={wy} x2="0" y2={B} gradientUnits="userSpaceOnUse">
              <stop offset="0" stopColor="#4a9ad3" />
              <stop offset="0.3" stopColor="#226398" />
              <stop offset="1" stopColor="#0a2440" />
            </linearGradient>
            <linearGradient id={`${id}air`} x1="0" y1={T} x2="0" y2={B} gradientUnits="userSpaceOnUse">
              <stop offset="0" stopColor="rgba(150,180,215,.10)" />
              <stop offset="1" stopColor="rgba(150,180,215,0)" />
            </linearGradient>
            <linearGradient id={`${id}sky`} x1="0" y1="0" x2="0" y2={B} gradientUnits="userSpaceOnUse">
              <stop offset="0" stopColor="rgba(8,12,20,.55)" />
              <stop offset="0.6" stopColor="rgba(16,24,36,.78)" />
              <stop offset="1" stopColor="rgba(22,30,42,.85)" />
            </linearGradient>
            <linearGradient id={`${id}fade`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#fff" />
              <stop offset="0.8" stopColor="#fff" />
              <stop offset="1" stopColor="#000" />
            </linearGradient>
            <mask id={`${id}m`} maskUnits="userSpaceOnUse" x={0} y={0} width={width} height={height}>
              <rect x={-60 * kw} y={T - 40 * kw} width={width + 120 * kw} height={height} fill={`url(#${id}fade)`} />
            </mask>
            <clipPath id={`${id}c`}><path d={canyon} /></clipPath>
            <clipPath id={`${id}r`}><path d={rockD} /></clipPath>
            <clipPath id={`${id}band`}><rect x={0} y={ringTop} width={width} height={Math.max(0, wy - ringTop)} /></clipPath>
            <filter id={`${id}rough`} x="-5%" y="-5%" width="110%" height="110%">
              <feTurbulence type="fractalNoise" baseFrequency={0.03} numOctaves={3} seed={11} result="n" />
              <feDisplacementMap in="SourceGraphic" in2="n" scale={10 * k} xChannelSelector="R" yChannelSelector="G" />
            </filter>
            <filter id={`${id}tex`} x="0" y="0" width="100%" height="100%">
              <feTurbulence type="fractalNoise" baseFrequency="0.01 0.08" numOctaves={3} seed={5} />
              <feColorMatrix type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 0.6 -0.14" />
            </filter>
          </defs>
          <rect x={0} y={0} width={width} height={B} fill={`url(#${id}sky)`} opacity={sectionP} />
          <g mask={`url(#${id}m)`}>
            <path d={canyon} fill={`url(#${id}air)`} />
            {/* the rock, its strata and grain */}
            <g filter={`url(#${id}rough)`}>
              <path d={rockD} fill={`url(#${id}rock)`} />
              <g clipPath={`url(#${id}r)`}>
                {strata.map((s, i) => (
                  <rect key={i} x={-60 * kw} y={T + s * (B - T)} width={width + 120 * kw} height={(2.5 + (i % 3) * 2.2) * k}
                    fill={i % 2 ? "rgba(255,226,190,.12)" : "rgba(0,0,0,.2)"} />
                ))}
                <rect x={-60 * kw} y={T} width={width + 120 * kw} height={height} filter={`url(#${id}tex)`} opacity={0.55} />
                <rect x={-60 * kw} y={T - 2 * k} width={width + 120 * kw} height={10 * k} fill="rgba(255,214,170,.22)" />
              </g>
            </g>
            {/* the bathtub ring: the walls the water has left, pale */}
            {ringP > 0 ? (
              <g clipPath={`url(#${id}band)`} opacity={ringP}>
                <g clipPath={`url(#${id}r)`}>
                  <path d={canyon} fill="none" stroke="#efe6d3" strokeWidth={24 * k} filter={`url(#${id}rough)`} opacity={0.92} />
                </g>
              </g>
            ) : null}
            {/* water */}
            <g clipPath={`url(#${id}c)`}>
              <path d={water} fill={`url(#${id}water)`} opacity={0.97} />
              <path d={surface} fill="none" stroke="rgba(196,232,255,.95)" strokeWidth={2.8 * k} />
            </g>
          </g>
          {/* full pool and thresholds, dashed across to the labels */}
          {plan.full !== null ? (
            <line x1={px(0.06)} x2={colR} y1={fullY} y2={fullY} stroke="rgba(255,255,255,.75)" strokeWidth={2.2 * k}
              strokeDasharray={dash} opacity={lineP} />
          ) : null}
          {plan.thresholds.map((th, i) => (
            <line key={i} x1={px(0.3)} x2={colR} y1={Y(th.value)} y2={Y(th.value)} stroke={rgba(hot, 0.9)} strokeWidth={2.2 * k}
              strokeDasharray={dash} opacity={inOf(f, (10 + i * 3) * S, 12 * S)} />
          ))}
          {/* the level, across to its plate */}
          <line x1={px(0.62)} x2={colR - 330 * k} y1={wy} y2={wy} stroke={WHITE} strokeWidth={2.6 * k}
            opacity={inOf(f, RES.moveAt * S, 8 * S)} />
          <circle cx={colR - 330 * k} cy={wy} r={7 * k} fill={WHITE} opacity={inOf(f, RES.moveAt * S, 8 * S)}
            style={{ filter: `drop-shadow(0 0 ${8 * k}px ${hot})` }} />
          {/* the drop from full pool, bracketed */}
          {showDrop ? (
            <g opacity={landP}>
              <line x1={bx} x2={bx} y1={fullY + 4 * k} y2={Y(plan.v) - 14 * k} stroke={hot} strokeWidth={3.2 * k} />
              <path d={`M${bx - 11 * k} ${Y(plan.v) - 20 * k} L${bx} ${Y(plan.v) - 3 * k} L${bx + 11 * k} ${Y(plan.v) - 20 * k}`}
                fill="none" stroke={hot} strokeWidth={3.2 * k} strokeLinejoin="round" strokeLinecap="round" />
              <line x1={bx - 14 * k} x2={bx + 14 * k} y1={fullY} y2={fullY} stroke={hot} strokeWidth={3.2 * k} />
            </g>
          ) : null}
        </svg>
        {plan.full !== null ? capsLine(`FULL POOL · ${unitTxt(plan.full)}`, WHITE, yOf("full") ?? fullY, lineP) : null}
        {plan.thresholds.map((th, i) => (
          <React.Fragment key={i}>
            {capsLine(`${clip(th.label, 26).toUpperCase()} · ${unitTxt(th.value)}`, hot, yOf(`th${i}`) ?? Y(th.value),
              inOf(f, (10 + i * 3) * S, 12 * S))}
          </React.Fragment>
        ))}
        <div style={{ position: "absolute", right: width - colR, top: levelTop, display: "flex", flexDirection: "column",
          alignItems: "flex-end", opacity: inOf(f, RES.moveAt * S, 8 * S) }}>
          <div style={{ display: "inline-flex", alignItems: "baseline", padding: `${12 * k}px ${20 * k}px`, borderRadius: 8 * k,
            background: "rgba(8,10,14,.86)", border: `${Math.max(1, 1.4 * k)}px solid rgba(255,255,255,.16)`,
            boxShadow: `0 ${12 * k}px ${34 * k}px rgba(0,0,0,.5)` }}>
            <FigureText fig={fig} text={figNow} size={valSize} unitColor={hot} />
          </div>
          {label ? <div style={{ ...caps(25 * k, WHITE, 0.16), marginTop: 14 * k, opacity: landP, textShadow: lift(k, 0.7) }}>{label}</div> : null}
          {showDrop && !bigGap ? (
            <div style={{ ...caps(23 * k, hot, 0.12), marginTop: 10 * k, opacity: landP, textShadow: lift(k, 0.7) }}>
              {`${dropText} ${dropWords}`}
            </div>
          ) : null}
        </div>
        {showDrop && plan.change !== null && bigGap ? (
          <div style={{ position: "absolute", left: bx + 22 * k, top: (fullY + Y(plan.v)) / 2 - 34 * k, opacity: landP,
            transform: `translateX(${((1 - landP) * -12 * k).toFixed(1)}px)` }}>
            <div style={{ ...heavy(48 * k, hot), textShadow: lift(k, 0.7) }}>{dropText}</div>
            <div style={{ ...caps(20 * k, WHITE, 0.14), marginTop: 8 * k, textShadow: lift(k, 0.8) }}>{dropWords}</div>
          </div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/** Exported for the planner's twin tests (proFormat covers the rest). */
export const _rowsForTests = (ov: Overlay): Row[] => rowsOf(ov.items, 12);

export const LOOKS: Record<string, Look> = {
  "dx-line-endpoint": guard(LineEndpoint),
  "dx-ghost-bars": guard(GhostBars),
  "dx-nested-squares": guard(NestedSquares),
  "dx-unit-split": guard(UnitSplit),
  "dx-filled-figure": guard(FilledFigure),
  "dx-capacity-gauge": guard(CapacityGauge),
  "dx-drum-counter": guard(DrumCounter),
  "dx-reservoir-section": guard(ReservoirSection),
};
