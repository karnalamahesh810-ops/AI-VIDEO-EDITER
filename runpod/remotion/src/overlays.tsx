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
import { IconPop, PathSteps, ProgressSteps, Span } from "./components/DataGraphics";
import { Banner, IconArray, ProgressBar, YearRoll } from "./components/MotionGraphics";
import { SatelliteMap, SpreadMap } from "./components/MapLooks";
import { ProBars, ProCompare, ProDate, ProStat, ProTimeline, ProTitle, ProTrend } from "./components/pro/ProGraphics";
import { ProPhoto } from "./components/pro/ProPhoto";
import { ProKicker, ProLabels, ProList } from "./components/pro/ProTags";
import { ProSplit } from "./components/pro/ProSplit";
import { ProChapter, ProHeadline, ProHighlight, ProQuote, ProWarning } from "./components/pro/ProText";
import { ProBubbles, ProColumns, ProDelta, ProLine, ProMeasure, ProPie, ProRank, ProRatio, ProShares, ProSpark, ProStack,
  ProTank, ProVersus } from "./components/pro/ProCharts";
import { ProBoard, ProCallout, ProClipping, ProEvidence, ProFile, ProSourceTag, ProWindows } from "./components/pro/ProCase";
import { LIBRARY } from "./components/lib";
import type { Overlay, OverlayType } from "./types";

/** Colour themes an overlay can ask for instead of the brand accent. */
export const THEMES: Record<string, string> = {
  gold: "#d6a83c", red: "#e63946", teal: "#2ec4b6", blue: "#2f80ed", white: "#f4f1ea", amber: "#f4a100",
};

const PERSON_TAGS = new Set(["tag", "line", "serif", "chyron"]);

export type OverlayComponent = React.FC<{ overlay: Overlay; accent: string }>;

/** Number looks by variant (ProCharts), and comparison looks by variant. */
const STAT_LOOKS: Record<string, OverlayComponent> = {
  tank: ProTank, pie: ProPie, spark: ProSpark, stack: ProStack, measure: ProMeasure, ratio: ProRatio,
};
const COMPARE_LOOKS: Record<string, OverlayComponent> = {
  versus: ProVersus, delta: ProDelta, columns: ProColumns, bubbles: ProBubbles,
};

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
  chapter: ProChapter,
  callout: CalloutOverlay,
  typewriter: ProTitle,
  stat: (p) => {
    // More number looks (ProCharts): the variant picks the drawing.
    const Look = STAT_LOOKS[p.overlay.variant || ""];
    return Look ? <Look {...p} /> : <ProStat {...p} />;
  },
  "bar-chart": (p) => {
    const v = p.overlay.variant || "";
    if (v === "shares" || v === "pie") return <ProShares {...p} />;
    if (v === "rank") return <ProRank {...p} />;
    return <ProBars {...p} />;
  },
  comparison: (p) => {
    const Look = COMPARE_LOOKS[p.overlay.variant || ""];
    return Look ? <Look {...p} /> : <ProCompare {...p} />;
  },
  map: (p) => {
    const v = p.overlay.variant || "";
    if (v.startsWith("satellite")) return <SatelliteMap {...p}/>;
    if (v.startsWith("spread")) return <SpreadMap {...p}/>;
    return v ? <DocumentaryMap {...p}/> : <MapOverlay {...p}/>;
  },
  quote: (p) => (p.overlay.variant === "audio" ? <ProWindows {...p} />
    : p.overlay.variant === "callout" ? <ProCallout {...p} /> : <ProQuote {...p} />),
  timeline: (p) => p.overlay.variant === 'ruler' ? <TimeRuler {...p}/> : <ProTimeline {...p}/>,
  highlight: HighlightOverlay,
  "lower-third": (p) => PERSON_TAGS.has(p.overlay.variant || "") ? <PersonTag {...p}/> : <LowerThird {...p}/>,
  arrow: (p) => p.overlay.anchor ? <ObjectCallout {...p}/> : <ArrowOverlay {...p}/>,
  "sentence-highlight": ProHighlight,
  "article-zoom": (p) => (p.overlay.variant === "clipping" ? <ProClipping {...p} />
    : p.overlay.variant === "doc" ? <ProWindows {...p} /> : <ArticleZoom {...p} />),
  "date-stamp": (p) => p.overlay.variant === "title" ? <ProDate {...p} /> : <DateStamp {...p} />,
  "photo-card": (p) => {
    // Case-file looks (ProCase): windows on the desk, the paper board.
    const v = p.overlay.variant || "";
    if (v === "window" || v === "pip" || v === "collage") {
      return <ProWindows {...p} overlay={{ ...p.overlay, variant: v === "window" ? "photo" : v }} />;
    }
    if (v === "board") return <ProBoard {...p} />;
    if (v === "evidence") return <ProEvidence {...p} />;
    return <ProPhoto {...p} />;
  },
  "name-card": (p) => <ProPhoto {...p} variant="person" />,
  "stat-tag": StatTag,
  "label-boxes": ProLabels,
  "ring-stat": (p) => <ProStat {...p} variant="ring" />,
  bullets: (p) => (p.overlay.variant === "facts" || p.overlay.variant === "dossier" ? <ProFile {...p} /> : <ProList {...p} />),
  "swoosh-title": (p) => <ProHeadline {...p} variant="underline" />,
  kicker: (p) => (p.overlay.variant === "source" ? <ProSourceTag {...p} /> : <ProKicker {...p} />),
  "memo-box": MemoBox,
  "word-type": (p) => <ProHeadline {...p} variant="center" />,
  "underline-title": (p) => <ProHeadline {...p} variant="underline" />,
  "bar-title": BarTitle,
  "age-tag": AgeTag,
  "clock-badge": ClockBadge,
  "red-strip": ProWarning,
  "line-chart": (p) => <ProLine {...p} />,
  "path-steps": PathSteps,
  "progress-steps": ProgressSteps,
  span: Span,
  "icon-pop": IconPop,
  donut: (p) => <ProStat {...p} variant="ring" />,
  "area-chart": (p) => <ProLine {...p} overlay={{ ...p.overlay, variant: "area" }} />,
  "progress-bar": ProgressBar,
  "icon-array": (p) => (p.overlay.total || (p.overlay.suffix || "").trim() === "%" ? <ProRatio {...p} /> : <IconArray {...p} />),
  ranking: (p) => <ProRank {...p} />,
  counter: (p) => ((p.overlay.items || []).filter((i) => typeof i.value === "number").length >= 2
    ? <ProCompare {...p} /> : <ProStat {...p} variant="roll" />),
  "number-roll": (p) => <ProStat {...p} variant="roll" />,
  trend: ProTrend,
  "year-roll": YearRoll,
  banner: Banner,
  "scale-compare": (p) => <ProBubbles {...p} />,
  // Split takes its two media entries rather than a text payload, so it gets
  // a small adapter instead of the shared signature.
  // Two pictures side by side with a divider (a contrast told with images).
  split: ProSplit,
  // The animation library: one look per variant (components/lib/index.ts).
  motion: (p) => {
    const Look = LIBRARY[p.overlay.variant || ""];
    return Look ? <Look {...p} /> : null;
  },
};

/** The accent an overlay draws with: its theme colour, else the brand accent. */
export const accentFor = (ov: Overlay, accent: string): string => THEMES[ov.theme || ""] || accent;
