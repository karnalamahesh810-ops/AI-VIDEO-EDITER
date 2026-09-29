import React from "react";
import { AbsoluteFill, Easing, Img, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { INTER, LABEL, SERIF, TYPEWRITER } from "../fonts";
import type { Overlay, SceneMedia } from "../../types";
import { lines, ramp, useK } from "../pro/ProGraphics";

/**
 * Person introductions (family "pf-"): a full-screen card for the moment a
 * named person enters the story. Props: text = the name, subtitle = the role
 * (optional: every look is composed to stand without it), label = a short
 * kicker such as "WHO IS", media[0] = a portrait still. With no picture the
 * portrait becomes an initials medallion in the accent.
 *
 *   pf-profile     a blurred copy of the portrait fills the frame; the framed
 *                  portrait slides in on the left, the name large on the right
 *                  over accent bars, the role beneath
 *   pf-dossier     a file folder slides up; the portrait is paper-clipped to
 *                  the sheet and the name is TYPED letter by letter (the house
 *                  typing contract below), the role filled in after it
 *   pf-split-name  the portrait fills the right half in a duotone; the name in
 *                  big clean type on the left with a line drawing under it
 *   pf-spotlight   a dark stage: a spotlight hits the portrait, the name below
 *                  with a thin accent underline drawing out from its centre
 *   pf-magazine    a magazine cover: the portrait full-bleed, the name as the
 *                  masthead, the role as the cover line
 *
 * Typing contract (shared with the sound planner): typing starts at frame
 * TYPE_START = 6 and reveals one character every FRAMES_PER_CHAR frames at
 * 30 fps (2 when the text has <= 48 characters, else 1), with a caret while
 * it types, so it ends at 6 + FRAMES_PER_CHAR * len(text).
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const expoOut = Easing.bezier(0.16, 1, 0.3, 1);
const expoIn = Easing.bezier(0.7, 0, 0.84, 0);
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const drift = Easing.bezier(0.33, 0, 0.45, 1);
const SHADOW = "0 6px 30px rgba(0,0,0,.5)";

export const TYPE_START = 6;
export const framesPerChar = (n: number) => (n <= 48 ? 2 : 1);

// ------------------------------------------------------------------ helpers
const str = (s: unknown): string => (typeof s === "string" ? s.replace(/\s+/g, " ").trim() : "");
const cap = (s: unknown): string => str(s).toUpperCase();
const clamp01 = (v: number) => Math.max(0, Math.min(1, Number.isFinite(v) ? v : 0));

const stillOf = (m: SceneMedia | null | undefined): string => {
  if (!m || typeof m !== "object") return "";
  const s = m.type === "image" ? m.url : m.thumbnail;
  return typeof s === "string" ? s.trim() : "";
};
/** The portrait as a still URL (a video lends its thumbnail); "" when there is none. */
const portraitOf = (ov: Overlay): string => {
  const media: SceneMedia[] = Array.isArray(ov.media) ? ov.media : [];
  for (const m of media) {
    const s = stillOf(m);
    if (s) return s;
  }
  return "";
};

type RGB = [number, number, number];
const toRgb = (c: string): RGB => {
  const s = (c || "").trim().replace(/^#/, "");
  let hex = "";
  if (/^[0-9a-f]{6}$/i.test(s)) hex = s;
  else if (/^[0-9a-f]{3}$/i.test(s)) hex = s.split("").map((x) => x + x).join("");
  const m = /^rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)/i.exec((c || "").trim());
  if (!hex && m) return [Number(m[1]), Number(m[2]), Number(m[3])];
  const n = hex ? parseInt(hex, 16) : 0xd6a83c;
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
const mix = (a: string, b: string, t: number) => {
  const x = toRgb(a), y = toRgb(b);
  const f = (i: number) => Math.round(x[i] + (y[i] - x[i]) * clamp01(t));
  return `rgb(${f(0)},${f(1)},${f(2)})`;
};
const rgba = (c: string, a: number) => {
  const [r, g, b] = toRgb(c);
  return `rgba(${r},${g},${b},${a})`;
};
const luma = (c: string) => {
  const [r, g, b] = toRgb(c);
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
};
/** The accent as a colour that reads on a dark ground (a navy accent is lifted toward white, a red only a touch). */
const readable = (accent: string) => {
  const l = luma(accent);
  return l < 0.2 ? mix(accent, "#ffffff", 0.55) : l < 0.3 ? mix(accent, "#ffffff", 0.16) : accent;
};

/** Re-wrap `ls` into the same number of lines, as even in length as the room allows (no orphan last word). */
const balance = (t: string, ls: string[], per: number): string[] => {
  if (ls.length < 2) return ls;
  for (let p = Math.ceil(t.length / ls.length); p < per; p++) {
    const b = lines(t, p);
    if (b.length <= ls.length && b.every((l) => l.length <= per)) return b;
  }
  return ls;
};

/** The largest size at which `text` wraps into at most `maxLines` lines `room` px wide (1080p px). */
const fitLines = (text: string, room: number, sizes: number[], em: number, maxLines: number): { size: number; ls: string[] } => {
  const t = str(text);
  const last = sizes[sizes.length - 1];
  if (!t) return { size: last, ls: [] };
  for (const s of sizes) {
    const per = Math.max(4, Math.floor(room / (em * s)));
    const ls = lines(t, per);
    if (ls.length <= maxLines && ls.every((l) => l.length <= per)) return { size: s, ls: balance(t, ls, per) };
  }
  const per = Math.max(4, Math.floor(room / (em * last)));
  const words = t.split(" ").flatMap((w) => (w.length > per ? (w.match(new RegExp(`.{1,${per - 1}}`, "g")) || [w]) : [w]));
  let ls = lines(words.join(" "), per);
  if (ls.length > maxLines) {
    ls = ls.slice(0, maxLines);
    const l = ls[maxLines - 1];
    ls[maxLines - 1] = `${l.length > per - 1 ? l.slice(0, per - 1).trimEnd() : l}…`;
  }
  return { size: last, ls };
};
/** Name sizes: up to 140 px for a name of four words or fewer, headline sizes for anything longer. */
const nameSizes = (name: string, big: number[]) =>
  str(name).split(" ").filter(Boolean).length <= 4 ? big : big.filter((s) => s <= 96).concat([64]);

const useOut = (frames = 12) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return ramp(frame, Math.max(0, durationInFrames - frames - 1), frames, expoIn);
};
const useDrift = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return interpolate(frame, [0, Math.max(1, durationInFrames)], [0, 1], { ...clamp, easing: drift });
};

const Rise: React.FC<{ at: number; q: number; children: React.ReactNode; style?: React.CSSProperties; frames?: number }> =
  ({ at, q, children, style, frames = 16 }) => {
    const frame = useCurrentFrame();
    const p = ramp(frame, at, frames);
    return (
      <div style={{ overflow: "hidden", paddingBottom: "0.14em", marginBottom: "-0.14em", ...style }}>
        <div style={{ transform: `translateY(${((1 - p) * 112 + q * 112).toFixed(2)}%)`, opacity: p > 0.002 ? 1 : 0 }}>{children}</div>
      </div>
    );
  };

const Photo: React.FC<{ src: string; style?: React.CSSProperties }> = ({ src, style }) => (
  <Img src={src} style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "100%", objectFit: "cover",
    objectPosition: "50% 28%", ...style }} />
);

const HONORIFIC = /^(dr|mr|mrs|ms|miss|sir|dame|prof|gen|col|capt|sen|rep|gov|rev|lt|sgt|hon|president|judge|justice)\.?$/i;
const initials = (name: string): string => {
  const words = str(name).split(" ").filter((w) => /[A-Za-z0-9]/.test(w) && !HONORIFIC.test(w));
  if (!words.length) return "•";
  const first = words[0].replace(/[^A-Za-z0-9]/g, "").charAt(0);
  const last = words.length > 1 ? words[words.length - 1].replace(/[^A-Za-z0-9]/g, "").charAt(0) : "";
  return `${first}${last}`.toUpperCase() || "•";
};

/** The initials medallion standing in for a missing portrait. */
const Medallion: React.FC<{ name: string; size: number; accent: string }> = ({ name, size, accent }) => (
  <div style={{ width: size, height: size, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center",
    background: `radial-gradient(circle at 34% 28%, ${mix(accent, "#ffffff", 0.3)} 0%, ${accent} 46%, ${mix(accent, "#000000", 0.5)} 100%)`,
    boxShadow: `0 ${size * 0.06}px ${size * 0.18}px rgba(0,0,0,.5), inset 0 0 0 ${size * 0.02}px rgba(255,255,255,.28)` }}>
    <span style={{ fontFamily: INTER, fontWeight: 800, fontSize: size * 0.36, letterSpacing: "-0.02em",
      color: luma(accent) > 0.62 ? "#111" : "#fff" }}>{initials(name)}</span>
  </div>
);

/** A portrait box: the picture when there is one, else a dark accent panel with the medallion. */
const PortraitBox: React.FC<{ src: string; name: string; w: number; h: number; accent: string; style?: React.CSSProperties;
  imgStyle?: React.CSSProperties }> = ({ src, name, w, h, accent, style, imgStyle }) => (
  <div style={{ position: "relative", width: w, height: h, overflow: "hidden", ...style }}>
    {src ? (
      <Photo src={src} style={imgStyle} />
    ) : (
      <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center",
        background: `linear-gradient(160deg, ${mix(accent, "#10131a", 0.72)} 0%, #0b0d12 100%)` }}>
        <Medallion name={name} size={Math.min(w, h) * 0.62} accent={accent} />
      </div>
    )}
  </div>
);

/** A duotone SVG filter: luminance mapped from `dark` to `light`. */
const DuoFilter: React.FC<{ id: string; dark: string; light: string }> = ({ id, dark, light }) => {
  const d = toRgb(dark).map((v) => (v / 255).toFixed(3));
  const l = toRgb(light).map((v) => (v / 255).toFixed(3));
  return (
    <svg width={0} height={0} style={{ position: "absolute" }}>
      <filter id={id} colorInterpolationFilters="sRGB">
        <feColorMatrix type="matrix" values=".2126 .7152 .0722 0 0  .2126 .7152 .0722 0 0  .2126 .7152 .0722 0 0  0 0 0 1 0" />
        <feComponentTransfer>
          <feFuncR type="table" tableValues={`${d[0]} ${l[0]}`} />
          <feFuncG type="table" tableValues={`${d[1]} ${l[1]}`} />
          <feFuncB type="table" tableValues={`${d[2]} ${l[2]}`} />
        </feComponentTransfer>
      </filter>
    </svg>
  );
};

/** The kicker: an accent dash and letter-spaced caps. */
const Kicker: React.FC<{ text: string; at: number; q: number; color: string; size?: number; center?: boolean }> =
  ({ text, at, q, color, size = 30, center }) => {
    const frame = useCurrentFrame();
    const k = useK();
    if (!text) return null;
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 16 * k, justifyContent: center ? "center" : "flex-start" }}>
        {!center ? <div style={{ width: 40 * k * ramp(frame, at - 2, 14, inOut) * (1 - q), height: 4 * k, background: color }} /> : null}
        <Rise at={at} q={q}>
          <div style={{ fontFamily: LABEL, fontWeight: 700, fontSize: size * k, letterSpacing: "0.3em", color, whiteSpace: "nowrap" }}>
            {text.slice(0, 40)}
          </div>
        </Rise>
      </div>
    );
  };

// ================================================================== pf-profile
// The portrait slides in over 4 -> 20, landing at ~13 (sfx_at 13); the name rises from 12.
const Profile: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const q = useOut();
  const d = useDrift();
  const src = portraitOf(overlay);
  const name = str(overlay.text);
  const role = str(overlay.subtitle);
  const kick = cap(overlay.label);
  const acc = readable(accent);
  const e = ramp(frame, 4, 16, expoOut);
  const bar = ramp(frame, 6, 18, inOut);
  const fit = fitLines(cap(name), 960, nameSizes(name, [140, 128, 116, 104, 96, 88, 80, 72]), 0.5, 3);
  const roleFit = fitLines(role, 940, [46, 42, 40], 0.5, 2);
  const lineDraw = ramp(frame, 22, 20, inOut) * (1 - q);
  const PW = 560 * k, PH = 700 * k;
  return (
    <AbsoluteFill style={{ background: "#07090d", overflow: "hidden" }}>
      {src ? (
        <AbsoluteFill style={{ transform: `scale(${1.25 + 0.05 * d})`, opacity: ramp(frame, 0, 12) }}>
          <Photo src={src} style={{ filter: `blur(${38 * k}px) brightness(.4) saturate(.75)` }} />
        </AbsoluteFill>
      ) : (
        <AbsoluteFill style={{ background: `radial-gradient(ellipse at 24% 42%, ${mix(accent, "#0b0e14", 0.78)} 0%, #07090d 70%)` }} />
      )}
      <AbsoluteFill style={{ background: "linear-gradient(90deg, rgba(7,9,13,.35) 0%, rgba(7,9,13,.7) 45%, rgba(7,9,13,.88) 100%)" }} />
      <div style={{ position: "absolute", left: 150 * k, top: `calc(50% - ${PH / 2}px)`, width: PW, height: PH,
        opacity: e * (1 - q), transform: `translateX(${((1 - e) * -90 * k - q * 60 * k).toFixed(2)}px)` }}>
        <PortraitBox src={src} name={name} w={PW} h={PH} accent={accent}
          style={{ boxShadow: `0 ${40 * k}px ${90 * k}px rgba(0,0,0,.6), 0 0 0 ${Math.max(1, k)}px rgba(255,255,255,.18)`,
            clipPath: `inset(0 0 ${((1 - e) * 100).toFixed(2)}% 0)` }}
          imgStyle={{ transform: `scale(${1.16 - 0.1 * e + 0.04 * d})` }} />
        <div style={{ position: "absolute", left: -22 * k, top: 0, width: 10 * k, height: PH * bar, background: acc,
          boxShadow: `0 0 ${18 * k}px ${rgba(accent, 0.5)}` }} />
      </div>
      <div style={{ position: "absolute", left: 830 * k, right: 110 * k, top: 0, bottom: 0, display: "flex", flexDirection: "column",
        justifyContent: "center" }}>
        <Kicker text={kick} at={10} q={q} color={acc} />
        <div style={{ marginTop: kick ? 18 * k : 0 }}>
          {fit.ls.map((ln, i) => (
            <Rise key={i} at={12 + i * 4} q={q}>
              <div style={{ fontFamily: LABEL, fontWeight: 800, fontSize: fit.size * k, letterSpacing: "0.01em", lineHeight: 0.98, color: "#fff",
                whiteSpace: "nowrap", textShadow: SHADOW }}>{ln}</div>
            </Rise>
          ))}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 18 * k, margin: `${26 * k}px 0 ${24 * k}px` }}>
          <div style={{ width: 84 * k * lineDraw, height: 8 * k, background: acc }} />
          <div style={{ flex: 1, height: 2 * k, background: "rgba(255,255,255,.3)", transform: `scaleX(${lineDraw})`, transformOrigin: "0 50%" }} />
        </div>
        {roleFit.ls.map((ln, i) => (
          <Rise key={i} at={26 + i * 3} q={q}>
            <div style={{ fontFamily: INTER, fontWeight: 400, fontSize: roleFit.size * k, lineHeight: 1.22, color: "rgba(255,255,255,.86)",
              whiteSpace: "nowrap", textShadow: SHADOW }}>{ln}</div>
          </Rise>
        ))}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== pf-dossier
const PaperClip: React.FC<{ w: number; h: number }> = ({ w, h }) => (
  <svg width={w} height={h} viewBox="0 0 30 90" style={{ display: "block", overflow: "visible" }}>
    <path d="M9 60 V16 a7 7 0 0 1 14 0 V70 a11 11 0 0 1 -22 0 V24" fill="none" stroke="#b9bec6" strokeWidth={3.4} strokeLinecap="round" />
    <path d="M9 60 V16 a7 7 0 0 1 14 0 V70 a11 11 0 0 1 -22 0 V24" fill="none" stroke="rgba(255,255,255,.55)" strokeWidth={1.2}
      strokeLinecap="round" transform="translate(-0.8,-0.8)" />
  </svg>
);

// The folder is up by frame ~8; the name types from frame 6 (the typing contract; sfx "keys" over the span, sfx_at 6).
const Dossier: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H } = useVideoConfig();
  const k = useK();
  const q = useOut();
  const src = portraitOf(overlay);
  const raw = typeof overlay.text === "string" ? overlay.text.trim() : "";
  const name = str(raw);
  const role = str(overlay.subtitle);
  const kick = cap(overlay.label) || "SUBJECT FILE";
  const total = Array.from(raw).length;
  const fpc = framesPerChar(total);
  const shown = frame < TYPE_START ? 0 : Math.min(total, Math.floor((frame - TYPE_START) / fpc) + 1);
  const typingEnd = TYPE_START + fpc * total;
  // The caret blinks (8 frames on, 8 off) while the name types, and for a moment after it.
  const caretOn = frame < typingEnd + 24 && Math.floor(frame / 8) % 2 === 0;
  const fit = fitLines(name.toUpperCase(), 820, [64, 58, 52, 46, 40], 0.6, 3);
  // Reveal the typed characters across the wrapped lines in reading order.
  let left = shown;
  const typedLines = fit.ls.map((ln, i) => {
    const n = Array.from(ln).length + (i < fit.ls.length - 1 ? 1 : 0);
    const take = Math.max(0, Math.min(n, left));
    left -= take;
    return Array.from(ln).slice(0, take).join("");
  });
  const caretLine = Math.max(0, typedLines.reduce((acc, t, i) => (t.length ? i : acc), 0));
  const roleFit = fitLines(role, 820, [38, 34, 32], 0.6, 2);
  const roleIn = ramp(frame, typingEnd + 2, 12);
  const e = ramp(frame, 0, 10, expoOut);
  const FW = 1560 * k, FH = 900 * k;
  const PW = 400 * k, PH = 500 * k;
  const hl = ramp(frame, typingEnd, 12, inOut);
  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 40% 30%, #3a3026 0%, #1c1712 55%, #0a0806 100%)", overflow: "hidden" }}>
      <div style={{ position: "absolute", left: (W - FW) / 2, top: (H - FH) / 2 + 20 * k, width: FW, height: FH,
        transform: `translateY(${((1 - e) * 160 * k + q * 120 * k).toFixed(2)}px) rotate(${(-1.4 - 2.6 * (1 - e)).toFixed(3)}deg)`,
        opacity: ramp(frame, 0, 4) * (1 - q) }}>
        <div style={{ position: "absolute", left: 40 * k, top: -46 * k, width: 320 * k, height: 70 * k, borderRadius: `${12 * k}px ${12 * k}px 0 0`,
          background: "#c49f60", display: "flex", alignItems: "flex-start", padding: `${12 * k}px ${22 * k}px`, boxSizing: "border-box" }}>
          <span style={{ fontFamily: TYPEWRITER, fontWeight: 700, fontSize: 28 * k, letterSpacing: "0.12em", color: "#4a3a22" }}>FILE</span>
        </div>
        <div style={{ position: "absolute", inset: 0, borderRadius: 10 * k, background: "linear-gradient(170deg, #d4ae6c 0%, #c29c5c 100%)",
          boxShadow: `0 ${40 * k}px ${90 * k}px rgba(0,0,0,.6)` }} />
        <div style={{ position: "absolute", left: 40 * k, top: 34 * k, right: 40 * k, bottom: 30 * k, background: "#f4efe3",
          boxShadow: "0 6px 18px rgba(0,0,0,.25)", borderRadius: 3 * k,
          backgroundImage: `repeating-linear-gradient(180deg, rgba(0,0,0,0) 0px, rgba(0,0,0,0) ${47 * k}px, rgba(60,90,140,.1) ${47 * k}px, rgba(60,90,140,.1) ${48.5 * k}px)` }}>
          <div style={{ position: "absolute", left: 60 * k, right: 60 * k, top: 44 * k, display: "flex", justifyContent: "space-between",
            alignItems: "center", borderBottom: `${2 * k}px solid #2b2620`, paddingBottom: 12 * k }}>
            <span style={{ fontFamily: TYPEWRITER, fontWeight: 700, fontSize: 32 * k, letterSpacing: "0.22em", color: "#2b2620" }}>{kick.slice(0, 32)}</span>
            <span style={{ width: 70 * k, height: 12 * k, background: accent, opacity: 0.85 }} />
          </div>
          <div style={{ position: "absolute", left: 70 * k, top: 150 * k, transform: "rotate(2deg)" }}>
            <div style={{ padding: 14 * k, background: "#fff", boxShadow: "0 12px 30px rgba(0,0,0,.35)" }}>
              <PortraitBox src={src} name={name} w={PW} h={PH} accent={accent} imgStyle={{ filter: "contrast(1.05) saturate(.9)" }} />
            </div>
            <div style={{ position: "absolute", left: 60 * k, top: -44 * k }}>
              <PaperClip w={34 * k} h={102 * k} />
            </div>
          </div>
          <div style={{ position: "absolute", left: 590 * k, right: 60 * k, top: 170 * k, display: "flex", flexDirection: "column" }}>
            <div style={{ fontFamily: TYPEWRITER, fontWeight: 400, fontSize: 30 * k, letterSpacing: "0.2em", color: "#6b645a" }}>NAME</div>
            <div style={{ position: "relative", alignSelf: "flex-start", marginTop: 10 * k, minHeight: fit.size * 1.15 * k }}>
              <div style={{ position: "absolute", left: -8 * k, top: fit.size * 0.2 * k, height: (fit.size * 1.12 * (fit.ls.length - 1) + fit.size * 0.9) * k,
                width: `calc(${(hl * 100).toFixed(2)}% + ${(16 * k * hl).toFixed(2)}px)`, background: rgba(accent, 0.26), borderRadius: 4 * k }} />
              {fit.ls.map((ln, i) => (
                <div key={i} style={{ position: "relative", fontFamily: TYPEWRITER, fontWeight: 700, fontSize: fit.size * k, lineHeight: 1.12,
                  color: "#1d1a16", whiteSpace: "pre" }}>
                  <span>{typedLines[i]}</span>
                  {i === caretLine && caretOn ? (
                    <span style={{ display: "inline-block", width: fit.size * 0.08 * k, height: fit.size * 0.95 * k, background: "#1d1a16",
                      marginLeft: 3 * k, verticalAlign: "text-bottom" }} />
                  ) : null}
                  <span style={{ visibility: "hidden" }}>{Array.from(ln).slice(Array.from(typedLines[i]).length).join("")}</span>
                </div>
              ))}
            </div>
            {roleFit.ls.length ? (
              <div style={{ marginTop: 44 * k, opacity: roleIn, transform: `translateY(${((1 - roleIn) * 10 * k).toFixed(2)}px)` }}>
                <div style={{ fontFamily: TYPEWRITER, fontWeight: 400, fontSize: 30 * k, letterSpacing: "0.2em", color: "#6b645a" }}>ROLE</div>
                {roleFit.ls.map((ln, i) => (
                  <div key={i} style={{ fontFamily: TYPEWRITER, fontWeight: 400, fontSize: roleFit.size * k, lineHeight: 1.25, color: "#2b2620",
                    marginTop: i ? 0 : 10 * k, whiteSpace: "nowrap" }}>{ln}</div>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      </div>
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${300 * k}px rgba(0,0,0,.65)` }} />
    </AbsoluteFill>
  );
};

// ================================================================== pf-split-name
// The portrait panel swipes in over 0 -> 14 (sfx_at 8); the line draws 12 -> 34 under the name.
const SplitName: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width: W } = useVideoConfig();
  const k = useK();
  const q = useOut();
  const d = useDrift();
  const id = `pfDuo${React.useId().replace(/[^A-Za-z0-9]/g, "")}`;
  const src = portraitOf(overlay);
  const name = str(overlay.text);
  const role = str(overlay.subtitle);
  const kick = cap(overlay.label);
  const acc = readable(accent);
  const dark = mix(accent, "#05070b", 0.86);
  const light = mix(accent, "#ffffff", 0.35);
  const e = ramp(frame, 0, 16, expoOut);
  const line = ramp(frame, 12, 22, inOut) * (1 - q);
  const fit = fitLines(name, 740, nameSizes(name, [132, 120, 108, 96, 88, 80, 72]), 0.56, 3);
  const roleFit = fitLines(role, 740, [42, 38, 36], 0.5, 2);
  const half = W / 2;
  return (
    <AbsoluteFill style={{ background: "linear-gradient(120deg, #0d1118 0%, #080a0f 100%)", overflow: "hidden" }}>
      <DuoFilter id={id} dark={dark} light={light} />
      <div style={{ position: "absolute", left: half, top: 0, width: half, height: "100%", overflow: "hidden",
        transform: `translateX(${((1 - e) * 100 + q * 100).toFixed(2)}%)` }}>
        {src ? (
          <AbsoluteFill style={{ transform: `scale(${1.12 - 0.06 * e + 0.05 * d})` }}>
            <Photo src={src} style={{ filter: `contrast(1.1) url(#${id})` }} />
          </AbsoluteFill>
        ) : (
          <AbsoluteFill style={{ alignItems: "center", justifyContent: "center",
            background: `linear-gradient(160deg, ${mix(accent, "#10131a", 0.55)} 0%, ${dark} 100%)` }}>
            <Medallion name={name} size={420 * k} accent={accent} />
          </AbsoluteFill>
        )}
        <AbsoluteFill style={{ background: `linear-gradient(90deg, ${rgba(dark, 0.55)} 0%, ${rgba(dark, 0)} 30%)` }} />
      </div>
      <div style={{ position: "absolute", left: half - 3 * k, top: 0, width: 6 * k, height: "100%", background: acc,
        transform: `scaleY(${e * (1 - q)})`, transformOrigin: "50% 0", boxShadow: `0 0 ${20 * k}px ${rgba(accent, 0.6)}` }} />
      <div style={{ position: "absolute", left: 130 * k, width: half - 200 * k, top: 0, bottom: 0, display: "flex", flexDirection: "column",
        justifyContent: "center" }}>
        <Kicker text={kick} at={8} q={q} color={acc} />
        <div style={{ marginTop: kick ? 20 * k : 0 }}>
          {fit.ls.map((ln, i) => (
            <Rise key={i} at={10 + i * 4} q={q}>
              <div style={{ fontFamily: INTER, fontWeight: 800, fontSize: fit.size * k, letterSpacing: "-0.025em", lineHeight: 1.02, color: "#fff",
                whiteSpace: "nowrap" }}>{ln}</div>
            </Rise>
          ))}
        </div>
        <div style={{ height: 4 * k, width: (half - 130 * k) * line, background: acc, margin: `${30 * k}px 0 ${26 * k}px`,
          boxShadow: `0 0 ${14 * k}px ${rgba(accent, 0.5)}` }} />
        {roleFit.ls.map((ln, i) => (
          <Rise key={i} at={24 + i * 3} q={q}>
            <div style={{ fontFamily: INTER, fontWeight: 400, fontSize: roleFit.size * k, lineHeight: 1.22, color: "rgba(255,255,255,.82)",
              whiteSpace: "nowrap" }}>{ln}</div>
          </Rise>
        ))}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== pf-spotlight
// The spotlight hits at frame 14 (sfx_at 14); the name rises at 20 and its underline draws 26 -> 44.
const Spotlight: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const q = useOut();
  const d = useDrift();
  const src = portraitOf(overlay);
  const name = str(overlay.text);
  const role = cap(overlay.subtitle);
  const kick = cap(overlay.label);
  const acc = readable(accent);
  const HIT = 14;
  const on = ramp(frame, HIT - 2, 5);
  const flicker = frame >= HIT && frame < HIT + 6 ? [1, 0.82, 1, 0.9, 1, 1][frame - HIT] : 1;
  const lit = on * flicker * (1 - 0.6 * q);
  const fit = fitLines(name, 1300, nameSizes(name, [104, 96, 88, 80, 72, 64]), 0.5, 2);
  const underline = ramp(frame, 26, 18, inOut) * (1 - q);
  const nameW = Math.min(1300, Math.max(...fit.ls.map((l) => l.length), 1) * fit.size * 0.5) * k;
  const PW = 420 * k, PH = 480 * k;
  return (
    <AbsoluteFill style={{ background: "#040405", overflow: "hidden" }}>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 55% 22% at 50% 96%, rgba(255,246,228,.09) 0%, rgba(255,246,228,0) 100%)",
        opacity: 0.4 + 0.6 * lit }} />
      <AbsoluteFill style={{ opacity: lit * 0.9, mixBlendMode: "screen", filter: `blur(${26 * k}px)` }}>
        <AbsoluteFill style={{ clipPath: "polygon(45% -5%, 55% -5%, 70% 74%, 30% 74%)",
          background: "linear-gradient(180deg, rgba(255,247,230,.3) 0%, rgba(255,247,230,.12) 55%, rgba(255,247,230,0) 100%)" }} />
      </AbsoluteFill>
      <AbsoluteFill style={{ opacity: lit, background: "radial-gradient(ellipse 30% 36% at 50% 36%, rgba(255,244,222,.16) 0%, rgba(255,244,222,0) 100%)" }} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column" }}>
        <div style={{ width: PW, height: PH, position: "relative", transform: `scale(${1 + 0.03 * d})`, opacity: 1 - q,
          WebkitMaskImage: "radial-gradient(ellipse 50% 50% at 50% 50%, #000 60%, transparent 100%)",
          maskImage: "radial-gradient(ellipse 50% 50% at 50% 50%, #000 60%, transparent 100%)" }}>
          {src ? (
            <Photo src={src} style={{ filter: `brightness(${(0.14 + 0.9 * lit).toFixed(3)}) contrast(1.08) saturate(${(0.5 + 0.45 * lit).toFixed(3)})` }} />
          ) : (
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center",
              filter: `brightness(${(0.2 + 0.8 * lit).toFixed(3)})` }}>
              <Medallion name={name} size={300 * k} accent={accent} />
            </div>
          )}
        </div>
        <div style={{ marginTop: 26 * k, display: "flex", flexDirection: "column", alignItems: "center" }}>
          <Kicker text={kick} at={18} q={q} color={acc} size={28} center />
          <div style={{ marginTop: kick ? 12 * k : 0, display: "flex", flexDirection: "column", alignItems: "center" }}>
            {fit.ls.map((ln, i) => (
              <Rise key={i} at={20 + i * 4} q={q}>
                <div style={{ fontFamily: SERIF, fontWeight: 400, fontSize: fit.size * k, lineHeight: 1.08, color: "#fff", whiteSpace: "nowrap",
                  textAlign: "center", textShadow: "0 8px 40px rgba(0,0,0,.6)" }}>{ln}</div>
              </Rise>
            ))}
          </div>
          <div style={{ width: nameW * underline, height: 3 * k, background: acc, marginTop: 16 * k, borderRadius: 2 * k,
            boxShadow: `0 0 ${12 * k}px ${rgba(accent, 0.55)}` }} />
          {role ? (
            <Rise at={30} q={q} style={{ marginTop: 20 * k }}>
              <div style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 32 * k, letterSpacing: "0.22em", color: "rgba(255,255,255,.74)",
                whiteSpace: "nowrap", textAlign: "center" }}>{role.slice(0, 64)}</div>
            </Rise>
          ) : null}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== pf-magazine
// The shutter fires at frame 3 (sfx_at 3); the masthead drops in letter by letter, the cover lines rise.
const Magazine: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const k = useK();
  const q = useOut();
  const d = useDrift();
  const src = portraitOf(overlay);
  const name = str(overlay.text);
  const role = str(overlay.subtitle);
  const kick = cap(overlay.label);
  const acc = readable(accent);
  const flash = interpolate(frame, [0, 3, 12], [0, 0.85, 0], clamp);
  const settle = ramp(frame, 2, 22);
  const mast = (() => {
    const one = fitLines(name.toUpperCase(), 1680, nameSizes(name, [140, 128, 116, 104, 96, 88]), 0.66, 1);
    if (Array.from(one.ls[0] || "").length && !(one.ls[0] || "").endsWith("…")) return one;
    return fitLines(name.toUpperCase(), 1680, [96, 88, 80, 72, 64], 0.66, 2);
  })();
  const roleFit = fitLines(role, 900, [52, 48, 44, 40], 0.52, 2);
  const rule = ramp(frame, 20, 18, inOut) * (1 - q);
  let li = 0;
  return (
    <AbsoluteFill style={{ background: "#0b0d12", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${(1.06 - 0.06 * settle + 0.04 * d).toFixed(4)})` }}>
        {src ? (
          <Photo src={src} style={{ objectPosition: "50% 22%", filter: "contrast(1.05) saturate(1.02)" }} />
        ) : (
          <AbsoluteFill style={{ alignItems: "center", justifyContent: "center",
            background: `radial-gradient(ellipse at 50% 60%, ${mix(accent, "#12151c", 0.55)} 0%, #0b0d12 75%)` }}>
            <div style={{ marginTop: 40 * k }}>
              <Medallion name={name} size={400 * k} accent={accent} />
            </div>
          </AbsoluteFill>
        )}
      </AbsoluteFill>
      <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(0,0,0,.6) 0%, rgba(0,0,0,.18) 30%, rgba(0,0,0,0) 45%)" }} />
      <AbsoluteFill style={{ background: "linear-gradient(0deg, rgba(0,0,0,.72) 0%, rgba(0,0,0,.28) 28%, rgba(0,0,0,0) 50%)" }} />
      <div style={{ position: "absolute", inset: 44 * k, border: `${Math.max(1, 1.5 * k)}px solid rgba(255,255,255,${(0.28 * ramp(frame, 6, 14) * (1 - q)).toFixed(3)})` }} />
      <div style={{ position: "absolute", left: 0, right: 0, top: 88 * k, display: "flex", flexDirection: "column", alignItems: "center",
        opacity: 1 - q, transform: `translateY(${(-q * 30 * k).toFixed(2)}px)` }}>
        {mast.ls.map((ln, i) => (
          <div key={i} style={{ fontFamily: SERIF, fontWeight: 400, fontSize: mast.size * k, lineHeight: 1.0, color: "#fff", whiteSpace: "pre",
            letterSpacing: "0.02em", textShadow: "0 6px 34px rgba(0,0,0,.45)" }}>
            {Array.from(ln).map((c, j) => {
              const p = ramp(frame, 5 + (li++) * 0.9, 14, expoOut);
              return (
                <span key={j} style={{ display: "inline-block", opacity: p, transform: `translateY(${((1 - p) * -0.25).toFixed(3)}em)` }}>{c}</span>
              );
            })}
          </div>
        ))}
      </div>
      <div style={{ position: "absolute", left: 110 * k, bottom: 110 * k, maxWidth: 960 * k, display: "flex", flexDirection: "column" }}>
        <Kicker text={kick} at={18} q={q} color={acc} size={30} />
        <div style={{ width: 120 * k * rule, height: 3 * k, background: "#fff", margin: `${kick ? 16 * k : 0}px 0 ${14 * k}px` }} />
        {roleFit.ls.map((ln, i) => (
          <Rise key={i} at={22 + i * 3} q={q}>
            <div style={{ fontFamily: INTER, fontWeight: 700, fontSize: roleFit.size * k, lineHeight: 1.15, color: "#fff", whiteSpace: "nowrap",
              letterSpacing: "-0.01em", textShadow: SHADOW }}>{ln}</div>
          </Rise>
        ))}
      </div>
      <AbsoluteFill style={{ background: "#fff", opacity: flash }} />
    </AbsoluteFill>
  );
};

// ================================================================== registry
export const LOOKS: Record<string, Look> = {
  "pf-profile": Profile,
  "pf-dossier": Dossier,
  "pf-split-name": SplitName,
  "pf-spotlight": Spotlight,
  "pf-magazine": Magazine,
};
