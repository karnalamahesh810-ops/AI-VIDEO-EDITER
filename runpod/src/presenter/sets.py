"""
Where the AI presenter is filmed, for ANY niche: a catalogue of sets, the
choice of one for a video ("auto" reads the title and the script), and the
presenter made IN that set - two pictures, the main camera (waist up) and a
close-up, drawn with Nano Banana Pro from the kit's master portrait, kept on
R2 beside the kit so each presenter + set pair is paid for once, ever.

(Not the kit's own "sets" in src/presenter/kits.py: those are the empty set
plates of the presenter's home set, the style's still fallbacks.)

  SETS / GROUPS  the catalogue (ids, the app's labels, the picture prompts).
                 The app shows the same list (_shared/presenterSets.ts in the
                 app; a test pins the ids on both sides).
  choose()       "auto": keyword rules over the title (x3) and the script for
                 every niche (history, finance, tech, true crime, travel, food,
                 sports, science, health, education, gaming, business, news,
                 weather...). Only when the rules are unsure, one cheap model
                 call (google/gemini-2.5-flash, ~$0.0005); still unsure: the
                 neutral studio. A pick that is the presenter's own home set
                 is that set (free: the kit's own pictures).
  request_of()   the job's choice ("presenter_set" for the AI presenter style,
                 the hybrid block's "set"): a set id, "auto", "home", or
                 "custom" with a description ("Describe a set"). Absent: the
                 kit's own set - exactly what jobs did before sets existed.
  ensure()       the pair: the R2 cache first (<kit folder>/sets/<set>/set.json,
                 the kit folder being the master's own folder on R2:
                 presenters/<id>/ or presenters/user/<uid>/<id>/), else made -
                 2 pictures, a same-person check on each, one retry - then
                 uploaded and recorded (set.json + the kit's sets/index.json,
                 which the app's picker reads for its previews).
  apply()        the kit with the set's two pictures as its framings (the
                 master first, the close-up the second camera); the home set's
                 empty plates go (they show another room).
  SetJob         one job's set: chosen, looked up, made in the background,
                 applied - and its report (meta.presenter.set,
                 meta.presenterHybrid.set). Any failure keeps the kit's own
                 set: the presenter still appears, the video still finishes.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .. import config

PROMPT_VERSION = 1
SET_MODEL = os.getenv("PRESENTER_SET_MODEL", "google/gemini-3-pro-image").strip()
SET_SIZE = os.getenv("PRESENTER_SET_SIZE", "2K").strip()
CHOOSE_MODEL = os.getenv("PRESENTER_SET_CHOOSE_MODEL", "google/gemini-2.5-flash").strip()
PICTURE_USD = 0.14            # one Nano Banana Pro 2K picture with a reference (measured 0.139-0.141, 2026-10-07)
CHECK_USD = 0.004             # the most one same-person check may cost
CHOOSE_USD = 0.003            # the most the model's pick may cost
# What a pair may cost: two pictures and their checks, with room for one picture's retry.
PAIR_PROJECTED_USD = round(3 * PICTURE_USD * 1.05 + 3 * CHECK_USD, 3)
DEFAULT_SET = "studio"
HOME = "home"
CUSTOM = "custom"
CLAIM_SECONDS = 6 * 60        # a pair "being made" by another job for longer than this is made again
CLAIM_WAIT_SECONDS = float(os.getenv("PRESENTER_SET_WAIT_SECONDS", "240") or 240)
MAX_DESCRIPTION = 200


# ------------------------------------------------------------------ the catalogue
@dataclass(frozen=True)
class SetSpec:
    id: str
    label: str                  # the app's chip
    hint: str                   # one line under it
    group: str                  # studio | learning | home | location
    niches: str                 # what it suits (the model's pick reads it; the app's tooltip)
    where: str                  # "in a wood-panelled study": the avatar prompt and the persona line
    room: str                   # the place behind the presenter, for the picture model
    stance: str                 # where the presenter is and what the hands do (the main camera)
    light: str
    wardrobe: str = ""          # "" the same clothes; "over: ..." a layer on top; "replace: ..." other clothes
    screens: str = ""           # what every screen in the set shows (never text)
    outdoor: bool = False


GROUPS: Tuple[Tuple[str, str], ...] = (
    ("studio", "Studios and desks"),
    ("learning", "Learning and stories"),
    ("home", "Home and hands-on"),
    ("location", "On location"),
)

_HANDS_STANDING = "stands with arms relaxed and hands loosely together at waist height"

SETS: Tuple[SetSpec, ...] = (
    # ---- studios and desks
    SetSpec("studio", "Neutral studio", "A plain backdrop: fits any topic", "studio",
            "any topic; the safe choice when nothing else clearly fits",
            "in a clean, neutral studio",
            "a clean, modern video studio with a plain seamless backdrop in soft charcoal grey, a gentle glow of light "
            "on the backdrop behind the presenter, nothing else in the frame",
            f"{_HANDS_STANDING}, in front of the backdrop",
            "Soft, even key light from camera left with a gentle rim light from behind"),
    SetSpec("office", "Modern office", "A business desk, glass and plants", "studio",
            "business, marketing, careers, entrepreneurship, startups, management, real estate",
            "at a desk in a modern office",
            "a bright modern office: a clean wooden desk with a closed laptop and a plain ceramic mug, glass walls, "
            "green plants and a softly blurred open-plan office behind",
            "sits at the desk with forearms resting on it and hands loosely together and still",
            "Soft daylight from large windows on camera left"),
    SetSpec("tech_desk", "Tech desk", "Monitors and a home-office setup", "studio",
            "technology, AI, software, coding, gadgets, computers, gaming, the internet",
            "at a tech desk in a home office",
            "a tidy home-office tech setup: a desk with two large monitors and a keyboard behind the presenter, a "
            "soft LED glow on the wall, a small plant",
            "sits at the desk, turned to the camera, with forearms resting on the desk edge and hands loosely "
            "together and still",
            "Soft key light from camera left with a cool blue accent light on the wall",
            screens="The monitors show only soft abstract blue and purple shapes: no letters, code, numbers or logos."),
    SetSpec("podcast", "Podcast studio", "Microphones and a talk-show table", "studio",
            "commentary, interviews, opinion, sports talk, entertainment, film and TV, culture",
            "in a podcast studio",
            "a cosy podcast studio: dark acoustic foam panels on the wall, warm hanging bulbs, a wooden table, a "
            "professional broadcast microphone on a boom arm placed to one side of the presenter at chest height "
            "(never in front of the mouth), a second microphone across the table",
            "sits at the table with forearms resting on it and hands loosely together and still; the whole face and "
            "mouth are clearly visible beside the microphone",
            "Warm key light from camera left, soft practical light from the bulbs behind"),
    SetSpec("newsroom", "Newsroom desk", "An anchor desk and wall screens", "studio",
            "news, current events, politics, reports, announcements",
            "at a news-style anchor desk",
            "a modern TV-news-style studio set: a sleek curved anchor desk in dark wood and brushed metal, large wall "
            "screens behind, cool blue studio accents",
            "sits at the curved anchor desk with hands resting still on it",
            "Soft, even studio key light from camera left with a gentle warm fill",
            screens="The wall screens show a soft-focus aerial photo of a city skyline at dusk: no text, numbers, "
                    "logos or ticker."),
    SetSpec("trading_desk", "Finance desk", "Screens of abstract charts", "studio",
            "finance, investing, stocks, crypto, the economy, money, markets, banking",
            "at a finance desk",
            "a modern finance desk in a dark office: several large screens behind the presenter, city lights through "
            "the window",
            "sits at the desk with forearms resting on it and hands loosely together and still",
            "Soft key light from camera left, the screens' cool glow behind",
            screens="The screens show abstract line and candlestick charts in green and red, softly out of focus: no "
                    "letters, numbers, tickers or logos."),
    SetSpec("weather_studio", "Weather studio", "A big weather-map screen", "studio",
            "weather forecasts, climate, seasons, temperature, rain and drought explainers",
            "in a TV weather studio",
            "a TV weather studio: a very large wall screen behind the presenter, a sleek dark studio floor",
            "stands beside the big screen, body turned slightly toward it, face and eyes to the camera, hands loosely "
            "together at waist height",
            "Bright, even studio light from the front",
            screens="The big screen shows a generic coloured weather radar map - soft green, yellow and red rain bands "
                    "over plain land shapes - with no words, numbers, logos or station names."),
    # ---- learning and stories
    SetSpec("classroom", "Classroom", "A chalkboard and desks", "learning",
            "education, lessons, study tips, explainers, language, maths, school and university",
            "in a classroom",
            "a bright classroom: a large green chalkboard wiped clean with faint chalk dust (no writing), wooden desks, "
            "tall windows",
            f"{_HANDS_STANDING}, at the front of the room beside a wooden teacher's desk",
            "Soft daylight from tall windows on camera left"),
    SetSpec("library", "Library / study", "Old books, a globe, old maps: history", "learning",
            "history, biography, ancient worlds, wars, empires, philosophy, religion, myths, books and literature",
            "in a wood-panelled study",
            "a quiet wood-panelled study: floor-to-ceiling shelves of old leather-bound books with no readable titles, "
            "a brass desk lamp, an antique globe, a framed old map with no readable writing",
            "sits at a heavy wooden desk with forearms resting on it and hands loosely together and still",
            "Warm lamplight and soft window light from camera left"),
    SetSpec("dark_room", "Dark moody room", "Low light and pinned notes: true crime", "learning",
            "true crime, mysteries, unsolved cases, disappearances, conspiracies, the paranormal, scary stories",
            "in a dim, moody room",
            "a dim, moody study at night: a single desk lamp, a cork board behind with pinned photographs and paper "
            "notes joined by red string (all blurred, nothing readable), deep shadows",
            "sits at a desk lit by the lamp with forearms resting on it and hands loosely together and still",
            "Low-key light: one warm desk lamp from camera left, deep shadows, a faint cool fill"),
    SetSpec("science_lab", "Science lab", "Glassware and a microscope", "learning",
            "science, experiments, space, physics, chemistry, biology, nature facts, inventions",
            "in a science lab",
            "a clean modern science laboratory: glass beakers and flasks with coloured liquids, a microscope, white "
            "shelves",
            "stands at the lab bench with hands resting still on its edge",
            "Bright, even laboratory light with soft daylight from a window",
            wardrobe="over: a plain white lab coat with no badge or writing"),
    # ---- home and hands-on
    SetSpec("kitchen", "Kitchen", "A warm home kitchen", "home",
            "food, cooking, recipes, baking, kitchen tips, household thrift",
            "in a warm home kitchen",
            "a warm, lived-in home kitchen: open wooden shelves with plain stoneware and unlabelled glass jars, a worn "
            "wooden island, a window with thin white curtains, potted herbs on the sill",
            "stands behind the kitchen island with forearms resting on it and hands loosely together and still",
            "Soft morning window light from camera left"),
    SetSpec("workshop", "Workshop / garage", "Tools and a workbench", "home",
            "DIY, repairs, tools, woodworking, building, home improvement, homesteading, cars and engines",
            "in a workshop",
            "a tidy workshop and garage: a pegboard of hand tools, a long wooden workbench, shelves of unlabelled tins "
            "and jars of screws, a roll-up garage door letting in daylight",
            "stands at the workbench with hands resting still on its edge",
            "Cool daylight from the open door on camera left"),
    SetSpec("living_room", "Cozy living room", "A sofa, a lamp, a bookshelf", "home",
            "lifestyle, family, relationships, wellness, sleep, habits, motivation, storytime, home life",
            "in a cosy living room",
            "a cosy living room: a soft sofa with cushions and a knitted throw, a floor lamp with warm light, a "
            "bookshelf with plain books, plants, a window with soft daylight",
            "sits on the sofa, leaning forward slightly, forearms on the knees and hands loosely together",
            "Soft window light from camera left with a warm lamp glow"),
    SetSpec("gym", "Gym", "Weights and a training floor", "home",
            "fitness, workouts, strength training, running, sports performance",
            "in a gym",
            "a clean modern gym: racks of dumbbells, a squat rack and a rubber floor, large windows",
            _HANDS_STANDING,
            "Bright daylight from large windows with soft overhead light",
            wardrobe="replace: plain athletic clothes - a dark zip-up training jacket over a plain grey t-shirt, with "
                     "no logos"),
    SetSpec("car", "Car interior", "The driver's seat, filmed from the dash", "home",
            "cars, driving, road trips, commuting, vehicle reviews",
            "in the driver's seat of a parked car",
            "the driver's seat of a parked car, filmed from a small camera on the dashboard: the seat, the side window "
            "with a softly blurred tree-lined street outside",
            "sits in the driver's seat facing the camera, hands resting in the lap below the frame",
            "Soft daylight through the windscreen"),
    # ---- on location
    SetSpec("city_street", "City street", "On location in a city", "location",
            "cities, urban life, housing, local stories, street-level reporting",
            "on a city street",
            "a lively city street on location: shop fronts with no readable signs, people and traffic far behind and "
            "softly blurred, street trees",
            f"{_HANDS_STANDING}, on the pavement",
            "Soft daylight, slightly overcast",
            wardrobe="over: a plain dark jacket", outdoor=True),
    SetSpec("nature", "Nature / outdoors", "A forest trail and distant hills", "location",
            "nature, wildlife, the outdoors, hiking, national parks, rivers, mountains, gardening, the environment",
            "outdoors on a forest trail",
            "a quiet natural spot outdoors: a forest trail with tall trees and green ferns, soft dappled sunlight, "
            "distant hills",
            f"{_HANDS_STANDING}, on the trail",
            "Soft, dappled daylight",
            wardrobe="over: a plain outdoor jacket", outdoor=True),
    SetSpec("landmark", "Travel landmark", "A scenic old town, no famous building", "location",
            "travel, destinations, tourism, countries and cultures, places to visit",
            "at a scenic travel spot",
            "a scenic travel spot: an old arched stone bridge and old-town buildings far behind and softly out of "
            "focus, a few tourists far away, no readable signs, not any specific famous landmark",
            f"{_HANDS_STANDING}, with the view behind",
            "Warm late-afternoon sunlight",
            wardrobe="over: a plain light jacket", outdoor=True),
    SetSpec("storm", "Storm, on location", "Dark storm sky and wind", "location",
            "storms, hurricanes, tornadoes, floods, wildfires, disasters as they happen",
            "outdoors in stormy weather",
            "outdoors on location in rough weather: a dark, dramatic storm sky with heavy clouds, wind bending tall "
            "grass and trees behind, wet ground",
            _HANDS_STANDING,
            "Flat, cold storm light",
            wardrobe="over: a plain dark rain jacket, hood down", outdoor=True),
)
_BY_ID: Dict[str, SetSpec] = {s.id: s for s in SETS}


def spec(set_id: str) -> Optional[SetSpec]:
    return _BY_ID.get(str(set_id or ""))


def ids() -> List[str]:
    return [s.id for s in SETS]


def catalogue() -> List[Dict[str, Any]]:
    """What presenter_info gives the app: every set's id, label, hint, group and niches (no prompts)."""
    return [{"id": s.id, "label": s.label, "hint": s.hint, "group": s.group, "niches": s.niches, "outdoor": s.outdoor}
            for s in SETS]


# ------------------------------------------------------------------ "Describe a set"
def clean_description(raw: Any) -> str:
    """One line of plain text, at most MAX_DESCRIPTION characters (the app checks names and brands first)."""
    text = re.sub(r"[\x00-\x1f\x7f<>{}]+", " ", str(raw or ""))
    return " ".join(text.split())[:MAX_DESCRIPTION].strip()


def custom_id(description: str) -> str:
    """The same description is the same set (and the same cached pair): custom-<10 hex>."""
    key = " ".join(clean_description(description).lower().split())
    return f"{CUSTOM}-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:10]}"


_PREPOSITION = re.compile(r"^(in|on|at|inside|outside|by|near|under|beside|beneath|above|among|atop)\b", re.I)


def custom_spec(description: str) -> SetSpec:
    text = clean_description(description).rstrip(".")
    where = text if _PREPOSITION.match(text) else f"in {text}"
    return SetSpec(custom_id(text), "Your set", text[:60], "custom", text,
                   where if len(where) <= 90 else "in the place described",
                   f"{text}; no readable text, signs, logos or writing anywhere",
                   "is in this place in a natural position for it (standing or sitting), arms relaxed and hands loosely "
                   "together and still", "Natural light that suits the place")


# ------------------------------------------------------------------ auto: the rules
# (niche, set, weight, words). Whole words or phrases, lower case, ASCII. The app runs the same table
# (_shared/presenterSets.ts NICHES): change both together - the tests pin the same sample scripts on each side.
NICHES: Tuple[Tuple[str, str, float, str], ...] = (
    ("history", "library", 1.0,
     "history|historic|historical|historian|historians|ancient|century|centuries|medieval|empire|empires|emperor|"
     "emperors|dynasty|pharaoh|pharaohs|kingdom|kingdoms|kings|queens|monarchy|royal family|world war|civil war|"
     "battle|battles|revolution|colonial|colonists|archaeology|archaeologist|archaeologists|ruins|civilization|"
     "civilizations|civilisation|romans|roman empire|ancient greece|vikings|samurai|aztec|aztecs|egyptians|"
     "napoleon|crusades|treaty|middle ages|bronze age|iron age|founding fathers"),
    ("biography", "library", 0.8,
     "biography|was born|born in|grew up|his life|her life|life story|legacy|childhood|his early years|"
     "her early years|died in|passed away in"),
    ("ideas", "library", 0.8,
     "philosophy|philosopher|philosophers|religion|religious|bible|scripture|mythology|myth|myths|legend|legends|"
     "literature|novel|novels|poet|poetry|author|authors"),
    ("finance", "trading_desk", 1.0,
     "stock|stocks|stock market|shares|invest|investing|investor|investors|investment|investments|portfolio|"
     "dividend|dividends|crypto|cryptocurrency|bitcoin|ethereum|trading|trader|traders|recession|inflation|"
     "interest rate|interest rates|federal reserve|wall street|index fund|index funds|etf|etfs|bonds|economy|"
     "economic|economists|gdp|market crash|bull market|bear market|hedge fund|net worth|compound interest|"
     "savings account|retirement|401k|mortgage|mortgages|personal finance|wealth|millionaire|billionaire|"
     "banks|banking|money"),
    ("business", "office", 1.0,
     "business|businesses|company|companies|startup|startups|entrepreneur|entrepreneurs|ceo|founder|founders|"
     "marketing|sales|customers|clients|revenue|profit|profits|corporate|employees|employee|career|careers|"
     "job interview|resume|hiring|management|manager|managers|side hustle|freelance|freelancing|small business|"
     "real estate|negotiation|productivity|branding|e-commerce|ecommerce|linkedin"),
    ("tech", "tech_desk", 1.0,
     "technology|tech|artificial intelligence|ai|machine learning|chatbot|chatbots|software|app|apps|coding|code|"
     "programming|programmer|programmers|developer|developers|computer|computers|laptop|laptops|smartphone|"
     "smartphones|iphone|android|gadget|gadgets|chip|chips|semiconductor|semiconductors|robot|robots|robotics|"
     "internet|cybersecurity|hacker|hackers|algorithm|algorithms|silicon valley|startup tech|cloud computing|"
     "data center|data centers|tech giants"),
    ("gaming", "tech_desk", 1.0,
     "video game|video games|gaming|gamer|gamers|esports|console|consoles|playstation|xbox|nintendo|minecraft|"
     "fortnite|speedrun|speedrunner|streamer|streamers|twitch|game developer|boss fight|multiplayer|pc build"),
    ("true_crime", "dark_room", 1.0,
     "murder|murders|murdered|killer|killers|serial killer|crime|crimes|criminal|criminals|detective|detectives|"
     "investigators|cold case|unsolved|mystery|mysteries|mysterious|disappearance|disappeared|vanished|"
     "missing person|kidnapped|kidnapping|heist|robbery|conspiracy|conspiracies|paranormal|haunted|ghost|ghosts|"
     "cult|cults|suspect|suspects|the victim|victims|forensic|forensics|true crime|homicide|police said|"
     "the body was|crime scene"),
    ("travel", "landmark", 1.0,
     "travel|traveling|travelling|traveler|travelers|trip|trips|vacation|vacations|holiday|holidays|tourist|"
     "tourists|tourism|destination|destinations|itinerary|backpacking|sightseeing|landmark|landmarks|"
     "things to do|places to visit|abroad|passport|hotel|hotels|old town|travel guide|visit"),
    ("city", "city_street", 1.0,
     "city|cities|urban|downtown|neighborhood|neighbourhood|neighborhoods|streets|subway|commute|commuters|"
     "skyscraper|skyscrapers|housing crisis|rent prices|homelessness|city council|metropolis"),
    ("food", "kitchen", 1.0,
     "recipe|recipes|cook|cooking|cooked|bake|baking|baked|kitchen|food|foods|meal|meals|dinner|breakfast|lunch|"
     "ingredient|ingredients|chef|cuisine|dish|dishes|flavor|flavour|bbq|barbecue|grill|grilling|steak|beef|"
     "chicken|pork|bread|sourdough|soup|sauce|spices|cast iron|skillet|oven|pantry|canning|vegetables|dessert|"
     "butter|flour|eggs|meat|meats|butcher|butchers|sausage|sausages|bacon|beans|stew|chili|biscuits|gravy|"
     "potatoes|onions"),
    ("diy", "workshop", 1.0,
     "diy|repair|repairs|fix|fixing|tool|tools|woodworking|carpentry|drill|saw|garage|workshop|renovation|"
     "renovate|remodel|plumbing|plumber|leak|leaking|faucet|wiring|electrical|install|installing|homestead|"
     "homesteading|restore|restoration|mechanic|engine|workbench|lumber|screws|build a|built a"),
    ("fitness", "gym", 1.0,
     "workout|workouts|exercise|exercises|fitness|gym|muscle|muscles|strength training|cardio|weightlifting|"
     "lifting|squat|squats|deadlift|push-ups|pushups|protein|reps|sets of|personal trainer|bodybuilding|"
     "marathon|running|yoga|stretching|hiit|abs"),
    ("sports", "podcast", 0.9,
     "sports|sport|football|soccer|basketball|baseball|nfl|nba|mlb|nhl|tennis|golf|boxing|ufc|olympics|olympic|"
     "championship|championships|league|playoffs|world cup|super bowl|quarterback|striker|coach|coaches|"
     "the season|draft pick|transfer window|athletes|athlete|tournament|match|matches|scored"),
    ("talk", "podcast", 0.8,
     "podcast|episode|interview|interviews|conversation|commentary|opinion|debate|reaction|react to|hot take|"
     "let's talk|we talk|talk about|discussion|rant|movie|movies|film|films|tv show|tv series|netflix|"
     "celebrity|celebrities|album|music|song|songs|band|concert|anime|review"),
    ("science", "science_lab", 1.0,
     "science|scientist|scientists|scientific|experiment|experiments|laboratory|lab|researchers|physics|"
     "chemistry|biology|molecule|molecules|atom|atoms|dna|gene|genes|genetic|cell|cells|quantum|space|nasa|"
     "planet|planets|galaxy|galaxies|universe|black hole|black holes|astronomy|astronomers|telescope|rocket|"
     "rockets|evolution|fossil|fossils|dinosaur|dinosaurs|invention|inventions|inventor|particle|particles|"
     "neuroscience"),
    ("health", "living_room", 0.9,
     "health|healthy|sleep|sleeping|insomnia|stress|anxiety|mental health|wellness|well-being|wellbeing|diet|"
     "nutrition|vitamin|vitamins|doctor|doctors|disease|symptoms|immune|heart health|blood pressure|"
     "cholesterol|weight loss|meditation|mindfulness|therapy|burnout|self-care"),
    ("lifestyle", "living_room", 0.7,
     "family|families|parenting|parents|toddler|kids|children|relationship|relationships|marriage|dating|"
     "lifestyle|habits|habit|morning routine|routine|self-improvement|motivation|mindset|happiness|minimalism|"
     "declutter|decluttering|organize|organizing|cleaning|home decor|cozy|storytime|story time|life lessons"),
    ("education", "classroom", 1.0,
     "lesson|lessons|learn|learning|teach|teacher|teachers|teaching|student|students|school|schools|classroom|"
     "university|college|exam|exams|study tips|studying|homework|course|courses|lecture|grammar|math|maths|"
     "algebra|geometry|vocabulary|language learning|spelling|reading skills|the test"),
    ("news", "newsroom", 1.0,
     "news|breaking|breaking news|reported|reporting|reporters|announced|announcement|government|governments|"
     "president|prime minister|election|elections|vote|voters|congress|senate|parliament|politics|political|"
     "politicians|policy|policies|lawmakers|minister|officials|according to|headlines|white house|"
     "supreme court|campaign|bill|legislation|sanctions|ceasefire|press conference"),
    ("weather", "weather_studio", 1.0,
     "weather|forecast|forecasts|forecasters|meteorologist|meteorologists|meteorology|temperature|temperatures|"
     "heat wave|heatwave|cold front|warm front|rainfall|snowfall|humidity|climate|climate change|drought|"
     "droughts|el nino|la nina|jet stream|radar|degrees|precipitation|cold snap|frost|polar vortex|"
     "weather service|seasonal outlook"),
    ("storm", "storm", 1.0,
     "storm|storms|hurricane|hurricanes|tornado|tornadoes|cyclone|typhoon|blizzard|flood|floods|flooding|"
     "flash flood|landfall|evacuation|evacuations|evacuate|damage|devastation|wildfire|wildfires|lightning|"
     "hail|storm surge|category 4|category 5|emergency"),
    ("nature", "nature", 1.0,
     "nature|wildlife|animal|animals|forest|forests|mountain|mountains|river|rivers|lake|lakes|ocean|oceans|"
     "national park|national parks|hiking|hike|camping|trail|trails|wilderness|birds|bears|wolves|whales|"
     "garden|gardening|plants|trees|canyon|canyons|desert|deserts|volcano|volcanoes|waterfall|waterfalls|"
     "ecosystem|ecosystems|environment|conservation|species"),
    ("cars", "car", 1.0,
     "car|cars|driving|driver|drivers|road trip|vehicle|vehicles|truck|trucks|suv|suvs|electric vehicle|"
     "electric vehicles|ev|evs|horsepower|mpg|dealership|highway|test drive|sedan|pickup truck|car review"),
)
# Old years read as history (1000-1949): half a word's weight each, as the words.
HISTORY_YEARS = re.compile(r"\b(1[0-8]\d\d|19[0-4]\d)s?\b", re.A)
YEAR_WEIGHT = 0.5
TITLE_WEIGHT = 3.0
CAP_PER_WORD = 3              # one word said thirty times counts three times
MIN_SCORE = 3.0               # at least about three hits (or one in the title) to be sure
LEAD = 1.4                    # and the best set at least this many times the next


def _norm(text: str) -> str:
    """Lower case, straight apostrophes, hyphens and dashes as spaces ("cast-iron" reads "cast iron")."""
    text = re.sub("[‘’ʼ]", "'", str(text or ""))
    return re.sub("[‐-―-]", " ", text).lower()


def _words_pattern(words: str) -> "re.Pattern[str]":
    parts = sorted({_norm(w).strip() for w in words.split("|") if w.strip()}, key=lambda w: (-len(w), w))
    return re.compile(r"\b(?:" + "|".join(re.escape(w) for w in parts) + r")\b", re.A)


_RULES: List[Tuple[str, str, float, "re.Pattern[str]"]] = [(n, s, w, _words_pattern(words)) for n, s, w, words in NICHES]


def _hits(pattern: "re.Pattern[str]", text: str) -> float:
    counts: Dict[str, int] = {}
    for m in pattern.finditer(text):
        counts[m.group(0)] = counts.get(m.group(0), 0) + 1
    return float(sum(min(c, CAP_PER_WORD) for c in counts.values()))


def scores(title: str = "", text: str = "") -> Dict[str, float]:
    """Every set's score for a title and a script (only the sets that scored)."""
    t, s = _norm(title), _norm(text)
    out: Dict[str, float] = {}
    for _niche, set_id, weight, pattern in _RULES:
        got = weight * (TITLE_WEIGHT * _hits(pattern, t) + _hits(pattern, s))
        if got:
            out[set_id] = out.get(set_id, 0.0) + got
    years = YEAR_WEIGHT * (TITLE_WEIGHT * _hits(HISTORY_YEARS, t) + _hits(HISTORY_YEARS, s))
    if years:
        out["library"] = out.get("library", 0.0) + years
    return {k: round(v, 3) for k, v in out.items()}


def rule_pick(title: str = "", text: str = "") -> Tuple[Optional[str], Dict[str, float]]:
    """(the set the rules are sure of, or None; the scores)."""
    sc = scores(title, text)
    ranked = sorted(sc.items(), key=lambda kv: (-kv[1], ids().index(kv[0])))
    if not ranked or ranked[0][1] < MIN_SCORE:
        return None, sc
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    if ranked[0][1] >= LEAD * second:
        return ranked[0][0], sc
    return None, sc


# ------------------------------------------------------------------ auto: the model, when the rules are unsure
CHOOSE_PROMPT = """You pick where a YouTube presenter is filmed for one video. The sets:
{sets}
Video title: {title}
Start of the script:
{text}

Pick the ONE set whose place best fits what this video is about (its topic and niche, not a single word in it).
If no set clearly fits, pick "studio". Reply with JSON only: {{"set": "<id>", "confidence": 0.0}}"""


def model_pick(title: str, text: str, provider, budget=None) -> Tuple[Optional[str], Dict[str, Any]]:
    """(a set id the model is sure of, or None; what happened). Never raises: a failed call is "unsure"."""
    info: Dict[str, Any] = {"model": CHOOSE_MODEL}
    if provider is None or not getattr(provider, "available", lambda: False)():
        info["error"] = "no provider"
        return None, info
    listing = "\n".join(f"- {s.id}: {s.label} - {s.niches}" for s in SETS)
    words = str(text or "").split()
    prompt = CHOOSE_PROMPT.format(sets=listing, title=str(title or "")[:200] or "(none)",
                                  text=" ".join(words[:700])[:4500] or "(none)")
    ticket = None
    if budget is not None:
        from .budget import BudgetExceeded
        try:
            ticket = budget.reserve(CHOOSE_USD, "set:choose")
        except BudgetExceeded as e:
            info["error"] = f"budget: {e}"
            return None, info
    try:
        res = provider.chat(CHOOSE_MODEL, [{"role": "user", "content": prompt}], json_mode=True, max_tokens=120,
                            timeout=45)
    except Exception as e:  # noqa: BLE001 - the neutral studio instead
        if budget is not None and ticket is not None:
            budget.release(ticket, str(e)[:120])
        info["error"] = f"{type(e).__name__}: {str(e)[:120]}"
        return None, info
    if budget is not None and ticket is not None:
        info["usd"] = budget.settle(ticket, res.cost, model=CHOOSE_MODEL, kind="set", label="set:choose")
    else:
        info["usd"] = float(res.cost or 0.0)
    try:
        from .checks import _parse
        got = _parse(res.text) or {}
        sid = str(got.get("set") or "").strip().lower()
        conf = float(got.get("confidence") or 0.0)
    except (TypeError, ValueError):
        sid, conf = "", 0.0
    info.update({"answer": sid, "confidence": conf})
    if sid in _BY_ID and conf >= 0.5:
        return sid, info
    return None, info


# ------------------------------------------------------------------ the job's request and the choice
def request_of(raw: Any) -> Optional[Dict[str, Any]]:
    """
    The job's set, normalised: {"id": "auto" | <set id> | "home" | "custom", "description", "images",
    "regenerate"}; None when the job names none (the kit's own set, as before sets existed). A string is the id;
    an unknown id reads as "auto".
    """
    if raw is None or raw is False or raw == "":
        return None
    if isinstance(raw, str):
        raw = {"id": raw}
    if not isinstance(raw, dict):
        return None
    sid = str(raw.get("id") or raw.get("set") or "").strip().lower()
    desc = clean_description(raw.get("description") or raw.get("describe") or "")
    if sid in (HOME, "own", "kit", "none", "default"):
        return {"id": HOME}
    if sid == CUSTOM or sid.startswith(CUSTOM + "-") or (not sid and desc):
        if len(desc) < 3:
            return {"id": "auto"}
        return {"id": CUSTOM, "description": desc, "regenerate": raw.get("regenerate") is True,
                "images": _images_of(raw)}
    if sid not in _BY_ID:
        sid = "auto"
    # A pair the job brings belongs to the set it names: never to whatever auto picks.
    return {"id": sid, "regenerate": raw.get("regenerate") is True,
            "images": _images_of(raw) if sid != "auto" else {}}


def _images_of(raw: dict) -> Dict[str, str]:
    imgs = raw.get("images") if isinstance(raw.get("images"), dict) else {}
    out = {k: str(imgs.get(k) or "").strip() for k in ("master", "closeup")}
    return out if all(v.startswith("https://") for v in out.values()) else {}


@dataclass
class Choice:
    id: str                         # a catalogue id, "home" or custom-<hash>
    how: str                        # asked | rules | model | default | home
    spec: Optional[SetSpec] = None
    scores: Dict[str, float] = field(default_factory=dict)
    model: Dict[str, Any] = field(default_factory=dict)
    asked: str = ""                 # what the job asked for (auto, a set id, home, custom)
    home_match: str = ""            # the catalogue id the pick matched the kit's own set on

    @property
    def is_home(self) -> bool:
        return self.id == HOME

    def report(self) -> Dict[str, Any]:
        top = dict(sorted(self.scores.items(), key=lambda kv: -kv[1])[:4])
        out = {"id": self.id, "how": self.how, "asked": self.asked, "label": self.spec.label if self.spec else
               ("The presenter's own set" if self.is_home else ""), "scores": top}
        if self.home_match:
            out["homeMatch"] = self.home_match
        if self.model:
            out["model"] = {k: v for k, v in self.model.items() if k in ("model", "answer", "confidence", "usd", "error")}
        if self.spec is not None and self.spec.group == "custom":
            out["description"] = self.spec.niches
        return out


def home_of(kit: Optional[dict]) -> str:
    """The catalogue id the kit's own pictures show (its "home_set"; else read from its room when the rules are
    sure); "" when unknown."""
    if not kit:
        return ""
    given = str(kit.get("home_set") or "").strip().lower()
    if given in _BY_ID:
        return given
    room = " ".join(str(kit.get(k) or "") for k in ("room", "camera"))
    world = kit.get("world") if isinstance(kit.get("world"), dict) else {}
    room = f"{room} {world.get('place') or ''}"
    # A room is a sentence or two: one clear word ("kitchen", "workshop") ahead of the rest is enough.
    ranked = sorted(scores("", room).items(), key=lambda kv: (-kv[1], ids().index(kv[0])))
    if not ranked or ranked[0][1] < 1.0:
        return ""
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    return ranked[0][0] if ranked[0][1] >= LEAD * second else ""


def choose(req: Optional[Dict[str, Any]], kit: Optional[dict], *, title: str = "", text: str = "",
           provider=None, budget=None, allow_model: bool = True) -> Choice:
    """
    What the job gets: the kit's own set (no request, or "home"), the set it asked for, a described one, or
    auto (rules, then the model when they are unsure, then the neutral studio). Any pick equal to the kit's own
    home set is the kit's own set (its pictures are free).
    """
    home = home_of(kit)
    if req is None or req.get("id") == HOME:
        return Choice(HOME, "home", asked=(req or {}).get("id", ""))
    if req["id"] == CUSTOM:
        sp = custom_spec(req.get("description") or "")
        return Choice(sp.id, "asked", sp, asked=CUSTOM)
    if req["id"] != "auto":
        if req["id"] == home:
            return Choice(HOME, "home", asked=req["id"], home_match=home)
        return Choice(req["id"], "asked", _BY_ID[req["id"]], asked=req["id"])
    pick, sc = rule_pick(title, text)
    how, minfo = "rules", {}
    if pick is None and allow_model and (title or text):
        pick, minfo = model_pick(title, text, provider, budget)
        how = "model"
    if pick is None:
        pick, how = DEFAULT_SET, "default"
    if pick == home:
        return Choice(HOME, "home", scores=sc, model=minfo, asked="auto", home_match=home)
    return Choice(pick, how, _BY_ID[pick], scores=sc, model=minfo, asked="auto")


# ------------------------------------------------------------------ the pictures' prompts
PHOTO = ("Photorealistic, unretouched photograph, not a render or illustration. Natural skin texture with visible "
         "pores, fine lines and uneven tone; a few loose flyaway hairs catching the light; slightly uneven natural "
         "teeth; no makeup look. Gentle light falloff. Full-frame camera, 50 mm lens at f/2.0, focus on the eyes, the "
         "background softly out of focus but recognisable. Very fine film grain, true-to-life colour.")
CLEAN = ("Plain unbranded clothing: no logos, brand patches, labels or writing on it. No text anywhere in the "
         "picture: no readable signs, posters, packaging, labels, book titles, screens or writing.")
FACE = "Glasses only if the person in image 1 wears them. No hands near the face, nothing in front of the face."
FULL = "Full-bleed photo that fills the whole 16:9 frame edge to edge: no black bars, borders or letterboxing. 16:9."
SAME_FIX = ("Important: it must be unmistakably the same person as image 1 - the same face shape, eyes, nose, mouth, "
            "skin, age, hair and facial hair; only the place, the light and the camera change.")


def clothes_line(kit: dict, sp: SetSpec) -> str:
    """What the presenter wears in the set: the kit's clothes, a light layer over them, or (a gym) other clothes."""
    own = str(kit.get("wardrobe") or "").strip().rstrip(".")
    base = f"the same clothes as in image 1 ({own})" if own else "the same clothes as in image 1"
    mode, _, what = sp.wardrobe.partition(": ")
    if mode == "over" and what:
        return f"{base}, with {what} over them"
    if mode == "replace" and what:
        return what
    return base


def wardrobe_for(kit: dict, sp: SetSpec) -> str:
    """The kit's wardrobe line in the set (the in-shot stills draw the presenter in it)."""
    own = str(kit.get("wardrobe") or "").strip().rstrip(".")
    mode, _, what = sp.wardrobe.partition(": ")
    if mode == "over" and what:
        return f"{own}, with {what} over it" if own else what
    if mode == "replace" and what:
        return what
    return own


def master_prompt(kit: dict, sp: SetSpec, retry: bool = False) -> str:
    parts = [
        "Image 1 is a photo of a presenter. Make a new photograph of exactly this same person, now filmed in a "
        "different place: keep their face, facial features, skin tone and texture, age, hair, facial hair and build "
        "exactly as in image 1, so they are instantly recognisable. Do not copy image 1's background, framing or "
        "light.",
        SAME_FIX if retry else "",
        "Medium shot video frame from the waist up, eye level, camera about 1.6 m away, the presenter in the centre "
        f"of the frame with comfortable headroom. The presenter {sp.stance} and speaks straight into the lens: mouth "
        "slightly open mid-word, a calm, warm expression, eyes on the lens.",
        f"They wear {clothes_line(kit, sp)}.",
        f"The place, behind them and softly out of focus: {sp.room}.",
        sp.screens, f"{sp.light}.", FACE, PHOTO, CLEAN, FULL,
    ]
    return " ".join(p for p in parts if p)


def closeup_prompt(kit: dict, sp: SetSpec, retry: bool = False) -> str:
    parts = [
        "Image 1 is the presenter in this place; image 2 is the same person somewhere else (use it only for their "
        "face). Closer framing from mid-chest up, from the same direction as image 1: head, shoulders and upper chest "
        "in frame with comfortable headroom, the top of the head fully inside the frame; the face fills about 40% of "
        "the frame height - a medium close-up, not an extreme close-up. The presenter in the centre of the frame, "
        "looking straight into the lens with a warm, calm expression, eyes open and clear, mouth slightly open "
        "mid-word.",
        SAME_FIX if retry else "",
        f"Exactly the same person, clothes ({clothes_line(kit, sp)}), place and light as image 1; the place behind "
        "more softly out of focus (85 mm lens, f/2.0). Hands out of frame.",
        sp.screens, FACE, PHOTO, CLEAN, FULL,
    ]
    return " ".join(p for p in parts if p)


SAME_PROMPT = """Picture 1 is a reference photo of a person. Picture 2 is a new photo that must show exactly the same \
person in another place. Check it like a casting director:
- same_person: 0-1, is it clearly the same individual (face shape, eyes, nose, mouth, age, skin, hair, facial hair)?
- natural: 0-1, does it look like a real, natural photograph (no warped or doubled features, no extra fingers)?
- issues: a list from different_person, warped_face, extra_person, bad_hands, readable_text, other (empty when fine).
Reply with JSON only: {"same_person": 0.0, "natural": 0.0, "issues": []}"""


def same_person(checker, reference: str, picture: str, stem: str) -> Dict[str, Any]:
    """The new picture against the person it must show (a vision call, ~$0.0006). A check that cannot run passes."""
    if checker is None:
        return {"ok": True, "checked": False}
    try:
        ref = checker._small(reference, f"{stem}_ref", 640)
        pic = checker._small(picture, f"{stem}_new", 768)
        got = checker._ask(SAME_PROMPT, [ref, pic], stem)
    except Exception as e:  # noqa: BLE001 - a check never costs the picture
        return {"ok": True, "checked": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}
    if got is None:
        return {"ok": True, "checked": False}

    def f(v, d=0.5):
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return d
    same, natural = f(got.get("same_person")), f(got.get("natural"))
    issues = sorted({str(i).strip().lower() for i in got.get("issues") or [] if str(i).strip()})
    ok = same >= 0.7 and natural >= 0.6 and not ({"extra_person"} & set(issues) and same < 0.9)
    return {"ok": ok, "checked": True, "samePerson": same, "natural": natural, "issues": issues,
            "model": got.get("_model")}


# ------------------------------------------------------------------ where the pairs are kept (R2)
class SetStore:
    """The R2 side of the cache (src/r2.py): JSON read/write and file uploads. Tests give a fake."""

    def enabled(self) -> bool:
        from .. import r2
        return r2.enabled()

    def get_json(self, key: str) -> Optional[dict]:
        from .. import r2
        try:
            raw = r2.get_bytes(key, timeout=20)
        except Exception:  # noqa: BLE001 - a cache miss
            return None
        if not raw:
            return None
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def put_json(self, key: str, data: dict) -> str:
        from .. import r2
        return r2.upload_bytes(json.dumps(data, indent=1).encode("utf-8"), key, content_type="application/json",
                               deadline=time.time() + 60, cache_control="no-cache")

    def put_file(self, local: str, key: str) -> str:
        from .. import r2
        return r2.upload(local, r2.tokened(key), content_type=r2.content_type(local),
                         deadline=time.time() + config.R2_MEDIA_UPLOAD_SECONDS, cache_control=r2.IMMUTABLE)


def folder_for(kit: dict) -> str:
    """
    The R2 folder of the kit's sets: beside the kit's master on our bucket (presenters/<id>/sets for a library
    presenter, presenters/user/<uid>/<id>/sets for a user's own), else one named by the kit and its master.
    """
    from .. import r2
    from . import kits as _kits
    master = str(kit.get("identity_master") or kit.get("master") or "")
    url = _kits.link(kit, master) or master
    loc = r2.locate(url) if url.startswith("http") else None
    if loc and loc[0] == config.R2_BUCKET and "/" in loc[1]:
        return f"{loc[1].rsplit('/', 1)[0]}/sets"
    safe = re.sub(r"[^a-z0-9-]+", "-", str(kit.get("id") or "kit").lower()).strip("-")[:40] or "kit"
    return f"presenters/_other/{safe}-{hashlib.sha1(url.encode('utf-8')).hexdigest()[:10]}/sets"


@dataclass
class Pair:
    set_id: str
    label: str
    master_url: str
    closeup_url: str
    master_preview: str = ""
    closeup_preview: str = ""
    cached: str = ""                # "" made now | "r2" | "job" (the job brought it)
    usd: float = 0.0
    folder: str = ""
    checks: Dict[str, Any] = field(default_factory=dict)
    made_at: str = ""

    def report(self) -> Dict[str, Any]:
        return {"set": self.set_id, "label": self.label, "master": self.master_url, "closeup": self.closeup_url,
                "masterPreview": self.master_preview, "closeupPreview": self.closeup_preview,
                "cached": self.cached, "usd": round(self.usd, 4), "folder": self.folder, "checks": self.checks,
                "madeAt": self.made_at}


class SetError(RuntimeError):
    """The pair could not be had (budget, model, checks, storage)."""


def _identity_master(kit: dict) -> str:
    from . import kits as _kits
    ref = str(kit.get("identity_master") or kit.get("master") or "")
    return _kits.link(kit, ref) or ref


def ensure(kit: dict, choice: Choice, *, provider, budget, work: str, checker=None,
           store: Optional[SetStore] = None, regenerate: bool = False, given: Optional[Dict[str, str]] = None,
           sleep: Callable[[float], None] = time.sleep, log: Callable[[str], None] = print) -> Pair:
    """The presenter in the chosen set: the pair the job brought, the R2 cache's, or two new pictures."""
    sp = choice.spec
    if sp is None:
        raise SetError("no set to make")
    if given and all(str(given.get(k) or "").startswith("https://") for k in ("master", "closeup")):
        return Pair(sp.id, sp.label, given["master"], given["closeup"], cached="job")
    store = store if store is not None else SetStore()
    durable = store.enabled()
    folder = f"{folder_for(kit)}/{sp.id}"
    made_from = _identity_master(kit)
    if durable and not regenerate:
        hit = _cached(store, folder, made_from, sleep=sleep, log=log)
        if hit is not None:
            return Pair(sp.id, sp.label, hit["images"]["master"], hit["images"]["closeup"],
                        hit["images"].get("master_1280", ""), hit["images"].get("closeup_1280", ""), cached="r2",
                        folder=folder, checks=hit.get("checks") or {}, made_at=str(hit.get("made_at") or ""))
        try:
            store.put_json(f"{folder}/set.json", {"version": 1, "status": "making", "set": sp.id, "at": time.time(),
                                                  "made_from": made_from})
        except Exception as e:  # noqa: BLE001 - the claim is only a courtesy to a parallel job
            log(f"[sets] claim on {folder} not written: {type(e).__name__}")
    try:
        pair = _make(kit, sp, provider=provider, budget=budget, work=work, checker=checker, log=log)
    except Exception:
        if durable:
            try:        # a parallel job must not wait on a pair nobody is making any more
                store.put_json(f"{folder}/set.json", {"version": 1, "status": "failed", "set": sp.id,
                                                      "at": time.time(), "made_from": made_from})
            except Exception:  # noqa: BLE001
                pass
        raise
    pair.folder = folder
    if durable:
        _keep(store, kit, sp, choice, pair, made_from, work, log)
    return pair


def _cached(store: SetStore, folder: str, made_from: str, *, sleep, log) -> Optional[dict]:
    """The folder's ready pair (made from this master), waiting a while when another job is making it."""
    waited = 0.0
    while True:
        m = store.get_json(f"{folder}/set.json")
        if not m:
            return None
        if m.get("status") == "ready" and isinstance(m.get("images"), dict) \
                and all(str(m["images"].get(k) or "").strip() for k in ("master", "closeup")):
            if m.get("made_from") and made_from and m.get("made_from") != made_from:
                log(f"[sets] {folder}: made from an older master - made again")
                return None
            return m
        making = m.get("status") == "making" and time.time() - float(m.get("at") or 0) < CLAIM_SECONDS
        if not making or waited >= CLAIM_WAIT_SECONDS:
            return None
        log(f"[sets] {folder}: another job is making it - waiting")
        sleep(10.0)
        waited += 10.0


def _picture(provider, budget, *, prompt: str, refs: List[str], label: str):
    from .budget import BudgetExceeded
    from .providers import ImageRequest, ProviderError
    ticket = budget.reserve(round(PICTURE_USD * 1.25, 4), label)
    try:
        res = provider.image(ImageRequest(model=SET_MODEL, prompt=prompt, size=SET_SIZE, aspect_ratio="16:9",
                                          references=refs))
    except ProviderError as e:
        if e.billed:
            budget.settle(ticket, None, model=SET_MODEL, kind="set", label=label, error=str(e)[:120])
        else:
            budget.release(ticket, str(e))
        raise
    except BudgetExceeded:
        budget.release(ticket, "budget")
        raise
    usd = budget.settle(ticket, res.cost, model=SET_MODEL, kind="set", label=label, seconds=res.seconds)
    return res, usd


def _make(kit: dict, sp: SetSpec, *, provider, budget, work: str, checker, log) -> Pair:
    """Two pictures with their checks (each retried once with a stronger same-person line)."""
    from . import kits as _kits
    from . import media_io
    from .. import costs
    from .checks import still_problems
    from .providers import data_url_for
    folder = os.path.join(work, "sets", sp.id)
    os.makedirs(folder, exist_ok=True)
    ident_local = _kits.fetch(kit, str(kit.get("identity_master") or kit["master"]), os.path.join(work, "kit"))
    ident_link = _identity_master(kit)
    if not ident_link.startswith("https://"):
        ident_link = data_url_for(media_io.to_jpeg(ident_local, os.path.join(folder, "identity.jpg"), width=1536,
                                                   quality=92))
    usd = 0.0
    checks: Dict[str, Any] = {}
    out: Dict[str, str] = {}
    for role in ("master", "closeup"):
        try:
            for attempt in range(2):
                prompt = (master_prompt if role == "master" else closeup_prompt)(kit, sp, retry=attempt > 0)
                refs = [ident_link] if role == "master" else [out["master_ref"], ident_link]
                res, cost = _picture(provider, budget, prompt=prompt, refs=refs, label=f"set:{sp.id}:{role}")
                usd += cost
                costs.record("image.usd", cost)
                costs.record("image.presenter_set.usd", cost)
                costs.record("image.presenter_set.calls")
                raw = os.path.join(folder, f"{role}_{attempt}{res.ext or '.png'}")
                with open(raw, "wb") as fh:
                    fh.write(res.data)
                problems = still_problems(raw, min_width=1200)
                verdict = {"ok": not problems, "problems": problems} if problems else \
                    same_person(checker, ident_local, raw, f"set_{sp.id}_{role}_{attempt}")
                checks[f"{role}{attempt}"] = verdict
                log(f"[sets] {sp.id} {role} try {attempt + 1}: ${cost:.3f} "
                    f"{'ok' if verdict.get('ok') else 'rejected'} {verdict.get('samePerson', '')}")
                if verdict.get("ok"):
                    out[role] = raw
                    out[f"{role}_ref"] = data_url_for(media_io.to_jpeg(raw, os.path.join(folder, f"{role}_ref.jpg"),
                                                                       width=1536, quality=92))
                    break
        except Exception as e:  # noqa: BLE001 - the main picture is the set; a missing close-up is not
            if role == "master":
                raise
            checks["closeupError"] = f"{type(e).__name__}: {str(e)[:160]}"
        if role not in out:
            if role == "master":
                raise SetError(f"the main picture in '{sp.id}' failed its checks twice")
            # The main camera alone films every take: the set is had, only the second camera is missing.
            log(f"[sets] {sp.id}: no close-up - the main camera films every take")
            out["closeup"] = out["master"]
            checks["closeupFallback"] = "the main camera"
    return Pair(sp.id, sp.label, out["master"], out["closeup"], usd=usd, checks=checks)


def _keep(store: SetStore, kit: dict, sp: SetSpec, choice: Choice, pair: Pair, made_from: str, work: str,
          log) -> None:
    """Upload the pair (originals + 1280-px previews), then its set.json and the kit's sets/index.json."""
    from . import media_io
    urls: Dict[str, str] = {}
    try:
        for role, local in (("master", pair.master_url), ("closeup", pair.closeup_url)):
            if role == "closeup" and local == pair.master_url:
                urls["closeup"], urls["closeup_1280"] = urls["master"], urls["master_1280"]
                continue
            ext = os.path.splitext(local)[1] or ".png"
            urls[role] = store.put_file(local, f"{pair.folder}/{role}{ext}")
            prev = media_io.to_jpeg(local, os.path.join(work, "sets", sp.id, f"{role}_1280.jpg"), width=1280,
                                    quality=88)
            urls[f"{role}_1280"] = store.put_file(prev, f"{pair.folder}/{role}_1280.jpg")
    except Exception as e:  # noqa: BLE001 - the job still uses its local pair; the next one makes it again
        log(f"[sets] {sp.id}: upload failed ({type(e).__name__}: {str(e)[:120]}); not cached")
        return
    pair.master_url, pair.closeup_url = urls["master"], urls["closeup"]
    pair.master_preview, pair.closeup_preview = urls["master_1280"], urls["closeup_1280"]
    pair.made_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    manifest = {"version": 1, "status": "ready", "set": sp.id, "label": sp.label, "kit": kit.get("id"),
                "made_from": made_from, "prompt_version": PROMPT_VERSION, "model": SET_MODEL, "size": SET_SIZE,
                "usd": round(pair.usd, 4), "made_at": pair.made_at, "images": urls,
                "checks": pair.checks, "how": choice.how,
                **({"description": sp.niches} if sp.group == "custom" else {})}
    try:
        store.put_json(f"{pair.folder}/set.json", manifest)
        index_key = f"{pair.folder.rsplit('/', 1)[0]}/index.json"
        index = store.get_json(index_key) or {}
        rows = index.get("sets") if isinstance(index.get("sets"), dict) else {}
        # The originals and the master they were drawn from too: the app may send a ready pair inline with the job
        # ("images"), when made_from is still the presenter's master.
        rows[sp.id] = {"label": sp.label, "master": urls["master"], "closeup": urls["closeup"],
                       "master_1280": urls["master_1280"], "closeup_1280": urls["closeup_1280"],
                       "made_from": made_from, "made_at": pair.made_at,
                       **({"description": sp.niches} if sp.group == "custom" else {})}
        store.put_json(index_key, {"version": 1, "kit": kit.get("id"), "sets": rows})
    except Exception as e:  # noqa: BLE001
        log(f"[sets] {sp.id}: set.json/index.json not written ({type(e).__name__})")


# ------------------------------------------------------------------ the kit in the set
def apply(kit: dict, choice: Choice, pair: Pair) -> dict:
    """The kit with the set's two pictures as its framings; the home set's plates and task picture go."""
    sp = choice.spec
    k = dict(kit)
    k["identity_master"] = str(kit.get("identity_master") or kit.get("master") or "")
    k["master"] = pair.master_url
    k["framings"] = [
        {"id": "master", "url": pair.master_url, "shot": "medium shot", "set": sp.id, "face_x": 0.5},
        {"id": "closeup", "url": pair.closeup_url, "shot": "medium close-up", "set": sp.id, "face_x": 0.5},
    ]
    k["sets"] = []
    world = dict(kit.get("world") or {})
    world["place"] = sp.room
    k["world"] = world
    k["wardrobe"] = wardrobe_for(kit, sp)
    k["set_where"] = sp.where
    k["filming_set"] = {"id": sp.id, "label": sp.label, "where": sp.where, "outdoor": sp.outdoor,
                        "how": choice.how, "cached": pair.cached}
    return k


# ------------------------------------------------------------------ one job's set
class SetJob:
    """
    One job's set: chosen (choose), found or made (run - in the caller's background thread), applied (kit).
    Any failure keeps the kit's own set, with a warning: the presenter still appears.
    """

    def __init__(self, kit: dict, raw_request: Any, *, provider=None, budget=None, work: str = "",
                 checker=None, store: Optional[SetStore] = None, log: Callable[[str], None] = print):
        self.home_kit = kit
        self.req = request_of(raw_request)
        self.provider, self.budget, self.work, self.checker = provider, budget, work, checker
        self.store = store
        self.log = log
        self.choice: Optional[Choice] = None
        self.pair: Optional[Pair] = None
        self.error = ""
        self.cached_hint: Optional[bool] = None
        self.kit = kit
        self.seconds = 0.0
        self._done = threading.Event()

    @property
    def requested(self) -> bool:
        return self.req is not None

    def choose(self, *, title: str = "", text: str = "", allow_model: bool = True) -> Choice:
        if self.choice is None:
            self.choice = choose(self.req, self.home_kit, title=title, text=text, provider=self.provider,
                                 budget=self.budget, allow_model=allow_model)
            self.log(f"[sets] set: {self.choice.id} ({self.choice.how}"
                     f"{', asked ' + self.choice.asked if self.choice.asked else ''})")
        return self.choice

    def needs_pair(self) -> bool:
        return self.choice is not None and not self.choice.is_home

    def maybe_cached(self) -> bool:
        """Is the pair already somewhere (brought by the job, or ready in the R2 cache)? Read once, cheaply."""
        if not self.needs_pair():
            return True
        if self.cached_hint is None:
            given = (self.req or {}).get("images") or {}
            if given:
                self.cached_hint = True
            else:
                store = self.store if self.store is not None else SetStore()
                try:
                    folder = f"{folder_for(self.home_kit)}/{self.choice.spec.id}"
                    m = store.get_json(f"{folder}/set.json") if store.enabled() else None
                except Exception:  # noqa: BLE001
                    m = None
                self.cached_hint = bool(m and m.get("status") == "ready"
                                        and (not m.get("made_from") or m.get("made_from") == _identity_master(
                                            self.home_kit))
                                        and not (self.req or {}).get("regenerate"))
        return bool(self.cached_hint)

    def extra_budget(self) -> float:
        """What the job's cap must add for the pair (0 when it is cached or not needed)."""
        return 0.0 if self.maybe_cached() else PAIR_PROJECTED_USD

    def run(self) -> dict:
        """Find or make the pair and apply it (idempotent); returns the kit to use."""
        if self._done.is_set():
            return self.kit
        t0 = time.time()
        try:
            if self.needs_pair():
                self.pair = ensure(self.home_kit, self.choice, provider=self.provider, budget=self.budget,
                                   work=self.work, checker=self.checker, store=self.store,
                                   regenerate=bool((self.req or {}).get("regenerate")),
                                   given=(self.req or {}).get("images") or None, log=self.log)
                self.kit = apply(self.home_kit, self.choice, self.pair)
                self.log(f"[sets] {self.choice.id}: {'from the cache' if self.pair.cached else 'made'}"
                         f" (${self.pair.usd:.3f})")
        except Exception as e:  # noqa: BLE001 - the kit's own set instead: the presenter still appears
            self.error = f"{type(e).__name__}: {str(e)[:200]}"
            self.kit = self.home_kit
            self.log(f"[sets] {self.choice.id if self.choice else '?'}: kept the presenter's own set ({self.error})")
        finally:
            self.seconds = round(time.time() - t0, 1)
            self._done.set()
        return self.kit

    def warning(self) -> str:
        if not self.error or self.choice is None or self.choice.spec is None:
            return ""
        return (f"The presenter could not be put in the \"{self.choice.spec.label}\" set this time "
                f"({self.error[:120]}): their own set was used.")

    def report(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"requested": self.requested}
        if self.choice is not None:
            out.update(self.choice.report())
        if self.pair is not None:
            out["pair"] = self.pair.report()
            out["usd"] = round(self.pair.usd + float((self.choice.model if self.choice else {}).get("usd") or 0.0), 4)
        elif self.choice is not None:
            out["usd"] = round(float(self.choice.model.get("usd") or 0.0), 4)
        out["used"] = (self.choice.id if self.choice is not None and self.pair is not None and not self.error
                       else HOME)
        if self.error:
            out["error"] = self.error
        out["seconds"] = self.seconds
        return out


def job_text(segments: Sequence[Any] = (), script: str = "") -> str:
    """The words auto reads: the script as written, else the narration's own lines."""
    if str(script or "").strip():
        return str(script)
    return " ".join(str(getattr(s, "text", "") or "") for s in segments or [])


def action(inp: Dict[str, Any], work: str) -> Dict[str, Any]:
    """
    The worker's "presenter_set" action, outside a video: {presenter_kit | presenter_id ..., "set": "auto" | id |
    {"id": "custom", "description"}, "title", "script", "make": false, "budget_usd": 0.6, "model": true}. Returns
    the choice, whether its pair is cached, and with make: true the pair itself (found or made) and its cost.
    """
    from . import kits as _kits
    from . import providers as _providers
    from .budget import Budget
    from .checks import Checker
    kit = _kits.for_job(inp)
    raw = inp.get("set", inp.get("presenter_set", "auto"))
    provider = _providers.get()
    try:
        cap = max(0.0, min(2.0, float(inp.get("budget_usd") if inp.get("budget_usd") not in (None, "") else 0.6)))
    except (TypeError, ValueError):
        cap = 0.6
    budget = Budget(cap)
    job = SetJob(kit, raw if raw not in (None, "") else "auto", provider=provider, budget=budget, work=work,
                 checker=Checker(provider, budget, work))
    choice = job.choose(title=str(inp.get("title") or ""), text=job_text((), str(inp.get("script") or "")),
                        allow_model=inp.get("model") is not False)
    out: Dict[str, Any] = {"ok": True, "kit": kit.get("id"), "set": choice.report(), "home": home_of(kit),
                           "cached": job.maybe_cached() if job.needs_pair() else True}
    if job.needs_pair():
        out["folder"] = f"{folder_for(kit)}/{choice.spec.id}"
    if inp.get("make") is True and job.needs_pair():
        job.run()
        out["pair"] = job.pair.report() if job.pair is not None else None
        if job.error:
            out["ok"], out["error"] = False, job.error
    out["usd"] = round(budget.spent, 4)
    return out
