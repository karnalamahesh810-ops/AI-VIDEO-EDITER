import React from "react";
import { AbsoluteFill, Easing, Img, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY, HAND, INTER, LABEL, MARKER, MONO, NARROW } from "../fonts";
import type { Overlay, SceneMedia } from "../../types";
import { LetterLine, MaskLine, ramp, useK } from "./ProGraphics";

/**
 * The "case file" graphics, read off a Dr Insanity documentary (2026-09-28
 * storyboard pass over all 58 minutes): evidence laid out on a designed
 * desktop instead of plain cuts.
 *
 *   CaseBackdrop   the desktop: flowing dotted ridges (light ice-blue, deep
 *                  navy or case-file red), drifting slowly
 *   ProWindows     floating app windows on it - variant photo (a photo
 *                  viewer with its caption), pip (one photo window riding on
 *                  the footage), audio (a recording playing: waveform, the
 *                  words below, the speaker's photo), doc (a report page with
 *                  its key line marked), collage (a burst of photo windows)
 *   ProBoard       a paper board: photos pasted on, a red marker circle, an
 *                  arrow to a handwritten note, a big marker word; with two
 *                  or three photos, hand-drawn links between them
 *   ProClipping    a newspaper page with the headline, a black-and-white
 *                  photo and the key sentence highlighted
 *   ProFile        a dossier (fields typed in beside a scanned photo, a
 *                  stamp) or a facts card (a portrait fading into the dark,
 *                  the points listed beside it)
 *   ProSourceTag   the small "ARCHIVE FOOTAGE" label bottom left
 *   ProCallout     a quoted line in a compact box near the top
 *   PlayerWindow   the footage itself playing in a player window
 *                  (SceneClip, scene.frame "window")
 *
 * None of it copies the channel's assets: the looks are rebuilt from shapes,
 * type and the story's own pictures.
 */

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const CYAN = "#53c8ff";
const MARKER_RED = "#d8262e";
const cap = (s?: string) => (s || "").toUpperCase();
const stillOf = (m?: SceneMedia) => (m ? (m.type === "image" ? m.url : m.thumbnail || "") : "");

// ================================================================== backdrop
export type CaseTone = "light" | "dark" | "red";

const TONES: Record<CaseTone, { bg: string; line: string; op: number; spot: string; vignette: string }> = {
  light: { bg: "radial-gradient(ellipse at 38% 32%, #fbfdff 0%, #e2eaf2 52%, #b7c6d6 100%)", line: "#2f4a66", op: 0.5,
    spot: "rgba(255,255,255,.75)", vignette: "rgba(40,60,85,.35)" },
  dark: { bg: "radial-gradient(ellipse at 45% 38%, #12325c 0%, #0a1d38 52%, #040b18 100%)", line: "#86ccff", op: 0.55,
    spot: "rgba(90,170,255,.22)", vignette: "rgba(0,0,0,.6)" },
  red: { bg: "radial-gradient(ellipse at 50% 40%, #b0141c 0%, #700a10 55%, #360205 100%)", line: "#ff9a9a", op: 0.26,
    spot: "rgba(255,120,120,.18)", vignette: "rgba(0,0,0,.55)" },
};

/** The case desktop: dotted ridges flowing diagonally, a soft light, a vignette. */
export const CaseBackdrop: React.FC<{ tone?: CaseTone; seed?: number }> = ({ tone = "light", seed = 0 }) => {
  const frame = useCurrentFrame();
  const { width, height, fps } = useVideoConfig();
  const k = width / 1920;
  const T = TONES[tone];
  const t = frame / fps;
  const N = 24;
  const lines: { d: string; o: number; far: boolean }[] = [];
  for (let i = 0; i < N; i++) {
    const baseY = (i / (N - 1)) * height * 1.5 - height * 0.25;
    const wl = (760 + ((i * 137 + seed * 31) % 420)) * k;
    const a1 = (34 + ((i * 53) % 5) * 8) * k;
    const a2 = (12 + ((i * 29) % 4) * 5) * k;
    const ph = i * 0.42 + seed;
    let d = "";
    for (let x = -40 * k; x <= width + 40 * k; x += 22 * k) {
      const y = baseY - x * 0.28 + a1 * Math.sin((x / wl) * Math.PI * 2 + ph + t * 0.22)
        + a2 * Math.sin((x / (wl * 0.41)) * Math.PI * 2 + i * 1.3 - t * 0.16);
      d += `${d ? " L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
    }
    const depth = ((i * 7 + seed) % 10) / 10;
    lines.push({ d, o: T.op * (0.3 + 0.7 * depth), far: depth < 0.35 });
  }
  const dash = `${0.1} ${9 * k}`;
  return (
    <AbsoluteFill style={{ background: T.bg, overflow: "hidden" }}>
      <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
        <g style={{ filter: `blur(${1.6 * k}px)` }}>
          {lines.filter((l) => l.far).map((l, i) => (
            <path key={i} d={l.d} fill="none" stroke={T.line} strokeOpacity={l.o} strokeWidth={4.2 * k}
              strokeLinecap="round" strokeDasharray={dash} />
          ))}
        </g>
        {lines.filter((l) => !l.far).map((l, i) => (
          <path key={i} d={l.d} fill="none" stroke={T.line} strokeOpacity={l.o} strokeWidth={3.4 * k}
            strokeLinecap="round" strokeDasharray={dash} />
        ))}
      </svg>
      <AbsoluteFill style={{ background: `radial-gradient(ellipse at 35% 30%, ${T.spot} 0%, transparent 55%)` }} />
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${320 * k}px ${T.vignette}` }} />
    </AbsoluteFill>
  );
};

// ================================================================== window chrome
const Win: React.FC<{
  title: string; x: number; y: number; w: number; h: number; at: number; dark?: boolean; rot?: number;
  children?: React.ReactNode; footer?: React.ReactNode;
}> = ({ title, x, y, w, h, at, dark, rot = 0, children, footer }) => {
  const frame = useCurrentFrame();
  const { durationInFrames, fps } = useVideoConfig();
  const k = useK();
  const p = ramp(frame, at, 16, backOut);
  const o = ramp(frame, at, 8);
  const q = ramp(frame, durationInFrames - 12, 10);
  const drift = Math.sin((frame + at * 7) / (fps * 1.9)) * 5 * k;
  const bar = 34 * k;
  const ink = dark ? "#cfe6ff" : "#23364b";
  return (
    <div style={{ position: "absolute", left: x, top: y + drift + (1 - o) * 24 * k, width: w, height: h, borderRadius: 10 * k,
      overflow: "hidden", transform: `scale(${(0.88 + 0.12 * p) * (1 - 0.06 * q)}) rotate(${rot}deg)`,
      opacity: o * (1 - q), background: dark ? "rgba(14,26,44,.62)" : "rgba(255,255,255,.34)",
      backdropFilter: "blur(14px)", WebkitBackdropFilter: "blur(14px)",
      border: `${1.5 * k}px solid ${dark ? "rgba(140,200,255,.55)" : "rgba(255,255,255,.9)"}`,
      boxShadow: `0 ${30 * k}px ${70 * k}px rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.5)` }}>
      <div style={{ height: bar, display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: `0 ${14 * k}px`, background: dark ? "rgba(120,180,255,.12)" : "rgba(255,255,255,.55)",
        borderBottom: `${1 * k}px solid ${dark ? "rgba(140,200,255,.3)" : "rgba(35,54,75,.15)"}` }}>
        <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 14 * k, letterSpacing: "0.22em", color: ink }}>{cap(title)}</span>
        <span style={{ display: "flex", alignItems: "center", gap: 12 * k, opacity: 0.8 }}>
          <span style={{ width: 12 * k, height: 2 * k, background: ink }} />
          <span style={{ width: 11 * k, height: 11 * k, border: `${2 * k}px solid ${ink}` }} />
          <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 15 * k, color: ink, lineHeight: 1 }}>×</span>
        </span>
      </div>
      <div style={{ position: "absolute", left: 8 * k, right: 8 * k, top: bar + 8 * k, bottom: (footer ? 44 : 8) * k,
        overflow: "hidden", borderRadius: 4 * k }}>{children}</div>
      {footer ? (
        <div style={{ position: "absolute", left: 8 * k, right: 8 * k, bottom: 6 * k, height: 34 * k, display: "flex",
          alignItems: "center" }}>{footer}</div>
      ) : null}
    </div>
  );
};

const Photo: React.FC<{ src: string; push?: number; gray?: boolean }> = ({ src, push = 0.06, gray }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const pr = interpolate(frame, [0, Math.max(1, durationInFrames)], [0, 1], clamp);
  return <Img src={src} style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${1.03 + push * pr})`,
    filter: gray ? "grayscale(1) contrast(1.15)" : "saturate(.92) contrast(1.04)" }} />;
};

const Caption: React.FC<{ text: string; dark?: boolean; at: number }> = ({ text, dark, at }) => {
  const k = useK();
  return (
    <LetterLine text={cap(text)} at={at} step={0.6} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 26 * k,
      letterSpacing: "0.16em", color: dark ? "#e6f3ff" : "#1f3044", paddingLeft: 6 * k }} />
  );
};

/** Bars of a recording playing: the played part bright, bars bouncing near the playhead. */
const Waveform: React.FC<{ w: number; h: number; dark?: boolean }> = ({ w, h, dark }) => {
  const frame = useCurrentFrame();
  const { durationInFrames, fps } = useVideoConfig();
  const k = useK();
  const N = 56;
  const head = interpolate(frame, [fps * 0.4, durationInFrames - 8], [0, 1], clamp);
  const t = frame / fps;
  const bw = w / N;
  return (
    <svg width={w} height={h}>
      {Array.from({ length: N }, (_, i) => {
        const x = i / (N - 1);
        const env = 0.35 + 0.65 * Math.abs(Math.sin(i * 0.37 + 1.1) * Math.cos(i * 0.11));
        const near = Math.max(0, 1 - Math.abs(x - head) * 6);
        const live = 0.55 + 0.45 * Math.abs(Math.sin(t * 9 + i * 1.7) * Math.sin(t * 5.3 + i * 0.6));
        const bh = Math.max(4 * k, h * 0.9 * env * (0.55 + 0.45 * (near > 0 ? live : 0.8)));
        const played = x <= head;
        return <rect key={i} x={i * bw + bw * 0.18} y={(h - bh) / 2} width={bw * 0.64} height={bh} rx={bw * 0.2}
          fill={played ? (dark ? "#e8f4ff" : "#ffffff") : (dark ? "rgba(200,225,255,.35)" : "rgba(255,255,255,.5)")} />;
      })}
      <rect x={head * w - 1.5 * k} y={0} width={3 * k} height={h} fill={CYAN} />
    </svg>
  );
};

// ================================================================== windows
/**
 * App windows on the case desktop. overlay.media holds the pictures (the
 * scene's own, or ones the worker searched for the subject); overlay.text
 * the caption, overlay.label the speaker (audio), overlay.highlight the key
 * line (doc).
 */
export const ProWindows: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, height, fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const v = overlay.variant || "photo";
  const pics = (overlay.media || []).map(stillOf).filter(Boolean);
  const tone: CaseTone = v === "collage" ? "red" : (overlay.theme === "blue" || v === "audio") ? "dark" : "light";
  const dark = tone !== "light";

  if (v === "pip") {
    // One photo window riding on the footage, its caption below.
    if (!pics.length) return null;
    const w = 520 * k, h = 470 * k;
    const left = (overlay.position || "").includes("left");
    return (
      <AbsoluteFill>
        <Win title={overlay.subtitle || "Photo viewer"} x={left ? 90 * k : width - w - 90 * k} y={140 * k} w={w} h={h} at={0}
          rot={left ? -1.5 : 1.5} footer={overlay.text ? <Caption text={overlay.text} at={8} /> : null}>
          <Photo src={pics[0]} />
        </Win>
      </AbsoluteFill>
    );
  }

  if (v === "audio") {
    const words = (overlay.text || "").split(/\s+/).filter(Boolean);
    const perWord = Math.max(2, Math.min(6, Math.floor((durationInFrames - fps) / Math.max(1, words.length))));
    const shown = Math.floor(interpolate(frame, [fps * 0.5, fps * 0.5 + words.length * perWord], [0, words.length], clamp));
    const secs = Math.max(1, Math.round(durationInFrames / fps + 40));
    const now = Math.round(interpolate(frame, [0, durationInFrames], [7, secs - 30], clamp));
    const mm = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
    const hasPic = pics.length > 0;
    const W = hasPic ? 1050 * k : 1250 * k;
    const X = hasPic ? 190 * k : (width - W) / 2;
    return (
      <AbsoluteFill>
        <CaseBackdrop tone={tone} seed={2} />
        <Win title={overlay.subtitle || "Audio recording"} x={X} y={250 * k} w={W} h={290 * k} at={0} dark={dark}
          footer={<span style={{ fontFamily: MONO, fontSize: 16 * k, color: dark ? "#cfe6ff" : "#23364b", paddingLeft: 8 * k }}>
            ▶ {mm(now)} / {mm(secs)}</span>}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%" }}>
            <Waveform w={W - 60 * k} h={170 * k} dark={dark} />
          </div>
        </Win>
        {hasPic ? (
          <Win title="Photo" x={1300 * k} y={190 * k} w={430 * k} h={500 * k} at={8} dark={dark} rot={1.2}
            footer={overlay.label ? <Caption text={overlay.label} dark={dark} at={16} /> : null}>
            <Photo src={pics[0]} />
          </Win>
        ) : null}
        <div style={{ position: "absolute", left: 0, right: 0, top: 790 * k, display: "flex", flexDirection: "column",
          alignItems: "center", gap: 12 * k }}>
          {overlay.label && !hasPic ? (
            <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 18 * k, letterSpacing: "0.2em", color: CYAN,
              opacity: ramp(frame, 6, 10) }}>{cap(overlay.label)}</span>
          ) : null}
          <div style={{ maxWidth: 1300 * k, textAlign: "center", padding: `${10 * k}px ${22 * k}px`, background: "rgba(8,10,14,.86)",
            opacity: ramp(frame, fps * 0.45, 8), fontFamily: INTER, fontWeight: 700, fontSize: 40 * k, lineHeight: 1.3,
            color: "#fff" }}>
            {words.map((w, i) => (
              <span key={i} style={{ opacity: i < shown ? 1 : 0, color: i < shown && i >= shown - 3 ? "#fff" : "#e8e8e8" }}>{w} </span>
            ))}
          </div>
        </div>
      </AbsoluteFill>
    );
  }

  if (v === "doc") {
    const hl = (overlay.highlight || overlay.body || "").trim();
    const sweep = ramp(frame, fps * 1.0, fps * 0.8, inOut);
    const scroll = interpolate(frame, [0, durationInFrames], [0, -50 * k], clamp);
    const grey = (w: number, i: number) => (
      <div key={i} style={{ height: 13 * k, width: `${w}%`, background: "rgba(40,48,60,.16)", borderRadius: 3 * k,
        margin: `${12 * k}px 0` }} />
    );
    return (
      <AbsoluteFill>
        <CaseBackdrop tone="light" seed={4} />
        <Win title={overlay.subtitle || "Document"} x={470 * k} y={90 * k} w={980 * k} h={900 * k} at={0}>
          <div style={{ background: "#fbfbf8", width: "100%", height: "100%", padding: `${46 * k}px ${60 * k}px`,
            transform: `translateY(${scroll}px)`, boxSizing: "border-box" }}>
            <div style={{ fontFamily: MONO, fontWeight: 700, fontSize: 16 * k, letterSpacing: "0.24em", color: "#6b7480" }}>
              {cap(overlay.label || "Official record")}</div>
            <div style={{ height: 3 * k, background: "#1d2530", margin: `${14 * k}px 0 ${22 * k}px` }} />
            <MaskLine at={6}><div style={{ fontFamily: NARROW, fontWeight: 700, fontSize: 50 * k, lineHeight: 1.08, color: "#11161d",
              textTransform: "uppercase" }}>{overlay.text}</div></MaskLine>
            {[92, 97, 88, 94].map(grey)}
            {hl ? (
              <div style={{ position: "relative", margin: `${18 * k}px 0`, fontFamily: INTER, fontWeight: 600, fontSize: 30 * k,
                lineHeight: 1.45, color: "#1b222b" }}>
                <span style={{ backgroundImage: "linear-gradient(transparent 12%, rgba(255,214,10,.8) 12%, rgba(255,214,10,.8) 90%, transparent 90%)",
                  backgroundRepeat: "no-repeat", backgroundSize: `${sweep * 100}% 100%`, boxDecorationBreak: "clone",
                  WebkitBoxDecorationBreak: "clone" }}>{hl}</span>
              </div>
            ) : null}
            {[95, 90, 97, 72, 93, 88, 96, 60].map(grey)}
          </div>
        </Win>
      </AbsoluteFill>
    );
  }

  if (v === "collage") {
    // The story's own pictures bursting onto the case desktop, one window after another.
    const slots = [
      [120, 120, 520, 360, -2], [700, 80, 460, 330, 1.5], [1250, 150, 540, 380, -1],
      [180, 560, 480, 340, 1.2], [760, 480, 560, 400, -1.5], [1380, 600, 420, 320, 2],
    ];
    const n = Math.min(slots.length, pics.length);
    if (!n) return null;
    return (
      <AbsoluteFill>
        <CaseBackdrop tone="red" seed={1} />
        {slots.slice(0, n).map(([x, y, w, h, r], i) => (
          <Win key={i} title={i % 2 ? "Photo viewer" : "Evidence"} x={x * k} y={y * k} w={w * k} h={h * k}
            at={Math.round(i * fps * 0.18)} rot={r}>
            <Photo src={pics[i % pics.length]} push={0.1} />
          </Win>
        ))}
        {overlay.text ? (
          <div style={{ position: "absolute", left: 90 * k, bottom: 70 * k, maxWidth: 1100 * k }}>
            <LetterLine text={cap(overlay.text)} at={Math.round(n * fps * 0.18)} style={{ fontFamily: DISPLAY, fontSize: 84 * k,
              color: "#fff", letterSpacing: "0.03em", textShadow: "0 8px 30px rgba(0,0,0,.6)" }} />
          </div>
        ) : null}
      </AbsoluteFill>
    );
  }

  // photo: a viewer window with the picture, an info window with its caption.
  const main = pics[0];
  const hasTwo = pics.length > 1;
  return (
    <AbsoluteFill>
      <CaseBackdrop tone={tone} seed={3} />
      {main ? (
        <Win title={overlay.subtitle || "Photo viewer"} x={(hasTwo ? 180 : 330) * k} y={130 * k} w={(hasTwo ? 900 : 1000) * k}
          h={660 * k} at={0} dark={dark} rot={-0.8}>
          <Photo src={main} />
        </Win>
      ) : null}
      {hasTwo ? (
        <Win title="Photo viewer" x={1150 * k} y={300 * k} w={600 * k} h={470 * k} at={8} dark={dark} rot={1.4}>
          <Photo src={pics[1]} />
        </Win>
      ) : null}
      {overlay.text ? (
        <Win title="Info" x={(main ? (hasTwo ? 240 : 420) : 560) * k} y={(main ? 830 : 420) * k} w={(main ? 760 : 800) * k}
          h={130 * k} at={12} dark={dark}>
          <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", height: "100%", paddingLeft: 12 * k }}>
            <LetterLine text={cap(overlay.text)} at={18} step={0.6} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 44 * k,
              letterSpacing: "0.06em", color: dark ? "#fff" : "#16212e" }} />
          </div>
        </Win>
      ) : null}
      {accent ? null : null}
    </AbsoluteFill>
  );
};

// ================================================================== board
/** A hand-drawn wobbly loop around a box (1.15 turns, so the ends overlap like a real marker circle). */
const loopPath = (cx: number, cy: number, rx: number, ry: number, seed: number) => {
  let d = "";
  const steps = 64;
  for (let i = 0; i <= steps; i++) {
    const a = -Math.PI * 0.6 + (i / steps) * Math.PI * 2 * 1.15;
    const wob = 1 + 0.035 * Math.sin(a * 3 + seed) + 0.02 * Math.sin(a * 7 + seed * 2) + (i / steps) * 0.05;
    d += `${i ? " L" : "M"}${(cx + Math.cos(a) * rx * wob).toFixed(1)} ${(cy + Math.sin(a) * ry * wob).toFixed(1)}`;
  }
  return d;
};

const arrowPath = (x1: number, y1: number, x2: number, y2: number, bend: number) => {
  const mx = (x1 + x2) / 2 - (y2 - y1) * bend, my = (y1 + y2) / 2 + (x2 - x1) * bend;
  const ang = Math.atan2(y2 - my, x2 - mx);
  const hl = 26;
  const h1 = [x2 - hl * Math.cos(ang - 0.45), y2 - hl * Math.sin(ang - 0.45)];
  const h2 = [x2 - hl * Math.cos(ang + 0.45), y2 - hl * Math.sin(ang + 0.45)];
  return { line: `M${x1} ${y1} Q${mx} ${my} ${x2} ${y2}`, head: `M${h1[0]} ${h1[1]} L${x2} ${y2} L${h2[0]} ${h2[1]}` };
};

const Paper: React.FC = () => {
  const { width, height } = useVideoConfig();
  const k = width / 1920;
  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 45% 40%, #fbfaf6 0%, #efece4 60%, #d9d4c8 100%)" }}>
      <svg width={width} height={height} style={{ position: "absolute", inset: 0, opacity: 0.35, mixBlendMode: "multiply" }}>
        <filter id="paperNoise"><feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="3" seed="4" />
          <feColorMatrix type="saturate" values="0" /></filter>
        <rect width={width} height={height} filter="url(#paperNoise)" opacity={0.35} />
      </svg>
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${260 * k}px rgba(90,80,60,.35)` }} />
    </AbsoluteFill>
  );
};

const Print: React.FC<{ src: string; x: number; y: number; w: number; h: number; rot: number; at: number }> =
  ({ src, x, y, w, h, rot, at }) => {
    const frame = useCurrentFrame();
    const k = useK();
    const p = ramp(frame, at, 14);
    return (
      <div style={{ position: "absolute", left: x, top: y, width: w, height: h, padding: 12 * k, background: "#fff",
        boxShadow: `0 ${14 * k}px ${34 * k}px rgba(0,0,0,.28)`, transform: `rotate(${rot}deg) scale(${1.12 - 0.12 * p})`,
        opacity: p, boxSizing: "border-box" }}>
        <Img src={src} style={{ width: "100%", height: "100%", objectFit: "cover", filter: "grayscale(.25) contrast(1.05)" }} />
        <div style={{ position: "absolute", left: "38%", top: -14 * k, width: "24%", height: 30 * k,
          background: "rgba(235,225,190,.75)", transform: "rotate(-3deg)" }} />
      </div>
    );
  };

/**
 * The detective board: photos pasted on paper, a red marker loop around the
 * first, an arrow to a handwritten note (overlay.text or the first item), a
 * big marker word above (overlay.subtitle). Two or three photos are linked
 * by hand-drawn lines, each labelled (items[i].label) under its print.
 */
export const ProBoard: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width, height, fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const pics = (overlay.media || []).map(stillOf).filter(Boolean).slice(0, 3);
  const items = (overlay.items || []).map((i) => (i.label || i.text || "").trim()).filter(Boolean);
  const note = (overlay.text || items[0] || "").trim();
  const big = (overlay.subtitle || "").trim();
  const push = interpolate(frame, [0, durationInFrames], [1, 1.05], clamp);
  const draw = (at: number, frames: number) => ramp(frame, at, frames, inOut);
  const ink = "#1d1d1f";

  if (pics.length >= 2) {
    const slots = pics.length === 2
      ? [[330, 250, 500, 600, -3], [1090, 230, 500, 600, 2.5]]
      : [[210, 170, 420, 500, -3], [1290, 170, 420, 500, 2.5], [750, 520, 420, 480, -1.5]];
    const centres = slots.map(([x, y, w, h]) => [(x + w / 2) * k, (y + h / 2) * k]);
    const links = pics.length === 2 ? [[0, 1]] : [[0, 1], [0, 2], [1, 2]];
    return (
      <AbsoluteFill style={{ overflow: "hidden" }}>
        <AbsoluteFill style={{ transform: `scale(${push})` }}>
          <Paper />
          <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
            {links.map(([a, b], i) => {
              const [x1, y1] = centres[a], [x2, y2] = centres[b];
              const p = draw(Math.round(fps * 0.8) + i * 10, 18);
              return <path key={i} d={`M${x1} ${y1} Q${(x1 + x2) / 2} ${(y1 + y2) / 2 - 60 * k} ${x2} ${y2}`} fill="none" stroke={ink}
                strokeWidth={5 * k} strokeLinecap="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - p} />;
            })}
          </svg>
          {pics.map((src, i) => {
            const [x, y, w, h, r] = slots[i];
            return <Print key={i} src={src} x={x * k} y={y * k} w={w * k} h={h * k} rot={r} at={i * 6} />;
          })}
          {pics.map((_, i) => {
            const [x, y, w, h] = slots[i];
            const label = items[i] || "";
            if (!label) return null;
            const p = ramp(frame, Math.round(fps * 1.2) + i * 8, 16);
            return (
              <div key={`l${i}`} style={{ position: "absolute", left: (x - 40) * k, top: (y + h + 18) * k, width: (w + 80) * k,
                textAlign: "center", fontFamily: HAND, fontWeight: 700, fontSize: 58 * k, color: ink,
                clipPath: `inset(0 ${(1 - p) * 100}% 0 0)`, transform: `rotate(${i % 2 ? 2 : -2}deg)` }}>{label}</div>
            );
          })}
          {note ? (
            <div style={{ position: "absolute", left: 0, right: 0, top: 60 * k, textAlign: "center", fontFamily: MARKER,
              fontSize: 72 * k, color: MARKER_RED, clipPath: `inset(0 ${(1 - ramp(frame, Math.round(fps * 1.8), 18)) * 100}% 0 0)` }}>
              {note}</div>
          ) : null}
        </AbsoluteFill>
      </AbsoluteFill>
    );
  }

  // One photo: loop it, arrow to the note, the marker word above.
  const W = 540 * k, H = 640 * k;
  const X = 470 * k, Y = 250 * k;
  const cx = X + W / 2, cy = Y + H / 2;
  const loop = loopPath(cx, cy, W * 0.66, H * 0.6, 1.3);
  const arrow = arrowPath(cx + W * 0.66, cy - 40 * k, 1240 * k, 470 * k, 0.18);
  const loopP = draw(Math.round(fps * 0.5), Math.round(fps * 0.8));
  const arrowP = draw(Math.round(fps * 1.25), Math.round(fps * 0.45));
  const noteP = ramp(frame, Math.round(fps * 1.6), Math.max(12, note.length * 1.4));
  const bigP = ramp(frame, Math.round(fps * 0.2), 14);
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${push})` }}>
        <Paper />
        {pics[0] ? <Print src={pics[0]} x={X} y={Y} w={W} h={H} rot={-2.5} at={0} /> : null}
        <svg width={width} height={height} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          <path d={loop} fill="none" stroke={MARKER_RED} strokeWidth={9 * k} strokeLinecap="round" strokeLinejoin="round"
            pathLength={1} strokeDasharray={1} strokeDashoffset={1 - loopP} opacity={0.92} />
          {note ? (
            <g>
              <path d={arrow.line} fill="none" stroke={MARKER_RED} strokeWidth={8 * k} strokeLinecap="round" pathLength={1}
                strokeDasharray={1} strokeDashoffset={1 - arrowP} />
              <path d={arrow.head} fill="none" stroke={MARKER_RED} strokeWidth={8 * k} strokeLinecap="round" strokeLinejoin="round"
                opacity={arrowP > 0.95 ? 1 : 0} />
            </g>
          ) : null}
          {big ? (
            <g opacity={bigP}>
              {(() => {
                const a1 = arrowPath(cx - 260 * k, 150 * k, cx - 120 * k, Y + 20 * k, -0.15);
                const a2 = arrowPath(cx + 260 * k, 150 * k, cx + 120 * k, Y + 20 * k, 0.15);
                const q = draw(Math.round(fps * 0.4), 14);
                return [a1, a2].map((a, i) => (
                  <g key={i}>
                    <path d={a.line} fill="none" stroke={ink} strokeWidth={6 * k} strokeLinecap="round" pathLength={1}
                      strokeDasharray={1} strokeDashoffset={1 - q} />
                    <path d={a.head} fill="none" stroke={ink} strokeWidth={6 * k} strokeLinecap="round" opacity={q > 0.95 ? 1 : 0} />
                  </g>
                ));
              })()}
            </g>
          ) : null}
        </svg>
        {big ? (
          <div style={{ position: "absolute", left: cx - 400 * k, width: 800 * k, top: 40 * k, textAlign: "center",
            fontFamily: MARKER, fontSize: 104 * k, color: MARKER_RED, lineHeight: 1,
            clipPath: `inset(0 ${(1 - bigP) * 100}% 0 0)` }}>{cap(big)}</div>
        ) : null}
        {note ? (
          <div style={{ position: "absolute", left: 1250 * k, top: 380 * k, width: 560 * k, fontFamily: HAND, fontWeight: 700,
            fontSize: 72 * k, lineHeight: 1.05, color: ink, transform: "rotate(-3deg)",
            clipPath: `inset(0 ${(1 - noteP) * 100}% 0 0)` }}>{note}</div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== clipping
/** A newspaper page: the headline, a black-and-white photo, the key sentence highlighted. */
export const ProClipping: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width, height, fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const pic = stillOf((overlay.media || [])[0]);
  const hl = (overlay.highlight || overlay.body || "").trim();
  const land = ramp(frame, 0, 20);
  const push = interpolate(frame, [0, durationInFrames], [1, 1.07], clamp);
  const sweep = ramp(frame, fps * 1.0, fps * 0.9, inOut);
  const grey = (w: number, i: number) => (
    <div key={i} style={{ height: 11 * k, width: `${w}%`, background: "rgba(20,20,20,.2)", margin: `${9 * k}px 0` }} />
  );
  const PW = 1480 * k, PH = 1080 * k;
  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 40%, #2a2a2e 0%, #121214 70%, #060607 100%)", overflow: "hidden" }}>
      <div style={{ position: "absolute", left: (width - PW) / 2, top: 70 * k, width: PW, height: PH,
        transform: `translateY(${(1 - land) * 120 * k}px) rotate(${-3.5 + 2 * land}deg) scale(${push})`, transformOrigin: "50% 12%",
        opacity: land, background: "#ecebe5", boxShadow: `0 ${40 * k}px ${90 * k}px rgba(0,0,0,.6)`,
        backgroundImage: "radial-gradient(rgba(0,0,0,.05) 1px, transparent 1.3px)", backgroundSize: `${6 * k}px ${6 * k}px`,
        padding: `${40 * k}px ${60 * k}px`, boxSizing: "border-box" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", fontFamily: NARROW, fontWeight: 500,
          fontSize: 22 * k, letterSpacing: "0.3em", color: "#2b2b2b" }}>
          <span>{cap(overlay.subtitle || "Special report")}</span><span>{cap(overlay.label || "")}</span>
        </div>
        <div style={{ height: 6 * k, background: "#151515", margin: `${12 * k}px 0 ${4 * k}px` }} />
        <div style={{ height: 2 * k, background: "#151515", marginBottom: 26 * k }} />
        <MaskLine at={10} frames={18}>
          <div style={{ fontFamily: NARROW, fontWeight: 700, fontSize: (overlay.text || "").length > 60 ? 70 * k : 92 * k,
            lineHeight: 1.02, color: "#0e0e0e", textTransform: "uppercase" }}>{overlay.text}</div>
        </MaskLine>
        <div style={{ display: "flex", gap: 44 * k, marginTop: 30 * k }}>
          {pic ? (
            <div style={{ width: 640 * k, flexShrink: 0 }}>
              <div style={{ width: 640 * k, height: 440 * k, overflow: "hidden", background: "#999" }}>
                <Img src={pic} style={{ width: "100%", height: "100%", objectFit: "cover", filter: "grayscale(1) contrast(1.25) brightness(.95)" }} />
              </div>
              {grey(70, 0)}
            </div>
          ) : null}
          <div style={{ flex: 1 }}>
            {hl ? (
              <div style={{ fontFamily: INTER, fontWeight: 600, fontSize: 30 * k, lineHeight: 1.5, color: "#161616", marginBottom: 10 * k }}>
                <span style={{ backgroundImage: "linear-gradient(transparent 10%, rgba(255,214,10,.85) 10%, rgba(255,214,10,.85) 92%, transparent 92%)",
                  backgroundRepeat: "no-repeat", backgroundSize: `${sweep * 100}% 100%`, boxDecorationBreak: "clone",
                  WebkitBoxDecorationBreak: "clone" }}>{hl}</span>
              </div>
            ) : null}
            {[98, 94, 97, 90, 96, 99, 85, 93, 97, 70].map(grey)}
          </div>
        </div>
      </div>
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${260 * k}px rgba(0,0,0,.65)` }} />
      {height ? null : null}
    </AbsoluteFill>
  );
};

// ================================================================== file cards
/**
 * variant "dossier": a file window on the red desk, fields (items: label ->
 * text) typed in beside a scanned photo, a stamp (overlay.subtitle).
 * variant "facts": a portrait fading into the dark on the right, the points
 * (items) listed on the left under overlay.text.
 */
export const ProFile: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width, height, fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const pic = stillOf((overlay.media || [])[0]);
  const items = (overlay.items || []).filter((i) => (i.label || i.text || "").trim());

  if (overlay.variant === "facts") {
    const push = interpolate(frame, [0, durationInFrames], [1.04, 1.1], clamp);
    return (
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 70% 45%, #123a40 0%, #081a1d 55%, #020607 100%)", overflow: "hidden" }}>
        {pic ? (
          <div style={{ position: "absolute", right: 0, top: 0, width: width * 0.56, height,
            maskImage: "linear-gradient(to left, #000 55%, transparent 100%)", WebkitMaskImage: "linear-gradient(to left, #000 55%, transparent 100%)",
            opacity: ramp(frame, 0, 18) }}>
            <Img src={pic} style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${push})`,
              filter: "saturate(.8) contrast(1.05) brightness(.9)" }} />
            <AbsoluteFill style={{ background: "linear-gradient(0deg, rgba(2,6,7,.75) 0%, transparent 40%)" }} />
          </div>
        ) : null}
        <AbsoluteFill style={{ boxShadow: `inset 0 0 ${300 * k}px rgba(0,0,0,.7)` }} />
        <div style={{ position: "absolute", left: 130 * k, top: 0, bottom: 0, width: 820 * k, display: "flex", flexDirection: "column",
          justifyContent: "center", gap: 14 * k }}>
          <LetterLine text={(overlay.text || "What we know").replace(/:?$/, ":")} at={4} style={{ fontFamily: LABEL, fontWeight: 800,
            fontSize: 58 * k, color: "#fff", letterSpacing: "0.02em" }} />
          {items.map((it, i) => (
            <MaskLine key={i} at={14 + i * 9}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 16 * k, fontFamily: LABEL, fontWeight: 600, fontSize: 38 * k,
                color: "rgba(235,245,245,.9)", lineHeight: 1.2 }}>
                <span style={{ color: accent, fontWeight: 800 }}>–</span>
                <span>{it.label || it.text}{it.label && it.text ? <span style={{ opacity: 0.7 }}> · {it.text}</span> : null}</span>
              </div>
            </MaskLine>
          ))}
          {overlay.subtitle ? (
            <div style={{ marginTop: 24 * k }}>
              <LetterLine text={overlay.subtitle} at={20 + items.length * 9} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 44 * k,
                color: accent }} />
            </div>
          ) : null}
        </div>
      </AbsoluteFill>
    );
  }

  // dossier
  const scan = ramp(frame, 10, Math.round(fps * 1.1), inOut);
  const stampP = ramp(frame, Math.round(fps * 1.5), 10);
  const typed = (s: string, at: number) => s.slice(0, Math.max(0, Math.floor((frame - at) * 1.6)));
  return (
    <AbsoluteFill>
      <CaseBackdrop tone="red" seed={5} />
      <Win title={`File · ${overlay.label || "Record"}`} x={230 * k} y={170 * k} w={1460 * k} h={740 * k} at={0} dark>
        <div style={{ display: "flex", height: "100%", padding: `${30 * k}px ${40 * k}px`, gap: 50 * k, boxSizing: "border-box",
          background: "rgba(8,6,8,.55)" }}>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 20 * k, paddingTop: 10 * k }}>
            {(overlay.text ? [{ label: "Name", text: overlay.text }, ...items] : items).slice(0, 6).map((it, i) => {
              const at = 8 + i * 12;
              return (
                <div key={i} style={{ display: "flex", alignItems: "baseline", gap: 24 * k, opacity: ramp(frame, at, 6) }}>
                  <span style={{ width: 190 * k, fontFamily: MONO, fontWeight: 700, fontSize: 20 * k, letterSpacing: "0.2em",
                    color: "rgba(255,190,190,.7)" }}>{cap(it.label)}</span>
                  <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 44 * k, color: "#fff", letterSpacing: "0.03em" }}>
                    {cap(typed(it.text || "", at))}</span>
                </div>
              );
            })}
          </div>
          {pic ? (
            <div style={{ position: "relative", width: 440 * k, height: 560 * k, flexShrink: 0, overflow: "hidden",
              border: `${2 * k}px solid rgba(255,255,255,.4)` }}>
              <Img src={pic} style={{ width: "100%", height: "100%", objectFit: "cover", clipPath: `inset(0 0 ${(1 - scan) * 100}% 0)`,
                filter: "contrast(1.05) saturate(.85)" }} />
              <div style={{ position: "absolute", left: 0, right: 0, top: `${scan * 100}%`, height: 4 * k, background: "#fff",
                boxShadow: `0 0 ${20 * k}px #fff`, opacity: scan < 1 ? 1 : 0 }} />
            </div>
          ) : null}
        </div>
      </Win>
      {overlay.subtitle ? (
        <div style={{ position: "absolute", left: 1150 * k, top: 700 * k, border: `${6 * k}px solid ${MARKER_RED}`,
          color: MARKER_RED, fontFamily: NARROW, fontWeight: 700, fontSize: 62 * k, letterSpacing: "0.12em",
          padding: `${4 * k}px ${22 * k}px`, background: "rgba(255,255,255,.9)",
          transform: `rotate(-9deg) scale(${2 - stampP})`, opacity: stampP }}>{cap(overlay.subtitle)}</div>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== source tag
/** "ARCHIVE FOOTAGE · 1936": a small outlined label low left, on the footage. */
export const ProSourceTag: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const k = useK();
  const p = ramp(frame, 0, 14);
  const q = ramp(frame, durationInFrames - 10, 10);
  const text = cap(overlay.text || "Archive footage");
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: 64 * k, bottom: 64 * k, display: "flex", alignItems: "center", gap: 12 * k,
        padding: `${7 * k}px ${16 * k}px ${6 * k}px ${12 * k}px`, borderRadius: 6 * k, background: "rgba(8,8,10,.58)",
        border: `${1.5 * k}px solid rgba(255,255,255,.55)`, opacity: p * (1 - q),
        transform: `translateX(${(1 - p) * -30 * k}px)` }}>
        <svg width={22 * k} height={18 * k} viewBox="0 0 22 18">
          <rect x="1" y="1" width="20" height="16" rx="2" fill="none" stroke="#fff" strokeWidth="1.6" />
          {[3, 7, 11, 15].map((y) => <rect key={y} x="3" y={y - 1} width="2" height="2" fill="#fff" />)}
          {[3, 7, 11, 15].map((y) => <rect key={`r${y}`} x="17" y={y - 1} width="2" height="2" fill="#fff" />)}
        </svg>
        <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 26 * k, letterSpacing: "0.16em", color: "#fff" }}>{text}</span>
        {overlay.subtitle ? (
          <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 26 * k, letterSpacing: "0.16em", color: "rgba(255,255,255,.7)" }}>
            · {cap(overlay.subtitle)}</span>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== callout
/** A quoted line in a compact dark box near the top, word by word, the speaker under it. */
export const ProCallout: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { durationInFrames, fps } = useVideoConfig();
  const k = useK();
  const words = (overlay.text || "").replace(/^["“]|["”]$/g, "").split(/\s+/).filter(Boolean);
  if (!words.length) return null;
  const p = ramp(frame, 0, 10, backOut);
  const q = ramp(frame, durationInFrames - 10, 10);
  const per = Math.max(1.5, Math.min(4, (fps * 1.2) / words.length));
  const left = (overlay.position || "").includes("left");
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", [left ? "left" : "right"]: 90 * k, top: 110 * k, maxWidth: 760 * k,
        transform: `scale(${0.9 + 0.1 * p})`, transformOrigin: left ? "0 0" : "100% 0", opacity: Math.min(1, p) * (1 - q) }}>
        <div style={{ background: "rgba(6,10,16,.86)", borderLeft: `${5 * k}px solid ${CYAN}`, padding: `${14 * k}px ${24 * k}px`,
          fontFamily: LABEL, fontWeight: 700, fontSize: 42 * k, lineHeight: 1.15, color: "#c9ecff" } as React.CSSProperties}>
          <span style={{ color: CYAN }}>“</span>
          {words.map((w, i) => (
            <span key={i} style={{ opacity: ramp(frame, 4 + i * per, 5) }}>{w}{i < words.length - 1 ? " " : ""}</span>
          ))}
          <span style={{ color: CYAN }}>”</span>
        </div>
        {overlay.label ? (
          <div style={{ marginTop: 8 * k, textAlign: left ? "left" : "right", fontFamily: MONO, fontWeight: 700, fontSize: 16 * k,
            letterSpacing: "0.2em", color: "rgba(255,255,255,.8)", opacity: ramp(frame, 10, 10),
            textShadow: "0 2px 8px rgba(0,0,0,.8)" }}>— {cap(overlay.label)}</div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== evidence photo
/**
 * The photo as evidence: full frame in black and white, grain and a vignette,
 * viewfinder brackets closing in, a slow push, and a small outlined tag low
 * left ("PHOTO · 1936"); overlay.text, if any, typed small at the top.
 */
export const ProEvidence: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width, height, fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const pic = stillOf((overlay.media || [])[0]);
  if (!pic) return null;
  const push = interpolate(frame, [0, durationInFrames], [1.04, 1.12], clamp);
  const br = ramp(frame, 4, 18, inOut);
  const inset = (1 - br) * 60 * k + 60 * k;
  const L = 70 * k;
  const corner = (x: number, y: number, dx: number, dy: number, i: number) => (
    <path key={i} d={`M${x + dx * L} ${y} L${x} ${y} L${x} ${y + dy * L}`} fill="none" stroke="#fff" strokeWidth={4 * k}
      opacity={0.9 * br} />
  );
  const typed = (overlay.text || "").toUpperCase().slice(0, Math.max(0, Math.floor((frame - fps * 0.5) * 1.4)));
  return (
    <AbsoluteFill style={{ background: "#050505", overflow: "hidden" }}>
      <Img src={pic} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover",
        transform: `scale(${push})`, filter: "grayscale(1) contrast(1.22) brightness(.92)" }} />
      <svg width={width} height={height} style={{ position: "absolute", inset: 0, opacity: 0.18, mixBlendMode: "overlay" }}>
        <filter id="evGrain"><feTurbulence type="fractalNoise" baseFrequency="0.95" numOctaves="2" seed={frame % 9} /></filter>
        <rect width={width} height={height} filter="url(#evGrain)" />
      </svg>
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${300 * k}px rgba(0,0,0,.85)` }} />
      <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
        {corner(inset, inset, 1, 1, 0)}
        {corner(width - inset, inset, -1, 1, 1)}
        {corner(inset, height - inset, 1, -1, 2)}
        {corner(width - inset, height - inset, -1, -1, 3)}
      </svg>
      {typed ? (
        <div style={{ position: "absolute", left: 150 * k, top: 130 * k, fontFamily: MONO, fontWeight: 700, fontSize: 26 * k,
          letterSpacing: "0.18em", color: "#fff", textShadow: "0 2px 10px rgba(0,0,0,.9)" }}>{typed}</div>
      ) : null}
      <div style={{ position: "absolute", left: 150 * k, bottom: 130 * k, padding: `${6 * k}px ${14 * k}px`,
        border: `${1.5 * k}px solid rgba(255,255,255,.7)`, background: "rgba(0,0,0,.45)", fontFamily: LABEL, fontWeight: 700,
        fontSize: 24 * k, letterSpacing: "0.2em", color: "#fff", opacity: ramp(frame, 12, 12) }}>
        [ {(overlay.label || "Photo").toUpperCase()}{overlay.subtitle ? ` · ${overlay.subtitle.toUpperCase()}` : ""} ]
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== player window (scene frame)
/**
 * The footage itself playing inside a player window on the case desktop
 * (scene.frame "window"): a slight turn as it lands, a scrubber running
 * along the bottom. `children` is the clip, already graded.
 */
export const PlayerWindow: React.FC<{ title?: string; tone?: CaseTone; seed?: number; children: React.ReactNode }> =
  ({ title = "Video player", tone = "light", seed = 0, children }) => {
    const frame = useCurrentFrame();
    const { width, height, fps, durationInFrames } = useVideoConfig();
    const k = width / 1920;
    const land = ramp(frame, 0, 20);
    const pr = interpolate(frame, [0, durationInFrames], [0, 1], clamp);
    const W = 1380 * k, VH = W * 9 / 16, BAR = 36 * k, CTRL = 46 * k;
    const H = VH + BAR + CTRL;
    const dark = tone !== "light";
    const ink = dark ? "#cfe6ff" : "#23364b";
    const drift = Math.sin(frame / (fps * 2.4)) * 4 * k;
    const secs = Math.round(durationInFrames / fps) + 95;
    const now = Math.round(pr * (durationInFrames / fps)) + 41;
    const mm = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
    return (
      <AbsoluteFill style={{ overflow: "hidden" }}>
        <CaseBackdrop tone={tone} seed={seed} />
        <div style={{ position: "absolute", left: (width - W) / 2, top: (height - H) / 2 + drift, width: W, height: H,
          borderRadius: 12 * k, overflow: "hidden", opacity: land,
          transform: `perspective(${2400 * k}px) rotateY(${(1 - land) * -14}deg) scale(${0.9 + 0.1 * land + pr * 0.02})`,
          background: dark ? "rgba(14,26,44,.7)" : "rgba(255,255,255,.4)", backdropFilter: "blur(14px)",
          border: `${1.5 * k}px solid ${dark ? "rgba(140,200,255,.55)" : "rgba(255,255,255,.9)"}`,
          boxShadow: `0 ${40 * k}px ${90 * k}px rgba(0,0,0,.4)` }}>
          <div style={{ height: BAR, display: "flex", alignItems: "center", justifyContent: "space-between", padding: `0 ${16 * k}px`,
            background: dark ? "rgba(120,180,255,.12)" : "rgba(255,255,255,.6)" }}>
            <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 15 * k, letterSpacing: "0.22em", color: ink }}>{cap(title)}</span>
            <span style={{ display: "flex", alignItems: "center", gap: 12 * k, opacity: 0.8 }}>
              <span style={{ width: 12 * k, height: 2 * k, background: ink }} />
              <span style={{ width: 11 * k, height: 11 * k, border: `${2 * k}px solid ${ink}` }} />
              <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 16 * k, color: ink, lineHeight: 1 }}>×</span>
            </span>
          </div>
          <div style={{ position: "relative", width: W, height: VH, overflow: "hidden", background: "#000" }}>{children}</div>
          <div style={{ height: CTRL, display: "flex", alignItems: "center", gap: 16 * k, padding: `0 ${18 * k}px` }}>
            <span style={{ fontFamily: MONO, fontSize: 16 * k, color: ink }}>▶</span>
            <div style={{ position: "relative", flex: 1, height: 5 * k, borderRadius: 3 * k, background: dark ? "rgba(255,255,255,.2)" : "rgba(35,54,75,.2)" }}>
              <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${(0.18 + pr * 0.3) * 100}%`, borderRadius: 3 * k,
                background: CYAN }} />
            </div>
            <span style={{ fontFamily: MONO, fontSize: 15 * k, color: ink }}>{mm(now)} / {mm(secs)}</span>
          </div>
        </div>
      </AbsoluteFill>
    );
  };
