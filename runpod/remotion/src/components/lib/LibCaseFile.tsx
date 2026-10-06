import React from "react";
import { AbsoluteFill, Easing, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { SafeImg } from "../motion/safePicture";
import { DISPLAY, HAND, INTER, LABEL, MONO, NARROW } from "../fonts";
import type { Overlay, OverlayItem, SceneMedia } from "../../types";
import { LetterLine, Odometer, lines, ramp, useHold, useK } from "../pro/ProGraphics";
import { CaseBackdrop } from "../pro/ProCase";

/**
 * Case file / true crime / investigation (family "cf-"): ten designed
 * moments for the evidence of a story. Every card draws its own backdrop;
 * the surveillance frame is a tag that rides on the footage.
 *
 *   cf-evidence-bag        a clear evidence bag lands on a steel desk; its printed
 *                          label fills in by hand (item number rolling, case no.,
 *                          description, chain-of-custody rows) and a tamper seal
 *                          wipes across the top; the story's still sits inside
 *   cf-case-stamp          a manila case folder slides onto the case desk; the case
 *                          number is stamped digit by digit with a knock on each
 *                          hit, the title sticker's letters rise, an optional word
 *                          stamp (overlay.highlight) slams down in red ink
 *   cf-redacted-doc        an official page tilts in, redaction bars are drawn over
 *                          its body; the bars on the key line retract one after
 *                          another, a highlighter sweeps it and the camera pushes in
 *   cf-fingerprint-scan    a procedural print is scanned top to bottom, ridges
 *                          lighting up, minutiae locking on; the match rolls on an
 *                          odometer while a segmented meter fills, a leader links them
 *   cf-police-log          a dispatch console: timestamped entries type in one after
 *                          another down a lit rail, the active row highlighted
 *   cf-unknown-silhouette  a dark bust rises in front of a height chart, a camera
 *                          flash, a rim light draws round it and a question mark
 *                          draws on its face; UNIDENTIFIED and the known details beside
 *   cf-evidence-markers    the photo graded as a scene photo; numbered tent markers
 *                          drop in and bounce, each listed in an evidence legend
 *   cf-phone-records       a phone turns in with its call log; the rows rise, one
 *                          call is flagged and its time and duration roll out beside
 *   cf-cctv-frame          (tag) a CCTV overlay on the footage: corner marks draw in,
 *                          REC blinks, the camera id, a ticking clock, a rolling band
 *   cf-transcript          an interview transcript page: numbered lines, Q/A entries
 *                          rising speaker by speaker, the page scrolling with them,
 *                          the key phrase highlighted
 *
 * Everything is deterministic (seeded by the overlay), clamps its data and
 * returns null when the one field it cannot do without is missing.
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;
type Item = OverlayItem & { suffix?: string; prefix?: string };
type Pt = { x: number; y: number };

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const expoIn = Easing.bezier(0.7, 0, 0.84, 0);
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const pen = Easing.bezier(0.3, 0.05, 0.4, 1);
const GOLD = "#F2B544";
const RED = "#ff3b30";
const CYAN = "#53c8ff";
const INK = "#15181d";
const PAPER = "#f3f1ea";
const STAMP_INK = "#1e2a3b";

// ================================================================== helpers
/** Seeded 0..1 noise: the same input always gives the same number. */
const rnd = (n: number): number => {
  const x = Math.sin(n * 12.9898 + 78.233) * 43758.5453;
  return x - Math.floor(x);
};

const hashStr = (s: string): number => {
  let h = 17;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 1000003;
  return h;
};

const str = (v: unknown): string =>
  typeof v === "string" ? v.trim() : typeof v === "number" && Number.isFinite(v) ? String(v) : "";
const cap = (v: unknown): string => str(v).toUpperCase();
const num = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) ? v : NaN);
const clip = (s: string, n: number): string => (s.length > n ? `${s.slice(0, Math.max(1, n - 1)).trimEnd()}…` : s);
const pad2 = (v: number): string => String(v).padStart(2, "0");
const norm = (s: string): string => s.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
const seedOf = (ov: Overlay): number =>
  (Math.abs(Math.round(num(ov.startFrame) || 0)) % 997) + (hashStr(str(ov.text)) % 991);

/** A colour at an opacity: hex accents become rgba, anything else is returned as it is. */
const tint = (color: string, a: number): string => {
  const c = (color || "").trim();
  const six = /^#([0-9a-f]{6})$/i.exec(c);
  if (six) {
    const v = parseInt(six[1], 16);
    return `rgba(${(v >> 16) & 255},${(v >> 8) & 255},${v & 255},${a})`;
  }
  const three = /^#([0-9a-f]{3})$/i.exec(c);
  if (three) {
    const [r, g, b] = three[1].split("").map((h) => parseInt(h + h, 16));
    return `rgba(${r},${g},${b},${a})`;
  }
  return c;
};

const stillOf = (m: SceneMedia | null | undefined): string => {
  if (!m || typeof m !== "object") return "";
  const s = m.type === "image" ? m.url : m.thumbnail;
  return typeof s === "string" ? s.trim() : "";
};

const stills = (ov: Overlay, max: number): string[] =>
  (Array.isArray(ov.media) ? ov.media : []).map((m) => stillOf(m)).filter((s) => s.length > 0).slice(0, max);

/** The overlay's items that carry any words, capped. */
const itemsOf = (ov: Overlay, max: number): Item[] =>
  (Array.isArray(ov.items) ? (ov.items as Item[]) : [])
    .filter((it) => Boolean(it) && typeof it === "object" && (str(it.label).length > 0 || str(it.text).length > 0))
    .slice(0, max);

/** A choreography written for `need` seconds, compressed (never stretched) into a shorter graphic. */
const usePace = (need: number): number => {
  const { durationInFrames, fps } = useVideoConfig();
  return Math.max(0.5, Math.min(1, (durationInFrames - 24) / Math.max(1, need * fps)));
};

/** 0 -> 1 over the last `len` frames: the exit. */
const useExit = (len = 12): number => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return ramp(frame, durationInFrames - len, Math.max(2, len - 2), expoIn);
};

/** A damped knock (a stamp hitting, a seal pressed): 0 before `at`. */
const jolt = (frame: number, at: number, amp: number): number => {
  const t = frame - at;
  return t < 0 ? 0 : amp * Math.exp(-t / 2.4) * Math.cos(t * 2.2);
};

/** A line rising out of its mask, and out through the top at the end. */
const Rise: React.FC<{ at: number; frames?: number; out?: number; style?: React.CSSProperties; children?: React.ReactNode }> =
  ({ at, frames = 16, out, style, children }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();
    const pin = ramp(frame, at, frames);
    const pout = ramp(frame, out ?? durationInFrames - 13, 10, expoIn);
    const hidden = pin <= 0.001 || pout >= 0.999;
    return (
      <div style={{ overflow: "hidden", paddingBottom: "0.12em", marginBottom: "-0.12em", ...style }}>
        <div style={{ transform: `translateY(${((1 - pin) - pout) * 118}%)`, opacity: hidden ? 0 : 1 }}>{children}</div>
      </div>
    );
  };

/** LetterLine (letters rise in one by one), its exit timed to finish before the graphic ends. */
const Letters: React.FC<{ text: string; at: number; step?: number; style?: React.CSSProperties }> =
  ({ text, at, step = 0.8, style }) => {
    const { durationInFrames } = useVideoConfig();
    const n = Array.from(text).length;
    const outAt = Math.round(durationInFrames - 11 - Math.min(n, 26) * 0.6);
    return <LetterLine text={text} at={at} step={step} outAt={outAt} style={{ whiteSpace: "nowrap", ...style }} />;
  };

/** Handwriting writing itself on at pen speed (a clip wipe), wiped off again at the end. */
const Written: React.FC<{ text: string; at: number; size: number; color?: string; cps?: number }> =
  ({ text, at, size, color = INK, cps = 1.6 }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();
    const p = interpolate(frame, [at, at + Math.max(6, text.length / cps)], [0, 1], { ...clamp, easing: pen });
    const o = ramp(frame, durationInFrames - 13, 10, expoIn);
    if (!text) return null;
    return (
      <div style={{ display: "inline-block", fontFamily: HAND, fontWeight: 700, fontSize: size, lineHeight: 1.05, color,
        whiteSpace: "nowrap", clipPath: `inset(-30% ${((1 - p) * 104 - 2).toFixed(2)}% -30% ${(o * 104 - 3).toFixed(2)}%)` }}>
        {text}
      </div>
    );
  };

/** A printed rule drawing on left to right. */
const Rule: React.FC<{ at: number; color?: string; h?: number }> = ({ at, color = "rgba(21,24,29,.32)", h = 1.5 }) => {
  const frame = useCurrentFrame();
  const k = useK();
  return <div style={{ height: h * k, background: color, transform: `scaleX(${ramp(frame, at, 16)})`, transformOrigin: "0 50%" }} />;
};

/**
 * The odometer for a preformatted string ("11:42", "4:36"): every digit rolls
 * into place, the right-most furthest; separators stay put. A soft mask
 * instead of a blur keeps it cheap.
 */
const DigitRoll: React.FC<{ text: string; at: number; frames: number; size: number; color: string; font?: string }> =
  ({ text, at, frames, size, color, font = DISPLAY }) => {
    const frame = useCurrentFrame();
    const chars = Array.from(text);
    const nd = chars.filter((c) => /\d/.test(c)).length;
    let di = 0;
    return (
      <span style={{ display: "inline-flex", alignItems: "flex-start", fontFamily: font, fontSize: size, lineHeight: 1, color,
        whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
        {chars.map((c, i) => {
          if (!/\d/.test(c)) {
            return <span key={i} style={{ whiteSpace: "pre", opacity: ramp(frame, at + 2, 8) }}>{c}</span>;
          }
          const fromRight = nd - 1 - di;
          di += 1;
          const travel = (1 + Math.min(2, fromRight)) * 10 + Number(c);
          const p = ramp(frame, at + fromRight * 2, frames);
          const pos = p * travel;
          const moving = p > 0.001 && p < 0.985;
          const fade = moving ? "linear-gradient(180deg, rgba(0,0,0,0) 0%, #000 16%, #000 84%, rgba(0,0,0,0) 100%)" : undefined;
          return (
            <span key={i} style={{ display: "inline-block", height: size, overflow: "hidden", WebkitMaskImage: fade, maskImage: fade }}>
              <span style={{ display: "flex", flexDirection: "column", transform: `translateY(${(-(pos % 10) * size).toFixed(2)}px)` }}>
                {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 0].map((d, j) => <span key={j} style={{ height: size, display: "block" }}>{d}</span>)}
              </span>
            </span>
          );
        })}
      </span>
    );
  };

/** A dark steel desk under a soft top light: the backdrop for objects. */
const SteelDesk: React.FC<{ glow?: string }> = ({ glow }) => {
  const k = useK();
  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 40%, #2a2d33 0%, #17191d 52%, #08090b 100%)" }}>
      <AbsoluteFill style={{ backgroundImage:
        "repeating-linear-gradient(90deg, rgba(255,255,255,.014) 0px, rgba(255,255,255,.014) 1px, rgba(255,255,255,0) 1px, rgba(255,255,255,0) 3px)" }} />
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 60% 55% at 50% 32%, rgba(255,244,228,.11) 0%, rgba(255,244,228,0) 70%)" }} />
      {glow ? <AbsoluteFill style={{ background: glow }} /> : null}
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${320 * k}px rgba(0,0,0,.78)` }} />
    </AbsoluteFill>
  );
};

// ================================================================== 1. evidence bag
const caption = (k: number, size = 18): React.CSSProperties => ({ fontFamily: LABEL, fontWeight: 700, fontSize: size * k,
  letterSpacing: "0.2em", color: "#6b6f77", whiteSpace: "nowrap" });

/** A printed form field: its caption rises, the value is written on its line. */
const Field: React.FC<{ label: string; at: number; width: number; children?: React.ReactNode }> = ({ label, at, width, children }) => {
  const k = useK();
  return (
    <div style={{ width, display: "flex", flexDirection: "column", gap: 4 * k }}>
      <Rise at={at}><span style={caption(k)}>{label}</span></Rise>
      <div style={{ height: 52 * k, display: "flex", alignItems: "flex-end", paddingLeft: 4 * k }}>{children}</div>
      <Rule at={at + 2} />
    </div>
  );
};

const barcodePath = (w: number, h: number, seed: number): string => {
  const unit = w / 96;
  let x = 0;
  let d = "";
  for (let i = 0; i < 80; i++) {
    const bw = (1 + Math.floor(rnd(seed + i * 1.7) * 3)) * unit;
    if (x + bw > w) break;
    d += `M${x.toFixed(1)} 0h${bw.toFixed(1)}v${h.toFixed(1)}h${(-bw).toFixed(1)}Z`;
    x += bw + (1 + Math.floor(rnd(seed + i * 2.9) * 2)) * unit;
  }
  return d;
};

/** A signature scrawl (loops riding a wave) for a custody row signed but not named. */
const scrawl = (w: number, h: number, seed: number): string => {
  const loops = 5 + Math.floor(rnd(seed) * 3);
  let d = "";
  for (let i = 0; i <= 84; i++) {
    const t = i / 84;
    const a = t * loops * Math.PI * 2;
    const env = Math.sin(Math.PI * Math.min(1, t * 1.08));
    const x = t * w * 0.9 + Math.cos(a + seed) * h * 0.2 * env;
    const y = h * 0.58 - Math.sin(a) * h * 0.32 * env * (0.65 + 0.35 * rnd(seed + Math.floor(t * loops)))
      + Math.sin(t * 5 + seed) * h * 0.08;
    d += `${i ? " L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
  }
  return d;
};

/**
 * value = item number, text = description, label = case number, subtitle =
 * where it was collected, items = chain of custody (label who, text when).
 * The story's still (media) sits inside the bag as a print.
 */
const EvidenceBag: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const q = useExit(14);
  const pace = usePace(4.2);
  const seed = seedOf(overlay);
  const desc = str(overlay.text);
  const caseNo = clip(cap(overlay.label), 14);
  const place = clip(str(overlay.subtitle), 22);
  const itemNo = num(overlay.value);
  const hasNo = Number.isFinite(itemNo) && itemNo >= 0 && itemNo < 100000;
  const rows = itemsOf(overlay, 3);
  const pic = stills(overlay, 1)[0] || "";
  if (!desc && !caseNo && !hasNo) return null;
  const T = (s: number) => Math.round(s * fps * pace);
  const wr = 1.7;
  const allDesc = lines(desc, 30);
  const descLines = allDesc.slice(0, 2);
  if (allDesc.length > 2) descLines[1] = `${descLines[1]}…`;
  const caseAt = T(0.62);
  const placeAt = caseAt + Math.round(Math.max(6, caseNo.length / wr)) + 3;
  const descAt = T(1.1);
  const desc2At = descAt + Math.round(Math.max(6, (descLines[0] || "").length / wr)) + 2;
  const rowsAt = T(1.85);
  const rowGap = T(0.45);
  const custody: (Item | null)[] = rows.length ? rows : [null, null];
  const sealAt = rowsAt + custody.length * rowGap + T(0.3);
  const land = ramp(frame, 0, T(0.75));
  const sheen = ramp(frame, T(0.2), T(1.4), inOut);
  const seal = ramp(frame, sealAt, 12);
  const bump = jolt(frame, sealAt + 8, 3 * k);
  const BW = (pic ? 1400 : 820) * k, BH = 810 * k, LW = 700 * k;
  const barW = 250 * k, barH = 44 * k;
  const barP = ramp(frame, T(0.55), 16);
  const code = caseNo ? caseNo.replace(/\s+/g, "") : hasNo ? `ITEM-${String(Math.round(itemNo)).padStart(3, "0")}` : "";
  const edge = (dir: string): string =>
    `repeating-linear-gradient(${dir}, rgba(255,255,255,.13) 0px, rgba(255,255,255,.13) 2px, rgba(255,255,255,0) 2px, rgba(255,255,255,0) 6px)`;
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <SteelDesk />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{ position: "relative", width: BW, height: BH, borderRadius: 20 * k, opacity: ramp(frame, 0, 5) * (1 - q),
          transform: `translateY(${((1 - land) * 300 + q * 170) * k + bump}px) rotate(${-2 - (1 - land) * 8 + q * 5}deg) scale(${(0.94 + 0.06 * land) * hold})`,
          background: "linear-gradient(158deg, rgba(255,255,255,.16) 0%, rgba(255,255,255,.05) 34%, rgba(255,255,255,.1) 58%, rgba(255,255,255,.03) 100%)",
          border: `${1.5 * k}px solid rgba(255,255,255,.3)`,
          boxShadow: `0 ${46 * k}px ${110 * k}px rgba(0,0,0,.62), inset 0 0 ${40 * k}px rgba(255,255,255,.05)` }}>
          {/* heat-sealed edges */}
          <div style={{ position: "absolute", left: 0, top: 70 * k, bottom: 0, width: 18 * k, backgroundImage: edge("0deg") }} />
          <div style={{ position: "absolute", right: 0, top: 70 * k, bottom: 0, width: 18 * k, backgroundImage: edge("0deg") }} />
          <div style={{ position: "absolute", left: 18 * k, right: 18 * k, bottom: 0, height: 18 * k, backgroundImage: edge("90deg") }} />
          {/* zip seal */}
          <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 70 * k, background: "rgba(255,255,255,.07)",
            borderBottom: `${1.5 * k}px solid rgba(255,255,255,.22)`, borderRadius: `${20 * k}px ${20 * k}px 0 0` }}>
            <div style={{ position: "absolute", left: 26 * k, right: 26 * k, top: 22 * k, height: 3 * k, borderRadius: 2 * k,
              background: "rgba(255,255,255,.3)" }} />
            <div style={{ position: "absolute", left: 26 * k, right: 26 * k, top: 32 * k, height: 3 * k, borderRadius: 2 * k,
              background: "rgba(255,255,255,.18)" }} />
          </div>
          {pic ? (
            <div style={{ position: "absolute", left: 64 * k, top: 108 * k, width: 530 * k, height: 640 * k, padding: 14 * k,
              boxSizing: "border-box", background: "#efede6", boxShadow: `0 ${14 * k}px ${30 * k}px rgba(0,0,0,.42)`,
              transform: `rotate(${-2.5 + Math.sin(frame / (fps * 2.2)) * 0.25}deg)` }}>
              <SafeImg src={pic} style={{ width: "100%", height: "100%", objectFit: "cover", display: "block",
                filter: "grayscale(.3) contrast(1.06) brightness(.94)" }} />
            </div>
          ) : null}
          {/* the printed label */}
          <div style={{ position: "absolute", left: (pic ? 640 : 60) * k, top: 100 * k, width: LW, borderRadius: 6 * k, overflow: "hidden",
            background: `linear-gradient(180deg, #f7f5ef 0%, ${PAPER} 100%)`, boxShadow: `0 ${8 * k}px ${22 * k}px rgba(0,0,0,.35)` }}>
            <div style={{ height: 78 * k, background: INK, display: "flex", alignItems: "center", justifyContent: "space-between",
              padding: `0 ${26 * k}px`, boxSizing: "border-box" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 14 * k }}>
                <div style={{ width: 16 * k, height: 16 * k, background: accent, transform: `scale(${ramp(frame, T(0.2), 10, backOut)})` }} />
                <Letters text="EVIDENCE" at={T(0.25)} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 42 * k,
                  letterSpacing: "0.22em", color: "#fff", lineHeight: 1 }} />
              </div>
              {hasNo ? (
                <div style={{ display: "flex", alignItems: "center", gap: 12 * k }}>
                  <Letters text="ITEM" at={T(0.32)} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 24 * k,
                    letterSpacing: "0.22em", color: "rgba(255,255,255,.6)" }} />
                  <Odometer value={Math.round(itemNo)} at={T(0.35)} frames={T(1.0)} size={60 * k} color={accent}
                    prefix={itemNo < 10 ? "0" : ""} grouping={false} />
                </div>
              ) : null}
            </div>
            <div style={{ display: "flex", gap: 26 * k, padding: `${16 * k}px ${26 * k}px 0` }}>
              <Field label="CASE NO." at={T(0.4)} width={250 * k}>
                {caseNo ? <Written text={caseNo} at={caseAt} size={40 * k} cps={wr} /> : null}
              </Field>
              <Field label="LOCATION" at={T(0.45)} width={LW - 328 * k}>
                {place ? <Written text={place} at={placeAt} size={40 * k} cps={wr} /> : null}
              </Field>
            </div>
            <div style={{ padding: `${14 * k}px ${26 * k}px 0` }}>
              <Rise at={T(0.5)}><span style={caption(k)}>DESCRIPTION OF EVIDENCE</span></Rise>
              <div style={{ height: 100 * k, display: "flex", flexDirection: "column", justifyContent: "flex-end", alignItems: "flex-start",
                paddingLeft: 4 * k }}>
                {descLines.map((ln, i) => <Written key={i} text={ln} at={i ? desc2At : descAt} size={44 * k} cps={wr} />)}
              </div>
              <Rule at={T(0.55)} />
            </div>
            <div style={{ padding: `${16 * k}px ${26 * k}px 0` }}>
              <div style={{ display: "flex", alignItems: "center", gap: 14 * k }}>
                <Rise at={T(0.6)}><span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 22 * k, letterSpacing: "0.22em",
                  color: INK, whiteSpace: "nowrap" }}>CHAIN OF CUSTODY</span></Rise>
                <div style={{ flex: 1 }}><Rule at={T(0.65)} color={INK} h={2} /></div>
              </div>
              <div style={{ display: "flex", marginTop: 8 * k }}>
                <div style={{ width: "62%" }}><Rise at={T(0.7)}><span style={caption(k, 16)}>RELEASED BY · RECEIVED BY</span></Rise></div>
                <div style={{ flex: 1, paddingLeft: 12 * k }}><Rise at={T(0.72)}><span style={caption(k, 16)}>DATE · TIME</span></Rise></div>
              </div>
              {custody.map((it, i) => {
                const at = rowsAt + i * rowGap;
                const who = it ? clip(str(it.label), 24) : "";
                const when = it ? clip(str(it.text), 16) : "";
                const sig = ramp(frame, at + 3, T(0.5), pen);
                return (
                  <div key={i} style={{ position: "relative", height: 58 * k, display: "flex", alignItems: "flex-end" }}>
                    <div style={{ width: "62%", paddingBottom: 7 * k, paddingLeft: 4 * k }}>
                      {who ? <Written text={who} at={at + 3} size={32 * k} cps={wr * 1.4} /> : (
                        <svg width={200 * k} height={44 * k} style={{ display: "block", overflow: "visible" }}>
                          <path d={scrawl(200 * k, 44 * k, seed + i * 7)} fill="none" stroke={INK} strokeWidth={2.4 * k}
                            strokeLinecap="round" strokeLinejoin="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - sig} />
                        </svg>
                      )}
                    </div>
                    <div style={{ flex: 1, paddingBottom: 7 * k, paddingLeft: 12 * k }}>
                      {when ? <Written text={when} at={at + 3 + Math.round(who.length / (wr * 2.8))} size={30 * k} cps={wr * 1.4} /> : null}
                    </div>
                    <div style={{ position: "absolute", left: 0, right: 0, bottom: 0 }}><Rule at={at} /></div>
                    <div style={{ position: "absolute", left: "62%", top: 10 * k, bottom: 0, width: 1.5 * k, background: "rgba(21,24,29,.2)",
                      transform: `scaleY(${ramp(frame, at + 2, 10)})`, transformOrigin: "50% 100%" }} />
                  </div>
                );
              })}
            </div>
            <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between",
              padding: `${18 * k}px ${26 * k}px ${20 * k}px` }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 5 * k }}>
                <svg width={barW} height={barH} style={{ display: "block", clipPath: `inset(0 ${((1 - barP) * 100).toFixed(2)}% 0 0)` }}>
                  <path d={barcodePath(barW, barH, seed)} fill={INK} />
                </svg>
                {code ? (
                  <Rise at={T(0.6)}><span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 15 * k, letterSpacing: "0.32em",
                    color: "#555a62" }}>{code}</span></Rise>
                ) : null}
              </div>
              <Rise at={T(0.62)}><span style={caption(k, 16)}>EVIDENCE · DO NOT OPEN</span></Rise>
            </div>
          </div>
          {/* the plastic: a sheen sweeping once, a few creases */}
          <div style={{ position: "absolute", left: 0, top: 0, right: 0, bottom: 0, borderRadius: 20 * k, overflow: "hidden" }}>
            <div style={{ position: "absolute", top: 0, bottom: 0, left: "-60%", width: "60%",
              transform: `translateX(${(sheen * 330).toFixed(1)}%) skewX(-16deg)`,
              background: "linear-gradient(90deg, rgba(255,255,255,0) 0%, rgba(255,255,255,.2) 45%, rgba(255,255,255,.06) 55%, rgba(255,255,255,0) 100%)" }} />
            {[0.18, 0.52, 0.8].map((x, i) => (
              <div key={i} style={{ position: "absolute", left: `${x * 100}%`, top: "8%", height: "84%", width: 2 * k,
                transform: `rotate(${8 + i * 5}deg)`,
                background: "linear-gradient(180deg, rgba(255,255,255,0), rgba(255,255,255,.18), rgba(255,255,255,0))" }} />
            ))}
          </div>
          {/* the tamper seal, pressed on last */}
          <div style={{ position: "absolute", left: -14 * k, right: -14 * k, top: 13 * k, height: 44 * k, background: accent,
            clipPath: `inset(0 ${((1 - seal) * 100).toFixed(2)}% 0 0)`, display: "flex", alignItems: "center", overflow: "hidden",
            boxShadow: `0 ${4 * k}px ${12 * k}px rgba(0,0,0,.35)`, transform: "rotate(-0.6deg)" }}>
            <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 17 * k, letterSpacing: "0.3em", color: INK, whiteSpace: "nowrap",
              paddingLeft: 24 * k }}>{"EVIDENCE · SEALED · DO NOT TAMPER · ".repeat(pic ? 5 : 3)}</span>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 2. case file cover
/** A rubber-stamp ink texture: seeded speckles and dry streaks punched out of a mask. */
const inkMask = (seed: number): string => {
  const f = (v: number) => v.toFixed(1);
  let holes = "";
  for (let i = 0; i < 90; i++) {
    const x = rnd(seed + i * 3.7) * 400;
    const y = rnd(seed + i * 5.3) * 200;
    const r = 0.6 + Math.pow(rnd(seed + i * 7.1), 2) * 3.4;
    holes += `M${f(x - r)} ${f(y)}a${f(r)} ${f(r)} 0 1 0 ${f(2 * r)} 0a${f(r)} ${f(r)} 0 1 0 ${f(-2 * r)} 0`;
  }
  for (let i = 0; i < 6; i++) {
    const x = rnd(seed + i * 11.3) * 360;
    const y = rnd(seed + i * 13.1) * 190;
    const len = 30 + rnd(seed + i * 17.9) * 80;
    holes += `M${f(x)} ${f(y)}h${f(len)}v1.4h${f(-len)}Z`;
  }
  const svg = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 400 200' preserveAspectRatio='none'>" +
    "<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='0.4'><stop offset='0' stop-color='#000' stop-opacity='.96'/>" +
    "<stop offset='.6' stop-color='#000' stop-opacity='.86'/><stop offset='1' stop-color='#000' stop-opacity='.64'/></linearGradient></defs>" +
    `<path fill='url(#g)' fill-rule='evenodd' d='M-10 -10H410V210H-10Z${holes}'/></svg>`;
  return `url("data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}")`;
};

/**
 * text = the case title, label (or value) = the case number, subtitle = the
 * department line, highlight = an optional word stamped in red (UNSOLVED).
 */
const CaseCover: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const q = useExit(14);
  const pace = usePace(3.6);
  const seed = seedOf(overlay);
  const title = str(overlay.text);
  const rawNo = str(overlay.label);
  const v = num(overlay.value);
  const caseNo = /\d/.test(rawNo) ? clip(rawNo.toUpperCase().replace(/^(CASE\s*)?(NO\.?|#)\s*/, "").trim(), 12)
    : Number.isFinite(v) ? String(Math.round(Math.abs(v))).slice(0, 10) : "";
  const dept = clip(cap(overlay.subtitle), 44);
  const hl = cap(overlay.highlight);
  const word = hl.length > 0 && hl.length <= 14 ? hl : "";
  if (!title && !caseNo) return null;
  const T = (s: number) => Math.round(s * fps * pace);
  const W = 1240 * k, H = 760 * k;
  const land = ramp(frame, 0, T(0.8));
  const chars = Array.from(caseNo);
  const boxAt = T(1.0);
  const digitAt = (i: number) => boxAt + 4 + i * 3;
  const wordAt = digitAt(chars.length) + T(0.35);
  const wordHit = wordAt + 5;
  let shake = 0;
  if (caseNo) shake += jolt(frame, boxAt + 3, 3 * k);
  chars.forEach((c, i) => {
    if (c.trim()) shake += jolt(frame, digitAt(i) + 2, 1.6 * k);
  });
  if (word) shake += jolt(frame, wordHit, 8 * k);
  const tl = lines(title.toUpperCase(), 24).slice(0, 2);
  const tSize = (tl.some((l) => l.length > 17) ? 68 : 82) * k;
  const numMask = inkMask(seed);
  const wordMask = inkMask(seed + 57);
  const wordFall = interpolate(frame, [wordAt, wordHit], [0, 1], { ...clamp, easing: Easing.in(Easing.quad) });
  const sticker = ramp(frame, T(0.5), 12);
  const boxIn = ramp(frame, boxAt, 5);
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <CaseBackdrop tone="dark" seed={7} />
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 55%, rgba(0,0,0,0) 30%, rgba(0,0,0,.35) 100%)" }} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", perspective: 2600 * k }}>
        <div style={{ position: "relative", width: W, height: H, marginTop: 60 * k, opacity: ramp(frame, 0, 6) * (1 - q),
          transform: `translate(${((1 - land) * 460 - q * 200) * k}px, ${((1 - land) * 130 + q * 80) * k + shake}px) ` +
            `rotateX(${12 - 4 * land}deg) rotate(${-2 + (1 - land) * 9 - q * 5}deg) scale(${hold})` }}>
          {/* back cover and its tab */}
          <div style={{ position: "absolute", left: 16 * k, top: -12 * k, width: W, height: H, borderRadius: 10 * k,
            background: "linear-gradient(170deg, #c7ab74 0%, #b3955b 100%)", boxShadow: `0 ${40 * k}px ${90 * k}px rgba(0,0,0,.55)` }} />
          <div style={{ position: "absolute", left: 80 * k, top: -66 * k, width: 370 * k, height: 76 * k, boxSizing: "border-box",
            borderRadius: `${16 * k}px ${16 * k}px 0 0`, background: "linear-gradient(180deg, #d6bd8a 0%, #c6a970 100%)",
            display: "flex", alignItems: "flex-start", paddingTop: 18 * k, paddingLeft: 30 * k }}>
            <Letters text="CASE FILE" at={T(0.3)} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 28 * k, letterSpacing: "0.3em",
              color: "rgba(21,24,29,.8)", lineHeight: 1 }} />
          </div>
          {/* front cover */}
          <div style={{ position: "absolute", left: 0, top: 0, width: W, height: H, borderRadius: 8 * k, overflow: "hidden",
            background: "linear-gradient(160deg, #e3d0a7 0%, #d8c193 45%, #c9ad79 100%)",
            boxShadow: `inset 0 0 ${70 * k}px rgba(120,84,30,.3), 0 ${6 * k}px ${16 * k}px rgba(0,0,0,.25)` }}>
            <AbsoluteFill style={{ backgroundImage:
              "repeating-linear-gradient(8deg, rgba(110,80,35,.035) 0px, rgba(110,80,35,.035) 2px, rgba(0,0,0,0) 2px, rgba(0,0,0,0) 7px)" }} />
            <AbsoluteFill style={{ background: "radial-gradient(ellipse at 28% 22%, rgba(255,250,235,.38) 0%, rgba(255,250,235,0) 55%)" }} />
            <div style={{ position: "absolute", left: 46 * k, top: 0, bottom: 0, width: 3 * k,
              background: "linear-gradient(90deg, rgba(90,62,20,.28), rgba(255,245,220,.4))" }} />
            {dept ? (
              <div style={{ position: "absolute", left: 96 * k, top: 50 * k }}>
                <Letters text={dept} at={T(0.4)} step={0.45} style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 26 * k,
                  letterSpacing: "0.22em", color: "rgba(21,24,29,.82)" }} />
              </div>
            ) : null}
            <div style={{ position: "absolute", left: 96 * k, right: 80 * k, top: 98 * k }}>
              <Rule at={T(0.35)} color="rgba(21,24,29,.78)" h={4} />
              <div style={{ height: 6 * k }} />
              <Rule at={T(0.4)} color="rgba(21,24,29,.6)" h={1.5} />
            </div>
            {title ? (
              <div style={{ position: "absolute", left: 96 * k, top: 330 * k }}>
                <Rise at={T(0.45)}><span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 20 * k, letterSpacing: "0.3em",
                  color: "rgba(21,24,29,.6)" }}>SUBJECT</span></Rise>
                <div style={{ marginTop: 10 * k, padding: `${22 * k}px ${34 * k}px ${16 * k}px`, width: 800 * k, boxSizing: "border-box",
                  background: "#f8f6f0", border: `${1 * k}px solid rgba(0,0,0,.12)`, boxShadow: `0 ${3 * k}px ${10 * k}px rgba(0,0,0,.18)`,
                  opacity: sticker, transform: `rotate(0.6deg) scale(${1.05 - 0.05 * sticker})`, transformOrigin: "20% 50%" }}>
                  {tl.map((ln, i) => (
                    <Letters key={i} text={ln} at={T(0.6) + i * 5} step={0.7} style={{ fontFamily: DISPLAY, fontSize: tSize,
                      lineHeight: 1.02, color: INK, letterSpacing: "0.03em" }} />
                  ))}
                </div>
              </div>
            ) : null}
            {caseNo ? (
              <div style={{ position: "absolute", right: 84 * k, top: 150 * k, mixBlendMode: "multiply",
                opacity: frame >= boxAt ? 0.92 : 0, transform: `rotate(-3.5deg) scale(${1 + 0.22 * (1 - boxIn)})`,
                WebkitMaskImage: numMask, maskImage: numMask, WebkitMaskSize: "100% 100%", maskSize: "100% 100%" }}>
                <div style={{ border: `${5 * k}px solid ${STAMP_INK}`, outline: `${2 * k}px solid ${STAMP_INK}`, outlineOffset: -12 * k,
                  padding: `${20 * k}px ${36 * k}px ${14 * k}px`, display: "flex", flexDirection: "column", alignItems: "center", gap: 4 * k }}>
                  <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 24 * k, letterSpacing: "0.34em", color: STAMP_INK }}>CASE NO.</span>
                  <div style={{ display: "flex", fontFamily: DISPLAY, fontSize: 104 * k, lineHeight: 1, color: STAMP_INK, letterSpacing: "0.04em" }}>
                    {chars.map((c, i) => {
                      const at = digitAt(i);
                      return (
                        <span key={i} style={{ display: "inline-block", whiteSpace: "pre", opacity: frame >= at ? 1 : 0,
                          transform: `scale(${1.4 - 0.4 * ramp(frame, at, 4)})` }}>{c}</span>
                      );
                    })}
                  </div>
                </div>
              </div>
            ) : null}
            {word ? (
              <div style={{ position: "absolute", right: 120 * k, bottom: 96 * k, mixBlendMode: "multiply",
                opacity: frame >= wordAt ? 0.35 + 0.55 * wordFall : 0, transform: `rotate(-10deg) scale(${2.1 - 1.1 * wordFall})`,
                WebkitMaskImage: wordMask, maskImage: wordMask, WebkitMaskSize: "100% 100%", maskSize: "100% 100%" }}>
                <div style={{ border: `${6 * k}px solid ${RED}`, outline: `${2 * k}px solid ${RED}`, outlineOffset: -13 * k,
                  padding: `${16 * k}px ${40 * k}px ${8 * k}px`, fontFamily: DISPLAY, fontSize: 86 * k, lineHeight: 1,
                  letterSpacing: "0.1em", color: RED, whiteSpace: "nowrap" }}>{word}</div>
              </div>
            ) : null}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 3. redacted document
type Tok = { w: string; red: boolean; em: number };

/** Body words in runs: a few left readable, then a run blacked out, and so on. */
const redactRuns = (words: string[], seed: number): Tok[] => {
  const out: Tok[] = [];
  let red = rnd(seed) > 0.45;
  let left = 1 + Math.floor(rnd(seed + 1) * 3);
  words.forEach((w, i) => {
    out.push({ w, red, em: 0 });
    left -= 1;
    if (left <= 0) {
      red = !red;
      left = red ? 2 + Math.floor(rnd(seed + i * 5.3) * 5) : 1 + Math.floor(rnd(seed + i * 7.1) * 3);
    }
  });
  return out;
};

/** No body given: a fully redacted passage (bars of seeded lengths). */
const ghostRuns = (n: number, seed: number): Tok[] =>
  Array.from({ length: n }, (_, i) => ({ w: "", red: true, em: 1.4 + rnd(seed + i * 3.1) * 4.2 }));

const breakToks = (toks: Tok[], cpl: number): Tok[][] => {
  const out: Tok[][] = [];
  let cur: Tok[] = [];
  let len = 0;
  toks.forEach((t) => {
    const l = t.w ? t.w.length : t.em / 0.55;
    if (cur.length && len + 1 + l > cpl) {
      out.push(cur);
      cur = [];
      len = 0;
    }
    len += (cur.length ? 1 : 0) + l;
    cur.push(t);
  });
  if (cur.length) out.push(cur);
  return out;
};

/**
 * highlight = the key line (revealed), text = the document heading (or the
 * key line when no highlight), body = the surrounding text (mostly redacted),
 * subtitle = the issuing office, label = a date or file reference.
 */
const Redacted: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const q = useExit(14);
  const pace = usePace(3.9);
  const seed = seedOf(overlay);
  const hl = str(overlay.highlight);
  const title = str(overlay.text);
  const keyText = clip(hl || title, 190);
  if (!keyText) return null;
  const T = (s: number) => Math.round(s * fps * pace);
  const dup = Boolean(hl && title && norm(hl).includes(norm(title).slice(0, 28)));
  const heading = hl && !dup ? title : "";
  const headLines = lines(heading.toUpperCase(), 36).slice(0, 2);
  const agency = clip(cap(overlay.subtitle) || "OFFICIAL RECORD", 40);
  const ref = clip(cap(overlay.label), 22);
  const body = str(overlay.body);
  const bodyDup = body.length > 0 && Boolean(hl) &&
    (norm(body).includes(norm(hl).slice(0, 36)) || norm(hl).includes(norm(body).slice(0, 36)));
  const words = bodyDup ? [] : body.split(/\s+/).filter(Boolean).slice(0, 90);
  const CPL = 60;
  const split = words.length ? Math.min(words.length, Math.max(12, Math.round(words.length * 0.38))) : 0;
  const fill = (ls: Tok[][], min: number, s: number): Tok[][] =>
    ls.length >= min ? ls : ls.concat(breakToks(ghostRuns(11 * (min - ls.length), s), CPL)).slice(0, min);
  const before = fill(words.length ? breakToks(redactRuns(words.slice(0, split), seed), CPL).slice(0, 4) : [], 2, seed + 5);
  const after = fill(words.length ? breakToks(redactRuns(words.slice(split), seed + 17), CPL).slice(0, 6) : [], 5, seed + 29);
  const kBase = keyText.length > 120 ? 27 : keyText.length > 64 ? 30 : 34;
  const keyLines = lines(keyText, keyText.length > 120 ? 54 : keyText.length > 64 ? 48 : 42).slice(0, 4);
  const land = ramp(frame, 0, T(0.85));
  const revealAt = T(1.7);
  const bodyAt = T(0.35);
  const dim = ramp(frame, revealAt + 6, 16);
  const zoom = 1 + 0.1 * ramp(frame, revealAt - 4, T(2.2), inOut);
  const headH = headLines.length ? headLines.length * 44 * 1.12 + 18 : 0;
  const keyTop = 70 + 32 + 14 + 11.5 + 30 + headH + before.length * 50 + 20;
  const keyY = (96 + keyTop + (keyLines.length * kBase * 1.45) / 2) * k;
  const bar = ramp(frame, revealAt + 8, 14);
  const renderLine = (toks: Tok[], idx: number, last: boolean) => (
    <Rise key={`l${idx}`} at={bodyAt + idx * 2} style={{ opacity: 1 - 0.6 * dim }}>
      <div style={{ display: "flex", justifyContent: last ? "flex-start" : "space-between", gap: "0.32em", whiteSpace: "nowrap",
        fontFamily: INTER, fontWeight: 500, fontSize: 25 * k, lineHeight: 2.0, color: "#2b3038" }}>
        {toks.map((t, ti) => {
          const bp = ramp(frame, T(0.55) + idx * 1.6 + ti * 0.35, 7);
          if (!t.red) return <span key={ti}>{t.w}</span>;
          if (!t.w) {
            return <span key={ti} style={{ display: "inline-block", alignSelf: "center", width: `${t.em.toFixed(2)}em`, height: "0.82em",
              background: INK, borderRadius: 2 * k, transform: `scaleX(${bp})`, transformOrigin: "0 50%" }} />;
          }
          return (
            <span key={ti} style={{ color: "rgba(0,0,0,0)", backgroundImage: `linear-gradient(${INK}, ${INK})`, backgroundRepeat: "no-repeat",
              backgroundPosition: "0 56%", backgroundSize: `${(bp * 100).toFixed(1)}% 52%`, borderRadius: 2 * k }}>{t.w}</span>
          );
        })}
      </div>
    </Rise>
  );
  let wordIndex = 0;
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <CaseBackdrop tone="light" seed={9} />
      <AbsoluteFill style={{ transform: `scale(${zoom})`, transformOrigin: `50% ${keyY.toFixed(1)}px`, perspective: 2400 * k }}>
        <div style={{ position: "absolute", left: 430 * k, top: 96 * k, width: 1060 * k, height: 1300 * k, boxSizing: "border-box",
          padding: `${70 * k}px ${90 * k}px`, display: "flex", flexDirection: "column",
          background: "linear-gradient(180deg, #fdfcf8 0%, #f4f1e8 100%)", boxShadow: `0 ${50 * k}px ${110 * k}px rgba(10,20,35,.38)`,
          opacity: ramp(frame, 0, 6) * (1 - q), transformOrigin: "50% 30%",
          transform: `translateY(${((1 - land) * 280 + q * 160) * k}px) rotateX(${6 + (1 - land) * 16 + q * 8}deg) rotate(-1.2deg)` }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", height: 32 * k }}>
            <Letters text={agency} at={T(0.2)} step={0.45} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 25 * k,
              letterSpacing: "0.22em", color: INK }} />
            {ref ? (
              <Rise at={T(0.3)}><span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 18 * k, letterSpacing: "0.2em",
                color: "#6b7480", whiteSpace: "nowrap" }}>{ref}</span></Rise>
            ) : null}
          </div>
          <div style={{ marginTop: 14 * k }}>
            <Rule at={T(0.25)} color={INK} h={4} />
            <div style={{ height: 6 * k }} />
            <Rule at={T(0.3)} color={INK} h={1.5} />
          </div>
          <div style={{ height: 30 * k, flexShrink: 0 }} />
          {headLines.map((ln, i) => (
            <Rise key={`h${i}`} at={T(0.35) + i * 4}>
              <div style={{ fontFamily: NARROW, fontWeight: 700, fontSize: 44 * k, lineHeight: 1.12, color: INK, whiteSpace: "nowrap" }}>{ln}</div>
            </Rise>
          ))}
          {headLines.length ? <div style={{ height: 18 * k, flexShrink: 0 }} /> : null}
          {before.map((ln, li) => renderLine(ln, li, li === before.length - 1))}
          <div style={{ position: "relative", margin: `${20 * k}px 0 ${24 * k}px`, display: "flex", flexDirection: "column", gap: 2 * k }}>
            <div style={{ position: "absolute", left: -38 * k, top: 6 * k, bottom: 6 * k, width: 6 * k, background: accent,
              transform: `scaleY(${bar * (1 - q)})`, transformOrigin: "50% 0" }} />
            {keyLines.map((ln, li) => (
              <Rise key={`k${li}`} at={bodyAt + (before.length + li) * 2}>
                <div style={{ display: "flex", gap: "0.3em", fontFamily: INTER, fontWeight: 700, fontSize: kBase * k, lineHeight: 1.45,
                  color: INK, whiteSpace: "nowrap" }}>
                  {ln.split(" ").map((w, wi) => {
                    const n = wordIndex++;
                    const open = ramp(frame, revealAt + n * 1.6, 10, inOut);
                    const mark = ramp(frame, revealAt + 10 + n * 1.2, 8);
                    return (
                      <span key={wi} style={{ position: "relative", display: "inline-block" }}>
                        <span style={{ position: "absolute", left: "-0.16em", right: "-0.16em", top: "18%", bottom: "10%",
                          background: tint(accent, 0.42), transform: `scaleX(${mark})`, transformOrigin: "0 50%" }} />
                        <span style={{ position: "relative" }}>{w}</span>
                        <span style={{ position: "absolute", left: "-0.1em", right: "-0.1em", top: "14%", bottom: "8%", background: INK,
                          borderRadius: 2 * k, transform: `translateX(${(open * 0.4).toFixed(3)}em) scaleX(${1 - open})`,
                          transformOrigin: "100% 50%" }} />
                      </span>
                    );
                  })}
                </div>
              </Rise>
            ))}
          </div>
          {after.map((ln, li) => renderLine(ln, li + before.length + keyLines.length, li === after.length - 1))}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 4. fingerprint scan
const TIP = "M200 24 C 296 24, 370 110, 370 248 C 370 392, 298 486, 200 490 C 102 486, 30 392, 30 248 C 30 110, 104 24, 200 24 Z";

type Ridge = { d: string; dash: string; off: number };

/** A whorl print: 26 wobbling rings round a low core, broken into ridges by seeded dashes; minutiae on them. */
const printRidges = (seed: number): { ridges: Ridge[]; dots: Pt[] } => {
  const cx = 200, cy = 232;
  const ring = (i: number, a: number): Pt => {
    const r = 6 + i * 9.4;
    const wob = 1 + 0.05 * Math.sin(3 * a + i * 0.7 + seed) + 0.03 * Math.sin(7 * a + i * 1.9 + seed * 0.37);
    const s = Math.sin(a);
    return {
      x: cx + Math.cos(a) * r * 0.86 * wob * (s > 0 ? 1 + 0.16 * s * (i / 26) : 1),
      y: cy + i * 1.7 + s * r * 1.06 * wob * (s > 0 ? 0.88 : 1),
    };
  };
  const ridges: Ridge[] = [];
  for (let i = 0; i < 26; i++) {
    let d = "";
    for (let j = 0; j <= 72; j++) {
      const p = ring(i, (j / 72) * Math.PI * 2 + i * 0.21);
      d += `${j ? " L" : "M"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`;
    }
    const L = 2 * Math.PI * (6 + i * 9.4) * 0.97;
    const a1 = L * (0.3 + 0.45 * rnd(seed + i * 3.3));
    const g1 = 5 + 9 * rnd(seed + i * 5.1);
    const a2 = L * (0.12 + 0.3 * rnd(seed + i * 7.7));
    const g2 = 4 + 8 * rnd(seed + i * 9.4);
    ridges.push({ d, dash: `${a1.toFixed(1)} ${g1.toFixed(1)} ${a2.toFixed(1)} ${g2.toFixed(1)}`, off: L * rnd(seed + i * 1.3) });
  }
  const dots: Pt[] = [];
  for (let n = 0; dots.length < 9 && n < 80; n++) {
    const p = ring(3 + Math.floor(rnd(seed + n * 4.1) * 19), rnd(seed + n * 6.7) * Math.PI * 2);
    const e = ((p.x - 200) / 160) ** 2 + ((p.y - 252) / 205) ** 2;
    if (e < 0.72 && dots.every((o) => Math.hypot(o.x - p.x, o.y - p.y) > 44)) dots.push(p);
  }
  return { ridges, dots };
};

/**
 * value = the match (percent by default), text = the result line, label = the
 * print's name, subtitle = the database. No value: the result alone, big.
 */
const PrintMatch: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const q = useExit(14);
  const pace = usePace(3.4);
  const value = num(overlay.value);
  const hasValue = Number.isFinite(value) && value >= 0 && value < 1e7;
  const result = str(overlay.text);
  if (!hasValue && !result) return null;
  const T = (s: number) => Math.round(s * fps * pace);
  const seed = seedOf(overlay) % 97;
  const suffix = str(overlay.suffix) || (hasValue && value <= 100 ? "%" : "");
  const pct = suffix === "%";
  const label = clip(cap(overlay.label) || "LATENT PRINT", 30);
  const db = clip(cap(overlay.subtitle), 40);
  const { ridges, dots } = printRidges(seed);
  const PW = 440 * k, PH = PW * 1.25, PX = 290 * k, PY = (height - PH) / 2;
  const u = PW / 400;
  const scan0 = T(0.35), scan1 = T(1.55);
  const scanY = interpolate(frame, [scan0, scan1], [0, 500], clamp);
  const scanning = frame >= scan0 && frame < scan1 + 3;
  const done = scan1 + 4;
  const numAt = T(0.55), numFrames = T(1.3);
  const fillP = ramp(frame, numAt, numFrames, inOut) * (pct ? Math.max(0, Math.min(1, value / 100)) : 1);
  const SEG = 32;
  const lit = hasValue ? Math.round(fillP * SEG) : 0;
  const filling = frame < numAt + numFrames;
  const land = ramp(frame, 0, T(0.6));
  const sc = hold * (0.94 + 0.06 * land) * (1 - 0.04 * q);
  const pulse = 0.5 + 0.5 * Math.sin(frame / (fps * 0.35));
  const lead = ramp(frame, T(1.75), T(0.5), inOut);
  const id = `cfp${Math.round(num(overlay.startFrame) || 0)}`;
  const resLines = hasValue ? lines(result, 30).slice(0, 2) : lines(result.toUpperCase(), 20).slice(0, 2);
  const panelH = 30 + 14 + 40 + (hasValue ? 14 + 184 + 14 + 62 : 0)
    + (resLines.length ? 14 + resLines.length * (hasValue ? 50 : 88) : 0) + (db ? 40 : 0);
  const panelTop = (height - panelH * k) / 2;
  const targetY = panelTop + (hasValue ? 30 + 14 + 40 + 14 + 92 : 30 + 14 + 40 + 14 + 44) * k;
  const hot = dots[0];
  const kx = hot ? PX + PW / 2 + (hot.x * u - PW / 2) * sc : 0;
  const ky = hot ? PY + PH / 2 + (hot.y * u - PH / 2) * sc : 0;
  const bx0 = PX - 34 * k, by0 = PY - 34 * k, bx1 = PX + PW + 34 * k, by1 = PY + PH + 34 * k, BL = 54 * k;
  const brackets = Math.max(0, ramp(frame, 2, 16, inOut) - q);
  const dotsN = 1 + (Math.floor(frame / 6) % 3);
  const monoCaption: React.CSSProperties = { fontFamily: MONO, fontWeight: 700, fontSize: 18 * k, letterSpacing: "0.32em", color: CYAN,
    whiteSpace: "pre" };
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 36% 48%, #10253b 0%, #07121f 52%, #020508 100%)" }} />
      <AbsoluteFill style={{ opacity: ramp(frame, 0, 12) * 0.9,
        backgroundImage: `linear-gradient(${tint(CYAN, 0.07)} 1px, rgba(0,0,0,0) 1px), linear-gradient(90deg, ${tint(CYAN, 0.07)} 1px, rgba(0,0,0,0) 1px)`,
        backgroundSize: `${60 * k}px ${60 * k}px`, backgroundPosition: `${(-frame * 0.3 * k).toFixed(1)}px ${(-frame * 0.15 * k).toFixed(1)}px` }} />
      <AbsoluteFill style={{ background: `radial-gradient(circle ${460 * k}px at ${PX + PW / 2}px ${height / 2}px, ${tint(CYAN, 0.1)} 0%, rgba(0,0,0,0) 70%)` }} />
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${320 * k}px rgba(0,0,0,.8)` }} />
      <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0 }}>
        {[[bx0, by0, 1, 1], [bx1, by0, -1, 1], [bx0, by1, 1, -1], [bx1, by1, -1, -1]].map(([x, y, dx, dy], i) => (
          <path key={i} d={`M${x + dx * BL} ${y} L${x} ${y} L${x} ${y + dy * BL}`} fill="none" stroke={CYAN} strokeWidth={3 * k}
            pathLength={1} strokeDasharray={1} strokeDashoffset={1 - brackets} />
        ))}
      </svg>
      <div style={{ position: "absolute", left: PX, top: PY, width: PW, height: PH, opacity: ramp(frame, 0, 10) * (1 - q),
        transform: `scale(${sc})` }}>
        <svg width={PW} height={PH} viewBox="0 0 400 500" style={{ overflow: "visible", display: "block" }}>
          <defs>
            <clipPath id={`${id}t`}><path d={TIP} /></clipPath>
            <radialGradient id={`${id}r`} cx="50%" cy="47%" r="54%">
              <stop offset="0.58" stopColor="#fff" stopOpacity={1} />
              <stop offset="1" stopColor="#fff" stopOpacity={0} />
            </radialGradient>
            <mask id={`${id}m`}><rect x={0} y={0} width={400} height={500} fill={`url(#${id}r)`} /></mask>
            <clipPath id={`${id}s`}><rect x={0} y={0} width={400} height={Math.max(0.01, scanY)} /></clipPath>
            <linearGradient id={`${id}g`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor={CYAN} stopOpacity={0} />
              <stop offset="1" stopColor={CYAN} stopOpacity={0.32} />
            </linearGradient>
          </defs>
          <path d={TIP} fill={tint(CYAN, 0.035)} stroke={tint(CYAN, 0.2)} strokeWidth={1.5} />
          <g clipPath={`url(#${id}t)`} mask={`url(#${id}m)`}>
            {ridges.map((r, i) => (
              <path key={i} d={r.d} fill="none" stroke="rgba(170,205,230,.22)" strokeWidth={4.6} strokeLinecap="round"
                strokeDasharray={r.dash} strokeDashoffset={r.off} />
            ))}
            <g clipPath={`url(#${id}s)`} opacity={frame >= done ? 0.82 + 0.18 * pulse : 1}>
              {ridges.map((r, i) => (
                <path key={i} d={r.d} fill="none" stroke="#a8e6ff" strokeWidth={4.6} strokeLinecap="round"
                  strokeDasharray={r.dash} strokeDashoffset={r.off} />
              ))}
            </g>
          </g>
          {scanning ? (
            <g>
              <rect x={0} y={scanY - 70} width={400} height={70} fill={`url(#${id}g)`} />
              <rect x={-16} y={scanY - 1.5} width={432} height={3} fill={CYAN} />
            </g>
          ) : null}
          {dots.map((p, i) => {
            const at = scan0 + (p.y / 500) * (scan1 - scan0) + 2;
            const pp = ramp(frame, at, 10, backOut);
            return (
              <g key={i} opacity={Math.min(1, pp)} transform={`translate(${p.x.toFixed(1)} ${p.y.toFixed(1)}) scale(${pp.toFixed(3)})`}>
                <rect x={-7} y={-7} width={14} height={14} fill="none" stroke={i === 0 ? accent : CYAN} strokeWidth={2.4} transform="rotate(45)" />
                {i === 0 ? <circle r={17 + 9 * pulse} fill="none" stroke={accent} strokeWidth={2} opacity={0.75 - 0.45 * pulse} /> : null}
              </g>
            );
          })}
        </svg>
      </div>
      <div style={{ position: "absolute", left: PX, width: PW, top: by1 + 18 * k, height: 30 * k }}>
        <div style={{ position: "absolute", left: 0, right: 0, top: 0, display: "flex", justifyContent: "center" }}>
          <Rise at={scan0} out={done}><span style={monoCaption}>{`SCANNING${".".repeat(dotsN)}${" ".repeat(3 - dotsN)}`}</span></Rise>
        </div>
        <div style={{ position: "absolute", left: 0, right: 0, top: 0, display: "flex", justifyContent: "center" }}>
          <Rise at={done + 2}><span style={monoCaption}>SCAN COMPLETE</span></Rise>
        </div>
      </div>
      {hot ? (
        <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0, opacity: 1 - q }}>
          <path d={`M${kx.toFixed(1)} ${ky.toFixed(1)} L${(PX + PW + 56 * k).toFixed(1)} ${ky.toFixed(1)} ` +
            `L${(975 * k).toFixed(1)} ${targetY.toFixed(1)} L${(1000 * k).toFixed(1)} ${targetY.toFixed(1)}`}
            fill="none" stroke={accent} strokeWidth={2.5 * k} strokeLinejoin="round" pathLength={1} strokeDasharray={1}
            strokeDashoffset={1 - lead} />
          <circle cx={1000 * k} cy={targetY} r={5 * k} fill={accent} opacity={lead > 0.97 ? 1 : 0} />
        </svg>
      ) : null}
      <div style={{ position: "absolute", left: 1010 * k, top: panelTop, width: 800 * k, display: "flex", flexDirection: "column",
        gap: 14 * k }}>
        <Letters text={label} at={T(0.15)} step={0.5} style={{ fontFamily: MONO, fontWeight: 700, fontSize: 22 * k, letterSpacing: "0.22em",
          color: CYAN, lineHeight: 1.3 }} />
        <Rise at={T(0.25)}><span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 32 * k, letterSpacing: "0.2em",
          color: "rgba(255,255,255,.72)", whiteSpace: "nowrap" }}>{hasValue ? "MATCH CONFIDENCE" : "PRINT ANALYSIS"}</span></Rise>
        {hasValue ? (
          <Rise at={numAt - 4} frames={12}>
            <Odometer value={value} at={numAt} frames={numFrames} size={180 * k} color="#fff" suffix={suffix} suffixColor={accent}
              suffixScale={0.5} />
          </Rise>
        ) : null}
        {hasValue ? (
          <Rise at={numAt} frames={12}>
            <svg width={SEG * 24 * k - 5 * k} height={34 * k} style={{ display: "block" }}>
              {Array.from({ length: SEG }, (_, i) => (
                <rect key={i} x={i * 24 * k} y={0} width={19 * k} height={34 * k} rx={2 * k}
                  fill={i < lit ? (filling && i === lit - 1 ? "#ffffff" : accent) : "rgba(255,255,255,.1)"} />
              ))}
            </svg>
            <div style={{ display: "flex", justifyContent: "space-between", width: SEG * 24 * k - 5 * k, marginTop: 8 * k, fontFamily: MONO,
              fontWeight: 500, fontSize: 16 * k, letterSpacing: "0.1em", color: "rgba(255,255,255,.45)" }}>
              <span>0</span><span>{pct ? "100%" : ""}</span>
            </div>
          </Rise>
        ) : null}
        {resLines.map((ln, i) => (hasValue ? (
          <Rise key={i} at={T(1.95) + i * 4}>
            <div style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 42 * k, lineHeight: 1.12, color: "#fff" }}>{ln}</div>
          </Rise>
        ) : (
          <Letters key={i} text={ln} at={T(1.8) + i * 5} step={0.7} style={{ fontFamily: DISPLAY, fontSize: 84 * k, lineHeight: 1.02,
            color: "#fff", letterSpacing: "0.03em" }} />
        )))}
        {db ? (
          <Rise at={T(2.1)}><span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 20 * k, letterSpacing: "0.18em",
            color: "rgba(255,255,255,.55)", whiteSpace: "nowrap" }}>{db}</span></Rise>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 5. police log
/**
 * items = log entries (label the time, text the event), text = the log's
 * title, subtitle = the unit or date. The entries type in on a console.
 */
const DispatchLog: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: dur, fps } = useVideoConfig();
  const k = useK();
  const q = useExit(14);
  const pace = usePace(1.6);
  const entries = itemsOf(overlay, 6).map((it) => {
    const a = str(it.label);
    const b = str(it.text);
    return b ? { time: clip(a, 11), ev: clip(b, 88) } : { time: "", ev: clip(a, 88) };
  });
  if (!entries.length) return null;
  const title = clip(cap(overlay.text), 38);
  const sub = clip(cap(overlay.subtitle), 36);
  const T = (s: number) => Math.round(s * fps * pace);
  const start = T(0.75);
  const total = entries.reduce((sum, e) => sum + e.ev.length, 0);
  const budget = Math.max(24, dur * 0.72 - start - entries.length * 9);
  const cps = Math.max(1.4, Math.min(6, total / budget));
  const sched: { at: number; typeAt: number }[] = [];
  let t = start;
  entries.forEach((e) => {
    sched.push({ at: t, typeAt: t + 5 });
    t = t + 5 + Math.ceil(e.ev.length / cps) + 4;
  });
  const n = entries.length;
  const active = sched.reduce((a, s, i) => (frame >= s.at ? i : a), -1);
  const rowH = (n <= 4 ? 120 : n === 5 ? 104 : 92) * k;
  const top0 = (title ? 350 : 270) * k;
  const railX = 182 * k;
  let railLen = 0;
  let band = top0;
  for (let i = 1; i < n; i++) {
    railLen += rowH * ramp(frame, sched[i].at - 5, 9, inOut);
    band += rowH * ramp(frame, sched[i].at - 3, 8, inOut);
  }
  const blink = Math.floor(frame / Math.max(1, Math.round(fps * 0.27))) % 2 === 0;
  const slow = Math.floor(frame / Math.max(1, fps)) % 2 === 0;
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 45% 42%, #0c1824 0%, #060b11 55%, #020406 100%)" }} />
      <AbsoluteFill style={{ background: `radial-gradient(ellipse 60% 50% at 30% 45%, ${tint(CYAN, 0.07)} 0%, rgba(0,0,0,0) 70%)` }} />
      <AbsoluteFill style={{ backgroundImage:
        "repeating-linear-gradient(0deg, rgba(255,255,255,.025) 0px, rgba(255,255,255,.025) 1px, rgba(255,255,255,0) 1px, rgba(255,255,255,0) 4px)" }} />
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${280 * k}px rgba(0,0,0,.85)` }} />
      <div style={{ position: "absolute", left: 60 * k, top: 60 * k, right: 60 * k, bottom: 60 * k, borderRadius: 28 * k,
        border: `${1.5 * k}px solid ${tint(CYAN, 0.16)}`, opacity: ramp(frame, 0, 12) * (1 - q),
        transform: `scale(${1.02 - 0.02 * ramp(frame, 0, 16)})` }} />
      <div style={{ position: "absolute", left: 150 * k, right: 150 * k, top: 110 * k, display: "flex", justifyContent: "space-between",
        alignItems: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14 * k }}>
          <div style={{ width: 12 * k, height: 12 * k, borderRadius: "50%", background: CYAN, boxShadow: `0 0 ${10 * k}px ${CYAN}`,
            opacity: slow ? 1 : 0.45, transform: `scale(${ramp(frame, 2, 8, backOut) * (1 - q)})` }} />
          <Letters text="INCIDENT LOG" at={3} step={0.6} style={{ fontFamily: MONO, fontWeight: 700, fontSize: 22 * k,
            letterSpacing: "0.3em", color: CYAN }} />
        </div>
        {sub ? <Letters text={sub} at={6} step={0.4} style={{ fontFamily: MONO, fontWeight: 500, fontSize: 21 * k, letterSpacing: "0.16em",
          color: "rgba(255,255,255,.55)" }} /> : null}
      </div>
      {title ? (
        <div style={{ position: "absolute", left: 150 * k, top: 160 * k }}>
          <Letters text={title} at={T(0.2)} step={0.7} style={{ fontFamily: DISPLAY, fontSize: 76 * k, color: "#fff",
            letterSpacing: "0.03em", lineHeight: 1 }} />
        </div>
      ) : null}
      <div style={{ position: "absolute", left: 150 * k, right: 150 * k, top: (title ? 268 : 160) * k }}>
        <Rule at={T(0.3)} color={tint(CYAN, 0.35)} h={1.5} />
      </div>
      <div style={{ position: "absolute", left: 150 * k, right: 150 * k, top: band, height: rowH - 10 * k,
        borderLeft: `${3 * k}px solid ${CYAN}`, opacity: ramp(frame, start, 8) * (1 - q),
        background: `linear-gradient(90deg, ${tint(CYAN, 0.13)} 0%, ${tint(CYAN, 0.03)} 70%, rgba(0,0,0,0) 100%)` }} />
      <div style={{ position: "absolute", left: railX - 1.5 * k, top: top0 + 30 * k, width: 3 * k, height: railLen * (1 - q),
        background: `linear-gradient(180deg, ${tint(CYAN, 0.6)}, ${tint(CYAN, 0.25)})` }} />
      {entries.map((e, i) => {
        const s = sched[i];
        const shown = Math.max(0, Math.min(e.ev.length, Math.floor((frame - s.typeAt) * cps)));
        const typing = frame >= s.typeAt && shown < e.ev.length;
        const cursor = typing || (i === active && shown >= e.ev.length && blink);
        const y = top0 + i * rowH;
        const dimmed = active > i ? 0.55 : 1;
        const node = ramp(frame, s.at, 10, backOut);
        const outAt = dur - 16 + Math.min(i, 5) * 0.6;
        return (
          <React.Fragment key={i}>
            <div style={{ position: "absolute", left: railX - 10 * k, top: y + 20 * k, width: 20 * k, height: 20 * k, borderRadius: "50%",
              boxSizing: "border-box", background: i === active ? accent : "#0b1016",
              border: `${3 * k}px solid ${i <= active ? accent : tint(CYAN, 0.35)}`, transform: `scale(${node * (1 - q)})` }} />
            <div style={{ position: "absolute", left: 220 * k, top: y + 10 * k, width: 200 * k, opacity: dimmed }}>
              <Rise at={s.at} frames={12} out={outAt}>
                <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 32 * k, color: accent, whiteSpace: "nowrap" }}>{e.time}</span>
              </Rise>
            </div>
            <div style={{ position: "absolute", left: 440 * k, right: 150 * k, top: y + 10 * k, opacity: dimmed }}>
              <Rise at={s.at} frames={12} out={outAt}>
                <div style={{ fontFamily: MONO, fontWeight: 500, fontSize: 29 * k, lineHeight: 1.32, color: "#e6edf3", minHeight: 38 * k }}>
                  {e.ev.slice(0, shown)}
                  <span style={{ display: "inline-block", width: "0.55em", height: "1em", verticalAlign: "-0.14em", marginLeft: 3 * k,
                    background: CYAN, opacity: cursor ? 0.9 : 0 }} />
                </div>
              </Rise>
            </div>
          </React.Fragment>
        );
      })}
    </AbsoluteFill>
  );
};

// ================================================================== 6. unknown silhouette
/** A frontal head-and-shoulders bust (viewBox 400 x 600), ears, neck and shoulders. */
const BUST = "M200 40 C 250 40, 284 76, 286 130 C 292 128, 298 136, 297 152 C 296 170, 291 186, 283 190 " +
  "C 280 226, 270 262, 252 286 C 250 290, 250 294, 250 300 L 254 334 C 270 348, 300 362, 330 374 " +
  "C 366 390, 388 424, 394 480 L 404 600 L -4 600 L 6 480 C 12 424, 34 390, 70 374 C 100 362, 130 348, 146 334 " +
  "L 150 300 C 150 294, 150 290, 148 286 C 130 262, 120 226, 117 190 C 109 186, 104 170, 103 152 " +
  "C 102 136, 108 128, 114 130 C 116 76, 150 40, 200 40 Z";
const QMARK = "M170 140 C 170 112, 185 98, 202 98 C 221 98, 234 111, 234 130 C 234 150, 219 158, 210 166 C 202 173, 200 180, 200 196";

/**
 * label = the headline word (default UNIDENTIFIED), text = who they are,
 * subtitle = a small line above (last seen...), items = the known details.
 */
const Unidentified: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, height } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const q = useExit(14);
  const pace = usePace(3.3);
  const big = clip(cap(overlay.label) || "UNIDENTIFIED", 16);
  const desc = str(overlay.text);
  const note = clip(cap(overlay.subtitle), 44);
  const facts = itemsOf(overlay, 4).map((f) => {
    const v = num(f.value);
    const val = str(f.text) || (Number.isFinite(v) ? `${str(v)}${f.suffix ? ` ${str(f.suffix)}` : ""}` : "");
    return val ? { key: clip(cap(f.label), 16), val: clip(val, 26) } : { key: "", val: clip(str(f.label), 26) };
  });
  const T = (s: number) => Math.round(s * fps * pace);
  const inch = (n: number) => (262 + (72 - n) * 40) * k;
  const rise = ramp(frame, T(0.1), T(0.8));
  const flashAt = T(0.45);
  const flash = interpolate(frame, [flashAt, flashAt + 1, flashAt + 10], [0, 0.42, 0], clamp);
  const rim = ramp(frame, T(0.5), T(0.9), inOut);
  const qm = ramp(frame, T(0.95), T(0.6), inOut);
  const dot = ramp(frame, T(1.45), 10, backOut);
  const SW = 620 * k, SH = SW * 1.5;
  const SX = 555 * k - SW / 2, SY = inch(72) + 6 * k - 40 * (SW / 400);
  const descLines = lines(desc, 32).slice(0, 3);
  const id = `cfu${Math.round(num(overlay.startFrame) || 0)}`;
  const glow = 0.78 + 0.22 * Math.sin(frame / (fps * 0.45));
  const marks: number[] = [];
  for (let m = 54; m <= 80; m += 2) marks.push(m);
  return (
    <AbsoluteFill style={{ overflow: "hidden", background: "linear-gradient(180deg, #2b2e33 0%, #1a1c20 100%)" }}>
      <AbsoluteFill style={{ background: `radial-gradient(circle ${520 * k}px at ${555 * k}px ${400 * k}px, rgba(255,255,255,.13) 0%, rgba(255,255,255,0) 70%)` }} />
      {marks.map((m, i) => {
        const y = inch(m);
        if (y < 40 * k || y > height - 30 * k) return null;
        const major = m % 6 === 0;
        return (
          <React.Fragment key={m}>
            <div style={{ position: "absolute", left: 120 * k, width: 870 * k, top: y, height: (major ? 3 : 1.5) * k,
              background: major ? "rgba(255,255,255,.5)" : "rgba(255,255,255,.2)",
              transform: `scaleX(${ramp(frame, i * 1.2, 14) * (1 - q)})`, transformOrigin: "0 50%" }} />
            {major ? (
              <div style={{ position: "absolute", left: 130 * k, top: y - 40 * k }}>
                <Rise at={4 + i}><span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 30 * k, color: "rgba(255,255,255,.72)",
                  letterSpacing: "0.04em" }}>{`${Math.floor(m / 12)}'${m % 12 ? `${m % 12}"` : ""}`}</span></Rise>
              </div>
            ) : null}
          </React.Fragment>
        );
      })}
      <div style={{ position: "absolute", left: SX, top: SY, width: SW, height: SH, opacity: ramp(frame, T(0.1), 8),
        transform: `translateY(${((1 - rise) * 90 + q * 70) * k}px) scale(${hold})`, transformOrigin: "50% 30%" }}>
        <svg width={SW} height={SH} viewBox="0 0 400 600" style={{ overflow: "visible", display: "block" }}>
          <defs>
            <linearGradient id={`${id}f`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#16181c" />
              <stop offset="1" stopColor="#060708" />
            </linearGradient>
            <radialGradient id={`${id}s`} cx="50%" cy="28%" r="45%">
              <stop offset="0" stopColor="#2c2f35" stopOpacity={0.9} />
              <stop offset="1" stopColor="#2c2f35" stopOpacity={0} />
            </radialGradient>
          </defs>
          <path d={BUST} fill={`url(#${id}f)`} />
          <path d={BUST} fill={`url(#${id}s)`} opacity={0.6} />
          <path d={BUST} fill="none" stroke={accent} strokeOpacity={0.14 * rim} strokeWidth={12} strokeLinejoin="round" />
          <path d={BUST} fill="none" stroke={accent} strokeOpacity={0.85} strokeWidth={2.6} strokeLinejoin="round"
            pathLength={1} strokeDasharray={1} strokeDashoffset={1 - rim} />
          <path d={QMARK} fill="none" stroke={accent} strokeWidth={16} strokeLinecap="round" strokeLinejoin="round"
            pathLength={1} strokeDasharray={1} strokeDashoffset={1 - qm} opacity={glow * (1 - q)} />
          <circle cx={200} cy={226} r={10 * dot} fill={accent} opacity={glow * (1 - q)} />
        </svg>
      </div>
      <AbsoluteFill style={{ background: "#fff", opacity: flash }} />
      <div style={{ position: "absolute", left: 1080 * k, top: 0, bottom: 0, width: 760 * k, display: "flex", flexDirection: "column",
        justifyContent: "center", gap: 12 * k }}>
        {note ? <Letters text={note} at={T(0.55)} step={0.4} style={{ fontFamily: MONO, fontWeight: 700, fontSize: 20 * k,
          letterSpacing: "0.22em", color: "rgba(255,255,255,.6)" }} /> : null}
        <Letters text={big} at={T(0.6)} step={1.1} style={{ fontFamily: DISPLAY, fontSize: 86 * k, lineHeight: 1, letterSpacing: "0.06em",
          color: "#fff" }} />
        <div style={{ width: ramp(frame, T(0.7), 16) * (1 - q) * 130 * k, height: 6 * k, background: accent, margin: `${4 * k}px 0 ${10 * k}px` }} />
        {descLines.map((ln, i) => (
          <Rise key={i} at={T(0.85) + i * 4}>
            <div style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 40 * k, lineHeight: 1.12, color: "rgba(255,255,255,.88)" }}>{ln}</div>
          </Rise>
        ))}
        {facts.length ? <div style={{ height: 14 * k }} /> : null}
        {facts.map((f, i) => (
          <Rise key={`f${i}`} at={T(1.1) + i * 5}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 14 * k, width: 680 * k }}>
              {f.key ? <span style={{ fontFamily: MONO, fontWeight: 700, fontSize: 20 * k, letterSpacing: "0.2em",
                color: "rgba(255,255,255,.55)", whiteSpace: "nowrap" }}>{f.key}</span> : null}
              {f.key ? <span style={{ flex: 1, borderBottom: `${2 * k}px dotted rgba(255,255,255,.25)`,
                transform: `translateY(${-6 * k}px)` }} /> : null}
              <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 34 * k, color: "#fff", whiteSpace: "nowrap" }}>{f.val}</span>
            </div>
          </Rise>
        ))}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 7. evidence markers on a photo
/** A yellow tent marker (front face, side, highlight), its number printed on. */
const Tent: React.FC<{ n: number; w: number; accent: string; uid: string }> = ({ n, w, accent, uid }) => (
  <svg width={w} height={w * 1.2} viewBox="0 0 100 120" style={{ display: "block", overflow: "visible" }}>
    <defs>
      <linearGradient id={`${uid}g`} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="#fff" stopOpacity={0.4} />
        <stop offset="0.45" stopColor="#fff" stopOpacity={0.06} />
        <stop offset="1" stopColor="#000" stopOpacity={0.22} />
      </linearGradient>
    </defs>
    <path d="M94 116 L82 16 L90 20 L100 110 Z" fill={accent} />
    <path d="M94 116 L82 16 L90 20 L100 110 Z" fill="#000" opacity={0.38} />
    <path d="M6 116 L18 16 Q19 8 27 8 H73 Q81 8 82 16 L94 116 Z" fill={accent} />
    <path d="M6 116 L18 16 Q19 8 27 8 H73 Q81 8 82 16 L94 116 Z" fill={`url(#${uid}g)`} />
    <rect x={22} y={12} width={56} height={3.5} rx={1.75} fill="#fff" opacity={0.5} />
    <text x={50} y={96} textAnchor="middle" fontFamily={DISPLAY} fontSize={n > 9 ? 56 : 70} fill={INK}>{n}</text>
    <path d="M6 116 H94" stroke="#000" strokeOpacity={0.35} strokeWidth={3} />
  </svg>
);

/**
 * media[0] = the scene photo, items = what each marker points out (label),
 * text = the legend title, subtitle = the place. No items: three markers.
 */
const MarkerPhoto: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: dur, fps, width, height } = useVideoConfig();
  const k = useK();
  const q = useExit(14);
  const pace = usePace(3.0);
  const seed = seedOf(overlay);
  const pic = stills(overlay, 1)[0] || "";
  const items = itemsOf(overlay, 6);
  const title = str(overlay.text);
  const place = clip(cap(overlay.subtitle), 26);
  if (!pic) return null;
  const T = (s: number) => Math.round(s * fps * pace);
  const panel = items.length > 0 || title.length > 0;
  const n = items.length || 3;
  const slots: [number, number][] = panel
    ? [[0.56, 0.74], [0.74, 0.6], [0.87, 0.81], [0.48, 0.54], [0.66, 0.88], [0.83, 0.47]]
    : [[0.32, 0.74], [0.54, 0.62], [0.73, 0.79], [0.42, 0.52], [0.86, 0.6], [0.62, 0.88]];
  const anchor = overlay.anchor;
  const pts = Array.from({ length: n }, (_, i) => {
    const [sx, sy] = slots[i % slots.length];
    let x = sx + (rnd(seed + i * 3.7) - 0.5) * 0.05;
    let y = sy + (rnd(seed + i * 5.9) - 0.5) * 0.05;
    if (i === 0 && anchor && Number.isFinite(anchor.x) && Number.isFinite(anchor.y)) {
      x = Math.max(0.06, Math.min(0.94, anchor.x));
      y = Math.max(0.3, Math.min(0.92, anchor.y));
    }
    const sc = Math.max(0.66, Math.min(1.08, 0.72 + 0.62 * (y - 0.45)));
    return { x, y, sc, at: T(0.5) + i * T(0.32) };
  });
  const order = pts.map((p, i) => ({ p, i })).sort((a, b) => a.p.y - b.p.y);
  const push = interpolate(frame, [0, Math.max(1, dur)], [1.04, 1.11], clamp);
  const flash = interpolate(frame, [T(0.5) + 6, T(0.5) + 7, T(0.5) + 16], [0, 0.22, 0], clamp);
  const uid = `cfm${Math.round(num(overlay.startFrame) || 0)}`;
  const titleLines = lines(title, 24).slice(0, 2);
  const panelIn = ramp(frame, T(0.15), 16);
  return (
    <AbsoluteFill style={{ background: "#050506", overflow: "hidden" }}>
      <SafeImg src={pic} style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "100%", objectFit: "cover",
        transform: `scale(${push})`, transformOrigin: "62% 68%", filter: "saturate(.78) contrast(1.08) brightness(.9)" }} />
      <AbsoluteFill style={{ background: panel
        ? "linear-gradient(90deg, rgba(0,0,0,.55) 0%, rgba(0,0,0,.18) 36%, rgba(0,0,0,0) 55%), linear-gradient(0deg, rgba(0,0,0,.4) 0%, rgba(0,0,0,0) 38%)"
        : "linear-gradient(0deg, rgba(0,0,0,.4) 0%, rgba(0,0,0,0) 38%)" }} />
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${280 * k}px rgba(0,0,0,.72)` }} />
      {order.map(({ p, i }) => {
        const sp = frame < p.at ? 0 : spring({ frame: frame - p.at, fps, config: { damping: 11, stiffness: 190, mass: 0.75 } });
        const lift = ramp(frame, dur - 14 + Math.min(i, 4) * 0.5, 10, expoIn);
        const w = 96 * k * p.sc;
        const h = w * 1.2;
        const gx = p.x * width, gy = p.y * height;
        const fall = (1 - sp) * -360 * k * p.sc - lift * 460 * k;
        const landed = Math.max(0, Math.min(1, sp));
        return (
          <React.Fragment key={i}>
            <div style={{ position: "absolute", left: gx - w * 0.75, top: gy - w * 0.16, width: w * 1.5, height: w * 0.34, borderRadius: "50%",
              background: "radial-gradient(ellipse at 50% 50%, rgba(0,0,0,.6) 0%, rgba(0,0,0,.25) 45%, rgba(0,0,0,0) 72%)",
              opacity: landed * (1 - lift), transform: `scale(${0.45 + 0.55 * landed})` }} />
            <div style={{ position: "absolute", left: gx - w / 2, top: gy - h, width: w, height: h, opacity: frame >= p.at ? 1 - lift * 0.3 : 0,
              transform: `translateY(${fall.toFixed(2)}px) rotate(${((1 - sp) * (i % 2 ? 12 : -12) + lift * 10).toFixed(2)}deg)`,
              transformOrigin: "50% 100%" }}>
              <Tent n={i + 1} w={w} accent={accent} uid={`${uid}-${i}`} />
            </div>
          </React.Fragment>
        );
      })}
      <AbsoluteFill style={{ background: "#fff", opacity: flash }} />
      {panel ? (
        <div style={{ position: "absolute", left: 90 * k, bottom: 110 * k, width: 560 * k, boxSizing: "border-box",
          padding: `${26 * k}px ${30 * k}px ${22 * k}px`, borderRadius: 14 * k, background: "rgba(10,12,15,.72)",
          backdropFilter: "blur(12px)", WebkitBackdropFilter: "blur(12px)", border: `${1 * k}px solid rgba(255,255,255,.14)`,
          boxShadow: `0 ${24 * k}px ${60 * k}px rgba(0,0,0,.45)`, opacity: ramp(frame, T(0.15), 10) * (1 - q),
          transform: `translateX(${((1 - panelIn) * -40 - q * 30) * k}px)` }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 * k }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 * k }}>
              <div style={{ width: 12 * k, height: 12 * k, background: accent }} />
              <Letters text="EVIDENCE" at={T(0.2)} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 24 * k, letterSpacing: "0.3em",
                color: accent }} />
            </div>
            {place ? <Letters text={place} at={T(0.25)} step={0.4} style={{ fontFamily: MONO, fontWeight: 500, fontSize: 18 * k,
              letterSpacing: "0.14em", color: "rgba(255,255,255,.55)" }} /> : null}
          </div>
          {titleLines.map((ln, i) => (
            <Rise key={`t${i}`} at={T(0.3) + i * 4} style={{ marginTop: i ? 0 : 12 * k }}>
              <div style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 38 * k, lineHeight: 1.1, color: "#fff" }}>{ln}</div>
            </Rise>
          ))}
          {items.length ? <div style={{ margin: `${16 * k}px 0 ${6 * k}px` }}><Rule at={T(0.4)} color="rgba(255,255,255,.2)" h={1.5} /></div> : null}
          {items.map((it, i) => (
            <Rise key={`r${i}`} at={pts[i].at + 8} style={{ marginTop: 10 * k }}>
              <div style={{ display: "flex", alignItems: "center", gap: 16 * k }}>
                <div style={{ width: 40 * k, height: 40 * k, borderRadius: 4 * k, background: accent, display: "flex", alignItems: "center",
                  justifyContent: "center", fontFamily: DISPLAY, fontSize: 30 * k, lineHeight: 1, color: INK, paddingTop: 3 * k,
                  boxSizing: "border-box", flexShrink: 0 }}>{i + 1}</div>
                <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 31 * k, color: "#fff", whiteSpace: "nowrap" }}>
                  {clip(str(it.label) || str(it.text), 28)}</span>
              </div>
            </Rise>
          ))}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== 8. phone records
const HANDSET = "M5 3.5 h3.2 l1.9 4.6 -2.3 1.6 a 10.5 10.5 0 0 0 5.2 5.2 l1.6 -2.3 4.6 1.9 v3.2 a 2 2 0 0 1 -2 2 A 16 16 0 0 1 3 5.5 a 2 2 0 0 1 2 -2 Z";

/** A call's duration from its value (seconds; "min" / "h" units convert), as m:ss. */
const fmtDur = (it: Item, unit: string): string => {
  let v = num(it.value);
  if (!Number.isFinite(v) || v <= 0) return "";
  const u = (str(it.suffix) || unit).toLowerCase();
  if (/^(m|min|mins|minutes?)$/.test(u)) v *= 60;
  if (/^(h|hr|hrs|hours?)$/.test(u)) v *= 3600;
  const s = Math.round(Math.min(v, 359999));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  return h ? `${h}:${pad2(m)}:${pad2(x)}` : `${m}:${pad2(x)}`;
};

/** The flagged call: the one named by highlight, else the longest, else the last. */
const pickCall = (calls: Item[], h: string): number => {
  const needle = h.toLowerCase();
  if (needle) {
    const i = calls.findIndex((c) => `${str(c.label)} ${str(c.text)}`.toLowerCase().includes(needle));
    if (i >= 0) return i;
  }
  let best = -1;
  let bv = 0;
  calls.forEach((c, i) => {
    const v = num(c.value);
    if (Number.isFinite(v) && v > bv) {
      bv = v;
      best = i;
    }
  });
  return best >= 0 ? best : calls.length - 1;
};

/**
 * items = calls (label the time, text the caller, value the duration in
 * seconds), highlight = the call to flag, text = what it was, subtitle =
 * whose phone. The flagged call's time and duration roll out beside it.
 */
const PhoneLog: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const q = useExit(14);
  const pace = usePace(3.4);
  const calls = itemsOf(overlay, 6);
  if (!calls.length) return null;
  const T = (s: number) => Math.round(s * fps * pace);
  const unit = str(overlay.suffix);
  const n = calls.length;
  const hi = pickCall(calls, str(overlay.highlight));
  const main = calls[hi];
  const when = str(main.text) ? str(main.label) : "";
  const dur = fmtDur(main, unit);
  const tm = /^(.*\d)(\s*[A-Za-z.]+)?$/.exec(when);
  const tMain = tm ? tm[1] : "";
  const tSuf = tm && tm[2] ? tm[2].trim().toUpperCase() : "";
  const body = clip(str(overlay.text), 90);
  const bodyLines = lines(body, 30).slice(0, 3);
  const sub = clip(cap(overlay.subtitle), 40);
  const PW = 450 * k, PH = 900 * k, PX = 300 * k, PY = (height - PH) / 2;
  const land = ramp(frame, 0, T(0.8));
  const theta = -(12 + (1 - land) * 28 + q * 26);
  const P = 1900 * k;
  const y0 = 166 * k;
  const rowH = Math.min(118, 660 / n) * k;
  const rowAt = (i: number) => T(0.45) + i * T(0.12);
  const hiAt = rowAt(n - 1) + T(0.35);
  const hp = ramp(frame, hiAt, 14);
  const tx = ((1 - land) * -180 - q * 120) * k;
  const rad = (theta * Math.PI) / 180;
  const dx = (PW / 2 - 26 * k) * hold;
  const dy = (14 * k + y0 + (hi + 0.5) * rowH - PH / 2) * hold;
  const persp = P / (P + dx * Math.sin(rad));
  const sx = PX + PW / 2 + tx + dx * Math.cos(rad) * persp;
  const sy = PY + PH / 2 + dy * persp;
  const panelH = 28 + 16 + 150 + (dur ? 16 + 92 : 0) + (bodyLines.length ? 22 + bodyLines.length * 50 : 0) + (sub ? 16 + 28 : 0);
  const panelTop = (height - panelH * k) / 2;
  const numY = panelTop + (28 + 16 + 75) * k;
  const lead = ramp(frame, hiAt + 6, T(0.45), inOut);
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <SteelDesk glow={`radial-gradient(circle ${700 * k}px at ${PX + PW / 2}px 50%, ${tint(accent, 0.16)} 0%, rgba(0,0,0,0) 70%)`} />
      <div style={{ position: "absolute", left: PX, top: PY, width: PW, height: PH, opacity: ramp(frame, 0, 6) * (1 - q),
        transform: `translateX(${tx.toFixed(2)}px) perspective(${P}px) rotateY(${theta.toFixed(3)}deg) scale(${hold})` }}>
        <div style={{ position: "absolute", left: 0, top: 0, right: 0, bottom: 0, borderRadius: 60 * k,
          background: "linear-gradient(145deg, #2b2e34 0%, #121418 40%, #0a0b0d 100%)",
          boxShadow: `0 ${50 * k}px ${110 * k}px rgba(0,0,0,.6), inset 0 0 0 ${2 * k}px rgba(255,255,255,.1)` }} />
        <div style={{ position: "absolute", left: -4 * k, top: 190 * k, width: 5 * k, height: 70 * k, borderRadius: 3 * k, background: "#2b2e34" }} />
        <div style={{ position: "absolute", left: -4 * k, top: 280 * k, width: 5 * k, height: 70 * k, borderRadius: 3 * k, background: "#2b2e34" }} />
        <div style={{ position: "absolute", left: 14 * k, top: 14 * k, right: 14 * k, bottom: 14 * k, borderRadius: 48 * k, overflow: "hidden",
          background: "linear-gradient(180deg, #0f1115 0%, #08090b 100%)" }}>
          <div style={{ position: "absolute", left: "50%", top: 16 * k, width: 120 * k, height: 34 * k, marginLeft: -60 * k,
            borderRadius: 20 * k, background: "#000" }} />
          <div style={{ position: "absolute", right: 34 * k, top: 26 * k, display: "flex", alignItems: "flex-end", gap: 10 * k, opacity: 0.85 }}>
            <div style={{ display: "flex", alignItems: "flex-end", gap: 3 * k }}>
              {[8, 12, 16, 20].map((b) => <div key={b} style={{ width: 5 * k, height: b * k, borderRadius: 1.5 * k, background: "#fff" }} />)}
            </div>
            <div style={{ width: 38 * k, height: 18 * k, borderRadius: 5 * k, border: `${2 * k}px solid rgba(255,255,255,.8)`, padding: 2 * k,
              boxSizing: "border-box" }}>
              <div style={{ width: "72%", height: "100%", borderRadius: 2 * k, background: "#fff" }} />
            </div>
          </div>
          <div style={{ position: "absolute", left: 30 * k, top: 80 * k }}>
            <Rise at={T(0.3)}><span style={{ fontFamily: INTER, fontWeight: 800, fontSize: 42 * k, color: "#fff" }}>Recents</span></Rise>
          </div>
          <div style={{ position: "absolute", left: 30 * k, right: 30 * k, top: 146 * k }}>
            <Rule at={T(0.35)} color="rgba(255,255,255,.12)" h={1.5} />
          </div>
          {calls.map((c, i) => {
            const on = i === hi;
            const who = clip(str(c.text) || str(c.label), 22);
            const t = clip(str(c.text) ? str(c.label) : "", 10);
            const d = fmtDur(c, unit);
            return (
              <div key={i} style={{ position: "absolute", left: 10 * k, right: 10 * k, top: y0 + i * rowH, height: rowH }}>
                {on ? (
                  <div style={{ position: "absolute", left: 0, right: 0, top: 6 * k, bottom: 6 * k, borderRadius: 18 * k,
                    background: `linear-gradient(90deg, ${tint(accent, 0.3)} 0%, ${tint(accent, 0.1)} 100%)`,
                    border: `${1.5 * k}px solid ${tint(accent, 0.55)}`, boxSizing: "border-box",
                    clipPath: `inset(0 ${((1 - hp) * 100).toFixed(2)}% 0 0 round ${18 * k}px)` }} />
                ) : null}
                <Rise at={rowAt(i)} frames={14}>
                  <div style={{ display: "flex", alignItems: "center", gap: 16 * k, height: rowH, padding: `0 ${18 * k}px`, boxSizing: "border-box" }}>
                    <div style={{ width: 46 * k, height: 46 * k, borderRadius: "50%", flexShrink: 0, display: "flex", alignItems: "center",
                      justifyContent: "center", background: on && hp > 0.5 ? accent : "rgba(255,255,255,.08)" }}>
                      <svg width={24 * k} height={24 * k} viewBox="0 0 24 24" style={{ display: "block" }}>
                        <path d={HANDSET} fill={on && hp > 0.5 ? INK : "rgba(255,255,255,.7)"} />
                      </svg>
                    </div>
                    <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 4 * k }}>
                      <span style={{ fontFamily: INTER, fontWeight: 700, fontSize: 26 * k, color: "#fff", whiteSpace: "nowrap", overflow: "hidden",
                        textOverflow: "ellipsis" }}>{who}</span>
                      <span style={{ fontFamily: INTER, fontWeight: 500, fontSize: 19 * k, color: on ? accent : "rgba(255,255,255,.45)" }}>
                        {d || "—"}</span>
                    </div>
                    <span style={{ fontFamily: INTER, fontWeight: 500, fontSize: 20 * k, color: on ? "#fff" : "rgba(255,255,255,.5)",
                      whiteSpace: "nowrap" }}>{t}</span>
                  </div>
                </Rise>
                {i < n - 1 ? <div style={{ position: "absolute", left: 80 * k, right: 12 * k, bottom: 0, height: 1 * k,
                  background: "rgba(255,255,255,.08)" }} /> : null}
              </div>
            );
          })}
          <div style={{ position: "absolute", left: 0, top: 0, right: 0, bottom: 0,
            background: "linear-gradient(125deg, rgba(255,255,255,.07) 0%, rgba(255,255,255,0) 38%)" }} />
        </div>
      </div>
      <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0, opacity: 1 - q }}>
        <path d={`M${(sx + 10 * k).toFixed(1)} ${sy.toFixed(1)} L${(sx + 70 * k).toFixed(1)} ${sy.toFixed(1)} ` +
          `L${(960 * k).toFixed(1)} ${numY.toFixed(1)} L${(996 * k).toFixed(1)} ${numY.toFixed(1)}`}
          fill="none" stroke={accent} strokeWidth={2.5 * k} strokeLinejoin="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - lead} />
        <circle cx={sx + 10 * k} cy={sy} r={6 * k} fill={accent} opacity={lead > 0.01 ? 1 : 0} />
      </svg>
      <div style={{ position: "absolute", left: 1010 * k, top: panelTop, width: 800 * k, display: "flex", flexDirection: "column", gap: 16 * k }}>
        <Letters text={`CALL ${pad2(hi + 1)} OF ${pad2(n)}`} at={hiAt} step={0.5} style={{ fontFamily: MONO, fontWeight: 700, fontSize: 22 * k,
          letterSpacing: "0.26em", color: accent, lineHeight: 1.25 }} />
        <Rise at={hiAt + 2} frames={12}>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 18 * k, height: 150 * k }}>
            {tMain ? <DigitRoll text={tMain} at={hiAt + 2} frames={T(0.9)} size={150 * k} color="#fff" /> : (
              <span style={{ fontFamily: DISPLAY, fontSize: 120 * k, lineHeight: 1, color: "#fff", whiteSpace: "nowrap" }}>
                {clip(cap(when || main.text || main.label), 12)}</span>
            )}
            {tSuf ? <span style={{ fontFamily: DISPLAY, fontSize: 64 * k, lineHeight: 1.1, color: "rgba(255,255,255,.6)" }}>{tSuf}</span> : null}
          </div>
        </Rise>
        {dur ? (
          <Rise at={hiAt + 8} frames={12}>
            <div style={{ display: "flex", alignItems: "center", gap: 20 * k }}>
              <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 28 * k, letterSpacing: "0.2em", color: "rgba(255,255,255,.6)" }}>
                DURATION</span>
              <DigitRoll text={dur} at={hiAt + 8} frames={T(0.8)} size={88 * k} color={accent} />
            </div>
          </Rise>
        ) : null}
        {bodyLines.length ? <div style={{ height: 6 * k }} /> : null}
        {bodyLines.map((ln, i) => (
          <Rise key={i} at={hiAt + 12 + i * 4}>
            <div style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 42 * k, lineHeight: 1.12, color: "#fff" }}>{ln}</div>
          </Rise>
        ))}
        {sub ? (
          <Rise at={hiAt + 16 + bodyLines.length * 4}><span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 20 * k,
            letterSpacing: "0.18em", color: "rgba(255,255,255,.55)", whiteSpace: "nowrap" }}>{sub}</span></Rise>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 9. CCTV frame (tag)
const parseClock = (s: string): { secs: number; ampm: boolean; rest: string } | null => {
  const m = /(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\s*([AaPp])\.?\s?[Mm]\.?)?/.exec(s);
  if (!m) return null;
  let h = Number(m[1]);
  const mi = Number(m[2]);
  const se = m[3] ? Number(m[3]) : 0;
  const ap = m[4] ? m[4].toLowerCase() : "";
  if (h > 23 || mi > 59 || se > 59) return null;
  if (ap === "p" && h < 12) h += 12;
  if (ap === "a" && h === 12) h = 0;
  const rest = `${s.slice(0, m.index)} ${s.slice(m.index + m[0].length)}`.replace(/\s+/g, " ")
    .replace(/^[\s·,|-]+|[\s·,|-]+$/g, "").trim();
  return { secs: h * 3600 + mi * 60 + se, ampm: ap !== "", rest };
};

const clockText = (secs: number, ampm: boolean): string => {
  const s = ((Math.floor(secs) % 86400) + 86400) % 86400;
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  if (!ampm) return `${pad2(h)}:${pad2(m)}:${pad2(x)}`;
  return `${pad2(h % 12 === 0 ? 12 : h % 12)}:${pad2(m)}:${pad2(x)} ${h < 12 ? "AM" : "PM"}`;
};

/**
 * On the footage: label = the camera id, text = the location, subtitle = the
 * date and time ("03-03-2014 23:41:07"); the clock ticks from that time (or
 * counts from 00:00:00 when none is given).
 */
const Surveillance: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const k = useK();
  const q = useExit(12);
  const cam = clip(cap(overlay.label) || "CCTV", 16);
  const place = clip(cap(overlay.text), 34);
  const sub = str(overlay.subtitle);
  const clock = parseClock(sub);
  const date = clip((clock ? clock.rest : sub).toUpperCase(), 22);
  const now = clockText((clock ? clock.secs : 0) + frame / fps, clock ? clock.ampm : false);
  const I = 90 * k, L = 92 * k;
  const dp = Math.max(0, ramp(frame, 0, 14) - q);
  const jx = frame < 7 ? (rnd(frame * 7.1 + 3) - 0.5) * 18 * k : 0;
  const flick = frame < 7 ? [0, 1, 0.3, 1, 0.55, 1, 0.8][Math.max(0, Math.floor(frame))] : 1;
  const on = Math.floor(frame / Math.max(1, Math.round(fps * 0.5))) % 2 === 0;
  const cx = width / 2, cy = height / 2;
  const band = ((frame * 7 * k) % (height + 180 * k)) - 180 * k;
  const texture = ramp(frame, 0, 8) * (1 - q);
  const hud = (size: number): React.CSSProperties => ({ fontFamily: MONO, fontWeight: 700, fontSize: size * k, letterSpacing: "0.12em",
    color: "#fff", textShadow: "0 2px 6px rgba(0,0,0,.85)", lineHeight: 1.15 });
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: texture, background:
        "radial-gradient(ellipse 34% 30% at 0% 0%, rgba(0,0,0,.38), rgba(0,0,0,0)), radial-gradient(ellipse 34% 30% at 100% 0%, rgba(0,0,0,.38), rgba(0,0,0,0)), " +
        "radial-gradient(ellipse 34% 30% at 0% 100%, rgba(0,0,0,.42), rgba(0,0,0,0)), radial-gradient(ellipse 34% 30% at 100% 100%, rgba(0,0,0,.42), rgba(0,0,0,0))" }} />
      <AbsoluteFill style={{ opacity: 0.35 * texture, backgroundImage:
        "repeating-linear-gradient(0deg, rgba(0,0,0,.28) 0px, rgba(0,0,0,.28) 1px, rgba(0,0,0,0) 1px, rgba(0,0,0,0) 3px)" }} />
      <div style={{ position: "absolute", left: 0, right: 0, top: band, height: 180 * k, opacity: texture,
        background: "linear-gradient(180deg, rgba(255,255,255,0) 0%, rgba(255,255,255,.05) 50%, rgba(255,255,255,0) 100%)" }} />
      <AbsoluteFill style={{ transform: `translateX(${jx.toFixed(2)}px)`, opacity: flick }}>
        <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0 }}>
          {[[I, I, 1, 1], [width - I, I, -1, 1], [I, height - I, 1, -1], [width - I, height - I, -1, -1]].map(([x, y, sx, sy], i) => (
            <path key={i} d={`M${x + sx * L} ${y} L${x} ${y} L${x} ${y + sy * L}`} fill="none" stroke="#fff" strokeOpacity={0.9}
              strokeWidth={3.5 * k} pathLength={1} strokeDasharray={1} strokeDashoffset={1 - dp} />
          ))}
          <path d={`M${cx - 22 * k} ${cy} H${cx + 22 * k} M${cx} ${cy - 22 * k} V${cy + 22 * k}`} fill="none" stroke="#fff"
            strokeOpacity={0.4} strokeWidth={2 * k} opacity={dp} />
        </svg>
        <div style={{ position: "absolute", left: I + 36 * k, top: I + 30 * k, display: "flex", alignItems: "center", gap: 14 * k }}>
          <div style={{ width: 20 * k, height: 20 * k, borderRadius: "50%", background: RED, boxShadow: `0 0 ${14 * k}px ${RED}`,
            opacity: on ? 1 : 0.15, transform: `scale(${ramp(frame, 4, 8, backOut) * (1 - q)})` }} />
          <Letters text="REC" at={5} style={hud(30)} />
        </div>
        <div style={{ position: "absolute", right: I + 36 * k, top: I + 30 * k }}>
          <Letters text={cam} at={7} step={0.6} style={hud(30)} />
        </div>
        <div style={{ position: "absolute", left: I + 36 * k, bottom: I + 28 * k, display: "flex", flexDirection: "column", gap: 6 * k }}>
          {date ? <Letters text={date} at={9} step={0.5} style={hud(26)} /> : null}
          <Rise at={11} frames={12}><span style={{ ...hud(34), fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>{now}</span></Rise>
        </div>
        {place ? (
          <div style={{ position: "absolute", right: I + 36 * k, bottom: I + 28 * k }}>
            <Letters text={place} at={12} step={0.45} style={hud(26)} />
          </div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 10. transcript
type TLine = { text: string; who: string; entry: number; blank: boolean; mark: [number, number] | null };

/**
 * items = the exchange (label the speaker, text the words), text = the
 * transcript title, subtitle = when / which case, highlight = the phrase to
 * mark. No items: text becomes one entry spoken by label (a quote).
 */
const Transcript: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: dur, fps } = useVideoConfig();
  const k = useK();
  const q = useExit(14);
  const pace = usePace(1.8);
  let title = str(overlay.text);
  let list = itemsOf(overlay, 6).map((it) => {
    const said = str(it.text);
    return said ? { who: clip(cap(it.label), 18), said } : { who: "", said: str(it.label) };
  });
  if (!list.length && title) {
    list = [{ who: clip(cap(overlay.label), 18), said: title }];
    title = "";
  }
  if (!list.length) return null;
  const sub = clip(cap(overlay.subtitle), 48);
  const phrase = str(overlay.highlight).toLowerCase().replace(/\s+/g, " ");
  const CPL = 52;
  const tl: TLine[] = [];
  let marked = false;
  for (let ei = 0; ei < list.length; ei++) {
    const e = list[ei];
    const said = e.said.replace(/^["“”']+|["“”']+$/g, "");
    const all = lines(`${e.who ? `${e.who}: ` : ""}${said}`, CPL);
    const ls = all.slice(0, 4);
    if (all.length > 4) ls[3] = `${ls[3]} …`;
    if (!ls.length || tl.length + ls.length + (ei ? 1 : 0) > 24) break;
    if (ei) tl.push({ text: "", who: "", entry: ei, blank: true, mark: null });
    const hit = !marked && phrase.length >= 3 ? ls.join(" ").toLowerCase().indexOf(phrase) : -1;
    if (hit >= 0) marked = true;
    let off = 0;
    ls.forEach((t, li) => {
      let mark: [number, number] | null = null;
      if (hit >= 0) {
        const a = Math.max(off, hit);
        const b = Math.min(off + t.length, hit + phrase.length);
        if (b > a) mark = [a - off, b - off];
      }
      tl.push({ text: t, who: li === 0 ? e.who : "", entry: ei, blank: false, mark });
      off += t.length + 1;
    });
  }
  if (!tl.length) return null;
  const nE = tl[tl.length - 1].entry + 1;
  const T = (s: number) => Math.round(s * fps * pace);
  const start = T(0.5);
  const gapE = Math.max(10, Math.min(Math.round(fps * 1.3), Math.floor((dur * 0.64 - start) / nE)));
  const entryAt = (e: number) => start + e * gapE;
  const lineH = 47 * k;
  const HH = 178 * k;
  const firstLine: number[] = [];
  const lastLine: number[] = [];
  tl.forEach((l, j) => {
    if (l.blank) return;
    if (firstLine[l.entry] === undefined) firstLine[l.entry] = j;
    lastLine[l.entry] = j;
  });
  const view = 830 * k;
  const target = (e: number) => Math.max(0, HH + ((lastLine[e] ?? 0) + 1) * lineH - view);
  let scroll = 0;
  for (let e = 0; e < nE; e++) scroll += (target(e) - (e ? target(e - 1) : 0)) * ramp(frame, entryAt(e) - 4, 16, inOut);
  const land = ramp(frame, 0, T(0.7));
  const pageH = Math.max(1180 * k, HH + tl.length * lineH + 400 * k);
  const markBg = tint(accent, 0.5);
  const renderLine = (l: TLine, markP: number): React.ReactNode => {
    const headLen = l.who && l.text.startsWith(`${l.who}:`) ? l.who.length + 1 : 0;
    const head = headLen ? (
      <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 27 * k, letterSpacing: "0.12em", color: INK }}>{l.text.slice(0, headLen)}</span>
    ) : null;
    const rest = l.text.slice(headLen);
    if (!l.mark) return <>{head}{rest}</>;
    const a = Math.max(0, l.mark[0] - headLen);
    const b = Math.max(a, l.mark[1] - headLen);
    return (
      <>
        {head}{rest.slice(0, a)}
        <span style={{ backgroundImage: `linear-gradient(${markBg}, ${markBg})`, backgroundRepeat: "no-repeat", backgroundPosition: "0 62%",
          backgroundSize: `${(markP * 100).toFixed(1)}% 58%` }}>{rest.slice(a, b)}</span>
        {rest.slice(b)}
      </>
    );
  };
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <CaseBackdrop tone="red" seed={11} />
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 50%, rgba(0,0,0,0) 35%, rgba(0,0,0,.45) 100%)" }} />
      <div style={{ position: "absolute", left: 370 * k, top: 90 * k, width: 1180 * k, height: pageH, borderRadius: 4 * k,
        background: "linear-gradient(180deg, #fbfaf6 0%, #f2efe6 100%)", boxShadow: `0 ${40 * k}px ${100 * k}px rgba(0,0,0,.5)`,
        opacity: ramp(frame, 0, 6) * (1 - q), transformOrigin: "50% 0",
        transform: `translateY(${(((1 - land) * 240 - q * 60) * k - scroll).toFixed(2)}px) rotate(${-1 - (1 - land) * 3}deg)` }}>
        <div style={{ position: "absolute", left: 132 * k, right: 64 * k, top: 54 * k }}>
          <Letters text={clip(cap(title) || "TRANSCRIPT", 34)} at={T(0.15)} step={0.6} style={{ fontFamily: LABEL, fontWeight: 800,
            fontSize: 44 * k, letterSpacing: "0.08em", color: INK, lineHeight: 1.1 }} />
          {sub ? (
            <Rise at={T(0.25)} style={{ marginTop: 8 * k }}><span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 19 * k,
              letterSpacing: "0.16em", color: "#6f747c", whiteSpace: "nowrap" }}>{sub}</span></Rise>
          ) : null}
        </div>
        <div style={{ position: "absolute", left: 60 * k, right: 60 * k, top: 146 * k }}>
          <Rule at={T(0.2)} color={INK} h={3} />
        </div>
        <div style={{ position: "absolute", left: 90 * k, top: 160 * k, bottom: 0, width: 1.5 * k, background: tint(accent, 0.75),
          transform: `scaleY(${ramp(frame, T(0.25), 24, inOut)})`, transformOrigin: "50% 0" }} />
        <div style={{ position: "absolute", left: 96 * k, top: 160 * k, bottom: 0, width: 1.5 * k, background: tint(accent, 0.75),
          transform: `scaleY(${ramp(frame, T(0.28), 24, inOut)})`, transformOrigin: "50% 0" }} />
        {tl.map((l, j) => {
          const fl = firstLine[l.entry];
          const at = entryAt(l.entry) + (fl === undefined ? 0 : j - fl) * 3;
          const dimP = l.entry < nE - 1 ? ramp(frame, entryAt(l.entry + 1), 12) : 0;
          return (
            <div key={j} style={{ position: "absolute", left: 0, right: 0, top: HH + j * lineH, height: lineH, opacity: 1 - 0.5 * dimP }}>
              <div style={{ position: "absolute", left: 0, width: 74 * k, top: 0, textAlign: "right" }}>
                <Rise at={at}><span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 17 * k, lineHeight: `${lineH}px`,
                  color: "#8b9099" }}>{j + 1}</span></Rise>
              </div>
              {l.who ? (
                <div style={{ position: "absolute", left: 112 * k, top: 11 * k, width: 6 * k, height: lineH - 22 * k, background: accent,
                  transform: `scaleY(${ramp(frame, at, 10) * (1 - q)})`, transformOrigin: "50% 0" }} />
              ) : null}
              {!l.blank ? (
                <div style={{ position: "absolute", left: 132 * k, right: 64 * k, top: 0 }}>
                  <Rise at={at}>
                    <div style={{ fontFamily: INTER, fontWeight: 500, fontSize: 29 * k, lineHeight: `${lineH}px`, color: "#1b1f25",
                      whiteSpace: "nowrap" }}>
                      {renderLine(l, ramp(frame, at + 12, 12))}
                    </div>
                  </Rise>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== registry
/** A look never throws on a missing overlay and always has an accent. */
const safe = (Inner: Look): Look => {
  const Guarded: Look = ({ overlay, accent }) =>
    overlay && typeof overlay === "object" ? <Inner overlay={overlay} accent={accent || GOLD} /> : null;
  return Guarded;
};

export const LOOKS: Record<string, Look> = {
  "cf-evidence-bag": safe(EvidenceBag),
  "cf-case-stamp": safe(CaseCover),
  "cf-redacted-doc": safe(Redacted),
  "cf-fingerprint-scan": safe(PrintMatch),
  "cf-police-log": safe(DispatchLog),
  "cf-unknown-silhouette": safe(Unidentified),
  "cf-evidence-markers": safe(MarkerPhoto),
  "cf-phone-records": safe(PhoneLog),
  "cf-cctv-frame": safe(Surveillance),
  "cf-transcript": safe(Transcript),
};
