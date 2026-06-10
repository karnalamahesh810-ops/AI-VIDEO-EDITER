import React from "react";
import { AbsoluteFill, Sequence, Img, staticFile } from "remotion";
import { getTheme } from "./theme";
import { LowerThirdTitle } from "./components/LowerThirdTitle";
import { KineticTitle } from "./components/KineticTitle";
import { DateStamp } from "./components/DateStamp";
import { BigNumber } from "./components/BigNumber";
import { StatChip } from "./components/StatChip";
import { StatCard } from "./components/StatCard";
import { PillChyron } from "./components/PillChyron";
import { GrungeTab } from "./components/GrungeTab";
import { PullQuote } from "./components/PullQuote";
import { HighlightCaption } from "./components/HighlightCaption";
import { LineChart } from "./components/LineChart";
import { BarChart } from "./components/BarChart";
import { RouteMap } from "./components/RouteMap";
import { MapHighlight } from "./components/MapHighlight";
import { BarGauge } from "./components/BarGauge";
import { Timeline } from "./components/Timeline";
import { TweetCard } from "./components/TweetCard";
import { PolaroidFrame } from "./components/PolaroidFrame";
import { PortraitFrame } from "./components/PortraitFrame";
import { PhotoCarousel } from "./components/PhotoCarousel";
import { NodeIntro } from "./components/NodeIntro";
import { BlueprintScroll } from "./components/BlueprintScroll";
import { HighlighterQuote } from "./components/HighlighterQuote";
import { LogoTiles } from "./components/LogoTiles";
import { SectionTitle } from "./components/SectionTitle";
import { HookCaption } from "./components/HookCaption";
import { GhostKeyword } from "./components/GhostKeyword";
import { ArchivalPhoto } from "./components/ArchivalPhoto";
import { StockCrashChart } from "./components/StockCrashChart";
import { DocumentCard } from "./components/DocumentCard";
import { MigrationMap } from "./components/MigrationMap";
import { NewspaperClipping } from "./components/NewspaperClipping";
import { SplitScreen } from "./components/SplitScreen";
import { HBarCompare } from "./components/HBarCompare";
import { DonutStat } from "./components/DonutStat";
import { GradeOverlay } from "./components/GradeOverlay";
import { CountdownList } from "./components/CountdownList";
import { ComparisonTable } from "./components/ComparisonTable";
import { PieBreakdown } from "./components/PieBreakdown";
import { AreaChart } from "./components/AreaChart";
import { ProcessSteps } from "./components/ProcessSteps";
import { SpotlightCallout } from "./components/SpotlightCallout";
import { ArrowCallout } from "./components/ArrowCallout";
import { LowerThirdName } from "./components/LowerThirdName";

// Kitchen-sink reel: every template animation (derived from the reference videos)
// with sample data, so the full look can be reviewed live in Studio. SEG = frames/element.
const SEG = 84;
const th = getTheme("business");

const Bg: React.FC<{ clip: string }> = ({ clip }) => (
  <AbsoluteFill style={{ backgroundColor: "#000" }}>
    <Img src={staticFile(`broll/posters/${clip.replace(/\.mp4$/, ".jpg")}`)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
    <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(0,0,0,.12), rgba(0,0,0,.5))" }} />
  </AbsoluteFill>
);

type Seg = { bg?: string; node: React.ReactNode };
const segs: Seg[] = [
  // --- core 14 ---
  { bg: "scene_06.mp4", node: <KineticTitle lines={["THE FACELESS", "DOC TEMPLATE"]} theme={th} durationInFrames={SEG} /> },
  { bg: "scene_07.mp4", node: <LowerThirdTitle lines={["Wilson Seeks Partnership with Starbucks"]} theme={th} durationInFrames={SEG} /> },
  { bg: "scene_07.mp4", node: <DateStamp day="November 4th" year="2025" pos="bl" typed theme={th} durationInFrames={SEG} /> },
  { bg: "scene_03.mp4", node: <BigNumber value={17000} prefix="$" countup scrim label="IN ANNUAL DAMAGE" theme={th} durationInFrames={SEG} /> },
  { bg: "scene_09.mp4", node: <StatChip value={44} suffix="%" countup label="CONSIDERING A MOVE" theme={th} durationInFrames={SEG} /> },
  { bg: "scene_06.mp4", node: <StatCard title="BOEING IN WASHINGTON (1989)" bullets={["105,000 jobs statewide", "1,540 supplier companies", "$56.8B in annual sales", "~5% of state economy"]} side="right" torn theme={th} durationInFrames={SEG} /> },
  { bg: "scene_07.mp4", node: <PillChyron value="2,000" label="JOBS TO NASHVILLE" theme={th} durationInFrames={SEG} /> },
  { bg: "scene_03.mp4", node: <GrungeTab value={346} label="DEATHS" theme={th} durationInFrames={SEG} /> },
  { node: <PullQuote quote="This really sets us up for our next leg of growth." cite="— Brian Niccol, CEO, Starbucks" bg="black" typed theme={th} durationInFrames={SEG} /> },
  { bg: "scene_07.mp4", node: <HighlightCaption lines={[{ text: "They told you the flies came" }, { text: "from outside.", highlight: true }, { text: "They didn't." }]} theme={th} durationInFrames={SEG} /> },
  { node: <LineChart title="Employees — 1989 to 1996" series={[{ points: [120, 112, 98, 86, 79, 74, 72] }]} xLabels={["'89", "'90", "'91", "'92", "'93", "'94", "'95"]} yLabel="Employees (K)" xLabel="Year" fullBg theme={th} durationInFrames={SEG} /> },
  { node: <BarChart title="Seattle — Combined Tax Rate" bars={[{ label: "Sales", value: 10.25 }, { label: "B&O", value: 1.5 }, { label: "Payroll", value: 2.6 }, { label: "Other", value: 9.9, spotlight: true }]} yLabel="Rate (%)" valueFmt={{ suffix: "%" }} fullBg theme={th} durationInFrames={SEG} /> },
  { node: <RouteMap from={{ x: 0.2, y: 0.42, label: "Chicago HQ" }} to={{ x: 0.74, y: 0.56, label: "Arlington, VA" }} theme={th} durationInFrames={SEG} /> },
  { node: <MapHighlight target={{ x: 0.5, y: 0.46, r: 120 }} label="Starbucks Seattle HQ" theme={th} durationInFrames={SEG} /> },
  // --- wave 2 (10 more) ---
  { bg: "scene_07.mp4", node: <Timeline ticks={["Nov '23", "Feb '24", "May '24", "Nov '24", "Feb '25"]} activeIndex={3} label="Nov 2024" theme={th} durationInFrames={SEG} /> },
  { node: <BarGauge value={31} suffix="%" label="AEROSPACE" footnote="All manufacturing = 100%  ·  Aerospace = 31%" fullBg theme={th} durationInFrames={SEG} /> },
  { node: <TweetCard handle="@SBWorkersUnited" time="Oct 18, 2023 · 9:13" body="The company's demands had been unreasonable from the very start." avatarLetter="S" bgColor="#8186C4" theme={th} durationInFrames={SEG} /> },
  { node: <PolaroidFrame caption="Seattle, 1971 — the bust years" rotate={-3} theme={th} durationInFrames={SEG} /> },
  { bg: "scene_07.mp4", node: <PortraitFrame side="right" label="Amos Stoltzfus" theme={th} durationInFrames={SEG} /> },
  { node: <PhotoCarousel items={[{ label: "Boeing HQ" }, { label: "Seattle Skyline" }]} number={4} fullBg theme={th} durationInFrames={SEG} /> },
  { node: <NodeIntro nodes={[{ label: "Layer 1", x: 0.22, y: 0.36 }, { label: "Grid", x: 0.5, y: 0.56 }, { label: "Suitcase", x: 0.78, y: 0.36 }]} links={[[0, 1], [1, 2]]} theme={th} durationInFrames={SEG} /> },
  { node: <BlueprintScroll caption="Boeing 777 — schematic" theme={th} durationInFrames={SEG} /> },
  { node: <HighlighterQuote paragraph="Boeing's exit triggered massive job cuts that rippled across the region for years." highlightPhrase="massive job cuts" photoCaption="Photo: Seattle, 1971 (archival)" theme={th} durationInFrames={SEG} /> },
  { bg: "scene_06.mp4", node: <LogoTiles tiles={[{ label: "Hiring Engine", color: "#0078D4" }, { label: "Left Behind", color: "#E8202B" }]} theme={th} durationInFrames={SEG} /> },
  // --- best extras (6 more) ---
  { bg: "scene_06.mp4", node: <SectionTitle headline="INTERCEPTOR TRAPS" subtitle="Layer 3 — Detection" align="left" theme={th} durationInFrames={SEG} /> },
  { bg: "scene_07.mp4", node: <HookCaption lines={["The company that gave Seattle", "its nickname — JET CITY — is leaving."]} keyword="jet city" theme={th} durationInFrames={SEG} /> },
  { bg: "scene_03.mp4", node: <GhostKeyword text="UNDERCOVER" theme={th} durationInFrames={SEG} /> },
  { node: <ArchivalPhoto caption="Boeing's postwar leap into jets — 1954" bw full theme={th} durationInFrames={SEG} /> },
  { node: <StockCrashChart title="STARBUCKS — MARKET REACTION" fullBg theme={th} durationInFrames={SEG} /> },
  { node: <DocumentCard title="Executive Compensation" rows={[{ label: "Base salary", value: "$1.3M" }, { label: "Stock awards", value: "$39.6M" }, { label: "Total, 2023", value: "$14.7M" }]} highlightRow={1} source="Source: SEC filing (2023)" theme={th} durationInFrames={SEG} /> },
  // --- batch 3 (6 more) ---
  { node: <MigrationMap arrows={[{ fromX: 0.34, fromY: 0.5, toX: 0.66, toY: 0.46 }, { fromX: 0.3, fromY: 0.58, toX: 0.72, toY: 0.62 }]} label="OPERATIONS RELOCATING SOUTH" fullBg theme={th} durationInFrames={SEG} /> },
  { node: <NewspaperClipping headline="BOEING TO LEAVE SEATTLE" dek="110 years of history comes to an end" source="The Seattle Times, 2022" circle theme={th} durationInFrames={SEG} /> },
  { node: <SplitScreen left={{ src: "broll/posters/scene_06.jpg", label: "1989" }} right={{ src: "broll/posters/scene_07.jpg", label: "2024" }} divider theme={th} durationInFrames={SEG} /> },
  { node: <HBarCompare title="Jobs by Sector (thousands)" bars={[{ label: "Aerospace", value: 65, spotlight: true }, { label: "Tech", value: 48 }, { label: "Retail", value: 30 }]} valueFmt={{ suffix: "K" }} fullBg theme={th} durationInFrames={SEG} /> },
  { node: <DonutStat value={80} suffix="%" label="of aerospace jobs" fullBg theme={th} durationInFrames={SEG} /> },
  { bg: "scene_06.mp4", node: (<><GradeOverlay vignette={0.55} grain={0.12} theme={th} durationInFrames={SEG} /><LowerThirdTitle lines={["Cinematic grade + film grain"]} theme={th} durationInFrames={SEG} /></>) },
  // --- batch 4 (8 more) ---
  { bg: "scene_07.mp4", node: <CountdownList title="TOP RELOCATIONS" items={[{ rank: 3, label: "Chicago HQ", value: "2001" }, { rank: 2, label: "787 line → SC", value: "2009" }, { rank: 1, label: "HQ → Arlington", value: "2022" }]} theme={th} durationInFrames={SEG} /> },
  { node: <ComparisonTable leftTitle="Store-bought" rightTitle="Grandma's way" rows={[{ label: "Cost", left: "$12", right: "9¢" }, { label: "Toxic", left: true, right: false }, { label: "Reusable", left: false, right: true }]} fullBg theme={th} durationInFrames={SEG} /> },
  { node: <PieBreakdown title="WHERE FLIES BREED" slices={[{ label: "Trash can", value: 35 }, { label: "Sink drain", value: 25 }, { label: "Compost", value: 20 }, { label: "Other", value: 20 }]} fullBg theme={th} durationInFrames={SEG} /> },
  { node: <AreaChart title="Fly complaints over summer" points={[10, 18, 30, 52, 70, 64, 48]} xLabels={["May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov"]} yLabel="Reports" fullBg theme={th} durationInFrames={SEG} /> },
  { bg: "scene_06.mp4", node: <ProcessSteps steps={[{ label: "Saucer", sub: "+ sugar" }, { label: "Jar trap", sub: "catch" }, { label: "Wipe down", sub: "daily" }]} theme={th} durationInFrames={SEG} /> },
  { bg: "scene_06.mp4", node: <SpotlightCallout x={0.5} y={0.45} r={170} label="The forgotten corner" shape="circle" theme={th} durationInFrames={SEG} /> },
  { bg: "scene_03.mp4", node: <ArrowCallout fromX={0.24} fromY={0.28} toX={0.58} toY={0.55} label="Fly on the rim" theme={th} durationInFrames={SEG} /> },
  { bg: "scene_07.mp4", node: <LowerThirdName name="Amos Stoltzfus" title="Amish farmer · Lancaster County, PA" theme={th} durationInFrames={SEG} /> },
];

export const TEMPLATE_DEMO_FRAMES = segs.length * SEG;

export const TemplateDemo: React.FC = () => {
  return (
    <AbsoluteFill style={{ backgroundColor: th.bg }}>
      {segs.map((s, i) => (
        <Sequence key={i} from={i * SEG} durationInFrames={SEG} layout="none">
          {s.bg ? (
            <Bg clip={s.bg} />
          ) : (
            <AbsoluteFill style={{ background: `radial-gradient(1200px 700px at 50% 40%, ${th.panel}, ${th.bg})` }} />
          )}
          {s.node}
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
