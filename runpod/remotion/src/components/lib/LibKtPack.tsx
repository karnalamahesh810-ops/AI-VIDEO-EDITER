import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import type { Overlay } from "../../types";
import { GROTESK, GROTESK_CAP, INTER, SERIF, SUBLINE } from "../fonts";
import { backOut, clamp01, cubicIn, cubicInOut, cubicOut, expoOut, idle, lerp, prog, sineInOut } from "../motion/ease";
import { guard, hash, rgba, rnd, type Look } from "./proKit";
import { countText, figureOf, num, rowsOf, seriesScale, str, unitsOf } from "./proFormat";
import { Glint, KineticLine, SOFT_WHITE, WHITE, blockAt, fitLines, isRight, settle, softShadow, widthOf, zoneFor,
  type Zone } from "./typeKit";
import { Backing, useLook } from "./LibKinetic";
import { Caps, DIM, Glass, RiseLine, capsWidth, riseWidth } from "./LibKtDates";
import { baselineIn, placeRect, rect, type Rect } from "./annoKit";
import { anchorFrom } from "./LibVideoMarks";
import { useLookSound } from "./LookSounds";
import scale from "./typeScale.json";

/**
 * THE LOOK PACK (2026-10-07, the owner: "build more interesting animations and
 * overlays - best quality ones, Premiere Pro / After Effects kind, perfect
 * size"). The words and the data of the pack, in the kinetic-type system
 * (typeKit.tsx: white bold grotesk, ONE accent following the brand kit, soft
 * shades and frosted glass instead of outlines or yellow fills, sizes from
 * typeScale.json, the same-place rule with the planner's calm side):
 *
 *   kt-quote       PULL QUOTE   a quote said by a named speaker: a serif quote mark in the accent, the words
 *                               coming into focus, the key phrase underlined as it lands, the speaker beneath
 *   kt-term        TERM CARD    a word the narration defines ("what's called dead pool, the level where..."):
 *                               a glass card, the term rising letter by letter, its one-line meaning under it
 *   kt-level       LEVEL GAUGE  "27 percent full": a glass gauge that fills with water to the level, the surface
 *                               moving gently, a marker riding up beside it while the share counts
 *   kt-trend       TREND LINE   three or more years with their figures: a glass card whose line draws in left to
 *                               right, a dot riding its head with the value counting, the peak and the low marked
 *   kt-milestones  MILESTONES   three to five years said one after another: a strip of points that light as each
 *                               year is said, the line running on to the next
 *   kt-pointer     ARROW        a thing the line points at on the footage (vision found it): a ring draws round
 *                               it, an arrow draws to it from a glass label on the calm side
 *   kt-chapter     CHAPTER      a section opens: the footage softens, one soft light leak crosses, the chapter's
 *                               number and title come up low left - a short designed moment, never a takeover
 *
 * Every look: an eased entry of 12-24 frames, a gentle idle, every element
 * leaving in the last 12 frames (the mirrored exit) - nothing pops, nothing
 * ends early (the registry's leastSeconds, src/datalooks.py). Only the
 * planner's words are set; a look that cannot set them whole draws nothing.
 */

// ------------------------------------------------------------------ shared
/** The size unit: the frame height, or the width's 16:9 height on a tall frame. */
const unitOf = (W: number, H: number) => Math.min(H, (W * 9) / 16);
/** Font px whose capitals stand `share` of the unit (fontScale applied). */
const capFont = (share: number, U: number, ks: number, cap = GROTESK_CAP) => (share * U * ks) / cap;
type PackKey = "quote" | "term" | "termDef" | "packKicker" | "levelNumber" | "trendValue" | "trendAxis" | "mileYear"
  | "mileLabel" | "pointerLabel" | "chapterTitle" | "chapterNumber";
const share = (key: PackKey) => (scale.pack[key] as { share: number }).share;

const normWord = (w: string) => w.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");

/** Where `phrase` sits on laid-out lines: per line, [x0, x1] in px from the line's start (empty when it is not there). */
const spansOf = (lines: string[], phrase: string, font: string, size: number, weight: number, tracking: number) => {
  const want = phrase.split(/\s+/).map(normWord).filter(Boolean);
  if (!want.length) return [] as { line: number; x0: number; x1: number }[];
  const flat: { line: number; idx: number; w: string }[] = [];
  lines.forEach((ln, li) => ln.split(/\s+/).filter(Boolean).forEach((w, wi) => flat.push({ line: li, idx: wi, w: normWord(w) })));
  let at = -1;
  for (let i = 0; i + want.length <= flat.length && at < 0; i++) {
    if (want.every((w, j) => flat[i + j].w === w)) at = i;
  }
  if (at < 0) return [];
  const out: { line: number; x0: number; x1: number }[] = [];
  for (let j = 0; j < want.length; j++) {
    const { line, idx } = flat[at + j];
    const ws = lines[line].split(/\s+/).filter(Boolean);
    const before = ws.slice(0, idx).join(" ");
    const x0 = before ? widthOf(`${before} `, font, size, weight, tracking) : 0;
    const x1 = widthOf(ws.slice(0, idx + 1).join(" "), font, size, weight, tracking);
    const cur = out.find((o) => o.line === line);
    if (cur) cur.x1 = Math.max(cur.x1, x1);
    else out.push({ line, x0, x1 });
  }
  return out;
};

/** A drawn stroke `p` 0..1 of its length (round caps, a soft shadow so it holds on any picture). */
const Draw: React.FC<{ d: string; p: number; color: string; width: number; shadow?: number; opacity?: number }> =
  ({ d, p, color, width, shadow = 0.5, opacity = 1 }) => (p <= 0.001 ? null : (
    <path d={d} pathLength={1} fill="none" stroke={color} strokeWidth={width} strokeLinecap="round" strokeLinejoin="round"
      strokeDasharray="1 1" strokeDashoffset={1 - clamp01(p)} opacity={opacity}
      style={shadow > 0 ? { filter: `drop-shadow(0 ${(width * 0.35).toFixed(2)}px ${(width * 1.1).toFixed(2)}px rgba(0,0,0,${shadow}))` }
        : undefined} />
  ));

/** A hand-feel underline under x0..x1 at y: a slight sag, the end lifting (deterministic for a seed). */
const underline = (x0: number, x1: number, y: number, seed: number, k: number) => {
  const sag = (2.5 + rnd(seed) * 2.5) * k;
  const lift0 = (rnd(seed + 1) * 3 - 1.5) * k;
  return `M${x0.toFixed(1)},${(y + lift0).toFixed(1)} Q${((x0 + x1) / 2).toFixed(1)},${(y + sag).toFixed(1)} `
    + `${x1.toFixed(1)},${(y - 1.5 * k).toFixed(1)}`;
};

// ================================================================== kt-quote
/**
 * The quote low left (the calm side; a slim panel over busy footage), up to three
 * lines at the statement size: a serif quote mark in the accent opens it (frames
 * 2-18), the lines come into focus word by word (from frame 6, every word in by
 * frame ~22 however long the quote), the key phrase underlines itself in the
 * accent (frames 30-46, the marker sound), then the speaker: an accent bar, the
 * name in tracked capitals, the role under it (frames 36-50). It leaves line by
 * line, the underline drawing back, in the last 12 frames.
 */
const Quote: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, dir, hot, out, ks, panel } = useLook(overlay, accent);
  const raw = str(overlay.text).replace(/^[\s"'“”‘’«»]+|[\s"'“”‘’«»]+$/g, "");
  if (!raw) return null;
  const speaker = str(overlay.label);
  const role = str(overlay.subtitle);
  const U = unitOf(W, H);
  const weight = 600;
  const track = -0.01;
  const size = capFont(share("quote"), U, ks);
  const least = capFont(scale.statement.least, U, ks);
  const maxW = (panel ? 0.38 : 0.44) * W;
  const fit = fitLines(raw, GROTESK, weight, size, least, maxW, 3, track);
  if (!fit) return null;
  const lineBox = fit.size * 1.04;
  const lh = fit.size * 1.24;
  const mark = fit.size * 2.2;
  const markRow = mark * 0.44;
  const nameSize = capFont(share("packKicker"), U, ks) * 1.12;
  const roleSize = capFont(scale.role.share, U, ks) * 0.92;
  const roleFit = role ? fitLines(role, INTER, 500, roleSize, roleSize * 0.85, maxW, 1) : null;
  const barW = 34 * k;
  const attrW = speaker ? barW + 14 * k + Math.max(capsWidth(speaker, nameSize, 0.14), roleFit ? roleFit.width : 0) : 0;
  const attrH = speaker ? nameSize + (roleFit ? roleFit.size * 1.5 + 8 * k : 0) : 0;
  const attrGap = speaker ? 0.62 * fit.size : 0;
  const w = Math.max(fit.width, attrW);
  const h = markRow + fit.lines.length * lh + attrGap + attrH;
  const zone = zoneFor(overlay, panel ? "left-panel" : "lower-left", w, h, W, H);
  const r = blockAt(zone, w, h, W, H);
  const anchorRight = isRight(zone);
  // every word in by frame ~22, however many there are
  const nWords = fit.lines.join(" ").split(/\s+/).filter(Boolean).length;
  const gap = Math.max(0.8, Math.min(3, 14 / Math.max(1, nWords - 1)));
  let wordAt = 0;
  const starts = fit.lines.map((ln) => {
    const s = 6 + wordAt * gap;
    wordAt += ln.split(/\s+/).filter(Boolean).length;
    return s;
  });
  // the key phrase: the planner's highlight when it is in the quote, else none
  const hl = str(overlay.highlight);
  const spans = hl ? spansOf(fit.lines, hl, GROTESK, fit.size, weight, track) : [];
  const base = baselineIn(GROTESK, weight, fit.size, lineBox);
  const U0 = 30;
  const draw = prog(f, U0, 16, S, cubicInOut) * (1 - cubicIn(clamp01(out * 1.3)));
  const glyphIn = prog(f, 2, 16, S, (u) => backOut(u, 1.3));
  const glyphO = prog(f, 2, 10, S, cubicOut) * (1 - clamp01(out * 1.4));
  const drift = idle(f, 40 * S, dur) * 5 * k;
  const seed = hash(raw);
  return (
    <AbsoluteFill>
      <Backing panel={panel} dir={dir} rect={r} right={anchorRight} p={prog(f, 0, 14, S, cubicOut)} out={out} />
      <div style={{ position: "absolute", left: r.x, top: r.y - drift, width: r.w, height: r.h }}>
        {/* the quote mark: a serif mark in the accent, hanging over the first line */}
        <div style={{ position: "absolute", left: -0.04 * mark, top: -0.16 * mark, fontFamily: SERIF, fontWeight: 700, fontSize: mark,
          lineHeight: 1, color: hot, opacity: glyphO, textShadow: softShadow(k, 0.35),
          transform: `translateY(${((1 - glyphIn) * 0.12 * mark).toFixed(2)}px) scale(${(0.72 + 0.28 * glyphIn).toFixed(4)})`,
          transformOrigin: "20% 60%" }}>“</div>
        {fit.lines.map((ln, i) => (
          <div key={i} style={{ position: "absolute", left: 0, top: markRow + i * lh, width: r.w }}>
            <KineticLine text={ln} font={GROTESK} weight={weight} size={fit.size} tracking={track} color={WHITE}
              preset="focus" timing={{ at: starts[i], gap, len: 14 }} out={out} shadow={softShadow(k, 0.6)} />
          </div>
        ))}
        <svg width={r.w} height={r.h} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          {spans.map((sp, i) => {
            const y = markRow + sp.line * lh + base + 0.16 * fit.size;
            const part = clamp01(draw * spans.length - i);
            return <Draw key={i} d={underline(sp.x0 - 3 * k, sp.x1 + 3 * k, y, seed + i, k)} p={part} color={hot}
              width={Math.max(3, 5 * k)} shadow={0.45} />;
          })}
        </svg>
        {speaker ? (
          <div style={{ position: "absolute", left: 0, top: markRow + fit.lines.length * lh + attrGap, display: "flex",
            alignItems: "flex-start", gap: 14 * k }}>
            <div style={{ width: barW, height: Math.max(2, 3 * k), marginTop: nameSize * 0.42, background: hot, borderRadius: 2 * k,
              transformOrigin: "left", transform: `scaleX(${(prog(f, 34, 14, S, expoOut) * (1 - clamp01(out * 1.4))).toFixed(4)})`,
              boxShadow: `0 0 ${(10 * k).toFixed(1)}px ${rgba(hot, 0.45)}` }} />
            <div>
              <div style={{ height: nameSize }}>
                <Caps text={speaker} size={nameSize} color={WHITE} at={36} out={out} k={k} tracking={0.14} />
              </div>
              {roleFit ? (
                <div style={{ marginTop: 8 * k }}>
                  <KineticLine text={roleFit.lines[0]} font={INTER} weight={500} size={roleFit.size} color={SOFT_WHITE}
                    preset="focus" timing={{ at: 42, gap: 2 }} out={out} shadow={softShadow(k, 0.55)} />
                </div>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== kt-term
/**
 * A frosted glass card low left with the accent edge drawing down its side: a
 * small kicker ("DEFINITION", or the planner's), the term in the bold grotesk
 * rising letter by letter (frames 8-24), a hairline drawing across (18-32), and
 * the term's meaning as the narration says it - one or two lines coming into
 * focus (from 22). The card closes back into its edge in the last 12 frames.
 */
const Term: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dir, hot, out, ks } = useLook(overlay, accent);
  const term = str(overlay.text);
  if (!term) return null;
  const meaning = str(overlay.subtitle);
  const kicker = (str(overlay.label) || "Definition").toUpperCase();
  const U = unitOf(W, H);
  const tSize0 = capFont(share("term"), U, ks, dir.cap);
  const dSize = capFont(share("termDef"), U, ks);
  const kSize = capFont(share("packKicker"), U, ks);
  const edgeW = 6 * k;
  const padL = edgeW + 0.42 * tSize0, padR = 0.5 * tSize0, padT = 0.34 * tSize0, padB = 0.36 * tSize0;
  const maxInner = 0.4 * W - padL - padR;
  let tSize = tSize0;
  while (tSize > tSize0 * 0.72 && riseWidth(term, GROTESK, tSize, 800) > maxInner) tSize *= 0.96;
  if (riseWidth(term, GROTESK, tSize, 800) > maxInner) return null;
  const termW = riseWidth(term, GROTESK, tSize, 800);
  const def = meaning ? fitLines(meaning, INTER, 500, dSize, dSize * 0.84, Math.max(termW, 0.3 * W), 2) : null;
  const innerW = Math.max(termW, def ? def.width : 0, capsWidth(kicker, kSize), 0.2 * W);
  const termH = tSize * 1.2;
  const head = kSize + 0.26 * tSize;
  const divGap = def ? 0.34 * tSize : 0;
  const defH = def ? def.lines.length * def.size * 1.3 : 0;
  const w = innerW + padL + padR;
  const h = padT + head + termH + divGap * 2 + defH + padB;
  const zone = zoneFor(overlay, "lower-left", w, h, W, H) as Zone;
  const r = blockAt(zone, w, h, W, H);
  const edgeP = prog(f, 0, 12, S, expoOut) * (1 - clamp01(out * 1.5));
  const open = prog(f, 2, 16, S, expoOut);
  const line = prog(f, 18, 14, S, expoOut) * (1 - clamp01(out * 1.5));
  return (
    <AbsoluteFill>
      <Glass x={r.x} y={r.y} w={w} h={h} k={k} p={Math.max(open, edgeP * 0.08)} out={out} radius={12} edge={hot} edgeP={edgeP}>
        <div style={{ position: "absolute", left: padL, right: padR, top: padT }}>
          <div style={{ height: kSize, marginBottom: 0.26 * tSize }}>
            <Caps text={kicker} size={kSize} color={dir.id === "doc" ? "rgba(250,250,247,0.86)" : hot} at={6} out={out} k={k} />
          </div>
          <RiseLine text={term} size={tSize} font={GROTESK} weight={800} at={8} out={out} k={k} gap={1.0} />
          {def ? (
            <>
              <div style={{ height: 1.5 * k, marginTop: divGap, marginBottom: divGap, width: innerW,
                background: "linear-gradient(90deg, rgba(255,255,255,0.34), rgba(255,255,255,0.06))",
                transformOrigin: "left", transform: `scaleX(${line.toFixed(4)})` }} />
              {def.lines.map((ln, i) => (
                <div key={i} style={{ height: def.size * 1.3 }}>
                  <KineticLine text={ln} font={INTER} weight={500} size={def.size} color={SOFT_WHITE} preset="focus"
                    timing={{ at: 22 + i * 4, gap: 1.6 }} out={out} shadow={softShadow(k, 0.4)} />
                </div>
              ))}
            </>
          ) : null}
        </div>
      </Glass>
    </AbsoluteFill>
  );
};

// ================================================================== kt-level
/** The water's surface across the gauge at `level` (px from the top), `amp` px high, moving with phase `ph`. */
const surface = (w: number, level: number, amp: number, ph: number): [number, number][] => {
  const n = 24;
  return Array.from({ length: n + 1 }, (_, i) => {
    const u = i / n;
    return [u * w, level + Math.sin(u * Math.PI * 2 * 1.3 + ph) * amp + Math.sin(u * Math.PI * 2 * 0.6 - ph * 0.7) * amp * 0.45];
  });
};
const ptsD = (pts: [number, number][]) => pts.map((p) => `${p[0].toFixed(2)},${p[1].toFixed(2)}`).join(" L");

/**
 * "27 percent full": a glass gauge low left (26 % of the frame height) whose
 * water rises to the level (frames 12-48, cubic in-out) with its surface moving
 * gently; an accent marker rides up its side; beside it the kicker, the share
 * counting with the water (the hero size of a ring's figure) and one line of
 * context. "FULL" sits at the gauge's top. On landing the surface swells once
 * and one light sweep crosses the figure.
 */
const Level: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, dir, hot, out, ks } = useLook(overlay, accent);
  const value = num(overlay.value);
  if (value === null || value < 0) return null;
  const total = num(overlay.total);
  const sh = clamp01(total && total > 0 ? value / total : value / 100);
  const kicker = str(overlay.label);
  const context = str(overlay.subtitle);
  const U = unitOf(W, H);
  const tubeH = scale.pack.gauge.share * U * ks;
  const tubeW = tubeH * 0.4;
  const rad = tubeW * 0.3;
  const numSize = capFont(share("levelNumber"), U, ks, dir.cap);
  const kSize = capFont(share("packKicker"), U, ks);
  const cSize = capFont(scale.context.share, U, ks) * 1.06;
  const ctx = context ? fitLines(context, INTER, 600, cSize, cSize * 0.8, 0.27 * W, 2) : null;
  const finalText = total ? `${countText(figureOf(value), 1)}/${countText(figureOf(total), 1)}` : `${countText(figureOf(value), 1)}%`;
  const numW = widthOf(finalText, GROTESK, numSize, 800, -0.02);
  const colW = Math.max(numW, kicker ? capsWidth(kicker, kSize) : 0, ctx ? ctx.width : 0);
  const gap = 0.4 * tubeW + 22 * k;
  const labelRow = kSize + 14 * k;
  const w = tubeW + gap + colW;
  const h = labelRow + tubeH;
  const zone = zoneFor(overlay, "lower-left", w, h, W, H) as Zone;
  const r = blockAt(zone, w, h, W, H);
  const right = isRight(zone);
  const tubeX = right ? r.x + r.w - tubeW : r.x;
  const tubeY = r.y + labelRow;
  const colX = right ? r.x : tubeX + tubeW + gap;
  const grow = prog(f, 0, 16, S, expoOut);
  const fill = prog(f, 10, 38, S, (u) => 1 - (1 - u) ** 2.6);
  const land = 48;
  const swell = clamp01((f / S - land) / 6) * (1 - clamp01((f / S - land - 6) / 26));
  const levelY = tubeH * (1 - sh * fill);
  const t = f / S;
  const amp = (1.6 + 3.2 * (fill > 0 && fill < 1 ? 1 : 0) + 4 * swell) * k * (sh * fill > 0.02 ? 1 : 0);
  const ph = t * 0.16;
  const o = clamp01(grow * 1.5) * (1 - clamp01(out * 1.3));
  const drift = idle(f, 50 * S, dur) * 4 * k;
  const shown = total ? `${countText(figureOf(value), fill)}` : `${countText(figureOf(value), fill)}%`;
  const ticks = [0.25, 0.5, 0.75];
  const markerY = tubeY + levelY;
  const waves = surface(tubeW, levelY, amp, ph);
  const waterId = `ktlv${hash(`${value}:${total}:${kicker}`)}`;
  return (
    <AbsoluteFill>
      <Backing panel={false} dir={dir} rect={r} right={right} p={grow} out={out} />
      <div style={{ position: "absolute", left: 0, top: -drift, width: W, height: H }}>
        {/* FULL over the gauge */}
        <div style={{ position: "absolute", left: tubeX - 40 * k, width: tubeW + 80 * k, top: r.y, display: "flex", justifyContent: "center" }}>
          <Caps text="Full" size={kSize * 0.92} color={DIM} at={10} out={out} k={k} tracking={0.22} align="center" />
        </div>
        {/* the gauge */}
        <div style={{ position: "absolute", left: tubeX, top: tubeY, width: tubeW, height: tubeH, opacity: o,
          transformOrigin: "50% 100%", transform: `scaleY(${(0.6 + 0.4 * grow).toFixed(4)})` }}>
          <div style={{ position: "absolute", inset: 0, borderRadius: rad, overflow: "hidden",
            background: "linear-gradient(180deg, rgba(30,34,42,0.62) 0%, rgba(10,12,16,0.78) 100%)",
            backdropFilter: `blur(${(14 * k).toFixed(1)}px)`, WebkitBackdropFilter: `blur(${(14 * k).toFixed(1)}px)`,
            boxShadow: `inset 0 0 0 ${Math.max(1, 1.5 * k).toFixed(1)}px rgba(255,255,255,0.2), 0 ${(16 * k).toFixed(1)}px ${(40 * k).toFixed(1)}px rgba(0,0,0,0.42)` }}>
            <svg width={tubeW} height={tubeH} style={{ position: "absolute", inset: 0 }}>
              <defs>
                <linearGradient id={waterId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="rgba(214,236,252,0.96)" />
                  <stop offset="18%" stopColor="rgba(148,201,238,0.9)" />
                  <stop offset="100%" stopColor="rgba(54,112,170,0.92)" />
                </linearGradient>
              </defs>
              {sh * fill > 0.002 ? (
                <>
                  <path d={`M0,${tubeH} L${ptsD(waves)} L${tubeW},${tubeH} Z`} fill={`url(#${waterId})`} />
                  <path d={`M${ptsD(waves)}`} fill="none" stroke="rgba(255,255,255,0.85)" strokeWidth={Math.max(1, 2 * k)} />
                </>
              ) : null}
              {/* the tick marks: a quarter, a half, three quarters */}
              {ticks.map((q, i) => (
                <line key={i} x1={0} x2={(q === 0.5 ? 0.38 : 0.24) * tubeW} y1={tubeH * (1 - q)} y2={tubeH * (1 - q)}
                  stroke="rgba(255,255,255,0.5)" strokeWidth={Math.max(1, 1.6 * k)} opacity={prog(f, 8 + i * 2, 10, S, cubicOut)} />
              ))}
            </svg>
            {/* glass sheen down the left side */}
            <div style={{ position: "absolute", left: tubeW * 0.12, top: rad * 0.6, bottom: rad * 0.6, width: tubeW * 0.1, borderRadius: tubeW,
              background: "linear-gradient(180deg, rgba(255,255,255,0.22), rgba(255,255,255,0.04))" }} />
          </div>
        </div>
        {/* the marker riding the level */}
        <svg width={W} height={H} style={{ position: "absolute", inset: 0, overflow: "visible", opacity: o }}>
          {(() => {
            const x = right ? tubeX - 8 * k : tubeX + tubeW + 8 * k;
            const s = 13 * k * prog(f, 12, 10, S, (u) => backOut(u, 1.6));
            const dirn = right ? 1 : -1;
            return (
              <g style={{ filter: `drop-shadow(0 ${(2 * k).toFixed(1)}px ${(5 * k).toFixed(1)}px rgba(0,0,0,0.5))` }}>
                <path d={`M${x.toFixed(1)},${markerY.toFixed(1)} L${(x - dirn * s * 1.2).toFixed(1)},${(markerY - s * 0.7).toFixed(1)} `
                  + `L${(x - dirn * s * 1.2).toFixed(1)},${(markerY + s * 0.7).toFixed(1)} Z`} fill={hot} />
                <line x1={x - dirn * s * 1.2} x2={x - dirn * (s * 1.2 + 10 * k)} y1={markerY} y2={markerY} stroke={hot}
                  strokeWidth={Math.max(1.5, 2.5 * k)} strokeLinecap="round" />
              </g>
            );
          })()}
        </svg>
        {/* the column: kicker, the figure, the context */}
        <div style={{ position: "absolute", left: colX, top: tubeY + tubeH / 2, transform: "translateY(-50%)", width: colW,
          display: "flex", flexDirection: "column", alignItems: right ? "flex-end" : "flex-start" }}>
          {kicker ? (
            <div style={{ height: kSize, marginBottom: 12 * k }}>
              <Caps text={kicker} size={kSize} color={dir.id === "doc" ? "rgba(250,250,247,0.86)" : hot} at={8} out={out} k={k}
                align={right ? "right" : "left"} />
            </div>
          ) : null}
          <div style={{ position: "relative", fontFamily: GROTESK, fontWeight: 800, fontSize: numSize, lineHeight: 1, color: WHITE,
            letterSpacing: "-0.02em", fontVariantNumeric: "tabular-nums", fontFeatureSettings: '"tnum" 1', whiteSpace: "nowrap",
            textShadow: softShadow(k, 0.55), opacity: prog(f, 9, 10, S, cubicOut) * (1 - clamp01(out * 1.3)),
            transform: `scale(${settle(f, land, S).toFixed(4)}) translateY(${(out * 8 * k).toFixed(2)}px)`,
            transformOrigin: right ? "right bottom" : "left bottom", minWidth: numW, textAlign: right ? "right" : "left" }}>
            {shown}
            {total ? <span style={{ fontSize: numSize * 0.55, color: SOFT_WHITE, fontWeight: 700 }}>{`/${countText(figureOf(total), 1)}`}</span> : null}
            <div style={{ position: "absolute", inset: 0, overflow: "hidden", mixBlendMode: "screen" }}>
              <Glint p={(t - land) / 20} />
            </div>
          </div>
          {ctx ? (
            <div style={{ marginTop: 14 * k }}>
              {ctx.lines.map((ln, i) => (
                <KineticLine key={i} text={ln} font={INTER} weight={600} size={ctx.size} color={SOFT_WHITE} preset="focus"
                  timing={{ at: 26 + i * 4, gap: 2 }} out={out} align={right ? "right" : "left"} shadow={softShadow(k, 0.55)} />
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== kt-trend
/** A smooth curve through points (Catmull-Rom as cubic Béziers), sampled into a polyline `per` points a segment. */
const sampleCurve = (pts: [number, number][], per = 18): [number, number][] => {
  if (pts.length < 2) return pts;
  const out: [number, number][] = [pts[0]];
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
    const c1: [number, number] = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
    const c2: [number, number] = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    for (let s = 1; s <= per; s++) {
      const t = s / per, u = 1 - t;
      out.push([
        u * u * u * p1[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t * t * t * p2[0],
        u * u * u * p1[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t * t * t * p2[1],
      ]);
    }
  }
  return out;
};
/** The point of a polyline (x increasing) at x. */
const atX = (poly: [number, number][], x: number): [number, number] => {
  if (x <= poly[0][0]) return poly[0];
  for (let i = 1; i < poly.length; i++) {
    if (poly[i][0] >= x) {
      const a = poly[i - 1], b = poly[i];
      const t = (x - a[0]) / Math.max(1e-6, b[0] - a[0]);
      return [x, lerp(a[1], b[1], t)];
    }
  }
  return poly[poly.length - 1];
};
const polyD = (poly: [number, number][]) => `M${poly.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" L")}`;

/**
 * Three or more years with their figures, as a frosted card upper right (the
 * calm side; 36 % of the width): the title and its unit, faint gridlines, the
 * line drawing in left to right (frames 12-58, cubic in-out) with its area
 * filling behind and a dot riding its head, the value counting in a pill
 * above it; when it has drawn, the peak (▲) and the low (▼) are marked with
 * their year and value, and the last point gets a ring.
 */
const Trend: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, dir, hot, out, ks } = useLook(overlay, accent);
  const rows = rowsOf(overlay.items, 8);
  if (rows.length < 3) return null;
  const { suffix, prefix } = unitsOf(rows, overlay.suffix, overlay.prefix);
  const title = str(overlay.text) || str(overlay.label);
  const unitLine = str(overlay.subtitle);
  const U = unitOf(W, H);
  const kSize = capFont(share("packKicker"), U, ks);
  const vSize = capFont(share("trendValue"), U, ks);
  const aSize = capFont(share("trendAxis"), U, ks);
  const cw = Math.min(scale.pack.trendCard.w * W, 0.62 * W);
  const ch = scale.pack.trendCard.h * U;
  const pad = 30 * k;
  const head = (title ? kSize + 10 * k : 0) + (unitLine ? aSize + 8 * k : 0) + 18 * k;
  const zone = zoneFor(overlay, "upper-right", cw, ch, W, H) as Zone;
  const r = blockAt(zone, cw, ch, W, H);
  const vals = rows.map((x) => x.value);
  const sc = seriesScale(vals, 3);
  const yearsX = rows.every((x) => /^(1[5-9]\d\d|20\d\d)$/.test(x.label));
  const axisW = Math.max(...sc.ticks.map((t) => widthOf(countText(figureOf(t, "", prefix), 1), SUBLINE, aSize, 600)));
  const px0 = pad + axisW + 16 * k, px1 = cw - pad - 18 * k;
  const py0 = head + pad + vSize * 1.4, py1 = ch - pad - aSize * 1.6;
  const lo = yearsX ? Number(rows[0].label) : 0, hi = yearsX ? Number(rows[rows.length - 1].label) : rows.length - 1;
  const xOf = (i: number) => px0 + ((yearsX ? Number(rows[i].label) - lo : i) / Math.max(1e-6, hi - lo)) * (px1 - px0);
  const yOf = (v: number) => py1 - ((v - sc.min) / Math.max(1e-9, sc.max - sc.min)) * (py1 - py0);
  const pts = rows.map((x, i) => [xOf(i), yOf(x.value)] as [number, number]);
  const monotone = pts.every((p, i) => i === 0 || p[0] > pts[i - 1][0]);
  if (!monotone) return null;
  const poly = sampleCurve(pts);
  const open = prog(f, 0, 14, S, expoOut);
  const drawP = prog(f, 12, 46, S, cubicInOut);
  const hx = lerp(px0, px1, drawP);
  const headPt = atX(poly, hx);
  // the value at the head: between the two points it is between
  let seg = 0;
  while (seg < pts.length - 2 && hx > pts[seg + 1][0]) seg++;
  const segT = clamp01((hx - pts[seg][0]) / Math.max(1e-6, pts[seg + 1][0] - pts[seg][0]));
  const headV = lerp(rows[seg].value, rows[seg + 1].value, segT);
  const fig = (v: number) => {
    const fg = figureOf(v, suffix, prefix);
    return `${fg.prefix}${countText(fg, 1)}${fg.glued}${fg.unit ? ` ${fg.unit}` : ""}`;
  };
  const landed = 58;
  const maxI = vals.indexOf(Math.max(...vals));
  const minI = vals.indexOf(Math.min(...vals));
  const marks = [{ i: maxI, up: true }, ...(minI !== maxI ? [{ i: minI, up: false }] : [])];
  const lastI = rows.length - 1;
  const ring = prog(f, landed + 4, 16, S, cubicInOut) * (1 - clamp01(out * 1.5));
  const id = `kttr${hash(rows.map((x) => `${x.label}:${x.value}`).join("|") + title)}`;
  const drift = idle(f, 70 * S, dur) * 3 * k;
  const pillText = fig(headV);
  const pillW = widthOf(pillText, GROTESK, vSize, 800, -0.01) + 22 * k;
  const showPill = drawP > 0.02 && drawP < 0.995 && out <= 0;
  return (
    <AbsoluteFill>
      <Glass x={r.x} y={r.y - drift} w={cw} h={ch} k={k} p={open} out={out} right={isRight(zone)} radius={16}>
        <div style={{ position: "absolute", left: pad, top: pad, right: pad }}>
          {title ? (
            <div style={{ height: kSize, marginBottom: 10 * k }}>
              <Caps text={title} size={kSize} color={dir.id === "doc" ? "rgba(250,250,247,0.86)" : hot} at={4} out={out} k={k} />
            </div>
          ) : null}
          {unitLine ? (
            <div style={{ height: aSize }}>
              <Caps text={unitLine} size={aSize} color={DIM} at={8} out={out} k={k} tracking={0.14} weight={600} />
            </div>
          ) : null}
        </div>
        <svg width={cw} height={ch} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          <defs>
            <linearGradient id={`${id}a`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={hot} stopOpacity={0.3} />
              <stop offset="100%" stopColor={hot} stopOpacity={0} />
            </linearGradient>
            <clipPath id={`${id}c`}><rect x={0} y={0} width={hx} height={ch} /></clipPath>
          </defs>
          {sc.ticks.map((tk, i) => (
            <g key={i} opacity={prog(f, 6 + i * 2, 12, S, cubicOut) * (1 - clamp01(out * 1.5))}>
              <line x1={px0} x2={px1} y1={yOf(tk)} y2={yOf(tk)} stroke="rgba(255,255,255,0.13)" strokeWidth={Math.max(1, 1.4 * k)}
                strokeDasharray={`${5 * k} ${7 * k}`} />
              {/* (the axis's lowest figure is left out: it would sit on the first year) */}
              {i > 0 ? (
                <text x={px0 - 12 * k} y={yOf(tk) + aSize * 0.36} textAnchor="end" fill="rgba(250,250,247,0.58)"
                  style={{ fontFamily: SUBLINE, fontWeight: 600, fontSize: aSize, fontVariantNumeric: "tabular-nums" }}>
                  {countText(figureOf(tk, "", prefix), 1)}
                </text>
              ) : null}
            </g>
          ))}
          <path d={`${polyD(poly)} L${px1},${py1} L${px0},${py1} Z`} fill={`url(#${id}a)`} clipPath={`url(#${id}c)`} />
          <path d={polyD(poly)} fill="none" stroke={hot} strokeWidth={Math.max(2.5, 4.5 * k)} strokeLinecap="round"
            strokeLinejoin="round" clipPath={`url(#${id}c)`} style={{ filter: `drop-shadow(0 0 ${(6 * k).toFixed(1)}px ${rgba(hot, 0.5)})` }} />
          {pts.map(([x, y], i) => {
            const on = clamp01((hx - x) / (8 * k) + 0.5);
            return on > 0 ? <circle key={i} cx={x} cy={y} r={(i === lastI ? 6.5 : 5) * k * (0.5 + 0.5 * on)} fill="#fff"
              stroke={hot} strokeWidth={2.5 * k} opacity={on * (1 - clamp01(out * 1.5))} /> : null;
          })}
          {/* the x labels: the years (the first and the last always, the rest when they fit) */}
          {rows.map((row, i) => {
            const x = xOf(i);
            const lw = widthOf(row.label, SUBLINE, aSize, 700, 0.04);
            const prevX = i > 0 ? xOf(i - 1) : -1e9;
            const crowded = i > 0 && i < lastI && (x - prevX < lw + 14 * k || xOf(lastI) - x < lw + 14 * k);
            if (crowded) return null;
            return (
              <text key={`x${i}`} x={x} y={py1 + aSize * 1.45} textAnchor="middle" fill="rgba(250,250,247,0.7)"
                opacity={prog(f, 8 + i, 12, S, cubicOut) * (1 - clamp01(out * 1.5))}
                style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: aSize, letterSpacing: "0.04em" }}>{row.label}</text>
            );
          })}
          {/* the head */}
          {drawP > 0.005 && drawP < 0.999 && out <= 0 ? (
            <g>
              <circle cx={headPt[0]} cy={headPt[1]} r={11 * k} fill={rgba(hot, 0.25)} />
              <circle cx={headPt[0]} cy={headPt[1]} r={6 * k} fill="#fff" stroke={hot} strokeWidth={3 * k} />
            </g>
          ) : null}
          {/* the peak and the low, once drawn */}
          {marks.map(({ i, up }, n) => {
            const p = prog(f, landed + 2 + n * 6, 14, S, expoOut) * (1 - clamp01(out * 1.4));
            if (p <= 0.001) return null;
            const [x, y] = pts[i];
            const s = 8 * k;
            const label = `${fig(rows[i].value)} · ${rows[i].label}`;
            const fs = aSize * 1.04;
            const lw = widthOf(label, GROTESK, fs, 700, 0) + (up ? 0 : 0);
            const ringed = i === lastI;
            // the label's place: above (the peak) or below (the low) its point when that is clear of the line, the
            // years and the card's edges, else beside it on the clear side - never over the line
            const clear = (cx: number, cy: number) => {
              const x0 = cx - lw / 2 - 5 * k, x1 = cx + lw / 2 + 5 * k, y0 = cy - fs * 0.62, y1 = cy + fs * 0.62;
              if (x0 < px0 + 2 * k || x1 > cw - pad * 0.5 || y0 < head + pad * 0.5 || y1 > py1 + 4 * k) return false;
              return !poly.some((q) => q[0] > x0 - 6 * k && q[0] < x1 + 6 * k && q[1] > y0 - 6 * k && q[1] < y1 + 6 * k);
            };
            const off = (ringed ? 30 : 24) * k + fs * 0.5;
            const dy = up ? -off : off;
            const cands: [number, number, boolean][] = [[x, y + dy, true], [x + lw / 2 + 16 * k, y + dy * 0.7, false],
              [x - lw / 2 - 16 * k, y + dy * 0.7, false], [x, y - dy, true], [x + lw / 2 + 16 * k, y - dy * 0.7, false],
              [x - lw / 2 - 16 * k, y - dy * 0.7, false]];
            const at = cands.find(([cx, cy]) => clear(cx, cy)) || cands[0];
            const [lx, lyc, onAxis] = at;
            const markUp = lyc < y;
            const ty = markUp ? y - (ringed ? 22 : 16) * k : y + (ringed ? 22 : 16) * k;
            return (
              <g key={n} opacity={p} transform={`translate(0, ${((1 - p) * (up ? 8 : -8) * k).toFixed(2)})`}>
                {onAxis && !ringed ? (
                  <path d={markUp ? `M${x},${ty - s * 0.4} L${x - s},${ty - s * 1.8} L${x + s},${ty - s * 1.8} Z`
                    : `M${x},${ty + s * 0.4} L${x - s},${ty + s * 1.8} L${x + s},${ty + s * 1.8} Z`} fill={up ? hot : WHITE} />
                ) : null}
                <text x={lx} y={lyc + fs * 0.36} textAnchor="middle" fill={WHITE}
                  style={{ fontFamily: GROTESK, fontWeight: 700, fontSize: fs, fontVariantNumeric: "tabular-nums",
                    paintOrder: "stroke", stroke: "rgba(8,10,14,0.55)", strokeWidth: 4 * k } as React.CSSProperties}>
                  <tspan fill={up ? hot : "rgba(250,250,247,0.8)"}>{up ? "▲ " : "▼ "}</tspan>{label}
                </text>
              </g>
            );
          })}
          {ring > 0.001 ? (
            <circle cx={pts[lastI][0]} cy={pts[lastI][1]} r={16 * k} fill="none" stroke="#fff" strokeWidth={2.5 * k} pathLength={1}
              strokeDasharray="1 1" strokeDashoffset={1 - ring} transform={`rotate(-90 ${pts[lastI][0]} ${pts[lastI][1]})`} />
          ) : null}
        </svg>
        {showPill ? (
          <div style={{ position: "absolute", left: Math.max(pad, Math.min(cw - pad - pillW, headPt[0] - pillW / 2)),
            top: headPt[1] - vSize * 1.55 - 12 * k, height: vSize * 1.3, padding: `0 ${11 * k}px`, borderRadius: vSize, display: "flex",
            alignItems: "center", background: "rgba(8,10,14,0.72)", boxShadow: `inset 0 0 0 ${Math.max(1, k)}px ${rgba(hot, 0.6)}`,
            fontFamily: GROTESK, fontWeight: 800, fontSize: vSize, color: WHITE, fontVariantNumeric: "tabular-nums",
            fontFeatureSettings: '"tnum" 1', whiteSpace: "nowrap", lineHeight: 1 }}>{pillText}</div>
        ) : null}
      </Glass>
    </AbsoluteFill>
  );
};

// ================================================================== kt-milestones
interface Mile { label: string; text: string; at: number | null }
/**
 * Three to five years said one after another, as a strip low in the frame (the
 * calm side's margin to 70-86 % of the width): every year shown faint from the
 * start, each point lighting when its year is said (items[].at, seconds from
 * the look's start; else one every 0.8 s) - its dot fills with the accent and
 * rings once, its year turns white, its words come into focus under it - the
 * accent line running on from the point before. A soft tick on each landing
 * (useLookSound: the frames are the items').
 */
const Milestones: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dir, hot, out, ks } = useLook(overlay, accent);
  const items: Mile[] = (Array.isArray(overlay.items) ? overlay.items : [])
    .map((it) => ({ label: str(it?.label), text: str(it?.text), at: num((it as { at?: unknown } | undefined)?.at) }))
    .filter((x) => x.label).slice(0, 5);
  const n = items.length;
  // light frames (30 fps): the first on its word at the look's start, each later one on its own word
  const lights: number[] = [];
  items.forEach((it, i) => {
    const said = it.at !== null && it.at >= 0 ? 6 + it.at * 30 : 14 + i * 24;
    lights.push(i === 0 ? Math.min(14, said) : Math.max(lights[i - 1] + 10, said));
  });
  const sound = useLookSound(n >= 2 ? lights.map((at) => ({ name: "ui-tick", alt: ["tick", "letter-tick"], at: Math.round(at), gain_db: -9 })) : null);
  if (n < 2) return null;
  const kicker = str(overlay.text) || str(overlay.label);
  const U = unitOf(W, H);
  const ySize = capFont(share("mileYear"), U, ks, dir.cap);
  const lSize = capFont(share("mileLabel"), U, ks);
  const kSize = capFont(share("packKicker"), U, ks);
  const mx = scale.safe.x * W;
  const colW = Math.min(0.2 * W, (W - 2 * mx - 60 * k) / n);
  const labels = items.map((it) => (it.text ? fitLines(it.text, INTER, 600, lSize, lSize * 0.82, colW - 24 * k, 2) : null));
  const labelH = Math.max(0, ...labels.map((l) => (l ? l.lines.length * l.size * 1.24 : 0)));
  const padX = 34 * k, padT = 26 * k, padB = 24 * k;
  const head = kicker ? kSize + 18 * k : 0;
  const nodeRow = 30 * k;
  const w = colW * n + padX * 2;
  const h = padT + head + ySize * 1.15 + 12 * k + nodeRow + 14 * k + labelH + padB;
  const zone = zoneFor(overlay, "lower-left", w, h, W, H) as Zone;
  const r = blockAt(zone, w, h, W, H);
  const open = prog(f, 0, 16, S, expoOut);
  const track = prog(f, 6, 18, S, expoOut) * (1 - clamp01(out * 1.4));
  const cx = (i: number) => padX + colW * (i + 0.5);
  const nodeY = padT + head + ySize * 1.15 + 12 * k + nodeRow / 2;
  const t = f / S;
  // the accent line: from the first point to the last lit one, running on as each lights
  let runX = cx(0);
  for (let i = 1; i < n; i++) {
    const p = clamp01((t - (lights[i] - 10)) / 10);
    if (p <= 0) break;
    runX = lerp(cx(i - 1), cx(i), cubicInOut(p));
  }
  const litN = lights.filter((l) => t >= l).length;
  return (
    <AbsoluteFill>
      {sound}
      <Glass x={r.x} y={r.y} w={w} h={h} k={k} p={open} out={out} right={isRight(zone)} radius={16}>
        {kicker ? (
          <div style={{ position: "absolute", left: padX, top: padT, height: kSize }}>
            <Caps text={kicker} size={kSize} color={dir.id === "doc" ? "rgba(250,250,247,0.86)" : hot} at={4} out={out} k={k} />
          </div>
        ) : null}
        <svg width={w} height={h} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          <line x1={cx(0)} x2={lerp(cx(0), cx(n - 1), track)} y1={nodeY} y2={nodeY} stroke="rgba(255,255,255,0.26)"
            strokeWidth={Math.max(1.5, 2.5 * k)} strokeLinecap="round" />
          {litN > 0 ? (
            <line x1={cx(0)} x2={runX} y1={nodeY} y2={nodeY} stroke={hot} strokeWidth={Math.max(2, 3.5 * k)} strokeLinecap="round"
              opacity={1 - clamp01(out * 1.4)} style={{ filter: `drop-shadow(0 0 ${(6 * k).toFixed(1)}px ${rgba(hot, 0.55)})` }} />
          ) : null}
          {items.map((_, i) => {
            const pop = prog(f, 8 + i * 3, 12, S, (u) => backOut(u, 1.4)) * (1 - clamp01(out * 1.4 - (i / n) * 0.3));
            const lit = clamp01((t - lights[i]) / 6);
            const ring = clamp01((t - lights[i]) / 22);
            return (
              <g key={i} opacity={clamp01(pop * 1.5)}>
                {lit > 0 && ring < 1 ? <circle cx={cx(i)} cy={nodeY} r={(10 + 22 * cubicOut(ring)) * k} fill="none" stroke={hot}
                  strokeWidth={2 * k} opacity={(1 - ring) * 0.8} /> : null}
                <circle cx={cx(i)} cy={nodeY} r={10 * k * (0.6 + 0.4 * pop)} fill={lit > 0 ? hot : "rgba(10,12,16,0.85)"}
                  stroke={lit > 0 ? hot : "rgba(255,255,255,0.55)"} strokeWidth={2.5 * k} />
                {lit > 0 ? <circle cx={cx(i)} cy={nodeY} r={3.5 * k * lit} fill="#fff" /> : null}
              </g>
            );
          })}
        </svg>
        {items.map((it, i) => {
          const lit = clamp01((t - lights[i]) / 8);
          const current = i === litN - 1;
          const yIn = prog(f, 8 + i * 3, 14, S, expoOut) * (1 - clamp01(out * 1.4 - (i / n) * 0.3));
          const lab = labels[i];
          return (
            <React.Fragment key={i}>
              <div style={{ position: "absolute", left: cx(i) - colW / 2, width: colW, top: padT + head, textAlign: "center",
                fontFamily: dir.font, fontWeight: 800, fontSize: ySize, lineHeight: 1.15, letterSpacing: "-0.01em",
                fontVariantNumeric: "tabular-nums", fontFeatureSettings: '"tnum" 1', whiteSpace: "nowrap",
                color: lit > 0 ? (current ? WHITE : "rgba(250,250,247,0.82)") : "rgba(250,250,247,0.34)",
                textShadow: softShadow(k, 0.5), opacity: yIn,
                transform: `translateY(${((1 - yIn) * 0.2 * ySize - (current ? 3 * k * sineInOut(clamp01((t - lights[i]) / 10)) : 0)).toFixed(2)}px) `
                  + `scale(${(1 + (current ? 0.04 * Math.sin(clamp01((t - lights[i]) / 12) * Math.PI) : 0)).toFixed(4)})` }}>
                {it.label}
              </div>
              {lab ? (
                <div style={{ position: "absolute", left: cx(i) - colW / 2 + 12 * k, width: colW - 24 * k, top: nodeY + nodeRow / 2 + 14 * k }}>
                  {lab.lines.map((ln, j) => (
                    <div key={j} style={{ height: lab.size * 1.24, opacity: lit }}>
                      <KineticLine text={ln} font={INTER} weight={600} size={lab.size} color={current ? WHITE : SOFT_WHITE}
                        preset="focus" timing={{ at: lights[i] + j * 3, gap: 1.6 }} out={out} align="left"
                        style={{ textAlign: "center" }} shadow={softShadow(k, 0.45)} />
                    </div>
                  ))}
                </div>
              ) : null}
            </React.Fragment>
          );
        })}
      </Glass>
    </AbsoluteFill>
  );
};

// ================================================================== kt-pointer
/** A point on a quadratic from a through c to b at t, and its direction there. */
const quadAt = (a: [number, number], c: [number, number], b: [number, number], t: number) => {
  const u = 1 - t;
  const p: [number, number] = [u * u * a[0] + 2 * u * t * c[0] + t * t * b[0], u * u * a[1] + 2 * u * t * c[1] + t * t * b[1]];
  const d: [number, number] = [2 * u * (c[0] - a[0]) + 2 * t * (b[0] - c[0]), 2 * u * (c[1] - a[1]) + 2 * t * (b[1] - c[1])];
  return { p, d };
};

/**
 * On the playing footage, at the thing the line points at (overlay.anchor:
 * where vision found it in the frame the mark lands on - never a guess; a
 * still's own subject box when the scene has one): a ring in the accent draws
 * round it and rings out once (frames 0-20), a frosted label opens on the
 * calm side - away from the frame's edge, the faces, logos and lettering
 * (overlay.avoid) and the thing itself - with its words rising (6-20), and a
 * white arrow draws from the label to the ring (14-32), its head a crisp
 * triangle landing at 32. Without a place to point at it draws nothing.
 */
const Pointer: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, hot, out, ks } = useLook(overlay, accent);
  const a = anchorFrom(overlay);
  const label = str(overlay.text).toUpperCase();
  if (!a || !label) return null;
  const kicker = str(overlay.label).toUpperCase();
  const U = unitOf(W, H);
  const short = Math.min(W, H);
  const P: [number, number] = [a.x * W, a.y * H];
  const r0 = Math.max(38 * k, Math.min(150 * k, a.r ? a.r * short * 1.05 : a.w && a.h ? 0.55 * Math.max(a.w * W, a.h * H) : 64 * k));
  const lSize0 = capFont(share("pointerLabel"), U, ks);
  const kSize = capFont(share("packKicker"), U, ks) * 0.9;
  let lSize = lSize0;
  while (lSize > lSize0 * 0.75 && riseWidth(label, GROTESK, lSize, 800, 0.01) > 0.34 * W) lSize *= 0.95;
  const textW = Math.max(riseWidth(label, GROTESK, lSize, 800, 0.01), kicker ? capsWidth(kicker, kSize) : 0);
  const padX = 22 * k, padY = 16 * k;
  const cw = textW + padX * 2;
  const chh = padY * 2 + lSize * 1.2 + (kicker ? kSize + 8 * k : 0);
  // the calm side: candidate spots round the thing, the preferred first (toward the frame's middle, above)
  const dist = r0 + 120 * k;
  const towardX = P[0] > W / 2 ? -1 : 1;
  const towardY = P[1] > H * 0.45 ? -1 : 1;
  const spot = (dx: number, dy: number): Rect => {
    const cx = P[0] + dx * (dist + cw / 2), cy = P[1] + dy * (dist * 0.8 + chh / 2);
    return rect(cx - cw / 2, cy - chh / 2, cw, chh);
  };
  const cands: Rect[] = [spot(towardX * 0.9, towardY * 0.75), spot(towardX, 0), spot(towardX * 0.9, -towardY * 0.75),
    spot(0, towardY), spot(-towardX * 0.9, towardY * 0.75), spot(-towardX, 0), spot(0, -towardY), spot(-towardX * 0.9, -towardY * 0.75)];
  const blockers: Rect[] = [rect(P[0] - r0 - 16 * k, P[1] - r0 - 16 * k, (r0 + 16 * k) * 2, (r0 + 16 * k) * 2),
    ...(Array.isArray(overlay.avoid) ? overlay.avoid : []).map((b) => rect(b.x * W, b.y * H, b.w * W, b.h * H))];
  const chip = placeRect(cands, blockers, W, H, 0.05 * W, 10 * k);
  // the arrow: from the label's edge nearest the thing to the ring's edge, bending gently
  const ccx = chip.x + chip.w / 2, ccy = chip.y + chip.h / 2;
  const vx = P[0] - ccx, vy = P[1] - ccy;
  const vl = Math.max(1, Math.hypot(vx, vy));
  const ux = vx / vl, uy = vy / vl;
  const tEdge = Math.min(Math.abs((chip.w / 2 + 8 * k) / (ux || 1e-6)), Math.abs((chip.h / 2 + 8 * k) / (uy || 1e-6)));
  const A0: [number, number] = [ccx + ux * tEdge, ccy + uy * tEdge];
  const B0: [number, number] = [P[0] - ux * (r0 + 14 * k), P[1] - uy * (r0 + 14 * k)];
  const len = Math.hypot(B0[0] - A0[0], B0[1] - A0[1]);
  const bend = (hash(label) % 2 === 0 ? 1 : -1) * Math.min(0.22 * len, 90 * k);
  const C: [number, number] = [(A0[0] + B0[0]) / 2 - uy * bend, (A0[1] + B0[1]) / 2 + ux * bend];
  const arrowP = prog(f, 14, 18, S, cubicInOut) * (1 - cubicIn(clamp01(out * 1.3)));
  const end = quadAt(A0, C, B0, Math.max(0.001, arrowP));
  const dl = Math.max(1e-6, Math.hypot(end.d[0], end.d[1]));
  const hx = end.d[0] / dl, hy = end.d[1] / dl;
  const hs = 15 * k * prog(f, 28, 8, S, (u) => backOut(u, 1.8)) * (1 - clamp01(out * 1.5));
  const tip: [number, number] = [end.p[0] + hx * hs * 0.55, end.p[1] + hy * hs * 0.55];
  const headD = `M${tip[0].toFixed(1)},${tip[1].toFixed(1)} L${(tip[0] - hx * hs * 1.6 - hy * hs * 0.85).toFixed(1)},${(tip[1] - hy * hs * 1.6 + hx * hs * 0.85).toFixed(1)} `
    + `L${(tip[0] - hx * hs * 1.6 + hy * hs * 0.85).toFixed(1)},${(tip[1] - hy * hs * 1.6 - hx * hs * 0.85).toFixed(1)} Z`;
  const ring = prog(f, 2, 18, S, cubicInOut) * (1 - cubicIn(clamp01(out * 1.3)));
  const pulse = clamp01((f / S - 8) / 26);
  const breathe = 1 + 0.025 * Math.sin(clamp01((f / S - 24) / 60) * Math.PI);
  const open = prog(f, 6, 14, S, expoOut);
  const quad = `M${A0[0].toFixed(1)},${A0[1].toFixed(1)} Q${C[0].toFixed(1)},${C[1].toFixed(1)} ${B0[0].toFixed(1)},${B0[1].toFixed(1)}`;
  return (
    <AbsoluteFill>
      <svg width={W} height={H} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
        {pulse > 0 && pulse < 1 ? (
          <circle cx={P[0]} cy={P[1]} r={r0 * (1 + 0.55 * cubicOut(pulse))} fill="none" stroke={hot} strokeWidth={2.5 * k}
            opacity={(1 - pulse) * 0.7} />
        ) : null}
        <g transform={`translate(${P[0]} ${P[1]}) scale(${breathe.toFixed(4)}) translate(${-P[0]} ${-P[1]})`}>
          <circle cx={P[0]} cy={P[1]} r={r0} fill="none" stroke={hot} strokeWidth={Math.max(3, 4.5 * k)} pathLength={1}
            strokeDasharray="1 1" strokeDashoffset={1 - ring} transform={`rotate(-120 ${P[0]} ${P[1]})`}
            style={{ filter: `drop-shadow(0 ${(1.5 * k).toFixed(1)}px ${(5 * k).toFixed(1)}px rgba(0,0,0,0.55))` }} />
        </g>
        <path d={quad} pathLength={1} fill="none" stroke="#fff" strokeWidth={Math.max(2.5, 4.5 * k)} strokeLinecap="round"
          strokeDasharray="1 1" strokeDashoffset={1 - arrowP}
          style={{ filter: `drop-shadow(0 ${(1.5 * k).toFixed(1)}px ${(5 * k).toFixed(1)}px rgba(0,0,0,0.6))` }} />
        {hs > 0.5 ? <path d={headD} fill="#fff" style={{ filter: `drop-shadow(0 ${(1.5 * k).toFixed(1)}px ${(4 * k).toFixed(1)}px rgba(0,0,0,0.55))` }} /> : null}
      </svg>
      <Glass x={chip.x} y={chip.y} w={chip.w} h={chip.h} k={k} p={open} out={out} right={ccx < P[0]} radius={12}>
        <div style={{ position: "absolute", left: padX, top: padY }}>
          {kicker ? (
            <div style={{ height: kSize, marginBottom: 8 * k }}>
              <Caps text={kicker} size={kSize} color={hot} at={8} out={out} k={k} />
            </div>
          ) : null}
          <RiseLine text={label} size={lSize} font={GROTESK} weight={800} at={9} out={out} k={k} tracking={0.01} />
        </div>
      </Glass>
    </AbsoluteFill>
  );
};

// ================================================================== kt-chapter
/**
 * A section opens (a deliberate full-frame moment of about three seconds: the
 * footage under it softens and dims - components/motion/stage.tsx): one soft
 * light leak crosses the frame (frames 0-30, warm white, never a gold wash),
 * an accent rule draws, the chapter's number rolls up in the accent, the
 * kicker tracks in and the title rises line by line from behind a mask, low
 * left (capitals 5 % of the height, two lines at most) - then all of it slides
 * back down behind its mask in the last 12 frames.
 */
const Chapter: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dir, hot, out, ks } = useLook(overlay, accent);
  const title = str(overlay.text);
  if (!title) return null;
  const n = num(overlay.value);
  const numText = n !== null && n >= 0 && n < 100 && Number.isInteger(n) ? String(n).padStart(2, "0") : "";
  const kicker = (str(overlay.label) || (numText ? "Chapter" : "")).toUpperCase();
  const sub = str(overlay.subtitle);
  const U = unitOf(W, H);
  const tSize0 = capFont(share("chapterTitle"), U, ks, dir.cap);
  const nSize = capFont(share("chapterNumber"), U, ks, dir.cap);
  const kSize = capFont(share("packKicker"), U, ks);
  const sSize = capFont(scale.context.share, U, ks);
  const fit = fitLines(title, dir.font, 800, tSize0, tSize0 * 0.72, 0.56 * W, 2, -0.015);
  if (!fit) return null;
  const subFit = sub ? fitLines(sub, INTER, 500, sSize, sSize * 0.85, 0.5 * W, 1) : null;
  const mx = scale.safe.x * W;
  const numW = numText ? widthOf(numText, dir.font, nSize, 800, -0.02) + 30 * k : 0;
  const lh = fit.size * 1.06;
  const blockH = kSize + 18 * k + fit.lines.length * lh + (subFit ? subFit.size * 1.6 : 0);
  const bottom = H * 0.8;
  const top = bottom - blockH;
  const t = f / S;
  // the light leak: two soft warm-white lobes crossing once, screen-blended, gone by frame ~34
  const leak = clamp01(t / 30);
  const leakO = Math.sin(leak * Math.PI) * 0.42 * (1 - clamp01(out * 2));
  const lx = lerp(-0.25, 1.15, cubicInOut(leak));
  // one thin anamorphic streak crossing with the leak, just under the title
  const streak = clamp01((t - 4) / 22);
  const streakO = Math.sin(streak * Math.PI) * 0.55 * (1 - clamp01(out * 2));
  const shade = prog(f, 0, 16, S, cubicOut) * (1 - clamp01(out * 1.2));
  const rule = prog(f, 6, 16, S, expoOut) * (1 - clamp01(out * 1.4));
  const nIn = prog(f, 6, 18, S, expoOut);
  const nOut = cubicIn(clamp01(out * 1.3));
  return (
    <AbsoluteFill>
      {/* the shade the words sit on: from the low left corner, no edge */}
      <AbsoluteFill style={{ opacity: shade, background: `radial-gradient(ellipse 70% 60% at 18% 82%, rgba(4,5,8,0.62) 0%, `
        + `rgba(4,5,8,0.32) 45%, rgba(4,5,8,0) 100%)` }} />
      {leakO > 0.002 ? (
        <AbsoluteFill style={{ mixBlendMode: "screen", opacity: leakO, pointerEvents: "none",
          background: `radial-gradient(ellipse 34% 70% at ${(lx * 100).toFixed(1)}% 40%, rgba(255,240,222,0.95) 0%, rgba(255,214,170,0.55) 35%, rgba(255,190,140,0) 70%), `
            + `radial-gradient(ellipse 22% 45% at ${((lx - 0.18) * 100).toFixed(1)}% 70%, rgba(255,226,196,0.7) 0%, rgba(255,226,196,0) 70%)` }} />
      ) : null}
      {streakO > 0.002 ? (
        <div style={{ position: "absolute", left: 0, right: 0, top: top + kSize + 18 * k + fit.lines.length * lh + 10 * k,
          height: Math.max(2, 3 * k),
          mixBlendMode: "screen", opacity: streakO, filter: `blur(${(1.5 * k).toFixed(1)}px)`, pointerEvents: "none",
          background: `radial-gradient(ellipse 30% 100% at ${(lerp(-0.1, 1.1, cubicInOut(streak)) * 100).toFixed(1)}% 50%, `
            + "rgba(255,246,232,1) 0%, rgba(255,226,190,0.5) 40%, rgba(255,226,190,0) 100%)" }} />
      ) : null}
      <div style={{ position: "absolute", left: mx, top, display: "flex", alignItems: "flex-start", gap: 0 }}>
        {numText ? (
          <div style={{ width: numW, height: nSize * 1.1, overflow: "hidden", marginTop: kSize + 18 * k - nSize * 0.05 }}>
            <div style={{ fontFamily: dir.font, fontWeight: 800, fontSize: nSize, lineHeight: 1.1, color: hot, letterSpacing: "-0.02em",
              fontVariantNumeric: "tabular-nums", textShadow: softShadow(k, 0.4),
              transform: `translateY(${((1 - nIn) * 100 + nOut * 100).toFixed(2)}%)` }}>{numText}</div>
          </div>
        ) : null}
        <div style={{ position: "relative", paddingLeft: numText ? 26 * k : 0 }}>
          {numText ? (
            <div style={{ position: "absolute", left: 0, top: kSize + 18 * k, width: Math.max(2, 3 * k), height: fit.lines.length * lh * rule,
              background: hot, borderRadius: 2 * k, boxShadow: `0 0 ${(10 * k).toFixed(1)}px ${rgba(hot, 0.5)}` }} />
          ) : (
            <div style={{ position: "absolute", left: 0, top: kSize + 8 * k, height: Math.max(2, 3 * k), width: 56 * k * rule,
              background: hot, borderRadius: 2 * k }} />
          )}
          {kicker ? (
            <div style={{ height: kSize, marginBottom: 18 * k }}>
              <Caps text={kicker} size={kSize} color={dir.id === "doc" ? "rgba(250,250,247,0.86)" : hot} at={8} out={out} k={k} tracking={0.28} />
            </div>
          ) : null}
          {fit.lines.map((ln, i) => (
            <div key={i} style={{ height: lh }}>
              <KineticLine text={ln} font={dir.font} weight={800} size={fit.size} tracking={-0.015} preset="mask"
                timing={{ at: 10 + i * 4, gap: 2, len: 18 }} out={out} shadow={softShadow(k, 0.6)} />
            </div>
          ))}
          {subFit ? (
            <div style={{ marginTop: subFit.size * 0.5 }}>
              <KineticLine text={subFit.lines[0]} font={INTER} weight={500} size={subFit.size} color={SOFT_WHITE} preset="focus"
                timing={{ at: 22, gap: 2 }} out={out} shadow={softShadow(k, 0.55)} />
            </div>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "kt-quote": guard(Quote),
  "kt-term": guard(Term),
  "kt-level": guard(Level),
  "kt-trend": guard(Trend),
  "kt-milestones": guard(Milestones),
  "kt-pointer": guard(Pointer),
  "kt-chapter": guard(Chapter),
};

