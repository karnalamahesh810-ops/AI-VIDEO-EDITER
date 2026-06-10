import React from "react";

import { ArchivalPhoto } from "./components/ArchivalPhoto";
import { AreaChart } from "./components/AreaChart";
import { ArrowCallout } from "./components/ArrowCallout";
import { BarChart } from "./components/BarChart";
import { BarGauge } from "./components/BarGauge";
import { BigNumber } from "./components/BigNumber";
import { BlueprintScroll } from "./components/BlueprintScroll";
import { ComparisonTable } from "./components/ComparisonTable";
import { CountdownList } from "./components/CountdownList";
import { DateStamp } from "./components/DateStamp";
import { DocumentCard } from "./components/DocumentCard";
import { DonutStat } from "./components/DonutStat";
import { GhostKeyword } from "./components/GhostKeyword";
import { GradeOverlay } from "./components/GradeOverlay";
import { GrungeTab } from "./components/GrungeTab";
import { HBarCompare } from "./components/HBarCompare";
import { HighlightCaption } from "./components/HighlightCaption";
import { HighlighterQuote } from "./components/HighlighterQuote";
import { HookCaption } from "./components/HookCaption";
import { KineticTitle } from "./components/KineticTitle";
import { LineChart } from "./components/LineChart";
import { LogoTiles } from "./components/LogoTiles";
import { LowerThirdName } from "./components/LowerThirdName";
import { LowerThirdTitle } from "./components/LowerThirdTitle";
import { MapHighlight } from "./components/MapHighlight";
import { MigrationMap } from "./components/MigrationMap";
import { NewspaperClipping } from "./components/NewspaperClipping";
import { NodeIntro } from "./components/NodeIntro";
import { PhotoCarousel } from "./components/PhotoCarousel";
import { PieBreakdown } from "./components/PieBreakdown";
import { PillChyron } from "./components/PillChyron";
import { PolaroidFrame } from "./components/PolaroidFrame";
import { PortraitFrame } from "./components/PortraitFrame";
import { ProcessSteps } from "./components/ProcessSteps";
import { PullQuote } from "./components/PullQuote";
import { RouteMap } from "./components/RouteMap";
import { SectionTitle } from "./components/SectionTitle";
import { SpotlightCallout } from "./components/SpotlightCallout";
import { SplitScreen } from "./components/SplitScreen";
import { StatCard } from "./components/StatCard";
import { StatChip } from "./components/StatChip";
import { StockCrashChart } from "./components/StockCrashChart";
import { Timeline } from "./components/Timeline";
import { TweetCard } from "./components/TweetCard";

export const REGISTRY: Record<string, React.ComponentType<any>> = {
  ArchivalPhoto,
  AreaChart,
  ArrowCallout,
  BarChart,
  BarGauge,
  BigNumber,
  BlueprintScroll,
  ComparisonTable,
  CountdownList,
  DateStamp,
  DocumentCard,
  DonutStat,
  GhostKeyword,
  GradeOverlay,
  GrungeTab,
  HBarCompare,
  HighlightCaption,
  HighlighterQuote,
  HookCaption,
  KineticTitle,
  LineChart,
  LogoTiles,
  LowerThirdName,
  LowerThirdTitle,
  MapHighlight,
  MigrationMap,
  NewspaperClipping,
  NodeIntro,
  PhotoCarousel,
  PieBreakdown,
  PillChyron,
  PolaroidFrame,
  PortraitFrame,
  ProcessSteps,
  PullQuote,
  RouteMap,
  SectionTitle,
  SpotlightCallout,
  SplitScreen,
  StatCard,
  StatChip,
  StockCrashChart,
  Timeline,
  TweetCard,
};

export type RegistryName = keyof typeof REGISTRY;

export const REGISTRY_NAMES: string[] = Object.keys(REGISTRY);
