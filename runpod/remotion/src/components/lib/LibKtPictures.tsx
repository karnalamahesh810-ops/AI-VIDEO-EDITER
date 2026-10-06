import React from "react";
import { AbsoluteFill, Img, useCurrentFrame, useVideoConfig } from "remotion";
import type { Overlay, SceneMedia } from "../../types";
import { GROTESK, GROTESK_CAP } from "../fonts";
import { backOut, clamp01, cubicIn, cubicInOut, cubicOut, expoOut, idle, lerp, prog, sineInOut } from "../motion/ease";
import { guard, rgba, type Look } from "./proKit";
import { milesBetween, num, placeName, placesOf, str, distanceText } from "./proFormat";
import { KineticLine, WHITE, fitLines, softShadow } from "./typeKit";
import { useLook } from "./LibKinetic";
import { Caps, DIM, Glass, RiseLine, capsWidth, riseWidth } from "./LibKtDates";
import { overlapArea, rect } from "./annoKit";
import scale from "./typeScale.json";

/**
 * THE LOOK PACK, its pictures (2026-10-07; LibKtPack.tsx has the words and the
 * data, LibKtMaps.tsx the places). The story's own pictures (Main.tsx binds them:
 * overlay.media, the scene's still or a frame of its clip, then pictures of
 * the same subject nearby) in the kinetic-type system:
 *
 *   kt-evidence    EVIDENCE CARD   a print of the picture slides in from the side with a 3D tilt that
 *                                  settles, a long soft shadow, one light sweep across its gloss, and its
 *                                  caption under it: a kicker, the words, the source
 *   kt-then-now    THEN / NOW      two pictures of one place full frame: the earlier one first, a divider
 *                                  sweeps in and reveals the later one, glass chips with the years, the
 *                                  divider's handle easing back and forth once
 *   kt-two-places  TWO PLACES      two places side by side on a diagonal split, each sliding in from its
 *                                  side, an accent divider drawing between them, their names on glass and
 *                                  the miles between them when both places are known
 *
 * The full-frame two (kt-then-now, kt-two-places) are deliberate full-frame
 * graphics: the footage under them pushes in and softens as they grow in
 * (components/motion/stage.tsx), and they leave the same way. A look whose
 * pictures did not load is drawn as the scene's own picture with its words
 * (components/motion/pictureGuard.tsx) - never an empty frame.
 */

const unitOf = (W: number, H: number) => Math.min(H, (W * 9) / 16);
const capFont = (sh: number, U: number, ks: number, cap = GROTESK_CAP) => (sh * U * ks) / cap;
const picsOf = (ov: Overlay): SceneMedia[] =>
  (Array.isArray(ov.media) ? ov.media : []).filter((m): m is SceneMedia => Boolean(m && typeof m === "object" && m.url));
/** Where a quiet one-line title sits at the lower left (its top): 0.1 H up, raised above lettering it would cover. */
const lowLineY = (overlay: Overlay, x: number, w: number, h: number, W: number, H: number, k: number): number => {
  let y = 0.9 * H - h;
  for (const b of Array.isArray(overlay.avoid) ? overlay.avoid : []) {
    const bx = b.x * W, by = b.y * H, bw = b.w * W, bh = b.h * H;
    if (bx < x + w && bx + bw > x && by < y + h && by + bh > y) y = Math.max(0.1 * H, Math.min(y, by - h - 14 * k));
  }
  return y;
};
const aspectOf = (m: SceneMedia): number => {
  const a = num((m as { focus?: { aspect?: unknown } }).focus?.aspect);
  return a !== null && a > 0.5 && a < 3 ? a : 1.5;
};

// ================================================================== kt-evidence
/**
 * A print of the picture (a warm white border, the photo inside it graded a
 * touch) slides in from the frame's side and turns toward the viewer as it
 * settles (frames 2-30: rotateY -38° to -7°, a small back-out), a long soft
 * shadow under it; one light sweep crosses its gloss on landing (30-52); its
 * caption comes up under it - the kicker in the accent, the words in the bold
 * grotesk, the source in small capitals. It floats a few pixels while it holds
 * and slides back out the way it came. The card sits on the side clear of the
 * faces and lettering under it (overlay.avoid), the right by default.
 */
const Evidence: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, hot, out, ks } = useLook(overlay, accent);
  const pic = picsOf(overlay)[0];
  if (!pic) return null;
  const caption = str(overlay.text);
  const kicker = str(overlay.label);
  const source = str(overlay.subtitle);
  const U = unitOf(W, H);
  const cardW = scale.pack.evidenceCard.w * W * Math.min(1.15, ks);
  const border = 12 * k;
  const aspect = Math.max(1.2, Math.min(1.78, aspectOf(pic)));
  const photoW = cardW - 2 * border;
  const photoH = photoW / aspect;
  const cardH = photoH + 2 * border;
  const cSize = capFont(scale.pack.caption.share, U, ks);
  const kSize = capFont(scale.pack.packKicker.share, U, ks);
  const sSize = capFont(scale.pack.placeSmall.share, U, ks);
  const cap = caption ? fitLines(caption, GROTESK, 700, cSize, cSize * 0.8, cardW, 2, -0.01) : null;
  const capH = (kicker ? kSize + 12 * k : 0) + (cap ? cap.lines.length * cap.size * 1.18 : 0) + (source ? sSize + 12 * k : 0);
  const gap = capH > 0 ? 26 * k : 0;
  const blockH = cardH + gap + capH;
  const mx = scale.safe.x * W;
  // the side: the right, unless the faces / lettering under it sit there and the left is clearer
  const avoid = (Array.isArray(overlay.avoid) ? overlay.avoid : []).map((b) => rect(b.x * W, b.y * H, b.w * W, b.h * H));
  const top = Math.max(0.08 * H, (H - blockH) / 2 - 0.02 * H);
  // (inset a little from the safe margin: the turn toward the viewer brings the near edge out)
  const rightBox = rect(W - mx - cardW - 24 * k, top, cardW, blockH);
  const leftBox = rect(mx + 24 * k, top, cardW, blockH);
  const hit = (b: ReturnType<typeof rect>) => avoid.reduce((a, x) => a + overlapArea(b, x), 0);
  const right = !(hit(rightBox) > 0 && hit(leftBox) < hit(rightBox) * 0.5);
  const x0 = right ? rightBox.x : leftBox.x;
  const side = right ? 1 : -1;
  const e = prog(f, 2, 26, S, expoOut);
  const b = prog(f, 2, 30, S, (u) => backOut(u, 1.15));
  const x = cubicIn(clamp01(out * 1.15));
  const hold = idle(f, 34 * S, dur);
  const rotY = side * (lerp(-40, -11, b) + 3 * hold - 26 * x);
  const rotZ = side * (lerp(7, -2.5, b) + 1.5 * x);
  const rotX = lerp(9, 3.5, b);
  const tx = side * ((1 - e) * 0.42 * W + x * 0.36 * W);
  const ty = -6 * k * hold;
  const o = clamp01(e * 2.2) * (1 - clamp01(x * 1.6));
  const shade = prog(f, 0, 16, S, cubicOut) * (1 - clamp01(out * 1.2));
  const glint = clamp01((f / S - 30) / 22);
  const capO = 1 - clamp01(out * 1.4);
  return (
    <AbsoluteFill>
      {/* the footage on the card's side falls back a little */}
      <AbsoluteFill style={{ opacity: shade, background: `radial-gradient(ellipse 60% 85% at ${right ? 78 : 22}% 50%, `
        + "rgba(4,5,8,0.5) 0%, rgba(4,5,8,0.22) 55%, rgba(4,5,8,0) 100%)" }} />
      <div style={{ position: "absolute", left: x0, top, width: cardW, height: cardH, perspective: 1600 * k }}>
        {/* the long shadow, on the ground under the card */}
        <div style={{ position: "absolute", left: -30 * k * side, top: 44 * k, width: cardW, height: cardH, borderRadius: 6 * k,
          background: "rgba(0,0,0,0.6)", filter: `blur(${(38 * k).toFixed(1)}px)`, opacity: o * 0.95,
          transform: `translateX(${tx.toFixed(1)}px) translateY(${ty.toFixed(1)}px) rotateZ(${rotZ.toFixed(3)}deg)` }} />
        <div style={{ position: "absolute", inset: 0, opacity: o, transformStyle: "preserve-3d",
          transform: `translateX(${tx.toFixed(1)}px) translateY(${ty.toFixed(1)}px) rotateX(${rotX.toFixed(3)}deg) `
            + `rotateY(${rotY.toFixed(3)}deg) rotateZ(${rotZ.toFixed(3)}deg)` }}>
          <div style={{ position: "absolute", inset: 0, borderRadius: 4 * k, background: "linear-gradient(160deg, #f7f4ec 0%, #ece7dc 100%)",
            boxShadow: `0 ${(2 * k).toFixed(1)}px ${(6 * k).toFixed(1)}px rgba(0,0,0,0.35)` }} />
          <div style={{ position: "absolute", left: border, top: border, width: photoW, height: photoH, overflow: "hidden",
            background: "#14161b" }}>
            <Img src={pic.url} style={{ width: "100%", height: "100%", objectFit: "cover", filter: "saturate(0.9) contrast(1.05)",
              transform: `scale(${(1.02 + 0.03 * hold).toFixed(4)})` }} />
            {/* the print's gloss: one light sweep on landing */}
            {glint > 0 && glint < 1 ? (
              <div style={{ position: "absolute", inset: 0, mixBlendMode: "screen", opacity: 0.55,
                background: `linear-gradient(115deg, transparent ${(cubicInOut(glint) * 160 - 60).toFixed(1)}%, `
                  + `rgba(255,255,255,0.55) ${(cubicInOut(glint) * 160 - 45).toFixed(1)}%, transparent ${(cubicInOut(glint) * 160 - 30).toFixed(1)}%)` }} />
            ) : null}
            <div style={{ position: "absolute", inset: 0, boxShadow: "inset 0 0 0 1px rgba(0,0,0,0.25)" }} />
          </div>
        </div>
      </div>
      {capH > 0 ? (
        <div style={{ position: "absolute", left: x0, top: top + cardH + gap, width: cardW, opacity: capO }}>
          {kicker ? (
            <div style={{ height: kSize, marginBottom: 12 * k }}>
              <Caps text={kicker} size={kSize} color={hot} at={18} out={out} k={k} />
            </div>
          ) : null}
          {cap ? cap.lines.map((ln, i) => (
            <div key={i} style={{ height: cap.size * 1.18 }}>
              <KineticLine text={ln} font={GROTESK} weight={700} size={cap.size} tracking={-0.01} color={WHITE} preset="focus"
                timing={{ at: 20 + i * 4, gap: 2 }} out={out} shadow={softShadow(k, 0.6)} />
            </div>
          )) : null}
          {source ? (
            <div style={{ height: sSize, marginTop: 12 * k }}>
              <Caps text={source} size={sSize} color={DIM} at={30} out={out} k={k} tracking={0.14} weight={600} />
            </div>
          ) : null}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== kt-then-now
/** A small glass chip with a kicker over a big line (a year), opening from its side. */
const Chip: React.FC<{ x: number; y: number; kicker: string; line: string; right: boolean; at: number; out: number; k: number;
  hot: string; kSize: number; lSize: number }> = ({ x, y, kicker, line, right, at, out, k, hot, kSize, lSize }) => {
  const padX = 0.42 * lSize, padY = 0.3 * lSize;
  const lw = line ? riseWidth(line, GROTESK, lSize, 800) : 0;
  const w = Math.max(lw, kicker ? capsWidth(kicker, kSize) : 0) + padX * 2;
  const h = padY * 2 + (kicker ? kSize + 0.22 * lSize : 0) + (line ? lSize * 1.18 : 0);
  return <ChipAt x={right ? x - w : x} y={y} w={w} h={h} kicker={kicker} line={line} right={right} at={at} out={out} k={k}
    hot={hot} kSize={kSize} lSize={lSize} padX={padX} padY={padY} />;
};
const ChipAt: React.FC<{ x: number; y: number; w: number; h: number; kicker: string; line: string; right: boolean; at: number;
  out: number; k: number; hot: string; kSize: number; lSize: number; padX: number; padY: number }> =
  ({ x, y, w, h, kicker, line, right, at, out, k, hot, kSize, lSize, padX, padY }) => {
    const f = useCurrentFrame();
    const S = useVideoConfig().fps / 30;
    return (
      <Glass x={x} y={y} w={w} h={h} k={k} p={prog(f, at, 14, S, expoOut)} out={out} right={right} radius={12}>
        <div style={{ position: "absolute", left: padX, top: padY }}>
          {kicker ? (
            <div style={{ height: kSize, marginBottom: 0.22 * lSize }}>
              <Caps text={kicker} size={kSize} color={hot} at={at + 3} out={out} k={k} />
            </div>
          ) : null}
          {line ? <RiseLine text={line} size={lSize} font={GROTESK} weight={800} at={at + 5} out={out} k={k} /> : null}
        </div>
      </Glass>
    );
  };

/** The slider's handle: a frosted disc with a white ring and two triangles pointing apart. */
const Handle: React.FC<{ x: number; y: number; d: number; k: number; hot: string; o: number; s: number }> = ({ x, y, d, k, hot, o, s }) => {
  const t = d * 0.16;
  return (
    <div style={{ position: "absolute", left: x - d / 2, top: y - d / 2, width: d, height: d, opacity: o,
      transform: `scale(${s.toFixed(4)})` }}>
      <div style={{ position: "absolute", inset: 0, borderRadius: "50%", background: "rgba(14,16,20,0.62)",
        backdropFilter: `blur(${(10 * k).toFixed(1)}px)`, WebkitBackdropFilter: `blur(${(10 * k).toFixed(1)}px)`,
        boxShadow: `inset 0 0 0 ${(3 * k).toFixed(1)}px #fff, 0 ${(6 * k).toFixed(1)}px ${(18 * k).toFixed(1)}px rgba(0,0,0,0.5)` }} />
      <svg width={d} height={d} style={{ position: "absolute", inset: 0 }}>
        <path d={`M${d / 2 - t * 0.55},${d / 2 - t} L${d / 2 - t * 0.55 - t * 1.25},${d / 2} L${d / 2 - t * 0.55},${d / 2 + t} Z`} fill={hot} />
        <path d={`M${d / 2 + t * 0.55},${d / 2 - t} L${d / 2 + t * 0.55 + t * 1.25},${d / 2} L${d / 2 + t * 0.55},${d / 2 + t} Z`} fill={hot} />
      </svg>
    </div>
  );
};

/**
 * Two pictures of one place, full frame. The earlier one first (a touch less
 * colour), its chip top left ("THEN" over its year); a divider sweeps in from
 * the right (frames 16-46, cubic in-out) and uncovers the later one behind it,
 * its chip top right; the handle then eases a little left and back once, as a
 * hand would test it (only when the look holds long enough). Both pictures push
 * in slowly while it holds. The years: items[0] / items[1] (label), else label
 * and subtitle; without them the chips say THEN and NOW.
 */
const ThenNow: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, hot, out, ks } = useLook(overlay, accent);
  const pics = picsOf(overlay);
  const items = Array.isArray(overlay.items) ? overlay.items : [];
  const yThen = str(items[0]?.label) || str(overlay.label);
  const yNow = str(items[1]?.label) || str(overlay.subtitle);
  const title = str(overlay.text);
  if (!pics.length) return null;
  const U = unitOf(W, H);
  const kSize = capFont(scale.pack.packKicker.share, U, ks);
  const lSize = capFont(scale.pack.mapLabel.share, U, ks);
  const mx = scale.safe.x * W;
  const t = f / S;
  const len = dur / S;
  // the divider: in from the right edge to the middle, then (on a long enough look) a small test left and back
  const sweep = prog(f, 16, 30, S, cubicInOut);
  let dx = lerp(1.03, 0.5, sweep);
  if (len >= 150 && t > 70) {
    const a = clamp01((t - 70) / 34), b2 = clamp01((t - 104) / 40);
    dx = 0.5 - 0.09 * sineInOut(a) + 0.09 * sineInOut(b2);
  }
  const divX = dx * W;
  const hold = idle(f, 0, dur);
  const push = (1.03 + 0.05 * hold).toFixed(4);
  const xo = 1 - clamp01(out * 1.3);
  const nowShown = clamp01((1.03 - dx) / 0.25);
  const titleEl = title ? (
    <div style={{ position: "absolute", left: mx, top: lowLineY(overlay, mx, capsWidth(title, kSize * 1.1), kSize * 1.1, W, H, k),
      opacity: xo }}>
      <Caps text={title} size={kSize * 1.1} color={WHITE} at={10} out={out} k={k} tracking={0.2} />
    </div>
  ) : null;
  // One picture left (the other did not load, components/motion/pictureGuard.tsx): it alone, full frame, with the
  // title - no divider, no then/now chips - never an empty full-frame moment over the softened footage.
  if (pics.length === 1) {
    return (
      <AbsoluteFill style={{ background: "#07090c" }}>
        <AbsoluteFill style={{ overflow: "hidden" }}>
          <Img src={pics[0].url} style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${push})` }} />
        </AbsoluteFill>
        <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(4,5,8,0) 62%, rgba(4,5,8,0.42) 100%)",
          opacity: prog(f, 0, 14, S, cubicOut) * xo }} />
        {titleEl}
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill style={{ background: "#07090c" }}>
      <AbsoluteFill style={{ overflow: "hidden" }}>
        <Img src={pics[0].url} style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${push})`,
          filter: "saturate(0.8) contrast(1.04) brightness(0.96)" }} />
      </AbsoluteFill>
      <AbsoluteFill style={{ overflow: "hidden", clipPath: `inset(0 0 0 ${Math.max(0, divX).toFixed(1)}px)` }}>
        <Img src={pics[1].url} style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${push})` }} />
      </AbsoluteFill>
      {/* a soft shade at the top for the chips, at the bottom for the title */}
      <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(4,5,8,0.45) 0%, rgba(4,5,8,0) 26%, rgba(4,5,8,0) 72%, rgba(4,5,8,0.42) 100%)",
        opacity: prog(f, 0, 14, S, cubicOut) * xo }} />
      {/* the divider and its handle */}
      {dx < 1.02 ? (
        <>
          <div style={{ position: "absolute", left: divX - 1.5 * k, top: 0, width: Math.max(2, 3 * k), height: H, background: "#fff",
            boxShadow: `0 0 ${(14 * k).toFixed(1)}px rgba(0,0,0,0.55), 0 0 ${(4 * k).toFixed(1)}px ${rgba(hot, 0.6)}`, opacity: xo }} />
          <Handle x={divX} y={H * 0.5} d={66 * k} k={k} hot={hot} o={xo * prog(f, 20, 10, S, cubicOut)}
            s={0.7 + 0.3 * prog(f, 20, 14, S, (u) => backOut(u, 1.5))} />
        </>
      ) : null}
      <Chip x={mx} y={0.09 * H} kicker="Then" line={yThen} right={false} at={6} out={out} k={k} hot={hot} kSize={kSize} lSize={lSize} />
      {nowShown > 0 ? (
        <Chip x={W - mx} y={0.09 * H} kicker="Now" line={yNow} right={true} at={34} out={out} k={k} hot={hot} kSize={kSize} lSize={lSize} />
      ) : null}
      {titleEl}
    </AbsoluteFill>
  );
};

// ================================================================== kt-two-places
/**
 * Two places side by side, full frame, on a diagonal split: the first picture
 * slides in from the left, the second from the right (frames 0-22, expo-out),
 * an accent divider draws down the split (12-32) with a soft glow; each place's
 * name rises on glass at its lower corner (the name, its region); when both
 * places are known the miles between them sit on the divider (from 34). Both
 * pictures push in slowly while it holds; it leaves sliding apart.
 */
const TwoPlaces: Look = ({ overlay, accent }) => {
  const { f, S, k, W, H, dur, hot, out, ks } = useLook(overlay, accent);
  const pics = picsOf(overlay);
  const items = Array.isArray(overlay.items) ? overlay.items : [];
  const locs = placesOf(overlay.locations, 2);
  const nameAt = (i: number) => {
    const fromItem = str(items[i]?.label);
    const fromLoc = locs[i] ? placeName(locs[i].label) : { name: "", region: "" };
    return { name: fromItem || fromLoc.name, region: str(items[i]?.text) || fromLoc.region };
  };
  const A = nameAt(0), B = nameAt(1);
  if (!pics.length) return null;
  const U = unitOf(W, H);
  const kSize = capFont(scale.pack.packKicker.share, U, ks);
  const nSize = capFont(scale.pack.placeName.share, U, ks);
  const mx = scale.safe.x * W;
  const slant = 0.06 * W;
  const inA = prog(f, 0, 22, S, expoOut), inB = prog(f, 4, 22, S, expoOut);
  const x = cubicIn(clamp01(out * 1.2));
  const offA = (-(1 - inA) * 0.5 - x * 0.12) * W, offB = ((1 - inB) * 0.5 + x * 0.12) * W;
  const hold = idle(f, 0, dur);
  const push = (1.04 + 0.05 * hold).toFixed(4);
  const line = prog(f, 12, 20, S, cubicInOut) * (1 - clamp01(x * 1.4));
  const top: [number, number] = [W / 2 + slant, 0], bot: [number, number] = [W / 2 - slant, H];
  const miles = locs.length >= 2 ? milesBetween(locs[0], locs[1]) : null;
  const dist = miles ? distanceText(miles, num(overlay.value), overlay.suffix) : "";
  const distIn = prog(f, 34, 14, S, (u) => backOut(u, 1.4)) * (1 - clamp01(x * 1.5));
  // One picture left (the other did not load, components/motion/pictureGuard.tsx): which place it shows is not
  // known any more, so it plays full frame under one quiet line naming both places (and the miles between).
  if (pics.length === 1) {
    const names = [A.name, B.name].filter(Boolean).join(" – ") + (dist ? `  ·  ${dist}` : "");
    return (
      <AbsoluteFill>
        <AbsoluteFill style={{ overflow: "hidden" }}>
          <Img src={pics[0].url} style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${push})` }} />
        </AbsoluteFill>
        <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(4,5,8,0) 60%, rgba(4,5,8,0.45) 100%)",
          opacity: prog(f, 6, 16, S, cubicOut) * (1 - x) }} />
        {names ? (
          <div style={{ position: "absolute", left: mx, top: lowLineY(overlay, mx, capsWidth(names, kSize * 1.1), kSize * 1.1, W, H, k),
            opacity: 1 - x }}>
            <Caps text={names} size={kSize * 1.1} color={WHITE} at={10} out={out} k={k} tracking={0.2} />
          </div>
        ) : null}
      </AbsoluteFill>
    );
  }
  const tag = (p: { name: string; region: string }, right: boolean, at: number) => {
    const nw = riseWidth(p.name.toUpperCase(), GROTESK, nSize, 800, 0.01);
    const rw = p.region ? capsWidth(p.region, kSize) : 0;
    const padX = 0.5 * nSize, padY = 0.36 * nSize;
    const w = Math.max(nw, rw) + padX * 2;
    const h = padY * 2 + nSize * 1.2 + (p.region ? kSize + 0.2 * nSize : 0);
    const gx = right ? W - mx - w : mx;
    let gy = H - 0.12 * H - h;
    for (const b of Array.isArray(overlay.avoid) ? overlay.avoid : []) {
      const bx = b.x * W, by = b.y * H, bw = b.w * W, bh = b.h * H;
      if (bx < gx + w && bx + bw > gx && by < gy + h && by + bh > gy) gy = Math.max(0.1 * H, Math.min(gy, by - h - 14 * k));
    }
    return (
      <Glass x={gx} y={gy} w={w} h={h} k={k} p={prog(f, at, 14, S, expoOut)} out={out} right={right} radius={12}>
        <div style={{ position: "absolute", left: padX, top: padY }}>
          <RiseLine text={p.name.toUpperCase()} size={nSize} font={GROTESK} weight={800} at={at + 3} out={out} k={k} tracking={0.01} />
          {p.region ? (
            <div style={{ height: kSize, marginTop: 0.2 * nSize }}>
              <Caps text={p.region} size={kSize} color={hot} at={at + 8} out={out} k={k} />
            </div>
          ) : null}
        </div>
      </Glass>
    );
  };
  const clipA = `polygon(0 0, ${top[0]}px 0, ${bot[0]}px ${H}px, 0 ${H}px)`;
  const clipB = `polygon(${top[0]}px 0, ${W}px 0, ${W}px ${H}px, ${bot[0]}px ${H}px)`;
  const midX = (top[0] + bot[0]) / 2, midY = H / 2;
  return (
    <AbsoluteFill>
      {/* (no backdrop: while the two halves slide in, the softened footage shows between them) */}
      <AbsoluteFill style={{ clipPath: clipA, transform: `translateX(${offA.toFixed(1)}px)` }}>
        <Img src={pics[0].url} style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${push})`,
          transformOrigin: "30% 50%" }} />
      </AbsoluteFill>
      <AbsoluteFill style={{ clipPath: clipB, transform: `translateX(${offB.toFixed(1)}px)` }}>
        <Img src={pics[1].url} style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${push})`,
          transformOrigin: "70% 50%" }} />
      </AbsoluteFill>
      <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(4,5,8,0) 55%, rgba(4,5,8,0.5) 100%)",
        opacity: prog(f, 6, 16, S, cubicOut) * (1 - x) }} />
      <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
        <line x1={top[0]} y1={top[1]} x2={lerp(top[0], bot[0], line)} y2={lerp(top[1], bot[1], line)} stroke={rgba(hot, 0.45)}
          strokeWidth={14 * k} style={{ filter: `blur(${(6 * k).toFixed(1)}px)` }} />
        <line x1={top[0]} y1={top[1]} x2={lerp(top[0], bot[0], line)} y2={lerp(top[1], bot[1], line)} stroke={hot}
          strokeWidth={Math.max(2.5, 4 * k)} />
      </svg>
      {A.name ? tag(A, false, 14) : null}
      {B.name ? tag(B, true, 20) : null}
      {dist && distIn > 0.001 ? (
        <div style={{ position: "absolute", left: midX, top: midY, transform: `translate(-50%, -50%) scale(${(0.7 + 0.3 * distIn).toFixed(4)})`,
          opacity: clamp01(distIn * 1.4), padding: `${10 * k}px ${22 * k}px`, borderRadius: 40 * k, background: "rgba(10,12,16,0.78)",
          boxShadow: `inset 0 0 0 ${(2.5 * k).toFixed(1)}px ${hot}, 0 ${(10 * k).toFixed(1)}px ${(28 * k).toFixed(1)}px rgba(0,0,0,0.5)`,
          fontFamily: GROTESK, fontWeight: 800, fontSize: kSize * 1.5, color: WHITE, whiteSpace: "nowrap", letterSpacing: "0.02em",
          fontVariantNumeric: "tabular-nums" }}>{dist}</div>
      ) : null}
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "kt-evidence": guard(Evidence),
  "kt-then-now": guard(ThenNow),
  "kt-two-places": guard(TwoPlaces),
};

