import React from "react";
import { AbsoluteFill, Img } from "remotion";
import { geoCentroid, geoInterpolate, geoMercator, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import worldTopology from "world-atlas/countries-110m.json";
import statesTopology from "../../data/us-states.json";
import type { Overlay } from "../../types";
import { LABEL, SERIF } from "../fonts";
import {
  ANTON, INTER, SUBLINE, Grain, Pool, Stage, Vignette, caps, clamp01, easeInOut, easeOut, exitOf, expoOut, fit,
  guard, hash, heavy, hotOf, inOf, lerp, lift, mixHex, rgba, rnd, textWidth, useBase, useSvgId, type CSS, type Face,
  type Look,
} from "./proKit";
import {
  countText, distanceText, figureOf, milesBetween, num, percentChange, placeName, placesOf, rowsOf, seriesScale, str,
  unitsOf,
} from "./proFormat";

/**
 * PREMIUM (family "pr-"): five looks a human documentary editor would cut
 * (the owner, 2026-10-05: "document animations with the photos, zoom and
 * circles - I like that ... professional editor quality, not cheap"):
 *
 *   pr-doc-spotlight   a document set in real type on a dark desk; the camera
 *                      pushes in to the line that matters, a hand-drawn loop
 *                      circles its key words and a callout names them
 *   pr-photo-focus     a still; the camera eases in on its subject, the rest
 *                      falls back into shade, a ring draws round it and a
 *                      label names it (only when the line names it)
 *   pr-graph-build     the narration's figures as a line or bar chart that
 *                      draws in, each value counting up as it lands, the key
 *                      point (the last, or the largest) ringed and called out
 *   pr-map-path        two places on a dark vector map: the camera travels
 *                      from the first to a view of both while the route
 *                      draws between them, pins, names and the distance
 *   pr-number-reveal   one big figure counting up with its unit and a single
 *                      line of what it means, low on the footage
 *
 * The type system (components/fonts.ts): Anton for the figures and words
 * that carry a line, Barlow Condensed for labels and callouts, Inter Tight
 * for small tracked lines, Source Serif 4 for print. One accent (the
 * overlay's theme colour) on white type and near-black glass. Motion is
 * eased (expo-out entrances, cubic in-out camera moves), nothing jitters,
 * every element leaves in a clean 14-frame exit. Only the plan's words are
 * set; a look missing what it needs draws nothing.
 */

const DARK = "#07090c";
const GLASS = "rgba(9,11,15,0.86)";
const PAPER = "#f2eee5";
const PAPER_INK = "#191b20";
const PAPER_SOFT = "#5a5c62";

// ------------------------------------------------------------------ shared drawing
/**
 * A loop drawn by hand round (cx, cy): a little over one turn, the radius
 * wandering a few percent, the end crossing past the start - the marker
 * circle an editor draws on a still. Deterministic for a seed.
 */
const loopPath = (cx: number, cy: number, rx: number, ry: number, seed: number): string => {
  const n = 72;
  const turns = 1.1;
  const a0 = -Math.PI * 0.72 + rnd(seed) * 0.35;
  const ph = rnd(seed + 7) * Math.PI * 2;
  const pts: string[] = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n;
    const a = a0 + t * turns * Math.PI * 2;
    const wob = 1 + 0.03 * Math.sin(t * Math.PI * 3 + ph) + 0.045 * (t - 0.5);
    const x = cx + Math.cos(a) * rx * wob;
    const y = cy + Math.sin(a) * ry * wob * (1 + 0.015 * Math.sin(t * 9 + ph));
    pts.push(`${x.toFixed(1)},${y.toFixed(1)}`);
  }
  return `M${pts[0]} L${pts.slice(1).join(" ")}`;
};

/** A hand underline under x0..x1 at y: a slight arc, ends lifting. */
const underPath = (x0: number, x1: number, y: number, seed: number, k: number): string => {
  const sag = (3 + rnd(seed) * 3) * k;
  const lift0 = (rnd(seed + 1) * 4 - 2) * k;
  return `M${x0.toFixed(1)},${(y + lift0).toFixed(1)} Q${((x0 + x1) / 2).toFixed(1)},${(y + sag).toFixed(1)} `
    + `${x1.toFixed(1)},${(y - 2 * k).toFixed(1)}`;
};

/** A drawn stroke: `p` 0..1 of its length shown. */
const Stroke: React.FC<{ d: string; p: number; color: string; width: number; shadow?: boolean }> =
  ({ d, p, color, width, shadow = true }) => (p <= 0 ? null : (
    <path d={d} pathLength={1} fill="none" stroke={color} strokeWidth={width} strokeLinecap="round" strokeLinejoin="round"
      strokeDasharray="1 1" strokeDashoffset={1 - clamp01(p)}
      style={shadow ? { filter: `drop-shadow(0 ${(width * 0.35).toFixed(1)}px ${(width * 0.9).toFixed(1)}px rgba(0,0,0,.55))` }
        : undefined} />
  ));

/** A callout: a near-black glass plate with the accent edge, a line in condensed caps and a small line under it. */
const Callout: React.FC<{ x: number; y: number; text: string; sub?: string; p: number; hot: string; k: number;
  align?: "left" | "right"; size?: number }> = ({ x, y, text, sub, p, hot, k, align = "left", size = 38 }) => {
  if (!text || p <= 0) return null;
  const s = size * k;
  const face: Face = { font: LABEL, weight: 700, tracking: 0.03 };
  const f = fit(text.toUpperCase(), face, 560 * k, s, s * 0.72, 2);
  const w = Math.max(f.width, sub ? textWidth(sub.toUpperCase(), SUBLINE, 19 * k, 700, 0.16) : 0) + 44 * k;
  const left = align === "left" ? x : x - w;
  const q = easeOut(p);
  return (
    <div style={{ position: "absolute", left, top: y, width: w, padding: `${14 * k}px ${22 * k}px ${16 * k}px`,
      background: GLASS, borderLeft: align === "left" ? `${6 * k}px solid ${hot}` : undefined,
      borderRight: align === "right" ? `${6 * k}px solid ${hot}` : undefined, borderRadius: 4 * k,
      boxShadow: `0 ${14 * k}px ${40 * k}px rgba(0,0,0,.5)`, opacity: q,
      transform: `translateX(${((1 - q) * (align === "left" ? -18 : 18) * k).toFixed(1)}px)`,
      clipPath: `inset(0 ${align === "left" ? ((1 - q) * 100).toFixed(1) : 0}% 0 ${align === "right" ? ((1 - q) * 100).toFixed(1) : 0}%)` }}>
      {f.lines.map((ln, i) => (
        <div key={i} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: f.size, lineHeight: 1.04, letterSpacing: "0.03em",
          color: "#fff", whiteSpace: "nowrap", textAlign: align }}>{ln}</div>
      ))}
      {sub ? <div style={{ ...caps(19 * k, "rgba(255,255,255,.72)", 0.16), marginTop: 8 * k, textAlign: align }}>{sub}</div> : null}
    </div>
  );
};

const words = (s: string) => s.split(/\s+/).filter(Boolean);
const normW = (w: string) => w.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");

// ================================================================== pr-photo-focus
/**
 * The still fills the frame and drifts; from frame 10 the camera eases in on
 * its subject (the overlay's anchor when a review set one, else the centre
 * of the frame, where a photo keeps its subject), the edges fall back into
 * shade, a hand-drawn ring circles the subject (frame 34 -> 56, the marker
 * sound on 36) and a callout names it (frame 54) when the plan named it.
 */
const PhotoFocus: Look = ({ overlay, accent }) => {
  const { f, S, k, width: W, height: H, dur } = useBase();
  const pic = (overlay.media || []).find((m) => m && m.url);
  if (!pic) return null;
  const hot = hotOf(accent);
  // The subject: the anchor vision found for it (src/marks.py: x, y, and its size r or w / h), else the centre.
  const an = (overlay.anchor || {}) as { x?: number; y?: number; r?: number; w?: number; h?: number };
  const found = typeof an.x === "number" && typeof an.y === "number";
  const fx = found ? Math.max(0.14, Math.min(0.86, an.x as number)) : 0.5;
  const fy = found ? Math.max(0.16, Math.min(0.84, an.y as number)) : 0.46;
  const enter = inOf(f, 0, 12 * S, easeOut);
  const push = inOf(f, 10 * S, 48 * S, easeInOut);
  const hold = clamp01((f - 58 * S) / Math.max(1, dur - 58 * S));
  const scale = 1.03 + 0.27 * push + 0.035 * hold;
  const ring = inOf(f, 34 * S, 22 * S, easeInOut);
  const dim = inOf(f, 28 * S, 20 * S);
  const lab = inOf(f, 54 * S, 16 * S);
  const out = exitOf(f, dur, S, 14);
  const cx = fx * W, cy = fy * H;
  // The ring round the subject as it stands once the camera has pushed in (it stays where it is: the zoom is about it).
  const grow = 1.03 + 0.27;
  const R = Math.max(120 * k, Math.min(330 * k, typeof an.w === "number" ? an.w * W * 0.58 * grow
    : typeof an.r === "number" ? an.r * H * 1.15 * grow : 200 * k));
  const RY = Math.max(100 * k, Math.min(300 * k, typeof an.h === "number" ? an.h * H * 0.58 * grow
    : typeof an.r === "number" ? an.r * H * 1.0 * grow : 168 * k));
  const seed = hash(str(overlay.text) || pic.url || "pr");
  const text = str(overlay.text);
  const sub = str(overlay.subtitle) || str(overlay.label);
  const right = fx <= 0.55;
  const lx = right ? cx + R + 70 * k : cx - R - 70 * k;
  const ly = fy > 0.6 ? cy - RY - 110 * k : cy - RY * 0.55;
  return (
    <AbsoluteFill style={{ background: DARK, opacity: enter * (1 - out) }}>
      <AbsoluteFill style={{ transform: `scale(${scale.toFixed(4)})`, transformOrigin: `${(fx * 100).toFixed(2)}% ${(fy * 100).toFixed(2)}%` }}>
        <Img src={pic.url} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      </AbsoluteFill>
      <AbsoluteFill style={{ opacity: dim, background: `radial-gradient(ellipse ${(R * 1.7).toFixed(0)}px ${(RY * 1.75).toFixed(0)}px `
        + `at ${cx.toFixed(0)}px ${cy.toFixed(0)}px, rgba(0,0,0,0) 52%, rgba(3,4,6,.66) 100%)` }} />
      <Vignette strength={0.42} />
      <svg width={W} height={H} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
        <Stroke d={loopPath(cx, cy, R, RY, seed)} p={ring} color={hot} width={7 * k} />
        {text ? (
          <Stroke d={`M${(right ? cx + R * 0.98 : cx - R * 0.98).toFixed(1)},${(cy - RY * 0.18).toFixed(1)} `
            + `L${(lx + (right ? -6 : 6) * k).toFixed(1)},${(ly + 34 * k).toFixed(1)}`} p={inOf(f, 50 * S, 10 * S)}
            color="rgba(255,255,255,.92)" width={3 * k} />
        ) : null}
      </svg>
      {text ? <Callout x={lx} y={ly} text={text} sub={sub} p={lab} hot={hot} k={k} align={right ? "left" : "right"} /> : null}
      <Grain opacity={0.045} />
    </AbsoluteFill>
  );
};

// ================================================================== pr-doc-spotlight
/** Where the highlighted words sit on the laid-out lines: per line, [x0, x1] in px from the line's start. */
const spansOf = (lines: string[], hl: string, face: Face, size: number): { line: number; x0: number; x1: number }[] => {
  const want = words(hl).map(normW).filter(Boolean);
  if (!want.length) return [];
  const flat: { line: number; idx: number; w: string }[] = [];
  lines.forEach((ln, li) => words(ln).forEach((w, wi) => flat.push({ line: li, idx: wi, w: normW(w) })));
  let at = -1;
  for (let i = 0; i + want.length <= flat.length && at < 0; i++) {
    if (want.every((w, j) => flat[i + j].w === w)) at = i;
  }
  if (at < 0) return [];
  const out: { line: number; x0: number; x1: number }[] = [];
  for (let j = 0; j < want.length; j++) {
    const { line, idx } = flat[at + j];
    const ws = words(lines[line]);
    const before = ws.slice(0, idx).join(" ");
    const x0 = before ? textWidth(`${before} `, face.font, size, face.weight ?? 400, face.tracking ?? 0) : 0;
    const x1 = textWidth(ws.slice(0, idx + 1).join(" "), face.font, size, face.weight ?? 400, face.tracking ?? 0);
    const cur = out.find((o) => o.line === line);
    if (cur) cur.x1 = Math.max(cur.x1, x1);
    else out.push({ line, x0, x1 });
  }
  return out;
};

/**
 * A document set in real type - its kind as a kicker (REPORT, RECORDS...), the
 * headline in Source Serif, the narration's sentence as its body - lands on a
 * dark desk; the camera pushes in and leans toward the key words (frames
 * 18 -> end), a hand-drawn loop circles them (frame 30 -> 52; two lines get a
 * hand underline each) and a callout with a leader line names them (frame 54).
 */
const DocSpotlight: Look = ({ overlay, accent }) => {
  const { f, S, k, width: W, height: H, dur } = useBase();
  const head = str(overlay.text);
  const body = str(overlay.body) || str(overlay.highlight);
  if (!head && !body) return null;
  const hot = hotOf(accent);
  const kicker = (str(overlay.label) || "DOCUMENT").toUpperCase();
  const source = str(overlay.subtitle);
  const PW = 1060 * k;
  const pad = 70 * k;
  const inner = PW - 2 * pad;
  const headFace: Face = { font: SERIF, weight: 700 };
  const bodyFace: Face = { font: SERIF, weight: 400 };
  const hf = fit(head, headFace, inner, 64 * k, 42 * k, 3);
  const bodySize = 34 * k;
  const bf = fit(body && body !== head ? body : "", bodyFace, inner, bodySize, 28 * k, 6);
  // The key words: the plan's highlight when it is a phrase of the text, else the body's first five words.
  let hl = str(overlay.highlight);
  if (!hl || words(hl).length > 8 || hl === body) hl = words(body || head).slice(0, 5).join(" ");
  const inBody = bf.lines.length ? spansOf(bf.lines, hl, bodyFace, bf.size) : [];
  const inHead = inBody.length ? [] : spansOf(hf.lines, hl, headFace, hf.size);
  const headTop = pad + 64 * k;
  const headLH = hf.size * 1.12;
  const bodyTop = headTop + hf.lines.length * headLH + 34 * k;
  const bodyLH = bf.size * 1.5;
  const fauxTop = bodyTop + bf.lines.length * bodyLH + 22 * k;
  const PH = fauxTop + 4 * 30 * k + pad * 0.6;
  const spans = inBody.length ? inBody.map((s) => ({ ...s, top: bodyTop + s.line * bodyLH, lh: bodyLH, size: bf.size }))
    : inHead.map((s) => ({ ...s, top: headTop + s.line * headLH, lh: headLH, size: hf.size }));
  // The focus: the middle of the key words on the page (else the headline).
  const fxP = spans.length ? pad + (spans[0].x0 + spans[0].x1) / 2 : PW / 2;
  const fyP = spans.length ? spans[0].top + spans[0].lh * 0.45 : headTop + headLH;
  const left = (W - PW) / 2;
  const top = Math.max(60 * k, (H - PH) / 2 + 10 * k);
  const enter = inOf(f, 0, 20 * S, expoOut);
  const push = inOf(f, 16 * S, Math.max(30 * S, dur - 30 * S), easeInOut);
  const out = exitOf(f, dur, S, 14);
  const s = 0.94 + 0.06 * enter + 0.42 * push;
  const rot = -2.2 + 1.2 * enter;
  const tx = (W / 2 - (left + fxP)) * 0.85 * push;
  const ty = (H * 0.44 - (top + fyP)) * 0.85 * push + (1 - enter) * 70 * k;
  const draw = inOf(f, 30 * S, 22 * S, easeInOut);
  const seed = hash(hl || head);
  // Where the loop sits on screen once the camera has moved (for the callout's leader line).
  // One loop round the key words (on one line, or the two lines they run over); three or more: a hand underline each.
  const one = spans.length >= 1 && spans.length <= 2 ? {
    x0: Math.min(...spans.map((sp) => sp.x0)), x1: Math.max(...spans.map((sp) => sp.x1)),
    top: spans[0].top, lh: spans[0].lh * spans.length, size: spans[0].size * (spans.length === 2 ? 1.7 : 1) } : null;
  const loop = one ? { cx: pad + (one.x0 + one.x1) / 2, cy: one.top + one.lh * (spans.length === 2 ? 0.46 : 0.42),
    rx: (one.x1 - one.x0) / 2 + 30 * k, ry: one.size * 0.95 } : null;
  const toScreen = (px: number, py: number) => {
    const ox = left + fxP, oy = top + fyP;
    const a = (rot * Math.PI) / 180;
    const dx = (left + px - ox) * s, dy = (top + py - oy) * s;
    return [ox + tx + dx * Math.cos(a) - dy * Math.sin(a), oy + ty + dx * Math.sin(a) + dy * Math.cos(a)];
  };
  const edge = loop ? toScreen(loop.cx + loop.rx, loop.cy) : spans.length ? toScreen(pad + spans[0].x1, spans[0].top + spans[0].lh * 0.8) : null;
  const callP = inOf(f, 54 * S, 16 * S);
  const callX = W - 150 * k;
  const callY = H * 0.72;
  const label = hl.length <= 34 ? hl : words(hl).slice(0, 4).join(" ");
  return (
    <AbsoluteFill style={{ opacity: 1 - out }}>
      <AbsoluteFill style={{ background: `radial-gradient(ellipse 80% 75% at 50% 45%, #171a20 0%, #0b0d11 60%, #050608 100%)`,
        opacity: inOf(f, 0, 10 * S) }} />
      <Grain opacity={0.06} />
      <div style={{ position: "absolute", left, top, width: PW, height: PH, transformOrigin: `${fxP}px ${fyP}px`,
        transform: `translate(${tx.toFixed(1)}px, ${ty.toFixed(1)}px) rotate(${rot.toFixed(3)}deg) scale(${s.toFixed(4)})`,
        opacity: enter }}>
        <div style={{ position: "absolute", inset: 0, background: `linear-gradient(170deg, #f7f4ec 0%, ${PAPER} 55%, #e6e0d3 100%)`,
          borderRadius: 3 * k, boxShadow: `0 ${40 * k}px ${90 * k}px rgba(0,0,0,.6), 0 ${8 * k}px ${20 * k}px rgba(0,0,0,.4)` }} />
        <div style={{ position: "absolute", left: pad, top: pad, right: pad, display: "flex", justifyContent: "space-between",
          alignItems: "baseline" }}>
          <span style={{ ...caps(20 * k, mixHex(hot, "#3a1c00", 0.55), 0.22) }}>{kicker}</span>
          {source ? <span style={{ ...caps(18 * k, PAPER_SOFT, 0.14) }}>{source}</span> : null}
        </div>
        <div style={{ position: "absolute", left: pad, right: pad, top: pad + 36 * k, height: 3 * k, background: PAPER_INK, opacity: 0.85 }} />
        <div style={{ position: "absolute", left: pad, right: pad, top: pad + 42 * k, height: 1 * k, background: PAPER_INK, opacity: 0.6 }} />
        {hf.lines.map((ln, i) => (
          <div key={`h${i}`} style={{ position: "absolute", left: pad, top: headTop + i * headLH, fontFamily: SERIF, fontWeight: 700,
            fontSize: hf.size, lineHeight: `${headLH}px`, color: PAPER_INK, whiteSpace: "nowrap", letterSpacing: "-0.005em" }}>{ln}</div>
        ))}
        {bf.lines.map((ln, i) => (
          <div key={`b${i}`} style={{ position: "absolute", left: pad, top: bodyTop + i * bodyLH, fontFamily: SERIF, fontWeight: 400,
            fontSize: bf.size, lineHeight: `${bodyLH}px`, color: "#2b2d33", whiteSpace: "nowrap" }}>{ln}</div>
        ))}
        {[0, 1, 2, 3].map((i) => (
          <div key={`x${i}`} style={{ position: "absolute", left: pad, top: fauxTop + i * 30 * k, height: 11 * k, borderRadius: 6 * k,
            width: inner * (i === 3 ? 0.58 : 0.97 - 0.05 * rnd(seed + i)), background: "rgba(40,42,48,.09)",
            filter: `blur(${(1.4 * k).toFixed(1)}px)` }} />
        ))}
        <svg width={PW} height={PH} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          {loop ? <Stroke d={loopPath(loop.cx, loop.cy, loop.rx, loop.ry, seed)} p={draw} color={hot} width={6 * k} shadow={false} />
            : spans.map((sp, i) => (
              <Stroke key={i} d={underPath(pad + sp.x0 - 4 * k, pad + sp.x1 + 4 * k, sp.top + sp.lh * 0.86, seed + i, k)}
                p={clamp01(draw * spans.length - i)} color={hot} width={6 * k} shadow={false} />
            ))}
        </svg>
      </div>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 70% 65% at 50% 50%, rgba(0,0,0,0) 55%, rgba(0,0,0,.45) 100%)",
        pointerEvents: "none" }} />
      {edge && label ? (
        <>
          <svg width={W} height={H} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
            <Stroke d={`M${(edge[0] + 10 * k).toFixed(1)},${edge[1].toFixed(1)} L${(callX - 8 * k).toFixed(1)},${(callY + 26 * k).toFixed(1)}`}
              p={inOf(f, 50 * S, 10 * S)} color="rgba(255,255,255,.9)" width={3 * k} />
          </svg>
          <Callout x={callX} y={callY} text={label} p={callP} hot={hot} k={k} align="right" size={36} />
        </>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== pr-number-reveal
/**
 * One figure, big: what it counts in small tracked caps (the accent), the
 * number counting up in Anton (frames 6 -> 40, tabular figures so nothing
 * jitters), its unit beside it, an accent rule drawing under it and one
 * line of what it means (subtitle) - low on the footage over a feathered
 * shade. Left by default; overlay.align "right" mirrors it.
 */
const NumberReveal: Look = ({ overlay, accent }) => {
  const { f, S, k, width: W, height: H, dur } = useBase();
  const value = num(overlay.value);
  if (value === null) return null;
  const hot = hotOf(accent);
  const fig = figureOf(value, overlay.suffix, overlay.prefix);
  const right = str(overlay.align).toLowerCase() === "right";
  const label = str(overlay.text).toUpperCase();
  const context = str(overlay.subtitle);
  const count = inOf(f, 6 * S, 34 * S, expoOut);
  const rise = inOf(f, 0, 16 * S, expoOut);
  const ruleP = inOf(f, 26 * S, 16 * S, easeInOut);
  const ctxP = inOf(f, 34 * S, 14 * S);
  const out = exitOf(f, dur, S, 12);
  const finalText = `${fig.prefix}${fig.main}${fig.glued}`;
  const numSize = Math.min(176 * k, (820 * k) / Math.max(1, textWidth(finalText, ANTON, 100, 400) / 100));
  const numW = textWidth(finalText, ANTON, numSize, 400);
  const unitSize = numSize * 0.34;
  const ctx = context ? fit(context, { font: INTER, weight: 600 }, 860 * k, 34 * k, 24 * k, 1) : null;
  const x = right ? W - 120 * k : 120 * k;
  const base = H * 0.80;
  const shown = `${fig.prefix}${countText(fig, count)}${fig.glued}`;
  const align: CSS = right ? { right: W - x, textAlign: "right", alignItems: "flex-end" } : { left: x, alignItems: "flex-start" };
  return (
    <AbsoluteFill style={{ opacity: (1 - out) * rise }}>
      <Pool x={right ? W - 460 * k : 460 * k} y={base - numSize * 0.45} w={1100 * k} h={numSize * 2.6} p={rise} strength={0.58} />
      <div style={{ position: "absolute", bottom: H - base - 60 * k, display: "flex", flexDirection: "column", ...align,
        transform: `translateY(${((1 - rise) * 26 * k + out * 20 * k).toFixed(1)}px)` }}>
        {label ? <div style={{ ...caps(26 * k, hot, 0.2), textShadow: lift(k, 0.55), marginBottom: 6 * k }}>{label}</div> : null}
        <div style={{ display: "flex", alignItems: "baseline", flexDirection: right ? "row-reverse" : "row", gap: 16 * k }}>
          <div style={{ ...heavy(numSize, "#fff", 0.005), textShadow: lift(k, 0.6), minWidth: numW, textAlign: right ? "right" : "left" }}>
            {shown}
          </div>
          {fig.unit ? <div style={{ fontFamily: LABEL, fontWeight: 800, fontSize: unitSize, letterSpacing: "0.04em", color: "#fff",
            textShadow: lift(k, 0.55), opacity: inOf(f, 18 * S, 12 * S) }}>{fig.unit}</div> : null}
        </div>
        <div style={{ height: 7 * k, width: Math.max(120 * k, numW * 0.42) * ruleP, background: hot, borderRadius: 2 * k,
          marginTop: 10 * k, boxShadow: `0 ${2 * k}px ${10 * k}px rgba(0,0,0,.45)` }} />
        {ctx && ctx.lines.length ? (
          <div style={{ fontFamily: INTER, fontWeight: 600, fontSize: ctx.size, lineHeight: 1.2, color: "rgba(255,255,255,.92)",
            marginTop: 14 * k, whiteSpace: "nowrap", textShadow: lift(k, 0.6), opacity: ctxP,
            transform: `translateY(${((1 - ctxP) * 10 * k).toFixed(1)}px)` }}>{ctx.lines[0]}</div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== pr-graph-build
const isYearish = (s: string) => /^(1[5-9]\d\d|20\d\d)s?$/.test(s) || /^(TODAY|NOW)$/i.test(s);
/** A smooth path through points (Catmull-Rom as cubic Béziers). */
const smooth = (pts: [number, number][]): string => {
  if (pts.length < 2) return "";
  let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
    const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += ` C${c1[0].toFixed(1)},${c1[1].toFixed(1)} ${c2[0].toFixed(1)},${c2[1].toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  return d;
};

/**
 * The line's own figures as a chart on dark glass: years (three or more) as a
 * line that draws in (frames 12 -> 60, cubic in-out) with its area filling
 * behind, each point popping and its value counting up as the line reaches
 * it, the last point ringed with its value and the change since the first;
 * anything else as bars that grow in turn, the largest in the accent and
 * called out. Title (text) and unit above.
 */
const GraphBuild: Look = ({ overlay, accent }) => {
  const { f, S, k, width: W, height: H, dur } = useBase();
  const rows = rowsOf(overlay.items, 8);
  if (rows.length < 2) return null;
  const hot = hotOf(accent);
  const { suffix, prefix } = unitsOf(rows, overlay.suffix, overlay.prefix);
  const line = rows.length >= 3 && rows.every((r) => isYearish(r.label)) && str(overlay.variant) !== "bars";
  const enter = inOf(f, 0, 14 * S, expoOut);
  const out = exitOf(f, dur, S, 14);
  const CW = 1480 * k, CH = 780 * k;
  const cl = (W - CW) / 2, ct = (H - CH) / 2 + 10 * k;
  const px0 = 150 * k, px1 = CW - 90 * k, py0 = 200 * k, py1 = CH - 120 * k;
  const vals = rows.map((r) => r.value);
  const sc = line ? seriesScale(vals, 4) : { ...seriesScale([0, ...vals], 4), min: 0 };
  const yOf = (v: number) => py1 - ((v - sc.min) / Math.max(1e-9, sc.max - sc.min)) * (py1 - py0);
  const title = str(overlay.text).toUpperCase();
  const unitLine = [str(overlay.subtitle), suffix].filter(Boolean).join(" · ").toUpperCase();
  const figAt = (v: number, p: number, from = 0) => {
    const fg = figureOf(v, suffix, prefix);
    return `${fg.prefix}${countText(fg, p, from)}${fg.glued}${fg.unit ? ` ${fg.unit}` : ""}`;
  };
  const id = `pg${hash(title + rows.map((r) => r.label).join())}`;
  let plot: React.ReactNode;
  if (line) {
    const n = rows.length;
    const xs = rows.map((_, i) => px0 + ((px1 - px0) * i) / (n - 1));
    const pts = rows.map((r, i) => [xs[i], yOf(r.value)] as [number, number]);
    const dp = inOf(f, 12 * S, 48 * S, easeInOut);
    const key = n - 1;
    const ringP = inOf(f, 62 * S, 18 * S, easeInOut);
    const chg = percentChange(vals[0], vals[n - 1]);
    const kx = pts[key][0], ky = pts[key][1];
    plot = (
      <svg width={CW} height={CH} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
        <defs>
          <linearGradient id={`${id}a`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={hot} stopOpacity={0.32} />
            <stop offset="100%" stopColor={hot} stopOpacity={0} />
          </linearGradient>
          <clipPath id={`${id}c`}><rect x={0} y={0} width={px0 + (px1 - px0) * dp} height={CH} /></clipPath>
        </defs>
        {sc.ticks.map((t, i) => (
          <g key={i} opacity={inOf(f, 2 * S + i * 2 * S, 12 * S)}>
            <line x1={px0} x2={px1} y1={yOf(t)} y2={yOf(t)} stroke="rgba(255,255,255,.12)" strokeWidth={1.5 * k} strokeDasharray={`${6 * k} ${8 * k}`} />
            <text x={px0 - 22 * k} y={yOf(t) + 7 * k} textAnchor="end" fill="rgba(255,255,255,.55)"
              style={{ fontFamily: SUBLINE, fontWeight: 600, fontSize: 20 * k, fontVariantNumeric: "tabular-nums" }}>
              {figureOf(t, "", prefix).main}
            </text>
          </g>
        ))}
        <path d={`${smooth(pts)} L${px1},${py1} L${px0},${py1} Z`} fill={`url(#${id}a)`} clipPath={`url(#${id}c)`} />
        <Stroke d={smooth(pts)} p={dp} color={hot} width={6 * k} />
        {pts.map(([x, y], i) => {
          // (each point lands as the line reaches it; its value counts on from the point before)
          const at = (i / (n - 1)) * 0.94;
          const p = clamp01((dp - at) / 0.06);
          const vp = inOf(f, 12 * S + at * 48 * S, 14 * S, expoOut);
          const from = i > 0 ? rows[i - 1].value : rows[i].value * 0.9;
          return (
            <g key={i} opacity={p}>
              <circle cx={x} cy={y} r={(i === key ? 10 : 8) * k * (0.6 + 0.4 * p)} fill="#fff" stroke={hot} strokeWidth={4 * k} />
              <text x={x} y={y - (i === key ? 58 : 24) * k} textAnchor="middle" fill="#fff"
                style={{ fontFamily: ANTON, fontSize: 34 * k, fontVariantNumeric: "tabular-nums", paintOrder: "stroke",
                  stroke: "rgba(0,0,0,.55)", strokeWidth: 6 * k } as CSS}>{figAt(rows[i].value, vp, from)}</text>
              <text x={x} y={py1 + 44 * k} textAnchor="middle" fill="rgba(255,255,255,.78)"
                style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 26 * k, letterSpacing: "0.06em" }}>{rows[i].label}</text>
            </g>
          );
        })}
        <Stroke d={loopPath(kx, ky, 44 * k, 40 * k, hash(id))} p={ringP} color="#fff" width={4 * k} />
        {chg ? (
          <g opacity={inOf(f, 70 * S, 14 * S)}>
            <rect x={kx - 150 * k} y={ky + 34 * k} width={110 * k} height={44 * k} rx={6 * k} fill={hot} />
            <text x={kx - 95 * k} y={ky + 66 * k} textAnchor="middle" fill="#0b0d11"
              style={{ fontFamily: ANTON, fontSize: 30 * k }}>{chg}</text>
          </g>
        ) : null}
      </svg>
    );
  } else {
    const n = Math.min(6, rows.length);
    const use = rows.slice(0, n);
    const gap = 46 * k;
    const bw = Math.min(190 * k, (px1 - px0 - gap * (n - 1)) / n);
    const total = bw * n + gap * (n - 1);
    const x0 = px0 + (px1 - px0 - total) / 2;
    const top = Math.max(...use.map((r) => r.value));
    const keyI = use.findIndex((r) => r.value === top);
    plot = (
      <svg width={CW} height={CH} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
        <line x1={px0} x2={px1} y1={py1} y2={py1} stroke="rgba(255,255,255,.35)" strokeWidth={2 * k} opacity={inOf(f, 0, 12 * S)} />
        {use.map((r, i) => {
          const g = inOf(f, 10 * S + i * 6 * S, 30 * S, expoOut);
          const x = x0 + i * (bw + gap);
          const y = yOf(r.value * g);
          const isKey = i === keyI;
          return (
            <g key={i}>
              <rect x={x} y={y} width={bw} height={Math.max(0, py1 - y)} rx={4 * k}
                fill={isKey ? hot : "rgba(255,255,255,.82)"} />
              <text x={x + bw / 2} y={y - 18 * k} textAnchor="middle" fill="#fff" opacity={clamp01(g * 3)}
                style={{ fontFamily: ANTON, fontSize: 38 * k, fontVariantNumeric: "tabular-nums" }}>{figAt(r.value, g)}</text>
              <text x={x + bw / 2} y={py1 + 44 * k} textAnchor="middle" fill="rgba(255,255,255,.8)"
                style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 26 * k, letterSpacing: "0.05em" }}>
                {r.label.toUpperCase().slice(0, 18)}
              </text>
            </g>
          );
        })}
        <Stroke d={loopPath(x0 + keyI * (bw + gap) + bw / 2, yOf(top) - 30 * k, bw * 0.75, 46 * k, hash(id))}
          p={inOf(f, 10 * S + n * 6 * S + 24 * S, 18 * S, easeInOut)} color="#fff" width={4 * k} />
      </svg>
    );
  }
  return (
    <AbsoluteFill style={{ opacity: 1 - out }}>
      <Stage ov={overlay} p={enter} />
      <div style={{ position: "absolute", left: cl, top: ct, width: CW, height: CH, borderRadius: 18 * k, background: GLASS,
        border: `${1.5 * k}px solid rgba(255,255,255,.08)`, boxShadow: `0 ${40 * k}px ${100 * k}px rgba(0,0,0,.55)`,
        opacity: enter, transform: `translateY(${((1 - enter) * 40 * k).toFixed(1)}px)` }}>
        <div style={{ position: "absolute", left: 64 * k, top: 52 * k, right: 64 * k }}>
          {title ? <div style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 48 * k, letterSpacing: "0.03em", color: "#fff",
            lineHeight: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{title}</div> : null}
          {unitLine ? <div style={{ ...caps(20 * k, "rgba(255,255,255,.6)", 0.18), marginTop: 12 * k }}>{unitLine}</div> : null}
          <div style={{ marginTop: 18 * k, height: 4 * k, width: 84 * k, background: hot, borderRadius: 2 * k }} />
        </div>
        {plot}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== pr-map-path
type Feat = { type: string; id?: string | number; properties?: { name?: string }; geometry: unknown };
type FeatColl = { type: "FeatureCollection"; features: Feat[] };
const WORLD = (feature(worldTopology as never, worldTopology.objects.countries as never) as unknown as FeatColl).features
  .filter((x) => x.properties?.name !== "Antarctica");
const STATES = (feature(statesTopology as never, statesTopology.objects.states as never) as unknown as FeatColl).features;
const geoCentroidOf = (g: Feat): [number, number] | null => {
  try {
    return geoCentroid(g as never) as [number, number];
  } catch {
    return null;
  }
};
const inUS = (p: { lat: number; lon: number }) => p.lat > 18 && p.lat < 72 && p.lon > -170 && p.lon < -64;
/** Never a view narrower than this many miles across: the states round the route must read as shapes. */
const MIN_VIEW_MILES = 620;

/**
 * Two places on a dark relief map (the states, else the countries, their
 * names faint at their centres): the camera starts close on the first - its
 * pin and name - and travels out to a view of both (frames 8 -> 54, cubic
 * in-out, one move: zoom and pan together) while the route draws along the
 * great circle (frames 20 -> 62) with a soft glow and a bright head; the
 * second pin lands as the route arrives, then its name and the distance (the
 * one the narration said, else the straight-line miles). The map is drawn
 * once and the camera moves over it, so the relief travels with the land.
 */
const MapPath: Look = ({ overlay, accent }) => {
  const { f, S, k, width: W, height: H, dur } = useBase();
  const reliefId = useSvgId("prrel");
  const clipId = useSvgId("prclip");
  const places = placesOf(overlay.locations, 2);
  if (places.length < 2) return null;
  const [A, B] = places;
  const hot = hotOf(accent);
  const out = exitOf(f, dur, S, 14);
  const us = inUS(A) && inUS(B);
  const geo = us ? STATES : WORLD;
  // The final view: both places, with room round them and never under MIN_VIEW_MILES across.
  const miles = milesBetween(A, B);
  const both = { type: "MultiPoint", coordinates: [[A.lon, A.lat], [B.lon, B.lat]] };
  const fitted = geoMercator().fitExtent([[420 * k, 300 * k], [W - 420 * k, H - 280 * k]], both as never);
  const acrossMiles = Math.max(1, miles * (W / Math.max(1, W - 840 * k)));
  const scale = fitted.scale() * Math.min(1, acrossMiles / Math.max(acrossMiles, MIN_VIEW_MILES));
  const mid = geoInterpolate([A.lon, A.lat], [B.lon, B.lat])(0.5) as [number, number];
  const cy0 = H / 2 + 10 * k;
  const proj = geoMercator().scale(scale).center(mid).translate([W / 2, cy0]);
  const path = geoPath(proj as never);
  const interp = geoInterpolate([A.lon, A.lat], [B.lon, B.lat]);
  const route = Array.from({ length: 65 }, (_, i) => proj(interp(i / 64)) as [number, number] | null)
    .filter(Boolean) as [number, number][];
  const routeD = route.length ? `M${route.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" L")}` : "";
  const pa = proj([A.lon, A.lat]) as [number, number];
  const pb = proj([B.lon, B.lat]) as [number, number];
  // The camera: centre m and zoom z, from close on A to the whole view.
  const cam = inOf(f, 8 * S, 46 * S, easeInOut);
  const z = Math.exp(lerp(Math.log(1.9), 0, cam));
  const m: [number, number] = [lerp(pa[0], W / 2, cam), lerp(pa[1], cy0, cam)];
  const toScreen = (p: [number, number]): [number, number] => [(p[0] - m[0]) * z + W / 2, (p[1] - m[1]) * z + cy0];
  const sa = toScreen(pa);
  const sb = toScreen(pb);
  const rp = inOf(f, 20 * S, 42 * S, easeInOut);
  const headI = Math.min(route.length - 1, Math.round(rp * (route.length - 1)));
  const head = route.length ? toScreen(route[headI]) : null;
  const pinA = inOf(f, 4 * S, 12 * S);
  const pinB = inOf(f, 60 * S, 12 * S);
  const nameA = placeName(A.label);
  const nameB = placeName(B.label);
  const dist = distanceText(miles, num(overlay.value), overlay.suffix);
  const midS = route.length ? toScreen(route[Math.floor(route.length / 2)]) : [(sa[0] + sb[0]) / 2, (sa[1] + sb[1]) / 2];
  const distP = inOf(f, 66 * S, 14 * S);
  const title = str(overlay.text).toUpperCase();
  const bLeft = pb[0] < pa[0];
  // The names of the land round the route, faint (only those whose centre is in the final view).
  const names = geo.map((g) => {
    const cc = geoCentroidOf(g);
    const c = cc ? (proj(cc) as [number, number] | null) : null;
    return c && c[0] > 80 * k && c[0] < W - 80 * k && c[1] > 80 * k && c[1] < H - 80 * k
      ? { c, n: String(g.properties?.name || "").toUpperCase() } : null;
  }).filter(Boolean) as { c: [number, number]; n: string }[];
  const pin = (p: [number, number], on: number, pulse: number) => (
    <g opacity={clamp01(on * 2)}>
      <circle cx={p[0]} cy={p[1]} r={(14 + 30 * pulse) * k} fill="none" stroke={hot} strokeWidth={2.5 * k} opacity={(1 - pulse) * 0.8} />
      <circle cx={p[0]} cy={p[1]} r={11 * k * (0.4 + 0.6 * on)} fill="#fff" stroke={hot} strokeWidth={5 * k} />
    </g>
  );
  const name = (p: [number, number], n: { name: string; region: string }, on: number, right: boolean) => (
    <div style={{ position: "absolute", left: right ? p[0] + 28 * k : undefined, right: right ? undefined : W - p[0] + 28 * k,
      top: p[1] - 26 * k, textAlign: right ? "left" : "right", opacity: on,
      transform: `translateY(${((1 - on) * 10 * k).toFixed(1)}px)` }}>
      <div style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 42 * k, letterSpacing: "0.03em", color: "#fff", lineHeight: 1,
        textShadow: lift(k, 0.75), whiteSpace: "nowrap" }}>{n.name.toUpperCase()}</div>
      {n.region ? <div style={{ ...caps(18 * k, "rgba(255,255,255,.72)", 0.18), marginTop: 7 * k, textShadow: lift(k, 0.6) }}>{n.region}</div> : null}
    </div>
  );
  return (
    <AbsoluteFill style={{ opacity: inOf(f, 0, 8 * S) * (1 - out) }}>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 90% 80% at 50% 45%, #0c131c 0%, #070b10 60%, #04060a 100%)" }} />
      <AbsoluteFill style={{ transformOrigin: "0 0",
        transform: `translate(${(W / 2).toFixed(1)}px, ${cy0.toFixed(1)}px) scale(${z.toFixed(4)}) `
          + `translate(${(-m[0]).toFixed(1)}px, ${(-m[1]).toFixed(1)}px)` }}>
        <svg width={W} height={H} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          <defs>
            <filter id={reliefId} x="-10%" y="-10%" width="120%" height="120%">
              <feTurbulence type="fractalNoise" baseFrequency="0.011" numOctaves={4} seed={7} result="n" />
              <feDiffuseLighting in="n" surfaceScale={4} lightingColor="#8aa0ba" result="l">
                <feDistantLight azimuth={225} elevation={38} />
              </feDiffuseLighting>
              <feComposite in="l" in2="SourceGraphic" operator="in" />
            </filter>
            <clipPath id={clipId}>{geo.map((g, i) => <path key={i} d={path(g as never) || ""} />)}</clipPath>
          </defs>
          {geo.map((g, i) => <path key={`f${i}`} d={path(g as never) || ""} fill="#121a24" />)}
          <g clipPath={`url(#${clipId})`} opacity={0.13} style={{ mixBlendMode: "screen" }}>
            <rect x={-W * 0.2} y={-H * 0.2} width={W * 1.4} height={H * 1.4} fill="#fff" filter={`url(#${reliefId})`} />
          </g>
          {geo.map((g, i) => <path key={`s${i}`} d={path(g as never) || ""} fill="none" stroke="#4d6079" strokeWidth={1.6 * k}
            vectorEffect="non-scaling-stroke" />)}
          <path d={routeD} pathLength={1} fill="none" stroke={rgba(hot, 0.4)} strokeWidth={14 * k} strokeLinecap="round"
            strokeDasharray="1 1" strokeDashoffset={1 - rp} vectorEffect="non-scaling-stroke"
            style={{ filter: `blur(${(5 * k).toFixed(1)}px)` }} />
          <path d={routeD} pathLength={1} fill="none" stroke={hot} strokeWidth={5.5 * k} strokeLinecap="round"
            strokeDasharray="1 1" strokeDashoffset={1 - rp} vectorEffect="non-scaling-stroke" />
        </svg>
      </AbsoluteFill>
      <AbsoluteFill style={{ opacity: inOf(f, 30 * S, 20 * S) }}>
        {names.map(({ c, n }, i) => {
          const sc = toScreen(c);
          const near = (q: [number, number]) => Math.hypot(sc[0] - q[0], sc[1] - q[1]) < 160 * k;
          return near(sa) || near(sb) ? null : (
            <div key={i} style={{ position: "absolute", left: sc[0], top: sc[1], transform: "translate(-50%, -50%)",
              ...caps(18 * k, "rgba(196,210,228,.5)", 0.32) }}>{n}</div>
          );
        })}
      </AbsoluteFill>
      <svg width={W} height={H} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
        {rp > 0 && rp < 1 && head ? <circle cx={head[0]} cy={head[1]} r={9 * k} fill="#fff" stroke={hot} strokeWidth={4 * k} /> : null}
        {pin(sa, pinA, clamp01((f - 6 * S) / (30 * S)))}
        {pin(sb, pinB, clamp01((f - 62 * S) / (30 * S)))}
      </svg>
      {name(sa, nameA, inOf(f, 10 * S, 14 * S), bLeft)}
      {name(sb, nameB, inOf(f, 64 * S, 14 * S), !bLeft)}
      {dist ? (
        <div style={{ position: "absolute", left: midS[0], top: midS[1] - 78 * k,
          transform: `translate(-50%, ${((1 - distP) * 10 * k).toFixed(1)}px)`, opacity: distP,
          padding: `${10 * k}px ${22 * k}px`, background: GLASS, border: `${2 * k}px solid ${hot}`, borderRadius: 40 * k,
          fontFamily: ANTON, fontSize: 34 * k, color: "#fff", letterSpacing: "0.02em", whiteSpace: "nowrap",
          fontVariantNumeric: "tabular-nums", boxShadow: `0 ${10 * k}px ${30 * k}px rgba(0,0,0,.5)` }}>{dist}</div>
      ) : null}
      {title ? (
        <div style={{ position: "absolute", left: 96 * k, top: 86 * k, opacity: inOf(f, 6 * S, 14 * S) }}>
          <div style={{ ...caps(22 * k, hot, 0.22), textShadow: lift(k, 0.6) }}>{title}</div>
        </div>
      ) : null}
      <Vignette strength={0.55} />
      <Grain opacity={0.05} />
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "pr-doc-spotlight": guard(DocSpotlight),
  "pr-photo-focus": guard(PhotoFocus),
  "pr-graph-build": guard(GraphBuild),
  "pr-map-path": guard(MapPath),
  "pr-number-reveal": guard(NumberReveal),
};
