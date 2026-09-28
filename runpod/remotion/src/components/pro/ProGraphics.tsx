import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY, INTER, LABEL } from "../fonts";
import type { Overlay, OverlayItem } from "../../types";

/**
 * The "pro" graphics: the number, chart and title moments rebuilt from the
 * VidRush reference frames (docs/reference-catalog.md, scratchpad catalog):
 *
 *  - numbers are big condensed numerals that ROLL like an odometer, never a
 *    plain count-up, with a label tag in the accent colour;
 *  - over footage the picture is darkened and desaturated behind the number
 *    (their "$2,500,000 over the newspaper" look), full screen they sit on the
 *    animation scene's blurred-footage backdrop;
 *  - text never fades or types in: every line slides up out of a mask, the
 *    After Effects "text reveal", staggered, with an expo ease;
 *  - bars, gauges and rings fill on an ease-in-out after the numbers start.
 *
 * All sizes are 1080p-referenced and scaled to the composition.
 */

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const expoOut = Easing.bezier(0.16, 1, 0.3, 1);
const inOut = Easing.bezier(0.65, 0, 0.35, 1);

/**
 * A size multiplier for everything drawn with useK(): the text looks are
 * drawn a fifth larger than the data looks (the owner: "before too big, now
 * too small"), and an overlay's fontScale overrides it (Main.tsx).
 */
export const KScale = React.createContext(1);

export const useK = () => {
  const { width } = useVideoConfig();
  return (width / 1920) * React.useContext(KScale);
};

/** 0 -> 1 from `at` over `frames`, on an expo-out curve. */
export const ramp = (frame: number, at: number, frames: number, ease = expoOut) =>
  interpolate(frame, [at, at + Math.max(1, frames)], [0, 1], { ...clamp, easing: ease });

const isFull = (ov: Overlay) => Boolean((ov as Overlay & { fullFrame?: boolean }).fullFrame);

// ------------------------------------------------------------------ number text
export function formatValue(v: number, grouping = true): { text: string; decimals: number } {
  if (!Number.isFinite(v)) return { text: "", decimals: 0 };
  const decimals = Math.abs(v) >= 100 || Number.isInteger(v) ? 0 : 1;
  const text = v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals,
    useGrouping: grouping });
  return { text, decimals };
}

/**
 * An odometer: each digit is a column of 0-9 that spins into place, the
 * right-most spinning furthest, with a little motion blur while it moves.
 */
export const Odometer: React.FC<{
  value: number; at: number; frames: number; size: number; color: string;
  prefix?: string; suffix?: string; suffixScale?: number; suffixColor?: string; font?: string; grouping?: boolean;
}> = ({ value, at, frames, size, color, prefix = "", suffix = "", suffixScale = 0.55, suffixColor, font = DISPLAY,
        grouping = true }) => {
  const frame = useCurrentFrame();
  // A year never gets a thousands comma ("2,026" read as a count).
  const looksLikeYear = Number.isInteger(value) && value >= 1500 && value <= 2100 && !suffix;
  const { text } = formatValue(value, grouping && !looksLikeYear);
  const chars = text.split("");
  const digitsTotal = chars.filter((c) => /\d/.test(c)).length;
  let digitIndex = 0;
  const h = size;
  return (
    <span style={{ display: "inline-flex", alignItems: "flex-start", fontFamily: font, fontSize: size, lineHeight: 1,
      color, letterSpacing: "0.01em", fontVariantNumeric: "tabular-nums" }}>
      {prefix ? <span>{prefix}</span> : null}
      {chars.map((c, i) => {
        if (!/\d/.test(c)) {
          return <span key={i} style={{ opacity: ramp(frame, at, frames * 0.3) }}>{c}</span>;
        }
        const fromRight = digitsTotal - 1 - digitIndex;
        digitIndex += 1;
        const d = Number(c);
        const turns = 1 + Math.min(3, fromRight);          // right-most digits spin more
        const travel = turns * 10 + d;
        const start = at + fromRight * 2;
        const p = interpolate(frame, [start, start + frames], [0, 1], { ...clamp, easing: expoOut });
        const pos = p * travel;
        const prev = interpolate(frame - 1, [start, start + frames], [0, 1], { ...clamp, easing: expoOut }) * travel;
        const speed = Math.abs(pos - prev);
        const y = -(pos % 10) * h;
        return (
          <span key={i} style={{ display: "inline-block", height: h, overflow: "hidden", position: "relative" }}>
            <span style={{ display: "flex", flexDirection: "column", transform: `translateY(${y}px)`,
              filter: speed > 0.05 ? `blur(${Math.min(6, speed * 4)}px)` : undefined }}>
              {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 0].map((n, k) => (
                <span key={k} style={{ height: h, display: "block" }}>{n}</span>
              ))}
            </span>
          </span>
        );
      })}
      {suffix ? (
        <span style={{ fontSize: size * suffixScale, marginLeft: size * 0.04, marginTop: size * 0.06,
          color: suffixColor || color, opacity: ramp(frame, at + frames * 0.35, frames * 0.4) }}>{suffix}</span>
      ) : null}
    </span>
  );
};

// ------------------------------------------------------------------ text reveal
/** A line that slides up out of a mask (the After Effects text reveal). */
export const MaskLine: React.FC<{ at: number; frames?: number; children: React.ReactNode; style?: React.CSSProperties }> =
  ({ at, frames = 16, children, style }) => {
    const frame = useCurrentFrame();
    const p = ramp(frame, at, frames);
    return (
      <div style={{ overflow: "hidden", paddingBottom: "0.08em", ...style }}>
        <div style={{ transform: `translateY(${(1 - p) * 110}%)` }}>{children}</div>
      </div>
    );
  };

/**
 * A line whose letters rise out of the mask one after another and, at the
 * end of the graphic, drop out one after another (the owner: "animation in
 * and out on each letter").
 */
export const LetterLine: React.FC<{ text: string; at: number; step?: number; style?: React.CSSProperties;
  outAt?: number; children?: React.ReactNode }> = ({ text, at, step = 1, style, outAt }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const end = outAt ?? durationInFrames - 14;
  const chars = Array.from(text);
  return (
    <div style={{ overflow: "hidden", paddingBottom: "0.08em", ...style }}>
      {chars.map((c, i) => {
        const pin = ramp(frame, at + i * step, 12);
        const pout = ramp(frame, end + i * 0.6, 9, Easing.bezier(0.7, 0, 0.84, 0));
        const y = (1 - pin) * 105 - pout * 105;
        return (
          <span key={i} style={{ display: "inline-block", transform: `translateY(${y}%)`, whiteSpace: "pre",
            opacity: pin < 0.02 || pout > 0.98 ? 0 : 1 }}>{c}</span>
        );
      })}
    </div>
  );
};

/** Split a sentence into lines of about `chars` characters. */
export function lines(text: string, chars: number): string[] {
  const words = (text || "").split(/\s+/).filter(Boolean);
  const out: string[] = [];
  let cur = "";
  for (const w of words) {
    if (cur && (cur + " " + w).length > chars) {
      out.push(cur);
      cur = w;
    } else {
      cur = cur ? `${cur} ${w}` : w;
    }
  }
  if (cur) out.push(cur);
  return out;
}

/** The accent tag under a number: white caps on the accent, wiping open. */
export const Tag: React.FC<{ text: string; at: number; accent: string; size?: number; dark?: boolean }> =
  ({ text, at, accent, size = 34, dark }) => {
    const frame = useCurrentFrame();
    const k = useK();
    const p = ramp(frame, at, 14);
    if (!text) return null;
    return (
      <div style={{ display: "inline-block", clipPath: `inset(0 ${(1 - p) * 100}% 0 0)`,
        background: dark ? "#0c0c0f" : accent, color: dark ? accent : "#fff", fontFamily: LABEL, fontWeight: 800,
        fontSize: size * k, letterSpacing: "0.12em", textTransform: "uppercase", padding: `${8 * k}px ${22 * k}px ${6 * k}px`,
        boxShadow: "0 10px 30px rgba(0,0,0,.35)" }}>
        {text}
      </div>
    );
  };

/**
 * Over footage: the picture behind a number is darkened and desaturated
 * (VidRush's stat look). Full screen, the animation scene already did it.
 */
export const Scrim: React.FC<{ ov: Overlay; at?: number; focus?: string }> = ({ ov, at = 0, focus = "50% 50%" }) => {
  const frame = useCurrentFrame();
  if (isFull(ov)) return null;
  const p = ramp(frame, at, 12);
  if (ov.compact) {
    // A single figure riding on the clip: a soft pool of shade behind it
    // only, the picture stays bright around it.
    return (
      <AbsoluteFill style={{ opacity: p * 0.9,
        background: "radial-gradient(ellipse 46% 42% at 50% 50%, rgba(0,0,0,.55) 0%, rgba(0,0,0,.28) 55%, rgba(0,0,0,0) 100%)" }} />
    );
  }
  return (
    <AbsoluteFill style={{ opacity: p, backdropFilter: "grayscale(0.55) brightness(0.8)",
      WebkitBackdropFilter: "grayscale(0.55) brightness(0.8)",
      background: `radial-gradient(ellipse at ${focus}, rgba(0,0,0,.28) 0%, rgba(0,0,0,.38) 60%, rgba(0,0,0,.5) 100%)` }} />
  );
};

export const useHold = () => {
  // A slow push while the graphic holds: never quite still.
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return 1 + 0.035 * interpolate(frame, [0, Math.max(1, durationInFrames)], [0, 1], clamp);
};

// ------------------------------------------------------------------ stats
/**
 * One figure. Variants (overlay.variant):
 *   gauge   a vertical thermometer filling to the percentage, the number
 *           beside it, a title above (VidRush "LAKE MEAD: REMAINING CAPACITY")
 *   ring    a ring filling round the number, the label tag beneath
 *   corner  the number bottom-right over the footage with its tag
 *   roll    (default) the number huge in the centre, the tag beneath
 * Percentages default to gauge, other figures to roll.
 */
export const ProStat: React.FC<{ overlay: Overlay; accent: string; variant?: string }> = ({ overlay, accent, variant }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const value = Number(overlay.value ?? NaN);
  if (!Number.isFinite(value)) return null;
  const suffix = overlay.suffix || "";
  const pct = suffix.trim() === "%";
  const v = variant || overlay.variant || (pct ? "gauge" : "roll");
  const label = (overlay.text || "").toUpperCase();
  const title = (overlay.subtitle || "").toUpperCase();
  const numAt = Math.round(fps * 0.25);
  const numFrames = Math.round(fps * 1.3);

  if (v === "gauge") {
    const H = 390 * k, W = 70 * k;
    const fill = ramp(frame, numAt, numFrames, inOut) * Math.max(0, Math.min(100, value)) / 100;
    return (
      <AbsoluteFill>
        <Scrim ov={overlay} />
        <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
          {title ? (
            <MaskLine at={2} style={{ position: "absolute", top: "11%", left: 0, right: 0, textAlign: "center" }}>
              <span style={{ fontFamily: DISPLAY, fontSize: 52 * k, color: "#fff", letterSpacing: "0.04em" }}>{title}</span>
            </MaskLine>
          ) : null}
          <div style={{ display: "flex", alignItems: "center", gap: 60 * k }}>
            <div style={{ position: "relative", width: W, height: H, borderRadius: 14 * k,
              border: `${5 * k}px solid rgba(255,255,255,.92)`, overflow: "hidden", background: "rgba(0,0,0,.35)",
              opacity: ramp(frame, 0, 10), boxShadow: "0 20px 60px rgba(0,0,0,.5)" }}>
              <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: `${fill * 100}%`,
                background: `linear-gradient(180deg, ${accent} 0%, ${accent}cc 100%)`, boxShadow: `0 0 ${30 * k}px ${accent}` }} />
              {[0.25, 0.5, 0.75].map((t) => (
                <div key={t} style={{ position: "absolute", left: 0, width: "35%", bottom: `${t * 100}%`, height: 3 * k,
                  background: "rgba(255,255,255,.55)" }} />
              ))}
            </div>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 18 * k }}>
              <Odometer value={value} at={numAt} frames={numFrames} size={220 * k} color={accent} suffix={suffix}
                suffixScale={0.5} />
              <Tag text={label} at={numAt + 16} accent={accent} size={32} />
            </div>
          </div>
        </AbsoluteFill>
      </AbsoluteFill>
    );
  }

  if (v === "ring") {
    const R = 170 * k, S = 22 * k, size = 2 * R + 2 * S;
    const c = 2 * Math.PI * R;
    const fill = ramp(frame, numAt, numFrames, inOut) * Math.max(0, Math.min(100, pct ? value : 100)) / 100;
    return (
      <AbsoluteFill>
        <Scrim ov={overlay} />
        <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 34 * k,
          transform: `scale(${hold})` }}>
          <div style={{ position: "relative", width: size, height: size, opacity: ramp(frame, 0, 10) }}>
            <svg width={size} height={size} style={{ position: "absolute", inset: 0 }}>
              <circle cx={size / 2} cy={size / 2} r={R} fill="none" stroke="rgba(255,255,255,.16)" strokeWidth={S} />
              <circle cx={size / 2} cy={size / 2} r={R} fill="none" stroke={accent} strokeWidth={S} strokeLinecap="round"
                strokeDasharray={`${c * fill} ${c}`} transform={`rotate(-90 ${size / 2} ${size / 2})`}
                style={{ filter: `drop-shadow(0 0 ${14 * k}px ${accent})` }} />
            </svg>
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Odometer value={value} at={numAt} frames={numFrames} size={150 * k} color="#fff" suffix={suffix}
                suffixColor={accent} />
            </div>
          </div>
          <Tag text={label} at={numAt + 16} accent={accent} size={32} />
        </AbsoluteFill>
      </AbsoluteFill>
    );
  }

  if (v === "waffle") {
    // 100 dots, the share filling row by row ("26 of every 100").
    const n = Math.round(Math.max(0, Math.min(100, value)));
    const on = Math.round(ramp(frame, numAt, numFrames, inOut) * n);
    const D = 26 * k, G = 9 * k;
    return (
      <AbsoluteFill>
        <Scrim ov={overlay} />
        <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 90 * k }}>
            <div style={{ display: "grid", gridTemplateColumns: `repeat(10, ${D}px)`, gap: G, opacity: ramp(frame, 0, 10) }}>
              {Array.from({ length: 100 }, (_, i) => {
                const lit = i < on;
                return <div key={i} style={{ width: D, height: D, borderRadius: "50%",
                  background: lit ? accent : "rgba(255,255,255,.18)",
                  boxShadow: lit ? `0 0 ${10 * k}px ${accent}aa` : "none",
                  transform: `scale(${lit ? 1 : 0.86})` }} />;
              })}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 14 * k, maxWidth: 620 * k }}>
              <Odometer value={value} at={numAt} frames={numFrames} size={200 * k} color="#fff" suffix={suffix}
                suffixColor={accent} />
              <Tag text={label} at={numAt + 16} accent={accent} size={32} />
            </div>
          </div>
        </AbsoluteFill>
      </AbsoluteFill>
    );
  }

  if (v === "bar") {
    // A wide horizontal bar filling to the share, the number riding its end.
    const W = 1000 * k, BH = 52 * k;
    const g = ramp(frame, numAt, numFrames, inOut);
    const fill = g * Math.max(0, Math.min(100, pct ? value : 100)) / 100;
    return (
      <AbsoluteFill>
        <Scrim ov={overlay} />
        <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 30 * k,
          transform: `scale(${hold})` }}>
          {title ? (
            <MaskLine at={2}><span style={{ fontFamily: DISPLAY, fontSize: 70 * k, color: "#fff", letterSpacing: "0.04em" }}>
              {title}</span></MaskLine>
          ) : null}
          <div style={{ width: W, display: "flex", justifyContent: "flex-start" }}>
            <div style={{ marginLeft: Math.max(0, fill * W - 200 * k) }}>
              <Odometer value={value} at={numAt} frames={numFrames} size={150 * k} color="#fff" suffix={suffix}
                suffixColor={accent} />
            </div>
          </div>
          <div style={{ position: "relative", width: W, height: BH, borderRadius: BH / 2, background: "rgba(255,255,255,.16)",
            overflow: "hidden", boxShadow: "inset 0 2px 10px rgba(0,0,0,.4)", opacity: ramp(frame, 0, 10) }}>
            <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${fill * 100}%`, borderRadius: BH / 2,
              background: `linear-gradient(90deg, ${accent}aa, ${accent})`, boxShadow: `0 0 ${26 * k}px ${accent}` }} />
          </div>
          <div style={{ width: W, display: "flex", justifyContent: "space-between", fontFamily: LABEL, fontWeight: 700,
            fontSize: 30 * k, color: "rgba(255,255,255,.7)", letterSpacing: "0.1em", opacity: ramp(frame, 8, 12) }}>
            <span>0</span><Tag text={label} at={numAt + 16} accent={accent} size={36} /><span>100{pct ? "%" : ""}</span>
          </div>
        </AbsoluteFill>
      </AbsoluteFill>
    );
  }

  if (v === "pill") {
    // VidRush's "~8 | states it sits beneath": a glass pill low-left, on the footage.
    return (
      <AbsoluteFill>
        <div style={{ position: "absolute", left: 110 * k, bottom: 150 * k, display: "flex", alignItems: "center",
          gap: 26 * k, padding: `${18 * k}px ${40 * k}px ${18 * k}px ${30 * k}px`, borderRadius: 22 * k,
          background: "linear-gradient(135deg, rgba(14,14,18,.82), rgba(14,14,18,.62))", backdropFilter: "blur(12px)",
          border: "1px solid rgba(255,255,255,.14)", boxShadow: "0 18px 50px rgba(0,0,0,.45)",
          opacity: ramp(frame, 0, 10), transform: `translateY(${(1 - ramp(frame, 0, 16)) * 30 * k}px)` }}>
          <Odometer value={value} at={numAt} frames={numFrames} size={100 * k} color="#fff" suffix={suffix}
            suffixColor={accent} prefix={overlay.prefix || ""} />
          <div style={{ width: 4 * k, height: 90 * k, background: accent }} />
          <MaskLine at={numAt + 8}>
            <span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 44 * k, color: "#fff", letterSpacing: "0.04em",
              lineHeight: 1.05, display: "inline-block", maxWidth: 520 * k }}>{(overlay.text || "").toLowerCase()}</span>
          </MaskLine>
        </div>
      </AbsoluteFill>
    );
  }

  if (v === "split") {
    // The number on the left, a line of context on the right, an accent rule between.
    return (
      <AbsoluteFill>
        <Scrim ov={overlay} />
        <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 60 * k }}>
            <Odometer value={value} at={numAt} frames={numFrames} size={230 * k} color="#fff" suffix={suffix}
              suffixColor={accent} prefix={overlay.prefix || ""} />
            <div style={{ width: 8 * k, height: `${ramp(frame, numAt, 16) * 260 * k}px`, background: accent,
              boxShadow: `0 0 ${18 * k}px ${accent}` }} />
            <div style={{ display: "flex", flexDirection: "column", gap: 10 * k, maxWidth: 640 * k }}>
              {lines((overlay.text || "").toUpperCase(), 18).slice(0, 3).map((ln, i) => (
                <MaskLine key={i} at={numAt + 10 + i * 4}>
                  <span style={{ fontFamily: DISPLAY, fontSize: 68 * k, lineHeight: 1, color: "#fff" }}>{ln}</span>
                </MaskLine>
              ))}
              {title ? <Tag text={title} at={numAt + 24} accent={accent} size={34} /> : null}
            </div>
          </div>
        </AbsoluteFill>
      </AbsoluteFill>
    );
  }

  if (v === "corner") {
    return (
      <AbsoluteFill>
        {!isFull(overlay) ? (
          <AbsoluteFill style={{ opacity: ramp(frame, 0, 12),
            background: "radial-gradient(ellipse at 85% 80%, rgba(0,0,0,.65) 0%, rgba(0,0,0,.25) 40%, rgba(0,0,0,0) 70%)" }} />
        ) : null}
        <div style={{ position: "absolute", right: 110 * k, bottom: 120 * k, display: "flex", flexDirection: "column",
          alignItems: "flex-end", gap: 10 * k }}>
          <Odometer value={value} at={numAt} frames={numFrames} size={165 * k} color="#fff" suffix={suffix} />
          <Tag text={label} at={numAt + 14} accent={accent} size={30} />
        </div>
      </AbsoluteFill>
    );
  }

  // roll
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 22 * k,
        transform: `scale(${hold})` }}>
        {title ? (
          <MaskLine at={2}><span style={{ fontFamily: LABEL, fontWeight: 700, fontSize: 40 * k, letterSpacing: "0.2em",
            color: "rgba(255,255,255,.85)" }}>{title}</span></MaskLine>
        ) : null}
        <Odometer value={value} at={numAt} frames={numFrames} size={240 * k} color="#fff" suffix={suffix}
          suffixColor={accent} prefix={overlay.prefix || ""} />
        <div style={{ width: `${ramp(frame, numAt + 8, 20) * 320 * k}px`, height: 5 * k, background: accent,
          boxShadow: `0 0 ${18 * k}px ${accent}` }} />
        <Tag text={label} at={numAt + 18} accent={accent} size={32} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ trend
/** A change: the arrow draws, the amount rolls, the label says since when. */
export const ProTrend: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const value = Number(overlay.value ?? NaN);
  if (!Number.isFinite(value)) return null;
  const down = (overlay.label || "").toLowerCase() !== "up";
  const col = down ? "#ff3b30" : "#27d17f";
  const draw = ramp(frame, 4, 22, inOut);
  const numAt = Math.round(fps * 0.3);
  const A = 170 * k;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 50 * k }}>
          <svg width={A} height={A} viewBox="0 0 100 100" style={{ overflow: "visible",
            filter: `drop-shadow(0 0 ${16 * k}px ${col})`, transform: down ? "rotate(180deg)" : undefined }}>
            <path d="M50 92 V14 M20 40 L50 10 L80 40" fill="none" stroke={col} strokeWidth={11} strokeLinecap="round"
              strokeLinejoin="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - draw} />
          </svg>
          <div style={{ display: "flex", flexDirection: "column", gap: 16 * k }}>
            <Odometer value={value} at={numAt} frames={Math.round(fps * 1.2)} size={210 * k} color="#fff"
              prefix={down ? "−" : "+"} suffix={overlay.suffix ? ` ${overlay.suffix}` : ""} suffixColor={col} />
            <Tag text={(overlay.text || "").toUpperCase()} at={numAt + 16} accent={col} size={32} />
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ compare
const numbered = (items?: OverlayItem[]) =>
  (items || []).filter((i) => typeof i.value === "number" && Number.isFinite(i.value)) as (OverlayItem & { value: number; suffix?: string })[];

/** Then vs now: two columns, the numbers roll, the bars grow, the change in a pill. */
export const ProCompare: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const [a, b] = numbered(overlay.items);
  if (!a || !b) return null;
  const suf = (b as { suffix?: string }).suffix || (a as { suffix?: string }).suffix || overlay.suffix || "";
  if (overlay.variant === "boxes") {
    const box = (it: typeof a, at: number, hot: boolean) => (
      <div style={{ width: 380 * k, height: 310 * k, display: "flex", flexDirection: "column", alignItems: "center",
        justifyContent: "center", gap: 10 * k, background: "rgba(10,10,13,.78)", backdropFilter: "blur(10px)",
        border: `${3 * k}px solid ${hot ? accent : "rgba(255,255,255,.7)"}`, boxShadow: "0 24px 60px rgba(0,0,0,.5)",
        opacity: ramp(frame, at, 10), transform: `scale(${0.9 + 0.1 * ramp(frame, at, 16)})` }}>
        <span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 44 * k, letterSpacing: "0.16em",
          color: hot ? accent : "rgba(255,255,255,.8)" }}>{it.label}</span>
        <Odometer value={it.value} at={at + 4} frames={Math.round(fps * 1.1)} size={135 * k} color="#fff"
          prefix={(it as { prefix?: string }).prefix || overlay.prefix || ""}
          suffix={suf ? ` ${suf}` : ""} suffixScale={0.4} />
      </div>
    );
    const link = ramp(frame, 18, 16);
    return (
      <AbsoluteFill>
        <Scrim ov={overlay} />
        <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 40 * k,
          transform: `scale(${hold})` }}>
          {overlay.text ? (
            <MaskLine at={0}><span style={{ fontFamily: DISPLAY, fontSize: 72 * k, color: "#fff", letterSpacing: "0.05em" }}>
              {overlay.text.toUpperCase()}</span></MaskLine>
          ) : null}
          <div style={{ display: "flex", alignItems: "center" }}>
            {box(a, 4, false)}
            <div style={{ width: 220 * k, borderTop: `${5 * k}px dashed rgba(255,255,255,.85)`,
              clipPath: `inset(0 ${(1 - link) * 100}% 0 0)` }} />
            {box(b, 14, true)}
          </div>
        </AbsoluteFill>
      </AbsoluteFill>
    );
  }
  const max = Math.max(a.value, b.value, 1e-9);
  const down = b.value < a.value;
  const col = down ? "#ff3b30" : "#27d17f";
  const change = a.value ? ((b.value - a.value) / Math.abs(a.value)) * 100 : 0;
  const BAR = 230 * k;
  const column = (it: typeof a, at: number, hot: boolean) => {
    const g = ramp(frame, at + 10, Math.round(fps * 1.1), inOut);
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 * k, width: 380 * k }}>
        <MaskLine at={at}><span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 42 * k, letterSpacing: "0.14em",
          color: hot ? col : "rgba(255,255,255,.8)" }}>{it.label}</span></MaskLine>
        <Odometer value={it.value} at={at + 4} frames={Math.round(fps * 1.2)} size={170 * k} color="#fff"
          prefix={(it as { prefix?: string }).prefix || overlay.prefix || ""}
          suffix={suf ? ` ${suf}` : ""} suffixScale={0.42} suffixColor={hot ? col : "rgba(255,255,255,.7)"} />
        <div style={{ width: 150 * k, height: BAR, display: "flex", alignItems: "flex-end",
          borderBottom: `${4 * k}px solid rgba(255,255,255,.7)` }}>
          <div style={{ width: "100%", height: `${g * (it.value / max) * 100}%`,
            background: hot ? `linear-gradient(180deg, ${col}, ${col}aa)` : "linear-gradient(180deg, #f2f2f2, #bdbdbd)",
            boxShadow: hot ? `0 0 ${24 * k}px ${col}88` : "none" }} />
        </div>
      </div>
    );
  };
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 40 * k,
        transform: `scale(${hold})` }}>
        {overlay.text ? (
          <MaskLine at={0}><span style={{ fontFamily: DISPLAY, fontSize: 72 * k, color: "#fff", letterSpacing: "0.05em" }}>
            {overlay.text.toUpperCase()}</span></MaskLine>
        ) : null}
        <div style={{ display: "flex", alignItems: "center", gap: 20 * k }}>
          {column(a, 4, false)}
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 14 * k,
            opacity: ramp(frame, Math.round(fps * 1.0), 12) }}>
            <svg width={160 * k} height={60 * k} viewBox="0 0 160 60">
              <path d="M6 30 H140 M112 8 L150 30 L112 52" fill="none" stroke="#fff" strokeWidth={8} strokeLinecap="round"
                strokeLinejoin="round" pathLength={1} strokeDasharray={1}
                strokeDashoffset={1 - ramp(frame, Math.round(fps * 0.9), 14)} />
            </svg>
            <div style={{ background: col, color: "#fff", fontFamily: LABEL, fontWeight: 800, fontSize: 44 * k,
              padding: `${8 * k}px ${26 * k}px`, borderRadius: 48 * k, letterSpacing: "0.04em",
              boxShadow: `0 0 ${24 * k}px ${col}88` }}>
              {down ? "▼" : "▲"} {Math.abs(change) >= 100 ? Math.round(Math.abs(change)) : Math.abs(change).toFixed(0)}%
            </div>
          </div>
          {column(b, 12, true)}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ bars
/** A dark chart: title, grid, bars growing in turn with their values rolling. */
export const ProBars: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const items = numbered(overlay.items).slice(0, 6);
  if (!items.length) return null;
  const max = Math.max(...items.map((i) => i.value), 1e-9);
  const H = 480 * k;
  const barW = Math.min(170, 950 / items.length) * k;
  const hi = items.reduce((m, it, i) => (it.value < items[m].value ? i : m), 0);
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 36 * k }}>
        {overlay.text ? (
          <MaskLine at={0}><span style={{ fontFamily: DISPLAY, fontSize: 70 * k, color: "#fff", letterSpacing: "0.05em" }}>
            {overlay.text.toUpperCase()}</span></MaskLine>
        ) : null}
        <div style={{ position: "relative", display: "flex", alignItems: "flex-end", gap: 60 * k, height: H,
          padding: `0 ${40 * k}px`, borderBottom: `${4 * k}px solid rgba(255,255,255,.8)` }}>
          {[0.25, 0.5, 0.75, 1].map((t) => (
            <div key={t} style={{ position: "absolute", left: 0, right: 0, bottom: t * H, height: 1,
              background: "rgba(255,255,255,.12)", opacity: ramp(frame, 0, 10) }} />
          ))}
          {items.map((it, i) => {
            const at = Math.round(fps * 0.25) + i * 5;
            const g = ramp(frame, at, Math.round(fps * 1.0), inOut);
            const hot = i === hi;
            return (
              <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10 * k, width: barW }}>
                <Odometer value={it.value} at={at} frames={Math.round(fps * 1.0)} size={68 * k}
                  color={hot ? accent : "#fff"} />
                <div style={{ width: "100%", height: g * (it.value / max) * (H - 110 * k),
                  background: hot ? `linear-gradient(180deg, ${accent}, ${accent}b0)` : "linear-gradient(180deg, #e9e9e9, #a9a9a9)",
                  boxShadow: hot ? `0 0 ${24 * k}px ${accent}88` : "none", borderRadius: `${6 * k}px ${6 * k}px 0 0` }} />
              </div>
            );
          })}
        </div>
        <div style={{ display: "flex", gap: 60 * k, padding: `0 ${40 * k}px` }}>
          {items.map((it, i) => (
            <div key={i} style={{ width: barW, textAlign: "center", fontFamily: LABEL, fontWeight: 700, fontSize: 42 * k,
              color: "rgba(255,255,255,.85)", letterSpacing: "0.06em", opacity: ramp(frame, 8 + i * 4, 12) }}>{it.label}</div>
          ))}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ title
/**
 * A kinetic title: big condensed lines slide up out of their masks one after
 * another, an accent bar sweeps behind the strongest word, a small kicker
 * above. A question gets "THE QUESTION" and a question mark in the accent.
 */
export const ProTitle: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const raw = (overlay.text || "").trim();
  const question = /\?\s*$/.test(raw);
  const text = raw.replace(/[?.!]+\s*$/, "");
  const words = text.split(/\s+/).filter(Boolean);
  const size = words.length > 14 ? 52 : words.length > 8 ? 62 : 74;
  const perLine = size > 70 ? 24 : size > 58 ? 30 : 36;
  const ls = lines(text.toUpperCase(), perLine).slice(0, 4);
  // The strongest word: the longest one of the last line (a crude but steady pick).
  const last = ls[ls.length - 1] || "";
  // A question keeps its accent for the question mark; a statement marks its
  // strongest word (the longest of the last line, five letters or more).
  const longest = last.split(" ").reduce((m, w) => (w.length > m.length ? w : m), "");
  const key = !question && longest.length >= 5 ? longest : "";
  const kicker = overlay.subtitle || (question ? "The question" : "");
  return (
    <AbsoluteFill>
      {isFull(overlay) ? null : (
        <AbsoluteFill style={{ opacity: ramp(frame, 0, 10),
          background: "linear-gradient(90deg, rgba(0,0,0,.5) 0%, rgba(0,0,0,.28) 38%, rgba(0,0,0,0) 62%)" }} />
      )}
      <AbsoluteFill style={{ justifyContent: "center", paddingLeft: "8%", paddingRight: "30%", transform: `scale(${hold})` }}>
        {kicker ? (
          <LetterLine text={kicker.toUpperCase()} at={0} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 28 * k,
            letterSpacing: "0.3em", color: accent }} />
        ) : null}
        <div style={{ width: `${ramp(frame, 2, 16) * 120 * k}px`, height: 6 * k, background: accent,
          margin: `${10 * k}px 0 ${14 * k}px` }} />
        {ls.map((line, i) => {
          const at = 4 + i * Math.round(fps * 0.16);
          const hasKey = key && i === ls.length - 1 && line.includes(key);
          const sweep = ramp(frame, at + 10, 14);
          return (
            <div key={i} style={{ position: "relative", display: "inline-block", alignSelf: "flex-start" }}>
              {hasKey ? (
                <span style={{ position: "absolute", left: `${(line.indexOf(key) / Math.max(1, line.length)) * 100}%`,
                  width: `${(key.length / Math.max(1, line.length)) * 100 + 2}%`, top: "8%", bottom: "6%", background: accent,
                  transform: `scaleX(${sweep})`, transformOrigin: "left", opacity: 0.95 }} />
              ) : null}
              <LetterLine text={line + (question && i === ls.length - 1 ? "?" : "")} at={at}
                style={{ position: "relative", fontFamily: DISPLAY, fontSize: size * k, lineHeight: 0.98, color: "#fff",
                  letterSpacing: "0.02em", textShadow: "0 6px 30px rgba(0,0,0,.55)" }} />
            </div>
          );
        })}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export { INTER as _INTER };


// ------------------------------------------------------------------ date
/** "SEPTEMBER 2026": the month slides up out of its mask, the year rolls in. */
export const ProDate: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const raw = (overlay.text || "").toUpperCase().trim();
  const m = /^(.*?)\s*((?:1[6-9]|20)\d\d)$/.exec(raw);
  const head = m ? m[1] : raw;
  const year = m ? Number(m[2]) : NaN;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 6 * k,
        transform: `scale(${hold})` }}>
        {head ? (
          <MaskLine at={2}><span style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 64 * k, letterSpacing: "0.3em",
            color: "#fff" }}>{head}</span></MaskLine>
        ) : null}
        {Number.isFinite(year) ? (
          <Odometer value={year} at={Math.round(fps * 0.2)} frames={Math.round(fps * 1.2)} size={210 * k} color={accent}
            grouping={false} />
        ) : null}
        <div style={{ width: `${ramp(frame, 10, 18) * 360 * k}px`, height: 6 * k, background: "#fff", marginTop: 6 * k }} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ timeline
/** A line drawing left to right; each event's dot pops and its labels slide up. */
export const ProTimeline: React.FC<{ overlay: Overlay; accent: string }> = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = useK();
  const items = (overlay.items || []).filter((i) => i.label).slice(0, 6);
  if (!items.length) return null;
  const W = 1500 * k;
  const draw = ramp(frame, 4, Math.round(fps * 1.6), inOut);
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 70 * k }}>
        {overlay.text ? (
          <MaskLine at={0}><span style={{ fontFamily: DISPLAY, fontSize: 72 * k, color: "#fff", letterSpacing: "0.05em" }}>
            {overlay.text.toUpperCase()}</span></MaskLine>
        ) : null}
        <div style={{ position: "relative", width: W, height: 260 * k }}>
          <div style={{ position: "absolute", left: 0, top: 130 * k, height: 5 * k, width: `${draw * 100}%`,
            background: "rgba(255,255,255,.9)" }} />
          {items.map((it, i) => {
            const x = items.length === 1 ? 0.5 : i / (items.length - 1);
            const at = 4 + Math.round(fps * 1.6 * x);
            const p = ramp(frame, at, 12);
            const up = i % 2 === 0;
            return (
              <div key={i} style={{ position: "absolute", left: x * W, top: 0, width: 0, height: 260 * k }}>
                <div style={{ position: "absolute", left: -16 * k, top: 116 * k, width: 32 * k, height: 32 * k,
                  borderRadius: "50%", background: accent, transform: `scale(${p})`,
                  boxShadow: `0 0 ${16 * k}px ${accent}` }} />
                <div style={{ position: "absolute", left: -220 * k, width: 440 * k, textAlign: "center",
                  top: up ? 10 * k : 170 * k }}>
                  <MaskLine at={at + 2}><span style={{ fontFamily: DISPLAY, fontSize: 64 * k, color: "#fff" }}>{it.label}</span></MaskLine>
                  {it.text ? (
                    <MaskLine at={at + 6}><span style={{ fontFamily: LABEL, fontWeight: 600, fontSize: 30 * k,
                      color: "rgba(255,255,255,.8)" }}>{it.text}</span></MaskLine>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
