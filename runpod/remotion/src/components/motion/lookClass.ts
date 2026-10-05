import { templateFor } from "../../templates";
import type { Overlay } from "../../types";
import measured from "./lookClasses.json";

/**
 * How a look moves in and out, by what it is on screen (the owner,
 * 2026-10-05: "the map animation suddenly comes up ... add a transition to
 * the map animations, chart animations, whatever it is"):
 *
 *   full   it covers the frame (a map, a chart, a document desk, a data
 *          graphic, a full-frame number): the footage under it pushes in,
 *          softens and dims while the graphic grows in from 96 %, and the
 *          exit mirrors it back into the clip (components/motion/stage.ts);
 *   panel  a large part of the frame (a photo card, a split, a window): it
 *          grows in from 97 % with a short focus pull;
 *   text   words or a figure on the footage: they rise a few pixels into
 *          focus and leave the same way;
 *   tag    a small label (a lower third, a source tag): a short slide and fade;
 *   mark   a drawn mark on the picture (a ring, an arrow): a fade only - its
 *          stroke draws itself on.
 *
 * The class comes from the overlay (stage), then the measured table
 * (lookClasses.json: the share of the frame each look covers at rest, from
 * its own frames), then the registry (kind, category, tags).
 */
export type MotionClass = "full" | "panel" | "text" | "tag" | "mark";

const TABLE = (measured as { looks: Record<string, string> }).looks || {};
const CLASSES = new Set(["full", "panel", "text", "tag", "mark"]);

const FULL_VARIANTS = /^(pr-doc-spotlight|pr-graph-build|pr-map-path|rd-|mx-|bm-|geo-|mv-|wx-|kt-chart|an-split-wipe)/;
const PANEL_TYPES = new Set(["photo-card", "name-card", "split", "article-zoom"]);
const TAG_TYPES = new Set(["lower-third", "kicker", "stat-tag", "label-boxes", "age-tag", "clock-badge"]);
const MARK_TYPES = new Set(["arrow", "highlight"]);
const FULL_TYPES = new Set(["map", "bar-chart", "line-chart", "area-chart", "comparison", "timeline", "ranking",
  "scale-compare", "chapter"]);

export const motionClass = (ov: Overlay): MotionClass => {
  const own = String((ov as { stage?: string }).stage || "");
  if (CLASSES.has(own)) return own as MotionClass;
  if (ov.backdrop === "blur" || ov.fullFrame) return "full";
  const id = ov.template || "";
  const m = TABLE[id];
  if (m && CLASSES.has(m)) return m as MotionClass;
  const v = ov.variant || "";
  if (FULL_VARIANTS.test(v)) return "full";
  if (/^an-/.test(v)) return "mark";
  const t = templateFor(id);
  const type = String(ov.type || t?.component || "");
  if (FULL_TYPES.has(type)) return "full";
  if (PANEL_TYPES.has(type)) return "panel";
  if (TAG_TYPES.has(type)) return "tag";
  if (MARK_TYPES.has(type)) return "mark";
  if (!t) return "text";
  if (t.kind === "map" || (t.tags || []).includes("own-backdrop") || t.category === "MAPS") return "full";
  if (t.kind === "card" && ["CHARTS", "COMPARISONS", "DOCUMENTS", "TIMELINES"].includes(t.category)) return "full";
  if (t.category === "IMAGES") return "panel";
  if (t.category === "LOWER_THIRDS") return "tag";
  if (t.category === "CALLOUTS") return "mark";
  return "text";
};
