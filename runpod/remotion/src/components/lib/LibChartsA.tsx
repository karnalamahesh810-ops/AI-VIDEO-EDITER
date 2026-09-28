import React from "react";
import { AbsoluteFill, Easing, interpolate, interpolateColors, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY, LABEL } from "../fonts";
import type { Overlay, OverlayItem } from "../../types";
import { Odometer, Scrim, formatValue, lines, ramp, useHold, useK } from "../pro/ProGraphics";

/**
 * Charts I (family "ca-"): ten data cards in the pro look. Every one starts
 * with the Scrim (footage darkened behind the chart; nothing when the chart is
 * a full-screen scene), lands its first marks inside 0.3-0.7 s, holds with a
 * slow push, and leaves in the last ~14 frames with its own exit (bars retract,
 * rings unwind, cells flip away) while every line of text drops out of its mask.
 *
 *   ca-bar-race        bars grow and overtake each other, rows re-sorting live
 *   ca-stacked-column  a 3D column built from share blocks dropping onto a stack
 *   ca-grouped-bars    then (hatched outline drawing on) vs now (solid) per label
 *   ca-lollipop        stems shoot out, heads pop with a shock ring, an AVG line
 *   ca-dot-plot        one ruler, dots sliding along it with comet trails
 *   ca-waterfall       a running total stepping up (green) and down (red)
 *   ca-bullet          value bar racing toward a dropped target marker over bands
 *   ca-radial-bars     concentric 270° bars sweeping, values riding the tips
 *   ca-heat-strip      year cells flipping up in a wave, coloured by intensity
 *   ca-histogram       dense bins rising in a wave, one called out
 *
 * Deterministic (no Math.random / Date), 1080p-referenced sizes times k.
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;
type Num = { label: string; value: number; text?: string; suffix?: string; prefix?: string };

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const expoOut = Easing.bezier(0.16, 1, 0.3, 1);
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const exitEase = Easing.bezier(0.7, 0, 0.84, 0);
const RED = "#ff3b30";
const GREEN = "#27d17f";
const CYAN = "#53c8ff";
const INK = "#0c0c0f";

// ------------------------------------------------------------------ data helpers
/** A number from a number or a numeric string ("27%", "1,234", "−8"). */
const toNum = (raw: unknown): number => {
  if (typeof raw === "number") return raw;
  if (typeof raw === "string") {
    const m = /-?\d[\d,]*(?:\.\d+)?|-?\.\d+/.exec(raw.replace(/−/g, "-"));
    return m ? Number(m[0].replace(/,/g, "")) : NaN;
  }
  return NaN;
};

/** The items that carry a finite value, at most `max` of them. */
const nums = (items: OverlayItem[] | undefined, max: number): Num[] => {
  const out: Num[] = [];
  if (!Array.isArray(items)) return out;
  for (const it of items) {
    if (!it || typeof it !== "object") continue;
    const raw = (it as { value?: unknown }).value;
    const v = raw === null || raw === undefined || raw === "" ? NaN : toNum(raw);
    if (!Number.isFinite(v)) continue;
    const ex = it as OverlayItem & { suffix?: unknown; prefix?: unknown };
    out.push({
      label: String((it as { label?: unknown }).label ?? "").trim(),
      value: v,
      text: typeof it.text === "string" ? it.text : undefined,
      suffix: typeof ex.suffix === "string" ? ex.suffix : undefined,
      prefix: typeof ex.prefix === "string" ? ex.prefix : undefined,
    });
    if (out.length >= max) break;
  }
  return out;
};

const units = (ov: Overlay, items: Num[]) => {
  const suffix = String(ov.suffix || items.find((i) => i.suffix)?.suffix || "").trim();
  const prefix = String(ov.prefix || items.find((i) => i.prefix)?.prefix || "").trim();
  return { suffix, prefix, pct: suffix === "%" };
};
/** The suffix as drawn after a number: "%" tight, a unit after a space. */
const tail = (s: string) => (!s ? "" : s === "%" ? "%" : ` ${s}`);
/** Upper case of a text field that may arrive as a number or be missing (never throws). */
const cap = (s?: unknown) => (typeof s === "string" ? s : s === null || s === undefined ? "" : String(s)).toUpperCase();
const fmt = (v: number) => formatValue(v).text;
/**
 * The decimals a value needs: at most 2 below 10, 1 below 100, none above, ignoring float noise
 * (1.04 stays "1.04" where formatValue would print "1.0"; 0.30000000000000004 is "0.3").
 */
const decOf = (v: number) => {
  const a = Math.abs(v);
  if (!Number.isFinite(a) || a >= 100) return 0;
  const most = a >= 10 ? 1 : 2;
  for (let d = 0; d < most; d++) {
    const m = a * Math.pow(10, d);
    if (Math.abs(m - Math.round(m)) < 1e-6 * Math.max(1, m)) return d;
  }
  return most;
};
const fmtD = (v: number, d: number, grouping = true) => {
  if (!Number.isFinite(v)) return "";
  const x = Math.abs(v) < 1e-9 ? 0 : v;
  return x.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d, useGrouping: grouping })
    .replace("-", "−");
};
/** An axis figure with the sign ahead of the unit: "−$25", not "$−25". */
const tickTxt = (t: number, d: number, prefix: string, grouping = true) =>
  `${t < -1e-9 ? "−" : ""}${prefix}${fmtD(Math.abs(t), d, grouping)}`;
const yearish = (v: number, suffix: string) => !suffix && Number.isInteger(v) && v >= 1500 && v <= 2100;
const tickDecimals = (step: number) => {
  for (let d = 0; d <= 3; d++) {
    const m = step * Math.pow(10, d);
    if (Math.abs(m - Math.round(m)) < 1e-6) return d;
  }
  return 3;
};
const niceStep = (raw: number) => {
  if (!(raw > 0) || !Number.isFinite(raw)) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= raw - 1e-12) return m * p;
  return 10 * p;
};
/** A round axis around [lo, hi] with about `count` steps. */
const niceScale = (lo: number, hi: number, count = 4) => {
  let a = Math.min(lo, hi), b = Math.max(lo, hi);
  if (!Number.isFinite(a) || !Number.isFinite(b)) { a = 0; b = 1; }
  // All-zero data arrives as [0, 1e-9]: give it a unit axis, not ticks of "0.000".
  if (b - a < 1e-6) b = a + (Math.abs(a) || 1);
  const step = niceStep((b - a) / count);
  const min = Math.floor(a / step + 1e-9) * step;
  let max = Math.ceil(b / step - 1e-9) * step;
  if (max <= min) max = min + step;
  const ticks: number[] = [];
  for (let i = 0; i <= 14; i++) {
    const t = min + i * step;
    if (t > max + step * 1e-6) break;
    ticks.push(Math.round(t * 1e6) / 1e6);
  }
  return { min, max, step, ticks };
};
/** The tighter of the 4- and 5-step round axes (a small dip below zero no longer costs a whole step). */
const fitScale = (lo: number, hi: number) => {
  const a = niceScale(lo, hi, 4), b = niceScale(lo, hi, 5);
  return b.max - b.min < a.max - a.min - 1e-9 ? b : a;
};
/** Axis annotations settle up into place and lift away with the exit (never a plain fade). */
const drift = (pin: number, pout: number, k: number) => `translate(0 ${((1 - pin) * 12 - pout * 12) * k})`;
/** interpolateColors that never throws on an odd accent string (falls back to a neutral grey). */
const mix = (t: number, stops: number[], colors: string[]): string => {
  try {
    return interpolateColors(t, stops, colors);
  } catch {
    return "#8a8d96";
  }
};
/** The item the narration points at (overlay.highlight), else the largest. */
const pickHot = (items: Num[], h?: unknown): number => {
  const q = (typeof h === "string" ? h : "").trim().toLowerCase();
  if (q) {
    const exact = items.findIndex((i) => i.label.toLowerCase() === q);
    if (exact >= 0) return exact;
    const part = items.findIndex((i) => i.label.length > 0 &&
      (i.label.toLowerCase().includes(q) || q.includes(i.label.toLowerCase())));
    if (part >= 0) return part;
  }
  return items.reduce((m, it, i) => (it.value > items[m].value ? i : m), 0);
};
/** A seeded 0..1 (deterministic, a function of the index only). */
const seeded = (i: number) => {
  const x = Math.sin(i * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
};
/** 0 -> 1 over the exit; element i of n leaves a little after element i-1. */
const exitOf = (frame: number, dur: number, i = 0, n = 1) =>
  ramp(frame, dur - 15 + (n > 1 ? (i / (n - 1)) * 4 : 0), 10, exitEase);

// ------------------------------------------------------------------ shared pieces
/** Text rising out of a mask, and (at the end) rising out of it again. */
const Rise: React.FC<{ at: number; children: React.ReactNode; frames?: number; outDelay?: number;
  style?: React.CSSProperties }> = ({ at, children, frames = 14, outDelay = 0, style }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const pin = ramp(frame, at, frames);
  const pout = ramp(frame, durationInFrames - 14 + Math.max(0, Math.min(4, outDelay)), 9, exitEase);
  const y = (1 - pin) * 112 - pout * 112;
  return (
    <div style={{ overflow: "hidden", paddingBottom: "0.06em", minWidth: 0, ...style }}>
      <div style={{ transform: `translateY(${y}%)`, opacity: pin < 0.02 || pout > 0.98 ? 0 : 1 }}>{children}</div>
    </div>
  );
};

/** The data-card frame: scrim (fading with the exit), centred content, a slow push. */
const Card: React.FC<{ overlay: Overlay; children: React.ReactNode }> = ({ overlay, children }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const scrim = 1 - ramp(frame, durationInFrames - 12, 11, exitEase);
  const fade = 1 - ramp(frame, durationInFrames - 6, 5);
  const settle = ramp(frame, 0, 20);
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: scrim }}>
        <Scrim ov={overlay} />
      </AbsoluteFill>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", opacity: fade,
        transform: `translateY(${(1 - settle) * 26 * k}px) scale(${hold})` }}>
        {children}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/**
 * LetterLine's reveal (letters rise out of a mask one after another) with an exit that fits the
 * last frames: the out-stagger shrinks with the line length, so even a 40-letter title has fully
 * left by the cut (LetterLine's fixed 0.6-frame stagger left long titles' tails to the fade).
 * No wrapping inside a line: a letter-level wrap would split a word.
 */
const Letters: React.FC<{ text: string; at: number; step?: number; style?: React.CSSProperties }> =
  ({ text, at, step = 0.7, style }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();
    const chars = Array.from(text);
    const outStep = Math.min(0.6, 4 / Math.max(1, chars.length - 1));
    const end = durationInFrames - 15;
    return (
      <div style={{ overflow: "hidden", paddingBottom: "0.08em", whiteSpace: "nowrap", ...style }}>
        {chars.map((c, i) => {
          const pin = ramp(frame, at + i * step, 12);
          const pout = ramp(frame, end + i * outStep, 9, exitEase);
          const y = (1 - pin) * 105 - pout * 105;
          return (
            <span key={i} style={{ display: "inline-block", transform: `translateY(${y}%)`, whiteSpace: "pre",
              opacity: pin < 0.02 || pout > 0.98 ? 0 : 1 }}>{c}</span>
          );
        })}
      </div>
    );
  };

/**
 * The chart heading in the house look (ProCharts Heading: DISPLAY capitals over a short accent bar),
 * wrapped by words to the room it has (`maxW`, px): one line when it fits, else a slightly smaller
 * size on at most two lines. Letters rise in and all leave inside the last frames; the bar retracts.
 */
const ChartTitle: React.FC<{ text?: string; accent: string; size?: number; center?: boolean; maxW?: number }> =
  ({ text, accent, size = 56, center, maxW }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();
    const k = useK();
    const t = cap(text).replace(/\s+/g, " ").trim();
    if (!t) return null;
    const room = Math.max(300 * k, maxW ?? 1300 * k);
    // Bebas capitals with 0.04em tracking average under 0.47em a character.
    const per = (px: number) => Math.max(8, Math.floor(room / (px * 0.47)));
    let fs = size * k;
    let ls = lines(t, per(fs));
    if (ls.length > 1) {
      fs = size * 0.84 * k;
      ls = lines(t, per(fs));
    }
    if (ls.length > 2) {
      ls = ls.slice(0, 2);
      ls[1] = `${ls[1].replace(/[\s.,;:\-–—]+$/, "")}…`;
    }
    const out = exitOf(frame, durationInFrames);
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: center ? "center" : "flex-start", gap: 4 * k,
        maxWidth: room }}>
        {ls.map((ln, i) => (
          <Letters key={i} text={ln} at={i * 5} step={ls.length > 1 ? 0.55 : 0.7} style={{ fontFamily: DISPLAY,
            fontSize: fs, color: "#fff", letterSpacing: "0.04em", lineHeight: 1, textAlign: center ? "center" : "left",
            textShadow: "0 6px 26px rgba(0,0,0,.5)" }} />
        ))}
        <div style={{ width: ramp(frame, 6, 16) * 110 * k * (1 - out), height: 5 * k, background: accent,
          marginTop: 6 * k }} />
      </div>
    );
  };

// ================================================================== 1. bar race
/**
 * Horizontal bars start one after another and race: as a bigger bar overtakes,
 * the rows glide into rank order (a smoothed live ranking), the values count up
 * at the bar ends, the current leader turns to the accent and an overtaking bar
 * flashes a green chevron. The subtitle (a year) sits as a big ghost figure; a
 * longer subtitle runs as a line under the title instead.
 * The smallest bar starts first and the biggest last, so the bigger bars always
 * have to overtake: a real race whatever order the items arrive in.
 */
const BarRace: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const items = nums(overlay.items, 6);
  if (items.length < 2) return null;
  const n = items.length;
  const { suffix, prefix } = units(overlay, items);
  const vals = items.map((i) => Math.max(0, i.value));
  const sc = niceScale(0, Math.max(...vals, 1e-9) * 1.03, 5);
  // One number format for the whole chart ("0.30 ... 4.40", never "1.0" for 1.04).
  const dAll = Math.max(0, ...items.map((i) => decOf(i.value)));
  const td = tickDecimals(sc.step);
  const W = 1360 * k, LW = 340 * k, VW = 210 * k, BW = W - LW - VW;
  const RH = (n > 4 ? 72 : 86) * k, PITCH = RH + (n > 4 ? 14 : 18) * k, BH = RH * 0.64, TOP = 46 * k;
  const HT = TOP + n * PITCH;
  const at0 = Math.round(fps * 0.4);
  const stagger = Math.max(3, Math.round(Math.min(fps * 0.22, (dur * 0.28) / n)));
  const grow = Math.max(18, Math.round(Math.min(fps * 1.6, dur * 0.36)));
  const settle = at0 + (n - 1) * stagger + grow;
  const startRank = new Array<number>(n).fill(0);
  vals.map((_, i) => i).sort((a, b) => vals[a] - vals[b] || a - b).forEach((idx, r) => { startRank[idx] = r; });
  const cur = (f: number): number[] =>
    vals.map((v, i) => v * ramp(Math.min(f, settle), at0 + startRank[i] * stagger, grow, inOut));
  const rankAt = (f: number): number[] => {
    const c = cur(f);
    const order = c.map((_, i) => i).sort((a, b) => c[b] - c[a] || startRank[a] - startRank[b]);
    const r = new Array<number>(n).fill(0);
    order.forEach((idx, rk) => { r[idx] = rk; });
    return r;
  };
  // The rank of each bar averaged over the last frames with a triangular
  // kernel: a swap becomes an eased glide of about a third of a second.
  const smooth = (f: number): number[] => {
    const SM = 10;
    const acc = new Array<number>(n).fill(0);
    let ws = 0;
    for (let t = 0; t < SM; t++) {
      const w = Math.min(t + 1, SM - t);
      const r = rankAt(f - t);
      for (let i = 0; i < n; i++) acc[i] += r[i] * w;
      ws += w;
    }
    return acc.map((a) => a / ws);
  };
  const slot = smooth(frame);
  const before = smooth(frame - 4);
  const c = cur(frame);
  const ex = exitOf(frame, dur);
  const ghost = cap(overlay.subtitle).replace(/\s+/g, " ").trim();
  const ghostFits = ghost.length > 0 && ghost.length <= 12;
  const subLine = !ghostFits && ghost ? lines(ghost, 60)[0] + (ghost.length > 60 ? "…" : "") : "";
  return (
    <Card overlay={overlay}>
      <div style={{ width: W, display: "flex", flexDirection: "column", gap: 24 * k }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 * k }}>
          <ChartTitle text={overlay.text} accent={accent} maxW={W} />
          {subLine ? (
            <Rise at={8}>
              <span style={{ display: "block", fontFamily: LABEL, fontWeight: 700, fontSize: 30 * k,
                letterSpacing: "0.1em", color: "rgba(255,255,255,.72)", whiteSpace: "nowrap" }}>{subLine}</span>
            </Rise>
          ) : null}
        </div>
        <div style={{ position: "relative", width: W, height: HT }}>
          {ghostFits ? (
            <div style={{ position: "absolute", right: 0, bottom: -14 * k }}>
              <Rise at={Math.round(fps * 0.6)} frames={20}>
                <span style={{ display: "block", fontFamily: DISPLAY, fontSize: (ghost.length <= 6 ? 170 : 110) * k,
                  lineHeight: 0.95, color: "rgba(255,255,255,.1)", letterSpacing: "0.02em" }}>{ghost}</span>
              </Rise>
            </div>
          ) : null}
          <svg width={W} height={HT} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
            {sc.ticks.map((t, i) => {
              const x = LW + (t / sc.max) * BW;
              const base = i === 0;
              const tp = ramp(frame, 4 + i * 2, 12);
              return (
                <g key={i} opacity={tp * (1 - ex)}>
                  <line x1={x} x2={x} y1={TOP - 8 * k} y2={HT - 8 * k}
                    stroke={base ? "rgba(255,255,255,.55)" : "rgba(255,255,255,.12)"} strokeWidth={(base ? 3 : 1.5) * k}
                    strokeDasharray={base ? undefined : `${5 * k} ${7 * k}`} />
                  <text x={x} y={TOP - 18 * k} textAnchor="middle" fontFamily={LABEL} fontWeight={600} fontSize={24 * k}
                    fill="rgba(255,255,255,.55)" transform={drift(tp, ex, k)}>{prefix}{fmtD(t, td)}</text>
                </g>
              );
            })}
          </svg>
          {items.map((_, r) => (
            <div key={`r${r}`} style={{ position: "absolute", left: 0, top: TOP + r * PITCH, width: 72 * k, height: RH,
              display: "flex", alignItems: "center" }}>
              <Rise at={3 + r * 3}>
                <span style={{ display: "block", fontFamily: DISPLAY, fontSize: RH * 0.6, lineHeight: 1,
                  color: r === 0 ? accent : "rgba(255,255,255,.34)" }}>{String(r + 1).padStart(2, "0")}</span>
              </Rise>
            </div>
          ))}
          {items.map((it, i) => {
            const s = slot[i];
            const hot = interpolate(s, [0, 0.65], [1, 0], clamp);
            // Rows arrive top-down in their starting order.
            const inP = ramp(frame, 4 + startRank[i] * 3, 16);
            const exI = exitOf(frame, dur, Math.min(n - 1, Math.round(s)), n);
            const w = Math.max(0, (c[i] / sc.max) * BW * (1 - exI));
            const up = interpolate(before[i] - s, [0.03, 0.25], [0, 1], clamp);
            const startAt = at0 + startRank[i] * stagger;
            const unit = it.suffix || suffix;
            // The leader's glow and figure colour follow the smoothed slot (no switch mid-overtake).
            const glowA = Math.round(Math.max(0, Math.min(1, hot)) * 102).toString(16).padStart(2, "0");
            const valCol = mix(hot, [0, 1], ["#ffffff", accent]);
            return (
              <div key={i} style={{ position: "absolute", left: 0, top: TOP + s * PITCH, width: W, height: RH,
                zIndex: up > 0 ? 2 : 1, opacity: inP, transform: `translateX(${(1 - inP) * -36 * k}px)` }}>
                <div style={{ position: "absolute", left: 84 * k, width: LW - 108 * k, top: 0, height: RH, display: "flex",
                  alignItems: "center", justifyContent: "flex-end" }}>
                  <Rise at={6 + startRank[i] * 3} style={{ maxWidth: "100%" }}>
                    <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: RH * 0.4,
                      letterSpacing: "0.06em", color: "#fff", whiteSpace: "nowrap", overflow: "hidden",
                      textOverflow: "ellipsis" }}>{cap(it.label)}</span>
                  </Rise>
                </div>
                <div style={{ position: "absolute", left: LW, top: (RH - BH) / 2, width: w, height: BH, overflow: "hidden",
                  borderRadius: `0 ${6 * k}px ${6 * k}px 0`, background: "linear-gradient(90deg, #5d5f68, #d9dadf)",
                  boxShadow: `0 0 ${24 * k}px ${accent}${glowA}, 0 ${8 * k}px ${20 * k}px rgba(0,0,0,.3)` }}>
                  <div style={{ position: "absolute", inset: 0, opacity: hot,
                    background: `linear-gradient(90deg, ${accent}99, ${accent})` }} />
                  <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 2 * k,
                    background: "rgba(255,255,255,.4)" }} />
                </div>
                <div style={{ position: "absolute", left: LW + w + 16 * k, top: 0, height: RH, display: "flex",
                  alignItems: "center", gap: 10 * k, whiteSpace: "nowrap" }}>
                  <Rise at={startAt} frames={12}>
                    <span style={{ display: "block", fontFamily: DISPLAY, fontSize: RH * 0.64, lineHeight: 1,
                      color: valCol }}>
                      {it.prefix || prefix}{fmtD(c[i], dAll)}
                      {unit ? (
                        <span style={{ fontSize: RH * 0.36, marginLeft: (unit === "%" ? 2 : 8) * k,
                          color: "rgba(255,255,255,.7)" }}>{unit}</span>
                      ) : null}
                    </span>
                  </Rise>
                  {up > 0.01 ? (
                    <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: RH * 0.3, color: GREEN, opacity: up,
                      transform: `translateY(${(1 - up) * 8 * k}px)` }}>{"▲"}</span>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </Card>
  );
};

// ================================================================== 2. stacked column
const PALETTE = (accent: string) => [accent, "#ececf0", "#a9abb3", "#767983", "#52555e", "#3b3d44"];

/**
 * Shares of a whole as one 3D column: a wireframe of the full column draws
 * on, then each share drops in as a solid block (falling, landing with a
 * squash and a white edge flash) onto the stack; leader lines draw from each
 * block's side to its rolling percentage and name.
 */
const StackedColumn: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const base = nums(overlay.items, 5).filter((i) => i.value > 0);
  if (base.length < 2) return null;
  const { suffix, prefix, pct } = units(overlay, base);
  const sum0 = base.reduce((a, i) => a + i.value, 0);
  const segs: Num[] = pct && sum0 < 99.5
    ? [...base, { label: "Other", value: Math.round((100 - sum0) * 10) / 10 }] : base;
  const total = segs.reduce((a, i) => a + i.value, 0);
  if (!(total > 0)) return null;
  const n = segs.length;
  const colors = PALETTE(accent);
  const FW = 250 * k, DX = 86 * k, DY = 50 * k, H = 540 * k, PADT = 70 * k;
  const bottom = PADT + H;
  const LX = FW + DX + 110 * k;
  const SVGW = LX + 560 * k, SVGH = bottom + 30 * k;
  let acc = 0;
  const geo = segs.map((s) => {
    const bot = bottom - (acc / total) * H;
    acc += s.value;
    const top = bottom - (acc / total) * H;
    return { top, bot, mid: (top + bot) / 2 };
  });
  const at0 = Math.round(fps * 0.45);
  const step = Math.max(5, Math.round(Math.min(fps * 0.34, (dur * 0.34) / n)));
  const FALL = 11;
  // Label rows: at their block's side, pushed apart so none overlap.
  const MS = 90 * k;
  const ys = geo.map((g) => g.mid - DY / 2);
  for (let i = n - 2; i >= 0; i--) ys[i] = Math.max(ys[i], ys[i + 1] + MS);
  if (ys[0] > bottom - 20 * k) {
    ys[0] = bottom - 20 * k;
    for (let i = 1; i < n; i++) ys[i] = Math.min(ys[i], ys[i - 1] - MS);
  }
  const ex = exitOf(frame, dur);
  const draw = ramp(frame, 2, 22, inOut) * (1 - ex);
  const id = `ca-sc-${overlay.startFrame ?? 0}`;
  const wire = `M0 ${bottom} V${PADT} H${FW} V${bottom} Z M${FW} ${PADT} L${FW + DX} ${PADT - DY} V${bottom - DY} ` +
    `L${FW} ${bottom} M0 ${PADT} L${DX} ${PADT - DY} H${FW + DX}`;
  return (
    <Card overlay={overlay}>
      <div style={{ display: "flex", flexDirection: "column", gap: 20 * k }}>
        <ChartTitle text={overlay.text} accent={accent} maxW={SVGW} />
        <div style={{ position: "relative", width: SVGW, height: SVGH }}>
          <svg width={SVGW} height={SVGH} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
            <defs>
              <radialGradient id={`${id}s`}>
                <stop offset="0%" stopColor="#000" stopOpacity={0.55} />
                <stop offset="100%" stopColor="#000" stopOpacity={0} />
              </radialGradient>
              <linearGradient id={`${id}f`} x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#fff" stopOpacity={0.14} />
                <stop offset="100%" stopColor="#000" stopOpacity={0.12} />
              </linearGradient>
              {/* The blocks drop in (and lift out) through a mask just under the heading, never across it. */}
              <clipPath id={`${id}c`}>
                <rect x={-40 * k} y={0} width={FW + DX + 80 * k} height={SVGH + 60 * k} />
              </clipPath>
            </defs>
            <ellipse cx={(FW + DX) / 2} cy={bottom - DY / 2 + 12 * k} rx={FW * 0.95} ry={DY * 1.3}
              fill={`url(#${id}s)`} opacity={ramp(frame, 0, 14) * (1 - ex)} />
            <path d={wire} fill="none" stroke="rgba(255,255,255,.34)" strokeWidth={2 * k} strokeLinejoin="round"
              pathLength={1} strokeDasharray={1} strokeDashoffset={1 - draw} />
            <g clipPath={`url(#${id}c)`}>
            {segs.map((s, i) => {
              const at = at0 + i * step;
              if (frame < at) return null;
              const { top, bot } = geo[i];
              const t = interpolate(frame, [at, at + FALL], [0, 1], clamp);
              const u = interpolate(frame, [at + FALL, at + FALL + 12], [0, 1], clamp);
              const exI = exitOf(frame, dur, n - 1 - i, n);
              const yo = -(1 - t * t) * 340 * k - exI * 160 * k;
              const sq = t >= 1 ? 1 - 0.07 * Math.sin(Math.PI * u) * (1 - u * 0.5) : 1;
              const col = colors[i % colors.length];
              const front = `M0 ${top} H${FW} V${bot} H0 Z`;
              const side = `M${FW} ${bot} L${FW + DX} ${bot - DY} V${top - DY} L${FW} ${top} Z`;
              const lid = `M0 ${top} H${FW} L${FW + DX} ${top - DY} H${DX} Z`;
              return (
                <g key={i} opacity={interpolate(t, [0, 0.3], [0, 1], clamp) * (1 - exI)}
                  transform={`translate(0 ${yo}) translate(0 ${bot}) scale(1 ${sq}) translate(0 ${-bot})`}>
                  <path d={front} fill={col} />
                  <path d={front} fill={`url(#${id}f)`} />
                  <path d={side} fill={col} />
                  <path d={side} fill="rgba(0,0,0,.34)" />
                  <path d={lid} fill={col} />
                  <path d={lid} fill="rgba(255,255,255,.22)" />
                  <path d={`${front} ${side} ${lid}`} fill="none" stroke="rgba(10,10,14,.55)" strokeWidth={1.5 * k}
                    strokeLinejoin="round" />
                  <line x1={0} x2={FW} y1={top} y2={top} stroke="#fff" strokeWidth={3 * k}
                    opacity={t >= 1 ? (1 - u) * 0.9 : 0} />
                </g>
              );
            })}
            </g>
            {segs.map((s, i) => {
              const land = at0 + i * step + FALL;
              const p = ramp(frame, land + 2, 14, inOut) * (1 - exitOf(frame, dur, n - 1 - i, n));
              if (p <= 0.001) return null;
              const sx = FW + DX / 2, sy = geo[i].mid - DY / 2;
              const d = `M${sx} ${sy} L${FW + DX + 46 * k} ${ys[i]} H${LX - 18 * k}`;
              return (
                <g key={`l${i}`}>
                  <path d={d} fill="none" stroke="rgba(255,255,255,.7)" strokeWidth={2 * k} strokeLinejoin="round"
                    pathLength={1} strokeDasharray={1} strokeDashoffset={1 - p} />
                  <circle cx={sx} cy={sy} r={5 * k * Math.min(1, p * 3)} fill="#fff" />
                </g>
              );
            })}
          </svg>
          {segs.map((s, i) => {
            const land = at0 + i * step + FALL;
            const lead = i === 0;
            const size = (lead ? 76 : 58) * k;
            return (
              <div key={i} style={{ position: "absolute", left: LX, top: ys[i], transform: "translateY(-50%)",
                display: "flex", alignItems: "center", gap: 18 * k, whiteSpace: "nowrap" }}>
                <Rise at={land}>
                  <Odometer value={s.value} at={land} frames={Math.round(fps * 0.8)} size={size}
                    color={lead ? accent : "#fff"} prefix={s.prefix || prefix} suffix={tail(s.suffix || suffix)}
                    suffixScale={0.5} />
                </Rise>
                <Rise at={land + 4} style={{ maxWidth: 300 * k }}>
                  <span style={{ display: "block", fontFamily: LABEL, fontWeight: 700, fontSize: 30 * k,
                    letterSpacing: "0.08em", color: "rgba(255,255,255,.86)", overflow: "hidden",
                    textOverflow: "ellipsis" }}>{cap(s.label)}</span>
                </Rise>
              </div>
            );
          })}
        </div>
      </div>
    </Card>
  );
};

// ================================================================== 3. grouped bars
/**
 * Pairs of bars per label: the "then" bar is a hatched ghost whose outline
 * draws on like a pen stroke, the "now" bar rises solid in the accent beside
 * it, both values roll above them, and a red/green change chip pops over each
 * pair. A legend names the two series (overlay.label "2000|2022").
 * items[].value = then, items[].text = now (a number as text).
 */
const GroupedBars: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const items = nums(overlay.items, 6);
  const pairs = items.map((it) => ({ it, a: it.value, b: toNum(it.text) }));
  const hasB = pairs.some((p) => Number.isFinite(p.b));
  if (!pairs.length || (!hasB && pairs.length < 2)) return null;
  const { suffix, prefix } = units(overlay, items);
  const names = cap(overlay.label).split(/\s*(?:\||\/|\bVS\b\.?)\s*/).map((s) => s.trim()).filter(Boolean);
  // Legend names stay short so the legend never squeezes the title.
  const short14 = (s: string) => (s.length > 14 ? `${s.slice(0, 13).trim()}…` : s);
  const nameA = short14(names[0] || "THEN"), nameB = short14(names[1] || "NOW");
  const legendW = hasB ? (68 + 28 + (nameA.length + nameB.length) * 17) * k : 0;
  const all: number[] = [];
  pairs.forEach((p) => { all.push(p.a); if (Number.isFinite(p.b)) all.push(p.b); });
  const sc = niceScale(Math.min(0, ...all), Math.max(0, ...all) * 1.04 || 1, 4);
  const td = tickDecimals(sc.step);
  const n = pairs.length;
  const W = 1340 * k, H = 420 * k, TOP = 150 * k, HT = TOP + H + 90 * k;
  const Y = (v: number) => TOP + (1 - (v - sc.min) / (sc.max - sc.min)) * H;
  const y0 = Y(0);
  const gw = W / n;
  const bw = Math.min(96 * k, gw * (hasB ? 0.27 : 0.42));
  const GB = 14 * k;
  const vs = gw < 200 * k ? 0.82 : 1;
  const at0 = Math.round(fps * 0.35);
  const stagger = Math.max(3, Math.round(Math.min(fps * 0.2, (dur * 0.22) / n)));
  const growF = Math.round(fps * 0.9);
  const hotA = hasB ? -1 : pickHot(items, overlay.highlight);
  const ex = exitOf(frame, dur);
  const id = `ca-gb-${overlay.startFrame ?? 0}`;
  const hatch = `repeating-linear-gradient(45deg, rgba(255,255,255,.4) 0px, rgba(255,255,255,.4) ${3 * k}px, ` +
    `transparent ${3 * k}px, transparent ${8 * k}px)`;
  return (
    <Card overlay={overlay}>
      <div style={{ width: W, display: "flex", flexDirection: "column", gap: 10 * k }}>
        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 40 * k }}>
          <ChartTitle text={overlay.text} accent={accent} maxW={W - legendW - 40 * k} />
          {hasB ? (
            <div style={{ display: "flex", alignItems: "center", gap: 28 * k, marginBottom: 12 * k, flexShrink: 0,
              whiteSpace: "nowrap" }}>
              <Rise at={10}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 * k }}>
                  <div style={{ width: 24 * k, height: 24 * k, border: `${2.5 * k}px solid rgba(255,255,255,.85)`,
                    background: hatch }} />
                  <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 28 * k, letterSpacing: "0.14em",
                    color: "rgba(255,255,255,.8)" }}>{nameA}</span>
                </div>
              </Rise>
              <Rise at={14}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 * k }}>
                  <div style={{ width: 24 * k, height: 24 * k, background: accent }} />
                  <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 28 * k, letterSpacing: "0.14em",
                    color: "#fff" }}>{nameB}</span>
                </div>
              </Rise>
            </div>
          ) : null}
        </div>
        <div style={{ position: "relative", width: W, height: HT }}>
          <svg width={W} height={HT} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
            <defs>
              <pattern id={`${id}h`} width={12 * k} height={12 * k} patternUnits="userSpaceOnUse"
                patternTransform="rotate(45)">
                <line x1={0} y1={0} x2={0} y2={12 * k} stroke="rgba(255,255,255,.3)" strokeWidth={4 * k} />
              </pattern>
              <linearGradient id={`${id}b`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={accent} />
                <stop offset="100%" stopColor={accent} stopOpacity={0.62} />
              </linearGradient>
              <linearGradient id={`${id}w`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#fff" stopOpacity={0.95} />
                <stop offset="100%" stopColor="#fff" stopOpacity={0.45} />
              </linearGradient>
            </defs>
            {sc.ticks.map((t, i) => {
              const tp = ramp(frame, 2 + i * 2, 12);
              return (
                <g key={`g${i}`} opacity={tp * (1 - ex)}>
                  <line x1={0} x2={W} y1={Y(t)} y2={Y(t)} stroke="rgba(255,255,255,.12)" strokeWidth={1.5 * k}
                    strokeDasharray={`${6 * k} ${8 * k}`} />
                  <text x={-16 * k} y={Y(t) + 8 * k} textAnchor="end" fontFamily={LABEL} fontWeight={600} fontSize={24 * k}
                    fill="rgba(255,255,255,.55)" transform={drift(tp, ex, k)}>
                    {tickTxt(t, td, prefix)}{suffix === "%" ? "%" : ""}</text>
                </g>
              );
            })}
            <line x1={0} x2={W * ramp(frame, 0, 18, inOut) * (1 - ex)} y1={y0} y2={y0} stroke="rgba(255,255,255,.8)"
              strokeWidth={3 * k} />
            {pairs.map((p, i) => {
              const cx = gw * (i + 0.5);
              const xa = hasB ? cx - GB / 2 - bw : cx - bw / 2;
              const xb = cx + GB / 2;
              const at = at0 + i * stagger;
              const exI = exitOf(frame, dur, i, n);
              if (frame < at) return null;
              if (!hasB) {
                const gA = ramp(frame, at, growF, inOut) * (1 - exI);
                const yA = Y(p.a * gA);
                return (
                  <rect key={i} x={xa} y={Math.min(yA, y0)} width={bw} height={Math.abs(yA - y0)}
                    fill={i === hotA ? `url(#${id}b)` : `url(#${id}w)`} />
                );
              }
              const dA = ramp(frame, at, 18, inOut) * (1 - exI);
              const ya = Y(p.a);
              const hasPair = Number.isFinite(p.b);
              const gB = hasPair ? ramp(frame, at + 8, growF, inOut) * (1 - exI) : 0;
              const yb = hasPair ? Y(p.b * gB) : y0;
              return (
                <g key={i}>
                  <rect x={xa} y={Math.min(ya, y0)} width={bw} height={Math.abs(ya - y0)} fill={`url(#${id}h)`}
                    opacity={dA} />
                  <path d={`M${xa} ${y0} V${ya} H${xa + bw} V${y0}`} fill="none" stroke="rgba(255,255,255,.88)"
                    strokeWidth={3 * k} strokeLinejoin="round" pathLength={1} strokeDasharray={1}
                    strokeDashoffset={1 - dA} />
                  {hasPair && gB > 0.001 ? (
                    <>
                      <rect x={xb} y={Math.min(yb, y0)} width={bw} height={Math.abs(yb - y0)} fill={`url(#${id}b)`} />
                      <rect x={xb} y={yb <= y0 ? yb : yb - 3 * k} width={bw} height={3 * k} fill="#fff" opacity={0.55} />
                    </>
                  ) : null}
                </g>
              );
            })}
          </svg>
          {pairs.map((p, i) => {
            const cx = gw * (i + 0.5);
            const xa = hasB ? cx - GB / 2 - bw : cx - bw / 2;
            const xb = cx + GB / 2;
            const at = at0 + i * stagger;
            const exI = exitOf(frame, dur, i, n);
            const ya = Y(p.a);
            const hasPair = hasB && Number.isFinite(p.b);
            const ybF = hasPair ? Y(p.b) : ya;
            const canChip = hasPair && Math.abs(p.a) > 1e-9;
            const chipAt = at + 8 + growF - 6;
            const chipP = canChip ? ramp(frame, chipAt, 14, backOut) * (1 - exI) : 0;
            const change = canChip ? ((p.b - p.a) / Math.abs(p.a)) * 100 : 0;
            const down = change < 0;
            const chipCol = down ? RED : GREEN;
            const chipY = Math.min(ya, ybF, y0) - 118 * k * vs;
            const ls = lines(cap(p.it.label), 14).slice(0, 2);
            const hotSingle = i === hotA;
            // Two values of about the same height would put their labels side by side over narrow
            // bars: then they splay outward from the gap between the bars instead of centring.
            const close = hasPair && Math.abs(Math.min(ya, y0) - Math.min(ybF, y0)) < 60 * k * vs;
            return (
              <React.Fragment key={i}>
                <div style={{ position: "absolute", left: close ? xa + bw : xa + bw / 2, top: Math.min(ya, y0) - 8 * k,
                  transform: close ? "translate(-100%, -100%)" : "translate(-50%, -100%)", whiteSpace: "nowrap" }}>
                  <Rise at={at + 6}>
                    <Odometer value={Math.abs(p.a)} at={at + 6} frames={Math.round(fps * 0.9)}
                      size={(hasB ? 36 : 50) * k * vs} color={hasB ? "rgba(255,255,255,.72)" : hotSingle ? accent : "#fff"}
                      prefix={(p.a < 0 ? "−" : "") + (p.it.prefix || prefix)} suffix={tail(p.it.suffix || suffix)}
                      suffixScale={0.5} />
                  </Rise>
                </div>
                {hasPair ? (
                  <div style={{ position: "absolute", left: close ? xb : xb + bw / 2, top: Math.min(ybF, y0) - 8 * k,
                    transform: close ? "translate(0, -100%)" : "translate(-50%, -100%)", whiteSpace: "nowrap" }}>
                    <Rise at={at + 12}>
                      <Odometer value={Math.abs(p.b)} at={at + 12} frames={growF} size={48 * k * vs} color="#fff"
                        prefix={(p.b < 0 ? "−" : "") + (p.it.prefix || prefix)} suffix={tail(p.it.suffix || suffix)}
                        suffixScale={0.5} suffixColor={accent} />
                    </Rise>
                  </div>
                ) : null}
                {canChip && chipP > 0.001 ? (
                  <div style={{ position: "absolute", left: cx, top: chipY, transform: `translate(-50%, 0) scale(${chipP})`,
                    transformOrigin: "50% 100%", display: "flex", alignItems: "center", gap: 6 * k, background: chipCol,
                    color: "#fff", fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k * vs, lineHeight: 1,
                    letterSpacing: "0.04em", padding: `${7 * k}px ${16 * k}px ${5 * k}px`, borderRadius: 40 * k,
                    boxShadow: `0 0 ${20 * k}px ${chipCol}66`, whiteSpace: "nowrap", opacity: Math.min(1, chipP * 2) }}>
                    <span style={{ fontSize: 20 * k * vs }}>{down ? "▼" : "▲"}</span>
                    {Math.abs(change) >= 10 ? Math.round(Math.abs(change)) : Math.abs(change).toFixed(1)}%
                  </div>
                ) : null}
                <div style={{ position: "absolute", left: gw * i, width: gw, top: TOP + H + 16 * k, display: "flex",
                  flexDirection: "column", alignItems: "center" }}>
                  {ls.map((ln, j) => (
                    <Rise key={j} at={at + 2 + j * 2}>
                      <span style={{ display: "block", fontFamily: LABEL, fontWeight: 700, fontSize: 30 * k * vs,
                        letterSpacing: "0.06em", lineHeight: 1.05, textAlign: "center",
                        color: hotSingle ? accent : "rgba(255,255,255,.86)" }}>{ln}</span>
                    </Rise>
                  ))}
                </div>
              </React.Fragment>
            );
          })}
        </div>
      </div>
    </Card>
  );
};

// ================================================================== 4. lollipop
/**
 * Rows of dotted tracks; each stem shoots out from zero with a small bead on
 * its tip, the head pops to full size with a shock ring when it lands, and the
 * value rolls beside it. The highlighted row is in the accent. Last, a cyan
 * dashed AVERAGE line drops through all rows.
 */
const Lollipop: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const items = nums(overlay.items, 6);
  if (items.length < 2) return null;
  const n = items.length;
  const { suffix, prefix } = units(overlay, items);
  const vals = items.map((i) => i.value);
  const sc = niceScale(Math.min(0, ...vals), Math.max(0, ...vals) * 1.04 || 1, 4);
  const td = tickDecimals(sc.step);
  const hot = pickHot(items, overlay.highlight);
  const W = 1360 * k, LW = 330 * k, VW = 190 * k, PW = W - LW - VW;
  const X = (v: number) => LW + ((v - sc.min) / (sc.max - sc.min)) * PW;
  const x0 = X(0);
  const TOP = 70 * k, RH = (n > 4 ? 82 : 96) * k, HR = (n > 4 ? 18 : 21) * k;
  const HT = TOP + n * RH + 56 * k;
  const at0 = Math.round(fps * 0.4);
  const stagger = Math.max(3, Math.round(Math.min(fps * 0.16, (dur * 0.2) / n)));
  const shoot = Math.round(fps * 0.55);
  const mean = vals.reduce((a, v) => a + v, 0) / n;
  const avgAt = at0 + (n - 1) * stagger + shoot;
  const ex = exitOf(frame, dur);
  const avgP = ramp(frame, avgAt, 18, inOut) * (1 - ex);
  const xm = X(mean);
  const meanTxt = fmtD(mean, Number.isInteger(mean) || Math.abs(mean) >= 100 ? 0 : 1);
  return (
    <Card overlay={overlay}>
      <div style={{ width: W, display: "flex", flexDirection: "column", gap: 18 * k }}>
        <ChartTitle text={overlay.text} accent={accent} maxW={W} />
        <div style={{ position: "relative", width: W, height: HT }}>
          <svg width={W} height={HT} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
            {sc.ticks.map((t, i) => {
              const tp = ramp(frame, 2 + i * 2, 12);
              return (
                <g key={`g${i}`} opacity={tp * (1 - ex)}>
                  <line x1={X(t)} x2={X(t)} y1={TOP} y2={TOP + n * RH} stroke="rgba(255,255,255,.1)" strokeWidth={1.5 * k} />
                  <text x={X(t)} y={TOP + n * RH + 36 * k} textAnchor="middle" fontFamily={LABEL} fontWeight={600}
                    fontSize={24 * k} fill="rgba(255,255,255,.55)" transform={drift(tp, ex, k)}>
                    {tickTxt(t, td, prefix)}{suffix === "%" ? "%" : ""}</text>
                </g>
              );
            })}
            {sc.min < 0 ? (
              <line x1={x0} x2={x0} y1={TOP} y2={TOP + n * RH} stroke="rgba(255,255,255,.7)" strokeWidth={3 * k}
                opacity={ramp(frame, 2, 12) * (1 - ex)} />
            ) : null}
            {items.map((it, i) => {
              const y = TOP + i * RH + RH / 2;
              const at = at0 + i * stagger;
              const exI = exitOf(frame, dur, i, n);
              const g = ramp(frame, at, shoot, expoOut) * (1 - exI);
              const xv = x0 + (X(it.value) - x0) * g;
              const arrive = at + Math.round(shoot * 0.35);
              const pop = ramp(frame, arrive, 14, backOut);
              const ring = interpolate(frame, [arrive, arrive + 16], [0, 1], clamp);
              const isHot = i === hot;
              const col = isHot ? accent : "#fff";
              return (
                <g key={i}>
                  <line x1={LW} x2={LW + PW} y1={y} y2={y} stroke="rgba(255,255,255,.2)" strokeWidth={4 * k}
                    strokeLinecap="round" strokeDasharray={`0 ${14 * k}`} opacity={ramp(frame, 2 + i * 2, 14) * (1 - ex)} />
                  {frame >= at ? (
                    <>
                      <line x1={x0} x2={xv} y1={y} y2={y} stroke={col} strokeOpacity={isHot ? 1 : 0.82}
                        strokeWidth={5 * k} strokeLinecap="round" />
                      {ring > 0 && ring < 1 ? (
                        <circle cx={xv} cy={y} r={HR + 34 * k * ring} fill="none" stroke={col} strokeWidth={3 * k}
                          opacity={(1 - ring) * 0.85} />
                      ) : null}
                      <circle cx={xv} cy={y} r={Math.max(0, (7 * k + (HR - 7 * k) * pop) * (1 - exI))}
                        fill={isHot ? accent : INK} stroke={col} strokeWidth={5 * k} />
                    </>
                  ) : null}
                </g>
              );
            })}
            {avgP > 0.001 ? (
              <line x1={xm} x2={xm} y1={TOP - 14 * k} y2={TOP - 14 * k + (n * RH + 14 * k) * avgP} stroke={CYAN}
                strokeWidth={3 * k} strokeDasharray={`${8 * k} ${6 * k}`} />
            ) : null}
          </svg>
          {items.map((it, i) => {
            const y = TOP + i * RH + RH / 2;
            const at = at0 + i * stagger;
            const exI = exitOf(frame, dur, i, n);
            const g = ramp(frame, at, shoot, expoOut) * (1 - exI);
            const xv = x0 + (X(it.value) - x0) * g;
            const arrive = at + Math.round(shoot * 0.35);
            const isHot = i === hot;
            const neg = it.value < 0;
            return (
              <React.Fragment key={i}>
                <div style={{ position: "absolute", left: 0, width: LW - 34 * k, top: y, transform: "translateY(-50%)",
                  display: "flex", justifyContent: "flex-end" }}>
                  <Rise at={4 + i * 3} style={{ maxWidth: "100%" }}>
                    <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: RH * 0.36,
                      letterSpacing: "0.06em", color: isHot ? "#fff" : "rgba(255,255,255,.82)", whiteSpace: "nowrap",
                      overflow: "hidden", textOverflow: "ellipsis" }}>{cap(it.label)}</span>
                  </Rise>
                </div>
                <div style={{ position: "absolute", left: neg ? xv - HR - 14 * k : xv + HR + 14 * k, top: y,
                  transform: neg ? "translate(-100%, -50%)" : "translateY(-50%)", whiteSpace: "nowrap" }}>
                  <Rise at={arrive}>
                    <Odometer value={Math.abs(it.value)} at={arrive} frames={Math.round(fps * 0.8)} size={RH * 0.52}
                      color={isHot ? accent : "#fff"} prefix={(neg ? "−" : "") + (it.prefix || prefix)}
                      suffix={tail(it.suffix || suffix)} suffixScale={0.5} />
                  </Rise>
                </div>
              </React.Fragment>
            );
          })}
          <div style={{ position: "absolute", left: xm, top: TOP - 22 * k, transform: "translate(-50%, -100%)",
            whiteSpace: "nowrap" }}>
            <Rise at={avgAt + 4}>
              <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: 26 * k, letterSpacing: "0.14em",
                color: CYAN }}>AVG {prefix}{meanTxt}{tail(suffix)}</span>
            </Rise>
          </div>
        </div>
      </div>
    </Card>
  );
};

// ================================================================== 5. dot plot
/**
 * One long ruler draws on, its ticks popping as the line passes; then each
 * value is a dot that slides from the left end to its place with a comet
 * trail, lands with a pulse ring and sends a thin stem up or down to its
 * callout (value + name), callouts stacked in tiers so they never collide.
 */
const DotPlot: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const items = nums(overlay.items, 6);
  if (items.length < 2) return null;
  const n = items.length;
  const { suffix, prefix } = units(overlay, items);
  const vals = items.map((i) => i.value);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const span = hi - lo || Math.abs(hi) || 1;
  const sc = lo >= 0 && lo <= hi * 0.45
    ? niceScale(0, hi * 1.04, 5) : niceScale(lo - span * 0.12, hi + span * 0.12, 5);
  const td = tickDecimals(sc.step);
  const hot = pickHot(items, overlay.highlight);
  const W = 1480 * k, TIER = 104 * k;
  const X = (v: number) => ((v - sc.min) / (sc.max - sc.min)) * W;
  const yearAxis = vals.every((v) => yearish(v, suffix));
  // Callout tiers: sides alternate, a callout moves up a tier when it would hit its neighbour.
  type Place = { side: 0 | 1; tier: number };
  const est = (it: Num) => Math.max(cap(it.label).length * 14 * k,
    (fmt(it.value).length + suffix.length + prefix.length) * 25 * k, 110 * k) + 30 * k;
  const order = items.map((_, i) => i).sort((a, b) => items[a].value - items[b].value || a - b);
  const edge: number[][] = [[-1e9, -1e9, -1e9], [-1e9, -1e9, -1e9]];
  const place: Place[] = items.map((): Place => ({ side: 0, tier: 0 }));
  order.forEach((idx, j) => {
    const x = X(items[idx].value), w = est(items[idx]);
    const pref: 0 | 1 = j % 2 === 0 ? 0 : 1;
    const other: 0 | 1 = pref === 0 ? 1 : 0;
    let found: Place | null = null;
    for (let tier = 0; tier < 3 && !found; tier++) {
      for (const side of [pref, other]) {
        if (edge[side][tier] < x - w / 2) { found = { side, tier }; break; }
      }
    }
    const pl: Place = found || { side: pref, tier: 2 };
    edge[pl.side][pl.tier] = x + w / 2;
    place[idx] = pl;
  });
  const upT = place.reduce((m, p) => (p.side === 0 ? Math.max(m, p.tier + 1) : m), 0);
  const dnT = place.reduce((m, p) => (p.side === 1 ? Math.max(m, p.tier + 1) : m), 0);
  const AY = upT > 0 ? upT * TIER + 40 * k : 60 * k;
  const HT = AY + (dnT > 0 ? 80 * k + dnT * TIER : 70 * k);
  const ex = exitOf(frame, dur);
  const axisP = ramp(frame, 2, Math.round(fps * 0.7), inOut) * (1 - ex);
  const at0 = Math.round(fps * 0.5);
  const stagger = Math.max(3, Math.round(Math.min(fps * 0.22, (dur * 0.25) / n)));
  const slide = Math.round(fps * 0.8);
  const minors: number[] = [];
  for (let s = 0; s < sc.ticks.length - 1; s++) {
    for (let j = 1; j < 5; j++) minors.push(sc.ticks[s] + (sc.step * j) / 5);
  }
  // A tick pops as the drawing line reaches it (and goes again as the line retracts).
  const tickOn = (x: number) => interpolate(axisP * W - x, [-30 * k, 0], [0, 1], clamp) * ramp(frame, 2, 8);
  const id = `ca-dp-${overlay.startFrame ?? 0}`;
  const yEndOf = (pl: Place) => (pl.side === 0 ? AY - 44 * k - pl.tier * TIER : AY + 76 * k + pl.tier * TIER);
  return (
    <Card overlay={overlay}>
      <div style={{ width: W, display: "flex", flexDirection: "column", gap: 26 * k }}>
        <ChartTitle text={overlay.text} accent={accent} maxW={W} />
        <div style={{ position: "relative", width: W, height: HT }}>
          <svg width={W} height={HT} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
            <defs>
              <linearGradient id={`${id}t`} x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#fff" stopOpacity={0} />
                <stop offset="100%" stopColor="#fff" stopOpacity={0.75} />
              </linearGradient>
              <linearGradient id={`${id}a`} x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor={accent} stopOpacity={0} />
                <stop offset="100%" stopColor={accent} stopOpacity={0.9} />
              </linearGradient>
            </defs>
            <line x1={0} x2={W * axisP} y1={AY} y2={AY} stroke="rgba(255,255,255,.85)" strokeWidth={4 * k}
              strokeLinecap="round" />
            {minors.map((t, i) => {
              const x = X(t);
              return (
                <line key={`m${i}`} x1={x} x2={x} y1={AY - 8 * k} y2={AY + 8 * k} stroke="rgba(255,255,255,.35)"
                  strokeWidth={2 * k} opacity={tickOn(x)} />
              );
            })}
            {sc.ticks.map((t, i) => {
              const x = X(t);
              return (
                <g key={`t${i}`} opacity={tickOn(x)}>
                  <line x1={x} x2={x} y1={AY - 16 * k} y2={AY + 16 * k} stroke="#fff" strokeWidth={3 * k} />
                  <text x={x} y={AY + 46 * k} textAnchor="middle" fontFamily={LABEL} fontWeight={600} fontSize={24 * k}
                    fill="rgba(255,255,255,.6)">{tickTxt(t, td, prefix, !yearAxis)}{suffix === "%" ? "%" : ""}</text>
                </g>
              );
            })}
            {suffix && suffix !== "%" ? (
              <text x={W + 26 * k} y={AY + 9 * k} fontFamily={LABEL} fontWeight={800} fontSize={24 * k}
                letterSpacing="0.12em" fill="rgba(255,255,255,.7)" opacity={tickOn(W)}>{cap(suffix)}</text>
            ) : null}
            {items.map((it, i) => {
              const at = at0 + i * stagger;
              if (frame < at) return null;
              const exI = exitOf(frame, dur, i, n);
              const xf = X(it.value);
              const x = xf * ramp(frame, at, slide, expoOut);
              const xp = Math.max(xf * ramp(frame - 4, at, slide, expoOut), x - 260 * k);
              const land = at + Math.round(slide * 0.4);
              const ring = interpolate(frame, [land, land + 16], [0, 1], clamp);
              const isHot = i === hot;
              const col = isHot ? accent : "#fff";
              const r = (isHot ? 17 : 14) * k * (1 - exI);
              const pl = place[i];
              const sp = ramp(frame, land, 12, inOut) * (1 - exI);
              const yS = pl.side === 0 ? AY - r - 6 * k : AY + r + 6 * k;
              const yE = yEndOf(pl);
              return (
                <g key={i}>
                  {x - xp > 1 ? (
                    <rect x={xp} y={AY - 5 * k} width={x - xp} height={10 * k} rx={5 * k}
                      fill={`url(#${id}${isHot ? "a" : "t"})`} />
                  ) : null}
                  {ring > 0 && ring < 1 ? (
                    <circle cx={xf} cy={AY} r={r + 30 * k * ring} fill="none" stroke={col} strokeWidth={3 * k}
                      opacity={1 - ring} />
                  ) : null}
                  {sp > 0.001 ? (
                    <line x1={xf} x2={xf} y1={yS} y2={yS + (yE - yS) * sp} stroke={col} strokeOpacity={0.7}
                      strokeWidth={2 * k} />
                  ) : null}
                  <circle cx={x} cy={AY} r={r} fill={col} stroke={INK} strokeWidth={4 * k}
                    style={isHot ? { filter: `drop-shadow(0 0 ${12 * k}px ${accent})` } : undefined} />
                </g>
              );
            })}
          </svg>
          {items.map((it, i) => {
            const at = at0 + i * stagger;
            const land = at + Math.round(slide * 0.4);
            const pl = place[i];
            const above = pl.side === 0;
            const isHot = i === hot;
            const yE = yEndOf(pl);
            const num = (
              <Rise at={land + 4}>
                <Odometer value={Math.abs(it.value)} at={land + 4} frames={Math.round(fps * 0.8)} size={46 * k}
                  color={isHot ? accent : "#fff"} prefix={(it.value < 0 ? "−" : "") + (it.prefix || prefix)}
                  suffix={tail(it.suffix || suffix)} suffixScale={0.5} grouping={!yearish(it.value, suffix)} />
              </Rise>
            );
            const name = (
              <Rise at={land + 7}>
                <span style={{ display: "block", fontFamily: LABEL, fontWeight: 700, fontSize: 26 * k,
                  letterSpacing: "0.08em", color: isHot ? "#fff" : "rgba(255,255,255,.78)", whiteSpace: "nowrap" }}>
                  {cap(it.label)}</span>
              </Rise>
            );
            // A callout at the very end of the ruler shifts inward instead of hanging past the safe margin.
            const half = est(it) / 2;
            const cxC = Math.max(half - 40 * k, Math.min(W - half + 40 * k, X(it.value)));
            return (
              <div key={i} style={{ position: "absolute", left: cxC, top: above ? yE - 4 * k : yE + 4 * k,
                transform: above ? "translate(-50%, -100%)" : "translate(-50%, 0)", display: "flex",
                flexDirection: "column", alignItems: "center", gap: 2 * k }}>
                {above ? <>{name}{num}</> : <>{num}{name}</>}
              </div>
            );
          })}
        </div>
      </div>
    </Card>
  );
};

// ================================================================== 6. waterfall
/**
 * A running total: the first item is the starting level (a white column),
 * every next item is a change that steps off the previous level, up in green
 * or down in red, joined by dashed connectors that draw across; a final
 * accent column (overlay.label, default "Total") rises to the net result.
 */
const Waterfall: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const items = nums(overlay.items, 6);
  if (items.length < 2) return null;
  const { suffix, prefix } = units(overlay, items);
  type Col = { label: string; from: number; to: number; delta: number; kind: "start" | "up" | "down" | "total" };
  const cols: Col[] = [];
  let level = 0;
  items.forEach((it, i) => {
    const from = i === 0 ? 0 : level;
    const to = i === 0 ? it.value : level + it.value;
    cols.push({ label: it.label, from, to, delta: it.value, kind: i === 0 ? "start" : it.value >= 0 ? "up" : "down" });
    level = to;
  });
  const totalName = typeof overlay.label === "string" && overlay.label.trim() ? overlay.label.trim() : "Total";
  cols.push({ label: totalName, from: 0, to: level, delta: level, kind: "total" });
  const nC = cols.length;
  const lv = cols.flatMap((c) => [c.from, c.to]);
  // The tighter round axis: a net just under zero no longer reserves a whole negative step.
  const sc = fitScale(Math.min(0, ...lv), Math.max(0, ...lv) * 1.06 || 1);
  const td = tickDecimals(sc.step);
  const d = Math.max(0, ...items.map((i) => decOf(i.value)));
  const W = 1400 * k, H = 430 * k, TOP = 80 * k;
  const Y = (v: number) => TOP + (1 - (v - sc.min) / (sc.max - sc.min)) * H;
  // A falling column's value hangs under its end; near the bottom of the scale it would sit on the
  // names, so the name row moves down to clear the lowest one.
  const labH = (c: Col) => (c.kind === "total" ? 70 : c.kind === "start" ? 57 : 50) * k;
  const lowest = cols.reduce((m, c) => (c.to < c.from ? Math.max(m, Y(c.to) + 10 * k + labH(c)) : m), 0);
  const NAMES = Math.max(TOP + H + 18 * k, lowest + 12 * k);
  const HT = NAMES + 72 * k;
  const cw = W / nC, bw = Math.min(128 * k, cw * 0.58);
  const at0 = Math.round(fps * 0.4);
  const step = Math.max(5, Math.min(Math.round(fps * 0.3), Math.round((dur * 0.5 - at0) / nC)));
  const GROW = 14;
  const ex = exitOf(frame, dur);
  const id = `ca-wf-${overlay.startFrame ?? 0}`;
  const colOf = (kind: Col["kind"]) => (kind === "start" ? "#e6e6ea" : kind === "up" ? GREEN : kind === "down" ? RED : accent);
  const signed = (v: number) => `${v >= 0 ? "+" : "−"}${prefix}${fmtD(Math.abs(v), d)}${tail(suffix)}`;
  return (
    <Card overlay={overlay}>
      <div style={{ width: W, display: "flex", flexDirection: "column", gap: 22 * k }}>
        <ChartTitle text={overlay.text} accent={accent} maxW={W} />
        <div style={{ position: "relative", width: W, height: HT }}>
          <svg width={W} height={HT} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
            <defs>
              <linearGradient id={`${id}s`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#fff" stopOpacity={0.22} />
                <stop offset="100%" stopColor="#fff" stopOpacity={0} />
              </linearGradient>
            </defs>
            {sc.ticks.map((t, i) => {
              const tp = ramp(frame, 2 + i * 2, 12);
              return (
                <g key={`g${i}`} opacity={tp * (1 - ex)}>
                  <line x1={0} x2={W} y1={Y(t)} y2={Y(t)} stroke="rgba(255,255,255,.1)" strokeWidth={1.5 * k}
                    strokeDasharray={`${6 * k} ${8 * k}`} />
                  <text x={-16 * k} y={Y(t) + 8 * k} textAnchor="end" fontFamily={LABEL} fontWeight={600} fontSize={24 * k}
                    fill="rgba(255,255,255,.55)" transform={drift(tp, ex, k)}>{tickTxt(t, td, prefix)}</text>
                </g>
              );
            })}
            <line x1={0} x2={W * ramp(frame, 0, 18, inOut) * (1 - ex)} y1={Y(0)} y2={Y(0)} stroke="rgba(255,255,255,.75)"
              strokeWidth={3 * k} />
            {cols.slice(0, -1).map((c, i) => {
              const at = at0 + i * step;
              const exI = exitOf(frame, dur, nC - 1 - i, nC);
              const cp = ramp(frame, at + GROW - 2, step + 4, inOut) * (1 - exI);
              if (cp <= 0.001) return null;
              const x1 = cw * (i + 0.5) + bw / 2, x2 = cw * (i + 1.5) - bw / 2;
              return (
                <line key={`k${i}`} x1={x1} x2={x1 + (x2 - x1) * cp} y1={Y(c.to)} y2={Y(c.to)} stroke="rgba(255,255,255,.55)"
                  strokeWidth={2 * k} strokeDasharray={`${6 * k} ${5 * k}`} />
              );
            })}
            {cols.map((c, i) => {
              const at = at0 + i * step;
              const exI = exitOf(frame, dur, nC - 1 - i, nC);
              const g = ramp(frame, at, c.kind === "total" ? GROW + 10 : GROW, inOut) * (1 - exI);
              if (g <= 0.001) return null;
              const curV = c.from + (c.to - c.from) * g;
              const y1 = Y(c.from), y2 = Y(curV);
              const x = cw * (i + 0.5) - bw / 2;
              const top = Math.min(y1, y2), h = Math.max(1, Math.abs(y2 - y1));
              return (
                <g key={i}>
                  <rect x={x} y={top} width={bw} height={h} rx={3 * k} fill={colOf(c.kind)}
                    style={c.kind === "total" ? { filter: `drop-shadow(0 0 ${14 * k}px ${accent}88)` } : undefined} />
                  <rect x={x} y={top} width={bw} height={h} rx={3 * k} fill={`url(#${id}s)`} />
                  <rect x={x} y={y2 <= y1 ? y2 : y2 - 3 * k} width={bw} height={3 * k} fill="#fff" opacity={0.55} />
                </g>
              );
            })}
          </svg>
          {cols.map((c, i) => {
            const at = at0 + i * step;
            const up = c.to >= c.from;
            const yEnd = Y(c.to);
            const isDelta = c.kind === "up" || c.kind === "down";
            const ls = lines(cap(c.label), 12).slice(0, 2);
            return (
              <React.Fragment key={i}>
                <div style={{ position: "absolute", left: cw * (i + 0.5), top: up ? yEnd - 10 * k : yEnd + 10 * k,
                  transform: up ? "translate(-50%, -100%)" : "translate(-50%, 0)", whiteSpace: "nowrap" }}>
                  {isDelta ? (
                    <Rise at={at + GROW - 4}>
                      <span style={{ display: "block", fontFamily: DISPLAY, fontSize: 44 * k, lineHeight: 1,
                        color: colOf(c.kind) }}>{signed(c.delta)}</span>
                    </Rise>
                  ) : (
                    <Rise at={at + 4}>
                      <Odometer value={Math.abs(c.to)} at={at + 4} frames={Math.round(fps * 0.9)}
                        size={(c.kind === "total" ? 62 : 50) * k} color={c.kind === "total" ? accent : "#fff"}
                        prefix={(c.to < 0 ? "−" : "") + prefix} suffix={tail(suffix)} suffixScale={0.45} />
                    </Rise>
                  )}
                </div>
                <div style={{ position: "absolute", left: cw * i, width: cw, top: NAMES, display: "flex",
                  flexDirection: "column", alignItems: "center" }}>
                  {ls.map((ln, j) => (
                    <Rise key={j} at={at + j * 2}>
                      <span style={{ display: "block", fontFamily: LABEL, fontWeight: 700, fontSize: 26 * k,
                        letterSpacing: "0.06em", lineHeight: 1.05, textAlign: "center",
                        color: c.kind === "total" ? accent : "rgba(255,255,255,.82)" }}>{ln}</span>
                    </Rise>
                  ))}
                </div>
              </React.Fragment>
            );
          })}
        </div>
      </div>
    </Card>
  );
};

// ================================================================== 7. bullet chart
/**
 * A figure against its target: qualitative bands wipe open along a wide
 * track (overlay.items as band limits, else poor / fair / good), the target
 * marker drops in from above with a bounce, the accent value bar races toward
 * it while the big number rolls, and a bracket draws the gap: "8% SHORT" in
 * red (or "OVER" in green). value = the figure, total = the target.
 */
const BulletChart: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const value = toNum(overlay.value);
  if (!Number.isFinite(value)) return null;
  const target = toNum(overlay.total);
  const hasT = Number.isFinite(target) && target > 0;
  const suffix = String(overlay.suffix ?? "").trim();
  const prefix = String(overlay.prefix ?? "").trim();
  const pct = suffix === "%";
  const bandsIn = nums(overlay.items, 3).filter((b) => b.value > 0).sort((a, b) => a.value - b.value);
  const hi = Math.max(value, hasT ? target : 0, ...bandsIn.map((b) => b.value), 1e-9);
  const sc = pct && hi > 60 && hi <= 100 ? niceScale(0, 100, 4) : niceScale(0, hi * 1.12, 4);
  const max = sc.max;
  const td = tickDecimals(sc.step);
  const W = 1360 * k, TH = 118 * k, VH = 42 * k, FLAG = 96 * k;
  const X = (v: number) => (Math.max(0, Math.min(max, v)) / max) * W;
  const custom = bandsIn.length >= 2;
  const th = custom ? bandsIn.map((b) => Math.min(max, b.value)) : [max * 0.5, max * 0.8, max];
  th[th.length - 1] = max;
  const alphas = th.length === 2 ? [0.2, 0.09] : [0.24, 0.15, 0.08];
  const tAt = Math.round(fps * 0.35);
  const vAt = Math.round(fps * 0.55);
  const vGrow = Math.round(fps * 1.2);
  const bAt = vAt + vGrow;
  const ex = exitOf(frame, dur);
  const g = ramp(frame, vAt, vGrow, inOut) * (1 - ex);
  const pT = ramp(frame, tAt, 16, backOut);
  const liftT = exitOf(frame, dur, 1, 2);
  const bP = ramp(frame, bAt, 14, inOut) * (1 - ex);
  const xv = X(value), xt = hasT ? X(target) : 0;
  const diff = hasT ? target - value : 0;
  const short = diff > 0;
  const onTarget = hasT && Math.abs(xt - xv) <= 12 * k;
  const bCol = short && !onTarget ? RED : GREEN;
  const bx1 = Math.min(xv, xt), bx2 = Math.max(xv, xt);
  const BY = FLAG + TH + 78 * k;
  const HT = BY + 70 * k;
  const ratio = hasT ? Math.round((value / target) * 100) : 0;
  const tRaw = cap(overlay.label).replace(/\s+/g, " ").trim();
  const tName = !tRaw ? "TARGET" : tRaw.length > 16 ? `${tRaw.slice(0, 15).trim()}…` : tRaw;
  const clampX = (x: number) => Math.max(90 * k, Math.min(W - 90 * k, x));
  // The target block on the right ("GOAL / 15% / 47% OF GOAL") and the room it leaves the title.
  const rightW = hasT ? Math.max(200, (tName.length + 8) * 17) * k : 0;
  return (
    <Card overlay={overlay}>
      <div style={{ width: W, display: "flex", flexDirection: "column", gap: 18 * k }}>
        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 40 * k }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 * k }}>
            <ChartTitle text={overlay.text} accent={accent} size={52} maxW={W - rightW - 40 * k} />
            <Rise at={vAt - 4}>
              <Odometer value={Math.abs(value)} at={vAt} frames={vGrow} size={150 * k} color="#fff"
                prefix={(value < 0 ? "−" : "") + prefix} suffix={tail(suffix)} suffixColor={accent} suffixScale={0.45} />
            </Rise>
          </div>
          {hasT ? (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 * k, marginBottom: 14 * k,
              flexShrink: 0, whiteSpace: "nowrap" }}>
              <Rise at={tAt + 4}>
                <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: 28 * k, letterSpacing: "0.22em",
                  color: "rgba(255,255,255,.6)" }}>{tName}</span>
              </Rise>
              <Rise at={tAt + 6}>
                <Odometer value={target} at={tAt + 6} frames={Math.round(fps * 0.9)} size={78 * k} color="#fff"
                  prefix={prefix} suffix={tail(suffix)} suffixScale={0.5} />
              </Rise>
              <Rise at={bAt}>
                <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: 32 * k, letterSpacing: "0.08em",
                  color: short ? accent : GREEN }}>{ratio}% OF {tName}</span>
              </Rise>
            </div>
          ) : null}
        </div>
        <div style={{ position: "relative", width: W, height: HT }}>
          <svg width={W} height={HT} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
            {th.map((t, j) => {
              const x0 = j === 0 ? 0 : X(th[j - 1]);
              const w = Math.max(0, X(t) - x0);
              const p = ramp(frame, 3 + j * 4, 16, inOut) * (1 - exitOf(frame, dur, th.length - 1 - j, th.length));
              return (
                <rect key={j} x={x0} y={FLAG} width={w * p} height={TH}
                  fill={`rgba(255,255,255,${alphas[j] ?? 0.08})`} />
              );
            })}
            {sc.ticks.filter((t) => t <= max + 1e-9).map((t, i, arr) => {
              const tp = ramp(frame, 8 + i * 2, 12);
              return (
                <g key={`t${i}`} opacity={tp * (1 - ex)}>
                  <line x1={X(t)} x2={X(t)} y1={FLAG + TH} y2={FLAG + TH + 12 * k} stroke="rgba(255,255,255,.6)"
                    strokeWidth={2 * k} />
                  <text x={X(t)} y={FLAG + TH + 40 * k} textAnchor={i === 0 ? "start" : i === arr.length - 1 ? "end" : "middle"}
                    fontFamily={LABEL} fontWeight={600} fontSize={24 * k} fill="rgba(255,255,255,.55)"
                    transform={drift(tp, ex, k)}>
                    {prefix}{fmtD(t, td)}{pct ? "%" : ""}</text>
                </g>
              );
            })}
            {g > 0.001 ? (
              <>
                <rect x={0} y={FLAG + (TH - VH) / 2} width={xv * g} height={VH} fill={accent} />
                {g < 0.995 ? (
                  <rect x={Math.max(0, xv * g - 4 * k)} y={FLAG + (TH - VH) / 2} width={4 * k} height={VH} fill="#fff" />
                ) : null}
              </>
            ) : null}
            {hasT && pT > 0.01 ? (
              <g opacity={1 - liftT} transform={`translate(0 ${-(1 - pT) * 90 * k - liftT * 60 * k})`}>
                <rect x={xt - 4 * k} y={FLAG - 22 * k} width={8 * k} height={TH + 44 * k} fill="#fff" />
              </g>
            ) : null}
            {hasT && !onTarget && bP > 0.001 ? (
              <path d={`M${bx1} ${BY - 16 * k} V${BY} H${bx2} V${BY - 16 * k}`} fill="none" stroke={bCol}
                strokeWidth={3 * k} strokeLinejoin="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - bP} />
            ) : null}
          </svg>
          {custom ? th.map((t, j) => {
            const x0 = j === 0 ? 0 : X(th[j - 1]);
            if (X(t) - x0 < 110 * k || !bandsIn[j]) return null;
            // A band's name stays inside its band (cut with an ellipsis rather than running into the next).
            return (
              <div key={`b${j}`} style={{ position: "absolute", left: x0 + 14 * k, top: FLAG + 8 * k,
                maxWidth: X(t) - x0 - 28 * k }}>
                <Rise at={8 + j * 4} style={{ maxWidth: "100%" }}>
                  <span style={{ display: "block", fontFamily: LABEL, fontWeight: 700, fontSize: 24 * k,
                    letterSpacing: "0.16em", color: "rgba(255,255,255,.72)", whiteSpace: "nowrap", overflow: "hidden",
                    textOverflow: "ellipsis" }}>
                    {cap(bandsIn[j].label)}</span>
                </Rise>
              </div>
            );
          }) : null}
          {hasT ? (
            <div style={{ position: "absolute", left: clampX(xt), top: FLAG - 30 * k, transform: "translate(-50%, -100%)" }}>
              <Rise at={tAt + 8}>
                <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: 26 * k, letterSpacing: "0.18em",
                  color: "#fff", whiteSpace: "nowrap" }}>{"▼"} {tName}</span>
              </Rise>
            </div>
          ) : null}
          {hasT ? (
            <div style={{ position: "absolute", left: clampX(onTarget ? xt : (bx1 + bx2) / 2), top: BY + 12 * k,
              transform: "translateX(-50%)" }}>
              <Rise at={bAt + 6}>
                <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: 32 * k, letterSpacing: "0.1em",
                  color: bCol, whiteSpace: "nowrap" }}>
                  {onTarget ? `ON ${tName}` : `${prefix}${fmt(Math.abs(diff))}${tail(suffix)} ${short ? "SHORT" : "OVER"}`}
                </span>
              </Rise>
            </div>
          ) : null}
        </div>
      </div>
    </Card>
  );
};

// ================================================================== 8. radial bars
/**
 * Concentric 270° bars: faint tracks and spokes appear, then each ring sweeps
 * clockwise from twelve o'clock to its share of the scale, a white bead on its
 * tip and the live value riding just ahead of it; names sit at each ring's
 * start, the highlighted ring glows in the accent and its figure rolls in the
 * centre. Rings unwind on the way out.
 */
const RadialBars: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const items = nums(overlay.items, 5).map((i) => ({ ...i, value: Math.max(0, i.value) }));
  if (items.length < 2) return null;
  const n = items.length;
  const { suffix, prefix, pct } = units(overlay, items);
  const hiV = Math.max(...items.map((i) => i.value), 1e-9);
  const max = pct && hiV <= 100 ? 100 : hiV;
  const hot = pickHot(items, overlay.highlight);
  const SW = (n > 4 ? 34 : 40) * k, GP = (n > 4 ? 13 : 16) * k, R0 = 290 * k;
  const S = 2 * (R0 + SW / 2 + 60 * k);
  const cx = S / 2, cy = S / 2;
  const SWEEP = Math.PI * 1.5;
  const rOf = (i: number) => R0 - i * (SW + GP);
  const rIn = rOf(n - 1) - SW / 2;
  const at0 = Math.round(fps * 0.4);
  const stagger = Math.max(3, Math.round(fps * 0.14));
  const sweepF = Math.round(fps * 1.3);
  const greys = ["#f0f0f3", "#c5c7ce", "#9a9ca6", "#777a84"];
  let gi = 0;
  const colorOf = items.map((_, i) => (i === hot ? accent : greys[Math.min(greys.length - 1, gi++)]));
  const dAll = Math.max(0, ...items.map((i) => decOf(i.value)));
  const unitTip = suffix === "%" ? "%" : suffix && suffix.length <= 3 ? ` ${suffix}` : "";
  const ex = exitOf(frame, dur);
  const pt = (r: number, a: number): [number, number] => [cx + r * Math.sin(a), cy - r * Math.cos(a)];
  const arcD = (r: number, a: number) => {
    if (a <= 1e-4) return "";
    const [x, y] = pt(r, Math.min(a, Math.PI * 2 - 1e-3));
    return `M${cx} ${(cy - r).toFixed(2)} A${r} ${r} 0 ${a > Math.PI ? 1 : 0} 1 ${x.toFixed(2)} ${y.toFixed(2)}`;
  };
  const COLW = 520 * k;
  // ~30 characters of 30 px Barlow Condensed fill the 520 px column without an orphan word.
  const sub = lines(cap(overlay.subtitle), 30).slice(0, 3);
  const qs = [0, 0.25, 0.5, 0.75, 1];
  return (
    <Card overlay={overlay}>
      <div style={{ display: "flex", alignItems: "center", gap: 70 * k }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 20 * k, width: COLW }}>
          <ChartTitle text={overlay.text} accent={accent} size={54} maxW={COLW} />
          {sub.map((ln, i) => (
            <Rise key={i} at={10 + i * 3}>
              <span style={{ display: "block", fontFamily: LABEL, fontWeight: 600, fontSize: 30 * k, letterSpacing: "0.06em",
                lineHeight: 1.1, color: "rgba(255,255,255,.78)" }}>{ln}</span>
            </Rise>
          ))}
        </div>
        <div style={{ position: "relative", width: S, height: S }}>
          <svg width={S} height={S} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
            {qs.map((q, i) => {
              const a = SWEEP * q;
              const [x1, y1] = pt(rIn - 6 * k, a);
              const [x2, y2] = pt(R0 + SW / 2 + 6 * k, a);
              const [tx, ty] = pt(R0 + SW / 2 + 32 * k, a);
              const tp = ramp(frame, 2 + i * 2, 12);
              return (
                <g key={`q${i}`} opacity={tp * (1 - ex)}>
                  <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="rgba(255,255,255,.1)" strokeWidth={1.5 * k} />
                  {pct ? (
                    <text x={tx} y={ty} textAnchor="middle" dominantBaseline="middle" fontFamily={LABEL} fontWeight={600}
                      fontSize={24 * k} fill="rgba(255,255,255,.5)" transform={drift(tp, ex, k)}>
                      {Math.round(q * 100)}%</text>
                  ) : null}
                </g>
              );
            })}
            {items.map((_, i) => (
              <path key={`k${i}`} d={arcD(rOf(i), SWEEP)} fill="none" stroke="rgba(255,255,255,.08)" strokeWidth={SW}
                strokeLinecap="round" opacity={ramp(frame, 2 + i * 2, 12) * (1 - ex)} />
            ))}
            {items.map((it, i) => {
              const at = at0 + i * stagger;
              const exI = exitOf(frame, dur, i, n);
              const g = ramp(frame, at, sweepF, inOut) * (1 - exI);
              const a = SWEEP * Math.min(1, it.value / max) * g;
              const d = arcD(rOf(i), a);
              if (!d) return null;
              const [bx, by] = pt(rOf(i), a);
              const moving = g > 0.02 && g < 0.98 && exI < 0.01;
              return (
                <g key={i}>
                  <path d={d} fill="none" stroke={colorOf[i]} strokeWidth={SW} strokeLinecap="round"
                    style={i === hot ? { filter: `drop-shadow(0 0 ${14 * k}px ${accent}99)` } : undefined} />
                  {moving ? <circle cx={bx} cy={by} r={SW * 0.2} fill={i === hot ? "#fff" : INK} opacity={0.9} /> : null}
                </g>
              );
            })}
          </svg>
          {items.map((it, i) => (
            <div key={`n${i}`} style={{ position: "absolute", right: S - (cx - 24 * k), top: cy - rOf(i),
              transform: "translateY(-50%)", maxWidth: R0 - 40 * k, display: "flex", justifyContent: "flex-end" }}>
              <Rise at={Math.max(0, at0 + i * stagger - 4)} style={{ maxWidth: "100%" }}>
                <span style={{ display: "block", fontFamily: LABEL, fontWeight: 700, fontSize: Math.min(30 * k, SW * 0.8),
                  letterSpacing: "0.06em", color: i === hot ? accent : "rgba(255,255,255,.85)", whiteSpace: "nowrap",
                  overflow: "hidden", textOverflow: "ellipsis" }}>{cap(it.label)}</span>
              </Rise>
            </div>
          ))}
          {items.map((it, i) => {
            const at = at0 + i * stagger;
            if (frame < at) return null;
            const gIn = ramp(frame, at, sweepF, inOut);
            const g = gIn * (1 - exitOf(frame, dur, i, n));
            const r = rOf(i);
            const a = SWEEP * Math.min(1, it.value / max) * g;
            const txt = `${it.prefix || prefix}${fmtD(it.value * gIn, dAll)}${unitTip}`;
            // Centred far enough ahead of the tip that its trailing edge clears the round cap (SW / 2).
            const off = (SW / 2 + 12 * k + txt.length * 9 * k) / r;
            const [tx, ty] = pt(r, a + off);
            return (
              <div key={`v${i}`} style={{ position: "absolute", left: tx, top: ty, transform: "translate(-50%, -50%)",
                whiteSpace: "nowrap" }}>
                <Rise at={at} frames={10}>
                  <span style={{ display: "block", fontFamily: DISPLAY, fontSize: Math.min(40 * k, SW), lineHeight: 1,
                    color: i === hot ? accent : "#fff", textShadow: "0 3px 12px rgba(0,0,0,.7)" }}>{txt}</span>
                </Rise>
              </div>
            );
          })}
          {rIn > 72 * k ? (
            <div style={{ position: "absolute", left: cx, top: cy, transform: "translate(-50%, -50%)" }}>
              <Rise at={at0 + hot * stagger + sweepF - 12}>
                <Odometer value={items[hot].value} at={at0 + hot * stagger + sweepF - 12} frames={Math.round(fps * 0.8)}
                  size={Math.min(84 * k, rIn * 0.72)} color="#fff" prefix={items[hot].prefix || prefix}
                  suffix={unitTip} suffixColor={accent} suffixScale={0.5} />
              </Rise>
            </div>
          ) : null}
        </div>
      </div>
    </Card>
  );
};

// ================================================================== 9. heat strip
/**
 * A row of cells (years, months, places) coloured by intensity, dark to the
 * accent to white-hot: the cells flip up one after another on their bottom
 * hinge like a departures board, each value rising inside its cell; a light
 * sweeps along the strip, the peak cell glows with a "PEAK" pointer, and a
 * gradient legend gives the low and high ends. Cells flip away at the end.
 */
const HeatStrip: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const items = nums(overlay.items, 14);
  if (items.length < 3) return null;
  const n = items.length;
  const { suffix, prefix } = units(overlay, items);
  const vals = items.map((i) => i.value);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const norm = (v: number) => (hi - lo > 1e-9 ? (v - lo) / (hi - lo) : 0.6);
  const hot3 = mix(0.5, [0, 1], [accent, "#ffffff"]);
  const heat = (q: number) => mix(Math.max(0, Math.min(1, q)), [0, 0.62, 1], ["#2a2e38", accent, hot3]);
  const peak = pickHot(items, overlay.highlight);
  const peakWord = vals[peak] >= hi ? "PEAK" : "";
  const GAP = (n > 10 ? 6 : 10) * k;
  const cw = Math.min((n <= 5 ? 190 : 150) * k, (1560 * k - GAP * (n - 1)) / n);
  const CH = 240 * k;
  const SWD = n * cw + (n - 1) * GAP;
  // A short strip is centred in a box of at least 900 px, so the title and the legend keep their room.
  const narrow = SWD < 900 * k;
  const BOXW = Math.max(SWD, 900 * k);
  const at0 = Math.round(fps * 0.35);
  const stagger = Math.max(2, Math.min(5, Math.round((fps * 1.1) / n)));
  const waveEnd = at0 + (n - 1) * stagger + 16;
  const sweep = interpolate(frame, [waveEnd + 4, waveEnd + 4 + Math.round(fps * 1.1)], [-260 * k, SWD + 60 * k],
    { ...clamp, easing: inOut });
  const pulse = 0.5 + 0.5 * Math.sin((frame / fps) * Math.PI * 1.6);
  const texts = items.map((it) => `${it.value < 0 ? "−" : ""}${it.prefix || prefix}${fmt(Math.abs(it.value))}` +
    `${suffix === "%" ? "%" : ""}`);
  const longest = Math.max(...texts.map((t) => t.length), 2);
  const fs = Math.min(60 * k, (cw * 0.84) / (longest * 0.44));
  const lblFs = (n > 10 ? 24 : 28) * k;
  const ex = exitOf(frame, dur);
  const lp = ramp(frame, waveEnd + 4, 18, inOut) * (1 - ex);
  const legend = (v: number) => `${v < 0 ? "−" : ""}${prefix}${fmt(Math.abs(v))}${tail(suffix)}`;
  return (
    <Card overlay={overlay}>
      <div style={{ width: BOXW, display: "flex", flexDirection: "column", gap: 10 * k, alignItems: "stretch" }}>
        <ChartTitle text={overlay.text} accent={accent} center={narrow} maxW={BOXW} />
        <div style={{ display: "flex", gap: GAP, justifyContent: "center" }}>
          {items.map((it, i) => {
            const at = at0 + i * stagger;
            const p = ramp(frame, at, 18, backOut);
            const exI = exitOf(frame, dur, i, n);
            const ang = (1 - p) * -92 + exI * 92;
            const q = norm(it.value);
            const isPeak = i === peak;
            const cellX = i * (cw + GAP);
            return (
              <div key={i} style={{ width: cw, display: "flex", flexDirection: "column", alignItems: "center", gap: 12 * k }}>
                <div style={{ height: 58 * k, display: "flex", alignItems: "flex-end" }}>
                  {isPeak ? (
                    <Rise at={waveEnd + 2}>
                      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", fontFamily: LABEL,
                        fontWeight: 800, fontSize: 24 * k, letterSpacing: "0.16em", color: accent, lineHeight: 1 }}>
                        {peakWord ? <span>{peakWord}</span> : null}
                        <span style={{ fontSize: 20 * k, marginTop: 4 * k }}>{"▼"}</span>
                      </div>
                    </Rise>
                  ) : null}
                </div>
                <div style={{ position: "relative", width: cw, height: CH, borderRadius: 6 * k, overflow: "hidden",
                  background: heat(q), opacity: frame >= at ? 1 - exI * 0.4 : 0,
                  transform: `perspective(${900 * k}px) rotateX(${ang}deg)`, transformOrigin: "50% 100%",
                  boxShadow: isPeak
                    ? `0 0 ${(18 + 16 * pulse) * k}px ${accent}88, inset 0 0 0 ${3 * k}px #fff`
                    : `0 ${12 * k}px ${26 * k}px rgba(0,0,0,.35), inset 0 0 0 ${1.5 * k}px rgba(255,255,255,.12)` }}>
                  <div style={{ position: "absolute", inset: 0,
                    background: "linear-gradient(180deg, rgba(255,255,255,.16) 0%, rgba(255,255,255,0) 40%, rgba(0,0,0,.22) 100%)" }} />
                  <div style={{ position: "absolute", inset: 0, background: "#000",
                    opacity: Math.max(0, Math.min(0.7, (1 - p) * 0.7)) }} />
                  <div style={{ position: "absolute", top: 0, bottom: 0, left: sweep - cellX, width: 200 * k,
                    background: "linear-gradient(100deg, rgba(255,255,255,0), rgba(255,255,255,.22), rgba(255,255,255,0))" }} />
                  <div style={{ position: "absolute", left: 0, right: 0, bottom: 18 * k, display: "flex",
                    justifyContent: "center" }}>
                    <Rise at={at + 8}>
                      <span style={{ display: "block", fontFamily: DISPLAY, fontSize: fs, lineHeight: 1,
                        color: q > 0.45 ? INK : "#fff" }}>{texts[i]}</span>
                    </Rise>
                  </div>
                </div>
                <Rise at={at + 4} style={{ maxWidth: cw + GAP }}>
                  <span style={{ display: "block", fontFamily: LABEL, fontWeight: isPeak ? 800 : 700, fontSize: lblFs,
                    letterSpacing: "0.06em", color: isPeak ? accent : "rgba(255,255,255,.8)", whiteSpace: "nowrap",
                    overflow: "hidden", textOverflow: "ellipsis", textAlign: "center" }}>
                    {cap(it.label)}</span>
                </Rise>
              </div>
            );
          })}
        </div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 30 * k, marginTop: 10 * k,
          alignSelf: "stretch" }}>
          <div style={{ minWidth: 0 }}>
            {overlay.subtitle ? (
              <Rise at={waveEnd}>
                <span style={{ display: "block", fontFamily: LABEL, fontWeight: 700, fontSize: 30 * k, letterSpacing: "0.1em",
                  color: "rgba(255,255,255,.82)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {cap(overlay.subtitle)}</span>
              </Rise>
            ) : null}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 14 * k, flexShrink: 0 }}>
            <Rise at={waveEnd + 4}>
              <span style={{ display: "block", fontFamily: LABEL, fontWeight: 700, fontSize: 24 * k,
                color: "rgba(255,255,255,.7)", whiteSpace: "nowrap" }}>{legend(lo)}</span>
            </Rise>
            <div style={{ width: 300 * k, height: 12 * k, borderRadius: 6 * k,
              background: `linear-gradient(90deg, #2a2e38, ${accent} 62%, ${hot3})`,
              clipPath: `inset(0 ${(1 - lp) * 100}% 0 0)` }} />
            <Rise at={waveEnd + 8}>
              <span style={{ display: "block", fontFamily: LABEL, fontWeight: 700, fontSize: 24 * k,
                color: "rgba(255,255,255,.7)", whiteSpace: "nowrap" }}>{legend(hi)}</span>
            </Rise>
          </div>
        </div>
      </div>
    </Card>
  );
};

// ================================================================== 10. histogram
/**
 * Dense bins (up to 24, nearly touching) rising in a wave from the left with a little
 * overshoot, then breathing in a slow travelling ripple; the highlighted
 * column (overlay.highlight, else the tallest) turns to the accent, a leader
 * line draws up from it to a callout with its rolling value and name. The
 * columns sink back in a reverse wave at the end.
 */
const Histogram: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const items = nums(overlay.items, 24).map((i) => ({ ...i, value: Math.max(0, i.value) }));
  if (items.length < 4) return null;
  const n = items.length;
  const { suffix, prefix } = units(overlay, items);
  const vals = items.map((i) => i.value);
  const hot = pickHot(items, overlay.highlight);
  const sc = niceScale(0, Math.max(...vals, 1e-9) * 1.02, 3);
  const td = tickDecimals(sc.step);
  const W = 1440 * k, H = 400 * k, TOP = 170 * k, BOT = 56 * k;
  const HT = TOP + H + BOT;
  const colW = W / n;
  // Histogram bins sit almost edge to edge (a thin gutter), which is what separates this look from a bar chart.
  const gutter = Math.max(3 * k, colW * (n > 16 ? 0.12 : 0.1));
  const bw = Math.max(4 * k, Math.min(180 * k, colW - gutter));
  const rad = Math.min(4 * k, bw / 3);
  const at0 = Math.round(fps * 0.35);
  const stagger = Math.max(1, Math.min(4, Math.round((fps * 0.9) / n)));
  const RISE = 20;
  const settle = at0 + (n - 1) * stagger + RISE;
  const live = ramp(frame, settle, 20);
  const ex = exitOf(frame, dur);
  const step = Math.max(1, Math.ceil(n / 8));
  const hAt = at0 + hot * stagger + RISE;
  const cP = ramp(frame, hAt + 2, 14, inOut) * (1 - ex);
  const hx = colW * (hot + 0.5);
  const hTop = TOP + H - (vals[hot] / sc.max) * H;
  const CY = TOP - 22 * k;
  const hotName = cap(items[hot].label).slice(0, 24);
  const subRaw = cap(overlay.subtitle).replace(/\s+/g, " ").trim();
  const sub = subRaw.length > 32 ? `${subRaw.slice(0, 31).trim()}…` : subRaw;
  // The callout's width (rolling number + name / subtitle), so it can be kept whole inside the chart.
  const unitH = tail(items[hot].suffix || suffix);
  const calloutW = (fmt(items[hot].value).length + (items[hot].prefix || prefix).length) * 36 * k +
    unitH.length * 19 * k + 16 * k + Math.max(hotName.length * 17, sub.length * 14) * k;
  const calloutX = Math.max(calloutW / 2, Math.min(W - calloutW / 2, hx));
  const ly1 = hTop - 12 * k;
  return (
    <Card overlay={overlay}>
      <div style={{ width: W, display: "flex", flexDirection: "column", gap: 6 * k }}>
        <ChartTitle text={overlay.text} accent={accent} maxW={W} />
        <div style={{ position: "relative", width: W, height: HT }}>
          <svg width={W} height={HT} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
            {sc.ticks.filter((t) => t > 0).map((t, i) => {
              const y = TOP + H - (t / sc.max) * H;
              const tp = ramp(frame, 2 + i * 2, 12);
              return (
                <g key={`g${i}`} opacity={tp * (1 - ex)}>
                  <line x1={0} x2={W} y1={y} y2={y} stroke="rgba(255,255,255,.1)" strokeWidth={1.5 * k}
                    strokeDasharray={`${6 * k} ${8 * k}`} />
                  <text x={-14 * k} y={y + 8 * k} textAnchor="end" fontFamily={LABEL} fontWeight={600} fontSize={24 * k}
                    fill="rgba(255,255,255,.55)" transform={drift(tp, ex, k)}>
                    {prefix}{fmtD(t, td)}{suffix === "%" ? "%" : ""}</text>
                </g>
              );
            })}
            <line x1={0} x2={W * ramp(frame, 0, 18, inOut) * (1 - ex)} y1={TOP + H} y2={TOP + H}
              stroke="rgba(255,255,255,.8)" strokeWidth={3 * k} />
            {cP > 0.001 ? (
              <>
                <line x1={hx} x2={hx} y1={ly1} y2={ly1 - (ly1 - CY) * cP} stroke={accent} strokeWidth={2.5 * k} />
                <circle cx={hx} cy={ly1} r={6 * k * Math.min(1, cP * 3)} fill={accent} />
              </>
            ) : null}
          </svg>
          {items.map((it, i) => {
            const at = at0 + i * stagger;
            const p = ramp(frame, at, RISE, backOut);
            const exI = exitOf(frame, dur, n - 1 - i, n);
            const wave = 1 + 0.025 * live * Math.sin((frame / fps) * 3.2 - i * 0.55 - seeded(i) * 0.8);
            const h = Math.max(0, (it.value / sc.max) * H * p * wave * (1 - exI));
            const isHot = i === hot;
            if (h <= 0.5) return null;
            return (
              <div key={i} style={{ position: "absolute", left: colW * i + (colW - bw) / 2, top: TOP + H - h, width: bw,
                height: h, borderRadius: `${rad}px ${rad}px 0 0`,
                background: isHot ? `linear-gradient(180deg, ${accent}, ${accent}bb)`
                  : "linear-gradient(180deg, rgba(255,255,255,.92), rgba(255,255,255,.3))",
                boxShadow: isHot ? `0 0 ${26 * k}px ${accent}88` : "none" }} />
            );
          })}
          {items.map((it, i) => {
            const isHot = i === hot;
            const show = isHot || (i % step === 0 && Math.abs(i - hot) >= Math.max(1, step * 0.6));
            if (!show) return null;
            return (
              <div key={`x${i}`} style={{ position: "absolute", left: colW * (i + 0.5), top: TOP + H + 12 * k,
                transform: "translateX(-50%)" }}>
                <Rise at={at0 + i * stagger + 6}>
                  <span style={{ display: "block", fontFamily: LABEL, fontWeight: isHot ? 800 : 600,
                    fontSize: (isHot ? 28 : 24) * k, letterSpacing: "0.04em", whiteSpace: "nowrap",
                    color: isHot ? accent : "rgba(255,255,255,.6)" }}>{cap(it.label)}</span>
                </Rise>
              </div>
            );
          })}
          <div style={{ position: "absolute", left: calloutX, top: CY - 6 * k, transform: "translate(-50%, -100%)",
            display: "flex", alignItems: "flex-end", gap: 16 * k, whiteSpace: "nowrap" }}>
            <Rise at={hAt}>
              <Odometer value={items[hot].value} at={hAt} frames={Math.round(fps * 0.9)} size={84 * k} color={accent}
                prefix={items[hot].prefix || prefix} suffix={unitH} suffixScale={0.45} />
            </Rise>
            <div style={{ display: "flex", flexDirection: "column", gap: 2 * k, paddingBottom: 8 * k }}>
              <Rise at={hAt + 4}>
                <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k, letterSpacing: "0.08em",
                  color: "#fff" }}>{hotName}</span>
              </Rise>
              {sub ? (
                <Rise at={hAt + 7}>
                  <span style={{ display: "block", fontFamily: LABEL, fontWeight: 600, fontSize: 24 * k,
                    letterSpacing: "0.08em", color: "rgba(255,255,255,.65)" }}>{sub}</span>
                </Rise>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </Card>
  );
};

// ================================================================== registry
export const LOOKS: Record<string, Look> = {
  "ca-bar-race": BarRace,
  "ca-stacked-column": StackedColumn,
  "ca-grouped-bars": GroupedBars,
  "ca-lollipop": Lollipop,
  "ca-dot-plot": DotPlot,
  "ca-waterfall": Waterfall,
  "ca-bullet": BulletChart,
  "ca-radial-bars": RadialBars,
  "ca-heat-strip": HeatStrip,
  "ca-histogram": Histogram,
};
