import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { SafeImg } from "../motion/safePicture";
import { DISPLAY, HAND, INTER, LABEL, MONO } from "../fonts";
import type { MapLocation, Overlay, OverlayItem, SceneMedia } from "../../types";
import { LetterLine, Odometer, formatValue, lines, ramp, useHold, useK } from "../pro/ProGraphics";

/**
 * Photo motion I (family "pa-"): ten designed moments for the story's own
 * stills (overlay.media; a video clip lends its thumbnail). Every look draws
 * its own full-frame backdrop.
 *
 *   pa-polaroid-drop     a polaroid falls onto a dark desk, lands, develops from
 *                        grey-green to colour; the caption is handwritten on it
 *   pa-tilt-card         a photo block flips in from edge-on and sways in 3D:
 *                        parallax inside, a gloss sweep, real thickness, a reflection
 *   pa-blinds-reveal     vertical blinds turn open over the photo, the caption
 *                        rises out of its mask; the blinds close again at the end
 *   pa-spotlight-focus   a follow-spot from above the frame: the photo waits dark
 *                        and out of focus, the beam (dust drifting in it) hunts
 *                        and locks on, the pool racks into focus, a stage caption
 *                        steps out under it; the spot swings off, lights go down
 *   pa-film-strip        a 35 mm strip races in and stops; the centre frame is
 *                        pulled out of it and enlarged as a print
 *   pa-mosaic-assemble   the photo builds from tiles flying in from the camera,
 *                        the seams close, a gloss sweeps; the tiles scatter out
 *   pa-torn-reveal       a sheet of paper tears away to a torn edge, leaving a
 *                        paper panel with the title beside the photo
 *   pa-loupe-zoom        a loupe glides over the photo and magnifies the detail
 *                        under it (the zoom pulls in as it lands), a dashed leader
 *   pa-scan-id           a HUD scan: brackets lock, a scan line resolves the photo
 *                        from cyan to colour, a detection box, readouts type in;
 *                        the screen collapses like a CRT at the end
 *   pa-ken-burns         a cinematic push with grade, vignette, grain and bars;
 *                        a lower caption with a drawn rule
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;
type Pt = [number, number];

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const expoIn = Easing.bezier(0.7, 0, 0.84, 0);
const CYAN = "#53c8ff";
const INK = "#1c2846";

// ------------------------------------------------------------------ helpers
const str = (s: unknown): string => (typeof s === "string" ? s.trim() : "");
const cap = (s: unknown): string => str(s).toUpperCase();

const stillOf = (m: SceneMedia | null | undefined): string => {
  if (!m || typeof m !== "object") return "";
  const s = m.type === "image" ? m.url : m.thumbnail;
  return typeof s === "string" ? s.trim() : "";
};

/** The overlay's pictures as still URLs (a video gives its thumbnail). */
const stills = (ov: Overlay, max: number): string[] => {
  const media: SceneMedia[] = Array.isArray(ov.media) ? ov.media : [];
  return media.map((m) => stillOf(m)).filter((s) => s.length > 0).slice(0, max);
};

const itemsOf = (ov: Overlay): OverlayItem[] => {
  const items: OverlayItem[] = Array.isArray(ov.items) ? ov.items : [];
  return items.filter((it): it is OverlayItem => !!it && typeof it === "object");
};

/** Deterministic 0..1 noise of an index and a salt (never Math.random). */
const rnd = (i: number, salt = 0): number => {
  const x = Math.sin(i * 127.1 + salt * 311.7 + 74.7) * 43758.5453123;
  return x - Math.floor(x);
};

const hashStr = (s: string): number => {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619) >>> 0;
  return h;
};

/** "#F2B544" + alpha -> rgba(); anything unparseable falls back to the house gold. */
const withAlpha = (color: string, a: number): string => {
  const s = (color || "").trim().replace(/^#/, "");
  let hex = "";
  if (/^[0-9a-f]{6}$/i.test(s)) hex = s;
  else if (/^[0-9a-f]{3}$/i.test(s)) hex = s.split("").map((c) => c + c).join("");
  const n = hex ? parseInt(hex, 16) : 0xf2b544;
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
};

const bez = (a: Pt, b: Pt, c: Pt, d: Pt, t: number): Pt => {
  const u = 1 - t;
  const w0 = u * u * u, w1 = 3 * u * u * t, w2 = 3 * u * t * t, w3 = t * t * t;
  return [w0 * a[0] + w1 * b[0] + w2 * c[0] + w3 * d[0], w0 * a[1] + w1 * b[1] + w2 * c[1] + w3 * d[1]];
};

/** The point of interest: overlay.anchor when valid (clamped), else the default. */
const anchorOf = (ov: Overlay, fx: number, fy: number, lo: number, hi: number): Pt => {
  const a = ov.anchor;
  const cl = (v: number) => Math.min(hi, Math.max(lo, v));
  if (a && typeof a === "object" && Number.isFinite(a.x) && Number.isFinite(a.y)) return [cl(a.x), cl(a.y)];
  return [fx, fy];
};

const coordText = (l: MapLocation): string =>
  `${Math.abs(l.lat).toFixed(2)}° ${l.lat >= 0 ? "N" : "S"}  ${Math.abs(l.lon).toFixed(2)}° ${l.lon >= 0 ? "E" : "W"}`;

const itemValue = (it: OverlayItem): string => {
  const x = it as OverlayItem & { prefix?: string; suffix?: string };
  if (str(x.text)) return str(x.text);
  if (typeof x.value === "number" && Number.isFinite(x.value)) {
    return `${str(x.prefix)}${formatValue(x.value).text}${x.suffix ? ` ${str(x.suffix)}` : ""}`;
  }
  return "";
};

/** Exit progress 0 -> 1 over the last `frames` frames (ease-in). */
const useOutQ = (frames = 12): number => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return ramp(frame, Math.max(0, durationInFrames - frames - 1), frames, expoIn);
};

/**
 * A LetterLine whose letters all finish dropping out before the graphic ends,
 * however long the line (the library default lets late letters overrun).
 */
const Letters: React.FC<{ text: string; at: number; style: React.CSSProperties; step?: number }> =
  ({ text, at, style, step }) => {
    const { durationInFrames } = useVideoConfig();
    const n = Array.from(text).length;
    if (!n) return null;
    const st = step ?? Math.max(0.35, Math.min(1, 18 / n));
    const outAt = Math.max(at + 18, durationInFrames - 12 - Math.ceil(n * 0.6));
    return <LetterLine text={text} at={at} step={st} style={style} outAt={outAt} />;
  };

/** A line sliding up out of its mask, and up out of it again at the end. */
const Rise: React.FC<{ at: number; children: React.ReactNode; style?: React.CSSProperties; frames?: number }> =
  ({ at, children, style, frames = 16 }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();
    const p = ramp(frame, at, frames);
    const q = ramp(frame, durationInFrames - 14, 10, expoIn);
    return (
      <div style={{ overflow: "hidden", paddingBottom: "0.1em", ...style }}>
        <div style={{ transform: `translateY(${((1 - p) * 115 - q * 115).toFixed(2)}%)` }}>{children}</div>
      </div>
    );
  };

// ================================================================== 1 polaroid drop
/** Handwriting: each letter is inked on left to right (a soft clip wipe per letter). */
const Handwrite: React.FC<{ text: string; at: number; step: number; style: React.CSSProperties }> =
  ({ text, at, step, style }) => {
    const frame = useCurrentFrame();
    return (
      <div style={{ whiteSpace: "pre", lineHeight: 1.15, ...style }}>
        {Array.from(text).map((c, i) => {
          const p = ramp(frame, at + i * step, 7);
          // The wipe box reaches past the glyph box (Caveat's loops and tails
          // overhang it), so nothing pops in when the clip is dropped.
          return (
            <span key={i} style={{ display: "inline-block", opacity: p > 0.01 ? 1 : 0,
              clipPath: p >= 0.999 ? undefined : `inset(-40% ${((1 - p) * 125 - 25).toFixed(1)}% -40% 0)`,
              transform: `translateY(${((1 - p) * 0.06).toFixed(3)}em)` }}>{c}</span>
          );
        })}
      </div>
    );
  };

const PolaroidDrop: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const q = useOutQ(13);
  const pics = stills(overlay, 2);
  if (!pics.length) return null;
  const back = pics[1] || "";
  const caption = str(overlay.text);
  const date = str(overlay.label);
  const capLines = lines(caption, date ? 26 : 32).slice(0, 2);
  const capChars = capLines.join("").length;
  const step = Math.max(0.55, Math.min(1.1, 30 / Math.max(1, capChars + date.length)));
  // The fall: accelerating toward the desk, a small impact, then it settles.
  const T = Math.max(8, Math.round(fps * 0.42));
  const hgt = 1 - interpolate(frame, [0, T], [0, 1], { ...clamp, easing: Easing.in(Easing.quad) });
  const landed = frame >= T;
  const settle = ramp(frame, T, Math.round(fps * 0.7));
  const bt = landed ? Math.min(1, (frame - T) / 8) : 0;
  const bump = Math.sin(bt * Math.PI) * (1 - bt);
  const t = frame / fps;
  const idle = ramp(frame, T, fps);
  const dev = ramp(frame, T - 2, Math.round(fps * 1.8), inOut);
  const CW = 860 * k, B = 30 * k, PW = CW - 2 * B, PH = 540 * k, BOT = 165 * k, CH = B + PH + BOT;
  const cx = width / 2 + (back ? -70 : 0) * k, cy = height / 2 + 6 * k;
  const lift = Math.min(1, hgt + q);
  const scale = (1 + hgt * 0.45 - bump * 0.02) * (1 + q * 0.1);
  const rot = interpolate(hgt, [0, 1], [-5.5, -19]) + 2 * settle + idle * 0.35 * Math.sin(t * 0.9) - q * 14;
  const x = (70 * hgt + 22 * (landed ? 1 - settle : 1) + q * 140) * k;
  const y = (-260 * hgt + idle * 4 * Math.sin(t * 1.1) - q * 1250) * k;
  const shadow = `${(6 + 26 * lift) * k}px ${(16 + 74 * lift) * k}px ${(26 + 90 * lift) * k}px rgba(0,0,0,${(0.58 - 0.24 * lift).toFixed(3)}), `
    + `0 ${2 * k}px ${4 * k}px rgba(0,0,0,${(0.35 * (1 - lift)).toFixed(3)})`;
  const capSize = capLines.length > 1 ? 46 : 58;
  const writeAt = T + 12;
  const lineAt: number[] = [];
  let acc = 0;
  capLines.forEach((ln, i) => {
    lineAt.push(writeAt + acc * step + i * 3);
    acc += Array.from(ln).length;
  });
  const dateAt = writeAt + acc * step + capLines.length * 3 + 2;
  const ba = ramp(frame, 0, 16);
  const bq = ramp(frame, durationInFrames - 12, 11, expoIn);
  const BW = CW * 0.84, BH = CH * 0.84;
  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 40%, #3b352e 0%, #221f1b 55%, #0c0b0a 100%)", overflow: "hidden" }}>
      <AbsoluteFill style={{ backgroundImage: `repeating-linear-gradient(86deg, rgba(255,255,255,.022) 0px, rgba(255,255,255,.022) ${2 * k}px, rgba(0,0,0,0) ${2 * k}px, rgba(0,0,0,0) ${9 * k}px)` }} />
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 30% 16%, rgba(255,222,165,.2) 0%, rgba(255,222,165,0) 52%)" }} />
      <AbsoluteFill style={{ transform: `scale(${hold})` }}>
        {back ? (
          <div style={{ position: "absolute", left: cx + 400 * k - BW / 2, top: cy - 60 * k - BH / 2, width: BW, height: BH,
            background: "linear-gradient(172deg, #efebe2 0%, #e0dbcf 100%)", borderRadius: 3 * k,
            boxShadow: `${8 * k}px ${22 * k}px ${44 * k}px rgba(0,0,0,.5)`, opacity: ba,
            transform: `translate(${((1 - ba) * 70 + bq * 160) * k}px, ${-bq * 1300 * k}px) rotate(${8 + (1 - ba) * 5 - bq * 10}deg)` }}>
            <div style={{ position: "absolute", left: B * 0.84, top: B * 0.84, width: PW * 0.84, height: PH * 0.84, overflow: "hidden",
              background: "#222" }}>
              <SafeImg src={back} style={{ width: "100%", height: "100%", objectFit: "cover", filter: "brightness(.8) saturate(.75) sepia(.18)" }} />
            </div>
          </div>
        ) : null}
        <div style={{ position: "absolute", left: cx - CW / 2, top: cy - CH / 2, width: CW, height: CH,
          background: "linear-gradient(172deg, #fcfbf7 0%, #f0ece2 100%)", borderRadius: 3 * k, boxShadow: shadow,
          opacity: ramp(frame, 0, 4), transform: `translate(${x}px, ${y}px) rotate(${rot}deg) scale(${scale})` }}>
          <div style={{ position: "absolute", left: B, top: B, width: PW, height: PH, overflow: "hidden", background: "#2b312d" }}>
            <SafeImg src={pics[0]} style={{ width: "100%", height: "100%", objectFit: "cover",
              filter: `brightness(${(0.3 + 0.7 * dev).toFixed(3)}) saturate(${(0.1 + 0.9 * dev).toFixed(3)}) contrast(${(1.3 - 0.26 * dev).toFixed(3)}) sepia(${(0.4 * (1 - dev)).toFixed(3)})` }} />
            {/* the undeveloped emulsion: grey-green, clearing as the picture comes up */}
            <div style={{ position: "absolute", inset: 0, background: "linear-gradient(160deg, #6a786d 0%, #3a443f 100%)", opacity: 0.88 * (1 - dev) }} />
            <div style={{ position: "absolute", inset: 0, background: "linear-gradient(125deg, rgba(255,255,255,.16) 0%, rgba(255,255,255,0) 40%)" }} />
            <div style={{ position: "absolute", inset: 0, boxShadow: `inset 0 0 0 ${Math.max(1, k)}px rgba(0,0,0,.3), inset 0 0 ${40 * k}px rgba(0,0,0,.3)` }} />
          </div>
          <div style={{ position: "absolute", left: B + 10 * k, right: B + 6 * k, top: B + PH + 18 * k, display: "flex",
            justifyContent: "space-between", alignItems: "flex-start", gap: 24 * k }}>
            <div style={{ display: "flex", flexDirection: "column" }}>
              {capLines.map((ln, i) => (
                <Handwrite key={i} text={ln} at={lineAt[i]} step={step}
                  style={{ fontFamily: HAND, fontWeight: 700, fontSize: capSize * k, color: INK }} />
              ))}
            </div>
            {date ? (
              <Handwrite text={date} at={dateAt} step={step}
                style={{ fontFamily: HAND, fontWeight: 600, fontSize: 40 * k, color: INK, opacity: 0.78, marginTop: 8 * k }} />
            ) : null}
          </div>
        </div>
      </AbsoluteFill>
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${340 * k}px rgba(0,0,0,.72)` }} />
    </AbsoluteFill>
  );
};

// ================================================================== 2 3D tilt card
const TiltCard: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, height, durationInFrames } = useVideoConfig();
  const k = useK();
  const q = useOutQ(13);
  const pics = stills(overlay, 1);
  if (!pics.length) return null;
  const src = pics[0];
  const title = cap(overlay.text);
  const kicker = cap(overlay.label);
  const sub = str(overlay.subtitle);
  const tl = lines(title, 15).slice(0, 3);
  // A line never breaks inside a word ("OUTLET WORK / S" on the Las Vegas video): the size fits the longest line
  // in the 600 px column (display caps run about 0.7 em a letter).
  const longest = Math.max(1, ...tl.map((l) => l.length));
  const size = Math.min(tl.length >= 3 ? 68 : 80, Math.floor(600 / (longest * 0.7)));
  const E = Math.round(fps * 0.85);
  const e = ramp(frame, 0, E, Easing.bezier(0.2, 1.22, 0.36, 1));
  const t = frame / fps;
  const sw = ramp(frame, E * 0.5, E);
  const ry = 78 + (-17 - 78) * e + sw * 6 * Math.sin(t * 1.05) - q * 76;
  const rx = -14 + 20 * e + sw * 2.4 * Math.cos(t * 0.8) + q * 8;
  const tz = (-520 * (1 - e) - q * 260) * k;
  const CW = 980 * k, CH = 620 * k, D = 18 * k;
  const cardL = 150 * k, cardT = (height - CH) / 2 - 40 * k;
  const shine = -60 + 100 * e + (ry + 17) * 3.2;
  const vis = ramp(frame, 0, 5) * (1 - ramp(frame, durationInFrames - 3, 2));
  const edge = "linear-gradient(180deg, #f4f2ed 0%, #b3aea5 100%)";
  // Parallax inside the face, saturating before it runs out of picture (the
  // photo bleeds 8% each side: 78 x 50 px). Linear it reached 247 px mid-flip.
  const par = { x: -70 * k * Math.tanh(((ry + 17) * 2.6) / 70), y: 44 * k * Math.tanh(((rx - 6) * 2.6) / 44) };
  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 34% 40%, #1c2533 0%, #0d121b 52%, #05070b 100%)", overflow: "hidden" }}>
      <AbsoluteFill style={{ backgroundImage: `radial-gradient(rgba(255,255,255,.075) ${1.3 * k}px, rgba(0,0,0,0) ${1.8 * k}px)`,
        backgroundSize: `${34 * k}px ${34 * k}px`, backgroundPosition: `${-frame * 0.4 * k}px 0px`,
        maskImage: "radial-gradient(ellipse at 40% 50%, #000 0%, rgba(0,0,0,.15) 78%)",
        WebkitMaskImage: "radial-gradient(ellipse at 40% 50%, #000 0%, rgba(0,0,0,.15) 78%)" }} />
      <div style={{ position: "absolute", left: cardL + CW / 2 - 760 * k, top: cardT + CH / 2 - 520 * k, width: 1520 * k, height: 1040 * k,
        background: `radial-gradient(ellipse at center, ${withAlpha(accent, 0.2)} 0%, rgba(0,0,0,0) 62%)`, opacity: Math.min(1, e) }} />
      <div style={{ position: "absolute", left: cardL, top: cardT, width: CW, height: CH, perspective: 1900 * k, perspectiveOrigin: "50% 50%" }}>
        <div style={{ position: "absolute", inset: 0, transformStyle: "preserve-3d", opacity: vis,
          transform: `translateZ(${tz}px) rotateX(${rx}deg) rotateY(${ry}deg)` }}>
          {/* the block's four edges, folded back from the face */}
          <div style={{ position: "absolute", left: CW, top: 0, width: D, height: CH, background: edge, transformOrigin: "0 50%", transform: "rotateY(90deg)" }} />
          <div style={{ position: "absolute", left: -D, top: 0, width: D, height: CH, background: edge, transformOrigin: "100% 50%", transform: "rotateY(-90deg)" }} />
          <div style={{ position: "absolute", left: 0, top: -D, width: CW, height: D, background: edge, transformOrigin: "50% 100%", transform: "rotateX(90deg)" }} />
          <div style={{ position: "absolute", left: 0, top: CH, width: CW, height: D, background: edge, transformOrigin: "50% 0", transform: "rotateX(-90deg)" }} />
          {/* reflection on the glossy floor */}
          <div style={{ position: "absolute", left: 0, top: CH + D + 10 * k, width: CW, height: CH * 0.42, overflow: "hidden", opacity: 0.28,
            maskImage: "linear-gradient(180deg, #000 0%, rgba(0,0,0,0) 100%)", WebkitMaskImage: "linear-gradient(180deg, #000 0%, rgba(0,0,0,0) 100%)" }}>
            <SafeImg src={src} style={{ position: "absolute", left: 0, top: 0, width: CW, height: CH, objectFit: "cover", transform: "scaleY(-1)" }} />
          </div>
          {/* the face: photo with parallax, gloss sweep, hairline edge */}
          <div style={{ position: "absolute", inset: 0, overflow: "hidden", borderRadius: 5 * k, background: "#0b0d12",
            boxShadow: `0 ${50 * k}px ${110 * k}px rgba(0,0,0,.6)`, backfaceVisibility: "hidden" }}>
            <SafeImg src={src} style={{ position: "absolute", left: -0.08 * CW, top: -0.08 * CH, width: CW * 1.16, height: CH * 1.16,
              objectFit: "cover", maxWidth: "none", transform: `translate(${par.x}px, ${par.y}px)` }} />
            <div style={{ position: "absolute", inset: 0, background: `linear-gradient(115deg, rgba(255,255,255,0) ${shine - 20}%, rgba(255,255,255,.24) ${shine}%, rgba(255,255,255,0) ${shine + 20}%)` }} />
            <div style={{ position: "absolute", inset: 0, background: "linear-gradient(180deg, rgba(0,0,0,0) 60%, rgba(0,0,0,.28) 100%)" }} />
            <div style={{ position: "absolute", inset: 0, borderRadius: 5 * k, boxShadow: `inset 0 0 0 ${1.5 * k}px rgba(255,255,255,.22)` }} />
          </div>
        </div>
      </div>
      <div style={{ position: "absolute", left: 1230 * k, width: 600 * k, top: cardT, height: CH, display: "flex", flexDirection: "column",
        justifyContent: "center", gap: 12 * k, transform: `translateX(${-sw * Math.sin(t * 1.05) * 5 * k}px)` }}>
        {kicker ? (
          <div style={{ display: "flex", alignItems: "center", gap: 16 * k }}>
            <div style={{ width: ramp(frame, 8, 14) * (1 - q) * 46 * k, height: 3 * k, background: accent }} />
            <Letters text={kicker} at={10} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 30 * k, letterSpacing: "0.24em", color: accent }} />
          </div>
        ) : null}
        {tl.map((ln, i) => (
          <Letters key={i} text={ln} at={12 + i * 5} style={{ fontFamily: DISPLAY, fontSize: size * k, lineHeight: 0.98, color: "#fff",
            letterSpacing: "0.02em", textShadow: "0 8px 30px rgba(0,0,0,.5)", whiteSpace: "nowrap" }} />
        ))}
        {sub ? (
          <div style={{ marginTop: 10 * k, display: "flex", flexDirection: "column", gap: 2 * k }}>
            {lines(sub, 36).slice(0, 3).map((ln, i) => (
              <Rise key={i} at={24 + i * 4}>
                <span style={{ fontFamily: INTER, fontWeight: 400, fontSize: 28 * k, lineHeight: 1.35, color: "rgba(255,255,255,.74)",
                  whiteSpace: "nowrap" }}>{ln}</span>
              </Rise>
            ))}
          </div>
        ) : null}
      </div>
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${300 * k}px rgba(0,0,0,.6)` }} />
    </AbsoluteFill>
  );
};

// ================================================================== 3 blinds reveal
const BlindsReveal: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width, durationInFrames } = useVideoConfig();
  const k = useK();
  const pics = stills(overlay, 1);
  if (!pics.length) return null;
  const N = 12;
  const sw = width / N;
  const lit = ramp(frame, 4, N + 16, inOut);
  const push = interpolate(frame, [0, Math.max(1, durationInFrames)], [1.13, 1.04], { ...clamp, easing: Easing.out(Easing.cubic) });
  const title = cap(overlay.text);
  const sub = cap(overlay.subtitle);
  const tl = lines(title, 22).slice(0, 2);
  const capAt = Math.round(fps * 0.75);
  const bar = ramp(frame, capAt - 4, 16) * (1 - ramp(frame, durationInFrames - 15, 10, expoIn));
  const hasCap = tl.length > 0 || sub.length > 0;
  return (
    <AbsoluteFill style={{ background: "#07080a", overflow: "hidden" }}>
      <SafeImg src={pics[0]} style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "100%", objectFit: "cover",
        transform: `scale(${push})`, filter: `brightness(${(0.5 + 0.5 * lit).toFixed(3)}) saturate(${(0.8 + 0.15 * lit).toFixed(3)})` }} />
      {hasCap ? (
        <AbsoluteFill style={{ background: "linear-gradient(0deg, rgba(0,0,0,.62) 0%, rgba(0,0,0,.18) 34%, rgba(0,0,0,0) 55%)", opacity: bar }} />
      ) : null}
      <AbsoluteFill style={{ perspective: 2400 * k }}>
        {Array.from({ length: N }, (_, i) => {
          const o = ramp(frame, 3 + i * 1.1, 16, inOut);
          const c = ramp(frame, durationInFrames - 17 + (N - 1 - i) * 0.55, 10, inOut);
          const a = 90 * o * (1 - c);
          if (a > 89.4) return null;
          const shade = Math.sin((a * Math.PI) / 180) * 0.6;
          // Nearly edge-on, an off-centre slat still shows a sliver through the
          // perspective: it thins away instead of popping off.
          const op = interpolate(a, [74, 89.4], [1, 0], clamp);
          return (
            <div key={i} style={{ position: "absolute", top: 0, bottom: 0, left: i * sw - 0.5, width: sw + 1, transform: `rotateY(${a}deg)`,
              opacity: op,
              background: "linear-gradient(90deg, #121317 0%, #26282e 30%, #33363d 52%, #1a1b20 80%, #0d0e11 100%)" }}>
              <div style={{ position: "absolute", top: 0, bottom: 0, right: 0, width: Math.max(1, 1.5 * k), background: withAlpha(accent, 0.22) }} />
              {shade > 0.01 ? <div style={{ position: "absolute", inset: 0, background: "#000", opacity: shade }} /> : null}
            </div>
          );
        })}
      </AbsoluteFill>
      {hasCap ? (
        // A location slug set right, the accent bar on its outer edge (the
        // lower-left caption belongs to pa-ken-burns).
        <div style={{ position: "absolute", right: 120 * k, bottom: 120 * k, display: "flex", gap: 24 * k, alignItems: "stretch" }}>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 * k }}>
            {tl.map((ln, i) => (
              <Rise key={i} at={capAt + i * 4}>
                <span style={{ fontFamily: DISPLAY, fontSize: 80 * k, lineHeight: 0.98, color: "#fff", letterSpacing: "0.02em",
                  textShadow: "0 6px 26px rgba(0,0,0,.5)", whiteSpace: "nowrap" }}>{ln}</span>
              </Rise>
            ))}
            {sub ? (
              <Rise at={capAt + tl.length * 4 + 4}>
                <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 30 * k, letterSpacing: "0.2em", color: "rgba(255,255,255,.84)",
                  whiteSpace: "nowrap" }}>{sub}</span>
              </Rise>
            ) : null}
          </div>
          <div style={{ width: 6 * k, flexShrink: 0, background: accent, transform: `scaleY(${bar})`, transformOrigin: "50% 100%",
            boxShadow: `0 0 ${16 * k}px ${withAlpha(accent, 0.6)}` }} />
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== 4 spotlight focus
/**
 * A follow-spot from the rafters. The picture waits dark and out of focus; a
 * lamp strikes above the frame (a short flicker) and its beam, dust drifting
 * in it, swings across the picture hunting for the subject, locks on, and the
 * picture inside the pool racks into focus. A stage caption steps out under
 * the pool. At the end the spot swings off and the house lights go down.
 * (Deliberately no ring and no leader line: those belong to pa-loupe-zoom and
 * to co-spotlight, the tag version of a searchlight over footage.)
 */
const SpotlightFocus: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const q = useOutQ(14);
  const pics = stills(overlay, 1);
  if (!pics.length) return null;
  const src = pics[0];
  const [ax, ay] = anchorOf(overlay, 0.5, 0.42, 0.2, 0.8);
  const tx = ax * width, ty = ay * height;
  const t = frame / fps;
  const f1 = (v: number): string => v.toFixed(1);
  const RR = 250 * k;
  // The lamp hangs above the frame, leaning a little toward the subject.
  const Lx = width / 2 + (tx - width / 2) * 0.35, Ly = -280 * k;
  // The hunt: the pool sweeps in on a curve, a handheld wobble dying as it
  // locks (quicker on a short graphic so the caption still gets its hold).
  const S0 = 4;
  const A = Math.round(Math.min(fps * 1.25, Math.max(fps * 0.8, (durationInFrames - 60) * 0.75)));
  const u = ramp(frame, S0, A, inOut);
  const [bx, by] = bez([0.1 * width, 0.8 * height], [0.3 * width, 0.06 * height], [0.96 * width, 0.86 * height], [tx, ty], u);
  const wob = (1 - u) * 8 * k;
  const idle = ramp(frame, S0 + A, fps);
  const hx = bx + wob * Math.sin(frame * 0.47) + idle * 6 * k * Math.sin(t * 0.9);
  const hy = by + wob * Math.cos(frame * 0.39) + idle * 4 * k * Math.sin(t * 1.3 + 0.8);
  // The exit: the spot swings off to the right.
  const px = hx + (width + 460 * k - hx) * q, py = hy + (ty - 180 * k - hy) * q;
  const lock = ramp(frame, S0 + A - 8, 18, backOut);
  const R = Math.max(1, RR * (1.3 - 0.3 * lock) * (1 + 0.015 * Math.sin(t * 2.1)));
  // The lamp strikes with a short flicker.
  const flick = frame < 12 ? 0.55 + 0.45 * Math.abs(Math.cos(frame * 2.3)) : 1;
  const lamp = ramp(frame, 3, 5) * flick;
  const focus = ramp(frame, S0 + A - 10, 22, inOut);
  const soft = (1 - focus) * 6 * k;
  const flash = ramp(frame, S0 + A - 4, 5) * (1 - ramp(frame, S0 + A + 2, 14));
  const house = ramp(frame, 0, 10) * (1 - ramp(frame, durationInFrames - 9, 8, expoIn));
  const pool = `circle ${f1(R)}px at ${f1(px)}px ${f1(py)}px`;
  const mask = `radial-gradient(${pool}, #000 0%, #000 58%, rgba(0,0,0,.55) 80%, rgba(0,0,0,0) 100%)`;
  // The beam: soft layered wedges from the lamp to the pool, brightest at the lamp.
  const dx = px - Lx, dy = py - Ly;
  const dl = Math.max(1, Math.hypot(dx, dy));
  const nx = -dy / dl, ny = dx / dl;
  const w0 = 22 * k, w1 = R * 0.9;
  const wedge = (f: number): string => {
    const pts: Pt[] = [
      [Lx + nx * w0 * f, Ly + ny * w0 * f], [px + nx * w1 * f, py + ny * w1 * f],
      [px - nx * w1 * f, py - ny * w1 * f], [Lx - nx * w0 * f, Ly - ny * w0 * f],
    ];
    return pts.map((p) => `${f1(p[0])},${f1(p[1])}`).join(" ");
  };
  // The caption: centred under the pool (above it when the subject sits low).
  const title = cap(overlay.text);
  const kick = cap(overlay.subtitle);
  const tl = lines(title, 24).slice(0, 2);
  const tsz = tl.length > 1 ? 58 : 68;
  const hasCap = tl.length > 0 || kick.length > 0;
  const gapY = 46 * k;
  const capH = (kick ? 44 * k : 0) + 22 * k + tl.length * tsz * 1.08 * k;
  const below = ty + RR + gapY + capH <= height - 90 * k;
  const capX = Math.min(width - 520 * k, Math.max(520 * k, tx));
  const capAt = S0 + A + 2;
  const rule = ramp(frame, capAt + 3, 16, inOut) * (1 - ramp(frame, durationInFrames - 15, 10, expoIn));
  const full: React.CSSProperties = { position: "absolute", left: 0, top: 0, width: "100%", height: "100%", objectFit: "cover" };
  return (
    <AbsoluteFill style={{ background: "#030304", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${hold})` }}>
        {/* the picture in the dark, out of focus (scaled past its blurred edges) */}
        <SafeImg src={src} style={{ ...full, opacity: house, transform: "scale(1.06)",
          filter: `blur(${f1(9 * k)}px) grayscale(.6) brightness(.22) contrast(1.08)` }} />
        {/* the pool: the same picture lit, racking into focus as the spot locks */}
        <AbsoluteFill style={{ maskImage: mask, WebkitMaskImage: mask, opacity: lamp }}>
          <SafeImg src={src} style={{ ...full,
            filter: `${soft > 0.05 ? `blur(${soft.toFixed(2)}px) ` : ""}brightness(${(1.04 + 0.24 * flash).toFixed(3)}) contrast(1.05)` }} />
          <AbsoluteFill style={{ background: `radial-gradient(${pool}, rgba(255,238,205,.14) 0%, rgba(255,238,205,0) 72%)` }} />
        </AbsoluteFill>
        <AbsoluteFill style={{ opacity: lamp,
          background: `radial-gradient(${pool}, rgba(0,0,0,0) 64%, ${withAlpha(accent, 0.2)} 86%, rgba(0,0,0,0) 100%)` }} />
        <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0 }}>
          <defs>
            <linearGradient id="paBeamG" gradientUnits="userSpaceOnUse" x1={Lx} y1={Ly} x2={px} y2={py}>
              <stop offset="0" stopColor="#fff4de" stopOpacity={0.34} />
              <stop offset="0.6" stopColor="#fff4de" stopOpacity={0.12} />
              <stop offset="1" stopColor="#fff4de" stopOpacity={0} />
            </linearGradient>
          </defs>
          <g opacity={lamp * (1 - q)}>
            <polygon points={wedge(1)} fill="url(#paBeamG)" opacity={0.45} />
            <polygon points={wedge(0.72)} fill="url(#paBeamG)" opacity={0.6} />
            <polygon points={wedge(0.42)} fill="url(#paBeamG)" opacity={0.8} />
            {/* dust drifting down the beam, fading at both ends */}
            {Array.from({ length: 18 }, (_, i) => {
              const uu = (rnd(i, 41) + frame * (0.0025 + rnd(i, 42) * 0.004)) % 1;
              const along = 0.3 + 0.7 * uu;
              const hw = w0 + (w1 - w0) * along;
              const vv = (rnd(i, 43) * 2 - 1) * 0.78 + 0.1 * Math.sin(t * (0.7 + rnd(i, 44)) + i);
              return <circle key={i} cx={Lx + dx * along + nx * vv * hw} cy={Ly + dy * along + ny * vv * hw}
                r={(1.1 + rnd(i, 45) * 2.2) * k} fill="#fff" opacity={(0.25 + 0.5 * rnd(i, 46)) * Math.sin(uu * Math.PI)} />;
            })}
          </g>
        </svg>
        <AbsoluteFill style={{ boxShadow: `inset 0 0 ${300 * k}px rgba(0,0,0,.65)` }} />
        {hasCap ? (
          <div style={{ position: "absolute", left: capX - 480 * k, width: 960 * k,
            ...(below ? { top: ty + RR + gapY } : { bottom: height - (ty - RR - gapY) }),
            display: "flex", flexDirection: "column", alignItems: "center" }}>
            {kick ? (
              <Letters text={kick} at={capAt} step={0.6} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 28 * k,
                letterSpacing: "0.3em", paddingLeft: "0.3em", color: accent, textShadow: "0 2px 14px rgba(0,0,0,.85)" }} />
            ) : null}
            <div style={{ width: 120 * k, height: 3 * k, margin: `${8 * k}px 0 ${12 * k}px`, background: accent,
              transform: `scaleX(${rule})`, boxShadow: `0 0 ${12 * k}px ${withAlpha(accent, 0.5)}` }} />
            {tl.map((ln, i) => (
              <Letters key={i} text={ln} at={capAt + 5 + i * 4} style={{ fontFamily: DISPLAY, fontSize: tsz * k, lineHeight: 1,
                color: "#fff", letterSpacing: "0.03em", textAlign: "center", textShadow: "0 4px 24px rgba(0,0,0,.9)" }} />
            ))}
          </div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 5 film strip
const FilmStrip: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const k = useK();
  const pics = stills(overlay, 4);
  if (!pics.length) return null;
  const n = 8, HERO = 3;
  const FW = 400 * k, FH = 268 * k, GAP = 34 * k, BAND = 50 * k, SH = FH + 2 * BAND;
  const pitch = FW + GAP, stripW = n * pitch + GAP;
  const heroLocal = GAP + HERO * pitch + FW / 2;
  const restX = width / 2 - heroLocal;
  const stripY = height / 2 - SH / 2 + 10 * k;
  // The race-in (quicker on a short graphic so the title still gets its hold).
  const S = Math.round(Math.min(fps * 1.2, Math.max(fps * 0.8, (durationInFrames - 60) * 0.8)));
  const travel = 2700 * k;
  // Strip position for any frame: races in, stops on the hero, drifts, races out.
  const X = (f: number): number => {
    const sp = ramp(f, 0, S);
    const drift = f > S ? (f - S) * 0.45 * k : 0;
    const out = ramp(f, durationInFrames - 14, 13, expoIn);
    return restX + (1 - sp) * travel - drift - out * 2500 * k;
  };
  const sx = X(frame);
  const speed = Math.abs(sx - X(frame - 1)) / Math.max(1e-6, k);
  const mblur = speed > 10 ? Math.min(7, speed * 0.05) : 0;
  const pull = ramp(frame, S - 6, Math.round(fps * 0.75));
  const dim = ramp(frame, S - 2, 18);
  const stripBlur = (mblur + dim * 2.5) * k;
  const stripFilter = stripBlur > 0.05 || dim > 0.01 ? `blur(${stripBlur.toFixed(2)}px) brightness(${(1 - 0.5 * dim).toFixed(3)})` : undefined;
  // The hero frame: tracks its slot, then is pulled out and enlarged as a print.
  const HW = 980 * k, HH = HW * (FH / FW);
  const heroY = 440 * k;
  const slotCx = sx + heroLocal, slotCy = stripY + BAND + FH / 2;
  const outH = ramp(frame, durationInFrames - 13, 12, expoIn);
  const hcx = interpolate(pull, [0, 1], [slotCx, width / 2]) - outH * 2300 * k;
  const hcy = interpolate(pull, [0, 1], [slotCy, heroY]);
  // Once pulled, the print keeps a slow push while it holds.
  const hs = interpolate(pull, [0, 1], [FW / HW, 1]) * (1 + 0.025 * interpolate(frame, [S, Math.max(S + 1, durationInFrames)], [0, 1], clamp));
  const heroFilter = pull < 0.02 && mblur > 0 ? `blur(${(mblur * k).toFixed(2)}px)` : undefined;
  const edgeLabels = itemsOf(overlay).map((it) => cap(it.label)).filter((s) => s.length > 0);
  const wrap = (i: number, m: number) => ((i % m) + m) % m;
  const edgeText = (s: number) => (edgeLabels.length ? edgeLabels[wrap(s - HERO, edgeLabels.length)] : `${14 + s}A`);
  const title = cap(overlay.text);
  const sub = cap(overlay.subtitle);
  const tl = lines(title, 36).slice(0, 2);
  const tsz = tl.length > 1 ? 52 : 64;
  const capAt = S + 8;
  const q = ramp(frame, durationInFrames - 13, 12, expoIn);
  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 42%, #2b2520 0%, #141113 52%, #060506 100%)", overflow: "hidden" }}>
      <AbsoluteFill style={{ background: `radial-gradient(ellipse at 50% 38%, ${withAlpha(accent, 0.12)} 0%, rgba(0,0,0,0) 55%)`, opacity: pull }} />
      <div style={{ position: "absolute", left: sx, top: stripY, width: stripW, height: SH, filter: stripFilter,
        background: "linear-gradient(180deg, #17120e 0%, #241c15 50%, #17120e 100%)", boxShadow: `0 ${30 * k}px ${70 * k}px rgba(0,0,0,.6)` }}>
        <svg width={stripW} height={SH} style={{ position: "absolute", left: 0, top: 0 }}>
          <defs>
            <pattern id="paSprTop" x={0} y={0} width={30 * k} height={BAND} patternUnits="userSpaceOnUse">
              <rect x={8 * k} y={BAND * 0.3} width={14 * k} height={BAND * 0.38} rx={3 * k} fill="#060505" />
            </pattern>
            <pattern id="paSprBot" x={0} y={BAND + FH} width={30 * k} height={BAND} patternUnits="userSpaceOnUse">
              <rect x={8 * k} y={BAND * 0.44} width={14 * k} height={BAND * 0.38} rx={3 * k} fill="#060505" />
            </pattern>
          </defs>
          <rect x={0} y={0} width={stripW} height={BAND} fill="url(#paSprTop)" />
          <rect x={0} y={BAND + FH} width={stripW} height={BAND} fill="url(#paSprBot)" />
        </svg>
        {Array.from({ length: n }, (_, s) => {
          const fx = GAP + s * pitch;
          return (
            <React.Fragment key={s}>
              <div style={{ position: "absolute", left: fx, top: BAND, width: FW, height: FH, background: "#050404", overflow: "hidden",
                boxShadow: "inset 0 0 0 1px rgba(255,255,255,.07)" }}>
                {s !== HERO ? (
                  <SafeImg src={pics[wrap(s - HERO, pics.length)]} style={{ width: "100%", height: "100%", objectFit: "cover",
                    filter: "sepia(.2) contrast(1.06) saturate(.9)" }} />
                ) : null}
              </div>
              <div style={{ position: "absolute", left: fx + 6 * k, top: BAND + FH + 3 * k, fontFamily: MONO, fontWeight: 700, fontSize: 18 * k,
                lineHeight: 1, letterSpacing: "0.12em", color: accent, opacity: 0.72, whiteSpace: "nowrap" }}>{`▸ ${edgeText(s)}`}</div>
            </React.Fragment>
          );
        })}
      </div>
      <div style={{ position: "absolute", left: hcx, top: hcy, width: HW, height: HH, boxSizing: "border-box",
        border: `${12 * k * pull}px solid #f2eee5`, background: "#050404", overflow: "hidden", filter: heroFilter,
        transform: `translate(-50%, -50%) scale(${hs}) rotate(${-1.6 * pull}deg)`,
        boxShadow: `0 ${40 * pull * k}px ${90 * pull * k}px rgba(0,0,0,${(0.65 * pull).toFixed(3)})` }}>
        <SafeImg src={pics[0]} style={{ width: "100%", height: "100%", objectFit: "cover", filter: `sepia(${(0.2 * (1 - pull)).toFixed(3)}) contrast(1.05)` }} />
      </div>
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${300 * k}px rgba(0,0,0,.7)` }} />
      {tl.length || sub ? (
        <div style={{ position: "absolute", left: 0, right: 0, top: 818 * k, display: "flex", flexDirection: "column", alignItems: "center", gap: 6 * k }}>
          {tl.map((ln, i) => (
            <Letters key={i} text={ln} at={capAt + i * 4} style={{ fontFamily: DISPLAY, fontSize: tsz * k, color: "#fff", letterSpacing: "0.04em",
              lineHeight: 1, textAlign: "center", textShadow: "0 6px 24px rgba(0,0,0,.6)" }} />
          ))}
          {sub ? (
            <div style={{ display: "flex", alignItems: "center", gap: 14 * k }}>
              <div style={{ width: ramp(frame, capAt + 6, 14) * (1 - q) * 34 * k, height: 2 * k, background: accent }} />
              <Letters text={sub} at={capAt + 6} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 28 * k, letterSpacing: "0.26em",
                color: "rgba(255,255,255,.78)" }} />
              <div style={{ width: ramp(frame, capAt + 6, 14) * (1 - q) * 34 * k, height: 2 * k, background: accent }} />
            </div>
          ) : null}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== 6 mosaic assemble
const MosaicAssemble: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, durationInFrames } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const q = useOutQ(12);
  const pics = stills(overlay, 1);
  if (!pics.length) return null;
  const src = pics[0];
  const COLS = 8, ROWS = 5;
  const PW = 1240 * k, PH = 698 * k;
  const L = (width - PW) / 2, T = 128 * k;
  const tw = PW / COLS, th = PH / ROWS;
  const seam = (1 - ramp(frame, 30, 14)) * 4 * k;
  const frameDraw = ramp(frame, 34, 22, inOut) * (1 - ramp(frame, durationInFrames - 16, 10, expoIn));
  const sweep = ramp(frame, 36, 26, inOut);
  const title = cap(overlay.text);
  const sub = cap(overlay.subtitle);
  const tl = lines(title, 30).slice(0, 2);
  const tsz = tl.length > 1 ? 52 : 64;
  // The caption steps in as the seams close (earlier on a short graphic).
  const capAt = Math.min(40, Math.round(durationInFrames * 0.36));
  const bgPush = interpolate(frame, [0, Math.max(1, durationInFrames)], [1.18, 1.23], clamp);
  const M = 14 * k;
  return (
    <AbsoluteFill style={{ background: "#08090b", overflow: "hidden" }}>
      <SafeImg src={src} style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "100%", objectFit: "cover",
        transform: `scale(${bgPush})`, filter: `blur(${36 * k}px) brightness(.34) saturate(.8)` }} />
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 45%, rgba(0,0,0,.1) 0%, rgba(0,0,0,.65) 100%)" }} />
      <div style={{ position: "absolute", left: L, top: T, width: PW, height: PH, perspective: 1500 * k, transform: `scale(${hold})` }}>
        {Array.from({ length: COLS * ROWS }, (_, i) => {
          const c = i % COLS, r = Math.floor(i / COLS);
          const order = (c + r * 1.4) / (COLS - 1 + (ROWS - 1) * 1.4);
          const st = 2 + order * 16 + rnd(i, 5) * 4;
          const p = ramp(frame, st, 16);
          const o = ramp(frame, st, 4);
          const g = ramp(frame, durationInFrames - 17 + rnd(i, 8) * 5, 11, expoIn);
          const f = 1 - p;
          const dx = (((c + 0.5) / COLS - 0.5) * 900 + (rnd(i, 1) - 0.5) * 700) * k;
          const dy = (((r + 0.5) / ROWS - 0.5) * 600 + (rnd(i, 2) - 0.5) * 500) * k;
          const dz = (350 + rnd(i, 3) * 600) * k;
          const rz = (rnd(i, 4) - 0.5) * 70, rxx = (rnd(i, 6) - 0.5) * 150, ryy = (rnd(i, 7) - 0.5) * 150;
          const m = f + g * 0.9;
          const l = c * tw + seam / 2, tp = r * th + seam / 2;
          const shade = 0.45 * f + 0.35 * g;
          return (
            <div key={i} style={{ position: "absolute", left: l, top: tp, width: tw - seam + 0.6, height: th - seam + 0.6, overflow: "hidden",
              opacity: o * (1 - g),
              transform: `translate3d(${dx * m}px, ${dy * m}px, ${dz * (f + g * 1.1)}px) rotateX(${rxx * (f + g)}deg) rotateY(${ryy * (f + g)}deg) rotateZ(${rz * (f + g)}deg)`,
              boxShadow: f > 0.02 ? `0 ${10 * k}px ${24 * k}px rgba(0,0,0,${(0.5 * f).toFixed(3)})` : undefined }}>
              <SafeImg src={src} style={{ position: "absolute", left: -l, top: -tp, width: PW, height: PH, objectFit: "cover", maxWidth: "none" }} />
              {shade > 0.01 ? <div style={{ position: "absolute", inset: 0, background: "#000", opacity: shade }} /> : null}
            </div>
          );
        })}
        <div style={{ position: "absolute", inset: 0, overflow: "hidden", opacity: 1 - q }}>
          {sweep > 0 && sweep < 1 ? (
            <div style={{ position: "absolute", top: "-20%", bottom: "-20%", width: "22%", left: `${-30 + 150 * sweep}%`,
              background: "linear-gradient(90deg, rgba(255,255,255,0), rgba(255,255,255,.26), rgba(255,255,255,0))", transform: "skewX(-18deg)" }} />
          ) : null}
        </div>
        <svg width={PW + 2 * M} height={PH + 2 * M} style={{ position: "absolute", left: -M, top: -M, overflow: "visible" }}>
          <path d={`M${M} ${M} H${PW + M} V${PH + M} H${M} Z`} fill="none" stroke="rgba(255,255,255,.85)" strokeWidth={2 * k}
            pathLength={1} strokeDasharray={1} strokeDashoffset={1 - frameDraw} />
          <path d={`M${M - 8 * k} ${M + 46 * k} V${M - 8 * k} H${M + 46 * k}`} fill="none" stroke={accent} strokeWidth={5 * k}
            opacity={frameDraw} />
          <path d={`M${PW + M + 8 * k} ${PH + M - 46 * k} V${PH + M + 8 * k} H${PW + M - 46 * k}`} fill="none" stroke={accent}
            strokeWidth={5 * k} opacity={frameDraw} />
        </svg>
      </div>
      {tl.length || sub ? (
        // 46 px below the picture: its hold push (x1.035) and the corner marks
        // (22 px out) would otherwise touch the title by the end.
        <div style={{ position: "absolute", left: L, width: PW, top: T + PH + 46 * k, display: "flex", justifyContent: "space-between",
          alignItems: "flex-start", gap: 40 * k }}>
          <div style={{ display: "flex", flexDirection: "column" }}>
            {tl.map((ln, i) => (
              <Letters key={i} text={ln} at={capAt + i * 4} style={{ fontFamily: DISPLAY, fontSize: tsz * k, lineHeight: 1, color: "#fff",
                letterSpacing: "0.03em", textShadow: "0 6px 24px rgba(0,0,0,.6)" }} />
            ))}
          </div>
          {sub ? (
            <div style={{ display: "flex", alignItems: "center", gap: 12 * k, marginTop: 16 * k }}>
              <div style={{ width: 12 * k, height: 12 * k, background: accent, transform: `scale(${ramp(frame, capAt + 4, 10, backOut) * (1 - q)})` }} />
              <Letters text={sub} at={capAt + 6} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 28 * k, letterSpacing: "0.22em",
                color: "rgba(255,255,255,.8)" }} />
            </div>
          ) : null}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== 7 torn paper reveal
const TornReveal: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const k = useK();
  const q = useOutQ(15);
  const X = 0.4 * width;
  // How far the sheet reaches left of its edge: enough to cover the frame at
  // frame 0 (edge 0.6w + 260 right of X), without a needlessly huge filtered layer.
  const FAR = 1700 * k;
  // The torn edge: a slight tilt, slow waves, and seeded jitter; the white
  // fibrous core of the tear (rim) sits a few px proud of the paper body.
  const paths = React.useMemo(() => {
    const edgeAt = (yy: number) => X + 0.07 * (yy - height / 2) + Math.sin(yy / (95 * k)) * 8 * k + Math.sin(yy / (41 * k) + 1.3) * 4 * k;
    const y0 = -60 * k, y1 = height + 60 * k;
    const body: string[] = [];
    const rim: string[] = [];
    let j = 0;
    for (let yy = y0; yy <= y1; yy += Math.max(1, 15 * k), j++) {
      body.push(`${(edgeAt(yy) + (rnd(j, 11) - 0.5) * 14 * k).toFixed(1)} ${yy.toFixed(1)}`);
    }
    j = 0;
    for (let yy = y0; yy <= y1; yy += Math.max(1, 7 * k), j++) {
      rim.push(`${(edgeAt(yy) + (4 + rnd(j, 13) * 13) * k).toFixed(1)} ${yy.toFixed(1)}`);
    }
    const close = `L${(-FAR).toFixed(1)} ${y1.toFixed(1)} L${(-FAR).toFixed(1)} ${y0.toFixed(1)} Z`;
    return { body: `M${body.join(" L")} ${close}`, rim: `M${rim.join(" L")} ${close}` };
  }, [X, FAR, height, k]);
  const pics = stills(overlay, 1);
  if (!pics.length) return null;
  const slide = ramp(frame, 2, Math.round(fps * 0.8), Easing.bezier(0.55, 0, 0.1, 1));
  const tx = (1 - slide) * (width - X + 260 * k) - q * (X + 440 * k);
  const push = interpolate(frame, [0, Math.max(1, durationInFrames)], [1.14, 1.05], clamp);
  // The photo sits right of the panel and slides home as the paper leaves; its
  // own left edge must never show past the torn edge (which reaches ~60 px left
  // of X + tx at the top), or a dark gap opens during the exit.
  const want = interpolate(slide, [0, 1], [0.27, 0.2]) * width * (1 - q);
  const shift = Math.max(0, Math.min(want, X + tx - 64 * k + ((push - 1) * width) / 2));
  const title = cap(overlay.text);
  const kick = cap(overlay.label);
  const sub = str(overlay.subtitle);
  const tl = lines(title, 13).slice(0, 4);
  const tsz = tl.length > 3 ? 70 : 84;
  const W2 = FAR + width;
  const titleEnd = 16 + tl.length * 4;
  return (
    <AbsoluteFill style={{ background: "#0a0a0b", overflow: "hidden" }}>
      <SafeImg src={pics[0]} style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "100%", objectFit: "cover",
        transform: `translateX(${shift}px) scale(${push})`, filter: "saturate(.95) contrast(1.04)" }} />
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${260 * k}px rgba(0,0,0,.45)` }} />
      <AbsoluteFill style={{ transform: `translateX(${tx}px)` }}>
        <svg width={W2} height={height} viewBox={`${-FAR} 0 ${W2} ${height}`}
          style={{ position: "absolute", left: -FAR, top: 0, filter: `drop-shadow(${12 * k}px 0 ${20 * k}px rgba(0,0,0,.55))` }}>
          <defs>
            <linearGradient id="paPaperG" gradientUnits="userSpaceOnUse" x1={0} y1={0} x2={X} y2={height}>
              <stop offset="0" stopColor="#f2ede2" />
              <stop offset="1" stopColor="#e1d9c7" />
            </linearGradient>
            <pattern id="paPaperT" width={18 * k} height={18 * k} patternUnits="userSpaceOnUse" patternTransform="rotate(32)">
              <line x1={0} y1={0} x2={18 * k} y2={0} stroke="rgba(110,90,60,.07)" strokeWidth={1.2 * k} />
            </pattern>
            <radialGradient id="paPaperL" gradientUnits="userSpaceOnUse" cx={X * 0.35} cy={height * 0.3} r={X * 1.1}>
              <stop offset="0" stopColor="rgba(255,255,255,.35)" />
              <stop offset="1" stopColor="rgba(255,255,255,0)" />
            </radialGradient>
          </defs>
          <path d={paths.rim} fill="#fbf9f3" />
          <path d={paths.body} fill="url(#paPaperG)" stroke="rgba(120,100,70,.3)" strokeWidth={1.2 * k} />
          <path d={paths.body} fill="url(#paPaperT)" />
          <path d={paths.body} fill="url(#paPaperL)" />
        </svg>
        <div style={{ position: "absolute", left: 120 * k, width: X - 230 * k, top: 0, bottom: 0, display: "flex", flexDirection: "column",
          justifyContent: "center", gap: 8 * k }}>
          {kick ? (
            <div style={{ display: "flex", alignItems: "center", gap: 12 * k, marginBottom: 6 * k }}>
              <div style={{ width: 10 * k, height: 10 * k, background: accent, transform: `scale(${ramp(frame, 14, 10, backOut)})` }} />
              <Letters text={kick} at={14} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 26 * k, letterSpacing: "0.26em", color: "#6a6254" }} />
            </div>
          ) : null}
          {tl.map((ln, i) => (
            <Letters key={i} text={ln} at={16 + i * 4} style={{ fontFamily: DISPLAY, fontSize: tsz * k, lineHeight: 0.96, color: "#15161a",
              letterSpacing: "0.015em" }} />
          ))}
          {tl.length ? (
            <div style={{ width: ramp(frame, titleEnd + 4, 16) * (1 - ramp(frame, durationInFrames - 16, 10, expoIn)) * 90 * k, height: 6 * k,
              background: accent, margin: `${10 * k}px 0 ${8 * k}px` }} />
          ) : null}
          {sub ? lines(sub, 34).slice(0, 4).map((ln, i) => (
            <Rise key={i} at={titleEnd + 8 + i * 3}>
              <span style={{ fontFamily: INTER, fontWeight: 400, fontSize: 27 * k, lineHeight: 1.4, color: "#3a3833", whiteSpace: "nowrap" }}>{ln}</span>
            </Rise>
          )) : null}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 8 magnifier lens
const LoupeZoom: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const q = useOutQ(13);
  const pics = stills(overlay, 1);
  if (!pics.length) return null;
  const src = pics[0];
  const [ax, ay] = anchorOf(overlay, 0.6, 0.45, 0.3, 0.7);
  const tx = ax * width, ty = ay * height;
  // The loupe glides in on an arc from below, lands on the detail, the zoom
  // pulls in (a quicker glide on a short graphic so the label gets its hold).
  const A = Math.round(Math.min(fps * 1.05, Math.max(fps * 0.75, (durationInFrames - 60) * 0.7)));
  const u = ramp(frame, 0, A, inOut);
  const [bx, by] = bez([0.1 * width, 1.28 * height], [0.08 * width, 0.42 * height], [tx - 0.3 * width, ty - 0.24 * height], [tx, ty], u);
  const t = frame / fps;
  const idle = ramp(frame, A - 4, fps);
  const lx = bx + idle * 14 * k * Math.sin(t * 1.25);
  const ly = by + idle * 10 * k * Math.sin(t * 1.9 + 0.6);
  const cx = lx + q * 0.6 * width, cy = ly + q * 0.8 * height;
  const settle = ramp(frame, A - 8, 20, backOut);
  const z = 1.3 + settle;
  const R = 215 * k;
  const right = tx < width / 2;
  const dir = right ? 1 : -1;
  const lx0 = lx + dir * (R + 12 * k);
  const LL = 90 * k;
  const ld = ramp(frame, A + 4, 14, inOut) * (1 - ramp(frame, durationInFrames - 15, 10, expoIn));
  const chip = ramp(frame, A - 2, 12);
  const title = cap(overlay.text);
  const kick = cap(overlay.subtitle);
  const tl = lines(title, 16).slice(0, 3);
  const labAt = A + 10;
  const hasLabel = tl.length > 0 || kick.length > 0;
  return (
    <AbsoluteFill style={{ background: "#07080a", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${hold})` }}>
        <SafeImg src={src} style={{ position: "absolute", left: 0, top: 0, width, height, objectFit: "cover", filter: "brightness(.72) saturate(.85)" }} />
        <AbsoluteFill style={{ boxShadow: `inset 0 0 ${320 * k}px rgba(0,0,0,.7)` }} />
        {hasLabel ? (
          <>
            <div style={{ position: "absolute", left: right ? lx0 : lx0 - LL * ld, top: ly - k, width: LL * ld, height: 0,
              borderTop: `${2 * k}px dashed rgba(255,255,255,.85)` }} />
            <div style={{ position: "absolute", ...(right ? { left: lx0 + LL + 16 * k } : { right: width - (lx0 - LL) + 16 * k }), top: ly,
              transform: "translateY(-50%)", display: "flex", flexDirection: "column", alignItems: right ? "flex-start" : "flex-end", gap: 6 * k }}>
              {kick ? <Letters text={kick} at={labAt} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 26 * k, letterSpacing: "0.24em",
                color: accent, textShadow: "0 2px 12px rgba(0,0,0,.8)" }} /> : null}
              {tl.map((ln, i) => (
                <Letters key={i} text={ln} at={labAt + 3 + i * 4} style={{ fontFamily: DISPLAY, fontSize: 60 * k, lineHeight: 1, color: "#fff",
                  letterSpacing: "0.03em", textAlign: right ? "left" : "right", textShadow: "0 4px 22px rgba(0,0,0,.85)" }} />
              ))}
            </div>
          </>
        ) : null}
        <div style={{ position: "absolute", left: cx - R, top: cy - R, width: 2 * R, height: 2 * R }}>
          <div style={{ position: "absolute", inset: 0, borderRadius: "50%", overflow: "hidden", background: "#111" }}>
            <SafeImg src={src} style={{ position: "absolute", left: R - cx * z, top: R - cy * z, width: width * z, height: height * z,
              objectFit: "cover", maxWidth: "none", filter: "brightness(1.08) contrast(1.06)" }} />
            <div style={{ position: "absolute", inset: 0, borderRadius: "50%", background: "radial-gradient(circle at 50% 50%, rgba(0,0,0,0) 58%, rgba(0,0,0,.42) 100%)" }} />
            <div style={{ position: "absolute", inset: 0, borderRadius: "50%", background: "radial-gradient(circle at 32% 26%, rgba(255,255,255,.34) 0%, rgba(255,255,255,0) 32%)" }} />
          </div>
          <div style={{ position: "absolute", inset: -9 * k, borderRadius: "50%", border: `${9 * k}px solid #eef0f2`,
            boxShadow: `0 ${26 * k}px ${60 * k}px rgba(0,0,0,.55), inset 0 0 0 ${2 * k}px rgba(0,0,0,.25), 0 0 0 ${1.5 * k}px rgba(0,0,0,.35)` }} />
          <div style={{ position: "absolute", inset: 4 * k, borderRadius: "50%", boxShadow: `inset 0 0 0 ${3 * k}px ${accent}`, opacity: Math.min(1, settle) }} />
          {hasLabel ? (
            <div style={{ position: "absolute", left: R + dir * (R + 12 * k) - 7 * k, top: R - 7 * k, width: 14 * k, height: 14 * k, borderRadius: "50%",
              background: accent, transform: `scale(${ld})` }} />
          ) : null}
          <div style={{ position: "absolute", left: R + R * 0.72 + 4 * k, top: R + R * 0.72 + 4 * k, padding: `${5 * k}px ${12 * k}px`,
            background: "rgba(8,9,12,.78)", border: `${1.5 * k}px solid rgba(255,255,255,.5)`, borderRadius: 6 * k, fontFamily: MONO, fontWeight: 700,
            fontSize: 24 * k, lineHeight: 1, color: "#fff", letterSpacing: "0.06em", whiteSpace: "nowrap",
            clipPath: `inset(0 ${((1 - chip) * 100).toFixed(1)}% 0 0)` }}>{`×${z.toFixed(1)}`}</div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 9 scan ID frame
const ScanID: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const pics = stills(overlay, 1);
  if (!pics.length) return null;
  const src = pics[0];
  const name = cap(overlay.text);
  const header = cap(overlay.subtitle) || "SUBJECT SCAN";
  const allLocs: MapLocation[] = Array.isArray(overlay.locations) ? overlay.locations : [];
  const locs = allLocs.filter((l) => !!l && typeof l === "object" && Number.isFinite(l.lat) && Number.isFinite(l.lon));
  const loc = locs[0];
  const mv = typeof overlay.value === "number" ? overlay.value : Number.NaN;
  const hasMatch = Number.isFinite(mv);
  const suffix = str(overlay.suffix);
  const pct = hasMatch && suffix === "%" ? Math.max(0, Math.min(100, mv)) : null;
  // Mono readouts never wrap, so every string is clipped to what its column holds.
  const clip = (s: string, n: number): string => (s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s);
  const metric = hasMatch ? clip(cap(overlay.label) || (pct !== null ? "MATCH" : "READING"), 40) : "";
  // "726 FT" (a hard space: a leading plain space collapses in the flex row), "27%", "12M".
  const unit = suffix.length > 1 ? `${String.fromCharCode(160)}${suffix}` : suffix;
  type Row = { label: string; value: string };
  const rows: Row[] = itemsOf(overlay)
    .map((it) => ({ label: clip(cap(it.label), 16), value: clip(cap(itemValue(it)), 30) }))
    .filter((r) => r.label.length > 0 && r.value.length > 0)
    .slice(0, 4);
  if (!rows.length && loc && str(loc.label)) rows.push({ label: "LOCATION", value: clip(cap(loc.label), 30) });
  if (loc && rows.length < 4) rows.push({ label: "COORDS", value: coordText(loc) });
  if (!hasMatch && str(overlay.label) && rows.length < 4) rows.push({ label: "RECORD", value: clip(cap(overlay.label), 30) });
  // Label column sized to the longest label (mono 22 px: 0.6 em advance + 0.2 em tracking).
  const labW = Math.min(300, Math.max(150, Math.max(6, ...rows.map((r) => r.label.length)) * 17.6 + 24)) * k;

  const PX = 170 * k, PY = 170 * k, PW = 600 * k, PH = 740 * k;
  const RX = 880 * k, RW = 860 * k;
  const t = frame / fps;
  const typed = (s: string, at: number, cps: number) => s.slice(0, Math.max(0, Math.floor((frame - at) * cps)));
  // Brackets lock on, the first scan resolves the picture, fainter passes loop after.
  const brk = ramp(frame, 2, 14);
  const lockPulse = ramp(frame, 16, 10) * Math.sin(t * 4) * 2 * k;
  const scanStart = 8, scanDur = Math.round(fps * 1.1);
  const scan = ramp(frame, scanStart, scanDur, inOut);
  const firstDone = frame >= scanStart + scanDur;
  const period = Math.max(1, Math.round(fps * 1.8));
  const loopP = firstDone ? ((frame - scanStart - scanDur) % period) / period : 0;
  const lineY = (firstDone ? loopP : scan) * PH;
  const lineOp = firstDone ? 0.35 : scan > 0 && scan < 1 ? 1 : 0;
  const det = ramp(frame, scanStart + Math.round(scanDur * 0.7), 16, inOut);
  const tagP = ramp(frame, scanStart + Math.round(scanDur * 0.7) + 10, 10);
  const push = interpolate(frame, [0, Math.max(1, durationInFrames)], [1.03, 1.1], clamp);
  const idTag = `ID-${1000 + (hashStr(name || src) % 9000)}  ·  LOCK`;
  const bxx = 0.24 * PW, byy = 0.12 * PH, bw = 0.52 * PW, bh = 0.4 * PH;
  const nl = lines(name, 18).slice(0, 2);
  const nsz = nl.length > 1 ? 68 : 84;
  // Rows type in one after another and the reading rolls last; on a short
  // graphic the rows come faster so the roll still lands before the collapse.
  const tail = durationInFrames - 13;
  const rowsAt = 24;
  const rowStep = Math.max(4, Math.min(8, Math.floor((tail - rowsAt - 36) / Math.max(1, rows.length))));
  const matchAt = rowsAt + rows.length * rowStep + 6;
  const rollF = Math.max(12, Math.min(Math.round(fps * 1.1), tail - matchAt - 4));
  const fill = ramp(frame, matchAt, rollF, inOut) * ((pct ?? 0) / 100);
  const SEG = 24;
  // The end: the screen collapses like a CRT switching off.
  const c1 = ramp(frame, durationInFrames - 13, 7, expoIn);
  const c2 = ramp(frame, durationInFrames - 6, 5, expoIn);
  const Mg = 80 * k;
  const g = 16 * k + (1 - brk) * 60 * k + lockPulse;
  const len = 56 * k;
  const corner = (x0: number, y0: number, dx: number, dy: number, i: number) => (
    <path key={i} d={`M${x0 + dx * len} ${y0} L${x0} ${y0} L${x0} ${y0 + dy * len}`} fill="none" stroke={CYAN} strokeWidth={4 * k}
      strokeLinecap="square" />
  );
  const imgStyle: React.CSSProperties = { position: "absolute", left: 0, top: 0, width: "100%", height: "100%", objectFit: "cover",
    transform: `scale(${push})` };
  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 30% 45%, #0c1a2a 0%, #060b13 55%, #020408 100%)", overflow: "hidden" }}>
      <AbsoluteFill style={{ backgroundImage: `linear-gradient(rgba(83,200,255,.07) 1px, rgba(0,0,0,0) 1px), linear-gradient(90deg, rgba(83,200,255,.07) 1px, rgba(0,0,0,0) 1px)`,
        backgroundSize: `${60 * k}px ${60 * k}px`, opacity: ramp(frame, 0, 10) }} />
      <AbsoluteFill style={{ background: `radial-gradient(ellipse at ${((PX + PW / 2) / (1920 * k)) * 100}% 50%, rgba(83,200,255,.12) 0%, rgba(0,0,0,0) 45%)` }} />
      <AbsoluteFill style={{ transform: `scale(${Math.max(0.001, 1 - c2)}, ${Math.max(0.002, 1 - 0.985 * c1)})`,
        filter: c1 > 0.001 ? `brightness(${(1 + 2.2 * c1).toFixed(3)})` : undefined }}>
        <div style={{ position: "absolute", left: PX, top: PY, width: PW, height: PH, overflow: "hidden", background: "#050a10",
          boxShadow: `0 0 0 ${Math.max(1, k)}px rgba(83,200,255,.28), 0 ${30 * k}px ${80 * k}px rgba(0,0,0,.6)` }}>
          <SafeImg src={src} style={{ ...imgStyle, filter: "grayscale(1) contrast(1.35) brightness(.5)" }} />
          <div style={{ position: "absolute", inset: 0, background: CYAN, mixBlendMode: "color", opacity: 0.75 }} />
          <div style={{ position: "absolute", inset: 0, clipPath: `inset(0 0 ${((1 - scan) * 100).toFixed(2)}% 0)` }}>
            <SafeImg src={src} style={{ ...imgStyle, filter: "contrast(1.06) saturate(.92)" }} />
          </div>
          <div style={{ position: "absolute", inset: 0, backgroundImage: `repeating-linear-gradient(0deg, rgba(0,0,0,.2) 0px, rgba(0,0,0,.2) ${2 * k}px, rgba(0,0,0,0) ${2 * k}px, rgba(0,0,0,0) ${5 * k}px)` }} />
          <div style={{ position: "absolute", left: 0, right: 0, top: lineY - 120 * k, height: 120 * k, opacity: lineOp,
            background: "linear-gradient(180deg, rgba(83,200,255,0) 0%, rgba(83,200,255,.24) 100%)" }} />
          <div style={{ position: "absolute", left: 0, right: 0, top: lineY - 1.5 * k, height: 3 * k, background: CYAN, opacity: lineOp,
            boxShadow: `0 0 ${18 * k}px ${CYAN}` }} />
          <svg width={PW} height={PH} style={{ position: "absolute", left: 0, top: 0 }}>
            <path d={`M${bxx} ${byy} H${bxx + bw} V${byy + bh} H${bxx} Z`} fill="none" stroke={CYAN} strokeWidth={2 * k}
              pathLength={1} strokeDasharray={1} strokeDashoffset={1 - det} />
            <g stroke="#fff" strokeWidth={2 * k} opacity={det}>
              <line x1={bxx + bw / 2 - 16 * k} y1={byy + bh / 2} x2={bxx + bw / 2 + 16 * k} y2={byy + bh / 2} />
              <line x1={bxx + bw / 2} y1={byy + bh / 2 - 16 * k} x2={bxx + bw / 2} y2={byy + bh / 2 + 16 * k} />
            </g>
            <g stroke="rgba(83,200,255,.35)" strokeWidth={Math.max(1, k)}>
              <line x1={0} y1={byy + bh / 2} x2={PW * det} y2={byy + bh / 2} />
              <line x1={bxx + bw / 2} y1={0} x2={bxx + bw / 2} y2={PH * det} />
            </g>
          </svg>
          <div style={{ position: "absolute", left: bxx, top: byy - 34 * k, padding: `${5 * k}px ${10 * k}px`, background: CYAN, color: "#03121d",
            fontFamily: MONO, fontWeight: 700, fontSize: 20 * k, lineHeight: 1, letterSpacing: "0.12em", whiteSpace: "pre",
            clipPath: `inset(0 ${((1 - tagP) * 100).toFixed(1)}% 0 0)` }}>{idTag}</div>
        </div>
        <svg width={PW + 2 * Mg} height={PH + 2 * Mg} style={{ position: "absolute", left: PX - Mg, top: PY - Mg }}>
          <g opacity={brk}>
            {corner(Mg - g, Mg - g, 1, 1, 0)}
            {corner(Mg + PW + g, Mg - g, -1, 1, 1)}
            {corner(Mg - g, Mg + PH + g, 1, -1, 2)}
            {corner(Mg + PW + g, Mg + PH + g, -1, -1, 3)}
          </g>
        </svg>
        <div style={{ position: "absolute", left: RX, top: PY + 16 * k, width: RW, display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 * k, fontFamily: MONO, fontWeight: 700, fontSize: 24 * k,
            letterSpacing: "0.28em", color: CYAN, lineHeight: 1 }}>
            <div style={{ width: 12 * k, height: 12 * k, background: CYAN, opacity: Math.floor(frame / Math.max(1, fps * 0.4)) % 2 === 0 ? 1 : 0.25 }} />
            <span style={{ whiteSpace: "pre" }}>{typed(header, 4, 1.5)}</span>
          </div>
          {nl.length ? (
            <div style={{ marginTop: 20 * k }}>
              {nl.map((ln, i) => (
                <Letters key={i} text={ln} at={10 + i * 4} style={{ fontFamily: DISPLAY, fontSize: nsz * k, lineHeight: 0.98, color: "#fff",
                  letterSpacing: "0.03em" }} />
              ))}
            </div>
          ) : null}
          <div style={{ marginTop: 16 * k, height: 2 * k, width: `${ramp(frame, 16, 20, inOut) * 100}%`,
            background: "linear-gradient(90deg, #53c8ff 0%, rgba(83,200,255,.12) 100%)" }} />
          {rows.map((r, i) => {
            const at = rowsAt + i * rowStep;
            const shown = typed(r.value, at + 3, 1.6);
            const typing = frame >= at + 3 && shown.length < r.value.length;
            return (
              <div key={i} style={{ position: "relative", display: "flex", alignItems: "baseline", gap: 20 * k, padding: `${14 * k}px 0`,
                opacity: frame >= at ? 1 : 0 }}>
                <span style={{ width: labW, flexShrink: 0, overflow: "hidden", fontFamily: MONO, fontWeight: 500, fontSize: 22 * k,
                  letterSpacing: "0.2em", color: "rgba(83,200,255,.78)", whiteSpace: "pre" }}>{typed(r.label, at, 2.4)}</span>
                <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 30 * k, color: "#fff", letterSpacing: "0.02em", whiteSpace: "pre",
                  overflow: "hidden", textOverflow: "ellipsis", maxWidth: RW - labW - 20 * k }}>
                  {shown}{typing ? <span style={{ color: CYAN }}>{"▌"}</span> : null}
                </span>
                <div style={{ position: "absolute", left: 0, bottom: 0, height: Math.max(1, k), width: `${ramp(frame, at, 14) * 100}%`,
                  background: "rgba(83,200,255,.2)" }} />
              </div>
            );
          })}
          {hasMatch ? (
            // The reading's label gets its own line: a long label beside the
            // 24-segment meter pushed the row past the right edge of the frame.
            <div style={{ marginTop: 26 * k, display: "flex", flexDirection: "column", gap: 10 * k, opacity: frame >= matchAt ? 1 : 0 }}>
              <span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 22 * k, letterSpacing: "0.2em", color: "rgba(83,200,255,.78)",
                whiteSpace: "pre" }}>{typed(metric, matchAt, 2.4)}</span>
              <div style={{ display: "flex", alignItems: "flex-end", gap: 34 * k }}>
                <Odometer value={mv} at={matchAt} frames={rollF} size={60 * k} color="#fff" font={MONO}
                  prefix={str(overlay.prefix)} suffix={unit} suffixColor={CYAN} suffixScale={0.5} />
                {pct !== null ? (
                  <div style={{ display: "flex", gap: 5 * k, paddingBottom: 8 * k }}>
                    {Array.from({ length: SEG }, (_, j) => {
                      const litSeg = (j + 1) / SEG <= fill + 1e-6;
                      return <div key={j} style={{ width: 15 * k, height: 34 * k, background: litSeg ? CYAN : "rgba(83,200,255,.14)",
                        boxShadow: litSeg ? `0 0 ${10 * k}px rgba(83,200,255,.55)` : undefined }} />;
                    })}
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}
        </div>
      </AbsoluteFill>
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${280 * k}px rgba(0,0,0,.7)` }} />
    </AbsoluteFill>
  );
};

// ================================================================== 10 ken burns vignette
const KenBurns: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, height, durationInFrames } = useVideoConfig();
  const k = useK();
  const q = useOutQ(13);
  const pics = stills(overlay, 1);
  if (!pics.length) return null;
  const src = pics[0];
  // The push direction is chosen by the picture itself: steady for a re-render.
  const DIRS: Pt[] = [[-1, -0.6], [1, -0.5], [-0.9, 0.5], [0.8, 0.55]];
  const dir = DIRS[hashStr(src) % 4];
  const p = interpolate(frame, [0, Math.max(1, durationInFrames)], [0, 1], { ...clamp, easing: Easing.bezier(0.33, 0, 0.67, 1) });
  const sc = 1.08 + 0.12 * p;
  const px = dir[0] * 2.4 * p, py = dir[1] * 1.8 * p;
  const up = ramp(frame, 0, 14);
  const bars = ramp(frame, 2, 18) * (1 - ramp(frame, durationInFrames - 14, 12, expoIn));
  const bh = 66 * k * bars;
  const title = cap(overlay.text);
  const kick = cap(overlay.subtitle);
  const meta = cap(overlay.label);
  const tl = lines(title, 28).slice(0, 2);
  const tsz = tl.length > 1 ? 68 : 80;
  const rule = ramp(frame, 20, 22, inOut) * (1 - ramp(frame, durationInFrames - 15, 11, expoIn));
  const hasCap = tl.length > 0 || kick.length > 0 || meta.length > 0;
  return (
    <AbsoluteFill style={{ background: "#000", overflow: "hidden" }}>
      <SafeImg src={src} style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "100%", objectFit: "cover",
        transform: `scale(${sc}) translate(${px}%, ${py}%)`, filter: "saturate(.9) contrast(1.07)" }} />
      <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(18,42,64,.55) 0%, rgba(0,0,0,0) 45%, rgba(70,40,12,.45) 100%)",
        mixBlendMode: "soft-light" }} />
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${380 * k}px rgba(0,0,0,.78)`,
        background: "radial-gradient(ellipse at 50% 45%, rgba(0,0,0,0) 45%, rgba(0,0,0,.45) 100%)" }} />
      {hasCap ? (
        <AbsoluteFill style={{ background: "linear-gradient(0deg, rgba(0,0,0,.62) 0%, rgba(0,0,0,.2) 30%, rgba(0,0,0,0) 50%)" }} />
      ) : null}
      <svg width={width / 2} height={height / 2} style={{ position: "absolute", left: 0, top: 0, transform: "scale(2)", transformOrigin: "0 0",
        opacity: 0.16, mixBlendMode: "overlay" }}>
        <filter id="paGrainKB" x="0" y="0" width="100%" height="100%">
          <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves={2} seed={frame % 12} stitchTiles="stitch" />
          <feColorMatrix type="saturate" values="0" />
        </filter>
        <rect width={width / 2} height={height / 2} filter="url(#paGrainKB)" />
      </svg>
      <AbsoluteFill style={{ background: "#000", opacity: 1 - up }} />
      {hasCap ? (
        <div style={{ position: "absolute", left: 120 * k, bottom: 150 * k, display: "flex", flexDirection: "column", gap: 8 * k, maxWidth: 1300 * k }}>
          {kick ? (
            <div style={{ display: "flex", alignItems: "center", gap: 14 * k }}>
              <div style={{ width: 10 * k, height: 10 * k, background: accent, transform: `rotate(45deg) scale(${ramp(frame, 8, 12, backOut) * (1 - q)})` }} />
              <Letters text={kick} at={10} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 28 * k, letterSpacing: "0.3em",
                color: "rgba(255,255,255,.88)" }} />
            </div>
          ) : null}
          {tl.map((ln, i) => (
            <Letters key={i} text={ln} at={13 + i * 5} style={{ fontFamily: DISPLAY, fontSize: tsz * k, lineHeight: 0.98, color: "#fff",
              letterSpacing: "0.02em", textShadow: "0 6px 30px rgba(0,0,0,.6)" }} />
          ))}
          <div style={{ display: "flex", alignItems: "center", gap: 16 * k, marginTop: 10 * k }}>
            <div style={{ width: rule * 560 * k, height: 2 * k, background: "rgba(255,255,255,.8)" }} />
            <div style={{ width: 9 * k, height: 9 * k, background: accent, transform: `rotate(45deg) scale(${rule})` }} />
            {meta ? (
              <Rise at={30}>
                <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 26 * k, letterSpacing: "0.24em", color: "rgba(255,255,255,.82)",
                  whiteSpace: "nowrap" }}>{meta}</span>
              </Rise>
            ) : null}
          </div>
        </div>
      ) : null}
      <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: bh, background: "#000" }} />
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: bh, background: "#000" }} />
    </AbsoluteFill>
  );
};

// ================================================================== registry
export const LOOKS: Record<string, Look> = {
  "pa-polaroid-drop": PolaroidDrop,
  "pa-tilt-card": TiltCard,
  "pa-blinds-reveal": BlindsReveal,
  "pa-spotlight-focus": SpotlightFocus,
  "pa-film-strip": FilmStrip,
  "pa-mosaic-assemble": MosaicAssemble,
  "pa-torn-reveal": TornReveal,
  "pa-loupe-zoom": LoupeZoom,
  "pa-scan-id": ScanID,
  "pa-ken-burns": KenBurns,
};
