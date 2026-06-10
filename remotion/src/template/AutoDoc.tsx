import React from "react";
import { AbsoluteFill, Sequence, Audio, staticFile, useVideoConfig } from "remotion";
import { SceneClip } from "../components/SceneClip";
import { GradeOverlay } from "./components/GradeOverlay";
import { REGISTRY } from "./registry";
import { getTheme } from "./theme";
import scenesJson from "../../../runtime/scenes.json";
import editJson from "../../../runtime/edit.json";

// Data-driven auto-edited doc: a b-roll backbone (contiguous, Ken-Burns) with
// overlays + SFX placed by the "director" (edit.json), plus narration + grade.
type Scene = { i: number; start: number; end: number; type: string; clip: string | null };
const scenes = (scenesJson as { scenes: Scene[] }).scenes;
const basename = (p: string | null) => (p ? p.split(/[\\/]/).pop() || null : null);
// resolve a clip path (absolute or relative) to a path under the public dir (runtime/),
// e.g. "C:\...\runtime\broll_pool\pool_000.mp4" -> "broll_pool/pool_000.mp4"
const publicRel = (p: string | null): string | null => {
  if (!p) return null;
  const norm = p.replace(/\\/g, "/");
  const m = norm.match(/\/runtime\/(.+)$/i);
  return m ? m[1] : norm.split("/").slice(-2).join("/");
};

type Overlay = { start: number; dur: number; component: string; props?: Record<string, unknown>; sfx?: string };
type Edit = { theme?: string; grade?: { vignette?: number; grain?: number } | null; overlays: Overlay[] };
const edit = editJson as Edit;

// short SFX name -> file in the public dir (runtime/fx)
const SFX: Record<string, string> = {
  whoosh: "fx/sfx_whoosh.mp3", pop: "fx/sfx_pop.mp3", impact: "fx/sfx_impact.mp3", boom: "fx/sfx_boom.mp3",
  click: "fx/sfx_click.mp3", riser: "fx/sfx_riser.mp3", swoosh: "fx/sfx_swoosh.mp3", cash: "fx/sfx_cash.mp3",
  type: "fx/sfx_type.mp3", paper: "fx/sfx_paper.mp3", highlight: "fx/sfx_highlight.mp3", glitch: "fx/sfx_glitch.mp3", ding: "fx/sfx_ding.mp3",
};
// SFX cut to ~30% of prior level (user: "SFX super high") -> barely-there accents, ~-30 dB under the VO
const SFX_VOL: Record<string, number> = {
  whoosh: 0.03, pop: 0.03, impact: 0.035, boom: 0.035, click: 0.025, riser: 0.03, swoosh: 0.03,
  cash: 0.03, type: 0.03, paper: 0.03, highlight: 0.03, glitch: 0.03, ding: 0.03,
};

export const AUTODOC_FRAMES = Math.max(1, Math.round(((scenes[scenes.length - 1]?.end || 240) + 0.6) * 30));

export const AutoDoc: React.FC = () => {
  const { fps, durationInFrames: total } = useVideoConfig();
  const f = (s: number) => Math.round(s * fps);
  const th = getTheme(edit.theme);

  // b-roll backbone: contiguous (no black gaps); pool-fallback for any missing scene
  // Each scene's UNIQUE clip plays its own slot [start -> next scene's start], back-to-back
  // (contiguous = no blackouts). No clip is ever reused (no pool fallback), and clips never
  // freeze or loop: downloaded sections are longer than the slot, so a clip simply plays for
  // its slot and then the NEXT scene's clip takes over. Scenes still being fetched show a brief
  // neutral plate (never a repeat) until their clip lands.
  const cut = (i: number) => (i <= 0 ? 0 : f(scenes[i].start));

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {scenes.map((sc, idx) => {
        const rel = publicRel(sc.clip);
        const from = cut(idx);
        const end = idx < scenes.length - 1 ? cut(idx + 1) : total;
        const slotSec = (end - from) / fps;
        // clips are ~5s; slow each one to FILL its slot (no freeze, no loop, no repeat).
        // Dramatic disaster footage reads well slightly slowed; clamp + loop backstop the few 12s slots.
        const playbackRate = Math.max(0.5, Math.min(1, 5.0 / slotSec));
        return (
          <Sequence key={`s${idx}`} from={from} durationInFrames={Math.max(1, end - from)}>
            <SceneClip src={rel} type="video" index={idx} loop playbackRate={playbackRate} />
          </Sequence>
        );
      })}

      {/* director-placed overlays + SFX */}
      {edit.overlays.map((o, i) => {
        const C = REGISTRY[o.component as keyof typeof REGISTRY] as React.ComponentType<any> | undefined;
        if (!C) return null;
        const from = f(o.start);
        const dur = Math.max(1, f(o.dur));
        const sfxSrc = o.sfx ? SFX[o.sfx] : undefined;
        return (
          <Sequence key={`o${i}`} from={from} durationInFrames={dur} layout="none">
            <C {...(o.props || {})} theme={th} durationInFrames={dur} />
            {sfxSrc ? <Audio src={staticFile(sfxSrc)} volume={SFX_VOL[o.sfx as string] ?? 0.5} /> : null}
          </Sequence>
        );
      })}

      {/* clean hard cuts for this documentary — no flame transitions (wrong tone for the topic) */}

      {edit.grade ? (
        <GradeOverlay vignette={edit.grade.vignette} grain={edit.grade.grain} theme={th} durationInFrames={total} />
      ) : null}

      {process.env.REMOTION_NO_VO !== "1" ? <Audio src={staticFile("narration.mp3")} /> : null}
    </AbsoluteFill>
  );
};
