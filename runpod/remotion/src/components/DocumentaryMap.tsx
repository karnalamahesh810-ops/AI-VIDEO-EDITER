import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {geoContains, geoMercator, geoPath} from 'd3-geo';
import {feature} from 'topojson-client';
import topology from 'world-atlas/countries-110m.json';
import statesTopology from '../data/us-states.json';
import type {Overlay} from '../types';
import {INTER} from './fonts';

const world = feature(topology as never, topology.objects.countries as never);
const states = feature(statesTopology as never, statesTopology.objects.states as never) as unknown as {features: object[]};
const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

/** Offline, deterministic locator/route map. Routes connect verified places;
 * they depict a journey, never a road alignment or a hazard boundary. */
export const DocumentaryMap: React.FC<{overlay: Overlay; accent: string}> = ({overlay, accent}) => {
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();
  const places = (overlay.locations || []).filter(p => Number.isFinite(p.lat) && Number.isFinite(p.lon));
  if (!places.length) return null;
  const paper = overlay.variant === 'paper' || overlay.variant === 'route-paper';
  const route = overlay.variant?.startsWith('route') && places.length > 1;
  const ink = paper ? '#28251e' : '#eee';
  const land = paper ? '#e4d7b2' : '#292a2c';
  const water = paper ? '#95adb0' : '#18191b';
  const s = width / 1920;
  // Circular mean keeps a journey crossing the Pacific centred on the Pacific.
  const rad = Math.PI / 180;
  const centreLon = Math.atan2(places.reduce((a,p)=>a+Math.sin(p.lon*rad),0), places.reduce((a,p)=>a+Math.cos(p.lon*rad),0))/rad;
  const centreLat = places.reduce((a,p)=>a+p.lat,0)/places.length;
  const relativeLon = (lon: number) => ((lon-centreLon+540)%360)-180;
  const span = Math.max(24, ...places.map(p=>Math.abs(relativeLon(p.lon))*2.6), ...places.map(p=>Math.abs(p.lat-centreLat)*4));
  const scale = width/(span*rad);
  const zoom = interpolate(frame, [0, fps*2], [.91,1], clamp);
  const projection = geoMercator().rotate([-centreLon,0]).center([0,centreLat]).scale(scale*zoom).translate([width/2,height*.46]);
  const path = geoPath(projection);
  const points = places.map(p => projection([p.lon, p.lat])!);
  const reveal = interpolate(frame,[fps*.3,fps*2.3],[0,1],clamp);
  const caption = overlay.text.slice(0,Math.floor(interpolate(frame,[fps*1.7,fps*3.1],[0,overlay.text.length],clamp)));
  return <AbsoluteFill style={{background:water, overflow:'hidden'}}>
    <svg width={width} height={height}>
      <path d={path(world as never)||''} fill={land} stroke={paper?'#c0b99e':'#47484a'} strokeWidth={s*1.4}/>
      {states.features.map((state,i)=><path key={i} d={path(state as never)||''} fill={places.some(p=>geoContains(state as never,[p.lon,p.lat])) ? (paper?'#c2a378':accent) : land} fillOpacity={.85} stroke={paper?'#b8af90':'#48494b'} strokeWidth={s*.9}/>)}
      {route && points.slice(1).map((p,i)=>{
        const a=points[i]; const progress=Math.max(0,Math.min(1,reveal*(points.length-1)-i));
        return <path key={i} d={`M ${a[0]} ${a[1]} Q ${(a[0]+p[0])/2} ${(a[1]+p[1])/2-Math.min(110*s,Math.abs(a[0]-p[0])*.16)} ${p[0]} ${p[1]}`} fill="none" stroke={accent} strokeWidth={5*s} pathLength={1} strokeDasharray={1} strokeDashoffset={1-progress}/>;
      })}
      {points.map(([x,y],i)=>{
        const show=interpolate(frame,[fps*(.5+i*.35),fps*(1+i*.35)],[0,1],clamp);
        const label=places[i].label.split(',').slice(0,2).join(',');
        const labelWidth=Math.min(width*.38,Math.max(120*s,label.length*15*s));
        const lx=Math.min(width-labelWidth-30*s,Math.max(30*s,x-labelWidth/2));
        return <g key={i} opacity={show}>
          <circle cx={x} cy={y} r={22*s} fill={accent} opacity={.2}/><circle cx={x} cy={y} r={7*s} fill={accent}/>
          <rect x={lx} y={y+25*s} width={labelWidth} height={44*s} rx={paper?18*s:3*s} fill={paper?'#f5efdf':'#eee'}/>
          <text x={lx+labelWidth/2} y={y+54*s} textAnchor="middle" fontFamily={INTER} fontSize={24*s} fill="#202020">{label}</text>
        </g>;
      })}
    </svg>
    <AbsoluteFill style={{boxShadow:'inset 0 0 160px rgba(0,0,0,.25)',pointerEvents:'none'}}/>
    <div style={{position:'absolute',left:'4%',bottom:'8%',fontFamily:INTER,fontSize:38*s,color:ink}}>{caption}{frame<fps*3.2?' |':''}</div>
    <div style={{position:'absolute',right:'2%',bottom:'2%',fontFamily:INTER,fontSize:16*s,color:ink,opacity:.65}}>Natural Earth / US Census{route?' · Schematic journey':''}</div>
  </AbsoluteFill>;
};
