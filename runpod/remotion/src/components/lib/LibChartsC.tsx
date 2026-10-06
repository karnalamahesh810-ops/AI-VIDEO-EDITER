import React from "react";
import { AbsoluteFill, Audio, Easing, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { SafeImg } from "../motion/safePicture";
import { DISPLAY, LABEL, MONO } from "../fonts";
import type { Overlay, OverlayItem, SceneMedia } from "../../types";
import { Odometer, Scrim, formatValue, lines, ramp, useHold, useK } from "../pro/ProGraphics";
import { CaseBackdrop } from "../pro/ProCase";

// The owner (2026-09-29): a look's own sounds sit at ~40% of their old level.
const IN_LOOK_SFX_SCALE = 0.4;

/**
 * Charts III (family "cc-"): charts that draw POINT BY POINT, the GoMotion
 * way. Every point, bar or node lands with its own soft tick (sfx/pop.mp3,
 * never more than twelve of them) and parks its value where it lands. The
 * six "ticker" looks paint their own dark, clean canvas with a small title
 * top-left and the source (subtitle) bottom-left; the two "tick" cards sit
 * on the Scrim like Charts I; the three diagrams paint flat black or the
 * case-file dark backdrop.
 *
 *   cc-line-ticker       a line drawing point by point, the value riding the head, a red/accent end badge
 *   cc-bars-ticker       horizontal bars growing one after another, values at their ends
 *   cc-columns-ticker    columns rising one after another, values above them
 *   cc-planned-vs-actual two columns, a diagonal drop line between them, the difference in a badge
 *   cc-two-series        two lines drawing together (value + a second number in text, else a trend)
 *   cc-snow-sites        item values as dots along one axis, the last one red and labelled
 *   cc-tick-bars         data card: bars with a bead on the head, a tick and a rolling value per bar
 *   cc-tick-line         data card: a monotone line drawn segment by segment, a pill on the end value
 *   cc-circle-row        outlined circles in a row on black, words inside, connectors between
 *   cc-network-tree      a hub chip, a trunk and right-angled branches to labelled photo tiles
 *   cc-wave-chain        a sine wave on black, labels at its crests and troughs
 *
 * Deterministic (no Math.random / Date), 1080p-referenced sizes times k.
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;
type Num = { label: string; value: number; text?: string; suffix?: string; prefix?: string };
type Pt = [number, number];

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const expoOut = Easing.bezier(0.16, 1, 0.3, 1);
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const exitEase = Easing.bezier(0.7, 0, 0.84, 0);
const RED = "#ff3b30";
const GREEN = "#27d17f";
const CYAN = "#53c8ff";
const INK = "#0c0c0f";
const GREY = "#8a8d96";
// Ticks per chart. 12 per look, eleven charts in a row, made the local
// renderer lose frames of the clip underneath (QA reel F); six still read as
// one tick per point on a typical chart.
const TICK_MAX = 6;

// ------------------------------------------------------------------ data helpers
/** A text field as a string (a number is spelled out; anything else is ""). */
const str = (s: unknown): string =>
  typeof s === "string" ? s : typeof s === "number" && Number.isFinite(s) ? String(s) : "";
/** Upper case of a text field that may arrive as a number or be missing (never throws). */
const cap = (s?: unknown) => str(s).toUpperCase();
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
      label: str((it as { label?: unknown }).label).trim(),
      value: v,
      text: typeof it.text === "string" ? it.text : undefined,
      suffix: typeof ex.suffix === "string" ? ex.suffix : undefined,
      prefix: typeof ex.prefix === "string" ? ex.prefix : undefined,
    });
    if (out.length >= max) break;
  }
  return out;
};
/** The items that carry a label (a value is optional), at most `max`. */
const itemsOf = (ov: Overlay, max: number): OverlayItem[] => {
  const items: OverlayItem[] = Array.isArray(ov.items) ? ov.items : [];
  return items
    .filter((it): it is OverlayItem => !!it && typeof it === "object" && str((it as { label?: unknown }).label).trim().length > 0)
    .slice(0, max);
};
const stillOf = (m: SceneMedia | null | undefined): string => {
  if (!m || typeof m !== "object") return "";
  const s = m.type === "image" ? m.url : m.thumbnail;
  return typeof s === "string" ? s.trim() : "";
};
/** The overlay's pictures as still URLs (a video gives its thumbnail). */
const stills = (ov: Overlay, max: number): string[] => {
  const media: SceneMedia[] = Array.isArray(ov.media) ? ov.media : [];
  return media.map((m) => stillOf(m)).filter((s) => s.length > 0).slice(0, max);
};
const units = (ov: Overlay, items: Num[]) => {
  const suffix = str(ov.suffix || items.find((i) => i.suffix)?.suffix).trim();
  const prefix = str(ov.prefix || items.find((i) => i.prefix)?.prefix).trim();
  return { suffix, prefix, pct: suffix === "%" };
};
/** The suffix as drawn after a number: "%" tight, a unit after a space. */
const tail = (s: string) => (!s ? "" : s === "%" ? "%" : ` ${s}`);
const fmt = (v: number) => formatValue(v).text;
const f1 = (v: number): string => (Number.isFinite(v) ? v.toFixed(1) : "0");
/** The decimals a value needs: at most 2 below 10, 1 below 100, none above. */
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
/** A value axis for a series: from zero when the data sits well above it, else padded around the data. */
const seriesScale = (vals: number[]) => {
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const span = hi - lo || Math.abs(hi) || 1;
  const zero = lo >= 0 && lo <= hi * 0.5;
  return niceScale(zero ? 0 : lo - span * 0.18, hi + span * 0.12, 4);
};
/** Axis annotations settle up into place and lift away with the exit (never a plain fade). */
const drift = (pin: number, pout: number, k: number) => `translate(0 ${((1 - pin) * 12 - pout * 12) * k})`;
/** The item the narration points at (overlay.highlight), else the largest. */
const pickHot = (items: Num[], h?: unknown): number => {
  const q = str(h).trim().toLowerCase();
  if (q) {
    const exact = items.findIndex((i) => i.label.toLowerCase() === q);
    if (exact >= 0) return exact;
    const part = items.findIndex((i) => i.label.length > 0 &&
      (i.label.toLowerCase().includes(q) || q.includes(i.label.toLowerCase())));
    if (part >= 0) return part;
  }
  return items.reduce((m, it, i) => (it.value > items[m].value ? i : m), 0);
};
/** The index of the x label the narration points at (overlay.highlight), else -1. */
const pickNamed = (items: Num[], h?: unknown): number => {
  const q = str(h).trim().toLowerCase();
  if (!q) return -1;
  const exact = items.findIndex((i) => i.label.toLowerCase() === q);
  if (exact >= 0) return exact;
  return items.findIndex((i) => i.label.length > 0 && (i.label.toLowerCase().includes(q) || q.includes(i.label.toLowerCase())));
};
/** Percent change first -> last, signed with the typographic minus: "−35%", "+12%". */
const signedPct = (from: number, to: number): string => {
  if (!Number.isFinite(from) || !Number.isFinite(to) || Math.abs(from) < 1e-9) return "";
  const pct = ((to - from) / Math.abs(from)) * 100;
  const a = Math.abs(pct);
  return `${pct < 0 ? "−" : "+"}${a >= 10 ? Math.round(a) : a.toFixed(1)}%`;
};
/** Cut a string to about n characters on a word boundary, ending in an ellipsis. */
const clip = (s: string, n: number) => {
  const t = (s || "").trim();
  if (t.length <= n) return t;
  const cut = t.slice(0, Math.max(1, n - 1));
  const sp = cut.lastIndexOf(" ");
  return `${(sp > n * 0.6 ? cut.slice(0, sp) : cut).replace(/[\s,.;:!?-]+$/, "")}…`;
};
/** "Planned | Actual", "A vs B", "A / B" -> names. */
const splitNames = (s: unknown): string[] =>
  str(s).split(/\s+vs\.?\s+|\s*[|/;]\s*/i).map((x) => x.trim()).filter(Boolean);
/** The most balanced word wrap of `t` into at most `n` lines. */
const wrapInto = (t: string, n: number): string[] => {
  if (n <= 1) return [t];
  for (let c = Math.ceil(t.length / n); c <= t.length; c++) {
    const ls = lines(t, c);
    if (ls.length <= n) return ls;
  }
  return [t];
};
/** A label wrapped into at most `maxLines` at the largest size (up to `max`) whose longest line fits `width`. */
const fitText = (text: string, width: number, max: number, min: number, maxLines = 1, em = 0.56) => {
  const t = text.trim();
  let out = { ls: [t], size: max };
  for (let n = 1; n <= Math.max(1, maxLines); n++) {
    const ls = wrapInto(t, n);
    const longest = Math.max(1, ...ls.map((l) => l.length));
    out = { ls, size: Math.min(max, width / (longest * em)) };
    if (out.size >= min) return out;
  }
  return { ls: out.ls, size: Math.max(min * 0.85, out.size) };
};
/** 0 -> 1 over the exit; element i of n leaves a little after element i-1. */
const exitOf = (frame: number, dur: number, i = 0, n = 1) =>
  ramp(frame, dur - 15 + (n > 1 ? (i / (n - 1)) * 4 : 0), 10, exitEase);
/** The first frame at which an eased ramp from `at` over `n` frames reaches `target`. */
const frameWhen = (at: number, n: number, ease: (x: number) => number, target: number): number => {
  for (let f = 0; f <= n; f++) if (ease(f / Math.max(1, n)) >= target - 1e-6) return at + f;
  return at + n;
};

// ------------------------------------------------------------------ geometry helpers
/** Monotone cubic (Fritsch-Carlson) through points with ascending x: no overshoot. */
const monotone = (xs: number[], ys: number[]): ((x: number) => number) => {
  const n = xs.length;
  if (n < 2) return () => (n ? ys[0] : 0);
  const d: number[] = [];
  for (let i = 0; i < n - 1; i++) d.push((ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i] || 1));
  const m: number[] = new Array<number>(n).fill(0);
  m[0] = d[0];
  m[n - 1] = d[n - 2];
  for (let i = 1; i < n - 1; i++) m[i] = d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2;
  for (let i = 0; i < n - 1; i++) {
    if (d[i] === 0) {
      m[i] = 0;
      m[i + 1] = 0;
      continue;
    }
    const a = m[i] / d[i], b = m[i + 1] / d[i];
    const s = a * a + b * b;
    if (s > 9) {
      const tt = 3 / Math.sqrt(s);
      m[i] = tt * a * d[i];
      m[i + 1] = tt * b * d[i];
    }
  }
  return (x: number) => {
    if (x <= xs[0]) return ys[0];
    if (x >= xs[n - 1]) return ys[n - 1];
    let i = 0;
    while (i < n - 2 && x > xs[i + 1]) i++;
    const h = xs[i + 1] - xs[i] || 1;
    const u = (x - xs[i]) / h;
    const u2 = u * u, u3 = u2 * u;
    const h00 = 2 * u3 - 3 * u2 + 1, h10 = u3 - 2 * u2 + u, h01 = -2 * u3 + 3 * u2, h11 = u3 - u2;
    return h00 * ys[i] + h10 * h * m[i] + h01 * ys[i + 1] + h11 * h * m[i + 1];
  };
};
const curvePath = (f: (x: number) => number, x0: number, x1: number, steps: number, move = true): string => {
  let out = "";
  for (let s = 0; s <= steps; s++) {
    const x = x0 + ((x1 - x0) * s) / steps;
    out += `${s === 0 && move ? "M" : "L"}${f1(x)} ${f1(f(x))} `;
  }
  return out;
};
const lerpPt = (a: Pt, b: Pt, t: number): Pt => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
/** The polyline through pts up to a fractional point index (2.4 = 40% along segment 2), and its head. */
const polyTo = (pts: Pt[], prog: number): { d: string; head: Pt } => {
  const n = pts.length;
  if (!n) return { d: "", head: [0, 0] };
  if (n === 1) return { d: `M${f1(pts[0][0])} ${f1(pts[0][1])}`, head: pts[0] };
  const p = Math.max(0, Math.min(n - 1, prog));
  const i = Math.min(n - 2, Math.floor(p));
  const head = lerpPt(pts[i], pts[i + 1], p - i);
  let d = `M${f1(pts[0][0])} ${f1(pts[0][1])}`;
  for (let j = 1; j <= i; j++) d += ` L${f1(pts[j][0])} ${f1(pts[j][1])}`;
  return { d: `${d} L${f1(head[0])} ${f1(head[1])}`, head };
};
const cumOf = (pts: Pt[]) => {
  const c = [0];
  for (let i = 1; i < pts.length; i++) c.push(c[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  return c;
};
const along = (pts: Pt[], cum: number[], run: number): { p: Pt; i: number; ang: number } => {
  if (pts.length < 2) return { p: pts[0] || [0, 0], i: 0, ang: 0 };
  const total = cum[cum.length - 1];
  const r = Math.max(0, Math.min(total, run));
  let i = 0;
  while (i < pts.length - 2 && cum[i + 1] < r) i++;
  const seg = cum[i + 1] - cum[i] || 1;
  const t = Math.max(0, Math.min(1, (r - cum[i]) / seg));
  const a = pts[i], b = pts[i + 1];
  return { p: [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t], i, ang: Math.atan2(b[1] - a[1], b[0] - a[0]) };
};
const partialD = (pts: Pt[], cum: number[], run: number) => {
  if (pts.length < 2 || run <= 0) return "";
  const h = along(pts, cum, run);
  let d = `M${f1(pts[0][0])} ${f1(pts[0][1])}`;
  for (let j = 1; j <= h.i; j++) d += ` L${f1(pts[j][0])} ${f1(pts[j][1])}`;
  return `${d} L${f1(h.p[0])} ${f1(h.p[1])}`;
};

/**
 * The point-by-point schedule: point i arrives at arrive(i); the segment to
 * i+1 draws between arrive(i)+dwell and arrive(i+1). The whole draw fits
 * `share` of the overlay, the segment never longer than fps*0.32.
 */
const tickerPlan = (fps: number, dur: number, n: number, share = 0.45, dwell = 4) => {
  const segs = Math.max(1, n - 1);
  const at0 = Math.round(fps * 0.5);
  const seg = Math.max(3, Math.round(Math.min(fps * 0.32, (dur * share - at0 - segs * dwell) / segs)));
  const arrive = (i: number) => at0 + i * (seg + dwell);
  const prog = (f: number) => {
    let p = 0;
    for (let i = 0; i < n - 1; i++) {
      const s = ramp(f, arrive(i) + dwell, seg, inOut);
      p += s;
      if (s < 1) break;
    }
    return p;
  };
  return { at0, seg, dwell, arrive, prog, done: arrive(Math.max(0, n - 1)) };
};

// ------------------------------------------------------------------ shared pieces
/** One soft tick at frame `at` (ui-tick.mp3): a Sequence of its own, never past the overlay's end. */
const Tick: React.FC<{ at: number; volume?: number }> = ({ at, volume = 0.3 }) => {
  const { durationInFrames } = useVideoConfig();
  const from = Math.round(at);
  if (!Number.isFinite(from) || from < 0 || from >= durationInFrames - 1) return null;
  return (
    <Sequence from={from} durationInFrames={Math.max(1, Math.min(30, durationInFrames - from))} layout="none">
      <Audio src={staticFile("sfx/ui-tick.mp3")} volume={Math.max(0, Math.min(1, volume * IN_LOOK_SFX_SCALE))} />
    </Sequence>
  );
};

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

/** Letters rising out of a mask one after another, all gone inside the last frames. */
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

/** The chart heading: DISPLAY capitals over a short accent bar, wrapped by words to `maxW`. */
const ChartTitle: React.FC<{ text?: string; accent: string; size?: number; center?: boolean; maxW?: number }> =
  ({ text, accent, size = 56, center, maxW }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();
    const k = useK();
    const t = cap(text).replace(/\s+/g, " ").trim();
    if (!t) return null;
    const room = Math.max(300 * k, maxW ?? 1300 * k);
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

/** The subtitle as a tracked kicker over a title. */
const Kicker: React.FC<{ text?: unknown; accent: string; at?: number; center?: boolean }> = ({ text, accent, at = 0, center }) => {
  const k = useK();
  const t = clip(cap(text).replace(/\s+/g, " "), 48);
  if (!t) return null;
  return (
    <Letters text={t} at={at} step={0.4} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 26 * k, letterSpacing: "0.3em",
      color: accent, lineHeight: 1.1, textAlign: center ? "center" : "left" }} />
  );
};

/** The axis caption (overlay.label) in MONO caps. */
const Caption: React.FC<{ text?: unknown; at: number; center?: boolean; color?: string }> = ({ text, at, center, color }) => {
  const k = useK();
  const t = clip(cap(text).replace(/\s+/g, " "), 60);
  if (!t) return null;
  return (
    <Rise at={at} style={{ textAlign: center ? "center" : "left" }}>
      <span style={{ display: "block", fontFamily: MONO, fontWeight: 500, fontSize: 22 * k, letterSpacing: "0.2em",
        color: color || "rgba(255,255,255,.5)", whiteSpace: "nowrap" }}>{t}</span>
    </Rise>
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
 * The GoMotion ticker canvas: a dark, clean full frame, a small title
 * top-left, the source (subtitle) bottom-left, the chart centred with the
 * slow push, everything fading in the last frames.
 */
const Canvas: React.FC<{ overlay: Overlay; accent: string; children: React.ReactNode; legend?: React.ReactNode }> =
  ({ overlay, accent, children, legend }) => {
    const frame = useCurrentFrame();
    const { width, durationInFrames } = useVideoConfig();
    const k = useK();
    const hold = useHold();
    const fade = 1 - ramp(frame, durationInFrames - 6, 5);
    const settle = ramp(frame, 0, 20);
    const src = clip(str(overlay.subtitle).replace(/\s+/g, " ").trim(), 72);
    return (
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 42%, #161a24 0%, #0b0d13 55%, #050609 100%)",
        overflow: "hidden" }}>
        <AbsoluteFill style={{ backgroundImage: "radial-gradient(rgba(255,255,255,.055) 1px, transparent 1.4px)",
          backgroundSize: `${28 * k}px ${28 * k}px` }} />
        <AbsoluteFill style={{ boxShadow: `inset 0 0 ${380 * k}px rgba(0,0,0,.7)`, pointerEvents: "none" }} />
        <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", opacity: fade,
          transform: `translateY(${(1 - settle) * 26 * k}px) scale(${hold})` }}>
          {children}
        </AbsoluteFill>
        <div style={{ position: "absolute", left: 100 * k, top: 76 * k }}>
          <ChartTitle text={overlay.text} accent={accent} size={46} maxW={Math.min(1100 * k, width - 200 * k)} />
        </div>
        {legend ? <div style={{ position: "absolute", right: 100 * k, top: 88 * k }}>{legend}</div> : null}
        {src ? (
          <div style={{ position: "absolute", left: 100 * k, bottom: 66 * k }}>
            <Rise at={10}>
              <span style={{ display: "block", fontFamily: MONO, fontWeight: 500, fontSize: 22 * k, letterSpacing: "0.18em",
                color: "rgba(255,255,255,.52)", whiteSpace: "nowrap" }}>{cap(src)}</span>
            </Rise>
          </div>
        ) : null}
      </AbsoluteFill>
    );
  };

/** Flat black with a faint vignette (GoMotion's diagram backdrop). */
const Black: React.FC = () => {
  const k = useK();
  return (
    <AbsoluteFill style={{ background: "#000" }}>
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${320 * k}px rgba(0,0,0,.9)`,
        background: "radial-gradient(ellipse at 50% 50%, rgba(255,255,255,.03) 0%, rgba(0,0,0,0) 60%)" }} />
    </AbsoluteFill>
  );
};

/** A coloured pill: a rolling value and (optionally) the change beside it. */
const Pill: React.FC<{ value: number; at: number; frames: number; color: string; prefix?: string; suffix?: string;
  change?: string; size?: number; scale?: number }> = ({ value, at, frames, color, prefix = "", suffix = "", change, size = 34, scale = 1 }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const p = ramp(frame, at, 14, backOut) * scale;
  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: 12 * k, background: color, color: "#fff",
      padding: `${8 * k}px ${20 * k}px ${6 * k}px`, borderRadius: 60 * k, boxShadow: `0 0 ${24 * k}px ${color}77`,
      transform: `scale(${Math.max(0, p)})`, opacity: Math.min(1, Math.max(0, p) * 2), whiteSpace: "nowrap" }}>
      <Odometer value={Math.abs(value)} at={at} frames={frames} size={size * k} color="#fff"
        prefix={(value < 0 ? "−" : "") + prefix} suffix={suffix} suffixScale={0.55} />
      {change ? (
        <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: size * 0.72 * k, letterSpacing: "0.04em",
          color: "rgba(255,255,255,.92)", paddingTop: 2 * k }}>{change}</span>
      ) : null}
    </div>
  );
};

/** Dashed horizontal grid lines with their figures on the left. */
const YGrid: React.FC<{ sc: { ticks: number[]; step: number }; Y: (v: number) => number; W: number; prefix: string;
  pct: boolean; ex: number; from?: number }> = ({ sc, Y, W, prefix, pct, ex, from = 2 }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const td = tickDecimals(sc.step);
  return (
    <>
      {sc.ticks.map((t, i) => {
        const tp = ramp(frame, from + i * 2, 12);
        return (
          <g key={`g${i}`} opacity={tp * (1 - ex)}>
            <line x1={0} x2={W * ramp(frame, from + i * 2, 18, inOut)} y1={Y(t)} y2={Y(t)} stroke="rgba(255,255,255,.12)"
              strokeWidth={1.5 * k} strokeDasharray={`${6 * k} ${8 * k}`} />
            <text x={-18 * k} y={Y(t) + 8 * k} textAnchor="end" fontFamily={LABEL} fontWeight={600} fontSize={24 * k}
              fill="rgba(255,255,255,.55)" transform={drift(tp, ex, k)}>{tickTxt(t, td, prefix)}{pct ? "%" : ""}</text>
          </g>
        );
      })}
    </>
  );
};

// ================================================================== 1. line ticker
/**
 * A line chart drawing point by point: each point pops in with its tick,
 * the value rides the head of the line, and when the last point lands the
 * end value parks in a badge: red when the series fell, the accent when it
 * rose, with the change from the first point beside it.
 */
const LineTicker: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const items = nums(overlay.items, 12);
  const n = items.length;
  if (n < 2) return <Canvas overlay={overlay} accent={accent}>{null}</Canvas>;
  const { suffix, prefix, pct } = units(overlay, items);
  const vals = items.map((i) => i.value);
  const sc = seriesScale(vals);
  const dAll = Math.max(0, ...vals.map(decOf));
  const W = 1300 * k, H = 470 * k;
  const X = (i: number) => (i / (n - 1)) * W;
  const Y = (v: number) => (1 - (v - sc.min) / (sc.max - sc.min)) * H;
  const pts: Pt[] = items.map((it, i) => [X(i), Y(it.value)]);
  const plan = tickerPlan(fps, dur, n, 0.5);
  const ex = exitOf(frame, dur);
  const prog = plan.prog(frame) * (1 - ex);
  const { d, head } = polyTo(pts, prog);
  const area = d ? `${d} L${f1(head[0])} ${f1(H)} L0 ${f1(H)} Z` : "";
  const cur = Math.max(0, Math.min(n - 1, Math.floor(prog + 1e-6)));
  const falls = vals[n - 1] < vals[0];
  const endCol = falls ? RED : accent;
  const done = plan.done;
  const finished = frame >= done;
  const pulse = finished ? ((frame - done) % Math.round(fps * 1.4)) / Math.round(fps * 1.4) : 0;
  const showX = (i: number) => n <= 7 || (n - 1 - i) % 2 === 0;
  const id = `cc-lt-${overlay.startFrame ?? 0}`;
  return (
    <Canvas overlay={overlay} accent={accent}>
      <div style={{ position: "relative", width: W, height: H + 90 * k, marginLeft: 100 * k, marginTop: 70 * k }}>
        <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          <defs>
            <linearGradient id={`${id}a`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={accent} stopOpacity={0.22} />
              <stop offset="100%" stopColor={accent} stopOpacity={0} />
            </linearGradient>
          </defs>
          <YGrid sc={sc} Y={Y} W={W} prefix={prefix} pct={pct} ex={ex} />
          <line x1={0} x2={W * ramp(frame, 0, 18, inOut) * (1 - ex)} y1={H} y2={H} stroke="rgba(255,255,255,.7)" strokeWidth={3 * k} />
          {area && frame >= plan.at0 ? <path d={area} fill={`url(#${id}a)`} /> : null}
          {d && frame >= plan.at0 ? (
            <path d={d} fill="none" stroke={accent} strokeWidth={6 * k} strokeLinecap="round" strokeLinejoin="round"
              style={{ filter: `drop-shadow(0 0 ${10 * k}px ${accent}88)` }} />
          ) : null}
          {pts.map((p, i) => {
            const at = plan.arrive(i);
            if (frame < at) return null;
            const exI = exitOf(frame, dur, n - 1 - i, n);
            const pop = ramp(frame, at, 12, backOut) * (1 - exI);
            const ring = interpolate(frame, [at, at + 16], [0, 1], clamp);
            const last = i === n - 1;
            return (
              <g key={i}>
                {ring < 1 ? (
                  <circle cx={p[0]} cy={p[1]} r={(10 + 44 * ring) * k} fill="none" stroke={last ? endCol : accent} strokeWidth={3 * k}
                    opacity={(1 - ring) * 0.8} />
                ) : null}
                {last && finished ? (
                  <circle cx={p[0]} cy={p[1]} r={(12 + 34 * pulse) * k} fill="none" stroke={endCol} strokeWidth={2.5 * k}
                    opacity={(1 - pulse) * 0.8 * (1 - ex)} />
                ) : null}
                <circle cx={p[0]} cy={p[1]} r={Math.max(0, (last ? 11 : 9) * k * pop)} fill={last && finished ? endCol : INK}
                  stroke={last ? endCol : accent} strokeWidth={4 * k} />
              </g>
            );
          })}
        </svg>
        {items.map((it, i) => (
          showX(i) ? (
            <div key={`x${i}`} style={{ position: "absolute", left: X(i), top: H + 22 * k, transform: "translateX(-50%)" }}>
              <Rise at={plan.arrive(i)}>
                <span style={{ display: "block", fontFamily: LABEL, fontWeight: 600, fontSize: 25 * k, letterSpacing: "0.06em",
                  color: i === n - 1 ? "#fff" : "rgba(255,255,255,.7)", whiteSpace: "nowrap" }}>{cap(it.label)}</span>
              </Rise>
            </div>
          ) : null
        ))}
        {!finished && frame >= plan.at0 ? (
          <div style={{ position: "absolute", left: head[0], top: head[1] - 26 * k, transform: "translate(-50%, -100%)",
            background: "rgba(10,11,16,.9)", border: `${2 * k}px solid ${accent}`, borderRadius: 10 * k,
            padding: `${6 * k}px ${14 * k}px ${4 * k}px`, whiteSpace: "nowrap" }}>
            <span style={{ fontFamily: DISPLAY, fontSize: 34 * k, color: "#fff", letterSpacing: "0.02em", lineHeight: 1 }}>
              {prefix}{fmtD(vals[cur], dAll)}{tail(suffix)}</span>
          </div>
        ) : null}
        {finished ? (
          <div style={{ position: "absolute", left: Math.min(W - 40 * k, pts[n - 1][0] - 10 * k), top: pts[n - 1][1] - 34 * k,
            transform: "translate(-100%, -100%)" }}>
            <Pill value={vals[n - 1]} at={done} frames={Math.round(fps * 0.7)} color={endCol} prefix={prefix} suffix={tail(suffix)}
              change={signedPct(vals[0], vals[n - 1])} size={36} scale={1 - ex} />
          </div>
        ) : null}
        {overlay.label ? (
          <div style={{ position: "absolute", left: 0, top: H + 60 * k }}>
            <Caption text={overlay.label} at={plan.at0} />
          </div>
        ) : null}
      </div>
      {pts.map((_, i) => (i < TICK_MAX ? <Tick key={`t${i}`} at={plan.arrive(i)} volume={0.3} /> : null))}
    </Canvas>
  );
};

// ================================================================== 2. bars ticker
/**
 * Horizontal bars growing one after another, a tick as each lands and its
 * value parking at the bar end; the largest bar (or the one the narration
 * names) in the accent, the rest in a white-to-grey gradient.
 */
const BarsTicker: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const items = nums(overlay.items, 8);
  const n = items.length;
  if (n < 1) return <Canvas overlay={overlay} accent={accent}>{null}</Canvas>;
  const { suffix, prefix, pct } = units(overlay, items);
  const vals = items.map((i) => i.value);
  const sc = niceScale(Math.min(0, ...vals), Math.max(0, ...vals) * 1.04 || 1, 5);
  const td = tickDecimals(sc.step);
  const dAll = Math.max(0, ...vals.map(decOf));
  const hot = pickHot(items, overlay.highlight);
  const W = 1320 * k, LW = 320 * k, VW = 220 * k, BW = W - LW - VW;
  const RH = (n > 5 ? 66 : 84) * k, PITCH = RH + (n > 5 ? 12 : 18) * k, BH = RH * 0.62, TOP = 50 * k;
  const HT = TOP + n * PITCH;
  const X = (v: number) => LW + ((v - sc.min) / (sc.max - sc.min)) * BW;
  const x0 = X(0);
  const at0 = Math.round(fps * 0.45);
  const grow = Math.round(fps * 0.55);
  const stagger = Math.max(4, Math.round(Math.min(fps * 0.4, (dur * 0.45 - at0) / n)));
  const land = (i: number) => at0 + i * stagger + Math.round(grow * 0.55);
  const ex = exitOf(frame, dur);
  const allDone = land(n - 1) + 6;
  const breathe = frame >= allDone ? 0.5 + 0.5 * Math.sin(((frame - allDone) / fps) * Math.PI * 1.4) : 0;
  return (
    <Canvas overlay={overlay} accent={accent}>
      <div style={{ position: "relative", width: W, height: HT + 50 * k, marginTop: 70 * k }}>
        <svg width={W} height={HT} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          {sc.ticks.map((t, i) => {
            const x = X(t);
            const base = Math.abs(t) < 1e-9;
            const tp = ramp(frame, 4 + i * 2, 12);
            return (
              <g key={i} opacity={tp * (1 - ex)}>
                <line x1={x} x2={x} y1={TOP - 8 * k} y2={HT - 8 * k}
                  stroke={base ? "rgba(255,255,255,.55)" : "rgba(255,255,255,.12)"} strokeWidth={(base ? 3 : 1.5) * k}
                  strokeDasharray={base ? undefined : `${5 * k} ${7 * k}`} />
                <text x={x} y={TOP - 18 * k} textAnchor="middle" fontFamily={LABEL} fontWeight={600} fontSize={24 * k}
                  fill="rgba(255,255,255,.55)" transform={drift(tp, ex, k)}>{tickTxt(t, td, prefix)}{pct ? "%" : ""}</text>
              </g>
            );
          })}
        </svg>
        {items.map((it, i) => {
          const at = at0 + i * stagger;
          const exI = exitOf(frame, dur, i, n);
          const g = ramp(frame, at, grow, expoOut) * (1 - exI);
          const xv = x0 + (X(it.value) - x0) * g;
          const neg = it.value < 0;
          const left = Math.min(x0, xv), w = Math.abs(xv - x0);
          const isHot = i === hot;
          const glowA = isHot ? Math.round((0.35 + 0.3 * breathe) * 255).toString(16).padStart(2, "0") : "00";
          const inP = ramp(frame, 4 + i * 3, 16);
          return (
            <div key={i} style={{ position: "absolute", left: 0, top: TOP + i * PITCH, width: W, height: RH, opacity: inP,
              transform: `translateX(${(1 - inP) * -30 * k}px)` }}>
              <div style={{ position: "absolute", left: 0, width: LW - 26 * k, top: 0, height: RH, display: "flex",
                alignItems: "center", justifyContent: "flex-end" }}>
                <Rise at={6 + i * 3} style={{ maxWidth: "100%" }}>
                  <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: RH * 0.4, letterSpacing: "0.06em",
                    color: isHot ? accent : "#fff", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {cap(it.label)}</span>
                </Rise>
              </div>
              <div style={{ position: "absolute", left, top: (RH - BH) / 2, width: w, height: BH, overflow: "hidden",
                borderRadius: neg ? `${6 * k}px 0 0 ${6 * k}px` : `0 ${6 * k}px ${6 * k}px 0`,
                background: isHot ? `linear-gradient(90deg, ${accent}99, ${accent})` : "linear-gradient(90deg, #5d5f68, #d9dadf)",
                boxShadow: `0 0 ${28 * k}px ${accent}${glowA}, 0 ${8 * k}px ${20 * k}px rgba(0,0,0,.3)` }}>
                <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 2 * k, background: "rgba(255,255,255,.4)" }} />
              </div>
              {frame >= land(i) ? (
                <div style={{ position: "absolute", left: neg ? xv - 16 * k : xv + 16 * k, top: 0, height: RH, display: "flex",
                  alignItems: "center", whiteSpace: "nowrap", transform: neg ? "translateX(-100%)" : undefined }}>
                  <Rise at={land(i)} frames={12}>
                    <span style={{ display: "block", fontFamily: DISPLAY, fontSize: RH * 0.62, lineHeight: 1, color: isHot ? accent : "#fff" }}>
                      {neg ? "−" : ""}{it.prefix || prefix}{fmtD(Math.abs(it.value), dAll)}
                      {it.suffix || suffix ? (
                        <span style={{ fontSize: RH * 0.34, marginLeft: ((it.suffix || suffix) === "%" ? 2 : 8) * k,
                          color: "rgba(255,255,255,.7)" }}>{it.suffix || suffix}</span>
                      ) : null}
                    </span>
                  </Rise>
                </div>
              ) : null}
            </div>
          );
        })}
        {overlay.label ? (
          <div style={{ position: "absolute", left: LW, top: HT + 6 * k }}>
            <Caption text={overlay.label} at={at0} />
          </div>
        ) : null}
      </div>
      {items.map((_, i) => (i < TICK_MAX ? <Tick key={`t${i}`} at={land(i)} volume={0.3} /> : null))}
    </Canvas>
  );
};

// ================================================================== 3. columns ticker
/** Vertical columns rising one after another, a tick as each lands, the value rolling above it. */
const ColumnsTicker: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const items = nums(overlay.items, 10);
  const n = items.length;
  if (n < 1) return <Canvas overlay={overlay} accent={accent}>{null}</Canvas>;
  const { suffix, prefix, pct } = units(overlay, items);
  const vals = items.map((i) => i.value);
  const sc = niceScale(Math.min(0, ...vals), Math.max(0, ...vals) * 1.05 || 1, 4);
  const hot = pickHot(items, overlay.highlight);
  const W = 1300 * k, H = 420 * k, TOP = 100 * k, HT = TOP + H + 90 * k;
  const Y = (v: number) => TOP + (1 - (v - sc.min) / (sc.max - sc.min)) * H;
  const y0 = Y(0);
  const gw = W / n;
  const bw = Math.min(120 * k, gw * 0.56);
  const vs = n > 6 ? 0.8 : 1;
  const at0 = Math.round(fps * 0.45);
  const grow = Math.round(fps * 0.55);
  const stagger = Math.max(4, Math.round(Math.min(fps * 0.4, (dur * 0.45 - at0) / n)));
  const land = (i: number) => at0 + i * stagger + Math.round(grow * 0.55);
  const ex = exitOf(frame, dur);
  const id = `cc-ct-${overlay.startFrame ?? 0}`;
  return (
    <Canvas overlay={overlay} accent={accent}>
      <div style={{ position: "relative", width: W, height: HT, marginLeft: 90 * k, marginTop: 60 * k }}>
        <svg width={W} height={HT} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          <defs>
            <linearGradient id={`${id}b`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={accent} />
              <stop offset="100%" stopColor={accent} stopOpacity={0.62} />
            </linearGradient>
            <linearGradient id={`${id}w`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#fff" stopOpacity={0.95} />
              <stop offset="100%" stopColor="#fff" stopOpacity={0.45} />
            </linearGradient>
          </defs>
          <YGrid sc={sc} Y={Y} W={W} prefix={prefix} pct={pct} ex={ex} />
          <line x1={0} x2={W * ramp(frame, 0, 18, inOut) * (1 - ex)} y1={y0} y2={y0} stroke="rgba(255,255,255,.8)" strokeWidth={3 * k} />
          {items.map((it, i) => {
            const at = at0 + i * stagger;
            if (frame < at) return null;
            const exI = exitOf(frame, dur, i, n);
            const g = ramp(frame, at, grow, expoOut) * (1 - exI);
            const yv = Y(it.value * g);
            const x = gw * (i + 0.5) - bw / 2;
            const flash = 1 - ramp(frame, land(i), 10);
            return (
              <g key={i}>
                <rect x={x} y={Math.min(yv, y0)} width={bw} height={Math.abs(yv - y0)} fill={i === hot ? `url(#${id}b)` : `url(#${id}w)`}
                  style={i === hot ? { filter: `drop-shadow(0 0 ${14 * k}px ${accent}77)` } : undefined} />
                <rect x={x} y={yv <= y0 ? yv : yv - 3 * k} width={bw} height={3 * k} fill="#fff" opacity={0.4 + 0.6 * flash} />
              </g>
            );
          })}
        </svg>
        {items.map((it, i) => {
          const cx = gw * (i + 0.5);
          const yv = Y(it.value);
          const neg = it.value < 0;
          const ls = lines(cap(it.label), 12).slice(0, 2);
          return (
            <React.Fragment key={i}>
              {frame >= land(i) ? (
                <div style={{ position: "absolute", left: cx, top: neg ? yv + 10 * k : yv - 10 * k,
                  transform: neg ? "translate(-50%, 0)" : "translate(-50%, -100%)", whiteSpace: "nowrap" }}>
                  <Rise at={land(i)}>
                    <Odometer value={Math.abs(it.value)} at={land(i)} frames={Math.round(fps * 0.6)} size={46 * k * vs}
                      color={i === hot ? accent : "#fff"} prefix={(neg ? "−" : "") + (it.prefix || prefix)}
                      suffix={tail(it.suffix || suffix)} suffixScale={0.5} />
                  </Rise>
                </div>
              ) : null}
              <div style={{ position: "absolute", left: gw * i, width: gw, top: TOP + H + 16 * k, display: "flex",
                flexDirection: "column", alignItems: "center" }}>
                {ls.map((ln, j) => (
                  <Rise key={j} at={at0 + i * stagger + j * 2}>
                    <span style={{ display: "block", fontFamily: LABEL, fontWeight: 700, fontSize: 28 * k * vs, letterSpacing: "0.06em",
                      lineHeight: 1.05, textAlign: "center", color: i === hot ? accent : "rgba(255,255,255,.86)" }}>{ln}</span>
                  </Rise>
                ))}
              </div>
            </React.Fragment>
          );
        })}
        {overlay.label ? (
          <div style={{ position: "absolute", left: 0, top: TOP + H + 92 * k }}>
            <Caption text={overlay.label} at={at0} />
          </div>
        ) : null}
      </div>
      {items.map((_, i) => (i < TICK_MAX ? <Tick key={`t${i}`} at={land(i)} volume={0.3} /> : null))}
    </Canvas>
  );
};

// ================================================================== 4. planned vs actual
/**
 * Two columns: items[0] planned (white), items[1] actual (red when it fell
 * short, green when it beat the plan). The planned level runs across as a
 * dashed target, a diagonal drop line draws from one top to the other and
 * the difference pops in a badge on it.
 */
const PlannedVsActual: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const items = nums(overlay.items, 2);
  if (!items.length) return <Canvas overlay={overlay} accent={accent}>{null}</Canvas>;
  const { suffix, prefix, pct } = units(overlay, items);
  const names = splitNames(overlay.label);
  const planned = items[0];
  const actual: Num | undefined = items[1];
  const nameA = cap(planned.label || names[0] || "Planned");
  const nameB = cap(actual?.label || names[1] || "Actual");
  const vals = items.map((i) => i.value);
  const sc = niceScale(Math.min(0, ...vals), Math.max(0, ...vals) * 1.18 || 1, 4);
  const dAll = Math.max(0, ...vals.map(decOf));
  const W = 820 * k, H = 440 * k, TOP = 110 * k, HT = TOP + H + 80 * k;
  const Y = (v: number) => TOP + (1 - (v - sc.min) / (sc.max - sc.min)) * H;
  const y0 = Y(0);
  const bw = 180 * k;
  const cx1 = W * 0.28, cx2 = W * 0.72;
  const at1 = Math.round(fps * 0.5), grow = Math.round(fps * 0.8);
  const land1 = at1 + Math.round(grow * 0.55);
  const at2 = land1 + Math.round(fps * 0.25);
  const land2 = at2 + Math.round(grow * 0.55);
  const lineAt = land2 + 4, lineN = Math.round(fps * 0.5);
  const ex = exitOf(frame, dur);
  const g1 = ramp(frame, at1, grow, expoOut) * (1 - ex);
  const g2 = actual ? ramp(frame, at2, grow, expoOut) * (1 - ex) : 0;
  const yA = Y(planned.value * g1), yB = actual ? Y(actual.value * g2) : y0;
  const diff = actual ? actual.value - planned.value : 0;
  const down = diff < 0;
  const col = !actual || Math.abs(diff) < 1e-9 ? GREY : down ? RED : GREEN;
  const lp = actual ? ramp(frame, lineAt, lineN, inOut) * (1 - ex) : 0;
  const x1 = cx1 + bw / 2 + 8 * k, x2 = cx2 - bw / 2 - 8 * k;
  const ya = Y(planned.value), yb = actual ? Y(actual.value) : y0;
  const lx = x1 + (x2 - x1) * lp, ly = ya + (yb - ya) * lp;
  const badgeAt = lineAt + lineN - 4;
  const bp = actual ? ramp(frame, badgeAt, 14, backOut) * (1 - ex) : 0;
  const mid: Pt = [(x1 + x2) / 2, (ya + yb) / 2];
  const change = actual ? signedPct(planned.value, actual.value) : "";
  const id = `cc-pa-${overlay.startFrame ?? 0}`;
  return (
    <Canvas overlay={overlay} accent={accent}>
      <div style={{ position: "relative", width: W, height: HT, marginLeft: 100 * k, marginTop: 60 * k }}>
        <svg width={W} height={HT} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          <defs>
            <linearGradient id={`${id}w`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#fff" stopOpacity={0.95} />
              <stop offset="100%" stopColor="#fff" stopOpacity={0.5} />
            </linearGradient>
            <linearGradient id={`${id}c`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={col} />
              <stop offset="100%" stopColor={col} stopOpacity={0.6} />
            </linearGradient>
          </defs>
          <YGrid sc={sc} Y={Y} W={W} prefix={prefix} pct={pct} ex={ex} />
          <line x1={0} x2={W * ramp(frame, 0, 18, inOut) * (1 - ex)} y1={y0} y2={y0} stroke="rgba(255,255,255,.8)" strokeWidth={3 * k} />
          {frame >= at1 ? (
            <>
              <rect x={cx1 - bw / 2} y={Math.min(yA, y0)} width={bw} height={Math.abs(yA - y0)} fill={`url(#${id}w)`} />
              <rect x={cx1 - bw / 2} y={yA <= y0 ? yA : yA - 3 * k} width={bw} height={3 * k} fill="#fff" />
            </>
          ) : null}
          {actual && frame >= at2 ? (
            <>
              <rect x={cx2 - bw / 2} y={Math.min(yB, y0)} width={bw} height={Math.abs(yB - y0)} fill={`url(#${id}c)`}
                style={{ filter: `drop-shadow(0 0 ${16 * k}px ${col}66)` }} />
              <rect x={cx2 - bw / 2} y={yB <= y0 ? yB : yB - 3 * k} width={bw} height={3 * k} fill="#fff" opacity={0.7} />
            </>
          ) : null}
          {actual && lp > 0 ? (
            <>
              <line x1={x1} x2={x1 + (cx2 + bw / 2 - x1) * lp} y1={ya} y2={ya} stroke="rgba(255,255,255,.45)" strokeWidth={2 * k}
                strokeDasharray={`${8 * k} ${8 * k}`} />
              <line x1={x1} y1={ya} x2={lx} y2={ly} stroke={col} strokeWidth={5 * k} strokeLinecap="round"
                style={{ filter: `drop-shadow(0 0 ${8 * k}px ${col}88)` }} />
              <circle cx={lx} cy={ly} r={8 * k} fill="#fff" />
              {Math.abs(yb - ya) > 40 * k ? (
                <line x1={cx2 + bw / 2 + 22 * k} x2={cx2 + bw / 2 + 22 * k} y1={ya} y2={ya + (yb - ya) * lp} stroke={col}
                  strokeWidth={3 * k} strokeDasharray={`${6 * k} ${6 * k}`} />
              ) : null}
            </>
          ) : null}
        </svg>
        <div style={{ position: "absolute", left: cx1, top: ya - 14 * k, transform: "translate(-50%, -100%)", whiteSpace: "nowrap" }}>
          <Rise at={land1}>
            <Odometer value={Math.abs(planned.value)} at={land1} frames={Math.round(fps * 0.7)} size={56 * k} color="#fff"
              prefix={(planned.value < 0 ? "−" : "") + (planned.prefix || prefix)} suffix={tail(planned.suffix || suffix)} suffixScale={0.5} />
          </Rise>
        </div>
        {actual ? (
          <div style={{ position: "absolute", left: cx2, top: yb - 14 * k, transform: "translate(-50%, -100%)", whiteSpace: "nowrap" }}>
            <Rise at={land2}>
              <Odometer value={Math.abs(actual.value)} at={land2} frames={Math.round(fps * 0.7)} size={56 * k} color={col}
                prefix={(actual.value < 0 ? "−" : "") + (actual.prefix || prefix)} suffix={tail(actual.suffix || suffix)} suffixScale={0.5} />
            </Rise>
          </div>
        ) : null}
        {actual && bp > 0.001 ? (
          <div style={{ position: "absolute", left: mid[0], top: mid[1] - 34 * k, transform: `translate(-50%, -100%) scale(${bp})`,
            transformOrigin: "50% 100%", display: "flex", flexDirection: "column", alignItems: "center", gap: 6 * k }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 * k, background: col, color: "#fff", fontFamily: LABEL,
              fontWeight: 800, fontSize: 34 * k, lineHeight: 1, letterSpacing: "0.04em", padding: `${9 * k}px ${20 * k}px ${7 * k}px`,
              borderRadius: 40 * k, boxShadow: `0 0 ${22 * k}px ${col}66`, whiteSpace: "nowrap" }}>
              <span style={{ fontSize: 22 * k }}>{Math.abs(diff) < 1e-9 ? "=" : down ? "▼" : "▲"}</span>
              {change || "0%"}
            </div>
            <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.1em", color: "rgba(255,255,255,.8)",
              whiteSpace: "nowrap" }}>{down ? "−" : "+"}{prefix}{fmtD(Math.abs(diff), dAll)}{tail(suffix)}</span>
          </div>
        ) : null}
        {[{ x: cx1, t: nameA, at: at1 }, ...(actual ? [{ x: cx2, t: nameB, at: at2 }] : [])].map((c, i) => (
          <div key={i} style={{ position: "absolute", left: c.x, top: TOP + H + 18 * k, transform: "translateX(-50%)" }}>
            <Rise at={c.at}>
              <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: 32 * k, letterSpacing: "0.12em",
                color: i === 1 ? col : "rgba(255,255,255,.88)", whiteSpace: "nowrap" }}>{clip(c.t, 22)}</span>
            </Rise>
          </div>
        ))}
      </div>
      <Tick at={land1} volume={0.3} />
      {actual ? <Tick at={land2} volume={0.3} /> : null}
    </Canvas>
  );
};

// ================================================================== 5. two series
/**
 * Two lines drawing point by point together (one tick per x), the first
 * from items[].value in the accent, the second from a number in items[].text
 * in cyan, or, when there is none, a smoothed copy of the first as a TREND.
 * A legend top-right names them (overlay.label "Inflow | Outflow").
 */
const TwoSeries: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const items = nums(overlay.items, 12);
  const n = items.length;
  if (n < 2) return <Canvas overlay={overlay} accent={accent}>{null}</Canvas>;
  const { suffix, prefix, pct } = units(overlay, items);
  const a = items.map((i) => i.value);
  const bRaw = items.map((i) => toNum(i.text));
  const hasB = bRaw.every((v) => Number.isFinite(v));
  const b = hasB ? bRaw : a.map((_, i) => {
    const w = [a[i - 1], a[i], a[i + 1]].filter((v): v is number => Number.isFinite(v));
    return w.reduce((s, v) => s + v, 0) / w.length;
  });
  const names = splitNames(overlay.label);
  const nameA = clip(cap(names[0] || "Series A"), 16), nameB = clip(cap(names[1] || (hasB ? "Series B" : "Trend")), 16);
  const sc = seriesScale([...a, ...b]);
  const W = 1240 * k, H = 460 * k;
  const X = (i: number) => (i / (n - 1)) * W;
  const Y = (v: number) => (1 - (v - sc.min) / (sc.max - sc.min)) * H;
  const ptsA: Pt[] = a.map((v, i) => [X(i), Y(v)]);
  const ptsB: Pt[] = b.map((v, i) => [X(i), Y(v)]);
  const plan = tickerPlan(fps, dur, n, 0.5);
  const ex = exitOf(frame, dur);
  const prog = plan.prog(frame) * (1 - ex);
  const A = polyTo(ptsA, prog), B = polyTo(ptsB, prog);
  const done = plan.done;
  const finished = frame >= done;
  const showX = (i: number) => n <= 7 || (n - 1 - i) % 2 === 0;
  // The two end labels never sit on each other: pushed apart around their points.
  let lyA = ptsA[n - 1][1], lyB = ptsB[n - 1][1];
  if (Math.abs(lyA - lyB) < 56 * k) {
    const m = (lyA + lyB) / 2;
    lyA = lyA <= lyB ? m - 28 * k : m + 28 * k;
    lyB = lyA <= lyB ? m + 28 * k : m - 28 * k;
    if (Math.abs(lyA - lyB) < 56 * k) lyB = lyA + 56 * k;
  }
  const legend = (
    <div style={{ display: "flex", alignItems: "center", gap: 28 * k, whiteSpace: "nowrap" }}>
      {[{ c: accent, t: nameA, at: 10 }, { c: CYAN, t: nameB, at: 14 }].map((l, i) => (
        <Rise key={i} at={l.at}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 * k }}>
            <div style={{ width: 30 * k, height: 6 * k, background: l.c, borderRadius: 3 * k }} />
            <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 26 * k, letterSpacing: "0.14em", color: "rgba(255,255,255,.85)" }}>{l.t}</span>
          </div>
        </Rise>
      ))}
    </div>
  );
  return (
    <Canvas overlay={overlay} accent={accent} legend={legend}>
      <div style={{ position: "relative", width: W, height: H + 90 * k, marginLeft: 40 * k, marginTop: 70 * k }}>
        <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          <YGrid sc={sc} Y={Y} W={W} prefix={prefix} pct={pct} ex={ex} />
          <line x1={0} x2={W * ramp(frame, 0, 18, inOut) * (1 - ex)} y1={H} y2={H} stroke="rgba(255,255,255,.7)" strokeWidth={3 * k} />
          {B.d && prog > 0 ? (
            <path d={B.d} fill="none" stroke={CYAN} strokeWidth={5 * k} strokeLinecap="round" strokeLinejoin="round"
              strokeDasharray={hasB ? undefined : `${12 * k} ${10 * k}`} />
          ) : null}
          {A.d && prog > 0 ? (
            <path d={A.d} fill="none" stroke={accent} strokeWidth={6 * k} strokeLinecap="round" strokeLinejoin="round"
              style={{ filter: `drop-shadow(0 0 ${10 * k}px ${accent}88)` }} />
          ) : null}
          {items.map((_, i) => {
            const at = plan.arrive(i);
            if (frame < at) return null;
            const exI = exitOf(frame, dur, n - 1 - i, n);
            const pop = ramp(frame, at, 12, backOut) * (1 - exI);
            const ring = interpolate(frame, [at, at + 16], [0, 1], clamp);
            return (
              <g key={i}>
                {ring < 1 ? (
                  <circle cx={ptsA[i][0]} cy={ptsA[i][1]} r={(9 + 40 * ring) * k} fill="none" stroke={accent} strokeWidth={3 * k}
                    opacity={(1 - ring) * 0.8} />
                ) : null}
                <circle cx={ptsB[i][0]} cy={ptsB[i][1]} r={Math.max(0, 7 * k * pop)} fill={INK} stroke={CYAN} strokeWidth={3.5 * k} />
                <circle cx={ptsA[i][0]} cy={ptsA[i][1]} r={Math.max(0, 9 * k * pop)} fill={INK} stroke={accent} strokeWidth={4 * k} />
              </g>
            );
          })}
        </svg>
        {items.map((it, i) => (
          showX(i) ? (
            <div key={`x${i}`} style={{ position: "absolute", left: X(i), top: H + 22 * k, transform: "translateX(-50%)" }}>
              <Rise at={plan.arrive(i)}>
                <span style={{ display: "block", fontFamily: LABEL, fontWeight: 600, fontSize: 25 * k, letterSpacing: "0.06em",
                  color: "rgba(255,255,255,.7)", whiteSpace: "nowrap" }}>{cap(it.label)}</span>
              </Rise>
            </div>
          ) : null
        ))}
        {finished ? [{ v: a[n - 1], y: lyA, c: accent }, { v: b[n - 1], y: lyB, c: CYAN }].map((e, i) => (
          <div key={`e${i}`} style={{ position: "absolute", left: W + 22 * k, top: e.y, transform: "translateY(-50%)", whiteSpace: "nowrap" }}>
            <Rise at={done}>
              <Odometer value={Math.abs(e.v)} at={done} frames={Math.round(fps * 0.6)} size={38 * k} color={e.c}
                prefix={(e.v < 0 ? "−" : "") + prefix} suffix={tail(suffix)} suffixScale={0.5} />
            </Rise>
          </div>
        )) : null}
      </div>
      {items.map((_, i) => (i < TICK_MAX ? <Tick key={`t${i}`} at={plan.arrive(i)} volume={0.3} /> : null))}
    </Canvas>
  );
};

// ================================================================== 6. snow sites
/**
 * Item values as dots along one horizontal axis (GoMotion's "SNOWPACK
 * DEPTH" sites): the dots land one after another with a tick, their names
 * on leader lines above and below, and the last dot is red, bigger, and
 * carries its value in a pill.
 */
const SnowSites: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const items = nums(overlay.items, 12);
  const n = items.length;
  if (n < 1) return <Canvas overlay={overlay} accent={accent}>{null}</Canvas>;
  const { suffix, prefix, pct } = units(overlay, items);
  const vals = items.map((i) => i.value);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const span = hi - lo || Math.abs(hi) || 1;
  const zero = lo >= 0 && lo <= hi * 0.4;
  const sc = niceScale(zero ? 0 : lo - span * 0.12, hi + span * 0.12, 5);
  const td = tickDecimals(sc.step);
  const W = 1320 * k, AX = 230 * k, HT = 420 * k;
  const X = (v: number) => ((v - sc.min) / (sc.max - sc.min)) * W;
  const at0 = Math.round(fps * 0.5);
  const stagger = Math.max(4, Math.round(Math.min(fps * 0.3, (dur * 0.45 - at0) / n)));
  const at = (i: number) => at0 + i * stagger;
  const ex = exitOf(frame, dur);
  const done = at(n - 1) + 8;
  const period = Math.round(fps * 1.3);
  const pulse = frame >= done ? ((frame - done) % period) / period : 0;
  // Label tiers: the last dot always takes the far-above tier for its pill.
  const tiers = [-58, 82, 132].map((t) => t * k);
  const tierOf = (i: number) => (i === n - 1 ? -128 * k : tiers[i % 3]);
  return (
    <Canvas overlay={overlay} accent={accent}>
      <div style={{ position: "relative", width: W, height: HT, marginTop: 40 * k }}>
        <svg width={W} height={HT} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          {sc.ticks.map((t, i) => {
            const tp = ramp(frame, 4 + i * 2, 12);
            return (
              <g key={`g${i}`} opacity={tp * (1 - ex)}>
                <line x1={X(t)} x2={X(t)} y1={AX - 10 * k} y2={AX + 10 * k} stroke="rgba(255,255,255,.5)" strokeWidth={2 * k} />
                <line x1={X(t)} x2={X(t)} y1={AX - 120 * k} y2={AX + 60 * k} stroke="rgba(255,255,255,.08)" strokeWidth={1.5 * k}
                  strokeDasharray={`${5 * k} ${7 * k}`} />
                <text x={X(t)} y={AX + 44 * k} textAnchor="middle" fontFamily={LABEL} fontWeight={600} fontSize={24 * k}
                  fill="rgba(255,255,255,.55)" transform={drift(tp, ex, k)}>{tickTxt(t, td, prefix)}{pct ? "%" : ""}</text>
              </g>
            );
          })}
          <line x1={0} x2={W * ramp(frame, 0, 18, inOut) * (1 - ex)} y1={AX} y2={AX} stroke="rgba(255,255,255,.75)" strokeWidth={3 * k} />
          {items.map((it, i) => {
            const a = at(i);
            if (frame < a) return null;
            const exI = exitOf(frame, dur, i, n);
            const pop = ramp(frame, a, 14, backOut) * (1 - exI);
            const ring = interpolate(frame, [a, a + 16], [0, 1], clamp);
            const last = i === n - 1;
            const col = last ? RED : "#fff";
            const x = X(it.value), ty = AX + tierOf(i);
            const lead = ramp(frame, a + 4, 12, inOut) * (1 - exI);
            return (
              <g key={i}>
                <line x1={x} x2={x} y1={AX} y2={AX + (ty - AX) * lead} stroke={last ? RED : "rgba(255,255,255,.35)"} strokeWidth={1.5 * k} />
                {ring < 1 ? (
                  <circle cx={x} cy={AX} r={(12 + 46 * ring) * k} fill="none" stroke={col} strokeWidth={3 * k} opacity={(1 - ring) * 0.8} />
                ) : null}
                {last && frame >= done ? (
                  <circle cx={x} cy={AX} r={(16 + 36 * pulse) * k} fill="none" stroke={RED} strokeWidth={2.5 * k}
                    opacity={(1 - pulse) * 0.8 * (1 - ex)} />
                ) : null}
                <circle cx={x} cy={AX} r={Math.max(0, (last ? 17 : 12) * k * pop)} fill={last ? RED : "#fff"} stroke={last ? "#fff" : INK}
                  strokeWidth={(last ? 3 : 2.5) * k} style={last ? { filter: `drop-shadow(0 0 ${14 * k}px ${RED}aa)` } : undefined} />
              </g>
            );
          })}
        </svg>
        {items.map((it, i) => {
          const a = at(i);
          const last = i === n - 1;
          const x = X(it.value), ty = AX + tierOf(i);
          const above = tierOf(i) < 0;
          const cx = Math.max(60 * k, Math.min(W - 60 * k, x));
          return (
            <div key={`l${i}`} style={{ position: "absolute", left: cx, top: ty, display: "flex", flexDirection: "column",
              alignItems: "center", gap: 4 * k, transform: `translate(-50%, ${above ? "-100%" : "0"})`, whiteSpace: "nowrap" }}>
              {last ? (
                <Pill value={it.value} at={a + 6} frames={Math.round(fps * 0.6)} color={RED} prefix={it.prefix || prefix}
                  suffix={tail(it.suffix || suffix)} size={34} scale={1 - ex} />
              ) : null}
              <Rise at={a + 6}>
                <span style={{ display: "block", fontFamily: LABEL, fontWeight: 700, fontSize: (last ? 28 : 24) * k, letterSpacing: "0.08em",
                  color: last ? RED : "rgba(255,255,255,.82)", textAlign: "center" }}>{clip(cap(it.label), 18)}</span>
              </Rise>
            </div>
          );
        })}
        {overlay.label ? (
          <div style={{ position: "absolute", left: 0, right: 0, top: AX + 176 * k }}>
            <Caption text={overlay.label} at={at0} center />
          </div>
        ) : null}
      </div>
      {items.map((_, i) => (i < TICK_MAX ? <Tick key={`t${i}`} at={at(i)} volume={0.3} /> : null))}
    </Canvas>
  );
};

// ================================================================== 7. tick bars (data card)
/**
 * Horizontal bars on the Scrim, in the given order: each grows expo-out
 * with a bright bead riding its head, flashes a white edge as it lands, plays
 * its tick and rolls its value at the bar end, then parks it with the unit.
 * The bar the narration names (else the largest) is the accent with a glow.
 */
const TickBars: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const items = nums(overlay.items, 6);
  const n = items.length;
  const { suffix, prefix, pct } = units(overlay, items);
  const W = 1360 * k, LW = 340 * k, VW = 240 * k, BW = W - LW - VW;
  const RH = 86 * k, PITCH = 86 * k, BH = 50 * k, TOP = 52 * k;
  const HT = TOP + n * PITCH;
  const head = (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 * k }}>
      <Kicker text={overlay.subtitle} accent={accent} />
      <ChartTitle text={overlay.text} accent={accent} maxW={W} />
    </div>
  );
  if (n < 1) return <Card overlay={overlay}><div style={{ width: W }}>{head}</div></Card>;
  const vals = items.map((i) => i.value);
  const sc = niceScale(Math.min(0, ...vals), Math.max(0, ...vals) * 1.04 || 1, 5);
  const td = tickDecimals(sc.step);
  const hot = pickHot(items, overlay.highlight);
  const X = (v: number) => LW + ((v - sc.min) / (sc.max - sc.min)) * BW;
  const x0 = X(0);
  const at0 = Math.round(fps * 0.45);
  const step = Math.round(fps * 0.4), grow = Math.round(fps * 0.7);
  const land = (i: number) => at0 + i * step + Math.round(grow * 0.55);
  const ex = exitOf(frame, dur);
  const allDone = land(n - 1) + 8;
  const breathe = frame >= allDone ? 0.5 + 0.5 * Math.sin(((frame - allDone) / fps) * Math.PI * 1.3) : 0;
  return (
    <Card overlay={overlay}>
      <div style={{ width: W, display: "flex", flexDirection: "column", gap: 22 * k }}>
        {head}
        <div style={{ position: "relative", width: W, height: HT + (overlay.label ? 46 * k : 0) }}>
          <svg width={W} height={HT} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
            {sc.ticks.map((t, i) => {
              const x = X(t);
              const base = Math.abs(t) < 1e-9;
              const tp = ramp(frame, 4 + i * 2, 12);
              return (
                <g key={i} opacity={tp * (1 - ex)}>
                  <line x1={x} x2={x} y1={TOP - 8 * k} y2={HT - 8 * k}
                    stroke={base ? "rgba(255,255,255,.55)" : "rgba(255,255,255,.12)"} strokeWidth={(base ? 3 : 1.5) * k}
                    strokeDasharray={base ? undefined : `${5 * k} ${7 * k}`} />
                  <text x={x} y={TOP - 18 * k} textAnchor="middle" fontFamily={LABEL} fontWeight={600} fontSize={24 * k}
                    fill="rgba(255,255,255,.55)" transform={drift(tp, ex, k)}>{tickTxt(t, td, prefix)}{pct ? "%" : ""}</text>
                </g>
              );
            })}
            {items.map((it, i) => {
              const at = at0 + i * step;
              if (frame < at) return null;
              const exI = exitOf(frame, dur, i, n);
              const g = ramp(frame, at, grow, expoOut) * (1 - exI);
              const xv = x0 + (X(it.value) - x0) * g;
              const y = TOP + i * PITCH + RH / 2;
              const flash = 1 - ramp(frame, land(i), 10);
              return (
                <g key={`b${i}`}>
                  {g > 0.02 && g < 0.98 ? <circle cx={xv} cy={y} r={7 * k} fill="#fff" opacity={0.9} style={{ filter: `drop-shadow(0 0 ${8 * k}px #fff)` }} /> : null}
                  {frame >= land(i) ? (
                    <rect x={xv - 1 * k} y={y - BH / 2} width={2 * k} height={BH} fill="#fff" opacity={flash} />
                  ) : null}
                </g>
              );
            })}
          </svg>
          {items.map((it, i) => {
            const at = at0 + i * step;
            const exI = exitOf(frame, dur, i, n);
            const g = ramp(frame, at, grow, expoOut) * (1 - exI);
            const xv = x0 + (X(it.value) - x0) * g;
            const neg = it.value < 0;
            const left = Math.min(x0, xv), w = Math.abs(xv - x0);
            const isHot = i === hot;
            const glowA = isHot ? Math.round((0.35 + 0.3 * breathe) * 255).toString(16).padStart(2, "0") : "00";
            const inP = ramp(frame, 4 + i * 3, 16);
            const unit = it.suffix || suffix;
            return (
              <div key={i} style={{ position: "absolute", left: 0, top: TOP + i * PITCH, width: W, height: RH, opacity: inP,
                transform: `translateX(${(1 - inP) * -30 * k}px)` }}>
                <div style={{ position: "absolute", left: 0, width: LW - 26 * k, top: 0, height: RH, display: "flex",
                  alignItems: "center", justifyContent: "flex-end" }}>
                  <Rise at={6 + i * 3} style={{ maxWidth: "100%" }}>
                    <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: 34 * k, letterSpacing: "0.06em",
                      color: isHot ? accent : "#fff", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {cap(it.label)}</span>
                  </Rise>
                </div>
                <div style={{ position: "absolute", left, top: (RH - BH) / 2, width: w, height: BH, overflow: "hidden",
                  borderRadius: neg ? `${6 * k}px 0 0 ${6 * k}px` : `0 ${6 * k}px ${6 * k}px 0`,
                  background: isHot ? `linear-gradient(90deg, ${accent}99, ${accent})` : "linear-gradient(90deg, #5d5f68, #d9dadf)",
                  boxShadow: `0 0 ${28 * k}px ${accent}${glowA}, 0 ${8 * k}px ${20 * k}px rgba(0,0,0,.3)` }}>
                  <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 2 * k, background: "rgba(255,255,255,.4)" }} />
                </div>
                {frame >= land(i) ? (
                  <div style={{ position: "absolute", left: neg ? xv - 16 * k : xv + 16 * k, top: 0, height: RH, display: "flex",
                    alignItems: "center", whiteSpace: "nowrap", transform: neg ? "translateX(-100%)" : undefined }}>
                    <Rise at={land(i)} frames={12}>
                      <Odometer value={Math.abs(it.value)} at={land(i)} frames={Math.round(fps * 0.6)} size={50 * k}
                        color={isHot ? accent : "#fff"} prefix={(neg ? "−" : "") + (it.prefix || prefix)} suffix={tail(unit)}
                        suffixScale={0.5} suffixColor="rgba(255,255,255,.7)" />
                    </Rise>
                  </div>
                ) : null}
              </div>
            );
          })}
          {overlay.label ? (
            <div style={{ position: "absolute", left: LW, top: HT + 4 * k }}>
              <Caption text={overlay.label} at={at0} />
            </div>
          ) : null}
        </div>
      </div>
      {items.map((_, i) => (i < TICK_MAX ? <Tick key={`t${i}`} at={land(i)} volume={0.25} /> : null))}
    </Card>
  );
};

// ================================================================== 8. tick line (data card)
/**
 * A monotone line on the Scrim drawn segment by segment with a dwell on
 * every point: the point pops with a shock ring and its tick, its value
 * rises beside it (above when the line is falling, below when rising), a
 * faint area follows the head, and the last value lands in a red / green
 * pill with the change from the first point.
 */
const TickLine: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const items = nums(overlay.items, 12);
  const n = items.length;
  const W = 1200 * k;
  const head = (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 * k }}>
      <Kicker text={overlay.subtitle} accent={accent} />
      <ChartTitle text={overlay.text} accent={accent} maxW={W} />
    </div>
  );
  if (n < 2) return <Card overlay={overlay}><div style={{ width: W }}>{head}</div></Card>;
  const { suffix, prefix, pct } = units(overlay, items);
  const vals = items.map((i) => i.value);
  const sc = seriesScale(vals);
  const dAll = Math.max(0, ...vals.map(decOf));
  const H = 400 * k, TOP = 70 * k, HT = TOP + H + 70 * k + (overlay.label ? 40 * k : 0);
  const X = (i: number) => (i / (n - 1)) * W;
  const Y = (v: number) => TOP + (1 - (v - sc.min) / (sc.max - sc.min)) * H;
  const xs = items.map((_, i) => X(i));
  const f = monotone(xs, vals.map(Y));
  const dwell = 4;
  const at0 = Math.round(fps * 0.45);
  const seg = Math.max(3, Math.round(Math.min(fps * 0.32, (dur * 0.45 - at0 - (n - 1) * dwell) / (n - 1))));
  const arrive = (i: number) => at0 + i * (seg + dwell);
  let prog = 0;
  for (let i = 0; i < n - 1; i++) {
    const s = ramp(frame, arrive(i) + dwell, seg, inOut);
    prog += s;
    if (s < 1) break;
  }
  const ex = exitOf(frame, dur);
  prog *= 1 - ex;
  const pi = Math.min(n - 2, Math.floor(prog));
  const headX = X(pi) + (X(pi + 1) - X(pi)) * (prog - pi);
  const path = headX > 0 ? curvePath(f, 0, headX, 120) : "";
  const area = path ? `${path} L${f1(headX)} ${f1(TOP + H)} L0 ${f1(TOP + H)} Z` : "";
  const done = arrive(n - 1);
  const finished = frame >= done;
  const hot = pickNamed(items, overlay.highlight);
  const falls = vals[n - 1] < vals[0];
  const flat = Math.abs(vals[n - 1] - vals[0]) < 1e-9;
  const endCol = flat ? GREY : falls ? RED : GREEN;
  const period = Math.round(fps * 1.3);
  const pulse = finished ? ((frame - done) % period) / period : 0;
  const showX = (i: number) => n <= 7 || (n - 1 - i) % 2 === 0;
  const fallingAt = (i: number) => {
    const prev = i > 0 ? vals[i - 1] : vals[i], next = i < n - 1 ? vals[i + 1] : vals[i];
    return next - prev < 0;
  };
  const id = `cc-tl-${overlay.startFrame ?? 0}`;
  return (
    <Card overlay={overlay}>
      <div style={{ width: W, display: "flex", flexDirection: "column", gap: 10 * k, paddingRight: 200 * k, paddingLeft: 60 * k }}>
        {head}
        <div style={{ position: "relative", width: W, height: HT }}>
          <svg width={W} height={HT} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
            <defs>
              <linearGradient id={`${id}a`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={accent} stopOpacity={0.16} />
                <stop offset="100%" stopColor={accent} stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <YGrid sc={sc} Y={Y} W={W} prefix={prefix} pct={pct} ex={ex} />
            <line x1={0} x2={W * ramp(frame, 0, 18, inOut) * (1 - ex)} y1={TOP + H} y2={TOP + H} stroke="rgba(255,255,255,.7)" strokeWidth={3 * k} />
            {area ? <path d={area} fill={`url(#${id}a)`} /> : null}
            {path ? (
              <path d={path} fill="none" stroke={accent} strokeWidth={6 * k} strokeLinecap="round" strokeLinejoin="round"
                style={{ filter: `drop-shadow(0 0 ${10 * k}px ${accent}88)` }} />
            ) : null}
            {items.map((it, i) => {
              const at = arrive(i);
              if (frame < at) return null;
              const exI = exitOf(frame, dur, n - 1 - i, n);
              const pop = ramp(frame, at, 12, backOut) * (1 - exI);
              const ring = interpolate(frame, [at, at + 16], [0, 1], clamp);
              const last = i === n - 1;
              const col = last && finished ? endCol : accent;
              const x = X(i), y = Y(it.value);
              return (
                <g key={i}>
                  {ring < 1 ? (
                    <circle cx={x} cy={y} r={(10 + 42 * ring) * k} fill="none" stroke={col} strokeWidth={3 * k} opacity={(1 - ring) * 0.8} />
                  ) : null}
                  {last && finished ? (
                    <circle cx={x} cy={y} r={(12 + 34 * pulse) * k} fill="none" stroke={endCol} strokeWidth={2.5 * k}
                      opacity={(1 - pulse) * 0.8 * (1 - ex)} />
                  ) : null}
                  <circle cx={x} cy={y} r={Math.max(0, (last ? 11 : 9) * k * pop)} fill={i === hot ? accent : last && finished ? endCol : INK}
                    stroke={col} strokeWidth={4 * k} />
                </g>
              );
            })}
          </svg>
          {items.map((it, i) => {
            const at = arrive(i);
            const last = i === n - 1;
            const x = X(i), y = Y(it.value);
            const above = fallingAt(i);
            return (
              <React.Fragment key={i}>
                {!last && frame >= at ? (
                  <div style={{ position: "absolute", left: x, top: above ? y - 22 * k : y + 22 * k,
                    transform: `translate(-50%, ${above ? "-100%" : "0"})`, whiteSpace: "nowrap" }}>
                    <Rise at={at + 2}>
                      <span style={{ display: "block", fontFamily: LABEL, fontWeight: 700, fontSize: 26 * k, letterSpacing: "0.04em",
                        color: i === hot ? accent : "#fff", textShadow: "0 2px 10px rgba(0,0,0,.8)" }}>
                        {it.value < 0 ? "−" : ""}{it.prefix || prefix}{fmtD(Math.abs(it.value), dAll)}{tail(it.suffix || suffix)}</span>
                    </Rise>
                  </div>
                ) : null}
                {last && frame >= at ? (
                  <div style={{ position: "absolute", left: x + 26 * k, top: y, transform: "translateY(-50%)" }}>
                    <Pill value={it.value} at={at} frames={Math.round(fps * 0.7)} color={endCol} prefix={it.prefix || prefix}
                      suffix={tail(it.suffix || suffix)} change={signedPct(vals[0], vals[n - 1])} size={34} scale={1 - ex} />
                  </div>
                ) : null}
                {showX(i) ? (
                  <div style={{ position: "absolute", left: x, top: TOP + H + 18 * k, transform: "translateX(-50%)" }}>
                    <Rise at={at}>
                      <span style={{ display: "block", fontFamily: LABEL, fontWeight: i === hot ? 800 : 600, fontSize: 24 * k, letterSpacing: "0.06em",
                        color: i === hot ? accent : "rgba(255,255,255,.7)", whiteSpace: "nowrap" }}>{cap(it.label)}</span>
                    </Rise>
                  </div>
                ) : null}
              </React.Fragment>
            );
          })}
          {overlay.label ? (
            <div style={{ position: "absolute", left: 0, top: TOP + H + 62 * k }}>
              <Caption text={overlay.label} at={at0} />
            </div>
          ) : null}
        </div>
      </div>
      {items.map((_, i) => (i < TICK_MAX ? <Tick key={`t${i}`} at={arrive(i)} volume={0.22} /> : null))}
    </Card>
  );
};

// ================================================================== 9. circle row
/**
 * Outlined circles in a row on flat black (GoMotion's TUNNELS / CUTS): each
 * ring draws on clockwise from 12 o'clock with a tick as it closes, the word
 * rises inside, a value rolls under it; connectors join the neighbours;
 * during the hold the circles take the accent one at a time.
 */
const CircleRow: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, height, fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const given = itemsOf(overlay, 5);
  const items: OverlayItem[] = given.length ? given : [{ label: str(overlay.text).trim() || "…" }];
  const n = items.length;
  const kicker = given.length ? clip(cap(overlay.text).replace(/\s+/g, " "), 44) : "";
  const R = (n >= 4 ? 90 : 110) * k, GAP = 90 * k, SW = 2.5 * k;
  const total = n * 2 * R + (n - 1) * GAP;
  const cy = height * 0.5 + 10 * k;
  const cx = (i: number) => width / 2 - total / 2 + R + i * (2 * R + GAP);
  const at0 = Math.round(fps * 0.4), step = Math.round(fps * 0.35);
  const at = (i: number) => at0 + i * step;
  const close = (i: number) => at(i) + 14;
  const lastClose = close(n - 1) + 4;
  const ex = exitOf(frame, dur);
  const cyc = Math.max(1, Math.round(fps * 0.8));
  const holdAt = lastClose + 10;
  const t = Math.max(0, frame - holdAt);
  const c = Math.floor(t / cyc), u = t % cyc;
  const hotNow = c % n, hotPrev = (c - 1 + n) % n;
  const hotP = (i: number) => {
    if (frame < holdAt || n < 2) return 0;
    if (i === hotNow) return Math.min(1, u / 5);
    if (i === hotPrev && c > 0) return Math.max(0, 1 - u / 5);
    return 0;
  };
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <Black />
      {kicker ? (
        <div style={{ position: "absolute", left: 0, right: 0, top: 96 * k, display: "flex", justifyContent: "center" }}>
          <Letters text={kicker} at={0} step={0.4} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 26 * k, letterSpacing: "0.32em",
            color: "rgba(255,255,255,.72)", textAlign: "center" }} />
        </div>
      ) : null}
      <AbsoluteFill style={{ transform: `scale(${hold})` }}>
        <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0 }}>
          {items.map((_, i) => {
            if (i === n - 1) return null;
            const p = ramp(frame, lastClose + i * 4, 12, inOut) * (1 - ex);
            const x1 = cx(i) + R + SW, x2 = cx(i + 1) - R - SW;
            return <line key={`c${i}`} x1={x1} x2={x1 + (x2 - x1) * p} y1={cy} y2={cy} stroke="rgba(255,255,255,.35)" strokeWidth={2 * k} />;
          })}
          {items.map((_, i) => {
            const p = ramp(frame, at(i), 18, expoOut) * (1 - exitOf(frame, dur, n - 1 - i, n));
            const h = hotP(i);
            return (
              <g key={i} transform={`rotate(-90 ${cx(i)} ${cy})`}>
                <circle cx={cx(i)} cy={cy} r={R} fill="none" stroke="#fff" strokeWidth={SW} pathLength={1} strokeDasharray={1}
                  strokeDashoffset={1 - p} strokeLinecap="round" />
                {h > 0 ? (
                  <circle cx={cx(i)} cy={cy} r={R} fill="none" stroke={accent} strokeWidth={SW + 1 * k} pathLength={1} strokeDasharray={1}
                    strokeDashoffset={1 - p} opacity={h} style={{ filter: `drop-shadow(0 0 ${14 * k}px ${accent}aa)` }} />
                ) : null}
              </g>
            );
          })}
        </svg>
        {items.map((it, i) => {
          const word = cap(it.label).replace(/\s+/g, " ").trim();
          const fit = fitText(word, R * 1.5, 30 * k, 16 * k, 2, 0.66);
          const h = hotP(i);
          const v = toNum(it.value);
          const hasV = Number.isFinite(v);
          const { suffix, prefix } = units(overlay, []);
          return (
            <React.Fragment key={i}>
              <div style={{ position: "absolute", left: cx(i) - R, top: cy - R, width: 2 * R, height: 2 * R, display: "flex",
                flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
                {fit.ls.map((ln, j) => (
                  <Rise key={j} at={at(i) + 6 + j * 3}>
                    <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: fit.size, letterSpacing: "0.16em",
                      lineHeight: 1.1, textAlign: "center", color: h > 0 ? `rgba(255,255,255,${1 - h})` : "#fff", position: "relative",
                      whiteSpace: "nowrap" }}>
                      {ln}
                      {h > 0 ? <span style={{ position: "absolute", left: 0, right: 0, top: 0, color: accent, opacity: h }}>{ln}</span> : null}
                    </span>
                  </Rise>
                ))}
              </div>
              {hasV ? (
                <div style={{ position: "absolute", left: cx(i), top: cy + R + 26 * k, transform: "translateX(-50%)", whiteSpace: "nowrap" }}>
                  <Rise at={close(i)}>
                    <Odometer value={Math.abs(v)} at={close(i)} frames={Math.round(fps * 0.6)} size={40 * k} color={h > 0.5 ? accent : "#fff"}
                      prefix={(v < 0 ? "−" : "") + prefix} suffix={tail(suffix)} suffixScale={0.55} />
                  </Rise>
                </div>
              ) : null}
            </React.Fragment>
          );
        })}
      </AbsoluteFill>
      {items.map((_, i) => (i < 5 ? <Tick key={`t${i}`} at={close(i)} volume={0.22} /> : null))}
    </AbsoluteFill>
  );
};

// ================================================================== 10. network tree
/**
 * A hub chip (overlay.label) on the case-file dark backdrop; a trunk line
 * draws right, drops to a bus and forks into right-angled branches that
 * pop labelled tiles (a still each when the overlay carries media, else a
 * dark tile with the node's initial). A comet keeps running down each
 * branch in turn while the card holds.
 */
const NetworkTree: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, height, fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const items = itemsOf(overlay, 5);
  const pics = stills(overlay, 5);
  const n = items.length;
  const hubTxt = clip(cap(overlay.label).replace(/\s+/g, " ").trim() || "SOURCE", 22);
  const chipH = 62 * k, chipW = hubTxt.length * 28 * 0.64 * k + 64 * k;
  const hubX = 110 * k, hubY = 360 * k;
  const cyh = hubY + chipH / 2;
  const hubRight = hubX + chipW;
  const left = 470 * k, avail = width - 110 * k - left;
  const trunkX = hubRight + 170 * k;
  const busY = 500 * k, tileTop = 570 * k;
  const tileW = Math.min(300 * k, avail / Math.max(1, n) - 30 * k), tileH = tileW * (2 / 3);
  const ncx = (i: number) => left + (i + 0.5) * (avail / Math.max(1, n));
  const trunkAt = Math.round(fps * 0.35), trunkN = Math.round(fps * 0.5);
  const brAt = (i: number) => trunkAt + trunkN + i * Math.round(fps * 0.2);
  const brN = Math.round(fps * 0.35);
  const landAt = (i: number) => brAt(i) + brN;
  const ex = exitOf(frame, dur);
  const trunkP = ramp(frame, trunkAt, trunkN, inOut) * (1 - ex);
  const allDone = n ? landAt(n - 1) + 6 : trunkAt + trunkN;
  const period = Math.max(1, Math.round(fps * 0.9));
  const tt = Math.max(0, frame - allDone);
  const cometOn = n > 0 && frame >= allDone ? Math.floor(tt / period) % n : -1;
  const cu = (tt % period) / period;
  const hubIn = ramp(frame, 2, 16, backOut);
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <CaseBackdrop tone="dark" seed={3} />
      <div style={{ position: "absolute", left: 100 * k, top: 76 * k, display: "flex", flexDirection: "column", gap: 6 * k }}>
        <Kicker text={overlay.subtitle} accent={accent} />
        <ChartTitle text={overlay.text} accent={accent} size={50} maxW={1100 * k} />
      </div>
      <AbsoluteFill style={{ transform: `scale(${hold})`, opacity: 1 - ramp(frame, dur - 6, 5) }}>
        <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          <path d={`M${f1(hubRight)} ${f1(cyh)} H${f1(trunkX)}`} fill="none" stroke={accent} strokeWidth={5 * k} strokeLinejoin="miter"
            pathLength={1} strokeDasharray={1} strokeDashoffset={1 - trunkP} style={{ filter: `drop-shadow(0 0 ${8 * k}px ${accent}66)` }} />
          {items.map((_, i) => {
            const p = ramp(frame, brAt(i), brN, inOut) * (1 - ex);
            const d = `M${f1(trunkX)} ${f1(cyh)} V${f1(busY)} H${f1(ncx(i))} V${f1(tileTop)}`;
            return (
              <g key={i}>
                <path d={d} fill="none" stroke={accent} strokeWidth={5 * k} strokeLinejoin="miter" pathLength={1} strokeDasharray={1}
                  strokeDashoffset={1 - p} />
                {cometOn === i && p >= 0.999 ? (
                  <path d={d} fill="none" stroke="#fff" strokeWidth={6 * k} strokeLinecap="round" pathLength={1}
                    strokeDasharray="0.16 0.84" strokeDashoffset={0.16 - cu * 1.16} opacity={0.9}
                    style={{ filter: `drop-shadow(0 0 ${10 * k}px #fff)` }} />
                ) : null}
              </g>
            );
          })}
          <circle cx={trunkX} cy={cyh} r={7 * k * trunkP} fill="#fff" />
        </svg>
        <div style={{ position: "absolute", left: hubX, top: hubY, width: chipW, height: chipH, boxSizing: "border-box", display: "flex",
          alignItems: "center", justifyContent: "center", padding: `0 ${20 * k}px`, background: "rgba(8,14,26,.92)",
          border: `${2 * k}px solid rgba(255,255,255,.22)`, borderLeft: `${8 * k}px solid ${accent}`, borderRadius: 10 * k,
          boxShadow: `0 ${10 * k}px ${30 * k}px rgba(0,0,0,.5)`, transform: `scale(${hubIn * (1 - ex)})`, transformOrigin: "0 50%",
          whiteSpace: "nowrap", overflow: "hidden" }}>
          <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 28 * k, letterSpacing: "0.14em", color: "#fff", overflow: "hidden",
            textOverflow: "ellipsis" }}>{hubTxt}</span>
        </div>
        {items.map((it, i) => {
          const land = landAt(i);
          if (frame < land) return null;
          const exI = exitOf(frame, dur, i, n);
          const pop = ramp(frame, land, 14, backOut) * (1 - exI);
          const pic = pics[i];
          const initial = Array.from(cap(it.label).trim())[0] || "•";
          const sub = clip(str(it.text).replace(/\s+/g, " ").trim(), 30);
          return (
            <div key={i} style={{ position: "absolute", left: ncx(i) - tileW / 2, top: tileTop, width: tileW, display: "flex",
              flexDirection: "column", alignItems: "center", gap: 14 * k }}>
              <div style={{ width: tileW, height: tileH, border: `${4 * k}px solid #fff`, boxSizing: "border-box", overflow: "hidden",
                position: "relative", background: "#0a1020", transform: `scale(${pop})`, transformOrigin: "50% 0",
                boxShadow: `0 ${14 * k}px ${34 * k}px rgba(0,0,0,.55)` }}>
                {pic ? (
                  <SafeImg src={pic} style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
                ) : (
                  <>
                    <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center",
                      fontFamily: DISPLAY, fontSize: 96 * k, color: "rgba(255,255,255,.9)", lineHeight: 1 }}>{initial}</div>
                    <div style={{ position: "absolute", right: 0, top: 0, width: 0, height: 0, borderTop: `${34 * k}px solid ${accent}`,
                      borderLeft: `${34 * k}px solid transparent` }} />
                  </>
                )}
              </div>
              <Rise at={land + 4} style={{ maxWidth: tileW + 60 * k }}>
                <span style={{ display: "block", fontFamily: LABEL, fontWeight: 700, fontSize: 28 * k, letterSpacing: "0.12em", color: "#fff",
                  textAlign: "center", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{cap(it.label)}</span>
              </Rise>
              {sub ? (
                <Rise at={land + 7} style={{ maxWidth: tileW + 60 * k, marginTop: -8 * k }}>
                  <span style={{ display: "block", fontFamily: LABEL, fontWeight: 600, fontSize: 22 * k, letterSpacing: "0.04em",
                    color: "rgba(255,255,255,.62)", textAlign: "center", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{sub}</span>
                </Rise>
              ) : null}
            </div>
          );
        })}
      </AbsoluteFill>
      {items.map((_, i) => (i < 5 ? <Tick key={`t${i}`} at={landAt(i)} volume={0.22} /> : null))}
    </AbsoluteFill>
  );
};

// ================================================================== 11. wave chain
/**
 * A sine wave on black drawing left to right, one half-period per item after
 * the first; the first label sits at the start and the rest at the crests
 * (above) and troughs (below), each popping a node with a tick as the head
 * arrives, arrowheads between them reading as "->". A green dot rides the
 * wave through the hold.
 */
const WaveChain: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, height, fps, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const given = itemsOf(overlay, 6);
  const items: OverlayItem[] = given.length ? given : [{ label: str(overlay.text).trim() || "…" }];
  const n = items.length;
  const kicker = given.length ? clip(cap(overlay.text).replace(/\s+/g, " "), 44) : "";
  const SPAN = 1400 * k, A = 150 * k;
  const x0 = width / 2 - SPAN / 2, cy = height * 0.52;
  const halves = n - 1;
  const wave = React.useMemo(() => {
    const N = 240;
    const pts: Pt[] = [];
    for (let s = 0; s <= N; s++) {
      const u = s / N;
      pts.push([x0 + SPAN * u, cy - A * Math.sin(Math.PI * halves * u)]);
    }
    return { pts, cum: cumOf(pts) };
  }, [x0, cy, SPAN, A, halves]);
  const total = wave.cum[wave.cum.length - 1] || 1;
  const drawAt = Math.round(fps * 0.4), drawN = Math.round(fps * 1.6);
  const ex = exitOf(frame, dur);
  const d = ramp(frame, drawAt, drawN, inOut) * (1 - ex);
  const run = d * total;
  const headPt = along(wave.pts, wave.cum, run).p;
  // Node m sits at the wave's start (m = 0) or its m-th extremum.
  const uOf = (m: number) => (m === 0 ? 0 : (m - 0.5) / Math.max(1, halves));
  const nodeAt = (m: number) => frameWhen(drawAt, drawN, (x) => inOut(x), uOf(m) * 0.98 + (m === 0 ? 0 : 0.01));
  const nodePt = (m: number): Pt => [x0 + SPAN * uOf(m), m === 0 ? cy : cy - A * Math.sin(Math.PI * halves * uOf(m))];
  const done = drawAt + drawN;
  const rideT = Math.round(fps * 4);
  const rideU = frame >= done ? 1 - Math.abs((((frame - done) % rideT) / rideT) * 2 - 1) : 0;
  const ridePt = along(wave.pts, wave.cum, rideU * total).p;
  const arrows = Array.from({ length: Math.max(0, n - 1) }, (_, m) => {
    const u = (uOf(m) + uOf(m + 1)) / 2;
    const r = u * total * 0.999;
    const h = along(wave.pts, wave.cum, r);
    return { p: h.p, ang: (h.ang * 180) / Math.PI, u };
  });
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <Black />
      {kicker ? (
        <div style={{ position: "absolute", left: 0, right: 0, top: 96 * k, display: "flex", justifyContent: "center" }}>
          <Letters text={kicker} at={0} step={0.4} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 26 * k, letterSpacing: "0.32em",
            color: "rgba(255,255,255,.72)", textAlign: "center" }} />
        </div>
      ) : null}
      <AbsoluteFill style={{ transform: `scale(${hold})` }}>
        <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0 }}>
          {run > 0 ? (
            <>
              <path d={partialD(wave.pts, wave.cum, run)} fill="none" stroke="#fff" strokeWidth={3 * k} strokeLinecap="round" strokeLinejoin="round" />
              {d < 1 ? (
                <circle cx={headPt[0]} cy={headPt[1]} r={9 * k} fill={accent} style={{ filter: `drop-shadow(0 0 ${14 * k}px ${accent})` }} />
              ) : null}
            </>
          ) : null}
          {arrows.map((a, m) => {
            const show = ramp(frame, frameWhen(drawAt, drawN, (x) => inOut(x), a.u), 8) * (1 - ex);
            return (
              <g key={`a${m}`} transform={`translate(${f1(a.p[0])} ${f1(a.p[1])}) rotate(${f1(a.ang)})`} opacity={show}>
                <path d={`M${f1(-12 * k)} ${f1(-10 * k)} L${f1(4 * k)} 0 L${f1(-12 * k)} ${f1(10 * k)}`} fill="none" stroke="rgba(255,255,255,.7)"
                  strokeWidth={2.5 * k} strokeLinecap="round" strokeLinejoin="round" />
              </g>
            );
          })}
          {items.map((_, m) => {
            const at = nodeAt(m);
            if (frame < at) return null;
            const p = nodePt(m);
            const exI = exitOf(frame, dur, n - 1 - m, n);
            const pop = ramp(frame, at, 12, backOut) * (1 - exI);
            const ring = interpolate(frame, [at, at + 16], [0, 1], clamp);
            return (
              <g key={`n${m}`}>
                {ring < 1 ? (
                  <circle cx={p[0]} cy={p[1]} r={(10 + 44 * ring) * k} fill="none" stroke={accent} strokeWidth={3 * k} opacity={(1 - ring) * 0.85} />
                ) : null}
                <circle cx={p[0]} cy={p[1]} r={Math.max(0, 9 * k * pop)} fill="#fff" />
              </g>
            );
          })}
          {frame >= done ? (
            <circle cx={ridePt[0]} cy={ridePt[1]} r={8 * k} fill={GREEN} opacity={1 - ex} style={{ filter: `drop-shadow(0 0 ${12 * k}px ${GREEN})` }} />
          ) : null}
        </svg>
        {items.map((it, m) => {
          const at = nodeAt(m);
          const p = nodePt(m);
          const crest = m === 0 ? true : m % 2 === 1;
          const big = m === 0 || m === n - 1;
          const size = (big ? 40 : 30) * k;
          const word = clip(cap(it.label).replace(/\s+/g, " ").trim(), 26);
          const estW = word.length * size * 0.64;
          // Labels stay inside the 90 px safe area: an endpoint label slides in along its side.
          const cx = Math.max(estW / 2 + 90 * k, Math.min(width - 90 * k - estW / 2, p[0]));
          const sub = clip(str(it.text).replace(/\s+/g, " ").trim(), 34);
          const above = crest;
          const y = m === 0 ? cy - 34 * k : above ? p[1] - 34 * k : p[1] + 34 * k;
          return (
            <div key={`l${m}`} style={{ position: "absolute", left: cx, top: y, transform: `translate(-50%, ${above ? "-100%" : "0"})`,
              display: "flex", flexDirection: above ? "column-reverse" : "column", alignItems: "center", gap: 4 * k, whiteSpace: "nowrap" }}>
              <Rise at={at + 2}>
                <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: size, letterSpacing: "0.16em", lineHeight: 1.1,
                  color: big ? "#fff" : "rgba(255,255,255,.92)", textAlign: "center" }}>{word}</span>
              </Rise>
              {sub ? (
                <Rise at={at + 6}>
                  <span style={{ display: "block", fontFamily: MONO, fontWeight: 500, fontSize: 20 * k, letterSpacing: "0.16em",
                    color: accent, textAlign: "center" }}>{cap(sub)}</span>
                </Rise>
              ) : null}
            </div>
          );
        })}
      </AbsoluteFill>
      {items.map((_, m) => (m < 6 ? <Tick key={`t${m}`} at={nodeAt(m)} volume={0.22} /> : null))}
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ registry
export const LOOKS: Record<string, Look> = {
  "cc-line-ticker": LineTicker,
  "cc-bars-ticker": BarsTicker,
  "cc-columns-ticker": ColumnsTicker,
  "cc-planned-vs-actual": PlannedVsActual,
  "cc-two-series": TwoSeries,
  "cc-snow-sites": SnowSites,
  "cc-tick-bars": TickBars,
  "cc-tick-line": TickLine,
  "cc-circle-row": CircleRow,
  "cc-network-tree": NetworkTree,
  "cc-wave-chain": WaveChain,
};
