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
/** "#rrggbb" mixed toward white by f (0..1); anything else unchanged. */
const lift = (c: string, f: number): string => {
  const m = /^#([0-9a-f]{6})$/i.exec(c);
  if (!m) return c;
  const n = parseInt(m[1], 16);
  const ch = (v: number) => Math.round(v + (255 - v) * f).toString(16).padStart(2, "0");
  return `#${ch((n >> 16) & 255)}${ch((n >> 8) & 255)}${ch(n & 255)}`;
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
    // Polished 2026-10-18 (round 2): the quoted line is the page's centre and its largest type (layer.size); the
    // typed rows around it are quiet grey; the accent marker lands under each word on its time (layer.times, never
    // before `mid`), so the push-in - which scales about the page's centre - always lands on the line being read.
    const h = (L.h || 0.8) * H;
    const padX = w * 0.09;
    const head = Math.max(0.03 * H, fs * 0.46);
    const marker = hexA(acc.startsWith("#") ? acc : "#f2b630", 0.7);
    const row = (i: number, k: number) => (
      <div key={`${k}-${i}`} style={{ height: fs * 0.2, margin: `${(fs * 0.24).toFixed(1)}px 0`, width: `${(58 + 40 * rand((L.seed || 1) * 97 + k * 31 + i)).toFixed(1)}%`,
        background: hexA("#000000", 0.13), borderRadius: fs }} />
    );
    return (
      <div style={{ position: "relative", width: w, height: h, background: `linear-gradient(178deg, ${lift(paper.startsWith("#") ? paper : "#f6f2e8", 0.25)} 0%, ${paper} 55%, #ece6d8 100%)`,
        boxShadow: `${drop(H)}, inset 0 0 ${(0.05 * H).toFixed(1)}px rgba(120,100,60,0.18)`, padding: `${(h * 0.07).toFixed(1)}px ${padX.toFixed(1)}px`,
        boxSizing: "border-box", overflow: "hidden", display: "flex", flexDirection: "column" }}>
        <div style={{ fontFamily: TYPEWRITER, fontWeight: 700, fontSize: head, letterSpacing: "0.14em", color: hexA("#000000", 0.78), lineHeight: 1,
          textTransform: "uppercase", borderBottom: `${Math.max(2, 0.003 * H).toFixed(1)}px solid ${hexA("#000000", 0.7)}`, paddingBottom: head * 0.55,
          display: "flex", justifyContent: "space-between", gap: head, whiteSpace: "nowrap", flex: "none" }}>
          <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{L.label || "Report"}</span><span>{L.meta || ""}</span></div>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center" }}>
          {[0, 1, 2].map((i) => row(i, 0))}
          <div style={{ fontFamily: TYPEWRITER, fontWeight: 700, fontSize: fs, lineHeight: 1.3, color: ink, margin: `${(fs * 0.45).toFixed(1)}px 0`, letterSpacing: "-0.01em" }}>
            {words.map((wd, i) => {
              const p = pr(lt, Math.max(mid, wordsAt(i)) - 0.02, 0.22);
              return <span key={i} style={{ backgroundImage: `linear-gradient(${marker}, ${marker})`, backgroundRepeat: "no-repeat",
                backgroundSize: `${(c01(p) * 100).toFixed(2)}% 78%`, backgroundPosition: "0 70%", boxDecorationBreak: "clone", WebkitBoxDecorationBreak: "clone",
                padding: "0 0.06em", margin: "0 -0.06em" }}>{wd}{i < words.length - 1 ? " " : ""}</span>;
            })}
          </div>
          {[0, 1, 2, 3].map((i) => row(i, 1))}
        </div>
      </div>
    );
  }

  if (L.card === "social") {
    const likes = L.valueTo ?? 0;
    const counts = L.valueTo !== undefined;
    // Polished 2026-10-18 (round 2): words wait at 32% (a readable ghost) and light in 0.12 s on their time; the heart
    // fills with one short pulse (no overshoot) on `mid`, the likes rolling up; furniture never under 3% of the height.
    const lp = pr(lt, mid, 0.9, "expoOut");
    const heart = c01((lt - mid) / 0.24);
    const dark = /^#(0|1|2)/.test(paper);
    const sub = dark ? "rgba(255,255,255,0.6)" : "rgba(0,0,0,0.55)";
    const initial = (L.label || "?").replace(/^@/, "").charAt(0).toUpperCase();
    const small = Math.max(0.03 * H, fs * 0.6);
    const ico: React.CSSProperties = { display: "inline-flex", alignItems: "center", gap: small * 0.35 };
    const icon = (dd: string, fill = "none") => (
      <svg width={small * 1.05} height={small * 1.05} viewBox="0 0 24 24" style={{ overflow: "visible" }}>
        <path d={dd} fill={fill} stroke="currentColor" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
      </svg>
    );
    return (
      <div style={{ width: w, background: paper, borderRadius: 0.02 * H, padding: `${(w * 0.055).toFixed(1)}px ${(w * 0.06).toFixed(1)}px`, boxSizing: "border-box",
        boxShadow: `${drop(H)}, 0 0 0 1px rgba(0,0,0,0.06)`, fontFamily: INTER, color: ink }}>
        <div style={{ display: "flex", alignItems: "center", gap: small * 0.6 }}>
          <div style={{ width: small * 2.3, height: small * 2.3, borderRadius: "50%", background: dark ? "#3a3f48" : "#dfe3e8", color: dark ? "#fff" : "#4a5361",
            display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 800, fontSize: small * 1.05, flex: "none", overflow: "hidden" }}>
            {L.src ? <SafeImg src={L.src} style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : initial}</div>
          <div style={{ lineHeight: 1.15, minWidth: 0 }}>
            <div style={{ fontWeight: 800, fontSize: Math.max(0.032 * H, fs * 0.72), whiteSpace: "nowrap", letterSpacing: "-0.01em" }}>{(L.label || "").replace(/^@/, "")}</div>
            <div style={{ fontSize: small, color: sub, whiteSpace: "nowrap" }}>@{(L.label || "user").replace(/^@/, "").replace(/\s+/g, "").toLowerCase()}{L.meta ? ` · ${L.meta}` : ""}</div>
          </div>
        </div>
        <div style={{ fontSize: fs, lineHeight: 1.22, fontWeight: 600, letterSpacing: "-0.012em", margin: `${(fs * 0.5).toFixed(1)}px 0 ${(fs * 0.55).toFixed(1)}px` }}>
          {words.map((wd, i) => <span key={i} style={{ opacity: 0.32 + 0.68 * c01((lt - wordsAt(i) + 0.02) / 0.12) }}>{wd}{i < words.length - 1 ? " " : ""}</span>)}
        </div>
        <div style={{ display: "flex", gap: small * 1.8, fontSize: small, color: sub, alignItems: "center", borderTop: `1px solid ${hexA(dark ? "#ffffff" : "#000000", 0.1)}`,
          paddingTop: small * 0.6, fontVariantNumeric: "tabular-nums" }}>
          <span style={ico}>{icon("M3 5h18v11H8l-5 4z")}</span>
          <span style={ico}>{icon("M5 9l3-3 3 3M8 6v9h8M19 15l-3 3-3-3M16 18V9H8")}</span>
          <span style={{ ...ico, color: heart > 0 ? "#f4245e" : sub, fontWeight: heart > 0 ? 700 : 500 }}>
            <span style={{ display: "inline-flex", transform: `scale(${(1 + 0.22 * Math.sin(Math.PI * heart)).toFixed(3)})` }}>
              {icon("M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z", heart > 0 ? "#f4245e" : "none")}</span>
            {counts ? formatCount(Math.round(likes * lp), 0) : ""}</span>
        </div>
      </div>
    );
  }

  if (L.card === "phone") {
    const ph = w * 2.05;
    const items = L.items && L.items.length ? L.items : [L.text || ""];
    const scr = "#0f1115";
    // Polished 2026-10-18 (round 2): bubbles rise 0.4 em into place in 0.22 s (they popped from scale 0 with an
    // overshoot) and stack from the bottom like a real chat above a reply bar; the contact's name never under 3%.
    const name = Math.max(0.03 * H, w * 0.075);
    return (
      <div style={{ position: "relative", width: w, height: ph, borderRadius: w * 0.16, background: "linear-gradient(145deg, #2b2d33, #050506 40%)", padding: w * 0.032,
        boxSizing: "border-box", boxShadow: `${drop(H)}, inset 0 0 0 ${(w * 0.01).toFixed(1)}px #3a3c42` }}>
        <div style={{ position: "relative", width: "100%", height: "100%", borderRadius: w * 0.13, background: scr, overflow: "hidden", fontFamily: INTER,
          display: "flex", flexDirection: "column" }}>
          <div style={{ position: "absolute", left: "50%", top: w * 0.03, width: w * 0.3, height: w * 0.075, borderRadius: w, background: "#000", transform: "translateX(-50%)" }} />
          <div style={{ paddingTop: w * 0.15, textAlign: "center", color: "#fff", fontWeight: 700, fontSize: name, letterSpacing: "-0.01em", flex: "none",
            borderBottom: "1px solid rgba(255,255,255,0.08)", paddingBottom: w * 0.035, background: "rgba(255,255,255,0.03)" }}>
            <div style={{ width: name * 1.9, height: name * 1.9, borderRadius: "50%", background: "#3a3f48", margin: "0 auto", marginBottom: w * 0.02, color: "#fff",
              display: "flex", alignItems: "center", justifyContent: "center", fontSize: name * 0.9 }}>{(L.label || "?").charAt(0).toUpperCase()}</div>
            {L.label || ""}
          </div>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "flex-end", gap: w * 0.03, padding: `${(w * 0.05).toFixed(1)}px` }}>
            {items.map((m, i) => {
              const at = L.times?.[i] ?? 0.5 + i * 0.9;
              const typing = lt > at - 0.6 && lt < at;
              const p = pr(lt, at, 0.22);
              const me = i % 2 === 1;
              if (typing) return (
                <div key={i} style={{ alignSelf: me ? "flex-end" : "flex-start", background: me ? acc : "#262a31", borderRadius: w * 0.06, padding: `${w * 0.04}px ${w * 0.055}px`, display: "flex", gap: w * 0.018 }}>
                  {[0, 1, 2].map((k) => <div key={k} style={{ width: w * 0.026, height: w * 0.026, borderRadius: "50%", background: me ? "#111" : "#aab",
                    opacity: 0.35 + 0.65 * Math.abs(Math.sin(lt * 7 - k * 0.8)) }} />)}
                </div>
              );
              if (p <= 0) return null;
              return (
                <div key={i} style={{ alignSelf: me ? "flex-end" : "flex-start", maxWidth: "84%", background: me ? acc : "#262a31", color: me ? "#111" : "#f2f3f5",
                  borderRadius: w * 0.06, padding: `${(w * 0.035).toFixed(1)}px ${(w * 0.05).toFixed(1)}px`, fontSize: fs, lineHeight: 1.2, fontWeight: 600,
                  letterSpacing: "-0.01em", transform: `translateY(${((1 - p) * 0.4 * fs).toFixed(2)}px)`, opacity: c01(p * 1.6) }}>{m}</div>
              );
            })}
          </div>
          <div style={{ flex: "none", margin: `0 ${(w * 0.05).toFixed(1)}px ${(w * 0.06).toFixed(1)}px`, height: w * 0.11, borderRadius: w, border: "1px solid rgba(255,255,255,0.16)" }} />
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

  if (L.effect === "ink") {
    // Polished 2026-10-18 (it was three lumpy blots of flat colour): ONE bloom from a point near an edge, its edge
    // finely torn and feathered like ink in water, a thin rim of the accent bleeding ahead of it; it covers the frame
    // at the cut, then a hole bleeds open from the opposite side with the same rim onto the next shot.
    const pin = easeOf("inOut")(c01(lt / mid));
    const pout = easeOf("inOut")(c01((lt - mid) / Math.max(0.05, D - mid)));
    const left = rand(seed * 7) > 0.5;
    const ox = (left ? 0.1 : 0.9) * W, oy = (0.25 + 0.5 * rand(seed * 11)) * H;
    const hx = W - ox, hy = H - oy;
    const reach = Math.hypot(Math.max(ox, W - ox), Math.max(oy, H - oy)) * 1.18;
    const r1 = pin * reach, r2 = pout * reach * 1.12;
    const rim = 1.04;
    const f = `url(#${id}f)`;
    return (
      <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
        <defs>
          <filter id={`${id}f`} x="-25%" y="-25%" width="150%" height="150%">
            <feTurbulence type="fractalNoise" baseFrequency={0.009} numOctaves={4} seed={seed % 97} />
            <feDisplacementMap in="SourceGraphic" scale={0.075 * H} xChannelSelector="R" yChannelSelector="G" result="d" />
            <feGaussianBlur in="d" stdDeviation={0.004 * H} />
          </filter>
          <mask id={`${id}a`}><rect width={W} height={H} fill="white" />{pout > 0 ? <circle cx={hx} cy={hy} r={r2} fill="black" filter={f} /> : null}</mask>
          <mask id={`${id}b`}><rect width={W} height={H} fill="white" />{pout > 0 ? <circle cx={hx} cy={hy} r={r2 * rim} fill="black" filter={f} /> : null}</mask>
        </defs>
        {lt < mid ? (
          <g>
            <circle cx={ox} cy={oy} r={r1 * rim} fill={col2} opacity={0.42} filter={f} />
            <circle cx={ox} cy={oy} r={r1} fill={col} filter={f} />
            <circle cx={ox + (W / 2 - ox) * 0.5} cy={oy + (H / 2 - oy) * 0.3} r={Math.max(0, (pin - 0.2) / 0.8) * reach * 0.55} fill={col} filter={f} />
          </g>
        ) : (
          <g>
            <rect width={W} height={H} fill={col2} opacity={0.42} mask={`url(#${id}a)`} />
            <rect width={W} height={H} fill={col} mask={`url(#${id}b)`} />
          </g>
        )}
      </svg>
    );
  }

  if (L.effect === "burn") {
    // Polished 2026-10-18 (orange blobs washed over everything): a real light leak - a warm, skewed band of light
    // sweeping across in screen blend with a glow from one corner and two gate streaks, peaking in a warm white
    // flash that hides the cut, then cooling off.
    const env = 1 - Math.min(1, Math.abs(lt - mid) / Math.max(0.05, D * 0.5));
    const e = env * env * (3 - 2 * env);
    const dir = seed % 2 ? 1 : -1;
    const sweep = c01(lt / D);
    const bx = (dir > 0 ? -0.35 + 1.7 * sweep : 1.35 - 1.7 * sweep) * W;
    const flick = 0.88 + 0.12 * Math.sin(lt * 37 + seed) * Math.sin(lt * 13 + 1);
    const corner = rand(seed * 5) > 0.5;
    const streaks = [0, 1].map((k) => (0.15 + 0.7 * rand(seed * 13 + k)) * W + Math.sin(lt * 9 + k * 2) * 0.01 * W);
    return (
      <div style={{ position: "absolute", inset: 0, mixBlendMode: "screen", overflow: "hidden" }}>
        <div style={{ position: "absolute", left: bx - 0.6 * W, top: -0.1 * H, width: 1.2 * W, height: 1.2 * H, transform: `skewX(${-14 * dir}deg)`,
          background: "linear-gradient(90deg, rgba(255,90,20,0) 0%, rgba(255,96,28,0.75) 30%, rgba(255,196,120,0.95) 48%, rgba(255,236,200,1) 52%, rgba(255,120,40,0.8) 68%, rgba(200,40,10,0) 100%)",
          opacity: e * flick, filter: `blur(${(0.05 * H).toFixed(1)}px)` }} />
        <div style={{ position: "absolute", inset: 0, opacity: e,
          background: `radial-gradient(ellipse 70% 90% at ${corner ? "0% 100%" : "100% 0%"}, rgba(255,70,20,0.85) 0%, rgba(255,70,20,0) 70%)` }} />
        {streaks.map((x, k) => (
          <div key={k} style={{ position: "absolute", left: x, top: 0, width: 0.008 * W, height: H, background: "rgba(255,226,180,0.9)",
            opacity: e * 0.45 * flick, filter: `blur(${(0.004 * H).toFixed(1)}px)` }} />
        ))}
        {/* the flash over the cut: ±0.14 s only, so the leak reads as light, not as a white-out */}
        <div style={{ position: "absolute", inset: 0, background: "rgb(255,242,222)", opacity: 0.95 * c01(1 - Math.abs(lt - mid) / 0.14) ** 1.5 }} />
      </div>
    );
  }

  if (L.effect === "glitch") {
    // Polished 2026-10-18 (round 2): it was nine full-width bands of flat kit colour and inverted strips at half
    // strength over the whole second - it read as coloured stripes, not as a signal failing. Now a digital tear built
    // from the shot itself: it builds over ~0.3 s into the cut (sound at its onset), a few torn bands of the picture
    // blown out and smeared with red / cyan channel fringes, compression macroblocks near the peak, a 2-frame signal
    // drop with one bright scan line that hides the cut, then it decays in ~0.2 s (faster out than in). The kit accent
    // is one thin line at the drop; everything else is the picture's own light.
    const pre = 0.32, post = 0.2;
    const env = lt < mid ? c01(1 - (mid - lt) / pre) ** 1.4 : 1 - easeOf("expoOut")(c01((lt - mid) / post));
    if (env <= 0.001) return null;
    const frame = Math.floor(lt * 24);
    const R = (n: number) => rand(seed * 131 + frame * 17 + n);
    const out: React.ReactNode[] = [];
    // torn bands: 1-4, more and taller as it peaks, clustered round one or two seams that move each frame
    const nb = 2 + Math.round(3 * env);
    const seamA = (0.2 + 0.6 * rand(seed * 7 + Math.floor(frame / 3))) * H;
    for (let k = 0; k < nb; k++) {
      const yy = c01((seamA + (R(k) - 0.5) * 0.55 * H) / H) * H;
      const hh = (0.02 + (0.03 + 0.1 * env) * R(k + 10)) * H;
      const x0 = R(k + 20) < 0.5 ? 0 : R(k + 30) * 0.45 * W;
      const ww = W - x0 - (R(k + 40) < 0.5 ? 0 : R(k + 50) * 0.3 * W);
      const fr = Math.max(2, 0.0035 * H);
      // one band in three shifts the picture's hue (a channel slipping); the others blow out and smear
      const shift = R(k + 70) < 0.34;
      const bf = shift
        ? `hue-rotate(${Math.round(90 + 180 * R(k + 80))}deg) saturate(2.6) contrast(1.4)`
        : `blur(${(0.004 * H * env).toFixed(1)}px) contrast(${(1.5 + 0.6 * env).toFixed(2)}) saturate(${(1.6 + env).toFixed(2)}) brightness(${(1.3 + 0.4 * R(k + 60)).toFixed(2)})`;
      out.push(
        <div key={`b${k}`} style={{ position: "absolute", left: x0, top: yy, width: ww, height: hh, backdropFilter: bf, opacity: Math.min(1, 0.55 + env) }}>
          {/* pixels stretched sideways: fine vertical streaks in screen */}
          <div style={{ position: "absolute", inset: 0, mixBlendMode: "screen", opacity: 0.5,
            backgroundImage: `repeating-linear-gradient(90deg, rgba(255,255,255,0.22) 0px, rgba(255,255,255,0.22) ${Math.max(1, 0.002 * W).toFixed(1)}px, transparent ${Math.max(1, 0.002 * W).toFixed(1)}px, transparent ${(0.004 + 0.012 * R(k + 90)) * W}px)` }} />
          <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: fr, background: "#ff2a55", mixBlendMode: "screen", opacity: 0.9, transform: `translateX(${(0.01 * W).toFixed(1)}px)` }} />
          <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: fr, background: "#22e4ff", mixBlendMode: "screen", opacity: 0.9, transform: `translateX(${(-0.01 * W).toFixed(1)}px)` }} />
        </div>,
      );
    }
    // macroblocks near the peak: the codec losing the picture - smeared tiles, a few dropped to black
    if (env > 0.35) {
      const cs = W / 20;
      const nm = Math.round(12 * (env - 0.35) / 0.65);
      for (let k = 0; k < nm; k++) {
        const cx = Math.floor(R(k + 100) * 20) * cs, cy = Math.floor(R(k + 120) * (H / cs)) * cs;
        const span = 1 + Math.floor(R(k + 140) * 3);
        out.push(<div key={`m${k}`} style={{ position: "absolute", left: cx, top: cy, width: cs * span, height: cs,
          ...(R(k + 160) < 0.25 ? { background: "rgba(5,6,9,0.9)" } : { backdropFilter: `blur(${(0.012 * H).toFixed(1)}px) saturate(2.2) contrast(1.3)` }) }} />);
      }
    }
    const cutDrop = Math.abs(lt - mid) < 0.045;
    const scanY = (0.3 + 0.4 * rand(seed * 3)) * H;
    return (
      <div style={{ position: "absolute", inset: 0 }}>
        {/* the whole frame loses a little colour and gains contrast as the signal goes */}
        <div style={{ position: "absolute", inset: 0, backdropFilter: `contrast(${(1 + 0.25 * env).toFixed(3)}) saturate(${(1 - 0.35 * env).toFixed(3)})` }} />
        {out}
        <div style={{ position: "absolute", inset: 0, backgroundImage: "repeating-linear-gradient(0deg, rgba(0,0,0,0.3) 0px, rgba(0,0,0,0.3) 1px, transparent 1px, transparent 4px)", opacity: 0.5 * env }} />
        {cutDrop ? (
          <>
            {/* signal lost: near black whatever the kit (a kit's deep blue here read as a blue screen) */}
            <div style={{ position: "absolute", inset: 0, background: "rgba(5,6,9,0.95)" }} />
            <div style={{ position: "absolute", left: 0, right: 0, top: scanY - 0.004 * H, height: 0.008 * H, background: "#ff2a55", opacity: 0.7, transform: `translateX(${(0.008 * W).toFixed(1)}px)`, mixBlendMode: "screen" }} />
            <div style={{ position: "absolute", left: 0, right: 0, top: scanY - 0.004 * H, height: 0.008 * H, background: "#22e4ff", opacity: 0.7, transform: `translateX(${(-0.008 * W).toFixed(1)}px)`, mixBlendMode: "screen" }} />
            <div style={{ position: "absolute", left: 0, right: 0, top: scanY - 0.0015 * H, height: 0.003 * H, background: "#ffffff", boxShadow: `0 0 ${(0.02 * H).toFixed(1)}px rgba(255,255,255,0.8)` }} />
            <div style={{ position: "absolute", left: 0.08 * W, width: 0.22 * W, top: scanY + 0.03 * H, height: Math.max(2, 0.004 * H), background: acc }} />
          </>
        ) : null}
      </div>
    );
  }

  if (L.effect === "tear") {
    // A sheet of paper with torn edges slides across: its leading edge covers the frame by the cut, its trailing edge reveals the next shot.
    // Polished 2026-10-18 (a flat sheet with a zigzag edge): a sheet of paper with grain, tilted a touch, its torn
    // edges finely ragged at two scales with the white fibrous core showing unevenly, a soft shadow on the shot.
    const p = easeOf("inOut")(c01(lt / D));
    const dir = seed % 2 ? -1 : 1;
    const sheetW = W * 1.55, top = -0.15 * H, sh = 1.3 * H;
    const x = dir > 0 ? -sheetW + p * (W + sheetW) : W - p * (W + sheetW);
    const STEPS = 64;
    const jag = (i: number, side: number, fine: number) => (rand(seed * 53 + i + side * 999) - 0.5) * 0.024 * W + Math.sin(i * 0.5 + side * 3 + seed) * 0.016 * W
      + (rand(seed * 91 + i * 7 + side * 31) - 0.5) * fine * W;
    const edge = (side: number, inset: number, fine: number) => Array.from({ length: STEPS + 1 }, (_, i) => {
      const yy = top + (i / STEPS) * sh;
      const xx = (side > 0 ? sheetW : 0) + jag(i, side, fine) - side * inset;
      return `${xx.toFixed(1)},${yy.toFixed(1)}`;
    });
    const outerL = edge(-1, 0, 0.012), outerR = edge(1, 0, 0.012);
    const sheet = [...outerL, ...outerR.slice().reverse()].join(" ");
    // the white core: between the torn edge and a second, independently ragged line just inside it
    const core = (side: number) => [...edge(side, 0, 0.012), ...edge(side, 0.009 * W, 0.02).reverse()].join(" ");
    return (
      <svg width={W} height={H} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
        <defs>
          <filter id={`${id}g`} x="0" y="0" width="100%" height="100%">
            <feTurbulence type="fractalNoise" baseFrequency={0.75} numOctaves={2} seed={seed % 89} />
            <feColorMatrix type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  3 0 0 0 -1.1" />
            <feComposite in2="SourceGraphic" operator="in" />
          </filter>
          {/* light catching the torn edges: the paper lifts a little where it tore */}
          <linearGradient id={`${id}s`} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor={lift(col, 0.16)} /><stop offset="0.1" stopColor={col} />
            <stop offset="0.9" stopColor={col} /><stop offset="1" stopColor={lift(col, 0.16)} />
          </linearGradient>
        </defs>
        <g transform={`translate(${x.toFixed(1)},0) rotate(${(1.6 * dir).toFixed(2)} ${(sheetW / 2).toFixed(0)} ${(H / 2).toFixed(0)})`}
          style={{ filter: `drop-shadow(0 ${(0.006 * H).toFixed(1)}px ${(0.018 * H).toFixed(1)}px rgba(0,0,0,0.5))` }}>
          <polygon points={sheet} fill={`url(#${id}s)`} />
          <polygon points={sheet} fill="#000" filter={`url(#${id}g)`} opacity={0.3} />
          <polygon points={core(-1)} fill="#efe9dd" />
          <polygon points={core(1)} fill="#efe9dd" />
        </g>
      </svg>
    );
  }

  if (L.effect === "blocks") {
    // Polished 2026-10-18 (random blue and yellow squares at full strength): a directional tile wipe in the kit's
    // ground tones - each tile grows from 60% as the wave reaches it, the wavefront lit in the accent, the frame
    // covered at the cut; the same wave carries on and the tiles shrink away onto the next shot.
    const cols = 12, rows = 7;
    const cw = W / cols, ch = H / rows;
    const dir = seed % 2 ? 1 : -1;
    const inLen = Math.max(0.12, mid * 0.4), outLen = Math.max(0.12, (D - mid) * 0.4);
    const cells: React.ReactNode[] = [];
    for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
      const k = r * cols + c;
      const u = (dir > 0 ? c : cols - 1 - c) / (cols - 1), v = r / (rows - 1);
      const order = c01(u * 0.8 + v * 0.1 + rand(seed * 7 + k) * 0.1);
      const pin = easeOf("expoOut")((lt - order * (mid - inLen)) / inLen);
      const pout = easeOf("expoIn")((lt - mid - order * (D - mid - outLen)) / outLen);
      const s = pin * (1 - pout);
      if (s <= 0.001) continue;
      const ground = rand(seed * 3 + k * 7) > 0.6 ? col2 : col;
      const front = pin > 0 && pin < 0.8;
      cells.push(<div key={k} style={{ position: "absolute", left: c * cw, top: r * ch, width: cw + 1, height: ch + 1,
        background: front ? acc : ground, opacity: c01(s * 1.6), transform: `scale(${(0.6 + 0.4 * s).toFixed(4)})`,
        boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.05)" }} />);
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

