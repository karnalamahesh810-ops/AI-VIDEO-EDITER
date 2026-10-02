import React from "react";
import { gradeMedians, sceneGrade, validMedians, type GradeMedians, type GradeSettings } from "./gradeMath";
import type { Scene } from "../types";

/**
 * The video's grade as the scene track sees it (gradeMath.ts): the
 * document's settings and the median tone of its scenes, computed once in
 * Main and read by every SceneClip. Null outside Main (or without a grade):
 * the scenes draw exactly as before.
 */
export interface GradeState { settings: GradeSettings; medians: GradeMedians | null }

export const GradeContext = React.createContext<GradeState | null>(null);

/**
 * The medians the worker froze in the document (doc.grade.medians: a Replace
 * Clip must not shift every other scene's grade, or every chunk of a split
 * render would change), else the scenes' own.
 */
export const gradeStateFor = (grade: unknown, scenes: Scene[]): GradeState | null => {
  if (!grade || typeof grade !== "object") return null;
  const settings = grade as GradeSettings & { medians?: unknown };
  return { settings, medians: validMedians(settings.medians) ? settings.medians : gradeMedians(scenes) };
};

const table = (values: number[]) => values.map((v) => v.toFixed(4)).join(" ");

/**
 * This scene's grade: the CSS filter its picture takes (first in its filter
 * list, before the scene's own treatment) and the SVG that defines it (drawn
 * once inside the scene; it takes no space). Null when the scene is not graded.
 */
export const useSceneGrade = (scene: Scene): { filter: string; defs: React.ReactNode } | null => {
  const state = React.useContext(GradeContext);
  const media = scene.media as Scene["media"] & { tone?: unknown };
  return React.useMemo(() => {
    if (!state) return null;
    const g = sceneGrade({ treatment: scene.treatment, media }, state.settings, state.medians);
    if (!g) return null;
    const id = `tg-grade-${scene.id}`.replace(/[^A-Za-z0-9_-]/g, "_");
    const defs = (
      <svg width={0} height={0} aria-hidden="true"
        style={{ position: "absolute", width: 0, height: 0, overflow: "hidden", pointerEvents: "none" }}>
        <defs>
          <filter id={id} x="0" y="0" width="1" height="1" filterUnits="objectBoundingBox"
            colorInterpolationFilters="sRGB">
            <feColorMatrix type="saturate" values={g.sat.toFixed(4)} />
            <feComponentTransfer>
              <feFuncR type="table" tableValues={table(g.r)} />
              <feFuncG type="table" tableValues={table(g.g)} />
              <feFuncB type="table" tableValues={table(g.b)} />
            </feComponentTransfer>
          </filter>
        </defs>
      </svg>
    );
    return { filter: `url(#${id})`, defs };
  }, [state, scene.id, scene.treatment, media?.type, media?.tone]);
};
