import React from "react";
import { AbsoluteFill } from "remotion";
import type { DataDoc, Overlay } from "../../types";
import { CAPTION_SAFE_ZONE, CaptionsOn } from "../layout";
import { useLookSound } from "./LookSounds";
import type { SoundCue } from "./lookSoundPlan";
import {
  ANTON, SUBLINE, Stage, backOut, caps, clamp01, easeInOut, easeOut, exitOf, fit, guard, heavy, hotOf, inOf, lerp,
  lift, mixHex, rgba, textWidth, useBase, useSvgId, type CSS, type Look,
} from "./proKit";
import { niceScale, seriesScale } from "./proFormat";
import { SourceLine } from "./LibSourceTag";
import { asOfNote, clipText, dataOf, dayOf, decimalsOf, fmtVal, periodLabel, seriesOf, unitParts, valueText,
  yearTicks } from "./rdFormat";

/**
 * REAL DATA (family "rd-"): charts of the official numbers behind a narration's water and weather facts - a
 * reservoir's level and how full it is (USBR), a river's flow and a lake's level (USGS), the share of a state in
 * drought (the U.S. Drought Monitor), a temperature record (NOAA). The numbers are only ever overlay.data, written
 * by the planner from the source's own answer (src/datagraphics.py, src/realdata.py): nothing here invents,
 * rounds away or "corrects" a value, and a look with no data draws nothing.
 *
 *   rd-line     the series over time: the line draws with a soft glow and the area under it fills, the levels
 *               the source states dashed, the start of the window marked, then the latest reading lands with a
 *               pulse and its value and date called out; the change since the start in a chip
 *   rd-number   the latest reading big, counting from the reading it is compared with, its date under it and a
 *               sparkline of the series beneath that draws to the same point
 *   rd-bars     comparison bars on a true zero (the drought categories this week), the one said in the accent
 *   rd-gauge    a reservoir's fill level: a glass vessel fills to the share of live capacity, last year's level a
 *               dashed ghost, the share counting up beside it with the storage out of the capacity
 *
 * Every look carries the source and the date of its data in the low corner, in the source tag's own line
 * (LibSourceTag SourceLine): "SOURCE: USBR · DATA AS OF OCT 3, 2026". The pro kit's language (Anton for the
 * figures, Inter Tight caps, one accent, a cinematic veil), sizes 1080p-referenced, the voice-synced hit on the
 * registry's sfxAt (the latest value lands there), a clean 12-frame exit. Every frame is a pure function of the
 * frame number.
 */

const WHITE = "#FFFFFF";
const SOFT = "rgba(255,255,255,.66)";
const GRID = "rgba(255,255,255,.10)";
const INK = "#0b0d11";
const WATER_TOP = "#8fd0f5";
const WATER_MID = "#3a90cc";
const WATER_DEEP = "#0f3f6e";

/** The title (the overlay's text when the editor set it) and the kicker (its label), in caps. */
const titles = (ov: Overlay, d: DataDoc) => ({
  title: clipText(String(ov.text || d.title || d.entity || ""), 60).toUpperCase(),
  kicker: clipText(String(ov.label || d.kicker || ""), 64).toUpperCase(),
});

// ------------------------------------------------------------------ shared parts
/** Kicker over the title, top-left, the change chip under them. */
const TitleBlock: React.FC<{ ov: Overlay; d: DataDoc; accent: string; out: number; chip?: string; chipAt?: number;
  maxW?: number }> = ({ ov, d, accent, out, chip, chipAt = 54, maxW }) => {
  const { f, S, k, kw, width } = useBase();
  const hot = hotOf(accent);
  const { title, kicker } = titles(ov, d);
  const room = maxW ?? Math.min(1180 * kw, width - 240 * kw);
  const t = fit(title, { font: ANTON, tracking: 0.01 }, room, 64 * k, 38 * k, 1);
  const p1 = inOf(f, 4 * S, 14 * S);
  const p2 = inOf(f, 8 * S, 14 * S);
  const pc = inOf(f, chipAt * S, 12 * S);
  return (
    <div style={{ position: "absolute", left: 120 * kw, top: 92 * kw, opacity: 1 - out,
      transform: `translateY(${(-out * 14 * k).toFixed(1)}px)` }}>
      {kicker ? (
        <div style={{ ...caps(22 * k, hot, 0.2), opacity: p1, transform: `translateY(${((1 - p1) * 10 * k).toFixed(1)}px)`,
          marginBottom: 14 * k, textShadow: lift(k, 0.5) }}>{kicker}</div>
      ) : null}
      {t.lines.map((ln, i) => (
        <div key={i} style={{ overflow: "hidden", paddingBottom: 4 * k }}>
          <div style={{ ...heavy(t.size, WHITE, 0.01), transform: `translateY(${((1 - p2) * 110).toFixed(1)}%)`,
            textShadow: lift(k, 0.4) }}>{ln}</div>
        </div>
      ))}
      {chip ? (
        <div style={{ display: "inline-flex", marginTop: 18 * k, padding: `${10 * k}px ${16 * k}px`, borderRadius: 8 * k,
          background: "rgba(8,10,14,.78)", border: `${Math.max(1, 1.4 * k)}px solid ${rgba(hot, 0.55)}`, opacity: pc,
          transform: `translateX(${((1 - pc) * -14 * k).toFixed(1)}px)` }}>
          <span style={{ ...caps(24 * k, WHITE, 0.1) }}>{clipText(chip, 44).toUpperCase()}</span>
        </div>
      ) : null}
    </div>
  );
};

/** The source and the date of the data, low left, in the source tag's line. */
const SourceCorner: React.FC<{ d: DataDoc; accent: string; at?: number }> = ({ d, accent, at = 18 }) => (
  <SourceLine name={String(d.source || d.sourceName || "")} note={asOfNote(d)} at={at} accent={hotOf(accent)} />
);

/** A figure in Anton with its unit: glued ("22.3%") or after it, smaller, in the accent ("1,037.9 FT"). */
const Figure: React.FC<{ text: string; unit: unknown; size: number; color?: string; unitColor?: string; style?: CSS }> =
  ({ text, unit, size, color = WHITE, unitColor, style }) => {
    const u = unitParts(unit);
    return (
      <span style={{ ...heavy(size, color), display: "inline-flex", alignItems: "baseline", ...style }}>
        <span>{text}</span>
        {u.glued ? <span style={{ fontSize: size * 0.66, color: unitColor || color, marginLeft: size * 0.02 }}>{u.glued}</span> : null}
        {u.after ? <span style={{ fontSize: size * 0.42, color: unitColor || color, marginLeft: size * 0.14,
          letterSpacing: "0.04em" }}>{u.after}</span> : null}
      </span>
    );
  };

const figureWidth = (text: string, unit: unknown, size: number): number => {
  const u = unitParts(unit);
  let w = textWidth(text, ANTON, size, 400, 0.01);
  if (u.glued) w += textWidth(u.glued, ANTON, size * 0.66) + size * 0.02;
  if (u.after) w += textWidth(u.after, ANTON, size * 0.42, 400, 0.04) + size * 0.14;
  return w;
};

/** Where the plot may go down to: above the caption strip when captions are on. */
const useFloor = (wanted: number): number => {
  const { kw, height } = useBase();
  const captions = React.useContext(CaptionsOn);
  return captions ? Math.min(wanted, height * (1 - CAPTION_SAFE_ZONE) - 40 * kw) : wanted;
};

// ================================================================== rd-line
const LINE = { drawAt: 12, drawFrames: 38, land: 50 };

const RdLine: Look = ({ overlay, accent }) => {
  const { f, S, k, kw, width, height, dur } = useBase();
  const id = useSvgId("rdl");
  const d = dataOf(overlay);
  const pts = seriesOf(d);
  const floor = useFloor(Math.min(850 * kw, height - 230 * kw));
  const sound = useLookSound(pts.length >= 2 ? [
    { name: "ui-tick", alt: ["tick"], at: 18, every: 6, count: 5, gain_db: -10 },
    { name: "count-final", alt: ["ui-tick", "tick"], at: LINE.land, gain_db: -4 },
  ] as SoundCue[] : []);
  if (!d || pts.length < 2) return null;
  const hot = hotOf(accent);
  const out = exitOf(f, dur, S);
  const dec = decimalsOf(d);
  const unit = d.unit || "";

  // The plot box (1080p): the left for the axis, the right for the latest reading's callout.
  const x0 = 250 * kw;
  const x1 = width - 470 * kw;
  const y0 = 330 * kw;
  const y1 = floor;
  const t0 = pts[0].t;
  const t1 = pts[pts.length - 1].t;
  const refs = (Array.isArray(d.refs) ? d.refs : []).filter((r) => Number.isFinite(Number(r?.value)));
  const vals = pts.map((p) => p.v);
  const range = Array.isArray(d.range) && d.range.length === 2 && d.range.every((x) => Number.isFinite(Number(x)))
    ? [Number(d.range[0]), Number(d.range[1])] : null;
  const sc = range ? niceScale(range[0], range[1], 4)
    : seriesScale([...vals, ...refs.map((r) => Number(r.value))], 5);
  const X = (t: number) => x0 + ((t - t0) / (t1 - t0 || 1)) * (x1 - x0);
  const Y = (v: number) => y1 - ((v - sc.min) / (sc.max - sc.min || 1)) * (y1 - y0);
  const P = pts.map((p) => [X(p.t), Y(p.v)] as [number, number]);

  // The draw: the head runs along time; the path is every point it has passed and the head itself.
  const draw = easeInOut(clamp01((f - LINE.drawAt * S) / (LINE.drawFrames * S)));
  const hx = lerp(P[0][0], P[P.length - 1][0], draw);
  const shown: [number, number][] = [];
  let hy = P[0][1];
  for (let i = 0; i < P.length; i++) {
    if (P[i][0] <= hx) {
      shown.push(P[i]);
      hy = P[i][1];
      continue;
    }
    const a = P[i - 1] || P[i];
    const u = (hx - a[0]) / ((P[i][0] - a[0]) || 1);
    hy = lerp(a[1], P[i][1], clamp01(u));
    shown.push([hx, hy]);
    break;
  }
  const path = shown.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const area = shown.length >= 2 ? `${path} L${shown[shown.length - 1][0].toFixed(1)} ${y1.toFixed(1)} L${P[0][0].toFixed(1)} ${y1.toFixed(1)} Z` : "";
  const passAt = (t: number) => LINE.drawAt + LINE.drawFrames * clamp01((t - t0) / (t1 - t0 || 1));

  // The callout: the record year when the line is about one, else the latest reading.
  const latest = pts[pts.length - 1];
  const rec = d.record && Number.isFinite(dayOf(d.record.date)) ? pts.find((p) => Math.abs(p.t - dayOf(d.record!.date)) < 864e5 * 200
    && Math.abs(p.v - Number(d.record!.value)) < 1e-6) : undefined;
  const focus = rec || latest;
  const [fx, fy] = [X(focus.t), Y(focus.v)];
  const landAt = rec && rec !== latest ? Math.min(LINE.land, Math.round(passAt(rec.t)) + 2) : LINE.land;
  const landP = inOf(f, landAt * S, 14 * S);
  const pulse = clamp01((f - landAt * S) / (24 * S));
  const valSize = 72 * k;
  const focusText = fmtVal(focus.v, dec);
  const fw = figureWidth(focusText, unit, valSize);
  const right = fx + 34 * k + fw < width - 90 * kw;
  const focusLabel = rec && rec !== latest ? `${d.record!.label} · ${String(d.record!.word || "").toUpperCase()}` : String(d.latest?.label || d.asOfLabel || "");
  const calloutTop = Math.max(y0 - 40 * kw, Math.min(y1 - 110 * kw, fy - valSize * 0.62));

  // The point compared with (a year said, the start of the window): marked small when the head passes it.
  const cmp = d.compare && Number.isFinite(dayOf(d.compare.date)) && Number.isFinite(Number(d.compare.value))
    ? { t: dayOf(d.compare.date), v: Number(d.compare.value), label: String(d.compare.label || "") } : null;
  const cmpVisible = cmp && Math.abs(cmp.t - focus.t) > (t1 - t0) * 0.12 ? cmp : null;
  const cx = cmpVisible ? X(Math.max(t0, Math.min(t1, cmpVisible.t))) : 0;
  const cy = cmpVisible ? Y(cmpVisible.v) : 0;
  const cmpP = cmpVisible ? inOf(f, (passAt(cmpVisible.t) + 1) * S, 12 * S) : 0;
  // Its label goes on the side the line leaves free just after it: below a rise, above a fall.
  const after = cmpVisible ? pts.filter((p) => p.t > cmpVisible.t && p.t <= cmpVisible.t + (t1 - t0) * 0.08) : [];
  const rises = after.length ? after.reduce((a, p) => a + p.v, 0) / after.length > cmpVisible!.v : false;
  const cmpAbove = cmpVisible ? (!rises && cy - 60 * k > y0 - 30 * kw) || cy + 70 * k > y1 : false;
  const cmpText = cmpVisible ? `${cmpVisible.label} · ${valueText(cmpVisible.v, dec, unit)}`.toUpperCase() : "";
  const cmpW = cmpVisible ? textWidth(cmpText, SUBLINE, 22 * k, 700, 0.12) + 24 * k : 0;
  const cmpLeft = cmpVisible ? Math.max(x0 - 20 * kw, Math.min(x1 - cmpW, cx - cmpW * 0.2)) : 0;

  // The latest reading, small, when the callout is on a record year.
  const latestSmall = rec && rec !== latest;
  const years = yearTicks(t0, t1);
  const tickLabel = (v: number) => {
    const step = sc.step;
    const dd = step >= 1 ? 0 : Math.min(2, Math.max(0, -Math.floor(Math.log10(step))));
    const u = unitParts(unit);
    return `${fmtVal(v, dd)}${u.glued}`;
  };
  const yLabel = 25 * k;

  return (
    <AbsoluteFill>
      {sound}
      <Stage ov={overlay} p={inOf(f, 0, 10 * S) * (1 - out)} />
      <AbsoluteFill style={{ opacity: 1 - out, transform: `translateY(${(-out * 16 * k).toFixed(1)}px)` }}>
        <svg width={width} height={height} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          <defs>
            <linearGradient id={`${id}a`} x1="0" y1={y0} x2="0" y2={y1} gradientUnits="userSpaceOnUse">
              <stop offset="0" stopColor={hot} stopOpacity={0.3} />
              <stop offset="1" stopColor={hot} stopOpacity={0} />
            </linearGradient>
            <filter id={`${id}g`} x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation={5 * k} result="b" />
              <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>
          {sc.ticks.map((t, i) => {
            const p = inOf(f, (4 + i * 2) * S, 16 * S, easeOut);
            const y = Y(t);
            return (
              <g key={`y${i}`}>
                <line x1={x0} x2={x0 + (x1 - x0 + 30 * kw) * p} y1={y} y2={y} stroke={i === 0 ? "rgba(255,255,255,.3)" : GRID}
                  strokeWidth={Math.max(1, 1.4 * k)} />
                <text x={x0 - 22 * k} y={y + yLabel * 0.36} textAnchor="end" fill={SOFT} opacity={p}
                  style={{ fontFamily: SUBLINE, fontWeight: 600, fontSize: yLabel, fontVariantNumeric: "tabular-nums" }}>
                  {tickLabel(t)}
                </text>
              </g>
            );
          })}
          {years.map((y, i) => {
            const x = X(Date.UTC(y, 0, 1));
            const p = inOf(f, (passAt(Date.UTC(y, 0, 1)) - 2) * S, 12 * S);
            return (
              <g key={`x${i}`} opacity={p}>
                <line x1={x} x2={x} y1={y1} y2={y1 + 10 * k} stroke="rgba(255,255,255,.4)" strokeWidth={2 * k} />
                <text x={x} y={y1 + 46 * k} textAnchor="middle" fill={SOFT}
                  style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.04em" }}>{y}</text>
              </g>
            );
          })}
          {refs.filter((r) => Number(r.value) >= sc.min && Number(r.value) <= sc.max).map((r, i) => {
            const y = Y(Number(r.value));
            const p = inOf(f, (8 + i * 3) * S, 14 * S);
            const text = `${String(r.label || "").toUpperCase()} · ${valueText(Number(r.value), 0, unit)}`;
            return (
              <g key={`r${i}`} opacity={p}>
                <line x1={x0} x2={x1 + 20 * kw} y1={y} y2={y} stroke={rgba(hot, 0.75)} strokeWidth={2 * k}
                  strokeDasharray={`${12 * k} ${10 * k}`} />
                <text x={x0 + 14 * k} y={y - 12 * k} fill={rgba(hot, 0.95)}
                  style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: 21 * k, letterSpacing: "0.12em" }}>{text}</text>
              </g>
            );
          })}
          {area ? <path d={area} fill={`url(#${id}a)`} /> : null}
          {draw > 0 ? (
            <path d={path} fill="none" stroke={hot} strokeWidth={4.5 * k} strokeLinejoin="round" strokeLinecap="round"
              filter={`url(#${id}g)`} />
          ) : null}
          {draw > 0 && f < (LINE.land + 2) * S ? (
            <circle cx={hx} cy={hy} r={9 * k} fill={WHITE} style={{ filter: `drop-shadow(0 0 ${10 * k}px ${hot})` }} />
          ) : null}
          {cmpVisible ? (
            <circle cx={cx} cy={cy} r={7 * k * cmpP} fill={INK} stroke={WHITE} strokeWidth={2.6 * k} opacity={cmpP} />
          ) : null}
          {latestSmall && f >= LINE.land * S ? (
            <circle cx={X(latest.t)} cy={Y(latest.v)} r={7 * k} fill={WHITE} opacity={inOf(f, LINE.land * S, 10 * S)} />
          ) : null}
          {f >= landAt * S ? (
            <g>
              <circle cx={fx} cy={fy} r={(12 + 40 * pulse) * k} fill="none" stroke={hot} strokeWidth={3 * k}
                opacity={(1 - pulse) * 0.8} />
              <circle cx={fx} cy={fy} r={11 * k * Math.min(1, landP * 1.4)} fill={WHITE}
                style={{ filter: `drop-shadow(0 0 ${12 * k}px ${hot})` }} />
            </g>
          ) : null}
        </svg>
        {cmpVisible ? (
          <div style={{ position: "absolute", left: cmpLeft, top: cmpAbove ? cy - 60 * k : cy + 20 * k, opacity: cmpP,
            padding: `${8 * k}px ${12 * k}px`, borderRadius: 6 * k, background: "rgba(8,10,14,.74)" }}>
            <span style={{ ...caps(22 * k, "rgba(255,255,255,.82)", 0.12) }}>{cmpText}</span>
          </div>
        ) : null}
        {latestSmall ? (
          // Under the record's callout when they would meet (a record set the year before the latest).
          <div style={{ position: "absolute", left: right ? fx + 34 * k : X(latest.t) + 16 * k,
            top: Math.max(Y(latest.v) + 16 * k, right ? calloutTop + valSize + 62 * k : 0),
            opacity: inOf(f, (LINE.land + 2) * S, 12 * S) }}>
            <span style={{ ...caps(21 * k, SOFT, 0.1), textShadow: lift(k, 0.6) }}>
              {`${d.step === "year" ? latest.date.slice(0, 4) : String(d.latest?.label || "").toUpperCase()} · `
                + valueText(latest.v, dec, unit)}
            </span>
          </div>
        ) : null}
        <div style={{ position: "absolute", top: calloutTop, left: right ? fx + 34 * k : fx - 34 * k - fw, width: fw,
          display: "flex", flexDirection: "column", alignItems: right ? "flex-start" : "flex-end", opacity: landP,
          transform: `translateX(${((1 - landP) * (right ? -18 : 18) * k).toFixed(1)}px)` }}>
          <Figure text={focusText} unit={unit} size={valSize} unitColor={hot} style={{ textShadow: lift(k, 0.55) }} />
          <div style={{ ...caps(23 * k, WHITE, 0.14), marginTop: 12 * k, opacity: 0.86, textShadow: lift(k, 0.6) }}>
            {clipText(focusLabel, 28)}
          </div>
        </div>
      </AbsoluteFill>
      <TitleBlock ov={overlay} d={d} accent={accent} out={out} chip={d.delta?.text} chipAt={landAt + 4} />
      <SourceCorner d={d} accent={accent} />
    </AbsoluteFill>
  );
};

// ================================================================== rd-number
const NUM = { countAt: 8, land: 40, sparkAt: 14, sparkFrames: 30 };

const RdNumber: Look = ({ overlay, accent }) => {
  const { f, S, k, kw, width, height, dur } = useBase();
  const id = useSvgId("rdn");
  const d = dataOf(overlay);
  const pts = seriesOf(d);
  const floor = useFloor(height - 200 * kw);
  const latestV = Number(d?.latest?.value);
  const ok = Boolean(d) && Number.isFinite(latestV);
  const sound = useLookSound(ok ? [
    { name: "count-roll", alt: ["count-tick", "ui-tick"], at: NUM.countAt, align: "start", until: NUM.land - 1, gain_db: -12 },
    { name: "count-final", alt: ["ui-tick", "tick"], at: NUM.land, gain_db: -5 },
  ] as SoundCue[] : []);
  if (!d || !ok) return null;
  const hot = hotOf(accent);
  const out = exitOf(f, dur, S);
  const dec = decimalsOf(d);
  const unit = d.unit || "";
  const from = d.compare && Number.isFinite(Number(d.compare.value)) ? Number(d.compare.value) : 0;
  const q = easeOut(clamp01((f - NUM.countAt * S) / ((NUM.land - NUM.countAt) * S)));
  const now = f >= NUM.land * S ? latestV : from + (latestV - from) * q;
  const finalText = fmtVal(latestV, dec);
  const nowText = fmtVal(Number(now.toFixed(dec)), dec);
  const size = Math.min(230 * k, (width * 0.6) / Math.max(1, figureWidth(finalText, unit, 1)));
  const fw = figureWidth(finalText, unit, size);
  const spark = pts.length >= 2;
  const numTop = spark ? Math.min(height * 0.36, floor - 470 * kw) : height * 0.42;
  const left = (width - fw) / 2;
  const landP = inOf(f, NUM.land * S, 14 * S);
  const appear = inOf(f, NUM.countAt * S, 10 * S);

  // The sparkline under the figure: the series to the same latest reading.
  const sx0 = width / 2 - 560 * kw;
  const sx1 = width / 2 + 560 * kw;
  const sy0 = numTop + size * 1.02 + 96 * kw;
  const sy1 = Math.min(floor - 40 * kw, sy0 + 180 * kw);
  const t0 = spark ? pts[0].t : 0;
  const t1 = spark ? pts[pts.length - 1].t : 1;
  const vals = pts.map((p) => p.v);
  // A share keeps its whole 0-100 scale; anything else spans its own low to high.
  const fixed = Array.isArray(d.range) && d.range.length === 2 && d.range.every((x) => Number.isFinite(Number(x)));
  const lo = fixed ? Number(d.range![0]) : spark ? Math.min(...vals) : 0;
  const hi = fixed ? Number(d.range![1]) : spark ? Math.max(...vals) : 1;
  const SX = (t: number) => sx0 + ((t - t0) / (t1 - t0 || 1)) * (sx1 - sx0);
  const SY = (v: number) => sy1 - ((v - lo) / (hi - lo || 1)) * (sy1 - sy0);
  const sDraw = easeInOut(clamp01((f - NUM.sparkAt * S) / (NUM.sparkFrames * S)));
  const head = lerp(sx0, sx1, sDraw);
  const sp: string[] = [];
  for (let i = 0; i < pts.length; i++) {
    const x = SX(pts[i].t);
    if (x > head && i > 0) {
      const a = pts[i - 1];
      const u = clamp01((head - SX(a.t)) / ((x - SX(a.t)) || 1));
      sp.push(`L${head.toFixed(1)} ${lerp(SY(a.v), SY(pts[i].v), u).toFixed(1)}`);
      break;
    }
    sp.push(`${i ? "L" : "M"}${x.toFixed(1)} ${SY(pts[i].v).toFixed(1)}`);
  }
  const startLabel = spark ? periodLabel(pts[0].date, d.step) : "";
  const pulse = clamp01((f - NUM.land * S) / (24 * S));
  return (
    <AbsoluteFill>
      {sound}
      <Stage ov={overlay} p={inOf(f, 0, 10 * S) * (1 - out)} />
      <AbsoluteFill style={{ opacity: 1 - out, transform: `translateY(${(-out * 16 * k).toFixed(1)}px)` }}>
        <div style={{ position: "absolute", left, top: numTop, opacity: appear,
          transform: `translateY(${((1 - appear) * 24 * k).toFixed(1)}px) scale(${(1 + 0.03 * Math.sin(Math.PI * clamp01((f - NUM.land * S) / (10 * S)))).toFixed(4)})`,
          transformOrigin: "50% 60%" }}>
          <Figure text={nowText} unit={unit} size={size} unitColor={hot} style={{ textShadow: lift(k, 0.6) }} />
        </div>
        <div style={{ position: "absolute", left: 0, right: 0, top: numTop + size * 1.02 + 14 * kw, display: "flex",
          justifyContent: "center", opacity: landP }}>
          <span style={{ ...caps(26 * k, WHITE, 0.16), opacity: 0.86, textShadow: lift(k, 0.6) }}>
            {clipText(String(d.latest?.label || d.asOfLabel || "").toUpperCase(), 28)}
          </span>
        </div>
        {spark ? (
          <svg width={width} height={height} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
            <defs>
              <linearGradient id={`${id}s`} x1="0" y1={sy0} x2="0" y2={sy1} gradientUnits="userSpaceOnUse">
                <stop offset="0" stopColor={hot} stopOpacity={0.22} />
                <stop offset="1" stopColor={hot} stopOpacity={0} />
              </linearGradient>
            </defs>
            <line x1={sx0} x2={sx1} y1={sy1 + 10 * k} y2={sy1 + 10 * k} stroke={GRID} strokeWidth={Math.max(1, 1.4 * k)}
              opacity={inOf(f, NUM.sparkAt * S, 12 * S)} />
            {sp.length >= 2 ? (
              <path d={`${sp.join(" ")} L${head.toFixed(1)} ${(sy1 + 10 * k).toFixed(1)} L${sx0.toFixed(1)} ${(sy1 + 10 * k).toFixed(1)} Z`}
                fill={`url(#${id}s)`} />
            ) : null}
            {sp.length >= 2 ? (
              <path d={sp.join(" ")} fill="none" stroke={hot} strokeWidth={3.4 * k} strokeLinejoin="round" strokeLinecap="round" />
            ) : null}
            {f >= NUM.land * S ? (
              <g>
                <circle cx={sx1} cy={SY(pts[pts.length - 1].v)} r={(9 + 28 * pulse) * k} fill="none" stroke={hot}
                  strokeWidth={2.4 * k} opacity={(1 - pulse) * 0.8} />
                <circle cx={sx1} cy={SY(pts[pts.length - 1].v)} r={8 * k} fill={WHITE}
                  style={{ filter: `drop-shadow(0 0 ${10 * k}px ${hot})` }} />
              </g>
            ) : null}
            <text x={sx0} y={sy1 + 50 * k} fill={SOFT} opacity={inOf(f, NUM.sparkAt * S, 12 * S)}
              style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: 22 * k, letterSpacing: "0.12em" }}>
              {startLabel.toUpperCase()}
            </text>
            <text x={sx1} y={sy1 + 50 * k} textAnchor="end" fill={WHITE} opacity={landP}
              style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: 22 * k, letterSpacing: "0.12em" }}>NOW</text>
          </svg>
        ) : null}
      </AbsoluteFill>
      <TitleBlock ov={overlay} d={d} accent={accent} out={out} chip={d.delta?.text} chipAt={NUM.land + 4} />
      <SourceCorner d={d} accent={accent} />
    </AbsoluteFill>
  );
};

// ================================================================== rd-bars
const BARS = { firstAt: 10, stagger: 6, grow: 20, land: 42 };

const RdBars: Look = ({ overlay, accent }) => {
  const { f, S, k, kw, width, height, dur } = useBase();
  const d = dataOf(overlay);
  const rows = (Array.isArray(d?.bars) ? (d as DataDoc).bars! : [])
    .filter((b) => b && Number.isFinite(Number(b.value))).slice(0, 6);
  const floor = useFloor(height - 190 * kw);
  const sound = useLookSound(rows.length ? [
    { name: "ui-tick", alt: ["tick"], at: BARS.firstAt, every: BARS.stagger, count: Math.min(6, rows.length), gain_db: -10 },
    { name: "count-final", alt: ["ui-tick", "tick"], at: BARS.land, gain_db: -5 },
  ] as SoundCue[] : []);
  if (!d || !rows.length) return null;
  const hot = hotOf(accent);
  const out = exitOf(f, dur, S);
  const dec = decimalsOf(d);
  const unit = d.unit || "";
  const range = Array.isArray(d.range) && d.range.length === 2 ? Number(d.range[1]) : NaN;
  const top = Number.isFinite(range) && range > 0 ? range : Math.max(...rows.map((r) => Number(r.value))) * 1.12 || 1;
  const labelSize = 30 * k;
  const labels = rows.map((r) => clipText(String(r.label || ""), 26).toUpperCase());
  const labelW = Math.min(520 * kw, Math.max(...labels.map((l) => textWidth(l, SUBLINE, labelSize, 700, 0.1))) + 10 * k);
  const bx = 120 * kw + labelW + 44 * kw;
  const bw = width - bx - 330 * kw;
  const blockTop = 330 * kw;
  const rowH = Math.min(110 * k, (floor - blockTop) / rows.length);
  const barH = rowH * 0.62;
  const startOf = (i: number) => (rows[i].highlight ? BARS.land - BARS.grow : BARS.firstAt + i * BARS.stagger);
  return (
    <AbsoluteFill>
      {sound}
      <Stage ov={overlay} p={inOf(f, 0, 10 * S) * (1 - out)} />
      <AbsoluteFill style={{ opacity: 1 - out, transform: `translateY(${(-out * 16 * k).toFixed(1)}px)` }}>
        <svg width={width} height={height} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          <line x1={bx} x2={bx} y1={blockTop - 16 * k} y2={blockTop + rows.length * rowH} stroke="rgba(255,255,255,.4)"
            strokeWidth={2.4 * k} opacity={inOf(f, 2 * S, 10 * S)} />
          {rows.map((r, i) => {
            const y = blockTop + i * rowH + (rowH - barH) / 2;
            const p = inOf(f, startOf(i) * S, BARS.grow * S, easeOut);
            const len = (Math.max(0, Number(r.value)) / top) * bw;
            const fill = r.highlight ? hot : "rgba(255,255,255,.82)";
            return (
              <g key={i}>
                {Number.isFinite(range) ? <rect x={bx} y={y} width={bw} height={barH} rx={4 * k} fill="rgba(255,255,255,.06)"
                  opacity={inOf(f, (startOf(i) - 4) * S, 10 * S)} /> : null}
                <rect x={bx} y={y} width={Math.max(0, len * p)} height={barH} rx={4 * k} fill={fill}
                  style={r.highlight ? { filter: `drop-shadow(0 0 ${16 * k}px ${rgba(hot, 0.45)})` } : undefined} />
              </g>
            );
          })}
        </svg>
        {rows.map((r, i) => {
          const y = blockTop + i * rowH + rowH / 2;
          const p = inOf(f, startOf(i) * S, BARS.grow * S, easeOut);
          const lp = inOf(f, (startOf(i) - 4) * S, 12 * S);
          const len = (Math.max(0, Number(r.value)) / top) * bw;
          const text = fmtVal(Number((Number(r.value) * p).toFixed(dec)), dec);
          const vSize = 52 * k;
          const pop = r.highlight ? backOut(inOf(f, BARS.land * S, 12 * S, (t) => t), 2) : 1;
          return (
            <React.Fragment key={i}>
              <div style={{ position: "absolute", left: 120 * kw, top: y - labelSize * 0.5, width: labelW, opacity: lp,
                transform: `translateX(${((1 - lp) * -14 * k).toFixed(1)}px)` }}>
                <span style={{ ...caps(labelSize, r.highlight ? WHITE : SOFT, 0.1), textShadow: lift(k, 0.5) }}>{labels[i]}</span>
              </div>
              <div style={{ position: "absolute", left: bx + len * p + 22 * k, top: y - vSize * 0.52, opacity: Math.min(1, p * 3),
                transform: `scale(${(r.highlight && f >= BARS.land * S ? 0.92 + 0.08 * pop : 1).toFixed(4)})`, transformOrigin: "0% 50%" }}>
                <Figure text={text} unit={unit} size={vSize} color={r.highlight ? hot : WHITE} unitColor={r.highlight ? hot : SOFT}
                  style={{ textShadow: lift(k, 0.5) }} />
              </div>
            </React.Fragment>
          );
        })}
      </AbsoluteFill>
      <TitleBlock ov={overlay} d={d} accent={accent} out={out} />
      <SourceCorner d={d} accent={accent} />
    </AbsoluteFill>
  );
};

// ================================================================== rd-gauge
const GAUGE = { drawAt: 0, riseAt: 12, land: 42 };

const RdGauge: Look = ({ overlay, accent }) => {
  const { f, S, k, kw, width, height, dur, fps } = useBase();
  const id = useSvgId("rdg");
  const d = dataOf(overlay);
  const pct = Number(d?.latest?.value);
  const ok = Boolean(d) && Number.isFinite(pct);
  const floor = useFloor(height - 180 * kw);
  const sound = useLookSound(ok ? [
    { name: "count-roll", alt: ["count-tick", "ui-tick"], at: GAUGE.riseAt, align: "start", until: GAUGE.land - 1, gain_db: -12 },
    { name: "count-final", alt: ["ui-tick", "tick"], at: GAUGE.land, gain_db: -5 },
  ] as SoundCue[] : []);
  if (!d || !ok) return null;
  const hot = hotOf(accent);
  const out = exitOf(f, dur, S);
  const dec = decimalsOf(d);
  const share = clamp01(pct / 100);
  const rise = inOf(f, GAUGE.riseAt * S, (GAUGE.land - GAUGE.riseAt) * S, easeOut);
  const level = share * rise;
  // The vessel (1080p): tall glass, left of centre.
  const vx = 330 * kw;
  const vw = 340 * kw;
  const vt = 300 * kw;
  const vb = floor;
  const vh = vb - vt;
  const r = 28 * k;
  const drawP = inOf(f, GAUGE.drawAt * S, 16 * S, easeInOut);
  const surface = vb - vh * level;
  const t = f / fps;
  const landed = f >= GAUGE.land * S;
  const amp = (3 + (landed ? 7 * Math.exp(-(f - GAUGE.land * S) / (9 * S)) : 3 * (1 - rise))) * k;
  const crest: string[] = [];
  for (let i = 0; i <= 40; i++) {
    const x = vx + (vw * i) / 40;
    const y = surface + Math.sin(i * 0.55 + t * 3.0) * amp + Math.sin(i * 0.23 - t * 1.7) * amp * 0.5;
    crest.push(`${x.toFixed(1)} ${y.toFixed(1)}`);
  }
  const water = `M${vx} ${vb + 20 * k} L${crest.join(" L")} L${vx + vw} ${vb + 20 * k} Z`;
  const cmp = d.compare && Number.isFinite(Number(d.compare.value)) ? Number(d.compare.value) : null;
  const cmpY = cmp !== null ? vb - vh * clamp01(cmp / 100) : 0;
  const cmpP = inOf(f, 30 * S, 12 * S);
  const cmpText = cmp !== null ? `${String(d.compare?.label || "").toUpperCase()} · ${fmtVal(cmp, dec)}%` : "";
  const landP = inOf(f, GAUGE.land * S, 14 * S);
  const numText = fmtVal(Number((pct * rise).toFixed(dec)), dec);
  const finalText = fmtVal(pct, dec);
  const rx = vx + vw + 190 * kw;
  const size = Math.min(210 * k, (width - rx - 120 * kw) / Math.max(1, figureWidth(finalText, "%", 1)));
  const numTop = vt + vh * 0.5 - size * 0.86;
  const storage = d.storage && Number.isFinite(Number(d.storage.value)) && Number.isFinite(Number(d.storage.capacity))
    ? `${fmtVal(Number(d.storage.value), 2)} OF ${fmtVal(Number(d.storage.capacity), 2)} MILLION ACRE-FEET` : "";
  const ticks = [0, 25, 50, 75, 100];
  return (
    <AbsoluteFill>
      {sound}
      <Stage ov={overlay} p={inOf(f, 0, 10 * S) * (1 - out)} />
      <AbsoluteFill style={{ opacity: 1 - out, transform: `translateY(${(-out * 16 * k).toFixed(1)}px)` }}>
        <svg width={width} height={height} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          <defs>
            <clipPath id={`${id}c`}><rect x={vx} y={vt} width={vw} height={vh} rx={r} /></clipPath>
            <linearGradient id={`${id}w`} x1="0" y1={vt} x2="0" y2={vb} gradientUnits="userSpaceOnUse">
              <stop offset="0" stopColor={WATER_TOP} />
              <stop offset="0.35" stopColor={WATER_MID} />
              <stop offset="1" stopColor={WATER_DEEP} />
            </linearGradient>
            <linearGradient id={`${id}glass`} x1={vx} y1="0" x2={vx + vw} y2="0" gradientUnits="userSpaceOnUse">
              <stop offset="0" stopColor="rgba(255,255,255,.10)" />
              <stop offset="0.18" stopColor="rgba(255,255,255,.02)" />
              <stop offset="0.82" stopColor="rgba(255,255,255,.02)" />
              <stop offset="1" stopColor="rgba(255,255,255,.08)" />
            </linearGradient>
          </defs>
          <rect x={vx} y={vt} width={vw} height={vh} rx={r} fill="rgba(6,10,16,.55)" opacity={drawP} />
          {/* a measuring glass's graduations inside, every 5%, the quarters longest */}
          {Array.from({ length: 19 }, (_, i) => (i + 1) * 5).map((g) => (
            <line key={`g${g}`} x1={vx + vw - (g % 25 === 0 ? 74 : g % 10 === 0 ? 46 : 30) * k} x2={vx + vw - 14 * k}
              y1={vb - vh * (g / 100)} y2={vb - vh * (g / 100)} stroke={`rgba(255,255,255,${g % 25 === 0 ? 0.22 : 0.13})`}
              strokeWidth={1.6 * k} opacity={drawP} />
          ))}
          <g clipPath={`url(#${id}c)`}>
            {level > 0.001 ? <path d={water} fill={`url(#${id}w)`} opacity={0.96} /> : null}
            {level > 0.001 ? <path d={`M${crest.join(" L")}`} fill="none" stroke="rgba(214,240,255,.95)" strokeWidth={3 * k} /> : null}
          </g>
          <rect x={vx} y={vt} width={vw} height={vh} rx={r} fill={`url(#${id}glass)`} opacity={drawP} />
          <rect x={vx} y={vt} width={vw} height={vh} rx={r} fill="none" stroke="rgba(255,255,255,.78)" strokeWidth={2.6 * k}
            strokeDasharray={2 * (vw + vh)} strokeDashoffset={2 * (vw + vh) * (1 - drawP)} />
          {ticks.map((tk, i) => {
            const y = vb - vh * (tk / 100);
            const p = inOf(f, (4 + i * 2) * S, 12 * S);
            return (
              <g key={i} opacity={p}>
                <line x1={vx + vw + 12 * k} x2={vx + vw + (tk % 50 === 0 ? 36 : 26) * k} y1={y} y2={y}
                  stroke="rgba(255,255,255,.6)" strokeWidth={2.2 * k} />
                <text x={vx + vw + 46 * k} y={y + 8 * k} fill={SOFT}
                  style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: 22 * k, letterSpacing: "0.06em" }}>{`${tk}%`}</text>
              </g>
            );
          })}
          {cmp !== null ? (
            <line x1={vx - 26 * k} x2={vx + vw} y1={cmpY} y2={cmpY} stroke="rgba(255,255,255,.85)" strokeWidth={2.2 * k}
              strokeDasharray={`${10 * k} ${8 * k}`} opacity={cmpP} />
          ) : null}
        </svg>
        {cmp !== null ? (
          <div style={{ position: "absolute", right: width - vx + 40 * k, top: cmpY - 14 * k, opacity: cmpP }}>
            <span style={{ ...caps(21 * k, WHITE, 0.12), opacity: 0.86, textShadow: lift(k, 0.7) }}>{cmpText}</span>
          </div>
        ) : null}
        <div style={{ position: "absolute", left: rx, top: numTop, opacity: inOf(f, GAUGE.riseAt * S, 8 * S) }}>
          <Figure text={landed ? finalText : numText} unit="%" size={size} unitColor={hot} style={{ textShadow: lift(k, 0.6) }} />
          <div style={{ ...caps(34 * k, WHITE, 0.16), marginTop: 18 * k, opacity: landP, textShadow: lift(k, 0.6) }}>FULL</div>
          {storage ? (
            <div style={{ ...caps(22 * k, SOFT, 0.12), marginTop: 16 * k, opacity: landP, textShadow: lift(k, 0.6) }}>{storage}</div>
          ) : null}
          <div style={{ ...caps(22 * k, mixHex(hot, "#ffffff", 0.25), 0.14), marginTop: 12 * k, opacity: landP, textShadow: lift(k, 0.6) }}>
            {clipText(String(d.latest?.label || d.asOfLabel || "").toUpperCase(), 28)}
          </div>
        </div>
      </AbsoluteFill>
      <TitleBlock ov={overlay} d={d} accent={accent} out={out} chip={d.delta?.text} chipAt={GAUGE.land + 6} />
      <SourceCorner d={d} accent={accent} />
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "rd-line": guard(RdLine),
  "rd-number": guard(RdNumber),
  "rd-bars": guard(RdBars),
  "rd-gauge": guard(RdGauge),
};
