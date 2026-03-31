import React, { useMemo } from "react";
import { geoAlbersUsa, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import type { Topology, GeometryCollection } from "topojson-specification";
import { StateData } from "../data/topStates";

// We'll load a minimal TopoJSON inline to avoid file import issues
// This is a simplified US states outline using the Albers USA projection
// coordinate system normalized to a 960x600 viewBox

interface USAMapSVGProps {
  width: number;
  height: number;
  highlightedFips: string | null;
  topStates: StateData[];
  zoomTransform?: { x: number; y: number; scale: number };
  mapOpacity?: number;
  pulseProgress?: number;
}

// Minimal state centroid data (projected Albers USA coords at 960x600)
// These are approximate centroids used for labels only
const STATE_CENTROIDS: Record<string, [number, number]> = {
  "01": [630, 390], "02": [150, 80],  "04": [190, 315], "05": [550, 370],
  "06": [115, 280], "08": [255, 275], "09": [810, 195], "10": [790, 215],
  "12": [680, 440], "13": [680, 385], "15": [180, 425], "16": [205, 205],
  "17": [575, 255], "18": [620, 265], "19": [510, 220], "20": [480, 310],
  "21": [650, 310], "22": [565, 420], "23": [855, 130], "24": [775, 230],
  "25": [820, 175], "26": [630, 185], "27": [510, 145], "28": [590, 390],
  "29": [545, 300], "30": [245, 165], "31": [455, 240], "32": [170, 255],
  "33": [830, 155], "34": [795, 210], "35": [265, 345], "36": [780, 185],
  "37": [710, 340], "38": [430, 155], "39": [680, 255], "40": [485, 360],
  "41": [130, 180], "42": [750, 210], "44": [825, 185], "45": [715, 365],
  "46": [425, 195], "47": [645, 340], "48": [450, 410], "49": [220, 265],
  "50": [815, 155], "51": [745, 265], "53": [140, 145], "54": [710, 270],
  "55": [570, 185], "56": [285, 220],
};

export const USAMapSVG: React.FC<USAMapSVGProps> = ({
  width,
  height,
  highlightedFips,
  topStates,
  zoomTransform,
  mapOpacity = 1,
  pulseProgress = 0,
}) => {
  // We'll use a hardcoded simplified SVG representation of the USA
  // with state outlines. Using simplified rectangles/polygons as placeholders
  // that form a recognizable USA map shape.

  const projection = useMemo(() => {
    return geoAlbersUsa()
      .scale(1300)
      .translate([width * 0.5, height * 0.5]);
  }, [width, height]);

  const pathGenerator = useMemo(() => geoPath().projection(projection), [projection]);

  const topStateFips = useMemo(() => new Set(topStates.map((s) => s.fips)), [topStates]);

  const transform = zoomTransform
    ? `translate(${zoomTransform.x}px, ${zoomTransform.y}px) scale(${zoomTransform.scale})`
    : "none";

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      style={{ opacity: mapOpacity }}
    >
      <defs>
        <filter id="glow-strong">
          <feGaussianBlur stdDeviation="4" result="blur" />
          <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
        <filter id="glow-soft">
          <feGaussianBlur stdDeviation="2" result="blur" />
          <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
        {topStates.map((s) => (
          <radialGradient
            key={s.fips}
            id={`grad-${s.fips}`}
            cx="50%"
            cy="50%"
            r="50%"
          >
            <stop offset="0%" stopColor={s.color} stopOpacity="0.6" />
            <stop offset="100%" stopColor={s.color} stopOpacity="0.15" />
          </radialGradient>
        ))}
      </defs>

      <g style={{ transform, transformOrigin: "center center", transition: "none" }}>
        {/* USA simplified outline using path data */}
        <USAStatesGroup
          projection={projection}
          pathGenerator={pathGenerator}
          topStates={topStates}
          highlightedFips={highlightedFips}
          pulseProgress={pulseProgress}
          width={width}
          height={height}
        />
      </g>
    </svg>
  );
};

// Internal component that renders simplified state-like regions
const USAStatesGroup: React.FC<{
  projection: ReturnType<typeof geoAlbersUsa>;
  pathGenerator: ReturnType<typeof geoPath>;
  topStates: StateData[];
  highlightedFips: string | null;
  pulseProgress: number;
  width: number;
  height: number;
}> = ({ projection, topStates, highlightedFips, pulseProgress, width, height }) => {
  // Scale factor for centroids (STATE_CENTROIDS are for 960x600 base)
  const sx = width / 960;
  const sy = height / 600;

  // Approximate state bounding regions using polygons
  // These define simplified shapes for each state
  const stateShapes = useSimplifiedStates(sx, sy);

  const topStateMap = useMemo(() => {
    const map: Record<string, StateData> = {};
    topStates.forEach((s) => { map[s.fips] = s; });
    return map;
  }, [topStates]);

  return (
    <g>
      {/* Ocean/background gradient */}
      <rect
        x={0}
        y={0}
        width={width}
        height={height}
        fill="transparent"
      />

      {/* State shapes */}
      {stateShapes.map(({ fips, path, labelX, labelY, abbr }) => {
        const isTop = fips in topStateMap;
        const isHighlighted = fips === highlightedFips;
        const stateData = topStateMap[fips];

        const baseColor = isHighlighted
          ? stateData?.color
          : isTop
          ? `${stateData?.color}88`
          : "rgba(255,255,255,0.06)";

        const strokeColor = isHighlighted
          ? stateData?.color
          : isTop
          ? `${stateData?.color}cc`
          : "rgba(255,255,255,0.15)";

        const strokeWidth = isHighlighted ? 2.5 : isTop ? 1.5 : 0.8;

        const pulseScale = isHighlighted
          ? 1 + Math.sin(pulseProgress * Math.PI * 2) * 0.02
          : 1;

        return (
          <g key={fips}>
            <path
              d={path}
              fill={isHighlighted ? `url(#grad-${fips})` : baseColor}
              stroke={strokeColor}
              strokeWidth={strokeWidth}
              style={{
                filter: isHighlighted
                  ? `drop-shadow(0 0 12px ${stateData?.color})`
                  : isTop
                  ? `drop-shadow(0 0 6px ${stateData?.color}80)`
                  : "none",
                transform: isHighlighted
                  ? `scale(${pulseScale})`
                  : "none",
                transformOrigin: `${labelX}px ${labelY}px`,
              }}
            />

            {/* Rank badge for top states */}
            {isTop && !isHighlighted && (
              <g transform={`translate(${labelX}, ${labelY})`}>
                <circle
                  r={12}
                  fill={stateData.color}
                  opacity={0.9}
                  style={{ filter: `drop-shadow(0 0 4px ${stateData.color})` }}
                />
                <text
                  textAnchor="middle"
                  dominantBaseline="central"
                  fontSize={10}
                  fontWeight="bold"
                  fill="#1a1a2e"
                  fontFamily="sans-serif"
                >
                  #{stateData.rank}
                </text>
              </g>
            )}

            {/* Highlighted state label */}
            {isHighlighted && (
              <g transform={`translate(${labelX}, ${labelY})`}>
                <circle
                  r={20}
                  fill={stateData.color}
                  opacity={0.95}
                  style={{
                    filter: `drop-shadow(0 0 12px ${stateData.color})`,
                  }}
                />
                <text
                  textAnchor="middle"
                  dominantBaseline="central"
                  fontSize={12}
                  fontWeight="bold"
                  fill="#1a1a2e"
                  fontFamily="sans-serif"
                >
                  {stateData.abbreviation}
                </text>
              </g>
            )}
          </g>
        );
      })}
    </g>
  );
};

// Simplified polygon paths for all US states
function useSimplifiedStates(sx: number, sy: number) {
  return useMemo(() => {
    // Define simplified state polygons (x, y coordinates in 960x600 space)
    // Each entry: [fips, [[x,y], ...], abbr]
    const rawStates: Array<[string, Array<[number, number]>, string]> = [
      // Continental states with simplified polygons
      ["01", [[575,355],[685,355],[695,410],[680,440],[610,445],[580,400]], "AL"],
      ["04", [[130,295],[255,300],[260,340],[250,390],[150,390],[115,345]], "AZ"],
      ["05", [[505,335],[590,330],[600,375],[555,385],[510,385]], "AR"],
      ["06", [[70,200],[150,185],[175,250],[160,340],[105,385],[65,355],[50,290]], "CA"],
      ["08", [[215,245],[310,245],[315,310],[315,335],[220,335],[215,280]], "CO"],
      ["09", [[795,185],[840,185],[845,205],[795,208]], "CT"],
      ["10", [[780,210],[800,210],[800,230],[775,232]], "DE"],
      ["12", [[640,405],[720,405],[750,430],[740,480],[680,490],[640,460]], "FL"],
      ["13", [[645,360],[720,355],[730,400],[710,420],[645,415]], "GA"],
      ["16", [[155,175],[240,175],[250,230],[205,235],[150,230]], "ID"],
      ["17", [[545,235],[605,230],[610,285],[545,288]], "IL"],
      ["18", [[600,240],[650,238],[655,280],[600,282]], "IN"],
      ["19", [[470,205],[545,205],[548,255],[470,258]], "IA"],
      ["20", [[420,280],[505,280],[508,325],[420,325]], "KS"],
      ["21", [[605,295],[680,290],[685,335],[610,338]], "KY"],
      ["22", [[510,390],[580,388],[590,425],[525,435],[510,415]], "LA"],
      ["23", [[800,115],[865,118],[870,168],[800,165]], "ME"],
      ["24", [[745,220],[790,215],[795,245],[745,248]], "MD"],
      ["25", [[790,165],[845,163],[848,188],[790,190]], "MA"],
      ["26", [[600,155],[660,155],[665,210],[600,215]], "MI"],
      ["27", [[455,120],[545,118],[550,185],[460,188]], "MN"],
      ["28", [[560,365],[630,362],[635,408],[560,412]], "MS"],
      ["29", [[505,285],[580,282],[585,335],[505,338]], "MO"],
      ["30", [[200,140],[320,138],[325,210],[200,215]], "MT"],
      ["31", [[415,225],[495,222],[498,272],[415,275]], "NE"],
      ["32", [[130,215],[210,212],[215,295],[130,298]], "NV"],
      ["33", [[820,148],[858,146],[860,170],[820,172]], "NH"],
      ["34", [[775,195],[810,193],[812,225],[773,228]], "NJ"],
      ["35", [[225,305],[310,302],[315,385],[225,388]], "NM"],
      ["36", [[715,168],[800,165],[805,215],[715,218]], "NY"],
      ["37", [[680,320],[755,318],[760,360],[680,365]], "NC"],
      ["38", [[390,130],[465,128],[468,175],[390,178]], "ND"],
      ["39", [[645,240],[710,238],[715,278],[645,282]], "OH"],
      ["40", [[430,340],[520,338],[525,385],[430,388]], "OK"],
      ["41", [[80,140],[175,138],[180,190],[80,193]], "OR"],
      ["42", [[708,195],[790,192],[793,230],[708,233]], "PA"],
      ["44", [[815,178],[840,176],[842,196],[815,198]], "RI"],
      ["45", [[685,345],[745,342],[748,382],[685,385]], "SC"],
      ["46", [[385,170],[465,168],[468,215],[385,218]], "SD"],
      ["47", [[605,315],[680,312],[685,355],[605,358]], "TN"],
      ["48", [[335,340],[555,338],[560,420],[455,445],[335,415]], "TX"],
      ["49", [[215,245],[315,242],[318,305],[215,308]], "UT"],
      ["50", [[800,140],[830,138],[832,162],[800,163]], "VT"],
      ["51", [[730,255],[785,252],[788,290],[730,293]], "VA"],
      ["53", [[85,100],[180,98],[185,155],[85,158]], "WA"],
      ["54", [[695,255],[740,252],[743,290],[695,293]], "WV"],
      ["55", [[540,168],[605,165],[608,220],[540,223]], "WI"],
      ["56", [[265,185],[365,182],[368,255],[265,258]], "WY"],
      // Alaska (bottom-left inset)
      ["02", [[40,475],[200,472],[215,560],[40,563]], "AK"],
      // Hawaii (bottom inset)
      ["15", [[250,500],[340,498],[345,540],[250,543]], "HI"],
    ];

    return rawStates.map(([fips, pts, abbr]) => {
      const scaledPts = pts.map(([x, y]) => [x * sx, y * sy] as [number, number]);
      const path = pointsToPath(scaledPts);
      const centroid = STATE_CENTROIDS[fips] ?? [480, 300];
      return {
        fips,
        path,
        abbr,
        labelX: centroid[0] * sx,
        labelY: centroid[1] * sy,
      };
    });
  }, [sx, sy]);
}

function pointsToPath(points: Array<[number, number]>): string {
  if (points.length === 0) return "";
  const [first, ...rest] = points;
  return (
    `M ${first[0]} ${first[1]} ` +
    rest.map(([x, y]) => `L ${x} ${y}`).join(" ") +
    " Z"
  );
}
