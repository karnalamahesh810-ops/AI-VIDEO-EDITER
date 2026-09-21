import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import { geoGraticule10, geoMercator, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import topology from "world-atlas/countries-110m.json";
import {
  PANEL_BG, PANEL_SHADOW, SANS, growth, useOverlayAnim,
  useOverlaySafeStyle, useScale,
} from "./layout";
import type { MapLocation, Overlay } from "../types";

/**
 * Locator map: real country geometry, zooming from continental scale down to
 * the place being named.
 *
 * The geometry is Natural Earth's 110m countries, bundled with the renderer
 * rather than fetched — a render must not depend on a CDN being up. Every
 * coordinate reaching this component was resolved by geocode.py against
 * OpenStreetMap, and the label drawn is the gazetteer's own name for that
 * point, so the pin and its caption cannot contradict each other.
 *
 * Mercator is the right projection here despite its area distortion: these
 * are local "where did this happen" maps, and at city zoom Mercator is
 * conformal, so coastlines look like themselves.
 */

// topojson -> geojson once at module load, not per frame.
const WORLD = feature(
  topology as never,
  (topology as never as { objects: { countries: never } }).objects.countries
) as unknown as { features: unknown[] };

const GRATICULE = geoGraticule10();

export const MapOverlay: React.FC<{ overlay: Overlay; accent: string }> = ({
  overlay,
  accent,
}) => {
  const { frame, enter, opacity, durationInFrames } = useOverlayAnim(20, 12);
  const s = useScale();
  const safe = useOverlaySafeStyle();

  const locations = (overlay.locations || []).filter(
    (l): l is MapLocation =>
      Number.isFinite(l?.lat) && Number.isFinite(l?.lon) && !!l?.label
  );
  if (locations.length === 0) return null;

  const boxW = s(900);
  const boxH = s(520);

  // Centre on the mean of the pins so several places stay in frame together.
  const centre: [number, number] = [
    locations.reduce((a, l) => a + l.lon, 0) / locations.length,
    locations.reduce((a, l) => a + l.lat, 0) / locations.length,
  ];

  // Push in over the first 60% of the clip, then hold so the viewer can read
  // it. `base` is the scale at which the whole world spans the box width.
  const base = boxW / (2 * Math.PI);
  const zoom = interpolate(growth(frame, Math.floor(durationInFrames * 0.6)), [0, 1], [2.2, 9]);

  const projection = geoMercator()
    .center(centre)
    .scale(base * zoom)
    .translate([boxW / 2, boxH / 2]);
  const draw = geoPath(projection);

  const pinDrop = growth(frame - Math.floor(durationInFrames * 0.35), 14);
  // 0 -> 1 repeatedly: a radar ring leaving the pin.
  const pulse = (frame % 40) / 40;

  return (
    <AbsoluteFill
      style={{
        ...safe,
        justifyContent: "center",
        alignItems: "center",
        opacity,
        transform: `scale(${interpolate(enter, [0, 1], [0.95, 1])})`,
      }}
    >
      <div
        style={{
          background: PANEL_BG,
          borderRadius: s(20),
          padding: s(20),
          boxShadow: PANEL_SHADOW,
          backdropFilter: "blur(10px)",
        }}
      >
        <svg width={boxW} height={boxH} style={{ display: "block", borderRadius: s(12) }}>
          <defs>
            <clipPath id="map-clip">
              <rect x={0} y={0} width={boxW} height={boxH} rx={s(12)} />
            </clipPath>
          </defs>
          <g clipPath="url(#map-clip)">
            <rect x={0} y={0} width={boxW} height={boxH} fill="#0d1117" />
            <path
              d={draw(GRATICULE as never) || undefined}
              fill="none"
              stroke="rgba(255,255,255,0.07)"
              strokeWidth={1}
            />
            {WORLD.features.map((f, i) => (
              <path
                key={i}
                d={draw(f as never) || undefined}
                fill="rgba(255,255,255,0.13)"
                stroke="rgba(255,255,255,0.32)"
                strokeWidth={1}
              />
            ))}

            {locations.map((loc, i) => {
              const xy = projection([loc.lon, loc.lat]);
              if (!xy) return null;
              const [x, y] = xy;
              return (
                <g key={i} opacity={pinDrop}>
                  {/* Radar ring — expands and fades, then repeats. */}
                  <circle
                    cx={x}
                    cy={y}
                    r={s(10) + pulse * s(58)}
                    fill="none"
                    stroke={accent}
                    strokeWidth={s(3)}
                    opacity={(1 - pulse) * 0.75 * pinDrop}
                  />
                  <circle cx={x} cy={y} r={s(11)} fill={accent} />
                  <circle cx={x} cy={y} r={s(5)} fill="#0d1117" />
                  <text
                    x={x + s(22)}
                    y={y + s(9)}
                    fill="#fff"
                    fontFamily={SANS}
                    fontSize={s(26)}
                    fontWeight={800}
                    style={{ paintOrder: "stroke", stroke: "#0d1117", strokeWidth: s(6) }}
                  >
                    {loc.label}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>

        {overlay.text ? (
          <div
            style={{
              fontFamily: SANS,
              fontSize: s(32),
              fontWeight: 800,
              color: "#fff",
              marginTop: s(16),
              paddingLeft: s(6),
              letterSpacing: "0.04em",
              textTransform: "uppercase",
            }}
          >
            <span style={{ color: accent, marginRight: s(10) }}>◆</span>
            {overlay.text}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
