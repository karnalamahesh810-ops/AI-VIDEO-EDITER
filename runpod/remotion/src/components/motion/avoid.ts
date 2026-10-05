import type { Box, Overlay, Scene, SceneMedia } from "../../types";

/**
 * What a look must keep its words off, from the picture under it (the owner,
 * 2026-10-05: "never over text burned into the footage, faces or subjects";
 * "never place a look's text over a broadcaster logo"): the station logos the
 * worker found in the corners (media.focus.logos), the faces
 * (media.focus.faceBoxes), lettering found on the picture (media.focus kind
 * "text", and the rows of burned-in lettering media.focus.bands), each as a
 * share of the FRAME (the picture covers the frame, centred). A clip whose
 * lettering could not be placed (media.focus.overlay) keeps the low band of
 * the frame clear, where chyrons and tickers sit.
 */
const num = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** A box of the source picture as a box of a frame of aspect `dst` it covers (centred). */
export const coverShare = (b: Box, src: number, dst: number): Box | null => {
  if (![b?.x, b?.y, b?.w, b?.h].every(num) || b.w <= 0 || b.h <= 0) return null;
  let { x, y, w, h } = b;
  if (src > 0 && dst > 0 && Math.abs(src - dst) > 1e-3) {
    if (src > dst) {
      const k = dst / src;
      x = (b.x - (1 - k) / 2) / k;
      w = b.w / k;
    } else {
      const k = src / dst;
      y = (b.y - (1 - k) / 2) / k;
      h = b.h / k;
    }
  }
  const x0 = Math.max(0, x), y0 = Math.max(0, y), x1 = Math.min(1, x + w), y1 = Math.min(1, y + h);
  return x1 > x0 && y1 > y0 ? { x: x0, y: y0, w: x1 - x0, h: y1 - y0 } : null;
};

export const mediaAvoid = (m: SceneMedia | null | undefined, frameAspect = 16 / 9): Box[] => {
  const focus = m?.focus;
  if (!focus || typeof focus !== "object") return [];
  const src = num(focus.aspect) ? focus.aspect : frameAspect;
  const out: Box[] = [];
  const add = (b: Box | null) => {
    if (b && b.w > 0.005 && b.h > 0.005) out.push(b);
  };
  for (const l of Array.isArray(focus.logos) ? focus.logos : []) add(coverShare(l, src, frameAspect));
  for (const f of Array.isArray(focus.faceBoxes) ? focus.faceBoxes : []) {
    if (Array.isArray(f) && f.length >= 4) {
      // brows to chin, padded to the head and shoulders
      add(coverShare({ x: f[0] - 0.45 * f[2], y: f[1] - 0.6 * f[3], w: f[2] * 1.9, h: f[3] * 2.4 }, src, frameAspect));
    }
  }
  for (const band of Array.isArray(focus.bands) ? focus.bands : []) {
    if (num(band?.y) && num(band?.h)) add(coverShare({ x: 0, y: band.y, w: 1, h: band.h }, src, frameAspect));
  }
  if (focus.kind === "text" && focus.box) add(coverShare(focus.box, src, frameAspect));
  if (focus.kind === "face" && focus.box && !(Array.isArray(focus.faceBoxes) && focus.faceBoxes.length)) {
    add(coverShare(focus.box, src, frameAspect));
  }
  if (focus.overlay === true && !(Array.isArray(focus.bands) && focus.bands.length)) {
    add({ x: 0, y: 0.8, w: 1, h: 0.2 });
  }
  return out;
};

/** The boxes to keep clear for an overlay: those of the scene it starts on. */
export const sceneAvoid = (ov: Overlay, scenes: Scene[] | undefined): Box[] => {
  const at = ov.startFrame;
  const sc = (scenes || []).find((s) => at >= s.startFrame && at < s.startFrame + s.durationInFrames);
  return sc ? mediaAvoid(sc.media) : [];
};
