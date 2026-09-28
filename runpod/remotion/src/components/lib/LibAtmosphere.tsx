import React from "react";
import { AbsoluteFill, Easing, Img, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY, LABEL, MONO } from "../fonts";
import type { MapLocation, Overlay, SceneMedia } from "../../types";
import { LetterLine, lines, ramp, useHold, useK } from "../pro/ProGraphics";

/**
 * Transitions and atmosphere (family "fx-"): ten looks that change the air of
 * a shot for a moment or carry a section change. Seven ride on the playing
 * footage and leave it clean; three are designed cards that draw their own
 * frame. Every word rises out of a mask letter by letter and leaves the same
 * way (typing only inside the HUD's mono readouts); everything is seeded,
 * nothing is random.
 *
 *   fx-ink-bleed      black ink blooms over the picture from three points,
 *                     crinkled edges creeping, until it closes the frame; the
 *                     title rises in white; at the end the ink opens from the
 *                     centre and gives the picture back
 *   fx-light-streak   an anamorphic streak crosses the frame and its hot spot
 *                     writes the title letter by letter; a weaker glint sweeps
 *                     back at the end and lifts the letters away
 *   fx-dust-motes     dust drifting in a shaft of light at three depths (far
 *                     specks, mid motes, near bokeh), motes flaring as they
 *                     cross the beam; an optional source line low left
 *   fx-hud-scan       a thin HUD grid draws out from the centre, a cyan scan
 *                     line sweeps and lights the crossings it passes, mono
 *                     readouts type in, the subject (and coordinates) low left
 *   fx-film-burn      warm light blooms in from the right edge, the film burns
 *                     through (white-hot hole, charred rim, embers), flickers
 *                     and fades; an optional date rises low left
 *   fx-shape-wipe     bars and triangles whip across with a smeared motion
 *                     blur; the last accent bar parks as the underline of an
 *                     optional word, then whips out with it
 *   fx-gradient-mesh  a slow gold and charcoal gradient mesh blooms open
 *                     behind a centred title, a sheen crossing it
 *   fx-glitch-slice   three short bursts: the picture slices and shifts
 *                     sideways, colour-split bands, an inverted band, block
 *                     artefacts, scanlines; an optional alert line jitters
 *   fx-zoom-tunnel    speed lines stream into the centre with an impact ring;
 *                     a short line punches in inside the clear zone
 *   fx-paper-tear     a sheet of paper lands over the shot with the title on
 *                     it, cracks along a jagged line and the halves fly apart,
 *                     revealing the footage (full screen: the scene's picture)
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;

// ================================================================== shared
const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const expoIn = Easing.bezier(0.7, 0, 0.84, 0);
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const quintOut = Easing.bezier(0.22, 1, 0.36, 1);
const TAU = Math.PI * 2;
const CYAN = "#53c8ff";
const INK = "#0a0b0e";
const PAPER_INK = "#141518";
const GOLD: [number, number, number] = [214, 168, 60];

const cap = (s?: string): string => (s || "").replace(/\s+/g, " ").trim().toUpperCase();
const pad2 = (n: number): string => String(Math.max(0, Math.floor(n))).padStart(2, "0");
const wrap = (v: number, m: number): number => ((v % m) + m) % m;
const lerp = (range: readonly number[], u: number): number => range[0] + (range[1] - range[0]) * u;
const smooth = (x: number): number => {
  const c = Math.max(0, Math.min(1, x));
  return c * c * (3 - 2 * c);
};

/** [r, g, b] of "#abc" / "#aabbcc" / "rgb(a)(...)"; null for anything else. */
const rgbOf = (c: string): [number, number, number] | null => {
  const s = (c || "").trim();
  const m = /^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)/i.exec(s);
  if (m) return [Number(m[1]), Number(m[2]), Number(m[3])];
  const h = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(s);
  if (!h) return null;
  let x = h[1];
  if (x.length === 3) x = x.split("").map((ch) => ch + ch).join("");
  const n = parseInt(x, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};

/** The colour at alpha `a`; an unreadable colour falls back to the house gold. */
const withAlpha = (c: string, a: number): string => {
  const v = rgbOf(c) || GOLD;
  return `rgba(${v[0]},${v[1]},${v[2]},${a})`;
};

/** The colour taken toward black by `dark` (0..1), at alpha `a`. */
const shade = (c: string, dark: number, a = 1): string => {
  const v = rgbOf(c) || GOLD;
  const f = 1 - dark;
  return `rgba(${Math.round(v[0] * f)},${Math.round(v[1] * f)},${Math.round(v[2] * f)},${a})`;
};

/** Deterministic 0..1 noise from an integer seed (one mulberry32 step). */
const rnd = (seed: number): number => {
  let t = (Math.imul(Math.floor(seed) | 0, 0x6d2b79f5) + 0x9e3779b9) | 0;
  t = Math.imul(t ^ (t >>> 15), t | 1);
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};

/** A title's size and lines: shrinks from `big` until it fits `maxLines`. */
const fit = (text: string, big: number, chars: number, maxLines: number): { size: number; ls: string[] } => {
  let size = big;
  let ls = lines(text, chars);
  while (ls.length > maxLines && size > 50) {
    size -= 6;
    ls = lines(text, Math.round((chars * big) / size));
  }
  if (ls.length > maxLines) {
    ls = ls.slice(0, maxLines);
    ls[maxLines - 1] = `${ls[maxLines - 1]}…`;
  }
  return { size, ls };
};

/** Letter stagger so any line lands inside ~0.9 s. */
const stepFor = (t: string): number => Math.max(0.4, Math.min(1, 14 / Math.max(1, Array.from(t).length)));
/** When a line's letters start leaving so the last one is gone `lead` frames before the end. */
const outFor = (t: string, D: number, lead: number): number =>
  Math.max(D - lead - 22, D - lead - Math.ceil(Math.max(0, Array.from(t).length - 1) * 0.6));

/** LetterLine with an in-stagger fitted to the line and an out-time fitted to the graphic. */
const Letters: React.FC<{ text: string; at: number; style: React.CSSProperties; step?: number; outAt?: number;
  lead?: number }> = ({ text, at, style, step, outAt, lead = 11 }) => {
  const { durationInFrames } = useVideoConfig();
  return <LetterLine text={text} at={at} step={step ?? stepFor(text)} outAt={outAt ?? outFor(text, durationInFrames, lead)}
    style={style} />;
};

/** A line rising out of its mask, and rising away through it at the end. */
const Rise: React.FC<{ at: number; frames?: number; outAt?: number; style?: React.CSSProperties;
  children: React.ReactNode }> = ({ at, frames = 16, outAt, style, children }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const pin = ramp(frame, at, frames);
  const pout = ramp(frame, outAt ?? durationInFrames - 13, 10, expoIn);
  return (
    <div style={{ overflow: "hidden", paddingBottom: "0.08em", ...style }}>
      <div style={{ transform: `translateY(${(1 - pin) * 110 - pout * 110}%)` }}>{children}</div>
    </div>
  );
};

/** Exit progress: 0 while the graphic holds, 1 once it has left. */
const useExit = (lead = 12, frames = 10): number => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return ramp(frame, durationInFrames - lead, frames, expoIn);
};

const stillOf = (m?: SceneMedia): string => (m && m.url ? (m.type === "image" ? m.url : m.thumbnail || "") : "");

/** Mono UI text typed in and deleted at the end (the only place typing is allowed). */
const typed = (s: string, frame: number, at: number, cps: number, outAt: number, outFrames: number): string => {
  const chars = Array.from(s);
  const shown = Math.max(0, Math.min(chars.length, Math.floor((frame - at) * cps)));
  const gone = Math.max(0, Math.min(chars.length, Math.ceil(((frame - outAt) / Math.max(1, outFrames)) * chars.length)));
  return chars.slice(0, Math.max(0, shown - gone)).join("");
};

/** HH:MM:SS:FF of a frame. */
const timecode = (f: number, fps: number): string => {
  const r = Math.max(0, Math.round(f));
  const s = Math.floor(r / fps);
  return `${pad2(s / 3600)}:${pad2((s / 60) % 60)}:${pad2(s % 60)}:${pad2(r % fps)}`;
};

const HARM: [number, number][] = [[2, 0.07], [3, 0.06], [5, 0.045], [8, 0.03], [13, 0.022], [21, 0.015], [34, 0.01], [55, 0.006]];

/**
 * An organic outline around (cx, cy): low harmonics for the lobes, high ones
 * for a crinkled edge, narrow bumps for the tendrils ink pushes into paper.
 * `t` slowly creeps the edge; everything else is fixed by `seed`.
 */
const blobPath = (cx: number, cy: number, r: number, seed: number, t: number, rough = 1, spikes = 7, n = 180): string => {
  if (!(r > 0.5)) return "";
  const ph = HARM.map((_, j) => rnd(seed * 131 + j * 17) * TAU);
  const sp = Array.from({ length: spikes }, (_, j) => ({
    a: rnd(seed * 71 + j * 13 + 5) * TAU,
    w: 0.025 + rnd(seed * 29 + j * 5 + 7) * 0.06,
    h: 0.035 + rnd(seed * 43 + j * 11 + 3) * 0.1,
  }));
  let d = "";
  for (let i = 0; i < n; i++) {
    const a = (i / n) * TAU;
    let m = 1;
    for (let j = 0; j < HARM.length; j++) {
      m += HARM[j][1] * rough * Math.sin(HARM[j][0] * a + ph[j] + t * (j % 2 ? 0.35 : -0.28));
    }
    for (const s of sp) {
      let da = Math.abs(a - s.a) % TAU;
      if (da > Math.PI) da = TAU - da;
      const q = da / s.w;
      m += s.h * rough * Math.exp(-q * q);
    }
    const rr = r * Math.max(0.2, m);
    d += `${i ? "L" : "M"}${(cx + Math.cos(a) * rr).toFixed(1)} ${(cy + Math.sin(a) * rr).toFixed(1)}`;
  }
  return `${d}Z`;
};

// ================================================================== 1. ink bleed
const INK_SEEDS = [
  { x: 0.34, y: 0.56, at: 0, grow: 34, r: 1450, seed: 11 },
  { x: 0.85, y: 0.18, at: 4, grow: 30, r: 900, seed: 23 },
  { x: 0.7, y: 0.9, at: 7, grow: 28, r: 780, seed: 37 },
  { x: 0.07, y: 0.1, at: 10, grow: 26, r: 620, seed: 41 },
];
const INK_DROPS = Array.from({ length: 7 }, (_, i) => ({
  x: 0.1 + rnd(i * 97 + 1) * 0.82,
  y: 0.08 + rnd(i * 89 + 2) * 0.84,
  at: 2 + Math.round(rnd(i * 83 + 3) * 9),
  r: 14 + rnd(i * 79 + 4) * 44,
  seed: 60 + i,
}));

/**
 * Ink blooms over the shot from three points (and a few satellite drops),
 * edges crinkled and creeping, a soft wet spread ahead of each edge, until it
 * closes the frame; the title rises in white over it. At the end the ink
 * opens from the centre with the same ragged edge. Full screen it blooms on
 * warm paper.
 */
const InkBleed: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width: W, height: H, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const title = cap(overlay.text);
  if (!title) return null;
  const full = Boolean(overlay.fullFrame);
  const kicker = cap(overlay.label);
  const sub = lines(overlay.subtitle || "", 48).slice(0, 2);
  const { size, ls } = fit(title, 84, 20, 2);
  const t = frame / fps;
  const id = `fxink${Math.round(overlay.startFrame || 0)}`;
  const diag = Math.hypot(W, H);
  const settle = ramp(frame, 20, 12, inOut);
  const live = settle < 1;
  const hs = Math.max(40, D - 16);
  const hp = ramp(frame, hs, Math.max(8, D - 2 - hs), inOut);
  const lead = 26;
  const textOut = ramp(frame, D - lead - 8, 10, expoIn);
  const rule = ramp(frame, 27, 18) * (1 - textOut);
  const glow = ramp(frame, 18, 24) * (0.75 + 0.25 * Math.sin(t * 1.1));
  const blobs = INK_SEEDS.map((s) => ({ x: s.x * W, y: s.y * H, seed: s.seed,
    r: s.r * k * ramp(frame, s.at, s.grow, quintOut) }));
  const drops = INK_DROPS.map((d) => ({ x: d.x * W, y: d.y * H, seed: d.seed, r: d.r * k * ramp(frame, d.at, 7, backOut) }));
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      {full ? (
        <AbsoluteFill style={{ background: "radial-gradient(ellipse 85% 75% at 45% 45%, #f5f2eb 0%, #e7e1d5 58%, #cfc7b6 100%)" }}>
          <AbsoluteFill style={{ boxShadow: `inset 0 0 ${240 * k}px rgba(80,66,44,.28)` }} />
        </AbsoluteFill>
      ) : null}
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
        <defs>
          <radialGradient id={`${id}g`} cx="38%" cy="52%" r="80%">
            <stop offset="0%" stopColor="#1a1b20" />
            <stop offset="55%" stopColor="#0c0d10" />
            <stop offset="100%" stopColor="#050506" />
          </radialGradient>
          <radialGradient id={`${id}c`}>
            <stop offset="0%" stopColor="#ffffff" stopOpacity={0.06} />
            <stop offset="100%" stopColor="#ffffff" stopOpacity={0} />
          </radialGradient>
          <radialGradient id={`${id}a`}>
            <stop offset="0%" stopColor={withAlpha(accent, 0.16)} />
            <stop offset="100%" stopColor={withAlpha(accent, 0)} />
          </radialGradient>
          <filter id={`${id}b`} filterUnits="userSpaceOnUse" x={-W * 0.1} y={-H * 0.1} width={W * 1.2} height={H * 1.2}>
            <feGaussianBlur stdDeviation={16 * k} />
          </filter>
          <mask id={`${id}m`} maskUnits="userSpaceOnUse" x={0} y={0} width={W} height={H}>
            <rect x={0} y={0} width={W} height={H} fill="#000" />
            <rect x={0} y={0} width={W} height={H} fill="#fff" opacity={settle} />
            {live ? blobs.map((b, i) => (b.r > 1 ? (
              <path key={`o${i}`} d={blobPath(b.x, b.y, b.r, b.seed, t)} fill="#fff" opacity={0.5} />
            ) : null)) : null}
            {live ? blobs.map((b, i) => (b.r > 1 ? (
              <path key={`c${i}`} d={blobPath(b.x, b.y, b.r * 0.93, b.seed + 5, t * 1.3, 0.8, 5)} fill="#fff" />
            ) : null)) : null}
            {live ? drops.map((d, i) => (d.r > 1 ? (
              <path key={`d${i}`} d={blobPath(d.x, d.y, d.r, d.seed, t, 1.3, 4, 64)} fill="#fff" />
            ) : null)) : null}
            {hp > 0 ? <path d={blobPath(W / 2, H / 2, hp * diag * 0.78, 91, t, 1, 8)} fill="#000" opacity={0.5} /> : null}
            {hp > 0 ? <path d={blobPath(W / 2, H / 2, hp * diag * 0.72, 97, t, 1, 8)} fill="#000" /> : null}
          </mask>
        </defs>
        {live ? (
          <g filter={`url(#${id}b)`} opacity={0.42 * (1 - settle)}>
            {blobs.map((b, i) => (b.r > 1 ? <path key={i} d={blobPath(b.x, b.y, b.r * 1.07, b.seed + 2, t)} fill={INK} /> : null))}
          </g>
        ) : null}
        <g mask={`url(#${id}m)`}>
          <rect x={0} y={0} width={W} height={H} fill={`url(#${id}g)`} />
          <ellipse cx={W * (0.3 + 0.05 * Math.sin(t * 0.5))} cy={H * (0.42 + 0.04 * Math.cos(t * 0.4))} rx={W * 0.38}
            ry={H * 0.46} fill={`url(#${id}c)`} />
          <ellipse cx={W * 0.5} cy={H * 0.5} rx={W * 0.32} ry={H * 0.26} fill={`url(#${id}a)`} opacity={glow} />
        </g>
      </svg>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", maxWidth: 1600 * k }}>
          {kicker ? (
            <Letters text={kicker} at={16} lead={lead} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k,
              letterSpacing: "0.36em", paddingLeft: "0.36em", color: accent, whiteSpace: "nowrap", marginBottom: 12 * k }} />
          ) : null}
          {ls.map((ln, i) => (
            <Letters key={i} text={ln} at={20 + i * 5} lead={lead} style={{ fontFamily: DISPLAY, fontSize: size * k,
              lineHeight: 1, letterSpacing: "0.04em", color: "#fff", textAlign: "center", whiteSpace: "nowrap",
              textShadow: "0 8px 30px rgba(0,0,0,.45)" }} />
          ))}
          <div style={{ width: 170 * k, height: 4 * k, marginTop: 18 * k, background: accent, transform: `scaleX(${rule})` }} />
          {sub.map((ln, i) => (
            <Rise key={`s${i}`} at={30 + i * 3} outAt={D - lead - 10} style={{ marginTop: i === 0 ? 16 * k : 0 }}>
              <span style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 30 * k, letterSpacing: "0.1em",
                color: "rgba(255,255,255,.66)" }}>{cap(ln)}</span>
            </Rise>
          ))}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 2. light streak
const GHOSTS = [
  { s: 0.45, r: 20, f: 0.12 },
  { s: 0.82, r: 56, f: 0.05 },
  { s: 1.28, r: 15, f: 0.16 },
  { s: 1.6, r: 88, f: 0.035 },
  { s: 2.05, r: 32, f: 0.08 },
];

const hexPath = (x: number, y: number, r: number): string => {
  let d = "";
  for (let i = 0; i < 6; i++) {
    const a = (i / 6) * TAU + Math.PI / 6;
    d += `${i ? "L" : "M"}${(x + Math.cos(a) * r).toFixed(1)} ${(y + Math.sin(a) * r).toFixed(1)}`;
  }
  return `${d}Z`;
};

/** Advance of a Bebas Neue capital in em, tracking included (to place letters under the streak). */
const advance = (c: string): number => (c === " " ? 0.26 : /[MW]/.test(c) ? 0.62 : /[IJ1.,'!:]/.test(c) ? 0.24 : 0.44) + 0.05;

/**
 * An anamorphic flare: a thin white core line with an accent glow, a hot spot,
 * faint parallel lines and hexagonal lens ghosts on the far side of the frame
 * centre, all screen-blended onto the footage. As the hot spot crosses, each
 * letter of the title rises exactly when the light reaches it, flashing; a
 * weaker glint sweeps back at the end and lifts the letters away.
 */
const LightStreak: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width: W, height: H, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const title = cap(overlay.text);
  const kicker = cap(overlay.label);
  const { size, ls } = fit(title, 76, 26, 2);
  const px = size * k;
  const a0 = 2;
  const pass = Math.max(18, Math.round(fps * 0.85));
  const back = Math.max(10, Math.round(pass * 0.62));
  const b0 = Math.max(a0 + pass + 14, D - back - 6);
  const sweepIn = (f: number): number => interpolate(f, [a0, a0 + pass], [-0.22, 1.22], { ...clamp, easing: inOut });
  const sweepOut = (f: number): number => interpolate(f, [b0, b0 + back], [1.22, -0.22], { ...clamp, easing: inOut });
  const second = frame >= b0;
  const X = second ? sweepOut(frame) : sweepIn(frame);
  const E = second
    ? interpolate(frame, [b0, b0 + 3, b0 + back * 0.5, b0 + back, b0 + back + 6], [0, 0.4, 0.55, 0.3, 0], clamp)
    : interpolate(frame, [a0, a0 + 4, a0 + pass * 0.5, a0 + pass, a0 + pass + 10], [0, 0.85, 1, 0.5, 0], clamp);
  const Y = H * (title ? 0.6 : 0.5);
  const crossIn = (lx: number): number => {
    for (let f = a0; f <= a0 + pass; f++) if (sweepIn(f) >= lx) return f;
    return a0 + pass;
  };
  const crossOut = (lx: number): number => {
    for (let f = b0; f <= b0 + back; f++) if (sweepOut(f) <= lx) return f;
    return b0 + back;
  };
  const shadeP = title ? ramp(frame, a0 + pass * 0.4, 14) * (1 - ramp(frame, b0 + back - 4, 8)) : 0;
  const hx = X * W;
  const xs = X * 100;
  const gcx = W / 2, gcy = H / 2;
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      {shadeP > 0 ? (
        <AbsoluteFill style={{ opacity: shadeP,
          background: `radial-gradient(ellipse 40% 24% at 50% ${(((Y - 50 * k) / H) * 100).toFixed(1)}%, rgba(0,0,0,.4) 0%, rgba(0,0,0,0) 100%)` }} />
      ) : null}
      {title ? (
        <div style={{ position: "absolute", left: 0, right: 0, bottom: H - Y + 12 * k, display: "flex", flexDirection: "column",
          alignItems: "center" }}>
          {kicker ? (
            <Letters text={kicker} at={crossIn(0.5) + 3} outAt={b0 + 2} style={{ fontFamily: LABEL, fontWeight: 800,
              fontSize: 28 * k, letterSpacing: "0.34em", paddingLeft: "0.34em", color: accent, whiteSpace: "nowrap",
              marginBottom: 2 * k, textShadow: "0 2px 14px rgba(0,0,0,.6)" }} />
          ) : null}
          {ls.map((ln, li) => {
            const chars = Array.from(ln);
            const total = chars.reduce((s, c) => s + advance(c) * px, 0);
            let cur = (W - total) / 2;
            return (
              <div key={li} style={{ overflow: "hidden", padding: "0.3em 0.4em", margin: "-0.3em 0 -0.22em", whiteSpace: "nowrap",
                fontFamily: DISPLAY, fontSize: px, lineHeight: 1, letterSpacing: "0.05em", color: "#fff" }}>
                {chars.map((c, i) => {
                  const w = advance(c) * px;
                  const lx = (cur + w / 2) / W;
                  cur += w;
                  const inAt = crossIn(lx) - 2 + li * 2;
                  const outAt = crossOut(lx);
                  const pin = ramp(frame, inAt, 11);
                  const pout = ramp(frame, outAt, 8, expoIn);
                  const g = interpolate(frame, [inAt, inAt + 2, inAt + 16], [0, 1, 0], clamp);
                  return (
                    <span key={i} style={{ display: "inline-block", whiteSpace: "pre",
                      transform: `translateY(${(1 - pin) * 150 - pout * 150}%)`, opacity: pin < 0.02 || pout > 0.98 ? 0 : 1,
                      textShadow: `0 0 ${(6 + 18 * g) * k}px ${withAlpha(accent, 0.2 + 0.7 * g)}, 0 6px 24px rgba(0,0,0,.55)` }}>
                      {c}
                    </span>
                  );
                })}
              </div>
            );
          })}
        </div>
      ) : null}
      {E > 0.003 ? (
        <AbsoluteFill style={{ mixBlendMode: "screen", pointerEvents: "none" }}>
          <AbsoluteFill style={{ opacity: E,
            background: `radial-gradient(ellipse 70% 55% at ${xs.toFixed(2)}% ${((Y / H) * 100).toFixed(2)}%, rgba(255,247,235,.2) 0%, rgba(255,247,235,.05) 45%, rgba(0,0,0,0) 75%)` }} />
          <div style={{ position: "absolute", left: 0, right: 0, top: Y - 120 * k, height: 240 * k, opacity: E,
            background: `radial-gradient(ellipse 62% 15% at ${xs.toFixed(2)}% 50%, rgba(255,255,255,.9) 0%, ${withAlpha(accent, 0.55)} 20%, ${withAlpha(accent, 0.14)} 48%, rgba(0,0,0,0) 72%)` }} />
          <div style={{ position: "absolute", left: 0, right: 0, top: Y - 9 * k, height: 18 * k, opacity: E * 0.9,
            background: `linear-gradient(90deg, rgba(0,0,0,0) ${(xs - 58).toFixed(2)}%, ${withAlpha(accent, 0.5)} ${xs.toFixed(2)}%, rgba(0,0,0,0) ${(xs + 58).toFixed(2)}%)`,
            WebkitMaskImage: "linear-gradient(180deg, rgba(0,0,0,0) 0%, #000 50%, rgba(0,0,0,0) 100%)",
            maskImage: "linear-gradient(180deg, rgba(0,0,0,0) 0%, #000 50%, rgba(0,0,0,0) 100%)" }} />
          <div style={{ position: "absolute", left: 0, right: 0, top: Y - 1.5 * k, height: 3 * k, opacity: E,
            background: `linear-gradient(90deg, rgba(255,255,255,0) ${(xs - 75).toFixed(2)}%, rgba(255,255,255,.95) ${xs.toFixed(2)}%, rgba(255,255,255,0) ${(xs + 75).toFixed(2)}%)` }} />
          {[-1, 1].map((s) => (
            <div key={s} style={{ position: "absolute", left: 0, right: 0, top: Y + s * 30 * k, height: 1.5 * k, opacity: E * 0.45,
              background: `linear-gradient(90deg, rgba(255,255,255,0) ${(xs - 40).toFixed(2)}%, rgba(255,255,255,.8) ${(xs + s * 6).toFixed(2)}%, rgba(255,255,255,0) ${(xs + 40).toFixed(2)}%)` }} />
          ))}
          <div style={{ position: "absolute", left: hx - 280 * k, top: Y - 280 * k, width: 560 * k, height: 560 * k, opacity: E,
            background: `radial-gradient(circle, rgba(255,255,255,1) 0%, rgba(255,251,242,.75) 5%, ${withAlpha(accent, 0.38)} 18%, ${withAlpha(accent, 0.08)} 40%, rgba(0,0,0,0) 62%)` }} />
          <div style={{ position: "absolute", left: hx - 1 * k, top: Y - 150 * k, width: 2 * k, height: 300 * k, opacity: E * 0.5,
            background: "linear-gradient(180deg, rgba(255,255,255,0), rgba(255,255,255,.9) 50%, rgba(255,255,255,0))" }} />
          <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, opacity: E }}>
            {GHOSTS.map((g, i) => {
              const gx = hx + (gcx - hx) * g.s;
              const gy = Y + (gcy - Y) * g.s;
              return (
                <path key={i} d={hexPath(gx, gy, g.r * k)} fill={withAlpha(accent, g.f)} stroke="rgba(255,255,255,.12)"
                  strokeWidth={1.2 * k} />
              );
            })}
          </svg>
        </AbsoluteFill>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== 3. dust motes
type Mote = {
  x: number; y: number; vx: number; vy: number; ax: number; ay: number; fx: number; fy: number;
  p: number; r: number; a: number; tw: number; layer: number;
};
const MOTE_LAYERS = [
  { n: 36, r: [0.9, 1.7], a: [0.22, 0.5], vx: [-8, 14], vy: [-12, -3], ax: [6, 18], par: 0.8 },
  { n: 22, r: [1.8, 3.2], a: [0.35, 0.7], vx: [-14, 22], vy: [-20, -5], ax: [10, 28], par: 1.1 },
  { n: 9, r: [9, 24], a: [0.55, 0.9], vx: [-20, 34], vy: [-28, -8], ax: [18, 46], par: 1.6 },
];
const MOTES: Mote[] = MOTE_LAYERS.flatMap((s, layer) => Array.from({ length: s.n }, (_, i) => {
  const q = (j: number): number => rnd(layer * 1009 + i * 37 + j * 7 + 11);
  return {
    x: q(1), y: q(2), vx: lerp(s.vx, q(3)) * s.par, vy: lerp(s.vy, q(4)) * s.par, ax: lerp(s.ax, q(5)),
    ay: lerp(s.ax, q(6)) * 0.7, fx: 0.08 + q(7) * 0.22, fy: 0.07 + q(8) * 0.2, p: q(9) * TAU, r: lerp(s.r, q(10)),
    a: lerp(s.a, q(11)), tw: 0.8 + q(12) * 2.2, layer,
  };
}));

/**
 * Dust in the air of the shot: a warm shaft of light slanting in from the top
 * left, sixty-odd motes at three depths drifting and rising slowly (far specks,
 * mid motes, soft near bokeh with a bright rim), each flaring as it crosses the
 * beam. Optional: a source line and a year low left beside an accent rule.
 */
const DustMotes: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width: W, height: H, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const t = frame / fps;
  const id = `fxdust${Math.round(overlay.startFrame || 0)}`;
  const vis = ramp(frame, 0, 20) * (1 - ramp(frame, D - 16, 14, inOut));
  const title = lines(cap(overlay.text), 30).slice(0, 2);
  const sub = cap(overlay.subtitle);
  const rule = ramp(frame, 12, 16) * (1 - ramp(frame, D - 14, 10, expoIn));
  const mar = 60 * k;
  // The shaft: from above the top left toward the lower middle.
  const ax0 = W * 0.2, ay0 = -H * 0.18, bx0 = W * 0.64, by0 = H * 1.18;
  const vx = bx0 - ax0, vy = by0 - ay0;
  const len = Math.hypot(vx, vy);
  const dx = vx / len, dy = vy / len;
  const nx = -dy, ny = dx;
  const half = 230 * k;
  const ang = (Math.atan2(-vx, vy) * 180) / Math.PI;
  const sway = Math.sin(t * 0.45) * 0.7;
  const shimmer = 0.78 + 0.22 * Math.sin(t * 1.15 + 0.6);
  const beamFade = "linear-gradient(180deg, #000 0%, rgba(0,0,0,.7) 55%, rgba(0,0,0,0) 100%)";
  return (
    <AbsoluteFill style={{ overflow: "hidden", pointerEvents: "none" }}>
      <AbsoluteFill style={{ mixBlendMode: "screen", opacity: vis }}>
        <div style={{ position: "absolute", left: ax0 - half, top: ay0, width: 2 * half, height: len, transformOrigin: "50% 0%",
          transform: `rotate(${(ang + sway).toFixed(3)}deg)`, opacity: shimmer,
          background: "linear-gradient(90deg, rgba(255,238,212,0) 0%, rgba(255,238,212,.09) 24%, rgba(255,238,212,.16) 50%, rgba(255,238,212,.09) 76%, rgba(255,238,212,0) 100%)",
          WebkitMaskImage: beamFade, maskImage: beamFade }} />
        <div style={{ position: "absolute", left: ax0 + nx * 330 * k - 80 * k, top: ay0 + ny * 330 * k, width: 160 * k,
          height: len * 0.9, transformOrigin: "50% 0%", transform: `rotate(${(ang + sway * 1.3).toFixed(3)}deg)`,
          opacity: 1.1 - shimmer,
          background: "linear-gradient(90deg, rgba(255,238,212,0) 0%, rgba(255,238,212,.08) 50%, rgba(255,238,212,0) 100%)",
          WebkitMaskImage: beamFade, maskImage: beamFade }} />
      </AbsoluteFill>
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
        <defs>
          <radialGradient id={`${id}h`}>
            <stop offset="0%" stopColor="#fff3dc" stopOpacity={0.8} />
            <stop offset="100%" stopColor="#fff3dc" stopOpacity={0} />
          </radialGradient>
          <radialGradient id={`${id}k`}>
            <stop offset="0%" stopColor="#fff4e2" stopOpacity={0.22} />
            <stop offset="64%" stopColor="#fff4e2" stopOpacity={0.14} />
            <stop offset="86%" stopColor="#fff4e2" stopOpacity={0.3} />
            <stop offset="100%" stopColor="#fff4e2" stopOpacity={0} />
          </radialGradient>
        </defs>
        {vis > 0.001 ? MOTES.map((m, i) => {
          const x = wrap(m.x * (W + 2 * mar) + (m.vx * t + m.ax * Math.sin(m.fx * TAU * t + m.p)) * k, W + 2 * mar) - mar;
          const y = wrap(m.y * (H + 2 * mar) + (m.vy * t + m.ay * Math.sin(m.fy * TAU * t + m.p * 1.7)) * k, H + 2 * mar) - mar;
          const rx = x - ax0, ry = y - ay0;
          const along = rx * dx + ry * dy;
          const across = Math.abs(rx * nx + ry * ny);
          const beam = along > 0 && along < len
            ? Math.pow(Math.max(0, 1 - across / half), 1.5) * (1 - 0.55 * (along / len)) : 0;
          const tw = 0.55 + 0.45 * Math.sin(t * m.tw + m.p * 3);
          const o = Math.min(1, m.a * (0.5 + 0.5 * tw) * (1 + 2.2 * beam)) * vis;
          if (o < 0.01) return null;
          const r = m.r * k * (1 + 0.3 * beam);
          if (m.layer === 2) return <circle key={i} cx={x} cy={y} r={r} fill={`url(#${id}k)`} opacity={o} />;
          return (
            <g key={i}>
              {m.layer === 1 && beam > 0.2 ? <circle cx={x} cy={y} r={r * 3.4} fill={`url(#${id}h)`} opacity={o * beam} /> : null}
              <circle cx={x} cy={y} r={r} fill="#fff6ea" opacity={o} />
            </g>
          );
        }) : null}
      </svg>
      {title.length ? (
        <>
          <AbsoluteFill style={{ opacity: ramp(frame, 8, 14) * (1 - ramp(frame, D - 12, 10)),
            background: "radial-gradient(ellipse 46% 34% at 12% 88%, rgba(0,0,0,.42) 0%, rgba(0,0,0,0) 100%)" }} />
          <div style={{ position: "absolute", left: 110 * k, bottom: 110 * k, display: "flex", alignItems: "stretch", gap: 18 * k }}>
            <div style={{ width: 3 * k, background: accent, transform: `scaleY(${rule})`, transformOrigin: "50% 0%" }} />
            <div style={{ display: "flex", flexDirection: "column", gap: 4 * k }}>
              {title.map((ln, i) => (
                <Letters key={i} text={ln} at={14 + i * 4} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 30 * k,
                  letterSpacing: "0.28em", color: "rgba(255,255,255,.94)", whiteSpace: "nowrap",
                  textShadow: "0 2px 14px rgba(0,0,0,.6)" }} />
              ))}
              {sub ? (
                <Letters text={sub} at={20 + title.length * 4} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 26 * k,
                  letterSpacing: "0.34em", color: accent, whiteSpace: "nowrap", textShadow: "0 2px 14px rgba(0,0,0,.6)" }} />
              ) : null}
            </div>
          </div>
        </>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== 4. HUD scan
/**
 * A thin HUD over the footage: an 80 px grid draws out from the centre (every
 * fourth line brighter), corner brackets close in, a ruler runs along the top.
 * A cyan scan line sweeps down and up with a phosphor trail, lighting the grid
 * crossings it passes; mono readouts type in (tag, grid and pass, timecode,
 * sweep direction, analysis progress); the subject rises low left with its
 * coordinates typed above it.
 */
const HudScan: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width: W, height: H, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const ex = useExit(14, 12);
  const on = ramp(frame, 0, 10) * (1 - ex);
  const loc: MapLocation | undefined = (overlay.locations || []).find((l) => Boolean(l)
    && Number.isFinite(Number(l.lat)) && Number.isFinite(Number(l.lon))
    && Math.abs(Number(l.lat)) <= 90 && Math.abs(Number(l.lon)) <= 180);
  const main = cap(overlay.text) || cap((loc?.label || "").split(",")[0]);
  const mainLs = lines(main, 30).slice(0, 2);
  const tag = Array.from(cap(overlay.label) || "SCAN").slice(0, 22).join("");
  const coord = loc
    ? `${Math.abs(Number(loc.lat)).toFixed(4)}°${Number(loc.lat) >= 0 ? "N" : "S"}  ${Math.abs(Number(loc.lon)).toFixed(4)}°${Number(loc.lon) >= 0 ? "E" : "W"}`
    : cap(overlay.subtitle);
  const S = 80 * k, M = 90 * k;
  const cx = W / 2, cy = H / 2;
  const cols = Math.floor(W / S), rows = Math.floor(H / S);
  const gx0 = (W - cols * S) / 2, gy0 = (H - rows * S) / 2;
  // The grid, drawn out from the centre.
  let minor = "";
  let major = "";
  for (let i = 0; i <= cols; i++) {
    const x = gx0 + i * S;
    const p = ramp(frame, 2 + (Math.abs(x - cx) / W) * 18, 16) * (1 - ex);
    if (p < 0.002) continue;
    const hh = (H / 2 + 10 * k) * p;
    const seg = `M${x.toFixed(1)} ${(cy - hh).toFixed(1)}V${(cy + hh).toFixed(1)}`;
    if ((i - Math.round(cols / 2)) % 4 === 0) major += seg;
    else minor += seg;
  }
  for (let j = 0; j <= rows; j++) {
    const y = gy0 + j * S;
    const p = ramp(frame, 2 + (Math.abs(y - cy) / H) * 14, 16) * (1 - ex);
    if (p < 0.002) continue;
    const hw = (W / 2 + 10 * k) * p;
    const seg = `M${(cx - hw).toFixed(1)} ${y.toFixed(1)}H${(cx + hw).toFixed(1)}`;
    if ((j - Math.round(rows / 2)) % 4 === 0) major += seg;
    else minor += seg;
  }
  // The scan: down, pause, up, pause... until the graphic leaves.
  const s0 = 8;
  const sweep = Math.max(20, Math.round(fps * 1.25));
  const pause = Math.round(fps * 0.3);
  const yA = M + 12 * k, yB = H - M - 12 * k;
  const scanEnd = Math.max(s0 + sweep, D - 16);
  const scanY = (f: number): number => {
    if (f <= s0) return yA;
    const cyc = sweep + pause;
    const n = Math.floor((f - s0) / cyc);
    const p = inOut(Math.min(1, (f - s0 - n * cyc) / sweep));
    return n % 2 === 0 ? yA + (yB - yA) * p : yB - (yB - yA) * p;
  };
  const fNow = Math.min(frame, scanEnd);
  const sy = scanY(fNow);
  const sPrev = scanY(fNow - 1);
  const moving = Math.abs(sy - sPrev) > 0.3 && frame < scanEnd;
  const down = sy >= sPrev;
  const sweeps = frame > s0 ? Math.floor((fNow - s0) / (sweep + pause)) + 1 : 0;
  const scanOn = ramp(frame, s0 - 2, 6) * on * (1 - ramp(frame, scanEnd, 8));
  // The rows the line has crossed, and when: their crossings flash and fade.
  const rowY = Array.from({ length: rows + 1 }, (_, j) => gy0 + j * S);
  const lastHit = rowY.map(() => -1e9);
  let prevY = scanY(s0);
  for (let f = s0 + 1; f <= fNow; f++) {
    const y = scanY(f);
    if (y !== prevY) {
      for (let j = 0; j < rowY.length; j++) {
        if ((prevY - rowY[j]) * (y - rowY[j]) <= 0) lastHit[j] = f;
      }
    }
    prevY = y;
  }
  const flashes = rowY.map((ry, j) => {
    const age = frame - lastHit[j];
    const q = age >= 0 && age < 40 ? Math.exp(-age / 7) : 0;
    if (q < 0.04) return null;
    let d = "";
    for (let i = 0; i <= cols; i++) {
      const x = gx0 + i * S;
      if (x < M - 1 || x > W - M + 1) continue;
      d += `M${(x - 7 * k).toFixed(1)} ${ry.toFixed(1)}H${(x + 7 * k).toFixed(1)}M${x.toFixed(1)} ${(ry - 7 * k).toFixed(1)}V${(ry + 7 * k).toFixed(1)}`;
    }
    return <path key={j} d={d} stroke={CYAN} strokeWidth={1.6 * k} fill="none" opacity={q * on} />;
  });
  // Corner brackets closing in, a ruler drawing out along the top.
  const bp = ramp(frame, 0, 16) * (1 - ex);
  const off = (1 - bp) * 46 * k;
  const L = 58 * k;
  const bl = M - off, bt = M - off, br = W - M + off, bb = H - M + off;
  const brackets = `M${bl} ${bt + L}V${bt}H${bl + L}M${br - L} ${bt}H${br}V${bt + L}M${br} ${bb - L}V${bb}H${br - L}M${bl + L} ${bb}H${bl}V${bb - L}`;
  // The ruler stays between the two readout blocks in the top corners.
  const rp = ramp(frame, 6, 20) * (1 - ex);
  const rulerY = M + 16 * k;
  const rulerHalf = Math.max(80 * k, W / 2 - M - 460 * k);
  const span = rulerHalf * rp;
  const nT = Math.floor(rulerHalf / (20 * k));
  let ticks = "";
  const marks: { x: number; v: number }[] = [];
  for (let i = -nT; i <= nT; i++) {
    const x = cx + i * 20 * k;
    if (Math.abs(x - cx) > span) continue;
    ticks += `M${x.toFixed(1)} ${rulerY.toFixed(1)}V${(rulerY + (i % 4 === 0 ? 12 : 5) * k).toFixed(1)}`;
    if (i % 16 === 0) marks.push({ x, v: i * 20 });
  }
  const outAt = D - 14;
  const pct = Math.round(interpolate(frame, [s0, Math.max(s0 + 1, D - 24)], [0, 100], clamp));
  const blink = Math.floor(frame / 12) % 2 === 0 ? 1 : 0.3;
  const mono = (size: number, weight: number, color: string): React.CSSProperties => ({ fontFamily: MONO, fontWeight: weight,
    fontSize: size * k, letterSpacing: "0.14em", color, whiteSpace: "pre", lineHeight: 1.25, textShadow: "0 2px 10px rgba(0,0,0,.7)" });
  return (
    <AbsoluteFill style={{ overflow: "hidden", pointerEvents: "none" }}>
      <AbsoluteFill style={{ opacity: on, background: "linear-gradient(180deg, rgba(0,0,0,.3) 0%, rgba(0,0,0,0) 20%)" }} />
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0,
        WebkitMaskImage: "radial-gradient(ellipse 72% 72% at 50% 50%, #000 45%, rgba(0,0,0,.25) 85%, rgba(0,0,0,0) 100%)",
        maskImage: "radial-gradient(ellipse 72% 72% at 50% 50%, #000 45%, rgba(0,0,0,.25) 85%, rgba(0,0,0,0) 100%)" }}>
        <path d={minor} stroke="rgba(255,255,255,.1)" strokeWidth={1 * k} fill="none" />
        <path d={major} stroke="rgba(255,255,255,.2)" strokeWidth={1.2 * k} fill="none" />
        {flashes}
      </svg>
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
        <path d={brackets} stroke="rgba(255,255,255,.88)" strokeWidth={2.5 * k} fill="none" opacity={bp} />
        <path d={ticks} stroke="rgba(255,255,255,.55)" strokeWidth={1.2 * k} fill="none" />
        {marks.map((m) => (
          <text key={m.v} x={m.x} y={rulerY + 34 * k} textAnchor="middle" fontFamily={MONO} fontSize={14 * k}
            fill="rgba(255,255,255,.5)" opacity={rp}>{m.v > 0 ? `+${m.v}` : `${m.v}`}</text>
        ))}
        <path d={`M${cx - 7 * k} ${rulerY + 22 * k}L${cx + 7 * k} ${rulerY + 22 * k}L${cx} ${rulerY + 13 * k}Z`} fill={accent}
          opacity={rp} />
      </svg>
      <div style={{ position: "absolute", left: M, right: M, top: down ? sy - 150 * k : sy, height: 150 * k,
        opacity: scanOn * (moving ? 1 : 0.35),
        background: down ? "linear-gradient(180deg, rgba(83,200,255,0) 0%, rgba(83,200,255,.16) 100%)"
          : "linear-gradient(0deg, rgba(83,200,255,0) 0%, rgba(83,200,255,.16) 100%)" }} />
      <div style={{ position: "absolute", left: M - 20 * k, right: M - 20 * k, top: sy - 1 * k, height: 2 * k, opacity: scanOn,
        background: "linear-gradient(90deg, rgba(83,200,255,0) 0%, rgba(83,200,255,.9) 10%, #e9f8ff 50%, rgba(83,200,255,.9) 90%, rgba(83,200,255,0) 100%)",
        boxShadow: `0 0 ${12 * k}px rgba(83,200,255,.8)` }} />
      <div style={{ position: "absolute", right: M + 10 * k, top: sy - 32 * k, opacity: scanOn, ...mono(20, 500, CYAN) }}>
        Y {String(Math.round(sy / k)).padStart(4, "0")}
      </div>
      <div style={{ position: "absolute", left: M + 24 * k, top: M + 44 * k, display: "flex", flexDirection: "column", gap: 6 * k }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 * k }}>
          <div style={{ width: 11 * k, height: 11 * k, borderRadius: "50%", background: accent, opacity: on * blink,
            boxShadow: `0 0 ${10 * k}px ${withAlpha(accent, 0.7)}` }} />
          <span style={mono(24, 700, "rgba(255,255,255,.94)")}>{typed(tag, frame, 10, 1.4, outAt, 10)}</span>
        </div>
        <span style={mono(20, 500, "rgba(255,255,255,.62)")}>
          {typed(`GRID ${Math.round(S / k)} · PASS ${pad2(Math.max(1, sweeps))}`, frame, 16, 1.6, outAt, 10)}
        </span>
      </div>
      <div style={{ position: "absolute", right: M + 24 * k, top: M + 44 * k, display: "flex", flexDirection: "column",
        alignItems: "flex-end", gap: 6 * k }}>
        <span style={mono(24, 700, "rgba(255,255,255,.94)")}>
          {typed(`REC ${timecode(Math.round(overlay.startFrame || 0) + frame, fps)}`, frame, 12, 1.6, outAt, 10)}
        </span>
        <span style={mono(20, 500, "rgba(255,255,255,.62)")}>
          {typed(`SWEEP ${pad2(Math.max(1, sweeps))} ${down ? "▼" : "▲"}`, frame, 18, 1.6, outAt, 10)}
        </span>
      </div>
      <div style={{ position: "absolute", right: M + 24 * k, bottom: M + 30 * k, display: "flex", flexDirection: "column",
        alignItems: "flex-end", gap: 10 * k, opacity: on }}>
        <span style={mono(20, 500, "rgba(255,255,255,.7)")}>{typed(`ANALYSIS ${String(pct).padStart(3, "0")}%`, frame, 20, 1.6, outAt, 10)}</span>
        <div style={{ position: "relative", width: 240 * k, height: 3 * k, background: "rgba(255,255,255,.18)",
          transform: `scaleX(${ramp(frame, 14, 16)})`, transformOrigin: "100% 50%" }}>
          <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${pct}%`, background: CYAN,
            boxShadow: `0 0 ${8 * k}px ${CYAN}` }} />
        </div>
      </div>
      {mainLs.length || coord ? (
        <>
          <AbsoluteFill style={{ opacity: on,
            background: "radial-gradient(ellipse 50% 36% at 14% 86%, rgba(0,0,0,.45) 0%, rgba(0,0,0,0) 100%)" }} />
          <div style={{ position: "absolute", left: M + 24 * k, bottom: M + 26 * k, display: "flex", flexDirection: "column",
            gap: 8 * k }}>
            {coord ? (
              <div style={{ ...mono(24, 500, CYAN), minHeight: 30 * k }}>{typed(coord, frame, 20, 1.8, outAt, 10)}</div>
            ) : null}
            {mainLs.length ? (
              <div style={{ display: "flex", alignItems: "stretch", gap: 16 * k }}>
                <div style={{ width: 4 * k, background: accent, transform: `scaleY(${ramp(frame, 18, 14) * (1 - ex)})`,
                  transformOrigin: "50% 100%" }} />
                <div style={{ display: "flex", flexDirection: "column" }}>
                  {mainLs.map((ln, i) => (
                    <Letters key={i} text={ln} at={22 + i * 4} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 46 * k,
                      letterSpacing: "0.06em", lineHeight: 1.02, color: "#fff", whiteSpace: "nowrap",
                      textShadow: "0 3px 16px rgba(0,0,0,.6)" }} />
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== 5. film burn
const EMBERS = Array.from({ length: 18 }, (_, i) => ({
  a: ((100 + rnd(i * 53 + 1) * 160) * Math.PI) / 180,
  at: 4 + Math.round(rnd(i * 47 + 2) * 16),
  v: 220 + rnd(i * 41 + 3) * 380,
  up: 60 + rnd(i * 37 + 4) * 160,
  r: 1.8 + rnd(i * 31 + 5) * 3.2,
  life: 14 + Math.round(rnd(i * 29 + 6) * 16),
}));

/**
 * The film burns: warm light floods in from the right edge with a flicker and
 * a light leak crossing the frame, then a white-hot hole with a charred rim
 * and a glowing ember edge eats in from the edge, throwing embers, and the
 * whole burn fades back to the shot in about 1.7 s. Optional: a date or era
 * rising low left in the afterglow.
 */
const FilmBurn: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width: W, height: H, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const title = cap(overlay.text);
  const kicker = cap(overlay.label);
  const sub = cap(overlay.subtitle);
  const { size, ls } = fit(title, 72, 22, 2);
  const t = frame / fps;
  const id = `fxburn${Math.round(overlay.startFrame || 0)}`;
  const ox = W + 40 * k, oy = H * 0.34;
  const env = interpolate(frame, [0, 4, 14, 30, 52], [0, 0.9, 1, 0.45, 0], clamp);
  const flick = frame < 52 ? rnd(Math.floor(frame / 2) * 7 + 3) : 0;
  const holeR = (f: number): number => (40 + 780 * ramp(f, 3, 22, quintOut) + 120 * ramp(f, 22, 30)) * k;
  const rH = holeR(frame);
  const hO = interpolate(frame, [3, 7, 22, 46], [0, 1, 1, 0], clamp);
  const leak = interpolate(frame, [0, 44], [112, 26], clamp);
  const warm = interpolate(frame, [14, 30, 64], [0.9, 0.6, 0], clamp);
  const live = frame < 56;
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      {live ? (
        <AbsoluteFill style={{ mixBlendMode: "screen", pointerEvents: "none" }}>
          <AbsoluteFill style={{ opacity: env * (0.8 + 0.2 * flick),
            background: "radial-gradient(ellipse 95% 95% at 100% 34%, rgba(255,214,150,.8) 0%, rgba(255,140,50,.5) 26%, rgba(210,60,12,.2) 52%, rgba(0,0,0,0) 76%)" }} />
          <AbsoluteFill style={{ opacity: env * (0.05 + 0.13 * flick), background: "#fff1dc" }} />
          <AbsoluteFill style={{ opacity: env * 0.75,
            background: `linear-gradient(104deg, rgba(0,0,0,0) ${(leak - 18).toFixed(2)}%, rgba(255,170,90,.36) ${(leak - 4).toFixed(2)}%, rgba(255,110,40,.2) ${(leak + 6).toFixed(2)}%, rgba(0,0,0,0) ${(leak + 20).toFixed(2)}%)` }} />
        </AbsoluteFill>
      ) : null}
      {live ? (
        <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
          <defs>
            <radialGradient id={`${id}h`} gradientUnits="userSpaceOnUse" cx={ox} cy={oy} r={Math.max(1, rH * 1.15)}>
              <stop offset="0%" stopColor="#ffffff" />
              <stop offset="40%" stopColor="#fff5dc" />
              <stop offset="64%" stopColor="#ffd58c" />
              <stop offset="80%" stopColor="#ffa244" />
              <stop offset="92%" stopColor="#ff6a1e" />
              <stop offset="100%" stopColor="#b8300c" />
            </radialGradient>
            <filter id={`${id}b`} filterUnits="userSpaceOnUse" x={-W * 0.2} y={-H * 0.2} width={W * 1.4} height={H * 1.4}>
              <feGaussianBlur stdDeviation={7 * k} />
            </filter>
          </defs>
          {hO > 0.001 ? (
            <g>
              <path d={blobPath(ox, oy, rH * 1.012, 5, t, 1.25, 9, 150)} fill="none" stroke="#2a0b03" strokeWidth={26 * k}
                opacity={0.55 * hO} filter={`url(#${id}b)`} />
              <path d={blobPath(ox, oy, rH, 5, t, 1.25, 9, 150)} fill={`url(#${id}h)`} opacity={0.97 * hO} />
              <path d={blobPath(ox, oy, rH * 0.985, 5, t, 1.25, 9, 150)} fill="none" stroke="#ff8a2e" strokeWidth={3 * k}
                opacity={0.8 * hO} />
            </g>
          ) : null}
          {EMBERS.map((e, i) => {
            const age = frame - e.at;
            if (age < 0 || age > e.life) return null;
            const q = age / e.life;
            const s = age / fps;
            const r0 = holeR(e.at);
            const x = ox + Math.cos(e.a) * (r0 + e.v * s * k);
            const y = oy + Math.sin(e.a) * (r0 + e.v * s * k) - e.up * s * s * k;
            const o = (1 - q) * Math.min(1, q * 6);
            return (
              <g key={i} opacity={o}>
                <circle cx={x} cy={y} r={e.r * 2.8 * k} fill="rgba(255,140,50,.35)" />
                <circle cx={x} cy={y} r={e.r * k} fill="#ffe2b0" />
              </g>
            );
          })}
        </svg>
      ) : null}
      {title ? (
        <>
          <AbsoluteFill style={{ opacity: ramp(frame, 12, 14) * (1 - ramp(frame, D - 12, 10)),
            background: "radial-gradient(ellipse 50% 38% at 14% 84%, rgba(0,0,0,.5) 0%, rgba(0,0,0,0) 100%)" }} />
          <div style={{ position: "absolute", left: 110 * k, bottom: 120 * k, display: "flex", flexDirection: "column",
            gap: 4 * k, transform: `scale(${hold})`, transformOrigin: "0% 100%" }}>
            {kicker ? (
              <Letters text={kicker} at={16} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 28 * k, letterSpacing: "0.32em",
                color: accent, whiteSpace: "nowrap", textShadow: "0 2px 14px rgba(0,0,0,.6)" }} />
            ) : null}
            {ls.map((ln, i) => (
              <Letters key={i} text={ln} at={19 + i * 5} style={{ fontFamily: DISPLAY, fontSize: size * k, lineHeight: 0.98,
                letterSpacing: "0.03em", color: "#fff", whiteSpace: "nowrap",
                textShadow: `0 0 ${24 * k * warm}px rgba(255,150,60,${(0.45 * warm).toFixed(3)}), 0 6px 26px rgba(0,0,0,.55)` }} />
            ))}
            {sub ? (
              <Letters text={sub} at={26} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 30 * k, letterSpacing: "0.2em",
                color: "rgba(255,255,255,.75)", whiteSpace: "nowrap", textShadow: "0 2px 14px rgba(0,0,0,.6)" }} />
            ) : null}
          </div>
        </>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== 6. shape wipe
type WipeShape = {
  kind: "bar" | "tri"; w: number; y0: number; y1: number; tone: "ink" | "accent" | "white"; lag: number; off: number;
  alpha: number;
};
/** Left to right in the group: offsets and widths at 1080p, lag in frames. */
const WIPE: WipeShape[] = [
  { kind: "bar", w: 14, y0: -0.1, y1: 1.1, tone: "white", lag: 3, off: -470, alpha: 0.9 },
  { kind: "bar", w: 140, y0: -0.1, y1: 1.1, tone: "accent", lag: 2, off: -300, alpha: 1 },
  { kind: "tri", w: 300, y0: 0.5, y1: 1.06, tone: "ink", lag: 2.4, off: -380, alpha: 0.96 },
  { kind: "bar", w: 520, y0: -0.1, y1: 1.1, tone: "ink", lag: 1.2, off: -120, alpha: 0.96 },
  { kind: "bar", w: 34, y0: -0.1, y1: 1.1, tone: "white", lag: 0.6, off: 430, alpha: 1 },
  { kind: "tri", w: 250, y0: -0.06, y1: 0.5, tone: "accent", lag: 0, off: 560, alpha: 1 },
];
const SKEW = 0.36;
/** Fast in, a glide through the middle, fast out. */
const whip = (u: number): number => {
  const c = Math.max(0, Math.min(1, u));
  return c + (0.6 * Math.sin(TAU * c)) / TAU;
};

/**
 * Skewed bars and triangles (ink, accent, white) whip across the frame as one
 * staggered group, each smeared along its motion like a real motion blur,
 * gliding through the middle. With a word: the trailing accent dash slides in
 * behind them and parks as its underline low left, the word rises over it,
 * and at the end the dash whips out to the right as the letters leave.
 */
const ShapeWipe: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const title = cap(overlay.text);
  const kicker = cap(overlay.label);
  const { size, ls } = fit(title, 72, 22, 2);
  const id = `fxwipe${Math.round(overlay.startFrame || 0)}`;
  const PASS = 30;
  const x0 = -1060 * k, x1 = W + 720 * k;
  const X = (f: number, lag: number): number => x0 + (x1 - x0) * whip((f - lag) / PASS);
  const cy = H / 2;
  const tone = (s: WipeShape): string => (s.tone === "ink" ? "#0d0e11" : s.tone === "white" ? "#f4f3ef" : accent);
  const shapes = frame <= PASS + 6 ? WIPE.map((s, i) => {
    const xa = X(frame, s.lag) + s.off * k;
    const xp = X(frame - 1, s.lag) + s.off * k;
    const sm = Math.min(260 * k, Math.abs(xa - xp) * 0.85);
    const w = s.w * k;
    const yA = s.y0 * H, yB = s.y1 * H;
    const lean = s.kind === "bar" ? SKEW : 0;
    const reach = lean * H * 0.62;
    if (xa + w + sm + reach < -20 * k || xa - sm - reach > W + 20 * k) return null;
    const uL = xa + lean * cy;
    const spanW = w + sm;
    const f = spanW > 0 ? Math.min(0.5, sm / spanW) : 0;
    const peak = sm > w ? Math.max(0.3, w / sm) : 1;
    const col = tone(s);
    const gid = `${id}g${i}`;
    const e2 = sm / 2;
    const points = s.kind === "bar"
      ? [[xa - e2 + lean * (cy - yA), yA], [xa + w + e2 + lean * (cy - yA), yA], [xa + w + e2 + lean * (cy - yB), yB],
        [xa - e2 + lean * (cy - yB), yB]]
      : [[xa - e2, yA], [xa + w + e2, (yA + yB) / 2], [xa - e2, yB]];
    return (
      <g key={i}>
        <defs>
          <linearGradient id={gid} gradientUnits="userSpaceOnUse" x1={uL - e2} y1={0} x2={uL + w + e2} y2={0}
            gradientTransform={lean ? `matrix(1 0 ${-lean} 1 0 0)` : undefined}>
            <stop offset={0} stopColor={col} stopOpacity={0} />
            <stop offset={f} stopColor={col} stopOpacity={s.alpha * peak} />
            <stop offset={1 - f} stopColor={col} stopOpacity={s.alpha * peak} />
            <stop offset={1} stopColor={col} stopOpacity={0} />
          </linearGradient>
        </defs>
        <polygon points={points.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ")} fill={`url(#${gid})`} />
      </g>
    );
  }) : null;
  const est = Math.max(4, ...ls.map((l) => l.length)) * size * 0.46 * k;
  const dashW = Math.min(560 * k, Math.max(160 * k, est * 0.6));
  const tx = 110 * k;
  const dashIn = ramp(frame, 12, 22, quintOut);
  const dashOut = ramp(frame, D - 15, 11, expoIn);
  const dashX = interpolate(dashIn, [0, 1], [-dashW - 300 * k, tx]) + dashOut * (W + 300 * k - tx);
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      {title ? (
        <>
          <AbsoluteFill style={{ opacity: ramp(frame, 14, 14) * (1 - ramp(frame, D - 12, 10)),
            background: "radial-gradient(ellipse 52% 40% at 16% 82%, rgba(0,0,0,.45) 0%, rgba(0,0,0,0) 100%)" }} />
          <div style={{ position: "absolute", left: tx, bottom: 150 * k, display: "flex", flexDirection: "column", gap: 2 * k,
            transform: `scale(${hold})`, transformOrigin: "0% 100%" }}>
            {kicker ? (
              <Letters text={kicker} at={18} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 28 * k, letterSpacing: "0.3em",
                color: accent, whiteSpace: "nowrap", marginBottom: 4 * k, textShadow: "0 2px 14px rgba(0,0,0,.6)" }} />
            ) : null}
            {ls.map((ln, i) => (
              <Letters key={i} text={ln} at={20 + i * 5} style={{ fontFamily: DISPLAY, fontSize: size * k, lineHeight: 0.98,
                letterSpacing: "0.03em", color: "#fff", whiteSpace: "nowrap", textShadow: "0 6px 26px rgba(0,0,0,.55)" }} />
            ))}
          </div>
          <div style={{ position: "absolute", left: dashX, bottom: 124 * k, width: dashW, height: 9 * k, background: accent,
            transform: `skewX(${((-Math.atan(SKEW) * 180) / Math.PI).toFixed(2)}deg)`,
            boxShadow: `0 0 ${16 * k}px ${withAlpha(accent, 0.45)}` }} />
        </>
      ) : null}
      {shapes ? (
        <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>{shapes}</svg>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== 7. gradient mesh
type MeshBlob = {
  tone: "accent" | "deep" | "slate" | "white" | "black"; a: number; x: number; y: number; r: number; ox: number; oy: number;
  hz: number; p: number;
};
const MESH: MeshBlob[] = [
  { tone: "black", a: 0.9, x: 0.1, y: 0.88, r: 0.55, ox: 0.04, oy: 0.03, hz: 0.05, p: 3.3 },
  { tone: "slate", a: 0.85, x: 0.84, y: 0.16, r: 0.5, ox: 0.05, oy: 0.05, hz: 0.065, p: 4.2 },
  { tone: "deep", a: 0.95, x: 0.76, y: 0.72, r: 0.64, ox: 0.06, oy: 0.07, hz: 0.055, p: 2.1 },
  { tone: "accent", a: 0.8, x: 0.26, y: 0.32, r: 0.56, ox: 0.07, oy: 0.06, hz: 0.07, p: 0 },
  { tone: "accent", a: 0.42, x: 0.94, y: 0.94, r: 0.38, ox: 0.05, oy: 0.04, hz: 0.075, p: 5.1 },
  { tone: "white", a: 0.18, x: 0.48, y: 0.56, r: 0.32, ox: 0.1, oy: 0.07, hz: 0.09, p: 1.3 },
];
const meshTone = (b: MeshBlob, accent: string, a: number): string => {
  if (b.tone === "accent") return withAlpha(accent, a);
  if (b.tone === "deep") return shade(accent, 0.62, a);
  if (b.tone === "slate") return `rgba(62,70,84,${a})`;
  if (b.tone === "white") return `rgba(255,255,255,${a})`;
  return `rgba(4,4,6,${a})`;
};

/**
 * A designed backdrop: six soft colour fields (the accent, a deep shade of
 * it, slate, charcoal, a white highlight) orbiting slowly on near-black, a
 * fine dot screen and a sheen crossing it. Over footage the mesh blooms open
 * from the centre through a soft circular edge and closes the same way; the
 * title rises in the middle with its kicker, a split rule and the subtitle.
 */
const GradientMesh: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width: W, height: H, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const title = cap(overlay.text);
  if (!title) return null;
  const full = Boolean(overlay.fullFrame);
  const kicker = cap(overlay.label);
  const sub = lines(overlay.subtitle || "", 50).slice(0, 2);
  const { size, ls } = fit(title, 86, 20, 2);
  const t = frame / fps;
  const lead = 20;
  const open = full ? 1 : ramp(frame, 0, 20, quintOut);
  const close = full ? 0 : ramp(frame, D - 13, 12, expoIn);
  const bloom = full ? ramp(frame, 0, 26, quintOut) : open;
  const rr = 125 * open * (1 - close);
  const maskImg = `radial-gradient(circle at 50% 50%, #000 ${Math.max(0, rr - 22).toFixed(2)}%, rgba(0,0,0,0) ${rr.toFixed(2)}%)`;
  const sh = interpolate(frame, [8, Math.max(9, D)], [-30, 130], clamp);
  const spread = 1 + 0.55 * (1 - bloom);
  const rule = ramp(frame, 20, 18) * (1 - ramp(frame, D - lead - 6, 10, expoIn));
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{ background: "#0b0b0d", overflow: "hidden",
        WebkitMaskImage: full ? undefined : maskImg, maskImage: full ? undefined : maskImg }}>
        {MESH.map((b, i) => {
          const bx = 0.5 + (b.x + b.ox * Math.sin(TAU * b.hz * t + b.p) - 0.5) * spread;
          const by = 0.5 + (b.y + b.oy * Math.cos(TAU * b.hz * t * 0.8 + b.p * 1.3) - 0.5) * spread;
          const R = b.r * W * (0.85 + 0.15 * bloom);
          return (
            <div key={i} style={{ position: "absolute", left: bx * W - R, top: by * H - R, width: 2 * R, height: 2 * R,
              borderRadius: "50%",
              background: `radial-gradient(circle, ${meshTone(b, accent, b.a)} 0%, ${meshTone(b, accent, b.a * 0.45)} 38%, rgba(0,0,0,0) 70%)` }} />
          );
        })}
        <AbsoluteFill style={{ opacity: 0.5, backgroundImage: "radial-gradient(rgba(255,255,255,.05) 1px, rgba(0,0,0,0) 1.4px)",
          backgroundSize: `${6 * k}px ${6 * k}px` }} />
        <AbsoluteFill style={{ background: `linear-gradient(112deg, rgba(255,255,255,0) ${(sh - 16).toFixed(2)}%, rgba(255,255,255,.07) ${sh.toFixed(2)}%, rgba(255,255,255,0) ${(sh + 16).toFixed(2)}%)` }} />
        <AbsoluteFill style={{ boxShadow: `inset 0 0 ${320 * k}px rgba(0,0,0,.6)` }} />
      </AbsoluteFill>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", maxWidth: 1600 * k }}>
          {kicker ? (
            <Letters text={kicker} at={10} lead={lead} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 28 * k,
              letterSpacing: "0.42em", paddingLeft: "0.42em", color: "rgba(255,255,255,.8)", whiteSpace: "nowrap",
              marginBottom: 14 * k }} />
          ) : null}
          {ls.map((ln, i) => (
            <Letters key={i} text={ln} at={13 + i * 5} lead={lead} style={{ fontFamily: DISPLAY, fontSize: size * k,
              lineHeight: 1, letterSpacing: "0.04em", color: "#fff", textAlign: "center", whiteSpace: "nowrap",
              textShadow: "0 10px 40px rgba(0,0,0,.35)" }} />
          ))}
          <div style={{ position: "relative", width: 240 * k, height: 2 * k, marginTop: 20 * k, background: "rgba(255,255,255,.4)",
            transform: `scaleX(${rule})` }}>
            <div style={{ position: "absolute", left: "50%", top: -1.5 * k, width: 64 * k, height: 5 * k, marginLeft: -32 * k,
              background: accent }} />
          </div>
          {sub.map((ln, i) => (
            <Rise key={`s${i}`} at={24 + i * 3} outAt={D - lead - 8} style={{ marginTop: i === 0 ? 18 * k : 0 }}>
              <span style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 30 * k, letterSpacing: "0.1em",
                color: "rgba(255,255,255,.72)" }}>{cap(ln)}</span>
            </Rise>
          ))}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 8. glitch slice
type Slice = { y: number; h: number; dx: number; tint: string; tinted: boolean };

/**
 * Three short bursts (in, middle, out) of a digital breakup: the picture
 * (a still of the shot) cut into horizontal bands shifted sideways, some
 * colour-split in cyan or the accent, a double image, an inverted band,
 * block artefacts, stray RGB lines and scanlines. Without a picture the bands
 * are drawn as corrupted data. Optional: an alert line low left that rises
 * letter by letter and jitters, colour-split, with every burst.
 */
const GlitchSlice: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const pic = stillOf((overlay.media || [])[0]);
  const title = lines(cap(overlay.text), 30).slice(0, 2);
  const kicker = cap(overlay.label);
  const bursts: [number, number][] = [[0, 10]];
  const mid = Math.round(D * 0.5);
  if (D >= 66) bursts.push([mid, mid + 6]);
  if (D >= 36) bursts.push([D - 13, D - 4]);
  const burst = bursts.find(([a, b]) => frame >= a && frame < b);
  const g = burst ? interpolate(frame, [burst[0], burst[0] + 1, burst[1]], [0.75, 1, 0.3], clamp) : 0;
  const step = Math.floor(frame / 2);
  const slices: Slice[] = [];
  if (burst) {
    slices.push({ y: rnd(step * 61 + 3) * 64, h: 14 + rnd(step * 67 + 1) * 18, dx: (rnd(step * 71 + 2) - 0.5) * 70 * k * g,
      tint: CYAN, tinted: false });
    const n = 5 + Math.floor(rnd(step * 13 + 1) * 4);
    for (let i = 0; i < n; i++) {
      const y = rnd(step * 31 + i * 7 + 2) * 96;
      const h = 0.8 + Math.pow(rnd(step * 17 + i * 3 + 5), 2) * 9;
      const mag = 16 + 150 * Math.pow(rnd(step * 5 + i * 19 + 9), 2);
      const r = rnd(step * 41 + i * 29 + 6);
      slices.push({ y, h: Math.min(h, 100 - y), dx: (rnd(step * 23 + i * 11 + 4) < 0.5 ? -1 : 1) * mag * k * g,
        tint: r < 0.8 ? CYAN : accent, tinted: r > 0.62 });
    }
  }
  const inv = burst && rnd(step * 83 + 7) < 0.6 ? { y: rnd(step * 89 + 5) * 90, h: 1.5 + rnd(step * 97 + 3) * 6 } : null;
  const jit = burst ? (rnd(step * 7 + 1) - 0.5) * 26 * k * g : 0;
  const split = burst
    ? `${(-4 * k * g).toFixed(1)}px 0 ${withAlpha(CYAN, 0.85)}, ${(4 * k * g).toFixed(1)}px 0 ${withAlpha(accent, 0.85)}, 0 4px 18px rgba(0,0,0,.6)`
    : "0 4px 18px rgba(0,0,0,.6)";
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      {burst && pic && g > 0.45 ? (
        <Img src={pic} onError={() => undefined} style={{ position: "absolute", left: jit * 1.6, top: 0, width: W, height: H,
          objectFit: "cover", opacity: 0.22 * g, mixBlendMode: "screen" }} />
      ) : null}
      {slices.map((s, i) => (
        <div key={i} style={{ position: "absolute", left: 0, top: `${s.y}%`, width: W, height: `${s.h}%`, overflow: "hidden" }}>
          {pic ? (
            <>
              <Img src={pic} onError={() => undefined} style={{ position: "absolute", left: s.dx, top: -(s.y / 100) * H, width: W,
                height: H, objectFit: "cover" }} />
              {s.tinted ? (
                <div style={{ position: "absolute", left: 0, top: 0, right: 0, bottom: 0, background: withAlpha(s.tint, 0.32),
                  mixBlendMode: "screen" }} />
              ) : null}
            </>
          ) : (
            <div style={{ position: "absolute", left: 0, top: 0, right: 0, bottom: 0, transform: `translateX(${s.dx}px)`,
              background: `repeating-linear-gradient(90deg, rgba(255,255,255,.13) 0px, rgba(255,255,255,.13) ${2 * k}px, rgba(0,0,0,0) ${2 * k}px, rgba(0,0,0,0) ${9 * k}px), ${s.tinted ? withAlpha(s.tint, 0.22) : "rgba(8,10,14,.5)"}`,
              borderTop: `${1.5 * k}px solid ${withAlpha(s.tint, 0.85)}`, borderBottom: `${1.5 * k}px solid rgba(255,255,255,.45)` }} />
          )}
          <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: Math.max(1, 1.5 * k), background: withAlpha(s.tint, 0.7) }} />
        </div>
      ))}
      {inv ? (
        <div style={{ position: "absolute", left: 0, right: 0, top: `${inv.y}%`, height: `${inv.h}%`,
          backdropFilter: "invert(1) hue-rotate(180deg) saturate(1.5)", WebkitBackdropFilter: "invert(1) hue-rotate(180deg) saturate(1.5)" }} />
      ) : null}
      {burst ? Array.from({ length: 9 }, (_, i) => {
        const r1 = rnd(step * 101 + i * 13 + 1);
        if (r1 < 0.25) return null;
        const bw = (12 + rnd(step * 103 + i * 7) * 90) * k;
        const bh = (4 + rnd(step * 107 + i * 5) * 14) * k;
        const bx = rnd(step * 109 + i * 3) * (W - bw);
        const by = rnd(step * 113 + i * 17) * (H - bh);
        const c = r1 < 0.5 ? CYAN : r1 < 0.72 ? "#f4f4f2" : r1 < 0.88 ? accent : "#07080a";
        return <div key={`b${i}`} style={{ position: "absolute", left: bx, top: by, width: bw, height: bh, background: c, opacity: 0.85 * g }} />;
      }) : null}
      {burst ? [0, 1].map((j) => (
        <div key={`l${j}`} style={{ position: "absolute", left: `${(rnd(step * 127 + j) * 40).toFixed(2)}%`,
          width: `${(30 + rnd(step * 131 + j) * 50).toFixed(2)}%`, top: `${(rnd(step * 137 + j * 5) * 100).toFixed(2)}%`,
          height: 2 * k, background: j ? accent : CYAN, opacity: 0.8 * g }} />
      )) : null}
      {burst ? (
        <AbsoluteFill style={{ opacity: 0.8 * g,
          background: "repeating-linear-gradient(0deg, rgba(255,255,255,.06) 0px, rgba(255,255,255,.06) 1px, rgba(0,0,0,0) 1px, rgba(0,0,0,0) 4px)" }} />
      ) : null}
      {title.length ? (
        <>
          <AbsoluteFill style={{ opacity: ramp(frame, 8, 12) * (1 - ramp(frame, D - 12, 10)),
            background: "radial-gradient(ellipse 48% 34% at 14% 86%, rgba(0,0,0,.45) 0%, rgba(0,0,0,0) 100%)" }} />
          <div style={{ position: "absolute", left: 110 * k, bottom: 120 * k, display: "flex", flexDirection: "column", gap: 6 * k,
            transform: `translateX(${jit.toFixed(1)}px) scale(${hold})`, transformOrigin: "0% 100%", textShadow: split }}>
            {kicker ? (
              <Letters text={`[ ${kicker} ]`} at={9} style={{ fontFamily: MONO, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.2em",
                color: CYAN, whiteSpace: "nowrap" }} />
            ) : null}
            {title.map((ln, i) => (
              <Letters key={i} text={ln} at={12 + i * 4} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 50 * k,
                letterSpacing: "0.05em", lineHeight: 1.02, color: "#fff", whiteSpace: "nowrap" }} />
            ))}
          </div>
        </>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== 9. zoom tunnel
const STREAKS = Array.from({ length: 84 }, (_, i) => ({
  a: ((i + rnd(i * 7 + 1) * 0.85) / 84) * TAU,
  w: 2.2 + rnd(i * 13 + 2) * 7.5,
  len: 0.16 + rnd(i * 17 + 3) * 0.34,
  ph: rnd(i * 29 + 4),
  alpha: 0.3 + rnd(i * 31 + 5) * 0.55,
  sp: 0.75 + rnd(i * 37 + 6) * 0.6,
  hot: i % 9 === 4,
}));

/**
 * An impact moment: tapered speed lines stream from the edges into the centre
 * (fast on the hit, then settling to a steady drift), a white and an accent
 * ring burst out, a flash, the edges dim. A short line punches in inside the
 * clear zone, letter by letter with a scale slam; at the end the lines rush in
 * and vanish as the letters leave.
 */
const ZoomTunnel: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width: W, height: H, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const title = cap(overlay.text);
  const kicker = cap(overlay.label);
  const { size, ls } = fit(title, 86, 18, 2);
  const cx = W / 2, cy = H / 2;
  const Rmax = Math.hypot(W, H) / 2 + 80 * k;
  const Rc = (title ? 320 : 170) * k;
  const inP = ramp(frame, 0, 6);
  const ex = ramp(frame, D - 14, 12, expoIn);
  const calm = 1 - 0.5 * ramp(frame, 10, 26, inOut);
  const env = inP * calm * (1 - ex);
  const phase = (0.38 * frame) / fps + 1.1 * (1 - Math.exp(-frame / 7)) + 1.5 * ex;
  const ring = ramp(frame, 2, 16);
  const ring2 = ramp(frame, 5, 18);
  const flash = interpolate(frame, [1, 3, 12], [0, 1, 0], clamp);
  const punch = 1.3 - 0.3 * ramp(frame, 3, 14, backOut);
  const polys = env > 0.002 ? STREAKS.map((s, i) => {
    const u = wrap(s.ph + phase * s.sp, 1);
    const rh = Rmax - u * (Rmax - Rc);
    const rt = rh + s.len * (Rmax - Rc);
    const o = s.alpha * smooth(u / 0.12) * smooth((1 - u) / 0.3) * env;
    if (o < 0.01) return null;
    const ca = Math.cos(s.a), sa = Math.sin(s.a);
    const hw = s.w * 0.5 * k;
    const pts = `${(cx + ca * rh).toFixed(1)},${(cy + sa * rh).toFixed(1)} ${(cx + ca * rt - sa * hw).toFixed(1)},${(cy + sa * rt + ca * hw).toFixed(1)} ${(cx + ca * rt + sa * hw).toFixed(1)},${(cy + sa * rt - ca * hw).toFixed(1)}`;
    return <polygon key={i} points={pts} fill={s.hot ? accent : "#ffffff"} opacity={o} />;
  }) : null;
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{ opacity: inP * (1 - ex) * (0.55 + 0.45 * calm),
        background: "radial-gradient(circle at 50% 50%, rgba(0,0,0,0) 34%, rgba(0,0,0,.38) 78%, rgba(0,0,0,.55) 100%)" }} />
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
        {polys}
        {frame >= 2 && ring < 1 ? (
          <circle cx={cx} cy={cy} r={Rc * (0.6 + 2.4 * ring)} fill="none" stroke="#fff" strokeWidth={(1 + 6 * (1 - ring)) * k}
            opacity={(1 - ring) * 0.9} />
        ) : null}
        {ring2 > 0 && ring2 < 1 ? (
          <circle cx={cx} cy={cy} r={Rc * (0.5 + 1.8 * ring2)} fill="none" stroke={accent} strokeWidth={(1 + 4 * (1 - ring2)) * k}
            opacity={(1 - ring2) * 0.9} />
        ) : null}
      </svg>
      {flash > 0 ? (
        <AbsoluteFill style={{ mixBlendMode: "screen", opacity: flash * 0.8,
          background: "radial-gradient(circle at 50% 50%, rgba(255,255,255,.45) 0%, rgba(255,255,255,.12) 28%, rgba(255,255,255,0) 55%)" }} />
      ) : null}
      {title ? (
        <AbsoluteFill style={{ alignItems: "center", justifyContent: "center",
          transform: `scale(${(punch * hold * (1 - 0.05 * ex)).toFixed(4)})` }}>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
            {kicker ? (
              <Letters text={kicker} at={4} step={0.5} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k,
                letterSpacing: "0.34em", paddingLeft: "0.34em", color: accent, whiteSpace: "nowrap", marginBottom: 8 * k,
                textShadow: "0 3px 16px rgba(0,0,0,.6)" }} />
            ) : null}
            {ls.map((ln, i) => (
              <Letters key={i} text={ln} at={6 + i * 4} step={0.5} style={{ fontFamily: DISPLAY, fontSize: size * k, lineHeight: 1,
                letterSpacing: "0.04em", color: "#fff", textAlign: "center", whiteSpace: "nowrap",
                textShadow: "0 8px 34px rgba(0,0,0,.6)" }} />
            ))}
          </div>
        </AbsoluteFill>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== 10. paper tear
const FIBERS = Array.from({ length: 26 }, (_, i) => ({
  x: rnd(i * 13 + 101), y: rnd(i * 17 + 103),
  cx: (rnd(i * 19 + 107) - 0.5) * 40, cy: (rnd(i * 23 + 109) - 0.5) * 40,
  dx: (rnd(i * 29 + 113) - 0.5) * 100, dy: (rnd(i * 31 + 127) - 0.5) * 60,
}));
const SCRAPS = Array.from({ length: 10 }, (_, i) => ({
  u: 0.05 + rnd(i * 61 + 1) * 0.9,
  at: Math.round(rnd(i * 67 + 2) * 7),
  vx: (rnd(i * 71 + 3) - 0.5) * 320,
  vy: -120 - rnd(i * 73 + 4) * 300,
  w: 8 + rnd(i * 79 + 5) * 18,
  h: 6 + rnd(i * 83 + 6) * 14,
  rot: rnd(i * 89 + 7) * 360,
  spin: (rnd(i * 97 + 8) - 0.5) * 720,
}));

/** The sheet: warm laid paper with fibres and a vignette, the title printed on it. */
const PaperFace: React.FC<{ kicker: string; ls: string[]; size: number; sub: string[]; accent: string; at: number }> =
  ({ kicker, ls, size, sub, accent, at }) => {
    const frame = useCurrentFrame();
    const { width: W, height: H, durationInFrames: D } = useVideoConfig();
    const k = useK();
    const hold = useHold();
    const never = D + 60;
    const rule = ramp(frame, at + 12, 16);
    return (
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 90% 85% at 42% 40%, #f7f3ea 0%, #ece5d6 55%, #d8cdb7 100%)" }}>
        <AbsoluteFill style={{ backgroundImage: "repeating-linear-gradient(0deg, rgba(110,90,60,.035) 0px, rgba(110,90,60,.035) 1px, rgba(0,0,0,0) 1px, rgba(0,0,0,0) 7px)" }} />
        <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
          {FIBERS.map((f, i) => (
            <path key={i} d={`M${(f.x * W).toFixed(1)} ${(f.y * H).toFixed(1)}q${(f.cx * k).toFixed(1)} ${(f.cy * k).toFixed(1)} ${(f.dx * k).toFixed(1)} ${(f.dy * k).toFixed(1)}`}
              fill="none" stroke="rgba(120,98,64,.16)" strokeWidth={1.1 * k} strokeLinecap="round" />
          ))}
        </svg>
        <AbsoluteFill style={{ boxShadow: `inset 0 0 ${240 * k}px rgba(96,74,40,.26)` }} />
        {ls.length ? (
          <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
              {kicker ? (
                <Letters text={kicker} at={at} outAt={never} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 28 * k,
                  letterSpacing: "0.38em", paddingLeft: "0.38em", color: "rgba(22,22,24,.62)", whiteSpace: "nowrap",
                  marginBottom: 10 * k }} />
              ) : null}
              {ls.map((ln, i) => (
                <Letters key={i} text={ln} at={at + 4 + i * 5} outAt={never} style={{ fontFamily: DISPLAY, fontSize: size * k,
                  lineHeight: 1, letterSpacing: "0.04em", color: PAPER_INK, textAlign: "center", whiteSpace: "nowrap" }} />
              ))}
              <div style={{ width: 170 * k, height: 5 * k, marginTop: 18 * k, background: accent, transform: `scaleX(${rule})` }} />
              {sub.map((ln, i) => (
                <Rise key={`s${i}`} at={at + 14 + i * 3} outAt={never} style={{ marginTop: i === 0 ? 16 * k : 0 }}>
                  <span style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 30 * k, letterSpacing: "0.1em",
                    color: "rgba(22,22,24,.6)" }}>{cap(ln)}</span>
                </Rise>
              ))}
            </div>
          </AbsoluteFill>
        ) : null}
      </AbsoluteFill>
    );
  };

/**
 * A sheet of paper slides up over the shot (full screen: it is already
 * there) with the title printed on it; after a beat a jagged tear runs across
 * it left to right with a small shudder, then the two halves hinge open from
 * the left and fly off, top up and bottom down, each with a white fibrous torn
 * edge and a shadow, a few scraps tumbling, revealing the footage (full
 * screen: the scene's own picture).
 */
const PaperTear: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width: W, height: H, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const full = Boolean(overlay.fullFrame);
  const pic = full ? stillOf((overlay.media || [])[0]) : "";
  const title = cap(overlay.text);
  const kicker = cap(overlay.label);
  const { size, ls } = fit(title, 84, 20, 2);
  const sub = lines(overlay.subtitle || "", 46).slice(0, 2);
  const land = full ? 1 : ramp(frame, 0, 13, quintOut);
  const textAt = full ? 4 : 10;
  // The tear comes 1.25 s before the end, after a beat of reading, and always early enough to finish.
  const tearAt = Math.min(Math.max(textAt + (title ? 28 : 8), D - Math.round(fps * 1.25)), Math.max(textAt + 4, D - 26));
  const crack = ramp(frame, tearAt, 9, inOut);
  const sepAt = tearAt + 9;
  const split = frame >= sepAt;
  const hinge = ramp(frame, sepAt, 10, quintOut);
  const fly = ramp(frame, sepAt + 3, Math.max(8, D - 3 - (sepAt + 3)), expoIn);
  const cracking = crack > 0 && crack < 1;
  const shx = cracking ? (rnd(frame * 7 + 1) - 0.5) * 5 * k : 0;
  const shy = cracking ? (rnd(frame * 11 + 2) - 0.5) * 4 * k : 0;
  const pr = interpolate(frame, [0, Math.max(1, D)], [0, 1], clamp);
  // The tear: a jagged line across the sheet, and a rougher copy of it for the torn fibres.
  const N = 56;
  const pts: [number, number][] = [];
  for (let i = 0; i <= N; i++) {
    const u = i / N;
    pts.push([-40 * k + u * (W + 80 * k),
      H * 0.53 + Math.sin(u * Math.PI * 1.6 + 0.7) * 44 * k + Math.sin(u * Math.PI * 5.2 + 2.2) * 13 * k
        + (rnd(i * 19 + 7) - 0.5) * 30 * k]);
  }
  const fib: [number, number][] = [];
  for (let i = 0; i < N * 3; i++) {
    const j = Math.floor(i / 3);
    const f = (i % 3) / 3;
    const [ax, ay] = pts[j];
    const [bx, by] = pts[j + 1];
    fib.push([ax + (bx - ax) * f, ay + (by - ay) * f + (rnd(i * 23 + 11) - 0.5) * 13 * k]);
  }
  fib.push(pts[N]);
  const pathOf = (p: [number, number][]): string => p.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join("");
  const polyOf = (p: [number, number][]): string => p.map(([x, y]) => `${x.toFixed(1)}px ${y.toFixed(1)}px`).join(", ");
  const tearD = pathOf(pts);
  const fibD = pathOf(fib);
  const e = 80 * k;
  const topClip = `polygon(${-e}px ${-e}px, ${W + e}px ${-e}px, ${polyOf([...pts].reverse())})`;
  const botClip = `polygon(${polyOf(pts)}, ${W + e}px ${H + e}px, ${-e}px ${H + e}px)`;
  const origin = `${W}px ${pts[N][1].toFixed(1)}px`;
  const topT = `translate(${(-fly * 150 * k).toFixed(1)}px, ${(-(hinge * 16 * k + fly * H * 0.85)).toFixed(1)}px) rotate(${(hinge * 2.4 + fly * 8).toFixed(2)}deg)`;
  const botT = `translate(${(fly * 100 * k).toFixed(1)}px, ${(hinge * 16 * k + fly * H * 0.85).toFixed(1)}px) rotate(${(-(hinge * 2 + fly * 6.5)).toFixed(2)}deg)`;
  const shadow = `drop-shadow(0 ${16 * k}px ${24 * k}px rgba(0,0,0,.45))`;
  const face = <PaperFace kicker={kicker} ls={ls} size={size} sub={sub} accent={accent} at={textAt} />;
  const edge = (dir: 1 | -1) => (
    <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
      <path d={fibD} fill="none" stroke="#fbf6ea" strokeWidth={14 * k} strokeLinejoin="round" />
      <path d={fibD} fill="none" stroke="rgba(120,96,60,.3)" strokeWidth={1.4 * k} transform={`translate(0 ${(dir * 7 * k).toFixed(1)})`} />
    </svg>
  );
  const scraps = split ? SCRAPS.map((s, i) => {
    const age = frame - sepAt - s.at;
    if (age < 0 || age > 30) return null;
    const q = age / fps;
    const [sx, sy] = pts[Math.min(N, Math.round(s.u * N))];
    return (
      <div key={i} style={{ position: "absolute", left: sx + s.vx * q * k, top: sy + (s.vy * q + 1100 * q * q) * k,
        width: s.w * k, height: s.h * k, background: "#f1ebdd", opacity: 1 - age / 30,
        transform: `rotate(${(s.rot + s.spin * q).toFixed(1)}deg)`, clipPath: "polygon(0% 14%, 72% 0%, 100% 60%, 34% 100%)" }} />
    );
  }) : null;
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      {full ? (
        pic ? (
          <AbsoluteFill>
            <Img src={pic} onError={() => undefined} style={{ width: "100%", height: "100%", objectFit: "cover",
              transform: `scale(${(1.05 + 0.06 * pr).toFixed(4)})` }} />
          </AbsoluteFill>
        ) : (
          <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 45%, #1d1e23 0%, #0d0e11 60%, #060607 100%)" }} />
        )
      ) : null}
      {!split ? (
        <AbsoluteFill style={{ transform: `translate(${shx.toFixed(1)}px, ${(shy + (1 - land) * H * 1.08).toFixed(1)}px)`,
          boxShadow: land < 1 ? `0 ${-18 * k}px ${50 * k}px rgba(0,0,0,.35)` : undefined }}>
          {face}
          {crack > 0 ? (
            <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
              <path d={fibD} fill="none" stroke="#fffaf0" strokeWidth={6 * k} pathLength={1} strokeDasharray={1}
                strokeDashoffset={1 - crack} />
              <path d={tearD} fill="none" stroke="rgba(40,30,18,.62)" strokeWidth={2.4 * k} pathLength={1} strokeDasharray={1}
                strokeDashoffset={1 - crack} />
            </svg>
          ) : null}
        </AbsoluteFill>
      ) : (
        <>
          <AbsoluteFill style={{ transform: botT, transformOrigin: origin, filter: shadow }}>
            <AbsoluteFill style={{ clipPath: botClip, WebkitClipPath: botClip }}>
              {face}
              {edge(1)}
            </AbsoluteFill>
          </AbsoluteFill>
          <AbsoluteFill style={{ transform: topT, transformOrigin: origin, filter: shadow }}>
            <AbsoluteFill style={{ clipPath: topClip, WebkitClipPath: topClip }}>
              {face}
              {edge(-1)}
            </AbsoluteFill>
          </AbsoluteFill>
          {scraps}
        </>
      )}
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "fx-ink-bleed": InkBleed,
  "fx-light-streak": LightStreak,
  "fx-dust-motes": DustMotes,
  "fx-hud-scan": HudScan,
  "fx-film-burn": FilmBurn,
  "fx-shape-wipe": ShapeWipe,
  "fx-gradient-mesh": GradientMesh,
  "fx-glitch-slice": GlitchSlice,
  "fx-zoom-tunnel": ZoomTunnel,
  "fx-paper-tear": PaperTear,
};
