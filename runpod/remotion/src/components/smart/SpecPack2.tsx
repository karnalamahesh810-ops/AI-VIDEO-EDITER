/**
 * Motion pack 2's drawing (2026-10-14): the layer kinds the Editor v2 motion library's second pack adds to the
 * motion-spec stage (SmartSpec.tsx draws every other kind):
 *
 *   chart    - data that builds item by item, each item on its spoken time (layer.times): a bar race that
 *              re-sorts itself, a line that draws on with a callout, a donut, a stat grid, a timeline
 *              scrubber, a ranking ladder (#5 -> #1);
 *   card     - a mock-up that drops onto the shot: sticky note, polaroid (its photo is the shot itself), a
 *              document page with a highlighted line, a social post, a phone with messages, a browser window,
 *              a quote card with a portrait;
 *   fx       - a full-frame effect: ink bleed, film burn, glitch slices, paper tear, block dissolve (over a cut),
 *              a magnifier focus and a before / after split (over one shot);
 *   scribble - a hand-drawn mark: a scribbled loop, a brush swoosh, a strike-through, a looping arrow.
 *
 * Same rules as the stage: pure functions of (layer, t) - no clock, no random source (rand() is seeded), no
 * network except SafeImg's picture, which can never hold the render (memory: safeimg-render-hang).
 */
import React from "react";
import { DISPLAY, GROTESK, HAND, INTER, KINETIC, MONO, NARROW, SERIF, SERIF_ITALIC, TYPEWRITER } from "../fonts";
import { SafeImg } from "../motion/safePicture";
import { easeOf, formatCount, rand, type DataItem, type Layer } from "./specMath";
import { styleFont } from "./styleFonts";

export interface XCtx { t: number; dur: number; W: number; H: number }

const FACES: Record<string, string> = {
  grotesk: GROTESK, kinetic: KINETIC, display: DISPLAY, serif: SERIF, "serif-italic": SERIF_ITALIC, mono: MONO,
  narrow: NARROW, inter: INTER, hand: HAND,
};
const faceOf = (k: string | undefined, d = GROTESK) => styleFont(k) || FACES[k || ""] || d;
const c01 = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);
/** Progress 0..1 of a move that starts at `at` and takes `len` seconds. */
const pr = (lt: number, at: number, len: number, ease = "expoOut") => easeOf(ease)((lt - at) / Math.max(0.01, len));
const hexA = (c: string, a: number): string => {
  const m = /^#([0-9a-f]{6})$/i.exec(c);
  if (!m) return c;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a.toFixed(3)})`;
};
const shadow = (H: number, k = 1) => `0 ${(0.004 * H * k).toFixed(1)}px ${(0.016 * H * k).toFixed(1)}px rgba(0,0,0,0.55)`;
const drop = (H: number) => `0 ${(0.012 * H).toFixed(1)}px ${(0.04 * H).toFixed(1)}px rgba(0,0,0,0.5)`;
/** Arrival of a block: from below, from a blur. */
const arrive = (p: number, H: number, dy = 0.03): React.CSSProperties => ({
  opacity: c01(p * 1.4), transform: `translateY(${((1 - p) * dy * H).toFixed(2)}px)`,
  filter: p < 0.97 ? `blur(${((1 - p) * 8 * H / 1080).toFixed(2)}px)` : undefined,
});
const fig = (d: DataItem, L: Layer, v: number) =>
  `${d.pre ?? L.prefix ?? ""}${formatCount(v, d.dec ?? L.decimals ?? 0)}${d.suf ?? L.suffix ?? ""}`;
const timesOf = (L: Layer, n: number) => Array.from({ length: n }, (_, i) => {
  const t = L.times?.[i];
  return typeof t === "number" ? t : 0.3 + i * (L.stagger ?? 0.35);
});

// ================================================================== charts
export const ChartBody: React.FC<{ layer: Layer; ctx: XCtx }> = ({ layer: L, ctx }) => {
  // Unique per drawn instance: two previews of one look on a page must not share SVG ids.
  const uid = React.useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const { W, H, t } = ctx;
  const lt = t - L.from;
  const bw = L.w * W, bh = L.h * H;
  const data = L.data || [];
  const n = data.length;
  const at = timesOf(L, n);
  const bd = L.bdur || 0.8;
  const acc = L.fill || "#f2b630", ink = L.color, alt = L.color2 || "rgba(255,255,255,0.7)", off = L.offColor || "rgba(255,255,255,0.18)";
  const onAcc = L.emphColor || "#111111";
  const lf = faceOf(L.font, NARROW), nf = faceOf(L.font2 || L.font);
  const fs = (L.size || 0.032) * H;
  const vals = data.map((d) => d.v ?? 0);
  const hi = L.hi !== undefined && L.hi >= 0 && L.hi < n ? L.hi : vals.indexOf(Math.max(...vals));

  if (L.chart === "race") {
    const max = Math.max(1e-9, ...vals.map(Math.abs));
    const rank = data.map((_, i) => i).sort((a, b) => vals[b] - vals[a]);
    const pos = new Array(n).fill(0);
    rank.forEach((i, r) => { pos[i] = r; });
    const last = Math.max(...at) + bd;
    const sortP = pr(lt, last - 0.15, 0.85, "inOut");
    const rowH = bh / n, barH = rowH * 0.6;
    const labW = bw * 0.25, barW = bw * 0.6;
    return (
      <div style={{ position: "relative", width: bw, height: bh }}>
        {data.map((d, i) => {
          const y = (i + (pos[i] - i) * sortP) * rowH;
          const show = pr(lt, at[i] - 0.2, 0.45);
          const grow = pr(lt, at[i], bd * 1.5, L.ease || "expoOut");
          const top = i === hi;
          const col = top ? acc : alt;
          return (
            <div key={i} style={{ position: "absolute", left: 0, top: y, width: bw, height: rowH, display: "flex", alignItems: "center", ...arrive(show, H, 0.0) }}>
              <div style={{ width: labW, paddingRight: fs * 0.5, textAlign: "right", fontFamily: lf, fontWeight: 800, fontSize: fs,
                color: ink, textTransform: "uppercase", letterSpacing: "0.04em", whiteSpace: "nowrap", overflow: "hidden", textShadow: shadow(H) }}>{d.l}</div>
              <div style={{ position: "relative", width: barW, height: barH }}>
                <div style={{ position: "absolute", inset: 0, background: off, borderRadius: barH * 0.12 }} />
                <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${(100 * Math.abs(vals[i]) / max * grow).toFixed(3)}%`,
                  background: `linear-gradient(90deg, ${hexA(col, 0.82)}, ${col})`, borderRadius: barH * 0.12,
                  boxShadow: top ? `0 0 ${(0.02 * H).toFixed(1)}px ${hexA(acc, 0.55)}` : undefined }} />
                <div style={{ position: "absolute", left: `${(100 * Math.abs(vals[i]) / max * grow).toFixed(3)}%`, top: "50%",
                  transform: "translate(0.4em, -50%)", fontFamily: nf, fontWeight: 800, fontSize: fs * 1.05, color: top ? acc : ink,
                  whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums", textShadow: shadow(H) }}>{fig(d, L, vals[i] * grow)}</div>
              </div>
            </div>
          );
        })}
      </div>
    );
  }

  if (L.chart === "line") {
    const padL = bw * 0.04, padR = bw * 0.08, top = bh * 0.14, bot = bh * 0.14;
    const pw = bw - padL - padR, ph = bh - top - bot;
    const lo = Math.min(...vals), hiV = Math.max(...vals);
    const span = Math.max(1e-9, hiV - lo);
    const vmin = lo - span * 0.18, vmax = hiV + span * 0.08;
    const P = vals.map((v, i) => [padL + (n > 1 ? i / (n - 1) : 0.5) * pw, top + (1 - (v - vmin) / (vmax - vmin)) * ph]);
    // Catmull-Rom through the points as cubic Béziers.
    let d = `M${P[0][0].toFixed(1)},${P[0][1].toFixed(1)}`;
    for (let i = 0; i < n - 1; i++) {
      const p0 = P[Math.max(0, i - 1)], p1 = P[i], p2 = P[i + 1], p3 = P[Math.min(n - 1, i + 2)];
      const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6], c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
      d += ` C${c1[0].toFixed(1)},${c1[1].toFixed(1)} ${c2[0].toFixed(1)},${c2[1].toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
    }
    // The line reaches point i at its time (piecewise, eased inside each span).
    let frac = 0;
    if (n > 1) {
      if (lt >= at[n - 1] + 0.01) frac = 1;
      else for (let i = 0; i < n - 1; i++) {
        const a0 = i === 0 ? at[0] - 0.5 : at[i], a1 = at[i + 1];
        if (lt < a0) { frac = i / (n - 1); break; }
        if (lt < a1) { frac = (i + easeOf("sine")((lt - a0) / Math.max(0.05, a1 - a0))) / (n - 1); break; }
      }
      if (lt < at[0] - 0.5) frac = 0;
    } else frac = c01((lt - at[0]) / 0.6);
    const grid = pr(lt, 0, 0.7);
    const sw = Math.max(3, 0.0075 * H);
    const ci = hi >= 0 ? hi : n - 1;
    const call = pr(lt, at[ci] + 0.15, 0.55);
    const ring = ((Math.max(0, lt - at[ci]) % 1.4) / 1.4);
    const gid = `lg${uid}`;
    return (
      <div style={{ position: "relative", width: bw, height: bh }}>
        <svg width={bw} height={bh} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          <defs>
            <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={acc} stopOpacity={0.42} /><stop offset="1" stopColor={acc} stopOpacity={0} /></linearGradient>
            <clipPath id={`${gid}c`}><rect x={0} y={0} width={padL + frac * pw} height={bh} /></clipPath>
          </defs>
          {[0, 1, 2, 3].map((k) => <line key={k} x1={padL} x2={padL + pw * grid} y1={top + (k / 3) * ph} y2={top + (k / 3) * ph}
            stroke={off} strokeWidth={Math.max(1, 0.0015 * H)} />)}
          <path d={`${d} L${P[n - 1][0].toFixed(1)},${(top + ph).toFixed(1)} L${P[0][0].toFixed(1)},${(top + ph).toFixed(1)} Z`} fill={`url(#${gid})`} clipPath={`url(#${gid}c)`} />
          <path d={d} fill="none" stroke={acc} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" pathLength={1}
            strokeDasharray="1 1" strokeDashoffset={1 - frac} style={{ filter: `drop-shadow(0 0 ${(0.01 * H).toFixed(1)}px ${hexA(acc, 0.6)})` }} />
          {P.map(([x, y], i) => {
            const on = c01(((frac * (n - 1)) - i + 0.08) / 0.15);
            return on > 0 ? <circle key={i} cx={x} cy={y} r={sw * (i === ci ? 1.5 : 1.05) * easeOf("backOut")(on)} fill={i === ci ? acc : ink} stroke={i === ci ? ink : acc} strokeWidth={sw * 0.5} /> : null;
          })}
          {call > 0 ? <circle cx={P[ci][0]} cy={P[ci][1]} r={sw * (1.5 + 5 * ring)} fill="none" stroke={acc} strokeWidth={sw * 0.4} opacity={(1 - ring) * call} /> : null}
        </svg>
        {data.map((dd, i) => dd.l ? (
          <div key={i} style={{ position: "absolute", left: P[i][0], top: top + ph + bot * 0.22, transform: "translateX(-50%)", fontFamily: lf, fontWeight: 700,
            fontSize: fs, color: i === ci ? acc : alt, letterSpacing: "0.06em", textTransform: "uppercase", whiteSpace: "nowrap",
            opacity: c01(((frac * (n - 1)) - i + 0.3) / 0.3), textShadow: shadow(H) }}>{dd.l}</div>
        ) : null)}
        {call > 0 ? (
          <div style={{ position: "absolute", left: P[ci][0], top: P[ci][1] - sw * 3, transform: `translate(-50%, -100%) scale(${(0.85 + 0.15 * call).toFixed(3)})`,
            transformOrigin: "50% 100%", opacity: call, background: acc, color: onAcc, fontFamily: nf, fontWeight: 800, fontSize: fs * 1.15,
            padding: "0.18em 0.5em 0.14em", borderRadius: fs * 0.22, whiteSpace: "nowrap", boxShadow: drop(H), fontVariantNumeric: "tabular-nums" }}>
            {fig(data[ci], L, vals[ci] * c01(call * 1.2))}
            <div style={{ position: "absolute", left: "50%", bottom: -fs * 0.3, width: fs * 0.5, height: fs * 0.5, background: acc,
              transform: "translateX(-50%) rotate(45deg)", zIndex: -1 }} />
          </div>
        ) : null}
      </div>
    );
  }

  if (L.chart === "donut") {
    const D = Math.min(bh, bw * 0.48);
    const R = D * 0.38, sw = D * 0.15;
    const tot = Math.max(1e-9, vals.reduce((a, v) => a + Math.max(0, v), 0));
    const pal = L.palette && L.palette.length ? L.palette : [acc, alt, off];
    let start = 0;
    const gap = n > 1 ? 0.006 : 0;
    const rest = pal.filter((c) => c !== acc);
    const others = rest.length ? rest : [alt, off];
    let oi = 0;
    const segs = data.map((d, i) => {
      const f = Math.max(0, vals[i]) / tot;
      const p = pr(lt, at[i], bd, "inOut");
      const s0 = start;
      start += f;
      const col = i === hi ? acc : others[oi++ % others.length];
      const pop = i === hi ? pr(lt, at[i] + bd * 0.8, 0.5, "backOut") : 0;
      return { f, p, s0, col, pop, d };
    });
    const hiSeg = segs[hi];
    const cp = pr(lt, at[hi] + bd * 0.4, 0.6);
    return (
      <div style={{ position: "relative", width: bw, height: bh, display: "flex", alignItems: "center", gap: D * 0.12 }}>
        <div style={{ position: "relative", width: D, height: D, flex: "none" }}>
          <svg width={D} height={D} style={{ overflow: "visible", transform: "rotate(-90deg)", filter: `drop-shadow(${shadow(H)})` }}>
            <circle cx={D / 2} cy={D / 2} r={R} fill="none" stroke={hexA("#000000", 0.35)} strokeWidth={sw} opacity={pr(lt, 0, 0.5)} />
            {segs.map((s, i) => s.p > 0 ? (
              <circle key={i} cx={D / 2} cy={D / 2} r={R + s.pop * sw * 0.08} fill="none" stroke={s.col} strokeWidth={sw * (1 + s.pop * 0.18)} pathLength={1}
                strokeDasharray={`${Math.max(0, s.f * s.p - gap).toFixed(4)} 1`} strokeDashoffset={-s.s0} />
            ) : null)}
          </svg>
          <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", opacity: cp,
            transform: `scale(${(0.9 + 0.1 * cp).toFixed(3)})` }}>
            <div style={{ fontFamily: nf, fontWeight: 800, fontSize: R * 0.55, color: ink, lineHeight: 1, fontVariantNumeric: "tabular-nums", textShadow: shadow(H) }}>
              {hiSeg ? fig(hiSeg.d, L, vals[hi] * cp) : ""}</div>
            <div style={{ fontFamily: lf, fontWeight: 700, fontSize: R * 0.16, color: acc, letterSpacing: "0.1em", textTransform: "uppercase",
              marginTop: R * 0.06, maxWidth: R * 1.4, textAlign: "center", lineHeight: 1.05 }}>{hiSeg?.d.l}</div>
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: fs * 0.5 }}>
          {segs.map((s, i) => {
            const p = pr(lt, at[i] + 0.1, 0.5);
            return (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: fs * 0.45, ...arrive(p, H, 0.015) }}>
                <div style={{ width: fs * 0.7, height: fs * 0.7, borderRadius: fs * 0.14, background: s.col, flex: "none" }} />
                <div style={{ fontFamily: lf, fontWeight: 700, fontSize: fs, color: i === hi ? acc : ink, textTransform: "uppercase", letterSpacing: "0.05em",
                  whiteSpace: "nowrap", textShadow: shadow(H) }}>{s.d.l}</div>
                <div style={{ fontFamily: nf, fontWeight: 800, fontSize: fs, color: alt, fontVariantNumeric: "tabular-nums", textShadow: shadow(H) }}>{fig(s.d, L, vals[i] * p)}</div>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  if (L.chart === "grid") {
    const cols = n <= 3 ? n : 2, rows = Math.ceil(n / cols);
    const gap = 0.018 * H;
    const tw = (bw - gap * (cols - 1)) / cols, th = (bh - gap * (rows - 1)) / rows;
    const big = Math.min(th * 0.42, (tw * 0.92) / Math.max(3, ...data.map((d) => fig(d, L, d.v ?? 0).length * 0.6)));
    return (
      <div style={{ position: "relative", width: bw, height: bh }}>
        {data.map((d, i) => {
          const c = i % cols, r = Math.floor(i / cols);
          const p = pr(lt, at[i] - 0.25, 0.6);
          const cnt = pr(lt, at[i], 1.1, "expoOut");
          const rule = pr(lt, at[i] - 0.05, 0.6, "expoInOut");
          const isHi = i === hi;
          return (
            <div key={i} style={{ position: "absolute", left: c * (tw + gap), top: r * (th + gap), width: tw, height: th, borderRadius: 0.008 * H,
              background: hexA("#0a0c10", 0.62), backdropFilter: "blur(14px)", overflow: "hidden", padding: `${(th * 0.14).toFixed(1)}px ${(tw * 0.08).toFixed(1)}px`,
              boxSizing: "border-box", display: "flex", flexDirection: "column", justifyContent: "center", ...arrive(p, H, 0.04) }}>
              <div style={{ position: "absolute", left: 0, top: 0, height: Math.max(3, 0.005 * H), width: "100%", background: isHi ? acc : alt,
                transform: `scaleX(${rule.toFixed(4)})`, transformOrigin: "0% 50%" }} />
              <div style={{ fontFamily: nf, fontWeight: 800, fontSize: big, lineHeight: 1, color: isHi ? acc : ink, fontVariantNumeric: "tabular-nums",
                whiteSpace: "nowrap" }}>{d.v === null ? "" : fig(d, L, (d.v ?? 0) * cnt)}</div>
              <div style={{ fontFamily: lf, fontWeight: 700, fontSize: Math.min(fs, big * 0.42), color: alt, textTransform: "uppercase", letterSpacing: "0.08em",
                marginTop: big * 0.18, lineHeight: 1.1 }}>{d.l}</div>
            </div>
          );
        })}
      </div>
    );
  }

  if (L.chart === "timeline") {
    const x0 = bw * 0.05, x1 = bw * 0.95, ty = bh * 0.55;
    const xs = data.map((_, i) => x0 + ((i + 0.5) / n) * (x1 - x0));
    const track = pr(lt, 0, 0.8, "expoInOut");
    let head = x0;
    for (let i = 0; i < n; i++) {
      const prev = i ? xs[i - 1] : x0;
      const p = pr(lt, at[i] - 0.55, 0.6, "inOut");
      if (p <= 0) break;
      head = prev + (xs[i] - prev) * p;
    }
    const sw = Math.max(3, 0.005 * H);
    const yearOf = (l: string) => { const m = /^(\S+)\s*(.*)$/.exec(l.trim()); return m ? [m[1], m[2]] : [l, ""]; };
    return (
      <div style={{ position: "relative", width: bw, height: bh }}>
        <div style={{ position: "absolute", left: x0, top: ty - sw / 2, width: (x1 - x0) * track, height: sw, background: off, borderRadius: sw }} />
        <div style={{ position: "absolute", left: x0, top: ty - sw / 2, width: Math.max(0, head - x0), height: sw, background: acc, borderRadius: sw,
          boxShadow: `0 0 ${(0.012 * H).toFixed(1)}px ${hexA(acc, 0.6)}` }} />
        {data.map((d, i) => {
          const seen = c01((track * (x1 - x0) + x0 - xs[i]) / (0.05 * bw));
          const lit = pr(lt, at[i], 0.45);
          const [yr, cap] = yearOf(d.l);
          const up = i % 2 === 0;
          return (
            <React.Fragment key={i}>
              <div style={{ position: "absolute", left: xs[i], top: ty, width: sw * 3.2, height: sw * 3.2, borderRadius: "50%",
                transform: `translate(-50%, -50%) scale(${(seen * (1 + 0.35 * Math.sin(Math.PI * c01(lit)))).toFixed(3)})`,
                background: lit > 0.5 ? acc : "#0c0d10", border: `${sw * 0.7}px solid ${lit > 0.5 ? ink : alt}` }} />
              <div style={{ position: "absolute", left: xs[i], top: up ? ty - sw * 3 : ty + sw * 3, transform: `translate(-50%, ${up ? "-100%" : "0%"})`,
                textAlign: "center", opacity: seen * (0.35 + 0.65 * lit), whiteSpace: "nowrap" }}>
                <div style={{ fontFamily: nf, fontWeight: 800, fontSize: fs * 1.5, lineHeight: 1, color: lit > 0.5 ? ink : alt, textShadow: shadow(H),
                  transform: `scale(${(0.85 + 0.15 * lit).toFixed(3)})` }}>{yr}</div>
                {cap ? <div style={{ fontFamily: lf, fontWeight: 700, fontSize: fs * 0.75, color: lit > 0.5 ? acc : alt, textTransform: "uppercase",
                  letterSpacing: "0.07em", marginTop: fs * 0.2, textShadow: shadow(H) }}>{cap}</div> : null}
              </div>
            </React.Fragment>
          );
        })}
        <div style={{ position: "absolute", left: head, top: ty, width: sw * 2.6, height: sw * 2.6, background: ink, transform: "translate(-50%, -50%) rotate(45deg)",
          boxShadow: `0 0 ${(0.016 * H).toFixed(1)}px ${acc}`, opacity: track }} />
      </div>
    );
  }

  // ladder: data[0] is #1 (the top); the recipe lands the rows from the bottom up
  const rowH = bh / n, gap = rowH * 0.14;
  return (
    <div style={{ position: "relative", width: bw, height: bh }}>
      {data.map((d, i) => {
        const p = pr(lt, at[i], 0.65, L.ease || "expoOut");
        const first = i === 0;
        const glow = first ? pr(lt, at[i] + 0.3, 0.6) : 0;
        const h = rowH - gap;
        return (
          <div key={i} style={{ position: "absolute", left: 0, top: i * rowH, width: bw, height: h, display: "flex", alignItems: "center",
            opacity: c01(p * 1.5), transform: `translateX(${((1 - p) * -0.05 * W).toFixed(2)}px) scale(${first ? (1 + 0.03 * Math.sin(Math.PI * glow)).toFixed(4) : 1})`,
            filter: p < 0.97 ? `blur(${((1 - p) * 10 * H / 1080).toFixed(2)}px)` : undefined, transformOrigin: "0% 50%" }}>
            <div style={{ width: h * 1.25, height: h, flex: "none", background: first ? acc : hexA("#0b0c10", 0.78), color: first ? onAcc : acc,
              display: "flex", alignItems: "center", justifyContent: "center", fontFamily: nf, fontWeight: 800, fontSize: h * 0.5,
              borderRadius: `${h * 0.12}px 0 0 ${h * 0.12}px` }}>#{i + 1}</div>
            <div style={{ flex: 1, height: h, display: "flex", alignItems: "center", justifyContent: "space-between", padding: `0 ${(h * 0.4).toFixed(1)}px`,
              background: first ? `linear-gradient(90deg, ${hexA(acc, 0.32)}, ${hexA("#0b0c10", 0.6)})` : hexA("#0b0c10", 0.58), backdropFilter: "blur(12px)",
              borderRadius: `0 ${h * 0.12}px ${h * 0.12}px 0`, boxShadow: first ? `0 0 ${(0.03 * H * glow).toFixed(1)}px ${hexA(acc, 0.55)}` : undefined }}>
              <div style={{ fontFamily: lf, fontWeight: 800, fontSize: Math.min(fs * 1.25, h * 0.46), color: ink, textTransform: "uppercase",
                letterSpacing: "0.04em", whiteSpace: "nowrap", overflow: "hidden" }}>{d.l}</div>
              {d.v !== null ? <div style={{ fontFamily: nf, fontWeight: 800, fontSize: Math.min(fs * 1.2, h * 0.44), color: first ? acc : alt,
                fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>{fig(d, L, (d.v ?? 0) * c01(p))}</div> : null}
            </div>
          </div>
        );
      })}
    </div>
  );
};

// ================================================================== cards
export const CardBody: React.FC<{ layer: Layer; ctx: XCtx }> = ({ layer: L, ctx }) => {
  const { W, H, t } = ctx;
  const lt = t - L.from;
  const w = L.w * W;
  const fs = (L.size || 0.032) * H;
  const paper = L.fill || "#ffffff", ink = L.color, acc = L.emphColor || "#f2b630";
  const mid = L.mid ?? 1;
  const tf = faceOf(L.font), lf = faceOf(L.font2 || "narrow", NARROW);
  const words = (L.text || "").split(/\s+/).filter(Boolean);
  const wordsAt = (i: number) => (L.times && typeof L.times[i] === "number" ? L.times[i] : 0.4 + i * 0.12);

  if (L.card === "sticky") {
    const chars = (L.text || "").length;
    const write = c01((lt - mid) / Math.max(0.4, chars * 0.035));
    return (
      <div style={{ position: "relative", width: w, height: w, background: `linear-gradient(160deg, ${paper} 0%, ${paper} 70%, ${hexA("#000000", 0.08)} 100%), ${paper}`,
        boxShadow: `${drop(H)}, inset 0 -${(0.02 * H).toFixed(1)}px ${(0.03 * H).toFixed(1)}px ${hexA("#000000", 0.08)}`, padding: w * 0.1, boxSizing: "border-box",
        display: "flex", flexDirection: "column", justifyContent: "center", borderRadius: `2px 2px ${(w * 0.06).toFixed(0)}px 2px` }}>
        <div style={{ position: "absolute", left: "50%", top: -w * 0.05, width: w * 0.38, height: w * 0.11, background: "rgba(255,255,255,0.55)",
          transform: "translateX(-50%) rotate(-3deg)", boxShadow: "0 1px 3px rgba(0,0,0,0.15)" }} />
        <div style={{ fontFamily: HAND, fontWeight: 700, fontSize: fs, lineHeight: 1.08, color: ink, clipPath: `inset(0 0 0 0)` }}>
          {Array.from(L.text || "").map((ch, i) => <span key={i} style={{ opacity: i / Math.max(1, chars) < write ? 1 : 0 }}>{ch}</span>)}
        </div>
        {L.label ? <div style={{ fontFamily: HAND, fontSize: fs * 0.55, color: hexA(ink === "#ffffff" ? "#222222" : ink, 0.7), marginTop: fs * 0.5,
          opacity: c01((write - 0.85) / 0.15) }}>— {L.label}</div> : null}
        <svg width={w * 0.5} height={fs * 0.5} style={{ position: "absolute", left: w * 0.1, bottom: w * 0.1, overflow: "visible" }}>
          <path d={`M0,${fs * 0.3} Q${w * 0.25},${-fs * 0.1} ${w * 0.5},${fs * 0.25}`} fill="none" stroke={acc} strokeWidth={fs * 0.12} strokeLinecap="round"
            pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - c01((write - 0.7) / 0.3)} />
        </svg>
      </div>
    );
  }

  if (L.card === "polaroid") {
    const pw = w * 0.88, ph = pw * 0.82;
    const dev = c01((lt - mid) / 1.6);
    return (
      <div style={{ width: w, borderStyle: "solid", borderColor: "#f7f5ef", borderWidth: `${(w * 0.06).toFixed(1)}px ${(w * 0.06).toFixed(1)}px ${(w * 0.2).toFixed(1)}px`,
        boxSizing: "border-box", boxShadow: `${drop(H)}, inset 0 0 0 1px rgba(0,0,0,0.25)`, position: "relative" }}>
        <div style={{ position: "relative", width: pw, height: ph, overflow: "hidden", background: L.src ? "#222" : "transparent",
          backdropFilter: "sepia(0.35) contrast(1.12) saturate(0.85) brightness(1.04)" }}>
          {L.src ? <SafeImg src={L.src} style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : null}
          <div style={{ position: "absolute", inset: 0, background: `rgba(240,236,226,${(0.96 * (1 - easeOf("inOut")(dev))).toFixed(3)})` }} />
          <div style={{ position: "absolute", inset: 0, boxShadow: "inset 0 0 40px rgba(0,0,0,0.35)" }} />
        </div>
        <div style={{ position: "absolute", left: 0, right: 0, bottom: -w * 0.155, textAlign: "center", fontFamily: HAND, fontWeight: 700, fontSize: fs,
          color: "#262626", opacity: c01((lt - mid - 0.6) / 0.6), whiteSpace: "nowrap", overflow: "hidden" }}>{L.text}</div>
      </div>
    );
  }

  if (L.card === "doc") {
    const h = (L.h || 0.9) * H;
    const lines = 16;
    const hlRow = 7;
    const hl = pr(lt, mid, 0.7, "inOut");
    const rows = Array.from({ length: lines }, (_, i) => i);
    const lh = (h * 0.62) / lines;
    return (
      <div style={{ position: "relative", width: w, height: h, background: paper, boxShadow: drop(H), padding: `${(w * 0.09).toFixed(1)}px`, boxSizing: "border-box", overflow: "hidden" }}>
        <div style={{ fontFamily: TYPEWRITER, fontWeight: 700, fontSize: lh * 0.62, letterSpacing: "0.12em", color: hexA("#000000", 0.75),
          textTransform: "uppercase", borderBottom: `2px solid ${hexA("#000000", 0.6)}`, paddingBottom: lh * 0.4, marginBottom: lh * 0.6,
          display: "flex", justifyContent: "space-between" }}><span>{L.label || "Report"}</span><span>{L.meta || ""}</span></div>
        {rows.map((i) => i === hlRow ? (
          <div key={i} style={{ position: "relative", height: lh * 2.2, display: "flex", alignItems: "center", margin: `${(lh * 0.2).toFixed(1)}px 0` }}>
            <div style={{ position: "absolute", left: -lh * 0.3, top: lh * 0.25, bottom: lh * 0.25, width: `calc(${(hl * 100).toFixed(2)}% + ${(lh * 0.6).toFixed(1)}px)`,
              background: hexA(acc.startsWith("#") ? acc : "#f2b630", 0.62), mixBlendMode: "multiply", borderRadius: 2 }} />
            <div style={{ position: "relative", fontFamily: TYPEWRITER, fontWeight: 700, fontSize: lh * 0.95, color: "#141414", lineHeight: 1.05 }}>{L.text}</div>
          </div>
        ) : (
          <div key={i} style={{ height: lh * 0.36, margin: `${(lh * 0.32).toFixed(1)}px 0`, width: `${(62 + 36 * rand((L.seed || 1) * 97 + i)).toFixed(1)}%`,
            background: hexA("#000000", 0.16), borderRadius: lh }} />
        ))}
      </div>
    );
  }

  if (L.card === "social") {
    const likes = L.valueTo ?? 0;
    const counts = L.valueTo !== undefined;
    const lp = pr(lt, mid, 1.4, "expoOut");
    const heart = pr(lt, mid, 0.45, "backOut");
    const dark = /^#(0|1|2)/.test(paper);
    const sub = dark ? "rgba(255,255,255,0.6)" : "rgba(0,0,0,0.55)";
    const initial = (L.label || "?").replace(/^@/, "").charAt(0).toUpperCase();
    const ico: React.CSSProperties = { display: "inline-flex", alignItems: "center", gap: fs * 0.3 };
    const icon = (dd: string, fill = "none") => (
      <svg width={fs * 0.85} height={fs * 0.85} viewBox="0 0 24 24" style={{ overflow: "visible" }}>
        <path d={dd} fill={fill} stroke="currentColor" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
      </svg>
    );
    return (
      <div style={{ width: w, background: paper, borderRadius: 0.018 * H, padding: w * 0.06, boxSizing: "border-box", boxShadow: drop(H), fontFamily: INTER, color: ink }}>
        <div style={{ display: "flex", alignItems: "center", gap: fs * 0.5 }}>
          <div style={{ width: fs * 1.9, height: fs * 1.9, borderRadius: "50%", background: acc, color: "#111", display: "flex", alignItems: "center",
            justifyContent: "center", fontWeight: 800, fontSize: fs * 0.95, flex: "none", overflow: "hidden" }}>
            {L.src ? <SafeImg src={L.src} style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : initial}</div>
          <div style={{ lineHeight: 1.15 }}>
            <div style={{ fontWeight: 800, fontSize: fs * 0.82 }}>{(L.label || "").replace(/^@/, "")}</div>
            <div style={{ fontSize: fs * 0.66, color: sub }}>@{(L.label || "user").replace(/^@/, "").replace(/\s+/g, "").toLowerCase()}{L.meta ? ` · ${L.meta}` : ""}</div>
          </div>
        </div>
        <div style={{ fontSize: fs, lineHeight: 1.28, fontWeight: 500, margin: `${(fs * 0.6).toFixed(1)}px 0` }}>
          {words.map((wd, i) => <span key={i} style={{ opacity: c01((lt - wordsAt(i) + 0.05) / 0.2) * 0.85 + 0.15 }}>{wd} </span>)}
        </div>
        <div style={{ display: "flex", gap: fs * 1.6, fontSize: fs * 0.7, color: sub, alignItems: "center", borderTop: `1px solid ${hexA(dark ? "#ffffff" : "#000000", 0.12)}`, paddingTop: fs * 0.5 }}>
          <span style={ico}>{icon("M3 5h18v11H8l-5 4z")}</span>
          <span style={ico}>{icon("M5 9l3-3 3 3M8 6v9h8M19 15l-3 3-3-3M16 18V9H8")}</span>
          <span style={{ ...ico, color: heart > 0.05 ? "#f4245e" : sub }}>
            <span style={{ display: "inline-flex", transform: `scale(${(1 + 0.6 * Math.sin(Math.PI * c01(heart))).toFixed(3)})` }}>
              {icon("M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z", heart > 0.05 ? "#f4245e" : "none")}</span>
            {counts ? formatCount(Math.round(likes * lp), 0) : ""}</span>
        </div>
      </div>
    );
  }

  if (L.card === "phone") {
    const ph = w * 2.05;
    const items = L.items && L.items.length ? L.items : [L.text || ""];
    const scr = "#0f1115";
    return (
      <div style={{ position: "relative", width: w, height: ph, borderRadius: w * 0.16, background: "#050506", padding: w * 0.035, boxSizing: "border-box",
        boxShadow: `${drop(H)}, inset 0 0 0 ${(w * 0.012).toFixed(1)}px #2a2c31` }}>
        <div style={{ position: "relative", width: "100%", height: "100%", borderRadius: w * 0.13, background: scr, overflow: "hidden", fontFamily: INTER }}>
          <div style={{ position: "absolute", left: "50%", top: w * 0.03, width: w * 0.3, height: w * 0.075, borderRadius: w, background: "#000", transform: "translateX(-50%)" }} />
          <div style={{ paddingTop: w * 0.17, textAlign: "center", color: "#fff", fontWeight: 700, fontSize: w * 0.06, borderBottom: "1px solid rgba(255,255,255,0.08)",
            paddingBottom: w * 0.04 }}>
            <div style={{ width: w * 0.16, height: w * 0.16, borderRadius: "50%", background: acc, margin: "0 auto", marginBottom: w * 0.02, color: "#111",
              display: "flex", alignItems: "center", justifyContent: "center", fontSize: w * 0.075 }}>{(L.label || "?").charAt(0).toUpperCase()}</div>
            {L.label || ""}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: w * 0.03, padding: w * 0.05 }}>
            {items.map((m, i) => {
              const at = L.times?.[i] ?? 0.5 + i * 0.9;
              const typing = lt > at - 0.6 && lt < at;
              const p = pr(lt, at, 0.45, "backOut");
              const me = i % 2 === 1;
              if (typing) return (
                <div key={i} style={{ alignSelf: me ? "flex-end" : "flex-start", background: me ? acc : "#262a31", borderRadius: w * 0.06, padding: `${w * 0.035}px ${w * 0.05}px`, display: "flex", gap: w * 0.015 }}>
                  {[0, 1, 2].map((k) => <div key={k} style={{ width: w * 0.022, height: w * 0.022, borderRadius: "50%", background: me ? "#111" : "#aab",
                    opacity: 0.35 + 0.65 * Math.abs(Math.sin(lt * 7 - k * 0.8)) }} />)}
                </div>
              );
              if (p <= 0) return null;
              return (
                <div key={i} style={{ alignSelf: me ? "flex-end" : "flex-start", maxWidth: "80%", background: me ? acc : "#262a31", color: me ? "#111" : "#f2f3f5",
                  borderRadius: w * 0.06, padding: `${(w * 0.035).toFixed(1)}px ${(w * 0.05).toFixed(1)}px`, fontSize: fs, lineHeight: 1.25, fontWeight: 500,
                  transform: `scale(${p.toFixed(3)})`, transformOrigin: me ? "100% 100%" : "0% 100%", opacity: c01(p * 2) }}>{m}</div>
              );
            })}
          </div>
        </div>
      </div>
    );
  }

  if (L.card === "browser") {
    const url = L.label || "news.example.com";
    const typed = c01((lt - 0.3) / Math.max(0.3, url.length * 0.03));
    const hl = pr(lt, mid, 0.7, "inOut");
    const h = (L.h || 0.62) * H;
    const bar = h * 0.085;
    return (
      <div style={{ width: w, height: h, borderRadius: 0.012 * H, overflow: "hidden", background: paper, boxShadow: drop(H), display: "flex", flexDirection: "column" }}>
        <div style={{ height: bar, background: "#e9eaee", display: "flex", alignItems: "center", gap: bar * 0.25, padding: `0 ${(bar * 0.4).toFixed(1)}px`, flex: "none" }}>
          {["#ff5f57", "#febc2e", "#28c840"].map((c) => <div key={c} style={{ width: bar * 0.3, height: bar * 0.3, borderRadius: "50%", background: c }} />)}
          <div style={{ flex: 1, marginLeft: bar * 0.4, height: bar * 0.62, background: "#fff", borderRadius: bar, display: "flex", alignItems: "center",
            padding: `0 ${(bar * 0.4).toFixed(1)}px`, fontFamily: INTER, fontSize: bar * 0.32, color: "#555", whiteSpace: "nowrap", overflow: "hidden" }}>
            {url.slice(0, Math.round(url.length * typed))}{typed < 1 && Math.floor(lt * 3) % 2 ? "|" : ""}</div>
        </div>
        <div style={{ flex: 1, padding: `${(w * 0.05).toFixed(1)}px ${(w * 0.07).toFixed(1)}px`, position: "relative" }}>
          {L.meta ? <div style={{ fontFamily: lf, fontWeight: 800, fontSize: fs * 0.6, letterSpacing: "0.14em", color: acc === "#ffffff" ? "#c00" : acc,
            textTransform: "uppercase", marginBottom: fs * 0.4, opacity: pr(lt, 0.5, 0.5) }}>{L.meta}</div> : null}
          <div style={{ position: "relative", fontFamily: SERIF, fontWeight: 700, fontSize: fs * 1.35, lineHeight: 1.12, color: "#111", ...arrive(pr(lt, 0.55, 0.7), H, 0.02) }}>
            <span style={{ backgroundImage: `linear-gradient(${hexA(acc.startsWith("#") ? acc : "#f2b630", 0.55)}, ${hexA(acc.startsWith("#") ? acc : "#f2b630", 0.55)})`,
              backgroundRepeat: "no-repeat", backgroundSize: `${(hl * 100).toFixed(2)}% 38%`, backgroundPosition: "0 88%", boxDecorationBreak: "clone",
              WebkitBoxDecorationBreak: "clone" }}>{L.text}</span>
          </div>
          {L.src ? <div style={{ marginTop: fs * 0.6, height: h * 0.28, borderRadius: 4, overflow: "hidden", background: "#ddd" }}>
            <SafeImg src={L.src} style={{ width: "100%", height: "100%", objectFit: "cover" }} /></div> : null}
          {[0, 1, 2, 3].map((i) => <div key={i} style={{ height: fs * 0.32, width: `${(70 + 28 * rand((L.seed || 1) * 31 + i)).toFixed(1)}%`, background: "#e3e4e8",
            borderRadius: fs, marginTop: fs * 0.42, opacity: pr(lt, 0.7 + i * 0.06, 0.5) }} />)}
        </div>
      </div>
    );
  }

  // quote card with a portrait (or the speaker's initials)
  const D = fs * 3.6;
  const initials = (L.label || "?").split(/\s+/).map((s) => s.charAt(0)).join("").slice(0, 2).toUpperCase();
  const ring = pr(lt, 0, 0.9, "inOut");
  return (
    <div style={{ width: w, background: hexA("#0b0c10", 0.72), backdropFilter: "blur(16px)", borderRadius: 0.014 * H, padding: `${(fs * 1.1).toFixed(1)}px ${(fs * 1.3).toFixed(1)}px`,
      boxSizing: "border-box", display: "flex", gap: fs * 1.1, alignItems: "center", boxShadow: drop(H), borderLeft: `${Math.max(3, 0.005 * H).toFixed(1)}px solid ${acc}` }}>
      <div style={{ position: "relative", width: D, height: D, flex: "none" }}>
        <svg width={D} height={D} style={{ position: "absolute", inset: 0, overflow: "visible", transform: "rotate(-90deg)" }}>
          <circle cx={D / 2} cy={D / 2} r={D / 2} fill="none" stroke={acc} strokeWidth={Math.max(3, 0.004 * H)} pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - ring} />
        </svg>
        <div style={{ position: "absolute", inset: D * 0.06, borderRadius: "50%", overflow: "hidden", background: `linear-gradient(135deg, ${hexA(acc, 0.9)}, ${hexA(acc, 0.45)})`,
          display: "flex", alignItems: "center", justifyContent: "center", fontFamily: tf, fontWeight: 800, fontSize: D * 0.32, color: "#111", opacity: c01(ring * 1.5) }}>
          {L.src ? <SafeImg src={L.src} style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : initials}
        </div>
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ fontFamily: SERIF, fontWeight: 700, fontSize: fs * 2.4, lineHeight: 0.6, color: acc, height: fs * 0.9 }}>“</div>
        <div style={{ fontFamily: SERIF_ITALIC, fontSize: fs * 1.05, lineHeight: 1.25, color: ink }}>
          {words.map((wd, i) => {
            const p = pr(lt, wordsAt(i), 0.5);
            return <span key={i} style={{ display: "inline-block", whiteSpace: "pre", opacity: c01(p * 1.3), transform: `translateY(${((1 - p) * 0.3 * fs).toFixed(2)}px)`,
              filter: p < 0.95 ? `blur(${((1 - p) * 4).toFixed(2)}px)` : undefined }}>{wd}{i < words.length - 1 ? " " : ""}</span>;
          })}
        </div>
        {L.label ? <div style={{ fontFamily: lf, fontWeight: 800, fontSize: fs * 0.62, letterSpacing: "0.14em", textTransform: "uppercase", color: acc,
          marginTop: fs * 0.6, opacity: pr(lt, mid, 0.5) }}>{L.label}{L.meta ? <span style={{ color: hexA("#ffffff", 0.6), fontWeight: 600 }}> · {L.meta}</span> : null}</div> : null}
      </div>
    </div>
  );
};

// ================================================================== full-frame effects
export const FxBody: React.FC<{ layer: Layer; ctx: XCtx }> = ({ layer: L, ctx }) => {
  const uid = React.useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const { W, H, t } = ctx;
  const lt = t - L.from;
  const D = Math.max(0.2, L.to - L.from);
  const mid = L.mid ?? D / 2;
  const col = L.color, col2 = L.color2 || "#000000", acc = L.fill || "#f2b630";
  const seed = L.seed || 1;
  const id = `fx${uid}`;
  const diag = Math.hypot(W, H);

  if (L.effect === "ink") {
    // In: ink blots bloom from three points until they cover the frame at the cut; out: a hole bleeds open from the centre.
    const pin = easeOf("in")(c01(lt / mid));
    const pout = easeOf("out")(c01((lt - mid) / Math.max(0.05, D - mid)));
    const pts = [0, 1, 2].map((k) => [W * (0.15 + 0.7 * rand(seed * 7 + k)), H * (0.15 + 0.7 * rand(seed * 11 + k))]);
    return (
      <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
        <defs>
          <filter id={`${id}f`} x="-20%" y="-20%" width="140%" height="140%">
            <feTurbulence type="fractalNoise" baseFrequency={0.012} numOctaves={3} seed={seed % 97} />
            <feDisplacementMap in="SourceGraphic" scale={0.12 * H} xChannelSelector="R" yChannelSelector="G" result="d" />
            <feGaussianBlur in="d" stdDeviation={0.0025 * H} />
          </filter>
          <mask id={`${id}m`}>
            <rect width={W} height={H} fill="white" />
            {pout > 0 ? <circle cx={W / 2} cy={H / 2} r={pout * diag * 0.62} fill="black" filter={`url(#${id}f)`} /> : null}
          </mask>
        </defs>
        <g mask={`url(#${id}m)`}>
          {lt < mid ? pts.map(([x, y], k) => <circle key={k} cx={x} cy={y} r={Math.max(0, pin * diag * (0.72 - k * 0.08) - k * 0.02 * diag)} fill={col} filter={`url(#${id}f)`} />)
            : <rect width={W} height={H} fill={col} />}
        </g>
      </svg>
    );
  }

  if (L.effect === "burn") {
    const peak = 1 - Math.min(1, Math.abs(lt - mid) / (D * 0.5));
    const flick = 0.85 + 0.15 * Math.sin(lt * 41 + seed) * Math.sin(lt * 17);
    const blobs = [0, 1, 2, 3].map((k) => {
      const fromLeft = rand(seed + k * 5) > 0.5;
      const x = (fromLeft ? -0.2 : 1.2) + (fromLeft ? 1 : -1) * (0.45 + 0.4 * rand(seed + k * 9)) * c01(lt / D) * 1.2;
      const y = 0.2 + 0.6 * rand(seed + k * 13) + 0.1 * Math.sin(lt * 2 + k);
      const r = (0.35 + 0.35 * rand(seed + k * 3)) * (0.5 + peak);
      return { x, y, r, hot: k % 2 === 0 };
    });
    return (
      <div style={{ position: "absolute", inset: 0, mixBlendMode: "screen" }}>
        {blobs.map((b, k) => (
          <div key={k} style={{ position: "absolute", left: b.x * W - b.r * H, top: b.y * H - b.r * H, width: b.r * 2 * H, height: b.r * 2 * H, borderRadius: "50%",
            background: `radial-gradient(circle, ${b.hot ? "rgba(255,244,214,1)" : "rgba(255,170,60,0.95)"} 0%, rgba(255,110,20,0.75) 35%, rgba(200,40,10,0.35) 60%, rgba(0,0,0,0) 72%)`,
            opacity: c01(peak * 1.6) * flick, filter: `blur(${(0.03 * H).toFixed(1)}px)` }} />
        ))}
        <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at 50% 50%, rgba(255,250,235,${(0.95 * peak ** 4).toFixed(3)}) 0%, rgba(255,160,60,${(0.85 * peak ** 3).toFixed(3)}) 60%, rgba(120,20,0,${(0.6 * peak ** 2).toFixed(3)}) 100%)` }} />
      </div>
    );
  }

  if (L.effect === "glitch") {
    const env = 1 - Math.min(1, Math.abs(lt - mid) / (D * 0.5));
    const frame = Math.floor(lt * 24);
    const slices = 9;
    const out: React.ReactNode[] = [];
    for (let k = 0; k < slices; k++) {
      const r1 = rand(seed * 101 + frame * 13 + k), r2 = rand(seed * 37 + frame * 7 + k * 3);
      if (r1 > 0.35 + 0.55 * env) continue;
      const y = r2 * H, h = (0.01 + 0.07 * rand(frame * 3 + k)) * H;
      const dx = (rand(frame * 17 + k) - 0.5) * 0.12 * W * env;
      const kind = k % 3;
      out.push(<div key={k} style={{ position: "absolute", left: kind === 0 ? 0 : dx, top: y, width: W, height: h,
        ...(kind === 0 ? { backdropFilter: `invert(1) hue-rotate(${Math.round(rand(frame + k) * 180)}deg)` }
          : { background: kind === 1 ? col : acc, opacity: 0.55, backdropFilter: "saturate(3) contrast(1.4)" }) }} />);
    }
    const flash = env > 0.92 ? (env - 0.92) / 0.08 : 0;
    return (
      <div style={{ position: "absolute", inset: 0 }}>
        <div style={{ position: "absolute", inset: 0, background: col2, opacity: 0.35 * env * env }} />
        {out}
        <div style={{ position: "absolute", inset: 0, backgroundImage: "repeating-linear-gradient(0deg, rgba(0,0,0,0.25) 0px, rgba(0,0,0,0.25) 2px, transparent 2px, transparent 5px)", opacity: env }} />
        <div style={{ position: "absolute", inset: 0, background: "#fff", opacity: flash * 0.7, mixBlendMode: "screen" }} />
      </div>
    );
  }

  if (L.effect === "tear") {
    // A sheet of paper with torn edges slides across: its leading edge covers the frame by the cut, its trailing edge reveals the next shot.
    const p = easeOf("inOut")(c01(lt / D));
    const dir = seed % 2 ? -1 : 1;
    const sheetW = W * 1.5;
    const x = dir > 0 ? -sheetW + p * (W + sheetW) : W - p * (W + sheetW);
    const edge = (side: number) => {
      const pts: string[] = [];
      const steps = 28;
      for (let i = 0; i <= steps; i++) {
        const yy = (i / steps) * H;
        const j = (rand(seed * 53 + i + side * 999) - 0.5) * 0.045 * W + Math.sin(i * 0.9 + side) * 0.012 * W;
        pts.push(`${(side > 0 ? sheetW + j : j).toFixed(1)},${yy.toFixed(1)}`);
      }
      return pts;
    };
    const right = edge(1), left = edge(-1);
    const poly = [...left, ...right.reverse()].join(" ");
    const fiber = (pts: string[], off: number) => pts.map((s) => { const [a, b] = s.split(","); return `${(Number(a) + off).toFixed(1)},${b}`; }).join(" ");
    return (
      <svg width={W} height={H} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
        <g transform={`translate(${x.toFixed(1)},0)`} style={{ filter: `drop-shadow(0 0 ${(0.02 * H).toFixed(1)}px rgba(0,0,0,0.55))` }}>
          <polygon points={poly} fill={col} />
          <polyline points={fiber(edge(1), -0.006 * W)} fill="none" stroke="#f4efe4" strokeWidth={0.008 * W} opacity={0.9} />
          <polyline points={fiber(edge(-1), 0.006 * W)} fill="none" stroke="#f4efe4" strokeWidth={0.008 * W} opacity={0.9} />
        </g>
      </svg>
    );
  }

  if (L.effect === "blocks") {
    const cols = 16, rows = 9;
    const cw = W / cols, ch = H / rows;
    const cells: React.ReactNode[] = [];
    for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
      const k = r * cols + c;
      const a = rand(seed * 7 + k) * 0.7 + (c / cols) * 0.3;
      const b = rand(seed * 13 + k * 3) * 0.7 + (c / cols) * 0.3;
      const pin = c01((lt - a * mid * 0.85) / (mid * 0.25));
      const pout = c01((lt - mid - b * (D - mid) * 0.8) / ((D - mid) * 0.25));
      const s = pin * (1 - pout);
      if (s <= 0.001) continue;
      const fill = rand(seed * 3 + k * 7) > 0.82 ? acc : rand(seed * 5 + k) > 0.5 ? col : col2;
      cells.push(<div key={k} style={{ position: "absolute", left: c * cw, top: r * ch, width: cw + 1, height: ch + 1, background: fill, transform: `scale(${s.toFixed(3)})` }} />);
    }
    return <div style={{ position: "absolute", inset: 0 }}>{cells}</div>;
  }

  if (L.effect === "lens") {
    // A magnifier glides onto the point: the rest of the shot blurs and dims, the lens stays sharp and a touch richer.
    const x = L.x * W, y = L.y * H;
    const r = (L.w || 0.16) * H;
    const p = pr(lt, mid - 0.2, 0.9);
    const cx = x + (1 - p) * 0.12 * W * (seed % 2 ? 1 : -1), cy = y + (1 - p) * 0.08 * H;
    const out = c01((lt - (D - 0.45)) / 0.45);
    const k = p * (1 - out);
    const hole = `radial-gradient(circle ${r.toFixed(1)}px at ${cx.toFixed(1)}px ${cy.toFixed(1)}px, transparent 98%, black 100%)`;
    const ang = 0.78;
    return (
      <div style={{ position: "absolute", inset: 0 }}>
        <div style={{ position: "absolute", inset: 0, backdropFilter: `blur(${(10 * k).toFixed(2)}px) brightness(${(1 - 0.42 * k).toFixed(3)}) saturate(${(1 - 0.4 * k).toFixed(3)})`,
          WebkitMaskImage: hole, maskImage: hole, background: `rgba(0,0,0,${(0.12 * k).toFixed(3)})` }} />
        <div style={{ position: "absolute", left: cx - r, top: cy - r, width: r * 2, height: r * 2, borderRadius: "50%", opacity: k,
          backdropFilter: "contrast(1.12) saturate(1.25) brightness(1.06)",
          background: "radial-gradient(circle at 32% 28%, rgba(255,255,255,0.28) 0%, rgba(255,255,255,0) 38%)",
          border: `${Math.max(4, 0.012 * H).toFixed(1)}px solid ${acc}`, boxShadow: `0 0 0 ${(0.004 * H).toFixed(1)}px rgba(0,0,0,0.6), 0 ${(0.015 * H).toFixed(1)}px ${(0.05 * H).toFixed(1)}px rgba(0,0,0,0.6)` }} />
        <div style={{ position: "absolute", left: cx + Math.cos(ang) * r * 1.02, top: cy + Math.sin(ang) * r * 1.02, width: r * 0.85, height: r * 0.2,
          background: `linear-gradient(180deg, ${col2 === "#000000" ? "#2b2d33" : col2}, #111)`, borderRadius: r * 0.1, transformOrigin: "0% 50%",
          transform: `translateY(-50%) rotate(${(ang * 180 / Math.PI).toFixed(2)}deg)`, opacity: k, boxShadow: drop(H) }} />
      </div>
    );
  }

  // split: before (left, an old print: black and white, grain) | after (right, the shot as it is); the handle slides in and settles
  const p1 = pr(lt, 0.1, 0.9, "expoOut");
  const wob = lt > 1.0 ? Math.sin((lt - 1.0) * 2.6) * 0.06 * Math.exp(-(lt - 1.0) * 1.1) : 0;
  const sx = (L.x || 0.5) * p1 + wob;
  const X = sx * W;
  const fs = (L.size || 0.03) * H;
  const lab = (L.items && L.items.length >= 2 ? L.items : ["Before", "After"]);
  const lp = pr(lt, 0.7, 0.5);
  const out = c01((lt - (D - 0.4)) / 0.4);
  return (
    <div style={{ position: "absolute", inset: 0, opacity: 1 - out }}>
      <div style={{ position: "absolute", left: 0, top: 0, width: X, height: H, backdropFilter: "grayscale(1) sepia(0.25) contrast(1.15) brightness(0.88)" }} />
      <div style={{ position: "absolute", left: X, top: 0, width: Math.max(3, 0.004 * H), height: H, background: "#fff", transform: "translateX(-50%)",
        boxShadow: "0 0 18px rgba(0,0,0,0.6)" }} />
      <div style={{ position: "absolute", left: X, top: H / 2, width: 0.07 * H, height: 0.07 * H, borderRadius: "50%", background: "#fff",
        transform: "translate(-50%, -50%)", display: "flex", alignItems: "center", justifyContent: "center", gap: 0.008 * H, boxShadow: drop(H),
        color: "#111", fontFamily: INTER, fontWeight: 800, fontSize: 0.03 * H }}>‹ ›</div>
      {[0, 1].map((k) => (
        <div key={k} style={{ position: "absolute", top: 0.08 * H, [k ? "right" : "left"]: 0.05 * W, fontFamily: faceOf(L.font, NARROW), fontWeight: 800,
          fontSize: fs, letterSpacing: "0.12em", textTransform: "uppercase", color: k ? "#111" : "#fff", background: k ? acc : "rgba(0,0,0,0.6)",
          padding: "0.25em 0.6em 0.2em", borderRadius: fs * 0.2, opacity: lp, transform: `translateY(${((1 - lp) * -0.02 * H).toFixed(1)}px)` }}>{lab[k]}</div>
      ))}
    </div>
  );
};

// ================================================================== hand-drawn marks
export const ScribbleBody: React.FC<{ layer: Layer; ctx: XCtx; draw: number }> = ({ layer: L, ctx, draw }) => {
  const { W, H } = ctx;
  const bw = L.w * W, bh = L.h * H;
  const seed = L.seed || 1;
  const sw = (L.stroke ?? 0.007) * H;
  const j = (k: number, a: number) => (rand(seed * 71 + k) - 0.5) * a;
  const glow = `drop-shadow(0 0 ${(0.004 * H).toFixed(1)}px rgba(0,0,0,0.55))`;
  if (L.scribble === "swoosh") {
    // A tapered brush stroke: thick in the middle, a flick up at the end; revealed left to right.
    const N = 24;
    const top: string[] = [], bot: string[] = [];
    for (let i = 0; i <= N; i++) {
      const u = i / N;
      const x = u * bw, y = bh * (0.55 - 0.25 * u * u + 0.05 * Math.sin(u * 3 + seed));
      const th = bh * 0.5 * Math.sin(Math.PI * Math.min(1, u * 1.05)) ** 0.6 + 1;
      top.push(`${x.toFixed(1)},${(y - th / 2).toFixed(1)}`);
      bot.unshift(`${x.toFixed(1)},${(y + th / 2).toFixed(1)}`);
    }
    return (
      <svg width={bw} height={bh} style={{ overflow: "visible", filter: glow, clipPath: `inset(-50% ${((1 - draw) * 100).toFixed(2)}% -50% -5%)` }}>
        <polygon points={[...top, ...bot].join(" ")} fill={L.color} />
      </svg>
    );
  }
  let d = "";
  if (L.scribble === "loop") {
    // Two rough passes round an ellipse that never quite close - a marker circle drawn fast by hand.
    const cx = bw / 2, cy = bh / 2, rx = bw / 2, ry = bh / 2;
    const turns = 1.75, steps = 60, a0 = -2.2 + j(1, 0.6);
    for (let i = 0; i <= steps; i++) {
      const u = i / steps, a = a0 + u * turns * Math.PI * 2;
      const wob = 1 + 0.06 * Math.sin(a * 2.3 + seed) + (u > 0.55 ? -0.07 : 0.02) + j(i, 0.02);
      const x = cx + Math.cos(a) * rx * wob, y = cy + Math.sin(a) * ry * wob * (1 + 0.05 * u);
      d += `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
    }
  } else if (L.scribble === "strike") {
    const y0 = bh * 0.55;
    d = `M${(-0.03 * bw).toFixed(1)},${(y0 + j(1, bh * 0.2)).toFixed(1)} Q${(bw * 0.5).toFixed(1)},${(y0 - bh * 0.12).toFixed(1)} ${(bw * 1.03).toFixed(1)},${(y0 + j(2, bh * 0.2)).toFixed(1)}`
      + ` M${(bw * 1.0).toFixed(1)},${(y0 + bh * 0.12).toFixed(1)} Q${(bw * 0.5).toFixed(1)},${(y0 + bh * 0.02).toFixed(1)} ${(-0.02 * bw).toFixed(1)},${(y0 + bh * 0.2).toFixed(1)}`;
  } else {
    // looparrow: from the box's start corner, one loop, into the end corner (layer.items unused); (0,1) -> (1,0)
    const flip = (seed % 2) ? -1 : 1;
    const P = (x: number, y: number) => `${(flip > 0 ? x * bw : (1 - x) * bw).toFixed(1)},${(y * bh).toFixed(1)}`;
    d = `M${P(0, 1)} C${P(0.25, 0.95)} ${P(0.55, 0.85)} ${P(0.55, 0.55)} C${P(0.55, 0.3)} ${P(0.3, 0.32)} ${P(0.34, 0.52)} C${P(0.4, 0.75)} ${P(0.8, 0.5)} ${P(1, 0)}`;
  }
  // the head for the looping arrow
  let head: React.ReactNode = null;
  if (L.scribble === "looparrow" && draw > 0.92) {
    const flip = (seed % 2) ? -1 : 1;
    const ex = flip > 0 ? bw : 0, ey = 0;
    const ang = Math.atan2(-0.5 * bh, (flip > 0 ? 0.2 : -0.2) * bw);
    const hl = 0.03 * H * c01((draw - 0.92) / 0.08);
    head = <path d={`M${(ex - hl * Math.cos(ang - 0.5)).toFixed(1)},${(ey - hl * Math.sin(ang - 0.5)).toFixed(1)} L${ex},${ey} L${(ex - hl * Math.cos(ang + 0.5)).toFixed(1)},${(ey - hl * Math.sin(ang + 0.5)).toFixed(1)}`}
      fill="none" stroke={L.color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" />;
  }
  return (
    <svg width={bw} height={bh} style={{ overflow: "visible", filter: glow }}>
      <path d={d} fill="none" stroke={L.color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" pathLength={1} strokeDasharray="1 1"
        strokeDashoffset={1 - draw} opacity={0.96} />
      {head}
    </svg>
  );
};

