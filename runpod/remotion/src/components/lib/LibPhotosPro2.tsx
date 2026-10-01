import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { ANTON, LABEL, MONO, SERIF, SERIF_ITALIC, SUBLINE, TYPEWRITER } from "../fonts";
import { useK } from "../pro/ProGraphics";
import { LOOP, markerPath, poly } from "./LibVideoMarks";
import { ANTON_TRACK, CaptionShade, Cover, EXPO_IN, EXPO_OUT, FillPhoto, FullPhoto, Grain, IN_OUT, PaperGrain, PxCaption,
  Rise, SHADOW, anchorOf, asWritten, caps, clamp, clamp01, cut, fitAnton, hasAnchor, hasCaption, hash01, hashStr, itemsOf,
  lerp, photoOf, photosOf, printAspect, ramp, str, uidOf, useLife, useOut, usePhotoInfo, yearIn, zoomRoom, type CSS,
  type Look, type Pt } from "./LibPhotosPro";

/**
 * Photo looks, pro set II (family "px-", the shared pieces in LibPhotosPro.tsx):
 * the archive - the photograph as an object that was printed, filed and
 * found again - and the looks drawn around several pictures.
 *
 *   px-contact-sheet     a black-and-white contact sheet, a grease-pencil box round one frame, the camera
 *                        pushes into it and it turns into the photo in colour
 *   px-negative-flip     the photo as a colour negative on a light table flips to the positive under a
 *                        flash and fills the frame
 *   px-darkroom          a print develops in a tray under the red safelight; the room light comes on
 *   px-slide-projector   a slide drops into a projector: the picture lands on the screen through dusty
 *                        light and pulls into focus
 *   px-flatbed-scan      a faded print on a scanner's glass: the light bar passes and leaves it restored,
 *                        then the scan fills the frame
 *   px-shutter-burst     three frames of a burst, each closer on the point, the shutter blinking between them
 *   px-album-page        a glassine sheet lifts off an album page: the print in its black corners, a typed label
 *   px-archive-stamp     an aged print slides onto the desk and an ARCHIVE rubber stamp comes down on it
 *   px-book-plate        a page of an old book turns over onto a photographic plate and its caption
 *   px-archive-envelope  the print slides up out of a kraft archive envelope with a typed label
 *   px-drying-line       the print slides along a darkroom drying line on its clothes-pegs and swings to rest
 *   px-dated-cascade     two or three prints land in turn along a time rail, each over its date
 *   px-then-now          a lit diagonal seam sweeps across: the earlier picture on one side, the later on the other
 *
 * The props are LibPhotosPro's. Everything here leaves through the
 * overlay's own fade unless its registry exit is "none".
 */

// ================================================================== px-contact-sheet
/** A hand-drawn box round a rect: four slightly bowed sides, the pen overshooting where it started. */
const penBox = (x: number, y: number, w: number, h: number, seed: number, k: number): Pt[] => {
  const pts: Pt[] = [];
  const j = (i: number) => (hash01(seed + i * 3.1) - 0.5) * 7 * k;
  const corners: Pt[] = [{ x: x - 4 * k, y: y + 2 * k }, { x: x + w + 3 * k, y: y - 3 * k }, { x: x + w + 2 * k, y: y + h + 4 * k },
    { x: x - 3 * k, y: y + h + 1 * k }, { x: x + 2 * k, y: y - 4 * k }, { x: x + w * 0.28, y: y - 6 * k }];
  for (let s = 0; s < corners.length - 1; s++) {
    const a = corners[s], b = corners[s + 1];
    for (let i = 0; i < 12; i++) {
      const t = i / 12;
      const bow = Math.sin(t * Math.PI) * 4 * k * (s % 2 ? -1 : 1);
      const nx = -(b.y - a.y), ny = b.x - a.x;
      const nl = Math.hypot(nx, ny) || 1;
      pts.push({ x: a.x + (b.x - a.x) * t + (nx / nl) * bow + j(s * 12 + i) * 0.2, y: a.y + (b.y - a.y) * t + (ny / nl) * bow + j(s * 12 + i + 7) * 0.2 });
    }
  }
  pts.push(corners[corners.length - 1]);
  return pts;
};

// The contact sheet holds; a red grease pencil boxes one frame (6 -> 18, sfx_at 16); the camera pushes into
// that frame (20 -> 38) as it turns from the black-and-white print into the photo in colour; the caption
// rises from 40.
const ContactSheet: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H } = useVideoConfig();
  const k = useK();
  const q = useOut(12);
  const life = useLife();
  const src = photoOf(overlay);
  const info = usePhotoInfo(src);
  if (!src) return null;
  const seed = hashStr(src) % 97;
  const fw = 300 * k, fh = 200 * k, gap = 22 * k, reb = 36 * k, sg = 24 * k, mx = 62 * k, my = 58 * k;
  const stripW = 4 * fw + 5 * gap, stripH = fh + 2 * reb;
  const SW = stripW + 2 * mx, SH = 3 * stripH + 2 * sg + 2 * my;
  const sx = (W - SW) / 2, sy = (H - SH) / 2;
  const ROT = -1.8;
  const SEL = { r: 1, c: 2 };
  const rect = (r: number, c: number) => ({ x: mx + gap + c * (fw + gap), y: my + r * (stripH + sg) + reb, w: fw, h: fh });
  const sel = rect(SEL.r, SEL.c);
  // The chosen frame's centre on screen (the sheet turned ROT about its centre).
  const a = (ROT * Math.PI) / 180;
  const lx = sel.x + fw / 2 - SW / 2, ly = sel.y + fh / 2 - SH / 2;
  const fc = { x: sx + SW / 2 + lx * Math.cos(a) - ly * Math.sin(a), y: sy + SH / 2 + lx * Math.sin(a) + ly * Math.cos(a) };
  const S = Math.max(W / fw, H / fh) * 1.004;
  const push = ramp(frame, 20, 18, IN_OUT);
  const s = Math.pow(S, push);
  // The camera centre slides to the frame in step with the zoom, so the frame grows in place.
  const wgt = (s - 1) / (S - 1);
  const c = { x: fc.x + (W / 2 - fc.x) * (1 - wgt), y: fc.y + (H / 2 - fc.y) * (1 - wgt) };
  const cam = `translate(${(W / 2).toFixed(2)}px, ${(H / 2).toFixed(2)}px) scale(${s.toFixed(5)}) rotate(${(-ROT * push).toFixed(4)}deg) translate(${(-c.x).toFixed(2)}px, ${(-c.y).toFixed(2)}px)`;
  const draw = ramp(frame, 6, 12, Easing.bezier(0.45, 0, 0.2, 1));
  const color = ramp(frame, 26, 12, IN_OUT);
  const final = ramp(frame, 35, 6, Easing.linear);
  const zr = zoomRoom(info.w, 1.7);
  const crop = (i: number) => {
    // A photographer's roll: the same scene framed again and again, a little closer, a little aside.
    const z = 1.06 + (zr - 1.06) * hash01(seed + i * 5.3);
    return { z, ox: (hash01(seed + i * 2.9) - 0.5) * 34, oy: (hash01(seed + i * 4.7) - 0.5) * 30,
      b: 0.86 + 0.24 * hash01(seed + i * 8.1) };
  };
  const holes = (y: number, key: string) => {
    const out: React.ReactNode[] = [];
    for (let x = 12 * k, i = 0; x < stripW - 20 * k; x += 34 * k, i++) {
      out.push(<div key={`${key}${i}`} style={{ position: "absolute", left: x, top: y, width: 16 * k, height: 21 * k, borderRadius: 3.5 * k,
        background: "#060606", boxShadow: "inset 0 0 2px rgba(255,255,255,.08)" }} />);
    }
    return out;
  };
  const cap_ = hasCaption(overlay);
  const boxPts = penBox(sel.x - 15 * k, sel.y - 14 * k, fw + 30 * k, fh + 28 * k, seed, k);
  return (
    <AbsoluteFill style={{ background: "#0c0b0a", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: cam, transformOrigin: "0 0", opacity: 1 - final }}>
        <AbsoluteFill style={{ background: "radial-gradient(ellipse at 45% 40%, #3a3128 0%, #1d1813 60%, #0b0907 100%)" }} />
        <div style={{ position: "absolute", left: sx, top: sy, width: SW, height: SH, transform: `rotate(${ROT}deg)`,
          background: "linear-gradient(170deg, #f4f1ea 0%, #ebe6dc 100%)", boxShadow: `0 ${26 * k}px ${60 * k}px rgba(0,0,0,.6)` }}>
          <PaperGrain w={SW} h={SH} seed={seed} opacity={0.1} />
          {[0, 1, 2].map((r) => (
            <div key={r} style={{ position: "absolute", left: mx + (hash01(seed + r) - 0.5) * 6 * k, top: my + r * (stripH + sg),
              width: stripW, height: stripH, background: "#232321", transform: `rotate(${((hash01(seed + r * 9) - 0.5) * 0.5).toFixed(3)}deg)` }}>
              {holes(7 * k, `t${r}`)}
              {holes(stripH - 28 * k, `b${r}`)}
              <div style={{ position: "absolute", left: 20 * k, top: stripH - 34 * k + 22 * k, fontFamily: MONO, fontSize: 11 * k, letterSpacing: "0.12em",
                color: "rgba(235,235,225,.55)", whiteSpace: "nowrap" }}>
                {[0, 1, 2, 3].map((cc) => `${r * 4 + cc + 12} ▸ ${r * 4 + cc + 12}A`).join("            ")}
              </div>
              <div style={{ position: "absolute", left: 60 * k, top: 7 * k + 2 * k, fontFamily: MONO, fontSize: 10 * k, letterSpacing: "0.3em",
                color: "rgba(235,235,225,.4)", whiteSpace: "nowrap" }}>SAFETY FILM 400</div>
              {[0, 1, 2, 3].map((cc) => {
                const f = rect(r, cc);
                const chosen = r === SEL.r && cc === SEL.c;
                const v = crop(r * 4 + cc);
                return (
                  <div key={cc} style={{ position: "absolute", left: f.x - mx, top: reb, width: fw, height: fh, overflow: "hidden", background: "#111" }}>
                    <div style={{ position: "absolute", inset: 0, transform: chosen ? undefined : `scale(${v.z.toFixed(3)}) translate(${v.ox.toFixed(1)}%, ${v.oy.toFixed(1)}%)` }}>
                      <FillPhoto src={src} ar={info.ar} w={fw} h={fh}
                        filter={`grayscale(1) contrast(1.16) brightness(${(chosen ? 1 : v.b).toFixed(3)})`} />
                    </div>
                    {chosen && color > 0.001 ? (
                      <div style={{ position: "absolute", inset: 0, opacity: color }}>
                        <FillPhoto src={src} ar={info.ar} w={fw} h={fh} filter="contrast(1.04)" />
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          ))}
          <svg width={SW} height={SH} style={{ position: "absolute", left: 0, top: 0, overflow: "visible", opacity: 1 - ramp(frame, 23, 7, Easing.linear) }}>
            <path d={markerPath(poly(boxPts), 0, draw, 11 * k, LOOP, seed)} fill="#d3212b" opacity={0.92} />
          </svg>
        </div>
      </AbsoluteFill>
      {final > 0.001 ? (
        <AbsoluteFill style={{ opacity: final, transform: `scale(${(1 + 0.04 * life).toFixed(4)})` }}>
          <FullPhoto src={src} ar={info.ar} filter="contrast(1.04)" />
        </AbsoluteFill>
      ) : null}
      <CaptionShade show={cap_ && final > 0.5} strength={0.6} />
      <PxCaption ov={overlay} at={40} q={q} accent={accent} />
    </AbsoluteFill>
  );
};

// ================================================================== px-negative-flip
// The photo lies on a light table as a colour negative, its neighbours either side (0 -> 15, drifting);
// a flash flips it to the positive at 16 (sfx_at 16); the film falls away as it fills the frame (18 -> 34);
// the caption rises from 34.
const NegativeFlip: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H } = useVideoConfig();
  const k = useK();
  const q = useOut(12);
  const life = useLife();
  const src = photoOf(overlay);
  const info = usePhotoInfo(src);
  if (!src) return null;
  const seed = hashStr(src) % 97;
  const FLIP = 16;
  const fw = 960 * k, fh = 640 * k, gap = 44 * k, reb = 92 * k;
  const stripH = fh + 2 * reb;
  const top = (H - stripH) / 2;
  const drift = interpolate(frame, [0, FLIP], [40 * k, 0], { ...clamp, easing: Easing.out(Easing.quad) });
  const flipped = frame >= FLIP;
  const flash = interpolate(frame, [FLIP - 1, FLIP + 1, FLIP + 9], [0, 0.85, 0], clamp);
  const grow = ramp(frame, FLIP + 2, 16, IN_OUT);
  const S = Math.max(W / fw, H / fh) * 1.003;
  const s = Math.pow(S, grow) * (1 + 0.035 * life);
  const zr = zoomRoom(info.w, 1.5);
  const neg = "invert(1) saturate(.85) contrast(.92)";
  const frameNode = (i: number) => {
    const chosen = i === 0;
    const z = chosen ? 1 : 1.1 + (zr - 1.1) * hash01(seed + i);
    const x = W / 2 - fw / 2 + i * (fw + gap);
    return (
      <div key={i} style={{ position: "absolute", left: x, top: top + reb, width: fw, height: fh, overflow: "hidden", background: "#2a1306" }}>
        <div style={{ position: "absolute", inset: 0, transform: `scale(${z.toFixed(3)})` }}>
          <FillPhoto src={src} ar={info.ar} w={fw} h={fh} filter={chosen && flipped ? "contrast(1.05)" : neg} />
        </div>
        {/* The orange mask of colour negative film. */}
        {!(chosen && flipped) ? <div style={{ position: "absolute", inset: 0, background: "rgba(222,128,58,.78)", mixBlendMode: "multiply" }} /> : null}
      </div>
    );
  };
  const holes: React.ReactNode[] = [];
  for (let x = -W, i = 0; x < 2 * W; x += 50 * k, i++) {
    holes.push(<div key={`a${i}`} style={{ position: "absolute", left: x, top: 22 * k, width: 26 * k, height: 36 * k, borderRadius: 5 * k, background: "#f4f8fb" }} />);
    holes.push(<div key={`b${i}`} style={{ position: "absolute", left: x, top: stripH - 58 * k, width: 26 * k, height: 36 * k, borderRadius: 5 * k, background: "#f4f8fb" }} />);
  }
  const film = 1 - grow;
  const cap_ = hasCaption(overlay);
  return (
    <AbsoluteFill style={{ background: "#e9eef1", overflow: "hidden" }}>
      {/* The light table: an even cold glow, brighter at the middle. */}
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 50%, #f7fafc 0%, #e3e9ed 70%, #cfd6db 100%)", opacity: film }} />
      <AbsoluteFill style={{ transform: `translateX(${drift.toFixed(2)}px)` }}>
        <AbsoluteFill style={{ transform: `scale(${s.toFixed(5)})`, transformOrigin: "50% 50%" }}>
          <div style={{ position: "absolute", left: -W, top, width: 3 * W, height: stripH, background: "rgba(176,92,36,.92)", opacity: film,
            boxShadow: "0 6px 24px rgba(0,0,0,.25)" }}>
            <div style={{ position: "absolute", inset: 0, transform: `translateX(${W}px)` }}>
              {holes}
              <div style={{ position: "absolute", left: W / 2 - fw / 2 + 30 * k, top: stripH - 86 * k, fontFamily: MONO, fontSize: 18 * k,
                letterSpacing: "0.2em", color: "rgba(60,20,4,.7)", whiteSpace: "nowrap" }}>14 ▸ 14A                 SAFETY FILM</div>
            </div>
          </div>
          <div style={{ position: "absolute", inset: 0 }}>
            {[-1, 1].map((i) => <div key={i} style={{ opacity: film }}>{frameNode(i)}</div>)}
            {frameNode(0)}
          </div>
        </AbsoluteFill>
      </AbsoluteFill>
      <AbsoluteFill style={{ background: "#fff", opacity: flash }} />
      <CaptionShade show={cap_ && grow > 0.6} strength={0.6} />
      <PxCaption ov={overlay} at={34} q={q} accent={accent} />
    </AbsoluteFill>
  );
};

// ================================================================== px-darkroom
// Under the red safelight a blank print in the tray develops (2 -> 22), the developer rocking over it;
// the room light comes on at 24 (sfx_at 24, the switch); the camera leans in; the caption rises from 28.
const Darkroom: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H, fps } = useVideoConfig();
  const k = useK();
  const q = useOut(12);
  const life = useLife();
  const src = photoOf(overlay);
  const info = usePhotoInfo(src);
  if (!src) return null;
  const LIGHT = 24;
  const dev = ramp(frame, 2, 20, Easing.bezier(0.3, 0, 0.3, 1));
  const on = ramp(frame, LIGHT, 6, EXPO_OUT);
  const t = frame / fps;
  const TW = 1640 * k, TH = 944 * k, TR = 48 * k, RIM = 34 * k;
  const pa = printAspect(info.ar);
  const B = 26 * k;
  let PW = 1180 * k, PH = PW / pa;
  if (PH > 760 * k) {
    PH = 760 * k;
    PW = PH * pa;
  }
  // The developer rocking: the print sways a hair under a sheen that rolls across the liquid.
  const rock = Math.sin(t * 2.1) * (1 - on) * 0.18;
  const sheenX = interpolate(frame, [0, 60], [-30, 130], clamp);
  const filter = `grayscale(1) contrast(${lerp(0.12, 1.14, dev).toFixed(3)}) brightness(${lerp(2.6, 1.0, dev).toFixed(3)})`;
  const cap_ = hasCaption(overlay);
  return (
    <AbsoluteFill style={{ background: "#0b0908", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${(1.02 + 0.08 * life * on + 0.0 * life).toFixed(4)})` }}>
        {/* The bench and the enamel tray. */}
        <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 46%, #2b2723 0%, #161412 62%, #090807 100%)" }} />
        <div style={{ position: "absolute", left: (W - TW) / 2, top: (H - TH) / 2, width: TW, height: TH, borderRadius: TR,
          background: "linear-gradient(160deg, #bdbbb5 0%, #9c9a94 100%)", boxShadow: `0 ${24 * k}px ${60 * k}px rgba(0,0,0,.7)` }}>
          <div style={{ position: "absolute", inset: RIM, borderRadius: TR - RIM / 2, overflow: "hidden",
            background: "linear-gradient(180deg, #8f938f 0%, #7d817e 100%)", boxShadow: `inset 0 ${10 * k}px ${30 * k}px rgba(0,0,0,.45)` }}>
            {/* The print under the liquid. */}
            <div style={{ position: "absolute", left: (TW - 2 * RIM - PW) / 2 - B, top: (TH - 2 * RIM - PH) / 2 - B, width: PW + 2 * B, height: PH + 2 * B,
              background: "#f6f5f1", transform: `rotate(${(-1.6 + rock).toFixed(3)}deg) translateY(${(Math.sin(t * 1.7) * 2 * k * (1 - on)).toFixed(2)}px)`,
              boxShadow: `0 ${3 * k}px ${10 * k}px rgba(0,0,0,.25)` }}>
              <div style={{ position: "absolute", left: B, top: B, width: PW, height: PH, overflow: "hidden", background: "#fff" }}>
                <FillPhoto src={src} ar={info.ar} w={PW} h={PH} filter={`${filter} blur(${(0.7 * (1 - on)).toFixed(2)}px)`} />
              </div>
            </div>
            {/* The liquid: a sheen rolling over it, a slight darkening at the edges. */}
            <div style={{ position: "absolute", inset: 0, opacity: 0.55, mixBlendMode: "screen", transform: `translateX(${sheenX.toFixed(2)}%)`,
              background: "linear-gradient(100deg, rgba(255,255,255,0) 30%, rgba(255,255,255,.22) 45%, rgba(255,255,255,0) 60%)" }} />
            <div style={{ position: "absolute", inset: 0, boxShadow: `inset 0 0 ${80 * k}px rgba(40,50,60,.35)` }} />
          </div>
        </div>
      </AbsoluteFill>
      {/* The safelight: the whole room in deep red until the light comes on. */}
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 70% 18%, rgb(210,40,22) 0%, rgb(150,18,10) 45%, rgb(70,4,2) 100%)",
        mixBlendMode: "multiply", opacity: 1 - on }} />
      <AbsoluteFill style={{ background: "rgba(0,0,0,.35)", opacity: 1 - on }} />
      <AbsoluteFill style={{ background: "#fff4e4", opacity: interpolate(frame, [LIGHT, LIGHT + 2, LIGHT + 9], [0, 0.16, 0], clamp) }} />
      <Grain opacity={0.06} />
      <CaptionShade show={cap_} strength={0.78 * on} />
      <PxCaption ov={overlay} at={28} q={q} accent={accent} />
    </AbsoluteFill>
  );
};

// ================================================================== px-slide-projector
// The lamp lights an empty screen; the slide drops in at 6 (sfx_at 6, the slide changer) through a beam of
// dust and pulls into focus by 22; the caption rises from 24.
const SlideProjector: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H, fps } = useVideoConfig();
  const k = useK();
  const q = useOut(12);
  const life = useLife();
  const src = photoOf(overlay);
  const info = usePhotoInfo(src);
  if (!src) return null;
  const seed = hashStr(src) % 97;
  const DROP = 6;
  const lamp = ramp(frame, 0, 4, Easing.linear);
  const inSlide = frame >= DROP;
  const fall = ramp(frame, DROP, 4, EXPO_OUT);
  const focus = ramp(frame, DROP + 2, 16, IN_OUT);
  const flick = inSlide ? [0.55, 1, 0.82, 1, 0.94, 1][Math.min(5, frame - DROP)] : 1;
  const SWd = 1500 * k, SHd = (SWd * 9) / 16;
  const scx = W / 2, scy = 466 * k;
  const left = scx - SWd / 2, top = scy - SHd / 2;
  const t = frame / fps;
  // The beam from the lens below the frame up to the screen.
  const lens = { x: W / 2, y: H + 140 * k };
  const beam = `polygon(${lens.x - 40 * k}px ${lens.y}px, ${lens.x + 40 * k}px ${lens.y}px, ${left + SWd}px ${top + SHd}px, ${left + SWd}px ${top}px, ${left}px ${top}px, ${left}px ${top + SHd}px)`;
  const motes = Array.from({ length: 26 }, (_, i) => {
    const u = hash01(seed + i * 3.3), v = hash01(seed + i * 7.9);
    const y = lerp(top + SHd + 40 * k, H + 40 * k, v) - ((t * (14 + 22 * u) * k) % (160 * k));
    const spread = (y - lens.y) / (top + SHd / 2 - lens.y);
    const x = lens.x + (u - 0.5) * SWd * clamp01(spread) * 0.9 + Math.sin(t * 0.8 + i) * 8 * k;
    const r = (1.4 + 2.6 * hash01(seed + i * 11)) * k;
    return <div key={i} style={{ position: "absolute", left: x, top: y, width: 2 * r, height: 2 * r, borderRadius: "50%",
      background: "rgba(255,240,215,.75)", filter: `blur(${(r * 0.6).toFixed(2)}px)`, opacity: (0.35 + 0.5 * hash01(seed + i * 13 + Math.floor(t * 6))) * lamp }} />;
  });
  const cap_ = hasCaption(overlay);
  return (
    <AbsoluteFill style={{ background: "#09090a", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${(1 + 0.035 * life).toFixed(4)})`, transformOrigin: `50% ${((scy / H) * 100).toFixed(1)}%` }}>
        {/* The wall and the screen's matte surface catching the lamp. */}
        <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 42%, #1c1b1a 0%, #0e0e0e 60%, #060606 100%)" }} />
        {/* The beam: blurred after it is cut to shape, so its edges melt into the dark. */}
        <AbsoluteFill style={{ filter: `blur(${34 * k}px)`, opacity: 0.8 * lamp }}>
          <AbsoluteFill style={{ clipPath: beam, background: "linear-gradient(0deg, rgba(255,236,206,.12) 0%, rgba(255,236,206,.045) 55%, rgba(255,236,206,.015) 100%)" }} />
        </AbsoluteFill>
        {motes}
        <div style={{ position: "absolute", left, top, width: SWd, height: SHd, overflow: "hidden", background: "#e8e0cf", opacity: lamp,
          boxShadow: `0 0 ${90 * k}px rgba(255,232,200,${(0.14 * lamp).toFixed(3)})` }}>
          {inSlide ? (
            <div style={{ position: "absolute", inset: 0, opacity: flick, transform: `translateY(${((fall - 1) * 22).toFixed(2)}%) scale(${(1.02 - 0.02 * focus).toFixed(4)})` }}>
              <FillPhoto src={src} ar={info.ar} w={SWd} h={SHd}
                filter={`sepia(.16) saturate(.9) contrast(1.06) brightness(1.04) blur(${(9 * k * (1 - focus)).toFixed(2)}px)`} />
            </div>
          ) : null}
          {/* The lamp's hot spot, the lens falling off at the corners, the screen's fine weave. */}
          <div style={{ position: "absolute", inset: 0, background: "radial-gradient(ellipse at 50% 48%, rgba(255,248,232,.2) 0%, rgba(255,248,232,0) 55%)",
            mixBlendMode: "screen" }} />
          <div style={{ position: "absolute", inset: 0, boxShadow: `inset 0 0 ${140 * k}px rgba(0,0,0,.55)` }} />
          <div style={{ position: "absolute", inset: 0, opacity: 0.06, backgroundImage: `repeating-linear-gradient(0deg, #000 0px, #000 ${1 * k}px, transparent ${1 * k}px, transparent ${3 * k}px)` }} />
        </div>
      </AbsoluteFill>
      <Grain opacity={0.08} />
      <CaptionShade show={cap_} strength={0.5} />
      <PxCaption ov={overlay} at={24} q={q} accent={accent} bottom={72} />
    </AbsoluteFill>
  );
};

// ================================================================== px-flatbed-scan
// A faded print lies on the scanner's glass; the light bar runs down it (6 -> 26, sfx_at 16) leaving it
// restored behind; the scan then fills the frame (28 -> 42; a portrait whole, over its blurred copy); the
// caption rises from 42.
const FlatbedScan: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H } = useVideoConfig();
  const k = useK();
  const q = useOut(12);
  const life = useLife();
  const src = photoOf(overlay);
  const info = usePhotoInfo(src);
  if (!src) return null;
  const seed = hashStr(src) % 97;
  const pa = printAspect(info.ar);
  const B = 20 * k;
  let PW = 1240 * k, PH = PW / pa;
  if (PH > 790 * k) {
    PH = 790 * k;
    PW = PH * pa;
  }
  const bedX = 120 * k, bedY = 84 * k, bedW = W - 240 * k, bedH = H - 168 * k;
  const px = bedX + (bedW - PW - 2 * B) / 2, py = bedY + (bedH - PH - 2 * B) / 2;
  const scan = ramp(frame, 6, 20, IN_OUT);
  const grow = ramp(frame, 28, 14, IN_OUT);
  const final = ramp(frame, 38, 5, Easing.linear);
  // The scan fills the frame: a landscape print covers the screen, a portrait one fills its height.
  const pr = { x: px + B, y: py + B, w: PW, h: PH };
  const S = info.ar >= 1.25 ? Math.max(W / pr.w, H / pr.h) : H / pr.h;
  const s = lerp(1, S, grow);
  const ox = lerp(pr.x, (W - pr.w * S) / 2, grow), oy = lerp(pr.y, (H - pr.h * S) / 2, grow);
  const barY = py + (PH + 2 * B) * scan;
  const barOn = scan > 0.001 && scan < 0.999 ? 1 : 0;
  const aged = "sepia(.62) saturate(.7) contrast(.78) brightness(1.08) blur(.6px)";
  const clean = "contrast(1.06) saturate(1.04)";
  const specks = Array.from({ length: 34 }, (_, i) => (
    <div key={i} style={{ position: "absolute", left: `${(hash01(seed + i * 3) * 100).toFixed(2)}%`, top: `${(hash01(seed + i * 5) * 100).toFixed(2)}%`,
      width: (1 + 3 * hash01(seed + i * 7)) * k, height: (1 + (i % 4 === 0 ? 14 : 2) * hash01(seed + i * 9)) * k, background: i % 3 ? "rgba(255,255,255,.7)" : "rgba(40,30,20,.55)",
      transform: `rotate(${(hash01(seed + i) * 180).toFixed(1)}deg)` }} />
  ));
  const cap_ = hasCaption(overlay);
  const ticks: React.ReactNode[] = [];
  for (let x = 0, i = 0; x <= bedW; x += 20 * k, i++) {
    ticks.push(<div key={`x${i}`} style={{ position: "absolute", left: bedX + x, top: bedY - (i % 5 ? 10 : 18) * k, width: 1.5 * k, height: (i % 5 ? 10 : 18) * k, background: "rgba(255,255,255,.35)" }} />);
  }
  return (
    <AbsoluteFill style={{ background: "#141518", overflow: "hidden" }}>
      <AbsoluteFill style={{ opacity: 1 - grow }}>
        {/* The scanner: its body, the ruler along the glass, the dark glass with a reflection. */}
        <AbsoluteFill style={{ background: "linear-gradient(170deg, #2a2c30 0%, #1a1b1e 100%)" }} />
        {ticks}
        <div style={{ position: "absolute", left: bedX, top: bedY, width: bedW, height: bedH, background: "linear-gradient(160deg, #101114 0%, #07080a 100%)",
          boxShadow: `inset 0 0 0 ${2 * k}px rgba(255,255,255,.06), inset 0 ${20 * k}px ${50 * k}px rgba(0,0,0,.6)` }}>
          <div style={{ position: "absolute", inset: 0, background: "linear-gradient(115deg, rgba(255,255,255,.05) 0%, rgba(255,255,255,0) 30%)" }} />
        </div>
      </AbsoluteFill>
      {/* The print: its border, its faded picture, the restored one where the light has passed. */}
      <div style={{ position: "absolute", left: px, top: py, width: PW + 2 * B, height: PH + 2 * B, background: "#efe6cf", opacity: 1 - grow,
        boxShadow: `0 ${4 * k}px ${14 * k}px rgba(0,0,0,.5)` }} />
      <div style={{ position: "absolute", left: ox, top: oy, width: pr.w, height: pr.h, transform: `scale(${s.toFixed(5)})`, transformOrigin: "0 0",
        overflow: "hidden", opacity: 1 - final }}>
        <FillPhoto src={src} ar={info.ar} w={pr.w} h={pr.h} filter={aged} />
        <div style={{ position: "absolute", inset: 0, opacity: 1 - grow }}>{specks}</div>
        <div style={{ position: "absolute", inset: 0, clipPath: `inset(0 0 ${((1 - scan) * 100).toFixed(3)}% 0)` }}>
          <FillPhoto src={src} ar={info.ar} w={pr.w} h={pr.h} filter={clean} />
        </div>
      </div>
      {final > 0.001 ? (
        <AbsoluteFill style={{ opacity: final, transform: `scale(${(1 + 0.04 * life).toFixed(4)})` }}>
          <FullPhoto src={src} ar={info.ar} filter={clean} />
        </AbsoluteFill>
      ) : null}
      {barOn ? (
        <>
          <div style={{ position: "absolute", left: bedX, top: barY - 140 * k, width: bedW, height: 140 * k,
            background: "linear-gradient(180deg, rgba(190,255,240,0) 0%, rgba(190,255,240,.12) 100%)" }} />
          <div style={{ position: "absolute", left: bedX, top: barY - 3 * k, width: bedW, height: 6 * k, background: "#f2fffb",
            boxShadow: `0 0 ${18 * k}px ${4 * k}px rgba(170,255,235,.65), 0 0 ${70 * k}px ${10 * k}px rgba(140,255,230,.25)` }} />
        </>
      ) : null}
      <CaptionShade show={cap_ && grow > 0.6} strength={0.6} />
      <PxCaption ov={overlay} at={42} q={q} accent={accent} />
    </AbsoluteFill>
  );
};

// ================================================================== px-shutter-burst
// Three frames of a burst, each closer on the point: wide (0 -> 7), the shutter blinks on 8-9 (a click),
// closer (10 -> 17), blinks on 18-19 (sfx_at 18), closest from 20, still easing in; the caption rises from 22.
const ShutterBurst: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const q = useOut(12);
  const life = useLife();
  const src = photoOf(overlay);
  const info = usePhotoInfo(src);
  if (!src) return null;
  const pinned = hasAnchor(overlay);
  const A = anchorOf(overlay, 0.5, 0.46, 0.15, 0.85);
  const most = zoomRoom(info.w, 1.85);
  const shot = frame < 8 ? 0 : frame < 18 ? 1 : 2;
  const blink = (frame >= 8 && frame < 10) || (frame >= 18 && frame < 20);
  if (blink) return <AbsoluteFill style={{ background: "#000" }} />;
  const zooms = [1, 1 + (most - 1) * 0.45, most];
  const since = frame - [0, 10, 20][shot];
  const snap = 1 + 0.025 * (1 - ramp(since, 0, 5, EXPO_OUT));
  const z = zooms[shot] * snap * (shot === 2 ? 1 + 0.05 * life : 1);
  const flash = interpolate(since, [0, 4], [shot ? 0.28 : 0, 0], clamp);
  const origin = `${(A.x * 100).toFixed(2)}% ${(A.y * 100).toFixed(2)}%`;
  const cap_ = hasCaption(overlay);
  return (
    <AbsoluteFill style={{ background: "#000", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${z.toFixed(4)})`, transformOrigin: origin }}>
        <FullPhoto src={src} ar={info.ar} pinned={pinned} filter="contrast(1.05)" />
      </AbsoluteFill>
      <AbsoluteFill style={{ background: "#fff", opacity: flash }} />
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 50%, rgba(0,0,0,0) 56%, rgba(0,0,0,.36) 100%)" }} />
      <CaptionShade show={cap_} strength={0.6} />
      <PxCaption ov={overlay} at={22} q={q} accent={accent} />
    </AbsoluteFill>
  );
};

// ================================================================== prints and paper
/** A print's deckled edge (the scalloped cut of mid-century prints) as a clip polygon over w x h. */
const deckle = (w: number, h: number, k: number, amp = 3): string => {
  const step = 6 * k;
  const a = (i: number) => amp * k * (0.5 + 0.5 * Math.sin((i * Math.PI) / 2));
  const pts: string[] = [];
  let i = 0;
  for (let x = 0; x <= w; x += step) pts.push(`${x.toFixed(1)}px ${a(i++).toFixed(1)}px`);
  for (let y = 0; y <= h; y += step) pts.push(`${(w - a(i++)).toFixed(1)}px ${y.toFixed(1)}px`);
  for (let x = w; x >= 0; x -= step) pts.push(`${x.toFixed(1)}px ${(h - a(i++)).toFixed(1)}px`);
  for (let y = h; y >= 0; y -= step) pts.push(`${a(i++).toFixed(1)}px ${y.toFixed(1)}px`);
  return `polygon(${pts.join(", ")})`;
};

/** Typewritten words: Courier Prime, each letter's ink a little heavier or lighter. */
const Typed: React.FC<{ text: string; size: number; color?: string; seed: number; weight?: number; track?: number }> =
  ({ text, size, color = "#24211c", seed, weight = 700, track = 0.04 }) => (
    <span style={{ fontFamily: TYPEWRITER, fontWeight: weight, fontSize: size, letterSpacing: `${track}em`, color, whiteSpace: "pre" }}>
      {Array.from(text).map((c, i) => (
        <span key={i} style={{ opacity: 0.74 + 0.26 * hash01(seed + i * 1.37) }}>{c}</span>
      ))}
    </span>
  );

/**
 * Lines of a printed page seen from reading distance: words as fine ink marks with x-height and the odd
 * ascender, set justified, paragraphs indented, a short last line (no fake words to read).
 */
const PageText: React.FC<{ w: number; rows: number; k: number; seed: number; gap?: number }> = ({ w, rows, k, seed, gap = 19 }) => {
  const xh = 4.2 * k;
  return (
    <div style={{ width: w }}>
      {Array.from({ length: rows }, (_, r) => {
        const para = r % 8 === 0;
        const last = r % 8 === 7;
        const end = last ? w * (0.25 + 0.45 * hash01(seed + r)) : w;
        const words: React.ReactNode[] = [];
        let x = para ? 30 * k : 0;
        for (let j = 0; x < end - 10 * k && j < 30; j++) {
          const ww = Math.min(end - x, (9 + 34 * hash01(seed * 7 + r * 31 + j)) * k);
          const tall = hash01(seed * 3 + r * 17 + j) > 0.55;
          words.push(<div key={j} style={{ position: "absolute", left: x, top: tall ? -2.2 * k : 0, width: ww, height: tall ? xh + 2.2 * k : xh,
            borderRadius: 1 * k, background: "rgba(52,40,26,.42)" }} />);
          x += ww + 6 * k;
        }
        const row = <div style={{ position: "relative", height: xh, marginBottom: gap * k - xh }}>{words}</div>;
        return last ? <React.Fragment key={r}>{row}<div style={{ height: 8 * k }} /></React.Fragment> : <React.Fragment key={r}>{row}</React.Fragment>;
      })}
    </div>
  );
};

// ================================================================== px-album-page
/** A black paper photo corner over one corner of a print (q: 0 top-left, 1 top-right, 2 bottom-right, 3 bottom-left). */
const PhotoCorner: React.FC<{ x: number; y: number; q: number; s: number; k: number }> = ({ x, y, q, s, k }) => {
  const rot = q * 90;
  return (
    <svg width={s} height={s} viewBox="0 0 100 100" style={{ position: "absolute", left: x - s * 0.18, top: y - s * 0.18, overflow: "visible",
      transform: `rotate(${rot}deg)`, transformOrigin: `${s * 0.18}px ${s * 0.18}px`, filter: `drop-shadow(${1.5 * k}px ${2.5 * k}px ${2.5 * k}px rgba(0,0,0,.35))` }}>
      <defs>
        <linearGradient id={`pc${q}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#2b2826" />
          <stop offset="100%" stopColor="#121110" />
        </linearGradient>
      </defs>
      <path d="M0 0 H100 L0 100 Z" fill={`url(#pc${q})`} />
      <path d="M100 0 L0 100" stroke="rgba(255,255,255,.18)" strokeWidth={2.2} />
      <path d="M0 0 H100 L0 100 Z" fill="none" stroke="rgba(0,0,0,.5)" strokeWidth={1} />
    </svg>
  );
};

// A glassine interleaf covers the album page; it lifts off upward (2 -> 17, clearing the print at ~14:
// sfx_at 14, the paper); the print in its black corners and its typed label; the camera leans in.
const AlbumPage: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H } = useVideoConfig();
  const k = useK();
  const life = useLife();
  const id = `pxAlb${uidOf(React.useId())}`;
  const src = photoOf(overlay);
  const info = usePhotoInfo(src);
  if (!src) return null;
  const seed = hashStr(src) % 97;
  const pa = printAspect(info.ar);
  const B = 24 * k;
  let PW = 1060 * k, PH = PW / pa;
  if (PH > 690 * k) {
    PH = 690 * k;
    PW = PH * pa;
  }
  const cx = W / 2, cy = 452 * k;
  const lift = ramp(frame, 2, 15, Easing.bezier(0.55, 0, 0.3, 1));
  const name = caps(overlay.text, 40);
  const when = yearIn(`${str(overlay.label)} ${str(overlay.subtitle)}`) || caps(overlay.label, 20);
  const label = [name, when].filter(Boolean).join(", ");
  const lpx = 30 * k;
  const lw = Math.min(W - 400 * k, label.length * lpx * 0.6 + 80 * k);
  const cs = 92 * k;
  const pw = PW + 2 * B, ph = PH + 2 * B;
  return (
    <AbsoluteFill style={{ background: "#e6ddc9", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${(1.02 + 0.05 * life).toFixed(4)})`, transformOrigin: "50% 46%" }}>
        <AbsoluteFill style={{ background: "radial-gradient(ellipse at 48% 40%, #f0e9d8 0%, #e4dac4 68%, #d2c6ac 100%)" }} />
        <PaperGrain w={W} h={H} seed={seed} opacity={0.24} freq={0.6} />
        <div style={{ position: "absolute", inset: 58 * k, border: `${1.5 * k}px solid rgba(116,96,64,.28)` }} />
        <div style={{ position: "absolute", left: cx - pw / 2, top: cy - ph / 2, width: pw, height: ph, transform: "rotate(-1.1deg)" }}>
          <div style={{ position: "absolute", inset: 0, filter: `drop-shadow(0 ${3 * k}px ${5 * k}px rgba(0,0,0,.3))` }}>
            <div style={{ position: "absolute", inset: 0, background: "#fbf9f2", clipPath: deckle(pw, ph, k) }}>
              <div style={{ position: "absolute", left: B, top: B, width: PW, height: PH, overflow: "hidden", background: "#222" }}>
                <Cover src={src} pos="50% 42%" style={{ filter: "contrast(1.05) saturate(.9) sepia(.12)" }} />
                <div style={{ position: "absolute", inset: 0, background: "linear-gradient(128deg, rgba(255,255,255,.12) 0%, rgba(255,255,255,0) 40%)" }} />
              </div>
            </div>
          </div>
          <PhotoCorner x={0} y={0} q={0} s={cs} k={k} />
          <PhotoCorner x={pw} y={0} q={1} s={cs} k={k} />
          <PhotoCorner x={pw} y={ph} q={2} s={cs} k={k} />
          <PhotoCorner x={0} y={ph} q={3} s={cs} k={k} />
        </div>
        {label ? (
          <div style={{ position: "absolute", left: cx - lw / 2, top: cy + ph / 2 + 50 * k, width: lw, padding: `${12 * k}px 0`, textAlign: "center",
            background: "linear-gradient(180deg, #faf6ea 0%, #f1ead8 100%)", transform: "rotate(0.6deg)",
            boxShadow: `0 ${2 * k}px ${5 * k}px rgba(0,0,0,.22)`, overflow: "hidden", whiteSpace: "nowrap" }}>
            <Typed text={label} size={lpx} seed={seed} />
          </div>
        ) : null}
      </AbsoluteFill>
      {/* The glassine interleaf: milky, a little creased, its lower edge casting a soft line as it lifts. */}
      {lift < 0.999 ? (
        <div style={{ position: "absolute", left: -60 * k, top: -60 * k, width: W + 120 * k, height: H + 120 * k,
          transform: `translateY(${(-lift * (H + 220 * k)).toFixed(2)}px) rotate(${(-2.4 * lift).toFixed(3)}deg)`, transformOrigin: "50% 100%",
          background: "rgba(247,246,240,.58)", backdropFilter: `blur(${5 * k}px)`, WebkitBackdropFilter: `blur(${5 * k}px)`,
          boxShadow: `0 ${16 * k}px ${36 * k}px rgba(60,48,30,${(0.22 * Math.min(1, lift * 4)).toFixed(3)})` } as CSS}>
          <svg width={W + 120 * k} height={H + 120 * k} style={{ position: "absolute", left: 0, top: 0, opacity: 0.35, mixBlendMode: "soft-light" }}>
            <filter id={`${id}c`} x="0" y="0" width="100%" height="100%">
              <feTurbulence type="fractalNoise" baseFrequency={`${(0.004 / k).toFixed(5)} ${(0.012 / k).toFixed(5)}`} numOctaves={3} seed={seed} />
              <feColorMatrix type="saturate" values="0" />
            </filter>
            <rect width={W + 120 * k} height={H + 120 * k} filter={`url(#${id}c)`} />
          </svg>
          <div style={{ position: "absolute", inset: 0, background: "linear-gradient(115deg, rgba(255,255,255,0) 30%, rgba(255,255,255,.35) 46%, rgba(255,255,255,0) 60%)" }} />
        </div>
      ) : null}
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${240 * k}px rgba(60,40,20,.35)` }} />
    </AbsoluteFill>
  );
};

// ================================================================== px-archive-stamp
const STAMP_RED = "#b0262c";

// An aged print slides onto the desk (0 -> 11); the shadow of the stamp closes in (9 -> 14) and the ARCHIVE
// stamp comes down on it at 14 (sfx_at 14, the stamp), the print giving a little under it; the camera leans in.
const ArchiveStamp: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H } = useVideoConfig();
  const k = useK();
  const life = useLife();
  const id = `pxStp${uidOf(React.useId())}`;
  const src = photoOf(overlay);
  const info = usePhotoInfo(src);
  if (!src) return null;
  const seed = hashStr(src) % 97;
  const LAND = 14;
  const pa = printAspect(info.ar);
  const B = 26 * k, BB = 86 * k;
  let PW = 1180 * k, PH = PW / pa;
  if (PH > 690 * k) {
    PH = 690 * k;
    PW = PH * pa;
  }
  const pw = PW + 2 * B, ph = PH + B + BB;
  const slide = ramp(frame, 0, 11, EXPO_OUT);
  const dt = frame - LAND;
  const give = dt >= 0 ? Math.sin(dt * 2.4) * Math.exp(-dt / 2.6) * 4 * k : 0;
  const near = ramp(frame, LAND - 5, 5, EXPO_IN);
  const pressed = dt >= 0;
  const pop = ramp(frame, LAND, 4, EXPO_OUT);
  const label = str(overlay.label);
  const word = label && !/\d/.test(label) && label.length <= 12 ? label.toUpperCase() : "ARCHIVE";
  const year = yearIn(`${label} ${str(overlay.subtitle)}`);
  const sw = 440 * k, sh = (year ? 170 : 130) * k;
  const caption = [asWritten(overlay.text, 44), year].filter(Boolean).join(" — ");
  // The stamp lands on the print over the picture's lower right corner, turned against the print, wholly on
  // the paper (an impression never runs off onto the desk).
  const stx = W / 2 + pw / 2 - sw - 56 * k, sty = H / 2 - 20 * k + ph / 2 - BB - sh * 0.62;
  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 46% 38%, #3b3128 0%, #221b15 55%, #0c0907 100%)", overflow: "hidden" }}>
      <AbsoluteFill style={{ backgroundImage: `repeating-linear-gradient(88deg, rgba(255,235,210,.02) 0px, rgba(255,235,210,.02) ${2 * k}px, rgba(0,0,0,0) ${2 * k}px, rgba(0,0,0,0) ${12 * k}px)` }} />
      <AbsoluteFill style={{ transform: `scale(${(1.01 + 0.05 * life).toFixed(4)})`, transformOrigin: "62% 62%" }}>
        <div style={{ position: "absolute", left: W / 2 - pw / 2, top: H / 2 - 20 * k - ph / 2, width: pw, height: ph,
          transform: `translateY(${((1 - slide) * 520 * k + give).toFixed(2)}px) rotate(${(1.3 + 4 * (1 - slide)).toFixed(3)}deg)`,
          background: "linear-gradient(170deg, #f3ecd9 0%, #e7dcc0 100%)", boxShadow: `0 ${18 * k}px ${44 * k}px rgba(0,0,0,.55)` }}>
          <PaperGrain w={pw} h={ph} seed={seed} opacity={0.2} />
          <div style={{ position: "absolute", left: B, top: B, width: PW, height: PH, overflow: "hidden", background: "#2a2622" }}>
            <Cover src={src} pos="50% 45%" style={{ filter: "grayscale(1) sepia(.38) contrast(1.1) brightness(.95)" }} />
            <div style={{ position: "absolute", inset: 0, boxShadow: `inset 0 0 ${70 * k}px rgba(70,46,20,.45)` }} />
            {Array.from({ length: 7 }, (_, i) => (
              <div key={i} style={{ position: "absolute", left: `${(hash01(seed + i * 3) * 100).toFixed(1)}%`, top: 0, bottom: 0,
                width: 1.2 * k, background: "rgba(255,250,235,.16)", transform: `rotate(${((hash01(seed + i) - 0.5) * 4).toFixed(2)}deg)` }} />
            ))}
          </div>
          {caption ? (
            <div style={{ position: "absolute", left: B + 6 * k, bottom: BB * 0.28, whiteSpace: "nowrap", overflow: "hidden", maxWidth: pw - 2 * B }}>
              <Typed text={caption} size={28 * k} seed={seed} weight={400} />
            </div>
          ) : null}
        </div>
        {/* The stamp block's shadow closing in, then the impression. */}
        {near > 0.01 && !pressed ? (
          <div style={{ position: "absolute", left: stx, top: sty, width: sw, height: sh, borderRadius: 14 * k, background: "rgba(0,0,0,.35)",
            filter: `blur(${(24 * (1 - near) + 6) * k}px)`, opacity: near, transform: `rotate(-8deg) scale(${(1.35 - 0.3 * near).toFixed(3)})` }} />
        ) : null}
        {pressed ? (
          <svg width={sw} height={sh} style={{ position: "absolute", left: stx, top: sty + give, overflow: "visible", mixBlendMode: "multiply",
            transform: `rotate(-8deg) scale(${(1.1 - 0.1 * pop).toFixed(4)})`, opacity: 0.93 }}>
            <defs>
              <filter id={`${id}i`} x="-5%" y="-5%" width="110%" height="110%">
                <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves={2} seed={seed} result="n" />
                <feColorMatrix in="n" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  9 0 0 0 -2.7" result="speck" />
                <feComposite in="SourceGraphic" in2="speck" operator="in" result="ink" />
                <feTurbulence type="fractalNoise" baseFrequency="0.03" numOctaves={2} seed={seed + 5} result="m" />
                <feColorMatrix in="m" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  1.6 0 0 0 0.05" result="press" />
                <feComposite in="ink" in2="press" operator="in" />
              </filter>
            </defs>
            <g filter={`url(#${id}i)`}>
              <rect x={5 * k} y={5 * k} width={sw - 10 * k} height={sh - 10 * k} rx={12 * k} fill="none" stroke={STAMP_RED} strokeWidth={7 * k} />
              <rect x={19 * k} y={19 * k} width={sw - 38 * k} height={sh - 38 * k} rx={6 * k} fill="none" stroke={STAMP_RED} strokeWidth={2.6 * k} />
              <text x={sw / 2} y={(year ? 92 : 90) * k} textAnchor="middle" fontFamily={ANTON} fontSize={(word.length > 8 ? 58 : 70) * k}
                letterSpacing={6 * k} fill={STAMP_RED}>{word}</text>
              {year ? <text x={sw / 2} y={136 * k} textAnchor="middle" fontFamily={LABEL} fontWeight={700} fontSize={30 * k} letterSpacing={10 * k}
                fill={STAMP_RED}>{year}</text> : null}
            </g>
          </svg>
        ) : null}
      </AbsoluteFill>
      <Grain opacity={0.06} />
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 40% 30%, rgba(255,226,180,.06) 0%, rgba(0,0,0,0) 45%, rgba(0,0,0,.45) 100%)" }} />
    </AbsoluteFill>
  );
};

// ================================================================== px-book-plate
// An old book lies open; the right-hand page turns over (2 -> 18, landing at ~16: sfx_at 14, the page) onto
// a photographic plate and its caption; the camera leans in toward the plate.
const BookPlate: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H } = useVideoConfig();
  const k = useK();
  const life = useLife();
  const src = photoOf(overlay);
  const info = usePhotoInfo(src);
  if (!src) return null;
  const seed = hashStr(src) % 97;
  const BW = 1780 * k, BH = 1010 * k, half = BW / 2;
  const bx = (W - BW) / 2, by = (H - BH) / 2 + 8 * k;
  const turn = ramp(frame, 2, 16, Easing.bezier(0.45, 0.05, 0.25, 1));
  const th = -180 * turn;
  const pa = printAspect(info.ar);
  let IW = half - 250 * k, IH = IW / pa;
  if (IH > 600 * k) {
    IH = 600 * k;
    IW = IH * pa;
  }
  const name = caps(overlay.text, 46);
  const second = cut(str(overlay.subtitle) || str(overlay.label), 60);
  const paper = "linear-gradient(90deg, #ece2c9 0%, #f2e9d3 40%, #efe5cc 100%)";
  const foxing = (s: number) => Array.from({ length: 9 }, (_, i) => {
    const r = (6 + 22 * hash01(s + i * 7)) * k;
    return <div key={i} style={{ position: "absolute", left: `${(hash01(s + i * 3) * 92).toFixed(1)}%`, top: `${(hash01(s + i * 5) * 92).toFixed(1)}%`,
      width: 2 * r, height: 2 * r, borderRadius: "50%", background: "radial-gradient(circle, rgba(150,100,40,.16) 0%, rgba(150,100,40,0) 70%)" }} />;
  });
  const pageBg = (side: number, s: number): CSS => ({ position: "absolute", inset: 0, background: paper,
    boxShadow: `inset ${side ? 70 : -70}px 0 ${90 * k}px rgba(90,60,25,.18)`, overflow: "hidden" } as CSS);
  const textPage = (s: number) => (
    <div style={{ position: "absolute", left: 120 * k, top: 124 * k }}>
      <PageText w={half - 240 * k} rows={38} k={k} seed={s} />
    </div>
  );
  const dark = 0.4 * Math.sin((turn * Math.PI));
  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 42%, #2f2720 0%, #1a1511 60%, #0a0806 100%)", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${(1.0 + 0.07 * life * turn).toFixed(4)})`, transformOrigin: "72% 44%" }}>
        <div style={{ position: "absolute", left: bx, top: by, width: BW, height: BH, transform: "rotate(0.5deg)", perspective: 2800 * k }}>
          {/* The binding and the page block's edges under the open pages. */}
          <div style={{ position: "absolute", left: -18 * k, top: -12 * k, right: -18 * k, bottom: -22 * k, borderRadius: 8 * k,
            background: "linear-gradient(180deg, #5a2c1c 0%, #3b1c12 100%)", boxShadow: `0 ${30 * k}px ${70 * k}px rgba(0,0,0,.65)` }} />
          <div style={{ position: "absolute", left: -8 * k, top: 4 * k, right: -8 * k, bottom: -10 * k,
            backgroundImage: `repeating-linear-gradient(180deg, #e8dcc0 0px, #e8dcc0 ${2 * k}px, #cdbf9f ${2 * k}px, #cdbf9f ${3 * k}px)` }} />
          {/* The left page: text. */}
          <div style={{ position: "absolute", left: 0, top: 0, width: half, height: BH }}>
            <div style={pageBg(0, seed)}>{textPage(seed)}{foxing(seed)}<PaperGrain w={half} h={BH} seed={seed} opacity={0.14} /></div>
          </div>
          {/* The right page: the plate and its caption. */}
          <div style={{ position: "absolute", left: half, top: 0, width: half, height: BH }}>
            <div style={pageBg(1, seed + 1)}>
              {foxing(seed + 40)}
              <PaperGrain w={half} h={BH} seed={seed + 1} opacity={0.14} />
              <div style={{ position: "absolute", left: (half - IW) / 2 - 14 * k, top: 120 * k + (600 * k - IH) / 2 - 14 * k, padding: 13 * k,
                border: `${1.5 * k}px solid rgba(52,40,26,.75)` }}>
                <div style={{ position: "relative", width: IW, height: IH, overflow: "hidden", background: "#2b241c" }}>
                  <Cover src={src} pos="50% 45%" style={{ filter: "grayscale(1) sepia(.42) contrast(1.08) brightness(.97)" }} />
                </div>
              </div>
              <div style={{ position: "absolute", left: 60 * k, right: 60 * k, top: 120 * k + 600 * k + 46 * k, textAlign: "center" }}>
                {name ? <div style={{ fontFamily: SERIF, fontSize: 30 * k, letterSpacing: "0.2em", color: "#2e2619" }}>{name}</div> : null}
                {second ? <div style={{ fontFamily: SERIF_ITALIC, fontSize: 26 * k, color: "#4a3d2a", marginTop: 10 * k }}>{second}</div> : null}
              </div>
            </div>
          </div>
          {/* The page turning over from right to left, hinged on the spine. */}
          {turn < 0.999 ? (
            <div style={{ position: "absolute", left: half, top: 0, width: half, height: BH, transformStyle: "preserve-3d", transformOrigin: "0% 50%",
              transform: `rotateY(${th.toFixed(3)}deg)` }}>
              <div style={{ position: "absolute", inset: 0, backfaceVisibility: "hidden" }}>
                <div style={pageBg(1, seed + 2)}>{textPage(seed + 7)}{foxing(seed + 70)}</div>
                <div style={{ position: "absolute", inset: 0, background: `rgba(0,0,0,${dark.toFixed(3)})` }} />
              </div>
              <div style={{ position: "absolute", inset: 0, backfaceVisibility: "hidden", transform: "rotateY(180deg)" }}>
                <div style={pageBg(0, seed + 3)}>{textPage(seed + 11)}{foxing(seed + 90)}</div>
                <div style={{ position: "absolute", inset: 0, background: `rgba(0,0,0,${(dark * 0.8).toFixed(3)})` }} />
              </div>
            </div>
          ) : null}
          {/* The gutter. */}
          <div style={{ position: "absolute", top: 0, bottom: 0, left: half - 90 * k, width: 180 * k,
            background: "linear-gradient(90deg, rgba(60,40,15,0) 0%, rgba(60,40,15,.12) 35%, rgba(40,25,8,.42) 50%, rgba(60,40,15,.12) 65%, rgba(60,40,15,0) 100%)" }} />
        </div>
      </AbsoluteFill>
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${260 * k}px rgba(0,0,0,.5)` }} />
    </AbsoluteFill>
  );
};

// ================================================================== px-archive-envelope
// A kraft archive envelope with its typed label lies on the desk; the print slides half out of it (4 -> 20,
// sfx_at 14, the paper), then the envelope drops to the foot of the frame (16 -> 34) as the print settles
// above it, whole, its label still in view under it.
const ArchiveEnvelope: Look = ({ overlay }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H } = useVideoConfig();
  const k = useK();
  const life = useLife();
  const src = photoOf(overlay);
  const info = usePhotoInfo(src);
  if (!src) return null;
  const seed = hashStr(src) % 97;
  const EW = 1060 * k, EH = 700 * k;
  const out = ramp(frame, 4, 16, EXPO_OUT);
  const settle = ramp(frame, 16, 18, IN_OUT);
  const pa = printAspect(info.ar);
  const B = 20 * k;
  let PW = 880 * k, PH = PW / pa;
  if (PH > 600 * k) {
    PH = 600 * k;
    PW = PH * pa;
  }
  const pw = PW + 2 * B, ph = PH + 2 * B;
  // The envelope: low on the desk, then dropping until only its labelled top shows.
  const ey = lerp(410 * k, H - 236 * k, settle);
  const ex = W / 2 - EW / 2;
  // The print: half out of the mouth, then up to its place above the envelope, a little larger.
  const halfOut = 410 * k + 40 * k - 0.55 * ph * out;
  const py = lerp(halfOut, 96 * k, settle);
  const ps = lerp(1, 1.04, settle);
  const name = caps(overlay.text, 34);
  const second = caps(overlay.subtitle || overlay.label, 40);
  const year = yearIn(`${str(overlay.label)} ${str(overlay.subtitle)}`);
  const kraft = "linear-gradient(170deg, #c49461 0%, #b58553 55%, #a57647 100%)";
  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 40%, #39302a 0%, #201a16 58%, #0b0907 100%)", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${(1.0 + 0.04 * life).toFixed(4)})` }}>
        {/* The envelope's back panel and its open flap, behind the print. */}
        <div style={{ position: "absolute", left: ex, top: ey, width: EW, height: EH, transform: "rotate(-1.4deg)", transformOrigin: "50% 0%" }}>
          <div style={{ position: "absolute", left: 30 * k, right: 30 * k, top: -150 * k, height: 170 * k, background: "linear-gradient(0deg, #9d6f42 0%, #b8885a 100%)",
            clipPath: "polygon(0% 100%, 12% 0%, 88% 0%, 100% 100%)", boxShadow: `0 ${10 * k}px ${30 * k}px rgba(0,0,0,.4)` }} />
          <div style={{ position: "absolute", inset: 0, background: "#8e643b", boxShadow: `0 ${26 * k}px ${60 * k}px rgba(0,0,0,.6)` }} />
        </div>
        {/* The print. */}
        <div style={{ position: "absolute", left: W / 2 - pw / 2, top: py, width: pw, height: ph, background: "#f8f6ef",
          transform: `rotate(${lerp(-1.4, -0.6, settle).toFixed(3)}deg) scale(${ps.toFixed(4)})`, boxShadow: `0 ${10 * k}px ${26 * k}px rgba(0,0,0,.45)` }}>
          <div style={{ position: "absolute", left: B, top: B, width: PW, height: PH, overflow: "hidden", background: "#222" }}>
            <Cover src={src} pos="50% 45%" style={{ filter: "contrast(1.05) saturate(.95)" }} />
            <div style={{ position: "absolute", inset: 0, background: "linear-gradient(125deg, rgba(255,255,255,.12) 0%, rgba(255,255,255,0) 40%)" }} />
          </div>
        </div>
        {/* The envelope's front: kraft, the typed label, the red handling stamp. */}
        <div style={{ position: "absolute", left: ex, top: ey, width: EW, height: EH, transform: "rotate(-1.4deg)", transformOrigin: "50% 0%",
          background: kraft, overflow: "hidden", boxShadow: `inset 0 ${3 * k}px 0 rgba(255,235,200,.25)` }}>
          <PaperGrain w={EW} h={EH} seed={seed} opacity={0.3} freq={0.7} rgb={[0.42, 0.28, 0.14]} />
          <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 26 * k, background: "linear-gradient(180deg, rgba(0,0,0,.28) 0%, rgba(0,0,0,0) 100%)" }} />
          <div style={{ position: "absolute", left: 70 * k, top: 66 * k, width: 540 * k, padding: `${20 * k}px ${28 * k}px`, background: "#f6f1e3",
            borderRadius: 6 * k, boxShadow: `0 ${1.5 * k}px ${3 * k}px rgba(0,0,0,.25), inset 0 0 0 ${2 * k}px rgba(176,38,44,.35)`, transform: "rotate(-0.8deg)" }}>
            {name ? <div style={{ whiteSpace: "nowrap", overflow: "hidden" }}><Typed text={name} size={34 * k} seed={seed} /></div> : null}
            {second ? <div style={{ whiteSpace: "nowrap", overflow: "hidden", marginTop: 8 * k }}><Typed text={second} size={26 * k} seed={seed + 5} weight={400} /></div> : null}
            {!second && year ? <div style={{ marginTop: 8 * k }}><Typed text={year} size={26 * k} seed={seed + 5} weight={400} /></div> : null}
          </div>
          <div style={{ position: "absolute", right: 56 * k, top: 96 * k, transform: "rotate(-4deg)", fontFamily: LABEL, fontWeight: 700, fontSize: 26 * k,
            letterSpacing: "0.2em", color: "rgba(160,30,36,.78)", border: `${3 * k}px solid rgba(160,30,36,.7)`, padding: `${6 * k}px ${14 * k}px`,
            mixBlendMode: "multiply", whiteSpace: "nowrap", textAlign: "center", lineHeight: 1.15 }}>PHOTOGRAPH<br />DO NOT BEND</div>
        </div>
      </AbsoluteFill>
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${260 * k}px rgba(0,0,0,.5)` }} />
    </AbsoluteFill>
  );
};

// ================================================================== px-drying-line
/** A wooden clothes-peg, its jaw down, about (x, y) at the top of what it holds. */
const Peg: React.FC<{ x: number; y: number; k: number; rot?: number }> = ({ x, y, k, rot = 0 }) => (
  <svg width={46 * k} height={150 * k} viewBox="0 0 46 150" style={{ position: "absolute", left: x - 23 * k, top: y - 96 * k, overflow: "visible",
    transform: `rotate(${rot}deg)`, transformOrigin: "50% 64%", filter: `drop-shadow(${2 * k}px ${4 * k}px ${3 * k}px rgba(0,0,0,.5))` }}>
    <defs>
      <linearGradient id="pegw" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0%" stopColor="#a87e4c" />
        <stop offset="45%" stopColor="#d9b582" />
        <stop offset="100%" stopColor="#9c7244" />
      </linearGradient>
    </defs>
    <rect x={4} y={0} width={18} height={150} rx={5} fill="url(#pegw)" />
    <rect x={24} y={0} width={18} height={150} rx={5} fill="url(#pegw)" />
    <rect x={22} y={0} width={2} height={150} fill="rgba(60,40,20,.5)" />
    <path d="M6 30 H40 M6 34 H40" stroke="rgba(90,60,30,.25)" strokeWidth={1} />
    <rect x={1} y={56} width={44} height={14} rx={4} fill="#5d6166" />
    <rect x={1} y={58} width={44} height={3} rx={1.5} fill="rgba(255,255,255,.35)" />
  </svg>
);

// The print slides along the drying line from the right and stops at 16 (sfx_at 16, the peg), swinging on
// its pegs to rest; prints either side hang out of focus; the caption rises from 22.
const DryingLine: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H } = useVideoConfig();
  const k = useK();
  const q = useOut(12);
  const life = useLife();
  const src = photoOf(overlay);
  const info = usePhotoInfo(src);
  if (!src) return null;
  const STOP = 16;
  const pa = printAspect(info.ar);
  const B = 18 * k;
  let PW = 900 * k, PH = PW / pa;
  if (PH > 660 * k) {
    PH = 660 * k;
    PW = PH * pa;
  }
  const pw = PW + 2 * B, ph = PH + 2 * B;
  const lineY = (x: number) => 150 * k + 22 * k * Math.sin((Math.PI * x) / W);
  const slide = ramp(frame, 0, STOP, Easing.bezier(0.25, 0.1, 0.2, 1));
  const dt = Math.max(0, frame - STOP);
  const swing = frame < STOP ? -7 * (1 - slide) : 6.5 * Math.exp(-dt / 11) * Math.sin(dt * 0.42);
  const x0 = W / 2 + (1 - slide) * 1300 * k;
  const top = lineY(x0) - 6 * k;
  const side = (dir: number) => {
    const cx = W / 2 + dir * (pw + 150 * k);
    const sway = Math.sin(frame / 16 + dir) * 1.2;
    return (
      <div key={dir} style={{ position: "absolute", left: cx - pw / 2, top: lineY(cx) - 6 * k, width: pw, height: ph * 0.94,
        transform: `rotate(${sway.toFixed(3)}deg)`, transformOrigin: "50% 0%", filter: `blur(${9 * k}px) brightness(.46)` }}>
        <div style={{ position: "absolute", inset: 0, background: "#e9e7e0", boxShadow: `0 ${16 * k}px ${30 * k}px rgba(0,0,0,.45)` }}>
          <div style={{ position: "absolute", inset: B, opacity: 0.08, transform: "scaleX(-1)" }}><Cover src={src} style={{ filter: "grayscale(1)" }} /></div>
        </div>
        <Peg x={70 * k} y={0} k={k} />
        <Peg x={pw - 70 * k} y={0} k={k} />
      </div>
    );
  };
  const wire = Array.from({ length: 33 }, (_, i) => {
    const x = (i / 32) * (W + 200 * k) - 100 * k;
    return `${i ? "L" : "M"} ${x.toFixed(1)} ${lineY(x).toFixed(1)}`;
  }).join(" ");
  const cap_ = hasCaption(overlay);
  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 30%, #2c2925 0%, #1a1816 55%, #0b0a09 100%)", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${(1.0 + 0.05 * life).toFixed(4)})`, transformOrigin: "50% 40%" }}>
        <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 18%, rgba(255,226,180,.1) 0%, rgba(0,0,0,0) 55%)" }} />
        {side(-1)}
        {side(1)}
        <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0 }}>
          <path d={wire} fill="none" stroke="rgba(0,0,0,.6)" strokeWidth={5 * k} transform={`translate(0 ${4 * k})`} />
          <path d={wire} fill="none" stroke="#9c978d" strokeWidth={2.4 * k} />
          <path d={wire} fill="none" stroke="rgba(255,255,255,.35)" strokeWidth={0.8 * k} transform={`translate(0 ${-0.6 * k})`} />
        </svg>
        <div style={{ position: "absolute", left: x0 - pw / 2, top, width: pw, height: ph, transform: `rotate(${swing.toFixed(3)}deg)`,
          transformOrigin: "50% 0%" }}>
          <div style={{ position: "absolute", inset: 0, background: "#f7f5ef", boxShadow: `${10 * k}px ${24 * k}px ${40 * k}px rgba(0,0,0,.55)` }}>
            <div style={{ position: "absolute", left: B, top: B, width: PW, height: PH, overflow: "hidden", background: "#222" }}>
              <Cover src={src} pos="50% 45%" style={{ filter: "contrast(1.05) saturate(.95)" }} />
              <div style={{ position: "absolute", inset: 0, background: "linear-gradient(120deg, rgba(255,255,255,.1) 0%, rgba(255,255,255,0) 40%)" }} />
            </div>
            {/* The paper bows a little from the pegs. */}
            <div style={{ position: "absolute", inset: 0, background: "linear-gradient(180deg, rgba(0,0,0,.12) 0%, rgba(0,0,0,0) 12%, rgba(0,0,0,0) 88%, rgba(0,0,0,.1) 100%)" }} />
          </div>
          <Peg x={74 * k} y={0} k={k} rot={-2} />
          <Peg x={pw - 74 * k} y={0} k={k} rot={2} />
        </div>
      </AbsoluteFill>
      <CaptionShade show={cap_} strength={0.62} />
      <PxCaption ov={overlay} at={22} q={q} accent={accent} />
    </AbsoluteFill>
  );
};

// ================================================================== px-dated-cascade
// Two or three prints land in turn along a time rail, the last at 25 (sfx_at 23, the paper); each date rises
// under its print as it lands; the title sits top left. At the exit the prints slide away to the left.
const DatedCascade: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width: W, durationInFrames: dur } = useVideoConfig();
  const k = useK();
  const q = useOut(12);
  const life = useLife();
  const pics = photosOf(overlay, 3);
  const i0 = usePhotoInfo(pics[0] || "");
  const i1 = usePhotoInfo(pics[1] || "");
  const i2 = usePhotoInfo(pics[2] || "");
  if (!pics.length) return null;
  const infos = [i0, i1, i2];
  const n = pics.length;
  const items = itemsOf(overlay);
  const dates = pics.map((_, i) => caps(items[i]?.label ?? "", 18));
  const base = n === 3 ? 560 : n === 2 ? 700 : 860;
  const xs = n === 3 ? [400, 960, 1520] : n === 2 ? [640, 1280] : [960];
  const ys = [452, 494, 466];
  const rots = [-3.4, 2.1, -1.5];
  const LAST = 25;
  const B = 16 * k;
  const railY = 836 * k;
  const draw = ramp(frame, 4, 26, IN_OUT);
  const leave = (i: number) => ramp(frame, dur - 14 + i * 2, 11, EXPO_IN);
  const title = fitAnton(caps(overlay.text, 50), 44, 32, 1300 * k, k, 1);
  const kick = caps(overlay.label, 40);
  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 42%, #23252a 0%, #131418 60%, #08090b 100%)", overflow: "hidden" }}>
      <Grain opacity={0.07} />
      <AbsoluteFill style={{ transform: `scale(${(1 + 0.035 * life).toFixed(4)})` }}>
        {/* The rail: a hairline drawing across, a tick under each print. */}
        <div style={{ position: "absolute", left: 160 * k, top: railY, width: (W - 320 * k) * draw, height: 2 * k, background: "rgba(255,255,255,.45)",
          opacity: 1 - q }} />
        {pics.map((src, i) => {
          const pa = printAspect(infos[i].ar);
          let PW = base * k, PH = PW / pa;
          if (PH > 470 * k) {
            PH = 470 * k;
            PW = PH * pa;
          }
          const at = LAST - 13 - 6 * (n - 1 - i);
          const e = ramp(frame, at, 13, EXPO_OUT);
          const o = leave(i);
          const cx = xs[i] * k, cy = ys[i] * k;
          const dx = (1 - e) * 320 * k - o * 1500 * k, dy = (1 - e) * 240 * k;
          const landed = ramp(frame, at + 9, 10);
          return (
            <React.Fragment key={i}>
              <div style={{ position: "absolute", left: cx - PW / 2 - B, top: cy - PH / 2 - B, width: PW + 2 * B, height: PH + 2 * B, background: "#f7f5ef",
                opacity: ramp(frame, at, 3), transform: `translate(${dx.toFixed(2)}px, ${dy.toFixed(2)}px) rotate(${(rots[i] + 9 * (1 - e)).toFixed(3)}deg)`,
                boxShadow: `${(8 + 20 * (1 - e)) * k}px ${(14 + 30 * (1 - e)) * k}px ${(26 + 30 * (1 - e)) * k}px rgba(0,0,0,.55)`, zIndex: i }}>
                <div style={{ position: "absolute", left: B, top: B, width: PW, height: PH, overflow: "hidden", background: "#222" }}>
                  <Cover src={src} pos="50% 45%" style={{ filter: "contrast(1.04)" }} />
                </div>
              </div>
              <div style={{ position: "absolute", left: cx - 1.5 * k - o * 1500 * k, top: railY - 12 * k, width: 3 * k, height: 26 * k, background: accent,
                opacity: landed * (1 - q), zIndex: 5 }} />
              {dates[i] ? (
                <div style={{ position: "absolute", left: cx - 300 * k - o * 1500 * k, width: 600 * k, top: railY + 26 * k, display: "flex",
                  justifyContent: "center", zIndex: 5 }}>
                  <Rise at={at + 10} q={Math.max(q, o)}>
                    <div style={{ fontFamily: ANTON, fontSize: (40 / 0.859) * k, letterSpacing: `${ANTON_TRACK}em`, color: "#fff", lineHeight: 1.04,
                      whiteSpace: "nowrap", textShadow: SHADOW }}>{dates[i]}</div>
                  </Rise>
                </div>
              ) : null}
            </React.Fragment>
          );
        })}
      </AbsoluteFill>
      {(kick || title.lines.length) ? (
        <div style={{ position: "absolute", left: 112 * k, top: 84 * k, display: "flex", flexDirection: "column" }}>
          {kick ? <Rise at={2} q={q} style={{ marginBottom: 8 * k }}><div style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: 23 * k,
            letterSpacing: "0.22em", color: accent, whiteSpace: "nowrap", textShadow: SHADOW }}>{kick}</div></Rise> : null}
          {title.lines.length ? <Rise at={5} q={q}><div style={{ fontFamily: ANTON, fontSize: title.size, letterSpacing: `${ANTON_TRACK}em`,
            color: "#fff", lineHeight: 1.04, whiteSpace: "nowrap", textShadow: SHADOW }}>{title.lines[0]}</div></Rise> : null}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ================================================================== px-then-now
// The earlier picture fills the frame; a lit diagonal seam sweeps in from the left and settles in the
// middle (4 -> 20, sfx_at 14, the sweep), the later picture on its right; each side's date sits at its top
// corner; at the exit the seam runs on and the later picture takes the frame.
const ThenNow: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { width: W, height: H, durationInFrames: dur, fps } = useVideoConfig();
  const k = useK();
  const q = useOut(12);
  const life = useLife();
  const pics = photosOf(overlay, 2);
  const a = usePhotoInfo(pics[0] || "");
  const b = usePhotoInfo(pics[1] || pics[0] || "");
  if (!pics.length) return null;
  const one = pics.length < 2;
  const srcA = pics[0], srcB = pics[1] || pics[0];
  const items = itemsOf(overlay);
  const thenL = caps(items[0]?.label ?? "", 16) || "THEN";
  const nowL = caps(items[1]?.label ?? "", 16) || "NOW";
  const thenS = caps(items[0]?.text ?? "", 40);
  const nowS = caps(items[1]?.text ?? "", 40);
  const tilt = Math.tan((12 * Math.PI) / 180) * H / 2;
  const settle = ramp(frame, 4, 16, Easing.bezier(0.25, 1.15, 0.5, 1));
  const away = ramp(frame, dur - 13, 11, IN_OUT);
  const t = frame / fps;
  const xs = lerp(-0.2 * W - tilt, 0.5 * W, settle) + Math.sin(t * 0.9) * 6 * k * settle + away * (0.75 * W + tilt);
  const clipB = `polygon(${(xs + tilt).toFixed(1)}px 0px, ${W}px 0px, ${W}px ${H}px, ${(xs - tilt).toFixed(1)}px ${H}px)`;
  const glowOn = settle > 0.001 ? 1 : 0;
  const s = (1.04 + 0.04 * life).toFixed(4);
  const gradeA = one ? "grayscale(1) sepia(.35) contrast(1.08) brightness(.95)" : "contrast(1.04) saturate(.9)";
  const label = (txt: string, sub: string, right: boolean, at: number) => (
    <div style={{ position: "absolute", top: 92 * k, [right ? "right" : "left"]: 112 * k, display: "flex", flexDirection: "column",
      alignItems: right ? "flex-end" : "flex-start" } as CSS}>
      <Rise at={at} q={q}>
        <div style={{ fontFamily: ANTON, fontSize: (50 / 0.859) * k, letterSpacing: `${ANTON_TRACK}em`, color: "#fff", lineHeight: 1.04,
          whiteSpace: "nowrap", textShadow: SHADOW }}>{txt}</div>
      </Rise>
      {sub ? (
        <Rise at={at + 4} q={q} style={{ marginTop: 6 * k }}>
          <div style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: 22 * k, letterSpacing: "0.18em", color: accent, whiteSpace: "nowrap",
            textShadow: SHADOW }}>{sub}</div>
        </Rise>
      ) : null}
    </div>
  );
  const cap_ = hasCaption(overlay);
  return (
    <AbsoluteFill style={{ background: "#000", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${s})` }}>
        <FullPhoto src={srcA} ar={a.ar} filter={gradeA} />
      </AbsoluteFill>
      <AbsoluteFill style={{ clipPath: clipB }}>
        <AbsoluteFill style={{ transform: `scale(${s})` }}>
          <FullPhoto src={srcB} ar={b.ar} filter="contrast(1.05) saturate(1.04)" />
        </AbsoluteFill>
      </AbsoluteFill>
      {/* Top shades for the dates, the seam with its light. */}
      <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(0,0,0,.55) 0%, rgba(0,0,0,.18) 22%, rgba(0,0,0,0) 38%)" }} />
      {glowOn ? (
        <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          <line x1={xs + tilt} y1={-10} x2={xs - tilt} y2={H + 10} stroke="rgba(0,0,0,.4)" strokeWidth={14 * k} style={{ filter: `blur(${6 * k}px)` }} />
          <line x1={xs + tilt} y1={-10} x2={xs - tilt} y2={H + 10} stroke="rgba(255,244,226,.5)" strokeWidth={12 * k} style={{ filter: `blur(${8 * k}px)` }} />
          <line x1={xs + tilt} y1={-10} x2={xs - tilt} y2={H + 10} stroke="#fffaf0" strokeWidth={3.2 * k} />
        </svg>
      ) : null}
      {label(thenL, thenS, false, 10)}
      {label(nowL, nowS, true, 16)}
      <CaptionShade show={cap_} strength={0.66} />
      <PxCaption ov={overlay} at={20} q={q} accent={accent} kicker={null} />
    </AbsoluteFill>
  );
};

// ================================================================== registry
export const LOOKS: Record<string, Look> = {
  "px-contact-sheet": ContactSheet,
  "px-negative-flip": NegativeFlip,
  "px-darkroom": Darkroom,
  "px-slide-projector": SlideProjector,
  "px-flatbed-scan": FlatbedScan,
  "px-shutter-burst": ShutterBurst,
  "px-album-page": AlbumPage,
  "px-archive-stamp": ArchiveStamp,
  "px-book-plate": BookPlate,
  "px-archive-envelope": ArchiveEnvelope,
  "px-drying-line": DryingLine,
  "px-dated-cascade": DatedCascade,
  "px-then-now": ThenNow,
};
