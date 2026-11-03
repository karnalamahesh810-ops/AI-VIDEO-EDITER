import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont as loadMontserrat } from "@remotion/google-fonts/Montserrat";
import type { Scene, StormDeskDoc } from "../../types";
import { SafeImg } from "../motion/safePicture";

/**
 * The storm desk style's graphics (doc.stormDesk, src/stormdesk.py), in the geometry measured on Global Storm Desk
 * (docs/style-refs/global-storm-desk/STYLE.md, 1920x1080; everything scales with the frame) and the customer's
 * colours and logo:
 *   - the logo bug, top-left, always on (3.4);
 *   - the lower third at each narration block: logo box, slanted divider, gradient bar with a 2-line heavy caps
 *     headline, a small tab above it (3.1) - in over ~12 frames (box, bar wipe, text, tab), out over 8 (fade);
 *   - the location / date chips at 1-9.5 s (3.3);
 *   - the subscribe pill with its bell at 50 s and every 120 s (3.5);
 *   - each shot's credit ("VIDEO: source", "ARCHIVE", "AI ILLUSTRATION") top-right, from scene.credit.
 * Drawn over the footage, under nothing; no sound.
 */
const MONT = `${loadMontserrat("normal", { subsets: ["latin"], weights: ["700", "800", "900"] }).fontFamily}, ` +
  "'Arial Black', sans-serif";
const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const ease = (x: number) => 1 - Math.pow(1 - Math.max(0, Math.min(1, x)), 3);

const DEFAULTS = {
  logo: "#0B2856", logo2: "#051531", bar: "#1B4CA0", bar2: "#08296A", rim: "#769CE8", divider: "#DE3349",
  tab: "#EF3E35", tab2: "#C71F1A", place: "#0E3076", date: "#CC241F", pin: "#CC2321", pill: "#E4302A",
  text: "#FDFDFA",
};

const hex = (c: unknown, fb: string) => (typeof c === "string" && /^#[0-9a-f]{6}$/i.test(c) ? c : fb);

/** A channel name as a wordmark: up to 3 balanced lines, sized to fit `width` x `height`. */
const wordmark = (text: string): string[] => {
  const words = String(text || "").toUpperCase().split(/\s+/).filter(Boolean).slice(0, 6);
  if (words.length <= 1) return words;
  let best: string[] = [words.join(" ")];
  let bestScore = best[0].length;
  for (let n = 2; n <= Math.min(3, words.length); n++) {
    // n lines: the split whose longest line is shortest (words kept in order).
    const per = Math.ceil(words.length / n);
    const lines: string[] = [];
    for (let k = 0; k < words.length; k += per) lines.push(words.slice(k, k + per).join(" "));
    const score = Math.max(...lines.map((l) => l.length)) + n * 1.5;
    if (score < bestScore) { best = lines; bestScore = score; }
  }
  return best;
};

const Logo: React.FC<{ url?: string; text?: string; height: number; width: number; color: string;
  align?: "left" | "center" }> = ({ url, text, height, width, color, align = "center" }) => {
  if (url) {
    return <SafeImg src={url} style={{ height, maxWidth: width, objectFit: "contain",
      objectPosition: `${align} center` }} />;
  }
  const lines = wordmark(String(text || "").slice(0, 32));
  if (!lines.length) return null;
  const longest = Math.max(...lines.map((l) => l.length), 1);
  const size = Math.min(height * 0.8 / lines.length, width / (longest * 0.72));
  return (
    <div style={{ font: `900 ${Math.round(size)}px ${MONT}`, color, lineHeight: 1.02, textAlign: align,
      whiteSpace: "nowrap" }}>
      {lines.map((l, k) => <div key={k}>{l}</div>)}
    </div>
  );
};

/** The lower third: frame f since it started, `dur` frames in all (in, hold, out). */
const LowerThird: React.FC<{ f: number; dur: number; lines: string[]; tab: string; c: typeof DEFAULTS;
  logoUrl?: string; logoText?: string; s: number }> = ({ f, dur, lines, tab, c, logoUrl, logoText, s }) => {
  const out = 1 - interpolate(f, [dur - 8, dur], [0, 1], clamp);
  if (out <= 0 || f < 0) return null;
  const X0 = 60 * s, Y0 = 850 * s, H = 149 * s, BOX = 270 * s, BAR = 1299 * s;
  const wipe = ease((f - 2) / 6);
  const text = ease((f - 8) / 3);
  const tabIn = ease((f - 10) / 3);
  const two = lines.length > 1;
  const longest = Math.max(...lines.map((l) => l.length), 1);
  const size = Math.min(two ? 62 : 70, (BAR - 110 * s) / s / (longest * 0.74)) * s;
  return (
    <div style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "100%", opacity: out,
      filter: `drop-shadow(0 ${4 * s}px ${12 * s}px rgba(0,0,0,0.35))` }}>
      <div style={{ position: "absolute", left: X0, top: Y0, width: BOX, height: H,
        background: `linear-gradient(${c.logo}, ${c.logo2})`, display: "flex", alignItems: "center",
        justifyContent: "center", overflow: "hidden" }}>
        <Logo url={logoUrl} text={logoText} height={118 * s} width={BOX - 36 * s} color={c.text} />
      </div>
      {wipe > 0 ? (
        <div style={{ position: "absolute", left: X0 + BOX, top: Y0, width: BAR * wipe, height: H, overflow: "hidden" }}>
          <div style={{ width: BAR, height: H, opacity: 0.93, background: `linear-gradient(${c.bar}, ${c.bar2})`,
            borderTop: `${3 * s}px solid ${c.rim}`, boxSizing: "border-box" }} />
          <div style={{ position: "absolute", left: 52 * s, top: 0, height: H, display: "flex", flexDirection: "column",
            justifyContent: "center", gap: 6 * s, opacity: text }}>
            {lines.slice(0, 2).map((l, k) => (
              <div key={k} style={{ font: `800 ${Math.round(size)}px ${MONT}`, color: c.text, lineHeight: 1.04,
                whiteSpace: "nowrap", textShadow: `0 ${2 * s}px ${3 * s}px rgba(0,0,0,0.35)` }}>{l}</div>
            ))}
          </div>
        </div>
      ) : null}
      {f >= 1 ? (
        <div style={{ position: "absolute", left: X0 + BOX - 8 * s, top: Y0, width: 14 * s, height: H,
          background: c.divider, transform: `skewX(-8deg)` }} />
      ) : null}
      {tabIn > 0 ? (
        <div style={{ position: "absolute", left: 366 * s - (1 - tabIn) * 30 * s, top: 802 * s, height: 47 * s,
          opacity: tabIn, display: "flex", alignItems: "center", gap: 12 * s, padding: `0 ${34 * s}px 0 ${18 * s}px`,
          background: `linear-gradient(${c.tab}, ${c.tab2})`,
          clipPath: `polygon(0 0, 100% 0, calc(100% - ${18 * s}px) 100%, 0 100%)` }}>
          <div style={{ width: 14 * s, height: 14 * s, borderRadius: "50%", background: c.text }} />
          <div style={{ font: `800 ${Math.round(30 * s)}px ${MONT}`, color: c.text, whiteSpace: "nowrap" }}>
            {tab.toUpperCase()}</div>
        </div>
      ) : null}
    </div>
  );
};

const Chip: React.FC<{ bg: string; h: number; s: number; children: React.ReactNode; first?: boolean }>
  = ({ bg, h, s, children, first }) => (
    <div style={{ height: h, background: bg, display: "flex", alignItems: "center", padding: `0 ${26 * s}px`,
      marginLeft: first ? 0 : -4 * s,
      clipPath: `polygon(${14 * s}px 0, 100% 0, calc(100% - ${14 * s}px) 100%, 0 100%)` }}>{children}</div>
  );

const LocationTag: React.FC<{ f: number; dur: number; place: string; date: string; c: typeof DEFAULTS; s: number }>
  = ({ f, dur, place, date, c, s }) => {
    const k = Math.min(ease(f / 9), 1 - interpolate(f, [dur - 9, dur], [0, 1], clamp));
    if (k <= 0) return null;
    const h = 73 * s;
    const font = `800 ${Math.round(36 * s)}px ${MONT}`;
    return (
      <div style={{ position: "absolute", left: 196 * s - (1 - k) * 24 * s, top: 30 * s, display: "flex",
        opacity: k, filter: `drop-shadow(0 ${3 * s}px ${8 * s}px rgba(0,0,0,0.45))` }}>
        <Chip bg={c.pin} h={h} s={s} first>
          <svg width={34 * s} height={44 * s} viewBox="0 0 34 44">
            <path d="M17 0C7.6 0 0 7.4 0 16.6 0 29 17 44 17 44s17-15 17-27.4C34 7.4 26.4 0 17 0z" fill={c.text} />
            <circle cx="17" cy="16" r="6.5" fill={c.pin} />
          </svg>
        </Chip>
        <Chip bg={c.place} h={h} s={s}><span style={{ font, color: c.text, whiteSpace: "nowrap" }}>{place}</span></Chip>
        <Chip bg={c.date} h={h} s={s}>
          <svg width={34 * s} height={34 * s} viewBox="0 0 34 34" style={{ marginRight: 14 * s }}>
            <rect x="2" y="2" width="30" height="30" rx="4" fill="none" stroke={c.text} strokeWidth="4" />
            <rect x="2" y="2" width="30" height="9" fill={c.text} />
            {[9, 16, 23].map((x) => [17, 24].map((y) => (
              <rect key={`${x}-${y}`} x={x} y={y} width="4" height="4" fill={c.text} />)))}
          </svg>
          <span style={{ font, color: c.text, whiteSpace: "nowrap" }}>{date}</span>
        </Chip>
      </div>
    );
  };

const Subscribe: React.FC<{ f: number; dur: number; c: typeof DEFAULTS; s: number }> = ({ f, dur, c, s }) => {
  if (f < 0 || f > dur) return null;
  const grow = ease(f / 4);
  const k = 1 - interpolate(f, [dur - 6, dur], [0, 1], clamp);
  const scale = 0.6 + 0.4 * grow;
  return (
    <div style={{ position: "absolute", right: (1920 - 1859) * s, top: 700 * s, height: 75 * s, display: "flex",
      alignItems: "center", gap: 16 * s, opacity: k, transform: `scale(${scale})`, transformOrigin: "right center",
      filter: `drop-shadow(0 ${3 * s}px ${8 * s}px rgba(0,0,0,0.45))` }}>
      <div style={{ width: 72 * s, height: 72 * s, borderRadius: "50%", background: "#FFFFFF", display: "flex",
        alignItems: "center", justifyContent: "center" }}>
        <svg width={40 * s} height={40 * s} viewBox="0 0 40 40">
          <path d="M20 4c-6.4 0-11 5-11 11.4V24l-4 5v2h30v-2l-4-5v-8.6C31 9 26.4 4 20 4z" fill={c.logo} />
          <circle cx="20" cy="34" r="4" fill={c.logo} />
        </svg>
      </div>
      <div style={{ height: 75 * s, padding: `0 ${36 * s}px`, borderRadius: 38 * s, background: c.pill,
        display: "flex", alignItems: "center", font: `800 ${Math.round(38 * s)}px ${MONT}`, color: "#FFFFFF" }}>
        SUBSCRIBE</div>
    </div>
  );
};

const Credit: React.FC<{ scene?: Scene; s: number }> = ({ scene, s }) => {
  const cr = (scene as unknown as { credit?: { text?: string; archive?: boolean; ai?: boolean } })?.credit;
  if (!cr || !cr.text) return null;
  const label = (cr.archive ? `ARCHIVE  ·  ${cr.text}` : cr.text).toUpperCase().slice(0, 60);
  return (
    <div style={{ position: "absolute", right: 40 * s, top: 40 * s, height: 38 * s, padding: `0 ${14 * s}px`,
      borderRadius: 6 * s, background: cr.ai ? "rgba(176,32,30,0.84)" : "rgba(0,0,0,0.47)", display: "flex",
      alignItems: "center", font: `700 ${Math.round(22 * s)}px ${MONT}`,
      color: cr.ai ? "rgba(255,255,255,0.92)" : "rgba(255,255,255,0.8)", whiteSpace: "nowrap" }}>{label}</div>
  );
};

/**
 * The logo on the blurred side panels of a vertical clip framed in the centre (scene.blurSides.panel = the centre
 * panel's share of the width; the reference channels put their mark there). desk.sideLogo false = off.
 */
const SideLogos: React.FC<{ scene?: Scene; url?: string; text: string; s: number; width: number }> = (
  { scene, url, text, s, width }) => {
  const panel = Number((scene as any)?.blurSides?.panel);
  if (!scene || !Number.isFinite(panel) || panel <= 0 || panel >= 0.9 || (!url && !text)) return null;
  const side = (1 - panel) / 2 * width;
  if (side < 140 * s) return null;
  const w = Math.min(side * 0.62, 300 * s);
  const box = (left: number) => (
    <div key={left} style={{ position: "absolute", left, top: 0, bottom: 0, width: side, display: "flex",
      alignItems: "center", justifyContent: "center", opacity: 0.88,
      filter: `drop-shadow(0 ${2 * s}px ${8 * s}px rgba(0,0,0,0.55))` }}>
      <Logo url={url} text={text} height={w * 0.62} width={w} color="rgba(255,255,255,0.9)" />
    </div>
  );
  return <>{box(0)}{box(width - side)}</>;
};

export const StormDesk: React.FC<{ desk: StormDeskDoc; scenes: Scene[] }> = ({ desk, scenes }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const s = Math.min(width / 1920, height / 1080);
  const c = { ...DEFAULTS } as typeof DEFAULTS;
  for (const k of Object.keys(DEFAULTS) as (keyof typeof DEFAULTS)[]) {
    c[k] = hex((desk.colors || {})[k], DEFAULTS[k]);
  }
  const logoUrl = desk.logo?.url || undefined;
  const logoText = desk.logo?.text || "";
  let current: Scene | undefined;
  for (const sc of scenes) {
    if (frame >= sc.startFrame && frame < sc.startFrame + sc.durationInFrames) { current = sc; break; }
  }
  const lt = (desk.lowerThirds || []).find((x) => frame >= x.startFrame && frame < x.startFrame + x.durationInFrames);
  const loc = desk.location && frame >= desk.location.startFrame
    && frame < desk.location.startFrame + desk.location.durationInFrames ? desk.location : null;
  const sub = (desk.subscribe || []).find((x) => frame >= x.startFrame && frame < x.startFrame + x.durationInFrames);
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {desk.sideLogo !== false ? <SideLogos scene={current} url={logoUrl} text={logoText} s={s} width={width} />
        : null}
      {/* The logo bug: always on, top-left, slightly translucent. */}
      <div style={{ position: "absolute", left: 36 * s, top: 22 * s, height: 92 * s, display: "flex",
        alignItems: "center", opacity: Math.max(0.3, Math.min(1, Number(desk.bug?.opacity ?? 0.9))),
        filter: `drop-shadow(0 ${2 * s}px ${6 * s}px rgba(0,0,0,0.5))` }}>
        {logoUrl || logoText ? <Logo url={logoUrl} text={logoText} height={(logoUrl ? 92 : 70) * s} width={150 * s}
          color="rgba(255,255,255,0.92)" align="left" /> : null}
      </div>
      {desk.credits !== false ? <Credit scene={current} s={s} /> : null}
      {loc ? <LocationTag f={frame - loc.startFrame} dur={loc.durationInFrames} place={loc.place} date={loc.date}
        c={c} s={s} /> : null}
      {sub ? <Subscribe f={frame - sub.startFrame} dur={sub.durationInFrames} c={c} s={s} /> : null}
      {lt ? <LowerThird f={frame - lt.startFrame} dur={lt.durationInFrames} lines={lt.lines || []}
        tab={lt.tab || "BREAKING NEWS"} c={c} logoUrl={logoUrl} logoText={logoText} s={s} /> : null}
    </AbsoluteFill>
  );
};
