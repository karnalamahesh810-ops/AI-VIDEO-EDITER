"""
The owner's script: plain narration with clip spots on their own lines.

    Tom Holland cannot keep a secret.
    [CLIP: Tom Holland | "I'm not allowed to say" | Jimmy Kimmel Live | 12-20s]
    [CLIP: url=https://youtu.be/XXXX start=1:12 end=1:31 | who=Tom Holland]

Fields (positional, '|' separated): who, "quote", where, duration hint. Any field may also be
written key=value (who=, quote=, where=, dur=, url=, start=, end=, label=). Everything outside
[CLIP ...] is narration. parse() returns the ordered blocks: the timeline skeleton.
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

_CLIP = re.compile(r"\[\s*(CLIP|MONTAGE|FLASH)\s*:?(.*?)\]", re.I | re.S)


@dataclass
class Block:
    kind: str                      # "narr" | "clip"
    text: str = ""                 # narration text (narr)
    who: List[str] = field(default_factory=list)
    quote: str = ""
    where: str = ""
    min_s: float = 0.0
    max_s: float = 0.0
    url: str = ""
    start: Optional[float] = None
    end: Optional[float] = None
    label: str = ""                # show / person label drawn at the clip's start
    cold: bool = False             # this clip gives the cold open (default: the plan picks one)
    film: str = ""                 # "Title / Subtitle / Year": a title card when the film changes
    names: List[str] = field(default_factory=list)    # "NAME@seconds@hint": name label + circle
    pops: List[str] = field(default_factory=list)     # "\"TEXT\"@seconds@hint": punchline pop
    points: List[str] = field(default_factory=list)   # "@seconds@hint": pointer triangle above a head
    shots: List[str] = field(default_factory=list)    # montage: "VIDEOID@a-b [pop=..|speed|arrow]"
    key: str = ""                  # the worker's own source name for this clip (src/celeb/pipeline.py)

    @property
    def youtube_id(self) -> str:
        m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", self.url or "")
        return m.group(1) if m else ""

    @property
    def video_id(self) -> str:
        """The source this clip plays from: the pipeline's downloaded window once found, else the URL's id."""
        if self.key:
            return self.key
        m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", self.url or "")
        return m.group(1) if m else ""


def timecode(v: str) -> Optional[float]:
    """'1:12' / '01:02:03' / '72' / '72.5s' -> seconds."""
    v = (v or "").strip().lower().rstrip("s")
    if not v:
        return None
    try:
        parts = [float(p) for p in v.split(":")]
    except ValueError:
        return None
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def duration_hint(v: str) -> Tuple[float, float]:
    """'12-20s' -> (12, 20); '15s' -> (0, 15); '' -> (0, 0)."""
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(?:-\s*(\d+(?:\.\d+)?))?\s*s?\s*$", v or "")
    if not m:
        return 0.0, 0.0
    a, b = float(m.group(1)), m.group(2)
    return (a, float(b)) if b else (0.0, a)


def parse_clip(body: str) -> Block:
    b = Block(kind="clip")
    positional = []
    for raw in body.split("|"):
        part = raw.strip()
        if not part:
            continue
        # key=value fields; several may share one segment ("url=... start=1:12 end=1:31")
        kvs = re.findall(r"(\w+)\s*=\s*(.*?)(?=\s+\w+\s*=|$)", part)
        if kvs and re.match(r"^\w+\s*=", part):
            for k, v in kvs:
                raw = v.strip()
                v = raw.strip('"')
                k = k.lower()
                if k == "who":
                    b.who = [w.strip() for w in re.split(r",|&| and ", v) if w.strip()]
                elif k == "quote":
                    b.quote = v
                elif k == "where":
                    b.where = v
                elif k in ("dur", "duration"):
                    b.min_s, b.max_s = duration_hint(v)
                elif k == "url":
                    b.url = v
                elif k in ("start", "in"):
                    b.start = timecode(v)
                elif k in ("end", "out"):
                    b.end = timecode(v)
                elif k == "label":
                    b.label = v
                elif k == "film":
                    b.film = v
                elif k == "name":
                    b.names.append(raw)
                elif k == "pop":
                    b.pops.append(raw)
                elif k == "point":
                    b.points.append(raw)
                elif k == "cold":
                    b.cold = v.lower() not in ("0", "no", "false")
            continue
        positional.append(part)
    for part in positional:
        if part[:1] in "\"“'" and not b.quote:
            b.quote = part.strip("\"“”' ")
        elif not b.who:
            b.who = [w.strip() for w in re.split(r",|&| and ", part) if w.strip()]
        elif re.match(r"^\d+(\.\d+)?\s*(-\s*\d+(\.\d+)?)?\s*s?$", part) and not b.max_s:
            b.min_s, b.max_s = duration_hint(part)
        elif not b.where:
            b.where = part
    return b


def parse(script: str) -> List[Block]:
    """Ordered narr / clip blocks. Consecutive narration lines join into one block."""
    blocks: List[Block] = []
    pos = 0
    for m in _CLIP.finditer(script or ""):
        _narr(blocks, script[pos:m.start()])
        kind = m.group(1).upper()
        if kind == "CLIP":
            blocks.append(parse_clip(m.group(2)))
        elif kind == "FLASH":
            blocks.append(Block(kind="flash"))
        else:
            blocks.append(Block(kind="montage", shots=[x.strip() for x in m.group(2).split(",") if x.strip()]))
        pos = m.end()
    _narr(blocks, (script or "")[pos:])
    return blocks


def _narr(blocks: List[Block], text: str) -> None:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return
    if blocks and blocks[-1].kind == "narr":
        blocks[-1].text = f"{blocks[-1].text} {text}"
    else:
        blocks.append(Block(kind="narr", text=text))
