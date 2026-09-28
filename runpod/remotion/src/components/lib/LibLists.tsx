import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { DISPLAY, INTER, LABEL } from "../fonts";
import type { Overlay, OverlayItem } from "../../types";
import { LetterLine, Odometer, Scrim, lines, ramp, useHold, useK } from "../pro/ProGraphics";
import { Heading } from "../pro/ProCharts";
import { CaseBackdrop } from "../pro/ProCase";

/**
 * Lists & processes (family "ls-"), in the pro look: condensed caps rising out
 * of masks (and leaving the same way), crisp geometry, the accent used
 * sparingly, green / red only for a plus / a minus or a gain / a loss.
 *
 *   ls-numbered-cascade   paper-white numbered cards falling into a diagonal
 *                         cascade (3D tilt, shadows tightening as they land)
 *   ls-checklist-ticks    a checklist on the footage: boxes draw, fill and
 *                         tick in turn, a progress bar counting them
 *   ls-pros-cons          two columns, a plus and a minus badge, the points
 *                         landing left, right, left, right
 *   ls-top-countdown      a giant rank rolling 5 > 1 while the list builds up
 *                         from the bottom; number one lands enlarged
 *   ls-icon-grid          a crosshair splits a 2x2 grid; geometric icons draw
 *                         on and fill with liquid, clockwise
 *   ls-process-chevrons   interlocking chevrons light up left to right
 *   ls-cycle-loop         steps round a ring, arcs drawing between them,
 *                         dashes flowing and a comet circling
 *   ls-pyramid-levels     trapezoid levels stacking bottom-up on the case
 *                         desktop, leaders out to their labels
 *   ls-funnel-stages      a funnel pouring stage by stage, the values and the
 *                         drop-off between stages, on a graphite mesh
 *   ls-tab-reveal         an accordion of white tabs on the footage: each
 *                         opens, runs its progress bar, closes to the next
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const backOut = Easing.bezier(0.34, 1.56, 0.64, 1);
const expoIn = Easing.bezier(0.7, 0, 0.84, 0);
const RED = "#ff3b30";
const GREEN = "#27d17f";
const CYAN = "#53c8ff";
const INK = "#0c0c0f";
const TAU = Math.PI * 2;

const cap = (s?: string) => (s || "").toUpperCase();
const pad2 = (i: number) => String(i).padStart(2, "0");
const f1 = (v: number) => (Number.isFinite(v) ? v : 0).toFixed(1);
const hexA = (a: number) => Math.round(Math.max(0, Math.min(1, a)) * 255).toString(16).padStart(2, "0");
const sfx = (s: string) => {
  const t = (s || "").trim();
  return !t ? "" : t === "%" ? "%" : ` ${t}`;
};
/** A short deterministic hash (SVG ids unique per overlay, not just per start frame). */
const hashStr = (s: string) => {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return (h >>> 0).toString(36);
};
const uidOf = (prefix: string, ov: Overlay) =>
  `${prefix}${Number.isFinite(ov.startFrame) ? ov.startFrame : 0}-${hashStr(`${ov.text || ""}|${ov.variant || ""}`)}`;
/** The items as an array whatever arrived (a malformed plan must not crash the render). */
const itemsOf = (items: unknown): OverlayItem[] =>
  Array.isArray(items) ? (items.filter((it) => Boolean(it) && typeof it === "object") as OverlayItem[]) : [];
/** A nearly closed circle as a path (so it can be drawn on with a dash). */
const ringPath = (cx: number, cy: number, r: number) =>
  `M${f1(cx)} ${f1(cy - r)} A${f1(r)} ${f1(r)} 0 1 1 ${f1(cx - 0.01)} ${f1(cy - r)}`;

type Row = { label: string; text: string; value: number | null; prefix: string; suffix: string };

/** Clean list rows: a label (or the text when there is no label), at most `max`. */
const rowsOf = (items: OverlayItem[] | undefined, max: number): Row[] => {
  const out: Row[] = [];
  for (const raw of itemsOf(items)) {
    const it = raw as OverlayItem & { prefix?: unknown; suffix?: unknown };
    const label = typeof it.label === "string" ? it.label.trim() : "";
    const text = typeof it.text === "string" ? it.text.trim() : "";
    if (!label && !text) continue;
    const v = typeof it.value === "number" && Number.isFinite(it.value) ? it.value : null;
    out.push({
      label: label || text, text: label ? text : "", value: v,
      prefix: typeof it.prefix === "string" ? it.prefix : "",
      suffix: typeof it.suffix === "string" ? it.suffix : "",
    });
    if (out.length >= max) break;
  }
  return out;
};

/** 0 while the look holds, 1 once it has gone: the last ~12 frames, accelerating. */
const useExit = (len = 12) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return ramp(frame, durationInFrames - len - 1, len, expoIn);
};

/** A line rising out of its mask at `at` and rising away out of it at `out`. */
const Rise: React.FC<{ at: number; out?: number; frames?: number; style?: React.CSSProperties; children: React.ReactNode }> =
  ({ at, out, frames = 16, style, children }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();
    const pin = ramp(frame, at, frames);
    const pout = ramp(frame, out ?? durationInFrames - 14, 10, expoIn);
    const y = (1 - pin) * 112 - pout * 112;
    return (
      <div style={{ overflow: "hidden", paddingBottom: "0.08em", ...style }}>
        <div style={{ transform: `translateY(${y.toFixed(2)}%)`, opacity: pin <= 0.001 || pout >= 0.999 ? 0 : 1 }}>
          {children}
        </div>
      </div>
    );
  };

// ================================================================== 1. numbered cascade
/**
 * Paper-white cards fall into a diagonal cascade one after another: each
 * drops in tilted back (rotateX in perspective), its shadow tightening as it
 * lands, the accent number block and the words rising out of their masks, a
 * sheen sweeping across once it settles. At the end the cards fold away in turn.
 */
const NumberedCascade: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit();
  const rows = rowsOf(overlay.items, 5);
  if (!rows.length) return null;
  const n = rows.length;
  const hasText = rows.some((r) => r.text);
  const CH = (hasText ? 110 : 92) * k;
  const CW = 860 * k;
  const SX = 44 * k;
  const GAP = (n > 4 ? 16 : 22) * k;
  const at0 = Math.round(fps * 0.3);
  const step = Math.max(5, Math.min(9, Math.round((durationInFrames * 0.3) / n)));
  const end = durationInFrames - 20;
  const title = overlay.text || "";
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 34 * k }}>
          {title ? (
            <div style={{ opacity: 1 - exit }}><Heading text={title} accent={accent} size={title.length > 34 ? 46 : 56} /></div>
          ) : null}
          <div style={{ position: "relative", width: CW + (n - 1) * SX, height: n * CH + (n - 1) * GAP, perspective: 1600 * k }}>
            {rows.map((r, i) => {
              const at = at0 + i * step;
              const p = ramp(frame, at, 20);
              const q = ramp(frame, end + i * 2, 10, expoIn);
              const float = Math.sin((frame + i * 11) / (fps * 0.9)) * 2.5 * k * p;
              const y = (1 - p) * -150 * k + float - q * 40 * k;
              const rx = (1 - p) * 58 - q * 80;
              const sheen = ramp(frame, at + 16, 24, inOut);
              const oy = (70 - 48 * p) * k;
              const blur = (90 - 46 * p) * k;
              const sa = 0.16 + 0.36 * p;
              const out = end + i * 2 - 5;
              return (
                <div key={i} style={{ position: "absolute", left: i * SX, top: i * (CH + GAP), width: CW, height: CH,
                  transformOrigin: "50% 0%", transform: `translateY(${f1(y)}px) rotateX(${f1(rx)}deg)`,
                  opacity: Math.min(1, p * 3) * (1 - q), borderRadius: 14 * k, overflow: "hidden", display: "flex",
                  background: "linear-gradient(180deg, #ffffff 0%, #eae8e2 100%)",
                  boxShadow: `0 ${f1(oy)}px ${f1(blur)}px rgba(0,0,0,${sa.toFixed(3)}), 0 ${f1(2 * k)}px ${f1(5 * k)}px rgba(0,0,0,.2)` }}>
                  <div style={{ width: CH * 1.08, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center",
                    background: `linear-gradient(160deg, ${accent} 0%, ${accent}d0 100%)` }}>
                    <Rise at={at + 6} out={out}>
                      <span style={{ display: "block", fontFamily: DISPLAY, fontSize: CH * 0.6, lineHeight: 1, color: INK,
                        letterSpacing: "0.02em", paddingTop: 4 * k }}>{pad2(i + 1)}</span>
                    </Rise>
                  </div>
                  <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", justifyContent: "center",
                    gap: 4 * k, padding: `0 ${34 * k}px` }}>
                    <Rise at={at + 9} out={out}>
                      <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: (r.text ? 40 : 44) * k,
                        lineHeight: 1.02, color: INK, letterSpacing: "0.04em", whiteSpace: "nowrap", overflow: "hidden",
                        textOverflow: "ellipsis" }}>{cap(r.label)}</span>
                    </Rise>
                    {r.text ? (
                      <Rise at={at + 13} out={out}>
                        <span style={{ display: "block", fontFamily: INTER, fontWeight: 400, fontSize: 24 * k, lineHeight: 1.2,
                          color: "#55565c", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{r.text}</span>
                      </Rise>
                    ) : null}
                  </div>
                  {sheen > 0 && sheen < 1 ? (
                    <div style={{ position: "absolute", inset: 0, pointerEvents: "none",
                      background: "linear-gradient(105deg, rgba(255,255,255,0) 38%, rgba(255,255,255,.65) 50%, rgba(255,255,255,0) 62%)",
                      transform: `translateX(${(-100 + 200 * sheen).toFixed(2)}%)` }} />
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 2. checklist ticks
/**
 * A checklist riding on the footage, left of frame: the rows rise in, each
 * box draws its outline, then in turn a box fills with the accent, the tick
 * draws through it with a ripple, the row brightens and the progress bar
 * below counts it ("3/4 CONFIRMED").
 */
const ChecklistTicks: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const exit = useExit();
  const rows = rowsOf(overlay.items, 5);
  if (!rows.length) return null;
  const n = rows.length;
  const end = durationInFrames - 16;
  const tick0 = Math.round(fps * 0.8);
  const tickStep = Math.max(6, Math.min(Math.round(fps * 0.55), Math.floor((end - 8 - tick0) / n)));
  const tickAt = (i: number) => tick0 + i * tickStep;
  const done = rows.reduce((m, _r, i) => m + (frame >= tickAt(i) + 4 ? 1 : 0), 0);
  const prog = rows.reduce((m, _r, i) => m + ramp(frame, tickAt(i), 12, inOut), 0) / n;
  const BOX = 46 * k;
  const W = 660 * k;
  const titleLines = lines(cap(overlay.text || ""), 28).slice(0, 2);
  const glow = ramp(frame, 0, 12) * (1 - exit);
  const foot = cap(overlay.label || "");
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: glow,
        background: "linear-gradient(90deg, rgba(0,0,0,.62) 0%, rgba(0,0,0,.34) 30%, rgba(0,0,0,0) 58%)" }} />
      <div style={{ position: "absolute", left: 110 * k, top: "50%", transform: "translateY(-50%)", width: W,
        display: "flex", flexDirection: "column" }}>
        {titleLines.length ? (
          <div style={{ marginBottom: 18 * k }}>
            {titleLines.map((ln, li) => (
              <LetterLine key={li} text={ln} at={li * 4} step={0.6} style={{ fontFamily: LABEL, fontWeight: 800,
                fontSize: 32 * k, lineHeight: 1.1, letterSpacing: "0.2em", color: accent, textShadow: "0 3px 14px rgba(0,0,0,.6)" }} />
            ))}
            <div style={{ width: ramp(frame, 3, 16) * (1 - exit) * 90 * k, height: 5 * k, background: accent, marginTop: 10 * k }} />
          </div>
        ) : null}
        {rows.map((r, i) => {
          const at = Math.round(fps * 0.2) + i * 4;
          const e = ramp(frame, at, 14);
          const box = ramp(frame, at + 2, 14, inOut);
          const t = tickAt(i);
          const fill = ramp(frame, t, 8, backOut);
          const check = ramp(frame, t + 3, 10, inOut);
          const rip = ramp(frame, t + 2, 18);
          const lit = ramp(frame, t, 10);
          // Staggered exit, the last row gone by the final frame (no pop on the cut).
          const qAt = durationInFrames - 18 + i * 1.5;
          const q = ramp(frame, qAt, 10, expoIn);
          return (
            <div key={i} style={{ position: "relative", display: "flex", alignItems: "center", gap: 24 * k, height: 72 * k,
              opacity: 1 - q, transform: `translateX(${f1(-q * 40 * k)}px)` }}>
              <svg width={BOX} height={BOX} viewBox="0 0 46 46" style={{ overflow: "visible", flexShrink: 0 }}>
                <path d="M12 2 H34 A10 10 0 0 1 44 12 V34 A10 10 0 0 1 34 44 H12 A10 10 0 0 1 2 34 V12 A10 10 0 0 1 12 2 Z"
                  fill={`rgba(0,0,0,${(0.28 * box).toFixed(3)})`} stroke="rgba(255,255,255,.9)" strokeWidth={3}
                  pathLength={1} strokeDasharray={1} strokeDashoffset={1 - box} />
                <rect x={2} y={2} width={42} height={42} rx={10} fill={accent}
                  transform={`translate(23 23) scale(${Math.max(0, fill).toFixed(4)}) translate(-23 -23)`} />
                <path d="M12 24 L20 32 L35 14" fill="none" stroke={INK} strokeWidth={5.5} strokeLinecap="round"
                  strokeLinejoin="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - check} />
                {rip > 0 && rip < 1 ? (
                  <circle cx={23} cy={23} r={24 + 26 * rip} fill="none" stroke={accent} strokeWidth={3 * (1 - rip)}
                    opacity={1 - rip} />
                ) : null}
              </svg>
              <Rise at={at + 2} out={qAt} style={{ flex: 1, minWidth: 0 }}>
                <span style={{ display: "block", fontFamily: LABEL, fontWeight: 700, fontSize: 40 * k, lineHeight: 1.05,
                  color: `rgba(255,255,255,${(0.58 + 0.42 * lit).toFixed(3)})`, letterSpacing: "0.02em", whiteSpace: "nowrap",
                  overflow: "hidden", textOverflow: "ellipsis", textShadow: "0 3px 14px rgba(0,0,0,.6)" }}>{r.label}</span>
              </Rise>
              <div style={{ position: "absolute", left: BOX + 24 * k, bottom: 0, height: Math.max(1, 1.5 * k),
                width: `${(e * (1 - q) * 100).toFixed(2)}%`, maxWidth: W - BOX - 24 * k, background: "rgba(255,255,255,.16)" }} />
            </div>
          );
        })}
        <div style={{ display: "flex", alignItems: "center", gap: 18 * k, marginTop: 24 * k,
          opacity: ramp(frame, tick0 - 6, 10) * (1 - exit) }}>
          <div style={{ position: "relative", flex: 1, height: 5 * k, background: "rgba(255,255,255,.2)", borderRadius: 3 * k,
            overflow: "hidden" }}>
            <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${(prog * 100).toFixed(2)}%`, background: accent,
              boxShadow: `0 0 ${10 * k}px ${accent}` }} />
          </div>
          <Rise at={tick0 - 4} out={durationInFrames - 14}>
            <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: 28 * k, color: "#fff",
              letterSpacing: "0.12em", whiteSpace: "nowrap", textShadow: "0 3px 12px rgba(0,0,0,.6)" }}>
              <span style={{ color: accent }}>{done}</span>/{n}{foot ? ` ${foot}` : ""}
            </span>
          </Rise>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== 3. pros cons
const PRO_RE = /^(pro|pros|\+|plus|for|yes|benefit|upside|good)$/i;
const CON_RE = /^(con|cons|-|−|minus|against|no|risk|downside|bad)$/i;

/**
 * Two columns split by a divider drawing from the centre: a green plus badge
 * spins in over the left column, a red minus badge over the right, each
 * column's tint wiping down; the points land left, right, left, right, their
 * little plus / minus rings drawing on as the words rise.
 */
const ProsCons: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit();
  const raw = itemsOf(overlay.items).filter((it) => typeof it.label === "string" && it.label.trim().length > 0);
  const tagOf = (it: OverlayItem) => (typeof it.text === "string" ? it.text.trim() : "");
  const tagged = raw.some((it) => PRO_RE.test(tagOf(it)) || CON_RE.test(tagOf(it)));
  let pros: string[];
  let cons: string[];
  if (tagged) {
    pros = raw.filter((it) => PRO_RE.test(tagOf(it))).map((it) => it.label.trim());
    cons = raw.filter((it) => CON_RE.test(tagOf(it))).map((it) => it.label.trim());
  } else {
    const half = Math.ceil(raw.length / 2);
    pros = raw.slice(0, half).map((it) => it.label.trim());
    cons = raw.slice(half).map((it) => it.label.trim());
  }
  pros = pros.slice(0, 4);
  cons = cons.slice(0, 4);
  if (!pros.length || !cons.length) return null;
  const heads = (overlay.label || "").split("|").map((s) => s.trim()).filter(Boolean);
  const headA = cap(heads[0] || "Pros");
  const headB = cap(heads[1] || "Cons");
  const headAt = [6, 12];
  const t0 = Math.round(fps * 0.55);
  const rowsMax = Math.max(pros.length, cons.length);
  const step = Math.max(4, Math.min(Math.round(fps * 0.28), Math.floor((durationInFrames * 0.45) / (rowsMax * 2))));
  const COLW = 620 * k;
  const dv = ramp(frame, 2, 20, inOut) * (1 - exit);
  const column = (list: string[], side: 0 | 1) => {
    const col = side === 0 ? GREEN : RED;
    const hp = ramp(frame, headAt[side], 16, backOut);
    const tint = ramp(frame, headAt[side] + 2, 22, inOut);
    return (
      <div style={{ position: "relative", width: COLW, padding: `${34 * k}px ${40 * k}px ${40 * k}px`, display: "flex",
        flexDirection: "column", gap: 18 * k }}>
        <div style={{ position: "absolute", inset: 0, borderRadius: 18 * k, borderTop: `${3 * k}px solid ${col}`,
          background: `linear-gradient(180deg, ${col}2a 0%, ${col}0a 55%, rgba(255,255,255,0) 100%)`,
          clipPath: `inset(0 0 ${((1 - tint) * 100).toFixed(2)}% 0)`, opacity: 1 - exit }} />
        <div style={{ position: "relative", display: "flex", alignItems: "center", gap: 20 * k, marginBottom: 8 * k }}>
          <svg width={60 * k} height={60 * k} viewBox="0 0 60 60" style={{ overflow: "visible", flexShrink: 0,
            transform: `scale(${(Math.max(0, hp) * (1 - exit)).toFixed(4)}) rotate(${f1((1 - Math.min(1, hp)) * (side === 0 ? -90 : 90))}deg)` }}>
            <circle cx={30} cy={30} r={28} fill={col} />
            <path d={side === 0 ? "M18 30 H42 M30 18 V42" : "M18 30 H42"} stroke="#fff" strokeWidth={6} strokeLinecap="round" />
          </svg>
          <LetterLine text={side === 0 ? headA : headB} at={headAt[side] + 3} step={0.8} style={{ fontFamily: DISPLAY,
            fontSize: 64 * k, color: "#fff", letterSpacing: "0.06em", lineHeight: 1, paddingTop: 6 * k }} />
        </div>
        {list.map((txt, j) => {
          const at = t0 + (2 * j + side) * step;
          const d = ramp(frame, at, 12, inOut);
          const qAt = durationInFrames - 17 + j * 1.5;
          const q = ramp(frame, qAt, 10, expoIn);
          return (
            <div key={j} style={{ position: "relative", display: "flex", alignItems: "flex-start", gap: 18 * k }}>
              <svg width={38 * k} height={38 * k} viewBox="0 0 40 40" style={{ flexShrink: 0, marginTop: 4 * k, opacity: 1 - q,
                overflow: "visible" }}>
                <path d={ringPath(20, 20, 17)} fill="none" stroke={col} strokeWidth={3} pathLength={1} strokeDasharray={1}
                  strokeDashoffset={1 - d} />
                <path d={side === 0 ? "M12 20 H28 M20 12 V28" : "M12 20 H28"} stroke={col} strokeWidth={4} strokeLinecap="round"
                  fill="none" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - ramp(frame, at + 5, 10)} />
              </svg>
              <div style={{ flex: 1, minWidth: 0 }}>
                {lines(txt, 28).slice(0, 2).map((ln, li) => (
                  <Rise key={li} at={at + 3 + li * 3} out={qAt}>
                    <span style={{ display: "block", fontFamily: LABEL, fontWeight: 700, fontSize: 38 * k, lineHeight: 1.08,
                      color: "#fff", letterSpacing: "0.01em" }}>{ln}</span>
                  </Rise>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    );
  };
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 40 * k }}>
          {overlay.text ? (
            <div style={{ opacity: 1 - exit }}><Heading text={overlay.text} accent={accent} center size={58} /></div>
          ) : null}
          <div style={{ display: "flex", alignItems: "stretch", gap: 50 * k }}>
            {column(pros, 0)}
            <div style={{ position: "relative", width: 18 * k, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <div style={{ width: 2 * k, height: `${(dv * 100).toFixed(2)}%`,
                background: "linear-gradient(180deg, rgba(255,255,255,0), rgba(255,255,255,.55) 20%, rgba(255,255,255,.55) 80%, rgba(255,255,255,0))" }} />
              <div style={{ position: "absolute", width: 16 * k, height: 16 * k, background: accent,
                boxShadow: `0 0 ${14 * k}px ${accent}`,
                transform: `rotate(45deg) scale(${(Math.max(0, ramp(frame, 12, 12, backOut)) * (1 - exit)).toFixed(4)})` }} />
            </div>
            {column(cons, 1)}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 4. top countdown
/**
 * A countdown: a giant rank numeral on the left rolls 5 > 4 > 3 > 2 > 1 (with
 * motion blur) while the rows fill the list from the bottom up; number one
 * lands last in its enlarged slot at the top, the accent wiping through it
 * with a glow flash, and the others dim.
 */
const TopCountdown: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit();
  const rows = rowsOf(overlay.items, 5);
  if (rows.length < 2) return null;
  const n = rows.length;
  const t0 = Math.round(fps * 0.35);
  const step = Math.max(9, Math.min(Math.round(fps * 0.7), Math.floor((durationInFrames * 0.5) / n)));
  const revealAt = (i: number) => t0 + (n - 1 - i) * step + (i === 0 ? 6 : 0);
  const posAt = (f: number) => {
    let s = 0;
    for (let j = 1; j < n; j++) s += ramp(f, revealAt(n - 1 - j), 12);
    return s;
  };
  const pos = posAt(frame);
  const speed = Math.abs(pos - posAt(frame - 1));
  const NH = 190 * k;
  const end = durationInFrames - 18;
  const win = ramp(frame, revealAt(0), 18, backOut);
  const winOn = ramp(frame, revealAt(0), 10);
  const numIn = ramp(frame, revealAt(n - 1) - 2, 14);
  const numOut = ramp(frame, end - 2, 10, expoIn);
  const RH = 82 * k, WH = 148 * k, G = 14 * k, LW = 880 * k;
  const topOf = (i: number) => (i === 0 ? 0 : WH + G + (i - 1) * (RH + G));
  const listH = WH + (n - 1) * (RH + G);
  const suffix = overlay.suffix || "";
  const prefix = overlay.prefix || "";
  const strip = Array.from({ length: n }, (_, j) => n - j);
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 36 * k }}>
          {overlay.text ? (
            <div style={{ opacity: 1 - exit }}><Heading text={overlay.text} accent={accent} size={56} /></div>
          ) : null}
          <div style={{ display: "flex", alignItems: "center", gap: 70 * k }}>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 6 * k, width: 250 * k }}>
              <Rise at={revealAt(n - 1) - 4} out={end - 4}>
                <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: 26 * k, letterSpacing: "0.3em",
                  color: "rgba(255,255,255,.72)" }}>{cap(overlay.label || "Rank")}</span>
              </Rise>
              <div style={{ display: "flex", alignItems: "flex-start", height: NH, overflow: "hidden" }}>
                <span style={{ display: "block", fontFamily: DISPLAY, fontSize: NH * 0.4, lineHeight: 1, color: accent,
                  marginTop: NH * 0.1, marginRight: 8 * k, transform: `translateY(${f1((1 - numIn - numOut) * NH)}px)` }}>#</span>
                <div style={{ transform: `translateY(${f1(-pos * NH + (1 - numIn) * NH - numOut * NH)}px)`,
                  filter: speed > 0.02 ? `blur(${f1(Math.min(6, speed * 14) * k)}px)` : undefined }}>
                  {strip.map((v) => (
                    <div key={v} style={{ height: NH, fontFamily: DISPLAY, fontSize: NH, lineHeight: 1,
                      color: v === 1 ? accent : "#fff", textShadow: "0 8px 30px rgba(0,0,0,.45)" }}>{v}</div>
                  ))}
                </div>
              </div>
              <div style={{ display: "flex", gap: 10 * k, marginTop: 8 * k, opacity: numIn * (1 - numOut) }}>
                {strip.map((v) => {
                  const lit = ramp(frame, revealAt(v - 1), 8);
                  return (
                    <div key={v} style={{ width: 12 * k, height: 12 * k, borderRadius: "50%",
                      background: lit > 0.5 ? (v === 1 ? accent : "#fff") : "rgba(255,255,255,.22)",
                      transform: `scale(${(0.7 + 0.3 * lit).toFixed(3)})` }} />
                  );
                })}
              </div>
            </div>
            <div style={{ position: "relative", width: LW, height: listH }}>
              {rows.map((r, i) => {
                const at = revealAt(i);
                const isWin = i === 0;
                const p = ramp(frame, at, 16);
                const q = ramp(frame, end + i * 1.5, 10, expoIn);
                const dim = isWin ? 0 : 0.42 * winOn;
                const h = isWin ? WH : RH;
                const wipe = isWin ? ramp(frame, at, 12, inOut) : 0;
                const flash = isWin ? 1 - ramp(frame, at + 4, 26) : 0;
                const sc = isWin ? 1.28 - 0.28 * win : 1;
                const val = r.value;
                return (
                  <div key={i} style={{ position: "absolute", left: 0, top: topOf(i), width: LW, height: h, display: "flex",
                    alignItems: "center", gap: 26 * k, padding: `0 ${30 * k}px 0 ${24 * k}px`, borderRadius: 10 * k,
                    overflow: "hidden", background: isWin ? "rgba(255,255,255,.06)" : "rgba(255,255,255,.08)",
                    borderLeft: isWin ? "none" : `${4 * k}px solid rgba(255,255,255,.5)`,
                    boxShadow: isWin && p > 0
                      ? `0 ${20 * k}px ${50 * k}px rgba(0,0,0,.45), 0 0 ${f1((24 + 70 * flash) * k)}px ${accent}${hexA(0.3 + 0.45 * flash)}`
                      : "none",
                    opacity: Math.min(1, p * 2) * (1 - dim) * (1 - q),
                    transform: `translateX(${f1(((1 - p) * 80 + q * 140) * k)}px) scale(${sc.toFixed(4)})`,
                    transformOrigin: "0% 50%" }}>
                    {isWin ? (
                      <div style={{ position: "absolute", inset: 0,
                        background: `linear-gradient(100deg, ${accent} 0%, ${accent}d9 100%)`,
                        clipPath: `inset(0 ${((1 - wipe) * 100).toFixed(2)}% 0 0)` }} />
                    ) : null}
                    <Rise at={at + (isWin ? 4 : 2)} out={end + i * 1.5 - 3}
                      style={{ position: "relative", width: (isWin ? 120 : 86) * k, flexShrink: 0 }}>
                      <span style={{ display: "block", fontFamily: DISPLAY, fontSize: (isWin ? 104 : 58) * k, lineHeight: 1,
                        paddingTop: 6 * k, color: isWin ? INK : "rgba(255,255,255,.55)" }}>{pad2(i + 1)}</span>
                    </Rise>
                    <Rise at={at + (isWin ? 6 : 3)} out={end + i * 1.5 - 3} style={{ position: "relative", flex: 1, minWidth: 0 }}>
                      <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: (isWin ? 58 : 40) * k,
                        lineHeight: 1.02, color: isWin ? INK : "#fff", letterSpacing: "0.04em", whiteSpace: "nowrap",
                        overflow: "hidden", textOverflow: "ellipsis" }}>{cap(r.label)}</span>
                    </Rise>
                    {val !== null ? (
                      <div style={{ position: "relative", flexShrink: 0 }}>
                        <Odometer value={val} at={at + 4} frames={Math.round(fps * 0.9)} size={(isWin ? 76 : 50) * k}
                          color={isWin ? INK : "#fff"} prefix={r.prefix || prefix} suffix={sfx(r.suffix || suffix)}
                          suffixScale={0.45} suffixColor={isWin ? INK : accent} />
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

// ================================================================== 5. icon grid
const ICON = {
  drop: "M50 8 C50 8 18 46 18 64 A32 32 0 0 0 82 64 C82 46 50 8 50 8 Z",
  bolt: "M58 6 L20 56 H47 L40 94 L80 40 H53 Z",
  house: "M12 48 L50 14 L88 48 V88 H12 Z",
  coin: "M50 10 A40 40 0 1 1 49.99 10 Z",
  alert: "M50 10 L92 86 H8 Z",
  leaf: "M18 84 C18 40 44 14 88 12 C86 56 62 84 18 84 Z",
  hex: "M50 8 L88 30 V70 L50 92 L12 70 V30 Z",
  diamond: "M50 6 L94 50 L50 94 L6 50 Z",
  circle: "M50 12 A38 38 0 1 1 49.99 12 Z",
  square: "M16 16 H84 V84 H16 Z",
};
type IconKey = keyof typeof ICON;
const DETAIL: Record<IconKey, string> = {
  drop: "M34 64 A16 16 0 0 0 50 80",
  bolt: "",
  house: "M40 88 V62 H60 V88",
  coin: "M50 26 V74 M61 38 C58 32 39 31 39 42 C39 52 61 48 61 58 C61 69 41 69 38 62",
  alert: "M50 38 V60 M50 71 V72",
  leaf: "M18 84 L62 40",
  hex: "M50 30 L68 40 V60 L50 70 L32 60 V40 Z",
  diamond: "M50 30 L70 50 L50 70 L30 50 Z",
  circle: "M50 34 A16 16 0 1 1 49.99 34 Z",
  square: "M34 34 H66 V66 H34 Z",
};
const pickIcon = (s: string, i: number): IconKey => {
  const t = s.toLowerCase();
  if (/water|rain|river|lake|drink|drought|aquifer|reservoir|snow|flood|ocean|sea\b/.test(t)) return "drop";
  if (/power|energy|electric|grid|heat|fuel|pump/.test(t)) return "bolt";
  if (/home|house|city|town|famil|housing|communit|village/.test(t)) return "house";
  if (/cost|price|money|\$|dollar|fund|budget|bill|pay|tax|profit/.test(t)) return "coin";
  if (/risk|danger|warn|crisis|collapse|toxic|contamin|poison|disease|lead\b/.test(t)) return "alert";
  if (/farm|crop|food|grow|harvest|plant|forest|soil|cattle/.test(t)) return "leaf";
  return (["hex", "diamond", "circle", "square"] as const)[i % 4];
};
const waveD = (y: number, a: number) =>
  `M-100 ${f1(y)} Q-75 ${f1(y - a)} -50 ${f1(y)} T0 ${f1(y)} T50 ${f1(y)} T100 ${f1(y)} T150 ${f1(y)} T200 ${f1(y)} V110 H-100 Z`;

/**
 * A crosshair draws out from the centre and splits a 2x2 grid; clockwise, each
 * cell's geometric line icon (picked from its words: a drop, a bolt, a house,
 * a coin, a warning, a leaf, else a hexagon / diamond / circle / square) draws
 * on and fills with a rippling accent liquid, its label and line rising beside it.
 */
const IconGrid: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit();
  const rows = rowsOf(overlay.items, 4);
  if (rows.length < 2) return null;
  const m = rows.length;
  const CW = 700 * k, CHh = 220 * k;
  const nr = m > 2 ? 2 : 1;
  const GW = 2 * CW, GH = nr * CHh;
  const cross = ramp(frame, 2, 22, inOut) * (1 - exit);
  const seq = (i: number) => (m === 4 && i === 2 ? 3 : m === 4 && i === 3 ? 2 : i);
  const t0 = Math.round(fps * 0.35);
  const step = Math.round(fps * 0.22);
  const uid = uidOf("lsig", overlay);
  const shift = (frame * 1.4) % 100;
  // Three cells: two on top, the third centred beneath (a T instead of a cross).
  const vH = m === 3 ? CHh : GH;
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 40 * k }}>
          {overlay.text ? (
            <div style={{ opacity: 1 - exit }}><Heading text={overlay.text} accent={accent} center size={58} /></div>
          ) : null}
          <div style={{ position: "relative", width: GW, height: GH }}>
            <div style={{ position: "absolute", left: CW - k, top: vH / 2 - (cross * vH) / 2, width: 2 * k, height: cross * vH,
              background: "linear-gradient(180deg, rgba(255,255,255,0), rgba(255,255,255,.42) 25%, rgba(255,255,255,.42) 75%, rgba(255,255,255,0))" }} />
            {nr === 2 ? (
              <div style={{ position: "absolute", top: CHh - k, left: CW - (cross * GW) / 2, height: 2 * k, width: cross * GW,
                background: "linear-gradient(90deg, rgba(255,255,255,0), rgba(255,255,255,.42) 25%, rgba(255,255,255,.42) 75%, rgba(255,255,255,0))" }} />
            ) : null}
            <div style={{ position: "absolute", left: CW - 9 * k, top: GH / 2 - 9 * k, width: 18 * k, height: 18 * k,
              background: accent, boxShadow: `0 0 ${16 * k}px ${accent}`,
              transform: `rotate(45deg) scale(${(Math.max(0, ramp(frame, 10, 14, backOut)) * (1 - exit)).toFixed(4)})` }} />
            {rows.map((r, i) => {
              const col = i % 2, row = Math.floor(i / 2);
              const at = t0 + seq(i) * step;
              const draw = ramp(frame, at, 18, inOut);
              const lvl = ramp(frame, at + 8, 26, inOut);
              const det = ramp(frame, at + 18, 14, inOut);
              const pop = ramp(frame, at, 16, backOut);
              const qAt = durationInFrames - 17 + seq(i) * 1.5;
              const q = ramp(frame, qAt, 10, expoIn);
              const key = pickIcon(`${r.label} ${r.text}`, i);
              const cellLeft = m === 3 && i === 2 ? CW / 2 : col * CW;
              const bob = Math.sin((frame + i * 13) / (fps * 0.8)) * 3 * k;
              const surf = 92 - 58 * lvl + Math.sin(frame / (fps * 0.5) + i) * 1.2;
              const body = lines(r.text, 34).slice(0, 2);
              return (
                <div key={i} style={{ position: "absolute", left: cellLeft, top: row * CHh, width: CW, height: CHh,
                  display: "flex", alignItems: "center", gap: 34 * k, padding: `0 ${50 * k}px` }}>
                  <div style={{ position: "relative", width: 116 * k, height: 116 * k, flexShrink: 0,
                    transform: `translateY(${f1(bob)}px) scale(${(Math.max(0, pop) * (1 - q)).toFixed(4)})` }}>
                    <div style={{ position: "absolute", inset: -40 * k, borderRadius: "50%", opacity: lvl,
                      background: `radial-gradient(circle, ${accent}38 0%, ${accent}00 65%)` }} />
                    <svg width={116 * k} height={116 * k} viewBox="0 0 100 100" style={{ position: "absolute", inset: 0, overflow: "visible" }}>
                      <defs>
                        <clipPath id={`${uid}-${i}`}><path d={ICON[key]} /></clipPath>
                      </defs>
                      {lvl > 0.001 ? (
                        <g clipPath={`url(#${uid}-${i})`}>
                          <path d={waveD(surf, 4 * lvl)} fill={accent} transform={`translate(${f1(shift)} 0)`} />
                        </g>
                      ) : null}
                      <path d={ICON[key]} fill="none" stroke="#fff" strokeWidth={4.5} strokeLinejoin="round" strokeLinecap="round"
                        pathLength={1} strokeDasharray={1} strokeDashoffset={1 - draw} />
                      {DETAIL[key] ? (
                        <path d={DETAIL[key]} fill="none" stroke="#fff" strokeWidth={4} strokeLinecap="round" strokeLinejoin="round"
                          pathLength={1} strokeDasharray={1} strokeDashoffset={1 - det} />
                      ) : null}
                    </svg>
                  </div>
                  <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 6 * k }}>
                    <Rise at={at + 6} out={qAt}>
                      <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: 42 * k, lineHeight: 1.02,
                        color: "#fff", letterSpacing: "0.04em", whiteSpace: "nowrap", overflow: "hidden",
                        textOverflow: "ellipsis" }}>{cap(r.label)}</span>
                    </Rise>
                    {body.map((ln, li) => (
                      <Rise key={li} at={at + 10 + li * 3} out={qAt}>
                        <span style={{ display: "block", fontFamily: INTER, fontWeight: 400, fontSize: 24 * k, lineHeight: 1.28,
                          color: "rgba(255,255,255,.74)" }}>{ln}</span>
                      </Rise>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 6. process chevrons
/**
 * Interlocking chevrons draw their outlines left to right, then light up in
 * turn: the accent pours through each one, the active step lifts with a glow
 * and its number flips to ink, its label brightens below; once all are lit a
 * sheen runs through the whole row.
 */
const ProcessChevrons: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit();
  const rows = rowsOf(overlay.items, 5);
  if (rows.length < 2) return null;
  const n = rows.length;
  const W = 1640 * k, H = 150 * k, N = 44 * k, G = 12 * k;
  const w = (W + (n - 1) * (N - G)) / n;
  const xOf = (i: number) => i * (w - N + G);
  const shape = (i: number) => {
    const x = xOf(i);
    const pts: [number, number][] = [[x, 0], [x + w - N, 0], [x + w, H / 2], [x + w - N, H], [x, H]];
    if (i > 0) pts.push([x + N, H / 2]);
    return `M${pts.map((p) => `${f1(p[0])} ${f1(p[1])}`).join(" L")} Z`;
  };
  const midX = (i: number) => (i === 0 ? xOf(i) + (w - N / 2) / 2 : xOf(i) + w / 2);
  const bodyW = w - N - 10 * k;
  const drawAt = (i: number) => 3 + i * 4;
  const t0 = Math.round(fps * 0.8);
  const lstep = Math.max(8, Math.min(Math.round(fps * 0.75), Math.floor((durationInFrames - t0 - 34) / n)));
  const lightAt = (i: number) => t0 + i * lstep;
  const lit = (i: number) => ramp(frame, lightAt(i), 14, inOut);
  const lift = (i: number) =>
    ramp(frame, lightAt(i), 10) * (i < n - 1 ? 1 - ramp(frame, lightAt(i + 1), 10) : 1) * (1 - exit);
  const end = durationInFrames - 18;
  const uid = uidOf("lspc", overlay);
  const sheen = ramp(frame, lightAt(n - 1) + 14, 26, inOut);
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 56 * k }}>
          {overlay.text ? (
            <div style={{ opacity: 1 - exit }}><Heading text={overlay.text} accent={accent} center size={58} /></div>
          ) : null}
          <div style={{ position: "relative", width: W, height: H + 220 * k }}>
            <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
              <defs>
                <linearGradient id={`${uid}g`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={accent} />
                  <stop offset="100%" stopColor={accent} stopOpacity={0.8} />
                </linearGradient>
                <linearGradient id={`${uid}s`} x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%" stopColor="#fff" stopOpacity={0} />
                  <stop offset="50%" stopColor="#fff" stopOpacity={0.5} />
                  <stop offset="100%" stopColor="#fff" stopOpacity={0} />
                </linearGradient>
                {rows.map((_, i) => (
                  <clipPath key={`c${i}`} id={`${uid}c${i}`}>
                    <rect x={xOf(i) - 2 * k} y={-4 * k} width={Math.max(0, (w + 4 * k) * lit(i))} height={H + 8 * k} />
                  </clipPath>
                ))}
                {rows.map((_, i) => (
                  <clipPath key={`s${i}`} id={`${uid}s${i}`}><path d={shape(i)} /></clipPath>
                ))}
              </defs>
              {rows.map((_, i) => {
                const d = ramp(frame, drawAt(i), 18, inOut);
                const lf = lift(i);
                const q = ramp(frame, end + i * 1.5, 10, expoIn);
                return (
                  <g key={i} transform={`translate(0 ${f1(-lf * 8 * k - q * 20 * k)})`} opacity={1 - q}>
                    <path d={shape(i)} fill={`rgba(255,255,255,${(0.08 * d).toFixed(3)})`} stroke="rgba(255,255,255,.5)"
                      strokeWidth={2 * k} strokeLinejoin="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - d} />
                    <path d={shape(i)} fill={`url(#${uid}g)`} clipPath={`url(#${uid}c${i})`}
                      style={lf > 0.05 ? { filter: `drop-shadow(0 0 ${f1(18 * k * lf)}px ${accent})` } : undefined} />
                    {sheen > 0 && sheen < 1 ? (
                      <rect x={-0.3 * W + sheen * 1.6 * W} y={0} width={0.22 * W} height={H} fill={`url(#${uid}s)`}
                        clipPath={`url(#${uid}s${i})`} />
                    ) : null}
                  </g>
                );
              })}
            </svg>
            {rows.map((r, i) => {
              const L = lit(i);
              const lf = lift(i);
              const q = ramp(frame, end + i * 1.5, 10, expoIn);
              const out = end + i * 1.5 - 3;
              const lbl = lines(cap(r.label), 16).slice(0, 2);
              const body = lines(r.text, 22).slice(0, 2);
              return (
                <React.Fragment key={i}>
                  <div style={{ position: "absolute", left: midX(i) - 70 * k, top: -lf * 8 * k, width: 140 * k, height: H,
                    display: "flex", alignItems: "center", justifyContent: "center" }}>
                    <Rise at={drawAt(i) + 8} out={out}>
                      <span style={{ display: "block", fontFamily: DISPLAY, fontSize: 66 * k, lineHeight: 1, paddingTop: 4 * k,
                        color: L > 0.5 ? INK : "rgba(255,255,255,.82)" }}>{pad2(i + 1)}</span>
                    </Rise>
                  </div>
                  <div style={{ position: "absolute", left: midX(i) - bodyW / 2, top: H + 28 * k, width: bodyW, display: "flex",
                    flexDirection: "column", alignItems: "center", textAlign: "center", gap: 4 * k }}>
                    <div style={{ width: 44 * k * (0.25 + 0.75 * L), height: 4 * k, marginBottom: 10 * k,
                      background: L > 0.02 ? accent : "rgba(255,255,255,.35)",
                      opacity: ramp(frame, drawAt(i) + 8, 10) * (1 - q) }} />
                    {lbl.map((ln, li) => (
                      <Rise key={li} at={drawAt(i) + 10 + li * 3} out={out}>
                        <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: 34 * k, lineHeight: 1.04,
                          letterSpacing: "0.05em", color: `rgba(255,255,255,${(0.62 + 0.38 * L).toFixed(3)})` }}>{ln}</span>
                      </Rise>
                    ))}
                    {body.map((ln, li) => (
                      <Rise key={`b${li}`} at={drawAt(i) + 14 + li * 3} out={out}>
                        <span style={{ display: "block", fontFamily: INTER, fontWeight: 400, fontSize: 24 * k, lineHeight: 1.26,
                          color: "rgba(255,255,255,.7)" }}>{ln}</span>
                      </Rise>
                    ))}
                  </div>
                </React.Fragment>
              );
            })}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 7. cycle loop
/**
 * Three to five steps round a ring: the nodes pop in clockwise, arcs draw
 * between them and grow arrowheads, accent dashes then flow round the loop
 * while a comet circles it and lights each node it passes; a dashed outer
 * ring turns slowly, the title sits in the middle.
 */
const CycleLoop: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit();
  const rows = rowsOf(overlay.items, 5);
  if (rows.length < 3) return null;
  const n = rows.length;
  // Sized so the top / bottom labels stay inside the 90 px safe area even at the end of the hold push.
  const R = 228 * k, r = 60 * k, PAD = 30 * k;
  const S = 2 * (R + r + PAD);
  const c = S / 2;
  const ang = (i: number) => -Math.PI / 2 + (i * TAU) / n;
  const P = (a: number, rad = R): [number, number] => [c + rad * Math.cos(a), c + rad * Math.sin(a)];
  const gap = (r + 18 * k) / R;
  const nodeAt = (i: number) => Math.round(fps * 0.3) + i * 5;
  const arcAt = (i: number) => nodeAt(n - 1) + 6 + i * 6;
  const orbitAt = arcAt(n - 1) + 16;
  const period = Math.round(fps * 3);
  const ca = ang(0) + (Math.max(0, frame - orbitAt) / period) * TAU;
  const orbit = ramp(frame, orbitAt, 12) * (1 - exit);
  const end = durationInFrames - 18;
  const title = lines(cap(overlay.text || ""), 12).slice(0, 3);
  const tSize = (title.length > 2 ? 46 : 56) * k;
  const ring = ramp(frame, 0, 24, inOut) * (1 - exit);
  const dAng = (a: number, b: number) => {
    let d = (a - b) % TAU;
    if (d < 0) d += TAU;
    return Math.min(d, TAU - d);
  };
  return (
    <AbsoluteFill>
      <Scrim ov={overlay} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ position: "relative", width: S, height: S }}>
          <svg width={S} height={S} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
            <circle cx={c} cy={c} r={R + r + 14 * k} fill="none" stroke="rgba(255,255,255,.18)" strokeWidth={2 * k}
              strokeDasharray={`${f1(2 * k)} ${f1(12 * k)}`} transform={`rotate(${f1(frame * 0.3)} ${f1(c)} ${f1(c)})`}
              opacity={ring} />
            <circle cx={c} cy={c} r={R - r - 26 * k} fill="none" stroke="rgba(255,255,255,.1)" strokeWidth={2 * k}
              strokeDasharray={`${f1(30 * k)} ${f1(12 * k)}`} transform={`rotate(${f1(-frame * 0.2)} ${f1(c)} ${f1(c)})`}
              opacity={ring} />
            {rows.map((_, i) => {
              const a0 = ang(i) + gap, a1 = ang(i) + TAU / n - gap;
              const [x0, y0] = P(a0);
              const [x1, y1] = P(a1);
              const d = `M${f1(x0)} ${f1(y0)} A${f1(R)} ${f1(R)} 0 0 1 ${f1(x1)} ${f1(y1)}`;
              const dr = ramp(frame, arcAt(i), 14, inOut);
              const flow = ramp(frame, arcAt(i) + 12, 10) * (1 - exit);
              const tx = -Math.sin(a1), ty = Math.cos(a1);
              const nx = Math.cos(a1), ny = Math.sin(a1);
              const bx = x1 - tx * 9 * k, by = y1 - ty * 9 * k;
              const head = `M${f1(x1 + tx * 9 * k)} ${f1(y1 + ty * 9 * k)} L${f1(bx + nx * 10 * k)} ${f1(by + ny * 10 * k)} ` +
                `L${f1(bx - nx * 10 * k)} ${f1(by - ny * 10 * k)} Z`;
              const hp = Math.max(0, Math.min(1, ramp(frame, arcAt(i) + 11, 8, backOut))) * (1 - exit);
              return (
                <g key={i}>
                  <path d={d} fill="none" stroke="rgba(255,255,255,.4)" strokeWidth={3 * k} strokeLinecap="round"
                    pathLength={1} strokeDasharray={1} strokeDashoffset={exit > 0 ? -exit : 1 - dr} />
                  {flow > 0 ? (
                    <path d={d} fill="none" stroke={accent} strokeWidth={3.5 * k} strokeLinecap="round"
                      strokeDasharray={`${f1(5 * k)} ${f1(16 * k)}`} strokeDashoffset={f1(-frame * 1.6 * k)} opacity={flow} />
                  ) : null}
                  <path d={head} fill={accent} opacity={hp} />
                </g>
              );
            })}
            {orbit > 0 ? (
              <g>
                <circle cx={P(ca)[0]} cy={P(ca)[1]} r={22 * k} fill={accent} opacity={0.22 * orbit} />
                {Array.from({ length: 8 }, (_, t) => {
                  const [x, y] = P(ca - t * 0.065);
                  return <circle key={t} cx={x} cy={y} r={(8 - t * 0.8) * k} fill={t === 0 ? "#fff" : accent}
                    opacity={orbit * (1 - t / 8)} />;
                })}
              </g>
            ) : null}
            {rows.map((_, i) => {
              const [x, y] = P(ang(i));
              const p = ramp(frame, nodeAt(i), 16, backOut);
              const q = ramp(frame, end + i * 1.5, 10, expoIn);
              const s = Math.max(0, p) * (1 - q);
              const g = frame >= orbitAt ? Math.max(0, 1 - dAng(ca, ang(i)) / 0.5) * orbit : 0;
              return (
                <g key={i} transform={`translate(${f1(x)} ${f1(y)}) scale(${s.toFixed(4)})`}>
                  <circle r={r} cy={8 * k} fill="rgba(0,0,0,.35)" />
                  <circle r={r + 12 * k + 6 * k * g} fill="none" stroke={accent} strokeWidth={3 * k} opacity={g} />
                  <circle r={r} fill="#f4f4f6" />
                  <circle r={r} fill={accent} opacity={g * 0.9} />
                  <text textAnchor="middle" dominantBaseline="central" y={3 * k} fontFamily={DISPLAY} fontSize={54 * k}
                    fill={INK}>{pad2(i + 1)}</text>
                </g>
              );
            })}
          </svg>
          {title.length ? (
            <div style={{ position: "absolute", left: c - 170 * k, top: c, width: 340 * k, transform: "translateY(-50%)",
              display: "flex", flexDirection: "column", alignItems: "center" }}>
              {title.map((ln, li) => (
                <LetterLine key={li} text={ln} at={4 + li * 4} step={0.8} style={{ fontFamily: DISPLAY, fontSize: tSize,
                  lineHeight: 1, color: "#fff", letterSpacing: "0.04em", textAlign: "center",
                  textShadow: "0 6px 24px rgba(0,0,0,.5)" }} />
              ))}
            </div>
          ) : null}
          {rows.map((row, i) => {
            const a = ang(i);
            const ux = Math.cos(a), uy = Math.sin(a);
            const la = R + r + 32 * k;
            const ax = c + la * ux, ay = c + la * uy;
            const side = ux > 0.3 ? "l" : ux < -0.3 ? "r" : "c";
            const tx = side === "l" ? "0%" : side === "r" ? "-100%" : "-50%";
            const ty = side === "c" ? (uy < 0 ? "-100%" : "0%") : "-50%";
            const align = side === "l" ? "left" : side === "r" ? "right" : "center";
            const body = lines(row.text, 25).slice(0, 2);
            const out = end + i * 1.5 - 2;
            const at = nodeAt(i) + 6;
            return (
              <div key={i} style={{ position: "absolute", left: ax, top: ay, width: 330 * k, transform: `translate(${tx}, ${ty})`,
                textAlign: align, display: "flex", flexDirection: "column", gap: 4 * k }}>
                <Rise at={at} out={out}>
                  <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: 36 * k, lineHeight: 1.04,
                    letterSpacing: "0.06em", color: "#fff", textShadow: "0 3px 14px rgba(0,0,0,.5)" }}>{cap(row.label)}</span>
                </Rise>
                {body.map((ln, li) => (
                  <Rise key={li} at={at + 4 + li * 3} out={out}>
                    <span style={{ display: "block", fontFamily: INTER, fontWeight: 400, fontSize: 24 * k, lineHeight: 1.26,
                      color: "rgba(255,255,255,.76)", textShadow: "0 2px 10px rgba(0,0,0,.5)" }}>{ln}</span>
                  </Rise>
                ))}
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 8. pyramid levels
/**
 * A pyramid built bottom-up on the dark case desktop: each trapezoid level
 * drops onto the one below and settles (a flash line where it lands), the
 * two faces lit differently, the apex in the accent; a leader draws out from
 * each level to its label. The first item is the apex.
 */
const PyramidLevels: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit();
  const bg = ramp(frame, 0, 8) * (1 - ramp(frame, durationInFrames - 9, 8));
  const rows = rowsOf(overlay.items, 5);
  if (rows.length < 2) return null;
  const n = rows.length;
  const PH = 540 * k, PW = 780 * k, G = 10 * k, LX = 66 * k, LBW = 440 * k;
  const lh = (PH - (n - 1) * G) / n;
  const cx = PW / 2;
  const wAt = (y: number) => (PW * Math.max(0, y)) / PH;
  const t0 = Math.round(fps * 0.35);
  const step = Math.max(6, Math.min(Math.round(fps * 0.42), Math.floor((durationInFrames * 0.4) / n)));
  const atOf = (j: number) => t0 + (n - 1 - j) * step;
  const end = durationInFrames - 18;
  const SHADES = ["#f4f4f6", "#d4d5da", "#b1b3ba", "#8c8f97"];
  const fillOf = (j: number) => (j === 0 ? accent : SHADES[Math.min(SHADES.length - 1, j - 1)]);
  const inkOf = (j: number) => (j >= 4 ? "#fff" : INK);
  const suffix = overlay.suffix || "";
  const glow = ramp(frame, atOf(n - 1) + 8, 16) * (1 - exit);
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: bg }}><CaseBackdrop tone="dark" seed={4} /></AbsoluteFill>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 44 * k }}>
          {overlay.text ? (
            <div style={{ opacity: 1 - exit }}><Heading text={overlay.text} accent={accent} size={58} /></div>
          ) : null}
          <div style={{ position: "relative", width: PW + LX + LBW, height: PH }}>
            <div style={{ position: "absolute", left: cx - PW * 0.75, top: PH - 70 * k, width: PW * 1.5, height: 140 * k,
              opacity: glow, background: `radial-gradient(ellipse at center, ${accent}44 0%, ${accent}00 70%)` }} />
            <svg width={PW} height={PH} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
              {rows.map((_, j) => {
                const yt = j * (lh + G), yb = yt + lh;
                const wt = wAt(yt), wb = wAt(yb);
                const at = atOf(j);
                const p = ramp(frame, at, 18, backOut);
                const o = ramp(frame, at, 6);
                const q = ramp(frame, end + j * 1.5, 10, expoIn);
                const dy = (1 - p) * -120 * k - q * 30 * k;
                const d = `M${f1(cx - wt / 2)} ${f1(yt)} L${f1(cx + wt / 2)} ${f1(yt)} L${f1(cx + wb / 2)} ${f1(yb)} ` +
                  `L${f1(cx - wb / 2)} ${f1(yb)} Z`;
                const dr = `M${f1(cx)} ${f1(yt)} L${f1(cx + wt / 2)} ${f1(yt)} L${f1(cx + wb / 2)} ${f1(yb)} L${f1(cx)} ${f1(yb)} Z`;
                const e = ramp(frame, at + 12, 14);
                const ym = yt + lh / 2;
                const x1 = cx + wAt(ym) / 2 + 12 * k;
                const x2 = PW + LX - 16 * k;
                const lp = ramp(frame, at + 10, 12, inOut) * (1 - q);
                return (
                  <g key={j}>
                    <g transform={`translate(0 ${f1(dy)})`} opacity={o * (1 - q)}>
                      <path d={d} fill={fillOf(j)} />
                      <path d={dr} fill="rgba(0,0,0,.16)" />
                      {wt > 0 ? (
                        <path d={`M${f1(cx - wt / 2)} ${f1(yt)} L${f1(cx + wt / 2)} ${f1(yt)}`} stroke="rgba(255,255,255,.75)"
                          strokeWidth={2 * k} />
                      ) : null}
                    </g>
                    {e > 0 && e < 1 ? (
                      <line x1={cx - (wb * (0.9 + 0.5 * e)) / 2} x2={cx + (wb * (0.9 + 0.5 * e)) / 2} y1={yb + G / 2} y2={yb + G / 2}
                        stroke="#fff" strokeWidth={2 * k} opacity={(1 - e) * 0.8} />
                    ) : null}
                    {lp > 0 ? (
                      <g>
                        <line x1={x1} x2={x1 + (x2 - x1) * lp} y1={ym} y2={ym} stroke="rgba(255,255,255,.55)" strokeWidth={2 * k}
                          strokeDasharray={`${f1(6 * k)} ${f1(6 * k)}`} />
                        <circle cx={x1} cy={ym} r={5 * k} fill={j === 0 ? accent : "#fff"} />
                      </g>
                    ) : null}
                  </g>
                );
              })}
            </svg>
            {rows.map((r, j) => {
              const yt = j * (lh + G);
              const ym = yt + lh * (j === 0 ? 0.64 : 0.5);
              const wm = wAt(ym);
              const at = atOf(j);
              const p = ramp(frame, at, 18, backOut);
              const q = ramp(frame, end + j * 1.5, 10, expoIn);
              const dy = (1 - p) * -120 * k - q * 30 * k;
              const val = r.value;
              const chars = val !== null ? `${r.prefix}${Math.round(val)}${r.suffix || suffix}`.length : 2;
              const size = Math.min(lh * 0.5, 64 * k, (wm * 0.78) / (0.46 * Math.max(2, chars)));
              if (size < 20 * k) return null;
              return (
                <div key={j} style={{ position: "absolute", left: cx - 160 * k, top: ym, width: 320 * k, display: "flex",
                  justifyContent: "center", transform: `translateY(calc(-50% + ${f1(dy)}px))`,
                  opacity: ramp(frame, at + 4, 8) * (1 - q) }}>
                  {val !== null ? (
                    <Odometer value={val} at={at + 4} frames={Math.round(fps * 0.9)} size={size} color={inkOf(j)}
                      prefix={r.prefix} suffix={sfx(r.suffix || suffix)} suffixScale={0.5} />
                  ) : (
                    <span style={{ fontFamily: DISPLAY, fontSize: size, lineHeight: 1, color: inkOf(j), opacity: 0.6,
                      paddingTop: size * 0.06 }}>{pad2(j + 1)}</span>
                  )}
                </div>
              );
            })}
            {rows.map((r, j) => {
              const ym = j * (lh + G) + lh / 2;
              const at = atOf(j) + 12;
              const out = end + j * 1.5 - 2;
              const body = lines(r.text, 33).slice(0, n > 4 ? 1 : 2);
              return (
                <div key={j} style={{ position: "absolute", left: PW + LX, top: ym, width: LBW, transform: "translateY(-50%)",
                  display: "flex", flexDirection: "column", gap: 2 * k }}>
                  <Rise at={at} out={out}>
                    <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: 38 * k, lineHeight: 1.02,
                      letterSpacing: "0.05em", color: j === 0 ? accent : "#fff", whiteSpace: "nowrap", overflow: "hidden",
                      textOverflow: "ellipsis" }}>{cap(r.label)}</span>
                  </Rise>
                  {body.map((ln, li) => (
                    <Rise key={li} at={at + 4 + li * 3} out={out}>
                      <span style={{ display: "block", fontFamily: INTER, fontWeight: 400, fontSize: 24 * k, lineHeight: 1.26,
                        color: "rgba(255,255,255,.76)" }}>{ln}</span>
                    </Rise>
                  ))}
                </div>
              );
            })}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 9. funnel stages
/**
 * A funnel on a graphite gradient mesh: the stage outlines draw, then the
 * accent pours down through it stage by stage (a bright front leading each
 * fill), each stage's value rolling as the pour reaches it, the labels
 * rising on the left and the drop-off between stages popping on the right.
 * Widths follow the values when every stage has one.
 */
const FunnelStages: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const k = useK();
  const hold = useHold();
  const exit = useExit();
  const bg = ramp(frame, 0, 8) * (1 - ramp(frame, durationInFrames - 9, 8));
  const rows = rowsOf(overlay.items, 5);
  if (rows.length < 2) return null;
  const n = rows.length;
  const allVals = rows.every((r) => r.value !== null && r.value > 0);
  const vmax = allVals ? Math.max(...rows.map((r) => r.value || 0)) : 1;
  const FW = 800 * k, G = 14 * k, LW = 420 * k, GX = 40 * k, RW = 230 * k;
  const BH = Math.min(118 * k, (600 * k - (n - 1) * G) / n);
  const widths: number[] = [];
  for (let j = 0; j < n; j++) {
    const v = rows[j].value;
    const raw = allVals && v !== null && vmax > 0
      ? FW * Math.max(0.24, Math.min(1, v / vmax))
      : FW * (1 - (0.58 * j) / Math.max(1, n - 1));
    widths.push(j ? Math.min(raw, widths[j - 1]) : raw);
  }
  widths.push(widths[n - 1] * 0.72);
  const cx = FW / 2;
  const t0 = Math.round(fps * 0.45);
  const step = Math.max(7, Math.min(Math.round(fps * 0.55), Math.floor((durationInFrames * 0.42) / n)));
  const fillAt = (j: number) => t0 + j * step;
  const end = durationInFrames - 18;
  const uid = uidOf("lsfn", overlay);
  const suffix = overlay.suffix || "";
  const prefix = overlay.prefix || "";
  const SH = ["#f3f3f5", "#dcdde1", "#c4c6cc", "#adb0b7"];
  const TH = n * BH + (n - 1) * G;
  const t = frame / fps;
  const b1x = 30 + 8 * Math.sin(t * 0.35), b1y = 30 + 6 * Math.cos(t * 0.3);
  const b2x = 72 + 7 * Math.cos(t * 0.28), b2y = 66 + 8 * Math.sin(t * 0.33);
  const band = (j: number) => {
    const yt = j * (BH + G), yb = yt + BH;
    const a = widths[j] / 2, b = widths[j + 1] / 2;
    return `M${f1(cx - a)} ${f1(yt)} L${f1(cx + a)} ${f1(yt)} L${f1(cx + b)} ${f1(yb)} L${f1(cx - b)} ${f1(yb)} Z`;
  };
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: bg, background:
        `radial-gradient(ellipse 55% 60% at ${f1(b1x)}% ${f1(b1y)}%, ${accent}30 0%, ${accent}00 70%), ` +
        `radial-gradient(ellipse 50% 55% at ${f1(b2x)}% ${f1(b2y)}%, ${CYAN}1c 0%, ${CYAN}00 70%), ` +
        "radial-gradient(ellipse at 50% 40%, #17191f 0%, #0b0c10 60%, #050507 100%)" }}>
        <svg width="100%" height="100%" style={{ position: "absolute", inset: 0 }}>
          <defs>
            <pattern id={`${uid}p`} width={64 * k} height={64 * k} patternUnits="userSpaceOnUse">
              <path d={`M${f1(64 * k)} 0 H0 V${f1(64 * k)}`} fill="none" stroke="rgba(255,255,255,.045)" strokeWidth={1} />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill={`url(#${uid}p)`} />
        </svg>
        <AbsoluteFill style={{ boxShadow: `inset 0 0 ${300 * k}px rgba(0,0,0,.7)` }} />
      </AbsoluteFill>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", transform: `scale(${hold})` }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 44 * k }}>
          {overlay.text ? (
            <div style={{ opacity: 1 - exit }}><Heading text={overlay.text} accent={accent} center size={58} /></div>
          ) : null}
          <div style={{ position: "relative", width: LW + GX + FW + RW, height: TH }}>
            <svg width={FW} height={TH} style={{ position: "absolute", left: LW + GX, top: 0, overflow: "visible" }}>
              <defs>
                <linearGradient id={`${uid}gl`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#fff" stopOpacity={0.45} />
                  <stop offset="60%" stopColor="#fff" stopOpacity={0} />
                </linearGradient>
                {rows.map((_, j) => {
                  const f = ramp(frame, fillAt(j), 16, inOut);
                  return (
                    <clipPath key={j} id={`${uid}c${j}`}>
                      <rect x={-10 * k} y={j * (BH + G)} width={FW + 20 * k} height={Math.max(0, BH * f)} />
                    </clipPath>
                  );
                })}
              </defs>
              {rows.map((r, j) => {
                const yt = j * (BH + G), yb = yt + BH;
                const d = ramp(frame, 2 + j * 3, 16, inOut);
                const f = ramp(frame, fillAt(j), 16, inOut);
                const q = ramp(frame, end + j * 1.5, 10, expoIn);
                const hw = (widths[j] + (widths[j + 1] - widths[j]) * f) / 2;
                const ym = yt + BH / 2;
                const edgeL = cx - (widths[j] + widths[j + 1]) / 4;
                const lp = ramp(frame, fillAt(j) + 2, 12, inOut) * (1 - q);
                const col = j === n - 1 ? accent : SH[Math.min(SH.length - 1, j)];
                return (
                  <g key={j} opacity={1 - q} transform={`translate(0 ${f1(-q * 16 * k)})`}>
                    <path d={band(j)} fill={`rgba(255,255,255,${(0.05 * d).toFixed(3)})`} stroke="rgba(255,255,255,.3)"
                      strokeWidth={2 * k} strokeLinejoin="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - d} />
                    <g clipPath={`url(#${uid}c${j})`}>
                      <path d={band(j)} fill={col} />
                      <path d={band(j)} fill={`url(#${uid}gl)`} />
                    </g>
                    {f > 0 && f < 1 ? (
                      <line x1={cx - hw} x2={cx + hw} y1={yt + BH * f} y2={yt + BH * f} stroke="#fff" strokeWidth={3 * k}
                        opacity={0.85} />
                    ) : null}
                    {lp > 0 ? (
                      <line x1={-GX + 12 * k} x2={-GX + 12 * k + (edgeL - 12 * k - (-GX + 12 * k)) * lp} y1={ym} y2={ym}
                        stroke="rgba(255,255,255,.3)" strokeWidth={2 * k} strokeDasharray={`${f1(4 * k)} ${f1(6 * k)}`} />
                    ) : null}
                    {j < n - 1 && r.value !== null && rows[j + 1].value !== null ? (
                      <line x1={cx + widths[j + 1] / 2 + 10 * k} x2={FW + 28 * k} y1={yb + G / 2} y2={yb + G / 2}
                        stroke="rgba(255,255,255,.3)" strokeWidth={2 * k} strokeDasharray={`${f1(4 * k)} ${f1(6 * k)}`}
                        opacity={ramp(frame, fillAt(j + 1) + 2, 10)} />
                    ) : null}
                  </g>
                );
              })}
            </svg>
            {rows.map((r, j) => {
              const ym = j * (BH + G) + BH / 2;
              const q = ramp(frame, end + j * 1.5, 10, expoIn);
              const at = fillAt(j);
              const size = Math.min(BH * 0.52, 70 * k);
              const out = end + j * 1.5 - 2;
              const body = lines(r.text, 30).slice(0, n > 4 ? 1 : 2);
              // The ink value shows as the pour front passes the middle of its stage (never ink on the empty outline).
              return (
                <React.Fragment key={j}>
                  <div style={{ position: "absolute", left: 0, top: ym, width: LW, transform: "translateY(-50%)", display: "flex",
                    flexDirection: "column", alignItems: "flex-end", textAlign: "right", gap: 2 * k }}>
                    <Rise at={at} out={out} style={{ maxWidth: LW }}>
                      <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: 36 * k, lineHeight: 1.02,
                        letterSpacing: "0.05em", color: j === n - 1 ? accent : "#fff", whiteSpace: "nowrap", overflow: "hidden",
                        textOverflow: "ellipsis" }}>{cap(r.label)}</span>
                    </Rise>
                    {body.map((ln, li) => (
                      <Rise key={li} at={at + 4 + li * 3} out={out}>
                        <span style={{ display: "block", fontFamily: INTER, fontWeight: 400, fontSize: 24 * k, lineHeight: 1.26,
                          color: "rgba(255,255,255,.72)" }}>{ln}</span>
                      </Rise>
                    ))}
                  </div>
                  <div style={{ position: "absolute", left: LW + GX + cx - 200 * k, top: ym, width: 400 * k, display: "flex",
                    justifyContent: "center", transform: `translateY(calc(-50% - ${f1(q * 16 * k)}px))`,
                    opacity: ramp(frame, at + 8, 7) * (1 - q) }}>
                    {r.value !== null ? (
                      <Odometer value={r.value} at={at + 6} frames={Math.round(fps * 0.9)} size={size} color={INK}
                        prefix={r.prefix || prefix} suffix={sfx(r.suffix || suffix)} suffixScale={0.5} />
                    ) : (
                      <span style={{ fontFamily: DISPLAY, fontSize: size, lineHeight: 1, color: INK, opacity: 0.55,
                        paddingTop: size * 0.06 }}>{pad2(j + 1)}</span>
                    )}
                  </div>
                </React.Fragment>
              );
            })}
            {rows.slice(0, -1).map((r, j) => {
              const a = r.value, b = rows[j + 1].value;
              if (a === null || b === null || a <= 0) return null;
              const pct = ((b - a) / a) * 100;
              const down = pct < 0;
              const col = down ? RED : GREEN;
              const p = ramp(frame, fillAt(j + 1) + 4, 14, backOut);
              const q = ramp(frame, end + j * 1.5, 10, expoIn);
              const y = (j + 1) * (BH + G) - G / 2;
              const mag = Math.abs(pct);
              const txt = `${down ? "▼" : "▲"} ${mag >= 10 ? Math.round(mag) : mag.toFixed(1)}%`;
              return (
                <div key={j} style={{ position: "absolute", left: LW + GX + FW + 36 * k, top: y,
                  transform: `translateY(-50%) scale(${(Math.max(0, p) * (1 - q)).toFixed(4)})`, transformOrigin: "0% 50%",
                  padding: `${6 * k}px ${16 * k}px ${4 * k}px`, borderRadius: 40 * k, border: `${2 * k}px solid ${col}`,
                  background: "rgba(0,0,0,.35)", color: col, fontFamily: LABEL, fontWeight: 800, fontSize: 28 * k,
                  letterSpacing: "0.04em", lineHeight: 1.1, whiteSpace: "nowrap", boxShadow: `0 0 ${16 * k}px ${col}33` }}>{txt}</div>
              );
            })}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== 10. tab reveal
/**
 * An accordion of white tabs sliding in on the right of the footage: one tab
 * at a time opens (its chevron turning, number chip going accent, an accent
 * edge growing), its lines rise in while a progress bar runs along its foot,
 * then it folds shut as the next one opens. The last stays open to the end.
 */
const TabReveal: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, height } = useVideoConfig();
  const k = useK();
  const exit = useExit();
  const rows = rowsOf(overlay.items, 5);
  if (rows.length < 2) return null;
  const n = rows.length;
  const PW = 600 * k, TH = 68 * k, G = 10 * k;
  const bodies = rows.map((r) => lines(r.text, 38).slice(0, 3));
  const maxLines = Math.max(0, ...bodies.map((b) => b.length));
  const EXTRA = (maxLines ? maxLines * 31 + 30 : 22) * k;
  const t0 = Math.round(fps * 0.55);
  const end = durationInFrames - 16;
  const dwell = Math.max(8, Math.min(Math.round(fps * 1.6), Math.floor((end - t0 - 10) / n)));
  const openAt = (i: number) => t0 + i * dwell;
  const openOf = (i: number) =>
    ramp(frame, openAt(i), 14, inOut) * (i < n - 1 ? 1 - ramp(frame, openAt(i + 1), 14, inOut) : 1);
  const titleLines = lines(cap(overlay.text || ""), 30).slice(0, 2);
  const totalH = (titleLines.length ? titleLines.length * 36 * k + 44 * k : 0) + n * TH + (n - 1) * G + EXTRA;
  const top = Math.max(90 * k, (height - totalH) / 2);
  const glow = ramp(frame, 0, 12) * (1 - exit);
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: glow,
        background: "linear-gradient(270deg, rgba(0,0,0,.55) 0%, rgba(0,0,0,.25) 30%, rgba(0,0,0,0) 55%)" }} />
      <div style={{ position: "absolute", right: 100 * k, top, width: PW, display: "flex", flexDirection: "column", gap: G }}>
        {titleLines.length ? (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", marginBottom: 12 * k }}>
            {titleLines.map((ln, li) => (
              <LetterLine key={li} text={ln} at={li * 4} step={0.6} style={{ fontFamily: LABEL, fontWeight: 800, fontSize: 32 * k,
                lineHeight: 1.1, letterSpacing: "0.14em", color: "#fff", textShadow: "0 3px 16px rgba(0,0,0,.7)" }} />
            ))}
            <div style={{ width: ramp(frame, 4, 16) * (1 - exit) * 90 * k, height: 5 * k, background: accent, marginTop: 10 * k }} />
          </div>
        ) : null}
        {rows.map((r, i) => {
          const e = ramp(frame, 4 + i * 3, 16);
          const qAt = end - 2 + i * 1.5;
          const q = ramp(frame, qAt, 10, expoIn);
          const o = openOf(i);
          const on = o > 0.5;
          const stop = i < n - 1 ? openAt(i + 1) : end;
          const prog = interpolate(frame, [openAt(i), Math.max(openAt(i) + 1, stop)], [0, 1], clamp);
          return (
            <div key={i} style={{ position: "relative", height: TH + EXTRA * o, borderRadius: 12 * k, overflow: "hidden",
              background: `rgba(255,255,255,${(0.86 + 0.12 * o).toFixed(3)})`,
              boxShadow: `0 ${f1((10 + 16 * o) * k)}px ${f1((30 + 30 * o) * k)}px rgba(0,0,0,${(0.28 + 0.14 * o).toFixed(3)})`,
              opacity: Math.min(1, e * 2) * (1 - q), transform: `translateX(${f1(((1 - e) * 140 + q * 160) * k)}px)` }}>
              <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 6 * k * o, background: accent }} />
              <div style={{ height: TH, display: "flex", alignItems: "center", gap: 18 * k, padding: `0 ${22 * k}px 0 ${24 * k}px` }}>
                <div style={{ width: 40 * k, height: 40 * k, borderRadius: 9 * k, flexShrink: 0, display: "flex", alignItems: "center",
                  justifyContent: "center", background: on ? accent : INK, color: on ? INK : "#fff", fontFamily: DISPLAY,
                  fontSize: 28 * k, lineHeight: 1, paddingTop: 3 * k }}>{i + 1}</div>
                <Rise at={6 + i * 3} out={qAt - 2} style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ display: "block", fontFamily: LABEL, fontWeight: 800, fontSize: 34 * k, lineHeight: 1.05,
                    color: INK, letterSpacing: "0.05em", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {cap(r.label)}
                  </span>
                </Rise>
                <svg width={22 * k} height={22 * k} viewBox="0 0 22 22" style={{ flexShrink: 0, transform: `rotate(${f1(90 * o)}deg)` }}>
                  <path d="M8 4 L15 11 L8 18" fill="none" stroke={INK} strokeWidth={3} strokeLinecap="round" strokeLinejoin="round"
                    opacity={0.55 + 0.45 * o} />
                </svg>
              </div>
              <div style={{ padding: `0 ${26 * k}px 0 ${82 * k}px`, display: "flex", flexDirection: "column", gap: 2 * k }}>
                {bodies[i].map((ln, li) => (
                  <Rise key={li} at={openAt(i) + 6 + li * 3} out={i < n - 1 ? openAt(i + 1) - 2 : qAt - 2} frames={14}>
                    <span style={{ display: "block", fontFamily: INTER, fontWeight: 400, fontSize: 24 * k, lineHeight: 1.3,
                      color: "#34363d" }}>{ln}</span>
                  </Rise>
                ))}
              </div>
              <div style={{ position: "absolute", left: 0, bottom: 0, height: 4 * k, width: `${(prog * 100).toFixed(2)}%`,
                background: accent, opacity: o }} />
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "ls-numbered-cascade": NumberedCascade,
  "ls-checklist-ticks": ChecklistTicks,
  "ls-pros-cons": ProsCons,
  "ls-top-countdown": TopCountdown,
  "ls-icon-grid": IconGrid,
  "ls-process-chevrons": ProcessChevrons,
  "ls-cycle-loop": CycleLoop,
  "ls-pyramid-levels": PyramidLevels,
  "ls-funnel-stages": FunnelStages,
  "ls-tab-reveal": TabReveal,
};
