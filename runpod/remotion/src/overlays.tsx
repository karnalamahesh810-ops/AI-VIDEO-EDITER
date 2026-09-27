import React from "react";
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
import { Bullets, LabelBoxes, RingStat, StatTag } from "./components/FootageTags";
import { AgeTag, BarTitle, ClockBadge, Kicker, MemoBox, PersonTag, RedStrip, SwooshTitle, UnderlineTitle, WordType } from "./components/TextGraphics";
import { IconPop, LineChart, PathSteps, ProgressSteps, Span } from "./components/DataGraphics";
import { AreaChart, Banner, Counter, Donut, IconArray, NumberRoll, ProgressBar, Ranking, ScaleCompare, Trend, YearRoll } from "./components/MotionGraphics";
import { SatelliteMap, SpreadMap } from "./components/MapLooks";
import type { Overlay, OverlayType } from "./types";

/** Colour themes an overlay can ask for instead of the brand accent. */
export const THEMES: Record<string, string> = {
  gold: "#d6a83c", red: "#e63946", teal: "#2ec4b6", blue: "#2f80ed", white: "#f4f1ea", amber: "#f4a100",
};

const PERSON_TAGS = new Set(["tag", "line", "serif", "chyron"]);

export type OverlayComponent = React.FC<{ overlay: Overlay; accent: string }>;

/**
 * Overlay type -> component.
 *
 * A lookup rather than a switch so the keys can be type-checked against
 * OverlayType: adding a template to types.ts without wiring it here becomes a
 * compile error instead of a title card appearing where a chart should be.
 * The Python test suite checks this same set against director.TEMPLATES.
 * Shared by the overlay track (Main.tsx) and full-screen animation scenes
 * (components/AnimationScene.tsx) so both draw a template the same way.
 */
export const OVERLAYS: Record<OverlayType, OverlayComponent> = {
  title: TitleOverlay,
  chapter: (p) => p.overlay.variant ? <EditorialChapter {...p}/> : <ChapterCard {...p}/>,
  callout: CalloutOverlay,
  typewriter: TypewriterTitle,
  stat: StatOverlay,
  "bar-chart": BarChartOverlay,
  comparison: ComparisonOverlay,
  map: (p) => {
    const v = p.overlay.variant || "";
    if (v.startsWith("satellite")) return <SatelliteMap {...p}/>;
    if (v.startsWith("spread")) return <SpreadMap {...p}/>;
    return v ? <DocumentaryMap {...p}/> : <MapOverlay {...p}/>;
  },
  quote: QuoteOverlay,
  timeline: (p) => p.overlay.variant === 'ruler' ? <TimeRuler {...p}/> : <TimelineOverlay {...p}/>,
  highlight: HighlightOverlay,
  "lower-third": (p) => PERSON_TAGS.has(p.overlay.variant || "") ? <PersonTag {...p}/> : <LowerThird {...p}/>,
  arrow: (p) => p.overlay.anchor ? <ObjectCallout {...p}/> : <ArrowOverlay {...p}/>,
  "sentence-highlight": SentenceHighlight,
  "article-zoom": ArticleZoom,
  "date-stamp": DateStamp,
  "photo-card": PhotoCard,
  "name-card": NameCard,
  "stat-tag": StatTag,
  "label-boxes": LabelBoxes,
  "ring-stat": RingStat,
  bullets: Bullets,
  "swoosh-title": SwooshTitle,
  kicker: Kicker,
  "memo-box": MemoBox,
  "word-type": WordType,
  "underline-title": UnderlineTitle,
  "bar-title": BarTitle,
  "age-tag": AgeTag,
  "clock-badge": ClockBadge,
  "red-strip": RedStrip,
  "line-chart": LineChart,
  "path-steps": PathSteps,
  "progress-steps": ProgressSteps,
  span: Span,
  "icon-pop": IconPop,
  donut: Donut,
  "area-chart": AreaChart,
  "progress-bar": ProgressBar,
  "icon-array": IconArray,
  ranking: Ranking,
  counter: Counter,
  "number-roll": NumberRoll,
  trend: Trend,
  "year-roll": YearRoll,
  banner: Banner,
  "scale-compare": ScaleCompare,
  // Split takes its two media entries rather than a text payload, so it gets
  // a small adapter instead of the shared signature.
  split: ({ overlay, accent }) =>
    overlay.media && overlay.media.length >= 2 ? (
      <SplitScreen top={overlay.media[0]} bottom={overlay.media[1]} accent={accent} />
    ) : null,
};

/** The accent an overlay draws with: its theme colour, else the brand accent. */
export const accentFor = (ov: Overlay, accent: string): string => THEMES[ov.theme || ""] || accent;
