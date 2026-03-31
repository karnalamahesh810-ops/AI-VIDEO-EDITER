export interface StateData {
  fips: string;
  name: string;
  abbreviation: string;
  person: {
    name: string;
    role: string;
    avatar: string;
  };
  rank: number;
  score: number;
  color: string;
  glowColor: string;
  stats: {
    population: number; // millions
    gdp: number; // trillion USD
    growth: number; // % YoY
    jobs: number; // millions
  };
  centroidApprox: [number, number]; // [lng, lat] approximate
}

export const TOP_5_STATES: StateData[] = [
  {
    fips: "06",
    name: "California",
    abbreviation: "CA",
    person: {
      name: "Alex Johnson",
      role: "West Coast Director",
      avatar: "AJ",
    },
    rank: 1,
    score: 98,
    color: "#FF6B6B",
    glowColor: "rgba(255,107,107,0.4)",
    stats: {
      population: 39.5,
      gdp: 3.6,
      growth: 4.2,
      jobs: 18.1,
    },
    centroidApprox: [-119.5, 37.3],
  },
  {
    fips: "48",
    name: "Texas",
    abbreviation: "TX",
    person: {
      name: "Sarah Williams",
      role: "Southern Regional Lead",
      avatar: "SW",
    },
    rank: 2,
    score: 94,
    color: "#4ECDC4",
    glowColor: "rgba(78,205,196,0.4)",
    stats: {
      population: 29.1,
      gdp: 2.0,
      growth: 3.8,
      jobs: 14.3,
    },
    centroidApprox: [-99.3, 31.2],
  },
  {
    fips: "12",
    name: "Florida",
    abbreviation: "FL",
    person: {
      name: "Michael Chen",
      role: "Southeast Manager",
      avatar: "MC",
    },
    rank: 3,
    score: 89,
    color: "#FFE66D",
    glowColor: "rgba(255,230,109,0.4)",
    stats: {
      population: 21.5,
      gdp: 1.1,
      growth: 5.1,
      jobs: 9.7,
    },
    centroidApprox: [-83.5, 27.8],
  },
  {
    fips: "36",
    name: "New York",
    abbreviation: "NY",
    person: {
      name: "Emma Davis",
      role: "Northeast Executive",
      avatar: "ED",
    },
    rank: 4,
    score: 86,
    color: "#A8E6CF",
    glowColor: "rgba(168,230,207,0.4)",
    stats: {
      population: 19.3,
      gdp: 1.9,
      growth: 2.7,
      jobs: 9.2,
    },
    centroidApprox: [-75.4, 43.0],
  },
  {
    fips: "42",
    name: "Pennsylvania",
    abbreviation: "PA",
    person: {
      name: "James Wilson",
      role: "Mid-Atlantic Director",
      avatar: "JW",
    },
    rank: 5,
    score: 81,
    color: "#C3A6FF",
    glowColor: "rgba(195,166,255,0.4)",
    stats: {
      population: 13.0,
      gdp: 0.9,
      growth: 2.1,
      jobs: 6.1,
    },
    centroidApprox: [-77.2, 40.9],
  },
];

export const TOTAL_FRAMES = 600;
export const FPS = 30;
export const INTRO_FRAMES = 60;
export const MAP_REVEAL_FRAMES = 90; // 60–150
export const STATE_DURATION = 72; // frames per state spotlight
export const OUTRO_FRAMES = 60;
