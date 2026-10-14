"""
Who is talking in a clip, for the reference's caption colours.

Celebs Goat colours captions by WHO is talking (measured on B4rM / r2op / UjOJ, celeb-elements.md section 13,
re-measured 2026-10-15 from the reference frames): the featured celebrity WHITE #FFFFFF, everyone else (host,
interviewer, fan, co-star) YELLOW #FCFF04, green #31FF03 rare (3 of 885 lines). B4rM: Tom Holland white in 50 of
58 clips, also when he speaks first or alone. So: one voice -> all white; several voices -> the celebrity's voice
white and the rest yellow (roles()); a clip we cannot judge stays white. The editor's click-to-cycle is the fix.

How (2026-10-15 bake-off on 885 caption lines of the three refs, ground truth read from the reference frames,
scratchpad diar/): one speaker embedding per speaker TURN (phrases that run on without a sentence end or a
pause) with 3D-Speaker ERes2Net trained on VoxCeleb (Apache-2.0, 26 MB, sherpa-onnx, local, free), taken from
the clip's audio decoded once. The turns are split into 2 (or 3) voices by spherical k-means and the split is
kept only when it is clearly real: mean same-group cosine minus mean cross-group cosine above GAP and every
group at least MIN_TURNS turns. On these clips music, laughter and crowd noise sit under short lines, so a
doubtful split costs more than it gains; when the evidence is weak the clip stays one voice.

Pairwise same/different-speaker agreement (old WeSpeaker k-means -> this): B4rM 66.6 -> 74.0 %, r2op 73.7 ->
85.9 %, UjOJ 67.0 -> 73.8 %. Tried and not used: vocal separation first (Spleeter, separate.py; no gain on
these clips, kept behind CELEB_SPEAKER_VOCALS=1), sherpa OfflineSpeakerDiarization (pyannote segmentation 3.0;
good on r2op, worse than one-voice on B4rM / UjOJ), WeSpeaker ResNet34, CAM++, NeMo TitaNet, average-linkage
clustering, voice-gated embeddings, and the camera-cut cue (a cut barely changes the odds of a new speaker:
P(switch | cut) 0.16-0.30 vs 0.13-0.16 without).

Exact colour with this WHO rule (old order rule -> this): B4rM 26 -> 82 %, r2op 74 -> 17 %, UjOJ 72 -> 22 %.
r2op and UjOJ are mostly yellow in the reference (the clips' main voice there is the co-star / an unnamed
actor), so "the most speech is the celebrity" fails on them; only a real identity signal (the named person's
face or voice) would fix that. Picking the celebrity's voice by speech share only acts on lopsided splits
(CONF); a face cue was not built because the diarizer splits 1 of 58 B4rM clips, so it could not move the score.
"""
import hashlib
import os
import re
import threading
from typing import List, Optional, Sequence, Tuple, Union

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
BAKED = os.getenv("CELEB_MODELS_DIR", "/opt/models/celeb")
LOCAL = os.path.join(HERE, "models")
MODEL_NAME = "3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx"
MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/" + MODEL_NAME)
MODEL_SHA256 = "c59158379255ad66e161679cca6af8d52d51e389e3224ab7d7a7baae295c2db5"
COLOURS = [(252, 255, 4, 255), (255, 255, 255, 255), (49, 255, 3, 255)]
SR = 16000
GAP = 0.20           # same-group minus cross-group cosine needed to keep a split (0.15-0.30 measured equal)
MIN_TURNS = 2        # each voice needs at least this many turns
MAX_SPEAKERS = 3
MIN_S = 0.7          # shorter turns are widened symmetrically before embedding
USE_VOCALS = os.getenv("CELEB_SPEAKER_VOCALS", "") == "1"
YELLOW, WHITE, GREEN = 0, 1, 2   # indices into COLOURS (the lead maps names by index)
CONF = 0.70          # the celebrity's voice must hold this share of the clip's speech, else the clip stays white
GREEN_THIRD = False  # a third voice in green: off (3 green lines in 885 measured; a guess there costs more)

_extractor = None
_lock = threading.Lock()


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def model_path() -> Optional[str]:
    """The verified embedding model: baked into the image, or fetched once into models/ (never committed)."""
    for d in (BAKED, LOCAL):
        p = os.path.join(d, MODEL_NAME)
        if os.path.isfile(p):
            return p
    try:
        import requests
        r = requests.get(MODEL_URL, timeout=180)
        r.raise_for_status()
        if hashlib.sha256(r.content).hexdigest() != MODEL_SHA256:
            return None
        os.makedirs(LOCAL, exist_ok=True)
        p = os.path.join(LOCAL, MODEL_NAME)
        with open(p + ".part", "wb") as fh:
            fh.write(r.content)
        os.replace(p + ".part", p)
        return p
    except Exception:  # noqa: BLE001
        return None


def available() -> bool:
    try:
        import sherpa_onnx  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return model_path() is not None


def _ext():
    global _extractor
    with _lock:
        if _extractor is None:
            import sherpa_onnx
            _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=model_path(), num_threads=max(1, min(4, os.cpu_count() or 1))))
        return _extractor


def embed_array(x: np.ndarray, a: float, b: float) -> Optional[np.ndarray]:
    """Unit-length voice embedding of x[a:b] (seconds, 16 kHz mono); None when too short to judge."""
    if b - a < MIN_S:
        pad = (MIN_S - (b - a)) / 2
        a, b = a - pad, b + pad
    seg = x[int(max(0.0, a) * SR):int(max(0.0, b) * SR)]
    if len(seg) < SR * 0.4:
        return None
    e = _ext()
    s = e.create_stream()
    s.accept_waveform(SR, np.ascontiguousarray(seg, dtype=np.float32))
    s.input_finished()
    if not e.is_ready(s):
        return None
    v = np.array(e.compute(s), np.float32)
    n = np.linalg.norm(v)
    return v / n if n else None


def _kmeans(X: np.ndarray, k: int, iters: int = 20) -> np.ndarray:
    """Spherical k-means, seeded with the most dissimilar items."""
    seeds = [0]
    for _ in range(1, k):
        sims = X @ X[seeds].T
        seeds.append(int(np.argmin(sims.max(axis=1))))
    C = X[seeds].copy()
    lab = np.zeros(len(X), int)
    for _ in range(iters):
        lab = np.argmax(X @ C.T, axis=1)
        for j in range(k):
            if (lab == j).any():
                c = X[lab == j].sum(axis=0)
                C[j] = c / (np.linalg.norm(c) or 1)
    return lab


def separation(X: np.ndarray, lab: Sequence[int]) -> float:
    """Mean same-group cosine minus mean cross-group cosine (-1 when either set of pairs is empty)."""
    S = X @ X.T
    iu = np.triu_indices(len(X), 1)
    same = np.asarray(lab)[iu[0]] == np.asarray(lab)[iu[1]]
    vals = S[iu]
    if not same.any() or same.all():
        return -1.0
    return float(vals[same].mean() - vals[~same].mean())


def renumber(labels: Sequence[int]) -> List[int]:
    """Speaker ids by first appearance: the first voice heard is 0 (yellow)."""
    order: List[int] = []
    for v in labels:
        if v not in order:
            order.append(v)
    return [order.index(v) for v in labels]


def assign(embs: Sequence[Optional[np.ndarray]], gap: float = GAP, min_turns: int = MIN_TURNS,
           max_speakers: int = MAX_SPEAKERS) -> List[int]:
    """
    Speaker index per turn (0 = first voice heard). Turns without an embedding take the previous turn's speaker
    (the next one's when they open the clip). One voice unless a 2- (then 3-) way split is clearly separated.
    """
    idx = [i for i, e in enumerate(embs) if e is not None]
    lab = {i: 0 for i in idx}
    if len(idx) >= 2 * min_turns:
        X = np.stack([embs[i] for i in idx])
        best = None
        for k in range(2, max_speakers + 1):
            if len(idx) < k * min_turns:
                break
            l = _kmeans(X, k)
            if min(int((l == j).sum()) for j in range(k)) < min_turns or separation(X, l) <= gap:
                break
            best = l
        if best is not None:
            lab = {i: int(v) for i, v in zip(idx, best)}
    out: List[Optional[int]] = []
    for i in range(len(embs)):
        out.append(lab[i] if i in lab else (out[-1] if out else None))
    first = next((v for v in out if v is not None), 0)
    return renumber([first if v is None else v for v in out])


def turns_of(phrases: Sequence[Tuple[float, float, str]]) -> List[List[int]]:
    """Phrases that continue one sentence without a pause belong to one speaker turn."""
    out: List[List[int]] = []
    for i, (a, b, t) in enumerate(phrases):
        if out:
            pa, pb, pt = phrases[out[-1][-1]]
            if pt.strip()[-1:] not in ".?!" and a - pb < 0.35:
                out[-1].append(i)
                continue
        out.append([i])
    return out


def speaker_index(colour: Union[Sequence[int], str, None]) -> int:
    """0 / 1 / 2 for a caption colour from COLOURS (RGB or RGBA tuple, or '#RRGGBB'); unknown reads as 0."""
    if isinstance(colour, str):
        h = colour.strip().lstrip("#")
        try:
            rgb = tuple(int(h[k:k + 2], 16) for k in (0, 2, 4)) if len(h) >= 6 else ()
        except ValueError:
            rgb = ()
    else:
        rgb = tuple(int(v) for v in (colour or ()))[:3]
    for k, c in enumerate(COLOURS):
        if tuple(c[:3]) == rgb:
            return k
    return 0


def _clip_audio(path: str, a: float, b: float) -> np.ndarray:
    from . import separate
    if USE_VOCALS:
        v = separate.vocals(path, a, b)
        if v is not None:
            return v
    return separate.mix(path, a, b)


def _name_tokens(featured: str) -> List[str]:
    return [w for w in re.findall(r"[a-z']+", (featured or "").lower()) if len(w) >= 3]


def mentions(text: str, featured: str) -> bool:
    """The line says the featured person's first or last name (then it is usually someone else talking)."""
    toks = _name_tokens(featured)
    words = set(re.findall(r"[a-z']+", (text or "").lower()))
    return any(t in words for t in toks)


def roles(voice: Sequence[int], secs: Sequence[float], texts: Sequence[str], featured: str = "",
          conf: Optional[float] = None) -> List[int]:
    """
    Colour index per turn under the reference's WHO rule: the featured celebrity WHITE, everyone else YELLOW
    (a third voice GREEN only with GREEN_THIRD). One voice -> all white. With several voices the celebrity is the
    voice with the most speech, after discounting turns that say the featured name; when that voice holds less
    than `conf` of the speech the clip is not judged and stays all white.
    """
    conf = CONF if conf is None else conf
    n = len(voice)
    if n == 0:
        return []
    ids = sorted(set(voice))
    if len(ids) == 1:
        return [WHITE] * n
    score = {v: 0.0 for v in ids}
    for v, s, t in zip(voice, secs, texts):
        score[v] += -max(0.0, s) if featured and mentions(t, featured) else max(0.0, s)
    total = sum(max(0.0, s) for s in secs) or 1.0
    star = max(ids, key=lambda v: (score[v], -ids.index(v)))
    if score[star] / total < conf:
        return [WHITE] * n
    others = [v for v in ids if v != star]
    out = []
    for v in voice:
        if v == star:
            out.append(WHITE)
        elif GREEN_THIRD and len(others) > 1 and v == others[-1]:
            out.append(GREEN)
        else:
            out.append(YELLOW)
    return out


def colour_phrases(path: str, src_in: float, phrases: Sequence[Tuple[float, float, str]], offset: float,
                   cuts: Sequence[float], featured: str = "") -> List[Tuple[float, float, str, tuple]]:
    """(start, end, text) on the output clock -> + colour, judged per speaker TURN on the clip's own audio.
    `featured` is the clip spot's first `who` name (the celebrity: white; everyone else yellow). `cuts` (source
    shot cuts) is accepted for the caller's sake; it measured as no help (see the module doc)."""
    if not phrases:
        return []
    if not available():
        return [(a, b, t, COLOURS[WHITE]) for a, b, t in phrases]
    groups = turns_of(phrases)
    shift = src_in - offset                          # output clock -> source clock
    a0 = max(0.0, min(p[0] for p in phrases) + shift - 0.5)
    b0 = max(p[1] for p in phrases) + shift + 0.5
    try:
        x = _clip_audio(path, a0, b0)
        embs = [embed_array(x, phrases[g[0]][0] + shift - a0, phrases[g[-1]][1] + shift - a0) for g in groups]
    except Exception:  # noqa: BLE001
        return [(a, b, t, COLOURS[WHITE]) for a, b, t in phrases]
    voice = assign(embs)
    secs = [sum(phrases[i][1] - phrases[i][0] for i in g) for g in groups]
    texts = [" ".join(phrases[i][2] for i in g) for g in groups]
    colour_turn = roles(voice, secs, texts, featured)
    col = [WHITE] * len(phrases)
    for g, c in zip(groups, colour_turn):
        for i in g:
            col[i] = c
    return [(a, b, t, COLOURS[c]) for (a, b, t), c in zip(phrases, col)]
