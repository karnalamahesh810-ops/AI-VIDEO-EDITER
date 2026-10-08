"""
How the presenter moves: the text that goes with every heygen/avatar-iv call.

What avatar-iv takes on OpenRouter (GET /api/v1/videos/models, read
2026-10-08, and HeyGen's own Avatar IV docs):
  * prompt; resolution 720p | 1080p; aspect_ratio 16:9 | 9:16 | 1:1;
  * input_references: one picture (https link or data: URL) and one
    audio_url (https only) - the clip is as long as the audio; no seed, no
    duration, no frame images, generate_audio false;
  * provider passthrough (provider.options.heygen; OpenRouter's
    allowed_passthrough_parameters): motion_prompt (natural language for
    body motion and hand gestures), expressiveness (low | medium | high:
    energy and range of movement, HeyGen's default low), fit (cover |
    contain), remove_background, background, caption, title, and voice_id /
    voice_settings (HeyGen's own text-to-speech: never used - our narration
    is the voice, the only sound of the video).

What is sent (for_shot):
  motion_prompt  a calm, natural default (the owner, 2026-10-08: eyes, face
                 and hands better): steady eye contact, natural blinking,
                 small nods and tilts, a relaxed face, the hands resting and
                 lifting now and then into a small gesture at chest height
                 (a close-up keeps them below the frame), nothing fast or
                 repetitive, never near the face; plus one or two lines for
                 the line's tone - the opening (an engaged nod), the sign-off
                 (a warm smile), a question (a tilt, raised eyebrows),
                 emphasis (a slight lean and a firm nod), a serious line
                 (steady, no smile), a memory (a glance aside and back), a
                 list (one small gesture a point).
  expressiveness low: HeyGen's own default (PRESENTER_EXPRESSIVENESS=medium
                 raises the main camera's; a close-up, a serious line and a
                 selfie stay low; a kit's own avatar.expressiveness wins).
                 Measured 2026-10-08 (Hollis, library set, the owner's voice):
                 medium moved the head ~35% and the hands ~2x more than the
                 old takes, but the eyes were shut or squinting in about a
                 quarter of the frames and the face check failed the take -
                 so the default stays low and the prompt asks for open eyes
                 and quick blinks; medium waits for an A/B.
  prompt         who talks, where (the set they are filmed in) and how.
A kit's own avatar.prompt / avatar.motion_prompt (the app may send them)
replace the defaults; the tone lines are still added to its motion prompt.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional

EXPRESSIVENESS = ("low", "medium", "high")
DEFAULT_EXPRESSIVENESS = (os.getenv("PRESENTER_EXPRESSIVENESS", "low").strip().lower() or "low")
if DEFAULT_EXPRESSIVENESS not in EXPRESSIVENESS:
    DEFAULT_EXPRESSIVENESS = "low"

_CALM = ("Eyes open, bright and engaged, looking into the lens; quick, natural blinks every few seconds, never held "
         "shut, no squinting; subtle head movement - small nods and slight tilts on the stressed words; a relaxed face "
         "with gentle eyebrow movement that follows the voice.")
MEDIUM = ("Natural, calm talking-to-camera delivery. " + _CALM + " The hands rest where they are and now and then "
          "lift into a small, calm gesture at chest height, then settle again. No fast, sudden or repetitive "
          "movement; the hands never come near the face; shoulders relaxed. Locked-off tripod camera; the background "
          "stays still.")
CLOSE = ("Natural, calm talking-to-camera delivery in a close-up. " + _CALM + " The hands stay below the frame. No "
         "fast, sudden or repetitive movement. Locked-off tripod camera; the background stays still.")
SELFIE = ("Handheld phone selfie: the phone sways gently in the hand. Eyes open and on the lens with quick, natural "
          "blinks, small head movements and a relaxed face; the free hand stays out of frame; nothing fast or "
          "repetitive; the room behind stays still.")

TONE_LINES = {
    "hook": "Open with an engaged, confident look and one small nod, as if greeting the viewer.",
    "close": "Finish with a warm, genuine smile, the eyes still open on the lens, and a small nod.",
    "close_serious": "Finish with a calm, sincere look and a small nod.",
    "question": "On the question, a slight head tilt and raised eyebrows, then the eyes stay on the lens.",
    "emphasis": "On the key phrase, a slight lean toward the camera and one firm nod.",
    "serious": "A serious, steady expression; slower, smaller movements; no smile.",
    "story": "A thoughtful look; the eyes may drift aside briefly on the memory, then come back to the lens.",
    "list": "As each point is named, one small, calm hand gesture at chest height.",
    "list_close": "A small nod as each point is named.",
}
MANNER = {"serious": "seriously and calmly", "close": "warmly", "hook": "warmly and with confidence",
          "question": "warmly and calmly", "emphasis": "with calm conviction", "story": "warmly, remembering",
          "list": "clearly and calmly", "plain": "warmly and calmly"}

_SERIOUS = re.compile(
    r"\b(died|dies|dead|death|deaths|killed|kill|murder\w*|tragedy|tragic|warning|danger|dangerous|deadly|disaster|"
    r"destroyed|devastat\w*|crisis|victims?|emergency|collapse\w*|grief|funeral|lost everything|never again|"
    r"cancer|war|attack\w*)\b", re.I)
_EMPHASIS = re.compile(
    r"(!|\b(never|always|most important|the truth|remember|listen|here'?s the thing|the secret|the key|biggest|"
    r"worst|best|every single|absolutely|exactly|must|critical|crucial|do not|don'?t ever|trust me|single most)\b)",
    re.I)
_STORY = re.compile(r"\b(i remember|when i was|years ago|back in|my (father|mother|dad|mom|grand\w+|late)|used to|"
                    r"once upon|growing up|as a (boy|girl|kid|child))\b", re.I)
_LIST = re.compile(r"^\s*(first(ly)?|second(ly)?|third(ly)?|next|finally|lastly|number (one|two|three|four|five|\d+)|"
                   r"step (one|two|three|four|five|\d+))\b", re.I)


def tone_of(text: str, role: str = "") -> Dict[str, str]:
    """{"role": hook | close | "", "tone": serious | question | emphasis | story | list | plain} for one line."""
    t = str(text or "")
    r = role if role in ("hook", "close") else ""
    if _SERIOUS.search(t):
        tone = "serious"
    elif "?" in t:
        tone = "question"
    elif _STORY.search(t):
        tone = "story"
    elif _EMPHASIS.search(t) or any(len(w) > 2 and w.isupper() and w.isalpha() for w in t.split()):
        tone = "emphasis"
    elif _LIST.search(t):
        tone = "list"
    else:
        tone = "plain"
    return {"role": r, "tone": tone}


def is_close(framing: Optional[dict], framing_id: str = "") -> bool:
    """A close-up camera (the hands stay below the frame)."""
    f = framing or {}
    words = f"{framing_id} {f.get('id') or ''} {f.get('shot') or ''}".lower()
    return "close" in words


def _who(kit: dict) -> str:
    """Who talks and where: the kit's persona in its own set; the name and the set it is filmed in otherwise (the
    persona names the home room, which a set replaces)."""
    name = str(kit.get("name") or "The presenter").strip()
    where = str(kit.get("set_where") or "").strip()
    if where:
        return f"{name} {where}"
    return str(kit.get("persona") or name).strip()


def for_shot(kit: dict, text: str = "", role: str = "", framing: Optional[dict] = None,
             framing_id: str = "") -> Dict[str, Any]:
    """{"prompt", "motion_prompt", "expressiveness", "tone"} for one presenter take."""
    avatar = kit.get("avatar") if isinstance(kit.get("avatar"), dict) else {}
    selfie = "selfie" in str(kit.get("style") or "").lower() or bool(avatar.get("selfie"))
    close = is_close(framing, framing_id)
    tone = tone_of(text, role)
    if avatar.get("custom_motion") and avatar.get("motion_prompt"):
        base = str(avatar["motion_prompt"]).strip()
    else:
        base = SELFIE if selfie else (CLOSE if close else MEDIUM)
    lines = []
    if tone["role"] == "hook":
        lines.append(TONE_LINES["hook"])
    if tone["tone"] in ("question", "emphasis", "story", "serious"):
        lines.append(TONE_LINES[tone["tone"]])
    elif tone["tone"] == "list":
        lines.append(TONE_LINES["list_close" if (close or selfie) else "list"])
    if tone["role"] == "close":
        lines.append(TONE_LINES["close_serious" if tone["tone"] == "serious" else "close"])
    motion_prompt = " ".join([base] + lines)
    if avatar.get("expressiveness") in EXPRESSIVENESS:
        expressiveness = str(avatar["expressiveness"])
    elif close or selfie or tone["tone"] == "serious":
        expressiveness = "low"
    else:
        expressiveness = DEFAULT_EXPRESSIVENESS
    if avatar.get("custom_prompt") and avatar.get("prompt"):
        prompt = str(avatar["prompt"]).strip()
    else:
        manner = MANNER.get(tone["tone"] if tone["tone"] != "plain" else (tone["role"] or "plain"), MANNER["plain"])
        prompt = (f"{_who(kit)} talks {manner} straight to the camera. Natural, subtle head movement and natural "
                  "blinking, realistic lip sync. Static camera, still background.")
    return {"prompt": prompt, "motion_prompt": motion_prompt, "expressiveness": expressiveness,
            "tone": tone["tone"], "role": tone["role"], "close": close}
