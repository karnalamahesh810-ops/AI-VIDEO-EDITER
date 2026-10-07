"""
The script preset for the AI presenter style: the template the owner's six
reference channels share (docs/ai-avatar-reference-analysis-2026-10-07.md,
sections 6.3-6.4). The worker does not write scripts - the app's script
generation does - so this is data the app reads (handler action
"presenter_info") to brief its script model, plus the presenter cues the
shot planner already follows (the opening line, the name line, each item's
first sentence and the close go to the presenter).
"""
from __future__ import annotations

PRESET = {
    "id": "ai_presenter_elder",
    "label": "AI presenter: old-wisdom story",
    "wordsPerMinute": 175,
    "voice": ("First person, as the presenter. No contractions (\"I am\", \"it is\", \"do not\"). Sentences of 8-16 "
              "words, plain words, one regional word every ~300 words, a concrete number (a price, a year, an amount) "
              "every ~100 words. No \"in this video we will\", no hype adjectives."),
    "inputs": ["persona name", "age", "county and state", "years doing it", "trade",
               "two named relatives with one detail each", "a proverb", "a sign-off motto",
               "topic", "number of items N", "the user's own product or link (optional)"],
    "sections": [
        {"id": "story", "words": 110, "presenter": "the first sentence",
         "brief": "Cold open: put the viewer in front of the mistake right now, or a 3-sentence story with a price, a "
                  "time and a place. Show what the mistake costs. Reframe it: \"It is not X. It is Y.\""},
        {"id": "who", "words": 90, "presenter": "the name line",
         "brief": "Name, age, county and state, years doing it; the relative who taught me, with a year and a number; "
                  "why I am filming (a family member set up the camera; I want it written down)."},
        {"id": "roadmap", "words": 60, "presenter": "the whole roadmap",
         "brief": "Announce the N parts and name them briefly; promise the last one is the one almost nobody does, "
                  "and hold it back."},
        {"id": "plug", "words": 60, "optional": True, "presenter": "none",
         "brief": "Once, only when the user gave a product or link: the full method is in [product] at [link]; "
                  "then move on and never repeat it."},
        {"id": "items", "words": "250-400 each", "presenter": "each item's first sentence",
         "brief": "Items 1..N-1: the step with exact amounts; why it works in plain kitchen science; a family "
                  "anecdote; the common wrong way; one safety line where it matters; a one-line bridge that teases "
                  "the next item."},
        {"id": "secret", "words": 400, "presenter": "the proverb",
         "brief": "Item N, the saved secret: the payoff, and the relative's proverb."},
        {"id": "close", "words": 120, "presenter": "the whole close",
         "brief": "One specific question for the comments; ask the viewer's county and promise to read every "
                  "comment; tease the next video with a concrete object; the presenter's own sign-off motto."},
    ],
    "length": "words = minutes x 175 (a one-trick video: 11-21 min, 2,000-3,500 words)",
    "guardrails": ["The presenter is a made-up person: never claim a real religious community or a real biography.",
                   "No medical, financial or legal advice; household tips with the safety lines the topic needs.",
                   "Generic product names, never real brands."],
}
