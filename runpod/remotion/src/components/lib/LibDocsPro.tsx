import React from "react";
import { AbsoluteFill, Img } from "remotion";
import type { Overlay, SceneMedia } from "../../types";
import { useLookSound } from "./LookSounds";
import type { SoundCue } from "./lookSoundPlan";
import {
  ANTON, DISPLAY_SERIF, DISPLAY_SERIF_ITALIC, Grain, HAND, INTER, NEWS, NEWS_ITALIC, Pool, SIGNATURE, Stage, SUBLINE,
  TYPEWRITER, backOut, caps, clamp01, easeInOut, easeOut, exitOf, expoOut, fit, guard, hash, heavy, hotOf, inOf, lerp, lift,
  mixHex, rgba, rnd, textWidth, useBase, useSvgId, wrap, type CSS, type Face, type Look,
} from "./proKit";
import { clip, digits, handleOf, initials, splitHighlight, stackLines, str, titleCase } from "./proFormat";

/**
 * DOCS PRO (family "kx-"): ten looks for print, paper and words, built like
 * a documentary's insert shots and title design - real type on real-looking
 * paper, a camera that moves to the line that matters, nothing "lorem":
 *
 *   kx-article-zoom      a newspaper page: the camera pushes from the masthead and headline down to the key
 *                        sentence while the rest falls out of focus, then a highlighter sweeps it (document)
 *   kx-official-memo     a typed agency memo: redaction bars slam across the surrounding lines, a rubber stamp
 *                        lands, the key sentence is highlighted (records, filings, memos)
 *   kx-report-cover      a bound report: its cover holds for the title, swings open, and the page inside has
 *                        the key sentence highlighted (report, study, assessment)
 *   kx-handwritten-note  a torn notebook page slides in on the right and the line is written on it by hand
 *   kx-keyword-stack     2-4 words stacked in heavy condensed type, solid / outline / accent, each rising out
 *                        of its own mask; no bar, no underline (headline, key phrase)
 *   kx-quote-portrait    a magazine pull quote: the speaker's portrait in monochrome, the quote in a display
 *                        serif, name and role under it (quote)
 *   kx-alert-strip       a slim dark-glass alert top-left: a pulsing dot, the label, the line (warning, alert)
 *   kx-definition        a dictionary entry: the term in a display serif and what it means (term)
 *   kx-letter-signature  a letter's excerpt on aged paper, signed in ink as it lands (a letter, "wrote")
 *   kx-social-post       a post card with no platform's branding: who posted it, the words appearing, the key
 *                        phrase marked, its picture when it has one (a post)
 *
 * Only the narration's words are set (body / highlight / text / label /
 * subtitle as the plan gave them); a publication, a stamp, a signer or a
 * handle appears only when the plan named one. Sounds are the paper's own:
 * a slide, a stamp, a marker, a pen - soft, on their frames.
 */

const PAPER = "#f3efe6";
const INK = "#1d1f24";
const INK_SOFT = "#4a4c52";

// ------------------------------------------------------------------ shared
/** Paper with a fine fibre texture, a soft warm vignette and a long shadow. */
const Paper: React.FC<{ w: number; h: number; color?: string; seed?: number; style?: CSS; children?: React.ReactNode }> =
  ({ w, h, color = PAPER, seed = 4, style, children }) => {
    const { k } = useBase();
    const id = useSvgId("kxp");
    return (
      <div style={{ position: "absolute", width: w, height: h, background: color, overflow: "hidden",
        boxShadow: `0 ${30 * k}px ${80 * k}px rgba(0,0,0,.55), 0 ${6 * k}px ${16 * k}px rgba(0,0,0,.35)`, ...style }}>
        <svg width={w} height={h} style={{ position: "absolute", inset: 0, opacity: 0.55, mixBlendMode: "multiply" }}>
          <filter id={id} x="0" y="0" width="100%" height="100%">
            <feTurbulence type="fractalNoise" baseFrequency="0.85 0.6" numOctaves={3} seed={seed} />
            <feColorMatrix type="matrix" values="0 0 0 0 0.45  0 0 0 0 0.40  0 0 0 0 0.32  0 0 0 0.16 0" />
          </filter>
          <rect width={w} height={h} filter={`url(#${id})`} />
        </svg>
        <div style={{ position: "absolute", inset: 0, background: "radial-gradient(ellipse 80% 70% at 50% 40%, rgba(255,255,255,0) 55%, rgba(120,95,60,.16) 100%)" }} />
        {children}
      </div>
    );
  };

/** Lines of text with a highlighter sweeping behind them, line by line from `at` (30 fps frames). */
const Highlighted: React.FC<{ lines: string[]; face: Face; size: number; lineH: number; at: number; color: string; ink: string;
  stagger?: number; sweep?: number }> = ({ lines, face, size, lineH, at, color, ink, stagger = 7, sweep = 10 }) => {
  const { f, S, k } = useBase();
  return (
    <div>
      {lines.map((ln, i) => {
        const w = textWidth(ln, face.font, size, face.weight ?? 400, face.tracking ?? 0, face.italic);
        const p = inOf(f, (at + i * stagger) * S, sweep * S, easeInOut);
        return (
          <div key={i} style={{ position: "relative", height: lineH, whiteSpace: "nowrap" }}>
            <div style={{ position: "absolute", left: -6 * k, top: (lineH - size * 1.08) / 2, height: size * 1.08, width: w + 12 * k,
              background: color, mixBlendMode: "multiply", borderRadius: `${3 * k}px ${8 * k}px ${4 * k}px ${9 * k}px`,
              transform: `scaleX(${p.toFixed(4)}) skewX(-4deg)`, transformOrigin: "0% 50%", opacity: p > 0 ? 0.92 : 0 }} />
            <span style={{ position: "relative", fontFamily: face.font, fontWeight: face.weight ?? 400, fontSize: size,
              fontStyle: face.italic ? "italic" : undefined, letterSpacing: face.tracking ? `${face.tracking}em` : undefined,
              color: ink, lineHeight: `${lineH}px` }}>{ln}</span>
          </div>
        );
      })}
    </div>
  );
};

/** The highlighter colour for paper: the accent, kept bright enough to read through. */
const markerOf = (accent: string) => mixHex(hotOf(accent), "#fff6a8", 0.35);

/** Sentences of a text ("A. B? C!" -> ["A.", "B?", "C!"]). */
const sentences = (s: string): string[] =>
  (str(s).match(/[^.!?]+[.!?]+["”’)]*|[^.!?]+$/g) || []).map((x) => x.trim()).filter(Boolean);

/** A still picture's url from the overlay's media (an image, or a clip's thumbnail). */
const stillOf = (ov: Overlay): string => {
  const media: SceneMedia[] = Array.isArray(ov.media) ? ov.media : [];
  for (const m of media) {
    if (!m || typeof m !== "object") continue;
    const u = m.type === "image" ? m.url : m.thumbnail;
    if (typeof u === "string" && u.trim()) return u.trim();
  }
  return "";
};

/** The camera on a page: from one view to another, `p` 0..1; a view is the page point at the screen's centre and a scale. */
const camera = (from: { x: number; y: number; s: number }, to: { x: number; y: number; s: number }, p: number,
  cx: number, cy: number) => {
  const s = lerp(from.s, to.s, p);
  const x = lerp(from.x, to.x, p);
  const y = lerp(from.y, to.y, p);
  return `translate(${cx.toFixed(1)}px, ${cy.toFixed(1)}px) scale(${s.toFixed(4)}) translate(${(-x).toFixed(1)}px, ${(-y).toFixed(1)}px)`;
};

/** The desk a document lies on: the footage blurred and darkened, or a dark gradient on a full-screen moment. */
const Desk: React.FC<{ ov: Overlay; p: number }> = ({ ov, p }) => <Stage ov={ov} p={p} tone={1.05} />;

// ================================================================== kx-article-zoom
const ART = { inAt: 0, pushAt: 8, pushFrames: 34, mark: 40 };

/** The page's words: headline, the key sentence, the other sentences, the publication (only when named). */
export const articlePlan = (ov: Overlay) => {
  const key = clip(digits(str(ov.highlight) || str(ov.body) || str(ov.text)), 240, true);
  if (!key) return null;
  const head = clip(digits(str(ov.text)), 96, true) || clip(key, 80, true);
  const rest = sentences(digits(str(ov.body))).filter((x) => x && !key.includes(x) && !x.includes(key));
  return { key, head, rest, masthead: clip(str(ov.subtitle), 40), kicker: clip(str(ov.label), 24).toUpperCase() };
};

const ArticleZoom: Look = ({ overlay, accent }) => {
  const { f, S, k, width, height, dur } = useBase();
  const plan = articlePlan(overlay);
  const out = exitOf(f, dur, S);
  const sound = useLookSound(plan ? [
    { name: "paper-slide-v2", alt: ["paper-slide", "paper"], at: 2, gain_db: -9 },
    { name: "marker-draw", alt: ["marker-underline", "marker"], at: ART.mark, align: "start", gain_db: -9 },
  ] : []);
  if (!plan) return null;
  const photo = stillOf(overlay);
  // The page, in its own px (1080p): 1500 wide, two columns under the headline.
  const PW = 1500 * k;
  const M = 96 * k;
  const bodySize = 34 * k;
  const lineH = bodySize * 1.5;
  const body: Face = { font: NEWS, weight: 400 };
  const mast = plan.masthead;
  let y = 70 * k;
  const mastY = y;
  if (mast) y += 120 * k;
  const kickY = y + 10 * k;
  if (plan.kicker) y += 48 * k;
  const headFit = fit(plan.head, { font: NEWS, weight: 700 }, PW - 2 * M, 82 * k, 56 * k, 3);
  const headY = y + 10 * k;
  y = headY + headFit.lines.length * headFit.size * 1.12 + 46 * k;
  const ruleY = y;
  y += 40 * k;
  const colGap = 56 * k;
  const col1W = (PW - 2 * M - colGap) * 0.56;
  const col2W = PW - 2 * M - colGap - col1W;
  const col2X = M + col1W + colGap;
  const keyLines = wrap(plan.key, body, bodySize, col1W);
  // Paragraphs around the key sentence: the narration's other sentences, else its own words again (out of focus).
  const fillerText = plan.rest.length ? plan.rest.join(" ") : `${plan.head}. ${plan.key}`;
  const para1 = wrap(fillerText, body, bodySize, col1W).slice(0, 4);
  const para3 = wrap(`${plan.key} ${fillerText}`, body, bodySize, col1W).slice(0, 6);
  const keyY = y + para1.length * lineH + 26 * k;
  const p3Y = keyY + keyLines.length * lineH + 26 * k;
  const photoH = photo ? col2W * 0.66 : 0;
  const col2Lines = wrap(`${fillerText} ${plan.key} ${fillerText}`, body, bodySize, col2W).slice(0, 14);
  const PH = Math.max(p3Y + para3.length * lineH, y + photoH + 30 * k + col2Lines.length * lineH) + 120 * k;
  // The camera: the top of the page, then onto the key sentence.
  const keyCx = M + col1W / 2;
  const keyCy = keyY + (keyLines.length * lineH) / 2;
  const startView = { x: PW / 2, y: Math.min(PH / 2, headY + 260 * k), s: Math.min(0.68, (height * 1.05) / (headY + 620 * k)) };
  const endScale = Math.min(1.9, (width * 0.7) / col1W);
  const endView = { x: keyCx, y: keyCy, s: endScale };
  const push = inOf(f, ART.pushAt * S, ART.pushFrames * S, easeInOut);
  const drift = 0.02 * clamp01((f - (ART.pushAt + ART.pushFrames) * S) / Math.max(1, dur));
  const cam = camera(startView, { ...endView, s: endView.s * (1 + drift) }, push, width / 2, height * 0.5);
  const enter = inOf(f, ART.inAt * S, 14 * S);
  const dof = 5.5 * k * push;
  const tilt = lerp(9, 1.5, push);
  const text = (lines: string[], x: number, top: number, w: number, blur: number, key?: string) => (
    <div key={key} style={{ position: "absolute", left: x, top, width: w, filter: blur > 0.2 ? `blur(${blur.toFixed(2)}px)` : undefined }}>
      {lines.map((ln, i) => (
        <div key={i} style={{ fontFamily: NEWS, fontSize: bodySize, lineHeight: `${lineH}px`, color: "#2b2b2e", whiteSpace: "nowrap",
          textAlign: "justify" }}>{ln}</div>
      ))}
    </div>
  );
  return (
    <AbsoluteFill>
      {sound}
      <Desk ov={overlay} p={enter * (1 - out)} />
      <AbsoluteFill style={{ perspective: 2600 * k, opacity: enter * (1 - out) }}>
        <div style={{ position: "absolute", left: 0, top: 0, width: 0, height: 0, transformOrigin: "0 0",
          transform: `${cam} translateY(${((1 - enter) * 60 + out * 40) * k}px)` }}>
          <div style={{ position: "absolute", left: 0, top: 0, width: PW, height: PH, transformOrigin: `${keyCx}px ${keyCy}px`,
            transform: `rotateX(${tilt.toFixed(2)}deg) rotateZ(-1.2deg)` }}>
            <Paper w={PW} h={PH} seed={hash(plan.key) % 97}>
              {mast ? (
                <div style={{ position: "absolute", left: 0, right: 0, top: mastY, textAlign: "center", filter: `blur(${(dof * 0.8).toFixed(2)}px)` }}>
                  <div style={{ fontFamily: NEWS, fontWeight: 700, fontSize: 74 * k, color: INK, letterSpacing: "0.01em" }}>{mast}</div>
                  <div style={{ margin: `${14 * k}px ${M}px 0`, borderTop: `${2 * k}px solid ${INK}`, borderBottom: `${1 * k}px solid ${INK}`,
                    height: 5 * k }} />
                </div>
              ) : null}
              {plan.kicker ? (
                <div style={{ position: "absolute", left: M, top: kickY, ...caps(24 * k, "#6a5f52", 0.2),
                  filter: `blur(${(dof * 0.8).toFixed(2)}px)` }}>{plan.kicker}</div>
              ) : null}
              <div style={{ position: "absolute", left: M, top: headY, width: PW - 2 * M, filter: `blur(${(dof * 0.7).toFixed(2)}px)` }}>
                {headFit.lines.map((ln, i) => (
                  <div key={i} style={{ fontFamily: NEWS, fontWeight: 700, fontSize: headFit.size, lineHeight: 1.12, color: INK,
                    letterSpacing: "-0.01em", whiteSpace: "nowrap" }}>{ln}</div>
                ))}
              </div>
              <div style={{ position: "absolute", left: M, right: M, top: ruleY, borderTop: `${1.5 * k}px solid rgba(29,31,36,.35)`,
                filter: `blur(${(dof * 0.6).toFixed(2)}px)` }} />
              {text(para1, M, y, col1W, dof * 0.85, "p1")}
              <div style={{ position: "absolute", left: M, top: keyY, width: col1W }}>
                <Highlighted lines={keyLines} face={body} size={bodySize} lineH={lineH} at={ART.mark} color={markerOf(accent)}
                  ink="#16171a" />
              </div>
              {text(para3, M, p3Y, col1W, dof, "p3")}
              {photo ? (
                <div style={{ position: "absolute", left: col2X, top: y + 6 * k, width: col2W, height: photoH, overflow: "hidden",
                  filter: `blur(${(dof * 0.9).toFixed(2)}px) grayscale(0.25)` }}>
                  <Img src={photo} onError={() => undefined} maxRetries={2}
                    style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                </div>
              ) : null}
              {text(col2Lines, col2X, y + photoH + (photo ? 30 * k : 0), col2W, dof * 1.1, "c2")}
            </Paper>
          </div>
        </div>
      </AbsoluteFill>
      <Grain opacity={0.04} />
    </AbsoluteFill>
  );
};

// ================================================================== kx-official-memo
const MEMO = { inAt: 0, redact: 12, stamp: 28, mark: 40 };
const REDDISH = (c: string) => {
  const m = /^#?([0-9a-f]{6})$/i.exec(c || "");
  if (!m) return false;
  const v = parseInt(m[1], 16);
  const r = (v >> 16) & 255;
  const g = (v >> 8) & 255;
  const b = v & 255;
  return r > 150 && r > g * 1.6 && r > b * 1.6;
};

/** The memo's words: agency (subtitle), its kind (label), subject (text), the key sentence and the lines around it. */
export const memoPlan = (ov: Overlay) => {
  const key = clip(digits(str(ov.highlight) || str(ov.body) || str(ov.text)), 220, true);
  if (!key) return null;
  const rest = sentences(digits(str(ov.body))).filter((x) => x && !key.includes(x) && !x.includes(key));
  const kind = clip(str(ov.label), 18).toUpperCase();
  return { key, rest, agency: clip(str(ov.subtitle), 48).toUpperCase(), kind,
    subject: clip(digits(str(ov.text)), 70, true), stamp: "FILE COPY" };
};

const OfficialMemo: Look = ({ overlay, accent }) => {
  const { f, S, k, width, height, dur } = useBase();
  const id = useSvgId("kxm");
  const plan = memoPlan(overlay);
  const out = exitOf(f, dur, S);
  const sound = useLookSound(plan ? [
    { name: "paper-slide-v2", alt: ["paper-slide", "paper"], at: 2, gain_db: -9 },
    { name: "stamp", alt: ["paper-pin", "frame-drop"], at: MEMO.stamp, gain_db: -9 },
    { name: "marker-draw", alt: ["marker-underline", "marker"], at: MEMO.mark, align: "start", gain_db: -10 },
  ] : []);
  if (!plan) return null;
  const PW = 1240 * k;
  const M = 100 * k;
  const size = 31 * k;
  const lineH = size * 1.62;
  const tw: Face = { font: TYPEWRITER, weight: 400 };
  let y = 86 * k;
  const agencyY = y;
  if (plan.agency) y += 64 * k;
  const ruleY = y;
  y += 40 * k;
  const kindY = y;
  if (plan.kind) y += 76 * k;
  const subjY = y;
  const subjLines = plan.subject ? wrap(`SUBJECT: ${plan.subject}`, { font: TYPEWRITER, weight: 700 }, size, PW - 2 * M - 420 * k).slice(0, 3) : [];
  y += subjLines.length * lineH + 34 * k;
  const filler = plan.rest.length ? plan.rest.join(" ") : `${plan.subject || plan.key}. ${plan.key}`;
  const para1 = wrap(filler, tw, size, PW - 2 * M).slice(0, 4);
  const keyY = y + para1.length * lineH + 28 * k;
  const keyLines = wrap(plan.key, tw, size, PW - 2 * M);
  const p3Y = keyY + keyLines.length * lineH + 28 * k;
  const para3 = wrap(`${filler} ${plan.key}`, tw, size, PW - 2 * M).slice(0, 5);
  const PH = p3Y + para3.length * lineH + 140 * k;
  const enter = inOf(f, MEMO.inAt * S, 14 * S);
  const push = inOf(f, 6 * S, 46 * S, easeInOut);
  const keyCy = keyY + (keyLines.length * lineH) / 2;
  const startView = { x: PW / 2, y: Math.min(PH * 0.42, keyCy), s: Math.min(0.8, (height * 0.98) / PH * 1.25) };
  const endView = { x: PW / 2, y: keyCy, s: Math.min(1.08, (width * 0.86) / PW) };
  const cam = camera(startView, endView, push, width / 2, height * 0.52);
  // Redaction bars over a few word runs of the surrounding paragraphs (never the key sentence).
  const bars: { line: number; para: 1 | 3; x0: number; x1: number; at: number }[] = [];
  const pick = (lines: string[], para: 1 | 3) => lines.forEach((ln, li) => {
    const words = ln.split(" ");
    if (words.length < 4) return;
    const r = rnd(hash(ln) % 1000 + li * 7 + para);
    if (r < 0.35) return;
    const start = Math.floor(rnd(li * 13 + para) * (words.length - 3));
    const count = 2 + Math.floor(rnd(li * 29 + para * 3) * Math.min(4, words.length - start - 1));
    const before = words.slice(0, start).join(" ");
    const span = words.slice(start, start + count).join(" ");
    const x0 = before ? textWidth(`${before} `, TYPEWRITER, size) : 0;
    const x1 = x0 + textWidth(span, TYPEWRITER, size);
    bars.push({ line: li, para, x0, x1, at: MEMO.redact + bars.length * 2.5 });
  });
  pick(para1, 1);
  pick(para3, 3);
  const ink = REDDISH(accent) ? mixHex(accent, "#5a0d10", 0.25) : "#22335c";
  const stampP = inOf(f, MEMO.stamp * S, 6 * S, (t) => backOut(t, 0.6));
  const stampText = plan.stamp;
  const stampSize = 58 * k;
  const stampW = textWidth(stampText, SUBLINE, stampSize, 700, 0.12) + 70 * k;
  const typed = (lines: string[], top: number, para: 1 | 3) => (
    <div style={{ position: "absolute", left: M, top, width: PW - 2 * M }}>
      {lines.map((ln, i) => (
        <div key={i} style={{ position: "relative", fontFamily: TYPEWRITER, fontSize: size, lineHeight: `${lineH}px`, color: "#2a2a2c",
          whiteSpace: "nowrap" }}>
          {ln}
          {bars.filter((b) => b.para === para && b.line === i).map((b, j) => {
            const p = inOf(f, b.at * S, 4 * S, easeOut);
            return <div key={j} style={{ position: "absolute", left: b.x0 - 4 * k, top: (lineH - size * 1.05) / 2,
              width: (b.x1 - b.x0 + 8 * k) * p, height: size * 1.05, background: "#121214" }} />;
          })}
        </div>
      ))}
    </div>
  );
  return (
    <AbsoluteFill>
      {sound}
      <Desk ov={overlay} p={enter * (1 - out)} />
      <AbsoluteFill style={{ perspective: 2400 * k, opacity: enter * (1 - out) }}>
        <div style={{ position: "absolute", left: 0, top: 0, width: 0, height: 0, transformOrigin: "0 0",
          transform: `${cam} translateY(${((1 - enter) * 80 + out * 40) * k}px)` }}>
          <div style={{ position: "absolute", left: 0, top: 0, width: PW, height: PH,
            transform: `rotateX(${lerp(7, 2, push).toFixed(2)}deg) rotateZ(${lerp(-2.4, -0.8, push).toFixed(2)}deg)` }}>
            <Paper w={PW} h={PH} color="#f1ede2" seed={hash(plan.key) % 89}>
              {plan.agency ? (
                <div style={{ position: "absolute", left: M, right: M, top: agencyY, textAlign: "center",
                  ...caps(28 * k, INK, 0.22) }}>{plan.agency}</div>
              ) : null}
              <div style={{ position: "absolute", left: M, right: M, top: ruleY, borderTop: `${2 * k}px solid ${INK}` }} />
              {plan.kind ? (
                <div style={{ position: "absolute", left: M, top: kindY, fontFamily: TYPEWRITER, fontWeight: 700, fontSize: 46 * k,
                  letterSpacing: "0.18em", color: INK }}>{plan.kind}</div>
              ) : null}
              <div style={{ position: "absolute", left: M, top: subjY, width: PW - 2 * M }}>
                {subjLines.map((ln, i) => (
                  <div key={i} style={{ fontFamily: TYPEWRITER, fontWeight: 700, fontSize: size, lineHeight: `${lineH}px`, color: INK,
                    whiteSpace: "nowrap" }}>{ln}</div>
                ))}
              </div>
              {typed(para1, y, 1)}
              <div style={{ position: "absolute", left: M, top: keyY, width: PW - 2 * M }}>
                <Highlighted lines={keyLines} face={tw} size={size} lineH={lineH} at={MEMO.mark} color={markerOf(accent)} ink="#151517" />
              </div>
              {typed(para3, p3Y, 3)}
              {/* the stamp, top-right, worn ink */}
              <svg width={0} height={0} style={{ position: "absolute" }}>
                <filter id={`${id}w`} x="-10%" y="-10%" width="120%" height="120%">
                  <feTurbulence type="fractalNoise" baseFrequency={0.9} numOctaves={2} seed={7} result="n" />
                  <feColorMatrix in="n" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -2.2 1.5" result="m" />
                  <feComposite in="SourceGraphic" in2="m" operator="in" />
                </filter>
              </svg>
              <div style={{ position: "absolute", right: M * 0.6, top: kindY - 6 * k, width: stampW, height: stampSize * 1.7,
                display: "flex", alignItems: "center", justifyContent: "center", border: `${6 * k}px solid ${ink}`, borderRadius: 10 * k,
                color: ink, ...caps(stampSize, ink, 0.12), opacity: stampP > 0 ? Math.min(1, stampP * 1.6) * 0.86 : 0,
                transform: `rotate(-9deg) scale(${(1.7 - 0.7 * stampP).toFixed(3)})`, filter: `url(#${id}w)`, mixBlendMode: "multiply" }}>
                {stampText}
              </div>
            </Paper>
          </div>
        </div>
      </AbsoluteFill>
      <Grain opacity={0.04} />
    </AbsoluteFill>
  );
};

// ================================================================== kx-report-cover
const REP = { inAt: 0, open: 24, openFrames: 20, mark: 46 };

/** The report: its title (text), who issued it (subtitle), its kind (label) and the key sentence inside. */
export const reportPlan = (ov: Overlay) => {
  const key = clip(digits(str(ov.highlight) || str(ov.body) || str(ov.text)), 200, true);
  const title = clip(digits(str(ov.text)), 90, true) || clip(key, 70, true);
  if (!key && !title) return null;
  return { key: key || title, title, issuer: clip(str(ov.subtitle), 44).toUpperCase(), kind: clip(str(ov.label), 20).toUpperCase() };
};

const ReportCover: Look = ({ overlay, accent }) => {
  const { f, S, k, width, height, dur } = useBase();
  const plan = reportPlan(overlay);
  const out = exitOf(f, dur, S);
  const hot = hotOf(accent);
  const sound = useLookSound(plan ? [
    { name: "paper-slide-v2", alt: ["paper-slide", "paper"], at: 2, gain_db: -9 },
    { name: "page-flip", alt: ["page", "paper"], at: REP.open + 6, gain_db: -8 },
    { name: "marker-draw", alt: ["marker-underline", "marker"], at: REP.mark, align: "start", gain_db: -10 },
  ] : []);
  if (!plan) return null;
  const CW = 760 * k;
  const CH = 980 * k;
  const enter = inOf(f, REP.inAt * S, 16 * S);
  const open = inOf(f, REP.open * S, REP.openFrames * S, easeInOut);
  const push = inOf(f, (REP.open + 6) * S, 34 * S, easeInOut);
  // The page inside: the key sentence large, the rest of the page soft.
  const M = 76 * k;
  const keySize = 40 * k;
  const keyLH = keySize * 1.45;
  const face: Face = { font: NEWS, weight: 400 };
  const keyLines = wrap(plan.key, face, keySize, CW - 2 * M).slice(0, 7);
  const keyTop = CH * 0.36;
  const keyCy = keyTop + (keyLines.length * keyLH) / 2;
  const s0 = Math.min(0.92, (height * 0.86) / CH);
  const s1 = Math.min(1.25, (width * 0.6) / CW);
  const cam = camera({ x: CW / 2, y: CH / 2, s: s0 }, { x: CW / 2, y: keyCy, s: s1 }, push, width / 2, height * 0.5);
  const titleFit = fit(plan.title, { font: NEWS, weight: 700 }, CW - 2 * M, 74 * k, 44 * k, 4);
  const angle = -168 * open;
  const filler = wrap(`${plan.title}. ${plan.key}`, face, 26 * k, CW - 2 * M).slice(0, 5);
  const filler2 = wrap(`${plan.key} ${plan.title}.`, face, 26 * k, CW - 2 * M).slice(0, 7);
  return (
    <AbsoluteFill>
      {sound}
      <Desk ov={overlay} p={enter * (1 - out)} />
      <AbsoluteFill style={{ opacity: enter * (1 - out) }}>
        <div style={{ position: "absolute", left: 0, top: 0, width: 0, height: 0, transformOrigin: "0 0",
          transform: `${cam} translateY(${((1 - enter) * 70 + out * 40) * k}px)` }}>
          <div style={{ position: "absolute", left: 0, top: 0, width: CW, height: CH, perspective: 2400 * k }}>
            {/* the first page, under the cover */}
            <Paper w={CW} h={CH} color="#f4f1e8" seed={13}>
              <div style={{ position: "absolute", left: M, top: 70 * k, ...caps(20 * k, "#7a7368", 0.2), filter: `blur(${(2.4 * k * push).toFixed(2)}px)` }}>
                {clip(plan.title, 46).toUpperCase()}
              </div>
              <div style={{ position: "absolute", left: M, top: 130 * k, width: CW - 2 * M, filter: `blur(${(3.2 * k * push).toFixed(2)}px)` }}>
                {filler.map((ln, i) => <div key={i} style={{ fontFamily: NEWS, fontSize: 26 * k, lineHeight: 1.6, color: "#3a3a3d", whiteSpace: "nowrap" }}>{ln}</div>)}
              </div>
              <div style={{ position: "absolute", left: M, top: keyTop, width: CW - 2 * M }}>
                <Highlighted lines={keyLines} face={face} size={keySize} lineH={keyLH} at={REP.mark} color={markerOf(accent)} ink="#141416" />
              </div>
              <div style={{ position: "absolute", left: M, top: keyTop + keyLines.length * keyLH + 40 * k, width: CW - 2 * M,
                filter: `blur(${(3.4 * k * push).toFixed(2)}px)` }}>
                {filler2.map((ln, i) => <div key={i} style={{ fontFamily: NEWS, fontSize: 26 * k, lineHeight: 1.6, color: "#3a3a3d", whiteSpace: "nowrap" }}>{ln}</div>)}
              </div>
            </Paper>
            {/* the cover, swinging open on its left edge */}
            <div style={{ position: "absolute", left: 0, top: 0, width: CW, height: CH, transformOrigin: "0% 50%", transformStyle: "preserve-3d",
              transform: `rotateY(${angle.toFixed(2)}deg)` }}>
              <div style={{ position: "absolute", inset: 0, backfaceVisibility: "hidden", WebkitBackfaceVisibility: "hidden",
                background: "linear-gradient(160deg, #26303d 0%, #161c25 60%, #10141b 100%)",
                boxShadow: `0 ${30 * k}px ${80 * k}px rgba(0,0,0,.6), inset ${8 * k}px 0 ${18 * k}px rgba(0,0,0,.5)` }}>
                <Grain opacity={0.08} seed={9} />
                <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 26 * k, background: "rgba(0,0,0,.35)" }} />
                {plan.issuer ? <div style={{ position: "absolute", left: M, right: M, top: 80 * k, ...caps(24 * k, "rgba(255,255,255,.78)", 0.22),
                  whiteSpace: "normal", lineHeight: 1.4 }}>{plan.issuer}</div> : null}
                <div style={{ position: "absolute", left: M, right: M, top: CH * 0.34 }}>
                  {titleFit.lines.map((ln, i) => (
                    <div key={i} style={{ fontFamily: NEWS, fontWeight: 700, fontSize: titleFit.size, lineHeight: 1.1, color: "#f6f2ea",
                      whiteSpace: "nowrap" }}>{ln}</div>
                  ))}
                </div>
                {plan.kind ? <div style={{ position: "absolute", left: M, bottom: 80 * k, ...caps(22 * k, "rgba(255,255,255,.6)", 0.24) }}>{plan.kind}</div> : null}
              </div>
              <div style={{ position: "absolute", inset: 0, backfaceVisibility: "hidden", WebkitBackfaceVisibility: "hidden",
                transform: "rotateY(180deg)", background: "#e9e4d8" }} />
            </div>
          </div>
        </div>
      </AbsoluteFill>
      <Grain opacity={0.04} />
    </AbsoluteFill>
  );
};

// ================================================================== kx-handwritten-note
const NOTE = { inAt: 0, write: 6 };

/** The words written on the note: the phrase, at most about 70 characters, in 1-3 lines. */
export const notePlan = (ov: Overlay) => {
  const t = clip(digits(str(ov.text)), 72, true);
  return t ? { text: t, label: clip(str(ov.label), 24) } : null;
};

const HandwrittenNote: Look = ({ overlay }) => {
  const { f, S, k, kw, width, height, dur } = useBase();
  const id = useSvgId("kxn");
  const plan = notePlan(overlay);
  const out = exitOf(f, dur, S);
  const n = plan ? plan.text.length : 0;
  const per = n <= 48 ? 2 : 1;
  const writeEnd = NOTE.write + per * n;
  const sound = useLookSound(plan ? [
    { name: "paper-slide-v2", alt: ["paper-slide", "paper"], at: 1, gain_db: -11 },
    { name: "pen-scribble", alt: ["marker-draw", "marker"], at: NOTE.write, align: "start", until: writeEnd, gain_db: -10 },
  ] : []);
  if (!plan) return null;
  // The note fits its words: Caveat at about 86 px (1080p), lines on the paper's rules.
  const size = 86 * k;
  const lineH = 96 * k;
  const pad = 70 * k;
  const face: Face = { font: HAND, weight: 700 };
  const lines = wrap(plan.text, face, size, 660 * k).slice(0, 3);
  const textW = Math.max(...lines.map((l) => textWidth(l, HAND, size, 700)), 0);
  const W = Math.max(560 * k, textW + 2 * pad + 20 * k);
  const top0 = 74 * k;
  const H = top0 + lines.length * lineH + 64 * k;
  const x = width - 110 * kw - W;
  const y = height * 0.46 - H / 2;
  const enter = inOf(f, NOTE.inAt * S, 14 * S, (t) => backOut(t, 0.8));
  // Letters appear in reading order at the typing contract's pace; each line's mask follows the pen.
  const shown = Math.max(0, Math.min(n, (f / S - NOTE.write) / per));
  let before = 0;
  const torn = (() => {
    let d = `M0 ${16 * k}`;
    for (let i = 0; i <= 30; i++) d += ` L${((W * i) / 30).toFixed(1)} ${((6 + rnd(i * 7 + 3) * 13) * k).toFixed(1)}`;
    return `${d} L${W} ${H} L0 ${H} Z`;
  })();
  return (
    <AbsoluteFill style={{ opacity: 1 - out }}>
      {sound}
      <Pool x={x + W / 2} y={y + H / 2} w={W * 1.8} h={H * 2.0} p={enter} strength={0.42} />
      <div style={{ position: "absolute", left: x, top: y, width: W, height: H,
        transform: `translate(${((1 - enter) * 120 + out * 40) * k}px, ${((1 - enter) * 30) * k}px) rotate(${(-2.4 + (1 - enter) * 4).toFixed(2)}deg)`,
        filter: `drop-shadow(0 ${24 * k}px ${40 * k}px rgba(0,0,0,.5))` }}>
        <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
          <defs>
            <clipPath id={`${id}c`}><path d={torn} /></clipPath>
            <filter id={`${id}t`} x="0" y="0" width="100%" height="100%">
              <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves={3} seed={21} />
              <feColorMatrix type="matrix" values="0 0 0 0 0.42  0 0 0 0 0.38  0 0 0 0 0.3  0 0 0 0.14 0" />
            </filter>
          </defs>
          <g clipPath={`url(#${id}c)`}>
            <rect width={W} height={H} fill="#f6f1e2" />
            <rect width={W} height={H} filter={`url(#${id}t)`} />
            {lines.map((_, i) => (
              <line key={i} x1={0} x2={W} y1={top0 + (i + 1) * lineH - 10 * k} y2={top0 + (i + 1) * lineH - 10 * k}
                stroke="rgba(80,120,190,.3)" strokeWidth={1.6 * k} />
            ))}
          </g>
        </svg>
        <div style={{ position: "absolute", left: pad, top: top0 }}>
          {lines.map((ln, i) => {
            const start = before;
            before += ln.length + 1;
            const q = clamp01((shown - start) / Math.max(1, ln.length));
            const w = textWidth(ln, HAND, size, 700);
            return (
              <div key={i} style={{ height: lineH, whiteSpace: "nowrap", fontFamily: HAND, fontWeight: 700, fontSize: size, color: "#1c2b4d",
                lineHeight: `${lineH * 0.98}px`, clipPath: `inset(-20% ${((1 - q) * 100).toFixed(2)}% -30% 0)`,
                transform: `rotate(${((rnd(i * 5 + 1) - 0.5) * 1.4).toFixed(2)}deg)`, width: w + 24 * k }}>{ln}</div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== kx-keyword-stack
const STACK = { at: 3, step: 4 };

/** The stacked lines (2-4 of one to three words) and the one in the accent. */
export const stackPlan = (ov: Overlay) => {
  const lines = stackLines(str(ov.text), 4, 10).map((l) => l.toUpperCase());
  if (!lines.length) return null;
  const want = str(ov.highlight).toUpperCase();
  let hotLine = want ? lines.findIndex((l) => l.includes(want) || want.includes(l)) : -1;
  if (hotLine < 0) hotLine = lines.length - 1;
  return { lines, hotLine };
};

const KeywordStack: Look = ({ overlay, accent }) => {
  const { f, S, k, kw, height, dur } = useBase();
  const plan = stackPlan(overlay);
  const hot = hotOf(accent);
  const n = plan ? plan.lines.length : 0;
  const land = STACK.at + STACK.step * Math.max(0, n - 1) + 10;
  const sound = useLookSound(plan ? [{ name: "swoosh-text", alt: ["whoosh-soft-v2", "ui-swipe"], at: STACK.at + 3, gain_db: -9 }] : []);
  if (!plan) return null;
  const maxW = 1050 * kw;
  // One size for the stack: the longest line fits the column, at most 150 px at 1080p.
  const size = Math.min(150 * k, ...plan.lines.map((l) => (maxW / Math.max(1, textWidth(l, ANTON, 100, 400, 0.01))) * 100));
  const lineH = size * 0.98;
  const blockH = n * lineH;
  const left = 120 * kw;
  const top = height * 0.48 - blockH / 2;
  const exitStart = dur - Math.round(12 * S);
  const sweep = clamp01((f - (land + 2) * S) / (16 * S));
  return (
    <AbsoluteFill>
      {sound}
      <Pool x={left + maxW * 0.45} y={height * 0.48} w={maxW * 1.9} h={blockH * 2.2} p={inOf(f, 0, 10 * S)} strength={0.5} />
      <div style={{ position: "absolute", left, top }}>
        {plan.lines.map((ln, i) => {
          const p = inOf(f, (STACK.at + i * STACK.step) * S, 12 * S);
          const x = clamp01((f - (exitStart + i * 1.5 * S)) / (9 * S));
          const outline = n >= 3 && i === 1 && i !== plan.hotLine;
          const isHot = i === plan.hotLine;
          const style: CSS = { ...heavy(size, isHot ? hot : "#fff", 0.01), lineHeight: `${lineH}px`, display: "block",
            transform: `translateY(${(((1 - p) - x) * 105).toFixed(2)}%)`,
            ...(outline ? { color: "transparent", WebkitTextStroke: `${Math.max(2, 2.6 * k)}px #fff` } : { textShadow: lift(k, 0.45) }) };
          return (
            <div key={i} style={{ position: "relative", height: lineH, overflow: "hidden", paddingRight: 20 * k }}>
              <span style={style}>{ln}</span>
              {sweep > 0 && sweep < 1 ? (
                <span style={{ ...style, position: "absolute", left: 0, top: 0, color: "transparent", WebkitTextStroke: undefined,
                  backgroundImage: `linear-gradient(105deg, rgba(255,255,255,0) ${(sweep * 130 - 30).toFixed(1)}%, rgba(255,255,255,.75) ${(sweep * 130 - 15).toFixed(1)}%, rgba(255,255,255,0) ${(sweep * 130).toFixed(1)}%)`,
                  WebkitBackgroundClip: "text", backgroundClip: "text", textShadow: "none" }}>{ln}</span>
              ) : null}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== kx-quote-portrait
const QUOTE = { at: 5, step: 4 };

/** The quote (its marks trimmed), who said it (label) and their role (subtitle). */
export const quotePlan = (ov: Overlay) => {
  const q = clip(digits(str(ov.text)).replace(/^[“"']+|[”"']+$/g, ""), 190, true);
  return q ? { quote: q, name: clip(str(ov.label), 36), role: clip(str(ov.subtitle), 54) } : null;
};

const QuotePortrait: Look = ({ overlay, accent }) => {
  const { f, S, k, kw, width, height, dur } = useBase();
  const plan = quotePlan(overlay);
  const hot = hotOf(accent);
  const out = exitOf(f, dur, S);
  const sound = useLookSound(plan ? [{ name: "whoosh-soft-v2", alt: ["swoosh-text", "whoosh-soft"], at: 2, gain_db: -11 }] : []);
  if (!plan) return null;
  const photo = stillOf(overlay);
  const enter = inOf(f, 0, 7 * S);
  const pw = photo ? 600 * kw : 0;
  const ph = height - 240 * kw;
  const px = 130 * kw;
  const colX = photo ? px + pw + 110 * kw : 260 * kw;
  const colW = width - colX - (photo ? 130 * kw : 260 * kw);
  const qf = fit(plan.quote, { font: DISPLAY_SERIF }, colW, 96 * k, 52 * k, 6);
  const lineH = qf.size * 1.18;
  const blockH = qf.lines.length * lineH + 150 * k;
  const top = height * 0.5 - blockH / 2 + 40 * k;
  const landAt = QUOTE.at + QUOTE.step * (qf.lines.length - 1) + 10;
  const attrP = inOf(f, landAt * S, 14 * S);
  const pushPhoto = 1.08 - 0.06 * inOf(f, 0, dur, easeInOut);
  return (
    <AbsoluteFill>
      {sound}
      <Stage ov={overlay} p={enter * (1 - out)} tone={1.05} />
      <AbsoluteFill style={{ opacity: 1 - out }}>
        {photo ? (
          <div style={{ position: "absolute", left: px, top: (height - ph) / 2, width: pw, height: ph, overflow: "hidden",
            opacity: enter, transform: `translateX(${((1 - enter) * -40) * k}px)`,
            boxShadow: `0 ${30 * k}px ${70 * k}px rgba(0,0,0,.55)` }}>
            <Img src={photo} onError={() => undefined} maxRetries={2} style={{ width: "100%", height: "100%", objectFit: "cover",
              filter: "grayscale(1) contrast(1.12) brightness(0.92)", transform: `scale(${pushPhoto.toFixed(4)})` }} />
            <div style={{ position: "absolute", inset: 0, background: "linear-gradient(180deg, rgba(0,0,0,0) 55%, rgba(0,0,0,.55) 100%)" }} />
            <Grain opacity={0.1} seed={17} />
          </div>
        ) : null}
        <div style={{ position: "absolute", left: colX - 18 * k, top: top - 150 * k, ...heavy(260 * k, hot), fontFamily: DISPLAY_SERIF,
          lineHeight: 1, opacity: inOf(f, 2 * S, 12 * S) * 0.9, transform: `translateY(${((1 - inOf(f, 2 * S, 12 * S)) * 20) * k}px)` }}>“</div>
        <div style={{ position: "absolute", left: colX, top }}>
          {qf.lines.map((ln, i) => {
            const p = inOf(f, (QUOTE.at + i * QUOTE.step) * S, 14 * S);
            return (
              <div key={i} style={{ height: lineH, overflow: "hidden" }}>
                <div style={{ fontFamily: DISPLAY_SERIF, fontSize: qf.size, lineHeight: `${lineH}px`, color: "#fbf8f2", whiteSpace: "nowrap",
                  transform: `translateY(${((1 - p) * 100).toFixed(2)}%)`, opacity: p, textShadow: lift(k, 0.4) }}>{ln}</div>
              </div>
            );
          })}
          {plan.name || plan.role ? (
            <div style={{ marginTop: 40 * k, opacity: attrP, transform: `translateY(${((1 - attrP) * 12) * k}px)` }}>
              {plan.name ? <div style={{ ...caps(30 * k, "#fff", 0.16) }}>{plan.name}</div> : null}
              {plan.role ? <div style={{ fontFamily: SUBLINE, fontWeight: 600, fontSize: 25 * k, color: "rgba(255,255,255,.62)", marginTop: 12 * k,
                whiteSpace: "nowrap" }}>{plan.role}</div> : null}
            </div>
          ) : null}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ================================================================== kx-alert-strip
const ALERT = { at: 2, textAt: 8 };

/** The alert's label (BREAKING / WARNING / ALERT - the plan's, else ALERT) and its line. */
export const alertPlan = (ov: Overlay) => {
  const text = clip(digits(str(ov.text)), 56, true);
  if (!text) return null;
  return { text: text.toUpperCase() === text ? titleCase(text) : text, label: clip(str(ov.label), 14).toUpperCase() || "ALERT" };
};

const AlertStrip: Look = ({ overlay, accent }) => {
  const { f, S, k, kw, width, dur, fps } = useBase();
  const plan = alertPlan(overlay);
  const hot = hotOf(accent);
  const out = exitOf(f, dur, S, 10);
  const sound = useLookSound(plan ? [{ name: "alert-tone", alt: ["ding", "ui-pop"], at: ALERT.at + 2, gain_db: -12 }] : []);
  if (!plan) return null;
  const h = 96 * k;
  const labelSize = 29 * k;
  const textSize = 44 * k;
  const labelW = textWidth(plan.label, SUBLINE, labelSize, 700, 0.2) + 104 * k;
  const maxText = Math.min(1300 * kw, width - 2 * 96 * kw - labelW - 40 * k);
  const tf = fit(plan.text, { font: SUBLINE, weight: 700, tracking: 0.01 }, maxText, textSize, 24 * k, 1);
  const total = labelW + tf.width + 64 * k;
  const wipe = inOf(f, ALERT.at * S, 12 * S);
  const textP = inOf(f, ALERT.textAt * S, 12 * S);
  const pulse = (Math.sin(((f / fps) * Math.PI * 2) / 1.2) + 1) / 2;
  const reveal = (1 - wipe) * 100 + out * 100;
  return (
    <AbsoluteFill>
      {sound}
      <div style={{ position: "absolute", left: 96 * kw, top: 84 * kw, height: h, width: total, display: "flex", alignItems: "center",
        clipPath: `inset(0 ${reveal.toFixed(2)}% 0 0)`, borderRadius: 10 * k, background: "rgba(10,12,16,.78)",
        backdropFilter: `blur(${14 * k}px)`, border: `${Math.max(1, 1.2 * k)}px solid rgba(255,255,255,.12)`,
        boxShadow: `0 ${16 * k}px ${40 * k}px rgba(0,0,0,.45)` }}>
        <div style={{ height: "100%", width: labelW, display: "flex", alignItems: "center", gap: 16 * k, paddingLeft: 28 * k,
          background: rgba(hot, 0.12), borderRight: `${Math.max(1, 1.2 * k)}px solid rgba(255,255,255,.14)`, boxSizing: "border-box" }}>
          <div style={{ position: "relative", width: 18 * k, height: 18 * k }}>
            <div style={{ position: "absolute", inset: 0, borderRadius: "50%", background: hot,
              boxShadow: `0 0 ${(8 + 10 * pulse) * k}px ${rgba(hot, 0.5 + 0.4 * pulse)}` }} />
          </div>
          <span style={{ ...caps(labelSize, hot, 0.2) }}>{plan.label}</span>
        </div>
        <div style={{ paddingLeft: 30 * k, overflow: "hidden" }}>
          <div style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: tf.size, letterSpacing: "0.01em", color: "#fff", whiteSpace: "nowrap",
            opacity: textP, transform: `translateX(${((1 - textP) * -24) * k}px)` }}>{tf.lines[0] || ""}</div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== kx-definition
const DEF = { at: 2, wordAt: 6, defAt: 14 };

/** The term (text) and what it means (subtitle, else body): never invented. */
export const definitionPlan = (ov: Overlay) => {
  const term = clip(digits(str(ov.text)), 32);
  if (!term) return null;
  const meaning = clip(digits(str(ov.subtitle) || str(ov.body)), 150, true);
  return { term, meaning, label: clip(str(ov.label), 20).toUpperCase() || "DEFINITION" };
};

const Definition: Look = ({ overlay, accent }) => {
  const { f, S, k, kw, height, dur } = useBase();
  const plan = definitionPlan(overlay);
  const hot = hotOf(accent);
  const out = exitOf(f, dur, S);
  const sound = useLookSound(plan ? [{ name: "swoosh-text", alt: ["whoosh-soft-v2", "ui-swipe"], at: DEF.wordAt, gain_db: -10 }] : []);
  if (!plan) return null;
  const maxW = 1080 * kw;
  const pad = 52 * k;
  const termFit = fit(plan.term, { font: DISPLAY_SERIF }, maxW - 2 * pad, 128 * k, 70 * k, 2);
  const mFit = plan.meaning ? fit(plan.meaning, { font: INTER, weight: 500 }, Math.max(560 * k, Math.min(maxW - 2 * pad, termFit.width * 1.4)),
    38 * k, 28 * k, 3) : null;
  const W = Math.min(maxW, Math.max(termFit.width, mFit ? mFit.width : 0, textWidth(plan.label, SUBLINE, 22 * k, 700, 0.24)) + 2 * pad + 8 * k);
  const H = pad * 2 + 46 * k + termFit.lines.length * termFit.size * 1.05 + (mFit ? 28 * k + mFit.lines.length * mFit.size * 1.42 : 0);
  const left = 110 * kw;
  const top = height * 0.72 - H;
  const plate = inOf(f, DEF.at * S, 12 * S);
  return (
    <AbsoluteFill style={{ opacity: 1 - out, transform: `translateY(${(out * 14 * k).toFixed(1)}px)` }}>
      {sound}
      <div style={{ position: "absolute", left, top, width: W, height: H, borderRadius: 16 * k, background: "rgba(9,11,15,.78)",
        backdropFilter: `blur(${16 * k}px)`, border: `${Math.max(1, 1.2 * k)}px solid rgba(255,255,255,.12)`,
        boxShadow: `0 ${24 * k}px ${60 * k}px rgba(0,0,0,.5)`, opacity: plate, transform: `scale(${(0.97 + 0.03 * plate).toFixed(4)})`,
        transformOrigin: "0% 100%" }} />
      <div style={{ position: "absolute", left: left + pad, top: top + pad }}>
        <div style={{ ...caps(22 * k, hot, 0.24), opacity: inOf(f, (DEF.at + 2) * S, 10 * S) }}>{plan.label}</div>
        <div style={{ marginTop: 14 * k }}>
          {termFit.lines.map((ln, i) => {
            const p = inOf(f, (DEF.wordAt + i * 3) * S, 14 * S);
            return (
              <div key={i} style={{ height: termFit.size * 1.05, overflow: "hidden" }}>
                <div style={{ fontFamily: DISPLAY_SERIF, fontSize: termFit.size, lineHeight: 1.05, color: "#fff", whiteSpace: "nowrap",
                  transform: `translateY(${((1 - p) * 100).toFixed(2)}%)` }}>{ln}</div>
              </div>
            );
          })}
        </div>
        {mFit ? (
          <div style={{ marginTop: 28 * k }}>
            {mFit.lines.map((ln, i) => {
              const p = inOf(f, (DEF.defAt + i * 3) * S, 12 * S);
              return <div key={i} style={{ fontFamily: INTER, fontWeight: 500, fontSize: mFit.size, lineHeight: 1.42,
                color: "rgba(255,255,255,.84)", whiteSpace: "nowrap", opacity: p, transform: `translateY(${((1 - p) * 10) * k}px)` }}>{ln}</div>;
            })}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ================================================================== kx-letter-signature
const LETTER = { inAt: 0, sign: 26, signFrames: 22 };

/** The letter's excerpt (text), who signed it (label) and their role (subtitle). */
export const letterPlan = (ov: Overlay) => {
  const q = clip(digits(str(ov.text)).replace(/^[“"']+|[”"']+$/g, ""), 220, true);
  return q ? { excerpt: q, signer: clip(str(ov.label), 34), role: clip(str(ov.subtitle), 48) } : null;
};

const LetterSignature: Look = ({ overlay }) => {
  const { f, S, k, width, height, dur } = useBase();
  const plan = letterPlan(overlay);
  const out = exitOf(f, dur, S);
  const sound = useLookSound(plan ? [
    { name: "paper-slide-v2", alt: ["paper-slide", "paper"], at: 1, gain_db: -10 },
    ...(plan.signer ? [{ name: "pen-scribble", alt: ["marker-draw", "marker"], at: LETTER.sign, align: "start" as const,
      until: LETTER.sign + LETTER.signFrames, gain_db: -9 }] : []),
  ] : []);
  if (!plan) return null;
  // The page fits the excerpt: italic Newsreader about 56 px (1080p), the signature under it on the right.
  const M = 100 * k;
  const size = 56 * k;
  const lineH = size * 1.5;
  const face: Face = { font: NEWS_ITALIC, weight: 400, italic: true };
  const lines = wrap(`“${plan.excerpt}”`, face, size, 1080 * k).slice(0, 5);
  const textW = Math.max(...lines.map((l) => textWidth(l, NEWS_ITALIC, size, 400, 0, true)), 0);
  const sigSize = 132 * k;
  const sigW = plan.signer ? textWidth(plan.signer, SIGNATURE, sigSize) + 40 * k : 0;
  const PW = Math.max(900 * k, textW + 2 * M);
  const textTop = 96 * k;
  const sigTop = textTop + lines.length * lineH + 40 * k;
  const PH = sigTop + (plan.signer ? sigSize + 120 * k : 20 * k) + 70 * k;
  const enter = inOf(f, LETTER.inAt * S, 16 * S);
  const push = inOf(f, 0, dur, easeInOut);
  const s = Math.min(1, (height * 0.86) / PH, (width * 0.8) / PW) * (1 + 0.04 * push);
  const sigP = inOf(f, LETTER.sign * S, LETTER.signFrames * S, easeInOut);
  return (
    <AbsoluteFill>
      {sound}
      <Desk ov={overlay} p={enter * (1 - out)} />
      <AbsoluteFill style={{ opacity: enter * (1 - out) }}>
        <div style={{ position: "absolute", left: width / 2, top: height / 2, width: 0, height: 0,
          transform: `scale(${s.toFixed(4)}) translateY(${((1 - enter) * 80 + out * 40) * k}px) rotate(${lerp(-2.6, -1.2, push).toFixed(2)}deg)` }}>
          <div style={{ position: "absolute", left: -PW / 2, top: -PH / 2, width: PW, height: PH }}>
            <Paper w={PW} h={PH} color="#efe5cf" seed={31}>
              <div style={{ position: "absolute", left: 0, right: 0, top: PH * 0.62, height: 2 * k, background: "rgba(90,70,40,.14)",
                boxShadow: `0 ${1 * k}px 0 rgba(255,255,255,.35)` }} />
              <div style={{ position: "absolute", left: M, top: textTop }}>
                {lines.map((ln, i) => {
                  const p = inOf(f, (4 + i * 3) * S, 12 * S);
                  return <div key={i} style={{ fontFamily: NEWS_ITALIC, fontStyle: "italic", fontSize: size, lineHeight: `${lineH}px`, color: "#2a2620",
                    whiteSpace: "nowrap", opacity: p }}>{ln}</div>;
                })}
              </div>
              {plan.signer ? (
                <div style={{ position: "absolute", left: PW - M - Math.max(sigW, 420 * k), top: sigTop }}>
                  <div style={{ fontFamily: SIGNATURE, fontSize: sigSize, lineHeight: 1, color: "#14254a", whiteSpace: "nowrap",
                    clipPath: `inset(-30% ${((1 - sigP) * 100).toFixed(2)}% -30% -5%)` }}>{plan.signer}</div>
                  <div style={{ ...caps(26 * k, "#3d3a33", 0.18), marginTop: 20 * k, opacity: inOf(f, (LETTER.sign + 10) * S, 12 * S) }}>
                    {plan.signer.toUpperCase()}
                  </div>
                  {plan.role ? <div style={{ fontFamily: NEWS, fontSize: 30 * k, color: "#5a564c", marginTop: 8 * k, whiteSpace: "nowrap",
                    opacity: inOf(f, (LETTER.sign + 14) * S, 12 * S) }}>{plan.role}</div> : null}
                </div>
              ) : null}
            </Paper>
          </div>
        </div>
      </AbsoluteFill>
      <Grain opacity={0.04} />
    </AbsoluteFill>
  );
};

// ================================================================== kx-social-post
const POST = { inAt: 0, wordsAt: 8 };

/** The post: who (label), their handle (subtitle, only when given), the words, the key phrase. */
export const postPlan = (ov: Overlay) => {
  const text = clip(digits(str(ov.text)), 220, true);
  if (!text) return null;
  const name = clip(str(ov.label), 32);
  return { text, name, handle: handleOf(ov.subtitle), initials: initials(name), highlight: str(ov.highlight) };
};

const SocialPost: Look = ({ overlay, accent }) => {
  const { f, S, k, width, height, dur } = useBase();
  const plan = postPlan(overlay);
  const hot = hotOf(accent);
  const out = exitOf(f, dur, S);
  const sound = useLookSound(plan ? [{ name: "ui-pop", alt: ["pop", "ui-tick"], at: 6, gain_db: -9 }] : []);
  if (!plan) return null;
  const photo = stillOf(overlay);
  const CW = 1000 * k;
  const pad = 50 * k;
  const size = 44 * k;
  const lineH = size * 1.38;
  const face: Face = { font: INTER, weight: 500 };
  const lines = wrap(plan.text, face, size, CW - 2 * pad).slice(0, 6);
  const photoH = photo ? (CW - 2 * pad) * 0.5 : 0;
  const headH = 96 * k;
  const CH = pad + headH + 30 * k + lines.length * lineH + (photo ? 32 * k + photoH : 0) + pad;
  const s = Math.min(1, (height * 0.86) / CH);
  const enter = inOf(f, POST.inAt * S, 16 * S, (t) => backOut(t, 0.7));
  const tilt = lerp(14, 0, inOf(f, 0, 22 * S));
  const [pre, mid] = splitHighlight(plan.text, plan.highlight);
  const nWords = plan.text.split(" ").length;
  const wordAt = (i: number) => POST.wordsAt + i * Math.min(1.4, 28 / Math.max(1, nWords));
  // The key phrase's characters (coloured as its words light up).
  const hotFrom = pre.length;
  const hotTo = pre.length + mid.length;
  let cursor = 0;
  const rendered = lines.map((ln, li) => {
    const parts: React.ReactNode[] = [];
    ln.split(" ").forEach((w, wi) => {
      const at = plan.text.indexOf(w, cursor);
      const idx = at >= 0 ? at : cursor;
      cursor = idx + w.length;
      const wordIndex = plan.text.slice(0, idx).split(" ").length - 1;
      // Every word is there from the start, faint, and lights up in reading order: never an empty card.
      const p = inOf(f, wordAt(wordIndex) * S, 8 * S);
      const isHot = Boolean(mid) && idx >= hotFrom && idx < hotTo;
      parts.push(<span key={`${li}-${wi}`} style={{ opacity: 0.22 + 0.78 * p, color: isHot ? (p > 0.5 ? hot : "#f2f4f7") : "#f2f4f7",
        fontWeight: isHot ? 700 : 500 }}>{wi ? " " : ""}{w}</span>);
    });
    return <div key={li} style={{ fontFamily: INTER, fontSize: size, lineHeight: `${lineH}px`, whiteSpace: "nowrap" }}>{parts}</div>;
  });
  return (
    <AbsoluteFill>
      {sound}
      <Stage ov={overlay} p={inOf(f, 0, 10 * S) * (1 - out)} tone={0.95} />
      <AbsoluteFill style={{ perspective: 2200 * k, opacity: 1 - out }}>
        <div style={{ position: "absolute", left: width / 2 - CW / 2, top: height / 2 - CH / 2, width: CW, height: CH,
          transform: `scale(${(s * (0.92 + 0.08 * enter)).toFixed(4)}) rotateX(${tilt.toFixed(2)}deg) translateY(${((1 - enter) * 60 - out * 30) * k}px)`,
          opacity: Math.min(1, enter * 1.4), borderRadius: 28 * k, background: "linear-gradient(180deg, #171a20 0%, #111318 100%)",
          border: `${Math.max(1, 1.2 * k)}px solid rgba(255,255,255,.10)`,
          boxShadow: `0 ${40 * k}px ${100 * k}px rgba(0,0,0,.6), inset 0 1px 0 rgba(255,255,255,.06)` }}>
          <div style={{ position: "absolute", left: pad, top: pad, display: "flex", alignItems: "center", gap: 22 * k }}>
            <div style={{ width: 92 * k, height: 92 * k, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center",
              background: `linear-gradient(135deg, ${hot} 0%, ${mixHex(hot, "#000000", 0.45)} 100%)`, ...heavy(38 * k, "#0b0d11", 0.02) }}>
              {plan.initials || "•"}
            </div>
            <div>
              {plan.name ? <div style={{ fontFamily: INTER, fontWeight: 700, fontSize: 36 * k, color: "#fff", whiteSpace: "nowrap" }}>{plan.name}</div> : null}
              {plan.handle ? <div style={{ fontFamily: INTER, fontWeight: 400, fontSize: 29 * k, color: "rgba(255,255,255,.5)", marginTop: 4 * k,
                whiteSpace: "nowrap" }}>{plan.handle}</div> : null}
            </div>
          </div>
          <div style={{ position: "absolute", left: pad, top: pad + headH + 30 * k }}>{rendered}</div>
          {photo ? (
            <div style={{ position: "absolute", left: pad, right: pad, top: pad + headH + 30 * k + lines.length * lineH + 32 * k, height: photoH,
              borderRadius: 20 * k, overflow: "hidden", opacity: inOf(f, 4 * S, 12 * S) }}>
              <Img src={photo} onError={() => undefined} maxRetries={2} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
            </div>
          ) : null}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/** Exported for the planner's tests: the plans every look draws from. */
export const PLANS = { articlePlan, memoPlan, reportPlan, notePlan, stackPlan, quotePlan, alertPlan, definitionPlan, letterPlan,
  postPlan };

export const LOOKS: Record<string, Look> = {
  "kx-article-zoom": guard(ArticleZoom),
  "kx-official-memo": guard(OfficialMemo),
  "kx-report-cover": guard(ReportCover),
  "kx-handwritten-note": guard(HandwrittenNote),
  "kx-keyword-stack": guard(KeywordStack),
  "kx-quote-portrait": guard(QuotePortrait),
  "kx-alert-strip": guard(AlertStrip),
  "kx-definition": guard(Definition),
  "kx-letter-signature": guard(LetterSignature),
  "kx-social-post": guard(SocialPost),
};
