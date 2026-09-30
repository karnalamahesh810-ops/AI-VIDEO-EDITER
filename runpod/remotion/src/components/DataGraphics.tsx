import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { TEXT_SHADOW, formatNumber, useOverlayAnim, useScale } from "./layout";
import { INTER, SERIF, SERIF_ITALIC, TYPEWRITER } from "./fonts";
import { useK } from "./pro/ProGraphics";
import { EASE, F, boldCaps, bright, caps, fit, str, tween, useExit } from "./pro/Kit";
import type { Overlay } from "../types";

/**
 * VidRush's data and sequence graphics, read off their exports:
 *   line-chart      a line drawing itself under a caps title
 *   path-steps      a red curve through numbered stops ("1 Cambridge", "2 ...")
 *   progress-steps  dots along a rule, the last one lit, "A -> B" under it
 *   span            two dated tags joined by a dotted rule, the span above
 *   icon-pop        one pictogram in a ring popping in, a caption under it
 */

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const ease = (frame: number, at: number, frames: number) =>
  interpolate(frame, [at, at + Math.max(1, frames)], [0, 1], {
    ...clamp,
    easing: (t) => 1 - Math.pow(1 - t, 3),
  });
const SHADE = "rgba(8,9,12,0.82)";

export const LineChart: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(10, 10);
  const s = useScale();
  const pts = (overlay.items || []).filter((i) => typeof i.value === "number").slice(0, 12);
  const W = 1400, H = 520;
  const vals = pts.map((p) => p.value as number);
  const lo = Math.min(0, ...vals), hi = Math.max(...vals, 1);
  const xy = pts.map((p, i) => [
    (i / Math.max(1, pts.length - 1)) * W,
    H - (((p.value as number) - lo) / (hi - lo || 1)) * H,
  ]);
  const d = xy.map(([x, y], i) => `${i ? "L" : "M"} ${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const draw = ease(frame, fps * 0.3, fps * 1.4);
  const last = pts[pts.length - 1];
  return (
    <AbsoluteFill style={{ opacity, background: SHADE, alignItems: "center", justifyContent: "center" }}>
      <div style={{ fontFamily: INTER, fontWeight: 700, fontSize: s(40), letterSpacing: "0.06em",
        color: "#fff", textTransform: "uppercase", marginBottom: s(40) }}>{overlay.text}</div>
      <svg width={s(W + 80)} height={s(H + 80)} viewBox={`-40 -40 ${W + 80} ${H + 80}`}>
        <line x1={0} y1={H} x2={W} y2={H} stroke="rgba(255,255,255,.35)" strokeWidth={2} />
        <line x1={0} y1={0} x2={0} y2={H} stroke="rgba(255,255,255,.2)" strokeWidth={2} />
        <path d={d} fill="none" stroke={accent || "#d62828"} strokeWidth={6} strokeLinejoin="round"
          pathLength={1} strokeDasharray={1} strokeDashoffset={1 - draw} />
        {pts.map((p, i) => (
          <text key={i} x={xy[i][0]} y={H + 34} fill="rgba(255,255,255,.7)" fontSize={24}
            fontFamily={INTER} textAnchor="middle" opacity={ease(frame, fps * 0.2 + i * 2, 6)}>
            {p.label}
          </text>
        ))}
        {last && draw > 0.98 ? (
          <text x={xy[xy.length - 1][0]} y={xy[xy.length - 1][1] - 18} fill="#fff" fontSize={40}
            fontFamily={SERIF_ITALIC} textAnchor="end">
            {formatNumber(last.value as number)}{overlay.suffix || ""}
          </text>
        ) : null}
      </svg>
    </AbsoluteFill>
  );
};

export const PathSteps: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, opacity, durationInFrames } = useOverlayAnim(10, 10);
  const s = useScale();
  const items = (overlay.items || []).slice(0, 4);
  const n = Math.max(2, items.length);
  // A loose S through the frame, like their hand-drawn red route.
  const stops = Array.from({ length: n }, (_, i) => {
    const t = i / (n - 1);
    return [220 + t * 1480, i % 2 ? 330 : 760];
  });
  const d = stops.map(([x, y], i) => {
    if (!i) return `M ${x} ${y}`;
    const [px, py] = stops[i - 1];
    return `C ${px + 320} ${py}, ${x - 320} ${y}, ${x} ${y}`;
  }).join(" ");
  const draw = ease(frame, fps * 0.2, Math.min(fps * 1.6, durationInFrames * 0.6));
  return (
    <AbsoluteFill style={{ opacity, background: "radial-gradient(ellipse at 50% 50%, rgba(40,6,6,.78), rgba(5,5,6,.9))" }}>
      {overlay.text ? (
        <div style={{ position: "absolute", top: s(70), width: "100%", textAlign: "center", fontFamily: SERIF,
          fontSize: s(84), color: "#fff", textShadow: TEXT_SHADOW, textTransform: "uppercase" }}>{overlay.text}</div>
      ) : null}
      <svg width="100%" height="100%" viewBox="0 0 1920 1080" style={{ position: "absolute", inset: 0 }}>
        <path d={d} fill="none" stroke={accent || "#d62828"} strokeWidth={4} pathLength={1}
          strokeDasharray={1} strokeDashoffset={1 - draw} />
        {stops.map(([x, y], i) => {
          const on = ease(frame, fps * 0.2 + (i / (n - 1)) * Math.min(fps * 1.6, durationInFrames * 0.6), 5);
          return (
            <g key={i} opacity={on}>
              <circle cx={x} cy={y} r={20} fill={accent || "#e53935"} />
              <circle cx={x} cy={y} r={34} fill={accent || "#e53935"} opacity={0.25} />
              <text x={i === n - 1 ? x - 44 : x + 44} y={y - 30} fill="#fff" fontFamily={SERIF_ITALIC}
                fontSize={72} textAnchor={i === n - 1 ? "end" : "start"}>{i + 1}</text>
              <text x={i === n - 1 ? x - 44 : x + 44} y={y + 30} fill="rgba(255,255,255,.92)"
                fontFamily={SERIF} fontSize={42} textAnchor={i === n - 1 ? "end" : "start"}>
                {items[i]?.label || items[i]?.text || ""}
              </text>
            </g>
          );
        })}
      </svg>
    </AbsoluteFill>
  );
};

/**
 * TL_PROGRESS_STEPS_V1, rebuilt 2026-09-30: a change told in two to four
 * steps across the frame. The title sits top-left in outlined bold caps; a
 * thick outlined rail draws across, and an accent fill travels along it from
 * node to node: each node pops (numbered), its label rises under it in
 * outlined bold caps; the last node glows in the accent and pulses. Labels
 * are fitted to their column (two lines at most). Everything leaves in the
 * last 12 frames, right to left.
 */
export const ProgressSteps: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const q = useExit(12);
  const items = (overlay.items || []).map((it) => str(it.label) || str(it.text)).filter(Boolean).slice(0, 4);
  if (items.length < 2) return null;
  const n = items.length;
  const hot = bright(accent);
  // Each label owns a column; the outer columns end at the 96 px margins, so nothing can clip.
  const col = Math.min(480 * k, ((width - 192 * k) / n) * 0.94);
  const X0 = 96 * k + col / 2, X1 = width - 96 * k - col / 2;
  const cy = height * 0.5;
  const xs = items.map((_, i) => X0 + ((X1 - X0) * i) / (n - 1));
  const fits = items.map((t) => fit(t.toUpperCase(), F.label, 64 * k, 36 * k, col, 2, 0.02));
  const size = Math.min(...fits.map((f) => f.size));
  const rows = items.map((t) => fit(t.toUpperCase(), F.label, size, size, col, 2, 0.02));
  const title = fit(caps(overlay.text), F.label, 84 * k, 48 * k, width - 240 * k, 1, 0.02);
  const railP = tween(frame, 2, 16, EASE.inOut);
  const step = Math.max(8, Math.min(Math.round(fps * 0.5), Math.floor((D * 0.5) / n)));
  const nodeAt = (i: number) => 10 + i * step;
  // The accent fill runs from node to node as each one lands.
  const fillX = (() => {
    let x = X0;
    for (let i = 1; i < n; i++) x += (xs[i] - xs[i - 1]) * tween(frame, nodeAt(i) - 8, 8, EASE.inOut);
    return x;
  })();
  const R = 30 * k;
  return (
    <AbsoluteFill>
      {title.lines.length ? (
        <div style={{ position: "absolute", left: 120 * k, top: height * 0.2, ...boldCaps(title.size, "#fff", k, 0.02),
          clipPath: `inset(-20% ${((1 - tween(frame, 0, 14)) * 100).toFixed(2)}% -20% 0)`, opacity: 1 - q }}>{title.lines[0]}</div>
      ) : null}
      <div style={{ position: "absolute", left: X0, top: cy - 7 * k, height: 14 * k, width: (X1 - X0) * railP * (1 - q), borderRadius: 7 * k,
        background: "rgba(255,255,255,.9)", boxShadow: `0 0 0 ${3 * k}px #000, 0 10px 30px rgba(0,0,0,.5)` }} />
      <div style={{ position: "absolute", left: X0, top: cy - 7 * k, height: 14 * k, width: Math.max(0, fillX - X0) * (1 - q), borderRadius: 7 * k,
        background: hot, boxShadow: `0 0 ${18 * k}px ${hot}` }} />
      {items.map((_, i) => {
        const at = nodeAt(i);
        const pop = tween(frame, at, 14, EASE.back);
        const qi = tween(frame, D - 13 + (n - 1 - i) * 1.2, 9, EASE.in);
        const last = i === n - 1;
        const lit = frame >= at;
        const pulse = last && lit ? 1 + 0.08 * Math.sin((frame - at) * 0.25) : 1;
        return (
          <React.Fragment key={i}>
            <div style={{ position: "absolute", left: xs[i] - R, top: cy - R, width: 2 * R, height: 2 * R, borderRadius: "50%",
              background: lit ? (last ? hot : "#fff") : "#fff", display: "flex", alignItems: "center", justifyContent: "center",
              transform: `scale(${(pop * (1 - qi) * pulse).toFixed(4)})`,
              boxShadow: `0 0 0 ${4 * k}px #000${last ? `, 0 0 ${30 * k}px ${hot}` : ""}` }}>
              <span style={{ fontFamily: INTER, fontWeight: 800, fontSize: 30 * k, color: last ? "#fff" : "#000", lineHeight: 1 }}>{i + 1}</span>
            </div>
            <div style={{ position: "absolute", left: xs[i] - col / 2, width: col, top: cy + R + 26 * k, display: "flex",
              flexDirection: "column", alignItems: "center" }}>
              {rows[i].lines.map((ln, j) => {
                const lp = tween(frame, at + 3 + j * 3, 14);
                return (
                  <div key={j} style={{ ...boldCaps(size, last ? hot : "#fff", k, 0.02),
                    transform: `translateY(${((1 - lp) * 30 * k + qi * 30 * k).toFixed(2)}px)`, opacity: Math.min(1, lp * 2) * (1 - qi) }}>{ln}</div>
                );
              })}
            </div>
          </React.Fragment>
        );
      })}
    </AbsoluteFill>
  );
};

export const Span: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(10, 10);
  const s = useScale();
  const [a, b] = [overlay.items?.[0], overlay.items?.[1]];
  const rule = ease(frame, fps * 0.3, fps * 0.8);
  const tag = (it: typeof a, side: "left" | "right", at: number) => (
    <div style={{ position: "absolute", [side]: "12%", top: "44%", opacity: ease(frame, at, 6),
      transform: "translateY(-50%)", textAlign: side === "left" ? "left" : "right" }}>
      <div style={{ display: "inline-block", background: "#f4f1ea", color: "#111", fontFamily: TYPEWRITER,
        fontWeight: 700, fontSize: s(36), padding: `${s(4)}px ${s(14)}px` }}>{it?.label}</div>
      <div style={{ fontFamily: TYPEWRITER, fontWeight: 700, fontSize: s(28), color: accent || "#e05a2a",
        marginTop: s(12), textTransform: "uppercase" }}>{it?.text}</div>
    </div>
  );
  return (
    <AbsoluteFill style={{ opacity, background: "rgba(6,7,9,.72)", backgroundImage:
      "linear-gradient(rgba(255,255,255,.05) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.05) 1px, transparent 1px)",
      backgroundSize: `${s(60)}px ${s(60)}px` }}>
      <div style={{ position: "absolute", top: "30%", width: "100%", textAlign: "center", fontFamily: TYPEWRITER,
        fontWeight: 700, fontSize: s(64), color: "#fff", opacity: ease(frame, fps * 0.9, 8) }}>{overlay.text}</div>
      <div style={{ position: "absolute", top: "44%", left: "14%", width: `${72 * rule}%`,
        borderTop: `${s(3)}px dotted rgba(255,255,255,.75)` }} />
      {tag(a, "left", fps * 0.2)}
      {tag(b, "right", fps * 0.9)}
    </AbsoluteFill>
  );
};

/** Simple line pictograms, drawn in-house so no icon font or network is needed. */
export const ICONS: Record<string, string> = {
  fuel: "M14 10h26v44H14z M14 26h26 M40 18l10 8v22a4 4 0 0 1-8 0V36h-2",
  water: "M32 8C22 24 16 32 16 40a16 16 0 0 0 32 0c0-8-6-16-16-32z",
  home: "M10 30L32 12l22 18 M16 26v28h32V26 M27 54V40h10v14",
  warning: "M32 8L58 54H6z M32 24v14 M32 44v4",
  fire: "M32 56c-12 0-18-8-18-18 0-10 8-14 10-24 6 6 8 10 8 16 4-2 6-6 6-10 6 6 12 12 12 20 0 10-6 16-18 16z",
  car: "M8 40l6-14h36l6 14v10H8z M18 50v4 M46 50v4 M8 40h48",
  money: "M8 18h48v28H8z M32 24a8 8 0 1 0 0 16 8 8 0 1 0 0-16",
  school: "M4 24L32 12l28 12-28 12z M14 28v14c10 8 26 8 36 0V28",
  hospital: "M12 12h40v40H12z M32 20v24 M20 32h24",
  phone: "M22 6h20v52H22z M30 50h4",
  clock: "M32 8a24 24 0 1 0 0 48 24 24 0 1 0 0-48 M32 18v14l10 6",
  thermometer: "M28 8h8v30a10 10 0 1 1-8 0z",
  document: "M16 6h22l10 10v42H16z M38 6v10h10 M22 28h20 M22 36h20 M22 44h14",
  people: "M22 24a7 7 0 1 0 0-.1 M42 24a7 7 0 1 0 0-.1 M10 50c2-10 22-10 24 0 M30 50c2-10 22-10 24 0",
};

/**
 * CALL_ICON_POP_V1, rebuilt 2026-09-30 in the owner's text language: low on
 * the left, an accent ring draws round a pictogram whose thick white strokes
 * (outlined in black, so they read on any footage) draw themselves on while
 * the ring pops; the caption rises beside it in big outlined bold caps, the
 * label (overlay.label) under it in the accent. No dark blob behind. It all
 * drops away in the last 12 frames.
 */
export const IconPop: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const k = useK();
  const q = useExit(12);
  const hot = bright(accent);
  const icon = ICONS[overlay.variant || ""] || ICONS.warning;
  const pop = tween(frame, 0, 16, EASE.back) * (1 - q);
  const ring = tween(frame, 2, 18, EASE.inOut);
  const draw = tween(frame, 6, 20, EASE.inOut);
  const S = 190 * k;
  const room = Math.min(1100 * k, width - 96 * k * 2 - S - 40 * k);
  const cap1 = fit(caps(overlay.text), F.label, 96 * k, 52 * k, room, 2, 0.02);
  const cap2 = fit(caps(overlay.label), F.label, 52 * k, 34 * k, room, 1, 0.06);
  const top = height * 0.7 - S;
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: 96 * k, top, display: "flex", alignItems: "center", gap: 36 * k }}>
        <div style={{ position: "relative", width: S, height: S, flexShrink: 0, transform: `scale(${(0.6 + 0.4 * pop).toFixed(4)})`,
          opacity: Math.min(1, pop * 3) }}>
          <svg width={S} height={S} viewBox="0 0 100 100" style={{ position: "absolute", inset: 0, overflow: "visible" }}>
            <circle cx={50} cy={50} r={45} fill="none" stroke="#000" strokeWidth={9} pathLength={1} strokeDasharray={1}
              strokeDashoffset={1 - ring} transform="rotate(-90 50 50)" />
            <circle cx={50} cy={50} r={45} fill="none" stroke={hot} strokeWidth={5} pathLength={1} strokeDasharray={1}
              strokeDashoffset={1 - ring} transform="rotate(-90 50 50)" style={{ filter: `drop-shadow(0 0 ${6 * k}px ${hot})` }} />
            <g transform="translate(18 18)">
              <path d={icon} fill="none" stroke="#000" strokeWidth={8.5} strokeLinecap="round" strokeLinejoin="round"
                pathLength={1} strokeDasharray={1} strokeDashoffset={1 - draw} />
              <path d={icon} fill="none" stroke="#fff" strokeWidth={4.6} strokeLinecap="round" strokeLinejoin="round"
                pathLength={1} strokeDasharray={1} strokeDashoffset={1 - draw} />
            </g>
          </svg>
        </div>
        <div>
          {cap1.lines.map((ln, i) => {
            const lp = tween(frame, 8 + i * 4, 14);
            return (
              <div key={i} style={{ ...boldCaps(cap1.size, "#fff", k, 0.02), transform: `translateY(${((1 - lp) * 30 * k + q * 30 * k).toFixed(2)}px)`,
                opacity: Math.min(1, lp * 2) * (1 - q) }}>{ln}</div>
            );
          })}
          {cap2.lines.length ? (
            <div style={{ ...boldCaps(cap2.size, hot, k, 0.06), marginTop: 6 * k, opacity: tween(frame, 16, 10) * (1 - q),
              transform: `translateY(${((1 - tween(frame, 16, 14)) * 20 * k).toFixed(2)}px)` }}>{cap2.lines[0]}</div>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const ICON_NAMES = Object.keys(ICONS);
