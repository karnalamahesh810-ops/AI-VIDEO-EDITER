import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {geoContains, geoMercator, geoPath} from 'd3-geo';
import {feature} from 'topojson-client';
import topology from 'world-atlas/countries-110m.json';
import statesTopology from '../data/us-states.json';
import type {Overlay} from '../types';
import {INTER, LABEL} from './fonts';

const world = feature(topology as never, topology.objects.countries as never);
const states = feature(statesTopology as never, statesTopology.objects.states as never) as unknown as {features: object[]};
const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

/** Offline, deterministic locator/route map. Routes connect verified places;
 * they depict a journey, never a road alignment or a hazard boundary. */
type Place = {lat: number; lon: number; label: string};

/** Where the map is centred and how far it is zoomed out for these places. */
const framing = (places: Place[], width: number, minSpan = 24) => {
  // Circular mean keeps a journey crossing the Pacific centred on the Pacific.
  const rad = Math.PI / 180;
  const centreLon = Math.atan2(places.reduce((a,p)=>a+Math.sin(p.lon*rad),0), places.reduce((a,p)=>a+Math.cos(p.lon*rad),0))/rad;
  const centreLat = places.reduce((a,p)=>a+p.lat,0)/places.length;
  const relativeLon = (lon: number) => ((lon-centreLon+540)%360)-180;
  const span = Math.max(minSpan, ...places.map(p=>Math.abs(relativeLon(p.lon))*2.6), ...places.map(p=>Math.abs(p.lat-centreLat)*4));
  return {centreLon, centreLat, scale: width/(span*rad)};
};

export const DocumentaryMap: React.FC<{overlay: Overlay; accent: string}> = ({overlay, accent}) => {
  // Rebuilt 2026-09-30 ("maps must look premium: clean labels, glowing
  // outlines, smooth camera"): a graded dark or paper basemap with a faint
  // grid, an eased camera settle and a slow push, the state that holds each
  // place glowing in the accent, glowing pins with outlined bold labels (no
  // grey pills), cased routes with a travelling head, and the title in
  // outlined bold caps top-left. Everything fades in the last 12 frames.
  const frame = useCurrentFrame();
  const {width, height, fps, durationInFrames: D} = useVideoConfig();
  const places = (overlay.locations || []).filter(p => Number.isFinite(p.lat) && Number.isFinite(p.lon));
  const placesKey = places.map(p => `${p.lon},${p.lat}`).join(';');
  const geo = React.useMemo(() => {
    if (!places.length) return null;
    const f = framing(places, width, (overlay.variant || '').startsWith('route') && places.length > 1 ? 5 : 24);
    const p = geoPath(geoMercator().rotate([-f.centreLon,0]).center([0,f.centreLat]).scale(f.scale).translate([width/2,height*.5]));
    type Feat = {properties?: {name?: string}};
    return {world: p(world as never) || '',
            states: states.features.map(st => ({d: p(st as never) || '', centroid: p.centroid(st as never),
                                                 name: String((st as Feat).properties?.name || ''),
                                                 hit: places.some(pl => geoContains(st as never, [pl.lon, pl.lat]))}))};
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [placesKey, width, height, overlay.variant]);
  if (!places.length || !geo) return null;
  const v = overlay.variant || '';
  const paper = ['paper', 'route-paper', 'region', 'marker'].includes(v);
  const route = v.startsWith('route') && places.length > 1;
  const s = width / 1920;
  const col = accent || '#e63946';
  const {centreLon, centreLat, scale} = framing(places, width, route ? 5 : 24);
  const settle = 1 - Math.pow(1 - interpolate(frame, [0, fps * 1.2], [0, 1], clamp), 3);
  const zoom = (0.9 + 0.1 * settle) * interpolate(frame, [0, D], [1, 1.05], clamp);
  const out = interpolate(frame, [D - 13, D - 1], [0, 1], {...clamp, easing: (t) => t * t});
  const tx = width / 2, ty = height * .5;
  // Only the few place points are projected per frame; the outlines ride on a transform.
  const projection = geoMercator().rotate([-centreLon,0]).center([0,centreLat]).scale(scale*zoom).translate([tx,ty]);
  const points = places.map(p => projection([p.lon, p.lat])!);
  const reveal = interpolate(frame, [fps*.5, fps*2.2], [0, 1], clamp);
  const land = paper ? '#efe7d2' : '#1b212b';
  const worldLand = paper ? '#e8dec6' : '#161b23';
  const edge = paper ? '#c2b797' : '#3a4350';
  const hitFill = paper ? '#d9b98a' : col;
  const outlineCss = (px: number) => ({WebkitTextStroke: `${Math.max(4*s, px*.11).toFixed(2)}px #000`, paintOrder: 'stroke fill',
    textShadow: `0 ${3*s}px ${4*s}px rgba(0,0,0,.35), 0 ${8*s}px ${24*s}px rgba(0,0,0,.5)`}) as React.CSSProperties;
  const title = (overlay.text || '').trim();
  const titlePx = Math.max(56, Math.min(88, 1500 / Math.max(8, title.length * .55))) * s;
  const labelPx = (places.length <= 2 ? 52 : 42) * s;
  const hitOn = 1 - Math.pow(1 - interpolate(frame, [fps*.35, fps*.9], [0, 1], clamp), 3);
  // For a region the state's own name is the label; for a point, the place's.
  const regionStates = v === 'region' ? geo.states.filter(st => st.hit) : [];
  return <AbsoluteFill style={{background: paper ? 'radial-gradient(ellipse at 50% 45%, #b8c9cc 0%, #93aab0 75%)'
      : 'radial-gradient(ellipse at 50% 45%, #111a26 0%, #080b11 70%)', overflow: 'hidden'}}>
    <AbsoluteFill style={{opacity: paper ? .1 : .06, backgroundImage:
      `linear-gradient(${paper ? '#29424a' : '#9fb4ff'} 1px, transparent 1px), linear-gradient(90deg, ${paper ? '#29424a' : '#9fb4ff'} 1px, transparent 1px)`,
      backgroundSize: `${96*s}px ${96*s}px`}}/>
    <svg width={width} height={height} style={{position: 'absolute', inset: 0}}>
      <defs><filter id="docGlow" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation={9*s}/></filter></defs>
      <g transform={`translate(${tx} ${ty}) scale(${zoom}) translate(${-tx} ${-ty})`}>
        <path d={geo.world} fill={worldLand} stroke={edge} strokeWidth={s*1.3/zoom}/>
        {geo.states.map((st,i)=><path key={i} d={st.d} fill={land} stroke={edge} strokeWidth={s*1.1/zoom}/>)}
        {/* a route is framed inside its state: the journey is the subject, not the state fill */}
        {route ? null : geo.states.map((st,i)=> st.hit ? <g key={`h${i}`} opacity={hitOn * (1 - out)}>
          <path d={st.d} fill="none" stroke={col} strokeWidth={10*s/zoom} strokeOpacity={paper ? .35 : .7} filter="url(#docGlow)"/>
          <path d={st.d} fill={hitFill} fillOpacity={paper ? .55 : .38} stroke={col} strokeWidth={3.5*s/zoom} strokeLinejoin="round"/>
        </g> : null)}
      </g>
      {route && points.slice(1).map((p,i)=>{
        const a=points[i]; const progress=Math.max(0,Math.min(1,reveal*(points.length-1)-i));
        const bend=Math.min(140*s,Math.hypot(a[0]-p[0],a[1]-p[1])*.22);
        const d=`M ${a[0]} ${a[1]} Q ${(a[0]+p[0])/2} ${(a[1]+p[1])/2-bend} ${p[0]} ${p[1]}`;
        // The head of the line: the point on the quadratic at `progress`.
        const t=progress, cx=(a[0]+p[0])/2, cy=(a[1]+p[1])/2-bend;
        const hx=(1-t)*(1-t)*a[0]+2*(1-t)*t*cx+t*t*p[0], hy=(1-t)*(1-t)*a[1]+2*(1-t)*t*cy+t*t*p[1];
        return <g key={i} opacity={1 - out}>
          <path d={d} fill="none" stroke="#000" strokeWidth={15*s} strokeLinecap="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1-progress} opacity={.6}/>
          <path d={d} fill="none" stroke={col} strokeWidth={9*s} strokeLinecap="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1-progress}
            style={{filter:`drop-shadow(0 0 ${8*s}px ${col})`}}/>
          {progress>0 && progress<1 ? <circle cx={hx} cy={hy} r={9*s} fill="#fff" style={{filter:`drop-shadow(0 0 ${10*s}px ${col})`}}/> : null}
        </g>;
      })}
      {v==='pulse' && points.map(([x,y],i)=>[0,1,2].map(kk=>{
        const t=((frame+kk*fps*.5)%(fps*1.5))/(fps*1.5);
        return <circle key={`${i}-${kk}`} cx={x} cy={y} r={(20+120*t)*s} fill="none" stroke={col} strokeWidth={4*s} opacity={(1-t)*(1-out)}/>;
      }))}
    </svg>
    {regionStates.map((st,i)=>{
      const [x,y]=st.centroid; if(!Number.isFinite(x)) return null;
      const X=tx+(x-tx)*zoom, Y=ty+(y-ty)*zoom;
      const p=1-Math.pow(1-interpolate(frame,[fps*(.7+i*.2),fps*(1.1+i*.2)],[0,1],clamp),3);
      return <div key={`r${i}`} style={{position:'absolute',left:X,top:Y,transform:`translate(-50%,-50%) translateY(${((1-p)*16*s).toFixed(2)}px)`,
        opacity:p*(1-out),fontFamily:LABEL,fontWeight:800,fontSize:labelPx*1.2,letterSpacing:'.04em',color:'#fff',whiteSpace:'nowrap',
        textTransform:'uppercase',...outlineCss(labelPx*1.2)}}>{st.name}</div>;
    })}
    {v==='region' ? null : points.map(([x,y],i)=>{
      const at=fps*(.55+i*.35);
      const p=1-Math.pow(1-interpolate(frame,[at,at+fps*.35],[0,1],clamp),3);
      const parts=places[i].label.split(',').map(t=>t.trim()).filter(Boolean);
      const main=(parts[0]||'').toUpperCase(), sub=(parts[1]||'').toUpperCase();
      const w=Math.max(main.length*labelPx*.5, sub.length*labelPx*.3);
      // Labels alternate sides, so two close places never print on top of each other.
      const left=(i%2===0 || places.length<2) ? x+w+60*s<width-96*s : !(x-w-60*s>96*s);
      const ring=((frame-at)/(fps*1.2))%1;
      return <React.Fragment key={i}>
        {v==='marker' ? <svg width={80*s} height={100*s} viewBox="0 0 80 100" style={{position:'absolute',left:x-40*s,top:y-96*s,
          transform:`scale(${p})`,transformOrigin:'50% 100%',overflow:'visible',opacity:1-out}}>
          <path d="M40 96 C40 96 8 60 8 38 A32 32 0 1 1 72 38 C72 60 40 96 40 96 Z" fill={col} stroke="#000" strokeWidth={5}/>
          <path d="M40 18 V44 M40 54 V58" stroke="#fff" strokeWidth={8} strokeLinecap="round"/>
        </svg> : <>
          {frame>at ? <div style={{position:'absolute',left:x-60*s,top:y-60*s,width:120*s,height:120*s,borderRadius:'50%',
            border:`${3*s}px solid ${col}`,transform:`scale(${(.2+.8*ring).toFixed(3)})`,opacity:(1-ring)*p*(1-out)}}/> : null}
          <div style={{position:'absolute',left:x-14*s,top:y-14*s,width:28*s,height:28*s,borderRadius:'50%',background:col,
            border:`${4*s}px solid #fff`,boxShadow:`0 0 0 ${2.5*s}px #000, 0 0 ${20*s}px ${col}`,transform:`scale(${p.toFixed(3)})`,opacity:1-out}}/>
        </>}
        <div style={{position:'absolute',top:y-labelPx*.95,left:left?x+34*s:undefined,right:left?undefined:width-x+34*s,
          textAlign:left?'left':'right',opacity:p*(1-out),transform:`translateX(${((1-p)*(left?-18:18)*s).toFixed(2)}px)`}}>
          <div style={{fontFamily:LABEL,fontWeight:800,fontSize:labelPx,lineHeight:1.02,letterSpacing:'.03em',color:'#fff',whiteSpace:'nowrap',
            ...outlineCss(labelPx)}}>{main}</div>
          {sub ? <div style={{fontFamily:LABEL,fontWeight:800,fontSize:labelPx*.56,letterSpacing:'.14em',color:col,whiteSpace:'nowrap',
            ...outlineCss(labelPx*.56)}}>{sub}</div> : null}
        </div>
      </React.Fragment>;
    })}
    <AbsoluteFill style={{boxShadow:`inset 0 0 ${220*s}px rgba(0,0,0,${paper?.22:.5})`,pointerEvents:'none'}}/>
    {title ? <div style={{position:'absolute',left:96*s,top:80*s,fontFamily:LABEL,fontWeight:800,fontSize:titlePx,color:'#fff',
      textTransform:'uppercase',letterSpacing:'.02em',whiteSpace:'nowrap',...outlineCss(titlePx),opacity:1-out,
      clipPath:`inset(-30% ${((1-(1-Math.pow(1-interpolate(frame,[fps*.1,fps*.6],[0,1],clamp),3)))*100).toFixed(2)}% -30% 0)`}}>{title}</div> : null}
    {title ? <div style={{position:'absolute',left:96*s,top:80*s+titlePx*1.2,height:10*s,borderRadius:3*s,background:col,
      width:200*s*(1-Math.pow(1-interpolate(frame,[fps*.4,fps*.9],[0,1],clamp),3))*(1-out),boxShadow:`0 0 0 ${2.5*s}px #000, 0 0 ${14*s}px ${col}`}}/> : null}
    <div style={{position:'absolute',right:24*s,bottom:18*s,fontFamily:INTER,fontSize:18*s,color:paper?'#28251e':'#dde2ea',opacity:.6}}>
      Natural Earth / US Census{route?' · Schematic journey':''}</div>
  </AbsoluteFill>;
};
