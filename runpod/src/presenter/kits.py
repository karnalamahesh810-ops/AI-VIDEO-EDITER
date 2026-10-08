"""
Presenter kits: who the AI presenter is.

No model is trained. A presenter is a set of our own pictures of one made-up
person, sent with every call (docs/ai-avatar-style-plan-2026-10-07.md
section 5): a master portrait, two or more framings of the same moment on
the same set (medium and close-up, cut between like a two-camera shoot), the
empty set (an establishing shot, and the still a failed presenter shot falls
back to), and optionally a voice sample. Every presenter shot starts from one
of the kit's framings, so the face never changes between shots or videos.

Kits are referenced by id from a JSON catalogue: the one shipped with the
worker (src/presenter/kits.json - empty: this repository is public, and a
kit's links are not for publishing), then PRESENTER_KITS_FILE (a local path)
and PRESENTER_KITS_URL (an https JSON, e.g. on R2) on top - a later one wins
on the same id. A job may also carry the kit itself ("presenter_kit": {...}),
which is how the app's presenters table can feed the worker without a deploy.

Kit fields: id, name (the lower third), title (its second line), synthetic
(a made-up person: true), persona and wardrobe (the presenter-in-action
stills are drawn from them), from_behind (how the presenter looks from
behind: anyone b-roll shows from behind is drawn so), world {place, era,
light, palette, lens} (the style bible's defaults), master, framings [{id,
url, shot, set, face_x (where the face is across the frame, 0-1: the split
screen crops on it)}], sets [{id, url, label}], style ("selfie": the avatar
moves like a handheld phone), avatar {prompt, motion_prompt, expressiveness},
voice {sample_url, suggested}, grade (a grade preset), home_set (the catalogue
set its own pictures show - src/presenter/sets.py). Picture links are https
(R2), or files - absolute, or relative to the catalogue - for local runs.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
from typing import Any, Dict, List, Optional

from urllib.parse import urljoin

import requests

from . import motion as _motion

HERE = os.path.dirname(os.path.abspath(__file__))
CATALOGUE = os.path.join(HERE, "kits.json")

# The tuned default (src/presenter/motion.py: eyes, face and hands, the owner 2026-10-08); every take now builds its
# own from the framing and the line's tone (motion.for_shot) - these stay for kits and callers that read them.
DEFAULT_MOTION_PROMPT = _motion.MEDIUM
DEFAULT_AVATAR_PROMPT = ("{who} talks warmly and calmly straight to the camera. Natural, subtle head movement, "
                         "realistic lip sync. Static camera, still background.")

_CACHE: Dict[str, Any] = {"at": 0.0, "kits": None}
_LOCK = threading.Lock()


class KitError(ValueError):
    """The job names no usable presenter kit."""


def _entries(data: Any, base_url: str = "") -> List[dict]:
    """
    The kit objects of a catalogue: {"kits": [...]}, {"presenters": [...]}, {id: kit}, or a bare list. A
    catalogue-wide "base_url" (or the one given) goes to every kit that has none: its relative picture paths
    ("ruth/ruth_master.png") are links under it (the app's R2 copies, presenters/<id>/<file>).
    """
    if isinstance(data, dict):
        base_url = str(data.get("base_url") or data.get("assets_base") or base_url or "")
        for key in ("kits", "presenters", "personas"):
            if isinstance(data.get(key), (list, dict)):
                data = data[key]
                break
    if isinstance(data, dict):
        rows = [dict(v, id=v.get("id") or k) for k, v in data.items() if isinstance(v, dict)]
    else:
        rows = [dict(v) for v in data or [] if isinstance(v, dict)]
    if base_url:
        rows = [dict(r, base_url=r.get("base_url") or base_url) for r in rows]
    return [r for r in rows if kit_id(r)]


def kit_id(kit: dict) -> str:
    persona = kit.get("persona") if isinstance(kit.get("persona"), dict) else {}
    kid = kit.get("id") or kit.get("slug") or kit.get("key") or persona.get("id") or persona.get("slug")
    if not kid:
        name = kit.get("name") or kit.get("display_name") or persona.get("name")
        kid = "-".join(str(name).lower().split()) if name else ""
    return str(kid or "")


def _load_file(path: str) -> List[dict]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        print(f"[presenter] kit catalogue {os.path.basename(path)} unreadable: {type(e).__name__}", flush=True)
        return []
    base = os.path.dirname(os.path.abspath(path))
    return [dict(k, _base=base) for k in _entries(data)]


def _load_url(url: str) -> List[dict]:
    try:
        r = requests.get(url, timeout=30)
        data = r.json() if r.status_code == 200 else {}
    except (requests.RequestException, ValueError) as e:
        print(f"[presenter] kit catalogue at {url.split('?')[0][-60:]} unreadable: {type(e).__name__}", flush=True)
        return []
    # Relative picture paths in a catalogue served by link are links beside it.
    return _entries(data, base_url=url.rsplit("/", 1)[0] + "/")


def catalogue(refresh: bool = False) -> Dict[str, dict]:
    """Every known kit by id: the shipped catalogue, then PRESENTER_KITS_FILE, then PRESENTER_KITS_URL."""
    with _LOCK:
        if _CACHE["kits"] is not None and not refresh:
            return dict(_CACHE["kits"])
    kits: Dict[str, dict] = {}
    sources = [_load_file(CATALOGUE) if os.path.isfile(CATALOGUE) else []]
    extra = os.getenv("PRESENTER_KITS_FILE", "").strip()
    if extra:
        sources.append(_load_file(extra))
    url = os.getenv("PRESENTER_KITS_URL", "").strip()
    if url.startswith("https://"):
        sources.append(_load_url(url))
    for rows in sources:
        for k in rows:
            kits[kit_id(k)] = k
    with _LOCK:
        _CACHE["kits"] = kits
    return dict(kits)


_URL_KEYS = ("url", "path", "file", "image", "src", "href")
# The order a kit's framings are used in (by id): the master, then a medium close-up as the second camera.
FRAMING_PREFERENCE = ("master", "medium", "closeup", "close", "wide", "three_quarter")
SELFIE_MOTION_PROMPT = _motion.SELFIE


def _url_of(entry: Any) -> str:
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, dict):
        for key in _URL_KEYS:
            if isinstance(entry.get(key), str) and entry[key].strip():
                return entry[key].strip()
    return ""


def _first(d: dict, *keys: str) -> Any:
    for key in keys:
        cur: Any = d
        for part in key.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
        if cur not in (None, "", [], {}):
            return cur
    return None


def _pictures(raw: Any, prefix: str) -> List[dict]:
    """A list (or {id: entry} map) of pictures as [{"id", "url", ...the entry's own fields}]."""
    items = list(raw.items()) if isinstance(raw, dict) else list(enumerate(raw or []))
    out = []
    for key, entry in items:
        url = _url_of(entry)
        if not url:
            continue
        row = dict(entry) if isinstance(entry, dict) else {}
        row["id"] = str(row.get("id") or (key if isinstance(key, str) else f"{prefix}{key}"))
        row["url"] = url
        out.append(row)
    return out


def normalize(kit: dict) -> dict:
    """
    A kit with every field the pipeline reads, checked: at least one framing
    (the master counts as one). Reads this module's schema and the obvious
    other spellings (master_url / portrait, angles / variants, plates /
    clean_plates, a persona object with name / title / wardrobe / bio), so a
    catalogue written elsewhere loads as it is.
    """
    if not isinstance(kit, dict):
        raise KitError("the presenter kit is not an object")
    k = dict(kit)
    persona_obj = k.get("persona") if isinstance(k.get("persona"), dict) else {}
    kid = _first(k, "id", "slug", "key") or _first(persona_obj, "id", "slug")
    name = _first(k, "name", "display_name") or _first(persona_obj, "name")
    if not kid and name:
        kid = "-".join(str(name).lower().split())
    if not kid:
        raise KitError("the presenter kit has no id")
    k["id"] = str(kid)
    k["name"] = str(name or k["id"]).strip()
    k["title"] = str(_first(k, "title", "role", "lower_third") or _first(persona_obj, "title", "role", "trade")
                     or "").strip()
    k["synthetic"] = k.get("synthetic") is not False
    persona_text = k.get("persona") if isinstance(k.get("persona"), str) else (
        _first(persona_obj, "description", "summary", "bio", "who") or _first(k, "bio", "description"))
    k["persona"] = str(persona_text or f"{k['name']}, the presenter").strip()
    k["wardrobe"] = str(_first(k, "wardrobe", "wardrobe_lock") or _first(persona_obj, "wardrobe") or "").strip()
    world = k.get("world") if isinstance(k.get("world"), dict) else {}
    k["world"] = {key: str(world.get(key) or "").strip() for key in ("place", "era", "light", "palette", "lens")}
    if not k["world"]["place"] and isinstance(k.get("room"), str):
        k["world"]["place"] = k["room"].strip()          # the presenter's room seeds the style bible's place
    master = _url_of(_first(k, "master", "master_url", "master_image", "portrait", "images.master") or "")
    framings = []
    for f in _pictures(_first(k, "framings", "angles", "variants", "presenter_frames", "camera_angles",
                              "images.framings") or [], "f"):
        framings.append({**{x: y for x, y in f.items() if x not in ("id", "url")}, "id": f["id"], "url": f["url"],
                         "shot": str(f.get("shot") or f.get("label") or ""), "set": str(f.get("set") or "")})
    if master and not any(f["url"] == master for f in framings):
        framings.insert(0, {"id": "master", "url": master, "shot": "medium shot", "set": ""})
    # The master first (the hook and most appearances), then the second camera the prototype found best - a
    # medium close-up (chest up) - then the wider and angled ones (the retry's).
    framings.sort(key=lambda f: next((n for n, word in enumerate(FRAMING_PREFERENCE) if word in f["id"].lower()),
                                     len(FRAMING_PREFERENCE)))
    if not framings:
        raise KitError(f"presenter kit '{k['id']}' has no framing or master picture")
    k["framings"] = framings
    k["master"] = master or framings[0]["url"]
    k["sets"] = [{"id": s["id"], "url": s["url"], "label": str(s.get("label") or s.get("description") or "")}
                 for s in _pictures(_first(k, "sets", "plates", "clean_plates", "backgrounds", "set_plates",
                                           "images.sets", "images.plates") or [], "set")]
    task = _url_of(_first(k, "task", "images.task") or "")
    if task and not any(x["url"] == task for x in k["sets"]):
        # The presenter's hands at work: one more picture a failed still may fall back to.
        k["sets"].append({"id": "task", "url": task, "label": "the presenter's hands at work"})
    avatar = k.get("avatar") if isinstance(k.get("avatar"), dict) else {}
    selfie = "selfie" in str(_first(k, "style", "camera", "framing_style") or "").lower()
    k["avatar"] = {"prompt": str(avatar.get("prompt") or DEFAULT_AVATAR_PROMPT.format(who=k["persona"])),
                   "motion_prompt": str(avatar.get("motion_prompt")
                                        or (SELFIE_MOTION_PROMPT if selfie else DEFAULT_MOTION_PROMPT)),
                   # The kit's own words (the app may send them) replace the per-take defaults (motion.for_shot).
                   # (a kit normalised once already keeps its own flags: its filled-in defaults are not "its own")
                   "custom_prompt": (bool(avatar["custom_prompt"]) if "custom_prompt" in avatar
                                     else bool(avatar.get("prompt"))),
                   "custom_motion": (bool(avatar["custom_motion"]) if "custom_motion" in avatar
                                     else bool(avatar.get("motion_prompt"))),
                   "selfie": selfie,
                   **({"expressiveness": avatar["expressiveness"]} if avatar.get("expressiveness") else {})}
    # The catalogue set its own pictures show (src/presenter/sets.py): a pick of that set uses them, free.
    k["home_set"] = str(k.get("home_set") or "").strip().lower()
    voice = k.get("voice") if isinstance(k.get("voice"), dict) else {}
    k["voice"] = {"sample_url": str(voice.get("sample_url") or voice.get("sample_mp3") or voice.get("wav") or ""),
                  "suggested": str(voice.get("suggested") or voice.get("label") or voice.get("id") or ""),
                  **({"transcript": str(voice["transcript"])} if voice.get("transcript") else {}),
                  **({"speed": voice["recommended_speed"]} if voice.get("recommended_speed") else {})}
    k["grade"] = str(k.get("grade") or "warm-doc")
    return k


def for_job(inp: dict) -> dict:
    """
    The kit a job asked for: its own inline "presenter_kit"; else "presenter_id" in the catalogue the job
    brings ("presenter_catalogue": the object, or "presenter_catalogue_url": an https link); else in the
    worker's catalogues. "presenter_base_url" (or the catalogue's "base_url") makes relative picture paths links.
    """
    base = str(inp.get("presenter_base_url") or "")
    inline = inp.get("presenter_kit")
    if isinstance(inline, dict) and inline:
        return normalize(dict(inline, base_url=inline.get("base_url") or base) if base else inline)
    wanted = str(inp.get("presenter_id") or inp.get("presenter") or "").strip()
    own = inp.get("presenter_catalogue")
    url = str(inp.get("presenter_catalogue_url") or "").strip()
    if isinstance(own, (dict, list)) or url.startswith("https://"):
        rows = _entries(own, base_url=base) if isinstance(own, (dict, list)) else _load_url(url)
        if base:
            rows = [dict(r, base_url=r.get("base_url") or base) for r in rows]
        mine = {kit_id(r): r for r in rows}
        if wanted in mine:
            return normalize(mine[wanted])
        if not wanted and len(mine) == 1:
            return normalize(next(iter(mine.values())))
    kits = catalogue()
    if not wanted:
        if len(kits) == 1:
            return normalize(next(iter(kits.values())))
        raise KitError("the AI presenter style needs a presenter: send presenter_id (or presenter_kit)")
    if wanted not in kits:
        kits = catalogue(refresh=True)
    if wanted not in kits:
        raise KitError(f"unknown presenter '{wanted}' (known: {', '.join(sorted(kits)) or 'none'})")
    return normalize(kits[wanted])


def _local_name(url: str, folder: str) -> str:
    ext = os.path.splitext(url.split("?")[0])[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".wav", ".mp3", ".m4a"):
        ext = ".jpg"
    return os.path.join(folder, hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ext)


def link(kit: dict, ref: str) -> str:
    """The kit picture as an https link a provider can fetch ("" when it is only a file here)."""
    if ref.startswith("https://"):
        return ref
    base_url = str(kit.get("base_url") or "")
    if base_url.startswith("https://") and not ref.startswith(("http://", "file://")) and not os.path.isabs(ref):
        return urljoin(base_url if base_url.endswith("/") else base_url + "/", ref.lstrip("/"))
    return ""


def fetch(kit: dict, ref: str, folder: str, timeout: float = 60.0) -> str:
    """One of the kit's files on this disk (downloaded once per job folder); raises KitError when it cannot be had."""
    os.makedirs(folder, exist_ok=True)
    base = str(kit.get("_base") or HERE)
    ref = link(kit, ref) or ref
    if ref.startswith(("http://", "https://")):
        out = _local_name(ref, folder)
        with _lock_for(out):                    # one download per file: the other takes wait for it
            if os.path.isfile(out) and os.path.getsize(out) > 0:
                return out
            try:
                r = requests.get(ref, timeout=timeout)
            except requests.RequestException as e:
                raise KitError(f"kit picture unreachable: {type(e).__name__}") from e
            if r.status_code != 200 or len(r.content) < 1000:
                raise KitError(f"kit picture answered HTTP {r.status_code}")
            _write_whole(out, r.content)
        return out
    path = ref[7:] if ref.startswith("file://") else ref
    if not os.path.isabs(path):
        path = os.path.join(base, path)
    if not os.path.isfile(path):
        raise KitError(f"kit file missing: {os.path.basename(path)}")
    out = _local_name(os.path.abspath(path), folder)
    with _lock_for(out):
        if not os.path.isfile(out):
            tmp = f"{out}.{threading.get_ident()}.part"
            shutil.copyfile(path, tmp)
            os.replace(tmp, out)
    return out


_FETCHING: Dict[str, threading.Lock] = {}


def _lock_for(path: str) -> threading.Lock:
    with _LOCK:
        return _FETCHING.setdefault(os.path.abspath(path), threading.Lock())


def _write_whole(out: str, data: bytes) -> None:
    """The file appears whole or not at all: the presenter's takes run in parallel, and one that found another's
    half-written master read a broken PNG (the hybrid laptop test, 2026-10-07)."""
    tmp = f"{out}.{threading.get_ident()}.part"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, out)


def framing(kit: dict, framing_id: str) -> Optional[dict]:
    return next((f for f in kit.get("framings") or [] if f["id"] == framing_id), None)


def other_framing(kit: dict, framing_id: str) -> Optional[dict]:
    """A different framing of the same kit (the retry's), None when the kit has only one."""
    rest = [f for f in kit.get("framings") or [] if f["id"] != framing_id]
    return rest[0] if rest else None


def public_summary(kit: dict) -> Dict[str, Any]:
    """What the plan's meta and the app keep about the kit (no local paths)."""
    out = {"id": kit["id"], "name": kit["name"], "title": kit.get("title", ""), "synthetic": kit.get("synthetic", True),
           "framings": [f["id"] for f in kit.get("framings") or []], "sets": [s["id"] for s in kit.get("sets") or []]}
    if isinstance(kit.get("filming_set"), dict):
        out["filmingSet"] = {k: kit["filming_set"].get(k) for k in ("id", "label", "how")}
    return out
