import React from "react";
import { AbsoluteFill } from "remotion";
import type { Overlay } from "../../types";
import { useLookSound } from "./LookSounds";
import type { SoundCue } from "./lookSoundPlan";
import {
  ANTON, ANTON_BASE, ANTON_CAP, ANTON_TOP, BlurDefs, CREAM, Caps, CornerShade, Figure, type FigSpec, Glyphs, type Look, type CSS, SOFT,
  SUBLINE, SerifWords, Stage, Vignette, WHITE, type Clock, type Roll, antonEm, blurRef, clamp01, easeIn, easeInOut,
  easeOut, easeOutQuart, figEm, landClicks, landOf, lerp, mix, outOf, posAt, prog, pushOf, px, readable, rgba, rollOf,
  rollTicks, safeOf, settle, shadow, sizeFor, speedAt, subEm, useClock, useSvgId, wrapBalanced,
} from "./nxKit";
import { type Drawn, type Fig, clip, digits, drawnOf, figureOf, figureSpan, numOf, sidesOf, str, trimEnds } from "./nxFormat";

/**
 * NUMBERS PRO (family "nx-"): thirteen figure looks drawn the way a top
 * documentary's graphics department sets a number - one clear device each,
 * the figure always in digits with its unit as said, landing on its spoken
 * word with a soft tick, leaving in its last 10 frames. Built from the owner's
 * VidRush reference (the framed callout boxes and their dashed leader, the
 * serif sentence, "the same place every time") and GoMotion's ranking row:
 *
 *   nx-stat-context   LOWER LEFT  the figure big, the rest of its sentence under it in serif italic
 *                                 ("40 MILLION" / "people depend on this one river")
 *   nx-frame-share    FULL FRAME  the picture itself is the gauge: a hairline sweeps to the share, the
 *                                 rest of the frame drains to grey, the count riding the line
 *   nx-ring-label     LOWER LEFT  a precise ring filling round the percent, its label beside it
 *   nx-delta-arrow    CENTRE      then and now: the earlier figure ghosted, an arrow drawing to the later
 *                                 one, the change under them only when it was said
 *   nx-money-roll     LOWER LEFT  money on slot reels with a motion blur that stop with a small bounce,
 *                                 the $ small, the scale word (BILLION) rising into its slot on the landing
 *   nx-dimension      LOWER LEFT  an engineer's dimension line - extension ticks, arrowheads - with the
 *                                 measurement in its gap; upright for a height, a depth, a level
 *   nx-callout-box    LEFT THIRD  VidRush's framed glass box: the edge draws round, the figure counts
 *                                 inside, a dashed leader runs to the point in the picture (anchor)
 *   nx-callout-pair   CENTRE      two framed boxes joined by a dashed line with an arrowhead: before and
 *                                 after, two estimates; the change on the line when it was said
 *   nx-number-line    CENTRE      two figures pinned on one shared scale, the gap between them bracketed
 *   nx-record-floor   LOWER LEFT  a dashed record line labelled as said; the figure breaks down through
 *                                 it (a record low) or up through it (a high)
 *   nx-rate-fraction  LOWER LEFT  a rate as a fraction: the figure over a hairline, "PER PERSON" /
 *                                 "A DAY" under it with a small drawn icon
 *   nx-rank-rows      CENTRE      a ranking: rows slide in by rank, thin bars grow to scale, values count
 *   nx-inline-count   LOWER LEFT  the sentence in clean caps, its figure counting in place in the accent
 *
 * Values come from value / prefix / suffix / items, else from the words
 * (spoken numbers in digits); a look given no number shows its words.
 * Context lines, record phrases and rates are the narration's own words
 * (src/treatments.py figure_line_props). The video's one accent colours the
 * signs, rings, leaders and the second figure; everything else is white.
 */

// ------------------------------------------------------------------ shared
const LOW_RX = /\b(LOW|LOWEST|LEAST|MINIMUM|DRIEST|SMALLEST|FEWEST|SHALLOWEST|WORST|DEAD POOL|FELL|DROPPED|SANK|DOWN|BELOW)\b/;
const HIGH_RX = /\b(HIGH|HIGHEST|MOST|PEAK|LARGEST|BIGGEST|HOTTEST|WETTEST|ABOVE|RECORD HIGH|TOPPED|SURPASSED)\b/;
const UPRIGHT_RX = /\b(HIGH|HIGHER|HIGHEST|TALL|TALLER|DEEP|DEEPER|DEPTH|HEIGHT|ELEVATION|ABOVE|BELOW|SEA LEVEL|DROP|DROPPED|FELL|FALLEN|LOWER|RISE|ROSE|RISEN|UNDERWATER|SURFACE|LEVEL|STAGE|CREST|DOWN|UP)\b/;

/** "PEOPLE DISPLACED" -> "People displaced"; a line in its own case is left as said. */
const asSaid = (s: string): string => {
  const t = str(s);
  if (!t || t !== t.toUpperCase() || !/[A-Z]/.test(t)) return t;
  const low = t.toLowerCase();
  return low.charAt(0).toUpperCase() + low.slice(1);
};
const specOf = (d: Drawn): FigSpec => ({ fig: d.fig, pre: d.pre, top: d.top, tag: d.tag });

/** A look with no number: its words, in clean caps, low on the left (nothing made up). */
const WordsOnly: React.FC<{ words: string }> = ({ words }) => {
  const t = useClock();
  const text = clip(trimEnds(digits(words)).toUpperCase(), 40) || "";
  const sound = useLookSound(text ? [{ name: "swoosh-text", alt: ["whoosh-soft-v2", "whoosh-soft"], at: 3, gain_db: -6 }] : []);
  if (!text) return null;
  const size = sizeFor(54, t, antonEm(text), Math.min(0.46 * t.width, 880 * t.kw));
  return (
    <AbsoluteFill>
      {sound}
      <CornerShade o={prog(t.f, 0, 10) * outOf(t, 10)} />
      <Stage t={t} place="lower-left">
        <div style={{ position: "relative" }}>
          <Glyphs text={text} size={size} t={t} enter={2} stagger={0.5} />
        </div>
      </Stage>
    </AbsoluteFill>
  );
};

/** The roll's soft ticks and its landing click (never a punch). */
const useRollSound = (rolls: Roll[]): React.ReactNode => {
  const lands = rolls.map(landOf);
  return useLookSound([...rollTicks(rolls, lands), ...landClicks(lands)]);
};
/** A look drawn only when its overlay has a figure, else its words. */
const withFigure = (Draw: React.FC<{ overlay: Overlay; accent: string; f: Fig }>, money = false): Look => ({ overlay, accent }) => {
  const f = figureOf(overlay, money);
  return f.value === null ? <WordsOnly words={f.label || f.extra} /> : <Draw overlay={overlay} accent={accent} f={f} />;
};

// ================================================================== nx-stat-context
const StatContextDraw: React.FC<{ overlay: Overlay; accent: string; f: Fig }> = ({ overlay, accent, f }) => {
  const t = useClock();
  const blurId = useSvgId("nxsc");
  const acc = readable(accent);
  const d = drawnOf(f);
  const spec = specOf(d);
  const roll = rollOf(d.fig, 3, 22);
  const land = landOf(roll);
  const sound = useRollSound([roll]);
  const maxW = Math.min(0.48 * t.width, 920 * t.kw);
  const size = sizeFor(104, t, figEm(spec), maxW);
  // The context: the rest of its sentence as said (subtitle), else what it counts.
  const said = str(overlay.subtitle);
  const context = clip(said ? digits(said) : asSaid(f.label || f.extra), 64);
  const words = context ? context.split(" ") : [];
  const ctxSize = 46 * t.k;
  const o = outOf(t, 8);
  return (
    <AbsoluteFill>
      {sound}
      <BlurDefs id={blurId} k={t.k} />
      <CornerShade o={prog(t.f, 0, 10) * outOf(t, 10)} />
      <Stage t={t} place="lower-left" push={pushOf(t, land)}>
        <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
          <Figure s={spec} size={size} t={t} roll={roll} blurId={blurId} signColor={acc} />
          {words.length ? (
            <div style={{ marginTop: size * 0.02, marginLeft: size * 0.03, transform: `translateY(${((1 - o) * 10 * t.k).toFixed(2)}px)` }}>
              <SerifWords words={words} t={t} at={land - 9} step={1.7} size={ctxSize} italic color={CREAM} maxW={maxW}
                out={o} lineHeight={1.16} />
            </div>
          ) : null}
        </div>
      </Stage>
    </AbsoluteFill>
  );
};

// ================================================================== nx-frame-share
const FrameShareDraw: React.FC<{ overlay: Overlay; accent: string; f: Fig }> = ({ overlay, accent, f }) => {
  const t = useClock();
  const blurId = useSvgId("nxfs");
  const acc = readable(accent);
  const { width: W, height: H, k } = t;
  const d = drawnOf(f);
  const spec: FigSpec = { fig: d.fig, top: d.top || "%" };
  const share = clamp01((f.value ?? 0) / 100);
  const C0 = 5;
  const roll = rollOf(d.fig, C0, 24);
  const land = landOf(roll);
  const sound = useRollSound([roll]);
  const sweep = easeOutQuart(clamp01((t.f - C0) / Math.max(1, land - C0)));
  const out = outOf(t, 9);
  const X = W * share * sweep;
  const grey = prog(t.f, 0, 7) * out;
  const lineO = prog(t.f, 2, 6) * out;
  const size = sizeFor(112, t, figEm(spec), 0.3 * W);
  const label = f.label || "";
  const kicker = f.label ? f.extra : "";
  const labelPx = 26 * k;
  const blockW = Math.max(figEm(spec) * size, subEm(label, 0.16) * labelPx, subEm(kicker, 0.2) * 22 * k);
  const gap = 34 * t.kw;
  const right = share <= 0.66;                     // the figure rides on the grey side while there is room
  const left = right ? X + gap : X - gap - blockW;
  const foot = H * 0.25;
  const figTop = H - foot - (label ? labelPx * 1.9 : 0) - size;
  const dotY = figTop + size * (ANTON_TOP + ANTON_CAP / 2);
  return (
    <AbsoluteFill>
      {sound}
      <BlurDefs id={blurId} k={k} />
      {/* The rest of the picture drains to grey, darker toward its far edge. */}
      <div style={{ position: "absolute", left: X, top: 0, right: 0, bottom: 0, opacity: grey,
        backdropFilter: "grayscale(1) brightness(0.5) contrast(0.92)", WebkitBackdropFilter: "grayscale(1) brightness(0.5) contrast(0.92)",
        background: "linear-gradient(90deg, rgba(8,10,14,.16) 0%, rgba(8,10,14,.34) 100%)" } as CSS} />
      {/* The scale along the top: unlabelled ticks every tenth, the half a little longer. */}
      <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 40 * t.kw, opacity: lineO * 0.9 }}>
        {Array.from({ length: 11 }, (_, i) => (
          <div key={i} style={{ position: "absolute", left: (W * i) / 10 - (i === 10 ? 2 * k : i === 0 ? 0 : k), top: 0,
            width: Math.max(1.5, 2 * k), height: (i % 5 === 0 ? 28 : 15) * t.kw, background: "rgba(255,255,255,.6)",
            boxShadow: "0 1px 3px rgba(0,0,0,.5)" }} />
        ))}
      </div>
      {/* The line: a hairline the height of the frame with a soft glow, an accent dot level with the figure. */}
      <div style={{ position: "absolute", left: X - Math.max(1.5, 1.75 * k), top: 0, bottom: 0, width: Math.max(2, 3.5 * k), opacity: lineO,
        background: "linear-gradient(180deg, rgba(255,255,255,.9) 0%, #fff 55%, rgba(255,255,255,.7) 100%)",
        boxShadow: `0 0 ${px(12 * k)} rgba(255,255,255,.5), 0 0 ${px(2 * k)} rgba(0,0,0,.6)` }} />
      <div style={{ position: "absolute", left: X - 9 * k, top: dotY - 9 * k, width: 18 * k, height: 18 * k, borderRadius: "50%",
        background: acc, opacity: lineO, boxShadow: `0 0 0 ${px(4 * k)} rgba(0,0,0,.3), 0 0 ${px(16 * k)} ${rgba(acc, 0.85)}` }} />
      <div style={{ position: "absolute", left, top: figTop - (kicker ? 40 * k : 0), display: "flex", flexDirection: "column",
        alignItems: right ? "flex-start" : "flex-end", width: blockW }}>
        {kicker ? <div style={{ marginBottom: 14 * k }}><Caps text={kicker} size={22 * k} t={t} at={8} color={acc} track={0.2} /></div> : null}
        <Figure s={spec} size={size} t={t} roll={roll} blurId={blurId} signColor={acc} />
        {label ? (
          <div style={{ marginTop: size * 0.12 }}>
            <Caps text={label} size={labelPx} t={t} at={land - 8} />
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== nx-ring-label
const RingLabelDraw: React.FC<{ overlay: Overlay; accent: string; f: Fig }> = ({ accent, f }) => {
  const t = useClock();
  const blurId = useSvgId("nxrl");
  const gid = useSvgId("nxrlg");
  const acc = readable(accent);
  const { k } = t;
  const d = drawnOf(f);
  const spec: FigSpec = { fig: d.fig, top: d.top || "%" };
  const share = clamp01((f.value ?? 0) / 100);
  const C0 = 4;
  const roll = rollOf(d.fig, C0, 24);
  const land = landOf(roll);
  const sound = useRollSound([roll]);
  const D = 258 * k;
  const SW = 17 * k;
  const r = D / 2 - SW / 2 - 14 * k;
  const C = 2 * Math.PI * r;
  const fill = share * easeOutQuart(clamp01((t.f - C0) / Math.max(1, land - C0)));
  const track = prog(t.f, 0, 12, easeInOut);
  const out = outOf(t, 9);
  const enter = prog(t.f, 0, 10);
  const size = sizeFor(70, t, figEm(spec), D - 2 * SW - 52 * k);
  const head = (fill * 360 - 90) * (Math.PI / 180);
  const hx = D / 2 + r * Math.cos(head);
  const hy = D / 2 + r * Math.sin(head);
  const label = clip(f.label || "", 60);
  const extra = f.label ? f.extra : "";
  const maxW = Math.min(0.34 * t.width, 660 * t.kw);
  const lcap = 48;
  const words = label ? wrapBalanced(label.split(" "), maxW, (s) => antonEm(s) * (lcap / ANTON_CAP) * k, label.length > 30 ? 3 : 2) : [];
  const lsize = Math.min((lcap / ANTON_CAP) * k, ...words.map((l) => maxW / Math.max(0.5, antonEm(l))));
  return (
    <AbsoluteFill>
      {sound}
      <BlurDefs id={blurId} k={k} />
      <CornerShade o={enter * out} />
      <Stage t={t} place="lower-left" push={pushOf(t, land)}>
        <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
          <div style={{ position: "relative", width: D, height: D, opacity: out,
            transform: `scale(${(0.88 + 0.12 * enter - 0.04 * (1 - out)).toFixed(4)}) rotate(${((1 - enter) * -50).toFixed(2)}deg)` }}>
            <svg width={D} height={D} style={{ position: "absolute", inset: 0, overflow: "visible", filter: shadow(k, true) }}>
              <defs>
                <linearGradient id={gid} x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0" stopColor={mix(acc, "#ffffff", 0.35)} />
                  <stop offset="1" stopColor={acc} />
                </linearGradient>
              </defs>
              {Array.from({ length: 60 }, (_, i) => {
                const a = (i / 60) * Math.PI * 2 - Math.PI / 2;
                const r1 = D / 2 - 5 * k;
                const r2 = D / 2 + (i % 5 === 0 ? 6 : 2) * k;
                const on = i / 60 < fill - 1e-6;
                return <line key={i} x1={D / 2 + r1 * Math.cos(a)} y1={D / 2 + r1 * Math.sin(a)} x2={D / 2 + r2 * Math.cos(a)}
                  y2={D / 2 + r2 * Math.sin(a)} stroke={on ? acc : "rgba(255,255,255,.55)"}
                  strokeWidth={Math.max(1, (i % 5 === 0 ? 2.6 : 1.6) * k)} strokeLinecap="round" opacity={clamp01(track * 60 - i * 0.5)} />;
              })}
              <circle cx={D / 2} cy={D / 2} r={r} fill="rgba(0,0,0,.22)" stroke="rgba(255,255,255,.17)" strokeWidth={SW}
                strokeDasharray={`${(C * track).toFixed(2)} ${C.toFixed(2)}`} transform={`rotate(-90 ${D / 2} ${D / 2})`} />
              {fill > 0.002 ? (
                <circle cx={D / 2} cy={D / 2} r={r} fill="none" stroke={`url(#${gid})`} strokeWidth={SW} strokeLinecap="round"
                  strokeDasharray={`${(C * fill).toFixed(2)} ${C.toFixed(2)}`} transform={`rotate(-90 ${D / 2} ${D / 2})`} />
              ) : null}
              {fill > 0.01 ? <circle cx={hx} cy={hy} r={SW * 0.34} fill="#fff" style={{ filter: `drop-shadow(0 0 ${px(7 * k)} ${acc})` }} /> : null}
            </svg>
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Figure s={spec} size={size} t={t} roll={roll} blurId={blurId} signColor={acc} />
            </div>
          </div>
          {words.length || extra ? (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", marginLeft: 38 * k }}>
              {words.map((l, i) => (
                <div key={i} style={{ marginTop: i ? lsize * 0.08 : 0 }}>
                  <Glyphs text={l} size={lsize} t={t} enter={8 + i * 3} stagger={0.45} exitFrom={i * 3} />
                </div>
              ))}
              {extra ? <div style={{ marginTop: 16 * k }}><Caps text={extra} size={22 * k} t={t} at={land - 6} color={SOFT} /></div> : null}
            </div>
          ) : null}
        </div>
      </Stage>
    </AbsoluteFill>
  );
};

// ================================================================== nx-delta-arrow
const DeltaArrowDraw: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const t = useClock();
  const blurId = useSvgId("nxda");
  const acc = readable(accent);
  const { k, width: W } = t;
  const full = Boolean(overlay.fullFrame);
  const sides = sidesOf(overlay);
  const specs = sides.map((s) => specOf(s.drawn));
  const rolls = [rollOf(specs[0].fig, 4, 16), rollOf(specs[1].fig, 16, 20)];
  const lands = rolls.map(landOf);
  const sound = useRollSound(rolls);
  const down = sides[1].drawn.value < sides[0].drawn.value;
  const arrowW = 190 * k;
  const SMALL = 0.66;
  const room = Math.min(W - 2 * safeOf(t) - arrowW - 140 * k, 1560 * t.kw);
  const size = sizeFor(full ? 150 : 132, t, figEm(specs[0]) * SMALL + figEm(specs[1]), room);
  const s0 = size * SMALL;
  const title = clip(trimEnds(digits(str(overlay.text))).toUpperCase(), 56);
  const change = clip(trimEnds(digits(str(overlay.subtitle))).toUpperCase(), 32);
  const ap = prog(t.f, 12, 12, easeInOut);
  const out = outOf(t, 9);
  const ghost = 1 - 0.45 * prog(t.f, lands[1] - 6, 12);
  const labelPx = 24 * k;
  const cap1 = size * ANTON_CAP;
  const aw = Math.max(3, 5 * k);
  const side = (i: number) => (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", opacity: i === 0 ? ghost : 1 }}>
      {sides[i].label ? (
        <div style={{ marginBottom: 16 * k }}>
          <Caps text={sides[i].label} size={labelPx} t={t} at={i ? 14 : 3} color={i ? acc : SOFT} track={0.18} />
        </div>
      ) : null}
      <Figure s={specs[i]} size={i ? size : s0} t={t} roll={rolls[i]} blurId={blurId} enter={i ? 14 : 2} signColor={i ? acc : WHITE}
        exitFrom={i * 3} />
    </div>
  );
  const changeP = prog(t.f, lands[1] - 2, 10);
  return (
    <AbsoluteFill>
      {sound}
      <BlurDefs id={blurId} k={k} />
      {!full ? <Vignette o={prog(t.f, 0, 10) * out} centre={0.38} edge={0.62} /> : null}
      <Stage t={t} place="center" push={pushOf(t, lands[1], 0.015)}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
          {title ? <div style={{ marginBottom: 46 * k }}><Caps text={title} size={28 * k} t={t} at={2} track={0.22} /></div> : null}
          <div style={{ display: "flex", alignItems: "flex-end" }}>
            {side(0)}
            <svg width={arrowW} height={cap1} viewBox={`0 0 ${arrowW} ${cap1}`}
              style={{ margin: `0 ${48 * k}px ${size * (1 - ANTON_BASE)}px`, overflow: "visible", opacity: out, filter: shadow(k, true) }}>
              <line x1={0} y1={cap1 / 2} x2={(arrowW - 30 * k) * ap} y2={cap1 / 2} stroke={acc} strokeWidth={aw} strokeLinecap="round" />
              {ap > 0.8 ? (
                <path d={`M ${arrowW - 34 * k} ${cap1 / 2 - 20 * k} L ${arrowW - 2 * k} ${cap1 / 2} L ${arrowW - 34 * k} ${cap1 / 2 + 20 * k}`}
                  fill="none" stroke={acc} strokeWidth={aw} strokeLinecap="round" strokeLinejoin="round" opacity={clamp01((ap - 0.8) / 0.2)} />
              ) : null}
            </svg>
            {side(1)}
          </div>
          {change ? (
            <div style={{ display: "flex", alignItems: "center", marginTop: 40 * k, opacity: changeP * out,
              transform: `translateY(${((1 - changeP) * 12 * k).toFixed(2)}px)`, filter: shadow(k, true) }}>
              <svg width={22 * k} height={19 * k} viewBox="0 0 18 16" style={{ marginRight: 14 * k }}>
                <path d={down ? "M1 2 L17 2 L9 15 Z" : "M1 14 L17 14 L9 1 Z"} fill={acc} />
              </svg>
              <div style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: 30 * k, letterSpacing: "0.16em", color: acc,
                whiteSpace: "nowrap", lineHeight: 1 }}>{change}</div>
            </div>
          ) : null}
        </div>
      </Stage>
    </AbsoluteFill>
  );
};
const DeltaArrow: Look = ({ overlay, accent }) => (sidesOf(overlay).length < 2
  ? <StatContext overlay={overlay} accent={accent} /> : <DeltaArrowDraw overlay={overlay} accent={accent} />);

// ================================================================== nx-money-roll
const MoneyRollDraw: React.FC<{ overlay: Overlay; accent: string; f: Fig }> = ({ accent, f }) => {
  const t = useClock();
  const blurId = useSvgId("nxmr");
  const acc = readable(accent);
  const { k } = t;
  const d = drawnOf(f, true);
  const spec: FigSpec = { fig: d.fig, pre: "$", top: d.top, tag: d.tag };
  // Slot reels: more laps than an odometer, a heavier blur, a small bounce as each stops.
  const base = rollOf(d.fig, 3, 24, false, 2.4);
  const reel: Roll = { ...base, to: base.to.map((v, c) => v + 10 * (1 + c)) };
  const land = landOf(reel);
  const sound = useRollSound([reel]);
  const size = sizeFor(100, t, figEm(spec), Math.min(0.5 * t.width, 980 * t.kw));
  const label = f.label || f.extra;
  const extra = f.label ? f.extra : "";
  const posFn = (i: number) => {
    const c = reel.cols.indexOf(i);
    if (c < 0) return null;
    const after = t.f - reel.ends[c];
    const p = posAt(reel, c, t.f);
    return after > 0 ? p - 0.08 * Math.sin(after * 0.95) * Math.exp(-after * 0.33) : p;
  };
  return (
    <AbsoluteFill>
      {sound}
      <BlurDefs id={blurId} k={k} />
      <CornerShade o={prog(t.f, 0, 10) * outOf(t, 10)} />
      <Stage t={t} place="lower-left" push={pushOf(t, land)}>
        <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
          <Figure s={spec} size={size} t={t} roll={reel} posFn={posFn} blurBoost={1.35} blurId={blurId} signColor={acc}
            tagAt={land - 3} />
          {label ? (
            <div style={{ marginTop: size * 0.16 }}>
              <Caps text={clip(label, 44)} size={27 * k} t={t} at={land - 4} />
            </div>
          ) : null}
          {extra ? <div style={{ marginTop: 12 * k }}><Caps text={clip(extra, 44)} size={21 * k} t={t} at={land} color={SOFT} /></div> : null}
        </div>
      </Stage>
    </AbsoluteFill>
  );
};

// ================================================================== nx-dimension
const DimensionDraw: React.FC<{ overlay: Overlay; accent: string; f: Fig }> = ({ overlay, accent, f }) => {
  const t = useClock();
  const blurId = useSvgId("nxdm");
  const acc = readable(accent);
  const { k } = t;
  const d = drawnOf(f);
  const spec = specOf(d);
  const roll = rollOf(d.fig, 4, 22);
  const land = landOf(roll);
  const sound = useRollSound([roll]);
  const all = `${f.words.toUpperCase()} ${str(overlay.subtitle).toUpperCase()} ${str(overlay.label).toUpperCase()}`;
  const upright = UPRIGHT_RX.test(all);
  const size = sizeFor(upright ? 92 : 84, t, figEm(spec), 0.4 * t.width);
  const figW = figEm(spec) * size;
  const cap = size * ANTON_CAP;
  const label = f.label || f.extra;
  const extra = f.label ? f.extra : "";
  const sw = Math.max(2, 3.5 * k);
  const out = outOf(t, 9);
  const ext = prog(t.f, 1, 9) * out;
  const grow = prog(t.f, 4, 14, easeInOut);
  const ao = clamp01((grow - 0.82) / 0.18) * out;
  const head = (x: number, y: number, dir: number, vertical: boolean) => {
    const a = 20 * k;
    const b = 10 * k;
    const pts = vertical ? `${x - b},${y - dir * a} ${x},${y} ${x + b},${y - dir * a}` : `${x - dir * a},${y - b} ${x},${y} ${x - dir * a},${y + b}`;
    return <polyline points={pts} fill="none" stroke={WHITE} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" opacity={ao} />;
  };
  const labels = (
    <>
      {label ? <div style={{ marginTop: 20 * k }}><Caps text={label} size={25 * k} t={t} at={land - 8} /></div> : null}
      {extra ? <div style={{ marginTop: 12 * k }}><Caps text={extra} size={20 * k} t={t} at={land - 4} color={SOFT} /></div> : null}
    </>
  );
  if (!upright) {
    // Across: the line spans past the figure both sides, the figure set in its gap.
    const L = Math.max(640 * k, figW + 360 * k);
    const half = L / 2;
    const gapHalf = figW / 2 + 30 * k;
    const segLen = half - gapHalf;
    const boxH = cap + 24 * k;
    const y = boxH / 2;
    return (
      <AbsoluteFill>
        {sound}
        <BlurDefs id={blurId} k={k} />
        <CornerShade o={prog(t.f, 0, 10) * out} />
        <Stage t={t} place="lower-left" push={pushOf(t, land)}>
          <div style={{ position: "relative", width: L, display: "flex", flexDirection: "column", alignItems: "center" }}>
            <div style={{ position: "relative", width: L, height: boxH }}>
              <svg width={L} height={boxH} style={{ position: "absolute", left: 0, top: 0, overflow: "visible", filter: shadow(k, true) }}>
                <line x1={sw / 2} y1={y - 34 * k * ext} x2={sw / 2} y2={y + 34 * k * ext} stroke={WHITE} strokeWidth={sw} opacity={ext} />
                <line x1={L - sw / 2} y1={y - 34 * k * ext} x2={L - sw / 2} y2={y + 34 * k * ext} stroke={WHITE} strokeWidth={sw} opacity={ext} />
                <line x1={half - gapHalf} y1={y} x2={half - gapHalf - (segLen - 2 * sw) * grow} y2={y} stroke={WHITE} strokeWidth={sw} opacity={out} />
                <line x1={half + gapHalf} y1={y} x2={half + gapHalf + (segLen - 2 * sw) * grow} y2={y} stroke={WHITE} strokeWidth={sw} opacity={out} />
                {head(sw * 1.6, y, -1, false)}
                {head(L - sw * 1.6, y, 1, false)}
              </svg>
              <div style={{ position: "absolute", left: 0, right: 0, top: y - size * (ANTON_TOP + ANTON_CAP / 2), display: "flex",
                justifyContent: "center" }}>
                <Figure s={spec} size={size} t={t} roll={roll} blurId={blurId} signColor={acc} tagColor={acc} />
              </div>
            </div>
            {labels}
          </div>
        </Stage>
      </AbsoluteFill>
    );
  }
  // Upright: a height, a depth, a level - the dimension stands at the left of the figure.
  const Hd = cap + 110 * k;
  const x = 22 * k;
  const mid = Hd / 2;
  return (
    <AbsoluteFill>
      {sound}
      <BlurDefs id={blurId} k={k} />
      <CornerShade o={prog(t.f, 0, 10) * out} />
      <Stage t={t} place="lower-left" push={pushOf(t, land)}>
        <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
          <svg width={44 * k} height={Hd} style={{ overflow: "visible", filter: shadow(k, true), marginRight: 34 * k }}>
            <line x1={x - 24 * k * ext} y1={sw / 2} x2={x + 24 * k * ext} y2={sw / 2} stroke={WHITE} strokeWidth={sw} opacity={ext} />
            <line x1={x - 24 * k * ext} y1={Hd - sw / 2} x2={x + 24 * k * ext} y2={Hd - sw / 2} stroke={WHITE} strokeWidth={sw} opacity={ext} />
            <line x1={x} y1={mid} x2={x} y2={mid - (mid - 2 * sw) * grow} stroke={WHITE} strokeWidth={sw} opacity={out} />
            <line x1={x} y1={mid} x2={x} y2={mid + (mid - 2 * sw) * grow} stroke={WHITE} strokeWidth={sw} opacity={out} />
            {head(x, sw * 1.6, -1, true)}
            {head(x, Hd - sw * 1.6, 1, true)}
          </svg>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
            <Figure s={spec} size={size} t={t} roll={roll} blurId={blurId} signColor={acc} tagColor={acc} />
            {labels}
          </div>
        </div>
      </Stage>
    </AbsoluteFill>
  );
};

// ================================================================== the glass box (callouts)
/** overlay.anchor as a point of the frame (0..1), else null. */
const anchorOf = (ov: Overlay): { x: number; y: number } | null => {
  const a = ov.anchor as { x?: unknown; y?: unknown } | undefined;
  const x = Number(a?.x);
  const y = Number(a?.y);
  return a && Number.isFinite(x) && Number.isFinite(y) ? { x: Math.min(0.97, Math.max(0.03, x)), y: Math.min(0.95, Math.max(0.05, y)) } : null;
};
/**
 * A framed glass box (VidRush's callout): a smoky fill that softens the
 * picture behind it, its edge drawing round from the top left. No opacity is
 * ever set above the fill (that would switch its blur off).
 */
const GlassBox: React.FC<{ w: number; h: number; t: Clock; at: number; edge: string; out: number; children: React.ReactNode }> =
  ({ w, h, t, at, edge, out, children }) => {
    const { k } = t;
    const p = prog(t.f, at, 14, easeInOut);
    const fillP = prog(t.f, at + 2, 10);
    const sw = Math.max(2, 3 * k);
    const per = 2 * (w + h);
    return (
      <div style={{ position: "relative", width: w, height: h }}>
        <div style={{ position: "absolute", inset: 0, borderRadius: 6 * k, opacity: fillP * out,
          background: "linear-gradient(160deg, rgba(10,11,15,.66) 0%, rgba(6,7,10,.58) 100%)",
          backdropFilter: "blur(10px) saturate(0.8) brightness(0.85)", WebkitBackdropFilter: "blur(10px) saturate(0.8) brightness(0.85)",
          boxShadow: `0 ${px(16 * k)} ${px(44 * k)} rgba(0,0,0,.38)` } as CSS} />
        <svg width={w} height={h} style={{ position: "absolute", inset: 0, overflow: "visible", opacity: out,
          filter: `drop-shadow(0 0 ${px(6 * k)} rgba(0,0,0,.35))` }}>
          <rect x={sw / 2} y={sw / 2} width={w - sw} height={h - sw} rx={6 * k} fill="none" stroke={edge} strokeWidth={sw}
            strokeDasharray={`${(per * p).toFixed(2)} ${per.toFixed(2)}`} />
        </svg>
        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
          opacity: out }}>
          {children}
        </div>
      </div>
    );
  };
/** A dashed leader drawing from (sx, sy) to (ax, ay), a ring settling on the point. */
const Leader: React.FC<{ t: Clock; sx: number; sy: number; ax: number; ay: number; at: number; color: string; out: number }> =
  ({ t, sx, sy, ax, ay, at, color, out }) => {
    const { k, width: W, height: H } = t;
    const lp = prog(t.f, at, 14, easeInOut);
    const ex = lerp(sx, ax, lp);
    const ey = lerp(sy, ay, lp);
    const ring = prog(t.f, at + 12, 10);
    return (
      <svg width={W} height={H} style={{ position: "absolute", inset: 0, overflow: "visible", opacity: out,
        filter: `drop-shadow(0 ${px(1 * k)} ${px(2 * k)} rgba(0,0,0,.7))` }}>
        <line x1={sx} y1={sy} x2={ex} y2={ey} stroke="rgba(0,0,0,.45)" strokeWidth={Math.max(4, 7 * k)} strokeDasharray={`${12 * k} ${8 * k}`}
          strokeLinecap="round" />
        <line x1={sx} y1={sy} x2={ex} y2={ey} stroke={color} strokeWidth={Math.max(2, 4 * k)} strokeDasharray={`${12 * k} ${8 * k}`}
          strokeLinecap="round" />
        {ring > 0 ? (
          <>
            <circle cx={ax} cy={ay} r={8 * k} fill={color} opacity={ring} />
            <circle cx={ax} cy={ay} r={(12 + 18 * ring) * k} fill="none" stroke={color} strokeWidth={Math.max(1.5, 2.5 * k)} opacity={(1 - ring) * 0.9} />
            <circle cx={ax} cy={ay} r={16 * k} fill="none" stroke={rgba(color, 0.75)} strokeWidth={Math.max(1.5, 2.5 * k)} opacity={ring} />
          </>
        ) : null}
      </svg>
    );
  };

// ================================================================== nx-callout-box
const CalloutBoxDraw: React.FC<{ overlay: Overlay; accent: string; f: Fig }> = ({ overlay, accent, f }) => {
  const t = useClock();
  const blurId = useSvgId("nxcb");
  const acc = readable(accent);
  const { k, width: W, height: H } = t;
  const d = drawnOf(f);
  const spec = specOf(d);
  const roll = rollOf(d.fig, 6, 18);
  const land = landOf(roll);
  const sound = useRollSound([roll]);
  const out = outOf(t, 9);
  const label = clip((f.label || f.extra).toUpperCase(), 40);
  const lcap = 40;
  const lsize = (lcap / ANTON_CAP) * k;
  const words = label ? wrapBalanced(label.split(" "), 420 * k, (s) => antonEm(s) * lsize, 2) : [];
  const size = sizeFor(88, t, figEm(spec), 440 * k);
  const bw = Math.max(480 * k, figEm(spec) * size + 110 * k, ...words.map((l) => antonEm(l) * lsize + 110 * k));
  const bh = Math.max(300 * k, 96 * k + size * ANTON_CAP + (words.length ? 26 * k + words.length * lcap * k * 1.12 : 0));
  const left = W * 0.12;
  const top = H * 0.44 - bh / 2;
  const anchor = anchorOf(overlay);
  let leader: React.ReactNode = null;
  if (anchor) {
    const ax = anchor.x * W;
    const ay = anchor.y * H;
    const fromRight = ax > left + bw / 2;
    leader = <Leader t={t} sx={fromRight ? left + bw : left} sy={top + bh / 2} ax={ax} ay={ay} at={12} color={acc} out={out} />;
  }
  return (
    <AbsoluteFill>
      {sound}
      <BlurDefs id={blurId} k={k} />
      {leader}
      <div style={{ position: "absolute", left, top, transform: `scale(${(0.96 + 0.04 * prog(t.f, 0, 12) - 0.03 * (1 - out)).toFixed(4)})`,
        transformOrigin: "50% 50%" }}>
        <GlassBox w={bw} h={bh} t={t} at={0} edge={acc} out={out}>
          <Figure s={spec} size={size} t={t} roll={roll} blurId={blurId} enter={5} signColor={acc} />
          {words.map((l, i) => (
            <div key={i} style={{ marginTop: i ? lsize * 0.06 : 24 * k }}>
              <Glyphs text={l} size={lsize} t={t} enter={land - 8 + i * 3} stagger={0.4} exitFrom={i * 3} />
            </div>
          ))}
        </GlassBox>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== nx-callout-pair
const CalloutPairDraw: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const t = useClock();
  const blurId = useSvgId("nxcp");
  const acc = readable(accent);
  const { k, width: W, height: H } = t;
  const full = Boolean(overlay.fullFrame);
  const sides = sidesOf(overlay);
  const specs = sides.map((s) => specOf(s.drawn));
  const rolls = [rollOf(specs[0].fig, 6, 16), rollOf(specs[1].fig, 24, 16)];
  const lands = rolls.map(landOf);
  const sound = useRollSound(rolls);
  const out = outOf(t, 9);
  const bw = Math.min(540 * k, W * 0.3);
  const size = Math.min(...specs.map((s) => sizeFor(full ? 92 : 84, t, figEm(s), bw - 80 * k)));
  const bh = Math.max(300 * k, 120 * k + 40 * k + size * ANTON_CAP);
  const cy = H * 0.52;
  const lx = W * 0.27 - bw / 2;
  const rx = W * 0.73 - bw / 2;
  const top = cy - bh / 2;
  const title = clip(trimEnds(digits(str(overlay.text))).toUpperCase(), 56);
  const change = clip(trimEnds(digits(str(overlay.subtitle))).toUpperCase(), 24);
  const cp = prog(t.f, 18, 16, easeInOut);
  const x1 = lx + bw;
  const x2 = rx;
  const ex = lerp(x1 + 6 * k, x2 - 6 * k, cp);
  const box = (i: number, x: number) => (
    <div style={{ position: "absolute", left: x, top }}>
      <GlassBox w={bw} h={bh} t={t} at={i ? 16 : 0} edge={i ? acc : "rgba(255,255,255,.9)"} out={out}>
        {sides[i].label ? (
          <div style={{ marginBottom: 20 * k }}>
            <Caps text={sides[i].label} size={23 * k} t={t} at={i ? 20 : 4} color={i ? acc : SOFT} track={0.2} />
          </div>
        ) : null}
        <Figure s={specs[i]} size={size} t={t} roll={rolls[i]} blurId={blurId} enter={i ? 22 : 4} signColor={i ? acc : WHITE}
          exitFrom={i * 3} />
      </GlassBox>
    </div>
  );
  const sw = Math.max(2, 3.5 * k);
  return (
    <AbsoluteFill>
      {sound}
      <BlurDefs id={blurId} k={k} />
      {!full ? <Vignette o={prog(t.f, 0, 10) * out} centre={0.24} edge={0.52} /> : null}
      {title ? (
        <div style={{ position: "absolute", left: 0, right: 0, top: top - 92 * k, display: "flex", justifyContent: "center" }}>
          <Caps text={title} size={28 * k} t={t} at={2} track={0.22} />
        </div>
      ) : null}
      <svg width={W} height={H} style={{ position: "absolute", inset: 0, overflow: "visible", opacity: out,
        filter: `drop-shadow(0 ${px(1 * k)} ${px(2 * k)} rgba(0,0,0,.7))` }}>
        {cp > 0 ? <line x1={x1 + 6 * k} y1={cy} x2={ex} y2={cy} stroke={acc} strokeWidth={sw} strokeDasharray={`${12 * k} ${8 * k}`}
          strokeLinecap="round" /> : null}
        {cp > 0.9 ? (
          <path d={`M ${x2 - 26 * k} ${cy - 14 * k} L ${x2 - 6 * k} ${cy} L ${x2 - 26 * k} ${cy + 14 * k}`} fill="none" stroke={acc}
            strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" opacity={clamp01((cp - 0.9) / 0.1)} />
        ) : null}
      </svg>
      {box(0, lx)}
      {box(1, rx)}
      {change ? (
        <div style={{ position: "absolute", left: (x1 + x2) / 2 - 200 * k, width: 400 * k, top: cy - 62 * k, display: "flex",
          justifyContent: "center", opacity: prog(t.f, lands[1] - 2, 10) * out }}>
          <div style={{ padding: `${8 * k}px ${16 * k}px`, borderRadius: 4 * k, background: "rgba(8,9,12,.85)", border: `${px(1.5 * k)} solid ${rgba(acc, 0.7)}`,
            fontFamily: SUBLINE, fontWeight: 700, fontSize: 22 * k, letterSpacing: "0.14em", color: acc, whiteSpace: "nowrap", lineHeight: 1 }}>{change}</div>
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== nx-number-line
const NumberLineDraw: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const t = useClock();
  const blurId = useSvgId("nxnl");
  const acc = readable(accent);
  const { k, width: W, height: H } = t;
  const full = Boolean(overlay.fullFrame);
  const sides = sidesOf(overlay);
  const specs = sides.map((s) => specOf(s.drawn));
  const rolls = [rollOf(specs[0].fig, 10, 14), rollOf(specs[1].fig, 22, 14)];
  const lands = rolls.map(landOf);
  const sound = useRollSound(rolls);
  const out = outOf(t, 9);
  const a = sides[0].drawn.value;
  const b = sides[1].drawn.value;
  const lo = Math.min(a, b);
  const hi = Math.max(a, b);
  const span = Math.max(hi - lo, Math.abs(hi) * 0.02, 1e-6);
  const d0 = lo - span * 0.8;
  const d1 = hi + span * 0.8;
  const x0 = W * 0.1;
  const x1 = W * 0.9;
  const xOf = (v: number) => lerp(x0, x1, (v - d0) / (d1 - d0));
  const ay = H * 0.62;
  const axis = prog(t.f, 0, 16, easeInOut);
  const size = Math.min(...specs.map((s) => sizeFor(full ? 80 : 74, t, figEm(s), W * 0.3)));
  const stem = 128 * k;
  const title = clip(trimEnds(digits(str(overlay.text))).toUpperCase(), 56);
  const gapText = clip(trimEnds(digits(str(overlay.subtitle))).toUpperCase(), 28);
  const xs = [xOf(a), xOf(b)];
  const pin = (i: number) => {
    const x = xs[i];
    const at = i ? 18 : 6;
    const p = prog(t.f, at, 12, easeOut);
    const leftSide = xs[i] < xs[1 - i];
    const figW = figEm(specs[i]) * size;
    const pop = settle(prog(t.f, at - 2, 8, (q) => q));
    return (
      <React.Fragment key={i}>
        <div style={{ position: "absolute", left: x - Math.max(1, 1.5 * k), top: ay - stem * p, width: Math.max(2, 3 * k), height: stem * p,
          background: i ? acc : WHITE, opacity: out, boxShadow: "0 0 4px rgba(0,0,0,.5)" }} />
        <div style={{ position: "absolute", left: x - 11 * k, top: ay - 11 * k, width: 22 * k, height: 22 * k, borderRadius: "50%",
          background: i ? acc : WHITE, opacity: prog(t.f, at - 2, 6) * out, transform: `scale(${(0.4 + 0.6 * pop).toFixed(3)})`,
          boxShadow: `0 0 0 ${px(6 * k)} ${rgba(i ? acc : "#ffffff", 0.24)}, 0 2px 8px rgba(0,0,0,.5)` }} />
        <div style={{ position: "absolute", top: ay - stem - 18 * k - size - 44 * k, ...(leftSide ? { right: W - x + 6 * k } : { left: x - 6 * k }),
          display: "flex", flexDirection: "column", alignItems: leftSide ? "flex-end" : "flex-start", width: Math.max(figW, 360 * k) }}>
          {sides[i].label ? (
            <div style={{ marginBottom: 14 * k }}>
              <Caps text={sides[i].label} size={23 * k} t={t} at={at + 2} color={i ? acc : SOFT} track={0.18} />
            </div>
          ) : <div style={{ height: 37 * k }} />}
          <Figure s={specs[i]} size={size} t={t} roll={rolls[i]} blurId={blurId} enter={at} signColor={i ? acc : WHITE} exitFrom={i * 3} />
        </div>
      </React.Fragment>
    );
  };
  const bx0 = Math.min(...xs);
  const bx1 = Math.max(...xs);
  const bp = prog(t.f, lands[1] - 2, 12, easeInOut);
  const by = ay + 40 * k;
  return (
    <AbsoluteFill>
      {sound}
      <BlurDefs id={blurId} k={k} />
      {!full ? <Vignette o={prog(t.f, 0, 10) * out} centre={0.34} edge={0.6} at="50% 55%" /> : null}
      {title ? (
        <div style={{ position: "absolute", left: x0, top: H * 0.14 }}>
          <Caps text={title} size={28 * k} t={t} at={2} track={0.2} />
        </div>
      ) : null}
      <svg width={W} height={H} style={{ position: "absolute", inset: 0, overflow: "visible", opacity: out, filter: shadow(k, true) }}>
        <line x1={x0} y1={ay} x2={lerp(x0, x1, axis)} y2={ay} stroke="rgba(255,255,255,.8)" strokeWidth={Math.max(2, 2.5 * k)} />
        {Array.from({ length: 41 }, (_, i) => {
          const x = lerp(x0, x1, i / 40);
          return <line key={i} x1={x} y1={ay} x2={x} y2={ay + (i % 10 === 0 ? 18 : 9) * k} stroke="rgba(255,255,255,.55)"
            strokeWidth={Math.max(1, 1.6 * k)} opacity={clamp01(axis * 41 - i)} />;
        })}
        {bp > 0 ? (
          <path d={`M ${bx0} ${by - 12 * k} L ${bx0} ${by} L ${lerp(bx0, bx1, bp)} ${by}${bp >= 1 ? ` L ${bx1} ${by - 12 * k}` : ""}`}
            fill="none" stroke={acc} strokeWidth={Math.max(2, 3 * k)} strokeLinejoin="round" />
        ) : null}
      </svg>
      {pin(0)}
      {pin(1)}
      {gapText ? (
        <div style={{ position: "absolute", left: (bx0 + bx1) / 2 - 320 * k, width: 640 * k, top: by + 18 * k, display: "flex",
          justifyContent: "center" }}>
          <Caps text={gapText} size={25 * k} t={t} at={lands[1] + 4} color={acc} track={0.16} />
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== nx-record-floor
const RecordFloorDraw: React.FC<{ overlay: Overlay; accent: string; f: Fig }> = ({ overlay, accent, f }) => {
  const t = useClock();
  const blurId = useSvgId("nxrf");
  const acc = readable(accent);
  const { k } = t;
  const d = drawnOf(f);
  const spec = specOf(d);
  // The record as said (label: "LOWEST SINCE THE DAM WAS FILLED"), what the figure is (text).
  const record = clip(trimEnds(digits(str(overlay.label))).toUpperCase(), 44);
  const what = clip(trimEnds(f.label || trimEnds(digits(str(overlay.subtitle))).toUpperCase()), 40);
  const said = `${record} ${f.words.toUpperCase()}`;
  const low = LOW_RX.test(said) || !HIGH_RX.test(said);
  const roll = rollOf(d.fig, 6, 20);
  const land = landOf(roll);
  const sound = useRollSound([roll]);
  const size = sizeFor(96, t, figEm(spec), 0.42 * t.width);
  const cap = size * ANTON_CAP;
  const recPx = 23 * k;
  const arrowW = 34 * k;
  const figW = figEm(spec) * size + arrowW + 22 * k;
  const lineW = Math.max(720 * k, figW + 240 * k, subEm(record, 0.18) * recPx + 80 * k);
  const out = outOf(t, 9);
  const draw = prog(t.f, 2, 14, easeInOut);
  // The figure breaks through the line: from behind it (hidden) to its side, 8 -> land, a settle on the landing.
  const MOVE_AT = 8;
  const mp = clamp01((t.f - MOVE_AT) / (land - MOVE_AT));
  const after = t.f - land;
  const bounce = after > 0 ? 0.06 * Math.sin(after * 0.8) * Math.exp(-after * 0.3) : 0;
  const GAP = 30 * k;
  const travel = cap + GAP + size * ANTON_TOP;
  const shift = (1 - easeOutQuart(mp) + bounce) * travel;        // px still to go toward the line
  // Where the figure breaks the line, the line dips and springs back.
  const crossAt = MOVE_AT + 2;
  const ripple = t.f > crossAt ? Math.exp(-(t.f - crossAt) * 0.2) * Math.sin((t.f - crossAt) * 0.85) : 0;
  const cx = figW / 2;
  const path = (() => {
    const pts: string[] = [];
    for (let i = 0; i <= 60; i++) {
      const x = (lineW * i) / 60;
      const g = Math.exp(-(((x - cx) / (110 * k)) ** 2));
      pts.push(`${i ? "L" : "M"} ${x.toFixed(1)} ${(ripple * g * 12 * k * (low ? 1 : -1)).toFixed(2)}`);
    }
    return pts.join(" ");
  })();
  const phraseH = record ? recPx * 1.9 : 0;
  const whatH = what ? 50 * k : 0;
  // Low: phrase, line, figure, what. High: what, figure, line, phrase.
  const lineY = low ? phraseH + 8 * k : whatH + cap + GAP + size * ANTON_TOP + 8 * k;
  const figTop = low ? lineY + GAP : lineY - GAP - cap - size * ANTON_TOP;
  const blockH = low ? figTop + size + whatH : lineY + 8 * k + phraseH;
  const clipStyle: CSS = low
    ? { position: "absolute", left: -40 * k, right: -40 * k, top: lineY + 2 * k, height: size + GAP + 40 * k, overflow: "hidden" }
    : { position: "absolute", left: -40 * k, right: -40 * k, top: 0, height: lineY - 2 * k, overflow: "hidden" };
  const figInClip = low ? figTop - (lineY + 2 * k) : figTop;
  return (
    <AbsoluteFill>
      {sound}
      <BlurDefs id={blurId} k={k} />
      <CornerShade o={prog(t.f, 0, 10) * out} />
      <Stage t={t} place="lower-left" push={pushOf(t, land)}>
        <div style={{ position: "relative", width: lineW, height: blockH }}>
          <svg width={lineW} height={40 * k} viewBox={`0 ${-20 * k} ${lineW} ${40 * k}`}
            style={{ position: "absolute", left: 0, top: lineY - 20 * k, overflow: "visible", opacity: out, filter: shadow(k, true) }}>
            <defs>
              <clipPath id={`${blurId}-c`}><rect x={0} y={-40 * k} width={lineW * draw} height={80 * k} /></clipPath>
            </defs>
            <path d={path} fill="none" stroke="rgba(255,255,255,.92)" strokeWidth={Math.max(2, 3 * k)}
              strokeDasharray={`${16 * k} ${10 * k}`} clipPath={`url(#${blurId}-c)`} />
          </svg>
          {record ? (
            <div style={{ position: "absolute", left: 0, top: low ? 0 : lineY + 18 * k }}>
              <Caps text={record} size={recPx} t={t} at={5} color={acc} track={0.18} />
            </div>
          ) : null}
          <div style={clipStyle}>
            <div style={{ position: "absolute", left: 40 * k, top: figInClip, display: "flex", alignItems: "flex-start",
              transform: `translateY(${((low ? -1 : 1) * shift).toFixed(2)}px)`, opacity: out }}>
              <svg width={arrowW} height={cap} viewBox="0 0 30 60" preserveAspectRatio="xMidYMid meet"
                style={{ marginRight: 22 * k, marginTop: size * ANTON_TOP, overflow: "visible", filter: shadow(k, true),
                  transform: low ? undefined : "scaleY(-1)" }}>
                <path d="M15 4 L15 52 M3 39 L15 54 L27 39" fill="none" stroke={acc} strokeWidth={5.5} strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <Figure s={spec} size={size} t={t} roll={roll} blurId={blurId} enter={-20} signColor={acc} />
            </div>
          </div>
          {what ? (
            <div style={{ position: "absolute", left: arrowW + 22 * k, top: low ? figTop + size + 16 * k : 0 }}>
              <Caps text={what} size={24 * k} t={t} at={land - 4} />
            </div>
          ) : null}
        </div>
      </Stage>
    </AbsoluteFill>
  );
};

// ================================================================== nx-rate-fraction
const RATE_RX = /\b(PER|A|AN|EACH|EVERY)\s+(PERSON|PEOPLE|RESIDENT|HOUSEHOLD|HOME|HOUSE|FAMILY|CAPITA|YEAR|DAY|MONTH|WEEK|HOUR|MINUTE|SECOND|ACRE|SQUARE MILE|MILE|FARM|CUSTOMER)\b/;
const rateOf = (ov: Overlay, f: Fig): string => {
  const said = trimEnds(digits(str(ov.label))).toUpperCase();
  if (said && !/^(UP|DOWN)$/.test(said)) return said;
  const m = RATE_RX.exec(f.words.toUpperCase());
  return m ? `${m[1]} ${m[2]}` : "";
};
type IconKind = "person" | "home" | "calendar" | "clock" | "field";
const iconOf = (rate: string): IconKind => (/PERSON|PEOPLE|RESIDENT|CAPITA|CUSTOMER/.test(rate) ? "person"
  : /HOUSEHOLD|HOME|HOUSE|FAMILY/.test(rate) ? "home" : /HOUR|MINUTE|SECOND/.test(rate) ? "clock"
    : /ACRE|MILE|FARM/.test(rate) ? "field" : "calendar");
/** A small line icon for what the rate is per, drawn on with its stroke. */
const RateIcon: React.FC<{ kind: IconKind; size: number; p: number; color: string }> = ({ kind, size, p, color }) => {
  const len = 160;
  const common = { fill: "none", stroke: color, strokeWidth: 2.6, strokeLinecap: "round" as const, strokeLinejoin: "round" as const,
    strokeDasharray: `${len}`, strokeDashoffset: `${(len * (1 - p)).toFixed(2)}` };
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" style={{ display: "block", overflow: "visible" }}>
      {kind === "person" ? (<><circle cx={16} cy={9} r={5.2} {...common} /><path d="M6 29 C6 20 10 16.5 16 16.5 C22 16.5 26 20 26 29" {...common} /></>)
        : kind === "home" ? (<><path d="M4 15 L16 5 L28 15" {...common} /><path d="M8 13 L8 28 L24 28 L24 13" {...common} /><path d="M14 28 L14 20 L18 20 L18 28" {...common} /></>)
          : kind === "clock" ? (<><circle cx={16} cy={16} r={12} {...common} /><path d="M16 9 L16 16 L21 19" {...common} /></>)
            : kind === "field" ? (<><path d="M3 26 L29 26 M6 26 L11 12 M13 26 L16 10 M19 26 L21 12 M25 26 L26 14" {...common} /></>)
              : (<><rect x={4} y={7} width={24} height={21} rx={2.5} {...common} /><path d="M4 13 L28 13 M10 4 L10 9 M22 4 L22 9" {...common} /></>)}
    </svg>
  );
};
const RateFractionDraw: React.FC<{ overlay: Overlay; accent: string; f: Fig }> = ({ overlay, accent, f }) => {
  const t = useClock();
  const blurId = useSvgId("nxrt");
  const acc = readable(accent);
  const { k } = t;
  const d = drawnOf(f);
  const spec = specOf(d);
  const rate = clip(rateOf(overlay, f), 24);
  const roll = rollOf(d.fig, 3, 22);
  const land = landOf(roll);
  const sound = useRollSound([roll]);
  const size = sizeFor(92, t, figEm(spec), 0.44 * t.width);
  const rsize = (46 / ANTON_CAP) * k;
  const iconS = rsize * ANTON_CAP * 1.18;
  const numW = figEm(spec) * size;
  const denW = rate ? antonEm(rate) * rsize + iconS + 18 * k : 0;
  const barW = Math.max(numW, denW) + 28 * k;
  // What it counts: the words as said, minus the rate.
  const rest = trimEnds((f.label || "").replace(RATE_RX, " ").replace(/\s+/g, " "));
  const what = clip(rest || f.extra, 44);
  const out = outOf(t, 9);
  const bar = prog(t.f, 8, 12, easeInOut);
  const dp = prog(t.f, 12, 10);
  const ip = prog(t.f, 14, 16, easeInOut);
  return (
    <AbsoluteFill>
      {sound}
      <BlurDefs id={blurId} k={k} />
      <CornerShade o={prog(t.f, 0, 10) * out} />
      <Stage t={t} place="lower-left" push={pushOf(t, land)}>
        <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
          <Figure s={spec} size={size} t={t} roll={roll} blurId={blurId} signColor={acc} />
          <div style={{ width: barW, height: Math.max(2, 4 * k), margin: `${size * 0.1}px 0 ${size * 0.14}px`, background: WHITE, borderRadius: 2 * k,
            transform: `scaleX(${(bar * out).toFixed(4)})`, transformOrigin: "0% 50%", boxShadow: "0 1px 4px rgba(0,0,0,.5)" }} />
          {rate ? (
            <div style={{ display: "flex", alignItems: "center" }}>
              <div style={{ marginRight: 18 * k, opacity: dp * out, transform: `translateY(${((1 - dp) * 8 * k).toFixed(2)}px)`, filter: shadow(k, true) }}>
                <RateIcon kind={iconOf(rate)} size={iconS} p={ip} color={acc} />
              </div>
              <Glyphs text={rate} size={rsize} t={t} enter={12} stagger={0.4} color={acc} />
            </div>
          ) : null}
          {what ? <div style={{ marginTop: 20 * k }}><Caps text={what} size={23 * k} t={t} at={land - 6} color={SOFT} /></div> : null}
        </div>
      </Stage>
    </AbsoluteFill>
  );
};

// ================================================================== nx-rank-rows
type Row = { label: string; value: number; drawn: Drawn };
const rowsOf = (ov: Overlay): Row[] => {
  const items = Array.isArray(ov.items) ? ov.items : [];
  const out: Row[] = [];
  for (const it of items) {
    if (!it || typeof it !== "object") continue;
    const x = it as { label?: unknown; value?: unknown; text?: unknown };
    const v = numOf(x.value);
    if (v === null) continue;
    const f = figureOf({ value: v, prefix: str(ov.prefix), suffix: str(ov.suffix) });
    out.push({ label: clip(trimEnds(digits(str(x.label) || str(x.text))).toUpperCase(), 26), value: v, drawn: drawnOf(f) });
    if (out.length >= 5) break;
  }
  return out.sort((a, b) => b.value - a.value);
};
const RankRowsDraw: React.FC<{ overlay: Overlay; accent: string; rows: Row[] }> = ({ overlay, accent, rows }) => {
  const t = useClock();
  const blurId = useSvgId("nxrr");
  const acc = readable(accent);
  const { k, width: W } = t;
  const full = Boolean(overlay.fullFrame);
  const STEP = 5;
  const rolls = rows.map((r, i) => rollOf(r.drawn.fig, 8 + i * STEP, 18));
  const lands = rolls.map(landOf);
  const sound = useRollSound(rolls);
  const out = outOf(t, 9);
  const max = Math.max(...rows.map((r) => Math.abs(r.value)), 1e-9);
  const BW = Math.min(1320 * k, W - 2 * safeOf(t) - 80 * k);
  const rowH = (rows.length > 4 ? 108 : 124) * k;
  const vsize = (52 / ANTON_CAP) * k;
  const title = clip(trimEnds(digits(str(overlay.text))).toUpperCase(), 52);
  const row = (r: Row, i: number) => {
    const at = 3 + i * STEP;
    const e = prog(t.f, at, 12, easeOut);
    const grow = easeOutQuart(clamp01((t.f - (at + 5)) / 18));
    const frac = Math.abs(r.value) / max;
    return (
      <div key={i} style={{ position: "relative", height: rowH, display: "flex", alignItems: "center",
        opacity: e * out, transform: `translateX(${((1 - e) * -44 * k).toFixed(2)}px)` }}>
        <div style={{ width: 104 * k, flex: "none", fontFamily: ANTON, fontSize: (56 / ANTON_CAP) * k, lineHeight: 1, color: i === 0 ? acc : WHITE,
          opacity: i === 0 ? 1 : 0.8, filter: shadow(k) }}>{i + 1}</div>
        <div style={{ position: "relative", flex: 1, height: rowH * 0.8, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
            <div style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: 31 * k, letterSpacing: "0.1em", color: WHITE,
              whiteSpace: "nowrap", filter: shadow(k, true), lineHeight: 1, paddingBottom: 6 * k }}>{r.label}</div>
            <Figure s={specOf(r.drawn)} size={vsize} t={t} roll={rolls[i]} blurId={blurId} enter={at + 3} exitFrom={i}
              signColor={i === 0 ? acc : WHITE} />
          </div>
          <div style={{ position: "relative", height: 10 * k, borderRadius: 5 * k, background: "rgba(255,255,255,.13)" }}>
            <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${(frac * grow * 100).toFixed(3)}%`, borderRadius: 5 * k,
              background: i === 0 ? `linear-gradient(90deg, ${mix(acc, "#000000", 0.25)}, ${acc})` : "linear-gradient(90deg, rgba(255,255,255,.4), rgba(255,255,255,.82))",
              boxShadow: i === 0 ? `0 0 ${px(16 * k)} ${rgba(acc, 0.5)}` : undefined }} />
          </div>
        </div>
      </div>
    );
  };
  return (
    <AbsoluteFill>
      {sound}
      <BlurDefs id={blurId} k={k} />
      {!full ? <Vignette o={prog(t.f, 0, 10) * out} centre={0.46} edge={0.66} /> : null}
      <Stage t={t} place="center">
        <div style={{ width: BW, display: "flex", flexDirection: "column" }}>
          {title ? <div style={{ marginBottom: 30 * k, marginLeft: 104 * k }}><Caps text={title} size={26 * k} t={t} at={1} track={0.2} color={SOFT} /></div> : null}
          {rows.map(row)}
        </div>
      </Stage>
    </AbsoluteFill>
  );
};
const RankRows: Look = ({ overlay, accent }) => {
  const rows = rowsOf(overlay);
  return rows.length < 2 ? <StatContext overlay={overlay} accent={accent} /> : <RankRowsDraw overlay={overlay} accent={accent} rows={rows} />;
};

// ================================================================== nx-inline-count
type Tok = { t: string; fig: boolean };
const SCALE_WORD = /^(MILLION|BILLION|THOUSAND|TRILLION)$/;
const InlineCountDraw: React.FC<{ overlay: Overlay; accent: string; f: Fig }> = ({ overlay, accent, f }) => {
  const t = useClock();
  const blurId = useSvgId("nxic");
  const acc = readable(accent);
  const { k } = t;
  const d = drawnOf(f);
  // The sentence as said (highlight, else text); the figure found in it, else set in front of it.
  const sentence = clip(trimEnds(digits(str(overlay.highlight) || str(overlay.text))), 84).toUpperCase();
  const span = figureSpan(sentence, d, f.value);
  let before = sentence;
  let after = "";
  if (span) {
    before = sentence.slice(0, span[0]);
    after = sentence.slice(span[1]);
    // The sign or scale said right after the figure belongs to it ("25 MILLION", "22%").
    const m = /^(\s?%|\s(?:MILLION|BILLION|THOUSAND|TRILLION)\b)/.exec(after);
    if (m) after = after.slice(m[0].length);
  }
  const scale = d.tag.split(" ")[0] || "";
  const figText = `${d.pre}${d.fig}${d.top}${span ? (SCALE_WORD.test(scale) ? ` ${scale}` : "") : d.tag ? ` ${d.tag}` : ""}`;
  const toks: Tok[] = [
    ...trimEnds(before).split(" ").filter(Boolean).map((w) => ({ t: w, fig: false })),
    { t: figText, fig: true },
    ...trimEnds(after).split(" ").filter(Boolean).map((w) => ({ t: w, fig: false })),
  ];
  const maxW = Math.min(0.52 * t.width, 1000 * t.kw);
  const sz = (c: number) => (c / ANTON_CAP) * k;
  const lineEm = (ws: Tok[]) => ws.reduce((a, w, i) => a + antonEm(w.t) + (i ? 0.234 : 0), 0);
  const fit = (() => {
    const CAP0 = 56;
    if (maxW / Math.max(0.3, lineEm(toks)) >= sz(CAP0)) return { lines: [toks], size: sz(CAP0) };
    let best: Tok[][] = [toks];
    let score = Infinity;
    for (let i = 1; i < toks.length; i++) {
      const s = Math.max(lineEm(toks.slice(0, i)), lineEm(toks.slice(i)));
      if (s < score) {
        score = s;
        best = [toks.slice(0, i), toks.slice(i)];
      }
    }
    return { lines: best, size: Math.max(sz(36), Math.min(sz(CAP0), maxW / Math.max(0.3, score))) };
  })();
  const size = fit.size;
  const STEP = 1.5;
  const figIndex = toks.findIndex((x) => x.fig);
  const C0 = 3 + figIndex * STEP;
  const roll = rollOf(figText, C0, 20);
  const land = landOf(roll);
  const sound = useRollSound([roll]);
  const out = outOf(t, 9);
  let idx = 0;
  const glow = prog(t.f, land - 1, 6) * (1 - prog(t.f, land + 8, 16));
  return (
    <AbsoluteFill>
      {sound}
      <BlurDefs id={blurId} k={k} />
      <CornerShade o={prog(t.f, 0, 10) * out} />
      <Stage t={t} place="lower-left" push={pushOf(t, land)}>
        <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
          {fit.lines.map((ws, li) => (
            <div key={li} style={{ display: "flex", alignItems: "flex-start", marginTop: li ? size * 0.12 : 0 }}>
              {ws.map((w, wi) => {
                const i = idx++;
                const enter = 3 + i * STEP;
                return (
                  <div key={wi} style={{ marginRight: wi < ws.length - 1 ? `${0.234 * size}px` : 0,
                    filter: w.fig && glow > 0.01 ? `drop-shadow(0 0 ${px(16 * k * glow)} ${rgba(acc, 0.65 * glow)})` : undefined }}>
                    <Glyphs text={w.t} size={size} t={t} enter={enter} exitFrom={i} color={w.fig ? acc : WHITE} stagger={w.fig ? 0.3 : 0.25}
                      pos={w.fig ? (j) => {
                        const c = roll.cols.indexOf(j);
                        return c >= 0 ? posAt(roll, c, t.f) : null;
                      } : undefined}
                      blur={w.fig ? (j) => {
                        const c = roll.cols.indexOf(j);
                        return c >= 0 ? blurRef(blurId, speedAt(roll, c, t.f)) : undefined;
                      } : undefined} />
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </Stage>
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ the looks
const StatContext = withFigure(StatContextDraw);
const CalloutBox = withFigure(CalloutBoxDraw);

/** What a look draws for an overlay's figure ("22%", "$4.2 BILLION", "3,517 FT"), digits and the unit as said. */
export const drawnFigure = (ov: Overlay, money = false): string => {
  const f = figureOf(ov, money);
  if (f.value === null) return "";
  const d = drawnOf(f, money);
  return `${d.pre}${d.fig}${d.top}${d.tag ? ` ${d.tag}` : ""}`;
};

export const LOOKS: Record<string, Look> = {
  "nx-stat-context": StatContext,
  "nx-frame-share": withFigure(FrameShareDraw),
  "nx-ring-label": withFigure(RingLabelDraw),
  "nx-delta-arrow": DeltaArrow,
  "nx-money-roll": withFigure(MoneyRollDraw, true),
  "nx-dimension": withFigure(DimensionDraw),
  "nx-callout-box": CalloutBox,
  "nx-callout-pair": ({ overlay, accent }) => (sidesOf(overlay).length < 2
    ? <CalloutBox overlay={overlay} accent={accent} /> : <CalloutPairDraw overlay={overlay} accent={accent} />),
  "nx-number-line": ({ overlay, accent }) => (sidesOf(overlay).length < 2
    ? <StatContext overlay={overlay} accent={accent} /> : <NumberLineDraw overlay={overlay} accent={accent} />),
  "nx-record-floor": withFigure(RecordFloorDraw),
  "nx-rate-fraction": withFigure(RateFractionDraw),
  "nx-rank-rows": RankRows,
  "nx-inline-count": withFigure(InlineCountDraw),
};
