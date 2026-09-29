import React from 'react';
import {AbsoluteFill, Img, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {geoContains, geoMercator, geoPath} from 'd3-geo';
import {feature} from 'topojson-client';
import topology from 'world-atlas/countries-110m.json';
import statesTopology from '../data/us-states.json';
import type {MapLocation, Overlay} from '../types';
import {INTER, NARROW} from './fonts';

/**
 * Realistic maps. The satellite looks zoom from space onto a verified place
 * through public-domain imagery: USGS orthoimagery inside the US (to street
 * level), NASA Blue Marble elsewhere (to regional level). Variants:
 *   satellite           zoom in, pin, label
 *   satellite-pulse     ... with an alert pulse on the place
 *   satellite-dark      night grade, for dramatic / disaster beats
 *   satellite-tilt      the camera tilts into a 3D angle as it lands
 *   satellite-route     two places, a path drawn between them
 *   satellite-distance  two places, the straight-line distance measured
 *   satellite-inset     zoom with a small locator map in the corner
 *   satellite-focus     teal night grade, a white box drawn round the place, its name in a pill
 *   satellite-photo     the pin, then a framed photo of the place on a leader line
 *   satellite-trace     two places on the teal grade, a dashed cyan route, "[ 50 MILES ]"
 * and the spread maps (spread / spread-dark): every named state or country
 * lights up in turn - "across seven states".
 */

const world = feature(topology as never, topology.objects.countries as never) as unknown as {features: object[]};
const states = feature(statesTopology as never, statesTopology.objects.states as never) as unknown as {features: object[]};
const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
const inOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const outCubic = (t: number) => 1 - Math.pow(1 - t, 3);

const TILE = 256;
const DISPLAY = 1.5;
const US_BOXES = [[18, 50, -126, -65], [51, 72, -170, -129], [18, 23, -161, -154]];
const inUS = (p: MapLocation) => US_BOXES.some(([a, b, c, d]) => p.lat >= a && p.lat <= b && p.lon >= c && p.lon <= d);
const GIBS_MAX = 8;
const USGS_MAX = 16;

// Web-Mercator world pixel at a (possibly fractional) zoom.
const worldPx = (lat: number, lon: number, z: number): [number, number] => {
  const n = TILE * Math.pow(2, z);
  const sin = Math.sin((Math.max(-85, Math.min(85, lat)) * Math.PI) / 180);
  return [((lon + 180) / 360) * n, (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * n];
};

const usgsZoom = (z: number, us: boolean) => us && z > GIBS_MAX - 2;
const tileUrl = (z: number, x: number, y: number, us: boolean) =>
  usgsZoom(z, us)
    ? `https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/${z}/${y}/${x}`
    : `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_NextGeneration/default/GoogleMapsCompatible_Level8/${z}/${y}/${x}.jpeg`;
// USGS imagery has no data over open water and serves those pixels black: a
// coastal zoom showed black squares on the sea. Its tiles go through this
// filter (near-black -> transparent) over a NASA Blue Marble underlay.
const NO_DATA_FILTER_ID = 'usgs-no-data';
// Blue Marble paints the open sea near-black too; under a USGS zoom its sea
// drops out as well and a painted ocean (USGS offshore water) shows instead.
const DARK_SEA_FILTER_ID = 'underlay-dark-sea';
const OCEAN = '#17314f';

// How close the camera lands, by what the gazetteer says the place is.
const LANDING: Record<string, number> = {
  country: 5, state: 7, region: 7, province: 7, county: 9, city: 11, town: 12,
  village: 13, hamlet: 13, suburb: 13, neighbourhood: 14, water: 10, lake: 10,
  reservoir: 10, river: 8, peak: 12, mountain: 11, mountain_range: 8,
  national_park: 9, dam: 14, building: 16, road: 14,
};

const miles = (a: MapLocation, b: MapLocation) => {
  const r = Math.PI / 180;
  const h = Math.sin(((b.lat - a.lat) * r) / 2) ** 2 +
    Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(((b.lon - a.lon) * r) / 2) ** 2;
  return 3958.8 * 2 * Math.asin(Math.sqrt(h));
};

const shortLabel = (l: string) => l.split(',')[0].trim();

type Layer = {z: number; opacity: number};

export const SatelliteMap: React.FC<{overlay: Overlay; accent: string}> = ({overlay, accent}) => {
  const frame = useCurrentFrame();
  const {width, height, fps, durationInFrames} = useVideoConfig();
  const places = (overlay.locations || []).filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon)).slice(0, 4);
  if (!places.length) return null;
  const v = overlay.variant || 'satellite';
  const pair = (v === 'satellite-route' || v === 'satellite-distance' || v === 'satellite-trace') && places.length > 1;
  // The case-file looks (Dr Insanity pass): a teal night grade and cyan markers.
  const teal = v === 'satellite-focus' || v === 'satellite-trace';
  const CYAN = '#53c8ff';
  const us = places.every(inUS);
  const zMax = us ? USGS_MAX : GIBS_MAX;
  const k = width / 1920;
  const unit = DISPLAY * k;

  // Where the camera looks and how far in it ends up.
  let centre: [number, number];
  let zEnd: number;
  if (pair) {
    const [a, b] = [worldPx(places[0].lat, places[0].lon, 0), worldPx(places[1].lat, places[1].lon, 0)];
    centre = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    const dx = Math.max(1e-6, Math.abs(a[0] - b[0])), dy = Math.max(1e-6, Math.abs(a[1] - b[1]));
    zEnd = Math.min(Math.log2((width * 0.55) / (unit * dx)), Math.log2((height * 0.5) / (unit * dy)), zMax);
  } else {
    centre = worldPx(places[0].lat, places[0].lon, 0);
    zEnd = Math.min(LANDING[places[0].kind || ''] ?? 10, zMax);
  }
  zEnd = Math.max(2, zEnd);
  const zStart = Math.max(1.5, zEnd - (pair ? 1.6 : 4));
  const land = durationInFrames * 0.62;
  const t = interpolate(frame, [0, land], [0, 1], clamp);
  const cam = zStart + (zEnd - zStart) * inOut(t) + interpolate(frame, [land, durationInFrames], [0, 0.18], clamp);

  // Screen position of a world point at the camera's zoom.
  const toScreen = (lat: number, lon: number): [number, number] => {
    const p = worldPx(lat, lon, cam);
    const f = Math.pow(2, cam);
    return [width / 2 + (p[0] - centre[0] * f) * unit, height / 2 + (p[1] - centre[1] * f) * unit];
  };

  const base = Math.min(zMax, Math.floor(cam));
  const frac = cam - base;
  const layers: Layer[] = [{z: base, opacity: 1}];
  if (base + 1 <= zMax && frac > 0.6) layers.push({z: base + 1, opacity: interpolate(frac, [0.6, 0.95], [0, 1], clamp)});
  const tilt = v === 'satellite-tilt' ? 40 * outCubic(interpolate(frame, [land * 0.4, land * 1.1], [0, 1], clamp)) : 0;
  const extraTop = tilt ? 0.9 : 0.1;

  // Under a USGS zoom, the Blue Marble layer at its own best zoom (the sea).
  const under: Layer[] = usgsZoom(base, us) ? [{z: Math.min(GIBS_MAX, base), opacity: 1}] : [];
  const tileLayer = ({z, opacity}: Layer, gibs: boolean) => {
    const scale = unit * Math.pow(2, cam - z);
    const size = TILE * scale;
    const cx = centre[0] * Math.pow(2, z), cy = centre[1] * Math.pow(2, z);
    const n = Math.pow(2, z);
    const side = tilt ? 1.45 : 1.02;
    const left = cx - (width / 2 / scale) * side, right = cx + (width / 2 / scale) * side;
    const top = cy - (height / 2 / scale) * (1 + extraTop), bottom = cy + height / 2 / scale * 1.1;
    const out: React.ReactNode[] = [];
    for (let ty = Math.floor(top / TILE); ty <= Math.floor(bottom / TILE); ty++) {
      if (ty < 0 || ty >= n) continue;
      for (let tx = Math.floor(left / TILE); tx <= Math.floor(right / TILE); tx++) {
        const wx = ((tx % n) + n) % n;
        out.push(
          <Img key={`${gibs ? 'g' : ''}${z}-${tx}-${ty}`} src={tileUrl(z, wx, ty, us && !gibs)} onError={() => undefined}
            delayRenderTimeoutInMilliseconds={60000} maxRetries={3}
            style={{position: 'absolute', left: width / 2 + (tx * TILE - cx) * scale, top: height / 2 + (ty * TILE - cy) * scale,
              width: Math.ceil(size) + 1, height: Math.ceil(size) + 1, opacity,
              filter: gibs ? `url(#${DARK_SEA_FILTER_ID})` : usgsZoom(z, us) ? `url(#${NO_DATA_FILTER_ID})` : undefined}} />,
        );
      }
    }
    return out;
  };
  const underTiles = under.flatMap((l) => tileLayer(l, true));
  const mainTiles = layers.flatMap((l) => tileLayer(l, false));

  const pinAt = land * 0.85;
  const pin = interpolate(frame, [pinAt, pinAt + fps * 0.4], [0, 1], clamp);
  const pts = places.map((p) => toScreen(p.lat, p.lon));
  const dark = v === 'satellite-dark';
  const pulse = v === 'satellite-pulse';
  const col = teal ? CYAN : pulse ? '#ff3b3b' : accent || '#ffd400';
  const draw = interpolate(frame, [pinAt, pinAt + fps * 1.2], [0, 1], clamp);
  const norm = (x: string) => x.toLowerCase().replace(/[^a-z0-9]/g, '');
  const heading = overlay.text && !tilt && !places.some((p) => norm(p.label).startsWith(norm(overlay.text)))
    ? overlay.text : '';

  return (
    <AbsoluteFill style={{background: '#050a14', overflow: 'hidden'}}>
      <AbsoluteFill style={{transform: tilt ? `perspective(${1500 * k}px) rotateX(${tilt}deg) scale(${1 + tilt / 110})` : undefined,
        transformOrigin: '50% 62%'}}>
        {/* The grade is on the imagery only, so pins, routes and labels keep their colour. */}
        <AbsoluteFill style={{background: under.length ? OCEAN : undefined,
          filter: teal ? 'grayscale(.85) sepia(.35) hue-rotate(150deg) saturate(1.3) brightness(.62) contrast(1.15)'
          : dark ? 'brightness(.55) contrast(1.25) saturate(.55) hue-rotate(-8deg)' : 'saturate(1.1) contrast(1.05)'}}>
          <svg width={0} height={0} style={{position: 'absolute'}}>
            <filter id={NO_DATA_FILTER_ID} colorInterpolationFilters="sRGB">
              {/* alpha = 9 x (R + G + B) - 0.1: black no-data drops out, dark water stays */}
              <feColorMatrix type="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  9 9 9 0 -0.1" />
            </filter>
            <filter id={DARK_SEA_FILTER_ID} colorInterpolationFilters="sRGB">
              {/* alpha = 4 x (R + G + B) - 0.4: the black sea goes, land stays */}
              <feColorMatrix type="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  4 4 4 0 -0.4" />
            </filter>
          </svg>
          {underTiles}
          {mainTiles}
        </AbsoluteFill>
        <svg width={width} height={height} style={{position: 'absolute', inset: 0}}>
          {pair && (() => {
            const [a, b] = pts;
            const bend = v === 'satellite-route' ? Math.min(160 * k, Math.hypot(b[0] - a[0], b[1] - a[1]) * 0.18) : 0;
            const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2 - bend;
            return <path d={`M ${a[0]} ${a[1]} Q ${mx} ${my} ${b[0]} ${b[1]}`} fill="none" stroke={col} strokeWidth={6 * k}
              strokeLinecap="round" pathLength={1}
              strokeDasharray={v === 'satellite-distance' ? '0.012 0.01' : v === 'satellite-trace' ? '0.016 0.012' : 1}
              strokeDashoffset={v === 'satellite-distance' ? 0 : 1 - draw}
              opacity={v === 'satellite-distance' ? draw : 1}
              style={teal ? {filter: `drop-shadow(0 0 ${8 * k}px ${CYAN})`} : undefined} />;
          })()}
          {pts.map(([x, y], i) => {
            const show = interpolate(frame, [pinAt + i * fps * 0.25, pinAt + i * fps * 0.25 + fps * 0.35], [0, 1], clamp);
            return (
              <g key={i} opacity={show}>
                {[0, 1, 2].slice(0, pulse ? 3 : 1).map((r) => {
                  const q = ((frame + r * fps * 0.5) % (fps * 1.5)) / (fps * 1.5);
                  return <circle key={r} cx={x} cy={y} r={(18 + (pulse ? 150 : 70) * q) * k} fill="none" stroke={col}
                    strokeWidth={4 * k} opacity={1 - q} />;
                })}
                <circle cx={x} cy={y} r={(teal ? 12 : 16) * k * show} fill={col} stroke="#fff" strokeWidth={(teal ? 3 : 5) * k}
                  style={teal ? {filter: `drop-shadow(0 0 ${14 * k}px ${CYAN})`} : undefined} />
              </g>
            );
          })}
        </svg>
      </AbsoluteFill>
      {dark ? <AbsoluteFill style={{background: 'radial-gradient(ellipse at center, transparent 45%, rgba(0,0,0,.7) 100%)'}} /> : null}
      {/* Labels sit outside the tilted plane so they stay readable. */}
      {!tilt && !teal && pts.map(([x, y], i) => {
        const show = interpolate(frame, [pinAt + fps * 0.2 + i * fps * 0.25, pinAt + fps * 0.6 + i * fps * 0.25], [0, 1], clamp);
        const label = shortLabel(places[i].label).toUpperCase();
        const w = Math.max(160, label.length * 26) * k;
        const right = x + w + 60 * k < width;
        return (
          <div key={i} style={{position: 'absolute', left: right ? x + 34 * k : x - w - 34 * k, top: y - 34 * k,
            opacity: show, transform: `translateX(${(1 - show) * (right ? -20 : 20) * k}px)`, background: 'rgba(8,10,14,.86)',
            borderLeft: `${6 * k}px solid ${col}`, padding: `${8 * k}px ${18 * k}px`, fontFamily: NARROW, fontWeight: 700,
            fontSize: 40 * k, letterSpacing: '0.04em', color: '#fff', whiteSpace: 'nowrap'}}>{label}</div>
        );
      })}
      {tilt ? (
        <div style={{position: 'absolute', left: 0, right: 0, top: height * 0.1, textAlign: 'center', opacity: pin,
          fontFamily: NARROW, fontWeight: 700, fontSize: 70 * k, color: '#fff', letterSpacing: '0.06em',
          textShadow: '0 4px 24px rgba(0,0,0,.9)'}}>{shortLabel(places[0].label).toUpperCase()}</div>
      ) : null}
      {pair && v === 'satellite-distance' ? (
        <div style={{position: 'absolute', left: (pts[0][0] + pts[1][0]) / 2 - 170 * k, top: (pts[0][1] + pts[1][1]) / 2 - 110 * k,
          width: 340 * k, textAlign: 'center', opacity: draw, fontFamily: NARROW, fontWeight: 700, fontSize: 54 * k,
          color: '#fff', textShadow: '0 4px 20px rgba(0,0,0,.95)'}}>
          ≈ {Math.round(miles(places[0], places[1])).toLocaleString('en-US')} MILES
          <div style={{fontFamily: INTER, fontWeight: 500, fontSize: 22 * k, letterSpacing: '0.12em', opacity: 0.8}}>STRAIGHT LINE</div>
        </div>
      ) : null}
      {heading ? (
        <div style={{position: 'absolute', left: 70 * k, top: 70 * k, maxWidth: width * 0.5, opacity: pin,
          fontFamily: NARROW, fontWeight: 700, fontSize: 48 * k, color: '#fff', textTransform: 'uppercase',
          textShadow: '0 4px 20px rgba(0,0,0,.95)'}}>{heading}</div>
      ) : null}
      {v === 'satellite-inset' ? <Inset place={places[0]} accent={col} /> : null}
      {teal ? pts.map(([x, y], i) => {
        // Small caps beside each dot (trace), or the focus box and its pill (focus).
        const show = interpolate(frame, [pinAt + fps * 0.2 + i * fps * 0.25, pinAt + fps * 0.6 + i * fps * 0.25], [0, 1], clamp);
        const label = shortLabel(places[i].label).toUpperCase();
        if (v === 'satellite-focus') {
          const bw = 300 * k, bh = 200 * k;
          const box = interpolate(frame, [pinAt + fps * 0.1, pinAt + fps * 0.7], [0, 1], clamp);
          return (
            <React.Fragment key={i}>
              <svg width={width} height={height} style={{position: 'absolute', inset: 0}}>
                <rect x={x - bw / 2} y={y - bh / 2} width={bw} height={bh} fill="none" stroke="#fff" strokeWidth={4 * k}
                  pathLength={1} strokeDasharray={1} strokeDashoffset={1 - box} />
              </svg>
              <div style={{position: 'absolute', left: x - 260 * k, width: 520 * k, top: y + bh / 2 + 18 * k, display: 'flex',
                justifyContent: 'center', opacity: show, transform: `translateY(${(1 - show) * 12 * k}px)`}}>
                <span style={{background: '#f4f7fb', color: '#10202e', fontFamily: NARROW, fontWeight: 700, fontSize: 30 * k,
                  letterSpacing: '0.08em', padding: `${6 * k}px ${18 * k}px`, borderRadius: 4 * k, whiteSpace: 'nowrap',
                  boxShadow: '0 8px 24px rgba(0,0,0,.45)'}}>{label}</span>
              </div>
            </React.Fragment>
          );
        }
        const right = x + 380 * k < width;
        return (
          <div key={i} style={{position: 'absolute', left: right ? x + 26 * k : x - 26 * k - 360 * k, width: 360 * k,
            textAlign: right ? 'left' : 'right', top: y - 18 * k, opacity: show, fontFamily: NARROW, fontWeight: 700,
            fontSize: 26 * k, letterSpacing: '0.12em', color: '#e9f6ff', textShadow: '0 2px 10px rgba(0,0,0,.95)'}}>{label}</div>
        );
      }) : null}
      {pair && v === 'satellite-trace' ? (
        <div style={{position: 'absolute', left: (pts[0][0] + pts[1][0]) / 2 - 200 * k, top: (pts[0][1] + pts[1][1]) / 2 - 64 * k,
          width: 400 * k, textAlign: 'center', opacity: draw, fontFamily: NARROW, fontWeight: 700, fontSize: 34 * k,
          letterSpacing: '0.1em', color: '#fff', textShadow: '0 3px 14px rgba(0,0,0,.95)'}}>
          [ {Math.round(miles(places[0], places[1])).toLocaleString('en-US')} MILES ]
        </div>
      ) : null}
      {v === 'satellite-photo' && pts.length ? (() => {
        // A framed photo of the place on a leader line from the pin.
        const src = (overlay.media || []).map((m) => (m.type === 'image' ? m.url : m.thumbnail || '')).find(Boolean);
        if (!src) return null;
        const [x, y] = pts[0];
        const cw = 400 * k, ch = 280 * k;
        const right = x + 90 * k + cw < width - 40 * k;
        const cx0 = right ? x + 90 * k : x - 90 * k - cw;
        const cy0 = Math.max(40 * k, y - ch - 110 * k);
        const pop = interpolate(frame, [pinAt + fps * 0.35, pinAt + fps * 0.75], [0, 1], clamp);
        return (
          <>
            <svg width={width} height={height} style={{position: 'absolute', inset: 0}}>
              <line x1={x} y1={y} x2={right ? cx0 : cx0 + cw} y2={cy0 + ch} stroke="#fff" strokeWidth={3 * k} opacity={pop} />
            </svg>
            <div style={{position: 'absolute', left: cx0, top: cy0, width: cw, height: ch, padding: 8 * k, background: '#fff',
              boxShadow: '0 18px 40px rgba(0,0,0,.5)', opacity: pop, transform: `scale(${0.85 + 0.15 * pop}) rotate(${right ? 1.5 : -1.5}deg)`,
              transformOrigin: right ? '0% 100%' : '100% 100%', boxSizing: 'border-box'}}>
              <Img src={src} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
            </div>
          </>
        );
      })() : null}
    </AbsoluteFill>
  );
};

const Inset: React.FC<{place: MapLocation; accent: string}> = ({place, accent}) => {
  const frame = useCurrentFrame();
  const {width, fps} = useVideoConfig();
  const k = width / 1920;
  const W = 380 * k, H = 250 * k;
  const us = inUS(place) && place.lon > -126;
  const shapes = us ? states : world;
  // Fit the lower 48 (or the inhabited world), not Alaska's Aleutians.
  const frameBox = us ? [[-125, 24], [-66, 50]] : [[-170, -56], [180, 76]];
  const projection = geoMercator().fitExtent([[10 * k, 10 * k], [W - 10 * k, H - 10 * k]],
    {type: 'MultiPoint', coordinates: frameBox} as never);
  const path = geoPath(projection);
  const p = projection([place.lon, place.lat]) || [W / 2, H / 2];
  const show = interpolate(frame, [fps * 0.3, fps * 0.8], [0, 1], clamp);
  const q = (frame % (fps * 1.2)) / (fps * 1.2);
  return (
    <div style={{position: 'absolute', right: 60 * k, top: 60 * k, width: W, height: H, opacity: show,
      background: 'rgba(12,16,24,.88)', border: `${2 * k}px solid rgba(255,255,255,.5)`, borderRadius: 10 * k}}>
      <svg width={W} height={H}>
        {shapes.features.map((f, i) => <path key={i} d={path(f as never) || ''} fill="#6b7686" stroke="#a3acb8" strokeWidth={0.8 * k} />)}
        <circle cx={p[0]} cy={p[1]} r={(6 + 26 * q) * k} fill="none" stroke={accent} strokeWidth={2.5 * k} opacity={1 - q} />
        <circle cx={p[0]} cy={p[1]} r={6 * k} fill={accent} stroke="#fff" strokeWidth={2 * k} />
      </svg>
    </div>
  );
};

export const SpreadMap: React.FC<{overlay: Overlay; accent: string}> = ({overlay, accent}) => {
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();
  const places = (overlay.locations || []).filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon));
  const placesKey = places.map((p) => `${p.lon},${p.lat},${p.label}`).join(';');
  // Only the reveal timing changes from frame to frame (the zoom is a CSS
  // transform): the outlines are projected once, not on every frame.
  const geo = React.useMemo(() => {
    if (!places.length) return null;
    const us = places.every(inUS);
    const shapes = us ? states : world;
    // Each place lights the state/country that contains it, in narration order.
    const found: {f: object; place: MapLocation}[] = [];
    for (const place of places) {
      const f = shapes.features.find((x) => geoContains(x as never, [place.lon, place.lat]));
      if (f && !found.some((l) => l.f === f)) found.push({f, place});
    }
    const focus = found.length ? {type: 'FeatureCollection', features: found.map((l) => l.f)} : shapes;
    const projection = geoMercator().fitExtent([[width * 0.22, height * 0.14], [width * 0.78, height * 0.74]], focus as never);
    const path = geoPath(projection);
    return {
      us,
      background: (us ? world.features : []).map((f) => path(f as never) || ''),
      shapes: shapes.features.map((f) => path(f as never) || ''),
      lit: found.map(({f, place}) => ({d: path(f as never) || '', centroid: path.centroid(f as never), place})),
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [placesKey, width, height]);
  if (!places.length || !geo) return null;
  const dark = overlay.variant === 'spread-dark';
  const k = width / 1920;
  const lit = geo.lit;
  const zoom = interpolate(frame, [0, fps * 3], [0.94, 1], clamp);
  const land = dark ? '#262a30' : '#e6dcc0';
  const edge = dark ? '#474c55' : '#b9ae8e';
  const sea = dark ? '#121418' : '#9fb6ba';
  const col = accent || '#e63946';
  const count = lit.filter((_, i) => frame > fps * (0.5 + i * 0.4)).length;
  return (
    <AbsoluteFill style={{background: sea, overflow: 'hidden'}}>
      <svg width={width} height={height} style={{transform: `scale(${zoom})`}}>
        <defs>
          <filter id="spreadGlow"><feGaussianBlur stdDeviation={6 * k} result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
        </defs>
        {geo.background.map((d, i) => <path key={`w${i}`} d={d} fill={land} stroke={edge} strokeWidth={k} />)}
        {geo.shapes.map((d, i) => <path key={i} d={d} fill={land} stroke={edge} strokeWidth={1.2 * k} />)}
        {lit.map(({d}, i) => {
          const on = interpolate(frame, [fps * (0.5 + i * 0.4), fps * (0.8 + i * 0.4)], [0, 1], clamp);
          return <path key={`l${i}`} d={d} fill={col} fillOpacity={0.85 * on} stroke="#fff"
            strokeWidth={2.5 * k * on} filter={dark ? 'url(#spreadGlow)' : undefined} />;
        })}
        {lit.map(({centroid, place}, i) => {
          const [x, y] = centroid;
          const on = interpolate(frame, [fps * (0.7 + i * 0.4), fps * (1.0 + i * 0.4)], [0, 1], clamp);
          if (!Number.isFinite(x)) return null;
          return <text key={`t${i}`} x={x} y={y} textAnchor="middle" dominantBaseline="middle" opacity={on}
            fontFamily={INTER} fontWeight={800} fontSize={Math.max(20, 32 - 1.5 * lit.length) * k} letterSpacing={1.5 * k}
            fill="#fff" stroke="rgba(0,0,0,.55)" strokeWidth={3 * k} paintOrder="stroke">{shortLabel(place.label).toUpperCase()}</text>;
        })}
      </svg>
      <div style={{position: 'absolute', left: 70 * k, top: 60 * k, fontFamily: NARROW, fontWeight: 700,
        fontSize: 64 * k, color: dark ? '#fff' : '#1d1b16', textTransform: 'uppercase', letterSpacing: '0.04em',
        opacity: interpolate(frame, [fps * 0.2, fps * 0.6], [0, 1], clamp)}}>
        {overlay.text || `${count} ${geo.us ? 'STATES' : 'COUNTRIES'}`}
      </div>
    </AbsoluteFill>
  );
};
