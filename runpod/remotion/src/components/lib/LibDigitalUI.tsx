import React from "react";
import { AbsoluteFill, Easing, Img, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY, INTER, LABEL, MONO } from "../fonts";
import type { Overlay, OverlayItem, SceneMedia } from "../../types";
import { LetterLine, Odometer, Scrim, lines, ramp, useHold, useK } from "../pro/ProGraphics";
import { Heading } from "../pro/ProCharts";
import { CaseBackdrop } from "../pro/ProCase";
import { F as KF, fit as kfit } from "../pro/Kit";

/**
 * Digital & social UI mockups (family "ui-", registry category DOCUMENTS):
 * the story told through the screens it happened on. Every mockup is generic
 * (no real app, logo or brand), built from shapes and type in the house
 * style: Bebas / Barlow for the big words, Inter for UI copy, JetBrains Mono
 * for chrome. Text rises out of its masks (typing only inside a search or an
 * address bar), holds with a slow push, and leaves in the last ~12 frames.
 *
 *   ui-social-post         a post card tilts up out of perspective, the avatar ring draws, the lines
 *                          rise; then the heart is tapped: squash, spark burst, the like count rolls
 *   ui-comment-thread      a comments panel unfolds; the top comment pops, thread lines draw down to
 *                          each reply as it lands with an accent "new" flash
 *   ui-search-bar          a search bar stretches open, the query types with a human rhythm, the
 *                          suggestions drop (typed part light, completion bold), a selection steps
 *                          down to the pick, enter, the dropdown folds and the results count rolls
 *   ui-notification-stack  (tag) phone notifications drop in on the right with a buzz, each pushing
 *                          the last down until the oldest tucks behind; the count badge ticks up
 *   ui-chat-bubbles        a chat panel: typing dots bounce in the sender's bubble, then the bubble
 *                          grows into the message; the thread scrolls to keep up; a read tick lands
 *   ui-phone-screen        own backdrop: a phone rises out of the frame in 3D, the screen wakes on a
 *                          news story; the phone turns aside and the story slides out from behind it
 *                          as a large card, its key words marked
 *   ui-browser-window      own backdrop: a browser swings in, the address types, a load bar races,
 *                          the page scrolls to the key sentence, a cursor clicks it and it is marked
 *   ui-video-player        (tag) player chrome on the footage: title, a play pop, the scrubber running
 *                          to the timestamp between chapter gaps, a hover preview with the chapter
 *   ui-email-card          an inbox: the unread row glows, opens and morphs into the full email
 *                          (sender, date, subject), the key line marked in the accent
 *   ui-poll-results        a poll card: the options land as radio buttons, one is voted, then every
 *                          bar fills to its share with its percentage rolling, the winner checked
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const easeIn = Easing.bezier(0.7, 0, 0.84, 0);
const GOLD = "#F2B544";
const CYAN = "#53c8ff";
const RED = "#ff3b30";
const INK = "#0d0e12";
const PAGE_INK = "#16181d";
const MUTED = "rgba(255,255,255,.58)";

// ================================================================== clock
/**
 * The clock every look runs on. Text leaves at `end` (dur - 14), containers
 * over the last 12 frames (`out` 0..1). `T(sec)` converts choreography times
 * to frames and runs them faster (never slower) on short overlays.
 */
const useT = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, width, height } = useVideoConfig();
  const k = useK();
  const dur = Math.max(1, durationInFrames);
  const end = Math.max(1, dur - 14);
  const out = ramp(frame, dur - 12, 10, easeIn);
  const sp = Math.max(0.55, Math.min(1, dur / 165));
  const T = (sec: number) => Math.round(sec * fps * sp);
  return { frame, fps, dur, end, out, k, width, height, sp, T };
};

// ================================================================== text helpers
/** A field as tidy text, cut at a word boundary (with an ellipsis) past `max` characters. */
const clean = (s: unknown, max = 400): string => {
  const raw = typeof s === "string" ? s : typeof s === "number" && Number.isFinite(s) ? String(s) : "";
  const t = raw.replace(/\s+/g, " ").trim();
  if (t.length <= max) return t;
  const cut = t.slice(0, max);
  const sp = cut.lastIndexOf(" ");
  return `${(sp > max * 0.6 ? cut.slice(0, sp) : cut).replace(/[\s,;:.·-]+$/, "")}…`;
};
const unquote = (s: string): string => s.replace(/^["“”'‘’«»]+|["“”'‘’«»]+$/g, "").trim();
const finite = (v: unknown): number | null => {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string" && v.trim()) {
    const n = Number(v.replace(/,/g, ""));
    return Number.isFinite(n) ? n : null;
  }
  return null;
};
/** The items as an array of objects whatever arrived (a malformed plan must not crash the render). */
const itemsOf = (items: unknown): OverlayItem[] =>
  Array.isArray(items) ? (items.filter((it) => Boolean(it) && typeof it === "object") as OverlayItem[]) : [];
/** Wrapped lines, at most `max` of them; the last ends in an ellipsis when the text was cut. */
const wrap = (text: string, chars: number, max: number): string[] => {
  const safe = text.split(" ").map((w) => (w.length > chars ? `${w.slice(0, Math.max(1, chars - 1))}…` : w)).join(" ");
  const all = lines(safe, chars);
  if (all.length <= max) return all;
  const kept = all.slice(0, max);
  kept[max - 1] = `${kept[max - 1].replace(/[\s,;:.·…-]+$/, "")}…`;
  return kept;
};
/** Where each wrapped line starts in the joined text. */
const offsets = (ls: string[]): number[] => {
  const o: number[] = [];
  let n = 0;
  for (const l of ls) {
    o.push(n);
    n += l.length + 1;
  }
  return o;
};
/** The character range of `phrase` inside `text` (case-insensitive), if it is there. */
const findRange = (text: string, phrase: string): [number, number] | null => {
  const p = unquote(phrase).toLowerCase();
  if (p.length < 3) return null;
  const i = text.toLowerCase().indexOf(p);
  return i >= 0 ? [i, i + p.length] : null;
};
type Run = { t: string; kind: "plain" | "hot" | "tag" };
/** One wrapped line as runs: the highlighted phrase, hashtags / mentions / links, plain words. */
const runs = (line: string, offset: number, range: [number, number] | null): Run[] => {
  const out: Run[] = [];
  let pos = offset;
  const words = line.split(" ");
  words.forEach((w, i) => {
    const s = pos;
    const e = pos + w.length;
    pos = e + 1;
    const kind: Run["kind"] = range && e > range[0] && s < range[1] ? "hot"
      : /^[#@][\p{L}\p{N}_]/u.test(w) || /^https?:\/\//i.test(w) ? "tag" : "plain";
    const piece = i < words.length - 1 ? `${w} ` : w;
    const last = out[out.length - 1];
    if (last && last.kind === kind) last.t += piece;
    else out.push({ t: piece, kind });
  });
  return out;
};

/** Deterministic 0..1 noise of a number (never Math.random). */
const rnd = (n: number): number => {
  const x = Math.sin(n * 12.9898 + 78.233) * 43758.5453;
  return x - Math.floor(x);
};
const seedOf = (s: string): number => {
  let h = 7;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 100003;
  return h;
};

// ================================================================== colour helpers
const pick = (a: string): string => (typeof a === "string" && a.trim() ? a.trim() : GOLD);
const rgbOf = (c: string): [number, number, number] | null => {
  const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec((c || "").trim());
  if (!m) return null;
  const h = m[1].length === 3 ? m[1].split("").map((x) => x + x).join("") : m[1];
  const n = parseInt(h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
const rgba = (c: string, a: number): string => {
  const v = rgbOf(c);
  return v ? `rgba(${v[0]},${v[1]},${v[2]},${Math.max(0, Math.min(1, a))})` : c;
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
/** Near-black on a light accent (gold), white on a dark one. */
const inkOn = (c: string): string => {
  const v = rgbOf(c);
  if (!v) return "#fff";
  return (0.299 * v[0] + 0.587 * v[1] + 0.114 * v[2]) / 255 > 0.6 ? INK : "#fff";
};
/** An accent marker sweeping across inline text (p 0..1). */
const markStyle = (accent: string, p: number, alpha = 0.42): React.CSSProperties => ({
  backgroundImage: `linear-gradient(transparent 12%, ${rgba(accent, alpha)} 12%, ${rgba(accent, alpha)} 92%, transparent 92%)`,
  backgroundRepeat: "no-repeat", backgroundSize: `${Math.max(0, Math.min(1, p)) * 100}% 100%`,
  boxDecorationBreak: "clone", WebkitBoxDecorationBreak: "clone",
});

// ================================================================== names, media, numbers
const initials = (name: string): string => {
  const words = name.replace(/[@#_.]/g, " ").split(/\s+/)
    .map((w) => Array.from(w).filter((c) => /[\p{L}\p{N}]/u.test(c)).join(""))
    .filter(Boolean);
  if (!words.length) return "•";
  const first = Array.from(words[0]);
  const second = words.length > 1 ? Array.from(words[words.length - 1])[0] : first[1];
  return `${first[0] || ""}${second || ""}`.toUpperCase();
};
const slug = (s: string, max = 40): string =>
  s.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "").slice(0, max).replace(/-+$/, "");
const stillOf = (m?: SceneMedia | null): string => {
  if (!m || typeof m !== "object" || typeof m.url !== "string") return "";
  return m.type === "image" ? m.url : (typeof m.thumbnail === "string" ? m.thumbnail : "");
};
const firstStill = (ov: Overlay): string => {
  const media: unknown = ov.media;
  if (!Array.isArray(media)) return "";
  for (const m of media as (SceneMedia | null)[]) {
    const s = stillOf(m);
    if (s) return s;
  }
  return "";
};
/** A social count as a short number and its unit: 48,200 -> 48.2 "K". */
const social = (v: number): { n: number; s: string } => {
  const a = Math.abs(v);
  const r1 = (x: number) => Math.round(x * 10) / 10;
  if (a >= 999950000) return { n: r1(v / 1e9), s: "B" };
  if (a >= 999950) return { n: r1(v / 1e6), s: "M" };
  if (a >= 10000) return { n: r1(v / 1e3), s: "K" };
  return { n: Math.round(v), s: "" };
};
const compact = (v: number): string => {
  const { n, s } = social(v);
  return `${Number.isInteger(n) ? n.toLocaleString("en-US") : n.toFixed(1)}${s}`;
};
const mmss = (s: number): string => {
  const t = Math.max(0, Math.floor(s));
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const ss = String(t % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
};

// ================================================================== text reveal
/**
 * A line sliding up out of its mask, and at `out` (default dur - 14) up and
 * away again: the house text reveal with an exit.
 */
const Rise: React.FC<{ at: number; frames?: number; out?: number; style?: React.CSSProperties; children: React.ReactNode }> =
  ({ at, frames = 14, out, style, children }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();
    const end = out ?? durationInFrames - 14;
    const p = ramp(frame, at, frames);
    const q = ramp(frame, end, 9, easeIn);
    const y = (1 - p) * 112 - q * 112;
    return (
      <div style={{ overflow: "hidden", paddingBottom: "0.1em", marginBottom: "-0.1em", ...style }}>
        <div style={{ transform: `translateY(${y.toFixed(2)}%)`, opacity: p < 0.01 || q > 0.99 ? 0 : 1 }}>{children}</div>
      </div>
    );
  };

// ================================================================== icons
const I = {
  reply: "M20 11.5c0 4.1-3.6 7.3-8 7.3-1.2 0-2.4-.2-3.4-.7L4 19.5l1.3-3.7C4.5 14.6 4 13.1 4 11.5c0-4.1 3.6-7.3 8-7.3s8 3.2 8 7.3z",
  repost: "M4.5 10.5V9a2.5 2.5 0 0 1 2.5-2.5h11 M15 3.5l3 3-3 3 M19.5 13.5V15a2.5 2.5 0 0 1-2.5 2.5H6 M9 20.5l-3-3 3-3",
  heart: "M12 20.3l-1.3-1.2C6 14.9 3 12.2 3 8.9 3 6.2 5.1 4.2 7.7 4.2c1.6 0 3.1.7 4.3 1.9 1.2-1.2 2.7-1.9 4.3-1.9 2.6 0 4.7 2 4.7 4.7 0 3.3-3 6-7.7 10.2L12 20.3z",
  share: "M12 14.5V3.8 M7.8 8 12 3.8 16.2 8 M5 12.5v6a1.8 1.8 0 0 0 1.8 1.8h10.4a1.8 1.8 0 0 0 1.8-1.8v-6",
  search: "M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13z M15.3 15.3 20 20",
  check: "M6.5 12.5l3.5 3.5 7.5-8",
  bell: "M6.5 16.5V11a5.5 5.5 0 0 1 11 0v5.5l1.5 2h-14z M10 20.5a2 2 0 0 0 4 0",
  drop: "M12 3.5c2.9 3.7 6 7.1 6 10.4a6 6 0 0 1-12 0c0-3.3 3.1-6.7 6-10.4z",
  alert: "M12 4.2 21 19.5H3z M12 10v4.2 M12 16.9v.2",
  heat: "M10 14.4V5.5a2 2 0 0 1 4 0v8.9a4 4 0 1 1-4 0z M12 9v7",
  back: "M15 5l-7 7 7 7",
  fwd: "M9 5l7 7-7 7",
  reload: "M19 12a7 7 0 1 1-2.1-5 M19 4.5V9h-4.5",
  lock: "M7 11h10v8.5H7z M9 11V8.5a3 3 0 0 1 6 0V11",
  play: "M8 5.5v13l10.5-6.5z",
  pause: "M8.5 5.5v13 M15.5 5.5v13",
  next: "M6 5.5v13l9-6.5z M18 5.5v13",
  volume: "M4 9.5h3.5L12 5.5v13l-4.5-4H4z M15.5 9a4 4 0 0 1 0 6 M18 6.5a7.5 7.5 0 0 1 0 11",
  gear: "M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z M12 3v2.5 M12 18.5V21 M3 12h2.5 M18.5 12H21 M5.6 5.6l1.8 1.8 M16.6 16.6l1.8 1.8 M5.6 18.4l1.8-1.8 M16.6 7.4l1.8-1.8",
  full: "M4 9V4h5 M15 4h5v5 M20 15v5h-5 M9 20H4v-5",
  archive: "M3.5 5h17v4h-17z M5 9v10h14V9 M10 13h4",
  trash: "M4.5 7h15 M9 7V4.5h6V7 M6.5 7l1 12.5h9l1-12.5",
  star: "M12 4l2.4 5 5.4.6-4 3.7 1.1 5.3L12 16l-4.9 2.6 1.1-5.3-4-3.7 5.4-.6z",
  reply2: "M10 8.5 4.5 13 10 17.5 M4.5 13H14a5.5 5.5 0 0 1 5.5 5.5",
  arrowLeft: "M19 12H5 M11 6l-6 6 6 6",
  mail: "M3.5 6h17v12h-17z M3.5 6.5l8.5 6.5 8.5-6.5",
  cursor: "M5 3.5v15l4-4 2.8 6 2.6-1.2-2.8-5.8h5.6z",
  chevron: "M7 10l5 5 5-5",
  ticks: "M1.5 9.5 5.5 13.5 13.5 4.5 M8.5 12 10 13.5 18 4.5",
  signal: "M4 18v-3 M9 18v-6 M14 18v-9 M19 18V6",
};

/** A 24-unit stroke icon; `draw` 0..1 draws it on. */
const Icon: React.FC<{ d: string; size: number; color: string; width?: number; fill?: string; draw?: number;
  style?: React.CSSProperties }> = ({ d, size, color, width = 1.8, fill = "none", draw = 1, style }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" style={{ display: "block", overflow: "visible", flexShrink: 0, ...style }}>
    <path d={d} fill={fill} stroke={color} strokeWidth={width} strokeLinecap="round" strokeLinejoin="round"
      pathLength={1} strokeDasharray={draw < 1 ? 1 : undefined} strokeDashoffset={draw < 1 ? 1 - Math.max(0, draw) : undefined} />
  </svg>
);

/** A round avatar with initials; `ring` 0..1 draws an accent ring round it (a story ring). */
const Avatar: React.FC<{ name: string; size: number; accent: string; ring?: number; pop?: number;
  tone?: "accent" | "gray" | "light" }> = ({ name, size, accent, ring = 0, pop = 1, tone = "accent" }) => {
  const bg = tone === "accent" ? `linear-gradient(145deg, ${tint(accent, 0.18)} 0%, ${shade(accent, 0.66)} 100%)`
    : tone === "light" ? "linear-gradient(145deg, #eceef2 0%, #c8ccd4 100%)" : "linear-gradient(145deg, #555965 0%, #2c2e35 100%)";
  const ink = tone === "accent" ? inkOn(accent) : tone === "light" ? "#2a2d34" : "#fff";
  const c = size * 0.68;
  return (
    <div style={{ position: "relative", width: size, height: size, flexShrink: 0, transform: `scale(${Math.max(0, pop)})` }}>
      {ring > 0 ? (
        <svg width={size * 1.36} height={size * 1.36} style={{ position: "absolute", left: -size * 0.18, top: -size * 0.18,
          overflow: "visible" }}>
          <circle cx={c} cy={c} r={size * 0.6} fill="none" stroke={accent} strokeWidth={size * 0.045} strokeLinecap="round"
            pathLength={1} strokeDasharray={1} strokeDashoffset={1 - Math.min(1, ring)} transform={`rotate(-90 ${c} ${c})`} />
        </svg>
      ) : null}
      <div style={{ width: size, height: size, borderRadius: "50%", background: bg, display: "flex", alignItems: "center",
        justifyContent: "center", fontFamily: INTER, fontWeight: 800, fontSize: size * 0.38, color: ink, letterSpacing: "0.02em",
        boxShadow: `inset 0 ${-size * 0.05}px ${size * 0.12}px rgba(0,0,0,.2)` }}>
        {initials(name)}
      </div>
    </div>
  );
};

/** A plain round check badge that pops and draws its tick. */
const Badge: React.FC<{ size: number; accent: string; at: number }> = ({ size, accent, at }) => {
  const frame = useCurrentFrame();
  const p = ramp(frame, at, 14, backOut);
  const d = ramp(frame, at + 5, 10, inOut);
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" style={{ display: "block", flexShrink: 0, transform: `scale(${p})` }}>
      <circle cx={12} cy={12} r={11} fill={accent} />
      <path d={I.check} fill="none" stroke={inkOn(accent)} strokeWidth={2.6} strokeLinecap="round" strokeLinejoin="round"
        pathLength={1} strokeDasharray={1} strokeDashoffset={1 - d} />
    </svg>
  );
};

// ================================================================== looks
// ------------------------------------------------------------------ 1. social post
/** The heart: tapped, it squashes, fills, throws a ring and sparks, and its count rolls up. */
const HeartButton: React.FC<{ n: number | null; at: number; tap: number; accent: string; end: number; seed: number }> =
  ({ n, at, tap, accent, end, seed }) => {
    const frame = useCurrentFrame();
    const { fps } = useVideoConfig();
    const k = useK();
    const p = ramp(frame, at, 14, backOut);
    const on = frame >= tap;
    const squash = on ? 0.55 + 0.45 * ramp(frame, tap, 14, backOut) : 1;
    const b = interpolate(frame, [tap, tap + 18], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
    const S = 36 * k;
    const num = n !== null ? social(Math.max(0, n)) : null;
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 12 * k }}>
        <svg width={S} height={S} viewBox="0 0 24 24" style={{ display: "block", overflow: "visible", transform: `scale(${p})` }}>
          {on && b < 1 ? (
            <g>
              <circle cx={12} cy={12.5} r={5 + 12 * b} fill="none" stroke={accent} strokeWidth={2.4 * (1 - b)} opacity={1 - b} />
              {Array.from({ length: 8 }, (_, i) => {
                const a = (i / 8) * Math.PI * 2 + (rnd(seed + i) - 0.5) * 0.5;
                const d = 9 + 13 * b;
                return <circle key={i} cx={12 + Math.cos(a) * d} cy={12.5 + Math.sin(a) * d} r={Math.max(0, 1.9 * (1 - b))}
                  fill={i % 2 ? "#fff" : accent} />;
              })}
            </g>
          ) : null}
          <g transform={`translate(12 12.5) scale(${squash}) translate(-12 -12.5)`}>
            <path d={I.heart} fill={on ? accent : "none"} stroke={on ? accent : MUTED} strokeWidth={1.8} strokeLinejoin="round" />
          </g>
        </svg>
        {num ? (
          <Rise at={tap - 2} out={end}>
            <span style={{ display: "inline-flex" }}>
              <Odometer value={num.n} at={tap} frames={Math.round(fps * 1.1)} size={28 * k} color={accent} font={INTER}
                suffix={num.s} suffixScale={1} />
            </span>
          </Rise>
        ) : null}
      </div>
    );
  };

const Action: React.FC<{ d: string; n: number | null; at: number; end: number }> = ({ d, n, at, end }) => {
  const frame = useCurrentFrame();
  const k = useK();
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12 * k }}>
      <Icon d={d} size={34 * k} color={MUTED} style={{ transform: `scale(${ramp(frame, at, 14, backOut)})` }} />
      {n !== null ? (
        <Rise at={at + 3} out={end}>
          <span style={{ fontFamily: INTER, fontWeight: 700, fontSize: 26 * k, color: MUTED }}>{compact(Math.max(0, n))}</span>
        </Rise>
      ) : null}
    </div>
  );
};

/**
 * A generic post: overlay.label the account name, overlay.subtitle "@handle ·
 * time" (or just the time), overlay.text the post, overlay.highlight the
 * phrase in the accent, overlay.value the likes (items "replies" / "reposts"
 * add those counts), overlay.media[0] an attached photo.
 */
const SocialPost: Look = ({ overlay, accent: acc }) => {
  const { frame, fps, dur, end, out, k, T } = useT();
  const hold = useHold();
  const accent = pick(acc);
  const text = unquote(clean(overlay.text, 280));
  if (!text) return null;
  const name = clean(overlay.label, 30) || "Public post";
  const sub = clean(overlay.subtitle, 44);
  const first = sub.split(" ")[0] || "";
  const handle = first.startsWith("@") ? first.slice(0, 22) : `@${slug(name, 22).replace(/-/g, "") || "public"}`;
  const when = first.startsWith("@") ? sub.slice(first.length).replace(/^[\s·•|,-]+/, "") : sub;
  const pic = firstStill(overlay);
  const stat = (re: RegExp): number | null => {
    const it = itemsOf(overlay.items).find((i) => typeof i.label === "string" && re.test(i.label));
    return it ? finite(it.value) : null;
  };
  const likes = finite(overlay.value) ?? stat(/like|heart|love/i);
  const replies = stat(/repl|comment/i);
  const reposts = stat(/repost|share|retweet|forward/i);
  const W = 1000 * k, PAD = 46 * k, FS = 38 * k;
  const ls = wrap(text, pic ? 42 : 40, pic ? 3 : 5);
  const offs = offsets(ls);
  const range = findRange(ls.join(" "), clean(overlay.highlight));
  const seed = seedOf(text);
  const p = ramp(frame, 0, T(0.7));
  const lineAt = (i: number) => T(0.42) + i * 4;
  const imgAt = lineAt(ls.length);
  const img = ramp(frame, imgAt, T(0.7), inOut);
  const rowAt = imgAt + (pic ? T(0.3) : 0);
  const tap = Math.max(rowAt + 14, T(1.45));
  const float = Math.sin((frame / fps) * 1.3) * 5 * k;
  const sheen = interpolate(frame, [T(0.3), T(1.3)], [-0.3, 1.3], clamp);
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", perspective: 1800 * k }}>
        <div style={{ position: "relative", width: W, padding: PAD, boxSizing: "border-box", borderRadius: 30 * k,
          overflow: "hidden", background: "linear-gradient(180deg, #1b1c22 0%, #111216 100%)",
          border: `${1.5 * k}px solid rgba(255,255,255,.1)`, boxShadow: `0 ${40 * k}px ${110 * k}px rgba(0,0,0,.6)`,
          opacity: Math.min(1, p * 1.8) * (1 - out),
          transform: `translateY(${(1 - p) * 120 * k + float + out * 70 * k}px) rotateX(${(1 - p) * 22 - out * 10}deg) ` +
            `scale(${(0.93 + 0.07 * p) * hold})` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 24 * k }}>
            <Avatar name={name} size={88 * k} accent={accent} ring={ramp(frame, T(0.12), T(0.6), inOut)}
              pop={ramp(frame, T(0.15), 16, backOut)} />
            <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 6 * k }}>
              <Rise at={T(0.24)} out={end}>
                <div style={{ display: "flex", alignItems: "center", gap: 12 * k }}>
                  <span style={{ fontFamily: INTER, fontWeight: 800, fontSize: 34 * k, color: "#fff", whiteSpace: "nowrap" }}>{name}</span>
                  <Badge size={30 * k} accent={accent} at={T(0.45)} />
                </div>
              </Rise>
              <Rise at={T(0.3)} out={end}>
                <span style={{ fontFamily: INTER, fontWeight: 400, fontSize: 26 * k, color: "rgba(255,255,255,.5)", whiteSpace: "nowrap" }}>
                  {handle}{when ? ` · ${when}` : ""}</span>
              </Rise>
            </div>
            <div style={{ display: "flex", gap: 7 * k, alignSelf: "flex-start", marginTop: 14 * k,
              opacity: ramp(frame, T(0.35), 10) * (1 - ramp(frame, end, 8)) }}>
              {[0, 1, 2].map((i) => <span key={i} style={{ width: 7 * k, height: 7 * k, borderRadius: "50%", background: MUTED }} />)}
            </div>
          </div>
          <div style={{ marginTop: 26 * k, display: "flex", flexDirection: "column" }}>
            {ls.map((ln, i) => (
              <Rise key={i} at={lineAt(i)} out={end + Math.min(i, 4)}>
                <span style={{ fontFamily: INTER, fontWeight: 400, fontSize: FS, lineHeight: 1.32, color: "rgba(255,255,255,.94)",
                  whiteSpace: "pre" }}>
                  {runs(ln, offs[i], range).map((r, j) => (
                    <span key={j} style={{ color: r.kind === "hot" ? accent : r.kind === "tag" ? CYAN : undefined,
                      fontWeight: r.kind === "hot" ? 800 : r.kind === "tag" ? 700 : undefined }}>{r.t}</span>
                  ))}
                </span>
              </Rise>
            ))}
          </div>
          {pic ? (
            <div style={{ marginTop: 24 * k, height: 330 * k, borderRadius: 22 * k, overflow: "hidden", background: "#23252c",
              clipPath: `inset(0 0 ${(1 - img) * 100}% 0 round ${22 * k}px)` }}>
              <Img src={pic} style={{ width: "100%", height: "100%", objectFit: "cover",
                transform: `scale(${1.14 - 0.08 * img + 0.05 * (frame / dur)})` }} />
            </div>
          ) : null}
          <div style={{ marginTop: 26 * k, height: 1.5 * k, background: "rgba(255,255,255,.1)", transformOrigin: "left",
            transform: `scaleX(${ramp(frame, rowAt - 6, T(0.6), inOut)})` }} />
          <div style={{ marginTop: 22 * k, display: "flex", alignItems: "center", justifyContent: "space-between", paddingRight: 30 * k }}>
            <Action d={I.reply} n={replies} at={rowAt} end={end} />
            <Action d={I.repost} n={reposts} at={rowAt + 3} end={end} />
            <HeartButton n={likes} at={rowAt + 6} tap={tap} accent={accent} end={end} seed={seed} />
            <Action d={I.share} n={null} at={rowAt + 9} end={end} />
          </div>
          <div style={{ position: "absolute", inset: 0, pointerEvents: "none",
            background: `linear-gradient(105deg, transparent ${sheen * 100 - 16}%, rgba(255,255,255,.07) ${sheen * 100}%, ` +
              `transparent ${sheen * 100 + 16}%)` }} />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
// ------------------------------------------------------------------ 2. comment thread
type Comment = { user: string; likes: number | null; ls: string[]; h: number; y: number };
const AGO = ["3h", "2h", "1h", "38m", "12m"];

/**
 * A comments section: overlay.text a heading above it, overlay.value the
 * comment count, items the comments (label the commenter, text the words,
 * value its likes). The first is the top comment, the rest its replies,
 * each joined to it by a thread line that draws down before the reply lands.
 */
const CommentThread: Look = ({ overlay, accent: acc }) => {
  const { frame, dur, end, out, k, width, height, T } = useT();
  const hold = useHold();
  const accent = pick(acc);
  const raw = itemsOf(overlay.items).filter((i) => clean(i.text) || clean(i.label)).slice(0, 4);
  if (!raw.length) return null;
  const PW = 1160 * k, PADX = 40 * k, AV = 60 * k, IND = 86 * k, FS = 29 * k, LH = 40 * k, HEAD = 84 * k;
  const heading = clean(overlay.text, 56);
  const headingH = heading ? 104 * k : 0;
  const LIMIT = 860 * k - headingH;
  const list: Comment[] = [];
  let y = HEAD;
  for (let i = 0; i < raw.length; i++) {
    const it = raw[i];
    const hasBody = !!clean(it.text);
    const user = (hasBody ? clean(it.label, 26) : "") || "Anonymous";
    const body = unquote(hasBody ? clean(it.text, 220) : clean(it.label, 220));
    if (!body) continue;
    const indent = list.length > 0 ? IND : 0;
    const chars = Math.max(24, Math.floor((PW - 2 * PADX - AV - 20 * k - indent) / (FS * 0.56)));
    const ls = wrap(body, chars, 3);
    const h = 26 * k + 34 * k + 8 * k + ls.length * LH + 10 * k + 32 * k + 22 * k;
    if (list.length && y + h > LIMIT) break;
    list.push({ user, likes: finite(it.value), ls, h, y });
    y += h;
  }
  const n = list.length;
  if (!n) return null;
  const fullH = y + 8 * k;
  const t0 = T(0.55);
  const step = Math.max(12, Math.min(T(1.0), Math.floor((dur - 50 - t0) / Math.max(1, n))));
  const at = (i: number) => t0 + i * step;
  const grow = list.map((_, i) => ramp(frame, at(i) - 2, T(0.5), inOut));
  const panelH = HEAD + list.reduce((s, c, i) => s + c.h * grow[i], 0) + 8 * k * grow[n - 1];
  const top = (height - fullH - headingH) / 2 + headingH;
  const left = (width - PW) / 2;
  const pIn = ramp(frame, T(0.1), T(0.6));
  const count = finite(overlay.value);
  const x0 = PADX + AV / 2;
  const y0 = list[0].y + 26 * k + AV + 6 * k;
  const r = 20 * k;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ transform: `scale(${hold})` }}>
        {heading ? (
          <div style={{ position: "absolute", left, top: top - headingH, width: PW, opacity: 1 - out }}>
            <Heading text={heading} accent={accent} size={54} />
          </div>
        ) : null}
        <div style={{ position: "absolute", left, top, width: PW, height: panelH, borderRadius: 26 * k, overflow: "hidden",
          background: "linear-gradient(180deg, rgba(25,26,31,.95) 0%, rgba(16,17,21,.95) 100%)",
          border: `${1.5 * k}px solid rgba(255,255,255,.09)`, boxShadow: `0 ${34 * k}px ${90 * k}px rgba(0,0,0,.55)`,
          opacity: Math.min(1, pIn * 1.6) * (1 - out), transform: `translateY(${(1 - pIn) * 50 * k + out * 50 * k}px)` }}>
          <div style={{ position: "absolute", left: PADX, right: PADX, top: 0, height: HEAD, display: "flex", alignItems: "center",
            justifyContent: "space-between", borderBottom: `${1.5 * k}px solid rgba(255,255,255,.08)` }}>
            <div style={{ display: "flex", alignItems: "center", gap: 14 * k }}>
              <Icon d={I.reply} size={30 * k} color={accent} width={2} draw={ramp(frame, T(0.15), T(0.5), inOut)} />
              {count !== null ? (
                <Rise at={T(0.2)} out={end}>
                  <span style={{ display: "inline-flex" }}>
                    <Odometer value={Math.max(0, Math.round(count))} at={T(0.2)} frames={T(1.1)} size={32 * k} color="#fff" font={INTER} />
                  </span>
                </Rise>
              ) : null}
              <Rise at={T(0.26)} out={end}>
                <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 28 * k, letterSpacing: "0.16em",
                  color: "rgba(255,255,255,.75)" }}>COMMENTS</span>
              </Rise>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 * k }}>
              <Rise at={T(0.32)} out={end}>
                <span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 24 * k, letterSpacing: "0.14em",
                  color: "rgba(255,255,255,.45)" }}>TOP</span>
              </Rise>
              <Icon d={I.chevron} size={24 * k} color="rgba(255,255,255,.45)" width={2.2}
                draw={ramp(frame, T(0.36), 10) * (1 - ramp(frame, end, 8))} />
            </div>
          </div>
          <svg width={PW} height={fullH} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
            {list.slice(1).map((c, j) => {
              const i = j + 1;
              const yc = c.y + 26 * k + AV / 2;
              const x1 = PADX + IND - 10 * k;
              const d = `M${x0} ${y0} V${yc - r} Q${x0} ${yc} ${x0 + r} ${yc} H${x1}`;
              const p = ramp(frame, at(i) - T(0.32), T(0.32), inOut);
              return <path key={i} d={d} fill="none" stroke="rgba(255,255,255,.22)" strokeWidth={3 * k} strokeLinecap="round"
                pathLength={1} strokeDasharray={1} strokeDashoffset={1 - p} />;
            })}
          </svg>
          {list.map((c, i) => {
            const a = at(i);
            const indent = i > 0 ? IND : 0;
            const flash = interpolate(frame, [a, a + 6, a + Math.max(12, T(1.1))], [0, 1, 0], clamp);
            return (
              <div key={i} style={{ position: "absolute", left: 0, right: 0, top: c.y, height: c.h }}>
                <div style={{ position: "absolute", left: 12 * k + indent, right: 12 * k, top: 6 * k, bottom: 6 * k,
                  borderRadius: 18 * k, background: rgba(accent, 0.13 * flash),
                  boxShadow: flash > 0.01 ? `inset ${4 * k}px 0 0 ${rgba(accent, 0.9 * flash)}` : "none" }} />
                <div style={{ position: "absolute", left: PADX + indent, right: PADX, top: 26 * k, display: "flex", gap: 20 * k }}>
                  <Avatar name={c.user} size={AV} accent={accent} tone={i === 0 ? "accent" : "gray"}
                    pop={ramp(frame, a, 16, backOut) * (1 - ramp(frame, end + 2, 8, easeIn))} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <Rise at={a + 2} out={end}>
                      <div style={{ display: "flex", alignItems: "baseline", gap: 12 * k, height: 34 * k }}>
                        <span style={{ fontFamily: INTER, fontWeight: 700, fontSize: 27 * k, color: "#fff", whiteSpace: "nowrap" }}>
                          {c.user}</span>
                        <span style={{ fontFamily: INTER, fontWeight: 400, fontSize: 24 * k, color: "rgba(255,255,255,.42)" }}>
                          {AGO[i] || "now"}</span>
                      </div>
                    </Rise>
                    <div style={{ marginTop: 8 * k }}>
                      {c.ls.map((ln, j) => (
                        <Rise key={j} at={a + 5 + j * 3} out={end + j}>
                          <span style={{ display: "block", fontFamily: INTER, fontWeight: 400, fontSize: FS, lineHeight: `${LH}px`,
                            color: "rgba(255,255,255,.9)", whiteSpace: "pre" }}>{ln}</span>
                        </Rise>
                      ))}
                    </div>
                    <div style={{ marginTop: 10 * k, height: 32 * k, display: "flex", alignItems: "center", gap: 28 * k }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 * k }}>
                        <Icon d={I.heart} size={24 * k} color={i === 0 ? accent : MUTED} fill={i === 0 ? accent : "none"}
                          style={{ transform: `scale(${ramp(frame, a + 9, 12, backOut) * (1 - ramp(frame, end + 2, 8, easeIn))})` }} />
                        {c.likes !== null ? (
                          <Rise at={a + 10} out={end}>
                            <span style={{ fontFamily: INTER, fontWeight: 700, fontSize: 24 * k, color: MUTED }}>
                              {compact(Math.max(0, c.likes))}</span>
                          </Rise>
                        ) : null}
                      </div>
                      <Rise at={a + 12} out={end}>
                        <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.14em",
                          color: "rgba(255,255,255,.5)" }}>REPLY</span>
                      </Rise>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
// ------------------------------------------------------------------ 3. search bar
/**
 * A search: overlay.text the query (typed in mono, with a human rhythm),
 * items the suggestions (labels), overlay.highlight which suggestion gets
 * picked (else the first), overlay.subtitle a kicker above the bar,
 * overlay.value the results count rolled in after "enter".
 */
const SearchBar: Look = ({ overlay, accent: acc }) => {
  const { frame, fps, dur, end, out, k, width, height, sp, T } = useT();
  const hold = useHold();
  const accent = pick(acc);
  const query = unquote(clean(overlay.text, 64));
  if (!query) return null;
  const sugg = itemsOf(overlay.items).map((i) => unquote(clean(i.label || i.text, 64))).filter(Boolean).slice(0, 5);
  const results = finite(overlay.value);
  const kicker = clean(overlay.subtitle, 48);
  const W = 1180 * k, BH = 104 * k, RH = 74 * k, R = 30 * k;
  const seed = seedOf(query);
  const chars = Array.from(query);
  // Typing: each key 0.8-1.9 frames plus a beat after a space, never more than ~1.7 s in all.
  const typeAt = T(0.55);
  const gaps = chars.map((ch, i) => 0.8 + rnd(seed + i) * 1.1 + (ch === " " ? 1.0 : 0));
  const total = gaps.reduce((s, g) => s + g, 0);
  const pace = Math.min(sp, (fps * 1.7 * sp) / Math.max(1, total));
  const times: number[] = [];
  let tt = typeAt;
  for (const g of gaps) {
    times.push(tt);
    tt += g * pace;
  }
  const typedEnd = Math.round(tt);
  let shown = 0;
  while (shown < times.length && frame >= times[shown]) shown++;
  const typed = chars.slice(0, shown).join("");
  // Suggestions, the pick, enter.
  const dropAt = typeAt + Math.round((typedEnd - typeAt) * 0.5);
  const hl = unquote(clean(overlay.highlight)).toLowerCase();
  const found = hl ? sugg.findIndex((s) => s.toLowerCase().includes(hl) || hl.includes(s.toLowerCase())) : 0;
  const target = Math.max(0, Math.min(sugg.length - 1, found));
  const selAt = typedEnd + T(0.35);
  const stepF = Math.max(4, T(0.24));
  const selPos = Array.from({ length: sugg.length ? target : 0 }, (_, s) => ramp(frame, selAt + (s + 1) * stepF, stepF - 1, inOut))
    .reduce((a, b) => a + b, 0);
  const selOn = sugg.length ? ramp(frame, selAt, 6) : 0;
  const enterAt = sugg.length ? selAt + (target + 1) * stepF + T(0.25) : typedEnd + T(0.3);
  const resAt = enterAt + 6;
  const close = results !== null ? ramp(frame, enterAt, 10, inOut) : 0;
  const openP = sugg.length ? ramp(frame, dropAt, T(0.45), inOut) * (1 - close) * (1 - ramp(frame, dur - 22, 8, inOut)) : 0;
  const barText = sugg.length && frame >= selAt ? sugg[Math.max(0, Math.min(sugg.length - 1, Math.round(selPos)))] : typed;
  const longest = Math.max(chars.length, sugg.length ? Array.from(sugg[target]).length : 0);
  const TA = W - 2 * 34 * k - 40 * k - 2 * 22 * k - 66 * k;
  const FS = Math.max(24 * k, Math.min(38 * k, TA / Math.max(1, longest * 0.61)));
  const caret = frame >= typeAt && frame < enterAt && (shown < chars.length || (frame - typedEnd) % 16 < 9);
  // Geometry.
  const barP = ramp(frame, 0, T(0.6));
  const wf = (0.38 + 0.62 * barP) * (1 - 0.45 * out);
  const barTop = sugg.length ? height * 0.5 - BH - 80 * k : (height - BH) / 2 - 30 * k;
  const left0 = (width - W) / 2;
  const listH = sugg.length * RH + 24 * k;
  const joined = Math.min(1, openP * 3);
  const press = interpolate(frame, [enterAt, enterAt + 3, enterAt + 10], [1, 0.84, 1], clamp);
  const ripple = interpolate(frame, [enterAt, enterAt + 16], [0, 1], clamp);
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ transform: `scale(${hold})` }}>
        {kicker ? (
          <div style={{ position: "absolute", left: left0 + 14 * k, top: barTop - 66 * k }}>
            <LetterLine text={kicker.toUpperCase()} at={T(0.1)} step={0.6} style={{ fontFamily: LABEL, fontWeight: 800,
              fontSize: 28 * k, letterSpacing: "0.3em", color: accent }} />
          </div>
        ) : null}
        {sugg.length ? (
          <div style={{ position: "absolute", left: left0, top: barTop + BH - 1 * k, width: W, height: listH * openP,
            overflow: "hidden", background: "#fff", borderRadius: `0 0 ${R}px ${R}px`,
            boxShadow: openP > 0.01 ? `0 ${40 * k}px ${80 * k}px rgba(0,0,0,.42)` : "none" }}>
            <div style={{ position: "absolute", left: 36 * k, right: 36 * k, top: 0, height: 1.5 * k, background: "rgba(0,0,0,.1)" }} />
            <div style={{ position: "absolute", left: 0, right: 0, top: 12 * k + selPos * RH, height: RH, opacity: selOn,
              background: rgba(accent, 0.16), boxShadow: `inset ${5 * k}px 0 0 ${accent}` }} />
            {sugg.map((s, i) => {
              const pre = typed && s.toLowerCase().startsWith(typed.toLowerCase()) ? s.slice(0, typed.length) : "";
              const rest = s.slice(pre.length);
              const a = dropAt + 3 + i * 3;
              return (
                <div key={i} style={{ position: "absolute", left: 0, right: 0, top: 12 * k + i * RH, height: RH, display: "flex",
                  alignItems: "center", gap: 24 * k, padding: `0 ${40 * k}px`, boxSizing: "border-box" }}>
                  <Icon d={I.search} size={28 * k} color="#9aa0a8" width={2.2} draw={ramp(frame, a, 10, inOut)} />
                  <Rise at={a} out={end} style={{ minWidth: 0 }}>
                    <span style={{ fontFamily: INTER, fontSize: 30 * k, whiteSpace: "pre", color: PAGE_INK }}>
                      <span style={{ fontWeight: 400, color: "#6b7078" }}>{pre}</span>
                      <span style={{ fontWeight: 700 }}>{rest}</span>
                    </span>
                  </Rise>
                </div>
              );
            })}
          </div>
        ) : null}
        <div style={{ position: "absolute", left: (width - W * wf) / 2, top: barTop, width: W * wf, height: BH,
          background: "#fff", overflow: "hidden", display: "flex", alignItems: "center", gap: 22 * k, padding: `0 ${22 * k}px 0 ${34 * k}px`,
          boxSizing: "border-box", borderRadius: `${R}px ${R}px ${R * (1 - joined)}px ${R * (1 - joined)}px`,
          boxShadow: `0 ${30 * k}px ${80 * k}px rgba(0,0,0,.45)`, opacity: Math.min(1, barP * 2) * (1 - out) }}>
          <Icon d={I.search} size={40 * k} color="#5f646c" width={2.4} draw={ramp(frame, T(0.2), T(0.5), inOut)} />
          <div style={{ position: "relative", flex: 1, minWidth: 0, height: BH, display: "flex", alignItems: "center", overflow: "hidden" }}>
            {!shown ? (
              <Rise at={T(0.3)} out={typeAt}>
                <span style={{ fontFamily: INTER, fontWeight: 400, fontSize: 34 * k, color: "#a3a8b0" }}>Search</span>
              </Rise>
            ) : null}
            <Rise at={typeAt - 1} frames={1} out={end}>
              <span style={{ display: "inline-flex", alignItems: "center", fontFamily: MONO, fontWeight: 500, fontSize: FS,
                color: PAGE_INK, whiteSpace: "pre" }}>
                {barText}
                <span style={{ display: "inline-block", width: 3 * k, height: FS * 1.15, marginLeft: 3 * k, background: accent,
                  opacity: caret ? 1 : 0 }} />
              </span>
            </Rise>
          </div>
          <div style={{ position: "relative", width: 66 * k, height: 66 * k, flexShrink: 0 }}>
            {ripple > 0 && ripple < 1 ? (
              <div style={{ position: "absolute", inset: 0, borderRadius: "50%", border: `${3 * k}px solid ${accent}`,
                transform: `scale(${1 + ripple * 0.9})`, opacity: 1 - ripple }} />
            ) : null}
            <div style={{ width: 66 * k, height: 66 * k, borderRadius: "50%", background: accent, display: "flex",
              alignItems: "center", justifyContent: "center", transform: `scale(${ramp(frame, T(0.35), 14, backOut) * press})` }}>
              <Icon d={I.search} size={32 * k} color={inkOn(accent)} width={2.6} />
            </div>
          </div>
        </div>
        {results !== null ? (
          <div style={{ position: "absolute", left: left0 + 34 * k, top: barTop + BH + 40 * k, display: "flex", alignItems: "center",
            gap: 14 * k }}>
            <Rise at={resAt} out={end}>
              <span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 26 * k, letterSpacing: "0.12em",
                color: "rgba(255,255,255,.72)" }}>ABOUT</span>
            </Rise>
            <Rise at={resAt + 2} out={end}>
              <span style={{ display: "inline-flex" }}>
                <Odometer value={Math.max(0, Math.round(results))} at={resAt + 2} frames={T(1.1)} size={36 * k} color="#fff" font={MONO} />
              </span>
            </Rise>
            <Rise at={resAt + 4} out={end}>
              <span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 26 * k, letterSpacing: "0.12em",
                color: "rgba(255,255,255,.72)" }}>RESULTS</span>
            </Rise>
          </div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
// ------------------------------------------------------------------ 4. notification stack
type Note = { app: string; msg: string[]; danger: boolean; glyph: string; h: number };
const DANGER = /emergenc|warning|alert|evacuat|danger|boil|shelter|flood|tornado|hurricane|wildfire/i;
const WATERY = /water|drought|reservoir|lake|river|rain|\bdam\b|aquifer|\bwell\b|\btap\b|pipe|\bmains?\b/i;
const HOT = /heat|°|temperature|\bhot\b|degrees/i;
const AGES = ["now", "1m", "4m", "9m"];

/**
 * Phone notifications riding on the footage, right side: items (label the
 * app or sender, text the message); a single overlay.label / text works too.
 * A header counts them (overlay.value overrides the count). Each drops in
 * with a buzz and pushes the older ones down; past three the oldest tucks
 * under the stack. Emergency wording gets the red alert icon.
 */
const NotificationStack: Look = ({ overlay, accent: acc }) => {
  const { frame, fps, dur, end, out, k, T } = useT();
  const accent = pick(acc);
  let src = itemsOf(overlay.items).filter((i) => clean(i.text) || clean(i.label))
    .map((i) => ({ app: clean(i.text) ? clean(i.label, 26) : "", msg: unquote(clean(i.text) ? clean(i.text, 110) : clean(i.label, 110)) }));
  if (!src.length && clean(overlay.text)) src = [{ app: clean(overlay.label, 26), msg: unquote(clean(overlay.text, 110)) }];
  src = src.filter((s) => s.msg).slice(0, 4);
  if (!src.length) return null;
  const CW = 860 * k, PAD = 28 * k, IC = 84 * k, LH = 50 * k, GAP = 16 * k, PEEK = 18 * k, HEADER = 88 * k;
  const notes: Note[] = src.map((s) => {
    const app = s.app || clean(overlay.label, 26) || "Notification";
    const all = `${app} ${s.msg}`;
    const danger = DANGER.test(all);
    const glyph = danger ? I.alert : WATERY.test(all) ? I.drop : HOT.test(all) ? I.heat : I.bell;
    // Measured, not counted: caps are wider than lower case. A shouted (all caps) line reads as a sentence.
    const said = s.msg === s.msg.toUpperCase() && /[A-Z]{4}/.test(s.msg)
      ? s.msg.charAt(0) + s.msg.slice(1).toLowerCase() : s.msg;
    const msg = kfit(said, KF.inter, 40 * k, 40 * k, CW - PAD * 2 - IC - 22 * k, 3).lines;
    return { app, msg, danger, glyph, h: PAD + 36 * k + 10 * k + msg.length * LH + PAD };
  });
  const n = notes.length;
  const t0 = T(0.35);
  const step = Math.max(10, Math.min(T(0.9), Math.floor((dur - 46 - t0) / Math.max(1, n))));
  const at = (j: number) => t0 + j * step;
  const push = notes.map((_, j) => ramp(frame, at(j), T(0.45), inOut));
  // Newest (highest j) on top; a card with more than two above it tucks under the one above.
  const ys = Array.from({ length: n }, () => 0);
  const depth = Array.from({ length: n }, () => 0);
  for (let j = n - 2; j >= 0; j--) {
    depth[j] = depth[j + 1] + push[j + 1];
    const c = Math.max(0, Math.min(1, depth[j] - 2));
    ys[j] = ys[j + 1] + ((notes[j + 1].h + GAP) * (1 - c) + PEEK * c) * push[j + 1];
  }
  const shownCount = notes.reduce((s, _, j) => s + (frame >= at(j) ? 1 : 0), 0);
  const given = finite(overlay.value);
  const count = given !== null && given >= 1 ? Math.round(given) : shownCount;
  const drift = Math.sin((frame / fps) * 1.1) * 3 * k;
  const hIn = ramp(frame, 0, T(0.5));
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: ramp(frame, 0, 12) * (1 - out),
        background: "radial-gradient(ellipse 50% 64% at 84% 36%, rgba(0,0,0,.5) 0%, rgba(0,0,0,.2) 50%, rgba(0,0,0,0) 100%)" }} />
      <div style={{ position: "absolute", right: 96 * k, top: 96 * k, width: CW, height: 820 * k, transform: `translateY(${drift}px)` }}>
        <div style={{ position: "absolute", left: 8 * k, right: 8 * k, top: 0, height: 60 * k, display: "flex", alignItems: "center",
          gap: 14 * k, opacity: 1 - out }}>
          <Icon d={I.bell} size={42 * k} color="#fff" width={2.2} draw={ramp(frame, 2, T(0.5), inOut)} />
          <Rise at={4} out={end}>
            <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 38 * k, letterSpacing: "0.16em", color: "#fff",
              textShadow: "0 3px 12px rgba(0,0,0,.7)" }}>
              NOTIFICATIONS</span>
          </Rise>
          <div style={{ minWidth: 56 * k, height: 52 * k, borderRadius: 26 * k, background: accent, display: "flex",
            alignItems: "center", justifyContent: "center", padding: `0 ${10 * k}px`, boxSizing: "border-box",
            transform: `scale(${ramp(frame, T(0.3), 14, backOut) * (1 - ramp(frame, end + 2, 8, easeIn))})` }}>
            <span style={{ fontFamily: INTER, fontWeight: 800, fontSize: 32 * k, color: inkOn(accent), lineHeight: 1 }}>
              {Math.max(1, count)}</span>
          </div>
          <div style={{ flex: 1, height: 1.5 * k, background: "rgba(255,255,255,.35)", transformOrigin: "left",
            transform: `scaleX(${hIn * (1 - out)})` }} />
        </div>
        {notes.map((nt, j) => {
          if (frame < at(j)) return null;
          const a = ramp(frame, at(j), T(0.5), backOut);
          const c = Math.max(0, Math.min(1, depth[j] - 2));
          const e = ramp(frame, dur - 12 + (n - 1 - j), 10, easeIn);
          const bz = frame - at(j) - 5;
          const dx = bz > 0 && bz < 14 ? Math.sin(bz * 2.1) * 6 * k * (1 - bz / 14) : 0;
          const icBg = nt.danger ? `linear-gradient(145deg, #ff6a61 0%, ${RED} 100%)`
            : `linear-gradient(145deg, ${tint(accent, 0.2)} 0%, ${shade(accent, 0.72)} 100%)`;
          const age = AGES[n - 1 - j] || "now";
          return (
            <div key={j} style={{ position: "absolute", right: 0, top: HEADER + ys[j], width: CW, height: nt.h, borderRadius: 32 * k,
              zIndex: j + 1, background: "linear-gradient(180deg, rgba(47,48,55,.95) 0%, rgba(28,29,34,.95) 100%)",
              border: `${1.2 * k}px solid rgba(255,255,255,.14)`, boxShadow: `0 ${18 * k}px ${44 * k}px rgba(0,0,0,.45)`,
              opacity: ramp(frame, at(j), 6) * (1 - 0.35 * c) * (1 - e), transformOrigin: "50% 0%",
              transform: `translate(${dx + e * 140 * k}px, ${(1 - a) * -60 * k}px) scale(${(1 - 0.06 * c) * (0.9 + 0.1 * a)})` }}>
              <div style={{ position: "absolute", left: PAD, top: PAD, width: IC, height: IC, borderRadius: 22 * k, background: icBg,
                display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "inset 0 1px 0 rgba(255,255,255,.25)",
                transform: `scale(${ramp(frame, at(j) + 2, 14, backOut)})` }}>
                <Icon d={nt.glyph} size={50 * k} color={nt.danger ? "#fff" : inkOn(accent)} width={2.2}
                  draw={ramp(frame, at(j) + 4, 12, inOut)} />
              </div>
              <div style={{ position: "absolute", left: PAD + IC + 22 * k, right: PAD, top: PAD - 2 * k, opacity: 1 - c }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", height: 36 * k }}>
                  <Rise at={at(j) + 5} out={end} style={{ minWidth: 0 }}>
                    <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 32 * k, letterSpacing: "0.1em",
                      color: "rgba(255,255,255,.72)", whiteSpace: "nowrap" }}>{nt.app.toUpperCase()}</span>
                  </Rise>
                  <Rise at={at(j) + 6} out={end}>
                    <span style={{ fontFamily: INTER, fontWeight: 500, fontSize: 28 * k, color: "rgba(255,255,255,.5)" }}>{age}</span>
                  </Rise>
                </div>
                <div style={{ marginTop: 10 * k }}>
                  {nt.msg.map((ln, l) => (
                    <Rise key={l} at={at(j) + 8 + l * 3} out={end}>
                      <span style={{ display: "block", fontFamily: INTER, fontWeight: 700, fontSize: 40 * k, lineHeight: `${LH}px`, letterSpacing: "-0.01em",
                        color: "#fff", whiteSpace: "pre" }}>{ln}</span>
                    </Rise>
                  ))}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
// ------------------------------------------------------------------ 5. chat bubbles
type Msg = { who: string; side: "l" | "r"; ls: string[]; chars: number };

/**
 * A conversation: items (label the sender, text the message), overlay.label
 * the chat's title. The first sender sits left in grey, the second right in
 * the accent. Typing dots bounce in the sender's bubble, then the bubble
 * grows into the message; the thread scrolls to keep the newest in view and
 * the last reply on the right gets a read tick.
 */
const ChatBubbles: Look = ({ overlay, accent: acc }) => {
  const { frame, dur, end, out, k, width, height, sp, T } = useT();
  const hold = useHold();
  const accent = pick(acc);
  const src = itemsOf(overlay.items).filter((i) => clean(i.text) || clean(i.label)).slice(0, 6);
  const senders: string[] = [];
  const msgs: Msg[] = src.map((it, i) => {
    const hasText = !!clean(it.text);
    const who = hasText ? clean(it.label, 24) : "";
    const key = who.toLowerCase();
    if (who && !senders.includes(key)) senders.push(key);
    const side: "l" | "r" = who ? (senders.indexOf(key) % 2 === 0 ? "l" : "r") : i % 2 === 0 ? "l" : "r";
    const body = unquote(hasText ? clean(it.text, 150) : clean(it.label, 150));
    return { who, side, ls: body ? wrap(body, 32, 4) : [], chars: body.length };
  }).filter((m) => m.ls.length > 0);
  if (!msgs.length) return null;
  const PW = 1120 * k, FS = 31 * k, LH = 41 * k, PX = 28 * k, PY = 18 * k, TYPH = 64 * k, TYPW = 116 * k;
  const HEADH = 104 * k, VH = 620 * k, TOPPAD = 24 * k, RECH = 38 * k;
  const panelH = HEADH + VH + 40 * k;
  const left = (width - PW) / 2;
  const PT = (height - panelH) / 2;
  const leftWho = msgs.find((m) => m.side === "l" && m.who);
  const title = clean(overlay.label, 30) || (leftWho ? leftWho.who : "") || "Messages";
  // Schedule: dots for a beat that grows with the message, then the message; squeezed to fit.
  let t = T(0.5);
  const raw = msgs.map((m) => {
    const typeF = Math.round(Math.max(10, Math.min(22, 8 + m.chars * 0.2)) * sp);
    const a = t;
    const b = t + typeF;
    t = b + Math.round(12 * sp);
    return { a, b };
  });
  const lastB = raw[raw.length - 1].b;
  const f = lastB > dur - 36 ? Math.max(0.3, (dur - 36) / lastB) : 1;
  const S = raw.map((s) => ({ a: Math.round(s.a * f), b: Math.max(Math.round(s.a * f) + 6, Math.round(s.b * f)) }));
  // Layout (content coordinates).
  let y = 0;
  const lay = msgs.map((m, i) => {
    const prev = i > 0 ? msgs[i - 1] : null;
    const newSender = !prev || prev.side !== m.side || prev.who !== m.who;
    if (i > 0) y += newSender ? 24 * k : 10 * k;
    const nameH = newSender && m.who ? 36 * k : 0;
    const top = y;
    y += nameH + Math.max(TYPH, 2 * PY + m.ls.length * LH);
    return { top, nameH, bottom: y };
  });
  const lastR = msgs.map((m) => m.side).lastIndexOf("r");
  // Scroll so the newest element stays in view.
  const events: { t: number; need: number }[] = [];
  msgs.forEach((_, i) => {
    events.push({ t: S[i].a, need: lay[i].top + lay[i].nameH + TYPH });
    events.push({ t: S[i].b, need: lay[i].bottom });
  });
  if (lastR >= 0) events.push({ t: S[lastR].b + 10, need: lay[lastR].bottom + RECH });
  events.sort((p, q) => p.t - q.t);
  let prevS = 0;
  let scroll = 0;
  for (const ev of events) {
    const s = Math.max(prevS, ev.need + TOPPAD + 20 * k - VH);
    scroll += (s - prevS) * ramp(frame, ev.t, 12, inOut);
    prevS = s;
  }
  const typingLeft = msgs.some((m, i) => m.side === "l" && frame >= S[i].a && frame < S[i].b);
  const pIn = ramp(frame, 0, T(0.7));
  const Rr = 30 * k, tail = 8 * k;
  const mask = `linear-gradient(180deg, transparent 0px, #000 ${TOPPAD}px, #000 100%)`;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ transform: `scale(${hold})` }}>
        <div style={{ position: "absolute", left, top: PT, width: PW, height: panelH, borderRadius: 34 * k, overflow: "hidden",
          background: "linear-gradient(180deg, rgba(23,24,29,.95) 0%, rgba(14,15,18,.95) 100%)",
          border: `${1.5 * k}px solid rgba(255,255,255,.09)`, boxShadow: `0 ${36 * k}px ${96 * k}px rgba(0,0,0,.55)`,
          opacity: Math.min(1, pIn * 1.6) * (1 - out),
          transform: `perspective(${2000 * k}px) translateY(${(1 - pIn) * 70 * k + out * 50 * k}px) rotateX(${(1 - pIn) * 12}deg)` }}>
          <div style={{ position: "absolute", left: 40 * k, right: 40 * k, top: 0, height: HEADH, display: "flex", alignItems: "center",
            gap: 20 * k }}>
            <Icon d={I.back} size={30 * k} color={MUTED} width={2.4} draw={ramp(frame, T(0.2), 12, inOut) * (1 - ramp(frame, end, 8))} />
            <Avatar name={title} size={64 * k} accent={accent} tone="gray"
              pop={ramp(frame, T(0.15), 16, backOut) * (1 - ramp(frame, end + 2, 8, easeIn))} />
            <div style={{ display: "flex", flexDirection: "column", gap: 4 * k, minWidth: 0 }}>
              <Rise at={T(0.22)} out={end}>
                <span style={{ fontFamily: INTER, fontWeight: 700, fontSize: 30 * k, color: "#fff", whiteSpace: "nowrap" }}>{title}</span>
              </Rise>
              <Rise at={T(0.28)} out={end}>
                <span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 24 * k, letterSpacing: "0.04em",
                  color: typingLeft ? CYAN : "rgba(255,255,255,.45)" }}>{typingLeft ? "typing…" : "online"}</span>
              </Rise>
            </div>
          </div>
          <div style={{ position: "absolute", left: 0, right: 0, top: HEADH, height: 1.5 * k, background: "rgba(255,255,255,.08)",
            transformOrigin: "left", transform: `scaleX(${ramp(frame, T(0.2), T(0.6), inOut)})` }} />
          <div style={{ position: "absolute", left: 40 * k, right: 40 * k, top: HEADH + 12 * k, height: VH, overflow: "hidden",
            maskImage: mask, WebkitMaskImage: mask }}>
            <div style={{ position: "relative", transform: `translateY(${TOPPAD - scroll}px)` }}>
              {msgs.map((m, i) => {
                const { a, b } = S[i];
                if (frame < a) return null;
                const L = lay[i];
                const right = m.side === "r";
                const tp = ramp(frame, a, 10, backOut) * (1 - ramp(frame, b - 2, 5, inOut));
                const mp = ramp(frame, b, T(0.45), backOut);
                const shrink = ramp(frame, end + 2, 9, easeIn);
                const radius = right ? `${Rr}px ${Rr}px ${tail}px ${Rr}px` : `${Rr}px ${Rr}px ${Rr}px ${tail}px`;
                const origin = right ? "100% 100%" : "0% 100%";
                const ink = right ? inkOn(accent) : "#fff";
                return (
                  <div key={i} style={{ position: "absolute", left: 0, right: 0, top: L.top, display: "flex", flexDirection: "column",
                    alignItems: right ? "flex-end" : "flex-start" }}>
                    {L.nameH ? (
                      <div style={{ height: L.nameH }}>
                        <Rise at={a} out={end}>
                          <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 24 * k, letterSpacing: "0.16em",
                            color: right ? accent : "rgba(255,255,255,.55)" }}>{m.who.toUpperCase()}</span>
                        </Rise>
                      </div>
                    ) : null}
                    <div style={{ position: "relative", minHeight: TYPH }}>
                      {tp > 0.001 && frame < b + 4 ? (
                        <div style={{ position: "absolute", left: right ? undefined : 0, right: right ? 0 : undefined, top: 0,
                          width: TYPW, height: TYPH, borderRadius: radius, background: right ? accent : "#2a2c32",
                          transform: `scale(${tp})`, transformOrigin: origin, display: "flex", alignItems: "center",
                          justifyContent: "center", gap: 9 * k }}>
                          {[0, 1, 2].map((d) => {
                            const w = Math.max(0, Math.sin((frame - a) * 0.38 - d * 0.95));
                            return <span key={d} style={{ width: 13 * k, height: 13 * k, borderRadius: "50%",
                              background: ink, opacity: 0.4 + 0.6 * w, transform: `translateY(${-w * 7 * k}px)` }} />;
                          })}
                        </div>
                      ) : null}
                      {frame >= b ? (
                        <div style={{ display: "inline-flex", flexDirection: "column", padding: `${PY}px ${PX}px`, borderRadius: radius,
                          background: right ? `linear-gradient(160deg, ${tint(accent, 0.12)} 0%, ${accent} 100%)` : "#2a2c32",
                          boxShadow: `0 ${12 * k}px ${30 * k}px rgba(0,0,0,.3)`,
                          transform: `scale(${(0.3 + 0.7 * mp) * (1 - 0.2 * shrink)})`,
                          transformOrigin: origin, opacity: Math.min(1, mp * 3) * (1 - shrink) }}>
                          {m.ls.map((ln, l) => (
                            <Rise key={l} at={b + 3 + l * 2} out={end}>
                              <span style={{ display: "block", fontFamily: INTER, fontWeight: right ? 700 : 400, fontSize: FS,
                                lineHeight: `${LH}px`, color: ink, whiteSpace: "pre" }}>{ln}</span>
                            </Rise>
                          ))}
                        </div>
                      ) : null}
                    </div>
                    {i === lastR && frame >= b + 8 ? (
                      <div style={{ marginTop: 6 * k, height: RECH - 6 * k, display: "flex", alignItems: "center", gap: 8 * k }}>
                        <Icon d={I.ticks} size={26 * k} color={CYAN} width={2.2} draw={ramp(frame, b + 8, 10, inOut) * (1 - shrink)} />
                        <Rise at={b + 10} out={end}>
                          <span style={{ fontFamily: INTER, fontWeight: 700, fontSize: 24 * k, color: CYAN }}>Read</span>
                        </Rise>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
// ------------------------------------------------------------------ 6. phone screen
/** Headline lines with an accent marker sweeping across the highlighted phrase (p 0..1). */
const MarkedLines: React.FC<{ ls: string[]; range: [number, number] | null; mark: number; accent: string; at: number;
  step: number; end: number; style: React.CSSProperties }> = ({ ls, range, mark, accent, at, step, end, style }) => {
  const offs = offsets(ls);
  return (
    <>
      {ls.map((ln, i) => (
        <Rise key={i} at={at + i * step} out={end + Math.min(i, 3)}>
          <span style={{ whiteSpace: "pre", ...style }}>
            {runs(ln, offs[i], range).map((r, j) => (
              <span key={j} style={r.kind === "hot" ? markStyle(accent, mark, 0.55) : undefined}>{r.t}</span>
            ))}
          </span>
        </Rise>
      ))}
    </>
  );
};

/**
 * A news story on a phone: overlay.text the headline, overlay.label the
 * outlet (generic), overlay.subtitle the standfirst, overlay.highlight the
 * words to mark, overlay.media[0] the story picture (optional). Own
 * backdrop: the phone rises out of the frame in 3D, the screen wakes, the
 * story rises line by line; then the phone turns aside and the story slides
 * out from behind it as a large card, its key words marked.
 */
const PhoneScreen: Look = ({ overlay, accent: acc }) => {
  const { frame, fps, dur, end, out, k, width, height, T } = useT();
  const accent = pick(acc);
  const head = unquote(clean(overlay.text, 120));
  if (!head) return null;
  const source = clean(overlay.label, 22) || "Newsroom";
  const dek = unquote(clean(overlay.subtitle, 110));
  const pic = firstStill(overlay);
  const seed = seedOf(head);
  const PW = 460 * k, PH = 880 * k, BZ = 14 * k, PADS = 26 * k;
  const long = head.length > 58;
  const HF = (long ? 32 : 37) * k;
  const hls = wrap(head, long ? 19 : 16, 5);
  const dls = dek ? wrap(dek, 27, 3) : [];
  const cls = wrap(head, 23, 4);
  const cdek = dek ? wrap(dek, 44, 2) : [];
  const hi = clean(overlay.highlight);
  const range = findRange(hls.join(" "), hi);
  const crange = findRange(cls.join(" "), hi);
  // Choreography.
  const rise = ramp(frame, 0, T(0.9));
  const wake = ramp(frame, T(0.5), T(0.35), inOut);
  const c0 = T(0.65);
  const slideAt = Math.max(T(1.55), c0 + 3 * (hls.length + 3));
  const slide = ramp(frame, slideAt, T(0.8), inOut);
  const cardP = ramp(frame, slideAt + 4, T(0.7));
  const cardText = slideAt + T(0.35);
  const markAt = cardText + cls.length * 3 + 6;
  const mark = ramp(frame, markAt, T(0.5), inOut);
  const float = Math.sin((frame / fps) * 1.2) * 6 * k;
  const cx = width / 2 - 370 * k * slide;
  const cy = height / 2;
  const ry = -16 * (1 - rise) - 7 + 17 * slide;
  const hh = String(6 + (seed % 4)).padStart(2, "0");
  const mm = String(seed % 60).padStart(2, "0");
  const sheenX = -60 + 90 * rise + 50 * slide;
  const CW = 880 * k;
  const cardLeft = 940 * k;
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 42%, #1d2029 0%, #0d0f14 58%, #050608 100%)" }} />
      <AbsoluteFill style={{ opacity: 0.5, background: "repeating-linear-gradient(135deg, rgba(255,255,255,.028) 0px, " +
        `rgba(255,255,255,.028) ${2 * k}px, transparent ${2 * k}px, transparent ${26 * k}px)` }} />
      <AbsoluteFill style={{ background: `radial-gradient(ellipse ${30 * (1 + slide * 0.4)}% 46% at ${(cx / width) * 100 + slide * 22}% 52%, ` +
        `${rgba(accent, 0.2)} 0%, ${rgba(accent, 0.06)} 45%, transparent 72%)`, opacity: rise }} />
      <div style={{ position: "absolute", left: cx - PW * 0.6, top: cy + PH / 2 - 26 * k, width: PW * 1.2, height: 70 * k,
        borderRadius: "50%", background: "radial-gradient(ellipse at 50% 50%, rgba(0,0,0,.7) 0%, rgba(0,0,0,0) 70%)",
        opacity: rise * (1 - out) }} />
      {/* the story card slides out from behind the phone */}
      <div style={{ position: "absolute", left: cardLeft, top: 0, bottom: 0, width: CW, display: "flex", alignItems: "center" }}>
        <div style={{ width: CW, boxSizing: "border-box", padding: `${40 * k}px ${46 * k}px ${44 * k}px`, borderRadius: 26 * k,
          background: "linear-gradient(180deg, #ffffff 0%, #eef0f3 100%)", boxShadow: `0 ${40 * k}px ${100 * k}px rgba(0,0,0,.55)`,
          opacity: Math.min(1, cardP * 2) * (1 - out),
          transform: `translateX(${(1 - cardP) * -300 * k - out * 80 * k}px) scale(${0.92 + 0.08 * cardP}) translateY(${float * 0.6}px)` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 16 * k }}>
            <div style={{ width: 44 * k, height: 44 * k, borderRadius: 12 * k, background: accent, display: "flex",
              alignItems: "center", justifyContent: "center", transform: `scale(${ramp(frame, cardText - 4, 14, backOut)})` }}>
              <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k, color: inkOn(accent), lineHeight: 1 }}>
                {initials(source).slice(0, 1)}</span>
            </div>
            <Rise at={cardText - 2} out={end}>
              <span style={{ fontFamily: INTER, fontWeight: 700, fontSize: 28 * k, color: PAGE_INK, whiteSpace: "nowrap" }}>
                {source}<span style={{ fontWeight: 400, color: "#8a8f98" }}> · now</span></span>
            </Rise>
          </div>
          <div style={{ marginTop: 22 * k }}>
            <MarkedLines ls={cls} range={crange} mark={mark} accent={accent} at={cardText} step={3} end={end}
              style={{ fontFamily: INTER, fontWeight: 800, fontSize: 50 * k, lineHeight: 1.14, color: PAGE_INK, letterSpacing: "-0.01em" }} />
          </div>
          {cdek.length ? (
            <div style={{ marginTop: 16 * k }}>
              {cdek.map((ln, i) => (
                <Rise key={i} at={cardText + cls.length * 3 + i * 3} out={end}>
                  <span style={{ fontFamily: INTER, fontWeight: 400, fontSize: 28 * k, lineHeight: 1.35, color: "#555a64",
                    whiteSpace: "pre" }}>{ln}</span>
                </Rise>
              ))}
            </div>
          ) : null}
        </div>
      </div>
      {/* the phone */}
      <div style={{ position: "absolute", left: cx - PW / 2, top: cy - PH / 2, width: PW, height: PH, borderRadius: 66 * k,
        padding: BZ, boxSizing: "border-box",
        background: "linear-gradient(145deg, #4a4d56 0%, #17181c 38%, #0b0b0d 62%, #34363d 100%)",
        boxShadow: `0 ${50 * k}px ${120 * k}px rgba(0,0,0,.7), inset 0 0 0 ${2 * k}px rgba(255,255,255,.14)`,
        opacity: Math.min(1, rise * 2) * (1 - out),
        transform: `perspective(${2600 * k}px) translateY(${(1 - rise) * 820 * k + float + out * 140 * k}px) ` +
          `rotateX(${(1 - rise) * 34 + out * 16}deg) rotateY(${ry}deg) rotateZ(${(1 - rise) * -5}deg)` }}>
        <div style={{ position: "relative", width: "100%", height: "100%", borderRadius: 54 * k, overflow: "hidden",
          background: "#f4f5f7" }}>
          <div style={{ position: "absolute", left: PADS, right: PADS, top: 20 * k, height: 34 * k, display: "flex",
            alignItems: "center", justifyContent: "space-between" }}>
            <Rise at={T(0.55)} out={end}>
              <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 24 * k, color: PAGE_INK }}>{hh}:{mm}</span>
            </Rise>
            <div style={{ display: "flex", alignItems: "center", gap: 8 * k }}>
              <Icon d={I.signal} size={24 * k} color={PAGE_INK} width={2.6} />
              <div style={{ width: 38 * k, height: 20 * k, borderRadius: 6 * k, border: `${2 * k}px solid ${PAGE_INK}`,
                padding: 2 * k, boxSizing: "border-box" }}>
                <div style={{ width: "72%", height: "100%", borderRadius: 3 * k, background: PAGE_INK }} />
              </div>
            </div>
          </div>
          <div style={{ position: "absolute", left: "50%", top: 16 * k, width: 124 * k, height: 36 * k, marginLeft: -62 * k,
            borderRadius: 18 * k, background: "#050506" }} />
          <div style={{ position: "absolute", left: PADS, right: PADS, top: 74 * k, height: 56 * k, display: "flex",
            alignItems: "center", gap: 14 * k, borderBottom: `${1.5 * k}px solid rgba(0,0,0,.1)` }}>
            <div style={{ width: 40 * k, height: 40 * k, borderRadius: 11 * k, background: accent, display: "flex",
              alignItems: "center", justifyContent: "center", transform: `scale(${ramp(frame, c0, 14, backOut)})` }}>
              <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 26 * k, color: inkOn(accent), lineHeight: 1 }}>
                {initials(source).slice(0, 1)}</span>
            </div>
            <Rise at={c0 + 2} out={end} style={{ flex: 1, minWidth: 0 }}>
              <span style={{ fontFamily: INTER, fontWeight: 800, fontSize: 26 * k, color: PAGE_INK, whiteSpace: "nowrap" }}>{source}</span>
            </Rise>
            <Icon d={I.search} size={28 * k} color="#6b7078" width={2.2} draw={ramp(frame, c0 + 4, 12, inOut)} />
          </div>
          <div style={{ position: "absolute", left: PADS, right: PADS, top: 150 * k, display: "flex", flexDirection: "column" }}>
            <Rise at={c0 + 4} out={end}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 8 * k, padding: `${4 * k}px ${12 * k}px`,
                borderRadius: 8 * k, background: rgba(accent, 0.16), fontFamily: LABEL, fontWeight: 800, fontSize: 24 * k,
                letterSpacing: "0.16em", color: shade(accent, 0.62) }}>
                <span style={{ width: 9 * k, height: 9 * k, borderRadius: "50%", background: accent,
                  opacity: 0.5 + 0.5 * Math.abs(Math.sin(frame / 6)) }} />LATEST</span>
            </Rise>
            <div style={{ marginTop: 14 * k }}>
              <MarkedLines ls={hls} range={range} mark={mark} accent={accent} at={c0 + 7} step={3} end={end}
                style={{ fontFamily: INTER, fontWeight: 800, fontSize: HF, lineHeight: 1.16, color: PAGE_INK }} />
            </div>
            {dls.length ? (
              <div style={{ marginTop: 12 * k }}>
                {dls.map((ln, i) => (
                  <Rise key={i} at={c0 + 9 + (hls.length + i) * 3} out={end}>
                    <span style={{ fontFamily: INTER, fontWeight: 400, fontSize: 24 * k, lineHeight: 1.36, color: "#5b606a",
                      whiteSpace: "pre" }}>{ln}</span>
                  </Rise>
                ))}
              </div>
            ) : null}
            {pic ? (
              <div style={{ marginTop: 18 * k, height: 214 * k, borderRadius: 16 * k, overflow: "hidden", background: "#d9dce1",
                clipPath: `inset(0 ${(1 - ramp(frame, c0 + 12 + hls.length * 3, T(0.6), inOut)) * 100}% 0 0 round ${16 * k}px)` }}>
                <Img src={pic} style={{ width: "100%", height: "100%", objectFit: "cover",
                  transform: `scale(${1.08 + 0.06 * (frame / dur)})` }} />
              </div>
            ) : (
              <div style={{ marginTop: 20 * k, display: "flex", flexDirection: "column", gap: 14 * k }}>
                {[0.96, 0.9, 0.97, 0.62].map((w, i) => (
                  <div key={i} style={{ height: 14 * k, borderRadius: 7 * k, background: "rgba(0,0,0,.09)", transformOrigin: "left",
                    width: `${w * 100}%`, transform: `scaleX(${ramp(frame, c0 + 12 + (hls.length + i) * 3, T(0.5), inOut) * (1 - out)})` }} />
                ))}
              </div>
            )}
          </div>
          <div style={{ position: "absolute", left: "50%", bottom: 12 * k, width: 150 * k, height: 6 * k, marginLeft: -75 * k,
            borderRadius: 3 * k, background: "rgba(0,0,0,.55)" }} />
          <div style={{ position: "absolute", inset: 0, background: "#050506", opacity: 1 - wake, pointerEvents: "none" }} />
          <div style={{ position: "absolute", inset: 0, pointerEvents: "none",
            background: `linear-gradient(115deg, rgba(255,255,255,0) ${sheenX}%, rgba(255,255,255,.22) ${sheenX + 12}%, ` +
              `rgba(255,255,255,0) ${sheenX + 24}%)` }} />
        </div>
      </div>
    </AbsoluteFill>
  );
};
// ------------------------------------------------------------------ 7. browser window
const sentencesOf = (s: string): string[] =>
  (s.match(/[^.!?]+[.!?]+["”’)]*|[^.!?]+$/g) || []).map((x) => x.trim()).filter(Boolean);
type Para = { ls: string[]; key: boolean; range: [number, number] | null; y: number };

/**
 * An article in a browser: overlay.text the headline, overlay.label the site
 * (generic), overlay.subtitle the kicker, overlay.body the article text,
 * overlay.highlight the sentence or phrase to mark. Own backdrop (the dark
 * case desktop): the window swings in, the address types, a load bar races,
 * the page builds and scrolls to the key sentence, a cursor clicks it and the
 * marker sweeps across it while the camera pushes in.
 */
const BrowserWindow: Look = ({ overlay, accent: acc }) => {
  const { frame, end, out, k, width, height, T } = useT();
  const accent = pick(acc);
  const head = unquote(clean(overlay.text, 120));
  if (!head) return null;
  const seed = seedOf(head);
  const site = clean(overlay.label, 26);
  const siteName = (site || "News").toUpperCase();
  const kicker = clean(overlay.subtitle, 48).toUpperCase();
  const url = `${slug(site, 16) || "news"}/${slug(head, 34) || "story"}`;
  const hiText = unquote(clean(overlay.highlight, 220));
  const sents = sentencesOf(clean(overlay.body, 900)).slice(0, 8);
  let keyIdx = hiText ? sents.findIndex((s) => s.toLowerCase().includes(hiText.toLowerCase())) : -1;
  if (keyIdx < 0 && hiText.length > 24) {
    keyIdx = Math.min(1, sents.length);
    sents.splice(keyIdx, 0, hiText);
  }
  if (keyIdx < 0 && sents.length) keyIdx = 0;
  // Paragraphs: two sentences each, the key sentence alone.
  const PCH = 58;
  let paras: Para[] = [];
  let buf: string[] = [];
  const flush = () => {
    if (buf.length) paras.push({ ls: wrap(buf.join(" "), PCH, 3), key: false, range: null, y: 0 });
    buf = [];
  };
  sents.forEach((s, i) => {
    if (i === keyIdx) {
      flush();
      const ls = wrap(s, PCH, 4);
      const joined = ls.join(" ");
      const r = hiText && hiText.length < s.length * 0.8 ? findRange(joined, hiText) : null;
      paras.push({ ls, key: true, range: r || [0, joined.length], y: 0 });
    } else {
      buf.push(s);
      if (buf.length >= 2) flush();
    }
  });
  flush();
  const kp = paras.findIndex((p) => p.key);
  if (kp >= 0) paras = paras.slice(Math.max(0, kp - 2), kp + 2);
  else paras = paras.slice(0, 3);
  const HL = wrap(head, 32, 3);
  // Layout, in page coordinates.
  const W = 1400 * k, H = 840 * k, TOP = 128 * k, VH = H - TOP, CL = 200 * k, LH = 46 * k;
  let y = 40 * k;
  const headerY = y;
  y += 90 * k;
  const kickerY = y;
  if (kicker) y += 46 * k;
  const headY = y;
  y += HL.length * 60 * k + 20 * k;
  const bylineY = y;
  y += 84 * k;
  for (const p of paras) {
    p.y = y;
    y += p.ls.length * LH + 30 * k;
  }
  const barsY = y;
  const contentH = y + 3 * 38 * k + 40 * k;
  const key = paras.find((p) => p.key) || null;
  const keyY = key ? key.y : headY;
  const scrollTo = Math.max(0, Math.min(keyY - 250 * k, contentH - VH));
  // Choreography.
  const winP = ramp(frame, 0, T(0.8));
  const typeAt = T(0.45);
  const perChar = Math.min(0.9, T(0.8) / Math.max(1, url.length));
  const typed = Math.max(0, Math.min(url.length, Math.floor((frame - typeAt) / Math.max(0.2, perChar))));
  const typeDone = typeAt + Math.ceil(url.length * perChar);
  const loadAt = typeDone + 2;
  const load = ramp(frame, loadAt, T(0.5), inOut);
  const pageAt = loadAt + 4;
  const scrollAt = loadAt + T(0.9);
  const sc = ramp(frame, scrollAt, T(0.9), inOut) * scrollTo;
  const clickAt = scrollAt + T(0.9);
  const cur = ramp(frame, scrollAt, clickAt - scrollAt, inOut);
  const markLines = key ? key.ls.length : HL.length;
  const markP = (i: number) => ramp(frame, clickAt + 3 + i * T(0.3), T(0.35), inOut);
  const push = ramp(frame, clickAt, T(1.2), inOut);
  const click = interpolate(frame, [clickAt, clickAt + 3, clickAt + 9], [1, 0.8, 1], clamp);
  const ring = interpolate(frame, [clickAt, clickAt + 16], [0, 1], clamp);
  const wx = (width - W) / 2, wy = (height - H) / 2;
  const tx = CL + 300 * k;
  const ty = TOP + (keyY - scrollTo) + LH * 0.5;
  const cx = interpolate(cur, [0, 1], [760 * k, tx]);
  const cy = interpolate(cur, [0, 1], [96 * k, ty]) - Math.sin(cur * Math.PI) * 60 * k;
  const lineAt = (i: number) => pageAt + 8 + i * 2;
  let li = 0;
  return (
    <AbsoluteFill>
      <CaseBackdrop tone="dark" seed={seed % 9} />
      <AbsoluteFill style={{ background: `radial-gradient(ellipse 60% 50% at 50% 55%, ${rgba(accent, 0.1)} 0%, transparent 70%)` }} />
      <div style={{ position: "absolute", left: wx, top: wy, width: W, height: H, borderRadius: 18 * k, overflow: "hidden",
        background: "#e7e9ed", boxShadow: `0 ${50 * k}px ${130 * k}px rgba(0,0,0,.6), 0 0 0 ${1.5 * k}px rgba(255,255,255,.25)`,
        opacity: Math.min(1, winP * 1.8) * (1 - out), transformOrigin: `${tx}px ${ty}px`,
        transform: `perspective(${2400 * k}px) translateY(${(1 - winP) * 90 * k + out * 60 * k}px) ` +
          `rotateX(${(1 - winP) * 16 + out * 8}deg) scale(${(0.9 + 0.1 * winP) * (1 + 0.06 * push)})` }}>
        {/* tab strip */}
        <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 64 * k, display: "flex", alignItems: "flex-end",
          padding: `0 ${24 * k}px`, gap: 20 * k }}>
          <div style={{ display: "flex", gap: 10 * k, alignSelf: "center" }}>
            {[0, 1, 2].map((i) => <span key={i} style={{ width: 16 * k, height: 16 * k, borderRadius: "50%",
              background: i === 0 ? "#9ea3ab" : "#b9bdc4", transform: `scale(${ramp(frame, 4 + i * 2, 12, backOut)})` }} />)}
          </div>
          <div style={{ width: 360 * k, height: 50 * k, borderRadius: `${14 * k}px ${14 * k}px 0 0`, background: "#fff",
            display: "flex", alignItems: "center", gap: 12 * k, padding: `0 ${18 * k}px`, boxSizing: "border-box" }}>
            <span style={{ width: 22 * k, height: 22 * k, borderRadius: 6 * k, background: accent, flexShrink: 0 }} />
            <Rise at={T(0.3)} out={end} style={{ minWidth: 0 }}>
              <span style={{ fontFamily: INTER, fontWeight: 700, fontSize: 24 * k, color: PAGE_INK, whiteSpace: "nowrap" }}>
                {clean(head, 22)}</span>
            </Rise>
          </div>
        </div>
        {/* toolbar */}
        <div style={{ position: "absolute", left: 0, right: 0, top: 64 * k, height: 64 * k, background: "#fff", display: "flex",
          alignItems: "center", gap: 18 * k, padding: `0 ${24 * k}px`, boxSizing: "border-box",
          borderBottom: `${1.5 * k}px solid rgba(0,0,0,.08)` }}>
          {[I.back, I.fwd, I.reload].map((d, i) => (
            <Icon key={i} d={d} size={28 * k} color={i === 1 ? "#b3b7be" : "#5f646c"} width={2.2}
              draw={ramp(frame, T(0.25) + i * 3, 12, inOut)} />
          ))}
          <div style={{ flex: 1, height: 44 * k, borderRadius: 22 * k, background: "#eff1f4", display: "flex", alignItems: "center",
            gap: 12 * k, padding: `0 ${20 * k}px`, overflow: "hidden" }}>
            <Icon d={I.lock} size={22 * k} color="#5f646c" width={2.2} />
            <span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 24 * k, color: PAGE_INK, whiteSpace: "pre",
              opacity: 1 - ramp(frame, end, 8) }}>
              {url.slice(0, typed)}
              <span style={{ display: "inline-block", width: 2 * k, height: 26 * k, marginLeft: 2 * k, verticalAlign: "middle",
                background: accent, opacity: frame >= typeAt && frame < loadAt + 6 && frame % 14 < 8 ? 1 : 0 }} />
            </span>
          </div>
          <Icon d={I.star} size={28 * k} color="#5f646c" width={2} draw={ramp(frame, T(0.35), 12, inOut)} />
        </div>
        <div style={{ position: "absolute", left: 0, top: TOP - 3 * k, height: 4 * k, width: `${load * 100}%`, background: accent,
          boxShadow: `0 0 ${10 * k}px ${rgba(accent, 0.8)}`, opacity: 1 - ramp(frame, loadAt + T(0.5), 8) }} />
        {/* page */}
        <div style={{ position: "absolute", left: 0, right: 0, top: TOP, height: VH, overflow: "hidden", background: "#fff" }}>
          <div style={{ position: "absolute", left: 0, right: 0, top: 0, transform: `translateY(${-sc}px)` }}>
            <div style={{ position: "absolute", left: CL, right: CL, top: headerY, height: 50 * k, display: "flex",
              alignItems: "center", justifyContent: "space-between" }}>
              <Rise at={pageAt} out={end}>
                <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 34 * k, letterSpacing: "0.12em", color: PAGE_INK }}>
                  {siteName}</span>
              </Rise>
              <div style={{ display: "flex", gap: 22 * k }}>
                {[90, 70, 110, 80].map((w, i) => (
                  <span key={i} style={{ width: w * k, height: 12 * k, borderRadius: 6 * k, background: "rgba(0,0,0,.12)",
                    transformOrigin: "left", transform: `scaleX(${ramp(frame, pageAt + 2 + i * 2, 12, inOut) * (1 - out)})` }} />
                ))}
              </div>
            </div>
            <div style={{ position: "absolute", left: CL, right: CL, top: headerY + 66 * k, height: 2 * k, background: PAGE_INK,
              transformOrigin: "left", transform: `scaleX(${ramp(frame, pageAt + 2, T(0.6), inOut) * (1 - out)})` }} />
            {kicker ? (
              <div style={{ position: "absolute", left: CL, top: kickerY }}>
                <Rise at={pageAt + 5} out={end}>
                  <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 26 * k, letterSpacing: "0.2em",
                    color: shade(accent, 0.7) }}>{kicker}</span>
                </Rise>
              </div>
            ) : null}
            <div style={{ position: "absolute", left: CL, right: CL, top: headY }}>
              {HL.map((ln, i) => (
                <Rise key={i} at={pageAt + 6 + i * 3} out={end + Math.min(i, 2)}>
                  <span style={{ fontFamily: INTER, fontWeight: 800, fontSize: 50 * k, lineHeight: `${60 * k}px`, color: PAGE_INK,
                    whiteSpace: "pre", ...(key ? {} : markStyle(accent, markP(i), 0.5)) }}>{ln}</span>
                </Rise>
              ))}
            </div>
            <div style={{ position: "absolute", left: CL, top: bylineY, display: "flex", alignItems: "center", gap: 16 * k }}>
              <span style={{ width: 44 * k, height: 44 * k, borderRadius: "50%", background: "#d7dade",
                transform: `scale(${ramp(frame, pageAt + 10, 12, backOut) * (1 - out)})` }} />
              {[180, 120].map((w, i) => (
                <span key={i} style={{ width: w * k, height: 14 * k, borderRadius: 7 * k, background: "rgba(0,0,0,.12)",
                  transformOrigin: "left", transform: `scaleX(${ramp(frame, pageAt + 11 + i * 2, 12, inOut) * (1 - out)})` }} />
              ))}
            </div>
            {paras.map((p, pi) => {
              const offs = offsets(p.ls);
              return (
                <div key={pi} style={{ position: "absolute", left: CL, right: CL, top: p.y }}>
                  {p.ls.map((ln, i) => {
                    const at = lineAt(li++);
                    return (
                      <Rise key={i} at={at} out={end}>
                        <span style={{ fontFamily: INTER, fontWeight: p.key ? 700 : 400, fontSize: 30 * k, lineHeight: `${LH}px`,
                          color: p.key ? PAGE_INK : "#3b3f47", whiteSpace: "pre" }}>
                          {runs(ln, offs[i], p.range).map((r, j) => (
                            <span key={j} style={r.kind === "hot" ? markStyle(accent, markP(i), 0.5) : undefined}>{r.t}</span>
                          ))}
                        </span>
                      </Rise>
                    );
                  })}
                </div>
              );
            })}
            <div style={{ position: "absolute", left: CL, right: CL, top: barsY, display: "flex", flexDirection: "column", gap: 24 * k }}>
              {[0.97, 0.92, 0.58].map((w, i) => (
                <span key={i} style={{ width: `${w * 100}%`, height: 14 * k, borderRadius: 7 * k, background: "rgba(0,0,0,.1)",
                  transformOrigin: "left", transform: `scaleX(${ramp(frame, lineAt(li + i), 14, inOut) * (1 - out)})` }} />
              ))}
            </div>
          </div>
        </div>
        {/* cursor */}
        {frame >= scrollAt - 2 && markLines > 0 ? (
          <div style={{ position: "absolute", left: cx, top: cy, width: 0, height: 0,
            opacity: ramp(frame, scrollAt - 2, 6) * (1 - ramp(frame, end - 4, 8)) }}>
            {ring > 0 && ring < 1 ? (
              <div style={{ position: "absolute", left: -30 * k, top: -30 * k, width: 60 * k, height: 60 * k, borderRadius: "50%",
                border: `${3 * k}px solid ${accent}`, transform: `scale(${0.4 + ring * 1.2})`, opacity: 1 - ring }} />
            ) : null}
            <Icon d={I.cursor} size={44 * k} color={PAGE_INK} width={1.6} fill="#fff"
              style={{ position: "absolute", left: -8 * k, top: -6 * k, transform: `scale(${click})`, transformOrigin: "20% 15%",
                filter: `drop-shadow(0 ${4 * k}px ${6 * k}px rgba(0,0,0,.35))` }} />
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
// ------------------------------------------------------------------ 8. video player
/**
 * Player chrome riding on the footage (a tag): overlay.text the video title,
 * overlay.label the channel (generic), overlay.subtitle the chapter, value
 * the moment in seconds, total the video's length in seconds. A play button
 * pops in the centre and clears, the scrubber seeks along a chaptered bar to
 * the moment and keeps playing, a hover preview with the chapter and the
 * timecode rises over the playhead. Soft gradients top and bottom only.
 */
const VideoPlayer: Look = ({ overlay, accent: acc }) => {
  const { frame, fps, end, out, k, width, height, T } = useT();
  const accent = pick(acc);
  const title = unquote(clean(overlay.text, 90));
  if (!title) return null;
  const channel = clean(overlay.label, 26);
  const chapter = clean(overlay.subtitle, 34);
  const pic = firstStill(overlay);
  const seed = seedOf(title);
  // Seconds by default; a "min" / "h" suffix scales value and total.
  const unit = /^h/i.test((overlay.suffix || "").trim()) ? 3600 : /^m/i.test((overlay.suffix || "").trim()) ? 60 : 1;
  const rawV = finite(overlay.value);
  const rawT = finite(overlay.total);
  const v = rawV !== null ? rawV * unit : null;
  const tot = rawT !== null ? rawT * unit : null;
  const total = tot !== null && tot > 0 ? tot : v !== null && v > 0 ? Math.max(v * 1.6, v + 120) : 1800;
  const target = v !== null && v >= 0 ? Math.min(v, total) : total * 0.42;
  const tls = wrap(title, 44, 2);
  // Chapters: three gaps at seeded positions, none right at the moment itself.
  const cuts = [0.18 + rnd(seed) * 0.08, 0.44 + rnd(seed + 1) * 0.1, 0.7 + rnd(seed + 2) * 0.1]
    .filter((c) => Math.abs(c - target / total) > 0.03);
  const X0 = 90 * k, BW = width - 180 * k, BY = height - 172 * k;
  const seekAt = T(0.55);
  const seekF = T(1.2);
  const seek = ramp(frame, seekAt, seekF, inOut);
  const playing = Math.max(0, frame - seekAt - seekF) / fps;
  const now = Math.min(total, target * seek + playing);
  const p = total > 0 ? now / total : 0;
  const barIn = ramp(frame, T(0.15), T(0.7), inOut) * (1 - out);
  const hover = ramp(frame, seekAt + seekF - 4, T(0.5), backOut) * (1 - ramp(frame, end, 10, easeIn));
  const hx = Math.max(X0, Math.min(X0 + BW - 300 * k, X0 + p * BW - 150 * k));
  const pop = ramp(frame, T(0.1), 14, backOut);
  const popOut = ramp(frame, T(0.75), T(0.35), easeIn);
  const ringP = interpolate(frame, [T(0.1), T(0.1) + 20], [0, 1], clamp);
  const segs: [number, number][] = [];
  let a0 = 0;
  for (const c of [...cuts, 1]) {
    segs.push([a0, c]);
    a0 = c;
  }
  const gap = 5 * k;
  const iconAt = (i: number) => T(0.35) + i * 3;
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: ramp(frame, 0, 12) * (1 - out),
        background: "linear-gradient(180deg, rgba(0,0,0,.55) 0%, rgba(0,0,0,0) 24%, rgba(0,0,0,0) 70%, rgba(0,0,0,.62) 100%)" }} />
      {/* play pop */}
      {popOut < 1 ? (
        <div style={{ position: "absolute", left: width / 2 - 75 * k, top: height / 2 - 75 * k, width: 150 * k, height: 150 * k }}>
          {ringP > 0 && ringP < 1 ? (
            <div style={{ position: "absolute", inset: 0, borderRadius: "50%", border: `${3 * k}px solid rgba(255,255,255,.8)`,
              transform: `scale(${1 + ringP * 0.8})`, opacity: 1 - ringP }} />
          ) : null}
          <div style={{ width: "100%", height: "100%", borderRadius: "50%", background: "rgba(10,10,12,.55)",
            border: `${2 * k}px solid rgba(255,255,255,.35)`, display: "flex", alignItems: "center", justifyContent: "center",
            transform: `scale(${pop * (1 + popOut * 0.35)})`, opacity: 1 - popOut }}>
            <Icon d={I.play} size={70 * k} color="#fff" fill="#fff" width={1.5} style={{ marginLeft: 8 * k }} />
          </div>
        </div>
      ) : null}
      {/* title */}
      <div style={{ position: "absolute", left: 90 * k, top: 80 * k, maxWidth: 1150 * k, display: "flex", flexDirection: "column",
        gap: 4 * k }}>
        {tls.map((ln, i) => (
          <Rise key={i} at={T(0.2) + i * 3} out={end + i}>
            <span style={{ fontFamily: INTER, fontWeight: 800, fontSize: 44 * k, lineHeight: 1.18, color: "#fff", whiteSpace: "pre",
              textShadow: "0 3px 18px rgba(0,0,0,.5)" }}>{ln}</span>
          </Rise>
        ))}
        {channel ? (
          <div style={{ display: "flex", alignItems: "center", gap: 14 * k, marginTop: 10 * k }}>
            <Avatar name={channel} size={44 * k} accent={accent} pop={ramp(frame, T(0.3), 14, backOut) * (1 - ramp(frame, end, 8, easeIn))} />
            <Rise at={T(0.34)} out={end}>
              <span style={{ fontFamily: INTER, fontWeight: 700, fontSize: 28 * k, color: "rgba(255,255,255,.88)", whiteSpace: "nowrap" }}>
                {channel}</span>
            </Rise>
          </div>
        ) : null}
      </div>
      {/* hover preview */}
      {hover > 0.001 ? (
        <div style={{ position: "absolute", left: hx, top: BY - 250 * k, width: 300 * k, transformOrigin: "50% 100%",
          transform: `scale(${0.6 + 0.4 * hover})`, opacity: Math.min(1, hover * 2) }}>
          {chapter ? (
            <Rise at={seekAt + seekF} out={end}>
              <span style={{ display: "block", textAlign: "center", fontFamily: LABEL, fontWeight: 800, fontSize: 26 * k,
                letterSpacing: "0.1em", color: "#fff", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                textShadow: "0 2px 10px rgba(0,0,0,.7)" }}>{chapter.toUpperCase()}</span>
            </Rise>
          ) : null}
          <div style={{ position: "relative", marginTop: 8 * k, height: 168 * k, borderRadius: 12 * k, overflow: "hidden",
            border: `${2.5 * k}px solid #fff`, boxShadow: `0 ${16 * k}px ${36 * k}px rgba(0,0,0,.5)`,
            background: `linear-gradient(135deg, ${shade(accent, 0.35)} 0%, #101116 100%)` }}>
            {pic ? <Img src={pic} style={{ width: "100%", height: "100%", objectFit: "cover", filter: "saturate(.9)" }} /> : null}
            <div style={{ position: "absolute", left: "50%", bottom: 10 * k, transform: "translateX(-50%)", padding: `${2 * k}px ${12 * k}px`,
              borderRadius: 8 * k, background: "rgba(0,0,0,.72)", fontFamily: MONO, fontWeight: 700, fontSize: 24 * k, color: "#fff" }}>
              {mmss(now)}</div>
          </div>
        </div>
      ) : null}
      {/* scrubber */}
      <div style={{ position: "absolute", left: X0, top: BY, width: BW, height: 12 * k, transformOrigin: "left",
        transform: `scaleX(${barIn})` }}>
        {segs.map(([s0, s1], i) => {
          const on = p >= s0 && p <= s1 + 1e-6;
          const hgt = (on ? 10 : 6) * k;
          const segW = Math.max(0, (s1 - s0) * BW - gap);
          const fillW = Math.max(0, Math.min(1, (p - s0) / Math.max(1e-6, s1 - s0))) * segW;
          const bufW = Math.max(0, Math.min(1, (p + 0.08 - s0) / Math.max(1e-6, s1 - s0))) * segW;
          return (
            <div key={i} style={{ position: "absolute", left: s0 * BW, top: (12 * k - hgt) / 2, width: segW, height: hgt,
              borderRadius: hgt / 2, background: "rgba(255,255,255,.28)", overflow: "hidden" }}>
              <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: bufW, background: "rgba(255,255,255,.4)" }} />
              <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: fillW, background: accent }} />
            </div>
          );
        })}
        <div style={{ position: "absolute", left: p * BW - 13 * k, top: -7 * k, width: 26 * k, height: 26 * k, borderRadius: "50%",
          background: accent, boxShadow: `0 0 0 ${5 * k}px ${rgba(accent, 0.3)}`,
          transform: `scale(${ramp(frame, seekAt - 4, 12, backOut)})` }} />
      </div>
      {/* controls */}
      <div style={{ position: "absolute", left: X0, right: 90 * k, top: BY + 26 * k, height: 50 * k, display: "flex",
        alignItems: "center", gap: 30 * k }}>
        <Icon d={frame >= seekAt + seekF ? I.pause : I.play} size={36 * k} color="#fff" fill={frame >= seekAt + seekF ? "none" : "#fff"}
          width={2.6} style={{ transform: `scale(${ramp(frame, iconAt(0), 12, backOut) * (1 - out)})` }} />
        <Icon d={I.next} size={32 * k} color="#fff" fill="#fff" width={1.6}
          style={{ transform: `scale(${ramp(frame, iconAt(1), 12, backOut) * (1 - out)})` }} />
        <Icon d={I.volume} size={34 * k} color="#fff" width={2}
          style={{ transform: `scale(${ramp(frame, iconAt(2), 12, backOut) * (1 - out)})` }} />
        <Rise at={iconAt(3)} out={end}>
          <span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 26 * k, color: "#fff", whiteSpace: "pre" }}>
            {mmss(now)}<span style={{ color: "rgba(255,255,255,.6)" }}> / {mmss(total)}</span></span>
        </Rise>
        {chapter ? (
          <Rise at={iconAt(4)} out={end} style={{ minWidth: 0 }}>
            <span style={{ fontFamily: INTER, fontWeight: 700, fontSize: 26 * k, color: "rgba(255,255,255,.85)", whiteSpace: "nowrap" }}>
              <span style={{ color: accent }}>•</span> {chapter}</span>
          </Rise>
        ) : null}
        <div style={{ flex: 1 }} />
        <Icon d={I.gear} size={34 * k} color="#fff" width={2}
          style={{ transform: `scale(${ramp(frame, iconAt(5), 12, backOut) * (1 - out)}) rotate(${ramp(frame, iconAt(5), 24) * 90}deg)` }} />
        <Icon d={I.full} size={34 * k} color="#fff" width={2.2}
          style={{ transform: `scale(${ramp(frame, iconAt(6), 12, backOut) * (1 - out)})` }} />
      </div>
    </AbsoluteFill>
  );
};
// ------------------------------------------------------------------ 9. email card
/**
 * An email: overlay.text the subject, overlay.label the sender, overlay.subtitle
 * the date, overlay.body the message, overlay.highlight the line to mark. An
 * inbox lands with the unread message between two others; it glows, is
 * clicked, and morphs open into the full email; the lines rise and the
 * marker sweeps the key line in the accent.
 */
const EmailCard: Look = ({ overlay, accent: acc }) => {
  const { frame, end, out, k, width, height, T } = useT();
  const hold = useHold();
  const accent = pick(acc);
  const subject = unquote(clean(overlay.text, 110));
  if (!subject) return null;
  const sender = clean(overlay.label, 28) || "Unknown sender";
  const date = clean(overlay.subtitle, 28);
  const body = unquote(clean(overlay.body, 420));
  const W = 1180 * k, PADX = 48 * k;
  const sls = wrap(subject, 38, 2);
  const bls = body ? wrap(body, 60, 6) : [];
  const joined = bls.join(" ");
  const hiRange = findRange(joined, clean(overlay.highlight));
  const firstSentence = sentencesOf(joined)[0] || "";
  const range: [number, number] | null = hiRange || (joined ? [0, Math.min(joined.length, firstSentence.length || joined.length)] : null);
  // The inbox.
  const LHEAD = 76 * k, RH = 104 * k;
  const listH = LHEAD + 3 * RH;
  const listTop = (height - listH) / 2;
  const left = (width - W) / 2;
  const rowTop = listTop + LHEAD + RH;
  // The open email.
  const BLH = 45 * k;
  const EH = 36 * k + 44 * k + 22 * k + sls.length * 54 * k + 26 * k + 64 * k + 24 * k + 2 * k + 26 * k
    + Math.max(bls.length, 3) * BLH + 30 * k + 60 * k + 36 * k;
  const eTop = (height - EH) / 2;
  // Choreography.
  const pIn = ramp(frame, 0, T(0.6));
  const glowAt = T(0.85);
  const clickAt = T(1.1);
  const openAt = T(1.3);
  const m = ramp(frame, openAt, T(0.6), inOut);
  const glow = ramp(frame, glowAt, T(0.3)) * (1 - m);
  const ring = interpolate(frame, [clickAt, clickAt + 16], [0, 1], clamp);
  const c0 = openAt + T(0.45);
  const bodyAt = c0 + 12 + sls.length * 3;
  const markAt = bodyAt + bls.length * 2 + 6;
  const markP = (i: number) => ramp(frame, markAt + i * T(0.22), T(0.3), inOut);
  const top = interpolate(m, [0, 1], [rowTop, eTop]);
  const h = interpolate(m, [0, 1], [RH, EH]);
  const snippet = clean(body || date, 52);
  const others = [0, 2];
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ transform: `scale(${hold})` }}>
        {/* inbox panel */}
        <div style={{ position: "absolute", left, top: listTop, width: W, height: listH, borderRadius: 24 * k,
          background: "linear-gradient(180deg, rgba(26,27,32,.95) 0%, rgba(17,18,22,.95) 100%)",
          border: `${1.5 * k}px solid rgba(255,255,255,.09)`, boxShadow: `0 ${34 * k}px ${90 * k}px rgba(0,0,0,.5)`,
          opacity: Math.min(1, pIn * 1.6) * (1 - m), transform: `translateY(${(1 - pIn) * 50 * k}px) scale(${1 - 0.04 * m})` }}>
          <div style={{ position: "absolute", left: PADX, right: PADX, top: 0, height: LHEAD, display: "flex", alignItems: "center",
            gap: 16 * k, borderBottom: `${1.5 * k}px solid rgba(255,255,255,.08)` }}>
            <Icon d={I.mail} size={30 * k} color={accent} width={2} draw={ramp(frame, T(0.1), T(0.5), inOut)} />
            <Rise at={T(0.15)} out={openAt}>
              <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k, letterSpacing: "0.18em", color: "#fff" }}>INBOX</span>
            </Rise>
            <span style={{ padding: `${3 * k}px ${12 * k}px`, borderRadius: 14 * k, background: accent, fontFamily: LABEL,
              fontWeight: 800, fontSize: 24 * k, letterSpacing: "0.08em", color: inkOn(accent),
              transform: `scale(${ramp(frame, T(0.3), 14, backOut) * (1 - m)})` }}>1 NEW</span>
          </div>
          {others.map((i) => (
            <div key={i} style={{ position: "absolute", left: PADX, right: PADX, top: LHEAD + i * RH, height: RH, display: "flex",
              alignItems: "center", gap: 22 * k, borderBottom: i === 0 ? `${1.5 * k}px solid rgba(255,255,255,.06)` : "none" }}>
              <Avatar name={i === 0 ? "A B" : "C D"} size={56 * k} accent={accent} tone="gray"
                pop={ramp(frame, T(0.25) + i * 4, 14, backOut) * (1 - m)} />
              <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 12 * k }}>
                {[0.34, 0.72].map((w, j) => (
                  <span key={j} style={{ width: `${w * 100}%`, height: 14 * k, borderRadius: 7 * k,
                    background: j ? "rgba(255,255,255,.1)" : "rgba(255,255,255,.2)", transformOrigin: "left",
                    transform: `scaleX(${ramp(frame, T(0.3) + i * 4 + j * 2, 14, inOut) * (1 - m)})` }} />
                ))}
              </div>
            </div>
          ))}
        </div>
        {/* the message: a row that opens into the email */}
        <div style={{ position: "absolute", left, top, width: W, height: h, borderRadius: 24 * k * m + 4 * k, overflow: "hidden",
          background: m > 0 ? "linear-gradient(180deg, #1d1e24 0%, #131418 100%)" : rgba(accent, 0.1 + 0.1 * glow),
          border: m > 0 ? `${1.5 * k}px solid rgba(255,255,255,.1)` : "none",
          boxShadow: m > 0 ? `0 ${40 * k}px ${100 * k}px rgba(0,0,0,${0.6 * m})` : `inset ${5 * k}px 0 0 ${accent}`,
          opacity: Math.min(1, pIn * 1.6) * (1 - out), transform: `translateY(${(1 - pIn) * 50 * k + out * 50 * k}px)` }}>
          {m < 1 ? (
            <div style={{ position: "absolute", left: PADX, right: PADX, top: 0, height: RH, display: "flex", alignItems: "center",
              gap: 22 * k }}>
              <span style={{ width: 12 * k, height: 12 * k, borderRadius: "50%", background: accent, marginLeft: -26 * k,
                boxShadow: `0 0 ${10 * k}px ${accent}`, transform: `scale(${ramp(frame, T(0.3), 12, backOut) * (1 - m)})` }} />
              <Avatar name={sender} size={56 * k} accent={accent} pop={ramp(frame, T(0.28), 14, backOut) * (1 - m)} />
              <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 4 * k }}>
                <Rise at={T(0.32)} out={openAt}>
                  <span style={{ fontFamily: INTER, fontWeight: 800, fontSize: 28 * k, color: "#fff", whiteSpace: "nowrap" }}>
                    {sender}<span style={{ fontWeight: 700, color: "rgba(255,255,255,.8)" }}>  ·  {clean(subject, 40)}</span></span>
                </Rise>
                <Rise at={T(0.36)} out={openAt}>
                  <span style={{ fontFamily: INTER, fontWeight: 400, fontSize: 24 * k, color: "rgba(255,255,255,.5)",
                    whiteSpace: "nowrap" }}>{snippet}</span>
                </Rise>
              </div>
              <Rise at={T(0.4)} out={openAt}>
                <span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 24 * k, color: accent, whiteSpace: "nowrap" }}>
                  {clean(date, 12) || "now"}</span>
              </Rise>
              {ring > 0 && ring < 1 ? (
                <div style={{ position: "absolute", left: W * 0.42 - 40 * k, top: RH / 2 - 40 * k, width: 80 * k, height: 80 * k,
                  borderRadius: "50%", border: `${3 * k}px solid ${accent}`, transform: `scale(${0.3 + ring * 1.4})`,
                  opacity: 1 - ring }} />
              ) : null}
            </div>
          ) : null}
          {m > 0.5 ? (
            <div style={{ position: "absolute", left: PADX, right: PADX, top: 36 * k }}>
              <div style={{ height: 44 * k, display: "flex", alignItems: "center", gap: 26 * k }}>
                {[I.arrowLeft, I.archive, I.trash].map((d, i) => (
                  <Icon key={i} d={d} size={30 * k} color={MUTED} width={2}
                    draw={ramp(frame, c0 + i * 2, 12, inOut) * (1 - ramp(frame, end, 8))} />
                ))}
                <div style={{ flex: 1 }} />
                <Icon d={I.star} size={30 * k} color={accent} width={2} fill={frame >= markAt ? accent : "none"}
                  draw={ramp(frame, c0 + 6, 12, inOut) * (1 - ramp(frame, end, 8))} />
              </div>
              <div style={{ marginTop: 22 * k }}>
                {sls.map((ln, i) => (
                  <Rise key={i} at={c0 + 4 + i * 3} out={end + i}>
                    <span style={{ fontFamily: INTER, fontWeight: 800, fontSize: 44 * k, lineHeight: `${54 * k}px`, color: "#fff",
                      whiteSpace: "pre", ...(range ? {} : markStyle(accent, markP(i), 0.45)) }}>{ln}</span>
                  </Rise>
                ))}
              </div>
              <div style={{ marginTop: 26 * k, height: 64 * k, display: "flex", alignItems: "center", gap: 20 * k }}>
                <Avatar name={sender} size={64 * k} accent={accent}
                  pop={ramp(frame, c0 + 8 + sls.length * 3, 14, backOut) * (1 - ramp(frame, end + 2, 8, easeIn))} />
                <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 2 * k }}>
                  <Rise at={c0 + 9 + sls.length * 3} out={end}>
                    <span style={{ fontFamily: INTER, fontWeight: 700, fontSize: 28 * k, color: "#fff", whiteSpace: "nowrap" }}>{sender}</span>
                  </Rise>
                  <Rise at={c0 + 11 + sls.length * 3} out={end}>
                    <span style={{ fontFamily: INTER, fontWeight: 400, fontSize: 24 * k, color: "rgba(255,255,255,.5)" }}>to me</span>
                  </Rise>
                </div>
                {date ? (
                  <Rise at={c0 + 12 + sls.length * 3} out={end}>
                    <span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 24 * k, color: "rgba(255,255,255,.62)",
                      whiteSpace: "nowrap" }}>{date}</span>
                  </Rise>
                ) : null}
              </div>
              <div style={{ marginTop: 24 * k, height: 2 * k, background: "rgba(255,255,255,.1)", transformOrigin: "left",
                transform: `scaleX(${ramp(frame, bodyAt - 4, T(0.6), inOut) * (1 - out)})` }} />
              <div style={{ marginTop: 26 * k }}>
                {bls.length ? (
                  bls.map((ln, i) => {
                    const offs = offsets(bls);
                    return (
                      <Rise key={i} at={bodyAt + i * 2} out={end + Math.min(i, 3)}>
                        <span style={{ fontFamily: INTER, fontWeight: 400, fontSize: 30 * k, lineHeight: `${BLH}px`,
                          color: "rgba(255,255,255,.86)", whiteSpace: "pre" }}>
                          {runs(ln, offs[i], range).map((r, j) => (
                            <span key={j} style={r.kind === "hot" ? { ...markStyle(accent, markP(i), 0.5), color: "#fff", fontWeight: 700 }
                              : undefined}>{r.t}</span>
                          ))}
                        </span>
                      </Rise>
                    );
                  })
                ) : (
                  [0.94, 0.88, 0.52].map((w, i) => (
                    <div key={i} style={{ height: BLH, display: "flex", alignItems: "center" }}>
                      <span style={{ width: `${w * 100}%`, height: 14 * k, borderRadius: 7 * k, background: "rgba(255,255,255,.12)",
                        transformOrigin: "left", transform: `scaleX(${ramp(frame, bodyAt + i * 2, 14, inOut) * (1 - out)})` }} />
                    </div>
                  ))
                )}
              </div>
              <div style={{ marginTop: 30 * k, display: "inline-flex", alignItems: "center", gap: 12 * k, height: 60 * k,
                padding: `0 ${26 * k}px`, borderRadius: 30 * k, border: `${2 * k}px solid ${rgba(accent, 0.7)}`,
                transform: `scale(${ramp(frame, markAt, 14, backOut) * (1 - ramp(frame, end + 2, 8, easeIn))})`, transformOrigin: "left" }}>
                <Icon d={I.reply2} size={28 * k} color={accent} width={2.2} />
                <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 26 * k, letterSpacing: "0.14em", color: accent }}>REPLY</span>
              </div>
            </div>
          ) : null}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
// ------------------------------------------------------------------ 10. poll results
/**
 * A poll: overlay.text the question, items the options (label, value = votes
 * or percent), overlay.value the total votes, overlay.label who ran it,
 * overlay.highlight the option voted (else the winner). The options land as
 * radio rows, one is tapped, then every bar fills to its share with its
 * percentage rolling; the winner fills in the accent and gets a check.
 */
const PollResults: Look = ({ overlay, accent: acc }) => {
  const { frame, fps, end, out, k, T } = useT();
  const hold = useHold();
  const accent = pick(acc);
  const opts = itemsOf(overlay.items)
    .map((i) => ({ label: clean(i.label || i.text, 40), v: finite(i.value) }))
    .filter((o): o is { label: string; v: number } => !!o.label && o.v !== null && o.v >= 0)
    .slice(0, 5);
  if (opts.length < 2) return null;
  const sum = opts.reduce((s, o) => s + o.v, 0);
  if (!(sum > 0)) return null;
  const asPct = sum >= 99 && sum <= 101;
  const pct = opts.map((o) => (asPct ? Math.round(o.v * 10) / 10 : Math.round((o.v / sum) * 100)));
  const win = pct.reduce((m, v, i) => (v > pct[m] ? i : m), 0);
  const hl = unquote(clean(overlay.highlight)).toLowerCase();
  const hit = hl ? opts.findIndex((o) => o.label.toLowerCase().includes(hl) || hl.includes(o.label.toLowerCase())) : -1;
  const voted = hit >= 0 ? hit : win;
  const question = unquote(clean(overlay.text, 110));
  const qls = question ? wrap(question, 34, 2) : [];
  const votes = finite(overlay.value);
  const by = clean(overlay.label, 30);
  const n = opts.length;
  const W = 1100 * k, PAD = 48 * k, RH = (n > 4 ? 74 : 82) * k, GAP = 14 * k;
  const TW = W - 2 * PAD;
  const pIn = ramp(frame, 0, T(0.6));
  const rowAt = (i: number) => T(0.5) + qls.length * 3 + i * 4;
  const voteAt = rowAt(n - 1) + T(0.35);
  const fillAt = voteAt + T(0.3);
  const fillF = Math.max(12, T(1.0));
  const tap = interpolate(frame, [voteAt, voteAt + 16], [0, 1], clamp);
  const float = Math.sin((frame / fps) * 1.1) * 4 * k;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ width: W, boxSizing: "border-box", padding: PAD, borderRadius: 28 * k,
          background: "linear-gradient(180deg, rgba(27,28,34,.96) 0%, rgba(16,17,21,.96) 100%)",
          border: `${1.5 * k}px solid rgba(255,255,255,.1)`, boxShadow: `0 ${40 * k}px ${100 * k}px rgba(0,0,0,.55)`,
          opacity: Math.min(1, pIn * 1.6) * (1 - out),
          transform: `translateY(${(1 - pIn) * 60 * k + float + out * 50 * k}px) scale(${0.95 + 0.05 * pIn})` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 16 * k, height: 40 * k }}>
            <span style={{ padding: `${4 * k}px ${14 * k}px`, borderRadius: 10 * k, border: `${2 * k}px solid ${accent}`,
              fontFamily: LABEL, fontWeight: 800, fontSize: 24 * k, letterSpacing: "0.2em", color: accent,
              transform: `scale(${ramp(frame, T(0.12), 14, backOut) * (1 - ramp(frame, end + 2, 8, easeIn))})` }}>POLL</span>
            {by ? (
              <Rise at={T(0.18)} out={end}>
                <span style={{ fontFamily: INTER, fontWeight: 400, fontSize: 26 * k, color: "rgba(255,255,255,.55)", whiteSpace: "nowrap" }}>
                  {by}</span>
              </Rise>
            ) : null}
            <div style={{ flex: 1 }} />
            <Rise at={fillAt + fillF} out={end}>
              <span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 24 * k, letterSpacing: "0.12em",
                color: "rgba(255,255,255,.55)" }}>FINAL RESULTS</span>
            </Rise>
          </div>
          {qls.length ? (
            <div style={{ marginTop: 22 * k }}>
              {qls.map((ln, i) => (
                <Rise key={i} at={T(0.25) + i * 3} out={end + i}>
                  <span style={{ fontFamily: INTER, fontWeight: 800, fontSize: 46 * k, lineHeight: 1.2, color: "#fff",
                    whiteSpace: "pre" }}>{ln}</span>
                </Rise>
              ))}
            </div>
          ) : null}
          <div style={{ marginTop: 30 * k, display: "flex", flexDirection: "column", gap: GAP }}>
            {opts.map((o, i) => {
              const a = rowAt(i);
              const isWin = i === win;
              const isVote = i === voted;
              const g = ramp(frame, fillAt + i * 3, fillF, inOut);
              const share = Math.max(0, Math.min(100, pct[i])) / 100;
              const radio = ramp(frame, a + 2, 12, inOut);
              const dot = isVote ? ramp(frame, voteAt, 10, backOut) : 0;
              return (
                <div key={i} style={{ position: "relative", height: RH, borderRadius: 16 * k, overflow: "hidden",
                  background: "rgba(255,255,255,.06)", transformOrigin: "left",
                  transform: `scaleX(${ramp(frame, a, T(0.45), inOut)})` }}>
                  <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: share * g * TW, borderRadius: 16 * k,
                    overflow: "hidden",
                    background: isWin ? `linear-gradient(90deg, ${rgba(accent, 0.22)} 0%, ${rgba(accent, 0.5)} 100%)` : "rgba(255,255,255,.14)",
                    boxShadow: isWin ? `0 0 ${24 * k}px ${rgba(accent, 0.3)}` : "none" }}>
                    <div style={{ position: "absolute", right: 0, top: 0, bottom: 0, width: 6 * k,
                      background: isWin ? accent : "rgba(255,255,255,.5)", opacity: g > 0.02 ? 1 : 0 }} />
                  </div>
                  <div style={{ position: "absolute", left: 24 * k, right: 24 * k, top: 0, bottom: 0, display: "flex", alignItems: "center",
                    gap: 18 * k }}>
                    <svg width={34 * k} height={34 * k} viewBox="0 0 24 24" style={{ flexShrink: 0, overflow: "visible",
                      opacity: 1 - ramp(frame, fillAt, 10) * (isVote ? 0 : 0.6) }}>
                      <circle cx={12} cy={12} r={10} fill="none" stroke={isVote && dot > 0 ? accent : "rgba(255,255,255,.7)"} strokeWidth={2.2}
                        pathLength={1} strokeDasharray={1} strokeDashoffset={1 - radio} transform="rotate(-90 12 12)" />
                      <circle cx={12} cy={12} r={5.5 * dot} fill={accent} />
                      {isVote && tap > 0 && tap < 1 ? (
                        <circle cx={12} cy={12} r={10 + 12 * tap} fill="none" stroke={accent} strokeWidth={2 * (1 - tap)} opacity={1 - tap} />
                      ) : null}
                    </svg>
                    <Rise at={a + 3} out={end} style={{ minWidth: 0, flex: 1 }}>
                      <span style={{ display: "block", fontFamily: INTER, fontWeight: isWin ? 800 : 700, fontSize: 30 * k,
                        whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: "#fff",
                        textShadow: "0 2px 8px rgba(0,0,0,.35)" }}>{o.label}</span>
                    </Rise>
                    {isWin ? (
                      <div style={{ transform: `scale(${1 - ramp(frame, end + 2, 8, easeIn)})` }}>
                        <Badge size={32 * k} accent={accent} at={fillAt + fillF} />
                      </div>
                    ) : null}
                    <div style={{ minWidth: 130 * k, display: "flex", justifyContent: "flex-end" }}>
                      <Rise at={fillAt + i * 3 - 2} out={end}>
                        <span style={{ display: "inline-flex" }}>
                          <Odometer value={pct[i]} at={fillAt + i * 3} frames={fillF} size={(isWin ? 54 : 46) * k}
                            color={isWin ? "#fff" : "rgba(255,255,255,.8)"} font={DISPLAY} suffix="%" suffixScale={0.6} />
                        </span>
                      </Rise>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
          {votes !== null && votes > 0 ? (
            <div style={{ marginTop: 24 * k, display: "flex", alignItems: "center", gap: 12 * k, height: 40 * k }}>
              <Rise at={fillAt} out={end}>
                <span style={{ display: "inline-flex" }}>
                  <Odometer value={Math.round(votes)} at={fillAt} frames={fillF} size={30 * k} color="#fff" font={INTER} />
                </span>
              </Rise>
              <Rise at={fillAt + 2} out={end}>
                <span style={{ fontFamily: INTER, fontWeight: 400, fontSize: 26 * k, color: "rgba(255,255,255,.55)" }}>votes</span>
              </Rise>
            </div>
          ) : null}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== registry
/** Guards every look: no overlay draws nothing, a missing accent falls back to the house gold. */
const safe = (Inner: Look): Look => {
  const Guarded: Look = ({ overlay, accent }) =>
    overlay && typeof overlay === "object" ? <Inner overlay={overlay} accent={pick(accent)} /> : null;
  return Guarded;
};

export const LOOKS: Record<string, Look> = {
  "ui-social-post": safe(SocialPost),
  "ui-comment-thread": safe(CommentThread),
  "ui-search-bar": safe(SearchBar),
  "ui-notification-stack": safe(NotificationStack),
  "ui-chat-bubbles": safe(ChatBubbles),
  "ui-phone-screen": safe(PhoneScreen),
  "ui-browser-window": safe(BrowserWindow),
  "ui-video-player": safe(VideoPlayer),
  "ui-email-card": safe(EmailCard),
  "ui-poll-results": safe(PollResults),
};
