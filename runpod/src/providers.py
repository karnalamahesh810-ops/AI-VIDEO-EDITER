"""
The footage providers as one registry, in the order a scene tries them.

Each provider is an adapter over a retrieval function that already exists
in media.py (YouTube, Dailymotion, web video, NASA, Wikimedia, archive.org,
Pexels, Pixabay, the image sources, generated stills); nothing about how a
source is searched or downloaded changes here. What the registry adds is
the shape: every source declares what it returns (footage or stills), its
licence class, and when it applies (YouTube-only jobs, Creative Commons
only, stock allowed, a named person, a preference for generated stills),
and `source_one` walks the list. Adding a source is one entry, and a job
can be told which sources it may use.

Adapters look the functions up on media at call time, so a test that
patches media.youtube_clip still drives the registry.
"""
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from . import config


@dataclass
class SourceContext:
    query: str
    seconds: float
    work_dir: str
    visual_type: str = "footage"       # what the director wants: footage | image
    nth: int = 0
    used: Optional[set] = None
    prompt: str = ""
    allow_youtube: bool = True
    allow_stock: bool = False
    require_cc: bool = False
    intent: str = ""
    context: str = ""
    subject: str = ""
    subject_type: str = ""
    youtube_only: bool = False
    tried_generation: bool = False
    enabled_names: Optional[set] = None  # a job's allow-list, or None for all

    @property
    def person(self) -> bool:
        return self.subject_type == "person"

    @property
    def wants_footage(self) -> bool:
        return self.visual_type == "footage"


@dataclass
class Provider:
    name: str
    kind: str                       # "footage" | "image"
    licence: str                    # "unverified" | "cc" | "public-domain" | "stock" | "generated"
    applies: Callable[[SourceContext], bool]
    find: Callable[[SourceContext], Optional[object]]
    note: str = ""


def _m():
    from . import media
    return media


# ------------------------------------------------------------- adapters
def _youtube(ctx: SourceContext):
    m = _m()
    return m.youtube_clip(ctx.query, ctx.work_dir, seconds=ctx.seconds, require_cc=ctx.require_cc,
                          skip=ctx.nth, start_at=30.0 + 25.0 * ctx.nth, used=ctx.used,
                          intent=ctx.intent, context=ctx.context, subject=ctx.subject)


def _dailymotion(ctx: SourceContext):
    m = _m()
    return m.dailymotion_clip(ctx.query, ctx.work_dir, seconds=ctx.seconds, skip=ctx.nth,
                              used=ctx.used, intent=ctx.intent, context=ctx.context,
                              subject=ctx.subject)


def _web_video(ctx: SourceContext):
    m = _m()
    return m.web_video_clip(ctx.query, ctx.work_dir, seconds=ctx.seconds, used=ctx.used,
                            intent=ctx.intent, context=ctx.context)


def _archive_video(search_name: str):
    def find(ctx: SourceContext):
        m = _m()
        found = m._cached_search(getattr(m, search_name), ctx.query, key=search_name)
        ordered = found[ctx.nth:] + found[:ctx.nth] if found else []
        return m._pick_unused(ordered, ctx.used, ctx.query, ctx.work_dir, ctx.intent, ctx.context)
    return find


def _stock(search_name: str, kind: str):
    def find(ctx: SourceContext):
        m = _m()
        fn = getattr(m, search_name)
        found = m._cached_search(lambda q: fn(q, kind=kind), ctx.query, key=f"{search_name}:{kind}")
        if kind == "video":
            found = [c for c in found if c.duration >= ctx.seconds * 0.8]
        return m._pick_unused(found[ctx.nth:] + found[:ctx.nth], ctx.used, ctx.query,
                              ctx.work_dir, ctx.intent, ctx.context)
    return find


def _generated_first(ctx: SourceContext):
    m = _m()
    ctx.tried_generation = True
    if m._generation_budget_left():
        return m.generate_image(ctx.prompt or ctx.query, ctx.work_dir)
    return None


def _generated_last(ctx: SourceContext):
    m = _m()
    if m._generation_budget_left():
        return m.generate_image(ctx.prompt or ctx.query, ctx.work_dir)
    return None


def _wikipedia_article(ctx: SourceContext):
    m = _m()
    found = m._cached_search(m.search_wikipedia_article_images, ctx.subject, key="wikipedia_article")
    ordered = found[ctx.nth:] + found[:ctx.nth] if found else []
    return m._pick_unused(ordered, ctx.used, ctx.subject, ctx.work_dir, ctx.intent, ctx.context)


def _image_search(search_name: str):
    def find(ctx: SourceContext):
        m = _m()
        found = m._cached_search(getattr(m, search_name), ctx.query, key=search_name)
        ordered = found[ctx.nth:] + found[:ctx.nth] if found else []
        return m._pick_unused(ordered, ctx.used, ctx.query, ctx.work_dir, ctx.intent, ctx.context)
    return find


# ------------------------------------------------------------- the list
def _footage(ctx: SourceContext) -> bool:
    return ctx.wants_footage


def _image(ctx: SourceContext) -> bool:
    return not ctx.wants_footage


REGISTRY: List[Provider] = [
    Provider("youtube", "footage", "unverified",
             lambda c: c.wants_footage and c.allow_youtube, _youtube,
             "yt-dlp range download, storyboard moments, the candidate pool"),
    Provider("dailymotion", "footage", "unverified",
             lambda c: c.wants_footage and config.ALLOW_DAILYMOTION and not c.require_cc, _dailymotion),
    Provider("web_video", "footage", "unverified",
             lambda c: c.wants_footage and config.ALLOW_WEB_VIDEO and not c.require_cc, _web_video,
             "TikTok, Facebook, Vimeo and news sites from Google's video search"),
    Provider("nasa_video", "footage", "public-domain", _footage, _archive_video("search_nasa_video")),
    Provider("wikimedia_video", "footage", "cc", _footage, _archive_video("search_wikimedia_video")),
    Provider("archive_org_video", "footage", "public-domain",
             lambda c: c.wants_footage and config.ALLOW_ARCHIVE_ORG, _archive_video("search_archive_org_video")),
    Provider("pexels_video", "footage", "stock",
             lambda c: c.wants_footage and c.allow_stock, _stock("search_pexels", "video")),
    Provider("pixabay_video", "footage", "stock",
             lambda c: c.wants_footage and c.allow_stock, _stock("search_pixabay", "video")),
    Provider("generated_first", "image", "generated",
             lambda c: config.PREFER_GENERATED_IMAGES and not c.person, _generated_first,
             "only when generated stills are preferred; never a real person"),
    Provider("wikipedia_article", "image", "cc",
             lambda c: bool(c.subject) and c.subject_type in ("person", "place", "event"), _wikipedia_article,
             "the named subject's own article: real photos of exactly that subject"),
    Provider("web_images", "image", "unverified", lambda c: True, _image_search("search_web_images")),
    Provider("wikimedia_images", "image", "cc", lambda c: True, _image_search("search_wikimedia")),
    Provider("nasa_images", "image", "public-domain", lambda c: True, _image_search("search_nasa")),
    Provider("openverse", "image", "cc", lambda c: True, _image_search("search_openverse")),
    Provider("pexels_images", "image", "stock", lambda c: c.allow_stock, _stock("search_pexels", "image")),
    Provider("pixabay_images", "image", "stock", lambda c: c.allow_stock, _stock("search_pixabay", "image")),
    # A still nothing was found for tries moving footage of the same thing.
    Provider("youtube_for_stills", "footage", "unverified",
             lambda c: not c.wants_footage and c.allow_youtube, _youtube),
    Provider("dailymotion_for_stills", "footage", "unverified",
             lambda c: not c.wants_footage and config.ALLOW_DAILYMOTION and not c.require_cc, _dailymotion),
    Provider("generated_last", "image", "generated",
             lambda c: not c.tried_generation and not c.person, _generated_last,
             "an illustration for a beat nothing real covers; always fresh"),
]


def ordered(ctx: SourceContext) -> List[Provider]:
    """The providers that apply to this scene, in order."""
    out = []
    for p in REGISTRY:
        if ctx.enabled_names is not None and p.name not in ctx.enabled_names:
            continue
        if ctx.youtube_only and p.name != "youtube":
            continue
        if p.applies(ctx):
            out.append(p)
    return out


def source_one(ctx: SourceContext):
    """
    The first provider that finds a usable asset for the scene, in registry
    order. `applies` is asked as each provider's turn comes, because an
    earlier one can change the context (a generated still tried early is
    not tried again at the end).
    """
    for p in REGISTRY:
        if ctx.enabled_names is not None and p.name not in ctx.enabled_names:
            continue
        if ctx.youtube_only and p.name != "youtube":
            continue
        if not p.applies(ctx):
            continue
        asset = p.find(ctx)
        if asset:
            return asset
    return None


def describe() -> List[dict]:
    return [{"name": p.name, "kind": p.kind, "licence": p.licence, "note": p.note} for p in REGISTRY]
