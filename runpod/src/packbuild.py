"""
Building a niche footage pack (the shelf src/packs.py reads).

Licensing is a hard rule here: a pack holds only footage we may show. The ONLY
sources are
  * NASA Image and Video Library (images-api.nasa.gov): NASA media is generally
    not copyrighted, so an item is kept unless its own text carries a copyright
    notice or a credit line naming someone who is not NASA or another US
    agency (nasa_verdict);
  * Wikimedia Commons videos under a public-domain mark or CC0, or CC BY /
    CC BY-SA with the author and the licence stored on the clip; NC, ND, GFDL,
    non-free and anything unrecognised is dropped (wikimedia_verdict);
  * the Internet Archive, only items whose licenseurl is an explicit
    public-domain mark or CC0 - being in a "public domain" collection such as
    Prelinger proves nothing about one item (archive_verdict);
  * the owner's own clip library rows that were kept UNUSED and never shown in
    a video (library.shown): they are already on R2, already through the
    library's gate, with an embedding, so they are only catalogued - their
    licence stays "unverified", as in the library itself.
Never YouTube, never a stock site, never a page that forbids it, never a CAPTCHA
(check_host refuses any other host).

Each source video is downloaded under a size cap, cut at shot changes into
4-10 second segments (plan_segments), every segment is transcoded to the
worker's clip format (H.264, no sound, at most 1080p, 16:9) and put through the
same gate a library clip passes (libstore.check: decodes, not short, black,
frozen, soft, letterboxed, a slideshow of stills, covered by text or graphics,
AI-made, a cartoon or a duplicate) plus the burned-in-captions test, then its
CLIP embedding is matched to the niche's topics: a segment that fits none is
not about the niche and is dropped. What stays is uploaded and listed in the
manifest. A build is resumable (a source already done is skipped, an entry id
is never written twice), capped (max_clips new clips, a time box, a topic
quota) and runs headless: scripts/build_pack.py, or the handler action
pack_build on a pod or the endpoint.

Limits, honestly. NASA's and Wikimedia's licence metadata is what they say it
is: the filters drop what the text marks otherwise, but a credit that is not in
the text cannot be seen, so each entry keeps its sourceUrl for a spot check. The
720p floor of the library gate drops most Internet Archive film (480p). The
catalogues are not large for every topic; a niche is a few hundred clips at
best, and how many of them match a given video is for the CLIP gate to say.
"""
from __future__ import annotations

import dataclasses
import html
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import requests

from . import config, filters, libstore, packs, r2

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

SOURCES = ("nasa", "wikimedia", "archive", "library")
ENTRY_PREFIX = {"nasa": "nasa", "wikimedia": "wm", "archive": "ia", "library": "lib"}
ASSET_SOURCE = {"nasa": "nasa", "wikimedia": "wikimedia", "archive": "archive_org", "library": "library"}
# The only places a pack's footage is ever fetched from.
HOSTS = ("nasa.gov", "wikimedia.org", "archive.org")
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
NASA_SEARCH = "https://images-api.nasa.gov/search"
ARCHIVE_SEARCH = "https://archive.org/advancedsearch.php"


def check_host(url: str, extra: Sequence[str] = ()) -> str:
    """The URL, if it is on one of the sources we may use; ValueError otherwise (the licensing rule, in code)."""
    host = (urllib.parse.urlparse(str(url or "")).hostname or "").lower()
    allowed = tuple(HOSTS) + tuple(h for h in extra if h)
    if not any(host == h or host.endswith("." + h) for h in allowed):
        raise ValueError(f"not a pack source: {host or url!r}")
    return url


# --------------------------------------------------------------------------- #
# Licences
# --------------------------------------------------------------------------- #

_NASA_DENY = re.compile(
    r"©|\(c\)\s*\d{4}|\bcopyright(?:ed)?\b|all rights reserved|(?:used|reprinted|reproduced)\s+(?:with|by)\s+permission"
    r"|with\s+permission\s+(?:of|from)|licen[sc]ed\s+(?:from|by|under)|\btrademark\b|shutterstock|getty\s*images|istock"
    r"|alamy|pond5|storyblocks|reuters|associated\s+press|\bafp\b", re.I)
# "Credit: ...", "footage courtesy of ...": the text up to the end of the line, a sentence or a gap.
_NASA_CREDIT = re.compile(
    r"\b(?:credits?(?=\s*:)|courtesy(?:\s+of)?|provided\s+by|footage\s+from|imagery\s+from|photos?\s+by|photograph\s+by|"
    r"video\s+by)\b\s*:?\s*((?:(?!\b(?:credits?|courtesy)\b)(?!\s{2,})[^\n.]){2,200})", re.I)
_AUDIO = re.compile(r"\b(?:music|audio|song|sound|voice|narrat\w*)\b", re.I)    # the pack keeps no sound
_US_GOV = re.compile(
    r"\b(?:nasa|jpl|caltech|goddard|gsfc|svs|scientific visualization|ames research|langley research|glenn research|"
    r"marshall space|kennedy space|johnson space|stennis|armstrong flight|wallops|earth observatory|usgs|"
    r"geological survey|noaa|national oceanic|national weather service|nws|landsat|modis|viirs|esdis|worldview|gibs|"
    r"space station|iss|astronaut|national science foundation|nsf|fema|forest service|national park service|nps|"
    r"bureau of reclamation|corps of engineers|us government|u\.s\. government)\b", re.I)


def nasa_verdict(data: dict) -> Tuple[bool, str]:
    """
    (keep, why not) for one NASA library item, from its own metadata: dropped
    when its text carries a copyright notice, a stock-agency name, or a credit /
    courtesy line naming anyone who is not NASA or another US agency. Audio
    credits (music) are ignored - a pack clip has no sound.
    """
    text = " ".join(str(data.get(k) or "") for k in ("title", "description", "description_508", "photographer"))
    m = _NASA_DENY.search(text)
    if m:
        return False, f"notice in the text: {m.group(0)[:30]}"
    for m in _NASA_CREDIT.finditer(text):
        lead = text[max(0, m.start() - 24):m.start(1)]
        if _AUDIO.search(lead):
            continue
        for part in m.group(1).split(";"):
            names = part.rsplit(":", 1)[-1]
            for tok in re.split(r"[/,&]|\band\b|\bwith\b", names):
                tok = tok.strip(" '\"()[]")
                if tok and not _US_GOV.search(tok):
                    return False, f"third-party credit: {tok[:40]}"
    return True, ""


def _plain(html_text: Any) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", str(html_text or ""))).split())


_NC_ND = re.compile(r"(?:^|[-\s])(?:nc|nd)(?:[-\s]|$)|non-?commercial|no[-\s]?deriv", re.I)


def wikimedia_verdict(meta: dict) -> dict:
    """
    The licence of a Commons file from its extmetadata: {"ok", "class", "label", "url", "why"}. Public domain and CC0
    are kept; CC BY and CC BY-SA are kept (the caller stores the author and the licence); NC / ND, GFDL, non-free
    and anything unrecognised is dropped.
    """
    def val(k: str) -> str:
        return _plain((meta.get(k) or {}).get("value") if isinstance(meta.get(k), dict) else meta.get(k))
    slug, short, url = val("License").lower(), val("LicenseShortName"), val("LicenseUrl")

    def no(why: str) -> dict:
        return {"ok": False, "class": "", "label": short, "url": url, "why": why}
    if val("NonFree").lower() in ("true", "1", "yes"):
        return no("non-free file")
    if _NC_ND.search(f"{slug} {short.lower()}"):
        return no("NC or ND licence")
    if slug.startswith("pd") or slug in ("cc-pd", "public domain") or re.search(r"\bpublic domain\b", short, re.I):
        klass, label = "pd", short or "Public domain"
    elif slug.startswith("cc0") or slug == "cc-zero" or re.match(r"cc0", short, re.I):
        klass, label = "cc0", short or "CC0"
    elif slug.startswith("cc-by-sa") or re.search(r"\bcc[- ]by[- ]sa\b", short, re.I):
        klass, label = "cc-by-sa", short or slug.upper()
    elif slug.startswith("cc-by") or re.search(r"\bcc[- ]by\b", short, re.I):
        klass, label = "cc-by", short or slug.upper()
    else:
        return no(f"licence not accepted ({short or slug or 'none'})")
    return {"ok": True, "class": klass, "label": label, "url": url, "why": ""}


def archive_verdict(licenseurl: Any) -> dict:
    """
    The licence of an Internet Archive item from its licenseurl: only an explicit public-domain mark (pd) or CC0
    qualifies. No licenseurl, or any other one, is dropped - a collection's name proves nothing about an item.
    """
    urls = [str(u) for u in (licenseurl if isinstance(licenseurl, list) else [licenseurl]) if u]
    if not urls:
        return {"ok": False, "class": "", "label": "", "url": "", "why": "no licence URL"}
    classes = []
    for u in urls:
        low = u.lower()
        if "/publicdomain/zero/" in low:
            classes.append("cc0")
        elif "/publicdomain/mark/" in low or "/licenses/publicdomain" in low:
            classes.append("pd")
        else:
            return {"ok": False, "class": "", "label": u, "url": u, "why": "licence not accepted"}
    klass = "cc0" if all(c == "cc0" for c in classes) else "pd"
    return {"ok": True, "class": klass, "label": "CC0" if klass == "cc0" else "Public domain", "url": urls[0], "why": ""}


# --------------------------------------------------------------------------- #
# Finding candidates
# --------------------------------------------------------------------------- #

@dataclasses.dataclass
class Candidate:
    source: str                     # nasa | wikimedia | archive
    source_id: str
    title: str
    page_url: str
    file_url: str = ""
    license: str = ""
    klass: str = ""                 # pd | cc0 | cc-by | cc-by-sa
    license_url: str = ""
    attribution: str = ""
    size: int = 0
    seconds: float = 0.0
    width: int = 0
    height: int = 0
    topic: str = ""                 # the topic whose search found it
    query: str = ""
    topics: List[str] = dataclasses.field(default_factory=list)
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.source_id}"

    @property
    def prefix(self) -> str:
        """The start of every entry id cut from this source: nasa-GSFC_2015_..."""
        return f"{ENTRY_PREFIX[self.source]}-{packs.safe_id(self.source_id, 70)}"

    def row(self) -> dict:
        """What a dry run shows of it."""
        return {"source": self.source, "id": self.source_id, "title": self.title[:90], "topic": self.topic,
                "license": self.license, "licenseClass": self.klass, "page": self.page_url,
                "file": self.file_url, "sizeMB": round(self.size / 1e6, 1) if self.size else None,
                "width": self.width or None, "height": self.height or None}


class Http:
    """requests with the worker's identifying User-Agent, a polite pause between API calls and a retry on 429 / 5xx."""

    def __init__(self, pause: float = 0.25, timeout: float = 40.0):
        self.pause, self.timeout = pause, timeout

    def get_json(self, url: str, params: Optional[dict] = None):
        last = ""
        for attempt in range(1, 4):
            time.sleep(self.pause)
            try:
                r = requests.get(url, params=params, headers={"User-Agent": config.USER_AGENT}, timeout=self.timeout)
                if r.status_code in (429, 500, 502, 503, 504):
                    last = f"HTTP {r.status_code}"
                    time.sleep(2.0 * attempt)
                    continue
                r.raise_for_status()
                return r.json()
            except (requests.RequestException, ValueError) as e:
                last = f"{type(e).__name__}: {str(e)[:80]}"
                time.sleep(1.0 * attempt)
        raise RuntimeError(f"{url.split('?')[0]}: {last}")


def _vocab(niche: str) -> List[str]:
    n = packs.NICHES[niche]
    words = list(n.keywords)
    for t in n.topics:
        words += [t.name, *t.words]
    return list(dict.fromkeys(words))


def relevant(niche: str, title: str, text: str) -> bool:
    """
    A cheap word test before anything is downloaded: the title uses a word of the niche, or the description two.
    Permissive on purpose - the CLIP topic match after the cut is the real judge - but it spares the build the
    archive search results that matched by chance (a coffee advertisement for "drought").
    """
    vocab = _vocab(niche)

    def hits(s: str) -> int:
        norm = packs._norm(s)
        stems = packs._stems(norm)
        return sum(1 for w in vocab if packs._has_keyword(w, stems, norm))
    return hits(title) >= 1 or hits(text[:900]) >= 2


def _count(stats: dict, source: str, key: str, n: int = 1, reason: str = "") -> None:
    """stats[source][key] += n, and the reason a candidate was turned down tallied under stats[source]["reasons"]."""
    s = stats.setdefault(source, {})
    s[key] = s.get(key, 0) + n
    if reason:
        r = s.setdefault("reasons", {})
        r[reason] = r.get(reason, 0) + 1


def discover_nasa(niche: str, http, per_query: int = 100, stats: Optional[dict] = None) -> List[Candidate]:
    stats = stats if stats is not None else {}
    found: Dict[str, Candidate] = {}
    seen: set = set()
    for topic in packs.NICHES[niche].topics:
        for q in topic.queries:
            try:
                body = http.get_json(NASA_SEARCH, {"q": q, "media_type": "video", "page_size": min(100, per_query)})
            except Exception as e:  # noqa: BLE001 - one search failing does not stop the others
                _count(stats, "nasa", "errors")
                print(f"[packbuild] NASA search {q!r}: {str(e)[:100]}", flush=True)
                continue
            for item in ((body.get("collection") or {}).get("items") or []):
                data = (item.get("data") or [{}])[0]
                nid = str(data.get("nasa_id") or "")
                if not nid or str(data.get("media_type") or "video") != "video":
                    continue
                if nid in seen:
                    if nid in found and topic.name not in found[nid].topics:
                        found[nid].topics.append(topic.name)
                    continue
                seen.add(nid)
                _count(stats, "nasa", "found")
                ok, why = nasa_verdict(data)
                if not ok:
                    _count(stats, "nasa", "licence", reason=why.split(":")[0])
                    continue
                title = _plain(data.get("title") or nid)
                text = f"{data.get('description') or ''} {' '.join(str(k) for k in data.get('keywords') or [])}"
                if not relevant(niche, title, text):
                    _count(stats, "nasa", "off topic")
                    continue
                found[nid] = Candidate(
                    "nasa", nid, title, f"https://images.nasa.gov/details/{urllib.parse.quote(nid)}",
                    license="Public domain (NASA)", klass="pd",
                    attribution=f"NASA {data.get('center') or ''} - {title}".replace("  ", " ")[:200],
                    topic=topic.name, query=q, topics=[topic.name], extra={"collection": item.get("href") or ""})
    return list(found.values())


def pick_nasa_rendition(urls: Sequence[str]) -> str:
    """The mp4 to fetch from an item's file list: large, then medium, then the master (a multi-GB risk), then small."""
    mp4 = [str(u) for u in urls if str(u).lower().endswith(".mp4")]
    for tag in ("~large.mp4", "~medium.mp4", "~orig.mp4", "~small.mp4"):
        for u in mp4:
            if u.lower().endswith(tag):
                return u.replace("http://", "https://")
    plain = [u for u in mp4 if "~" not in u]
    return plain[0].replace("http://", "https://") if plain else ""


def discover_wikimedia(niche: str, http, per_query: int = 50, stats: Optional[dict] = None) -> List[Candidate]:
    stats = stats if stats is not None else {}
    found: Dict[str, Candidate] = {}
    seen: set = set()
    for topic in packs.NICHES[niche].topics:
        for q in topic.queries:
            params = {"action": "query", "format": "json", "generator": "search", "gsrsearch": f"{q} filetype:video",
                      "gsrlimit": min(50, per_query), "gsrnamespace": 6, "prop": "imageinfo",
                      "iiprop": "url|size|mime|mediatype|extmetadata",
                      "iiextmetadatafilter": "License|LicenseShortName|LicenseUrl|Artist|Credit|NonFree|"
                                             "ImageDescription|ObjectName|Categories"}
            try:
                body = http.get_json(COMMONS_API, params)
            except Exception as e:  # noqa: BLE001
                _count(stats, "wikimedia", "errors")
                print(f"[packbuild] Commons search {q!r}: {str(e)[:100]}", flush=True)
                continue
            for page in ((body.get("query") or {}).get("pages") or {}).values():
                info = (page.get("imageinfo") or [{}])[0]
                name = str(page.get("title") or "")
                url = str(info.get("url") or "")
                if not name or not url:
                    continue
                key = name[5:] if name.startswith("File:") else name
                if key in seen:
                    if key in found and topic.name not in found[key].topics:
                        found[key].topics.append(topic.name)
                    continue
                mime = str(info.get("mime") or "")
                if not (mime.startswith("video/") or mime == "application/ogg"):
                    continue
                seen.add(key)
                _count(stats, "wikimedia", "found")
                meta = info.get("extmetadata") or {}
                v = wikimedia_verdict(meta)
                if not v["ok"]:
                    _count(stats, "wikimedia", "licence", reason=v["why"].split(" (")[0])
                    continue
                title = _plain((meta.get("ObjectName") or {}).get("value")) or os.path.splitext(key)[0]
                text = f"{_plain((meta.get('ImageDescription') or {}).get('value'))} " \
                       f"{_plain((meta.get('Categories') or {}).get('value'))}"
                if not relevant(niche, f"{title} {key}", text):
                    _count(stats, "wikimedia", "off topic")
                    continue
                page_url = str(info.get("descriptionurl") or f"https://commons.wikimedia.org/wiki/{urllib.parse.quote(name)}")
                artist = _plain((meta.get("Artist") or {}).get("value")) or _plain((meta.get("Credit") or {}).get("value"))
                credit = f"{artist or 'Wikimedia Commons'} - {title}, {v['label']}" + (f" ({v['url']})" if v["url"] else "")
                found[key] = Candidate(
                    "wikimedia", key, title, page_url, file_url=url, license=v["label"], klass=v["class"],
                    license_url=v["url"], attribution=credit[:300], size=int(info.get("size") or 0),
                    seconds=float(info.get("duration") or 0.0), width=int(info.get("width") or 0),
                    height=int(info.get("height") or 0), topic=topic.name, query=q, topics=[topic.name])
    return list(found.values())


def discover_archive(niche: str, http, per_query: int = 30, stats: Optional[dict] = None) -> List[Candidate]:
    stats = stats if stats is not None else {}
    found: Dict[str, Candidate] = {}
    seen: set = set()
    for topic in packs.NICHES[niche].topics:
        for q in topic.queries:
            params = {"q": f"mediatype:movies AND ({q}) AND (licenseurl:*publicdomain* OR licenseurl:*zero*)",
                      "fl[]": ["identifier", "title", "licenseurl", "description", "creator"],
                      "rows": per_query, "output": "json"}
            try:
                body = http.get_json(ARCHIVE_SEARCH, params)
            except Exception as e:  # noqa: BLE001
                _count(stats, "archive", "errors")
                print(f"[packbuild] Internet Archive search {q!r}: {str(e)[:100]}", flush=True)
                continue
            for d in ((body.get("response") or {}).get("docs") or []):
                ident = str(d.get("identifier") or "")
                if not ident:
                    continue
                if ident in seen:
                    if ident in found and topic.name not in found[ident].topics:
                        found[ident].topics.append(topic.name)
                    continue
                seen.add(ident)
                _count(stats, "archive", "found")
                v = archive_verdict(d.get("licenseurl"))
                if not v["ok"]:
                    _count(stats, "archive", "licence", reason=v["why"])
                    continue
                title = _plain(d.get("title") or ident)
                desc = " ".join(_plain(x) for x in (d.get("description") if isinstance(d.get("description"), list)
                                                    else [d.get("description")]))
                if not relevant(niche, title, desc):
                    _count(stats, "archive", "off topic")
                    continue
                creator = d.get("creator")
                creator = ", ".join(creator) if isinstance(creator, list) else str(creator or "")
                found[ident] = Candidate(
                    "archive", ident, title, f"https://archive.org/details/{urllib.parse.quote(ident)}",
                    license=v["label"], klass=v["class"], license_url=v["url"],
                    attribution=f"Internet Archive{' - ' + creator if creator else ''} - {title}"[:300],
                    topic=topic.name, query=q, topics=[topic.name])
    return list(found.values())


def resolve_file(cand: Candidate, http) -> bool:
    """Find the file to fetch for a NASA or Internet Archive item (one more metadata request); False when there is none."""
    try:
        if cand.source == "nasa" and not cand.file_url:
            urls = http.get_json(cand.extra.get("collection") or f"https://images-api.nasa.gov/asset/{cand.source_id}")
            if isinstance(urls, dict):          # the /asset/<id> shape
                urls = [i.get("href", "") for i in ((urls.get("collection") or {}).get("items") or [])]
            cand.file_url = pick_nasa_rendition(urls or [])
        elif cand.source == "archive" and not cand.file_url:
            files = (http.get_json(f"https://archive.org/metadata/{urllib.parse.quote(cand.source_id)}") or {}).get("files") or []
            vids = [f for f in files if str(f.get("name", "")).lower().endswith((".mp4", ".webm", ".ogv"))
                    and str(f.get("source", "")).lower() != "metadata"]
            vids.sort(key=lambda f: (int(f.get("height") or 0) >= config.LIBRARY_MIN_HEIGHT, int(f.get("size") or 0)),
                      reverse=True)
            if vids:
                f = vids[0]
                cand.file_url = f"https://archive.org/download/{urllib.parse.quote(cand.source_id)}/{urllib.parse.quote(f['name'])}"
                cand.size, cand.width, cand.height = int(f.get("size") or 0), int(f.get("width") or 0), int(f.get("height") or 0)
                cand.seconds = float(f.get("length") or 0.0)
    except Exception as e:  # noqa: BLE001
        print(f"[packbuild] no file for {cand.key}: {str(e)[:100]}", flush=True)
    return bool(cand.file_url)


def library_entries(niche: str, lib, http, tv=None, limit: int = 100) -> List["packs.Entry"]:
    """
    The owner's own library clips kept unused and never shown, as pack entries: already on R2 and through the
    library's gate, so only the embedding sidecar is read, and the topics assigned. Their licence stays "unverified".
    """
    from . import ledger
    from . import library as libmod
    out: List[packs.Entry] = []
    for e in list(getattr(lib, "entries", None) or []):
        if len(out) >= limit:
            break
        a = e.get("analysis") or {}
        if e.get("kind", "video") != "video" or not e.get("saved", True) or libmod.shown(e) \
                or not a.get("embeddingKey") or not libstore.is_r2_ref(e.get("bucket") or "") or not e.get("read_url"):
            continue
        try:
            if ledger.on() and ledger.library_used(e):
                continue                                         # an earlier video showed it
            side = http.get_json(libstore.url_for(e.get("bucket") or "", a["embeddingKey"]))
            vec = np.asarray(side.get("embedding"), dtype=np.float32)
            vec = vec / max(float(np.linalg.norm(vec)), 1e-8)
        except Exception:  # noqa: BLE001 - a row without a readable sidecar is skipped
            continue
        topics = assign_topics(niche, vec, tv)
        if not topics:
            continue
        ident = packs.safe_id(str(e["id"]), 70)
        check = a.get("check") if isinstance(a.get("check"), dict) else {}
        out.append(packs.Entry(
            id=f"lib-{ident}@0", niche=niche, url=str(e["read_url"]), seconds=float(e.get("seconds") or 0.0),
            width=int(e.get("width") or 0), height=int(e.get("height") or 0), topics=[t for t, _s in topics],
            source="library", license=e.get("license") or "unverified - you must hold the rights",
            license_class="unverified", attribution=str(e.get("attribution") or "")[:300],
            source_url=str(e.get("url") or ""), start=float(a.get("startSeconds") or 0.0),
            title=str(e.get("subject") or e.get("description") or "")[:120], thumb=str(e.get("thumb_url") or ""),
            phash=list(a.get("phash") or []), checks={**check, "fromLibrary": True},
            created=libstore.now_iso(), vec=vec))
    return out


# --------------------------------------------------------------------------- #
# Cutting a source video into clips
# --------------------------------------------------------------------------- #

def plan_segments(total: float, cuts: Sequence[float], lo: Optional[float] = None, hi: Optional[float] = None,
                  target: float = 8.0, trim: float = 0.25, per_source: Optional[int] = None) -> List[Tuple[float, float]]:
    """
    [(start, length)] of the usable clips in a source `total` seconds long whose shot changes are at `cuts`:
    each shot (a little trimmed at both ends, where fades and transitions live) of `lo`..`hi` seconds is one
    clip, a longer one is split into equal pieces near `target` s, a shorter one is skipped. At most `per_source`
    clips, spread evenly over the video so one source does not give a pack ten near-identical shots.
    """
    lo = config.PACKS_SEGMENT_MIN if lo is None else lo
    hi = config.PACKS_SEGMENT_MAX if hi is None else hi
    per_source = config.PACKS_MAX_PER_SOURCE if per_source is None else per_source
    edges = [0.0] + sorted(c for c in cuts if trim < c < total - trim) + [float(total)]
    out: List[Tuple[float, float]] = []
    for a, b in zip(edges, edges[1:]):
        start, length = a + trim, (b - a) - 2 * trim
        if length < lo:
            continue
        n = 1 if length <= hi else math.ceil(length / target)
        piece = length / n
        out += [(round(start + k * piece, 3), round(piece, 3)) for k in range(n)]
    if per_source and len(out) > per_source:
        step = (len(out) - 1) / max(1, per_source - 1)
        out = [out[round(i * step)] for i in range(per_source)]
    return out


def video_filter(width: int, height: int, fps: float = 30.0) -> str:
    """
    The ffmpeg filter that makes a segment the worker's clip: 16:9 (a wider or taller picture is cropped to it),
    never wider than 1920, square pixels, 30 fps at most, yuv420p. Nothing is upscaled: the pipeline's own
    upscaler lifts a clip under 900 lines.
    """
    parts = []
    aspect = width / max(1, height)
    if aspect > 1.85:
        parts.append("crop=trunc(ih*16/9/2)*2:ih")
    elif aspect < 1.70:
        parts.append("crop=iw:trunc(iw*9/16/2)*2")
    parts.append("scale=min(1920\\,iw):-2:flags=lanczos")
    if fps > 30.5:
        parts.append("fps=30")
    parts += ["setsar=1", "format=yuv420p"]
    return ",".join(parts)


def source_fps(path: str) -> float:
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=avg_frame_rate",
                            "-of", "csv=p=0", path], capture_output=True, text=True, timeout=30)
        num, _, den = (p.stdout or "").strip().partition("/")
        return float(num) / float(den or 1)
    except (OSError, ValueError, ZeroDivisionError, subprocess.TimeoutExpired):
        return 30.0


def transcode(src: str, start: float, length: float, out: str, vf: str, timeout: int = 240) -> bool:
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-i", src, "-t", f"{length:.3f}", "-an", "-vf", vf,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
    try:
        subprocess.run(cmd, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return os.path.isfile(out) and os.path.getsize(out) > 5_000


def download_capped(url: str, dest: str, max_bytes: int, timeout: float = 600.0) -> int:
    """Stream `url` (a source we may use) to `dest`; RuntimeError when it is over `max_bytes` or the time is up."""
    check_host(url)
    t0, written = time.time(), 0
    with requests.get(url, stream=True, timeout=(20, 60), headers={"User-Agent": config.USER_AGENT}) as r:
        r.raise_for_status()
        if int(r.headers.get("Content-Length") or 0) > max_bytes:
            raise RuntimeError(f"{int(r.headers['Content-Length']) / 1e6:.0f} MB is over the {max_bytes / 1e6:.0f} MB cap")
        with open(dest, "wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if not chunk:
                    continue
                written += len(chunk)
                if written > max_bytes:
                    raise RuntimeError("over the size cap")
                if time.time() - t0 > timeout:
                    raise RuntimeError("download timed out")
                fh.write(chunk)
    return written


# --------------------------------------------------------------------------- #
# Which topic a clip is about
# --------------------------------------------------------------------------- #

def topic_vectors(niche: str):
    """(topic name per row, matrix): CLIP's vector for every prompt of every topic of the niche."""
    names, rows = [], []
    for t in packs.NICHES[niche].topics:
        q = packs.query_vectors(list(t.prompts))
        if q is None:
            raise RuntimeError("the local CLIP model is not available (LOCAL_VISION_DIR)")
        rows.append(q)
        names += [t.name] * len(q)
    return names, np.vstack(rows)


def assign_topics(niche: str, vec, tv=None, floor: Optional[float] = None) -> List[Tuple[str, float]]:
    """
    [(topic, similarity)] a clip's embedding fits, best first, at most three and none more than 0.04 under the
    best; [] when even the best is under PACKS_TOPIC_MIN_SIMILARITY - the clip is not about the niche.
    """
    names, mat = tv if tv is not None else topic_vectors(niche)
    floor = config.PACKS_TOPIC_MIN_SIMILARITY if floor is None else floor
    best: Dict[str, float] = {}
    for name, s in zip(names, mat @ np.asarray(vec, dtype=np.float32)):
        best[name] = max(best.get(name, -1.0), float(s))
    ranked = sorted(best.items(), key=lambda kv: -kv[1])
    if not ranked or ranked[0][1] < floor:
        return []
    return [(n, s) for n, s in ranked[:3] if s >= floor and s >= ranked[0][1] - 0.04]


# --------------------------------------------------------------------------- #
# Where a pack is written
# --------------------------------------------------------------------------- #

class LocalStore:
    """A pack in a local folder (a dry build for a look, or PACKS_DIR for a test): <dir>/<niche>/..."""

    def __init__(self, folder: str):
        self.folder = os.path.abspath(folder)

    def _path(self, niche: str, *parts: str) -> str:
        p = os.path.join(self.folder, niche, *parts)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        return p

    def put(self, niche: str, kind: str, name: str, path: str) -> str:
        dest = self._path(niche, kind, name)
        shutil.copyfile(path, dest)
        return dest

    def read_manifest(self, niche: str) -> Optional[dict]:
        p = os.path.join(self.folder, niche, "index.json")
        if not os.path.isfile(p):
            return None
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)

    def write_manifest(self, niche: str, data: dict) -> str:
        p = self._path(niche, "index.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(data, fh, separators=(",", ":"))
        return p


class R2Store:
    """A pack in the library bucket under packs/<niche>/ (needs the R2 keys; only a build ever writes)."""

    def __init__(self):
        if not r2.library_enabled():
            raise RuntimeError("the R2 library bucket is not configured (R2_* and R2_LIBRARY_* env)")

    def put(self, niche: str, kind: str, name: str, path: str) -> str:
        key = f"{packs.key_prefix(niche)}{kind}/{name}"
        ctype = "video/mp4" if name.endswith(".mp4") else "image/jpeg"
        return r2.upload(path, key, content_type=ctype, deadline=time.time() + 300, bucket=config.R2_LIBRARY_BUCKET,
                         base=config.R2_LIBRARY_PUBLIC_BASE, cache_control="public, max-age=86400")

    def read_manifest(self, niche: str) -> Optional[dict]:
        raw = r2.get_bytes(f"{packs.key_prefix(niche)}index.json", bucket=config.R2_LIBRARY_BUCKET)
        return json.loads(raw.decode("utf-8")) if raw else None

    def write_manifest(self, niche: str, data: dict) -> str:
        return r2.upload_bytes(json.dumps(data, separators=(",", ":")).encode("utf-8"),
                               f"{packs.key_prefix(niche)}index.json", content_type="application/json",
                               deadline=time.time() + 120, bucket=config.R2_LIBRARY_BUCKET,
                               base=config.R2_LIBRARY_PUBLIC_BASE, cache_control="public, max-age=300")


# --------------------------------------------------------------------------- #
# Building
# --------------------------------------------------------------------------- #

@dataclasses.dataclass
class Build:
    """One build's shared state (sources are processed a few at a time)."""
    niche: str
    store: Any
    work: str
    max_clips: int
    deadline: float
    tv: Any = None
    entries: Dict[str, "packs.Entry"] = dataclasses.field(default_factory=dict)
    sources: Dict[str, dict] = dataclasses.field(default_factory=dict)
    known: Dict[str, list] = dataclasses.field(default_factory=dict)
    topic_counts: Counter = dataclasses.field(default_factory=Counter)
    added: int = 0
    rejected: Counter = dataclasses.field(default_factory=Counter)
    lock: threading.Lock = dataclasses.field(default_factory=threading.Lock)

    def full(self) -> bool:
        return self.added >= self.max_clips or time.time() > self.deadline

    def adopt(self, data: Optional[dict]) -> None:
        """Start from the manifest already there (a build adds to a pack; it never starts over)."""
        pack = packs.Pack.from_manifest(self.niche, data or {})
        for e in pack.entries:
            self.entries[e.id] = e
            self.known[e.id] = libstore.parse_hashes(e.phash)
            if e.topics:
                self.topic_counts[e.topics[0]] += 1
        self.sources.update((data or {}).get("sources") or {})

    def manifest(self) -> dict:
        return packs.manifest(self.niche, self.entries.values(), self.sources)


def _clean_reason(reason: str) -> str:
    return reason.split(" (")[0].split(" of ")[0][:40]


def build_source(cand: Candidate, b: Build, http) -> dict:
    """
    Download one source, cut it, check every cut and keep the good ones: returns what happened to it
    ({"segments", "kept", "why"}). A failure of any step only ends this source.
    """
    rec = {"at": libstore.now_iso(), "segments": 0, "kept": 0, "why": ""}
    folder = tempfile.mkdtemp(prefix="packsrc_", dir=b.work)
    try:
        if not cand.file_url and not resolve_file(cand, http):
            rec["why"] = "no video file"
            return rec
        cap = int(config.PACKS_MAX_SOURCE_MB * 1e6)
        if cand.size and cand.size > cap:
            rec["why"] = f"{cand.size / 1e6:.0f} MB is over the cap"
            return rec
        ext = os.path.splitext(urllib.parse.urlparse(cand.file_url).path)[1] or ".mp4"
        src = os.path.join(folder, f"source{ext}")
        download_capped(cand.file_url, src, cap)
        info = libstore.probe(src)
        if not info["ok"]:
            rec["why"] = "unreadable file"
            return rec
        w, h, total = info["width"], info["height"], info["seconds"]
        if w < config.LIBRARY_MIN_WIDTH or h < config.LIBRARY_MIN_HEIGHT or w < h * 1.2:
            rec["why"] = f"below the quality floor ({w}x{h})"
            return rec
        if total > config.PACKS_MAX_SOURCE_SECONDS:
            rec["why"] = f"{total / 60:.0f} minutes is too long"
            return rec
        cuts = filters.scene_cuts(src)
        plan = plan_segments(total, cuts, per_source=config.PACKS_MAX_PER_SOURCE * 2)
        vf = video_filter(w, h, source_fps(src))
        kept: List[packs.Entry] = []
        for n, (start, length) in enumerate(plan):
            if b.full() or len(kept) >= config.PACKS_MAX_PER_SOURCE:
                break
            rec["segments"] += 1
            entry_id = f"{cand.prefix}@{int(start)}"
            if entry_id in b.entries:
                continue                                              # resumed: already in the pack
            seg = os.path.join(folder, f"seg_{n:03d}.mp4")
            if not transcode(src, start, length, seg, vf):
                b.rejected["transcode failed"] += 1
                continue
            e = _check_and_catalogue(cand, b, entry_id, seg, start)
            if e is not None:
                kept.append(e)
        rec["kept"] = len(kept)
        return rec
    except Exception as e:  # noqa: BLE001 - one source never stops the build
        rec["why"] = f"{type(e).__name__}: {str(e)[:100]}"
        return rec
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _check_and_catalogue(cand: Candidate, b: Build, entry_id: str, seg: str, start: float) -> Optional["packs.Entry"]:
    """The gate, the topic match, then the upload; the entry, or None (counted by reason)."""
    with b.lock:
        known = dict(b.known)
    v = libstore.check(seg, kind="video", known=known, title=cand.title or "",
                       source="archive_org" if cand.source == "archive" else cand.source)
    if not v.ok:
        for r in v.reasons:
            b.rejected[_clean_reason(r)] += 1
        return None
    if v.embedding is None:
        b.rejected["no CLIP embedding"] += 1
        return None
    if filters.has_burned_captions(seg):
        b.rejected["burned-in captions or UI"] += 1
        return None
    vec = np.asarray(v.embedding, dtype=np.float32)
    vec = vec / max(float(np.linalg.norm(vec)), 1e-8)
    topics = assign_topics(b.niche, vec, b.tv)
    if not topics:
        b.rejected["not about the niche"] += 1
        return None
    with b.lock:
        if b.full():
            return None
        if b.topic_counts[topics[0][0]] >= config.PACKS_TOPIC_QUOTA:
            b.rejected["topic full"] += 1
            return None
        dup = libstore.duplicate_of(v.hashes, b.known)
        if dup:
            b.rejected["duplicate"] += 1
            return None
        b.known[entry_id] = v.hashes                  # claimed before the upload: no twin slips in
        b.topic_counts[topics[0][0]] += 1
        b.added += 1
    safe = packs.safe_id(entry_id)
    try:
        url = b.store.put(b.niche, "clips", f"{safe}.mp4", seg)
        thumb_path = libstore.thumbnail(seg, seg + ".jpg", v.seconds)
        thumb = b.store.put(b.niche, "thumbs", f"{safe}.jpg", thumb_path) if thumb_path else ""
    except Exception as e:  # noqa: BLE001 - not listed unless it is there
        with b.lock:
            b.known.pop(entry_id, None)
            b.topic_counts[topics[0][0]] -= 1
            b.added -= 1
        b.rejected["upload failed"] += 1
        print(f"[packbuild] upload of {entry_id} failed: {type(e).__name__}: {str(e)[:100]}", flush=True)
        return None
    checks = {k: val for k, val in v.summary().items() if k in ("v", "ok", "sharpness", "motion", "bars", "graphics",
                                                                "textBands", "kindClass", "slop")}
    checks.update(captions=False, topicSim=round(topics[0][1], 3))
    entry = packs.Entry(
        id=entry_id, niche=b.niche, url=url, seconds=v.seconds, width=v.width, height=v.height,
        topics=[t for t, _s in topics], source=ASSET_SOURCE[cand.source], license=cand.license, license_class=cand.klass,
        license_url=cand.license_url, attribution=cand.attribution, source_url=cand.page_url, start=float(start),
        title=cand.title, thumb=thumb, phash=libstore.hex_hashes(v.hashes), checks=checks, created=libstore.now_iso(),
        vec=vec)
    with b.lock:
        b.entries[entry_id] = entry
    return entry


def _order(cands: List[Candidate]) -> List[Candidate]:
    """One candidate per topic in turn (so a small max-clips still spreads over the niche), NASA before Commons before the Archive."""
    rank = {"nasa": 0, "wikimedia": 1, "archive": 2}
    groups: Dict[str, List[Candidate]] = {}
    for c in sorted(cands, key=lambda c: rank.get(c.source, 9)):
        groups.setdefault(c.topic, []).append(c)
    out: List[Candidate] = []
    while any(groups.values()):
        for g in groups.values():
            if g:
                out.append(g.pop(0))
    return out


def discover(niche: str, http, sources: Sequence[str] = ("nasa", "wikimedia", "archive"),
             per_query: Optional[Dict[str, int]] = None, stats: Optional[dict] = None) -> List[Candidate]:
    """Every licence-clean, on-topic candidate the chosen sources list for the niche (counts go in `stats`)."""
    per = {"nasa": 100, "wikimedia": 50, "archive": 30, **(per_query or {})}
    fns = {"nasa": discover_nasa, "wikimedia": discover_wikimedia, "archive": discover_archive}
    out: List[Candidate] = []
    for s in sources:
        if s in fns:
            out += fns[s](niche, http, per[s], stats)
    return out


def run(niche: str, *, max_clips: int = 40, sources: Optional[Sequence[str]] = None, dry_run: bool = False,
        resolve: bool = False, seconds: float = 1500.0, local_dir: str = "", library=None, parallel: int = 2,
        http=None, store=None, work: str = "", report: Optional[Callable] = None) -> dict:
    """
    Build or refresh a niche's pack: discover, skip what the pack already has, then (unless `dry_run`) download,
    cut, check and upload until `max_clips` new clips are in or `seconds` are up, writing the manifest as it goes.
    `dry_run` lists what it would fetch and downloads nothing (`resolve` also looks up each item's file link).
    `library`: a library.Library to catalogue unused clips from. Returns a JSON-able summary.
    """
    niche = str(niche or "").strip().lower()
    if niche not in packs.NICHES:
        return {"ok": False, "error": f"unknown niche {niche!r} (one of {', '.join(packs.NICHES)})"}
    chosen = [s for s in (sources or ("nasa", "wikimedia", "archive")) if s in SOURCES]
    t0 = time.time()
    http = http or Http()
    say = report or (lambda *a, **k: None)
    stats: Dict[str, Any] = {}
    if store is None:
        try:
            store = LocalStore(local_dir) if local_dir else (None if dry_run and not r2.library_enabled() else R2Store())
        except RuntimeError as e:
            return {"ok": False, "action": "pack_build", "niche": niche, "error": str(e)}
    existing = None
    try:
        existing = store.read_manifest(niche) if store is not None else (packs._read_manifest(niche) if packs.available() else None)
    except Exception as e:  # noqa: BLE001 - a dry run still plans
        print(f"[packbuild] existing {niche} pack not read: {type(e).__name__}: {str(e)[:100]}", flush=True)
    b = Build(niche, store, work or tempfile.mkdtemp(prefix="packbuild_"), max(0, int(max_clips)), t0 + float(seconds))
    b.adopt(existing)
    say(f"Looking for {niche} footage", 5)
    cands = discover(niche, http, [s for s in chosen if s != "library"], stats=stats)
    todo = [c for c in _order(cands) if c.key not in b.sources]
    by_licence: Dict[str, Dict[str, int]] = {}
    for c in cands:
        by_licence.setdefault(c.source, {})[c.klass] = by_licence.get(c.source, {}).get(c.klass, 0) + 1
    out: Dict[str, Any] = {
        "ok": True, "action": "pack_build", "niche": niche, "dryRun": bool(dry_run), "sources": chosen,
        "existing": len(b.entries), "found": {s: dict(v) for s, v in stats.items()}, "candidates": len(cands),
        "licences": by_licence, "alreadyDone": len(cands) - len(todo)}
    if dry_run:
        plan = todo[:max(10, b.max_clips * 3)]
        if resolve:
            for c in plan:
                resolve_file(c, http)
        out.update(planned=[c.row() for c in plan], wouldTry=len(plan))
        out["seconds"] = round(time.time() - t0, 1)
        return out
    try:
        b.tv = topic_vectors(niche)
    except RuntimeError as e:
        return {**out, "ok": False, "error": str(e)}
    if "library" in chosen and library is not None:
        for e in library_entries(niche, library, http, b.tv, limit=b.max_clips):
            if e.id not in b.entries:
                b.entries[e.id] = e
                b.topic_counts[e.topics[0]] += 1
        out["fromLibrary"] = sum(1 for e in b.entries.values() if e.source == "library")
    done = 0

    def one(c: Candidate) -> None:
        nonlocal done
        if b.full():
            return
        rec = build_source(c, b, http)
        with b.lock:
            b.sources[c.key] = rec
            done += 1
            n = done
        say(f"Building the {niche} pack: {b.added} clips from {n} sources", min(95, 10 + int(80 * b.added / max(1, b.max_clips))))
        if rec["kept"]:
            with b.lock:
                data = b.manifest()
            b.store.write_manifest(niche, data)
        print(f"[packbuild] {c.key}: {rec['kept']} kept of {rec['segments']} cut"
              + (f" ({rec['why']})" if rec["why"] else ""), flush=True)

    pool = ThreadPoolExecutor(max_workers=max(1, parallel))
    try:
        for _ in pool.map(one, todo):
            pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    with b.lock:
        data = b.manifest()
    where = b.store.write_manifest(niche, data)
    shutil.rmtree(b.work, ignore_errors=True)
    out.update(added=b.added, total=len(b.entries), manifest=where, sourcesTried=done,
               rejected=dict(b.rejected), topics=dict(b.topic_counts), seconds=round(time.time() - t0, 1),
               stoppedBy="max_clips" if b.added >= b.max_clips else ("time" if time.time() > b.deadline else "candidates"))
    return out
