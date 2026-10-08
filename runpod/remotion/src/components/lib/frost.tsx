import React from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import { clamp01, cubicIn, cubicInOut } from "../motion/ease";
import { rgba } from "./proKit";

/**
 * Frosted glass that really frosts (looks pack 4, 2026-10-08). The kt- looks' Glass (LibKtDates.tsx) clips its
 * frosted layer with a clip-path on the layer's parent, and a parent with a clip-path (or an opacity, a filter,
 * a mask) is a "backdrop root": the layer's backdrop-filter then sees nothing behind it, so the footage under the
 * card was never blurred - only darkened. Here the frosted layer has no such parent: it reveals itself with its own
 * clip-path and opacity, and its words sit in a sibling layer.
 *
 * The look's wrapper (MotionWrap) fades the overlay in and out over its first and last frames, and while it does
 * no backdrop can be read either: the frost therefore pulls focus in just after the entry (frames 12-24) and back
 * out just before the exit (it is gone 14 frames before the end), so the footage behind the card softens and
 * sharpens smoothly instead of popping.
 */
const TOP = "rgba(24,27,34,0.76)";
const BOTTOM = "rgba(9,11,15,0.86)";
export const FROST_HAIRLINE = "rgba(255,255,255,0.13)";

export const Frost: React.FC<{ x: number; y: number; w: number; h: number; k: number; p: number; out: number;
  right?: boolean; radius?: number; edge?: string; edgeP?: number; children?: React.ReactNode }> =
  ({ x, y, w, h, k, p, out, right = false, radius = 16, edge, edgeP = 1, children }) => {
    const f = useCurrentFrame();
    const { fps, durationInFrames: dur } = useVideoConfig();
    const S = fps / 30;
    const t = f / S;
    const d30 = dur / S;
    const open = clamp01(p) * (1 - cubicIn(clamp01(out * 1.25 - 0.2)));
    const hide = (1 - open) * 100;
    const rr = radius * k;
    const clip = `inset(0 ${right ? 0 : hide.toFixed(2)}% 0 ${right ? hide.toFixed(2) : 0}% round ${rr.toFixed(1)}px)`;
    const o = clamp01(p * 2.2) * (1 - out * 0.5);
    // the frost's focus pull: in after the wrapper's entry, out before its exit
    const frost = cubicInOut(clamp01((t - 12) / 12)) * (1 - cubicInOut(clamp01((t - (d30 - 30)) / 16)));
    const blur = 18 * k * frost;
    const filter = blur > 0.2 ? `blur(${blur.toFixed(1)}px) saturate(${(1 + 0.15 * frost).toFixed(3)})` : undefined;
    return (
      <>
        {/* the shadow under it */}
        <div style={{ position: "absolute", left: x, top: y, width: w, height: h, borderRadius: rr, opacity: clamp01(p) * (1 - out) * 0.9,
          boxShadow: `0 ${(18 * k).toFixed(1)}px ${(46 * k).toFixed(1)}px rgba(0,0,0,0.42), 0 ${(3 * k).toFixed(1)}px ${(10 * k).toFixed(1)}px rgba(0,0,0,0.25)`,
          clipPath: `inset(-${(80 * k).toFixed(0)}px ${right ? -80 * k : (hide / 100) * w - 80 * k}px -${(80 * k).toFixed(0)}px ${right ? (hide / 100) * w - 80 * k : -80 * k}px)` }} />
        {/* the frosted layer itself: its own clip and opacity, no parent that would hide the footage from it */}
        <div style={{ position: "absolute", left: x, top: y, width: w, height: h, borderRadius: rr, clipPath: clip, opacity: o,
          backdropFilter: filter, WebkitBackdropFilter: filter, background: `linear-gradient(180deg, ${TOP} 0%, ${BOTTOM} 100%)`,
          boxShadow: `inset 0 ${(1 * k).toFixed(1)}px 0 rgba(255,255,255,0.08), inset 0 0 0 ${Math.max(1, k).toFixed(1)}px ${FROST_HAIRLINE}` }} />
        {edge ? (
          <div style={{ position: "absolute", left: x, top: y, width: w, height: h, borderRadius: rr, clipPath: clip, opacity: o,
            overflow: "hidden", pointerEvents: "none" }}>
            <div style={{ position: "absolute", top: 0, bottom: 0, [right ? "right" : "left"]: 0, width: 6 * k,
              background: `linear-gradient(180deg, ${rgba(edge, 1)} 0%, ${rgba(edge, 0.82)} 100%)`,
              transformOrigin: "top", transform: `scaleY(${clamp01(edgeP).toFixed(4)})`,
              boxShadow: `0 0 ${(14 * k).toFixed(1)}px ${rgba(edge, 0.55)}` }} />
          </div>
        ) : null}
        <div style={{ position: "absolute", left: x, top: y, width: w, height: h, borderRadius: rr, overflow: "hidden", clipPath: clip,
          opacity: o }}>
          {children}
        </div>
      </>
    );
  };
