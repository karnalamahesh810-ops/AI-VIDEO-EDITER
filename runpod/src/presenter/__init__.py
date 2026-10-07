"""
The AI presenter video style ("ai_presenter"): a made-up presenter who talks
to camera (HeyGen Avatar IV, lip-synced to the job's own voice track), cut
with AI stills that move and AI video clips, all through OpenRouter.

  tiers.py      the tiers (shares of screen time, models) as configuration
  kits.py       presenter kits: master portrait, framings, sets (a JSON catalogue)
  shotplan.py   which lines are presenter / AI video / still, to the tier's shares
  director.py   the planner model's notes: roles, prompts, the style bible
  providers.py  OpenRouter (and a slot for Algrow's REST API)
  generate.py   making every shot: async, bounded, checked, retried, with fallbacks
  checks.py     length / frozen / black, the face against the master, AI giveaways
  budget.py     the job's hard spending cap; store.py: R2 + the paid-call cache
  assemble.py   the timeline document (the worker's own renderer and editor)
  estimate.py   $ and minutes per 10/15/20-minute video per tier, for the app
  pipeline.py   plan(): the whole style for a plan/build job

Docs: docs/ai-avatar-style-plan-2026-10-07.md (models, costs) and
docs/ai-avatar-reference-analysis-2026-10-07.md (what the reference videos do).
"""
from __future__ import annotations

from typing import Any, Dict

STYLE = "ai_presenter"


def is_presenter(inp: Dict[str, Any]) -> bool:
    """A job whose video style is the AI presenter's."""
    from .. import styles
    return styles.resolve((inp or {}).get("video_style")) == STYLE


def plan(inp: Dict[str, Any], work: str, report, narrate=None) -> Dict[str, Any]:
    from . import pipeline
    return pipeline.plan(inp, work, report, narrate=narrate)


def info() -> Dict[str, Any]:
    from . import pipeline
    return pipeline.info()
