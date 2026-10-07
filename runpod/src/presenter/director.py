"""
The AI presenter style's planner call: one model reads the narration and, for
every beat, says what it is (hook, chapter opening, "why it matters", close),
how much it wants the presenter on camera, how much its picture must move,
whether the presenter should be in the b-roll doing it, and writes the
prompts - the still (a documentary photograph of the line, in the story's
world) and the motion (a camera move and what moves, for image-to-video). It
also writes the video's style bible: place, era, season, light, palette and
lens, so every still and clip looks like one shoot.

The rules in shotplan.rule_note stand in when there is no key, no budget or
no answer; the shot planner enforces the tier's shares and the shot lengths
whatever the model says. Chunks of CHUNK beats, the first one first (its
bible goes to the others), the rest in parallel. Costs go to the ledger as
llm.presenter_plan.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .. import costs
from . import shotplan, tiers
from .budget import Budget, BudgetExceeded
from .providers import Provider, ProviderError

CHUNK = 50
CALL_USD = 0.08          # what one planning call may cost at most (gpt-5.2, ~50 lines, low effort)

SYSTEM = """You direct videos for a YouTube channel hosted by an AI presenter: a made-up person who talks to camera from \
one believable place, cut with b-roll that shows what they talk about. Everything you write becomes a prompt for a \
photorealistic image model or an image-to-video model, so be concrete and visual. Reply with JSON only."""

INSTRUCTIONS = """For the narration beats below write:

"bible": the look every picture shares - {"place": where the story's pictures are (region, kind of place), "era": \
time period, "season": season and weather, "light": the light, "palette": the colours, "lens": camera and lens \
(documentary, eye level), "people": who appears in b-roll besides the presenter (age, dress), or "none"}.

"beats": one object per beat, same "i":
  "role": "hook" (the opening lines), "chapter" (opens a new part or step), "why" (the key point, why it matters, \
a warning or a personal memory), "close" (the last lines, the sign-off) or "body".
  "fit": 0-1, how much this line should be said by the presenter ON CAMERA (hook, chapter openings, key points, \
personal memories, asking the viewer something, the sign-off: high; describing objects, places, steps: low).
  "move": 0-1, how much its picture must MOVE to make sense (pouring, steam, smoke, flowing water, weather, \
crowds, hands at work: high; objects, rooms, landscapes, food at rest: low).
  "me": true when the b-roll should show the presenter themself doing or remembering it (their own hands, \
their own kitchen, "my mama taught me"), else false.
  "still": ONE photograph that shows this line literally - the thing the sentence is about (its noun), or hands \
doing the step in close-up - 15-35 words: the subject, what is happening, the setting in the bible's world, the \
framing (wide / medium / close-up / overhead) and the light. A candid, lived-in snapshot (used pots, clutter, real \
wear), not a glossy studio shot. A "before" line and its "after" line are a matching pair of the same place. Write \
"the presenter" only when "me" is true (that picture is drawn from their portrait); otherwise show hands, objects, \
places, or people far away or from behind - never another recognisable face. Never a collage, never a diagram.
  "alt": a second, clearly different photograph for the same line (another angle, a closer detail, the result).
  "motion": for image-to-video, 10-25 words: one slow camera move (push in, pull back, pan, tilt, gentle handheld \
drift) and what moves naturally in the scene (steam rises, leaves sway, dust drifts in the light). Nothing new \
enters the frame, nothing morphs, no fast action.

Rules for every picture: no brand names or logos (packaging plain and generic, labels turned away or out of \
focus), no readable signs, captions or screens; no famous people; strangers seen at a distance, from behind or out \
of focus rather than as close-up faces; hands natural and relaxed. Keep the bible's place, era and season unless a \
line clearly names another one."""


def _beat_rows(beats: Sequence[shotplan.Beat]) -> List[Dict[str, Any]]:
    return [{"i": b.index, "t": round(b.start, 1), "s": round(b.seconds, 1), "text": b.text} for b in beats]


def _parse(text: str) -> Optional[dict]:
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        got = json.loads(t)
    except ValueError:
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            return None
        try:
            got = json.loads(m.group(0))
        except ValueError:
            return None
    return got if isinstance(got, dict) else None


def _num(v: Any, default: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, x))


def _note(row: dict, base: shotplan.Note) -> shotplan.Note:
    role = str(row.get("role") or base.role).strip().lower()
    if role not in ("hook", "chapter", "why", "close", "body"):
        role = base.role
    return shotplan.Note(role=role, presenter_fit=_num(row.get("fit"), base.presenter_fit),
                         needs_motion=_num(row.get("move"), base.needs_motion),
                         in_shot=bool(row.get("me")) if row.get("me") is not None else base.in_shot,
                         still=str(row.get("still") or "").strip()[:400],
                         alt=str(row.get("alt") or "").strip()[:400],
                         motion=str(row.get("motion") or "").strip()[:300])


def default_bible(kit: dict) -> Dict[str, str]:
    w = kit.get("world") or {}
    return {"place": w.get("place") or "", "era": w.get("era") or "present day", "season": "",
            "light": w.get("light") or "soft natural daylight", "palette": w.get("palette") or "natural, slightly warm colours",
            "lens": w.get("lens") or "candid camera at eye level, 35-50mm lens", "people": ""}


def _ask(provider: Provider, budget: Budget, title: str, kit: dict, rows: List[dict],
         bible: Optional[dict], models: Sequence[str], cache: Optional[str] = None
         ) -> Tuple[Optional[dict], Optional[str]]:
    payload = {"title": title, "presenter": {"who": kit.get("persona"), "wardrobe": kit.get("wardrobe"),
                                             "world": kit.get("world")},
               "beats": rows}
    if bible:
        payload["bible_to_keep"] = bible
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": INSTRUCTIONS + "\n\n" + json.dumps(payload, ensure_ascii=False)}]
    # The same request answered before (a re-run of a failed job): the same answer, so every prompt - and every
    # paid picture and clip cached under its prompt (src/presenter/store.py Cache) - comes back the same.
    key = hashlib.sha256(json.dumps([list(models), messages], sort_keys=True).encode("utf-8")).hexdigest()[:32]
    cached = os.path.join(cache, f"plan_{key}.json") if cache else ""
    if cached and os.path.isfile(cached):
        try:
            with open(cached, encoding="utf-8") as fh:
                got = json.load(fh)
            if isinstance(got, dict) and isinstance(got.get("beats"), list):
                print("[presenter] planner answer from the cache", flush=True)
                return got, None
        except (OSError, ValueError):
            pass
    last = None
    for model in models:
        try:
            ticket = budget.reserve(CALL_USD, f"plan:{model}")
        except BudgetExceeded as e:
            return None, str(e)
        try:
            res = provider.chat(model, messages, json_mode=True, max_tokens=max(2500, 260 * len(rows)),
                                reasoning_effort="low", timeout=240)
        except ProviderError as e:
            budget.release(ticket, str(e))
            last = str(e)
            print(f"[presenter] planner {model} failed: {str(e)[:160]}", flush=True)
            continue
        usd = budget.settle(ticket, res.cost, model=model, kind="plan", seconds=res.seconds)
        costs.record("llm.usd", usd)
        costs.record("llm.presenter_plan.usd", usd)
        costs.record("llm.presenter_plan.calls")
        got = _parse(res.text)
        if got and isinstance(got.get("beats"), list):
            if cached:
                try:
                    os.makedirs(cache, exist_ok=True)
                    with open(cached, "w", encoding="utf-8") as fh:
                        json.dump(got, fh)
                except OSError:
                    pass
            return got, None
        last = f"{model}: answer was not the JSON asked for"
        print(f"[presenter] planner {last}", flush=True)
    return None, last


def annotate(beats: Sequence[shotplan.Beat], *, title: str, kit: dict, provider: Optional[Provider],
             budget: Budget, models: Optional[Sequence[str]] = None, cache: Optional[str] = None) -> Dict[str, Any]:
    """
    {"notes": [Note per beat], "bible": {...}, "planner": "model id" | "rules", "errors": [...]}.
    A beat the model left out keeps the rules' note; a chunk the model failed is all rules.
    """
    rules = [shotplan.rule_note(b.text, b.index, len(beats)) for b in beats]
    out: Dict[str, Any] = {"notes": list(rules), "bible": default_bible(kit), "planner": "rules", "errors": []}
    if not beats or provider is None or not provider.available():
        return out
    models = list(models or [tiers.DIRECTOR_MODEL] + tiers.DIRECTOR_FALLBACK_MODELS)
    rows = _beat_rows(beats)
    chunks = [rows[k:k + CHUNK] for k in range(0, len(rows), CHUNK)]
    first, err = _ask(provider, budget, title, kit, chunks[0], None, models, cache)
    answers = [first]
    if err:
        out["errors"].append(err)
    bible = None
    if first and isinstance(first.get("bible"), dict):
        bible = {k: str(v)[:200] for k, v in first["bible"].items() if isinstance(k, str)}
    if len(chunks) > 1:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futs = [pool.submit(_ask, provider, budget, title, kit, c, bible, models, cache) for c in chunks[1:]]
            for f in futs:
                got, e = f.result()
                answers.append(got)
                if e:
                    out["errors"].append(e)
    by_index: Dict[int, dict] = {}
    for ans in answers:
        for row in (ans or {}).get("beats") or []:
            if isinstance(row, dict):
                try:
                    by_index[int(row.get("i"))] = row
                except (TypeError, ValueError):
                    continue
    if by_index:
        out["planner"] = models[0]
        out["notes"] = [_note(by_index[b.index], rules[k]) if b.index in by_index else rules[k]
                        for k, b in enumerate(beats)]
        # The first and last beats keep their places whatever the model said.
        out["notes"][0].role = "hook"
        if len(beats) > 1:
            out["notes"][-1].role = "close"
    if bible:
        out["bible"] = {**out["bible"], **{k: v for k, v in bible.items() if v}}
    out["covered"] = len(by_index)
    return out


def bible_line(bible: Dict[str, str]) -> str:
    """The style bible as one sentence every picture prompt starts from."""
    parts = []
    if bible.get("place"):
        parts.append(f"Setting: {bible['place']}")
    if bible.get("era"):
        parts.append(f"era: {bible['era']}")
    if bible.get("season"):
        parts.append(f"season and weather: {bible['season']}")
    if bible.get("light"):
        parts.append(f"light: {bible['light']}")
    if bible.get("palette"):
        parts.append(f"colours: {bible['palette']}")
    return "; ".join(parts) + "." if parts else ""
