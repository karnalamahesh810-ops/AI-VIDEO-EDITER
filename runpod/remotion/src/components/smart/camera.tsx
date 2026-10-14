/**
 * The Smart Editor's camera on the footage (2026-10-14): a smart graphic may move the clip under it - a push
 * into the point it marks, a whip, a small shake on an impact, a dim while its words hold the screen. The
 * move is keyed in the graphic's spec (spec.camera.keys: scale, x, y, rot, shake, blur, dim; x / y shares of
 * the frame) and drawn here over the whole picture track, exactly like StageFx. No graphic with a camera = the
 * picture is untouched.
 */
import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { cameraAt, cleanSpec, type MotionSpec } from "./specMath";
import { stillOf } from "./SmartSpec";

export interface CameraWindow { start: number; frames: number; spec: MotionSpec; at?: number }

/** The camera moves of a document's smart graphics, in order (cleaned once). */
export const cameraWindows = (overlays: { type?: string; variant?: string; spec?: unknown; startFrame: number;
  durationInFrames: number }[], fps: number): CameraWindow[] => {
  const out: CameraWindow[] = [];
  for (const ov of overlays || []) {
    if (!ov || ov.type !== "motion" || ov.variant !== "smart-spec") continue;
    const still = stillOf((ov as { smartStill?: unknown }).smartStill);
    const spec = cleanSpec(ov.spec, still ? still.dur : ov.durationInFrames / fps);
    if (spec && spec.camera) out.push({ start: ov.startFrame, frames: ov.durationInFrames, spec, at: still?.t });
  }
  return out;
};

export const CameraFx: React.FC<{ windows: CameraWindow[]; children: React.ReactNode }> = ({ windows, children }) => {
  const f = useCurrentFrame();
  const { fps, width: W, height: H } = useVideoConfig();
  let win: CameraWindow | null = null;
  for (const w of windows) if (f >= w.start && f < w.start + w.frames) win = w;
  if (!win) return <AbsoluteFill>{children}</AbsoluteFill>;
  const c = cameraAt(win.spec, win.at ?? (f - win.start) / fps);
  const ident = Math.abs(c.scale - 1) < 1e-4 && !c.x && !c.y && !c.rot && c.blur < 0.05 && c.dim < 0.002;
  if (ident) return <AbsoluteFill>{children}</AbsoluteFill>;
  // Never show the edge of the picture: a move sideways is covered by at least as much scale.
  const need = 1 + 2 * Math.max(Math.abs(c.x), Math.abs(c.y)) + Math.abs(c.rot) * 0.012;
  const scale = Math.max(c.scale, need);
  const filters: string[] = [];
  if (c.blur > 0.05) filters.push(`blur(${(c.blur * H / 1080).toFixed(2)}px)`);
  if (c.dim > 0.002) filters.push(`brightness(${(1 - Math.min(0.8, c.dim)).toFixed(3)})`);
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{
        transform: `translate(${(-c.x * W).toFixed(2)}px, ${(-c.y * H).toFixed(2)}px) rotate(${c.rot.toFixed(3)}deg) scale(${scale.toFixed(4)})`,
        filter: filters.length ? filters.join(" ") : undefined }}>
        {children}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
