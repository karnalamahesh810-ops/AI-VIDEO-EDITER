import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY, INTER, LABEL, MONO } from "../fonts";
import type { MapLocation, Overlay } from "../../types";
import { ramp, useK } from "../pro/ProGraphics";

/**
 * Lower thirds & name tags (family "lt-"). Every look rides ON the footage:
 * small, low-left (or a corner), a soft local gradient at most, the picture
 * stays the picture. Text never fades or types: letters rise out of masks
 * (or lines slide out of them) and leave the same way in the last frames.
 *
 *   lt-accent-line     a line grows, the name rises out of it, the role drops out
 *                      of it; at the end they sink back in and the line retracts
 *   lt-two-tone        name on a white block, role on an accent block, the blocks
 *                      wipe in from opposite sides with hard cut-out shadows
 *   lt-glass-card      a frosted glass card tilts up into place, an icon circle
 *                      draws its ring and person glyph, a shine sweeps across
 *   lt-location-pin    a map pin drops and squashes, ground ripples pulse, the
 *                      place rises, the coordinates decode in mono
 *   lt-date-place      date | place in condensed caps under mono captions, both
 *                      sliding out of a glowing divider that grows from its centre
 *   lt-role-badge      a gold coin with the initials flips in, an orbit ring turns,
 *                      the name rises and the role wipes open in a pill
 *   lt-corner-brackets a tiny top-left tag; four brackets lock onto it with an
 *                      overshoot, a scan line passes, the brackets breathe
 *   lt-stacked-index   an outline index number rolls in and fills like liquid,
 *                      name / role / organisation rows slide out of their masks
 *   lt-slant-bar       a skewed accent bar whips in with speed streaks, a thin
 *                      role drawer drops out from under it
 *   lt-source-credit   top-right "FOOTAGE: ..." credit, characters rising in
 *                      one by one beside a play icon whose ring tracks playback
 *
 * The low-left tags keep their lowest line above LOW (250 px) so they never
 * sit on the burned-in captions, even when a caption wraps to two lines.
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;
type Dir = "up" | "down";

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const easeIn = Easing.bezier(0.7, 0, 0.84, 0);
const GOLD = "#F2B544";
const INK = "#0d0d10";
const CYAN = "#53c8ff";
const DIGITS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 0];
/**
 * Bottom edge (1080p px) of the low-left tags. Burned-in captions sit centred
 * at the bottom: a 70 px pad plus up to five words at 58-74 px, line height
 * 1.18. One line tops out near 160 px, but five long words wrap to a second
 * line (up to ~244 px in the "modern" style, ~234 px with the news bar), so
 * every name tag keeps its lowest line above 250 px and never collides with a
 * caption.
 */
const LOW = 250;

// ------------------------------------------------------------------ helpers
/** 0 -> 1 between two frames (never an invalid range). */
const span = (frame: number, a: number, b: number, ease?: (t: number) => number): number =>
  interpolate(frame, [a, Math.max(a + 1, b)], [0, 1], ease ? { ...clamp, easing: ease } : clamp);

const useT = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const dur = Math.max(1, durationInFrames);
  return { frame, fps, dur, k, end: dur - 14 };
};

/** #rgb, #rrggbb, #rrggbbaa or rgb()/rgba() -> [r, g, b]; null for anything else. */
const rgbOf = (c: string): [number, number, number] | null => {
  const s = typeof c === "string" ? c.trim() : "";
  const m = /^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.exec(s);
  if (m) {
    const h = m[1].length === 3 ? m[1].split("").map((x) => x + x).join("") : m[1].slice(0, 6);
    const n = parseInt(h, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  const f = /^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})/i.exec(s);
  return f ? [Math.min(255, Number(f[1])), Math.min(255, Number(f[2])), Math.min(255, Number(f[3]))] : null;
};

/**
 * The accent to draw with. Every glow, tint and shadow below is derived from
 * it, so a colour the helpers cannot read (a CSS name, hsl()) falls back to
 * the house gold instead of turning every gradient into a solid block.
 */
const pick = (a: string): string => (rgbOf(a) ? a.trim() : GOLD);
const rgba = (c: string, a: number): string => {
  const v = rgbOf(c);
  return v ? `rgba(${v[0]},${v[1]},${v[2]},${a})` : c;
};
const shade = (c: string, f: number): string => {
  const v = rgbOf(c);
  if (!v) return c;
  const s = v.map((x) => Math.max(0, Math.min(255, Math.round(x * f))));
  return `rgb(${s[0]},${s[1]},${s[2]})`;
};
const tint = (c: string, t: number): string => {
  const v = rgbOf(c);
  if (!v) return c;
  const s = v.map((x) => Math.max(0, Math.min(255, Math.round(x + (255 - x) * t))));
  return `rgb(${s[0]},${s[1]},${s[2]})`;
};
/** WCAG relative luminance of an sRGB colour. */
const luminance = (v: [number, number, number]): number => {
  const [r, g, b] = v.map((x) => {
    const c = x / 255;
    return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
/**
 * Text colour on an accent fill: white only where it keeps at least 3:1
 * (large-text) contrast, i.e. on red and blue; near-black on gold, amber,
 * teal and white, where white text would wash out (teal: ~2.2:1).
 */
const inkOn = (c: string): string => {
  const v = rgbOf(c);
  if (!v) return INK;
  return 1.05 / (luminance(v) + 0.05) >= 3 ? "#fff" : INK;
};

/** Tidy a field and cut it at a word boundary so a tag never runs off the frame. */
const clean = (s: string | undefined | null, max: number): string => {
  const t = String(s ?? "").replace(/\s+/g, " ").trim();
  if (t.length <= max) return t;
  const cut = t.slice(0, max);
  const sp = cut.lastIndexOf(" ");
  return (sp > max * 0.55 ? cut.slice(0, sp) : cut).replace(/[\s,;:·/-]+$/, "").trim();
};

const TITLES = /^(dr|mr|mrs|ms|mx|prof|sir|dame|rev|gen|col|capt|sen|rep|gov|jr|sr|ii|iii)$/i;
const initials = (name: string): string => {
  const words = name.replace(/[^\p{L}\s'-]/gu, " ").split(/\s+/)
    .filter((w) => w && /\p{L}/u.test(w) && !TITLES.test(w.replace(/'/g, "")));
  if (!words.length) return "";
  const first = Array.from(words[0])[0] || "";
  const last = words.length > 1 ? Array.from(words[words.length - 1])[0] || "" : "";
  return (first + last).toUpperCase();
};

/** Deterministic 0..1 noise from two integers (no Math.random anywhere). */
const hash = (a: number, b: number): number => {
  let h = Math.imul(a | 0, 374761393) ^ Math.imul(b | 0, 668265263);
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
};

const fmtCoord = (lat: number, lon: number): string =>
  `${Math.abs(lat).toFixed(4)}°${lat >= 0 ? "N" : "S"}  ${Math.abs(lon).toFixed(4)}°${lon >= 0 ? "E" : "W"}`;

// ------------------------------------------------------------------ text engines
/**
 * Letters rising out of (or dropping into) a mask one after another, and
 * leaving the same way at the end. `enter`/`exit` choose the direction, so a
 * name can rise out of a line and sink back into it.
 */
const Letters: React.FC<{
  text: string; at: number; step?: number; frames?: number; outAt?: number;
  enter?: Dir; exit?: Dir; reverseOut?: boolean; style?: React.CSSProperties;
}> = ({ text, at, step = 1, frames = 12, outAt, enter = "up", exit = "up", reverseOut = false, style }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const chars = Array.from(text);
  const n = chars.length;
  const end = outAt ?? durationInFrames - 14;
  const inStep = n > 1 ? Math.min(step, 20 / (n - 1)) : step;
  // The whole exit (stagger + 8-frame drop) is over by durationInFrames - 2, so
  // no letter is still half-visible on the last frame of the sequence.
  const outStep = n > 1 ? Math.min(0.6, 4 / (n - 1)) : 0;
  const y0 = enter === "up" ? 108 : -108;
  const y1 = exit === "up" ? -108 : 108;
  return (
    <div style={{ overflow: "hidden", whiteSpace: "nowrap", paddingBottom: "0.08em", ...style }}>
      {chars.map((c, i) => {
        const pin = ramp(frame, at + i * inStep, frames);
        const oi = reverseOut ? n - 1 - i : i;
        const pout = ramp(frame, end + oi * outStep, 8, easeIn);
        const y = (1 - pin) * y0 + pout * y1;
        const hidden = pin < 0.02 || pout > 0.98;
        return (
          <span key={i} style={{ display: "inline-block", whiteSpace: "pre", transform: `translateY(${y.toFixed(2)}%)`,
            opacity: hidden ? 0 : 1 }}>{c}</span>
        );
      })}
    </div>
  );
};

/** A whole line sliding out of its mask (and back into it at the end). */
const Rise: React.FC<{ at: number; frames?: number; outAt?: number; enter?: Dir; exit?: Dir;
  style?: React.CSSProperties; children: React.ReactNode }> =
  ({ at, frames = 16, outAt, enter = "up", exit = "down", style, children }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();
    const end = outAt ?? durationInFrames - 13;
    const pin = ramp(frame, at, frames);
    const pout = ramp(frame, end, 10, easeIn);
    const y = (1 - pin) * (enter === "up" ? 112 : -112) + pout * (exit === "up" ? -112 : 112);
    return (
      <div style={{ overflow: "hidden", paddingBottom: "0.08em", ...style }}>
        <div style={{ transform: `translateY(${y.toFixed(2)}%)`, whiteSpace: "nowrap" }}>{children}</div>
      </div>
    );
  };

/** A line sliding sideways out of a mask edge, and back in at the end. */
const Slide: React.FC<{ at: number; from: "left" | "right"; frames?: number; outAt?: number; children: React.ReactNode }> =
  ({ at, from, frames = 16, outAt, children }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();
    const end = outAt ?? durationInFrames - 13;
    const pin = ramp(frame, at, frames);
    const pout = ramp(frame, end, 10, easeIn);
    const x = (1 - pin + pout) * 104 * (from === "right" ? 1 : -1);
    return (
      <div style={{ overflow: "hidden", paddingBottom: "0.06em" }}>
        <div style={{ transform: `translateX(${x.toFixed(2)}%)`, whiteSpace: "nowrap" }}>{children}</div>
      </div>
    );
  };

/** A mono readout: characters rise in, digits scramble (cyan) then lock, and drop out at the end. */
const Decode: React.FC<{ text: string; at: number; step?: number; hot: string; style?: React.CSSProperties }> =
  ({ text, at, step = 0.9, hot, style }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();
    const chars = Array.from(text);
    const n = chars.length;
    const end = durationInFrames - 14;
    const outStep = n > 1 ? Math.min(0.5, 4 / (n - 1)) : 0;
    return (
      <div style={{ overflow: "hidden", whiteSpace: "nowrap", paddingBottom: "0.06em", ...style }}>
        {chars.map((c, i) => {
          const show = at + i * step * 0.5;
          const lock = at + 8 + i * step;
          const pin = ramp(frame, show, 6);
          const pout = ramp(frame, end + (n - 1 - i) * outStep, 8, easeIn);
          const digit = /\d/.test(c);
          const settled = frame >= lock;
          const glyph = settled || !digit ? c : String(Math.floor(hash(i + 7, Math.floor(frame / 2)) * 10));
          return (
            <span key={i} style={{ display: "inline-block", whiteSpace: "pre", color: settled ? undefined : hot,
              opacity: frame < show ? 0 : 1, transform: `translateY(${((1 - pin) * 70 + pout * 110).toFixed(1)}%)` }}>
              {glyph}
            </span>
          );
        })}
      </div>
    );
  };

/** A soft local darkening behind a tag: never a full-frame scrim. */
const LocalShade: React.FC<{ pos: string; op: number; a?: number; w?: number; h?: number }> =
  ({ pos, op, a = 0.5, w = 60, h = 55 }) => (
    <AbsoluteFill style={{ opacity: Math.max(0, Math.min(1, op)), pointerEvents: "none",
      background: `radial-gradient(ellipse ${w}% ${h}% at ${pos}, rgba(0,0,0,${a}) 0%, rgba(0,0,0,${(a * 0.42).toFixed(3)}) 48%, rgba(0,0,0,0) 100%)` }} />
  );

// ================================================================== 1. accent line
/** A line grows; the name rises out of it, the role drops out of it; both sink back and the line retracts. */
const AccentLine: Look = ({ overlay, accent }) => {
  const { frame, fps, dur, k } = useT();
  const A = pick(accent);
  const name = clean(overlay.text, 34).toUpperCase();
  const role = clean(overlay.subtitle || overlay.label, 52).toUpperCase();
  if (!name) return null;
  const size = (name.length > 24 ? 58 : name.length > 15 ? 70 : 82) * k;
  const grow = ramp(frame, 2, Math.round(fps * 0.6));
  const gone = ramp(frame, dur - 10, 9, easeIn);
  const leaving = gone > 0;
  const sx = leaving ? 1 - gone : grow;
  const glint = span(frame, fps * 1.0, fps * 1.9, inOut);
  const drift = span(frame, 0, dur) * 12 * k;
  const node = ramp(frame, 2, 6) * (1 - gone);
  return (
    <AbsoluteFill>
      <LocalShade pos="10% 77%" op={ramp(frame, 0, 12) * (1 - gone)} />
      <div style={{ position: "absolute", left: 110 * k, bottom: LOW * k, transform: `translateX(${drift}px)`,
        display: "flex", flexDirection: "column", alignItems: "flex-start", minWidth: 380 * k }}>
        <Letters text={name} at={Math.round(fps * 0.2)} step={0.9} exit="down"
          style={{ fontFamily: DISPLAY, fontSize: size, lineHeight: 1, color: "#fff", letterSpacing: "0.035em",
            textShadow: "0 6px 26px rgba(0,0,0,.5)" }} />
        <div style={{ position: "relative", alignSelf: "stretch", height: 5 * k, margin: `${3 * k}px 0 ${12 * k}px` }}>
          <div style={{ position: "absolute", inset: 0, overflow: "hidden", transform: `scaleX(${sx})`,
            transformOrigin: leaving ? "100% 50%" : "0% 50%", background: A,
            boxShadow: `0 0 ${16 * k}px ${rgba(A, 0.55)}` }}>
            <div style={{ position: "absolute", top: 0, bottom: 0, width: "22%", left: `${-22 + glint * 122}%`,
              background: "linear-gradient(90deg, rgba(255,255,255,0), rgba(255,255,255,.95), rgba(255,255,255,0))" }} />
          </div>
          <div style={{ position: "absolute", top: "50%", left: `${(leaving ? 1 : grow) * 100}%`, width: 13 * k,
            height: 13 * k, borderRadius: "50%", background: "#fff",
            boxShadow: `0 0 ${14 * k}px ${A}, 0 0 ${4 * k}px #fff`, transform: `translate(-50%, -50%) scale(${node})` }} />
        </div>
        {role ? (
          <Letters text={role} at={Math.round(fps * 0.38)} step={0.5} enter="down" exit="up"
            style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 30 * k, lineHeight: 1.1, color: "rgba(255,255,255,.9)",
              letterSpacing: "0.2em", textShadow: "0 4px 18px rgba(0,0,0,.55)" }} />
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 2. two-tone split
/** Name on a white block from the left, role on an accent block from the right, hard cut-out shadows. */
const TwoTone: Look = ({ overlay, accent }) => {
  const { frame, fps, dur, k } = useT();
  const A = pick(accent);
  const name = clean(overlay.text, 30).toUpperCase();
  const role = clean(overlay.subtitle || overlay.label, 44).toUpperCase();
  if (!name) return null;
  const ink = inkOn(A);
  const size = (name.length > 22 ? 54 : name.length > 14 ? 62 : 70) * k;
  const a = ramp(frame, 0, Math.round(fps * 0.5));
  const b = ramp(frame, Math.round(fps * 0.2), Math.round(fps * 0.5));
  const ax = ramp(frame, dur - 11, 10, easeIn);
  const bx = ramp(frame, dur - 12, 10, easeIn);
  const hold = span(frame, fps * 0.7, dur);
  const clipA = `inset(0 ${Math.min(100, (1 - a) * 100 + ax * 100).toFixed(2)}% 0 0)`;
  const clipB = `inset(0 0 0 ${Math.min(100, (1 - b) * 100 + bx * 100).toFixed(2)}%)`;
  const xA = (1 - a) * -70 * k - ax * 50 * k + hold * 6 * k;
  const xB = (1 - b) * 70 * k + bx * 50 * k - hold * 6 * k;
  const off = 9 * k;
  return (
    <AbsoluteFill>
      <LocalShade pos="12% 76%" a={0.42} op={ramp(frame, 0, 12) * (1 - ax)} />
      <div style={{ position: "absolute", left: 110 * k, bottom: LOW * k, display: "flex", flexDirection: "column",
        alignItems: "flex-start" }}>
        <div style={{ position: "relative", transform: `translateX(${xA}px)` }}>
          <div style={{ position: "absolute", inset: 0, transform: `translate(${off}px, ${off}px)`,
            background: "rgba(0,0,0,.34)", clipPath: clipA }} />
          {/* No accent edge stripe on the name block: an off-white plate with an
              accent stripe is the existing "Lower Thirds (tag)" look. Here the
              accent lives only in the role block, which is what makes it two-tone. */}
          <div style={{ position: "relative", background: "#f5f4f0", clipPath: clipA,
            padding: `${12 * k}px ${36 * k}px ${6 * k}px ${30 * k}px` }}>
            <Letters text={name} at={Math.round(fps * 0.18)} step={0.8}
              style={{ fontFamily: DISPLAY, fontSize: size, lineHeight: 1, color: INK, letterSpacing: "0.03em" }} />
          </div>
        </div>
        {role ? (
          <div style={{ position: "relative", marginLeft: 48 * k, transform: `translateX(${xB}px)` }}>
            <div style={{ position: "absolute", inset: 0, transform: `translate(${off}px, ${off}px)`,
              background: "rgba(0,0,0,.3)", clipPath: clipB }} />
            <div style={{ position: "relative", background: A, clipPath: clipB,
              padding: `${9 * k}px ${26 * k}px ${7 * k}px` }}>
              <Letters text={role} at={Math.round(fps * 0.38)} step={0.5}
                style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 28 * k, lineHeight: 1.05, color: ink,
                  letterSpacing: "0.16em" }} />
            </div>
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 3. glass card
/** A frosted card tilts up into place; the icon ring and person glyph draw on; a shine sweeps across. */
const GlassCard: Look = ({ overlay, accent }) => {
  const { frame, fps, dur, k } = useT();
  const A = pick(accent);
  const name = clean(overlay.text, 30);
  const role = clean(overlay.subtitle || overlay.label, 44).toUpperCase();
  if (!name) return null;
  const ink = inkOn(A);
  const land = ramp(frame, 0, Math.round(fps * 0.6));
  const out = ramp(frame, dur - 11, 10, easeIn);
  const tilt = (1 - land) * 24 - out * 16;
  const y = (1 - land) * 46 * k + out * 26 * k + Math.sin((frame / fps) * 1.7) * 3 * k * land;
  const op = Math.min(1, land * 1.8) * (1 - out);
  const pop = ramp(frame, 6, 16, backOut) * (1 - out * 0.4);
  const ring = ramp(frame, 8, Math.round(fps * 0.75), inOut);
  const head = ramp(frame, 12, 14, inOut);
  const body = ramp(frame, 16, 16, inOut);
  const shine = span(frame, fps * 0.75, fps * 1.55, inOut);
  const size = (name.length > 20 ? 44 : 50) * k;
  const D = 96 * k;
  return (
    <AbsoluteFill>
      <LocalShade pos="12% 77%" a={0.38} op={ramp(frame, 0, 12) * (1 - out)} />
      <div style={{ position: "absolute", left: 110 * k, bottom: LOW * k, perspective: 1100 * k }}>
        <div style={{ position: "relative", overflow: "hidden", display: "flex", alignItems: "center", gap: 26 * k,
          padding: `${20 * k}px ${46 * k}px ${20 * k}px ${20 * k}px`, borderRadius: 28 * k,
          background: "linear-gradient(135deg, rgba(255,255,255,.22) 0%, rgba(255,255,255,.07) 55%, rgba(255,255,255,.13) 100%), linear-gradient(rgba(12,14,20,.3), rgba(12,14,20,.3))",
          backdropFilter: "blur(18px) saturate(1.5)", WebkitBackdropFilter: "blur(18px) saturate(1.5)",
          border: `${1.5 * k}px solid rgba(255,255,255,.3)`,
          boxShadow: `0 ${26 * k}px ${60 * k}px rgba(0,0,0,.42), inset 0 ${1.5 * k}px 0 rgba(255,255,255,.4)`,
          transform: `translateY(${y}px) rotateX(${tilt}deg)`, transformOrigin: "50% 100%", opacity: op }}>
          <div style={{ position: "absolute", top: -60 * k, bottom: -60 * k, width: 150 * k, left: `${-20 + shine * 130}%`,
            transform: "skewX(-22deg)", opacity: shine > 0 && shine < 1 ? 1 : 0,
            background: "linear-gradient(90deg, rgba(255,255,255,0), rgba(255,255,255,.3), rgba(255,255,255,0))" }} />
          <div style={{ position: "relative", width: D, height: D, flex: "none", transform: `scale(${pop})` }}>
            <svg width={D} height={D} viewBox="0 0 96 96" style={{ position: "absolute", inset: 0, overflow: "visible" }}>
              <circle cx={48} cy={48} r={46} fill="none" stroke="rgba(255,255,255,.22)" strokeWidth={2} />
              <circle cx={48} cy={48} r={46} fill="none" stroke={A} strokeWidth={3} strokeLinecap="round" pathLength={1}
                strokeDasharray={1} strokeDashoffset={1 - ring} transform="rotate(-90 48 48)" />
            </svg>
            <div style={{ position: "absolute", inset: 8 * k, borderRadius: "50%", display: "flex", alignItems: "center",
              justifyContent: "center",
              background: `radial-gradient(circle at 34% 28%, ${tint(A, 0.35)} 0%, ${A} 48%, ${shade(A, 0.6)} 100%)`,
              boxShadow: `inset 0 ${2 * k}px ${4 * k}px rgba(255,255,255,.3)` }}>
              <svg width={46 * k} height={46 * k} viewBox="0 0 44 44" style={{ overflow: "visible" }}>
                <circle cx={22} cy={15} r={7.5} fill="none" stroke={ink} strokeWidth={3} pathLength={1} strokeDasharray={1}
                  strokeDashoffset={1 - head} transform="rotate(-90 22 15)" />
                <path d="M7 39 C7 29.5 13.5 25 22 25 C30.5 25 37 29.5 37 39" fill="none" stroke={ink} strokeWidth={3}
                  strokeLinecap="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - body} />
              </svg>
            </div>
          </div>
          <div style={{ position: "relative", display: "flex", flexDirection: "column", gap: 6 * k }}>
            <Letters text={name} at={10} step={0.8}
              style={{ fontFamily: INTER, fontWeight: 800, fontSize: size, lineHeight: 1.08, color: "#fff",
                letterSpacing: "-0.01em" }} />
            {role ? (
              <Letters text={role} at={17} step={0.45}
                style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 28 * k, lineHeight: 1.1,
                  color: "rgba(255,255,255,.78)", letterSpacing: "0.18em" }} />
            ) : null}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 4. location pin
/** A pin drops and squashes, ripples pulse under it, the place rises, the coordinates decode. */
const LocationPin: Look = ({ overlay, accent }) => {
  const { frame, fps, dur, k } = useT();
  const A = pick(accent);
  const locs: MapLocation[] = Array.isArray(overlay.locations) ? overlay.locations : [];
  const loc: MapLocation | undefined = locs.find((l) =>
    !!l && Number.isFinite(l.lat) && Number.isFinite(l.lon) && Math.abs(l.lat) <= 90 && Math.abs(l.lon) <= 180);
  const place = clean(overlay.text || (loc ? loc.label : ""), 28).toUpperCase();
  const region = clean(overlay.subtitle || overlay.label, 40).toUpperCase();
  if (!place) return null;
  const coord = loc ? fmtCoord(loc.lat, loc.lon) : "";
  const LAND = Math.max(8, Math.round(fps * 0.4));
  const fall = interpolate(frame, [1, LAND], [-230 * k, 0], { ...clamp, easing: Easing.in(Easing.quad) });
  const hop = interpolate(frame, [LAND, LAND + 5, LAND + 11], [0, -20 * k, 0],
    { ...clamp, easing: Easing.inOut(Easing.quad) });
  const sq = interpolate(frame, [LAND - 1, LAND + 1, LAND + 7], [1, 0.8, 1], clamp);
  const lift = ramp(frame, dur - 12, 10, easeIn);
  const appear = span(frame, 1, 3);
  const pinS = 1 - lift;
  const sx = 1 + (1 - sq) * 0.9;
  const ripple = (offset: number) => {
    const t = frame - LAND - offset;
    if (t < 0) return { s: 0, o: 0 };
    const ph = (t % 46) / 46;
    return { s: 0.3 + ph * 1.5, o: (1 - ph) * 0.9 * (1 - lift) };
  };
  const rings = [ripple(0), ripple(23)];
  const size = (place.length > 18 ? 62 : 76) * k;
  const hair = ramp(frame, 18, 20, inOut) * (1 - ramp(frame, dur - 11, 9, easeIn));
  return (
    <AbsoluteFill>
      <LocalShade pos="11% 76%" op={ramp(frame, 0, 12) * (1 - lift)} />
      {/* left 120: the ground ripples reach ~1.6x their 76 px ring while still
          visible, so the block sits far enough in to keep them inside the 90 px margin. */}
      <div style={{ position: "absolute", left: 120 * k, bottom: LOW * k, display: "flex", alignItems: "center",
        gap: 22 * k }}>
        <div style={{ position: "relative", width: 64 * k, height: 104 * k, flex: "none" }}>
          {rings.map((r, i) => (
            <div key={i} style={{ position: "absolute", left: 32 * k, top: 92 * k, width: 76 * k, height: 22 * k,
              marginLeft: -38 * k, marginTop: -11 * k, borderRadius: "50%", border: `${2 * k}px solid ${A}`,
              transform: `scale(${r.s})`, opacity: r.o }} />
          ))}
          <svg width={60 * k} height={84 * k} viewBox="0 0 60 84" style={{ position: "absolute", left: 2 * k, top: 10 * k,
            overflow: "visible", opacity: appear * (1 - lift), transformOrigin: "50% 97.6%",
            transform: `translateY(${fall + hop - lift * 46 * k}px) scale(${pinS * sx}, ${pinS * sq})`,
            filter: `drop-shadow(0 ${6 * k}px ${7 * k}px rgba(0,0,0,.45))` }}>
            <path d="M30 82 C30 82 5 52 5 30 A25 25 0 1 1 55 30 C55 52 30 82 30 82 Z" fill={A}
              stroke="rgba(0,0,0,.25)" strokeWidth={1.2} />
            <path d="M13 24 A18 18 0 0 1 27 11" fill="none" stroke="rgba(255,255,255,.55)" strokeWidth={3}
              strokeLinecap="round" />
            <circle cx={30} cy={30} r={10} fill={INK} />
          </svg>
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
          <Letters text={place} at={LAND - 2} step={0.9}
            style={{ fontFamily: DISPLAY, fontSize: size, lineHeight: 1, color: "#fff", letterSpacing: "0.035em",
              textShadow: "0 6px 26px rgba(0,0,0,.5)" }} />
          {region ? (
            <Letters text={region} at={LAND + 4} step={0.5}
              style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 28 * k, lineHeight: 1.1, color: A,
                letterSpacing: "0.24em", marginTop: 2 * k, textShadow: "0 3px 14px rgba(0,0,0,.5)" }} />
          ) : null}
          {coord ? (
            <>
              <div style={{ alignSelf: "stretch", height: 1.5 * k, margin: `${12 * k}px 0 ${9 * k}px`,
                background: "linear-gradient(90deg, rgba(255,255,255,.6), rgba(255,255,255,0))",
                transform: `scaleX(${hair})`, transformOrigin: "0% 50%" }} />
              <Decode text={coord} at={LAND + 10} hot={CYAN}
                style={{ fontFamily: MONO, fontWeight: 500, fontSize: 24 * k, color: "rgba(255,255,255,.8)",
                  letterSpacing: "0.06em", textShadow: "0 2px 12px rgba(0,0,0,.6)" }} />
            </>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 5. date and place
/** DATE | PLACE in condensed caps: a glowing divider grows from its centre and both sides slide out of it. */
const DatePlace: Look = ({ overlay, accent }) => {
  const { frame, fps, dur, k } = useT();
  const A = pick(accent);
  const place = clean(overlay.text, 30).toUpperCase();
  const date = clean(overlay.label || overlay.subtitle, 26).toUpperCase();
  if (!place && !date) return null;
  const both = !!place && !!date;
  const grow = ramp(frame, 2, 14);
  const shrink = ramp(frame, dur - 9, 8, easeIn);
  const hair = ramp(frame, 8, Math.round(fps * 0.8), inOut) * (1 - ramp(frame, dur - 11, 9, easeIn));
  const drift = span(frame, 0, dur) * 10 * k;
  const pulse = 0.5 + 0.5 * Math.sin((frame / fps) * Math.PI * 1.3);
  const side = (caption: string, value: string, from: "left" | "right", at: number, color: string) => (
    <div style={{ display: "flex", flexDirection: "column", alignItems: from === "right" ? "flex-end" : "flex-start",
      gap: 4 * k }}>
      <Slide at={at + 5} from={from}>
        <span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 24 * k, letterSpacing: "0.26em",
          color: "rgba(255,255,255,.66)", textShadow: "0 2px 12px rgba(0,0,0,.6)" }}>{caption}</span>
      </Slide>
      <Slide at={at} from={from}>
        <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 46 * k, lineHeight: 1.05, letterSpacing: "0.07em",
          color, textShadow: "0 4px 20px rgba(0,0,0,.55)" }}>{value}</span>
      </Slide>
    </div>
  );
  return (
    <AbsoluteFill>
      <LocalShade pos="12% 78%" a={0.48} op={ramp(frame, 0, 12) * (1 - shrink)} />
      <div style={{ position: "absolute", left: 110 * k, bottom: LOW * k, transform: `translateX(${drift}px)` }}>
        <div style={{ display: "flex", alignItems: "stretch" }}>
          {both ? side("DATE", date, "right", 7, A) : null}
          <div style={{ width: 3 * k, alignSelf: "stretch", flex: "none",
            margin: `${2 * k}px ${28 * k}px ${2 * k}px ${both ? 28 * k : 0}px`, background: A,
            transform: `scaleY(${grow * (1 - shrink)})`, boxShadow: `0 0 ${(6 + 12 * pulse) * k}px ${rgba(A, 0.65)}` }} />
          {both
            ? side("LOCATION", place, "left", 10, "#fff")
            : side(date ? "DATE" : "LOCATION", date || place, "left", 7, date ? A : "#fff")}
        </div>
        <div style={{ height: 1.5 * k, marginTop: 14 * k, transform: `scaleX(${hair})`, transformOrigin: "0% 50%",
          background: "linear-gradient(90deg, rgba(255,255,255,.55), rgba(255,255,255,0))" }} />
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 6. role badge
/** A coin with the initials flips in, its ring draws and an orbit turns; name rises, role wipes open in a pill. */
const RoleBadge: Look = ({ overlay, accent }) => {
  const { frame, fps, dur, k } = useT();
  const A = pick(accent);
  const name = clean(overlay.text, 30);
  const role = clean(overlay.subtitle || overlay.label, 40).toUpperCase();
  if (!name) return null;
  const ini = initials(name) || (Array.from(name)[0] || "").toUpperCase();
  const ink = inkOn(A);
  const D = 128 * k;
  const flip = ramp(frame, 1, 20, backOut);
  const flipOut = ramp(frame, dur - 12, 10, easeIn);
  const rot = (1 - flip) * -110 + flipOut * 100;
  const ring = ramp(frame, 6, Math.round(fps * 0.7), inOut) * (1 - flipOut);
  const orbit = (frame * 0.5) % 360;
  const nameSize = (name.length > 22 ? 52 : 62) * k;
  const slideIn = ramp(frame, 8, 18);
  const pill = ramp(frame, Math.round(fps * 0.45), 14);
  const pillOut = ramp(frame, dur - 12, 9, easeIn);
  const pillClip = Math.min(100, (1 - pill + pillOut) * 100);
  return (
    <AbsoluteFill>
      <LocalShade pos="11% 77%" a={0.45} op={ramp(frame, 0, 12) * (1 - flipOut)} />
      <div style={{ position: "absolute", left: 108 * k, bottom: LOW * k, display: "flex", alignItems: "center",
        gap: 26 * k }}>
        <div style={{ perspective: 900 * k, width: D, height: D, flex: "none" }}>
          <div style={{ position: "relative", width: D, height: D, transform: `rotateY(${rot}deg)`,
            backfaceVisibility: "hidden" }}>
            <svg width={D} height={D} viewBox="0 0 140 140" style={{ position: "absolute", inset: 0, overflow: "visible" }}>
              <circle cx={70} cy={70} r={67} fill="none" stroke="rgba(255,255,255,.5)" strokeWidth={1.4}
                strokeDasharray="2 7" transform={`rotate(${orbit} 70 70)`} />
              <circle cx={70} cy={70} r={59} fill="none" stroke={A} strokeWidth={4} strokeLinecap="round" pathLength={1}
                strokeDasharray={1} strokeDashoffset={1 - ring} transform="rotate(-90 70 70)" />
            </svg>
            <div style={{ position: "absolute", inset: 18 * k, borderRadius: "50%", display: "flex", alignItems: "center",
              justifyContent: "center",
              background: `radial-gradient(circle at 34% 28%, ${tint(A, 0.35)} 0%, ${A} 45%, ${shade(A, 0.62)} 100%)`,
              boxShadow: `0 ${12 * k}px ${30 * k}px rgba(0,0,0,.45), inset 0 ${2 * k}px 0 rgba(255,255,255,.35)` }}>
              <Letters text={ini} at={10} step={2}
                style={{ fontFamily: DISPLAY, fontSize: 54 * k, lineHeight: 1, color: ink, letterSpacing: "0.04em" }} />
            </div>
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 10 * k,
          transform: `translateX(${(1 - slideIn) * -34 * k}px)` }}>
          <Letters text={name.toUpperCase()} at={9} step={0.8}
            style={{ fontFamily: DISPLAY, fontSize: nameSize, lineHeight: 1, color: "#fff", letterSpacing: "0.03em",
              textShadow: "0 6px 26px rgba(0,0,0,.5)" }} />
          {role ? (
            <div style={{ clipPath: `inset(0 ${pillClip.toFixed(2)}% 0 0 round ${40 * k}px)`,
              border: `${2 * k}px solid ${A}`, background: rgba(A, 0.16), borderRadius: 40 * k,
              padding: `${7 * k}px ${20 * k}px ${5 * k}px` }}>
              <Letters text={role} at={Math.round(fps * 0.5)} step={0.45}
                style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 26 * k, lineHeight: 1.05, color: "#fff",
                  letterSpacing: "0.16em" }} />
            </div>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 7. corner brackets
/** A tiny top-left tag: four brackets lock onto it with an overshoot, a scan line passes, they breathe. */
const CornerBrackets: Look = ({ overlay, accent }) => {
  const { frame, fps, dur, k } = useT();
  const A = pick(accent);
  const text = clean(overlay.text, 32).toUpperCase();
  const sub = clean(overlay.subtitle || overlay.label, 40).toUpperCase();
  if (!text) return null;
  const lockF = Math.max(4, Math.round(fps * 0.5));
  const lock = ramp(frame, 0, lockF, backOut);
  const settled = ramp(frame, lockF, 10);
  const release = ramp(frame, dur - 11, 10, easeIn);
  const breathe = Math.sin(((frame - lockF) / fps) * Math.PI * 1.1) * 2.5 * k * settled * (1 - release);
  const off = (1 - lock) * 46 * k + breathe + release * 34 * k;
  const bop = ramp(frame, 0, 5) * (1 - release);
  const flash = interpolate(frame, [lockF - 3, lockF, lockF + 14], [0, 1, 0], clamp);
  const scan = span(frame, lockF - 2, lockF + 14, inOut);
  const scanOp = Math.sin(scan * Math.PI) * (1 - release);
  const dotS = ramp(frame, 5, 10, backOut) * (1 - release);
  const blink = 0.55 + 0.45 * Math.cos((frame / fps) * Math.PI * 2);
  const L = 22 * k;
  const edge = `${3 * k}px solid ${A}`;
  const corners: React.CSSProperties[] = [
    { left: -off, top: -off, borderLeft: edge, borderTop: edge },
    { right: -off, top: -off, borderRight: edge, borderTop: edge },
    { left: -off, bottom: -off, borderLeft: edge, borderBottom: edge },
    { right: -off, bottom: -off, borderRight: edge, borderBottom: edge },
  ];
  return (
    <AbsoluteFill>
      <LocalShade pos="8% 10%" a={0.42} w={46} h={38} op={ramp(frame, 0, 12) * (1 - release)} />
      <div style={{ position: "absolute", left: 100 * k, top: 94 * k }}>
        <div style={{ position: "relative", padding: `${16 * k}px ${28 * k}px ${15 * k}px ${24 * k}px` }}>
          <div style={{ position: "absolute", inset: 0, opacity: bop,
            filter: `drop-shadow(0 0 ${((2 + 10 * flash) * k).toFixed(2)}px ${rgba(A, 0.9)})` }}>
            {corners.map((c, i) => (
              <div key={i} style={{ position: "absolute", width: L, height: L, ...c }} />
            ))}
            <div style={{ position: "absolute", left: 10 * k, right: 10 * k, top: `${scan * 100}%`, height: 2 * k,
              background: `linear-gradient(90deg, ${rgba(A, 0)}, ${A}, ${rgba(A, 0)})`, opacity: scanOp }} />
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 * k }}>
            <div style={{ width: 10 * k, height: 10 * k, borderRadius: "50%", background: A, flex: "none",
              transform: `scale(${dotS})`, opacity: blink, boxShadow: `0 0 ${10 * k}px ${A}` }} />
            <Letters text={text} at={7} step={0.7}
              style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 32 * k, lineHeight: 1.08, color: "#fff",
                letterSpacing: "0.18em", textShadow: "0 3px 14px rgba(0,0,0,.6)" }} />
          </div>
          {sub ? (
            <Letters text={sub} at={13} step={0.45}
              style={{ fontFamily: MONO, fontWeight: 500, fontSize: 24 * k, lineHeight: 1.1, color: "rgba(255,255,255,.72)",
                letterSpacing: "0.08em", marginTop: 6 * k, marginLeft: 22 * k, textShadow: "0 3px 14px rgba(0,0,0,.6)" }} />
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 8. stacked index
/**
 * Two digits rolling into place like an odometer. The number rises out of its
 * mask as the roll starts (it never pops in on frame 0) and slides back down
 * into it at the end.
 */
const RollIndex: React.FC<{ digits: number[]; at: number; size: number; out: number; style?: React.CSSProperties }> =
  ({ digits, at, size, out, style }) => {
    const frame = useCurrentFrame();
    const rise = ramp(frame, at, 14);
    return (
      <div style={{ height: size * 1.02, overflow: "hidden" }}>
        <div style={{ display: "flex", transform: `translateY(${((1 - rise) * 110 + out * 110).toFixed(2)}%)`,
          fontFamily: DISPLAY,
          fontSize: size, lineHeight: 1, fontVariantNumeric: "tabular-nums", ...style }}>
          {digits.map((d, i) => {
            const fromRight = digits.length - 1 - i;
            const travel = (1 + fromRight) * 10 + d;
            const p = ramp(frame, at + i * 3, 26);
            const y = -((p * travel) % 10) * size;
            return (
              <div key={i} style={{ height: size, overflow: "hidden" }}>
                <div style={{ display: "flex", flexDirection: "column", transform: `translateY(${y.toFixed(2)}px)` }}>
                  {DIGITS.map((n, j) => <span key={j} style={{ display: "block", height: size }}>{n}</span>)}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  };

const Hair: React.FC<{ at: number; outAt: number }> = ({ at, outAt }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const g = ramp(frame, at, 16, inOut) * (1 - ramp(frame, outAt, 9, easeIn));
  return (
    <div style={{ height: Math.max(1, 1.5 * k), margin: `${7 * k}px 0 ${6 * k}px`, transform: `scaleX(${g})`,
      transformOrigin: "0% 50%", background: "linear-gradient(90deg, rgba(255,255,255,.45), rgba(255,255,255,.06))" }} />
  );
};

/** An outline index number rolls in and fills with liquid; name / role / organisation rows slide out of masks. */
const StackedIndex: Look = ({ overlay, accent }) => {
  const { frame, fps, dur, k, end } = useT();
  const A = pick(accent);
  const name = clean(overlay.text, 30).toUpperCase();
  const role = clean(overlay.subtitle, 44).toUpperCase();
  const org = clean(overlay.label, 44).toUpperCase();
  if (!name) return null;
  const raw = Number(overlay.value);
  const idx = Number.isFinite(raw) && raw >= 0 && raw < 100 ? Math.round(raw) : 1;
  const digits = String(Math.min(99, Math.max(0, idx))).padStart(2, "0").split("").map(Number);
  const S = 150 * k;
  const idxOut = ramp(frame, dur - 12, 10, easeIn);
  const lvl = ramp(frame, 22, Math.round(fps * 0.9), inOut) * 1.14;
  const wave: string[] = [];
  for (let i = 0; i <= 12; i++) {
    const x = (i / 12) * 100;
    const y = (1 - lvl) * 100 + Math.sin((i / 12) * Math.PI * 3 + frame * 0.2) * 4;
    wave.push(`${x.toFixed(1)}% ${y.toFixed(1)}%`);
  }
  wave.push("100% 110%", "0% 110%");
  const bar = ramp(frame, 4, 16);
  const barOut = ramp(frame, dur - 10, 9, easeIn);
  const drift = span(frame, 0, dur) * 8 * k;
  const nameSize = (name.length > 22 ? 54 : 66) * k;
  return (
    <AbsoluteFill>
      <LocalShade pos="12% 75%" a={0.5} w={64} h={58} op={ramp(frame, 0, 12) * (1 - idxOut)} />
      <div style={{ position: "absolute", left: 100 * k, bottom: LOW * k, display: "flex", alignItems: "center",
        gap: 24 * k, transform: `translateX(${drift}px)` }}>
        <div style={{ position: "relative", flex: "none" }}>
          <RollIndex digits={digits} at={2} size={S} out={idxOut}
            style={{ color: "transparent", WebkitTextStroke: `${2 * k}px rgba(255,255,255,.9)` }} />
          <div style={{ position: "absolute", inset: 0, clipPath: `polygon(${wave.join(", ")})`,
            opacity: lvl > 0.02 ? 1 : 0 }}>
            <RollIndex digits={digits} at={2} size={S} out={idxOut}
              style={{ color: A, WebkitTextStroke: `${2 * k}px ${A}` }} />
          </div>
        </div>
        <div style={{ width: 4 * k, height: 150 * k, background: A, flex: "none",
          transform: `scaleY(${bar * (1 - barOut)})`, transformOrigin: barOut > 0 ? "50% 100%" : "50% 0%",
          boxShadow: `0 0 ${12 * k}px ${rgba(A, 0.5)}` }} />
        <div style={{ display: "flex", flexDirection: "column", alignItems: "stretch" }}>
          <Rise at={8} outAt={end + 1}>
            <span style={{ fontFamily: DISPLAY, fontSize: nameSize, lineHeight: 1, color: "#fff", letterSpacing: "0.035em",
              textShadow: "0 6px 26px rgba(0,0,0,.5)" }}>{name}</span>
          </Rise>
          {role ? (
            <>
              <Hair at={12} outAt={end - 1} />
              <Rise at={13} outAt={end - 1}>
                <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 30 * k, lineHeight: 1.05, color: A,
                  letterSpacing: "0.16em", textShadow: "0 3px 14px rgba(0,0,0,.5)" }}>{role}</span>
              </Rise>
            </>
          ) : null}
          {org ? (
            <>
              <Hair at={17} outAt={end - 3} />
              <Rise at={18} outAt={end - 3}>
                <span style={{ fontFamily: INTER, fontWeight: 700, fontSize: 24 * k, lineHeight: 1.1,
                  color: "rgba(255,255,255,.66)", letterSpacing: "0.22em", textShadow: "0 3px 14px rgba(0,0,0,.5)" }}>
                  {org}
                </span>
              </Rise>
            </>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 9. slant bar
const STREAKS = [{ t: 16, w: 260, h: 3 }, { t: 48, w: 170, h: 2 }, { t: 78, w: 320, h: 3 }];

/** A skewed accent bar whips in trailing speed streaks; a thin role drawer drops out from under it. */
const SlantBar: Look = ({ overlay, accent }) => {
  const { frame, fps, dur, k } = useT();
  const A = pick(accent);
  const name = clean(overlay.text, 30).toUpperCase();
  const role = clean(overlay.subtitle || overlay.label, 44).toUpperCase();
  if (!name) return null;
  const ink = inkOn(A);
  const IN = Math.round(fps * 0.45);
  const xAt = (f: number) => (1 - ramp(f, 0, IN)) * -150 * k + ramp(f, dur - 12, 11, easeIn) * 120 * k;
  const x = xAt(frame);
  const v = Math.abs(x - xAt(frame - 1));
  const streak = Math.min(1, v / (9 * k));
  const wipeIn = ramp(frame, 0, IN + 3);
  const wipeOut = ramp(frame, dur - 12, 11, easeIn);
  const sliver = ramp(frame, 0, 9) * (1 - ramp(frame, dur - 13, 8, easeIn));
  const d = ramp(frame, Math.round(fps * 0.42), 14);
  const dOut = ramp(frame, dur - 17, 9, easeIn);
  const glint = span(frame, fps * 1.0, fps * 1.7, inOut);
  const drift = span(frame, 0, dur) * 8 * k;
  const size = (name.length > 22 ? 50 : 60) * k;
  const SK = -14;
  return (
    <AbsoluteFill>
      <LocalShade pos="12% 78%" a={0.42} op={ramp(frame, 0, 12) * (1 - wipeOut)} />
      <div style={{ position: "absolute", left: 130 * k, bottom: LOW * k, transform: `translateX(${x + drift}px)` }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", transform: `skewX(${SK}deg)` }}>
          {/* The shadow is a drop-shadow on this wrapper: a box-shadow on the bar
              itself would be cut away by the bar's own clip-path wipe. */}
          <div style={{ position: "relative", filter: `drop-shadow(0 ${10 * k}px ${22 * k}px rgba(0,0,0,.4))` }}>
            {/* The streaks trail the bar's visible left edge: on the exit the bar is
                wiped away from the left while it is fastest, so the streaks ride the
                wipe edge and fade with it instead of floating on without a bar. */}
            {STREAKS.map((s, i) => (
              <div key={i} style={{ position: "absolute", top: `${s.t}%`,
                right: `calc(${((1 - wipeOut) * 100).toFixed(2)}% + ${(24 + i * 6) * k}px)`,
                width: s.w * k * streak, height: s.h * k, opacity: streak * (1 - wipeOut),
                background: `linear-gradient(90deg, ${rgba(A, 0)}, ${A})` }} />
            ))}
            <div style={{ position: "absolute", left: -20 * k, top: 0, bottom: 0, width: 9 * k, background: "#fff",
              transform: `scaleY(${sliver})`, transformOrigin: "50% 0%" }} />
            <div style={{ position: "relative", overflow: "hidden",
              clipPath: `inset(0 ${((1 - wipeIn) * 100).toFixed(2)}% 0 ${(wipeOut * 100).toFixed(2)}%)`,
              background: `linear-gradient(100deg, ${shade(A, 0.82)} 0%, ${A} 38%, ${tint(A, 0.12)} 100%)`,
              padding: `${9 * k}px ${40 * k}px ${5 * k}px ${30 * k}px` }}>
              <div style={{ position: "absolute", top: 0, bottom: 0, width: "18%", left: `${-18 + glint * 118}%`,
                background: "linear-gradient(90deg, rgba(255,255,255,0), rgba(255,255,255,.4), rgba(255,255,255,0))" }} />
              <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 2 * k, background: "rgba(255,255,255,.35)" }} />
              <div style={{ position: "relative", transform: `skewX(${-SK}deg)` }}>
                <Letters text={name} at={5} step={0.8}
                  style={{ fontFamily: DISPLAY, fontSize: size, lineHeight: 1, color: ink, letterSpacing: "0.04em" }} />
              </div>
            </div>
          </div>
          {role ? (
            <div style={{ overflow: "hidden", marginLeft: 34 * k }}>
              <div style={{ transform: `translateY(${((-(1 - d) - dOut) * 104).toFixed(2)}%)`,
                background: "rgba(12,12,15,.88)", borderBottom: `${3 * k}px solid ${A}`,
                padding: `${8 * k}px ${22 * k}px ${6 * k}px` }}>
                <div style={{ transform: `skewX(${-SK}deg)`, fontFamily: LABEL, fontWeight: 700, fontSize: 26 * k,
                  lineHeight: 1.05, letterSpacing: "0.18em", color: "#fff", whiteSpace: "nowrap" }}>{role}</div>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 10. source credit
/**
 * Top-right "FOOTAGE: SOURCE": characters rise out of a mask one by one beside a
 * play icon whose ring tracks playback. Top-right on purpose: bottom-right is
 * where the burned-in captions end and where YouTube puts the channel watermark.
 */
const SourceCredit: Look = ({ overlay, accent }) => {
  const { frame, fps, dur, k, end } = useT();
  const A = pick(accent);
  const src = clean(overlay.text, 44).toUpperCase();
  if (!src) return null;
  const head = `${clean(overlay.label, 14).toUpperCase().replace(/[:\s]+$/, "") || "FOOTAGE"}:`;
  const sub = clean(overlay.subtitle, 28).toUpperCase();
  const chars: { ch: string; color: string; bold: boolean }[] = [];
  const push = (t: string, color: string, bold: boolean) =>
    Array.from(t).forEach((ch) => chars.push({ ch, color, bold }));
  push(`${head} `, A, true);
  push(src, "rgba(255,255,255,.94)", false);
  if (sub) push(`  /  ${sub}`, "rgba(255,255,255,.66)", false);
  const n = chars.length;
  const at0 = 9;
  const step = n > 1 ? Math.min(0.9, 26 / (n - 1)) : 0;
  const outStep = n > 1 ? Math.min(0.5, 4 / (n - 1)) : 0;
  const icon = ramp(frame, 2, 14, backOut);
  const iconOut = ramp(frame, dur - 10, 9, easeIn);
  const ring = ramp(frame, 2, 18, inOut);
  const prog = span(frame, fps * 0.8, dur - 12);
  const rule = ramp(frame, 10, 22, inOut) * (1 - ramp(frame, dur - 11, 9, easeIn));
  const tick = ramp(frame, 6, 12) * (1 - iconOut);
  return (
    <AbsoluteFill>
      <LocalShade pos="92% 8%" a={0.45} w={46} h={36} op={ramp(frame, 0, 12) * (1 - iconOut)} />
      <div style={{ position: "absolute", right: 96 * k, top: 94 * k, display: "flex", alignItems: "center",
        gap: 16 * k }}>
        <svg width={44 * k} height={44 * k} viewBox="0 0 44 44"
          style={{ overflow: "visible", flex: "none", transform: `scale(${icon * (1 - iconOut)})` }}>
          <circle cx={22} cy={22} r={19} fill="rgba(0,0,0,.25)" stroke="rgba(255,255,255,.4)" strokeWidth={2}
            pathLength={1} strokeDasharray={1} strokeDashoffset={1 - ring} transform="rotate(-90 22 22)" />
          <circle cx={22} cy={22} r={19} fill="none" stroke={A} strokeWidth={2.6} strokeLinecap="round" pathLength={1}
            strokeDasharray={`${prog.toFixed(4)} 1`} transform="rotate(-90 22 22)" opacity={prog > 0.005 ? 1 : 0} />
          <path d="M18 14.5 L30.5 22 L18 29.5 Z" fill="#fff" />
        </svg>
        <div style={{ width: Math.max(1, 1.5 * k), height: 30 * k, background: "rgba(255,255,255,.45)",
          transform: `scaleY(${tick})` }} />
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end" }}>
          <div style={{ fontFamily: MONO, fontSize: 24 * k, letterSpacing: "0.08em", lineHeight: 1.2, whiteSpace: "nowrap",
            overflow: "hidden", paddingBottom: "0.06em", textShadow: "0 2px 12px rgba(0,0,0,.7)" }}>
            {chars.map((c, i) => {
              // Each character rises out of the line's mask and drops back into it
              // at the end (a mask reveal, not a fade).
              const pin = ramp(frame, at0 + i * step, 9);
              const pout = ramp(frame, end + (n - 1 - i) * outStep, 7, easeIn);
              return (
                <span key={i} style={{ display: "inline-block", whiteSpace: "pre", color: c.color,
                  fontWeight: c.bold ? 700 : 500, opacity: pin < 0.02 || pout > 0.98 ? 0 : 1,
                  transform: `translateY(${((1 - pin) * 108 + pout * 108).toFixed(1)}%)` }}>{c.ch}</span>
              );
            })}
          </div>
          <div style={{ alignSelf: "stretch", height: Math.max(1, 1.2 * k), marginTop: 5 * k, transform: `scaleX(${rule})`,
            transformOrigin: "100% 50%", background: `linear-gradient(270deg, ${rgba(A, 0.9)}, rgba(255,255,255,0))` }} />
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "lt-accent-line": AccentLine,
  "lt-two-tone": TwoTone,
  "lt-glass-card": GlassCard,
  "lt-location-pin": LocationPin,
  "lt-date-place": DatePlace,
  "lt-role-badge": RoleBadge,
  "lt-corner-brackets": CornerBrackets,
  "lt-stacked-index": StackedIndex,
  "lt-slant-bar": SlantBar,
  "lt-source-credit": SourceCredit,
};
