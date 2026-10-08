import React from "react";
import { AbsoluteFill } from "remotion";
import type { Overlay, SceneMedia } from "../../types";
import { GROTESK, GROTESK_CAP, INTER, MONO, SUBLINE } from "../fonts";
import { backOut, clamp01, cubicIn, cubicInOut, cubicOut, expoOut, idle, lerp, prog } from "../motion/ease";
import { SafeImg } from "../motion/safePicture";
import { guard, rgba, type Look } from "./proKit";
import { num, str } from "./proFormat";
import { KineticLine, SOFT_WHITE, WHITE, SAFE, INK, blockAt, fitLines, isRight, softShadow, widthOf, zoneFor,
  type Zone } from "./typeKit";
import { useLook } from "./LibKinetic";
import { Caps, DIM, RiseLine, capsWidth, riseWidth } from "./LibKtDates";
import { Frost } from "./frost";
import { useLookSound } from "./LookSounds";
import scale from "./typeScale.json";

/**
 * LOOKS PACK 4, the cards (2026-10-08; LibKtPack4.tsx has the figures and the comparisons): people, steps,
 * causes, cases, posts and claims - for history and biography, education and how-to, true crime, social and
 * news, science and health - in the kinetic-type system (white bold grotesk, ONE accent, frosted glass; sizes
 * from typeScale.json "pack4"):
 *
 *   kt-profile    PROFILE     a person introduced with facts: a frosted ID card low on the calm side - the
 *                             portrait (the scene's own picture of that person, framed on the face; else the
 *                             initials), the name rising, the role, each fact (BORN, DIED, AGE, FROM, LAST SEEN)
 *                             landing ON its word
 *   kt-steps      STEPS       steps said in order: numbered rings down a frosted card, each step's ring filling
 *                             in the accent and its words rising on its word, the ones before it checked off; the
 *                             steps still to come wait as faint numbers
 *   kt-chain      CAUSE CHAIN causes and their effects: frosted nodes low across the frame, an arrow drawing to
 *                             each consequence as it is said (a spark running along it), CAUSE and EFFECT over the
 *                             ends
 *   kt-case       CASE FILE   a crime or a mystery: a frosted dossier - CASE FILE, the case's name, each fact typed
 *                             in on its word (date, location), the status stamped on its word (UNSOLVED)
 *   kt-post       POST        a social post quoted: a platform-neutral post card - the name as said (initials in
 *                             a disc), the handle and the platform only when said, the post's words coming into
 *                             focus, the likes counting only when they were said
 *   kt-factcheck  FACT CHECK  a claim and its verdict: the claim in quotes, then ON the verdict word a stamp
 *                             (FALSE / TRUE / MISLEADING) presses in - a false claim struck through - and the fact
 *                             as said under it
 *
 * Every look: an eased entry, each part landing on its own word (items[].at, seconds from the look's start), a
 * gentle idle, every element leaving in the last 12 frames. Only the planner's words are drawn
 * (src/lookpack4.py); a look that cannot set them whole draws nothing.
 */

// ------------------------------------------------------------------ shared
const unitOf = (W: number, H: number) => Math.min(H, (W * 9) / 16);
const capFont = (sh: number, U: number, ks: number, cap = GROTESK_CAP) => (sh * U * ks) / cap;
type P4 = Record<string, { share?: number; w?: number; h?: number }>;
const PACK4 = (scale as unknown as { pack4: P4 }).pack4;
const share = (key: string) => PACK4[key]?.share ?? 0.02;
const cardW = (key: string, W: number, H: number, tall = 0.88) => (W >= H ? (PACK4[key]?.w ?? 0.36) : tall) * W;
const saidAt = (at: number | null, fallback: number) => (at !== null && Number.isFinite(at) && at >= 0
  ? Math.max(2, at * 30 - 1) : fallback);
const TABULAR: React.CSSProperties = { fontVariantNumeric: "tabular-nums", fontFeatureSettings: '"tnum" 1' };
const RED = "#E5484D";
const GREEN = "#3DD68C";
const ORANGE = "#F0883E";

const Masked: React.FC<{ text: string; font: string; size: number; weight: number; color?: string; p: number; x?: number;
  tracking?: number; align?: "left" | "right" | "center"; shadow?: string }> =
  ({ text, font, size, weight, color = WHITE, p, x = 0, tracking = -0.01, align = "left", shadow }) => (
    <div style={{ overflow: "hidden", height: size * 1.22, paddingTop: size * 0.06, marginTop: -size * 0.06 }}>
      <div style={{ fontFamily: font, fontWeight: weight, fontSize: size, lineHeight: 1.12, color, whiteSpace: "nowrap",
        letterSpacing: `${tracking}em`, textAlign: align, textShadow: shadow, opacity: clamp01(p * 3) * (1 - clamp01(x * 1.6)),
        transform: `translateY(${((1 - clamp01(p)) * 104 + cubicIn(clamp01(x)) * 104).toFixed(2)}%)` }}>{text}</div>
    </div>
  );

interface Part { label: string; text: string; value: number | null; at: number | null }
const partsOf = (ov: Overlay, max = 6): Part[] => (Array.isArray(ov.items) ? ov.items : [])
  .map((it) => ({ label: str(it?.label), text: str(it?.text), value: num(it?.value),
    at: num((it as { at?: unknown } | undefined)?.at) }))
  .filter((x) => x.label || x.text).slice(0, max);

/** "Steve Jobs" -> "SJ", "Malala" -> "M". */
const initialsOf = (name: string) => {
  const words = name.split(/\s+/).filter((w) => /^[A-Za-z]/.test(w) && !/^(?:Jr\.?|Sr\.?|III|II|de|van|von|da|bin|al)$/.test(w));
  return ((words[0] || "")[0] || "") + (words.length > 1 ? (words[words.length - 1][0] || "") : "");
};

// ================================================================== kt-profile
/**
 * A person introduced with facts, as a frosted ID card low on the calm side (home: lower left; mirrored off a
 * face or lettering): the portrait - the scene's own picture of that person, framed on the face found in it
 * (vision's face box) and developing out of a soft blur; without one, the person's initials in the accent on a
 * dark disc - with a thin accent corner drawing on; beside it a kicker when one was said (VICTIM), the name rising
 * letter by letter, the role, a hairline, and each fact on its own line landing ON its word (BORN Feb 12, 1809 ·
 * Kentucky).
 */
const Profile: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, dir, hot, out, ks } = useLook(overlay, accent);
  const name = str(overlay.text);
  const facts = partsOf(overlay, 4).filter((x) => x.label && (x.text || x.value !== null));
  const lands = facts.map((x, i) => saidAt(x.at, 22 + i * 10));
  const sound = useLookSound(name ? [{ name: "ui-swipe", alt: ["swipe", "whoosh-soft"], at: 0, gain_db: -13 },
    ...lands.map((at) => ({ name: "ui-tick", alt: ["tick"], at: Math.round(at + 4), gain_db: -12 }))] : null);
  if (!name) return null;
  const role = str(overlay.subtitle);
  const kicker = str(overlay.label);
  const pic = (Array.isArray(overlay.media) ? overlay.media : []).find((m): m is SceneMedia => Boolean(m && typeof m === "object" && m.url));
  const U = unitOf(W, H);
  const kSize = capFont(share("kicker"), U, ks);
  let nSize = capFont(share("profileName"), U, ks, dir.cap);
  const rSize = capFont(share("profileRole"), U, ks);
  const lSize = capFont(share("small"), U, ks);
  const fSize = capFont(share("profileField"), U, ks);
  const P = share("portrait") * U * ks;
  const pad = 22 * k;
  const colMax = cardW("profileCard", W, H) - P - pad * 3;
  while (nSize > capFont(share("profileName"), U, ks) * 0.7 && riseWidth(name, GROTESK, nSize, 800) > colMax) nSize *= 0.95;
  const roleFit = role ? fitLines(role, INTER, 500, rSize, rSize * 0.85, colMax, 2) : null;
  const labW = facts.length ? Math.max(...facts.map((x) => widthOf(x.label.toUpperCase(), SUBLINE, lSize, 700, 0.12))) + 14 * k : 0;
  const factText = (x: Part) => x.text || String(x.value ?? "");
  const factW = facts.length ? labW + Math.max(...facts.map((x) => widthOf(factText(x), GROTESK, fSize, 700))) : 0;
  const colW = Math.min(colMax * 1.15, Math.max(riseWidth(name, GROTESK, nSize, 800), roleFit ? roleFit.width : 0, factW,
    kicker ? capsWidth(kicker, kSize) : 0, 0.16 * W));
  const rowH = fSize * 1.62;
  const colH = (kicker ? kSize + 12 * k : 0) + nSize * 1.2 + (roleFit ? roleFit.lines.length * roleFit.size * 1.3 + 4 * k : 0)
    + (facts.length ? 16 * k + facts.length * rowH : 0);
  const w = pad * 3 + P + colW;
  const h = pad * 2 + Math.max(P, colH);
  const zone = zoneFor(overlay, "lower-left", w, h, W, H) as Zone;
  const r = blockAt(zone, w, h, W, H);
  const open = prog(f, 0, 14, S, expoOut);
  const xo = 1 - clamp01(out * 1.4);
  const drift = idle(f, 40 * S, dur) * 3 * k;
  const t = f / S;
  // the portrait: framed on the face (or the subject) the worker found in the picture
  const fc = ((pic?.focus || {}) as { faceBoxes?: number[][]; box?: { x: number; y: number; w: number; h: number } });
  const face = Array.isArray(fc.faceBoxes) && Array.isArray(fc.faceBoxes[0]) && fc.faceBoxes[0].length === 4
    ? { cx: fc.faceBoxes[0][0] + fc.faceBoxes[0][2] / 2, cy: fc.faceBoxes[0][1] + fc.faceBoxes[0][3] / 2, s: fc.faceBoxes[0][3] }
    : fc.box && typeof fc.box.x === "number" ? { cx: fc.box.x + fc.box.w / 2, cy: fc.box.y + fc.box.h * 0.35, s: fc.box.h * 0.45 } : null;
  // (the face - brows to chin - about half the portrait's height: a head-and-shoulders crop)
  const zoom = face ? Math.max(1, Math.min(2.6, 0.6 / Math.max(0.05, face.s))) : 1;
  const pos = face ? `${(clamp01(face.cx) * 100).toFixed(1)}% ${(clamp01(face.cy) * 100).toFixed(1)}%` : "50% 32%";
  const reveal = prog(f, 3, 22, S, cubicOut);
  const corner = prog(f, 10, 16, S, expoOut) * xo;
  const colX = pad * 2 + P;
  const monogram = (
    <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center",
      background: `radial-gradient(circle at 40% 35%, ${rgba(hot, 0.22)} 0%, rgba(14,16,21,0.92) 70%)` }}>
      <span style={{ fontFamily: GROTESK, fontWeight: 800, fontSize: P * 0.36, letterSpacing: "0.02em", color: hot,
        textShadow: softShadow(k, 0.35) }}>{initialsOf(name)}</span>
    </div>
  );
  let y = (kicker ? kSize + 12 * k : 0) + nSize * 1.2 + (roleFit ? roleFit.lines.length * roleFit.size * 1.3 + 4 * k : 0);
  const factsY = y + 16 * k;
  y = factsY;
  return (
    <AbsoluteFill>
      {sound}
      <Frost x={r.x} y={r.y - drift} w={w} h={h} k={k} p={open} out={out} right={isRight(zone)} radius={16}>
        <div style={{ position: "absolute", left: pad, top: (h - P) / 2, width: P, height: P, borderRadius: 12 * k, overflow: "hidden",
          background: "#111318", clipPath: `inset(${((1 - reveal) * 100).toFixed(2)}% 0 0 0 round ${(12 * k).toFixed(1)}px)`,
          boxShadow: `inset 0 0 0 ${Math.max(1, k).toFixed(1)}px rgba(255,255,255,0.16)`, opacity: xo }}>
          {pic ? (
            <SafeImg src={pic.url} fallback={monogram} style={{ position: "absolute", inset: 0, width: "100%", height: "100%",
              objectFit: "cover", objectPosition: pos, transformOrigin: pos,
              transform: `scale(${(zoom * (1.08 - 0.08 * reveal + 0.02 * idle(f, 30 * S, dur))).toFixed(4)})`,
              filter: `blur(${((1 - reveal) * 6 * k).toFixed(2)}px) saturate(0.92) contrast(1.04)` }} />
          ) : monogram}
          <div style={{ position: "absolute", inset: 0, boxShadow: "inset 0 -40px 50px -30px rgba(0,0,0,0.45)" }} />
        </div>
        {/* the accent corner over the portrait */}
        <svg width={w} height={h} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          <path d={`M${pad - 6 * k},${(h - P) / 2 + 26 * k} L${pad - 6 * k},${(h - P) / 2 - 6 * k} L${pad + 26 * k},${(h - P) / 2 - 6 * k}`}
            fill="none" stroke={hot} strokeWidth={Math.max(2, 2.6 * k)} strokeLinecap="round" pathLength={1} strokeDasharray="1 1"
            strokeDashoffset={1 - corner} />
        </svg>
        <div style={{ position: "absolute", left: colX, top: (h - colH) / 2, width: colW }}>
          {kicker ? (
            <div style={{ height: kSize, marginBottom: 12 * k }}>
              <Caps text={kicker} size={kSize} color={dir.id === "doc" ? "rgba(250,250,247,0.86)" : hot} at={6} out={out} k={k} />
            </div>
          ) : null}
          <RiseLine text={name} size={nSize} font={GROTESK} weight={800} at={8} out={out} k={k} gap={0.9} roll={false} />
          {roleFit ? (
            <div style={{ marginTop: 4 * k }}>
              {roleFit.lines.map((ln, i) => (
                <div key={i} style={{ height: roleFit.size * 1.3 }}>
                  <KineticLine text={ln} font={INTER} weight={500} size={roleFit.size} color={SOFT_WHITE} preset="focus"
                    timing={{ at: 16 + i * 4, gap: 1.6 }} out={out} shadow={softShadow(k, 0.4)} />
                </div>
              ))}
            </div>
          ) : null}
        </div>
        {facts.length ? (
          <div style={{ position: "absolute", left: colX, top: (h - colH) / 2 + factsY - 16 * k, width: colW, height: Math.max(1, 1.2 * k),
            background: "linear-gradient(90deg, rgba(255,255,255,0.3), rgba(255,255,255,0.04))", transformOrigin: "left",
            transform: `scaleX(${(prog(f, 18, 16, S, expoOut) * xo).toFixed(4)})` }} />
        ) : null}
        {facts.map((x, i) => {
          const at = lands[i];
          const p = prog(f, at, 14, S, expoOut);
          const top = (h - colH) / 2 + factsY + i * rowH;
          // the label glows in the accent as its fact lands, then settles back to a quiet white (one small accent)
          const glow = clamp01((t - at) / 5) * (1 - clamp01((t - at - 20) / 14));
          const lab: React.CSSProperties = { fontFamily: SUBLINE, fontWeight: 700, fontSize: lSize, letterSpacing: "0.12em",
            textTransform: "uppercase", whiteSpace: "nowrap", lineHeight: 1 };
          return (
            <div key={i} style={{ position: "absolute", left: colX, top, width: colW, height: rowH, display: "flex", alignItems: "center" }}>
              <div style={{ position: "relative", width: labW, flex: "none", opacity: prog(f, Math.min(at, 20 + i * 3), 10, S, cubicOut) * xo }}>
                <div style={{ ...lab, color: DIM }}>{x.label}</div>
                <div style={{ ...lab, position: "absolute", left: 0, top: 0, color: hot, opacity: glow }}>{x.label}</div>
              </div>
              <Masked text={factText(x)} font={GROTESK} size={fSize} weight={700} p={p} x={out} shadow={softShadow(k, 0.4)} />
            </div>
          );
        })}
      </Frost>
    </AbsoluteFill>
  );
};

// ================================================================== kt-steps
/** A check mark drawn on (0..1) in a ring of diameter d. */
const checkD = (d: number) => `M${d * 0.3},${d * 0.52} L${d * 0.45},${d * 0.66} L${d * 0.72},${d * 0.36}`;

/**
 * Steps said in order, as a frosted card on the calm side (home: the left-hand panel): the title as a kicker
 * when one was said (HOW TO START INVESTING), then a numbered ring a step down the card joined by a thin line.
 * A step lands ON its word: its ring fills in the accent with a small settle (its numeral dark on it), its words
 * rise beside it, and the line runs on to it; the steps before it are checked off (a check in a white ring,
 * their words dimmed); the steps still to come wait as faint numbers without words. One card can carry the
 * steps so far (said far apart): the earlier ones checked from the start, the new one landing.
 */
const Steps: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, dir, hot, out, ks } = useLook(overlay, accent);
  const steps = partsOf(overlay, 6).filter((x) => x.label);
  const total = Math.max(steps.length, Math.min(6, Math.round(num(overlay.total) ?? steps.length)));
  // a step without its moment was said before this card: checked off from the start
  const lands = steps.map((x, i) => (x.at === null ? -1 : saidAt(x.at, 8 + i * 20)));
  const live = lands.filter((a) => a >= 0);
  const sound = useLookSound(steps.length ? [{ name: "ui-swipe", alt: ["swipe", "whoosh-soft"], at: 0, gain_db: -13 },
    ...live.map((at) => ({ name: "ui-pop", alt: ["pop", "ui-tick"], at: Math.round(at + 6), gain_db: -11 }))] : null);
  if (!steps.length) return null;
  const title = str(overlay.text);
  const U = unitOf(W, H);
  const kSize = capFont(share("kicker"), U, ks);
  const lSize0 = capFont(share("stepLabel"), U, ks);
  const nSize = capFont(share("stepNumber"), U, ks);
  const d = share("stepRing") * U * ks;
  const cw = cardW("stepsCard", W, H);
  const pad = 26 * k, gapX = 18 * k, gapY = 16 * k;
  const textW = cw - pad * 2 - d - gapX;
  const fits = steps.map((x) => fitLines(x.label, GROTESK, 700, lSize0, lSize0 * 0.8, textW, 2, -0.01));
  if (fits.some((x) => !x)) return null;
  const lSize = Math.min(...fits.map((x) => (x as { size: number }).size));
  const lineH = lSize * 1.2;
  const linesOf = (i: number) => (i < steps.length ? (fitLines(steps[i].label, GROTESK, 700, lSize, lSize, textW, 2, -0.01)?.lines
    || [steps[i].label]) : []);
  const rowH = (i: number) => Math.max(d, linesOf(i).length * lineH) + gapY;
  const head = title ? kSize + 18 * k : 0;
  const tops: number[] = [];
  let acc = pad + head;
  for (let i = 0; i < total; i++) {
    tops.push(acc);
    acc += rowH(i);
  }
  const ch = acc - gapY + pad;
  // the card as wide as its longest step (never wider than its share, never a sliver)
  const contentW = Math.max(...steps.map((_x, i) => Math.max(...linesOf(i).map((ln) => widthOf(ln, GROTESK, lSize, 700, -0.01)))));
  const cwFit = Math.min(cw, Math.max(0.22 * W, pad * 2 + d + gapX + contentW + 10 * k, title ? capsWidth(title, kSize) + pad * 2 : 0));
  const zone = zoneFor(overlay, "left-panel", cwFit, ch, W, H) as Zone;
  const r = blockAt(zone, cwFit, ch, W, H);
  const open = prog(f, 0, 14, S, expoOut);
  const xo = 1 - clamp01(out * 1.4);
  const drift = idle(f, 50 * S, dur) * 3 * k;
  const t = f / S;
  const landedAt = (i: number) => (i < steps.length ? (lands[i] < 0 ? 2 + i * 2 : lands[i]) : Infinity);
  const current = (() => {
    let c = -1;
    for (let i = 0; i < steps.length; i++) if (t >= landedAt(i)) c = i;
    return c;
  })();
  const ringCY = (i: number) => tops[i] + d / 2;
  return (
    <AbsoluteFill>
      {sound}
      <Frost x={r.x} y={r.y - drift} w={cwFit} h={ch} k={k} p={open} out={out} right={isRight(zone)} radius={16}>
        {title ? (
          <div style={{ position: "absolute", left: pad, top: pad, height: kSize }}>
            <Caps text={title} size={kSize} color={dir.id === "doc" ? "rgba(250,250,247,0.86)" : hot} at={3} out={out} k={k} />
          </div>
        ) : null}
        <svg width={cwFit} height={ch} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          {/* the line joining the rings, running on to each step as it lands */}
          {Array.from({ length: total - 1 }, (_v, i) => {
            const y0 = ringCY(i) + d / 2 + 4 * k, y1 = ringCY(i + 1) - d / 2 - 4 * k;
            const base = prog(f, 6 + i * 2, 12, S, cubicOut) * xo;
            const fill = i + 1 < steps.length ? prog(f, landedAt(i + 1) - 10, 12, S, cubicInOut) * xo : 0;
            return (
              <g key={i}>
                <line x1={pad + d / 2} x2={pad + d / 2} y1={y0} y2={y1} stroke="rgba(255,255,255,0.14)" strokeWidth={Math.max(1.5, 2 * k)}
                  opacity={base} />
                {fill > 0.001 ? <line x1={pad + d / 2} x2={pad + d / 2} y1={y0} y2={lerp(y0, y1, fill)} stroke={rgba(hot, 0.85)}
                  strokeWidth={Math.max(1.5, 2 * k)} strokeLinecap="round" /> : null}
              </g>
            );
          })}
          {Array.from({ length: total }, (_v, i) => {
            const cx = pad + d / 2, cy = ringCY(i);
            const appear = prog(f, 4 + i * 2, 12, S, cubicOut) * (1 - clamp01(out * 1.5 - ((total - 1 - i) / total) * 0.5));
            const landed = t >= landedAt(i);
            const isCur = i === current;
            const pop = landed ? prog(f, landedAt(i), 12, S, (u) => backOut(u, 1.7)) : 0;
            const done = landed && !isCur;
            const fillP = isCur ? pop : 0;
            return (
              <g key={i} opacity={appear}>
                <circle cx={cx} cy={cy} r={d / 2 - 1.5 * k} fill={isCur ? rgba(hot, 0.95 * fillP) : "rgba(10,12,16,0.35)"}
                  stroke={isCur ? hot : done ? "rgba(250,250,247,0.6)" : "rgba(255,255,255,0.22)"} strokeWidth={Math.max(1.5, 2 * k)}
                  style={isCur ? { filter: `drop-shadow(0 0 ${(8 * k).toFixed(1)}px ${rgba(hot, 0.55)})` } : undefined}
                  transform={isCur ? `translate(${cx} ${cy}) scale(${(0.86 + 0.14 * pop).toFixed(4)}) translate(${-cx} ${-cy})` : undefined} />
                {done ? (
                  <path d={checkD(d)} transform={`translate(${cx - d / 2} ${cy - d / 2})`} fill="none" stroke="rgba(250,250,247,0.85)"
                    strokeWidth={Math.max(2, 2.4 * k)} strokeLinecap="round" strokeLinejoin="round" pathLength={1} strokeDasharray="1 1"
                    strokeDashoffset={1 - prog(f, Math.max(landedAt(i) + 4, (i + 1 < steps.length ? landedAt(i + 1) : 0)), 10, S, cubicOut)} />
                ) : (
                  <text x={cx} y={cy + nSize * 0.36} textAnchor="middle" fill={isCur ? INK : "rgba(250,250,247,0.42)"}
                    style={{ fontFamily: GROTESK, fontWeight: 800, fontSize: nSize, ...TABULAR }}>{i + 1}</text>
                )}
              </g>
            );
          })}
        </svg>
        {steps.map((x, i) => {
          const at = landedAt(i);
          const isCur = i === current;
          const lines = linesOf(i);
          const top = ringCY(i) - (lines.length * lineH) / 2;
          return (
            <div key={i} style={{ position: "absolute", left: pad + d + gapX, top, width: textW,
              opacity: (isCur || t < at ? 1 : 0.62) * xo }}>
              {lines.map((ln, li) => (
                <Masked key={li} text={ln} font={GROTESK} size={lSize} weight={700} p={prog(f, at + 2 + li * 3, 14, S, expoOut)}
                  x={clamp01(out * 1.5 - ((steps.length - 1 - i) / steps.length) * 0.5)} shadow={softShadow(k, 0.4)} />
              ))}
            </div>
          );
        })}
      </Frost>
    </AbsoluteFill>
  );
};

// ================================================================== kt-chain
/**
 * Causes and their effects said in a chain ("Rising rates led to falling prices, which triggered a wave of
 * defaults"), low across the frame (up top when a face or lettering sits low): a frosted node a cause or an
 * effect, each opening ON its word, an arrow drawing from the one before to it as it is said - a spark running
 * along the arrow - and CAUSE over the first, EFFECT over the last (whose node has the accent edge).
 */
const Chain: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, hot, out, ks } = useLook(overlay, accent);
  const nodes = partsOf(overlay, 4).filter((x) => x.label);
  const n = nodes.length;
  const lands = nodes.map((x, i) => (i === 0 ? 6 : saidAt(x.at, 10 + i * 24)));
  for (let i = 1; i < n; i++) lands[i] = Math.max(lands[i], lands[i - 1] + 12);
  const sound = useLookSound(n >= 2 ? [{ name: "ui-swipe", alt: ["swipe", "whoosh-soft"], at: 0, gain_db: -13 },
    ...lands.slice(1).map((at) => ({ name: "whoosh-soft", alt: ["swipe"], at: Math.round(at - 6), gain_db: -16 })),
    ...lands.slice(1).map((at) => ({ name: "ui-tick", alt: ["tick"], at: Math.round(at + 2), gain_db: -12 }))] : null);
  if (n < 2) return null;
  const title = str(overlay.text);
  const U = unitOf(W, H);
  const kSize = capFont(share("kicker"), U, ks);
  let nSize = capFont(share("chainNode"), U, ks);
  const tall = W < H;
  const arrowW = (tall ? 0.06 * H : 0.05 * W);
  const padX = 20 * k, padY = 16 * k;
  const room = tall ? 0.84 * W : 0.88 * W;
  const maxNode = (s: number) => (tall ? room : Math.min(0.24 * W, (room - (n - 1) * arrowW) / n)) - padX * 2;
  let fits = nodes.map((x) => fitLines(x.label, GROTESK, 700, nSize, nSize * 0.8, maxNode(nSize), 2, -0.01));
  while (fits.some((x) => !x) && nSize > capFont(share("chainNode"), U, ks) * 0.7) {
    nSize *= 0.94;
    fits = nodes.map((x) => fitLines(x.label, GROTESK, 700, nSize, nSize * 0.8, maxNode(nSize), 2, -0.01));
  }
  if (fits.some((x) => !x)) return null;
  const size = Math.min(...fits.map((x) => (x as { size: number }).size));
  const lineH = size * 1.2;
  const boxes = nodes.map((x) => {
    const fl = fitLines(x.label, GROTESK, 700, size, size, maxNode(nSize), 2, -0.01) || { lines: [x.label], width: widthOf(x.label, GROTESK, size, 700) };
    return { lines: fl.lines, w: fl.width + padX * 2, h: fl.lines.length * lineH + padY * 2 };
  });
  const nodeH = Math.max(...boxes.map((b) => b.h));
  const kickRow = kSize + 12 * k;
  const titleRow = title ? kSize + 14 * k : 0;
  const totalW = tall ? Math.max(...boxes.map((b) => b.w)) : boxes.reduce((a, b) => a + b.w, 0) + (n - 1) * arrowW;
  const totalH = titleRow + kickRow + (tall ? boxes.reduce((a, b) => a + b.h, 0) + (n - 1) * arrowW : nodeH);
  const x0 = (W - totalW) / 2;
  let y0 = tall ? (H - totalH) / 2 : H - SAFE.bottom * H - totalH;
  const avoid = Array.isArray(overlay.avoid) ? overlay.avoid : [];
  const hits = (y: number) => avoid.some((b) => b.x * W < x0 + totalW && (b.x + b.w) * W > x0 && b.y * H < y + totalH && (b.y + b.h) * H > y);
  if (!tall && hits(y0) && !hits(SAFE.top * H)) y0 = SAFE.top * H;
  const xo = 1 - clamp01(out * 1.4);
  const drift = idle(f, 40 * S, dur) * 3 * k;
  // each node's box
  const place: { x: number; y: number; w: number; h: number }[] = [];
  let cx = 0, cy = titleRow + kickRow;
  boxes.forEach((b) => {
    if (tall) {
      place.push({ x: (totalW - b.w) / 2, y: cy, w: b.w, h: b.h });
      cy += b.h + arrowW;
    } else {
      place.push({ x: cx, y: titleRow + kickRow + (nodeH - b.h) / 2, w: b.w, h: b.h });
      cx += b.w + arrowW;
    }
  });
  return (
    <AbsoluteFill>
      {sound}
      {/* a soft shade under the row, so its small capitals and arrows hold on a bright picture */}
      <div style={{ position: "absolute", left: x0 - 160 * k, top: y0 - 70 * k, width: totalW + 320 * k, height: totalH + 140 * k,
        opacity: prog(f, 0, 14, S, cubicOut) * xo, pointerEvents: "none",
        background: "radial-gradient(ellipse 50% 50% at 50% 55%, rgba(4,5,8,0.66) 0%, rgba(4,5,8,0.38) 52%, rgba(4,5,8,0) 100%)" }} />
      <div style={{ position: "absolute", left: x0, top: y0 - drift, width: totalW, height: totalH }}>
        {title ? (
          <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: kSize }}>
            <Caps text={title} size={kSize} color={hot} at={2} out={out} k={k} align="center" />
          </div>
        ) : null}
        {[{ i: 0, text: "Cause" }, { i: n - 1, text: "Effect" }].map((kk) => (
          <div key={kk.text} style={{ position: "absolute", left: place[kk.i].x, width: place[kk.i].w, top: tall ? place[kk.i].y - kickRow : titleRow,
            height: kSize }}>
            <Caps text={kk.text} size={kSize} color={kk.i === n - 1 ? hot : SOFT_WHITE} at={lands[kk.i] + 2} out={out} k={k} align="center" />
          </div>
        ))}
        {place.map((p, i) => {
          const o = prog(f, lands[i], 14, S, expoOut);
          const last = i === n - 1;
          return (
            <React.Fragment key={i}>
              <Frost x={p.x} y={p.y} w={p.w} h={p.h} k={k} p={o} out={out} radius={Math.min(p.h / 2, 18)}
                edge={last ? hot : undefined} edgeP={last ? prog(f, lands[i] + 6, 12, S, expoOut) : 1}>
                <div style={{ position: "absolute", left: padX, top: padY, width: p.w - padX * 2, textAlign: "center" }}>
                  {boxes[i].lines.map((ln, li) => (
                    <Masked key={li} text={ln} font={GROTESK} size={size} weight={700} p={prog(f, lands[i] + 3 + li * 3, 14, S, expoOut)}
                      x={out} align="center" shadow={softShadow(k, 0.4)} />
                  ))}
                </div>
              </Frost>
            </React.Fragment>
          );
        })}
        <svg width={totalW} height={totalH} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          {place.slice(1).map((p, j) => {
            const a = place[j];
            const from = tall ? [a.x + a.w / 2, a.y + a.h + 8 * k] : [a.x + a.w + 8 * k, a.y + a.h / 2];
            const to = tall ? [p.x + p.w / 2, p.y - 8 * k] : [p.x - 8 * k, p.y + p.h / 2];
            const dp = prog(f, lands[j + 1] - 12, 14, S, cubicInOut) * xo;
            if (dp <= 0.001) return null;
            const hx = lerp(from[0], to[0], dp), hy = lerp(from[1], to[1], dp);
            const ang = Math.atan2(to[1] - from[1], to[0] - from[0]);
            const s = 7 * k * clamp01((dp - 0.7) / 0.3);
            const spark = dp < 1 ? 1 : 1 - clamp01((f / S - lands[j + 1] - 2) / 8);
            return (
              <g key={j} style={{ filter: `drop-shadow(0 ${(1.5 * k).toFixed(1)}px ${(4 * k).toFixed(1)}px rgba(0,0,0,0.5))` }}>
                <line x1={from[0]} y1={from[1]} x2={hx} y2={hy} stroke="rgba(250,250,247,0.85)" strokeWidth={Math.max(2, 2.6 * k)}
                  strokeLinecap="round" />
                {s > 0.3 ? <path d={`M${to[0]},${to[1]} L${to[0] - Math.cos(ang - 0.5) * s * 1.6},${to[1] - Math.sin(ang - 0.5) * s * 1.6} `
                  + `L${to[0] - Math.cos(ang + 0.5) * s * 1.6},${to[1] - Math.sin(ang + 0.5) * s * 1.6} Z`} fill="rgba(250,250,247,0.92)" /> : null}
                {spark > 0.01 ? <circle cx={hx} cy={hy} r={4.5 * k} fill={hot} opacity={spark}
                  style={{ filter: `drop-shadow(0 0 ${(6 * k).toFixed(1)}px ${rgba(hot, 0.9)})` }} /> : null}
              </g>
            );
          })}
        </svg>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== kt-case
const UNRESOLVED = /unsolved|open|missing|cold/i;

/** A rubber stamp pressing in: a rounded border and its word in capitals, turned a little, an ink ring on impact. */
const Stamp: React.FC<{ text: string; size: number; color: string; p: number; t: number; at: number; k: number; out: number;
  angle?: number }> = ({ text, size, color, p, t, at, k, out, angle = -8 }) => {
  const s = 1.55 - 0.55 * p;
  const ring = clamp01((t - at - 2) / 16);
  const w = widthOf(text, GROTESK, size, 800, 0.14) + size * 1.2;
  const h = size * 1.75;
  return (
    <div style={{ position: "relative", width: w, height: h, opacity: clamp01(p * 2) * (1 - clamp01(out * 1.4)),
      transform: `rotate(${angle}deg) scale(${s.toFixed(4)})`, transformOrigin: "50% 50%" }}>
      {ring > 0 && ring < 1 ? (
        <div style={{ position: "absolute", left: -size * 0.5 * ring, top: -size * 0.5 * ring, right: -size * 0.5 * ring,
          bottom: -size * 0.5 * ring, borderRadius: 8 * k, border: `${Math.max(1, 1.5 * k)}px solid ${rgba(color, 0.6 * (1 - ring))}` }} />
      ) : null}
      <div style={{ position: "absolute", inset: 0, borderRadius: 7 * k, border: `${Math.max(2, 3 * k).toFixed(1)}px solid ${rgba(color, 0.92)}`,
        background: rgba(color, 0.1), display: "flex", alignItems: "center", justifyContent: "center",
        boxShadow: `0 0 ${(14 * k).toFixed(1)}px ${rgba(color, 0.25)}` }}>
        <span style={{ fontFamily: GROTESK, fontWeight: 800, fontSize: size, letterSpacing: "0.14em", color: rgba(color, 0.96),
          lineHeight: 1, paddingLeft: "0.14em", whiteSpace: "nowrap" }}>{text}</span>
      </div>
    </div>
  );
};

/**
 * A crime or a mystery with its facts, as a frosted dossier on the calm side (home: the right-hand panel): a
 * header band (CASE FILE, a hairline), the case's name as said, then each fact on its own line - its label in
 * small mono capitals, its value typed in ON its word (a caret blinking while it types) - and the status
 * stamped in ON its word (UNSOLVED, OPEN, COLD CASE in red; SOLVED, CONVICTED in the accent), a little turned,
 * an ink ring on impact.
 */
const Case: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, dir, hot, out, ks } = useLook(overlay, accent);
  const all = partsOf(overlay, 5).filter((x) => x.label && x.text);
  const status = all.find((x) => /^status$/i.test(x.label));
  const fields = all.filter((x) => x !== status).slice(0, 3);
  const fAt = fields.map((x, i) => saidAt(x.at, 14 + i * 14));
  const sAt = status ? saidAt(status.at, Math.max(30, ...fAt) + 16) : 0;
  const CPS = 1.4;
  const sound = useLookSound(fields.length || status ? [{ name: "paper-slide", alt: ["paper", "swipe"], at: 0, gain_db: -14 },
    ...fields.map((x, i) => ({ name: "typewriter-clean", alt: ["keys", "typewriter"], at: Math.round(fAt[i]),
      until: Math.round(fAt[i] + x.text.length / CPS), gain_db: -18 })),
    ...(status ? [{ name: "stamp", alt: ["impact", "pop"], at: Math.round(sAt + 2), gain_db: -8 }] : [])] : null);
  if (!fields.length && !status) return null;
  const title = str(overlay.text);
  const kicker = (str(overlay.label) || "Case file").toUpperCase();
  const U = unitOf(W, H);
  const kSize = capFont(share("kicker"), U, ks);
  const tSize = capFont(share("caseName"), U, ks, dir.cap);
  const lSize = capFont(share("small"), U, ks);
  const fSize = capFont(share("caseField"), U, ks);
  const stSize = capFont(share("caseStamp"), U, ks);
  const cw = cardW("caseCard", W, H);
  const pad = 28 * k;
  const titleFit = title ? fitLines(title, GROTESK, 800, tSize, tSize * 0.75, cw - pad * 2, 2, -0.01) : null;
  const labW = Math.max(widthOf("LOCATION", MONO, lSize, 600, 0.08), ...fields.map((x) => widthOf(x.label.toUpperCase(), MONO, lSize, 600, 0.08)))
    + 18 * k;
  const valMax = cw - pad * 2 - labW;
  const vals = fields.map((x) => {
    let s = fSize;
    while (s > fSize * 0.72 && widthOf(x.text, MONO, s, 600) > valMax) s *= 0.95;
    return s;
  });
  const band = kSize + 22 * k;
  const rowH = fSize * 1.9;
  const stampH = status ? stSize * 1.75 + 22 * k : 0;
  const ch = pad + band + (titleFit ? titleFit.lines.length * titleFit.size * 1.18 + 14 * k : 0) + fields.length * rowH + stampH + pad * 0.6;
  const zone = zoneFor(overlay, "right-panel", cw, ch, W, H) as Zone;
  const r = blockAt(zone, cw, ch, W, H);
  const open = prog(f, 0, 14, S, expoOut);
  const xo = 1 - clamp01(out * 1.4);
  const drift = idle(f, 50 * S, dur) * 3 * k;
  const t = f / S;
  const bodyY = pad + band;
  const fieldsY = bodyY + (titleFit ? titleFit.lines.length * titleFit.size * 1.18 + 14 * k : 0);
  const unresolved = status ? UNRESOLVED.test(status.text) : false;
  const stCol = unresolved ? RED : hot;
  return (
    <AbsoluteFill>
      {sound}
      <Frost x={r.x} y={r.y - drift} w={cw} h={ch} k={k} p={open} out={out} right={isRight(zone)} radius={14}>
        {/* the header band: the file's tab */}
        <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: pad + band - 10 * k,
          background: "linear-gradient(180deg, rgba(255,255,255,0.07), rgba(255,255,255,0.02))" }} />
        <div style={{ position: "absolute", left: pad, top: pad - 4 * k, height: kSize, display: "flex", alignItems: "center", gap: 10 * k }}>
          <svg width={kSize * 1.1} height={kSize} style={{ overflow: "visible", opacity: prog(f, 2, 10, S, cubicOut) * xo }}>
            <path d={`M0,${kSize * 0.15} L${kSize * 0.38},${kSize * 0.15} L${kSize * 0.5},${kSize * 0.32} L${kSize * 1.1},${kSize * 0.32} `
              + `L${kSize * 1.1},${kSize} L0,${kSize} Z`} fill="none" stroke={hot} strokeWidth={Math.max(1.4, 1.8 * k)} strokeLinejoin="round" />
          </svg>
          <Caps text={kicker} size={kSize} color={dir.id === "doc" ? "rgba(250,250,247,0.86)" : hot} at={4} out={out} k={k} />
        </div>
        <div style={{ position: "absolute", left: pad, right: pad, top: pad + band - 10 * k, height: Math.max(1, 1.2 * k),
          background: "rgba(255,255,255,0.16)", transformOrigin: "left", transform: `scaleX(${(prog(f, 4, 18, S, expoOut) * xo).toFixed(4)})` }} />
        {titleFit ? titleFit.lines.map((ln, i) => (
          <div key={`t${i}`} style={{ position: "absolute", left: pad, top: bodyY + i * titleFit.size * 1.18, width: cw - pad * 2 }}>
            <Masked text={ln} font={GROTESK} size={titleFit.size} weight={800} p={prog(f, 8 + i * 4, 16, S, expoOut)} x={out}
              shadow={softShadow(k, 0.45)} />
          </div>
        )) : null}
        {fields.map((x, i) => {
          const at = fAt[i];
          const typed = Math.max(0, Math.min(x.text.length, Math.floor((t - at) * CPS)));
          const typing = t >= at && typed < x.text.length;
          const caret = typing || (t >= at && t < at + x.text.length / CPS + 18 && Math.floor(t / 8) % 2 === 0);
          return (
            <div key={i} style={{ position: "absolute", left: pad, top: fieldsY + i * rowH, width: cw - pad * 2, height: rowH,
              display: "flex", alignItems: "center", opacity: xo }}>
              <div style={{ width: labW, flex: "none", fontFamily: MONO, fontWeight: 600, fontSize: lSize, letterSpacing: "0.08em",
                color: DIM, textTransform: "uppercase", opacity: prog(f, Math.min(at, 12 + i * 4), 10, S, cubicOut) }}>{x.label}</div>
              <div style={{ fontFamily: MONO, fontWeight: 600, fontSize: vals[i], color: WHITE, whiteSpace: "pre", textShadow: softShadow(k, 0.35) }}>
                {x.text.slice(0, typed)}
                {caret ? <span style={{ display: "inline-block", width: vals[i] * 0.55, height: vals[i] * 1.05, marginLeft: 2 * k,
                  verticalAlign: "text-bottom", background: rgba(hot, 0.9) }} /> : null}
              </div>
            </div>
          );
        })}
        {status ? (
          <div style={{ position: "absolute", left: pad, top: fieldsY + fields.length * rowH + 10 * k, display: "flex", alignItems: "center",
            gap: 16 * k }}>
            <div style={{ width: labW - 16 * k, fontFamily: MONO, fontWeight: 600, fontSize: lSize, letterSpacing: "0.08em", color: DIM,
              textTransform: "uppercase", opacity: prog(f, Math.min(sAt, 16), 10, S, cubicOut) * xo }}>Status</div>
            <Stamp text={status.text.toUpperCase()} size={stSize} color={stCol} p={prog(f, sAt, 9, S, (u) => backOut(u, 1.25))} t={t} at={sAt}
              k={k} out={out} angle={-6} />
          </div>
        ) : null}
      </Frost>
    </AbsoluteFill>
  );
};

// ================================================================== kt-post
/** A small line icon: reply, repost, like (a heart) or views (an eye), drawn in a box of side s. */
type IconKind = "reply" | "repost" | "like" | "views" | "up";
const Icon: React.FC<{ kind: IconKind; s: number; color: string; fill?: number; k: number }> =
  ({ kind, s, color, fill = 0, k }) => {
    const sw = Math.max(1.4, 1.8 * k);
    const common = { fill: "none", stroke: color, strokeWidth: sw, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
    return (
      <svg width={s} height={s} viewBox="0 0 24 24" style={{ overflow: "visible", flex: "none" }}>
        {kind === "reply" ? <path {...common} strokeWidth={sw * (24 / s)} d="M4 5h16v11H9l-5 4z" /> : null}
        {kind === "repost" ? (
          <g {...common} strokeWidth={sw * (24 / s)}>
            <path d="M7 4 4 7l3 3" /><path d="M4 7h11a4 4 0 0 1 4 4v1" /><path d="m17 20 3-3-3-3" /><path d="M20 17H9a4 4 0 0 1-4-4v-1" />
          </g>
        ) : null}
        {kind === "like" ? (
          <path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z" fill={rgba(color, clamp01(fill))} stroke={color}
            strokeWidth={sw * (24 / s)} strokeLinejoin="round" />
        ) : null}
        {kind === "views" ? (
          <g {...common} strokeWidth={sw * (24 / s)}><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></g>
        ) : null}
        {kind === "up" ? (
          // an upvote: the arrow of a vote, filling as its figure counts
          <path d="M12 3.5 3.5 12.5H8.5V20.5H15.5V12.5H20.5z" fill={rgba(color, clamp01(fill))} stroke={color}
            strokeWidth={sw * (24 / s)} strokeLinejoin="round" />
        ) : null}
      </svg>
    );
  };

/**
 * A social post quoted, as a platform-neutral post card on the calm side (home: the right-hand panel): a disc
 * with the poster's initials, the name as said, the handle only when one was said, the platform in small
 * capitals only when it was named; the post's words coming into focus line by line; a row of quiet icons, the
 * one the narration counted (likes, reposts, views) in the accent with its figure counting up - no figure is
 * ever shown that was not said.
 */
const Post: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, hot, out, ks } = useLook(overlay, accent);
  const body = str(overlay.text);
  const count = num(overlay.value);
  const sound = useLookSound(body ? [{ name: "ui-pop", alt: ["pop", "ui-tick"], at: 2, gain_db: -12 },
    ...(count !== null ? [{ name: "count-roll", alt: ["count-tick"], at: 34, until: 56, gain_db: -12 },
      { name: "ui-pop", alt: ["pop"], at: 58, gain_db: -11 }] : [])] : null);
  if (!body) return null;
  const name = str(overlay.label) || "User";
  const handle = str(overlay.subtitle);
  const platform = str(overlay.highlight);
  const metric = str(overlay.suffix).toLowerCase();
  const U = unitOf(W, H);
  const nmSize = capFont(share("postName"), U, ks);
  const hSize = capFont(share("small"), U, ks);
  let tSize = capFont(share("postText"), U, ks);
  const cw = cardW("postCard", W, H);
  const pad = 26 * k;
  const av = nmSize * 2.6;
  const fit = fitLines(body, INTER, 500, tSize, tSize * 0.78, cw - pad * 2, 5);
  if (!fit) return null;
  tSize = fit.size;
  const lineH = tSize * 1.36;
  const iconS = hSize * 1.35;
  const ch = pad + av + 18 * k + fit.lines.length * lineH + 18 * k + iconS + pad;
  const zone = zoneFor(overlay, "right-panel", cw, ch, W, H) as Zone;
  const r = blockAt(zone, cw, ch, W, H);
  const e = prog(f, 0, 16, S, expoOut);
  const xo = 1 - clamp01(out * 1.4);
  const drift = idle(f, 50 * S, dur) * 3 * k;
  // the counted figure's own icon: an upvote is an arrow, never a heart
  const which: IconKind = /upvote/.test(metric) ? "up" : /retweet|repost|share/.test(metric) ? "repost"
    : /comment|repl/.test(metric) ? "reply" : /view/.test(metric) ? "views" : "like";
  const cp = prog(f, 34, 24, S, expoOut);
  const fmtCount = (v: number) => (v >= 1e6 ? `${(v / 1e6).toFixed(v >= 1e7 ? 0 : 1).replace(/\.0$/, "")}M`
    : v >= 1e4 ? `${Math.round(v / 1e3)}K` : v >= 1e3 ? `${(v / 1e3).toFixed(1).replace(/\.0$/, "")}K` : String(Math.round(v)));
  const icons: IconKind[] = ["reply", "repost", which === "up" ? "up" : "like", "views"];
  const words = fit.lines.join(" ").split(/\s+/).length;
  const gap = Math.max(0.6, Math.min(2, 24 / Math.max(1, words)));
  let wordsBefore = 0;
  return (
    <AbsoluteFill>
      {sound}
      <div style={{ position: "absolute", left: 0, top: 0, width: W, height: H,
        transform: `translateY(${((1 - e) * 26 * k - drift).toFixed(2)}px)` }}>
        <Frost x={r.x} y={r.y} w={cw} h={ch} k={k} p={e} out={out} right={isRight(zone)} radius={18}>
          <div style={{ position: "absolute", left: pad, top: pad, display: "flex", alignItems: "center", gap: 14 * k, width: cw - pad * 2 }}>
            <div style={{ width: av, height: av, borderRadius: av, flex: "none", display: "flex", alignItems: "center", justifyContent: "center",
              background: `linear-gradient(140deg, ${rgba(hot, 0.95)}, ${rgba(hot, 0.62)})`, opacity: prog(f, 3, 10, S, cubicOut) * xo,
              transform: `scale(${(0.7 + 0.3 * prog(f, 3, 14, S, (u) => backOut(u, 1.6))).toFixed(4)})` }}>
              <span style={{ fontFamily: GROTESK, fontWeight: 800, fontSize: av * 0.4, color: INK }}>{initialsOf(name) || "·"}</span>
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <Masked text={name} font={GROTESK} size={nmSize} weight={700} p={prog(f, 5, 14, S, expoOut)} x={out} />
              {handle ? (
                <div style={{ marginTop: 2 * k, fontFamily: INTER, fontWeight: 500, fontSize: hSize, color: DIM, whiteSpace: "nowrap",
                  opacity: prog(f, 9, 12, S, cubicOut) * xo }}>{handle}</div>
              ) : null}
            </div>
            {platform ? (
              <div style={{ flex: "none", alignSelf: "flex-start", marginTop: 4 * k }}>
                <Caps text={platform} size={hSize} color={DIM} at={8} out={out} k={k} tracking={0.16} />
              </div>
            ) : null}
          </div>
          <div style={{ position: "absolute", left: pad, top: pad + av + 18 * k, width: cw - pad * 2 }}>
            {fit.lines.map((ln, i) => {
              const at = 10 + wordsBefore * gap;
              wordsBefore += ln.split(/\s+/).length;
              return (
                <div key={i} style={{ height: lineH }}>
                  <KineticLine text={ln} font={INTER} weight={500} size={tSize} color={WHITE} preset="focus"
                    timing={{ at, gap, len: 12 }} out={out} shadow={softShadow(k, 0.3)} />
                </div>
              );
            })}
          </div>
          <div style={{ position: "absolute", left: pad, top: ch - pad - iconS, display: "flex", alignItems: "center", gap: 30 * k,
            opacity: prog(f, 16, 12, S, cubicOut) * xo }}>
            {icons.map((ic) => {
              const mine = count !== null && ic === which;
              return (
                <div key={ic} style={{ display: "flex", alignItems: "center", gap: 8 * k }}>
                  <Icon kind={ic} s={iconS} color={mine ? hot : "rgba(250,250,247,0.5)"} fill={mine && (ic === "like" || ic === "up") ? cp : 0} k={k} />
                  {mine ? (
                    <span style={{ fontFamily: GROTESK, fontWeight: 700, fontSize: hSize * 1.05, color: hot, ...TABULAR }}>
                      {fmtCount((count as number) * cp)}
                    </span>
                  ) : null}
                </div>
              );
            })}
          </div>
        </Frost>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== kt-factcheck
const VERDICT: Record<string, { color: string; word: string }> = {
  false: { color: RED, word: "FALSE" }, myth: { color: RED, word: "MYTH" }, true: { color: GREEN, word: "TRUE" },
  misleading: { color: ORANGE, word: "MISLEADING" },
};

/**
 * A claim and its verdict, as a frosted card on the calm side (home: the left-hand panel): CLAIM (with its time
 * when the narration gave one: CLAIM · 1969) over the claim in quotes, its words coming into focus; then ON the
 * verdict word a stamp presses in at the card's corner
 * (FALSE in red, TRUE in green, MISLEADING in orange) with an ink ring - a false claim struck through line by
 * line and dimmed, a misleading one underlined with a wave - and, when the narration says how it really is, the
 * fact under it (FACT, its words).
 */
const FactCheck: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, hot, out, ks } = useLook(overlay, accent);
  const claim = str(overlay.text).replace(/^[\s"'“”]+|[\s"'“”.]+$/g, "");
  const parts = partsOf(overlay, 1);
  // the verdict is the first part's; `label` is a verdict only when it is one ("True"), else the claim's time
  // ("1969": the kicker reads CLAIM · 1969)
  const lab = str(overlay.label);
  const labVerdict = VERDICT[lab.toLowerCase()] ? lab : "";
  const when = labVerdict ? "" : lab;
  const raw = (parts[0]?.label || labVerdict || "False").toLowerCase();
  const v = VERDICT[raw] || VERDICT.false;
  const vAt = saidAt(parts[0]?.at ?? null, 40);
  const sound = useLookSound(claim ? [{ name: "ui-swipe", alt: ["swipe", "whoosh-soft"], at: 0, gain_db: -13 },
    { name: "stamp", alt: ["impact", "pop"], at: Math.round(vAt + 2), gain_db: -8 },
    ...(v.word === "FALSE" || v.word === "MYTH" ? [{ name: "marker-draw", alt: ["marker"], at: Math.round(vAt + 6), gain_db: -18 }] : [])]
    : null);
  if (!claim) return null;
  const fact = str(overlay.subtitle);
  const U = unitOf(W, H);
  const kSize = capFont(share("kicker"), U, ks);
  const cSize0 = capFont(share("factClaim"), U, ks);
  const stSize = capFont(share("factStamp"), U, ks);
  const tSize = capFont(share("factText"), U, ks);
  const cw = cardW("factCard", W, H);
  const pad = 28 * k;
  const stampW = widthOf(v.word, GROTESK, stSize, 800, 0.14) + stSize * 1.2;
  const fit = fitLines(`“${claim}”`, GROTESK, 600, cSize0, cSize0 * 0.75, cw - pad * 2, 3, -0.01);
  if (!fit) return null;
  const cSize = fit.size;
  const lineH = cSize * 1.28;
  const factFit = fact ? fitLines(fact, INTER, 500, tSize, tSize * 0.82, cw - pad * 2, 2) : null;
  const head = kSize + 16 * k;
  const stampRow = stSize * 1.75 + 18 * k;
  const ch = pad + head + fit.lines.length * lineH + 12 * k + stampRow + (factFit ? kSize + 12 * k + factFit.lines.length * factFit.size * 1.32 + 8 * k : 0) + pad * 0.7;
  const zone = zoneFor(overlay, "left-panel", cw, ch, W, H) as Zone;
  const r = blockAt(zone, cw, ch, W, H);
  const open = prog(f, 0, 14, S, expoOut);
  const xo = 1 - clamp01(out * 1.4);
  const drift = idle(f, 50 * S, dur) * 3 * k;
  const t = f / S;
  const struck = v.word === "FALSE" || v.word === "MYTH";
  const wavy = v.word === "MISLEADING";
  const landed = t >= vAt;
  const claimY = pad + head;
  const stampY = claimY + fit.lines.length * lineH + 12 * k;
  const factAt = vAt + 16;
  return (
    <AbsoluteFill>
      {sound}
      <Frost x={r.x} y={r.y - drift} w={cw} h={ch} k={k} p={open} out={out} right={isRight(zone)} radius={16}>
        <div style={{ position: "absolute", left: pad, top: pad, height: kSize }}>
          <Caps text={when ? `Claim · ${when}` : "Claim"} size={kSize} color="rgba(250,250,247,0.7)" at={3} out={out} k={k} />
        </div>
        {fit.lines.map((ln, i) => {
          const lw = widthOf(ln, GROTESK, cSize, 600, -0.01);
          const sp = struck ? prog(f, vAt + 4 + i * 4, 10, S, cubicInOut) * xo : 0;
          return (
            <div key={i} style={{ position: "absolute", left: pad, top: claimY + i * lineH, width: cw - pad * 2, height: lineH }}>
              <div style={{ opacity: struck && landed ? 1 - 0.3 * prog(f, vAt + 4, 12, S, cubicOut) : 1 }}>
                <KineticLine text={ln} font={GROTESK} weight={600} size={cSize} tracking={-0.01} color={WHITE} preset="focus"
                  timing={{ at: 6 + i * 4, gap: 1.6 }} out={out} shadow={softShadow(k, 0.4)} />
              </div>
              {sp > 0.001 ? (
                <div style={{ position: "absolute", left: -4 * k, top: cSize * 0.62, width: (lw + 8 * k) * sp, height: Math.max(2, 3 * k),
                  borderRadius: 2 * k, background: rgba(v.color, 0.92), boxShadow: `0 0 ${(8 * k).toFixed(1)}px ${rgba(v.color, 0.4)}` }} />
              ) : null}
              {wavy && landed ? (
                <svg width={lw} height={cSize * 0.5} style={{ position: "absolute", left: 0, top: cSize * 1.12, overflow: "visible" }}>
                  {/* a soft wave: smooth quadratic arcs, one every 12 px */}
                  <path d={`M0,${(cSize * 0.12).toFixed(1)} Q${(6 * k).toFixed(1)},${(cSize * 0.12 - 4 * k).toFixed(1)} ${(12 * k).toFixed(1)},`
                    + `${(cSize * 0.12).toFixed(1)}` + Array.from({ length: Math.max(1, Math.round(lw / (12 * k)) - 1) }, (_q, j) =>
                    ` T${((j + 2) * 12 * k).toFixed(1)},${(cSize * 0.12).toFixed(1)}`).join("")} fill="none" stroke={v.color}
                    strokeWidth={Math.max(1.6, 2.2 * k)} strokeLinecap="round" pathLength={1} strokeDasharray="1 1"
                    strokeDashoffset={1 - prog(f, vAt + 4 + i * 4, 12, S, cubicInOut) * xo} />
                </svg>
              ) : null}
            </div>
          );
        })}
        <div style={{ position: "absolute", left: pad, top: stampY, display: "flex", alignItems: "center", gap: 14 * k }}>
          <div style={{ width: stampW + stSize * 0.6 }}>
            <Stamp text={v.word} size={stSize} color={v.color} p={prog(f, vAt, 9, S, (u) => backOut(u, 1.25))} t={t} at={vAt} k={k} out={out}
              angle={-5} />
          </div>
        </div>
        {factFit ? (
          <div style={{ position: "absolute", left: pad, top: stampY + stampRow, width: cw - pad * 2 }}>
            <div style={{ height: kSize, marginBottom: 12 * k }}>
              <Caps text="Fact" size={kSize} color={v.word === "TRUE" ? GREEN : hot} at={factAt} out={out} k={k} />
            </div>
            {factFit.lines.map((ln, i) => (
              <div key={i} style={{ height: factFit.size * 1.32 }}>
                <KineticLine text={ln} font={INTER} weight={500} size={factFit.size} color={SOFT_WHITE} preset="focus"
                  timing={{ at: factAt + 4 + i * 4, gap: 1.6 }} out={out} shadow={softShadow(k, 0.4)} />
              </div>
            ))}
          </div>
        ) : null}
      </Frost>
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "kt-profile": guard(Profile),
  "kt-steps": guard(Steps),
  "kt-chain": guard(Chain),
  "kt-case": guard(Case),
  "kt-post": guard(Post),
  "kt-factcheck": guard(FactCheck),
};
