/**
 * The Smart Editor's one renderer: draws any motion spec (specMath.ts) at the current frame (2026-10-14).
 *
 * Layers - text with per-character / word / line animators tied to the narration's word times, number
 * counters, boxes, hand-drawn circles, arrows and lines that draw on, focus brackets, map pins with pulses,
 * spotlights that dim all but one point of the shot, pictures (SafeImg only), particles - each with its own
 * keyframes and easing, in a 2.5D stage (perspective, rotateX / rotateY, depth parallax, extruded type,
 * glow, blur, blend modes). Deterministic: nothing here reads the clock, a random source or the network
 * except SafeImg's picture, which can never hold the render (memory: safeimg-render-hang).
 *
 * Fail safe: a spec that does not clean up (cleanSpec) draws nothing, and an error while drawing is caught by
 * the boundary below and draws nothing - one bad graphic never stops a video.
 */
import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY, GROTESK, HAND, INTER, KINETIC, MONO, NARROW, SERIF, SERIF_ITALIC } from "../fonts";
import { SafeImg } from "../motion/safePicture";
import { cleanSpec, easeOf, formatCount, rand, unitProgress, valueAt, type Layer, type MotionSpec } from "./specMath";
import { styleFont } from "./styleFonts";
import { CardBody, ChartBody, FxBody, ScribbleBody } from "./SpecPack2";
import { GameBody } from "./SpecGaming";

/** A measured outline (and the band round it) as a ring of hard text-shadows: one stroke on every glyph. */
const ringShadows = (w: number, color: string, steps = 16, blur = 0): string[] => {
  const out: string[] = [];
  for (let i = 0; i < steps; i++) {
    const a = (i / steps) * Math.PI * 2;
    out.push(`${(Math.cos(a) * w).toFixed(2)}px ${(Math.sin(a) * w).toFixed(2)}px ${blur.toFixed(1)}px ${color}`);
  }
  return out;
};

const FONTS: Record<string, string> = {
  grotesk: GROTESK, kinetic: KINETIC, display: DISPLAY, serif: SERIF, "serif-italic": SERIF_ITALIC, mono: MONO,
  narrow: NARROW, inter: INTER, hand: HAND,
};

class Guard extends React.Component<{ children: React.ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(e: unknown) { console.warn("[smart-spec] graphic left out:", e); }
  render() { return this.state.failed ? null : this.props.children; }
}

interface Ctx { t: number; dur: number; W: number; H: number; spec: MotionSpec }

const SHADOW_SOFT = (H: number) => `0 ${(0.004 * H).toFixed(1)}px ${(0.016 * H).toFixed(1)}px rgba(0,0,0,0.55)`;

/** Per-unit transform/opacity for an animator unit at progress p (0 = from, 1 = rest). */
const unitStyle = (layer: Layer, p: number, H: number, sizePx: number): React.CSSProperties => {
  const f = layer.animator?.from || {};
  const lerp = (a: number | undefined, rest: number) => (a === undefined ? rest : a + (rest - a) * p);
  const op = lerp(f.opacity, 1);
  const y = lerp(f.y, 0) * sizePx;
  const x = lerp(f.x, 0) * sizePx;
  const sc = lerp(f.scale, 1);
  const rot = lerp(f.rot, 0);
  const rx = lerp(f.rotX, 0);
  const ry = lerp(f.rotY, 0);
  const bl = lerp(f.blur, 0) * (H / 1080);
  const tr = lerp(f.tracking, 0);
  return {
    display: "inline-block", whiteSpace: "pre", opacity: Math.max(0, Math.min(1, op)),
    transform: `translate3d(${x.toFixed(2)}px, ${y.toFixed(2)}px, 0) rotateX(${rx.toFixed(2)}deg) rotateY(${ry.toFixed(2)}deg) rotate(${rot.toFixed(2)}deg) scale(${sc.toFixed(4)})`,
    filter: bl > 0.05 ? `blur(${bl.toFixed(2)}px)` : undefined,
    letterSpacing: tr ? `${tr.toFixed(3)}em` : undefined,
    transformOrigin: "50% 70%",
    backfaceVisibility: "hidden",
  };
};

const TextBody: React.FC<{ layer: Layer; ctx: Ctx; counterText?: string }> = ({ layer, ctx, counterText }) => {
  const { H, t } = ctx;
  const lt = t - layer.from;
  const sizePx = (layer.size || 0.06) * H;
  const raw = counterText ?? (layer.text || "");
  const text = layer.upper ? raw.toUpperCase() : raw;
  const a = layer.animator;
  const glow = valueAt(layer.keys, "glow", lt, layer.glow || 0) * (H / 1080);
  const shadows: string[] = [];
  if (layer.extrude) {
    for (let i = 1; i <= layer.extrude; i++) shadows.push(`${(i * 0.9 * H / 1080).toFixed(1)}px ${(i * 1.1 * H / 1080).toFixed(1)}px 0 ${layer.extrudeColor}`);
  }
  if (glow > 0.2) shadows.push(`0 0 ${glow.toFixed(1)}px ${layer.emphColor || layer.color}`);
  if (layer.outline) shadows.push(...ringShadows(layer.outline.w * H, layer.outline.color));
  if (layer.band) {
    const bw = ((layer.outline?.w || 0) + layer.band.w) * H;
    shadows.push(...ringShadows(bw, layer.band.color, 20, layer.band.soft * layer.band.w * H));
  }
  if (layer.shadow === "soft") shadows.push(SHADOW_SOFT(H));
  if (layer.shadow === "hard") shadows.push(`${(0.003 * H).toFixed(1)}px ${(0.003 * H).toFixed(1)}px 0 rgba(0,0,0,0.85)`);
  const tracking = valueAt(layer.keys, "tracking", lt, layer.tracking || 0);
  const style: React.CSSProperties = {
    fontFamily: styleFont(layer.font) || FONTS[layer.font || "grotesk"] || GROTESK, fontWeight: layer.weight || 800, fontSize: sizePx,
    fontStyle: layer.italic ? "italic" : undefined, lineHeight: layer.lineH || 1.05, color: layer.color,
    letterSpacing: `${tracking.toFixed(3)}em`, textAlign: layer.align || "center", maxWidth: (layer.maxW || 0.8) * ctx.W,
    textShadow: shadows.length ? shadows.join(", ") : undefined, fontVariantNumeric: "tabular-nums",
    transformStyle: "preserve-3d", whiteSpace: "normal", wordBreak: "keep-all",
  };
  const emph = new Set(layer.emph || []);
  const lines = text.split("\n");
  let wordIndex = 0;
  let charIndex = 0;
  const body = lines.map((line, li) => {
    const words = line.split(/\s+/).filter(Boolean);
    const lineP = a && a.unit === "line" ? unitProgress(a, li, lt) : 1;
    const wordsOut = words.map((w, wi) => {
      const gi = wordIndex++;
      const isEmph = emph.has(gi);
      let inner: React.ReactNode = w;
      if (a && a.unit === "char") {
        inner = Array.from(w).map((ch, ci) => {
          const p = unitProgress(a, charIndex++, lt);
          return <span key={ci} style={unitStyle(layer, p, H, sizePx)}>{ch}</span>;
        });
      }
      const wp = a && a.unit === "word" ? unitProgress(a, gi, lt) : a && a.unit === "line" ? lineP : 1;
      const wStyle: React.CSSProperties = a && a.unit !== "char" ? unitStyle(layer, wp, H, sizePx) : { display: "inline-block" };
      let deco: React.ReactNode = null;
      if (isEmph) {
        const landed = a ? (a.unit === "char" ? 1 : wp) : 1;
        const sweep = Math.max(0, Math.min(1, (landed - 0.35) / 0.65));
        if (layer.emphStyle === "box") {
          deco = <span style={{ position: "absolute", left: "-0.12em", right: "-0.12em", top: "0.08em", bottom: "0.02em",
            background: layer.emphColor, transform: `scaleX(${sweep.toFixed(3)})`, transformOrigin: "0% 50%", zIndex: -1,
            borderRadius: "0.06em" }} />;
          wStyle.color = "#0b0c10";
          wStyle.textShadow = "none";
        } else if (layer.emphStyle === "underline") {
          deco = <span style={{ position: "absolute", left: 0, right: 0, bottom: "-0.06em", height: "0.09em",
            background: layer.emphColor, transform: `scaleX(${sweep.toFixed(3)})`, transformOrigin: "0% 50%" }} />;
        } else if (layer.emphStyle === "glow") {
          wStyle.color = layer.emphColor;
          wStyle.textShadow = `0 0 ${(0.02 * H * sweep).toFixed(1)}px ${layer.emphColor}`;
        } else {
          wStyle.color = layer.emphColor;
        }
      }
      // A redacted word (layer.redact): a bar over it pulls away to the right the moment the word lands.
      if (layer.redact) {
        const rp = a ? (a.unit === "char" ? 1 : wp) : 1;
        deco = <>{deco}<span style={{ position: "absolute", left: "-0.08em", right: "-0.08em", top: "0.06em", bottom: "0.02em", zIndex: 2,
          background: layer.redact, transform: `scaleX(${(1 - Math.max(0, Math.min(1, rp))).toFixed(4)})`, transformOrigin: "100% 50%" }} /></>;
      }
      const span = <span style={{ ...wStyle, position: "relative", zIndex: 0 }}>{deco}{inner}</span>;
      return (
        <React.Fragment key={wi}>
          {/* A masked reveal (animator.clip): the word rises out of its own line, never seen below it. */}
          {a?.clip ? <span style={{ display: "inline-block", overflow: "hidden", verticalAlign: "top",
            padding: "0.04em 0.06em 0.12em", margin: "-0.04em -0.06em -0.12em" }}>{span}</span> : span}
          {wi < words.length - 1 ? " " : null}
        </React.Fragment>
      );
    });
    return <div key={li} style={{ transformStyle: "preserve-3d" }}>{wordsOut}</div>;
  });
  const panel = layer.panel;
  const pad = panel ? panel.pad * H : 0;
  // The block's own furniture, laid out by the browser so nothing ever overlaps: a kicker tag above, an
  // underline under the words, a sub line below, a bar beside, corner brackets round it (layer.deco).
  const D = layer.deco;
  const dAt = D ? D.at : 0;
  const dp = (delay: number, len = 0.5) => easeOf("expoOut")((lt - dAt - delay) / len);
  const side = layer.align === "right" ? "flex-end" : layer.align === "center" ? "center" : "flex-start";
  const sw = Math.max(2, 0.0045 * H);
  const shape = (layer.stretch && Math.abs(layer.stretch - 1) > 0.01) || layer.skew
    ? `scaleX(${(layer.stretch || 1).toFixed(3)}) skewX(${(-(layer.skew || 0)).toFixed(2)}deg)` : undefined;
  // A colour bar sweeping across the words (layer.sweep): it grows from the left, the words appear under it once
  // it covers them, then it slides off to the right - the block always fits its own words.
  const SW = layer.sweep;
  const swIn = SW ? easeOf("expoInOut")((lt - SW.at) / (SW.dur * 0.5)) : 1;
  const swOut = SW ? easeOf("expoInOut")((lt - SW.at - SW.dur * 0.5) / (SW.dur * 0.5)) : 1;
  const main = (
    <div style={{ ...style, position: "relative", width: "max-content", transform: panel ? undefined : shape,
      transformOrigin: layer.align === "left" ? "0% 50%" : layer.align === "right" ? "100% 50%" : "50% 50%" }}>
      {SW ? <div style={{ opacity: swOut > 0 ? 1 : 0 }}>{body}</div> : body}
      {SW && swOut < 1 ? <div style={{ position: "absolute", left: "-0.1em", right: "-0.1em", top: "0.02em", bottom: "0.02em",
        background: SW.color, transform: swOut > 0 ? `scaleX(${(1 - swOut).toFixed(4)})` : `scaleX(${swIn.toFixed(4)})`,
        transformOrigin: swOut > 0 ? "100% 50%" : "0% 50%" }} /> : null}
      {D?.underline ? <div style={{ position: "absolute", left: 0, right: 0, bottom: "-0.12em", height: sw * 1.3,
        background: D.underline, transform: `scaleX(${dp(0.1, 0.55).toFixed(4)})`,
        transformOrigin: layer.align === "right" ? "100% 50%" : "0% 50%" }} /> : null}
    </div>
  );
  const sub = layer.sub;
  const subP = sub ? easeOf("expoOut")((lt - sub.at) / 0.55) : 0;
  const kick = layer.kicker;
  const kickP = kick ? easeOf("expoOut")((lt - kick.at) / 0.45) : 0;
  const bracket = D?.bracket ? (() => {
    const c = dp(0.15, 0.5);
    const L = `${(0.9 * c).toFixed(3)}em`;
    const corner = (pos: React.CSSProperties, k: number) => (
      <div key={k} style={{ position: "absolute", width: L, height: L, ...pos }} />
    );
    const b = `${sw.toFixed(1)}px solid ${D.bracket}`;
    return [
      corner({ left: "-0.35em", top: "-0.3em", borderLeft: b, borderTop: b }, 0),
      corner({ right: "-0.35em", top: "-0.3em", borderRight: b, borderTop: b }, 1),
      corner({ left: "-0.35em", bottom: "-0.3em", borderLeft: b, borderBottom: b }, 2),
      corner({ right: "-0.35em", bottom: "-0.3em", borderRight: b, borderBottom: b }, 3),
    ];
  })() : null;
  return (
    <div style={{
      display: "flex", flexDirection: "column", alignItems: side, position: "relative", width: "max-content",
      maxWidth: (layer.maxW || 0.8) * ctx.W, transformStyle: "preserve-3d", fontSize: sizePx,
      // a stretched face in a box: the box stretches with it, its side padding divided back to the measured size
      ...(panel && shape ? { transform: shape, transformOrigin: "50% 50%" } : {}),
      ...(panel ? { background: hexA(panel.color, panel.opacity),
        padding: `${(panel.padY !== undefined ? panel.padY * H : pad * 0.7).toFixed(1)}px ${(pad / (layer.stretch || 1)).toFixed(1)}px`,
        borderRadius: panel.radius * H, backdropFilter: panel.blur ? `blur(${panel.blur}px)` : undefined } : {}),
    }}>
      {D?.bar ? <div style={{ position: "absolute", top: "0.05em", bottom: "0.05em", width: sw * 1.2, background: D.bar,
        [layer.align === "right" ? "right" : "left"]: "-0.45em", transform: `scaleY(${dp(0, 0.45).toFixed(4)})`,
        transformOrigin: "50% 0%" }} /> : null}
      {bracket}
      {D?.rule ? <div style={{ width: "1.6em", height: sw * 1.2, background: D.rule, marginBottom: "0.32em",
        transform: `scaleX(${dp(0, 0.4).toFixed(4)})`, transformOrigin: layer.align === "right" ? "100% 50%" : "0% 50%" }} /> : null}
      {kick ? (
        <div style={{ fontFamily: NARROW, fontWeight: 800, fontSize: kick.size * H, letterSpacing: "0.14em",
          textTransform: "uppercase", color: kick.color, background: kick.bg, padding: "0.18em 0.45em 0.12em",
          marginBottom: "0.5em", whiteSpace: "nowrap", lineHeight: 1,
          clipPath: `inset(0 ${((1 - kickP) * 100).toFixed(2)}% 0 0)` }}>{kick.text}</div>
      ) : null}
      {main}
      {sub ? (
        <div style={{ fontFamily: FONTS[sub.font] || INTER, fontWeight: sub.weight, fontSize: sub.size * H,
          letterSpacing: `${sub.tracking}em`, color: sub.color, marginTop: D?.underline ? "0.75em" : "0.45em",
          textAlign: layer.align || "center", lineHeight: 1.2, textTransform: sub.upper ? "uppercase" : undefined,
          maxWidth: (layer.maxW || 0.8) * ctx.W, textShadow: SHADOW_SOFT(H), opacity: subP,
          transform: `translateY(${((1 - subP) * 0.5 * sub.size * H).toFixed(2)}px)`,
          filter: subP < 0.98 ? `blur(${((1 - subP) * 6 * H / 1080).toFixed(2)}px)` : undefined }}>{sub.text}</div>
      ) : null}
    </div>
  );
};

/** "#rrggbb" + alpha -> rgba(); anything else is returned unchanged. */
const hexA = (c: string, a: number): string => {
  const m = /^#([0-9a-f]{6})$/i.exec(c);
  if (!m) return c;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a.toFixed(3)})`;
};

const pathFor = (pts: [number, number][], curve: number, W: number, H: number): string => {
  const P = pts.map(([x, y]) => [x * W, y * H]);
  if (P.length === 2) {
    const [[x0, y0], [x1, y1]] = P;
    const mx = (x0 + x1) / 2, my = (y0 + y1) / 2;
    const dx = x1 - x0, dy = y1 - y0;
    const cx = mx - dy * curve, cy = my + dx * curve;
    return `M${x0.toFixed(1)},${y0.toFixed(1)} Q${cx.toFixed(1)},${cy.toFixed(1)} ${x1.toFixed(1)},${y1.toFixed(1)}`;
  }
  let d = `M${P[0][0].toFixed(1)},${P[0][1].toFixed(1)}`;
  for (let i = 1; i < P.length; i++) {
    const [px, py] = P[i - 1];
    const [x, y] = P[i];
    d += ` Q${px.toFixed(1)},${py.toFixed(1)} ${((px + x) / 2).toFixed(1)},${((py + y) / 2).toFixed(1)}`;
  }
  const last = P[P.length - 1];
  return d + ` L${last[0].toFixed(1)},${last[1].toFixed(1)}`;
};

const LineBody: React.FC<{ layer: Layer; ctx: Ctx; draw: number }> = ({ layer, ctx, draw }) => {
  const { W, H } = ctx;
  const pts = layer.points || [];
  const sw = (layer.stroke ?? 0.005) * H;
  const d = pathFor(pts, layer.curve || 0, W, H);
  const n = pts.length;
  const [ex, ey] = [pts[n - 1][0] * W, pts[n - 1][1] * H];
  // The head's direction: from the curve's control side into the end point.
  let [bx, by] = [pts[n - 2][0] * W, pts[n - 2][1] * H];
  if (n === 2 && layer.curve) {
    const mx = (bx + ex) / 2, my = (by + ey) / 2, dx = ex - bx, dy = ey - by;
    bx = mx - dy * (layer.curve || 0); by = my + dx * (layer.curve || 0);
  }
  const ang = Math.atan2(ey - by, ex - bx);
  const hl = (layer.head || 0) * H;
  const headP = Math.max(0, Math.min(1, (draw - 0.85) / 0.15));
  const h1 = [ex - hl * headP * Math.cos(ang - 0.5), ey - hl * headP * Math.sin(ang - 0.5)];
  const h2 = [ex - hl * headP * Math.cos(ang + 0.5), ey - hl * headP * Math.sin(ang + 0.5)];
  return (
    <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible",
      filter: `drop-shadow(0 ${(0.003 * H).toFixed(1)}px ${(0.008 * H).toFixed(1)}px rgba(0,0,0,0.5))` }}>
      <path d={d} fill="none" stroke={layer.color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round"
        pathLength={1} strokeDasharray={layer.dash ? `${layer.dash * 4} ${layer.dash * 3}` : "1 1"}
        strokeDashoffset={layer.dash ? 0 : 1 - draw} opacity={layer.dash ? draw : 1} />
      {layer.kind === "arrow" && headP > 0 ? (
        <path d={`M${h1[0].toFixed(1)},${h1[1].toFixed(1)} L${ex.toFixed(1)},${ey.toFixed(1)} L${h2[0].toFixed(1)},${h2[1].toFixed(1)}`}
          fill="none" stroke={layer.color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" />
      ) : null}
    </svg>
  );
};

const FormBody: React.FC<{ layer: Layer; ctx: Ctx; draw: number }> = ({ layer, ctx, draw }) => {
  const { W, H } = ctx;
  const w = layer.w * W, h = layer.h * H;
  const sw = (layer.stroke ?? 0.004) * H;
  if (layer.kind === "rect") {
    return <div style={{ width: w, height: h, background: layer.fill || layer.color, borderRadius: (layer.radius || 0) * H,
      border: layer.stroke ? `${sw.toFixed(1)}px solid ${layer.color}` : undefined,
      transform: `scaleX(${draw.toFixed(4)})`, transformOrigin: "0% 50%" }} />;
  }
  if (layer.kind === "ellipse") {
    // A hand-drawn ring: starts a little past the top-left and overshoots its start by a few degrees.
    const rx = w / 2, ry = h / 2;
    return (
      <svg width={w + sw * 2} height={h + sw * 2} style={{ overflow: "visible",
        filter: `drop-shadow(0 0 ${(0.006 * H).toFixed(1)}px rgba(0,0,0,0.6))` }}>
        {layer.fill ? <ellipse cx={rx + sw} cy={ry + sw} rx={rx} ry={ry} fill={layer.fill} /> : null}
        <ellipse cx={rx + sw} cy={ry + sw} rx={rx} ry={ry} fill="none" stroke={layer.color} strokeWidth={sw}
          strokeLinecap="round" pathLength={1.08} strokeDasharray="1.08 1.08" strokeDashoffset={1.08 * (1 - draw)}
          transform={`rotate(-128 ${rx + sw} ${ry + sw})`} />
      </svg>
    );
  }
  // bracket: four corners that grow out from each corner
  const c = Math.min(w, h) * 0.28 * draw;
  const corner = (cx: number, cy: number, sx: number, sy: number, k: number) => (
    <path key={k} d={`M${cx + sx * c},${cy} L${cx},${cy} L${cx},${cy + sy * c}`} fill="none" stroke={layer.color}
      strokeWidth={sw} strokeLinecap="square" />
  );
  return (
    <svg width={w} height={h} style={{ overflow: "visible" }}>
      {layer.fill ? <rect width={w} height={h} fill={layer.fill} opacity={draw} /> : null}
      {corner(0, 0, 1, 1, 0)}{corner(w, 0, -1, 1, 1)}{corner(0, h, 1, -1, 2)}{corner(w, h, -1, -1, 3)}
    </svg>
  );
};

const PinBody: React.FC<{ layer: Layer; ctx: Ctx }> = ({ layer, ctx }) => {
  const { H, t } = ctx;
  const lt = Math.max(0, t - layer.from);
  const r = 0.009 * H;
  const rings = [0, 0.8].map((off, i) => {
    const ph = ((lt + off) % 1.6) / 1.6;
    const R = r * (1 + 3.5 * ph);
    return <div key={i} style={{ position: "absolute", left: r - R, top: r - R, width: 2 * R, height: 2 * R,
      borderRadius: "50%", border: `${(0.002 * H).toFixed(1)}px solid ${layer.color}`, opacity: 1 - ph }} />;
  });
  return (
    <div style={{ position: "relative", width: r * 2, height: r * 2 }}>
      {rings}
      <div style={{ position: "absolute", inset: 0, borderRadius: "50%", background: layer.color,
        boxShadow: `0 0 ${(0.012 * H).toFixed(1)}px ${layer.color}` }} />
      {layer.text ? (
        <div style={{ position: "absolute", left: r * 3, top: "50%", transform: "translateY(-50%)", whiteSpace: "nowrap",
          fontFamily: FONTS[layer.font || "narrow"] || NARROW, fontWeight: layer.weight || 700, fontSize: (layer.size || 0.03) * H,
          letterSpacing: `${layer.tracking || 0.08}em`, color: "#fff", textTransform: "uppercase", textShadow: SHADOW_SOFT(H) }}>
          {layer.text}
        </div>
      ) : null}
    </div>
  );
};

const Particles: React.FC<{ layer: Layer; ctx: Ctx }> = ({ layer, ctx }) => {
  const { W, H, t } = ctx;
  const n = layer.count || 30;
  const out: React.ReactNode[] = [];
  for (let i = 0; i < n; i++) {
    const s = (layer.seed || 1) * 1000 + i * 13;
    const x0 = rand(s), y0 = rand(s + 1), sz = (0.4 + rand(s + 2)) * (layer.size || 0.004) * H;
    const sp = (0.3 + rand(s + 3)) * (layer.speed || 0.15);
    const x = ((x0 + Math.sin(t * 0.6 + i) * 0.01) % 1) * W;
    const y = (((y0 - sp * t * 0.25) % 1) + 1) % 1 * H;
    const tw = 0.35 + 0.65 * Math.abs(Math.sin(t * (1 + rand(s + 4) * 2) + i));
    out.push(<div key={i} style={{ position: "absolute", left: x, top: y, width: sz, height: sz, borderRadius: "50%",
      background: layer.color, opacity: tw * layer.opacity, boxShadow: `0 0 ${(sz * 2).toFixed(1)}px ${layer.color}` }} />);
  }
  return <AbsoluteFill style={{ mixBlendMode: (layer.blend as React.CSSProperties["mixBlendMode"]) || "screen" }}>{out}</AbsoluteFill>;
};

// ------------------------------------------------------------------ brand-kit primitives
const partStyle = (build: string, p: number): { transform?: string; opacity?: number } => {
  if (build === "up") return { transform: `scaleY(${p.toFixed(4)})`, opacity: p > 0.001 ? 1 : 0 };
  if (build === "left") return { transform: `scaleX(${p.toFixed(4)})`, opacity: p > 0.001 ? 1 : 0 };
  if (build === "pop") return { transform: `scale(${p.toFixed(4)})`, opacity: Math.min(1, p * 3) };
  return { opacity: p };
};

/** A flat vector illustration built piece by piece (a tower draws upward, a card assembles). */
const ShapeBody: React.FC<{ layer: Layer; ctx: Ctx }> = ({ layer, ctx }) => {
  const { W, H, t } = ctx;
  const lt = t - layer.from;
  const bw = layer.w * W, bh = layer.h * H;
  const build = layer.build || "up";
  const e = easeOf(layer.ease);
  const parts = (layer.shapes || []).map((q, i) => {
    const raw = (lt - i * (layer.stagger || 0)) / (layer.bdur || 0.45);
    const p = build === "pop" ? easeOf("backOut")(raw) : e(raw);
    if (p <= 0.0001) return null;
    const ps = partStyle(build, Math.max(0, p));
    const style: React.CSSProperties = { transformBox: "fill-box",
      transformOrigin: build === "up" ? "50% 100%" : build === "left" ? "0% 50%" : "50% 50%", transform: ps.transform };
    const sw = (q.sw || 0.01) * Math.min(bw, bh);
    if (q.t === "rect") return <rect key={i} style={style} opacity={ps.opacity} x={(q.x || 0) * bw} y={(q.y || 0) * bh}
      width={(q.w || 0) * bw} height={(q.h || 0) * bh} rx={(q.r || 0) * Math.min(bw, bh)} fill={q.c} />;
    if (q.t === "ellipse") return <ellipse key={i} style={style} opacity={ps.opacity} cx={((q.x || 0) + (q.w || 0) / 2) * bw}
      cy={((q.y || 0) + (q.h || 0) / 2) * bh} rx={(q.w || 0) * bw / 2} ry={(q.h || 0) * bh / 2} fill={q.c} />;
    const d = (q.p || []).map((v, k) => `${k ? "L" : "M"}${(v[0] * bw).toFixed(1)},${(v[1] * bh).toFixed(1)}`).join(" ");
    if (q.t === "line") {
      return <path key={i} d={d} fill="none" stroke={q.c} strokeWidth={sw} strokeLinecap="round" pathLength={1}
        strokeDasharray="1 1" strokeDashoffset={1 - Math.max(0, Math.min(1, p))} />;
    }
    return <path key={i} style={style} opacity={ps.opacity} d={d + " Z"} fill={q.c} />;
  });
  return <svg width={bw} height={bh} style={{ overflow: "visible",
    filter: `drop-shadow(0 ${(0.006 * H).toFixed(1)}px ${(0.02 * H).toFixed(1)}px rgba(0,0,0,0.35))` }}>{parts}</svg>;
};

/** A waffle / unit chart: the grid pops in, then cells fill one by one from the bottom row. */
const WaffleBody: React.FC<{ layer: Layer; ctx: Ctx }> = ({ layer, ctx }) => {
  const { W, H, t } = ctx;
  const lt = t - layer.from;
  const cols = layer.cols || 10, rows = layer.rows || 10;
  const bw = layer.w * W, bh = layer.h * H;
  const gap = 0.16;
  const cell = Math.min(bw / (cols + (cols - 1) * gap), bh / (rows + (rows - 1) * gap));
  const n = cols * rows;
  const per = (layer.fillFor || 1.4) / Math.max(1, layer.value || 1);
  const cells: React.ReactNode[] = [];
  for (let k = 0; k < n; k++) {
    const r = rows - 1 - Math.floor(k / cols), c = k % cols;
    const on = k < (layer.value || 0);
    const appear = Math.max(0, easeOf("backOut")((lt - (k / n) * 0.5) / 0.35));
    const fill = on ? easeOf("out")((lt - 0.45 - k * per) / 0.18) : 0;
    const bump = fill > 0 && fill < 1 ? 1 + 0.22 * Math.sin(Math.PI * fill) : 1;
    cells.push(<div key={k} style={{ position: "absolute", left: c * cell * (1 + gap), top: r * cell * (1 + gap), width: cell,
      height: cell, borderRadius: cell * 0.18, background: fill > 0.5 ? layer.fill : layer.offColor,
      transform: `scale(${(appear * bump).toFixed(4)})` }} />);
  }
  return <div style={{ position: "relative", width: cols * cell * (1 + gap) - cell * gap,
    height: rows * cell * (1 + gap) - cell * gap }}>{cells}</div>;
};

/** A measurement: a line drawn out from its middle, a tick and an arrow head at each end, its value beside. */
const MeasureBody: React.FC<{ layer: Layer; ctx: Ctx; draw: number }> = ({ layer, ctx, draw }) => {
  const { W, H } = ctx;
  const pts = (layer.points || [[0, 0], [0, 0]]) as [number, number][];
  const ax = pts[0][0] * W, ay = pts[0][1] * H, bx = pts[1][0] * W, by = pts[1][1] * H;
  const mx = (ax + bx) / 2, my = (ay + by) / 2;
  const ang = Math.atan2(by - ay, bx - ax);
  const p = Math.max(0, Math.min(1, draw));
  const sx = mx + (ax - mx) * p, sy = my + (ay - my) * p, ex = mx + (bx - mx) * p, ey = my + (by - my) * p;
  const sw = Math.max(2, (layer.stroke ?? 0.003) * H);
  const tick = 0.018 * H, head = 0.013 * H;
  const nx = -Math.sin(ang), ny = Math.cos(ang);
  const end = (x: number, y: number, dir: number, k: number) => (
    <g key={k} opacity={p > 0.97 ? 1 : 0}>
      <line x1={x + nx * tick} y1={y + ny * tick} x2={x - nx * tick} y2={y - ny * tick} stroke={layer.color} strokeWidth={sw} />
      <path d={`M${x - dir * Math.cos(ang - 0.5) * head},${y - dir * Math.sin(ang - 0.5) * head} L${x},${y} L${x - dir * Math.cos(ang + 0.5) * head},${y - dir * Math.sin(ang + 0.5) * head}`}
        fill="none" stroke={layer.color} strokeWidth={sw} strokeLinejoin="round" />
    </g>
  );
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        <line x1={sx} y1={sy} x2={ex} y2={ey} stroke={layer.color} strokeWidth={sw} strokeLinecap="round" />
        {end(ax, ay, -1, 0)}{end(bx, by, 1, 1)}
      </svg>
      {layer.text ? (
        <div style={{ position: "absolute", left: mx + nx * 0.05 * H, top: my + ny * 0.05 * H, transform: "translate(-50%, -50%)",
          fontFamily: FONTS[layer.font || "grotesk"] || GROTESK, fontWeight: 800, fontSize: (layer.size || 0.034) * H,
          color: layer.fill || "#fff", whiteSpace: "nowrap", opacity: Math.max(0, (p - 0.6) / 0.4), textShadow: SHADOW_SOFT(H) }}>
          {layer.text}
        </div>
      ) : null}
    </div>
  );
};

/** A circular loupe that magnifies one point of a picture, its rim in the kit colour. */
const LoupeBody: React.FC<{ layer: Layer; ctx: Ctx }> = ({ layer, ctx }) => {
  const { W, H } = ctx;
  const d = layer.w * W;
  const z = layer.zoom || 2.5;
  const iw = d * z * 1.6, ih = iw * 0.5625;
  return (
    <div style={{ width: d, height: d, borderRadius: "50%", overflow: "hidden", position: "relative",
      border: `${Math.max(3, 0.005 * H).toFixed(1)}px solid ${layer.color}`,
      boxShadow: `0 ${(0.01 * H).toFixed(1)}px ${(0.035 * H).toFixed(1)}px rgba(0,0,0,0.6)` }}>
      <SafeImg src={layer.src || ""} style={{ position: "absolute", width: iw, height: ih, objectFit: "cover", maxWidth: "none",
        left: d / 2 - (layer.fx ?? 0.5) * iw, top: d / 2 - (layer.fy ?? 0.5) * ih }} />
    </div>
  );
};

/** A row of tiles that pop in one after another (sources, organisations, items). */
const TilesBody: React.FC<{ layer: Layer; ctx: Ctx }> = ({ layer, ctx }) => {
  const { H, t } = ctx;
  const lt = t - layer.from;
  const s = (layer.size || 0.09) * H;
  return (
    <div style={{ display: "flex", gap: s * 0.28, alignItems: "flex-start" }}>
      {(layer.items || []).map((it, i) => {
        const p = Math.max(0, easeOf("backOut")((lt - i * (layer.stagger ?? 0.18)) / 0.4));
        return (
          <div key={i} style={{ width: s * 1.6, height: s, borderRadius: s * 0.14, background: layer.fill,
            display: "flex", alignItems: "center", justifyContent: "center", padding: "0 0.3em",
            fontFamily: NARROW, fontWeight: 800, fontSize: s * 0.3, letterSpacing: "0.04em", color: layer.color,
            textAlign: "center", lineHeight: 1.05, textTransform: "uppercase",
            transform: `scale(${p.toFixed(4)})`, opacity: Math.min(1, p * 2) }}>{it}</div>
        );
      })}
    </div>
  );
};

/** A label pill in the kit's pill colours. */
const PillBody: React.FC<{ layer: Layer; ctx: Ctx }> = ({ layer, ctx }) => {
  const { H } = ctx;
  const sz = (layer.size || 0.026) * H;
  return (
    <div style={{ fontFamily: FONTS[layer.font || "narrow"] || NARROW, fontWeight: 800, fontSize: sz, lineHeight: 1,
      letterSpacing: "0.08em", textTransform: "uppercase", color: layer.color, background: layer.fill,
      padding: `${(sz * 0.32).toFixed(1)}px ${(sz * 0.55).toFixed(1)}px ${(sz * 0.26).toFixed(1)}px`, borderRadius: sz * 0.22,
      whiteSpace: "nowrap", boxShadow: `0 ${(0.004 * H).toFixed(1)}px ${(0.012 * H).toFixed(1)}px rgba(0,0,0,0.4)` }}>
      {layer.text}
    </div>
  );
};

/** The kit's full-frame ground: a deep radial gradient that breathes slowly, a soft vignette, an optional grid. */
const BackdropBody: React.FC<{ layer: Layer; ctx: Ctx }> = ({ layer, ctx }) => {
  const { W, H, t } = ctx;
  const g = 0.06 * H;
  return (
    <div style={{ position: "absolute", left: 0, top: 0, width: W, height: H,
      background: `radial-gradient(ellipse at ${(50 + 4 * Math.sin(t * 0.3)).toFixed(2)}% 42%, ${layer.color} 0%, ${layer.color2} 100%)` }}>
      {layer.grid ? <div style={{ position: "absolute", inset: 0, opacity: 0.07,
        backgroundImage: "linear-gradient(rgba(255,255,255,0.6) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.6) 1px, transparent 1px)",
        backgroundSize: `${g}px ${g}px` }} /> : null}
      <div style={{ position: "absolute", inset: 0, background: "radial-gradient(ellipse at center, rgba(0,0,0,0) 55%, rgba(0,0,0,0.35) 100%)" }} />
    </div>
  );
};

const LayerView: React.FC<{ layer: Layer; ctx: Ctx }> = ({ layer, ctx }) => {
  const { t, W, H, dur, spec } = ctx;
  // Before any early return (a hook): the id of this layer's motion-blur filter.
  const mbId = React.useId().replace(/[^a-zA-Z0-9_-]/g, "");
  if (t < layer.from || t > layer.to) return null;
  const lt = t - layer.from;
  const k = layer.keys;
  const v = (p: string, rest: number) => valueAt(k, p, lt, rest);
  const opacity = v("opacity", 1) * layer.opacity;
  if (opacity <= 0.001) return null;
  const draw = Math.max(0, Math.min(1, v("draw", 1)));
  const wipe = Math.max(0, Math.min(1, v("wipe", 1)));
  const blur = v("blur", 0) * (H / 1080);
  const scale = v("scale", 1);
  // Motion blur (layer.mb): the layer's own speed over half a frame at 30 fps, as a directional blur.
  let mbX = 0, mbY = 0;
  if (layer.mb) {
    const dt = 1 / 60;
    const dx = (v("x", 0) - valueAt(k, "x", lt - dt, 0)) * W;
    const dy = (v("y", 0) - valueAt(k, "y", lt - dt, 0)) * H;
    const ds = (scale - valueAt(k, "scale", lt - dt, 1)) * Math.max(layer.w * W, layer.h * H, 0.2 * H);
    mbX = Math.min(40, Math.abs(dx) * layer.mb * 0.5 + Math.abs(ds) * layer.mb * 0.25);
    mbY = Math.min(40, Math.abs(dy) * layer.mb * 0.5 + Math.abs(ds) * layer.mb * 0.25);
  }
  const z = v("z", layer.z);
  // Depth parallax: nearer layers drift further than the stage as the graphic lives.
  const life = dur > 0 ? t / dur - 0.5 : 0;
  const px = spec.drift.x * life * z * 2 * W;
  const py = spec.drift.y * life * z * 2 * H;
  const fullFrame = layer.kind === "line" || layer.kind === "arrow" || layer.kind === "spot" || layer.kind === "particles"
    || layer.kind === "backdrop" || layer.kind === "measure" || layer.kind === "fx" || layer.kind === "game";
  const tx = layer.anchor === "l" ? "0%" : layer.anchor === "r" ? "-100%" : "-50%";
  const transform = fullFrame
    ? `translate3d(${(v("x", 0) * W + px).toFixed(2)}px, ${(v("y", 0) * H + py).toFixed(2)}px, ${(z * 200).toFixed(1)}px) scale(${scale.toFixed(4)})`
    : `translate(${tx}, -50%) translate3d(${px.toFixed(2)}px, ${py.toFixed(2)}px, ${(z * 200).toFixed(1)}px) rotateX(${v("rotX", 0).toFixed(2)}deg) rotateY(${v("rotY", 0).toFixed(2)}deg) rotate(${v("rot", 0).toFixed(2)}deg) scale(${(scale * v("sx", 1)).toFixed(4)}, ${(scale * v("sy", 1)).toFixed(4)})`;
  const base: React.CSSProperties = fullFrame
    ? { position: "absolute", left: 0, top: 0, width: W, height: H }
    // max-content: a block wider than the space right of its anchor keeps its own width (shrink-to-fit would
    // squeeze it to that space and the -50% / -100% shift would then put it off its anchor)
    : { position: "absolute", left: (layer.x + v("x", 0)) * W, top: (layer.y + v("y", 0)) * H, width: "max-content" };
  let body: React.ReactNode = null;
  switch (layer.kind) {
    case "text":
      body = <TextBody layer={layer} ctx={ctx} />;
      break;
    case "counter": {
      const ramp = Math.min(1, Math.max(0, lt / 1.2));
      const p = v("p", 1 - (1 - ramp) ** 4);
      const val = (layer.valueFrom || 0) + ((layer.valueTo || 0) - (layer.valueFrom || 0)) * p;
      body = <TextBody layer={layer} ctx={ctx} counterText={`${layer.prefix || ""}${formatCount(val, layer.decimals || 0, layer.group !== false)}${layer.suffix || ""}`} />;
      break;
    }
    case "rect": case "ellipse": case "bracket":
      body = <FormBody layer={layer} ctx={ctx} draw={draw} />;
      break;
    case "line": case "arrow":
      body = <LineBody layer={layer} ctx={ctx} draw={draw} />;
      break;
    case "pin":
      body = <PinBody layer={layer} ctx={ctx} />;
      break;
    case "spot": {
      const rx = (layer.w / 2) * W, ry = (layer.h / 2) * H;
      const cx = layer.x * W, cy = layer.y * H;
      body = <div style={{ position: "absolute", inset: 0,
        background: `radial-gradient(ellipse ${rx.toFixed(0)}px ${ry.toFixed(0)}px at ${cx.toFixed(0)}px ${cy.toFixed(0)}px, rgba(0,0,0,0) 0%, rgba(0,0,0,0) 78%, ${hexA(layer.fill || "#000000", 0.62)} 100%)` }} />;
      break;
    }
    case "image":
      body = (
        <div style={{ width: layer.w * W, height: layer.h * H, borderRadius: (layer.radius || 0) * H, overflow: "hidden",
          boxShadow: `0 ${(0.01 * H).toFixed(1)}px ${(0.04 * H).toFixed(1)}px rgba(0,0,0,0.55)`,
          border: layer.stroke ? `${((layer.stroke || 0) * H).toFixed(1)}px solid ${layer.color}` : undefined }}>
          <SafeImg src={layer.src || ""} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        </div>
      );
      break;
    case "particles":
      body = <Particles layer={layer} ctx={ctx} />;
      break;
    case "backdrop": body = <BackdropBody layer={layer} ctx={ctx} />; break;
    case "shape": body = <ShapeBody layer={layer} ctx={ctx} />; break;
    case "waffle": body = <WaffleBody layer={layer} ctx={ctx} />; break;
    case "measure": body = <MeasureBody layer={layer} ctx={ctx} draw={draw} />; break;
    case "loupe": body = <LoupeBody layer={layer} ctx={ctx} />; break;
    case "tiles": body = <TilesBody layer={layer} ctx={ctx} />; break;
    case "pill": body = <PillBody layer={layer} ctx={ctx} />; break;
    case "chart": body = <ChartBody layer={layer} ctx={ctx} />; break;
    case "card": body = <CardBody layer={layer} ctx={ctx} />; break;
    case "fx": body = <FxBody layer={layer} ctx={ctx} />; break;
    case "scribble": body = <ScribbleBody layer={layer} ctx={ctx} draw={draw} />; break;
    case "game": body = <GameBody layer={layer} ctx={ctx} />; break;
    default:
      return null;
  }
  return (
    <div style={{ ...base, transform, opacity: Math.min(1, opacity), transformStyle: "preserve-3d",
      filter: [blur > 0.05 ? `blur(${blur.toFixed(2)}px)` : "", mbX + mbY > 0.6 ? `url(#mb${mbId})` : ""].filter(Boolean).join(" ") || undefined,
      clipPath: layer.cut ? `inset(${(layer.cut[0] * 100).toFixed(2)}% -30% ${(layer.cut[1] * 100).toFixed(2)}% -30%)`
        : wipe < 0.999 ? wipeClip(layer.wipeFrom, wipe) : undefined,
      mixBlendMode: layer.kind !== "particles" ? (layer.blend as React.CSSProperties["mixBlendMode"]) : undefined }}>
      {mbX + mbY > 0.6 ? (
        <svg width={0} height={0} style={{ position: "absolute" }}>
          <filter id={`mb${mbId}`} x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation={`${mbX.toFixed(2)} ${mbY.toFixed(2)}`} />
          </filter>
        </svg>
      ) : null}
      {body}
    </div>
  );
};

/** The clip of a "wipe" key: the visible part grows from the left (default), the right, the top or the bottom. */
const wipeClip = (from: Layer["wipeFrom"], w: number): string => {
  const h = ((1 - w) * 100).toFixed(2);
  if (from === "r") return `inset(-20% -20% -20% ${h}%)`;
  if (from === "t") return `inset(-20% -20% ${h}% -20%)`;
  if (from === "b") return `inset(${h}% -20% -20% -20%)`;
  return `inset(-20% ${h}% -20% -20%)`;
};

const shadeBg = (kind: string, a: number): string => {
  const d = `rgba(0,0,0,${a.toFixed(3)})`;
  switch (kind) {
    case "bottom": return `linear-gradient(to top, ${d} 0%, rgba(0,0,0,0) 55%)`;
    case "top": return `linear-gradient(to bottom, ${d} 0%, rgba(0,0,0,0) 50%)`;
    case "left": return `linear-gradient(to right, ${d} 0%, rgba(0,0,0,0) 62%)`;
    case "right": return `linear-gradient(to left, ${d} 0%, rgba(0,0,0,0) 62%)`;
    case "full": return d;
    default: return `radial-gradient(ellipse at center, rgba(0,0,0,0) 35%, ${d} 100%)`;
  }
};

const onShot = (l: Layer) => l.kind === "fx" && (l.effect === "lens" || l.effect === "split" || l.effect === "glitch");

/** Draws a cleaned spec at second `t` of a graphic that lasts `dur` seconds. */
export const SpecStage: React.FC<{ spec: MotionSpec; t: number; dur: number }> = ({ spec, t, dur }) => {
  const { width: W, height: H } = useVideoConfig();
  const ctx: Ctx = { t, dur, W, H, spec };
  const into = Math.min(1, Math.max(0, t / 0.3));
  const ex = spec.exit.dur > 0 ? Math.min(1, Math.max(0, (t - (dur - spec.exit.dur)) / spec.exit.dur)) : 0;
  const e = ex * ex * (3 - 2 * ex);
  const life = dur > 0 ? t / dur - 0.5 : 0;
  let stage: React.CSSProperties = { opacity: 1 - (spec.exit.kind === "wipe" ? 0 : e) };
  if (spec.exit.kind === "blur") stage = { ...stage, filter: e > 0.01 ? `blur(${(14 * e * H / 1080).toFixed(2)}px)` : undefined };
  if (spec.exit.kind === "drop") stage = { ...stage, transform: `translateY(${(0.04 * H * e).toFixed(1)}px)` };
  if (spec.exit.kind === "scale") stage = { ...stage, transform: `scale(${(1 - 0.06 * e).toFixed(4)})` };
  if (spec.exit.kind === "wipe") stage = { ...stage, clipPath: e > 0.001 ? `inset(0 0 0 ${(e * 100).toFixed(2)}%)` : undefined };
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {spec.shade ? <AbsoluteFill style={{ background: shadeBg(spec.shade.kind, spec.shade.amount), opacity: into * (1 - e) }} /> : null}
      {/* Effects that process the shot itself (backdrop-filter: a magnifier, a before / after split, glitch slices) sit
          outside the 3D stage - a transformed / faded ancestor would cut them off from the footage they filter. */}
      {spec.layers.filter((l) => onShot(l) && t >= l.from && t <= l.to).map((l, i) => (
        <AbsoluteFill key={`shot-${l.id}-${i}`}><FxBody layer={l} ctx={ctx} /></AbsoluteFill>
      ))}
      <AbsoluteFill style={{ ...stage, perspective: `${(spec.persp * H / 1080).toFixed(0)}px` }}>
        <AbsoluteFill style={{ transformStyle: "preserve-3d",
          transform: `translate3d(${(spec.drift.x * life * W).toFixed(2)}px, ${(spec.drift.y * life * H).toFixed(2)}px, 0) rotateY(${(spec.drift.rotY * life).toFixed(3)}deg)` }}>
          {spec.layers.map((l, i) => (onShot(l) ? null : <LayerView key={`${l.id}-${i}`} layer={l} ctx={ctx} />))}
        </AbsoluteFill>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/** The overlay look: `overlay.spec` drawn over its own Sequence (frame 0 = the graphic's first frame). */
export const SmartSpec: React.FC<{ overlay: { spec?: unknown; durationInFrames: number; smartStill?: unknown } }> = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  // A still of the graphic at one moment (the critic's contact frames, an editor thumbnail): {t, dur} seconds.
  const still = stillOf(overlay.smartStill);
  const dur = still ? still.dur : overlay.durationInFrames / fps;
  const spec = React.useMemo(() => cleanSpec(overlay.spec, dur), [overlay.spec, dur]);
  if (!spec) return null;
  return <Guard><SpecStage spec={spec} t={still ? still.t : frame / fps} dur={dur} /></Guard>;
};

export const stillOf = (v: unknown): { t: number; dur: number } | null => {
  if (!v || typeof v !== "object") return null;
  const { t, dur } = v as { t?: unknown; dur?: unknown };
  return typeof t === "number" && typeof dur === "number" && Number.isFinite(t) && Number.isFinite(dur) && dur > 0
    ? { t: Math.max(0, Math.min(dur, t)), dur } : null;
};
