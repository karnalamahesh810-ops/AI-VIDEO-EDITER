"""
Who is talking in a clip, for the reference's caption colours.

Celebs Goat colours each SPEAKER's captions (measured on B4rM / r2op / UjOJ, celeb-elements.md section 13):
the first voice heard in a clip is yellow #FCFF04, the second white #FFFFFF, a third green #31FF03
(B4rM: Kimmel yellow, Tom white; a fan yellow, Tom white. r2op cold open: John yellow, Emily green).

How: one speaker embedding per caption phrase (WeSpeaker ResNet34 on VoxCeleb through sherpa-onnx, local,
free; the model is CC BY 4.0, fetched once into models/), clustered greedily by cosine similarity. A phrase too
short to judge keeps the previous phrase's speaker unless a camera cut sits between them (the face-on-screen cue:
a new shot with no clear voice evidence is not taken as a speaker change by itself, and vice versa).
"""
import os
import subprocess
from typing import List, Optional, Sequence, Tuple

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(HERE, "models", "wespeaker_en_voxceleb_resnet34_LM.onnx")
MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
             "wespeaker_en_voxceleb_resnet34_LM.onnx")
COLOURS = [(252, 255, 4, 255), (255, 255, 255, 255), (49, 255, 3, 255)]
SAME = 0.42          # cosine similarity above which two phrases are the same voice (r2op eval: best)
MIN_S = 0.7          # shorter phrases are judged with their neighbours' context

_extractor = None


def available() -> bool:
    try:
        import sherpa_onnx  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    if not os.path.isfile(MODEL):
        try:
            import requests
            os.makedirs(os.path.dirname(MODEL), exist_ok=True)
            r = requests.get(MODEL_URL, timeout=120)
            r.raise_for_status()
            with open(MODEL, "wb") as fh:
                fh.write(r.content)
        except Exception:  # noqa: BLE001
            return False
    return True


def _ext():
    global _extractor
    if _extractor is None:
        import sherpa_onnx
        _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=MODEL, num_threads=4))
    return _extractor


def _audio(path: str, a: float, b: float) -> np.ndarray:
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, a):.3f}", "-t", f"{b - a:.3f}", "-i", path,
                        "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True, timeout=120)
    return np.frombuffer(p.stdout, np.float32)


def embed(path: str, a: float, b: float) -> Optional[np.ndarray]:
    if b - a < MIN_S:                                   # widen a short phrase symmetrically
        pad = (MIN_S - (b - a)) / 2
        a, b = a - pad, b + pad
    x = _audio(path, a, b)
    if len(x) < 16000 * 0.4:
        return None
    e = _ext()
    s = e.create_stream()
    s.accept_waveform(16000, x)
    s.input_finished()
    if not e.is_ready(s):
        return None
    v = np.array(e.compute(s), np.float32)
    n = np.linalg.norm(v)
    return v / n if n else None


def _kmeans(X: np.ndarray, k: int, iters: int = 20) -> np.ndarray:
    """Spherical k-means, seeded with the most dissimilar phrases."""
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


SPLIT = 0.80         # two voice groups whose centroids are less similar than this are two speakers


def assign(embs: Sequence[Optional[np.ndarray]], cut_before: Sequence[bool], max_speakers: int = 3) -> List[int]:
    """
    Speaker index per phrase (0 = first voice heard). Clip audio carries laughs and music, so absolute
    similarities run high (0.5-0.8 between two different actors on these reels): the phrases are split into
    2 (or 3) groups and the split is kept only when the groups' centroids differ enough and each group has
    at least two phrases. Phrases without an embedding take their neighbour's speaker.
    """
    idx = [i for i, e in enumerate(embs) if e is not None]
    lab = {i: 0 for i in idx}
    if len(idx) >= 4:
        X = np.stack([embs[i] for i in idx])
        best = None
        for k in range(2, max_speakers + 1):
            if len(idx) < 2 * k:
                break
            l = _kmeans(X, k)
            sizes = [int((l == j).sum()) for j in range(k)]
            cents = [X[l == j].mean(axis=0) for j in range(k)]
            cents = [c / (np.linalg.norm(c) or 1) for c in cents]
            worst = max(float(cents[x] @ cents[y]) for x in range(k) for y in range(x + 1, k))
            if min(sizes) >= 2 and worst < SPLIT:
                best = l
            else:
                break
        if best is not None:
            lab = {i: int(v) for i, v in zip(idx, best)}
    out: List[int] = []
    for i in range(len(embs)):
        if i in lab:
            out.append(lab[i])
        else:
            out.append(out[-1] if out else 0)
    order: List[int] = []                       # renumber by first appearance: first voice = 0 = yellow
    for v in out:
        if v not in order:
            order.append(v)
    return [order.index(v) for v in out]


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


def colour_phrases(path: str, src_in: float, phrases: Sequence[Tuple[float, float, str]], offset: float,
                   cuts: Sequence[float]) -> List[Tuple[float, float, str, tuple]]:
    """(start, end, text) on the output clock -> + colour, judged per speaker TURN on the clip's own audio."""
    if not phrases:
        return []
    if not available():
        return [(a, b, t, COLOURS[0]) for a, b, t in phrases]
    groups = turns_of(phrases)
    embs, cut_before = [], []
    prev_end = None
    for g in groups:
        sa = phrases[g[0]][0] - offset + src_in
        sb = phrases[g[-1]][1] - offset + src_in
        embs.append(embed(path, sa, sb))
        cut_before.append(prev_end is not None and any(prev_end <= c <= sa + 0.05 for c in cuts))
        prev_end = sb
    who_turn = assign(embs, cut_before)
    who = [0] * len(phrases)
    for g, w in zip(groups, who_turn):
        for i in g:
            who[i] = w
    return [(a, b, t, COLOURS[min(w, len(COLOURS) - 1)]) for (a, b, t), w in zip(phrases, who)]
