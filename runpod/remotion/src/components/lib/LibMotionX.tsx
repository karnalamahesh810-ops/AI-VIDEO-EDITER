import React from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import type { Overlay } from "../../types";
import { SpecStage } from "../smart/SmartSpec";
import { buildMotionLook, kitFrom, paramsFromOverlay, RECIPES } from "../smart/library";
import type { Look } from "./index";

/**
 * Editor v2's motion library as looks (2026-10-14): one look per recipe of components/smart/library.ts, drawn by
 * the Smart Editor's motion-spec stage. The overlay's own fields are the recipe's words (text, subtitle, label,
 * value, prefix, suffix, items, anchor, position, speed, scale), `wordAt` lands each word on its spoken time, and
 * `kit` (a kit id or a Style Kit's brand tokens) styles it; without a kit the look takes the video's accent.
 */
class Guard extends React.Component<{ children: React.ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(e: unknown) { console.warn("[motion-library] look left out:", e); }
  render() { return this.state.failed ? null : this.props.children; }
}

const MotionLook: React.FC<{ id: string; overlay: Overlay; accent: string }> = ({ id, overlay, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const ov = overlay as unknown as Record<string, unknown>;
  const spec = React.useMemo(() => {
    const params = paramsFromOverlay(ov, fps, width / height);
    return buildMotionLook(id, params, kitFrom(ov.kit, accent));
    // The overlay object is rebuilt by the editor on each change; its fields are what matter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, JSON.stringify(ov), fps, width, height, accent]);
  if (!spec) return null;
  return <Guard><SpecStage spec={spec} t={frame / fps} dur={overlay.durationInFrames / fps} /></Guard>;
};

export const LOOKS: Record<string, Look> = Object.fromEntries(RECIPES.map((r) => [r.id,
  (p: { overlay: Overlay; accent: string }) => <MotionLook id={r.id} overlay={p.overlay} accent={p.accent} />]));
