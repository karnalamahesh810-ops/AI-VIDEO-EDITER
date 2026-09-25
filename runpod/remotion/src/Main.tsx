import React from "react";
import { AbsoluteFill, Audio, Sequence } from "remotion";
import { SceneClip } from "./components/SceneClip";
import { Captions } from "./components/Captions";
import { TitleOverlay } from "./components/TitleOverlay";
import { CalloutOverlay } from "./components/CalloutOverlay";
import { TypewriterTitle } from "./components/TypewriterTitle";
import { SplitScreen } from "./components/SplitScreen";
import { ChapterCard } from "./components/ChapterCard";
import { StatOverlay } from "./components/StatOverlay";
import { BarChartOverlay } from "./components/BarChartOverlay";
import { ComparisonOverlay } from "./components/ComparisonOverlay";
import { MapOverlay } from "./components/MapOverlay";
import { QuoteOverlay } from "./components/QuoteOverlay";
import { TimelineOverlay } from "./components/TimelineOverlay";
import { HighlightOverlay } from "./components/HighlightOverlay";
import { LowerThird } from "./components/LowerThird";
import { ArrowOverlay } from "./components/ArrowOverlay";
import { SentenceHighlight } from "./components/SentenceHighlight";
import { ArticleZoom } from "./components/ArticleZoom";
import { DateStamp } from "./components/DateStamp";
import { DocumentaryMap } from "./components/DocumentaryMap";
import { PhotoCard, NameCard, TimeRuler, ObjectCallout, EditorialChapter } from "./components/ReferenceGraphics";
import type { Overlay, OverlayType, TimelineProps } from "./types";

/**
 * Overlay type -> component.
 *
 * A lookup rather than a switch so the keys can be type-checked against
 * OverlayType: adding a template to types.ts without wiring it here becomes a
 * compile error instead of a title card appearing where a chart should be.
 * The Python test suite checks this same set against director.TEMPLATES.
 */
const OVERLAYS: Record<
  OverlayType,
  React.FC<{ overlay: Overlay; accent: string }>
> = {
  title: TitleOverlay,
  chapter: (p) => p.overlay.variant ? <EditorialChapter {...p}/> : <ChapterCard {...p}/>,
  callout: CalloutOverlay,
  typewriter: TypewriterTitle,
  stat: StatOverlay,
  "bar-chart": BarChartOverlay,
  comparison: ComparisonOverlay,
  map: (p) => p.overlay.variant ? <DocumentaryMap {...p}/> : <MapOverlay {...p}/>,
  quote: QuoteOverlay,
  timeline: (p) => p.overlay.variant === 'ruler' ? <TimeRuler {...p}/> : <TimelineOverlay {...p}/>,
  highlight: HighlightOverlay,
  "lower-third": LowerThird,
  arrow: (p) => p.overlay.anchor ? <ObjectCallout {...p}/> : <ArrowOverlay {...p}/>,
  "sentence-highlight": SentenceHighlight,
  "article-zoom": ArticleZoom,
  "date-stamp": DateStamp,
  "photo-card": PhotoCard,
  "name-card": NameCard,
  // Split takes its two media entries rather than a text payload, so it gets
  // a small adapter instead of the shared signature.
  split: ({ overlay, accent }) =>
    overlay.media && overlay.media.length >= 2 ? (
      <SplitScreen top={overlay.media[0]} bottom={overlay.media[1]} accent={accent} />
    ) : null,
};

const renderOverlay = (ov: Overlay, accent: string) => {
  const Component = OVERLAYS[ov.type];
  // A document can arrive from the editor or an older schema, so an unknown
  // type is possible at runtime even though it is not at compile time.
  if (!Component) return null;
  return <Component overlay={ov} accent={accent} />;
};

export const Main: React.FC<TimelineProps> = (props) => {
  const { scenes, overlays, audio, bgm, captions } = props;
  // Track toggles from the editor. Absent means on, so older timelines
  // render exactly as before.
  const showOverlays = props.overlaysEnabled !== false;

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {/* Visual track — one clip per spoken clause */}
      {scenes.map((scene) => (
        <Sequence
          key={scene.id}
          from={scene.startFrame}
          durationInFrames={scene.durationInFrames}
        >
          <SceneClip scene={scene} />
        </Sequence>
      ))}

      {/* Caption track, burned in over the visuals but under the graphics */}
      {captions.enabled &&
        scenes.map((scene) => (
          <Sequence
            key={`cap-${scene.id}`}
            from={scene.startFrame}
            durationInFrames={scene.durationInFrames}
          >
            <Captions scene={scene} style={captions} />
          </Sequence>
        ))}

      {/* Overlay track — graphics sit on top of everything visual */}
      {showOverlays && (overlays || []).map((ov, i) => (
        <Sequence
          key={`ov-${i}`}
          from={ov.startFrame}
          durationInFrames={ov.durationInFrames}
        >
          {renderOverlay(ov, captions.accent)}
        </Sequence>
      ))}

      {/* Audio: narration drives the whole timeline; bgm sits well under it */}
      {audio?.url ? <Audio src={audio.url} volume={audio.volume ?? 1} /> : null}
      {bgm?.url ? <Audio src={bgm.url} volume={bgm.volume ?? 0.12} loop /> : null}
    </AbsoluteFill>
  );
};
