// Theme tokens for the faceless-doc template, distilled from 5 reference videos.
// 4 presets ("dialects"): business-blue, minimal red/white, essay-cyan, seattle-navy.

export type ThemeName = "business" | "minimal" | "essay" | "navy";

export type Theme = {
  name: ThemeName;
  bg: string;        // dark backdrop for graphic-only scenes
  panel: string;     // chart/quote panel fill (dark)
  cardPaper: string; // stat-card body
  cardInk: string;   // stat-card bullet text
  accent: string;    // primary structure accent (headers, checkboxes, pins)
  accent2: string;   // secondary accent (borders, pills)
  alert: string;     // emphasis/decline/highlight
  chartA: string;    // chart line/bar A
  chartB: string;    // chart line/bar B (spotlight)
  text: string;
  textMute: string;
  headerFont: string;     // condensed caps (Oswald/Anton/Bebas)
  bodyFont: string;       // humanist sans (Montserrat/Inter/Poppins)
  cardBulletFont: string; // italic serif/casual for card bullets
};

const COND = "'Oswald','Anton','Arial Narrow',Impact,sans-serif";
const SANS = "'Montserrat','Inter','Poppins',Arial,sans-serif";
const SERIF_IT = "Georgia,'Times New Roman',serif";

export const THEMES: Record<ThemeName, Theme> = {
  business: {
    name: "business", bg: "#0E1B2A", panel: "#152238", cardPaper: "#F7F8FA", cardInk: "#3C4654",
    accent: "#2B5CA8", accent2: "#3B7DF0", alert: "#E8202B", chartA: "#2BB6E6", chartB: "#E8722C",
    text: "#FFFFFF", textMute: "#9AA0A6", headerFont: COND, bodyFont: SANS, cardBulletFont: SERIF_IT,
  },
  minimal: {
    name: "minimal", bg: "#0B0D10", panel: "#16202E", cardPaper: "#F4F4F2", cardInk: "#222831",
    accent: "#E10E10", accent2: "#FFFFFF", alert: "#E10E10", chartA: "#FFFFFF", chartB: "#E10E10",
    text: "#FFFFFF", textMute: "#8A8A8A", headerFont: COND, bodyFont: SANS, cardBulletFont: SANS,
  },
  essay: {
    name: "essay", bg: "#0E1014", panel: "#14161E", cardPaper: "#F4F4F2", cardInk: "#1A1D24",
    accent: "#23A9E0", accent2: "#9ACD32", alert: "#23A9E0", chartA: "#23A9E0", chartB: "#9ACD32",
    text: "#FFFFFF", textMute: "#8A9099", headerFont: SANS, bodyFont: SANS, cardBulletFont: SANS,
  },
  navy: {
    name: "navy", bg: "#0E1726", panel: "#16213A", cardPaper: "#F7F8FA", cardInk: "#3C4654",
    accent: "#29B6F6", accent2: "#F5A623", alert: "#E53935", chartA: "#29B6F6", chartB: "#F5A623",
    text: "#FFFFFF", textMute: "#9AA0A6", headerFont: COND, bodyFont: SANS, cardBulletFont: SERIF_IT,
  },
};

export const defaultTheme = THEMES.business;
export const getTheme = (n?: string): Theme => THEMES[(n as ThemeName)] || defaultTheme;
