import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { ANTON, ANTON_CAP, MONO, SUBLINE, SUBLINE_CAP } from "../fonts";
import type { Overlay } from "../../types";
import { useK } from "../pro/ProGraphics";
import { spokenToDigits } from "./numWords";

/**
 * PACK C - places and labels: where the footage is, what it is, who shot it
 * (the owner, 2026-10-01: "clean, premium, high-end news channel"). Every
 * look is text riding on the footage in the bold-text language (LibBoldText):
 * Anton for the line that carries it (caps ~40-56 px tall at 1080p), Inter
 * Tight 700 in tracked caps for the small line, white with one amber accent
 * (#F5B400), a soft dark shadow and never a stroke, a box or a band - at most
 * a thin amber rule, a small vector mark or a feathered shade. Clean mask and
 * slide reveals with a small settle, out in the last 11 frames, inside the
 * 96 px safe margins (lower looks a quarter of the height up, clear of the
 * captions). The sound is the registry's (scripts/look_sounds.json), its
 * frames read off the timings below (30 fps from the look's first frame):
 *
 *   plc-location-tag    top left: a small map pin drops, the place slides out
 *                       from behind it ("ATLANTIC CITY, NJ")       pin-drop
 *   plc-region-label    lower left: the region big, a thin amber divider, the
 *                       area small beside it ("NORTH CAROLINA · OUTER BANKS")
 *   plc-section-marker  a region change: "NOW" small in amber on a thin rule,
 *                       the new region drops out from under the rule
 *   plc-route-label     a road in perspective draws, "NC-12" slides out, the
 *                       status ("CLOSED") rises in amber
 *   plc-river-gauge     flowing amber waves, the river big, the gauge (and a
 *                       reading from value / suffix) small
 *   plc-distance-line   "31 MILES" over a scale bar that measures itself out,
 *                       "NORTH OF DALLAS" small under it
 *   plc-coordinates     a crosshair turns in, the lat / lon decode in small
 *                       mono (overlay.locations, else read off the text)
 *   plc-source-credit   tiny, bottom right: "VIDEO | @HANDLE" parting from a
 *                       hairline
 *   plc-footage-tag     top right: "DRONE VIEW", "LIVE CAM" (a pulsing dot),
 *                       "ARCHIVE 2012" (the year in amber) - minimal
 *   plc-warning-label   a small amber alert mark, "FLOOD WARNING" (the alert
 *                       word in amber), a thin amber underline
 *   plc-place-time      top left: "ATLANTIC CITY | 6:40 AM"
 *   plc-where-lower     the WHERE lower third: a thin amber bar, the place big,
 *                       the county / state small, a soft feathered shade
 *
 * overlay.align ("left" / "right" / "center") moves a look to the other side;
 * a full-screen scene centres it. Text is cleaned and fitted (a long name
 * shrinks, then takes two lines), and a look still draws with only its text.
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;

// ------------------------------------------------------------------ the type
const AMBER = "#F5B400";
const WHITE = "#FFFFFF";
const SOFT_WHITE = "rgba(255,255,255,.94)";
const EXIT = 11;                 // frames (30 fps) a look takes to leave
const MARGIN = 96;               // px at 1080p: the safe margin
const SUB_PX = 25;               // the small line (Inter Tight 700, caps ~18 px)
const SUB_TRACK = 0.16;          // its letter spacing (em)
const MAIN_TRACK = 0.012;        // Anton's (em)
// Anton in a line box of 1 em: the caps from 0.065 em to 0.924 em (the baseline).
const ANTON_TOP = 0.065;
const ANTON_BASE = 0.924;
// Inter Tight in a line box of 1 em: the caps from 0.136 em.
const SUB_TOP = 0.136;
const BELOW = 1.2;               // em a line waits under (or over) its mask

/** Anton's advance widths (em). */
const ADV: Record<string, number> = {
  A: 0.485, B: 0.479, C: 0.474, D: 0.493, E: 0.412, F: 0.399, G: 0.485, H: 0.499, I: 0.227, J: 0.466, K: 0.472,
  L: 0.397, M: 0.746, N: 0.498, O: 0.486, P: 0.472, Q: 0.494, R: 0.477, S: 0.461, T: 0.396, U: 0.474, V: 0.469,
  W: 0.712, X: 0.484, Y: 0.446, Z: 0.41, "0": 0.494, "1": 0.331, "2": 0.494, "3": 0.494, "4": 0.494, "5": 0.494,
  "6": 0.494, "7": 0.494, "8": 0.494, "9": 0.494, " ": 0.234, ".": 0.229, ",": 0.236, ":": 0.242, "%": 1.057,
  "$": 0.462, "°": 0.389, "-": 0.311, "–": 0.311, "—": 0.563, "·": 0.234, "'": 0.214, "&": 0.52, "/": 0.405,
  "+": 0.355, "(": 0.291, ")": 0.291, "?": 0.492, "!": 0.229, "#": 0.546, "@": 0.8,
};
const antonEm = (s: string) => Array.from(s).reduce((a, c) => a + (ADV[c] ?? 0.48) + MAIN_TRACK, 0);
/** Inter Tight 700 caps, roughly (em). */
const subEm = (s: string, track = SUB_TRACK) =>
  Array.from(s).reduce((a, c) => a + (c === " " ? 0.24 : /[0-9]/.test(c) ? 0.56 : /[MW@]/.test(c) ? 0.86
    : /[IJ1.,:'·|]/.test(c) ? 0.3 : 0.64) + track, 0);
const monoEm = (s: string, track = 0) => Array.from(s).length * (0.6 + track);

const clamp01 = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);
const easeOut = (t: number) => 1 - (1 - t) ** 3;
const easeIn = (t: number) => t * t * t;
/** Ease-out with a small overshoot (about 3 %): the settle. */
const settle = (t: number, s = 0.9) => 1 + (s + 1) * (t - 1) ** 3 + s * (t - 1) ** 2;
const px = (n: number, k: number) => `${(n * k).toFixed(2)}px`;

// ------------------------------------------------------------------ the words
const str = (v: unknown): string =>
  (typeof v === "string" ? v : typeof v === "number" && Number.isFinite(v) ? String(v) : "")
    .replace(/[‘’]/g, "'").replace(/[“”"]/g, "").replace(/\s+/g, " ").trim();
/** Caps, at most `max` characters (cut at a word). */
const caps = (v: unknown, max = 48): string => {
  const s = str(v).toUpperCase();
  if (s.length <= max) return s;
  const cut = s.slice(0, max);
  const sp = cut.lastIndexOf(" ");
  return (sp > max * 0.6 ? cut.slice(0, sp) : cut).replace(/[\s,·:;-]+$/, "");
};
/** Caps with every spoken number in digits ("thirty-one miles" -> "31 MILES"). */
const capsN = (v: unknown, max = 48) => caps(spokenToDigits(str(v)), max);
const SEP = /\s*(?:·|•|\||—|–|\s-\s|\/\/)\s*/;
const partsOf = (s: string): string[] => s.split(SEP).map((x) => x.trim()).filter(Boolean);
const fmtNum = (v: number) =>
  v.toLocaleString("en-US", { maximumFractionDigits: Math.abs(v) < 100 ? 2 : 0, useGrouping: true });

/** Split a line of words into two balanced lines. */
const twoLines = (s: string): string[] => {
  const words = s.split(" ");
  if (words.length < 2) return [s];
  let best = [s];
  let score = Infinity;
  for (let i = 1; i < words.length; i++) {
    const a = words.slice(0, i).join(" ");
    const b = words.slice(i).join(" ");
    const d = Math.max(antonEm(a), antonEm(b));
    if (d < score) {
      score = d;
      best = [a, b];
    }
  }
  return best;
};

/** The Anton size for a line of `cap` px caps (1080p) in `room` px: shrunk to `minCap`, then two lines. */
const fitAnton = (text: string, cap: number, minCap: number, room: number, k: number, wrap = true) => {
  const size = (cap / ANTON_CAP) * k;
  const least = (minCap / ANTON_CAP) * k;
  const w = Math.max(0.5, antonEm(text));
  if (w * size <= room) return { size, lines: [text] };
  if (w * least <= room || !wrap || !text.includes(" ")) return { size: Math.max(least * 0.8, room / w), lines: [text] };
  const lines = twoLines(text);
  const two = Math.min(size, ...lines.map((l) => room / Math.max(0.5, antonEm(l))));
  return { size: Math.max(least * 0.85, two), lines };
};

const accentOf = (ov: Overlay, accent: string) => (ov.theme && ov.theme !== "accent" && accent ? accent : AMBER);

// ------------------------------------------------------------------ timing
type Clock = { f: number; S: number; exitAt: number; settled: number };
/** The look's clock: everything in at `enterEnd` (30 fps), out over the last EXIT frames. */
const useClock = (enterEnd: number): Clock => {
  const f = useCurrentFrame();
  const { fps, durationInFrames: dur } = useVideoConfig();
  const S = fps / 30;
  const settled = Math.round(enterEnd * S);
  return { f, S, exitAt: Math.max(settled, dur - Math.round(EXIT * S)), settled };
};
/** 0 -> 1 from frame `at` over `len` (30 fps): with the small settle, or a plain ease-out. */
const inn = (c: Clock, at: number, len: number, plain = false) => {
  const t = clamp01((c.f - at * c.S) / (len * c.S));
  return plain ? easeOut(t) : settle(t);
};
/** 0 -> 1 (ease-in) from `delay` frames into the exit, over `len`. */
const out = (c: Clock, delay: number, len: number) => easeIn(clamp01((c.f - c.exitAt - delay * c.S) / (len * c.S)));
/** The slow push while it holds (1 -> 1.008). */
const pushOf = (c: Clock) => 1 + 0.008 * clamp01((c.f - c.settled) / Math.max(1, c.exitAt - c.settled));

// ------------------------------------------------------------------ placement
type H = "left" | "right" | "center";
type V = "top" | "lower" | "bottom";
const sideOf = (ov: Overlay, def: H): H => {
  const a = String(ov.align || "").toLowerCase();
  return a === "left" || a === "right" || a === "center" ? a : def;
};
const itemsOf = (h: H) => (h === "right" ? "flex-end" : h === "center" ? "center" : "flex-start");

/** The block at its corner, inside the safe margins; a full-screen scene centres it a quarter larger. */
const Spot: React.FC<{ ov: Overlay; v: V; h: H; push: number; children: React.ReactNode }> = ({ ov, v, h, push, children }) => {
  const { width, height } = useVideoConfig();
  const mx = MARGIN * (width / 1920);
  const my = MARGIN * (height / 1080);
  const full = Boolean(ov.fullFrame);
  const pos: React.CSSProperties = full
    ? { left: 0, right: 0, top: 0, bottom: 0, justifyContent: "center", alignItems: "center" }
    : {
      ...(v === "top" ? { top: my } : { bottom: v === "lower" ? height * 0.25 : my }),
      ...(h === "center" ? { left: mx, right: mx } : h === "right" ? { right: mx } : { left: mx }),
      alignItems: itemsOf(h),
    };
  const ox = full || h === "center" ? "50%" : h === "right" ? "100%" : "0%";
  const oy = full ? "50%" : v === "top" ? "0%" : "100%";
  return (
    <div style={{ position: "absolute", display: "flex", flexDirection: "column", ...pos, textAlign: full ? "center" : h,
      transformOrigin: `${ox} ${oy}`, transform: `scale(${((full ? 1.25 : 1) * push).toFixed(5)})` }}>
      {children}
    </div>
  );
};

// ------------------------------------------------------------------ lettering
/** The shadow under a main line (on a wrapper, so the mask never cuts it): an edge, a close and a wide shadow. */
const SHADOW = (k: number) => `drop-shadow(0 0 ${px(1.5, k)} rgba(0,0,0,.72)) drop-shadow(0 ${px(2, k)} ${px(3, k)} rgba(0,0,0,.45)) `
  + `drop-shadow(0 ${px(5, k)} ${px(18, k)} rgba(0,0,0,.5))`;
/** Enough body to hold small white caps on snow or a white sky, still no outline. */
const SHADOW_SMALL = (k: number) => `drop-shadow(0 0 ${px(1.2, k)} rgba(0,0,0,.8)) drop-shadow(0 ${px(1, k)} ${px(2, k)} rgba(0,0,0,.55)) `
  + `drop-shadow(0 ${px(2, k)} ${px(8, k)} rgba(0,0,0,.5))`;

type Seg = { t: string; color?: string; dot?: boolean };
const segsOf = (parts: string[], color?: string): Seg[] =>
  parts.flatMap((t, i) => (i ? [{ t: "", dot: true }, { t, color }] : [{ t, color }]));

/**
 * up: rises out of a mask at its baseline; down: drops out of a mask at its
 * top; right / left: slides out sideways from behind its left / right edge.
 * `p` 0 -> 1 in (with its settle), `q` 0 -> 1 back out the same way.
 */
type Mode = "up" | "down" | "right" | "left";
const MASKS: Record<Mode, string> = {
  up: "inset(-0.6em -0.7em -0.12em -0.7em)",
  down: "inset(-0.02em -0.7em -0.6em -0.7em)",
  right: "inset(-0.6em -0.7em -0.6em 0)",
  left: "inset(-0.6em 0 -0.6em -0.7em)",
};
const Masked: React.FC<{ mode: Mode; p: number; q: number; k: number; small?: boolean; font: React.CSSProperties;
  children: React.ReactNode }> = ({ mode, p, q, k, small, font, children }) => {
  const off = (1 - p) + q;
  const hidden = p <= 0 || q >= 1;
  const tf = mode === "up" ? `translateY(${(off * BELOW).toFixed(4)}em)`
    : mode === "down" ? `translateY(${(-off * BELOW).toFixed(4)}em)`
      : mode === "right" ? `translateX(${(-off * 104).toFixed(3)}%)` : `translateX(${(off * 104).toFixed(3)}%)`;
  return (
    <div style={{ ...font, filter: small ? SHADOW_SMALL(k) : SHADOW(k), visibility: hidden ? "hidden" : undefined }}>
      <div style={{ display: "flex", clipPath: MASKS[mode] }}>
        <div style={{ transform: tf, whiteSpace: "pre" }}>{children}</div>
      </div>
    </div>
  );
};

const antonFont = (size: number): React.CSSProperties => ({ fontFamily: ANTON, fontWeight: 400, fontSize: size, lineHeight: 1,
  letterSpacing: `${MAIN_TRACK}em`, color: WHITE });
const subFont = (size: number, track = SUB_TRACK, weight = 700): React.CSSProperties => ({ fontFamily: SUBLINE,
  fontWeight: weight, fontSize: size, lineHeight: 1, letterSpacing: `${track}em`, textTransform: "uppercase", color: SOFT_WHITE });

/** Words in coloured runs, small amber dots between parts. */
const Runs: React.FC<{ segs: Seg[]; ac: string }> = ({ segs, ac }) => (
  <>
    {segs.map((s, i) => (s.dot ? (
      <span key={i} style={{ display: "inline-block", width: "0.22em", height: "0.22em", borderRadius: "50%", background: ac,
        margin: "0 0.6em 0 0.44em", transform: "translateY(-0.14em)", verticalAlign: "middle" }} />
    ) : <span key={i} style={s.color ? { color: s.color } : undefined}>{s.t}</span>))}
  </>
);

/** The small line: tracked caps rising into place as their spacing closes, out with a fade. */
const Small: React.FC<{ segs: Seg[]; size: number; k: number; p: number; q: number; ac: string; track?: number;
  font?: React.CSSProperties }> = ({ segs, size, k, p, q, ac, track = SUB_TRACK, font }) => {
  const t = clamp01(p);
  return (
    <div style={{ ...subFont(size, track + 0.1 * (1 - t)), ...font, whiteSpace: "nowrap", opacity: t * (1 - q),
      transform: `translateY(${((1 - t) * 0.5 + q * 0.35).toFixed(4)}em)`, filter: SHADOW_SMALL(k),
      visibility: p <= 0 || q >= 1 ? "hidden" : undefined }}>
      <Runs segs={segs} ac={ac} />
    </div>
  );
};

/** A thin amber rule, drawn out from `from` (scaleX or scaleY). */
const RuleBar: React.FC<{ w: number; h: number; p: number; from: "left" | "right" | "top" | "bottom" | "center"; ac: string;
  k: number; style?: React.CSSProperties }> = ({ w, h, p, from, ac, k, style }) => {
  const vertical = from === "top" || from === "bottom";
  const origin = from === "left" ? "0% 50%" : from === "right" ? "100% 50%" : from === "top" ? "50% 0%" : from === "bottom"
    ? "50% 100%" : "50% 50%";
  return (
    <div style={{ width: w, height: h, background: ac, borderRadius: Math.min(w, h) / 2, flex: "none",
      transformOrigin: origin, transform: vertical ? `scaleY(${clamp01(p).toFixed(4)})` : `scaleX(${clamp01(p).toFixed(4)})`,
      boxShadow: `0 ${px(1, k)} ${px(3, k)} rgba(0,0,0,.45)`, opacity: p > 0.001 ? 1 : 0, ...style }} />
  );
};

/** The feathered shade behind a block: a blurred dark ellipse, no edge anywhere. */
const Shade: React.FC<{ size: number; k: number; opacity: number }> = ({ size, k, opacity }) => (
  <div style={{ position: "absolute", left: -0.9 * size, right: -1.2 * size, top: -0.7 * size, bottom: -0.7 * size,
    background: "radial-gradient(closest-side, rgba(0,0,0,.5), rgba(0,0,0,.42) 40%, rgba(0,0,0,.2) 70%, rgba(0,0,0,0) 100%)",
    filter: `blur(${(20 * k).toFixed(1)}px)`, opacity, zIndex: -1, pointerEvents: "none" }} />
);

/** The small line's size for these words in this room (never under 18 px at 1080p). */
const subSizeFor = (text: string, room: number, k: number, want = SUB_PX, least = 18) =>
  Math.max(least * k, Math.min(want * k, room / Math.max(1, subEm(text))));

// ------------------------------------------------------------------ the marks
const Pin: React.FC<{ h: number; ac: string }> = ({ h, ac }) => (
  <svg width={(h * 24) / 34} height={h} viewBox="0 0 24 34" style={{ display: "block", overflow: "visible" }}>
    <path fillRule="evenodd" fill={ac} d="M12 0C5.37 0 0 5.37 0 12c0 8.4 10.2 20.3 11.1 21.4a1.2 1.2 0 0 0 1.8 0C13.8 32.3 24 20.4 24 12
      24 5.37 18.63 0 12 0Z M12 7.1a4.9 4.9 0 1 1 0 9.8a4.9 4.9 0 0 1 0-9.8Z" />
  </svg>
);

const Triangle: React.FC<{ h: number; ac: string }> = ({ h, ac }) => (
  <svg width={(h * 26) / 23} height={h} viewBox="0 0 26 23" style={{ display: "block", overflow: "visible" }}>
    <path fillRule="evenodd" fill={ac} d="M11.27 1a2 2 0 0 1 3.46 0l10.99 19a2 2 0 0 1-1.73 3H2.01a2 2 0 0 1-1.73-3Z
      M11.65 7.2h2.7l-.5 8.3h-1.7Z M13 17.2a1.55 1.55 0 1 1 0 3.1a1.55 1.55 0 0 1 0-3.1Z" />
  </svg>
);

/** A road in perspective: its edges draw up, the centre dashes run towards the viewer. */
const Road: React.FC<{ h: number; p: number; run: number; ac: string }> = ({ h, p, run, ac }) => (
  <svg width={h} height={h} viewBox="0 0 40 40" style={{ display: "block", overflow: "visible" }}>
    <path d="M5 39.5 L14.6 0.5 M35 39.5 L25.4 0.5" stroke={WHITE} strokeWidth={3.4} strokeLinecap="round" fill="none"
      pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - clamp01(p)} />
    <path d="M20 39 V2" stroke={ac} strokeWidth={2.8} strokeLinecap="round" fill="none" strokeDasharray="4.2 4.6"
      strokeDashoffset={-run} opacity={clamp01(p * 2 - 0.6)} />
  </svg>
);

/** Three waves, the top one amber, flowing; revealed from the left. */
const Waves: React.FC<{ h: number; reveal: number; flow: number; ac: string }> = ({ h, reveal, flow, ac }) => {
  const wave = (y: number, a: number) => `M-20 ${y} q2.5 ${-a} 5 0` + " t5 0".repeat(15);
  const shift = -(flow % 10);
  return (
    <svg width={(h * 40) / 34} height={h} viewBox="0 0 40 34"
      style={{ display: "block", clipPath: `inset(-20% ${((1 - clamp01(reveal)) * 100).toFixed(2)}% -20% 0)` }}>
      <g transform={`translate(${shift.toFixed(3)} 0)`} fill="none" strokeLinecap="round" strokeWidth={3}>
        <path d={wave(7, 3.4)} stroke={ac} />
        <path d={wave(17, 3.4)} stroke={WHITE} opacity={0.92} />
        <path d={wave(27, 3.4)} stroke={WHITE} opacity={0.62} />
      </g>
    </svg>
  );
};

const Crosshair: React.FC<{ h: number; ac: string }> = ({ h, ac }) => (
  <svg width={h} height={h} viewBox="0 0 24 24" style={{ display: "block", overflow: "visible" }}>
    <circle cx={12} cy={12} r={6.4} stroke={WHITE} strokeWidth={1.8} fill="none" />
    <path d="M12 1.2v4.2 M12 18.6v4.2 M1.2 12h4.2 M18.6 12h4.2" stroke={WHITE} strokeWidth={1.8} strokeLinecap="round" />
    <circle cx={12} cy={12} r={2} fill={ac} />
  </svg>
);

const Viewfinder: React.FC<{ h: number; ac: string }> = ({ h, ac }) => (
  <svg width={h} height={h} viewBox="0 0 24 24" style={{ display: "block", overflow: "visible" }}>
    <path d="M2 8.5V2h6.5 M15.5 2H22v6.5 M22 15.5V22h-6.5 M8.5 22H2v-6.5" stroke={WHITE} strokeWidth={2.4} strokeLinecap="round"
      strokeLinejoin="round" fill="none" />
    <circle cx={12} cy={12} r={2.6} fill={ac} />
  </svg>
);

// ================================================================== plc-location-tag
const PlcLocationTag: Look = ({ overlay, accent }) => {
  const k = useK();
  const { width } = useVideoConfig();
  const ac = accentOf(overlay, accent);
  const h = sideOf(overlay, "left");
  const c = useClock(26);
  const main = caps(overlay.text || overlay.label || overlay.subtitle, 60) || "LOCATION";
  const sub0 = caps(overlay.text ? overlay.subtitle || overlay.label : "", 44);
  const sub = sub0 !== main ? sub0 : "";
  const cap0 = 40 * k;
  const pinH = cap0 * 1.22;
  const gap = cap0 * 0.42;
  const { size, lines } = fitAnton(main, 40, 34, 0.42 * width - pinH - gap, k);
  const cap = size * ANTON_CAP;
  // The pin falls onto the line (gravity: its tip touches the first baseline at frame 8, the sound's peak),
  // squashes a little and springs back, and a ring spreads once from the tip.
  const fallT = clamp01(c.f / (8 * c.S));
  const fall = 1 - fallT * fallT;
  const pinQ = out(c, 4, 7);
  const squash = Math.sin(clamp01((c.f - 8 * c.S) / (6 * c.S)) * Math.PI) * 0.08;
  const ring = clamp01((c.f - 8 * c.S) / (16 * c.S));
  const textQ = out(c, 0, 8);
  const subP = inn(c, 14, 12, true);
  const subQ = out(c, 0, 7);
  const subSize = sub ? subSizeFor(sub, 0.42 * width - pinH - gap, k) : 0;
  return (
    <AbsoluteFill>
      <Spot ov={overlay} v="top" h={h} push={pushOf(c)}>
        <div style={{ display: "flex", alignItems: "flex-start" }}>
          <div style={{ position: "relative", width: (pinH * 24) / 34, height: pinH, marginTop: size * ANTON_BASE - pinH,
            marginRight: gap, flex: "none" }}>
            <div style={{ position: "absolute", left: "50%", bottom: -cap * 0.05, width: cap * 0.9, height: cap * 0.24,
              marginLeft: -cap * 0.45, borderRadius: "50%", border: `${Math.max(1.5, 2 * k).toFixed(2)}px solid ${ac}`,
              transform: `scale(${(0.3 + 0.9 * easeOut(ring)).toFixed(4)})`, opacity: ring > 0 && ring < 1 ? 0.75 * (1 - ring) : 0 }} />
            <div style={{ position: "absolute", inset: 0, filter: SHADOW(k), transformOrigin: "50% 100%",
              opacity: clamp01(fallT * 4) * (1 - pinQ),
              transform: `translateY(${(-fall * 1.1 * pinH - pinQ * 0.5 * pinH).toFixed(2)}px) scale(${(1 + squash).toFixed(4)}, ${(1 - squash).toFixed(4)})` }}>
              <Pin h={pinH} ac={ac} />
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: h === "right" ? "flex-end" : "flex-start" }}>
            {lines.map((l, i) => (
              <Masked key={i} mode="right" p={inn(c, 7 + i * 3, 13)} q={textQ} k={k} font={antonFont(size)}>{l}</Masked>
            ))}
            {sub ? (
              <div style={{ marginTop: size * 0.2 }}>
                <Small segs={segsOf(partsOf(sub))} size={subSize} k={k} p={subP} q={subQ} ac={ac} />
              </div>
            ) : null}
          </div>
        </div>
      </Spot>
    </AbsoluteFill>
  );
};

// ================================================================== plc-region-label
const PlcRegionLabel: Look = ({ overlay, accent }) => {
  const k = useK();
  const { width } = useVideoConfig();
  const ac = accentOf(overlay, accent);
  const h = sideOf(overlay, "left");
  const c = useClock(26);
  const parts = partsOf(caps(overlay.text || overlay.label, 80));
  const main = parts[0] || caps(overlay.subtitle, 40) || "REGION";
  const area = parts.length > 1 ? parts.slice(1).join(" · ") : caps(overlay.text ? overlay.subtitle || overlay.label : "", 40);
  const room = (h === "center" ? 0.8 : 0.55) * width;
  const subPx = SUB_PX * k;
  const areaW = area ? subEm(area) * subPx : 0;
  // One line when it fits: the region, a thin amber divider, the area beside it; else the area under it.
  const inline = Boolean(area) && antonEm(main) * (46 / ANTON_CAP) * k + areaW + 60 * k <= room;
  const { size, lines } = fitAnton(main, 46, 34, inline ? room - areaW - 60 * k : room, k);
  const cap = size * ANTON_CAP;
  const mainQ = out(c, 4, 7);
  const divP = easeOut(clamp01((c.f - 10 * c.S) / (7 * c.S))) * (1 - out(c, 2, 6));
  const areaP = inn(c, 13, 12);
  const areaQ = out(c, 0, 7);
  const subSize = area && !inline ? subSizeFor(area, room, k) : subPx;
  const subCap = subSize * SUBLINE_CAP;
  const mainLines = lines.map((l, i) => (
    <Masked key={i} mode="up" p={inn(c, 2 + i * 3, 12)} q={mainQ} k={k} font={antonFont(size)}>{l}</Masked>
  ));
  return (
    <AbsoluteFill>
      <Spot ov={overlay} v="lower" h={h} push={pushOf(c)}>
        {inline ? (
          <div style={{ display: "flex", alignItems: "flex-start" }}>
            <div style={{ display: "flex", flexDirection: "column" }}>{mainLines}</div>
            <RuleBar w={Math.max(2, 3 * k)} h={cap * 0.94} p={divP} from="center" ac={ac} k={k}
              style={{ marginTop: size * (lines.length - 1) + size * ANTON_TOP + cap * 0.03, marginLeft: cap * 0.42, marginRight: cap * 0.42 }} />
            <div style={{ marginTop: size * (lines.length - 1) + size * ANTON_TOP + cap / 2 - subCap / 2 - subSize * SUB_TOP }}>
              <Masked mode="right" p={areaP} q={areaQ} k={k} small font={subFont(subSize)}>{area}</Masked>
            </div>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", alignItems: itemsOf(h) }}>
            {mainLines}
            {area ? (
              <div style={{ display: "flex", alignItems: "center", marginTop: size * 0.24 }}>
                <RuleBar w={subSize * 1.1} h={Math.max(2, 3 * k)} p={divP} from="left" ac={ac} k={k} style={{ marginRight: subSize * 0.55 }} />
                <Masked mode="right" p={areaP} q={areaQ} k={k} small font={subFont(subSize)}>{area}</Masked>
              </div>
            ) : null}
          </div>
        )}
      </Spot>
    </AbsoluteFill>
  );
};

// ================================================================== plc-section-marker
const KICK = /^(NOW|NEXT|MEANWHILE|ELSEWHERE|LATER|ALSO|THEN|FIRST|FINALLY|BACK TO|BACK IN|OVER TO|OVER IN|HEADING TO|MOVING TO|ON TO|DOWN IN|UP IN|OUT IN|INSIDE)\b\s*[:·\-–—|]?\s*(.+)$/;
const PlcSectionMarker: Look = ({ overlay, accent }) => {
  const k = useK();
  const { width } = useVideoConfig();
  const ac = accentOf(overlay, accent);
  const h = sideOf(overlay, "left");
  const c = useClock(26);
  const raw = caps(overlay.text || overlay.subtitle, 72);
  let kicker = "";
  let main = raw;
  const m = KICK.exec(raw);
  if (m) {
    kicker = m[1];
    main = m[2];
  } else if (raw.includes(":")) {
    kicker = raw.slice(0, raw.indexOf(":")).trim().slice(0, 18);
    main = raw.slice(raw.indexOf(":") + 1).trim();
  }
  kicker = kicker || caps(overlay.label, 18) || "NOW";
  main = main || "—";
  const sub = caps(overlay.text ? overlay.subtitle : "", 48);
  const room = (h === "center" ? 0.8 : 0.55) * width;
  const { size, lines } = fitAnton(main, 52, 38, room, k);
  const cap = size * ANTON_CAP;
  const mainW = Math.max(...lines.map((l) => antonEm(l) * size));
  const kickSize = SUB_PX * k;
  const kickW = subEm(kicker, 0.2) * kickSize;
  const ruleW = Math.max(cap * 1.6, Math.min(mainW * 0.62, room - kickW) - kickW * 0.2);
  const ruleP = easeOut(clamp01((c.f - 2 * c.S) / (14 * c.S))) * (1 - out(c, 3, 8));
  const kickP = inn(c, 1, 10, true);
  const kickQ = out(c, 2, 7);
  const mainQ = out(c, 0, 8);
  const subP = inn(c, 15, 12, true);
  const subQ = out(c, 0, 7);
  const right = h === "right";
  return (
    <AbsoluteFill>
      <Spot ov={overlay} v="lower" h={h} push={pushOf(c)}>
        <div style={{ display: "flex", flexDirection: right ? "row-reverse" : "row", alignItems: "center", marginBottom: size * 0.12 }}>
          <Small segs={[{ t: kicker, color: ac }]} size={kickSize} k={k} p={kickP} q={kickQ} ac={ac} track={0.2} />
          <RuleBar w={ruleW} h={Math.max(2, 3 * k)} p={ruleP} from={right ? "right" : "left"} ac={ac} k={k}
            style={right ? { marginRight: kickSize * 0.7 } : { marginLeft: kickSize * 0.5 }} />
        </div>
        {lines.map((l, i) => (
          <Masked key={i} mode="down" p={inn(c, 6 + i * 3, 13)} q={mainQ} k={k} font={antonFont(size)}>{l}</Masked>
        ))}
        {sub ? (
          <div style={{ marginTop: size * 0.22 }}>
            <Small segs={segsOf(partsOf(sub))} size={subSizeFor(sub, room, k)} k={k} p={subP} q={subQ} ac={ac} />
          </div>
        ) : null}
      </Spot>
    </AbsoluteFill>
  );
};

// ================================================================== plc-route-label
const DIRS = "NORTHBOUND|SOUTHBOUND|EASTBOUND|WESTBOUND|BOTH WAYS|BOTH DIRECTIONS|IN BOTH DIRECTIONS";
const STATUS = new RegExp(`(?:^|\\s|[:·\\-–—|]\\s*)((?:(?:${DIRS})\\s+)?(?:IS\\s+|ARE\\s+|NOW\\s+|STILL\\s+)?`
  + "(?:CLOSED|CLOSURE|CLOSES|SHUT DOWN|SHUT|REOPENED|REOPENS|OPEN|FLOODED|UNDER WATER|UNDERWATER|BLOCKED|IMPASSABLE|"
  + "WASHED OUT|DAMAGED|DETOUR|GRIDLOCKED|JAMMED|ONE LANE|EVACUATION ROUTE|TOLLS SUSPENDED)"
  + `(?:\\s+(?:${DIRS}|TO TRAFFIC|INDEFINITELY|AHEAD))?)\\s*$`);
const PlcRouteLabel: Look = ({ overlay, accent }) => {
  const k = useK();
  const { width } = useVideoConfig();
  const ac = accentOf(overlay, accent);
  const h = sideOf(overlay, "left");
  const c = useClock(26);
  const raw = capsN(overlay.text || overlay.label, 80);
  let route = raw;
  let status = "";
  const m = STATUS.exec(raw);
  if (m && m.index > 0) {
    route = raw.slice(0, m.index).replace(/[\s:·\-–—|]+$/, "");
    status = m[1].replace(/^(?:IS|ARE|NOW|STILL)\s+/, "").replace(/\s+(?:IS|ARE|NOW|STILL)\s+/, " ");
  } else if (overlay.text && overlay.label) status = caps(overlay.label, 24);
  route = route || "ROUTE";
  const sub = capsN(overlay.subtitle, 48);
  const room = (h === "center" ? 0.8 : 0.55) * width;
  const want = (46 / ANTON_CAP) * k;
  const lineEm = antonEm(route) + (status ? 0.3 + antonEm(status) : 0) + 1.05;
  const size = Math.max((32 / ANTON_CAP) * k, Math.min(want, room / lineEm));
  const cap = size * ANTON_CAP;
  const roadP = easeOut(clamp01((c.f - 0) / (12 * c.S))) * (1 - out(c, 5, 6));
  const run = (c.f / c.S) * 0.42;
  const routeQ = out(c, 3, 8);
  const statusQ = out(c, 0, 7);
  return (
    <AbsoluteFill>
      <Spot ov={overlay} v="lower" h={h} push={pushOf(c)}>
        <div style={{ display: "flex", alignItems: "flex-start" }}>
          <div style={{ marginTop: size * ANTON_TOP - cap * 0.04, marginRight: cap * 0.36, filter: SHADOW(k), flex: "none" }}>
            <Road h={cap * 1.08} p={roadP} run={run} ac={ac} />
          </div>
          <Masked mode="right" p={inn(c, 5, 12)} q={routeQ} k={k} font={antonFont(size)}>{route}</Masked>
          {status ? (
            <div style={{ marginLeft: size * 0.3 }}>
              <Masked mode="up" p={inn(c, 13, 11)} q={statusQ} k={k} font={{ ...antonFont(size), color: ac }}>{status}</Masked>
            </div>
          ) : null}
        </div>
        {sub ? (
          <div style={{ marginTop: size * 0.22, marginLeft: h === "right" ? 0 : cap * 1.44 }}>
            <Small segs={segsOf(partsOf(sub))} size={subSizeFor(sub, room, k)} k={k} p={inn(c, 16, 12, true)} q={out(c, 0, 7)} ac={ac} />
          </div>
        ) : null}
      </Spot>
    </AbsoluteFill>
  );
};

// ================================================================== plc-river-gauge
const PlcRiverGauge: Look = ({ overlay, accent }) => {
  const k = useK();
  const { width } = useVideoConfig();
  const ac = accentOf(overlay, accent);
  const h = sideOf(overlay, "left");
  const c = useClock(26);
  const parts = partsOf(caps(overlay.text || overlay.label, 80));
  const river = parts[0] || "RIVER";
  const station = parts.length > 1 ? parts.slice(1).join(" · ") : caps(overlay.text ? overlay.subtitle || overlay.label : "", 40);
  const v = typeof overlay.value === "number" && Number.isFinite(overlay.value) ? overlay.value : null;
  const reading = v !== null ? `${fmtNum(v)} ${caps(overlay.suffix, 10) || "FT"}` : "";
  const room = (h === "center" ? 0.8 : 0.55) * width;
  const iconW = ((46 * 1.0 * 40) / 34) * k;
  const { size, lines } = fitAnton(river, 46, 34, room - iconW * 1.4, k);
  const cap = size * ANTON_CAP;
  const smallSegs: Seg[] = [...(station ? [{ t: station }] : []), ...(station && reading ? [{ t: "", dot: true }] : []),
    ...(reading ? [{ t: reading, color: ac }] : [])];
  const smallText = [station, reading].filter(Boolean).join(" · ");
  const reveal = easeOut(clamp01((c.f - 0) / (14 * c.S))) * (1 - out(c, 4, 7));
  const flow = (c.f / c.S) * 0.32;
  const mainQ = out(c, 3, 8);
  return (
    <AbsoluteFill>
      <Spot ov={overlay} v="lower" h={h} push={pushOf(c)}>
        <div style={{ display: "flex", alignItems: "flex-start" }}>
          <div style={{ marginTop: size * ANTON_TOP + cap * 0.06, marginRight: cap * 0.38, filter: SHADOW(k), flex: "none" }}>
            <Waves h={cap * 0.88} reveal={reveal} flow={flow} ac={ac} />
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
            {lines.map((l, i) => (
              <Masked key={i} mode="up" p={inn(c, 4 + i * 3, 12)} q={mainQ} k={k} font={antonFont(size)}>{l}</Masked>
            ))}
            {smallText ? (
              <div style={{ marginTop: size * 0.22 }}>
                <Small segs={smallSegs} size={subSizeFor(smallText, room - cap * 1.4, k)} k={k} p={inn(c, 12, 12, true)}
                  q={out(c, 0, 7)} ac={ac} />
              </div>
            ) : null}
          </div>
        </div>
      </Spot>
    </AbsoluteFill>
  );
};

// ================================================================== plc-distance-line
const UNITS = "MILES|MILE|MI|KILOMETERS|KILOMETRES|KILOMETER|KILOMETRE|KM|FEET|FOOT|FT|YARDS|YARD|METERS|METRES|METER|METRE|BLOCKS|BLOCK";
const DIST = new RegExp(`^(?:(ABOUT|NEARLY|ALMOST|ROUGHLY|SOME|JUST|ONLY|OVER|UNDER|MORE THAN|LESS THAN|UP TO)\\s+)?`
  + `(\\d[\\d,]*(?:\\.\\d+)?)\\s*(${UNITS})\\b[\\s,:·\\-–—]*(.*)$`);
/** The figure said later in the line ("NORTH OF DALLAS, 31 MILES"). */
const DIST_ANY = new RegExp(`(?:\\b(ABOUT|NEARLY|ALMOST|ROUGHLY|SOME|JUST|ONLY|OVER|UNDER|MORE THAN|LESS THAN|UP TO)\\s+)?`
  + `(\\d[\\d,]*(?:\\.\\d+)?)\\s*(${UNITS})\\b`);
const unitOf = (u: string, n: number) => {
  const one = Math.abs(n) === 1;
  if (/^(MI|MILES?)$/.test(u)) return one ? "MILE" : "MILES";
  if (/^(FT|FOOT|FEET)$/.test(u)) return one ? "FOOT" : "FEET";
  if (/^KILOMET/.test(u)) return one ? "KILOMETER" : "KILOMETERS";
  if (/^MET/.test(u)) return one ? "METER" : "METERS";
  return u;
};
const PlcDistanceLine: Look = ({ overlay, accent }) => {
  const k = useK();
  const { width } = useVideoConfig();
  const ac = accentOf(overlay, accent);
  const h = sideOf(overlay, "left");
  const c = useClock(26);
  const raw = capsN(overlay.text || overlay.label, 80);
  let fig = "";
  let rest = raw;
  const m = DIST.exec(raw);
  const v = typeof overlay.value === "number" && Number.isFinite(overlay.value) ? overlay.value : null;
  if (m) {
    const n = Number(m[2].replace(/,/g, ""));
    const unit = unitOf(caps(overlay.suffix, 12) || m[3], n);
    fig = `${m[1] ? m[1] + " " : ""}${m[2]} ${unit}`;
    rest = m[4];
  } else if (v !== null) {
    fig = `${fmtNum(v)} ${unitOf(caps(overlay.suffix, 12) || "MILES", v)}`;
  } else {
    const a = DIST_ANY.exec(raw);
    if (a) {
      fig = `${a[1] ? a[1] + " " : ""}${a[2]} ${unitOf(a[3], Number(a[2].replace(/,/g, "")))}`;
      rest = (raw.slice(0, a.index) + " " + raw.slice(a.index + a[0].length)).replace(/\s*[,:·\-–—]\s*$|^\s*[,:·\-–—]\s*/g, "")
        .replace(/\s+/g, " ").trim();
    }
  }
  if (!fig) {
    fig = raw || "—";
    rest = "";
  }
  rest = rest || caps(overlay.subtitle, 48);
  const room = (h === "center" ? 0.8 : 0.55) * width;
  const { size, lines } = fitAnton(fig, 50, 36, room, k);
  const cap = size * ANTON_CAP;
  const figW = Math.max(...lines.map((l) => antonEm(l) * size));
  const lineW = Math.max(figW, cap * 2.4);
  const draw = easeOut(clamp01((c.f - 2 * c.S) / (14 * c.S)));
  const back = out(c, 3, 8);
  const reach = draw * (1 - back);
  const tick = Math.max(2, 2.6 * k);
  const tickH = cap * 0.34;
  const endP = settle(clamp01((c.f - 15 * c.S) / (5 * c.S))) * (1 - back);
  const dot = cap * 0.24;
  const right = h === "right";
  const lineBox = (
    <div style={{ position: "relative", width: lineW, height: tickH, marginTop: size * 0.2, filter: SHADOW_SMALL(k) }}>
      <div style={{ position: "absolute", top: (tickH - tick) / 2, height: tick, width: lineW, background: SOFT_WHITE,
        borderRadius: tick / 2, transformOrigin: right ? "100% 50%" : "0% 50%", transform: `scaleX(${reach.toFixed(4)})`,
        opacity: reach > 0.001 ? 1 : 0, [right ? "right" : "left"]: 0 }} />
      <div style={{ position: "absolute", top: 0, [right ? "right" : "left"]: 0, width: tick, height: tickH, background: SOFT_WHITE,
        borderRadius: tick / 2, transform: `scaleY(${clamp01(inn(c, 2, 5) * (1 - back)).toFixed(4)})` }} />
      <div style={{ position: "absolute", top: 0, [right ? "left" : "right"]: 0, width: tick, height: tickH, background: SOFT_WHITE,
        borderRadius: tick / 2, transform: `scaleY(${Math.max(0, endP).toFixed(4)})` }} />
      <div style={{ position: "absolute", top: (tickH - dot) / 2, width: dot, height: dot, borderRadius: "50%", background: ac,
        [right ? "right" : "left"]: reach * (lineW - dot), opacity: reach > 0.02 ? 1 : 0,
        boxShadow: `0 0 ${px(6, k)} rgba(0,0,0,.4)` }} />
    </div>
  );
  return (
    <AbsoluteFill>
      <Spot ov={overlay} v="lower" h={h} push={pushOf(c)}>
        {lines.map((l, i) => (
          <Masked key={i} mode="up" p={inn(c, 6 + i * 3, 12)} q={out(c, 2, 8)} k={k} font={antonFont(size)}>{l}</Masked>
        ))}
        {lineBox}
        {rest ? (
          <div style={{ marginTop: size * 0.24 }}>
            <Small segs={segsOf(partsOf(rest))} size={subSizeFor(rest, room, k)} k={k} p={inn(c, 14, 12, true)} q={out(c, 0, 7)} ac={ac} />
          </div>
        ) : null}
      </Spot>
    </AbsoluteFill>
  );
};

// ================================================================== plc-coordinates
const COORD = /(-?\d{1,2}(?:\.\d+)?)\s*°?\s*([NS])?\s*[,;/\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*°?\s*([EW])?/i;
/** The place's coordinates, as precise as their source (the gazetteer's: 4 decimals; typed ones as typed). */
const coordsOf = (ov: Overlay): { lat: number; lon: number; label: string; dec: number } | null => {
  const loc = (ov.locations || []).find((l) => l && Number.isFinite(Number(l.lat)) && Number.isFinite(Number(l.lon)));
  if (loc && Math.abs(Number(loc.lat)) <= 90 && Math.abs(Number(loc.lon)) <= 180) {
    // The place as the overlay words it, else the gazetteer's name for it.
    const said = str(ov.text);
    return { lat: Number(loc.lat), lon: Number(loc.lon), label: said && !COORD.test(said) ? said : str(loc.label), dec: 4 };
  }
  for (const src of [str(ov.text), str(ov.label), str(ov.subtitle)]) {
    const m = COORD.exec(src);
    if (!m) continue;
    const lat = Number(m[1]) * (/s/i.test(m[2] || "") ? -1 : 1);
    const lon = Number(m[3]) * (/w/i.test(m[4] || "") ? -1 : 1);
    if (Math.abs(lat) <= 90 && Math.abs(lon) <= 180 && (m[1].includes(".") || m[3].includes(".") || m[2] || m[4])) {
      const dec = Math.min(4, Math.max(1, (m[1].split(".")[1] || "").length, (m[3].split(".")[1] || "").length));
      return { lat, lon, label: src.replace(m[0], " ").replace(/[\s,;:·\-–—|]+/g, " ").trim(), dec };
    }
  }
  return null;
};
/** A stable pseudo-random digit for character i at a 2-frame step. */
const scramble = (i: number, step: number) => String(Math.floor(((Math.sin(i * 91.7 + step * 12.9898) * 43758.5453) % 1 + 1) % 1 * 10));
const PlcCoordinates: Look = ({ overlay, accent }) => {
  const k = useK();
  const { width } = useVideoConfig();
  const ac = accentOf(overlay, accent);
  const h = sideOf(overlay, "left");
  const c = useClock(34);
  const co = coordsOf(overlay);
  const fmt = (n: number, pos: string, neg: string) => `${Math.abs(n).toFixed(co ? co.dec : 4)}° ${n >= 0 ? pos : neg}`;
  const line = co ? `${fmt(co.lat, "N", "S")} · ${fmt(co.lon, "E", "W")}` : caps(overlay.text || overlay.label, 36) || "—";
  const place = caps(co ? co.label || overlay.subtitle : overlay.subtitle, 40);
  const room = (h === "center" ? 0.8 : 0.5) * width;
  const monoPx = Math.max(18 * k, Math.min(27 * k, (room * 0.86) / Math.max(4, monoEm(line, 0.02))));
  const iconH = monoPx * 1.25;
  const chars = Array.from(line);
  const n = Math.max(1, chars.length - 1);
  // Each digit flickers from its appearance and locks in turn, the last at frame 30 whatever the length.
  const step = Math.floor(c.f / (2 * c.S));
  const shown = chars.map((ch, i) => {
    const appear = (4 + (10 * i) / n) * c.S;
    const lock = (10 + (20 * i) / n) * c.S;
    if (c.f < appear) return " ";
    return /[0-9]/.test(ch) && c.f < lock ? scramble(i, step) : ch;
  }).join("");
  const crossP = inn(c, 0, 12);
  const crossQ = out(c, 3, 8);
  const lineQ = out(c, 0, 8);
  const placeP = inn(c, 18, 12, true);
  return (
    <AbsoluteFill>
      <Spot ov={overlay} v="lower" h={h} push={pushOf(c)}>
        <div style={{ display: "flex", alignItems: "center" }}>
          <div style={{ marginRight: monoPx * 0.55, filter: SHADOW(k), opacity: clamp01(crossP * 2) * (1 - crossQ), flex: "none",
            transform: `rotate(${((1 - crossP) * -90).toFixed(2)}deg) scale(${(0.6 + 0.4 * crossP - 0.3 * crossQ).toFixed(4)})` }}>
            <Crosshair h={iconH} ac={ac} />
          </div>
          <Masked mode="right" p={inn(c, 3, 10, true)} q={lineQ} k={k} small
            font={{ fontFamily: MONO, fontWeight: 500, fontSize: monoPx, lineHeight: 1, letterSpacing: "0.02em", color: WHITE }}>
            {shown}
          </Masked>
        </div>
        {place ? (
          <div style={{ marginTop: monoPx * 0.5, marginLeft: h === "right" ? 0 : iconH + monoPx * 0.55 }}>
            <Small segs={segsOf(partsOf(place), ac)} size={subSizeFor(place, room, k, 21, 16)} k={k} p={placeP} q={out(c, 0, 7)} ac={ac}
              track={0.2} />
          </div>
        ) : null}
      </Spot>
    </AbsoluteFill>
  );
};

// ================================================================== plc-source-credit
const CREDIT = /^\s*(VIDEO|VIDEOS|PHOTO|PHOTOS|FOOTAGE|IMAGE|IMAGES|SOURCE|SOURCES|VIA|COURTESY(?:\s+OF)?|CREDIT|CREDITS|DATA|MAP|RADAR|SATELLITE|FILM|CLIP|AUDIO|DRONE)\b\s*[:\-–—·|]?\s*(.+)$/i;
const PlcSourceCredit: Look = ({ overlay, accent }) => {
  const k = useK();
  const { width } = useVideoConfig();
  const ac = accentOf(overlay, accent);
  const h = sideOf(overlay, "right");
  const c = useClock(18);
  const raw = str(overlay.text || overlay.subtitle);
  const m = CREDIT.exec(raw);
  let label = m ? m[1] : caps(overlay.label, 14);
  const name = caps(m ? m[2] : raw, 34) || caps(overlay.label, 34) || "—";
  label = caps(label, 14) || (name.startsWith("@") ? "VIDEO" : "SOURCE");
  const track = 0.14;
  const want = 20 * k;
  const total = subEm(label, track) + subEm(name, track) + 1.4;
  const size = Math.max(15 * k, Math.min(want, (0.26 * width) / Math.max(1, total)));
  const cap = size * SUBLINE_CAP;
  const divP = easeOut(clamp01((c.f - 1 * c.S) / (6 * c.S))) * (1 - out(c, 6, 5));
  const p = inn(c, 4, 11);
  const q = out(c, 1, 7);
  return (
    <AbsoluteFill>
      <Spot ov={overlay} v="bottom" h={h} push={1}>
        <div style={{ display: "flex", alignItems: "center" }}>
          <Masked mode="left" p={p} q={q} k={k} small font={{ ...subFont(size, track), color: ac }}>{label}</Masked>
          <div style={{ width: Math.max(1.5, 1.8 * k), height: cap * 1.25, margin: `0 ${(size * 0.55).toFixed(2)}px`,
            background: "rgba(255,255,255,.7)", transform: `scaleY(${divP.toFixed(4)})`, opacity: divP > 0.001 ? 1 : 0,
            boxShadow: `0 0 ${px(3, k)} rgba(0,0,0,.6)`, flex: "none" }} />
          <Masked mode="right" p={p} q={q} k={k} small font={subFont(size, track)}>{name}</Masked>
        </div>
      </Spot>
    </AbsoluteFill>
  );
};

// ================================================================== plc-footage-tag
const PlcFootageTag: Look = ({ overlay, accent }) => {
  const k = useK();
  const { width } = useVideoConfig();
  const ac = accentOf(overlay, accent);
  const h = sideOf(overlay, "right");
  const c = useClock(18);
  let words = caps(overlay.text || overlay.label, 28) || "FOOTAGE";
  const sub = caps(overlay.subtitle, 16);
  if (sub && !words.includes(sub)) words = `${words} ${sub}`.slice(0, 40);
  const live = /\bLIVE\b/.test(words);
  const archive = /\b(ARCHIVE|ARCHIVAL|FILE|NEWSREEL|HISTORIC|ARCHIVES)\b/.test(words);
  const year = /\b(1[89]\d\d|20\d\d)\b/.exec(words);
  const segs: Seg[] = year
    ? [{ t: words.slice(0, year.index) }, { t: year[1], color: ac }, { t: words.slice(year.index + year[1].length) }]
    : [{ t: words }];
  const size = Math.max(17 * k, Math.min(24 * k, (0.3 * width) / Math.max(1, subEm(words, 0.2))));
  const cap = size * SUBLINE_CAP;
  const popP = inn(c, 0, 9);
  const popQ = out(c, 4, 7);
  const textP = inn(c, 4, 11);
  const textQ = out(c, 0, 7);
  const track = 0.18 + 0.1 * (1 - clamp01(textP));
  const pulse = (c.f / c.S) % 30 / 30;
  const iconH = cap * 1.35;
  const icon = live ? (
    <div style={{ position: "relative", width: cap * 0.78, height: cap * 0.78 }}>
      <div style={{ position: "absolute", inset: 0, borderRadius: "50%", background: ac,
        transform: `scale(${(1 + 1.3 * easeOut(pulse)).toFixed(4)})`, opacity: c.f > 9 * c.S ? 0.45 * (1 - pulse) : 0 }} />
      <div style={{ position: "absolute", inset: 0, borderRadius: "50%", background: ac }} />
    </div>
  ) : archive ? (
    <div style={{ width: cap * 0.6, height: cap * 0.6, borderRadius: "50%", background: ac }} />
  ) : <Viewfinder h={iconH} ac={ac} />;
  return (
    <AbsoluteFill>
      <Spot ov={overlay} v="top" h={h} push={1}>
        <div style={{ display: "flex", alignItems: "center" }}>
          <div style={{ marginRight: size * 0.62, filter: SHADOW_SMALL(k), flex: "none", opacity: clamp01(popP * 2) * (1 - popQ),
            transform: `scale(${Math.max(0, 0.4 + 0.6 * popP - 0.4 * popQ).toFixed(4)})` }}>
            {icon}
          </div>
          <Masked mode="right" p={textP} q={textQ} k={k} small font={subFont(size, track)}>
            <Runs segs={segs} ac={ac} />
          </Masked>
        </div>
      </Spot>
    </AbsoluteFill>
  );
};

// ================================================================== plc-warning-label
const ALERT = /\b(WARNING|WARNINGS|WATCH|WATCHES|ADVISORY|EMERGENCY|ALERT|ORDER|ORDERS|STATEMENT)\b/g;
const PlcWarningLabel: Look = ({ overlay, accent }) => {
  const k = useK();
  const { width } = useVideoConfig();
  const ac = accentOf(overlay, accent);
  const h = sideOf(overlay, "left");
  const c = useClock(30);
  const main = caps(overlay.text || overlay.label, 64) || "WARNING";
  const sub = capsN(overlay.text ? overlay.subtitle || overlay.label : overlay.subtitle, 52);
  const room = (h === "center" ? 0.8 : 0.55) * width;
  const triW = ((46 * 26) / 23) * k;
  const { size, lines } = fitAnton(main, 46, 34, room - triW * 1.35, k);
  const cap = size * ANTON_CAP;
  // The alert word in amber (the last one said: "FLOOD WATCH" -> WATCH).
  const keyed = (l: string): Seg[] => {
    const all = Array.from(l.matchAll(ALERT));
    const hit = all[all.length - 1];
    if (!hit || hit.index === undefined) return [{ t: l }];
    return [{ t: l.slice(0, hit.index) }, { t: hit[0], color: ac }, { t: l.slice(hit.index + hit[0].length) }];
  };
  const triP = inn(c, 0, 9);
  const triQ = out(c, 4, 7);
  const triH = cap * 1.0;
  const rowW = (triH * 26) / 23 + cap * 0.34 + Math.max(...lines.map((l) => antonEm(l) * size));
  const ruleP = easeOut(clamp01((c.f - 10 * c.S) / (13 * c.S))) * (1 - out(c, 0, 8));
  const right = h === "right";
  return (
    <AbsoluteFill>
      <Spot ov={overlay} v="lower" h={h} push={pushOf(c)}>
        <div style={{ display: "flex", alignItems: "flex-start" }}>
          <div style={{ marginTop: size * ANTON_TOP, marginRight: cap * 0.34, filter: SHADOW(k), flex: "none",
            opacity: clamp01(triP * 2.5) * (1 - triQ), transformOrigin: "50% 80%",
            transform: `scale(${Math.max(0, 0.45 + 0.55 * triP - 0.35 * triQ).toFixed(4)})` }}>
            <Triangle h={triH} ac={ac} />
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
            {lines.map((l, i) => (
              <Masked key={i} mode="right" p={inn(c, 5 + i * 3, 12)} q={out(c, 2, 8)} k={k} font={antonFont(size)}>
                <Runs segs={keyed(l)} ac={ac} />
              </Masked>
            ))}
          </div>
        </div>
        <RuleBar w={rowW} h={Math.max(2, 3 * k)} p={ruleP} from={right ? "right" : "left"} ac={ac} k={k}
          style={{ marginTop: size * 0.2 }} />
        {sub ? (
          <div style={{ marginTop: size * 0.24 }}>
            <Small segs={segsOf(partsOf(sub))} size={subSizeFor(sub, room, k)} k={k} p={inn(c, 17, 12, true)} q={out(c, 0, 7)} ac={ac} />
          </div>
        ) : null}
      </Spot>
    </AbsoluteFill>
  );
};

// ================================================================== plc-place-time
const ZONES = "ET|EST|EDT|CT|CST|CDT|MT|MST|MDT|PT|PST|PDT|AKST|AKDT|HST|UTC|GMT|LOCAL TIME|LOCAL";
const TIME = new RegExp(`\\b(\\d{1,2}(?::\\d{2})?\\s*(?:A\\.?M\\.?|P\\.?M\\.?)|\\d{1,2}:\\d{2}|NOON|MIDNIGHT)(?:\\s+(${ZONES})\\b)?`);
const timeOf = (s: string) => {
  const m = TIME.exec(s);
  if (!m) return null;
  const t = m[1].replace(/\./g, "").replace(/\s+/g, " ");
  const tm = /^(\d{1,2}(?::\d{2})?)\s*(AM|PM)?$/.exec(t);
  return { at: m.index, len: m[0].length, figure: tm ? tm[1] : t, period: tm && tm[2] ? tm[2] : "", zone: m[2] || "" };
};
const PlcPlaceTime: Look = ({ overlay, accent }) => {
  const k = useK();
  const { width } = useVideoConfig();
  const ac = accentOf(overlay, accent);
  const h = sideOf(overlay, "left");
  const c = useClock(28);
  const raw = capsN(overlay.text || overlay.label, 72);
  let t = timeOf(raw);
  let place = raw;
  let sub = capsN(overlay.subtitle, 44);
  if (t) {
    place = (raw.slice(0, t.at) + " " + raw.slice(t.at + t.len)).replace(/\s*[·•|—–,]\s*$|^\s*[·•|—–,]\s*/g, "")
      .replace(/\s+/g, " ").trim().replace(/^(?:IN|AT|NEAR|OVER|FROM)\s+/, "");
  } else if (sub && timeOf(sub)) {
    t = timeOf(sub);
    sub = "";
  }
  place = place || caps(overlay.label, 40) || "—";
  const tags = t ? [t.period, t.zone].filter(Boolean).join(" ") : "";
  const room = 0.46 * width;
  const tagSize = (40 * k * 0.42) / SUBLINE_CAP;     // the AM / PM beside the figure, sized for the room
  const lineEm = antonEm(place) + (t ? 0.85 + antonEm(t.figure) : 0);
  const tagRoom = tags ? subEm(tags, 0.06) * tagSize + 12 * k : 0;
  const size = Math.max((30 / ANTON_CAP) * k, Math.min((40 / ANTON_CAP) * k, (room - tagRoom) / lineEm));
  const cap = size * ANTON_CAP;
  const tagPx = (cap * 0.42) / SUBLINE_CAP;
  const divP = easeOut(clamp01((c.f - 9 * c.S) / (7 * c.S))) * (1 - out(c, 2, 6));
  const tagP = easeOut(clamp01((c.f - 19 * c.S) / (8 * c.S)));
  const tagQ = out(c, 0, 5);
  return (
    <AbsoluteFill>
      <Spot ov={overlay} v="top" h={h} push={pushOf(c)}>
        <div style={{ display: "flex", alignItems: "flex-start" }}>
          <Masked mode="up" p={inn(c, 2, 12)} q={out(c, 4, 7)} k={k} font={antonFont(size)}>{place}</Masked>
          {t ? (
            <>
              <RuleBar w={Math.max(2, 3 * k)} h={cap * 0.94} p={divP} from="center" ac={ac} k={k}
                style={{ marginTop: size * ANTON_TOP + cap * 0.03, marginLeft: cap * 0.4, marginRight: cap * 0.4 }} />
              <Masked mode="right" p={inn(c, 12, 12)} q={out(c, 0, 7)} k={k} font={antonFont(size)}>{t.figure}</Masked>
              {tags ? (
                <div style={{ marginLeft: cap * 0.16, marginTop: size * ANTON_TOP - tagPx * SUB_TOP, fontFamily: SUBLINE, fontWeight: 700,
                  fontSize: tagPx, lineHeight: 1, letterSpacing: "0.06em", color: ac, whiteSpace: "nowrap", filter: SHADOW_SMALL(k),
                  opacity: tagP * (1 - tagQ), transform: `translateY(${((1 - tagP) * 0.6 + tagQ * 0.5).toFixed(4)}em)` }}>{tags}</div>
              ) : null}
            </>
          ) : null}
        </div>
        {sub ? (
          <div style={{ marginTop: size * 0.22 }}>
            <Small segs={segsOf(partsOf(sub))} size={subSizeFor(sub, room, k, 23)} k={k} p={inn(c, 16, 12, true)} q={out(c, 0, 7)} ac={ac} />
          </div>
        ) : null}
      </Spot>
    </AbsoluteFill>
  );
};

// ================================================================== plc-where-lower
const PlcWhereLower: Look = ({ overlay, accent }) => {
  const k = useK();
  const { width } = useVideoConfig();
  const ac = accentOf(overlay, accent);
  const h = sideOf(overlay, "left");
  const c = useClock(28);
  const text = caps(overlay.text || overlay.label, 80);
  let parts = partsOf(text);
  if (parts.length === 1 && !overlay.subtitle && text.includes(",")) {
    const at = text.indexOf(",");
    parts = [text.slice(0, at).trim(), text.slice(at + 1).trim()].filter(Boolean);
  }
  const place = parts[0] || "—";
  const area = parts.length > 1 ? parts.slice(1).join(", ") : caps(overlay.subtitle || (overlay.text ? overlay.label : ""), 48);
  const room = (h === "center" ? 0.8 : 0.55) * width;
  const { size, lines } = fitAnton(place, 54, 38, room, k);
  const cap = size * ANTON_CAP;
  const bar = Math.max(3, 4 * k);
  const right = h === "right";
  const barP = easeOut(clamp01((c.f - 0) / (12 * c.S)));
  const barQ = out(c, 3, 8);
  const shade = easeOut(clamp01(c.f / (12 * c.S))) * (1 - out(c, 4, 8));
  const mode: Mode = right ? "left" : "right";
  const subSize = area ? subSizeFor(area, room, k) : 0;
  return (
    <AbsoluteFill>
      <Spot ov={overlay} v="lower" h={h} push={pushOf(c)}>
        <div style={{ position: "relative", display: "flex", flexDirection: right ? "row-reverse" : "row", alignItems: "stretch" }}>
          <Shade size={size} k={k} opacity={shade} />
          <div style={{ width: bar, flex: "none", borderRadius: bar / 2, background: ac, marginTop: size * ANTON_TOP,
            marginBottom: area ? subSize * (1 - SUBLINE_CAP - SUB_TOP) : size * (1 - ANTON_BASE),
            transformOrigin: barQ > 0 ? "50% 100%" : "50% 0%", transform: `scaleY(${(barP * (1 - barQ)).toFixed(4)})`,
            boxShadow: `0 ${px(1, k)} ${px(4, k)} rgba(0,0,0,.45)` }} />
          <div style={{ display: "flex", flexDirection: "column", alignItems: right ? "flex-end" : "flex-start",
            [right ? "marginRight" : "marginLeft"]: cap * 0.36 }}>
            {lines.map((l, i) => (
              <Masked key={i} mode={mode} p={inn(c, 4 + i * 3, 13)} q={out(c, 2, 8)} k={k} font={antonFont(size)}>{l}</Masked>
            ))}
            {area ? (
              <div style={{ marginTop: size * 0.2 }}>
                <Masked mode={mode} p={inn(c, 10, 13)} q={out(c, 0, 8)} k={k} small font={subFont(subSize)}>
                  <Runs segs={segsOf(partsOf(area))} ac={ac} />
                </Masked>
              </div>
            ) : null}
          </div>
        </div>
      </Spot>
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "plc-location-tag": PlcLocationTag,
  "plc-region-label": PlcRegionLabel,
  "plc-section-marker": PlcSectionMarker,
  "plc-route-label": PlcRouteLabel,
  "plc-river-gauge": PlcRiverGauge,
  "plc-distance-line": PlcDistanceLine,
  "plc-coordinates": PlcCoordinates,
  "plc-source-credit": PlcSourceCredit,
  "plc-footage-tag": PlcFootageTag,
  "plc-warning-label": PlcWarningLabel,
  "plc-place-time": PlcPlaceTime,
  "plc-where-lower": PlcWhereLower,
};
