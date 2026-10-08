import React from "react";
import { AbsoluteFill } from "remotion";
import type { Overlay } from "../../types";
import { GROTESK, GROTESK_CAP, INTER, SUBLINE } from "../fonts";
import { backOut, clamp01, cubicIn, cubicInOut, cubicOut, expoOut, idle, lerp, motionBlur, prog } from "../motion/ease";
import { guard, hash, rgba, useSvgId, type Look } from "./proKit";
import { num, str } from "./proFormat";
import { Glint, KineticLine, SOFT_WHITE, WHITE, SAFE, blockAt, fitLines, isRight, settle, softShadow, widthOf,
  zoneFor, type Zone } from "./typeKit";
import { Backing, useLook } from "./LibKinetic";
import { Caps, DIM, capsWidth } from "./LibKtDates";
import { Frost } from "./frost";
import { useLookSound } from "./LookSounds";
import scale from "./typeScale.json";

/**
 * LOOKS PACK 4 (2026-10-08, the owner: "it's not a weather channel tool ... it needs to do everything"): the
 * figures and the comparisons every niche says - finance, business, tech, sports, history, travel, food - in the
 * kinetic-type system of the kt- looks (typeKit.tsx: white bold grotesk, ONE accent following the brand kit,
 * frosted glass or a soft shade - never an outline, a yellow fill or a poster face; sizes from typeScale.json
 * "pack4"). LibKtCards4.tsx has the cards about people, steps, causes, cases, posts and claims.
 *
 *   kt-price    PRICE CHART   a price said over time ("from $1,000 in 2017 to nearly $20,000 ... then crashed to
 *                             $3,200"): a frosted market card - the live price counting at the head of a line that
 *                             draws to each said price ON its word (a small market wander between them, always
 *                             through the said prices), the peak or the crash called out, the change in a pill
 *   kt-money    MONEY         a big sum ("$1 billion for Instagram"): the digits roll in on reels (an odometer, the
 *                             left one first, a touch of motion blur) and settle, the scale word tracking in under
 *                             them (BILLION), an accent rule drawing on, one line of what it was
 *   kt-table    TABLE         two sides on two to four things ("Messi 672 goals in 778 games; Ronaldo 701 in
 *                             1,000"): a frosted table - the sides' names, a row a thing, each cell rising on its word
 *   kt-proscons PROS & CONS   two columns, a check or a cross drawing on beside each point as it is said
 *   kt-podium   PODIUM        a top three: frosted podium blocks rising (second, first, third) on each name, the
 *                             winner's numeral in the accent with one light sweep
 *   kt-versus   VERSUS        a head-to-head as a scoreboard low in the middle: two frosted halves sliding in on
 *                             their names, the scores counting, the winner's in the accent
 *
 * Every look: an eased entry of 12-24 frames, each part landing on its own word (items[].at, seconds from the
 * look's start), a gentle idle, every element leaving in the last 12 frames (the mirrored exit). Only the
 * planner's words and figures are drawn (src/lookpack4.py); a look that cannot set them whole draws nothing.
 */

// ------------------------------------------------------------------ shared
/** The size unit: the frame height, or the width's 16:9 height on a tall frame. */
const unitOf = (W: number, H: number) => Math.min(H, (W * 9) / 16);
/** Font px whose capitals stand `sh` of the unit (fontScale applied). */
const capFont = (sh: number, U: number, ks: number, cap = GROTESK_CAP) => (sh * U * ks) / cap;
type P4 = Record<string, { share?: number; w?: number; h?: number }>;
const PACK4 = (scale as unknown as { pack4: P4 }).pack4;
const share = (key: string) => PACK4[key]?.share ?? 0.02;
const cardW = (key: string, W: number, H: number, tall = 0.88) => (W >= H ? (PACK4[key]?.w ?? 0.38) : tall) * W;

/** The 30-fps frame a part said `at` seconds into the look lands on (a frame before its word, never earlier). */
const saidAt = (at: number | null, fallback: number) => (at !== null && Number.isFinite(at) && at >= 0
  ? Math.max(2, at * 30 - 1) : fallback);

const TABULAR: React.CSSProperties = { fontVariantNumeric: "tabular-nums", fontFeatureSettings: '"tnum" 1' };
const DOWN_RED = "#F2555A";

/** Words that rise out of a mask (one line), leaving by sinking back into it. */
const Masked: React.FC<{ text: string; font: string; size: number; weight: number; color?: string; p: number; x?: number;
  tracking?: number; upper?: boolean; align?: "left" | "right" | "center"; tabular?: boolean; shadow?: string }> =
  ({ text, font, size, weight, color = WHITE, p, x = 0, tracking = -0.01, upper = false, align = "left", tabular = false,
    shadow }) => (
    <div style={{ overflow: "hidden", height: size * 1.22, paddingTop: size * 0.06, marginTop: -size * 0.06 }}>
      <div style={{ fontFamily: font, fontWeight: weight, fontSize: size, lineHeight: 1.12, color, whiteSpace: "nowrap",
        letterSpacing: `${tracking}em`, textTransform: upper ? "uppercase" : undefined, textAlign: align,
        ...(tabular ? TABULAR : {}), textShadow: shadow, opacity: clamp01(p * 3) * (1 - clamp01(x * 1.6)),
        transform: `translateY(${((1 - clamp01(p)) * 104 + cubicIn(clamp01(x)) * 104).toFixed(2)}%)` }}>{text}</div>
    </div>
  );

/** A sum as written: "$20,000", "$4.5B", "€3.20" - the decimals as said (at most two). */
const decimalsSaid = (vals: number[]) => Math.min(2, Math.max(0, ...vals.map((v) => {
  const s = String(Math.abs(v));
  return s.includes(".") && !s.includes("e") ? s.split(".")[1].length : 0;
})));
const sumText = (v: number, dec: number, prefix: string, suffix: string) =>
  `${v < 0 ? "−" : ""}${prefix}${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec })}${suffix}`;
/** A figure with the unit it was said with: "8 GB", "$999", "672", "36¢", "6.1 IN". */
const cellText = (v: number, prefix: string, suffix: string) => {
  const dec = decimalsSaid([v]);
  const body = Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });
  const glued = suffix === "%" || suffix === "¢" || /^[KMBT]$/.test(suffix);
  return `${v < 0 ? "−" : ""}${prefix}${body}${glued ? suffix : suffix ? ` ${suffix}` : ""}`;
};
/** "+1,900%", "−84%" - the change from the first to the last, or "" when it cannot be said. */
const changeText = (a: number, b: number) => {
  if (!Number.isFinite(a) || !Number.isFinite(b) || Math.abs(a) < 1e-9) return "";
  const pct = ((b - a) / Math.abs(a)) * 100;
  const v = Math.abs(pct);
  const body = v >= 100 ? Math.round(v).toLocaleString("en-US") : v >= 10 ? String(Math.round(v)) : v.toFixed(1).replace(/\.0$/, "");
  return `${pct < 0 ? "−" : "+"}${body}%`;
};

/** A small solid triangle pointing down (▼) or up (▲) with its tip at (x, y). */
const tri = (x: number, y: number, s: number, down: boolean) => (down
  ? `M${x.toFixed(1)},${y.toFixed(1)} L${(x - s).toFixed(1)},${(y - s * 1.5).toFixed(1)} L${(x + s).toFixed(1)},${(y - s * 1.5).toFixed(1)} Z`
  : `M${x.toFixed(1)},${y.toFixed(1)} L${(x - s).toFixed(1)},${(y + s * 1.5).toFixed(1)} L${(x + s).toFixed(1)},${(y + s * 1.5).toFixed(1)} Z`);

const polyD = (pts: [number, number][]) => (pts.length ? `M${pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" L")}` : "");

/** A deterministic 0..1 for an integer seed (no Math.random in a render). */
const r01 = (i: number) => {
  const x = Math.sin(i * 12.9898 + 78.233) * 43758.5453123;
  return x - Math.floor(x);
};

// ================================================================== kt-price
interface Pt { label: string; value: number; at: number | null; text: string }
const pointsOf = (ov: Overlay): Pt[] => (Array.isArray(ov.items) ? ov.items : [])
  .map((it) => ({ label: str(it?.label), value: num(it?.value), at: num((it as { at?: unknown } | undefined)?.at),
    text: str(it?.text) }))
  .filter((p): p is Pt => p.value !== null && Number.isFinite(p.value))
  .slice(0, 6);

/**
 * A price said over time, as a frosted market card on the calm side (home: the right-hand panel): the subject
 * as a kicker, the live price big under it, counting as the line's head moves; the chart under them - a hairline
 * baseline and two faint guides - where the line draws to each said price ON its word (18 frames, eased) with a
 * small market wander between two prices (deterministic, zero at both ends, so the line always passes through
 * what was said) and a soft white fill under it. Each said price leaves a dot and its time (as said) under it;
 * the peak or the crash said (or the line's own high or low) is called out with a ring, a dashed drop line and
 * a pill (ALL-TIME HIGH $20,000). When the last price lands the change from the first counts in a pill beside the
 * price (▲ +1,900%). The card closes into its side.
 */
const Price: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, dir, hot, out, ks } = useLook(overlay, accent);
  const areaId = useSvgId("ktprarea");
  const clipId = useSvgId("ktprclip");
  const pts = pointsOf(overlay);
  const n = pts.length;
  const lands = pts.map((p, i) => (i === 0 ? 8 : saidAt(p.at, 14 + i * 24)));
  for (let i = 1; i < n; i++) lands[i] = Math.max(lands[i], lands[i - 1] + 14);
  // a segment draws from 10 frames before its price's word to 8 after it: the head lands on the word
  const segFrom = (i: number) => lands[i + 1] - 10;
  const SEG = 18;
  const sound = useLookSound(n >= 2 ? [{ name: "ui-swipe", alt: ["swipe", "whoosh-soft"], at: 0, gain_db: -13 },
    ...lands.slice(1).map((at) => ({ name: "ui-tick", alt: ["tick", "count-tick"], at: Math.round(at + 8), gain_db: -11 })),
    { name: "ui-pop", alt: ["pop", "ui-tick"], at: Math.round(lands[n - 1] + 14), gain_db: -10 }] : null);
  if (n < 2) return null;
  const prefix = str(overlay.prefix);
  const suffix = str(overlay.suffix).toUpperCase();
  const title = str(overlay.text) || "Price";
  const vals = pts.map((p) => p.value);
  const dec = decimalsSaid(vals);
  const U = unitOf(W, H);
  const kSize = capFont(share("kicker"), U, ks);
  const vSize0 = capFont(share("priceValue"), U, ks, dir.cap);
  const lSize = capFont(share("small"), U, ks);
  const cSize = capFont(share("callout"), U, ks);
  const pSize = capFont(share("pill"), U, ks);
  const cw = Math.max(cardW("priceCard", W, H), capsWidth(title, capFont(share("kicker"), unitOf(W, H), ks)) + 60 * k);
  const ch = (PACK4.priceCard?.h ?? 0.46) * U * (W >= H ? 1 : 1.4);
  const pad = 30 * k;
  const zone = zoneFor(overlay, "right-panel", cw, ch, W, H) as Zone;
  const r = blockAt(zone, cw, ch, W, H);
  const open = prog(f, 0, 14, S, expoOut);
  const xo = 1 - clamp01(out * 1.4);
  const drift = idle(f, 40 * S, dur) * 3 * k;
  const t = f / S;
  // the price's size: the widest figure fits the card's first half
  let vSize = vSize0;
  const widest = Math.max(...vals.map((v) => widthOf(sumText(v, dec, prefix, suffix), GROTESK, vSize0, 800, -0.01)));
  if (widest > cw * 0.56) vSize = vSize0 * (cw * 0.56) / widest;
  const headH = kSize + 12 * k + vSize * 1.08;
  const labelsH = pts.some((p) => p.label) ? lSize * 2.4 : lSize * 0.8;
  const cx0 = pad, cx1 = cw - pad;
  const cy0 = pad + headH + 26 * k, cy1 = ch - pad - labelsH;
  const chartH = cy1 - cy0;
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const span = hi - lo || Math.abs(hi) || 1;
  const yOf = (v: number) => cy1 - ((v - (lo - span * 0.16)) / (span * 1.42)) * chartH;
  // the points' x: evenly spaced, inset so a callout's pill fits at the edges
  const xs = pts.map((_p, i) => lerp(cx0 + 14 * k, cx1 - 14 * k, n === 1 ? 0 : i / (n - 1)));
  const ys = pts.map((p) => yOf(p.value));
  // the market wander between two said prices (smooth: two slow waves and a fine tick, zero at both ends)
  const seed = hash(`${title}|${vals.join("|")}`) % 9973;
  const SUB = 22;
  const amp = chartH * 0.05;
  const poly: [number, number][] = [];
  for (let i = 0; i < n - 1; i++) {
    const f1 = 1.4 + r01(seed + i * 3) * 1.4, f2 = 3.6 + r01(seed + i * 5 + 1) * 2.4;
    const p1 = r01(seed + i * 7 + 2), p2 = r01(seed + i * 11 + 3);
    const segAmp = amp * (0.6 + 0.5 * Math.min(1, Math.abs(ys[i + 1] - ys[i]) / Math.max(1, chartH * 0.3)));
    for (let s = 0; s < SUB; s++) {
      const u = s / SUB;
      const env = Math.sin(Math.PI * u);
      const wob = segAmp * env * (0.62 * Math.sin(2 * Math.PI * (u * f1 + p1)) + 0.3 * Math.sin(2 * Math.PI * (u * f2 + p2))
        + 0.18 * (r01(seed * 31 + i * 101 + s) - 0.5));
      poly.push([lerp(xs[i], xs[i + 1], u), lerp(ys[i], ys[i + 1], cubicInOut(u) * 0.35 + u * 0.65) + wob]);
    }
  }
  poly.push([xs[n - 1], ys[n - 1]]);
  // how far the line has drawn: segment j at p
  let j = -1, pj = 0;
  for (let i = 0; i < n - 1; i++) {
    const p = prog(f, segFrom(i), SEG, S, cubicInOut);
    if (p > 0) { j = i; pj = p; }
  }
  const firstIn = prog(f, lands[0] - 2, 14, S, expoOut);
  const upto = j < 0 ? 0 : j * SUB + pj * SUB;
  const whole = Math.floor(upto);
  const shown: [number, number][] = poly.slice(0, whole + 1);
  if (whole < poly.length - 1 && upto > whole) {
    const a = poly[whole], b = poly[whole + 1];
    shown.push([lerp(a[0], b[0], upto - whole), lerp(a[1], b[1], upto - whole)]);
  }
  const head = shown[shown.length - 1] || poly[0];
  const live = j < 0 ? vals[0] : lerp(vals[j], vals[j + 1], cubicInOut(pj));
  const reached = (i: number) => (i === 0 ? t >= lands[0] : t >= segFrom(i - 1) + SEG - 1);
  // the callouts: as said (items[].text), else the line's own interior high and low
  const calls: { i: number; text: string; up: boolean }[] = [];
  pts.forEach((p, i) => {
    if (p.text && calls.length < 2) calls.push({ i, text: p.text, up: p.value >= (lo + hi) / 2 });
  });
  if (!calls.length && n >= 3) {
    const iMax = vals.indexOf(hi), iMin = vals.indexOf(lo);
    if (iMax > 0 && iMax < n - 1) calls.push({ i: iMax, text: "Peak", up: true });
    else if (iMin > 0 && iMin < n - 1) calls.push({ i: iMin, text: "Low", up: false });
  }
  const lastLand = segFrom(n - 2) + SEG;
  const pill = prog(f, lastLand + 4, 14, S, (u) => backOut(u, 1.5)) * xo;
  // the change worth a pill: off the peak when the price came down from one, off the low when it came back from
  // one, else since the first price
  const iTop = vals.indexOf(hi), iBot = vals.indexOf(lo);
  const ref = iTop > 0 && iTop < n - 1 && vals[n - 1] < hi ? iTop : iBot > 0 && iBot < n - 1 && vals[n - 1] > lo ? iBot : 0;
  const change = changeText(vals[ref], vals[n - 1]);
  const pillNote = ref === iTop && ref > 0 ? "FROM PEAK" : ref === iBot && ref > 0 ? "FROM LOW"
    : pts[0].label ? `SINCE ${pts[0].label.toUpperCase()}` : "";
  const down = vals[n - 1] < vals[ref];
  const pillCol = down ? DOWN_RED : hot;
  const liveText = sumText(live, dec, prefix, suffix);
  const finalW = Math.max(...vals.map((v) => widthOf(sumText(v, dec, prefix, suffix), GROTESK, vSize, 800, -0.01)));
  const pulse = 0.5 + 0.5 * Math.sin(t / 5);
  // the time labels: centred under their price, the first one starting at it and the last one ending at it; a label
  // that would touch the one before it is left out (the first and the last always stay)
  const labelBoxes: ({ x: number; w: number; align: "left" | "right" | "center" } | null)[] = pts.map((p, i) => {
    if (!p.label) return null;
    const lw = widthOf(p.label.toUpperCase(), SUBLINE, lSize, 700, 0.08) + 4 * k;
    if (i === 0) return { x: Math.max(pad * 0.5, xs[i] - 10 * k), w: lw, align: "left" };
    if (i === n - 1) return { x: Math.min(cw - pad * 0.5, xs[i] + 10 * k) - lw, w: lw, align: "right" };
    return { x: xs[i] - lw / 2, w: lw, align: "center" };
  });
  for (let i = 1; i < n - 1; i++) {
    const b = labelBoxes[i];
    if (!b) continue;
    const prevB = labelBoxes.slice(0, i).reverse().find((x) => x);
    const nextB = labelBoxes[n - 1];
    if ((prevB && b.x < prevB.x + prevB.w + 12 * k) || (nextB && b.x + b.w > nextB.x - 12 * k)) labelBoxes[i] = null;
  }
  /** Where a callout's pill sits: above (or below) its point, centred or to one side, inside the chart, off the line. */
  const calloutAt = (x: number, y: number, pw: number, ph: number, up: boolean) => {
    const gapY = 20 * k;
    const xsC = [x - pw / 2, x - pw + 18 * k, x - 18 * k];
    const ysC = up ? [y - gapY - ph, y + gapY] : [y - gapY - ph, y + gapY];
    const clear = (px: number, py: number) => {
      if (px < pad * 0.4 || px + pw > cw - pad * 0.4 || py < cy0 - ph * 0.7 || py + ph > cy1 - 2 * k) return false;
      return !poly.some((q) => q[0] > px - 6 * k && q[0] < px + pw + 6 * k && q[1] > py - 6 * k && q[1] < py + ph + 6 * k);
    };
    for (const py of ysC) for (const px of xsC) if (clear(px, py)) return { px, py, above: py < y };
    // nothing clear next to it: higher up over its point, as high as the chart allows, off the line
    for (const px of xsC) {
      for (let py = y - gapY - ph; py >= cy0 - ph * 0.7; py -= 6 * k) if (clear(px, py)) return { px, py, above: true };
    }
    const px = Math.max(pad * 0.4, Math.min(cw - pad * 0.4 - pw, x - pw / 2));
    return { px, py: Math.max(cy0 - ph * 0.7, y - gapY - ph), above: true };
  };
  return (
    <AbsoluteFill>
      {sound}
      <Frost x={r.x} y={r.y - drift} w={cw} h={ch} k={k} p={open} out={out} right={isRight(zone)} radius={16}>
        <div style={{ position: "absolute", left: pad, top: pad, right: pad }}>
          <div style={{ height: kSize, marginBottom: 12 * k }}>
            <Caps text={title} size={kSize} color={dir.id === "doc" ? "rgba(250,250,247,0.86)" : hot} at={3} out={out} k={k} />
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 16 * k }}>
            <div style={{ position: "relative", minWidth: finalW, fontFamily: GROTESK, fontWeight: 800, fontSize: vSize, lineHeight: 1,
              letterSpacing: "-0.01em", color: WHITE, whiteSpace: "nowrap", ...TABULAR, textShadow: softShadow(k, 0.45),
              opacity: firstIn * xo, transform: `translateY(${((1 - firstIn) * 0.18 * vSize).toFixed(2)}px) scale(${settle(f, lastLand, S).toFixed(4)})`,
              transformOrigin: "left center" }}>
              {liveText}
              <span style={{ position: "absolute", inset: 0, overflow: "hidden", mixBlendMode: "screen" }}>
                <Glint p={(t - lastLand) / 20} />
              </span>
            </div>
            {change && pill > 0.001 ? (
              <div style={{ display: "flex", alignItems: "center", gap: 7 * k, padding: `${5 * k}px ${12 * k}px`, borderRadius: pSize,
                background: "rgba(8,10,14,0.62)", boxShadow: `inset 0 0 0 ${Math.max(1, k).toFixed(1)}px ${rgba(pillCol, 0.75)}`,
                opacity: clamp01(pill * 1.4), transform: `scale(${(0.86 + 0.14 * pill).toFixed(4)})`, transformOrigin: "left center",
                whiteSpace: "nowrap" }}>
                <svg width={pSize * 0.8} height={pSize * 0.8} style={{ overflow: "visible" }}>
                  <path d={tri(pSize * 0.4, down ? pSize * 0.8 : 0, pSize * 0.32, down)} fill={pillCol} />
                </svg>
                <span style={{ fontFamily: GROTESK, fontWeight: 800, fontSize: pSize, lineHeight: 1, color: WHITE, ...TABULAR }}>{change}</span>
                {pillNote ? (
                  <span style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: lSize * 0.92, lineHeight: 1, letterSpacing: "0.1em",
                    color: DIM, marginLeft: 2 * k }}>{pillNote}</span>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
        <svg width={cw} height={ch} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          <defs>
            <linearGradient id={areaId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#ffffff" stopOpacity={0.2} />
              <stop offset="100%" stopColor="#ffffff" stopOpacity={0} />
            </linearGradient>
            <clipPath id={clipId}><rect x={0} y={0} width={cw} height={cy1 + 1} /></clipPath>
          </defs>
          {/* the baseline and two faint guides */}
          {[0, 1, 2].map((g) => {
            const y = g === 0 ? cy1 : lerp(cy1, cy0, g / 3);
            const o = prog(f, 4 + g * 2, 14, S, cubicOut) * xo;
            return <line key={g} x1={cx0} x2={lerp(cx0, cx1, prog(f, 2 + g * 2, 18, S, expoOut))} y1={y} y2={y}
              stroke={g === 0 ? "rgba(255,255,255,0.28)" : "rgba(255,255,255,0.09)"} strokeWidth={Math.max(1, 1.3 * k)}
              strokeDasharray={g === 0 ? undefined : `${3 * k} ${6 * k}`} opacity={o} />;
          })}
          {shown.length >= 2 ? (
            <g clipPath={`url(#${clipId})`} opacity={xo}>
              <path d={`${polyD(shown)} L${head[0].toFixed(1)},${cy1} L${shown[0][0].toFixed(1)},${cy1} Z`} fill={`url(#${areaId})`} />
              <path d={polyD(shown)} fill="none" stroke={WHITE} strokeWidth={Math.max(2, 3.2 * k)} strokeLinecap="round"
                strokeLinejoin="round" style={{ filter: `drop-shadow(0 0 ${(5 * k).toFixed(1)}px rgba(255,255,255,0.35))` }} />
            </g>
          ) : null}
          {/* each said price: its dot once the line has reached it */}
          {pts.map((_p, i) => {
            const on = reached(i) ? prog(f, i === 0 ? lands[0] : segFrom(i - 1) + SEG - 2, 8, S, (u) => backOut(u, 1.8)) : 0;
            return on > 0.001 ? <circle key={i} cx={xs[i]} cy={ys[i]} r={4.2 * k * on} fill={WHITE} opacity={xo}
              stroke="rgba(8,10,14,0.6)" strokeWidth={1.4 * k} /> : null;
          })}
          {/* the head: a ring breathing in the accent while the line moves */}
          {firstIn > 0.01 && out <= 0 ? (
            <g>
              <circle cx={head[0]} cy={head[1]} r={(10 + 3 * pulse) * k} fill={rgba(hot, 0.18)} />
              <circle cx={head[0]} cy={head[1]} r={5.2 * k} fill={WHITE} stroke={hot} strokeWidth={2.6 * k} />
            </g>
          ) : null}
          {/* the callouts: a ring ping, a dashed drop line */}
          {calls.map((c, m) => {
            const at = (c.i === 0 ? lands[0] : segFrom(c.i - 1) + SEG) + 2;
            const p = prog(f, at, 14, S, expoOut) * xo;
            if (p <= 0.001) return null;
            const ping = clamp01((t - at) / 22);
            return (
              <g key={m}>
                <line x1={xs[c.i]} x2={xs[c.i]} y1={ys[c.i] + 8 * k} y2={lerp(ys[c.i] + 8 * k, cy1, p)} stroke="rgba(255,255,255,0.32)"
                  strokeWidth={Math.max(1, 1.2 * k)} strokeDasharray={`${3 * k} ${4 * k}`} />
                {ping < 1 ? <circle cx={xs[c.i]} cy={ys[c.i]} r={(6 + 18 * cubicOut(ping)) * k} fill="none" stroke={hot}
                  strokeWidth={Math.max(1.2, 2 * k)} opacity={(1 - ping) * 0.9} /> : null}
                <circle cx={xs[c.i]} cy={ys[c.i]} r={6 * k * p} fill={hot} />
              </g>
            );
          })}
        </svg>
        {/* the times as said, under their prices (the first from its left, the last to its right: inside the card) */}
        {labelBoxes.map((b, i) => (b ? (
          <div key={`l${i}`} style={{ position: "absolute", top: cy1 + lSize * 0.85, left: b.x, width: b.w, textAlign: b.align,
            opacity: (reached(i) ? prog(f, i === 0 ? lands[0] : segFrom(i - 1) + SEG - 4, 10, S, cubicOut) : 0) * xo }}>
            <span style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: lSize, letterSpacing: "0.08em", color: DIM,
              textTransform: "uppercase", whiteSpace: "nowrap" }}>{pts[i].label}</span>
          </div>
        ) : null))}
        {/* the callouts' pills, each where it is clear of the line and inside the chart */}
        {calls.map((c, m) => {
          const at = (c.i === 0 ? lands[0] : segFrom(c.i - 1) + SEG) + 4;
          const p = prog(f, at, 14, S, expoOut) * xo;
          if (p <= 0.001) return null;
          const label = c.text.toUpperCase();
          const fig = sumText(vals[c.i], dec, prefix, suffix);
          const pw = widthOf(label, SUBLINE, cSize * 0.86, 700, 0.12) + widthOf(fig, GROTESK, cSize, 800) + 34 * k;
          const ph = cSize * 1.9;
          const { px, py, above } = calloutAt(xs[c.i], ys[c.i], pw, ph, c.up);
          return (
            <div key={`c${m}`} style={{ position: "absolute", left: px, top: py, width: pw, height: ph, borderRadius: ph / 2,
              display: "flex", alignItems: "center", justifyContent: "center", gap: 9 * k, background: "rgba(8,10,14,0.78)",
              boxShadow: `inset 0 0 0 ${Math.max(1, k).toFixed(1)}px ${rgba(hot, 0.65)}, 0 ${(6 * k).toFixed(1)}px ${(16 * k).toFixed(1)}px rgba(0,0,0,0.35)`,
              opacity: clamp01(p * 1.3), transform: `translateY(${((1 - p) * (above ? 8 : -8) * k).toFixed(2)}px)` }}>
              <span style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: cSize * 0.86, letterSpacing: "0.12em", color: hot,
                whiteSpace: "nowrap" }}>{label}</span>
              <span style={{ fontFamily: GROTESK, fontWeight: 800, fontSize: cSize, color: WHITE, whiteSpace: "nowrap", ...TABULAR }}>{fig}</span>
            </div>
          );
        })}
      </Frost>
    </AbsoluteFill>
  );
};

// ================================================================== kt-money
const SCALE_WORDS = new Set(["THOUSAND", "MILLION", "BILLION", "TRILLION"]);

/** One digit reel: it spins `turns` whole turns and lands on `to`, the motion blurred while fast, a small settle. */
const Reel: React.FC<{ to: number; turns: number; at: number; len: number; size: number; font: string; color: string;
  k: number; out: number; f: number; S: number; w: number }> = ({ to, turns, at, len, size, font, color, k, out, f, S, w }) => {
  const ease = (u: number) => 1 - (1 - u) ** 4;
  const e = prog(f, at, len, S, ease);
  const e1 = prog(f + S, at, len, S, ease);
  const cells = turns * 10 + to;                     // cells passed from 0 to the landing
  const pos = cells * e;                             // the reel's position, in cells
  const h = size * 1.04;
  const blur = motionBlur((e1 - e) * cells * h, k, 7);
  const land = at + len;
  const u = clamp01((f / S - land + 1) / 10);
  const bounce = f / S > land - 1 ? Math.sin(u * Math.PI) * (1 - u) * 0.06 * h : 0;
  const base = Math.floor(pos);
  const frac = pos - base;
  const digit = (c: number) => ((c % 10) + 10) % 10;
  const o = prog(f, at - 3, 8, S, cubicOut) * (1 - clamp01(out * 1.4));
  return (
    <div style={{ position: "relative", width: w, height: h, overflow: "hidden",
      WebkitMaskImage: "linear-gradient(180deg, transparent 0%, #000 16%, #000 84%, transparent 100%)",
      maskImage: "linear-gradient(180deg, transparent 0%, #000 16%, #000 84%, transparent 100%)", opacity: o }}>
      {/* rolling forward, the next digit comes up from below */}
      {[0, 1].map((d) => (
        <div key={d} style={{ position: "absolute", left: 0, right: 0, height: h, top: (d - frac) * h - bounce,
          display: "flex", alignItems: "center", justifyContent: "center", fontFamily: font, fontWeight: 800, fontSize: size,
          lineHeight: 1, color, ...TABULAR, filter: blur ? `blur(${(blur * 0.6).toFixed(2)}px)` : undefined }}>{digit(base + d)}</div>
      ))}
    </div>
  );
};

/**
 * A big sum said ("Facebook paid $1 billion for Instagram"), low on the calm side over a soft shade (the slim
 * panel over busy footage): the kicker (who, as said), then the figure on reels - each digit on its own reel
 * spinning a few turns and landing, the leftmost first (frames 6-48), a touch of motion blur while they run and a
 * small settle - the currency sign beside them; the scale word under it, tracking in (BILLION); an accent rule
 * drawing on with one light sweep; one line of what it was. Only the sum said; a sum that cannot be set whole
 * draws nothing.
 */
const Money: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, dir, hot, out, ks, panel } = useLook(overlay, accent);
  const value = num(overlay.value);
  const lastReel = 48;
  const sound = useLookSound(value !== null ? [{ name: "count-roll", alt: ["count-tick"], at: 6, until: lastReel - 2, gain_db: -9 },
    { name: "count-final", alt: ["tick"], at: lastReel, gain_db: -7 }] : null);
  if (value === null || value <= 0) return null;
  const prefix = str(overlay.prefix) || "$";
  const suf = str(overlay.suffix).toUpperCase();
  const word = SCALE_WORDS.has(suf) ? suf : "";
  const glued = !word && /^[KMBT%]$/.test(suf) ? suf : "";
  const kicker = str(overlay.label);
  const context = str(overlay.subtitle);
  const dec = decimalsSaid([value]);
  const body = value.toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });
  const U = unitOf(W, H);
  let fSize = capFont(share("moneyFigure"), U, ks, dir.cap);
  const kSize = capFont(share("kicker"), U, ks);
  const wSize = capFont(share("moneyScale"), U, ks);
  const cSize = capFont(share("context"), U, ks);
  const digitW = (s: number) => widthOf("0", GROTESK, s, 800) * 1.02;
  const sepW = (s: number, ch: string) => widthOf(ch, GROTESK, s, 800);
  const signSize = (s: number) => s * 0.56;
  const figW = (s: number) => Array.from(body).reduce((a, ch) => a + (/\d/.test(ch) ? digitW(s) : sepW(s, ch)), 0)
    + widthOf(prefix, GROTESK, signSize(s), 800) + 8 * k + (glued ? sepW(s, glued) : 0);
  while (fSize > 20 && figW(fSize) > 0.5 * W) fSize *= 0.96;
  const ctx = context ? fitLines(context, INTER, 600, cSize, cSize * 0.85, 0.42 * W, 1) : null;
  const wordW = word ? widthOf(word, SUBLINE, wSize, 700, 0.22) : 0;
  const w = Math.max(figW(fSize), kicker ? widthOf(kicker.toUpperCase(), SUBLINE, kSize, 700, 0.2) : 0, wordW, ctx ? ctx.width : 0);
  const h = (kicker ? kSize + 16 * k : 0) + fSize * 1.04 + (word ? wSize + 16 * k : 0) + 20 * k + (ctx ? ctx.size * 1.5 : 0);
  const zone = zoneFor(overlay, panel ? "left-panel" : "lower-left", w, h, W, H) as Zone;
  const r = blockAt(zone, w, h, W, H);
  const right = isRight(zone);
  const align = right ? "right" : "left";
  const xo = 1 - clamp01(out * 1.4);
  const drift = idle(f, 40 * S, dur) * 4 * k;
  const t = f / S;
  // the reels: the leftmost first, each a little longer (and a turn more) than the one before
  const chars = Array.from(body);
  let di = 0;
  const nDigits = chars.filter((c) => /\d/.test(c)).length;
  const figY = kicker ? kSize + 16 * k : 0;
  const ruleP = prog(f, lastReel - 6, 16, S, expoOut) * xo;
  return (
    <AbsoluteFill>
      {sound}
      <Backing panel={panel} dir={dir} rect={r} right={right} p={prog(f, 0, 14, S, cubicOut)} out={out} />
      <div style={{ position: "absolute", left: r.x, top: r.y - drift, width: r.w, height: r.h }}>
        {kicker ? (
          <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: kSize }}>
            <Caps text={kicker} size={kSize} color={dir.id === "doc" ? SOFT_WHITE : hot} at={0} out={out} k={k} align={align} />
          </div>
        ) : null}
        <div style={{ position: "absolute", top: figY, [right ? "right" : "left"]: 0, display: "flex", alignItems: "flex-start",
          transform: `scale(${settle(f, lastReel, S).toFixed(4)})`, transformOrigin: right ? "right bottom" : "left bottom",
          filter: `drop-shadow(0 ${(3 * k).toFixed(1)}px ${(10 * k).toFixed(1)}px rgba(0,0,0,0.5))` } as React.CSSProperties}>
          <div style={{ fontFamily: GROTESK, fontWeight: 800, fontSize: signSize(fSize), lineHeight: 1, color: WHITE,
            marginTop: fSize * 0.1, marginRight: 8 * k, opacity: prog(f, 2, 10, S, cubicOut) * xo,
            transform: `translateY(${((1 - prog(f, 2, 14, S, expoOut)) * 0.3 * fSize).toFixed(2)}px)` }}>{prefix}</div>
          {chars.map((ch, i) => {
            if (!/\d/.test(ch)) {
              return (
                <div key={i} style={{ width: sepW(fSize, ch), height: fSize * 1.04, fontFamily: GROTESK, fontWeight: 800, fontSize: fSize,
                  lineHeight: `${fSize * 1.04}px`, color: WHITE, opacity: prog(f, 10 + i * 2, 10, S, cubicOut) * xo,
                  textAlign: "center" }}>{ch}</div>
              );
            }
            const d = di++;
            const at = 6 + d * 3;
            const len = Math.max(18, lastReel - at - (nDigits - 1 - d) * 3);
            return <Reel key={i} to={Number(ch)} turns={1 + Math.min(2, d)} at={at} len={len} size={fSize} font={GROTESK}
              color={WHITE} k={k} out={out} f={f} S={S} w={digitW(fSize)} />;
          })}
          {glued ? (
            <div style={{ fontFamily: GROTESK, fontWeight: 800, fontSize: fSize, lineHeight: `${fSize * 1.04}px`, color: WHITE,
              opacity: prog(f, lastReel - 8, 10, S, cubicOut) * xo }}>{glued}</div>
          ) : null}
          <span style={{ position: "absolute", inset: 0, overflow: "hidden", mixBlendMode: "screen" }}>
            <Glint p={(t - lastReel - 2) / 22} />
          </span>
        </div>
        {word ? (
          <div style={{ position: "absolute", left: 0, right: 0, top: figY + fSize * 1.04 + 14 * k, height: wSize }}>
            <Caps text={word} size={wSize} color={WHITE} at={24} out={out} k={k} tracking={0.22} align={align} />
          </div>
        ) : null}
        <div style={{ position: "absolute", [right ? "right" : "left"]: 0, top: figY + fSize * 1.04 + (word ? wSize + 16 * k : 0) + 10 * k,
          width: Math.max(80 * k, figW(fSize) * 0.36), height: Math.max(2, 3 * k), borderRadius: 2 * k, background: hot,
          transformOrigin: right ? "right" : "left", transform: `scaleX(${ruleP.toFixed(4)})`, overflow: "hidden",
          boxShadow: `0 0 ${(10 * k).toFixed(1)}px ${rgba(hot, 0.45)}` } as React.CSSProperties}>
          <Glint p={(t - lastReel - 6) / 20} />
        </div>
        {ctx ? (
          <div style={{ position: "absolute", left: 0, right: 0, top: h - ctx.size * 1.3 }}>
            <KineticLine text={ctx.lines[0]} font={INTER} weight={600} size={ctx.size} color={SOFT_WHITE} preset="focus"
              timing={{ at: 34, gap: 2 }} out={out} align={align} shadow={softShadow(k, 0.55)} />
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== kt-table
interface Cell { value: number | null; text: string; prefix: string; suffix: string; at: number | null }
interface TRow { label: string; a: Cell | null; b: Cell | null }
/** The table's rows: an item a cell, the first with a label in the left column, the second with it in the right. */
const tableOf = (ov: Overlay): TRow[] => {
  const rows: TRow[] = [];
  for (const it of Array.isArray(ov.items) ? ov.items : []) {
    const o = (it || {}) as unknown as Record<string, unknown>;
    const label = str(o.label);
    if (!label) continue;
    const cell: Cell = { value: num(o.value), text: str(o.text), prefix: str(o.prefix), suffix: str(o.suffix), at: num(o.at) };
    if (cell.value === null && !cell.text) continue;
    const row = rows.find((x) => x.label.toLowerCase() === label.toLowerCase());
    if (!row) rows.push({ label, a: cell, b: null });
    else if (!row.b) row.b = cell;
  }
  return rows.filter((x) => x.a && x.b).slice(0, 4);
};
const cellOf = (c: Cell) => (c.value !== null ? cellText(c.value, c.prefix, c.suffix) : c.text);

/**
 * Two sides compared on two to four things, as a frosted table on the calm side (home: the right-hand panel):
 * a kicker when one was said (THEN AND NOW), the two sides' names at the heads of their columns (the second when
 * its first figure is said), then a row a thing - its name in small capitals, a hairline drawing across - and
 * each cell rising in ON its word, figures in tabular digits with the unit they were said with.
 */
const Table: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, dir, hot, out, ks } = useLook(overlay, accent);
  const rows = tableOf(overlay);
  const cellsAt = rows.flatMap((x, i) => [saidAt(x.a?.at ?? null, 10 + i * 6), saidAt(x.b?.at ?? null, 30 + i * 6)]);
  const sound = useLookSound(rows.length >= 2 ? [{ name: "ui-swipe", alt: ["swipe", "whoosh-soft"], at: 0, gain_db: -13 },
    ...cellsAt.map((at) => ({ name: "ui-tick", alt: ["tick"], at: Math.round(at + 4), gain_db: -12 }))] : null);
  if (rows.length < 2) return null;
  const heads = str(overlay.text).split(/\s+(?:vs\.?|versus|v\.?)\s+|\s*\|\s*/i).map((x) => x.trim()).filter(Boolean);
  const headA = heads[0] || "", headB = heads[1] || "";
  const kicker = str(overlay.label);
  const U = unitOf(W, H);
  const kSize = capFont(share("kicker"), U, ks);
  let hSize = capFont(share("tableHead"), U, ks);
  let cSize = capFont(share("tableCell"), U, ks);
  const lSize = capFont(share("small"), U, ks);
  const padX = 30 * k, padT = 26 * k, padB = 22 * k, gap = 26 * k;
  const texts = rows.map((x) => [cellOf(x.a as Cell), cellOf(x.b as Cell)]);
  const labelW = Math.max(...rows.map((x) => widthOf(x.label.toUpperCase(), SUBLINE, lSize, 700, 0.12)));
  const colW = (hs: number, cs: number) => Math.max(widthOf(headA, GROTESK, hs, 800), widthOf(headB, GROTESK, hs, 800),
    ...texts.flat().map((s) => widthOf(s, GROTESK, cs, 800)));
  const maxW = cardW("tableCard", W, H) * 1.18;
  while ((padX * 2 + labelW + gap * 2 + colW(hSize, cSize) * 2) > maxW && cSize > capFont(share("tableCell"), U, ks) * 0.7) {
    hSize *= 0.95;
    cSize *= 0.95;
  }
  const cw0 = colW(hSize, cSize);
  const cw = Math.max(cardW("tableCard", W, H), padX * 2 + labelW + gap * 2 + cw0 * 2);
  const valW = (cw - padX * 2 - labelW - gap * 2) / 2;
  const head = (kicker ? kSize + 14 * k : 0) + hSize * 1.3 + 16 * k;
  const rowH = cSize * 2.1;
  const ch = padT + head + rows.length * rowH + padB;
  const zone = zoneFor(overlay, "right-panel", cw, ch, W, H) as Zone;
  const r = blockAt(zone, cw, ch, W, H);
  const open = prog(f, 0, 14, S, expoOut);
  const xo = 1 - clamp01(out * 1.4);
  const drift = idle(f, 50 * S, dur) * 3 * k;
  const aX = padX + labelW + gap, bX = aX + valW + gap;
  const bFirst = Math.min(...rows.map((x, i) => saidAt(x.b?.at ?? null, 30 + i * 6)));
  const headY = padT + (kicker ? kSize + 14 * k : 0);
  return (
    <AbsoluteFill>
      {sound}
      <Frost x={r.x} y={r.y - drift} w={cw} h={ch} k={k} p={open} out={out} right={isRight(zone)} radius={16}>
        {kicker ? (
          <div style={{ position: "absolute", left: padX, top: padT, height: kSize }}>
            <Caps text={kicker} size={kSize} color={dir.id === "doc" ? "rgba(250,250,247,0.86)" : hot} at={3} out={out} k={k} />
          </div>
        ) : null}
        {/* the sides' names */}
        {[{ x: aX, text: headA, at: 6 }, { x: bX, text: headB, at: Math.max(8, bFirst - 6) }].map((hd, i) => (
          <div key={`h${i}`} style={{ position: "absolute", left: hd.x, top: headY, width: valW }}>
            <Masked text={hd.text} font={GROTESK} size={hSize} weight={800} p={prog(f, hd.at, 14, S, expoOut)} x={out} align="right"
              shadow={softShadow(k, 0.4)} />
            <div style={{ height: Math.max(2, 2.5 * k), marginTop: 6 * k, marginLeft: "auto", width: Math.min(valW, 46 * k),
              background: i === 0 ? hot : "rgba(250,250,247,0.75)", borderRadius: 2 * k, transformOrigin: "right",
              transform: `scaleX(${(prog(f, hd.at + 6, 14, S, expoOut) * xo).toFixed(4)})` }} />
          </div>
        ))}
        {/* the rows */}
        {rows.map((row, i) => {
          const y = padT + head + i * rowH;
          const aAt = saidAt(row.a?.at ?? null, 10 + i * 6);
          const bAt = saidAt(row.b?.at ?? null, 30 + i * 6);
          const first = Math.min(aAt, bAt);
          const line = prog(f, Math.max(4, first - 8), 16, S, expoOut) * xo;
          const x = clamp01(out * 1.5 - ((rows.length - 1 - i) / rows.length) * 0.5);
          return (
            <div key={i} style={{ position: "absolute", left: 0, top: y, width: cw, height: rowH }}>
              <div style={{ position: "absolute", left: padX, right: padX, top: 0, height: Math.max(1, 1.2 * k),
                background: "linear-gradient(90deg, rgba(255,255,255,0.18), rgba(255,255,255,0.06))", transformOrigin: "left",
                transform: `scaleX(${line.toFixed(4)})` }} />
              <div style={{ position: "absolute", left: padX, top: (rowH - lSize) / 2 + 2 * k, width: labelW, opacity: line,
                fontFamily: SUBLINE, fontWeight: 700, fontSize: lSize, letterSpacing: "0.12em", color: DIM, textTransform: "uppercase",
                whiteSpace: "nowrap", lineHeight: 1 }}>{row.label}</div>
              {[{ x: aX, at: aAt, text: texts[i][0] }, { x: bX, at: bAt, text: texts[i][1] }].map((c, m) => (
                <div key={m} style={{ position: "absolute", left: c.x, top: (rowH - cSize * 1.22) / 2 + 2 * k, width: valW }}>
                  <Masked text={c.text} font={GROTESK} size={cSize} weight={800} p={prog(f, c.at, 14, S, expoOut)} x={x} align="right"
                    tabular shadow={softShadow(k, 0.4)} />
                </div>
              ))}
            </div>
          );
        })}
        {/* the column rule between the two sides */}
        <div style={{ position: "absolute", left: bX - gap / 2, top: headY, width: Math.max(1, 1.2 * k),
          height: (ch - padB - headY) * prog(f, 4, 22, S, expoOut) * xo, background: "rgba(255,255,255,0.12)" }} />
      </Frost>
    </AbsoluteFill>
  );
};

// ================================================================== kt-proscons
interface PC { label: string; pro: boolean; at: number | null }
const pointsPC = (ov: Overlay): PC[] => (Array.isArray(ov.items) ? ov.items : [])
  .map((it) => ({ label: str(it?.label), pro: (num(it?.value) ?? 1) >= 0, at: num((it as { at?: unknown } | undefined)?.at) }))
  .filter((x) => x.label);

/** A check or a cross drawing on in a small ring. */
const Mark: React.FC<{ pro: boolean; p: number; size: number; color: string; k: number }> = ({ pro, p, size, color, k }) => {
  const s = size;
  const ring = clamp01(p * 1.6);
  const stroke = clamp01(p * 1.6 - 0.5);
  const d = pro ? `M${s * 0.28},${s * 0.52} L${s * 0.44},${s * 0.68} L${s * 0.73},${s * 0.34}`
    : `M${s * 0.33},${s * 0.33} L${s * 0.67},${s * 0.67} M${s * 0.67},${s * 0.33} L${s * 0.33},${s * 0.67}`;
  return (
    <svg width={s} height={s} style={{ overflow: "visible", flex: "none" }}>
      <circle cx={s / 2} cy={s / 2} r={s * 0.46 * (0.6 + 0.4 * ring)} fill={rgba(color, 0.16 * ring)} stroke={rgba(color, 0.85 * ring)}
        strokeWidth={Math.max(1.2, 1.8 * k)} />
      <path d={d} fill="none" stroke={color} strokeWidth={Math.max(2, 2.8 * k)} strokeLinecap="round" strokeLinejoin="round"
        pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - stroke} />
    </svg>
  );
};

/**
 * The upsides and the downsides said, as a frosted card on the calm side (home: the right-hand panel): the topic
 * when one was said, PROS and CONS at the heads of two columns (a check in the accent, a cross in a soft red),
 * a hairline between them drawing down; each point lands ON its word - its mark drawing on in its ring, its words
 * rising - in its own column, up to three a side.
 */
const ProsCons: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, dir, hot, out, ks } = useLook(overlay, accent);
  const all = pointsPC(overlay);
  const pros = all.filter((x) => x.pro).slice(0, 3);
  const cons = all.filter((x) => !x.pro).slice(0, 3);
  const lands = (xs: PC[], base: number) => xs.map((x, i) => saidAt(x.at, base + i * 10));
  const proAt = lands(pros, 10), conAt = lands(cons, 40);
  const sound = useLookSound(pros.length && cons.length ? [{ name: "ui-swipe", alt: ["swipe", "whoosh-soft"], at: 0, gain_db: -13 },
    ...[...proAt, ...conAt].map((at) => ({ name: "ui-tick", alt: ["tick"], at: Math.round(at + 4), gain_db: -11 }))] : null);
  if (!pros.length || !cons.length) return null;
  const title = str(overlay.text);
  const U = unitOf(W, H);
  const kSize = capFont(share("kicker"), U, ks);
  const tSize = capFont(share("prosTitle"), U, ks);
  const hSize = capFont(share("prosHead"), U, ks);
  const iSize0 = capFont(share("prosItem"), U, ks);
  const cw = cardW("prosCard", W, H);
  const padX = 30 * k, padT = 26 * k, padB = 26 * k, gap = 34 * k;
  const colW = (cw - padX * 2 - gap) / 2;
  const markS = iSize0 * 1.35;
  const textW = colW - markS - 14 * k;
  const fits = [...pros, ...cons].map((x) => fitLines(x.label, GROTESK, 600, iSize0, iSize0 * 0.8, textW, 2, -0.005));
  if (fits.some((x) => !x)) return null;
  const iSize = Math.min(...fits.map((x) => (x as { size: number }).size));
  const lineH = iSize * 1.2;
  const itemH = (x: PC) => {
    const fl = fitLines(x.label, GROTESK, 600, iSize, iSize, textW, 2, -0.005);
    return Math.max(markS, (fl ? fl.lines.length : 1) * lineH) + 16 * k;
  };
  const colH = (xs: PC[]) => xs.reduce((a, x) => a + itemH(x), 0);
  const titleFit = title ? fitLines(title, GROTESK, 700, tSize, tSize * 0.8, cw - padX * 2, 1, -0.01) : null;
  const head = (titleFit ? titleFit.size * 1.25 + 14 * k : 0) + hSize + 20 * k;
  const ch = padT + head + Math.max(colH(pros), colH(cons)) + padB - 16 * k;
  const zone = zoneFor(overlay, "right-panel", cw, ch, W, H) as Zone;
  const r = blockAt(zone, cw, ch, W, H);
  const open = prog(f, 0, 14, S, expoOut);
  const xo = 1 - clamp01(out * 1.4);
  const drift = idle(f, 50 * S, dur) * 3 * k;
  const conCol = DOWN_RED;
  const column = (xs: PC[], ats: number[], x0: number, pro: boolean) => {
    let y = padT + head;
    return xs.map((x, i) => {
      const fl = fitLines(x.label, GROTESK, 600, iSize, iSize, textW, 2, -0.005);
      const lines = fl ? fl.lines : [x.label];
      const top = y;
      y += itemH(x);
      const p = prog(f, ats[i], 14, S, expoOut);
      const ex = clamp01(out * 1.5 - ((xs.length - 1 - i) / Math.max(1, xs.length)) * 0.5);
      return (
        <div key={`${pro ? "p" : "c"}${i}`} style={{ position: "absolute", left: x0, top, width: colW, display: "flex", gap: 14 * k,
          opacity: 1 - clamp01(ex * 1.3) }}>
          <Mark pro={pro} p={prog(f, ats[i], 16, S, cubicOut)} size={markS} color={pro ? hot : conCol} k={k} />
          <div style={{ paddingTop: (markS - lineH) / 2 }}>
            {lines.map((ln, li) => (
              <Masked key={li} text={ln} font={GROTESK} size={iSize} weight={600} p={p * prog(f, ats[i] + 2 + li * 3, 14, S, expoOut)}
                x={ex} tracking={-0.005} shadow={softShadow(k, 0.4)} />
            ))}
          </div>
        </div>
      );
    });
  };
  const headY = padT + (titleFit ? titleFit.size * 1.25 + 14 * k : 0);
  return (
    <AbsoluteFill>
      {sound}
      <Frost x={r.x} y={r.y - drift} w={cw} h={ch} k={k} p={open} out={out} right={isRight(zone)} radius={16}>
        {titleFit ? (
          <div style={{ position: "absolute", left: padX, top: padT, width: cw - padX * 2 }}>
            <KineticLine text={titleFit.lines[0]} font={GROTESK} weight={700} size={titleFit.size} color={WHITE} preset="focus"
              timing={{ at: 4, gap: 2 }} out={out} shadow={softShadow(k, 0.45)} />
          </div>
        ) : null}
        {[{ x: padX, text: "Pros", col: dir.id === "doc" ? "rgba(250,250,247,0.86)" : hot, at: 4 },
          { x: padX + colW + gap, text: "Cons", col: rgba(conCol, 0.95), at: 8 }].map((hd, i) => (
          <div key={`h${i}`} style={{ position: "absolute", left: hd.x, top: headY, height: hSize }}>
            <Caps text={hd.text} size={hSize} color={hd.col} at={hd.at} out={out} k={k} tracking={0.22} />
          </div>
        ))}
        <div style={{ position: "absolute", left: padX + colW + gap / 2, top: headY, width: Math.max(1, 1.2 * k),
          height: (ch - padB - headY) * prog(f, 4, 24, S, expoOut) * xo, background: "rgba(255,255,255,0.12)" }} />
        {column(pros, proAt, padX, true)}
        {column(cons, conAt, padX + colW + gap, false)}
      </Frost>
    </AbsoluteFill>
  );
};

// ================================================================== kt-podium
interface Podi { label: string; value: number | null; at: number | null }
const podiumOf = (ov: Overlay): Podi[] => (Array.isArray(ov.items) ? ov.items : [])
  .map((it) => ({ label: str(it?.label), value: num(it?.value), at: num((it as { at?: unknown } | undefined)?.at) }))
  .filter((x) => x.label).slice(0, 3);

/**
 * A top three, as a frosted card on the calm side (home: the right-hand panel): the title as a kicker, then
 * three podium blocks - second, first, third - each rising out of the baseline when its name is said (a small
 * settle), its place's numeral on its face (the winner's in the accent, one light sweep across it as it lands),
 * the name rising above it and the figure under the name when one was said.
 */
const Podium: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, dir, hot, out, ks } = useLook(overlay, accent);
  const rows = podiumOf(overlay);
  const lands = rows.map((x, i) => saidAt(x.at, 12 + i * 14));
  const sound = useLookSound(rows.length === 3 ? [{ name: "ui-swipe", alt: ["swipe", "whoosh-soft"], at: 0, gain_db: -13 },
    ...lands.map((at, i) => ({ name: i === 0 ? "ui-pop" : "ui-tick", alt: ["tick", "pop"], at: Math.round(at + 8),
      gain_db: i === 0 ? -9 : -11 }))] : null);
  if (rows.length !== 3) return null;
  const title = str(overlay.text);
  const prefix = str(overlay.prefix), suffix = str(overlay.suffix);
  const U = unitOf(W, H);
  const kSize = capFont(share("kicker"), U, ks);
  const nSize0 = capFont(share("podiumName"), U, ks);
  const rSize = capFont(share("podiumRank"), U, ks, dir.cap);
  const vSize = capFont(share("podiumValue"), U, ks);
  // (as wide as its title when the title is long: a kicker never wraps)
  const cw = Math.max(cardW("podiumCard", W, H), title ? capsWidth(title, capFont(share("kicker"), unitOf(W, H), ks)) + 56 * k : 0);
  const ch = (PACK4.podiumCard?.h ?? 0.44) * U * (W >= H ? 1 : 1.3);
  const pad = 28 * k, gap = 14 * k;
  const blockW = (cw - pad * 2 - gap * 2) / 3;
  const fits = rows.map((x) => fitLines(x.label, GROTESK, 700, nSize0, nSize0 * 0.72, blockW + gap * 0.8, 2, -0.01));
  const nSize = Math.min(...fits.map((x) => (x ? x.size : nSize0 * 0.72)));
  const zone = zoneFor(overlay, "right-panel", cw, ch, W, H) as Zone;
  const r = blockAt(zone, cw, ch, W, H);
  const open = prog(f, 0, 14, S, expoOut);
  const xo = 1 - clamp01(out * 1.4);
  const drift = idle(f, 50 * S, dur) * 3 * k;
  const t = f / S;
  const baseY = ch - pad;
  const labelsH = nSize * 2.5 + (rows.some((x) => x.value !== null) ? vSize * 1.6 : 0);
  const topY = pad + (title ? kSize + 18 * k : 0) + labelsH;
  const maxH = baseY - topY;
  // the places left to right: second, first, third
  const slots = [1, 0, 2];
  const heights = [1, 0.74, 0.56];
  const valued = rows.every((x) => x.value !== null);
  return (
    <AbsoluteFill>
      {sound}
      <Frost x={r.x} y={r.y - drift} w={cw} h={ch} k={k} p={open} out={out} right={isRight(zone)} radius={16}>
        {title ? (
          <div style={{ position: "absolute", left: pad, top: pad, height: kSize }}>
            <Caps text={title} size={kSize} color={dir.id === "doc" ? "rgba(250,250,247,0.86)" : hot} at={3} out={out} k={k} />
          </div>
        ) : null}
        <div style={{ position: "absolute", left: pad, right: pad, top: baseY, height: Math.max(1, 1.3 * k),
          background: "rgba(255,255,255,0.3)", transformOrigin: "center", transform: `scaleX(${(prog(f, 2, 18, S, expoOut) * xo).toFixed(4)})` }} />
        {slots.map((rank, col) => {
          const row = rows[rank];
          const at = lands[rank];
          const rise = prog(f, at, 16, S, (u) => backOut(u, 1.25));
          const o = prog(f, at, 8, S, cubicOut);
          const bh = maxH * heights[rank];
          const x = pad + col * (blockW + gap);
          const win = rank === 0;
          const ex = clamp01(out * 1.5 - (col / 3) * 0.4);
          const fit = fitLines(row.label, GROTESK, 700, nSize, nSize, blockW + gap * 0.8, 2, -0.01);
          const lines = fit ? fit.lines : [row.label];
          const nameTop = baseY - bh * rise - 12 * k - (valued ? vSize * 1.5 : 0) - lines.length * nSize * 1.18;
          return (
            <React.Fragment key={rank}>
              <div style={{ position: "absolute", left: x, top: baseY - bh * rise, width: blockW, height: bh * rise, opacity: o * (1 - ex),
                borderRadius: `${8 * k}px ${8 * k}px 0 0`, overflow: "hidden",
                background: win ? `linear-gradient(180deg, ${rgba(hot, 0.34)} 0%, rgba(255,255,255,0.06) 100%)`
                  : "linear-gradient(180deg, rgba(255,255,255,0.16) 0%, rgba(255,255,255,0.04) 100%)",
                boxShadow: `inset 0 ${Math.max(1, 1.5 * k).toFixed(1)}px 0 ${win ? rgba(hot, 0.9) : "rgba(255,255,255,0.4)"}` }}>
                <div style={{ position: "absolute", left: 0, right: 0, top: 10 * k, textAlign: "center", fontFamily: GROTESK, fontWeight: 800,
                  fontSize: rSize, lineHeight: 1, color: win ? hot : "rgba(250,250,247,0.82)", ...TABULAR,
                  textShadow: softShadow(k, 0.35), opacity: prog(f, at + 6, 10, S, cubicOut) }}>{rank + 1}</div>
                {win ? <Glint p={(t - at - 14) / 22} /> : null}
              </div>
              <div style={{ position: "absolute", left: x - gap * 0.4, width: blockW + gap * 0.8, top: nameTop, textAlign: "center",
                opacity: 1 - ex }}>
                {lines.map((ln, li) => (
                  <Masked key={li} text={ln} font={GROTESK} size={nSize} weight={700} p={prog(f, at + 4 + li * 3, 14, S, expoOut)}
                    x={ex} align="center" tracking={-0.01} shadow={softShadow(k, 0.45)} />
                ))}
                {valued && row.value !== null ? (
                  <div style={{ marginTop: 4 * k, fontFamily: GROTESK, fontWeight: 700, fontSize: vSize, color: win ? hot : DIM,
                    ...TABULAR, opacity: prog(f, at + 10, 12, S, cubicOut) }}>{cellText(row.value, prefix, suffix)}</div>
                ) : null}
              </div>
            </React.Fragment>
          );
        })}
      </Frost>
    </AbsoluteFill>
  );
};

// ================================================================== kt-versus
interface Side { label: string; value: number | null; at: number | null }
const sidesOf = (ov: Overlay): Side[] => (Array.isArray(ov.items) ? ov.items : [])
  .map((it) => ({ label: str(it?.label), value: num(it?.value), at: num((it as { at?: unknown } | undefined)?.at) }))
  .filter((x) => x.label).slice(0, 2);

/**
 * A head-to-head said ("Argentina beat France 4-2", "365 electoral votes to 173", "50,000 Carthaginians faced
 * 86,000 Romans"), as a scoreboard low in the middle of the frame (up top when a face or lettering sits there):
 * the kicker centred over it (FINAL SCORE), two frosted halves sliding in from their sides ON their names, each
 * name in tracked capitals toward its outer edge and its figure counting up toward the middle, a small VS between
 * them; the winner's figure in the accent with a thin accent line along its half and one light sweep. The event
 * as said under it.
 */
const Versus: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, hot, out, ks } = useLook(overlay, accent);
  const sides = sidesOf(overlay);
  const lands = sides.map((x, i) => saidAt(x.at, 8 + i * 14));
  const countAt = Math.max(...lands, 0) + 8;
  const sound = useLookSound(sides.length === 2 ? [{ name: "ui-swipe", alt: ["swipe", "whoosh-soft"], at: Math.round(lands[0]), gain_db: -12 },
    { name: "ui-swipe", alt: ["swipe", "whoosh-soft"], at: Math.round(lands[1]), gain_db: -14 },
    { name: "count-roll", alt: ["count-tick"], at: Math.round(countAt), until: Math.round(countAt + 22), gain_db: -10 },
    { name: "count-final", alt: ["tick"], at: Math.round(countAt + 24), gain_db: -8 }] : null);
  if (sides.length !== 2 || sides.some((x) => x.value === null)) return null;
  const kicker = str(overlay.label);
  const event = str(overlay.text);
  const win = str(overlay.highlight).toLowerCase();
  const U = unitOf(W, H);
  const kSize = capFont(share("kicker"), U, ks);
  let nSize = capFont(share("versusName"), U, ks);
  let sSize = capFont(share("versusScore"), U, ks);
  const eSize = capFont(share("small"), U, ks) * 1.1;
  const vals = sides.map((x) => x.value as number);
  const dec = decimalsSaid(vals);
  const fmt = (v: number) => v.toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });
  const halfMax = (W >= H ? 0.29 : 0.44) * W;
  // (the padding on both sides, and a clear gap between the name and its score)
  const halfW0 = (s: number, ns: number) => Math.max(...sides.map((x, i) => widthOf(x.label.toUpperCase(), GROTESK, ns, 800, 0.04)
    + widthOf(fmt(vals[i]), GROTESK, s, 800) + 52 * k + 44 * k));
  while (halfW0(sSize, nSize) > halfMax && nSize > capFont(share("versusName"), U, ks) * 0.66) {
    nSize *= 0.95;
    sSize *= 0.96;
  }
  const halfW = Math.max(halfW0(sSize, nSize), 0.2 * W);
  const vsW = 64 * k;
  const barH = sSize * 1.62;
  const w = halfW * 2 + vsW;
  const h = (kicker ? kSize + 16 * k : 0) + barH + (event ? eSize * 2.2 : 0);
  // low in the middle; up top when a face or lettering of the picture sits there
  const x0 = (W - w) / 2;
  let y0 = H - SAFE.bottom * H - h;
  const avoid = Array.isArray(overlay.avoid) ? overlay.avoid : [];
  const hits = (y: number) => avoid.some((b) => b.x * W < x0 + w && (b.x + b.w) * W > x0 && b.y * H < y + h && (b.y + b.h) * H > y);
  if (hits(y0) && !hits(SAFE.top * H)) y0 = SAFE.top * H;
  const xo = 1 - clamp01(out * 1.4);
  const t = f / S;
  const barY = kicker ? kSize + 16 * k : 0;
  const count = prog(f, countAt, 24, S, expoOut);
  return (
    <AbsoluteFill>
      {sound}
      <div style={{ position: "absolute", left: x0, top: y0, width: w, height: h }}>
        {kicker ? (
          <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: kSize }}>
            <Caps text={kicker} size={kSize} color="rgba(250,250,247,0.86)" at={2} out={out} k={k} align="center" />
          </div>
        ) : null}
        {sides.map((sd, i) => {
          const left = i === 0;
          const p = prog(f, lands[i], 16, S, expoOut);
          const isWin = win && sd.label.toLowerCase() === win;
          const col = isWin ? hot : win ? "rgba(250,250,247,0.78)" : WHITE;
          const ex = clamp01(out * 1.3);
          const shift = (1 - p) * (left ? -1 : 1) * 60 * k + cubicIn(ex) * (left ? -1 : 1) * 40 * k;
          const hx = left ? 0 : halfW + vsW;
          const v = vals[i] * count;
          return (
            <div key={i} style={{ position: "absolute", left: hx, top: barY, width: halfW, height: barH, opacity: clamp01(p * 1.5) * (1 - ex),
              transform: `translateX(${shift.toFixed(2)}px)` }}>
              <Frost x={0} y={0} w={halfW} h={barH} k={k} p={p} out={out} right={!left} radius={14}>
                {isWin ? (
                  <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: Math.max(2, 3 * k), background: hot,
                    transformOrigin: left ? "left" : "right", transform: `scaleX(${prog(f, countAt + 20, 16, S, expoOut).toFixed(4)})`,
                    boxShadow: `0 0 ${(10 * k).toFixed(1)}px ${rgba(hot, 0.5)}` }} />
                ) : null}
                <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "space-between",
                  flexDirection: left ? "row" : "row-reverse", padding: `0 ${26 * k}px` }}>
                  <div style={{ fontFamily: GROTESK, fontWeight: 800, fontSize: nSize, letterSpacing: "0.04em", color: WHITE,
                    textTransform: "uppercase", whiteSpace: "nowrap", textShadow: softShadow(k, 0.4),
                    opacity: prog(f, lands[i] + 4, 12, S, cubicOut) }}>{sd.label}</div>
                  <div style={{ position: "relative", fontFamily: GROTESK, fontWeight: 800, fontSize: sSize, lineHeight: 1, color: col,
                    whiteSpace: "nowrap", ...TABULAR, textShadow: softShadow(k, 0.45), opacity: prog(f, countAt - 2, 8, S, cubicOut),
                    transform: `scale(${settle(f, countAt + 22, S).toFixed(4)})` }}>
                    {fmt(count >= 1 ? vals[i] : Number(v.toFixed(dec)))}
                  </div>
                </div>
                {isWin ? <Glint p={(t - countAt - 26) / 22} /> : null}
              </Frost>
            </div>
          );
        })}
        <div style={{ position: "absolute", left: halfW, top: barY, width: vsW, height: barH, display: "flex", alignItems: "center",
          justifyContent: "center", fontFamily: SUBLINE, fontWeight: 700, fontSize: kSize, letterSpacing: "0.16em", color: DIM,
          opacity: prog(f, 4, 10, S, cubicOut) * xo, transform: `scale(${(0.7 + 0.3 * prog(f, 4, 12, S, (u) => backOut(u, 1.6))).toFixed(4)})` }}>VS</div>
        {event ? (
          <div style={{ position: "absolute", left: 0, right: 0, top: barY + barH + eSize * 0.7 }}>
            <KineticLine text={event} font={INTER} weight={600} size={eSize} color={SOFT_WHITE} preset="focus" timing={{ at: 12, gap: 2 }}
              out={out} align="left" style={{ textAlign: "center" }} shadow={softShadow(k, 0.5)} />
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "kt-price": guard(Price),
  "kt-money": guard(Money),
  "kt-table": guard(Table),
  "kt-proscons": guard(ProsCons),
  "kt-podium": guard(Podium),
  "kt-versus": guard(Versus),
};
