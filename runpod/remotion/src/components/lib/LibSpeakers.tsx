import React from "react";
import { AbsoluteFill, Audio, Easing, Img, Sequence, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY, INTER, LABEL, SERIF, SERIF_ITALIC } from "../fonts";
import type { Overlay, OverlayItem, SceneMedia } from "../../types";
import { Scrim, lines, ramp, useHold, useK } from "../pro/ProGraphics";

/**
 * Speakers & people (family "sp-"): the quote, portrait and concept cards a
 * GoMotion documentary cuts to when somebody is talking or a plan is laid out.
 *
 *   sp-quote-portrait    own backdrop: the speaker's portrait in a ringed circle on the left, a serif
 *                        quote typing in line by line on the right, name and role beneath
 *   sp-name-tag          (tag) a slim bottom-left bar with the name in bold and the role under it, an
 *                        accent stripe, sliding in from the left for press photos and interviews
 *   sp-two-voices        two portraits facing each other, each with a position and its line, a hairline
 *                        divider drawing between them (no "VS")
 *   sp-statement-card    one bold sentence on a light paper card, the key phrase marked in accent by a
 *                        highlighter sweep, the source under it
 *   sp-checklist         a paper card titled with the text, the items as checkbox rows ticking one by
 *                        one with a small pop each
 *   sp-circle-list       own backdrop: three to five circled words appearing left to right on black,
 *                        connected by dots
 *   sp-network           a hub-and-spoke diagram: the text in the hub, the items on spokes drawing
 *                        out one after another, small photo tiles when media has entries
 *   sp-concept-wave      a sine wave drawing across the frame, three labelled stops lighting up in turn
 *                        as the glow passes them
 *   sp-portrait-quote    a serif italic quote left over dimmed footage, a framed 4:5 portrait turning in
 *                        on the right, name and role under an accent rule
 *
 * Deterministic (no Math.random / Date), 1080p-referenced sizes times k. Every
 * look renders something sensible from its sample props alone and never throws
 * on a missing prop.
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const easeIn = Easing.bezier(0.7, 0, 0.84, 0);
const GOLD = "#d6a83c";
const WHITE = "#ffffff";
const INK = "#1b1f27";
const PAPER = "linear-gradient(172deg, #fbf8f1 0%, #efe9dc 100%)";
const SHADOW = "0 6px 28px rgba(0,0,0,.55)";

// ================================================================== helpers
const str = (s: unknown): string => (typeof s === "string" ? s.trim() : "");
const cap = (s: unknown): string => str(s).toUpperCase();
/** The words without outer quotation marks or doubled spaces. */
const clean = (s?: unknown): string =>
  str(s).replace(/\s+/g, " ").replace(/^["“”'‘’«»]+|["“”'‘’«»]+$/g, "").trim();
const norm = (w: string): string => w.toLowerCase().replace(/[^\p{L}\p{N}']/gu, "");
const words = (s: string): string[] => (s || "").split(/\s+/).filter(Boolean);
const hiSet = (h?: unknown): Set<string> => new Set(words(str(h)).map(norm).filter(Boolean));
/** At most n characters, cut at a word where possible, ending in an ellipsis. */
const clip = (s: string, n: number): string => {
  if (s.length <= n) return s;
  const cut = s.slice(0, Math.max(1, n - 1));
  const sp = cut.lastIndexOf(" ");
  return `${(sp > n * 0.6 ? cut.slice(0, sp) : cut).replace(/[\s,.;:–—-]+$/, "")}…`;
};
/** Word-wrapped, capped lines; the last kept line ends in an ellipsis when words were dropped. */
const wrap = (text: string, chars: number, max: number): string[] => {
  let ls = lines(text, chars);
  if (ls.length > 1 && ls.length <= max) {
    const n = ls.length;
    for (let c = Math.max(6, Math.ceil(text.length / n)); c < chars; c++) {
      const t = lines(text, c);
      if (t.length === n) {
        ls = t;
        break;
      }
    }
  }
  if (ls.length <= max) return ls;
  const out = ls.slice(0, max);
  out[max - 1] = `${out[max - 1].replace(/[,.;:!?…-]+$/, "")}…`;
  return out;
};
/** Lines and size: the text shrinks (never below `floor`) before it is cut to `max` lines. */
const fit = (text: string, size: number, per: number, max: number, floor: number): { ls: string[]; size: number } => {
  let s = size;
  let ls = lines(text, per);
  while (ls.length > max && s * 0.92 >= floor) {
    s *= 0.92;
    ls = lines(text, Math.round((per * size) / s));
  }
  // wrap() balances the lines it keeps (no one-word orphan) and cuts the rest.
  return { size: s, ls: wrap(text, Math.round((per * size) / s), max) };
};
/** Global word index of each line's first word. */
const starts = (ls: string[]): number[] => {
  const out: number[] = [];
  let n = 0;
  for (const l of ls) {
    out.push(n);
    n += words(l).length;
  }
  return out;
};
/**
 * The word indexes to mark: the highlight phrase where it occurs as a run of
 * words, else every word of it wherever it appears.
 */
const hotIndexes = (ws: string[], h?: unknown): Set<number> => {
  const hw = words(str(h)).map(norm).filter(Boolean);
  const out = new Set<number>();
  if (!hw.length) return out;
  const nw = ws.map(norm);
  for (let i = 0; i + hw.length <= nw.length; i++) {
    if (hw.every((w, j) => nw[i + j] === w)) for (let j = 0; j < hw.length; j++) out.add(i + j);
  }
  if (!out.size) {
    const set = new Set(hw);
    nw.forEach((w, i) => { if (set.has(w)) out.add(i); });
  }
  return out;
};
/** A hex colour at an alpha (anything else is returned as it is). */
const alpha = (color: string, a: number): string => {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec((color || "").trim());
  if (!m) return color;
  const h = m[1].length === 3 ? m[1].split("").map((c) => c + c).join("") : m[1];
  const v = parseInt(h, 16);
  return `rgba(${(v >> 16) & 255},${(v >> 8) & 255},${v & 255},${Math.max(0, Math.min(1, a))})`;
};
/** "Russ Schumacher" -> "RS"; nothing usable -> "?" */
const initialsOf = (name: string): string => {
  const parts = words(name).filter((w) => /\p{L}/u.test(w));
  const s = parts.slice(0, 2).map((w) => Array.from(w).find((c) => /\p{L}/u.test(c)) || "").join("").toUpperCase();
  return s || "?";
};

const stillOf = (m: SceneMedia | null | undefined): string => {
  if (!m || typeof m !== "object") return "";
  const s = m.type === "image" ? m.url : m.thumbnail;
  return typeof s === "string" ? s.trim() : "";
};
/** The overlay's pictures as still URLs (a video gives its thumbnail), empty strings kept in place. */
const stillsAt = (ov: Overlay, max: number): string[] => {
  const media: SceneMedia[] = Array.isArray(ov.media) ? ov.media : [];
  return media.slice(0, max).map((m) => stillOf(m));
};
const stills = (ov: Overlay, max: number): string[] => stillsAt(ov, 64).filter((s) => s.length > 0).slice(0, max);

type Row = { label: string; text: string };
/** The rows that carry a label or a text (a numeric value is written out as the text). */
const rowsOf = (ov: Overlay, max: number): Row[] => {
  const items: OverlayItem[] = Array.isArray(ov.items) ? ov.items : [];
  const out: Row[] = [];
  for (const it of items) {
    if (!it || typeof it !== "object") continue;
    const label = str(it.label);
    const text = str(it.text) || (typeof it.value === "number" && Number.isFinite(it.value) ? String(it.value) : "");
    if (!label && !text) continue;
    out.push({ label: label || text, text: label ? text : "" });
    if (out.length >= max) break;
  }
  return out;
};

/** 0 -> 1 over the last `frames` frames (ease-in), for graphics leaving. */
const useExit = (frames = 13): number => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return ramp(frame, durationInFrames - frames, Math.max(1, frames - 2), easeIn);
};

/** A sound file from public/sfx played from frame `at` (never before the graphic, never after it). */
const Sfx: React.FC<{ name: string; at: number; volume?: number }> = ({ name, at, volume = 0.35 }) => {
  const { durationInFrames } = useVideoConfig();
  const from = Math.max(0, Math.round(at));
  if (from >= durationInFrames - 1) return null;
  return (
    <Sequence from={from} layout="none">
      <Audio src={staticFile(`sfx/${name}.mp3`)} volume={volume} />
    </Sequence>
  );
};

/** A line rising out of its mask at `at`, and up out of it again at the end (element i of a stagger). */
const Rise: React.FC<{ at: number; frames?: number; outDelay?: number; style?: React.CSSProperties; children: React.ReactNode }> =
  ({ at, frames = 16, outDelay = 0, style, children }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();
    const pin = ramp(frame, at, frames);
    const pout = ramp(frame, durationInFrames - 14 + Math.max(0, Math.min(5, outDelay)), 9, easeIn);
    return (
      <div style={{ overflow: "hidden", padding: "0.06em 0.02em 0.12em", margin: "-0.06em -0.02em -0.12em", ...style }}>
        <div style={{ transform: `translateY(${((1 - pin) * 115 - pout * 115).toFixed(2)}%)`,
          opacity: pin < 0.01 || pout > 0.99 ? 0 : 1 }}>{children}</div>
      </div>
    );
  };

/** A line of words with the marked ones in a colour. */
const HotLine: React.FC<{ text: string; start: number; hot: Set<number>; color: string }> = ({ text, start, hot, color }) => (
  <>
    {words(text).map((w, i) => (
      <React.Fragment key={i}>
        {i ? " " : ""}
        {hot.has(start + i) ? <span style={{ color }}>{w}</span> : w}
      </React.Fragment>
    ))}
  </>
);

/**
 * A speaker's still (object-fit cover, a slow push) or, with no still, a dark
 * medallion with the initials on the accent, so a portrait look never renders
 * an empty frame.
 */
const Portrait: React.FC<{ src: string; name: string; accent: string; w: number; h: number; radius: number | string; push?: number;
  gray?: boolean }> = ({ src, name, accent, w, h, radius, push = 0.08, gray }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const k = useK();
  const pr = interpolate(frame, [0, Math.max(1, durationInFrames)], [0, 1], clamp);
  const ini = initialsOf(name);
  return (
    <div style={{ width: w, height: h, borderRadius: radius, overflow: "hidden", position: "relative",
      background: "radial-gradient(ellipse at 40% 30%, #2a3140 0%, #12161e 60%, #080a0e 100%)" }}>
      {src ? (
        <Img src={src} style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${(1.04 + push * pr).toFixed(4)})`,
          filter: gray ? "grayscale(1) contrast(1.1)" : "saturate(.95) contrast(1.05)" }} />
      ) : (
        <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
          <div style={{ position: "absolute", inset: 0, background: `radial-gradient(circle at 50% 42%, ${alpha(accent, 0.28)} 0%, rgba(0,0,0,0) 62%)` }} />
          <span style={{ fontFamily: DISPLAY, fontSize: Math.min(w, h) * (ini.length > 1 ? 0.42 : 0.52), lineHeight: 1, color: accent,
            letterSpacing: "0.04em", textShadow: `0 0 ${24 * k}px ${alpha(accent, 0.5)}` }}>{ini}</span>
        </AbsoluteFill>
      )}
      <div style={{ position: "absolute", inset: 0, boxShadow: `inset 0 0 ${60 * k}px rgba(0,0,0,.45)` }} />
    </div>
  );
};

/** A soft dark ground with a fine dot screen and a vignette (the own-backdrop looks). */
const DarkGround: React.FC<{ focus?: string }> = ({ focus = "30% 50%" }) => {
  const k = useK();
  return (
    <AbsoluteFill style={{ background: `radial-gradient(ellipse at ${focus}, #1a2230 0%, #0b0f16 52%, #04060a 100%)`, overflow: "hidden" }}>
      <AbsoluteFill style={{ backgroundImage: "radial-gradient(rgba(170,200,235,.09) 1px, transparent 1.5px)",
        backgroundSize: `${24 * k}px ${24 * k}px` }} />
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${320 * k}px rgba(0,0,0,.7)` }} />
    </AbsoluteFill>
  );
};

// ================================================================== 1. quote portrait
/**
 * Own backdrop. The speaker's photo in a ringed circle on the left (an accent
 * arc turning round it), a big accent quote mark, and the quote typing in line
 * by line in the serif italic with a blinking caret; the name slides out of
 * an accent rule with the role under it once the last line is typed.
 */
const QuotePortrait: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: D, width: VW, height: VH } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit(13);
  const body = clean(overlay.text);
  if (!body) return null;
  const name = clip(cap(clean(overlay.label)) || "SOURCE", 40);
  const role = clip(clean(overlay.subtitle), 60);
  const pic = stills(overlay, 1)[0] || "";
  const n = words(body).length;
  const size0 = n <= 12 ? 58 : n <= 22 ? 50 : 44;
  const per = size0 >= 58 ? 30 : size0 >= 50 ? 36 : 42;
  const ft = fit(body, size0, per, 5, 40);
  const ls = ft.ls;
  const st = starts(ls);
  const hot = hotIndexes(words(body), overlay.highlight);
  const total = ls.reduce((a, l) => a + Array.from(l).length, 0);
  // Every character typed by ~55% of the beat, a caret pause between lines.
  const typeAt = 12;
  const room = Math.max(24, D * 0.55 - typeAt - ls.length * 3);
  const step = Math.max(0.45, Math.min(1.15, room / Math.max(1, total)));
  const lineAt: number[] = [];
  let acc = 0;
  ls.forEach((l, i) => {
    lineAt.push(typeAt + acc * step + i * 3);
    acc += Array.from(l).length;
  });
  const endAt = typeAt + acc * step + ls.length * 3;
  const curLine = ls.findIndex((l, i) => frame < lineAt[i] + Array.from(l).length * step);
  const typing = frame >= typeAt && curLine >= 0;
  const caretOn = typing || Math.floor((frame - endAt) / (fps * 0.5)) % 2 === 0;
  const R = 250 * k;
  const picP = ramp(frame, 2, 22, backOut);
  const ringP = ramp(frame, 4, 26, inOut);
  const markP = ramp(frame, 6, 20, backOut);
  const rule = ramp(frame, endAt + 2, 16);
  const left = 150 * k;
  const cy = (VH / 2);
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <DarkGround focus="28% 50%" />
      <Sfx name="typewriter" at={typeAt} volume={0.28} />
      <AbsoluteFill style={{ transform: `scale(${hold})` }}>
        <div style={{ position: "absolute", left: left + R - R * picP - (exit * 260) * k, top: cy - R * picP,
          width: 2 * R * picP, height: 2 * R * picP, borderRadius: "50%", opacity: (1 - exit) * Math.min(1, picP * 2),
          boxShadow: `0 ${30 * k}px ${80 * k}px rgba(0,0,0,.65)` }}>
          <Portrait src={pic} name={name} accent={accent} w={2 * R * picP} h={2 * R * picP} radius="50%" />
        </div>
        <svg width={2 * R + 60 * k} height={2 * R + 60 * k}
          style={{ position: "absolute", left: left - 30 * k - exit * 260 * k, top: cy - R - 30 * k, overflow: "visible", opacity: 1 - exit }}>
          <circle cx={R + 30 * k} cy={R + 30 * k} r={R + 16 * k} fill="none" stroke="rgba(255,255,255,.18)" strokeWidth={1.5 * k} />
          <circle cx={R + 30 * k} cy={R + 30 * k} r={R + 16 * k} fill="none" stroke={accent} strokeWidth={5 * k} strokeLinecap="round"
            pathLength={1} strokeDasharray="0.62 0.38" strokeDashoffset={1 - ringP * 0.62}
            transform={`rotate(${-90 + frame * 0.35} ${R + 30 * k} ${R + 30 * k})`}
            style={{ filter: `drop-shadow(0 0 ${8 * k}px ${alpha(accent, 0.6)})` }} />
        </svg>
        <div style={{ position: "absolute", left: 770 * k, top: 0, bottom: 0, width: 1010 * k, display: "flex", flexDirection: "column",
          justifyContent: "center" }}>
          <div style={{ fontFamily: SERIF, fontSize: 210 * k, lineHeight: 0.6, color: accent, height: 96 * k, marginLeft: -8 * k,
            opacity: Math.min(1, markP * 2) * (1 - exit), transform: `translateY(${(1 - markP) * 40 * k - exit * 60 * k}px) scale(${0.6 + 0.4 * markP})`,
            transformOrigin: "0 100%" }}>“</div>
          {ls.map((ln, i) => {
            const chars = Array.from(ln);
            const shown = frame < lineAt[i] ? 0 : Math.min(chars.length, Math.floor((frame - lineAt[i]) / step) + 1);
            const wIdx: number[] = [];
            let wi = 0;
            chars.forEach((c) => { if (c === " ") wi += 1; wIdx.push(wi); });
            const drop = ramp(frame, D - 14 + i * 1.2, 9, easeIn);
            return (
              <div key={i} style={{ overflow: "hidden", padding: "0.04em 0 0.16em", margin: "-0.04em 0 -0.16em" }}>
                <div style={{ fontFamily: SERIF_ITALIC, fontWeight: 700, fontSize: ft.size * k, lineHeight: 1.22, color: WHITE, whiteSpace: "pre",
                  textShadow: SHADOW, transform: `translateY(${(-drop * 118).toFixed(2)}%)`, opacity: drop > 0.99 ? 0 : 1 }}>
                  {chars.slice(0, shown).map((c, ci) => (
                    <span key={ci} style={{ color: hot.has(st[i] + wIdx[ci]) ? accent : WHITE }}>{c}</span>
                  ))}
                  {(curLine === i && frame >= typeAt) || (curLine < 0 && i === ls.length - 1 && frame < D - 14) ? (
                    <span style={{ display: "inline-block", width: 5 * k, height: "0.9em", background: accent, verticalAlign: "-0.1em",
                      marginLeft: 4 * k, opacity: caretOn ? 1 : 0 }} />
                  ) : null}
                  {/* the untyped rest keeps its width so the line never re-centres while it types */}
                  {chars.slice(shown).map((c, ci) => (
                    <span key={`h${ci}`} style={{ visibility: "hidden" }}>{c}</span>
                  ))}
                </div>
              </div>
            );
          })}
          <div style={{ display: "flex", alignItems: "center", gap: 22 * k, marginTop: 36 * k }}>
            <div style={{ width: 80 * k, height: 4 * k, flexShrink: 0, background: accent, transformOrigin: "0 50%",
              transform: `scaleX(${Math.max(0, rule * (1 - exit)).toFixed(3)})`, boxShadow: `0 0 ${12 * k}px ${alpha(accent, 0.55)}` }} />
            <div style={{ display: "flex", flexDirection: "column", gap: 2 * k }}>
              <Rise at={endAt + 5}>
                <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 34 * k, letterSpacing: "0.16em", color: WHITE, whiteSpace: "nowrap" }}>{name}</span>
              </Rise>
              {role ? (
                <Rise at={endAt + 10} outDelay={2}>
                  <span style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 26 * k, letterSpacing: "0.05em", color: "rgba(255,255,255,.7)",
                    whiteSpace: "nowrap" }}>{role}</span>
                </Rise>
              ) : null}
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 2. name tag
/**
 * A tag riding on footage: a slim dark bar bottom-left with the name in bold
 * caps and the role under it, an accent stripe on its left edge. It slides in
 * from the left out of a mask, a hairline grows under the name, and it slides
 * back out at the end.
 */
const NameTag: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: D } = useVideoConfig();
  const k = useK();
  const name = clip(cap(clean(overlay.text) || clean(overlay.label)), 34);
  const role = clip(clean(overlay.subtitle), 52);
  if (!name && !role) return null;
  const pin = ramp(frame, 0, 20);
  const pout = ramp(frame, D - 13, 11, easeIn);
  const x = (-(1 - pin) - pout) * 106;
  const line = ramp(frame, 12, 18, inOut) * (1 - pout);
  const stripe = ramp(frame, 4, 14);
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: 100 * k, bottom: 120 * k, overflow: "hidden", paddingRight: 40 * k }}>
        <div style={{ display: "flex", alignItems: "stretch", transform: `translateX(${x.toFixed(2)}%)` }}>
          <div style={{ width: 12 * k, flexShrink: 0, background: accent, transformOrigin: "50% 100%",
            transform: `scaleY(${stripe.toFixed(3)})`, boxShadow: `0 0 ${14 * k}px ${alpha(accent, 0.6)}` }} />
          <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", gap: 4 * k,
            padding: `${14 * k}px ${40 * k}px ${12 * k}px ${26 * k}px`, background: "rgba(8,10,14,.82)",
            backdropFilter: "blur(10px)", WebkitBackdropFilter: "blur(10px)", boxShadow: `0 ${14 * k}px ${40 * k}px rgba(0,0,0,.4)` }}>
            {name ? (
              <Rise at={6}>
                <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 42 * k, lineHeight: 1.05, letterSpacing: "0.08em", color: WHITE,
                  whiteSpace: "nowrap" }}>{name}</span>
              </Rise>
            ) : null}
            <div style={{ height: 2 * k, width: `${(line * 100).toFixed(1)}%`, background: alpha(accent, 0.8) }} />
            {role ? (
              <Rise at={11} outDelay={2}>
                <span style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 26 * k, lineHeight: 1.1, letterSpacing: "0.06em",
                  color: "rgba(255,255,255,.76)", whiteSpace: "nowrap" }}>{role}</span>
              </Rise>
            ) : null}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 3. two voices
/**
 * Two portraits (media[0], media[1]) turned toward each other over the dimmed
 * footage, each with its position (items[i].label) and line (items[i].text)
 * beneath; a hairline divider draws out from a small accent diamond between
 * them. No "VS": the pictures face each other and that is the argument.
 */
const TwoVoices: Look = ({ overlay, accent }) => {
  const { width: VW, height: VH } = useVideoConfig();
  const frame = useCurrentFrame();
  const k = useK();
  const hold = useHold();
  const exit = useExit(13);
  const rows = rowsOf(overlay, 2);
  const pics = stillsAt(overlay, 2);
  const title = clip(cap(clean(overlay.text)), 44);
  if (!rows.length && !pics.some(Boolean)) return null;
  const R = 150 * k;
  const colW = 640 * k;
  const div = ramp(frame, 8, 22, inOut) * (1 - exit);
  const sides = [0, 1].map((i) => {
    const row = rows[i] || { label: "", text: "" };
    const at = 4 + i * 8;
    const p = ramp(frame, at, 22, backOut);
    const dir = i ? 1 : -1;
    const body = wrap(clean(row.text), 28, 3);
    return { row, at, p, dir, body, pic: pics[i] || "" };
  });
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ transform: `scale(${hold})` }}>
        {title ? (
          <div style={{ position: "absolute", left: 0, right: 0, top: 96 * k, display: "flex", justifyContent: "center" }}>
            <Rise at={2}>
              <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k, letterSpacing: "0.26em", color: accent,
                textShadow: SHADOW, whiteSpace: "nowrap" }}>{title}</span>
            </Rise>
          </div>
        ) : null}
        <div style={{ position: "absolute", left: (VW / 2) - 1 * k, top: (VH / 2) - 300 * k * div, width: 2 * k, height: 600 * k * div,
          background: "linear-gradient(to bottom, rgba(255,255,255,0), rgba(255,255,255,.55) 20%, rgba(255,255,255,.55) 80%, rgba(255,255,255,0))" }} />
        <div style={{ position: "absolute", left: (VW / 2) - 9 * k, top: (VH / 2) - 9 * k, width: 18 * k, height: 18 * k, background: accent,
          transform: `rotate(45deg) scale(${ramp(frame, 6, 14, backOut) * (1 - exit)})`, boxShadow: `0 0 ${16 * k}px ${alpha(accent, 0.7)}` }} />
        {sides.map((s, i) => {
          const cx = (i ? 1440 : 480) * k;
          const slide = (1 - s.p) * 140 * s.dir + exit * 200 * s.dir;
          return (
            <div key={i} style={{ position: "absolute", left: cx - colW / 2, top: 0, bottom: 0, width: colW, display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center", perspective: 1400 * k }}>
              <div style={{ width: 2 * R, height: 2 * R, borderRadius: "50%", padding: 6 * k, background: accent, opacity: Math.min(1, s.p * 2) * (1 - exit),
                transform: `translateX(${slide * k}px) rotateY(${(s.dir * -16 * (1 - s.p) + s.dir * -8).toFixed(2)}deg) scale(${(0.7 + 0.3 * s.p).toFixed(3)})`,
                boxShadow: `0 ${24 * k}px ${60 * k}px rgba(0,0,0,.6)` }}>
                <Portrait src={s.pic} name={s.row.label || (i ? "B" : "A")} accent={accent} w={2 * R - 12 * k} h={2 * R - 12 * k} radius="50%" />
              </div>
              <div style={{ marginTop: 28 * k, display: "flex", flexDirection: "column", alignItems: "center", gap: 8 * k }}>
                {s.row.label ? (
                  <Rise at={s.at + 8}>
                    <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 36 * k, letterSpacing: "0.14em", color: WHITE, textShadow: SHADOW,
                      whiteSpace: "nowrap" }}>{clip(cap(s.row.label), 26)}</span>
                  </Rise>
                ) : null}
                {s.body.map((ln, li) => (
                  <Rise key={li} at={s.at + 14 + li * 4} outDelay={li}>
                    <span style={{ fontFamily: INTER, fontWeight: 600, fontSize: 30 * k, lineHeight: 1.25, color: "rgba(255,255,255,.88)",
                      textShadow: SHADOW, whiteSpace: "nowrap", textAlign: "center", display: "block" }}>{ln}</span>
                  </Rise>
                ))}
              </div>
            </div>
          );
        })}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 4. statement card
/**
 * A light paper card settles in over the dimmed footage with one bold sentence
 * rising line by line; then a highlighter sweeps under the key phrase
 * (overlay.highlight) in the accent, word by word; the source sits under an
 * accent dash. The card drops away at the end.
 */
const StatementCard: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit(13);
  const body = clean(overlay.text);
  if (!body) return null;
  const ws = words(body);
  const size0 = ws.length <= 10 ? 56 : ws.length <= 18 ? 50 : 44;
  const ft = fit(body, size0, size0 >= 56 ? 30 : size0 >= 50 ? 34 : 40, 4, 38);
  const st = starts(ft.ls);
  const hot = hotIndexes(ws, overlay.highlight);
  const hotList = Array.from(hot).sort((a, b) => a - b);
  const source = clip(clean(overlay.subtitle) || clean(overlay.label), 70);
  const cardIn = ramp(frame, 0, 20, backOut);
  const lineAt = (i: number) => 6 + i * 5;
  const markAt = lineAt(ft.ls.length) + Math.round(fps * 0.25);
  const W = 1240 * k;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <Sfx name="paper" at={0} volume={0.3} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{ width: W, padding: `${64 * k}px ${76 * k}px ${52 * k}px`, background: PAPER, borderRadius: 6 * k,
          boxShadow: `0 ${34 * k}px ${80 * k}px rgba(0,0,0,.55), 0 ${2 * k}px ${4 * k}px rgba(0,0,0,.25)`,
          opacity: Math.min(1, cardIn * 2) * (1 - exit),
          transform: `translateY(${((1 - cardIn) * 80 + exit * 160) * k}px) rotate(${(-1.6 + 1 * cardIn - exit * 3).toFixed(2)}deg) scale(${(0.94 + 0.06 * cardIn) * hold})` }}>
          <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 10 * k, background: accent, borderRadius: `${6 * k}px 0 0 ${6 * k}px` }} />
          {ft.ls.map((ln, i) => (
            <Rise key={i} at={lineAt(i)} outDelay={i} style={{ marginBottom: 4 * k }}>
              <div style={{ fontFamily: INTER, fontWeight: 800, fontSize: ft.size * k, lineHeight: 1.22, color: INK, letterSpacing: "-0.01em",
                whiteSpace: "nowrap" }}>
                {words(ln).map((w, wi) => {
                  const gi = st[i] + wi;
                  const order = hotList.indexOf(gi);
                  const sweep = order >= 0 ? ramp(frame, markAt + order * 3, 12, inOut) : 0;
                  return (
                    <React.Fragment key={wi}>
                      {wi ? " " : ""}
                      <span style={{ position: "relative", display: "inline-block", padding: `0 ${order >= 0 ? 4 * k : 0}px`,
                        margin: `0 ${order >= 0 ? -4 * k : 0}px` }}>
                        {order >= 0 ? (
                          <span style={{ position: "absolute", left: 0, top: "0.18em", bottom: "0.08em", width: `${(sweep * 100).toFixed(1)}%`,
                            background: alpha(accent, 0.55), borderRadius: 3 * k, transform: "skewX(-6deg)" }} />
                        ) : null}
                        <span style={{ position: "relative" }}>{w}</span>
                      </span>
                    </React.Fragment>
                  );
                })}
              </div>
            </Rise>
          ))}
          {source ? (
            <div style={{ display: "flex", alignItems: "center", gap: 16 * k, marginTop: 30 * k }}>
              <div style={{ width: 44 * k, height: 3 * k, background: accent, transformOrigin: "0 50%",
                transform: `scaleX(${ramp(frame, lineAt(ft.ls.length) + 4, 14).toFixed(3)})` }} />
              <Rise at={lineAt(ft.ls.length) + 6} outDelay={3}>
                <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 26 * k, letterSpacing: "0.18em", color: "#5a5f6a", whiteSpace: "nowrap" }}>
                  {cap(source)}</span>
              </Rise>
            </div>
          ) : null}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 5. checklist
/**
 * A ruled paper card drops onto the frame (a small bounce) titled with the
 * text; the items are checkbox rows that rise in, then tick one by one, each
 * tick a drawn stroke in the accent with a pop, the row's ink darkening. A
 * footer counts them. The card slides away at the end.
 */
const Checklist: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: D } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit(13);
  const rows = rowsOf(overlay, 6);
  const title = clip(cap(clean(overlay.text)), 30);
  if (!rows.length && !title) return null;
  const n = rows.length;
  const drop = spring({ frame, fps, config: { damping: 13, stiffness: 150, mass: 0.8 } });
  const tick0 = Math.round(fps * 0.9);
  const end = D - 18;
  const tickStep = Math.max(6, Math.min(Math.round(fps * 0.5), Math.floor((end - 6 - tick0) / Math.max(1, n))));
  const tickAt = (i: number) => tick0 + i * tickStep;
  const done = rows.reduce((m, _r, i) => m + (frame >= tickAt(i) + 4 ? 1 : 0), 0);
  const BOX = 44 * k;
  const RH = 64 * k;
  const W = 900 * k;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <Sfx name="paper" at={0} volume={0.3} />
      {rows.map((_r, i) => <Sfx key={i} name="pop" at={tickAt(i)} volume={0.28} />)}
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{ width: W, padding: `${46 * k}px ${56 * k}px ${40 * k}px`, borderRadius: 4 * k, position: "relative",
          background: PAPER, boxShadow: `0 ${34 * k}px ${80 * k}px rgba(0,0,0,.55), 0 ${2 * k}px ${4 * k}px rgba(0,0,0,.25)`,
          opacity: Math.min(1, drop * 3) * (1 - exit),
          transform: `translateY(${((1 - drop) * -700 + exit * 900) * k}px) rotate(${(1.2 - 0.6 * drop + exit * 4).toFixed(2)}deg) scale(${hold})` }}>
          <div style={{ position: "absolute", inset: 0, borderRadius: 4 * k, pointerEvents: "none",
            backgroundImage: `repeating-linear-gradient(0deg, rgba(60,80,120,0) 0px, rgba(60,80,120,0) ${RH - 1.5 * k}px, rgba(60,80,120,.16) ${RH - 1.5 * k}px, rgba(60,80,120,.16) ${RH}px)`,
            backgroundPosition: `0 ${(46 + 70) * k}px` }} />
          <div style={{ position: "absolute", left: 40 * k, top: 0, bottom: 0, width: 2 * k, background: "rgba(214,70,70,.35)" }} />
          <div style={{ position: "relative", paddingLeft: 24 * k }}>
            {title ? (
              <div style={{ marginBottom: 18 * k }}>
                <Rise at={4}>
                  <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 46 * k, letterSpacing: "0.16em", color: INK, whiteSpace: "nowrap" }}>{title}</span>
                </Rise>
                <div style={{ width: ramp(frame, 8, 16) * (1 - exit) * 120 * k, height: 5 * k, background: accent, marginTop: 6 * k }} />
              </div>
            ) : null}
            {rows.map((r, i) => {
              const at = 8 + i * 4;
              const t = tickAt(i);
              const check = ramp(frame, t, 11, inOut);
              const bump = ramp(frame, t, 12, backOut);
              const lit = ramp(frame, t, 10);
              const label = clip(r.label, 34);
              return (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 22 * k, height: RH }}>
                  <div style={{ width: BOX, height: BOX, flexShrink: 0, opacity: ramp(frame, at, 12),
                    transform: `scale(${(1 + 0.18 * Math.sin(Math.PI * bump) * (1 - bump * 0.4)).toFixed(3)})` }}>
                    <svg width={BOX} height={BOX} viewBox="0 0 44 44" style={{ overflow: "visible", display: "block" }}>
                      <rect x={3} y={3} width={38} height={38} rx={5} fill="rgba(255,255,255,.55)" stroke={INK} strokeWidth={3}
                        pathLength={1} strokeDasharray={1} strokeDashoffset={1 - ramp(frame, at + 2, 14, inOut)} />
                      <path d="M10 23 L19 32 L36 12" fill="none" stroke={accent} strokeWidth={6} strokeLinecap="round" strokeLinejoin="round"
                        pathLength={1} strokeDasharray={1} strokeDashoffset={1 - check} />
                    </svg>
                  </div>
                  <Rise at={at + 2} outDelay={Math.min(5, i)} style={{ flex: 1, minWidth: 0 }}>
                    <span style={{ display: "block", fontFamily: INTER, fontWeight: 700, fontSize: 34 * k, lineHeight: 1.1,
                      color: `rgba(27,31,39,${(0.5 + 0.5 * lit).toFixed(3)})`, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {label}{r.text ? <span style={{ fontWeight: 500, color: "#5a5f6a", marginLeft: 14 * k, fontSize: 26 * k }}>{clip(r.text, 30)}</span> : null}
                    </span>
                  </Rise>
                </div>
              );
            })}
            {n ? (
              <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 16 * k }}>
                <Rise at={tick0 - 6} outDelay={4}>
                  <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 26 * k, letterSpacing: "0.16em", color: "#5a5f6a", whiteSpace: "nowrap" }}>
                    <span style={{ color: accent }}>{done}</span>/{n} {cap(clean(overlay.label)) || "CHECKED"}</span>
                </Rise>
              </div>
            ) : null}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 6. circle list
/**
 * Own backdrop, black. The words sit in circles left to right: each ring
 * draws on with a pop as the word rises into it, three dots step across to
 * the next. The highlighted word's ring is in the accent; the rest stay white.
 */
const CircleList: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: D, width: VW, height: VH } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit(13);
  const rows = rowsOf(overlay, 6);
  if (!rows.length) return null;
  const n = rows.length;
  const title = clip(cap(clean(overlay.text)), 44);
  const hi = hiSet(overlay.highlight);
  const isHot = (r: Row) => hi.size > 0 && words(r.label).some((w) => hi.has(norm(w)));
  const gap = n > 4 ? 120 * k : 170 * k;
  const R = Math.min(150 * k, (1680 * k - gap * (n - 1)) / (2 * n));
  const totalW = n * 2 * R + (n - 1) * gap;
  const x0 = (VW / 2) - totalW / 2 + R;
  const cy = (VH / 2);
  const at0 = Math.round(fps * 0.3);
  const step = Math.max(8, Math.min(Math.round(fps * 0.7), Math.floor((D * 0.62 - at0) / Math.max(1, n))));
  const atOf = (i: number) => at0 + i * step;
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 50%, #121318 0%, #07070a 55%, #030304 100%)" }} />
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${300 * k}px rgba(0,0,0,.8)` }} />
      {rows.map((_r, i) => <Sfx key={i} name="pop" at={atOf(i)} volume={0.3} />)}
      <AbsoluteFill style={{ transform: `scale(${hold})` }}>
        {title ? (
          <div style={{ position: "absolute", left: 0, right: 0, top: 150 * k, display: "flex", justifyContent: "center" }}>
            <Rise at={2}>
              <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 30 * k, letterSpacing: "0.3em", color: "rgba(255,255,255,.62)",
                whiteSpace: "nowrap" }}>{title}</span>
            </Rise>
          </div>
        ) : null}
        {rows.map((r, i) => {
          const at = atOf(i);
          const cx = x0 + i * (2 * R + gap);
          const draw = ramp(frame, at, 20, inOut);
          const pop = ramp(frame, at, 16, backOut);
          const q = ramp(frame, D - 14 + i * 1, 9, easeIn);
          const hot = isHot(r);
          const col = hot ? accent : WHITE;
          const label = cap(r.label);
          const ls = wrap(label, 12, 2);
          const longest = Math.max(...ls.map((l) => l.length), 1);
          const fs = Math.min(46, Math.max(22, (R * 1.5) / k / (longest * 0.55)));
          return (
            <React.Fragment key={i}>
              <div style={{ position: "absolute", left: cx - R, top: cy - R, width: 2 * R, height: 2 * R, opacity: 1 - q,
                transform: `scale(${(0.6 + 0.4 * pop) * (1 - 0.5 * q)})` }}>
                <svg width={2 * R} height={2 * R} viewBox="0 0 200 200" style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
                  <circle cx={100} cy={100} r={92} fill={hot ? alpha(accent, 0.12) : "rgba(255,255,255,.04)"} />
                  <circle cx={100} cy={100} r={92} fill="none" stroke={col} strokeWidth={4} strokeLinecap="round" pathLength={1}
                    strokeDasharray={1} strokeDashoffset={1 - draw} transform="rotate(-90 100 100)"
                    style={{ filter: hot ? `drop-shadow(0 0 ${8 * k}px ${alpha(accent, 0.7)})` : undefined }} />
                </svg>
                <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", padding: 18 * k }}>
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                    {ls.map((ln, li) => (
                      <Rise key={li} at={at + 4 + li * 3} outDelay={Math.min(5, i)}>
                        <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: fs * k, lineHeight: 1.05, letterSpacing: "0.08em", color: col,
                          whiteSpace: "nowrap", textAlign: "center", display: "block" }}>{ln}</span>
                      </Rise>
                    ))}
                  </div>
                </AbsoluteFill>
              </div>
              {i < n - 1 ? [0, 1, 2].map((d) => {
                const dp = ramp(frame, at + 10 + d * 4, 10, backOut) * (1 - q);
                const dx = cx + R + (gap * (d + 1)) / 4;
                return (
                  <div key={d} style={{ position: "absolute", left: dx - 6 * k, top: cy - 6 * k, width: 12 * k, height: 12 * k, borderRadius: "50%",
                    background: "rgba(255,255,255,.75)", transform: `scale(${dp.toFixed(3)})` }} />
                );
              }) : null}
            </React.Fragment>
          );
        })}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 7. network
/**
 * A hub-and-spoke diagram over the dimmed footage: the text in the hub ring in
 * the centre, the items on nodes around it. A line draws out to each node in
 * turn with a pulse riding it, the node pops (a photo tile when media has an
 * entry for it, else a dark disc with the item's initial), the label rises.
 */
const Network: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: D, width: VW, height: VH } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit(13);
  const rows = rowsOf(overlay, 6);
  const hub = clean(overlay.text) || clean(overlay.label);
  if (!hub && !rows.length) return null;
  const n = rows.length;
  const pics = stillsAt(overlay, 6);
  const cx = (VW / 2), cy = (VH / 2);
  const HR = 130 * k;
  const NR = (n > 4 ? 72 : 86) * k;
  const rx = 560 * k, ry = 330 * k;
  const hubLs = wrap(cap(hub), 12, 2);
  const hubFs = Math.min(44, Math.max(24, 190 / Math.max(...hubLs.map((l) => l.length), 1)));
  const hubP = ramp(frame, 2, 20, backOut);
  const at0 = Math.round(fps * 0.5);
  const step = Math.max(6, Math.min(Math.round(fps * 0.45), Math.floor((D * 0.6 - at0) / Math.max(1, n))));
  const nodes = rows.map((r, i) => {
    const a = -Math.PI / 2 + (i / n) * Math.PI * 2;
    const x = cx + Math.cos(a) * rx, y = cy + Math.sin(a) * ry;
    const at = at0 + i * step;
    const ux = x - cx, uy = y - cy;
    const L = Math.hypot(ux, uy) || 1;
    const sx = cx + (ux / L) * HR, sy = cy + (uy / L) * HR;
    const ex = x - (ux / L) * NR, ey = y - (uy / L) * NR;
    return { r, x, y, at, sx, sy, ex, ey, below: Math.sin(a) > 0.2, pic: pics[i] || "" };
  });
  const vis = 1 - exit;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      {nodes.map((nd, i) => <Sfx key={i} name="pop" at={nd.at + 10} volume={0.26} />)}
      <AbsoluteFill style={{ transform: `scale(${hold})` }}>
        <svg width={VW} height={VH} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          {nodes.map((nd, i) => {
            const d = ramp(frame, nd.at, 16, inOut) * vis;
            const pulse = ramp(frame, nd.at + 4, 16);
            const px = nd.sx + (nd.ex - nd.sx) * Math.min(d, pulse), py = nd.sy + (nd.ey - nd.sy) * Math.min(d, pulse);
            return (
              <g key={i}>
                <line x1={nd.sx} y1={nd.sy} x2={nd.sx + (nd.ex - nd.sx) * d} y2={nd.sy + (nd.ey - nd.sy) * d} stroke="rgba(255,255,255,.55)"
                  strokeWidth={3 * k} strokeLinecap="round" strokeDasharray={`${2 * k} ${10 * k}`} />
                {d > 0 && pulse < 1 ? <circle cx={px} cy={py} r={7 * k} fill={accent} style={{ filter: `drop-shadow(0 0 ${8 * k}px ${accent})` }} /> : null}
              </g>
            );
          })}
        </svg>
        <div style={{ position: "absolute", left: cx - HR, top: cy - HR, width: 2 * HR, height: 2 * HR, borderRadius: "50%",
          background: `radial-gradient(circle at 40% 35%, ${alpha(accent, 0.95)}, ${alpha(accent, 0.7)} 60%, ${alpha(accent, 0.55)})`,
          boxShadow: `0 0 ${50 * k}px ${alpha(accent, 0.45)}, 0 ${20 * k}px ${50 * k}px rgba(0,0,0,.5)`, display: "flex", alignItems: "center",
          justifyContent: "center", flexDirection: "column", opacity: Math.min(1, hubP * 2) * vis,
          transform: `scale(${(0.5 + 0.5 * hubP) * (1 - 0.4 * exit)})` }}>
          <div style={{ position: "absolute", inset: -14 * k, borderRadius: "50%", border: `${2 * k}px solid ${alpha(accent, 0.5)}`,
            transform: `scale(${1 + 0.06 * Math.sin(frame / (fps * 0.4))})` }} />
          {hubLs.map((ln, li) => (
            <Rise key={li} at={6 + li * 3}>
              <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: hubFs * k, lineHeight: 1.05, letterSpacing: "0.1em", color: "#0c0c0f",
                whiteSpace: "nowrap", display: "block", textAlign: "center" }}>{ln}</span>
            </Rise>
          ))}
        </div>
        {nodes.map((nd, i) => {
          const pop = ramp(frame, nd.at + 10, 16, backOut);
          const label = clip(cap(nd.r.label), 22);
          const sub = clip(nd.r.text, 26);
          return (
            <React.Fragment key={i}>
              <div style={{ position: "absolute", left: nd.x - NR, top: nd.y - NR, width: 2 * NR, height: 2 * NR, borderRadius: "50%", padding: 5 * k,
                background: WHITE, opacity: Math.min(1, pop * 2) * vis, transform: `scale(${(0.4 + 0.6 * pop) * (1 - 0.4 * exit)})`,
                boxShadow: `0 ${16 * k}px ${40 * k}px rgba(0,0,0,.55)` }}>
                <Portrait src={nd.pic} name={nd.r.label} accent={accent} w={2 * NR - 10 * k} h={2 * NR - 10 * k} radius="50%" push={0.05} />
              </div>
              <div style={{ position: "absolute", left: nd.x - 200 * k, width: 400 * k, top: nd.below ? nd.y + NR + 14 * k : undefined,
                bottom: nd.below ? undefined : VH - (nd.y - NR) + 14 * k, display: "flex", flexDirection: "column", alignItems: "center", gap: 2 * k }}>
                <Rise at={nd.at + 14} outDelay={Math.min(5, i)}>
                  <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k, letterSpacing: "0.14em", color: WHITE, textShadow: SHADOW,
                    whiteSpace: "nowrap" }}>{label}</span>
                </Rise>
                {sub ? (
                  <Rise at={nd.at + 18} outDelay={Math.min(5, i)}>
                    <span style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 24 * k, letterSpacing: "0.04em", color: "rgba(255,255,255,.72)",
                      textShadow: SHADOW, whiteSpace: "nowrap" }}>{sub}</span>
                  </Rise>
                ) : null}
              </div>
            </React.Fragment>
          );
        })}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 8. concept wave
/**
 * A sine wave draws across the dimmed footage with a glowing head; three
 * stops on it (crest, trough, crest) light up in turn as the head passes,
 * each with its label rising (items[0..2].label, a small line of text under
 * it) and a chevron pointing on to the next. The wave keeps breathing while
 * the card holds and drops out at the end.
 */
const ConceptWave: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: D, width: VW, height: VH } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit(13);
  const rows = rowsOf(overlay, 3);
  if (!rows.length) return null;
  const n = rows.length;
  const title = clip(cap(clean(overlay.text)), 44);
  const X0 = 120 * k, X1 = 1800 * k, CY = 560 * k, A = 130 * k;
  const N = 160;
  // Half a cycle per stop: stop i sits at u = (2i+1)/2n, on a crest, then a trough, then a crest.
  const yAt = (u: number) => CY - A * Math.sin(Math.PI * n * u);
  const wave = (u: number): [number, number] => [X0 + (X1 - X0) * u, yAt(u) + 4 * k * Math.sin(frame / (fps * 0.5) + u * 6)];
  const pts = Array.from({ length: N + 1 }, (_, i) => wave(i / N));
  const d = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
  const drawAt = Math.round(fps * 0.3);
  const drawF = Math.max(20, Math.round(Math.min(fps * 1.8, D * 0.5)));
  const draw = ramp(frame, drawAt, drawF, inOut);
  const head = wave(draw);
  const stopU = (i: number) => (n === 1 ? 0.5 : (2 * i + 1) / (2 * n));
  const vis = 1 - exit;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <Sfx name="whoosh" at={drawAt} volume={0.3} />
      <AbsoluteFill style={{ transform: `scale(${hold})` }}>
        {title ? (
          <div style={{ position: "absolute", left: 120 * k, top: 110 * k }}>
            <Rise at={2}>
              <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 32 * k, letterSpacing: "0.24em", color: accent, textShadow: SHADOW,
                whiteSpace: "nowrap" }}>{title}</span>
            </Rise>
            <div style={{ width: ramp(frame, 6, 16) * vis * 100 * k, height: 4 * k, background: accent, marginTop: 8 * k }} />
          </div>
        ) : null}
        <svg width={VW} height={VH} style={{ position: "absolute", left: 0, top: 0, overflow: "visible", opacity: vis }}>
          <path d={d} fill="none" stroke="rgba(255,255,255,.14)" strokeWidth={2 * k} strokeDasharray={`${4 * k} ${10 * k}`} />
          <path d={d} fill="none" stroke={alpha(accent, 0.25)} strokeWidth={18 * k} strokeLinecap="round" pathLength={1} strokeDasharray={1}
            strokeDashoffset={1 - draw} />
          <path d={d} fill="none" stroke={accent} strokeWidth={5 * k} strokeLinecap="round" pathLength={1} strokeDasharray={1}
            strokeDashoffset={1 - draw} />
          {draw > 0 && draw < 1 ? (
            <circle cx={head[0]} cy={head[1]} r={12 * k} fill={WHITE} style={{ filter: `drop-shadow(0 0 ${14 * k}px ${accent})` }} />
          ) : null}
          {rows.map((_r, i) => {
            const u = stopU(i);
            const p = wave(u);
            const litAt = drawAt + Math.round(drawF * u);
            const lit = ramp(frame, litAt, 14, backOut);
            const ring = ramp(frame, litAt, 22);
            return (
              <g key={i}>
                <circle cx={p[0]} cy={p[1]} r={16 * k} fill="none" stroke="rgba(255,255,255,.5)" strokeWidth={2 * k} />
                {ring > 0 && ring < 1 ? (
                  <circle cx={p[0]} cy={p[1]} r={(18 + 60 * ring) * k} fill="none" stroke={accent} strokeWidth={3 * k} opacity={1 - ring} />
                ) : null}
                <circle cx={p[0]} cy={p[1]} r={(8 + 8 * lit) * k} fill={lit > 0 ? accent : "rgba(255,255,255,.35)"} stroke={WHITE}
                  strokeWidth={3 * k * lit} style={{ filter: lit > 0 ? `drop-shadow(0 0 ${10 * k}px ${accent})` : undefined }} />
              </g>
            );
          })}
        </svg>
        {rows.map((r, i) => {
          const u = stopU(i);
          const p = wave(u);
          const up = yAt(u) <= CY;
          const litAt = drawAt + Math.round(drawF * u);
          const label = clip(cap(r.label), 24);
          const sub = clip(r.text, 34);
          const next = i < n - 1 ? ramp(frame, drawAt + Math.round(drawF * (u + stopU(i + 1)) / 2), 12, backOut) * vis : 0;
          return (
            <React.Fragment key={i}>
              <div style={{ position: "absolute", left: p[0] - 260 * k, width: 520 * k, top: up ? undefined : p[1] + 34 * k,
                bottom: up ? VH - p[1] + 34 * k : undefined, display: "flex", flexDirection: up ? "column-reverse" : "column",
                alignItems: "center", gap: 6 * k }}>
                <Rise at={litAt + 2} outDelay={i * 2}>
                  <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 38 * k, letterSpacing: "0.14em", color: WHITE, textShadow: SHADOW,
                    whiteSpace: "nowrap" }}>{label}</span>
                </Rise>
                {sub ? (
                  <Rise at={litAt + 7} outDelay={i * 2}>
                    <span style={{ fontFamily: INTER, fontWeight: 600, fontSize: 24 * k, color: "rgba(255,255,255,.72)", textShadow: SHADOW,
                      whiteSpace: "nowrap" }}>{sub}</span>
                  </Rise>
                ) : null}
              </div>
              {i < n - 1 ? (
                <svg width={44 * k} height={44 * k} viewBox="0 0 44 44"
                  style={{ position: "absolute", left: (p[0] + wave(stopU(i + 1))[0]) / 2 - 22 * k, top: CY - 22 * k, overflow: "visible",
                    opacity: Math.min(1, next), transform: `translateX(${(1 - next) * -20 * k}px)`,
                    filter: `drop-shadow(0 0 ${8 * k}px ${alpha(accent, 0.6)})` }}>
                  <circle cx={22} cy={22} r={20} fill="#0c0c0f" stroke={accent} strokeWidth={3} />
                  <path d="M17 12 L28 22 L17 32" fill="none" stroke={accent} strokeWidth={4} strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              ) : null}
            </React.Fragment>
          );
        })}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 9. portrait quote
/**
 * The quote card with the speaker's portrait (GoMotion): the footage darkens
 * more on the left, where an accent opening mark and the serif italic quote
 * rise line by line with the key words in the accent; the name rises out of
 * an accent rule with the role under it. On the right a 4:5 framed portrait
 * slides in with a 3D turn and a gloss sweep; with no still it shows a dark
 * medallion with the speaker's initials. The lines drop and the frame slides
 * out right at the end.
 */
const PortraitQuote: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: D, width: VW, height: VH } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit(13);
  const body = clean(overlay.text);
  if (!body) return null;
  const name = clip(cap(clean(overlay.label)) || "SOURCE", 40);
  const role = clip(clean(overlay.subtitle), 60);
  const pic = stills(overlay, 1)[0] || "";
  const ft = fit(body, 54, 34, 4, 44);
  const st = starts(ft.ls);
  const hot = hotIndexes(words(body), overlay.highlight);
  const lineAt = (i: number) => 8 + i * 5;
  const endAt = lineAt(ft.ls.length) + 4;
  const rule = ramp(frame, endAt, 16);
  const markP = ramp(frame, 2, 20, backOut);
  const shade = ramp(frame, 0, 12) * (1 - ramp(frame, D - 10, 9, easeIn));
  const fIn = ramp(frame, 4, 24);
  const fOut = ramp(frame, D - 13, 11, easeIn);
  const FW = 460 * k, FH = FW * 1.25;
  const fx = VW - 140 * k - FW;
  const fy = (VH / 2) - FH / 2;
  const gloss = interpolate(frame, [14, 44], [-60, 160], clamp);
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: shade, background: "linear-gradient(90deg, rgba(0,0,0,.72) 0%, rgba(0,0,0,.55) 50%, rgba(0,0,0,.35) 100%)" }} />
      <AbsoluteFill style={{ transform: `scale(${hold})` }}>
        <div style={{ position: "absolute", left: 120 * k, top: 0, bottom: 0, width: 1100 * k, display: "flex", flexDirection: "column",
          justifyContent: "center" }}>
          <div style={{ fontFamily: SERIF_ITALIC, fontWeight: 700, fontSize: 140 * k, lineHeight: 0.7, height: 70 * k, color: accent,
            opacity: 0.35 * Math.min(1, markP * 2) * (1 - exit), transform: `translateY(${(1 - markP) * 30 * k - exit * 40 * k}px)` }}>“</div>
          {ft.ls.map((ln, i) => (
            <Rise key={i} at={lineAt(i)} outDelay={i}>
              <span style={{ fontFamily: SERIF_ITALIC, fontWeight: 700, fontSize: ft.size * k, lineHeight: 1.22, color: WHITE, whiteSpace: "nowrap",
                textShadow: SHADOW, display: "block" }}>
                <HotLine text={ln} start={st[i]} hot={hot} color={accent} />
              </span>
            </Rise>
          ))}
          <div style={{ display: "flex", alignItems: "center", gap: 20 * k, marginTop: 30 * k }}>
            <div style={{ width: 70 * k, height: 4 * k, flexShrink: 0, background: accent, transformOrigin: "0 50%",
              transform: `scaleX(${Math.max(0, rule * (1 - exit)).toFixed(3)})`, boxShadow: `0 0 ${12 * k}px ${alpha(accent, 0.55)}` }} />
            <div style={{ display: "flex", flexDirection: "column", gap: 2 * k }}>
              <Rise at={endAt + 4} outDelay={3}>
                <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k, letterSpacing: "0.16em", color: WHITE, whiteSpace: "nowrap" }}>{name}</span>
              </Rise>
              {role ? (
                <Rise at={endAt + 9} outDelay={4}>
                  <span style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 24 * k, letterSpacing: "0.05em", color: "rgba(255,255,255,.75)",
                    whiteSpace: "nowrap" }}>{role}</span>
                </Rise>
              ) : null}
            </div>
          </div>
        </div>
        <div style={{ position: "absolute", left: fx, top: fy, width: FW, height: FH, perspective: 1400 * k }}>
          <div style={{ width: "100%", height: "100%", border: `${6 * k}px solid ${WHITE}`, boxSizing: "border-box", overflow: "hidden", position: "relative",
            boxShadow: `0 ${24 * k}px ${60 * k}px rgba(0,0,0,.6)`, background: "#0b0d12",
            opacity: Math.min(1, fIn * 3) * (1 - fOut),
            transform: `translateX(${((1 - fIn) * 520 + fOut * 620) * k}px) rotateY(${(18 * (1 - fIn) - 12 * fOut).toFixed(2)}deg)`,
            transformOrigin: "100% 50%" }}>
            <Portrait src={pic} name={name} accent={accent} w={FW - 12 * k} h={FH - 12 * k} radius={0} push={0.07} />
            <div style={{ position: "absolute", inset: 0, pointerEvents: "none",
              background: `linear-gradient(115deg, rgba(255,255,255,0) ${gloss - 18}%, rgba(255,255,255,.28) ${gloss}%, rgba(255,255,255,0) ${gloss + 18}%)` }} />
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== registry
/** Guards every look: no overlay draws nothing, a missing accent falls back to the house gold. */
const safe = (Inner: Look): Look => {
  const Guarded: Look = ({ overlay, accent }) =>
    overlay && typeof overlay === "object" ? <Inner overlay={overlay} accent={accent || GOLD} /> : null;
  return Guarded;
};

export const LOOKS: Record<string, Look> = {
  "sp-quote-portrait": safe(QuotePortrait),
  "sp-name-tag": safe(NameTag),
  "sp-two-voices": safe(TwoVoices),
  "sp-statement-card": safe(StatementCard),
  "sp-checklist": safe(Checklist),
  "sp-circle-list": safe(CircleList),
  "sp-network": safe(Network),
  "sp-concept-wave": safe(ConceptWave),
  "sp-portrait-quote": safe(PortraitQuote),
};
