import React from "react";
import { AbsoluteFill, interpolate, random } from "remotion";
import { TEXT_SHADOW, formatNumber, useOverlayAnim, useScale } from "./layout";
import { INTER, NARROW, SERIF_ITALIC } from "./fonts";
import { ICONS } from "./DataGraphics";
import type { Overlay, OverlayItem } from "../types";

/**
 * Broadcast data graphics, each with several looks (overlay.variant):
 *   donut          donut | pie | gauge | rings        a share or a breakdown
 *   area-chart     area | step | glow | bars          a trend over 3+ points
 *   progress-bar   bar | tank | battery | thermometer | segments | circle-fill
 *   icon-array     any icon-pop pictogram             "7 in 10", "40%"
 *   ranking        list | bars | podium               ordered places
 *   counter        split | arrow | drop               a number then vs now
 *   number-roll    odometer | stamp | ticker | glitch one number landing
 *   trend          (up/down from the sign)            a % change
 *   year-roll      (years rolling A -> B)             a span of years
 *   banner         breaking | alert | update | live   a news strip
 *   scale-compare  circles | squares | columns        sizes side by side
 * Every value drawn comes from the plan, which copies it from the narration.
 */

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const ease = (frame: number, at: number, frames: number) =>
  interpolate(frame, [at, at + Math.max(1, frames)], [0, 1], {
    ...clamp,
    easing: (t) => 1 - Math.pow(1 - t, 3),
  });
const SHADE = "rgba(8,9,12,0.84)";
const INK = "#f4f1ea";
const DIM = "rgba(255,255,255,0.14)";
const RED = "#e63946";
const GREEN = "#2ec27e";
const PALETTE = (accent: string) => [accent || RED, INK, "#8d99ae", "#e9c46a", "#2a9d8f"];

type P = { overlay: Overlay; accent: string };
const numbered = (items?: OverlayItem[]) =>
  (items || []).filter((i) => typeof i.value === "number" && Number.isFinite(i.value)) as
    (OverlayItem & { value: number })[];
const pct = (v?: number) => Math.max(0, Math.min(100, v ?? 0));

const Heading: React.FC<{ text: string; s: (n: number) => number; show: number; size?: number }> = ({ text, s, show, size = 44 }) =>
  text ? (
    <div style={{ fontFamily: NARROW, fontWeight: 700, fontSize: s(size), letterSpacing: "0.05em",
      color: INK, textTransform: "uppercase", textShadow: TEXT_SHADOW, textAlign: "center",
      maxWidth: "80%", opacity: show, transform: `translateY(${(1 - show) * s(24)}px)` }}>{text}</div>
  ) : null;

// --------------------------------------------------------------------------- donut
export const Donut: React.FC<P> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(10, 10);
  const s = useScale();
  const v = overlay.variant || "donut";
  const items = numbered(overlay.items).filter((i) => i.value > 0).slice(0, 5);
  const single = items.length < 2;
  const colors = PALETTE(accent);
  const grow = ease(frame, fps * 0.2, fps * 1.4);
  const R = 190;
  const share = single ? [pct(overlay.value)] : items.map((i) => i.value);
  const total = single ? 100 : share.reduce((a, b) => a + b, 0) || 1;
  const half = v === "gauge";
  const C = 2 * Math.PI * R;
  const arcLen = half ? C / 2 : C;
  let run = 0;
  const segs = share.map((val, k) => {
    const len = (val / total) * arcLen * grow;
    const seg = { k, len, start: run };
    run += (val / total) * arcLen * grow;
    return seg;
  });
  const centre = single ? `${formatNumber(pct(overlay.value) * grow)}%` : "";
  const width = v === "pie" ? R : 58;
  const r = v === "pie" ? R / 2 : R;
  const Cr = 2 * Math.PI * r;
  const scaleLen = Cr / C;
  return (
    <AbsoluteFill style={{ opacity, background: SHADE, alignItems: "center", justifyContent: "center",
      flexDirection: "row", gap: s(90) }}>
      <div style={{ position: "relative", width: s(480), height: s(half ? 300 : 480) }}>
        {v === "rings" ? (
          <svg width={s(480)} height={s(480)} viewBox="-240 -240 480 480">
            {share.map((val, k) => {
              const rr = R - k * 46;
              const cc = 2 * Math.PI * rr;
              const max = single ? 100 : Math.max(100, ...share);
              const g = ease(frame, fps * (0.2 + k * 0.15), fps * 1.2);
              return (
                <g key={k} transform="rotate(-90)">
                  <circle r={rr} fill="none" stroke={DIM} strokeWidth={30} />
                  <circle r={rr} fill="none" stroke={colors[k]} strokeWidth={30} strokeLinecap="round"
                    strokeDasharray={`${(val / max) * cc * g} ${cc}`} />
                </g>
              );
            })}
          </svg>
        ) : (
          <svg width={s(480)} height={s(half ? 300 : 480)} viewBox={half ? "-240 -240 480 300" : "-240 -240 480 480"}>
            <g transform={half ? "rotate(180)" : "rotate(-90)"}>
              <circle r={r} fill="none" stroke={DIM} strokeWidth={width}
                strokeDasharray={half ? `${Cr / 2} ${Cr}` : undefined} />
              {segs.map(({ k, len, start }) => (
                <circle key={k} r={r} fill="none" stroke={single && k === 0 ? colors[0] : colors[k]}
                  strokeWidth={width} strokeDasharray={`${len * scaleLen} ${Cr}`}
                  strokeDashoffset={-start * scaleLen} />
              ))}
            </g>
          </svg>
        )}
        {single && v !== "pie" ? (
          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: half ? "flex-end" : "center",
            justifyContent: "center", paddingBottom: half ? s(20) : 0, fontFamily: NARROW, fontWeight: 700,
            fontSize: s(half ? 110 : 120), color: INK }}>{centre}</div>
        ) : null}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: s(22), maxWidth: s(760) }}>
        <div style={{ fontFamily: NARROW, fontWeight: 700, fontSize: s(single ? 58 : 46), color: INK,
          textTransform: "uppercase", lineHeight: 1.05, textShadow: TEXT_SHADOW,
          opacity: ease(frame, fps * 0.3, fps * 0.5) }}>{overlay.text}</div>
        {!single && items.map((it, k) => (
          <div key={k} style={{ display: "flex", alignItems: "center", gap: s(18),
            opacity: ease(frame, fps * (0.5 + k * 0.15), fps * 0.4) }}>
            <div style={{ width: s(26), height: s(26), borderRadius: s(6), background: colors[k] }} />
            <div style={{ fontFamily: INTER, fontSize: s(34), color: INK }}>
              {it.label} <b style={{ marginLeft: s(8) }}>{formatNumber(it.value)}{overlay.suffix || ""}</b>
            </div>
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};

// --------------------------------------------------------------------------- area chart
export const AreaChart: React.FC<P> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(10, 10);
  const s = useScale();
  const v = overlay.variant || "area";
  const pts = numbered(overlay.items).slice(0, 12);
  const W = 1400, H = 500;
  const vals = pts.map((p) => p.value);
  const lo = Math.min(0, ...vals), hi = Math.max(...vals, 1);
  const x = (i: number) => (i / Math.max(1, pts.length - 1)) * W;
  const y = (val: number) => H - ((val - lo) / (hi - lo || 1)) * H;
  const draw = ease(frame, fps * 0.3, fps * 1.6);
  const col = v === "glow" ? "#35e0ff" : accent || RED;
  let line = "";
  pts.forEach((p, i) => {
    if (!i) line += `M ${x(0)} ${y(p.value)}`;
    else if (v === "step") line += ` H ${x(i)} V ${y(p.value)}`;
    else line += ` L ${x(i)} ${y(p.value)}`;
  });
  const area = `${line} L ${W} ${H} L 0 ${H} Z`;
  const barW = (W / Math.max(1, pts.length)) * 0.55;
  return (
    <AbsoluteFill style={{ opacity, background: v === "glow" ? "rgba(3,8,18,0.9)" : SHADE,
      alignItems: "center", justifyContent: "center", gap: s(30) }}>
      <Heading text={overlay.text} s={s} show={ease(frame, 0, fps * 0.5)} />
      <svg width={s(W + 120)} height={s(H + 110)} viewBox={`-60 -60 ${W + 120} ${H + 110}`}>
        <defs>
          <linearGradient id="ag" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor={col} stopOpacity={0.55} />
            <stop offset="1" stopColor={col} stopOpacity={0.02} />
          </linearGradient>
          <clipPath id="reveal"><rect x={-60} y={-60} width={(W + 120) * draw} height={H + 120} /></clipPath>
          <filter id="glow"><feGaussianBlur stdDeviation="8" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
        </defs>
        {[0.25, 0.5, 0.75].map((f) => (
          <line key={f} x1={0} x2={W} y1={H * f} y2={H * f} stroke="rgba(255,255,255,.08)" strokeWidth={2} />
        ))}
        <line x1={0} y1={H} x2={W} y2={H} stroke="rgba(255,255,255,.35)" strokeWidth={2} />
        {v === "bars" && pts.map((p, i) => {
          const g = ease(frame, fps * (0.2 + i * 0.08), fps * 0.6);
          return <rect key={i} x={x(i) - barW / 2} y={H - (H - y(p.value)) * g} width={barW}
            height={(H - y(p.value)) * g} fill="rgba(255,255,255,.18)" rx={6} />;
        })}
        <g clipPath="url(#reveal)">
          {v !== "bars" && <path d={area} fill="url(#ag)" />}
          <path d={line} fill="none" stroke={col} strokeWidth={6} strokeLinejoin="round"
            filter={v === "glow" ? "url(#glow)" : undefined} />
          {pts.map((p, i) => (
            <circle key={i} cx={x(i)} cy={y(p.value)} r={9} fill={INK} stroke={col} strokeWidth={4} />
          ))}
        </g>
        {pts.map((p, i) => (
          <text key={i} x={x(i)} y={H + 40} fill="rgba(255,255,255,.75)" fontSize={26} fontFamily={INTER}
            textAnchor="middle" opacity={ease(frame, fps * 0.2 + i * 2, 6)}>{p.label}</text>
        ))}
        {pts.map((p, i) => {
          const at = (i / Math.max(1, pts.length - 1)) * 0.95;
          const show = interpolate(draw, [at, Math.min(1, at + 0.08)], [0, 1], clamp);
          return (i === 0 || i === pts.length - 1) ? (
            <text key={`v${i}`} x={x(i)} y={y(p.value) - 24} fill={INK} fontSize={40} fontFamily={NARROW}
              fontWeight={700} textAnchor={i ? "end" : "start"} opacity={show}>
              {formatNumber(p.value)}{overlay.suffix || ""}
            </text>
          ) : null;
        })}
      </svg>
    </AbsoluteFill>
  );
};

// --------------------------------------------------------------------------- progress
export const ProgressBar: React.FC<P> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(10, 10);
  const s = useScale();
  const v = overlay.variant || "bar";
  const target = pct(overlay.value);
  const g = ease(frame, fps * 0.25, fps * 1.6);
  const now = target * g;
  const col = accent || RED;
  const water = "#2f8fd8";
  const label = `${formatNumber(now)}${overlay.suffix ?? "%"}`;
  const wave = (w: number, h: number, level: number, amp: number) => {
    const top = h * (1 - level / 100);
    let d = `M 0 ${top}`;
    for (let xx = 0; xx <= w; xx += 10) d += ` L ${xx} ${top + Math.sin(xx / 38 + frame / 5) * amp}`;
    return `${d} L ${w} ${h} L 0 ${h} Z`;
  };
  let body: React.ReactNode;
  if (v === "tank" || v === "circle-fill") {
    const W = v === "tank" ? 340 : 420, H = v === "tank" ? 520 : 420;
    body = (
      <svg width={s(W + 20)} height={s(H + 20)} viewBox={`-10 -10 ${W + 20} ${H + 20}`}>
        <defs>
          <clipPath id="vessel">
            {v === "tank" ? <rect x={0} y={0} width={W} height={H} rx={28} /> : <circle cx={W / 2} cy={H / 2} r={W / 2} />}
          </clipPath>
        </defs>
        <g clipPath="url(#vessel)">
          <rect x={0} y={0} width={W} height={H} fill="rgba(255,255,255,.08)" />
          <path d={wave(W, H, now, 9)} fill={water} opacity={0.55} />
          <path d={wave(W, H, now - 1.5, 6)} fill={water} />
          {v === "tank" && [25, 50, 75].map((m) => (
            <g key={m}>
              <line x1={W - 50} x2={W} y1={H * (1 - m / 100)} y2={H * (1 - m / 100)} stroke="rgba(255,255,255,.6)" strokeWidth={3} />
              <text x={W - 58} y={H * (1 - m / 100) + 9} fill="rgba(255,255,255,.7)" fontSize={26} fontFamily={INTER} textAnchor="end">{m}%</text>
            </g>
          ))}
        </g>
        {v === "tank" ? <rect x={0} y={0} width={W} height={H} rx={28} fill="none" stroke={INK} strokeWidth={6} />
          : <circle cx={W / 2} cy={H / 2} r={W / 2} fill="none" stroke={INK} strokeWidth={6} />}
        {v === "circle-fill" ? (
          <text x={W / 2} y={H / 2 + 34} textAnchor="middle" fill="#fff" fontFamily={NARROW} fontWeight={700}
            fontSize={100} style={{ textShadow: TEXT_SHADOW }}>{label}</text>
        ) : null}
      </svg>
    );
  } else if (v === "thermometer") {
    const H = 520;
    body = (
      <svg width={s(220)} height={s(H + 140)} viewBox={`-110 -20 220 ${H + 140}`}>
        <rect x={-34} y={0} width={68} height={H} rx={34} fill="rgba(255,255,255,.1)" stroke={INK} strokeWidth={5} />
        <circle cx={0} cy={H + 50} r={62} fill={col} stroke={INK} strokeWidth={5} />
        <rect x={-20} y={H * (1 - now / 100)} width={40} height={H * (now / 100) + 30} fill={col} />
      </svg>
    );
  } else if (v === "battery") {
    const cells = 5;
    body = (
      <svg width={s(640)} height={s(300)} viewBox="-10 -10 640 300">
        <rect x={0} y={0} width={580} height={280} rx={30} fill="none" stroke={INK} strokeWidth={10} />
        <rect x={588} y={90} width={32} height={100} rx={8} fill={INK} />
        {Array.from({ length: cells }).map((_, k) => {
          const on = now / 100 * cells > k + 0.5;
          return <rect key={k} x={24 + k * 108} y={24} width={96} height={232} rx={12}
            fill={on ? (target < 30 ? RED : GREEN) : "rgba(255,255,255,.08)"} />;
        })}
      </svg>
    );
  } else if (v === "segments") {
    body = (
      <div style={{ display: "flex", gap: s(12) }}>
        {Array.from({ length: 10 }).map((_, k) => (
          <div key={k} style={{ width: s(96), height: s(150), borderRadius: s(10),
            background: now / 10 > k + 0.5 ? col : "rgba(255,255,255,.1)",
            transform: `scaleY(${now / 10 > k + 0.5 ? 1 : 0.8})` }} />
        ))}
      </div>
    );
  } else {
    body = (
      <div style={{ width: s(1300), height: s(70), borderRadius: s(35), background: "rgba(255,255,255,.1)",
        border: `${s(4)}px solid rgba(255,255,255,.5)`, overflow: "hidden" }}>
        <div style={{ width: `${now}%`, height: "100%", background: `linear-gradient(90deg, ${col}, ${col}cc)`,
          borderRadius: s(35) }} />
      </div>
    );
  }
  const showNumber = v !== "circle-fill";
  return (
    <AbsoluteFill style={{ opacity, background: SHADE, alignItems: "center", justifyContent: "center", gap: s(36) }}>
      <Heading text={overlay.text} s={s} show={ease(frame, 0, fps * 0.5)} size={50} />
      {body}
      {showNumber ? (
        <div style={{ fontFamily: NARROW, fontWeight: 700, fontSize: s(96), color: INK, textShadow: TEXT_SHADOW }}>{label}</div>
      ) : null}
      {overlay.subtitle ? (
        <div style={{ fontFamily: INTER, fontSize: s(32), color: "rgba(255,255,255,.75)" }}>{overlay.subtitle}</div>
      ) : null}
    </AbsoluteFill>
  );
};

// --------------------------------------------------------------------------- icon array
export const IconArray: React.FC<P> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(10, 10);
  const s = useScale();
  // One figure per person reads as a headcount; the two-figure pictogram does not.
  const PERSON = "M32 6a9 9 0 1 1 0 18a9 9 0 1 1 0-18 M14 58c0-16 8-28 18-28s18 12 18 28z";
  const icon = !overlay.variant || overlay.variant === "people" ? PERSON : ICONS[overlay.variant] || PERSON;
  const value = Math.max(0, overlay.value ?? 0);
  const hundred = value > 10 || overlay.suffix === "%";
  const n = hundred ? 100 : 10;
  const lit = Math.round(hundred ? Math.min(100, value) : Math.min(10, value));
  const size = hundred ? 58 : 130;
  const cols = hundred ? 20 : 10;
  const per = hundred ? 1.6 : 4;
  return (
    <AbsoluteFill style={{ opacity, background: SHADE, alignItems: "center", justifyContent: "center", gap: s(40) }}>
      <div style={{ fontFamily: NARROW, fontWeight: 700, fontSize: s(110), color: accent || RED, textShadow: TEXT_SHADOW }}>
        {hundred ? `${formatNumber(value)}%` : `${lit} IN 10`}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${cols}, ${s(size)}px)`, gap: s(hundred ? 8 : 20) }}>
        {Array.from({ length: n }).map((_, k) => {
          const on = k < lit;
          const show = ease(frame, fps * 0.2 + k * (per / (hundred ? 4 : 1)), fps * 0.25);
          return (
            <svg key={k} width={s(size)} height={s(size)} viewBox="0 0 64 64"
              style={{ transform: `scale(${0.6 + 0.4 * show})`, opacity: 0.3 + 0.7 * show }}>
              <path d={icon} fill={on ? accent || RED : "none"} stroke={on ? accent || RED : "rgba(255,255,255,.45)"}
                strokeWidth={3.5} strokeLinejoin="round" strokeLinecap="round" fillOpacity={on ? 0.35 : 0} />
            </svg>
          );
        })}
      </div>
      <Heading text={overlay.text} s={s} show={ease(frame, fps * 0.6, fps * 0.5)} size={46} />
    </AbsoluteFill>
  );
};

// --------------------------------------------------------------------------- ranking
export const Ranking: React.FC<P> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(10, 10);
  const s = useScale();
  const v = overlay.variant || "list";
  const items = (overlay.items || []).slice(0, 5);
  const vals = numbered(items);
  const max = Math.max(1, ...vals.map((i) => i.value));
  const col = accent || RED;
  if (v === "podium" && items.length >= 3) {
    const order = [1, 0, 2];
    const heights = [360, 460, 280];
    return (
      <AbsoluteFill style={{ opacity, background: SHADE, alignItems: "center", justifyContent: "center", gap: s(40) }}>
        <Heading text={overlay.text} s={s} show={ease(frame, 0, fps * 0.5)} />
        <div style={{ display: "flex", alignItems: "flex-end", gap: s(24) }}>
          {order.map((idx, k) => {
            const g = ease(frame, fps * (0.3 + k * 0.2), fps * 0.7);
            const it = items[idx];
            return (
              <div key={idx} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: s(14) }}>
                <div style={{ fontFamily: INTER, fontWeight: 700, fontSize: s(34), color: INK, opacity: g,
                  maxWidth: s(360), textAlign: "center" }}>{it.label || it.text}</div>
                <div style={{ width: s(340), height: s(heights[k] * g), background: idx === 0 ? col : "rgba(255,255,255,.22)",
                  borderRadius: `${s(12)}px ${s(12)}px 0 0`, display: "flex", justifyContent: "center",
                  fontFamily: NARROW, fontWeight: 700, fontSize: s(110), color: "#fff", paddingTop: s(12) }}>{idx + 1}</div>
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill style={{ opacity, background: SHADE, alignItems: "center", justifyContent: "center", gap: s(34) }}>
      <Heading text={overlay.text} s={s} show={ease(frame, 0, fps * 0.5)} />
      <div style={{ display: "flex", flexDirection: "column", gap: s(18), width: s(1200) }}>
        {items.map((it, k) => {
          const g = ease(frame, fps * (0.25 + k * 0.18), fps * 0.5);
          const val = typeof it.value === "number" ? it.value : undefined;
          return (
            <div key={k} style={{ display: "flex", alignItems: "center", gap: s(26), opacity: g,
              transform: `translateX(${(1 - g) * -s(120)}px)` }}>
              <div style={{ width: s(86), height: s(86), borderRadius: s(12), background: k === 0 ? col : "rgba(255,255,255,.14)",
                display: "flex", alignItems: "center", justifyContent: "center", fontFamily: NARROW,
                fontWeight: 700, fontSize: s(56), color: "#fff" }}>{k + 1}</div>
              <div style={{ flex: 1, position: "relative", height: s(86), display: "flex", alignItems: "center" }}>
                {v === "bars" && val !== undefined ? (
                  <div style={{ position: "absolute", left: 0, top: s(8), bottom: s(8), borderRadius: s(8),
                    width: `${(val / max) * 100 * g}%`, background: k === 0 ? `${col}aa` : "rgba(255,255,255,.12)" }} />
                ) : null}
                <div style={{ position: "relative", paddingLeft: s(20), fontFamily: INTER, fontWeight: 600,
                  fontSize: s(42), color: INK }}>{it.label || it.text}</div>
              </div>
              {val !== undefined ? (
                <div style={{ fontFamily: NARROW, fontWeight: 700, fontSize: s(52), color: INK }}>
                  {formatNumber(val * g)}{overlay.suffix || ""}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// --------------------------------------------------------------------------- counter
export const Counter: React.FC<P> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(10, 10);
  const s = useScale();
  const v = overlay.variant || "split";
  const [a, b] = numbered(overlay.items);
  if (!a || !b) return null;
  const change = a.value ? ((b.value - a.value) / Math.abs(a.value)) * 100 : 0;
  const down = b.value < a.value;
  const tone = down ? RED : GREEN;
  const suf = overlay.suffix || "";
  const g1 = ease(frame, fps * 0.2, fps * 0.9);
  const g2 = ease(frame, fps * 0.9, fps * 1.1);
  const pill = (
    <div style={{ fontFamily: INTER, fontWeight: 800, fontSize: s(38), color: "#fff", background: tone,
      borderRadius: s(40), padding: `${s(8)}px ${s(28)}px`, opacity: g2 }}>
      {down ? "▼" : "▲"} {formatNumber(Math.abs(change))}%
    </div>
  );
  if (v === "drop") {
    const now = interpolate(g2, [0, 1], [a.value, b.value]);
    return (
      <AbsoluteFill style={{ opacity, background: SHADE, alignItems: "center", justifyContent: "center", gap: s(26) }}>
        <Heading text={overlay.text} s={s} show={g1} />
        <div style={{ fontFamily: NARROW, fontWeight: 700, fontSize: s(220), lineHeight: 1,
          color: g2 > 0.02 ? tone : INK, textShadow: TEXT_SHADOW }}>{formatNumber(now)}{suf}</div>
        <div style={{ fontFamily: INTER, fontSize: s(34), color: "rgba(255,255,255,.8)" }}>
          {a.label} {formatNumber(a.value)}{suf} → {b.label} {formatNumber(b.value)}{suf}
        </div>
        {pill}
      </AbsoluteFill>
    );
  }
  const col = (it: OverlayItem & { value: number }, g: number, hot: boolean) => (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: s(10), opacity: g,
      transform: `translateY(${(1 - g) * s(40)}px)` }}>
      <div style={{ fontFamily: INTER, fontWeight: 700, fontSize: s(38), letterSpacing: "0.08em",
        color: "rgba(255,255,255,.75)", textTransform: "uppercase" }}>{it.label}</div>
      <div style={{ fontFamily: NARROW, fontWeight: 700, fontSize: s(170), lineHeight: 1,
        color: hot ? tone : INK, textShadow: TEXT_SHADOW }}>{formatNumber(it.value * g)}{suf}</div>
    </div>
  );
  return (
    <AbsoluteFill style={{ opacity, background: SHADE, alignItems: "center", justifyContent: "center", gap: s(40) }}>
      <Heading text={overlay.text} s={s} show={g1} />
      <div style={{ display: "flex", alignItems: "center", gap: s(v === "arrow" ? 50 : 110) }}>
        {col(a, g1, false)}
        {v === "arrow" ? (
          <svg width={s(260)} height={s(120)} viewBox="0 0 260 120">
            <path d="M10 60 H220 M180 20 L230 60 L180 100" fill="none" stroke={tone} strokeWidth={14}
              strokeLinecap="round" strokeLinejoin="round" pathLength={1} strokeDasharray={1}
              strokeDashoffset={1 - ease(frame, fps * 0.6, fps * 0.5)} />
          </svg>
        ) : (
          <div style={{ width: s(4), height: s(260), background: "rgba(255,255,255,.35)" }} />
        )}
        {col(b, g2, true)}
      </div>
      {pill}
    </AbsoluteFill>
  );
};

// --------------------------------------------------------------------------- number roll
export const NumberRoll: React.FC<P> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(8, 10);
  const s = useScale();
  const v = overlay.variant || "ticker";
  const value = overlay.value ?? 0;
  const col = accent || RED;
  const g = ease(frame, fps * 0.15, fps * 1.3);
  const text = formatNumber(value);
  const big = s(200);
  let number: React.ReactNode;
  if (v === "odometer") {
    number = (
      <div style={{ display: "flex", fontFamily: NARROW, fontWeight: 700, fontSize: big, color: INK, lineHeight: 1 }}>
        {text.split("").map((ch, k) => {
          const d = parseInt(ch, 10);
          if (Number.isNaN(d)) return <span key={k}>{ch}</span>;
          const land = ease(frame, fps * (0.15 + k * 0.06), fps * 1.0);
          const pos = d + 20 * (1 - land);
          return (
            <div key={k} style={{ height: big, overflow: "hidden", width: "0.62em", position: "relative" }}>
              <div style={{ position: "absolute", top: -pos * big, left: 0, right: 0 }}>
                {Array.from({ length: 30 }).map((_, i) => (
                  <div key={i} style={{ height: big, textAlign: "center" }}>{i % 10}</div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    );
  } else if (v === "stamp") {
    const hit = ease(frame, 0, fps * 0.25);
    const shake = frame < fps * 0.45 ? (random(`st${frame}`) - 0.5) * s(14) * (1 - hit) : 0;
    number = (
      <div style={{ fontFamily: NARROW, fontWeight: 700, fontSize: big, color: col, lineHeight: 1,
        border: `${s(10)}px solid ${col}`, padding: `${s(10)}px ${s(40)}px`, borderRadius: s(14),
        transform: `rotate(-5deg) scale(${interpolate(hit, [0, 1], [2.6, 1])}) translate(${shake}px, ${shake}px)`,
        opacity: hit }}>{text}{overlay.suffix || ""}</div>
    );
  } else if (v === "glitch") {
    const jitter = frame < fps * 0.6 ? 1 - frame / (fps * 0.6) : 0;
    const off = (k: string) => (random(`${k}${Math.floor(frame / 2)}`) - 0.5) * s(40) * jitter;
    const base: React.CSSProperties = { position: "absolute", inset: 0, fontFamily: NARROW, fontWeight: 700,
      fontSize: big, lineHeight: 1, textAlign: "center" };
    number = (
      <div style={{ position: "relative", height: big, width: s(1200) }}>
        <div style={{ ...base, color: "#ff2a55", transform: `translate(${off("r")}px,${off("ry")}px)`, mixBlendMode: "screen" }}>{text}{overlay.suffix || ""}</div>
        <div style={{ ...base, color: "#20e3ff", transform: `translate(${off("b")}px,${off("by")}px)`, mixBlendMode: "screen" }}>{text}{overlay.suffix || ""}</div>
        <div style={{ ...base, color: INK, opacity: 1 - jitter * 0.6 }}>{text}{overlay.suffix || ""}</div>
      </div>
    );
  } else {
    number = (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
        <div style={{ fontFamily: NARROW, fontWeight: 700, fontSize: big, color: INK, lineHeight: 1 }}>
          {formatNumber(value * g)}{overlay.suffix || ""}
        </div>
        <div style={{ height: s(12), width: s(600) * g, background: col, borderRadius: s(6), marginTop: s(10) }} />
      </div>
    );
  }
  return (
    <AbsoluteFill style={{ opacity, background: SHADE, alignItems: "center", justifyContent: "center", gap: s(34) }}>
      {number}
      <Heading text={overlay.text} s={s} show={ease(frame, fps * 0.5, fps * 0.5)} size={50} />
    </AbsoluteFill>
  );
};

// --------------------------------------------------------------------------- trend
export const Trend: React.FC<P> = ({ overlay }) => {
  const { frame, fps, opacity } = useOverlayAnim(10, 10);
  const s = useScale();
  const value = overlay.value ?? 0;
  const up = value >= 0;
  const tone = overlay.variant === "neutral" ? "#e9c46a" : up ? GREEN : RED;
  const g = ease(frame, fps * 0.15, fps * 1.0);
  return (
    <AbsoluteFill style={{ opacity, background: SHADE, alignItems: "center", justifyContent: "center",
      flexDirection: "row", gap: s(60) }}>
      <svg width={s(300)} height={s(300)} viewBox="-150 -150 300 300"
        style={{ transform: `translateY(${(1 - g) * (up ? s(80) : -s(80))}px)` }}>
        <path d={up ? "M0 -130 L120 20 H45 V130 H-45 V20 H-120 Z" : "M0 130 L120 -20 H45 V-130 H-45 V-20 H-120 Z"}
          fill={tone} opacity={g} />
      </svg>
      <div style={{ display: "flex", flexDirection: "column", gap: s(10) }}>
        <div style={{ fontFamily: NARROW, fontWeight: 700, fontSize: s(200), lineHeight: 1, color: tone }}>
          {up ? "+" : "−"}{formatNumber(Math.abs(value) * g)}{overlay.suffix ?? "%"}
        </div>
        <div style={{ fontFamily: NARROW, fontWeight: 700, fontSize: s(52), color: INK, textTransform: "uppercase",
          maxWidth: s(900), opacity: ease(frame, fps * 0.5, fps * 0.4) }}>{overlay.text}</div>
      </div>
    </AbsoluteFill>
  );
};

// --------------------------------------------------------------------------- year roll
export const YearRoll: React.FC<P> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(8, 10);
  const s = useScale();
  const [a, b] = (overlay.items || []).map((i) => parseInt(String(i.label), 10));
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  const g = ease(frame, fps * 0.2, fps * 1.6);
  const year = Math.round(interpolate(g, [0, 1], [a, b]));
  return (
    <AbsoluteFill style={{ opacity, background: SHADE, alignItems: "center", justifyContent: "center", gap: s(24) }}>
      <div style={{ fontFamily: NARROW, fontWeight: 700, fontSize: s(260), lineHeight: 1, color: INK,
        letterSpacing: "0.02em", textShadow: TEXT_SHADOW }}>{year}</div>
      <div style={{ position: "relative", width: s(1000), height: s(8), background: "rgba(255,255,255,.2)", borderRadius: s(4) }}>
        <div style={{ width: `${g * 100}%`, height: "100%", background: accent || RED, borderRadius: s(4) }} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", width: s(1000), fontFamily: INTER,
        fontSize: s(30), color: "rgba(255,255,255,.7)" }}><span>{a}</span><span>{b}</span></div>
      <Heading text={overlay.text} s={s} show={ease(frame, fps * 0.6, fps * 0.5)} size={46} />
    </AbsoluteFill>
  );
};

// --------------------------------------------------------------------------- banner
export const Banner: React.FC<P> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(8, 10);
  const s = useScale();
  const v = overlay.variant || "breaking";
  const tag = { breaking: "BREAKING", alert: "ALERT", update: "UPDATE", live: "LIVE" }[v] || "BREAKING";
  const tagBg = v === "update" ? "#1e6fd9" : v === "alert" ? "#f4a100" : RED;
  const slide = ease(frame, 0, fps * 0.45);
  const textIn = ease(frame, fps * 0.3, fps * 0.45);
  const blink = v === "live" ? 0.4 + 0.6 * Math.abs(Math.sin(frame / 8)) : 1;
  return (
    <AbsoluteFill style={{ opacity }}>
      <div style={{ position: "absolute", left: s(70), top: s(80), display: "flex", alignItems: "stretch",
        transform: `translateX(${(1 - slide) * -s(900)}px)`, boxShadow: "0 18px 50px rgba(0,0,0,.55)" }}>
        <div style={{ background: tagBg, color: "#fff", fontFamily: INTER, fontWeight: 900, fontSize: s(40),
          letterSpacing: "0.1em", padding: `${s(16)}px ${s(30)}px`, display: "flex", alignItems: "center", gap: s(14) }}>
          {v === "live" ? <span style={{ width: s(22), height: s(22), borderRadius: "50%", background: "#fff", opacity: blink }} /> : null}
          {tag}
        </div>
        <div style={{ background: "rgba(250,250,247,.97)", color: "#111", fontFamily: NARROW, fontWeight: 700,
          fontSize: s(50), padding: `${s(12)}px ${s(34)}px`, maxWidth: s(1300), textTransform: "uppercase",
          clipPath: `inset(0 ${(1 - textIn) * 100}% 0 0)`, borderBottom: `${s(6)}px solid ${accent || tagBg}` }}>
          {overlay.text}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// --------------------------------------------------------------------------- scale compare
export const ScaleCompare: React.FC<P> = ({ overlay, accent }) => {
  const { frame, fps, opacity } = useOverlayAnim(10, 10);
  const s = useScale();
  const v = overlay.variant || "circles";
  const items = numbered(overlay.items).filter((i) => i.value > 0).slice(0, 2);
  if (items.length < 2) return null;
  const max = Math.max(...items.map((i) => i.value));
  const MAXPX = 460;
  const colors = [accent || RED, "#8d99ae"];
  return (
    <AbsoluteFill style={{ opacity, background: SHADE, alignItems: "center", justifyContent: "center", gap: s(40) }}>
      <Heading text={overlay.text} s={s} show={ease(frame, 0, fps * 0.5)} />
      <div style={{ display: "flex", alignItems: "flex-end", gap: s(120) }}>
        {items.map((it, k) => {
          const g = ease(frame, fps * (0.3 + k * 0.35), fps * 0.8);
          const f = v === "columns" ? it.value / max : Math.sqrt(it.value / max);
          const side = Math.max(8, MAXPX * f * g);
          return (
            <div key={k} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: s(18) }}>
              <div style={{ width: s(v === "columns" ? 200 : side), height: s(side), background: colors[k],
                borderRadius: v === "circles" ? "50%" : s(10), opacity: 0.9 }} />
              <div style={{ fontFamily: NARROW, fontWeight: 700, fontSize: s(64), color: INK }}>
                {formatNumber(it.value * g)}{overlay.suffix || ""}
              </div>
              <div style={{ fontFamily: INTER, fontSize: s(32), color: "rgba(255,255,255,.75)", maxWidth: s(520),
                textAlign: "center" }}>{it.label}</div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
