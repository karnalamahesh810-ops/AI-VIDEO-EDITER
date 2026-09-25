import React from 'react';
import {AbsoluteFill, Img, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import type {Overlay} from '../types';
import {INTER, TYPEWRITER, NARROW} from './fonts';

const clamp={extrapolateLeft:'clamp',extrapolateRight:'clamp'} as const;
const progress=(frame:number,start:number,end:number)=>interpolate(frame,[start,Math.max(start+1,end)],[0,1],clamp);

/** Staggered source images on graph paper; no baked-in reference footage. */
export const PhotoCard: React.FC<{overlay:Overlay;accent:string}>=({overlay,accent})=>{
 const f=useCurrentFrame(); const {fps,width}=useVideoConfig(); const s=width/1920;
 const media=(overlay.media||[]).filter(m=>m.type==='image'&&m.url).slice(0,2);
 const pair=media.length>1; const paper=overlay.variant==='grid';
 return <AbsoluteFill style={{background:paper?'#eeeade':'#153e34',backgroundImage:paper?'linear-gradient(#7775 1px, transparent 1px),linear-gradient(90deg,#7775 1px,transparent 1px)':'radial-gradient(ellipse,#286a53,#0c2520)',backgroundSize:paper?`${50*s}px ${50*s}px`:'cover',alignItems:'center',justifyContent:'center',flexDirection:'row',gap:'5%'}}>
  {media.map((m,i)=>{const p=progress(f,i*fps*.8,i*fps*.8+fps*.5);return <div key={i} style={{width:pair?'40%':'70%',height:'72%',opacity:p,transform:`translateY(${(1-p)*55*s}px) scale(${.96+.04*p})`,display:'flex',alignItems:'center',justifyContent:'center'}}><Img src={m.url} style={{maxWidth:'100%',maxHeight:'100%',objectFit:'contain',boxShadow:paper?'none':'0 18px 50px #0009',outline:paper?`2px dashed ${accent}`:'none',outlineOffset:4*s}}/></div>;})}
  {overlay.text&&<div style={{position:'absolute',bottom:'6%',fontFamily:TYPEWRITER,fontSize:40*s,color:paper?'#272522':'#eee',opacity:progress(f,fps,fps*1.6)}}>{overlay.text}</div>}
 </AbsoluteFill>;
};

/** Original image/transparent cutout supplied by the editor or sourcing stage. */
export const NameCard: React.FC<{overlay:Overlay;accent:string}>=({overlay,accent})=>{
 const f=useCurrentFrame();const {fps,width}=useVideoConfig();const s=width/1920;
 const media=overlay.media?.find(m=>m.type==='image'&&m.url);const p=progress(f,0,fps*1.1);
 return <AbsoluteFill style={{background:'#202020',overflow:'hidden'}}>
  <div style={{position:'absolute',left:`${33-25*p}%`,top:'37%',width:'24%',aspectRatio:'1',borderRadius:'50%',background:accent,boxShadow:`0 0 ${90*s}px ${accent}55`}}/>
  {media&&<Img src={media.url} style={{position:'absolute',left:`${35-27*p}%`,bottom:'10%',width:'25%',height:'80%',objectFit:'contain',opacity:progress(f,0,fps*.3)}}/>}
  <div style={{position:'absolute',left:'43%',right:'6%',top:'39%',opacity:progress(f,fps*.8,fps*1.5)}}>
   <div style={{fontFamily:TYPEWRITER,fontSize:31*s,color:'#ccc',marginBottom:20*s}}>{overlay.subtitle}</div>
   <div style={{fontFamily:TYPEWRITER,fontSize:64*s,color:accent,textTransform:'uppercase'}}>{overlay.text}</div>
  </div>
 </AbsoluteFill>;
};

/** A scrolling time ruler, with event labels revealed as the camera travels. */
export const TimeRuler:React.FC<{overlay:Overlay;accent:string}>=({overlay,accent})=>{
 const f=useCurrentFrame();const {fps,width,height}=useVideoConfig();const s=width/1920;
 const items=(overlay.items||[]).slice(0,6); const p=progress(f,fps*.2,fps*2.4); const scale=2.2-1.2*p;
 return <AbsoluteFill style={{background:'#0008',justifyContent:'center',overflow:'hidden'}}>
  <svg width={width} height={height} style={{transform:`scale(${scale}) translateX(${(1-p)*18}%)`}}>
   {Array.from({length:61},(_,i)=><line key={i} x1={i*width/60} x2={i*width/60} y1={height*.58} y2={height*.58+(i%5===0?65:38)*s} stroke="#eeeb" strokeWidth={3*s}/>)}
   {items.map((it,i)=>{const x=width*(.12+.76*i/Math.max(1,items.length-1));const show=progress(f,fps*(.3+i*.55),fps*(.65+i*.55));return <g key={i} opacity={show}><line x1={x} x2={x} y1={height*.57} y2={height*.67} stroke={accent} strokeWidth={8*s}/><rect x={x-105*s} y={height*.47} width={210*s} height={52*s} fill="#f2f2ee" rx={4*s}/><text x={x} y={height*.47+37*s} fill="#181818" fontFamily={INTER} fontSize={30*s} textAnchor="middle">{it.label}</text>{it.text&&<text x={x} y={height*.74} fill="#fff" fontFamily={INTER} fontSize={22*s} textAnchor="middle">{it.text.slice(0,35)}</text>}</g>;})}
  </svg>
 </AbsoluteFill>;
};

export const ObjectCallout:React.FC<{overlay:Overlay;accent:string}>=({overlay})=>{
 const f=useCurrentFrame();const {fps,width,height}=useVideoConfig();const s=width/1920;
 const target=overlay.anchor||{x:.63,y:.39};const label=overlay.labelPosition||{x:.3,y:.59};
 const x=target.x*width,y=target.y*height,lx=label.x*width,ly=label.y*height;const p=progress(f,0,fps*.65);
 return <AbsoluteFill><svg width={width} height={height}><path d={`M ${lx} ${ly} Q ${x} ${ly} ${x} ${y}`} fill="none" stroke="#fff" strokeWidth={4*s} pathLength={1} strokeDasharray={1} strokeDashoffset={1-p}/><circle cx={x} cy={y} r={4*s} fill="#fff" opacity={p}/></svg><div style={{position:'absolute',left:lx,top:ly,transform:'translate(-50%,-50%)',background:'#eee5d2',color:'#28221c',padding:`${10*s}px ${18*s}px`,fontFamily:'Georgia,serif',fontWeight:700,fontSize:38*s,textTransform:'uppercase',maxWidth:'40%',opacity:p}}>{overlay.text}</div></AbsoluteFill>;
};

export const EditorialChapter:React.FC<{overlay:Overlay;accent:string}>=({overlay,accent})=>{
 const f=useCurrentFrame();const {fps,width}=useVideoConfig();const s=width/1920;const p=progress(f,0,fps*.6);
 return <AbsoluteFill style={{background:'#111b',justifyContent:'center',alignItems:'center',overflow:'hidden'}}>
  {overlay.variant==='echo'&&<AbsoluteFill style={{color:accent,opacity:.16,fontFamily:NARROW,fontSize:160*s,lineHeight:1.12,fontWeight:700,transform:`rotate(-7deg) translateX(${-f*s*.5}px)`}}>{Array(8).fill(overlay.text.toUpperCase()).join(' ')}</AbsoluteFill>}
  <div style={{fontFamily:overlay.variant==='echo'?NARROW:'Georgia,serif',fontStyle:overlay.variant==='echo'?'normal':'italic',fontWeight:700,color:'#fff',fontSize:72*s,maxWidth:'80%',textAlign:'center',opacity:p,transform:`translateY(${(1-p)*28*s}px)`,textShadow:'0 4px 20px #000'}}>{overlay.text}</div>
 </AbsoluteFill>;
};
