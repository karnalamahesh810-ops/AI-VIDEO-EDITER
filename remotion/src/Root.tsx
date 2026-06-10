import React from "react";
import { Composition } from "remotion";
import { DocVideo } from "./DocVideo";
import { TemplateDemo, TEMPLATE_DEMO_FRAMES } from "./template/TemplateDemo";
import { AutoDoc, AUTODOC_FRAMES } from "./template/AutoDoc";
import segsJson from "../../runtime/segments.json";

const FPS = 30;
const segs = (segsJson as { segments: Array<{ end: number }> }).segments;
const lastEnd = segs.length ? segs[segs.length - 1].end : 240;
const durationInFrames = Math.ceil(lastEnd * FPS) + 18;

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="AutoDoc"
        component={AutoDoc}
        durationInFrames={AUTODOC_FRAMES}
        fps={FPS}
        width={1920}
        height={1080}
      />
      <Composition
        id="DocVideo"
        component={DocVideo}
        durationInFrames={durationInFrames}
        fps={FPS}
        width={1920}
        height={1080}
      />
      <Composition
        id="TemplateDemo"
        component={TemplateDemo}
        durationInFrames={TEMPLATE_DEMO_FRAMES}
        fps={FPS}
        width={1920}
        height={1080}
      />
    </>
  );
};
