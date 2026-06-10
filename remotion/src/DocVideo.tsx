import React from "react";
import { AbsoluteFill, Sequence, Audio, OffthreadVideo, staticFile, useVideoConfig } from "remotion";
import { SceneClip } from "./components/SceneClip";
import { StatCard } from "./components/StatCard";
import scenesJson from "../../runtime/scenes.json";
import overlaysJson from "../../runtime/overlays.json";

type Scene = { i: number; start: number; end: number; type: string; clip: string | null };
const scenes = (scenesJson as { scenes: Scene[] }).scenes;

const basename = (p: string | null) => (p ? p.split(/[\\/]/).pop() || null : null);
const publicRel = (p: string | null): string | null => {
  if (!p) return null;
  const norm = p.replace(/\\/g, "/");
  const m = norm.match(/\/runtime\/(.+)$/i);
  return m ? m[1] : norm.split("/").slice(-2).join("/");
};
void basename;

type Card = { start: number; dur: number; side?: "right" | "left"; accent?: string; title: string; bullets: string[] };
const overlays = overlaysJson as { grain?: number; cards: Card[] };

// VidRush-style assembly: each ~4-6s scene = one matched b-roll clip with Ken-Burns
// motion; clean documentary captions track the narration; narration is the master audio.
export const DocVideo: React.FC = () => {
  const { fps, durationInFrames: total } = useVideoConfig();
  const f = (s: number) => Math.round(s * fps);

  // every scene gets real footage: scenes without a fetched clip reuse one from the pool
  const pool = scenes.filter((s) => s.clip).map((s) => ({ clip: s.clip as string, type: s.type }));

  // CONTIGUOUS timeline: each clip runs from its own start until the NEXT clip begins
  // (scene 0 from frame 0, last scene to the very end). This removes the silent narration
  // gaps that were rendering as black frames -> true clip-after-clip, no blackouts, no fades.
  const cut = (idx: number) => (idx <= 0 ? 0 : f(scenes[idx].start));
  const bounds = scenes.map((sc, idx) => {
    const from = cut(idx);
    const end = idx < scenes.length - 1 ? cut(idx + 1) : total;
    return { from, dur: Math.max(1, end - from) };
  });

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {scenes.map((sc, idx) => {
        let clip = sc.clip;
        let type = sc.type;
        if (!clip && pool.length) {
          const p = pool[idx % pool.length];
          clip = p.clip;
          type = p.type;
        }
        return (
          <Sequence key={`s${idx}`} from={bounds[idx].from} durationInFrames={bounds[idx].dur}>
            <SceneClip src={publicRel(clip)} type={type} index={idx} />
          </Sequence>
        );
      })}

      {/* burn/flame transitions + whoosh SFX at select cuts (every ~4th, not overused).
          Sits on the cut with screen blend so it only adds flame/film grain, never black. */}
      {scenes.map((sc, idx) => {
        if (idx === 0 || idx % 4 !== 0) return null;
        const tFrom = Math.max(0, cut(idx) - Math.round(0.5 * fps));
        const tDur = Math.round(1.0 * fps);
        const burn = `fx/burn0${((Math.floor(idx / 4) - 1) % 4) + 1}.mp4`;
        return (
          <Sequence key={`t${idx}`} from={tFrom} durationInFrames={tDur} layout="none">
            <AbsoluteFill style={{ mixBlendMode: "screen" }}>
              <OffthreadVideo src={staticFile(burn)} muted style={{ width: "100%", height: "100%", objectFit: "cover" }} />
            </AbsoluteFill>
            <Audio src={staticFile("fx/whoosh.mp3")} volume={0.5} />
          </Sequence>
        );
      })}

      {/* data-driven stat cards (VidRush fact panels) from overlays.json */}
      {overlays.cards.map((c, k) => {
        const cf = f(c.start);
        const cd = Math.max(1, Math.round(c.dur * fps));
        return (
          <Sequence key={`card${k}`} from={cf} durationInFrames={cd} layout="none">
            <StatCard title={c.title} bullets={c.bullets} accent={c.accent} side={c.side} durationInFrames={cd} />
          </Sequence>
        );
      })}

      <Audio src={staticFile("narration.mp3")} />
    </AbsoluteFill>
  );
};
