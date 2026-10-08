import React from "react";
import { AbsoluteFill } from "remotion";
import type { Overlay } from "../../types";
import { GROTESK, GROTESK_CAP, INTER, SUBLINE } from "../fonts";
import { backOut, clamp01, cubicIn, cubicInOut, cubicOut, expoOut, idle, lerp, prog } from "../motion/ease";
import { guard, mixHex, rgba, useSvgId, type Look } from "./proKit";
import { countText, figureOf, num, str, unitsOf } from "./proFormat";
import { Glint, KineticLine, SOFT_WHITE, WHITE, blockAt, fitLines, isRight, settle, softShadow, widthOf, zoneFor,
  type Zone } from "./typeKit";
import { Backing, useLook } from "./LibKinetic";
import { Caps, DIM, Glass, RiseLine, capsWidth, riseWidth } from "./LibKtDates";
import { useLookSound } from "./LookSounds";
import scale from "./typeScale.json";

/**
 * LOOKS PACK 3 (2026-10-08, the owner: "more animations, better animations ...
 * extra ones that are perfectly quality ones"), the data on the footage, in the
 * kinetic-type system of the kt- looks (typeKit.tsx: white bold grotesk, ONE
 * accent following the brand kit, frosted glass or a soft shade - never an
 * outline, a yellow fill or a poster face; sizes from typeScale.json "pack3"):
 *
 *   kt-ranking    RANKING     three to six names with their values ("Phoenix 2.1 inches, Tucson 1.8 ..."): a
 *                             glass card on the calm side whose rank slots fill as each one is SAID - its name
 *                             rising, its bar growing to scale, its value counting; the leader in the accent
 *   kt-waterline  WATERLINE   a lake's level through the years: a canyon in section, the water falling from one
 *                             year's line to the next as each is said, the pale bathtub ring left on the walls,
 *                             the drop counted in a pill
 *   kt-severity   SCALE       a level on its scale ("Category 4", "EF-3", "D4", "Tier 2", "level 3 of 4"): the
 *                             segments light one by one up to the level, a marker lands on it
 *   kt-delta      CHANGE      "from 1,225 feet to 1,040": the old figure, an arrow drawing to the new one as it
 *                             counts, the change in a pill (or one change "since 2000")
 *   kt-streak     STREAK      "31 straight days above 110": the count rolling while a calendar of day cells
 *                             lights, the last one ringed
 *   kt-alert      ALERT       an official weather alert as said ("a flash flood warning until 9 PM"): a glass
 *                             card top left, a small status dot in the alert's level colour, the name rising
 *
 * Every look: an eased entry of 12-24 frames, each part landing on its own word (items[].at, seconds from the
 * look's start), a gentle idle, every element leaving in the last 12 frames (the mirrored exit). Only the
 * planner's words and figures are drawn (src/lookpack3.py); a look that cannot set them whole draws nothing.
 */

// ------------------------------------------------------------------ shared
/** The size unit: the frame height, or the width's 16:9 height on a tall frame. */
const unitOf = (W: number, H: number) => Math.min(H, (W * 9) / 16);
/** Font px whose capitals stand `sh` of the unit (fontScale applied). */
const capFont = (sh: number, U: number, ks: number, cap = GROTESK_CAP) => (sh * U * ks) / cap;
type P3 = Record<string, { share?: number; w?: number; h?: number }>;
const PACK3 = (scale as unknown as { pack3: P3 }).pack3;
const share = (key: string) => PACK3[key]?.share ?? 0.02;

/** The 30-fps frame a part said `at` seconds into the look starts on (a frame before its word, never earlier). */
const saidAt = (at: number | null, fallback: number) => (at !== null && Number.isFinite(at) && at >= 0
  ? Math.max(2, at * 30 - 1) : fallback);

interface Item { label: string; value: number | null; at: number | null; text: string }
const itemsOf = (ov: Overlay, max = 8): Item[] => (Array.isArray(ov.items) ? ov.items : [])
  .map((it) => ({ label: str(it?.label), value: num(it?.value), at: num((it as { at?: unknown } | undefined)?.at),
    text: str(it?.text) }))
  .filter((x) => x.label || x.value !== null).slice(0, max);

/** A figure as drawn: the digits (partway through a count) and the unit that rides on them. */
const figParts = (v: number, p: number, suffix: unknown, prefix: unknown, from = 0) => {
  const fg = figureOf(v, suffix, prefix);
  return { main: `${fg.prefix}${countText(fg, p, from)}${fg.glued}`, unit: fg.unit, final: `${fg.prefix}${fg.main}${fg.glued}` };
};

/** A stroke drawn `p` 0..1 of its length (round caps, a soft shadow so it holds on any picture). */
const Draw: React.FC<{ d: string; p: number; color: string; width: number; shadow?: number; opacity?: number;
  dash?: string }> = ({ d, p, color, width, shadow = 0.5, opacity = 1, dash }) => (p <= 0.001 ? null : (
    <path d={d} pathLength={dash ? undefined : 1} fill="none" stroke={color} strokeWidth={width} strokeLinecap="round"
      strokeLinejoin="round" strokeDasharray={dash || "1 1"} strokeDashoffset={dash ? undefined : 1 - clamp01(p)}
      opacity={opacity * (dash ? clamp01(p) : 1)}
      style={shadow > 0 ? { filter: `drop-shadow(0 ${(width * 0.35).toFixed(2)}px ${(width * 1.1).toFixed(2)}px rgba(0,0,0,${shadow}))` }
        : undefined} />
  ));

/** A small solid triangle pointing down (▼) or up (▲) at (x, y) - its tip on the point. */
const tri = (x: number, y: number, s: number, down: boolean) => (down
  ? `M${x.toFixed(1)},${(y).toFixed(1)} L${(x - s).toFixed(1)},${(y - s * 1.5).toFixed(1)} L${(x + s).toFixed(1)},${(y - s * 1.5).toFixed(1)} Z`
  : `M${x.toFixed(1)},${(y).toFixed(1)} L${(x - s).toFixed(1)},${(y + s * 1.5).toFixed(1)} L${(x + s).toFixed(1)},${(y + s * 1.5).toFixed(1)} Z`);

/** Words that rise out of a mask (one line), leaving by sinking back into it. */
const Masked: React.FC<{ text: string; font: string; size: number; weight: number; color?: string; p: number; x?: number;
  tracking?: number; upper?: boolean; align?: "left" | "right"; tabular?: boolean; shadow?: string }> =
  ({ text, font, size, weight, color = WHITE, p, x = 0, tracking = -0.01, upper = false, align = "left", tabular = false,
    shadow }) => (
    <div style={{ overflow: "hidden", height: size * 1.22, paddingTop: size * 0.06, marginTop: -size * 0.06 }}>
      <div style={{ fontFamily: font, fontWeight: weight, fontSize: size, lineHeight: 1.12, color, whiteSpace: "nowrap",
        letterSpacing: `${tracking}em`, textTransform: upper ? "uppercase" : undefined, textAlign: align,
        fontVariantNumeric: tabular ? "tabular-nums" : undefined, fontFeatureSettings: tabular ? '"tnum" 1' : undefined,
        textShadow: shadow, opacity: clamp01(p * 3) * (1 - clamp01(x * 1.6)),
        transform: `translateY(${((1 - clamp01(p)) * 104 + cubicIn(clamp01(x)) * 104).toFixed(2)}%)` }}>{text}</div>
    </div>
  );

// ================================================================== kt-ranking
/**
 * Three to six names with their values (or a ranked list of names), as a frosted card on the calm side
 * (home: the right-hand panel, vertically centred; mirrored off faces and lettering): the title and its unit,
 * then one rank slot per row - the numerals faint from the start - and each row arriving in ITS slot when it is
 * said (items[].at): the name rising out of a mask, its bar growing to scale (expo-out, 22 frames) while its
 * value counts. Once the last one is said, the leader takes the accent: its numeral and its bar, one light
 * sweep along it. The rows leave bottom first; the card closes into its side.
 */
const Ranking: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, dir, hot, out, ks } = useLook(overlay, accent);
  const rows = itemsOf(overlay, 6).filter((r) => r.label);
  const n = rows.length;
  const lands = rows.map((r, i) => saidAt(r.at, 10 + i * 5));
  const sound = useLookSound(n >= 3 ? [{ name: "ui-swipe", alt: ["swipe", "whoosh-soft"], at: 0, gain_db: -13 },
    ...lands.map((at) => ({ name: "ui-tick", alt: ["tick", "count-tick"], at: Math.round(at + 6), gain_db: -10 }))] : null);
  if (n < 3) return null;
  const valued = rows.every((r) => r.value !== null && (r.value as number) >= 0) && rows.some((r) => (r.value as number) > 0);
  const { suffix, prefix } = unitsOf(rows.map((r) => ({ label: r.label, value: r.value ?? 0, suffix: "", prefix: "", text: "" })),
    overlay.suffix, overlay.prefix);
  const title = str(overlay.text) || str(overlay.label);
  const unitLine = str(overlay.subtitle);
  const U = unitOf(W, H);
  const kSize = capFont(share("kicker"), U, ks);
  const uSize = capFont(share("small"), U, ks);
  const rSize = capFont(share("rankNumber"), U, ks);
  const vSize = capFont(share("rankValue"), U, ks);
  let nSize = capFont(share("rankName"), U, ks);
  const nameMax = 0.17 * W;
  const widest = (s: number) => Math.max(...rows.map((r) => widthOf(r.label, GROTESK, s, 700, -0.005)));
  while (nSize > capFont(share("rankName"), U, ks) * 0.8 && widest(nSize) > nameMax) nSize *= 0.96;
  const nameW = Math.min(nameMax * 1.15, widest(nSize));
  const unitOfFig = valued ? figureOf(rows[0].value as number, suffix, prefix).unit : "";
  const unitBeside = unitOfFig.length > 0 && unitOfFig.length <= 4;
  const uvSize = vSize * 0.56;
  const valueW = valued ? Math.max(...rows.map((r) => widthOf(figParts(r.value as number, 1, suffix, prefix).final, GROTESK, vSize, 800)))
    + (unitBeside ? 7 * k + widthOf(unitOfFig, SUBLINE, uvSize, 700, 0.08) : 0) : 0;
  const padX = 30 * k, padT = 26 * k, padB = 22 * k, gap = 20 * k;
  const rankW = widthOf(String(n), GROTESK, rSize, 800) + 22 * k;
  const barMin = 0.09 * W;
  const fixed = padX * 2 + rankW + nameW + (valued ? gap * 2 + valueW : 0);
  const cardW0 = (PACK3.rankCard?.w ?? 0.36) * W;
  const barW = valued ? Math.max(barMin, cardW0 - fixed) : 0;
  const cw = Math.max(fixed + barW, 0.2 * W, title ? capsWidth(title, kSize) + padX * 2 : 0);
  const head = (title ? kSize + 10 * k : 0) + (unitLine ? uSize + 8 * k : 0) + (title || unitLine ? 16 * k : 0);
  const rowH = Math.max(nSize, vSize) * 2.05;
  const ch = padT + head + n * rowH + padB;
  const zone = zoneFor(overlay, "right-panel", cw, ch, W, H) as Zone;
  const r = blockAt(zone, cw, ch, W, H);
  const open = prog(f, 0, 14, S, expoOut);
  const drift = idle(f, 40 * S, dur) * 4 * k;
  const maxV = valued ? Math.max(...rows.map((x) => x.value as number)) : 1;
  const lastLand = Math.max(...lands);
  const lead = prog(f, lastLand + 16, 14, S, cubicOut) * (1 - clamp01(out * 1.4));
  const t = f / S;
  const barH = Math.max(6, 0.44 * vSize);
  return (
    <AbsoluteFill>
      {sound}
      <Glass x={r.x} y={r.y - drift} w={cw} h={ch} k={k} p={open} out={out} right={isRight(zone)} radius={16}>
        <div style={{ position: "absolute", left: padX, top: padT, right: padX }}>
          {title ? (
            <div style={{ height: kSize, marginBottom: 10 * k }}>
              <Caps text={title} size={kSize} color={dir.id === "doc" ? "rgba(250,250,247,0.86)" : hot} at={4} out={out} k={k} />
            </div>
          ) : null}
          {unitLine ? (
            <div style={{ height: uSize }}>
              <Caps text={unitLine} size={uSize} color={DIM} at={8} out={out} k={k} tracking={0.14} weight={600} />
            </div>
          ) : null}
        </div>
        {rows.map((row, i) => {
          const y = padT + head + i * rowH;
          const x = clamp01(out * 1.5 - ((n - 1 - i) / n) * 0.5);
          const slot = prog(f, 6 + i * 2, 12, S, cubicOut) * (1 - clamp01(out * 1.4));
          const a = prog(f, lands[i], 14, S, expoOut);
          const grow = prog(f, lands[i] + 2, 22, S, expoOut);
          const lit = t >= lands[i];
          const leader = i === 0;
          const numColor = leader && lead > 0 ? mixHex("#FAFAF7", hot.startsWith("#") ? hot : "#F2B544", lead)
            : lit ? WHITE : "rgba(250,250,247,0.34)";
          const fp = valued ? figParts(row.value as number, grow, suffix, prefix) : null;
          const fillW = valued ? barW * clamp01((row.value as number) / Math.max(1e-9, maxV)) * grow : 0;
          return (
            <div key={i} style={{ position: "absolute", left: padX, top: y, width: cw - padX * 2, height: rowH, display: "flex",
              alignItems: "center", opacity: 1 - clamp01(x * 1.2), transform: `translateY(${(cubicIn(clamp01(x)) * 10 * k).toFixed(2)}px)` }}>
              <div style={{ width: rankW, flex: "none", opacity: slot, fontFamily: GROTESK, fontWeight: 800, fontSize: rSize,
                lineHeight: 1, color: numColor, fontVariantNumeric: "tabular-nums", fontFeatureSettings: '"tnum" 1',
                textShadow: softShadow(k, 0.4) }}>{i + 1}</div>
              <div style={{ width: nameW, flex: "none" }}>
                <Masked text={row.label} font={GROTESK} size={nSize} weight={700} p={a}
                  color={!lead || leader ? WHITE : `rgba(250,250,247,${(1 - 0.16 * lead).toFixed(3)})`} shadow={softShadow(k, 0.45)} />
              </div>
              {valued ? (
                <>
                  <div style={{ position: "relative", width: barW, height: barH, marginLeft: gap, flex: "none",
                    borderRadius: barH, background: `rgba(255,255,255,${(0.07 * slot).toFixed(3)})`, overflow: "hidden" }}>
                    <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: fillW, borderRadius: barH,
                      background: leader && lead > 0
                        ? `linear-gradient(90deg, ${rgba(hot, 0.75 + 0.25 * lead)}, ${rgba(hot, 1)})`
                        : "linear-gradient(90deg, rgba(250,250,247,0.62), rgba(250,250,247,0.92))",
                      boxShadow: leader && lead > 0 ? `0 0 ${(12 * k).toFixed(1)}px ${rgba(hot, 0.5 * lead)}` : undefined }}>
                      {leader ? <Glint p={(t - lastLand - 22) / 22} /> : null}
                    </div>
                  </div>
                  <div style={{ marginLeft: gap, width: valueW, flex: "none", display: "flex", alignItems: "baseline",
                    justifyContent: "flex-end", gap: 7 * k, opacity: clamp01(a * 2) }}>
                    <span style={{ fontFamily: GROTESK, fontWeight: 800, fontSize: vSize, lineHeight: 1, color: WHITE,
                      fontVariantNumeric: "tabular-nums", fontFeatureSettings: '"tnum" 1', whiteSpace: "nowrap",
                      textShadow: softShadow(k, 0.45) }}>{fp ? fp.main : ""}</span>
                    {unitBeside ? (
                      <span style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: uvSize, letterSpacing: "0.08em", color: DIM,
                        whiteSpace: "nowrap" }}>{unitOfFig}</span>
                    ) : null}
                  </div>
                </>
              ) : null}
            </div>
          );
        })}
      </Glass>
    </AbsoluteFill>
  );
};

// ================================================================== kt-waterline
/** A canyon's walls in section (shares of the section box): left wall down to the floor, right wall back up. */
const WALL_L: [number, number][] = [[0, 0], [0.075, 0.15], [0.125, 0.17], [0.175, 0.37], [0.225, 0.4], [0.275, 0.61],
  [0.345, 0.77], [0.42, 0.89], [0.5, 0.93]];
const WALL_R: [number, number][] = [[0.5, 0.93], [0.6, 0.88], [0.665, 0.74], [0.715, 0.71], [0.765, 0.5], [0.815, 0.47],
  [0.875, 0.24], [0.925, 0.21], [1, 0]];
/** Where a wall stands at depth v (0 top .. 1 floor): its x share, by straight runs between its points. */
const wallAt = (wall: [number, number][], v: number): number => {
  const pts = wall[0][1] <= wall[wall.length - 1][1] ? wall : [...wall].reverse();
  if (v <= pts[0][1]) return pts[0][0];
  for (let i = 1; i < pts.length; i++) {
    if (pts[i][1] >= v) {
      const a = pts[i - 1], b = pts[i];
      return lerp(a[0], b[0], (v - a[1]) / Math.max(1e-6, b[1] - a[1]));
    }
  }
  return pts[pts.length - 1][0];
};

/**
 * A lake's level through the years (items: each year with its level, said one after another; or the years
 * alone with the drop in `value`), as a frosted card on the calm side: the lake's name and its unit, a canyon in
 * section drawing itself on, the water rising to the first year's level, then falling to each next year's
 * level as it is said (30 frames, ease in-out) - every level it leaves stays as a dashed line with its year, and
 * the pale bathtub ring stays on the walls above the water. When the last level has landed the drop counts in
 * a pill under the years (▼ 185 FT).
 */
const Waterline: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, dir, hot, out, ks } = useLook(overlay, accent);
  const clipId = useSvgId("ktwlclip");
  const rockId = useSvgId("ktwlrock");
  const waterId = useSvgId("ktwlwater");
  const items = itemsOf(overlay, 4).filter((x) => x.label);
  const absolute = items.length >= 2 && items.every((x) => x.value !== null);
  const drop = num(overlay.value);
  const relative = !absolute && items.length >= 2 && drop !== null && drop !== 0;
  const n = items.length;
  const lands = items.map((x, i) => (i === 0 ? 14 : saidAt(x.at, 44 + (i - 1) * 34)));
  for (let i = 1; i < n; i++) lands[i] = Math.max(lands[i], lands[i - 1] + 30);
  const sound = useLookSound(n >= 2 ? [{ name: "ui-swipe", alt: ["swipe", "whoosh-soft"], at: 0, gain_db: -13 },
    ...lands.slice(1).map((at) => ({ name: "whoosh-soft", alt: ["whoosh-soft-v2"], at: Math.round(at + 2), gain_db: -15 })),
    { name: "ui-tick", alt: ["tick"], at: Math.round(lands[n - 1] + 34), gain_db: -9 }] : null);
  if (n < 2 || !(absolute || relative)) return null;
  const { suffix, prefix } = unitsOf(items.map((x) => ({ label: x.label, value: x.value ?? 0, suffix: "", prefix: "", text: "" })),
    overlay.suffix, overlay.prefix);
  const title = str(overlay.text);
  const unitLine = str(overlay.subtitle);
  const U = unitOf(W, H);
  const kSize = capFont(share("kicker"), U, ks);
  const uSize = capFont(share("small"), U, ks);
  const lSize = capFont(share("waterLabel"), U, ks);
  const vSize = capFont(share("waterValue"), U, ks);
  const pSize = capFont(share("deltaPill"), U, ks);
  // the levels: shares of the section's depth (the highest at 0.14, the lowest at 0.78)
  const vals = absolute ? items.map((x) => x.value as number) : items.map((_x, i) => -(i / (n - 1)) * Math.abs(drop as number));
  const hi = Math.max(...vals), lo = Math.min(...vals);
  const depthOf = (v: number) => (hi - lo < 1e-9 ? 0.4 : 0.14 + ((hi - v) / (hi - lo)) * 0.64);
  const vs = vals.map(depthOf);
  const change = absolute ? vals[n - 1] - vals[0] : (vals[n - 1] - vals[0]);
  const down = change < 0;
  const changeAbs = Math.abs(absolute ? change : (drop as number));
  const labelOf = (i: number) => (absolute ? figParts(vals[i], 1, suffix, prefix) : null);
  const valTexts = items.map((_x, i) => {
    const fp = labelOf(i);
    return fp ? `${fp.final}${fp.unit ? ` ${fp.unit}` : ""}` : "";
  });
  const colW = Math.max(...items.map((x, i) => Math.max(riseWidth(x.label.toUpperCase(), GROTESK, lSize, 800, 0.01),
    valTexts[i] ? widthOf(valTexts[i], GROTESK, vSize, 600, 0.02) : 0))) + 26 * k;
  const pad = 28 * k;
  const head = (title ? kSize + 10 * k : 0) + (unitLine ? uSize + 8 * k : 0) + (title || unitLine ? 22 * k : 0);
  const cw = Math.max((PACK3.waterCard?.w ?? 0.38) * W, colW + 0.22 * W + pad * 2);
  const ch = (PACK3.waterCard?.h ?? 0.46) * U;
  const secX = pad, secY = pad + head, secW = cw - pad * 2 - colW - 34 * k, secH = ch - pad - secY - pSize * 2.4;
  const zone = zoneFor(overlay, "right-panel", cw, ch, W, H) as Zone;
  const r = blockAt(zone, cw, ch, W, H);
  const open = prog(f, 0, 14, S, expoOut);
  const xo = 1 - clamp01(out * 1.4);
  const drift = idle(f, 50 * S, dur) * 3 * k;
  const t = f / S;
  // the surface: rises to the first level, then steps down to each next one on its word
  const rise = prog(f, lands[0], 20, S, cubicOut);
  let surf = lerp(1.02, vs[0], rise);
  for (let i = 1; i < n; i++) {
    const p = prog(f, lands[i], 30, S, cubicInOut);
    if (p > 0) surf = lerp(vs[i - 1], vs[i], p);
  }
  const P = (u: number, v: number): [number, number] => [secX + u * secW, secY + v * secH];
  const ptsD = (pts: [number, number][]) => pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const walls = [...WALL_L, ...WALL_R.slice(1)].map(([u, v]) => P(u, v));
  const interior = `${ptsD(walls)} Z`;
  const rock = `${ptsD([P(0, 0), ...walls, P(1, 0), P(1, 1.04), P(0, 1.04)])} Z`;
  const outline = ptsD(walls);
  const draw = prog(f, 3, 24, S, cubicInOut) * xo;
  const sy = secY + surf * secH;
  // a gentle surface: two slow sines, swelling a little while the water moves
  const moving = n > 1 && lands.slice(1).some((a) => t > a && t < a + 30);
  const amp = (1.4 + (moving ? 1.8 : 0)) * k;
  const wave = Array.from({ length: 33 }, (_v, i) => {
    const u = i / 32;
    const x = secX + u * secW;
    return [x, sy + Math.sin(u * Math.PI * 4.2 + t * 0.09) * amp + Math.sin(u * Math.PI * 1.7 - t * 0.06) * amp * 0.6] as [number, number];
  });
  // the bathtub ring: once the water has started down from a level, the walls above it stay pale
  const left = vs.filter((_v, i) => i >= 1 && t >= lands[i]).length;
  const ringTop = left > 0 ? secY + Math.min(...vs.slice(0, left)) * secH : Infinity;
  // the years' labels at their lines, spread apart when two levels sit close
  const labelH = lSize * 1.22 + (absolute ? vSize * 1.2 : 0) + 6 * k;
  const labelY: number[] = vs.map((v) => secY + v * secH - lSize * 0.72);
  const order = labelY.map((y, i) => [y, i] as [number, number]).sort((a, b) => a[0] - b[0]);
  for (let j = 1; j < order.length; j++) {
    const need = order[j - 1][0] + labelH;
    if (order[j][0] < need) order[j][0] = need;
  }
  const overflow = order.length ? order[order.length - 1][0] + labelH - (secY + secH + pSize * 0.5) : 0;
  order.forEach(([y, i]) => { labelY[i] = y - Math.max(0, overflow); });
  const lastLand = lands[n - 1] + (n > 1 ? 30 : 20);
  const pill = prog(f, lastLand + 4, 14, S, (u) => backOut(u, 1.5)) * xo;
  const pillCount = prog(f, lastLand + 4, 24, S, expoOut);
  const pillFig = figParts(changeAbs, pillCount, suffix, prefix);
  const pillText = `${pillFig.main}${pillFig.unit ? ` ${pillFig.unit}` : ""}`;
  const strata = [0.12, 0.27, 0.43, 0.58, 0.72, 0.86];
  return (
    <AbsoluteFill>
      {sound}
      <Glass x={r.x} y={r.y - drift} w={cw} h={ch} k={k} p={open} out={out} right={isRight(zone)} radius={16}>
        <div style={{ position: "absolute", left: pad, top: pad, right: pad }}>
          {title ? (
            <div style={{ height: kSize, marginBottom: 10 * k }}>
              <Caps text={title} size={kSize} color={dir.id === "doc" ? "rgba(250,250,247,0.86)" : hot} at={4} out={out} k={k} />
            </div>
          ) : null}
          {unitLine ? (
            <div style={{ height: uSize }}>
              <Caps text={unitLine} size={uSize} color={DIM} at={8} out={out} k={k} tracking={0.14} weight={600} />
            </div>
          ) : null}
        </div>
        <svg width={cw} height={ch} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          <defs>
            <clipPath id={clipId}><path d={interior} /></clipPath>
            <clipPath id={rockId}><path d={rock} /></clipPath>
            <linearGradient id={`${rockId}g`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="rgba(66,58,51,0.9)" />
              <stop offset="100%" stopColor="rgba(36,32,29,0.94)" />
            </linearGradient>
            <linearGradient id={waterId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="rgba(196,226,248,0.92)" />
              <stop offset="16%" stopColor="rgba(120,178,224,0.82)" />
              <stop offset="100%" stopColor="rgba(34,84,138,0.9)" />
            </linearGradient>
          </defs>
          {/* the rock either side, in strata */}
          <g clipPath={`url(#${rockId})`} opacity={prog(f, 6, 18, S, cubicOut) * xo}>
            <rect x={secX - 2} y={secY} width={secW + 4} height={secH * 1.05} fill={`url(#${rockId}g)`} />
            {strata.map((v, i) => (
              <path key={i} d={ptsD(Array.from({ length: 13 }, (_q, j) => [secX + (j / 12) * secW,
                secY + (v + Math.sin(j * 1.3 + i) * 0.006) * secH] as [number, number]))}
              stroke="rgba(255,240,225,0.11)" strokeWidth={Math.max(1, 1.2 * k)} fill="none" />
            ))}
          </g>
          <g clipPath={`url(#${clipId})`}>
            {/* the open canyon, a shade darker than the glass */}
            <rect x={secX} y={secY} width={secW} height={secH * 1.05} fill="rgba(6,8,12,0.5)" opacity={prog(f, 6, 18, S, cubicOut) * xo} />
            {/* the bathtub ring: the walls the water has left, pale where it stood */}
            {ringTop < sy - 1 ? (
              <>
                <defs>
                  <clipPath id={`${clipId}r`}><rect x={secX - 4} y={ringTop} width={secW + 8} height={Math.max(0, sy - ringTop)} /></clipPath>
                </defs>
                <path d={outline} fill="none" stroke="rgba(244,238,226,0.86)" strokeWidth={Math.max(6, 14 * k)} clipPath={`url(#${clipId}r)`}
                  opacity={xo} />
              </>
            ) : null}
            {surf < 1.01 ? (
              <>
                <path d={`${ptsD(wave)} L${secX + secW},${secY + secH * 1.05} L${secX},${secY + secH * 1.05} Z`} fill={`url(#${waterId})`}
                  opacity={xo} />
                <path d={ptsD(wave)} fill="none" stroke="rgba(255,255,255,0.85)" strokeWidth={Math.max(1, 1.8 * k)} opacity={xo} />
              </>
            ) : null}
          </g>
          {/* the canyon's walls drawing on */}
          <Draw d={outline} p={draw} color="rgba(255,255,255,0.78)" width={Math.max(1.5, 2.2 * k)} shadow={0.35} />
          {/* each year's line, left where the water stood, with its year and level */}
          {items.map((it, i) => {
            const shown = i === 0 ? prog(f, lands[0] + 14, 12, S, cubicOut) : prog(f, lands[i] + 22, 12, S, cubicOut);
            if (shown <= 0.001) return null;
            const v = vs[i];
            const y = secY + v * secH;
            const x0 = secX + wallAt(WALL_L, v) * secW, x1 = secX + wallAt(WALL_R, v) * secW;
            const current = i === n - 1 || t < lands[i + 1];
            const col = current ? "rgba(255,255,255,0.95)" : "rgba(255,255,255,0.5)";
            const lx = cw - pad - colW + 14 * k;
            const ly = labelY[i] + lSize * 0.62;
            const lead = `M${(x1 + 4 * k).toFixed(1)},${y.toFixed(1)} L${(lx - 22 * k).toFixed(1)},${y.toFixed(1)} `
              + `L${(lx - 10 * k).toFixed(1)},${ly.toFixed(1)}`;
            return (
              <g key={i} opacity={shown * xo}>
                <line x1={x0} x2={x1} y1={y} y2={y} stroke={col} strokeWidth={Math.max(1, 1.6 * k)}
                  strokeDasharray={`${6 * k} ${5 * k}`} />
                <path d={lead} fill="none" stroke="rgba(255,255,255,0.3)" strokeWidth={Math.max(1, k)}
                  strokeDasharray={`${2 * k} ${4 * k}`} />
                {current ? <circle cx={lx - 10 * k} cy={ly} r={4 * k} fill={hot} /> : null}
              </g>
            );
          })}
        </svg>
        {/* the years and their levels, at their lines */}
        {items.map((it, i) => {
          const shown = i === 0 ? prog(f, lands[0] + 14, 14, S, expoOut) : prog(f, lands[i] + 22, 14, S, expoOut);
          const current = i === n - 1 || t < lands[i + 1];
          const x = cw - pad - colW + 14 * k;
          return (
            <div key={i} style={{ position: "absolute", left: x, top: labelY[i], opacity: xo }}>
              <Masked text={it.label.toUpperCase()} font={GROTESK} size={lSize} weight={800} p={shown} tracking={0.01}
                color={current ? WHITE : "rgba(250,250,247,0.62)"} shadow={softShadow(k, 0.4)} />
              {valTexts[i] ? (
                <div style={{ fontFamily: GROTESK, fontWeight: 600, fontSize: vSize, lineHeight: 1.1, letterSpacing: "0.02em",
                  color: current ? SOFT_WHITE : "rgba(250,250,247,0.5)", whiteSpace: "nowrap", opacity: clamp01(shown * 1.3),
                  fontVariantNumeric: "tabular-nums", fontFeatureSettings: '"tnum" 1', marginTop: 2 * k }}>{valTexts[i]}</div>
              ) : null}
            </div>
          );
        })}
        {/* the drop, counted, once the last level has landed */}
        {pill > 0.001 ? (
          <div style={{ position: "absolute", left: secX + secW * 0.5, top: secY + secH + pSize * 0.75,
            transform: `translateX(-50%) scale(${(0.86 + 0.14 * pill).toFixed(4)})`, opacity: clamp01(pill * 1.4),
            display: "flex", alignItems: "center", gap: 8 * k, padding: `${5 * k}px ${13 * k}px`, borderRadius: pSize,
            background: "rgba(8,10,14,0.66)", boxShadow: `inset 0 0 0 ${Math.max(1, k).toFixed(1)}px ${rgba(hot, 0.7)}`,
            whiteSpace: "nowrap" }}>
            <svg width={pSize * 0.8} height={pSize * 0.8} style={{ overflow: "visible" }}>
              <path d={tri(pSize * 0.4, down ? pSize * 0.8 : 0, pSize * 0.32, down)} fill={hot} />
            </svg>
            <span style={{ fontFamily: GROTESK, fontWeight: 800, fontSize: pSize, lineHeight: 1, color: WHITE,
              fontVariantNumeric: "tabular-nums", fontFeatureSettings: '"tnum" 1' }}>{pillText}</span>
          </div>
        ) : null}
      </Glass>
    </AbsoluteFill>
  );
};

// ================================================================== kt-severity
/**
 * A level on its scale as said ("a Category 4 hurricane", "an EF-3 tornado", "D4, exceptional drought", "a
 * Tier 2 shortage", "level 3 of 4"), as a frosted card low on the calm side: the scale's name as a kicker, the
 * level in the bold grotesk rising letter by letter, what it means in one line, and the scale - one segment a
 * level, each labelled - whose segments light one after another up to the level (a soft tick each), the lit
 * ones from soft white toward the accent, the level's own in the accent with a marker landing over it and one
 * light sweep across.
 */
const Severity: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, dir, hot, out, ks } = useLook(overlay, accent);
  const total = Math.round(num(overlay.total) ?? 5);
  const level = Math.round(num(overlay.value) ?? 0);
  const ok = total >= 2 && total <= 8 && level >= 1 && level <= total;
  const lightAt = (i: number) => 18 + i * 5;
  const landF = lightAt(Math.max(0, level - 1)) + 6;
  const sound = useLookSound(ok ? [{ name: "ui-swipe", alt: ["swipe", "whoosh-soft"], at: 0, gain_db: -13 },
    ...Array.from({ length: Math.max(0, level - 1) }, (_v, i) => ({ name: "ui-tick", alt: ["tick"], at: lightAt(i) + 2,
      gain_db: -13 + i })),
    { name: "ui-pop", alt: ["pop", "ui-tick"], at: landF, gain_db: -8 }] : null);
  const text = str(overlay.text);
  if (!ok || !text) return null;
  const kicker = str(overlay.label);
  const sub = str(overlay.subtitle);
  const given = Array.isArray(overlay.items) ? overlay.items.map((it) => str(it?.label)) : [];
  const labels = given.length === total && given.every(Boolean) ? given : Array.from({ length: total }, (_v, i) => String(i + 1));
  const U = unitOf(W, H);
  const kSize = capFont(share("kicker"), U, ks);
  const tSize0 = capFont(share("scaleLevel"), U, ks, dir.cap);
  const sSize = capFont(share("scaleName"), U, ks);
  const lbSize = capFont(share("small"), U, ks);
  const padX = 30 * k, padT = 24 * k, padB = 24 * k;
  const segH = Math.max(12, 0.72 * lbSize);
  const segGap = 7 * k;
  let tSize = tSize0;
  const maxInner = (PACK3.scaleCard?.w ?? 0.34) * W * 1.25;
  while (tSize > tSize0 * 0.72 && riseWidth(text, GROTESK, tSize, 800, -0.012) > maxInner) tSize *= 0.96;
  const subFit = sub ? fitLines(sub, INTER, 500, sSize, sSize * 0.86, maxInner, 1) : null;
  const labelW = Math.max(...labels.map((l) => widthOf(l.toUpperCase(), SUBLINE, lbSize, 700, 0.06)));
  const innerW = Math.max((PACK3.scaleCard?.w ?? 0.34) * W - padX * 2, riseWidth(text, GROTESK, tSize, 800, -0.012),
    subFit ? subFit.width : 0, kicker ? capsWidth(kicker, kSize) : 0, total * (labelW + 10 * k));
  const segW = (innerW - segGap * (total - 1)) / total;
  const markerRow = 18 * k;
  const head = (kicker ? kSize + 14 * k : 0) + tSize * 1.2 + (subFit ? subFit.size * 1.5 : 0) + 18 * k;
  const w = innerW + padX * 2;
  const h = padT + head + markerRow + segH + 10 * k + lbSize * 1.3 + padB;
  const zone = zoneFor(overlay, "lower-left", w, h, W, H) as Zone;
  const r = blockAt(zone, w, h, W, H);
  const open = prog(f, 0, 14, S, expoOut);
  const xo = 1 - clamp01(out * 1.4);
  const drift = idle(f, 40 * S, dur) * 4 * k;
  const t = f / S;
  const segY = padT + head + markerRow;
  const segX = (i: number) => padX + i * (segW + segGap);
  const lit = (i: number) => (i < level ? clamp01((t - lightAt(i)) / 5) : 0);
  const rampOf = (i: number) => (level <= 1 ? hot : mixHex("#F4F2EC", hot.startsWith("#") ? hot : "#F2B544", Math.pow(i / Math.max(1, level - 1), 1.4)));
  const mark = prog(f, landF, 12, S, (u) => backOut(u, 1.7)) * xo;
  const mx = segX(level - 1) + segW / 2;
  const breathe = t > landF + 10 ? 0.5 + 0.5 * Math.sin((t - landF - 10) / 14) : 0;
  return (
    <AbsoluteFill>
      {sound}
      <Glass x={r.x} y={r.y - drift} w={w} h={h} k={k} p={open} out={out} right={isRight(zone)} radius={14}>
        <div style={{ position: "absolute", left: padX, top: padT, width: innerW }}>
          {kicker ? (
            <div style={{ height: kSize, marginBottom: 14 * k }}>
              <Caps text={kicker} size={kSize} color={dir.id === "doc" ? "rgba(250,250,247,0.86)" : hot} at={4} out={out} k={k} />
            </div>
          ) : null}
          <RiseLine text={text} size={tSize} font={GROTESK} weight={800} at={8} out={out} k={k} gap={1.1} />
          {subFit ? (
            <div style={{ marginTop: subFit.size * 0.32 }}>
              <KineticLine text={subFit.lines[0]} font={INTER} weight={500} size={subFit.size} color={SOFT_WHITE} preset="focus"
                timing={{ at: 18, gap: 2 }} out={out} shadow={softShadow(k, 0.45)} />
            </div>
          ) : null}
        </div>
        <svg width={w} height={h} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          {labels.map((_l, i) => {
            const pop = prog(f, 10 + i * 2, 12, S, cubicOut) * (1 - clamp01(out * 1.4 - ((total - 1 - i) / total) * 0.4));
            const q = lit(i);
            const x = segX(i);
            const own = i === level - 1;
            const col = q > 0 ? rampOf(i) : "#FFFFFF";
            return (
              <g key={i} opacity={pop}>
                <rect x={x} y={segY} width={segW * (0.4 + 0.6 * pop)} height={segH} rx={segH / 2} fill="rgba(255,255,255,0.1)" />
                {q > 0 ? (
                  <rect x={x} y={segY} width={segW * q} height={segH} rx={segH / 2} fill={col}
                    opacity={own ? 1 : 0.88}
                    style={own ? { filter: `drop-shadow(0 0 ${(8 + 6 * breathe) * k}px ${rgba(hot, 0.65)})` } : undefined} />
                ) : null}
              </g>
            );
          })}
          {mark > 0.001 ? (
            <path d={tri(mx, segY - 6 * k - (1 - mark) * 10 * k, 7 * k, true)} fill={WHITE} opacity={clamp01(mark * 1.3)}
              style={{ filter: `drop-shadow(0 ${(1.5 * k).toFixed(1)}px ${(4 * k).toFixed(1)}px rgba(0,0,0,0.5))` }} />
          ) : null}
        </svg>
        <div style={{ position: "absolute", left: segX(level - 1), top: segY, width: segW, height: segH, borderRadius: segH,
          overflow: "hidden", opacity: xo }}>
          <Glint p={(t - landF - 4) / 18} />
        </div>
        {labels.map((l, i) => (
          <div key={`l${i}`} style={{ position: "absolute", left: segX(i), top: segY + segH + 10 * k, width: segW,
            textAlign: "center", fontFamily: SUBLINE, fontWeight: 700, fontSize: lbSize, lineHeight: 1, letterSpacing: "0.06em",
            color: i === level - 1 ? WHITE : i < level ? "rgba(250,250,247,0.7)" : "rgba(250,250,247,0.4)", whiteSpace: "nowrap",
            textTransform: "uppercase", opacity: prog(f, 12 + i * 2, 12, S, cubicOut) * xo }}>{l}</div>
        ))}
      </Glass>
    </AbsoluteFill>
  );
};

// ================================================================== kt-delta
/**
 * A figure's change as said, low on the calm side over a soft shade. From and to ("from 1,225 feet in 1983 to
 * 1,040 feet"): the old figure smaller and quieter with its year under it, an arrow drawing from it (bending
 * down for a fall, up for a rise) to the new figure, which counts from the old value to its own as the arrow
 * lands (the second part waits for its word, items[1].at), then the change in a pill (▼ 185 FT) and one line
 * of context. One change since a time ("down 38 percent since 2000", value -38): the change big with its
 * arrow and "SINCE 2000" under it.
 */
const Delta: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, dir, hot, out, ks, panel } = useLook(overlay, accent);
  const items = itemsOf(overlay, 2).filter((x) => x.value !== null);
  const pair = items.length === 2;
  const single = num(overlay.value);
  const t1 = pair ? saidAt(items[1].at, 14) : 8;
  const landF = t1 + 30;
  const sound = useLookSound(pair || single !== null ? [{ name: "ui-swipe", alt: ["swipe", "whoosh-soft"], at: Math.round(t1), gain_db: -13 },
    { name: "count-roll", alt: ["count-tick"], at: Math.round(t1 + 4), until: Math.round(landF - 2), gain_db: -8 },
    { name: "count-final", alt: ["tick"], at: Math.round(landF), gain_db: -6 }] : null);
  if (!pair && (single === null || single === 0)) return null;
  const kicker = str(overlay.text);
  const context = str(overlay.subtitle);
  const since = str(overlay.label);
  const U = unitOf(W, H);
  const kSize = capFont(share("kicker"), U, ks);
  const oSize = capFont(share("deltaOld"), U, ks, dir.cap);
  const nSize0 = capFont(share("deltaNew"), U, ks, dir.cap);
  const pSize = capFont(share("deltaPill"), U, ks);
  const lSize = capFont(share("small"), U, ks);
  const cSize = capFont(share("context"), U, ks);
  const suffix = overlay.suffix, prefix = overlay.prefix;
  const from = pair ? (items[0].value as number) : 0;
  const to = pair ? (items[1].value as number) : (single as number);
  const down = pair ? to < from : to < 0;
  const grow = prog(f, t1 + 6, 30, S, expoOut);
  const oldF = figParts(from, 1, suffix, prefix);
  const newF = figParts(Math.abs(to), pair ? grow : prog(f, 8, 30, S, expoOut), suffix, prefix, pair ? from : 0);
  const newFinal = `${newF.final}`;
  let nSize = nSize0;
  const unitW = (s: number, u: string) => (u ? 10 * k + widthOf(u, SUBLINE, Math.max(lSize, s * 0.34), 700, 0.08) : 0);
  const newW = (s: number) => widthOf(newFinal, dir.font, s, 800, -0.01) + unitW(s, newF.unit) + (pair ? 0 : s * 0.42 + 10 * k);
  const arrowW = pair ? 0.075 * W : 0;
  const oldW = pair ? widthOf(oldF.final, dir.font, oSize, 800, -0.01) + unitW(oSize, oldF.unit) : 0;
  while (nSize > nSize0 * 0.72 && oldW + arrowW + newW(nSize) > 0.5 * W) nSize *= 0.96;
  const change = pair ? Math.abs(to - from) : Math.abs(to);
  const pill = prog(f, landF + 2, 14, S, (u) => backOut(u, 1.5));
  const pillF = figParts(change, prog(f, landF + 2, 22, S, expoOut), suffix, prefix);
  const pillText = `${pillF.main}${pillF.unit ? ` ${pillF.unit}` : ""}`;
  const ctx = context ? fitLines(context, INTER, 600, cSize, cSize * 0.85, 0.44 * W, 1) : null;
  const rowH = nSize * 1.02;
  const labelRow = pair || since ? lSize * 2.1 : 0;
  const w = Math.max(oldW + arrowW + newW(nSize), kicker ? capsWidth(kicker, kSize) : 0, ctx ? ctx.width : 0) + 8 * k;
  const h = (kicker ? kSize + 16 * k : 0) + rowH + labelRow + (pair ? 14 * k + pSize * 1.8 : 0) + (ctx ? ctx.size * 1.6 : 0);
  const zone = zoneFor(overlay, panel ? "left-panel" : "lower-left", w, h, W, H) as Zone;
  const r = blockAt(zone, w, h, W, H);
  const right = isRight(zone);
  const xo = 1 - clamp01(out * 1.4);
  const drift = idle(f, 40 * S, dur) * 4 * k;
  const t = f / S;
  const rowY = kicker ? kSize + 16 * k : 0;
  // the arrow: from the old figure's right to the new one's left, bending the way the figure went
  const ax0 = oldW + 14 * k, ax1 = oldW + arrowW - 14 * k;
  const ay = rowY + rowH * 0.55;
  const bend = (down ? 1 : -1) * rowH * 0.32;
  const arrowP = pair ? prog(f, t1, 20, S, cubicInOut) * xo : 0;
  const arrowD = `M${ax0.toFixed(1)},${(ay - bend * 0.6).toFixed(1)} Q${((ax0 + ax1) / 2).toFixed(1)},${(ay + bend).toFixed(1)} ${ax1.toFixed(1)},${(ay + bend * 0.25).toFixed(1)}`;
  const headS = 8 * k * prog(f, t1 + 16, 8, S, (u) => backOut(u, 1.8)) * xo;
  const dx = ax1 - (ax0 + ax1) / 2, dy = (ay + bend * 0.25) - (ay + bend);
  const dl = Math.max(1e-6, Math.hypot(dx, dy));
  const hx = dx / dl, hy = dy / dl;
  const tipX = ax1 + hx * 2 * k, tipY = ay + bend * 0.25 + hy * 2 * k;
  const headD = `M${tipX.toFixed(1)},${tipY.toFixed(1)} L${(tipX - hx * headS * 1.7 - hy * headS).toFixed(1)},${(tipY - hy * headS * 1.7 + hx * headS).toFixed(1)} `
    + `L${(tipX - hx * headS * 1.7 + hy * headS).toFixed(1)},${(tipY - hy * headS * 1.7 - hx * headS).toFixed(1)} Z`;
  const figStyle = (size: number, color: string): React.CSSProperties => ({ fontFamily: dir.font, fontWeight: 800, fontSize: size,
    lineHeight: 1, color, letterSpacing: "-0.01em", fontVariantNumeric: "tabular-nums", fontFeatureSettings: '"tnum" 1',
    whiteSpace: "nowrap", textShadow: softShadow(k, 0.55) });
  const newIn = pair ? prog(f, t1 + 4, 12, S, cubicOut) : prog(f, 4, 12, S, cubicOut);
  return (
    <AbsoluteFill>
      {sound}
      <Backing panel={panel} dir={dir} rect={r} right={right} p={prog(f, 0, 14, S, cubicOut)} out={out} />
      <div style={{ position: "absolute", left: r.x, top: r.y - drift, width: r.w, height: r.h }}>
        {kicker ? (
          <div style={{ position: "absolute", left: 0, top: 0, height: kSize }}>
            <Caps text={kicker} size={kSize} color={dir.id === "doc" ? SOFT_WHITE : hot} at={0} out={out} k={k} />
          </div>
        ) : null}
        {pair ? (
          <div style={{ position: "absolute", left: 0, top: rowY + (rowH - oSize) * 0.72, opacity: prog(f, 3, 12, S, cubicOut) * xo,
            transform: `translateY(${((1 - prog(f, 3, 14, S, expoOut)) * 10 * k).toFixed(2)}px)` }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8 * k }}>
              <span style={figStyle(oSize, "rgba(250,250,247,0.74)")}>{oldF.final}</span>
              {oldF.unit ? <span style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: Math.max(lSize, oSize * 0.42),
                letterSpacing: "0.08em", color: DIM }}>{oldF.unit}</span> : null}
            </div>
            <div style={{ marginTop: (rowH - oSize) * 0.28 + lSize * 0.55, height: lSize }}>
              <Caps text={items[0].label} size={lSize} color={DIM} at={6} out={out} k={k} tracking={0.16} />
            </div>
          </div>
        ) : null}
        <svg width={r.w} height={r.h} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          {pair ? (
            <>
              <Draw d={arrowD} p={arrowP} color={WHITE} width={Math.max(2.5, 3.6 * k)} shadow={0.55} />
              {headS > 0.5 ? <path d={headD} fill={WHITE} style={{ filter: `drop-shadow(0 ${(1.5 * k).toFixed(1)}px ${(4 * k).toFixed(1)}px rgba(0,0,0,0.5))` }} /> : null}
            </>
          ) : null}
        </svg>
        <div style={{ position: "absolute", left: pair ? oldW + arrowW : 0, top: rowY, opacity: newIn * xo,
          transform: `scale(${settle(f, landF, S).toFixed(4)})`, transformOrigin: "left bottom" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10 * k }}>
            {!pair ? (
              <svg width={nSize * 0.42} height={nSize * 0.62} style={{ overflow: "visible", alignSelf: "center" }}>
                <path d={tri(nSize * 0.21, down ? nSize * 0.56 : 0.06 * nSize, nSize * 0.19, down)} fill={hot} />
              </svg>
            ) : null}
            <span style={{ position: "relative", ...figStyle(nSize, WHITE) }}>
              {newF.main}
              <span style={{ position: "absolute", inset: 0, overflow: "hidden", mixBlendMode: "screen" }}>
                <Glint p={(t - landF - 2) / 20} />
              </span>
            </span>
            {newF.unit ? <span style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: nSize * 0.34, letterSpacing: "0.08em",
              color: SOFT_WHITE, textShadow: softShadow(k, 0.45) }}>{newF.unit}</span> : null}
          </div>
          {pair ? (
            <div style={{ marginTop: lSize * 0.55, height: lSize }}>
              <Caps text={items[1].label} size={lSize} color={WHITE} at={t1 + 10} out={out} k={k} tracking={0.16} />
            </div>
          ) : since ? (
            <div style={{ marginTop: lSize * 0.55, height: lSize }}>
              <Caps text={since} size={lSize} color={SOFT_WHITE} at={14} out={out} k={k} tracking={0.16} />
            </div>
          ) : null}
        </div>
        {pair && pill > 0.001 ? (
          <div style={{ position: "absolute", left: oldW + arrowW, top: rowY + rowH + labelRow + 10 * k, display: "flex",
            alignItems: "center", gap: 8 * k, padding: `${5 * k}px ${13 * k}px`, borderRadius: pSize, opacity: clamp01(pill * 1.4) * xo,
            transform: `scale(${(0.86 + 0.14 * pill).toFixed(4)})`, transformOrigin: "left center",
            background: "rgba(8,10,14,0.6)", boxShadow: `inset 0 0 0 ${Math.max(1, k).toFixed(1)}px ${rgba(hot, 0.7)}`, whiteSpace: "nowrap" }}>
            <svg width={pSize * 0.8} height={pSize * 0.8} style={{ overflow: "visible" }}>
              <path d={tri(pSize * 0.4, down ? pSize * 0.8 : 0, pSize * 0.32, down)} fill={hot} />
            </svg>
            <span style={{ fontFamily: GROTESK, fontWeight: 800, fontSize: pSize, lineHeight: 1, color: WHITE,
              fontVariantNumeric: "tabular-nums", fontFeatureSettings: '"tnum" 1' }}>{pillText}</span>
          </div>
        ) : null}
        {ctx ? (
          <div style={{ position: "absolute", left: 0, top: h - ctx.size * 1.35 }}>
            <KineticLine text={ctx.lines[0]} font={INTER} weight={600} size={ctx.size} color={SOFT_WHITE} preset="focus"
              timing={{ at: pair ? t1 + 18 : 20, gap: 2 }} out={out} align={right ? "right" : "left"} shadow={softShadow(k, 0.55)} />
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== kt-streak
/**
 * A streak as said ("31 straight days above 110 degrees", "143 days without rain"), low on the calm side over
 * a soft shade: the kicker, the count rolling up (expo-out, 36 frames) with DAYS beside it, and the streak as a
 * calendar - one cell a day, a week to a column (one row for a short streak) - the cells lighting with the count,
 * the last one in the accent and ringed as the count lands; one line of context under it. Up to a year of days.
 */
const Streak: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, dir, hot, out, ks, panel } = useLook(overlay, accent);
  const days = Math.round(num(overlay.value) ?? 0);
  const ok = days >= 2 && days <= 371;
  const landF = 46;
  const sound = useLookSound(ok ? [{ name: "count-roll", alt: ["count-tick"], at: 8, until: landF - 2, gain_db: -8 },
    { name: "count-final", alt: ["tick"], at: landF, gain_db: -6 }] : null);
  if (!ok) return null;
  const kicker = str(overlay.text) || str(overlay.label);
  const context = str(overlay.subtitle);
  const unit = (str(overlay.suffix) || "days").toUpperCase();
  const U = unitOf(W, H);
  const kSize = capFont(share("kicker"), U, ks);
  const nSize = capFont(share("streakNumber"), U, ks, dir.cap);
  const uSize = capFont(share("streakUnit"), U, ks);
  const cSize = capFont(share("context"), U, ks);
  const cell0 = share("dayCell") * U * ks;
  // the calendar: one row up to two weeks, else a week to a column
  const rowsN = days <= 14 ? 1 : 7;
  const cols = Math.ceil(days / rowsN);
  const maxGridW = 0.34 * W;
  const gapOf = (c: number) => Math.max(2, c * 0.28);
  let cell = cell0;
  while (cell > 5 && cols * cell + (cols - 1) * gapOf(cell) > maxGridW) cell *= 0.94;
  const cg = gapOf(cell);
  const gridW = cols * cell + (cols - 1) * cg;
  const gridH = rowsN * cell + (rowsN - 1) * cg;
  const numText = countText(figureOf(days), 1);
  const numW = widthOf(numText, dir.font, nSize, 800, -0.02);
  const unitW = widthOf(unit, SUBLINE, uSize, 700, 0.1);
  const ctx = context ? fitLines(context, INTER, 600, cSize, cSize * 0.85, 0.42 * W, 1) : null;
  const w = Math.max(numW + 16 * k + unitW, gridW, kicker ? capsWidth(kicker, kSize) : 0, ctx ? ctx.width : 0) + 6 * k;
  const h = (kicker ? kSize + 16 * k : 0) + nSize * 0.9 + 22 * k + gridH + (ctx ? 18 * k + ctx.size * 1.3 : 0);
  const zone = zoneFor(overlay, panel ? "left-panel" : "lower-left", w, h, W, H) as Zone;
  const r = blockAt(zone, w, h, W, H);
  const right = isRight(zone);
  const xo = 1 - clamp01(out * 1.4);
  const drift = idle(f, 40 * S, dur) * 4 * k;
  const t = f / S;
  const count = prog(f, 8, landF - 8, S, expoOut);
  const shown = Math.round(days * count);
  const fig = countText(figureOf(days), count);
  const numY = kicker ? kSize + 16 * k : 0;
  const gridY = numY + nSize * 0.9 + 22 * k;
  const ring = clamp01((t - landF) / 26);
  const lastI = days - 1;
  const cellXY = (i: number): [number, number] => (rowsN === 1 ? [i * (cell + cg), 0]
    : [Math.floor(i / 7) * (cell + cg), (i % 7) * (cell + cg)]);
  const gx0 = right ? w - gridW : 0;
  return (
    <AbsoluteFill>
      {sound}
      <Backing panel={panel} dir={dir} rect={r} right={right} p={prog(f, 0, 14, S, cubicOut)} out={out} />
      <div style={{ position: "absolute", left: r.x, top: r.y - drift, width: w, height: h }}>
        {kicker ? (
          <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: kSize }}>
            <Caps text={kicker} size={kSize} color={dir.id === "doc" ? SOFT_WHITE : hot} at={0} out={out} k={k}
              align={right ? "right" : "left"} />
          </div>
        ) : null}
        <div style={{ position: "absolute", top: numY, [right ? "right" : "left"]: 0, display: "flex", alignItems: "baseline",
          flexDirection: right ? "row-reverse" : "row", gap: 16 * k, opacity: prog(f, 4, 10, S, cubicOut) * xo,
          transform: `scale(${settle(f, landF, S).toFixed(4)}) translateY(${(out * 8 * k).toFixed(2)}px)`,
          transformOrigin: right ? "right bottom" : "left bottom" } as React.CSSProperties}>
          <span style={{ position: "relative", display: "inline-block", minWidth: numW, textAlign: right ? "right" : "left",
            fontFamily: dir.font, fontWeight: 800, fontSize: nSize, lineHeight: 0.9, letterSpacing: "-0.02em", color: WHITE,
            fontVariantNumeric: "tabular-nums", fontFeatureSettings: '"tnum" 1', textShadow: softShadow(k, 0.55) }}>
            {fig}
            <span style={{ position: "absolute", inset: 0, overflow: "hidden", mixBlendMode: "screen" }}>
              <Glint p={(t - landF) / 20} />
            </span>
          </span>
          <span style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: uSize, letterSpacing: "0.1em", color: SOFT_WHITE,
            textShadow: softShadow(k, 0.45), opacity: prog(f, 12, 12, S, cubicOut) }}>{unit}</span>
        </div>
        <svg width={w} height={h} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          {Array.from({ length: days }, (_v, i) => {
            const [cx, cy] = cellXY(i);
            const x = gx0 + cx, y = gridY + cy;
            const on = i < shown;
            const appear = prog(f, 4 + Math.min(10, (i / days) * 10), 10, S, cubicOut)
              * (1 - clamp01(out * 1.5 - (i / days) * 0.5));
            const last = i === lastI && t >= landF - 1;
            return (
              <rect key={i} x={x} y={y} width={cell} height={cell} rx={cell * 0.24}
                fill={last ? hot : on ? "rgba(250,250,247,0.86)" : "rgba(255,255,255,0.11)"} opacity={appear}
                style={last ? { filter: `drop-shadow(0 0 ${(6 * k).toFixed(1)}px ${rgba(hot, 0.7)})` } : undefined} />
            );
          })}
          {ring > 0 && ring < 1 ? (() => {
            const [cx, cy] = cellXY(lastI);
            return <circle cx={gx0 + cx + cell / 2} cy={gridY + cy + cell / 2} r={cell * (0.7 + 1.6 * cubicOut(ring))} fill="none"
              stroke={hot} strokeWidth={Math.max(1.5, 2 * k)} opacity={(1 - ring) * 0.8 * xo} />;
          })() : null}
        </svg>
        {ctx ? (
          <div style={{ position: "absolute", left: 0, right: 0, top: gridY + gridH + 18 * k }}>
            <KineticLine text={ctx.lines[0]} font={INTER} weight={600} size={ctx.size} color={SOFT_WHITE} preset="focus"
              timing={{ at: 22, gap: 2 }} out={out} align={right ? "right" : "left"} shadow={softShadow(k, 0.55)} />
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== kt-alert
/** The level of an alert from its name, and its status colour (warning red, watch orange, advisory amber). */
export const alertLevel = (name: string): { level: "warning" | "watch" | "advisory" | "order"; color: string } => {
  const s = name.toLowerCase();
  if (/\b(evacuation|order|emergency)\b/.test(s)) return { level: "order", color: "#E5484D" };
  if (/\bwatch(es)?\b/.test(s)) return { level: "watch", color: "#F0883E" };
  if (/\b(advisory|advisories|statement|notice)\b/.test(s)) return { level: "advisory", color: "#E9B949" };
  return { level: "warning", color: "#E5484D" };
};

/**
 * An official alert as said ("a flash flood warning until 9 PM for Maricopa County"), as a frosted card top left
 * (mirrored off faces and logos): a small status dot in the alert's level colour that pops and pings twice,
 * the kicker (who issued it, as said; else ALERT), the alert's name rising letter by letter in the bold grotesk,
 * and its details as said (until when, where) coming into focus under it. No bars, no strip: the dot alone
 * carries the colour. The dot breathes while it holds.
 */
const Alert: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, out, ks } = useLook(overlay, accent);
  const name = str(overlay.text);
  if (!name) return null;
  const details = str(overlay.subtitle);
  const lvl = alertLevel(name);
  const kicker = (str(overlay.label) || "Alert").toUpperCase();
  const U = unitOf(W, H);
  const kSize = capFont(share("kicker"), U, ks);
  let nSize = capFont(share("alertName"), U, ks);
  const dSize = capFont(share("alertDetail"), U, ks);
  const up = name.toUpperCase();
  const maxW = 0.4 * W;
  while (nSize > capFont(share("alertName"), U, ks) * 0.72 && riseWidth(up, GROTESK, nSize, 800, 0.005) > maxW) nSize *= 0.96;
  const nameW = riseWidth(up, GROTESK, nSize, 800, 0.005);
  if (nameW > maxW * 1.05) return null;
  const det = details ? fitLines(details, INTER, 500, dSize, dSize * 0.86, Math.max(nameW, 0.26 * W), 1) : null;
  const dotR = kSize * 0.42;
  const padX = 24 * k, padY = 20 * k;
  const innerW = Math.max(nameW, (det ? det.width : 0), capsWidth(kicker, kSize) + dotR * 2 + 12 * k);
  const w = innerW + padX * 2;
  const h = padY * 2 + kSize + 0.3 * nSize + nSize * 1.2 + (det ? 0.25 * nSize + det.size * 1.25 : 0);
  const zone = zoneFor(overlay, "upper-left", w, h, W, H) as Zone;
  const r = blockAt(zone, w, h, W, H);
  const open = prog(f, 0, 14, S, expoOut);
  const xo = 1 - clamp01(out * 1.4);
  const t = f / S;
  const pop = prog(f, 4, 10, S, (u) => backOut(u, 1.9)) * xo;
  const pings = [8, 30].map((s) => clamp01((t - s) / 26));
  const breathe = t > 40 ? 0.5 + 0.5 * Math.sin((t - 40) / 9) : 0;
  const drift = idle(f, 40 * S, dur) * 3 * k;
  return (
    <AbsoluteFill>
      <Glass x={r.x} y={r.y + drift} w={w} h={h} k={k} p={open} out={out} right={isRight(zone)} radius={14}>
        {/* a breath of the alert's colour from the dot's corner, so the card belongs to the alert */}
        <div style={{ position: "absolute", left: -w * 0.2, top: -h * 0.6, width: w * 0.9, height: h * 1.6, opacity: 0.22 * pop,
          background: `radial-gradient(ellipse 50% 50% at 30% 40%, ${rgba(lvl.color, 0.55)} 0%, ${rgba(lvl.color, 0)} 70%)` }} />
        <div style={{ position: "absolute", left: padX, top: padY, width: innerW }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 * k, height: kSize, marginBottom: 0.3 * nSize }}>
            <svg width={dotR * 2} height={dotR * 2} style={{ overflow: "visible", flex: "none" }}>
              {pings.map((p, i) => (p > 0 && p < 1 ? (
                <circle key={i} cx={dotR} cy={dotR} r={dotR * (1 + 2.6 * cubicOut(p))} fill="none" stroke={lvl.color}
                  strokeWidth={Math.max(1.2, 1.8 * k)} opacity={(1 - p) * 0.85 * xo} />
              ) : null))}
              <circle cx={dotR} cy={dotR} r={Math.max(0, dotR * pop * (1 + 0.08 * breathe))} fill={lvl.color}
                style={{ filter: `drop-shadow(0 0 ${((5 + 5 * breathe) * k).toFixed(1)}px ${rgba(lvl.color, 0.8)})` }} />
            </svg>
            <Caps text={kicker} size={kSize} color="rgba(250,250,247,0.86)" at={6} out={out} k={k} />
          </div>
          <RiseLine text={up} size={nSize} font={GROTESK} weight={800} at={8} out={out} k={k} tracking={0.005} gap={0.9} />
          {det ? (
            <div style={{ marginTop: 0.25 * nSize }}>
              <KineticLine text={det.lines[0]} font={INTER} weight={500} size={det.size} color={SOFT_WHITE} preset="focus"
                timing={{ at: 20, gap: 2 }} out={out} shadow={softShadow(k, 0.4)} />
            </div>
          ) : null}
        </div>
      </Glass>
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "kt-ranking": guard(Ranking),
  "kt-waterline": guard(Waterline),
  "kt-severity": guard(Severity),
  "kt-delta": guard(Delta),
  "kt-streak": guard(Streak),
  "kt-alert": guard(Alert),
};
