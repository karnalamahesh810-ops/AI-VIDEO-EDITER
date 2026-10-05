import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { SUBLINE, SUBLINE_CAP } from "../fonts";
import type { Overlay } from "../../types";
import { useK } from "../pro/ProGraphics";
import { CAPTION_SAFE_ZONE, CaptionsOn } from "../layout";

/**
 * THE SOURCE TAG ("src-tag"): the citation for a fact whose source the
 * narration names - "SOURCE: USBR, 2024" - small and quiet in a low corner
 * for about three seconds (src/sources.py places it, behind
 * config.SOURCE_TAGS; the words come only from the narration, never
 * invented).
 *
 * The pack's small-line language (LibPackPlaces): Inter Tight 700 in tracked
 * caps about 17 px tall at 1080p, white on the picture with a soft dark
 * shadow - no box, no band, no stroke - under ONE thin rule in the accent.
 * Frames (30 fps from the look's first frame):
 *
 *    0 ->  9   the rule draws out from the corner
 *    3 -> 12   "SOURCE:" rises out of its mask under the rule
 *    6 -> 16   the name (and the year, when one was said) rises after it
 *   last 9     the words sink back and fade, the rule draws back to the corner
 *
 * overlay.text = the source ("USBR", "PACIFIC INSTITUTE"); overlay.subtitle =
 * the year; overlay.label = the word before the colon ("Source").
 * overlay.align "right" takes the other low corner (the planner moves it off
 * a face). With burned-in captions on, it sits above the caption strip
 * instead of in it. It makes no sound.
 */

type Look = React.FC<{ overlay: Overlay; accent: string }>;

const AMBER = "#F5B400";
const WHITE = "#FFFFFF";
const MARGIN = 96;               // px at 1080p: the safe margin
const SIZE = 24;                 // px at 1080p (caps about 17 px tall)
const MIN_SIZE = 18;             // a long name shrinks to this, never under it
const TRACK = 0.14;              // letter spacing (em)
const RULE = 2;                  // px at 1080p
const ROOM = 0.42;               // the widest the tag may be, a share of the frame's width
const EXIT = 9;                  // frames (30 fps) it takes to leave

const clamp01 = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);
const easeOut = (t: number) => 1 - (1 - t) ** 3;
const easeIn = (t: number) => t * t * t;
const px = (n: number, k: number) => `${(n * k).toFixed(2)}px`;

const clean = (v: unknown, max: number): string => {
  const s = (typeof v === "string" ? v : typeof v === "number" && Number.isFinite(v) ? String(v) : "")
    .replace(/[‘’]/g, "'").replace(/[“”"]/g, "").replace(/\s+/g, " ").trim().toUpperCase();
  if (s.length <= max) return s;
  const cut = s.slice(0, max);
  const sp = cut.lastIndexOf(" ");
  return (sp > max * 0.6 ? cut.slice(0, sp) : cut).replace(/[\s,·:;-]+$/, "");
};

/** Inter Tight 700 caps, roughly (em), with their tracking. */
const widthEm = (s: string) =>
  Array.from(s).reduce((a, c) => a + (c === " " ? 0.24 : /[0-9]/.test(c) ? 0.56 : /[MW@&]/.test(c) ? 0.86
    : /[IJ1.,:'·|]/.test(c) ? 0.3 : 0.64) + TRACK, 0);

/** An edge, a close and a wide shadow: enough body to hold small white caps on snow or a white sky. */
const SHADOW = (k: number) => `drop-shadow(0 0 ${px(1.2, k)} rgba(0,0,0,.85)) drop-shadow(0 ${px(1, k)} ${px(2, k)} rgba(0,0,0,.6)) `
  + `drop-shadow(0 ${px(2, k)} ${px(9, k)} rgba(0,0,0,.55))`;

const SourceTag: Look = ({ overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames: dur, width, height } = useVideoConfig();
  const k = useK();
  const captions = React.useContext(CaptionsOn);
  const S = fps / 30;
  const right = String(overlay.align || "").toLowerCase() === "right";
  const ac = overlay.theme && overlay.theme !== "accent" && accent ? accent : AMBER;

  const label = clean(overlay.label, 14) || "SOURCE";
  const name = clean(overlay.text, 44);
  const year = clean(overlay.subtitle, 16);
  if (!name) return null;
  const line = `${label}: ${name}${year ? `, ${year}` : ""}`;
  const size = Math.max(MIN_SIZE * k, Math.min(SIZE * k, (ROOM * width) / Math.max(1, widthEm(line))));
  const cap = size * SUBLINE_CAP;

  // In, hold, out (frames at 30 fps, stretched to the composition's rate).
  const exitAt = Math.max(Math.round(16 * S), dur - Math.round(EXIT * S));
  const q = easeIn(clamp01((frame - exitAt) / (6 * S)));                     // the words leave first
  const qRule = easeIn(clamp01((frame - exitAt - 2 * S) / (7 * S)));         // then the rule draws back
  const pRule = easeOut(clamp01(frame / (9 * S))) * (1 - qRule);
  const pLabel = easeOut(clamp01((frame - 3 * S) / (9 * S)));
  const pName = easeOut(clamp01((frame - 6 * S) / (10 * S)));

  const mx = MARGIN * (width / 1920);
  const bottom = captions ? height * CAPTION_SAFE_ZONE : MARGIN * (height / 1080);
  const font: React.CSSProperties = { fontFamily: SUBLINE, fontWeight: 700, fontSize: size, lineHeight: 1,
    letterSpacing: `${TRACK}em`, textTransform: "uppercase", whiteSpace: "pre" };
  const rise = (p: number): React.CSSProperties => ({ display: "inline-block", opacity: p * (1 - q),
    transform: `translateY(${((1 - p) * 0.9 + q * 0.45).toFixed(4)}em)` });

  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", bottom, ...(right ? { right: mx } : { left: mx }), display: "flex",
        flexDirection: "column", alignItems: right ? "flex-end" : "flex-start" }}>
        <div style={{ display: "inline-flex", flexDirection: "column", alignItems: "stretch" }}>
          {/* the one thin rule, drawn out from the corner */}
          <div style={{ height: Math.max(1.5, RULE * k), background: ac, borderRadius: RULE * k,
            marginBottom: cap * 0.78, transformOrigin: right ? "100% 50%" : "0% 50%",
            transform: `scaleX(${pRule.toFixed(4)})`, opacity: pRule > 0.001 ? 1 : 0,
            boxShadow: `0 ${px(1, k)} ${px(3, k)} rgba(0,0,0,.5)` }} />
          {/* the words rise out of a mask under it */}
          {/* (the shadow on the wrapper, so the mask never cuts it) */}
          <div style={{ ...font, filter: SHADOW(k), marginRight: `${-TRACK}em` }}>
            <div style={{ clipPath: "inset(-0.5em -0.7em -0.14em -0.7em)" }}>
              <span style={{ ...rise(pLabel), color: "rgba(255,255,255,.72)" }}>{`${label}: `}</span>
              <span style={{ ...rise(pName), color: WHITE }}>{name}</span>
              {year ? <span style={{ ...rise(pName), color: "rgba(255,255,255,.86)", fontWeight: 600 }}>{`, ${year}`}</span> : null}
            </div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

/**
 * The source tag's own line inside a full-screen look (the real data graphics, LibRealData.tsx): the same thin
 * accent rule and rising tracked caps in the same low corner, read as "SOURCE: USBR · DATA AS OF OCT 3, 2026".
 * `at` delays it (frames at 30 fps from the look's first frame); it leaves with the look's last `EXIT` frames.
 * `room` is the widest it may be, a share of the frame's width.
 */
export const SourceLine: React.FC<{ name: string; note?: string; label?: string; align?: "left" | "right";
  at?: number; accent?: string; room?: number }> = ({ name, note, label, align = "left", at = 0, accent, room = 0.62 }) => {
  const own = useCurrentFrame();
  const { fps, durationInFrames: dur, width, height } = useVideoConfig();
  const k = useK();
  const captions = React.useContext(CaptionsOn);
  const S = fps / 30;
  const frame = own - at * S;
  const right = align === "right";
  const ac = accent || AMBER;
  const lab = clean(label, 14) || "SOURCE";
  const who = clean(name, 44);
  const tail = clean(note, 40);
  if (!who) return null;
  const line = `${lab}: ${who}${tail ? ` · ${tail}` : ""}`;
  const size = Math.max(MIN_SIZE * k, Math.min(SIZE * k, (room * width) / Math.max(1, widthEm(line))));
  const cap = size * SUBLINE_CAP;
  const exitAt = Math.max(Math.round((16 + at) * S), dur - Math.round(EXIT * S));
  const q = easeIn(clamp01((own - exitAt) / (6 * S)));
  const qRule = easeIn(clamp01((own - exitAt - 2 * S) / (7 * S)));
  const pRule = easeOut(clamp01(frame / (9 * S))) * (1 - qRule);
  const pLabel = easeOut(clamp01((frame - 3 * S) / (9 * S)));
  const pName = easeOut(clamp01((frame - 6 * S) / (10 * S)));
  const mx = MARGIN * (width / 1920);
  const bottom = captions ? height * CAPTION_SAFE_ZONE : MARGIN * 0.8 * (height / 1080);
  const font: React.CSSProperties = { fontFamily: SUBLINE, fontWeight: 700, fontSize: size, lineHeight: 1,
    letterSpacing: `${TRACK}em`, textTransform: "uppercase", whiteSpace: "pre" };
  const rise = (p: number): React.CSSProperties => ({ display: "inline-block", opacity: p * (1 - q),
    transform: `translateY(${((1 - p) * 0.9 + q * 0.45).toFixed(4)}em)` });
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div style={{ position: "absolute", bottom, ...(right ? { right: mx } : { left: mx }), display: "flex",
        flexDirection: "column", alignItems: right ? "flex-end" : "flex-start" }}>
        <div style={{ display: "inline-flex", flexDirection: "column", alignItems: "stretch" }}>
          <div style={{ height: Math.max(1.5, RULE * k), background: ac, borderRadius: RULE * k,
            marginBottom: cap * 0.78, transformOrigin: right ? "100% 50%" : "0% 50%",
            transform: `scaleX(${pRule.toFixed(4)})`, opacity: pRule > 0.001 ? 1 : 0,
            boxShadow: `0 ${px(1, k)} ${px(3, k)} rgba(0,0,0,.5)` }} />
          <div style={{ ...font, filter: SHADOW(k), marginRight: `${-TRACK}em` }}>
            <div style={{ clipPath: "inset(-0.5em -0.7em -0.14em -0.7em)" }}>
              <span style={{ ...rise(pLabel), color: "rgba(255,255,255,.72)" }}>{`${lab}: `}</span>
              <span style={{ ...rise(pName), color: WHITE }}>{who}</span>
              {tail ? <span style={{ ...rise(pName), color: "rgba(255,255,255,.86)", fontWeight: 600 }}>{` · ${tail}`}</span> : null}
            </div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const LOOKS: Record<string, Look> = {
  "src-tag": SourceTag,
};
