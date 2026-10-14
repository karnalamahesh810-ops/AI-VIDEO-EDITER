/**
 * The gaming video-essay pack (2026-10-15): the layer kind "game" of the motion-spec stage, measured frame by frame
 * from the owner's reference ("Why GTA 6 Is Making Driving HARD Again!", docs/style-refs/gta6_driving/catalogue.md).
 * Every variant draws in full-frame coordinates (the layer's x / y / w / h are shares of the frame):
 *
 *   kinetic  - big white words standing in the shot, one chunk at a time, each on its spoken time (a hard swap,
 *              3 frames in, or a soft left-to-right character fade); a chunk the planner stresses takes the accent
 *   boxed    - mono words each in a green-outlined dark box, typed on their spoken times ("you had")
 *   meter    - an Easy -> Hard pill: segmented fill sweeping green -> red, labels, a caption and a drawn arrow
 *   article  - a newspaper clipping in close-up: depth-of-field lines, one phrase highlighted yellow
 *   versus   - a split: a white divider drawn down the middle, two titles, the side being talked about lit,
 *              the other dimmed, a curved arrow when the talk switches sides
 *   board    - a cork-board chapter: map-textured board, a big chapter number, taped labels, polaroids that show
 *              the shot through them, red strings, a "?" card; out of black with a camera push
 *   curve    - a learning curve drawn over the footage, red turning green as it rises, its label fading in
 *   zone     - a glowing green outline drawn round a district (on the shot's own map, or a drawn dark game map)
 *   wire     - a wireframe box drawn edge by edge round the subject, a label laid on the ground plane
 *   formula  - chalk formulas and triangles floating in over the shot
 *   thumbs   - a green thumbs-up / red thumbs-down disc popping on each verdict
 *   manual   - an open game manual: aged pages, numbered sections written on their words, a red pen circle
 *   summary  - a dark summary card: a lead line with its highlight, bold-led bullets typed on
 *   neon     - a neon question box (pink / purple / cyan frame, palm, a title badge), the question typed on
 *   static   - a TV-static and colour-bars cut
 *   endline  - the last line: a small white line and a bold gold one on black
 *
 * Pure functions of (layer, t): no clock, no random source (rand() is seeded), no network.
 */
import React from "react";
import { INTER, TYPEWRITER } from "../fonts";
import { easeOf, rand, type Layer } from "./specMath";
import { styleFont } from "./styleFonts";

export interface GCtx { t: number; dur: number; W: number; H: number }

const c01 = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);
const pr = (lt: number, at: number, len: number, ease = "expoOut") => easeOf(ease)((lt - at) / Math.max(0.01, len));
const F = {
  poppins: () => styleFont("lib:Poppins") || INTER,
  mono: () => styleFont("lib:Space Mono") || TYPEWRITER,
  oswald: () => styleFont("lib:Oswald") || INTER,
  slab: () => styleFont("lib:Roboto Slab") || INTER,
  marker: () => styleFont("lib:Permanent Marker") || INTER,
  chalk: () => styleFont("lib:Caveat") || INTER,
};
const timesOf = (L: Layer, n: number, start = 0.2, gap = 0.45) =>
  Array.from({ length: n }, (_, i) => (typeof L.times?.[i] === "number" ? L.times![i] : start + i * gap));
const shadowTxt = (H: number, k = 1) =>
  `0 ${(0.004 * H * k).toFixed(1)}px ${(0.018 * H * k).toFixed(1)}px rgba(0,0,0,0.55), 0 0 ${(0.04 * H * k).toFixed(1)}px rgba(0,0,0,0.25)`;

/** Characters fading in left to right (the reference's soft type-on: ~0.2 s each, staggered). */
const CharFade: React.FC<{ text: string; lt: number; at: number; per?: number; len?: number; H: number }> = ({ text, lt, at, per, len = 0.22, H }) => {
  const step = per ?? Math.min(0.055, 0.7 / Math.max(1, text.length));
  return (
    <>
      {Array.from(text).map((ch, i) => {
        const p = c01((lt - at - i * step) / len);
        return (
          <span key={i} style={{ opacity: p, filter: p < 0.98 ? `blur(${((1 - p) * 0.006 * H).toFixed(2)}px)` : undefined, whiteSpace: "pre" }}>{ch}</span>
        );
      })}
    </>
  );
};

/** A curved hand-drawn arrow, drawn on over `len` seconds from `at`. */
const DrawnArrow: React.FC<{ d: string; head: [number, number, number]; lt: number; at: number; len: number; H: number; color?: string }> = ({ d, head, lt, at, len, H, color = "#ffffff" }) => {
  const p = pr(lt, at, len, "inOut");
  if (p <= 0) return null;
  const [hx, hy, ang] = head;
  const s = 0.022 * H;
  const hp = c01((p - 0.85) / 0.15);
  return (
    <g style={{ filter: `drop-shadow(0 ${(0.003 * H).toFixed(1)}px ${(0.006 * H).toFixed(1)}px rgba(0,0,0,0.5))` }}>
      <path d={d} pathLength={1} strokeDasharray={`${p} 1`} fill="none" stroke={color} strokeWidth={0.0042 * H} strokeLinecap="round" />
      <g transform={`translate(${hx} ${hy}) rotate(${ang})`} opacity={hp}>
        <path d={`M ${-s} ${-s * 0.7} L 0 0 L ${-s} ${s * 0.7}`} fill="none" stroke={color} strokeWidth={0.0042 * H} strokeLinecap="round" strokeLinejoin="round" />
      </g>
    </g>
  );
};

// ================================================================== kinetic words
const Kinetic: React.FC<{ L: Layer; c: GCtx }> = ({ L, c }) => {
  const { W, H } = c;
  const lt = c.t - L.from;
  const chunks = L.items || [];
  const at = timesOf(L, chunks.length, 0, 0.5);
  let i = -1;
  for (let k = 0; k < chunks.length; k++) if (lt >= at[k]) i = k;
  if (i < 0) return null;
  const word = chunks[i];
  const upper = word === word.toUpperCase() && /[A-Z]/.test(word);
  let size = (L.size || 0.13) * H * (upper ? 1.1 : 1);
  const est = word.length * 0.6 * size;
  if (est > 0.86 * W) size = (0.86 * W) / (word.length * 0.6);
  const life = Math.max(0.5, L.to - L.from);
  const dir = (L.seed || 0) % 2 ? -1 : 1;
  // The words stand in the scene: a slow track with the camera (the reference's words ride the footage).
  const x = L.x * W + dir * 0.012 * W * (lt / life);
  const y = L.y * H - 0.006 * H * (lt / life);
  const soft = L.label === "type";
  const pin = c01((lt - at[i]) / 0.06);
  const sc = 1 + 0.05 * (1 - pr(lt, at[i], 0.22));
  const hot = L.hi === i;
  return (
    <div style={{ position: "absolute", left: x, top: y, transform: `translate(-50%, -50%) scale(${sc.toFixed(4)})`,
      fontFamily: F.poppins(), fontWeight: 700, fontSize: size, lineHeight: 1, letterSpacing: "-0.01em",
      color: hot ? (L.emphColor || "#f2c94c") : (L.color || "#ffffff"), whiteSpace: "nowrap", textShadow: shadowTxt(H, size / (0.12 * H)),
      opacity: soft ? 1 : pin }}>
      {soft ? <CharFade text={word} lt={lt} at={at[i]} H={H} /> : word}
    </div>
  );
};

// ================================================================== boxed mono words
const Boxed: React.FC<{ L: Layer; c: GCtx }> = ({ L, c }) => {
  const { H } = c;
  const lt = c.t - L.from;
  const words = L.items || [];
  const at = timesOf(L, words.length, 0, 0.35);
  const size = (L.size || 0.07) * H;
  const green = L.fill || "#39e75f";
  return (
    <div style={{ position: "absolute", left: L.x * c.W, top: L.y * H, transform: "translateY(-50%)", display: "flex", gap: 0.016 * H }}>
      {words.map((w, i) => {
        const p = pr(lt, at[i], 0.14, "out");
        if (lt < at[i]) return null;
        const last = i === words.length - 1;
        const chars = Math.min(w.length, Math.floor((lt - at[i]) / 0.035) + 1);
        return (
          <div key={i} style={{ position: "relative", padding: `${0.008 * H}px ${0.016 * H}px`, background: "rgba(8,12,10,0.42)",
            clipPath: `inset(0 ${((1 - p) * 100).toFixed(1)}% 0 0)`, boxShadow: `0 0 ${0.012 * H}px ${green}55` }}>
            <div style={{ position: "absolute", inset: 0, border: `${0.0052 * H}px solid ${green}` }} />
            <span style={{ fontFamily: F.mono(), fontWeight: 700, fontSize: size, lineHeight: 1.05, color: last ? green : "#ffffff",
              textShadow: `0 0 ${0.01 * H}px rgba(0,0,0,0.6)`, whiteSpace: "pre" }}>
              {w.slice(0, chars)}<span style={{ opacity: 0 }}>{w.slice(chars)}</span>
            </span>
          </div>
        );
      })}
    </div>
  );
};

// ================================================================== difficulty meter
const METER_STOPS = ["#38f23a", "#a6f03a", "#ffd21f", "#ff8a1a", "#ff2a2a"];
const meterColor = (u: number) => {
  const k = Math.min(METER_STOPS.length - 2, Math.floor(u * (METER_STOPS.length - 1)));
  return METER_STOPS[u >= 0.999 ? METER_STOPS.length - 1 : k + (u * (METER_STOPS.length - 1) - k > 0.5 ? 1 : 0)];
};
const Meter: React.FC<{ L: Layer; c: GCtx }> = ({ L, c }) => {
  const { W, H } = c;
  const lt = c.t - L.from;
  const w = L.w * W, h = L.h * H, x = L.x * W - w / 2, y = L.y * H - h / 2;
  const target = c01((L.valueTo ?? 85) / 100);
  const fillStart = 0.28;
  const v = target * pr(lt, fillStart, L.bdur || 1.2, "inOut");
  const track = pr(lt, 0, 0.25, "out");
  const fw = Math.max(v > 0.002 ? h : 0, v * w);
  const end = meterColor(v);
  const seg = w / 26;
  const words = L.items || [];
  const wAt = timesOf(L, words.length, fillStart + 0.4, 0.3);
  const lab = { fontFamily: F.poppins(), fontWeight: 700, fontSize: 0.031 * H, color: "rgba(240,240,240,0.92)", textShadow: shadowTxt(H, 0.4) } as const;
  const capX = x + 0.01 * W, capY = y + h + 0.03 * H;
  const arrowAt = words.length ? wAt[words.length - 1] + 0.15 : (L.mid ?? 1.3);
  return (
    <>
      <div style={{ position: "absolute", left: x, top: y, width: w, height: h, borderRadius: h / 2, opacity: track,
        background: "rgba(38,40,44,0.55)", boxShadow: `inset 0 0 0 ${0.0015 * H}px rgba(255,255,255,0.08)` }} />
      <div style={{ position: "absolute", left: x, top: y, width: fw, height: h, borderRadius: h / 2, overflow: "hidden",
        opacity: track, filter: `drop-shadow(0 0 ${(0.018 * H).toFixed(1)}px ${end}aa)` }}>
        <div style={{ position: "absolute", left: 0, top: 0, width: w, height: h,
          background: `linear-gradient(90deg, ${METER_STOPS.join(", ")})` }} />
        <div style={{ position: "absolute", left: 0, top: 0, width: w, height: h,
          background: `repeating-linear-gradient(90deg, rgba(0,0,0,0) 0px, rgba(0,0,0,0) ${(seg - 0.0028 * H).toFixed(1)}px, rgba(0,0,0,0.32) ${(seg - 0.0028 * H).toFixed(1)}px, rgba(0,0,0,0.32) ${seg.toFixed(1)}px)` }} />
        <div style={{ position: "absolute", left: 0, top: 0, width: w, height: h * 0.5, background: "linear-gradient(180deg, rgba(255,255,255,0.32), rgba(255,255,255,0))" }} />
      </div>
      <div style={{ ...lab, position: "absolute", left: x + 0.012 * W, top: y - 0.05 * H, opacity: pr(lt, 0.25, 0.3) }}>{L.label || "Easy"}</div>
      <div style={{ ...lab, position: "absolute", left: x + w - 0.012 * W, top: y - 0.05 * H, transform: "translateX(-100%)",
        opacity: c01((v / Math.max(0.01, target) - 0.6) / 0.3) }}>{L.meta || "Hard"}</div>
      {words.length ? (
        <div style={{ position: "absolute", left: capX, top: capY, display: "flex", alignItems: "baseline", gap: 0.008 * W,
          fontFamily: F.poppins(), fontWeight: 700, color: "#ffffff", textShadow: shadowTxt(H, 0.5), whiteSpace: "nowrap" }}>
          {words.map((wd, i) => {
            const p = pr(lt, wAt[i], 0.25);
            const big = L.hi === i;
            return <span key={i} style={{ fontSize: (big ? 0.052 : 0.042) * H, opacity: p, transform: `translateY(${((1 - p) * 0.012 * H).toFixed(1)}px)`, display: "inline-block",
              textTransform: big ? "uppercase" : undefined }}>{wd}</span>;
          })}
        </div>
      ) : null}
      {L.text !== "arrow" ? null : (
        <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          <DrawnArrow lt={lt} at={arrowAt} len={0.45} H={H}
            d={`M ${x + w + 0.03 * W} ${y + 0.02 * H} C ${x + w + 0.075 * W} ${y + 0.09 * H}, ${x + w + 0.06 * W} ${y + 0.2 * H}, ${x + w + 0.0 * W} ${y + 0.24 * H}`}
            head={[x + w + 0.0 * W, y + 0.24 * H, 150]} />
        </svg>
      )}
    </>
  );
};

// ================================================================== article clipping
const Article: React.FC<{ L: Layer; c: GCtx }> = ({ L, c }) => {
  const { W, H } = c;
  const lt = c.t - L.from;
  const life = Math.max(0.5, L.to - L.from);
  const fs = (L.size || 0.1) * H;
  const lh = fs * 1.2;
  const other = L.items || [];
  const lines: { t: React.ReactNode; dy: number }[] = [];
  const above = other.slice(0, 2), below = other.slice(2, 5);
  above.forEach((t, i) => lines.push({ t, dy: -(above.length - i) }));
  const hp = pr(lt, L.mid ?? 0.5, 0.35);
  lines.push({ dy: 0, t: (
    <>
      {L.label ? <span>{L.label} </span> : null}
      <span style={{ position: "relative", display: "inline-block", padding: `0 ${0.012 * H}px` }}>
        <span style={{ position: "absolute", left: 0, top: "6%", bottom: "2%", width: `${(hp * 100).toFixed(1)}%`, background: L.fill || "#f4e22b" }} />
        <span style={{ position: "relative", color: "#141414" }}>{L.text}</span>
      </span>
      {L.meta ? <span> {L.meta}</span> : null}
    </>
  ) });
  below.forEach((t, i) => lines.push({ t, dy: i + 1 }));
  const push = 1.02 + 0.08 * (lt / life);
  const noise = `nz${(L.seed || 1) % 997}`;
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden", background: "#ece7dc", opacity: pr(lt, 0, 0.12, "out") }}>
      <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
        <filter id={noise}><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed={(L.seed || 1) % 50} />
          <feColorMatrix values="0 0 0 0 0.35  0 0 0 0 0.3  0 0 0 0 0.24  0 0 0 0.22 0" /></filter>
        <rect width={W} height={H} filter={`url(#${noise})`} />
        <path d={`M ${0.08 * W} ${-0.1 * H} Q ${0.32 * W} ${0.5 * H} ${0.2 * W} ${1.1 * H}`} stroke="rgba(120,105,80,0.18)" strokeWidth={0.004 * H} fill="none" />
        <radialGradient id={`${noise}v`}><stop offset="55%" stopColor="rgba(0,0,0,0)" /><stop offset="100%" stopColor="rgba(60,45,25,0.35)" /></radialGradient>
        <rect width={W} height={H} fill={`url(#${noise}v)`} />
      </svg>
      <div style={{ position: "absolute", left: 0.5 * W, top: 0.5 * H, transform: `translate(-50%, -50%) rotate(-1.6deg) scale(${push.toFixed(4)})`,
        transformOrigin: "50% 50%" }}>
        {lines.map((ln, i) => (
          <div key={i} style={{ position: "absolute", left: 0, top: ln.dy * lh, transform: "translate(-50%, -50%)", whiteSpace: "nowrap",
            fontFamily: F.oswald(), fontWeight: 700, fontSize: fs, lineHeight: 1.1, color: "#2a2723",
            filter: ln.dy ? `blur(${(Math.min(3, Math.abs(ln.dy)) * 0.0045 * H).toFixed(1)}px)` : undefined, opacity: ln.dy ? 0.85 : 1 }}>
            {ln.t}
          </div>
        ))}
      </div>
    </div>
  );
};

// ================================================================== versus split
const Versus: React.FC<{ L: Layer; c: GCtx }> = ({ L, c }) => {
  const { W, H } = c;
  const lt = c.t - L.from;
  const [tl, tr] = timesOf(L, 2, 0, 0.8);
  // The side being talked about is lit: the later of the two spoken times that has passed.
  const leftLit = lt < tr ? true : tl > tr && lt >= tl;
  const switchAt = Math.max(tl, tr);
  const sw = pr(lt, switchAt, 0.25, "out");
  const dimL = leftLit ? (lt >= switchAt && tl > tr ? 1 - sw : 0) : sw;
  const dimR = leftLit ? (lt >= switchAt && tl > tr ? sw : 1) : 1 - sw;
  const div = pr(lt, 0, 0.3, "out");
  // each title fits its half (a long name shrinks; the reference's "IV" / "VI" stand 0.16 of the frame tall)
  const fit = (s: string) => Math.min((L.size || 0.16) * H, (0.4 * W) / Math.max(1, s.length * 0.66));
  const t1 = pr(lt, 0.05, 0.3), t2 = pr(lt, 0.12, 0.3);
  const title = (txt: string, grad: boolean, p: number): React.CSSProperties => ({
    position: "absolute", top: 0.04 * H, transform: `translate(-50%, 0) scale(${(1.08 - 0.08 * p).toFixed(4)})`, opacity: p,
    fontFamily: F.slab(), fontWeight: 800, fontSize: fit(txt), lineHeight: 1, letterSpacing: "0.02em", whiteSpace: "nowrap",
    ...(grad ? { background: `linear-gradient(180deg, ${L.color2 && L.color2.startsWith("#") ? L.color2 : "#ff4fd8"}, ${L.emphColor || "#ff9a3c"})`, WebkitBackgroundClip: "text",
      backgroundClip: "text", color: "transparent", WebkitTextStroke: `${(0.004 * H).toFixed(1)}px #1a0a24` }
      : { color: "#111111", WebkitTextStroke: `${(0.006 * H).toFixed(1)}px #f2f2f2`, paintOrder: "stroke fill" }),
    filter: `drop-shadow(0 ${(0.006 * H).toFixed(1)}px ${(0.01 * H).toFixed(1)}px rgba(0,0,0,0.6))`,
  });
  const fromX = leftLit ? 0.68 * W : 0.32 * W, toX = leftLit ? 0.3 * W : 0.7 * W;
  const showArrow = switchAt > 0.3;
  return (
    <>
      <div style={{ position: "absolute", left: 0, top: 0, width: W / 2, height: H, background: "#000", opacity: 0.62 * dimL }} />
      <div style={{ position: "absolute", left: W / 2, top: 0, width: W / 2, height: H, background: "#000", opacity: 0.62 * dimR }} />
      <div style={{ position: "absolute", left: W / 2 - 0.002 * W, top: 0, width: 0.004 * W, height: H * div, background: "#ffffff",
        boxShadow: "0 0 8px rgba(0,0,0,0.5)" }} />
      <div style={{ ...title(L.label || "", false, t1), left: 0.25 * W, opacity: t1 * (1 - 0.55 * dimL) }}>{L.label}</div>
      <div style={{ ...title(L.meta || "", true, t2), left: 0.75 * W, opacity: t2 * (1 - 0.55 * dimR) }}>{L.meta}</div>
      {showArrow ? (
        <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          <DrawnArrow lt={lt} at={switchAt + 0.05} len={0.4} H={H}
            d={`M ${fromX} ${0.4 * H} Q ${0.5 * W} ${0.5 * H} ${toX} ${0.33 * H}`} head={[toX, 0.33 * H, leftLit ? 205 : -25]} />
        </svg>
      ) : null}
    </>
  );
};

// ================================================================== cork-board chapter
const Tape: React.FC<{ x: number; y: number; w: number; text: string; rot: number; seed: number; op?: number }> = ({ x, y, w, text, rot, seed, op = 1 }) => {
  const h = 46;
  const jag = (side: number) => Array.from({ length: 5 }, (_, i) => `${side + (rand(seed + i + side) - 0.5) * 8},${(i / 4) * h}`);
  const pts = [...jag(0), ...jag(w).reverse()].join(" ");
  return (
    <g transform={`translate(${x} ${y}) rotate(${rot})`} opacity={op}>
      <polygon points={pts} transform={`translate(${-w / 2} ${-h / 2})`} fill="#1c1c1c" />
      <text x={0} y={9} textAnchor="middle" fontFamily={TYPEWRITER} fontWeight={700} fontSize={26} fill="#ececec" letterSpacing={1}>{text.toUpperCase()}</text>
    </g>
  );
};
const Board: React.FC<{ L: Layer; c: GCtx }> = ({ L, c }) => {
  const { W, H } = c;
  const lt = c.t - L.from;
  const life = Math.max(0.5, L.to - L.from);
  const uid = React.useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const seed = L.seed || 1;
  const push = 0.8 + 0.2 * pr(lt, 0.05, 0.75) + 0.035 * (lt / life);
  const black = 1 - c01(lt / 0.35);
  const num = L.label || "1";
  const answer = L.meta || "THE ANSWER";
  const others = (L.items || []).filter((t) => t && t.toUpperCase() !== (L.text || "").toUpperCase()).slice(0, 2);
  // Polaroids: their photo windows are holes in the board (the shot shows through).
  const pols = [
    { x: 610, y: 470, w: 230, h: 200, r: -6, at: 0.25 },
    { x: 860, y: 450, w: 230, h: 200, r: 3, at: 0.33 },
    { x: 1110, y: 470, w: 200, h: 200, r: 7, at: 0.41 },
  ];
  const lines = Array.from({ length: 26 }, (_, i) => {
    const y0 = rand(seed * 7 + i) * 1080, amp = 30 + rand(seed + i * 3) * 80;
    return `M -50 ${y0.toFixed(0)} C 500 ${(y0 + amp).toFixed(0)}, 1300 ${(y0 - amp).toFixed(0)}, 1970 ${(y0 + amp * 0.4).toFixed(0)}`;
  });
  const pinPop = (at: number) => backOutLite(c01((lt - at) / 0.25));
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
      <svg viewBox="0 0 1920 1080" width={W} height={H} style={{ position: "absolute", inset: 0 }} preserveAspectRatio="xMidYMid slice">
        <defs>
          <radialGradient id={`${uid}g`} cx="45%" cy="45%" r="75%">
            <stop offset="0%" stopColor="#a47b49" /><stop offset="45%" stopColor="#6e5030" /><stop offset="100%" stopColor="#170f07" />
          </radialGradient>
          <radialGradient id={`${uid}w`} cx="42%" cy="40%" r="55%">
            <stop offset="0%" stopColor="#ffe2b0" stopOpacity={0.16} /><stop offset="100%" stopColor="#ffe2b0" stopOpacity={0} />
          </radialGradient>
          <filter id={`${uid}n`}><feTurbulence type="fractalNoise" baseFrequency="0.75" numOctaves="3" seed={seed % 90} />
            <feColorMatrix values="0 0 0 0 0.18  0 0 0 0 0.12  0 0 0 0 0.06  0 0 0 0.55 0" /></filter>
          <filter id={`${uid}s`} x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="8" stdDeviation="9" floodColor="#000" floodOpacity="0.55" /></filter>
          <mask id={`${uid}m`}>
            <rect x={-200} y={-200} width={2320} height={1480} fill="#fff" />
            {pols.map((p, i) => lt >= p.at ? (
              <rect key={i} x={-p.w / 2 + 14} y={-p.h / 2 + 14} width={p.w - 28} height={p.h - 62} fill="#000"
                transform={`translate(${p.x} ${p.y}) rotate(${p.r}) scale(${(1 + 0.12 * (1 - pr(lt, p.at, 0.35))).toFixed(3)})`} />
            ) : null)}
          </mask>
        </defs>
        <g transform={`translate(960 540) scale(${push.toFixed(4)}) translate(-960 -540)`}>
          <g mask={`url(#${uid}m)`}>
            <rect x={-200} y={-200} width={2320} height={1480} fill={`url(#${uid}g)`} />
            <rect x={-200} y={-200} width={2320} height={1480} filter={`url(#${uid}n)`} />
            {lines.map((d, i) => <path key={i} d={d} fill="none" stroke="#24170a" strokeOpacity={0.32} strokeWidth={i % 4 ? 1.8 : 3.4} />)}
            <rect x={-200} y={-200} width={2320} height={1480} fill={`url(#${uid}w)`} />
          </g>
          {/* the polaroid frames round their windows */}
          {pols.map((p, i) => {
            const pp = pr(lt, p.at, 0.35);
            if (lt < p.at) return null;
            return (
              <g key={i} transform={`translate(${p.x} ${p.y}) rotate(${p.r}) scale(${(1 + 0.12 * (1 - pp)).toFixed(3)})`} opacity={c01(pp * 1.6)} filter={`url(#${uid}s)`}>
                <path fillRule="evenodd" fill="#f3f0e8"
                  d={`M ${-p.w / 2} ${-p.h / 2} h ${p.w} v ${p.h} h ${-p.w} Z M ${-p.w / 2 + 14} ${-p.h / 2 + 14} v ${p.h - 62} h ${p.w - 28} v ${-(p.h - 62)} Z`} />
              </g>
            );
          })}
          {/* the big chapter number */}
          <text x={430} y={640} textAnchor="middle" fontFamily={INTER} fontWeight={400} fontSize={430} fill="#f1ede4"
            opacity={pr(lt, 0.35, 0.45) * 0.95} transform={`translate(${(-30 * (1 - pr(lt, 0.35, 0.5))).toFixed(1)} 0)`}
            style={{ filter: "drop-shadow(0 10px 18px rgba(0,0,0,0.5))" }}>{num}</text>
          {/* red strings to the answer */}
          {[[1220, 420], [880, 760]].map(([sx, sy], i) => (
            <path key={i} d={`M ${sx} ${sy} Q ${(sx + 1560) / 2} ${Math.max(sy, 560) + 60} 1560 ${560}`} fill="none" stroke="#b3262b" strokeWidth={3}
              pathLength={1} strokeDasharray={`${pr(lt, 0.6 + i * 0.1, 0.5, "inOut")} 1`} opacity={0.9} />
          ))}
          {/* the "?" card */}
          <g transform={`translate(1560 560) rotate(4) scale(${(0.9 + 0.1 * pinPop(0.5)).toFixed(3)})`} opacity={c01((lt - 0.5) / 0.2)} filter={`url(#${uid}s)`}>
            <rect x={-130} y={-150} width={260} height={300} fill="#f3f0e8" />
            <rect x={-114} y={-134} width={228} height={230} fill="#141414" />
            <text x={0} y={60} textAnchor="middle" fontFamily={F.poppins()} fontWeight={900} fontSize={200} fill="#f3f0e8">?</text>
          </g>
          <Tape x={1560} y={760} w={280} text={answer} rot={-3} seed={seed + 5} op={c01((lt - 0.6) / 0.2)} />
          <Tape x={860} y={300} w={Math.max(240, (L.text || "").length * 17 + 60)} text={L.text || ""} rot={-2} seed={seed + 1} op={c01((lt - 0.2) / 0.2)} />
          {others.map((t, i) => (
            <Tape key={i} x={i ? 1500 : 760} y={i ? 230 : 820} w={Math.max(220, t.length * 17 + 50)} text={t} rot={i ? 3 : 2} seed={seed + 9 + i}
              op={0.85 * c01((lt - 0.7 - i * 0.1) / 0.2)} />
          ))}
          {[[860, 270], [1560, 400], [760, 790]].map(([px, py], i) => (
            <g key={i} transform={`translate(${px} ${py}) scale(${pinPop(0.3 + i * 0.15).toFixed(3)})`}>
              <circle r={11} fill="#c62828" /><circle r={4} cx={-3} cy={-3} fill="#ff8a80" />
            </g>
          ))}
        </g>
        <rect width={1920} height={1080} fill="#000" opacity={black} />
      </svg>
    </div>
  );
};
const backOutLite = (t: number) => { const c1 = 1.4, c3 = c1 + 1; const x = c01(t) - 1; return 1 + c3 * x * x * x + c1 * x * x; };

// ================================================================== learning curve
const Curve: React.FC<{ L: Layer; c: GCtx }> = ({ L, c }) => {
  const { W, H } = c;
  const lt = c.t - L.from;
  const uid = React.useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const x0 = L.x * W, y0 = L.y * H, x1 = (L.x + L.w) * W, y1 = (L.y - L.h) * H;
  const pts = Array.from({ length: 41 }, (_, i) => {
    const u = i / 40;
    return `${(x0 + (x1 - x0) * u).toFixed(1)},${(y0 - (y0 - y1) * u ** 2.7).toFixed(1)}`;
  });
  const d = `M ${pts.join(" L ")}`;
  const p = pr(lt, 0.15, L.bdur || 1.1, "inOut");
  const u = p, hx = x0 + (x1 - x0) * u, hy = y0 - (y0 - y1) * u ** 2.7;
  const sw = 0.0065 * H;
  return (
    <>
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
        <defs>
          <linearGradient id={`${uid}c`} gradientUnits="userSpaceOnUse" x1={x0} y1={0} x2={x1} y2={0}>
            <stop offset="0%" stopColor={L.color2 && L.color2.startsWith("#") ? L.color2 : "#ff2b2b"} />
            <stop offset="48%" stopColor="#ff3b30" /><stop offset="62%" stopColor="#ffb21f" />
            <stop offset="74%" stopColor={L.fill || "#3dff4e"} /><stop offset="100%" stopColor={L.fill || "#3dff4e"} />
          </linearGradient>
          <filter id={`${uid}b`} x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation={0.007 * H} /></filter>
        </defs>
        <path d={d} pathLength={1} strokeDasharray={`${p} 1`} fill="none" stroke={`url(#${uid}c)`} strokeWidth={sw * 3} strokeLinecap="round" filter={`url(#${uid}b)`} opacity={0.75} />
        <path d={d} pathLength={1} strokeDasharray={`${p} 1`} fill="none" stroke={`url(#${uid}c)`} strokeWidth={sw} strokeLinecap="round" />
        {p > 0.01 && p < 0.995 ? <circle cx={hx} cy={hy} r={sw * 0.9} fill="#ffffff" opacity={0.9} /> : null}
      </svg>
      {L.text ? (
        <div style={{ position: "absolute", left: x0 + (x1 - x0) * 0.42, top: y1 + (y0 - y1) * 0.08, transform: "translate(-50%, -50%)",
          fontFamily: F.poppins(), fontWeight: 700, fontSize: (L.size || 0.045) * H, color: "#ffffff", textShadow: shadowTxt(H, 0.6), whiteSpace: "nowrap" }}>
          <CharFade text={L.text} lt={lt} at={0.35} H={H} />
        </div>
      ) : null}
    </>
  );
};

// ================================================================== glowing map zone
const blobPath = (cx: number, cy: number, rx: number, ry: number, seed: number) => {
  const n = 9;
  const p = Array.from({ length: n }, (_, i) => {
    const a = (i / n) * Math.PI * 2 + rand(seed) * 0.6;
    const k = 0.78 + rand(seed * 13 + i) * 0.4;
    return [cx + Math.cos(a) * rx * k, cy + Math.sin(a) * ry * k] as [number, number];
  });
  let d = `M ${p[0][0].toFixed(1)} ${p[0][1].toFixed(1)}`;
  for (let i = 0; i < n; i++) {
    const p0 = p[(i - 1 + n) % n], p1 = p[i], p2 = p[(i + 1) % n], p3 = p[(i + 2) % n];
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6], c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += ` C ${c1[0].toFixed(1)} ${c1[1].toFixed(1)}, ${c2[0].toFixed(1)} ${c2[1].toFixed(1)}, ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
  }
  return d;
};
const Zone: React.FC<{ L: Layer; c: GCtx }> = ({ L, c }) => {
  const { W, H } = c;
  const lt = c.t - L.from;
  const life = Math.max(0.5, L.to - L.from);
  const uid = React.useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const seed = L.seed || 3;
  const cx = L.x * W, cy = L.y * H, rx = (L.w * W) / 2, ry = (L.h * H) / 2;
  const d = blobPath(cx, cy, rx, ry, seed);
  const green = L.fill && L.fill.startsWith("#") ? L.fill : "#31ff45";
  const p = pr(lt, 0.1, L.bdur || 0.8, "inOut");
  const span = 0.66 * p;
  const map = L.label === "map";
  const zoom = 1 + 0.07 * (lt / life);
  return (
    <>
      {map ? <GameMap W={W} H={H} seed={seed} zoom={zoom} labels={L.items || []} lt={lt} /> : null}
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        <defs><filter id={`${uid}b`} x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation={0.012 * H} /></filter></defs>
        <g transform={`translate(${cx} ${cy}) scale(${map ? zoom : 1}) translate(${-cx} ${-cy})`}>
          <path d={d} fill={green} opacity={0.08 * c01((p - 0.7) / 0.3)} />
          <path d={d} pathLength={1} strokeDasharray={`${span} 1`} fill="none" stroke={green} strokeWidth={0.026 * H} strokeLinecap="round" filter={`url(#${uid}b)`} opacity={0.85} />
          <path d={d} pathLength={1} strokeDasharray={`${span} 1`} fill="none" stroke={green} strokeWidth={0.011 * H} strokeLinecap="round" />
          <path d={d} pathLength={1} strokeDasharray={`${span} 1`} fill="none" stroke="#d9ffdc" strokeWidth={0.003 * H} strokeLinecap="round" opacity={0.85} />
        </g>
      </svg>
      {L.text ? (
        <div style={{ position: "absolute", left: cx, top: cy - ry - 0.07 * H, transform: "translate(-50%, -50%)", whiteSpace: "nowrap",
          fontFamily: F.poppins(), fontWeight: 700, fontSize: (L.size || 0.1) * H, color: "#ffffff", textShadow: shadowTxt(H) }}>
          <CharFade text={L.text} lt={lt} at={0.35} per={0.07} len={0.25} H={H} />
        </div>
      ) : null}
    </>
  );
};
/** A dark game map drawn when the shot is not one: teal water, black land, outlined grey streets, district names. */
const GameMap: React.FC<{ W: number; H: number; seed: number; zoom: number; labels: string[]; lt: number }> = ({ W, H, seed, zoom, labels, lt }) => {
  const uid = React.useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const land = [
    blobPath(0.3 * W, 0.42 * H, 0.42 * W, 0.62 * H, seed + 1),
    blobPath(1.02 * W, 0.98 * H, 0.38 * W, 0.42 * H, seed + 2),
  ];
  const rot = -18 + rand(seed) * 12;
  const step = 0.055 * W;
  const roads: string[] = [];
  for (let i = -20; i <= 20; i++) roads.push(`M ${i * step} ${-H} L ${i * step} ${2 * H}`, `M ${-W} ${i * step * 0.8} L ${2 * W} ${i * step * 0.8}`);
  const spots = [[0.12, 0.2], [0.33, 0.12], [0.16, 0.62], [0.42, 0.3], [0.85, 0.82]];
  return (
    <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
      <defs><clipPath id={`${uid}l`}>{land.map((d, i) => <path key={i} d={d} />)}</clipPath></defs>
      <g transform={`translate(${W / 2} ${H / 2}) scale(${zoom}) translate(${-W / 2} ${-H / 2})`}>
        <rect width={W} height={H} fill="#3d6678" />
        {land.map((d, i) => <path key={i} d={d} fill="#0f1011" />)}
        <g clipPath={`url(#${uid}l)`} transform={`rotate(${rot} ${W / 2} ${H / 2})`}>
          {roads.map((d, i) => <path key={i} d={d} stroke="#5c6066" strokeWidth={0.011 * H} />)}
          {roads.map((d, i) => <path key={`i${i}`} d={d} stroke="#16181a" strokeWidth={0.006 * H} />)}
        </g>
        {labels.slice(0, 5).map((t, i) => (
          <text key={i} x={spots[i][0] * W} y={spots[i][1] * H} fill="#c9cdd2" fontFamily={F.poppins()} fontWeight={700} fontSize={0.019 * H}
            textAnchor="middle" opacity={c01((lt - 0.1 * i) / 0.3)} style={{ textTransform: "uppercase", letterSpacing: "0.04em" }}>{t.toUpperCase()}</text>
        ))}
      </g>
    </svg>
  );
};

// ================================================================== wireframe tracker
const Wire: React.FC<{ L: Layer; c: GCtx }> = ({ L, c }) => {
  const { W, H } = c;
  const lt = c.t - L.from;
  const uid = React.useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const green = L.fill && L.fill.startsWith("#") ? L.fill : "#3cff3c";
  const dir = (L.seed || 0) % 2 ? -1 : 1;
  const cx = L.x * W + Math.sin(lt * 1.3) * 0.006 * W, cy = L.y * H + Math.sin(lt * 1.7) * 0.004 * H;
  const fw = L.w * W, fh = L.h * H * 0.62;
  const f = [[cx - fw / 2, cy - fh / 2 + 0.25 * fh], [cx + fw / 2 - 0.12 * fw, cy - fh / 2 + 0.25 * fh], [cx + fw / 2 - 0.12 * fw, cy + fh / 2 + 0.25 * fh], [cx - fw / 2, cy + fh / 2 + 0.25 * fh]];
  const off = [dir * 0.3 * fw, -0.55 * fh];
  const b = f.map(([x, y]) => [x + off[0] + (x - cx) * -0.12, y + off[1] + (y - cy) * -0.12]);
  const edges: [number[], number[]][] = [
    [f[0], f[1]], [f[1], f[2]], [f[2], f[3]], [f[3], f[0]],
    [f[0], b[0]], [f[1], b[1]], [f[2], b[2]], [f[3], b[3]],
    [b[0], b[1]], [b[1], b[2]], [b[2], b[3]], [b[3], b[0]],
  ];
  const sw = 0.0034 * H;
  const lab = L.text || "";
  return (
    <>
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        <defs><filter id={`${uid}b`} x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation={0.004 * H} /></filter></defs>
        {[0, 1].map((pass) => (
          <g key={pass} filter={pass ? undefined : `url(#${uid}b)`} opacity={pass ? 1 : 0.8}>
            {edges.map(([a, z], i) => {
              const p = pr(lt, 0.1 + i * 0.035, 0.32, "out");
              if (p <= 0) return null;
              return <line key={i} x1={a[0]} y1={a[1]} x2={a[0] + (z[0] - a[0]) * p} y2={a[1] + (z[1] - a[1]) * p}
                stroke={green} strokeWidth={pass ? sw : sw * 2.6} strokeLinecap="round" />;
            })}
          </g>
        ))}
      </svg>
      {lab ? (
        <div style={{ position: "absolute", left: b[1][0] + dir * 0.02 * W, top: b[1][1] - 0.02 * H,
          transform: `translate(${dir > 0 ? "-30%" : "-70%"}, -100%) perspective(${(0.9 * H).toFixed(0)}px) rotateX(38deg) rotateZ(${(dir * 14).toFixed(1)}deg)`,
          fontFamily: F.poppins(), fontWeight: 800, fontSize: (L.size || 0.065) * H, color: "#ffffff", letterSpacing: "0.02em",
          textShadow: shadowTxt(H, 0.7), whiteSpace: "nowrap", textTransform: "uppercase" }}>
          <CharFade text={lab.toUpperCase()} lt={lt} at={0.45} per={0.04} len={0.25} H={H} />
        </div>
      ) : null}
    </>
  );
};

// ================================================================== floating formulas
const FORMULAS = ["x²", "(y+b)²", "A = ½bh", "√y / (x+2)", "x − y", "F = ma", "v²/r", "μ·g", "Δv = a·t", "θ", "(x)²", "Σ F", "y = ax²", "2√3"];
const Formula: React.FC<{ L: Layer; c: GCtx }> = ({ L, c }) => {
  const { W, H } = c;
  const lt = c.t - L.from;
  const seed = L.seed || 7;
  const list = (L.items && L.items.length ? L.items : FORMULAS).slice(0, 14);
  const chalk = L.color && L.color !== "#ffffff" ? L.color : "#f2ebc4";
  const items = list.map((t, i) => {
    let x = 0, y = 0;
    for (let k = 0; k < 8; k++) {
      x = 0.05 + rand(seed * 17 + i * 5 + k) * 0.9; y = 0.08 + rand(seed * 29 + i * 7 + k) * 0.84;
      if (((x - 0.5) / 0.22) ** 2 + ((y - 0.56) / 0.2) ** 2 > 1) break;
    }
    return { t, x, y, s: 0.035 + rand(seed + i * 11) * 0.045, r: (rand(seed * 3 + i) - 0.5) * 24, at: 0.05 + ((i * 7) % list.length) * 0.07, v: 1 + (i % 3) };
  });
  const tris = [0, 1, 2].map((i) => ({ x: 0.1 + rand(seed + 91 + i) * 0.8, y: 0.1 + rand(seed + 71 + i) * 0.35, s: 0.05 + rand(seed + i) * 0.04, at: 0.3 + i * 0.2 }));
  return (
    <>
      {items.map((m, i) => {
        const p = pr(lt, m.at, 0.6, "out");
        return (
          <div key={i} style={{ position: "absolute", left: m.x * W, top: m.y * H - lt * 0.006 * H * m.v, transform: `translate(-50%, -50%) rotate(${m.r.toFixed(1)}deg)`,
            fontFamily: F.chalk(), fontWeight: 700, fontSize: m.s * H, color: chalk, opacity: 0.8 * p, whiteSpace: "nowrap",
            filter: p < 0.97 ? `blur(${((1 - p) * 0.008 * H).toFixed(1)}px)` : undefined, textShadow: "0 0 6px rgba(0,0,0,0.35)" }}>{m.t}</div>
        );
      })}
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
        {tris.map((tr, i) => {
          const s = tr.s * H, x = tr.x * W, y = tr.y * H - lt * 0.004 * H;
          return <path key={i} d={`M ${x} ${y - s} L ${x + s * 0.9} ${y + s * 0.6} L ${x - s * 0.9} ${y + s * 0.6} Z`} fill="none" stroke={chalk} strokeWidth={0.0025 * H}
            pathLength={1} strokeDasharray={`${pr(lt, tr.at, 0.6, "inOut")} 1`} opacity={0.75} />;
        })}
      </svg>
    </>
  );
};

// ================================================================== verdict thumbs
const THUMB = "M30 46 h11 l12 -25 c2.5 -5.5 11 -4.8 11.6 2.4 l-2 16.6 h17.4 c5.6 0 9.2 5.3 7.6 10.4 l-5.8 26.4 c-1 3.6 -4.2 6.2 -8 6.2 H30 Z M14 46 h11 v42 h-11 z";
const Thumbs: React.FC<{ L: Layer; c: GCtx }> = ({ L, c }) => {
  const { W, H } = c;
  const lt = c.t - L.from;
  const v = L.items && L.items.length ? L.items : ["up"];
  const at = timesOf(L, v.length, 0, 1.2);
  let i = -1;
  for (let k = 0; k < v.length; k++) if (lt >= at[k]) i = k;
  if (i < 0) return null;
  const up = !/down|no|bad|hate|red|-/.test(v[i].toLowerCase());
  const col = up ? (L.fill && L.fill.startsWith("#") ? L.fill : "#22d63a") : "#d6282f";
  const pop = backOutLite(c01((lt - at[i]) / 0.24));
  const grow = 1 + 0.07 * c01((lt - at[i] - 0.24) / 1.6);
  const out = i < v.length - 1 ? 1 - c01((lt - (at[i + 1] - 0.12)) / 0.12) : 1;
  // the disc's diameter is the layer's height share (the reference: ~0.26 of the frame)
  const d = (L.h || 0.26) * H * pop * grow * out;
  return (
    <div style={{ position: "absolute", left: L.x * W, top: L.y * H, width: d, height: d, transform: "translate(-50%, -50%)", borderRadius: "50%",
      background: `radial-gradient(circle at 35% 30%, ${up ? "#5dff6e" : "#ff5a5f"} 0%, ${col} 55%, ${up ? "#13a524" : "#a51419"} 100%)`,
      boxShadow: `0 0 ${(0.06 * H).toFixed(1)}px ${col}bb, 0 ${(0.01 * H).toFixed(1)}px ${(0.03 * H).toFixed(1)}px rgba(0,0,0,0.45)` }}>
      <svg viewBox="0 0 100 100" width={d * 0.62} height={d * 0.62} style={{ position: "absolute", left: d * 0.19, top: d * (up ? 0.16 : 0.22),
        transform: up ? undefined : "rotate(180deg)", filter: "drop-shadow(0 2px 2px rgba(0,0,0,0.25))" }}>
        <path d={THUMB} fill="#ffffff" />
      </svg>
    </div>
  );
};

// ================================================================== game manual
const Manual: React.FC<{ L: Layer; c: GCtx }> = ({ L, c }) => {
  const { W, H } = c;
  const lt = c.t - L.from;
  const secs = (L.items || []).slice(0, 4);
  const at = timesOf(L, secs.length, 0.8, 0.6);
  const bw = 0.64 * W, bh = 0.64 * H;
  const rise = pr(lt, 0, 0.6);
  const open = pr(lt, 0.35, 0.5, "inOut");
  const page: React.CSSProperties = { position: "absolute", top: 0, width: bw / 2, height: bh,
    background: "radial-gradient(ellipse at 50% 45%, #f1e6c9 0%, #e7d7b1 70%, #cdb488 100%)", boxShadow: "inset 0 0 40px rgba(110,80,40,0.35)" };
  const ink = "#2b2118";
  const head = (s: string, i: number) => {
    const p = pr(lt, at[i], 0.45, "out");
    return (
      <div key={i} style={{ position: "relative", marginBottom: 0.03 * H, clipPath: `inset(0 ${((1 - p) * 100).toFixed(1)}% 0 0)` }}>
        <div style={{ fontFamily: F.marker(), fontSize: 0.034 * H, color: ink, whiteSpace: "nowrap" }}>{`${i + 1}. ${s.toUpperCase()}`}</div>
        {[0.9, 0.75, 0.82].map((wd, k) => <div key={k} style={{ height: 0.006 * H, width: `${wd * 70}%`, background: "#a8946c", marginTop: 0.012 * H, borderRadius: 3, opacity: 0.8 }} />)}
        {L.hi === i ? (
          <svg width={bw * 0.42} height={0.08 * H} style={{ position: "absolute", left: -0.012 * W, top: -0.018 * H, overflow: "visible" }}>
            <ellipse cx={bw * 0.2} cy={0.03 * H} rx={bw * 0.21} ry={0.032 * H} fill="none" stroke="#c62828" strokeWidth={0.004 * H}
              pathLength={1} strokeDasharray={`${pr(lt, at[i] + 0.35, 0.45, "inOut")} 1`} transform={`rotate(-3 ${bw * 0.2} ${0.03 * H})`} />
          </svg>
        ) : null}
      </div>
    );
  };
  const left = secs.slice(0, 2), right = secs.slice(2);
  return (
    <div style={{ position: "absolute", left: L.x * W - bw / 2, top: L.y * H - bh / 2 + (1 - rise) * 0.7 * H, width: bw, height: bh,
      transform: `rotate(${(-7 + 5 * rise).toFixed(2)}deg)`, filter: "drop-shadow(0 24px 36px rgba(0,0,0,0.6))", perspective: 1800 }}>
      <div style={{ ...page, left: 0, padding: 0.035 * H, boxSizing: "border-box" }}>
        {L.label ? <div style={{ fontFamily: TYPEWRITER, fontWeight: 700, fontSize: 0.02 * H, color: "#6b5634", letterSpacing: "0.12em" }}>{L.label.toUpperCase()}</div> : null}
        <div style={{ fontFamily: F.marker(), fontSize: 0.05 * H, color: ink, margin: `${0.01 * H}px 0 ${0.03 * H}px`, lineHeight: 1.05 }}>{L.text}</div>
        {left.map((s, i) => head(s, i))}
      </div>
      <div style={{ ...page, left: bw / 2, padding: 0.035 * H, boxSizing: "border-box", transformOrigin: "0% 50%",
        transform: `rotateY(${(-100 * (1 - open)).toFixed(1)}deg)`, opacity: open > 0.02 ? 1 : 0 }}>
        {right.map((s, i) => head(s, i + 2))}
        {L.meta ? (
          <div style={{ position: "absolute", right: 0.04 * H, bottom: 0.05 * H, padding: `${0.012 * H}px ${0.016 * H}px`, background: "#f7e26b", transform: "rotate(4deg)",
            fontFamily: F.marker(), fontSize: 0.026 * H, color: ink, boxShadow: "0 6px 10px rgba(0,0,0,0.25)", opacity: pr(lt, (L.mid ?? 2), 0.3) }}>{L.meta}</div>
        ) : null}
      </div>
      <div style={{ position: "absolute", left: bw / 2 - 0.03 * W, top: 0, width: 0.06 * W, height: bh,
        background: "linear-gradient(90deg, rgba(0,0,0,0) 0%, rgba(60,40,15,0.45) 50%, rgba(0,0,0,0) 100%)" }} />
    </div>
  );
};

// ================================================================== summary card
const Summary: React.FC<{ L: Layer; c: GCtx }> = ({ L, c }) => {
  const { W, H } = c;
  const lt = c.t - L.from;
  const life = Math.max(0.5, L.to - L.from);
  const rows = L.items || [];
  const at = timesOf(L, rows.length, 0.9, 0.9);
  const typed = (s: string, t0: number) => s.slice(0, Math.max(0, Math.floor((lt - t0) / 0.014)));
  const lead = L.text || "";
  const hl = L.label || "";
  const lp = typed(lead, 0.15);
  const k = hl ? lead.indexOf(hl) : -1;
  const leadNode = k >= 0 ? (
    <>{lp.slice(0, k)}<span style={{ color: L.emphColor || "#f2c94c" }}>{lp.slice(k, k + hl.length)}</span>{lp.slice(k + hl.length)}</>
  ) : lp;
  const zoom = 1 + 0.08 * (lt / life);
  return (
    <div style={{ position: "absolute", inset: 0, background: "radial-gradient(ellipse at 40% 45%, #2b2f36 0%, #1d2025 70%, #121418 100%)", opacity: pr(lt, 0, 0.2, "out") }}>
      <div style={{ position: "absolute", left: 0.2 * W, top: 0.36 * H, width: 0.62 * W, transform: `scale(${zoom.toFixed(4)})`, transformOrigin: "0% 30%",
        fontFamily: INTER, color: "#e8eaed" }}>
        <div style={{ fontSize: 0.046 * H, fontWeight: 500, lineHeight: 1.3, marginBottom: 0.035 * H }}>{leadNode}</div>
        {rows.map((r, i) => {
          const s = typed(r, at[i]);
          if (!s) return null;
          const colon = r.indexOf(":");
          const b = colon > 0 ? s.slice(0, colon + 1) : "";
          const rest = colon > 0 ? s.slice(colon + 1) : s;
          return (
            <div key={i} style={{ display: "flex", gap: 0.016 * H, fontSize: 0.04 * H, lineHeight: 1.35, marginBottom: 0.02 * H }}>
              <span style={{ color: "#c8ccd2" }}>•</span>
              <span><b style={{ fontWeight: 700, color: "#ffffff" }}>{b}</b><span style={{ color: "#c3c7cd" }}>{rest}</span></span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

// ================================================================== neon question box
const Neon: React.FC<{ L: Layer; c: GCtx }> = ({ L, c }) => {
  const { W, H } = c;
  const lt = c.t - L.from;
  const uid = React.useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const w = L.w * W, h = L.h * H, x = L.x * W - w / 2, y = L.y * H - h / 2;
  const a = pr(lt, 0, 0.3);
  const flick = lt > 0.05 && lt < 0.12 ? 0.35 : 1;
  const P = [[0.03, 0], [0.97, 0], [1, 0.25], [1, 0.78], [0.95, 1], [0.03, 1], [0, 0.78], [0, 0.2]].map(([px, py]) => `${(px * w).toFixed(1)},${(py * h).toFixed(1)}`).join(" ");
  const q = L.text || "";
  const n = Math.max(0, Math.min(q.length, Math.floor((lt - 0.3) / 0.03)));
  const track = 0.04 + 0.16 * (1 - pr(lt, 0.3, 1.2, "out"));
  const pink = "#ff3fa4", purple = "#8b5cf6", cyan = "#22d3ee";
  return (
    <div style={{ position: "absolute", left: x, top: y, width: w, height: h, opacity: a * flick, transform: `scaleX(${(0.75 + 0.25 * a).toFixed(4)})`, transformOrigin: "50% 50%" }}>
      <svg width={w} height={h} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
        <defs>
          <linearGradient id={`${uid}s`} x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stopColor={pink} /><stop offset="55%" stopColor={purple} /><stop offset="100%" stopColor={cyan} /></linearGradient>
          <linearGradient id={`${uid}f`} x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor="rgba(45,10,50,0.9)" /><stop offset="100%" stopColor="rgba(10,10,32,0.88)" /></linearGradient>
          <filter id={`${uid}g`} x="-10%" y="-30%" width="120%" height="160%"><feGaussianBlur stdDeviation={0.008 * H} /></filter>
          <linearGradient id={`${uid}p`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#ff7ad1" /><stop offset="100%" stopColor="#c2187a" /></linearGradient>
        </defs>
        <polygon points={P} fill={`url(#${uid}f)`} />
        <polygon points={P} fill="none" stroke={`url(#${uid}s)`} strokeWidth={0.012 * H} filter={`url(#${uid}g)`} opacity={0.85} />
        <polygon points={P} fill="none" stroke={`url(#${uid}s)`} strokeWidth={0.005 * H} />
        {[0, 1, 2].map((i) => <path key={i} d={`M ${0.2 * w + i * 0.018 * w} ${-0.06 * h} l ${0.012 * w} 0 l ${-0.01 * w} ${0.08 * h} l ${-0.012 * w} 0 z`} fill={pink} />)}
        {[0, 1, 2].map((i) => <path key={`b${i}`} d={`M ${0.86 * w + i * 0.018 * w} ${1.0 * h} l ${0.012 * w} 0 l ${-0.01 * w} ${0.08 * h} l ${-0.012 * w} 0 z`} fill={cyan} />)}
        <g transform={`translate(${-0.02 * w} ${h * 0.95}) scale(${(h / 140).toFixed(3)})`} opacity={0.95}>
          <path d="M 18 0 C 22 -40 30 -80 44 -112" stroke={`url(#${uid}p)`} strokeWidth={7} fill="none" strokeLinecap="round" />
          {[[-60, -20], [-30, -45], [10, -50], [45, -30], [70, -5]].map(([dx, dy], i) => (
            <path key={i} d={`M 44 -112 Q ${44 + dx * 0.6} ${-112 + dy - 25} ${44 + dx} ${-112 - dy * -0.4 + 20}`} stroke={`url(#${uid}p)`} strokeWidth={9} fill="none" strokeLinecap="round" />
          ))}
        </g>
      </svg>
      {L.label ? (
        <div style={{ position: "absolute", right: 0.01 * w, top: -0.35 * h, fontFamily: F.slab(), fontWeight: 800, fontSize: 0.5 * h, lineHeight: 1,
          background: `linear-gradient(180deg, ${pink}, #ffb347)`, WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent",
          WebkitTextStroke: `${(0.004 * H).toFixed(1)}px #2a0a2e`, filter: `drop-shadow(0 0 ${(0.01 * H).toFixed(1)}px ${pink})` }}>{L.label}</div>
      ) : null}
      <div style={{ position: "absolute", left: 0.1 * w, right: 0.12 * w, top: "50%", transform: "translateY(-50%)", fontFamily: INTER, color: "#ffffff",
        textShadow: `0 0 ${(0.01 * H).toFixed(1)}px rgba(255,80,200,0.35)` }}>
        <div style={{ fontSize: (L.size || 0.034) * H, fontWeight: 500, letterSpacing: `${track.toFixed(3)}em`, whiteSpace: "nowrap" }}>{q.slice(0, n)}</div>
        {L.meta ? <div style={{ fontSize: (L.size || 0.034) * H * 1.05, fontWeight: 800, marginTop: 0.008 * H, opacity: pr(lt, (L.mid ?? 1.2), 0.3) }}>{L.meta}</div> : null}
      </div>
    </div>
  );
};

// ================================================================== tv static cut
const BARS = ["#c0c0c0", "#c0c000", "#00c0c0", "#00c000", "#c000c0", "#c00000", "#0000c0"];
const Static: React.FC<{ L: Layer; c: GCtx }> = ({ L, c }) => {
  const { W, H } = c;
  const lt = c.t - L.from;
  const life = Math.max(0.3, L.to - L.from);
  const u = lt / life;
  const uid = React.useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const f = Math.floor(lt * 30);
  const noise = u < 0.3 ? u / 0.3 : u > 0.7 ? (1 - u) / 0.3 : 0.35;
  const bars = u > 0.28 && u < 0.72;
  const jit = (rand(f * 13 + 1) - 0.5) * 0.04 * W;
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      {bars ? (
        <div style={{ position: "absolute", inset: 0, display: "flex", transform: `translateX(${jit.toFixed(1)}px)` }}>
          {BARS.map((b, i) => <div key={i} style={{ flex: 1, background: b }} />)}
        </div>
      ) : null}
      <svg width={W} height={H} style={{ position: "absolute", inset: 0, opacity: Math.min(1, noise * 1.2) }}>
        <filter id={`${uid}n`}><feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="1" seed={f % 97} />
          <feColorMatrix type="saturate" values="0" /><feComponentTransfer><feFuncA type="linear" slope="1" intercept="0.25" /></feComponentTransfer></filter>
        <rect width={W} height={H} filter={`url(#${uid}n)`} />
      </svg>
      <div style={{ position: "absolute", inset: 0, background: `repeating-linear-gradient(0deg, rgba(0,0,0,0.22) 0px, rgba(0,0,0,0.22) 2px, rgba(0,0,0,0) 2px, rgba(0,0,0,0) 5px)` }} />
      {[0, 1].map((k) => {
        const y = rand(f * 7 + k * 31) * H;
        return <div key={k} style={{ position: "absolute", left: 0, top: y, width: W, height: 0.03 * H, background: "rgba(255,255,255,0.25)", transform: `translateX(${((rand(f + k) - 0.5) * 0.08 * W).toFixed(1)}px)` }} />;
      })}
    </div>
  );
};

// ================================================================== end line
const EndLine: React.FC<{ L: Layer; c: GCtx }> = ({ L, c }) => {
  const { W, H } = c;
  const lt = c.t - L.from;
  const a = pr(lt, 0.1, 0.5), b = pr(lt, L.mid ?? 0.8, 0.5);
  return (
    <div style={{ position: "absolute", inset: 0, background: "#000", opacity: pr(lt, 0, 0.25, "out") }}>
      <div style={{ position: "absolute", left: 0.5 * W, top: 0.5 * H, transform: "translate(-50%, -50%)", textAlign: "center", whiteSpace: "nowrap" }}>
        {L.meta ? <div style={{ fontFamily: F.poppins(), fontWeight: 700, fontSize: 0.033 * H, color: "#f2f2f2", opacity: a, transform: `translateY(${((1 - a) * 0.01 * H).toFixed(1)}px)` }}>{L.meta}</div> : null}
        <div style={{ fontFamily: F.poppins(), fontWeight: 900, fontSize: (L.size || 0.042) * H, color: L.emphColor || "#e6a915", letterSpacing: "0.03em", textTransform: "uppercase",
          opacity: b, transform: `translateY(${((1 - b) * 0.012 * H).toFixed(1)}px)`, marginTop: 0.006 * H }}>{L.text}</div>
      </div>
    </div>
  );
};

/** Draws one "game" layer (full frame). */
export const GameBody: React.FC<{ layer: Layer; ctx: GCtx }> = ({ layer: L, ctx: c }) => {
  switch (L.game) {
    case "kinetic": return <Kinetic L={L} c={c} />;
    case "boxed": return <Boxed L={L} c={c} />;
    case "meter": return <Meter L={L} c={c} />;
    case "article": return <Article L={L} c={c} />;
    case "versus": return <Versus L={L} c={c} />;
    case "board": return <Board L={L} c={c} />;
    case "curve": return <Curve L={L} c={c} />;
    case "zone": return <Zone L={L} c={c} />;
    case "wire": return <Wire L={L} c={c} />;
    case "formula": return <Formula L={L} c={c} />;
    case "thumbs": return <Thumbs L={L} c={c} />;
    case "manual": return <Manual L={L} c={c} />;
    case "summary": return <Summary L={L} c={c} />;
    case "neon": return <Neon L={L} c={c} />;
    case "static": return <Static L={L} c={c} />;
    case "endline": return <EndLine L={L} c={c} />;
    default: return null;
  }
};
