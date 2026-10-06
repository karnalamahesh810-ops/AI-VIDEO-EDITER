import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import type { Overlay } from "../../types";
import { GROTESK, GROTESK_CAP, INTER, SUBLINE } from "../fonts";
import { THEMES } from "../themes";
import { backOut, exitProg, idle, motionBlur, sineInOut } from "../motion/ease";
import { guard, hash, rgba, type Look } from "./proKit";
import { num, str } from "./proFormat";
import {
  CHARCOAL, DIRECTIONS, Glint, INK, KineticLine, PanelBacking, SOFT_WHITE, SoftBacking, WHITE, blockAt, clamp01,
  contextStyle, cubicInOut, cubicOut, directionOf, expoOut, figureAt, fitLines, fontScaleOf, formatFigure, isRight,
  isUpper, kickerStyle, prog, settle, sizeFor, softShadow, widthOf, zoneFor, type DirSpec, type Zone,
} from "./typeKit";
import scale from "./typeScale.json";
import { typedAt, typingEnds } from "./LibEditorText";

/**
 * KINETIC TYPE (family "kt-", 2026-10-05): the words and figures the
 * narration says, in one premium editorial system (components/lib/typeKit.tsx)
 * - replacing the big yellow outlined condensed words and the boxed stacks the
 * owner called cheap ("like a CapCut font").
 *
 *   kt-keyword     the key phrase being said: kicker + 1-2 lines, low left
 *   kt-number      a figure counting up to its value with its unit and one line
 *                  of context (60,000 / 1.25M), the hero size rule (14 % of height)
 *   kt-chip        the same figure compact, for a quick run of numbers
 *   kt-percent     a ring that fills to the share while the number counts (27 %)
 *   kt-progress    a bar that fills for "3 of 4" / a share of a whole
 *   kt-multiplier  "15x": the count climbs inside a ring of ticks that light one
 *                  by one, the ring closes on the landing
 *   kt-compare     two (or three) values as bars that grow ("1x vs 15x",
 *                  "50,000 vs 760,000"), the larger in the accent
 *   kt-date ...    the dates, years and times said: LibKtDates.tsx (the date family, 2026-10-06)
 *   kt-lower-third a name and role, low left
 *
 * Every one: a direction (editorial / doc / kinetic), its home place (mirrored
 * off a face, a logo or lettering, overlay.avoid), a soft shade, a slim blurred
 * panel over busy footage (overlay.backing "panel") or the kinetic charcoal box,
 * an eased entry of 12-20 frames, a gentle idle, and a mirrored 12-frame exit.
 * Only the plan's words are set; a look that cannot set them whole draws nothing.
 */

export const useLook = (overlay: Overlay, accent: string) => {
  const f = useCurrentFrame();
  const { fps, width: W, height: H, durationInFrames: dur } = useVideoConfig();
  const S = fps / 30;
  const k = W / 1920;
  const dir = directionOf(overlay);
  // The accent: the overlay's theme (or the brand kit's colour, theme "accent"), else the direction's own.
  // The brand kit's accent leads (the kicker, the bar, the ring); the worker's unset default (#FFD400, a hard
  // yellow) gives way to the direction's refined gold, so a video without a brand kit never gets a yellow fill.
  const themed = overlay.theme && overlay.theme !== "auto" && overlay.theme !== "accent";
  const brand = accent && !/^#?ffd400$/i.test(accent.trim()) ? accent : "";
  const hot = themed ? (THEMES[overlay.theme || ""] || brand || dir.accent) : (brand || dir.accent);
  const out = exitProg(f, dur, 12, S);
  const ks = fontScaleOf(overlay);
  const panel = String((overlay as { backing?: string }).backing || "") === "panel";
  return { f, S, k, W, H, dur, dir, hot, out, ks, panel };
};

/** The backing behind a block: the slim panel, the kinetic box (drawn per line by the look) or the soft shade. */
export const Backing: React.FC<{ panel: boolean; dir: DirSpec; rect: { x: number; y: number; w: number; h: number };
  right: boolean; p: number; out: number; boxed?: boolean }> = ({ panel, dir, rect, right, p, out, boxed = false }) => {
  if (panel) return <PanelBacking right={right} p={p * (1 - out)} />;
  if (boxed && dir.backing === "box") return null;
  return <SoftBacking rect={rect} p={p * (1 - out)} right={right} strength={0.7} />;
};

const caseOf = (dir: DirSpec, s: string) => (dir.upper ? s.toUpperCase() : s);

// ================================================================== kt-keyword
const Keyword: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, dir, hot, out, ks, panel } = useLook(overlay, accent);
  const text = caseOf(dir, str(overlay.text));
  if (!text) return null;
  const kicker = str(overlay.label);
  const size = sizeFor("keyword", H, dir.cap, ks);
  const least = (scale.keyword.least * H * ks) / dir.cap;
  const fit = fitLines(text, dir.font, dir.weight, size, least, (panel ? 0.36 : 0.46) * W, 2, dir.tracking);
  if (!fit) return null;
  const kSize = sizeFor("kicker", H, GROTESK_CAP, ks);
  const lh = fit.size * 1.06;
  const kickW = kicker ? widthOf(kicker.toUpperCase(), SUBLINE, kSize, 700, 0.2) : 0;
  const barW = dir.id === "doc" ? 22 * k : 0;
  const head = kicker ? kSize + 18 * k : 0;
  const rule = dir.id === "editorial" ? 18 * k : 0;
  const boxPad = dir.id === "kinetic" ? 16 * k : 0;
  const w = Math.max(fit.width + boxPad * 2, kickW) + barW;
  const h = head + rule + fit.lines.length * (lh + boxPad * 1.2);
  const zone = zoneFor(overlay, panel ? "left-panel" : "lower-left", w, h, W, H);
  const r = blockAt(zone, w, h, W, H);
  const right = isRight(zone);
  const align = right ? "right" : "left";
  const p0 = prog(f, 0, 14, S, cubicOut);
  const drift = idle(f, 30 * S, dur) * 6 * k;
  return (
    <AbsoluteFill>
      <Backing panel={panel} dir={dir} rect={r} right={right} p={p0} out={out} boxed />
      <div style={{ position: "absolute", left: r.x, top: r.y - drift, width: r.w, textAlign: align }}>
        {kicker ? (
          dir.id === "kinetic" ? (
            <div style={{ display: "inline-block", marginBottom: 14 * k, padding: `${6 * k}px ${12 * k}px`, background: hot,
              clipPath: `inset(0 ${((1 - prog(f, 0, 10, S, expoOut)) * 100).toFixed(1)}% 0 0)`, opacity: 1 - out }}>
              <span style={{ ...kickerStyle(kSize * 0.92, INK, 0.16) }}>{kicker}</span>
            </div>
          ) : (
            <div style={{ height: kSize, marginBottom: 18 * k }}>
              <KineticLine text={kicker.toUpperCase()} font={SUBLINE} weight={700} size={kSize} tracking={0.2}
                color={dir.id === "doc" ? SOFT_WHITE : hot} preset="track" timing={{ at: 0 }} out={out} align={align}
                shadow={softShadow(k, 0.5)} />
            </div>
          )
        ) : null}
        {dir.id === "editorial" ? (
          <div style={{ position: "relative", height: 3 * k, width: 64 * k, marginBottom: 15 * k, marginLeft: right ? "auto" : 0,
            background: hot, transformOrigin: right ? "right" : "left", borderRadius: 2 * k, overflow: "hidden",
            transform: `scaleX(${(prog(f, 3, 16, S, expoOut) * (1 - out)).toFixed(4)})` }}>
            <Glint p={(f / S - 18) / 20} />
          </div>
        ) : null}
        <div style={{ position: "relative", paddingLeft: !right ? barW : 0, paddingRight: right ? barW : 0 }}>
          {dir.id === "doc" ? (
            <div style={{ position: "absolute", [right ? "right" : "left"]: 0, bottom: 4 * k, width: 6 * k, borderRadius: 3 * k,
              height: (fit.lines.length * lh - 8 * k) * prog(f, 0, 14, S, expoOut) * (1 - out), background: hot,
              boxShadow: `0 0 ${14 * k}px ${rgba(hot, 0.45)}`, overflow: "hidden" }}>
              <Glint p={(f / S - 14) / 22} />
            </div>
          ) : null}
          {fit.lines.map((ln, i) => (
            <div key={i} style={{ position: "relative", marginBottom: boxPad * 1.2 }}>
              {dir.id === "kinetic" ? (
                <div style={{ position: "absolute", top: -boxPad * 0.6, bottom: -boxPad * 0.5, [right ? "right" : "left"]: -boxPad,
                  width: (widthOf(ln, dir.font, fit.size, dir.weight, dir.tracking) + boxPad * 2)
                    * prog(f, 2 + i * 3, 12, S, expoOut), background: CHARCOAL, opacity: 1 - out }} />
              ) : null}
              <KineticLine text={ln} font={dir.font} weight={dir.weight} size={fit.size} tracking={dir.tracking}
                preset={dir.reveal} timing={{ at: 5 + i * (dir.reveal === "focus" ? 6 : 3) }} out={out} align={align}
                accent={hot} shadow={dir.id === "kinetic" ? undefined : softShadow(k, 0.55)} />
            </div>
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== figures
interface Fig { pre: string; value: number; glued: string; unit: string }
const UNIT_GLUE = new Set(["%", "×", "X"]);
/** The figure's parts: "$" before, the value, a glued sign (%, ×, M, B) and a unit word ("ACRE-FT"). */
const figOf = (ov: Overlay): Fig | null => {
  const value = num(ov.value);
  if (value === null) return null;
  const pre = str(ov.prefix) === "$" ? "$" : "";
  let suffix = str(ov.suffix).trim();
  let v = value;
  const up = suffix.toUpperCase();
  if (up === "MILLION" || up === "M") { v = value * 1e6; suffix = ""; }
  else if (up === "BILLION" || up === "B") { v = value * 1e9; suffix = ""; }
  else if (up === "THOUSAND" || up === "K") { v = value * 1e3; suffix = ""; }
  const glued = UNIT_GLUE.has(suffix.toUpperCase()) ? (suffix === "%" ? "%" : "×") : "";
  const unit = glued ? "" : suffix.toUpperCase();
  return { pre, value: v, glued, unit };
};

/** The number partway through its count, as drawn ("$1.2" ... "$1.25M"). */
const figText = (fg: Fig, p: number) => `${fg.pre}${figureAt(fg.value, p)}${formatFigure(fg.value).glued}${fg.glued}`;
const figFinal = (fg: Fig) => `${fg.pre}${formatFigure(fg.value).main}${formatFigure(fg.value).glued}${fg.glued}`;

/** The number itself: counting (tabular), a touch of motion blur while it runs, a settle and one light sweep on landing. */
const Figure: React.FC<{ fg: Fig; size: number; font: string; weight: number; color?: string; at: number; len?: number;
  out: number; align: "left" | "right"; hot: string; k: number; unitSize?: number; unitColor?: string }> =
  ({ fg, size, font, weight, color = WHITE, at, len = 30, out, align, hot, k, unitSize, unitColor = SOFT_WHITE }) => {
    const f = useCurrentFrame();
    const { fps } = useVideoConfig();
    const S = fps / 30;
    const p = prog(f, at, len, S, expoOut);
    const p1 = prog(f + S, at, len, S, expoOut);
    const blur = motionBlur((p1 - p) * size * 1.4, k, 3);
    const shown = figText(fg, p);
    const finalW = widthOf(figFinal(fg), font, size, weight, -0.01);
    const o = prog(f, at - 4, 10, S, cubicOut);
    const st = settle(f, at + len * 0.75, S);
    const style: React.CSSProperties = { fontFamily: font, fontWeight: weight, fontSize: size, lineHeight: 1, color,
      letterSpacing: "-0.01em", fontVariantNumeric: "tabular-nums", fontFeatureSettings: '"tnum" 1', whiteSpace: "nowrap" };
    return (
      <div style={{ display: "flex", alignItems: "baseline", flexDirection: align === "right" ? "row-reverse" : "row",
        gap: 14 * k, opacity: o * (1 - out),
        transform: `translateY(${((1 - o) * 0.12 * size - out * 0.08 * size).toFixed(2)}px) scale(${st.toFixed(4)})`,
        transformOrigin: align === "right" ? "right bottom" : "left bottom" }}>
        <div style={{ position: "relative", width: finalW, textAlign: align }}>
          <div style={{ ...style, textShadow: softShadow(k, 0.55), filter: blur ? `blur(${blur.toFixed(2)}px)` : undefined }}>{shown}</div>
          {/* one light sweep across the digits as the figure lands */}
          <div style={{ ...style, position: "absolute", inset: 0, color: "transparent", WebkitBackgroundClip: "text", backgroundClip: "text",
            backgroundImage: `linear-gradient(105deg, transparent 30%, ${rgba("#ffffff", 0.95)} 46%, ${rgba(hot, 0.9)} 52%, transparent 66%)`,
            backgroundSize: "300% 100%", backgroundPosition: `${(100 - 100 * cubicInOut(clamp01((f / S - at - len * 0.8) / 22))).toFixed(1)}% 0`,
            opacity: f / S > at + len * 0.8 && f / S < at + len * 0.8 + 22 ? 1 : 0 }}>{shown}</div>
        </div>
        {fg.unit ? (
          <div style={{ ...kickerStyle(unitSize || size * 0.3, unitColor, 0.08), fontFamily: GROTESK, fontWeight: 700,
            textShadow: softShadow(k, 0.5), opacity: prog(f, at + 8, 12, S, cubicOut) }}>{fg.unit}</div>
        ) : null}
      </div>
    );
  };

// ================================================================== kt-number
const NumberLook: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, dir, hot, out, ks, panel } = useLook(overlay, accent);
  const fg = figOf(overlay);
  if (!fg) return null;
  const kicker = str(overlay.label) || (str(overlay.text) && str(overlay.text).length <= 28 ? str(overlay.text) : "");
  const context = str(overlay.subtitle);
  const finalText = figFinal(fg);
  let size = sizeFor("hero", H, dir.cap, ks);
  // A short unit rides beside the figure (FT, MI, KM); a long one ("ACRE-FT") goes on its own line under it.
  const beside = fg.unit.length > 0 && fg.unit.length <= 4;
  const under = fg.unit && !beside ? fg.unit : "";
  const figure: Fig = beside ? fg : { ...fg, unit: "" };
  const least = (scale.hero.least * H * ks) / dir.cap;
  const floor = (0.09 * H * ks) / dir.cap;
  const maxW = 0.52 * W;
  const wOf = (s: number) => widthOf(finalText, dir.font, s, 800, -0.01)
    + (beside ? 14 * k + widthOf(fg.unit, GROTESK, s * scale.unit.ofHero, 700, 0.08) : 0);
  while (size > least && wOf(size) > maxW) size *= 0.97;
  while (size > floor && wOf(size) > maxW) size *= 0.97;
  const kSize = sizeFor("kicker", H, GROTESK_CAP, ks);
  const cSize = sizeFor("context", H, GROTESK_CAP, ks);
  const ctx = context ? fitLines(context, INTER, 600, cSize, cSize * 0.85, 0.42 * W, 1) : null;
  const uSize = kSize * 1.15;
  const w = Math.max(wOf(size), kicker ? widthOf(kicker.toUpperCase(), SUBLINE, kSize, 700, 0.2) : 0, ctx ? ctx.width : 0,
    under ? widthOf(under, SUBLINE, uSize, 700, 0.16) : 0);
  const h = (kicker ? kSize + 16 * k : 0) + size * 0.9 + 22 * k + (under ? uSize + 12 * k : 0) + (ctx ? ctx.size * 1.25 : 0);
  const zone = zoneFor(overlay, panel ? "left-panel" : "lower-left", w, h, W, H);
  const r = blockAt(zone, w, h, W, H);
  const right = isRight(zone);
  const align = right ? "right" : "left";
  const drift = idle(f, 40 * S, dur) * 5 * k;
  return (
    <AbsoluteFill>
      <Backing panel={panel} dir={dir} rect={r} right={right} p={prog(f, 0, 14, S, cubicOut)} out={out} />
      <div style={{ position: "absolute", left: r.x, top: r.y - drift, width: r.w, display: "flex", flexDirection: "column",
        alignItems: right ? "flex-end" : "flex-start" }}>
        {kicker ? (
          <div style={{ height: kSize, marginBottom: 16 * k }}>
            <KineticLine text={kicker.toUpperCase()} font={SUBLINE} weight={700} size={kSize} tracking={0.2}
              color={dir.id === "doc" ? SOFT_WHITE : hot} preset="track" timing={{ at: 0 }} out={out} align={align}
              shadow={softShadow(k, 0.5)} />
          </div>
        ) : null}
        <Figure fg={figure} size={size} font={dir.font} weight={dir.id === "editorial" ? 800 : dir.weight + 100} at={6} len={30}
          out={out} align={align} hot={hot} k={k} unitSize={size * scale.unit.ofHero} />
        {under ? (
          <div style={{ marginTop: 10 * k, height: uSize }}>
            <KineticLine text={under} font={SUBLINE} weight={700} size={uSize} tracking={0.16} color={WHITE} preset="track"
              timing={{ at: 14 }} out={out} align={align} shadow={softShadow(k, 0.55)} />
          </div>
        ) : null}
        <div style={{ position: "relative", marginTop: 14 * k, height: (dir.id === "kinetic" ? 8 : 4) * k,
          width: Math.max(90 * k, wOf(size) * 0.34), background: hot, borderRadius: 2 * k, overflow: "hidden",
          transformOrigin: right ? "right" : "left",
          transform: `scaleX(${(prog(f, 18, 18, S, expoOut) * (1 - out)).toFixed(4)})` }}>
          <Glint p={(f / S - 34) / 20} />
        </div>
        {ctx ? (
          <div style={{ marginTop: 14 * k }}>
            <KineticLine text={ctx.lines[0]} font={INTER} weight={600} size={ctx.size} color={SOFT_WHITE} preset="focus"
              timing={{ at: 26, gap: 2 }} out={out} align={align} shadow={softShadow(k, 0.55)} />
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== kt-chip
const Chip: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, dir, hot, out, ks } = useLook(overlay, accent);
  const fg = figOf(overlay);
  if (!fg) return null;
  const label = str(overlay.label) || str(overlay.text);
  const size = sizeFor("chip", H, dir.cap, ks);
  const kSize = sizeFor("kicker", H, GROTESK_CAP, ks) * 0.92;
  const numW = widthOf(figFinal(fg), dir.font, size, 800, -0.01) + (fg.unit ? 12 * k + widthOf(fg.unit, GROTESK, size * 0.4, 700, 0.08) : 0);
  const labW = label ? widthOf(label.toUpperCase(), SUBLINE, kSize, 700, 0.18) : 0;
  const padX = 26 * k, padY = 18 * k;
  const w = Math.max(numW, labW) + padX * 2 + 6 * k;
  const h = (label ? kSize + 12 * k : 0) + size * 0.86 + padY * 2;
  const zone = zoneFor(overlay, "lower-left", w, h, W, H);
  const r = blockAt(zone, w, h, W, H);
  const right = isRight(zone);
  const grow = prog(f, 0, 12, S, expoOut);
  const drift = idle(f, 30 * S, dur) * 4 * k;
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: r.x, top: r.y - drift, width: r.w, height: r.h, borderRadius: 12 * k,
        background: CHARCOAL, backdropFilter: `blur(${(14 * k).toFixed(1)}px)`, WebkitBackdropFilter: `blur(${(14 * k).toFixed(1)}px)`,
        boxShadow: `0 ${16 * k}px ${44 * k}px rgba(0,0,0,.45)`, [right ? "borderRight" : "borderLeft"]: `${6 * k}px solid ${hot}`,
        transformOrigin: right ? "right center" : "left center", transform: `scaleX(${(0.6 + 0.4 * grow).toFixed(4)})`,
        opacity: clamp01(grow * 1.6) * (1 - out), boxSizing: "border-box", padding: `${padY}px ${padX}px`,
        display: "flex", flexDirection: "column", alignItems: right ? "flex-end" : "flex-start" }}>
        {label ? (
          <div style={{ height: kSize, marginBottom: 12 * k }}>
            <KineticLine text={label.toUpperCase()} font={SUBLINE} weight={700} size={kSize} tracking={0.18} color={hot}
              preset="track" timing={{ at: 4 }} out={out} align={right ? "right" : "left"} />
          </div>
        ) : null}
        <Figure fg={fg} size={size} font={dir.font} weight={800} at={5} len={24} out={0} align={right ? "right" : "left"}
          hot={hot} k={k} unitSize={size * 0.4} />
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== kt-percent / kt-progress
const arcPath = (cx: number, cy: number, r: number, a0: number, a1: number) => {
  const p = (a: number) => `${(cx + r * Math.cos(a)).toFixed(2)},${(cy + r * Math.sin(a)).toFixed(2)}`;
  const large = a1 - a0 > Math.PI ? 1 : 0;
  return `M${p(a0)} A${r.toFixed(2)},${r.toFixed(2)} 0 ${large} 1 ${p(a1)}`;
};

/** The size unit: the frame height, or the 16:9 height of a tall frame's width (a short keeps the proportions). */
const unitOf = (W: number, H: number) => Math.min(H, (W * 9) / 16);
/** A ring's diameter (typeScale "ringD": 18 % of the height, 16-20 %) and the share of the frame its context may take. */
const ringD = (W: number, H: number, ks: number) => scale.ringD.share * unitOf(W, H) * ks;
const SIDE_W = 0.28;

/** The largest font (from `size` down to 60 %) at which `text` fits `maxW`. */
const fitSize = (text: string, font: string, weight: number, size: number, maxW: number, tracking = -0.02) => {
  let s = size;
  while (s > size * 0.6 && widthOf(text, font, s, weight, tracking) > maxW) s *= 0.96;
  return s;
};

/** The side column of a ring look: the kicker and ONE line of context, beside the ring. */
const SideText: React.FC<{ kicker: string; context: string; hot: string; dir: DirSpec; k: number; H: number; W: number;
  ks: number; out: number; align: "left" | "right"; at: number }> = ({ kicker, context, hot, dir, k, H, W, ks, out, align, at }) => {
  const kSize = sizeFor("kicker", H, GROTESK_CAP, ks);
  const cSize = sizeFor("context", H, GROTESK_CAP, ks) * 1.12;
  const ctx = context ? fitLines(context, INTER, 600, cSize, cSize * 0.8, SIDE_W * W, 1) : null;
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: align === "right" ? "flex-end" : "flex-start" }}>
      {kicker ? (
        <div style={{ height: kSize, marginBottom: 14 * k }}>
          <KineticLine text={kicker.toUpperCase()} font={SUBLINE} weight={700} size={kSize} tracking={0.2}
            color={dir.id === "doc" ? SOFT_WHITE : hot} preset="track" timing={{ at }} out={out} align={align} shadow={softShadow(k, 0.5)} />
        </div>
      ) : null}
      {ctx ? (
        <KineticLine text={ctx.lines[0]} font={INTER} weight={600} size={ctx.size} color={WHITE} preset="focus"
          timing={{ at: at + 6, gap: 2 }} out={out} align={align} shadow={softShadow(k, 0.55)} />
      ) : null}
    </div>
  );
};

/**
 * One line of context beside a ring: the whole phrase when it fits (the type may shrink a little), else the
 * phrase up to a natural break ("full - the lowest since..." -> "full"), else nothing - never a phrase cut
 * off mid-thought ("the lowest since it first").
 */
const oneLine = (context: string, W: number, H: number, ks: number) => {
  if (!context) return "";
  const cSize = sizeFor("context", H, GROTESK_CAP, ks) * 1.12;
  const fits = (s: string) => Boolean(fitLines(s, INTER, 600, cSize, cSize * 0.78, SIDE_W * W, 1));
  if (fits(context)) return context;
  const parts = context.split(/\s+[-–—:]\s+|[,;]\s+|\s+\(/);
  for (let n = parts.length - 1; n >= 1; n--) {
    const head = parts.slice(0, n).join(", ").trim();
    if (head.length >= 3 && fits(head)) return head;
  }
  return "";
};

const sideWidth = (kicker: string, context: string, k: number, H: number, W: number, ks: number) => {
  const kSize = sizeFor("kicker", H, GROTESK_CAP, ks);
  const cSize = sizeFor("context", H, GROTESK_CAP, ks) * 1.12;
  const ctx = context ? fitLines(context, INTER, 600, cSize, cSize * 0.8, SIDE_W * W, 1) : null;
  return Math.max(kicker ? widthOf(kicker.toUpperCase(), SUBLINE, kSize, 700, 0.2) : 0, ctx ? ctx.width : 0);
};

const Percent: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, dir, hot, out, ks, panel } = useLook(overlay, accent);
  const value = num(overlay.value);
  if (value === null) return null;
  const total = num(overlay.total);
  const share = clamp01(total && total > 0 ? value / total : value / 100);
  const kicker = str(overlay.label) || (str(overlay.text).length <= 28 ? str(overlay.text) : "");
  const context = oneLine(str(overlay.subtitle), W, H, ks);
  const U = unitOf(W, H);
  const D = ringD(W, H, ks);
  const stroke = (dir.id === "kinetic" ? 0.022 : 0.016) * U * ks;
  const R = D / 2 - stroke / 2 - 2 * k;
  const gap = 32 * k;
  const sideW = sideWidth(kicker, context, k, H, W, ks);
  const w = D + (sideW ? gap + sideW : 0);
  const h = D;
  const zone = zoneFor(overlay, panel ? "left-panel" : "lower-left", w, h, W, H);
  const r = blockAt(zone, w, h, W, H);
  const right = isRight(zone);
  const enter = prog(f, 0, 14, S, (u) => 1 - (1 - u) ** 3);
  const track = prog(f, 0, 16, S, cubicInOut);
  const fill = prog(f, 8, 34, S, cubicInOut);
  const land = 8 + 34;
  const glow = clamp01((f / S - land) / 10) * (1 - clamp01((f / S - land - 10) / 24)) * 0.7 + (f / S > land ? 0.18 : 0);
  const a0 = -Math.PI / 2;
  const a1 = a0 + Math.PI * 2 * share * fill;
  const head = [D / 2 + R * Math.cos(a1), D / 2 + R * Math.sin(a1)];
  // the number inside the ring: as large as fits inside it (typeScale "ringNumber", capitals 5 % of the height)
  const finalText = total ? `${formatFigure(value).main}/${formatFigure(total).main}` : `${formatFigure(value).main}%`;
  const inner = D - 2 * stroke - 14 * k;
  const numSize = fitSize(finalText, dir.font, 800, (scale.ringNumber.share * U * ks) / dir.cap, inner * 0.78);
  const fg: Fig = { pre: "", value, glued: total ? "" : "%", unit: "" };
  const shown = `${figureAt(value, fill)}${fg.glued}`;
  const drift = idle(f, 40 * S, dur);
  const ringX = right ? r.x + r.w - D : r.x;
  return (
    <AbsoluteFill>
      <Backing panel={panel} dir={dir} rect={r} right={right} p={enter} out={out} />
      <div style={{ position: "absolute", left: ringX, top: r.y - drift * 4 * k, width: D, height: D, opacity: enter * (1 - out),
        transform: `scale(${(0.86 + 0.14 * enter + out * 0.03).toFixed(4)}) rotate(${(drift * 2).toFixed(3)}deg)` }}>
        <svg width={D} height={D} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          {dir.id === "kinetic" ? <circle cx={D / 2} cy={D / 2} r={D / 2 + 2 * k} fill={CHARCOAL} /> : (
            <circle cx={D / 2} cy={D / 2} r={R + stroke * 0.5} fill="rgba(6,8,11,0.5)" />
          )}
          <circle cx={D / 2} cy={D / 2} r={R} fill="none" stroke="rgba(255,255,255,0.18)" strokeWidth={stroke}
            pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - track} transform={`rotate(-90 ${D / 2} ${D / 2})`} />
          {fill > 0.001 ? (
            <>
              <path d={arcPath(D / 2, D / 2, R, a0, Math.max(a0 + 0.001, a1))} fill="none" stroke={hot} strokeWidth={stroke * 1.9}
                strokeLinecap="round" opacity={glow * 0.5} style={{ filter: `blur(${(8 * k).toFixed(1)}px)` }} />
              <path d={arcPath(D / 2, D / 2, R, a0, Math.max(a0 + 0.001, a1))} fill="none" stroke={hot} strokeWidth={stroke}
                strokeLinecap="round" />
              <circle cx={head[0]} cy={head[1]} r={stroke * 0.32} fill="#fff" opacity={fill < 1 ? 0.95 : 0.6} />
            </>
          ) : null}
        </svg>
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{ fontFamily: dir.font, fontWeight: 800, fontSize: numSize, color: WHITE, letterSpacing: "-0.02em",
            fontVariantNumeric: "tabular-nums", fontFeatureSettings: '"tnum" 1', lineHeight: 1, textShadow: softShadow(k, 0.5),
            transform: `scale(${settle(f, land, S).toFixed(4)})`, opacity: prog(f, 4, 10, S, cubicOut), whiteSpace: "nowrap" }}>
            {total ? `${figureAt(value, fill)}` : shown}
            {total ? <span style={{ fontSize: numSize * 0.55, color: SOFT_WHITE, fontWeight: 700 }}>{`/${figureAt(total, 1)}`}</span> : null}
          </div>
        </div>
      </div>
      {sideW ? (
        <div style={{ position: "absolute", top: r.y + D / 2 - drift * 4 * k, transform: "translateY(-50%)",
          [right ? "right" : "left"]: right ? W - (ringX - gap) : ringX + D + gap }}>
          <SideText kicker={kicker} context={context} hot={hot} dir={dir} k={k} H={H} W={W} ks={ks} out={out}
            align={right ? "right" : "left"} at={10} />
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

/** "1 in 3", "3 of 4", "2 out of 5": the words the narration joined the two figures with (overlay.text), else "of". */
const joinerOf = (ov: Overlay) => {
  const t = str(ov.text).toLowerCase();
  return t === "in" || t === "out of" || t === "of" ? t : "of";
};

const Progress: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, dir, hot, out, ks, panel } = useLook(overlay, accent);
  const value = num(overlay.value);
  if (value === null) return null;
  const total = num(overlay.total);
  const share = clamp01(total && total > 0 ? value / total : value / 100);
  const kicker = str(overlay.label);
  const context = oneLine(str(overlay.subtitle), W, H, ks);
  const U = unitOf(W, H);
  const size = (scale.ringNumber.share * 1.15 * U * ks) / dir.cap;
  const joiner = joinerOf(overlay);
  // "1 in 3" / "3 of 4" of a few (at most 10): that many dots, the share lit one by one; else a bar
  const dots = total !== null && Number.isInteger(total) && total >= 2 && total <= 10 && Number.isInteger(value) && value >= 1
    && value < total;
  const barW = 0.26 * W, barH = 0.016 * U * ks;
  const dotD = dots ? Math.min(0.062 * U * ks, (barW - (total! - 1) * 14 * k) / total!) : 0;
  const dotGap = dots ? Math.min(18 * k, (barW - total! * dotD) / Math.max(1, total! - 1)) : 0;
  const rowW = dots ? total! * dotD + (total! - 1) * dotGap : barW;
  const kSize = sizeFor("kicker", H, GROTESK_CAP, ks);
  const cSize = sizeFor("context", H, GROTESK_CAP, ks) * 1.08;
  const finalLabel = total ? `${formatFigure(value).main} ${joiner} ${formatFigure(total).main}` : `${formatFigure(value).main}%`;
  const labelW = widthOf(finalLabel, dir.font, size, 800, -0.015);
  const w = Math.max(rowW, labelW, kicker ? widthOf(kicker.toUpperCase(), SUBLINE, kSize, 700, 0.2) : 0);
  const rowH = dots ? dotD : barH;
  const h = (kicker ? kSize + 16 * k : 0) + size + 20 * k + rowH + (context ? cSize * 1.6 : 0);
  const zone = zoneFor(overlay, panel ? "left-panel" : "lower-left", w, h, W, H);
  const r = blockAt(zone, w, h, W, H);
  const right = isRight(zone);
  const align = right ? "right" : "left";
  const fill = prog(f, 10, 32, S, cubicInOut);
  const drift = idle(f, 40 * S, dur) * 5 * k;
  const label = total ? `${figureAt(value, fill)} ${joiner} ${figureAt(total, 1)}` : `${figureAt(value, fill)}%`;
  return (
    <AbsoluteFill>
      <Backing panel={panel} dir={dir} rect={r} right={right} p={prog(f, 0, 14, S, cubicOut)} out={out} />
      <div style={{ position: "absolute", left: r.x, top: r.y - drift, width: r.w, display: "flex", flexDirection: "column",
        alignItems: right ? "flex-end" : "flex-start" }}>
        {kicker ? (
          <div style={{ height: kSize, marginBottom: 16 * k }}>
            <KineticLine text={kicker.toUpperCase()} font={SUBLINE} weight={700} size={kSize} tracking={0.2}
              color={dir.id === "doc" ? SOFT_WHITE : hot} preset="track" timing={{ at: 0 }} out={out} align={align} />
          </div>
        ) : null}
        <div style={{ fontFamily: dir.font, fontWeight: 800, fontSize: size, color: WHITE, lineHeight: 1, letterSpacing: "-0.015em",
          fontVariantNumeric: "tabular-nums", textShadow: softShadow(k, 0.55), opacity: prog(f, 4, 10, S, cubicOut) * (1 - out),
          transform: `scale(${settle(f, 42, S).toFixed(4)})`, transformOrigin: right ? "right bottom" : "left bottom",
          whiteSpace: "nowrap" }}>{label}</div>
        {dots ? (
          <div style={{ marginTop: 20 * k, display: "flex", gap: dotGap, flexDirection: right ? "row-reverse" : "row" }}>
            {Array.from({ length: total! }, (_, i) => {
              const on = i < value;
              const pop = prog(f, 4 + i * 2, 12, S, (u) => backOut(u, 1.5)) * (1 - clamp01(out * 1.4 - (i / total!) * 0.4));
              const lit = on ? prog(f, 16 + i * 5, 10, S, cubicOut) : 0;
              return (
                <div key={i} style={{ width: dotD, height: dotD, borderRadius: "50%", boxSizing: "border-box",
                  border: `${(2.5 * k).toFixed(1)}px solid ${on && lit > 0 ? hot : "rgba(255,255,255,0.42)"}`,
                  background: on ? rgba(hot, 0.92 * lit) : "rgba(10,12,16,0.35)", opacity: pop,
                  transform: `scale(${(0.6 + 0.4 * pop + 0.08 * Math.sin(clamp01((f / S - 16 - i * 5) / 10) * Math.PI) * (on ? 1 : 0)).toFixed(4)})`,
                  boxShadow: on && lit > 0 ? `0 0 ${(14 * lit * k).toFixed(1)}px ${rgba(hot, 0.5 * lit)}` : undefined }} />
              );
            })}
          </div>
        ) : (
          <div style={{ position: "relative", marginTop: 20 * k, width: barW, height: barH, borderRadius: barH,
            background: "rgba(255,255,255,0.16)", overflow: "hidden", opacity: 1 - out,
            clipPath: `inset(0 ${((1 - prog(f, 2, 14, S, expoOut)) * 100).toFixed(1)}% 0 0)` }}>
            <div style={{ position: "absolute", top: 0, bottom: 0, [right ? "right" : "left"]: 0, width: `${(share * fill * 100).toFixed(2)}%`,
              background: `linear-gradient(90deg, ${rgba(hot, 0.85)}, ${hot})`, borderRadius: barH, overflow: "hidden" }}>
              <Glint p={(f / S - 42) / 22} />
            </div>
          </div>
        )}
        {context ? (
          <div style={{ marginTop: 14 * k }}>
            <KineticLine text={context} font={INTER} weight={600} size={cSize} color={SOFT_WHITE} preset="focus"
              timing={{ at: 24, gap: 2 }} out={out} align={align} shadow={softShadow(k, 0.55)} />
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== kt-multiplier
const Multiplier: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, dir, hot, out, ks, panel } = useLook(overlay, accent);
  const value = num(overlay.value);
  if (value === null || value <= 0) return null;
  const kicker = str(overlay.label) || (str(overlay.text).length <= 28 ? str(overlay.text) : "");
  const context = oneLine(str(overlay.subtitle), W, H, ks);
  const U = unitOf(W, H);
  const D = ringD(W, H, ks);
  const tickLen = 0.022 * U * ks;
  const R = D / 2 - tickLen - 6 * k;
  const gap = 32 * k;
  const sideW = sideWidth(kicker, context, k, H, W, ks);
  const w = D + (sideW ? gap + sideW : 0);
  const zone = zoneFor(overlay, panel ? "left-panel" : "lower-left", w, D, W, H);
  const r = blockAt(zone, w, D, W, H);
  const right = isRight(zone);
  const enter = prog(f, 0, 14, S, cubicOut);
  const count = prog(f, 8, 34, S, cubicInOut);
  const land = 42;
  // one tick a unit for 5x-24x (15 ticks light for "15 times"); a smaller or a larger figure fills a fine ring
  const n = value >= 5 && value <= 24 && Math.abs(value - Math.round(value)) < 1e-6 ? Math.round(value) : 0;
  const lit = n ? count * n : 0;
  const close = prog(f, land - 2, 14, S, cubicInOut);
  const shown = value < 10 && !Number.isInteger(value) ? (value * count).toFixed(1) : figureAt(value, count);
  const finalText = `${value < 10 && !Number.isInteger(value) ? value.toFixed(1) : formatFigure(value).main}×`;
  const numSize = fitSize(finalText, dir.font, 800, (scale.ringNumber.share * U * ks) / dir.cap, (2 * R - 16 * k) * 0.8);
  const drift = idle(f, 40 * S, dur);
  const ringX = right ? r.x + r.w - D : r.x;
  const ticks = n || 36;
  return (
    <AbsoluteFill>
      <Backing panel={panel} dir={dir} rect={r} right={right} p={enter} out={out} />
      <div style={{ position: "absolute", left: ringX, top: r.y - drift * 4 * k, width: D, height: D, opacity: enter * (1 - out),
        transform: `scale(${(0.86 + 0.14 * enter + 0.03 * out).toFixed(4)})` }}>
        <svg width={D} height={D} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          <circle cx={D / 2} cy={D / 2} r={D / 2 - 2 * k} fill={dir.id === "kinetic" ? CHARCOAL : "rgba(6,8,11,0.5)"} />
          {Array.from({ length: ticks }, (_, i) => {
            const a = -Math.PI / 2 + (i / ticks) * Math.PI * 2;
            const on = n ? clamp01(lit - i) : clamp01(count * ticks - i);
            const r0 = R, r1 = R + tickLen;
            return (
              <line key={i} x1={D / 2 + r0 * Math.cos(a)} y1={D / 2 + r0 * Math.sin(a)} x2={D / 2 + r1 * Math.cos(a)}
                y2={D / 2 + r1 * Math.sin(a)} stroke={on > 0 ? hot : "rgba(255,255,255,0.22)"} strokeWidth={(n ? 6 : 3.5) * k}
                strokeLinecap="round" opacity={0.35 + 0.65 * on} />
            );
          })}
          <circle cx={D / 2} cy={D / 2} r={D / 2 - 2.5 * k} fill="none" stroke={hot} strokeWidth={2.5 * k} pathLength={1}
            strokeDasharray="1 1" strokeDashoffset={1 - close} transform={`rotate(-90 ${D / 2} ${D / 2})`} opacity={0.9} />
        </svg>
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{ fontFamily: dir.font, fontWeight: 800, fontSize: numSize, color: WHITE, letterSpacing: "-0.02em", lineHeight: 1,
            fontVariantNumeric: "tabular-nums", textShadow: softShadow(k, 0.5), transform: `scale(${settle(f, land, S).toFixed(4)})`,
            opacity: prog(f, 4, 10, S, cubicOut), whiteSpace: "nowrap" }}>
            {shown}<span style={{ color: hot, fontWeight: 700, marginLeft: 2 * k }}>×</span>
          </div>
        </div>
      </div>
      {sideW ? (
        <div style={{ position: "absolute", top: r.y + D / 2 - drift * 4 * k, transform: "translateY(-50%)",
          [right ? "right" : "left"]: right ? W - (ringX - gap) : ringX + D + gap }}>
          <SideText kicker={kicker} context={context} hot={hot} dir={dir} k={k} H={H} W={W} ks={ks} out={out}
            align={right ? "right" : "left"} at={10} />
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== kt-compare
const Compare: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, dir, hot, out, ks, panel } = useLook(overlay, accent);
  const rows = (Array.isArray(overlay.items) ? overlay.items : [])
    .map((it) => ({ label: str(it?.label), value: num(it?.value) }))
    .filter((x): x is { label: string; value: number } => Boolean(x.label) && x.value !== null && x.value >= 0).slice(0, 3);
  if (rows.length < 2) return null;
  const kicker = str(overlay.text) || str(overlay.label);
  const context = str(overlay.subtitle);
  const suffix = str(overlay.suffix);
  const times = suffix === "×" || suffix.toUpperCase() === "X";
  const max = Math.max(...rows.map((x) => x.value), 1e-9);
  const kSize = sizeFor("kicker", H, GROTESK_CAP, ks);
  const lSize = kSize * 1.05;
  const vSize = sizeFor("chip", H, dir.cap, ks) * 0.9;
  const barMax = 0.34 * W;
  const barH = 0.022 * H * ks;
  const rowH = lSize + 12 * k + Math.max(barH, vSize * 0.8) + 26 * k;
  const cSize = sizeFor("context", H, GROTESK_CAP, ks);
  const valW = Math.max(...rows.map((x) => widthOf(times ? `${formatFigure(x.value).main}×` : `${formatFigure(x.value).main}${formatFigure(x.value).glued}`, dir.font, vSize, 800)));
  const w = barMax + 24 * k + valW;
  const h = (kicker ? kSize + 22 * k : 0) + rows.length * rowH + (context ? cSize * 1.6 : 0);
  const zone = zoneFor(overlay, panel ? "left-panel" : "lower-left", w, h, W, H);
  const r = blockAt(zone, w, h, W, H);
  const right = isRight(zone);
  const align = right ? "right" : "left";
  const drift = idle(f, 40 * S, dur) * 5 * k;
  const big = rows.reduce((a, x, i) => (x.value > rows[a].value ? i : a), 0);
  return (
    <AbsoluteFill>
      <Backing panel={panel} dir={dir} rect={r} right={right} p={prog(f, 0, 14, S, cubicOut)} out={out} />
      <div style={{ position: "absolute", left: r.x, top: r.y - drift, width: r.w, display: "flex", flexDirection: "column",
        alignItems: right ? "flex-end" : "flex-start" }}>
        {kicker ? (
          <div style={{ height: kSize, marginBottom: 22 * k }}>
            <KineticLine text={kicker.toUpperCase()} font={SUBLINE} weight={700} size={kSize} tracking={0.2}
              color={dir.id === "doc" ? SOFT_WHITE : hot} preset="track" timing={{ at: 0 }} out={out} align={align} />
          </div>
        ) : null}
        {rows.map((row, i) => {
          const at = 6 + i * 10;
          const g = prog(f, at, 26, S, cubicInOut);
          const len = Math.max(10 * k, (row.value / max) * barMax) * g;
          const col = i === big ? hot : "rgba(255,255,255,0.78)";
          const val = times ? `${(row.value * g).toFixed(Number.isInteger(row.value) ? 0 : 1)}×` : figText({ pre: "", value: row.value, glued: "", unit: "" }, g);
          return (
            <div key={i} style={{ marginBottom: 26 * k, display: "flex", flexDirection: "column", alignItems: right ? "flex-end" : "flex-start",
              opacity: prog(f, at - 2, 10, S, cubicOut) * (1 - out) }}>
              <div style={{ ...kickerStyle(lSize, SOFT_WHITE, 0.16), marginBottom: 12 * k, textShadow: softShadow(k, 0.5) }}>{row.label}</div>
              <div style={{ display: "flex", alignItems: "center", gap: 24 * k, flexDirection: right ? "row-reverse" : "row" }}>
                <div style={{ position: "relative", width: len, height: barH, borderRadius: barH / 2, background: col, overflow: "hidden",
                  boxShadow: i === big ? `0 0 ${18 * k}px ${rgba(hot, 0.4)}` : undefined }}>
                  {i === big ? <Glint p={(f / S - at - 28) / 20} /> : null}
                </div>
                <div style={{ fontFamily: dir.font, fontWeight: 800, fontSize: vSize, color: i === big ? WHITE : SOFT_WHITE, lineHeight: 1,
                  fontVariantNumeric: "tabular-nums", textShadow: softShadow(k, 0.5), whiteSpace: "nowrap" }}>{val}</div>
              </div>
            </div>
          );
        })}
        {context ? (
          <KineticLine text={context} font={INTER} weight={600} size={cSize} color={SOFT_WHITE} preset="focus"
            timing={{ at: 6 + rows.length * 10 + 10, gap: 2 }} out={out} align={align} shadow={softShadow(k, 0.55)} />
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== dates, years, times
// The date family (kt-date, kt-date-card, kt-date-line, kt-date-badge, kt-year, kt-time, kt-time-clock)
// lives in LibKtDates.tsx since 2026-10-06 (the owner: "when dates are mentioned it barely shows them").

// ================================================================== kt-lower-third
const LowerThird: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, dir, hot, out, ks, panel } = useLook(overlay, accent);
  const name = caseOf(dir, str(overlay.text));
  if (!name) return null;
  const role = str(overlay.subtitle) || str(overlay.label);
  const size = sizeFor("name", H, dir.cap, ks);
  const rSize = sizeFor("role", H, GROTESK_CAP, ks);
  const fit = fitLines(name, dir.font, dir.weight, size, size * 0.8, 0.5 * W, 1, dir.tracking);
  if (!fit) return null;
  const roleFit = role ? fitLines(role, INTER, 500, rSize, rSize * 0.85, 0.5 * W, 1) : null;
  const bar = dir.id === "doc" ? 22 * k : 0;
  const w = Math.max(fit.width, roleFit ? roleFit.width : 0) + bar + (dir.id === "kinetic" ? 32 * k : 0);
  const h = fit.size * 1.1 + (roleFit ? roleFit.size * 1.5 : 0) + 10 * k;
  const zone = zoneFor(overlay, "lower-left", w, h, W, H);
  const r = blockAt(zone, w, h, W, H);
  const right = isRight(zone);
  const align = right ? "right" : "left";
  const drift = idle(f, 30 * S, dur) * 3 * k;
  return (
    <AbsoluteFill>
      <Backing panel={panel} dir={dir} rect={r} right={right} p={prog(f, 0, 14, S, cubicOut)} out={out} />
      <div style={{ position: "absolute", left: r.x, top: r.y - drift, width: r.w, textAlign: align,
        paddingLeft: right ? 0 : bar, paddingRight: right ? bar : 0, boxSizing: "border-box" }}>
        {dir.id === "doc" ? (
          <div style={{ position: "absolute", [right ? "right" : "left"]: 0, top: 4 * k, width: 6 * k, borderRadius: 3 * k,
            height: (h - 8 * k) * prog(f, 0, 14, S, expoOut) * (1 - out), background: hot }} />
        ) : null}
        <div style={{ position: "relative" }}>
          {dir.id === "kinetic" ? (
            <div style={{ position: "absolute", top: -8 * k, bottom: -6 * k, [right ? "right" : "left"]: -16 * k, opacity: 1 - out,
              width: (fit.width + 32 * k) * prog(f, 2, 12, S, expoOut), background: CHARCOAL }} />
          ) : null}
          <KineticLine text={fit.lines[0]} font={dir.font} weight={dir.weight} size={fit.size} tracking={dir.tracking}
            preset={dir.reveal} timing={{ at: 4 }} out={out} align={align} accent={hot}
            shadow={dir.id === "kinetic" ? undefined : softShadow(k, 0.55)} />
        </div>
        {roleFit ? (
          <div style={{ marginTop: 10 * k, display: "flex", justifyContent: right ? "flex-end" : "flex-start", gap: 12 * k, alignItems: "center" }}>
            {dir.id === "editorial" ? <div style={{ width: 28 * k * prog(f, 10, 14, S, expoOut), height: 3 * k, background: hot }} /> : null}
            <KineticLine text={roleFit.lines[0]} font={INTER} weight={500} size={roleFit.size} color={SOFT_WHITE} preset="focus"
              timing={{ at: 12, gap: 2 }} out={out} align={align} shadow={softShadow(k, 0.55)} />
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== kt-statement
/**
 * A line of the narration typed on (the typing contract: frame 6 on, 2 frames a
 * character up to 48 characters, else 1 - the planner's "keys" sound follows it),
 * in the text face over a soft shade, low left, up to three lines, an accent
 * caret that rests after the last letter; an optional kicker ("THE QUESTION").
 */
const Statement: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, dir, hot, out, ks, panel } = useLook(overlay, accent);
  const raw = str(overlay.text).replace(/^[\s"'“”‘’«»]+|[\s"'“”‘’«»]+$/g, "");
  if (!raw) return null;
  const quoted = /quote/i.test(str(overlay.variant)) || /^[“"]/.test(str(overlay.text));
  const kicker = str(overlay.label) || (/\?\s*$/.test(raw) ? "The question" : "");
  const font = dir.id === "kinetic" ? dir.font : GROTESK;
  const weight = dir.id === "kinetic" ? 700 : 600;
  const size = sizeFor("statement", H, GROTESK_CAP, ks);
  const fit = fitLines(raw, font, weight, size, (scale.statement.least * H * ks) / GROTESK_CAP, (panel ? 0.38 : 0.5) * W, 3, -0.005);
  if (!fit) return null;
  const kSize = sizeFor("kicker", H, GROTESK_CAP, ks);
  const lh = fit.size * 1.22;
  const w = Math.max(fit.width, kicker ? widthOf(kicker.toUpperCase(), SUBLINE, kSize, 700, 0.2) : 0) + (quoted ? 0 : 0);
  const h = (kicker ? kSize + 18 * k : 0) + fit.lines.length * lh;
  const zone = zoneFor(overlay, panel ? "left-panel" : "lower-left", w, h, W, H);
  const r = blockAt(zone, w, h, W, H);
  const right = isRight(zone);
  const align = right ? "right" : "left";
  const f30 = f / S;
  const joined = fit.lines.join(" ");
  const shown = joined.slice(0, typedAt(Math.floor(f30), joined, joined.length));
  const done = typingEnds(joined);
  let left = shown;
  const drift = idle(f, done * S, dur) * 4 * k;
  const caretOn = f30 < done + 1 || Math.floor((f30 - done) / 16) % 2 === 0;
  return (
    <AbsoluteFill style={{ opacity: 1 - out, transform: `translateY(${(-out * 8 * k).toFixed(2)}px)`,
      filter: out > 0 ? `blur(${(out * 4 * k).toFixed(2)}px)` : undefined }}>
      <Backing panel={panel} dir={dir} rect={r} right={right} p={prog(f, 0, 12, S, cubicOut)} out={0} />
      <div style={{ position: "absolute", left: r.x, top: r.y - drift, width: r.w, textAlign: align }}>
        {kicker ? (
          <div style={{ height: kSize, marginBottom: 18 * k }}>
            <KineticLine text={kicker.toUpperCase()} font={SUBLINE} weight={700} size={kSize} tracking={0.2}
              color={dir.id === "doc" ? SOFT_WHITE : hot} preset="track" timing={{ at: 0 }} out={0} align={align} />
          </div>
        ) : null}
        {fit.lines.map((ln, i) => {
          const part = left.slice(0, ln.length);
          left = left.slice(ln.length + 1);
          const last = part.length > 0 && (left.length === 0 || i === fit.lines.length - 1) && part.length <= ln.length;
          return (
            <div key={i} style={{ position: "relative", height: lh, fontFamily: font, fontWeight: weight, fontSize: fit.size,
              lineHeight: `${lh}px`, letterSpacing: "-0.005em", color: WHITE, whiteSpace: "pre", textShadow: softShadow(k, 0.6) }}>
              {dir.id === "kinetic" && part ? (
                <div style={{ position: "absolute", top: lh * 0.08, bottom: lh * 0.04, [right ? "right" : "left"]: -12 * k,
                  width: widthOf(part, font, fit.size, weight, -0.005) + 24 * k, background: CHARCOAL }} />
              ) : null}
              <span style={{ position: "relative" }}>{part}</span>
              {last && caretOn ? (
                <span style={{ position: "relative", display: "inline-block", width: 4 * k, height: fit.size * 0.86, marginLeft: 6 * k,
                  verticalAlign: "-0.1em", background: hot, borderRadius: 2 * k }} />
              ) : null}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "kt-keyword": guard(Keyword),
  "kt-number": guard(NumberLook),
  "kt-chip": guard(Chip),
  "kt-percent": guard(Percent),
  "kt-progress": guard(Progress),
  "kt-multiplier": guard(Multiplier),
  "kt-compare": guard(Compare),
  "kt-lower-third": guard(LowerThird),
  "kt-statement": guard(Statement),
};

export { DIRECTIONS, sineInOut, isUpper };
